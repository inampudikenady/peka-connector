import asyncio
import io
import logging
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_knowledge_service
from app.core.config import get_settings
from app.core.rate_limit import auth_rate_limiter
from app.core.version import CONNECTOR_VERSION
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import engine
from app.main import app

ADMIN_PASSWORD = "Strong!LocalPass123"


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(_reset_database())
    auth_rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client


def _bootstrap(client: TestClient, username: str = "admin") -> None:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "username": username,
            "password": ADMIN_PASSWORD,
            "confirm_password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text


def _login(
    client: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD
) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_runtime_version_is_consistent_across_apis(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["version"] == CONNECTOR_VERSION
    assert health.json()["status"] in {"healthy", "degraded"}
    assert health.json()["components"]["connector"] == {"status": "healthy"}
    assert "local_knowledge_store" in health.json()["components"]
    component_versions = client.get("/api/v1/version")
    assert component_versions.status_code == 200
    assert component_versions.json() == {
        "peka_connector": CONNECTOR_VERSION,
        "components": {"qdrant": "Unknown"},
    }

    _bootstrap(client)
    headers = _login(client)
    overview = client.get("/api/v1/overview", headers=headers)
    diagnostics = client.get("/api/v1/diagnostics", headers=headers)
    assert overview.status_code == 200
    assert diagnostics.status_code == 200
    assert overview.json()["connector_version"] == CONNECTOR_VERSION
    assert overview.json()["peka_connector"] == "1.0.2"
    assert overview.json()["components"]["qdrant"] == "Unknown"
    assert overview.json()["knowledge_store"]["status"] == "unavailable"
    assert diagnostics.json()["version"] == CONNECTOR_VERSION


def test_overview_exposes_structured_healthy_knowledge_store(client: TestClient) -> None:
    indexed_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    searched_at = datetime(2026, 8, 12, 12, 5, tzinfo=UTC)

    class FakeKnowledgeService:
        settings = SimpleNamespace(qdrant_collection="peka_documents")

        async def stats(self):
            return SimpleNamespace(
                qdrant_reachable=True,
                collection_available=True,
                statistics_readable=True,
                search_operational=True,
                engine_version="runtime-version",
                document_count=1,
                indexed_chunk_count=2,
                pending_count=0,
                failed_count=0,
                last_index_activity=indexed_at,
                last_search_at=searched_at,
            )

    app.dependency_overrides[get_knowledge_service] = lambda: FakeKnowledgeService()
    try:
        _bootstrap(client)
        response = client.get("/api/v1/overview", headers=_login(client))
        assert response.status_code == 200
        payload = response.json()
        assert payload["peka_connector"] == "1.0.2"
        assert payload["components"] == {"qdrant": "runtime-version"}
        assert payload["knowledge_store"] == {
            "status": "healthy",
            "engine": "qdrant",
            "engine_version": "runtime-version",
            "collection": "peka_documents",
            "documents": 1,
            "chunks": 2,
            "pending": 0,
            "failed": 0,
            "last_indexed_at": "2026-08-12T12:00:00Z",
            "last_search_at": "2026-08-12T12:05:00Z",
            "checks": {
                "qdrant_reachable": True,
                "collection_exists": True,
                "collection_accessible": True,
                "statistics_readable": True,
                "search_service_operational": True,
            },
        }
    finally:
        app.dependency_overrides.pop(get_knowledge_service, None)


def test_startup_log_includes_runtime_version(caplog: pytest.LogCaptureFixture) -> None:
    asyncio.run(_reset_database())
    auth_rate_limiter.reset()
    with caplog.at_level(logging.INFO, logger="app.main"), TestClient(app):
        pass
    assert (
        f"PEKA Connector starting version={CONNECTOR_VERSION} "
        f"environment={get_settings().environment}"
    ) in caplog.messages


def test_first_run_login_refresh_logout_and_password_change(client: TestClient) -> None:
    assert client.get("/api/v1/auth/setup-status").json() == {"setup_required": True}
    invalid = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "x", "password": "weak", "confirm_password": "different"},
    )
    assert invalid.status_code == 422
    _bootstrap(client)
    activity = client.get("/api/v1/activity", headers=_login(client))
    assert activity.status_code == 200
    activity_payload = activity.json()
    assert activity_payload["total"] >= 2
    assert all(item["created_at"].endswith("Z") for item in activity_payload["items"])
    assert [item["created_at"] for item in activity_payload["items"]] == sorted(
        [item["created_at"] for item in activity_payload["items"]], reverse=True
    )
    assert all("details" not in item for item in activity_payload["items"])
    assert ADMIN_PASSWORD not in activity.text
    assert client.get("/api/v1/auth/setup-status").json() == {"setup_required": False}
    assert (
        client.post(
            "/api/v1/auth/bootstrap",
            json={
                "username": "second",
                "password": "Another!StrongPass123",
                "confirm_password": "Another!StrongPass123",
            },
        ).status_code
        == 409
    )

    headers = _login(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "administrator"
    csrf = client.cookies.get("peka_csrf")
    assert csrf
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200
    refreshed_headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    new_password = "Changed!LocalPass456"
    changed = client.post(
        "/api/v1/auth/change-password",
        headers=refreshed_headers,
        json={
            "current_password": ADMIN_PASSWORD,
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )
    assert changed.status_code == 204
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        ).status_code
        == 401
    )
    headers = _login(client, password=new_password)
    csrf = client.cookies.get("peka_csrf")
    assert (
        client.post(
            "/api/v1/auth/logout", headers={**headers, "X-CSRF-Token": str(csrf)}
        ).status_code
        == 204
    )


def test_role_enforcement_and_last_administrator_safeguards(client: TestClient) -> None:
    _bootstrap(client)
    admin_headers = _login(client)
    admin = client.get("/api/v1/auth/me", headers=admin_headers).json()
    assert (
        client.put(
            f"/api/v1/users/{admin['id']}/state",
            headers=admin_headers,
            json={"enabled": False},
        ).status_code
        == 409
    )
    assert client.delete(f"/api/v1/users/{admin['id']}", headers=admin_headers).status_code == 409

    reader_password = "Viewer!StrongPass123"
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "reader",
            "password": reader_password,
            "confirm_password": reader_password,
            "role": "read_only",
        },
    )
    assert created.status_code == 201, created.text
    reader_headers = _login(client, "reader", reader_password)
    assert client.get("/api/v1/sources", headers=reader_headers).status_code == 200
    assert client.get("/api/v1/diagnostics", headers=reader_headers).status_code == 200
    assert client.get("/api/v1/users", headers=reader_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/sources",
            headers=reader_headers,
            json={
                "plugin_type": "filesystem_documents",
                "name": "Forbidden",
                "enabled": True,
                "configuration": {
                    "path": str(get_settings().sources_root),
                    "include_patterns": ["**/*.txt"],
                    "exclude_patterns": [],
                    "scan_interval_seconds": 300,
                },
            },
        ).status_code
        == 403
    )


def test_generic_filesystem_source_creation_is_unavailable(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "plugin_type": "filesystem_documents",
            "name": "Manuals",
            "enabled": True,
            "configuration": {
                "path": str(get_settings().sources_root / "manuals"),
                "include_patterns": ["**/*.txt"],
                "exclude_patterns": [],
                "scan_interval_seconds": 300,
            },
        },
    )
    assert response.status_code == 409
    assert "not available" in response.json()["detail"]
    assert client.get("/api/v1/sources", headers=headers).json() == []


def test_read_only_cannot_mutate_saas_registration(client: TestClient) -> None:
    _bootstrap(client)
    admin_headers = _login(client)
    password = "Viewer!StrongPass123"
    client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "registration-reader",
            "password": password,
            "confirm_password": password,
            "role": "read_only",
        },
    )
    reader_headers = _login(client, "registration-reader", password)
    assert client.get("/api/v1/settings", headers=reader_headers).status_code == 200
    response = client.post(
        "/api/v1/settings/saas/register",
        headers=reader_headers,
        json={
            "saas_url": "https://saas.example.test",
            "registration_token": "must-not-be-accepted",
        },
    )
    assert response.status_code == 403
    assert (
        client.post(
            "/api/v1/settings/saas/test",
            headers=reader_headers,
            json={"saas_url": "https://saas.example.test"},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/settings/saas/retry", headers=reader_headers).status_code == 403


def test_diagnostics_bundle_is_sanitized(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    response = client.get("/api/v1/diagnostics/bundle", headers=headers)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {"diagnostics.json", "configuration.json", "recent-logs.json"} <= names
        combined = "".join(archive.read(name).decode("utf-8") for name in names)
    assert "password_hash" not in combined
    assert get_settings().jwt_secret.get_secret_value() not in combined
    assert client.cookies.get("peka_refresh") not in combined
