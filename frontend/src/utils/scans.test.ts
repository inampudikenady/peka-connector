import { describe, expect, it } from 'vitest';

import type { ScanRecord } from '../api/types';
import { enumLabel, scanDuration, scanRate } from './scans';

const scan: ScanRecord = {
  id: 'scan', source_id: 'source', status: 'completed', trigger: 'scheduled',
  started_at: '2026-07-20T12:00:00Z', completed_at: '2026-07-20T12:00:02Z',
  discovered_count: 10, added_count: 1, changed_count: 1, unchanged_count: 8,
  missing_count: 0, failed_count: 0, error: null, correlation_id: 'operation',
};

describe('scan presentation', () => {
  it('formats user-facing enums', () => {
    expect(enumLabel('scheduled')).toBe('Scheduled');
    expect(enumLabel('authentication_failed')).toBe('Authentication Failed');
  });

  it('calculates duration and average rate', () => {
    expect(scanDuration(scan)).toBe('2.0 s');
    expect(scanRate(scan)).toBe('5.0 files/s');
  });
});
