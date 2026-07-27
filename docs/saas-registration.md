# SaaS registration and heartbeat

## Registration workflow

Start PEKA SaaS and PEKA Connector, create or select a SaaS tenant, and generate a one-time connector registration token. In Connector, an Administrator opens Settings > SaaS Registration, enters the SaaS origin, token, and connector name, tests connectivity, and registers.

The connector calls `POST /api/v1/connectors/register` with:

```json
{
  "registration_token": "string",
  "connector_name": "string",
  "connector_version": "string",
  "environment": "string",
  "instance_id": "uuid",
  "capabilities": ["filesystem_documents"]
}
```

A response is accepted only when it contains UUID `connector_id` and `tenant_id`, a non-empty `connector_secret`, a valid interval, and an ISO-8601 UTC `registered_at`. The token is discarded. The secret is encrypted with AES-GCM before SQLite persistence. The state becomes Awaiting First Heartbeat, not Connected.

Registration errors are sanitized: 400 malformed input, 401 invalid token, 403 not permitted, 409 duplicate instance or used token, 410 expired/revoked token, 429 rate-limited, and 5xx temporarily unavailable.

## Heartbeat contract

The connector calls `POST /api/v1/connectors/{connector_id}/heartbeat` with bearer secret authentication and `X-PEKA-Connector-ID`. The payload contains only instance identity, the current appliance-owned connector name, deployment environment, version, UTC time, uptime, process status `healthy`, aggregate source health, and `filesystem_documents`. It never contains paths, filenames, users, document metadata/content, or secrets. The display name is edited only in General settings; a rename is sent immediately and retried by normal heartbeats without changing connector credentials or re-registering.

The response is:

```json
{
  "accepted": true,
  "server_time": "ISO-8601 UTC timestamp",
  "next_heartbeat_seconds": 300
}
```

The response interval replaces the current interval when valid. The registration interval is used initially and 300 seconds is only the final fallback.

## Status meanings

- **Unregistered:** local connector ID or secret is absent.
- **Registering:** a registration request is active.
- **Awaiting First Heartbeat:** credentials exist but SaaS has accepted no heartbeat.
- **Connected:** the latest heartbeat is timely and enabled sources are healthy.
- **Degraded:** heartbeats succeed but at least one enabled source is unhealthy.
- **Reconnecting:** a temporary SaaS communication failure is actively being retried.
- **Out of Sync:** last success is older than 1.5 but less than 3 expected intervals.
- **Disconnected:** no success for at least 3 expected intervals.
- **Authentication Failed:** heartbeat received 401 or 403.

Connected means communication with SaaS. It does not mean files were uploaded, synchronized, or indexed. In Sync is never emitted. Retired is SaaS-side only.

Re-registration requires a new token and replaces credentials only after a complete valid response. Local unregister deletes local SaaS credentials and stops heartbeats, but does not delete or retire the SaaS record.
