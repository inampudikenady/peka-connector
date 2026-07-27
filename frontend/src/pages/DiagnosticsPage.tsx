import DownloadIcon from '@mui/icons-material/Download';
import { Alert, Button, Chip, Grid, List, ListItem, ListItemText, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { Diagnostics } from '../api/types';
import { ConnectionStatusBadge } from '../components/ConnectionStatusBadge';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

export function DiagnosticsPage() {
  const toast = useToast(); const [data, setData] = useState<Diagnostics | null>(null); const [error, setError] = useState('');
  useEffect(() => { void api.diagnostics().then(setData).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <LoadingState label="Running diagnostics" />;
  const facts = [
    ['Instance ID', data.instance_id], ['Registration State', data.registration_state], ['PEKA Hostname', data.saas_hostname ?? 'Not configured'],
    ['Last Heartbeat Attempt', formatTimestamp(data.last_heartbeat_attempt_at)], ['Last Successful Heartbeat', formatTimestamp(data.last_successful_heartbeat_at)],
    ['Next Heartbeat', formatTimestamp(data.next_heartbeat_at, 'Not scheduled')], ['Heartbeat Interval', `${data.heartbeat_interval_seconds} seconds`],
    ['Consecutive Failures', String(data.consecutive_failures)], ['Round-Trip Latency', data.heartbeat_round_trip_ms === null ? 'Unavailable' : `${data.heartbeat_round_trip_ms.toFixed(1)} ms`],
    ['Scheduler', data.scheduler_running ? 'Running' : 'Stopped'], ['Heartbeat Job', data.heartbeat_job_scheduled ? 'Scheduled' : 'Not scheduled'], ['Source Jobs', String(data.source_scheduler_job_count)],
  ];
  return <Stack spacing={3}><Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between"><div><Typography variant="h4" fontWeight={700}>Diagnostics</Typography><Typography color="text.secondary">Runtime and appliance health checks</Typography></div><Button startIcon={<DownloadIcon />} variant="outlined" onClick={() => void api.downloadDiagnostics().catch((e: Error) => toast.show(e.message, 'error'))}>Download diagnostics bundle</Button></Stack>
    <Paper variant="outlined" sx={{ p: 3 }}><Stack direction="row" spacing={2} alignItems="center"><Typography variant="h6">Connector Connection</Typography><ConnectionStatusBadge status={data.connection_state} /></Stack><Grid container spacing={2} sx={{ mt: 1 }}>{facts.map(([label, value]) => <Grid key={label} size={{ xs: 12, sm: 6, lg: 4 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography sx={{ overflowWrap: 'anywhere' }}>{value}</Typography></Grid>)}</Grid></Paper>
    <Paper variant="outlined"><List>{data.checks.map((check) => <ListItem key={check.name} divider><ListItemText primary={check.name} secondary={check.detail} /><Chip label={check.status} color={check.status === 'healthy' ? 'success' : check.status === 'unhealthy' ? 'error' : 'default'} /></ListItem>)}</List></Paper>
    <Paper variant="outlined" sx={{ p: 2 }}><Typography>Version: {data.version} ({data.build})</Typography><Typography>Python: {data.python_version}</Typography><Typography>Platform: {data.platform}</Typography><Typography>Migration: {data.migration_revision ?? 'Unavailable'}</Typography></Paper>
  </Stack>;
}
