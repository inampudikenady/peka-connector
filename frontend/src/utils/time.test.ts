import { describe, expect, it } from 'vitest';

import { formatTimestamp, parseTimestamp, relativeTimestamp, timestampDisplay } from './time';

const NOW = Date.parse('2026-07-21T06:14:00Z');

describe('timestamp utilities', () => {
  it('treats Z and +00:00 as the same instant without duplicate conversion', () => {
    expect(parseTimestamp('2026-07-21T06:11:00Z')?.getTime()).toBe(
      parseTimestamp('2026-07-21T06:11:00+00:00')?.getTime(),
    );
    expect(relativeTimestamp('2026-07-21T06:11:00+00:00', NOW)).toBe('3 minutes ago');
  });

  it('treats legacy offset-free backend values as UTC exactly once', () => {
    expect(parseTimestamp('2026-07-21T06:11:00')?.toISOString()).toBe(
      '2026-07-21T06:11:00.000Z',
    );
  });

  it('renders future timestamps as future values', () => {
    expect(relativeTimestamp('2026-07-21T06:16:00Z', NOW)).toBe('in 2 minutes');
  });

  it('uses the browser zone for absolute display without changing relative time', () => {
    const ahead = timestampDisplay('2026-07-21T06:11:00Z', NOW, 'Never', {
      locale: 'en-US', timeZone: 'Asia/Kolkata',
    });
    const behind = timestampDisplay('2026-07-21T06:11:00Z', NOW, 'Never', {
      locale: 'en-US', timeZone: 'America/Los_Angeles',
    });
    expect(ahead.relative).toBe('3 minutes ago');
    expect(behind.relative).toBe('3 minutes ago');
    expect(ahead.absolute).not.toBe(behind.absolute);
  });

  it('uses the platform time-zone database across daylight-saving transitions', () => {
    expect(formatTimestamp('2026-03-08T07:30:00Z', 'Never', {
      locale: 'en-US', timeZone: 'America/New_York',
    })).toContain('3:30 AM');
  });

  it('provides clear missing and invalid states', () => {
    expect(formatTimestamp(null, 'Not scheduled')).toBe('Not scheduled');
    expect(relativeTimestamp('not-a-timestamp', NOW)).toBe('Invalid timestamp');
  });
});
