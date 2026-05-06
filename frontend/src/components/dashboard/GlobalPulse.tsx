'use client';

import { useAlpacaTicker } from '@/hooks/useAlpacaTicker';
import { useStreaming } from '@/contexts/StreamingContext';
import { Activity, TrendingUp, TrendingDown, Target, Zap } from 'lucide-react';
import { motion } from 'framer-motion';

export function GlobalPulse() {
  const { isStreaming } = useStreaming();
  const { lastPrice, bars, isConnected } = useAlpacaTicker('SPY', isStreaming);

  const openBar = bars.length > 0 ? bars[0] : null;
  const prevClose = openBar?.close ?? 0;
  const change = lastPrice && prevClose ? lastPrice - prevClose : 0;
  const changePct = change && prevClose ? (change / prevClose) * 100 : 0;
  const isPositive = change >= 0;

  return (
    <div className="rounded-2xl border border-white/8 bg-card/20 overflow-hidden">
      <div className="p-6">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
              <Activity className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">Global Market Pulse</h3>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Tracking SPY • Real-time</p>
            </div>
          </div>
          <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${isConnected ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-zinc-500/10 border-zinc-500/20 text-zinc-500'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'}`} />
            <span className="text-[10px] font-mono font-bold">{isConnected ? 'LIVE FEED' : 'CONNECTING'}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
          <div>
            <div className="flex items-baseline gap-3 mb-1">
              <span className="text-4xl font-bold text-white tracking-tighter">
                {lastPrice ? `$${lastPrice.toFixed(2)}` : '—'}
              </span>
              <div className={`flex items-center gap-1 text-sm font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                {isPositive ? '+' : ''}{changePct.toFixed(2)}%
              </div>
            </div>
            <p className="text-xs font-mono text-muted-foreground">Standard & Poor's 500 ETF Trust</p>
          </div>

          <div className="flex flex-col gap-2">
            <div className="p-3 rounded-xl bg-white/4 border border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Target className="w-3.5 h-3.5 text-zinc-500" />
                <span className="text-[10px] font-mono text-zinc-500 uppercase">Engine Status</span>
              </div>
              <span className="text-xs font-mono font-bold text-emerald-400">READY</span>
            </div>
            <div className="p-3 rounded-xl bg-white/4 border border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap className="w-3.5 h-3.5 text-zinc-500" />
                <span className="text-[10px] font-mono text-zinc-500 uppercase">Sub-Agents</span>
              </div>
              <span className="text-xs font-mono font-bold text-zinc-400">IDLE</span>
            </div>
          </div>
        </div>
      </div>
      
      {/* Visual background element */}
      <div className="h-1 bg-gradient-to-r from-primary/50 via-sky-500/50 to-primary/50 opacity-20" />
    </div>
  );
}
