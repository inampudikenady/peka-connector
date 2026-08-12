# Pre-v1 architecture assessment

This assessment records the implementation immediately before the PEKA Connector 1.0.0
customer-resident data-plane change. It is intentionally descriptive rather than aspirational.

## 1. What currently runs in PEKA SaaS

PEKA SaaS owns connector registration and heartbeat acceptance, tenant and user identity,
conversation orchestration, the LLM gateway, connector operational-tool request queues, and the
complete document knowledge pipeline. An authenticated connector uploads document bytes to SaaS.
SaaS stores those bytes in its configured object store, persists document/version/parsed-section/
chunk/job metadata and chunk text in PostgreSQL, generates embeddings with its configured
OpenAI-compatible provider, writes vectors to Qdrant, and queries that Qdrant collection from
`KnowledgeService` during answer generation.

The SaaS collection name defaults to `peka_document_chunks`. Its Qdrant deployment is optional
under the `documents` Compose profile, uses `qdrant/qdrant:v1.14.1`, and persists to either
`peka_saas_qdrant` or the older standalone `peka_qdrant_data` volume. Both current SaaS Compose
forms publish Qdrant port 6333; the standalone development form also publishes 6334.

## 2. What currently runs in the connector

The connector is a FastAPI and compiled React appliance backed by SQLite and APScheduler. It
provides local authentication, source/document administration, configuration, registration,
heartbeats, diagnostics, CMDB inventory, and live or locally synchronized ServiceNow, Zammad,
Prometheus, and Loki tools. Its typed SaaS client makes outbound registration, heartbeat,
document-delivery, and operational-tool polling/result calls. There is no connector-side parser,
chunker, embedding service, knowledge abstraction, or vector store.

The source-plugin abstraction currently covers discoverable document sources; the integration
catalog/lifecycle abstraction represents documents, CMDB, Prometheus, Loki, Zammad, and
ServiceNow. Operational integrations are not sent to Qdrant. Zammad tickets and ServiceNow
records are cached in connector SQLite, Prometheus inventory observations and CMDB imports are
stored locally, and Loki evidence remains API-driven.

## 3. Where documents are currently stored

Customer-uploaded/current document files live in the connector's `connector_documents` named
volume at `/data/sources/documents`. Immutable delivery snapshots live under `/data/spool` in the
`peka-data` named volume until SaaS acknowledges them. SaaS also stores a durable copy in its
configured object store (the development Compose volume is `peka_saas_documents`).

## 4. Where extracted text is currently stored

Only SaaS extracts document text. It stores parsed section text in
`document_parsed_sections.text` and final chunk text in `document_chunks.text` in PostgreSQL.
Connector SQLite stores file metadata and delivery state but no extracted text or chunks.

## 5. Where embeddings are generated

SaaS generates embeddings in its ingestion worker through `EmbeddingProvider`. Production uses
an OpenAI-compatible endpoint when configured; tests can use the deterministic fake provider.
The connector does not currently generate embeddings.

## 6. Where Qdrant currently runs

Qdrant runs as an optional SaaS/development infrastructure service, not as part of the connector.
SaaS calls it directly over HTTP through `QdrantVectorStore`. The repository does not use the
Python Qdrant client; it uses `httpx` against Qdrant's REST API.

## 7. Where Qdrant data persists

The integrated SaaS Compose file uses `peka_saas_qdrant`; the older standalone Qdrant Compose
file uses an explicitly named `peka_qdrant_data` volume. Neither volume is connector-owned.

## 8. Customer operational data currently persisted in SaaS

SaaS durably persists uploaded document bytes, document identity/version metadata, parsed text,
chunk text, embedding provenance, vector references, and Qdrant vectors. It also persists
operational-tool request arguments and completed result JSON in `operational_tool_requests`.
Conversation messages persist user and assistant text, citations, retrieval summary metadata,
and operational follow-up context. The document answer path does not persist the complete raw
retrieval response, but citation records can include evidence excerpts. Connector registration,
tenant association, capabilities, status, and heartbeat timestamps also persist in SaaS.

## 9. Connector APIs and contracts that need to change

- Add a connector-local authenticated knowledge search API and knowledge statistics/health.
- Add a connector-side knowledge service boundary for collection initialization, upsert, search,
  metadata filtering, document/tenant deletion, schema validation, and statistics.
- Make upload, direct-copy reconciliation, update, and deletion drive local indexing rather than
  normal document-byte delivery to SaaS.
- Extend health/version responses with connector and Local Knowledge Store component state.
- Advertise an explicit local-knowledge capability in registration and heartbeats.
- Extend the existing outbound operational request channel with a knowledge-search request so
  SaaS can retrieve authorized context without an inbound connector or Qdrant connection.
- Change SaaS answer retrieval to use connector results for connectors advertising the new
  capability, while retaining the existing central pipeline only as a documented migration/
  compatibility path until existing knowledge is moved and validated.

## Isolation and lifecycle observations

One connector registration stores exactly one SaaS `tenant_id` in connector product settings.
Document ownership fields already bind local records to instance, connector, and tenant IDs.
The v1 local collection must therefore derive its tenant filter from this registered identity and
must reject client-provided tenant overrides. Current lifecycle scripts use `docker compose down`
without `-v`, so named volumes survive normal stop/restart; no existing script automatically
deletes volumes.
