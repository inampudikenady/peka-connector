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

    async def create(self, username: str, password_hash: str) -> UserAccount:
        user = UserModel(username=username, password_hash=password_hash)
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return self._to_entity(user)

    @staticmethod
    def _to_entity(model: UserModel) -> UserAccount:
        return UserAccount(
            id=model.id,
            username=model.username,
            password_hash=model.password_hash,
            is_active=model.is_active,
        )
