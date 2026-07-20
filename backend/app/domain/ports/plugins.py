from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.domain.entities.document import DiscoveredDocument


class SourcePlugin[ConfigT: BaseModel](ABC):
    """Contract shared by every discoverable connector source."""

    plugin_type: str
    display_name: str
    config_model: type[ConfigT]

    def parse_config(self, raw: dict[str, object]) -> ConfigT:
        return self.config_model.model_validate(raw)

    @abstractmethod
    async def validate(self, config: ConfigT) -> None:
        """Raise a domain-friendly error when the source cannot be used."""

    @abstractmethod
    def discover(self, config: ConfigT) -> AsyncIterator[DiscoveredDocument]:
        """Yield metadata for discoverable items without extracting content."""
