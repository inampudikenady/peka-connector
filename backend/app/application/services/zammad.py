"""Read-only connector-local Zammad synchronization and operational queries."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import ssl
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.integrations import IntegrationService
from app.application.services.inventory import endpoint_identity
from app.application.services.zammad_relevance import (
    CONCEPT_FAMILIES,
    classify_ticket_type,
    expand_concepts,
    score_ticket_relevance,
)
from app.core.logging import sanitize
from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.models.inventory import (
    InventoryAssetModel,
    InventoryIdentityModel,
)
from app.infrastructure.database.models.operations import ProductSettingsModel
from app.infrastructure.database.models.zammad import (
    ZammadConfigurationModel,
    ZammadTicketArticleModel,
    ZammadTicketModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService

logger = logging.getLogger(__name__)


class ZammadError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(str(sanitize(message)))
        self.code = code
        self.status_code = status_code


def validate_zammad_base_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    parsed = urlparse(clean)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ZammadError(
            "INVALID_URL",
            "Zammad URL must be an HTTP(S) base URL without credentials, query, or fragment.",
        )
    return clean


def redact_zammad_secret(value: str, token: str | None = None) -> str:
    safe = str(sanitize(value))
    if token:
        safe = safe.replace(token, "[REDACTED]")
    return re.sub(r"(?i)Token\s+token=[^\s,]+", "Token token=[REDACTED]", safe)


class _PlainTextParser(HTMLParser):
    block_tags = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style"}:
            self.suppressed_depth += 1
            return
        if self.suppressed_depth:
            return
        if tag.casefold() in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self.suppressed_depth:
            self.suppressed_depth -= 1
            return
        if self.suppressed_depth:
            return
        if tag.casefold() in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)


def html_to_safe_text(value: object) -> str:
    parser = _PlainTextParser()
    try:
        parser.feed(str(value or ""))
        raw = "".join(parser.parts)
    except Exception:
        raw = re.sub(r"<[^>]*>", " ", str(value or ""))
    lines = [" ".join(unescape(line).split()) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _date(value: object, *, required: bool = False) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    if required:
        raise ZammadError("MALFORMED_RESPONSE", "Zammad returned an invalid ticket timestamp.")
    return None


def normalize_state(value: object, state_type: object = None) -> tuple[str, str, bool]:
    name = str(value or "unknown").strip()
    kind = str(state_type or name).strip().casefold().replace(" ", "_")
    if kind in {"new", "open", "pending_reminder", "pending_action", "pending"}:
        normalized_type = "pending" if kind.startswith("pending") else kind
        return name, normalized_type, True
    if kind in {"closed", "merged", "removed"}:
        return name, "closed", False
    return name, kind or "unknown", kind not in {"closed", "merged", "removed"}


@dataclass(frozen=True)
class NormalizedTicketArticle:
    external_id: str
    created_at: datetime
    updated_at: datetime | None
    author: str | None
    sender: str | None
    article_type: str | None
    internal: bool
    subject: str | None
    body_text: str
    automated: bool = False


@dataclass(frozen=True)
class NormalizedTicket:
    source: str
    external_id: str
    number: str
    title: str
    state: str
    state_type: str
    priority: str | None
    group: str | None
    owner: str | None
    customer: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    is_open: bool
    initial_description: str | None
    latest_update_text: str | None
    latest_update_at: datetime | None
    articles: list[NormalizedTicketArticle]
    referenced_asset_ids: list[str] = field(default_factory=list)
    referenced_hostnames: list[str] = field(default_factory=list)
    referenced_fqdns: list[str] = field(default_factory=list)
    referenced_ip_addresses: list[str] = field(default_factory=list)
    asset_relationships: list[dict[str, str]] = field(default_factory=list)
    ticket_type: str = "unknown"
    ticket_type_reason: str = "No deterministic ticket-type evidence"
    search_text: str = ""


def _display(value: object, lookups: dict[str, dict[str, str]], kind: str) -> str | None:
    if isinstance(value, dict):
        for key in ("name", "fullname", "login", "email"):
            if value.get(key):
                return str(value[key])
    if value is None:
        return None
    return lookups.get(kind, {}).get(str(value), str(value))


def _meaningful_article(articles: list[NormalizedTicketArticle]) -> NormalizedTicketArticle | None:
    meaningful = [item for item in articles if item.body_text.strip()]
    human = [item for item in meaningful if not item.automated]
    candidates = human or meaningful
    return candidates[-1] if candidates else None


def normalize_ticket(
    raw: dict[str, Any],
    raw_articles: list[dict[str, Any]],
    lookups: dict[str, dict[str, str]] | None = None,
) -> NormalizedTicket:
    lookups = lookups or {}
    articles: list[NormalizedTicketArticle] = []
    for item in raw_articles:
        created = _date(item.get("created_at"), required=True)
        assert created is not None
        sender = _display(item.get("sender") or item.get("sender_id"), lookups, "users")
        author = _display(item.get("created_by") or item.get("created_by_id"), lookups, "users")
        article_type = _display(item.get("type") or item.get("type_id"), lookups, "article_types")
        automated = bool(
            item.get("automated")
            or str(sender or "").casefold() == "system"
            or str(article_type or "").casefold() in {"note-system", "system"}
        )
        articles.append(
            NormalizedTicketArticle(
                external_id=str(item.get("id") or ""),
                created_at=created,
                updated_at=_date(item.get("updated_at")),
                author=author,
                sender=sender,
                article_type=article_type,
                internal=bool(item.get("internal", False)),
                subject=html_to_safe_text(item.get("subject")) or None,
                body_text=html_to_safe_text(item.get("body")),
                automated=automated,
            )
        )
    articles.sort(key=lambda item: (item.created_at, item.external_id))
    initial = next((item.body_text for item in articles if item.body_text), None)
    latest = _meaningful_article(articles)
    state_value = raw.get("state") or lookups.get("states", {}).get(str(raw.get("state_id")))
    state_type = raw.get("state_type") or lookups.get("state_types", {}).get(
        str(raw.get("state_id"))
    )
    state, normalized_state, is_open = normalize_state(state_value, state_type)
    created = _date(raw.get("created_at"), required=True)
    updated = _date(raw.get("updated_at"), required=True)
    assert created is not None and updated is not None
    tags = [str(value) for value in (raw.get("tags") or []) if value]
    title = html_to_safe_text(raw.get("title")) or "Untitled ticket"
    known_fields = {
        "id",
        "number",
        "title",
        "state",
        "state_id",
        "state_type",
        "priority",
        "priority_id",
        "group",
        "group_id",
        "owner",
        "owner_id",
        "customer",
        "customer_id",
        "tags",
        "created_at",
        "updated_at",
        "close_at",
        "closed_at",
    }
    custom_values = [
        str(item)
        for key, value in raw.items()
        if key not in known_fields
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, str | int | float)
    ]
    searchable = "\n".join(
        [title, initial or "", *(item.body_text for item in articles), *tags, *custom_values]
    ).casefold()
    ticket_type, ticket_type_reason = classify_ticket_type(searchable)
    return NormalizedTicket(
        source="zammad",
        external_id=str(raw.get("id") or ""),
        number=str(raw.get("number") or raw.get("id") or ""),
        title=title,
        state=state,
        state_type=normalized_state,
        priority=_display(raw.get("priority") or raw.get("priority_id"), lookups, "priorities"),
        group=_display(raw.get("group") or raw.get("group_id"), lookups, "groups"),
        owner=_display(raw.get("owner") or raw.get("owner_id"), lookups, "users"),
        customer=_display(raw.get("customer") or raw.get("customer_id"), lookups, "users"),
        tags=tags,
        created_at=created,
        updated_at=updated,
        closed_at=_date(raw.get("close_at") or raw.get("closed_at")),
        is_open=is_open,
        initial_description=initial,
        latest_update_text=latest.body_text if latest else None,
        latest_update_at=latest.created_at if latest else None,
        articles=articles,
        ticket_type=ticket_type,
        ticket_type_reason=ticket_type_reason,
        search_text=searchable,
    )


class ZammadClient:
    def __init__(
        self,
        configuration: ZammadConfigurationModel,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.configuration = configuration
        self.token = token
        self.transport = transport
        self.last_ticket_pages_fetched = 0

    async def validate(self) -> dict[str, Any]:
        payload = await self._request(
            "GET", "/api/v1/tickets", params={"page": 1, "per_page": 1, "expand": "true"}
        )
        if not isinstance(payload, list):
            raise ZammadError("MALFORMED_RESPONSE", "Zammad ticket-read response was not a list.")
        return {"success": True, "readable_ticket_count": len(payload)}

    async def lookup_tables(self) -> dict[str, dict[str, str]]:
        lookups: dict[str, dict[str, str]] = {}
        for path, key in (
            ("/api/v1/ticket_states", "states"),
            ("/api/v1/ticket_priorities", "priorities"),
            ("/api/v1/groups", "groups"),
            ("/api/v1/users", "users"),
        ):
            try:
                payload = await self._request("GET", path)
            except ZammadError:
                continue
            if isinstance(payload, list):
                lookups[key] = {
                    str(item.get("id")): str(
                        item.get("name")
                        or item.get("fullname")
                        or item.get("login")
                        or item.get("id")
                    )
                    for item in payload
                    if isinstance(item, dict) and item.get("id") is not None
                }
                if key == "states":
                    lookups["state_types"] = {
                        str(item.get("id")): str(
                            item.get("state_type") or item.get("name") or "unknown"
                        )
                        for item in payload
                        if isinstance(item, dict) and item.get("id") is not None
                    }
        return lookups

    async def tickets(
        self, *, updated_after: datetime | None = None, limit: int = 5000
    ) -> list[dict[str, Any]]:
        self.last_ticket_pages_fetched = 0
        if updated_after:
            query = f"updated_at:>{updated_after.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            return await self.search(query, limit=limit)
        items: list[dict[str, Any]] = []
        per_page = 100
        for page in range(1, min(100, (limit + per_page - 1) // per_page) + 1):
            payload = await self._request(
                "GET",
                "/api/v1/tickets",
                params={"page": page, "per_page": per_page, "expand": "true"},
            )
            if not isinstance(payload, list):
                raise ZammadError("MALFORMED_RESPONSE", "Zammad ticket page was not a list.")
            self.last_ticket_pages_fetched += 1
            items.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < per_page or len(items) >= limit:
                break
        return items[:limit]

    async def search(self, query: str, *, limit: int = 5000) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_size = min(100, limit)
        for page in range(1, min(100, (limit + page_size - 1) // page_size) + 1):
            payload = await self._request(
                "GET",
                "/api/v1/tickets/search",
                params={
                    "query": query,
                    "page": page,
                    "limit": page_size,
                    "expand": "true",
                },
            )
            if not isinstance(payload, list):
                raise ZammadError(
                    "MALFORMED_RESPONSE", "Zammad ticket search response was not a list."
                )
            self.last_ticket_pages_fetched += 1
            items.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < page_size or len(items) >= limit:
                break
        return items[:limit]

    async def ticket(self, external_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET", f"/api/v1/tickets/{quote(external_id, safe='')}", params={"expand": "true"}
        )
        if not isinstance(payload, dict):
            raise ZammadError("MALFORMED_RESPONSE", "Zammad ticket response was not an object.")
        return payload

    async def ticket_by_number(self, number: str) -> dict[str, Any] | None:
        results = await self.search(f"number:{number}", limit=10)
        return next((item for item in results if str(item.get("number")) == number), None)

    async def articles(self, external_id: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", f"/api/v1/ticket_articles/by_ticket/{quote(external_id, safe='')}"
        )
        if not isinstance(payload, list):
            raise ZammadError("MALFORMED_RESPONSE", "Zammad article response was not a list.")
        return [item for item in payload if isinstance(item, dict)]

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        headers = {"Authorization": f"Token token={self.token}", "Accept": "application/json"}
        timeout = httpx.Timeout(self.configuration.request_timeout_seconds)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    verify=self.configuration.tls_verify,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = await client.request(
                        method, self.configuration.base_url + path, headers=headers, params=params
                    )
                if response.status_code == 401:
                    raise ZammadError(
                        "AUTHENTICATION_FAILED", "Zammad rejected the configured access token.", 401
                    )
                if response.status_code == 403:
                    raise ZammadError(
                        "PERMISSION_DENIED",
                        "The Zammad token cannot read tickets or permitted articles.",
                        403,
                    )
                if response.status_code == 404:
                    raise ZammadError(
                        "NOT_FOUND", "The requested Zammad record was not found.", 404
                    )
                if response.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as exc:
                    raise ZammadError(
                        "MALFORMED_RESPONSE", "Zammad returned malformed JSON."
                    ) from exc
            except ZammadError:
                raise
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < 2:
                    continue
                raise ZammadError("TIMEOUT", "The Zammad request timed out.", 504) from exc
            except httpx.ConnectError as exc:
                cause: BaseException | None = exc
                while getattr(cause, "__cause__", None) is not None:
                    next_cause = getattr(cause, "__cause__", None)
                    if next_cause is None:
                        break
                    cause = next_cause
                if isinstance(cause, socket.gaierror):
                    code, message = "DNS_FAILURE", "The Zammad hostname could not be resolved."
                elif isinstance(cause, ssl.SSLError | ssl.CertificateError):
                    code, message = (
                        "TLS_FAILURE",
                        "The Zammad TLS certificate could not be validated.",
                    )
                else:
                    code, message = (
                        "CONNECTION_REFUSED",
                        "The connector could not connect to Zammad.",
                    )
                raise ZammadError(code, message, 502) from exc
            except httpx.HTTPStatusError as exc:
                detail = redact_zammad_secret(exc.response.text[:500], self.token)
                raise ZammadError(
                    "HTTP_FAILURE",
                    f"Zammad returned HTTP {exc.response.status_code}: {detail}",
                    502,
                ) from exc
        raise ZammadError(
            "REQUEST_FAILED",
            redact_zammad_secret(str(last_error or "Zammad request failed"), self.token),
            502,
        )


class ZammadService:
    def __init__(self, session: AsyncSession, encryption: SecretEncryptionService) -> None:
        self.session = session
        self.encryption = encryption

    async def list_configurations(self) -> list[dict[str, Any]]:
        models = list(
            (
                await self.session.scalars(
                    select(ZammadConfigurationModel).order_by(ZammadConfigurationModel.name)
                )
            ).all()
        )
        return [self._configuration_response(item) for item in models]

    async def save(self, configuration_id: UUID | None, values: dict[str, Any]) -> dict[str, Any]:
        model = (
            await self.session.get(ZammadConfigurationModel, configuration_id)
            if configuration_id
            else ZammadConfigurationModel()
        )
        if configuration_id and model is None:
            raise ZammadError("CONFIGURATION_NOT_FOUND", "Zammad configuration was not found.", 404)
        assert model is not None
        model.name = str(values.get("name") or "Zammad").strip()
        model.base_url = validate_zammad_base_url(str(values["base_url"]))
        model.instance_key = sha256(model.base_url.casefold().encode()).hexdigest()
        token = str(values.get("access_token") or "")
        if token:
            if not self.encryption.ready:
                raise ZammadError(
                    "ENCRYPTION_KEY_REQUIRED",
                    "The connector encryption key is required to store the Zammad token.",
                    503,
                )
            model.encrypted_access_token = self.encryption.encrypt(token)
            model.token_configured = True
        elif not model.encrypted_access_token:
            raise ZammadError("ACCESS_TOKEN_REQUIRED", "A Zammad access token is required.")
        model.tls_verify = bool(values.get("tls_verify", True))
        model.request_timeout_seconds = float(values.get("request_timeout_seconds", 15))
        model.sync_interval_seconds = int(values.get("sync_interval_seconds", 900))
        model.history_window_days = int(values.get("history_window_days", 90))
        model.group_filters_json = sorted(
            {str(value).strip() for value in values.get("group_filters", []) if str(value).strip()}
        )
        model.include_closed_tickets = bool(values.get("include_closed_tickets", True))
        model.enabled = bool(values.get("enabled", True))
        if not 1 <= model.request_timeout_seconds <= 120:
            raise ZammadError(
                "INVALID_TIMEOUT", "Request timeout must be between 1 and 120 seconds."
            )
        if not 60 <= model.sync_interval_seconds <= 86400:
            raise ZammadError(
                "INVALID_SYNC_INTERVAL",
                "Synchronization interval must be between 60 and 86400 seconds.",
            )
        if not 1 <= model.history_window_days <= 3650:
            raise ZammadError(
                "INVALID_HISTORY_WINDOW", "Ticket history window must be between 1 and 3650 days."
            )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        integrations = IntegrationService(self.session, self.encryption)
        await integrations.bootstrap_legacy_integrations()
        await integrations.bootstrap_stream_activations()
        integration = await self._integration_for_configuration(model.id)
        # Connection runtime follows stream selection. Saving an alternate
        # Ticketing configuration must never bypass the confirmation contract.
        selected = await integrations.integration_is_selected(integration.id)
        model.enabled = selected
        integration.enabled = selected
        integration.display_name = model.name
        integration.status = "healthy" if model.connection_state == "connected" else "attention"
        integration.last_error = model.last_error
        await self.session.commit()
        return self._configuration_response(model)

    async def delete(self, configuration_id: UUID) -> None:
        model = await self._configuration(configuration_id)
        await self.session.delete(model)
        await self.session.commit()

    async def test(self, configuration_id: UUID) -> dict[str, Any]:
        model = await self._configuration(configuration_id)
        try:
            result = await self._client(model).validate()
            model.connection_state = "connected"
            model.last_successful_test_at = datetime.now(UTC)
            model.last_error = None
            await self.session.commit()
            integration = await self._integration_for_configuration(model.id)
            await IntegrationService(self.session, self.encryption).mark_test_result(
                integration.id, True
            )
            return {
                **result,
                "message": "Zammad authentication and ticket-read permission validated.",
            }
        except ZammadError as exc:
            model.connection_state = "failed"
            model.last_error = str(exc)[:2000]
            await self.session.commit()
            integration = await self._integration_for_configuration(model.id)
            await IntegrationService(self.session, self.encryption).mark_test_result(
                integration.id, False, str(exc)
            )
            raise

    async def synchronize(
        self,
        configuration_id: UUID,
        *,
        full: bool = False,
        trigger: str = "scheduled",
    ) -> dict[str, Any]:
        model = await self._configuration(configuration_id)
        if not model.enabled:
            raise ZammadError("ZAMMAD_DISABLED", "The Zammad integration is disabled.", 409)
        integration = await self._integration_for_configuration(model.id)
        if not integration.enabled:
            raise ZammadError("ZAMMAD_DISABLED", "The Zammad integration is disabled.", 409)
        integration_id = integration.id
        started = time.monotonic()
        now = datetime.now(UTC)
        cursor_before = model.sync_cursor_at
        product = await self.session.get(ProductSettingsModel, 1)
        stats: dict[str, Any] = {
            "tenant_id": product.tenant_id if product else None,
            "connector_id": integration.connector_id,
            "integration_id": str(integration.id),
            "configuration_id": str(model.id),
            "trigger": trigger,
            "cursor_before": cursor_before.isoformat() if cursor_before else None,
            "cursor_after": None,
            "pages_fetched": 0,
            "tickets_fetched": 0,
            "tickets_normalized": 0,
            "tickets_stored": 0,
            "tickets_skipped": 0,
            "skip_reasons": {},
            "articles_fetched": 0,
            "articles_stored": 0,
        }

        def log_stage(event: str, *, failed: bool = False) -> None:
            stats["duration_seconds"] = round(time.monotonic() - started, 3)
            if failed:
                logger.exception("%s %s", event, sanitize(stats))
            else:
                logger.info("%s %s", event, sanitize(stats))

        def skip(reason: str) -> None:
            stats["tickets_skipped"] += 1
            reasons = cast(dict[str, int], stats["skip_reasons"])
            reasons[reason] = reasons.get(reason, 0) + 1

        log_stage("zammad_sync_started")
        try:
            client = self._client(model)
            lookups = await client.lookup_tables()
            visible_count = int(
                await self.session.scalar(
                    select(func.count(ZammadTicketModel.id)).where(
                        ZammadTicketModel.configuration_id == model.id,
                        ZammadTicketModel.visible.is_(True),
                        ZammadTicketModel.cache_status == "active",
                    )
                )
                or 0
            )
            # Manual synchronization is a full reconciliation. An empty cache with a
            # cursor is treated as recoverable cursor corruption and also forces full.
            reconciliation_due = (
                full
                or visible_count == 0
                or model.last_reconciled_at is None
                or now - model.last_reconciled_at >= timedelta(hours=24)
            )
            updated_after = None
            if not reconciliation_due and model.sync_cursor_at is not None:
                updated_after = model.sync_cursor_at - timedelta(minutes=2)
            raw_tickets = await client.tickets(updated_after=updated_after, limit=5000)
            stats["pages_fetched"] = client.last_ticket_pages_fetched
            stats["tickets_fetched"] = len(raw_tickets)
            log_stage("zammad_ticket_fetch_completed")
            cutoff = now - timedelta(days=model.history_window_days)
            allowed_groups = {value.casefold() for value in model.group_filters_json}
            seen: set[str] = set()
            normalized: list[NormalizedTicket] = []
            for raw in raw_tickets:
                updated = _date(raw.get("updated_at"))
                if updated and updated < cutoff:
                    skip("outside_history_window")
                    continue
                external_id = str(raw.get("id") or "")
                if not external_id:
                    skip("missing_external_id")
                    continue
                articles = await client.articles(external_id)
                stats["articles_fetched"] += len(articles)
                ticket = normalize_ticket(raw, articles, lookups)
                if not model.include_closed_tickets and not ticket.is_open:
                    skip("closed_ticket_excluded")
                    continue
                if allowed_groups and str(ticket.group or "").casefold() not in allowed_groups:
                    skip("group_filter")
                    continue
                ticket = await self._correlate(ticket)
                normalized.append(ticket)
            stats["tickets_normalized"] = len(normalized)
            log_stage("zammad_ticket_normalization_completed")
            log_stage("zammad_article_fetch_completed")
            for ticket in normalized:
                await self._upsert(model, ticket, now)
                seen.add(ticket.external_id)
                stats["tickets_stored"] += 1
                stats["articles_stored"] += len(ticket.articles)
            log_stage("zammad_ticket_cache_write_completed")
            log_stage("zammad_article_cache_write_completed")
            if reconciliation_due:
                stale = select(ZammadTicketModel).where(
                    ZammadTicketModel.configuration_id == model.id
                )
                if seen:
                    stale = stale.where(ZammadTicketModel.external_id.not_in(seen))
                await self.session.execute(
                    update(ZammadTicketModel)
                    .where(ZammadTicketModel.id.in_(stale.with_only_columns(ZammadTicketModel.id)))
                    .values(visible=False, cache_status="deleted")
                )
            updated_dates = [
                value
                for value in (_date(item.get("updated_at")) for item in raw_tickets)
                if value is not None
            ]
            # Never move an incremental cursor forward when the remote query is empty.
            # This makes an incorrect future cursor self-recoverable on the next full run.
            if updated_dates:
                model.sync_cursor_at = max(updated_dates)
            model.last_successful_sync_at = now
            if reconciliation_due:
                model.last_reconciled_at = now
            model.last_sync_duration_seconds = round(time.monotonic() - started, 3)
            await self.session.flush()
            model.synchronized_ticket_count = int(
                await self.session.scalar(
                    select(func.count(ZammadTicketModel.id)).where(
                        ZammadTicketModel.configuration_id == model.id,
                        ZammadTicketModel.visible.is_(True),
                    )
                )
                or 0
            )
            model.synchronized_article_count = int(
                await self.session.scalar(
                    select(func.count(ZammadTicketArticleModel.id))
                    .join(
                        ZammadTicketModel,
                        ZammadTicketModel.id == ZammadTicketArticleModel.ticket_id,
                    )
                    .where(
                        ZammadTicketModel.configuration_id == model.id,
                        ZammadTicketModel.visible.is_(True),
                    )
                )
                or 0
            )
            model.connection_state = "connected"
            model.last_error = None
            stats["cursor_after"] = (
                model.sync_cursor_at.isoformat() if model.sync_cursor_at else None
            )
            stats["duration_seconds"] = model.last_sync_duration_seconds
            await self.session.commit()
            await IntegrationService(self.session, self.encryption).mark_sync_result(
                integration_id, True
            )
            log_stage("zammad_sync_completed")
            return {
                "ticket_count": stats["tickets_stored"],
                "article_count": stats["articles_stored"],
                "cached_ticket_count": model.synchronized_ticket_count,
                "cached_article_count": model.synchronized_article_count,
                "full_reconciliation": reconciliation_due,
                "pages_fetched": stats["pages_fetched"],
                "tickets_skipped": stats["tickets_skipped"],
                "duration_seconds": model.last_sync_duration_seconds,
                "cache_timestamp": now.isoformat(),
                "live": True,
            }
        except Exception as exc:
            await self.session.rollback()
            model = await self._configuration(configuration_id)
            model.connection_state = "failed"
            safe_error = str(sanitize(str(exc)))[:2000]
            model.last_error = safe_error
            await self.session.commit()
            await IntegrationService(self.session, self.encryption).mark_sync_result(
                integration_id, False, safe_error
            )
            stats["error_category"] = getattr(exc, "code", type(exc).__name__)
            log_stage("zammad_sync_failed", failed=True)
            raise

    async def search_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        configuration = await self._enabled_configuration(require_enabled=True)
        query = str(arguments.get("query") or "").strip()
        terms = expand_concepts(query)
        state = str(arguments.get("state") or "all")
        ticket_number = str(arguments.get("ticket_number") or "").strip()
        asset_identifier = str(arguments.get("asset_identifier") or "").strip()
        limit = max(1, min(int(arguments.get("limit", 5)), 50))
        rows = await self._ticket_rows(configuration.id)
        article_rows = list(
            (
                await self.session.scalars(
                    select(ZammadTicketArticleModel)
                    .join(ZammadTicketModel)
                    .where(ZammadTicketModel.configuration_id == configuration.id)
                )
            ).all()
        )
        articles_by_ticket: dict[UUID, list[str]] = {}
        for article in article_rows:
            articles_by_ticket.setdefault(article.ticket_id, []).append(article.body_text)
        asset_id = (
            await self._resolve_asset_identifier(asset_identifier) if asset_identifier else None
        )
        created_from = _date(arguments.get("created_from"))
        created_to = _date(arguments.get("created_to"))
        updated_from = _date(arguments.get("updated_from"))
        updated_to = _date(arguments.get("updated_to"))
        matches: list[tuple[float, ZammadTicketModel, dict[str, Any] | None]] = []
        for row in rows:
            if state == "open" and not row.is_open or state == "closed" and row.is_open:
                continue
            if ticket_number and row.number != ticket_number:
                continue
            if (
                created_from
                and row.created_at_source < created_from
                or created_to
                and row.created_at_source > created_to
            ):
                continue
            if (
                updated_from
                and row.updated_at_source < updated_from
                or updated_to
                and row.updated_at_source > updated_to
            ):
                continue
            identities = set(
                row.referenced_asset_ids_json
                + row.referenced_hostnames_json
                + row.referenced_fqdns_json
                + row.referenced_ip_addresses_json
            )
            if asset_identifier and not (
                {asset_identifier.casefold(), str(asset_id or "")}
                & {value.casefold() for value in identities}
            ):
                continue
            relevance = None
            score = 0.0
            if query:
                scored = score_ticket_relevance(
                    query,
                    ticket_number=row.number,
                    title=row.title,
                    initial_description=row.initial_description,
                    article_bodies=articles_by_ticket.get(row.id, []),
                    tags=row.tags_json,
                    asset_identifiers=[
                        *row.referenced_hostnames_json,
                        *row.referenced_fqdns_json,
                        *row.referenced_ip_addresses_json,
                    ],
                )
                if not scored.accepted:
                    continue
                score = scored.score
                relevance = {
                    "score": scored.score,
                    "confidence": scored.confidence,
                    "match_reasons": scored.reasons,
                }
            matches.append((score, row, relevance))
        reverse = str(arguments.get("sort_order") or "updated_desc") != "updated_asc"
        matches.sort(key=lambda item: (item[0], item[1].updated_at_source), reverse=reverse)
        concept_family = next(
            (
                name
                for name, family_terms in CONCEPT_FAMILIES.items()
                if any(term in terms for term in family_terms)
            ),
            None,
        )
        return self._cached_result(
            configuration,
            {
                "tickets": [
                    self._ticket_summary(
                        row,
                        base_url=configuration.base_url,
                        relevance=relevance,
                    )
                    for _score, row, relevance in matches[:limit]
                ],
                "count": len(matches),
                "requested_limit": limit,
                "query_terms": sorted(terms),
                "concept_family": concept_family,
                "minimum_score": 0.65,
            },
        )

    async def get_ticket(self, arguments: dict[str, Any]) -> dict[str, Any]:
        configuration = await self._enabled_configuration(require_enabled=False)
        identifier = str(
            arguments.get("ticket_number") or arguments.get("external_id") or ""
        ).lstrip("#")
        cached = await self._find_ticket(configuration.id, identifier)
        live = False
        warning: str | None = None
        if configuration.enabled and configuration.token_configured:
            try:
                client = self._client(configuration)
                raw = (
                    await client.ticket(str(cached.external_id))
                    if cached
                    else await client.ticket_by_number(identifier)
                )
                if raw:
                    ticket = await self._correlate(
                        normalize_ticket(
                            raw, await client.articles(str(raw["id"])), await client.lookup_tables()
                        )
                    )
                    cached = await self._upsert(configuration, ticket, datetime.now(UTC))
                    await self.session.commit()
                    live = True
            except ZammadError as exc:
                warning = str(exc)
        if cached is None:
            if warning:
                raise ZammadError(
                    "ZAMMAD_UNAVAILABLE",
                    f"Zammad is unavailable and ticket {identifier} is not cached: {warning}",
                    503,
                )
            raise ZammadError("TICKET_NOT_FOUND", f"Ticket {identifier} was not found.", 404)
        return {
            "ticket": await self._ticket_detail(cached, configuration.base_url),
            "live": live,
            "cache_timestamp": cached.synchronized_at.isoformat(),
            "warning": warning,
        }

    async def get_ticket_counts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        configuration = await self._enabled_configuration(require_enabled=False)
        live = False
        warning = None
        if configuration.enabled:
            try:
                await self.synchronize(configuration.id)
                live = True
            except ZammadError as exc:
                warning = str(exc)
        rows = await self._ticket_rows(configuration.id)
        updated_from = _date(arguments.get("updated_from"))
        if updated_from:
            rows = [row for row in rows if row.updated_at_source >= updated_from]
        grouped: dict[str, int] = {}
        for row in rows:
            grouped[row.state_type] = grouped.get(row.state_type, 0) + 1
        return {
            "total_visible": len(rows),
            "open": sum(row.is_open for row in rows),
            "closed": sum(not row.is_open for row in rows),
            "new": grouped.get("new", 0),
            "pending": grouped.get("pending", 0),
            "counts_by_state": grouped,
            "live": live,
            "cache_timestamp": configuration.last_successful_sync_at.isoformat()
            if configuration.last_successful_sync_at
            else None,
            "warning": warning,
        }

    async def get_asset_tickets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        configuration = await self._enabled_configuration(require_enabled=False)
        identifier = str(arguments.get("identifier") or "")
        asset_id = await self._resolve_asset_identifier(identifier)
        if asset_id is None:
            return {
                "match_status": "not_found",
                "identifier": identifier,
                "tickets": [],
                "availability": self._availability(configuration),
            }
        rows = await self._ticket_rows(configuration.id)
        direct_roles = {
            "primary_affected_asset",
            "impacted_asset",
            "canonical_direct_match",
        }
        direct = [
            row
            for row in rows
            if any(
                item.get("asset_id") == str(asset_id) and item.get("relationship") in direct_roles
                for item in row.asset_relationships_json
            )
        ]
        indirect = [
            row
            for row in rows
            if row not in direct
            and any(item.get("asset_id") == str(asset_id) for item in row.asset_relationships_json)
        ]
        identity_values = await self._asset_identity_values(asset_id)
        potential = [
            row
            for row in rows
            if row not in direct
            and row not in indirect
            and identity_values
            & {
                value.casefold().rstrip(".")
                for value in (
                    row.referenced_hostnames_json
                    + row.referenced_fqdns_json
                    + row.referenced_ip_addresses_json
                )
            }
        ][:5]
        recently_closed_days = int(arguments.get("recently_closed_days", 30))
        cutoff = datetime.now(UTC) - timedelta(days=recently_closed_days)
        open_rows = [row for row in direct if row.is_open][:5]
        closed_rows = [
            row for row in direct if not row.is_open and row.updated_at_source >= cutoff
        ][:3]
        return {
            "match_status": "found",
            "asset_id": str(asset_id),
            "identifier": identifier,
            "open_tickets": [
                self._ticket_summary_for_asset(row, configuration.base_url, asset_id)
                for row in open_rows
            ],
            "recently_closed_tickets": [
                self._ticket_summary_for_asset(row, configuration.base_url, asset_id)
                for row in closed_rows
            ],
            "direct_tickets": [
                self._ticket_summary_for_asset(row, configuration.base_url, asset_id)
                for row in direct[:8]
            ],
            "indirect_tickets": [
                self._ticket_summary_for_asset(row, configuration.base_url, asset_id)
                for row in indirect[:8]
            ],
            "other_potentially_related": [
                self._ticket_summary(
                    row,
                    base_url=configuration.base_url,
                )
                for row in potential
            ],
            "availability": self._availability(configuration),
        }

    async def correlate_tickets_with_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = await self.get_asset_tickets(
            {"identifier": arguments.get("identifier"), "recently_closed_days": 90}
        )
        if base.get("match_status") != "found":
            return {**base, "correlations": []}
        configuration = await self._enabled_configuration(require_enabled=False)
        rows = await self._ticket_rows(configuration.id)
        asset_id = str(base["asset_id"])
        start = _date(arguments.get("evidence_start"))
        end = _date(arguments.get("evidence_end"))
        signals = [
            str(value).casefold()
            for key in ("error_strings", "warning_strings", "service_names")
            for value in arguments.get(key, [])
            if value
        ]
        signals.extend(expand_concepts(str(arguments.get("symptoms") or "")))
        ranked: list[dict[str, Any]] = []
        for row in rows:
            score = 0
            reasons: list[str] = []
            asset_relationship = next(
                (item for item in row.asset_relationships_json if item.get("asset_id") == asset_id),
                None,
            )
            relationship = (
                str(asset_relationship.get("relationship")) if asset_relationship else None
            )
            if relationship in {
                "primary_affected_asset",
                "impacted_asset",
                "canonical_direct_match",
            }:
                score += 50
                reasons.append(f"asset_relationship:{relationship}")
            elif relationship in {
                "monitoring_relationship",
                "service_dependency",
                "hosting_asset",
            }:
                score += 20
                reasons.append(f"asset_relationship:{relationship}")
            elif relationship == "mentioned_asset":
                score += 5
                reasons.append("asset_relationship:mentioned_asset")
            if start and end and row.created_at_source <= end and row.updated_at_source >= start:
                score += 20
                reasons.append("incident_window_overlap")
            exact = [value for value in signals if value and value in row.search_text]
            if exact:
                score += min(20, len(exact) * 5)
                reasons.append("evidence_text_match")
            if row.updated_at_source >= datetime.now(UTC) - timedelta(days=30):
                score += 5
                reasons.append("recent_update")
            if score < 10:
                continue
            classification = (
                "directly_related"
                if score >= 70
                else "probably_related"
                if score >= 45
                else "possibly_related"
                if score >= 20
                else "insufficient_evidence"
            )
            ranked.append(
                {
                    **self._ticket_summary(row, base_url=configuration.base_url),
                    "score": score,
                    "classification": classification,
                    "reasons": reasons,
                    "relationship": relationship,
                    "causality": "Correlation does not prove causation.",
                }
            )
        ranked.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)
        return {
            "match_status": "found",
            "asset_id": asset_id,
            "correlations": ranked[:10],
            "availability": self._availability(configuration),
        }

    async def _correlate(self, ticket: NormalizedTicket) -> NormalizedTicket:
        assets = list(
            (
                await self.session.scalars(
                    select(InventoryAssetModel).where(InventoryAssetModel.retired_at.is_(None))
                )
            ).all()
        )
        identities = list(
            (
                await self.session.scalars(
                    select(InventoryIdentityModel).where(
                        InventoryIdentityModel.asset_id.is_not(None)
                    )
                )
            ).all()
        )
        by_value: dict[str, UUID] = {}
        for asset in assets:
            for value in (
                asset.canonical_name,
                asset.hostname,
                asset.fqdn,
                asset.primary_ip,
                *(asset.additional_ips_json or []),
            ):
                if value:
                    by_value[str(value).casefold().rstrip(".")] = asset.id
        for identity in identities:
            if identity.asset_id:
                by_value[identity.normalized_value.casefold().rstrip(".")] = identity.asset_id
                by_value[identity.original_value.casefold().rstrip(".")] = identity.asset_id
        text = "\n".join(
            [
                ticket.title,
                ticket.initial_description or "",
                *(item.body_text for item in ticket.articles),
                *ticket.tags,
            ]
        )
        lower = text.casefold()
        asset_values: dict[UUID, set[str]] = {}
        for value, asset_id in by_value.items():
            if value and re.search(rf"(?<![a-z0-9_.-]){re.escape(value)}(?![a-z0-9_.-])", lower):
                asset_values.setdefault(asset_id, set()).add(value)
        asset_ids = {str(asset_id) for asset_id in asset_values}
        title_lower = ticket.title.casefold()
        monitoring_language = bool(
            re.search(
                r"\b(?:loki|prometheus|monitoring|telemetry|logs?|metrics?|scrape|ingestion)\b",
                title_lower,
            )
        )
        relationships: list[dict[str, str]] = []
        for asset_id, values in asset_values.items():
            relationship = "mentioned_asset"
            confidence = "medium"
            matched = sorted(values, key=len, reverse=True)
            title_mentions = [value for value in matched if value in title_lower]
            if title_mentions:
                value = title_mentions[0]
                if monitoring_language and re.search(
                    rf"\b(?:logs?|metrics?|telemetry)\s+(?:from|for|of)\s+{re.escape(value)}\b|"
                    rf"\b{re.escape(value)}\s+(?:logs?|metrics?|telemetry)\b|"
                    rf"\b(?:delivery|collection|scrape)\s+(?:of|from|for)\s+{re.escape(value)}\b",
                    title_lower,
                ):
                    relationship = "monitoring_relationship"
                    confidence = "high"
                elif monitoring_language and re.search(
                    rf"\b(?:on|hosted on|running on)\s+{re.escape(value)}\b",
                    title_lower,
                ):
                    relationship = "hosting_asset"
                    confidence = "high"
                elif re.search(
                    rf"\b(?:depends? on|dependency on|provided by)\s+{re.escape(value)}\b",
                    title_lower,
                ):
                    relationship = "service_dependency"
                    confidence = "high"
                elif re.search(
                    rf"(?:^|\b){re.escape(value)}\b.*\b(?:cpu|memory|disk|filesystem|"
                    r"outage|down|unreachable|failed|failure|reboot|warning|critical)\b",
                    title_lower,
                ):
                    relationship = "primary_affected_asset"
                    confidence = "high"
                else:
                    relationship = "canonical_direct_match"
                    confidence = "medium"
            elif any(
                re.search(
                    rf"\b(?:affected|impact(?:ed|ing)?|degraded)\b.{{0,60}}\b{re.escape(value)}\b",
                    lower,
                )
                for value in matched
            ):
                relationship = "impacted_asset"
                confidence = "medium"
            relationships.append(
                {
                    "asset_id": str(asset_id),
                    "relationship": relationship,
                    "confidence": confidence,
                }
            )
        ips: set[str] = set()
        for raw in re.findall(
            r"(?<![\w:])(?:[0-9a-fA-F]*:[0-9a-fA-F:]+|(?:\d{1,3}\.){3}\d{1,3})(?![\w:])", text
        ):
            try:
                ips.add(str(ipaddress.ip_address(raw)))
            except ValueError:
                pass
        fqdns = {
            value.casefold().rstrip(".")
            for value in re.findall(
                r"\b[a-zA-Z0-9][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9-]*)+\b", text
            )
        }
        hosts = {
            value.casefold()
            for value in re.findall(
                r"\b(?=[a-zA-Z0-9-]*[a-zA-Z])(?=[a-zA-Z0-9-]*\d)"
                r"[a-zA-Z0-9][a-zA-Z0-9-]{1,62}\b",
                text,
            )
        }
        known_values = set(by_value)
        for reference in sorted((hosts | fqdns | ips) - known_values):
            relationships.append(
                {
                    "reference": reference,
                    "relationship": "unresolved_reference",
                    "confidence": "low",
                }
            )
        return replace(
            ticket,
            referenced_asset_ids=sorted(asset_ids),
            referenced_hostnames=sorted(hosts),
            referenced_fqdns=sorted(fqdns),
            referenced_ip_addresses=sorted(ips),
            asset_relationships=relationships,
            search_text=(ticket.search_text + "\n" + "\n".join([*hosts, *fqdns, *ips])).casefold(),
        )

    async def _upsert(
        self,
        configuration: ZammadConfigurationModel,
        ticket: NormalizedTicket,
        synchronized_at: datetime,
    ) -> ZammadTicketModel:
        integration = await self._integration_for_configuration(configuration.id)
        model = await self.session.scalar(
            select(ZammadTicketModel).where(
                ZammadTicketModel.integration_id == integration.id,
                ZammadTicketModel.source_record_id == ticket.external_id,
            )
        )
        if model is None:
            model = ZammadTicketModel(
                configuration_id=configuration.id,
                instance_key=configuration.instance_key,
                connector_id=integration.connector_id,
                integration_id=integration.id,
                source_record_id=ticket.external_id,
                source_updated_at=ticket.updated_at,
                synced_at=synchronized_at,
                cache_status="active",
                external_id=ticket.external_id,
                number=ticket.number,
                title=ticket.title,
                state=ticket.state,
                state_type=ticket.state_type,
                created_at_source=ticket.created_at,
                updated_at_source=ticket.updated_at,
                is_open=ticket.is_open,
            )
            self.session.add(model)
            await self.session.flush()
        for name, value in {
            "number": ticket.number,
            "title": ticket.title,
            "state": ticket.state,
            "state_type": ticket.state_type,
            "priority": ticket.priority,
            "group_name": ticket.group,
            "owner": ticket.owner,
            "customer": ticket.customer,
            "tags_json": ticket.tags,
            "created_at_source": ticket.created_at,
            "updated_at_source": ticket.updated_at,
            "closed_at": ticket.closed_at,
            "is_open": ticket.is_open,
            "ticket_type": ticket.ticket_type,
            "ticket_type_reason": ticket.ticket_type_reason,
            "initial_description": ticket.initial_description,
            "latest_update_text": ticket.latest_update_text,
            "latest_update_at": ticket.latest_update_at,
            "referenced_asset_ids_json": ticket.referenced_asset_ids,
            "referenced_hostnames_json": ticket.referenced_hostnames,
            "referenced_fqdns_json": ticket.referenced_fqdns,
            "referenced_ip_addresses_json": ticket.referenced_ip_addresses,
            "asset_relationships_json": ticket.asset_relationships,
            "search_text": ticket.search_text,
            "visible": True,
            "synchronized_at": synchronized_at,
            "connector_id": integration.connector_id,
            "integration_type": integration.integration_type,
            "integration_id": integration.id,
            "source_record_id": ticket.external_id,
            "source_updated_at": ticket.updated_at,
            "synced_at": synchronized_at,
            "cache_status": "active",
        }.items():
            setattr(model, name, value)
        integration.initial_sync_status = "completed"
        integration.last_successful_sync_at = synchronized_at
        existing = {
            item.external_id: item
            for item in (
                await self.session.scalars(
                    select(ZammadTicketArticleModel).where(
                        ZammadTicketArticleModel.ticket_id == model.id
                    )
                )
            ).all()
        }
        article_ids: set[str] = set()
        for article in ticket.articles:
            article_model = existing.get(article.external_id) or ZammadTicketArticleModel(
                ticket_id=model.id,
                external_id=article.external_id,
                created_at_source=article.created_at,
            )
            self.session.add(article_model)
            article_ids.add(article.external_id)
            article_values: dict[str, Any] = {
                "created_at_source": article.created_at,
                "updated_at_source": article.updated_at,
                "author": article.author,
                "sender": article.sender,
                "article_type": article.article_type,
                "internal": article.internal,
                "automated": article.automated,
                "subject": article.subject,
                "body_text": article.body_text,
                "raw_metadata_json": {"untrusted_evidence": True},
            }
            for name, value in article_values.items():
                setattr(article_model, name, value)
        if article_ids:
            await self.session.execute(
                delete(ZammadTicketArticleModel).where(
                    ZammadTicketArticleModel.ticket_id == model.id,
                    ZammadTicketArticleModel.external_id.not_in(article_ids),
                )
            )
        await self.session.flush()
        return model

    async def _ticket_rows(self, configuration_id: UUID) -> list[ZammadTicketModel]:
        integration = await self._integration_enabled_for_configuration(
            configuration_id, require_synced=True
        )
        return list(
            (
                await self.session.scalars(
                    select(ZammadTicketModel)
                    .where(
                        ZammadTicketModel.integration_id == integration.id,
                        ZammadTicketModel.cache_status == "active",
                        ZammadTicketModel.visible.is_(True),
                    )
                    .order_by(ZammadTicketModel.updated_at_source.desc())
                )
            ).all()
        )

    async def _find_ticket(
        self, configuration_id: UUID, identifier: str
    ) -> ZammadTicketModel | None:
        integration = await self._integration_enabled_for_configuration(
            configuration_id, require_synced=True
        )
        return cast(
            ZammadTicketModel | None,
            await self.session.scalar(
                select(ZammadTicketModel).where(
                    ZammadTicketModel.integration_id == integration.id,
                    ZammadTicketModel.cache_status == "active",
                    ZammadTicketModel.visible.is_(True),
                    or_(
                        ZammadTicketModel.number == identifier,
                        ZammadTicketModel.external_id == identifier,
                    ),
                )
            ),
        )

    async def _ticket_detail(self, row: ZammadTicketModel, base_url: str) -> dict[str, Any]:
        articles = list(
            (
                await self.session.scalars(
                    select(ZammadTicketArticleModel)
                    .where(ZammadTicketArticleModel.ticket_id == row.id)
                    .order_by(ZammadTicketArticleModel.created_at_source)
                )
            ).all()
        )
        return {
            **self._ticket_summary(row, base_url=base_url),
            "priority": row.priority,
            "owner": row.owner,
            "group": row.group_name,
            "customer": row.customer,
            "initial_description": row.initial_description,
            "created_at": row.created_at_source.isoformat(),
            "latest_update": {
                "text": row.latest_update_text,
                "at": row.latest_update_at.isoformat() if row.latest_update_at else None,
                "author": next(
                    (
                        item.author
                        for item in reversed(articles)
                        if item.body_text == row.latest_update_text
                    ),
                    None,
                ),
            },
            "articles": [
                {
                    "external_id": item.external_id,
                    "created_at": item.created_at_source.isoformat(),
                    "updated_at": item.updated_at_source.isoformat()
                    if item.updated_at_source
                    else None,
                    "author": item.author,
                    "sender": item.sender,
                    "article_type": item.article_type,
                    "internal": item.internal,
                    "automated": item.automated,
                    "subject": item.subject,
                    "body_text": item.body_text[:4000],
                    "content_trust": "untrusted_evidence",
                }
                for item in articles[-25:]
            ],
            "related_asset_ids": row.referenced_asset_ids_json,
            "asset_relationships": row.asset_relationships_json,
        }

    @staticmethod
    def _ticket_summary(
        row: ZammadTicketModel,
        *,
        base_url: str,
        relevance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = row.initial_description or row.latest_update_text or row.title
        summary = re.sub(r"(?im)^\s*(?:seed|fixture|debug)\s*(?:marker)?\s*:.*$", "", summary)
        summary = " ".join(summary.split())[:280]
        value = {
            "number": row.number,
            "ticket_number": row.number,
            "external_id": row.external_id,
            "title": row.title,
            "state": row.state,
            "state_type": row.state_type,
            "is_open": row.is_open,
            "ticket_type": row.ticket_type,
            "ticket_type_reason": row.ticket_type_reason,
            "updated_at": row.updated_at_source.isoformat(),
            "summary": summary,
            "latest_update": row.latest_update_text[:500] if row.latest_update_text else None,
            "related_asset_ids": row.referenced_asset_ids_json,
            "asset_relationships": row.asset_relationships_json,
            "web_url": ZammadService._ticket_web_url(base_url, row.external_id),
        }
        if relevance:
            value["relevance"] = relevance
        return value

    @staticmethod
    def _ticket_summary_for_asset(
        row: ZammadTicketModel, base_url: str, asset_id: UUID
    ) -> dict[str, Any]:
        value = ZammadService._ticket_summary(row, base_url=base_url)
        relationship = next(
            (
                item
                for item in row.asset_relationships_json
                if item.get("asset_id") == str(asset_id)
            ),
            None,
        )
        if relationship:
            value["relationship"] = relationship.get("relationship")
            value["relationship_confidence"] = relationship.get("confidence")
        return value

    @staticmethod
    def _ticket_web_url(base_url: str, external_id: str) -> str | None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        return f"{base_url.rstrip('/')}/#ticket/zoom/{quote(external_id, safe='')}"

    async def _resolve_asset_identifier(self, identifier: str) -> UUID | None:
        identity_type, normalized = endpoint_identity(identifier)
        candidate = (normalized or identifier).casefold().rstrip(".")
        asset = await self.session.scalar(
            select(InventoryAssetModel).where(
                or_(
                    InventoryAssetModel.canonical_name.ilike(candidate),
                    InventoryAssetModel.hostname.ilike(candidate),
                    InventoryAssetModel.fqdn.ilike(candidate),
                    InventoryAssetModel.primary_ip == candidate,
                )
            )
        )
        if asset:
            return asset.id
        identity = await self.session.scalar(
            select(InventoryIdentityModel).where(
                InventoryIdentityModel.normalized_value == candidate,
                InventoryIdentityModel.asset_id.is_not(None),
            )
        )
        return identity.asset_id if identity else None

    async def _asset_identity_values(self, asset_id: UUID) -> set[str]:
        asset = await self.session.get(InventoryAssetModel, asset_id)
        values = {
            str(value).casefold().rstrip(".")
            for value in (
                asset.canonical_name if asset else None,
                asset.hostname if asset else None,
                asset.fqdn if asset else None,
                asset.primary_ip if asset else None,
                *((asset.additional_ips_json or []) if asset else []),
            )
            if value
        }
        values.update(
            str(value).casefold().rstrip(".")
            for value in (
                await self.session.scalars(
                    select(InventoryIdentityModel.normalized_value).where(
                        InventoryIdentityModel.asset_id == asset_id
                    )
                )
            ).all()
            if value
        )
        return values

    async def _configuration(self, configuration_id: UUID) -> ZammadConfigurationModel:
        model = await self.session.get(ZammadConfigurationModel, configuration_id)
        if model is None:
            raise ZammadError("CONFIGURATION_NOT_FOUND", "Zammad configuration was not found.", 404)
        return model

    async def _enabled_configuration(self, *, require_enabled: bool) -> ZammadConfigurationModel:
        integration = await self._enabled_integration(require_synced=True)
        if integration.legacy_zammad_configuration_id is None:
            raise ZammadError(
                "ZAMMAD_CONFIGURATION_UNAVAILABLE",
                "The enabled Zammad integration does not have a configured adapter.",
                503,
            )
        model = await self._configuration(integration.legacy_zammad_configuration_id)
        if require_enabled and not model.enabled:
            raise ZammadError("ZAMMAD_DISABLED", "The Zammad integration is disabled.", 503)
        return model

    async def _enabled_integration(self, *, require_synced: bool) -> ConnectorIntegrationModel:
        await IntegrationService(self.session, self.encryption).bootstrap_legacy_integrations()
        connector_id = await IntegrationService(self.session, self.encryption).connector_id()
        integration = await self.session.scalar(
            select(ConnectorIntegrationModel)
            .where(
                ConnectorIntegrationModel.connector_id == connector_id,
                ConnectorIntegrationModel.integration_type == "zammad",
                ConnectorIntegrationModel.enabled.is_(True),
            )
            .order_by(ConnectorIntegrationModel.created_at)
        )
        if integration is None:
            raise ZammadError(
                "TICKETING_PROVIDER_UNAVAILABLE",
                "No enabled Zammad integration is configured.",
                503,
            )
        if require_synced and integration.initial_sync_status != "completed":
            raise ZammadError(
                "TICKETING_INITIAL_SYNC_INCOMPLETE",
                "Zammad is enabled, but its initial synchronization has not completed.",
                503,
            )
        return integration

    async def _integration_enabled_for_configuration(
        self, configuration_id: UUID, *, require_synced: bool
    ) -> ConnectorIntegrationModel:
        integration = await self._integration_for_configuration(configuration_id)
        if not integration.enabled:
            raise ZammadError("ZAMMAD_DISABLED", "The Zammad integration is disabled.", 503)
        if require_synced and integration.initial_sync_status != "completed":
            raise ZammadError(
                "TICKETING_INITIAL_SYNC_INCOMPLETE",
                "Zammad is enabled, but its initial synchronization has not completed.",
                503,
            )
        return integration

    async def _integration_for_configuration(
        self, configuration_id: UUID
    ) -> ConnectorIntegrationModel:
        await IntegrationService(self.session, self.encryption).bootstrap_legacy_integrations()
        integration = await self.session.scalar(
            select(ConnectorIntegrationModel).where(
                ConnectorIntegrationModel.legacy_zammad_configuration_id == configuration_id
            )
        )
        if integration is None:
            raise ZammadError(
                "INTEGRATION_NOT_FOUND", "Zammad integration record was not found.", 503
            )
        return integration

    def _client(self, model: ZammadConfigurationModel) -> ZammadClient:
        if not model.encrypted_access_token:
            raise ZammadError(
                "ACCESS_TOKEN_REQUIRED", "The Zammad access token is not configured.", 503
            )
        return ZammadClient(model, self.encryption.decrypt(model.encrypted_access_token))

    def _availability(self, model: ZammadConfigurationModel) -> dict[str, Any]:
        return {
            "enabled": model.enabled,
            "state": model.connection_state,
            "cache_timestamp": model.last_successful_sync_at.isoformat()
            if model.last_successful_sync_at
            else None,
            "stale": not model.last_successful_sync_at
            or datetime.now(UTC) - model.last_successful_sync_at
            > timedelta(seconds=model.sync_interval_seconds * 2),
            "retention_days": model.history_window_days,
            "last_error": model.last_error,
        }

    def _cached_result(
        self, model: ZammadConfigurationModel, result: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **result,
            "live": False,
            "cache_timestamp": model.last_successful_sync_at.isoformat()
            if model.last_successful_sync_at
            else None,
            "availability": self._availability(model),
        }

    @staticmethod
    def _configuration_response(model: ZammadConfigurationModel) -> dict[str, Any]:
        return {
            "id": str(model.id),
            "name": model.name,
            "base_url": model.base_url,
            "token_configured": bool(model.encrypted_access_token),
            "tls_verify": model.tls_verify,
            "request_timeout_seconds": model.request_timeout_seconds,
            "sync_interval_seconds": model.sync_interval_seconds,
            "history_window_days": model.history_window_days,
            "group_filters": model.group_filters_json,
            "include_closed_tickets": model.include_closed_tickets,
            "enabled": model.enabled,
            "connection_state": model.connection_state,
            "last_successful_test_at": model.last_successful_test_at,
            "last_successful_sync_at": model.last_successful_sync_at,
            "last_sync_duration_seconds": model.last_sync_duration_seconds,
            "synchronized_ticket_count": model.synchronized_ticket_count,
            "synchronized_article_count": model.synchronized_article_count,
            "last_error": model.last_error,
            "next_scheduled_sync_at": model.next_scheduled_sync_at,
        }
