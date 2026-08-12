from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.application.services.operational_tools import NormalizedTicketingArguments
from app.application.services.servicenow import (
    ServiceNowClient,
    ServiceNowError,
    ci_aliases,
    latest_meaningful_update,
    validate_instance_url,
)
from app.infrastructure.database.models.servicenow import ServiceNowConfigurationModel


def configuration() -> ServiceNowConfigurationModel:
    return ServiceNowConfigurationModel(
        integration_id=uuid4(),
        instance_url="https://instance.service-now.com",
        username="api-reader",
        encrypted_password="encrypted",
        page_size=2,
        request_timeout_seconds=2,
    )


def test_configuration_validation_ci_aliases_and_human_update_selection() -> None:
    assert validate_instance_url(" https://instance.service-now.com/// ") == (
        "https://instance.service-now.com"
    )
    with pytest.raises(ServiceNowError):
        validate_instance_url("https://user:password@instance.service-now.com?secret=value")
    assert ci_aliases(
        {
            "name": "UTIL001",
            "fqdn": "util001.demo.internal",
            "ip_address": "172.16.165.12",
        }
    ) == ["172.16.165.12", "util001", "util001.demo.internal"]
    latest = latest_meaningful_update(
        [
            {
                "sys_id": "system",
                "element": "work_notes",
                "value": "Automated state update",
                "sys_created_by": "system",
                "sys_created_on": "2026-08-04 10:00:00",
            },
            {
                "sys_id": "comment",
                "element": "comments",
                "value": "Customer confirmed impact",
                "sys_created_by": "alice",
                "sys_created_on": "2026-08-04 09:00:00",
            },
            {
                "sys_id": "work-note",
                "element": "work_notes",
                "value": "Operator isolated the failed service",
                "sys_created_by": "bob",
                "sys_created_on": "2026-08-04 08:00:00",
            },
        ]
    )
    assert latest and latest["sys_id"] == "work-note"


def test_ticket_provider_identifiers_are_canonical() -> None:
    assert NormalizedTicketingArguments.model_validate(
        {"providers": ["servicenow", "zammad"]}
    ).providers == ["servicenow", "zammad"]
    with pytest.raises(ValidationError):
        NormalizedTicketingArguments.model_validate({"providers": ["service_now"]})
    with pytest.raises(ValidationError):
        NormalizedTicketingArguments.model_validate({"providers": ["service-now"]})


@pytest.mark.asyncio
async def test_table_api_paginates_and_limits_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params["sysparm_offset"])
        rows = (
            [
                {"sys_id": "a" * 32, "number": "INC1"},
                {"sys_id": "b" * 32, "number": "INC2"},
            ]
            if offset == 0
            else [{"sys_id": "c" * 32, "number": "INC3"}]
        )
        return httpx.Response(200, json={"result": rows})

    client = ServiceNowClient(configuration(), "secret", httpx.MockTransport(handler))
    rows = await client.list_incidents()
    assert [row["number"] for row in rows] == ["INC1", "INC2", "INC3"]
    assert len(requests) == 2
    assert "description" in requests[0].url.params["sysparm_fields"]
    assert requests[0].url.params["sysparm_exclude_reference_link"] == "true"
    assert "secret" not in str(requests[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTHENTICATION_FAILED"),
        (403, "PERMISSION_DENIED"),
        (404, "TABLE_OR_RECORD_NOT_FOUND"),
    ],
)
async def test_table_api_maps_auth_permission_and_missing_table_errors(
    status: int, code: str
) -> None:
    client = ServiceNowClient(
        configuration(),
        "never-return-this-password",
        httpx.MockTransport(lambda _request: httpx.Response(status, json={"error": {}})),
    )
    with pytest.raises(ServiceNowError) as caught:
        await client.list_incidents()
    assert caught.value.code == code
    assert "never-return-this-password" not in str(caught.value)


@pytest.mark.asyncio
async def test_table_api_retries_rate_limits_and_server_errors() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {}})
        if attempts == 2:
            return httpx.Response(503, json={"error": {}})
        return httpx.Response(200, json={"result": []})

    client = ServiceNowClient(configuration(), "secret", httpx.MockTransport(handler))
    assert await client.list_incidents(datetime.now(UTC)) == []
    assert attempts == 3
