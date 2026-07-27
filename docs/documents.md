# Managed document delivery

## Directory and deployment

The connector accepts managed documents only under `/data/sources/documents`. The path is fixed, cannot be configured through an API or the UI, and is validated as readable and writable at startup and in Diagnostics.

The production Compose file mounts `connector_documents` directly at
`/data/sources/documents`. The customer-selected external source tree is a separate read-only bind
at `/data/external-sources`, so it does not overlap the managed writable document volume.

```yaml
volumes:
  - connector_documents:/data/sources/documents
```

For a controlled host mapping, replace that line with:

```yaml
volumes:
  - ./documents:/data/sources/documents
```

Do not make the general `/data/sources` mount writable. The connector does not follow symlinks and never scans outside the managed root.

## Entry methods and supported files

Administrators can select or drag multiple files on the Documents page. The same pipeline discovers files copied directly into the managed directory during periodic reconciliation. Supported extensions are `.txt`, `.md`, `.csv`, `.pdf`, `.docx`, and `.xlsx`. Extension, supplied MIME type, and safe format signatures are checked. Text must be UTF-8. Executables, scripts, archives, legacy Office files, presentations, hidden system files, zero-byte files, symlinks, and detectable encrypted documents are rejected.

The connector initializes exactly one source named **Uploaded Documents**. The Documents page has **Files** and **Source settings** tabs. Source settings shows the fixed path, enabled state, interval, scan timestamps/result, discovered count, and health. Administrators can enable/disable, change the interval, scan immediately, or test health. The path and file policies are read-only, and there is no separate Sources navigation item.

Defaults are 100 MB per file, 20 files per request, 500 MB per request, and 255 filename characters. Deployment operators can override the corresponding `PEKA_DOCUMENT_*` bootstrap environment values. They are operational safeguards, not customer path controls.

## Processing and statuses

UI requests stream one-megabyte chunks to a generated temporary filename. Limits and SHA-256 are evaluated while streaming; the file is fsynced and atomically renamed only after validation. Direct-copy files must retain the same size and modification time across checks and remain stable for the configured window.

Local states include Discovered, Waiting For Stability, Ready, Queued, Uploading, Uploaded, Upload Failed, Unsupported, and Deleted. PEKA delivery status is tracked separately; the connector does not infer PEKA parsing or indexing state.

Every stable version creates an immutable spool snapshot and SQLite job. UPSERT and DELETE jobs survive restart, prevent duplicate active versions, recover stale in-progress work, retry transient failures with bounded exponential backoff and jitter, and reuse one idempotency key after ambiguous timeouts. Authentication failures are visible and are not retried aggressively. Validation failures require a corrected file or explicit administrative action.

## Expected PEKA contract

`POST /api/v1/connectors/{connector_id}/documents` uses the existing Bearer connector credential, `X-PEKA-Connector-ID`, and `Idempotency-Key`. UPSERT is multipart with original bytes plus a JSON metadata envelope containing source/document identity, relative path, filename, MIME type, byte size, `sha256:<hash>`, modification time, operation, and connector version. DELETE is a metadata-only tombstone. The payload never selects `tenant_id`; PEKA derives ownership from authenticated credentials.

The connector marks a version uploaded only after a response with `accepted: true` and, for UPSERT, an acknowledged hash exactly matching the sent hash. Timeouts and connection closes are ambiguous and retry with the same key. If the endpoint is unavailable, production never fabricates success: jobs remain failed-retryable with an accurate safe error.

## Deletion

Deleting a UI-uploaded document asks: “Delete this document from the connector and PEKA?” The local file is removed immediately, the logical record is tombstoned, and remote deletion retries until acknowledged. The tombstone prevents accidental rediscovery. Files copied by an operator must be removed by that operator; future external-source plugins must not delete customer source files.

PEKA—not the connector—performs parsing, OCR, chunking, embeddings, Qdrant/vector indexing, retrieval, and AI.
