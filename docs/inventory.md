# Connector inventory

Connector Inventory Phase 1 is entirely local to the PEKA Connector. It does not send inventory
records, mappings, observations, or correlation decisions to PEKA SaaS.

## Sources and authority

- CMDB files describe declared assets, ownership, and lifecycle.
- Prometheus active targets describe observed monitoring endpoints and current scrape health.
- Canonical assets combine source observations without silently overwriting another source.

Uploaded CSV and XLSX files live under `/data/sources/cmdb`. SQLite stores version metadata,
normalized records, raw values for traceability, assets, observations, identities, correlations,
and conflicts. Replacement creates a new version; prior provenance remains.

## CMDB import

Administrators upload a UTF-8 CSV or XLSX workbook, select a worksheet and header row, preview it,
and map arbitrary source columns. A row needs at least one cloud instance ID, serial number, asset
tag, FQDN, hostname, or primary IP.

The XLSX reader processes worksheet and shared-string XML only. It never executes formulas, macros,
embedded programs, or external links. Formula cells use a cached value when present. Limits are
configured with `PEKA_CMDB_MAX_FILE_SIZE_BYTES` (50 MiB by default) and
`PEKA_CMDB_MAX_ROW_COUNT` (100,000 by default).

## Prometheus and correlation

Administrators configure HTTP(S), authentication, TLS verification, timeout, schedule, and enabled
state. Secrets use existing AES-256-GCM encryption and are never returned. Manual and scheduled
scans read active targets only; historical series are not collected.

Ports remain endpoint metadata but are stripped from identities. The connector does not resolve
DNS. Exact matching priority is cloud instance ID, serial number, asset tag, FQDN, hostname, then
IP. Job, application, environment, exporter type, ownership, partial names, and fuzzy similarity
never create an automatic match. Ambiguous or conflicting evidence creates a review condition.
Manual decisions persist and take precedence on later scans.

Read-only users may view data. Only administrators may mutate datasets, Prometheus configuration,
or correlations.

## Deferred

Alloy, Loki, Zammad, connector-to-SaaS inventory synchronization, and historical Prometheus series
are intentionally outside Phase 1.
