# Plugin framework

Plugins are trusted modules shipped with the signed connector image and registered explicitly. Arbitrary customer Python is never loaded.

A source plugin provides a durable type, display name, Pydantic configuration schema, asynchronous validation, and metadata discovery. A discovery batch includes records plus a failed-file count. Application services own persistence, authorization, history, logging, and scheduling.

## Filesystem Documents

Type: `filesystem_documents`.

Configuration:

- absolute `path` restricted to `/data/sources` or descendants
- include and exclude glob lists
- scan interval from 30 through 86,400 seconds

Defaults include PDF, DOCX, TXT, and Markdown. Defaults exclude temporary Office files, hidden entries, `tmp`, and `archive` trees. Validation resolves paths, rejects traversal and symlink escapes, requires an existing readable directory, and never changes the Docker mount.

Discovery does not follow symlinks. It reads included file bytes only to calculate SHA-256 and records relative path, filename, extension, size, modification time, discovery time, last-seen time, and state. It performs no content extraction or SaaS-side processing.

Future Prometheus, Loki, Zammad, ServiceNow, SharePoint, Confluence, and Jira packages can reuse registration and orchestration, but remain absent from the UI until implemented and tested. Non-document sources should introduce suitable domain records rather than forcing all data into document metadata.
