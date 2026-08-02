"""Connector-local Loki discovery, correlation, and allow-listed evidence queries."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.certificates import TrustedCertificateService
from app.application.services.inventory import endpoint_identity, normalize_hostname
from app.core.config import Settings, get_settings
from app.core.logging import sanitize
from app.infrastructure.database.models.inventory import (
    InventoryAssetModel,
    InventoryIdentityModel,
    InventoryServiceModel,
    LokiConfigurationModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService


class LokiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_EVIDENCE_FILTERS: dict[str, tuple[str, str]] = {
    "errors": ("error", r"(?i)\b(error|fatal|critical|failed|failure)\b"),
    "warnings": ("warning", r"(?i)\bwarn(?:ing)?\b"),
    "restarts": (
        "warning",
        r"(?i)\b(restart(?:ed|ing)?|scheduled restart|restart job)\b",
    ),
    "crashes": ("critical", r"(?i)\b(panic|segfault|core dumped|crash(?:ed)?)\b"),
    "exceptions": ("error", r"(?i)\b(exception|traceback|stack trace)\b"),
    "auth_failures": (
        "warning",
        r"(?i)\b(authentication failure|failed password|invalid user|login failed|"
        r"access denied|pam_.+authentication)\b",
    ),
    "kernel": (
        "warning",
        r"(?i)\b(kernel|call trace|soft lockup|hard lockup|machine check)\b",
    ),
    "filesystem": (
        "error",
        r"(?i)\b(no space left|read-only file system|filesystem error|i/o error|"
        r"ext[234].*error|xfs.*error)\b",
    ),
    "oom": (
        "critical",
        r"(?i)\b(out of memory|oom-kill(?:er)?|killed process .+ memory)\b",
    ),
    "application_failures": (
        "error",
        r"(?i)\b(application|service|process).*\b(failed|failure|fatal|terminated)\b",
    ),
}


def validate_loki_base_url(value: str) -> str:
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
        raise LokiError(
            "INVALID_URL",
            "Loki URL must be an HTTP(S) base URL without credentials, query, or fragment.",
        )
    return clean


def loki_endpoint_warnings(value: str) -> list[str]:
    parsed = urlparse(value)
    if parsed.scheme != "http":
        return []
    hostname = parsed.hostname or ""
    normalized_hostname = hostname.casefold().rstrip(".")
    internal = (
        normalized_hostname == "localhost"
        or "." not in normalized_hostname
        or normalized_hostname.endswith((".internal", ".local", ".localhost"))
    )
    try:
        address = ipaddress.ip_address(hostname)
        internal = address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        pass
    scope = "internal" if internal else "public"
    return [
        f"This {scope} Loki endpoint uses unencrypted HTTP. "
        "Credentials and log evidence are not protected in transit."
    ]


def _escape_logql(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _selector(labels: dict[str, Any]) -> str:
    usable = {
        str(key): value
        for key, value in labels.items()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))
        and value is not None
        and str(value) != ""
    }
    if not usable:
        raise LokiError("LOKI_STREAM_NOT_FOUND", "The discovered Loki stream has no usable labels.")
    matchers = ",".join(f'{key}="{_escape_logql(usable[key])}"' for key in sorted(usable))
    return "{" + matchers + "}"


def _epoch_ns(value: datetime) -> str:
    return str(int(value.timestamp() * 1_000_000_000))


def _normalized_candidates(value: object) -> set[str]:
    original = str(value or "").strip()
    if not original:
        return set()
    candidates = {original.casefold().rstrip(".")}
    identity_type, normalized = endpoint_identity(original)
    if identity_type and normalized:
        candidates.add(normalized.casefold().rstrip("."))
        if identity_type == "fqdn":
            _, short = normalize_hostname(normalized)
            if short:
                candidates.add(short)
    return candidates


class LokiService:
    def __init__(
        self,
        session: AsyncSession,
        encryption: SecretEncryptionService,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.encryption = encryption
        self.settings = settings or get_settings()

    async def list_configurations(self) -> list[dict[str, Any]]:
        configurations = list(
            (
                await self.session.scalars(
                    select(LokiConfigurationModel).order_by(LokiConfigurationModel.name)
                )
            ).all()
        )
        return [self._response(item) for item in configurations]

    async def save(
        self,
        configuration_id: UUID | None,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        model = (
            await self.session.get(LokiConfigurationModel, configuration_id)
            if configuration_id
            else LokiConfigurationModel()
        )
        if configuration_id and model is None:
            raise LokiError("CONFIGURATION_NOT_FOUND", "Configuration not found.", 404)
        assert model is not None
        model.name = str(values["name"]).strip()
        model.base_url = validate_loki_base_url(str(values["base_url"]))
        model.auth_type = str(values.get("auth_type", "none"))
        if model.auth_type not in {"none", "basic", "bearer"}:
            raise LokiError("INVALID_AUTH_TYPE", "Unsupported authentication type.")
        model.username = (
            str(values.get("username") or "").strip() or None
            if model.auth_type == "basic"
            else None
        )
        secret = str(values.get("secret") or "")
        if secret:
            if not self.encryption.ready:
                raise LokiError(
                    "ENCRYPTION_KEY_REQUIRED",
                    "The connector encryption key is required to store credentials.",
                    503,
                )
            model.encrypted_secret = self.encryption.encrypt(secret)
        elif model.auth_type == "none":
            model.encrypted_secret = None
        elif not model.encrypted_secret:
            raise LokiError("SECRET_REQUIRED", "Authentication secret is required.")
        model.tls_verify = bool(values.get("tls_verify", True))
        model.request_timeout_seconds = float(values.get("request_timeout_seconds", 10))
        if not 1 <= model.request_timeout_seconds <= 120:
            raise LokiError("INVALID_TIMEOUT", "Timeout must be between 1 and 120 seconds.")
        model.discovery_lookback_days = int(values.get("discovery_lookback_days", 30))
        if not 1 <= model.discovery_lookback_days <= 90:
            raise LokiError("INVALID_LOOKBACK", "Discovery lookback must be between 1 and 90 days.")
        model.enabled = bool(values.get("enabled", True))
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return self._response(model)

    async def delete(self, configuration_id: UUID) -> None:
        model = await self._get(configuration_id)
        await self.session.delete(model)
        await self.session.commit()

    async def test(self, configuration_id: UUID) -> dict[str, Any]:
        configuration = await self._get(configuration_id)
        build = await self._request(
            configuration, "/loki/api/v1/status/buildinfo", require_loki_envelope=False
        )
        schema = await self.discover(configuration_id)
        sample_validated = False
        sample_stream = next(iter(schema.get("streams") or []), None)
        sample_window = next(iter(schema.get("stream_windows") or []), None)
        if isinstance(sample_stream, dict) and isinstance(sample_window, dict):
            await self._query_range(
                configuration,
                _selector(sample_stream),
                datetime.fromisoformat(str(sample_window["start"])),
                datetime.fromisoformat(str(sample_window["end"])),
                limit=1,
            )
            sample_validated = True
        configuration.last_successful_test_at = datetime.now(UTC)
        configuration.last_error = None
        await self.session.commit()
        return {
            "success": True,
            "message": "Loki connection, discovery, and fixed LogQL validation succeeded.",
            "version": build.get("version"),
            "labels": schema["labels"],
            "stream_count": schema["stream_count"],
            "sample_query_validated": sample_validated,
            "warnings": loki_endpoint_warnings(configuration.base_url),
        }

    async def discover(self, configuration_id: UUID) -> dict[str, Any]:
        configuration = await self._get(configuration_id)
        try:
            labels_payload = await self._request(configuration, "/loki/api/v1/labels")
            labels = sorted(
                str(value) for value in labels_payload.get("data", []) if isinstance(value, str)
            )
            values: dict[str, list[str]] = {}
            for label in labels:
                payload = await self._request(
                    configuration,
                    f"/loki/api/v1/label/{quote(label, safe='')}/values",
                )
                values[label] = [str(value) for value in payload.get("data", [])[:500]]

            now = datetime.now(UTC)
            streams_by_key: dict[str, dict[str, Any]] = {}
            stream_windows: dict[str, dict[str, str]] = {}
            if not labels:
                raise LokiError(
                    "LOKI_LABELS_NOT_FOUND",
                    "Loki is reachable but exposes no stream labels in the configured tenant.",
                )
            selector_labels = [
                label for label in labels if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label)
            ]
            if not selector_labels:
                raise LokiError(
                    "LOKI_LABELS_INVALID",
                    "Loki exposes no label name that can be used safely for discovery.",
                )
            # Loki 2.9 can reject broad TSDB series scans. Daily windows are bounded,
            # deterministic, and cover streams that do not share any one label.
            discovery_selectors = ["{" + label + '=~".+"}' for label in selector_labels]
            for offset in range(configuration.discovery_lookback_days):
                end = now - timedelta(days=offset)
                start = end - timedelta(days=1)
                params = [
                    *[("match[]", selector) for selector in discovery_selectors],
                    ("start", _epoch_ns(start)),
                    ("end", _epoch_ns(end)),
                ]
                payload = await self._request(
                    configuration,
                    "/loki/api/v1/series",
                    params,
                )
                for raw in payload.get("data", []):
                    if not isinstance(raw, dict):
                        continue
                    labels_map = {
                        str(key): str(value) for key, value in raw.items() if value is not None
                    }
                    key = sha256(json.dumps(labels_map, sort_keys=True).encode()).hexdigest()
                    streams_by_key[key] = labels_map
                    stream_windows.setdefault(
                        key,
                        {"start": start.isoformat(), "end": end.isoformat()},
                    )
            schema = {
                "labels": labels,
                "label_values": values,
                "streams": list(streams_by_key.values()),
                "stream_windows": [
                    {"stream_key": key, **stream_windows[key]} for key in streams_by_key
                ],
                "stream_count": len(streams_by_key),
                "discovered_at": now.isoformat(),
                "lookback_days": configuration.discovery_lookback_days,
            }
            configuration.discovered_schema_json = schema
            configuration.stream_count = len(streams_by_key)
            configuration.last_successful_discovery_at = now
            configuration.last_error = None
            await self.session.commit()
            return schema
        except LokiError as exc:
            configuration.last_failed_discovery_at = datetime.now(UTC)
            configuration.last_error = str(exc)[:2000]
            await self.session.commit()
            raise

    async def asset_evidence(
        self,
        asset: InventoryAssetModel,
        *,
        lookback_hours: int = 24,
        categories: list[str] | None = None,
        limit_per_category: int = 5,
    ) -> dict[str, Any]:
        if not 1 <= lookback_hours <= 720:
            raise LokiError("INVALID_LOOKBACK", "Evidence lookback must be 1 to 720 hours.")
        requested = categories or list(_EVIDENCE_FILTERS)
        invalid = [item for item in requested if item not in _EVIDENCE_FILTERS]
        if invalid:
            raise LokiError(
                "UNSUPPORTED_EVIDENCE_CATEGORY",
                f"Unsupported evidence category: {invalid[0]}.",
            )
        configuration = await self.session.scalar(
            select(LokiConfigurationModel)
            .where(LokiConfigurationModel.enabled.is_(True))
            .order_by(LokiConfigurationModel.last_successful_discovery_at.desc())
        )
        if configuration is None:
            return self._unavailable("LOKI_NOT_CONFIGURED", "Loki is not configured.")
        schema = configuration.discovered_schema_json or {}
        if not schema.get("streams"):
            schema = await self.discover(configuration.id)
        candidates, candidate_kinds = await self._asset_candidates(asset)
        matches: list[dict[str, Any]] = []
        for stream in schema.get("streams") or []:
            if not isinstance(stream, dict):
                continue
            matched = [
                {
                    "label": str(label),
                    "value": str(value),
                    "normalized": sorted(_normalized_candidates(value) & candidates),
                }
                for label, value in stream.items()
                if _normalized_candidates(value) & candidates
            ]
            if matched:
                matches.append({"labels": stream, "matched_by": matched})
        if not matches:
            return {
                **self._unavailable(
                    "LOKI_STREAM_NOT_FOUND",
                    "No Loki stream could be correlated to this asset from discovered labels.",
                ),
                "schema_discovered": True,
                "discovered_labels": schema.get("labels") or [],
                "asset_candidates": sorted(candidates),
                "candidate_sources": candidate_kinds,
                "matched_streams": [],
            }

        end = datetime.now(UTC)
        start = end - timedelta(hours=lookback_hours)
        evidence: list[dict[str, Any]] = []
        query_errors: list[dict[str, str]] = []
        for match in matches:
            selector = _selector(match["labels"])
            for category in requested:
                severity, expression = _EVIDENCE_FILTERS[category]
                query = f'{selector} |~ "{_escape_logql(expression)}"'
                try:
                    payload = await self._query_range(
                        configuration,
                        query,
                        start,
                        end,
                        limit=limit_per_category,
                    )
                except LokiError as exc:
                    query_errors.append({"code": exc.code, "message": str(exc)})
                    continue
                evidence.extend(
                    self._parse_evidence(
                        payload,
                        category=category,
                        severity=severity,
                        matched_by=match["matched_by"],
                    )
                )
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in evidence:
            key = (item["observed_at"], item["category"], item["summary"])
            unique[key] = item
        timeline = sorted(unique.values(), key=lambda item: item["observed_at"], reverse=True)
        last_log_at = max(
            (item["observed_at"] for item in timeline),
            default=None,
        )
        return {
            "available": not query_errors or bool(timeline),
            "error_code": query_errors[0]["code"] if query_errors and not timeline else None,
            "unavailable_reason": (
                query_errors[0]["message"] if query_errors and not timeline else None
            ),
            "source": "loki",
            "configuration": configuration.name,
            "lookback_hours": lookback_hours,
            "matched_streams": matches,
            "evidence": timeline,
            "counts_by_category": {
                category: sum(1 for item in timeline if item["category"] == category)
                for category in requested
            },
            "last_log_at": last_log_at,
            "query_errors": query_errors,
        }

    async def _asset_candidates(
        self, asset: InventoryAssetModel
    ) -> tuple[set[str], dict[str, list[str]]]:
        by_source: dict[str, list[str]] = {
            "canonical": [
                value
                for value in (
                    asset.canonical_name,
                    asset.hostname,
                    asset.fqdn,
                    asset.primary_ip,
                )
                if value
            ],
            "identity": [],
            "service": [],
        }
        identities = list(
            (
                await self.session.scalars(
                    select(InventoryIdentityModel).where(
                        InventoryIdentityModel.asset_id == asset.id
                    )
                )
            ).all()
        )
        by_source["identity"] = [
            value
            for item in identities
            for value in (item.original_value, item.normalized_value)
            if value
        ]
        services = list(
            (
                await self.session.scalars(
                    select(InventoryServiceModel).where(InventoryServiceModel.asset_id == asset.id)
                )
            ).all()
        )
        by_source["service"] = [
            str(value) for item in services for value in (item.name, item.endpoint) if value
        ]
        candidates = {
            normalized
            for values in by_source.values()
            for value in values
            for normalized in _normalized_candidates(value)
        }
        return candidates, by_source

    @staticmethod
    def _parse_evidence(
        payload: dict[str, Any],
        *,
        category: str,
        severity: str,
        matched_by: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        result = payload.get("data", {}).get("result", [])
        for stream in result if isinstance(result, list) else []:
            if not isinstance(stream, dict):
                continue
            labels = stream.get("stream") if isinstance(stream.get("stream"), dict) else {}
            values = stream.get("values") if isinstance(stream.get("values"), list) else []
            for raw in values:
                if not isinstance(raw, list) or len(raw) < 2:
                    continue
                try:
                    observed = datetime.fromtimestamp(int(raw[0]) / 1_000_000_000, UTC)
                except (TypeError, ValueError, OverflowError):
                    continue
                message = str(raw[1]).strip()
                if not _message_matches_category(category, message):
                    continue
                items.append(
                    {
                        "source": "loki",
                        "category": category,
                        "severity": severity,
                        "observed_at": observed.isoformat(),
                        "summary": sanitize(message)[:1000],
                        "stream_labels": labels,
                        "correlation_evidence": matched_by,
                    }
                )
        return items

    async def _query_range(
        self,
        configuration: LokiConfigurationModel,
        query: str,
        start: datetime,
        end: datetime,
        *,
        limit: int,
    ) -> dict[str, Any]:
        return await self._request(
            configuration,
            "/loki/api/v1/query_range",
            {
                "query": query,
                "start": _epoch_ns(start),
                "end": _epoch_ns(end),
                "limit": str(max(1, min(limit, 100))),
                "direction": "backward",
            },
        )

    async def _request(
        self,
        configuration: LokiConfigurationModel,
        path: str,
        params: dict[str, str] | list[tuple[str, str]] | None = None,
        *,
        require_loki_envelope: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {"Accept": "application/json"}
        auth: httpx.BasicAuth | None = None
        if configuration.auth_type != "none":
            if not configuration.encrypted_secret:
                raise LokiError("SECRET_REQUIRED", "Stored authentication is incomplete.")
            secret = self.encryption.decrypt(configuration.encrypted_secret)
            if configuration.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {secret}"
            else:
                auth = httpx.BasicAuth(configuration.username or "", secret)
        try:
            verify: bool | ssl.SSLContext = configuration.tls_verify
            if configuration.tls_verify:
                verify = await TrustedCertificateService(self.session, self.settings).ssl_context()
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(configuration.request_timeout_seconds),
                verify=verify,
                follow_redirects=False,
                auth=auth,
                headers=headers,
            ) as client:
                response = await client.get(
                    urljoin(f"{configuration.base_url}/", path.lstrip("/")),
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise LokiError("TIMEOUT", "Loki request timed out.", 504) from exc
        except httpx.HTTPStatusError as exc:
            try:
                detail = sanitize(str(exc.response.json().get("error") or ""))
            except ValueError:
                detail = ""
            if exc.response.status_code in {401, 403}:
                code, message = (
                    "AUTHENTICATION_FAILED",
                    "Loki rejected the configured credentials.",
                )
            elif exc.response.status_code in {400, 422}:
                code, message = (
                    "LOKI_QUERY_REJECTED",
                    "Loki rejected a fixed connector query" + (f": {detail}" if detail else "."),
                )
            elif exc.response.status_code == 429:
                code, message = (
                    "LOKI_QUERY_LIMITED",
                    "Loki limited the bounded evidence query.",
                )
            else:
                code, message = (
                    "HTTP_ERROR",
                    f"Loki returned HTTP {exc.response.status_code}.",
                )
            raise LokiError(code, message[:500], 502) from exc
        except httpx.HTTPError as exc:
            raise self._network_error(exc) from exc
        except ValueError as exc:
            raise LokiError(
                "INVALID_LOKI_RESPONSE",
                "Loki returned a response that is not valid JSON.",
                502,
            ) from exc
        if not isinstance(payload, dict) or (
            require_loki_envelope and payload.get("status") != "success"
        ):
            raise LokiError("INVALID_LOKI_RESPONSE", "Loki returned an invalid response.", 502)
        return payload

    @staticmethod
    def _network_error(exc: Exception) -> LokiError:
        detail = str(exc).casefold()
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                return LokiError(
                    "DNS_RESOLUTION_FAILED", "Loki hostname could not be resolved.", 502
                )
            if isinstance(cause, ConnectionRefusedError):
                return LokiError(
                    "CONNECTION_REFUSED", "The Loki host refused the TCP connection.", 502
                )
            if isinstance(cause, ssl.SSLCertVerificationError):
                return LokiError(
                    "TLS_CERTIFICATE_NOT_TRUSTED",
                    "The Loki TLS certificate is not trusted.",
                    502,
                )
            cause = cause.__cause__ or cause.__context__
        if "connection refused" in detail:
            return LokiError("CONNECTION_REFUSED", "The Loki host refused the TCP connection.", 502)
        return LokiError("CONNECTION_FAILED", "Loki could not be reached.", 502)

    async def _get(self, configuration_id: UUID) -> LokiConfigurationModel:
        configuration = await self.session.get(LokiConfigurationModel, configuration_id)
        if configuration is None:
            raise LokiError("CONFIGURATION_NOT_FOUND", "Configuration not found.", 404)
        return configuration

    @staticmethod
    def _unavailable(code: str, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "source": "loki",
            "error_code": code,
            "unavailable_reason": reason,
            "evidence": [],
            "counts_by_category": {},
            "last_log_at": None,
        }

    @staticmethod
    def _response(item: LokiConfigurationModel) -> dict[str, Any]:
        schema = item.discovered_schema_json or {}
        return {
            "id": item.id,
            "name": item.name,
            "base_url": item.base_url,
            "auth_type": item.auth_type,
            "username": item.username,
            "has_secret": bool(item.encrypted_secret),
            "tls_verify": item.tls_verify,
            "request_timeout_seconds": item.request_timeout_seconds,
            "enabled": item.enabled,
            "discovery_lookback_days": item.discovery_lookback_days,
            "last_successful_test_at": item.last_successful_test_at,
            "last_successful_discovery_at": item.last_successful_discovery_at,
            "last_failed_discovery_at": item.last_failed_discovery_at,
            "last_error": item.last_error,
            "stream_count": item.stream_count,
            "labels": schema.get("labels") or [],
            "label_values": schema.get("label_values") or {},
            "warnings": loki_endpoint_warnings(item.base_url),
        }


def _message_matches_category(category: str, message: str) -> bool:
    """Reject lexical LogQL matches that do not express the requested event."""
    lower = message.casefold()
    structured_error = bool(re.search(r"\blevel\s*=\s*[\"']?(?:error|fatal|critical)\b", lower))
    normal_lifecycle = bool(
        re.search(
            r"^(?:starting|started|finished|stopping|stopped)\s+|"
            r"\bsession (?:opened|closed)\b|\bloaded kernel module\b",
            lower,
        )
    )
    if normal_lifecycle and not structured_error:
        return False
    if category == "errors":
        return structured_error or bool(
            re.search(
                r"\b(fatal|critical|failure|failed to|failed with|"
                r"entered failed state|error:|error while|error occurred)\b",
                lower,
            )
        )
    if category == "application_failures":
        return bool(
            re.search(
                r"\b(failed to start|entered failed state|main process exited|"
                r"terminated unexpectedly|application failure|fatal application error)\b",
                lower,
            )
        )
    if category == "warnings":
        return bool(re.search(r"\b(level\s*=\s*[\"']?warn|warning|warn:)\b", lower))
    if category == "kernel":
        return bool(
            re.search(
                r"\b(call trace|soft lockup|hard lockup|machine check|kernel panic|"
                r"kernel bug|kernel oops)\b",
                lower,
            )
        )
    return True
