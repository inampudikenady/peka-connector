import { createTheme } from '@mui/material/styles';

import { pekaTokens as colors } from './pekaTokens';

export const pekaTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: colors.primary, dark: colors.primaryHover },
    success: { main: colors.success }, warning: { main: colors.warning },
    error: { main: colors.danger }, info: { main: colors.info },
    background: { default: colors.bgApp, paper: colors.bgSurface },
    text: { primary: colors.textPrimary, secondary: colors.textSecondary, disabled: colors.textMuted },
    divider: colors.borderDefault,
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: 'var(--peka-font-sans)', fontSize: 14,
    h4: { fontSize: 'var(--peka-font-size-heading-xl)', lineHeight: 1.25, fontWeight: 700 },
    h5: { fontSize: 'var(--peka-font-size-heading-lg)', lineHeight: 1.3, fontWeight: 700 },
    h6: { fontSize: 'var(--peka-font-size-heading-md)', lineHeight: 1.4, fontWeight: 700 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiCssBaseline: { styleOverrides: { body: { backgroundColor: colors.bgApp } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 40, borderRadius: 8 } } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' }, outlined: { borderColor: colors.borderDefault, boxShadow: 'var(--peka-shadow-card)' } } },
    MuiCard: { styleOverrides: { root: { borderColor: colors.borderDefault, boxShadow: 'var(--peka-shadow-card)' } } },
    MuiTableCell: { styleOverrides: { head: { backgroundColor: colors.bgApp, color: colors.textSecondary, fontWeight: 700 }, root: { borderColor: colors.borderDefault } } },
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiFormControl: { defaultProps: { size: 'small' } },
    MuiOutlinedInput: { styleOverrides: { root: { minHeight: 40, borderRadius: 8 } } },
    MuiTabs: { styleOverrides: { root: { minHeight: 44 } } },
    MuiTab: { styleOverrides: { root: { minHeight: 44, textTransform: 'none', fontWeight: 600 } } },
    MuiTooltip: { defaultProps: { enterDelay: 500, leaveDelay: 0 } },
  },
});
