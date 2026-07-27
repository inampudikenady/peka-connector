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
from app.infrastructure.scheduling import HeartbeatInProgressError, connector_scheduler

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
    current = await operations.get_settings()
    name_changed = current.connector_display_name != request.connector_display_name
    settings = await operations.update_settings(
        request.connector_display_name,
        request.environment_label,
        request.log_level,
    )
    logging.getLogger().setLevel(request.log_level)
    await operations.record_event(
        "settings.updated",
        "Connector settings updated",
        actor=actor,
        target_type="settings",
        target_id="1",
        details={"connector_display_name": settings.connector_display_name},
        component="settings",
    )
    if name_changed:
        await operations.record_event(
            "connector.display_name_changed",
            f"Connector display name changed to {settings.connector_display_name}",
            actor=actor,
            target_type="connector",
            target_id=settings.instance_id,
            component="settings",
        )
    warning: str | None = None
    if name_changed and settings.connector_id and settings.encrypted_connector_secret:
        try:
            await connector_scheduler.retry_heartbeat_now()
        except HeartbeatInProgressError:
            warning = (
                "Connector name was saved locally. An active heartbeat will synchronize it "
                "with PEKA."
            )
        except Exception:
            warning = (
                "Connector name was saved locally, but PEKA could not be updated. "
                "A later heartbeat will retry automatically."
            )
            await operations.record_event(
                "connector.metadata_sync_deferred",
                "Connector name saved locally; PEKA metadata update deferred",
                actor=actor,
                target_type="connector",
                target_id=settings.connector_id,
                details={"connector_display_name": settings.connector_display_name},
                level="WARNING",
                component="heartbeat",
            )
        settings = await operations.refresh_settings()
        if settings.last_heartbeat_status == "failed":
            warning = (
                "Connector name was saved locally, but PEKA could not be updated. "
                "A later heartbeat will retry automatically."
            )
    response = ProductSettingsResponse.model_validate(settings).model_dump()
    response["metadata_sync_warning"] = warning
    return response


@router.post("/saas/test", response_model=ActionResponse)
async def test_saas(
    request: SaaSConnectivityRequest,
    _: Administrator,
    service: RegistrationServiceDep,
) -> ActionResponse:
    await service.test_connectivity(request.saas_url)
    return ActionResponse(message="PEKA endpoint is reachable")


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
        actor,
    )
    await operations.record_event(
        "connector.registered",
        "Connector registered with PEKA",
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
        actor,
        reregister=True,
        confirmed=request.confirmed,
    )
    await operations.record_event(
        "connector.reregistered",
        "Connector re-registered with PEKA",
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
