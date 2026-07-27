# ADR-007: Generic source mount

- Status: Accepted
- Date: 2026-07-20

## Context

A mount named for documents implies one source and prevents a durable appliance convention for multiple local source configurations.

## Decision

Mount the customer-selected host tree read-only at `/data/external-sources`. Each external
filesystem source stores a distinct path at that root or below it, such as
`/data/external-sources/manuals` and `/data/external-sources/contracts`. Managed document and CMDB
uploads use separate writable volumes under `/data/sources`. Compose exposes
`PEKA_SOURCES_PATH` for selecting the external host root.

## Consequences

Multiple external filesystem sources share one narrowly scoped read-only mount. Administrators
organize host subdirectories and configure them independently. Changing the host mount remains a
deployment action, not an application setting. The separate mount prevents writable managed-source
volumes from being nested beneath a read-only bind.
