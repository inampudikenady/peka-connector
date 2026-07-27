import io
import json
import os
import platform
import shutil
import sys
import zipfile
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Response
from sqlalchemy import select, text

from app.api.dependencies import CurrentUser, OperationsDep, SessionDep, SettingsDep
from app.api.schemas import DiagnosticCheck, DiagnosticsResponse
from app.application.services.documents import DocumentDeliveryWorker
from app.core.logging import sanitize
from app.core.version import CONNECTOR_VERSION
from app.infrastructure.database.models.document import DocumentDeliveryJobModel
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.saas.client import HttpxPEKASaaSClient
from app.infrastructure.scheduling import connector_scheduler
from app.infrastructure.security.secrets import SecretEncryptionService

router = APIRouter()


async def _migration_revision(session: SessionDep) -> str | None:
    try:
        return cast(
            str | None,
            await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1")),
        )
    except Exception:
        return None


async def _checks(session: SessionDep, settings: SettingsDep) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    try:
        await session.scalar(text("SELECT 1"))
        checks.append(
            DiagnosticCheck(name="Database", status="healthy", detail="SQLite query succeeded")
        )
    except Exception as exc:
        checks.append(DiagnosticCheck(name="Database", status="unhealthy", detail=str(exc)[:200]))
    for name in ("state", "config", "logs", "spool"):
        path = settings.data_root / name
        writable = path.is_dir() and os.access(path, os.W_OK | os.X_OK)
        checks.append(
            DiagnosticCheck(
                name=f"Data directory: {name}",
                status="healthy" if writable else "unhealthy",
                detail=f"{path} is {'writable' if writable else 'not writable'}",
            )
        )
    mount_ok = settings.filesystem_sources_root.is_dir() and os.access(
        settings.filesystem_sources_root, os.R_OK
    )
    checks.append(
        DiagnosticCheck(
            name="Source mount",
            status="healthy" if mount_ok else "warning",
            detail=(
                f"{settings.filesystem_sources_root} is "
                f"{'readable' if mount_ok else 'not available'}"
            ),
        )
    )
    documents_root = settings.managed_documents_root
    documents_readable = documents_root.is_dir() and os.access(documents_root, os.R_OK)
    documents_writable = documents_root.is_dir() and os.access(documents_root, os.W_OK)
    spool = settings.data_root / "spool"
    successful_delivery = await session.scalar(
        select(DocumentDeliveryJobModel.id)
        .where(DocumentDeliveryJobModel.state == "SUCCEEDED")
        .limit(1)
    )
    managed_sources = list(
        (
            await session.scalars(select(SourceModel).where(SourceModel.system_managed.is_(True)))
        ).all()
    )
    managed_source = managed_sources[0] if len(managed_sources) == 1 else None
    managed_path_correct = bool(
        managed_source
        and managed_source.plugin_type == "filesystem_documents"
        and managed_source.configuration.get("path") == "/data/sources/documents"
    )
    checks.extend(
        [
            DiagnosticCheck(
                name="Managed document source",
                status="healthy" if managed_source else "unhealthy",
                detail=(
                    "Exactly one managed document source exists"
                    if managed_source
                    else f"Expected one managed document source; found {len(managed_sources)}"
                ),
            ),
            DiagnosticCheck(
                name="Managed source path",
                status="healthy" if managed_path_correct else "unhealthy",
                detail=(
                    "Managed source path is /data/sources/documents"
                    if managed_path_correct
                    else "Managed source path or type is invalid"
                ),
            ),
            DiagnosticCheck(
                name="Managed documents directory",
                status="healthy" if documents_readable and documents_writable else "unhealthy",
                detail=(
                    "Directory is readable and writable"
                    if documents_readable and documents_writable
                    else "Directory is not readable and writable"
                ),
            ),
            DiagnosticCheck(
                name="Managed source scheduler",
                status=(
                    "healthy"
                    if managed_source
                    and (
                        not managed_source.enabled
                        or connector_scheduler.document_reconciliation_scheduled
                    )
                    else "unhealthy"
                ),
                detail=(
                    "Active"
                    if connector_scheduler.document_reconciliation_scheduled
                    else "Not scheduled because the source is disabled"
                    if managed_source and not managed_source.enabled
                    else "Not scheduled"
                ),
            ),
            DiagnosticCheck(
                name="Document spool",
                status="healthy" if spool.is_dir() and os.access(spool, os.W_OK) else "unhealthy",
                detail="Spool is writable"
                if spool.is_dir() and os.access(spool, os.W_OK)
                else "Spool is unavailable",
            ),
            DiagnosticCheck(
                name="Document delivery API",
                status="healthy" if successful_delivery else "unavailable",
                detail=(
                    "At least one document delivery was acknowledged"
                    if successful_delivery
                    else "Endpoint availability is confirmed only by an acknowledged delivery"
                ),
            ),
            DiagnosticCheck(
                name="Available data storage",
                status="healthy",
                detail=f"{shutil.disk_usage(settings.data_root).free} bytes free",
            ),
        ]
    )
    product = await SqlAlchemyOperationsRepository(session).get_settings()
    endpoint_hostname = (
        urlsplit(product.saas_url).hostname if product.saas_url else "not configured"
    )
    scheduler_detail = (
        f"Running: {connector_scheduler.running}; "
        f"source jobs: {connector_scheduler.source_job_count}"
    )
    heartbeat_detail = (
        f"Scheduled: {connector_scheduler.heartbeat_scheduled}; "
        f"last success: {product.last_heartbeat_at or 'none'}"
    )
    checks.append(
        DiagnosticCheck(
            name="PEKA connectivity",
            status="warning"
            if product.saas_status in {"degraded", "disconnected", "authentication_failed"}
            else "unavailable"
            if product.saas_status in {"unregistered", "not_registered"}
            else "healthy",
            detail=f"Registration state: {product.saas_status}; endpoint: {endpoint_hostname}",
        )
    )
    checks.extend(
        [
            DiagnosticCheck(
                name="Scheduler",
                status="healthy" if connector_scheduler.running else "unhealthy",
                detail=scheduler_detail,
            ),
            DiagnosticCheck(
                name="Heartbeat scheduler",
                status="healthy" if connector_scheduler.heartbeat_scheduled else "unavailable",
                detail=heartbeat_detail,
            ),
            DiagnosticCheck(
                name="Secret encryption",
                status="healthy"
                if SecretEncryptionService(settings.encryption_key).ready
                else "unhealthy",
                detail="Deployment encryption key is available"
                if settings.encryption_key
                else "Deployment encryption key is unavailable",
            ),
        ]
    )
    return checks


@router.get("", response_model=DiagnosticsResponse)
async def diagnostics(
    _: CurrentUser, session: SessionDep, settings: SettingsDep
) -> DiagnosticsResponse:
    product = await SqlAlchemyOperationsRepository(session).get_settings()
    registration_state = (
        "registering"
        if product.saas_status == "registering"
        else "registered"
        if product.connector_id and product.encrypted_connector_secret
        else "unregistered"
    )
    worker = DocumentDeliveryWorker(
        session,
        settings,
        HttpxPEKASaaSClient(
            settings.saas_connect_timeout_seconds,
            settings.saas_read_timeout_seconds,
            settings.tls_verify,
        ),
        SecretEncryptionService(settings.encryption_key),
    )
    pending_jobs, stale_jobs = await worker.counts()
    return DiagnosticsResponse(
        version=CONNECTOR_VERSION,
        build=os.getenv("PEKA_BUILD_ID", "development"),
        python_version=platform.python_version(),
        platform=platform.platform(),
        migration_revision=await _migration_revision(session),
        checks=await _checks(session, settings),
        instance_id=str(product.instance_id),
        registration_state=registration_state,
        connection_state=product.saas_status,
        saas_hostname=urlsplit(product.saas_url).hostname if product.saas_url else None,
        last_heartbeat_attempt_at=product.last_heartbeat_attempt_at,
        last_successful_heartbeat_at=product.last_heartbeat_at,
        next_heartbeat_at=product.next_heartbeat_at,
        heartbeat_interval_seconds=product.heartbeat_interval_seconds,
        consecutive_failures=product.heartbeat_failure_count,
        heartbeat_round_trip_ms=product.heartbeat_round_trip_ms,
        scheduler_running=connector_scheduler.running,
        heartbeat_job_scheduled=connector_scheduler.heartbeat_scheduled,
        source_scheduler_job_count=connector_scheduler.source_job_count,
        document_worker_running=connector_scheduler.document_worker_running,
        document_reconciliation_scheduled=connector_scheduler.document_reconciliation_scheduled,
        pending_document_jobs=pending_jobs,
        stale_document_jobs=stale_jobs,
    )


@router.get("/bundle")
async def diagnostics_bundle(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    operations: OperationsDep,
) -> Response:
    diagnostic = await diagnostics(user, session, settings)
    product_settings = await operations.get_settings()
    sources = list((await session.scalars(select(SourceModel).order_by(SourceModel.name))).all())
    logs, _total = await operations.list_logs(None, None, None, 1, 500)
    safe_config: dict[str, Any] = {
        "connector_display_name": product_settings.connector_display_name,
        "environment_label": product_settings.environment_label,
        "log_level": product_settings.log_level,
        "saas_status": product_settings.saas_status,
        "saas_url": product_settings.saas_url,
        "instance_id": product_settings.instance_id,
        "last_heartbeat_at": product_settings.last_heartbeat_at,
        "heartbeat_failure_count": product_settings.heartbeat_failure_count,
        "heartbeat_round_trip_ms": product_settings.heartbeat_round_trip_ms,
        "last_saas_server_time": product_settings.last_saas_server_time,
        "last_heartbeat_attempt_at": product_settings.last_heartbeat_attempt_at,
        "last_heartbeat_failed_at": product_settings.last_heartbeat_failed_at,
        "next_heartbeat_at": product_settings.next_heartbeat_at,
    }
    source_health = [
        {
            "id": str(source.id),
            "name": source.name,
            "plugin_type": source.plugin_type,
            "enabled": source.enabled,
            "health_status": source.health_status,
            "last_success_at": source.last_success_at,
            "last_error": source.last_error,
            "configuration": sanitize(source.configuration),
        }
        for source in sources
    ]
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "data_root": str(settings.data_root),
        "sources_root": str(settings.filesystem_sources_root),
        "environment": settings.environment,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        entries = {
            "diagnostics.json": diagnostic.model_dump(mode="json"),
            "configuration.json": sanitize(safe_config),
            "source-health.json": sanitize(source_health),
            "environment.json": environment,
            "recent-logs.json": [
                {
                    "level": log.level,
                    "component": log.component,
                    "message": log.message,
                    "context": sanitize(log.context),
                    "created_at": log.created_at,
                }
                for log in logs
            ],
        }
        for filename, content in entries.items():
            archive.writestr(filename, json.dumps(content, default=str, indent=2))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=peka-diagnostics.zip"},
    )
