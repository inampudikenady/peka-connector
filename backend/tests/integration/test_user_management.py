import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import auth_rate_limiter
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


def _bootstrap_and_login(client: TestClient) -> tuple[dict[str, str], dict[str, object]]:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "confirm_password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, client.get("/api/v1/auth/me", headers=headers).json()


def test_local_user_lifecycle_and_password_secrecy(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401
    headers, current = _bootstrap_and_login(client)

    password = "Temporary!Pass123"
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "operator",
            "password": password,
            "confirm_password": password,
            "role": "administrator",
            "enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["username"] == "operator"
    assert body["role"] == "administrator"
    assert body["is_active"] is False
    assert "password" not in body
    assert password not in created.text

    users = client.get("/api/v1/users", headers=headers)
    assert users.status_code == 200
    assert {item["username"] for item in users.json()} == {"admin", "operator"}
    assert all("password" not in item for item in users.json())
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": password},
        ).status_code
        == 401
    )

    duplicate = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "operator",
            "password": password,
            "confirm_password": password,
            "role": "administrator",
        },
    )
    assert duplicate.status_code == 409
    mismatch = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "another",
            "password": password,
            "confirm_password": "Different!Pass123",
            "role": "administrator",
        },
    )
    assert mismatch.status_code == 422

    user_id = body["id"]
    enabled = client.put(
        f"/api/v1/users/{user_id}/state",
        headers=headers,
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    disabled = client.put(
        f"/api/v1/users/{user_id}/state",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    client.put(
        f"/api/v1/users/{user_id}/state",
        headers=headers,
        json={"enabled": True},
    )

    replacement = "Replacement!Pass456"
    reset = client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=headers,
        json={"password": replacement, "confirm_password": replacement},
    )
    assert reset.status_code == 204
    assert replacement not in reset.text
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": password},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": replacement},
        ).status_code
        == 200
    )

    # Self-service lockout protection applies even while another administrator exists.
    self_disable = client.put(
        f"/api/v1/users/{current['id']}/state",
        headers=headers,
        json={"enabled": False},
    )
    assert self_disable.status_code == 409
    assert "own account" in self_disable.json()["detail"]
    assert client.delete(f"/api/v1/users/{current['id']}", headers=headers).status_code == 409

    logs = client.get("/api/v1/logs?component=users", headers=headers)
    assert logs.status_code == 200
    assert password not in logs.text
    assert replacement not in logs.text

    deleted = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert deleted.status_code == 204
    assert [item["username"] for item in client.get("/api/v1/users", headers=headers).json()] == [
        "admin"
    ]

