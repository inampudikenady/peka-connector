export interface TimestampFormatOptions {
  locale?: string;
  /** Tests may supply a zone; production callers always use the browser default. */
  timeZone?: string;
}

export interface TimestampDisplay {
  relative: string;
  absolute: string;
  valid: boolean;
}

const OFFSET_SUFFIX = /(?:[zZ]|[+-]\d{2}:\d{2})$/;

export function parseTimestamp(value: string | null): Date | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Support legacy SQLite/API values as UTC without modifying values that
  // already carry Z or an explicit offset.
  const normalized = OFFSET_SUFFIX.test(trimmed) ? trimmed : `${trimmed}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function absoluteFromDate(date: Date, options: TimestampFormatOptions): string {
  return new Intl.DateTimeFormat(options.locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: options.timeZone,
  }).format(date);
}

function relativeFromDate(date: Date, now: number, locale?: string): string {
  const seconds = Math.round((date.getTime() - now) / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'always' });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, 'second');
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour');
  return formatter.format(Math.round(hours / 24), 'day');
}

export function timestampDisplay(
  value: string | null,
  now = Date.now(),
  empty = 'Never',
  options: TimestampFormatOptions = {},
): TimestampDisplay {
  if (!value) return { relative: empty, absolute: empty, valid: false };
  const date = parseTimestamp(value);
  if (!date) {
    return { relative: 'Invalid timestamp', absolute: 'Invalid timestamp', valid: false };
  }
  return {
    relative: relativeFromDate(date, now, options.locale),
    absolute: absoluteFromDate(date, options),
    valid: true,
  };
}

export function formatTimestamp(
  value: string | null,
  empty = 'Never',
  options: TimestampFormatOptions = {},
): string {
  if (!value) return empty;
  const date = parseTimestamp(value);
  return date ? absoluteFromDate(date, options) : 'Invalid timestamp';
}

export function relativeTimestamp(
  value: string | null,
  now = Date.now(),
  empty = 'Never',
): string {
  if (!value) return empty;
  const date = parseTimestamp(value);
  return date ? relativeFromDate(date, now) : 'Invalid timestamp';
}
