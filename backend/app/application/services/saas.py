from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.version import CONNECTOR_VERSION
from app.domain.entities.source import UserAccount
from app.domain.ports.saas import (
    ConnectorCapabilityName,
    ConnectorHeartbeatRequest,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
    PEKASaaSClient,
    SaaSClientError,
    SourceHeartbeatSummary,
)
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.security.secrets import SecretEncryptionService

CAPABILITIES: list[ConnectorCapabilityName] = ["filesystem_documents"]
PROCESS_STARTED = time.monotonic()


class SaaSConfigurationError(Exception):
    pass


class ConfirmationRequiredError(Exception):
    pass


class RegistrationStateError(Exception):
    pass


class LifecycleScheduler(Protocol):
    async def schedule_heartbeat(self, delay_seconds: float = 5) -> None: ...

    async def remove_heartbeat(self) -> None: ...


def validate_saas_url(value: str, environment: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    allowed = {"https"} if environment.lower() != "development" else {"http", "https"}
    if parsed.scheme not in allowed:
        requirement = "HTTPS" if environment.lower() != "development" else "HTTP or HTTPS"
        raise SaaSConfigurationError(f"PEKA URL must use {requirement}")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SaaSConfigurationError("PEKA URL must be an origin without credentials or query")
    return value


class RegistrationService:
    def __init__(
        self,
        operations: SqlAlchemyOperationsRepository,
        client: PEKASaaSClient,
        secrets: SecretEncryptionService,
        settings: Settings,
        scheduler: LifecycleScheduler | None = None,
    ) -> None:
        self._operations = operations
        self._client = client
        self._secrets = secrets
        self._settings = settings
        self._scheduler = scheduler

    async def test_connectivity(self, saas_url: str) -> None:
        await self._client.test_connectivity(
            validate_saas_url(saas_url, self._settings.environment)
        )

    async def register(
        self,
        saas_url: str,
        registration_token: str,
        actor: UserAccount | None,
        *,
        reregister: bool = False,
        confirmed: bool = False,
    ) -> ConnectorRegistrationResponse:
        current = await self._operations.get_settings()
        if current.connector_id and (not reregister or not confirmed):
            raise ConfirmationRequiredError("Explicit confirmation is required to re-register")
        connector_name = current.connector_display_name
        clean_url = validate_saas_url(saas_url, self._settings.environment)
        previous_state = current.saas_status
        correlation_id = str(uuid4())
        await self._operations.record_event(
            "connector.registration_started",
            "PEKA registration attempt started",
            actor=actor,
            target_type="connector",
            target_id=current.instance_id,
            details={
                "saas_hostname": urlsplit(clean_url).hostname,
                "reregister": reregister,
                "instance_id": current.instance_id,
                "connector_name": connector_name,
                "correlation_id": correlation_id,
            },
            component="saas",
        )
        current = await self._operations.begin_registration(
            clean_url if not current.connector_id else None
        )
        try:
            response = await self._client.register_connector(
                clean_url,
                ConnectorRegistrationRequest(
                    registration_token=registration_token,
                    connector_name=connector_name,
                    connector_version=CONNECTOR_VERSION,
                    environment=self._settings.environment,
                    instance_id=UUID(str(current.instance_id)),
                    capabilities=CAPABILITIES,
                ),
                correlation_id,
            )
            encrypted_secret = self._secrets.encrypt(response.connector_secret)
            registration_interval = (
                response.heartbeat_interval_seconds
                if 30 <= response.heartbeat_interval_seconds <= 86400
                else 300
            )
            await self._operations.complete_registration(
                str(response.connector_id),
                str(response.tenant_id),
                encrypted_secret,
                registration_interval,
                response.registered_at,
                clean_url,
            )
        except Exception as exc:
            client_error = exc if isinstance(exc, SaaSClientError) else None
            public_error = str(client_error) if client_error else "Connector registration failed."
            await self._operations.registration_failed(public_error, previous_state)
            await self._operations.record_event(
                "connector.registration_failed",
                "PEKA registration failed",
                actor=actor,
                target_type="connector",
                target_id=current.instance_id,
                details={
                    "error": public_error,
                    "reregister": reregister,
                    "instance_id": current.instance_id,
                    "correlation_id": correlation_id,
                    "request_id": client_error.request_id if client_error else None,
                    "http_status": client_error.status_code if client_error else None,
                    "saas_error_code": client_error.error_code if client_error else None,
                },
                level="ERROR",
                component="saas",
            )
            raise
        await self._operations.record_event(
            "connector.registration_succeeded",
            "Connector registered; awaiting first accepted heartbeat",
            actor=actor,
            target_type="connector",
            target_id=str(response.connector_id),
            details={
                "tenant_id": str(response.tenant_id),
                "reregister": reregister,
                "instance_id": current.instance_id,
                "correlation_id": correlation_id,
                "request_id": correlation_id,
                "http_status": 201,
            },
            component="saas",
        )
        await self._operations.record_event(
            "connector.awaiting_first_heartbeat",
            "Connector is awaiting its first accepted heartbeat",
            actor=actor,
            target_type="connector",
            target_id=str(response.connector_id),
            component="heartbeat",
        )
        if self._scheduler:
            # Keep Awaiting First Heartbeat observable in the registration
            # response while still starting delivery immediately afterwards.
            await self._scheduler.schedule_heartbeat(0.5)
        return response

    async def unregister(self, confirmed: bool, actor: UserAccount) -> ProductSettingsModel:
        if not confirmed:
            raise ConfirmationRequiredError("Explicit confirmation is required to unregister")
        if self._scheduler:
            await self._scheduler.remove_heartbeat()
        result = await self._operations.unregister_local()
        await self._operations.record_event(
            "connector.local_unregistered",
            "Connector registration removed locally",
            actor=actor,
            target_type="connector",
            target_id=result.instance_id,
            details={"remote_record_deleted": False},
            component="saas",
        )
        return result


@dataclass(frozen=True, slots=True)
class HeartbeatDelivery:
    next_delay_seconds: float
    connection_state: str
    round_trip_ms: float
    first_heartbeat: bool
    reconnected: bool


class HeartbeatService:
    def __init__(
        self,
        operations: SqlAlchemyOperationsRepository,
        client: PEKASaaSClient,
        secrets: SecretEncryptionService,
        environment: str,
    ) -> None:
        self._operations = operations
        self._client = client
        self._secrets = secrets
        self._environment = environment

    async def send(self) -> HeartbeatDelivery:
        settings = await self._operations.get_settings()
        if (
            not settings.connector_id
            or not settings.encrypted_connector_secret
            or not settings.saas_url
        ):
            raise RegistrationStateError("Connector is not registered")
        await self._operations.heartbeat_attempted()
        interval = settings.heartbeat_interval_seconds or 300
        previous_state = settings.saas_status
        first_heartbeat = settings.last_heartbeat_at is None
        summary = SourceHeartbeatSummary(**(await self._operations.source_summary()))
        request = ConnectorHeartbeatRequest(
            instance_id=UUID(str(settings.instance_id)),
            name=settings.connector_display_name,
            environment=self._environment,
            connector_version=CONNECTOR_VERSION,
            timestamp=datetime.now(UTC),
            status="healthy",
            uptime_seconds=max(0, int(time.monotonic() - PROCESS_STARTED)),
            sources=summary,
            capabilities=CAPABILITIES,
        )
        try:
            secret = self._secrets.decrypt(settings.encrypted_connector_secret)
            started = time.perf_counter()
            response = await self._client.send_heartbeat(
                settings.saas_url, UUID(settings.connector_id), secret, request
            )
            round_trip_ms = (time.perf_counter() - started) * 1000
        except SaaSClientError as exc:
            delay = (
                max(interval * 3, 900)
                if exc.authentication_failure
                else min(interval * (2 ** min(settings.heartbeat_failure_count, 4)), 3600)
            )
            await self._operations.heartbeat_failed(
                str(exc), exc.authentication_failure, datetime.now(UTC) + timedelta(seconds=delay)
            )
            raise
        response_interval = response.next_heartbeat_seconds
        next_interval = (
            response_interval
            if 30 <= response_interval <= 86400
            else interval
            if 30 <= interval <= 86400
            else 300
        )
        next_at = datetime.now(UTC) + timedelta(seconds=next_interval)
        state = await self._operations.heartbeat_succeeded(
            next_at,
            next_interval,
            round_trip_ms,
            response.server_time,
        )
        return HeartbeatDelivery(
            next_delay_seconds=float(next_interval),
            connection_state=state,
            round_trip_ms=round_trip_ms,
            first_heartbeat=first_heartbeat,
            reconnected=previous_state
            in {
                "reconnecting",
                "out_of_sync",
                "disconnected",
                "authentication_failed",
            },
        )
