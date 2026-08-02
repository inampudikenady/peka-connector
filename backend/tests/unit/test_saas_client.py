import json
import socket
import ssl
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.domain.ports.saas import (
    ConnectorHeartbeatRequest,
    ConnectorRegistrationRequest,
    DocumentDeliveryMetadata,
    OperationalToolResult,
    SaaSClientError,
    SourceHeartbeatSummary,
)
from app.infrastructure.saas.client import HttpxPEKASaaSClient


def client_for(handler: httpx.AsyncBaseTransport) -> HttpxPEKASaaSClient:
    return HttpxPEKASaaSClient(1, 1, transport=handler)


def heartbeat_request() -> ConnectorHeartbeatRequest:
    return ConnectorHeartbeatRequest(
        instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        name="PEKA Connector",
        environment="production",
        connector_version="1.2.3",
        timestamp=datetime(2026, 7, 20, 12, tzinfo=UTC),
        status="healthy",
        uptime_seconds=123,
        sources=SourceHeartbeatSummary(total=0, healthy=0, unhealthy=0, disabled=0),
        capabilities=["filesystem_documents"],
    )


class FailingTransport(httpx.AsyncBaseTransport):
    def __init__(self, failure: str) -> None:
        self.failure = failure

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.failure == "dns":
            try:
                raise socket.gaierror(-2, "Name or service not known")
            except socket.gaierror as exc:
                raise httpx.ConnectError("connect failed", request=request) from exc
        if self.failure == "refused":
            try:
                raise ConnectionRefusedError(111, "Connection refused")
            except ConnectionRefusedError as exc:
                raise httpx.ConnectError("connect failed", request=request) from exc
        if self.failure == "connect_timeout":
            raise httpx.ConnectTimeout("connect timeout", request=request)
        if self.failure == "read_timeout":
            raise httpx.ReadTimeout("read timeout", request=request)
        if self.failure == "tls_verification":
            try:
                raise ssl.SSLCertVerificationError(1, "certificate verify failed")
            except ssl.SSLCertVerificationError as exc:
                raise httpx.ConnectError("TLS failed", request=request) from exc
        if self.failure == "tls":
            try:
                raise ssl.SSLError("TLS protocol error")
            except ssl.SSLError as exc:
                raise httpx.ConnectError("TLS failed", request=request) from exc
        raise httpx.ConnectError("unknown failure", request=request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "kind", "reason"),
    [
        ("dns", "dns", "DNS resolution failed"),
        ("refused", "connection_refused", "Connection refused"),
        ("connect_timeout", "connection_timeout", "Connection timed out"),
        ("read_timeout", "read_timeout", "Read timed out"),
        ("tls_verification", "tls_verification", "TLS certificate verification failed"),
        ("tls", "tls", "TLS/SSL connection failed"),
        ("unknown", "transport", "Unknown transport error"),
    ],
)
async def test_heartbeat_transport_failures_are_classified(
    failure: str, kind: str, reason: str
) -> None:
    client = client_for(FailingTransport(failure))
    with pytest.raises(SaaSClientError) as captured:
        await client.send_heartbeat(
            "https://peka.example.com",
            UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368"),
            "connector-secret",
            heartbeat_request(),
        )
    error = captured.value
    assert error.kind == kind
    assert error.failure_reason == reason
    assert error.destination_host == "peka.example.com"
    assert error.request_path == "/api/v1/connectors/<redacted>/heartbeat"
    assert "connector-secret" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "kind", "reason"),
    [
        (400, "http_400", "PEKA rejected the heartbeat request"),
        (401, "authentication", "Authentication rejected by PEKA"),
        (403, "forbidden", "Authentication rejected by PEKA"),
        (404, "not_found", "PEKA endpoint not found"),
        (409, "conflict", "PEKA rejected the heartbeat conflict"),
        (429, "rate_limited", "PEKA rate limit reached"),
        (500, "server_error", "PEKA returned HTTP 500"),
    ],
)
async def test_heartbeat_http_failures_include_only_safe_metadata(
    status_code: int, kind: str, reason: str
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code,
            json={
                "code": "invalid_connector_token",
                "message": "The connector authentication was rejected.",
                "authorization": "Bearer should-never-appear",
            },
            headers={"X-Request-ID": "safe-request-123"},
        )
    )
    with pytest.raises(SaaSClientError) as captured:
        await client_for(transport).send_heartbeat(
            "https://peka.example.com",
            UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368"),
            "connector-secret",
            heartbeat_request(),
        )
    error = captured.value
    assert error.kind == kind
    assert error.failure_reason == reason
    assert error.status_code == status_code
    assert error.error_code == "invalid_connector_token"
    assert error.safe_api_message == "The connector authentication was rejected."
    assert error.request_id == "safe-request-123"
    serialized = " ".join(
        str(value)
        for value in (
            error,
            error.failure_reason,
            error.error_code,
            error.safe_api_message,
            error.request_id,
        )
    )
    assert "connector-secret" not in serialized
    assert "Bearer should-never-appear" not in serialized


@pytest.mark.asyncio
async def test_heartbeat_rejects_malformed_success_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"accepted": True, "unexpected": True})
    )
    with pytest.raises(SaaSClientError) as captured:
        await client_for(transport).send_heartbeat(
            "https://peka.example.com",
            UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368"),
            "connector-secret",
            heartbeat_request(),
        )
    assert captured.value.kind == "malformed_response"
    assert captured.value.failure_reason == "Unexpected heartbeat response"


@pytest.mark.asyncio
async def test_heartbeat_never_relays_secret_bearing_remote_message() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401,
            json={
                "code": "invalid_connector_token",
                "message": "Authorization: Bearer remote-secret-value",
            },
        )
    )
    with pytest.raises(SaaSClientError) as captured:
        await client_for(transport).send_heartbeat(
            "https://peka.example.com",
            UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368"),
            "local-connector-secret",
            heartbeat_request(),
        )
    assert captured.value.safe_api_message is None
    assert "remote-secret-value" not in str(captured.value)
    assert "local-connector-secret" not in str(captured.value)


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
            connector_version="1.2.3",
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
            "connector_version": "1.2.3",
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
        connector_version="1.2.3",
        environment="production",
        instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        capabilities=["filesystem_documents"],
    )
    with pytest.raises(SaaSClientError, match="invalid registration response"):
        await client.register_connector("https://saas.example.test", request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("TOKEN_NOT_FOUND", "The registration token is invalid."),
        (
            "TOKEN_EXPIRED",
            "The registration token has expired. Generate a new token in PEKA.",
        ),
        (
            "TOKEN_USED",
            "The registration token has already been used. Generate a new token in PEKA.",
        ),
        (
            "TOKEN_REVOKED",
            "The registration token was revoked. Generate a new token in PEKA.",
        ),
        (
            "INSTANCE_ALREADY_REGISTERED",
            "This connector appliance is already registered in PEKA.",
        ),
        (
            "TENANT_MISMATCH",
            "The registration token is not valid for this connector registration.",
        ),
        ("VALIDATION_FAILED", "The connector name is not valid."),
        ("REGISTRATION_NOT_PERMITTED", "Connector registration is not permitted."),
    ],
)
async def test_registration_maps_structured_remote_errors(code: str, message: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            409,
            json={"code": code, "message": "The connector name is not valid."},
            headers={"X-Request-ID": "saas-request-123"},
        )
    )
    client = client_for(transport)
    request = ConnectorRegistrationRequest(
        registration_token="secret-value-not-in-error",
        connector_name="Connector",
        connector_version="1.2.3",
        environment="production",
        instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
        capabilities=["filesystem_documents"],
    )
    with pytest.raises(SaaSClientError) as captured:
        await client.register_connector(
            "https://saas.example.test", request, "local-correlation-123"
        )
    assert str(captured.value) == message
    assert captured.value.error_code == code
    assert captured.value.status_code == 409
    assert captured.value.request_id == "saas-request-123"
    assert "secret-value-not-in-error" not in str(captured.value)


@pytest.mark.asyncio
async def test_unknown_registration_code_uses_safe_saas_message() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            400,
            json={"code": "NEW_SAFE_CODE", "message": "A safe registration explanation."},
        )
    )
    client = client_for(transport)
    with pytest.raises(SaaSClientError) as captured:
        await client.register_connector(
            "https://saas.example.test",
            ConnectorRegistrationRequest(
                registration_token="one-time-registration-token",
                connector_name="Connector",
                connector_version="1.2.3",
                environment="production",
                instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
                capabilities=["filesystem_documents"],
            ),
        )
    assert str(captured.value) == "A safe registration explanation."
    assert captured.value.error_code == "NEW_SAFE_CODE"


@pytest.mark.asyncio
async def test_structured_error_never_relays_token_bearing_message() -> None:
    submitted_token = "one-time-registration-token"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            400,
            json={
                "code": "FUTURE_ERROR",
                "message": f"registration_token={submitted_token}",
            },
        )
    )
    client = client_for(transport)
    with pytest.raises(SaaSClientError) as captured:
        await client.register_connector(
            "https://saas.example.test",
            ConnectorRegistrationRequest(
                registration_token=submitted_token,
                connector_name="Connector",
                connector_version="1.2.3",
                environment="production",
                instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
                capabilities=["filesystem_documents"],
            ),
        )
    assert str(captured.value) == "Connector registration failed."
    assert submitted_token not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="<html>proxy failure</html>"),
        httpx.Response(400, json={"code": 123, "message": ["not", "safe"]}),
    ],
)
async def test_malformed_registration_error_uses_generic_fallback(
    response: httpx.Response,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    client = client_for(httpx.MockTransport(handler))
    with pytest.raises(SaaSClientError) as captured:
        await client.register_connector(
            "https://saas.example.test",
            ConnectorRegistrationRequest(
                registration_token="one-time-registration-token",
                connector_name="Connector",
                connector_version="1.2.3",
                environment="production",
                instance_id="41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
                capabilities=["filesystem_documents"],
            ),
        )
    assert str(captured.value) == "Connector registration failed."
    assert "proxy failure" not in str(captured.value)
    assert calls == 1


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
            name="VITWO Production Connector",
            environment="production",
            connector_version="1.2.3",
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
        "name": "VITWO Production Connector",
        "environment": "production",
        "connector_version": "1.2.3",
        "timestamp": "2026-07-20T12:00:00Z",
        "status": "healthy",
        "uptime_seconds": 12345,
        "sources": {"total": 1, "healthy": 1, "unhealthy": 0, "disabled": 0},
        "capabilities": ["filesystem_documents"],
    }
    assert response.accepted
    assert response.next_heartbeat_seconds == 240


@pytest.mark.asyncio
async def test_document_delivery_contract_is_authenticated_idempotent_and_acknowledged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.txt"
    path.write_bytes(b"policy bytes")
    digest = "8" * 64
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["connector"] = request.headers["X-PEKA-Connector-ID"]
        captured["idempotency"] = request.headers["Idempotency-Key"]
        body = request.content
        captured["has_metadata"] = b'"operation": "upsert"' in body
        captured["has_file"] = b"policy bytes" in body
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "document_id": "remote-document",
                "version_id": "remote-version",
                "content_hash": f"sha256:{digest}",
                "ingestion_status": "RECEIVED",
            },
        )

    connector_id = UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368")
    response = await client_for(httpx.MockTransport(handler)).deliver_document(
        "https://peka.example.test",
        connector_id,
        "connector-secret",
        DocumentDeliveryMetadata(
            source_id="d0c0a001-6f05-4bd8-a123-000000000001",
            document_key="uploaded-documents/policy.txt",
            relative_path="policy.txt",
            filename="policy.txt",
            mime_type="text/plain",
            size_bytes=12,
            content_hash=f"sha256:{digest}",
            modified_at=datetime(2026, 7, 21, 10, 30, tzinfo=UTC),
            operation="upsert",
            connector_version="1.2.3",
        ),
        "stable-idempotency-key",
        path,
    )
    assert captured == {
        "path": f"/api/v1/connectors/{connector_id}/documents",
        "authorization": "Bearer connector-secret",
        "connector": str(connector_id),
        "idempotency": "stable-idempotency-key",
        "has_metadata": True,
        "has_file": True,
    }
    assert response.accepted and response.content_hash == f"sha256:{digest}"


@pytest.mark.asyncio
async def test_operational_tool_poll_and_result_use_connector_authentication() -> None:
    captured: list[tuple[str, str, str]] = []
    request_id = "8b7ed8f3-1397-4ec8-b601-1b75d8bc18c7"
    connector_id = UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368")

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            (
                request.method,
                request.url.path,
                request.headers["Authorization"],
            )
        )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": request_id,
                    "tool_name": "count_assets",
                    "arguments": {"os_family": "linux"},
                    "expires_at": "2026-07-29T12:00:30Z",
                    "claim_token": "ephemeral-claim-token-that-is-long",
                },
            )
        body = json.loads(request.content)
        assert body["result"]["count"] == 14
        assert "promql" not in body
        return httpx.Response(204)

    client = client_for(httpx.MockTransport(handler))
    claimed = await client.claim_operational_tool(
        "https://peka.example.test", connector_id, "connector-secret"
    )
    assert claimed is not None and claimed.tool_name == "count_assets"
    await client.submit_operational_tool_result(
        "https://peka.example.test",
        connector_id,
        "connector-secret",
        claimed.id,
        OperationalToolResult(
            claim_token=claimed.claim_token,
            status="completed",
            result={"count": 14},
        ),
    )
    assert captured == [
        (
            "GET",
            f"/api/v1/connectors/{connector_id}/operational-tools/requests/next",
            "Bearer connector-secret",
        ),
        (
            "POST",
            (f"/api/v1/connectors/{connector_id}/operational-tools/requests/{request_id}/result"),
            "Bearer connector-secret",
        ),
    ]


@pytest.mark.asyncio
async def test_operational_tool_poll_returns_none_for_no_content() -> None:
    client = client_for(httpx.MockTransport(lambda _request: httpx.Response(204)))
    result = await client.claim_operational_tool(
        "https://peka.example.test",
        UUID("7dca1b71-b55d-48d6-a20b-bf7cb5552368"),
        "connector-secret",
    )
    assert result is None
