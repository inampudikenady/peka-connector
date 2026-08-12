# ServiceNow integration

ServiceNow is an optional, independent connector integration. It can run alongside Zammad;
their credentials, schedules, cursors, cache records, status, and assistant results are never
merged. All ServiceNow API traffic originates from the connector. PEKA SaaS does not connect to
the customer instance.

## Configuration

Open **Integrations → ServiceNow** and configure:

- Enabled
- Instance URL, such as `https://instance.service-now.com`
- Username and password
- Verify TLS certificate
- Request timeout, page size, and synchronization interval

The password is encrypted with the connector encryption key and is never returned by the API.
The current implementation uses HTTP Basic authentication for a dedicated least-privilege API
account. Credentials and instance URLs are not compiled into PEKA.

Use **Test connection** to validate authentication and CMDB read permission. Use **Run
synchronization now** for an immediate staged synchronization. Disabling the integration removes
its scheduled job and marks its cache inactive without deleting the configuration or affecting
Zammad.

## Required permissions and tables

Grant read-only access only to the records PEKA is allowed to expose. Supported tables are:

- `cmdb_ci`, `cmdb_ci_server`, `cmdb_ci_linux_server`, `cmdb_ci_win_server`, `cmdb_ci_service`
- `cmdb_rel_ci`, `cmdb_rel_type`
- `incident`, `problem`, `change_request`
- `sys_user`, `sys_journal_field`

ACL restrictions remain authoritative. A denied or unavailable table is reported as a named sync
stage error rather than being treated as an empty table. Internal work-note access must only be
granted when the connector's tenant roles are permitted to consume it.

## Synchronization and cache

The connector performs an initial full synchronization and then queries `sys_updated_on` using a
two-minute overlap. Independent cursors are stored for configuration items, relationships,
incidents, incident journals, problems, and changes. Each cursor advances only after its stage
commits successfully, so a change-request failure cannot roll back a completed incident stage.
Upserts use ServiceNow `sys_id`; repeated and overlapping runs do not duplicate records.

Cached records retain tenant, connector, integration, source, record type, external number,
ServiceNow `sys_id`, source update time, and synchronization time. Disabled data is excluded.
Failed synchronization can use the last cache only when the response marks its timestamp and stale
state. Records are conservatively retained rather than immediately hard-deleted.

## Correlation and relationships

CI aliases include the name, short hostname, FQDN, IP address, and lowercase variants. ServiceNow
`cmdb_ci.sys_id` is the authoritative incident/problem/change correlation. Exact alias fallback is
used conservatively; weak text similarity is never presented as an exact match.

`cmdb_rel_ci` traversal is bounded to three levels and tracks visited CIs to prevent loops.
Relationship results retain direction and type (for example Runs on, Depends on, Hosted on, and
Contains).

## Assistant access

The connector exposes only fixed ServiceNow operational tools for status, incidents, journals,
CIs, relationships, related records, problems, and changes. Arbitrary table names, encoded queries,
REST paths, and commands are rejected. Results are labelled `ServiceNow`; Zammad results retain the
`Zammad` source label and independent counts.

## Troubleshooting

- **401:** verify the username/password without logging either value.
- **403:** grant read access to the named table and required fields.
- **404:** confirm the table is active in the instance and permitted for the account.
- **429:** PEKA retries a bounded number of times; reduce page size or sync frequency if persistent.
- **TLS failure:** install the issuing CA and keep verification enabled whenever possible.
- **Stale cache:** inspect the failing stage and last successful synchronization timestamp.

Audit events record configuration changes, enable/disable actions, tests, manual/scheduled syncs,
RPC execution, outcomes, counts, duration, and safe error categories. Passwords and authorization
headers are never audited.
