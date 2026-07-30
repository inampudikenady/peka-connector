import re
from importlib import import_module, metadata

DEVELOPMENT_VERSION = "0.3.0.dev0"
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:(?:a|b|rc)\d+|\.dev\d+|-(?:(?:alpha|beta|a|b|rc)\.?\d+|dev(?:\.\d+)?))?"
    r"(?:\+[a-z0-9]+(?:[.-][a-z0-9]+)*)?$"
)


def validate_connector_version(value: str) -> str:
    if not _VERSION_PATTERN.fullmatch(value):
        raise ValueError(
            "Connector version must be canonical PEP 440 / semantic form, "
            "for example 0.3.0, 0.4.0-rc.1, or 0.3.0-dev."
        )
    return value


def package_connector_version() -> str:
    try:
        value = metadata.version("peka-connector")
    except metadata.PackageNotFoundError:
        value = DEVELOPMENT_VERSION
    try:
        return validate_connector_version(value)
    except ValueError as exc:
        raise RuntimeError(f"Installed PEKA Connector version is invalid: {value!r}") from exc


def runtime_connector_version() -> str:
    try:
        build_module = import_module("app.core._build_version")
    except ModuleNotFoundError as exc:
        if exc.name != "app.core._build_version":
            raise
        return package_connector_version()
    build_version = getattr(build_module, "BUILD_VERSION", None)
    if not isinstance(build_version, str):
        raise RuntimeError("Built PEKA Connector version is missing or invalid")
    try:
        return validate_connector_version(build_version)
    except ValueError as exc:
        raise RuntimeError(f"Built PEKA Connector version is invalid: {build_version!r}") from exc


CONNECTOR_VERSION = runtime_connector_version()
