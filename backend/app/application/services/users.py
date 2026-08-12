from collections.abc import Sequence
from uuid import UUID

from app.core.validation import validate_password, validate_username
from app.domain.entities.source import UserAccount
from app.domain.ports.repositories import RefreshTokenRepository, UserRepository
from app.infrastructure.auth.passwords import hash_password

VALID_ROLES = frozenset({"administrator", "read_only"})


class UserNotFoundError(Exception):
    pass


class UserSafeguardError(Exception):
    pass


class UsernameConflictError(Exception):
    pass


class UserService:
    def __init__(self, users: UserRepository, refresh_tokens: RefreshTokenRepository) -> None:
        self._users = users
        self._refresh_tokens = refresh_tokens

    async def list_users(self) -> Sequence[UserAccount]:
        return await self._users.list()

    async def create_user(
        self, username: str, password: str, role: str, active: bool = True
    ) -> UserAccount:
        clean_username = validate_username(username)
        validate_password(password, clean_username)
        if role not in VALID_ROLES:
            raise ValueError("Role must be administrator or read_only")
        if await self._users.get_by_username(clean_username):
            raise UsernameConflictError("Username already exists")
        return await self._users.create(clean_username, hash_password(password), role, active)

    async def set_active(
        self, user_id: UUID, active: bool, actor_id: UUID | None = None
    ) -> UserAccount:
        user = await self._require(user_id)
        if not active and actor_id is not None and user.id == actor_id:
            raise UserSafeguardError("You cannot disable your own account")
        if (
            not active
            and user.is_active
            and user.role == "administrator"
            and await self._users.count_active_administrators() <= 1
        ):
            raise UserSafeguardError("The last active administrator cannot be disabled")
        updated = await self._users.set_active(user_id, active)
        if not active:
            await self._refresh_tokens.revoke_for_user(user_id)
        return updated

    async def reset_password(self, user_id: UUID, password: str) -> None:
        user = await self._require(user_id)
        validate_password(password, user.username)
        await self._users.update_password(user_id, hash_password(password))
        await self._refresh_tokens.revoke_for_user(user_id)

    async def delete_user(self, user_id: UUID, actor_id: UUID) -> None:
        user = await self._require(user_id)
        if user.id == actor_id:
            raise UserSafeguardError("You cannot delete your own account")
        if (
            user.is_active
            and user.role == "administrator"
            and await self._users.count_active_administrators() <= 1
        ):
            raise UserSafeguardError("The last active administrator cannot be deleted")
        await self._users.delete(user_id)

    async def _require(self, user_id: UUID) -> UserAccount:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User not found: {user_id}")
        return user
