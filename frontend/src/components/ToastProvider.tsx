import { Alert, Snackbar } from '@mui/material';
import { createContext, useContext, useMemo, useState, type PropsWithChildren } from 'react';

type Severity = 'success' | 'error' | 'info' | 'warning';
interface ToastContextValue { show: (message: string, severity?: Severity) => void }
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: PropsWithChildren) {
  const [toast, setToast] = useState<{ message: string; severity: Severity } | null>(null);
  const value = useMemo(() => ({ show: (message: string, severity: Severity = 'info') => setToast({ message, severity }) }), []);
  return <ToastContext.Provider value={value}>
    {children}
    <Snackbar open={Boolean(toast)} autoHideDuration={5000} onClose={() => setToast(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
      <Alert severity={toast?.severity ?? 'info'} onClose={() => setToast(null)} variant="filled">{toast?.message}</Alert>
    </Snackbar>
  </ToastContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error('useToast must be used inside ToastProvider');
  return value;
}
