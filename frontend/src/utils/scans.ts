import type { ScanRecord } from '../api/types';

export const enumLabel = (value: string) => value.split('_').map((part) => part[0]?.toUpperCase() + part.slice(1)).join(' ');
export const scanDurationSeconds = (scan: ScanRecord) => scan.completed_at ? Math.max(0, (new Date(scan.completed_at).getTime() - new Date(scan.started_at).getTime()) / 1000) : null;
export const scanDuration = (scan: ScanRecord) => { const seconds = scanDurationSeconds(scan); return seconds === null ? 'In progress' : seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`; };
export const scanRate = (scan: ScanRecord) => { const seconds = scanDurationSeconds(scan); return seconds && seconds > 0 ? `${(scan.discovered_count / seconds).toFixed(1)} files/s` : 'Unavailable'; };
