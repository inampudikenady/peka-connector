import { describe, expect, it } from 'vitest';

import { formatTimestamp, relativeTimestamp } from './time';

describe('formatTimestamp', () => {
  it('uses the configured display time zone', () => {
    const utc = formatTimestamp('2026-07-20T12:00:00Z', 'UTC');
    const kolkata = formatTimestamp('2026-07-20T12:00:00Z', 'Asia/Kolkata');
    expect(utc).not.toBe(kolkata);
  });

  it('returns the requested empty state', () => {
    expect(formatTimestamp(null, 'UTC', 'Not scheduled')).toBe('Not scheduled');
  });

  it('formats relative timestamps', () => {
    expect(relativeTimestamp('2026-07-20T11:59:42Z', Date.parse('2026-07-20T12:00:00Z'))).toBe('18 seconds ago');
  });
});
