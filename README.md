# PEKA Connector

PEKA Connector v2.0.1 is the customer-resident PEKA data plane. It provides a local
administration UI, integration access, policy enforcement, document processing, local semantic
knowledge storage and retrieval, and outbound-only HTTPS communication with PEKA SaaS.

The connector performs document extraction, normalization, sensitive-content redaction,
chunking, local embedding, and indexing. Qdrant is bundled as the internal **Local Knowledge
Store** and does not require separate customer installation or administration. AI inference and
conversation orchestration remain PEKA SaaS responsibilities.

## Customer-resident data-plane architecture

The connector manages:

- integration access
- document processing
- local semantic knowledge storage and retrieval
- policy enforcement and content minimization
- secure communication with PEKA SaaS

Customer systems and durable knowledge indexes remain inside the customer environment. The PEKA
Connector sends only the authorized context required to fulfil a request to the PEKA SaaS
service. ServiceNow, Zammad, Prometheus, Loki, VMware, and SolarWinds operational data remains
live/API-driven unless a future knowledge source is explicitly enabled for indexing.

## Foundation capabilities

- FastAPI API and compiled React/TypeScript/Material UI served from one container on port 8080
- browser-based first-run administrator creation, Argon2 password hashing, JWT access tokens, rotating cookie refresh sessions, and CSRF protection
- Administrator and Read Only roles with enforced API authorization
- UI-managed users, connector settings, documents, activity, logs, and diagnostics
- typed trusted-plugin framework with Filesystem Documents as the only exposed source type
- isolated read-only `/data/sources` source tree supporting multiple configured subdirectories
- metadata reconciliation, SHA-256 hashing, scan metrics/history, missing-file state, and source health
- controlled document upload/direct-copy ingestion into the Local Knowledge Store
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

The Local Knowledge Store persists separately in the Docker named volume
`peka_connector_qdrant_data`, mounted at `/qdrant/storage` inside its internal component. The
volume survives connector/container restarts, Docker restarts, host reboots, upgrades, and
`docker compose down`. Normal lifecycle commands must never use `docker compose down -v`.

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

3. Start the connector deployment:

   ```sh
   docker compose up --build -d
   ```

4. Open `http://localhost:8080` (or the configured `PEKA_HTTP_PORT`).

5. Create the first local administrator in the browser.

6. Open **Documents**. The singular **Uploaded Documents** source is already initialized; no source creation is required.

Compose starts the connector and its internal Local Knowledge Store. Only connector port 8080 is
published; Qdrant ports 6333 and 6334 are not published. The default Compose file mounts the
customer-selected `PEKA_SOURCES_PATH` read-only at
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

Connected means the appliance is communicating with PEKA. Local Knowledge Store health and
document indexing state are reported separately and do not disable live integrations.

## Managed documents

Administrators can upload TXT, Markdown, PDF, DOCX, XLSX, and CSV files from the **Documents** page, or copy them directly into `/data/sources/documents`. UI uploads stream through a generated temporary file, are validated, hashed, fsynced, atomically moved, and copied to the durable spool. Direct copies pass a stability window and periodic reconciliation before following the same queue.

Documents contains **Files** and **Source settings** tabs. Administrators may enable or disable the source, set its 30–86,400 second scan interval, run Scan now, and test directory health. Its name, filesystem type, path, include/exclude policy, and deletion protection are appliance-owned. The previous Sources navigation and generic filesystem creation workflow are not exposed. Existing legacy source rows are retained for future migration tooling but do not replace or interfere with the managed source.

Each stable content hash is normalized, sanitized, chunked, embedded locally, and reconciled into
the Local Knowledge Store by stable document identifier. Updates replace old chunks and deletion
removes every matching point. If the store is unavailable, the file and pending state remain
durable while live integrations and heartbeats continue. See [customer data plane](docs/customer-data-plane.md).

## Connector inventory

The local connector supports versioned CSV/XLSX CMDB imports, Prometheus active-target collection,
and deterministic canonical inventory correlation. See
[connector inventory](docs/inventory.md) for source authority, security, and matching rules.

The optional read-only [Zammad integration](docs/ZAMMAD.md) synchronizes permitted ticket
evidence locally, correlates it with canonical CMDB assets, and exposes bounded results through
the existing operational assistant transport without sending the Zammad credential to SaaS.

The independent [ServiceNow integration](docs/SERVICENOW.md) synchronizes CMDB items and
relationships, incidents and journals, problems, and changes. It can run alongside Zammad while
retaining separate credentials, cursors, health, and cache provenance.

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

`VERSION` is the authoritative release version. Release builds validate the requested image
version against it. See the
[release procedure](docs/release.md) for version validation, image labels, and runtime checks.

See [customer data plane](docs/customer-data-plane.md), [architecture](docs/architecture.md),
[migration plan](docs/knowledge-migration.md), [managed documents](docs/documents.md),
[database](docs/database.md), [plugins](docs/plugins.md), [security](docs/security.md),
[installation](docs/installation.md), [PEKA registration](docs/saas-registration.md),
[local development](docs/local-development.md), [troubleshooting](docs/troubleshooting.md),
[lifecycle E2E](docs/e2e-lifecycle-test.md), [roadmap](docs/roadmap.md), and [ADRs](docs/adr/).

## License

Proprietary. See [LICENSE](LICENSE).
