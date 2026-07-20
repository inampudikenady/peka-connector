import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import MenuIcon from '@mui/icons-material/Menu';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import TimelineOutlinedIcon from '@mui/icons-material/TimelineOutlined';
import {
  AppBar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material';
import { useState, type PropsWithChildren, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { ChangePasswordDialog } from './ChangePasswordDialog';

const drawerWidth = 240;
interface NavItem { label: string; path: string; icon: ReactNode; adminOnly?: boolean }
const items: NavItem[] = [
  { label: 'Overview', path: '/', icon: <DashboardOutlinedIcon /> },
  { label: 'Sources', path: '/sources', icon: <DnsOutlinedIcon /> },
  { label: 'Activity', path: '/activity', icon: <TimelineOutlinedIcon /> },
  { label: 'Logs', path: '/logs', icon: <DescriptionOutlinedIcon /> },
  { label: 'Diagnostics', path: '/diagnostics', icon: <MonitorHeartOutlinedIcon /> },
  { label: 'Users', path: '/users', icon: <GroupOutlinedIcon />, adminOnly: true },
  { label: 'Settings', path: '/settings', icon: <SettingsOutlinedIcon /> },
  { label: 'About', path: '/about', icon: <InfoOutlinedIcon /> },
];

export function AppShell({ children }: PropsWithChildren) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down('md'));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const drawer = <Box><Toolbar><FactCheckOutlinedIcon color="primary" sx={{ mr: 1 }} /><Typography fontWeight={800}>PEKA Connector</Typography></Toolbar><Divider />
    <List>{items.filter((item) => !item.adminOnly || user?.role === 'administrator').map((item) => <ListItemButton key={item.path} selected={location.pathname === item.path} onClick={() => { navigate(item.path); setDrawerOpen(false); }}>
      <ListItemIcon>{item.icon}</ListItemIcon><ListItemText primary={item.label} />
    </ListItemButton>)}</List></Box>;
  return <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'grey.50' }}>
    <AppBar position="fixed" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider', ml: { md: `${drawerWidth}px` }, width: { md: `calc(100% - ${drawerWidth}px)` } }}>
      <Toolbar>{mobile && <IconButton aria-label="Open navigation" onClick={() => setDrawerOpen(true)}><MenuIcon /></IconButton>}
        <Box sx={{ flexGrow: 1 }} /><Tooltip title="User menu"><IconButton aria-label="User menu" aria-controls={anchor ? 'profile-menu' : undefined} aria-haspopup="true" aria-expanded={Boolean(anchor)} onClick={(event) => setAnchor(event.currentTarget)}><AccountCircleIcon /></IconButton></Tooltip>
        <Menu id="profile-menu" anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)} MenuListProps={{ 'aria-label': 'User menu' }}>
          <MenuItem disabled><ListItemText primary={user?.username} secondary={user?.role === 'administrator' ? 'Administrator' : 'Read Only'} /></MenuItem><Divider />
          <MenuItem onClick={() => { setAnchor(null); setPasswordOpen(true); }}>Change Password</MenuItem>
          <MenuItem onClick={() => { setAnchor(null); void logout(); }}>Logout</MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
    <Drawer variant={mobile ? 'temporary' : 'permanent'} open={mobile ? drawerOpen : true} onClose={() => setDrawerOpen(false)} sx={{ width: drawerWidth, flexShrink: 0, '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box' } }}>{drawer}</Drawer>
    <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, sm: 3 }, mt: 8 }}>{children}</Box>
    <ChangePasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
  </Box>;
}
