'use client';

import { createContext, useContext, useState, useCallback, useRef, useEffect, type ReactNode } from 'react';
import { API_BASE_URL } from '@/lib/api';

const API_BASE = API_BASE_URL;

interface StreamingStats {
  paused: boolean;
  ticker: {
    running: boolean;
    connected: boolean;
    subscribed_symbols: string[];
    total_subscribers: number;
    messages_received: number;
    messages_fanout: number;
    messages_dropped: number;
  } | null;
  ws_channels: number;
}

interface StreamingContextValue {
  /** Master on/off for all WebSocket connections */
  isStreaming: boolean;
  /** Pause all data streams (WS connections closed on frontend, backend fan-out paused) */
  pause: () => Promise<void>;
  /** Resume all data streams */
  resume: () => Promise<void>;
  /** Toggle streaming state */
  toggle: () => Promise<void>;
  /** Current streaming stats from the backend */
  stats: StreamingStats;
  /** Whether a pause/resume operation is in-flight */
  isTransitioning: boolean;
}

const defaultStats: StreamingStats = {
  paused: false,
  ticker: null,
  ws_channels: 0,
};

const StreamingContext = createContext<StreamingContextValue>({
  isStreaming: true,
  pause: async () => {},
  resume: async () => {},
  toggle: async () => {},
  stats: defaultStats,
  isTransitioning: false,
});

export function useStreaming() {
  return useContext(StreamingContext);
}

export function StreamingProvider({ children }: { children: ReactNode }) {
  const [isStreaming, setIsStreaming] = useState(true);
  const [stats, setStats] = useState<StreamingStats>(defaultStats);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/streaming/status`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch {
      // Backend may be down — ignore
    }
  }, []);

  // Poll stats every 5s when streaming, every 15s when paused
  useEffect(() => {
    fetchStats();
    const interval = isStreaming ? 5000 : 15000;
    pollRef.current = setInterval(fetchStats, interval);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isStreaming, fetchStats]);

  const pause = useCallback(async () => {
    setIsTransitioning(true);
    try {
      await fetch(`${API_BASE}/streaming/pause`, { method: 'POST' });
      setIsStreaming(false);
      await fetchStats();
    } catch (e) {
      console.error('[Streaming] Pause failed:', e);
    } finally {
      setIsTransitioning(false);
    }
  }, [fetchStats]);

  const resume = useCallback(async () => {
    setIsTransitioning(true);
    try {
      await fetch(`${API_BASE}/streaming/resume`, { method: 'POST' });
      setIsStreaming(true);
      await fetchStats();
    } catch (e) {
      console.error('[Streaming] Resume failed:', e);
    } finally {
      setIsTransitioning(false);
    }
  }, [fetchStats]);

  const toggle = useCallback(async () => {
    if (isStreaming) {
      await pause();
    } else {
      await resume();
    }
  }, [isStreaming, pause, resume]);

  return (
    <StreamingContext.Provider value={{ isStreaming, pause, resume, toggle, stats, isTransitioning }}>
      {children}
    </StreamingContext.Provider>
  );
}
