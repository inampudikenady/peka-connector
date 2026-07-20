import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { useState } from 'react';

import { api } from './api/client';
import { AppShell } from './components/AppShell';
import { LoginPage } from './pages/LoginPage';
import { SourcesPage } from './pages/SourcesPage';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#1746a2' },
    background: { default: '#f6f8fb' },
  },
  shape: { borderRadius: 10 },
  typography: { fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' },
});

export default function App() {
  const [authenticated, setAuthenticated] = useState(api.isAuthenticated());

  const logout = () => {
    api.logout();
    setAuthenticated(false);
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {authenticated ? (
        <AppShell onLogout={logout}><SourcesPage /></AppShell>
      ) : (
        <LoginPage onLogin={() => setAuthenticated(true)} />
      )}
    </ThemeProvider>
  );
}

