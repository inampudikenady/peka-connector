from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.infrastructure.database.types import UTCDateTime

if TYPE_CHECKING:
    from app.infrastructure.database.models.source import SourceModel


class DocumentModel(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "relative_path"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    relative_path: Mapped[str] = mapped_column(String(2048))
    filename: Mapped[str] = mapped_column(String(512))
    normalized_filename: Mapped[str] = mapped_column(String(512), default="")
    document_key: Mapped[str] = mapped_column(String(2200), default="")
    extension: Mapped[str] = mapped_column(String(20), index=True)
    mime_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    modified_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sha256: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    discovered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
    state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    local_status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    upload_attempt_count: Mapped[int] = mapped_column(default=0)
    last_upload_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    remote_document_id: Mapped[str | None] = mapped_column(String(200), default=None)
    remote_version_id: Mapped[str | None] = mapped_column(String(200), default=None)
    owner_instance_id: Mapped[str | None] = mapped_column(String(36), default=None, index=True)
    owner_connector_id: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    owner_tenant_id: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    last_error_message: Mapped[str | None] = mapped_column(String(1000), default=None)
    first_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC)
    )
    stable_since_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    entry_method: Mapped[str] = mapped_column(String(32), default="DIRECT_COPY")
    version_sequence: Mapped[int] = mapped_column(default=1)
    deletion_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    source: Mapped["SourceModel"] = relationship(back_populates="documents")
    delivery_jobs: Mapped[list["DocumentDeliveryJobModel"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    if TYPE_CHECKING:
        can_delete: bool
        delete_unavailable_reason: str | None
        deletion_in_progress: bool


class DocumentDeliveryJobModel(Base):
    __tablename__ = "document_delivery_jobs"
    __table_args__ = (
        UniqueConstraint("document_id", "version_sequence", "operation"),
        UniqueConstraint("idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    version_sequence: Mapped[int] = mapped_column(default=1)
    operation: Mapped[str] = mapped_column(String(16), index=True)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_message: Mapped[str | None] = mapped_column(String(1000), default=None)
    correlation_id: Mapped[UUID] = mapped_column(default=uuid4, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    spool_path: Mapped[str | None] = mapped_column(Text, default=None)
    document: Mapped["DocumentModel"] = relationship(back_populates="delivery_jobs")
