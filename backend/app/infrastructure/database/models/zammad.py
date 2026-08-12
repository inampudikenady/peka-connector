from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import utcnow
from app.infrastructure.database.types import UTCDateTime


class ZammadConfigurationModel(Base):
    __tablename__ = "zammad_configurations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    instance_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, default=None)
    token_configured: Mapped[bool] = mapped_column(Boolean, default=False)
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    request_timeout_seconds: Mapped[float] = mapped_column(Float, default=15.0)
    sync_interval_seconds: Mapped[int] = mapped_column(default=900)
    history_window_days: Mapped[int] = mapped_column(default=90)
    group_filters_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    include_closed_tickets: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    connection_state: Mapped[str] = mapped_column(String(32), default="not_tested")
    sync_cursor_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_sync_duration_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    next_scheduled_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    synchronized_ticket_count: Mapped[int] = mapped_column(default=0)
    synchronized_article_count: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ZammadTicketModel(Base):
    __tablename__ = "zammad_tickets"
    __table_args__ = (
        UniqueConstraint("configuration_id", "external_id"),
        UniqueConstraint("configuration_id", "number"),
        UniqueConstraint("integration_id", "source_record_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    configuration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("zammad_configurations.id", ondelete="CASCADE"), index=True, default=None
    )
    instance_key: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), default="zammad")
    connector_id: Mapped[str] = mapped_column(String(200), index=True, default="local")
    integration_type: Mapped[str] = mapped_column(String(64), index=True, default="zammad")
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="RESTRICT"), index=True
    )
    source_record_id: Mapped[str] = mapped_column(String(100), index=True, default="")
    source_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True, default=utcnow)
    cache_status: Mapped[str] = mapped_column(String(32), index=True, default="active")
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    number: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(1000), index=True)
    state: Mapped[str] = mapped_column(String(255), index=True)
    state_type: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[str | None] = mapped_column(String(255), default=None)
    group_name: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    owner: Mapped[str | None] = mapped_column(String(500), default=None)
    customer: Mapped[str | None] = mapped_column(String(500), default=None)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at_source: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    updated_at_source: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    is_open: Mapped[bool] = mapped_column(Boolean, index=True)
    ticket_type: Mapped[str] = mapped_column(String(64), index=True, default="unknown")
    ticket_type_reason: Mapped[str] = mapped_column(String(500), default="")
    initial_description: Mapped[str | None] = mapped_column(Text, default=None)
    latest_update_text: Mapped[str | None] = mapped_column(Text, default=None)
    latest_update_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), index=True, default=None
    )
    referenced_asset_ids_json: Mapped[list[str]] = mapped_column(JSON, index=True, default=list)
    referenced_hostnames_json: Mapped[list[str]] = mapped_column(JSON, index=True, default=list)
    referenced_fqdns_json: Mapped[list[str]] = mapped_column(JSON, index=True, default=list)
    referenced_ip_addresses_json: Mapped[list[str]] = mapped_column(JSON, index=True, default=list)
    asset_relationships_json: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    search_text: Mapped[str] = mapped_column(Text, index=True, default="")
    visible: Mapped[bool] = mapped_column(Boolean, index=True, default=True)
    synchronized_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ZammadTicketArticleModel(Base):
    __tablename__ = "zammad_ticket_articles"
    __table_args__ = (UniqueConstraint("ticket_id", "external_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        ForeignKey("zammad_tickets.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    created_at_source: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    updated_at_source: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    author: Mapped[str | None] = mapped_column(String(500), default=None)
    sender: Mapped[str | None] = mapped_column(String(255), default=None)
    article_type: Mapped[str | None] = mapped_column(String(255), default=None)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    automated: Mapped[bool] = mapped_column(Boolean, default=False)
    subject: Mapped[str | None] = mapped_column(String(1000), default=None)
    body_text: Mapped[str] = mapped_column(Text, index=True, default="")
    raw_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
