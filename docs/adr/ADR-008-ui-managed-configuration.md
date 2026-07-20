# ADR-008: UI-managed product configuration

- Status: Accepted
- Date: 2026-07-20

## Context

Requiring customers to edit YAML, JSON, environment files, or SQLite for ordinary operation creates support and validation problems.

## Decision

Persist normal connector configuration through authenticated application services and manage it through the local web UI. Restrict environment variables to deployment bootstrap concerns such as port, JWT secret, optional initial administrator, source host mount, and initial log level.

## Consequences

Configuration receives typed validation, authorization, and audit events. Secrets are not added to general settings records, and full secret values are never returned. Backup of `/data` captures operational configuration consistently.
