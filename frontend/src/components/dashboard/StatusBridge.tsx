'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { DecisionFlow, DeliberationMeta, PIPELINE_STAGES, AgentState } from '@/hooks/useAgentStream';
import { ArrowRight, CheckCircle2, XCircle, Circle, Loader2, AlertTriangle, Gauge, Package, Zap } from 'lucide-react';

interface StatusBridgeProps {
  flow: DecisionFlow;
  agents: AgentState[];
  lastSignal: string;
  cycleCount: number;
  deliberation: DeliberationMeta | null;
}

// ─── Quorum Gauge ─────────────────────────────────────────────────────────────

function QuorumGauge({ score, isDegraded }: { score: number; isDegraded: boolean }) {
  // Score ranges from -1 to +1; normalize to 0-100 for visual
  const normalized = Math.min(100, Math.max(0, ((score + 1) / 2) * 100));
  const color = isDegraded
    ? 'text-orange-400'
    : score > 0.2
      ? 'text-emerald-400'
      : score > 0
        ? 'text-amber-400'
        : 'text-rose-400';
  const bgColor = isDegraded
    ? 'bg-orange-400'
    : score > 0.2
      ? 'bg-emerald-400'
      : score > 0
        ? 'bg-amber-400'
        : 'bg-rose-400';
  const label = isDegraded
    ? 'DEGRADED'
    : score > 0.2
      ? 'STRONG'
      : score > 0
        ? 'WEAK'
        : 'AGAINST';

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-zinc-800/60 border border-white/5">
      <Gauge className={`w-4 h-4 ${color} shrink-0`} />
      <div className="flex flex-col gap-1 min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <span className="text-[8px] font-mono text-zinc-500 uppercase tracking-widest">Quorum Score</span>
          <span className={`text-[9px] font-mono font-bold ${color}`}>{score.toFixed(3)}</span>
        </div>
        <div className="h-1 w-full bg-zinc-700 rounded-full overflow-hidden">
          <motion.div
            className={`h-full rounded-full ${bgColor}`}
            initial={{ width: 0 }}
            animate={{ width: `${normalized}%` }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          />
        </div>
        <div className="flex items-center gap-1">
          {isDegraded && <AlertTriangle className="w-3 h-3 text-orange-400" />}
          <span className={`text-[7px] font-mono font-bold uppercase ${color}`}>{label}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Deliberation Detail ──────────────────────────────────────────────────────

function DeliberationDetail({ deliberation }: { deliberation: DeliberationMeta }) {
  return (
    <div className="grid grid-cols-3 gap-2 mt-3">
      {/* Signal */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-zinc-800/50 border border-white/5">
        <Zap className={`w-3.5 h-3.5 shrink-0 ${
          deliberation.signal === 'BUY' ? 'text-emerald-400' :
          deliberation.signal === 'SELL' ? 'text-rose-400' : 'text-zinc-500'
        }`} />
        <div>
          <span className="text-[7px] font-mono text-zinc-600 block">SIGNAL</span>
          <span className={`text-[10px] font-mono font-bold ${
            deliberation.signal === 'BUY' ? 'text-emerald-400' :
            deliberation.signal === 'SELL' ? 'text-rose-400' : 'text-zinc-500'
          }`}>{deliberation.signal}</span>
        </div>
      </div>

      {/* Qty */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-zinc-800/50 border border-white/5">
        <Package className="w-3.5 h-3.5 text-sky-400 shrink-0" />
        <div>
          <span className="text-[7px] font-mono text-zinc-600 block">QTY</span>
          <span className="text-[10px] font-mono font-bold text-sky-400">{deliberation.approvedQty || '--'}</span>
        </div>
      </div>

      {/* Urgency */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-zinc-800/50 border border-white/5">
        <AlertTriangle className={`w-3.5 h-3.5 shrink-0 ${
          deliberation.orderUrgency === 'HIGH' ? 'text-amber-400' : 'text-zinc-500'
        }`} />
        <div>
          <span className="text-[7px] font-mono text-zinc-600 block">URGENCY</span>
          <span className={`text-[10px] font-mono font-bold ${
            deliberation.orderUrgency === 'HIGH' ? 'text-amber-400' : 'text-zinc-500'
          }`}>{deliberation.orderUrgency}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main StatusBridge ────────────────────────────────────────────────────────

export function StatusBridge({ flow, agents, lastSignal, cycleCount, deliberation }: StatusBridgeProps) {
  const getStepStatus = (stageId: string): 'pending' | 'active' | 'approved' | 'vetoed' | 'degraded' => {
    const agent = agents.find(a => a.id === stageId);
    if (!agent) return 'pending';
    if (agent.status === 'degraded') return 'degraded';
    if (agent.status === 'approved') return 'approved';
    if (agent.status === 'vetoed') return 'vetoed';
    if (agent.status === 'processing') return 'active';
    return 'pending';
  };

  return (
    <div className="w-full rounded-2xl bg-zinc-900/80 backdrop-blur-sm border border-white/6 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-[11px] font-mono font-bold text-white tracking-[0.2em]">
            ◈ STATUS BRIDGE
          </h2>
          <p className="text-[9px] font-mono text-zinc-600 mt-0.5">MAS deliberation protocol v2</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[9px] font-mono text-zinc-500">
            CYCLE <span className="text-primary font-bold">#{cycleCount.toString().padStart(3, '0')}</span>
          </span>
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[9px] font-mono font-bold ${
            deliberation?.isDegraded
              ? 'border-orange-500/40 text-orange-400 bg-orange-500/10'
              : flow.isFlowing
                ? 'border-primary/40 text-primary bg-primary/10'
                : 'border-zinc-700 text-zinc-500 bg-zinc-800/50'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              deliberation?.isDegraded
                ? 'bg-orange-400 animate-pulse'
                : flow.isFlowing ? 'bg-primary animate-pulse' : 'bg-zinc-600'
            }`} />
            {deliberation?.isDegraded ? 'DEGRADED' : flow.isFlowing ? 'FLOWING' : 'STANDBY'}
          </div>
        </div>
      </div>

      {/* Pipeline visualization */}
      <div className="flex items-center gap-0 overflow-x-auto pb-2">
        {PIPELINE_STAGES.map((stage, index) => {
          const status = getStepStatus(stage.id);
          const isToken = flow.tokenPosition === index && flow.isFlowing && status === 'active';

          return (
            <div key={stage.id} className="flex items-center">
              {/* Stage node */}
              <div className="flex flex-col items-center gap-2 min-w-[72px]">
                {/* Node circle */}
                <div className="relative">
                  <div className={`
                    w-10 h-10 rounded-full flex items-center justify-center border-2 transition-all duration-500
                    ${status === 'approved'   ? 'border-emerald-500 bg-emerald-500/10' :
                      status === 'vetoed'     ? 'border-rose-500 bg-rose-500/10' :
                      status === 'degraded'   ? 'border-orange-500 bg-orange-500/10' :
                      status === 'active'     ? 'border-amber-400 bg-amber-400/10' :
                                               'border-zinc-700 bg-zinc-800/50'}
                  `}>
                    {status === 'approved' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                    {status === 'vetoed'   && <XCircle      className="w-4 h-4 text-rose-400" />}
                    {status === 'degraded' && <AlertTriangle className="w-4 h-4 text-orange-400" />}
                    {status === 'active'   && (
                      <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
                        <Loader2 className="w-4 h-4 text-amber-400" />
                      </motion.div>
                    )}
                    {status === 'pending'  && <Circle       className="w-3.5 h-3.5 text-zinc-600" />}
                  </div>

                  {/* Token glow ring when active */}
                  {isToken && (
                    <motion.div
                      className="absolute inset-0 rounded-full border-2 border-amber-400"
                      animate={{ scale: [1, 1.5, 1], opacity: [0.8, 0, 0.8] }}
                      transition={{ duration: 1.2, repeat: Infinity }}
                    />
                  )}

                  {/* Approved glow */}
                  {status === 'approved' && (
                    <motion.div
                      className="absolute inset-0 rounded-full border border-emerald-400"
                      animate={{ scale: [1, 1.3, 1], opacity: [0.6, 0, 0.6] }}
                      transition={{ duration: 2, repeat: Infinity }}
                    />
                  )}
                </div>

                {/* Step label */}
                <span className={`text-[8px] font-mono font-semibold tracking-wider text-center leading-tight ${
                  status === 'approved'  ? 'text-emerald-400' :
                  status === 'vetoed'    ? 'text-rose-400' :
                  status === 'degraded'  ? 'text-orange-400' :
                  status === 'active'    ? 'text-amber-400' :
                                          'text-zinc-600'
                }`}>
                  {stage.label.toUpperCase()}
                </span>
              </div>

              {/* Connector arrow */}
              {index < PIPELINE_STAGES.length - 1 && (
                <div className="flex items-center px-0.5 mb-5">
                  <div className={`h-px w-4 transition-all duration-500 ${
                    getStepStatus(stage.id) === 'approved' ? 'bg-emerald-500/60' :
                    getStepStatus(stage.id) === 'vetoed' ? 'bg-rose-500/40' :
                    'bg-zinc-700'
                  }`} />
                  <ArrowRight className={`w-3 h-3 shrink-0 transition-all duration-500 ${
                    getStepStatus(stage.id) === 'approved' ? 'text-emerald-500/60' :
                    getStepStatus(stage.id) === 'vetoed' ? 'text-rose-500/40' :
                    'text-zinc-700'
                  }`} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Quorum + Details Row (Gaps 3, 4, 9) ──────────────────────────── */}
      {deliberation && (
        <div className="mt-4 pt-4 border-t border-white/5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* Quorum Gauge */}
            <QuorumGauge score={deliberation.quorumScore} isDegraded={deliberation.isDegraded} />

            {/* Veto agents list (if any) */}
            {deliberation.vetoAgents.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-rose-500/5 border border-rose-500/20">
                <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <div>
                  <span className="text-[8px] font-mono text-rose-400/70 block uppercase tracking-widest">Veto Agents</span>
                  <span className="text-[10px] font-mono font-bold text-rose-400">{deliberation.vetoAgents.join(', ')}</span>
                </div>
              </div>
            )}
          </div>

          {/* Detail cards: Signal, Qty, Urgency */}
          <DeliberationDetail deliberation={deliberation} />
        </div>
      )}

      {/* Live signal ticker — now shows reasoning string from backend (Gap 4) */}
      <div className="mt-4 pt-4 border-t border-white/5">
        <div className="flex items-start gap-2">
          <span className="text-[9px] font-mono text-zinc-600 shrink-0 mt-0.5">SIGNAL</span>
          <AnimatePresence mode="wait">
            <motion.p
              key={lastSignal}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              className="text-[10px] font-mono text-zinc-300 leading-relaxed"
            >
              {lastSignal}
            </motion.p>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
