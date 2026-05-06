'use client';

import { cn } from '@/lib/utils';
import type { BotTickerInfo } from '@/hooks/useTickerBots';

interface BotSwitcherStripProps {
  bots: BotTickerInfo[];
  selectedBotId: string | null;
  onSelect: (bot: BotTickerInfo) => void;
  isLoading?: boolean;
}

const ANIMAL_EMOJI: Record<string, string> = {
  elephant: '🐘',
  buffalo: '🦬',
  rhino: '🦏',
  leopard: '🐆',
  lion: '🦁',
};

function getAnimalEmoji(tags: string[]): string {
  for (const tag of tags) {
    if (ANIMAL_EMOJI[tag]) return ANIMAL_EMOJI[tag];
  }
  return '🤖';
}

function StatusDot({ status }: { status: string }) {
  const isRunning = status === 'RUNNING';
  const isCritical = status === 'CRITICAL_STOP';
  return (
    <span
      className={cn(
        'inline-block w-1.5 h-1.5 rounded-full shrink-0',
        isRunning && 'bg-emerald-400 animate-pulse shadow-[0_0_6px] shadow-emerald-400/60',
        isCritical && 'bg-red-500 animate-pulse',
        !isRunning && !isCritical && 'bg-zinc-500',
      )}
    />
  );
}

export function BotSwitcherStrip({
  bots,
  selectedBotId,
  onSelect,
  isLoading,
}: BotSwitcherStripProps) {
  if (isLoading && bots.length === 0) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5 bg-card/30 backdrop-blur-md overflow-x-auto scrollbar-none">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 w-40 rounded-xl bg-white/5 animate-pulse shrink-0" />
        ))}
      </div>
    );
  }

  if (bots.length === 0) {
    return (
      <div className="flex items-center gap-2 px-6 py-3 border-b border-white/5 bg-card/30 backdrop-blur-md text-xs font-mono text-muted-foreground">
        <span className="w-1.5 h-1.5 rounded-full bg-zinc-600" />
        No bots deployed — deploy bots from the Fleet page to see them here
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/5 bg-card/30 backdrop-blur-md overflow-x-auto scrollbar-none shrink-0">
      {bots.map((bot) => {
        const isSelected = bot.bot_id === selectedBotId;
        const pnlPositive = bot.daily_pnl >= 0;
        const emoji = getAnimalEmoji(bot.tags);

        return (
          <button
            key={bot.bot_id}
            onClick={() => onSelect(bot)}
            className={cn(
              'group relative flex flex-col gap-0.5 px-3.5 py-2.5 rounded-xl border transition-all duration-200 shrink-0 text-left',
              'hover:bg-white/5 hover:border-primary/40 hover:shadow-[0_0_16px_-4px] hover:shadow-primary/20',
              isSelected
                ? 'bg-primary/10 border-primary/50 shadow-[0_0_20px_-4px] shadow-primary/30'
                : 'bg-white/3 border-white/8',
            )}
          >
            {/* Top row: emoji + name + status dot */}
            <div className="flex items-center gap-1.5">
              <span className="text-sm leading-none">{emoji}</span>
              <span className="font-semibold text-xs text-foreground truncate max-w-[100px]">
                {bot.name}
              </span>
              <StatusDot status={bot.bot_status} />
            </div>

            {/* Symbol badge */}
            <div className="flex items-center gap-2">
              <span className="px-1.5 py-0.5 rounded-md bg-white/8 border border-white/10 text-[10px] font-mono text-primary font-bold leading-none">
                {bot.symbol}
              </span>
              <span
                className={cn(
                  'text-[10px] font-mono font-semibold leading-none',
                  pnlPositive ? 'text-emerald-400' : 'text-red-400',
                )}
              >
                {pnlPositive ? '+' : ''}
                {bot.daily_pnl.toFixed(2)}
              </span>
            </div>

            {/* Selected indicator bar */}
            {isSelected && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 h-0.5 w-3/4 rounded-full bg-primary/60" />
            )}
          </button>
        );
      })}
    </div>
  );
}
