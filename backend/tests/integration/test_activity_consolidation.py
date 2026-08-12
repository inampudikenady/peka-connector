import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.operations import AuditEventModel
from app.infrastructure.database.session import engine, session_factory
from app.main import app

PASSWORD = "Strong!ActivityPass123"


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
    assert client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": PASSWORD, "confirm_password": PASSWORD},
    ).status_code == 201
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_request_events() -> str:
    request_id = str(uuid4())
    now = datetime.now(UTC)
    details = {
        "tool_name": "get_asset_status",
        "integration": "Prometheus",
        "target_asset": "util001",
    }
    async with session_factory() as session:
        session.add_all(
            [
                AuditEventModel(
                    event_type="operational_request.started",
                    target_type="operational_tool_request",
                    target_id=request_id,
                    message="get_asset_status request started",
                    details=details,
                    created_at=now - timedelta(milliseconds=42),
                ),
                AuditEventModel(
                    event_type="operational_request.succeeded",
                    target_type="operational_tool_request",
                    target_id=request_id,
                    message="get_asset_status request completed",
                    details={
                        **details,
                        "duration_ms": 42.0,
                        "result_summary": "Request completed",
                        "error_code": None,
                    },
                    created_at=now,
                ),
                AuditEventModel(
                    event_type="prometheus.sync_completed",
                    target_type="integration",
                    target_id="prometheus",
                    message="Prometheus synchronization completed",
                    details={"integration": "Prometheus"},
                    created_at=now,
                ),
            ]
        )
        await session.commit()
    return request_id


def test_activity_apis_keep_requests_events_and_summary_separate(
    client: TestClient,
) -> None:
    headers = _headers(client)
    request_id = asyncio.run(_seed_request_events())

    requests = client.get("/api/v1/operational-requests", headers=headers)
    assert requests.status_code == 200
    assert requests.json()["items"] == [
        {
            "request_id": request_id,
            "requested_at": requests.json()["items"][0]["requested_at"],
            "completed_at": requests.json()["items"][0]["completed_at"],
            "tool_name": "get_asset_status",
            "integration": "Prometheus",
            "target_asset": "util001",
            "status": "succeeded",
            "duration_ms": 42.0,
            "result_summary": "Request completed",
            "error_code": None,
        }
    ]
    events = client.get("/api/v1/activity", headers=headers)
    assert events.status_code == 200
    assert any(item["event_type"] == "prometheus.sync_completed" for item in events.json()["items"])
    summary = client.get("/api/v1/activity/overview", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["successful_requests_24h"] == 1
    assert summary.json()["last_completed_sync_at"] is not None
    logs = client.get("/api/v1/logs", headers=headers)
    assert logs.status_code == 200
    assert "items" in logs.json()
