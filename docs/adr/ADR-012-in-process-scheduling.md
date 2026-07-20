# ADR-012: In-process scheduling

- Status: Accepted
- Date: 2026-07-20

## Decision

Use one APScheduler `AsyncIOScheduler` inside the FastAPI lifespan. Reconstruct enabled source jobs and registered heartbeat work from SQLite at startup. Reconcile jobs after configuration mutations. Manual and scheduled scans call one application service guarded per source; jobs use `max_instances=1`, coalescing, UTC, and isolated error handling.

## Consequences

The single-process appliance needs no Redis, Celery, worker, or extra container. Job definitions are derived state. Horizontal or multi-process execution would require scheduler leadership.
