import asyncio
import hashlib
import ipaddress
import json
import socket
import ssl
import time
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.certificates import TrustedCertificateService
from app.application.services.inventory import (
    InventoryService,
    endpoint_identity,
    normalize_hostname,
    row_checksum,
)
from app.core.config import Settings, get_settings
from app.core.logging import sanitize
from app.infrastructure.database.models.inventory import (
    InventoryObservationModel,
    PrometheusConfigurationModel,
)
from app.infrastructure.security.secrets import SecretEncryptionService


class PrometheusError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def validate_base_url(value: str) -> str:
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
        raise PrometheusError(
            "INVALID_URL",
            "Prometheus URL must be an HTTP(S) base URL without credentials, query, or fragment.",
        )
    return clean


def endpoint_warnings(value: str) -> list[str]:
    parsed = urlparse(value)
    if parsed.scheme != "http":
        return []
    hostname = parsed.hostname or ""
    internal = hostname.casefold() == "localhost" or "." not in hostname
    try:
        address = ipaddress.ip_address(hostname)
        internal = address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        pass
    if internal:
        return [
            "This internal Prometheus endpoint uses unencrypted HTTP. "
            "Credentials and metrics metadata are not protected in transit."
        ]
    return ["This Prometheus endpoint uses unencrypted public HTTP. HTTPS is strongly recommended."]


def target_id(configuration_id: UUID, target: dict[str, Any]) -> str:
    labels = (
        cast(dict[str, Any], target.get("labels")) if isinstance(target.get("labels"), dict) else {}
    )
    discovered = (
        cast(dict[str, Any], target.get("discoveredLabels"))
        if isinstance(target.get("discoveredLabels"), dict)
        else {}
    )
    identity = {
        "configuration_id": str(configuration_id),
        "scrape_url": target.get("scrapeUrl"),
        "global_url": target.get("globalUrl"),
        "job": labels.get("job"),
        "instance": labels.get("instance"),
        "discovered_address": discovered.get("__address__"),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def target_identities(target: dict[str, Any]) -> list[tuple[str, str, str]]:
    labels = (
        cast(dict[str, Any], target.get("labels")) if isinstance(target.get("labels"), dict) else {}
    )
    discovered = (
        cast(dict[str, Any], target.get("discoveredLabels"))
        if isinstance(target.get("discoveredLabels"), dict)
        else {}
    )
    candidates: list[object] = [
        labels.get("instance"),
        target.get("scrapeUrl"),
        target.get("globalUrl"),
        discovered.get("__address__"),
    ]
    host_label_names = {
        "hostname",
        "host",
        "fqdn",
        "node",
        "nodename",
        "instance_name",
        "__meta_kubernetes_node_name",
        "__meta_gce_instance_name",
    }
    for source in (discovered, labels):
        candidates.extend(
            value for key, value in source.items() if key.casefold() in host_label_names
        )
    identities: list[tuple[str, str, str]] = []
    for candidate in candidates:
        if candidate is None:
            continue
        original = str(candidate).strip()
        identity_type, normalized = endpoint_identity(original)
        if identity_type and normalized:
            identities.append((identity_type, original, normalized))
            if identity_type == "fqdn":
                _, short = normalize_hostname(normalized)
                if short:
                    identities.append(("hostname", original, short))
    for identity_type, labels_key in (
        ("cloud_instance_id", "cloud_instance_id"),
        ("asset_tag", "asset_tag"),
        ("serial_number", "serial_number"),
    ):
        value = labels.get(labels_key) or discovered.get(labels_key)
        if value:
            original = str(value).strip()
            normalized = original.casefold() if identity_type != "serial_number" else original
            identities.append((identity_type, original, normalized))
    return list(dict.fromkeys(identities))


class PrometheusService:
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
        items = list(
            (
                await self.session.scalars(
                    select(PrometheusConfigurationModel).order_by(PrometheusConfigurationModel.name)
                )
            ).all()
        )
        return [self._response(item) for item in items]

    async def save(
        self,
        configuration_id: UUID | None,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        model = (
            await self.session.get(PrometheusConfigurationModel, configuration_id)
            if configuration_id
            else PrometheusConfigurationModel()
        )
        if configuration_id and not model:
            raise PrometheusError("CONFIGURATION_NOT_FOUND", "Configuration not found.", 404)
        assert model is not None
        model.name = str(values["name"]).strip()
        model.base_url = validate_base_url(str(values["base_url"]))
        model.auth_type = str(values.get("auth_type", "none"))
        if model.auth_type not in {"none", "basic", "bearer"}:
            raise PrometheusError("INVALID_AUTH_TYPE", "Unsupported authentication type.")
        model.username = (
            str(values.get("username") or "").strip() or None
            if model.auth_type == "basic"
            else None
        )
        secret = str(values.get("secret") or "")
        if secret:
            if not self.encryption.ready:
                raise PrometheusError(
                    "ENCRYPTION_KEY_REQUIRED",
                    "The connector encryption key is required to store credentials.",
                    503,
                )
            model.encrypted_secret = self.encryption.encrypt(secret)
        elif model.auth_type == "none":
            model.encrypted_secret = None
        elif not model.encrypted_secret:
            raise PrometheusError("SECRET_REQUIRED", "Authentication secret is required.")
        model.tls_verify = bool(values.get("tls_verify", True))
        model.request_timeout_seconds = float(values.get("request_timeout_seconds", 10))
        if not 1 <= model.request_timeout_seconds <= 120:
            raise PrometheusError("INVALID_TIMEOUT", "Timeout must be between 1 and 120 seconds.")
        model.scan_interval_seconds = int(values.get("scan_interval_seconds", 300))
        if not 30 <= model.scan_interval_seconds <= 86400:
            raise PrometheusError(
                "INVALID_SCAN_INTERVAL", "Scan interval must be between 30 and 86400 seconds."
            )
        model.enabled = bool(values.get("enabled", True))
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return self._response(model)

    async def test(self, configuration_id: UUID) -> dict[str, Any]:
        configuration = await self._get(configuration_id)
        payload = await self._request(configuration, "/api/v1/status/buildinfo")
        return {
            "success": True,
            "message": "Prometheus connection succeeded.",
            "version": payload.get("data", {}).get("version"),
            "warnings": endpoint_warnings(configuration.base_url),
        }

    async def diagnose(self, configuration_id: UUID) -> dict[str, Any]:
        configuration = await self._get(configuration_id)
        parsed = urlparse(configuration.base_url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        timeout = configuration.request_timeout_seconds
        stages: list[dict[str, Any]] = []

        async def stage(name: str, operation: Any) -> bool:
            started = time.perf_counter()
            try:
                detail = await asyncio.wait_for(operation(), timeout=timeout)
                stages.append(
                    {
                        "stage": name,
                        "status": "success",
                        "message": str(detail),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
                return True
            except Exception as exc:
                error = self._network_error(exc)
                stages.append(
                    {
                        "stage": name,
                        "status": "failed",
                        "code": error.code,
                        "message": str(error),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
                return False

        async def dns() -> str:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            )
            unique = list(dict.fromkeys(item[4][0] for item in addresses))
            return f"Resolved {hostname} to {', '.join(unique[:4])}"

        async def tcp() -> str:
            reader, writer = await asyncio.open_connection(hostname, port)
            del reader
            writer.close()
            await writer.wait_closed()
            return f"TCP connection to {hostname}:{port} succeeded"

        async def tls() -> str:
            context = (
                await TrustedCertificateService(self.session, self.settings).ssl_context()
                if configuration.tls_verify
                else ssl._create_unverified_context()
            )
            reader, writer = await asyncio.open_connection(
                hostname, port, ssl=context, server_hostname=hostname
            )
            del reader
            writer.close()
            await writer.wait_closed()
            return (
                "TLS handshake and certificate verification succeeded"
                if configuration.tls_verify
                else "TLS handshake succeeded; certificate verification is disabled"
            )

        if not await stage("DNS", dns):
            return {
                "success": False,
                "stages": stages,
                "warnings": endpoint_warnings(configuration.base_url),
            }
        if not await stage("TCP", tcp):
            return {
                "success": False,
                "stages": stages,
                "warnings": endpoint_warnings(configuration.base_url),
            }
        if parsed.scheme == "https" and not await stage("TLS", tls):
            return {
                "success": False,
                "stages": stages,
                "warnings": endpoint_warnings(configuration.base_url),
            }

        async def http() -> str:
            payload = await self._request(configuration, "/api/v1/status/buildinfo")
            version = payload.get("data", {}).get("version")
            suffix = f" (version {version})" if version else ""
            return f"Prometheus HTTP API returned a valid response{suffix}"

        success = await stage("HTTP", http)
        return {
            "success": success,
            "stages": stages,
            "warnings": endpoint_warnings(configuration.base_url),
        }

    async def scan(self, configuration_id: UUID) -> dict[str, Any]:
        configuration = await self._get(configuration_id)
        now = datetime.now(UTC)
        try:
            payload = await self._request(configuration, "/api/v1/targets?state=active")
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("activeTargets"), list):
                raise PrometheusError(
                    "MALFORMED_RESPONSE", "Prometheus returned malformed active-target data.", 502
                )
            targets = data["activeTargets"]
            inventory = InventoryService(self.session)
            healthy = 0
            ambiguous = 0
            unmatched = 0
            for target in targets:
                if not isinstance(target, dict):
                    raise PrometheusError(
                        "MALFORMED_RESPONSE", "Prometheus returned a malformed target.", 502
                    )
                health = str(target.get("health") or "unknown")
                healthy += health == "up"
                source_record_id = target_id(configuration.id, target)
                observation = await self.session.scalar(
                    select(InventoryObservationModel).where(
                        InventoryObservationModel.source_type == "prometheus",
                        InventoryObservationModel.source_record_id == source_record_id,
                    )
                )
                fields = self._fields(target)
                checksum = row_checksum(fields)
                if observation is None:
                    observation = InventoryObservationModel(
                        source_type="prometheus",
                        source_configuration_id=configuration.id,
                        source_record_id=source_record_id,
                        observed_fields_json=fields,
                        raw_reference=f"prometheus:{configuration.id}:target:{source_record_id}",
                        raw_checksum=checksum,
                        observed_at=now,
                        first_seen_at=now,
                        last_seen_at=now,
                        status="observed",
                    )
                    self.session.add(observation)
                    await self.session.flush()
                else:
                    observation.observed_fields_json = fields
                    observation.raw_checksum = checksum
                    observation.observed_at = now
                    observation.last_seen_at = now
                await inventory.correlate_prometheus(observation, target_identities(target))
                await inventory.sync_prometheus_topology(observation, configuration, target)
                ambiguous += observation.status == "ambiguous"
                unmatched += observation.status == "unmatched"
            configuration.last_successful_scan_at = now
            configuration.last_error = None
            configuration.target_count = len(targets)
            configuration.healthy_target_count = healthy
            configuration.unhealthy_target_count = len(targets) - healthy
            await self.session.commit()
            return {
                "configuration_id": configuration.id,
                "target_count": len(targets),
                "healthy_target_count": healthy,
                "unhealthy_target_count": len(targets) - healthy,
                "ambiguous_target_count": ambiguous,
                "unmatched_target_count": unmatched,
                "scanned_at": now,
            }
        except Exception as exc:
            await self.session.rollback()
            configuration = await self._get(configuration_id)
            configuration.last_failed_scan_at = now
            configuration.last_error = str(sanitize(str(exc)))[:2000]
            await self.session.commit()
            raise

    async def delete(self, configuration_id: UUID) -> None:
        configuration = await self._get(configuration_id)
        await self.session.delete(configuration)
        await self.session.commit()

    async def _request(
        self, configuration: PrometheusConfigurationModel, path: str
    ) -> dict[str, Any]:
        headers: dict[str, str] = {"Accept": "application/json"}
        auth: httpx.BasicAuth | None = None
        if configuration.auth_type != "none":
            if not configuration.encrypted_secret:
                raise PrometheusError("SECRET_REQUIRED", "Stored authentication is incomplete.")
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
                response = await client.get(urljoin(f"{configuration.base_url}/", path.lstrip("/")))
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise PrometheusError("TIMEOUT", "Prometheus request timed out.", 504) from exc
        except httpx.HTTPStatusError as exc:
            code = (
                "AUTHENTICATION_FAILED" if exc.response.status_code in {401, 403} else "HTTP_ERROR"
            )
            raise PrometheusError(
                code, f"Prometheus returned HTTP {exc.response.status_code}.", 502
            ) from exc
        except httpx.HTTPError as exc:
            raise self._network_error(exc) from exc
        except ValueError as exc:
            raise PrometheusError(
                "INVALID_PROMETHEUS_RESPONSE",
                "Prometheus returned a response that is not valid JSON.",
                502,
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise PrometheusError(
                "INVALID_PROMETHEUS_RESPONSE", "Prometheus returned an invalid response.", 502
            )
        return payload

    @staticmethod
    def _network_error(exc: Exception) -> PrometheusError:
        if isinstance(exc, PrometheusError):
            return exc
        if isinstance(exc, TimeoutError | asyncio.TimeoutError | httpx.TimeoutException):
            return PrometheusError("TIMEOUT", "Prometheus request timed out.", 504)
        detail = str(exc).casefold()
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                return PrometheusError(
                    "DNS_RESOLUTION_FAILED", "Prometheus hostname could not be resolved.", 502
                )
            if isinstance(cause, ConnectionRefusedError):
                return PrometheusError(
                    "CONNECTION_REFUSED",
                    "The Prometheus host refused the TCP connection.",
                    502,
                )
            if isinstance(cause, ssl.SSLCertVerificationError):
                certificate_detail = str(cause).casefold()
                if (
                    "hostname mismatch" in certificate_detail
                    or "not valid for" in certificate_detail
                ):
                    return PrometheusError(
                        "TLS_HOSTNAME_MISMATCH",
                        "The Prometheus TLS certificate does not match the configured hostname.",
                        502,
                    )
                return PrometheusError(
                    "TLS_CERTIFICATE_NOT_TRUSTED",
                    "The Prometheus TLS certificate is not trusted. Add its issuing CA "
                    "in Settings → Certificates.",
                    502,
                )
            cause = cause.__cause__ or cause.__context__
        if "name or service not known" in detail or "nodename nor servname" in detail:
            return PrometheusError(
                "DNS_RESOLUTION_FAILED", "Prometheus hostname could not be resolved.", 502
            )
        if "connection refused" in detail:
            return PrometheusError(
                "CONNECTION_REFUSED", "The Prometheus host refused the TCP connection.", 502
            )
        if "hostname mismatch" in detail:
            return PrometheusError(
                "TLS_HOSTNAME_MISMATCH",
                "The Prometheus TLS certificate does not match the configured hostname.",
                502,
            )
        if "certificate verify failed" in detail or "self-signed certificate" in detail:
            return PrometheusError(
                "TLS_CERTIFICATE_NOT_TRUSTED",
                "The Prometheus TLS certificate is not trusted. Add its issuing CA "
                "in Settings → Certificates.",
                502,
            )
        return PrometheusError("CONNECTION_FAILED", "Prometheus could not be reached.", 502)

    async def _get(self, configuration_id: UUID) -> PrometheusConfigurationModel:
        configuration = await self.session.get(PrometheusConfigurationModel, configuration_id)
        if not configuration:
            raise PrometheusError("CONFIGURATION_NOT_FOUND", "Configuration not found.", 404)
        return configuration

    @staticmethod
    def _response(item: PrometheusConfigurationModel) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "base_url": item.base_url,
            "auth_type": item.auth_type,
            "username": item.username,
            "has_secret": bool(item.encrypted_secret),
            "tls_verify": item.tls_verify,
            "request_timeout_seconds": item.request_timeout_seconds,
            "scan_interval_seconds": item.scan_interval_seconds,
            "enabled": item.enabled,
            "last_successful_scan_at": item.last_successful_scan_at,
            "last_failed_scan_at": item.last_failed_scan_at,
            "last_error": item.last_error,
            "target_count": item.target_count,
            "healthy_target_count": item.healthy_target_count,
            "unhealthy_target_count": item.unhealthy_target_count,
            "warnings": endpoint_warnings(item.base_url),
        }

    @staticmethod
    def _fields(target: dict[str, Any]) -> dict[str, Any]:
        labels = (
            cast(dict[str, Any], target.get("labels"))
            if isinstance(target.get("labels"), dict)
            else {}
        )
        discovered = (
            cast(dict[str, Any], target.get("discoveredLabels"))
            if isinstance(target.get("discoveredLabels"), dict)
            else {}
        )
        instance = labels.get("instance")
        identity_type, normalized = endpoint_identity(instance or target.get("scrapeUrl"))
        return {
            "scrape_pool": target.get("scrapePool"),
            "scrape_url": target.get("scrapeUrl"),
            "global_url": target.get("globalUrl"),
            "discovered_labels": discovered,
            "labels": labels,
            "instance": instance,
            "job": labels.get("job"),
            "health": target.get("health"),
            "last_scrape": target.get("lastScrape"),
            "scrape_duration": target.get("lastScrapeDuration"),
            "last_scrape_error": target.get("lastError"),
            "original_endpoint": instance or discovered.get("__address__"),
            "identity_type": identity_type,
            "normalized_identity": normalized,
            "primary_ip": normalized if identity_type == "ip_address" else None,
            "fqdn": normalized if identity_type == "fqdn" else None,
            "hostname": normalized if identity_type == "hostname" else None,
        }
