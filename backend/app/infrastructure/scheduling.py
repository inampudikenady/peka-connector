import logging
from asyncio import Lock
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.date import DateTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
from sqlalchemy import update

from app.application.services.saas import HeartbeatService, RegistrationStateError
from app.application.services.sources import ScanInProgressError, SourceService
from app.core.config import get_settings
from app.domain.ports.saas import SaaSClientError
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.documents import SqlAlchemyDocumentRepository
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.database.repositories.scans import SqlAlchemyScanRepository
from app.infrastructure.database.repositories.sources import SqlAlchemySourceRepository
from app.infrastructure.database.session import session_factory
from app.infrastructure.saas.client import HttpxPEKASaaSClient
from app.infrastructure.security.secrets import SecretEncryptionService
from app.plugins.registry import plugin_registry

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite datetimes, whose driver drops timezone information."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class HeartbeatInProgressError(Exception):
    pass


class ConnectorScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=UTC)
        self._heartbeat_lock = Lock()

    @property
    def running(self) -> bool:
        return self._scheduler.running

    @property
    def source_job_count(self) -> int:
        return sum(job.id.startswith("source:") for job in self._scheduler.get_jobs())

    @property
    def heartbeat_scheduled(self) -> bool:
        return self._scheduler.get_job("heartbeat") is not None

    def source_interval_seconds(self, source_id: UUID) -> float | None:
        job = self._scheduler.get_job(f"source:{source_id}")
        interval = getattr(job.trigger, "interval", None) if job else None
        return interval.total_seconds() if interval else None

    async def start(self) -> None:
        if self.running:
            return
        self._scheduler.start()
        logger.info("Connector scheduler started")
        async with session_factory() as session:
            await session.execute(update(SourceModel).values(scan_in_progress=False))
            await session.commit()
            sources = await SqlAlchemySourceRepository(session).list()
        for source in sources:
            await self.reconcile_source(source.id)
        async with session_factory() as session:
            product = await SqlAlchemyOperationsRepository(session).get_settings()
            if product.connector_id and product.encrypted_connector_secret:
                await self.schedule_heartbeat(2)

    async def shutdown(self) -> None:
        if self.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Connector scheduler stopped")

    async def reconcile_source(self, source_id: UUID) -> None:
        job_id = f"source:{source_id}"
        async with session_factory() as session:
            repository = SqlAlchemySourceRepository(session)
            source = await repository.get(source_id)
            if source is None or not source.enabled:
                self._scheduler.remove_job(job_id) if self._scheduler.get_job(job_id) else None
                if source:
                    await repository.set_next_scheduled_scan(source_id, None)
                logger.info("Source schedule removed", extra={"source_id": str(source_id)})
                return
            seconds = int(source.configuration.get("scan_interval_seconds", 300))
            job = self._scheduler.add_job(
                self._run_source_scan,
                IntervalTrigger(seconds=seconds, timezone=UTC),
                args=[source_id],
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(30, min(seconds, 300)),
            )
            await repository.set_next_scheduled_scan(source_id, job.next_run_time)
        logger.info(
            "Source scan job registered",
            extra={"source_id": str(source_id), "interval_seconds": seconds},
        )

    async def remove_source(self, source_id: UUID) -> None:
        job = self._scheduler.get_job(f"source:{source_id}")
        if job:
            self._scheduler.remove_job(job.id)
            logger.info("Source scan job removed", extra={"source_id": str(source_id)})

    async def _run_source_scan(self, source_id: UUID) -> None:
        logger.info("Scheduled source scan executing", extra={"source_id": str(source_id)})
        correlation_id = uuid4()
        async with session_factory() as session:
            operations = SqlAlchemyOperationsRepository(session)
            source_service = SourceService(
                SqlAlchemySourceRepository(session),
                SqlAlchemyDocumentRepository(session),
                SqlAlchemyScanRepository(session),
                plugin_registry,
            )
            try:
                await operations.record_event(
                    "source.scan_started",
                    "Scheduled source scan started",
                    target_type="source",
                    target_id=str(source_id),
                    details={
                        "trigger": "scheduled",
                        "correlation_id": str(correlation_id),
                    },
                    component="scheduler",
                )
                result = await source_service.scan(source_id, "scheduled", correlation_id)
                await operations.record_event(
                    "source.scan_completed",
                    "Scheduled source scan completed",
                    target_type="source",
                    target_id=str(source_id),
                    details={
                        "trigger": "scheduled",
                        "discovered": result.discovered_count,
                        "correlation_id": str(correlation_id),
                    },
                    component="scheduler",
                )
                logger.info("Scheduled source scan succeeded", extra={"source_id": str(source_id)})
            except ScanInProgressError:
                await SqlAlchemyScanRepository(session).skip(
                    source_id,
                    "scheduled",
                    correlation_id,
                    "Skipped because another scan was already in progress",
                )
                logger.warning(
                    "Scheduled source scan skipped because a scan is active",
                    extra={"source_id": str(source_id)},
                )
            except Exception as exc:
                await operations.record_event(
                    "source.scan_failed",
                    "Scheduled source scan failed",
                    target_type="source",
                    target_id=str(source_id),
                    details={
                        "trigger": "scheduled",
                        "error": str(exc),
                        "correlation_id": str(correlation_id),
                    },
                    level="ERROR",
                    component="scheduler",
                )
                logger.error("Scheduled source scan failed", extra={"source_id": str(source_id)})
            finally:
                job = self._scheduler.get_job(f"source:{source_id}")
                if job:
                    await SqlAlchemySourceRepository(session).set_next_scheduled_scan(
                        source_id, job.next_run_time
                    )

    async def schedule_heartbeat(self, delay_seconds: float = 5) -> None:
        run_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        self._scheduler.add_job(
            self._run_heartbeat,
            DateTrigger(run_date=run_at),
            id="heartbeat",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        async with session_factory() as session:
            await SqlAlchemyOperationsRepository(session).set_next_heartbeat(run_at, True)
        logger.info("Heartbeat job scheduled", extra={"next_run_at": run_at.isoformat()})

    async def remove_heartbeat(self) -> None:
        if self._scheduler.get_job("heartbeat"):
            self._scheduler.remove_job("heartbeat")
        async with session_factory() as session:
            await SqlAlchemyOperationsRepository(session).set_next_heartbeat(None, False)
        logger.info("Heartbeat job removed")

    async def retry_heartbeat_now(self) -> None:
        if self._heartbeat_lock.locked():
            raise HeartbeatInProgressError("A heartbeat attempt is already in progress")
        await self._run_heartbeat(force=True)

    async def _run_heartbeat(self, force: bool = False) -> None:
        if self._heartbeat_lock.locked():
            if force:
                raise HeartbeatInProgressError("A heartbeat attempt is already in progress")
            logger.warning("Heartbeat job skipped because an attempt is active")
            return
        async with self._heartbeat_lock:
            await self._execute_heartbeat()

    async def _execute_heartbeat(self) -> None:
        logger.info("Heartbeat job executing")
        delay: float | None = None
        correlation_id = str(uuid4())
        async with session_factory() as session:
            operations = SqlAlchemyOperationsRepository(session)
            settings = get_settings()
            previous = await operations.get_settings()
            if previous.next_heartbeat_at and datetime.now(UTC) > _as_utc(
                previous.next_heartbeat_at
            ) + timedelta(seconds=5):
                await operations.record_event(
                    "heartbeat.delayed",
                    "Heartbeat execution was delayed",
                    target_type="connector",
                    target_id=previous.connector_id,
                    details={"correlation_id": correlation_id},
                    level="WARNING",
                    component="heartbeat",
                )
            service = HeartbeatService(
                operations,
                HttpxPEKASaaSClient(
                    settings.saas_connect_timeout_seconds,
                    settings.saas_read_timeout_seconds,
                    settings.tls_verify,
                ),
                SecretEncryptionService(settings.encryption_key),
            )
            try:
                delivery = await service.send()
                delay = delivery.next_delay_seconds
                await operations.record_event(
                    "heartbeat.first_succeeded"
                    if delivery.first_heartbeat
                    else "heartbeat.succeeded",
                    "First connector heartbeat accepted"
                    if delivery.first_heartbeat
                    else "Connector heartbeat accepted",
                    target_type="connector",
                    target_id=previous.connector_id,
                    details={
                        "correlation_id": correlation_id,
                        "round_trip_ms": round(delivery.round_trip_ms, 2),
                        "connection_state": delivery.connection_state,
                    },
                    component="heartbeat",
                )
                if delivery.reconnected:
                    await operations.record_event(
                        "heartbeat.reconnected",
                        "Connector communication with PEKA SaaS recovered",
                        target_type="connector",
                        target_id=previous.connector_id,
                        details={"correlation_id": correlation_id},
                        component="heartbeat",
                    )
                logger.info("Heartbeat succeeded")
            except SaaSClientError as exc:
                product = await operations.get_settings()
                if product.next_heartbeat_at:
                    delay = max(
                        1,
                        (_as_utc(product.next_heartbeat_at) - datetime.now(UTC)).total_seconds(),
                    )
                await operations.record_event(
                    "heartbeat.failed",
                    "Connector heartbeat failed",
                    target_type="connector",
                    target_id=product.connector_id,
                    details={
                        "error": str(exc),
                        "kind": exc.kind,
                        "correlation_id": correlation_id,
                        "connection_state": product.saas_status,
                    },
                    level="ERROR",
                    component="heartbeat",
                )
                if exc.authentication_failure:
                    await operations.record_event(
                        "heartbeat.authentication_failed",
                        "PEKA SaaS rejected connector heartbeat credentials",
                        target_type="connector",
                        target_id=product.connector_id,
                        details={"correlation_id": correlation_id},
                        level="ERROR",
                        component="heartbeat",
                    )
                else:
                    await operations.record_event(
                        "heartbeat.retry_scheduled",
                        "Heartbeat retry scheduled after a temporary failure",
                        target_type="connector",
                        target_id=product.connector_id,
                        details={
                            "correlation_id": correlation_id,
                            "next_heartbeat_at": product.next_heartbeat_at,
                        },
                        level="WARNING",
                        component="heartbeat",
                    )
                if product.saas_status != previous.saas_status:
                    state_label = product.saas_status.replace("_", " ")
                    await operations.record_event(
                        f"heartbeat.{product.saas_status}",
                        f"Connector connection state changed to {state_label}",
                        target_type="connector",
                        target_id=product.connector_id,
                        details={"correlation_id": correlation_id},
                        level="WARNING",
                        component="heartbeat",
                    )
                logger.warning("Heartbeat failed: %s", exc)
            except RegistrationStateError:
                logger.info("Heartbeat skipped because connector is unregistered")
            except Exception:
                logger.exception("Heartbeat failed unexpectedly")
                delay = 300
        if delay is not None:
            await self.schedule_heartbeat(delay)


connector_scheduler = ConnectorScheduler()
