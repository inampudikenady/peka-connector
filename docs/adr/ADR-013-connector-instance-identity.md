# ADR-013: Connector instance identity

- Status: Accepted
- Date: 2026-07-20

## Decision

Generate one UUID when product settings are first accessed and persist it in SQLite under `/data/state`. Include it in registration and every heartbeat. Local unregister retains it.

## Consequences

Restart and container replacement preserve identity when `/data` is preserved. Restoring or cloning the database also restores identity and requires deliberate operational handling.
