from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import Administrator, CurrentUser, OperationsDep, ZammadServiceDep
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


class ConfigurationRequest(BaseModel):
    name: str = Field(default="Zammad", min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=1000)
    access_token: str | None = Field(default=None, max_length=5000)
    tls_verify: bool = True
    request_timeout_seconds: float = Field(default=15, ge=1, le=120)
    sync_interval_seconds: int = Field(default=900, ge=60, le=86400)
    history_window_days: int = Field(default=90, ge=1, le=3650)
    group_filters: list[str] = Field(default_factory=list, max_length=100)
    include_closed_tickets: bool = True
    enabled: bool = True


@router.get("/configurations")
async def configurations(_: CurrentUser, service: ZammadServiceDep) -> list[dict[str, Any]]:
    return await service.list_configurations()


@router.post("/configurations", status_code=status.HTTP_201_CREATED)
async def create(
    request: ConfigurationRequest, _: Administrator, service: ZammadServiceDep
) -> dict[str, Any]:
    result = await service.save(None, request.model_dump())
    await connector_scheduler.reconcile_zammad(UUID(result["id"]))
    return result


@router.put("/configurations/{configuration_id}")
async def update(
    configuration_id: UUID,
    request: ConfigurationRequest,
    _: Administrator,
    service: ZammadServiceDep,
) -> dict[str, Any]:
    result = await service.save(configuration_id, request.model_dump())
    await connector_scheduler.reconcile_zammad(configuration_id)
    return result


@router.post("/configurations/{configuration_id}/test")
async def test(
    configuration_id: UUID,
    actor: Administrator,
    service: ZammadServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    succeeded = False
    try:
        result = await service.test(configuration_id)
        succeeded = True
        return {**result, "correlation_id": correlation_id}
    finally:
        await operations.record_event(
            "zammad.connection_test",
            "Zammad authentication and ticket-read permission validated"
            if succeeded
            else "Zammad connection test failed",
            actor=actor,
            target_type="zammad_configuration",
            target_id=str(configuration_id),
            details={"correlation_id": correlation_id},
            level="INFO" if succeeded else "ERROR",
            component="zammad",
        )


@router.post("/configurations/{configuration_id}/sync")
async def synchronize(
    configuration_id: UUID,
    actor: Administrator,
    service: ZammadServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    result = await service.synchronize(configuration_id, full=True, trigger="manual")
    await operations.record_event(
        "zammad.sync_completed",
        f"Zammad synchronization completed: {result['ticket_count']} tickets",
        actor=actor,
        target_type="zammad_configuration",
        target_id=str(configuration_id),
        details={
            "correlation_id": correlation_id,
            "ticket_count": result["ticket_count"],
            "article_count": result["article_count"],
        },
        component="zammad",
    )
    return {**result, "correlation_id": correlation_id}


@router.delete("/configurations/{configuration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_configuration(
    configuration_id: UUID, _: Administrator, service: ZammadServiceDep
) -> Response:
    await connector_scheduler.remove_zammad(configuration_id)
    await service.delete(configuration_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
