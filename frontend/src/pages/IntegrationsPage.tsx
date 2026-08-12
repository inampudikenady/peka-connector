import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined';
import ConfirmationNumberOutlinedIcon from '@mui/icons-material/ConfirmationNumberOutlined';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import QueryStatsOutlinedIcon from '@mui/icons-material/QueryStatsOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import ViewInArOutlinedIcon from '@mui/icons-material/ViewInArOutlined';
import {
  Alert, Box, Button, Card, CardActions, CardContent, Checkbox, Chip, Dialog,
  DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel,
  Grid, InputLabel, MenuItem, Paper, Select, Stack, Tab, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Tabs, TextField, Tooltip,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type {
  ConnectorIntegration, IntegrationCatalogItem, LokiConfiguration,
  ManagedDocumentSource, PrometheusConfiguration, ZammadConfiguration,
  ServiceNowConfiguration,
} from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { timestampDisplay } from '../utils/time';

type IntegrationTab = 'catalog' | 'configured' | 'data-sync';
interface SyncRow {
  key: string; integration: string; dataType: string; status: string;
  lastSync: string | null; records: number | null; nextSync: string | null;
  lastError: string | null; actionLabel?: string; action?: () => Promise<unknown>;
  detailsPath: string;
}

const dedicatedRoutes: Record<string, string> = {
  prometheus: '/prometheus', loki: '/loki', zammad: '/zammad',
  servicenow: '/servicenow',
  generic_cmdb: '/cmdb', documents: '/documents',
};
const secretFields = new Set(['access_token', 'password', 'client_secret', 'token']);
const icons: Record<string, ReactNode> = {
  prometheus: <QueryStatsOutlinedIcon />, loki: <DnsOutlinedIcon />,
  zammad: <ConfirmationNumberOutlinedIcon />, servicenow: <HubOutlinedIcon />,
  solarwinds: <StorageOutlinedIcon />, vmware_vcenter: <ViewInArOutlinedIcon />,
  generic_cmdb: <Inventory2OutlinedIcon />, documents: <ArticleOutlinedIcon />,
};
const descriptions: Record<string, string> = {
  prometheus: 'Targets, metrics and infrastructure health',
  loki: 'Live operational log evidence', zammad: 'Tickets and asset relationships',
  servicenow: 'Incidents, changes and CMDB', solarwinds: 'Nodes, alerts and performance',
  vmware_vcenter: 'Virtual infrastructure and datastore capacity',
  generic_cmdb: 'Imported asset inventory', documents: 'Knowledge files and delivery',
};

function when(value: string | null) {
  return value ? timestampDisplay(value, Date.now(), 'Never').relative : 'Never';
}

function normalizedTab(value: string | null): IntegrationTab {
  return value === 'configured' || value === 'data-sync' ? value : 'catalog';
}

function healthLabel(status: string) {
  const labels: Record<string, string> = {
    healthy: 'Healthy', attention: 'Degraded', unavailable: 'Unavailable',
    syncing: 'Syncing', configured: 'Configured', failed: 'Error', error: 'Error',
  };
  return labels[status] ?? status.replaceAll('_', ' ').replace(/^./, (value) => value.toUpperCase());
}

function configuredSync(item: ConnectorIntegration): (() => Promise<unknown>) | null {
  const legacyId = String(item.configuration.legacy_id ?? '');
  if (item.integration_type === 'zammad') return () => api.syncIntegration(item.id);
  if (item.integration_type === 'servicenow') return () => api.syncIntegration(item.id);
  if (item.integration_type === 'prometheus' && legacyId) return () => api.scanPrometheus(legacyId);
  if (item.integration_type === 'documents') return () => api.scanDocuments();
  return null;
}

export function IntegrationsPage() {
  const navigate = useNavigate(); const toast = useToast();
  const [params, setParams] = useSearchParams(); const tab = normalizedTab(params.get('tab'));
  const [catalog, setCatalog] = useState<IntegrationCatalogItem[]>([]);
  const [items, setItems] = useState<ConnectorIntegration[]>([]);
  const [syncRows, setSyncRows] = useState<SyncRow[]>([]);
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [search, setSearch] = useState(''); const [category, setCategory] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [configure, setConfigure] = useState<IntegrationCatalogItem | null>(null);
  const [editingIntegration, setEditingIntegration] = useState<ConnectorIntegration | null>(null);

  const load = useCallback(async () => {
    try {
      const [catalogRows, integrations] = await Promise.all([
        api.integrationCatalog(), api.integrations(),
      ]);
      setCatalog(catalogRows); setItems(integrations); setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Integrations could not be loaded.');
    } finally { setLoading(false); }
  }, []);

  const loadSync = useCallback(async () => {
    const [prometheus, loki, zammad, servicenow, documents, cmdb] = await Promise.allSettled([
      api.prometheusConfigurations(), api.lokiConfigurations(), api.zammadConfigurations(),
      api.serviceNowConfigurations(),
      api.documentSource(), api.cmdbDatasets(),
    ]);
    const rows: SyncRow[] = [];
    if (prometheus.status === 'fulfilled') prometheus.value.forEach((item: PrometheusConfiguration) => rows.push({ key: `prometheus:${item.id}`, integration: item.name, dataType: 'Targets', status: item.last_error ? 'Error' : item.last_successful_scan_at ? 'Healthy' : 'Configured', lastSync: item.last_successful_scan_at, records: item.target_count, nextSync: item.enabled ? `Every ${item.scan_interval_seconds}s` : null, lastError: item.last_error, actionLabel: 'Sync now', action: () => api.scanPrometheus(item.id), detailsPath: '/prometheus' }));
    if (zammad.status === 'fulfilled') zammad.value.forEach((item: ZammadConfiguration) => rows.push({ key: `zammad:${item.id}`, integration: item.name, dataType: 'Tickets', status: item.last_error ? 'Error' : item.connection_state === 'connected' ? 'Healthy' : 'Configured', lastSync: item.last_successful_sync_at, records: item.synchronized_ticket_count, nextSync: item.next_scheduled_sync_at, lastError: item.last_error, actionLabel: item.enabled ? 'Sync now' : undefined, action: item.enabled ? () => api.syncZammad(item.id) : undefined, detailsPath: '/zammad' }));
    if (servicenow.status === 'fulfilled') servicenow.value.forEach((item: ServiceNowConfiguration) => rows.push({ key: `servicenow:${item.id}`, integration: 'ServiceNow', dataType: 'CMDB & ITSM', status: item.last_sync_error ? 'Error' : item.connected ? 'Healthy' : 'Configured', lastSync: item.last_successful_sync_at, records: Object.values(item.counts).reduce((sum, value) => sum + value, 0), nextSync: item.next_scheduled_sync_at, lastError: item.last_sync_error, actionLabel: item.enabled ? 'Sync now' : undefined, action: item.enabled ? () => api.syncServiceNow(item.id) : undefined, detailsPath: '/servicenow' }));
    if (loki.status === 'fulfilled') loki.value.forEach((item: LokiConfiguration) => rows.push({ key: `loki:${item.id}`, integration: item.name, dataType: 'Live evidence', status: item.last_error ? 'Error' : item.last_successful_test_at ? 'Healthy' : 'Configured', lastSync: item.last_successful_discovery_at, records: item.stream_count, nextSync: 'Queried live', lastError: item.last_error, actionLabel: 'Refresh discovery', action: () => api.discoverLoki(item.id), detailsPath: '/loki' }));
    if (documents.status === 'fulfilled') { const item = documents.value as ManagedDocumentSource; rows.push({ key: `documents:${item.id}`, integration: item.name, dataType: 'Files', status: item.last_error ? 'Error' : item.health_status === 'healthy' ? 'Healthy' : 'Configured', lastSync: item.last_scan_at, records: item.discovered_document_count, nextSync: item.next_scheduled_scan_at, lastError: item.last_error, actionLabel: item.enabled ? 'Sync now' : undefined, action: item.enabled ? () => api.scanDocuments() : undefined, detailsPath: '/documents' }); }
    if (cmdb.status === 'fulfilled') cmdb.value.forEach((item) => rows.push({ key: `cmdb:${item.id}`, integration: item.name, dataType: 'Assets', status: item.status === 'active' ? 'Healthy' : healthLabel(item.status), lastSync: item.imported_at, records: item.valid_rows, nextSync: 'Imported manually', lastError: item.invalid_rows ? `${item.invalid_rows} invalid rows` : null, detailsPath: '/cmdb' }));
    setSyncRows(rows);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (tab === 'data-sync') void loadSync(); }, [tab, loadSync]);
  const categories = ['All', ...Array.from(new Set(catalog.map((item) => item.category)))];
  const filtered = useMemo(() => catalog.filter((item) => {
    const configured = items.some((integration) => integration.integration_type === item.integration_type);
    const state = !item.available ? 'Unavailable' : configured ? 'Configured' : 'Available';
    return (category === 'All' || item.category === category)
      && (statusFilter === 'All' || state === statusFilter)
      && `${item.name} ${item.category} ${descriptions[item.integration_type] ?? ''}`.toLowerCase().includes(search.toLowerCase());
  }), [catalog, items, category, statusFilter, search]);
  const act = async (operation: () => Promise<unknown>, success: string, refreshSync = false) => {
    try { await operation(); toast.show(success, 'success'); await load(); if (refreshSync) await loadSync(); }
    catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Action failed.', 'error'); }
  };
  const openConfiguration = (integrationType: string, integration?: ConnectorIntegration) => {
    const route = dedicatedRoutes[integrationType];
    if (route) navigate(route);
    else { setEditingIntegration(integration ?? null); setConfigure(catalog.find((entry) => entry.integration_type === integrationType) ?? null); }
  };
  if (loading) return <LoadingState label="Loading integrations" />;
  return <Stack spacing={2}>
    <Box><Typography variant="h4" fontWeight={800}>Integrations</Typography><Typography color="text.secondary">Configure providers and review synchronized connector data.</Typography></Box>
    {error && <Alert severity="error">{error}</Alert>}
    <Paper variant="outlined"><Tabs value={tab} onChange={(_, value: IntegrationTab) => setParams({ tab: value })} aria-label="Integration sections"><Tab value="catalog" label="Catalog" /><Tab value="configured" label="Configured" /><Tab value="data-sync" label="Data & Sync" /></Tabs></Paper>
    {tab === 'catalog' && <CatalogTab catalog={filtered} items={items} search={search} category={category} status={statusFilter} categories={categories} onSearch={setSearch} onCategory={setCategory} onStatus={setStatusFilter} onConfigure={openConfiguration} />}
    {tab === 'configured' && <ConfiguredTab items={items} catalog={catalog} onConfigure={openConfiguration} onAction={act} />}
    {tab === 'data-sync' && <DataSyncTab rows={syncRows} onAction={act} onNavigate={navigate} />}
    <ConfigurationDialog catalog={configure} integration={editingIntegration} onClose={() => { setConfigure(null); setEditingIntegration(null); }} onSaved={async () => { setConfigure(null); setEditingIntegration(null); await load(); }} />
  </Stack>;
}

function CatalogTab({ catalog, items, search, category, status, categories, onSearch, onCategory, onStatus, onConfigure }: { catalog: IntegrationCatalogItem[]; items: ConnectorIntegration[]; search: string; category: string; status: string; categories: string[]; onSearch: (value: string) => void; onCategory: (value: string) => void; onStatus: (value: string) => void; onConfigure: (type: string, integration?: ConnectorIntegration) => void }) {
  return <Stack spacing={2}><Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}><TextField size="small" label="Search integrations" value={search} onChange={(event) => onSearch(event.target.value)} sx={{ minWidth: 260 }} /><FormControl size="small" sx={{ minWidth: 170 }}><InputLabel>Category</InputLabel><Select label="Category" value={category} onChange={(event) => onCategory(event.target.value)}>{categories.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl><FormControl size="small" sx={{ minWidth: 170 }}><InputLabel>Status</InputLabel><Select label="Status" value={status} onChange={(event) => onStatus(event.target.value)}>{['All', 'Available', 'Configured', 'Unavailable'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl></Stack><Grid container spacing={1.5}>{catalog.map((entry) => { const configured = items.find((item) => item.integration_type === entry.integration_type); return <Grid key={entry.integration_type} size={{ xs: 12, sm: 6, lg: 4 }}><Card variant="outlined" sx={{ height: '100%' }}><CardContent sx={{ pb: 1 }}><Stack direction="row" spacing={1.25}><Box color="primary.main">{icons[entry.integration_type]}</Box><Box sx={{ flex: 1 }}><Stack direction="row" justifyContent="space-between" gap={1}><Typography fontWeight={750}>{entry.name}</Typography><Chip size="small" label={entry.category} variant="outlined" /></Stack><Typography variant="body2" color="text.secondary" mt={0.5}>{descriptions[entry.integration_type]}</Typography><Stack direction="row" spacing={0.75} mt={1}>{!entry.available ? <Tooltip title={entry.unavailable_reason ?? 'The runtime adapter is not implemented.'}><Chip size="small" label="Adapter unavailable" color="default" /></Tooltip> : configured ? <><Chip size="small" label="Configured" /><Chip size="small" label={configured.enabled ? 'Enabled' : 'Disabled'} color={configured.enabled ? 'success' : 'default'} /></> : <Chip size="small" label="Available" color="info" />}</Stack></Box></Stack></CardContent><CardActions sx={{ pt: 0 }}>{entry.available ? <Button size="small" onClick={() => onConfigure(entry.integration_type, configured)}>{configured ? 'Configure' : 'Enable'}</Button> : <Tooltip title={entry.unavailable_reason ?? ''}><span><Button size="small" disabled>Coming soon</Button></span></Tooltip>}</CardActions></Card></Grid>; })}</Grid>{catalog.length === 0 && <Alert severity="info">No integrations match the selected filters.</Alert>}</Stack>;
}

function ConfiguredTab({ items, catalog, onConfigure, onAction }: { items: ConnectorIntegration[]; catalog: IntegrationCatalogItem[]; onConfigure: (type: string, item?: ConnectorIntegration) => void; onAction: (operation: () => Promise<unknown>, success: string) => Promise<void> }) {
  if (!items.length) return <Alert severity="info">No integrations are configured.</Alert>;
  return <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Integration</TableCell><TableCell>State</TableCell><TableCell>Health</TableCell><TableCell>Last sync</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{items.map((item) => { const available = catalog.find((entry) => entry.integration_type === item.integration_type)?.available !== false; const sync = configuredSync(item); const testable = ['prometheus', 'loki', 'zammad', 'servicenow'].includes(item.integration_type); return <TableRow key={item.id}><TableCell><Typography fontWeight={700}>{item.display_name}</Typography><Typography variant="caption" color="text.secondary">{item.category}</Typography></TableCell><TableCell><Chip size="small" label={item.enabled ? 'Enabled' : 'Disabled'} color={item.enabled ? 'success' : 'default'} /></TableCell><TableCell><Typography variant="body2">{item.enabled ? healthLabel(item.status) : 'Inactive'}</Typography>{item.enabled && item.initial_sync_status === 'pending' && <Typography variant="caption" color="warning.main">Initial sync pending</Typography>}</TableCell><TableCell>{when(item.last_successful_sync_at)}</TableCell><TableCell align="right"><Stack direction="row" justifyContent="flex-end" flexWrap="wrap" spacing={0.5}><Button size="small" disabled={!available} onClick={() => onConfigure(item.integration_type, item)}>Configure</Button><Button size="small" disabled={!available || !item.enabled || !testable} onClick={() => void onAction(() => api.testIntegration(item.id), 'Connection test completed.')}>Test connection</Button><Button size="small" disabled={!available || !item.enabled || !sync} onClick={() => sync && void onAction(sync, 'Synchronization completed.')}>Sync now</Button>{item.enabled ? <Button size="small" color="warning" onClick={() => void onAction(() => api.disableIntegration(item.id), 'Integration disabled.')}>Disable</Button> : <Button size="small" disabled={!available} onClick={() => void onAction(() => api.enableIntegration(item.id), 'Integration enabled.')}>Enable</Button>}</Stack></TableCell></TableRow>; })}</TableBody></Table></TableContainer>;
}

function DataSyncTab({ rows, onAction, onNavigate }: { rows: SyncRow[]; onAction: (operation: () => Promise<unknown>, success: string, refreshSync?: boolean) => Promise<void>; onNavigate: (path: string) => void }) {
  if (!rows.length) return <Alert severity="info">No configured integration data is available.</Alert>;
  return <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Integration</TableCell><TableCell>Data</TableCell><TableCell>Status</TableCell><TableCell>Last successful sync</TableCell><TableCell>Records</TableCell><TableCell>Next sync</TableCell><TableCell>Last error</TableCell><TableCell align="right">Action</TableCell></TableRow></TableHead><TableBody>{rows.map((row) => <TableRow key={row.key}><TableCell><Typography fontWeight={650}>{row.integration}</Typography></TableCell><TableCell>{row.dataType}</TableCell><TableCell><Chip size="small" label={row.status} color={row.status === 'Healthy' ? 'success' : row.status === 'Error' ? 'error' : 'default'} /></TableCell><TableCell>{when(row.lastSync)}</TableCell><TableCell>{row.records ?? '—'}</TableCell><TableCell>{row.nextSync?.includes('T') ? when(row.nextSync) : row.nextSync ?? '—'}</TableCell><TableCell><Typography variant="body2" color={row.lastError ? 'error' : 'text.secondary'} noWrap sx={{ maxWidth: 220 }}>{row.lastError ?? '—'}</Typography></TableCell><TableCell align="right"><Stack direction="row" justifyContent="flex-end" spacing={0.5}>{row.action && <Button size="small" onClick={() => void onAction(row.action!, `${row.integration} synchronization completed.`, true)}>{row.actionLabel}</Button>}<Button size="small" onClick={() => onNavigate(row.detailsPath)}>View details</Button></Stack></TableCell></TableRow>)}</TableBody></Table></TableContainer>;
}

function ConfigurationDialog({ catalog, integration, onClose, onSaved }: { catalog: IntegrationCatalogItem | null; integration: ConnectorIntegration | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const toast = useToast(); const [name, setName] = useState(''); const [values, setValues] = useState<Record<string, string | boolean>>({ validate_tls: true }); const [capabilities, setCapabilities] = useState<Record<string, boolean>>({});
  useEffect(() => { if (catalog) { setName(integration?.display_name ?? catalog.name); setValues({ validate_tls: true, ...(integration?.configuration ?? {}) } as Record<string, string | boolean>); setCapabilities({ ...(integration?.capabilities ?? catalog.capabilities) }); } }, [catalog, integration]);
  const save = async () => { if (!catalog || !catalog.available) return; try { if (integration) await api.updateIntegration(integration.id, { display_name: name, configuration: values, capabilities }); else await api.createIntegration({ integration_type: catalog.integration_type, display_name: name, enabled: true, configuration: values, capabilities }); toast.show(`${catalog.name} integration saved.`, 'success'); await onSaved(); } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Integration could not be saved.', 'error'); } };
  return <Dialog open={Boolean(catalog)} onClose={onClose} fullWidth maxWidth="sm"><DialogTitle>Configure {catalog?.name}</DialogTitle><DialogContent><Stack spacing={1.5} mt={1}><TextField size="small" label="Display name" value={name} onChange={(event) => setName(event.target.value)} />{catalog?.configuration_fields.map((field) => field === 'validate_tls' ? <FormControlLabel key={field} control={<Checkbox checked={values[field] !== false} onChange={(event) => setValues({ ...values, [field]: event.target.checked })} />} label="Validate TLS certificate" /> : <TextField size="small" key={field} label={field.replaceAll('_', ' ')} type={secretFields.has(field) ? 'password' : 'text'} value={String(values[field] ?? '')} onChange={(event) => setValues({ ...values, [field]: event.target.value })} />)}<Typography variant="subtitle2">Capabilities</Typography>{catalog && Object.keys(catalog.capabilities).map((capability) => <FormControlLabel key={capability} control={<Checkbox checked={capabilities[capability] ?? false} onChange={(event) => setCapabilities({ ...capabilities, [capability]: event.target.checked })} />} label={capability.replaceAll('_', ' ')} />)}</Stack></DialogContent><DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={!catalog?.available} onClick={() => void save()}>Save integration</Button></DialogActions></Dialog>;
}
