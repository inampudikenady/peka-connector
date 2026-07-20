from typing import Any

from app.domain.ports.plugins import SourcePlugin
from app.plugins.errors import PluginNotFoundError


class PluginRegistry:
    """In-process registry of trusted plugins shipped with the connector."""

    def __init__(self) -> None:
        self._plugins: dict[str, SourcePlugin[Any]] = {}

    def register(self, plugin: SourcePlugin[Any]) -> None:
        if plugin.plugin_type in self._plugins:
            raise ValueError(f"Plugin already registered: {plugin.plugin_type}")
        self._plugins[plugin.plugin_type] = plugin

    def get(self, plugin_type: str) -> SourcePlugin[Any]:
        try:
            return self._plugins[plugin_type]
        except KeyError as exc:
            raise PluginNotFoundError(f"Unknown plugin type: {plugin_type}") from exc

    def list(self) -> tuple[SourcePlugin[Any], ...]:
        return tuple(self._plugins.values())


plugin_registry = PluginRegistry()
