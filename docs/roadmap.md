# Roadmap

## Completed foundation

- single-container FastAPI/React appliance
- first-run and optional unattended local administrator setup
- rotating refresh sessions, CSRF, roles, user safeguards, password lifecycle
- UI-managed General settings and explicit SaaS registration status
- isolated multi-source filesystem discovery, reconciliation, health, and scan history
- activity, structured logs, diagnostics, sanitized bundles, and security headers
- SQLite/Alembic persistence and hardened Docker Compose deployment

## Next: SaaS lifecycle

- real registration API contract, connector identity, credential protection and rotation
- outbound HTTPS client with certificate validation, timeouts, retry/backoff, and proxy support
- honest heartbeat state and audit events
- unregister/re-register confirmation flows connected to the real API

## Next: background operation

- APScheduler invoking the existing scan use case
- bounded concurrency, cancellation, backoff, retention, and durable spool processing
- incremental SaaS metadata transfer and tombstones

## Later source plugins

Prometheus, Loki, Zammad, ServiceNow, SharePoint, Confluence, and Jira will be added only with real contracts, permissions guidance, health checks, secret handling, and tests. They will not appear in the UI before completion.

## Enterprise hardening

- TLS and ingress deployment profiles, recovery workflows, optional external identity/MFA
- signed artifacts, SBOM/provenance, vulnerability response, and upgrade channels
- backup/restore, performance, failure injection, migration, and long-running soak testing

OCR, parsing, chunking, embeddings, AI inference, vector databases, and vector indexing remain outside connector scope.
