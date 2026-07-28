from datetime import UTC, datetime, timedelta

import pytest

from app.domain.services.connector_status import derive_connection_state

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"has_credentials": False}, "unregistered"),
        ({"current_state": "registering"}, "registering"),
        ({"last_success_at": None}, "awaiting_first_heartbeat"),
        ({"last_success_at": None, "consecutive_failures": 1}, "reconnecting"),
        ({"last_success_at": NOW - timedelta(seconds=100)}, "connected"),
        ({"last_success_at": NOW - timedelta(seconds=100), "unhealthy_sources": 1}, "connected"),
        (
            {"last_success_at": NOW - timedelta(seconds=100), "consecutive_failures": 1},
            "reconnecting",
        ),
        ({"last_success_at": NOW - timedelta(seconds=451)}, "out_of_sync"),
        ({"last_success_at": NOW - timedelta(seconds=900)}, "disconnected"),
        ({"current_state": "authentication_failed"}, "authentication_failed"),
    ],
)
def test_final_connector_status_rules(kwargs: dict[str, object], expected: str) -> None:
    values: dict[str, object] = {
        "has_credentials": True,
        "current_state": "connected",
        "last_success_at": NOW,
        "heartbeat_interval_seconds": 300,
        "consecutive_failures": 0,
        "unhealthy_sources": 0,
        "now": NOW,
    }
    values.update(kwargs)
    assert derive_connection_state(**values).value == expected  # type: ignore[arg-type]
