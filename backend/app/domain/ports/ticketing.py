"""Provider-neutral ticketing adapter contract."""

from typing import Any, Protocol


class TicketingProvider(Protocol):
    async def test_connection(self) -> dict[str, Any]: ...
    async def initial_sync(self) -> dict[str, Any]: ...
    async def incremental_sync(self, cursor: str | None) -> dict[str, Any]: ...
    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def search_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def get_ticket_counts(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def get_asset_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def correlate_tickets_with_evidence(
        self, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


class ServiceNowProviderUnavailable:
    """Honest placeholder until the ServiceNow API adapter is implemented."""

    message = "The ServiceNow API adapter is not implemented yet."

    async def _unavailable(self) -> dict[str, Any]:
        raise NotImplementedError(self.message)

    test_connection = initial_sync = _unavailable

    async def incremental_sync(self, cursor: str | None) -> dict[str, Any]:
        return await self._unavailable()

    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._unavailable()

    search_tickets = get_ticket_counts = get_asset_tickets = get_ticket
    correlate_tickets_with_evidence = get_ticket
