import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ConnectionStatusBadge } from './ConnectionStatusBadge';

describe('ConnectionStatusBadge', () => {
  it.each([
    ['connected', 'Connected'],
    ['awaiting_first_heartbeat', 'Awaiting First Heartbeat'],
    ['authentication_failed', 'Authentication Failed'],
  ])('renders %s with a text label', (status, label) => {
    expect(renderToStaticMarkup(<ConnectionStatusBadge status={status} />)).toContain(label);
  });

  it('never displays the legacy In Sync state', () => {
    const output = renderToStaticMarkup(<ConnectionStatusBadge status="in_sync" />);
    expect(output).toContain('Unknown');
    expect(output).not.toContain('In Sync');
  });
});
