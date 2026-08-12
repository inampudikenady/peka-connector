from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.services.knowledge import (
    KnowledgeChunk,
    KnowledgeSearchResult,
    KnowledgeStoreHealth,
    KnowledgeUnavailableError,
    LocalKnowledgeService,
    QdrantKnowledgeStore,
)
from app.core.config import Settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import DocumentModel
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.models.source import SourceModel


class ObservableStore:
    def __init__(self, *, fail_search: bool = False) -> None:
        self.fail_search = fail_search

    async def initialize(self, dimension: int) -> None:
        return None

    async def health_check(self) -> bool:
        return True

    async def health_status(self) -> KnowledgeStoreHealth:
        return KnowledgeStoreHealth(True, True, "runtime-test-version", True)

    async def upsert_chunks(self, tenant_id: UUID, chunks: list[KnowledgeChunk]) -> None:
        return None

    async def search(
        self,
        tenant_id: UUID,
        vector: list[float],
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        if self.fail_search:
            raise httpx.ConnectError("unavailable")
        return []

    async def delete_document(self, tenant_id: UUID, document_id: UUID) -> None:
        return None

    async def delete_tenant_knowledge(self, tenant_id: UUID) -> None:
        return None

    async def count(self, tenant_id: UUID) -> int:
        raise AssertionError("Overview counts must come from connector document metadata")


def config(tmp_path: Path) -> Settings:
    return Settings(
        jwt_secret="x" * 32,
        encryption_key="y" * 32,
        environment="development",
        database_url="sqlite+aiosqlite:///:memory:",
        data_root=tmp_path / "data",
        sources_root=tmp_path / "sources",
    )


async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_stats_use_documents_page_state_for_documents_chunks_pending_and_failed(
    tmp_path: Path,
) -> None:
    engine, factory = await session_factory()
    indexed_at = datetime(2026, 8, 12, 10, 30, tzinfo=UTC)
    async with factory() as session:
        source = SourceModel(plugin_type="filesystem_documents", name="Documents", configuration={})
        session.add_all(
            [source, ProductSettingsModel(id=1, instance_id=str(uuid4()), tenant_id=str(uuid4()))]
        )
        await session.flush()
        for status, chunks in (("INDEXED", 2), ("PENDING", 0), ("FAILED", 0)):
            session.add(
                DocumentModel(
                    source_id=source.id,
                    relative_path=f"{status}.txt",
                    filename=f"{status}.txt",
                    extension=".txt",
                    mime_type="text/plain",
                    size_bytes=1,
                    modified_at=indexed_at,
                    sha256=status.casefold().ljust(64, "0")[:64],
                    content_hash=status.casefold().ljust(64, "0")[:64],
                    knowledge_status=status,
                    indexed_chunk_count=chunks,
                    knowledge_indexed_at=indexed_at if status == "INDEXED" else None,
                )
            )
        await session.commit()
        stats = await LocalKnowledgeService(session, config(tmp_path), ObservableStore()).stats()
        assert (stats.document_count, stats.indexed_chunk_count) == (1, 2)
        assert (stats.pending_count, stats.failed_count) == (1, 1)
        assert stats.last_index_activity == indexed_at
        assert stats.engine_version == "runtime-test-version"
    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_new_connector_is_healthy_and_has_never_activity(tmp_path: Path) -> None:
    engine, factory = await session_factory()
    async with factory() as session:
        session.add(ProductSettingsModel(id=1, instance_id=str(uuid4())))
        await session.commit()
        stats = await LocalKnowledgeService(session, config(tmp_path), ObservableStore()).stats()
        assert stats.document_count == stats.indexed_chunk_count == 0
        assert stats.pending_count == stats.failed_count == 0
        assert stats.last_index_activity is None
        assert stats.last_search_at is None
        assert stats.search_operational is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_only_successful_qdrant_search_updates_durable_last_search(tmp_path: Path) -> None:
    engine, factory = await session_factory()
    tenant_id = uuid4()
    async with factory() as session:
        session.add(ProductSettingsModel(id=1, instance_id=str(uuid4()), tenant_id=str(tenant_id)))
        await session.commit()
        service = LocalKnowledgeService(session, config(tmp_path), ObservableStore())
        assert await service.search("a successful empty search", 5) == []
        successful_at = (
            await service.operations.get_settings()
        ).last_successful_knowledge_search_at
        assert successful_at is not None
        failing = LocalKnowledgeService(
            session, config(tmp_path), ObservableStore(fail_search=True)
        )
        with pytest.raises(KnowledgeUnavailableError):
            await failing.search("failed search", 5)
        assert (
            await failing.operations.get_settings()
        ).last_successful_knowledge_search_at == successful_at
    await engine.dispose()


@pytest.mark.asyncio
async def test_qdrant_version_is_detected_from_runtime_and_is_optional(monkeypatch) -> None:
    responses = iter(
        [
            httpx.Response(200, json={"version": "9.8.7"}),
            httpx.Response(200),
            httpx.Response(200, json={"result": {"status": "green"}}),
        ]
    )

    async def get(_client, _url):
        return next(responses)

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    health = await QdrantKnowledgeStore("http://qdrant:6333", "peka_documents").health_status()
    assert health.engine_version == "9.8.7"
    assert health.qdrant_reachable and health.collection_available and health.statistics_readable
