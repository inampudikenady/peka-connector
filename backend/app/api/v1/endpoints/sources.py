from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, SourceServiceDep
from app.api.schemas import (
    DocumentResponse,
    ScanResponse,
    SourceResponse,
    SourceUpdate,
    SourceWrite,
)

router = APIRouter()


@router.get("", response_model=list[SourceResponse])
async def list_sources(_: CurrentUser, service: SourceServiceDep) -> object:
    return await service.list_sources()


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(request: SourceWrite, _: CurrentUser, service: SourceServiceDep) -> object:
    return await service.create_source(
        request.plugin_type, request.name, request.enabled, request.configuration
    )


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID, request: SourceUpdate, _: CurrentUser, service: SourceServiceDep
) -> object:
    return await service.update_source(
        source_id, request.name, request.enabled, request.configuration
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: UUID, _: CurrentUser, service: SourceServiceDep) -> Response:
    await service.delete_source(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/scan", response_model=ScanResponse)
async def scan_source(source_id: UUID, _: CurrentUser, service: SourceServiceDep) -> ScanResponse:
    count = await service.scan(source_id)
    return ScanResponse(discovered_count=count)


@router.get("/{source_id}/documents", response_model=list[DocumentResponse])
async def list_documents(source_id: UUID, _: CurrentUser, service: SourceServiceDep) -> object:
    return await service.list_documents(source_id)
