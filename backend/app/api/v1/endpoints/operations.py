import json
import shutil
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.dependencies import (
    CurrentUser,
    IntegrationServiceDep,
    KnowledgeServiceDep,
    OperationsDep,
    SettingsDep,
)
from app.api.schemas import (
    ActivityOverviewResponse,
    ActivityResponse,
    KnowledgeStoreChecksResponse,
    KnowledgeStoreOverviewResponse,
    LogResponse,
    OperationalRequestResponse,
    OverviewResponse,
    PaginatedActivityResponse,
    PaginatedLogsResponse,
    PaginatedOperationalRequestsResponse,
)
from app.core.version import CONNECTOR_VERSION
from app.infrastructure.database.models.operations import AuditEventModel
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


def _activity_outcome(
    event_type: str,
) -> Literal["success", "warning", "failure", "information"]:
    if any(
        term in event_type
        for term in ("failed", "failure", "disconnected", "authentication_failed")
    ):
        return "failure"
    if any(
        term in event_type
        for term in ("warning", "delayed", "deferred", "retry", "reconnecting", "out_of_sync")
    ):
        return "warning"
    if any(
        term in event_type
        for term in (
            "succeeded",
            "completed",
            "created",
            "enabled",
            "deleted",
            "reconnected",
            "registered",
            "password_changed",
        )
    ):
        return "success"
    return "information"


def _activity_response(item: AuditEventModel) -> ActivityResponse:
    response = ActivityResponse.model_validate(
        {
            "id": item.id,
            "event_type": item.event_type,
            "actor_username": item.actor_username,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "message": item.message,
            "created_at": item.created_at,
            "outcome": _activity_outcome(item.event_type),
            "integration": str(
                item.details.get("integration")
                or item.details.get("integration_name")
                or item.target_type
                or ""
            )
            or None,
        }
    )
    return response


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    _: CurrentUser,
    operations: OperationsDep,
    settings: SettingsDep,
    integrations: IntegrationServiceDep,
    knowledge: KnowledgeServiceDep,
) -> OverviewResponse:
    await integrations.bootstrap_legacy_integrations()
    data = await operations.overview()
    try:
        usage = shutil.disk_usage(settings.data_root)
        total, free = usage.total, usage.free
    except OSError:
        total, free = None, None
    try:
        knowledge_stats = await knowledge.stats()
        knowledge_status = (
            "unavailable"
            if not knowledge_stats.qdrant_reachable
            else "healthy"
            if knowledge_stats.collection_available
            and knowledge_stats.statistics_readable
            and knowledge_stats.search_operational
            else "degraded"
        )
        knowledge_overview = KnowledgeStoreOverviewResponse(
            status=knowledge_status,
            engine_version=knowledge_stats.engine_version,
            collection=settings.qdrant_collection,
            documents=knowledge_stats.document_count,
            chunks=knowledge_stats.indexed_chunk_count,
            pending=knowledge_stats.pending_count,
            failed=knowledge_stats.failed_count,
            last_indexed_at=knowledge_stats.last_index_activity,
            last_search_at=knowledge_stats.last_search_at,
            checks=KnowledgeStoreChecksResponse(
                qdrant_reachable=knowledge_stats.qdrant_reachable,
                collection_exists=knowledge_stats.collection_available,
                collection_accessible=knowledge_stats.collection_available,
                statistics_readable=knowledge_stats.statistics_readable,
                search_service_operational=knowledge_stats.search_operational,
            ),
        )
    except Exception:
        try:
            store_health = await knowledge.health_status()
        except Exception:
            store_health = None
        reachable = bool(store_health and store_health.qdrant_reachable)
        collection_available = bool(store_health and store_health.collection_available)
        statistics_readable = bool(store_health and store_health.statistics_readable)
        knowledge_overview = KnowledgeStoreOverviewResponse(
            status="degraded" if reachable else "unavailable",
            engine_version=store_health.engine_version if store_health else None,
            collection=settings.qdrant_collection,
            documents=0,
            chunks=0,
            pending=0,
            failed=0,
            checks=KnowledgeStoreChecksResponse(
                qdrant_reachable=reachable,
                collection_exists=collection_available,
                collection_accessible=collection_available,
                statistics_readable=statistics_readable,
                search_service_operational=False,
            ),
        )
    return OverviewResponse(
        connector_status=data["connector_status"],
        saas_status=data["saas_status"],
        last_heartbeat_at=data["last_heartbeat_at"],
        connector_version=CONNECTOR_VERSION,
        peka_connector=CONNECTOR_VERSION,
        components={"qdrant": knowledge_overview.engine_version or "Unknown"},
        knowledge_store=knowledge_overview,
        source_count=data["source_count"],
        enabled_source_count=data["enabled_source_count"],
        unhealthy_source_count=data["unhealthy_source_count"],
        recent_events=[_activity_response(item) for item in data["recent_events"]],
        enabled_integration_count=data["enabled_integration_count"],
        healthy_integration_count=data["healthy_integration_count"],
        attention_integration_count=data["attention_integration_count"],
        recent_integration_failures=[
            _activity_response(item) for item in data["recent_integration_failures"]
        ],
        storage_total_bytes=total,
        storage_free_bytes=free,
        connector_display_name=data["connector_display_name"],
        instance_id=data["instance_id"],
        connector_id=data["connector_id"],
        tenant_id=data["tenant_id"],
        next_heartbeat_at=data["next_heartbeat_at"],
        heartbeat_failure_count=data["heartbeat_failure_count"],
        last_heartbeat_error=data["last_heartbeat_error"],
        saas_url=data["saas_url"],
        registered_at=data["registered_at"],
        last_heartbeat_attempt_at=data["last_heartbeat_attempt_at"],
        heartbeat_interval_seconds=data["heartbeat_interval_seconds"],
        heartbeat_round_trip_ms=data["heartbeat_round_trip_ms"],
        scheduler_running=connector_scheduler.running,
        heartbeat_job_scheduled=connector_scheduler.heartbeat_scheduled,
        source_scheduler_job_count=connector_scheduler.source_job_count,
        document_total=data["document_total"],
        document_queued=data["document_queued"],
        document_uploading=data["document_uploading"],
        document_uploaded=data["document_uploaded"],
        document_failed=data["document_failed"],
        document_unsupported=data["document_unsupported"],
        last_document_delivery_at=data["last_document_delivery_at"],
        document_endpoint_status=data["document_endpoint_status"],
        document_source_health=data["document_source_health"],
        document_source_last_scan_at=data["document_source_last_scan_at"],
        document_source_next_scan_at=data["document_source_next_scan_at"],
    )


@router.get("/activity", response_model=PaginatedActivityResponse)
async def activity(
    _: CurrentUser,
    operations: OperationsDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PaginatedActivityResponse:
    items, total = await operations.list_activity_page(page, page_size)
    return PaginatedActivityResponse(
        items=[_activity_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/activity/overview", response_model=ActivityOverviewResponse)
async def activity_overview(_: CurrentUser, operations: OperationsDep) -> ActivityOverviewResponse:
    data = await operations.activity_overview()
    return ActivityOverviewResponse.model_validate(
        {
            **data,
            "recent_warnings_or_failures": [
                _activity_response(item) for item in data["recent_warnings_or_failures"]
            ],
        }
    )


@router.get("/operational-requests", response_model=PaginatedOperationalRequestsResponse)
async def operational_requests(
    _: CurrentUser,
    operations: OperationsDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PaginatedOperationalRequestsResponse:
    items, total = await operations.list_operational_requests(page, page_size)
    return PaginatedOperationalRequestsResponse(
        items=[OperationalRequestResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/logs", response_model=PaginatedLogsResponse)
async def logs(
    _: CurrentUser,
    operations: OperationsDep,
    level: str | None = None,
    component: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> PaginatedLogsResponse:
    items, total = await operations.list_logs(level, component, search, page, page_size)
    return PaginatedLogsResponse(
        items=[LogResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/logs/download")
async def download_logs(_user: CurrentUser, operations: OperationsDep) -> Response:
    items, _total = await operations.list_logs(None, None, None, 1, 1000)
    body = "\n".join(
        json.dumps(LogResponse.model_validate(item).model_dump(mode="json"), separators=(",", ":"))
        for item in items
    )
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=peka-connector-logs.jsonl"},
    )
