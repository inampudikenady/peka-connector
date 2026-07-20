import logging

from fastapi import APIRouter

from app.api.dependencies import (
    Administrator,
    CurrentUser,
    OperationsDep,
    RegistrationServiceDep,
)
from app.api.schemas import (
    ActionResponse,
    ConfirmationRequest,
    ProductSettingsResponse,
    ProductSettingsUpdate,
    SaaSConnectivityRequest,
    SaaSRegistrationRequest,
)
from app.infrastructure.scheduling import connector_scheduler

router = APIRouter()


@router.get("", response_model=ProductSettingsResponse)
async def get_product_settings(_: CurrentUser, operations: OperationsDep) -> object:
    return await operations.get_settings()


@router.put("", response_model=ProductSettingsResponse)
async def update_product_settings(
    request: ProductSettingsUpdate,
    actor: Administrator,
    operations: OperationsDep,
) -> object:
    settings = await operations.update_settings(
        request.connector_display_name,
        request.environment_label,
        request.log_level,
        request.timezone,
    )
    logging.getLogger().setLevel(request.log_level)
    await operations.record_event(
        "settings.updated",
        "Connector settings updated",
        actor=actor,
        target_type="settings",
        target_id="1",
        component="settings",
    )
    return settings


@router.post("/saas/test", response_model=ActionResponse)
async def test_saas(
    request: SaaSConnectivityRequest,
    _: Administrator,
    service: RegistrationServiceDep,
) -> ActionResponse:
    await service.test_connectivity(request.saas_url)
    return ActionResponse(message="PEKA SaaS endpoint is reachable")


@router.post("/saas/register", response_model=ProductSettingsResponse)
async def register_saas(
    request: SaaSRegistrationRequest,
    actor: Administrator,
    service: RegistrationServiceDep,
    operations: OperationsDep,
) -> object:
    await service.register(
        request.saas_url,
        request.registration_token,
        request.connector_display_name,
        actor,
    )
    await operations.record_event(
        "connector.registered",
        "Connector registered with PEKA SaaS",
        actor=actor,
        target_type="connector",
        component="saas",
    )
    return await operations.get_settings()


@router.post("/saas/reregister", response_model=ProductSettingsResponse)
async def reregister_saas(
    request: SaaSRegistrationRequest,
    actor: Administrator,
    service: RegistrationServiceDep,
    operations: OperationsDep,
) -> object:
    await service.register(
        request.saas_url,
        request.registration_token,
        request.connector_display_name,
        actor,
        reregister=True,
        confirmed=request.confirmed,
    )
    await operations.record_event(
        "connector.reregistered",
        "Connector re-registered with PEKA SaaS",
        actor=actor,
        target_type="connector",
        component="saas",
    )
    return await operations.get_settings()


@router.post("/saas/unregister", response_model=ProductSettingsResponse)
async def unregister_saas(
    request: ConfirmationRequest,
    actor: Administrator,
    service: RegistrationServiceDep,
) -> object:
    return await service.unregister(request.confirmed, actor)


@router.post("/saas/retry", response_model=ProductSettingsResponse)
async def retry_heartbeat(
    actor: Administrator,
    operations: OperationsDep,
) -> object:
    product = await operations.get_settings()
    if not product.connector_id or not product.encrypted_connector_secret:
        from app.application.services.saas import RegistrationStateError

        raise RegistrationStateError("Connector is not registered")
    await operations.record_event(
        "heartbeat.retry_now",
        "Administrator requested an immediate heartbeat",
        actor=actor,
        target_type="connector",
        target_id=product.connector_id,
        component="heartbeat",
    )
    await connector_scheduler.retry_heartbeat_now()
    return await operations.refresh_settings()
