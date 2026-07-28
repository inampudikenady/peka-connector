import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.api.dependencies import (
    AuthServiceDep,
    CurrentUser,
    OperationsDep,
    SettingsDep,
)
from app.api.schemas import (
    BootstrapRequest,
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    Role,
    SetupStatusResponse,
    TokenResponse,
)
from app.application.services.auth import SessionTokens
from app.core.rate_limit import auth_rate_limiter

router = APIRouter()
REFRESH_COOKIE = "peka_refresh"
CSRF_COOKIE = "peka_csrf"


def _client_key(request: Request, operation: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{operation}:{host}"


def _set_session_cookies(
    response: Response, tokens: SessionTokens, settings: SettingsDep, request: Request
) -> None:
    max_age = settings.refresh_token_days * 86400
    secure = settings.cookie_secure or request.url.scheme == "https"
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth",
    )
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _clear_session_cookies(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/api/v1/auth",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _require_csrf(request: Request, header_token: str | None) -> tuple[str, str]:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if (
        not refresh_token
        or not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return refresh_token, cookie_token


@router.get("/setup-status", response_model=SetupStatusResponse)
async def setup_status(service: AuthServiceDep) -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=await service.setup_required())


@router.post("/bootstrap", response_model=CurrentUserResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap(
    request: BootstrapRequest,
    http_request: Request,
    service: AuthServiceDep,
    operations: OperationsDep,
) -> CurrentUserResponse:
    auth_rate_limiter.check(_client_key(http_request, "bootstrap"), limit=5, window_seconds=300)
    user = await service.create_first_administrator(request.username, request.password)
    await operations.record_event(
        "user.bootstrap_created",
        f"Initial local administrator {user.username} created",
        actor=user,
        target_type="user",
        target_id=str(user.id),
        component="authentication",
    )
    return CurrentUserResponse(id=user.id, username=user.username, role="administrator")


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    operations: OperationsDep,
) -> TokenResponse:
    auth_rate_limiter.check(_client_key(http_request, "login"), limit=10, window_seconds=60)
    tokens = await service.authenticate(request.username, request.password)
    await operations.record_event(
        "user.login",
        f"User {tokens.user.username} logged in",
        actor=tokens.user,
        component="authentication",
    )
    _set_session_cookies(response, tokens, settings, http_request)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> TokenResponse:
    refresh_token, csrf_token = _require_csrf(request, csrf_header)
    tokens = await service.refresh(refresh_token, csrf_token)
    _set_session_cookies(response, tokens, settings, request)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        _require_csrf(request, csrf_header)
    await service.logout(refresh_token)
    _clear_session_cookies(response, settings)


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUser) -> CurrentUserResponse:
    role: Role = "administrator" if user.role == "administrator" else "read_only"
    return CurrentUserResponse(id=user.id, username=user.username, role=role)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    user: CurrentUser,
    service: AuthServiceDep,
    operations: OperationsDep,
) -> None:
    await service.change_password(user, request.current_password, request.new_password)
    await operations.record_event(
        "user.password_changed",
        f"User {user.username} changed their password",
        actor=user,
        target_type="user",
        target_id=str(user.id),
        component="authentication",
    )
