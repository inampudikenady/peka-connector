import asyncio
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
from app.domain.ports.saas import DocumentDeliveryResponse
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
            assert jobs == 3

        async with session_factory() as restarted_session:
            restored = await restarted_session.scalar(
                select(DocumentModel).where(DocumentModel.relative_path == filename)
            )
            assert restored and restored.deletion_requested
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_acknowledgement_marks_exact_version_uploaded() -> None:
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
        worker = DocumentDeliveryWorker(session, settings, fake, encryption)  # type: ignore[arg-type]
        assert await worker.run_once()
        await session.refresh(document)
        assert document.delivery_status == "UPLOADED"
        assert document.remote_document_id == "remote-document"
        assert document.remote_version_id == "remote-version"
        assert len(fake.keys) == 1
        job = await session.scalar(
            select(DocumentDeliveryJobModel).where(
                DocumentDeliveryJobModel.document_id == document.id
            )
        )
        assert job and job.state == "SUCCEEDED"
        assert job.spool_path and not await asyncio.to_thread(Path(job.spool_path).exists)
    await asyncio.to_thread((settings.managed_documents_root / filename).unlink, missing_ok=True)


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
