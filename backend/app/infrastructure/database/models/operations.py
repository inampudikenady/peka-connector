from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


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
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)


class ApplicationLogModel(Base):
    __tablename__ = "application_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    level: Mapped[str] = mapped_column(String(20), index=True)
    component: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)


class ProductSettingsModel(Base):
    __tablename__ = "product_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    connector_display_name: Mapped[str] = mapped_column(String(200), default="PEKA Connector")
    environment_label: Mapped[str] = mapped_column(String(100), default="Production")
    log_level: Mapped[str] = mapped_column(String(20), default="INFO")
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    saas_status: Mapped[str] = mapped_column(String(32), default="not_registered")
    connector_id: Mapped[str | None] = mapped_column(String(200), default=None)
    tenant_id: Mapped[str | None] = mapped_column(String(200), default=None)
    saas_url: Mapped[str | None] = mapped_column(String(500), default=None)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
