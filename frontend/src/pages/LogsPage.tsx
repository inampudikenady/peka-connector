import DownloadIcon from '@mui/icons-material/Download';
import {
  Alert, Button, Checkbox, FormControlLabel, MenuItem, Pagination, Paper, Stack,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { PaginatedLogs } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

export function LogsContent() {
  const toast = useToast(); const [data, setData] = useState<PaginatedLogs | null>(null);
  const [level, setLevel] = useState(''); const [component, setComponent] = useState('');
  const [search, setSearch] = useState(''); const [page, setPage] = useState(1);
  const [autoRefresh, setAutoRefresh] = useState(false); const [error, setError] = useState('');
  const load = useCallback(() => {
    const query = new URLSearchParams({ page: String(page), page_size: '50' });
    if (level) query.set('level', level); if (component) query.set('component', component);
    if (search) query.set('search', search);
    void api.logs(query.toString()).then((result) => { setData(result); setError(''); }).catch((reason: Error) => setError(reason.message));
  }, [page, level, component, search]);
  useEffect(load, [load]);
  useEffect(() => { if (!autoRefresh) return undefined; const timer = window.setInterval(load, 10000); return () => window.clearInterval(timer); }, [autoRefresh, load]);
  return <Stack spacing={1.5}>
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} alignItems={{ md: 'center' }}><TextField size="small" select label="Level" value={level} onChange={(event) => { setLevel(event.target.value); setPage(1); }} sx={{ minWidth: 130 }}><MenuItem value="">All</MenuItem>{['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField size="small" label="Component" value={component} onChange={(event) => { setComponent(event.target.value); setPage(1); }} /><TextField size="small" fullWidth label="Search logs" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} /><FormControlLabel control={<Checkbox checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />} label="Auto-refresh" /><Button startIcon={<DownloadIcon />} onClick={() => void api.downloadLogs().catch((reason: Error) => toast.show(reason.message, 'error'))}>Download</Button></Stack>
    {error ? <Alert severity="error">{error}</Alert> : !data ? <LoadingState /> : data.items.length === 0 ? <Alert severity="info">No logs match the selected filters.</Alert> : <><TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Timestamp</TableCell><TableCell>Level</TableCell><TableCell>Component</TableCell><TableCell>Message</TableCell></TableRow></TableHead><TableBody>{data.items.map((item) => <TableRow key={item.id}><TableCell>{formatTimestamp(item.created_at)}</TableCell><TableCell>{item.level}</TableCell><TableCell>{item.component}</TableCell><TableCell>{item.message}</TableCell></TableRow>)}</TableBody></Table></TableContainer><Pagination page={page} count={Math.max(1, Math.ceil(data.total / data.page_size))} onChange={(_, value) => setPage(value)} /></>}
  </Stack>;
}

export function LogsPage() { return <LogsContent />; }
