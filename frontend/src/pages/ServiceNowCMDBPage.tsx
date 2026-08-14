import ArrowBackOutlinedIcon from '@mui/icons-material/ArrowBackOutlined';
import {
  Alert, Button, Paper, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { ServiceNowCMDBObservability } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { formatTimestamp } from '../utils/time';
import { serviceNowFreshnessMessage } from './serviceNowFreshness';

export function ServiceNowCMDBPage() {
  const { configurationId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<ServiceNowCMDBObservability | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const load = useCallback(async () => {
    if (!configurationId) { setError('ServiceNow configuration was not specified.'); setLoading(false); return; }
    setLoading(true);
    try { setData(await api.serviceNowCMDB(configurationId, page + 1)); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'ServiceNow CMDB records could not be loaded.'); }
    finally { setLoading(false); }
  }, [configurationId, page]);
  useEffect(() => { void load(); }, [load]);

  if (loading) return <LoadingState label="Loading ServiceNow CMDB records" />;
  return <Stack spacing={2}>
    <Stack direction="row" alignItems="center" spacing={1}>
      <Button startIcon={<ArrowBackOutlinedIcon />} onClick={() => navigate('/integrations?tab=data-sync')}>Data & Sync</Button>
      <div><Typography variant="h4" fontWeight={800}>ServiceNow CMDB records</Typography><Typography color="text.secondary">Cached configuration items from the ServiceNow CMDB source.</Typography></div>
    </Stack>
    {error && <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>}>{error}</Alert>}
    {data && <ServiceNowCMDBContent data={data} onPageChange={setPage} />}
  </Stack>;
}

export function ServiceNowCMDBContent({
  data,
  onPageChange,
}: {
  data: ServiceNowCMDBObservability;
  onPageChange?: (page: number) => void;
}) {
  const freshnessSeverity = data.freshness_state === 'error' ? 'error'
    : data.freshness_state === 'stale' ? 'warning' : 'success';
  return <>
      <Alert severity={freshnessSeverity} variant="outlined" sx={{ py: 0.25 }}>
        {serviceNowFreshnessMessage(data)}
      </Alert>
      {data.last_error && <Alert severity="warning">{data.last_error}</Alert>}
      <Stack direction="row" flexWrap="wrap" alignItems="center" gap={2}>
        <Typography variant="body2" fontWeight={650}>{data.total_cis} CIs</Typography>
        <Typography variant="body2" fontWeight={650}>{data.server_cis} servers</Typography>
        <Typography variant="body2" fontWeight={650}>{data.relationship_count} relationships</Typography>
      </Stack>
      {data.last_attempted_sync_at && <Typography variant="body2" color="text.secondary">Last attempted sync: {formatTimestamp(data.last_attempted_sync_at)}</Typography>}
      {data.items.length === 0 ? <Alert severity="info">No ServiceNow CMDB records have been synchronized.</Alert> :
        <Paper variant="outlined"><TableContainer><Table size="small"><TableHead><TableRow><TableCell>CI name</TableCell><TableCell>CI class</TableCell><TableCell>FQDN</TableCell><TableCell>IP address</TableCell><TableCell>Operating system</TableCell><TableCell>Environment</TableCell><TableCell>Application</TableCell><TableCell>Business owner</TableCell><TableCell>Support group</TableCell><TableCell>Lifecycle state</TableCell><TableCell>Updated</TableCell><TableCell>Source</TableCell></TableRow></TableHead><TableBody>{data.items.map((row) => <TableRow key={row.id}><TableCell>{row.ci_name}</TableCell><TableCell>{row.ci_class}</TableCell><TableCell>{row.fqdn ?? '—'}</TableCell><TableCell>{row.ip_address ?? '—'}</TableCell><TableCell>{row.operating_system ?? '—'}</TableCell><TableCell>{row.environment ?? '—'}</TableCell><TableCell>{row.application ?? '—'}</TableCell><TableCell>{row.business_owner ?? '—'}</TableCell><TableCell>{row.support_group ?? '—'}</TableCell><TableCell>{row.lifecycle_state ?? '—'}</TableCell><TableCell>{formatTimestamp(row.updated_at)}</TableCell><TableCell>{row.source}</TableCell></TableRow>)}</TableBody></Table></TableContainer><TablePagination component="div" count={data.total} page={data.page - 1} rowsPerPage={data.page_size} rowsPerPageOptions={[data.page_size]} onPageChange={(_, value) => onPageChange?.(value)} /></Paper>}
    </>;
}
