'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getWsUrl } from '@/lib/api';

const WS_URL = getWsUrl('/ws');
const INITIAL_RECONNECT_MS = 2000;
const MAX_RECONNECT_MS = 30000;

/**
 * useLiveFeed — connects to the TradeClaw WebSocket and pushes every
 * incoming state update directly into the React Query cache.
 *
 * This replaces all polling (refetchInterval) for status, history, and vitals.
 *
 * @param enabled — when false, the WebSocket is cleanly closed and won't reconnect.
 */
export function useLiveFeed(enabled: boolean = true) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const backoffRef = useRef(INITIAL_RECONNECT_MS);

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    // Don't open a second connection
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] Connected to TradeClaw engine');
      backoffRef.current = INITIAL_RECONNECT_MS; // reset backoff on success
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'state') {
          // ── Push status into the 'trading-status' cache ────────────────
          if (msg.status) {
            queryClient.setQueryData(['trading-status'], msg.status);
          }

          // ── Push chart data into the 'trading-history' cache ──────────
          if (msg.chart) {
            queryClient.setQueryData(['trading-history'], (old: any) => ({
              ...(old || {}),
              price_data: msg.chart.price_data || [],
              bollinger: msg.chart.bollinger || [],
              markers: msg.chart.markers || [],
              // Preserve trade history — comes from REST /history
              trades: old?.trades || [],
              equity_curve: old?.equity_curve || [],
            }));
          }

          // ── Push vitals into the 'vital-status' cache ─────────────────
          if (msg.vitals) {
            queryClient.setQueryData(['vital-status'], msg.vitals);
          }

          // ── Push Fibonacci signal into the 'fib-signal' cache ─────────
          // Provides real-time Fib level data for chart overlays and the
          // signal panel. Shape matches FibSignal.to_dict() from the backend.
          if (msg.fib_signal !== undefined) {
            queryClient.setQueryData(['fib-signal'], msg.fib_signal);
          }
        }
      } catch (e) {
        console.warn('[WS] Failed to parse message', e);
      }
    };

    ws.onerror = (err) => {
      console.warn('[WS] Error — will reconnect', err);
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (mountedRef.current && enabled) {
        console.log(`[WS] Disconnected — reconnecting in ${backoffRef.current}ms`);
        reconnectTimer.current = setTimeout(connect, backoffRef.current);
        // Exponential backoff: 2s → 4s → 8s → ... → 30s max
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_RECONNECT_MS);
      }
    };
  }, [queryClient, enabled]);

  useEffect(() => {
    mountedRef.current = true;

    if (enabled) {
      backoffRef.current = INITIAL_RECONNECT_MS;
      connect();
    } else {
      cleanup();
    }

    // Ping every 20s to keep the connection alive
    const pingInterval = enabled
      ? setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send('ping');
          }
        }, 20_000)
      : null;

    return () => {
      mountedRef.current = false;
      if (pingInterval) clearInterval(pingInterval);
      cleanup();
    };
  }, [connect, enabled, cleanup]);
}
