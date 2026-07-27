import type {
  CurrentUser, Diagnostics, LocalUser, LoginResponse, Overview, PaginatedActivity,
  DocumentUploadBatch, ManagedDocumentScan, ManagedDocumentSource, PaginatedLogs, PaginatedManagedDocuments, PaginatedScans, ProductSettings, ScanDetail, ScanRecord, SetupStatus, Source, SourceInput,
  CMDBDataset, CMDBUpload, PaginatedCMDBRecords, PrometheusConfiguration, PaginatedInventory, InventoryDetail,
} from './types';

let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string) { super(message); }
}

function csrfToken(): string | null {
  const item = document.cookie.split('; ').find((cookie) => cookie.startsWith('peka_csrf='));
  return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : null;
}

async function parseError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown; code?: unknown };
  let message = 'Request failed';
  if (typeof body.detail === 'string') message = body.detail;
  if (Array.isArray(body.detail)) {
    message = body.detail.map((item) => (item as { msg?: string }).msg ?? 'Invalid value').join('. ');
  }
  const code = typeof body.code === 'string' ? body.code : undefined;
  return new ApiError(message, response.status, code);
}

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const csrf = csrfToken();
    if (!csrf) return false;
    const response = await fetch('/api/v1/auth/refresh', {
      method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf },
    });
    if (!response.ok) { accessToken = null; return false; }
    const result = await response.json() as LoginResponse;
    accessToken = result.access_token;
    return true;
  })().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init.headers,
    },
  });
  // Registration endpoints can legitimately relay a SaaS 401 (invalid one-time
  // token). That must not be mistaken for expiry of the local administrator's
  // session.
  const relaysSaasAuthentication = path === '/settings/saas/register'
    || path === '/settings/saas/reregister';
  if (response.status === 401 && !relaysSaasAuthentication && retry && await refreshAccessToken()) {
    return request(path, init, false);
  }
  if (!response.ok) {
    if (response.status === 401 && !relaysSaasAuthentication) unauthorizedHandler?.();
    throw await parseError(response);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function download(path: string, filename: string): Promise<void> {
  let response = await fetch(`/api/v1${path}`, { credentials: 'same-origin', headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} });
  if (response.status === 401 && await refreshAccessToken()) response = await fetch(`/api/v1${path}`, { credentials: 'same-origin', headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} });
  if (!response.ok) throw await parseError(response);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}

export const api = {
  setUnauthorizedHandler: (handler: () => void) => { unauthorizedHandler = handler; },
  setupStatus: (): Promise<SetupStatus> => request('/auth/setup-status'),
  bootstrap: (username: string, password: string, confirmPassword: string): Promise<CurrentUser> =>
    request('/auth/bootstrap', { method: 'POST', body: JSON.stringify({ username, password, confirm_password: confirmPassword }) }),
  async login(username: string, password: string): Promise<void> {
    const result = await request<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }, false);
    accessToken = result.access_token;
  },
  async restoreSession(): Promise<boolean> { return refreshAccessToken(); },
  async logout(): Promise<void> {
    const csrf = csrfToken();
    await request('/auth/logout', { method: 'POST', headers: csrf ? { 'X-CSRF-Token': csrf } : {} }, false).catch(() => undefined);
    accessToken = null;
  },
  me: (): Promise<CurrentUser> => request('/auth/me'),
  changePassword: (currentPassword: string, newPassword: string, confirmPassword: string): Promise<void> =>
    request('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword }) }),
  overview: (): Promise<Overview> => request('/overview'),
  activity: (page = 1): Promise<PaginatedActivity> => request(`/activity?page=${page}&page_size=25`),
  logs: (query: string): Promise<PaginatedLogs> => request(`/logs?${query}`),
  downloadLogs: (): Promise<void> => download('/logs/download', 'peka-connector-logs.jsonl'),
  diagnostics: (): Promise<Diagnostics> => request('/diagnostics'),
  downloadDiagnostics: (): Promise<void> => download('/diagnostics/bundle', 'peka-diagnostics.zip'),
  listSources: (): Promise<Source[]> => request('/sources'),
  createSource: (source: SourceInput): Promise<Source> => request('/sources', { method: 'POST', body: JSON.stringify(source) }),
  updateSource: (id: string, source: Omit<SourceInput, 'plugin_type'>): Promise<Source> => request(`/sources/${id}`, { method: 'PUT', body: JSON.stringify(source) }),
  validateSourceInput: (source: SourceInput): Promise<{ valid: boolean; message: string }> => request('/sources/validate', { method: 'POST', body: JSON.stringify(source) }),
  validateSource: (id: string): Promise<{ valid: boolean; message: string }> => request(`/sources/${id}/validate`, { method: 'POST' }),
  deleteSource: (id: string): Promise<void> => request(`/sources/${id}`, { method: 'DELETE' }),
  scanSource: (id: string): Promise<ScanRecord> => request(`/sources/${id}/scan`, { method: 'POST' }),
  scanHistory: (id: string, page = 1): Promise<PaginatedScans> => request(`/sources/${id}/scans?page=${page}&page_size=20`),
  scanDetail: (sourceId: string, scanId: string): Promise<ScanDetail> => request(`/sources/${sourceId}/scans/${scanId}`),
  documents: (page = 1): Promise<PaginatedManagedDocuments> => request(`/documents?page=${page}&page_size=25`),
  documentSource: (): Promise<ManagedDocumentSource> => request('/documents/source'),
  updateDocumentSource: (enabled: boolean, scanIntervalSeconds: number): Promise<ManagedDocumentSource> => request('/documents/source', { method: 'PUT', body: JSON.stringify({ enabled, scan_interval_seconds: scanIntervalSeconds }) }),
  testDocumentSource: (): Promise<ManagedDocumentSource> => request('/documents/source/test', { method: 'POST' }),
  scanDocuments: (): Promise<ManagedDocumentScan> => request('/documents/source/scan', { method: 'POST' }),
  uploadDocuments(files: File[], onProgress: (percent: number) => void): Promise<DocumentUploadBatch> {
    return new Promise((resolve, reject) => {
      const form = new FormData(); files.forEach((file) => form.append('files', file, file.name));
      const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/v1/documents/upload');
      if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
      xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100)); };
      xhr.onerror = () => reject(new ApiError('Document upload could not reach the connector', 0));
      xhr.onload = () => {
        let body: unknown = null; try { body = JSON.parse(xhr.responseText); } catch { body = null; }
        if (xhr.status >= 200 && xhr.status < 300) { resolve(body as DocumentUploadBatch); return; }
        const error = body as { detail?: unknown; message?: unknown; code?: unknown } | null;
        const message = typeof error?.message === 'string' ? error.message : typeof error?.detail === 'string' ? error.detail : 'Document upload failed';
        reject(new ApiError(message, xhr.status, typeof error?.code === 'string' ? error.code : undefined));
      };
      xhr.send(form);
    });
  },
  retryDocument: (id: string): Promise<{ message: string }> => request(`/documents/${id}/retry`, { method: 'POST' }),
  deleteDocument: (id: string): Promise<void> => request(`/documents/${id}`, { method: 'DELETE' }),
  cmdbFields: (): Promise<{ fields: string[]; identity_fields: string[] }> => request('/cmdb/fields'),
  cmdbDatasets: (): Promise<CMDBDataset[]> => request('/cmdb/datasets'),
  cmdbRecords: (query: string): Promise<PaginatedCMDBRecords> => request(`/cmdb/records?${query}`),
  uploadCMDB(file: File, datasetName: string, datasetId?: string): Promise<CMDBUpload> {
    const form = new FormData(); form.append('file', file, file.name); form.append('dataset_name', datasetName);
    if (datasetId) form.append('dataset_id', datasetId);
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/v1/cmdb/upload');
      if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
      xhr.onerror = () => reject(new ApiError('CMDB upload could not reach the connector', 0));
      xhr.onload = () => {
        let body: unknown = null; try { body = JSON.parse(xhr.responseText); } catch { body = null; }
        if (xhr.status >= 200 && xhr.status < 300) { resolve(body as CMDBUpload); return; }
        const error = body as { detail?: unknown; code?: unknown } | null;
        reject(new ApiError(typeof error?.detail === 'string' ? error.detail : 'CMDB upload failed', xhr.status, typeof error?.code === 'string' ? error.code : undefined));
      };
      xhr.send(form);
    });
  },
  previewCMDB: (versionId: string, sheetName: string | null, headerRow: number): Promise<Omit<CMDBUpload, 'dataset_id' | 'version_id' | 'version_number' | 'filename' | 'file_type' | 'file_size' | 'checksum' | 'sheets' | 'correlation_id'>> =>
    request(`/cmdb/versions/${versionId}/preview`, { method: 'POST', body: JSON.stringify({ sheet_name: sheetName, header_row: headerRow }) }),
  importCMDB: (versionId: string, sheetName: string | null, headerRow: number, mapping: Record<string, string>): Promise<{ valid_rows: number; invalid_rows: number; total_rows: number }> =>
    request(`/cmdb/versions/${versionId}/import`, { method: 'POST', body: JSON.stringify({ sheet_name: sheetName, header_row: headerRow, mapping }) }),
  cmdbMappingProfiles: (): Promise<Array<{ id: string; name: string; mapping: Record<string, string> }>> => request('/cmdb/mapping-profiles'),
  saveCMDBMappingProfile: (name: string, mapping: Record<string, string>): Promise<void> => request('/cmdb/mapping-profiles', { method: 'POST', body: JSON.stringify({ name, mapping, normalization: {} }) }),
  renameCMDB: (datasetId: string, name: string): Promise<void> => request(`/cmdb/datasets/${datasetId}/name`, { method: 'PUT', body: JSON.stringify({ name }) }),
  retireCMDB: (datasetId: string): Promise<void> => request(`/cmdb/datasets/${datasetId}/retire`, { method: 'POST' }),
  deleteCMDB: (datasetId: string): Promise<void> => request(`/cmdb/datasets/${datasetId}`, { method: 'DELETE' }),
  prometheusConfigurations: (): Promise<PrometheusConfiguration[]> => request('/prometheus/configurations'),
  createPrometheusConfiguration: (body: object): Promise<PrometheusConfiguration> => request('/prometheus/configurations', { method: 'POST', body: JSON.stringify(body) }),
  updatePrometheusConfiguration: (id: string, body: object): Promise<PrometheusConfiguration> => request(`/prometheus/configurations/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  testPrometheus: (id: string): Promise<{ message: string }> => request(`/prometheus/configurations/${id}/test`, { method: 'POST' }),
  scanPrometheus: (id: string): Promise<{ target_count: number }> => request(`/prometheus/configurations/${id}/scan`, { method: 'POST' }),
  inventory: (query: string): Promise<PaginatedInventory> => request(`/inventory?${query}`),
  inventoryDetail: (id: string): Promise<InventoryDetail> => request(`/inventory/${id}`),
  decideCorrelation: (observationId: string, assetId: string | null, status: string): Promise<void> =>
    request(`/inventory/observations/${observationId}/correlation`, { method: 'POST', body: JSON.stringify({ asset_id: assetId, status }) }),
  users: (): Promise<LocalUser[]> => request('/users'),
  createUser: (body: object): Promise<LocalUser> => request('/users', { method: 'POST', body: JSON.stringify(body) }),
  setUserState: (id: string, enabled: boolean): Promise<LocalUser> => request(`/users/${id}/state`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
  resetUserPassword: (id: string, password: string, confirmPassword: string): Promise<void> => request(`/users/${id}/reset-password`, { method: 'POST', body: JSON.stringify({ password, confirm_password: confirmPassword }) }),
  deleteUser: (id: string): Promise<void> => request(`/users/${id}`, { method: 'DELETE' }),
  settings: (): Promise<ProductSettings> => request('/settings'),
  updateSettings: (settings: object): Promise<ProductSettings> => request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  testSaas: (saasUrl: string): Promise<{ message: string }> => request('/settings/saas/test', { method: 'POST', body: JSON.stringify({ saas_url: saasUrl }) }),
  registerSaas: (body: { saas_url: string; registration_token: string; confirmed?: boolean }): Promise<ProductSettings> => request('/settings/saas/register', { method: 'POST', body: JSON.stringify(body) }),
  reregisterSaas: (body: { saas_url: string; registration_token: string; confirmed: boolean }): Promise<ProductSettings> => request('/settings/saas/reregister', { method: 'POST', body: JSON.stringify(body) }),
  unregisterSaas: (): Promise<ProductSettings> => request('/settings/saas/unregister', { method: 'POST', body: JSON.stringify({ confirmed: true }) }),
  retryHeartbeat: (): Promise<ProductSettings> => request('/settings/saas/retry', { method: 'POST' }),
};
