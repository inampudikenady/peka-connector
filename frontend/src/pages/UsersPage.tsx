import AddIcon from '@mui/icons-material/Add';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import {
  Alert, Button, Chip, Dialog, DialogActions, DialogContent, DialogContentText,
  DialogTitle, FormControlLabel, IconButton, Menu, MenuItem, Paper, Stack, Switch,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField,
  Tooltip, Typography,
} from '@mui/material';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';

import { api } from '../api/client';
import type { LocalUser, Role } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { LoadingState } from '../components/LoadingState';
import { useToast } from '../components/ToastProvider';
import { formatTimestamp } from '../utils/time';

export function UsersPage() {
  const { user: current } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState<LocalUser[] | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<LocalUser | null>(null);
  const [deleting, setDeleting] = useState<LocalUser | null>(null);

  const load = useCallback(async () => {
    try { setUsers(await api.users()); setError(''); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Users could not be loaded.'); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const activeAdministratorCount = useMemo(
    () => users?.filter((user) => user.role === 'administrator' && user.is_active).length ?? 0,
    [users],
  );
  const safeguardReason = (user: LocalUser, action: 'disable' | 'delete') => {
    if (user.id === current?.id) return action === 'disable' ? 'You cannot disable your own account.' : 'You cannot delete your own account.';
    if (user.role === 'administrator' && user.is_active && activeAdministratorCount <= 1) return `The last enabled administrator cannot be ${action === 'disable' ? 'disabled' : 'deleted'}.`;
    return '';
  };
  const changeState = async (user: LocalUser) => {
    try {
      await api.setUserState(user.id, !user.is_active);
      toast.show(`${user.username} ${user.is_active ? 'disabled' : 'enabled'}.`, 'success');
      await load();
    } catch (caught) { toast.show(caught instanceof Error ? caught.message : 'User update failed.', 'error'); }
  };

  if (error) return <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>}>{error}</Alert>;
  if (!users) return <LoadingState label="Loading local users" />;
  return <Stack spacing={2.5}>
    <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'center' }} justifyContent="space-between" gap={1.5}>
      <div><Typography variant="h4">Users</Typography><Typography variant="body2" color="text.secondary">Local connector access</Typography></div>
      <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)}>Create user</Button>
    </Stack>
    <TableContainer component={Paper} variant="outlined"><Table size="small" aria-label="Local connector users"><TableHead><TableRow><TableCell>Username</TableCell><TableCell>Role</TableCell><TableCell>Status</TableCell><TableCell>Last login</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{users.map((user) => {
      const disableReason = user.is_active ? safeguardReason(user, 'disable') : '';
      const deleteReason = safeguardReason(user, 'delete');
      return <TableRow key={user.id} hover><TableCell><Typography variant="body2" fontWeight={650}>{user.username}</Typography>{user.id === current?.id && <Typography variant="caption" color="text.secondary">Current user</Typography>}</TableCell><TableCell>{user.role === 'administrator' ? 'Administrator' : 'Read Only'}</TableCell><TableCell><Stack direction="row" alignItems="center" spacing={1}><Chip size="small" label={user.is_active ? 'Enabled' : 'Disabled'} color={user.is_active ? 'success' : 'default'} /><Tooltip title={disableReason}><span><Switch size="small" checked={user.is_active} disabled={Boolean(disableReason)} onChange={() => void changeState(user)} inputProps={{ 'aria-label': `${user.is_active ? 'Disable' : 'Enable'} ${user.username}` }} /></span></Tooltip></Stack></TableCell><TableCell>{user.last_login_at ? formatTimestamp(user.last_login_at) : 'Never'}</TableCell><TableCell align="right"><UserActions user={user} disableReason={disableReason} deleteReason={deleteReason} onReset={() => setResetting(user)} onState={() => void changeState(user)} onDelete={() => setDeleting(user)} /></TableCell></TableRow>;
    })}</TableBody></Table></TableContainer>
    <CreateUserDialog open={creating} onClose={() => setCreating(false)} onSaved={async () => { setCreating(false); await load(); toast.show('Local user created.', 'success'); }} />
    <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
    <DeleteUserDialog user={deleting} onClose={() => setDeleting(null)} onDeleted={async () => { setDeleting(null); await load(); toast.show('Local user deleted.', 'success'); }} />
  </Stack>;
}

function UserActions({ user, disableReason, deleteReason, onReset, onState, onDelete }: { user: LocalUser; disableReason: string; deleteReason: string; onReset: () => void; onState: () => void; onDelete: () => void }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const closeThen = (action: () => void) => { setAnchor(null); action(); };
  return <><Tooltip title={`Actions for ${user.username}`}><IconButton size="small" aria-label={`Actions for ${user.username}`} aria-haspopup="menu" aria-expanded={Boolean(anchor)} onClick={(event) => setAnchor(event.currentTarget)}><MoreVertIcon /></IconButton></Tooltip><Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)} MenuListProps={{ 'aria-label': `Actions for ${user.username}` }}><MenuItem onClick={() => closeThen(onReset)}>Reset password</MenuItem><Tooltip title={disableReason} placement="left"><span><MenuItem disabled={Boolean(disableReason)} onClick={() => closeThen(onState)}>{user.is_active ? 'Disable' : 'Enable'}</MenuItem></span></Tooltip><Tooltip title={deleteReason} placement="left"><span><MenuItem disabled={Boolean(deleteReason)} onClick={() => closeThen(onDelete)}>Delete</MenuItem></span></Tooltip></Menu></>;
}

function CreateUserDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const [username, setUsername] = useState('');
  const [role, setRole] = useState<Role>('administrator');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const close = () => { setUsername(''); setRole('administrator'); setPassword(''); setConfirm(''); setEnabled(true); setError(''); onClose(); };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (password !== confirm) { setError('Password confirmation does not match'); return; }
    setSaving(true);
    try { await api.createUser({ username, role, password, confirm_password: confirm, enabled }); setUsername(''); setRole('administrator'); setPassword(''); setConfirm(''); setEnabled(true); setError(''); await onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'User creation failed.'); }
    finally { setSaving(false); }
  };
  return <Dialog open={open} onClose={saving ? undefined : close} fullWidth maxWidth="xs" PaperProps={{ component: 'form', onSubmit: submit }}><DialogTitle>Create user</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{error && <Alert severity="error">{error}</Alert>}<TextField required label="Username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" /><TextField select label="Role" value={role} onChange={(event) => setRole(event.target.value as Role)}><MenuItem value="administrator">Administrator</MenuItem><MenuItem value="read_only">Read Only</MenuItem></TextField><TextField required type="password" label="Temporary password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" helperText="12+ characters with uppercase, lowercase, number and special character" /><TextField required type="password" label="Confirm password" value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" /><FormControlLabel control={<Switch checked={enabled} onChange={(event) => setEnabled(event.target.checked)} inputProps={{ 'aria-label': 'User enabled' }} />} label="Enabled" /></Stack></DialogContent><DialogActions><Button disabled={saving} onClick={close}>Cancel</Button><Button disabled={saving} type="submit" variant="contained">{saving ? 'Creating…' : 'Create user'}</Button></DialogActions></Dialog>;
}

function ResetPasswordDialog({ user, onClose }: { user: LocalUser | null; onClose: () => void }) {
  const toast = useToast();
  const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState(''); const [error, setError] = useState(''); const [saving, setSaving] = useState(false);
  const close = () => { setPassword(''); setConfirm(''); setError(''); onClose(); };
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!user) return; setError(''); if (password !== confirm) { setError('Password confirmation does not match'); return; } setSaving(true); try { await api.resetUserPassword(user.id, password, confirm); toast.show('Password reset successfully.', 'success'); close(); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Password reset failed.'); } finally { setSaving(false); } };
  return <Dialog open={Boolean(user)} onClose={saving ? undefined : close} fullWidth maxWidth="xs" PaperProps={{ component: 'form', onSubmit: submit }}><DialogTitle>Reset password</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{error && <Alert severity="error">{error}</Alert>}<DialogContentText>Set a new password for {user?.username}.</DialogContentText><TextField required type="password" label="New password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" helperText="12+ characters with uppercase, lowercase, number and special character" /><TextField required type="password" label="Confirm password" value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" /></Stack></DialogContent><DialogActions><Button disabled={saving} onClick={close}>Cancel</Button><Button disabled={saving} type="submit" variant="contained">{saving ? 'Resetting…' : 'Reset password'}</Button></DialogActions></Dialog>;
}

function DeleteUserDialog({ user, onClose, onDeleted }: { user: LocalUser | null; onClose: () => void; onDeleted: () => Promise<void> }) {
  const [error, setError] = useState(''); const [deleting, setDeleting] = useState(false);
  const close = () => { setError(''); onClose(); };
  const remove = async () => { if (!user) return; setDeleting(true); setError(''); try { await api.deleteUser(user.id); await onDeleted(); } catch (caught) { setError(caught instanceof Error ? caught.message : 'User deletion failed.'); } finally { setDeleting(false); } };
  return <Dialog open={Boolean(user)} onClose={deleting ? undefined : close} fullWidth maxWidth="xs"><DialogTitle>Delete local user “{user?.username}”?</DialogTitle><DialogContent>{error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}<DialogContentText>This user will no longer be able to sign in to the connector.</DialogContentText></DialogContent><DialogActions><Button disabled={deleting} onClick={close}>Cancel</Button><Button disabled={deleting} color="error" variant="contained" onClick={() => void remove()}>{deleting ? 'Deleting…' : 'Delete user'}</Button></DialogActions></Dialog>;
}
