import type { ServiceNowCMDBObservability } from '../api/types';
import { relativeTimestamp } from '../utils/time';

export function serviceNowFreshnessMessage(
  data: ServiceNowCMDBObservability,
  now = Date.now(),
) {
  const relative = relativeTimestamp(data.last_successful_sync_at, now, 'never');
  if (data.freshness_state === 'error') {
    return data.last_successful_sync_at
      ? `Last synchronization failed — latest successful data is from ${relative}.`
      : 'Last synchronization failed — no successful CMDB synchronization is available.';
  }
  if (data.freshness_state === 'stale') {
    return data.last_successful_sync_at
      ? `Data is stale — last successful sync was ${relative}.`
      : 'Data is stale — no successful CMDB synchronization is available.';
  }
  return data.last_successful_sync_at
    ? `Data is fresh — synced ${relative}.`
    : 'Data freshness is unknown.';
}
