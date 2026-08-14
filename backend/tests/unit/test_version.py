import sys
from importlib import metadata
from types import ModuleType

import pytest

from app.core import version


@pytest.mark.parametrize(
    "value",
    [
        "0.3.0",
        "0.4.0rc1",
        "0.4.0-rc.1",
        "0.4.0-beta.1",
        "0.3.0.dev0",
        "0.4.0-dev",
        "0.4.0-dev+abc123",
        "1.2.3+build.7",
    ],
)
def test_validate_connector_version_accepts_canonical_versions(value: str) -> None:
    assert version.validate_connector_version(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "latest", "v0.3.0", "0.3", "0.3.0-foo", "01.2.3"],
)
def test_validate_connector_version_rejects_ambiguous_versions(value: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        version.validate_connector_version(value)


def test_package_connector_version_uses_installed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version.metadata, "version", lambda _name: "1.2.3")
    assert version.package_connector_version() == "1.2.3"


def test_package_connector_version_has_development_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(version.metadata, "version", missing)
    assert version.package_connector_version() == version.DEVELOPMENT_VERSION
    assert version.DEVELOPMENT_VERSION == "2.0.1"


def test_package_connector_version_rejects_invalid_installed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version.metadata, "version", lambda _name: "latest")
    with pytest.raises(RuntimeError, match="Installed PEKA Connector version is invalid"):
        version.package_connector_version()


def test_runtime_connector_version_prefers_generated_build_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_module = ModuleType("app.core._build_version")
    build_module.BUILD_VERSION = "0.4.0-rc.1"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core._build_version", build_module)
    assert version.runtime_connector_version() == "0.4.0-rc.1"
