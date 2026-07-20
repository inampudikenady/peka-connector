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


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    username: str
    password_hash: str
    is_active: bool
