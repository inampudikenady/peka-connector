import errno
import json
import re
import socket
import ssl
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.domain.ports.saas import (
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
    DocumentDeliveryMetadata,
    DocumentDeliveryResponse,
    OperationalToolRequest,
    OperationalToolResult,
    SaaSClientError,
)


class HttpxPEKASaaSClient:
    """Central HTTP transport for the versioned PEKA SaaS connector contract."""

    def __init__(
        self,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        verify_tls: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._verify_tls = verify_tls
        self._transport = transport

    async def test_connectivity(self, base_url: str) -> None:
        url = f"{base_url.rstrip('/')}/api/v1/connectors/register"
        async with self._client() as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if response.status_code == 405:
            return
        if response.status_code in {400, 401, 403, 422, 429}:
            return
        if response.status_code == 404:
            raise SaaSClientError(
                "unexpected_response", "PEKA connector API path was not found", 404
            )
        if response.status_code >= 500:
            self._raise_status(response.status_code, "connectivity")
        raise SaaSClientError(
            "unexpected_response",
            f"PEKA connector API returned unexpected HTTP {response.status_code}",
            response.status_code,
        )

    async def register_connector(
        self,
        base_url: str,
        request: ConnectorRegistrationRequest,
        correlation_id: str | None = None,
    ) -> ConnectorRegistrationResponse:
        url = f"{base_url.rstrip('/')}/api/v1/connectors/register"
        headers = {"X-Request-ID": correlation_id} if correlation_id else None
        async with self._client() as client:
            try:
                response = await client.post(
                    url,
                    json=request.model_dump(mode="json"),
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if not response.is_success:
            self._raise_registration_error(response, request.registration_token, correlation_id)
        try:
            return ConnectorRegistrationResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response", "PEKA returned an invalid registration response"
            ) from exc

    async def send_heartbeat(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        request: ConnectorHeartbeatRequest,
    ) -> ConnectorHeartbeatResponse:
        url = f"{base_url.rstrip('/')}/api/v1/connectors/{connector_id}/heartbeat"
        headers = {
            "Authorization": f"Bearer {connector_secret}",
            "X-PEKA-Connector-ID": str(connector_id),
        }
        async with self._client() as client:
            try:
                response = await client.post(
                    url, json=request.model_dump(mode="json"), headers=headers
                )
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if not response.is_success:
            self._raise_heartbeat_error(response)
        try:
            return ConnectorHeartbeatResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response",
                "PEKA returned an unexpected response",
                failure_reason="Unexpected heartbeat response",
                method="POST",
                destination_host=response.request.url.host,
                request_path=self._safe_request_path(response.request.url.path),
                request_id=self._safe_request_id(response),
            ) from exc

    async def deliver_document(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        metadata: DocumentDeliveryMetadata,
        idempotency_key: str,
        file_path: Path | None,
    ) -> DocumentDeliveryResponse:
        url = f"{base_url.rstrip('/')}/api/v1/connectors/{connector_id}/documents"
        headers = {
            "Authorization": f"Bearer {connector_secret}",
            "X-PEKA-Connector-ID": str(connector_id),
            "Idempotency-Key": idempotency_key,
        }
        async with self._client() as client:
            try:
                if metadata.operation == "upsert":
                    if file_path is None:
                        raise SaaSClientError("validation", "Document spool file is unavailable")
                    with file_path.open("rb") as document_file:
                        response = await client.post(
                            url,
                            headers=headers,
                            data={"metadata": json.dumps(metadata.model_dump(mode="json"))},
                            files={"file": (metadata.filename, document_file, metadata.mime_type)},
                        )
                else:
                    response = await client.post(
                        url, headers=headers, json=metadata.model_dump(mode="json")
                    )
            except OSError as exc:
                raise SaaSClientError("storage", "Document spool file is unavailable") from exc
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if not response.is_success:
            messages = {
                400: ("validation", "PEKA rejected the document metadata"),
                401: ("authentication", "PEKA rejected the connector credentials"),
                403: ("authentication", "PEKA denied document delivery"),
                409: ("conflict", "PEKA rejected the document version conflict"),
                413: ("validation", "PEKA rejected the document size"),
                422: ("validation", "PEKA rejected the document"),
                429: ("rate_limited", "PEKA document delivery is rate limited"),
            }
            kind, message = messages.get(
                response.status_code,
                ("unavailable", "PEKA document delivery is temporarily unavailable"),
            )
            raise SaaSClientError(kind, message, response.status_code)
        try:
            return DocumentDeliveryResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response", "PEKA returned an invalid document acknowledgement"
            ) from exc

    async def report_source_health(self) -> None:
        raise NotImplementedError("Source health reporting is outside this vertical slice")

    async def receive_commands(self) -> None:
        raise NotImplementedError("Command polling is outside this vertical slice")

    async def claim_operational_tool(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
    ) -> OperationalToolRequest | None:
        url = (
            f"{base_url.rstrip('/')}/api/v1/connectors/{connector_id}"
            "/operational-tools/requests/next"
        )
        headers = {
            "Authorization": f"Bearer {connector_secret}",
            "X-PEKA-Connector-ID": str(connector_id),
        }
        async with self._client() as client:
            try:
                response = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if response.status_code == 204:
            return None
        if not response.is_success:
            self._raise_status(response.status_code, "operational_tool_claim")
        try:
            return OperationalToolRequest.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response",
                "PEKA returned an invalid operational tool request",
            ) from exc

    async def submit_operational_tool_result(
        self,
        base_url: str,
        connector_id: UUID,
        connector_secret: str,
        request_id: UUID,
        result: OperationalToolResult,
    ) -> None:
        url = (
            f"{base_url.rstrip('/')}/api/v1/connectors/{connector_id}"
            f"/operational-tools/requests/{request_id}/result"
        )
        headers = {
            "Authorization": f"Bearer {connector_secret}",
            "X-PEKA-Connector-ID": str(connector_id),
        }
        async with self._client() as client:
            try:
                response = await client.post(
                    url, headers=headers, json=result.model_dump(mode="json")
                )
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if not response.is_success:
            self._raise_status(response.status_code, "operational_tool_result")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            verify=self._verify_tls,
            transport=self._transport,
            follow_redirects=False,
        )

    @staticmethod
    def _raise_status(status_code: int, operation: str) -> NoReturn:
        heartbeat_messages = {
            400: "PEKA rejected an invalid heartbeat",
            401: "PEKA rejected the connector heartbeat credentials",
            403: "PEKA denied connector heartbeat access",
            404: "The registered PEKA connector was not found",
            409: "Heartbeat instance identity does not match the PEKA registration",
            429: "PEKA heartbeat rate limit was reached; retry later",
        }
        messages = heartbeat_messages if operation == "heartbeat" else {}
        message = messages.get(
            status_code,
            "PEKA is temporarily unavailable"
            if status_code >= 500
            else f"PEKA request failed with HTTP {status_code}",
        )
        raise SaaSClientError("http_error", message, status_code)

    @staticmethod
    def _raise_heartbeat_error(response: httpx.Response) -> NoReturn:
        status_code = response.status_code
        error_code, safe_message = HttpxPEKASaaSClient._safe_api_error(response)
        request_id = HttpxPEKASaaSClient._safe_request_id(response)
        failure_reasons = {
            400: "PEKA rejected the heartbeat request",
            401: "Authentication rejected by PEKA",
            403: "Authentication rejected by PEKA",
            404: "PEKA endpoint not found",
            409: "PEKA rejected the heartbeat conflict",
            429: "PEKA rate limit reached",
        }
        failure_reason = failure_reasons.get(
            status_code,
            f"PEKA returned HTTP {status_code}",
        )
        kinds = {
            400: "http_400",
            401: "authentication",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            429: "rate_limited",
        }
        kind = kinds.get(
            status_code,
            "server_error" if status_code >= 500 else "http_error",
        )
        path = HttpxPEKASaaSClient._safe_request_path(response.request.url.path)
        message = f"POST {path} returned HTTP {status_code}"
        if error_code:
            message += f", code={error_code}"
        raise SaaSClientError(
            kind,
            message,
            status_code,
            error_code=error_code,
            request_id=request_id,
            failure_reason=failure_reason,
            method="POST",
            destination_host=response.request.url.host,
            request_path=path,
            safe_api_message=safe_message,
        )

    @staticmethod
    def _safe_api_error(response: httpx.Response) -> tuple[str | None, str | None]:
        try:
            payload: Any = response.json()
        except ValueError:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        raw_code = payload.get("code", payload.get("error_code"))
        code = (
            raw_code
            if isinstance(raw_code, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", raw_code)
            else None
        )
        raw_message = payload.get("message", payload.get("detail"))
        message = HttpxPEKASaaSClient._safe_remote_message(raw_message)
        return code, message

    @staticmethod
    def _safe_remote_message(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        lower_value = value.casefold()
        if "<" in value or ">" in value or "traceback" in lower_value:
            return None
        if re.search(
            r"(?i)(authorization\s*:|bearer\s+\S+|connector_secret\s*[=:]|"
            r"registration_token\s*[=:]|password\s*[=:]|token\s*[=:])",
            value,
        ):
            return None
        message = " ".join(value.split())[:300]
        return message or None

    @staticmethod
    def _safe_request_id(response: httpx.Response) -> str | None:
        value = (
            response.headers.get("X-Request-ID")
            or response.headers.get("X-Correlation-ID")
            or response.headers.get("Request-ID")
        )
        if value and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value):
            return value
        return None

    @staticmethod
    def _safe_request_path(path: str) -> str:
        return re.sub(
            r"(?<=/connectors/)[0-9a-fA-F-]{36}(?=/)",
            "<redacted>",
            path,
        )

    @staticmethod
    def _raise_registration_error(
        response: httpx.Response,
        registration_token: str,
        correlation_id: str | None,
    ) -> NoReturn:
        request_id = response.headers.get("X-Request-ID") or correlation_id
        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise SaaSClientError(
                "registration_error",
                "Connector registration failed.",
                response.status_code,
                request_id=request_id,
            )

        raw_code = payload.get("code")
        code = (
            raw_code
            if isinstance(raw_code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", raw_code)
            else None
        )
        if code is None:
            raise SaaSClientError(
                "registration_error",
                "Connector registration failed.",
                response.status_code,
                request_id=request_id,
            )
        raw_message = payload.get("message")
        safe_message = HttpxPEKASaaSClient._safe_registration_message(
            raw_message, registration_token
        )
        messages = {
            "TOKEN_NOT_FOUND": "The registration token is invalid.",
            "TOKEN_EXPIRED": ("The registration token has expired. Generate a new token in PEKA."),
            "TOKEN_USED": (
                "The registration token has already been used. Generate a new token in PEKA."
            ),
            "TOKEN_REVOKED": ("The registration token was revoked. Generate a new token in PEKA."),
            "INSTANCE_ALREADY_REGISTERED": (
                "This connector appliance is already registered in PEKA."
            ),
            "TENANT_MISMATCH": (
                "The registration token is not valid for this connector registration."
            ),
            "REGISTRATION_NOT_PERMITTED": "Connector registration is not permitted.",
        }
        message = (
            safe_message or "Connector registration failed."
            if code == "VALIDATION_FAILED"
            else messages.get(code or "") or safe_message or "Connector registration failed."
        )
        raise SaaSClientError(
            "registration_error",
            message,
            response.status_code,
            error_code=code,
            request_id=request_id,
        )

    @staticmethod
    def _safe_registration_message(value: Any, registration_token: str) -> str | None:
        if not isinstance(value, str):
            return None
        lower_value = value.casefold()
        if "<" in value or ">" in value or "traceback" in lower_value:
            return None
        if re.search(
            r"(?i)(authorization\s*:|bearer\s+\S+|connector_secret\s*[=:]|"
            r"registration_token\s*[=:]|password\s*[=:])",
            value,
        ):
            return None
        message = " ".join(value.split())[:500]
        if not message or registration_token in message:
            return None
        return message

    @staticmethod
    def _raise_transport(exc: httpx.HTTPError) -> NoReturn:
        try:
            request = exc.request
        except RuntimeError:
            request = None
        host = request.url.host if request else None
        method = request.method if request else None
        path = HttpxPEKASaaSClient._safe_request_path(request.url.path) if request else None

        def error(kind: str, message: str, reason: str) -> SaaSClientError:
            return SaaSClientError(
                kind,
                message,
                failure_reason=reason,
                method=method,
                destination_host=host,
                request_path=path,
            )

        if isinstance(exc, httpx.ConnectTimeout):
            raise error(
                "connection_timeout",
                f"Connection timed out while contacting {host or 'PEKA'}",
                "Connection timed out",
            ) from exc
        if isinstance(exc, httpx.ReadTimeout):
            raise error(
                "read_timeout",
                f"Timed out waiting for a response from {host or 'PEKA'}",
                "Read timed out",
            ) from exc
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                raise error(
                    "dns",
                    f"DNS resolution failed for {host or 'the PEKA hostname'}",
                    "DNS resolution failed",
                ) from exc
            if isinstance(cause, ConnectionRefusedError):
                raise error(
                    "connection_refused",
                    f"Connection refused by {host or 'PEKA'}",
                    "Connection refused",
                ) from exc
            if isinstance(cause, OSError) and cause.errno in {
                errno.ECONNREFUSED,
                61,
                111,
            }:
                raise error(
                    "connection_refused",
                    f"Connection refused by {host or 'PEKA'}",
                    "Connection refused",
                ) from exc
            if isinstance(cause, ssl.SSLCertVerificationError):
                raise error(
                    "tls_verification",
                    f"TLS certificate verification failed for {host or 'PEKA'}",
                    "TLS certificate verification failed",
                ) from exc
            if isinstance(cause, ssl.SSLError):
                raise error(
                    "tls",
                    f"TLS handshake failed for {host or 'PEKA'}",
                    "TLS/SSL connection failed",
                ) from exc
            cause = cause.__cause__ or cause.__context__
        if isinstance(exc, httpx.TimeoutException):
            raise error(
                "transport_timeout",
                f"Request timed out while contacting {host or 'PEKA'}",
                "Connection timed out",
            ) from exc
        raise error(
            "transport",
            f"Unknown transport error while contacting {host or 'PEKA'}",
            "Unknown transport error",
        ) from exc
