from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import (
    Administrator,
    CurrentUser,
    OperationsDep,
    PrometheusServiceDep,
)
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


class ConfigurationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=1000)
    auth_type: str = "none"
    username: str | None = Field(default=None, max_length=500)
    secret: str | None = Field(default=None, max_length=5000)
    tls_verify: bool = True
    request_timeout_seconds: float = Field(default=10, ge=1, le=120)
    scan_interval_seconds: int = Field(default=300, ge=30, le=86400)
    enabled: bool = True


@router.get("/configurations")
async def configurations(_: CurrentUser, service: PrometheusServiceDep) -> list[dict[str, Any]]:
    return await service.list_configurations()


@router.post("/configurations", status_code=status.HTTP_201_CREATED)
async def create(
    request: ConfigurationRequest,
    _: Administrator,
    service: PrometheusServiceDep,
) -> dict[str, Any]:
    result = await service.save(None, request.model_dump())
    await connector_scheduler.reconcile_prometheus(UUID(str(result["id"])))
    return result


@router.put("/configurations/{configuration_id}")
async def update(
    configuration_id: UUID,
    request: ConfigurationRequest,
    _: Administrator,
    service: PrometheusServiceDep,
) -> dict[str, Any]:
    result = await service.save(configuration_id, request.model_dump())
    await connector_scheduler.reconcile_prometheus(configuration_id)
    return result


@router.post("/configurations/{configuration_id}/test")
async def test(
    configuration_id: UUID,
    actor: Administrator,
    service: PrometheusServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    result = await service.test(configuration_id)
    await operations.record_event(
        "prometheus.connection_test",
        "Prometheus connection test succeeded",
        actor=actor,
        target_type="prometheus_configuration",
        target_id=str(configuration_id),
        details={"correlation_id": correlation_id},
        component="prometheus",
    )
    return {**result, "correlation_id": correlation_id}


@router.post("/configurations/{configuration_id}/diagnostics")
async def diagnostics(
    configuration_id: UUID,
    actor: Administrator,
    service: PrometheusServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    result = await service.diagnose(configuration_id)
    await operations.record_event(
        "prometheus.connection_diagnostics",
        "Prometheus layered connection diagnostics completed",
        actor=actor,
        target_type="prometheus_configuration",
        target_id=str(configuration_id),
        details={
            "correlation_id": correlation_id,
            "success": result["success"],
            "stages": result["stages"],
        },
        level="INFO" if result["success"] else "WARNING",
        component="prometheus",
    )
    return {**result, "correlation_id": correlation_id}


@router.post("/configurations/{configuration_id}/scan")
async def scan(
    configuration_id: UUID,
    actor: Administrator,
    service: PrometheusServiceDep,
    operations: OperationsDep,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    await operations.record_event(
        "prometheus.scan_started",
        "Prometheus scan started",
        actor=actor,
        target_type="prometheus_configuration",
        target_id=str(configuration_id),
        details={"correlation_id": correlation_id},
        component="prometheus",
    )
    try:
        result = await service.scan(configuration_id)
    except Exception as exc:
        await operations.record_event(
            "prometheus.scan_failed",
            "Prometheus scan failed",
            actor=actor,
            target_type="prometheus_configuration",
            target_id=str(configuration_id),
            details={"correlation_id": correlation_id, "reason": str(exc)[:500]},
            level="ERROR",
            component="prometheus",
        )
        raise
    await operations.record_event(
        "prometheus.scan_completed",
        f"Prometheus scan completed: {result['target_count']} targets",
        actor=actor,
        target_type="prometheus_configuration",
        target_id=str(configuration_id),
        details={"correlation_id": correlation_id, **result},
        component="prometheus",
    )
    await operations.record_event(
        "inventory.correlation_completed",
        "Prometheus inventory correlation completed",
        actor=actor,
        target_type="prometheus_configuration",
        target_id=str(configuration_id),
        details={
            "correlation_id": correlation_id,
            "ambiguous_matches": result["ambiguous_target_count"],
            "unmatched": result["unmatched_target_count"],
        },
        component="inventory",
    )
    if result["ambiguous_target_count"]:
        await operations.record_event(
            "inventory.ambiguous_matches_found",
            f"{result['ambiguous_target_count']} Prometheus targets require review",
            actor=actor,
            target_type="prometheus_configuration",
            target_id=str(configuration_id),
            details={
                "correlation_id": correlation_id,
                "count": result["ambiguous_target_count"],
            },
            level="WARNING",
            component="inventory",
        )
    return {**result, "correlation_id": correlation_id}


@router.delete("/configurations/{configuration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    configuration_id: UUID,
    _: Administrator,
    service: PrometheusServiceDep,
) -> Response:
    await service.delete(configuration_id)
    await connector_scheduler.remove_prometheus(configuration_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
