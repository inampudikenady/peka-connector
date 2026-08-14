"""Provider-neutral ticketing facade, discovery, and normalized multi-source queries."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integrations import IntegrationService
from app.application.services.servicenow import ServiceNowError, ServiceNowService
from app.application.services.zammad import ZammadError, ZammadService
from app.domain.ports.ticketing import TicketingProvider
from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.models.servicenow import ServiceNowConfigurationModel
from app.infrastructure.database.models.zammad import ZammadConfigurationModel
from app.infrastructure.security.secrets import SecretEncryptionService

TICKETING_TOOL_NAMES = frozenset(
    {
        "search_tickets",
        "get_ticket",
        "get_ticket_counts",
        "get_asset_tickets",
        "correlate_tickets_with_evidence",
    }
)


class ZammadTicketingProvider:
    """Adapt the existing Zammad implementation to the provider-neutral contract."""

    def __init__(self, service: ZammadService) -> None:
        self.service = service

    async def test_connection(self) -> dict[str, Any]:
        integration = await self.service._enabled_integration(require_synced=False)
        if integration.legacy_zammad_configuration_id is None:
            raise ZammadError("CONFIGURATION_NOT_FOUND", "Zammad configuration was not found.")
        return await self.service.test(integration.legacy_zammad_configuration_id)

    async def initial_sync(self) -> dict[str, Any]:
        integration = await self.service._enabled_integration(require_synced=False)
        if integration.legacy_zammad_configuration_id is None:
            raise ZammadError("CONFIGURATION_NOT_FOUND", "Zammad configuration was not found.")
        return await self.service.synchronize(integration.legacy_zammad_configuration_id)

    async def incremental_sync(self, cursor: str | None) -> dict[str, Any]:
        # Zammad persists its own cursor. The neutral contract deliberately does not
        # allow callers to override a provider's trusted synchronization state.
        return await self.initial_sync()

    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.service.get_ticket(arguments)

    async def search_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.service.search_tickets(arguments)

    async def get_ticket_counts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.service.get_ticket_counts(arguments)

    async def get_asset_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.service.get_asset_tickets(arguments)

    async def correlate_tickets_with_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.service.correlate_tickets_with_evidence(arguments)


class ServiceNowTicketingProvider:
    """Adapt ServiceNow ticket records to the provider-neutral ticketing contract."""

    def __init__(self, service: ServiceNowService, integration_id: Any) -> None:
        self.service = service
        self.integration_id = integration_id

    async def test_connection(self) -> dict[str, Any]:
        configuration = await self.service._active_configuration(
            self.integration_id, require_enabled=True
        )
        return await self.service.test(configuration.id)

    async def initial_sync(self) -> dict[str, Any]:
        configuration = await self.service._active_configuration(
            self.integration_id, require_enabled=True
        )
        return await self.service.synchronize(configuration.id)

    async def incremental_sync(self, cursor: str | None) -> dict[str, Any]:
        return await self.initial_sync()

    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]:
        number = str(arguments.get("ticket_number") or arguments.get("external_id") or "")
        prefix = number[:3].upper()
        if prefix in {"PRB", "CHG"}:
            tool_name = (
                "servicenow_search_problems"
                if prefix == "PRB"
                else "servicenow_search_changes"
            )
            result = await self.service.execute_tool(
                tool_name, {"query": number, "limit": 25}
            )
            record = next(
                (
                    item
                    for item in result.get("records") or []
                    if str(item.get("number") or item.get("external_id") or "").upper()
                    == number.upper()
                ),
                None,
            )
        else:
            result = await self.service.execute_tool(
                "servicenow_get_incident", {"number": number}
            )
            record = result.get("incident")
        ticket = self._ticket(record) if record else None
        return {
            "ticket": ticket,
            "availability": result.get("availability") or {},
        }

    async def search_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.service.execute_tool(
            "servicenow_list_open_incidents"
            if arguments.get("state", "open") == "open"
            else "servicenow_search_incidents",
            {
                "query": arguments.get("query"),
                "limit": arguments.get("limit", 50),
            },
        )
        tickets = [self._ticket(item) for item in result.get("records") or []]
        return {
            "tickets": tickets,
            "count": int(result.get("count", len(tickets))),
            "availability": result.get("availability") or {},
        }

    async def get_ticket_counts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.search_tickets({**arguments, "limit": 50})
        return {"count": result["count"], "availability": result["availability"]}

    async def get_asset_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.service.execute_tool(
            "servicenow_get_ci_tickets",
            {"identifier": arguments["identifier"], "max_depth": 3},
        )
        tickets = [self._ticket(item) for item in result.get("records") or []]
        open_tickets = [item for item in tickets if item["is_open"]]
        closed_tickets = [item for item in tickets if not item["is_open"]]
        return {
            "match_status": "found" if result.get("ci") else "not_found",
            "direct_tickets": tickets,
            "indirect_tickets": [],
            "open_tickets": open_tickets,
            "recently_closed_tickets": closed_tickets,
            "availability": result.get("availability") or {},
        }

    async def correlate_tickets_with_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.get_asset_tickets(arguments)
        return {
            "correlations": [],
            "availability": result.get("availability") or {},
            "warning": "ServiceNow records were returned without inferred causal correlation.",
        }

    @staticmethod
    def _ticket(item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        record_type = str(item.get("record_type") or "incident")
        state = str(item.get("state") or "unknown")
        active = item.get("active") is True
        return {
            **item,
            "source": "servicenow",
            "number": item.get("number") or item.get("external_id"),
            "external_id": item.get("external_id") or item.get("number"),
            "title": item.get("short_description") or item.get("title"),
            "summary": item.get("short_description") or item.get("title"),
            "state": state,
            "is_open": active,
            "ticket_type": record_type,
            "updated_at": item.get("source_updated_at"),
        }


class TicketingProviderService:
    """Route ticket operations exclusively through the stream's active source."""

    def __init__(self, session: AsyncSession, encryption: SecretEncryptionService) -> None:
        self.session = session
        self.integrations = IntegrationService(session, encryption)
        self.zammad = ZammadService(session, encryption)
        self.servicenow = ServiceNowService(session, encryption)

    async def search_enabled_records(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Query the configured source selected by the Ticketing stream binding."""
        requested = set(arguments.get("providers") or {"zammad", "servicenow"})
        mode = str(arguments.get("mode") or "search")
        state = str(arguments.get("state") or "open")
        query = str(arguments.get("query") or "")
        identifier = str(arguments.get("identifier") or "")
        limit = min(max(int(arguments.get("limit") or 50), 1), 50)
        record_types = list(arguments.get("record_types") or ["incident", "problem", "change"])
        configured: list[str] = []
        enabled: list[str] = []
        providers: list[dict[str, Any]] = []
        connector_id = await self.integrations.connector_id()
        await self.integrations.bootstrap_legacy_integrations()
        await self.integrations.bootstrap_stream_activations()
        active = await self.integrations.active_source("ticketing")
        active_key = active.source_key if active else None

        zammad_pair = (
            await self.session.execute(
                select(ZammadConfigurationModel, ConnectorIntegrationModel)
                .join(
                    ConnectorIntegrationModel,
                    ConnectorIntegrationModel.legacy_zammad_configuration_id
                    == ZammadConfigurationModel.id,
                )
                .where(
                    ConnectorIntegrationModel.connector_id == connector_id,
                    ConnectorIntegrationModel.integration_type == "zammad",
                )
                .order_by(ZammadConfigurationModel.updated_at.desc())
            )
        ).first()
        zammad_configuration = zammad_pair[0] if zammad_pair else None
        zammad_integration = zammad_pair[1] if zammad_pair else None
        if zammad_configuration and zammad_configuration.token_configured:
            configured.append("zammad")
            if zammad_integration and active_key == "zammad":
                enabled.append("zammad")
                if "zammad" in requested:
                    providers.append(
                        await self._zammad_records(
                            zammad_configuration, mode, state, query, identifier, limit
                        )
                    )

        servicenow_pair = (
            await self.session.execute(
                select(ServiceNowConfigurationModel, ConnectorIntegrationModel)
                .join(
                    ConnectorIntegrationModel,
                    ConnectorIntegrationModel.id == ServiceNowConfigurationModel.integration_id,
                )
                .where(
                    ConnectorIntegrationModel.connector_id == connector_id,
                    ConnectorIntegrationModel.integration_type == "servicenow",
                )
                .order_by(ServiceNowConfigurationModel.updated_at.desc())
            )
        ).first()
        servicenow_configuration = servicenow_pair[0] if servicenow_pair else None
        servicenow_integration = servicenow_pair[1] if servicenow_pair else None
        if (
            servicenow_configuration
            and servicenow_configuration.instance_url
            and servicenow_configuration.username
            and servicenow_configuration.encrypted_password
        ):
            configured.append("servicenow")
            if servicenow_integration and active_key == "servicenow":
                enabled.append("servicenow")
                if "servicenow" in requested:
                    providers.append(
                        await self._servicenow_records(
                            mode, state, query, identifier, limit, record_types
                        )
                    )
        return {
            "requested_providers": sorted(requested),
            "configured_providers": configured,
            "enabled_providers": enabled,
            "selected_providers": [item["source"] for item in providers],
            "active_source": active_key,
            "providers": providers,
        }

    async def _servicenow_records(
        self,
        mode: str,
        state: str,
        query: str,
        identifier: str,
        limit: int,
        record_types: list[str],
    ) -> dict[str, Any]:
        try:
            if mode == "asset":
                result = await self.servicenow.execute_tool(
                    "servicenow_get_ci_tickets",
                    {"identifier": identifier, "max_depth": 3},
                )
            else:
                records: list[dict[str, Any]] = []
                availability: dict[str, Any] = {}
                tools = {
                    "incident": (
                        "servicenow_list_open_incidents"
                        if state == "open"
                        else "servicenow_search_incidents"
                    ),
                    "problem": "servicenow_search_problems",
                    "change": "servicenow_search_changes",
                }
                for record_type in record_types:
                    result = await self.servicenow.execute_tool(
                        tools[record_type],
                        {
                            "query": query or None,
                            "identifier": identifier or None,
                            "limit": limit,
                        },
                    )
                    records.extend(result.get("records") or [])
                    availability = result.get("availability") or availability
                result = {"records": records, "availability": availability}
            records = list(result.get("records") or [])
            records = [item for item in records if item.get("record_type") in record_types]
            if state == "open":
                records = [
                    item
                    for item in records
                    if item.get("active") is True
                    and str(item.get("state_value") or "").casefold() not in {"6", "7", "8"}
                    and str(item.get("state") or "").casefold()
                    not in {"resolved", "closed", "canceled", "cancelled"}
                ]
            availability = result.get("availability") or {}
            total = len(records)
            return {
                "source": "servicenow",
                "record_type": "ticket",
                "status": "ok",
                "enabled": True,
                "stale": bool(availability.get("stale")),
                "last_synced_at": availability.get("cache_timestamp"),
                "total": total,
                "count": total,
                "records": records[:limit],
            }
        except ServiceNowError as exc:
            return self._provider_error("servicenow", "incident", exc.code, str(exc))

    async def _zammad_records(
        self,
        configuration: ZammadConfigurationModel,
        mode: str,
        state: str,
        query: str,
        identifier: str,
        limit: int,
    ) -> dict[str, Any]:
        try:
            if mode == "asset":
                result = await self.zammad.get_asset_tickets(
                    {"identifier": identifier, "recently_closed_days": 30}
                )
                records = [
                    *list(result.get("direct_tickets") or []),
                    *list(result.get("indirect_tickets") or []),
                ]
                availability = result.get("availability") or {}
            else:
                result = await self.zammad.search_tickets(
                    {
                        "query": query,
                        "state": state,
                        "limit": limit,
                        "sort_order": "updated_desc",
                    }
                )
                records = list(result.get("tickets") or [])
                availability = {
                    "stale": bool(result.get("warning")),
                    "cache_timestamp": result.get("cache_timestamp"),
                }
            normalized = [
                {
                    **item,
                    "source": "zammad",
                    "record_type": "ticket",
                    "external_id": item.get("number") or item.get("external_id"),
                    "title": item.get("title") or item.get("summary"),
                    "active": bool(item.get("is_open")),
                }
                for item in records
                if state != "open" or item.get("is_open") is True
            ]
            total = int(result.get("count", len(normalized)))
            return {
                "source": "zammad",
                "record_type": "ticket",
                "status": "ok",
                "enabled": True,
                "stale": bool(availability.get("stale")),
                "last_synced_at": availability.get("cache_timestamp")
                or configuration.last_successful_sync_at,
                "total": total,
                "count": total,
                "records": normalized[:limit],
            }
        except ZammadError as exc:
            return self._provider_error("zammad", "ticket", exc.code, str(exc))

    @staticmethod
    def _provider_error(source: str, record_type: str, code: str, message: str) -> dict[str, Any]:
        return {
            "source": source,
            "record_type": record_type,
            "status": "error",
            "enabled": True,
            "stale": False,
            "last_synced_at": None,
            "total": 0,
            "count": 0,
            "records": [],
            "error_code": code,
            "error_message": message,
        }

    async def provider(self) -> TicketingProvider:
        active = await self.integrations.active_source("ticketing")
        if active is None:
            raise ZammadError(
                "TICKETING_PROVIDER_UNAVAILABLE",
                "No active Ticketing source is configured.",
                503,
            )
        if active.source_key == "servicenow":
            await self.servicenow._active_configuration(active.integration_id, require_enabled=True)
            return ServiceNowTicketingProvider(self.servicenow, active.integration_id)
        await self.zammad._enabled_integration(require_synced=True)
        return ZammadTicketingProvider(self.zammad)

    async def active_tool_names(self) -> frozenset[str]:
        try:
            active = await self.integrations.active_source("ticketing")
            if active is None:
                return frozenset()
            integration = await self.session.get(ConnectorIntegrationModel, active.integration_id)
            if active.source_key == "zammad":
                await self.zammad._enabled_integration(require_synced=True)
            else:
                await self.servicenow._active_configuration(
                    active.integration_id, require_enabled=True
                )
        except (ZammadError, ServiceNowError):
            return frozenset()
        if (
            integration is None
            or not integration.enabled
            or not integration.capabilities_json.get("tickets", False)
            or integration.status in {"failed", "unavailable"}
        ):
            return frozenset()
        return TICKETING_TOOL_NAMES

    async def ensure_tool_available(self, tool_name: str) -> None:
        if tool_name in await self.active_tool_names():
            return
        raise ZammadError(
            "TICKETING_ADAPTER_UNAVAILABLE",
            "The active Ticketing source is unavailable.",
            503,
        )

    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._with_provider(await (await self.provider()).get_ticket(arguments))

    async def search_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._with_provider(await (await self.provider()).search_tickets(arguments))

    async def get_ticket_counts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._with_provider(await (await self.provider()).get_ticket_counts(arguments))

    async def get_asset_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._with_provider(await (await self.provider()).get_asset_tickets(arguments))

    async def correlate_tickets_with_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._with_provider(
            await (await self.provider()).correlate_tickets_with_evidence(arguments)
        )

    async def _with_provider(self, result: dict[str, Any]) -> dict[str, Any]:
        active = await self.integrations.active_source("ticketing")
        if active is None:
            raise ZammadError(
                "TICKETING_PROVIDER_UNAVAILABLE", "No active Ticketing source is configured."
            )
        integration = await self.session.get(ConnectorIntegrationModel, active.integration_id)
        if integration is None:
            raise ZammadError(
                "TICKETING_PROVIDER_UNAVAILABLE", "The active Ticketing source is unavailable."
            )
        return {
            **result,
            "ticketing_provider": {
                "integration_id": str(integration.id),
                "integration_type": integration.integration_type,
                "display_name": integration.display_name,
                "source_key": active.source_key,
            },
        }
