import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import { navigationItems } from '../components/navigationItems';
import { pekaTokens } from '../pekaTokens';

import activitySource from './ActivityPage.tsx?raw';
import appSource from '../App.tsx?raw';
import headerSource from '../components/AppShell.tsx?raw';
import integrationsSource from './IntegrationsPage.tsx?raw';
import overviewSource from './OverviewPage.tsx?raw';
import settingsSource from './SettingsPage.tsx?raw';
import usersSource from './UsersPage.tsx?raw';

afterEach(() => { vi.unstubAllGlobals(); });

describe('consolidated connector administration UI', () => {
  it('keeps the concise primary navigation plus local document management', () => {
    expect(navigationItems.map((item) => [item.label, item.path])).toEqual([
      ['Overview', '/overview'], ['Integrations', '/integrations'],
      ['Documents', '/documents'],
      ['Activity', '/activity'], ['Users', '/users'], ['Settings', '/settings'],
    ]);
  });

  it('defines integration and activity tabs and redirects bookmarked routes', () => {
    for (const label of ['Catalog', 'Configured', 'Data & Sync']) expect(integrationsSource).toContain(`label="${label}"`);
    for (const label of ['Overview', 'Requests', 'Events', 'Logs']) expect(activitySource).toContain(`label="${label}"`);
    expect(appSource).toContain('/integrations?tab=data-sync');
    expect(appSource).toContain('/activity?tab=requests');
    expect(appSource).toContain('/activity?tab=logs');
  });

  it('restores administrator-only local user management without old navigation items', () => {
    expect(appSource).toContain('path="/users"');
    expect(appSource).toContain("user.role === 'administrator' ? <UsersPage />");
    expect(usersSource).toContain('Local connector access');
    for (const column of ['Username', 'Role', 'Status', 'Last login', 'Actions']) expect(usersSource).toContain(column);
    for (const action of ['Reset password', "user.is_active ? 'Disable' : 'Enable'", 'Delete']) expect(usersSource).toContain(action);
    expect(usersSource).toContain('You cannot disable your own account.');
    expect(usersSource).toContain('You cannot delete your own account.');
    expect(usersSource).toContain('last enabled administrator');
    expect(usersSource).toContain('variant="outlined"');
    expect(appSource).toContain('pekaTheme');
    for (const removed of ['Prometheus', 'Loki', 'Zammad', 'CMDB', 'Diagnostics', 'Logs']) {
      expect(navigationItems.some((item) => item.label === removed)).toBe(false);
    }
  });

  it('keeps the single heartbeat control on Overview and shares its status with the header', () => {
    expect(overviewSource).toContain('Connector connectivity');
    expect(overviewSource.match(/Retry heartbeat/g)).toHaveLength(1);
    expect(headerSource).toContain('useConnectorStatus');
    expect(headerSource).not.toContain('Retry heartbeat');
    expect(headerSource).not.toContain('RefreshIcon');
    expect(settingsSource).not.toContain('retryHeartbeat');
    expect(settingsSource).not.toContain('Retry Now');
    expect(headerSource).toContain('aria-label="Open user menu"');
    expect(headerSource).toContain('<Tooltip title="User menu"');
  });

  it('refreshes authoritative status whenever the Overview route is entered', () => {
    expect(overviewSource).toContain('refreshing, retrying, refresh, retryHeartbeat');
    expect(overviewSource).toContain('useEffect(() => { void refresh(); }, [refresh])');
  });

  it('uses the guarded shared refresh for the Knowledge Store card', () => {
    expect(overviewSource).toContain('aria-label="Refresh knowledge store"');
    expect(overviewSource).toContain('disabled={refreshing}');
    expect(overviewSource).toContain("user?.role === 'administrator' ? () => void refresh()");
  });

  it('prevents unsupported adapter enablement and preserves catalog controls', () => {
    expect(integrationsSource).toContain('Adapter unavailable');
    expect(integrationsSource).toContain('<Button size="small" disabled>Coming soon</Button>');
    expect(integrationsSource).toContain("configured.enabled ? 'Enabled' : 'Disabled'");
    expect(integrationsSource).toContain('Search integrations');
    expect(integrationsSource).toContain('Category');
    expect(integrationsSource).not.toContain('Make active');
    expect(integrationsSource).not.toContain('Switch active');
    expect(integrationsSource).not.toContain('active_provider_role');
  });

  it('defines and consumes the shared semantic PEKA token contract', () => {
    expect(Object.keys(pekaTokens)).toEqual(expect.arrayContaining([
      'bgApp', 'bgSurface', 'bgSidebar', 'primary', 'textPrimary', 'borderDefault',
      'success', 'warning', 'danger', 'focusRing',
    ]));
    expect(headerSource).toContain('var(--peka-bg-sidebar)');
    expect(appSource).toContain('pekaTheme');
  });

  it('uses the real heartbeat retry endpoint with POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      connector_display_name: 'Connector', environment_label: 'Lab', log_level: 'INFO',
      saas_status: 'connected', connector_id: 'connector-id', tenant_id: 'tenant-id',
      saas_url: 'https://peka.example.test', last_heartbeat_at: '2026-08-04T00:00:00Z',
      instance_id: 'instance-id', registered_at: '2026-08-01T00:00:00Z',
      heartbeat_interval_seconds: 300, last_heartbeat_attempt_at: '2026-08-04T00:00:00Z',
      next_heartbeat_at: null, last_heartbeat_status: 'success', last_heartbeat_error: null,
      heartbeat_failure_count: 0, last_heartbeat_failed_at: null,
      heartbeat_round_trip_ms: 12, last_saas_server_time: '2026-08-04T00:00:00Z',
      metadata_sync_warning: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.retryHeartbeat();

    expect(result.saas_status).toBe('connected');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/settings/saas/retry', expect.objectContaining({ method: 'POST' }));
  });
});
