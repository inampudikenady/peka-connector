# Stream and source architecture

PEKA Connector v2.0.1 groups operational integrations into five streams: Monitoring, Logs,
Ticketing, CMDB, and Knowledge. A configured integration connection can expose one or more source
capabilities. ServiceNow therefore owns one credential/configuration record while exposing separate
`servicenow` Ticketing and `servicenow_cmdb` CMDB sources.

`integration_stream_activations` is the authoritative routing layer. Each row is scoped by connector,
stream, integration, and source key. In v2.0.1 its legacy `enabled` and `active` columns are
constrained to the same selected-source value. A partial unique index on `(connector_id, stream)`
prevents two sources in one stream from being selected. Switching locks the stream rows, updates
the old and new selection inside one database transaction, and commits once. Configuration and
caches are retained.

Operational code resolves the active stream source before selecting an adapter. Inactive caches are
not fallback data. In particular, Ticketing returns one logical source and CMDB never combines Local
CMDB with ServiceNow CMDB. Cross-source federation within a stream is intentionally deferred.

## Migration

The `20260813_0017` migration derives source rows from existing connector integrations. The
`20260814_0018` migration normalizes v2.0.0 rows to selected-source semantics. An existing active
row wins. If no row is active but multiple rows are enabled, the most recently activated or updated
row wins, with row UUID as a deterministic tie-breaker and a migration warning. Other saved
configuration remains retained but not selected. ServiceNow source rows are created only for
capabilities already enabled in `capabilities_json`, so Ticketing does not imply CMDB.

## Operational request diagnostics

The existing operational request UUID is the correlation ID across SaaS dispatch, connector claim,
routing, source execution, result submission, and SaaS receipt. Logs contain stage names, elapsed
milliseconds, and source timings without request payloads. The connector also records total request
duration in its audit view.

The prior claim lease was 15 seconds while the request deadline was 30 seconds and individual
downstream adapters could wait 15–20 seconds. Valid results could therefore be rejected after their
claim expired. The claim now shares the request deadline, source timings identify delays, and the
estate assessment limits Loki expansion to candidates already identified by broad monitoring state.
Partial source errors remain explicit rather than fabricating evidence.

## Heartbeat recovery

Heartbeat delivery uses a one-shot job because success and failure select different next delays.
Previously its 60-second misfire grace allowed APScheduler to discard the only heartbeat after a
long sleep, leaving no job to schedule its successor. Heartbeat jobs now execute missed runs on
resume. Startup still schedules an immediate heartbeat. The normal cadence is 60 seconds, with
temporary-stale and unavailable thresholds after 1.5 and 3 intervals respectively, so one missed
heartbeat does not mark a connector dead. Successful recovery resets failure state, and normal
retry/backoff handles temporary network loss. SaaS continues to distinguish connected,
temporarily out-of-sync, and disconnected states; a request timeout remains distinct from connector
unavailability.
