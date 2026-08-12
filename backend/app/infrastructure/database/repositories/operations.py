from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integration_catalog import INTEGRATION_CATALOG
from app.core.logging import sanitize
from app.domain.entities.source import UserAccount
from app.domain.services.connector_status import derive_connection_state
from app.infrastructure.database.models.document import DocumentDeliveryJobModel, DocumentModel
from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.models.operations import (
    ApplicationLogModel,
    AuditEventModel,
    ProductSettingsModel,
)
from app.infrastructure.database.models.source import SourceModel

EXTERNAL_INTEGRATION_TYPES = frozenset(
    str(item["integration_type"])
    for item in INTEGRATION_CATALOG
    if "knowledge" not in item.get("provider_roles", ())
)


def summarize_external_integrations(
    integrations: list[ConnectorIntegrationModel],
) -> dict[str, int]:
    """Summarize enabled customer integrations using the shared catalog boundary."""
    enabled = [
        item
        for item in integrations
        if item.enabled and item.integration_type in EXTERNAL_INTEGRATION_TYPES
    ]
    healthy = sum(item.status == "healthy" for item in enabled)
    return {
        "enabled": len(enabled),
        "healthy": healthy,
        "attention": len(enabled) - healthy,
    }


class SqlAlchemyOperationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

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

    async def record_audit_event(
        self,
        event_type: str,
        message: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Persist UI/audit history without changing structured application logs."""
        self._session.add(
            AuditEventModel(
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                message=str(sanitize(message))[:1000],
                details=sanitize(details or {}),
            )
        )
        await self._session.commit()

    async def list_activity_page(
        self, page: int, page_size: int
    ) -> tuple[list[AuditEventModel], int]:
        human_event = or_(
            AuditEventModel.target_type.is_(None),
            AuditEventModel.target_type != "operational_tool_request",
        )
        total = int(
            await self._session.scalar(select(func.count(AuditEventModel.id)).where(human_event))
            or 0
        )
        result = await self._session.scalars(
            select(AuditEventModel)
            .where(human_event)
            .order_by(AuditEventModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), total

    async def list_operational_requests(
        self, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        events = list(
            (
                await self._session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.target_type == "operational_tool_request")
                    .order_by(AuditEventModel.created_at.desc())
                    .limit(5000)
                )
            ).all()
        )
        grouped: dict[str, dict[str, Any]] = {}
        for event in reversed(events):
            request_id = str(event.target_id or "")
            if not request_id:
                continue
            details = event.details or {}
            current = grouped.setdefault(
                request_id,
                {
                    "request_id": request_id,
                    "requested_at": event.created_at,
                    "completed_at": None,
                    "tool_name": str(details.get("tool_name") or "unknown"),
                    "integration": str(details.get("integration") or "Connector"),
                    "target_asset": details.get("target_asset"),
                    "status": "running",
                    "duration_ms": None,
                    "result_summary": None,
                    "error_code": None,
                },
            )
            if event.event_type == "operational_request.started":
                current["requested_at"] = event.created_at
                current["status"] = "running"
            elif event.event_type in {
                "operational_request.succeeded",
                "operational_request.failed",
            }:
                current.update(
                    {
                        "completed_at": event.created_at,
                        "status": "succeeded"
                        if event.event_type.endswith("succeeded")
                        else "failed",
                        "duration_ms": details.get("duration_ms"),
                        "result_summary": details.get("result_summary"),
                        "error_code": details.get("error_code"),
                    }
                )
        rows = sorted(grouped.values(), key=lambda item: item["requested_at"], reverse=True)
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    async def activity_overview(self) -> dict[str, Any]:
        requests, _ = await self.list_operational_requests(1, 5000)
        now = datetime.now(UTC)
        warning_events = list(
            (
                await self._session.scalars(
                    select(AuditEventModel)
                    .where(
                        or_(
                            AuditEventModel.event_type.contains("failed"),
                            AuditEventModel.event_type.contains("warning"),
                            AuditEventModel.event_type.contains("deferred"),
                        )
                    )
                    .order_by(AuditEventModel.created_at.desc())
                    .limit(5)
                )
            ).all()
        )
        last_sync = await self._session.scalar(
            select(func.max(AuditEventModel.created_at)).where(
                AuditEventModel.event_type.contains("sync"),
                AuditEventModel.event_type.contains("completed"),
            )
        )
        settings = await self.get_settings()
        return {
            "pending_requests": sum(item["status"] == "pending" for item in requests),
            "running_requests": sum(item["status"] == "running" for item in requests),
            "failed_requests": sum(item["status"] == "failed" for item in requests),
            "successful_requests_24h": sum(
                item["status"] == "succeeded"
                and item["completed_at"] is not None
                and item["completed_at"] >= now - timedelta(hours=24)
                for item in requests
            ),
            "recent_warnings_or_failures": warning_events,
            "last_heartbeat_at": settings.last_heartbeat_at,
            "last_completed_sync_at": last_sync,
        }

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

    async def scan_log_references(self, correlation_id: str) -> list[str]:
        result = await self._session.scalars(
            select(ApplicationLogModel).order_by(ApplicationLogModel.created_at.desc()).limit(1000)
        )
        return [
            str(item.id)
            for item in result.all()
            if str(item.context.get("correlation_id", "")) == correlation_id
        ]

    async def get_settings(self) -> ProductSettingsModel:
        model = await self._session.get(ProductSettingsModel, 1)
        if model is None:
            model = ProductSettingsModel(id=1)
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
        if model.instance_id is None:
            model.instance_id = str(uuid4())
            await self._session.commit()
            await self._session.refresh(model)
        derived = derive_connection_state(
            has_credentials=bool(model.connector_id and model.encrypted_connector_secret),
            current_state=model.saas_status,
            last_success_at=model.last_heartbeat_at,
            heartbeat_interval_seconds=model.heartbeat_interval_seconds,
            consecutive_failures=model.heartbeat_failure_count,
        ).value
        if model.saas_status != derived:
            model.saas_status = derived
            await self._session.commit()
            await self._session.refresh(model)
        return model

    async def refresh_settings(self) -> ProductSettingsModel:
        """Discard identity-map state after a scheduler-owned transaction."""
        self._session.expire_all()
        return await self.get_settings()

    async def set_encryption_key_check(self, encrypted_check: str) -> None:
        model = await self.get_settings()
        model.encryption_key_check = encrypted_check
        await self._session.commit()

    async def begin_registration(
        self,
        saas_url: str | None = None,
    ) -> ProductSettingsModel:
        model = await self.get_settings()
        if saas_url is not None:
            model.saas_url = saas_url
        model.saas_status = "registering"
        model.last_heartbeat_error = None
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def registration_failed(self, error: str, previous_state: str) -> None:
        model = await self.get_settings()
        model.saas_status = previous_state
        model.last_heartbeat_error = str(sanitize(error))[:2000]
        await self._session.commit()

    async def complete_registration(
        self,
        connector_id: str,
        tenant_id: str,
        encrypted_secret: str,
        heartbeat_interval_seconds: int,
        registered_at: datetime,
        saas_url: str,
    ) -> ProductSettingsModel:
        model = await self.get_settings()
        model.connector_id = connector_id
        model.tenant_id = tenant_id
        model.encrypted_connector_secret = encrypted_secret
        model.heartbeat_interval_seconds = heartbeat_interval_seconds
        model.registered_at = registered_at
        model.saas_url = saas_url
        model.saas_status = "awaiting_first_heartbeat"
        model.last_heartbeat_attempt_at = None
        model.last_heartbeat_at = None
        model.last_heartbeat_failed_at = None
        model.last_heartbeat_status = None
        model.heartbeat_round_trip_ms = None
        model.last_saas_server_time = None
        model.last_heartbeat_error = None
        model.heartbeat_failure_count = 0
        model.heartbeat_job_enabled = True
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def unregister_local(self) -> ProductSettingsModel:
        model = await self.get_settings()
        model.connector_id = None
        model.tenant_id = None
        model.encrypted_connector_secret = None
        model.registered_at = None
        model.saas_status = "unregistered"
        model.last_heartbeat_attempt_at = None
        model.last_heartbeat_at = None
        model.last_heartbeat_failed_at = None
        model.next_heartbeat_at = None
        model.last_heartbeat_status = None
        model.last_heartbeat_error = None
        model.heartbeat_failure_count = 0
        model.heartbeat_round_trip_ms = None
        model.last_saas_server_time = None
        model.heartbeat_job_enabled = False
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def heartbeat_attempted(self) -> None:
        model = await self.get_settings()
        model.last_heartbeat_attempt_at = datetime.now(UTC)
        await self._session.commit()

    async def heartbeat_succeeded(
        self,
        next_at: datetime,
        interval_seconds: int,
        round_trip_ms: float,
        server_time: datetime,
    ) -> str:
        model = await self.get_settings()
        now = datetime.now(UTC)
        model.last_heartbeat_at = now
        model.next_heartbeat_at = next_at
        model.last_heartbeat_status = "success"
        model.last_heartbeat_error = None
        model.heartbeat_failure_count = 0
        model.heartbeat_interval_seconds = interval_seconds
        model.heartbeat_round_trip_ms = round_trip_ms
        model.last_saas_server_time = server_time
        model.saas_status = "connected"
        await self._session.commit()
        return model.saas_status

    async def heartbeat_failed(
        self, error: str, authentication_failure: bool, next_at: datetime
    ) -> int:
        model = await self.get_settings()
        model.heartbeat_failure_count += 1
        model.last_heartbeat_failed_at = datetime.now(UTC)
        model.next_heartbeat_at = next_at
        model.last_heartbeat_status = "failed"
        model.last_heartbeat_error = str(sanitize(error))[:2000]
        state_hint = "authentication_failed" if authentication_failure else model.saas_status
        model.saas_status = derive_connection_state(
            has_credentials=True,
            current_state=state_hint,
            last_success_at=model.last_heartbeat_at,
            heartbeat_interval_seconds=model.heartbeat_interval_seconds,
            consecutive_failures=model.heartbeat_failure_count,
        ).value
        await self._session.commit()
        return model.heartbeat_failure_count

    async def set_next_heartbeat(self, next_at: datetime | None, enabled: bool) -> None:
        model = await self.get_settings()
        model.next_heartbeat_at = next_at
        model.heartbeat_job_enabled = enabled
        await self._session.commit()

    async def source_summary(self) -> dict[str, int]:
        rows = list((await self._session.scalars(select(SourceModel))).all())
        return {
            "total": len(rows),
            "healthy": sum(source.enabled and source.health_status == "healthy" for source in rows),
            "unhealthy": sum(
                source.enabled and source.health_status != "healthy" for source in rows
            ),
            "disabled": sum(not source.enabled for source in rows),
        }

    async def update_settings(
        self,
        connector_display_name: str,
        environment_label: str,
        log_level: str,
    ) -> ProductSettingsModel:
        model = await self.get_settings()
        model.connector_display_name = connector_display_name
        model.environment_label = environment_label
        model.log_level = log_level
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
        recent_events = await self._session.scalars(
            select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(12)
        )
        connector_id = str(settings.connector_id or settings.instance_id or "local")
        integrations = list(
            (
                await self._session.scalars(
                    select(ConnectorIntegrationModel).where(
                        ConnectorIntegrationModel.connector_id == connector_id,
                        ConnectorIntegrationModel.integration_type.in_(EXTERNAL_INTEGRATION_TYPES),
                    )
                )
            ).all()
        )
        integration_summary = summarize_external_integrations(integrations)
        external_integration_ids = [str(item.id) for item in integrations]
        recent_integration_failures = await self._session.scalars(
            select(AuditEventModel)
            .where(
                AuditEventModel.target_type == "integration",
                AuditEventModel.event_type.contains("failed"),
                AuditEventModel.target_id.in_(external_integration_ids),
            )
            .order_by(AuditEventModel.created_at.desc())
            .limit(5)
        )
        managed_source = await self._session.scalar(
            select(SourceModel).where(SourceModel.system_managed.is_(True)).limit(1)
        )
        documents = list(
            (
                await self._session.scalars(
                    select(DocumentModel)
                    .join(SourceModel, SourceModel.id == DocumentModel.source_id)
                    .where(SourceModel.system_managed.is_(True))
                )
            ).all()
        )
        last_delivery = await self._session.scalar(
            select(func.max(DocumentDeliveryJobModel.completed_at)).where(
                DocumentDeliveryJobModel.state == "SUCCEEDED"
            )
        )
        return {
            "connector_status": "operational",
            "saas_status": settings.saas_status,
            "connector_display_name": settings.connector_display_name,
            "instance_id": settings.instance_id,
            "connector_id": settings.connector_id,
            "tenant_id": settings.tenant_id,
            "last_heartbeat_at": settings.last_heartbeat_at,
            "next_heartbeat_at": settings.next_heartbeat_at,
            "heartbeat_failure_count": settings.heartbeat_failure_count,
            "last_heartbeat_error": settings.last_heartbeat_error,
            "saas_url": settings.saas_url,
            "registered_at": settings.registered_at,
            "last_heartbeat_attempt_at": settings.last_heartbeat_attempt_at,
            "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
            "heartbeat_round_trip_ms": settings.heartbeat_round_trip_ms,
            "source_count": source_count,
            "enabled_source_count": enabled_count,
            "unhealthy_source_count": unhealthy_count,
            "recent_events": list(recent_events.all()),
            "enabled_integration_count": integration_summary["enabled"],
            "healthy_integration_count": integration_summary["healthy"],
            "attention_integration_count": integration_summary["attention"],
            "recent_integration_failures": list(recent_integration_failures.all()),
            "document_total": len(documents),
            "document_queued": sum(
                item.delivery_status in {"PENDING", "QUEUED", "PENDING_DELETE"}
                for item in documents
            ),
            "document_uploading": sum(item.delivery_status == "UPLOADING" for item in documents),
            "document_uploaded": sum(item.delivery_status == "UPLOADED" for item in documents),
            "document_failed": sum(item.delivery_status == "FAILED" for item in documents),
            "document_unsupported": sum(item.local_status == "UNSUPPORTED" for item in documents),
            "last_document_delivery_at": last_delivery,
            "document_endpoint_status": (
                "available"
                if last_delivery
                else "pending"
                if settings.connector_id
                else "unavailable"
            ),
            "document_source_health": (
                managed_source.health_status if managed_source else "missing"
            ),
            "document_source_last_scan_at": (
                managed_source.last_scan_at if managed_source else None
            ),
            "document_source_next_scan_at": (
                managed_source.next_scheduled_scan_at if managed_source else None
            ),
        }
