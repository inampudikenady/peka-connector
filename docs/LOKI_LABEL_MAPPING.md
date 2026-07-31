# Loki Label Mapping

PEKA discovers Loki's schema from the connector. Neither PEKA SaaS nor the
Assistant creates LogQL or assumes a label such as `host`, `instance`, `job`,
`container`, or `service`.

## Discovery

For every enabled Loki configuration, the connector:

1. Reads `/loki/api/v1/labels`.
2. Reads `/loki/api/v1/label/<label>/values` for each discovered label.
3. Scans `/loki/api/v1/series` in bounded one-day windows, sending one repeated
   `match[]` selector for every safe discovered label. Querying every label is
   necessary because streams do not necessarily share a common label.
4. Stores the discovered labels, capped label values, stream label maps, and
   the discovery window in the connector-local database.

The scan window is configurable from 1 to 90 days and defaults to 30 days.
Daily scans avoid Loki 2.9 TSDB query-scheduler failures observed with a single
wide series request.

## Observed Loki 2.9.8 schema

Live discovery on 2026-07-30 against
`http://util001.demo.internal:3100` returned:

| Label | Observed values |
| --- | --- |
| `channel` | `Application`, `Security`, `System` |
| `computer` | `win001` |
| `environment` | `demo` |
| `host` | `lin001.demo.internal`, `util001.demo.internal`, `win001.demo.internal` |
| `job` | `systemd-journal`, `windows-events` |
| `os` | `linux`, `windows` |

Five current streams were observed: one systemd-journal stream for
`lin001.demo.internal`, one for `util001.demo.internal`, and three Windows event
streams for `win001.demo.internal`. This table documents live evidence; it is
not encoded as a runtime schema. An earlier preserved index segment also exposed
legacy `filename`, `auth`, and `syslog` values, demonstrating why runtime
discovery cannot depend on a static mapping.

No container or service label exists in the observed data. If Loki later
exposes those labels, the same discovery and correlation algorithm evaluates
them without a code change.

## Asset correlation

The connector first resolves the Assistant identifier to one canonical
inventory asset. Resolution accepts:

- canonical name;
- hostname, FQDN, or short hostname;
- primary IP;
- normalized inventory identities, including aliases and additional observed
  identities.

The connector then creates a candidate set from the canonical fields, all
inventory identities, and observed service names/endpoints. Every value on
every discovered Loki stream is normalized and compared with this set.
Correlation output records the exact label, original value, and normalized
value that matched.

An asset with no exact discovered match returns `LOKI_STREAM_NOT_FOUND` and an
empty evidence list. It is reported as unknown, not healthy and not as “zero
errors.”

## Query boundary

Only connector-owned evidence categories are queryable:

- errors;
- warnings;
- restarts;
- crashes;
- exceptions;
- authentication failures;
- kernel failures;
- filesystem and disk failures;
- out-of-memory events;
- application failures.

The SaaS RPC accepts a category enum and a fixed lookback enum. The connector
builds the selector exclusively from a correlated, discovered stream and adds
a connector-owned regular expression. Request models reject additional fields,
including `logql`. There is no HTTP API that accepts a query string and no
unrestricted LogQL or command capability is exposed to SaaS.
