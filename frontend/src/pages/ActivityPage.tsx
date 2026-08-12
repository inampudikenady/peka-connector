import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import {
  Alert, Box, Button, Chip, Collapse, FormControl, IconButton, InputLabel, MenuItem,
  Pagination, Paper, Select, Stack, Tab, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Tabs, Typography,
} from '@mui/material';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type {
  ActivityOverview, OperationalRequestRecord, PaginatedActivity,
  PaginatedOperationalRequests,
} from '../api/types';
import { LoadingState } from '../components/LoadingState';
import {
  activityEventLabel, activityOutcomeLabel, activityTimestamp, safeActivitySummary,
} from '../utils/activity';
import { formatTimestamp, relativeTimestamp } from '../utils/time';
import { LogsContent } from './LogsPage';

type ActivityTab = 'overview' | 'requests' | 'events' | 'logs';
const outcomeColor = {
  success: 'success', warning: 'warning', failure: 'error', information: 'default',
} as const;
const requestColor = {
  pending: 'default', running: 'info', succeeded: 'success', failed: 'error',
  expired: 'warning', cancelled: 'default',
} as const;

interface ActivityContentProps {
  data: PaginatedActivity | null; error: boolean; loading: boolean;
  onRetry: () => void; onPageChange: (page: number) => void;
}

export function ActivityContent({ data, error, loading, onRetry, onPageChange }: ActivityContentProps) {
  const [integration, setIntegration] = useState('All'); const [eventType, setEventType] = useState('All');
  const [outcome, setOutcome] = useState('All'); const [timeRange, setTimeRange] = useState('All');
  const filtered = useMemo(() => {
    if (!data) return [];
    const cutoffHours = timeRange === '24 hours' ? 24 : timeRange === '7 days' ? 168 : timeRange === '30 days' ? 720 : null;
    return data.items.filter((event) => (integration === 'All' || (event.integration ?? '') === integration)
      && (eventType === 'All' || event.event_type === eventType)
      && (outcome === 'All' || event.outcome === outcome)
      && (!cutoffHours || Date.parse(event.created_at) >= Date.now() - cutoffHours * 3600000));
  }, [data, integration, eventType, outcome, timeRange]);
  if (error) return <Alert severity="error" action={<Button color="inherit" onClick={onRetry}>Retry</Button>}>Activity could not be loaded.</Alert>;
  if (loading || !data) return <LoadingState label="Loading activity" />;
  const integrations = ['All', ...Array.from(new Set(data.items.map((item) => item.integration).filter(Boolean) as string[]))];
  const eventTypes = ['All', ...Array.from(new Set(data.items.map((item) => item.event_type)))];
  return <Stack spacing={1.5}><Stack direction={{ xs: 'column', md: 'row' }} spacing={1}><Filter label="Integration" value={integration} values={integrations} onChange={setIntegration} /><Filter label="Event type" value={eventType} values={eventTypes} onChange={setEventType} /><Filter label="Outcome" value={outcome} values={['All', 'success', 'warning', 'failure', 'information']} onChange={setOutcome} /><Filter label="Time range" value={timeRange} values={['All', '24 hours', '7 days', '30 days']} onChange={setTimeRange} /></Stack>{filtered.length === 0 ? <Alert severity="info">{data.items.length === 0 ? 'No activity has been recorded yet.' : 'No activity matches the selected filters.'}</Alert> : <TableContainer component={Paper} variant="outlined"><Table size="small" aria-label="Connector activity"><TableHead><TableRow><TableCell>Event</TableCell><TableCell>Summary</TableCell><TableCell>Integration</TableCell><TableCell>Time</TableCell><TableCell>Outcome</TableCell></TableRow></TableHead><TableBody>{filtered.map((event) => { const timestamp = activityTimestamp(event.created_at); return <TableRow key={event.id}><TableCell><Typography fontWeight={650}>{activityEventLabel(event.event_type)}</Typography>{event.actor_username && <Typography variant="caption" color="text.secondary">By {event.actor_username}</Typography>}</TableCell><TableCell>{safeActivitySummary(event.message)}</TableCell><TableCell>{event.integration ?? 'Connector'}</TableCell><TableCell><Typography variant="body2">{timestamp.relative}</Typography><Typography variant="caption" color="text.secondary">{timestamp.absolute}</Typography></TableCell><TableCell><Chip size="small" label={activityOutcomeLabel(event.outcome)} color={outcomeColor[event.outcome]} /></TableCell></TableRow>; })}</TableBody></Table></TableContainer>}{data.total > data.page_size && <Pagination page={data.page} count={Math.ceil(data.total / data.page_size)} onChange={(_, next) => onPageChange(next)} />}</Stack>;
}

function Filter({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <FormControl size="small" sx={{ minWidth: 150 }}><InputLabel>{label}</InputLabel><Select label={label} value={value} onChange={(event) => onChange(event.target.value)}>{values.map((item) => <MenuItem key={item} value={item}>{item.replaceAll('_', ' ')}</MenuItem>)}</Select></FormControl>;
}

export function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const tab: ActivityTab = requested === 'requests' || requested === 'events' || requested === 'logs' ? requested : 'overview';
  return <Stack spacing={2}><Box><Typography variant="h4" fontWeight={800}>Activity</Typography><Typography color="text.secondary">Operational requests, human-readable events, and technical logs.</Typography></Box><Paper variant="outlined"><Tabs value={tab} onChange={(_, value: ActivityTab) => setParams({ tab: value })} aria-label="Activity sections"><Tab value="overview" label="Overview" /><Tab value="requests" label="Requests" /><Tab value="events" label="Events" /><Tab value="logs" label="Logs" /></Tabs></Paper>{tab === 'overview' && <ActivityOverviewTab />}{tab === 'requests' && <RequestsTab />}{tab === 'events' && <EventsTab />}{tab === 'logs' && <LogsContent />}</Stack>;
}

function ActivityOverviewTab() {
  const [data, setData] = useState<ActivityOverview | null>(null); const [error, setError] = useState('');
  useEffect(() => { void api.activityOverview().then(setData).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <Alert severity="error">{error}</Alert>; if (!data) return <LoadingState />;
  const facts = [['Pending', data.pending_requests], ['Running', data.running_requests], ['Failed', data.failed_requests], ['Succeeded in 24h', data.successful_requests_24h]] as const;
  return <Stack spacing={1.5}><Paper variant="outlined"><Stack direction={{ xs: 'column', sm: 'row' }}>{facts.map(([label, value]) => <Box key={label} sx={{ px: 2, py: 1.25, minWidth: 140 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" fontWeight={750}>{value}</Typography></Box>)}</Stack></Paper><Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}><Paper variant="outlined" sx={{ p: 1.5, flex: 1 }}><Typography variant="caption" color="text.secondary">Last heartbeat</Typography><Typography fontWeight={650}>{data.last_heartbeat_at ? relativeTimestamp(data.last_heartbeat_at) : 'Never'}</Typography></Paper><Paper variant="outlined" sx={{ p: 1.5, flex: 1 }}><Typography variant="caption" color="text.secondary">Last completed sync</Typography><Typography fontWeight={650}>{data.last_completed_sync_at ? relativeTimestamp(data.last_completed_sync_at) : 'Never'}</Typography></Paper></Stack><Typography variant="subtitle1" fontWeight={700}>Recent warnings or failures</Typography>{data.recent_warnings_or_failures.length ? <Paper variant="outlined">{data.recent_warnings_or_failures.map((event) => <Box key={event.id} sx={{ px: 2, py: 1, borderTop: 1, borderColor: 'divider' }}><Typography fontWeight={650}>{activityEventLabel(event.event_type)}</Typography><Typography variant="body2" color="text.secondary">{safeActivitySummary(event.message)} · {relativeTimestamp(event.created_at)}</Typography></Box>)}</Paper> : <Alert severity="success">No recent warnings or failures.</Alert>}</Stack>;
}

function RequestsTab() {
  const [data, setData] = useState<PaginatedOperationalRequests | null>(null); const [page, setPage] = useState(1); const [error, setError] = useState('');
  useEffect(() => { void api.operationalRequests(page).then(setData).catch((reason: Error) => setError(reason.message)); }, [page]);
  if (error) return <Alert severity="error">{error}</Alert>; if (!data) return <LoadingState />;
  if (!data.items.length) return <Alert severity="info">No operational requests have been executed yet.</Alert>;
  return <Stack spacing={1}><TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell /><TableCell>Request time</TableCell><TableCell>Request type</TableCell><TableCell>Integration</TableCell><TableCell>Target asset</TableCell><TableCell>Status</TableCell><TableCell>Duration</TableCell><TableCell>Result</TableCell></TableRow></TableHead><TableBody>{data.items.map((item) => <RequestRow key={item.request_id} item={item} />)}</TableBody></Table></TableContainer>{data.total > data.page_size && <Pagination page={page} count={Math.ceil(data.total / data.page_size)} onChange={(_, value) => setPage(value)} />}</Stack>;
}

function RequestRow({ item }: { item: OperationalRequestRecord }) {
  const [open, setOpen] = useState(false);
  return <><TableRow><TableCell><IconButton size="small" aria-label="Technical request details" onClick={() => setOpen(!open)}>{open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}</IconButton></TableCell><TableCell>{formatTimestamp(item.requested_at)}</TableCell><TableCell>{item.tool_name.replaceAll('_', ' ')}</TableCell><TableCell>{item.integration}</TableCell><TableCell>{item.target_asset ?? '—'}</TableCell><TableCell><Chip size="small" label={item.status.charAt(0).toUpperCase() + item.status.slice(1)} color={requestColor[item.status]} /></TableCell><TableCell>{item.duration_ms === null ? '—' : `${item.duration_ms.toFixed(1)} ms`}</TableCell><TableCell>{item.result_summary ?? '—'}</TableCell></TableRow><TableRow><TableCell colSpan={8} sx={{ py: 0 }}><Collapse in={open} unmountOnExit><Box sx={{ py: 1.25 }}><Typography variant="caption" color="text.secondary">Request ID</Typography><Typography variant="body2" fontFamily="monospace">{item.request_id}</Typography>{item.error_code && <Typography variant="body2" color="error">Error code: {item.error_code}</Typography>}</Box></Collapse></TableCell></TableRow></>;
}

function EventsTab() {
  const [data, setData] = useState<PaginatedActivity | null>(null); const [page, setPage] = useState(1); const [loading, setLoading] = useState(true); const [error, setError] = useState(false);
  const load = useCallback(() => { setLoading(true); setError(false); void api.activity(page).then(setData).catch(() => setError(true)).finally(() => setLoading(false)); }, [page]);
  useEffect(load, [load]);
  return <ActivityContent data={data} error={error} loading={loading} onRetry={load} onPageChange={setPage} />;
}
