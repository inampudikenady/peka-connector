import json
import logging
import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

SECRET_PATTERN = re.compile(
    r"(?i)(password|secret|token|authorization|cookie)([\"'\s:=]+)([^\s,;}]+)"
)


def redact_text(value: str) -> str:
    return SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                term in key.casefold()
                for term in (
                    "password",
                    "secret",
                    "token",
                    "authorization",
                    "cookie",
                    "api_key",
                )
            )
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return sanitize(value.value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str, log_directory: Path | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    if log_directory is not None:
        log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        file_handler = logging.FileHandler(log_directory / "connector.jsonl", encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
