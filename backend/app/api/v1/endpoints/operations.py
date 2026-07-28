import json
import shutil
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, OperationsDep, SettingsDep
from app.api.schemas import (
    ActivityResponse,
    LogResponse,
    OverviewResponse,
    PaginatedActivityResponse,
    PaginatedLogsResponse,
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
        }
    )
    return response


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    _: CurrentUser, operations: OperationsDep, settings: SettingsDep
) -> OverviewResponse:
    data = await operations.overview()
    try:
        usage = shutil.disk_usage(settings.data_root)
        total, free = usage.total, usage.free
    except OSError:
        total, free = None, None
    return OverviewResponse(
        connector_status=data["connector_status"],
        saas_status=data["saas_status"],
        last_heartbeat_at=data["last_heartbeat_at"],
        connector_version=CONNECTOR_VERSION,
        source_count=data["source_count"],
        enabled_source_count=data["enabled_source_count"],
        unhealthy_source_count=data["unhealthy_source_count"],
        recent_events=[_activity_response(item) for item in data["recent_events"]],
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
