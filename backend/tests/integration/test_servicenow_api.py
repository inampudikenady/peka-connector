import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.application.services.integrations import IntegrationService
from app.application.services.servicenow import ServiceNowClient, ServiceNowService
from app.application.services.ticketing import TicketingProviderService
from app.core.config import get_settings
from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.integration import (
    ConnectorIntegrationModel,
    IntegrationStreamActivationModel,
)
from app.infrastructure.database.models.servicenow import (
    ServiceNowCIModel,
    ServiceNowConfigurationModel,
    ServiceNowJournalModel,
    ServiceNowRecordModel,
    ServiceNowRelationshipModel,
    ServiceNowSyncCursorModel,
)
from app.infrastructure.database.models.zammad import ZammadConfigurationModel
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.security.secrets import SecretEncryptionService
from app.main import app

PASSWORD = "Strong!ServiceNowTestPass123"


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(_reset_database())
    auth_rate_limiter.reset()
    with TestClient(app) as instance:
        yield instance


def headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": PASSWORD, "confirm_password": PASSWORD},
    )
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_servicenow_configuration_redacts_password_and_exposes_actions(
    client: TestClient, monkeypatch
) -> None:
    secret = "service-now-secret-never-returned"
    auth_headers = headers(client)
    created = client.post(
        "/api/v1/servicenow/configurations",
        headers=auth_headers,
        json={
            "name": "Lab ServiceNow",
            "enabled": True,
            "instance_url": "https://instance.service-now.com/",
            "username": "api-reader",
            "password": secret,
            "verify_tls": True,
            "request_timeout_seconds": 10,
            "page_size": 100,
            "sync_interval_seconds": 300,
        },
    )
    assert created.status_code == 201, created.text
    configuration = created.json()
    assert configuration["instance_url"] == "https://instance.service-now.com"
    assert configuration["password_configured"] is True
    assert "password" not in configuration
    assert secret not in created.text
    configuration_id = configuration["id"]

    async def stored_secret() -> tuple[str, str | None]:
        async with session_factory() as session:
            model = await session.get(ServiceNowConfigurationModel, UUID(configuration_id))
            assert model is not None
            integration = await session.get(ConnectorIntegrationModel, model.integration_id)
            assert integration is not None
            return model.encrypted_password, integration.configuration_encrypted

    encrypted_password, generic_secret_blob = asyncio.run(stored_secret())
    assert encrypted_password != secret
    assert secret not in encrypted_password
    assert generic_secret_blob is None

    listed = client.get("/api/v1/servicenow/configurations", headers=auth_headers)
    assert listed.status_code == 200
    assert secret not in listed.text

    async def test_connection(_client: ServiceNowClient):
        return {"success": True, "readable_configuration_item_count": 1}

    monkeypatch.setattr(ServiceNowClient, "test_connection", test_connection)
    tested = client.post(
        f"/api/v1/servicenow/configurations/{configuration_id}/test",
        headers=auth_headers,
    )
    assert tested.status_code == 200, tested.text

    async def synchronize(_service: ServiceNowService, _configuration_id):
        return {"counts": {"incidents": 2}, "stage_errors": {}}

    monkeypatch.setattr(ServiceNowService, "synchronize", synchronize)
    synced = client.post(
        f"/api/v1/servicenow/configurations/{configuration_id}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200
    assert synced.json()["counts"]["incidents"] == 2


def test_servicenow_sync_is_idempotent_correlated_and_stage_cursor_scoped(
    client: TestClient, monkeypatch
) -> None:
    auth_headers = headers(client)
    created = client.post(
        "/api/v1/servicenow/configurations",
        headers=auth_headers,
        json={
            "name": "ServiceNow",
            "enabled": True,
            "instance_url": "https://instance.service-now.com",
            "username": "api-reader",
            "password": "service-now-cache-test-secret",
            "verify_tls": True,
            "sync_interval_seconds": 300,
        },
    ).json()
    ci_id = "a" * 32

    async def cis(_client, _after=None):
        return [
            {
                "sys_id": ci_id,
                "sys_class_name": "cmdb_ci_linux_server",
                "name": "UTIL001",
                "fqdn": "util001.demo.internal",
                "ip_address": "172.16.165.12",
                "os": {"value": "linux", "display_value": "Red Hat Enterprise Linux"},
                "environment": {"value": "prod", "display_value": "Production"},
                "application": {"value": "app-1", "display_value": "Payments"},
                "owned_by": {"value": "user-1", "display_value": "Pat Owner"},
                "support_group": {"value": "group-1", "display_value": "Linux Support"},
                "install_status": {"value": "1", "display_value": "Installed"},
                "sys_updated_on": "2026-08-04 10:00:00",
            }
        ]

    async def relationships(_client, _after=None):
        return [
            {
                "sys_id": "b" * 32,
                "parent": {"value": ci_id, "display_value": "UTIL001"},
                "child": {"value": "c" * 32, "display_value": "Prometheus"},
                "type": {"value": "d" * 32, "display_value": "Runs on::Runs"},
                "sys_updated_on": "2026-08-04 10:00:01",
            },
            {
                "sys_id": "e" * 32,
                "parent": {"value": "c" * 32, "display_value": "Prometheus"},
                "child": {"value": ci_id, "display_value": "UTIL001"},
                "type": {"value": "f" * 32, "display_value": "Depends on::Used by"},
                "sys_updated_on": "2026-08-04 10:00:02",
            },
        ]

    async def incidents(_client, _after=None):
        return [
            {
                "sys_id": "1" * 32,
                "number": "INC0010001",
                "short_description": "Memory pressure on util001",
                "description": "util001.demo.internal is swapping",
                "active": "true",
                "state": {"value": "2", "display_value": "In Progress"},
                "cmdb_ci": {"value": ci_id, "display_value": "UTIL001"},
                "sys_updated_on": "2026-08-04 10:01:00",
            }
        ]

    async def journals(_client, _incident_id, _after=None):
        return [
            {
                "sys_id": "2" * 32,
                "element": "comments",
                "element_id": "1" * 32,
                "value": "Automated update",
                "sys_created_by": "system",
                "sys_created_on": "2026-08-04 10:02:00",
                "sys_updated_on": "2026-08-04 10:02:00",
            },
            {
                "sys_id": "3" * 32,
                "element": "work_notes",
                "element_id": "1" * 32,
                "value": "Operator reduced memory pressure",
                "sys_created_by": "alice",
                "sys_created_on": "2026-08-04 10:01:30",
                "sys_updated_on": "2026-08-04 10:01:30",
            },
        ]

    async def problems(_client, _after=None):
        return [
            {
                "sys_id": "4" * 32,
                "number": "PRB0010001",
                "short_description": "Recurring memory pressure",
                "active": "true",
                "state": "1",
                "cmdb_ci": {"value": ci_id, "display_value": "UTIL001"},
                "sys_updated_on": "2026-08-04 10:03:00",
            }
        ]

    async def changes(_client, _after=None):
        return [
            {
                "sys_id": "5" * 32,
                "number": "CHG0010001",
                "short_description": "Increase memory allocation",
                "active": "true",
                "state": "2",
                "cmdb_ci": {"value": ci_id, "display_value": "UTIL001"},
                "sys_updated_on": "2026-08-04 10:04:00",
            }
        ]

    monkeypatch.setattr(ServiceNowClient, "list_configuration_items", cis)
    monkeypatch.setattr(ServiceNowClient, "list_ci_relationships", relationships)
    monkeypatch.setattr(ServiceNowClient, "list_incidents", incidents)
    monkeypatch.setattr(ServiceNowClient, "list_incident_updates", journals)
    monkeypatch.setattr(ServiceNowClient, "list_problems", problems)
    monkeypatch.setattr(ServiceNowClient, "list_changes", changes)

    async def zammad_records(_service, _configuration, _mode, _state, _query, _identifier, _limit):
        return {
            "source": "zammad",
            "record_type": "ticket",
            "status": "ok",
            "enabled": True,
            "stale": False,
            "count": 1,
            "records": [{"external_id": "11012", "title": "Zammad issue", "active": True}],
        }

    monkeypatch.setattr(TicketingProviderService, "_zammad_records", zammad_records)

    for _ in range(2):
        response = client.post(
            f"/api/v1/servicenow/configurations/{created['id']}/sync",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

    async def snapshot():
        async with session_factory() as session:
            counts = {}
            for name, model in (
                ("cis", ServiceNowCIModel),
                ("relationships", ServiceNowRelationshipModel),
                ("records", ServiceNowRecordModel),
                ("journals", ServiceNowJournalModel),
                ("cursors", ServiceNowSyncCursorModel),
            ):
                counts[name] = await session.scalar(select(func.count()).select_from(model))
            service = ServiceNowService(
                session, SecretEncryptionService(get_settings().encryption_key)
            )
            encryption = SecretEncryptionService(get_settings().encryption_key)
            session.add(
                ZammadConfigurationModel(
                    name="Disabled Zammad",
                    instance_key="disabled-zammad",
                    base_url="https://tickets.example.test",
                    encrypted_access_token=encryption.encrypt("disabled-zammad-test-token"),
                    token_configured=True,
                    enabled=False,
                    connection_state="connected",
                    last_successful_sync_at=datetime.now(UTC),
                )
            )
            await session.commit()
            provider_result = await TicketingProviderService(
                session, encryption
            ).search_enabled_records(
                {
                    "mode": "search",
                    "state": "open",
                    "query": "",
                    "providers": [],
                    "limit": 50,
                }
            )
            zammad_configuration = await session.scalar(select(ZammadConfigurationModel))
            assert zammad_configuration is not None
            zammad_integration = await session.scalar(
                select(ConnectorIntegrationModel).where(
                    ConnectorIntegrationModel.integration_type == "zammad"
                )
            )
            servicenow_configuration = await session.get(
                ServiceNowConfigurationModel, UUID(created["id"])
            )
            assert zammad_integration is not None and servicenow_configuration is not None
            zammad_configuration.enabled = True
            zammad_integration.enabled = True
            await session.commit()
            both_enabled = await TicketingProviderService(
                session, encryption
            ).search_enabled_records(
                {"mode": "search", "state": "open", "query": "", "providers": [], "limit": 50}
            )
            await IntegrationService(session, encryption).select_source(
                zammad_integration.id,
                "ticketing",
                confirmed=True,
                actor="test",
            )
            servicenow_configuration.enabled = False
            servicenow_integration = await session.get(
                ConnectorIntegrationModel, servicenow_configuration.integration_id
            )
            assert servicenow_integration is not None
            servicenow_integration.enabled = False
            await session.commit()
            zammad_only = await TicketingProviderService(
                session, encryption
            ).search_enabled_records(
                {"mode": "search", "state": "open", "query": "", "providers": [], "limit": 50}
            )
            zammad_configuration.enabled = False
            zammad_integration.enabled = False
            await session.commit()
            both_disabled = await TicketingProviderService(
                session, encryption
            ).search_enabled_records(
                {"mode": "search", "state": "open", "query": "", "providers": [], "limit": 50}
            )
            servicenow_configuration.enabled = True
            servicenow_integration.enabled = True
            await session.commit()
            tickets = await service.execute_tool(
                "servicenow_get_ci_tickets", {"identifier": "172.16.165.12"}
            )
            graph = await service.execute_tool(
                "servicenow_get_ci_relationships",
                {"identifier": "util001.demo.internal", "max_depth": 3},
            )
            incident = await service.execute_tool(
                "servicenow_get_incident", {"number": "INC0010001"}
            )
            return (
                counts,
                tickets,
                graph,
                incident,
                provider_result,
                both_enabled,
                zammad_only,
                both_disabled,
            )

    (
        counts,
        tickets,
        graph,
        incident,
        provider_result,
        both_enabled,
        zammad_only,
        both_disabled,
    ) = asyncio.run(snapshot())
    assert counts == {"cis": 1, "relationships": 2, "records": 3, "journals": 2, "cursors": 6}
    assert {item["record_type"] for item in tickets["records"]} == {"incident", "problem", "change"}
    assert len(graph["relationships"]) == 2
    assert incident["incident"]["correlation_method"] == "cmdb_ci_sys_id"
    assert incident["incident"]["latest_update"] == "Operator reduced memory pressure"
    cmdb = client.get(
        f"/api/v1/servicenow/configurations/{created['id']}/cmdb",
        headers=auth_headers,
    )
    assert cmdb.status_code == 200, cmdb.text
    assert cmdb.json()["relationship_count"] == 2
    assert cmdb.json()["items"] == [
        {
            "id": cmdb.json()["items"][0]["id"],
            "ci_name": "UTIL001",
            "ci_class": "cmdb_ci_linux_server",
            "fqdn": "util001.demo.internal",
            "ip_address": "172.16.165.12",
            "operating_system": "Red Hat Enterprise Linux",
            "environment": "Production",
            "application": "Payments",
            "business_owner": "Pat Owner",
            "support_group": "Linux Support",
            "lifecycle_state": "Installed",
            "updated_at": "2026-08-04T10:00:00Z",
            "source": "ServiceNow CMDB",
        }
    ]
    assert provider_result["configured_providers"] == ["zammad", "servicenow"]
    assert provider_result["enabled_providers"] == ["servicenow"]
    assert provider_result["selected_providers"] == ["servicenow"]
    assert provider_result["providers"][0]["count"] == 3
    # Runtime configuration flags cannot bypass the selected Ticketing source.
    assert both_enabled["enabled_providers"] == ["servicenow"]
    assert both_enabled["selected_providers"] == ["servicenow"]
    assert zammad_only["enabled_providers"] == ["zammad"]
    assert zammad_only["selected_providers"] == ["zammad"]
    assert both_disabled["enabled_providers"] == ["zammad"]
    assert both_disabled["selected_providers"] == ["zammad"]


def test_failed_stage_does_not_advance_its_cursor_or_rollback_other_stages(
    client: TestClient, monkeypatch
) -> None:
    auth_headers = headers(client)
    created = client.post(
        "/api/v1/servicenow/configurations",
        headers=auth_headers,
        json={
            "instance_url": "https://instance.service-now.com",
            "username": "api-reader",
            "password": "service-now-stage-failure-test",
        },
    ).json()

    async def empty(_client, _after=None):
        return []

    async def changes_fail(_client, _after=None):
        from app.application.services.servicenow import ServiceNowError

        raise ServiceNowError("PERMISSION_DENIED", "ServiceNow denied change_request.", 403)

    async def journals(_client, _incident_id, _after=None):
        return []

    monkeypatch.setattr(ServiceNowClient, "list_configuration_items", empty)
    monkeypatch.setattr(ServiceNowClient, "list_ci_relationships", empty)
    monkeypatch.setattr(ServiceNowClient, "list_incidents", empty)
    monkeypatch.setattr(ServiceNowClient, "list_incident_updates", journals)
    monkeypatch.setattr(ServiceNowClient, "list_problems", empty)
    monkeypatch.setattr(ServiceNowClient, "list_changes", changes_fail)
    response = client.post(
        f"/api/v1/servicenow/configurations/{created['id']}/sync", headers=auth_headers
    )
    assert response.status_code == 200
    assert "changes" in response.json()["stage_errors"]

    async def cursors():
        async with session_factory() as session:
            rows = (await session.scalars(select(ServiceNowSyncCursorModel))).all()
            return {row.record_type: row for row in rows}

    rows = asyncio.run(cursors())
    assert rows["incidents"].cursor_at is not None
    assert rows["incidents"].last_error is None
    assert rows["changes"].cursor_at is None
    assert "denied change_request" in rows["changes"].last_error


def test_servicenow_sync_respects_independent_selected_capabilities(
    client: TestClient, monkeypatch
) -> None:
    auth_headers = headers(client)
    created = client.post(
        "/api/v1/servicenow/configurations",
        headers=auth_headers,
        json={
            "instance_url": "https://instance.service-now.com",
            "username": "api-reader",
            "password": "service-now-capability-test",
        },
    ).json()
    calls: list[str] = []

    async def configuration_items(_client, _after=None):
        calls.append("configuration_items")
        return []

    async def relationships(_client, _after=None):
        calls.append("relationships")
        return []

    async def incidents(_client, _after=None):
        calls.append("incidents")
        return []

    async def problems(_client, _after=None):
        calls.append("problems")
        return []

    async def changes(_client, _after=None):
        calls.append("changes")
        return []

    monkeypatch.setattr(ServiceNowClient, "list_configuration_items", configuration_items)
    monkeypatch.setattr(ServiceNowClient, "list_ci_relationships", relationships)
    monkeypatch.setattr(ServiceNowClient, "list_incidents", incidents)
    monkeypatch.setattr(ServiceNowClient, "list_problems", problems)
    monkeypatch.setattr(ServiceNowClient, "list_changes", changes)

    async def select_only(stream: str) -> None:
        async with session_factory() as session:
            configuration = await session.get(ServiceNowConfigurationModel, UUID(created["id"]))
            assert configuration is not None
            activations = list(
                (
                    await session.scalars(
                        select(IntegrationStreamActivationModel).where(
                            IntegrationStreamActivationModel.integration_id
                            == configuration.integration_id
                        )
                    )
                ).all()
            )
            assert {activation.stream for activation in activations} == {"ticketing", "cmdb"}
            for activation in activations:
                activation.enabled = activation.stream == stream
                activation.active = activation.stream == stream
            configuration.enabled = True
            await session.commit()

    asyncio.run(select_only("cmdb"))
    cmdb_sync = client.post(
        f"/api/v1/servicenow/configurations/{created['id']}/sync", headers=auth_headers
    )
    assert cmdb_sync.status_code == 200, cmdb_sync.text
    assert cmdb_sync.json()["selected_capabilities"] == ["cmdb"]
    assert calls == ["configuration_items", "relationships"]

    calls.clear()
    asyncio.run(select_only("ticketing"))
    ticketing_sync = client.post(
        f"/api/v1/servicenow/configurations/{created['id']}/sync", headers=auth_headers
    )
    assert ticketing_sync.status_code == 200, ticketing_sync.text
    assert ticketing_sync.json()["selected_capabilities"] == ["ticketing"]
    assert calls == ["incidents", "problems", "changes"]


def test_cmdb_records_endpoint_rejects_another_connector_configuration(
    client: TestClient,
) -> None:
    auth_headers = headers(client)

    async def create_other_connector_configuration() -> UUID:
        async with session_factory() as session:
            integration = ConnectorIntegrationModel(
                connector_id="other-connector",
                integration_type="servicenow",
                display_name="Other ServiceNow",
                category="Ticketing / CMDB",
                enabled=True,
                status="healthy",
                capabilities_json={"cmdb": True, "incidents": True},
            )
            session.add(integration)
            await session.flush()
            configuration = ServiceNowConfigurationModel(
                integration_id=integration.id,
                instance_url="https://other.service-now.com",
                username="api-reader",
                encrypted_password="not-read-by-this-endpoint",
                enabled=True,
            )
            session.add(configuration)
            await session.commit()
            return configuration.id

    other_id = asyncio.run(create_other_connector_configuration())
    response = client.get(
        f"/api/v1/servicenow/configurations/{other_id}/cmdb",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_cmdb_records_endpoint_returns_empty_state_before_first_sync(
    client: TestClient,
) -> None:
    auth_headers = headers(client)
    created = client.post(
        "/api/v1/servicenow/configurations",
        headers=auth_headers,
        json={
            "instance_url": "https://instance.service-now.com",
            "username": "api-reader",
            "password": "service-now-empty-state-secret",
        },
    )
    assert created.status_code == 201
    response = client.get(
        f"/api/v1/servicenow/configurations/{created.json()['id']}/cmdb",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total_cis"] == 0
