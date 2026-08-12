"""Allow-listed operational tool execution and outbound SaaS RPC worker."""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.inventory import InventoryService
from app.application.services.knowledge import (
    KnowledgeIdentityError,
    KnowledgeUnavailableError,
    LocalKnowledgeService,
)
from app.application.services.loki import LokiError, LokiService
from app.application.services.prometheus import PrometheusError, PrometheusService
from app.application.services.servicenow import ServiceNowError, ServiceNowService
from app.application.services.ticketing import TICKETING_TOOL_NAMES, TicketingProviderService
from app.application.services.zammad import ZammadError
from app.core.config import Settings
from app.domain.ports.saas import (
    OperationalToolRequest,
    OperationalToolResult,
    PEKASaaSClient,
)
from app.infrastructure.database.models.inventory import InventoryAssetModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.security.secrets import SecretEncryptionService

logger = logging.getLogger(__name__)


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
    detail_level: Literal["concise", "detailed"] = "concise"


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


class KnowledgeSearchArguments(_Arguments):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: UUID | None = None


class TicketSearchArguments(_Arguments):
    query: str | None = Field(default=None, max_length=1000)
    state: Literal["open", "closed", "all"] = "all"
    ticket_number: str | None = Field(default=None, max_length=100)
    asset_identifier: str | None = Field(default=None, max_length=500)
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    limit: int = Field(default=5, ge=1, le=50)
    sort_order: Literal["updated_desc", "updated_asc"] = "updated_desc"


class TicketArguments(_Arguments):
    ticket_number: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=100)
    view: Literal["full", "status", "latest_update", "owner"] = "full"


class TicketCountArguments(_Arguments):
    updated_from: datetime | None = None
    group_by_state: bool = True
    requested_state: Literal["open", "closed", "all"] = "all"


class AssetTicketArguments(AssetArguments):
    recently_closed_days: int = Field(default=30, ge=1, le=365)


class TicketCorrelationArguments(AssetArguments):
    evidence_start: datetime | None = None
    evidence_end: datetime | None = None
    error_strings: list[str] = Field(default_factory=list, max_length=20)
    warning_strings: list[str] = Field(default_factory=list, max_length=20)
    service_names: list[str] = Field(default_factory=list, max_length=20)
    symptoms: str | None = Field(default=None, max_length=1000)


SERVICENOW_TOOL_NAMES = frozenset(
    {
        "servicenow_get_status",
        "servicenow_get_incident",
        "servicenow_search_incidents",
        "servicenow_list_open_incidents",
        "servicenow_get_incident_updates",
        "servicenow_get_ci",
        "servicenow_get_ci_relationships",
        "servicenow_get_ci_tickets",
        "servicenow_search_problems",
        "servicenow_search_changes",
    }
)

MULTI_SOURCE_TOOL_NAMES = frozenset({"get_all_ticket_sources"})
NORMALIZED_TICKETING_TOOL_NAMES = frozenset({"ticketing_search_records"})


class ServiceNowSearchArguments(_Arguments):
    query: str | None = Field(default=None, max_length=1000)
    identifier: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=25, ge=1, le=50)


class ServiceNowIncidentArguments(_Arguments):
    number: str = Field(min_length=1, max_length=100)


class ServiceNowCIArguments(AssetArguments):
    max_depth: int = Field(default=3, ge=1, le=3)


class NormalizedTicketingArguments(_Arguments):
    mode: Literal["search", "count", "asset"] = "search"
    state: Literal["all", "open", "closed"] = "open"
    query: str | None = Field(default=None, max_length=1000)
    identifier: str | None = Field(default=None, max_length=500)
    providers: list[Literal["zammad", "servicenow"]] = Field(default_factory=list, max_length=2)
    limit: int = Field(default=50, ge=1, le=50)
    updated_from: datetime | None = None


def _classify_log_impact(item: dict[str, Any], *, historical: bool) -> tuple[str, str]:
    summary = str(item.get("summary") or "").casefold()
    category = str(item.get("category") or "").casefold()
    if historical:
        return "historical", "The event is outside the current two-hour evidence window."
    if re.search(
        r"\b(?:starting|started|finished|stopping|stopped)\s+.+(?:service|session)\b|"
        r"\bload(?:ed|ing) kernel module\b|\bsession (?:opened|closed)\b|"
        r"\bmodprobe@.+(?:starting|started|finished|stopping|stopped)\b",
        summary,
    ):
        return "routine_system_event", "Routine service or system lifecycle event."
    if re.search(
        r"timestamp.+(?:ahead|too new|out of order)|entry.+rejected|loki.+reject|"
        r"ingestion.+delay|telemetry.+delay|scrape pipeline",
        summary,
    ):
        return (
            "monitoring_pipeline_issue",
            "The anomaly affects monitoring ingestion or timestamp handling, not host resources.",
        )
    if re.search(r"firmware|dmi|metadata.+pars|configuration.+(?:invalid|error)", summary):
        return (
            "configuration_issue",
            "Configuration or firmware metadata anomaly without current service-impact evidence.",
        )
    if re.search(
        r"\b(?:outage|service (?:is )?down|unreachable|connection refused|"
        r"fatal|panic|oom[- ]kill|out of memory|filesystem.+(?:read.only|failure)|"
        r"i/o error)\b",
        summary,
    ):
        return "active_operational_issue", "The message explicitly describes active degradation."
    if category in {"oom", "crashes", "filesystem", "application_failures"}:
        return "likely_operational_issue", "The event category can indicate operational impact."
    if category in {"errors", "exceptions", "auth_failures", "restarts"}:
        return (
            "isolated_anomaly",
            "An error-like event was observed without evidence of current host degradation.",
        )
    if category in {"warnings", "kernel"}:
        return "informational", "The source/category alone does not establish impact."
    return "unknown", "The available event metadata does not establish operational impact."


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
                f"1-minute load is {load:.2f} across {cpu_count:.0f} CPUs (critical ≥ 1.5 per CPU)."
            )
            metric_issues.append("load")
        elif ratio >= 1.0:
            raise_severity("warning")
            evidence.append(
                f"1-minute load is {load:.2f} across {cpu_count:.0f} CPUs (warning ≥ 1.0 per CPU)."
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
    for item in log_evidence.get("evidence") or []:
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
    correlation_details: list[dict[str, Any]] = []
    for item in raw_events:
        event_time = _as_datetime(item.get("observed_at"))
        age_seconds = abs((metric_time - event_time).total_seconds()) if event_time else None
        temporally_aligned = age_seconds is not None and age_seconds <= 2 * 3600
        enriched = dict(item)
        impact, impact_reason = _classify_log_impact(item, historical=not temporally_aligned)
        enriched["impact_classification"] = impact
        enriched["impact_reason"] = impact_reason
        if temporally_aligned and impact != "routine_system_event":
            enriched["relevance"] = "observation"
            enriched["relevance_reason"] = (
                f"Observed {age_seconds / 60:.0f} minutes from the latest metrics snapshot; "
                f"classified as {impact.replace('_', ' ')}."
            )
            relevant_events.append(enriched)
            correlation_details.append(
                {
                    "event": item.get("summary") or "Log anomaly",
                    "minutes_from_metrics": round(age_seconds / 60),
                    "shared_asset_or_service": True,
                    "current_metrics_support_impact": bool(metric_issues),
                    "impact_classification": impact,
                    "confidence": (
                        "high"
                        if impact == "active_operational_issue" and metric_issues
                        else "medium"
                        if impact in {"active_operational_issue", "likely_operational_issue"}
                        else "low"
                    ),
                    "causation_established": False,
                }
            )
        else:
            enriched["relevance"] = "unrelated"
            enriched["relevance_reason"] = impact_reason
            unrelated_events.append(enriched)

    impact_counts: dict[str, int] = {}
    for item in relevant_events:
        impact = str(item.get("impact_classification") or "unknown")
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
    active_count = impact_counts.get("active_operational_issue", 0)
    likely_count = impact_counts.get("likely_operational_issue", 0)
    if active_count:
        raise_severity("critical" if metric_issues else "warning")
        evidence.append(
            f"{active_count} log event{'s' if active_count != 1 else ''} explicitly "
            "describe active operational degradation."
        )
        recommendations.append("Review the active service-impact evidence and affected component.")
    if any(str(item.get("category")) == "oom" for item in relevant_events):
        recommendations.append(
            "Review memory pressure, process limits, and the OOM-affected workload."
        )
    if likely_count and (metric_issues or likely_count >= 2):
        raise_severity("warning")
        evidence.append(
            f"{likely_count} repeated or metric-supported log event"
            f"{'s' if likely_count != 1 else ''} indicate a likely operational issue."
        )
    low_impact_count = len(relevant_events) - active_count - likely_count
    if low_impact_count > 0 and not metric_issues:
        evidence.append(
            f"{low_impact_count} recent log anomal"
            f"{'ies were' if low_impact_count != 1 else 'y was'} detected, but "
            "none currently affects reachability, CPU, memory, disk, or monitored services."
        )
    if correlation_details:
        closest = min(item["minutes_from_metrics"] for item in correlation_details)
        correlations.append(
            f"{len(correlation_details)} log anomal"
            f"{'ies occurred' if len(correlation_details) != 1 else 'y occurred'} within "
            f"{closest} minutes of the latest metrics snapshot. "
            + (
                "Current metrics support ongoing impact. "
                if metric_issues
                else "Current CPU, memory, disk, and reachability do not show ongoing degradation. "
            )
            + "Time proximity is correlation evidence; causation is not established."
        )
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
                for value in (_as_datetime(item.get("observed_at")) for item in relevant_events)
                if value is not None
            ),
            default=None,
        )
        metrics_follow_events = bool(
            latest_event_time and metric_time and metric_time >= latest_event_time
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
        "correlation_details": correlation_details,
        "log_impact_counts": impact_counts,
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
        self.ticketing = TicketingProviderService(session, secrets)
        self.servicenow = ServiceNowService(session, secrets)
        self.knowledge = LocalKnowledgeService(session, settings)

    async def execute(self, request: OperationalToolRequest) -> dict[str, Any]:
        if request.tool_name == "knowledge_search":
            knowledge_arguments = KnowledgeSearchArguments.model_validate(request.arguments)
            results = await self.knowledge.search(
                knowledge_arguments.query,
                knowledge_arguments.top_k,
                knowledge_arguments.document_id,
            )
            return {
                "results": [
                    {
                        "document_id": str(item.document_id),
                        "chunk_id": str(item.chunk_id),
                        "content": item.content,
                        "score": item.score,
                        "source": item.source,
                        "metadata": item.metadata,
                    }
                    for item in results
                ]
            }
        if request.tool_name in NORMALIZED_TICKETING_TOOL_NAMES:
            arguments = NormalizedTicketingArguments.model_validate(request.arguments).model_dump()
            if arguments["mode"] == "asset" and not arguments.get("identifier"):
                raise ValueError("A CI or server identifier is required")
            return await self.ticketing.search_enabled_records(arguments)
        if request.tool_name in MULTI_SOURCE_TOOL_NAMES:
            arguments = AssetArguments.model_validate(request.arguments).model_dump()
            sources: dict[str, Any] = {}
            try:
                sources["zammad"] = await self.ticketing.zammad.get_asset_tickets(arguments)
            except ZammadError as exc:
                sources["zammad"] = {
                    "available": False,
                    "error_code": exc.code,
                    "error_message": str(exc),
                }
            try:
                sources["servicenow"] = await self.servicenow.execute_tool(
                    "servicenow_get_ci_tickets", arguments
                )
            except ServiceNowError as exc:
                sources["servicenow"] = {
                    "available": False,
                    "error_code": exc.code,
                    "error_message": str(exc),
                }
            return {"identifier": arguments["identifier"], "sources": sources}
        if request.tool_name in SERVICENOW_TOOL_NAMES:
            if request.tool_name == "servicenow_get_status":
                arguments = EmptyArguments.model_validate(request.arguments).model_dump()
            elif request.tool_name in {
                "servicenow_get_incident",
                "servicenow_get_incident_updates",
            }:
                arguments = ServiceNowIncidentArguments.model_validate(
                    request.arguments
                ).model_dump()
            elif request.tool_name in {
                "servicenow_get_ci",
                "servicenow_get_ci_relationships",
                "servicenow_get_ci_tickets",
            }:
                arguments = ServiceNowCIArguments.model_validate(request.arguments).model_dump()
            else:
                arguments = ServiceNowSearchArguments.model_validate(request.arguments).model_dump()
            return await self.servicenow.execute_tool(request.tool_name, arguments)
        if request.tool_name in TICKETING_TOOL_NAMES:
            await self.ticketing.ensure_tool_available(request.tool_name)
        if request.tool_name == "search_tickets":
            ticket_search = TicketSearchArguments.model_validate(request.arguments)
            return await self.ticketing.search_tickets(ticket_search.model_dump(mode="json"))
        if request.tool_name == "get_ticket":
            ticket_lookup = TicketArguments.model_validate(request.arguments)
            if not ticket_lookup.ticket_number and not ticket_lookup.external_id:
                raise ValueError("A ticket number or external ID is required")
            return await self.ticketing.get_ticket(ticket_lookup.model_dump(exclude_none=True))
        if request.tool_name == "get_ticket_counts":
            ticket_counts = TicketCountArguments.model_validate(request.arguments)
            return await self.ticketing.get_ticket_counts(ticket_counts.model_dump(mode="json"))
        if request.tool_name == "get_asset_tickets":
            asset_tickets = AssetTicketArguments.model_validate(request.arguments)
            return await self.ticketing.get_asset_tickets(asset_tickets.model_dump())
        if request.tool_name == "correlate_tickets_with_evidence":
            ticket_correlation = TicketCorrelationArguments.model_validate(request.arguments)
            return await self.ticketing.correlate_tickets_with_evidence(
                ticket_correlation.model_dump(mode="json")
            )
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
                    logs = await self.loki.asset_evidence(model, limit_per_category=2)
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
                result: dict[str, Any] = {
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
                    "detail_level": (
                        status_arguments.detail_level if status_arguments else "concise"
                    ),
                    "evidence_sources": {
                        "inventory": "connector inventory",
                        "metrics": "prometheus",
                        "logs": "loki",
                    },
                }
                try:
                    related_tickets = await self.ticketing.get_asset_tickets(
                        {"identifier": asset_arguments.identifier, "recently_closed_days": 30}
                    )
                    result["related_tickets"] = related_tickets
                    assessment = result["assessment"]
                    open_direct = related_tickets.get("open_tickets") or []
                    closed_direct = related_tickets.get("recently_closed_tickets") or []
                    non_health_types = {
                        "service_request",
                        "access_request",
                        "maintenance",
                        "change",
                        "informational",
                    }
                    open_incidents = [
                        item for item in open_direct if item.get("ticket_type") == "incident"
                    ]
                    ignored_open = [
                        item for item in open_direct if item.get("ticket_type") in non_health_types
                    ]
                    current_support = assessment.get("overall_health") in {
                        "warning",
                        "critical",
                    }
                    result["ticket_health_context"] = {
                        "open_incident_count": len(open_incidents),
                        "closed_incident_count": sum(
                            item.get("ticket_type") == "incident" for item in closed_direct
                        ),
                        "non_health_open_count": len(ignored_open),
                        "current_evidence_supports_open_incident": bool(
                            open_incidents and current_support
                        ),
                        "assessment": (
                            "Open incidents have supporting current monitoring evidence."
                            if open_incidents and current_support
                            else (
                                "Open tickets are contextual; current monitoring does not "
                                "support active degradation."
                            )
                            if open_direct
                            else (
                                "Closed incidents are historical context and current monitoring "
                                "shows no active recurrence."
                            )
                            if closed_direct and not current_support
                            else "No ticket changes the monitoring-derived health state."
                        ),
                    }
                except ZammadError as exc:
                    result["related_tickets"] = {
                        "availability": {
                            "enabled": False,
                            "state": "unavailable",
                            "error_code": exc.code,
                            "last_error": str(exc),
                        },
                        "open_tickets": [],
                        "recently_closed_tickets": [],
                    }
                try:
                    result["servicenow_records"] = await self.servicenow.execute_tool(
                        "servicenow_get_ci_tickets",
                        {"identifier": asset_arguments.identifier, "max_depth": 3},
                    )
                except ServiceNowError as exc:
                    result["servicenow_records"] = {
                        "source": "servicenow",
                        "availability": {
                            "enabled": False,
                            "state": "unavailable",
                            "error_code": exc.code,
                            "last_error": str(exc),
                        },
                        "records": [],
                    }
                return result
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
        started = time.monotonic()
        integration = (
            "Local Knowledge Store"
            if request.tool_name == "knowledge_search"
            else "Zammad + ServiceNow"
            if request.tool_name in MULTI_SOURCE_TOOL_NAMES
            else "ServiceNow"
            if request.tool_name in SERVICENOW_TOOL_NAMES
            else "Ticketing"
            if request.tool_name in TICKETING_TOOL_NAMES
            or request.tool_name in NORMALIZED_TICKETING_TOOL_NAMES
            else "Prometheus"
            if request.tool_name in {"get_asset_status", "get_asset_utilization"}
            else "Loki"
            if request.tool_name == "get_asset_log_evidence"
            else "Inventory"
        )
        target_asset = str(request.arguments.get("identifier") or "") or None
        operations = SqlAlchemyOperationsRepository(self.session)
        await operations.record_audit_event(
            "operational_request.started",
            f"{request.tool_name} request started",
            target_type="operational_tool_request",
            target_id=str(request.id),
            details={
                "tool_name": request.tool_name,
                "integration": integration,
                "target_asset": target_asset,
            },
        )
        try:
            result = await OperationalToolExecutor(
                self.session, self.settings, self.secrets
            ).execute(request)
            if request.tool_name in NORMALIZED_TICKETING_TOOL_NAMES:
                provider_results = list(result.get("providers") or [])
                logger.info(
                    "ticket_provider_selection tenant_id=%s connector_id=%s request_id=%s "
                    "intent=%s configured=%s enabled=%s selected=%s tool=%s records=%s stale=%s",
                    product.tenant_id,
                    connector_id,
                    request.id,
                    request.arguments.get("mode"),
                    result.get("configured_providers") or [],
                    result.get("enabled_providers") or [],
                    result.get("selected_providers") or [],
                    request.tool_name,
                    sum(int(item.get("count") or 0) for item in provider_results),
                    any(bool(item.get("stale")) for item in provider_results),
                )
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
        except ZammadError as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
        except ServiceNowError as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
        except (KnowledgeUnavailableError, KnowledgeIdentityError) as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="LOCAL_KNOWLEDGE_UNAVAILABLE",
                error_message=str(exc)[:500],
            )
        except Exception:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="TOOL_EXECUTION_FAILED",
                error_message="The connector could not execute the operational tool.",
            )
        try:
            await self.client.submit_operational_tool_result(
                product.saas_url,
                connector_id,
                connector_secret,
                request.id,
                submission,
            )
        except Exception:
            await operations.record_audit_event(
                "operational_request.failed",
                f"{request.tool_name} result submission failed",
                target_type="operational_tool_request",
                target_id=str(request.id),
                details={
                    "tool_name": request.tool_name,
                    "integration": integration,
                    "target_asset": target_asset,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    "result_summary": "The result could not be submitted to PEKA.",
                    "error_code": "RESULT_SUBMISSION_FAILED",
                },
            )
            raise
        result = submission.result or {}
        result_summary = (
            f"Returned {result.get('count')} records"
            if result.get("count") is not None
            else "Request completed"
            if submission.status == "completed"
            else submission.error_message or "Request failed"
        )
        await operations.record_audit_event(
            "operational_request.succeeded"
            if submission.status == "completed"
            else "operational_request.failed",
            f"{request.tool_name} request {submission.status}",
            target_type="operational_tool_request",
            target_id=str(request.id),
            details={
                "tool_name": request.tool_name,
                "integration": integration,
                "target_asset": target_asset,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "result_summary": result_summary[:500],
                "error_code": submission.error_code,
            },
        )
        if (
            request.tool_name in TICKETING_TOOL_NAMES
            or request.tool_name in SERVICENOW_TOOL_NAMES
            or request.tool_name in MULTI_SOURCE_TOOL_NAMES
            or request.tool_name in NORMALIZED_TICKETING_TOOL_NAMES
        ):
            await operations.record_event(
                "ticketing.operational_request",
                f"Ticketing operational request {submission.status}",
                target_type="operational_tool_request",
                target_id=str(request.id),
                details={
                    "tool_name": request.tool_name,
                    "status": submission.status,
                    "error_code": submission.error_code,
                },
                level="INFO" if submission.status == "completed" else "ERROR",
                component="ticketing",
            )
        return True
