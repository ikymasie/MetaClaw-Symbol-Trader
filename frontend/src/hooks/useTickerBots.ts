'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface BotTickerInfo {
  bot_id: string;
  name: string;
  symbol: string;
  strategy: string;
  demo_mode: boolean;
  tags: string[];
  bot_status: string;
  daily_pnl: number;
  equity: number;
  current_price: number;
  position_qty: number;
  position_side: string;
  unrealized_pnl: number;
}

/** Poll /ticker/symbols every 5s to keep the bot switcher up to date */
export function useTickerBots() {
  return useQuery({
    queryKey: ['ticker-symbols'],
    queryFn: async (): Promise<{ bots: BotTickerInfo[] }> => {
      const { data } = await api.get('/ticker/symbols');
      return data;
    },
    refetchInterval: 5000,
    retry: 2,
  });
}
