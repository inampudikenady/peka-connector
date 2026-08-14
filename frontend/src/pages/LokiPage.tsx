import {
  Alert, Button, Card, CardActions, CardContent, Checkbox, Chip, FormControlLabel,
  Grid, MenuItem, Stack, TextField, Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { LokiConfiguration } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

const empty = {
  name: '', base_url: '', auth_type: 'none', username: '', secret: '',
  tls_verify: true, request_timeout_seconds: 10, discovery_lookback_days: 30,
  enabled: true,
};

export function LokiPage() {
  const { user } = useAuth();
  const admin = user?.role === 'administrator';
  const toast = useToast();
  const [items, setItems] = useState<LokiConfiguration[]>([]);
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      setLoading(true);
      setItems(await api.lokiConfigurations());
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Loki configurations could not be loaded');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const save = async () => {
    try {
      if (editingId) await api.updateLokiConfiguration(editingId, form);
      else await api.createLokiConfiguration(form);
      setForm(empty);
      setEditingId(null);
      await load();
      toast.show('Loki configuration saved.', 'success');
    } catch (reason) {
      toast.show(reason instanceof Error ? reason.message : 'Save failed', 'error');
    }
  };
  const act = async (item: LokiConfiguration, action: 'test' | 'discover') => {
    try {
      if (action === 'test') {
        const result = await api.testLoki(item.id);
        toast.show(`${result.message} ${result.stream_count} streams discovered.`, 'success');
      } else {
        const result = await api.discoverLoki(item.id);
        toast.show(`Discovered ${result.stream_count} streams and ${result.labels.length} labels.`, 'success');
      }
      await load();
    } catch (reason) {
      toast.show(reason instanceof Error ? reason.message : `${action} failed`, 'error');
    }
  };
  return <Stack spacing={3}>
    <div>
      <Typography variant="h4" fontWeight={800}>Loki</Typography>
      <Typography color="text.secondary">Discover live log labels and correlate fixed operational evidence queries with inventory assets. LogQL remains connector-controlled.</Typography>
    </div>
    {error && <Alert severity="error">{error}</Alert>}
    {admin && <Card variant="outlined"><CardContent><Stack spacing={2}>
      <Typography variant="h6">{editingId ? 'Edit Loki configuration' : 'Add Loki configuration'}</Typography>
      <TextField label="Configuration name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <TextField label="Base URL" placeholder="https://loki.example.com" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} />
      <TextField select label="Authentication" value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value })}>
        <MenuItem value="none">None</MenuItem><MenuItem value="basic">Basic</MenuItem><MenuItem value="bearer">Bearer token</MenuItem>
      </TextField>
      {form.auth_type === 'basic' && <TextField label="Username" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />}
      {form.auth_type !== 'none' && <TextField label={form.auth_type === 'bearer' ? 'Bearer token' : 'Password'} type="password" value={form.secret} onChange={(event) => setForm({ ...form, secret: event.target.value })} helperText="Credentials are encrypted and are not shown again." />}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField label="Request timeout (seconds)" type="number" value={form.request_timeout_seconds} onChange={(event) => setForm({ ...form, request_timeout_seconds: Number(event.target.value) })} />
        <TextField label="Discovery lookback (days)" type="number" value={form.discovery_lookback_days} onChange={(event) => setForm({ ...form, discovery_lookback_days: Number(event.target.value) })} helperText="Daily bounded scans; 1–90 days." />
      </Stack>
      <FormControlLabel control={<Checkbox checked={form.tls_verify} onChange={(event) => setForm({ ...form, tls_verify: event.target.checked })} />} label="Verify TLS certificates" />
    </Stack></CardContent><CardActions>
      {editingId && <Button onClick={() => { setEditingId(null); setForm(empty); }}>Cancel</Button>}
      <Button variant="contained" disabled={!form.name || !form.base_url} onClick={() => void save()}>Save configuration</Button>
    </CardActions></Card>}
    {loading ? <LoadingState label="Loading Loki configurations" /> : <Grid container spacing={2}>{items.map((item) => <Grid key={item.id} size={{ xs: 12, md: 6 }}><Card variant="outlined"><CardContent>
      <Stack direction="row" justifyContent="space-between"><Typography variant="h6">{item.name}</Typography><Chip size="small" label="Configured" /></Stack>
      <Typography color="text.secondary">{item.base_url}</Typography>
      {item.warnings.map((warning) => <Alert key={warning} severity="warning" sx={{ mt: 1 }}>{warning}</Alert>)}
      <Typography sx={{ mt: 2 }}>{item.stream_count} streams · {item.labels.length} labels</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 1 }}>{item.labels.map((label) => <Chip key={label} size="small" label={label} />)}</Stack>
      <Typography variant="body2" sx={{ mt: 2 }}>Last discovery: {formatTimestamp(item.last_successful_discovery_at)}</Typography>
      <Typography variant="body2">Last connection test: {formatTimestamp(item.last_successful_test_at)}</Typography>
      {item.last_error && <Alert severity="error" sx={{ mt: 1 }}>{item.last_error}</Alert>}
    </CardContent>{admin && <CardActions>
      <Button onClick={() => { setEditingId(item.id); setForm({ name: item.name, base_url: item.base_url, auth_type: item.auth_type, username: item.username ?? '', secret: '', tls_verify: item.tls_verify, request_timeout_seconds: item.request_timeout_seconds, discovery_lookback_days: item.discovery_lookback_days, enabled: item.enabled }); }}>Edit</Button>
      <Button variant="contained" onClick={() => void act(item, 'test')}>Test connection</Button>
    </CardActions>}</Card></Grid>)}</Grid>}
    {!loading && items.length === 0 && <Alert severity="info">Loki is not configured. Log evidence will be reported as unknown, never as healthy or empty.</Alert>}
  </Stack>;
}
