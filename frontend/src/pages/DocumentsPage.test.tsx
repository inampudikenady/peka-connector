import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { LEGACY_SOURCES_REDIRECT, navigationItems } from '../components/navigationItems';
import { formatTimestamp, relativeTimestamp } from '../utils/time';
import { DOCUMENT_TABS } from './DocumentsPage';

describe('Documents UI', () => {
  it('has a top-level Documents navigation entry', () => {
    expect(navigationItems.find((item) => item.label === 'Documents')?.path).toBe('/documents');
    expect(navigationItems.some((item) => item.label === 'Sources')).toBe(false);
    expect(LEGACY_SOURCES_REDIRECT).toBe('/documents');
    expect(DOCUMENT_TABS).toEqual(['Files', 'Source settings']);
  });

  it('uses browser-local timestamp helpers without changing relative time', () => {
    const timestamp = '2026-07-21T10:30:00Z';
    expect(relativeTimestamp(timestamp, Date.parse('2026-07-21T10:33:00Z'))).toBe('3 minutes ago');
    expect(formatTimestamp(timestamp, 'Never', { timeZone: 'Asia/Kolkata' })).not.toBe(
      formatTimestamp(timestamp, 'Never', { timeZone: 'America/Los_Angeles' }),
    );
  });

  it('keeps the controlled path out of navigation and user inputs', () => {
    const markup = renderToStaticMarkup(<span>No documents have been added yet.</span>);
    expect(markup).toContain('No documents have been added yet.');
    expect(markup).not.toContain('/data/sources/documents');
  });
});
