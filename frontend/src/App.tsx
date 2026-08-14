import { Box, CircularProgress, CssBaseline, ThemeProvider } from '@mui/material';
import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, useAuth } from './auth/AuthContext';
import { AppShell } from './components/AppShell';
import { ConnectorStatusProvider } from './components/ConnectorStatusContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LEGACY_SOURCES_REDIRECT } from './components/navigationItems';
import { ToastProvider } from './components/ToastProvider';
import { ActivityPage } from './pages/ActivityPage';
import { LoginPage } from './pages/LoginPage';
import { SetupPage } from './pages/SetupPage';
import './peka-tokens.css';
import { pekaTheme } from './pekaTheme';

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })));
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage').then((module) => ({ default: module.IntegrationsPage })));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage').then((module) => ({ default: module.DocumentsPage })));
const CMDBPage = lazy(() => import('./pages/CMDBPage').then((module) => ({ default: module.CMDBPage })));
const PrometheusPage = lazy(() => import('./pages/PrometheusPage').then((module) => ({ default: module.PrometheusPage })));
const LokiPage = lazy(() => import('./pages/LokiPage').then((module) => ({ default: module.LokiPage })));
const ZammadPage = lazy(() => import('./pages/ZammadPage').then((module) => ({ default: module.ZammadPage })));
const ServiceNowPage = lazy(() => import('./pages/ServiceNowPage').then((module) => ({ default: module.ServiceNowPage })));
const ServiceNowCMDBPage = lazy(() => import('./pages/ServiceNowCMDBPage').then((module) => ({ default: module.ServiceNowCMDBPage })));
const InventoryPage = lazy(() => import('./pages/InventoryPage').then((module) => ({ default: module.InventoryPage })));
const DiagnosticsPage = lazy(() => import('./pages/DiagnosticsPage').then((module) => ({ default: module.DiagnosticsPage })));
const UsersPage = lazy(() => import('./pages/UsersPage').then((module) => ({ default: module.UsersPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })));
const AboutPage = lazy(() => import('./pages/AboutPage').then((module) => ({ default: module.AboutPage })));

function Application() {
  const { loading, setupRequired, user } = useAuth();
  if (loading) return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><CircularProgress aria-label="Loading application" /></Box>;
  if (setupRequired) return <SetupPage />;
  if (!user) return <LoginPage />;
  return <ConnectorStatusProvider><AppShell><Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}><Routes>
    <Route path="/" element={<Navigate to="/overview" replace />} />
    <Route path="/overview" element={<OverviewPage />} />
    <Route path="/integrations" element={<IntegrationsPage />} />
    <Route path="/data-sync" element={<Navigate to="/integrations?tab=data-sync" replace />} />
    <Route path="/sources/*" element={<Navigate to={LEGACY_SOURCES_REDIRECT} replace />} />
    <Route path="/documents" element={<DocumentsPage />} />
    <Route path="/cmdb" element={<CMDBPage />} />
    <Route path="/prometheus" element={<PrometheusPage />} />
    <Route path="/loki" element={<LokiPage />} />
    <Route path="/zammad" element={<ZammadPage />} />
    <Route path="/servicenow" element={<ServiceNowPage />} />
    <Route path="/servicenow/:configurationId/cmdb" element={<ServiceNowCMDBPage />} />
    <Route path="/inventory" element={<InventoryPage />} />
    <Route path="/activity" element={<ActivityPage />} />
    <Route path="/operational-requests" element={<Navigate to="/activity?tab=requests" replace />} />
    <Route path="/logs" element={<Navigate to="/activity?tab=logs" replace />} />
    <Route path="/diagnostics" element={<DiagnosticsPage />} />
    <Route path="/users" element={user.role === 'administrator' ? <UsersPage /> : <Navigate to="/" replace />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="*" element={<Navigate to="/overview" replace />} />
  </Routes></Suspense></AppShell></ConnectorStatusProvider>;
}

export default function App() {
  return <ThemeProvider theme={pekaTheme}><CssBaseline /><ErrorBoundary><ToastProvider><BrowserRouter><AuthProvider><Application /></AuthProvider></BrowserRouter></ToastProvider></ErrorBoundary></ThemeProvider>;
}
