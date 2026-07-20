# ADR-001: Clean Architecture

- Status: Accepted
- Date: 2026-07-20

## Context

The connector must support multiple integrations, local and SaaS workflows, and years of enterprise maintenance without coupling business behavior to FastAPI, SQLAlchemy, or a particular deployment model.

## Decision

Organize the backend into domain, application, infrastructure, plugin, and API boundaries. Domain entities and ports describe business needs. Application services coordinate use cases. Infrastructure implements persistence and security. The API is a delivery adapter. Dependencies point toward the domain/application core.

## Consequences

Use cases and plugins can be tested without HTTP or SQLite, and adapters can evolve independently. There is modest mapping code between domain entities and ORM/Pydantic models. We will not add interfaces unless there is a genuine boundary or test seam.

