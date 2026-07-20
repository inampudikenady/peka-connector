import { Box, CircularProgress, Typography } from '@mui/material';

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return <Box role="status" sx={{ py: 8, display: 'grid', placeItems: 'center', gap: 2 }}>
    <CircularProgress size={32} /><Typography color="text.secondary">{label}</Typography>
  </Box>;
}
