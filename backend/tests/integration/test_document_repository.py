from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.entities.document import DiscoveredDocument
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.documents import SqlAlchemyDocumentRepository


@pytest.mark.asyncio
async def test_replaces_snapshot_after_request_transaction_has_started() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = SourceModel(
            plugin_type="filesystem_documents",
            name="Documents",
            enabled=True,
            configuration={"path": "/documents"},
        )
        session.add(source)
        await session.commit()
        await session.scalar(select(func.count(SourceModel.id)))

        counts = await SqlAlchemyDocumentRepository(session).reconcile_for_source(
            source.id,
            [
                DiscoveredDocument(
                    relative_path="guide.md",
                    filename="guide.md",
                    extension="md",
                    size_bytes=10,
                    modified_at=datetime.now(UTC),
                    sha256="a" * 64,
                )
            ],
        )

        assert counts == {"added": 1, "changed": 0, "unchanged": 0, "missing": 0}
        documents = await SqlAlchemyDocumentRepository(session).list_for_source(source.id)
        assert [document.relative_path for document in documents] == ["guide.md"]

    await engine.dispose()
