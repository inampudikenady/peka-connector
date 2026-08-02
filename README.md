# PEKA Connector

PEKA Connector is a single-container enterprise appliance installed inside a customer environment. It provides a local administration UI, inventories explicitly mounted sources, stores local operational state, and is designed for outbound-only HTTPS communication with PEKA SaaS.

It does **not** perform OCR, parsing, chunking, embeddings, AI inference, or vector indexing. Those remain PEKA SaaS responsibilities.

## Foundation capabilities

- FastAPI API and compiled React/TypeScript/Material UI served from one container on port 8080
- browser-based first-run administrator creation, Argon2 password hashing, JWT access tokens, rotating cookie refresh sessions, and CSRF protection
- Administrator and Read Only roles with enforced API authorization
- UI-managed users, connector settings, documents, activity, logs, and diagnostics
- typed trusted-plugin framework with Filesystem Documents as the only exposed source type
- isolated read-only `/data/sources` source tree supporting multiple configured subdirectories
- metadata reconciliation, SHA-256 hashing, scan metrics/history, missing-file state, and source health
- controlled document upload/direct-copy ingestion with a durable, idempotent PEKA delivery queue
- automatic per-source scans with restart recovery and overlap prevention
- persistent instance identity, outbound SaaS registration, and heartbeat lifecycle
- AES-256-GCM protection for the connector credential using a deployment-owned key
- SQLite/Alembic state, structured logs, audit events, sanitized diagnostics bundles
- non-root runtime, read-only root filesystem, `no-new-privileges`, and bounded no-exec tmpfs

## Production data layout

```text
/data/
  state/       SQLite database (`peka.db`)
  config/      application-managed configuration material
  logs/        structured local logs
  spool/       durable future outbound work
  sources/     read-only customer source mount
    documents/ dedicated writable managed-document volume
```

The database and connector configuration are persisted in `/data`. General customer sources are
mounted read-only at `/data/external-sources`. Separate sibling named volumes make
`/data/sources/documents` and `/data/sources/cmdb` writable without nesting them beneath a
read-only mount.

## Install

1. Create a host source directory:

   ```sh
   mkdir -p sources
   ```

2. Copy `.env.example` to `.env` and optionally set `PEKA_SOURCES_PATH`. Leave bootstrap
   administrator fields blank for interactive setup. JWT and encryption secrets are generated
   automatically and persisted with mode `0600` in `/data/config/secrets`.

3. Start the single connector service:

   ```sh
   docker compose up --build -d
   ```

4. Open `http://localhost:8080` (or the configured `PEKA_HTTP_PORT`).

5. Create the first local administrator in the browser.

6. Open **Documents**. The singular **Uploaded Documents** source is already initialized; no source creation is required.

The default Compose file mounts the customer-selected `PEKA_SOURCES_PATH` read-only at
`/data/external-sources`. Managed UI uploads use separate writable named volumes:
`connector_documents` at `/data/sources/documents` and `connector_cmdb` at
`/data/sources/cmdb`. A short initialization service assigns those persistent paths to UID/GID
10001 before the non-root connector starts.

After startup, customer configuration is managed through the UI. Customers do not edit Compose,
YAML, JSON, SQLite, JWT secrets, or encryption keys for normal connector operation. Environment
values are limited to deployment concerns such as published HTTP port, optional unattended
administrator, source host mount, and initial log level.

## SaaS registration and heartbeat

An Administrator sets the appliance-owned display name under **Settings > General**, then enters only the HTTPS PEKA SaaS origin and one-time registration token under **SaaS Registration**. The connector posts the current General display name, persistent instance ID, version, environment, and capabilities to `/api/v1/connectors/register`. It retains no registration token. A valid response supplies connector and tenant IDs, an encrypted-at-rest connector secret, and the heartbeat interval.

Registration first enters **Awaiting First Heartbeat**. Only an accepted authenticated heartbeat changes the state to **Connected** (or **Degraded** when an enabled source is unhealthy). Temporary failures use bounded exponential backoff and progress through Reconnecting, Out of Sync, and Disconnected without failing process liveness. HTTP 401/403 produces Authentication Failed. Local unregister stops heartbeats and removes local credentials but does not delete the remote SaaS record.

Every authenticated heartbeat carries the current connector display name, deployment environment, version, and capabilities. Saving a new display name triggers an immediate heartbeat; if SaaS is unavailable, the local change remains and normal heartbeat recovery retries the metadata update. All UI timestamps use the browser's local time zone automatically.

Connected means the appliance is communicating with PEKA. It does not mean a document has been parsed, indexed, or synchronized. Document delivery is acknowledged separately for each immutable content version.

## Managed documents

Administrators can upload TXT, Markdown, PDF, DOCX, XLSX, and CSV files from the **Documents** page, or copy them directly into `/data/sources/documents`. UI uploads stream through a generated temporary file, are validated, hashed, fsynced, atomically moved, and copied to the durable spool. Direct copies pass a stability window and periodic reconciliation before following the same queue.

Documents contains **Files** and **Source settings** tabs. Administrators may enable or disable the source, set its 30–86,400 second scan interval, run Scan now, and test directory health. Its name, filesystem type, path, include/exclude policy, and deletion protection are appliance-owned. The previous Sources navigation and generic filesystem creation workflow are not exposed. Existing legacy source rows are retained for future migration tooling but do not replace or interfere with the managed source.

Each delivery uses an idempotency key and remains queued until PEKA explicitly acknowledges the exact SHA-256 hash. Retryable failures use bounded exponential backoff; validation rejection is permanent until the file is corrected. Deleting a UI-uploaded document removes the local file and retains a durable PEKA tombstone until acknowledgement. See [managed document delivery](docs/documents.md).

## Connector inventory

The local connector supports versioned CSV/XLSX CMDB imports, Prometheus active-target collection,
and deterministic canonical inventory correlation. See
[connector inventory](docs/inventory.md) for source authority, security, and matching rules.

The optional read-only [Zammad integration](docs/ZAMMAD.md) synchronizes permitted ticket
evidence locally, correlates it with canonical CMDB assets, and exposes bounded results through
the existing operational assistant transport without sending the Zammad credential to SaaS.

## Optional unattended first run

Set both `PEKA_BOOTSTRAP_ADMIN_USERNAME` and `PEKA_BOOTSTRAP_ADMIN_PASSWORD` before the first start. The account is created only while the user table is empty. Remove these values after provisioning. Interactive browser setup is the default and never creates a silent default account.

## Development

Backend requires Python 3.13:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e './backend[dev]'
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend requires Node.js 22:

```sh
cd frontend
npm ci
npm run dev
```

Vite serves port 5173 and proxies `/api` to development Uvicorn on port 8000. Production remains one image and one process.

When SaaS runs on the host and Connector runs in Docker, use `http://host.docker.internal:<saas-port>` and set `PEKA_ENVIRONMENT=development`. HTTP is rejected in production. macOS and Windows provide this host name automatically; Linux Compose deployments can add `host.docker.internal:host-gateway` when required.

## Verification

```sh
.venv/bin/ruff check backend
.venv/bin/mypy backend/app
.venv/bin/pytest backend
cd frontend && npm run lint && npm run test && npm run build
docker compose config
docker compose build
```

Release builds must set one canonical connector version and pass it through Compose. See the
[release procedure](docs/release.md) for version validation, image labels, and runtime checks.

See [architecture](docs/architecture.md), [managed documents](docs/documents.md), [database](docs/database.md), [plugins](docs/plugins.md), [security](docs/security.md), [installation](docs/installation.md), [PEKA registration](docs/saas-registration.md), [local development](docs/local-development.md), [troubleshooting](docs/troubleshooting.md), [lifecycle E2E](docs/e2e-lifecycle-test.md), [roadmap](docs/roadmap.md), and [ADRs](docs/adr/).

## License

Proprietary. See [LICENSE](LICENSE).
