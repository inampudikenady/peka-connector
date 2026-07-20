from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DiscoveredDocument:
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    modified_at: datetime
    sha256: str
    discovered_at: datetime | None = None
    last_seen_at: datetime | None = None
    state: str = "active"


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    documents: tuple[DiscoveredDocument, ...]
    failed_count: int = 0
