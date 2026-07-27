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
            self._raise_status(response.status_code, "heartbeat")
        try:
            return ConnectorHeartbeatResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response", "PEKA returned an invalid heartbeat response"
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
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                raise SaaSClientError("dns", "PEKA hostname could not be resolved") from exc
            if isinstance(cause, ConnectionRefusedError):
                raise SaaSClientError("connection_refused", "PEKA refused the connection") from exc
            if isinstance(cause, ssl.SSLError):
                raise SaaSClientError("tls", "PEKA TLS validation failed") from exc
            cause = cause.__cause__
        if isinstance(exc, httpx.TimeoutException):
            raise SaaSClientError("timeout", "PEKA request timed out") from exc
        raise SaaSClientError("connection", "PEKA could not be reached") from exc
