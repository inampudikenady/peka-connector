import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
} from '@mui/material';
import { useState, type FormEvent } from 'react';

import { api } from '../api/client';
import type { SourceInput } from '../api/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function SourceDialog({ open, onClose, onCreated }: Props) {
  const [name, setName] = useState('');
  const [path, setPath] = useState('/documents');
  const [includes, setIncludes] = useState('**/*.pdf, **/*.docx, **/*.txt, **/*.md');
  const [excludes, setExcludes] = useState('**/.git/**, **/~$*');
  const [interval, setInterval] = useState(300);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const splitPatterns = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    const input: SourceInput = {
      plugin_type: 'filesystem_documents',
      name,
      enabled,
      configuration: {
        path,
        include_patterns: splitPatterns(includes),
        exclude_patterns: splitPatterns(excludes),
        scan_interval_seconds: interval,
      },
    };
    try {
      await api.createSource(input);
      setName('');
      onCreated();
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create source');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" PaperProps={{ component: 'form', onSubmit: submit }}>
      <DialogTitle>Add filesystem source</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" required value={name} onChange={(event) => setName(event.target.value)} />
          <TextField label="Absolute path" required value={path} onChange={(event) => setPath(event.target.value)} helperText="Path as mounted inside the connector container" />
          <TextField label="Include patterns" value={includes} onChange={(event) => setIncludes(event.target.value)} helperText="Comma-separated glob patterns" />
          <TextField label="Exclude patterns" value={excludes} onChange={(event) => setExcludes(event.target.value)} helperText="Comma-separated glob patterns" />
          <TextField label="Scan interval (seconds)" type="number" value={interval} onChange={(event) => setInterval(Number(event.target.value))} inputProps={{ min: 30, max: 86400 }} />
          <FormControlLabel control={<Switch checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />} label="Enabled" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={saving}>Create source</Button>
      </DialogActions>
    </Dialog>
  );
}

