import asyncio

import pytest

from app.domain.ports.saas import SaaSClientError
from app.infrastructure.scheduling import (
    ConnectorScheduler,
    HeartbeatInProgressError,
    heartbeat_failure_context,
)


@pytest.mark.asyncio
async def test_repeated_retry_now_cannot_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = ConnectorScheduler()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def heartbeat(*, force: bool = False) -> None:
        nonlocal calls
        assert force
        calls += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(scheduler, "_run_heartbeat", heartbeat)
    first = asyncio.create_task(scheduler.retry_heartbeat_now())
    await started.wait()
    with pytest.raises(HeartbeatInProgressError):
        await scheduler.retry_heartbeat_now()
    assert calls == 1
    release.set()
    await first


def test_structured_heartbeat_log_context_is_allow_listed_and_secret_free() -> None:
    error = SaaSClientError(
        "authentication",
        "POST /api/v1/connectors/<redacted>/heartbeat returned HTTP 401, "
        "code=invalid_connector_token",
        401,
        error_code="invalid_connector_token",
        request_id="request-123",
        failure_reason="Authentication rejected by PEKA",
        method="POST",
        destination_host="peka.example.com",
        request_path="/api/v1/connectors/<redacted>/heartbeat",
        safe_api_message="Connector authentication was rejected.",
    )
    context = heartbeat_failure_context(error, "local-correlation-123", "authentication_failed")
    assert context["event"] == "heartbeat_failed"
    assert context["failure_type"] == "authentication"
    assert context["http_status"] == 401
    serialized = repr(context)
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized
    assert "connector-secret" not in serialized
