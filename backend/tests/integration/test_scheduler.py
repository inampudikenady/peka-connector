from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.services.sources import ScanInProgressError, SourceService, source_scan_guard
from app.core.config import get_settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.repositories.documents import SqlAlchemyDocumentRepository
from app.infrastructure.database.repositories.scans import SqlAlchemyScanRepository
from app.infrastructure.database.repositories.sources import SqlAlchemySourceRepository
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.scheduling import ConnectorScheduler, _as_utc
from app.plugins.filesystem import FilesystemDocumentSourcePlugin
from app.plugins.registry import plugin_registry


def test_sqlite_scheduler_timestamp_is_normalized_to_utc() -> None:
    naive = datetime(2026, 7, 20, 12, 0)
    assert _as_utc(naive) == datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_scheduled_scan_history_overlap_and_scheduler_recovery() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    source_root = get_settings().sources_root / f"scheduler-{uuid4()}"
    source_root.mkdir()
    (source_root / "scheduled.txt").write_text("scheduled metadata", encoding="utf-8")
    if not plugin_registry.list():
        plugin_registry.register(FilesystemDocumentSourcePlugin(get_settings().sources_root))

    async with session_factory() as session:
        repository = SqlAlchemySourceRepository(session)
        source = await repository.create(
            "filesystem_documents",
            "Recovered source",
            True,
            {
                "path": str(source_root),
                "include_patterns": ["**/*.txt"],
                "exclude_patterns": [],
                "scan_interval_seconds": 300,
            },
        )
        service = SourceService(
            repository,
            SqlAlchemyDocumentRepository(session),
            SqlAlchemyScanRepository(session),
            plugin_registry,
        )
        scan = await service.scan(source.id, "scheduled")
        assert scan.trigger == "scheduled"
        history = await service.list_scan_history(source.id)
        assert history[0].trigger == "scheduled"

        guard_id = uuid4()
        assert await source_scan_guard.enter(guard_id)
        assert not await source_scan_guard.enter(guard_id)
        await source_scan_guard.leave(guard_id)
        assert await source_scan_guard.enter(source.id)
        with pytest.raises(ScanInProgressError):
            await service.scan(source.id)
        await source_scan_guard.leave(source.id)

    scheduler = ConnectorScheduler()
    await scheduler.start()
    try:
        assert scheduler.source_job_count == 1
        assert scheduler.source_interval_seconds(source.id) == 300
        async with session_factory() as session:
            repository = SqlAlchemySourceRepository(session)
            current = await repository.get(source.id)
            assert current and current.next_scheduled_scan_at
            configuration = dict(current.configuration)
            configuration["scan_interval_seconds"] = 600
            await repository.update(source.id, current.name, True, configuration)
        await scheduler.reconcile_source(source.id)
        assert scheduler.source_interval_seconds(source.id) == 600
        async with session_factory() as session:
            repository = SqlAlchemySourceRepository(session)
            current = await repository.get(source.id)
            assert current
            await repository.update(source.id, current.name, False, current.configuration)
        await scheduler.reconcile_source(source.id)
        assert scheduler.source_job_count == 0
    finally:
        await scheduler.shutdown()
