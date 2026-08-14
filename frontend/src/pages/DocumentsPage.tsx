import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import ReplayOutlinedIcon from '@mui/icons-material/ReplayOutlined';
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControlLabel, Grid,
  IconButton, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TablePagination, TableRow, Tab, Tabs, TextField, Tooltip, Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api/client';
import type { DocumentUploadResult, ManagedDocument, ManagedDocumentSource } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { documentDeletionAction } from '../utils/documents';
import { formatTimestamp, relativeTimestamp } from '../utils/time';

const formatSize = (size: number) => size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
const label = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
export const DOCUMENT_TABS = ['Files', 'Source settings'] as const;

function DocumentDeleteAction({
  document,
  onDelete,
}: {
  document: ManagedDocument;
  onDelete: (document: ManagedDocument) => void;
}) {
  const action = documentDeletionAction(document);
  if (!action.visible) return null;
  return <Tooltip title={action.tooltip}><span><IconButton color="error" disabled={action.disabled} aria-label={`Delete ${document.filename}`} onClick={() => onDelete(document)}><DeleteOutlineIcon /></IconButton></span></Tooltip>;
}

export function DocumentActions({
  admin,
  document,
  onDetails,
  onRetry,
  onDelete,
}: {
  admin: boolean;
  document: ManagedDocument;
  onDetails: (document: ManagedDocument) => void;
  onRetry: (document: ManagedDocument) => void;
  onDelete: (document: ManagedDocument) => void;
}) {
  return <><Tooltip title="Document details"><IconButton aria-label={`Details for ${document.filename}`} onClick={() => onDetails(document)}><InfoOutlinedIcon /></IconButton></Tooltip>{admin && document.delivery_status === 'FAILED' && <Tooltip title="Retry delivery"><IconButton aria-label={`Retry ${document.filename}`} onClick={() => onRetry(document)}><ReplayOutlinedIcon /></IconButton></Tooltip>}{admin && <DocumentDeleteAction document={document} onDelete={onDelete} />}</>;
}

export function DocumentVisibilityControl({
  showDeleted,
  onChange,
}: {
  showDeleted: boolean;
  onChange: (showDeleted: boolean) => void;
}) {
  return <FormControlLabel sx={{ alignSelf: 'flex-start' }} control={<Checkbox checked={showDeleted} onChange={(event) => onChange(event.target.checked)} />} label="Show deleted documents" />;
}

function Status({ value }: { value: string }) {
  const color = value.includes('FAILED') ? 'error' : value === 'UPLOADED' ? 'success' : value === 'UPLOADING' ? 'info' : value === 'UNSUPPORTED' ? 'warning' : 'default';
  return <Chip size="small" label={label(value)} color={color} variant={color === 'default' ? 'outlined' : 'filled'} />;
}

function SourceSettings() {
  const { user } = useAuth(); const toast = useToast(); const admin = user?.role === 'administrator';
  const [source, setSource] = useState<ManagedDocumentSource | null>(null); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(''); const [interval, setInterval] = useState(300); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setLoading(true); setError(''); try { const value = await api.documentSource(); setSource(value); setInterval(value.scan_interval_seconds); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Source settings could not be loaded'); } finally { setLoading(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  const perform = async (action: () => Promise<unknown>, success: string) => { setBusy(true); try { await action(); toast.show(success, 'success'); await load(); } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Source operation failed', 'error'); } finally { setBusy(false); } };
  if (loading) return <LoadingState label="Loading document source settings" />;
  if (error) return <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>}>{error}</Alert>;
  if (!source) return null;
  return <Paper variant="outlined" sx={{ p: 3 }}><Stack spacing={3}>
    <div><Typography variant="h6">Uploaded Documents</Typography><Typography color="text.secondary">Upload files through PEKA Connector or copy them into the managed document directory. The source path is controlled by the appliance.</Typography></div><Divider />
    <Grid container spacing={3}><Grid size={{ xs: 12, md: 6 }}><TextField fullWidth label="Source name" value={source.name} slotProps={{ input: { readOnly: true } }} /></Grid><Grid size={{ xs: 12, md: 6 }}><TextField fullWidth label="Fixed path" value={source.path} slotProps={{ input: { readOnly: true } }} helperText="This path cannot be edited." /></Grid><Grid size={{ xs: 12, md: 6 }}><TextField fullWidth type="number" label="Scan interval (seconds)" value={interval} disabled={!admin || busy} onChange={(event) => setInterval(Number(event.target.value))} slotProps={{ htmlInput: { min: 30, max: 86400 } }} helperText="Allowed range: 30–86400 seconds. Select Documents for Knowledge from Catalog." /></Grid></Grid>
    <Grid container spacing={2}><Grid size={{ xs: 6, md: 3 }}><Typography variant="caption" color="text.secondary">Source health</Typography><Box><Status value={source.health_status} /></Box></Grid><Grid size={{ xs: 6, md: 3 }}><Typography variant="caption" color="text.secondary">Last scan result</Typography><Typography>{source.last_scan_result}</Typography></Grid><Grid size={{ xs: 6, md: 3 }}><Typography variant="caption" color="text.secondary">Last scan</Typography><Typography title={formatTimestamp(source.last_scan_at)}>{relativeTimestamp(source.last_scan_at)}</Typography></Grid><Grid size={{ xs: 6, md: 3 }}><Typography variant="caption" color="text.secondary">Next scan</Typography><Typography title={formatTimestamp(source.next_scheduled_scan_at)}>{relativeTimestamp(source.next_scheduled_scan_at, Date.now(), 'Not scheduled')}</Typography></Grid><Grid size={{ xs: 6, md: 3 }}><Typography variant="caption" color="text.secondary">Documents discovered</Typography><Typography>{source.discovered_document_count}</Typography></Grid></Grid>
    {source.last_error && <Alert severity="warning">{source.last_error}</Alert>}
    {admin && <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}><Button variant="contained" disabled={busy || interval < 30 || interval > 86400} onClick={() => void perform(() => api.updateDocumentSource(source.enabled, interval), 'Document source settings saved')}>Save settings</Button><Button disabled={busy || !source.enabled} onClick={() => void perform(() => api.scanDocuments(), 'Document scan completed')}>Scan now</Button><Button disabled={busy} onClick={() => void perform(() => api.testDocumentSource(), 'Document source is healthy')}>Test source health</Button></Stack>}
  </Stack></Paper>;
}

export function DocumentsPage() {
  const { user } = useAuth(); const toast = useToast(); const input = useRef<HTMLInputElement>(null);
  const admin = user?.role === 'administrator';
  const [items, setItems] = useState<ManagedDocument[]>([]); const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false); const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<DocumentUploadResult[]>([]); const [details, setDetails] = useState<ManagedDocument | null>(null);
  const [deleting, setDeleting] = useState<ManagedDocument | null>(null);
  const [deletingBusy, setDeletingBusy] = useState(false);
  const [showDeleted, setShowDeleted] = useState(false);
  const [tab, setTab] = useState(0);
  const load = useCallback(async () => { setLoading(true); setError(''); try { const response = await api.documents(page + 1, showDeleted); setItems(response.items); setTotal(response.total); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Documents could not be loaded'); } finally { setLoading(false); } }, [page, showDeleted]);
  useEffect(() => { void load(); }, [load]);
  const upload = async (files: File[]) => {
    if (!files.length || !admin || uploading) return;
    setUploading(true); setProgress(0); setResults([]);
    try { const response = await api.uploadDocuments(files, setProgress); setResults(response.results); const succeeded = response.results.filter((item) => item.success).length; toast.show(`${succeeded} of ${files.length} document(s) stored`, succeeded ? 'success' : 'error'); await load(); }
    catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Upload failed', 'error'); }
    finally { setUploading(false); setProgress(0); if (input.current) input.current.value = ''; }
  };
  const retry = async (document: ManagedDocument) => { try { await api.retryDocument(document.id); toast.show('Local indexing queued for retry', 'success'); await load(); } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Retry failed', 'error'); } };
  const remove = async () => { if (!deleting || deletingBusy) return; setDeletingBusy(true); try { await api.deleteDocument(deleting.id); toast.show('Document deletion queued locally', 'success'); setDeleting(null); await load(); } catch (reason) { toast.show(reason instanceof Error ? reason.message : 'Delete failed', 'error'); } finally { setDeletingBusy(false); } };
  return <Stack spacing={3}>
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" gap={2}><div><Typography variant="h4" fontWeight={700}>Documents</Typography><Typography color="text.secondary">Customer-resident content in the Local Knowledge Store</Typography></div>{admin && tab === 0 && <Button variant="contained" startIcon={<CloudUploadOutlinedIcon />} disabled={uploading} onClick={() => input.current?.click()}>Upload documents</Button>}</Stack>
    <Tabs value={tab} onChange={(_, value: number) => setTab(value)} aria-label="Document management">{DOCUMENT_TABS.map((tabLabel) => <Tab key={tabLabel} label={tabLabel} />)}</Tabs>
    {tab === 0 ? <>
    {admin && <Paper variant="outlined" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void upload(Array.from(event.dataTransfer.files)); }} sx={{ p: 4, textAlign: 'center', borderStyle: 'dashed', bgcolor: 'background.default' }}><input ref={input} hidden type="file" multiple accept=".txt,.md,.pdf,.docx,.xlsx,.csv" onChange={(event) => void upload(Array.from(event.target.files ?? []))} /><CloudUploadOutlinedIcon color="primary" fontSize="large" /><Typography fontWeight={600}>Drag documents here or use Upload documents</Typography><Typography variant="body2" color="text.secondary">TXT, Markdown, PDF, DOCX, XLSX, or CSV · up to 100 MB per file</Typography>{uploading && <Box sx={{ mt: 2 }}><LinearProgress variant="determinate" value={progress} /><Typography variant="caption">Uploading {progress}%</Typography></Box>}</Paper>}
    {results.length > 0 && <Stack spacing={1}>{results.map((result, index) => <Alert key={`${result.filename}-${index}`} severity={result.success ? 'success' : 'error'}>{result.filename}: {result.message}</Alert>)}</Stack>}
    {error && <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>}>{error}</Alert>}
    <DocumentVisibilityControl showDeleted={showDeleted} onChange={(checked) => { setPage(0); setShowDeleted(checked); }} />
    {loading ? <LoadingState label="Loading documents" /> : items.length === 0 ? <Paper variant="outlined" sx={{ p: 5, textAlign: 'center' }}><Typography>No documents have been added yet.</Typography></Paper> : <Paper variant="outlined"><TableContainer><Table><TableHead><TableRow><TableCell>Document</TableCell><TableCell>Type</TableCell><TableCell>Size</TableCell><TableCell>Status</TableCell><TableCell>Indexed chunks</TableCell><TableCell>Last modified</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{items.map((document) => <TableRow key={document.id} hover><TableCell><Typography fontWeight={600}>{document.filename}</Typography><Typography variant="caption" color="text.secondary">{document.relative_path}</Typography></TableCell><TableCell>{document.extension.slice(1).toUpperCase()}</TableCell><TableCell>{formatSize(document.size_bytes)}</TableCell><TableCell><Status value={document.knowledge_status} /></TableCell><TableCell>{document.indexed_chunk_count.toLocaleString()}</TableCell><TableCell title={formatTimestamp(document.modified_at)}>{relativeTimestamp(document.modified_at)}</TableCell><TableCell align="right"><DocumentActions admin={admin} document={document} onDetails={setDetails} onRetry={(item) => void retry(item)} onDelete={setDeleting} /></TableCell></TableRow>)}</TableBody></Table></TableContainer><TablePagination component="div" count={total} page={page} rowsPerPage={25} rowsPerPageOptions={[25]} onPageChange={(_, next) => setPage(next)} /></Paper>}
    <Dialog open={Boolean(details)} onClose={() => setDetails(null)} fullWidth maxWidth="sm"><DialogTitle>Document details</DialogTitle><DialogContent dividers>{details && <Stack spacing={1}>{([['Filename', details.filename], ['Relative path', details.relative_path], ['MIME type', details.mime_type], ['Size', formatSize(details.size_bytes)], ['SHA-256', details.content_hash], ['Local Knowledge Store status', label(details.knowledge_status)], ['Indexed chunks', String(details.indexed_chunk_count)], ['Discovered', formatTimestamp(details.discovered_at)], ['Modified', formatTimestamp(details.modified_at)], ['Last error', details.knowledge_error ?? 'None']] as Array<[string, string]>).map(([name, value]) => <Box key={name}><Typography variant="caption" color="text.secondary">{name}</Typography><Typography sx={{ overflowWrap: 'anywhere', fontFamily: name.includes('SHA') || name.includes('ID') ? 'monospace' : undefined }}>{value}</Typography></Box>)}</Stack>}</DialogContent><DialogActions><Button onClick={() => setDetails(null)}>Close</Button></DialogActions></Dialog>
    <Dialog open={Boolean(deleting)} onClose={() => { if (!deletingBusy) setDeleting(null); }}><DialogTitle>Delete document?</DialogTitle><DialogContent><Typography fontWeight={600}>{deleting?.filename}</Typography><Typography sx={{ mt: 1 }}>This removes the local file and its indexed chunks from the Local Knowledge Store.</Typography></DialogContent><DialogActions><Button disabled={deletingBusy} onClick={() => setDeleting(null)}>Cancel</Button><Button disabled={deletingBusy} color="error" variant="contained" onClick={() => void remove()}>{deletingBusy ? 'Deleting…' : 'Delete'}</Button></DialogActions></Dialog>
    </> : <SourceSettings />}
  </Stack>;
}
