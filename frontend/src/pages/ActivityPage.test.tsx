import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import type { PaginatedActivity } from '../api/types';
import { navigationItems } from '../components/navigationItems';
import { activityTimestamp, safeActivitySummary } from '../utils/activity';
import { ActivityContent } from './ActivityPage';

const empty: PaginatedActivity = { items: [], total: 0, page: 1, page_size: 25 };

describe('Activity page', () => {
  it('renders the required empty state', () => {
    const html = renderToStaticMarkup(
      <ActivityContent data={empty} error={false} loading={false} onRetry={vi.fn()} onPageChange={vi.fn()} />,
    );
    expect(html).toContain('No activity has been recorded yet.');
  });

  it('renders a retry action after loading fails', () => {
    const html = renderToStaticMarkup(
      <ActivityContent data={null} error loading={false} onRetry={vi.fn()} onPageChange={vi.fn()} />,
    );
    expect(html).toContain('Activity could not be loaded.');
    expect(html).toContain('Retry');
  });

  it('renders human events and never renders sensitive values', () => {
    const data: PaginatedActivity = {
      items: [{
        id: 'event-1', event_type: 'connector.registration_succeeded', actor_username: 'admin',
        target_type: 'connector', target_id: 'connector-1',
        message: 'Registration token: raw-secret-token was accepted',
        created_at: '2026-07-21T06:11:00Z', outcome: 'success',
      }],
      total: 1, page: 1, page_size: 25,
    };
    const html = renderToStaticMarkup(
      <ActivityContent data={data} error={false} loading={false} onRetry={vi.fn()} onPageChange={vi.fn()} />,
    );
    expect(html).toContain('Connector Registration Succeeded');
    expect(html).toContain('Success');
    expect(html).not.toContain('raw-secret-token');
    expect(safeActivitySummary(data.items[0]!.message)).toContain('[REDACTED]');
  });

  it('formats Activity timestamps in the browser-local zone', () => {
    const india = activityTimestamp('2026-07-21T06:11:00Z', Date.parse('2026-07-21T06:14:00Z'), {
      locale: 'en-US', timeZone: 'Asia/Kolkata',
    });
    const california = activityTimestamp('2026-07-21T06:11:00Z', Date.parse('2026-07-21T06:14:00Z'), {
      locale: 'en-US', timeZone: 'America/Los_Angeles',
    });
    expect(india.relative).toBe('3 minutes ago');
    expect(california.relative).toBe('3 minutes ago');
    expect(india.absolute).not.toBe(california.absolute);
  });

  it('consolidates requests and logs under Activity navigation', () => {
    expect(navigationItems.find((item) => item.label === 'Activity')?.path).toBe('/activity');
    expect(navigationItems.some((item) => item.label === 'Operational Requests')).toBe(false);
    expect(navigationItems.some((item) => item.label === 'Logs')).toBe(false);
  });
});
