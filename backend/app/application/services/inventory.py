import hashlib
import ipaddress
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.inventory import (
    CMDBRecordModel,
    InventoryAssetModel,
    InventoryConflictModel,
    InventoryCorrelationModel,
    InventoryDependencyModel,
    InventoryIdentityModel,
    InventoryObservationModel,
    InventoryServiceModel,
    PrometheusConfigurationModel,
)

IDENTITY_PRIORITY = (
    "cloud_instance_id",
    "serial_number",
    "asset_tag",
    "fqdn",
    "alias",
    "hostname",
    "ip_address",
)
CMDB_FIELDS = (
    "source_record_key",
    "hostname",
    "fqdn",
    "primary_ip",
    "additional_ips",
    "asset_type",
    "environment",
    "operating_system",
    "application",
    "business_owner",
    "technical_owner",
    "location",
    "serial_number",
    "asset_tag",
    "cloud_provider",
    "cloud_instance_id",
    "lifecycle_status",
    "description",
    "aliases",
)
IDENTITY_FIELDS = (
    "cloud_instance_id",
    "serial_number",
    "asset_tag",
    "fqdn",
    "hostname",
    "primary_ip",
)


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_hostname(value: object, *, fqdn: bool = False) -> tuple[str | None, str | None]:
    display = clean_text(value)
    if display is None:
        return None, None
    comparison = display.rstrip(".").casefold()
    if not comparison or any(character.isspace() for character in comparison):
        return display, None
    if fqdn and "." not in comparison:
        return display, None
    if not fqdn and "." in comparison:
        comparison = comparison.split(".", 1)[0]
    return display.rstrip("."), comparison


def normalize_ip(value: object) -> tuple[str | None, str | None]:
    display = clean_text(value)
    if display is None:
        return None, None
    try:
        normalized = str(ipaddress.ip_address(display.strip("[]")))
    except ValueError:
        return display, None
    return display, normalized


def normalize_identifier(value: object, identity_type: str) -> tuple[str | None, str | None]:
    display = clean_text(value)
    if display is None:
        return None, None
    if identity_type in {"cloud_instance_id", "asset_tag"}:
        return display, display.casefold()
    return display, display


def split_addresses(value: object) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        text = clean_text(value)
        values = [] if text is None else text.replace(";", ",").split(",")
    normalized: list[str] = []
    for item in values:
        _, address = normalize_ip(item)
        if address and address not in normalized:
            normalized.append(address)
    return normalized


def split_aliases(value: object) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        text = clean_text(value)
        values = [] if text is None else text.replace(";", ",").split(",")
    return list(dict.fromkeys(item.strip() for item in values if str(item).strip()))


def endpoint_identity(value: object) -> tuple[str | None, str | None]:
    text = clean_text(value)
    if not text:
        return None, None
    candidate = text if "://" in text else f"target://{text}"
    parsed = urlparse(candidate)
    host = parsed.hostname
    if not host:
        return None, None
    _, ip = normalize_ip(host)
    if ip:
        return "ip_address", ip
    _, fqdn = normalize_hostname(host, fqdn=True)
    if fqdn:
        return "fqdn", fqdn
    _, hostname = normalize_hostname(host)
    return ("hostname", hostname) if hostname else (None, None)


def normalize_cmdb_row(
    raw: dict[str, object], mapping: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    mapped: dict[str, object] = {}
    for source_column, field in mapping.items():
        if field in CMDB_FIELDS and field not in mapped:
            mapped[field] = raw.get(source_column)
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    for field in CMDB_FIELDS:
        value = mapped.get(field)
        if field == "hostname":
            display, comparison = normalize_hostname(value)
            normalized[field] = display
            normalized["hostname_normalized"] = comparison
        elif field == "fqdn":
            display, comparison = normalize_hostname(value, fqdn=True)
            normalized[field] = display
            normalized["fqdn_normalized"] = comparison
            if clean_text(value) and not comparison:
                errors.append("fqdn is not a fully qualified hostname")
        elif field == "primary_ip":
            display, comparison = normalize_ip(value)
            normalized[field] = display
            normalized["primary_ip_normalized"] = comparison
            if clean_text(value) and not comparison:
                errors.append("primary_ip is invalid")
        elif field == "additional_ips":
            normalized[field] = split_addresses(value)
        elif field == "aliases":
            normalized[field] = split_aliases(value)
        else:
            normalized[field] = clean_text(value)
    if not any(normalized.get(field) for field in IDENTITY_FIELDS):
        errors.append("at least one usable identity field is required")
    return normalized, errors


def row_checksum(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def identities_from_fields(fields: dict[str, Any]) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for identity_type, field in (
        ("cloud_instance_id", "cloud_instance_id"),
        ("serial_number", "serial_number"),
        ("asset_tag", "asset_tag"),
        ("fqdn", "fqdn"),
        ("hostname", "hostname"),
        ("ip_address", "primary_ip"),
    ):
        original = clean_text(fields.get(field))
        if not original:
            continue
        if identity_type == "fqdn":
            _, normalized = normalize_hostname(original, fqdn=True)
        elif identity_type == "hostname":
            _, normalized = normalize_hostname(original)
        elif identity_type == "ip_address":
            _, normalized = normalize_ip(original)
        else:
            _, normalized = normalize_identifier(original, identity_type)
        if normalized:
            results.append((identity_type, original, normalized))
    for address in split_addresses(fields.get("additional_ips")):
        results.append(("ip_address", address, address))
    for alias in split_aliases(fields.get("aliases")):
        _, normalized_ip = normalize_ip(alias)
        if normalized_ip:
            results.append(("alias", alias, normalized_ip))
            continue
        _, normalized_host = endpoint_identity(alias)
        if normalized_host:
            results.append(("alias", alias, normalized_host))
    return list(dict.fromkeys(results))


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest_cmdb_record(self, record: CMDBRecordModel) -> InventoryObservationModel:
        now = datetime.now(UTC)
        fields = record.normalized_fields_json
        source_record_id = str(record.id)
        observation = await self.session.scalar(
            select(InventoryObservationModel).where(
                InventoryObservationModel.source_type == "cmdb",
                InventoryObservationModel.source_record_id == source_record_id,
            )
        )
        if observation is None:
            observation = InventoryObservationModel(
                source_type="cmdb",
                source_record_id=source_record_id,
                observed_fields_json=fields,
                raw_reference=(f"cmdb:{record.dataset_version_id}:row:{record.source_row_number}"),
                raw_checksum=record.row_checksum,
                observed_at=now,
                first_seen_at=now,
                last_seen_at=now,
                confidence=1.0,
            )
            self.session.add(observation)
            await self.session.flush()
        identities = identities_from_fields(fields)
        asset, method, ambiguity = await self._find_asset(identities)
        if asset is None:
            asset = self._new_asset(fields, now)
            self.session.add(asset)
            await self.session.flush()
            method = (
                "conflicting_identity_new_asset"
                if ambiguity
                else identities[0][0]
                if identities
                else "new_asset"
            )
        observation.asset_id = asset.id if asset else None
        observation.status = "ambiguous" if ambiguity else "observed"
        await self._replace_identities(observation, asset, identities)
        self.session.add(
            InventoryCorrelationModel(
                observation_id=observation.id,
                asset_id=asset.id if asset else None,
                match_method=method or "ambiguous_identity",
                confidence=1.0 if asset else 0.0,
                decision_type="automatic",
                status="proposed" if ambiguity else "matched",
            )
        )
        await self._merge_cmdb_fields(asset, observation, fields, now)
        if ambiguity:
            self.session.add(
                InventoryConflictModel(
                    asset_id=asset.id,
                    observation_id=observation.id,
                    field_name="identity",
                    source_values_json={"cmdb": [item[2] for item in identities]},
                    resolution_status="open",
                )
            )
        return observation

    async def correlate_prometheus(
        self,
        observation: InventoryObservationModel,
        identities: list[tuple[str, str, str]],
    ) -> None:
        manual = await self.session.scalar(
            select(InventoryCorrelationModel)
            .where(
                InventoryCorrelationModel.observation_id == observation.id,
                InventoryCorrelationModel.decision_type == "manual",
            )
            .order_by(InventoryCorrelationModel.created_at.desc())
            .limit(1)
        )
        if manual:
            observation.asset_id = manual.asset_id if manual.status == "matched" else None
            observation.status = "observed" if manual.status == "matched" else "unmatched"
            await self._replace_identities(observation, None, identities)
            return
        candidates: dict[UUID, set[str]] = {}
        candidate_priority: int | None = None
        for priority, identity_type in enumerate(IDENTITY_PRIORITY):
            values = (
                {normalized for _, _, normalized in identities}
                if identity_type == "alias"
                else {
                    normalized
                    for kind, _, normalized in identities
                    if kind == identity_type
                }
            )
            for normalized in values:
                rows = await self.session.execute(
                    select(InventoryIdentityModel.asset_id).where(
                        InventoryIdentityModel.identity_type == identity_type,
                        InventoryIdentityModel.normalized_value == normalized,
                        InventoryIdentityModel.asset_id.is_not(None),
                        InventoryIdentityModel.source_type == "cmdb",
                    )
                )
                for asset_id in rows.scalars():
                    if asset_id:
                        candidates.setdefault(asset_id, set()).add(identity_type)
            if candidates:
                candidate_priority = priority
                break
        all_exact: dict[str, set[UUID]] = {}
        for kind in (*IDENTITY_PRIORITY,):
            values = (
                {normalized for _, _, normalized in identities}
                if kind == "alias"
                else {
                    normalized
                    for identity_type, _, normalized in identities
                    if identity_type == kind
                }
            )
            if not values:
                continue
            scalar_rows = await self.session.scalars(
                select(InventoryIdentityModel.asset_id).where(
                    InventoryIdentityModel.identity_type == kind,
                    InventoryIdentityModel.normalized_value.in_(values),
                    InventoryIdentityModel.asset_id.is_not(None),
                    InventoryIdentityModel.source_type == "cmdb",
                )
            )
            all_exact[kind] = {item for item in scalar_rows.all() if item}
        # A unique strong identity must not be invalidated by a weaker shared
        # address. For example, many exporters can share a host IP while an
        # instance_name FQDN still identifies exactly one CMDB asset. Conflicts
        # between strong identifiers remain ambiguous.
        conflict_ceiling = (
            max(candidate_priority, IDENTITY_PRIORITY.index("fqdn"))
            if candidate_priority is not None
            else len(IDENTITY_PRIORITY) - 1
        )
        nonempty = [
            values
            for priority, kind in enumerate(IDENTITY_PRIORITY)
            if priority <= conflict_ceiling
            and (values := all_exact.get(kind, set()))
        ]
        conflicting = len({asset_id for values in nonempty for asset_id in values}) > 1
        if len(candidates) == 1 and not conflicting:
            asset_id = next(iter(candidates))
            method = next(iter(candidates[asset_id]))
            observation.asset_id = asset_id
            observation.status = "observed"
            status = "matched"
            confidence = 1.0
        else:
            asset_id = None
            method = "conflicting_identity" if conflicting else "ambiguous_or_unmatched"
            observation.asset_id = None
            observation.status = "ambiguous" if candidates or conflicting else "unmatched"
            status = "proposed" if candidates or conflicting else "rejected"
            confidence = 0.0
        await self._replace_identities(observation, None, identities)
        self.session.add(
            InventoryCorrelationModel(
                observation_id=observation.id,
                asset_id=asset_id,
                match_method=method,
                confidence=confidence,
                decision_type="automatic",
                status=status,
            )
        )
        if conflicting or len(candidates) > 1:
            self.session.add(
                InventoryConflictModel(
                    asset_id=asset_id,
                    observation_id=observation.id,
                    field_name="identity",
                    source_values_json={
                        kind: [str(value) for value in values]
                        for kind, values in all_exact.items()
                        if values
                    },
                )
            )

    async def sync_prometheus_topology(
        self,
        observation: InventoryObservationModel,
        configuration: PrometheusConfigurationModel,
        target: dict[str, Any],
    ) -> None:
        if observation.asset_id is None:
            return
        scrape_url = clean_text(target.get("scrapeUrl"))
        if not scrape_url:
            return
        parsed = urlparse(scrape_url)
        if not parsed.hostname:
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target_labels = target.get("labels")
        labels: dict[str, Any] = target_labels if isinstance(target_labels, dict) else {}
        job = str(labels.get("job") or "").casefold()
        service_type = self._service_type(port, job)
        now = datetime.now(UTC)
        service = await self.session.scalar(
            select(InventoryServiceModel).where(
                InventoryServiceModel.observation_id == observation.id,
                InventoryServiceModel.protocol == (parsed.scheme or "http"),
                InventoryServiceModel.port == port,
                InventoryServiceModel.path == (parsed.path or "/"),
            )
        )
        if service is None:
            service = InventoryServiceModel(
                asset_id=observation.asset_id,
                observation_id=observation.id,
                service_type=service_type,
                name=service_type.replace("_", " ").title(),
                protocol=parsed.scheme or "http",
                port=port,
                path=parsed.path or "/",
                endpoint=scrape_url,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(service)
        else:
            service.asset_id = observation.asset_id
            service.service_type = service_type
            service.endpoint = scrape_url
            service.last_seen_at = now

        await self._upsert_dependency(
            observation,
            "scraped_by",
            configuration.base_url,
            f"Prometheus active target in configuration {configuration.name}",
            now,
        )
        global_url = clean_text(target.get("globalUrl"))
        if global_url:
            global_host = urlparse(global_url).hostname
            if global_host and global_host.casefold() != parsed.hostname.casefold():
                await self._upsert_dependency(
                    observation,
                    "reverse_proxied_by",
                    global_url,
                    "Prometheus global URL host differs from the scrape URL host",
                    now,
                )

    async def _upsert_dependency(
        self,
        observation: InventoryObservationModel,
        relation_type: str,
        target_reference: str,
        evidence: str,
        now: datetime,
    ) -> None:
        assert observation.asset_id is not None
        dependency = await self.session.scalar(
            select(InventoryDependencyModel).where(
                InventoryDependencyModel.source_asset_id == observation.asset_id,
                InventoryDependencyModel.source_observation_id == observation.id,
                InventoryDependencyModel.relation_type == relation_type,
                InventoryDependencyModel.target_reference == target_reference,
            )
        )
        if dependency is None:
            self.session.add(
                InventoryDependencyModel(
                    source_asset_id=observation.asset_id,
                    source_observation_id=observation.id,
                    relation_type=relation_type,
                    target_reference=target_reference,
                    evidence=evidence,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        else:
            dependency.last_seen_at = now
            dependency.evidence = evidence

    @staticmethod
    def _service_type(port: int, job: str) -> str:
        hints = (
            ("windows_exporter", ("windows",), (9182,)),
            ("process_exporter", ("process",), (9256,)),
            ("node_exporter", ("node",), (9100,)),
            ("prometheus", ("prometheus",), (9090,)),
            ("loki", ("loki",), (3100,)),
        )
        for service_type, job_hints, ports in hints:
            if port in ports or any(hint in job for hint in job_hints):
                return service_type
        return "metrics_endpoint"

    async def _find_asset(
        self, identities: list[tuple[str, str, str]]
    ) -> tuple[InventoryAssetModel | None, str | None, bool]:
        matches: dict[UUID, set[str]] = {}
        for identity_type in IDENTITY_PRIORITY:
            values = [item[2] for item in identities if item[0] == identity_type]
            if not values:
                continue
            rows = await self.session.execute(
                select(InventoryIdentityModel.asset_id).where(
                    InventoryIdentityModel.identity_type == identity_type,
                    InventoryIdentityModel.normalized_value.in_(values),
                    InventoryIdentityModel.asset_id.is_not(None),
                )
            )
            ids = {item for item in rows.scalars() if item}
            for match_id in ids:
                matches.setdefault(match_id, set()).add(identity_type)
        if len(matches) != 1:
            return None, None, len(matches) > 1
        asset_id = next(iter(matches))
        existing = list(
            (
                await self.session.scalars(
                    select(InventoryIdentityModel).where(
                        InventoryIdentityModel.asset_id == asset_id
                    )
                )
            ).all()
        )
        existing_by_type: dict[str, set[str]] = {}
        for existing_identity in existing:
            existing_by_type.setdefault(existing_identity.identity_type, set()).add(
                existing_identity.normalized_value
            )
        for identity_type, _, normalized in identities:
            identity_values = existing_by_type.get(identity_type)
            if identity_values and normalized not in identity_values:
                return None, "conflicting_identity", True
        return (
            await self.session.get(InventoryAssetModel, asset_id),
            next(iter(matches[asset_id])),
            False,
        )

    @staticmethod
    def _new_asset(fields: dict[str, Any], now: datetime) -> InventoryAssetModel:
        canonical = (
            clean_text(fields.get("fqdn"))
            or clean_text(fields.get("hostname"))
            or clean_text(fields.get("cloud_instance_id"))
            or clean_text(fields.get("serial_number"))
            or clean_text(fields.get("asset_tag"))
            or clean_text(fields.get("primary_ip"))
            or "Unnamed asset"
        )
        return InventoryAssetModel(
            canonical_name=canonical,
            first_seen_at=now,
            last_seen_at=now,
            **{
                field: fields.get(field)
                for field in (
                    "hostname",
                    "fqdn",
                    "primary_ip",
                    "asset_type",
                    "environment",
                    "operating_system",
                    "cloud_provider",
                    "cloud_instance_id",
                    "serial_number",
                    "asset_tag",
                    "location",
                    "application",
                    "business_owner",
                    "technical_owner",
                    "lifecycle_status",
                )
            },
            additional_ips_json=split_addresses(fields.get("additional_ips")),
        )

    async def _replace_identities(
        self,
        observation: InventoryObservationModel,
        asset: InventoryAssetModel | None,
        identities: list[tuple[str, str, str]],
    ) -> None:
        existing = list(
            (
                await self.session.scalars(
                    select(InventoryIdentityModel).where(
                        InventoryIdentityModel.observation_id == observation.id
                    )
                )
            ).all()
        )
        known = {(item.identity_type, item.normalized_value): item for item in existing}
        now = datetime.now(UTC)
        pending: set[tuple[str, str]] = set()
        for identity_type, original, normalized in identities:
            key = (identity_type, normalized)
            if key in pending:
                continue
            pending.add(key)
            item = known.get(key)
            if item:
                item.last_seen_at = now
                item.asset_id = observation.asset_id or (asset.id if asset else None)
            else:
                self.session.add(
                    InventoryIdentityModel(
                        asset_id=observation.asset_id or (asset.id if asset else None),
                        observation_id=observation.id,
                        identity_type=identity_type,
                        original_value=original,
                        normalized_value=normalized,
                        source_type=observation.source_type,
                        confidence=1.0,
                    )
                )

    async def _merge_cmdb_fields(
        self,
        asset: InventoryAssetModel,
        observation: InventoryObservationModel,
        fields: dict[str, Any],
        now: datetime,
    ) -> None:
        strong = (
            "cloud_instance_id",
            "serial_number",
            "asset_tag",
            "fqdn",
            "hostname",
            "primary_ip",
        )
        for field in strong:
            old = getattr(asset, field)
            new = clean_text(fields.get(field))
            if old and new:
                old_normalized = identities_from_fields({field: old})
                new_normalized = identities_from_fields({field: new})
                if (
                    old_normalized
                    and new_normalized
                    and old_normalized[0][2] != new_normalized[0][2]
                ):
                    self.session.add(
                        InventoryConflictModel(
                            asset_id=asset.id,
                            observation_id=observation.id,
                            field_name=field,
                            source_values_json={"canonical": old, "cmdb": new},
                        )
                    )
                    continue
            if not old and new:
                setattr(asset, field, new)
        for field in (
            "asset_type",
            "environment",
            "operating_system",
            "cloud_provider",
            "location",
            "application",
            "business_owner",
            "technical_owner",
            "lifecycle_status",
        ):
            value = clean_text(fields.get(field))
            if value:
                setattr(asset, field, value)
        asset.last_seen_at = now
        asset.canonical_name = asset.fqdn or asset.hostname or asset.canonical_name

    async def list_assets(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        coverage: str | None = None,
        environment: str | None = None,
        asset_type: str | None = None,
        lifecycle_status: str | None = None,
        prometheus_health: str | None = None,
        correlation_status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = []
        if search:
            escaped = search.replace("%", "\\%").replace("_", "\\_")
            filters.append(
                or_(
                    InventoryAssetModel.canonical_name.ilike(f"%{escaped}%", escape="\\"),
                    InventoryAssetModel.hostname.ilike(f"%{escaped}%", escape="\\"),
                    InventoryAssetModel.fqdn.ilike(f"%{escaped}%", escape="\\"),
                    InventoryAssetModel.primary_ip.ilike(f"%{escaped}%", escape="\\"),
                )
            )
        if environment:
            filters.append(InventoryAssetModel.environment == environment)
        if asset_type:
            filters.append(InventoryAssetModel.asset_type == asset_type)
        if lifecycle_status:
            filters.append(InventoryAssetModel.lifecycle_status == lifecycle_status)
        assets = list(
            (
                await self.session.scalars(
                    select(InventoryAssetModel)
                    .where(*filters)
                    .order_by(InventoryAssetModel.canonical_name)
                )
            ).all()
        )
        prometheus_configured = bool(
            await self.session.scalar(select(PrometheusConfigurationModel.id).limit(1))
        )
        prometheus_scanned = bool(
            await self.session.scalar(
                select(PrometheusConfigurationModel.id)
                .where(PrometheusConfigurationModel.last_successful_scan_at.is_not(None))
                .limit(1)
            )
        )
        results: list[dict[str, Any]] = []
        for asset in assets:
            observations = list(
                (
                    await self.session.scalars(
                        select(InventoryObservationModel).where(
                            InventoryObservationModel.asset_id == asset.id
                        )
                    )
                ).all()
            )
            sources = {item.source_type for item in observations}
            if {"cmdb", "prometheus"} <= sources:
                state = "Declared and monitored"
            elif "cmdb" in sources and not prometheus_configured:
                state = "Unknown — Prometheus not configured"
            elif "cmdb" in sources and not prometheus_scanned:
                state = "Unknown — Prometheus not scanned"
            elif "cmdb" in sources:
                state = "Declared but not monitored"
            else:
                state = "Observed but missing from CMDB"
            if coverage and coverage != state:
                continue
            prometheus = [item for item in observations if item.source_type == "prometheus"]
            health = (
                "unhealthy"
                if any(item.observed_fields_json.get("health") != "up" for item in prometheus)
                else "healthy"
                if prometheus
                else "not_configured"
                if not prometheus_configured
                else "unknown"
                if not prometheus_scanned
                else "not_observed"
            )
            item_result = {
                "id": asset.id,
                "canonical_name": asset.canonical_name,
                "hostname": asset.hostname,
                "fqdn": asset.fqdn,
                "primary_ip": asset.primary_ip,
                "asset_type": asset.asset_type,
                "environment": asset.environment,
                "lifecycle_status": asset.lifecycle_status,
                "sources": sorted(sources),
                "coverage": state,
                "prometheus_health": health,
                "last_metrics_seen": max((item.last_seen_at for item in prometheus), default=None),
                "correlation_status": "matched",
            }
            if (not prometheus_health or prometheus_health == health) and (
                not correlation_status or correlation_status == "matched"
            ):
                results.append(item_result)
        unmatched = list(
            (
                await self.session.scalars(
                    select(InventoryObservationModel).where(
                        InventoryObservationModel.source_type == "prometheus",
                        InventoryObservationModel.asset_id.is_(None),
                    )
                )
            ).all()
        )
        if not coverage or coverage == "Observed but missing from CMDB":
            for item in unmatched:
                fields = item.observed_fields_json
                item_result = {
                    "id": f"observation:{item.id}",
                    "canonical_name": fields.get("instance")
                    or fields.get("scrape_url")
                    or "Observed target",
                    "hostname": fields.get("hostname"),
                    "fqdn": fields.get("fqdn"),
                    "primary_ip": fields.get("primary_ip"),
                    "asset_type": None,
                    "environment": fields.get("labels", {}).get("environment"),
                    "lifecycle_status": None,
                    "sources": ["prometheus"],
                    "coverage": "Observed but missing from CMDB",
                    "prometheus_health": fields.get("health", "unknown"),
                    "last_metrics_seen": item.last_seen_at,
                    "correlation_status": item.status,
                }
                if (
                    not prometheus_health or prometheus_health == item_result["prometheus_health"]
                ) and (
                    not correlation_status
                    or correlation_status == item_result["correlation_status"]
                ):
                    results.append(item_result)
        total = len(results)
        start = (page - 1) * page_size
        return results[start : start + page_size], total

    @staticmethod
    def _os_condition(os_family: str) -> Any:
        family = os_family.casefold()
        operating_system = func.lower(InventoryAssetModel.operating_system)
        if family == "linux":
            return or_(
                operating_system.contains("linux"),
                operating_system.contains("rhel"),
                operating_system.contains("red hat"),
                operating_system.contains("ubuntu"),
                operating_system.contains("debian"),
                operating_system.contains("centos"),
                operating_system.contains("suse"),
            )
        if family == "windows":
            return operating_system.contains("windows")
        return operating_system.contains(family.replace("%", "\\%").replace("_", "\\_"))

    async def count_assets(self, os_family: str | None = None) -> dict[str, Any]:
        filters: list[Any] = [InventoryAssetModel.retired_at.is_(None)]
        if os_family:
            filters.append(self._os_condition(os_family))
        count = int(
            await self.session.scalar(
                select(func.count(InventoryAssetModel.id)).where(*filters)
            )
            or 0
        )
        return {
            "count": count,
            "filters": {"os_family": os_family} if os_family else {},
            "observed_at": datetime.now(UTC),
        }

    async def inventory_summary(self) -> dict[str, Any]:
        total = await self.count_assets()
        linux = await self.count_assets("linux")
        windows = await self.count_assets("windows")
        return {
            "total_count": total["count"],
            "counts_by_os_family": {
                "linux": linux["count"],
                "windows": windows["count"],
                "other_or_unknown": max(
                    0, total["count"] - linux["count"] - windows["count"]
                ),
            },
            "observed_at": total["observed_at"],
        }

    async def find_assets(
        self,
        *,
        identifier: str | None = None,
        os_family: str | None = None,
        environment: str | None = None,
        missing_prometheus: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        filters: list[Any] = [InventoryAssetModel.retired_at.is_(None)]
        if identifier:
            clean = identifier.strip().rstrip(".").casefold()
            short = clean.split(".", 1)[0]
            filters.append(
                or_(
                    func.lower(InventoryAssetModel.hostname) == short,
                    func.lower(InventoryAssetModel.fqdn) == clean,
                    func.lower(InventoryAssetModel.canonical_name) == clean,
                    func.lower(InventoryAssetModel.canonical_name) == short,
                    InventoryAssetModel.primary_ip == identifier.strip(),
                )
            )
        if os_family:
            filters.append(self._os_condition(os_family))
        if environment:
            filters.append(func.lower(InventoryAssetModel.environment) == environment.casefold())
        assets = list(
            (
                await self.session.scalars(
                    select(InventoryAssetModel)
                    .where(*filters)
                    .order_by(InventoryAssetModel.canonical_name)
                    .limit(limit)
                )
            ).all()
        )
        results: list[dict[str, Any]] = []
        for asset in assets:
            observations = list(
                (
                    await self.session.scalars(
                        select(InventoryObservationModel).where(
                            InventoryObservationModel.asset_id == asset.id
                        )
                    )
                ).all()
            )
            prometheus = [
                item for item in observations if item.source_type == "prometheus"
            ]
            if missing_prometheus is True and prometheus:
                continue
            if missing_prometheus is False and not prometheus:
                continue
            health = (
                "unhealthy"
                if any(item.observed_fields_json.get("health") != "up" for item in prometheus)
                else "healthy"
                if prometheus
                else "unavailable"
            )
            results.append(
                {
                    "id": str(asset.id),
                    "canonical_name": asset.canonical_name,
                    "hostname": asset.hostname,
                    "fqdn": asset.fqdn,
                    "primary_ip": asset.primary_ip,
                    "operating_system": asset.operating_system,
                    "environment": asset.environment,
                    "asset_type": asset.asset_type,
                    "lifecycle_status": asset.lifecycle_status,
                    "prometheus_health": health,
                    "last_observed_at": max(
                        (item.last_seen_at for item in observations), default=None
                    ),
                    "last_metrics_seen_at": max(
                        (item.last_seen_at for item in prometheus), default=None
                    ),
                }
            )
        return results

    async def operational_asset_status(self, asset_id: UUID) -> dict[str, Any] | None:
        asset = await self.session.get(InventoryAssetModel, asset_id)
        if asset is None or asset.retired_at is not None:
            return None
        matches = await self.find_assets(identifier=asset.canonical_name, limit=20)
        item = next((value for value in matches if value["id"] == str(asset.id)), None)
        if item is None:
            return None
        return {
            **item,
            "inventory_status": asset.lifecycle_status or "unknown",
            "reachable": (
                True
                if item["prometheus_health"] == "healthy"
                else False
                if item["prometheus_health"] == "unhealthy"
                else None
            ),
        }

    async def asset_detail(self, asset_id: UUID) -> dict[str, Any] | None:
        asset = await self.session.get(InventoryAssetModel, asset_id)
        if not asset:
            return None
        observations = list(
            (
                await self.session.scalars(
                    select(InventoryObservationModel).where(
                        InventoryObservationModel.asset_id == asset.id
                    )
                )
            ).all()
        )
        identities = list(
            (
                await self.session.scalars(
                    select(InventoryIdentityModel).where(
                        InventoryIdentityModel.asset_id == asset.id
                    )
                )
            ).all()
        )
        conflicts = list(
            (
                await self.session.scalars(
                    select(InventoryConflictModel).where(
                        InventoryConflictModel.asset_id == asset.id
                    )
                )
            ).all()
        )
        services = list(
            (
                await self.session.scalars(
                    select(InventoryServiceModel).where(InventoryServiceModel.asset_id == asset.id)
                )
            ).all()
        )
        dependencies = list(
            (
                await self.session.scalars(
                    select(InventoryDependencyModel).where(
                        InventoryDependencyModel.source_asset_id == asset.id
                    )
                )
            ).all()
        )
        return {
            "asset": {
                column.name: getattr(asset, column.name) for column in asset.__table__.columns
            },
            "observations": [
                {
                    "id": item.id,
                    "source_type": item.source_type,
                    "status": item.status,
                    "observed_fields": item.observed_fields_json,
                    "raw_reference": item.raw_reference,
                    "first_seen_at": item.first_seen_at,
                    "last_seen_at": item.last_seen_at,
                }
                for item in observations
            ],
            "identities": [
                {
                    "identity_type": item.identity_type,
                    "original_value": item.original_value,
                    "normalized_value": item.normalized_value,
                    "source_type": item.source_type,
                }
                for item in identities
            ],
            "conflicts": [
                {
                    "id": item.id,
                    "field_name": item.field_name,
                    "source_values": item.source_values_json,
                    "resolution_status": item.resolution_status,
                }
                for item in conflicts
            ],
            "services": [
                {
                    "id": item.id,
                    "service_type": item.service_type,
                    "name": item.name,
                    "protocol": item.protocol,
                    "port": item.port,
                    "path": item.path,
                    "endpoint": item.endpoint,
                    "first_seen_at": item.first_seen_at,
                    "last_seen_at": item.last_seen_at,
                }
                for item in services
            ],
            "dependencies": [
                {
                    "id": item.id,
                    "relation_type": item.relation_type,
                    "target_asset_id": item.target_asset_id,
                    "target_reference": item.target_reference,
                    "evidence": item.evidence,
                    "first_seen_at": item.first_seen_at,
                    "last_seen_at": item.last_seen_at,
                }
                for item in dependencies
            ],
        }

    async def manual_decision(
        self,
        observation_id: UUID,
        asset_id: UUID | None,
        status: str,
        reviewed_by: UUID,
    ) -> InventoryCorrelationModel:
        observation = await self.session.get(InventoryObservationModel, observation_id)
        if not observation:
            raise ValueError("Observation not found")
        if asset_id and not await self.session.get(InventoryAssetModel, asset_id):
            raise ValueError("Asset not found")
        decision = InventoryCorrelationModel(
            observation_id=observation.id,
            asset_id=asset_id,
            match_method="manual_mapping",
            confidence=1.0 if asset_id else 0.0,
            decision_type="manual",
            status=status,
            reviewed_at=datetime.now(UTC),
            reviewed_by=reviewed_by,
        )
        observation.asset_id = asset_id if status == "matched" else None
        observation.status = "observed" if status == "matched" else "unmatched"
        await self.session.execute(
            update(InventoryIdentityModel)
            .where(InventoryIdentityModel.observation_id == observation.id)
            .values(asset_id=observation.asset_id)
        )
        self.session.add(decision)
        await self.session.commit()
        await self.session.refresh(decision)
        return decision
