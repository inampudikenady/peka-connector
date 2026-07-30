from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.api.dependencies import Administrator, CMDBServiceDep, CurrentUser, OperationsDep
from app.application.services.cmdb import CMDBError
from app.core.rate_limit import auth_rate_limiter

router = APIRouter()


class PreviewRequest(BaseModel):
    sheet_name: str | None = None
    header_row: int = Field(default=1, ge=1)


class ImportRequest(PreviewRequest):
    mapping: dict[str, str]
    mapping_profile_id: UUID | None = None


class MappingProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mapping: dict[str, str]
    normalization: dict[str, Any] = Field(default_factory=dict)


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("/fields")
async def fields(_: CurrentUser) -> dict[str, list[str]]:
    from app.application.services.inventory import CMDB_FIELDS, IDENTITY_FIELDS

    return {"fields": list(CMDB_FIELDS), "identity_fields": list(IDENTITY_FIELDS)}


@router.get("/datasets")
async def datasets(_: CurrentUser, service: CMDBServiceDep) -> list[dict[str, object]]:
    return await service.list_datasets()


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(
    actor: Administrator,
    service: CMDBServiceDep,
    operations: OperationsDep,
    file: Annotated[UploadFile, File()],
    dataset_name: Annotated[str, Form()],
    import_mode: Annotated[str, Form()] = "create_new",
    dataset_id: Annotated[UUID | None, Form()] = None,
) -> dict[str, object]:
    if import_mode not in {"create_new", "new_version"}:
        raise CMDBError(
            "UNSUPPORTED_IMPORT_MODE",
            "The selected CMDB import mode is not supported.",
        )
    if import_mode == "create_new" and dataset_id is not None:
        raise CMDBError(
            "INVALID_IMPORT_MODE",
            "Create new dataset cannot target an existing dataset.",
        )
    if import_mode == "new_version" and dataset_id is None:
        raise CMDBError(
            "INVALID_IMPORT_MODE",
            "Select an existing dataset when importing a new version.",
        )
    correlation_id = str(uuid4())
    auth_rate_limiter.check(f"cmdb-upload:{actor.id}", limit=20, window_seconds=60)
    await operations.record_event(
        "cmdb.upload_started",
        "CMDB upload started",
        actor=actor,
        target_type="cmdb_dataset",
        target_id=str(dataset_id) if dataset_id else None,
        details={"correlation_id": correlation_id, "filename": file.filename},
        component="cmdb",
    )
    try:
        result = await service.upload(file, dataset_name, dataset_id)
    except Exception as exc:
        await operations.record_event(
            "cmdb.upload_rejected",
            "CMDB upload was rejected",
            actor=actor,
            target_type="cmdb_dataset",
            target_id=str(dataset_id) if dataset_id else None,
            details={"correlation_id": correlation_id, "reason": str(exc)[:500]},
            level="WARNING",
            component="cmdb",
        )
        raise
    return {**result, "correlation_id": correlation_id}


@router.post("/versions/{version_id}/preview")
async def preview(
    version_id: UUID,
    request: PreviewRequest,
    _: Administrator,
    service: CMDBServiceDep,
) -> dict[str, object]:
    return await service.preview(version_id, request.sheet_name, request.header_row)


@router.post("/versions/{version_id}/import")
async def import_version(
    version_id: UUID,
    request: ImportRequest,
    actor: Administrator,
    service: CMDBServiceDep,
    operations: OperationsDep,
) -> dict[str, object]:
    correlation_id = str(uuid4())
    await operations.record_event(
        "cmdb.mapping_validated",
        "CMDB mapping validation started",
        actor=actor,
        target_type="cmdb_dataset_version",
        target_id=str(version_id),
        details={"correlation_id": correlation_id},
        component="cmdb",
    )
    try:
        result = await service.import_version(
            version_id,
            request.sheet_name,
            request.header_row,
            request.mapping,
            request.mapping_profile_id,
        )
    except Exception as exc:
        await operations.record_event(
            "cmdb.import_failed",
            "CMDB import failed",
            actor=actor,
            target_type="cmdb_dataset_version",
            target_id=str(version_id),
            details={"correlation_id": correlation_id, "reason": str(exc)[:500]},
            level="ERROR",
            component="cmdb",
        )
        raise
    await operations.record_event(
        "cmdb.import_completed",
        (f"CMDB import completed: {result['valid_rows']} valid, {result['invalid_rows']} invalid"),
        actor=actor,
        target_type="cmdb_dataset_version",
        target_id=str(version_id),
        details={"correlation_id": correlation_id, **result},
        component="cmdb",
    )
    await operations.record_event(
        "inventory.correlation_completed",
        "CMDB inventory correlation completed",
        actor=actor,
        target_type="cmdb_dataset_version",
        target_id=str(version_id),
        details={
            "correlation_id": correlation_id,
            "ambiguous_matches": result["ambiguous_matches"],
        },
        component="inventory",
    )
    if result["ambiguous_matches"]:
        await operations.record_event(
            "inventory.ambiguous_matches_found",
            f"{result['ambiguous_matches']} ambiguous CMDB identities require review",
            actor=actor,
            target_type="cmdb_dataset_version",
            target_id=str(version_id),
            details={
                "correlation_id": correlation_id,
                "count": result["ambiguous_matches"],
            },
            level="WARNING",
            component="inventory",
        )
    return {**result, "correlation_id": correlation_id}


@router.get("/mapping-profiles")
async def profiles(_: CurrentUser, service: CMDBServiceDep) -> list[dict[str, object]]:
    items = await service.list_profiles()
    return [
        {
            "id": item.id,
            "name": item.name,
            "mapping": item.mapping_json,
            "normalization": item.normalization_json,
            "required_field_policy": item.required_field_policy,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in items
    ]


@router.post("/mapping-profiles", status_code=status.HTTP_201_CREATED)
async def save_profile(
    request: MappingProfileRequest, _: Administrator, service: CMDBServiceDep
) -> dict[str, object]:
    item = await service.save_profile(request.name, request.mapping, request.normalization)
    return {"id": item.id, "name": item.name, "mapping": item.mapping_json}


@router.get("/records")
async def records(
    _: CurrentUser,
    service: CMDBServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=500),
    validation_status: str | None = None,
    dataset_id: UUID | None = None,
) -> dict[str, object]:
    items, total = await service.list_records(
        page, page_size, search, validation_status, dataset_id
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/datasets/{dataset_id}/name")
async def rename(
    dataset_id: UUID,
    request: RenameRequest,
    _: Administrator,
    service: CMDBServiceDep,
) -> dict[str, object]:
    item = await service.rename(dataset_id, request.name)
    return {"id": item.id, "name": item.name, "status": item.status}


@router.post("/datasets/{dataset_id}/retire")
async def retire(
    dataset_id: UUID,
    actor: Administrator,
    service: CMDBServiceDep,
    operations: OperationsDep,
) -> dict[str, object]:
    item = await service.retire(dataset_id)
    await operations.record_event(
        "cmdb.dataset_retired",
        "CMDB dataset retired",
        actor=actor,
        target_type="cmdb_dataset",
        target_id=str(dataset_id),
        details={"correlation_id": str(uuid4())},
        component="cmdb",
    )
    return {"id": item.id, "status": item.status, "retired_at": item.retired_at}


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    dataset_id: UUID,
    _: Administrator,
    service: CMDBServiceDep,
) -> Response:
    await service.delete(dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
