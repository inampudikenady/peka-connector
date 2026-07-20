from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.entities.document import DiscoveredDocument
from app.domain.entities.source import ScanRecord, Source, UserAccount


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserAccount | None: ...

    async def get_by_id(self, user_id: UUID) -> UserAccount | None: ...

    async def count(self) -> int: ...

    async def count_active_administrators(self) -> int: ...

    async def list(self) -> Sequence[UserAccount]: ...

    async def create(
        self, username: str, password_hash: str, role: str = "administrator"
    ) -> UserAccount: ...

    async def update_password(self, user_id: UUID, password_hash: str) -> None: ...

    async def set_active(self, user_id: UUID, active: bool) -> UserAccount: ...

    async def delete(self, user_id: UUID) -> None: ...

    async def record_login(self, user_id: UUID) -> None: ...


class RefreshTokenRepository(Protocol):
    async def create(
        self,
        user_id: UUID,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
    ) -> None: ...

    async def get_valid_user_id(self, token_hash: str, csrf_hash: str) -> UUID | None: ...

    async def revoke(self, token_hash: str) -> None: ...

    async def revoke_for_user(self, user_id: UUID) -> None: ...


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

    async def update_operational_status(
        self,
        source_id: UUID,
        health_status: str,
        last_error: str | None,
        file_count: int | None = None,
        success: bool = False,
    ) -> Source: ...


class DocumentRepository(Protocol):
    async def reconcile_for_source(
        self, source_id: UUID, documents: Sequence[DiscoveredDocument]
    ) -> dict[str, int]: ...

    async def list_for_source(self, source_id: UUID) -> Sequence[DiscoveredDocument]: ...


class ScanRepository(Protocol):
    async def start(self, source_id: UUID) -> ScanRecord: ...

    async def complete(
        self, scan_id: UUID, counts: dict[str, int], discovered_count: int
    ) -> ScanRecord: ...

    async def fail(self, scan_id: UUID, error: str) -> ScanRecord: ...

    async def list_for_source(self, source_id: UUID, limit: int = 50) -> Sequence[ScanRecord]: ...
