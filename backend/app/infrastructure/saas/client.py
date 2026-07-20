import socket
import ssl
from typing import NoReturn
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.domain.ports.saas import (
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
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
                "unexpected_response", "PEKA SaaS connector API path was not found", 404
            )
        if response.status_code >= 500:
            self._raise_status(response.status_code, "connectivity")
        raise SaaSClientError(
            "unexpected_response",
            f"PEKA SaaS connector API returned unexpected HTTP {response.status_code}",
            response.status_code,
        )

    async def register_connector(
        self, base_url: str, request: ConnectorRegistrationRequest
    ) -> ConnectorRegistrationResponse:
        url = f"{base_url.rstrip('/')}/api/v1/connectors/register"
        async with self._client() as client:
            try:
                response = await client.post(url, json=request.model_dump(mode="json"))
            except httpx.HTTPError as exc:
                self._raise_transport(exc)
        if not response.is_success:
            self._raise_status(response.status_code, "registration")
        try:
            return ConnectorRegistrationResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise SaaSClientError(
                "malformed_response", "PEKA SaaS returned an invalid registration response"
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
                "malformed_response", "PEKA SaaS returned an invalid heartbeat response"
            ) from exc

    async def upload_documents(self) -> None:
        raise NotImplementedError("Document upload is outside this vertical slice")

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
        registration_messages = {
            400: "PEKA SaaS rejected an invalid or malformed request",
            401: "PEKA SaaS rejected the supplied credentials or registration token",
            403: "The registration token or tenant is not permitted",
            404: "PEKA SaaS connector endpoint was not found",
            409: (
                "This instance may already be registered or the registration token was used; "
                "review the SaaS connector record and generate a new token if re-registering"
            ),
            410: "The registration token expired or was revoked; generate a new token",
            429: "PEKA SaaS rate limit was reached; retry later",
        }
        heartbeat_messages = {
            400: "PEKA SaaS rejected an invalid heartbeat",
            401: "PEKA SaaS rejected the connector heartbeat credentials",
            403: "PEKA SaaS denied connector heartbeat access",
            404: "The registered PEKA SaaS connector was not found",
            409: "Heartbeat instance identity does not match the SaaS registration",
            429: "PEKA SaaS heartbeat rate limit was reached; retry later",
        }
        messages = heartbeat_messages if operation == "heartbeat" else registration_messages
        message = messages.get(
            status_code,
            "PEKA SaaS is temporarily unavailable"
            if status_code >= 500
            else f"PEKA SaaS request failed with HTTP {status_code}",
        )
        raise SaaSClientError("http_error", message, status_code)

    @staticmethod
    def _raise_transport(exc: httpx.HTTPError) -> NoReturn:
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                raise SaaSClientError("dns", "PEKA SaaS hostname could not be resolved") from exc
            if isinstance(cause, ConnectionRefusedError):
                raise SaaSClientError(
                    "connection_refused", "PEKA SaaS refused the connection"
                ) from exc
            if isinstance(cause, ssl.SSLError):
                raise SaaSClientError("tls", "PEKA SaaS TLS validation failed") from exc
            cause = cause.__cause__
        if isinstance(exc, httpx.TimeoutException):
            raise SaaSClientError("timeout", "PEKA SaaS request timed out") from exc
        raise SaaSClientError("connection", "PEKA SaaS could not be reached") from exc
