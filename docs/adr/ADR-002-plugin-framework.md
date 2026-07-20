# ADR-002: Trusted typed plugin framework

- Status: Accepted
- Date: 2026-07-20

## Context

PEKA Connector needs heterogeneous future sources. Arbitrary runtime code loading would create security, compatibility, deployment, and support risks.

## Decision

Ship trusted plugins in the connector release and register them explicitly in-process. Each source plugin exposes stable identity, a Pydantic configuration model, asynchronous validation, and asynchronous discovery through a small domain contract. Application services own persistence and scheduling.

## Consequences

Plugins are typed, discoverable by the UI through JSON Schema, and easy to test. Adding a bundled plugin requires a connector release. If independent distribution becomes necessary, signed packages and compatibility negotiation can extend the registry without changing the core contract.

