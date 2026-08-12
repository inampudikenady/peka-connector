from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.source import UserAccount
from app.infrastructure.database.models.user import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> UserAccount | None:
        model = await self._session.scalar(select(UserModel).where(UserModel.username == username))
        return self._to_entity(model) if model else None

    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        model = await self._session.get(UserModel, user_id)
        return self._to_entity(model) if model else None

    async def count(self) -> int:
        return int(await self._session.scalar(select(func.count(UserModel.id))) or 0)

    async def count_active_administrators(self) -> int:
        query = select(func.count(UserModel.id)).where(
            UserModel.is_active.is_(True), UserModel.role == "administrator"
        )
        return int(await self._session.scalar(query) or 0)

    async def list(self) -> list[UserAccount]:
        result = await self._session.scalars(select(UserModel).order_by(UserModel.username))
        return [self._to_entity(model) for model in result.all()]

    async def create(
        self,
        username: str,
        password_hash: str,
        role: str = "administrator",
        active: bool = True,
    ) -> UserAccount:
        user = UserModel(
            username=username,
            password_hash=password_hash,
            role=role,
            is_active=active,
        )
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return self._to_entity(user)

    async def update_password(self, user_id: UUID, password_hash: str) -> None:
        model = await self._require(user_id)
        model.password_hash = password_hash
        await self._session.commit()

    async def set_active(self, user_id: UUID, active: bool) -> UserAccount:
        model = await self._require(user_id)
        model.is_active = active
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, user_id: UUID) -> None:
        model = await self._require(user_id)
        await self._session.delete(model)
        await self._session.commit()

    async def record_login(self, user_id: UUID) -> None:
        model = await self._require(user_id)
        model.last_login_at = datetime.now(UTC)
        await self._session.commit()

    async def _require(self, user_id: UUID) -> UserModel:
        model = await self._session.get(UserModel, user_id)
        if model is None:
            raise LookupError(f"User not found: {user_id}")
        return model

    @staticmethod
    def _to_entity(model: UserModel) -> UserAccount:
        return UserAccount(
            id=model.id,
            username=model.username,
            password_hash=model.password_hash,
            is_active=model.is_active,
            role=model.role,
            created_at=model.created_at,
            updated_at=model.updated_at,
            last_login_at=model.last_login_at,
        )
