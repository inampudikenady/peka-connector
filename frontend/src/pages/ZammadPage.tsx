import {
  Alert, Button, Card, CardActions, CardContent, Checkbox, Chip,
  FormControlLabel, Grid, Stack, TextField, Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { ZammadConfiguration } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

const empty = {
  name: 'Zammad', base_url: '', access_token: '', tls_verify: true,
  request_timeout_seconds: 15, sync_interval_seconds: 900,
  history_window_days: 90, group_filters_text: '',
  include_closed_tickets: true, enabled: true,
};

export function ZammadPage() {
  const { user } = useAuth();
  const admin = user?.role === 'administrator';
  const toast = useToast();
  const [items, setItems] = useState<ZammadConfiguration[]>([]);
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try { setLoading(true); setItems(await api.zammadConfigurations()); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Zammad configuration could not be loaded'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const payload = () => ({
    name: form.name, base_url: form.base_url,
    access_token: form.access_token || null, tls_verify: form.tls_verify,
    request_timeout_seconds: form.request_timeout_seconds,
    sync_interval_seconds: form.sync_interval_seconds,
    history_window_days: form.history_window_days,
    group_filters: form.group_filters_text.split(',').map((value) => value.trim()).filter(Boolean),
    include_closed_tickets: form.include_closed_tickets, enabled: form.enabled,
  });
  const save = async () => {
    try {
      if (editingId) await api.updateZammadConfiguration(editingId, payload());
      else await api.createZammadConfiguration(payload());
      setEditingId(null); setForm(empty); await load();
      toast.show('Zammad configuration saved.', 'success');
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Save failed', 'error'); }
  };
  const act = async (item: ZammadConfiguration, action: 'test' | 'sync') => {
    try {
      if (action === 'test') {
        const result = await api.testZammad(item.id);
        toast.show(result.message, 'success');
      } else {
        const result = await api.syncZammad(item.id);
        toast.show(`Synchronized ${result.ticket_count} tickets and ${result.article_count} articles.`, 'success');
      }
      await load();
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : `${action} failed`, 'error'); }
  };

  return <Stack spacing={3}>
    <div><Typography variant="h4" fontWeight={800}>Zammad</Typography>
      <Typography color="text.secondary">Synchronize read-only ticket evidence locally for operational assistant questions. Access tokens never leave this connector.</Typography></div>
    {error && <Alert severity="error">{error}</Alert>}
    {admin && <Card variant="outlined"><CardContent><Stack spacing={2}>
      <Typography variant="h6">{editingId ? 'Edit Zammad configuration' : 'Add Zammad configuration'}</Typography>
      <TextField label="Configuration name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <TextField label="Zammad base URL" placeholder="https://zammad.example.com" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} />
      <TextField label="Access token" type="password" value={form.access_token} onChange={(event) => setForm({ ...form, access_token: event.target.value })} helperText={editingId ? 'Leave blank to keep the configured token.' : 'Encrypted locally and never shown again.'} />
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField fullWidth label="Request timeout (seconds)" type="number" value={form.request_timeout_seconds} onChange={(event) => setForm({ ...form, request_timeout_seconds: Number(event.target.value) })} />
        <TextField fullWidth label="Synchronization interval (seconds)" type="number" value={form.sync_interval_seconds} onChange={(event) => setForm({ ...form, sync_interval_seconds: Number(event.target.value) })} />
        <TextField fullWidth label="Ticket history window (days)" type="number" value={form.history_window_days} onChange={(event) => setForm({ ...form, history_window_days: Number(event.target.value) })} />
      </Stack>
      <TextField label="Group filters (optional, comma separated)" value={form.group_filters_text} onChange={(event) => setForm({ ...form, group_filters_text: event.target.value })} />
      <FormControlLabel control={<Checkbox checked={form.tls_verify} onChange={(event) => setForm({ ...form, tls_verify: event.target.checked })} />} label="Verify TLS certificate" />
      <FormControlLabel control={<Checkbox checked={form.include_closed_tickets} onChange={(event) => setForm({ ...form, include_closed_tickets: event.target.checked })} />} label="Include closed tickets" />
      <FormControlLabel control={<Checkbox checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />} label="Enable Zammad synchronization" />
    </Stack></CardContent><CardActions>
      {editingId && <Button onClick={() => { setEditingId(null); setForm(empty); }}>Cancel</Button>}
      <Button variant="contained" disabled={!form.name || !form.base_url || (!editingId && !form.access_token)} onClick={() => void save()}>Save</Button>
    </CardActions></Card>}
    {loading ? <LoadingState label="Loading Zammad configuration" /> : <Grid container spacing={2}>{items.map((item) => <Grid key={item.id} size={{ xs: 12, md: 6 }}><Card variant="outlined"><CardContent>
      <Stack direction="row" justifyContent="space-between"><Typography variant="h6">{item.name}</Typography><Chip size="small" color={item.connection_state === 'connected' ? 'success' : item.connection_state === 'failed' ? 'error' : 'default'} label={item.connection_state.replace('_', ' ')} /></Stack>
      <Typography color="text.secondary">{item.base_url}</Typography>
      <Typography sx={{ mt: 1 }}>Token: {item.token_configured ? 'Configured' : 'Not configured'}</Typography>
      <Typography>{item.synchronized_ticket_count} tickets · {item.synchronized_article_count} articles</Typography>
      <Typography variant="body2" sx={{ mt: 1 }}>Last connection test: {formatTimestamp(item.last_successful_test_at)}</Typography>
      <Typography variant="body2">Last synchronization: {formatTimestamp(item.last_successful_sync_at)}</Typography>
      <Typography variant="body2">Duration: {item.last_sync_duration_seconds == null ? 'Never' : `${item.last_sync_duration_seconds}s`}</Typography>
      <Typography variant="body2">Next synchronization: {formatTimestamp(item.next_scheduled_sync_at)}</Typography>
      {item.last_error && <Alert severity="error" sx={{ mt: 1 }}>{item.last_error}</Alert>}
    </CardContent>{admin && <CardActions>
      <Button onClick={() => { setEditingId(item.id); setForm({ name: item.name, base_url: item.base_url, access_token: '', tls_verify: item.tls_verify, request_timeout_seconds: item.request_timeout_seconds, sync_interval_seconds: item.sync_interval_seconds, history_window_days: item.history_window_days, group_filters_text: item.group_filters.join(', '), include_closed_tickets: item.include_closed_tickets, enabled: item.enabled }); }}>Edit</Button>
      <Button disabled={!item.enabled} onClick={() => void act(item, 'sync')}>Sync now</Button>
      <Button variant="contained" disabled={!item.enabled || !item.token_configured} onClick={() => void act(item, 'test')}>Test connection</Button>
    </CardActions>}</Card></Grid>)}</Grid>}
    {!loading && items.length === 0 && <Alert severity="info">Zammad is not configured. Ticket evidence will be reported as unavailable.</Alert>}
  </Stack>;
}
