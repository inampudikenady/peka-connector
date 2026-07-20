from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.source import ScanRecord
from app.infrastructure.database.models.scan import ScanHistoryModel


class SqlAlchemyScanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self, source_id: UUID, trigger: str = "manual", correlation_id: UUID | None = None
    ) -> ScanRecord:
        model = ScanHistoryModel(
            source_id=source_id,
            status="running",
            trigger=trigger,
            **({"correlation_id": correlation_id} if correlation_id else {}),
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def complete(
        self, scan_id: UUID, counts: dict[str, int], discovered_count: int
    ) -> ScanRecord:
        model = await self._require(scan_id)
        model.status = "completed"
        model.completed_at = datetime.now(UTC)
        model.discovered_count = discovered_count
        model.added_count = counts["added"]
        model.changed_count = counts["changed"]
        model.unchanged_count = counts["unchanged"]
        model.missing_count = counts["missing"]
        model.failed_count = counts["failed"]
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def fail(self, scan_id: UUID, error: str) -> ScanRecord:
        model = await self._require(scan_id)
        model.status = "failed"
        model.completed_at = datetime.now(UTC)
        model.failed_count = 1
        model.error = error[:2000]
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_for_source(self, source_id: UUID, limit: int = 50) -> Sequence[ScanRecord]:
        result = await self._session.scalars(
            select(ScanHistoryModel)
            .where(ScanHistoryModel.source_id == source_id)
            .order_by(ScanHistoryModel.started_at.desc())
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.all()]

    async def list_page_for_source(
        self, source_id: UUID, page: int, page_size: int
    ) -> tuple[Sequence[ScanRecord], int]:
        total = int(
            await self._session.scalar(
                select(func.count(ScanHistoryModel.id)).where(
                    ScanHistoryModel.source_id == source_id
                )
            )
            or 0
        )
        result = await self._session.scalars(
            select(ScanHistoryModel)
            .where(ScanHistoryModel.source_id == source_id)
            .order_by(ScanHistoryModel.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_entity(model) for model in result.all()], total

    async def get(self, scan_id: UUID) -> ScanRecord | None:
        model = await self._session.get(ScanHistoryModel, scan_id)
        return self._to_entity(model) if model else None

    async def skip(
        self, source_id: UUID, trigger: str, correlation_id: UUID, reason: str
    ) -> ScanRecord:
        now = datetime.now(UTC)
        model = ScanHistoryModel(
            source_id=source_id,
            status="skipped",
            trigger=trigger,
            correlation_id=correlation_id,
            started_at=now,
            completed_at=now,
            error=reason[:2000],
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def _require(self, scan_id: UUID) -> ScanHistoryModel:
        model = await self._session.get(ScanHistoryModel, scan_id)
        if model is None:
            raise LookupError(f"Scan not found: {scan_id}")
        return model

    @staticmethod
    def _to_entity(model: ScanHistoryModel) -> ScanRecord:
        return ScanRecord(
            id=model.id,
            source_id=model.source_id,
            status=model.status,
            trigger=model.trigger,
            started_at=model.started_at,
            completed_at=model.completed_at,
            discovered_count=model.discovered_count,
            added_count=model.added_count,
            changed_count=model.changed_count,
            unchanged_count=model.unchanged_count,
            missing_count=model.missing_count,
            failed_count=model.failed_count,
            error=model.error,
            correlation_id=model.correlation_id,
        )
