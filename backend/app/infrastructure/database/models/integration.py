"""Generic connector integrations."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import utcnow
from app.infrastructure.database.types import UTCDateTime


class ConnectorIntegrationModel(Base):
    __tablename__ = "connector_integrations"
    __table_args__ = (UniqueConstraint("connector_id", "display_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_type: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="not_configured", index=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    capabilities_json: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    initial_sync_status: Mapped[str] = mapped_column(String(32), default="not_started")
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    legacy_zammad_configuration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("zammad_configurations.id", ondelete="CASCADE"),
        unique=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class IntegrationStreamActivationModel(Base):
    """Capability-level source activation within a connector stream."""

    __tablename__ = "integration_stream_activations"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "stream",
            "source_key",
            name="uq_stream_activation_connector_stream_source",
        ),
        Index(
            "uq_stream_activation_one_active",
            "connector_id",
            "stream",
            unique=True,
            sqlite_where=text("active = 1"),
            postgresql_where=text("active = true"),
        ),
        CheckConstraint("enabled = active", name="ck_stream_activation_selected_state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    stream: Mapped[str] = mapped_column(String(32), index=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(100))
    # v2.0.1 keeps both columns for a safe in-place migration, but constrains
    # them to one meaning: selected for use by PEKA.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
