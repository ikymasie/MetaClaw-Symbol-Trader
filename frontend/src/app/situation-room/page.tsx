'use client';

import { useAgentStream } from '@/hooks/useAgentStream';
import { useStreaming } from '@/contexts/StreamingContext';
import { AgentCard } from '@/components/dashboard/AgentCard';
import { StatusBridge } from '@/components/dashboard/StatusBridge';
import { SignalScanning } from '@/components/dashboard/SignalScanning';
import { ExecutionerPanel } from '@/components/dashboard/ExecutionerPanel';
import { OrbitalNexus } from '@/components/dashboard/OrbitalNexus';
import { AgentDetailsPanel } from '@/components/dashboard/AgentDetailsPanel';
import { useFleetStatus } from '@/hooks/useFleet';
import { motion, AnimatePresence } from 'framer-motion';
import { Radio, Activity, Shield, ChevronDown, ListChecks } from 'lucide-react';
import { useState, useEffect } from 'react';

export default function SituationRoomPage() {
  const { data: fleet } = useFleetStatus();
  const bots = fleet?.bots ?? [];
  
  const [selectedBotId, setSelectedBotId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  
  // Live clock – only ticks on the client to avoid hydration mismatch
  const [now, setNow] = useState('--:--:--');
  useEffect(() => {
    const fmt = () =>
      new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    setNow(fmt());
    const id = setInterval(() => setNow(fmt()), 1_000);
    return () => clearInterval(id);
  }, []);

  // Connect stream to selected bot
  const { isStreaming } = useStreaming();
  const { agents, flow, cycleCount, lastSignal, enabledAgents, deliberation } = useAgentStream(selectedBotId ?? undefined, isStreaming);

  const selectedBot = bots.find(b => b.bot_id === selectedBotId);

  // Count statuses for the top stat bar
  const counts = agents.reduce(
    (acc, a) => {
      acc[a.status] = (acc[a.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div className="min-h-screen bg-background px-6 py-6 space-y-6">

      {/* ── Page Header ───────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-xl flex items-center justify-center transition-colors ${selectedBotId ? 'bg-rose-500/20 border border-rose-500/30' : 'bg-zinc-800 border border-white/5'}`}>
              <Radio className={`w-4 h-4 ${selectedBotId ? 'text-rose-400 animate-pulse' : 'text-zinc-500'}`} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight uppercase">
                Situation Room
              </h1>
              <p className="text-[10px] font-mono text-zinc-500 tracking-widest uppercase">
                {selectedBot ? `FEED: ${selectedBot.name} [${selectedBot.symbol}]` : 'AWAITING OPERATIONAL UPLINK'}
              </p>
            </div>
          </div>

          {/* Bot Selector Dropdown */}
          {bots.length > 0 && (
            <div className="relative group">
              <select
                value={selectedBotId ?? ''}
                onChange={(e) => setSelectedBotId(e.target.value || null)}
                className="appearance-none bg-zinc-900 border border-white/6 rounded-xl px-4 py-2 pr-10 text-xs font-mono font-bold text-zinc-300 hover:border-white/20 transition-all cursor-pointer outline-none focus:ring-1 focus:ring-primary/50"
              >
                <option value="">SELECT BOT TO MONITOR</option>
                {bots.map(b => (
                  <option key={b.bot_id} value={b.bot_id}>
                    {b.name} ({b.symbol})
                  </option>
                ))}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none opacity-50 group-hover:opacity-100 transition-opacity">
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              </div>
            </div>
          )}
        </div>

        {/* Top stats */}
        <div className="flex items-center gap-3 flex-wrap">
          <StatPill label="UPSTREAM" value={counts.processing ?? 0} color="text-amber-400" dot="bg-amber-400" />
          <StatPill label="QUORUM" value={counts.approved ?? 0} color="text-emerald-400" dot="bg-emerald-400" />
          <StatPill label="VETOED" value={counts.vetoed ?? 0} color="text-rose-400" dot="bg-rose-500" />
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-zinc-900 border border-white/6">
            <Activity className="w-3 h-3 text-primary" />
            <span className="text-[10px] font-mono text-zinc-400">{now}</span>
          </div>
        </div>
      </motion.div>

      <AnimatePresence mode="wait">
        {!selectedBotId ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 1.02 }}
            transition={{ duration: 0.4 }}
          >
            <SignalScanning />
          </motion.div>
        ) : (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-6"
          >
            {/* ── Status Bridge ─────────────────────────────────────────────────── */}
            <StatusBridge
              flow={flow}
              agents={agents}
              lastSignal={lastSignal}
              cycleCount={cycleCount}
              deliberation={deliberation}
            />

            {/* ── Split Layout: Agent Grid + Verdict Panel ────────────────────── */}
            <div className="flex flex-col-reverse lg:flex-row gap-4 h-[700px]">

              {/* ── Left Side Panel for Agent Details ────────────────────── */}
              <AnimatePresence>
                {selectedAgentId && (
                  <AgentDetailsPanel
                    agent={agents.find(a => a.id === selectedAgentId)}
                    onClose={() => setSelectedAgentId(null)}
                  />
                )}
              </AnimatePresence>

              {/* ── War Room Grid (6 voting agents, no executioner) ────────────── */}
              <div className="flex-1 min-w-0 flex flex-col h-full">
                <OrbitalNexus
                  agents={agents}
                  flow={flow}
                  enabledAgents={enabledAgents}
                  deliberation={deliberation}
                  onAgentSelect={setSelectedAgentId}
                />
              </div>

              {/* ── Executioner Verdict Panel (fixed right) ────────────────────── */}
              <ExecutionerPanel
                agents={agents}
                deliberation={deliberation}
                symbol={selectedBot?.symbol}
              />

            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Footer info ───────────────────────────────────────────────────── */}
      <motion.div className="flex items-center justify-between pt-2 border-t border-white/5">
        <div className="flex items-center gap-2">
          <Shield className="w-3 h-3 text-zinc-600" />
          <span className="text-[9px] font-mono text-zinc-600 uppercase tracking-tight">
            ALGORITHM DEPLOYMENT: {selectedBotId ? 'TARGETING' : 'SCANNING'} · MAS V2 PROTOCOL · CAPITAL-PROTECTED
          </span>
        </div>
        <div className="flex items-center gap-2 text-[9px] font-mono text-zinc-700 uppercase tracking-tight">
          <ListChecks className="w-3 h-3" />
          <span>CYCLES: {cycleCount}</span>
        </div>
      </motion.div>
    </div>
  );
}

// ─── Stat Pill helper ─────────────────────────────────────────────────────────

function StatPill({
  label, value, color, dot,
}: {
  label: string; value: number; color: string; dot: string;
}) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-zinc-900 border border-white/6">
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      <span className="text-[9px] font-mono text-zinc-500">{label}</span>
      <span className={`text-[10px] font-mono font-bold ${color}`}>{value}</span>
    </div>
  );
}
