# Troubleshooting

- **Connectivity test reports DNS or connection refused:** verify the origin and published SaaS port. From Docker, use `host.docker.internal`, not `localhost`, for a host service.
- **HTTP URL rejected:** set development mode only for local development, or provide an HTTPS SaaS origin in production.
- **TLS verification failed:** correct the server certificate and trust chain. Disabling TLS verification is not supported.
- **409 during registration:** this permanent instance may already be active or the token was already used. Check the SaaS connector record before generating a replacement token.
- **410 during registration:** generate a new SaaS registration token; the submitted token expired or was revoked.
- **Authentication Failed:** use Retry Now only after credentials are expected to be valid, or re-register with a new token. Automatic retries are intentionally slow.
- **Out of Sync or Disconnected:** confirm network/TLS availability. Recovery is automatic after an accepted heartbeat; successful recovery resets the failure count.
- **Encryption-key startup failure:** restore `/data/config/secrets/encryption_key` from the same
  backup as `/data/state`. Do not generate a replacement key for existing ciphertext.
- **Startup health reports `INSUFFICIENT_DISK_SPACE`:** free the reported number of bytes in the
  connector data volume. Migrations have not run; the container remains up only to serve the clear
  unhealthy health response and will recover on restart after space is available.
- **Source Failed:** confirm its configured path is beneath `/data/external-sources`, is included
  by the read-only mount, and is readable by the container user.

Download the sanitized diagnostics bundle from Diagnostics. It excludes all credentials, authorization headers, password hashes, document contents, and connector-secret ciphertext.
