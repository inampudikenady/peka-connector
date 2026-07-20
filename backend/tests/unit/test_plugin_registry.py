import pytest

from app.plugins.errors import PluginNotFoundError
from app.plugins.filesystem import FilesystemDocumentSourcePlugin
from app.plugins.registry import PluginRegistry


def test_registers_and_resolves_plugin() -> None:
    registry = PluginRegistry()
    plugin = FilesystemDocumentSourcePlugin()

    registry.register(plugin)

    assert registry.get("filesystem_documents") is plugin


def test_unknown_plugin_is_domain_error() -> None:
    with pytest.raises(PluginNotFoundError):
        PluginRegistry().get("unknown")
