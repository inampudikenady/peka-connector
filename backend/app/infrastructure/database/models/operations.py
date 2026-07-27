from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.types import UTCDateTime


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    actor_username: Mapped[str | None] = mapped_column(String(100), default=None)
    target_type: Mapped[str | None] = mapped_column(String(100), default=None)
    target_id: Mapped[str | None] = mapped_column(String(100), default=None)
    message: Mapped[str] = mapped_column(String(1000))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), index=True
    )


class ApplicationLogModel(Base):
    __tablename__ = "application_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    level: Mapped[str] = mapped_column(String(20), index=True)
    component: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), index=True
    )


class ProductSettingsModel(Base):
    __tablename__ = "product_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    connector_display_name: Mapped[str] = mapped_column(String(200), default="PEKA Connector")
    environment_label: Mapped[str] = mapped_column(String(100), default="Production")
    log_level: Mapped[str] = mapped_column(String(20), default="INFO")
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    saas_status: Mapped[str] = mapped_column(String(32), default="unregistered")
    connector_id: Mapped[str | None] = mapped_column(String(200), default=None)
    tenant_id: Mapped[str | None] = mapped_column(String(200), default=None)
    saas_url: Mapped[str | None] = mapped_column(String(500), default=None)
    instance_id: Mapped[str | None] = mapped_column(String(36), unique=True, default=None)
    encrypted_connector_secret: Mapped[str | None] = mapped_column(Text, default=None)
    encryption_key_check: Mapped[str | None] = mapped_column(Text, default=None)
    registered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    heartbeat_interval_seconds: Mapped[int] = mapped_column(default=300)
    last_heartbeat_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_heartbeat_failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    next_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_heartbeat_status: Mapped[str | None] = mapped_column(String(32), default=None)
    last_heartbeat_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    heartbeat_failure_count: Mapped[int] = mapped_column(default=0)
    heartbeat_job_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_round_trip_ms: Mapped[float | None] = mapped_column(Float, default=None)
    last_saas_server_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
