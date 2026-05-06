'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useAlpacaAccount, FLEET_KEY } from '@/hooks/useFleet';
import { Wifi, WifiOff, Rocket, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';
import { FleetStatus } from '@/lib/api';

interface Props {
  fleet: FleetStatus | undefined;
  onDeployClick: () => void;
  onRefresh: () => void;
}

export function FleetSummaryBar({ fleet, onDeployClick, onRefresh }: Props) {
  const queryClient = useQueryClient();
  const { data: account } = useAlpacaAccount();
  const [wsAlive, setWsAlive] = useState(false);

  // Derive WS liveness from how fresh the fleet polling data is
  useEffect(() => {
    const check = () => {
      const cached: any = queryClient.getQueryData([FLEET_KEY]);
      if (cached?.summary?.timestamp) {
        const ageMs = Date.now() - new Date(cached.summary.timestamp).getTime();
        setWsAlive(ageMs < 6000);
      } else {
        setWsAlive(false);
      }
    };
    check();
    const id = setInterval(check, 1000);
    return () => clearInterval(id);
  }, [queryClient]);

  const summary = fleet?.summary;
  const config  = fleet?.fleet_config;
  const totalPnl = summary?.total_daily_pnl ?? 0;
  const pnlPositive = totalPnl >= 0;

  const drift = account?.daily_pnl_pct ?? 0;
  const driftPositive = drift >= 0;

  return (
    <div className="border-b border-white/8 bg-card/40 backdrop-blur-sm">
      <div className="max-w-[1600px] mx-auto px-6 py-2.5 flex items-center gap-3">

        {/* Summary pills */}
        <div className="flex items-center gap-2 flex-1 flex-wrap">
          <Pill
            dot={summary && summary.running_bots > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}
            label="ACTIVE"
            value={summary ? `${summary.running_bots} / ${summary.total_bots}` : '— / —'}
          />
          <Pill
            dot={driftPositive ? 'bg-emerald-400' : 'bg-red-400'}
            label="DAILY DRIFT"
            value={account ? `${driftPositive ? '+' : ''}${drift.toFixed(2)}%` : '—'}
            valueClass={driftPositive ? 'text-emerald-400' : 'text-red-400'}
            icon={driftPositive ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
          />
          <Pill
            dot={pnlPositive ? 'bg-emerald-400' : 'bg-red-400'}
            label="FLEET P&L"
            value={summary ? `${pnlPositive ? '+' : ''}$${totalPnl.toFixed(2)}` : '—'}
            valueClass={pnlPositive ? 'text-emerald-400' : 'text-red-400'}
          />
          <Pill
            dot="bg-sky-400"
            label="NET EQUITY"
            value={account ? `$${account.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : (summary ? `$${summary.total_equity.toFixed(0)}` : '—')}
          />
          {config?.max_bots && (
            <Pill
              dot={
                summary && summary.total_bots >= config.max_bots
                  ? 'bg-amber-400'
                  : 'bg-slate-600'
              }
              label="CAPACITY"
              value={summary ? `${summary.total_bots} / ${config.max_bots}` : `— / ${config.max_bots}`}
            />
          )}

          {/* WS liveness */}
          <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border border-white/8 text-[10px] font-mono ${wsAlive ? 'text-emerald-400' : 'text-amber-400'}`}>
            {wsAlive
              ? <><Wifi className="w-3 h-3" /><span className="animate-pulse">LIVE</span></>
              : <><WifiOff className="w-3 h-3" /><span>POLLING</span></>
            }
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onRefresh}
            className="p-2 rounded-xl border border-white/8 text-muted-foreground hover:text-white hover:border-white/20 transition-all"
            title="Refresh fleet"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onDeployClick}
            disabled={!!(summary && config && summary.total_bots >= config.max_bots)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-bold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-primary/10"
          >
            <Rocket className="w-3.5 h-3.5" />
            DEPLOY BOT
          </button>
        </div>
      </div>
    </div>
  );
}

function Pill({
  dot, label, value, valueClass, icon,
}: {
  dot: string; label: string; value: string; valueClass?: string; icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-white/4 border border-white/8">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
      <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">{label}</span>
      <div className="flex items-center gap-1">
        {icon}
        <span className={`text-xs font-mono font-semibold tabular-nums ${valueClass ?? 'text-white'}`}>{value}</span>
      </div>
    </div>
  );
}
