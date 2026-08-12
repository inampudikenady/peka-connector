from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from app.api.dependencies import (
    Administrator,
    CurrentUser,
    DocumentServiceDep,
    KnowledgeServiceDep,
    OperationsDep,
)
from app.api.schemas import (
    DocumentUploadBatchResponse,
    DocumentUploadResult,
    ManagedDocumentResponse,
    ManagedDocumentScanResponse,
    ManagedDocumentSourceResponse,
    ManagedDocumentSourceUpdate,
    PaginatedManagedDocumentsResponse,
)
from app.application.services.documents import DocumentError
from app.application.services.knowledge import (
    KnowledgeIdentityError,
    KnowledgeUnavailableError,
)
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


def _source_response(source: SourceModel) -> ManagedDocumentSourceResponse:
    return ManagedDocumentSourceResponse(
        id=source.id,
        name=source.name,
        plugin_type="filesystem_documents",
        path="/data/sources/documents",
        enabled=source.enabled,
        system_managed=True,
        scan_interval_seconds=int(source.configuration.get("scan_interval_seconds", 300)),
        last_scan_at=source.last_scan_at,
        next_scheduled_scan_at=source.next_scheduled_scan_at,
        last_scan_result=(
            "Failed" if source.last_error else "Completed" if source.last_scan_at else "Never"
        ),
        discovered_document_count=source.file_count,
        health_status=source.health_status,
        last_error=source.last_error,
    )


@router.get("/source", response_model=ManagedDocumentSourceResponse)
async def get_managed_source(
    _: CurrentUser, service: DocumentServiceDep
) -> ManagedDocumentSourceResponse:
    return _source_response(await service.source())


@router.put("/source", response_model=ManagedDocumentSourceResponse)
async def update_managed_source(
    request: ManagedDocumentSourceUpdate,
    actor: Administrator,
    service: DocumentServiceDep,
    operations: OperationsDep,
) -> ManagedDocumentSourceResponse:
    previous = await service.source()
    previous_enabled = previous.enabled
    previous_interval = int(previous.configuration.get("scan_interval_seconds", 300))
    source = await service.update_source(request.enabled, request.scan_interval_seconds)
    if previous_enabled != source.enabled:
        await operations.record_event(
            "document_source.enabled" if source.enabled else "document_source.disabled",
            f"Managed document source {'enabled' if source.enabled else 'disabled'}",
            actor=actor,
            target_type="source",
            target_id=str(source.id),
            component="documents",
        )
    if previous_interval != request.scan_interval_seconds:
        await operations.record_event(
            "document_source.scan_interval_changed",
            (
                "Managed document source scan interval changed to "
                f"{request.scan_interval_seconds} seconds"
            ),
            actor=actor,
            target_type="source",
            target_id=str(source.id),
            component="documents",
        )
    await connector_scheduler.reconcile_document_schedule()
    return _source_response(await service.refresh_source())


@router.post("/source/test", response_model=ManagedDocumentSourceResponse)
async def test_managed_source(
    _: Administrator, service: DocumentServiceDep
) -> ManagedDocumentSourceResponse:
    return _source_response(await service.test_source_health())


@router.post("/source/scan", response_model=ManagedDocumentScanResponse)
async def scan_managed_source(
    actor: Administrator,
    service: DocumentServiceDep,
    operations: OperationsDep,
) -> ManagedDocumentScanResponse:
    source = await service.source()
    await operations.record_event(
        "document_source.scan_started",
        "Managed document source scan started",
        actor=actor,
        target_type="source",
        target_id=str(source.id),
        details={"trigger": "manual"},
        component="documents",
    )
    try:
        counts = await service.reconcile_with_stability()
    except Exception as exc:
        await service.mark_scan_failed(str(exc))
        await operations.record_event(
            "document_source.scan_failed",
            "Managed document source scan failed",
            actor=actor,
            target_type="source",
            target_id=str(source.id),
            details={"trigger": "manual", "error": str(exc)[:500]},
            level="ERROR",
            component="documents",
        )
        raise
    await operations.record_event(
        "document_source.scan_completed",
        (
            "Managed document source scan completed: "
            f"{counts['discovered']} discovered, {counts['changed']} changed, "
            f"{counts['removed']} removed"
        ),
        actor=actor,
        target_type="source",
        target_id=str(source.id),
        details={"trigger": "manual", **counts},
        component="documents",
    )
    return ManagedDocumentScanResponse(**counts)


@router.get("", response_model=PaginatedManagedDocumentsResponse)
async def list_documents(
    _: CurrentUser,
    service: DocumentServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    show_deleted: bool = Query(default=False),
) -> PaginatedManagedDocumentsResponse:
    items, total = await service.list_page(page, page_size, show_deleted=show_deleted)
    return PaginatedManagedDocumentsResponse(
        items=[ManagedDocumentResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}", response_model=ManagedDocumentResponse)
async def get_document(
    document_id: UUID, _: CurrentUser, service: DocumentServiceDep
) -> ManagedDocumentResponse:
    document = await service.get(document_id)
    await service.prepare_for_response([document])
    return ManagedDocumentResponse.model_validate(document)


@router.post("/upload", response_model=DocumentUploadBatchResponse)
async def upload_documents(
    _: Administrator,
    service: DocumentServiceDep,
    knowledge: KnowledgeServiceDep,
    files: Annotated[list[UploadFile], File()],
) -> DocumentUploadBatchResponse:
    if len(files) > service.max_files_per_request:
        raise DocumentError(
            "BATCH_TOO_LARGE",
            "Too many files were included in this upload request.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    results: list[DocumentUploadResult] = []
    batch_bytes = 0
    for upload in files:
        try:
            document = await service.upload(upload, batch_bytes)
            try:
                await knowledge.index_document(document)
            except Exception:
                # The durable local file remains queued for the background knowledge worker.
                pass
            await service.prepare_for_response([document])
            batch_bytes += document.size_bytes
            results.append(
                DocumentUploadResult(
                    filename=document.filename,
                    success=True,
                    document=ManagedDocumentResponse.model_validate(document),
                    message="Document was stored and queued for local indexing.",
                )
            )
        except DocumentError as exc:
            await upload.close()
            results.append(
                DocumentUploadResult(
                    filename=upload.filename or "Unknown file",
                    success=False,
                    code=exc.code,
                    message=str(exc),
                )
            )
    return DocumentUploadBatchResponse(results=results)


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document(
    document_id: UUID,
    _: Administrator,
    service: DocumentServiceDep,
    knowledge: KnowledgeServiceDep,
) -> dict[str, str]:
    document = await service.retry(document_id)
    await knowledge.index_document(document)
    return {"message": "Document local indexing was retried."}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    _: Administrator,
    service: DocumentServiceDep,
    knowledge: KnowledgeServiceDep,
) -> Response:
    await service.delete(document_id)
    try:
        await knowledge.delete_document(document_id)
    except (KnowledgeUnavailableError, KnowledgeIdentityError):
        # The durable DELETE_PENDING marker is retried by the local knowledge worker.
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)
