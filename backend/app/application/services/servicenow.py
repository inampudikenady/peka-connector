"""ServiceNow Table API adapter, staged synchronization, and normalized cache queries."""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integrations import IntegrationService
from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.models.servicenow import (
    ServiceNowCIModel,
    ServiceNowConfigurationModel,
    ServiceNowJournalModel,
    ServiceNowRecordModel,
    ServiceNowRelationshipModel,
    ServiceNowSyncCursorModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService

CI_FIELDS = (
    "sys_id,sys_class_name,name,fqdn,ip_address,serial_number,asset_tag,os,os_version,"
    "environment,operational_status,install_status,short_description,company,location,"
    "sys_created_on,sys_updated_on"
)
INCIDENT_FIELDS = (
    "sys_id,number,short_description,description,state,active,priority,impact,urgency,"
    "category,subcategory,caller_id,assigned_to,assignment_group,cmdb_ci,opened_at,"
    "resolved_at,closed_at,sys_created_on,sys_updated_on,close_code,close_notes,correlation_id"
)
PROBLEM_FIELDS = (
    "sys_id,number,short_description,description,state,active,priority,impact,urgency,"
    "assigned_to,assignment_group,cmdb_ci,known_error,workaround,fix_notes,"
    "sys_created_on,sys_updated_on"
)
CHANGE_FIELDS = (
    "sys_id,number,short_description,description,state,active,type,risk,impact,priority,"
    "assigned_to,assignment_group,cmdb_ci,justification,implementation_plan,backout_plan,"
    "test_plan,start_date,end_date,sys_created_on,sys_updated_on"
)
RELATIONSHIP_FIELDS = "sys_id,parent,child,type,sys_updated_on"
RELATIONSHIP_TYPE_FIELDS = "sys_id,name,parent_descriptor,child_descriptor,sys_updated_on"
JOURNAL_FIELDS = "sys_id,element_id,element,value,sys_created_on,sys_created_by,sys_updated_on"
CI_TABLES = (
    "cmdb_ci",
    "cmdb_ci_server",
    "cmdb_ci_linux_server",
    "cmdb_ci_win_server",
    "cmdb_ci_service",
)
STAGES = (
    "configuration_items",
    "relationships",
    "incidents",
    "incident_journal",
    "problems",
    "changes",
)


class ServiceNowError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def validate_instance_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ServiceNowError(
            "INVALID_INSTANCE_URL", "ServiceNow instance URL must be HTTP or HTTPS."
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ServiceNowError(
            "INVALID_INSTANCE_URL",
            "ServiceNow instance URL cannot contain credentials, query parameters, or fragments.",
        )
    return candidate


def _value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("display_value") or "")
    return str(value or "")


def _display(value: Any) -> str | None:
    if isinstance(value, dict):
        result = value.get("display_value") or value.get("value")
    else:
        result = value
    return str(result) if result not in {None, ""} else None


def _date(value: Any, *, fallback: datetime | None = None) -> datetime:
    text = _value(value)
    if not text:
        return fallback or datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ServiceNowError(
                "INVALID_TIMESTAMP", "ServiceNow returned an invalid timestamp."
            ) from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def ci_aliases(raw: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for key in ("name", "fqdn", "ip_address"):
        value = _value(raw.get(key)).strip().casefold()
        if value:
            values.add(value)
            if key in {"name", "fqdn"}:
                values.add(value.split(".", 1)[0])
    return sorted(values)


def _human(author: str | None) -> bool:
    return bool(author) and not re.search(
        r"(?:^|[._-])(system|admin|integration|automation|bot)(?:$|[._-])", author, re.I
    )


def latest_meaningful_update(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = [entry for entry in entries if _value(entry.get("value")).strip()]
    if not normalized:
        return None
    normalized.sort(
        key=lambda item: (
            2
            if _human(_value(item.get("sys_created_by")))
            and _value(item.get("element")) == "work_notes"
            else 1
            if _human(_value(item.get("sys_created_by")))
            and _value(item.get("element")) == "comments"
            else 0,
            _date(item.get("sys_created_on")),
        ),
        reverse=True,
    )
    return normalized[0]


class ServiceNowClient:
    def __init__(
        self,
        configuration: ServiceNowConfigurationModel,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.configuration = configuration
        self.password = password
        self.transport = transport

    async def test_connection(self) -> dict[str, Any]:
        rows = await self._list("cmdb_ci", fields="sys_id,name", limit=1)
        return {"success": True, "readable_configuration_item_count": len(rows)}

    async def list_configuration_items(
        self, updated_after: datetime | None = None
    ) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for table in CI_TABLES:
            for item in await self._list(table, fields=CI_FIELDS, updated_after=updated_after):
                sys_id = _value(item.get("sys_id"))
                if sys_id:
                    records[sys_id] = {**records.get(sys_id, {}), **item}
        return list(records.values())

    async def get_configuration_item(self, identifier: str) -> dict[str, Any] | None:
        query = (
            f"sys_id={identifier}"
            if re.fullmatch(r"[0-9a-f]{32}", identifier, re.I)
            else f"name={identifier}^ORfqdn={identifier}^ORip_address={identifier}"
        )
        rows = await self._list("cmdb_ci", fields=CI_FIELDS, query=query, limit=2)
        return rows[0] if rows else None

    async def list_ci_relationships(
        self, updated_after: datetime | None = None
    ) -> list[dict[str, Any]]:
        relationships = await self._list(
            "cmdb_rel_ci", fields=RELATIONSHIP_FIELDS, updated_after=updated_after
        )
        relationship_types = await self.list_relationship_types()
        names = {
            _value(item.get("sys_id")): _display(item.get("name"))
            or "::".join(
                filter(
                    None,
                    (
                        _display(item.get("parent_descriptor")),
                        _display(item.get("child_descriptor")),
                    ),
                )
            )
            for item in relationship_types
        }
        for relationship in relationships:
            type_sys_id = _value(relationship.get("type"))
            if type_sys_id in names and names[type_sys_id]:
                relationship["relationship_type_name"] = names[type_sys_id]
        return relationships

    async def list_relationship_types(self) -> list[dict[str, Any]]:
        return await self._list("cmdb_rel_type", fields=RELATIONSHIP_TYPE_FIELDS, limit=1000)

    async def list_incidents(self, updated_after: datetime | None = None) -> list[dict[str, Any]]:
        return await self._list("incident", fields=INCIDENT_FIELDS, updated_after=updated_after)

    async def get_incident(self, number_or_sys_id: str) -> dict[str, Any] | None:
        query = (
            f"sys_id={number_or_sys_id}"
            if re.fullmatch(r"[0-9a-f]{32}", number_or_sys_id, re.I)
            else f"number={number_or_sys_id.upper()}"
        )
        rows = await self._list("incident", fields=INCIDENT_FIELDS, query=query, limit=2)
        return rows[0] if rows else None

    async def list_incident_updates(
        self, incident_sys_id: str, updated_after: datetime | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            "sys_journal_field",
            fields=JOURNAL_FIELDS,
            query=f"name=incident^element_id={incident_sys_id}^elementINcomments,work_notes",
            updated_after=updated_after,
        )

    async def list_problems(self, updated_after: datetime | None = None) -> list[dict[str, Any]]:
        return await self._list("problem", fields=PROBLEM_FIELDS, updated_after=updated_after)

    async def get_problem(self, number_or_sys_id: str) -> dict[str, Any] | None:
        return await self._one("problem", number_or_sys_id, PROBLEM_FIELDS)

    async def list_changes(self, updated_after: datetime | None = None) -> list[dict[str, Any]]:
        return await self._list("change_request", fields=CHANGE_FIELDS, updated_after=updated_after)

    async def get_change(self, number_or_sys_id: str) -> dict[str, Any] | None:
        return await self._one("change_request", number_or_sys_id, CHANGE_FIELDS)

    async def _one(self, table: str, identifier: str, fields: str) -> dict[str, Any] | None:
        key = "sys_id" if re.fullmatch(r"[0-9a-f]{32}", identifier, re.I) else "number"
        rows = await self._list(table, fields=fields, query=f"{key}={identifier}", limit=2)
        return rows[0] if rows else None

    async def _list(
        self,
        table: str,
        *,
        fields: str,
        query: str | None = None,
        updated_after: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_size = min(max(self.configuration.page_size, 1), 1000)
        encoded = query or ""
        if updated_after:
            stamp = updated_after.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
            encoded = f"{encoded}^{'' if not encoded else ''}sys_updated_on>={stamp}".lstrip("^")
        for offset in range(0, limit, page_size):
            payload = await self._request(
                table,
                {
                    "sysparm_fields": fields,
                    "sysparm_query": encoded,
                    "sysparm_limit": min(page_size, limit - offset),
                    "sysparm_offset": offset,
                    "sysparm_exclude_reference_link": "true",
                    "sysparm_display_value": "all",
                },
            )
            if not isinstance(payload, list):
                raise ServiceNowError(
                    "MALFORMED_RESPONSE", f"ServiceNow table {table} did not return a result list."
                )
            rows = [item for item in payload if isinstance(item, dict)]
            items.extend(rows)
            if len(rows) < page_size:
                break
        return items

    async def _request(self, table: str, params: dict[str, Any]) -> Any:
        url = f"{self.configuration.instance_url}/api/now/table/{table}"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.configuration.request_timeout_seconds),
                    verify=self.configuration.verify_tls,
                    transport=self.transport,
                ) as client:
                    response = await client.get(
                        url,
                        params=params,
                        auth=(self.configuration.username, self.password),
                        headers={"Accept": "application/json"},
                    )
                if response.status_code == 401:
                    raise ServiceNowError(
                        "AUTHENTICATION_FAILED",
                        "ServiceNow rejected the configured username or password.",
                        401,
                    )
                if response.status_code == 403:
                    raise ServiceNowError(
                        "PERMISSION_DENIED", f"ServiceNow denied read access to table {table}.", 403
                    )
                if response.status_code == 404:
                    raise ServiceNowError(
                        "TABLE_OR_RECORD_NOT_FOUND",
                        f"ServiceNow table or record {table} was not found.",
                        404,
                    )
                if response.status_code == 429:
                    if attempt < 2:
                        await asyncio.sleep(
                            min(float(response.headers.get("Retry-After", "1") or 1), 2.0)
                        )
                        continue
                    raise ServiceNowError(
                        "RATE_LIMITED", "ServiceNow rate-limited the connector request.", 429
                    )
                if response.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                response.raise_for_status()
                try:
                    body = response.json()
                except ValueError as exc:
                    raise ServiceNowError(
                        "MALFORMED_RESPONSE", "ServiceNow returned invalid JSON.", 502
                    ) from exc
                if not isinstance(body, dict) or "result" not in body:
                    message = _display(body.get("error")) if isinstance(body, dict) else None
                    raise ServiceNowError(
                        "MALFORMED_RESPONSE",
                        message or "ServiceNow response did not include result.",
                        502,
                    )
                return body["result"]
            except ServiceNowError:
                raise
            except httpx.TimeoutException as exc:
                if attempt < 2:
                    continue
                raise ServiceNowError("TIMEOUT", "The ServiceNow request timed out.", 504) from exc
            except httpx.ConnectError as exc:
                cause: BaseException | None = exc
                while getattr(cause, "__cause__", None) is not None:
                    cause = cause.__cause__
                if isinstance(cause, socket.gaierror):
                    code, message = "DNS_FAILURE", "The ServiceNow hostname could not be resolved."
                elif isinstance(cause, (ssl.SSLError, ssl.CertificateError)):
                    code, message = (
                        "TLS_FAILURE",
                        "The ServiceNow TLS certificate could not be validated.",
                    )
                else:
                    code, message = (
                        "CONNECTION_FAILED",
                        "The connector could not connect to ServiceNow.",
                    )
                raise ServiceNowError(code, message, 502) from exc
            except httpx.HTTPStatusError as exc:
                raise ServiceNowError(
                    "HTTP_FAILURE", f"ServiceNow returned HTTP {exc.response.status_code}.", 502
                ) from exc
        raise ServiceNowError("REQUEST_FAILED", "The ServiceNow request failed.", 502)


class ServiceNowService:
    overlap = timedelta(minutes=2)

    def __init__(self, session: AsyncSession, encryption: SecretEncryptionService) -> None:
        self.session = session
        self.encryption = encryption

    async def list_configurations(self) -> list[dict[str, Any]]:
        rows = (
            await self.session.scalars(
                select(ServiceNowConfigurationModel).order_by(
                    ServiceNowConfigurationModel.created_at
                )
            )
        ).all()
        return [await self._response(row) for row in rows]

    async def save(
        self, configuration_id: UUID | None, values: dict[str, Any], actor: str | None = None
    ) -> dict[str, Any]:
        instance_url = validate_instance_url(str(values.get("instance_url") or ""))
        password = str(values.get("password") or "")
        if configuration_id:
            model = await self._configuration(configuration_id)
            integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
            if integration is None:
                raise ServiceNowError(
                    "INTEGRATION_NOT_FOUND", "ServiceNow integration was not found.", 404
                )
            await IntegrationService(self.session, self.encryption).update(
                integration.id,
                {
                    "display_name": values.get("name") or integration.display_name,
                    "configuration": {
                        "instance_url": instance_url,
                        "username": str(values.get("username") or ""),
                        "verify_tls": bool(values.get("verify_tls", True)),
                        "sync_interval_seconds": int(values.get("sync_interval_seconds", 900)),
                    },
                },
                actor,
            )
        else:
            if not password:
                raise ServiceNowError("PASSWORD_REQUIRED", "ServiceNow password is required.")
            response = await IntegrationService(self.session, self.encryption).create(
                {
                    "integration_type": "servicenow",
                    "display_name": str(values.get("name") or "ServiceNow"),
                    "enabled": bool(values.get("enabled", True)),
                    "configuration": {
                        "instance_url": instance_url,
                        "username": str(values.get("username") or ""),
                        "verify_tls": bool(values.get("verify_tls", True)),
                        "sync_interval_seconds": int(values.get("sync_interval_seconds", 900)),
                    },
                },
                actor,
            )
            integration = await self.session.get(ConnectorIntegrationModel, UUID(response["id"]))
            assert integration is not None
            model = ServiceNowConfigurationModel(
                integration_id=integration.id,
                instance_url=instance_url,
                username=str(values.get("username") or ""),
                encrypted_password=self.encryption.encrypt(password),
            )
            self.session.add(model)
        if not password and not configuration_id:
            raise ServiceNowError("PASSWORD_REQUIRED", "ServiceNow password is required.")
        if password and configuration_id:
            model.encrypted_password = self.encryption.encrypt(password)
            model.password_configured = True
        model.instance_url = instance_url
        model.username = str(values.get("username") or "").strip()
        if not model.username:
            raise ServiceNowError("USERNAME_REQUIRED", "ServiceNow username is required.")
        model.verify_tls = bool(values.get("verify_tls", True))
        model.request_timeout_seconds = float(values.get("request_timeout_seconds", 20))
        model.page_size = int(values.get("page_size", 200))
        model.sync_interval_seconds = int(values.get("sync_interval_seconds", 900))
        model.enabled = bool(values.get("enabled", True))
        integration.enabled = model.enabled
        if not model.enabled:
            await self._mark_cache(model.integration_id, "inactive")
        await self.session.commit()
        await self.session.refresh(model)
        return await self._response(model)

    async def test(self, configuration_id: UUID) -> dict[str, Any]:
        model = await self._configuration(configuration_id)
        model.last_test_at = datetime.now(UTC)
        try:
            result = await self._client(model).test_connection()
        except ServiceNowError as exc:
            model.connection_state = "failed"
            model.last_sync_error = str(exc)
            await IntegrationService(self.session, self.encryption).mark_test_result(
                model.integration_id, False, str(exc)
            )
            await self.session.commit()
            raise
        model.connection_state = "connected"
        model.last_successful_test_at = datetime.now(UTC)
        model.last_sync_error = None
        await IntegrationService(self.session, self.encryption).mark_test_result(
            model.integration_id, True
        )
        await self.session.commit()
        return {**result, "message": "ServiceNow authentication and CMDB read access validated."}

    async def synchronize(self, configuration_id: UUID) -> dict[str, Any]:
        model = await self._configuration(configuration_id)
        if not model.enabled:
            raise ServiceNowError(
                "SERVICENOW_DISABLED", "The ServiceNow integration is disabled.", 503
            )
        client = self._client(model)
        counts: dict[str, int] = dict(model.counts_json or {})
        errors: dict[str, str] = {}
        stage_handlers = {
            "configuration_items": lambda cursor: self._sync_cis(
                model, awaitable=client.list_configuration_items(cursor)
            ),
            "relationships": lambda cursor: self._sync_relationships(
                model, awaitable=client.list_ci_relationships(cursor)
            ),
            "incidents": lambda cursor: self._sync_records(
                model, "incident", awaitable=client.list_incidents(cursor)
            ),
            "incident_journal": lambda cursor: self._sync_journals(model, client, cursor),
            "problems": lambda cursor: self._sync_records(
                model, "problem", awaitable=client.list_problems(cursor)
            ),
            "changes": lambda cursor: self._sync_records(
                model, "change", awaitable=client.list_changes(cursor)
            ),
        }
        for stage in STAGES:
            cursor = await self._cursor(model.integration_id, stage)
            cursor.last_attempt_at = datetime.now(UTC)
            after = cursor.cursor_at - self.overlap if cursor.cursor_at else None
            try:
                count, maximum = await stage_handlers[stage](after)
                counts[stage] = count
                cursor.cursor_at = maximum or datetime.now(UTC)
                cursor.last_error = None
                await self.session.commit()
            except ServiceNowError as exc:
                cursor.last_error = str(exc)[:2000]
                errors[stage] = str(exc)
                await self.session.commit()
        model.counts_json = counts
        integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
        if errors:
            model.last_sync_error = "; ".join(f"{key}: {value}" for key, value in errors.items())[
                :2000
            ]
            if integration:
                integration.status = "attention"
                integration.last_error = model.last_sync_error
        else:
            model.last_successful_sync_at = datetime.now(UTC)
            model.last_sync_error = None
            if integration:
                integration.status = "healthy"
                integration.initial_sync_status = "completed"
                integration.last_successful_sync_at = model.last_successful_sync_at
                integration.last_error = None
        await self.session.commit()
        if errors and len(errors) == len(STAGES):
            raise ServiceNowError(
                "SYNCHRONIZATION_FAILED",
                model.last_sync_error or "ServiceNow synchronization failed.",
                502,
            )
        return {
            "counts": counts,
            "stage_errors": errors,
            "last_successful_sync_at": model.last_successful_sync_at,
        }

    async def status(self, integration_id: UUID | None = None) -> dict[str, Any]:
        model = await self._active_configuration(integration_id, require_enabled=False)
        return await self._response(model)

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        model = await self._active_configuration(
            None, require_enabled=tool_name != "servicenow_get_status"
        )
        if tool_name == "servicenow_get_status":
            return await self._response(model)
        availability = self._availability(model)
        if tool_name == "servicenow_get_incident":
            number = str(arguments.get("number") or "").upper()
            row = await self.session.scalar(
                select(ServiceNowRecordModel).where(
                    ServiceNowRecordModel.integration_id == model.integration_id,
                    ServiceNowRecordModel.record_type == "incident",
                    or_(
                        ServiceNowRecordModel.external_id == number,
                        ServiceNowRecordModel.external_sys_id == number,
                    ),
                    ServiceNowRecordModel.cache_status == "active",
                )
            )
            return {
                "source": "servicenow",
                "incident": self._record_dict(row) if row else None,
                "availability": availability,
            }
        if tool_name == "servicenow_get_incident_updates":
            number = str(arguments.get("number") or "").upper()
            record = await self.session.scalar(
                select(ServiceNowRecordModel).where(
                    ServiceNowRecordModel.integration_id == model.integration_id,
                    ServiceNowRecordModel.record_type == "incident",
                    ServiceNowRecordModel.external_id == number,
                )
            )
            rows = (
                []
                if not record
                else list(
                    (
                        await self.session.scalars(
                            select(ServiceNowJournalModel)
                            .where(ServiceNowJournalModel.record_id == record.id)
                            .order_by(ServiceNowJournalModel.source_created_at.desc())
                            .limit(50)
                        )
                    ).all()
                )
            )
            return {
                "source": "servicenow",
                "incident": self._record_dict(record) if record else None,
                "updates": [self._journal_dict(row) for row in rows],
                "availability": availability,
            }
        if tool_name in {
            "servicenow_search_incidents",
            "servicenow_list_open_incidents",
            "servicenow_search_problems",
            "servicenow_search_changes",
        }:
            record_type = (
                "problem"
                if "problems" in tool_name
                else "change"
                if "changes" in tool_name
                else "incident"
            )
            query = str(arguments.get("query") or "").casefold()
            identifier = str(arguments.get("identifier") or "").strip()
            limit = min(max(int(arguments.get("limit", 25)), 1), 50)
            rows = list(
                (
                    await self.session.scalars(
                        select(ServiceNowRecordModel)
                        .where(
                            ServiceNowRecordModel.integration_id == model.integration_id,
                            ServiceNowRecordModel.record_type == record_type,
                            ServiceNowRecordModel.cache_status == "active",
                        )
                        .order_by(ServiceNowRecordModel.source_updated_at.desc())
                    )
                ).all()
            )
            if tool_name == "servicenow_list_open_incidents":
                rows = [row for row in rows if self._incident_is_open(row)]
            if identifier:
                matching_ci = await self._find_ci(model.integration_id, identifier)
                rows = (
                    [row for row in rows if row.cmdb_ci_sys_id == matching_ci.external_sys_id]
                    if matching_ci
                    else []
                )
            if query:
                rows = [
                    row
                    for row in rows
                    if query
                    in (
                        f"{row.external_id} {row.short_description} {row.description or ''}"
                    ).casefold()
                ]
            return {
                "source": "servicenow",
                "record_type": record_type,
                "count": len(rows),
                "records": [self._record_dict(row) for row in rows[:limit]],
                "availability": availability,
            }
        identifier = str(arguments.get("identifier") or "")
        ci = await self._find_ci(model.integration_id, identifier)
        if tool_name == "servicenow_get_ci":
            return {
                "source": "servicenow",
                "ci": self._ci_dict(ci) if ci else None,
                "availability": availability,
            }
        if tool_name == "servicenow_get_ci_tickets":
            rows = (
                []
                if not ci
                else list(
                    (
                        await self.session.scalars(
                            select(ServiceNowRecordModel)
                            .where(
                                ServiceNowRecordModel.integration_id == model.integration_id,
                                ServiceNowRecordModel.cmdb_ci_sys_id == ci.external_sys_id,
                                ServiceNowRecordModel.cache_status == "active",
                            )
                            .order_by(ServiceNowRecordModel.source_updated_at.desc())
                            .limit(100)
                        )
                    ).all()
                )
            )
            return {
                "source": "servicenow",
                "ci": self._ci_dict(ci) if ci else None,
                "records": [self._record_dict(row) for row in rows],
                "count": len(rows),
                "availability": availability,
            }
        if tool_name == "servicenow_get_ci_relationships":
            depth = min(max(int(arguments.get("max_depth", 3)), 1), 3)
            return {
                "source": "servicenow",
                "ci": self._ci_dict(ci) if ci else None,
                "relationships": await self._traverse(
                    model.integration_id, ci.external_sys_id if ci else "", depth
                ),
                "availability": availability,
            }
        raise ServiceNowError("UNSUPPORTED_TOOL", "Unsupported ServiceNow operational tool.")

    async def _sync_cis(
        self, model: ServiceNowConfigurationModel, *, awaitable: Any
    ) -> tuple[int, datetime | None]:
        rows = await awaitable
        now = datetime.now(UTC)
        maximum = None
        product = await self.session.get(ProductSettingsModel, 1)
        tenant_id = str(product.tenant_id if product else "")
        integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
        connector_id = integration.connector_id if integration else "local"
        for raw in rows:
            sys_id = _value(raw.get("sys_id"))
            updated = _date(raw.get("sys_updated_on"))
            maximum = max(maximum, updated) if maximum else updated
            row = await self.session.scalar(
                select(ServiceNowCIModel).where(
                    ServiceNowCIModel.integration_id == model.integration_id,
                    ServiceNowCIModel.external_sys_id == sys_id,
                )
            )
            row = row or ServiceNowCIModel(
                tenant_id=tenant_id,
                connector_id=connector_id,
                integration_id=model.integration_id,
                external_id=sys_id,
                external_sys_id=sys_id,
                sys_class_name="cmdb_ci",
                name="",
                source_updated_at=updated,
            )
            if row.id is None:
                self.session.add(row)
            row.sys_class_name = _value(raw.get("sys_class_name")) or "cmdb_ci"
            row.name = _value(raw.get("name"))
            row.fqdn = _display(raw.get("fqdn"))
            row.ip_address = _display(raw.get("ip_address"))
            row.aliases_json = ci_aliases(raw)
            row.fields_json = raw
            row.active = _value(raw.get("install_status")) not in {"7", "retired"}
            row.source_updated_at = updated
            row.synced_at = now
            row.last_seen_at = now
            row.cache_status = "active" if model.enabled else "inactive"
        await self.session.flush()
        return len(rows), maximum

    async def _sync_relationships(
        self, model: ServiceNowConfigurationModel, *, awaitable: Any
    ) -> tuple[int, datetime | None]:
        rows = await awaitable
        maximum = None
        product = await self.session.get(ProductSettingsModel, 1)
        integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
        for raw in rows:
            sys_id = _value(raw.get("sys_id"))
            updated = _date(raw.get("sys_updated_on"))
            maximum = max(maximum, updated) if maximum else updated
            row = await self.session.scalar(
                select(ServiceNowRelationshipModel).where(
                    ServiceNowRelationshipModel.integration_id == model.integration_id,
                    ServiceNowRelationshipModel.external_sys_id == sys_id,
                )
            )
            row = row or ServiceNowRelationshipModel(
                tenant_id=str(product.tenant_id if product else ""),
                connector_id=integration.connector_id if integration else "local",
                integration_id=model.integration_id,
                external_id=sys_id,
                external_sys_id=sys_id,
                parent_sys_id="",
                child_sys_id="",
                relationship_type_name="Related to",
                source_updated_at=updated,
            )
            if row.id is None:
                self.session.add(row)
            row.parent_sys_id = _value(raw.get("parent"))
            row.child_sys_id = _value(raw.get("child"))
            row.parent_display_name = _display(raw.get("parent"))
            row.child_display_name = _display(raw.get("child"))
            row.relationship_type_sys_id = _value(raw.get("type")) or None
            row.relationship_type_name = (
                _display(raw.get("relationship_type_name"))
                or _display(raw.get("type"))
                or "Related to"
            )
            row.source_updated_at = updated
            row.synced_at = datetime.now(UTC)
            row.cache_status = "active"
        await self.session.flush()
        return len(rows), maximum

    async def _sync_records(
        self, model: ServiceNowConfigurationModel, record_type: str, *, awaitable: Any
    ) -> tuple[int, datetime | None]:
        rows = await awaitable
        maximum = None
        product = await self.session.get(ProductSettingsModel, 1)
        integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
        for raw in rows:
            sys_id = _value(raw.get("sys_id"))
            number = _value(raw.get("number")) or sys_id
            updated = _date(raw.get("sys_updated_on"))
            maximum = max(maximum, updated) if maximum else updated
            row = await self.session.scalar(
                select(ServiceNowRecordModel).where(
                    ServiceNowRecordModel.integration_id == model.integration_id,
                    ServiceNowRecordModel.record_type == record_type,
                    ServiceNowRecordModel.external_sys_id == sys_id,
                )
            )
            row = row or ServiceNowRecordModel(
                tenant_id=str(product.tenant_id if product else ""),
                connector_id=integration.connector_id if integration else "local",
                integration_id=model.integration_id,
                record_type=record_type,
                external_id=number,
                external_sys_id=sys_id,
                source_updated_at=updated,
            )
            if row.id is None:
                self.session.add(row)
            ci_sys_id = _value(raw.get("cmdb_ci")) or None
            correlation_method = "cmdb_ci_sys_id" if ci_sys_id else "unmatched"
            correlation_confidence = "exact" if ci_sys_id else "none"
            if not ci_sys_id:
                match = await self._correlate_record_ci(model.integration_id, raw)
                if match:
                    ci_sys_id, correlation_method = match
                    correlation_confidence = "exact"
            row.external_id = number
            row.short_description = _value(raw.get("short_description"))
            row.description = _display(raw.get("description"))
            row.state = _value(raw.get("state")) or "unknown"
            row.state_display = _display(raw.get("state")) or row.state
            row.active = _value(raw.get("active")).casefold() not in {"false", "0", "no"}
            row.priority = _display(raw.get("priority"))
            row.assigned_to = _display(raw.get("assigned_to"))
            row.assignment_group = _display(raw.get("assignment_group"))
            row.cmdb_ci_sys_id = ci_sys_id
            row.correlation_method = correlation_method
            row.correlation_confidence = correlation_confidence
            row.fields_json = raw
            row.source_updated_at = updated
            row.synced_at = datetime.now(UTC)
            row.last_seen_at = datetime.now(UTC)
            row.cache_status = "active"
        await self.session.flush()
        return len(rows), maximum

    async def _sync_journals(
        self, model: ServiceNowConfigurationModel, client: ServiceNowClient, after: datetime | None
    ) -> tuple[int, datetime | None]:
        product = await self.session.get(ProductSettingsModel, 1)
        integration = await self.session.get(ConnectorIntegrationModel, model.integration_id)
        tenant_id = str(product.tenant_id if product else "")
        connector_id = integration.connector_id if integration else "local"
        incidents = list(
            (
                await self.session.scalars(
                    select(ServiceNowRecordModel).where(
                        ServiceNowRecordModel.integration_id == model.integration_id,
                        ServiceNowRecordModel.record_type == "incident",
                    )
                )
            ).all()
        )
        count = 0
        maximum = None
        for incident in incidents:
            entries = await client.list_incident_updates(incident.external_sys_id, after)
            for raw in entries:
                sys_id = _value(raw.get("sys_id"))
                created = _date(raw.get("sys_created_on"))
                updated = _date(raw.get("sys_updated_on"), fallback=created)
                maximum = max(maximum, updated) if maximum else updated
                row = await self.session.scalar(
                    select(ServiceNowJournalModel).where(
                        ServiceNowJournalModel.integration_id == model.integration_id,
                        ServiceNowJournalModel.external_sys_id == sys_id,
                    )
                )
                row = row or ServiceNowJournalModel(
                    tenant_id=tenant_id,
                    connector_id=connector_id,
                    integration_id=model.integration_id,
                    record_id=incident.id,
                    external_id=sys_id,
                    external_sys_id=sys_id,
                    element_id=incident.external_sys_id,
                    element="comments",
                    value="",
                    source_created_at=created,
                    source_updated_at=updated,
                )
                if row.id is None:
                    self.session.add(row)
                row.element = _value(raw.get("element"))
                row.value = _value(raw.get("value"))
                row.created_by = _display(raw.get("sys_created_by"))
                row.human = _human(row.created_by)
                row.source_created_at = created
                row.source_updated_at = updated
                count += 1
            latest = latest_meaningful_update(entries)
            if latest:
                incident.latest_update_text = _value(latest.get("value"))
                incident.latest_update_at = _date(latest.get("sys_created_on"))
                incident.latest_update_by = _display(latest.get("sys_created_by"))
        await self.session.flush()
        return count, maximum

    async def _cursor(self, integration_id: UUID, stage: str) -> ServiceNowSyncCursorModel:
        row = await self.session.scalar(
            select(ServiceNowSyncCursorModel).where(
                ServiceNowSyncCursorModel.integration_id == integration_id,
                ServiceNowSyncCursorModel.record_type == stage,
            )
        )
        if row is None:
            row = ServiceNowSyncCursorModel(integration_id=integration_id, record_type=stage)
            self.session.add(row)
            await self.session.flush()
        return row

    async def _find_ci(self, integration_id: UUID, identifier: str) -> ServiceNowCIModel | None:
        target = identifier.strip().casefold()
        rows = (
            await self.session.scalars(
                select(ServiceNowCIModel).where(
                    ServiceNowCIModel.integration_id == integration_id,
                    ServiceNowCIModel.cache_status == "active",
                )
            )
        ).all()
        return next(
            (
                row
                for row in rows
                if target in set(row.aliases_json or [])
                or target
                in {
                    row.external_sys_id.casefold(),
                    row.name.casefold(),
                    (row.fqdn or "").casefold(),
                    (row.ip_address or "").casefold(),
                }
            ),
            None,
        )

    async def _correlate_record_ci(
        self, integration_id: UUID, raw: dict[str, Any]
    ) -> tuple[str, str] | None:
        """Return a unique exact alias match; never promote fuzzy text to an exact CI."""
        text = " ".join(
            _value(raw.get(field))
            for field in ("short_description", "description", "correlation_id")
        ).casefold()
        if not text.strip():
            return None
        cis = (
            await self.session.scalars(
                select(ServiceNowCIModel).where(
                    ServiceNowCIModel.integration_id == integration_id,
                    ServiceNowCIModel.cache_status == "active",
                )
            )
        ).all()
        matches: list[tuple[ServiceNowCIModel, str]] = []
        for ci in cis:
            for alias in sorted(set(ci.aliases_json or []), key=len, reverse=True):
                if not alias:
                    continue
                pattern = re.escape(alias)
                if re.fullmatch(r"[a-z0-9_-]+", alias):
                    pattern = rf"(?<![a-z0-9_-]){pattern}(?![a-z0-9_-])"
                if re.search(pattern, text, re.IGNORECASE):
                    method = (
                        "ip_address"
                        if alias == (ci.ip_address or "").casefold()
                        else "fqdn"
                        if alias == (ci.fqdn or "").casefold()
                        else "hostname"
                    )
                    matches.append((ci, method))
                    break
        unique = {match[0].external_sys_id: match for match in matches}
        if len(unique) != 1:
            return None
        ci, method = next(iter(unique.values()))
        return ci.external_sys_id, method

    async def _traverse(
        self, integration_id: UUID, start: str, max_depth: int
    ) -> list[dict[str, Any]]:
        if not start:
            return []
        rows = list(
            (
                await self.session.scalars(
                    select(ServiceNowRelationshipModel).where(
                        ServiceNowRelationshipModel.integration_id == integration_id,
                        ServiceNowRelationshipModel.cache_status == "active",
                    )
                )
            ).all()
        )
        queue = [(start, 0)]
        visited = {start}
        emitted: set[str] = set()
        result = []
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for row in rows:
                if current not in {row.parent_sys_id, row.child_sys_id}:
                    continue
                if row.external_sys_id in emitted:
                    continue
                emitted.add(row.external_sys_id)
                other = row.child_sys_id if current == row.parent_sys_id else row.parent_sys_id
                result.append(
                    {
                        "external_sys_id": row.external_sys_id,
                        "parent_sys_id": row.parent_sys_id,
                        "child_sys_id": row.child_sys_id,
                        "type": row.relationship_type_name,
                        "parent": row.parent_display_name,
                        "child": row.child_display_name,
                        "depth": depth + 1,
                    }
                )
                if other not in visited:
                    visited.add(other)
                    queue.append((other, depth + 1))
        return result

    async def _active_configuration(
        self, integration_id: UUID | None, *, require_enabled: bool
    ) -> ServiceNowConfigurationModel:
        statement = (
            select(ServiceNowConfigurationModel)
            .join(
                ConnectorIntegrationModel,
                ConnectorIntegrationModel.id == ServiceNowConfigurationModel.integration_id,
            )
            .where(ConnectorIntegrationModel.integration_type == "servicenow")
        )
        if integration_id:
            statement = statement.where(
                ServiceNowConfigurationModel.integration_id == integration_id
            )
        model = await self.session.scalar(
            statement.order_by(ServiceNowConfigurationModel.updated_at.desc())
        )
        if model is None:
            raise ServiceNowError("SERVICENOW_NOT_CONFIGURED", "ServiceNow is not configured.", 404)
        if require_enabled and not model.enabled:
            raise ServiceNowError("SERVICENOW_DISABLED", "ServiceNow is disabled.", 503)
        return model

    async def _configuration(self, configuration_id: UUID) -> ServiceNowConfigurationModel:
        model = await self.session.get(ServiceNowConfigurationModel, configuration_id)
        if model is None:
            raise ServiceNowError(
                "CONFIGURATION_NOT_FOUND", "ServiceNow configuration was not found.", 404
            )
        return model

    def _client(self, model: ServiceNowConfigurationModel) -> ServiceNowClient:
        if not model.encrypted_password:
            raise ServiceNowError(
                "PASSWORD_REQUIRED", "ServiceNow password is not configured.", 503
            )
        return ServiceNowClient(model, self.encryption.decrypt(model.encrypted_password))

    async def _mark_cache(self, integration_id: UUID, status: str) -> None:
        for model in (ServiceNowCIModel, ServiceNowRelationshipModel, ServiceNowRecordModel):
            await self.session.execute(
                update(model)
                .where(model.integration_id == integration_id)
                .values(cache_status=status)
            )

    def _availability(self, model: ServiceNowConfigurationModel) -> dict[str, Any]:
        return {
            "enabled": model.enabled,
            "state": model.connection_state,
            "cache_timestamp": model.last_successful_sync_at.isoformat()
            if model.last_successful_sync_at
            else None,
            "stale": not model.last_successful_sync_at
            or datetime.now(UTC) - model.last_successful_sync_at
            > timedelta(seconds=model.sync_interval_seconds * 2),
            "last_error": model.last_sync_error,
        }

    async def _response(self, model: ServiceNowConfigurationModel) -> dict[str, Any]:
        return {
            "id": str(model.id),
            "integration_id": str(model.integration_id),
            "integration": "servicenow",
            "enabled": model.enabled,
            "configured": bool(model.instance_url and model.username and model.encrypted_password),
            "instance_url": model.instance_url,
            "username": model.username,
            "password_configured": bool(model.encrypted_password),
            "verify_tls": model.verify_tls,
            "request_timeout_seconds": model.request_timeout_seconds,
            "page_size": model.page_size,
            "sync_interval_seconds": model.sync_interval_seconds,
            "connection_state": model.connection_state,
            "connected": model.connection_state == "connected",
            "last_test_at": model.last_test_at,
            "last_successful_test_at": model.last_successful_test_at,
            "last_successful_sync_at": model.last_successful_sync_at,
            "last_sync_error": model.last_sync_error,
            "next_scheduled_sync_at": model.next_scheduled_sync_at,
            "counts": model.counts_json or {},
            "availability": self._availability(model),
        }

    @staticmethod
    def _ci_dict(row: ServiceNowCIModel | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "source": "servicenow",
            "record_type": "configuration_item",
            "external_id": row.external_id,
            "external_sys_id": row.external_sys_id,
            "sys_class_name": row.sys_class_name,
            "name": row.name,
            "fqdn": row.fqdn,
            "ip_address": row.ip_address,
            "aliases": row.aliases_json,
            "active": row.active,
            **row.fields_json,
        }

    @staticmethod
    def _record_dict(row: ServiceNowRecordModel | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "source": "servicenow",
            "record_type": row.record_type,
            "external_id": row.external_id,
            "external_sys_id": row.external_sys_id,
            "number": row.external_id,
            "title": row.short_description,
            "short_description": row.short_description,
            "description": row.description,
            "state": row.state_display,
            "state_value": row.state,
            "active": row.active,
            "priority": row.priority,
            "assigned_to": row.assigned_to,
            "assignment_group": row.assignment_group,
            "cmdb_ci_sys_id": row.cmdb_ci_sys_id,
            "correlation_method": row.correlation_method,
            "correlation_confidence": row.correlation_confidence,
            "latest_update": row.latest_update_text,
            "latest_update_at": row.latest_update_at.isoformat() if row.latest_update_at else None,
            "source_updated_at": row.source_updated_at.isoformat(),
            "updated_at": row.source_updated_at.isoformat(),
            "ci_name": _display((row.fields_json or {}).get("cmdb_ci")),
            "fields": row.fields_json,
        }

    @staticmethod
    def _incident_is_open(row: ServiceNowRecordModel) -> bool:
        closed_values = {"6", "7", "8"}
        closed_labels = {"resolved", "closed", "canceled", "cancelled"}
        return (
            row.active
            and row.state.casefold() not in closed_values
            and row.state_display.casefold() not in closed_labels
        )

    @staticmethod
    def _journal_dict(row: ServiceNowJournalModel) -> dict[str, Any]:
        return {
            "source": "servicenow",
            "record_type": "incident_journal",
            "external_sys_id": row.external_sys_id,
            "element": row.element,
            "value": row.value,
            "created_by": row.created_by,
            "human": row.human,
            "created_at": row.source_created_at.isoformat(),
        }
