import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type PropsWithChildren,
} from 'react';

import { api } from '../api/client';
import type { Overview } from '../api/types';
import { createRefreshAction } from '../utils/createRefreshAction';
import { useToast } from './ToastProvider';

interface ConnectorStatusContextValue {
  data: Overview | null;
  error: string;
  loading: boolean;
  refreshing: boolean;
  retrying: boolean;
  refresh: () => Promise<void>;
  retryHeartbeat: () => Promise<void>;
}

const ConnectorStatusContext = createContext<ConnectorStatusContextValue | null>(null);

export function ConnectorStatusProvider({ children }: PropsWithChildren) {
  const toast = useToast();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const retryInFlight = useRef(false);

  const refresh = useMemo(() => createRefreshAction({
    load: api.overview,
    onStart: () => setRefreshing(true),
    onSuccess: (overview) => { setData(overview); setError(''); },
    onError: (reason) => setError(
      reason instanceof Error ? reason.message : 'Connector status could not be loaded.',
    ),
    onSettled: () => { setLoading(false); setRefreshing(false); },
  }), []);

  const retryHeartbeat = useCallback(async () => {
    if (retryInFlight.current) return;
    retryInFlight.current = true;
    setRetrying(true);
    try {
      await api.retryHeartbeat();
      await refresh();
      toast.show('Heartbeat completed successfully.', 'success');
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Heartbeat retry failed.';
      setError(message);
      toast.show(message, 'error');
      throw reason;
    } finally {
      retryInFlight.current = false;
      setRetrying(false);
    }
  }, [refresh, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  const value = useMemo(
    () => ({ data, error, loading, refreshing, retrying, refresh, retryHeartbeat }),
    [data, error, loading, refreshing, retrying, refresh, retryHeartbeat],
  );
  return <ConnectorStatusContext.Provider value={value}>{children}</ConnectorStatusContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useConnectorStatus(): ConnectorStatusContextValue {
  const value = useContext(ConnectorStatusContext);
  if (!value) throw new Error('useConnectorStatus must be used inside ConnectorStatusProvider');
  return value;
}
