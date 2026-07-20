import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import { useState, type FormEvent } from 'react';

import { useAuth } from '../auth/AuthContext';

export function SetupPage() {
  const { setup } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try { await setup(username, password, confirm); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Administrator setup failed'); }
    finally { setSaving(false); }
  };
  return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: 'grey.100', p: 2 }}>
    <Paper component="form" onSubmit={submit} sx={{ p: 4, width: '100%', maxWidth: 480 }}>
      <Stack spacing={2.5}>
        <Box><Typography variant="h4" fontWeight={700}>PEKA Connector</Typography><Typography variant="h6">Create Local Administrator</Typography></Box>
        <Typography color="text.secondary">Create the first account for this appliance. Use at least 12 characters with uppercase, lowercase, a number, and a special character.</Typography>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField required autoFocus label="Username" value={username} onChange={(e) => setUsername(e.target.value)} helperText="3–50 characters; start with a letter" />
        <TextField required type="password" label="Password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <TextField required type="password" label="Confirm password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <Button type="submit" variant="contained" size="large" disabled={saving}>Create administrator</Button>
      </Stack>
    </Paper>
  </Box>;
}
