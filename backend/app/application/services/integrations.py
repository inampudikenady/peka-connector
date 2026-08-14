"""Generic integration lifecycle driven solely by configured enabled integrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integration_catalog import (
    CATALOG_BY_TYPE,
    INTEGRATION_CATALOG,
    SECRET_FIELDS,
    STREAM_SOURCES,
    STREAMS,
)
from app.infrastructure.database.models.integration import (
    ConnectorIntegrationModel,
    IntegrationStreamActivationModel,
)
from app.infrastructure.database.models.inventory import (
    CMDBDatasetModel,
    LokiConfigurationModel,
    PrometheusConfigurationModel,
)
from app.infrastructure.database.models.operations import AuditEventModel, ProductSettingsModel
from app.infrastructure.database.models.servicenow import (
    ServiceNowConfigurationModel,
)
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.models.zammad import (
    ZammadConfigurationModel,
    ZammadTicketModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService


class IntegrationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SourceSwitchConfirmationRequiredError(IntegrationError):
    def __init__(
        self,
        stream: str,
        current_source: str,
        requested_source: str,
    ) -> None:
        super().__init__(
            "SOURCE_SWITCH_CONFIRMATION_REQUIRED",
            f"{current_source} is currently selected as the {stream.title()} source. "
            f"Switching to {requested_source} will stop PEKA from using {current_source} "
            f"for {stream.title()} and select {requested_source}. Saved configuration "
            "will be retained.",
            409,
        )
        self.stream = stream
        self.current_source = current_source
        self.requested_source = requested_source


class IntegrationService:
    def __init__(self, session: AsyncSession, encryption: SecretEncryptionService) -> None:
        self.session = session
        self.encryption = encryption

    async def connector_id(self) -> str:
        product = await self.session.get(ProductSettingsModel, 1)
        if product is None:
            return "local"
        return str(product.connector_id or product.instance_id or "local")

    @staticmethod
    def _stream_sources_for(
        integration_type: str, capabilities: dict[str, bool]
    ) -> tuple[tuple[str, str, str], ...]:
        values = STREAM_SOURCES.get(integration_type, ())
        if integration_type != "servicenow":
            return values
        return tuple(
            item
            for item in values
            if (item[0] == "ticketing" and capabilities.get("incidents", False))
            or (item[0] == "cmdb" and capabilities.get("cmdb", False))
        )

    async def catalog(self) -> list[dict[str, Any]]:
        return [dict(item) for item in INTEGRATION_CATALOG]

    async def bootstrap_legacy_integrations(self) -> None:
        """Represent existing providers without changing or decrypting their secrets."""
        connector_id = await self.connector_id()
        zammad = list((await self.session.scalars(select(ZammadConfigurationModel))).all())
        for configuration in zammad:
            existing = await self.session.scalar(
                select(ConnectorIntegrationModel).where(
                    ConnectorIntegrationModel.legacy_zammad_configuration_id == configuration.id
                )
            )
            if existing is None:
                existing = ConnectorIntegrationModel(
                    connector_id=connector_id,
                    integration_type="zammad",
                    display_name=configuration.name,
                    category="ITSM",
                    enabled=configuration.enabled,
                    status="healthy"
                    if configuration.connection_state == "connected"
                    else "attention",
                    configuration_json={"legacy_configuration_id": str(configuration.id)},
                    capabilities_json={"tickets": True},
                    last_tested_at=configuration.last_successful_test_at,
                    last_successful_test_at=configuration.last_successful_test_at,
                    last_successful_sync_at=configuration.last_successful_sync_at,
                    initial_sync_status="completed"
                    if configuration.last_successful_sync_at
                    else "not_started",
                    last_error=configuration.last_error,
                    legacy_zammad_configuration_id=configuration.id,
                )
                self.session.add(existing)
                await self.session.flush()
            await self.session.execute(
                update(ZammadTicketModel)
                .where(ZammadTicketModel.configuration_id == configuration.id)
                .values(
                    connector_id=connector_id,
                    integration_type="zammad",
                    integration_id=existing.id,
                    source_record_id=ZammadTicketModel.external_id,
                    source_updated_at=ZammadTicketModel.updated_at_source,
                    synced_at=ZammadTicketModel.synchronized_at,
                    cache_status=func.coalesce(ZammadTicketModel.cache_status, "active"),
                )
            )
        await self._bootstrap_non_ticketing(connector_id)
        await self.session.commit()

    async def _bootstrap_non_ticketing(self, connector_id: str) -> None:
        async def add_if_missing(
            integration_type: str,
            display_name: str,
            enabled: bool,
            status: str,
            configuration: dict[str, Any],
            capabilities: dict[str, bool],
            last_sync: datetime | None = None,
            last_error: str | None = None,
        ) -> None:
            legacy_key = str(configuration.get("legacy_id") or integration_type)
            existing = await self.session.scalar(
                select(ConnectorIntegrationModel).where(
                    ConnectorIntegrationModel.connector_id == connector_id,
                    ConnectorIntegrationModel.integration_type == integration_type,
                    ConnectorIntegrationModel.configuration_json["legacy_id"].as_string()
                    == legacy_key,
                )
            )
            if existing is None:
                catalog = CATALOG_BY_TYPE[integration_type]
                self.session.add(
                    ConnectorIntegrationModel(
                        connector_id=connector_id,
                        integration_type=integration_type,
                        display_name=display_name,
                        category=str(catalog["category"]),
                        enabled=enabled,
                        status=status,
                        configuration_json=configuration,
                        capabilities_json=capabilities,
                        last_successful_sync_at=last_sync,
                        initial_sync_status="completed" if last_sync else "not_started",
                        last_error=last_error,
                    )
                )

        for prometheus in (await self.session.scalars(select(PrometheusConfigurationModel))).all():
            await add_if_missing(
                "prometheus",
                prometheus.name,
                prometheus.enabled,
                "healthy" if prometheus.last_successful_scan_at else "attention",
                {"legacy_id": str(prometheus.id)},
                CATALOG_BY_TYPE["prometheus"]["capabilities"],
                prometheus.last_successful_scan_at,
                prometheus.last_error,
            )
        for loki in (await self.session.scalars(select(LokiConfigurationModel))).all():
            await add_if_missing(
                "loki",
                loki.name,
                loki.enabled,
                "healthy" if loki.last_successful_discovery_at else "attention",
                {"legacy_id": str(loki.id)},
                CATALOG_BY_TYPE["loki"]["capabilities"],
                loki.last_successful_discovery_at,
                loki.last_error,
            )
        document_source = await self.session.scalar(
            select(SourceModel).where(SourceModel.system_managed.is_(True)).limit(1)
        )
        if document_source is not None:
            await add_if_missing(
                "documents",
                "Documents",
                document_source.enabled,
                document_source.health_status,
                {"legacy_id": str(document_source.id)},
                {"documents": True},
                document_source.last_success_at,
                document_source.last_error,
            )
        cmdb_count = int(await self.session.scalar(select(func.count(CMDBDatasetModel.id))) or 0)
        if cmdb_count:
            await add_if_missing(
                "generic_cmdb",
                "Local CMDB",
                True,
                "healthy",
                {"legacy_id": "generic_cmdb", "dataset_count": cmdb_count},
                {"inventory": True},
            )

    async def list_integrations(self) -> list[dict[str, Any]]:
        await self.bootstrap_legacy_integrations()
        await self.bootstrap_stream_activations()
        connector_id = await self.connector_id()
        rows = list(
            (
                await self.session.scalars(
                    select(ConnectorIntegrationModel)
                    .where(ConnectorIntegrationModel.connector_id == connector_id)
                    .order_by(ConnectorIntegrationModel.display_name)
                )
            ).all()
        )
        return [self._response(item) for item in rows]

    async def bootstrap_stream_activations(self) -> None:
        """Backfill capability rows for integrations created outside the generic API."""
        connector_id = await self.connector_id()
        integrations = list(
            (
                await self.session.scalars(
                    select(ConnectorIntegrationModel).where(
                        ConnectorIntegrationModel.connector_id == connector_id
                    )
                )
            ).all()
        )
        changed = False
        for integration in integrations:
            for stream, source_key, source_name in self._stream_sources_for(
                integration.integration_type, integration.capabilities_json
            ):
                existing = await self.session.scalar(
                    select(IntegrationStreamActivationModel).where(
                        IntegrationStreamActivationModel.connector_id == connector_id,
                        IntegrationStreamActivationModel.stream == stream,
                        IntegrationStreamActivationModel.source_key == source_key,
                    )
                )
                if existing is not None:
                    continue
                selected = False
                if integration.enabled:
                    current = await self.session.scalar(
                        select(IntegrationStreamActivationModel.id).where(
                            IntegrationStreamActivationModel.connector_id == connector_id,
                            IntegrationStreamActivationModel.stream == stream,
                            IntegrationStreamActivationModel.active.is_(True),
                        )
                    )
                    selected = current is None
                self.session.add(
                    IntegrationStreamActivationModel(
                        connector_id=connector_id,
                        integration_id=integration.id,
                        stream=stream,
                        source_key=source_key,
                        source_name=source_name,
                        enabled=selected,
                        active=selected,
                        activated_at=datetime.now(UTC) if selected else None,
                    )
                )
                await self.session.flush()
                changed = True
        for integration in integrations:
            selected = await self.integration_is_selected(integration.id)
            if integration.enabled != selected:
                await self._set_connection_enabled(integration, selected)
                changed = True
        if changed:
            await self.session.commit()

    async def stream_sources(self) -> list[dict[str, Any]]:
        await self.bootstrap_legacy_integrations()
        await self.bootstrap_stream_activations()
        connector_id = await self.connector_id()
        rows = list(
            (
                await self.session.execute(
                    select(IntegrationStreamActivationModel, ConnectorIntegrationModel)
                    .join(
                        ConnectorIntegrationModel,
                        ConnectorIntegrationModel.id
                        == IntegrationStreamActivationModel.integration_id,
                    )
                    .where(IntegrationStreamActivationModel.connector_id == connector_id)
                    .order_by(
                        IntegrationStreamActivationModel.stream,
                        IntegrationStreamActivationModel.source_name,
                    )
                )
            ).all()
        )
        by_stream: dict[str, list[dict[str, Any]]] = {stream: [] for stream in STREAMS}
        for activation, integration in rows:
            by_stream[activation.stream].append(
                {
                    "activation_id": str(activation.id),
                    "integration_id": str(integration.id),
                    "source_key": activation.source_key,
                    "source_name": activation.source_name,
                    "configured": True,
                    "selected": activation.active and activation.enabled,
                    "status": integration.status,
                    "last_successful_sync_at": integration.last_successful_sync_at,
                    "last_error": integration.last_error,
                }
            )
        return [
            {
                "stream": stream,
                "display_name": stream.title() if stream != "cmdb" else "CMDB",
                "selected_source": next(
                    (item["source_key"] for item in by_stream[stream] if item["selected"]), None
                ),
                "sources": by_stream[stream],
            }
            for stream in STREAMS
        ]

    async def active_source(self, stream: str) -> IntegrationStreamActivationModel | None:
        if stream not in STREAMS:
            raise IntegrationError("UNKNOWN_STREAM", "Integration stream is not supported.")
        await self.bootstrap_stream_activations()
        connector_id = await self.connector_id()
        return await self.session.scalar(
            select(IntegrationStreamActivationModel)
            .join(
                ConnectorIntegrationModel,
                ConnectorIntegrationModel.id == IntegrationStreamActivationModel.integration_id,
            )
            .where(
                IntegrationStreamActivationModel.connector_id == connector_id,
                IntegrationStreamActivationModel.stream == stream,
                IntegrationStreamActivationModel.active.is_(True),
                IntegrationStreamActivationModel.enabled.is_(True),
            )
        )

    async def integration_is_selected(self, integration_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(IntegrationStreamActivationModel.id).where(
                    IntegrationStreamActivationModel.integration_id == integration_id,
                    IntegrationStreamActivationModel.active.is_(True),
                    IntegrationStreamActivationModel.enabled.is_(True),
                )
            )
            is not None
        )

    async def select_source(
        self,
        integration_id: UUID,
        stream: str,
        *,
        confirmed: bool,
        actor: str | None,
    ) -> dict[str, Any]:
        await self.bootstrap_stream_activations()
        integration = await self.get(integration_id)
        requested = await self.session.scalar(
            select(IntegrationStreamActivationModel)
            .where(
                IntegrationStreamActivationModel.integration_id == integration.id,
                IntegrationStreamActivationModel.stream == stream,
            )
            .with_for_update()
        )
        if requested is None:
            raise IntegrationError(
                "SOURCE_NOT_AVAILABLE_FOR_STREAM",
                f"{integration.display_name} is not a source for {stream.title()}.",
                409,
            )
        stream_rows = list(
            (
                await self.session.scalars(
                    select(IntegrationStreamActivationModel)
                    .where(
                        IntegrationStreamActivationModel.connector_id
                        == requested.connector_id,
                        IntegrationStreamActivationModel.stream == stream,
                    )
                    .with_for_update()
                )
            ).all()
        )
        current = next((item for item in stream_rows if item.active), None)
        if current is not None and current.id != requested.id and not confirmed:
            raise SourceSwitchConfirmationRequiredError(
                stream, current.source_name, requested.source_name
            )
        if not CATALOG_BY_TYPE[integration.integration_type].get("available"):
            raise IntegrationError("ADAPTER_UNAVAILABLE", "This source is unavailable.", 409)
        now = datetime.now(UTC)
        previous_integration_id = current.integration_id if current else None
        if current is not None and current.id != requested.id:
            await self.session.execute(
                update(IntegrationStreamActivationModel)
                .where(
                    IntegrationStreamActivationModel.connector_id == requested.connector_id,
                    IntegrationStreamActivationModel.stream == stream,
                    IntegrationStreamActivationModel.active.is_(True),
                )
                .values(active=False, enabled=False)
                .execution_options(synchronize_session="fetch")
            )
            await self.session.flush()
        requested.enabled = True
        requested.active = True
        requested.activated_at = now
        await self._set_connection_enabled(integration, True)
        if previous_integration_id and previous_integration_id != integration.id:
            remaining = await self.session.scalar(
                select(IntegrationStreamActivationModel.id).where(
                    IntegrationStreamActivationModel.integration_id
                    == previous_integration_id,
                    IntegrationStreamActivationModel.active.is_(True),
                )
            )
            if remaining is None:
                previous_integration = await self.session.get(
                    ConnectorIntegrationModel, previous_integration_id
                )
                if previous_integration is not None:
                    await self._set_connection_enabled(previous_integration, False)
        self._audit(
            "integration.source_selected",
            integration,
            actor,
            f"{requested.source_name} selected for {stream}",
            {
                "stream": stream,
                "source": requested.source_key,
                "previous_source": (
                    current.source_key if current and current.id != requested.id else None
                ),
            },
        )
        await self.session.commit()
        return {
            "stream": stream,
            "selected_source": requested.source_key,
            "source_name": requested.source_name,
            "previous_source": (
                current.source_key if current and current.id != requested.id else None
            ),
        }

    async def get(self, integration_id: UUID) -> ConnectorIntegrationModel:
        connector_id = await self.connector_id()
        model = await self.session.scalar(
            select(ConnectorIntegrationModel).where(
                ConnectorIntegrationModel.id == integration_id,
                ConnectorIntegrationModel.connector_id == connector_id,
            )
        )
        if model is None:
            raise IntegrationError("INTEGRATION_NOT_FOUND", "Integration was not found.", 404)
        return model

    async def create(self, values: dict[str, Any], actor: str | None) -> dict[str, Any]:
        integration_type = str(values["integration_type"])
        catalog = CATALOG_BY_TYPE.get(integration_type)
        if catalog is None:
            raise IntegrationError("UNKNOWN_INTEGRATION_TYPE", "Integration type is not supported.")
        public, secrets = self._split_configuration(dict(values.get("configuration") or {}))
        model = ConnectorIntegrationModel(
            connector_id=await self.connector_id(),
            integration_type=integration_type,
            display_name=str(values.get("display_name") or catalog["name"]).strip(),
            category=str(catalog["category"]),
            enabled=bool(values.get("enabled", False)) and bool(catalog.get("available")),
            status="configured" if catalog.get("available") else "unavailable",
            configuration_json=public,
            configuration_encrypted=self._encrypt_secrets(secrets),
            capabilities_json=self._validated_capabilities(
                integration_type, dict(values.get("capabilities") or catalog["capabilities"])
            ),
            initial_sync_status="not_started",
            last_error=str(catalog.get("unavailable_reason"))
            if not catalog.get("available")
            else None,
        )
        self.session.add(model)
        await self.session.flush()
        for stream, source_key, source_name in self._stream_sources_for(
            integration_type, model.capabilities_json
        ):
            current = await self.session.scalar(
                select(IntegrationStreamActivationModel.id).where(
                    IntegrationStreamActivationModel.connector_id == model.connector_id,
                    IntegrationStreamActivationModel.stream == stream,
                    IntegrationStreamActivationModel.active.is_(True),
                )
            )
            selected = model.enabled and current is None
            self.session.add(
                IntegrationStreamActivationModel(
                    connector_id=model.connector_id,
                    integration_id=model.id,
                    stream=stream,
                    source_key=source_key,
                    source_name=source_name,
                    enabled=selected,
                    active=selected,
                    activated_at=datetime.now(UTC) if selected else None,
                )
            )
            await self.session.flush()
        selected_count = int(
            await self.session.scalar(
                select(func.count(IntegrationStreamActivationModel.id)).where(
                    IntegrationStreamActivationModel.integration_id == model.id,
                    IntegrationStreamActivationModel.active.is_(True),
                )
            )
            or 0
        )
        model.enabled = selected_count > 0
        self._audit("integration.created", model, actor, "Integration created")
        await self.session.commit()
        return self._response(model)

    async def update(
        self, integration_id: UUID, values: dict[str, Any], actor: str | None
    ) -> dict[str, Any]:
        model = await self.get(integration_id)
        if "display_name" in values:
            model.display_name = str(values["display_name"]).strip()
        if "capabilities" in values:
            model.capabilities_json = self._validated_capabilities(
                model.integration_type, dict(values["capabilities"])
            )
        if "configuration" in values:
            public, secrets = self._split_configuration(dict(values["configuration"] or {}))
            model.configuration_json = {**model.configuration_json, **public}
            if secrets:
                previous = self._decrypt_secrets(model.configuration_encrypted)
                model.configuration_encrypted = self._encrypt_secrets({**previous, **secrets})
        model.status = (
            "configured" if CATALOG_BY_TYPE[model.integration_type]["available"] else "unavailable"
        )
        self._audit(
            "integration.configuration_changed",
            model,
            actor,
            "Integration configuration changed",
        )
        await self.session.commit()
        return self._response(model)

    async def set_enabled(
        self, integration_id: UUID, enabled: bool, actor: str | None
    ) -> dict[str, Any]:
        model = await self.get(integration_id)
        sources = self._stream_sources_for(
            model.integration_type, model.capabilities_json
        )
        if len(sources) != 1:
            raise IntegrationError(
                "STREAM_SELECTION_REQUIRED",
                "Select or unselect ServiceNow separately for Ticketing or CMDB.",
                409,
            )
        if enabled:
            await self.select_source(
                integration_id, sources[0][0], confirmed=False, actor=actor
            )
            return self._response(model)
        model.enabled = False
        await self.session.execute(
            update(IntegrationStreamActivationModel)
            .where(IntegrationStreamActivationModel.integration_id == model.id)
            .values(
                enabled=False,
                active=False,
            )
        )
        await self._set_connection_enabled(model, False)
        self._audit(
            "integration.enabled" if enabled else "integration.disabled",
            model,
            actor,
            "Integration enabled" if enabled else "Integration disabled",
        )
        await self.session.commit()
        return self._response(model)

    async def _set_connection_enabled(
        self, model: ConnectorIntegrationModel, enabled: bool
    ) -> None:
        """Synchronize runtime connection state without deleting configuration or cache."""
        model.enabled = enabled
        if model.integration_type == "zammad" and model.legacy_zammad_configuration_id:
            legacy = await self.session.get(
                ZammadConfigurationModel, model.legacy_zammad_configuration_id
            )
            if legacy is not None:
                legacy.enabled = enabled
        if model.integration_type == "servicenow":
            configuration = await self.session.scalar(
                select(ServiceNowConfigurationModel).where(
                    ServiceNowConfigurationModel.integration_id == model.id
                )
            )
            if configuration is not None:
                configuration.enabled = enabled
        legacy_id = model.configuration_json.get("legacy_id")
        if legacy_id and model.integration_type in {"prometheus", "loki", "documents"}:
            try:
                source_id = UUID(str(legacy_id))
            except ValueError:
                source_id = None
            if source_id is not None:
                if model.integration_type == "prometheus":
                    prometheus = await self.session.get(PrometheusConfigurationModel, source_id)
                    if prometheus is not None:
                        prometheus.enabled = enabled
                elif model.integration_type == "loki":
                    loki = await self.session.get(LokiConfigurationModel, source_id)
                    if loki is not None:
                        loki.enabled = enabled
                else:
                    document_source = await self.session.get(SourceModel, source_id)
                    if document_source is not None:
                        document_source.enabled = enabled

    async def mark_test_result(
        self, integration_id: UUID, success: bool, error: str | None = None
    ) -> ConnectorIntegrationModel:
        model = await self.get(integration_id)
        now = datetime.now(UTC)
        model.last_tested_at = now
        if success:
            model.last_successful_test_at = now
            model.status = (
                "healthy"
                if model.initial_sync_status == "completed"
                and model.last_successful_sync_at is not None
                else "configured"
            )
            model.last_error = None
        else:
            model.status = "attention"
            model.last_error = (error or "Connection test failed")[:2000]
        self._audit(
            "integration.connection_test.succeeded"
            if success
            else "integration.connection_test.failed",
            model,
            "system",
            "Connection test completed",
            {"result": "success" if success else "failed"},
        )
        await self.session.commit()
        return model

    async def mark_sync_result(
        self, integration_id: UUID, success: bool, error: str | None = None
    ) -> None:
        model = await self.get(integration_id)
        if success:
            model.initial_sync_status = "completed"
            model.last_successful_sync_at = datetime.now(UTC)
            model.status = "healthy"
            model.last_error = None
        else:
            model.initial_sync_status = "failed"
            model.status = "attention"
            model.last_error = (error or "Initial synchronization failed")[:2000]
        self._audit(
            "initial_sync.completed" if success else "initial_sync.failed",
            model,
            "system",
            "Initial synchronization completed" if success else "Initial synchronization failed",
            {"result": "success" if success else "failed"},
        )
        await self.session.commit()

    def _response(self, model: ConnectorIntegrationModel) -> dict[str, Any]:
        secrets = self._decrypt_secrets(model.configuration_encrypted)
        configuration = dict(model.configuration_json)
        configuration.update({name: "••••••••" for name in secrets})
        return {
            "id": str(model.id),
            "integration_type": model.integration_type,
            "display_name": model.display_name,
            "category": model.category,
            "enabled": model.enabled,
            "status": model.status,
            "configuration": configuration,
            "capabilities": model.capabilities_json,
            "last_tested_at": model.last_tested_at,
            "last_successful_test_at": model.last_successful_test_at,
            "last_successful_sync_at": model.last_successful_sync_at,
            "initial_sync_status": model.initial_sync_status,
            "last_error": model.last_error,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    @staticmethod
    def _validated_capabilities(integration_type: str, supplied: dict[str, Any]) -> dict[str, bool]:
        available = set(CATALOG_BY_TYPE[integration_type]["capabilities"])
        unknown = set(supplied) - available
        if unknown:
            raise IntegrationError(
                "UNKNOWN_CAPABILITY", f"Unknown capabilities: {', '.join(sorted(unknown))}."
            )
        defaults = dict(CATALOG_BY_TYPE[integration_type]["capabilities"])
        defaults.update({name: bool(value) for name, value in supplied.items()})
        return defaults

    @staticmethod
    def _split_configuration(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        public = {key: value for key, value in values.items() if key not in SECRET_FIELDS}
        secrets = {
            key: str(value)
            for key, value in values.items()
            if key in SECRET_FIELDS and value not in {None, "", "••••••••"}
        }
        return public, secrets

    def _encrypt_secrets(self, values: dict[str, str]) -> str | None:
        if not values:
            return None
        if not self.encryption.ready:
            raise IntegrationError(
                "ENCRYPTION_KEY_REQUIRED",
                "The connector encryption key is required to store integration secrets.",
                503,
            )
        return self.encryption.encrypt(json.dumps(values, sort_keys=True))

    def _decrypt_secrets(self, value: str | None) -> dict[str, str]:
        if not value:
            return {}
        try:
            parsed = json.loads(self.encryption.decrypt(value))
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(item) for key, item in parsed.items()}

    def _audit(
        self,
        event_type: str,
        integration: ConnectorIntegrationModel,
        actor: str | None,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditEventModel(
                event_type=event_type,
                actor_username=actor,
                target_type="integration",
                target_id=str(integration.id),
                message=message,
                details={
                    "connector_id": integration.connector_id,
                    "integration_type": integration.integration_type,
                    **(details or {}),
                },
            )
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
