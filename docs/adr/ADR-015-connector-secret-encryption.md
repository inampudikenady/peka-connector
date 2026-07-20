# ADR-015: Connector secret encryption

- Status: Accepted
- Date: 2026-07-20

## Decision

Encrypt the connector secret with AES-256-GCM using a key derived from required deployment secret `PEKA_ENCRYPTION_KEY`. Store versioned ciphertext and an encrypted validation marker. Validate both during startup. Never auto-generate a production key.

## Consequences

Database disclosure does not directly disclose the credential. Operators must back up and restore the external key separately. A missing or incorrect key prevents startup rather than silently destroying access.
