import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from '@mui/material';
import { useState, type FormEvent } from 'react';

import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useToast } from './ToastProvider';

export function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { logout } = useAuth(); const toast = useToast();
  const [current, setCurrent] = useState(''); const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState('');
  const [error, setError] = useState(''); const [saving, setSaving] = useState(false);
  const submit = async (event: FormEvent) => { event.preventDefault(); setSaving(true); setError('');
    try { await api.changePassword(current, password, confirm); toast.show('Password changed. Sign in again.', 'success'); onClose(); await logout(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Password change failed'); }
    finally { setSaving(false); }
  };
  return <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs" PaperProps={{ component: 'form', onSubmit: submit }}>
    <DialogTitle>Change Password</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField required type="password" label="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      <TextField required type="password" label="New password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} helperText="12+ characters with uppercase, lowercase, number and special character" />
      <TextField required type="password" label="Confirm new password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
    </Stack></DialogContent><DialogActions><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="contained" disabled={saving}>Change password</Button></DialogActions>
  </Dialog>;
}
