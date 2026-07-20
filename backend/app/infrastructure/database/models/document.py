from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

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
    extension: Mapped[str] = mapped_column(String(20), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source: Mapped["SourceModel"] = relationship(back_populates="documents")
