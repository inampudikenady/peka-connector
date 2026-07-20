export function formatTimestamp(value: string | null, timeZone = 'UTC', empty = 'Never'): string {
  if (!value) return empty;
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium', timeStyle: 'medium', timeZone,
    }).format(new Date(value));
  } catch {
    return new Date(value).toLocaleString();
  }
}

export function relativeTimestamp(value: string | null, now = Date.now(), empty = 'Never'): string {
  if (!value) return empty;
  const seconds = Math.round((new Date(value).getTime() - now) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, 'second');
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour');
  return formatter.format(Math.round(hours / 24), 'day');
}
