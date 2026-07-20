export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
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
}

export interface SourceInput {
  plugin_type: 'filesystem_documents';
  name: string;
  enabled: boolean;
  configuration: SourceConfiguration;
}

export interface DocumentMetadata {
  relative_path: string;
  filename: string;
  extension: string;
  size_bytes: number;
  modified_at: string;
  sha256: string;
}

