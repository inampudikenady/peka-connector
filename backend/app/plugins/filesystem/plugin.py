import asyncio
import fnmatch
import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from app.domain.entities.document import DiscoveredDocument
from app.domain.ports.plugins import SourcePlugin
from app.plugins.errors import PluginValidationError
from app.plugins.filesystem.config import FilesystemSourceConfig

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".markdown"})


class FilesystemDocumentSourcePlugin(SourcePlugin[FilesystemSourceConfig]):
    plugin_type = "filesystem_documents"
    display_name = "Filesystem Document Source"
    config_model = FilesystemSourceConfig

    async def validate(self, config: FilesystemSourceConfig) -> None:
        path = config.path
        if not await asyncio.to_thread(path.exists):
            raise PluginValidationError(f"Path does not exist: {path}")
        if not await asyncio.to_thread(path.is_dir):
            raise PluginValidationError(f"Path is not a directory: {path}")
        if not os.access(path, os.R_OK | os.X_OK):
            raise PluginValidationError(f"Path is not readable: {path}")

    async def discover(self, config: FilesystemSourceConfig) -> AsyncIterator[DiscoveredDocument]:
        await self.validate(config)
        root = config.path.resolve()
        paths = await asyncio.to_thread(self._collect_paths, root, config)
        for path in paths:
            try:
                document = await asyncio.to_thread(self._metadata, root, path)
            except (OSError, PermissionError):
                continue
            yield document

    @staticmethod
    def _collect_paths(root: Path, config: FilesystemSourceConfig) -> list[Path]:
        matches: list[Path] = []
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(directory)
            dirnames[:] = [
                name
                for name in dirnames
                if not FilesystemDocumentSourcePlugin._excluded(
                    (current / name).relative_to(root).as_posix(), config.exclude_patterns
                )
            ]
            for filename in filenames:
                path = current / filename
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if FilesystemDocumentSourcePlugin._excluded(relative, config.exclude_patterns):
                    continue
                if any(
                    FilesystemDocumentSourcePlugin._matches(relative, pattern)
                    for pattern in config.include_patterns
                ):
                    matches.append(path)
        return sorted(matches)

    @staticmethod
    def _excluded(relative_path: str, patterns: list[str]) -> bool:
        return any(
            FilesystemDocumentSourcePlugin._matches(relative_path, pattern) for pattern in patterns
        )

    @staticmethod
    def _matches(relative_path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(relative_path, pattern) or (
            pattern.startswith("**/") and fnmatch.fnmatch(relative_path, pattern[3:])
        )

    @staticmethod
    def _metadata(root: Path, path: Path) -> DiscoveredDocument:
        stat = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return DiscoveredDocument(
            relative_path=path.relative_to(root).as_posix(),
            filename=path.name,
            extension=path.suffix.lower().lstrip("."),
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            sha256=digest.hexdigest(),
        )
