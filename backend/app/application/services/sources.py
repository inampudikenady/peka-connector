from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.domain.entities.document import DiscoveredDocument
from app.domain.entities.source import ScanRecord, Source
from app.domain.ports.repositories import DocumentRepository, ScanRepository, SourceRepository
from app.plugins.errors import PluginError
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
        scans: ScanRepository,
        plugins: PluginRegistry,
    ) -> None:
        self._sources = sources
        self._documents = documents
        self._scans = scans
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
        source = await self._sources.create(
            plugin_type, name, enabled, config.model_dump(mode="json")
        )
        return await self._sources.update_operational_status(source.id, "healthy", None)

    async def validate_configuration(self, plugin_type: str, configuration: dict[str, Any]) -> None:
        plugin = self._plugins.get(plugin_type)
        config = plugin.parse_config(configuration)
        await plugin.validate(config)

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
        updated = await self._sources.update(
            source_id, name, enabled, config.model_dump(mode="json")
        )
        return await self._sources.update_operational_status(updated.id, "healthy", None)

    async def delete_source(self, source_id: UUID) -> None:
        await self.get_source(source_id)
        await self._sources.delete(source_id)

    async def validate_source(self, source_id: UUID) -> Source:
        source = await self.get_source(source_id)
        plugin = self._plugins.get(source.plugin_type)
        config = plugin.parse_config(source.configuration)
        try:
            await plugin.validate(config)
        except Exception as exc:
            await self._sources.update_operational_status(source.id, "unhealthy", str(exc)[:2000])
            raise
        return await self._sources.update_operational_status(source.id, "healthy", None)

    async def scan(self, source_id: UUID) -> ScanRecord:
        source = await self.get_source(source_id)
        if not source.enabled:
            raise DisabledSourceError("Enable the source before scanning")
        scan = await self._scans.start(source.id)
        plugin = self._plugins.get(source.plugin_type)
        config = plugin.parse_config(source.configuration)
        try:
            batch = await plugin.discover_batch(config)
            discovered = list(batch.documents)
            counts = await self._documents.reconcile_for_source(source.id, discovered)
            counts["failed"] = batch.failed_count
            completed = await self._scans.complete(scan.id, counts, len(discovered))
            health_status = "degraded" if batch.failed_count else "healthy"
            last_error = (
                f"{batch.failed_count} file(s) could not be read" if batch.failed_count else None
            )
            await self._sources.update_operational_status(
                source.id,
                health_status,
                last_error,
                file_count=len(discovered),
                success=True,
            )
            return completed
        except Exception as exc:
            message = str(exc)[:2000] or "Source scan failed"
            await self._scans.fail(scan.id, message)
            await self._sources.update_operational_status(source.id, "unhealthy", message)
            if isinstance(exc, PluginError):
                raise
            raise PluginError(message) from exc

    async def list_documents(self, source_id: UUID) -> Sequence[DiscoveredDocument]:
        await self.get_source(source_id)
        return await self._documents.list_for_source(source_id)

    async def list_scan_history(self, source_id: UUID) -> Sequence[ScanRecord]:
        await self.get_source(source_id)
        return await self._scans.list_for_source(source_id)
