"""Allow-listed operational tool execution and outbound SaaS RPC worker."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.inventory import InventoryService
from app.application.services.prometheus import PrometheusService
from app.core.config import Settings
from app.domain.ports.saas import (
    OperationalToolRequest,
    OperationalToolResult,
    PEKASaaSClient,
)
from app.infrastructure.database.models.inventory import InventoryAssetModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.security.secrets import SecretEncryptionService


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CountArguments(_Arguments):
    os_family: str | None = Field(default=None, max_length=100)


class SearchArguments(_Arguments):
    identifier: str | None = Field(default=None, max_length=500)
    os_family: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=255)
    missing_prometheus: bool | None = None
    limit: int = Field(default=25, ge=1, le=50)


class AssetArguments(_Arguments):
    identifier: str = Field(min_length=1, max_length=500)


class EmptyArguments(_Arguments):
    pass


class OperationalToolExecutor:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        secrets: SecretEncryptionService,
    ) -> None:
        self.session = session
        self.inventory = InventoryService(session)
        self.prometheus = PrometheusService(session, secrets, settings)

    async def execute(self, request: OperationalToolRequest) -> dict[str, Any]:
        if request.tool_name == "get_inventory_summary":
            EmptyArguments.model_validate(request.arguments)
            return await self.inventory.inventory_summary()
        if request.tool_name == "count_assets":
            count_arguments = CountArguments.model_validate(request.arguments)
            return await self.inventory.count_assets(count_arguments.os_family)
        if request.tool_name == "search_assets":
            search_arguments = SearchArguments.model_validate(request.arguments)
            assets = await self.inventory.find_assets(**search_arguments.model_dump())
            return {
                "match_status": "found" if assets else "not_found",
                "assets": assets,
                "count": len(assets),
            }
        if request.tool_name in {
            "get_asset_details",
            "get_asset_status",
            "get_asset_utilization",
        }:
            asset_arguments = AssetArguments.model_validate(request.arguments)
            matches = await self.inventory.find_assets(
                identifier=asset_arguments.identifier, limit=20
            )
            if not matches:
                return {
                    "match_status": "not_found",
                    "identifier": asset_arguments.identifier,
                    "candidates": [],
                }
            if len(matches) > 1:
                return {
                    "match_status": "ambiguous",
                    "identifier": asset_arguments.identifier,
                    "candidates": matches,
                }
            asset = matches[0]
            if request.tool_name == "get_asset_details":
                return {"match_status": "found", "asset": asset}
            asset_id = UUID(asset["id"])
            if request.tool_name == "get_asset_status":
                status = await self.inventory.operational_asset_status(asset_id)
                return {"match_status": "found", "asset": status}
            model = await self.session.get(InventoryAssetModel, asset_id)
            if model is None:
                return {
                    "match_status": "not_found",
                    "identifier": asset_arguments.identifier,
                    "candidates": [],
                }
            utilization = await self.prometheus.asset_utilization(model)
            return {"match_status": "found", "utilization": utilization}
        raise ValueError("Unsupported operational tool")


class OperationalToolWorker:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        client: PEKASaaSClient,
        secrets: SecretEncryptionService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.client = client
        self.secrets = secrets

    async def run_once(self) -> bool:
        product = await SqlAlchemyOperationsRepository(self.session).get_settings()
        if (
            not product.connector_id
            or not product.saas_url
            or not product.encrypted_connector_secret
        ):
            return False
        connector_id = UUID(product.connector_id)
        connector_secret = self.secrets.decrypt(product.encrypted_connector_secret)
        request = await self.client.claim_operational_tool(
            product.saas_url, connector_id, connector_secret
        )
        if request is None:
            return False
        try:
            result = await OperationalToolExecutor(
                self.session, self.settings, self.secrets
            ).execute(request)
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="completed",
                result=result,
            )
        except (ValidationError, ValueError) as exc:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="INVALID_TOOL_REQUEST",
                error_message=str(exc)[:500],
            )
        except Exception:
            submission = OperationalToolResult(
                claim_token=request.claim_token,
                status="failed",
                error_code="TOOL_EXECUTION_FAILED",
                error_message="The connector could not execute the operational tool.",
            )
        await self.client.submit_operational_tool_result(
            product.saas_url,
            connector_id,
            connector_secret,
            request.id,
            submission,
        )
        return True
