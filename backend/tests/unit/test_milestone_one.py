import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.services.inventory import InventoryService
from app.application.services.prometheus import (
    PrometheusService,
    endpoint_warnings,
)
from app.core.preflight import check_migration_disk_space


def test_internal_http_is_allowed_with_a_warning() -> None:
    assert "internal" in endpoint_warnings("http://prometheus:9090")[0]
    assert "internal" in endpoint_warnings("http://10.20.30.40:9090")[0]
    assert endpoint_warnings("https://prometheus.example.com") == []


def test_network_errors_are_classified_for_operators() -> None:
    refused = PrometheusService._network_error(ConnectionRefusedError())
    dns = PrometheusService._network_error(socket.gaierror("name not known"))
    assert refused.code == "CONNECTION_REFUSED"
    assert dns.code == "DNS_RESOLUTION_FAILED"


def test_exporter_service_inference_uses_port_and_job_hints() -> None:
    assert InventoryService._service_type(9100, "servers") == "node_exporter"
    assert InventoryService._service_type(443, "windows-exporter") == "windows_exporter"
    assert InventoryService._service_type(3100, "logs") == "loki"
    assert InventoryService._service_type(8443, "custom") == "metrics_endpoint"


def test_disk_preflight_accounts_for_database_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "peka.db"
    database.write_bytes(b"x" * 1024)

    def disk_usage(_: Path) -> SimpleNamespace:
        return SimpleNamespace(free=100, total=1000, used=900)

    monkeypatch.setattr("app.core.preflight.shutil.disk_usage", disk_usage)
    result = check_migration_disk_space(f"sqlite+aiosqlite:///{database}", minimum_free_bytes=200)
    assert result.ok is False
    assert result.free_bytes == 100
    assert result.required_bytes >= 64 * 1024 * 1024
