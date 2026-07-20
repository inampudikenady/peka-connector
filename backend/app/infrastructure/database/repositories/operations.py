from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import sanitize
from app.domain.entities.source import UserAccount
from app.infrastructure.database.models.operations import (
    ApplicationLogModel,
    AuditEventModel,
    ProductSettingsModel,
)
from app.infrastructure.database.models.source import SourceModel


class SqlAlchemyOperationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(
        self,
        event_type: str,
        message: str,
        actor: UserAccount | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        level: str = "INFO",
        component: str = "application",
    ) -> None:
        safe_message = str(sanitize(message))[:1000]
        safe_details = sanitize(details or {})
        self._session.add(
            AuditEventModel(
                event_type=event_type,
                actor_user_id=actor.id if actor else None,
                actor_username=actor.username if actor else None,
                target_type=target_type,
                target_id=target_id,
                message=safe_message,
                details=safe_details,
            )
        )
        self._session.add(
            ApplicationLogModel(
                level=level,
                component=component,
                message=safe_message,
                context=safe_details,
            )
        )
        await self._session.commit()

    async def list_activity(self, limit: int = 100, offset: int = 0) -> list[AuditEventModel]:
        result = await self._session.scalars(
            select(AuditEventModel)
            .order_by(AuditEventModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def list_logs(
        self,
        level: str | None,
        component: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ApplicationLogModel], int]:
        filters = []
        if level:
            filters.append(ApplicationLogModel.level == level.upper())
        if component:
            filters.append(ApplicationLogModel.component == component)
        if search:
            escaped = search.replace("%", "\\%").replace("_", "\\_")
            filters.append(
                or_(
                    ApplicationLogModel.message.ilike(f"%{escaped}%", escape="\\"),
                    ApplicationLogModel.component.ilike(f"%{escaped}%", escape="\\"),
                )
            )
        total = int(
            await self._session.scalar(select(func.count(ApplicationLogModel.id)).where(*filters))
            or 0
        )
        result = await self._session.scalars(
            select(ApplicationLogModel)
            .where(*filters)
            .order_by(ApplicationLogModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), total

    async def get_settings(self) -> ProductSettingsModel:
        model = await self._session.get(ProductSettingsModel, 1)
        if model is None:
            model = ProductSettingsModel(id=1)
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
        return model

    async def update_settings(
        self,
        connector_display_name: str,
        environment_label: str,
        log_level: str,
        timezone: str,
        saas_url: str | None,
    ) -> ProductSettingsModel:
        model = await self.get_settings()
        model.connector_display_name = connector_display_name
        model.environment_label = environment_label
        model.log_level = log_level
        model.timezone = timezone
        model.saas_url = saas_url
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def overview(self) -> dict[str, Any]:
        settings = await self.get_settings()
        source_count = int(await self._session.scalar(select(func.count(SourceModel.id))) or 0)
        enabled_count = int(
            await self._session.scalar(
                select(func.count(SourceModel.id)).where(SourceModel.enabled.is_(True))
            )
            or 0
        )
        unhealthy_count = int(
            await self._session.scalar(
                select(func.count(SourceModel.id)).where(SourceModel.health_status == "unhealthy")
            )
            or 0
        )
        recent_failures = await self._session.scalars(
            select(AuditEventModel)
            .where(AuditEventModel.event_type.in_(["source.scan_failed", "heartbeat.failed"]))
            .order_by(AuditEventModel.created_at.desc())
            .limit(5)
        )
        return {
            "connector_status": "operational",
            "saas_status": settings.saas_status,
            "last_heartbeat_at": settings.last_heartbeat_at,
            "source_count": source_count,
            "enabled_source_count": enabled_count,
            "unhealthy_source_count": unhealthy_count,
            "recent_failures": list(recent_failures.all()),
        }
