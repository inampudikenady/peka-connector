import { createContext, useCallback, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';

import { api } from '../api/client';
import type { CurrentUser } from '../api/types';

interface AuthValue {
  loading: boolean; setupRequired: boolean; user: CurrentUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setup: (username: string, password: string, confirm: string) => Promise<void>;
}
const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [loading, setLoading] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const clearSession = useCallback(() => setUser(null), []);

  useEffect(() => {
    api.setUnauthorizedHandler(clearSession);
    void (async () => {
      try {
        const status = await api.setupStatus();
        setSetupRequired(status.setup_required);
        if (!status.setup_required && await api.restoreSession()) setUser(await api.me());
      } finally { setLoading(false); }
    })();
  }, [clearSession]);

  const value = useMemo<AuthValue>(() => ({
    loading, setupRequired, user,
    login: async (username, password) => { await api.login(username, password); setUser(await api.me()); },
    logout: async () => { await api.logout(); setUser(null); },
    setup: async (username, password, confirm) => { await api.bootstrap(username, password, confirm); setSetupRequired(false); },
  }), [loading, setupRequired, user]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used within AuthProvider');
  return value;
}
