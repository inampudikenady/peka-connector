import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import engine
from app.main import app

PASSWORD = "Strong!IntegrationApiPass123"


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


def _headers(client: TestClient) -> dict[str, str]:
    assert (
        client.post(
            "/api/v1/auth/bootstrap",
            json={"username": "admin", "password": PASSWORD, "confirm_password": PASSWORD},
        ).status_code
        == 201
    )
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_catalog_exposes_servicenow_without_provider_binding_api(
    client: TestClient,
) -> None:
    headers = _headers(client)
    catalog = client.get("/api/v1/integrations/catalog", headers=headers)
    assert catalog.status_code == 200
    types = {item["integration_type"] for item in catalog.json()}
    assert {"zammad", "servicenow", "solarwinds", "vmware_vcenter"} <= types
    servicenow = next(item for item in catalog.json() if item["integration_type"] == "servicenow")
    assert servicenow["available"] is True
    assert servicenow["integration_type"] == "servicenow"
    assert client.get("/api/v1/provider-bindings", headers=headers).status_code == 404


def test_integration_api_rejects_connector_or_tenant_identity_override(
    client: TestClient,
) -> None:
    headers = _headers(client)
    response = client.post(
        "/api/v1/integrations",
        headers={**headers, "X-Tenant-ID": "other-tenant"},
        json={
            "integration_type": "solarwinds",
            "display_name": "SolarWinds",
            "connector_id": "other-connector",
            "tenant_id": "other-tenant",
        },
    )
    assert response.status_code == 422


def test_stream_switch_api_returns_explicit_confirmation_contract(client: TestClient) -> None:
    headers = _headers(client)
    servicenow = client.post(
        "/api/v1/integrations",
        headers=headers,
        json={
            "integration_type": "servicenow",
            "display_name": "ServiceNow",
            "enabled": True,
        },
    ).json()
    zammad = client.post(
        "/api/v1/integrations",
        headers=headers,
        json={
            "integration_type": "zammad",
            "display_name": "Zammad",
            "enabled": True,
        },
    ).json()

    conflict = client.post(
        f"/api/v1/integrations/{zammad['id']}/streams/ticketing/select",
        headers=headers,
        json={"confirmed": False},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "SOURCE_SWITCH_CONFIRMATION_REQUIRED",
        "message": (
            "ServiceNow is currently selected as the Ticketing source. Switching to Zammad "
            "will stop PEKA from using ServiceNow for Ticketing and select Zammad. Saved "
            "configuration will be retained."
        ),
        "stream": "ticketing",
        "current_source": "ServiceNow",
        "requested_source": "Zammad",
    }
    switched = client.post(
        f"/api/v1/integrations/{zammad['id']}/streams/ticketing/select",
        headers=headers,
        json={"confirmed": True},
    )
    assert switched.status_code == 200
    streams = client.get("/api/v1/integrations/streams", headers=headers).json()
    ticketing = next(item for item in streams if item["stream"] == "ticketing")
    assert ticketing["selected_source"] == "zammad"
    sources = {item["source_key"]: item for item in ticketing["sources"]}
    assert sources["servicenow"]["configured"] is True
    assert sources["servicenow"]["selected"] is False
    assert sources["zammad"]["selected"] is True
    assert servicenow["id"] == sources["servicenow"]["integration_id"]


def test_configuring_zammad_cannot_bypass_selected_servicenow(client: TestClient) -> None:
    headers = _headers(client)
    servicenow = client.post(
        "/api/v1/servicenow/configurations",
        headers=headers,
        json={
            "name": "ServiceNow",
            "instance_url": "https://instance.service-now.com",
            "username": "api-reader",
            "password": "saved-servicenow-secret",
        },
    )
    assert servicenow.status_code == 201, servicenow.text
    zammad = client.post(
        "/api/v1/zammad/configurations",
        headers=headers,
        json={
            "name": "Zammad",
            "base_url": "https://tickets.example.test",
            "access_token": "saved-zammad-token",
            "enabled": True,
        },
    )
    assert zammad.status_code == 201, zammad.text
    assert zammad.json()["enabled"] is False

    streams = client.get("/api/v1/integrations/streams", headers=headers).json()
    ticketing = next(item for item in streams if item["stream"] == "ticketing")
    sources = {item["source_key"]: item for item in ticketing["sources"]}
    assert sources["servicenow"]["selected"] is True
    assert sources["zammad"]["selected"] is False

    conflict = client.post(
        f"/api/v1/integrations/{sources['zammad']['integration_id']}"
        "/streams/ticketing/select",
        headers=headers,
        json={"confirmed": False},
    )
    assert conflict.status_code == 409
    switched = client.post(
        f"/api/v1/integrations/{sources['zammad']['integration_id']}"
        "/streams/ticketing/select",
        headers=headers,
        json={"confirmed": True},
    )
    assert switched.status_code == 200
    ticketing = next(
        item
        for item in client.get("/api/v1/integrations/streams", headers=headers).json()
        if item["stream"] == "ticketing"
    )
    assert ticketing["selected_source"] == "zammad"
    assert len(client.get("/api/v1/servicenow/configurations", headers=headers).json()) == 1
