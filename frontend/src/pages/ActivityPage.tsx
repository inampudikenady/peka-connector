import { Alert, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { api } from '../api/client'; import type { ActivityEvent } from '../api/types'; import { LoadingState } from '../components/LoadingState';
export function ActivityPage() { const [items, setItems] = useState<ActivityEvent[] | null>(null); const [error, setError] = useState('');
  useEffect(() => { void api.activity().then(setItems).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <Alert severity="error">{error}</Alert>; if (!items) return <LoadingState label="Loading activity" />;
  return <><Typography variant="h4" fontWeight={700}>Activity</Typography><Typography color="text.secondary" sx={{ mb: 3 }}>Security and operational events</Typography>
    {items.length === 0 ? <Alert severity="info">No activity has been recorded yet.</Alert> : <TableContainer component={Paper}><Table><TableHead><TableRow><TableCell>Time</TableCell><TableCell>Event</TableCell><TableCell>Actor</TableCell><TableCell>Message</TableCell></TableRow></TableHead><TableBody>{items.map((item) => <TableRow key={item.id}><TableCell>{new Date(item.created_at).toLocaleString()}</TableCell><TableCell>{item.event_type}</TableCell><TableCell>{item.actor_username ?? 'System'}</TableCell><TableCell>{item.message}</TableCell></TableRow>)}</TableBody></Table></TableContainer>}</>;
}
