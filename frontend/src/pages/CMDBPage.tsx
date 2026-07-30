import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, IconButton, InputLabel, MenuItem, Paper, Select, Stack, Tab, Table,
  TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow,
  Tabs, TextField, Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api/client';
import type { CMDBDataset, CMDBRecord, CMDBUpload } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { cmdbImportMode } from '../utils/cmdb';
import { formatTimestamp, relativeTimestamp } from '../utils/time';

const defaultColumns = ['hostname', 'fqdn', 'primary_ip', 'asset_type', 'environment', 'operating_system', 'application', 'business_owner', 'technical_owner', 'lifecycle_status'];

export function CMDBImportModeField({
  datasets,
  selectedDatasetId,
  onChange,
}: {
  datasets: CMDBDataset[];
  selectedDatasetId: string;
  onChange: (datasetId: string) => void;
}) {
  const value = selectedDatasetId || 'create_new';
  return (
    <FormControl fullWidth>
      <InputLabel id="cmdb-import-mode-label">Import mode</InputLabel>
      <Select
        labelId="cmdb-import-mode-label"
        id="cmdb-import-mode"
        label="Import mode"
        value={value}
        disabled={datasets.length === 0}
        onChange={(event) =>
          onChange(event.target.value === 'create_new' ? '' : event.target.value)
        }
        inputProps={{ 'aria-label': 'Import mode' }}
      >
        <MenuItem value="create_new">Create new dataset</MenuItem>
        {datasets.map((item) => (
          <MenuItem key={item.id} value={item.id}>New version of {item.name}</MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

export function CMDBPage() {
  const { user } = useAuth();
  const admin = user?.role === 'administrator';
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState(0);
  const [datasets, setDatasets] = useState<CMDBDataset[]>([]);
  const [records, setRecords] = useState<CMDBRecord[]>([]);
  const [fields, setFields] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Array<{ id: string; name: string; mapping: Record<string, string> }>>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [validation, setValidation] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState('');
  const [replaceId, setReplaceId] = useState('');
  const [draft, setDraft] = useState<CMDBUpload | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [headerRow, setHeaderRow] = useState(1);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Record<string, string>[]>([]);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<CMDBDataset | null>(null);
  const [renaming, setRenaming] = useState<CMDBDataset | null>(null); const [renameValue, setRenameValue] = useState('');
  const [profileName, setProfileName] = useState(''); const [visibleColumns, setVisibleColumns] = useState(defaultColumns);

  const load = useCallback(async () => {
    try {
      setLoading(true); setError('');
      const query = new URLSearchParams({ page: String(page + 1), page_size: '25' });
      if (search) query.set('search', search);
      if (validation) query.set('validation_status', validation);
      const [nextDatasets, nextRecords, fieldResult, nextProfiles] = await Promise.all([
        api.cmdbDatasets(), api.cmdbRecords(query.toString()), api.cmdbFields(), api.cmdbMappingProfiles(),
      ]);
      setDatasets(nextDatasets); setRecords(nextRecords.items); setTotal(nextRecords.total); setFields(fieldResult.fields); setProfiles(nextProfiles);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'CMDB data could not be loaded'); }
    finally { setLoading(false); }
  }, [page, search, validation]);
  useEffect(() => { void load(); }, [load]);

  const upload = async () => {
    if (!file || !datasetName.trim()) return;
    try {
      setBusy(true);
      const result = await api.uploadCMDB(
        file,
        datasetName.trim(),
        cmdbImportMode(replaceId),
        replaceId || undefined,
      );
      setDraft(result); setSheet(result.sheets[0] ?? null); setHeaderRow(result.header_row);
      setMapping(result.suggested_mapping); setPreview(result.preview_rows); setTab(1);
      toast.show('CMDB file uploaded and parsed safely.', 'success');
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Upload failed', 'error'); }
    finally { setBusy(false); }
  };
  const refreshPreview = async (nextSheet = sheet, nextHeader = headerRow) => {
    if (!draft) return;
    try {
      setBusy(true);
      const result = await api.previewCMDB(draft.version_id, nextSheet, nextHeader);
      setPreview(result.preview_rows); setMapping(result.suggested_mapping);
      setDraft({ ...draft, headers: result.headers, detected_total_rows: result.detected_total_rows });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Preview failed', 'error'); }
    finally { setBusy(false); }
  };
  const importData = async () => {
    if (!draft) return;
    try {
      setBusy(true);
      const result = await api.importCMDB(draft.version_id, sheet, headerRow, mapping);
      toast.show(
        `Imported ${result.valid_rows} valid rows; ${result.invalid_rows} need review.`,
        'success',
      );
      setDraft(null); setFile(null); setDatasetName(''); setReplaceId(''); setTab(0); await load();
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Import failed', 'error'); }
    finally { setBusy(false); }
  };

  return <Stack spacing={3}>
    <Box><Typography variant="h4" fontWeight={800}>CMDB</Typography><Typography color="text.secondary">Declared inventory, ownership, and lifecycle data managed locally by this connector.</Typography></Box>
    <Paper variant="outlined"><Tabs value={tab} onChange={(_, value) => setTab(value)}><Tab label="Datasets" /><Tab label="Upload & map" disabled={!admin} /><Tab label="Records" /></Tabs></Paper>
    {error && <Alert severity="error">{error}</Alert>}
    {tab === 0 && (loading ? <LoadingState label="Loading CMDB datasets" /> : <Stack spacing={2}>
      {admin && <Button variant="contained" startIcon={<CloudUploadOutlinedIcon />} onClick={() => setTab(1)} sx={{ alignSelf: 'flex-start' }}>Import CMDB file</Button>}
      <Paper variant="outlined"><TableContainer><Table><TableHead><TableRow><TableCell>Dataset</TableCell><TableCell>Version</TableCell><TableCell>Source</TableCell><TableCell>Imported</TableCell><TableCell>Rows</TableCell><TableCell>Status</TableCell>{admin && <TableCell align="right">Actions</TableCell>}</TableRow></TableHead><TableBody>
        {datasets.map((item) => <TableRow key={item.id} hover><TableCell><Typography fontWeight={600}>{item.name}</Typography></TableCell><TableCell>{item.current_version ?? 'Draft'}</TableCell><TableCell>{item.source_filename ?? '—'}</TableCell><TableCell title={formatTimestamp(item.imported_at)}>{relativeTimestamp(item.imported_at)}</TableCell><TableCell>{item.valid_rows} valid / {item.invalid_rows} invalid</TableCell><TableCell><Chip size="small" label={item.status} color={item.status === 'active' ? 'success' : 'default'} /></TableCell>{admin && <TableCell align="right"><Button size="small" onClick={() => { setReplaceId(item.id); setDatasetName(item.name); setTab(1); }}>New version</Button><Button size="small" onClick={() => { setRenaming(item); setRenameValue(item.name); }}>Rename</Button><Button size="small" onClick={() => void api.retireCMDB(item.id).then(load)}>Retire</Button><IconButton color="error" aria-label={`Delete ${item.name}`} onClick={() => setDeleting(item)}><DeleteOutlineIcon /></IconButton></TableCell>}</TableRow>)}
        {datasets.length === 0 && <TableRow><TableCell colSpan={7}><Typography color="text.secondary">No CMDB datasets have been imported.</Typography></TableCell></TableRow>}
      </TableBody></Table></TableContainer></Paper>
    </Stack>)}
    {tab === 1 && admin && <Stack spacing={2}>
      {!draft ? <Paper variant="outlined" sx={{ p: 3 }}><Stack spacing={2}>
        <TextField label="Dataset name" value={datasetName} onChange={(event) => setDatasetName(event.target.value)} required helperText={!datasetName.trim() ? 'Dataset name is required.' : ' '} />
        <CMDBImportModeField datasets={datasets} selectedDatasetId={replaceId} onChange={(datasetId) => { setReplaceId(datasetId); const item = datasets.find((dataset) => dataset.id === datasetId); setDatasetName(item?.name ?? ''); }} />
        <input ref={input} hidden type="file" accept=".csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <Button variant="outlined" onClick={() => input.current?.click()}>{file ? file.name : 'Choose CSV or XLSX'}</Button>
        <Alert severity="info">Files are stored under the managed CMDB source directory. Formulas and external workbook links are never executed or fetched.</Alert>
        <Button variant="contained" disabled={!file || !datasetName.trim() || busy} onClick={() => void upload()}>Upload and preview</Button>
      </Stack></Paper> : <Stack spacing={2}>
        <Paper variant="outlined" sx={{ p: 3 }}><Stack spacing={2}><Typography variant="h6">Configure {draft.filename}</Typography>
          {draft.sheets.length > 0 && <FormControl><InputLabel>Worksheet</InputLabel><Select label="Worksheet" value={sheet ?? ''} onChange={(event) => { const value = event.target.value; setSheet(value); void refreshPreview(value, headerRow); }}>{draft.sheets.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}</Select></FormControl>}
          <TextField label="Header row" type="number" inputProps={{ min: 1 }} value={headerRow} onChange={(event) => setHeaderRow(Number(event.target.value))} onBlur={() => void refreshPreview()} />
          {profiles.length > 0 && <FormControl><InputLabel>Mapping profile</InputLabel><Select label="Mapping profile" value="" onChange={(event) => { const profile = profiles.find((item) => item.id === event.target.value); if (profile) setMapping(profile.mapping); }}><MenuItem value="">Select reusable profile</MenuItem>{profiles.map((profile) => <MenuItem key={profile.id} value={profile.id}>{profile.name}</MenuItem>)}</Select></FormControl>}
          <Typography variant="subtitle1" fontWeight={700}>Column mapping</Typography>
          {draft.headers.map((header) => <Stack key={header} direction={{ xs: 'column', sm: 'row' }} spacing={2}><TextField label="Source column" value={header} disabled fullWidth /><FormControl fullWidth><InputLabel>PEKA field</InputLabel><Select label="PEKA field" value={mapping[header] ?? 'ignored'} onChange={(event) => setMapping({ ...mapping, [header]: event.target.value })}><MenuItem value="ignored">Ignore</MenuItem>{fields.map((field) => <MenuItem key={field} value={field} disabled={Object.entries(mapping).some(([source, value]) => source !== header && value === field)}>{field}</MenuItem>)}</Select></FormControl></Stack>)}
          <Stack direction="row" spacing={1}><TextField size="small" label="Profile name" value={profileName} onChange={(event) => setProfileName(event.target.value)} /><Button disabled={!profileName.trim()} onClick={() => void api.saveCMDBMappingProfile(profileName.trim(), mapping).then(() => { setProfileName(''); toast.show('Mapping profile saved.', 'success'); return load(); })}>Save profile</Button></Stack>
        </Stack></Paper>
        <Paper variant="outlined"><TableContainer><Table size="small"><TableHead><TableRow>{draft.headers.map((header) => <TableCell key={header}>{header}</TableCell>)}</TableRow></TableHead><TableBody>{preview.slice(0, 10).map((row, index) => <TableRow key={index}>{draft.headers.map((header) => <TableCell key={header}>{row[header]}</TableCell>)}</TableRow>)}</TableBody></Table></TableContainer></Paper>
        <Stack direction="row" spacing={1}><Button onClick={() => setDraft(null)}>Cancel</Button><Button variant="contained" disabled={busy || !Object.values(mapping).some((value) => ['cloud_instance_id', 'serial_number', 'asset_tag', 'fqdn', 'hostname', 'primary_ip'].includes(value))} onClick={() => void importData()}>Validate and import {draft.detected_total_rows} rows</Button></Stack>
      </Stack>}
    </Stack>}
    {tab === 2 && <Stack spacing={2}><Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}><TextField label="Search records" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} /><FormControl sx={{ minWidth: 180 }}><InputLabel>Validation</InputLabel><Select label="Validation" value={validation} onChange={(event) => { setValidation(event.target.value); setPage(0); }}><MenuItem value="">All</MenuItem><MenuItem value="valid">Valid</MenuItem><MenuItem value="invalid">Invalid</MenuItem></Select></FormControl><FormControl sx={{ minWidth: 260 }}><InputLabel>Visible columns</InputLabel><Select multiple label="Visible columns" value={visibleColumns} onChange={(event) => setVisibleColumns(typeof event.target.value === 'string' ? event.target.value.split(',') : event.target.value)}>{defaultColumns.map((column) => <MenuItem key={column} value={column}>{column.replaceAll('_', ' ')}</MenuItem>)}</Select></FormControl></Stack>
      {loading ? <LoadingState label="Loading CMDB records" /> : <Paper variant="outlined"><TableContainer><Table size="small"><TableHead><TableRow>{visibleColumns.map((column) => <TableCell key={column}>{column.replaceAll('_', ' ')}</TableCell>)}<TableCell>Validation</TableCell><TableCell>Source row</TableCell><TableCell>Version</TableCell></TableRow></TableHead><TableBody>{records.map((record) => <TableRow key={record.id} hover>{visibleColumns.map((column) => <TableCell key={column}>{String(record.normalized_fields[column] ?? '—')}</TableCell>)}<TableCell><Chip size="small" label={record.validation_status} color={record.validation_status === 'valid' ? 'success' : 'error'} title={record.validation_errors.join(', ')} /></TableCell><TableCell>{record.source_row_number}</TableCell><TableCell>{record.dataset_version}</TableCell></TableRow>)}</TableBody></Table></TableContainer><TablePagination component="div" count={total} page={page} rowsPerPage={25} rowsPerPageOptions={[25]} onPageChange={(_, value) => setPage(value)} /></Paper>}
    </Stack>}
    <Dialog open={Boolean(deleting)} onClose={() => setDeleting(null)}><DialogTitle>Delete dataset?</DialogTitle><DialogContent><Typography>The dataset is hidden, while imported records and historical provenance remain preserved.</Typography></DialogContent><DialogActions><Button onClick={() => setDeleting(null)}>Cancel</Button><Button color="error" onClick={() => { if (deleting) void api.deleteCMDB(deleting.id).then(() => { setDeleting(null); return load(); }); }}>Delete</Button></DialogActions></Dialog>
    <Dialog open={Boolean(renaming)} onClose={() => setRenaming(null)}><DialogTitle>Rename dataset</DialogTitle><DialogContent><TextField autoFocus fullWidth sx={{ mt: 1 }} label="Dataset name" value={renameValue} onChange={(event) => setRenameValue(event.target.value)} /></DialogContent><DialogActions><Button onClick={() => setRenaming(null)}>Cancel</Button><Button variant="contained" disabled={!renameValue.trim()} onClick={() => { if (renaming) void api.renameCMDB(renaming.id, renameValue.trim()).then(() => { setRenaming(null); return load(); }); }}>Rename</Button></DialogActions></Dialog>
  </Stack>;
}
