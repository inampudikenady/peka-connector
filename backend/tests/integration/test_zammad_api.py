import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.application.services.zammad import ZammadClient, ZammadService
from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import engine
from app.main import app

PASSWORD = "Strong!ZammadApiPass123"


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(_reset_database())
    auth_rate_limiter.reset()
    with TestClient(app) as instance:
        yield instance


def _headers(client: TestClient) -> dict[str, str]:
    created = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": PASSWORD, "confirm_password": PASSWORD},
    )
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_zammad_configuration_api_never_returns_token_and_exposes_actions(
    client: TestClient, monkeypatch
) -> None:
    headers = _headers(client)
    token = "temporary-secret-that-must-not-be-returned"
    created = client.post(
        "/api/v1/zammad/configurations",
        headers=headers,
        json={
            "name": "Operations Zammad",
            "base_url": "https://zammad.example.test///",
            "access_token": token,
            "tls_verify": True,
            "request_timeout_seconds": 10,
            "sync_interval_seconds": 300,
            "history_window_days": 90,
            "group_filters": ["Infrastructure"],
            "include_closed_tickets": True,
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    configuration = created.json()
    assert configuration["base_url"] == "https://zammad.example.test"
    assert configuration["token_configured"] is True
    assert token not in created.text
    assert "access_token" not in configuration
    configuration_id = configuration["id"]

    listed = client.get("/api/v1/zammad/configurations", headers=headers)
    assert listed.status_code == 200
    assert token not in listed.text

    async def validate(_client):
        return {"success": True, "readable_ticket_count": 1}

    monkeypatch.setattr(ZammadClient, "validate", validate)
    tested = client.post(f"/api/v1/zammad/configurations/{configuration_id}/test", headers=headers)
    assert tested.status_code == 200
    assert tested.json()["readable_ticket_count"] == 1

    async def synchronize(_service, _configuration_id):
        return {
            "ticket_count": 2,
            "article_count": 5,
            "duration_seconds": 0.1,
            "cache_timestamp": "2026-08-01T00:00:00Z",
            "live": True,
        }

    monkeypatch.setattr(ZammadService, "synchronize", synchronize)
    synchronized = client.post(
        f"/api/v1/zammad/configurations/{configuration_id}/sync", headers=headers
    )
    assert synchronized.status_code == 200
    assert synchronized.json()["article_count"] == 5

    deleted = client.delete(f"/api/v1/zammad/configurations/{configuration_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/zammad/configurations", headers=headers).json() == []
