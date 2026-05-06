'use client';

import { useState, useEffect } from 'react';
import { BotSnapshot, tradingApi } from '@/lib/api';
import { useKillBot, useStartBotEngine, useStopBotEngine, useTriggerBotAI, useBotAIStatus, useBotAIDecisions, useUpdateBotConfig, useMarketData } from '@/hooks/useFleet';
import { TradingChart } from '@/components/dashboard/TradingChart';
import {
  X, Bot, BrainCircuit, Activity, TrendingUp, TrendingDown,
  Play, Square, Zap, Trash2, Shield, Skull, AlertTriangle, Crown,
  Flame, Loader2, AlertCircle, History, ArrowUpRight, ArrowDownRight,
  BarChart3, RefreshCw, CandlestickChart
} from 'lucide-react';

interface Props {
  bot: BotSnapshot;
  onClose: () => void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface TradeRecord {
  bot_id: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  regime: string;
  timestamp: string;
  pnl: number;
}

interface BotHistory {
  bot_id: string;
  trades: TradeRecord[];
  equity_curve: { time: string; equity: number; daily_pnl: number }[];
  total_trades: number;
  total_realized_pnl: number;
}

const SURVIVAL_COLORS: Record<string, { text: string; bg: string; border: string; pulse: boolean }> = {
  HEALTHY:       { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/25', pulse: false },
  WOUNDED:       { text: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   pulse: true  },
  ORGAN_FAILURE: { text: 'text-orange-400',  bg: 'bg-orange-500/10',  border: 'border-orange-500/40',  pulse: true  },
  DECEASED:      { text: 'text-red-500',     bg: 'bg-red-500/10',     border: 'border-red-500/50',     pulse: true  },
};

const APEX_COLORS: Record<string, string> = {
  DORMANT: 'text-slate-400', HUNTING: 'text-sky-400', FEEDING: 'text-violet-400',
  APEX: 'text-amber-400', SINGULARITY: 'text-fuchsia-400',
};

const STATUS_DOT: Record<string, string> = {
  RUNNING: 'bg-emerald-400', IDLE: 'bg-slate-400', STARTING: 'bg-amber-400',
  STOPPED: 'bg-slate-600', EMERGENCY_HALTED: 'bg-red-500', CRITICAL_STOP: 'bg-red-500',
};

function pnlClass(v: number) {
  return v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-muted-foreground';
}

export function BotDetailDrawer({ bot, onClose }: Props) {
  const [tab, setTab] = useState<'overview' | 'trades' | 'ai' | 'chart'>('overview');
  const [history, setHistory] = useState<BotHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const killBot      = useKillBot();
  const startEngine  = useStartBotEngine();
  const stopEngine   = useStopBotEngine();
  const triggerAI    = useTriggerBotAI();
  const updateConfig = useUpdateBotConfig();

  // ── Local optimistic state for demo mode toggle ──
  // Prevents the 3-second fleet poll from resetting the toggle mid-transition.
  const [localDemoMode, setLocalDemoMode] = useState<boolean>(bot.demo_mode !== false);

  // Sync from prop only when the drawer opens for a *different* bot
  useEffect(() => {
    setLocalDemoMode(bot.demo_mode !== false);
  }, [bot.bot_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isDemo = localDemoMode;

  const handleToggleDemoMode = () => {
    const newMode = !isDemo;
    if (!newMode) {
      // Switching to LIVE — require confirmation
      if (!confirm(
        `⚠️ Switch "${bot.name}" to LIVE MODE?\n\n` +
        `This will execute REAL trades on your Alpaca account.\n` +
        `Ensure your API keys and capital allocation are correct.`
      )) return;
    }
    // Optimistically update local state immediately
    setLocalDemoMode(newMode);
    updateConfig.mutate(
      { botId: bot.bot_id, updates: { demo_mode: newMode } },
      {
        // If the server rejects, revert to old state
        onError: () => setLocalDemoMode(!newMode),
      },
    );
  };

  const { data: aiStatus }    = useBotAIStatus(bot.bot_id);
  const { data: aiDecisions } = useBotAIDecisions(bot.bot_id);
  const { data: marketData, isLoading: marketLoading } = useMarketData(bot.symbol);

  const s  = bot.status  || ({} as BotSnapshot['status']);
  const v  = bot.vitals  || ({} as BotSnapshot['vitals']);
  const ai = bot.ai      || ({} as BotSnapshot['ai']);

  const isRunning      = s.bot_status === 'RUNNING';
  const survivalStyle  = SURVIVAL_COLORS[v.survival_state] ?? SURVIVAL_COLORS.HEALTHY;
  const apexClass      = APEX_COLORS[v.apex_state] ?? 'text-muted-foreground';
  const dotClass       = STATUS_DOT[s.bot_status] ?? 'bg-slate-500';
  const pnl            = s.daily_pnl ?? 0;

  // Fetch trade history when the trades tab is selected
  const fetchHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await tradingApi.getFleetBotHistory(bot.bot_id);
      setHistory(data);
    } catch (e) {
      console.error('Failed to fetch bot history:', e);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (tab === 'trades') {
      fetchHistory();
    }
  }, [tab, bot.bot_id]);

  return (
    /* Overlay */
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="relative z-10 w-full max-w-xl h-full bg-[#0d0f14] border-l border-white/8 flex flex-col shadow-2xl animate-in slide-in-from-right duration-300">

        {/* ── Header ── */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-white/8 shrink-0">
          <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${dotClass} ${isRunning ? 'animate-pulse' : ''}`} />
          <div className="w-8 h-8 rounded-xl bg-primary/15 flex items-center justify-center shrink-0">
            <Bot className="w-4 h-4 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">{bot.name}</span>
              {bot.demo_mode && (
                <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20">
                  DEMO
                </span>
              )}
            </div>
            <div className="text-[10px] font-mono text-muted-foreground mt-0.5">
              {bot.symbol} · {bot.strategy?.toUpperCase()} · {bot.bot_id}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* ── KPI Strip ── */}
        <div className="grid grid-cols-4 border-b border-white/6 shrink-0">
          {[
            { label: 'DAILY P&L', value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`, cls: pnlClass(pnl) },
            { label: 'EQUITY',    value: `$${(s.equity ?? 0).toFixed(0)}`,             cls: 'text-white'  },
            { label: 'SURVIVAL',  value: v.survival_state ?? '—',                       cls: survivalStyle.text },
            { label: 'APEX TIER', value: v.apex_state ?? '—',                           cls: apexClass     },
          ].map((k, i) => (
            <div key={i} className="px-4 py-3 border-r border-white/6 last:border-r-0">
              <div className={`text-sm font-mono font-semibold tabular-nums ${k.cls}`}>{k.value}</div>
              <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{k.label}</div>
            </div>
          ))}
        </div>

        {/* ── Tabs ── */}
        <div className="flex gap-1 px-5 pt-3 pb-0 border-b border-white/6 shrink-0">
          {(['overview', 'chart', 'trades', 'ai'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-mono uppercase tracking-widest rounded-t-lg -mb-px border border-b-0 transition-all ${
                tab === t
                  ? 'border-white/12 bg-white/5 text-white'
                  : 'border-transparent text-muted-foreground hover:text-white'
              }`}
            >
              {t === 'overview' && <Activity className="w-3 h-3" />}
              {t === 'chart' && <BarChart3 className="w-3 h-3" />}
              {t === 'trades' && <History className="w-3 h-3" />}
              {t === 'ai' && <BrainCircuit className="w-3 h-3" />}
              {t === 'overview' ? 'Overview' : t === 'chart' ? 'Chart' : t === 'trades' ? 'Trades' : 'AI Brain'}
            </button>
          ))}
        </div>

        {/* ── Scrollable Body ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {tab === 'overview' && (
            <>
              {/* Position */}
              <section>
                <SectionLabel>Position</SectionLabel>
                <div className="grid grid-cols-3 gap-2">
                  <Metric label="Entry Price"  value={s.entry_price   ? `$${s.entry_price.toFixed(2)}`    : '—'} />
                  <Metric label="Current"      value={s.current_price ? `$${s.current_price.toFixed(2)}`  : '—'} />
                  <Metric label="Unreal. PnL"  value={s.unrealized_pnl !== undefined ? `${s.unrealized_pnl >= 0 ? '+' : ''}$${s.unrealized_pnl.toFixed(2)}` : '—'} color={pnlClass(s.unrealized_pnl ?? 0)} />
                  <Metric label="Qty"          value={`${s.position_qty ?? 0}`} />
                  <Metric label="Side"         value={s.position_side ?? 'NONE'} />
                </div>
              </section>

              {/* Trading Mode */}
              <section>
                <SectionLabel>Trading Mode</SectionLabel>
                <div className={`flex items-center justify-between p-4 rounded-xl border transition-all ${
                  isDemo
                    ? 'bg-amber-500/5 border-amber-500/20'
                    : 'bg-emerald-500/5 border-emerald-500/20'
                }`}>
                  <div className="flex items-center gap-3">
                    {!isDemo && <AlertTriangle className="w-4 h-4 text-red-400" />}
                    <div>
                      <div className={`text-xs font-mono font-bold ${
                        isDemo ? 'text-amber-400' : 'text-emerald-400'
                      }`}>
                        {isDemo ? '📋 PAPER / DEMO' : '🟢 LIVE TRADING'}
                      </div>
                      <p className="text-[9px] font-mono text-muted-foreground mt-0.5">
                        {isDemo
                          ? 'Simulated — no real capital at risk'
                          : 'Executing real trades via Alpaca'}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={handleToggleDemoMode}
                    disabled={updateConfig.isPending}
                    className={`w-11 h-6 rounded-full transition-all relative shrink-0 ${
                      isDemo ? 'bg-amber-500/80' : 'bg-emerald-500/80'
                    } ${updateConfig.isPending ? 'opacity-50' : 'hover:brightness-110'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-md transition-all ${
                      isDemo ? 'left-1' : 'left-6'
                    }`} />
                  </button>
                </div>
              </section>

              {/* Vitals */}
              <section>
                <SectionLabel>Vitals</SectionLabel>
                <div className={`rounded-xl border p-4 space-y-3 ${survivalStyle.bg} ${survivalStyle.border}`}>
                  <div className={`text-sm font-bold font-mono ${survivalStyle.text} ${survivalStyle.pulse ? 'animate-pulse' : ''}`}>
                    {v.survival_state ?? 'UNKNOWN'}
                  </div>
                  <VitalBar label="Drawdown" value={v.drawdown_pct ?? 0} max={15} color="bg-red-500" />
                  <VitalBar label="Profit"   value={v.profit_pct ?? 0}  max={50} color="bg-violet-500" />
                </div>
              </section>

              {/* Tags */}
              {bot.tags?.length > 0 && (
                <section>
                  <SectionLabel>Tags</SectionLabel>
                  <div className="flex flex-wrap gap-1.5">
                    {bot.tags.map(tag => (
                      <span key={tag} className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-[9px] text-primary font-mono">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}

          {/* ── CHART TAB ── */}
          {tab === 'chart' && (
            <>
              <section>
                <SectionLabel>Live Market · {bot.symbol}</SectionLabel>
                <div className="h-[350px] rounded-xl overflow-hidden border border-white/6">
                  {marketLoading && !marketData ? (
                    <div className="flex items-center justify-center h-full gap-3">
                      <Loader2 className="w-5 h-5 text-primary animate-spin" />
                      <span className="text-xs font-mono text-zinc-500">Loading {bot.symbol} chart…</span>
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
                      <p className="text-xs font-mono">No market data for {bot.symbol}</p>
                    </div>
                  )}
                </div>
              </section>

              {/* BB Stats */}
              {marketData?.bollinger?.length ? (() => {
                const lastBB = marketData.bollinger[marketData.bollinger.length - 1];
                const lastPrice = marketData.price_data[marketData.price_data.length - 1];
                const bbWidth = ((lastBB.upper - lastBB.lower) / lastBB.middle * 100);
                const isBullish = lastPrice.close > lastBB.middle;
                return (
                  <section>
                    <SectionLabel>Technical Snapshot</SectionLabel>
                    <div className="grid grid-cols-3 gap-2">
                      <Metric label="BB Width" value={`${bbWidth.toFixed(2)}%`} />
                      <Metric
                        label="Trend Bias"
                        value={isBullish ? 'BULLISH' : 'BEARISH'}
                        color={isBullish ? 'text-emerald-400' : 'text-rose-400'}
                      />
                      <Metric
                        label="Spot"
                        value={`$${lastPrice.close.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
                      />
                    </div>
                  </section>
                );
              })() : null}
            </>
          )}

          {/* ── TRADES TAB ── */}
          {tab === 'trades' && (
            <>
              {/* Summary Strip */}
              <section>
                <div className="flex items-center justify-between mb-3">
                  <SectionLabel>Trade History</SectionLabel>
                  <button
                    onClick={fetchHistory}
                    disabled={historyLoading}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg text-[9px] font-mono text-muted-foreground hover:text-white hover:bg-white/5 border border-white/6 transition-all disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3 h-3 ${historyLoading ? 'animate-spin' : ''}`} />
                    REFRESH
                  </button>
                </div>

                {/* Trade summary cards */}
                {history && (
                  <div className="grid grid-cols-3 gap-2 mb-4">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20">
                      <div className="text-lg font-mono font-bold text-white tabular-nums">{history.total_trades}</div>
                      <div className="text-[9px] font-mono text-blue-400 mt-0.5">TOTAL TRADES</div>
                    </div>
                    <div className="p-3 rounded-xl bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20">
                      <div className={`text-lg font-mono font-bold tabular-nums ${pnlClass(history.total_realized_pnl)}`}>
                        {history.total_realized_pnl >= 0 ? '+' : ''}${history.total_realized_pnl.toFixed(2)}
                      </div>
                      <div className="text-[9px] font-mono text-emerald-400 mt-0.5">REALIZED P&L</div>
                    </div>
                    <div className="p-3 rounded-xl bg-gradient-to-br from-violet-500/10 to-violet-600/5 border border-violet-500/20">
                      <div className="text-lg font-mono font-bold text-white tabular-nums">
                        {history.trades.filter(t => t.pnl > 0).length}/{history.trades.filter(t => t.side === 'sell').length || 0}
                      </div>
                      <div className="text-[9px] font-mono text-violet-400 mt-0.5">WIN / CLOSED</div>
                    </div>
                  </div>
                )}
              </section>

              {/* Trade List */}
              <section>
                {historyLoading && !history ? (
                  <div className="flex flex-col items-center justify-center py-16 gap-3">
                    <Loader2 className="w-6 h-6 text-primary animate-spin" />
                    <p className="text-xs font-mono text-muted-foreground">Loading trade history…</p>
                  </div>
                ) : !history?.trades?.length ? (
                  <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
                    <div className="w-12 h-12 rounded-2xl bg-white/3 border border-white/8 flex items-center justify-center">
                      <BarChart3 className="w-5 h-5 text-muted-foreground/50" />
                    </div>
                    <p className="text-xs font-mono">No trades recorded yet.</p>
                    <p className="text-[10px] font-mono text-muted-foreground/60 max-w-[250px] text-center">
                      Trades will appear here once the bot generates BUY/SELL signals from Bollinger Band analysis.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {history.trades.map((trade, i) => (
                      <TradeRow key={`${trade.timestamp}-${i}`} trade={trade} />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}

          {tab === 'ai' && (
            <>
              {/* AI Summary */}
              <section>
                <SectionLabel>AI Brain Status</SectionLabel>
                <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4 space-y-2">
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Enabled</span>
                    <span className={ai.enabled ? 'text-emerald-400' : 'text-slate-500'}>{ai.enabled ? 'YES' : 'NO'}</span>
                  </div>
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">State</span>
                    <span className="text-violet-300">{aiStatus?.state ?? '—'}</span>
                  </div>
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Total Cycles</span>
                    <span className="text-white">{ai.total_cycles ?? 0}</span>
                  </div>
                  {ai.last_trigger && (
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-muted-foreground">Last Trigger</span>
                      <span className="text-violet-400 truncate max-w-[200px]">{ai.last_trigger}</span>
                    </div>
                  )}
                  {ai.last_run_at && (
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-muted-foreground">Last Run</span>
                      <span className="text-slate-300">{new Date(ai.last_run_at).toLocaleTimeString()}</span>
                    </div>
                  )}
                </div>
              </section>

              {/* AI Decisions */}
              <section>
                <SectionLabel>Decision Log</SectionLabel>
                {!aiDecisions?.decisions?.length ? (
                  <div className="flex flex-col items-center justify-center py-10 text-muted-foreground gap-2">
                    <AlertCircle className="w-5 h-5" />
                    <p className="text-xs font-mono">No AI decisions recorded for this bot.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {aiDecisions.decisions.slice(0, 15).map((d: any, i: number) => (
                      <div key={i} className="p-3 rounded-xl border border-white/6 bg-white/2 space-y-1.5">
                        <div className="flex justify-between items-center">
                          <span className="text-[10px] font-mono text-muted-foreground">
                            {new Date(d.timestamp).toLocaleString()}
                          </span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${
                            d.applied
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-white/5 text-slate-400 border border-white/8'
                          }`}>
                            {d.applied ? 'APPLIED' : 'REJECTED'}
                          </span>
                        </div>
                        <p className="text-xs text-slate-300 leading-snug">{d.reasoning}</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>

        {/* ── Action Footer ── */}
        <div className="flex items-center gap-2 px-5 py-4 border-t border-white/8 shrink-0">
          {isRunning ? (
            <FooterBtn
              icon={stopEngine.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
              label="STOP"
              onClick={() => stopEngine.mutate(bot.bot_id)}
              disabled={stopEngine.isPending}
              cls="text-amber-400 border-amber-500/30 hover:bg-amber-500/10"
            />
          ) : (
            <FooterBtn
              icon={startEngine.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
              label="START"
              onClick={() => startEngine.mutate(bot.bot_id)}
              disabled={startEngine.isPending}
              cls="text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10"
            />
          )}
          <FooterBtn
            icon={triggerAI.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            label="AI TRIGGER"
            onClick={() => triggerAI.mutate(bot.bot_id)}
            disabled={triggerAI.isPending}
            cls="text-violet-400 border-violet-500/30 hover:bg-violet-500/10"
          />
          <div className="flex-1" />
          <FooterBtn
            icon={<Trash2 className="w-3 h-3" />}
            label="KILL BOT"
            onClick={() => {
              if (confirm(`Kill bot "${bot.name}"? This cannot be undone.`)) {
                killBot.mutate(bot.bot_id);
                onClose();
              }
            }}
            disabled={killBot.isPending}
            cls="text-red-400 border-red-500/30 hover:bg-red-500/10"
          />
        </div>
      </div>
    </div>
  );
}

// ── Trade Row Component ───────────────────────────────────────────────────────

function TradeRow({ trade }: { trade: TradeRecord }) {
  const isBuy = trade.side.toLowerCase() === 'buy';
  const hasPnl = trade.pnl !== 0;
  const isWin = trade.pnl > 0;
  const ts = new Date(trade.timestamp);

  return (
    <div className={`group relative flex items-center gap-3 px-3.5 py-3 rounded-xl border transition-all hover:bg-white/[0.03] ${
      isBuy
        ? 'border-emerald-500/10 hover:border-emerald-500/25'
        : 'border-red-500/10 hover:border-red-500/25'
    }`}>
      {/* Direction icon */}
      <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
        isBuy
          ? 'bg-emerald-500/10 border border-emerald-500/20'
          : 'bg-red-500/10 border border-red-500/20'
      }`}>
        {isBuy
          ? <ArrowUpRight className="w-4 h-4 text-emerald-400" />
          : <ArrowDownRight className="w-4 h-4 text-red-400" />
        }
      </div>

      {/* Trade info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
            isBuy
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              : 'bg-red-500/10 text-red-400 border border-red-500/20'
          }`}>
            {trade.side.toUpperCase()}
          </span>
          <span className="text-xs font-semibold text-white">{trade.symbol}</span>
          <span className="text-[9px] font-mono text-muted-foreground/60 px-1.5 py-0.5 rounded bg-white/3">
            {trade.regime}
          </span>
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-[10px] font-mono text-muted-foreground">
            {ts.toLocaleTimeString()} · {ts.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
          </span>
        </div>
      </div>

      {/* Price & Qty */}
      <div className="text-right shrink-0">
        <div className="text-xs font-mono font-semibold text-white tabular-nums">
          ${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        <div className="text-[10px] font-mono text-muted-foreground">
          ×{trade.qty}
        </div>
      </div>

      {/* P&L */}
      <div className="text-right shrink-0 w-20">
        {hasPnl ? (
          <div className={`text-sm font-mono font-bold tabular-nums ${isWin ? 'text-emerald-400' : 'text-red-400'}`}>
            {isWin ? '+' : ''}${trade.pnl.toFixed(2)}
          </div>
        ) : (
          <div className="text-[10px] font-mono text-muted-foreground">—</div>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="text-[9px] font-mono font-semibold uppercase tracking-widest text-muted-foreground">
        {children}
      </span>
      <span className="flex-1 h-px bg-white/6" />
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="p-2.5 rounded-xl bg-white/3 border border-white/6">
      <div className={`text-xs font-mono font-semibold tabular-nums ${color ?? 'text-white'}`}>{value}</div>
      <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{label}</div>
    </div>
  );
}

function VitalBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
        <span>{label}</span>
        <span>{value.toFixed(2)}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-white/8">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FooterBtn({ icon, label, onClick, disabled, cls }: {
  icon: React.ReactNode; label: string; onClick: () => void; disabled?: boolean; cls?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/8 text-[10px] font-mono font-semibold transition-all disabled:opacity-50 ${cls}`}
    >
      {icon}
      {label}
    </button>
  );
}
