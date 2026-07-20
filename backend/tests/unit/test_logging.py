from datetime import UTC, datetime
from uuid import UUID

from app.core.logging import sanitize


def test_sanitize_redacts_secrets_and_serializes_structured_values() -> None:
    safe = sanitize(
        {
            "authorization": "Bearer credential",
            "registration_token": "one-time-token",
            "next_heartbeat_at": datetime(2026, 7, 20, 12, tzinfo=UTC),
            "correlation_id": UUID("41ed86ec-58d1-4ac3-9107-ff2c47ca11cc"),
        }
    )
    assert safe == {
        "authorization": "[REDACTED]",
        "registration_token": "[REDACTED]",
        "next_heartbeat_at": "2026-07-20T12:00:00Z",
        "correlation_id": "41ed86ec-58d1-4ac3-9107-ff2c47ca11cc",
    }
