# Architecture

## Context

PEKA Connector runs inside a customer's trust boundary. Administrators use its local web interface, and connector integrations read explicitly configured local systems. Future SaaS communication is outbound-only over HTTPS. The connector is a transport and discovery product, not an inference or indexing service.

## Runtime components

```text
Administrator browser
        |
        | HTTP(S) inside customer network
        v
Single PEKA Connector container (port 8080)
  FastAPI ---- / ----> compiled React assets
      |
      +---- /api ----> Application services
                           |              |
                           v              v
                    Plugin registry   Repository ports
                           |              |
                    Source plugin     SQLAlchemy/SQLite
                           |
                    /documents (read-only)
                                      |
                              /data/peka.db (persistent)

Future: application services ---- outbound HTTPS ----> PEKA SaaS
```

Production uses one appliance container and exposes only port 8080. A multi-stage build compiles React with Node.js, installs the Python package in a Python builder, and copies both outputs into a non-root Python runtime. FastAPI handles `/api` routes first and serves the compiled SPA for all remaining browser routes. SQLite and discovered metadata live under `/data` on a persistent volume; customer documents are mounted at `/documents` read-only.

Logical source separation remains under `backend/` and `frontend/`. Local development may run Uvicorn on port 8000 and Vite on port 5173 with Vite's API proxy. These development processes are not separate production services.

## Backend boundaries

- **Domain** contains immutable business entities plus repository and plugin interfaces. It has no FastAPI or SQLAlchemy dependency.
- **Application** contains use cases such as authentication, source lifecycle management, and scans. It coordinates domain ports and defines use-case errors.
- **Infrastructure** implements persistence and cryptography with SQLAlchemy, SQLite, Argon2, and JWT.
- **Plugins** contains a small registry and source implementations. Plugins implement the domain `SourcePlugin` contract.
- **API** validates HTTP input, applies authentication, calls application services, and converts known errors to HTTP responses.

Dependencies point inward: delivery and infrastructure depend on application/domain abstractions. Pydantic is permitted in the plugin configuration port because configuration validation and JSON Schema generation are intentional shared requirements.

## Request flows

Creating a source validates the HTTP shape, resolves the trusted plugin, validates its typed configuration and external connectivity, then stores the normalized configuration. Scanning reloads that configuration, invokes discovery, and atomically replaces the source's metadata snapshot. A failed scan leaves the previous snapshot intact.

The initial UI starts scans manually. The scan interval is persisted now so a later APScheduler worker can schedule the same application use case without changing plugin contracts.

## Scalability boundaries

SQLite is appropriate for one connector process and modest local metadata. A single backend replica owns writes. Background work will be bounded and scheduled locally. If future scale requires multiple processes or large metadata volumes, the repository port allows a different local persistence adapter without changing plugins or HTTP contracts.

## Deliberate omissions

SaaS registration, heartbeats, background scheduling, diagnostics bundles, and remote plugin implementations belong to later milestones. The layout reserves clean extension points but does not include placeholder classes with no behavior.
