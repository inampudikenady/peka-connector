from fastapi import APIRouter

from app.api.dependencies import CurrentUser
from app.api.schemas import PluginResponse
from app.plugins.registry import plugin_registry

router = APIRouter()


@router.get("", response_model=list[PluginResponse])
async def list_plugins(_: CurrentUser) -> list[PluginResponse]:
    return [
        PluginResponse(
            plugin_type=plugin.plugin_type,
            display_name=plugin.display_name,
            configuration_schema=plugin.config_model.model_json_schema(),
        )
        for plugin in plugin_registry.list()
    ]
