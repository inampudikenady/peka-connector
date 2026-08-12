import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.application.services.documents import (
    DocumentDeliveryWorker,
    ManagedDocumentService,
)
from app.core.config import get_settings
from app.domain.ports.saas import DocumentDeliveryResponse, SaaSClientError
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import (
    DocumentDeliveryJobModel,
    DocumentModel,
)
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.security.secrets import SecretEncryptionService


class AcknowledgingClient:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def deliver_document(
        self,
        _base_url: str,
        _connector_id: UUID,
        _connector_secret: str,
        metadata: Any,
        idempotency_key: str,
        _file_path: Path | None,
    ) -> DocumentDeliveryResponse:
        self.keys.append(idempotency_key)
        return DocumentDeliveryResponse(
            accepted=True,
            document_id="remote-document",
            version_id="remote-version",
            content_hash=metadata.content_hash,
            ingestion_status="RECEIVED",
        )


class UnavailableClient:
    async def deliver_document(
        self,
        _base_url: str,
        _connector_id: UUID,
        _connector_secret: str,
        _metadata: Any,
        _idempotency_key: str,
        _file_path: Path | None,
    ) -> DocumentDeliveryResponse:
        raise SaaSClientError("transport", "PEKA is temporarily unavailable")


async def _reset() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_direct_copy_stability_change_delete_and_restart_state() -> None:
    await _reset()
    settings = get_settings()
    filename = f"direct-{uuid4()}.txt"
    path = settings.managed_documents_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("first version", encoding="utf-8")
    try:
        async with session_factory() as session:
            service = ManagedDocumentService(session, settings)
            first = await service.reconcile()
            assert first["delayed"] >= 1
            document = await session.scalar(
                select(DocumentModel).where(DocumentModel.relative_path == filename)
            )
            assert document and document.local_status == "WAITING_FOR_STABILITY"
            document.stable_since_at = datetime.now(UTC) - timedelta(seconds=30)
            await session.commit()
            second = await service.reconcile()
            assert second["discovered"] == 1
            initial_hash = document.content_hash
            initial_version = document.version_sequence

            path.write_text("second version", encoding="utf-8")
            await service.reconcile()
            document.stable_since_at = datetime.now(UTC) - timedelta(seconds=30)
            await session.commit()
            changed = await service.reconcile()
            assert changed["changed"] == 1
            assert document.content_hash != initial_hash
            assert document.version_sequence == initial_version + 1

            path.unlink()
            removed = await service.reconcile()
            assert removed["removed"] == 1
            assert document.deletion_requested
            jobs = int(await session.scalar(select(func.count(DocumentDeliveryJobModel.id))) or 0)
            assert jobs == 0
            assert document.knowledge_status == "DELETE_PENDING"

        async with session_factory() as restarted_session:
            restored = await restarted_session.scalar(
                select(DocumentModel).where(DocumentModel.relative_path == filename)
            )
            assert restored and restored.deletion_requested
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_document_bytes_are_not_delivered_to_saas_in_v1() -> None:
    await _reset()
    settings = get_settings()
    filename = f"delivery-{uuid4()}.txt"
    encryption = SecretEncryptionService(settings.encryption_key)
    fake = AcknowledgingClient()
    async with session_factory() as session:
        service = ManagedDocumentService(session, settings)
        await service.ensure_managed_source()
        upload = StarletteUploadFile(
            filename=filename,
            file=io.BytesIO(b"deliver me"),
            headers=Headers({"content-type": "text/plain"}),
        )
        document = await service.upload(upload, 0)
        operations = SqlAlchemyOperationsRepository(session)
        await operations.complete_registration(
            str(uuid4()),
            str(uuid4()),
            encryption.encrypt("connector-secret"),
            300,
            datetime.now(UTC),
            "https://peka.example.test",
        )
        await session.refresh(document)
        assert document.delivery_status == "LOCAL_ONLY"
        assert document.knowledge_status == "PENDING"
        assert document.remote_document_id is None
        assert document.remote_version_id is None
        assert fake.keys == []
        job = await session.scalar(
            select(DocumentDeliveryJobModel).where(
                DocumentDeliveryJobModel.document_id == document.id
            )
        )
        assert job is None
        await service.delete(document.id)
        await session.refresh(document)
        assert document.deletion_requested
        assert document.delivery_status == "LOCAL_ONLY"
        assert document.knowledge_status == "DELETE_PENDING"
        assert not (settings.managed_documents_root / filename).exists()
        delete_job = await session.scalar(
            select(DocumentDeliveryJobModel).where(
                DocumentDeliveryJobModel.document_id == document.id,
                DocumentDeliveryJobModel.operation == "DELETE",
            )
        )
        assert delete_job is None


@pytest.mark.asyncio
async def test_unavailable_saas_does_not_affect_local_document_lifecycle() -> None:
    await _reset()
    settings = get_settings()
    filename = f"delete-retry-{uuid4()}.txt"
    encryption = SecretEncryptionService(settings.encryption_key)
    async with session_factory() as session:
        service = ManagedDocumentService(session, settings)
        operations = SqlAlchemyOperationsRepository(session)
        await operations.complete_registration(
            str(uuid4()),
            str(uuid4()),
            encryption.encrypt("connector-secret"),
            300,
            datetime.now(UTC),
            "https://peka.example.test",
        )
        upload = StarletteUploadFile(
            filename=filename,
            file=io.BytesIO(b"delete me later"),
            headers=Headers({"content-type": "text/plain"}),
        )
        document = await service.upload(upload, 0)
        await service.delete(document.id)

        unavailable = DocumentDeliveryWorker(
            session,
            settings,
            UnavailableClient(),
            encryption,  # type: ignore[arg-type]
        )
        assert not await unavailable.run_once()
        await session.refresh(document)
        assert document.deletion_requested
        assert document.deleted_at is not None
        delete_job = await session.scalar(
            select(DocumentDeliveryJobModel).where(
                DocumentDeliveryJobModel.document_id == document.id,
                DocumentDeliveryJobModel.operation == "DELETE",
            )
        )
        assert delete_job is None
        assert document.knowledge_status == "DELETE_PENDING"
        assert document.delivery_status == "LOCAL_ONLY"


@pytest.mark.asyncio
async def test_matching_source_is_reused_and_unrelated_legacy_source_is_preserved() -> None:
    await _reset()
    settings = get_settings()
    matching_id = uuid4()
    legacy_id = uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                SourceModel(
                    id=matching_id,
                    plugin_type="filesystem_documents",
                    name="Old managed path",
                    enabled=False,
                    configuration={
                        "path": "/data/sources/documents",
                        "scan_interval_seconds": 900,
                    },
                ),
                SourceModel(
                    id=legacy_id,
                    plugin_type="filesystem_documents",
                    name="Legacy manuals",
                    enabled=True,
                    configuration={
                        "path": "/data/sources/manuals",
                        "scan_interval_seconds": 300,
                    },
                ),
            ]
        )
        await session.commit()
        service = ManagedDocumentService(session, settings)
        first = await service.ensure_managed_source()
        second = await service.ensure_managed_source()
        assert first.id == matching_id == second.id
        assert first.name == "Uploaded Documents"
        assert first.enabled is False
        assert first.configuration["scan_interval_seconds"] == 900
        sources = list((await session.scalars(select(SourceModel))).all())
        assert len(sources) == 2
        assert sum(source.system_managed for source in sources) == 1
        legacy = await session.get(SourceModel, legacy_id)
        assert legacy and legacy.name == "Legacy manuals" and not legacy.system_managed
