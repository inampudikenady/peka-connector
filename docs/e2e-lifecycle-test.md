# Connector lifecycle end-to-end test

Use isolated development tenants and tokens. Never corrupt production credentials.

1. Start SaaS and Connector, create/select a tenant, generate a token, and create the first local Connector Administrator.
2. Register through Settings using the development SaaS origin. Capture connector ID, tenant ID, instance ID, and version on both sides.
3. Observe Awaiting First Heartbeat, then Connected only after SaaS accepts the immediate heartbeat. Verify all captured identifiers, version, and aggregate source counts match.
4. Stop Connector. After more than 1.5 expected intervals verify SaaS reports Out of Sync; after at least 3 verify Disconnected.
5. Restart Connector. Verify its single heartbeat job is restored and both sides return to Connected.
6. Stop or isolate SaaS. Verify Reconnecting, then time-based Out of Sync/Disconnected. Restore SaaS and verify automatic recovery and a Reconnected activity event.
7. In an isolated fixture, register a connector, replace only that fixture's credential with an invalid value, and verify Authentication Failed. Re-register with a new one-time token and verify recovery.

Automated contract, scheduler, persistence, recovery, authorization, and redaction tests run in the backend suite. A live test additionally requires a running SaaS stack and a newly issued tenant-scoped token, so the environment-specific provisioning steps remain operator supplied.
