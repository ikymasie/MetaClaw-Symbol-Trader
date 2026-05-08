'use client';

import { cn } from '@/lib/utils';
import type { MT5Bar, MT5Quote, TickerBotContext } from '@/hooks/useMT5Ticker';
import {
  TrendingUp, TrendingDown, Activity, Wifi, WifiOff,
  DollarSign, BarChart2, Target, Layers,
} from 'lucide-react';

interface TickerStatsBarProps {
  symbol: string;
  bars: MT5Bar[];
  lastQuote: MT5Quote | null;
  lastPrice: number | null;
  bots: TickerBotContext[];
  isConnected: boolean;
}

function StatCell({
  label,
  value,
  sub,
  positive,
  icon: Icon,
  mono = true,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  icon?: React.ElementType;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-4 border-r border-white/5 last:border-r-0 shrink-0">
      <div className="flex items-center gap-1 text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
        {Icon && <Icon className="w-3 h-3" />}
        {label}
      </div>
      <div
        className={cn(
          'text-sm font-bold leading-none',
          mono && 'font-mono',
          positive === true && 'text-emerald-400',
          positive === false && 'text-red-400',
          positive === undefined && 'text-foreground',
        )}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[10px] font-mono text-muted-foreground">{sub}</div>
      )}
    </div>
  );
}

export function TickerStatsBar({
  symbol,
  bars,
  lastQuote,
  lastPrice,
  bots,
  isConnected,
}: TickerStatsBarProps) {
  const openBar = bars.length > 1 ? bars[0] : null;
  const prevClose = openBar?.close ?? null;
  const change = lastPrice && prevClose ? lastPrice - prevClose : null;
  const changePct = change && prevClose ? (change / prevClose) * 100 : null;

  const spread = lastQuote
    ? (lastQuote.ask - lastQuote.bid).toFixed(3)
    : null;

  // Aggregate bot stats
  const totalEquity = bots.reduce((a, b) => a + (b.equity || 0), 0);
  const totalDailyPnl = bots.reduce((a, b) => a + (b.daily_pnl || 0), 0);
  const totalUnrealizedPnl = bots.reduce((a, b) => a + (b.unrealized_pnl || 0), 0);
  const openPositions = bots.filter((b) => b.position_qty !== 0);
  const positionText =
    openPositions.length === 0
      ? 'FLAT'
      : openPositions
          .map((b) => `${b.position_qty > 0 ? '+' : ''}${b.position_qty} ${b.position_side}`)
          .join(' / ');

  const lastBar = bars[bars.length - 1];
  const volume = lastBar?.volume
    ? lastBar.volume >= 1_000_000
      ? `${(lastBar.volume / 1_000_000).toFixed(1)}M`
      : lastBar.volume >= 1_000
      ? `${(lastBar.volume / 1_000).toFixed(1)}K`
      : lastBar.volume.toString()
    : '—';

  return (
    <div className="flex items-stretch bg-card/50 backdrop-blur-md border-b border-white/5 overflow-x-auto scrollbar-none shrink-0">
      {/* Symbol + connection status */}
      <div className="flex items-center gap-2 px-4 border-r border-white/5 shrink-0">
        <div className="flex flex-col">
          <span className="text-lg font-bold font-mono text-foreground leading-none">{symbol}</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            {isConnected ? (
              <>
                <Wifi className="w-3 h-3 text-emerald-400" />
                <span className="text-[10px] font-mono text-emerald-400">LIVE</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-muted-foreground" />
                <span className="text-[10px] font-mono text-muted-foreground">OFFLINE</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Price */}
      <StatCell
        label="Last Price"
        icon={Activity}
        value={lastPrice ? `$${lastPrice.toFixed(2)}` : '—'}
        sub={
          change !== null && changePct !== null
            ? `${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`
            : undefined
        }
        positive={change !== null ? change >= 0 : undefined}
      />

      {/* Bid/Ask */}
      {lastQuote && (
        <StatCell
          label="Bid / Ask"
          icon={Layers}
          value={`${lastQuote.bid.toFixed(2)} / ${lastQuote.ask.toFixed(2)}`}
          sub={spread ? `Spread: $${spread}` : undefined}
        />
      )}

      {/* Volume */}
      <StatCell label="Volume" icon={BarChart2} value={volume} />

      {/* Divider: Bot stats section */}
      {bots.length > 0 && (
        <div className="flex items-center px-3 border-r border-white/5 shrink-0">
          <span className="text-[9px] font-mono text-muted-foreground/60 uppercase tracking-[0.15em] rotate-0">
            BOT STATS
          </span>
        </div>
      )}

      {bots.length > 0 && (
        <>
          <StatCell
            label="Bot Equity"
            icon={DollarSign}
            value={`$${totalEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          />
          <StatCell
            label="Daily P&L"
            value={`${totalDailyPnl >= 0 ? '+' : ''}$${totalDailyPnl.toFixed(2)}`}
            positive={totalDailyPnl >= 0}
          />
          <StatCell
            label="Unrealized"
            value={`${totalUnrealizedPnl >= 0 ? '+' : ''}$${totalUnrealizedPnl.toFixed(2)}`}
            positive={totalUnrealizedPnl >= 0}
          />
          <StatCell
            label="Position"
            icon={Target}
            value={positionText}
            positive={
              openPositions.length > 0
                ? openPositions[0].position_side === 'long'
                : undefined
            }
          />
        </>
      )}
    </div>
  );
}
