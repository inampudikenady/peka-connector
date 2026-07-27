from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.api.schemas import ProductSettingsUpdate, SaaSRegistrationRequest
from app.api.v1.endpoints import settings as settings_endpoint
from app.domain.entities.source import UserAccount


class FakeOperations:
    def __init__(self) -> None:
        self.model = SimpleNamespace(
            connector_display_name="PEKA Connector",
            environment_label="Production",
            log_level="INFO",
            saas_status="connected",
            connector_id=str(uuid4()),
            tenant_id=str(uuid4()),
            saas_url="https://saas.example.test",
            last_heartbeat_at=datetime.now(UTC),
            instance_id=str(uuid4()),
            registered_at=datetime.now(UTC),
            heartbeat_interval_seconds=300,
            last_heartbeat_attempt_at=datetime.now(UTC),
            next_heartbeat_at=datetime.now(UTC),
            last_heartbeat_status="success",
            last_heartbeat_error=None,
            heartbeat_failure_count=0,
            last_heartbeat_failed_at=None,
            heartbeat_round_trip_ms=12.5,
            last_saas_server_time=datetime.now(UTC),
            encrypted_connector_secret="encrypted-secret",
        )

    async def get_settings(self) -> SimpleNamespace:
        return self.model

    async def update_settings(self, name: str, environment: str, level: str) -> SimpleNamespace:
        self.model.connector_display_name = name
        self.model.environment_label = environment
        self.model.log_level = level
        return self.model

    async def record_event(self, *args: object, **kwargs: object) -> None:
        return None

    async def refresh_settings(self) -> SimpleNamespace:
        return self.model


@pytest.mark.asyncio
async def test_name_change_triggers_heartbeat_and_keeps_identity_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = FakeOperations()
    original_identity = (
        operations.model.connector_id,
        operations.model.tenant_id,
        operations.model.instance_id,
    )
    calls = 0

    async def failed_heartbeat() -> None:
        nonlocal calls
        calls += 1
        operations.model.last_heartbeat_status = "failed"
        operations.model.saas_status = "reconnecting"

    monkeypatch.setattr(
        settings_endpoint.connector_scheduler, "retry_heartbeat_now", failed_heartbeat
    )
    actor = UserAccount(
        id=uuid4(),
        username="admin",
        password_hash="hash",
        role="administrator",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_login_at=None,
    )
    response = await settings_endpoint.update_product_settings(
        ProductSettingsUpdate(
            connector_display_name="VITWO Production Connector",
            environment_label="Production",
            log_level="INFO",
        ),
        actor,
        operations,  # type: ignore[arg-type]
    )

    payload = cast(dict[str, Any], response)
    assert calls == 1
    assert payload["connector_display_name"] == "VITWO Production Connector"
    assert payload["metadata_sync_warning"]
    assert (
        operations.model.connector_id,
        operations.model.tenant_id,
        operations.model.instance_id,
    ) == original_identity


def test_timezone_and_duplicate_registration_name_are_not_api_fields() -> None:
    with pytest.raises(ValueError):
        ProductSettingsUpdate.model_validate(
            {
                "connector_display_name": "Connector",
                "environment_label": "Production",
                "log_level": "INFO",
                "timezone": "Asia/Kolkata",
            }
        )
    with pytest.raises(ValueError):
        SaaSRegistrationRequest.model_validate(
            {
                "saas_url": "https://saas.example.test",
                "registration_token": "one-time-registration-token",
                "connector_display_name": "Duplicate Name",
            }
        )
