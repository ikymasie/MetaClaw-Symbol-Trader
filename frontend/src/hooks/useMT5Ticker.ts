'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { getWsUrl } from '@/lib/api';

const INITIAL_RECONNECT_MS = 2000;
const MAX_RECONNECT_MS = 30000;
const MAX_BARS = 400;

export interface MT5Bar {
  time: string;       // ISO timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  symbol: string;
}

export interface MT5Quote {
  bid: number;
  ask: number;
  bid_size: number;
  ask_size: number;
  time: string;
  symbol: string;
}

export interface TickerBotContext {
  bot_id: string;
  name: string;
  bot_status: string;
  current_price: number;
  daily_pnl: number;
  equity: number;
  position_qty: number;
  position_side: string;
  entry_price: number;
  unrealized_pnl: number;
  last_signal: string;
  bollinger_last: {
    upper?: number;
    middle?: number;
    lower?: number;
    time?: string;
  };
  markers: Array<{
    time: string;
    position: string;
    color: string;
    shape: string;
    text: string;
  }>;
}

export interface TickerState {
  bars: MT5Bar[];
  lastQuote: MT5Quote | null;
  lastPrice: number | null;
  bots: TickerBotContext[];
  isConnected: boolean;
  error: string | null;
}

/**
 * useMT5Ticker
 * Connects to /ws/ticker/{symbol} and streams live MT5 bar + bot context.
 * Tears down and reconnects when `symbol` changes.
 *
 * @param symbol — the ticker symbol to subscribe to, or null to disconnect
 * @param enabled — master switch; when false, WS is cleanly closed
 */
export function useMT5Ticker(symbol: string | null, enabled: boolean = true): TickerState {
  const [bars, setBars] = useState<MT5Bar[]>([]);
  const [lastQuote, setLastQuote] = useState<MT5Quote | null>(null);
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const [bots, setBots] = useState<TickerBotContext[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const symbolRef = useRef<string | null>(null);
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

  useEffect(() => {
    mountedRef.current = true;

    // Reset state on symbol change
    setBars([]);
    setLastQuote(null);
    setLastPrice(null);
    setBots([]);
    setIsConnected(false);
    setError(null);

    // Close existing connection
    cleanup();

    if (!symbol || !enabled) return;

    symbolRef.current = symbol;
    backoffRef.current = INITIAL_RECONNECT_MS;

    const connect = (sym: string) => {
      if (!mountedRef.current || !enabled) return;

      const ws = new WebSocket(getWsUrl(`/ws/ticker/${sym}`));
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        backoffRef.current = INITIAL_RECONNECT_MS;
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      // Buffer incoming high-frequency data
      let bufferedQuote: MT5Quote | null = null;
      let bufferedPrice: number | null = null;
      let bufferedBots: TickerBotContext[] | null = null;
      let bufferedBars: MT5Bar[] = [];
      let flushTimeout: ReturnType<typeof setTimeout> | null = null;

      const flushBuffer = () => {
        if (!mountedRef.current) return;
        
        if (bufferedBots) {
          setBots(bufferedBots);
          bufferedBots = null;
        }
        if (bufferedBars.length > 0) {
          setBars((prev) => {
            const newBars = [...prev, ...bufferedBars];
            return newBars.slice(-MAX_BARS);
          });
          bufferedBars = [];
        }
        if (bufferedQuote) {
          setLastQuote(bufferedQuote);
          bufferedQuote = null;
        }
        if (bufferedPrice !== null) {
          setLastPrice(bufferedPrice);
          bufferedPrice = null;
        }
        flushTimeout = null;
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.bots) bufferedBots = msg.bots;

          if (msg.type === 'bar' && msg.bar) {
            bufferedBars.push(msg.bar);
            bufferedPrice = msg.bar.close;
          }

          if (msg.type === 'quote' && msg.quote) {
            bufferedQuote = msg.quote;
            if (msg.quote.bid && msg.quote.ask) {
              bufferedPrice = (msg.quote.bid + msg.quote.ask) / 2;
            }
          }

          if (msg.type === 'trade_tick' && msg.tick) {
            bufferedPrice = msg.tick.price;
          }

          // Throttle state updates to roughly 10fps
          if (!flushTimeout) {
            flushTimeout = setTimeout(flushBuffer, 100);
          }

        } catch (e) {
          console.warn('[TickerWS] Parse error', e);
        }
      };

      ws.onerror = () => {
        setError(`Cannot connect to ticker for ${sym}`);
      };

      ws.onclose = () => {
        if (flushTimeout) clearTimeout(flushTimeout);
        setIsConnected(false);
        wsRef.current = null;
        // Only reconnect if the symbol hasn't changed and we're still enabled
        if (mountedRef.current && symbolRef.current === sym && enabled) {
          reconnectTimer.current = setTimeout(() => connect(sym), backoffRef.current);
          backoffRef.current = Math.min(backoffRef.current * 2, MAX_RECONNECT_MS);
        }
      };
    };

    connect(symbol);

    // Ping every 20s to keep alive
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 20_000);

    return () => {
      clearInterval(pingInterval);
      cleanup();
    };
  }, [symbol, enabled, cleanup]);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  return { bars, lastQuote, lastPrice, bots, isConnected, error };
}
