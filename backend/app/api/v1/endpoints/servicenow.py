from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.dependencies import Administrator, CurrentUser, OperationsDep, ServiceNowServiceDep
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


class ServiceNowConfigurationRequest(BaseModel):
    name: str = Field(default="ServiceNow", min_length=1, max_length=200)
    enabled: bool = True
    instance_url: str = Field(min_length=1, max_length=1000)
    username: str = Field(min_length=1, max_length=255)
    password: str | None = Field(default=None, max_length=5000)
    verify_tls: bool = True
    request_timeout_seconds: float = Field(default=20, ge=1, le=120)
    page_size: int = Field(default=200, ge=1, le=1000)
    sync_interval_seconds: int = Field(default=900, ge=60, le=86400)


@router.get("/configurations")
async def configurations(_: CurrentUser, service: ServiceNowServiceDep) -> list[dict[str, Any]]:
    return await service.list_configurations()


@router.post("/configurations", status_code=status.HTTP_201_CREATED)
async def create(
    request: ServiceNowConfigurationRequest,
    actor: Administrator,
    service: ServiceNowServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    result = await service.save(None, request.model_dump(), actor.username)
    await connector_scheduler.reconcile_servicenow(UUID(result["id"]))
    await operations.record_event(
        "servicenow.configuration_created",
        "ServiceNow configuration created",
        actor=actor,
        target_type="servicenow_configuration",
        target_id=result["id"],
        details={"integration": "servicenow"},
        component="servicenow",
    )
    return result


@router.put("/configurations/{configuration_id}")
async def update(
    configuration_id: UUID,
    request: ServiceNowConfigurationRequest,
    actor: Administrator,
    service: ServiceNowServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    result = await service.save(configuration_id, request.model_dump(), actor.username)
    await connector_scheduler.reconcile_servicenow(configuration_id)
    await operations.record_event(
        "servicenow.configuration_updated",
        "ServiceNow configuration updated",
        actor=actor,
        target_type="servicenow_configuration",
        target_id=str(configuration_id),
        details={"integration": "servicenow", "enabled": result["enabled"]},
        component="servicenow",
    )
    return result


@router.post("/configurations/{configuration_id}/test")
async def test(
    configuration_id: UUID,
    actor: Administrator,
    service: ServiceNowServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    outcome = "failed"
    try:
        result = await service.test(configuration_id)
        outcome = "success"
        return {**result, "correlation_id": correlation_id}
    finally:
        await operations.record_event(
            "servicenow.connection_test",
            f"ServiceNow connection test {outcome}",
            actor=actor,
            target_type="servicenow_configuration",
            target_id=str(configuration_id),
            details={
                "integration": "servicenow",
                "outcome": outcome,
                "correlation_id": correlation_id,
            },
            level="INFO" if outcome == "success" else "ERROR",
            component="servicenow",
        )


@router.post("/configurations/{configuration_id}/sync")
async def synchronize(
    configuration_id: UUID,
    actor: Administrator,
    service: ServiceNowServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    started = __import__("time").monotonic()
    correlation_id = str(uuid4())
    try:
        result = await service.synchronize(configuration_id)
        await operations.record_event(
            "servicenow.sync_completed",
            "ServiceNow synchronization completed",
            actor=actor,
            target_type="servicenow_configuration",
            target_id=str(configuration_id),
            details={
                "integration": "servicenow",
                "outcome": "success",
                "counts": result["counts"],
                "duration_ms": round((__import__("time").monotonic() - started) * 1000, 1),
                "correlation_id": correlation_id,
            },
            component="servicenow",
        )
        return {**result, "correlation_id": correlation_id}
    except Exception:
        await operations.record_event(
            "servicenow.sync_failed",
            "ServiceNow synchronization failed",
            actor=actor,
            target_type="servicenow_configuration",
            target_id=str(configuration_id),
            details={
                "integration": "servicenow",
                "outcome": "failed",
                "duration_ms": round((__import__("time").monotonic() - started) * 1000, 1),
                "correlation_id": correlation_id,
            },
            level="ERROR",
            component="servicenow",
        )
        raise


@router.get("/configurations/{configuration_id}/status")
async def integration_status(
    configuration_id: UUID, _: CurrentUser, service: ServiceNowServiceDep
) -> dict[str, Any]:
    items = await service.list_configurations()
    for item in items:
        if item["id"] == str(configuration_id):
            return item
    return await service.status(configuration_id)


@router.get("/configurations/{configuration_id}/cmdb")
async def cmdb_observability(
    configuration_id: UUID,
    _: CurrentUser,
    service: ServiceNowServiceDep,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    return await service.cmdb_observability(
        configuration_id,
        page=max(1, page),
        page_size=min(max(1, page_size), 100),
    )
