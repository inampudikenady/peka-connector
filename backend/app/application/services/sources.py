from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.domain.entities.document import DiscoveredDocument
from app.domain.entities.source import Source
from app.domain.ports.repositories import DocumentRepository, SourceRepository
from app.plugins.registry import PluginRegistry


class SourceNotFoundError(Exception):
    pass


class DisabledSourceError(Exception):
    pass


class SourceService:
    def __init__(
        self,
        sources: SourceRepository,
        documents: DocumentRepository,
        plugins: PluginRegistry,
    ) -> None:
        self._sources = sources
        self._documents = documents
        self._plugins = plugins

    async def list_sources(self) -> Sequence[Source]:
        return await self._sources.list()

    async def get_source(self, source_id: UUID) -> Source:
        source = await self._sources.get(source_id)
        if source is None:
            raise SourceNotFoundError(f"Source not found: {source_id}")
        return source

    async def create_source(
        self,
        plugin_type: str,
        name: str,
        enabled: bool,
        configuration: dict[str, Any],
    ) -> Source:
        plugin = self._plugins.get(plugin_type)
        config = plugin.parse_config(configuration)
        await plugin.validate(config)
        return await self._sources.create(
            plugin_type, name, enabled, config.model_dump(mode="json")
        )

    async def update_source(
        self,
        source_id: UUID,
        name: str,
        enabled: bool,
        configuration: dict[str, Any],
    ) -> Source:
        source = await self.get_source(source_id)
        plugin = self._plugins.get(source.plugin_type)
        config = plugin.parse_config(configuration)
        await plugin.validate(config)
        return await self._sources.update(source_id, name, enabled, config.model_dump(mode="json"))

    async def delete_source(self, source_id: UUID) -> None:
        await self.get_source(source_id)
        await self._sources.delete(source_id)

    async def scan(self, source_id: UUID) -> int:
        source = await self.get_source(source_id)
        if not source.enabled:
            raise DisabledSourceError("Enable the source before scanning")
        plugin = self._plugins.get(source.plugin_type)
        config = plugin.parse_config(source.configuration)
        discovered = [document async for document in plugin.discover(config)]
        return await self._documents.replace_for_source(source.id, discovered)

    async def list_documents(self, source_id: UUID) -> Sequence[DiscoveredDocument]:
        await self.get_source(source_id)
        return await self._documents.list_for_source(source_id)
