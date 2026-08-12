"""Independent ServiceNow configuration and normalized cache models."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import utcnow
from app.infrastructure.database.types import UTCDateTime


class ServiceNowConfigurationModel(Base):
    __tablename__ = "servicenow_configurations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), unique=True, index=True
    )
    instance_url: Mapped[str] = mapped_column(String(1000))
    username: Mapped[str] = mapped_column(String(255))
    encrypted_password: Mapped[str] = mapped_column(Text)
    password_configured: Mapped[bool] = mapped_column(Boolean, default=True)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    request_timeout_seconds: Mapped[float] = mapped_column(Float, default=20.0)
    page_size: Mapped[int] = mapped_column(Integer, default=200)
    sync_interval_seconds: Mapped[int] = mapped_column(Integer, default=900)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    connection_state: Mapped[str] = mapped_column(String(32), default="not_tested")
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_sync_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    next_scheduled_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ServiceNowSyncCursorModel(Base):
    __tablename__ = "servicenow_sync_cursors"
    __table_args__ = (UniqueConstraint("integration_id", "record_type"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    record_type: Mapped[str] = mapped_column(String(64), index=True)
    cursor_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ServiceNowCIModel(Base):
    __tablename__ = "servicenow_configuration_items"
    __table_args__ = (UniqueConstraint("integration_id", "external_sys_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="servicenow", index=True)
    record_type: Mapped[str] = mapped_column(String(64), default="configuration_item")
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    external_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    sys_class_name: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    fqdn: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    ip_address: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    cache_status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class ServiceNowRelationshipModel(Base):
    __tablename__ = "servicenow_ci_relationships"
    __table_args__ = (UniqueConstraint("integration_id", "external_sys_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="servicenow", index=True)
    record_type: Mapped[str] = mapped_column(String(64), default="ci_relationship")
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    external_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    child_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    relationship_type_sys_id: Mapped[str | None] = mapped_column(String(64), default=None)
    relationship_type_name: Mapped[str] = mapped_column(String(500), index=True)
    parent_display_name: Mapped[str | None] = mapped_column(String(500), default=None)
    child_display_name: Mapped[str | None] = mapped_column(String(500), default=None)
    source_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    cache_status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class ServiceNowRecordModel(Base):
    __tablename__ = "servicenow_records"
    __table_args__ = (
        UniqueConstraint("integration_id", "record_type", "external_sys_id"),
        UniqueConstraint("integration_id", "record_type", "external_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="servicenow", index=True)
    record_type: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    external_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    short_description: Mapped[str] = mapped_column(String(1000), index=True, default="")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    state: Mapped[str] = mapped_column(String(255), index=True, default="unknown")
    state_display: Mapped[str] = mapped_column(String(255), default="Unknown")
    active: Mapped[bool] = mapped_column(Boolean, index=True, default=True)
    priority: Mapped[str | None] = mapped_column(String(100), default=None)
    assigned_to: Mapped[str | None] = mapped_column(String(500), default=None)
    assignment_group: Mapped[str | None] = mapped_column(String(500), default=None)
    cmdb_ci_sys_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    correlation_method: Mapped[str] = mapped_column(String(64), default="unmatched")
    correlation_confidence: Mapped[str] = mapped_column(String(32), default="none")
    latest_update_text: Mapped[str | None] = mapped_column(Text, default=None)
    latest_update_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    latest_update_by: Mapped[str | None] = mapped_column(String(255), default=None)
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    cache_status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class ServiceNowJournalModel(Base):
    __tablename__ = "servicenow_journal_entries"
    __table_args__ = (UniqueConstraint("integration_id", "external_sys_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    connector_id: Mapped[str] = mapped_column(String(200), index=True)
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_integrations.id", ondelete="CASCADE"), index=True
    )
    record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("servicenow_records.id", ondelete="CASCADE"), index=True, default=None
    )
    source: Mapped[str] = mapped_column(String(32), default="servicenow")
    record_type: Mapped[str] = mapped_column(String(64), default="incident_journal")
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    external_sys_id: Mapped[str] = mapped_column(String(64), index=True)
    element_id: Mapped[str] = mapped_column(String(64), index=True)
    element: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255), default=None)
    human: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
