# Database

SQLite state is stored at `/data/state/peka.db`, accessed through SQLAlchemy 2.x and migrated only by Alembic. The entrypoint runs `alembic upgrade head` before FastAPI starts. SQLite foreign keys are enabled on every connection.

## Tables

- `users`: local identity, Argon2 hash, role, enabled state, timestamps, last login.
- `refresh_tokens`: hashes of opaque refresh and CSRF tokens, expiry and revocation state. Raw tokens are never stored.
- `sources`: plugin identity, UI-managed JSON configuration, enabled state, health, last success/error/scan, file count.
- `documents`: source-relative metadata, SHA-256, discovery and last-seen timestamps, active/missing state.
- `scan_history`: status, timestamps, discovered/added/changed/unchanged/missing/failed counts, sanitized error.
- `audit_events`: security and operational actions with actor and safe structured details.
- `application_logs`: structured searchable logs with level, component, message, and sanitized context.
- `product_settings`: the single UI-managed General and SaaS status record.

Document content, passwords, raw refresh tokens, JWT secrets, and SaaS API tokens are not stored in these tables.

## Transactions

Discovery and hashing occur outside the SQLite write phase. Reconciliation updates metadata in one transaction. Scan lifecycle and source health are committed explicitly so failures remain observable. The appliance runs one writing backend process.

## Migration 0002

`20260720_0002` adds roles and user lifecycle fields, refresh sessions, source health, document last-seen/state, scan history, activity, logs, and product settings. Existing users migrate as Administrators to preserve access. Existing document records become active and use discovery time as initial last-seen time.

Back up `/data/state/peka.db` with SQLite-safe procedures before upgrades. Do not place the database on an unsupported network filesystem.
