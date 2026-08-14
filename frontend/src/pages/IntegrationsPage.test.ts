import { describe, expect, it } from 'vitest';

import type {
  ConnectorIntegration, IntegrationCatalogItem, IntegrationStream,
} from '../api/types';
import pageSource from './IntegrationsPage.tsx?raw';
import { buildSourceCards, filterSourceCards } from './integrationSourceModels';

const catalog: IntegrationCatalogItem[] = [
  { integration_type: 'prometheus', name: 'Prometheus', category: 'Monitoring', provider_roles: ['monitoring'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'loki', name: 'Loki', category: 'Logs', provider_roles: ['logs'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'servicenow', name: 'ServiceNow', category: 'Ticketing / CMDB', provider_roles: ['ticketing', 'cmdb'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'zammad', name: 'Zammad', category: 'Ticketing', provider_roles: ['ticketing'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'generic_cmdb', name: 'Local CMDB', category: 'CMDB', provider_roles: ['cmdb'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'documents', name: 'Documents', category: 'Knowledge', provider_roles: ['knowledge'], capabilities: {}, available: true, configuration_fields: [] },
  { integration_type: 'solarwinds', name: 'SolarWinds', category: 'Monitoring', provider_roles: ['monitoring'], capabilities: {}, available: false, unavailable_reason: 'Not implemented.', configuration_fields: [] },
  { integration_type: 'vmware_vcenter', name: 'VMware vCenter', category: 'Virtualization', provider_roles: ['virtualization'], capabilities: {}, available: false, unavailable_reason: 'Not implemented.', configuration_fields: [] },
];

const integration = (id: string, integration_type: string): ConnectorIntegration => ({
  id, integration_type, display_name: integration_type, category: '', enabled: true,
  status: 'healthy', configuration: {}, capabilities: {}, last_tested_at: null,
  last_successful_test_at: null, last_successful_sync_at: null,
  initial_sync_status: 'completed', last_error: null,
  created_at: '2026-08-14T00:00:00Z', updated_at: '2026-08-14T00:00:00Z',
});

const source = (activation_id: string, integration_id: string, source_key: string, source_name: string, selected: boolean) => ({
  activation_id, integration_id, source_key, source_name, configured: true, selected,
  status: 'healthy', last_successful_sync_at: null, last_error: null,
});

const streams: IntegrationStream[] = [
  { stream: 'monitoring', display_name: 'Monitoring', selected_source: 'prometheus', sources: [source('p', 'prom', 'prometheus', 'Prometheus', true)] },
  { stream: 'logs', display_name: 'Logs', selected_source: 'loki', sources: [source('l', 'loki', 'loki', 'Loki', true)] },
  { stream: 'ticketing', display_name: 'Ticketing', selected_source: 'servicenow', sources: [source('z', 'zammad', 'zammad', 'Zammad', false), source('st', 'snow', 'servicenow', 'ServiceNow', true)] },
  { stream: 'cmdb', display_name: 'CMDB', selected_source: 'servicenow_cmdb', sources: [source('c', 'cmdb', 'local_cmdb', 'Local CMDB', false), source('sc', 'snow', 'servicenow_cmdb', 'ServiceNow CMDB', true)] },
  { stream: 'knowledge', display_name: 'Knowledge', selected_source: 'documents', sources: [source('d', 'docs', 'documents', 'Documents', true)] },
];

const items = [
  integration('prom', 'prometheus'), integration('loki', 'loki'),
  integration('snow', 'servicenow'), integration('zammad', 'zammad'),
  integration('cmdb', 'generic_cmdb'), integration('docs', 'documents'),
];

describe('grouped integration sources', () => {
  it('groups source capabilities once under their streams', () => {
    const cards = buildSourceCards(catalog, items, streams);
    expect(cards.map((card) => [card.section, card.name, card.state])).toEqual([
      ['Monitoring', 'Prometheus', 'Active'], ['Monitoring', 'SolarWinds', 'Coming soon'],
      ['Logs', 'Loki', 'Active'], ['Ticketing', 'ServiceNow', 'Active'],
      ['Ticketing', 'Zammad', 'Inactive'], ['CMDB', 'ServiceNow CMDB', 'Active'],
      ['CMDB', 'Local CMDB', 'Inactive'], ['Knowledge', 'Documents', 'Active'],
      ['Virtualization', 'VMware vCenter', 'Coming soon'],
    ]);
  });

  it('filters across source name, stream, and concise state', () => {
    const cards = buildSourceCards(catalog, items, streams);
    expect(filterSourceCards(cards, 'service', 'Ticketing', 'Active').map((card) => card.name)).toEqual(['ServiceNow']);
    expect(filterSourceCards(cards, '', 'CMDB', 'Inactive').map((card) => card.name)).toEqual(['Local CMDB']);
    expect(filterSourceCards(cards, 'solar', 'All', 'Coming soon').map((card) => card.name)).toEqual(['SolarWinds']);
    expect(filterSourceCards(cards, '', 'All', 'All').map((card) => card.name).slice(0, 2)).toEqual(['Prometheus', 'SolarWinds']);
  });

  it('keeps the catalog route internally while presenting Sources without summary cards', () => {
    expect(pageSource).toContain('<Tab value="catalog" label="Sources" />');
    expect(pageSource).not.toContain('function StreamOverview');
    expect(pageSource).toContain('Active source: {active.source_name}');
    expect(pageSource).toContain('xs: 12, md: 6');
    expect(pageSource).toContain("['All', 'Active', 'Inactive', 'Coming soon']");
    expect(pageSource).not.toContain("'Selected'");
    expect(pageSource).not.toContain("'Enabled'");
    expect(pageSource).toContain('SOURCE_SWITCH_CONFIRMATION_REQUIRED');
  });

  it('shows ServiceNow schedule and freshness details in Data & Sync', () => {
    expect(pageSource).toContain('Last attempted sync');
    expect(pageSource).toContain('item.availability.freshness_state');
    expect(pageSource).toContain('item.sync_interval_seconds / 60');
  });
});
