from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.infrastructure.database.types import UTCDateTime

if TYPE_CHECKING:
    from app.infrastructure.database.models.document import DocumentModel
    from app.infrastructure.database.models.scan import ScanHistoryModel


class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plugin_type: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    system_managed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    last_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    file_count: Mapped[int] = mapped_column(default=0)
    next_scheduled_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_scheduled_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    scan_in_progress: Mapped[bool] = mapped_column(Boolean, default=False)
    documents: Mapped[list["DocumentModel"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
    scans: Mapped[list["ScanHistoryModel"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
