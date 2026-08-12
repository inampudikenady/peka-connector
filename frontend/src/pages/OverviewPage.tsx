import RefreshIcon from '@mui/icons-material/Refresh';
import {
  Alert, Box, Button, CircularProgress, Chip, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import type { KnowledgeStoreOverview } from '../api/types';

import { useAuth } from '../auth/AuthContext';
import { ConnectionStatusBadge } from '../components/ConnectionStatusBadge';
import { useConnectorStatus } from '../components/ConnectorStatusContext';
import { LoadingState } from '../components/LoadingState';
import { activityEventLabel, safeActivitySummary } from '../utils/activity';
import { timestampDisplay } from '../utils/time';

function relative(value: string | null) {
  return value ? timestampDisplay(value, Date.now(), 'Never').relative : 'Never';
}

function SummaryValue({ label, value }: { label: string; value: number | string }) {
  return <Paper variant="outlined" sx={{ flex: '1 1 150px', minWidth: 0, px: 2, py: 1.5 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5">{value}</Typography></Paper>;
}

export function KnowledgeStoreCard({ store }: { store: KnowledgeStoreOverview }) {
  const status = store.status.charAt(0).toUpperCase() + store.status.slice(1);
  const color = store.status === 'healthy' ? 'success' : store.status === 'degraded' ? 'warning' : 'error';
  const facts: Array<[string, string]> = [
    ['Engine', `Qdrant ${store.engine_version ?? 'Unknown'}`],
    ['Collection', store.collection],
    ['Documents', store.documents.toLocaleString()],
    ['Chunks', store.chunks.toLocaleString()],
    ['Pending', store.pending.toLocaleString()],
    ['Failed', store.failed.toLocaleString()],
  ];
  return <Paper variant="outlined" sx={{ flex: '1.8 1 340px', minWidth: 0, px: 2, py: 1.5 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1.25}>
      <Typography variant="caption" color="text.secondary">Local Knowledge Store</Typography>
      <Chip size="small" color={color} label={status} />
    </Stack>
    <Box sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.5 }}>
      {facts.map(([name, value]) => <Box key={name} sx={{ display: 'contents' }}><Typography variant="caption" color="text.secondary">{name}</Typography><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{value}</Typography></Box>)}
    </Box>
    <Box sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.5, mt: 1.25 }}>
      <Typography variant="caption" color="text.secondary">Last indexed</Typography>
      <Typography variant="caption" color="text.secondary">{relative(store.last_indexed_at)}</Typography>
      <Typography variant="caption" color="text.secondary">Last search</Typography>
      <Typography variant="caption" color="text.secondary">{relative(store.last_search_at)}</Typography>
    </Box>
  </Paper>;
}

export function OverviewPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data, error, loading, retrying, retryHeartbeat } = useConnectorStatus();
  if (loading && !data) return <LoadingState label="Loading connector overview" />;
  if (!data) return <Alert severity="error">{error || 'Connector status could not be loaded.'}</Alert>;
  return <Stack spacing={2.5}>
    <Box><Typography variant="h4">Overview</Typography><Typography variant="body2" color="text.secondary">Connector connectivity and integration readiness.</Typography></Box>
    {error && <Alert severity="error">{error}</Alert>}
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ md: 'center' }} spacing={2}>
        <Box sx={{ flex: 1 }}><Typography variant="overline" color="text.secondary">Connector connectivity</Typography><Typography variant="h6">{data.connector_display_name}</Typography><Typography variant="body2" color="text.secondary">Version {data.connector_version} · {data.connector_status}</Typography><Typography variant="body2" color="text.secondary">Last successful heartbeat: {relative(data.last_heartbeat_at)}</Typography></Box>
        <Stack direction="row" alignItems="center" spacing={1.5}><ConnectionStatusBadge status={data.saas_status} />{user?.role === 'administrator' && <Button variant="outlined" size="small" startIcon={retrying ? <CircularProgress size={16} /> : <RefreshIcon />} disabled={retrying || !data.connector_id} onClick={() => void retryHeartbeat().catch(() => undefined)}>{retrying ? 'Retrying…' : 'Retry heartbeat'}</Button>}</Stack>
      </Stack>
    </Paper>
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}><KnowledgeStoreCard store={data.knowledge_store} /><SummaryValue label="Enabled integrations" value={data.enabled_integration_count} /><SummaryValue label="Healthy integrations" value={data.healthy_integration_count} /><SummaryValue label="Need attention" value={data.attention_integration_count} /></Box>
    <Box><Typography variant="h6" mb={1}>Recent integration failures</Typography>{data.recent_integration_failures.length === 0 ? <Paper variant="outlined" sx={{ px: 2, py: 1.5 }}><Typography variant="body2" color="text.secondary">No recent integration failures.</Typography></Paper> : <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Integration</TableCell><TableCell>Failure</TableCell><TableCell>Time</TableCell><TableCell>Status</TableCell><TableCell align="right" /></TableRow></TableHead><TableBody>{data.recent_integration_failures.map((event) => <TableRow key={event.id}><TableCell>{event.integration ?? 'Connector'}</TableCell><TableCell><Typography variant="body2" fontWeight={650}>{activityEventLabel(event.event_type)}</Typography><Typography variant="caption" color="text.secondary">{safeActivitySummary(event.message)}</Typography></TableCell><TableCell>{relative(event.created_at)}</TableCell><TableCell><Chip size="small" color="error" label="Failed" /></TableCell><TableCell align="right"><Button size="small" variant="text" onClick={() => navigate('/activity?tab=events')}>View details</Button></TableCell></TableRow>)}</TableBody></Table></TableContainer>}</Box>
  </Stack>;
}
