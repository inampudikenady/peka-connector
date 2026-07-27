# Architecture

## Appliance boundary

PEKA Connector is one deployable image and one product service. A Node build stage compiles React, a Python build stage resolves backend dependencies, and the runtime contains FastAPI, migrations, and static UI assets. FastAPI serves both `/api/*` and the SPA on port 8080.

```text
Administrator browser
        |
        v
PEKA Connector container :8080
  FastAPI delivery layer ---- compiled React SPA
        |
  application services ---- typed SaaS client ---- HTTPS outbound
        |              |
  plugin ports     repository ports ---- in-process scheduler
        |              |
  Filesystem       SQLAlchemy / SQLite
        |              |
/data/external-sources:ro   /data/state/peka.db
        |
  documents (writable volume) -> validation/hash -> /data/spool -> PEKA
```

There is no production Nginx, Redis, PostgreSQL, separate frontend, or separate worker service.

## Backend boundaries

- **Domain:** immutable entities plus repository and plugin contracts.
- **Application:** authentication, user, source, scan, registration, and heartbeat use cases.
- **Infrastructure:** SQLAlchemy/SQLite repositories, APScheduler, typed HTTP transport, AES-GCM, Argon2, JWT, refresh sessions, and structured logging.
- **Plugins:** explicitly registered trusted source implementations.
- **API:** Pydantic validation, authorization dependencies, cookies, HTTP error mapping, and response schemas.

Normal configuration is persisted by application services and changed through authenticated APIs. Environment variables configure only deployment bootstrap concerns.

## Authentication flow

If no user exists, the unauthenticated setup-status endpoint directs the SPA to first-run setup. The one-time bootstrap endpoint creates an Argon2-hashed Administrator and becomes unavailable. Login returns a short-lived JWT kept in browser memory and sets a rotating opaque refresh token in an HTTP-only SameSite cookie. A separate CSRF cookie/header pair protects refresh and logout. Refresh tokens are hashed in SQLite and revoked on rotation, logout, password changes, reset, or user disablement.

## Source and scan flow

Each source stores a stable plugin type, typed normalized configuration, enabled state, and operational health. Filesystem paths resolve within `/data/sources`; traversal and symlink escapes are rejected. Manual and scheduled scans invoke the same service and per-source guard. APScheduler rebuilds enabled interval jobs from SQLite at startup; source mutations reconcile the corresponding job. Scans inventory metadata only and persist trigger, metrics, and history.

For the initial controlled-document release, the customer UI exposes exactly one `filesystem_documents` source named **Uploaded Documents**. A separate `system_managed` flag protects it without creating a connector-specific plugin type. Its path and patterns are fixed, while enabled state, scan interval, Scan now, and health testing live under **Documents > Source settings**. Generic source APIs, repository ports, and plugin contracts remain available for future complete source integrations, but generic filesystem creation is disabled and the Sources route redirects to Documents.

## SaaS lifecycle

The database creates one permanent instance UUID. Registration uses an injected typed client and never fabricates success. A successful response is validated before IDs and the AES-GCM encrypted connector secret are committed. One heartbeat job sends state through the same client, reschedules at the server interval, and applies bounded backoff after failure. SaaS is a dependency status and cannot make process liveness unhealthy.

Registration calls `POST {saas_url}/api/v1/connectors/register` with the one-time token, connector name/version, deployment environment, instance UUID, and `filesystem_documents` capability. A valid response contains UUID connector/tenant IDs, connector secret, optional 30–86,400 second heartbeat interval (default 300), and registration timestamp.

Heartbeat calls `POST {saas_url}/api/v1/connectors/{connector_id}/heartbeat` with `Authorization: Bearer <connector_secret>` and `X-PEKA-Connector-ID: <connector_id>`. Its typed body contains immutable instance identity plus the current appliance-owned name, deployment environment, version, UTC timestamp, process status `healthy`, uptime, source health totals, and capabilities. Source degradation is represented only by the summary counts. The validated response must contain `accepted: true`, UTC `server_time`, and `next_heartbeat_seconds`.

The General connector display name is the only editable name. Registration reads it from local settings, and every heartbeat resends it so a rename does not require re-registration. Settings commit the local name before attempting an immediate heartbeat; failure is non-blocking and the normal heartbeat schedule retries it.

The local connection engine emits Unregistered, Registering, Awaiting First Heartbeat, Connected, Degraded, Out of Sync, Reconnecting, Disconnected, or Authentication Failed. It never emits In Sync. Connected describes transport communication only, not document upload or synchronization. Retired remains SaaS-authoritative and is not generated locally.

On restart, startup validates the deployment encryption key, rebuilds source schedules, and schedules a near-immediate heartbeat when registration IDs and ciphertext exist.

## Operational data

Audit events and application logs are structured and persisted locally. Overview, activity, logs, and diagnostics report real state or explicit unavailable/empty states. Registration, heartbeat, scheduler actions, and failures use sanitized events and logs.

Application timestamps are aware UTC values at the SQLAlchemy boundary and are serialized with `Z` or `+00:00`. The React timestamp utility parses each instant once and uses the browser's local time zone for display; there is no customer-configured display time zone.

## Managed document delivery

The built-in managed source has a fixed identity and path. It is deliberately hidden from the configurable source-plugin API. UI uploads and direct directory copies converge after stability validation. The connector creates an immutable spool snapshot for every version so retries send the bytes that match the job hash even if the working file changes later.

```text
UI upload or controlled directory copy
  -> stability and type validation
  -> streaming SHA-256
  -> logical document/version update
  -> durable SQLite job + spool snapshot
  -> authenticated, idempotent PEKA upload
  -> explicit hash-matching acknowledgement
```

APScheduler owns one reconciliation job and one non-overlapping delivery-worker job. Job state is durable, stale in-progress work is recovered after restart, and ambiguous network outcomes retain the same idempotency key. PEKA owns parsing, OCR, chunking, embeddings, indexing, vector storage, and AI.
