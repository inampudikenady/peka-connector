import {
  Alert, Button, Card, CardActions, CardContent, Checkbox, Chip,
  FormControlLabel, Grid, Stack, TextField, Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { ServiceNowConfiguration } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

const empty = {
  name: 'ServiceNow', enabled: true, instance_url: '', username: '', password: '',
  verify_tls: true, request_timeout_seconds: 20, page_size: 200,
  sync_interval_seconds: 900,
};

export function ServiceNowPage() {
  const toast = useToast();
  const [items, setItems] = useState<ServiceNowConfiguration[]>([]);
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try { setItems(await api.serviceNowConfigurations()); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'ServiceNow configuration could not be loaded.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const edit = (item: ServiceNowConfiguration) => {
    setEditingId(item.id);
    setForm({ name: 'ServiceNow', enabled: item.enabled, instance_url: item.instance_url, username: item.username, password: '', verify_tls: item.verify_tls, request_timeout_seconds: item.request_timeout_seconds, page_size: item.page_size, sync_interval_seconds: item.sync_interval_seconds });
  };
  const save = async () => {
    setBusy(true);
    try {
      if (editingId) await api.updateServiceNowConfiguration(editingId, form);
      else await api.createServiceNowConfiguration(form);
      toast.show('ServiceNow configuration saved.', 'success'); setForm(empty); setEditingId(null); await load();
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'ServiceNow configuration could not be saved.', 'error'); }
    finally { setBusy(false); }
  };
  const disable = async (item: ServiceNowConfiguration) => {
    setBusy(true);
    try {
      await api.updateServiceNowConfiguration(item.id, {
        name: 'ServiceNow', enabled: false, instance_url: item.instance_url,
        username: item.username, password: null, verify_tls: item.verify_tls,
        request_timeout_seconds: item.request_timeout_seconds, page_size: item.page_size,
        sync_interval_seconds: item.sync_interval_seconds,
      });
      toast.show('ServiceNow integration disabled.', 'success'); await load();
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'ServiceNow could not be disabled.', 'error'); }
    finally { setBusy(false); }
  };
  const act = async (item: ServiceNowConfiguration, action: 'test' | 'sync') => {
    setBusy(true);
    try {
      if (action === 'test') await api.testServiceNow(item.id); else await api.syncServiceNow(item.id);
      toast.show(action === 'test' ? 'ServiceNow connection test completed.' : 'ServiceNow synchronization completed.', 'success'); await load();
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : `ServiceNow ${action} failed.`, 'error'); }
    finally { setBusy(false); }
  };
  return <Stack spacing={2}>
    <div><Typography variant="h4" fontWeight={800}>ServiceNow</Typography><Typography color="text.secondary">CMDB, incident, problem, change and relationship evidence.</Typography></div>
    {error && <Alert severity="error">{error}</Alert>}
    <Card variant="outlined"><CardContent><Typography variant="h6">{editingId ? 'Edit ServiceNow configuration' : 'Configure ServiceNow'}</Typography><Grid container spacing={1.5} mt={0.5}>
      <Grid size={{ xs: 12 }}><TextField fullWidth label="Instance URL" placeholder="https://instance.service-now.com" value={form.instance_url} onChange={(event) => setForm({ ...form, instance_url: event.target.value })}/></Grid>
      <Grid size={{ xs: 12, md: 6 }}><TextField fullWidth label="Username" autoComplete="username" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })}/></Grid>
      <Grid size={{ xs: 12, md: 6 }}><TextField fullWidth label={editingId ? 'Password (leave blank to keep saved password)' : 'Password'} type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })}/></Grid>
      <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth label="Synchronization interval (seconds)" type="number" value={form.sync_interval_seconds} onChange={(event) => setForm({ ...form, sync_interval_seconds: Number(event.target.value) })}/></Grid>
      <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth label="Request timeout (seconds)" type="number" value={form.request_timeout_seconds} onChange={(event) => setForm({ ...form, request_timeout_seconds: Number(event.target.value) })}/></Grid>
      <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth label="Page size" type="number" value={form.page_size} onChange={(event) => setForm({ ...form, page_size: Number(event.target.value) })}/></Grid>
      <Grid size={{ xs: 12 }}><Stack direction="row" flexWrap="wrap"><FormControlLabel control={<Checkbox checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })}/>} label="Enabled"/><FormControlLabel control={<Checkbox checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })}/>} label="Verify TLS certificate"/></Stack></Grid>
    </Grid></CardContent><CardActions><Button variant="contained" disabled={busy || !form.instance_url || !form.username || (!editingId && !form.password)} onClick={() => void save()}>Save</Button>{editingId && <Button onClick={() => { setEditingId(null); setForm(empty); }}>Cancel</Button>}</CardActions></Card>
    {loading ? <LoadingState label="Loading ServiceNow configuration"/> : <Grid container spacing={2}>{items.map((item) => <Grid key={item.id} size={{ xs: 12 }}><Card variant="outlined"><CardContent><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={2}><div><Typography fontWeight={750}>{item.instance_url}</Typography><Stack direction="row" spacing={1} mt={1}><Chip size="small" label={item.enabled ? 'Enabled' : 'Disabled'} color={item.enabled ? 'success' : 'default'}/><Chip size="small" label={item.connected ? 'Connected' : item.configured ? 'Configured' : 'Not configured'} color={item.connected ? 'success' : item.connection_state === 'failed' ? 'error' : 'default'}/></Stack></div><div><Typography variant="body2">Last test: {formatTimestamp(item.last_successful_test_at)}</Typography><Typography variant="body2">Last sync: {formatTimestamp(item.last_successful_sync_at)}</Typography></div></Stack>{item.last_sync_error && <Alert severity="warning" sx={{ mt: 2 }}>{item.last_sync_error}</Alert>}<Stack direction="row" flexWrap="wrap" gap={1} mt={2}>{Object.entries(item.counts).map(([name, count]) => <Chip size="small" variant="outlined" key={name} label={`${name.replaceAll('_', ' ')}: ${count}`}/>)}</Stack></CardContent><CardActions><Button onClick={() => edit(item)}>Configure</Button><Button disabled={busy || !item.enabled} onClick={() => void act(item, 'test')}>Test connection</Button><Button disabled={busy || !item.enabled} onClick={() => void act(item, 'sync')}>Run synchronization now</Button>{item.enabled && <Button color="warning" disabled={busy} onClick={() => void disable(item)}>Disable integration</Button>}</CardActions></Card></Grid>)}</Grid>}
    {!loading && items.length === 0 && <Alert severity="info">ServiceNow is not configured.</Alert>}
  </Stack>;
}
