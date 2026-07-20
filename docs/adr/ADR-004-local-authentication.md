# ADR-004: Local authentication

- Status: Accepted
- Date: 2026-07-20

## Context

Administrators need access when SaaS connectivity is unavailable, and customer environments cannot be assumed to provide a common identity provider in the first release.

## Decision

Use local users with Argon2 password hashes and short-lived HMAC-signed JWT bearer tokens. Create the first administrator from deployment secrets only when the database contains no users. Validate the active user on every authenticated request.

## Consequences

The first deployment is self-contained and works offline. Customers must protect bootstrap and JWT secrets. Account administration, recovery, MFA, external identity, rate limiting, and token revocation remain required hardening work before broader enterprise rollout.

