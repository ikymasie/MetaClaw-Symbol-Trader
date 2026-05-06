'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { AgentState, AgentId, DeliberationMeta } from '@/hooks/useAgentStream';
import {
  ThumbsUp, ThumbsDown, Minus, Zap,
  Eye, Cpu, CalendarCheck, BarChart3, MessageSquare, ShieldAlert,
  TrendingUp, TrendingDown, Pause, AlertTriangle, Gauge,
} from 'lucide-react';

// ─── Agent display config ────────────────────────────────────────────────────

const VOTING_AGENTS: { id: AgentId; label: string; icon: React.ReactNode }[] = [
  { id: 'watchman',          label: 'WATCHMAN',   icon: <Eye className="w-3.5 h-3.5" /> },
  { id: 'macro_analyst',     label: 'MACRO',      icon: <Cpu className="w-3.5 h-3.5" /> },
  { id: 'earnings_analyst',  label: 'EARNINGS',   icon: <CalendarCheck className="w-3.5 h-3.5" /> },
  { id: 'technical_analyst', label: 'TECHNICAL',  icon: <BarChart3 className="w-3.5 h-3.5" /> },
  { id: 'sentiment_analyst', label: 'SENTIMENT',  icon: <MessageSquare className="w-3.5 h-3.5" /> },
  { id: 'risk_manager',      label: 'RISK MGR',   icon: <ShieldAlert className="w-3.5 h-3.5" /> },
];

// ─── Verdict signal config ───────────────────────────────────────────────────

const SIGNAL_CONFIG: Record<string, {
  color: string; glow: string; bg: string; border: string; icon: React.ReactNode;
}> = {
  BUY:  { color: 'text-emerald-400', glow: 'shadow-emerald-500/30', bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', icon: <TrendingUp className="w-6 h-6" /> },
  SELL: { color: 'text-rose-400',    glow: 'shadow-rose-500/30',    bg: 'bg-rose-500/10',    border: 'border-rose-500/40',    icon: <TrendingDown className="w-6 h-6" /> },
  HOLD: { color: 'text-zinc-500',    glow: 'shadow-zinc-500/10',    bg: 'bg-zinc-800/50',    border: 'border-zinc-700',       icon: <Pause className="w-6 h-6" /> },
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface Props {
  agents: AgentState[];
  deliberation: DeliberationMeta | null;
  symbol?: string;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ExecutionerPanel({ agents, deliberation, symbol }: Props) {
  const signal = deliberation?.signal || 'HOLD';
  const cfg = SIGNAL_CONFIG[signal] || SIGNAL_CONFIG.HOLD;

  // Count votes
  const approveCount = agents.filter(a => a.id !== 'executioner' && a.status === 'approved').length;
  const vetoCount = agents.filter(a => a.id !== 'executioner' && a.status === 'vetoed').length;
  const totalVoting = VOTING_AGENTS.length;

  return (
    <div className="w-full lg:w-[340px] lg:shrink-0">
      <div className="lg:sticky lg:top-6 space-y-3">

        {/* ═══════════════════════════════════════════════════════════════════
            SECTION 1 — VERDICT BANNER
            ═══════════════════════════════════════════════════════════════════ */}
        <motion.div
          layout
          className={`
            relative rounded-2xl p-5 overflow-hidden
            bg-zinc-900/90 backdrop-blur-sm border transition-all duration-500
            ${deliberation ? cfg.border : 'border-white/6'}
          `}
        >
          {/* Ambient glow */}
          {deliberation && signal !== 'HOLD' && (
            <motion.div
              className="absolute inset-0 pointer-events-none"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              style={{
                background: signal === 'BUY'
                  ? 'radial-gradient(ellipse at center, rgba(52,211,153,0.08) 0%, transparent 70%)'
                  : 'radial-gradient(ellipse at center, rgba(239,68,68,0.08) 0%, transparent 70%)',
              }}
            />
          )}

          <div className="relative flex flex-col items-center gap-3">
            {/* Section header */}
            <div className="flex items-center gap-2 self-start">
              <Zap className="w-3.5 h-3.5 text-zinc-500" />
              <span className="text-[9px] font-mono font-bold text-zinc-500 tracking-[0.2em] uppercase">
                Verdict
              </span>
            </div>

            {/* Animated signal ring */}
            <div className="relative my-2">
              {/* Outer pulsing ring */}
              {deliberation && signal !== 'HOLD' && (
                <motion.div
                  className={`absolute inset-[-8px] rounded-full border-2 ${
                    signal === 'BUY' ? 'border-emerald-500/50' : 'border-rose-500/50'
                  }`}
                  animate={{ scale: [1, 1.15, 1], opacity: [0.6, 0, 0.6] }}
                  transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                />
              )}

              {/* Main circle */}
              <div className={`
                w-[88px] h-[88px] rounded-full flex flex-col items-center justify-center
                border-2 transition-all duration-500
                ${deliberation ? `${cfg.bg} ${cfg.border}` : 'bg-zinc-800/50 border-zinc-700'}
              `}>
                <AnimatePresence mode="wait">
                  <motion.div
                    key={signal}
                    initial={{ scale: 0.7, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.7, opacity: 0 }}
                    transition={{ duration: 0.3, ease: 'easeOut' }}
                    className="flex flex-col items-center gap-0.5"
                  >
                    <span className={cfg.color}>{cfg.icon}</span>
                    <span className={`text-lg font-black font-mono tracking-widest ${cfg.color}`}>
                      {signal}
                    </span>
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>

            {/* Sub-details */}
            {deliberation && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col items-center gap-1"
              >
                <span className="text-[10px] font-mono text-zinc-300">
                  {symbol ?? '---'} × <span className="font-bold text-white">{deliberation.approvedQty || '--'}</span> shares
                </span>
                <div className="flex items-center gap-2">
                  <span className={`text-[8px] font-mono font-bold px-2 py-0.5 rounded-full border ${
                    deliberation.orderUrgency === 'HIGH'
                      ? 'text-amber-400 border-amber-500/30 bg-amber-500/10'
                      : 'text-zinc-500 border-zinc-700 bg-zinc-800/50'
                  }`}>
                    {deliberation.orderUrgency} URGENCY
                  </span>
                  {deliberation.isDegraded && (
                    <span className="text-[8px] font-mono font-bold px-2 py-0.5 rounded-full border border-orange-500/30 text-orange-400 bg-orange-500/10 flex items-center gap-1">
                      <AlertTriangle className="w-2.5 h-2.5" /> DEGRADED
                    </span>
                  )}
                </div>
              </motion.div>
            )}

            {/* No data fallback */}
            {!deliberation && (
              <p className="text-[10px] font-mono text-zinc-600 text-center">
                Awaiting deliberation cycle...
              </p>
            )}
          </div>
        </motion.div>

        {/* ═══════════════════════════════════════════════════════════════════
            SECTION 2 — AGENT QUORUM ROSTER
            ═══════════════════════════════════════════════════════════════════ */}
        <div className="rounded-2xl bg-zinc-900/90 backdrop-blur-sm border border-white/6 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <span className="text-[9px] font-mono font-bold text-zinc-500 tracking-[0.2em] uppercase">
              Agent Quorum
            </span>
            <div className="flex items-center gap-1.5">
              <span className={`text-[10px] font-mono font-bold ${
                approveCount >= 4 ? 'text-emerald-400' : approveCount >= 3 ? 'text-amber-400' : 'text-zinc-500'
              }`}>
                {approveCount}
              </span>
              <span className="text-[9px] font-mono text-zinc-600">/ {totalVoting}</span>
              <span className="text-[8px] font-mono text-zinc-600 ml-1">APPROVE</span>
            </div>
          </div>

          {/* Vote rows */}
          <div className="divide-y divide-white/5">
            {VOTING_AGENTS.map(({ id, label, icon }) => {
              const agent = agents.find(a => a.id === id);
              const status = agent?.status ?? 'idle';
              const confidence = agent?.metric;
              const isVeto = status === 'vetoed';
              const isApproved = status === 'approved';

              return (
                <motion.div
                  key={id}
                  className={`
                    flex items-center justify-between px-4 py-2.5 transition-colors duration-300
                    ${isVeto ? 'bg-rose-500/5' : ''}
                  `}
                  initial={false}
                  animate={{ backgroundColor: isVeto ? 'rgba(239,68,68,0.05)' : 'transparent' }}
                >
                  {/* Left: icon + name */}
                  <div className="flex items-center gap-2.5">
                    <span className={`shrink-0 ${
                      isVeto ? 'text-rose-400' : isApproved ? 'text-emerald-400' : 'text-zinc-600'
                    }`}>
                      {icon}
                    </span>
                    <span className={`text-[10px] font-mono font-bold tracking-wider ${
                      isVeto ? 'text-rose-400' : isApproved ? 'text-zinc-200' : 'text-zinc-600'
                    }`}>
                      {label}
                    </span>
                  </div>

                  {/* Right: confidence + thumb */}
                  <div className="flex items-center gap-2.5">
                    {/* Confidence */}
                    {confidence && confidence !== '--' && (
                      <span className={`text-[9px] font-mono font-semibold ${
                        isVeto ? 'text-rose-400/70' : isApproved ? 'text-emerald-400/70' : 'text-zinc-600'
                      }`}>
                        {confidence}
                      </span>
                    )}

                    {/* Vote icon */}
                    <AnimatePresence mode="wait">
                      <motion.div
                        key={`${id}-${status}`}
                        initial={{ scale: 0.5, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.5, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                      >
                        {isApproved && <ThumbsUp className="w-3.5 h-3.5 text-emerald-400" />}
                        {isVeto && <ThumbsDown className="w-3.5 h-3.5 text-rose-400" />}
                        {!isApproved && !isVeto && <Minus className="w-3.5 h-3.5 text-zinc-700" />}
                      </motion.div>
                    </AnimatePresence>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════════════════════
            SECTION 3 — TRADE DETAILS
            ═══════════════════════════════════════════════════════════════════ */}
        <div className="rounded-2xl bg-zinc-900/90 backdrop-blur-sm border border-white/6 p-4">
          {/* Header */}
          <div className="flex items-center gap-2 mb-3">
            <Gauge className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-[9px] font-mono font-bold text-zinc-500 tracking-[0.2em] uppercase">
              Trade Details
            </span>
          </div>

          {deliberation ? (
            <div className="space-y-2.5">
              {/* Quorum Score with mini-bar */}
              <DetailRow label="Quorum Score">
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-mono font-bold ${
                    deliberation.quorumScore > 0.2 ? 'text-emerald-400' :
                    deliberation.quorumScore > 0 ? 'text-amber-400' : 'text-rose-400'
                  }`}>
                    {deliberation.quorumScore.toFixed(3)}
                  </span>
                  <div className="w-12 h-1 bg-zinc-800 rounded-full overflow-hidden">
                    <motion.div
                      className={`h-full rounded-full ${
                        deliberation.quorumScore > 0.2 ? 'bg-emerald-400' :
                        deliberation.quorumScore > 0 ? 'bg-amber-400' : 'bg-rose-400'
                      }`}
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(100, Math.max(0, ((deliberation.quorumScore + 1) / 2) * 100))}%` }}
                      transition={{ duration: 0.5 }}
                    />
                  </div>
                </div>
              </DetailRow>

              {/* Signal */}
              <DetailRow label="Signal">
                <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${
                  signal === 'BUY' ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' :
                  signal === 'SELL' ? 'text-rose-400 border-rose-500/30 bg-rose-500/10' :
                  'text-zinc-500 border-zinc-700 bg-zinc-800/50'
                }`}>
                  {signal}
                </span>
              </DetailRow>

              {/* Kelly Qty */}
              <DetailRow label="Kelly Qty">
                <span className="text-[10px] font-mono font-bold text-sky-400">
                  {deliberation.approvedQty || '--'}
                </span>
              </DetailRow>

              {/* Urgency */}
              <DetailRow label="Urgency">
                <span className={`text-[10px] font-mono font-bold ${
                  deliberation.orderUrgency === 'HIGH' ? 'text-amber-400' : 'text-zinc-500'
                }`}>
                  {deliberation.orderUrgency}
                </span>
              </DetailRow>

              {/* Veto count */}
              {deliberation.vetoAgents.length > 0 && (
                <DetailRow label="Vetoes">
                  <span className="text-[10px] font-mono font-bold text-rose-400">
                    {deliberation.vetoAgents.join(', ')}
                  </span>
                </DetailRow>
              )}

              {/* Reasoning */}
              {deliberation.reasoning && (
                <div className="mt-3 pt-3 border-t border-white/5">
                  <span className="text-[8px] font-mono text-zinc-600 tracking-widest uppercase block mb-1">
                    Reasoning
                  </span>
                  <p className="text-[9px] font-mono text-zinc-400 leading-relaxed line-clamp-3">
                    {deliberation.reasoning}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-[10px] font-mono text-zinc-600 italic">
              No deliberation data yet.
            </p>
          )}
        </div>

      </div>
    </div>
  );
}

// ─── Detail row helper ───────────────────────────────────────────────────────

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[9px] font-mono text-zinc-600">{label}</span>
      {children}
    </div>
  );
}
