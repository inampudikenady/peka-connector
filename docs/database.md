# Database

SQLite state is stored at `/data/state/peka.db`, accessed through SQLAlchemy 2.x and migrated only by Alembic. The entrypoint runs `alembic upgrade head` before FastAPI starts. SQLite foreign keys are enabled on every connection.

Inventory Phase 1 adds versioned `cmdb_*` tables and canonical `inventory_assets`,
`inventory_observations`, `inventory_identities`, `inventory_correlations`, and
`inventory_conflicts` tables. `prometheus_configurations` stores collection state and encrypted
credentials. CMDB source files stay on disk under `/data/sources/cmdb`, not in SQLite.

## Tables

- `users`: local identity, Argon2 hash, role, enabled state, timestamps, last login.
- `refresh_tokens`: hashes of opaque refresh and CSRF tokens, expiry and revocation state. Raw tokens are never stored.
- `sources`: plugin identity, UI-managed JSON configuration, health, scan schedule/in-progress state, and file count.
- `documents`: logical source-relative identity, current immutable-byte hash/version, MIME and file metadata, local/delivery status, remote acknowledgement IDs, safe failure state, and lifecycle timestamps.
- `document_delivery_jobs`: durable UPSERT/DELETE operations, immutable content hash/version, spool reference, idempotency key, attempts/backoff, correlation ID, and safe result state.
- `scan_history`: manual/scheduled trigger, status, timestamps, metrics, and sanitized error.
- `audit_events`: security and operational actions with actor and safe structured details.
- `application_logs`: structured searchable logs with level, component, message, and sanitized context.
- `product_settings`: General settings, instance ID, registration state/IDs, secret ciphertext/key check, and heartbeat state.

Document content, passwords, raw refresh tokens, deployment secrets, registration tokens, and plaintext connector secrets are not stored in these tables.

All application datetime values are written as timezone-aware UTC. SQLite does not preserve timezone metadata, so the shared SQLAlchemy UTC type restores UTC on reads, including legacy rows, before API serialization. The historical `product_settings.timezone` column may remain for migration compatibility, but it is ignored and is no longer exposed by the settings API; browser-local display requires no database reset.

## Transactions

Discovery and hashing occur outside the SQLite write phase. Reconciliation updates metadata in one transaction. Scan lifecycle and source health are committed explicitly so failures remain observable. The appliance runs one writing backend process.

## Migration 0002

`20260720_0002` adds roles and user lifecycle fields, refresh sessions, source health, document last-seen/state, scan history, activity, logs, and product settings. Existing users migrate as Administrators to preserve access. Existing document records become active and use discovery time as initial last-seen time.

Back up `/data/state/peka.db` with SQLite-safe procedures before upgrades. Do not place the database on an unsupported network filesystem.

## Migration 0003

`20260720_0003` adds source schedule timestamps/in-progress state, scan trigger, permanent instance identity, authenticated connector-secret ciphertext/key validation, registration timestamps, and heartbeat scheduling/status/failure fields. Existing `not_registered` state becomes `unregistered`. Jobs are reconstructed from database state after each process start.

## Migration 0004

`20260720_0004` finalizes the real SaaS lifecycle telemetry. It adds last failed heartbeat time, round-trip latency, last SaaS server time, and a unique scan correlation ID. Existing scan rows receive non-secret generated correlation identifiers during upgrade.

## Migration 0005

`20260721_0005` extends existing document rows without resetting the database and creates the durable delivery-job table. Existing configurable-source documents are backfilled as external-source metadata with delivery marked not applicable. New managed documents use `source_id + normalized relative path` as logical identity, SHA-256 as content-version identity, and a monotonically increasing local version sequence so returning to an older hash still creates a new version event.

## Migration 0006

`20260721_0006` adds the indexed `sources.system_managed` protection flag and idempotently creates or reuses the singular **Uploaded Documents** source. A matching `/data/sources/documents` source is reused with its enabled state and valid scan interval preserved. Unrelated legacy sources remain untouched and non-managed. Startup performs the same singularity repair defensively without resetting state.
