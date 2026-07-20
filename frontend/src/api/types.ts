export type Role = 'administrator' | 'read_only';

export interface CurrentUser { id: string; username: string; role: Role }
export interface SetupStatus { setup_required: boolean }
export interface LoginResponse { access_token: string; expires_in: number; token_type: 'bearer' }

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
}

export interface ActivityEvent {
  id: string; event_type: string; actor_username: string | null; target_type: string | null;
  target_id: string | null; message: string; details: Record<string, unknown>; created_at: string;
}

export interface LogEntry {
  id: string; level: string; component: string; message: string;
  context: Record<string, unknown>; created_at: string;
}

export interface PaginatedLogs { items: LogEntry[]; total: number; page: number; page_size: number }

export interface Overview {
  connector_status: string; saas_status: string; last_heartbeat_at: string | null; connector_version: string;
  source_count: number; enabled_source_count: number; unhealthy_source_count: number;
  recent_failures: ActivityEvent[]; storage_total_bytes: number | null; storage_free_bytes: number | null;
}

export interface DiagnosticCheck { name: string; status: string; detail: string }
export interface Diagnostics {
  version: string; build: string; python_version: string; platform: string;
  migration_revision: string | null; checks: DiagnosticCheck[];
}

export interface LocalUser {
  id: string; username: string; role: Role; is_active: boolean;
  created_at: string; updated_at: string; last_login_at: string | null;
}

export interface ProductSettings {
  connector_display_name: string; environment_label: string; log_level: string; timezone: string;
  saas_status: string; connector_id: string | null; tenant_id: string | null;
  saas_url: string | null; last_heartbeat_at: string | null;
}
