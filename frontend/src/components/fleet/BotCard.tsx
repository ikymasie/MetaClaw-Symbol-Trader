'use client';

import { useState } from 'react';
import { BotSnapshot } from '@/lib/api';
import { useKillBot, useStartBotEngine, useStopBotEngine, useTriggerBotAI } from '@/hooks/useFleet';
import {
  Activity, Bot, BrainCircuit, TrendingDown, TrendingUp,
  Square, Play, Zap, Trash2, ChevronDown, ChevronUp
} from 'lucide-react';

interface Props {
  bot: BotSnapshot;
  onSelect?: (botId: string) => void;
}

const SURVIVAL_COLORS: Record<string, string> = {
  HEALTHY: 'text-emerald-400',
  WOUNDED: 'text-amber-400',
  ORGAN_FAILURE: 'text-orange-400',
  DECEASED: 'text-red-400',
};

const APEX_COLORS: Record<string, string> = {
  DORMANT: 'text-slate-400',
  HUNTING: 'text-sky-400',
  FEEDING: 'text-violet-400',
  APEX: 'text-amber-400',
  SINGULARITY: 'text-fuchsia-400',
};

const STATUS_DOT: Record<string, string> = {
  RUNNING: 'bg-emerald-400',
  IDLE: 'bg-slate-400',
  STARTING: 'bg-amber-400',
  STOPPED: 'bg-slate-600',
  EMERGENCY_HALTED: 'bg-red-500',
  CRITICAL_STOP: 'bg-red-500',
};

function pnlClass(v: number) {
  return v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-muted-foreground';
}

export function BotCard({ bot, onSelect }: Props) {
  const [expanded, setExpanded] = useState(false);
  const killBot = useKillBot();
  const startEngine = useStartBotEngine();
  const stopEngine = useStopBotEngine();
  const triggerAI = useTriggerBotAI();

  const s = bot.status || {};
  const v = bot.vitals || {};
  const ai = bot.ai || {};
  const sentiment = bot.agent_sentiment || {};

  const isRunning = s.bot_status === 'RUNNING' || s.bot_status === 'STARTING';
  const survivalClass = SURVIVAL_COLORS[v.survival_state] || 'text-muted-foreground';
  const apexClass = APEX_COLORS[v.apex_state] || 'text-muted-foreground';
  const dotClass = STATUS_DOT[s.bot_status] || 'bg-slate-500';

  const pnl = s.daily_pnl ?? 0;
  const equity = s.equity ?? 0;
  const sentScore = sentiment.score ?? 0;
  const sentConf = sentiment.confidence ?? 0;

  return (
    <div className={`rounded-2xl border transition-all duration-200 overflow-hidden group ${
      isRunning ? 'border-emerald-500/25 bg-emerald-500/3 hover:border-emerald-500/40' : 'border-white/8 bg-white/2 hover:border-white/14'
    }`}>
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Status dot */}
        <div className={`w-2 h-2 rounded-full shrink-0 ${dotClass} ${isRunning ? 'animate-pulse' : ''}`} />

        {/* Bot icon */}
        <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
          {bot.animal ? (
            <span className="text-sm">{bot.animal === 'elephant' ? '🐘' : bot.animal === 'buffalo' ? '🦬' : bot.animal === 'rhino' ? '🦏' : bot.animal === 'leopard' ? '🐆' : bot.animal === 'lion' ? '🦁' : '🦁'}</span>
          ) : (
            <Bot className="w-3.5 h-3.5 text-primary" />
          )}
        </div>

        {/* Identity — clicking opens the detail drawer */}
        <div
          className={`flex-1 min-w-0 ${onSelect ? 'cursor-pointer' : ''}`}
          onClick={onSelect ? () => onSelect(bot.bot_id) : undefined}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white truncate">{bot.name}</span>
            {bot.leverage_mode_enabled && <Zap className="w-3 h-3 text-violet-400 fill-violet-400/20 shrink-0" />}
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-white/10 text-muted-foreground border border-white/8">
              ${(bot.capital_allocation / 1000).toFixed(0)}K
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] font-mono text-muted-foreground">{bot.symbol}</span>
            <span className="text-muted-foreground/30">·</span>
            <span className="text-[10px] font-mono text-muted-foreground">{bot.strategy?.toUpperCase()}</span>
            <span className="text-muted-foreground/30">·</span>
            <span className={`text-[10px] font-mono ${survivalClass}`}>{v.survival_state}</span>
          </div>
        </div>

        {/* P&L */}
        <div className="text-right shrink-0">
          <div className={`text-sm font-mono font-semibold tabular-nums ${pnlClass(pnl)}`}>
            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
          </div>
          <div className="text-[10px] font-mono text-muted-foreground">DAILY P&L</div>
        </div>

        {/* Expand */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors ml-1"
        >
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Quick stats bar */}
      <div className="grid grid-cols-4 border-t border-white/5">
        {[
          { label: 'EQUITY', value: `$${equity.toFixed(0)}`, mono: true },
          { label: 'APEX', value: v.apex_state || '—', className: apexClass },
          { label: 'AI CYCLES', value: ai.total_cycles ?? 0, mono: true },
          { label: 'SENTIMENT', value: sentScore !== 0 ? `${sentScore > 0 ? '+' : ''}${sentScore.toFixed(2)}` : '—', className: sentScore > 0 ? 'text-emerald-400' : sentScore < 0 ? 'text-red-400' : 'text-muted-foreground' },
        ].map((item, i) => (
          <div key={i} className="px-3 py-2 border-r border-white/5 last:border-r-0">
            <div className={`text-xs font-mono font-semibold tabular-nums ${item.className || 'text-white'}`}>
              {item.value}
            </div>
            <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-white/5 px-4 py-4 space-y-4 animate-in fade-in duration-150">

          {/* Vitals row */}
          <div className="grid grid-cols-3 gap-3">
            <Metric label="Profit %" value={`${v.profit_pct >= 0 ? '+' : ''}${(v.profit_pct ?? 0).toFixed(2)}%`} color={pnlClass(v.profit_pct ?? 0)} />
            <Metric label="Drawdown" value={`${(v.drawdown_pct ?? 0).toFixed(2)}%`} color={(v.drawdown_pct ?? 0) > 3 ? 'text-red-400' : 'text-muted-foreground'} />
            <Metric label="Position" value={`${s.position_qty ?? 0} ${s.position_side ?? 'NONE'}`} />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Metric label="Entry Price" value={s.entry_price ? `$${s.entry_price.toFixed(2)}` : '—'} />
            <Metric label="Curr Price" value={s.current_price ? `$${s.current_price.toFixed(2)}` : '—'} />
            <Metric label="Unreal. PnL" value={s.unrealized_pnl !== undefined ? `${s.unrealized_pnl >= 0 ? '+' : ''}$${s.unrealized_pnl.toFixed(2)}` : '—'} color={pnlClass(s.unrealized_pnl ?? 0)} />
          </div>

          {/* AI info */}
          {ai.last_trigger && (
            <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
              <BrainCircuit className="w-3 h-3 text-violet-400" />
              <span>Last AI trigger: <span className="text-violet-400">{ai.last_trigger}</span></span>
              {ai.last_run_at && <span>· {new Date(ai.last_run_at).toLocaleTimeString()}</span>}
            </div>
          )}

          {/* Tags */}
          {bot.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {bot.tags.map(tag => (
                <span key={tag} className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-[9px] text-primary font-mono">#{tag}</span>
              ))}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-1">
            {isRunning ? (
              <ActionButton
                icon={<Square className="w-3 h-3" />}
                label="STOP"
                onClick={() => stopEngine.mutate(bot.bot_id)}
                loading={stopEngine.isPending}
                className="text-amber-400 border-amber-500/30 hover:bg-amber-500/10"
              />
            ) : (
              <ActionButton
                icon={<Play className="w-3 h-3" />}
                label="START"
                onClick={() => startEngine.mutate(bot.bot_id)}
                loading={startEngine.isPending}
                className="text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10"
              />
            )}

            <ActionButton
              icon={<Zap className="w-3 h-3" />}
              label="AI TRIGGER"
              onClick={() => triggerAI.mutate(bot.bot_id)}
              loading={triggerAI.isPending}
              className="text-violet-400 border-violet-500/30 hover:bg-violet-500/10"
            />

            <div className="flex-1" />

            <ActionButton
              icon={<Trash2 className="w-3 h-3" />}
              label="KILL"
              onClick={() => {
                if (confirm(`Kill bot "${bot.name}"? This cannot be undone.`)) {
                  killBot.mutate(bot.bot_id);
                }
              }}
              loading={killBot.isPending}
              className="text-red-400 border-red-500/30 hover:bg-red-500/10"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="p-2.5 rounded-xl bg-white/3 border border-white/6">
      <div className={`text-xs font-mono font-semibold tabular-nums ${color || 'text-white'}`}>{value}</div>
      <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{label}</div>
    </div>
  );
}

function ActionButton({
  icon, label, onClick, loading, className
}: {
  icon: React.ReactNode; label: string; onClick: () => void;
  loading?: boolean; className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/8 text-[10px] font-mono font-semibold transition-all disabled:opacity-50 ${className}`}
    >
      {loading ? <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> : icon}
      {label}
    </button>
  );
}
