'use client';

import { useState, useMemo } from 'react';
import { useTickerBots, type BotTickerInfo } from '@/hooks/useTickerBots';
import { useAlpacaTicker } from '@/hooks/useAlpacaTicker';
import { useStreaming } from '@/contexts/StreamingContext';
import { BotSwitcherStrip } from '@/components/ticker/BotSwitcherStrip';
import { TickerStatsBar } from '@/components/ticker/TickerStatsBar';
import { TickerChart } from '@/components/ticker/TickerChart';
import { BotDetailPanel } from '@/components/ticker/BotDetailPanel';
import { cn } from '@/lib/utils';
import { LayoutGrid, BarChart2 } from 'lucide-react';

export default function TickerPage() {
  const { data: botsData, isLoading: botsLoading } = useTickerBots();
  const bots: BotTickerInfo[] = botsData?.bots ?? [];

  // Default to first bot's symbol if nothing selected, fallback to BTC/USD
  const [selectedBotId, setSelectedBotId] = useState<string | null>(null);
  const selectedBot = bots.find((b) => b.bot_id === selectedBotId) ?? bots[0] ?? null;
  const activeSymbol = selectedBot?.symbol ?? 'BTC/USD';

  const { isStreaming } = useStreaming();
  const { bars, lastQuote, lastPrice, bots: liveBots, isConnected, error } = useAlpacaTicker(activeSymbol, isStreaming);

  // Only show bots for the selected symbol
  const filteredBots = useMemo(
    () => liveBots.filter((b) => b.bot_id === selectedBotId || bots.find((sb) => sb.symbol === activeSymbol && sb.bot_id === b.bot_id)),
    [liveBots, selectedBotId, bots, activeSymbol]
  );

  function handleSelectBot(bot: BotTickerInfo) {
    setSelectedBotId(bot.bot_id);
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] bg-background text-foreground overflow-hidden">
      {/* ── Bot Switcher Strip ── */}
      <BotSwitcherStrip
        bots={bots}
        selectedBotId={selectedBotId ?? selectedBot?.bot_id ?? null}
        onSelect={handleSelectBot}
        isLoading={botsLoading}
      />

      {/* ── Stats Bar ── */}
      {activeSymbol && (
        <TickerStatsBar
          symbol={activeSymbol}
          bars={bars}
          lastQuote={lastQuote}
          lastPrice={lastPrice}
          bots={filteredBots}
          isConnected={isConnected}
        />
      )}

      {/* ── Main Content: Chart + Right Panel ── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Chart Area */}
        <div className="flex-1 relative min-w-0">
          {/* No symbol state */}
          {!activeSymbol && !botsLoading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
              <LayoutGrid className="w-12 h-12 text-muted-foreground/30" />
              <div className="text-center max-w-xs">
                <p className="text-sm font-semibold text-foreground/70">No symbol selected</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Deploy bots from the <strong>Fleet</strong> page, then return here to monitor them in real-time.
                </p>
              </div>
            </div>
          )}

          {/* Error state */}
          {error && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 px-4 py-2 rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 text-xs font-mono">
              {error} — retrying…
            </div>
          )}

          {/* Chart */}
          {activeSymbol && (
            <TickerChart
              bars={bars}
              bots={filteredBots}
              className="absolute inset-0"
            />
          )}

          {/* Connecting overlay */}
          {activeSymbol && !isConnected && bars.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/60 backdrop-blur-sm">
              <div className="flex flex-col items-center gap-3">
                <BarChart2 className="w-8 h-8 text-primary animate-pulse" />
                <p className="text-sm font-mono text-muted-foreground">
                  Connecting to live feed for{' '}
                  <span className="text-primary font-bold">{activeSymbol}</span>…
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right Panel — Bot Detail */}
        <aside
          className={cn(
            'w-72 shrink-0 border-l border-white/5 bg-card/30 backdrop-blur-md flex flex-col overflow-hidden',
          )}
        >
          {/* Panel header */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5 shrink-0">
            <span className="text-xs font-mono font-bold text-muted-foreground uppercase tracking-widest">
              Bot Intel
            </span>
            {filteredBots.length > 0 && (
              <span className="ml-auto text-[10px] font-mono text-primary bg-primary/10 px-2 py-0.5 rounded-full border border-primary/20">
                {filteredBots.length} bot{filteredBots.length > 1 ? 's' : ''}
              </span>
            )}
          </div>

          <BotDetailPanel bots={filteredBots} symbol={activeSymbol ?? ''} />
        </aside>
      </div>
    </div>
  );
}
