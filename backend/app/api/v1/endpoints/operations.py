import json
import shutil

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, OperationsDep, SettingsDep
from app.api.schemas import (
    ActivityResponse,
    LogResponse,
    OverviewResponse,
    PaginatedLogsResponse,
)

router = APIRouter()


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
        connector_version="0.1.0",
        source_count=data["source_count"],
        enabled_source_count=data["enabled_source_count"],
        unhealthy_source_count=data["unhealthy_source_count"],
        recent_failures=[ActivityResponse.model_validate(item) for item in data["recent_failures"]],
        storage_total_bytes=total,
        storage_free_bytes=free,
    )


@router.get("/activity", response_model=list[ActivityResponse])
async def activity(
    _: CurrentUser,
    operations: OperationsDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> object:
    return await operations.list_activity(limit, offset)


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
