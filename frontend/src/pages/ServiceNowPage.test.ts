import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import appSource from '../App.tsx?raw';
import integrationsSource from './IntegrationsPage.tsx?raw';
import serviceNowSource from './ServiceNowPage.tsx?raw';

afterEach(() => { vi.unstubAllGlobals(); });

describe('ServiceNow connector UI', () => {
  it('exposes independent configuration, status, and synchronization controls', () => {
    expect(appSource).toContain('path="/servicenow"');
    expect(integrationsSource).toContain("servicenow: '/servicenow'");
    for (const label of [
      'Instance URL', 'Username', 'Password', 'Verify TLS certificate',
      'Synchronization interval (seconds)', 'Test connection',
      'Run synchronization now', 'Disable integration',
    ]) expect(serviceNowSource).toContain(label);
    expect(serviceNowSource).toContain("password: ''");
    expect(serviceNowSource).toContain('item.counts');
    expect(serviceNowSource).not.toContain('dev425377');
  });

  it('uses separate ServiceNow API routes and never serializes a stored password', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.serviceNowConfigurations();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/servicenow/configurations', expect.any(Object));
  });
});
