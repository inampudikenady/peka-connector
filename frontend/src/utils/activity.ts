import type { ActivityEvent } from '../api/types';
import { customerFacingText } from './displayText';
import { timestampDisplay, type TimestampFormatOptions } from './time';

export function activityEventLabel(eventType: string): string {
  return eventType
    .replaceAll('.', ' ')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function safeActivitySummary(message: string): string {
  return customerFacingText(message);
}

export function activityTimestamp(
  value: string,
  now = Date.now(),
  options: TimestampFormatOptions = {},
) {
  return timestampDisplay(value, now, 'Unknown time', options);
}

export const activityOutcomeLabel = (outcome: ActivityEvent['outcome']) => (
  outcome === 'information' ? 'Information' : outcome.charAt(0).toUpperCase() + outcome.slice(1)
);
