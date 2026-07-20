from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.document import DiscoveredDocument
from app.infrastructure.database.models.document import DocumentModel


class SqlAlchemyDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_source(
        self, source_id: UUID, documents: Sequence[DiscoveredDocument]
    ) -> int:
        try:
            await self._session.execute(
                delete(DocumentModel).where(DocumentModel.source_id == source_id)
            )
            self._session.add_all(
                DocumentModel(
                    source_id=source_id,
                    relative_path=document.relative_path,
                    filename=document.filename,
                    extension=document.extension,
                    size_bytes=document.size_bytes,
                    modified_at=document.modified_at,
                    sha256=document.sha256,
                )
                for document in documents
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return len(documents)

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
            )
            for model in result.all()
        ]
