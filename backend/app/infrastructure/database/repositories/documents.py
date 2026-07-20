from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.document import DiscoveredDocument
from app.infrastructure.database.models.document import DocumentModel


class SqlAlchemyDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reconcile_for_source(
        self, source_id: UUID, documents: Sequence[DiscoveredDocument]
    ) -> dict[str, int]:
        now = datetime.now(UTC)
        existing_result = await self._session.scalars(
            select(DocumentModel).where(DocumentModel.source_id == source_id)
        )
        existing = {model.relative_path: model for model in existing_result.all()}
        counts = {"added": 0, "changed": 0, "unchanged": 0, "missing": 0}
        seen: set[str] = set()
        try:
            for document in documents:
                seen.add(document.relative_path)
                model = existing.get(document.relative_path)
                if model is None:
                    self._session.add(
                        DocumentModel(
                            source_id=source_id,
                            relative_path=document.relative_path,
                            filename=document.filename,
                            extension=document.extension,
                            size_bytes=document.size_bytes,
                            modified_at=document.modified_at,
                            sha256=document.sha256,
                            discovered_at=now,
                            last_seen_at=now,
                            state="active",
                        )
                    )
                    counts["added"] += 1
                    continue
                stored_modified = model.modified_at
                if stored_modified.tzinfo is None:
                    stored_modified = stored_modified.replace(tzinfo=UTC)
                changed = (
                    model.sha256 != document.sha256
                    or model.size_bytes != document.size_bytes
                    or stored_modified != document.modified_at
                )
                counts["changed" if changed else "unchanged"] += 1
                model.filename = document.filename
                model.extension = document.extension
                model.size_bytes = document.size_bytes
                model.modified_at = document.modified_at
                model.sha256 = document.sha256
                model.last_seen_at = now
                model.state = "active"
            for relative_path, model in existing.items():
                if relative_path not in seen:
                    model.state = "missing"
                    counts["missing"] += 1
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return counts

    async def list_for_source(self, source_id: UUID) -> Sequence[DiscoveredDocument]:
        result = await self._session.scalars(
            select(DocumentModel)
            .where(DocumentModel.source_id == source_id)
            .order_by(DocumentModel.relative_path)
        )
        return [
            DiscoveredDocument(
                relative_path=model.relative_path,
                filename=model.filename,
                extension=model.extension,
                size_bytes=model.size_bytes,
                modified_at=model.modified_at,
                sha256=model.sha256,
                discovered_at=model.discovered_at,
                last_seen_at=model.last_seen_at,
                state=model.state,
            )
            for model in result.all()
        ]
