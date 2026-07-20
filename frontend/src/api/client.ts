import type { DocumentMetadata, LoginResponse, Source, SourceInput } from './types';

const TOKEN_KEY = 'peka_access_token';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const detail = typeof body.detail === 'string' ? body.detail : 'Request failed';
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  isAuthenticated: (): boolean => Boolean(sessionStorage.getItem(TOKEN_KEY)),
  logout: (): void => sessionStorage.removeItem(TOKEN_KEY),
  async login(username: string, password: string): Promise<void> {
    const result = await request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    sessionStorage.setItem(TOKEN_KEY, result.access_token);
  },
  listSources: (): Promise<Source[]> => request('/sources'),
  createSource: (source: SourceInput): Promise<Source> =>
    request('/sources', { method: 'POST', body: JSON.stringify(source) }),
  deleteSource: (id: string): Promise<void> => request(`/sources/${id}`, { method: 'DELETE' }),
  scanSource: (id: string): Promise<{ discovered_count: number }> =>
    request(`/sources/${id}/scan`, { method: 'POST' }),
  listDocuments: (id: string): Promise<DocumentMetadata[]> => request(`/sources/${id}/documents`),
};

