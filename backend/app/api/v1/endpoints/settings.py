import logging

from fastapi import APIRouter, status

from app.api.dependencies import Administrator, CurrentUser, OperationsDep
from app.api.schemas import ProductSettingsResponse, ProductSettingsUpdate
from app.application.services.saas import UnavailableSaaSRegistrationService

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
        request.saas_url,
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


@router.post("/saas/register", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
async def register_saas(_: Administrator) -> None:
    await UnavailableSaaSRegistrationService().register()


@router.post("/saas/unregister", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
async def unregister_saas(_: Administrator) -> None:
    await UnavailableSaaSRegistrationService().unregister()
