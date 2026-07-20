# ADR-016: Heartbeat lifecycle

- Status: Accepted
- Date: 2026-07-20

## Decision

Schedule one authenticated heartbeat immediately after registration and shortly after registered startup, then at the valid server-returned interval (300 seconds only when unavailable). Persist attempts, successes and failures, next run, latency, SaaS server time, sanitized error, and failure count. Apply bounded exponential backoff. Map 401/403 to Authentication Failed and slow retries. Temporary errors transition through Reconnecting; age beyond 1.5 intervals is Out of Sync and age at least 3 intervals is Disconnected. An accepted heartbeat returns to Connected or Degraded according to enabled-source health.

## Consequences

SaaS unavailability is observable without stopping scans or failing liveness. Retry Now reuses the same overlap-protected service without creating another scheduled job. Successful delivery resets failure state and emits recovery activity. Connected is not a synchronization assertion. Future payload extensions remain behind the typed client contract.
