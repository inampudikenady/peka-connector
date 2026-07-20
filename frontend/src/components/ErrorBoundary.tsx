import { Alert, Box, Button, Typography } from '@mui/material';
import { Component, type ErrorInfo, type ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('UI error', error, info.componentStack); }
  render() {
    if (!this.state.failed) return this.props.children;
    return <Box sx={{ p: 4, maxWidth: 720, mx: 'auto' }}>
      <Alert severity="error">
        <Typography variant="h6">The application encountered an unexpected error.</Typography>
        <Button sx={{ mt: 2 }} variant="outlined" onClick={() => window.location.reload()}>Reload application</Button>
      </Alert>
    </Box>;
  }
}
