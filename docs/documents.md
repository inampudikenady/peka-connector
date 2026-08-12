# Managed local document knowledge

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

Local knowledge states include Pending, Indexed, Failed, Delete Pending, and Deleted. Every stable
content hash is normalized, sanitized, chunked, embedded locally, and reconciled by stable
document ID. Indexing work is rebuilt from durable SQLite state after restart. An unavailable
Local Knowledge Store does not remove the original file or stop live integrations.

## Retrieval contract

The connector exposes authenticated `POST /api/v1/knowledge/search` for local administration.
PEKA SaaS queues the same bounded `knowledge_search` operation through its existing connector
request channel. The connector always derives tenant scope from registration and never accepts a
tenant override from either request.

## Deletion

Deleting a UI-uploaded document removes the local file, records a durable tombstone, and deletes
all matching Local Knowledge Store chunks. If the store is unavailable, the tombstone remains
Delete Pending for retry. Files copied by an operator must be removed by that operator; future
external-source plugins must not delete customer source files.

The connector performs extraction for supported text-bearing files, chunking, local embeddings,
indexing, and retrieval. OCR and AI inference are not part of this release.
