import DownloadIcon from '@mui/icons-material/Download';
import { Alert, Button, Chip, List, ListItem, ListItemText, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { api } from '../api/client'; import type { Diagnostics } from '../api/types'; import { LoadingState } from '../components/LoadingState'; import { useToast } from '../components/ToastProvider';
export function DiagnosticsPage() { const toast = useToast(); const [data, setData] = useState<Diagnostics | null>(null); const [error, setError] = useState(''); useEffect(() => { void api.diagnostics().then(setData).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <Alert severity="error">{error}</Alert>; if (!data) return <LoadingState label="Running diagnostics" />;
  return <Stack spacing={3}><Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between"><div><Typography variant="h4" fontWeight={700}>Diagnostics</Typography><Typography color="text.secondary">Runtime and appliance health checks</Typography></div><Button startIcon={<DownloadIcon />} variant="outlined" onClick={() => void api.downloadDiagnostics().catch((e: Error) => toast.show(e.message, 'error'))}>Download diagnostics bundle</Button></Stack>
    <Paper variant="outlined"><List>{data.checks.map((check) => <ListItem key={check.name} divider><ListItemText primary={check.name} secondary={check.detail} /><Chip label={check.status} color={check.status === 'healthy' ? 'success' : check.status === 'unhealthy' ? 'error' : 'default'} /></ListItem>)}</List></Paper>
    <Paper variant="outlined" sx={{ p: 2 }}><Typography>Version: {data.version} ({data.build})</Typography><Typography>Python: {data.python_version}</Typography><Typography>Platform: {data.platform}</Typography><Typography>Migration: {data.migration_revision ?? 'Unavailable'}</Typography></Paper>
  </Stack>;
}
