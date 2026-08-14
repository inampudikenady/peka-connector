import type {
  ConnectorIntegration, IntegrationCatalogItem, IntegrationStream, IntegrationStreamSource,
} from '../api/types';

export const streamOrder = [
  'Monitoring', 'Logs', 'Ticketing', 'CMDB', 'Knowledge', 'Virtualization',
];

export const sourceDescriptions: Record<string, string> = {
  prometheus: 'Targets, metrics and infrastructure health',
  loki: 'Live operational log evidence',
  zammad: 'Tickets and asset relationships',
  servicenow: 'Incidents, problems and changes',
  servicenow_cmdb: 'Configuration items and relationships',
  solarwinds: 'Nodes, alerts and performance',
  vmware_vcenter: 'Virtual infrastructure and datastore capacity',
  generic_cmdb: 'Imported asset inventory',
  documents: 'Knowledge files and delivery',
};

const sourceKeys: Record<string, string> = { generic_cmdb: 'local_cmdb' };

export interface SourceCardModel {
  key: string;
  section: string;
  name: string;
  description: string;
  state: 'Active' | 'Inactive' | 'Coming soon';
  priority: 0 | 1 | 2 | 3;
  catalog: IntegrationCatalogItem;
  integration?: ConnectorIntegration;
  stream?: IntegrationStream;
  source?: IntegrationStreamSource;
}

export function buildSourceCards(
  catalog: IntegrationCatalogItem[],
  items: ConnectorIntegration[],
  streams: IntegrationStream[],
): SourceCardModel[] {
  const cards = catalog.flatMap((entry) => {
    const integration = items.find((item) => item.integration_type === entry.integration_type);
    const capabilityRows = integration
      ? streams.flatMap((stream) => stream.sources
        .filter((source) => source.integration_id === integration.id)
        .map((source) => ({ stream, source })))
      : [];
    const definitions = entry.integration_type === 'servicenow'
      ? [
        { section: 'Ticketing', sourceKey: 'servicenow', name: 'ServiceNow' },
        { section: 'CMDB', sourceKey: 'servicenow_cmdb', name: 'ServiceNow CMDB' },
      ]
      : [{
        section: entry.category,
        sourceKey: sourceKeys[entry.integration_type] ?? entry.integration_type,
        name: entry.name,
      }];
    return definitions.map(({ section, sourceKey, name }) => {
      const capability = capabilityRows.find(({ source }) => source.source_key === sourceKey);
      const state = !entry.available ? 'Coming soon'
        : capability?.source.selected ? 'Active' : 'Inactive';
      const priority = !entry.available ? 3
        : capability?.source.selected ? 0
          : integration ? 1 : 2;
      return {
        key: `${entry.integration_type}:${sourceKey}`,
        section,
        name,
        description: sourceDescriptions[sourceKey]
          ?? sourceDescriptions[entry.integration_type] ?? '',
        state,
        priority,
        catalog: entry,
        integration,
        stream: capability?.stream,
        source: capability?.source,
      } satisfies SourceCardModel;
    });
  });
  return cards.sort((left, right) => {
    const sectionDifference = streamOrder.indexOf(left.section) - streamOrder.indexOf(right.section);
    return sectionDifference || left.priority - right.priority || left.name.localeCompare(right.name);
  });
}

export function filterSourceCards(
  cards: SourceCardModel[], search: string, stream: string, status: string,
) {
  const query = search.trim().toLowerCase();
  return cards.filter((card) => (
    (stream === 'All' || card.section === stream)
    && (status === 'All' || card.state === status)
    && (!query || `${card.name} ${card.description} ${card.section}`.toLowerCase().includes(query))
  ));
}
