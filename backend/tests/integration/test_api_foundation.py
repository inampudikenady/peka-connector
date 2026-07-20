import asyncio
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
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


def test_first_run_login_refresh_logout_and_password_change(client: TestClient) -> None:
    assert client.get("/api/v1/auth/setup-status").json() == {"setup_required": True}
    invalid = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "x", "password": "weak", "confirm_password": "different"},
    )
    assert invalid.status_code == 422
    _bootstrap(client)
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


def test_multiple_sources_manual_scan_metadata_and_history(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    root = get_settings().sources_root
    manuals = root / "manuals"
    contracts = root / "contracts"
    manuals.mkdir(exist_ok=True)
    contracts.mkdir(exist_ok=True)
    document = manuals / "guide.txt"
    document.write_text("version one", encoding="utf-8")

    def create(name: str, path: Path) -> dict[str, object]:
        response = client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "plugin_type": "filesystem_documents",
                "name": name,
                "enabled": True,
                "configuration": {
                    "path": str(path),
                    "include_patterns": ["**/*.txt"],
                    "exclude_patterns": ["**/archive/**"],
                    "scan_interval_seconds": 300,
                },
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = create("Manuals", manuals)
    create("Contracts", contracts)
    assert len(client.get("/api/v1/sources", headers=headers).json()) == 2
    source_id = first["id"]
    scan = client.post(f"/api/v1/sources/{source_id}/scan", headers=headers).json()
    assert scan["added_count"] == 1
    scan = client.post(f"/api/v1/sources/{source_id}/scan", headers=headers).json()
    assert scan["unchanged_count"] == 1
    document.write_text("version two", encoding="utf-8")
    scan = client.post(f"/api/v1/sources/{source_id}/scan", headers=headers).json()
    assert scan["changed_count"] == 1
    document.unlink()
    scan = client.post(f"/api/v1/sources/{source_id}/scan", headers=headers).json()
    assert scan["missing_count"] == 1
    metadata = client.get(f"/api/v1/sources/{source_id}/documents", headers=headers).json()
    assert metadata[0]["state"] == "missing"
    history = client.get(f"/api/v1/sources/{source_id}/scans", headers=headers).json()
    assert len(history) == 4


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
