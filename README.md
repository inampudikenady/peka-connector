# PEKA Connector

PEKA Connector is a single-container enterprise appliance installed inside a customer environment. It provides a local administration UI, inventories explicitly mounted sources, stores local operational state, and is designed for outbound-only HTTPS communication with PEKA SaaS.

It does **not** perform OCR, parsing, chunking, embeddings, AI inference, or vector indexing. Those remain PEKA SaaS responsibilities.

## Foundation capabilities

- FastAPI API and compiled React/TypeScript/Material UI served from one container on port 8080
- browser-based first-run administrator creation, Argon2 password hashing, JWT access tokens, rotating cookie refresh sessions, and CSRF protection
- Administrator and Read Only roles with enforced API authorization
- UI-managed users, connector settings, sources, activity, logs, and diagnostics
- typed trusted-plugin framework with Filesystem Documents as the only exposed source type
- isolated read-only `/data/sources` source tree supporting multiple configured subdirectories
- metadata reconciliation, SHA-256 hashing, scan metrics/history, missing-file state, and source health
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
```

Only `/data` is persistent. The database is `/data/state/peka.db`. Customer content is mounted read-only at `/data/sources`; source paths configured in the UI must be that directory or a descendant such as `/data/sources/manuals` or `/data/sources/contracts`.

## Install

1. Create a host source directory:

   ```sh
   mkdir -p sources
   ```

2. Copy `.env.example` to `.env`. Generate independent JWT and encryption secrets (the script can be run twice), and optionally set `PEKA_SOURCES_PATH`. Preserve `PEKA_ENCRYPTION_KEY` across replacements and restores; losing or changing it makes stored SaaS credentials unreadable. Leave bootstrap administrator fields blank for interactive setup.

3. Start the single connector service:

   ```sh
   docker compose up --build -d
   ```

4. Open `http://localhost:8080` (or the configured `PEKA_HTTP_PORT`).

5. Create the first local administrator in the browser.

6. Configure one or more Filesystem Documents sources from the Sources page using paths beneath `/data/sources`.

After startup, customer configuration is managed through the UI. Customers do not edit Compose, YAML, JSON, or SQLite for normal connector operation. Environment values are limited to deployment bootstrap concerns: published HTTP port, JWT signing secret, encryption key, optional unattended administrator, source host mount, and initial log level.

## SaaS registration and heartbeat

An Administrator enters the HTTPS PEKA SaaS origin, one-time registration token, and display name under Settings. The connector posts its persistent instance ID, version, environment, and capabilities to `/api/v1/connectors/register`. It retains no registration token. A valid response supplies connector and tenant IDs, an encrypted-at-rest connector secret, and the heartbeat interval.

Registration first enters **Awaiting First Heartbeat**. Only an accepted authenticated heartbeat changes the state to **Connected** (or **Degraded** when an enabled source is unhealthy). Temporary failures use bounded exponential backoff and progress through Reconnecting, Out of Sync, and Disconnected without failing process liveness. HTTP 401/403 produces Authentication Failed. Local unregister stops heartbeats and removes local credentials but does not delete the remote SaaS record.

Connected means the appliance is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized; document upload is not implemented yet.

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

See [architecture](docs/architecture.md), [database](docs/database.md), [plugins](docs/plugins.md), [security](docs/security.md), [installation](docs/installation.md), [SaaS registration](docs/saas-registration.md), [local development](docs/local-development.md), [troubleshooting](docs/troubleshooting.md), [lifecycle E2E](docs/e2e-lifecycle-test.md), [roadmap](docs/roadmap.md), and [ADRs](docs/adr/).

## License

Proprietary. See [LICENSE](LICENSE).
