from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Source:
    id: UUID
    plugin_type: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    health_status: str
    last_success_at: datetime | None
    last_error: str | None
    last_scan_at: datetime | None
    file_count: int


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    username: str
    password_hash: str
    is_active: bool
    role: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScanRecord:
    id: UUID
    source_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    discovered_count: int
    added_count: int
    changed_count: int
    unchanged_count: int
    missing_count: int
    failed_count: int
    error: str | None
