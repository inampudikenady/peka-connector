"""Allow-listed operational tool execution and outbound SaaS RPC worker."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.inventory import InventoryService
from app.application.services.loki import LokiError, LokiService
from app.application.services.prometheus import PrometheusError, PrometheusService
from app.core.config import Settings
from app.domain.ports.saas import (
    OperationalToolRequest,
    OperationalToolResult,
    PEKASaaSClient,
)
from app.infrastructure.database.models.inventory import InventoryAssetModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.security.secrets import SecretEncryptionService


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CountArguments(_Arguments):
    os_family: str | None = Field(default=None, max_length=100)


class SearchArguments(_Arguments):
    identifier: str | None = Field(default=None, max_length=500)
    os_family: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=255)
    missing_prometheus: bool | None = None
    prometheus_health: Literal["healthy", "unhealthy"] | None = None
    limit: int = Field(default=25, ge=1, le=50)


class AssetArguments(_Arguments):
    identifier: str = Field(min_length=1, max_length=500)


class StatusArguments(AssetArguments):
    mode: Literal["health", "performance", "timeline"] = "health"


EvidenceCategory = Literal[
    "errors",
    "warnings",
    "restarts",
    "crashes",
    "exceptions",
    "auth_failures",
    "kernel",
    "filesystem",
    "oom",
    "application_failures",
]


class LogEvidenceArguments(AssetArguments):
    category: EvidenceCategory | None = None
    lookback_hours: Literal[1, 6, 24, 72, 168, 720] = 24


class EmptyArguments(_Arguments):
    pass


def _health_assessment(
    status: dict[str, Any],
    utilization: dict[str, Any],
    log_evidence: dict[str, Any] | None = None,
    mode: Literal["health", "performance", "timeline"] = "health",
) -> dict[str, Any]:
    """Apply deterministic thresholds and question-aware evidence relevance."""
    severity = "healthy"
    evidence: list[str] = []
    metric_issues: list[str] = []

    def raise_severity(value: str) -> None:
        nonlocal severity
        order = {"healthy": 0, "unknown": 1, "warning": 2, "critical": 3}
        if order[value] > order[severity]:
            severity = value

    if status.get("reachable") is False:
        severity = "critical"
        evidence.append("Prometheus reports the target as unreachable.")
    elif status.get("reachable") is None:
        severity = "unknown"
        evidence.append("Reachability is unavailable.")

    for label, key, warning, critical in (
        ("CPU", "cpu_percent", 75.0, 90.0),
        ("Memory", "memory_percent", 80.0, 90.0),
    ):
        value = utilization.get(key)
        if not isinstance(value, int | float):
            continue
        if value >= critical:
            raise_severity("critical")
            evidence.append(f"{label} utilization is {value:.2f}% (critical ≥ {critical:.0f}%).")
            metric_issues.append(label.casefold())
        elif value >= warning:
            raise_severity("warning")
            evidence.append(f"{label} utilization is {value:.2f}% (warning ≥ {warning:.0f}%).")
            metric_issues.append(label.casefold())

    filesystems = utilization.get("filesystems") or []
    for filesystem in filesystems:
        value = filesystem.get("used_percent")
        if not isinstance(value, int | float):
            continue
        mountpoint = filesystem.get("mountpoint") or "unknown"
        if value >= 90:
            raise_severity("critical")
            evidence.append(f"Filesystem {mountpoint} is {value:.2f}% used (critical ≥ 90%).")
            metric_issues.append("disk")
        elif value >= 80:
            raise_severity("warning")
            evidence.append(f"Filesystem {mountpoint} is {value:.2f}% used (warning ≥ 80%).")
            metric_issues.append("disk")

    load = utilization.get("load_average_1m")
    cpu_count = utilization.get("cpu_count")
    if isinstance(load, int | float) and isinstance(cpu_count, int | float) and cpu_count > 0:
        ratio = load / cpu_count
        if ratio >= 1.5:
            raise_severity("critical")
            evidence.append(
                f"1-minute load is {load:.2f} across {cpu_count:.0f} CPUs "
                "(critical ≥ 1.5 per CPU)."
            )
            metric_issues.append("load")
        elif ratio >= 1.0:
            raise_severity("warning")
            evidence.append(
                f"1-minute load is {load:.2f} across {cpu_count:.0f} CPUs "
                "(warning ≥ 1.0 per CPU)."
            )
            metric_issues.append("load")

    if utilization.get("error_code"):
        if severity == "healthy":
            severity = "unknown"
        evidence.append(str(utilization.get("unavailable_reason") or "Metrics are unavailable."))
    recommendations: list[str] = []
    if "cpu" in metric_issues:
        recommendations.append(
            "Inspect the reported top CPU processes because CPU exceeded its threshold."
        )
    if "memory" in metric_issues:
        recommendations.append(
            "Inspect the reported top memory processes because memory exceeded its threshold."
        )
    if "disk" in metric_issues:
        recommendations.append(
            "Inspect the affected filesystems because disk usage exceeded its threshold."
        )
    if "load" in metric_issues:
        recommendations.append(
            "Inspect runnable work and top CPU processes because load per CPU "
            "exceeded its threshold."
        )

    log_evidence = log_evidence or {}
    category_priority = {
        category: index
        for index, category in enumerate(
            (
                "oom",
                "crashes",
                "filesystem",
                "exceptions",
                "auth_failures",
                "restarts",
                "application_failures",
                "kernel",
                "warnings",
                "errors",
            )
        )
    }
    events_by_occurrence: dict[tuple[object, object], dict[str, Any]] = {}
    for item in (log_evidence.get("evidence") or []):
        if not isinstance(item, dict):
            continue
        key = (item.get("observed_at"), item.get("summary"))
        current = events_by_occurrence.get(key)
        if current is None or category_priority.get(
            str(item.get("category")), 100
        ) < category_priority.get(str(current.get("category")), 100):
            events_by_occurrence[key] = item
    raw_events = list(events_by_occurrence.values())
    metric_time = _as_datetime(utilization.get("metric_timestamp")) or datetime.now(UTC)
    relevant_events: list[dict[str, Any]] = []
    unrelated_events: list[dict[str, Any]] = []
    correlations: list[str] = []
    performance_categories = {
        "oom",
        "crashes",
        "exceptions",
        "application_failures",
        "restarts",
        "filesystem",
    }
    for item in raw_events:
        event_time = _as_datetime(item.get("observed_at"))
        age_seconds = (
            abs((metric_time - event_time).total_seconds()) if event_time else None
        )
        temporally_aligned = age_seconds is not None and age_seconds <= 2 * 3600
        category = str(item.get("category") or "")
        if mode == "performance":
            semantically_related = (
                category in {"oom", "crashes", "exceptions", "restarts"}
                or (
                    bool(metric_issues)
                    and category
                    in performance_categories | {"errors", "warnings", "kernel"}
                )
            )
        else:
            semantically_related = category in {
                "errors",
                "warnings",
                "restarts",
                "crashes",
                "exceptions",
                "auth_failures",
                "kernel",
                "filesystem",
                "oom",
                "application_failures",
            }
        enriched = dict(item)
        if temporally_aligned and semantically_related:
            enriched["relevance"] = "relevant"
            enriched["relevance_reason"] = (
                f"The event occurred within {age_seconds / 60:.0f} minutes of the "
                "Prometheus observation and matches the operational intent."
            )
            relevant_events.append(enriched)
            correlations.append(
                f"{category.replace('_', ' ').title()} evidence occurred "
                f"{age_seconds / 60:.0f} minutes from the Prometheus observation."
            )
        else:
            enriched["relevance"] = "unrelated"
            if not temporally_aligned:
                enriched["relevance_reason"] = (
                    "The event is historical and outside the two-hour correlation window."
                )
            else:
                enriched["relevance_reason"] = (
                    "The event category does not explain the current operational question."
                )
            unrelated_events.append(enriched)

    relevant_counts: dict[str, int] = {}
    for item in relevant_events:
        category = str(item.get("category") or "unknown")
        relevant_counts[category] = relevant_counts.get(category, 0) + 1
    for category, category_severity, statement, recommendation in (
        (
            "oom",
            "critical",
            "Loki contains out-of-memory evidence in the requested window.",
            "Review memory pressure, process limits, and the OOM-killed workload.",
        ),
        (
            "crashes",
            "critical",
            "Loki contains crash or panic evidence in the requested window.",
            "Inspect the crash evidence and the affected service before restarting it.",
        ),
        (
            "filesystem",
            "critical",
            "Loki contains filesystem or disk I/O failure evidence.",
            "Inspect filesystem health and free space on the affected mount.",
        ),
        (
            "exceptions",
            "warning",
            "Loki contains application exception evidence.",
            "Review the most recent exception and its application context.",
        ),
        (
            "auth_failures",
            "warning",
            "Loki contains authentication failure evidence.",
            "Review the source and frequency of the authentication failures.",
        ),
        (
            "restarts",
            "warning",
            "Loki contains service restart evidence.",
            "Check service restart frequency and the preceding log evidence.",
        ),
        (
            "errors",
            "warning",
            "Loki contains error evidence in the requested window.",
            "Review the latest Loki error evidence for the affected component.",
        ),
    ):
        count = relevant_counts.get(category)
        if isinstance(count, int) and count > 0:
            raise_severity(category_severity)
            evidence.append(f"{statement} ({count} event{'s' if count != 1 else ''}).")
            recommendations.append(recommendation)
    if log_evidence.get("error_code") and not log_evidence.get("evidence"):
        evidence.append(
            "Loki evidence is unknown: "
            + str(log_evidence.get("unavailable_reason") or log_evidence["error_code"])
        )
    if unrelated_events:
        categories = sorted(
            {str(item.get("category") or "event").replace("_", " ") for item in unrelated_events}
        )
        evidence.append(
            f"{len(unrelated_events)} historical Loki event"
            f"{'s' if len(unrelated_events) != 1 else ''} "
            f"({', '.join(categories)}) do not align with the current Prometheus observation."
        )
        if mode == "performance":
            evidence.append(
                "No evidence was found linking those historical events to current performance."
            )
    if not evidence:
        evidence.append(
            "Reachability and all available utilization metrics are within thresholds, "
            "and no relevant Loki events were found."
        )

    if mode == "timeline":
        latest_event_time = max(
            (
                value
                for value in (
                    _as_datetime(item.get("observed_at"))
                    for item in relevant_events
                )
                if value is not None
            ),
            default=None,
        )
        metrics_follow_events = bool(
            latest_event_time
            and metric_time
            and metric_time >= latest_event_time
        )
        if relevant_events and metrics_follow_events and not metric_issues:
            conclusion = (
                "Relevant operational events were followed by a Prometheus observation "
                "within normal utilisation thresholds. No later relevant failure was "
                "found in the collected evidence."
            )
        elif relevant_events and metric_issues:
            conclusion = (
                "Relevant operational events are temporally aligned with the latest "
                "threshold breach, so the issue may still be active. The timing is "
                "correlation evidence, not proof of causation."
            )
        elif relevant_events:
            conclusion = (
                "Relevant operational events were found, but the available timestamps "
                "do not establish whether the system recovered afterward."
            )
        elif unrelated_events:
            conclusion = (
                "Only historical events outside the current correlation window were "
                "found. They do not indicate a current operational incident."
            )
        else:
            conclusion = (
                "No relevant Loki events were found in the requested period. The latest "
                "available Prometheus observation is the only time-stamped operational "
                "evidence."
            )
    elif mode == "performance":
        if metric_issues and relevant_events:
            conclusion = (
                f"{', '.join(dict.fromkeys(metric_issues)).title()} is above threshold, "
                "and temporally aligned Loki evidence provides a plausible contributing "
                "factor. The timing supports correlation but does not by itself prove causation."
            )
        elif metric_issues:
            conclusion = (
                f"{', '.join(dict.fromkeys(metric_issues)).title()} is above threshold. "
                "No relevant Loki evidence explains the increase, so the cause remains unknown."
            )
        elif unrelated_events:
            conclusion = (
                "Current CPU, memory, load, and disk utilisation are within thresholds. "
                "The collected historical Loki events do not appear related to current "
                "system utilisation."
            )
        else:
            conclusion = (
                "Current CPU, memory, load, and disk utilisation are within thresholds, "
                "and no relevant Loki events were found in the requested period."
            )
    elif severity in {"warning", "critical"}:
        if metric_issues and relevant_events:
            conclusion = (
                "The overall state is driven by both current threshold breaches and "
                "temporally aligned operational evidence."
            )
        elif metric_issues:
            conclusion = (
                "The overall state is driven by the current threshold breaches; no "
                "relevant Loki evidence explains their cause."
            )
        else:
            conclusion = (
                "The overall state is driven by recent, relevant Loki evidence even "
                "though current utilisation is within thresholds."
            )
    elif unrelated_events:
        conclusion = (
            "Current reachability and utilisation are healthy. Historical Loki events "
            "were observed, but they do not align with the current observation."
        )
    else:
        conclusion = (
            "Current reachability and available utilisation are within thresholds, with "
            "no relevant Loki evidence indicating an active problem."
        )
    return {
        "overall_health": severity,
        "mode": mode,
        "evidence": evidence,
        "conclusion": conclusion,
        "relevant_log_evidence": relevant_events,
        "unrelated_log_evidence": unrelated_events,
        "correlations": correlations,
        "thresholds": {
            "cpu_warning_percent": 75,
            "cpu_critical_percent": 90,
            "memory_warning_percent": 80,
            "memory_critical_percent": 90,
            "disk_warning_percent": 80,
            "disk_critical_percent": 90,
            "load_warning_per_cpu": 1.0,
            "load_critical_per_cpu": 1.5,
        },
        "recommendations": list(dict.fromkeys(recommendations)),
    }


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class OperationalToolExecutor:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        secrets: SecretEncryptionService,
    ) -> None:
        self.session = session
        self.inventory = InventoryService(session)
        self.prometheus = PrometheusService(session, secrets, settings)
        self.loki = LokiService(session, secrets, settings)

    async def execute(self, request: OperationalToolRequest) -> dict[str, Any]:
        if request.tool_name == "get_inventory_summary":
            EmptyArguments.model_validate(request.arguments)
            return await self.inventory.inventory_summary()
        if request.tool_name == "count_assets":
            count_arguments = CountArguments.model_validate(request.arguments)
            return await self.inventory.count_assets(count_arguments.os_family)
        if request.tool_name == "search_assets":
            search_arguments = SearchArguments.model_validate(request.arguments)
            assets = await self.inventory.find_assets(**search_arguments.model_dump())
            return {
                "match_status": "found" if assets else "not_found",
                "assets": assets,
                "count": len(assets),
            }
        if request.tool_name in {
            "get_asset_details",
            "get_asset_status",
            "get_asset_utilization",
            "get_asset_log_evidence",
        }:
            log_arguments = (
                LogEvidenceArguments.model_validate(request.arguments)
                if request.tool_name == "get_asset_log_evidence"
                else None
            )
            status_arguments = (
                StatusArguments.model_validate(request.arguments)
                if request.tool_name == "get_asset_status"
                else None
            )
            asset_arguments = (
                log_arguments
                or status_arguments
                or AssetArguments.model_validate(request.arguments)
            )
            matches = await self.inventory.find_assets(
                identifier=asset_arguments.identifier, limit=20
            )
            if not matches:
                return {
                    "match_status": "not_found",
                    "identifier": asset_arguments.identifier,
                    "candidates": [],
                }
            if len(matches) > 1:
                return {
                    "match_status": "ambiguous",
                    "identifier": asset_arguments.identifier,
                    "candidates": matches,
                }
            asset = matches[0]
            if request.tool_name == "get_asset_details":
                return {"match_status": "found", "asset": asset}
            asset_id = UUID(asset["id"])
            model = await self.session.get(InventoryAssetModel, asset_id)
            if model is None:
                return {
                    "match_status": "not_found",
                    "identifier": asset_arguments.identifier,
                    "candidates": [],
                }
            if request.tool_name == "get_asset_log_evidence":
                assert log_arguments is not None
                categories = [log_arguments.category] if log_arguments.category else None
                evidence = await self.loki.asset_evidence(
                    model,
                    lookback_hours=log_arguments.lookback_hours,
                    categories=categories,
                    limit_per_category=25 if log_arguments.category else 5,
                )
                return {
                    "match_status": "found",
                    "asset": asset,
                    "log_evidence": evidence,
                }
            utilization = await self.prometheus.asset_utilization(model)
            if request.tool_name == "get_asset_status":
                status = await self.inventory.operational_asset_status(asset_id)
                assert status is not None
                try:
                    logs = await self.loki.asset_evidence(
                        model, limit_per_category=2
                    )
                except LokiError as exc:
                    logs = {
                        "available": False,
                        "source": "loki",
                        "error_code": exc.code,
                        "unavailable_reason": str(exc),
                        "evidence": [],
                        "counts_by_category": {},
                        "last_log_at": None,
                    }
                timeline = [
                    {
                        "source": "prometheus",
                        "category": "metrics_observation",
                        "severity": "information",
                        "observed_at": utilization.get("metric_timestamp"),
                        "summary": "Prometheus utilization metrics observed.",
                    },
                    *(logs.get("evidence") or []),
                ]
                timeline = sorted(
                    (item for item in timeline if item.get("observed_at")),
                    key=lambda item: str(item["observed_at"]),
                    reverse=True,
                )
                return {
                    "match_status": "found",
                    "asset": status,
                    "utilization": utilization,
                    "log_evidence": logs,
                    "timeline": timeline,
                    "assessment": _health_assessment(
                        status,
                        utilization,
                        logs,
                        status_arguments.mode if status_arguments else "health",
                    ),
                    "evidence_sources": {
                        "inventory": "connector inventory",
                        "metrics": "prometheus",
                        "logs": "loki",
                    },
                }
            return {"match_status": "found", "utilization": utilization}
        raise ValueError("Unsupported operational tool")


class OperationalToolWorker:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        client: PEKASaaSClient,
        secrets: SecretEncryptionService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.client = client
        self.secrets = secrets

    async def run_once(self) -> bool:
        product = await SqlAlchemyOperationsRepository(self.session).get_settings()
        if (
            not product.connector_id
            or not product.saas_url
            or not product.encrypted_connector_secret
        ):
            return False
        connector_id = UUID(product.connector_id)
        connector_secret = self.secrets.decrypt(product.encrypted_connector_secret)
        request = await self.client.claim_operational_tool(
            product.saas_url, connector_id, connector_secret
        )
        if request is None:
            return False
        try:
            result = await OperationalToolExecutor(
                self.session, self.settings, self.secrets
            ).execute(request)
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="completed",
                result=result,
            )
        except (ValidationError, ValueError) as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="INVALID_TOOL_REQUEST",
                error_message=str(exc)[:500],
            )
        except PrometheusError as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
        except LokiError as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
        except Exception:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="TOOL_EXECUTION_FAILED",
                error_message="The connector could not execute the operational tool.",
            )
        await self.client.submit_operational_tool_result(
            product.saas_url,
            connector_id,
            connector_secret,
            request.id,
            submission,
        )
        return True
