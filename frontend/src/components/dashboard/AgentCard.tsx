'use client';

import { useRef, useEffect, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AgentState, AgentStatus } from '@/hooks/useAgentStream';
import { Progress } from '@/components/ui/progress';
import {
  Eye, Cpu, TrendingUp, MessageSquare, ShieldAlert, Zap,
  BarChart3, CalendarCheck,
} from 'lucide-react';

// ─── Status config ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<AgentStatus, {
  label: string;
  color: string;
  ring: string;
  pulse: string;
  dotColor: string;
  progressColor: string;
}> = {
  idle:       { label: 'IDLE',       color: 'text-zinc-400',    ring: 'ring-zinc-700',    pulse: '',                     dotColor: 'bg-zinc-500',  progressColor: 'bg-zinc-600' },
  processing: { label: 'PROCESSING', color: 'text-amber-400',   ring: 'ring-amber-500/60',pulse: 'animate-pulse-amber',  dotColor: 'bg-amber-400', progressColor: 'bg-amber-400' },
  approved:   { label: 'APPROVED',   color: 'text-emerald-400', ring: 'ring-emerald-500/60',pulse: 'animate-pulse-green',dotColor: 'bg-emerald-400',progressColor: 'bg-emerald-400' },
  vetoed:     { label: 'VETOED',     color: 'text-rose-400',    ring: 'ring-rose-500/60', pulse: 'animate-pulse-red',    dotColor: 'bg-rose-500',  progressColor: 'bg-rose-500' },
  disabled:   { label: 'DISABLED',   color: 'text-zinc-600',    ring: 'ring-zinc-800',    pulse: '',                     dotColor: 'bg-zinc-700',  progressColor: 'bg-zinc-800' },
  degraded:   { label: 'DEGRADED',   color: 'text-orange-400',  ring: 'ring-orange-500/60', pulse: 'animate-pulse',      dotColor: 'bg-orange-500', progressColor: 'bg-orange-400' },
};

// Updated to match new AgentId values from corrected useAgentStream
const AGENT_ICONS: Record<string, React.ReactNode> = {
  watchman:          <Eye className="w-4 h-4" />,
  macro_analyst:     <Cpu className="w-4 h-4" />,
  earnings_analyst:  <CalendarCheck className="w-4 h-4" />,
  technical_analyst: <BarChart3 className="w-4 h-4" />,
  sentiment_analyst: <MessageSquare className="w-4 h-4" />,
  risk_manager:      <ShieldAlert className="w-4 h-4" />,
  executioner:       <Zap className="w-4 h-4" />,
};

// ─── Thought Log ───────────────────────────────────────────────────────────────

function ThoughtLog({ thoughts }: { thoughts: AgentState['thoughts'] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thoughts]);

  return (
    <div className="flex-1 overflow-y-auto font-mono text-[10px] leading-relaxed space-y-0.5 pr-1 min-h-0">
      <AnimatePresence initial={false}>
        {thoughts.length === 0 ? (
          <p className="text-zinc-600 italic">Awaiting signal...</p>
        ) : (
          thoughts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.25 }}
              className="flex gap-2"
            >
              <span className="text-zinc-600 shrink-0">{t.timestamp}</span>
              <span className="text-zinc-300">{t.text}</span>
            </motion.div>
          ))
        )}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}

// ─── AgentCard ─────────────────────────────────────────────────────────────────

interface AgentCardProps {
  agent: AgentState;
  isActive: boolean; // currently in pipeline focus
  disabled?: boolean; // agent not configured for this bot
}

export const AgentCard = memo(function AgentCard({ agent, isActive, disabled = false }: AgentCardProps) {
  const effectiveStatus = disabled ? 'disabled' : agent.status;
  const cfg = STATUS_CONFIG[effectiveStatus] ?? STATUS_CONFIG.idle;
  const icon = AGENT_ICONS[agent.id];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      className={`
        relative flex flex-col gap-3 p-4 rounded-2xl h-full
        bg-zinc-900/80 backdrop-blur-sm border transition-all duration-300
        ${disabled ? 'opacity-40 pointer-events-none border-zinc-800/50' :
          isActive ? `ring-1 ${cfg.ring} border-transparent shadow-lg shadow-black/40` : 'border-white/6'}
      `}
    >
      {/* Active glow overlay */}
      {isActive && (
        <motion.div
          className="absolute inset-0 rounded-2xl pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          style={{
            background: agent.status === 'vetoed'
              ? 'radial-gradient(ellipse at top, rgba(239,68,68,0.07) 0%, transparent 70%)'
              : agent.status === 'approved'
              ? 'radial-gradient(ellipse at top, rgba(52,211,153,0.07) 0%, transparent 70%)'
              : agent.status === 'degraded'
              ? 'radial-gradient(ellipse at top, rgba(249,115,22,0.07) 0%, transparent 70%)'
              : 'radial-gradient(ellipse at top, rgba(251,191,36,0.06) 0%, transparent 70%)',
          }}
        />
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          {/* Status dot */}
          <div className="relative flex shrink-0">
            <span className={`w-2 h-2 rounded-full ${cfg.dotColor}`} />
            {effectiveStatus !== 'idle' && effectiveStatus !== 'disabled' && (
              <span className={`absolute inset-0 rounded-full ${cfg.dotColor} opacity-60 animate-ping`} />
            )}
          </div>

          {/* Agent name + role */}
          <div>
            <div className="flex items-center gap-1.5">
              <span className={`${cfg.color} opacity-80`}>{icon}</span>
              <h3 className="text-[11px] font-bold text-white tracking-widest font-mono">
                {agent.name}
              </h3>
              {/* Weight badge for voting agents */}
              {agent.weight && (
                <span className="text-[7px] font-mono text-zinc-500 bg-zinc-800 px-1 py-0.5 rounded border border-white/5">
                  ×{agent.weight}
                </span>
              )}
            </div>
            <p className="text-[9px] text-zinc-500 font-mono tracking-wider mt-0.5">
              {agent.role}
            </p>
          </div>
        </div>

        {/* Status badge */}
        <motion.span
          key={agent.status}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className={`text-[8px] font-mono font-bold tracking-widest px-2 py-0.5 rounded-full border ${
            effectiveStatus === 'disabled'   ? 'border-zinc-700 text-zinc-600 bg-zinc-800/30' :
            effectiveStatus === 'idle'       ? 'border-zinc-700 text-zinc-500 bg-zinc-800/50' :
            effectiveStatus === 'processing' ? 'border-amber-500/40 text-amber-400 bg-amber-500/10' :
            effectiveStatus === 'approved'   ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10' :
            effectiveStatus === 'degraded'   ? 'border-orange-500/40 text-orange-400 bg-orange-500/10' :
                                            'border-rose-500/40 text-rose-400 bg-rose-500/10'
          }`}
        >
          {cfg.label}
        </motion.span>
      </div>

      {/* Progress bar */}
      <Progress
        value={agent.progress}
        indicatorClassName={cfg.progressColor}
        className="h-[3px] bg-white/5"
      />

      {/* Thought log */}
      <div className="flex-1 min-h-0 flex flex-col bg-black/30 rounded-xl p-3 border border-white/5" style={{ maxHeight: '180px', minHeight: '140px' }}>
        {/* Terminal header */}
        <div className="flex items-center gap-1.5 mb-2 shrink-0">
          <span className="w-2 h-2 rounded-full bg-rose-500/70" />
          <span className="w-2 h-2 rounded-full bg-amber-500/70" />
          <span className="w-2 h-2 rounded-full bg-emerald-500/70" />
          <span className="ml-1.5 text-[8px] font-mono text-zinc-600">thought-stream</span>
        </div>
        <ThoughtLog thoughts={agent.thoughts} />
      </div>

      {/* Metric footer */}
      <div className="flex items-center justify-between shrink-0 pt-0.5">
        <span className="text-[9px] font-mono text-zinc-600">{agent.metricLabel}</span>
        <motion.span
          key={agent.metric}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className={`text-xs font-mono font-bold ${cfg.color}`}
        >
          {agent.metric}
        </motion.span>
      </div>
    </motion.div>
  );
});
