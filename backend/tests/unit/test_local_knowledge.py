from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.services.knowledge import (
    ContentSanitizer,
    KnowledgeChunk,
    KnowledgeSearchResult,
    KnowledgeStoreHealth,
    LocalKnowledgeService,
)
from app.core.config import Settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import DocumentModel
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.models.source import SourceModel


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self.points: dict[UUID, tuple[UUID, KnowledgeChunk]] = {}
        self.dimension: int | None = None

    async def initialize(self, dimension: int) -> None:
        self.dimension = dimension

    async def health_check(self) -> bool:
        return True

    async def health_status(self) -> KnowledgeStoreHealth:
        return KnowledgeStoreHealth(True, True)

    async def upsert_chunks(self, tenant_id: UUID, chunks: list[KnowledgeChunk]) -> None:
        for chunk in chunks:
            self.points[chunk.chunk_id] = (tenant_id, chunk)

    async def search(
        self,
        tenant_id: UUID,
        vector: list[float],
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        results = []
        for point_tenant, chunk in self.points.values():
            if point_tenant != tenant_id:
                continue
            if filters and filters.get("document_id") != str(chunk.document_id):
                continue
            results.append(
                KnowledgeSearchResult(
                    chunk.document_id,
                    chunk.chunk_id,
                    chunk.content,
                    sum(a * b for a, b in zip(vector, chunk.vector, strict=True)),
                    "Documents",
                    chunk.metadata,
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    async def delete_document(self, tenant_id: UUID, document_id: UUID) -> None:
        self.points = {
            key: value
            for key, value in self.points.items()
            if value[0] != tenant_id or value[1].document_id != document_id
        }

    async def delete_tenant_knowledge(self, tenant_id: UUID) -> None:
        self.points = {
            key: value for key, value in self.points.items() if value[0] != tenant_id
        }

    async def count(self, tenant_id: UUID) -> int:
        return sum(point_tenant == tenant_id for point_tenant, _chunk in self.points.values())


def settings(tmp_path: Path) -> Settings:
    return Settings(
        jwt_secret="x" * 32,
        encryption_key="y" * 32,
        environment="development",
        database_url="sqlite+aiosqlite:///:memory:",
        data_root=tmp_path / "data",
        sources_root=tmp_path / "sources",
    )


@pytest.mark.asyncio
async def test_collection_upsert_query_update_and_delete_are_tenant_scoped(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid4()
    other_tenant = uuid4()
    store = MemoryKnowledgeStore()
    config = settings(tmp_path)
    config.managed_documents_root.mkdir(parents=True)
    path = config.managed_documents_root / "runbook.txt"
    path.write_text("SAP latency troubleshooting restart application service", encoding="utf-8")

    async with factory() as session:
        source = SourceModel(
            plugin_type="filesystem_documents",
            name="Documents",
            configuration={"path": str(config.managed_documents_root)},
        )
        session.add(source)
        session.add(ProductSettingsModel(id=1, instance_id=str(uuid4()), tenant_id=str(tenant_id)))
        await session.flush()
        document = DocumentModel(
            source_id=source.id,
            relative_path=path.name,
            filename=path.name,
            extension=".txt",
            mime_type="text/plain",
            size_bytes=path.stat().st_size,
            modified_at=datetime.now(UTC),
            sha256="a" * 64,
            content_hash="a" * 64,
            owner_tenant_id=str(tenant_id),
        )
        session.add(document)
        await session.commit()
        service = LocalKnowledgeService(session, config, store=store)

        await service.initialize()
        assert store.dimension == config.knowledge_embedding_dimension
        assert await service.index_document(document) == 1
        other_chunk = KnowledgeChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="SAP latency private procedure for the other tenant",
            vector=service.embeddings.embed(
                ["SAP latency private procedure for the other tenant"]
            )[0],
            metadata={"filename": "private.txt", "chunk_index": 0},
        )
        await store.upsert_chunks(other_tenant, [other_chunk])
        assert (await service.search("SAP latency", 5))[0].document_id == document.id
        assert all(
            result.document_id != other_chunk.document_id
            for result in await service.search("private procedure", 5)
        )
        assert (await store.search(other_tenant, other_chunk.vector, 5))[0].document_id == (
            other_chunk.document_id
        )

        old_ids = {
            chunk_id
            for chunk_id, (point_tenant, _chunk) in store.points.items()
            if point_tenant == tenant_id
        }
        path.write_text("database failover recovery procedure", encoding="utf-8")
        document.content_hash = "b" * 64
        await session.commit()
        await service.index_document(document)
        assert old_ids.isdisjoint(store.points)
        assert len(store.points) == document.indexed_chunk_count + 1

        await service.delete_document(document.id)
        assert list(store.points.values()) == [(other_tenant, other_chunk)]
        assert document.knowledge_status == "DELETED"

    await engine.dispose()


def test_sanitizer_removes_connector_credentials_before_persistence() -> None:
    sanitized = ContentSanitizer().sanitize(
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
        "password=do-not-index-this\n"
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
        "safe runbook text"
    )
    assert "abcdefghijklmnopqrstuvwxyz" not in sanitized
    assert "do-not-index-this" not in sanitized
    assert "BEGIN PRIVATE KEY" not in sanitized
    assert "safe runbook text" in sanitized


@pytest.mark.asyncio
async def test_grub_query_returns_relevant_chunk_and_irrelevant_query_is_rejected(
    tmp_path: Path,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid4()
    store = MemoryKnowledgeStore()
    config = settings(tmp_path)
    config.managed_documents_root.mkdir(parents=True)
    path = config.managed_documents_root / "boot_disk_migration.txt"
    path.write_text(
        "After creating /dev/sdb2 for the new boot partition, install GRUB:\n"
        "grub\n"
        "device (hd0) /dev/sdb\n"
        "root (hd0,1)\n"
        "setup (hd0)\n"
        "quit\n",
        encoding="utf-8",
    )
    async with factory() as session:
        source = SourceModel(
            plugin_type="filesystem_documents",
            name="Documents",
            configuration={"path": str(config.managed_documents_root)},
        )
        session.add(source)
        session.add(ProductSettingsModel(id=1, instance_id=str(uuid4()), tenant_id=str(tenant_id)))
        await session.flush()
        document = DocumentModel(
            source_id=source.id,
            relative_path=path.name,
            filename=path.name,
            extension=".txt",
            mime_type="text/plain",
            size_bytes=path.stat().st_size,
            modified_at=datetime.now(UTC),
            sha256="c" * 64,
            content_hash="c" * 64,
            owner_tenant_id=str(tenant_id),
        )
        session.add(document)
        await session.commit()
        service = LocalKnowledgeService(session, config, store=store)
        await service.index_document(document)

        results = await service.search(
            "What GRUB commands should I use after creating /dev/sdb2 for the new boot partition?",
            5,
        )
        assert len(results) == 1
        assert "device (hd0) /dev/sdb" in results[0].content
        assert results[0].score >= 0.60
        assert results[0].metadata["vector_score"] < results[0].score
        assert results[0].metadata["retrieval_score_model"] == "local-hybrid-v1"

        assert await service.search("How do I prune roses during a lunar eclipse?", 5) == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_search_diagnostics_distinguish_zero_hits_from_rejected_hits(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid4()
    store = MemoryKnowledgeStore()
    config = settings(tmp_path)
    async with factory() as session:
        session.add(ProductSettingsModel(id=1, instance_id=str(uuid4()), tenant_id=str(tenant_id)))
        await session.commit()
        service = LocalKnowledgeService(session, config, store=store)
        with caplog.at_level("INFO"):
            assert await service.search("database recovery", 5) == []
        assert "rejection_reason=qdrant_returned_zero_results" in caplog.text

        chunk = KnowledgeChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="orchard irrigation schedule and soil moisture",
            vector=service.embeddings.embed(["orchard irrigation schedule and soil moisture"])[0],
            metadata={"filename": "orchard.txt", "chunk_index": 0},
        )
        await store.upsert_chunks(tenant_id, [chunk])
        caplog.clear()
        with caplog.at_level("INFO"):
            assert await service.search("database recovery", 5) == []
        assert "qdrant_result_count=1 parsed_result_count=1 accepted_result_count=0" in caplog.text
        assert "rejection_reason=qdrant_results_rejected_by_evidence_filter" in caplog.text

    await engine.dispose()


def test_compose_bundles_private_persistent_qdrant_and_release_is_consistent() -> None:
    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    release = (root / "release.json").read_text(encoding="utf-8")
    assert version == "2.0.1"
    assert '"version": "2.0.1"' in release
    assert "qdrant/qdrant:v1.14.1" in compose
    assert "peka_connector_qdrant_data:/qdrant/storage" in compose
    qdrant_service = compose.split("  qdrant:", 1)[1].split("volumes:", 1)[0]
    assert "ports:" not in qdrant_service
    assert "condition: service_healthy" in compose
