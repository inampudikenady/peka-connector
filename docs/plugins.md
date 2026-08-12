# Plugin framework

Plugins are trusted modules shipped with the signed connector image and registered explicitly. Arbitrary customer Python is never loaded.

A source plugin provides a durable type, display name, Pydantic configuration schema, asynchronous validation, and metadata discovery. A discovery batch includes records plus a failed-file count. Application services own persistence, authorization, history, logging, and scheduling. Plugins never create scheduler jobs or make SaaS calls directly.

## Filesystem Documents

Type: `filesystem_documents`.

Configuration:

- absolute `path` restricted to `/data/sources` or descendants
- include and exclude glob lists
- scan interval from 30 through 86,400 seconds

Defaults include PDF, DOCX, TXT, and Markdown. Defaults exclude temporary Office files, hidden entries, `tmp`, and `archive` trees. Validation resolves paths, rejects traversal and symlink escapes, requires an existing readable directory, and never changes the Docker mount.

Discovery does not follow symlinks. It reads included file bytes only to calculate SHA-256 and records relative path, filename, extension, size, modification time, discovery time, last-seen time, and state. It performs no content extraction or SaaS-side processing.

Enabled sources receive one UTC interval job. Create/update reconciles the interval, disable/delete removes it, and startup rebuilds jobs. Manual and scheduled runs share discovery/reconciliation; history identifies the trigger and overlapping runs are skipped.

Future SharePoint, Confluence, and Jira packages can reuse registration and orchestration, but remain absent from the UI until implemented and tested. Prometheus, Loki, Zammad, and ServiceNow use dedicated domain records and configuration surfaces rather than forcing non-document data into document metadata.

## Built-in managed documents

The built-in source uses the normal `filesystem_documents` plugin type plus `system_managed=true`; there is no incompatible managed-only plugin type. It is absent from generic source lists and cannot be created, renamed, repathed, or deleted through customer APIs. Documents exposes only enabled state, bounded scan interval, Scan now, and health testing. Future external-source plugins may reuse delivery jobs, but must never delete customer source files automatically.

Existing non-managed filesystem source rows are preserved as legacy records. They are not displayed in the simplified navigation and do not participate in managed document identity. A future migration experience can expose them when an associated source type is complete.
