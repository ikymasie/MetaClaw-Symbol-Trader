'use client';

import { motion } from 'framer-motion';
import { DeliberationMeta } from '@/hooks/useAgentStream';
import { ShieldAlert, Zap, Clock, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';

interface OrbitalCoreProps {
  deliberation: DeliberationMeta | null;
}

export function OrbitalCore({ deliberation }: OrbitalCoreProps) {
  let stateLabel = 'AWAITING SIGNALS';
  let colorClass = 'text-zinc-500';
  let glowClass = 'shadow-zinc-500/20';
  let bgClass = 'bg-zinc-900/80';
  let borderClass = 'border-white/10';
  let progressColor = 'text-zinc-600';

  let progress = 0;
  let signalText = 'HOLD';

  if (deliberation) {
    progress = Math.min(100, Math.max(0, Math.abs(deliberation.quorumScore) * 100));
    signalText = deliberation.signal || 'HOLD';

    if (deliberation.isDegraded) {
      stateLabel = 'DEGRADED';
      colorClass = 'text-orange-400';
      glowClass = 'shadow-orange-500/30';
      bgClass = 'bg-orange-500/10';
      borderClass = 'border-orange-500/40';
      progressColor = 'text-orange-500';
    } else if (deliberation.vetoAgents.length > 0) {
      stateLabel = 'VETOED';
      colorClass = 'text-rose-400';
      glowClass = 'shadow-rose-500/30';
      bgClass = 'bg-rose-500/10';
      borderClass = 'border-rose-500/40';
      progressColor = 'text-rose-500';
    } else if (deliberation.approved) {
      stateLabel = 'APPROVED';
      colorClass = 'text-emerald-400';
      glowClass = 'shadow-emerald-500/30';
      bgClass = 'bg-emerald-500/10';
      borderClass = 'border-emerald-500/40';
      progressColor = 'text-emerald-500';
    } else if (deliberation.quorumScore >= 0.2) {
      stateLabel = 'QUORUM REACHED';
      colorClass = 'text-amber-400';
      glowClass = 'shadow-amber-500/30';
      bgClass = 'bg-amber-500/10';
      borderClass = 'border-amber-500/40';
      progressColor = 'text-amber-500';
    } else {
      stateLabel = 'DELIBERATING';
      colorClass = 'text-blue-400';
      glowClass = 'shadow-blue-500/30';
      bgClass = 'bg-blue-500/10';
      borderClass = 'border-blue-500/40';
      progressColor = 'text-blue-500';
    }
  }

  const radius = 76;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (progress / 100) * circumference;

  return (
    <motion.div
      layout
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex flex-col items-center justify-center pointer-events-none"
    >
      {/* Outer ambient glow ring */}
      <motion.div
        animate={{ scale: [1, 1.1, 1], opacity: [0.3, 0.6, 0.3] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
        className={`absolute w-48 h-48 rounded-full blur-2xl pointer-events-none ${bgClass}`}
      />
      
      {/* SVG Circular Progress Indicator */}
      <svg className="absolute w-44 h-44 -rotate-90 pointer-events-none">
        <circle
          cx="88"
          cy="88"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="4"
          className="text-zinc-800"
        />
        <motion.circle
          cx="88"
          cy="88"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          className={`transition-colors duration-500 ${progressColor}`}
          strokeDasharray={circumference}
          animate={{ strokeDashoffset }}
          transition={{ duration: 1, ease: "easeOut" }}
          strokeLinecap="round"
        />
      </svg>

      {/* Core element */}
      <div className={`relative w-36 h-36 rounded-full flex flex-col items-center justify-center border backdrop-blur-md shadow-2xl transition-colors duration-500 ${bgClass} ${borderClass} ${glowClass}`}>
        <h1 className={`text-2xl font-black tracking-widest text-center font-mono transition-colors duration-500 ${colorClass}`}>
          {signalText}
        </h1>
        <h2 className={`text-[9px] mt-1 font-bold tracking-widest text-center font-mono transition-colors duration-500 ${colorClass} opacity-80`}>
          {stateLabel}
        </h2>
        {deliberation && (
          <div className="mt-1">
            <span className="text-[10px] text-zinc-400 font-mono">
              STR: {(deliberation.quorumScore * 100).toFixed(0)}%
            </span>
          </div>
        )}
      </div>
    </motion.div>
  );
}
