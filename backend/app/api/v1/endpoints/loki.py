from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import Administrator, CurrentUser, LokiServiceDep, OperationsDep

router = APIRouter()


class ConfigurationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=1000)
    auth_type: str = "none"
    username: str | None = Field(default=None, max_length=500)
    secret: str | None = Field(default=None, max_length=5000)
    tls_verify: bool = True
    request_timeout_seconds: float = Field(default=10, ge=1, le=120)
    discovery_lookback_days: int = Field(default=30, ge=1, le=90)
    enabled: bool = True


@router.get("/configurations")
async def configurations(_: CurrentUser, service: LokiServiceDep) -> list[dict[str, Any]]:
    return await service.list_configurations()


@router.post("/configurations", status_code=status.HTTP_201_CREATED)
async def create(
    request: ConfigurationRequest,
    _: Administrator,
    service: LokiServiceDep,
) -> dict[str, Any]:
    return await service.save(None, request.model_dump())


@router.put("/configurations/{configuration_id}")
async def update(
    configuration_id: UUID,
    request: ConfigurationRequest,
    _: Administrator,
    service: LokiServiceDep,
) -> dict[str, Any]:
    return await service.save(configuration_id, request.model_dump())


@router.post("/configurations/{configuration_id}/test")
async def test(
    configuration_id: UUID,
    actor: Administrator,
    service: LokiServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    result = await service.test(configuration_id)
    await operations.record_event(
        "loki.connection_test",
        "Loki connection, schema discovery, and fixed LogQL test succeeded",
        actor=actor,
        target_type="loki_configuration",
        target_id=str(configuration_id),
        details={
            "correlation_id": correlation_id,
            "stream_count": result["stream_count"],
            "labels": result["labels"],
            "sample_query_validated": result["sample_query_validated"],
        },
        component="loki",
    )
    return {**result, "correlation_id": correlation_id}


@router.post("/configurations/{configuration_id}/discover")
async def discover(
    configuration_id: UUID,
    actor: Administrator,
    service: LokiServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    result = await service.discover(configuration_id)
    await operations.record_event(
        "loki.discovery_completed",
        f"Loki schema discovery completed: {result['stream_count']} streams",
        actor=actor,
        target_type="loki_configuration",
        target_id=str(configuration_id),
        details={
            "correlation_id": correlation_id,
            "stream_count": result["stream_count"],
            "labels": result["labels"],
        },
        component="loki",
    )
    return {**result, "correlation_id": correlation_id}


@router.delete("/configurations/{configuration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    configuration_id: UUID,
    _: Administrator,
    service: LokiServiceDep,
) -> Response:
    await service.delete(configuration_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
