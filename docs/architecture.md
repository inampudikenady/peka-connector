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
  application services
        |              |
  plugin ports     repository ports
        |              |
  Filesystem       SQLAlchemy / SQLite
        |              |
/data/sources:ro   /data/state/peka.db
```

There is no production Nginx, Redis, PostgreSQL, separate frontend, or separate worker service.

## Backend boundaries

- **Domain:** immutable entities plus repository and plugin contracts.
- **Application:** authentication, user, source, scan, and SaaS boundary use cases.
- **Infrastructure:** SQLAlchemy/SQLite repositories, Argon2, JWT, refresh sessions, structured logging.
- **Plugins:** explicitly registered trusted source implementations.
- **API:** Pydantic validation, authorization dependencies, cookies, HTTP error mapping, and response schemas.

Normal configuration is persisted by application services and changed through authenticated APIs. Environment variables configure only deployment bootstrap concerns.

## Authentication flow

If no user exists, the unauthenticated setup-status endpoint directs the SPA to first-run setup. The one-time bootstrap endpoint creates an Argon2-hashed Administrator and becomes unavailable. Login returns a short-lived JWT kept in browser memory and sets a rotating opaque refresh token in an HTTP-only SameSite cookie. A separate CSRF cookie/header pair protects refresh and logout. Refresh tokens are hashed in SQLite and revoked on rotation, logout, password changes, reset, or user disablement.

## Source and scan flow

Each source stores a stable plugin type, typed normalized configuration, enabled state, and operational health. Filesystem paths resolve within `/data/sources`; traversal and symlink escapes are rejected. A scan inventories metadata only, reconciles it with the prior snapshot, marks unseen records missing, and persists counts and history. The initial UI exposes only the implemented filesystem plugin.

## Operational data

Audit events and application logs are structured and persisted locally. Overview, activity, logs, and diagnostics report real state or explicit unavailable/empty states. The SaaS registration boundary deliberately returns unavailable until a real PEKA API is supplied.
