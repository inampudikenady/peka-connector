import {
  Alert, Button, Chip, Pagination, Paper, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { PaginatedActivity } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import {
  activityEventLabel, activityOutcomeLabel, activityTimestamp, safeActivitySummary,
} from '../utils/activity';

const outcomeColor = {
  success: 'success', warning: 'warning', failure: 'error', information: 'default',
} as const;

interface ActivityContentProps {
  data: PaginatedActivity | null;
  error: boolean;
  loading: boolean;
  onRetry: () => void;
  onPageChange: (page: number) => void;
}

export function ActivityContent({
  data, error, loading, onRetry, onPageChange,
}: ActivityContentProps) {
  if (error) {
    return <Alert severity="error" action={<Button color="inherit" onClick={onRetry}>Retry</Button>}>Activity could not be loaded.</Alert>;
  }
  if (loading || !data) return <LoadingState label="Loading activity" />;
  if (data.items.length === 0) {
    return <Alert severity="info">No activity has been recorded yet.</Alert>;
  }
  return <Stack spacing={2}>
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="Connector activity">
        <TableHead><TableRow><TableCell>Event</TableCell><TableCell>Summary</TableCell><TableCell>When</TableCell><TableCell>Outcome</TableCell></TableRow></TableHead>
        <TableBody>{data.items.map((event) => {
          const timestamp = activityTimestamp(event.created_at);
          return <TableRow key={event.id}>
            <TableCell><Typography fontWeight={600}>{activityEventLabel(event.event_type)}</Typography>{event.actor_username && <Typography variant="caption" color="text.secondary">By {event.actor_username}</Typography>}</TableCell>
            <TableCell>{safeActivitySummary(event.message)}</TableCell>
            <TableCell><Typography>{timestamp.relative}</Typography><Typography variant="caption" color="text.secondary">{timestamp.absolute}</Typography></TableCell>
            <TableCell><Chip size="small" label={activityOutcomeLabel(event.outcome)} color={outcomeColor[event.outcome]} /></TableCell>
          </TableRow>;
        })}</TableBody>
      </Table>
    </TableContainer>
    {data.total > data.page_size && <Pagination page={data.page} count={Math.ceil(data.total / data.page_size)} onChange={(_, page) => onPageChange(page)} />}
  </Stack>;
}

export function ActivityPage() {
  const [data, setData] = useState<PaginatedActivity | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    void api.activity(page)
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [page]);
  useEffect(load, [load]);
  return <Stack spacing={3}>
    <div><Typography variant="h4" fontWeight={700}>Activity</Typography><Typography color="text.secondary">Human-readable operational history. Use Logs for technical troubleshooting.</Typography></div>
    <ActivityContent data={data} error={error} loading={loading} onRetry={load} onPageChange={setPage} />
  </Stack>;
}
