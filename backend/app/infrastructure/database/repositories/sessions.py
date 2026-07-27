from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.user import RefreshTokenModel


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: UUID,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            RefreshTokenModel(
                user_id=user_id,
                token_hash=token_hash,
                csrf_hash=csrf_hash,
                expires_at=expires_at,
            )
        )
        await self._session.commit()

    async def get_valid_user_id(self, token_hash: str, csrf_hash: str) -> UUID | None:
        now = datetime.now(UTC)
        query = select(RefreshTokenModel.user_id).where(
            RefreshTokenModel.token_hash == token_hash,
            RefreshTokenModel.csrf_hash == csrf_hash,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
        return cast(UUID | None, await self._session.scalar(query))

    async def revoke(self, token_hash: str) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.token_hash == token_hash)
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.commit()

    async def revoke_for_user(self, user_id: UUID) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.commit()
