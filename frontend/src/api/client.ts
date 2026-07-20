import type {
  ActivityEvent, CurrentUser, Diagnostics, LocalUser, LoginResponse, Overview,
  PaginatedLogs, ProductSettings, ScanRecord, SetupStatus, Source, SourceInput,
} from './types';

let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

function csrfToken(): string | null {
  const item = document.cookie.split('; ').find((cookie) => cookie.startsWith('peka_csrf='));
  return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : null;
}

async function parseError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  let message = 'Request failed';
  if (typeof body.detail === 'string') message = body.detail;
  if (Array.isArray(body.detail)) {
    message = body.detail.map((item) => (item as { msg?: string }).msg ?? 'Invalid value').join('. ');
  }
  return new ApiError(message, response.status);
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
  if (response.status === 401 && retry && await refreshAccessToken()) return request(path, init, false);
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
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
  activity: (): Promise<ActivityEvent[]> => request('/activity'),
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
  scanHistory: (id: string): Promise<ScanRecord[]> => request(`/sources/${id}/scans`),
  users: (): Promise<LocalUser[]> => request('/users'),
  createUser: (body: object): Promise<LocalUser> => request('/users', { method: 'POST', body: JSON.stringify(body) }),
  setUserState: (id: string, enabled: boolean): Promise<LocalUser> => request(`/users/${id}/state`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
  resetUserPassword: (id: string, password: string, confirmPassword: string): Promise<void> => request(`/users/${id}/reset-password`, { method: 'POST', body: JSON.stringify({ password, confirm_password: confirmPassword }) }),
  deleteUser: (id: string): Promise<void> => request(`/users/${id}`, { method: 'DELETE' }),
  settings: (): Promise<ProductSettings> => request('/settings'),
  updateSettings: (settings: object): Promise<ProductSettings> => request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
};
