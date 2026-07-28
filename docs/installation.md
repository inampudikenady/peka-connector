# Docker installation

1. Create a source directory, for example `mkdir -p sources`.
2. Copy `.env.example` to `.env`. The connector generates independent JWT and encryption secrets
   on first start and persists them under `/data/config/secrets` with mode `0600`.
3. Set `PEKA_SOURCES_PATH` only when the host source directory is not `./sources`.
4. Run `docker compose up --build -d`.
5. Open port 8080, create the first local administrator, and configure sources and SaaS registration in the UI.

Compose deploys one non-root product container, one named `/data` volume, and one read-only source bind mount. The root filesystem is read-only and `/tmp` is a bounded tmpfs. Normal settings are never managed through Compose, JSON, YAML, or direct SQLite edits.

Production SaaS URLs must use HTTPS. TLS may terminate at an enterprise ingress; PEKA Connector still validates the certificate presented by the configured SaaS origin.
