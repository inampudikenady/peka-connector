from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class CMDBDatasetModel(Base):
    __tablename__ = "cmdb_datasets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), index=True)
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cmdb_dataset_versions.id", use_alter=True, ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class CMDBMappingProfileModel(Base):
    __tablename__ = "cmdb_mapping_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalization_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    required_field_policy: Mapped[str] = mapped_column(String(64), default="any_identity")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class CMDBDatasetVersionModel(Base):
    __tablename__ = "cmdb_dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("cmdb_datasets.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column()
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    stored_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    file_type: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column()
    sheet_name: Mapped[str | None] = mapped_column(String(255), default=None)
    header_row: Mapped[int | None] = mapped_column(default=None)
    mapping_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cmdb_mapping_profiles.id", ondelete="SET NULL"), default=None
    )
    mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    total_rows: Mapped[int] = mapped_column(default=0)
    valid_rows: Mapped[int] = mapped_column(default=0)
    invalid_rows: Mapped[int] = mapped_column(default=0)
    duplicate_rows: Mapped[int] = mapped_column(default=0)
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CMDBRecordModel(Base):
    __tablename__ = "cmdb_records"
    __table_args__ = (UniqueConstraint("dataset_version_id", "source_row_number"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("cmdb_dataset_versions.id", ondelete="CASCADE"), index=True
    )
    source_row_number: Mapped[int] = mapped_column()
    source_record_key: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    hostname: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    fqdn: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    primary_ip: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    cloud_instance_id: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    serial_number: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    asset_tag: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    normalized_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(32), index=True)
    validation_errors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    row_checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InventoryAssetModel(Base):
    __tablename__ = "inventory_assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(500), index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    fqdn: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    primary_ip: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    additional_ips_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    asset_type: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    environment: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    operating_system: Mapped[str | None] = mapped_column(String(500), default=None)
    cloud_provider: Mapped[str | None] = mapped_column(String(255), default=None)
    cloud_instance_id: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    serial_number: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    asset_tag: Mapped[str | None] = mapped_column(String(500), index=True, default=None)
    location: Mapped[str | None] = mapped_column(String(500), default=None)
    application: Mapped[str | None] = mapped_column(String(500), default=None)
    business_owner: Mapped[str | None] = mapped_column(String(500), default=None)
    technical_owner: Mapped[str | None] = mapped_column(String(500), default=None)
    lifecycle_status: Mapped[str | None] = mapped_column(String(100), index=True, default=None)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class InventoryObservationModel(Base):
    __tablename__ = "inventory_observations"
    __table_args__ = (UniqueConstraint("source_type", "source_record_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="SET NULL"), index=True, default=None
    )
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_configuration_id: Mapped[UUID | None] = mapped_column(index=True, default=None)
    source_record_id: Mapped[str] = mapped_column(String(500), index=True)
    observed_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_reference: Mapped[str] = mapped_column(String(1000))
    raw_checksum: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), index=True, default="observed")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class InventoryIdentityModel(Base):
    __tablename__ = "inventory_identities"
    __table_args__ = (UniqueConstraint("observation_id", "identity_type", "normalized_value"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="CASCADE"), index=True, default=None
    )
    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_observations.id", ondelete="CASCADE"), index=True
    )
    identity_type: Mapped[str] = mapped_column(String(64), index=True)
    original_value: Mapped[str] = mapped_column(String(1000))
    normalized_value: Mapped[str] = mapped_column(String(1000), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InventoryCorrelationModel(Base):
    __tablename__ = "inventory_correlations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_observations.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="SET NULL"), index=True, default=None
    )
    match_method: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    decision_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


class InventoryConflictModel(Base):
    __tablename__ = "inventory_conflicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="CASCADE"), index=True, default=None
    )
    observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_observations.id", ondelete="CASCADE"), index=True, default=None
    )
    field_name: Mapped[str] = mapped_column(String(100), index=True)
    source_values_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    preferred_value: Mapped[str | None] = mapped_column(Text, default=None)
    resolution_status: Mapped[str] = mapped_column(String(32), index=True, default="open")
    resolution_reason: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    resolved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class InventoryServiceModel(Base):
    __tablename__ = "inventory_services"
    __table_args__ = (UniqueConstraint("observation_id", "protocol", "port", "path"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_observations.id", ondelete="CASCADE"), index=True
    )
    service_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    protocol: Mapped[str] = mapped_column(String(16))
    port: Mapped[int] = mapped_column(index=True)
    path: Mapped[str] = mapped_column(String(1000), default="/")
    endpoint: Mapped[str] = mapped_column(String(2000))
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InventoryDependencyModel(Base):
    __tablename__ = "inventory_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "source_asset_id", "relation_type", "target_reference", "source_observation_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="CASCADE"), index=True
    )
    target_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_assets.id", ondelete="SET NULL"), index=True, default=None
    )
    source_observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_observations.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(64), index=True)
    target_reference: Mapped[str] = mapped_column(String(2000))
    evidence: Mapped[str] = mapped_column(String(1000))
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PrometheusConfigurationModel(Base):
    __tablename__ = "prometheus_configurations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    auth_type: Mapped[str] = mapped_column(String(32), default="none")
    username: Mapped[str | None] = mapped_column(String(500), default=None)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, default=None)
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_ca_path: Mapped[str | None] = mapped_column(Text, default=None)
    request_timeout_seconds: Mapped[float] = mapped_column(Float, default=10.0)
    scan_interval_seconds: Mapped[int] = mapped_column(default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_failed_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    target_count: Mapped[int] = mapped_column(default=0)
    healthy_target_count: Mapped[int] = mapped_column(default=0)
    unhealthy_target_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
