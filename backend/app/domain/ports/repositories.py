from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.domain.entities.document import DiscoveredDocument
from app.domain.entities.source import Source, UserAccount


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserAccount | None: ...

    async def get_by_id(self, user_id: UUID) -> UserAccount | None: ...

    async def count(self) -> int: ...

    async def create(self, username: str, password_hash: str) -> UserAccount: ...


class SourceRepository(Protocol):
    async def list(self) -> Sequence[Source]: ...

    async def get(self, source_id: UUID) -> Source | None: ...

    async def create(
        self, plugin_type: str, name: str, enabled: bool, configuration: dict[str, Any]
    ) -> Source: ...

    async def update(
        self,
        source_id: UUID,
        name: str,
        enabled: bool,
        configuration: dict[str, Any],
    ) -> Source: ...

    async def delete(self, source_id: UUID) -> None: ...


class DocumentRepository(Protocol):
    async def replace_for_source(
        self, source_id: UUID, documents: Sequence[DiscoveredDocument]
    ) -> int: ...

    async def list_for_source(self, source_id: UUID) -> Sequence[DiscoveredDocument]: ...
