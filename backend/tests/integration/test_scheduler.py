from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.services.servicenow import ServiceNowError, ServiceNowService
from app.application.services.sources import ScanInProgressError, SourceService, source_scan_guard
from app.core.config import get_settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.integration import (
    ConnectorIntegrationModel,
    IntegrationStreamActivationModel,
)
from app.infrastructure.database.models.servicenow import ServiceNowConfigurationModel
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
async def test_heartbeat_misfire_runs_immediately_after_resume() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    scheduler = ConnectorScheduler()
    scheduler._scheduler.start(paused=True)
    try:
        await scheduler.schedule_heartbeat(30)
        job = scheduler._scheduler.get_job("heartbeat")
        assert job is not None
        assert job.misfire_grace_time is None
    finally:
        scheduler._scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_servicenow_scheduler_recovers_repeats_and_registers_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    integration_id = uuid4()
    configuration_id = uuid4()
    async with session_factory() as session:
        session.add(
            ConnectorIntegrationModel(
                id=integration_id,
                connector_id="local-connector",
                integration_type="servicenow",
                display_name="ServiceNow",
                category="Ticketing / CMDB",
                enabled=True,
                status="healthy",
                capabilities_json={"ticketing": True, "cmdb": True},
            )
        )
        session.add(
            ServiceNowConfigurationModel(
                id=configuration_id,
                integration_id=integration_id,
                instance_url="https://instance.service-now.com",
                username="api-reader",
                encrypted_password="not-used-by-this-test",
                sync_interval_seconds=900,
                enabled=True,
            )
        )
        session.add(
            IntegrationStreamActivationModel(
                connector_id="local-connector",
                integration_id=integration_id,
                stream="cmdb",
                source_key="servicenow_cmdb",
                source_name="ServiceNow CMDB",
                enabled=True,
                active=True,
            )
        )
        await session.commit()

    calls = 0

    async def synchronize(_service: ServiceNowService, received_id):
        nonlocal calls
        calls += 1
        assert received_id == configuration_id
        if calls == 1:
            raise ServiceNowError("TEMPORARY_FAILURE", "Temporary ServiceNow failure.", 502)
        return {
            "counts": {"configuration_items": 4, "relationships": 17},
            "stage_errors": {},
        }

    monkeypatch.setattr(ServiceNowService, "synchronize", synchronize)

    scheduler = ConnectorScheduler()
    scheduler._scheduler.start(paused=True)
    try:
        await scheduler.reconcile_servicenow(configuration_id)
        job = scheduler._scheduler.get_job(f"servicenow:{configuration_id}")
        assert job is not None
        assert job.trigger.interval.total_seconds() == 900
        assert job.misfire_grace_time is None

        # A failed recurring run is recorded, but does not remove the job.
        await scheduler._run_servicenow_sync(configuration_id)
        assert scheduler._scheduler.get_job(f"servicenow:{configuration_id}") is not None
        # The next run can execute successfully without manual intervention.
        await scheduler._run_servicenow_sync(configuration_id)
        assert calls == 2

        async with session_factory() as session:
            configuration = await session.get(ServiceNowConfigurationModel, configuration_id)
            assert configuration is not None
            assert configuration.last_attempted_sync_at is not None
            assert configuration.next_scheduled_sync_at is not None
    finally:
        scheduler._scheduler.shutdown(wait=False)

    restarted = ConnectorScheduler()
    restarted._scheduler.start(paused=True)
    try:
        # Startup reconstruction uses persisted configuration and capability selection.
        await restarted.reconcile_servicenow(configuration_id)
        assert restarted._scheduler.get_job(f"servicenow:{configuration_id}") is not None
    finally:
        restarted._scheduler.shutdown(wait=False)


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
