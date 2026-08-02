import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import TimelineOutlinedIcon from '@mui/icons-material/TimelineOutlined';
import FolderCopyOutlinedIcon from '@mui/icons-material/FolderCopyOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import SubjectOutlinedIcon from '@mui/icons-material/SubjectOutlined';
import ConfirmationNumberOutlinedIcon from '@mui/icons-material/ConfirmationNumberOutlined';
import type { ReactNode } from 'react';

export interface NavItem { label: string; path: string; icon: ReactNode; adminOnly?: boolean }
export const LEGACY_SOURCES_REDIRECT = '/documents';

export const navigationItems: NavItem[] = [
  { label: 'Overview', path: '/', icon: <DashboardOutlinedIcon /> },
  { label: 'Documents', path: '/documents', icon: <FolderCopyOutlinedIcon /> },
  { label: 'CMDB', path: '/cmdb', icon: <StorageOutlinedIcon /> },
  { label: 'Prometheus', path: '/prometheus', icon: <DnsOutlinedIcon /> },
  { label: 'Loki', path: '/loki', icon: <SubjectOutlinedIcon /> },
  { label: 'Zammad', path: '/zammad', icon: <ConfirmationNumberOutlinedIcon /> },
  { label: 'Inventory', path: '/inventory', icon: <Inventory2OutlinedIcon /> },
  { label: 'Activity', path: '/activity', icon: <TimelineOutlinedIcon /> },
  { label: 'Logs', path: '/logs', icon: <DescriptionOutlinedIcon /> },
  { label: 'Diagnostics', path: '/diagnostics', icon: <MonitorHeartOutlinedIcon /> },
  { label: 'Users', path: '/users', icon: <GroupOutlinedIcon />, adminOnly: true },
  { label: 'Settings', path: '/settings', icon: <SettingsOutlinedIcon /> },
  { label: 'About', path: '/about', icon: <InfoOutlinedIcon /> },
];
