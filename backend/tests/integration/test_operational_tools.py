from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from app.application.services.operational_tools import (
    OperationalToolExecutor,
    _health_assessment,
)
from app.core.config import get_settings
from app.domain.ports.saas import OperationalToolRequest
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import (
    InventoryAssetModel,
    InventoryObservationModel,
    PrometheusConfigurationModel,
)
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.security.secrets import SecretEncryptionService


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def _request(tool_name: str, arguments: dict) -> OperationalToolRequest:
    return OperationalToolRequest(
        id=uuid4(),
        tool_name=tool_name,
        arguments=arguments,
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        claim_token="claim-token-that-is-long-enough",
    )


@pytest.mark.asyncio
async def test_inventory_tools_count_lookup_status_filter_and_tenant_local_data():
    await _reset_database()
    async with session_factory() as session:
        linux = InventoryAssetModel(
            canonical_name="util001.example.test",
            hostname="util001",
            fqdn="util001.example.test",
            primary_ip="10.20.30.40",
            operating_system="Red Hat Enterprise Linux 9",
            environment="production",
            lifecycle_status="active",
        )
        windows = InventoryAssetModel(
            canonical_name="win001",
            hostname="win001",
            primary_ip="10.20.30.50",
            operating_system="Windows Server 2022",
            environment="test",
            lifecycle_status="active",
        )
        session.add_all([linux, windows])
        await session.flush()
        session.add(
            InventoryObservationModel(
                asset_id=linux.id,
                source_type="prometheus",
                source_record_id="prom-util001",
                observed_fields_json={"health": "up"},
                raw_reference="prometheus:test",
                raw_checksum="a" * 64,
                observed_at=datetime.now(UTC),
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                status="observed",
            )
        )
        await session.commit()
        executor = OperationalToolExecutor(
            session,
            get_settings(),
            SecretEncryptionService(get_settings().encryption_key),
        )

        linux_count = await executor.execute(
            _request("count_assets", {"os_family": "linux"})
        )
        total = await executor.execute(_request("get_inventory_summary", {}))
        lookup = await executor.execute(
            _request("get_asset_details", {"identifier": "UTIL001"})
        )
        fqdn = await executor.execute(
            _request("get_asset_details", {"identifier": "util001.example.test"})
        )
        status = await executor.execute(
            _request("get_asset_status", {"identifier": "util001"})
        )
        missing = await executor.execute(
            _request(
                "search_assets",
                {"missing_prometheus": True, "limit": 50},
            )
        )

        assert linux_count["count"] == 1
        assert total["total_count"] == 2
        assert lookup["asset"]["primary_ip"] == "10.20.30.40"
        assert fqdn["asset"]["id"] == lookup["asset"]["id"]
        assert status["asset"]["reachable"] is True
        assert status["assessment"]["overall_health"] == "unknown"
        assert [asset["hostname"] for asset in missing["assets"]] == ["win001"]


@pytest.mark.asyncio
async def test_utilization_preserves_zero_and_unavailable_and_rejects_promql(monkeypatch):
    await _reset_database()
    async with session_factory() as session:
        asset = InventoryAssetModel(
            canonical_name="util001",
            hostname="util001",
            operating_system="Linux",
        )
        session.add(asset)
        await session.commit()
        executor = OperationalToolExecutor(
            session,
            get_settings(),
            SecretEncryptionService(get_settings().encryption_key),
        )

        async def utilization(_asset):
            return {
                "asset_id": str(asset.id),
                "asset": "util001",
                "cpu_percent": 0.0,
                "memory_percent": None,
                "disk_percent": None,
                "metric_timestamp": datetime.now(UTC),
                "unavailable_reason": None,
            }

        monkeypatch.setattr(executor.prometheus, "asset_utilization", utilization)
        result = await executor.execute(
            _request("get_asset_utilization", {"identifier": "util001"})
        )
        assert result["utilization"]["cpu_percent"] == 0.0
        assert result["utilization"]["memory_percent"] is None

        with pytest.raises(ValueError):
            await executor.execute(
                _request(
                    "get_asset_utilization",
                    {
                        "identifier": "util001",
                        "promql": "up or vector(1)",
                    },
                )
            )


@pytest.mark.asyncio
async def test_utilization_uses_correlated_instance_and_valid_re2_promql(monkeypatch):
    await _reset_database()
    now = datetime.now(UTC)
    timestamp = now.timestamp()
    async with session_factory() as session:
        asset = InventoryAssetModel(
            canonical_name="util001.demo.internal",
            hostname="util001",
            fqdn="util001.demo.internal",
            primary_ip="172.16.165.12",
            operating_system="Linux",
        )
        configuration = PrometheusConfigurationModel(
            name="prometheus",
            base_url="http://prometheus.test:9090",
            enabled=True,
            last_successful_scan_at=now,
        )
        session.add_all([asset, configuration])
        await session.flush()
        session.add_all(
            [
                InventoryObservationModel(
                    asset_id=asset.id,
                    source_type="prometheus",
                    source_record_id="node-target",
                    observed_fields_json={
                        "instance": "172.16.165.12:9100",
                        "job": "linux-node",
                        "health": "up",
                        "last_scrape": now.isoformat(),
                    },
                    raw_reference="prometheus:test",
                    raw_checksum="a" * 64,
                    observed_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    status="observed",
                ),
                InventoryObservationModel(
                    asset_id=asset.id,
                    source_type="prometheus",
                    source_record_id="process-target",
                    observed_fields_json={
                        "instance": "172.16.165.12:9256",
                        "job": "linux-process",
                        "health": "up",
                        "last_scrape": now.isoformat(),
                    },
                    raw_reference="prometheus:test",
                    raw_checksum="b" * 64,
                    observed_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    status="observed",
                ),
            ]
        )
        await session.commit()
        executor = OperationalToolExecutor(
            session,
            get_settings(),
            SecretEncryptionService(get_settings().encryption_key),
        )
        queries: list[str] = []

        async def request(_configuration, path):
            query = parse_qs(urlparse(path).query)["query"][0]
            queries.append(query)
            assert "(?:" not in query
            assert "!~=" not in query
            assert r"172\\.16\\.165\\.12:9100" in query
            if "node_filesystem_avail_bytes" in query and "max by" not in query:
                return {
                    "data": {
                        "result": [
                            {
                                "metric": {
                                    "mountpoint": "/",
                                    "device": "/dev/root",
                                    "fstype": "ext4",
                                },
                                "value": [timestamp, "82.5"],
                            }
                        ]
                    }
                }
            if "namedprocess_namegroup_cpu" in query:
                return {
                    "data": {
                        "result": [
                            {
                                "metric": {"groupname": "prometheus"},
                                "value": [timestamp, "3.5"],
                            }
                        ]
                    }
                }
            if "namedprocess_namegroup_memory" in query:
                return {
                    "data": {
                        "result": [
                            {
                                "metric": {"groupname": "prometheus"},
                                "value": [timestamp, str(128 * 1024 * 1024)],
                            }
                        ]
                    }
                }
            values = {
                "count by (instance)": "4",
                "node_cpu_seconds_total": "0",
                "node_memory_MemAvailable_bytes": "64",
                "max by (instance)": "82.5",
                "node_load1": "1.25",
            }
            value = next(
                (number for marker, number in values.items() if marker in query),
                "0",
            )
            return {"data": {"result": [{"metric": {}, "value": [timestamp, value]}]}}

        monkeypatch.setattr(executor.prometheus, "_request", request)
        result = await executor.execute(
            _request("get_asset_utilization", {"identifier": "util001"})
        )
        utilization = result["utilization"]

        assert utilization["cpu_percent"] == 0.0
        assert utilization["load_average_1m"] == 1.25
        assert utilization["cpu_count"] == 4.0
        assert utilization["disk_percent"] == 82.5
        assert utilization["filesystems"][0]["mountpoint"] == "/"
        assert utilization["top_cpu_processes"][0]["name"] == "prometheus"
        assert utilization["top_memory_processes"][0]["memory_bytes"] == 128 * 1024 * 1024
        assert utilization["error_code"] is None
        assert queries


@pytest.mark.asyncio
async def test_utilization_returns_specific_mapping_error_without_target():
    await _reset_database()
    async with session_factory() as session:
        asset = InventoryAssetModel(
            canonical_name="util001",
            hostname="util001",
            operating_system="Linux",
        )
        session.add_all(
            [
                asset,
                PrometheusConfigurationModel(
                    name="prometheus",
                    base_url="http://prometheus.test:9090",
                    enabled=True,
                ),
            ]
        )
        await session.commit()
        executor = OperationalToolExecutor(
            session,
            get_settings(),
            SecretEncryptionService(get_settings().encryption_key),
        )

        result = await executor.execute(
            _request("get_asset_utilization", {"identifier": "util001"})
        )

        assert result["utilization"]["error_code"] == "PROMETHEUS_TARGET_NOT_FOUND"
        assert "hostname could not be mapped" in result["utilization"]["unavailable_reason"]


@pytest.mark.asyncio
async def test_utilization_distinguishes_mapping_scrape_and_node_exporter_errors(
    monkeypatch,
):
    await _reset_database()
    now = datetime.now(UTC)
    async with session_factory() as session:
        assets = {
            name: InventoryAssetModel(
                canonical_name=name,
                hostname=name,
                operating_system="Linux",
            )
            for name in ("unmapped", "never-scraped", "no-node-metrics")
        }
        session.add_all(
            [
                *assets.values(),
                PrometheusConfigurationModel(
                    name="prometheus",
                    base_url="http://prometheus.test:9090",
                    enabled=True,
                    last_successful_scan_at=now,
                ),
            ]
        )
        await session.flush()
        observations = [
            (
                "unmapped",
                {"health": "up", "last_scrape": now.isoformat()},
            ),
            (
                "never-scraped",
                {"health": "unknown", "instance": "never-scraped:9100"},
            ),
            (
                "no-node-metrics",
                {
                    "health": "up",
                    "instance": "no-node-metrics:9100",
                    "last_scrape": now.isoformat(),
                },
            ),
        ]
        for index, (name, fields) in enumerate(observations):
            session.add(
                InventoryObservationModel(
                    asset_id=assets[name].id,
                    source_type="prometheus",
                    source_record_id=f"target-{index}",
                    observed_fields_json=fields,
                    raw_reference="prometheus:test",
                    raw_checksum=str(index) * 64,
                    observed_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    status="observed",
                )
            )
        await session.commit()
        executor = OperationalToolExecutor(
            session,
            get_settings(),
            SecretEncryptionService(get_settings().encryption_key),
        )

        async def empty_result(_configuration, _path):
            return {"data": {"result": []}}

        monkeypatch.setattr(executor.prometheus, "_request", empty_result)
        expected = {
            "unmapped": "HOSTNAME_MAPPING_FAILED",
            "never-scraped": "HOST_NEVER_SCRAPED",
            "no-node-metrics": "NODE_EXPORTER_METRICS_NOT_FOUND",
        }
        for identifier, error_code in expected.items():
            result = await executor.execute(
                _request(
                    "get_asset_utilization",
                    {"identifier": identifier},
                )
            )
            assert result["utilization"]["error_code"] == error_code


def test_health_assessment_applies_documented_thresholds():
    assessment = _health_assessment(
        {"reachable": True},
        {
            "cpu_percent": 91.0,
            "memory_percent": 82.0,
            "load_average_1m": 5.0,
            "cpu_count": 4,
            "filesystems": [
                {"mountpoint": "/", "used_percent": 81.0},
                {"mountpoint": "/data", "used_percent": 92.0},
            ],
            "error_code": None,
        },
    )

    assert assessment["overall_health"] == "critical"
    assert any("CPU utilization is 91.00%" in item for item in assessment["evidence"])
    assert any("Filesystem /data is 92.00%" in item for item in assessment["evidence"])
    assert assessment["thresholds"]["cpu_critical_percent"] == 90


def test_performance_assessment_excludes_historical_unrelated_log_noise():
    now = datetime.now(UTC)
    assessment = _health_assessment(
        {"reachable": True},
        {
            "cpu_percent": 9.0,
            "memory_percent": 71.0,
            "load_average_1m": 0.2,
            "cpu_count": 2,
            "filesystems": [{"mountpoint": "/", "used_percent": 20.0}],
            "metric_timestamp": now,
            "error_code": None,
        },
        {
            "available": True,
            "evidence": [
                {
                    "source": "loki",
                    "category": "errors",
                    "severity": "error",
                    "observed_at": (now - timedelta(hours=23)).isoformat(),
                    "summary": "failed to validate image signature",
                }
            ],
        },
        "performance",
    )

    assert assessment["overall_health"] == "healthy"
    assert assessment["relevant_log_evidence"] == []
    assert len(assessment["unrelated_log_evidence"]) == 1
    assert "do not appear related" in assessment["conclusion"]
    assert "No evidence was found linking" in " ".join(assessment["evidence"])
    assert assessment["recommendations"] == []


def test_performance_assessment_correlates_aligned_oom_with_high_utilization():
    now = datetime.now(UTC)
    assessment = _health_assessment(
        {"reachable": True},
        {
            "cpu_percent": 94.0,
            "memory_percent": 93.0,
            "load_average_1m": 3.5,
            "cpu_count": 2,
            "filesystems": [],
            "metric_timestamp": now,
            "error_code": None,
        },
        {
            "available": True,
            "evidence": [
                {
                    "source": "loki",
                    "category": "oom",
                    "severity": "critical",
                    "observed_at": (now - timedelta(minutes=1)).isoformat(),
                    "summary": "java.lang.OutOfMemoryError: Java heap space",
                }
            ],
        },
        "performance",
    )

    assert assessment["overall_health"] == "critical"
    assert assessment["relevant_log_evidence"][0]["category"] == "oom"
    assert assessment["correlations"]
    assert "plausible contributing factor" in assessment["conclusion"]
    assert any("memory pressure" in item for item in assessment["recommendations"])


def test_performance_assessment_keeps_cause_unknown_without_relevant_logs():
    assessment = _health_assessment(
        {"reachable": True},
        {
            "cpu_percent": 95.0,
            "memory_percent": 50.0,
            "load_average_1m": 0.5,
            "cpu_count": 2,
            "filesystems": [],
            "metric_timestamp": datetime.now(UTC),
            "error_code": None,
        },
        {"available": True, "evidence": []},
        "performance",
    )

    assert assessment["overall_health"] == "critical"
    assert "cause remains unknown" in assessment["conclusion"]
    assert all("network" not in item.casefold() for item in assessment["recommendations"])


def test_timeline_assessment_explains_recovery_sequence_from_timestamps():
    metric_time = datetime.now(UTC)
    assessment = _health_assessment(
        {"reachable": True},
        {
            "cpu_percent": 12.0,
            "memory_percent": 55.0,
            "disk_percent": 40.0,
            "load_average_1m": 0.2,
            "cpu_count": 4,
            "metric_timestamp": metric_time.isoformat(),
        },
        {
            "available": True,
            "evidence": [
                {
                    "category": "restarts",
                    "observed_at": (
                        metric_time - timedelta(minutes=5)
                    ).isoformat(),
                    "summary": "Application restarted.",
                }
            ],
        },
        "timeline",
    )

    assert assessment["mode"] == "timeline"
    assert len(assessment["relevant_log_evidence"]) == 1
    assert "followed by a Prometheus observation" in assessment["conclusion"]
    assert "No later relevant failure" in assessment["conclusion"]
