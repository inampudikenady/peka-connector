# ADR-003: SQLite for local state

- Status: Accepted
- Date: 2026-07-20

## Context

An on-premises connector should be simple to install and operate. Its initial state consists of users, configuration, and discovery metadata managed by one connector instance.

## Decision

Use SQLite on a local persistent volume, accessed with SQLAlchemy 2.x and versioned with Alembic. Enable foreign keys and keep write transactions short. Run one writing backend process.

## Consequences

Deployment has no external database dependency and backup is straightforward. SQLite limits write concurrency and must not live on an unsupported network filesystem. Repository ports preserve an upgrade path if measured scale later requires another embedded or customer-managed database.

