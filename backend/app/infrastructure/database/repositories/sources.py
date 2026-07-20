from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.source import Source
from app.infrastructure.database.models.source import SourceModel


class SqlAlchemySourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[Source]:
        result = await self._session.scalars(select(SourceModel).order_by(SourceModel.name))
        return [self._to_entity(model) for model in result.all()]

    async def get(self, source_id: UUID) -> Source | None:
        model = await self._session.get(SourceModel, source_id)
        return self._to_entity(model) if model else None

    async def create(
        self, plugin_type: str, name: str, enabled: bool, configuration: dict[str, Any]
    ) -> Source:
        source = SourceModel(
            plugin_type=plugin_type, name=name, enabled=enabled, configuration=configuration
        )
        self._session.add(source)
        await self._session.commit()
        await self._session.refresh(source)
        return self._to_entity(source)

    async def update(
        self,
        source_id: UUID,
        name: str,
        enabled: bool,
        configuration: dict[str, Any],
    ) -> Source:
        source = await self._session.get(SourceModel, source_id)
        if source is None:
            raise LookupError(f"Source not found: {source_id}")
        source.name = name
        source.enabled = enabled
        source.configuration = configuration
        await self._session.commit()
        await self._session.refresh(source)
        return self._to_entity(source)

    async def delete(self, source_id: UUID) -> None:
        source = await self._session.get(SourceModel, source_id)
        if source is None:
            return
        await self._session.delete(source)
        await self._session.commit()

    @staticmethod
    def _to_entity(model: SourceModel) -> Source:
        return Source(
            id=model.id,
            plugin_type=model.plugin_type,
            name=model.name,
            enabled=model.enabled,
            configuration=model.configuration,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
