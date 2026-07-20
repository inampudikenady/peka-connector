# ADR-014: SaaS registration contract

- Status: Accepted
- Date: 2026-07-20

## Decision

Use a typed client for `POST /api/v1/connectors/register`, with explicit timeouts, TLS verification, validated responses, and centralized sanitized error mapping. HTTPS is mandatory except in development. The UI supplies the origin, one-time token, and display name. Persist success only after a valid remote response.

The final contract uses UUID instance/connector/tenant identifiers, UTC `registered_at`, and the sole current capability `filesystem_documents`. A successful response stores the returned secret only as authenticated ciphertext. Status remains Awaiting First Heartbeat until SaaS accepts a heartbeat. Failed re-registration leaves existing credentials intact.

## Consequences

Routes and schedulers contain no HTTP implementation. Tests can inject transport. Re-register is explicit. Local unregister currently has no remote deletion semantics and says so in the UI.
