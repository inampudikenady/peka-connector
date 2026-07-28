from datetime import UTC, datetime
from enum import StrEnum


class ConnectorConnectionState(StrEnum):
    UNREGISTERED = "unregistered"
    REGISTERING = "registering"
    AWAITING_FIRST_HEARTBEAT = "awaiting_first_heartbeat"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    OUT_OF_SYNC = "out_of_sync"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    AUTHENTICATION_FAILED = "authentication_failed"


def derive_connection_state(
    *,
    has_credentials: bool,
    current_state: str,
    last_success_at: datetime | None,
    heartbeat_interval_seconds: int,
    consecutive_failures: int,
    unhealthy_sources: int = 0,
    now: datetime | None = None,
) -> ConnectorConnectionState:
    if not has_credentials:
        return ConnectorConnectionState.UNREGISTERED
    if current_state == ConnectorConnectionState.REGISTERING:
        return ConnectorConnectionState.REGISTERING
    if current_state == ConnectorConnectionState.AUTHENTICATION_FAILED:
        return ConnectorConnectionState.AUTHENTICATION_FAILED
    if last_success_at is None:
        if consecutive_failures:
            return ConnectorConnectionState.RECONNECTING
        return ConnectorConnectionState.AWAITING_FIRST_HEARTBEAT

    current_time = now or datetime.now(UTC)
    last_success = (
        last_success_at.replace(tzinfo=UTC)
        if last_success_at.tzinfo is None
        else last_success_at.astimezone(UTC)
    )
    elapsed = max(0.0, (current_time - last_success).total_seconds())
    interval = max(1, heartbeat_interval_seconds)
    if elapsed >= 3 * interval:
        return ConnectorConnectionState.DISCONNECTED
    if elapsed > 1.5 * interval:
        return ConnectorConnectionState.OUT_OF_SYNC
    if consecutive_failures:
        return ConnectorConnectionState.RECONNECTING
    # Source health is intentionally not part of connector-to-PEKA
    # connectivity. Keep the argument for API compatibility with callers that
    # also calculate a source summary, but report that summary independently.
    _ = unhealthy_sources
    return ConnectorConnectionState.CONNECTED
