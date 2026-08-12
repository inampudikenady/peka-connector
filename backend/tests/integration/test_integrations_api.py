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
