# Existing SaaS knowledge migration plan

PEKA Connector 1.0.2 does not delete or rewrite existing SaaS document objects, PostgreSQL rows,
or Qdrant points. Existing central collection `peka_document_chunks` remains a compatibility and
rollback source until each tenant is migrated and validated.

Use one controlled path per tenant:

1. Inventory SaaS documents, versions, hashes, chunk counts, and source connector ownership.
2. Prefer re-indexing from the original files still held in the connector managed-document
   volume. This re-applies the connector's current normalization and sanitization policy.
3. If an original is unavailable, export a tenant-scoped package over an authenticated channel;
   never expose either Qdrant instance or accept a tenant ID supplied without registration
   validation.
4. Import/re-index into the connector collection and validate document hashes, document counts,
   chunk counts, tenant filters, representative queries, updates, and deletions.
5. Advertise `local_knowledge`, switch normal retrieval for that connector, and monitor controlled
   fallback/rollback metrics.
6. Retain SaaS objects and vectors for an agreed rollback period. Any later SaaS cleanup must be
   a separately authorized, audited, tenant-scoped destructive operation.

The repository does not yet contain a production export/import command, so no existing SaaS data
has been migrated by this release. A v1.1.0 migration utility should provide resumable manifests,
hash verification, dry-run reporting, explicit tenant/connector binding, and post-import query
validation.
