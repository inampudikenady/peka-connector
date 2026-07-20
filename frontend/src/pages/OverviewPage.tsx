import { Alert, Card, CardContent, Chip, Grid, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { Overview } from '../api/types';
import { LoadingState } from '../components/LoadingState';

const bytes = (value: number | null) => value === null ? 'Unavailable' : `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null); const [error, setError] = useState('');
  useEffect(() => { void api.overview().then(setData).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <Alert severity="error">{error}</Alert>; if (!data) return <LoadingState label="Loading connector status" />;
  const cards = [
    ['Connector status', data.connector_status], ['SaaS registration', data.saas_status.replaceAll('_', ' ')],
    ['Last heartbeat', data.last_heartbeat_at ? new Date(data.last_heartbeat_at).toLocaleString() : 'No heartbeat recorded'],
    ['Connector version', data.connector_version], ['Sources', `${data.enabled_source_count} enabled / ${data.source_count} configured`],
    ['Local storage', `${bytes(data.storage_free_bytes)} free of ${bytes(data.storage_total_bytes)}`],
  ];
  return <Stack spacing={3}><div><Typography variant="h4" fontWeight={700}>Overview</Typography><Typography color="text.secondary">Current appliance operational state</Typography></div>
    <Grid container spacing={2}>{cards.map(([label, value]) => <Grid key={label} size={{ xs: 12, sm: 6, lg: 4 }}><Card variant="outlined" sx={{ height: '100%' }}><CardContent><Typography color="text.secondary" variant="body2">{label}</Typography><Typography variant="h6" sx={{ mt: 1, textTransform: 'capitalize' }}>{value}</Typography></CardContent></Card></Grid>)}</Grid>
    {data.unhealthy_source_count > 0 && <Alert severity="warning">{data.unhealthy_source_count} source(s) require attention.</Alert>}
    <div><Typography variant="h6" gutterBottom>Recent failures</Typography>{data.recent_failures.length === 0 ? <Alert severity="info">No recent connector failures have been recorded.</Alert> : <Stack spacing={1}>{data.recent_failures.map((failure) => <Card variant="outlined" key={failure.id}><CardContent><Chip size="small" color="error" label={failure.event_type} /><Typography sx={{ mt: 1 }}>{failure.message}</Typography><Typography variant="caption" color="text.secondary">{new Date(failure.created_at).toLocaleString()}</Typography></CardContent></Card>)}</Stack>}</div>
  </Stack>;
}
