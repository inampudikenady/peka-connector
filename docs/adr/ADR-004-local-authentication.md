# ADR-004: Local authentication

- Status: Accepted
- Date: 2026-07-20

## Context

Administrators need access when SaaS connectivity is unavailable, and customer environments cannot be assumed to provide a common identity provider in the first release.

## Decision

Use local users with Argon2 password hashes, short-lived HMAC-signed JWT access tokens, and rotating opaque refresh tokens. Interactive browser setup creates the first Administrator and closes permanently after any user exists. Optional environment bootstrap is allowed only for unattended first deployment. Store refresh tokens only as hashes and deliver them through HTTP-only SameSite cookies with CSRF binding. Validate the active user on every authenticated request.

## Consequences

The first deployment is self-contained and works offline. Customers must protect unattended bootstrap and JWT secrets. Password changes, resets, user disablement, rotation, and logout revoke refresh sessions. Recovery, MFA, and external identity remain future work.
