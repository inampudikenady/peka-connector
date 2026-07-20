# Security

## Runtime

- one non-root `peka` process
- read-only root filesystem and `no-new-privileges`
- persistent writes only under `/data/state`, `/data/config`, `/data/logs`, and `/data/spool`
- `/data/sources` mounted read-only
- bounded `/tmp` tmpfs with `noexec` and `nosuid`
- only port 8080 published; TLS terminates at the customer ingress where required

## Identity and sessions

The first administrator is created interactively unless explicit unattended credentials are supplied. The endpoint is permanently closed after any user exists. Usernames and strong passwords are validated. Argon2 hashes protect passwords.

Access JWTs are short-lived and held only in browser memory. Long-lived refresh tokens are opaque, rotated, stored only as SHA-256 hashes, and delivered in HTTP-only SameSite cookies. The Secure attribute is applied for HTTPS or explicit secure-cookie deployments. Double-submit CSRF protection covers refresh and logout. Login and setup have single-process sliding-window rate limits.

Administrator and Read Only policies are enforced by API dependencies, never only by navigation visibility. Last-active-administrator safeguards prevent lockout. Password changes, resets, disables, and logout revoke refresh sessions.

## Source isolation

Filesystem configuration cannot escape `/data/sources`, including through `..` resolution or a configured symlink. Discovery does not follow file symlinks. The UI has no host mount editor, file browser, shell, or raw SQL capability.

## Browser and diagnostics

Responses set CSP, frame denial, MIME sniffing prevention, referrer, and permissions headers. Operational contexts pass through secret-key and text redaction. Diagnostics bundles use a positive safe-data selection and exclude hashes, JWT secrets, raw tokens, API tokens, and document contents.

The current in-memory rate limiter is appropriate for the single-process appliance. A future multi-process architecture would require a shared limiter, but no such architecture is planned at this stage.
