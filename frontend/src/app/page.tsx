'use client';

import { useState, useMemo } from 'react';

import { useFleetStatus, useFleetConfig, useMarketData, useAvailableSymbols } from '@/hooks/useFleet';
import { FleetSummaryBar } from '@/components/dashboard/FleetSummaryBar';
import { FleetBotGrid } from '@/components/dashboard/FleetBotGrid';
import { BotDetailDrawer } from '@/components/dashboard/BotDetailDrawer';
import { AccountVitalsCard } from '@/components/dashboard/AccountVitalsCard';
import { TradingChart } from '@/components/dashboard/TradingChart';
import { BotWizard } from '@/components/fleet/BotWizard';
import { FleetSettings } from '@/components/fleet/FleetSettings';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertTriangle, Loader2, ShieldAlert, ChevronDown, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react';
import type { BotSnapshot, FleetStatus } from '@/lib/api';

type Filter = 'all' | 'running' | 'stopped';

export default function Dashboard() {
  const { data: fleet, isLoading, error, refetch } = useFleetStatus();
  const { data: fleetConfig } = useFleetConfig();
  const { data: symbolsData } = useAvailableSymbols();

  const [filter, setFilter]         = useState<Filter>('all');
  const [selectedBotId, setSelectedBotId] = useState<string | null>(null);
  const [showDeploy, setShowDeploy]   = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const fleetData = fleet as FleetStatus | undefined;
  const bots: BotSnapshot[] = fleetData?.bots ?? [];
  const config = fleetData?.fleet_config;

  // ── Market Pulse ────────────────────────────────────────
  
  // Dynamically derive watchlist from available MT5 symbols + active bots
  const watchlistSymbols = useMemo(() => {
    const available = symbolsData?.symbols?.map(s => s.name) ?? [];
    const botSymbols = bots.map(b => b.symbol);
    
    // Combine and remove duplicates
    const combined = Array.from(new Set([...botSymbols, ...available]));
    
    // If we have too many, let's prioritize bot symbols and a few majors
    // For now, we'll just return the combined list (select handles large lists okay-ish)
    // But we might want to limit to top 50 if it's crazy
    return combined.slice(0, 100);
  }, [symbolsData, bots]);

  // Default to first running bot's symbol, fallback to first available or BTCUSD
  const defaultSymbol = useMemo(() => {
    const running = bots.find(b => b.status?.bot_status === 'RUNNING');
    if (running) return running.symbol;
    if (watchlistSymbols.length > 0) return watchlistSymbols[0];
    return 'BTCUSD';
  }, [bots, watchlistSymbols]);

  const [pulseSymbol, setPulseSymbol] = useState<string | null>(null);
  const activeSymbol = pulseSymbol ?? defaultSymbol;
  const { data: marketData, isLoading: marketLoading } = useMarketData(activeSymbol);

  const selectedBot = selectedBotId
    ? bots.find((b) => b.bot_id === selectedBotId) ?? null
    : null;

  // ── Loading state ──────────────────────────────────────────
  if (isLoading && bots.length === 0) {
    return (
      <div className="flex h-[calc(100vh-48px)] w-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-mono text-muted-foreground tracking-widest uppercase">
            Connecting to Fleet...
          </p>
        </div>
      </div>
    );
  }

  // ── Connection error ───────────────────────────────────────
  if (error) {
    return (
      <div className="flex h-[calc(100vh-48px)] w-screen items-center justify-center bg-background p-6">
        <div className="max-w-sm text-center space-y-4">
          <AlertTriangle className="w-10 h-10 text-red-400 mx-auto" />
          <h3 className="text-sm font-semibold text-white">Backend Offline</h3>
          <p className="text-xs font-mono text-muted-foreground">
            Cannot reach the TradeClaw execution engine.<br />
            Make sure the backend is running on{' '}
            <span className="text-primary">localhost:8000</span>
          </p>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 rounded-xl bg-primary/20 border border-primary/30 text-primary text-xs font-mono hover:bg-primary/30 transition-all"
          >
            RETRY CONNECTION
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background selection:bg-primary/20">

      {/* ── Fleet summary header ─────────────────────────────── */}
      <FleetSummaryBar
        fleet={fleetData}
        onDeployClick={() => setShowDeploy(true)}
        onRefresh={() => refetch()}
      />

      {/* ── Fleet-wide alerts ────────────────────────────────── */}
      <div className="max-w-[1600px] mx-auto w-full px-6 pt-4 space-y-2">
        {config?.global_risk_enabled && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-amber-500/30 bg-amber-500/8">
            <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
            <span className="text-xs font-mono text-amber-300">
              Fleet Risk Kill Switch active — drawdown limit:{' '}
              <span className="text-amber-400 font-semibold">{config.max_fleet_drawdown_pct}%</span>
            </span>
          </div>
        )}
      </div>

      {/* ── Market Pulse — Always-On Chart ─────────────────── */}
      <div className="max-w-[1600px] mx-auto w-full px-6 pt-4">
        <div className="rounded-2xl border border-white/6 bg-white/[0.02] overflow-hidden">
          {/* Chart Header */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 px-5 py-3 border-b border-white/6">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-primary/15 flex items-center justify-center border border-primary/20">
                <BarChart3 className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-white tracking-tight uppercase">
                  Market Pulse
                </h2>
                <p className="text-[9px] font-mono text-zinc-500 tracking-widest">
                  {activeSymbol} · 1M BARS · BOLLINGER BANDS
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              {/* Quick price stat */}
              {marketData?.price_data?.length ? (() => {
                const latest = marketData.price_data[marketData.price_data.length - 1];
                const prev = marketData.price_data[Math.max(0, marketData.price_data.length - 2)];
                const change = latest.close - prev.close;
                const changePct = prev.close > 0 ? (change / prev.close) * 100 : 0;
                return (
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <div className="text-[9px] font-mono text-zinc-500 uppercase">Price</div>
                      <div className="text-sm font-black text-white tabular-nums">
                        ${latest.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    </div>
                    <div className={`flex items-center gap-1 text-xs font-bold tabular-nums ${change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {change >= 0 ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                      {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
                    </div>
                  </div>
                );
              })() : null}

              {/* Symbol Selector */}
              <div className="relative group">
                <select
                  value={activeSymbol}
                  onChange={(e) => setPulseSymbol(e.target.value)}
                  className="appearance-none bg-zinc-900 border border-white/8 rounded-xl px-3 py-1.5 pr-8 text-[10px] font-mono font-bold text-zinc-300 hover:border-white/20 transition-all cursor-pointer outline-none focus:ring-1 focus:ring-primary/50"
                >
                  {watchlistSymbols.map(sym => (
                    <option key={sym} value={sym}>{sym}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-zinc-500 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* Chart Body */}
          <div className="h-[400px]">
            {marketLoading && !marketData ? (
              <div className="flex items-center justify-center h-full gap-3">
                <Loader2 className="w-5 h-5 text-primary animate-spin" />
                <span className="text-xs font-mono text-zinc-500">Loading {activeSymbol} data…</span>
              </div>
            ) : marketData?.price_data?.length ? (
              <TradingChart
                priceData={marketData.price_data}
                bollingerData={marketData.bollinger ?? []}
                markers={[]}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-600">
                <BarChart3 className="w-8 h-8 opacity-30" />
                <p className="text-xs font-mono">No market data available for {activeSymbol}</p>
                <p className="text-[10px] font-mono text-zinc-700">Check MT5 API keys and symbol availability</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Main content ─────────────────────────────────────── */}
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-6 ring-1 ring-white/5">
        <div className="flex flex-col lg:flex-row gap-6">
          
          {/* Left Column: Fleet Grid */}
          <div className="flex-1 space-y-6">
            <FleetBotGrid
              bots={bots}
              filter={filter}
              onFilterChange={setFilter}
              onSelectBot={(id) => setSelectedBotId(id)}
              onDeployClick={() => setShowDeploy(true)}
              isLoading={isLoading}
            />
          </div>

          {/* Right Column: Vitals Sidebar */}
          <aside className="w-full lg:w-80 space-y-6 shrink-0">
            <AccountVitalsCard />
            
            {/* Market sentiment or other global trackers can go here */}
            <div className="p-4 rounded-2xl border border-white/4 bg-white/2 text-[10px] font-mono text-zinc-600">
              <p className="uppercase tracking-widest mb-2 opacity-50">Operational Memo</p>
              <p className="leading-relaxed">
                All bots execute via the MT5 terminal. Account type (demo/live) is determined by your MT5 credentials.
              </p>
            </div>
          </aside>
        </div>
      </main>

      {/* ── Footer ───────────────────────────────────────────── */}
      <footer className="px-6 py-4 border-t bg-card/20 text-[10px] text-muted-foreground flex justify-between items-center font-mono">
        <div>© 2024 TradeClaw Autonomous Fleet Command v2.0</div>
        <div className="flex gap-4">
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" /> API: OK
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" /> FLEET: {bots.length} bots
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" /> MT5: ACTIVE
          </span>
        </div>
      </footer>

      {/* ── Bot detail drawer ─────────────────────────────────── */}
      {selectedBot && (
        <BotDetailDrawer
          bot={selectedBot}
          onClose={() => setSelectedBotId(null)}
        />
      )}

      {/* ── Deploy wizard modal ───────────────────────────────── */}
      {showDeploy && (
        <BotWizard
          onClose={() => setShowDeploy(false)}
          onDeployed={() => { setShowDeploy(false); refetch(); }}
        />
      )}

      {/* ── Fleet settings modal ──────────────────────────────── */}
      {showSettings && fleetConfig && (
        <FleetSettings config={fleetConfig} onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}
