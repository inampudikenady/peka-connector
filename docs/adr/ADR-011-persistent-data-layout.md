# ADR-011: Persistent data layout

- Status: Accepted
- Date: 2026-07-20

## Context

Enterprise backup, permission, diagnostics, and future spool behavior require stable ownership of persistent appliance files.

## Decision

Use `/data/state`, `/data/config`, `/data/logs`, and `/data/spool` for writable persistent state and `/data/sources` for the read-only customer mount. Store SQLite at `/data/state/peka.db`. Create writable directories with mode `0700` at image build and startup. Keep the root filesystem read-only and use a bounded no-exec tmpfs for `/tmp`.

## Consequences

Backup and restore scope is one named `/data` volume. Persistent writes are predictable and inspectable. The source bind overlays `/data/sources` read-only and is excluded from state backups.
