# ADR-009: Initial role model

- Status: Accepted
- Date: 2026-07-20

## Context

Operational viewers need appliance visibility without permission to change state, credentials, or source metadata.

## Decision

Support `administrator` and `read_only`. Administrators manage all local state. Read Only users view overview, sources and health, activity, logs, diagnostics, settings status, and about information. They cannot mutate settings, manage users, validate or scan sources, or perform destructive operations. Enforce policy in API dependencies.

## Consequences

The model is small, comprehensible, and testable. Navigation mirrors permissions but is not a security boundary. Last-active-administrator and self-delete safeguards prevent common lockouts.
