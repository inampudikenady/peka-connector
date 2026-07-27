# Security

## Runtime

- one non-root `peka` process
- read-only root filesystem and `no-new-privileges`
- persistent writes only under `/data/state`, `/data/config`, `/data/logs`, and `/data/spool`
- `/data/external-sources` mounted read-only
- managed `/data/sources/documents` and `/data/sources/cmdb` mounted as isolated,
  connector-writable named volumes
- bounded `/tmp` tmpfs with `noexec` and `nosuid`
- only port 8080 published; TLS terminates at the customer ingress where required

CMDB uploads accept only CSV and XLSX, use generated filenames, enforce size and row limits, and
never execute formulas, macros, external links, or embedded workbook programs. Prometheus
credentials use the connector encryption service and are not returned after save. Inventory
mutation endpoints require the administrator role; authenticated read-only users may view data.
- outbound SaaS origins require HTTPS outside development and use TLS verification

## Identity and sessions

The first administrator is created interactively unless explicit unattended credentials are supplied. The endpoint is permanently closed after any user exists. Usernames and strong passwords are validated. Argon2 hashes protect passwords.

Access JWTs are short-lived and held only in browser memory. Long-lived refresh tokens are opaque, rotated, stored only as SHA-256 hashes, and delivered in HTTP-only SameSite cookies. The Secure attribute is applied for HTTPS or explicit secure-cookie deployments. Double-submit CSRF protection covers refresh and logout. Login and setup have single-process sliding-window rate limits.

Administrator and Read Only policies are enforced by API dependencies, never only by navigation visibility. Last-active-administrator safeguards prevent lockout. Password changes, resets, disables, and logout revoke refresh sessions.

## Source isolation

Filesystem configuration cannot escape `/data/sources`, including through `..` resolution or a configured symlink. Discovery does not follow file symlinks. The UI has no host mount editor, file browser, shell, or raw SQL capability.

The managed document source is stricter: `/data/sources/documents` is compiled into the
application boundary and has no writeable path setting. A dedicated Docker volume makes that
directory writable while the external source bind and container root remain read-only. Upload
filenames are normalized and stripped of paths; hidden files, traversal, symlinks, unsupported
types, MIME/signature mismatches, zero-byte files, and detectable encryption are rejected. Uploads
stream to unpredictable temporary names, enforce byte limits during streaming, fsync, and use
atomic rename. Files are never executed or extracted.

The source row is marked `system_managed`. Generic source repository operations exclude it, generic filesystem creation is disabled, and the Documents settings schema forbids extra fields such as `path` or patterns. Administrators can change only enabled state and a bounded scan interval. Read Only users can inspect the same operational state without mutation rights.

Only Administrators can upload, retry, or delete. Read Only users can inspect inventory and status. PEKA transfers omit tenant selection, local usernames, arbitrary paths, and document content from logs/activity. Authorization headers, connector credentials, registration tokens, and file bytes pass through neither structured log fields nor diagnostics.

## Browser and diagnostics

Responses set CSP, frame denial, MIME sniffing prevention, referrer, and permissions headers. Operational contexts pass through secret-key and text redaction. Diagnostics bundles use a positive safe-data selection and exclude hashes, JWT secrets, raw tokens, API tokens, and document contents.

The current in-memory rate limiter is appropriate for the single-process appliance. A future multi-process architecture would require a shared limiter, but no such architecture is planned at this stage.

## Connector credentials

`PEKA_ENCRYPTION_KEY` is a required production bootstrap secret independent of the JWT key. It is never generated silently, persisted, returned by an API, logged, or included in diagnostics. The application derives an AES-256 key and uses AES-GCM with a random nonce and associated data. SQLite stores only versioned ciphertext and an encrypted validation marker. Startup validates the marker and any stored connector credential; a missing or changed key fails safely before serving traffic. Operators must preserve the key in their deployment secret manager through container replacement and database restore.

The one-time registration token exists only in request memory. The returned connector secret is decrypted only for heartbeat authorization. Client error messages are centrally mapped and sanitized; authorization headers and secret values never enter structured contexts.

Re-registration is transactional from the appliance perspective: existing working credentials remain stored unless a new registration response is fully validated. Registration `401` responses are treated as remote token rejection, not local browser-session expiry. Connectivity testing never submits the one-time token and cannot create a connector.
