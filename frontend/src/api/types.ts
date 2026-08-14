export type Role = 'administrator' | 'read_only';

export interface CurrentUser { id: string; username: string; role: Role }
export interface SetupStatus { setup_required: boolean }
export interface LoginResponse { access_token: string; expires_in: number; token_type: 'bearer' }
export interface Health {
  status: 'healthy' | 'degraded'; version: string;
  components: Record<string, { status: 'healthy' | 'unavailable' }>;
}
export type CMDBImportMode = 'create_new' | 'new_version';

export interface CMDBDataset {
  id: string; name: string; status: string; current_version_id: string | null;
  current_version: number | null; source_filename: string | null; imported_at: string | null;
  total_rows: number; valid_rows: number; invalid_rows: number; updated_at: string;
}
export interface CMDBUpload {
  dataset_id: string; version_id: string; version_number: number; filename: string;
  file_type: 'csv' | 'xlsx'; file_size: number; checksum: string; sheets: string[];
  sheet_name: string | null; header_row: number; headers: string[];
  preview_rows: Record<string, string>[]; suggested_mapping: Record<string, string>;
  detected_total_rows: number; correlation_id: string;
}
export interface CMDBRecord {
  id: string; dataset_version_id: string; dataset_version: number; source_row_number: number;
  normalized_fields: Record<string, string | string[] | null>; validation_status: string;
  validation_errors: string[]; imported_at: string | null;
}
export interface PaginatedCMDBRecords {
  items: CMDBRecord[]; total: number; page: number; page_size: number;
}
export interface PrometheusConfiguration {
  id: string; name: string; base_url: string; auth_type: string; username: string | null;
  has_secret: boolean; tls_verify: boolean; request_timeout_seconds: number;
  scan_interval_seconds: number; enabled: boolean; last_successful_scan_at: string | null;
  last_failed_scan_at: string | null; last_error: string | null; target_count: number;
  healthy_target_count: number; unhealthy_target_count: number;
  warnings: string[];
}
export interface PrometheusDiagnosticStage {
  stage: 'DNS' | 'TCP' | 'TLS' | 'HTTP'; status: 'success' | 'failed';
  code?: string; message: string; duration_ms: number;
}
export interface PrometheusDiagnostics {
  success: boolean; stages: PrometheusDiagnosticStage[]; warnings: string[];
  correlation_id: string;
}
export interface LokiConfiguration {
  id: string; name: string; base_url: string; auth_type: string; username: string | null;
  has_secret: boolean; tls_verify: boolean; request_timeout_seconds: number;
  enabled: boolean; discovery_lookback_days: number;
  last_successful_test_at: string | null; last_successful_discovery_at: string | null;
  last_failed_discovery_at: string | null; last_error: string | null;
  stream_count: number; labels: string[]; label_values: Record<string, string[]>;
  warnings: string[];
}
export interface ZammadConfiguration {
  id: string; name: string; base_url: string; token_configured: boolean;
  tls_verify: boolean; request_timeout_seconds: number; sync_interval_seconds: number;
  history_window_days: number; group_filters: string[]; include_closed_tickets: boolean;
  enabled: boolean; connection_state: string; last_successful_test_at: string | null;
  last_successful_sync_at: string | null; last_sync_duration_seconds: number | null;
  synchronized_ticket_count: number; synchronized_article_count: number;
  last_error: string | null; next_scheduled_sync_at: string | null;
}
export interface ServiceNowConfiguration {
  id: string; integration_id: string; integration: 'servicenow'; enabled: boolean;
  configured: boolean; instance_url: string; username: string; password_configured: boolean;
  verify_tls: boolean; request_timeout_seconds: number; page_size: number;
  sync_interval_seconds: number; connection_state: string; connected: boolean;
  last_test_at: string | null; last_successful_test_at: string | null;
  last_successful_sync_at: string | null; last_sync_error: string | null;
  last_attempted_sync_at: string | null;
  next_scheduled_sync_at: string | null; counts: Record<string, number>;
  availability: { enabled: boolean; state: string; cache_timestamp: string | null; stale: boolean; freshness_state: 'fresh' | 'stale' | 'error'; freshness_threshold_seconds: number; last_error: string | null };
}
export interface ServiceNowCMDBObservability {
  source: 'ServiceNow CMDB'; active: boolean; connection_state: string; sync_state: string;
  last_successful_sync_at: string | null; last_attempted_sync_at: string | null;
  stale: boolean; freshness_state: 'fresh' | 'stale' | 'error';
  freshness_threshold_seconds: number; cache_timestamp: string | null;
  total_cis: number; server_cis: number;
  other_cis: number; relationship_count: number; last_error: string | null;
  items: Array<{ id: string; ci_name: string; ci_class: string; fqdn: string | null;
    ip_address: string | null; operating_system: string | null; environment: string | null;
    application: string | null; business_owner: string | null; support_group: string | null;
    lifecycle_state: string | null; updated_at: string; source: string }>;
  total: number; page: number; page_size: number;
}
export interface IntegrationCatalogItem {
  integration_type: string; name: string; category: string; provider_roles: string[];
  capabilities: Record<string, boolean>; available: boolean;
  unavailable_reason?: string; configuration_fields: string[];
}
export interface ConnectorIntegration {
  id: string; integration_type: string; display_name: string; category: string;
  enabled: boolean; status: string; configuration: Record<string, unknown>;
  capabilities: Record<string, boolean>; last_tested_at: string | null;
  last_successful_test_at: string | null; last_successful_sync_at: string | null;
  initial_sync_status: string; last_error: string | null;
  created_at: string; updated_at: string;
}
export interface IntegrationStreamSource {
  activation_id: string; integration_id: string; source_key: string; source_name: string;
  configured: boolean; selected: boolean; status: string;
  last_successful_sync_at: string | null; last_error: string | null;
}
export interface IntegrationStream {
  stream: 'monitoring' | 'logs' | 'ticketing' | 'cmdb' | 'knowledge';
  display_name: string; selected_source: string | null; sources: IntegrationStreamSource[];
}
export interface TrustedCertificateAuthority {
  id: string; name: string; original_filename: string; fingerprint_sha256: string;
  subject: string; issuer: string; not_valid_before: string; not_valid_after: string;
  expired: boolean; enabled: boolean; created_at: string;
}
export interface InventoryItem {
  id: string; canonical_name: string; hostname: string | null; fqdn: string | null;
  primary_ip: string | null; asset_type: string | null; environment: string | null;
  lifecycle_status: string | null; sources: string[]; coverage: string;
  prometheus_health: string; last_metrics_seen: string | null; correlation_status: string;
}
export interface PaginatedInventory {
  items: InventoryItem[]; total: number; page: number; page_size: number;
}
export interface InventoryDetail {
  asset: Record<string, unknown>;
  observations: Array<{ id: string; source_type: string; status: string; observed_fields: Record<string, unknown>; raw_reference: string; first_seen_at: string; last_seen_at: string }>;
  identities: Array<{ identity_type: string; original_value: string; normalized_value: string; source_type: string }>;
  conflicts: Array<{ id: string; field_name: string; source_values: Record<string, unknown>; resolution_status: string }>;
  services: Array<{ id: string; service_type: string; name: string; protocol: string; port: number; path: string; endpoint: string; first_seen_at: string; last_seen_at: string }>;
  dependencies: Array<{ id: string; relation_type: string; target_asset_id: string | null; target_reference: string; evidence: string; first_seen_at: string; last_seen_at: string }>;
}

export interface SourceConfiguration {
  path: string;
  include_patterns: string[];
  exclude_patterns: string[];
  scan_interval_seconds: number;
}

export interface Source {
  id: string;
  plugin_type: string;
  name: string;
  enabled: boolean;
  configuration: SourceConfiguration;
  created_at: string;
  updated_at: string;
  health_status: string;
  last_success_at: string | null;
  last_error: string | null;
  last_scan_at: string | null;
  file_count: number;
  next_scheduled_scan_at: string | null;
  last_scheduled_scan_at: string | null;
  scan_in_progress: boolean;
}

export interface SourceInput {
  plugin_type: 'filesystem_documents';
  name: string;
  enabled: boolean;
  configuration: SourceConfiguration;
}

export interface ScanRecord {
  id: string; source_id: string; status: string; started_at: string; completed_at: string | null;
  discovered_count: number; added_count: number; changed_count: number; unchanged_count: number;
  missing_count: number; failed_count: number; error: string | null;
  trigger: 'manual' | 'scheduled';
  correlation_id: string;
}
export interface PaginatedScans { items: ScanRecord[]; total: number; page: number; page_size: number }
export interface ScanDetail extends ScanRecord { source_name: string; log_references: string[] }

export interface ActivityEvent {
  id: string; event_type: string; actor_username: string | null; target_type: string | null;
  target_id: string | null; message: string; created_at: string;
  outcome: 'success' | 'warning' | 'failure' | 'information';
  integration?: string | null;
}

export interface PaginatedActivity { items: ActivityEvent[]; total: number; page: number; page_size: number }

export interface OperationalRequestRecord {
  request_id: string; requested_at: string; completed_at: string | null;
  tool_name: string; integration: string; target_asset: string | null;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'expired' | 'cancelled';
  duration_ms: number | null; result_summary: string | null; error_code: string | null;
}
export interface PaginatedOperationalRequests {
  items: OperationalRequestRecord[]; total: number; page: number; page_size: number;
}
export interface ActivityOverview {
  pending_requests: number; running_requests: number; failed_requests: number;
  successful_requests_24h: number; recent_warnings_or_failures: ActivityEvent[];
  last_heartbeat_at: string | null; last_completed_sync_at: string | null;
}

export interface LogEntry {
  id: string; level: string; component: string; message: string;
  context: Record<string, unknown>; created_at: string;
}

export interface PaginatedLogs { items: LogEntry[]; total: number; page: number; page_size: number }

export interface Overview {
  connector_status: string; saas_status: string; last_heartbeat_at: string | null; connector_version: string;
  peka_connector: string; components: Record<string, string>;
  knowledge_store: KnowledgeStoreOverview;
  source_count: number; enabled_source_count: number; unhealthy_source_count: number;
  recent_events: ActivityEvent[]; storage_total_bytes: number | null; storage_free_bytes: number | null;
  enabled_integration_count: number; healthy_integration_count: number;
  attention_integration_count: number; recent_integration_failures: ActivityEvent[];
  connector_display_name: string; instance_id: string; connector_id: string | null; tenant_id: string | null;
  next_heartbeat_at: string | null; heartbeat_failure_count: number;
  last_heartbeat_error: string | null;
  saas_url: string | null; registered_at: string | null; last_heartbeat_attempt_at: string | null;
  heartbeat_interval_seconds: number; heartbeat_round_trip_ms: number | null;
  scheduler_running: boolean; heartbeat_job_scheduled: boolean; source_scheduler_job_count: number;
  document_total: number; document_queued: number; document_uploading: number;
  document_uploaded: number; document_failed: number; document_unsupported: number;
  last_document_delivery_at: string | null; document_endpoint_status: string;
  document_source_health: string; document_source_last_scan_at: string | null;
  document_source_next_scan_at: string | null;
}

export interface KnowledgeStoreOverview {
  status: 'healthy' | 'degraded' | 'unavailable'; engine: 'qdrant';
  engine_version: string | null; collection: string;
  documents: number; chunks: number; pending: number; failed: number;
  last_indexed_at: string | null; last_search_at: string | null;
  checks: {
    qdrant_reachable: boolean; collection_exists: boolean; collection_accessible: boolean;
    statistics_readable: boolean; search_service_operational: boolean;
  };
}

export interface DiagnosticCheck { name: string; status: string; detail: string }
export interface Diagnostics {
  version: string; build: string; python_version: string; platform: string;
  migration_revision: string | null; checks: DiagnosticCheck[];
  instance_id: string; registration_state: string; connection_state: string; saas_hostname: string | null;
  last_heartbeat_attempt_at: string | null; last_successful_heartbeat_at: string | null;
  next_heartbeat_at: string | null; heartbeat_interval_seconds: number; consecutive_failures: number;
  latest_heartbeat_failure_reason: string | null;
  heartbeat_round_trip_ms: number | null; scheduler_running: boolean;
  heartbeat_job_scheduled: boolean; source_scheduler_job_count: number;
  document_worker_running: boolean; document_reconciliation_scheduled: boolean;
  pending_document_jobs: number; stale_document_jobs: number;
}

export interface LocalUser {
  id: string; username: string; role: Role; is_active: boolean;
  created_at: string; updated_at: string; last_login_at: string | null;
}

export interface ProductSettings {
  connector_display_name: string; environment_label: string; log_level: string;
  saas_status: string; connector_id: string | null; tenant_id: string | null;
  saas_url: string | null; last_heartbeat_at: string | null;
  instance_id: string; registered_at: string | null; heartbeat_interval_seconds: number;
  last_heartbeat_attempt_at: string | null; next_heartbeat_at: string | null;
  last_heartbeat_status: string | null; last_heartbeat_error: string | null;
  heartbeat_failure_count: number;
  last_heartbeat_failed_at: string | null; heartbeat_round_trip_ms: number | null;
  last_saas_server_time: string | null;
  metadata_sync_warning: string | null;
}

export interface ManagedDocument {
  id: string; source_id: string; document_key: string; relative_path: string; filename: string;
  normalized_filename: string; extension: string; mime_type: string; size_bytes: number;
  content_hash: string; modified_at: string; discovered_at: string; first_seen_at: string;
  last_seen_at: string; state: string; local_status: string; delivery_status: string; upload_attempt_count: number;
  knowledge_status: string; indexed_chunk_count: number; knowledge_error: string | null;
  last_upload_attempt_at: string | null; uploaded_at: string | null;
  remote_document_id: string | null; remote_version_id: string | null;
  last_error_code: string | null; last_error_message: string | null;
  created_at: string; updated_at: string; deleted_at: string | null; entry_method: string;
  can_delete: boolean; delete_unavailable_reason: string | null; deletion_in_progress: boolean;
}

export interface PaginatedManagedDocuments { items: ManagedDocument[]; total: number; page: number; page_size: number }
export interface DocumentUploadResult { filename: string; success: boolean; document: ManagedDocument | null; code: string | null; message: string }
export interface DocumentUploadBatch { results: DocumentUploadResult[] }

export interface ManagedDocumentSource {
  id: string; name: string; plugin_type: 'filesystem_documents';
  path: '/data/sources/documents'; enabled: boolean; system_managed: true;
  scan_interval_seconds: number; last_scan_at: string | null;
  next_scheduled_scan_at: string | null; last_scan_result: string;
  discovered_document_count: number; health_status: string; last_error: string | null;
}

export interface ManagedDocumentScan {
  discovered: number; changed: number; unchanged: number; removed: number; delayed: number;
}
