'use client';

import { cn } from '@/lib/utils';
import type { TickerBotContext } from '@/hooks/useAlpacaTicker';
import { TrendingUp, TrendingDown, Target, Zap, DollarSign } from 'lucide-react';

interface BotDetailPanelProps {
  bots: TickerBotContext[];
  symbol: string;
}

const STATUS_COLORS: Record<string, string> = {
  RUNNING: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  IDLE: 'text-zinc-400 bg-zinc-400/10 border-zinc-400/30',
  STOPPED: 'text-zinc-500 bg-zinc-500/10 border-zinc-500/30',
  CRITICAL_STOP: 'text-red-400 bg-red-400/10 border-red-400/30',
  PAUSED: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
};

function Stat({
  label,
  value,
  positive,
  icon: Icon,
}: {
  label: string;
  value: string;
  positive?: boolean;
  icon?: React.ElementType;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-[9px] font-mono text-muted-foreground uppercase tracking-wider">
        {Icon && <Icon className="w-3 h-3" />}
        {label}
      </div>
      <div
        className={cn(
          'text-sm font-bold font-mono',
          positive === true && 'text-emerald-400',
          positive === false && 'text-red-400',
          positive === undefined && 'text-foreground',
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function BotDetailPanel({ bots, symbol }: BotDetailPanelProps) {
  if (bots.length === 0) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <p className="text-xs font-mono text-muted-foreground text-center pt-8">
          No bots actively trading {symbol}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-3 overflow-y-auto">
      {bots.map((bot) => {
        const hasPosition = bot.position_qty !== 0;
        const isLong = bot.position_side === 'long';
        const statusClass = STATUS_COLORS[bot.bot_status] ?? STATUS_COLORS['IDLE'];

        return (
          <div
            key={bot.bot_id}
            className="rounded-xl border border-white/8 bg-white/3 p-3 flex flex-col gap-3 hover:bg-white/5 transition-colors"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold text-foreground truncate">{bot.name}</span>
                <span className="text-[10px] font-mono text-muted-foreground">{bot.bot_id.slice(0, 8)}&hellip;</span>
              </div>
              <span
                className={cn(
                  'text-[10px] font-mono font-bold px-2 py-1 rounded-md border shrink-0',
                  statusClass,
                )}
              >
                {bot.bot_status}
              </span>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <Stat
                label="Daily P&L"
                value={`${bot.daily_pnl >= 0 ? '+' : ''}$${bot.daily_pnl.toFixed(2)}`}
                positive={bot.daily_pnl >= 0}
                icon={DollarSign}
              />
              <Stat
                label="Equity"
                value={`$${bot.equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              />
              <Stat
                label="Unrealized"
                value={`${bot.unrealized_pnl >= 0 ? '+' : ''}$${bot.unrealized_pnl.toFixed(2)}`}
                positive={bot.unrealized_pnl >= 0}
              />
              <Stat
                label="Price"
                value={bot.current_price ? `$${bot.current_price.toFixed(2)}` : '—'}
              />
            </div>

            {/* Position info */}
            {hasPosition && (
              <div className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-2">
                {isLong ? (
                  <TrendingUp className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-400 shrink-0" />
                )}
                <div className="flex flex-col gap-0.5 text-[10px] font-mono">
                  <span className={cn('font-bold', isLong ? 'text-emerald-400' : 'text-red-400')}>
                    {bot.position_side.toUpperCase()} × {Math.abs(bot.position_qty)}
                  </span>
                  {bot.entry_price > 0 && (
                    <span className="text-muted-foreground">
                      Entry @ ${bot.entry_price.toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Last signal */}
            {bot.last_signal && (
              <div className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground">
                <Zap className="w-3 h-3 text-amber-400 shrink-0" />
                <span className="truncate">{bot.last_signal}</span>
              </div>
            )}

            {/* Last Bollinger */}
            {bot.bollinger_last?.upper && (
              <div className="flex items-center gap-3 text-[10px] font-mono text-muted-foreground border-t border-white/5 pt-2 mt-1">
                <span className="text-indigo-400">BB</span>
                <span>↑ {bot.bollinger_last.upper?.toFixed(2)}</span>
                <span className="text-muted-foreground/60">— {bot.bollinger_last.middle?.toFixed(2)}</span>
                <span>↓ {bot.bollinger_last.lower?.toFixed(2)}</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
