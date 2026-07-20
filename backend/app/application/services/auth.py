from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.validation import validate_password, validate_username
from app.domain.entities.source import UserAccount
from app.domain.ports.repositories import RefreshTokenRepository, UserRepository
from app.infrastructure.auth.passwords import hash_password, verify_password
from app.infrastructure.auth.tokens import create_access_token, generate_opaque_token, hash_token


class InvalidCredentialsError(Exception):
    pass


class SetupUnavailableError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    expires_in: int
    user: UserAccount


class AuthenticationService:
    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        settings: Settings,
    ) -> None:
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._settings = settings

    async def setup_required(self) -> bool:
        return await self._users.count() == 0

    async def create_first_administrator(self, username: str, password: str) -> UserAccount:
        if not await self.setup_required():
            raise SetupUnavailableError("Initial administrator setup is already complete")
        clean_username = validate_username(username)
        validate_password(password, clean_username)
        return await self._users.create(
            clean_username, hash_password(password), role="administrator"
        )

    async def authenticate(self, username: str, password: str) -> SessionTokens:
        user = await self._users.get_by_username(username.strip())
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid username or password")
        await self._users.record_login(user.id)
        return await self._create_session(user)

    async def refresh(self, refresh_token: str, csrf_token: str) -> SessionTokens:
        user_id = await self._refresh_tokens.get_valid_user_id(
            hash_token(refresh_token), hash_token(csrf_token)
        )
        if user_id is None:
            raise InvalidRefreshTokenError("Refresh session is invalid or expired")
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError("Refresh session is invalid or expired")
        await self._refresh_tokens.revoke(hash_token(refresh_token))
        return await self._create_session(user)

    async def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            await self._refresh_tokens.revoke(hash_token(refresh_token))

    async def change_password(
        self, user: UserAccount, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Current password is incorrect")
        validate_password(new_password, user.username)
        if verify_password(new_password, user.password_hash):
            raise ValueError("New password must be different from the current password")
        await self._users.update_password(user.id, hash_password(new_password))
        await self._refresh_tokens.revoke_for_user(user.id)

    async def bootstrap_admin(self) -> bool:
        username = self._settings.bootstrap_admin_username
        password = self._settings.bootstrap_admin_password
        if username is None or password is None or not await self.setup_required():
            return False
        await self.create_first_administrator(username, password.get_secret_value())
        return True

    async def _create_session(self, user: UserAccount) -> SessionTokens:
        refresh_token = generate_opaque_token()
        csrf_token = generate_opaque_token()
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_days)
        await self._refresh_tokens.create(
            user.id,
            hash_token(refresh_token),
            hash_token(csrf_token),
            expires_at,
        )
        return SessionTokens(
            access_token=create_access_token(str(user.id), self._settings),
            refresh_token=refresh_token,
            csrf_token=csrf_token,
            expires_in=self._settings.access_token_minutes * 60,
            user=user,
        )
