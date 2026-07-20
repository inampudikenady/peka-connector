import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { Source } from '../api/types';
import { SourceDialog } from '../components/SourceDialog';

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setSources(await api.listSources());
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load sources');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const scan = async (source: Source) => {
    setBusyId(source.id);
    setMessage('');
    setError('');
    try {
      const result = await api.scanSource(source.id);
      setMessage(`${source.name}: discovered ${result.discovered_count} document(s).`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Scan failed');
    } finally {
      setBusyId('');
    }
  };

  const remove = async (source: Source) => {
    if (!window.confirm(`Delete source “${source.name}” and its discovered metadata?`)) return;
    setBusyId(source.id);
    try {
      await api.deleteSource(source.id);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Delete failed');
    } finally {
      setBusyId('');
    }
  };

  return (
    <Stack spacing={3}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" fontWeight={700}>Document sources</Typography>
          <Typography color="text.secondary">Discover document metadata from local filesystems.</Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>Add source</Button>
      </Box>
      {message && <Alert severity="success" onClose={() => setMessage('')}>{message}</Alert>}
      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Path</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Interval</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={5} align="center"><CircularProgress size={28} /></TableCell></TableRow>}
            {!loading && sources.length === 0 && (
              <TableRow><TableCell colSpan={5} align="center" sx={{ py: 8 }}>
                <FolderOpenIcon color="disabled" sx={{ fontSize: 44 }} />
                <Typography color="text.secondary">No sources configured</Typography>
              </TableCell></TableRow>
            )}
            {sources.map((source) => (
              <TableRow key={source.id} hover>
                <TableCell><Typography fontWeight={600}>{source.name}</Typography><Typography variant="caption" color="text.secondary">Filesystem documents</Typography></TableCell>
                <TableCell sx={{ fontFamily: 'monospace' }}>{source.configuration.path}</TableCell>
                <TableCell><Chip size="small" color={source.enabled ? 'success' : 'default'} label={source.enabled ? 'Enabled' : 'Disabled'} /></TableCell>
                <TableCell>{source.configuration.scan_interval_seconds}s</TableCell>
                <TableCell align="right">
                  <Tooltip title="Scan now"><span><IconButton disabled={busyId === source.id || !source.enabled} onClick={() => void scan(source)}><PlayArrowIcon /></IconButton></span></Tooltip>
                  <Tooltip title="Delete"><span><IconButton color="error" disabled={busyId === source.id} onClick={() => void remove(source)}><DeleteOutlineIcon /></IconButton></span></Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <SourceDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onCreated={() => void load()} />
    </Stack>
  );
}

