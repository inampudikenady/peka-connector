import { Alert, Button, Card, CardContent, Grid, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useState, type ReactNode } from 'react';

import { api } from '../api/client';
import type { Overview } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ConnectionStatusBadge } from '../components/ConnectionStatusBadge';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { activityEventLabel, safeActivitySummary } from '../utils/activity';
import { timestampDisplay } from '../utils/time';

const bytes = (value: number | null) => value === null ? 'Unavailable' : `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;

function RelativeTime({ value, empty = 'Never' }: { value: string | null; empty?: string }) {
  const display = timestampDisplay(value, Date.now(), empty);
  return <span>{display.relative}{display.valid && <><br /><Typography component="span" variant="caption" color="text.secondary">{display.absolute}</Typography></>}</span>;
}

function Fact({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return <div><Typography variant="caption" color="text.secondary">{label}</Typography><Typography sx={{ overflowWrap: 'anywhere', fontFamily: mono ? 'monospace' : undefined }}>{children}</Typography></div>;
}

export function OverviewPage() {
  const { user } = useAuth(); const toast = useToast();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState(''); const [retrying, setRetrying] = useState(false);
  const load = () => api.overview().then(setData);
  useEffect(() => { void api.overview().then(setData).catch((e: Error) => setError(e.message)); }, []);
  const retry = async () => { setRetrying(true); try { await api.retryHeartbeat(); await load(); toast.show('Heartbeat attempt completed', 'success'); } catch (e) { toast.show(e instanceof Error ? e.message : 'Heartbeat retry failed', 'error'); } finally { setRetrying(false); } };
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <LoadingState label="Loading connector status" />;
  return <Stack spacing={3}>
    <div><Typography variant="h4" fontWeight={700}>Overview</Typography><Typography color="text.secondary">Current appliance operational state</Typography></div>
    <Grid container spacing={2}>{([
      ['Connector Name', data.connector_display_name], ['Connector Version', data.connector_version], ['Instance ID', data.instance_id],
    ] as Array<[string, string]>).map(([label, value]) => <Grid key={label} size={{ xs: 12, md: 4 }}><Card variant="outlined"><CardContent><Fact label={label} mono={label === 'Instance ID'}>{value}</Fact></CardContent></Card></Grid>)}</Grid>
    <Paper variant="outlined" sx={{ p: 3 }}><Stack spacing={2}><Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="h6">PEKA Registration</Typography><Stack direction="row" spacing={1} alignItems="center"><ConnectionStatusBadge status={data.saas_status} />{user?.role === 'administrator' && data.saas_status !== 'unregistered' && <Button size="small" disabled={retrying} onClick={() => void retry()}>Retry Now</Button>}</Stack></Stack><Alert severity="info">Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.</Alert><Grid container spacing={2}><Grid size={{ xs: 12, md: 6 }}><Fact label="PEKA URL">{data.saas_url ?? 'Not configured'}</Fact></Grid><Grid size={{ xs: 12, md: 6 }}><Fact label="Registered At"><RelativeTime value={data.registered_at} /></Fact></Grid><Grid size={{ xs: 12, md: 6 }}><Fact label="Tenant ID" mono>{data.tenant_id ?? 'Not assigned'}</Fact></Grid><Grid size={{ xs: 12, md: 6 }}><Fact label="Connector ID" mono>{data.connector_id ?? 'Not assigned'}</Fact></Grid></Grid></Stack></Paper>
    <Paper variant="outlined" sx={{ p: 3 }}><Typography variant="h6" gutterBottom>Heartbeat</Typography><Grid container spacing={2}><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Last Successful Heartbeat"><RelativeTime value={data.last_heartbeat_at} /></Fact></Grid><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Last Heartbeat Attempt"><RelativeTime value={data.last_heartbeat_attempt_at} /></Fact></Grid><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Next Heartbeat"><RelativeTime value={data.next_heartbeat_at} empty="Not scheduled" /></Fact></Grid><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Heartbeat Interval">{data.heartbeat_interval_seconds} seconds</Fact></Grid><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Consecutive Failures">{data.heartbeat_failure_count}</Fact></Grid><Grid size={{ xs: 12, sm: 6, lg: 4 }}><Fact label="Round-Trip Latency">{data.heartbeat_round_trip_ms === null ? 'Unavailable' : `${data.heartbeat_round_trip_ms.toFixed(1)} ms`}</Fact></Grid></Grid></Paper>
    <Paper variant="outlined" sx={{ p: 3 }}><Typography variant="h6" gutterBottom>Operations</Typography><Grid container spacing={2}><Grid size={{ xs: 12, md: 4 }}><Fact label="Document source">{data.document_source_health.charAt(0).toUpperCase() + data.document_source_health.slice(1)}</Fact></Grid><Grid size={{ xs: 12, md: 4 }}><Fact label="Local Storage">{bytes(data.storage_free_bytes)} free of {bytes(data.storage_total_bytes)}</Fact></Grid><Grid size={{ xs: 12, md: 4 }}><Fact label="Scheduler">{data.scheduler_running ? `Running${data.heartbeat_job_scheduled ? ', heartbeat scheduled' : ''}` : 'Stopped'}</Fact></Grid><Grid size={{ xs: 12, md: 4 }}><Fact label="Last document scan"><RelativeTime value={data.document_source_last_scan_at} /></Fact></Grid><Grid size={{ xs: 12, md: 4 }}><Fact label="Next document scan"><RelativeTime value={data.document_source_next_scan_at} empty="Not scheduled" /></Fact></Grid></Grid></Paper>
    <Paper variant="outlined" sx={{ p: 3 }}><Typography variant="h6" gutterBottom>Document Delivery</Typography><Grid container spacing={2}><Grid size={{ xs: 6, md: 2 }}><Fact label="Total">{data.document_total}</Fact></Grid><Grid size={{ xs: 6, md: 2 }}><Fact label="Queued">{data.document_queued}</Fact></Grid><Grid size={{ xs: 6, md: 2 }}><Fact label="Uploading">{data.document_uploading}</Fact></Grid><Grid size={{ xs: 6, md: 2 }}><Fact label="Uploaded">{data.document_uploaded}</Fact></Grid><Grid size={{ xs: 6, md: 2 }}><Fact label="Failed">{data.document_failed}</Fact></Grid><Grid size={{ xs: 6, md: 2 }}><Fact label="Unsupported">{data.document_unsupported}</Fact></Grid><Grid size={{ xs: 12, md: 6 }}><Fact label="Last successful delivery"><RelativeTime value={data.last_document_delivery_at} /></Fact></Grid><Grid size={{ xs: 12, md: 6 }}><Fact label="PEKA document endpoint">{data.document_endpoint_status}</Fact></Grid></Grid></Paper>
    {data.unhealthy_source_count > 0 && <Alert severity="warning">{data.unhealthy_source_count} enabled source(s) require attention.</Alert>}
    <div><Typography variant="h6" gutterBottom>Recent Events</Typography>{data.recent_events.length === 0 ? <Alert severity="info">No connector events have been recorded.</Alert> : <Stack spacing={1}>{data.recent_events.map((event) => <Card variant="outlined" key={event.id}><CardContent><Typography variant="overline" color="text.secondary">{activityEventLabel(event.event_type)}</Typography><Typography>{safeActivitySummary(event.message)}</Typography><Typography variant="caption" color="text.secondary"><RelativeTime value={event.created_at} /></Typography></CardContent></Card>)}</Stack>}</div>
  </Stack>;
}
