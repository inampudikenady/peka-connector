from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import Administrator, CurrentUser, OperationsDep, SourceServiceDep
from app.api.schemas import (
    DocumentResponse,
    PaginatedScansResponse,
    ScanDetailResponse,
    ScanResponse,
    SourceResponse,
    SourceUpdate,
    SourceValidationResponse,
    SourceWrite,
)
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


@router.get("", response_model=list[SourceResponse])
async def list_sources(_: CurrentUser, service: SourceServiceDep) -> object:
    return await service.list_sources()


@router.post("/validate", response_model=SourceValidationResponse)
async def validate_configuration(
    request: SourceWrite, _: Administrator, service: SourceServiceDep
) -> SourceValidationResponse:
    await service.validate_configuration(request.plugin_type, request.configuration)
    return SourceValidationResponse(valid=True, message="Configuration is valid and readable")


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    _request: SourceWrite,
    _actor: Administrator,
) -> object:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Generic filesystem source creation is not available in this release.",
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: UUID, _: CurrentUser, service: SourceServiceDep) -> object:
    return await service.get_source(source_id)


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    request: SourceUpdate,
    actor: Administrator,
    service: SourceServiceDep,
    operations: OperationsDep,
) -> object:
    previous = await service.get_source(source_id)
    source = await service.update_source(
        source_id, request.name, request.enabled, request.configuration
    )
    event_type = "source.updated"
    if previous.enabled != source.enabled:
        event_type = "source.enabled" if source.enabled else "source.disabled"
    await operations.record_event(
        event_type,
        f"Source {source.name} updated",
        actor=actor,
        target_type="source",
        target_id=str(source.id),
        component="sources",
    )
    await connector_scheduler.reconcile_source(source.id)
    return await service.get_source(source.id)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    actor: Administrator,
    service: SourceServiceDep,
    operations: OperationsDep,
) -> Response:
    source = await service.get_source(source_id)
    await connector_scheduler.remove_source(source_id)
    await service.delete_source(source_id)
    await operations.record_event(
        "source.deleted",
        f"Source {source.name} deleted",
        actor=actor,
        target_type="source",
        target_id=str(source_id),
        component="sources",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/validate", response_model=SourceValidationResponse)
async def validate_source(
    source_id: UUID, _: Administrator, service: SourceServiceDep
) -> SourceValidationResponse:
    await service.validate_source(source_id)
    return SourceValidationResponse(valid=True, message="Source path is available and readable")


@router.post("/{source_id}/scan", response_model=ScanResponse)
async def scan_source(
    source_id: UUID,
    actor: Administrator,
    service: SourceServiceDep,
    operations: OperationsDep,
) -> object:
    source = await service.get_source(source_id)
    correlation_id = uuid4()
    await operations.record_event(
        "source.scan_started",
        f"Scan started for {source.name}",
        actor=actor,
        target_type="source",
        target_id=str(source_id),
        details={"correlation_id": str(correlation_id), "trigger": "manual"},
        component="scanner",
    )
    try:
        result = await service.scan(source_id, "manual", correlation_id)
    except Exception:
        await operations.record_event(
            "source.scan_failed",
            f"Scan failed for {source.name}",
            actor=actor,
            target_type="source",
            target_id=str(source_id),
            level="ERROR",
            details={"correlation_id": str(correlation_id), "trigger": "manual"},
            component="scanner",
        )
        raise
    await operations.record_event(
        "source.scan_completed",
        (
            f"Scan completed for {source.name}: {result.added_count} added, "
            f"{result.changed_count} changed, {result.missing_count} removed"
        ),
        actor=actor,
        target_type="source",
        target_id=str(source_id),
        details={
            "discovered": result.discovered_count,
            "added": result.added_count,
            "changed": result.changed_count,
            "missing": result.missing_count,
            "correlation_id": str(result.correlation_id),
            "trigger": "manual",
        },
        component="scanner",
    )
    return result


@router.get("/{source_id}/documents", response_model=list[DocumentResponse])
async def list_documents(source_id: UUID, _: CurrentUser, service: SourceServiceDep) -> object:
    return await service.list_documents(source_id)


@router.get("/{source_id}/scans", response_model=PaginatedScansResponse)
async def list_scan_history(
    source_id: UUID,
    _: CurrentUser,
    service: SourceServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedScansResponse:
    items, total = await service.list_scan_history_page(source_id, page, page_size)
    return PaginatedScansResponse(
        items=[ScanResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{source_id}/scans/{scan_id}", response_model=ScanDetailResponse)
async def get_scan_detail(
    source_id: UUID,
    scan_id: UUID,
    _: CurrentUser,
    service: SourceServiceDep,
    operations: OperationsDep,
) -> ScanDetailResponse:
    source = await service.get_source(source_id)
    scan = await service.get_scan(source_id, scan_id)
    return ScanDetailResponse(
        **ScanResponse.model_validate(scan).model_dump(),
        source_name=source.name,
        log_references=await operations.scan_log_references(str(scan.correlation_id)),
    )
