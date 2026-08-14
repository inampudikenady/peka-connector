from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.application.services.cmdb_sources import CMDBSourceService
from app.application.services.integrations import (
    IntegrationService,
    SourceSwitchConfirmationRequiredError,
)
from app.application.services.ticketing import TICKETING_TOOL_NAMES, TicketingProviderService
from app.application.services.zammad import ZammadError, ZammadService, normalize_ticket
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.models.inventory import InventoryAssetModel
from app.infrastructure.database.models.servicenow import ServiceNowCIModel
from app.infrastructure.database.models.zammad import ZammadConfigurationModel, ZammadTicketModel
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.scheduling import ConnectorScheduler
from app.infrastructure.security.secrets import SecretEncryptionService


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def _encryption() -> SecretEncryptionService:
    return SecretEncryptionService(SecretStr("integration-test-key-that-is-long-enough"))


def _ticket(ticket_id: str, number: str, title: str):
    now = datetime.now(UTC)
    return normalize_ticket(
        {
            "id": ticket_id,
            "number": number,
            "title": title,
            "state": "open",
            "state_type": "open",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        [],
    )


async def _zammad_with_ticket(session):
    zammad = ZammadService(session, _encryption())
    saved = await zammad.save(
        None,
        {
            "name": "Operations Zammad",
            "base_url": "https://zammad.example.test",
            "access_token": "zammad-secret-token",
            "enabled": True,
        },
    )
    configuration = await zammad._configuration(UUID(saved["id"]))
    await zammad._upsert(
        configuration,
        _ticket("1", "11007", "Memory pressure on lin001"),
        datetime.now(UTC),
    )
    configuration.last_successful_sync_at = datetime.now(UTC)
    await session.commit()
    integration = await zammad._enabled_integration(require_synced=True)
    return zammad, configuration, integration


@pytest.mark.asyncio
async def test_enabled_integrations_coexist_without_active_provider_state() -> None:
    await _reset_database()
    async with session_factory() as session:
        zammad, _configuration, zammad_integration = await _zammad_with_ticket(session)
        service = IntegrationService(session, _encryption())
        servicenow = ConnectorIntegrationModel(
            connector_id=await service.connector_id(),
            integration_type="servicenow",
            display_name="Production ServiceNow",
            category="ITSM",
            enabled=True,
            status="healthy",
            capabilities_json={"incidents": True, "cmdb": True},
            initial_sync_status="completed",
        )
        session.add(servicenow)
        await session.commit()

        integrations = await service.list_integrations()
        enabled = {item["integration_type"] for item in integrations if item["enabled"]}
        assert {"zammad", "servicenow"} <= enabled
        assert all("active_provider_role" not in item for item in integrations)
        assert all("provider_generation" not in item for item in integrations)
        assert (await zammad.search_tickets({"query": "memory"}))["count"] == 1
        assert (
            await TicketingProviderService(session, _encryption()).active_tool_names()
            == TICKETING_TOOL_NAMES
        )
        assert zammad_integration.enabled is True


@pytest.mark.asyncio
async def test_connection_success_does_not_report_unsynchronized_integration_healthy() -> None:
    await _reset_database()
    async with session_factory() as session:
        service = IntegrationService(session, _encryption())
        created = await service.create(
            {
                "integration_type": "servicenow",
                "display_name": "ServiceNow",
                "enabled": True,
                "configuration": {
                    "instance_url": "https://example.service-now.com",
                    "username": "api-user",
                    "password": "secret-value",
                },
            },
            "admin",
        )
        model = await service.mark_test_result(UUID(created["id"]), True)
        assert model.status == "configured"
        assert model.last_successful_test_at is not None
        assert model.last_successful_sync_at is None


@pytest.mark.asyncio
async def test_ticketing_source_switch_requires_confirmation_and_is_atomic() -> None:
    await _reset_database()
    async with session_factory() as session:
        service = IntegrationService(session, _encryption())
        servicenow = await service.create(
            {"integration_type": "servicenow", "display_name": "ServiceNow", "enabled": True},
            "admin",
        )
        zammad = await service.create(
            {"integration_type": "zammad", "display_name": "Zammad", "enabled": True},
            "admin",
        )
        with pytest.raises(SourceSwitchConfirmationRequiredError):
            await service.select_source(
                UUID(zammad["id"]), "ticketing", confirmed=False, actor="admin"
            )
        before = await service.stream_sources()
        ticketing = next(item for item in before if item["stream"] == "ticketing")
        assert [item["source_key"] for item in ticketing["sources"] if item["selected"]] == [
            "servicenow"
        ]

        switched = await service.select_source(
            UUID(zammad["id"]), "ticketing", confirmed=True, actor="admin"
        )
        assert switched["previous_source"] == "servicenow"
        after = await service.stream_sources()
        ticketing = next(item for item in after if item["stream"] == "ticketing")
        assert [
            item["source_key"] for item in ticketing["sources"] if item["selected"]
        ] == ["zammad"]
        assert all(item["configured"] for item in ticketing["sources"])
        assert servicenow["id"] != zammad["id"]


@pytest.mark.asyncio
async def test_servicenow_capabilities_activate_independently_from_connection() -> None:
    await _reset_database()
    async with session_factory() as session:
        service = IntegrationService(session, _encryption())
        servicenow = await service.create(
            {"integration_type": "servicenow", "display_name": "ServiceNow", "enabled": True},
            "admin",
        )
        local = await service.create(
            {"integration_type": "generic_cmdb", "display_name": "Local CMDB", "enabled": True},
            "admin",
        )
        await service.select_source(UUID(local["id"]), "cmdb", confirmed=True, actor="admin")
        streams = await service.stream_sources()
        assert (
            next(item for item in streams if item["stream"] == "ticketing")["selected_source"]
            == "servicenow"
        )
        assert (
            next(item for item in streams if item["stream"] == "cmdb")["selected_source"]
            == "local_cmdb"
        )

        zammad = await service.create(
            {"integration_type": "zammad", "display_name": "Zammad", "enabled": True},
            "admin",
        )
        await service.select_source(
            UUID(zammad["id"]), "ticketing", confirmed=True, actor="admin"
        )
        await service.select_source(
            UUID(servicenow["id"]), "cmdb", confirmed=True, actor="admin"
        )
        streams = await service.stream_sources()
        assert (
            next(item for item in streams if item["stream"] == "ticketing")["selected_source"]
            == "zammad"
        )
        assert (
            next(item for item in streams if item["stream"] == "cmdb")["selected_source"]
            == "servicenow_cmdb"
        )


@pytest.mark.asyncio
async def test_cmdb_switch_routes_only_to_active_source_and_classifies_servers() -> None:
    await _reset_database()
    now = datetime.now(UTC)
    async with session_factory() as session:
        integrations = IntegrationService(session, _encryption())
        servicenow = await integrations.create(
            {"integration_type": "servicenow", "display_name": "ServiceNow", "enabled": True},
            "admin",
        )
        local = await integrations.create(
            {"integration_type": "generic_cmdb", "display_name": "Local CMDB", "enabled": True},
            "admin",
        )
        session.add(
            InventoryAssetModel(
                canonical_name="local.example.test",
                hostname="local",
                asset_type="server",
                operating_system="Linux",
            )
        )
        session.add_all(
            [
                ServiceNowCIModel(
                    tenant_id="tenant",
                    connector_id="local-connector",
                    integration_id=UUID(servicenow["id"]),
                    external_id="sn-server",
                    external_sys_id="sn-server",
                    sys_class_name="cmdb_ci_linux_server",
                    name="sn-server",
                    fqdn="sn-server.example.test",
                    source_updated_at=now,
                    fields_json={"os": "Linux"},
                ),
                ServiceNowCIModel(
                    tenant_id="tenant",
                    connector_id="local-connector",
                    integration_id=UUID(servicenow["id"]),
                    external_id="sn-container",
                    external_sys_id="sn-container",
                    sys_class_name="cmdb_ci_container",
                    name="sn-container",
                    source_updated_at=now,
                ),
            ]
        )
        await session.commit()

        cmdb = CMDBSourceService(session, _encryption())
        await integrations.select_source(
            UUID(servicenow["id"]), "cmdb", confirmed=True, actor="admin"
        )
        servicenow_rows = await cmdb.search_assets(asset_class="server", limit=50)
        assert [row["canonical_name"] for row in servicenow_rows] == [
            "sn-server.example.test"
        ]
        assert all(row["source"] == "ServiceNow CMDB" for row in servicenow_rows)

        await integrations.select_source(
            UUID(local["id"]), "cmdb", confirmed=True, actor="admin"
        )
        local_rows = await cmdb.search_assets(asset_class="server", limit=50)
        assert [row["canonical_name"] for row in local_rows] == ["local.example.test"]
        assert all(row["source"] == "Local CMDB" for row in local_rows)


@pytest.mark.asyncio
async def test_disabling_zammad_stops_schedule_without_hiding_cached_records() -> None:
    await _reset_database()
    async with session_factory() as session:
        zammad, configuration, integration = await _zammad_with_ticket(session)
        scheduler = ConnectorScheduler()
        scheduler._scheduler.start(paused=True)
        try:
            await scheduler.reconcile_zammad(configuration.id)
            assert scheduler._scheduler.get_job(f"zammad:{configuration.id}") is not None

            await IntegrationService(session, _encryption()).set_enabled(
                integration.id, False, "admin"
            )
            await scheduler.reconcile_zammad(configuration.id)
            assert scheduler._scheduler.get_job(f"zammad:{configuration.id}") is None
            cached = await session.scalar(
                select(ZammadTicketModel).where(ZammadTicketModel.integration_id == integration.id)
            )
            assert cached is not None
            assert cached.cache_status == "active"
            assert cached.visible is True
            with pytest.raises(ZammadError) as exc:
                await zammad.search_tickets({"query": "memory"})
            assert exc.value.code == "TICKETING_PROVIDER_UNAVAILABLE"
        finally:
            scheduler._scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_connector_scoping_excludes_other_connector_cache() -> None:
    await _reset_database()
    async with session_factory() as session:
        zammad, _configuration, local = await _zammad_with_ticket(session)
        other = ConnectorIntegrationModel(
            connector_id="other-connector",
            integration_type="zammad",
            display_name="Other connector Zammad",
            category="ITSM",
            enabled=True,
            status="healthy",
            capabilities_json={"tickets": True},
            initial_sync_status="completed",
        )
        session.add(other)
        await session.flush()
        now = datetime.now(UTC)
        session.add(
            ZammadTicketModel(
                configuration_id=None,
                instance_key="other-zammad",
                source="zammad",
                connector_id="other-connector",
                integration_type="zammad",
                integration_id=other.id,
                source_record_id="1",
                source_updated_at=now,
                synced_at=now,
                cache_status="active",
                external_id="1",
                number="OTHER-1",
                title="Other connector ticket",
                state="open",
                state_type="open",
                created_at_source=now,
                updated_at_source=now,
                is_open=True,
                visible=True,
            )
        )
        await session.commit()

        result = await zammad.search_tickets({"query": "ticket", "limit": 20})
        assert "OTHER-1" not in {item["number"] for item in result["tickets"]}
        enabled = await zammad._enabled_integration(require_synced=True)
        assert enabled.id == local.id


@pytest.mark.asyncio
async def test_legacy_bootstrap_preserves_encrypted_zammad_secret_and_tools() -> None:
    await _reset_database()
    encryption = _encryption()
    encrypted_token = encryption.encrypt("existing-customer-token")
    async with session_factory() as session:
        configuration = ZammadConfigurationModel(
            name="Existing Zammad",
            instance_key="existing-zammad",
            base_url="https://zammad.example.test",
            encrypted_access_token=encrypted_token,
            token_configured=True,
            enabled=True,
            connection_state="connected",
            last_successful_test_at=datetime.now(UTC),
            last_successful_sync_at=datetime.now(UTC),
        )
        session.add(configuration)
        await session.commit()

        service = IntegrationService(session, encryption)
        await service.bootstrap_legacy_integrations()
        integration = await ZammadService(session, encryption)._enabled_integration(
            require_synced=True
        )

        preserved = await session.get(ZammadConfigurationModel, configuration.id)
        assert preserved is not None
        assert preserved.encrypted_access_token == encrypted_token
        assert encryption.decrypt(preserved.encrypted_access_token) == "existing-customer-token"
        assert integration.legacy_zammad_configuration_id == configuration.id
        assert (
            await TicketingProviderService(session, encryption).active_tool_names()
            == TICKETING_TOOL_NAMES
        )
