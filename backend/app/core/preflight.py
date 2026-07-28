"""Startup checks that must run before Alembic touches the SQLite database."""

from __future__ import annotations

import json
import os
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple


class DiskCheck(NamedTuple):
    ok: bool
    free_bytes: int
    required_bytes: int
    database_path: Path


def database_path_from_url(database_url: str) -> Path:
    value = database_url.removeprefix("sqlite+aiosqlite:///")
    if value == database_url or value == ":memory:":
        raise ValueError("Startup disk preflight requires a file-backed SQLite database")
    return Path(value).expanduser().resolve()


def check_migration_disk_space(
    database_url: str,
    minimum_free_bytes: int,
) -> DiskCheck:
    database_path = database_path_from_url(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_size = database_path.stat().st_size if database_path.exists() else 0
    # SQLite migrations may briefly need the database, journal/WAL, and copied
    # table data at the same time. Keep a fixed reserve as well as 2x DB growth.
    required = max(minimum_free_bytes, (database_size * 2) + (64 * 1024 * 1024))
    free = shutil.disk_usage(database_path.parent).free
    return DiskCheck(free >= required, free, required, database_path)


def _health_payload(check: DiskCheck) -> dict[str, object]:
    return {
        "status": "unhealthy",
        "code": "INSUFFICIENT_DISK_SPACE",
        "message": (
            "Database migration was not started because the connector data volume "
            "does not have enough free space."
        ),
        "free_bytes": check.free_bytes,
        "required_bytes": check.required_bytes,
        "database_path": str(check.database_path),
    }


def _write_marker(data_root: Path, payload: dict[str, object]) -> None:
    state_root = data_root / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    marker = state_root / "startup-health.json"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(marker)


def serve_unhealthy(payload: dict[str, object], port: int = 8080) -> None:
    encoded = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, message_format: str, *args: object) -> None:
            del message_format, args
            return

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main() -> None:
    database_url = os.getenv("PEKA_DATABASE_URL", "sqlite+aiosqlite:////data/state/peka.db")
    minimum_free = int(os.getenv("PEKA_MINIMUM_FREE_DISK_BYTES", str(256 * 1024 * 1024)))
    data_root = Path(os.getenv("PEKA_DATA_ROOT", "/data"))
    check = check_migration_disk_space(database_url, minimum_free)
    marker = data_root / "state" / "startup-health.json"
    if check.ok:
        marker.unlink(missing_ok=True)
        print(
            "Startup disk preflight passed: "
            f"{check.free_bytes} bytes free; {check.required_bytes} required.",
            flush=True,
        )
        return

    payload = _health_payload(check)
    _write_marker(data_root, payload)
    print(
        "Startup blocked: INSUFFICIENT_DISK_SPACE "
        f"({check.free_bytes} bytes free; {check.required_bytes} required). "
        "Serving an unhealthy health endpoint; migrations were not run.",
        flush=True,
    )
    serve_unhealthy(payload)


if __name__ == "__main__":
    main()
