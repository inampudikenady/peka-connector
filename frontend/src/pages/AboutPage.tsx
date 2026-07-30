import { Alert, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';

import { api } from '../api/client';

export function AboutDetails({ version }: { version: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={1}>
        <Typography variant="h6">PEKA Connector</Typography>
        <Typography>Version {version}</Typography>
        <Typography color="text.secondary">
          Enterprise on-premises source discovery and secure outbound connectivity foundation.
        </Typography>
        <Typography color="text.secondary">
          This connector does not perform OCR, parsing, chunking, embeddings, AI inference, or
          vector indexing.
        </Typography>
      </Stack>
    </Paper>
  );
}

export function AboutPage() {
  const [version, setVersion] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    void api
      .health()
      .then((result) => setVersion(result.version))
      .catch((reason: Error) => setError(reason.message));
  }, []);
  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="h4" fontWeight={700}>About</Typography>
        <Typography color="text.secondary">PEKA Connector appliance information</Typography>
      </div>
      {error ? (
        <Alert severity="error">Connector version could not be loaded: {error}</Alert>
      ) : version ? (
        <AboutDetails version={version} />
      ) : (
        <Typography color="text.secondary">Loading connector version…</Typography>
      )}
    </Stack>
  );
}
