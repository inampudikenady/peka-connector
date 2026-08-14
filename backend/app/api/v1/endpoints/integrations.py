"""Generic integration catalog and lifecycle APIs."""

from typing import Any, Never
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import (
    Administrator,
    CurrentUser,
    IntegrationServiceDep,
    LokiServiceDep,
    PrometheusServiceDep,
    ServiceNowServiceDep,
    ZammadServiceDep,
)
from app.application.services.integration_catalog import CATALOG_BY_TYPE
from app.application.services.integrations import (
    IntegrationError,
    SourceSwitchConfirmationRequiredError,
)
from app.infrastructure.database.models.servicenow import ServiceNowConfigurationModel
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


class IntegrationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool = False
    configuration: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(default_factory=dict)


class IntegrationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    configuration: dict[str, Any] | None = None
    capabilities: dict[str, bool] | None = None


def _raise(exc: IntegrationError) -> Never:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if isinstance(exc, SourceSwitchConfirmationRequiredError):
        detail.update(
            {
                "stream": exc.stream,
                "current_source": exc.current_source,
                "requested_source": exc.requested_source,
            }
        )
    raise HTTPException(
        status_code=exc.status_code,
        detail=detail,
    ) from exc


@router.get("/catalog")
async def catalog(_: CurrentUser, service: IntegrationServiceDep) -> list[dict[str, Any]]:
    return await service.catalog()


@router.get("")
async def integrations(_: CurrentUser, service: IntegrationServiceDep) -> list[dict[str, Any]]:
    return await service.list_integrations()


@router.get("/streams")
async def streams(_: CurrentUser, service: IntegrationServiceDep) -> list[dict[str, Any]]:
    return await service.stream_sources()


class SourceSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False


@router.post("/{integration_id}/streams/{stream}/select")
async def select_source(
    integration_id: UUID,
    stream: str,
    request: SourceSelectionRequest,
    actor: Administrator,
    service: IntegrationServiceDep,
) -> dict[str, Any]:
    try:
        result = await service.select_source(
            integration_id,
            stream,
            confirmed=request.confirmed,
            actor=actor.username,
        )
        await _reconcile_zammad_schedules(service)
        await _reconcile_servicenow_schedules(service)
        return result
    except IntegrationError as exc:
        _raise(exc)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    request: IntegrationCreateRequest,
    actor: Administrator,
    service: IntegrationServiceDep,
) -> dict[str, Any]:
    try:
        return await service.create(request.model_dump(), actor.username)
    except IntegrationError as exc:
        _raise(exc)


@router.get("/{integration_id}")
async def detail(
    integration_id: UUID, _: CurrentUser, service: IntegrationServiceDep
) -> dict[str, Any]:
    try:
        model = await service.get(integration_id)
        return service._response(model)
    except IntegrationError as exc:
        _raise(exc)


@router.patch("/{integration_id}")
async def update(
    integration_id: UUID,
    request: IntegrationUpdateRequest,
    actor: Administrator,
    service: IntegrationServiceDep,
) -> dict[str, Any]:
    try:
        return await service.update(
            integration_id, request.model_dump(exclude_unset=True), actor.username
        )
    except IntegrationError as exc:
        _raise(exc)


@router.post("/{integration_id}/test")
async def test_connection(
    integration_id: UUID,
    actor: Administrator,
    integrations: IntegrationServiceDep,
    zammad: ZammadServiceDep,
    prometheus: PrometheusServiceDep,
    loki: LokiServiceDep,
    servicenow: ServiceNowServiceDep,
) -> dict[str, Any]:
    try:
        model = await integrations.get(integration_id)
        catalog_item = CATALOG_BY_TYPE[model.integration_type]
        if not catalog_item.get("available"):
            message = str(catalog_item.get("unavailable_reason") or "Adapter unavailable")
            await integrations.mark_test_result(model.id, False, message)
            raise IntegrationError("ADAPTER_UNAVAILABLE", message, 501)
        if model.integration_type == "zammad" and model.legacy_zammad_configuration_id:
            return await zammad.test(model.legacy_zammad_configuration_id)
        if model.integration_type == "servicenow":
            # An alternate source may be configured and tested before the user
            # confirms switching the stream to it.
            configuration = await servicenow._active_configuration(model.id, require_enabled=False)
            return await servicenow.test(configuration.id)
        legacy_id = model.configuration_json.get("legacy_id")
        if model.integration_type == "prometheus" and legacy_id:
            result = await prometheus.test(UUID(str(legacy_id)))
            await integrations.mark_test_result(model.id, True)
            return result
        if model.integration_type == "loki" and legacy_id:
            result = await loki.test(UUID(str(legacy_id)))
            await integrations.mark_test_result(model.id, True)
            return result
        if model.integration_type in {"documents", "generic_cmdb"}:
            raise IntegrationError(
                "TEST_NOT_APPLICABLE",
                "This local data integration does not have a remote connection to test.",
                409,
            )
        raise IntegrationError(
            "CONFIGURATION_NOT_LINKED",
            "This integration is not linked to a configured provider instance.",
            409,
        )
    except IntegrationError as exc:
        _raise(exc)


@router.post("/{integration_id}/enable")
async def enable(
    integration_id: UUID, actor: Administrator, service: IntegrationServiceDep
) -> dict[str, Any]:
    try:
        result = await service.set_enabled(integration_id, True, actor.username)
        await _reconcile_zammad_schedules(service)
        await _reconcile_servicenow_schedules(service)
        return result
    except IntegrationError as exc:
        _raise(exc)


@router.post("/{integration_id}/disable")
async def disable(
    integration_id: UUID, actor: Administrator, service: IntegrationServiceDep
) -> dict[str, Any]:
    try:
        result = await service.set_enabled(integration_id, False, actor.username)
        await _reconcile_zammad_schedules(service)
        await _reconcile_servicenow_schedules(service)
        return result
    except IntegrationError as exc:
        _raise(exc)


@router.post("/{integration_id}/sync")
async def sync(
    integration_id: UUID,
    _: Administrator,
    integrations: IntegrationServiceDep,
    zammad: ZammadServiceDep,
    servicenow: ServiceNowServiceDep,
) -> dict[str, Any]:
    try:
        model = await integrations.get(integration_id)
        if model.integration_type == "servicenow":
            configuration = await servicenow._active_configuration(model.id, require_enabled=True)
            return await servicenow.synchronize(configuration.id)
        if model.integration_type != "zammad" or model.legacy_zammad_configuration_id is None:
            raise IntegrationError(
                "ADAPTER_UNAVAILABLE",
                str(CATALOG_BY_TYPE[model.integration_type].get("unavailable_reason")),
                501,
            )
        return await zammad.synchronize(
            model.legacy_zammad_configuration_id, full=True, trigger="manual"
        )
    except IntegrationError as exc:
        _raise(exc)


async def _reconcile_zammad_schedules(service: IntegrationServiceDep) -> None:
    for item in await service.list_integrations():
        if item["integration_type"] == "zammad":
            model = await service.get(UUID(item["id"]))
            if model.legacy_zammad_configuration_id:
                await connector_scheduler.reconcile_zammad(model.legacy_zammad_configuration_id)


async def _reconcile_servicenow_schedules(service: IntegrationServiceDep) -> None:
    configuration_ids = (
        await service.session.scalars(select(ServiceNowConfigurationModel.id))
    ).all()
    for configuration_id in configuration_ids:
        await connector_scheduler.reconcile_servicenow(configuration_id)
