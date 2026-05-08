'use client';

import { motion } from 'framer-motion';
import { Shield, Wallet, TrendingUp, TrendingDown, Landmark, Zap } from 'lucide-react';
import { useMT5Account, useFleetStatus } from '@/hooks/useFleet';

export function AccountVitalsCard() {
  const { data: account, isLoading, error } = useMT5Account();
  const { data: fleetStatus } = useFleetStatus();

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-white/8 bg-card/20 p-5 space-y-4 animate-pulse">
        <div className="h-4 w-24 bg-white/5 rounded" />
        <div className="h-8 w-32 bg-white/5 rounded" />
        <div className="grid grid-cols-2 gap-3">
          <div className="h-12 bg-white/5 rounded-xl" />
          <div className="h-12 bg-white/5 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !account) return null;

  // Include paper trading P&L so the user sees real-time changes
  // even when bots are in demo_mode
  const paperPnl = fleetStatus?.bots
    ?.filter(b => b.demo_mode)
    .reduce((sum, b) => sum + (b.status?.daily_pnl || 0), 0) || 0;

  const displayEquity = account.equity + paperPnl;
  const displayDailyPnl = account.daily_pnl + paperPnl;
  // Recalculate drift (pct) against the starting balance
  const startingBalance = account.equity - account.daily_pnl; 
  const drift = startingBalance > 0 ? (displayDailyPnl / startingBalance) * 100 : 0;
  
  const isPositive = drift >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="rounded-2xl border border-white/8 bg-card/20 overflow-hidden"
    >
      <div className="p-5 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Landmark className="w-4 h-4 text-zinc-500" />
            <h3 className="text-[10px] font-mono font-bold text-zinc-500 uppercase tracking-widest">
              Account Vitals
            </h3>
          </div>
          {paperPnl !== 0 && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20">
              <Zap className="w-2.5 h-2.5 text-primary" />
              <span className="text-[9px] font-mono text-primary font-bold">PAPER ACTIVE</span>
            </div>
          )}
        </div>

        {/* Main Value */}
        <div>
          <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-tighter mb-1">
            Total Equity
          </p>
          <div className="flex items-baseline gap-2">
            <h2 className="text-2xl font-bold text-white tracking-tight">
              ${displayEquity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </h2>
            <div className={`flex items-center gap-1 text-[10px] font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              {isPositive ? '+' : ''}{drift.toFixed(2)}%
            </div>
          </div>
        </div>

        {/* Breakdown Grid */}
        <div className="grid grid-cols-1 gap-2">
          <VitalRow
            icon={<Wallet className="w-3 h-3 text-zinc-400" />}
            label="Buying Power"
            value={`$${account.buying_power.toLocaleString()}`}
          />
          <VitalRow
            icon={<Shield className="w-3 h-3 text-zinc-400" />}
            label="Daily P&L"
            value={`$${displayDailyPnl.toFixed(2)}`}
            valueClass={displayDailyPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}
          />
        </div>
      </div>

      {/* Decorative footer */}
      <div className="px-5 py-3 bg-white/2 border-t border-white/4">
        <div className="flex items-center justify-between text-[9px] font-mono text-zinc-600">
          <span>STATUS: {account.status}</span>
          <span>{account.currency}</span>
        </div>
      </div>
    </motion.div>
  );
}

function VitalRow({ icon, label, value, valueClass }: { icon: React.ReactNode, label: string, value: string, valueClass?: string }) {
  return (
    <div className="flex items-center justify-between p-3 rounded-xl bg-white/4 border border-white/4">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-[10px] font-mono text-zinc-500 uppercase">{label}</span>
      </div>
      <span className={`text-xs font-mono font-bold ${valueClass ?? 'text-zinc-200'}`}>{value}</span>
    </div>
  );
}
