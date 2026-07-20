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
