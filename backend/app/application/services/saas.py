from typing import Protocol


class SaaSRegistrationUnavailableError(Exception):
    pass


class SaaSRegistrationPort(Protocol):
    async def register(self) -> None: ...

    async def unregister(self) -> None: ...


class UnavailableSaaSRegistrationService:
    """Explicit boundary used until the PEKA SaaS registration API is available."""

    async def register(self) -> None:
        raise SaaSRegistrationUnavailableError(
            "PEKA SaaS registration API is not configured in this release"
        )

    async def unregister(self) -> None:
        raise SaaSRegistrationUnavailableError(
            "PEKA SaaS registration API is not configured in this release"
        )
