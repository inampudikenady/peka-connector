# Plugin framework

## Contract

A source plugin declares a stable `plugin_type`, a display name, and a Pydantic configuration model. It implements two operations:

1. `validate(config)` checks whether the configured source can be used and raises `PluginValidationError` with an administrator-safe message.
2. `discover(config)` asynchronously yields `DiscoveredDocument` metadata.

Plugins do not own persistence, HTTP routes, authentication, or scheduling. Application services invoke them and repository adapters persist their results. This keeps connector implementations easy to test and prevents infrastructure concerns from spreading between integrations.

Plugins are trusted code shipped with a signed connector release. The current registry is explicit and in-process; PEKA Connector does not load arbitrary Python from customer directories. A packaging or entry-point mechanism should be introduced only when independently distributed plugins are required.

## Filesystem Document Source

Plugin type: `filesystem_documents`.

Configuration fields:

- `path`: absolute directory path visible to the backend container
- `include_patterns`: glob patterns; defaults to PDF, DOCX, TXT, and Markdown
- `exclude_patterns`: glob patterns applied to directories and files
- `scan_interval_seconds`: 30 through 86,400 seconds

Validation requires an existing, readable, searchable directory. Discovery does not follow symbolic links, filters to the supported extensions, reads files only to calculate SHA-256, and yields relative path, filename, extension, byte size, modification time, and hash. Individual files that disappear or become unreadable during a scan are skipped. The plugin never parses document contents.

## Adding a plugin

1. Add a package under `app/plugins/<name>` with a Pydantic configuration model and `SourcePlugin` implementation.
2. Give `plugin_type` a durable machine identifier; stored sources depend on it.
3. Keep discovery output domain-oriented. New source families may require a new domain item type and purpose-specific plugin contract rather than adding unrelated optional fields.
4. Register the plugin once during application composition in `app/main.py`.
5. Add unit tests for validation, filtering, transient failures, and metadata mapping.
6. Document network requirements, secrets, rate limits, and permissions.

Prometheus, Loki, Zammad, ServiceNow, SharePoint, Confluence, and Jira can reuse registration, typed configuration, application orchestration, and repository patterns. Metrics, logs, tickets, and pages should receive their own discovery item types when implemented; they should not be forced into document metadata.

