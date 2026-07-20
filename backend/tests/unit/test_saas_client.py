import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.domain.ports.saas import (
    ConnectorHeartbeatRequest,
    ConnectorRegistrationRequest,
    SaaSClientError,
    SourceHeartbeatSummary,
)
from app.infrastructure.saas.client import HttpxPEKASaaSClient


def client_for(handler: httpx.AsyncBaseTransport) -> HttpxPEKASaaSClient:
    return HttpxPEKASaaSClient(1, 1, transport=handler)


@pytest.mark.asyncio
async def test_final_registration_contract_serialization_and_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "connector_id": "7dca1b71-b55d-48d6-a20b-bf7cb5552368",
                "tenant_id": "81ef3567-bcf6-4376-b2ea-887b3c913fe9",
                "connector_secret": "one-time-connector-secret",
                "heartbeat_interval_seconds": 300,
                "registered_at": "2026-07-20T12:00:00Z",
            },
        )

    client = client_for(httpx.MockTransport(handler))
    response = await client.register_connector(
        "https://saas.example.test",
        ConnectorRegistrationRequest(
            registration_token="one-time-registration-token",
            connector_name="PEKA Connector",
            connector_version="0.2.0",
            environment="production",
            instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
            capabilities=["filesystem_documents"],
        ),
    )
    assert captured == {
        "path": "/api/v1/connectors/register",
        "body": {
            "registration_token": "one-time-registration-token",
            "connector_name": "PEKA Connector",
            "connector_version": "0.2.0",
            "environment": "production",
            "instance_id": "41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
            "capabilities": ["filesystem_documents"],
        },
    }
    assert str(response.connector_id) == "7dca1b71-b55d-48d6-a20b-bf7cb5552368"
    assert response.heartbeat_interval_seconds == 300


@pytest.mark.asyncio
async def test_registration_rejects_malformed_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": True}))
    client = client_for(transport)
    request = ConnectorRegistrationRequest(
        registration_token="one-time-registration-token",
        connector_name="Connector",
        connector_version="0.2.0",
        environment="production",
        instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        capabilities=["filesystem_documents"],
    )
    with pytest.raises(SaaSClientError, match="invalid registration response"):
        await client.register_connector("https://saas.example.test", request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (400, "invalid or malformed"),
        (401, "rejected the supplied credentials"),
        (403, "not permitted"),
        (404, "endpoint was not found"),
        (409, "already be registered"),
        (410, "expired or was revoked"),
        (429, "rate limit"),
        (503, "temporarily unavailable"),
    ],
)
async def test_registration_maps_remote_errors(status_code: int, message: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    client = client_for(transport)
    request = ConnectorRegistrationRequest(
        registration_token="secret-value-not-in-error",
        connector_name="Connector",
        connector_version="0.2.0",
        environment="production",
        instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        capabilities=["filesystem_documents"],
    )
    with pytest.raises(SaaSClientError, match=message) as captured:
        await client.register_connector("https://saas.example.test", request)
    assert "secret-value-not-in-error" not in str(captured.value)


@pytest.mark.asyncio
async def test_final_contract_serialization_and_heartbeat_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["connector_header"] = request.headers["X-PEKA-Connector-ID"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "server_time": "2026-07-20T12:00:01Z",
                "next_heartbeat_seconds": 240,
            },
        )

    connector_id = "7dca1b71-b55d-48d6-a20b-bf7cb5552368"
    client = client_for(httpx.MockTransport(handler))
    response = await client.send_heartbeat(
        "https://saas.example.test",
        UUID(connector_id),
        "connector-secret",
        ConnectorHeartbeatRequest(
            instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
            connector_version="0.2.0",
            timestamp=datetime(2026, 7, 20, 12, tzinfo=UTC),
            status="healthy",
            uptime_seconds=12345,
            sources=SourceHeartbeatSummary(total=1, healthy=1, unhealthy=0, disabled=0),
            capabilities=["filesystem_documents"],
        ),
    )
    assert captured["path"] == f"/api/v1/connectors/{connector_id}/heartbeat"
    assert captured["authorization"] == "Bearer connector-secret"
    assert captured["connector_header"] == connector_id
    body = captured["body"]
    assert isinstance(body, dict)
    assert body == {
        "instance_id": "41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        "connector_version": "0.2.0",
        "timestamp": "2026-07-20T12:00:00Z",
        "status": "healthy",
        "uptime_seconds": 12345,
        "sources": {"total": 1, "healthy": 1, "unhealthy": 0, "disabled": 0},
        "capabilities": ["filesystem_documents"],
    }
    assert response.accepted
    assert response.next_heartbeat_seconds == 240
