# ADR-015: Connector secret encryption

- Status: Superseded by the 2026-07-28 automatic secret persistence amendment
- Date: 2026-07-20

## Decision

Encrypt the connector secret with AES-256-GCM using an independent generated encryption key.
Generate both the JWT and encryption keys on first container start and persist them as mode `0600`
files under `/data/config/secrets`. Import an existing environment value only when its persistent
file does not yet exist, preserving upgrades. Store versioned ciphertext and an encrypted
validation marker and validate both during startup.

## Consequences

Database disclosure does not directly disclose the credential. Operators do not manually manage
keys, but backups and restores must keep `/data/config/secrets` with the SQLite state. A missing or
incorrect key prevents startup rather than silently destroying access.
