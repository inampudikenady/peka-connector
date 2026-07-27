from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.application.services.saas import (
    HeartbeatService,
    RegistrationService,
    SaaSConfigurationError,
    validate_saas_url,
)
from app.core.config import get_settings
from app.domain.ports.saas import (
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
    SaaSClientError,
)
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.database.session import session_factory
from app.infrastructure.security.secrets import SecretDecryptionError, SecretEncryptionService


class FakeScheduler:
    def __init__(self) -> None:
        self.heartbeat_delay: float | None = None
        self.removed = False

    async def schedule_heartbeat(self, delay_seconds: float = 5) -> None:
        self.heartbeat_delay = delay_seconds

    async def remove_heartbeat(self) -> None:
        self.removed = True


class FakeSaaSClient:
    def __init__(self) -> None:
        self.registration_token: str | None = None
        self.registration_calls = 0
        self.registration_correlation_id: str | None = None
        self.secret_received: str | None = None
        self.heartbeat_error: SaaSClientError | None = None
        self.registration_error: SaaSClientError | None = None
        self.registration_request: ConnectorRegistrationRequest | None = None
        self.heartbeat_request: ConnectorHeartbeatRequest | None = None

    async def test_connectivity(self, base_url: str) -> None:
        return None

    async def register_connector(
        self,
        base_url: str,
        request: ConnectorRegistrationRequest,
        correlation_id: str | None = None,
    ) -> ConnectorRegistrationResponse:
        self.registration_calls += 1
        self.registration_request = request
        self.registration_correlation_id = correlation_id
        self.registration_token = request.registration_token
        if self.registration_error:
            raise self.registration_error
        return ConnectorRegistrationResponse(
            connector_id=uuid4(),
            tenant_id=uuid4(),
            connector_secret="remote-connector-secret",
            heartbeat_interval_seconds=120,
            registered_at=datetime.now(UTC),
        )

    async def send_heartbeat(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        request: ConnectorHeartbeatRequest,
    ) -> ConnectorHeartbeatResponse:
        self.secret_received = connector_secret
        self.heartbeat_request = request
        if self.heartbeat_error:
            raise self.heartbeat_error
        return ConnectorHeartbeatResponse(
            accepted=True,
            server_time=datetime.now(UTC),
            next_heartbeat_seconds=180,
        )

    async def upload_documents(self) -> None:
        raise NotImplementedError

    async def report_source_health(self) -> None:
        raise NotImplementedError

    async def receive_commands(self) -> None:
        raise NotImplementedError


def test_saas_url_enforces_https() -> None:
    with pytest.raises(SaaSConfigurationError, match="HTTPS"):
        validate_saas_url("http://saas.example.test", "production")
    assert validate_saas_url("http://localhost:9000", "development") == "http://localhost:9000"
    assert (
        validate_saas_url("http://host.docker.internal:8000", "development")
        == "http://host.docker.internal:8000"
    )


@pytest.mark.asyncio
async def test_registration_encrypts_secret_and_heartbeat_recovers() -> None:
    settings = get_settings()
    encryption = SecretEncryptionService(settings.encryption_key)
    client = FakeSaaSClient()
    scheduler = FakeScheduler()
    async with session_factory() as session:
        operations = SqlAlchemyOperationsRepository(session)
        await operations.unregister_local()
        await operations.update_settings("Lifecycle Test", "Production", "INFO")
        service = RegistrationService(operations, client, encryption, settings, scheduler)
        response = await service.register(
            "https://saas.example.test",
            "one-time-registration-token",
            None,
        )
        product = await operations.get_settings()
        assert product.connector_id == str(response.connector_id)
        assert product.encrypted_connector_secret
        assert "remote-connector-secret" not in product.encrypted_connector_secret
        assert not hasattr(product, "registration_token")
        assert product.saas_status == "awaiting_first_heartbeat"
        assert scheduler.heartbeat_delay == 0.5

        assert client.registration_request
        assert client.registration_request.connector_name == "Lifecycle Test"
        heartbeat = HeartbeatService(operations, client, encryption, settings.environment)
        delivery = await heartbeat.send()
        assert delivery.next_delay_seconds == 180
        assert delivery.first_heartbeat
        product = await operations.get_settings()
        assert product.saas_status == "connected"
        assert product.heartbeat_interval_seconds == 180
        assert product.heartbeat_round_trip_ms is not None
        assert product.last_saas_server_time is not None
        assert product.heartbeat_failure_count == 0
        assert client.secret_received == "remote-connector-secret"
        assert client.heartbeat_request
        assert client.heartbeat_request.name == "Lifecycle Test"
        assert client.heartbeat_request.environment == settings.environment
        connector_id = product.connector_id
        tenant_id = product.tenant_id
        instance_id = product.instance_id

        await operations.update_settings("VITWO Production Connector", "Production", "INFO")
        await heartbeat.send()
        assert client.heartbeat_request.name == "VITWO Production Connector"
        renamed = await operations.get_settings()
        assert renamed.connector_display_name == "VITWO Production Connector"
        assert renamed.connector_id == connector_id
        assert renamed.tenant_id == tenant_id
        assert renamed.instance_id == instance_id

        client.heartbeat_error = SaaSClientError("http_error", "Credentials rejected", 401)
        with pytest.raises(SaaSClientError):
            await heartbeat.send()
        product = await operations.get_settings()
        assert product.saas_status == "authentication_failed"
        assert product.heartbeat_failure_count == 1

        client.heartbeat_error = None
        await heartbeat.send()
        product = await operations.get_settings()
        assert product.saas_status == "connected"
        assert product.heartbeat_failure_count == 0

        stored = await session.scalar(
            select(ProductSettingsModel).where(ProductSettingsModel.id == 1)
        )
        assert stored and stored.encrypted_connector_secret == product.encrypted_connector_secret


@pytest.mark.asyncio
async def test_failed_reregistration_preserves_existing_credentials() -> None:
    settings = get_settings()
    client = FakeSaaSClient()
    encryption = SecretEncryptionService(settings.encryption_key)
    async with session_factory() as session:
        operations = SqlAlchemyOperationsRepository(session)
        await operations.unregister_local()
        await operations.update_settings("Preserved Connector", "Production", "INFO")
        service = RegistrationService(operations, client, encryption, settings)
        await service.register(
            "https://saas.example.test",
            "first-valid-registration-token",
            None,
        )
        before = await operations.get_settings()
        prior_id = before.connector_id
        prior_secret = before.encrypted_connector_secret
        client.registration_error = SaaSClientError("http_error", "Token was used", 409)
        with pytest.raises(SaaSClientError):
            await service.register(
                "https://other.example.test",
                "second-valid-registration-token",
                None,
                reregister=True,
                confirmed=True,
            )
        after = await operations.get_settings()
        assert after.connector_id == prior_id
        assert after.encrypted_connector_secret == prior_secret
        assert after.saas_url == "https://saas.example.test"


@pytest.mark.asyncio
async def test_failed_initial_registration_keeps_configuration_without_credentials_or_secrets() -> (
    None
):
    settings = get_settings()
    client = FakeSaaSClient()
    submitted_token = "raw-one-time-registration-token"
    client.registration_error = SaaSClientError(
        "registration_error",
        "This connector appliance is already registered in PEKA SaaS.",
        409,
        error_code="INSTANCE_ALREADY_REGISTERED",
        request_id="saas-request-456",
    )
    async with session_factory() as session:
        operations = SqlAlchemyOperationsRepository(session)
        await operations.unregister_local()
        await operations.update_settings("Unregistered Appliance", "Production", "INFO")
        service = RegistrationService(
            operations,
            client,
            SecretEncryptionService(settings.encryption_key),
            settings,
        )
        with pytest.raises(SaaSClientError):
            await service.register(
                "https://new-saas.example.test",
                submitted_token,
                None,
            )

        product = await operations.get_settings()
        assert product.saas_status == "unregistered"
        assert product.saas_url == "https://new-saas.example.test"
        assert product.connector_display_name == "Unregistered Appliance"
        assert product.connector_id is None
        assert product.tenant_id is None
        assert product.encrypted_connector_secret is None
        assert product.registered_at is None
        assert client.registration_calls == 1
        assert client.registration_correlation_id

        logs, _ = await operations.list_logs(None, "saas", None, 1, 100)
        serialized_logs = " ".join(f"{item.message} {item.context}" for item in logs)
        assert submitted_token not in serialized_logs
        assert "INSTANCE_ALREADY_REGISTERED" in serialized_logs
        assert "saas-request-456" in serialized_logs
        assert "409" in serialized_logs


def test_wrong_encryption_key_fails_safely() -> None:
    first = SecretEncryptionService(get_settings().encryption_key)
    encrypted = first.encrypt("connector-secret")
    from pydantic import SecretStr

    wrong = SecretEncryptionService(SecretStr("a-different-key-that-is-at-least-32-characters"))
    with pytest.raises(SecretDecryptionError):
        wrong.decrypt(encrypted)
