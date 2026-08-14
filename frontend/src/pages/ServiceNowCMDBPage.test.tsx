import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import type { ServiceNowCMDBObservability } from '../api/types';
import appSource from '../App.tsx?raw';
import pageSource from './ServiceNowCMDBPage.tsx?raw';
import { ServiceNowCMDBContent } from './ServiceNowCMDBPage';
import { serviceNowFreshnessMessage } from './serviceNowFreshness';

const data: ServiceNowCMDBObservability = {
  source: 'ServiceNow CMDB', active: true, connection_state: 'connected', sync_state: 'connected',
  last_successful_sync_at: '2026-08-14T10:00:00Z', last_attempted_sync_at: '2026-08-14T10:00:00Z',
  stale: false, cache_timestamp: '2026-08-14T10:00:00Z', total_cis: 1, server_cis: 1,
  freshness_state: 'fresh', freshness_threshold_seconds: 1800,
  other_cis: 0, relationship_count: 17, last_error: null, total: 1, page: 1, page_size: 25,
  items: [{
    id: 'ci-1', ci_name: 'util001', ci_class: 'cmdb_ci_linux_server',
    fqdn: 'util001.example.test', ip_address: '10.0.0.12',
    operating_system: 'Red Hat Enterprise Linux', environment: 'Production',
    application: 'Payments', business_owner: 'Pat Owner', support_group: 'Linux Support',
    lifecycle_state: 'Installed', updated_at: '2026-08-14T09:00:00Z',
    source: 'ServiceNow CMDB',
  }],
};

afterEach(() => vi.unstubAllGlobals());

describe('ServiceNow CMDB records', () => {
  it('has a dedicated route and calls the configuration-scoped API', async () => {
    expect(appSource).toContain('path="/servicenow/:configurationId/cmdb"');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(data), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await api.serviceNowCMDB('configuration-1');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/servicenow/configurations/configuration-1/cmdb?page=1&page_size=25',
      expect.any(Object),
    );
  });

  it('renders normalized records and relationship visibility', () => {
    const markup = renderToStaticMarkup(<ServiceNowCMDBContent data={data} />);
    expect(markup).toContain('util001.example.test');
    expect(markup).toContain('Red Hat Enterprise Linux');
    expect(markup).toContain('17 relationships');
    expect(markup).toContain('Data is fresh');
    expect(markup).not.toContain('Data is stale');
    expect(markup).not.toContain('Other classes');
    expect(markup).toContain('ServiceNow CMDB');
  });

  it('renders a dynamic stale duration without source-selection status', () => {
    const stale = { ...data, stale: true, freshness_state: 'stale' as const };
    expect(serviceNowFreshnessMessage(stale, Date.parse('2026-08-14T16:00:00Z')))
      .toBe('Data is stale — last successful sync was 6 hours ago.');
    const markup = renderToStaticMarkup(<ServiceNowCMDBContent data={stale} />);
    expect(markup).toContain('Data is stale');
    expect(markup).not.toContain('Active source');
  });

  it('distinguishes a failed latest attempt from the older successful cache', () => {
    const failed = { ...data, freshness_state: 'error' as const, last_error: 'Request timed out.' };
    expect(serviceNowFreshnessMessage(failed, Date.parse('2026-08-14T12:00:00Z')))
      .toBe('Last synchronization failed — latest successful data is from 2 hours ago.');
    const markup = renderToStaticMarkup(<ServiceNowCMDBContent data={failed} />);
    expect(markup).toContain('Last synchronization failed');
    expect(markup).toContain('Request timed out.');
  });

  it('renders the empty state and includes a recoverable API error state', () => {
    const markup = renderToStaticMarkup(
      <ServiceNowCMDBContent data={{ ...data, items: [], total: 0, total_cis: 0 }} />,
    );
    expect(markup).toContain('No ServiceNow CMDB records have been synchronized.');
    expect(pageSource).toContain('severity="error"');
    expect(pageSource).toContain('Retry');
  });
});
