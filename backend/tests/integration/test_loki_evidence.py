from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.services.loki import LokiService, _message_matches_category
from app.application.services.operational_tools import OperationalToolExecutor
from app.core.config import get_settings
from app.domain.ports.saas import OperationalToolRequest
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.inventory import (
    InventoryAssetModel,
    LokiConfigurationModel,
)
from app.infrastructure.database.session import engine, session_factory
from app.infrastructure.security.secrets import SecretEncryptionService


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def _request(arguments: dict) -> OperationalToolRequest:
    return OperationalToolRequest(
        id=uuid4(),
        tool_name="get_asset_log_evidence",
        arguments=arguments,
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        claim_token="claim-token-that-is-long-enough",
    )


@pytest.mark.asyncio
async def test_dynamic_loki_discovery_and_asset_evidence_use_fixed_logql(monkeypatch):
    await _reset_database()
    async with session_factory() as session:
        asset = InventoryAssetModel(
            canonical_name="util001.demo.internal",
            hostname="util001",
            fqdn="util001.demo.internal",
            primary_ip="10.20.30.40",
            operating_system="Linux",
        )
        configuration = LokiConfigurationModel(
            name="loki",
            base_url="http://loki.test:3100",
            discovery_lookback_days=1,
            enabled=True,
        )
        session.add_all([asset, configuration])
        await session.commit()
        service = LokiService(
            session,
            SecretEncryptionService(get_settings().encryption_key),
            get_settings(),
        )
        discovery_selectors: list[str] = []

        async def discovery_request(
            _configuration,
            path,
            params=None,
            *,
            require_loki_envelope=True,
        ):
            assert require_loki_envelope is True
            if path == "/loki/api/v1/labels":
                return {"status": "success", "data": ["instance_name", "source"]}
            if "/label/instance_name/" in path:
                return {"status": "success", "data": ["util001.demo.internal"]}
            if "/label/source/" in path:
                return {"status": "success", "data": ["syslog"]}
            assert path == "/loki/api/v1/series"
            discovery_selectors.extend(
                value for key, value in params if key == "match[]"
            )
            return {
                "status": "success",
                "data": [
                    {
                        "instance_name": "util001.demo.internal",
                        "source": "syslog",
                    }
                ],
            }

        monkeypatch.setattr(service, "_request", discovery_request)
        schema = await service.discover(configuration.id)

        assert schema["labels"] == ["instance_name", "source"]
        assert schema["stream_count"] == 1
        assert discovery_selectors == [
            '{instance_name=~".+"}',
            '{source=~".+"}',
        ]

        queries: list[str] = []

        async def query_range(_configuration, query, _start, _end, *, limit):
            queries.append(query)
            assert limit == 5
            return {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {
                                "instance_name": "util001.demo.internal",
                                "source": "syslog",
                            },
                            "values": [
                                [
                                    str(int(datetime.now(UTC).timestamp() * 1_000_000_000)),
                                    "service failed with error code 2",
                                ]
                            ],
                        }
                    ]
                },
            }

        monkeypatch.setattr(service, "_query_range", query_range)
        result = await service.asset_evidence(asset, categories=["errors"])

        assert result["available"] is True
        assert result["counts_by_category"] == {"errors": 1}
        assert result["evidence"][0]["source"] == "loki"
        assert result["matched_streams"][0]["matched_by"][0]["label"] == "instance_name"
        assert queries and queries[0].startswith(
            '{instance_name="util001.demo.internal",source="syslog"} |~ '
        )
        assert "error|fatal|critical|failed|failure" in queries[0]


@pytest.mark.asyncio
async def test_log_tool_rejects_arbitrary_logql_and_preserves_unknown_correlation():
    await _reset_database()
    async with session_factory() as session:
        asset = InventoryAssetModel(canonical_name="util001", hostname="util001")
        session.add_all(
            [
                asset,
                LokiConfigurationModel(
                    name="loki",
                    base_url="http://loki.test:3100",
                    enabled=True,
                    discovered_schema_json={
                        "labels": ["host"],
                        "streams": [{"host": "different-host"}],
                    },
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
            _request(
                {
                    "identifier": "util001",
                    "category": "errors",
                    "lookback_hours": 24,
                }
            )
        )
        logs = result["log_evidence"]
        assert logs["available"] is False
        assert logs["error_code"] == "LOKI_STREAM_NOT_FOUND"
        assert logs["evidence"] == []

        with pytest.raises(ValueError):
            await executor.execute(
                _request(
                    {
                        "identifier": "util001",
                        "category": "errors",
                        "lookback_hours": 24,
                        "logql": '{host=~".+"}',
                    }
                )
            )


def test_loki_message_relevance_rejects_normal_lifecycle_false_positives():
    normal = (
        "Finished update-notifier-download.service - Download data for packages "
        "that failed at package install time."
    )
    assert _message_matches_category("errors", normal) is False
    assert _message_matches_category("application_failures", normal) is False
    assert (
        _message_matches_category(
            "errors",
            'level=error msg="failed to validate image signature"',
        )
        is True
    )
