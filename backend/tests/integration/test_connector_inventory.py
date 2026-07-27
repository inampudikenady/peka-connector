import asyncio
import io
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.application.services.prometheus import PrometheusService
from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import engine
from app.main import app

PASSWORD = "Strong!LocalPass123"


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
    created = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": PASSWORD, "confirm_password": PASSWORD},
    )
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload_csv(
    client: TestClient,
    headers: dict[str, str],
    content: bytes,
    dataset_name: str = "Servers",
    dataset_id: str | None = None,
) -> dict[str, Any]:
    data = {"dataset_name": dataset_name}
    if dataset_id:
        data["dataset_id"] = dataset_id
    response = client.post(
        "/api/v1/cmdb/upload",
        headers=headers,
        data=data,
        files={"file": ("servers.csv", content, "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _import(
    client: TestClient,
    headers: dict[str, str],
    upload: dict[str, Any],
    mapping: dict[str, str],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/cmdb/versions/{upload['version_id']}/import",
        headers=headers,
        json={"sheet_name": upload["sheet_name"], "header_row": 1, "mapping": mapping},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _xlsx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
            <Default Extension="xml" ContentType="application/xml"/>
            <Override PartName="/xl/workbook.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
            <Override PartName="/xl/worksheets/sheet1.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
            <Override PartName="/xl/worksheets/sheet2.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
            </Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
            <sheets><sheet name="Servers" sheetId="1" r:id="rId1"/>
            <sheet name="Ignored" sheetId="2" r:id="rId2"/></sheets></workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
            <Relationship Id="rId1" Target="worksheets/sheet1.xml"
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
            <Relationship Id="rId2" Target="worksheets/sheet2.xml"
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
            <Relationship Id="external" Target="https://example.invalid/data"
            TargetMode="External" Type="externalLink"/></Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <sheetData>
            <row r="1"><c r="A1" t="inlineStr"><is><t>Hostname</t></is></c>
            <c r="B1" t="inlineStr"><is><t>IP</t></is></c></row>
            <row r="2"><c r="A2" t="inlineStr"><is><t>xlsx01</t></is></c>
            <c r="B2"><f>WEBSERVICE("https://example.invalid")</f><v>10.0.0.8</v></c></row>
            </sheetData></worksheet>""",
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Other</t></is></c></row>
            </sheetData></worksheet>""",
        )
    return buffer.getvalue()


def test_csv_import_replacement_inventory_and_roles(client: TestClient) -> None:
    headers = _headers(client)
    upload = _upload_csv(
        client,
        headers,
        b"Hostname,FQDN,IP,Owner\n WEB01 ,web01.example.com.,10.0.0.7, Platform Team \n,,,Nobody\n",
    )
    imported = _import(
        client,
        headers,
        upload,
        {
            "Hostname": "hostname",
            "FQDN": "fqdn",
            "IP": "primary_ip",
            "Owner": "technical_owner",
        },
    )
    assert imported["valid_rows"] == 1
    assert imported["invalid_rows"] == 1
    records = client.get("/api/v1/cmdb/records?page=1&page_size=25", headers=headers).json()
    assert records["total"] == 2
    valid_record = next(item for item in records["items"] if item["validation_status"] == "valid")
    assert valid_record["normalized_fields"]["hostname"] == "WEB01"
    inventory = client.get("/api/v1/inventory?page=1&page_size=25", headers=headers).json()
    assert inventory["items"][0]["coverage"] == "Unknown — Prometheus not configured"

    replacement = _upload_csv(
        client,
        headers,
        b"Hostname,IP\nweb02,10.0.0.9\n",
        dataset_id=upload["dataset_id"],
    )
    _import(
        client,
        headers,
        replacement,
        {"Hostname": "hostname", "IP": "primary_ip"},
    )
    datasets = client.get("/api/v1/cmdb/datasets", headers=headers).json()
    assert datasets[0]["current_version"] == 2
    assert (
        client.get("/api/v1/cmdb/records?page=1&page_size=25", headers=headers).json()["total"] == 3
    )

    reader_password = "Viewer!StrongPass123"
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "inventory-reader",
            "password": reader_password,
            "confirm_password": reader_password,
            "role": "read_only",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "inventory-reader", "password": reader_password},
    ).json()
    reader = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/cmdb/datasets", headers=reader).status_code == 200
    assert client.get("/api/v1/inventory?page=1&page_size=25", headers=reader).status_code == 200
    assert (
        client.post(
            "/api/v1/cmdb/upload",
            headers=reader,
            data={"dataset_name": "Denied"},
            files={"file": ("denied.csv", b"hostname\nno\n", "text/csv")},
        ).status_code
        == 403
    )


def test_safe_multisheet_xlsx_uses_cached_formula_value(client: TestClient) -> None:
    headers = _headers(client)
    response = client.post(
        "/api/v1/cmdb/upload",
        headers=headers,
        data={"dataset_name": "Workbook"},
        files={
            "file": (
                "inventory.xlsx",
                _xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201, response.text
    upload = response.json()
    assert upload["sheets"] == ["Servers", "Ignored"]
    assert upload["preview_rows"][0] == {"Hostname": "xlsx01", "IP": "10.0.0.8"}
    imported = _import(
        client,
        headers,
        upload,
        {"Hostname": "hostname", "IP": "primary_ip"},
    )
    assert imported["valid_rows"] == 1


def test_prometheus_collection_exact_match_and_manual_decision_persistence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _headers(client)
    upload = _upload_csv(client, headers, b"Hostname,IP\nweb01,10.0.0.7\n")
    _import(client, headers, upload, {"Hostname": "hostname", "IP": "primary_ip"})

    async def fake_request(
        self: PrometheusService, configuration: object, path: str
    ) -> dict[str, Any]:
        if "buildinfo" in path:
            return {"status": "success", "data": {"version": "3.0.0"}}
        return {
            "status": "success",
            "data": {
                "activeTargets": [
                    {
                        "scrapePool": "node",
                        "scrapeUrl": "http://web01:9100/metrics",
                        "globalUrl": "http://prometheus:9090/graph",
                        "labels": {"instance": "web01:9100", "job": "node"},
                        "discoveredLabels": {"__address__": "web01:9100"},
                        "health": "up",
                        "lastScrape": "2026-07-27T12:00:00Z",
                        "lastScrapeDuration": 0.01,
                        "lastError": "",
                    }
                ]
            },
        }

    monkeypatch.setattr(PrometheusService, "_request", fake_request)
    created = client.post(
        "/api/v1/prometheus/configurations",
        headers=headers,
        json={
            "name": "Local Prometheus",
            "base_url": "http://prometheus.internal:9090",
            "auth_type": "none",
            "tls_verify": True,
            "request_timeout_seconds": 5,
            "scan_interval_seconds": 300,
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    configuration_id = created.json()["id"]
    assert (
        client.post(
            f"/api/v1/prometheus/configurations/{configuration_id}/test", headers=headers
        ).status_code
        == 200
    )
    scan = client.post(
        f"/api/v1/prometheus/configurations/{configuration_id}/scan", headers=headers
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["healthy_target_count"] == 1
    inventory = client.get("/api/v1/inventory?page=1&page_size=25", headers=headers).json()
    assert inventory["items"][0]["coverage"] == "Declared and monitored"
    assert inventory["items"][0]["prometheus_health"] == "healthy"

    detail = client.get(f"/api/v1/inventory/{inventory['items'][0]['id']}", headers=headers).json()
    observation = next(
        item for item in detail["observations"] if item["source_type"] == "prometheus"
    )
    rejected = client.post(
        f"/api/v1/inventory/observations/{observation['id']}/correlation",
        headers=headers,
        json={"asset_id": None, "status": "rejected"},
    )
    assert rejected.status_code == 200
    client.post(f"/api/v1/prometheus/configurations/{configuration_id}/scan", headers=headers)
    inventory = client.get("/api/v1/inventory?page=1&page_size=25", headers=headers).json()
    assert any(item["correlation_status"] == "unmatched" for item in inventory["items"])
