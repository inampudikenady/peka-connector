from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

ConnectorCapabilityName = Literal["filesystem_documents"]


class ConnectorRegistrationRequest(BaseModel):
    registration_token: str = Field(min_length=20, max_length=512)
    connector_name: str = Field(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f]+$")
    connector_version: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$"
    )
    environment: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$"
    )
    instance_id: UUID
    capabilities: list[ConnectorCapabilityName] = Field(default_factory=list, max_length=32)


class ConnectorRegistrationResponse(BaseModel):
    connector_id: UUID
    tenant_id: UUID
    connector_secret: str = Field(min_length=1, max_length=4096)
    heartbeat_interval_seconds: int
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def registered_at_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("registered_at must include a UTC offset")
        if offset.total_seconds() != 0:
            raise ValueError("registered_at must be UTC")
        return value


class SourceHeartbeatSummary(BaseModel):
    total: int = Field(ge=0)
    healthy: int = Field(ge=0)
    unhealthy: int = Field(ge=0)
    disabled: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "SourceHeartbeatSummary":
        if self.healthy + self.unhealthy + self.disabled != self.total:
            raise ValueError("source counts must add up to total")
        return self


class ConnectorHeartbeatRequest(BaseModel):
    instance_id: UUID
    name: str = Field(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f]+$")
    environment: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$"
    )
    connector_version: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$"
    )
    timestamp: datetime
    status: Literal["healthy"]
    uptime_seconds: int = Field(ge=0)
    sources: SourceHeartbeatSummary
    capabilities: list[ConnectorCapabilityName] = Field(default_factory=list, max_length=32)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("timestamp must include a UTC offset")
        if offset.total_seconds() != 0:
            raise ValueError("timestamp must be UTC")
        return value


class ConnectorHeartbeatResponse(BaseModel):
    accepted: Literal[True]
    server_time: datetime
    next_heartbeat_seconds: int

    @field_validator("server_time")
    @classmethod
    def server_time_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("server_time must include a UTC offset")
        if offset.total_seconds() != 0:
            raise ValueError("server_time must be UTC")
        return value


class DocumentDeliveryMetadata(BaseModel):
    source_id: UUID
    document_key: str = Field(min_length=1, max_length=2200)
    relative_path: str = Field(min_length=1, max_length=2048)
    filename: str = Field(min_length=1, max_length=512)
    mime_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    content_hash: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$", default=None)
    modified_at: datetime | None = None
    operation: Literal["upsert", "delete"]
    connector_version: str


class DocumentDeliveryResponse(BaseModel):
    accepted: Literal[True]
    document_id: str = Field(min_length=1, max_length=200)
    version_id: str | None = Field(default=None, max_length=200)
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    ingestion_status: str = Field(min_length=1, max_length=100)


class SaaSClientError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        status_code: int | None = None,
        *,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id

    @property
    def authentication_failure(self) -> bool:
        return self.status_code in {401, 403}


class PEKASaaSClient(Protocol):
    async def test_connectivity(self, base_url: str) -> None: ...

    async def register_connector(
        self,
        base_url: str,
        request: ConnectorRegistrationRequest,
        correlation_id: str | None = None,
    ) -> ConnectorRegistrationResponse: ...

    async def send_heartbeat(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        request: ConnectorHeartbeatRequest,
    ) -> ConnectorHeartbeatResponse: ...

    async def deliver_document(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        metadata: DocumentDeliveryMetadata,
        idempotency_key: str,
        file_path: Path | None,
    ) -> DocumentDeliveryResponse: ...

    async def report_source_health(self) -> None: ...

    async def receive_commands(self) -> None: ...
