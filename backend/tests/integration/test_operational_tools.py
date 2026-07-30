from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.services.operational_tools import OperationalToolExecutor
from app.core.config import get_settings
from app.domain.ports.saas import OperationalToolRequest
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import (
    InventoryAssetModel,
    InventoryObservationModel,
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
