'use client';

import { useState } from 'react';
import { useFleetStatus, useFleetConfig } from '@/hooks/useFleet';
import { BotCard } from '@/components/fleet/BotCard';
import { BotWizard } from '@/components/fleet/BotWizard';
import { FleetSettings } from '@/components/fleet/FleetSettings';
import type { BotSnapshot, FleetStatus } from '@/lib/api';
import {
  Rocket, Settings2,
  Bot, Zap, RefreshCw, AlertTriangle, Loader2, ShieldAlert
} from 'lucide-react';

export default function FleetPage() {
  const { data: fleet, isLoading, error, refetch } = useFleetStatus();
  const { data: fleetConfig } = useFleetConfig();
  const [showDeploy, setShowDeploy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [filter, setFilter] = useState<'all' | 'running' | 'stopped'>('all');

  const summary = (fleet as FleetStatus | undefined)?.summary;
  const bots: BotSnapshot[] = (fleet as FleetStatus | undefined)?.bots ?? [];
  const config = (fleet as FleetStatus | undefined)?.fleet_config;

  const filtered: BotSnapshot[] = bots.filter((b: BotSnapshot) => {
    if (filter === 'running') return b.status?.bot_status === 'RUNNING';
    if (filter === 'stopped') return b.status?.bot_status !== 'RUNNING';
    return true;
  });

  const totalPnl = summary?.total_daily_pnl ?? 0;
  const atCap = summary && summary.total_bots >= (config?.max_bots ?? 10);

  return (
    <div className="min-h-screen bg-background">

      {/* ── Page Header ────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-white/8 bg-background/80 backdrop-blur-xl">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between gap-6">

          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/20 flex items-center justify-center">
              <Zap className="w-4.5 h-4.5 text-primary" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white tracking-wide">FLEET COMMAND</h1>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
                TradeClaw Autonomous Bot Fleet
              </p>
            </div>
          </div>

          {/* Summary Pills */}
          {summary && (
            <div className="flex items-center gap-3 flex-1 justify-center">
              <StatPill
                label="ACTIVE"
                value={`${summary.running_bots}/${summary.total_bots}`}
                dot="bg-emerald-400"
                glow={summary.running_bots > 0}
              />
              <StatPill
                label="CAPACITY"
                value={`${summary.total_bots}/${config?.max_bots ?? '?'}`}
                dot={atCap ? 'bg-amber-400' : 'bg-slate-500'}
              />
              <StatPill
                label="FLEET P&L"
                value={`${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}`}
                dot={totalPnl >= 0 ? 'bg-emerald-400' : 'bg-red-400'}
                valueClass={totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}
              />
              <StatPill
                label="EQUITY"
                value={`$${(summary.total_equity).toFixed(0)}`}
                dot="bg-sky-400"
              />
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => refetch()}
              className="p-2 rounded-xl border border-white/8 text-muted-foreground hover:text-white hover:border-white/20 transition-all"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setShowSettings(true)}
              className="flex items-center gap-2 px-3 py-2 rounded-xl border border-white/8 text-xs font-mono text-muted-foreground hover:text-white hover:border-white/20 transition-all"
            >
              <Settings2 className="w-3.5 h-3.5" />
              SETTINGS
            </button>
            <button
              onClick={() => setShowDeploy(true)}
              disabled={atCap}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              <Rocket className="w-3.5 h-3.5" />
              DEPLOY BOT
            </button>
          </div>
        </div>
      </header>

      {/* ── Main Content ───────────────────────────────────── */}
      <main className="max-w-[1600px] mx-auto px-6 py-8 space-y-6">

        {/* Fleet status alert */}
        {config?.global_risk_enabled && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-amber-500/30 bg-amber-500/8">
            <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
            <div className="text-xs font-mono text-amber-300">
              Fleet Risk Kill Switch is active — drawdown limit: <span className="text-amber-400 font-semibold">{config.max_fleet_drawdown_pct}%</span>
            </div>
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-24">
            <div className="flex flex-col items-center gap-4 text-center">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-xs font-mono text-muted-foreground uppercase tracking-widest">
                Connecting to Fleet...
              </p>
            </div>
          </div>
        )}

        {/* Error */}
        {error && !isLoading && (
          <div className="flex items-center justify-center py-24">
            <div className="max-w-sm text-center space-y-4">
              <AlertTriangle className="w-10 h-10 text-red-400 mx-auto" />
              <h3 className="text-sm font-semibold text-white">Backend Offline</h3>
              <p className="text-xs font-mono text-muted-foreground">
                Cannot reach the TradeClaw execution engine.<br />
                Make sure the backend is running on <span className="text-primary">localhost:8000</span>
              </p>
              <button onClick={() => refetch()} className="px-4 py-2 rounded-xl bg-primary/20 border border-primary/30 text-primary text-xs font-mono hover:bg-primary/30 transition-all">
                RETRY CONNECTION
              </button>
            </div>
          </div>
        )}

        {/* Bot Grid */}
        {!isLoading && !error && (
          <>
            {/* Filter tabs */}
            <div className="flex items-center gap-1">
              {(['all', 'running', 'stopped'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 rounded-xl text-[10px] font-mono uppercase tracking-widest transition-all ${
                    filter === f
                      ? 'bg-primary/20 text-primary border border-primary/30'
                      : 'text-muted-foreground hover:text-white border border-transparent hover:border-white/8'
                  }`}
                >
                  {f} {f === 'all' && bots.length > 0 && `(${bots.length})`}
                  {f === 'running' && `(${bots.filter((b: BotSnapshot) => b.status?.bot_status === 'RUNNING').length})`}
                  {f === 'stopped' && `(${bots.filter((b: BotSnapshot) => b.status?.bot_status !== 'RUNNING').length})`}
                </button>
              ))}
            </div>

            {/* Empty state */}
            {filtered.length === 0 && (
              <div className="flex flex-col items-center justify-center py-28 text-center">
                <div className="w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-6">
                  <Bot className="w-7 h-7 text-primary/60" />
                </div>
                <h3 className="text-sm font-semibold text-white mb-2">
                  {filter === 'all' ? 'Fleet is Empty' : `No ${filter} bots`}
                </h3>
                <p className="text-xs font-mono text-muted-foreground mb-6 max-w-xs">
                  {filter === 'all'
                    ? 'Deploy your first autonomous bot to begin trading. Each bot runs completely independently with its own AI brain and sub-agent pool.'
                    : `No bots currently ${filter}.`
                  }
                </p>
                {filter === 'all' && (
                  <button
                    onClick={() => setShowDeploy(true)}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-semibold hover:bg-primary/90 transition-all"
                  >
                    <Rocket className="w-3.5 h-3.5" />
                    DEPLOY FIRST BOT
                  </button>
                )}
              </div>
            )}

            {/* Bot Cards Grid */}
            {filtered.length > 0 && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {filtered.map(bot => (
                  <BotCard key={bot.bot_id} bot={bot} />
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {/* Modals */}
      {showDeploy && (
        <BotWizard onClose={() => setShowDeploy(false)} onDeployed={() => { setShowDeploy(false); refetch(); }} />
      )}
      {showSettings && fleetConfig && (
        <FleetSettings config={fleetConfig} onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}

function StatPill({
  label, value, dot, glow, valueClass
}: {
  label: string;
  value: string;
  dot: string;
  glow?: boolean;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/4 border border-white/8">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot} ${glow ? 'animate-pulse' : ''}`} />
      <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">{label}</span>
      <span className={`text-xs font-mono font-semibold tabular-nums ${valueClass || 'text-white'}`}>{value}</span>
    </div>
  );
}
