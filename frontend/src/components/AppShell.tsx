import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import MenuIcon from '@mui/icons-material/Menu';
import {
  AppBar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material';
import { useState, type PropsWithChildren } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { ChangePasswordDialog } from './ChangePasswordDialog';
import { ConnectionStatusBadge } from './ConnectionStatusBadge';
import { useConnectorStatus } from './ConnectorStatusContext';
import { navigationItems } from './navigationItems';

const drawerWidth = 240;
export function AppShell({ children }: PropsWithChildren) {
  const { user, logout } = useAuth();
  const { data: connector } = useConnectorStatus();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down('md'));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const drawer = <Box sx={{ color: 'var(--peka-text-on-dark)' }}><Toolbar sx={{ minHeight: 'var(--peka-header-height)', px: 2.5 }}><FactCheckOutlinedIcon sx={{ mr: 1.25, color: 'var(--peka-info)' }} /><Typography fontWeight={750}>PEKA Connector</Typography></Toolbar><Divider sx={{ borderColor: 'var(--peka-bg-sidebar-hover)' }} />
    <List sx={{ px: 1.5, py: 2 }}>{navigationItems.filter((item) => !item.adminOnly || user?.role === 'administrator').map((item) => <ListItemButton key={item.path} selected={location.pathname === item.path} onClick={() => { navigate(item.path); setDrawerOpen(false); }} sx={{ mb: 0.5, borderRadius: 1, color: 'var(--peka-text-muted)', '& .MuiListItemIcon-root': { color: 'inherit', minWidth: 40 }, '&:hover': { bgcolor: 'var(--peka-bg-sidebar-hover)', color: 'var(--peka-text-on-dark)' }, '&.Mui-selected': { bgcolor: 'var(--peka-bg-sidebar-active)', color: 'var(--peka-text-on-dark)' }, '&.Mui-selected:hover': { bgcolor: 'var(--peka-bg-sidebar-active)' } }}>
      <ListItemIcon>{item.icon}</ListItemIcon><ListItemText primary={item.label} primaryTypographyProps={{ fontSize: 14, fontWeight: location.pathname === item.path ? 650 : 500 }} />
    </ListItemButton>)}</List></Box>;
  return <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'var(--peka-bg-app)' }}>
    <AppBar position="fixed" color="inherit" elevation={0} sx={{ bgcolor: 'var(--peka-bg-surface)', borderBottom: 1, borderColor: 'var(--peka-border-default)', ml: { md: `${drawerWidth}px` }, width: { md: `calc(100% - ${drawerWidth}px)` } }}>
      <Toolbar sx={{ minHeight: 'var(--peka-header-height)' }}>{mobile && <IconButton aria-label="Open navigation" onClick={() => setDrawerOpen(true)}><MenuIcon /></IconButton>}
        <Box sx={{ flexGrow: 1 }} />{connector && <ConnectionStatusBadge status={connector.saas_status} />}
        <Typography variant="body2" sx={{ display: { xs: 'none', sm: 'block' }, ml: 2, color: 'text.secondary' }}>{user?.username}</Typography>
        <Tooltip title="User menu" disableInteractive><IconButton aria-label="Open user menu" aria-controls={anchor ? 'profile-menu' : undefined} aria-haspopup="true" aria-expanded={Boolean(anchor)} onClick={(event) => setAnchor(event.currentTarget)}><AccountCircleIcon /></IconButton></Tooltip>
        <Menu id="profile-menu" anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)} MenuListProps={{ 'aria-label': 'User menu' }}>
          <MenuItem disabled><ListItemText primary={user?.username} secondary={user?.role === 'administrator' ? 'Administrator' : 'Read Only'} /></MenuItem><Divider />
          <MenuItem onClick={() => { setAnchor(null); setPasswordOpen(true); }}>Change Password</MenuItem>
          <MenuItem onClick={() => { setAnchor(null); void logout(); }}>Sign out</MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
    <Drawer variant={mobile ? 'temporary' : 'permanent'} open={mobile ? drawerOpen : true} onClose={() => setDrawerOpen(false)} sx={{ width: drawerWidth, flexShrink: 0, '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', bgcolor: 'var(--peka-bg-sidebar)', borderRightColor: 'var(--peka-bg-sidebar-hover)' } }}>{drawer}</Drawer>
    <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, sm: 3, lg: 4 }, mt: 'var(--peka-header-height)' }}>{children}</Box>
    <ChangePasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
  </Box>;
}
