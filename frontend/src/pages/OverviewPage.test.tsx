import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { KnowledgeStoreOverview } from '../api/types';
import { KnowledgeStoreCard } from './OverviewPage';

function store(overrides: Partial<KnowledgeStoreOverview> = {}): KnowledgeStoreOverview {
  return {
    status: 'healthy', engine: 'qdrant', engine_version: 'runtime-1.14.1',
    collection: 'peka_documents', documents: 1, chunks: 2, pending: 0, failed: 0,
    last_indexed_at: null, last_search_at: null,
    checks: {
      qdrant_reachable: true, collection_exists: true, collection_accessible: true,
      statistics_readable: true, search_service_operational: true,
    },
    ...overrides,
  };
}

describe('Local Knowledge Store overview card', () => {
  it('shows runtime component and authoritative indexing statistics', () => {
    const html = renderToStaticMarkup(<KnowledgeStoreCard store={store()} />);
    expect(html).toContain('Local Knowledge Store');
    expect(html).toContain('Qdrant runtime-1.14.1');
    expect(html).toContain('peka_documents');
    expect(html).toContain('Documents');
    expect(html).toContain('Chunks');
    expect(html).toContain('Last indexed');
    expect(html).toContain('Last search');
    expect(html).not.toContain('Last indexed:');
    expect(html).not.toContain('Last search:');
    expect(html.match(/>Never</g)).toHaveLength(2);
  });

  it('renders unavailable runtime details safely', () => {
    const html = renderToStaticMarkup(
      <KnowledgeStoreCard store={store({ status: 'unavailable', engine_version: null })} />,
    );
    expect(html).toContain('Unavailable');
    expect(html).toContain('Qdrant Unknown');
  });
});
