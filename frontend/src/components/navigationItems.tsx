import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import PeopleOutlineIcon from '@mui/icons-material/PeopleOutline';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import SyncAltOutlinedIcon from '@mui/icons-material/SyncAltOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import type { ReactNode } from 'react';

export interface NavItem { label: string; path: string; icon: ReactNode; adminOnly?: boolean }
export const LEGACY_SOURCES_REDIRECT = '/documents';

export const navigationItems: NavItem[] = [
  { label: 'Overview', path: '/overview', icon: <DashboardOutlinedIcon /> },
  { label: 'Integrations', path: '/integrations', icon: <HubOutlinedIcon /> },
  { label: 'Documents', path: '/documents', icon: <DescriptionOutlinedIcon /> },
  { label: 'Activity', path: '/activity', icon: <SyncAltOutlinedIcon /> },
  { label: 'Users', path: '/users', icon: <PeopleOutlineIcon />, adminOnly: true },
  { label: 'Settings', path: '/settings', icon: <SettingsOutlinedIcon /> },
];
