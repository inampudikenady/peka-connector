# ADR-010: Filesystem source isolation

- Status: Accepted
- Date: 2026-07-20

## Context

An administrator-entered path must not turn the connector into an arbitrary host filesystem reader.

## Decision

Resolve every configured external filesystem path and require it to equal `/data/external-sources`
or have that resolved root as an ancestor. Reject traversal and configured symlink escapes, require
directory read/search permissions, do not follow discovery symlinks, and keep the Docker mount
read-only. Do not implement file browsing or mount editing in the UI.

## Consequences

The maximum readable scope is explicit at deployment. Multiple isolated source configurations remain possible under that scope. Operators must mount only the minimum required host tree.
