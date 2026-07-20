# Roadmap

## Completed foundation

- single-container FastAPI/React appliance
- first-run and optional unattended local administrator setup
- rotating refresh sessions, CSRF, roles, user safeguards, password lifecycle
- UI-managed General settings and explicit SaaS registration status
- isolated multi-source filesystem discovery, reconciliation, health, and scan history
- activity, structured logs, diagnostics, sanitized bundles, and security headers
- SQLite/Alembic persistence and hardened Docker Compose deployment
- automatic interval scans with restart recovery and overlap prevention
- persistent instance identity and typed registration/heartbeat contracts
- encrypted connector credential, heartbeat backoff, lifecycle states, and UI controls
- real SaaS registration/heartbeat contract, Retry Now, connection-state engine, latency/server-time telemetry, and restart recovery

## Next: outbound synchronization

- incremental SaaS metadata transfer and tombstones
- durable spool processing, bounded upload concurrency, retention, and recovery
- connector-secret rotation and remote unregister when SaaS contracts are defined
- customer proxy configuration and enterprise CA trust workflow

## Later source plugins

Prometheus, Loki, Zammad, ServiceNow, SharePoint, Confluence, and Jira will be added only with real contracts, permissions guidance, health checks, secret handling, and tests. They will not appear in the UI before completion.

## Enterprise hardening

- TLS and ingress deployment profiles, recovery workflows, optional external identity/MFA
- signed artifacts, SBOM/provenance, vulnerability response, and upgrade channels
- backup/restore, performance, failure injection, migration, and long-running soak testing

OCR, parsing, chunking, embeddings, AI inference, vector databases, and vector indexing remain outside connector scope.
