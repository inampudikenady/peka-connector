from app.core.config import Settings
from app.domain.ports.repositories import UserRepository
from app.infrastructure.auth.passwords import hash_password, verify_password
from app.infrastructure.auth.tokens import create_access_token


class InvalidCredentialsError(Exception):
    pass


class AuthenticationService:
    def __init__(self, users: UserRepository, settings: Settings) -> None:
        self._users = users
        self._settings = settings

    async def authenticate(self, username: str, password: str) -> str:
        user = await self._users.get_by_username(username)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid username or password")
        return create_access_token(str(user.id), self._settings)

    async def bootstrap_admin(self) -> bool:
        if await self._users.count() > 0:
            return False
        password = self._settings.bootstrap_admin_password
        if password is None:
            raise RuntimeError(
                "PEKA_BOOTSTRAP_ADMIN_PASSWORD is required when no local user exists"
            )
        await self._users.create(
            self._settings.bootstrap_admin_username,
            hash_password(password.get_secret_value()),
        )
        return True
