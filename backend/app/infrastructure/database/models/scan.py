from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.infrastructure.database.models.source import SourceModel


class ScanHistoryModel(Base):
    __tablename__ = "scan_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    discovered_count: Mapped[int] = mapped_column(default=0)
    added_count: Mapped[int] = mapped_column(default=0)
    changed_count: Mapped[int] = mapped_column(default=0)
    unchanged_count: Mapped[int] = mapped_column(default=0)
    missing_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    correlation_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, index=True)
    source: Mapped["SourceModel"] = relationship(back_populates="scans")
