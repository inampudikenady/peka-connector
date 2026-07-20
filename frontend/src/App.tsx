import { Box, CircularProgress, CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, useAuth } from './auth/AuthContext';
import { AppShell } from './components/AppShell';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ToastProvider } from './components/ToastProvider';
import { LoginPage } from './pages/LoginPage';
import { SetupPage } from './pages/SetupPage';

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })));
const SourcesPage = lazy(() => import('./pages/SourcesPage').then((module) => ({ default: module.SourcesPage })));
const ActivityPage = lazy(() => import('./pages/ActivityPage').then((module) => ({ default: module.ActivityPage })));
const LogsPage = lazy(() => import('./pages/LogsPage').then((module) => ({ default: module.LogsPage })));
const DiagnosticsPage = lazy(() => import('./pages/DiagnosticsPage').then((module) => ({ default: module.DiagnosticsPage })));
const UsersPage = lazy(() => import('./pages/UsersPage').then((module) => ({ default: module.UsersPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })));
const AboutPage = lazy(() => import('./pages/AboutPage').then((module) => ({ default: module.AboutPage })));

const theme = createTheme({ palette: { primary: { main: '#1746a2' }, background: { default: '#f6f8fb' } }, shape: { borderRadius: 8 }, typography: { fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }, components: { MuiButton: { defaultProps: { disableElevation: true } } } });

function Application() {
  const { loading, setupRequired, user } = useAuth();
  if (loading) return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><CircularProgress aria-label="Loading application" /></Box>;
  if (setupRequired) return <SetupPage />;
  if (!user) return <LoginPage />;
  return <AppShell><Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}><Routes>
    <Route path="/" element={<OverviewPage />} />
    <Route path="/sources" element={<SourcesPage />} />
    <Route path="/activity" element={<ActivityPage />} />
    <Route path="/logs" element={<LogsPage />} />
    <Route path="/diagnostics" element={<DiagnosticsPage />} />
    <Route path="/users" element={user.role === 'administrator' ? <UsersPage /> : <Navigate to="/" replace />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></Suspense></AppShell>;
}

export default function App() {
  return <ThemeProvider theme={theme}><CssBaseline /><ErrorBoundary><ToastProvider><BrowserRouter><AuthProvider><Application /></AuthProvider></BrowserRouter></ToastProvider></ErrorBoundary></ThemeProvider>;
}
