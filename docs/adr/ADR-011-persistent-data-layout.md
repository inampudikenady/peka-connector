# ADR-011: Persistent data layout

- Status: Accepted
- Date: 2026-07-20

## Context

Enterprise backup, permission, diagnostics, and future spool behavior require stable ownership of persistent appliance files.

## Decision

Use `/data/state`, `/data/config`, `/data/logs`, and `/data/spool` for writable persistent state,
`/data/external-sources` for the read-only customer mount, and dedicated volumes beneath
`/data/sources` for managed uploads. Store SQLite at `/data/state/peka.db`. Initialize writable
volume ownership for UID/GID 10001 and mode `0700` before connector startup. Keep the root
filesystem read-only and use a bounded no-exec tmpfs for `/tmp`.

## Consequences

Backup and restore scope includes the named `/data`, managed Documents, and CMDB volumes.
Persistent writes are predictable and inspectable. The external source bind is excluded from state
backups.
