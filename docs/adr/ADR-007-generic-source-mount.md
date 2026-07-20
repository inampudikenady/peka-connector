# ADR-007: Generic source mount

- Status: Accepted
- Date: 2026-07-20

## Context

A mount named for documents implies one source and prevents a durable appliance convention for multiple local source configurations.

## Decision

Mount the customer-selected host tree read-only at `/data/sources`. Each filesystem source stores a distinct path at that root or below it, such as `/data/sources/manuals` and `/data/sources/contracts`. Compose exposes only `PEKA_SOURCES_PATH` for selecting the host root.

## Consequences

Multiple filesystem sources share one narrowly scoped read-only mount. Administrators organize host subdirectories and configure them independently in the UI. Changing the host mount remains a deployment action, not an application setting.
