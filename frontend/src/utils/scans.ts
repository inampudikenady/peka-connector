import type { ScanRecord } from '../api/types';
import { parseTimestamp } from './time';

export const enumLabel = (value: string) => value.split('_').map((part) => part[0]?.toUpperCase() + part.slice(1)).join(' ');
export const scanDurationSeconds = (scan: ScanRecord) => {
  const started = parseTimestamp(scan.started_at);
  const completed = parseTimestamp(scan.completed_at);
  return started && completed ? Math.max(0, (completed.getTime() - started.getTime()) / 1000) : null;
};
export const scanDuration = (scan: ScanRecord) => { const seconds = scanDurationSeconds(scan); return seconds === null ? 'In progress' : seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`; };
export const scanRate = (scan: ScanRecord) => { const seconds = scanDurationSeconds(scan); return seconds && seconds > 0 ? `${(scan.discovered_count / seconds).toFixed(1)} files/s` : 'Unavailable'; };
