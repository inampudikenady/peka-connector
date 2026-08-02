# Zammad operational ticket integration

The connector can synchronize permitted Zammad tickets and articles into its local SQLite
store and expose bounded, read-only evidence through PEKA's existing operational-tool RPC.
The integration does not create, modify, close, or delete tickets.

## Compatibility and permissions

The client targets the stable Zammad REST API v1 endpoints for tickets, ticket search,
ticket articles, states, priorities, groups, and users. It assumes a maintained Zammad
release that supports token authentication with `Authorization: Token token=...`, expanded
ticket responses, and page/per-page pagination. Validate an upgraded or customized Zammad
instance with **Test connection** before synchronization.

Create a dedicated, least-privilege Zammad integration user. Its token needs read access to
the ticket groups that PEKA may use and permission to read the corresponding ticket articles.
Do not grant ticket create, update, close, or administration permissions. Internal notes are
available to PEKA only when Zammad itself returns them to this user.

## Configure the connector

1. Sign in to the local connector as an Administrator and open **Zammad**.
2. Enter the HTTPS Zammad origin and a dedicated access token.
3. Select TLS verification, timeout, sync interval, ticket-history window, optional groups,
   whether closed tickets are included, and whether synchronization is enabled.
4. Save, then select **Test connection**. This verifies authentication and ticket-read access.
5. Select **Sync now** for the first import. The page shows ticket/article counts, duration,
   last error, last successful test and sync, and the next scheduled sync.

The base URL is normalized when saved. Leave the token field blank while editing to retain the
existing token. The API returns only whether a token is configured, never the token itself.
Configuration changes are reconciled by the existing connector scheduler without rebuilding.

## Synchronization and freshness

The first synchronization imports the configured bounded history window. Normal scheduled
runs request tickets changed after the saved cursor, with a small overlap to avoid timestamp
boundary gaps. At least daily, the connector reconciles the full bounded window and marks
tickets no longer visible as unavailable. Ticket identity is the Zammad instance plus its
internal ticket ID, so configured instances do not share records.

Broad discovery and historical searches use the local cache. Exact ticket state/latest-update
questions and current counts attempt a live freshness validation first. If Zammad is unavailable
and matching cached data exists, PEKA labels the response as cached and includes its timestamp.
Zammad failure does not suppress otherwise available CMDB, Prometheus, or Loki health evidence.

Semantic discovery uses centralized deterministic concept families and weighted field scoring.
Exact title phrases, title tokens, descriptions, articles, tags, and canonical assets have
different weights; the default acceptance threshold is 0.65. Results include a score,
confidence, and match reasons. Low-confidence matches are omitted rather than padding a result
set. Access provisioning, authentication failures, authorization failures, and account
administration are separate concepts.

## Locally retained data

The connector stores normalized ticket metadata, state, source timestamps, descriptions,
permitted article text and chronology, search text, sync cursor/status, and CMDB correlation
references. HTML is converted to plain text. Ticket text is marked and handled as untrusted
operational evidence. Arbitrary ticket HTML and links are not rendered by the assistant.

Canonical asset attachment requires an exact match through the existing inventory identities
(hostname, FQDN, IP address, canonical name, or CMDB alias). Explicit unmatched identifiers are
kept as search metadata so a later CMDB synchronization can resolve them. Ordinary words never
create new assets.

Recognized assets retain a relationship role such as primary affected asset, impacted asset,
hosting asset, monitoring relationship, service dependency, or mention-only asset. Explicit
unmatched host references are retained as unresolved references. Asset-ticket answers therefore
separate direct incidents from indirect monitoring or dependency context.

The connector constructs ticket navigation URLs only from the configured Zammad origin and the
internal ticket ID. It never trusts links embedded in ticket text and never places credentials in
a URL. SaaS displays these URLs as safe external links while continuing to show the human ticket
number.

## Security model

- The token is AES-256-GCM encrypted with the connector's existing deployment-owned encryption
  key and remains in the connector database.
- The raw token and authorization header are redacted from errors and logs and are never sent to
  PEKA SaaS.
- Only allow-listed, typed, bounded read operations can cross the tenant-scoped connector RPC.
- Responses include only the records and bounded article history needed for the question.
- Zammad remains the permission authority; PEKA cannot retrieve content hidden from the token.

## Token rotation

1. Create a replacement token for the same least-privilege integration user.
2. Open **Zammad**, select **Edit**, enter the replacement token, and save.
3. Run **Test connection**, then **Sync now**.
4. Revoke the previous token in Zammad after both operations succeed.

The old encrypted value is replaced locally and is never displayed.

## Troubleshooting

- **DNS failure / connection refused:** verify name resolution and routing from inside the
  connector container, not only from an administrator workstation.
- **TLS failure:** install the issuing CA in the connector trust store. Disable verification only
  for a controlled temporary test.
- **Authentication failed:** rotate or correct the token.
- **Permission denied:** grant the integration user read access to the intended ticket groups and
  articles; do not add write permission.
- **Malformed response / HTTP failure:** confirm Zammad REST API v1 compatibility and inspect the
  connector's redacted error.
- **Missing ticket:** check the history window, group filter, closed-ticket setting, and the
  integration user's Zammad permissions.
- **Missing asset relation:** confirm that the hostname, FQDN, IP, or alias exists in the connector
  CMDB inventory, then synchronize CMDB and Zammad again.
- **Stale answers:** inspect the last error and next scheduled synchronization. Cached answers
  explicitly show their cache timestamp.

## Supported questions

- How many open tickets are there?
- What is the status of ticket 10023?
- What is the latest update on ticket 10023?
- Find tickets about memory problems.
- Show access or permission requests.
- Show tickets for a hostname, FQDN, IP address, or CMDB alias.
- Does this server have any incidents?
- Did anyone report this issue?
- Give me a health report for this server, including related tickets.
