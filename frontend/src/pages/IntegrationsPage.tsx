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
  TableCell, TableContainer, TableHead, TableRow, Tabs, TextField,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type {
  ConnectorIntegration, IntegrationCatalogItem, LokiConfiguration,
  ManagedDocumentSource, PrometheusConfiguration, ZammadConfiguration,
  ServiceNowConfiguration, IntegrationStream, IntegrationStreamSource,
} from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { timestampDisplay } from '../utils/time';
import {
  buildSourceCards, filterSourceCards, streamOrder, type SourceCardModel,
} from './integrationSourceModels';

type IntegrationTab = 'catalog' | 'data-sync';
interface SyncRow {
  key: string; integration: string; dataType: string; status: string;
  lastSync: string | null; records: number | null; nextSync: string | null;
  lastAttempt?: string | null;
  lastError: string | null; actionLabel?: string; action?: () => Promise<unknown>;
  detailsPath: string; recordDetailsPath?: string;
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
function when(value: string | null) {
  return value ? timestampDisplay(value, Date.now(), 'Never').relative : 'Never';
}

function normalizedTab(value: string | null): IntegrationTab {
  return value === 'data-sync' ? value : 'catalog';
}

function healthLabel(status: string) {
  const labels: Record<string, string> = {
    healthy: 'Healthy', attention: 'Degraded', unavailable: 'Unavailable',
    syncing: 'Syncing', configured: 'Configured', failed: 'Error', error: 'Error',
  };
  return labels[status] ?? status.replaceAll('_', ' ').replace(/^./, (value) => value.toUpperCase());
}

export function IntegrationsPage() {
  const navigate = useNavigate(); const toast = useToast();
  const [params, setParams] = useSearchParams(); const tab = normalizedTab(params.get('tab'));
  const [catalog, setCatalog] = useState<IntegrationCatalogItem[]>([]);
  const [items, setItems] = useState<ConnectorIntegration[]>([]);
  const [streams, setStreams] = useState<IntegrationStream[]>([]);
  const [syncRows, setSyncRows] = useState<SyncRow[]>([]);
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [search, setSearch] = useState(''); const [category, setCategory] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [configure, setConfigure] = useState<IntegrationCatalogItem | null>(null);
  const [editingIntegration, setEditingIntegration] = useState<ConnectorIntegration | null>(null);
  const [switching, setSwitching] = useState<{ stream: IntegrationStream; source: IntegrationStreamSource } | null>(null);

  const load = useCallback(async () => {
    try {
      const [catalogRows, integrations, streamRows] = await Promise.all([
        api.integrationCatalog(), api.integrations(), api.integrationStreams(),
      ]);
      setCatalog(catalogRows); setItems(integrations); setStreams(streamRows); setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Integrations could not be loaded.');
    } finally { setLoading(false); }
  }, []);

  const loadSync = useCallback(async () => {
    const streamRows = await api.integrationStreams().catch(() => [] as IntegrationStream[]);
    const selected = new Map<string, IntegrationStreamSource>();
    streamRows.forEach((stream) => {
      const source = stream.sources.find((item) => item.selected);
      if (source) selected.set(source.source_key, source);
    });
    const selectedLegacyId = (sourceKey: string) => {
      const source = selected.get(sourceKey);
      const integration = items.find((item) => item.id === source?.integration_id);
      return String(integration?.configuration.legacy_id ?? '');
    };
    const [prometheus, loki, zammad, servicenow, documents, cmdb] = await Promise.allSettled([
      api.prometheusConfigurations(), api.lokiConfigurations(), api.zammadConfigurations(),
      api.serviceNowConfigurations(),
      api.documentSource(), api.cmdbDatasets(),
    ]);
    const rows: SyncRow[] = [];
    if (prometheus.status === 'fulfilled' && selected.has('prometheus')) prometheus.value.filter((item: PrometheusConfiguration) => !selectedLegacyId('prometheus') || item.id === selectedLegacyId('prometheus')).forEach((item: PrometheusConfiguration) => rows.push({ key: `prometheus:${item.id}`, integration: item.name, dataType: `Targets · healthy ${item.healthy_target_count} · unhealthy ${item.unhealthy_target_count}`, status: item.last_error ? 'Error' : item.last_successful_scan_at ? 'Healthy' : 'Configured', lastSync: item.last_successful_scan_at, records: item.target_count, nextSync: item.enabled ? `Every ${item.scan_interval_seconds}s` : null, lastError: item.last_error, actionLabel: 'Refresh targets', action: () => api.scanPrometheus(item.id), detailsPath: '/prometheus' }));
    if (zammad.status === 'fulfilled' && selected.has('zammad')) zammad.value.filter((item: ZammadConfiguration) => !selectedLegacyId('zammad') || item.id === selectedLegacyId('zammad')).forEach((item: ZammadConfiguration) => rows.push({ key: `zammad:${item.id}`, integration: item.name, dataType: 'Tickets', status: item.last_error ? 'Error' : item.connection_state === 'connected' ? 'Healthy' : 'Configured', lastSync: item.last_successful_sync_at, records: item.synchronized_ticket_count, nextSync: item.next_scheduled_sync_at, lastError: item.last_error, actionLabel: 'Run synchronization now', action: () => api.syncZammad(item.id), detailsPath: '/zammad' }));
    if (servicenow.status === 'fulfilled') servicenow.value.filter((item: ServiceNowConfiguration) => [selected.get('servicenow')?.integration_id, selected.get('servicenow_cmdb')?.integration_id].includes(item.integration_id)).forEach((item: ServiceNowConfiguration) => rows.push({ key: `servicenow:${item.id}`, integration: 'ServiceNow', dataType: `${[selected.get('servicenow')?.integration_id === item.integration_id ? 'Ticketing' : null, selected.get('servicenow_cmdb')?.integration_id === item.integration_id ? 'CMDB' : null].filter(Boolean).join(' & ')} · every ${Math.round(item.sync_interval_seconds / 60)} min`, status: item.availability.freshness_state === 'error' ? 'Error' : item.availability.freshness_state === 'stale' ? 'Stale' : item.connected ? 'Healthy' : 'Configured', lastSync: item.last_successful_sync_at, lastAttempt: item.last_attempted_sync_at, records: Object.values(item.counts).reduce((sum, value) => sum + value, 0), nextSync: item.next_scheduled_sync_at, lastError: item.last_sync_error, actionLabel: 'Run synchronization now', action: () => api.syncServiceNow(item.id), detailsPath: '/servicenow', recordDetailsPath: `/servicenow/${item.id}/cmdb` }));
    if (loki.status === 'fulfilled' && selected.has('loki')) loki.value.filter((item: LokiConfiguration) => !selectedLegacyId('loki') || item.id === selectedLegacyId('loki')).forEach((item: LokiConfiguration) => rows.push({ key: `loki:${item.id}`, integration: item.name, dataType: 'Live log evidence', status: item.last_error ? 'Error' : item.last_successful_test_at ? 'Healthy' : 'Configured', lastSync: item.last_successful_discovery_at, records: item.stream_count, nextSync: 'Queried live', lastError: item.last_error, actionLabel: 'Refresh discovery', action: () => api.discoverLoki(item.id), detailsPath: '/loki' }));
    if (documents.status === 'fulfilled' && selected.has('documents')) { const item = documents.value as ManagedDocumentSource; rows.push({ key: `documents:${item.id}`, integration: item.name, dataType: 'Knowledge files', status: item.last_error ? 'Error' : item.health_status === 'healthy' ? 'Healthy' : 'Configured', lastSync: item.last_scan_at, records: item.discovered_document_count, nextSync: item.next_scheduled_scan_at, lastError: item.last_error, actionLabel: 'Run indexing now', action: () => api.scanDocuments(), detailsPath: '/documents' }); }
    if (cmdb.status === 'fulfilled' && selected.has('local_cmdb')) cmdb.value.forEach((item) => rows.push({ key: `cmdb:${item.id}`, integration: 'Local CMDB', dataType: 'Assets', status: item.status === 'active' ? 'Healthy' : healthLabel(item.status), lastSync: item.imported_at, records: item.valid_rows, nextSync: 'Imported manually', lastError: item.invalid_rows ? `${item.invalid_rows} invalid rows` : null, detailsPath: '/cmdb' }));
    setSyncRows(rows);
  }, [items]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (tab === 'data-sync') void loadSync(); }, [tab, loadSync]);
  const act = async (operation: () => Promise<unknown>, success: string, refreshSync = false) => {
    try { await operation(); toast.show(success, 'success'); await load(); if (refreshSync) await loadSync(); }
    catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Action failed.', 'error'); }
  };
  const openConfiguration = (integrationType: string, integration?: ConnectorIntegration) => {
    const route = dedicatedRoutes[integrationType];
    if (route) navigate(route);
    else { setEditingIntegration(integration ?? null); setConfigure(catalog.find((entry) => entry.integration_type === integrationType) ?? null); }
  };
  const activate = async (stream: IntegrationStream, source: IntegrationStreamSource, confirmed = false) => {
    try {
      await api.selectIntegrationSource(source.integration_id, stream.stream, confirmed);
      setSwitching(null); toast.show(`${source.source_name} is now selected for ${stream.display_name}.`, 'success'); await load();
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'SOURCE_SWITCH_CONFIRMATION_REQUIRED') {
        setSwitching({ stream, source }); return;
      }
      toast.show(reason instanceof Error ? reason.message : 'Source activation failed.', 'error');
    }
  };
  if (loading) return <LoadingState label="Loading integrations" />;
  return <Stack spacing={2}>
    <Box><Typography variant="h4" fontWeight={800}>Integrations</Typography><Typography color="text.secondary">Configure sources and choose one selected source for each stream.</Typography></Box>
    {error && <Alert severity="error">{error}</Alert>}
    <Paper variant="outlined"><Tabs value={tab} onChange={(_, value: IntegrationTab) => setParams({ tab: value })} aria-label="Integration sections"><Tab value="catalog" label="Sources" /><Tab value="data-sync" label="Data & Sync" /></Tabs></Paper>
    {tab === 'catalog' && <SourcesTab catalog={catalog} items={items} streams={streams} search={search} category={category} status={statusFilter} onSearch={setSearch} onCategory={setCategory} onStatus={setStatusFilter} onConfigure={openConfiguration} onSelect={activate} onTest={(item) => act(() => api.testIntegration(item.id), 'Connection test completed.')} />}
    {tab === 'data-sync' && <DataSyncTab rows={syncRows} onAction={act} onNavigate={navigate} />}
    <ConfigurationDialog catalog={configure} integration={editingIntegration} onClose={() => { setConfigure(null); setEditingIntegration(null); }} onSaved={async () => { setConfigure(null); setEditingIntegration(null); await load(); }} />
    <Dialog open={Boolean(switching)} onClose={() => setSwitching(null)}><DialogTitle>Switch selected source?</DialogTitle><DialogContent>{switching && <Stack spacing={1}><Typography><strong>{switching.stream.sources.find((source) => source.selected)?.source_name}</strong> is currently selected as the {switching.stream.display_name} source.</Typography><Typography>Switching to <strong>{switching.source.source_name}</strong> will stop PEKA from using the current source for {switching.stream.display_name} and will select {switching.source.source_name}. Saved configuration will be retained.</Typography></Stack>}</DialogContent><DialogActions><Button onClick={() => setSwitching(null)}>Cancel</Button><Button variant="contained" onClick={() => switching && void activate(switching.stream, switching.source, true)}>Switch to {switching?.source.source_name}</Button></DialogActions></Dialog>
  </Stack>;
}

export function SourcesTab({ catalog, items, streams, search, category, status, onSearch, onCategory, onStatus, onConfigure, onSelect, onTest }: { catalog: IntegrationCatalogItem[]; items: ConnectorIntegration[]; streams: IntegrationStream[]; search: string; category: string; status: string; onSearch: (value: string) => void; onCategory: (value: string) => void; onStatus: (value: string) => void; onConfigure: (type: string, integration?: ConnectorIntegration) => void; onSelect: (stream: IntegrationStream, source: IntegrationStreamSource) => Promise<void>; onTest: (item: ConnectorIntegration) => Promise<void> }) {
  const cards = useMemo(() => buildSourceCards(catalog, items, streams), [catalog, items, streams]);
  const visible = useMemo(() => filterSourceCards(cards, search, category, status), [cards, search, category, status]);
  const sections = streamOrder.filter((section) => visible.some((card) => card.section === section));
  const categories = ['All', ...streamOrder.filter((section) => cards.some((card) => card.section === section))];
  return <Stack spacing={2.5} sx={{ width: '100%', maxWidth: 1200 }}>
    <Paper variant="outlined" sx={{ p: 1.5 }}><Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25}>
      <TextField size="small" label="Search integrations" value={search} onChange={(event) => onSearch(event.target.value)} sx={{ minWidth: { md: 280 } }} />
      <FormControl size="small" sx={{ minWidth: 170 }}><InputLabel>Stream</InputLabel><Select label="Stream" value={category} onChange={(event) => onCategory(event.target.value)}>{categories.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl>
      <FormControl size="small" sx={{ minWidth: 170 }}><InputLabel>Status</InputLabel><Select label="Status" value={status} onChange={(event) => onStatus(event.target.value)}>{['All', 'Active', 'Inactive', 'Coming soon'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl>
    </Stack></Paper>
    {sections.map((section) => {
      const sectionCards = visible.filter((card) => card.section === section);
      const stream = streams.find((item) => item.display_name === section);
      const active = stream?.sources.find((source) => source.selected);
      return <Stack key={section} component="section" spacing={1.25} aria-labelledby={`stream-${section.toLowerCase()}`}>
        <Stack spacing={0.125} sx={{ borderBottom: 1, borderColor: 'divider', pb: 0.75 }}>
          <Typography id={`stream-${section.toLowerCase()}`} variant="h6" fontWeight={750} lineHeight={1.3}>{section}</Typography>
          {active && <Typography variant="body2" color="text.secondary">Active source: {active.source_name}</Typography>}
        </Stack>
        <Grid container spacing={1.5}>{sectionCards.map((card) => <SourceCard key={card.key} card={card} onConfigure={onConfigure} onSelect={onSelect} onTest={onTest} />)}</Grid>
      </Stack>;
    })}
    {visible.length === 0 && <Alert severity="info">No sources match the selected filters.</Alert>}
  </Stack>;
}

function SourceCard({ card, onConfigure, onSelect, onTest }: { card: SourceCardModel; onConfigure: (type: string, integration?: ConnectorIntegration) => void; onSelect: (stream: IntegrationStream, source: IntegrationStreamSource) => Promise<void>; onTest: (item: ConnectorIntegration) => Promise<void> }) {
  const activityLabel: Record<string, string> = {
    prometheus: 'observation', servicenow: 'sync', servicenow_cmdb: 'sync',
    zammad: 'sync', loki: 'activity', documents: 'index', local_cmdb: 'import',
  };
  const sourceKey = card.source?.source_key ?? card.catalog.integration_type;
  const sourceHealth = card.source ? healthLabel(card.source.status) : null;
  const statusColor = card.state === 'Active' ? 'success' : 'default';
  const operationalLine = card.state === 'Inactive' ? 'Configuration retained'
    : card.source?.last_error ? card.source.last_error
      : card.source?.last_successful_sync_at ? `${sourceHealth} · Last ${activityLabel[sourceKey] ?? 'activity'} ${when(card.source.last_successful_sync_at)}`
        : card.state === 'Active' ? sourceHealth ?? 'Ready for PEKA requests'
          : card.state === 'Coming soon' ? card.catalog.unavailable_reason
            : card.integration ? 'Configuration retained' : 'Ready to configure';
  return <Grid size={{ xs: 12, md: 6 }}><Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column', borderColor: card.state === 'Active' ? 'success.light' : 'divider' }}>
    <CardContent sx={{ pb: 0.5, flex: 1 }}><Stack direction="row" spacing={1.25} alignItems="flex-start"><Box color={card.state === 'Active' ? 'primary.main' : 'text.secondary'} aria-hidden="true" sx={{ display: 'flex', mt: 0.25 }}>{icons[card.catalog.integration_type]}</Box><Box sx={{ flex: 1, minWidth: 0 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}><Typography fontWeight={750}>{card.name}</Typography><Chip size="small" label={card.state} color={statusColor} variant={card.state === 'Active' ? 'filled' : 'outlined'} /></Stack>
      <Typography variant="body2" color="text.secondary" mt={0.375}>{card.description}</Typography>
      <Typography variant="caption" color={card.source?.last_error ? 'error' : 'text.secondary'} sx={{ display: 'block', mt: 1 }}>{operationalLine}</Typography>
    </Box></Stack></CardContent>
    {card.catalog.available && <CardActions sx={{ pt: 0, px: 1.5, pb: 1, flexWrap: 'wrap' }}>
      <Button size="small" onClick={() => onConfigure(card.catalog.integration_type, card.integration)}>Configure</Button>
      {card.source && card.stream && !card.source.selected && <Button size="small" onClick={() => void onSelect(card.stream!, card.source!)}>{card.stream.sources.some((source) => source.selected) ? `Switch to ${card.name}` : `Select ${card.name}`}</Button>}
      {card.integration && ['prometheus', 'loki', 'zammad', 'servicenow'].includes(card.catalog.integration_type) && <Button size="small" onClick={() => void onTest(card.integration!)}>Test connection</Button>}
    </CardActions>}
  </Card></Grid>;
}

function DataSyncTab({ rows, onAction, onNavigate }: { rows: SyncRow[]; onAction: (operation: () => Promise<unknown>, success: string, refreshSync?: boolean) => Promise<void>; onNavigate: (path: string) => void }) {
  if (!rows.length) return <Alert severity="info">No configured integration data is available.</Alert>;
  return <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Source</TableCell><TableCell>Data</TableCell><TableCell>Status</TableCell><TableCell>Last successful sync</TableCell><TableCell>Last attempted sync</TableCell><TableCell>Records</TableCell><TableCell>Next sync</TableCell><TableCell>Last error</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{rows.map((row) => <TableRow key={row.key}><TableCell><Typography fontWeight={650}>{row.integration}</Typography></TableCell><TableCell>{row.dataType}</TableCell><TableCell><Chip size="small" label={row.status} color={row.status === 'Healthy' ? 'success' : row.status === 'Error' ? 'error' : row.status === 'Stale' ? 'warning' : 'default'} /></TableCell><TableCell>{when(row.lastSync)}</TableCell><TableCell>{row.lastAttempt === undefined ? '—' : when(row.lastAttempt)}</TableCell><TableCell>{row.records ?? '—'}</TableCell><TableCell>{row.nextSync?.includes('T') ? when(row.nextSync) : row.nextSync ?? '—'}</TableCell><TableCell><Typography variant="body2" color={row.lastError ? 'error' : 'text.secondary'} noWrap sx={{ maxWidth: 220 }}>{row.lastError ?? '—'}</Typography></TableCell><TableCell align="right"><Stack direction="row" justifyContent="flex-end" spacing={0.5}>{row.action && <Button size="small" onClick={() => void onAction(row.action!, `${row.integration} synchronization completed.`, true)}>{row.actionLabel}</Button>}{row.recordDetailsPath && <Button size="small" onClick={() => onNavigate(row.recordDetailsPath!)}>View CMDB records</Button>}<Button size="small" onClick={() => onNavigate(row.detailsPath)}>View details</Button></Stack></TableCell></TableRow>)}</TableBody></Table></TableContainer>;
}

function ConfigurationDialog({ catalog, integration, onClose, onSaved }: { catalog: IntegrationCatalogItem | null; integration: ConnectorIntegration | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const toast = useToast(); const [name, setName] = useState(''); const [values, setValues] = useState<Record<string, string | boolean>>({ validate_tls: true }); const [capabilities, setCapabilities] = useState<Record<string, boolean>>({});
  useEffect(() => { if (catalog) { setName(integration?.display_name ?? catalog.name); setValues({ validate_tls: true, ...(integration?.configuration ?? {}) } as Record<string, string | boolean>); setCapabilities({ ...(integration?.capabilities ?? catalog.capabilities) }); } }, [catalog, integration]);
  const save = async () => { if (!catalog || !catalog.available) return; try { if (integration) await api.updateIntegration(integration.id, { display_name: name, configuration: values, capabilities }); else await api.createIntegration({ integration_type: catalog.integration_type, display_name: name, enabled: true, configuration: values, capabilities }); toast.show(`${catalog.name} integration saved.`, 'success'); await onSaved(); } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Integration could not be saved.', 'error'); } };
  return <Dialog open={Boolean(catalog)} onClose={onClose} fullWidth maxWidth="sm"><DialogTitle>Configure {catalog?.name}</DialogTitle><DialogContent><Stack spacing={1.5} mt={1}><TextField size="small" label="Display name" value={name} onChange={(event) => setName(event.target.value)} />{catalog?.configuration_fields.map((field) => field === 'validate_tls' ? <FormControlLabel key={field} control={<Checkbox checked={values[field] !== false} onChange={(event) => setValues({ ...values, [field]: event.target.checked })} />} label="Validate TLS certificate" /> : <TextField size="small" key={field} label={field.replaceAll('_', ' ')} type={secretFields.has(field) ? 'password' : 'text'} value={String(values[field] ?? '')} onChange={(event) => setValues({ ...values, [field]: event.target.value })} />)}<Typography variant="subtitle2">Capabilities</Typography>{catalog && Object.keys(catalog.capabilities).map((capability) => <FormControlLabel key={capability} control={<Checkbox checked={capabilities[capability] ?? false} onChange={(event) => setCapabilities({ ...capabilities, [capability]: event.target.checked })} />} label={capability.replaceAll('_', ' ')} />)}</Stack></DialogContent><DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={!catalog?.available} onClick={() => void save()}>Save integration</Button></DialogActions></Dialog>;
}
