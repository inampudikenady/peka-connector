# PEKA Connector

PEKA Connector is an enterprise on-premises service that discovers customer-approved data inside a customer environment and communicates outbound to the PEKA SaaS platform. The initial release runs with Docker Compose and includes a local administration UI, local authentication, SQLite state, and a filesystem document source.

The connector does **not** perform OCR, content parsing, chunking, embedding generation, AI inference, or vector indexing. Those remain SaaS responsibilities.

## Current capabilities

- FastAPI API with JWT bearer authentication and Argon2 password hashing
- React/TypeScript/Material UI administration interface, compiled into the appliance image
- Versioned SQLite schema managed by Alembic
- Typed plugin contract and trusted in-process plugin registry
- Filesystem source configuration, validation, metadata discovery, and SHA-256 hashing
- Single non-root appliance container, read-only document mount, health checks, and CI checks

## Repository layout

```text
backend/
  app/
    api/              HTTP delivery and schemas
    application/      use cases and orchestration
    core/             settings and logging
    domain/           entities and ports
    infrastructure/   SQLAlchemy, SQLite, Argon2, JWT
    plugins/          plugin registry and implementations
  alembic/            database migrations
  tests/              unit and integration tests
frontend/             React administration UI
Dockerfile            multi-stage production appliance build
docs/                 architecture, security, database, plugin, and ADR docs
scripts/              local development helpers
.github/workflows/    continuous integration
```

## Run with Docker Compose

Requirements: Docker Engine with Compose v2 and a local directory containing documents to expose read-only.

```sh
cp .env.example .env
./scripts/generate-secret.sh
```

Put the generated value in `PEKA_JWT_SECRET`, set a strong bootstrap password, set `PEKA_DOCUMENTS_PATH`, then start the connector:

```sh
docker compose up --build -d
```

Open `http://localhost:8080` and sign in with the configured bootstrap administrator. In a container deployment, configure filesystem sources using paths beneath `/documents`.

The production build is a single image. Its stages compile the React application, install the Python backend, and copy both into one minimal Python runtime. FastAPI serves `/api/*` and the compiled SPA from port 8080. SQLite is stored at `/data/peka.db`; `/documents` is mounted read-only by Compose. Only port 8080 is exposed.

The bootstrap password is used only when the user table is empty. Remove it from the runtime environment after the first successful start where operational tooling permits it. Back up the `peka-data` Docker volume as part of the customer's normal backup policy.

## Local development

Backend (Python 3.13):

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e './backend[dev]'
cp .env.example .env
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend (Node.js 22):

```sh
cd frontend
npm install
npm run dev
```

During development, Vite serves the UI on port 5173 and proxies `/api` to FastAPI on port 8000. This two-process workflow is development-only and does not change the single-container production artifact.

Run checks with `pytest backend`, `ruff check backend`, `mypy backend/app`, and `npm run build` from `frontend/`.

## Documentation

Start with [architecture](docs/architecture.md), [plugin development](docs/plugins.md), [database design](docs/database.md), [security](docs/security.md), and the [roadmap](docs/roadmap.md). Architectural decisions are recorded under [docs/adr](docs/adr/).

## License

Proprietary. See [LICENSE](LICENSE).
