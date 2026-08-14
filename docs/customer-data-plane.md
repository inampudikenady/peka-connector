# Customer-resident data plane

PEKA Connector v2.0.1 separates the customer data plane from the PEKA SaaS control and
orchestration plane.

```text
Customer sources -> PEKA Connector -> Local Knowledge Store
                           |
                           +-- outbound HTTPS, minimum authorized context --> PEKA SaaS
```

## Customer resident

- customer source systems
- uploaded and explicitly indexed documents
- original document files and durable spool/configuration state
- normalized document chunks and embeddings
- the bundled Local Knowledge Store
- integration credentials and connector secrets
- ServiceNow, Zammad, Prometheus, Loki, CMDB, VMware, and SolarWinds runtime access/caches

The Local Knowledge Store is Qdrant 1.14.1 internally. It is reachable only at
`http://qdrant:6333` on the private Compose network. No Qdrant port, ingress, proxy, Tailscale
route, or host-network binding is created. Collection `peka_documents`, vector dimension 384,
Cosine distance, payload indexes, and schema validation are connector-owned.

One connector registration has one authoritative tenant ID. Every index, query, count, and
delete operation derives that ID from the encrypted connector registration state and applies it
as a mandatory server-side payload filter. Request bodies cannot select or override a tenant.

## PEKA SaaS

- tenant and user metadata
- connector registration, capabilities, and health state
- conversation orchestration and LLM access
- authorization and audit/control policy
- the minimum connector context needed to fulfil an authorized request

SaaS queues a short-lived `knowledge_search` request. The connector claims it using the existing
outbound authenticated polling channel, embeds the query locally, searches the local collection,
filters by its registered tenant, and returns bounded chunks. SaaS clears request arguments and
raw result JSON after the authorized consumer copies the response.

## Transient

Retrieved chunks are request context, distinct from user messages, assistant messages, and tool
execution state. Connector responses contain only stable identifiers, bounded content, score,
source, and citation metadata. Raw retrieval results should remain ephemeral. SaaS currently
persists final citation excerpts in conversation records; reducing or encrypting those excerpts is
a follow-up SaaS persistence decision and is not expanded by this connector milestone.

Customer systems and durable knowledge indexes remain inside the customer environment. The PEKA
Connector sends only the authorized context required to fulfil a request to the PEKA SaaS
service.

## Processing and failure behavior

```text
raw document -> normalize -> redact obvious secrets -> chunk -> local embed -> local index
```

The pre-persistence sanitizer removes private-key blocks, Authorization headers, bearer tokens,
common cloud/GitHub credentials, and common password/token configuration assignments. Logs use
document identifiers and counts, never document bodies.

If the Local Knowledge Store becomes unavailable, `/health` reports `degraded`, indexing/search
return controlled unavailable results, and pending document state remains durable. Registration,
heartbeats, configuration, ServiceNow, Zammad, Prometheus, Loki, and other live tools continue.

## Storage, backup, and upgrade

Back up `peka-data`, `connector_documents`, `connector_cmdb`, and
`peka_connector_qdrant_data` together for a consistent connector recovery point. `docker compose
down` preserves them. Do not use `docker compose down -v` during stop, restart, upgrade, or normal
uninstall. Destructive knowledge deletion must be an explicit future administrative operation.

Startup waits on the Qdrant health check, initializes or validates the collection, then exposes
the connector API. Compatible upgrades reuse the existing volume. Future schema changes must add
explicit migration logic; an incompatible vector dimension fails validation rather than
recreating or wiping the collection.
