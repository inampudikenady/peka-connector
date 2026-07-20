import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.api.v1.router import api_router
from app.application.services.auth import (
    AuthenticationService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    SetupUnavailableError,
)
from app.application.services.saas import SaaSRegistrationUnavailableError
from app.application.services.sources import (
    DisabledSourceError,
    SourceNotFoundError,
)
from app.application.services.users import (
    UsernameConflictError,
    UserNotFoundError,
    UserSafeguardError,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.database.repositories.sessions import SqlAlchemyRefreshTokenRepository
from app.infrastructure.database.repositories.users import SqlAlchemyUserRepository
from app.infrastructure.database.session import session_factory
from app.plugins.errors import PluginError
from app.plugins.filesystem import FilesystemDocumentSourcePlugin
from app.plugins.registry import plugin_registry

logger = logging.getLogger(__name__)
settings = get_settings()
settings.ensure_data_directories()
configure_logging(settings.log_level, settings.data_root / "logs")

if not plugin_registry.list():
    plugin_registry.register(FilesystemDocumentSourcePlugin(settings.sources_root))


class SPAStaticFiles(StaticFiles):
    """Serve compiled assets and fall back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code != status.HTTP_404_NOT_FOUND
                or path.startswith("api/")
                or PurePosixPath(path).suffix
            ):
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with session_factory() as session:
        created = await AuthenticationService(
            SqlAlchemyUserRepository(session),
            SqlAlchemyRefreshTokenRepository(session),
            settings,
        ).bootstrap_admin()
        if created:
            logger.warning(
                "Created unattended bootstrap administrator '%s'",
                settings.bootstrap_admin_username,
            )
    yield


app = FastAPI(
    title="PEKA Connector API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.include_router(api_router, prefix="/api/v1")


@app.middleware("http")
async def security_headers(request: Request, call_next: object) -> Response:
    response: Response = await call_next(request)  # type: ignore[operator]
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials(_: Request, exc: InvalidCredentialsError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(InvalidRefreshTokenError)
async def invalid_refresh(_: Request, exc: InvalidRefreshTokenError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)})


@app.exception_handler(SetupUnavailableError)
async def setup_unavailable(_: Request, exc: SetupUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(UserNotFoundError)
async def user_not_found(_: Request, exc: UserNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(UserSafeguardError)
async def user_safeguard(_: Request, exc: UserSafeguardError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(UsernameConflictError)
async def username_conflict(_: Request, exc: UsernameConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(SaaSRegistrationUnavailableError)
async def saas_unavailable(_: Request, exc: SaaSRegistrationUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.exception_handler(SourceNotFoundError)
async def source_not_found(_: Request, exc: SourceNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(DisabledSourceError)
async def disabled_source(_: Request, exc: DisabledSourceError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(PluginError)
async def plugin_error(_: Request, exc: PluginError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


@app.exception_handler(ValidationError)
async def plugin_configuration_error(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(include_url=False)},
    )


if settings.static_assets_dir.is_dir():
    app.mount(
        "/",
        SPAStaticFiles(directory=settings.static_assets_dir, html=True),
        name="frontend",
    )
else:
    logger.info(
        "Frontend assets not found at %s; API-only development mode enabled",
        settings.static_assets_dir,
    )
