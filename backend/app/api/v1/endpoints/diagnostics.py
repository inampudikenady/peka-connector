import io
import json
import os
import platform
import sys
import zipfile
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select, text

from app.api.dependencies import CurrentUser, OperationsDep, SessionDep, SettingsDep
from app.api.schemas import DiagnosticCheck, DiagnosticsResponse
from app.core.logging import sanitize
from app.infrastructure.database.models.source import SourceModel

router = APIRouter()


async def _migration_revision(session: SessionDep) -> str | None:
    try:
        return await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
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
    mount_ok = settings.sources_root.is_dir() and os.access(settings.sources_root, os.R_OK)
    checks.append(
        DiagnosticCheck(
            name="Source mount",
            status="healthy" if mount_ok else "warning",
            detail=f"{settings.sources_root} is {'readable' if mount_ok else 'not available'}",
        )
    )
    checks.append(
        DiagnosticCheck(
            name="PEKA SaaS connectivity",
            status="unavailable",
            detail="SaaS registration API is not configured in this release",
        )
    )
    return checks


@router.get("", response_model=DiagnosticsResponse)
async def diagnostics(
    _: CurrentUser, session: SessionDep, settings: SettingsDep
) -> DiagnosticsResponse:
    return DiagnosticsResponse(
        version="0.1.0",
        build=os.getenv("PEKA_BUILD_ID", "development"),
        python_version=platform.python_version(),
        platform=platform.platform(),
        migration_revision=await _migration_revision(session),
        checks=await _checks(session, settings),
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
        "timezone": product_settings.timezone,
        "saas_status": product_settings.saas_status,
        "saas_url": product_settings.saas_url,
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
        "sources_root": str(settings.sources_root),
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
