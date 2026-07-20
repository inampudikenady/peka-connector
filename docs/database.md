# Database

SQLite state is stored at `/data/state/peka.db`, accessed through SQLAlchemy 2.x and migrated only by Alembic. The entrypoint runs `alembic upgrade head` before FastAPI starts. SQLite foreign keys are enabled on every connection.

## Tables

- `users`: local identity, Argon2 hash, role, enabled state, timestamps, last login.
- `refresh_tokens`: hashes of opaque refresh and CSRF tokens, expiry and revocation state. Raw tokens are never stored.
- `sources`: plugin identity, UI-managed JSON configuration, health, scan schedule/in-progress state, and file count.
- `documents`: source-relative metadata, SHA-256, discovery and last-seen timestamps, active/missing state.
- `scan_history`: manual/scheduled trigger, status, timestamps, metrics, and sanitized error.
- `audit_events`: security and operational actions with actor and safe structured details.
- `application_logs`: structured searchable logs with level, component, message, and sanitized context.
- `product_settings`: General settings, instance ID, registration state/IDs, secret ciphertext/key check, and heartbeat state.

Document content, passwords, raw refresh tokens, deployment secrets, registration tokens, and plaintext connector secrets are not stored in these tables.

## Transactions

Discovery and hashing occur outside the SQLite write phase. Reconciliation updates metadata in one transaction. Scan lifecycle and source health are committed explicitly so failures remain observable. The appliance runs one writing backend process.

## Migration 0002

`20260720_0002` adds roles and user lifecycle fields, refresh sessions, source health, document last-seen/state, scan history, activity, logs, and product settings. Existing users migrate as Administrators to preserve access. Existing document records become active and use discovery time as initial last-seen time.

Back up `/data/state/peka.db` with SQLite-safe procedures before upgrades. Do not place the database on an unsupported network filesystem.

## Migration 0003

`20260720_0003` adds source schedule timestamps/in-progress state, scan trigger, permanent instance identity, authenticated connector-secret ciphertext/key validation, registration timestamps, and heartbeat scheduling/status/failure fields. Existing `not_registered` state becomes `unregistered`. Jobs are reconstructed from database state after each process start.

## Migration 0004

`20260720_0004` finalizes the real SaaS lifecycle telemetry. It adds last failed heartbeat time, round-trip latency, last SaaS server time, and a unique scan correlation ID. Existing scan rows receive non-secret generated correlation identifiers during upgrade.
