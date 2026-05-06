'use client';

import { memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AgentState, AgentStatus } from '@/hooks/useAgentStream';
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
  bg: string;
}> = {
  idle:       { label: 'IDLE',       color: 'text-zinc-400',    ring: 'border-zinc-700',    pulse: '',                     dotColor: 'bg-zinc-500',  bg: 'bg-zinc-800/50' },
  processing: { label: 'PROCESSING', color: 'text-amber-400',   ring: 'border-amber-500/60',pulse: 'animate-pulse-amber',  dotColor: 'bg-amber-400', bg: 'bg-amber-500/10' },
  approved:   { label: 'APPROVED',   color: 'text-emerald-400', ring: 'border-emerald-500/60',pulse: 'animate-pulse-green',dotColor: 'bg-emerald-400',bg: 'bg-emerald-500/10' },
  vetoed:     { label: 'VETOED',     color: 'text-rose-400',    ring: 'border-rose-500/60', pulse: 'animate-pulse-red',    dotColor: 'bg-rose-500',  bg: 'bg-rose-500/10' },
  disabled:   { label: 'DISABLED',   color: 'text-zinc-600',    ring: 'border-zinc-800',    pulse: '',                     dotColor: 'bg-zinc-700',  bg: 'bg-zinc-800/30' },
  degraded:   { label: 'DEGRADED',   color: 'text-orange-400',  ring: 'border-orange-500/60', pulse: 'animate-pulse',      dotColor: 'bg-orange-500', bg: 'bg-orange-500/10' },
};

const AGENT_ICONS: Record<string, React.ReactNode> = {
  watchman:          <Eye className="w-5 h-5" />,
  macro_analyst:     <Cpu className="w-5 h-5" />,
  earnings_analyst:  <CalendarCheck className="w-5 h-5" />,
  technical_analyst: <BarChart3 className="w-5 h-5" />,
  sentiment_analyst: <MessageSquare className="w-5 h-5" />,
  risk_manager:      <ShieldAlert className="w-5 h-5" />,
  executioner:       <Zap className="w-5 h-5" />,
};

interface OrbitalAgentProps {
  agent: AgentState;
  isActive: boolean;
  disabled?: boolean;
  angle: number; // in radians
  rx: number;
  ry: number;
  onClick?: () => void;
}

export const OrbitalAgent = memo(function OrbitalAgent({ agent, isActive, disabled = false, angle, rx, ry, onClick }: OrbitalAgentProps) {
  const effectiveStatus = disabled ? 'disabled' : agent.status;
  const cfg = STATUS_CONFIG[effectiveStatus] ?? STATUS_CONFIG.idle;
  const icon = AGENT_ICONS[agent.id];

  // Calculate base position
  const x = Math.cos(angle) * rx;
  const y = Math.sin(angle) * ry;

  const numThoughts = agent.thoughts.length;

  return (
    <>
      {/* Main Agent Node */}
      <motion.div
        layoutId={`agent-${agent.id}`}
        initial={false}
        animate={{ x, y }}
        transition={{ type: 'spring', damping: 25, stiffness: 100 }}
        className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex flex-col items-center justify-center cursor-pointer`}
        onClick={onClick}
      >
        <div className={`relative w-16 h-16 rounded-full flex items-center justify-center border-2 backdrop-blur-md shadow-lg transition-colors duration-300 ${cfg.bg} ${cfg.ring} ${disabled ? 'opacity-40' : 'opacity-100'}`}>
          {isActive && (
             <motion.div
               className={`absolute inset-0 rounded-full ${cfg.bg}`}
               animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0, 0.5] }}
               transition={{ duration: 2, repeat: Infinity }}
             />
          )}
          
          <span className={`${cfg.color}`}>{icon}</span>

          {/* Status Dot */}
          <div className="absolute -top-1 -right-1">
            <span className="relative flex h-3 w-3">
              {effectiveStatus !== 'idle' && effectiveStatus !== 'disabled' && (
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${cfg.dotColor}`}></span>
              )}
              <span className={`relative inline-flex rounded-full h-3 w-3 ${cfg.dotColor}`}></span>
            </span>
          </div>

          {/* Task Counter Badge */}
          {numThoughts > 0 && (
            <div className="absolute -top-2 -left-2 w-5 h-5 rounded-full bg-blue-500 text-white flex items-center justify-center text-[10px] font-bold border border-white/20 shadow-md">
              {numThoughts}
            </div>
          )}

          {/* Metric Badge */}
          {agent.metric && agent.metric !== '--' && (
            <div className="absolute -bottom-3 px-2 py-0.5 rounded-full bg-zinc-900 border border-white/10 shadow-xl">
              <span className={`text-[9px] font-mono font-bold ${cfg.color}`}>{agent.metric}</span>
            </div>
          )}
        </div>

        {/* Label */}
        <div className="mt-4 text-center">
          <h3 className="text-[10px] font-bold text-white tracking-widest font-mono uppercase whitespace-nowrap">
            {agent.name}
          </h3>
          {agent.weight && (
            <span className="text-[8px] font-mono text-zinc-500 bg-zinc-900/80 px-1 py-0.5 rounded border border-white/5 mt-1 inline-block">
              W: {agent.weight.toFixed(2)}
            </span>
          )}
        </div>
      </motion.div>
    </>
  );
});
