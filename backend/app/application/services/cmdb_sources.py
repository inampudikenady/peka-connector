"""Active-source routing for the CMDB stream."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integrations import IntegrationService
from app.application.services.inventory import InventoryService
from app.infrastructure.database.models.servicenow import (
    ServiceNowCIModel,
    ServiceNowRelationshipModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService

SERVER_CLASS_MARKERS = ("server", "computer", "host")


def _is_server_class(value: str | None) -> bool:
    clean = (value or "").casefold().replace("_", " ")
    return any(marker in clean for marker in SERVER_CLASS_MARKERS)


class CMDBSourceService:
    def __init__(self, session: AsyncSession, encryption: SecretEncryptionService) -> None:
        self.session = session
        self.integrations = IntegrationService(session, encryption)
        self.inventory = InventoryService(session)

    async def active_source_key(self) -> str | None:
        active = await self.integrations.active_source("cmdb")
        if active:
            return active.source_key
        return "local_cmdb" if await self._legacy_local_allowed() else None

    async def search_assets(self, **arguments: Any) -> list[dict[str, Any]]:
        local_arguments = {key: value for key, value in arguments.items() if key != "asset_class"}
        active = await self.integrations.active_source("cmdb")
        if active is None:
            if not await self._legacy_local_allowed():
                return []
            rows = await self.inventory.find_assets(**local_arguments)
            return self._local_rows(rows, arguments.get("asset_class"))
        if active.source_key == "servicenow_cmdb":
            return await self._search_servicenow(integration_id=active.integration_id, **arguments)
        rows = await self.inventory.find_assets(**local_arguments)
        return self._local_rows(rows, arguments.get("asset_class"))

    @staticmethod
    def _local_rows(rows: list[dict[str, Any]], asset_class: str | None) -> list[dict[str, Any]]:
        if asset_class == "server":
            rows = [
                row
                for row in rows
                if _is_server_class(str(row.get("asset_type") or ""))
                or bool(row.get("operating_system"))
            ]
        return [{**row, "source": "Local CMDB"} for row in rows]

    async def _legacy_local_allowed(self) -> bool:
        """Compatibility only for pre-v2 databases not yet bootstrapped with sources."""
        streams = await self.integrations.stream_sources()
        cmdb = next(item for item in streams if item["stream"] == "cmdb")
        return not cmdb["sources"]

    async def count_assets(
        self, os_family: str | None = None, asset_class: str | None = None
    ) -> dict[str, Any]:
        rows = await self.search_assets(
            os_family=os_family,
            asset_class=asset_class,
            limit=100_000,
        )
        filters = {
            key: value
            for key, value in {"os_family": os_family, "asset_class": asset_class}.items()
            if value
        }
        return {"count": len(rows), "filters": filters, "observed_at": datetime.now(UTC)}

    async def inventory_summary(self) -> dict[str, Any]:
        total = await self.count_assets(asset_class="server")
        linux = await self.count_assets("linux", asset_class="server")
        windows = await self.count_assets("windows", asset_class="server")
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
            "source": await self.active_source_key(),
        }

    async def asset_relationships(self, asset: dict[str, Any]) -> dict[str, Any] | None:
        active = await self.integrations.active_source("cmdb")
        if active and active.source_key == "servicenow_cmdb":
            external_sys_id = str(asset.get("external_sys_id") or "")
            if not external_sys_id:
                return None
            rows = list(
                (
                    await self.session.scalars(
                        select(ServiceNowRelationshipModel).where(
                            ServiceNowRelationshipModel.integration_id
                            == active.integration_id,
                            ServiceNowRelationshipModel.cache_status == "active",
                            or_(
                                ServiceNowRelationshipModel.parent_sys_id == external_sys_id,
                                ServiceNowRelationshipModel.child_sys_id == external_sys_id,
                            ),
                        )
                    )
                ).all()
            )
            return {
                "asset": asset,
                "services": [],
                "outgoing_relationships": [
                    {
                        "relation_type": row.relationship_type_name,
                        "target_reference": row.child_display_name or row.child_sys_id,
                    }
                    for row in rows
                    if row.parent_sys_id == external_sys_id
                ],
                "incoming_relationships": [
                    {
                        "relation_type": row.relationship_type_name,
                        "source_name": row.parent_display_name or row.parent_sys_id,
                    }
                    for row in rows
                    if row.child_sys_id == external_sys_id
                ],
            }
        return await self.inventory.asset_relationships(UUID(str(asset["id"])))

    async def _search_servicenow(
        self,
        *,
        integration_id: Any,
        identifier: str | None = None,
        os_family: str | None = None,
        environment: str | None = None,
        asset_class: str | None = None,
        limit: int = 50,
        **_: Any,
    ) -> list[dict[str, Any]]:
        filters: list[Any] = [
            ServiceNowCIModel.integration_id == integration_id,
            ServiceNowCIModel.cache_status == "active",
            ServiceNowCIModel.active.is_(True),
        ]
        if identifier:
            clean = identifier.strip().casefold()
            filters.append(
                or_(
                    func.lower(ServiceNowCIModel.name) == clean,
                    func.lower(ServiceNowCIModel.fqdn) == clean,
                    ServiceNowCIModel.ip_address == identifier.strip(),
                    func.lower(ServiceNowCIModel.external_sys_id) == clean,
                )
            )
        rows = list(
            (
                await self.session.scalars(
                    select(ServiceNowCIModel)
                    .where(*filters)
                    .order_by(ServiceNowCIModel.name)
                    .limit(limit)
                )
            ).all()
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            fields = row.fields_json or {}
            operating_system = fields.get("os") or fields.get("operating_system")
            row_environment = fields.get("environment")
            if os_family and os_family.casefold() not in str(operating_system or "").casefold():
                continue
            if environment and environment.casefold() != str(row_environment or "").casefold():
                continue
            if asset_class == "server" and not _is_server_class(row.sys_class_name):
                continue
            results.append(
                {
                    "id": str(row.id),
                    "external_sys_id": row.external_sys_id,
                    "canonical_name": row.fqdn or row.name,
                    "hostname": row.name,
                    "fqdn": row.fqdn,
                    "primary_ip": row.ip_address,
                    "operating_system": operating_system,
                    "environment": row_environment,
                    "asset_type": row.sys_class_name,
                    "ci_class": row.sys_class_name,
                    "application": fields.get("application"),
                    "business_owner": fields.get("owned_by"),
                    "technical_owner": fields.get("support_group"),
                    "lifecycle_status": fields.get("install_status"),
                    "updated_at": row.source_updated_at,
                    "source": "ServiceNow CMDB",
                }
            )
        return results

    async def servicenow_observability(self) -> dict[str, Any] | None:
        active = await self.integrations.active_source("cmdb")
        streams = await self.integrations.stream_sources()
        cmdb_stream = next(item for item in streams if item["stream"] == "cmdb")
        source = next(
            (item for item in cmdb_stream["sources"] if item["source_key"] == "servicenow_cmdb"),
            None,
        )
        if source is None:
            return None
        integration_id = source["integration_id"]
        total = int(
            await self.session.scalar(
                select(func.count(ServiceNowCIModel.id)).where(
                    ServiceNowCIModel.integration_id == integration_id,
                    ServiceNowCIModel.cache_status == "active",
                )
            )
            or 0
        )
        server_count = int(
            await self.session.scalar(
                select(func.count(ServiceNowCIModel.id)).where(
                    ServiceNowCIModel.integration_id == integration_id,
                    ServiceNowCIModel.cache_status == "active",
                    or_(
                        func.lower(ServiceNowCIModel.sys_class_name).contains("server"),
                        func.lower(ServiceNowCIModel.sys_class_name).contains("computer"),
                        func.lower(ServiceNowCIModel.sys_class_name).contains("host"),
                    ),
                )
            )
            or 0
        )
        return {
            **source,
            "active": bool(active and active.source_key == "servicenow_cmdb"),
            "total_cis": total,
            "server_cis": server_count,
            "other_cis": max(0, total - server_count),
        }
