# Security

## Trust boundaries

The connector runs inside the customer environment. The local UI should be reachable only from an administrative network. Customer source mounts are read-only. Future PEKA SaaS traffic originates from the backend over HTTPS; the SaaS platform never requires an inbound connection to the connector.

## Local authentication

Passwords are hashed with pwdlib's recommended Argon2 settings. Successful login issues a short-lived signed JWT containing an opaque user UUID, token type, issued-at time, and expiry. Every protected request verifies the signature, allowed algorithm, expiry, token type, and active local user.

The JWT secret must be at least 32 characters and unique per installation. The bootstrap password is required only to create the first account and should be removed from deployment configuration afterward. Production password rotation and additional-user management are roadmap items.

The web UI keeps the access token in session storage, limiting persistence to one browser tab session. This does not eliminate XSS risk; the UI avoids raw HTML injection, uses a restrictive dependency set, and should receive a Content Security Policy before general availability.

## Container posture

The appliance runs one non-root FastAPI process with `no-new-privileges` and a read-only root filesystem. Only port 8080 is published. `/data` is the only persistent writable volume, `/tmp` is a bounded no-exec tmpfs, and `/documents` is a read-only customer mount. FastAPI serves both the API and compiled UI, eliminating an internal reverse-proxy service. Deploy TLS at the customer ingress or reverse proxy; plain HTTP is suitable only on a trusted local development host.

## Filesystem handling

Filesystem configuration requires an absolute path. Discovery does not follow symlinks and produces only normalized relative paths. The configured mount determines the maximum readable scope, so operators should mount the narrowest possible directories. SHA-256 requires reading file bytes but content is neither parsed nor persisted.

## Future controls

- HTTPS certificate validation and optional outbound proxy configuration
- connector identity and credential rotation for PEKA SaaS
- encrypted secret storage for plugin credentials
- audit events, rate limiting, session revocation, and password rotation
- signed release images, SBOMs, vulnerability scanning, and provenance
- diagnostics redaction and configurable retention
