import hashlib

import pytest

from app.plugins.errors import PluginValidationError
from app.plugins.filesystem.config import FilesystemSourceConfig
from app.plugins.filesystem.plugin import FilesystemDocumentSourcePlugin


@pytest.mark.asyncio
async def test_discovers_supported_documents_and_metadata(tmp_path) -> None:
    content = b"PEKA metadata only"
    document = tmp_path / "guide.txt"
    document.write_bytes(content)
    (tmp_path / "image.png").write_bytes(b"ignored")
    excluded = tmp_path / "private"
    excluded.mkdir()
    (excluded / "secret.md").write_text("ignored", encoding="utf-8")
    config = FilesystemSourceConfig(
        path=tmp_path,
        exclude_patterns=["private/**"],
    )

    discovered = [item async for item in FilesystemDocumentSourcePlugin().discover(config)]

    assert len(discovered) == 1
    assert discovered[0].relative_path == "guide.txt"
    assert discovered[0].filename == "guide.txt"
    assert discovered[0].extension == "txt"
    assert discovered[0].size_bytes == len(content)
    assert discovered[0].sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_rejects_missing_path(tmp_path) -> None:
    config = FilesystemSourceConfig(path=tmp_path / "missing")

    with pytest.raises(PluginValidationError, match="does not exist"):
        await FilesystemDocumentSourcePlugin().validate(config)


def test_requires_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        FilesystemSourceConfig(path="relative")
