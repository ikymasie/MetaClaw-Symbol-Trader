'use client';

import { BotSnapshot } from '@/lib/api';
import { Bot, Rocket } from 'lucide-react';
import { BotCard } from '@/components/fleet/BotCard';

type Filter = 'all' | 'running' | 'stopped';

interface Props {
  bots: BotSnapshot[];
  filter: Filter;
  onFilterChange: (f: Filter) => void;
  onSelectBot: (botId: string) => void;
  onDeployClick: () => void;
  isLoading: boolean;
}

export function FleetBotGrid({ bots, filter, onFilterChange, onSelectBot, onDeployClick, isLoading }: Props) {
  const filtered = bots.filter((b) => {
    if (filter === 'running') return b.status?.bot_status === 'RUNNING';
    if (filter === 'stopped') return b.status?.bot_status !== 'RUNNING';
    return true;
  });

  const runningCount = bots.filter((b) => b.status?.bot_status === 'RUNNING').length;
  const stoppedCount = bots.filter((b) => b.status?.bot_status !== 'RUNNING').length;

  if (isLoading && bots.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 rounded-2xl bg-white/3 border border-white/6 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filter tabs */}
      <div className="flex items-center gap-1">
        {(['all', 'running', 'stopped'] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => onFilterChange(f)}
            className={`px-3 py-1.5 rounded-xl text-[10px] font-mono uppercase tracking-widest transition-all ${
              filter === f
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'text-muted-foreground hover:text-white border border-transparent hover:border-white/8'
            }`}
          >
            {f}
            {f === 'all'     && bots.length > 0 && ` (${bots.length})`}
            {f === 'running' && ` (${runningCount})`}
            {f === 'stopped' && ` (${stoppedCount})`}
          </button>
        ))}
      </div>

      {/* Empty state */}
      {filtered.length === 0 && (
        <div className="space-y-6">
          <div className="flex flex-col items-center justify-center py-12 text-center border-2 border-dashed border-white/5 rounded-2xl bg-white/[0.01]">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-5">
              <Bot className="w-6 h-6 text-primary/60" />
            </div>
            <h3 className="text-sm font-semibold text-white mb-2">
              {filter === 'all' ? 'Fleet is Offline' : `No ${filter} bots`}
            </h3>
            <p className="text-xs font-mono text-muted-foreground mb-6 max-w-xs">
              {filter === 'all'
                ? 'Your autonomous fleet is currently empty. Deploy your first bot to activate sub-agent deliberation.'
                : `No bots currently ${filter}.`
              }
            </p>
            {filter === 'all' && (
              <button
                onClick={onDeployClick}
                className="flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-bold hover:bg-primary/90 transition-all shadow-lg shadow-primary/20"
              >
                <Rocket className="w-4 h-4" />
                INITIATE DEPLOYMENT
              </button>
            )}
          </div>
        </div>
      )}

      {/* Bot grid — 2 columns on xl, 1 on smaller */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {filtered.map((bot) => (
            <BotCard key={bot.bot_id} bot={bot} onSelect={onSelectBot} />
          ))}
        </div>
      )}
    </div>
  );
}
