import { Chip, Tooltip } from '@mui/material';

const descriptions: Record<string, string> = {
  connected: 'The connector is communicating successfully with PEKA. This does not mean source data has been uploaded or synchronized.',
  degraded: 'Heartbeats are succeeding, but one or more enabled local sources are unhealthy.',
  out_of_sync: 'The last successful heartbeat is older than one and a half expected intervals.',
  reconnecting: 'The connector is retrying after a temporary PEKA communication failure.',
  disconnected: 'No successful heartbeat has occurred for at least three expected intervals.',
  authentication_failed: 'PEKA rejected the connector heartbeat credentials.',
  unregistered: 'This appliance has no PEKA connector credentials.',
  registering: 'A PEKA registration request is in progress.',
  awaiting_first_heartbeat: 'Registration succeeded and the connector is waiting for its first accepted heartbeat.',
  retired: 'The connector was retired in PEKA.',
  unknown: 'The connector reported an unsupported legacy state.',
};

const colors: Record<string, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
  connected: 'success', degraded: 'warning', out_of_sync: 'warning', reconnecting: 'warning',
  disconnected: 'error', authentication_failed: 'error', unregistered: 'default',
  registering: 'info', awaiting_first_heartbeat: 'info', retired: 'default',
  unknown: 'default',
};

const connectionStatusLabel = (status: string) => status.split('_').map((part) => part[0]?.toUpperCase() + part.slice(1)).join(' ');

export function ConnectionStatusBadge({ status }: { status: string }) {
  const safeStatus = status === 'in_sync' ? 'unknown' : status;
  const label = connectionStatusLabel(safeStatus);
  return <Tooltip title={descriptions[safeStatus] ?? 'Connector connection state'}><Chip label={label} color={colors[safeStatus] ?? 'default'} size="small" /></Tooltip>;
}
