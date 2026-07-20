# Roadmap

## Milestone 1 — Product foundation

- Clean backend boundaries and typed API
- local Argon2/JWT authentication
- SQLite/Alembic persistence
- trusted plugin registry
- Filesystem Document Source and manual scans
- Docker Compose deployment and local administration UI

## Milestone 2 — Connector lifecycle

- secure SaaS registration and connector identity
- outbound HTTPS client with retries, timeouts, proxy support, and certificate validation
- heartbeats and health state
- configuration and credential rotation
- structured local logs, audit events, and diagnostics export

## Milestone 3 — Background operation

- APScheduler integration invoking existing application use cases
- bounded concurrency, cancellation, backoff, and scan state
- incremental metadata synchronization and tombstones
- retention policies and operational metrics

## Milestone 4 — Plugin expansion

- plugin SDK/version compatibility policy
- Prometheus and Loki sources
- Zammad, ServiceNow, SharePoint, Confluence, and Jira sources
- secret references and per-plugin connectivity diagnostics

## Milestone 5 — Enterprise hardening

- VM packaging and service management
- TLS deployment guidance, RBAC, password lifecycle, and recovery workflows
- signed artifacts, SBOM/provenance, vulnerability response, and upgrade channels
- performance, failure-injection, migration, backup/restore, and long-running soak tests

Priorities should follow validated customer deployment requirements. The connector will continue to exclude AI inference, OCR, parsing, chunking, embeddings, vector databases, and indexing.
