'use client';

import { motion } from 'framer-motion';
import { AgentState } from '@/hooks/useAgentStream';
import { X, CheckCircle2, XCircle, Clock, Activity, BrainCircuit } from 'lucide-react';

interface AgentDetailsPanelProps {
  agent?: AgentState;
  onClose: () => void;
}

export function AgentDetailsPanel({ agent, onClose }: AgentDetailsPanelProps) {
  if (!agent) return null;

  const isApproved = agent.status === 'approved';
  const isVetoed = agent.status === 'vetoed';
  const isProcessing = agent.status === 'processing';

  return (
    <motion.div
      initial={{ width: 0, opacity: 0, marginLeft: 0 }}
      animate={{ width: 320, opacity: 1, marginLeft: 0 }}
      exit={{ width: 0, opacity: 0, marginLeft: -16 }}
      transition={{ type: 'spring', damping: 25, stiffness: 200 }}
      className="hidden lg:flex flex-col bg-zinc-900 border border-white/10 rounded-2xl overflow-hidden shrink-0 h-full max-h-[700px]"
    >
      <div className="p-4 border-b border-white/10 flex items-center justify-between bg-zinc-950/50">
        <div>
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">{agent.name}</h2>
          <p className="text-[10px] text-zinc-500 font-mono tracking-widest uppercase">{agent.role}</p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 bg-zinc-950/30 border-b border-white/5 flex items-center gap-4">
        <div className="flex-1">
          <div className="text-[10px] text-zinc-500 font-mono mb-1 uppercase">Status</div>
          <div className="flex items-center gap-2">
            {isApproved && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
            {isVetoed && <XCircle className="w-4 h-4 text-rose-400" />}
            {isProcessing && <Activity className="w-4 h-4 text-amber-400 animate-pulse" />}
            {agent.status === 'idle' && <Clock className="w-4 h-4 text-zinc-500" />}
            <span className={`text-xs font-bold uppercase tracking-wider ${
              isApproved ? 'text-emerald-400' :
              isVetoed ? 'text-rose-400' :
              isProcessing ? 'text-amber-400' :
              'text-zinc-400'
            }`}>
              {agent.status}
            </span>
          </div>
        </div>
        
        {agent.metric && agent.metric !== '--' && (
          <div className="flex-1 border-l border-white/10 pl-4">
            <div className="text-[10px] text-zinc-500 font-mono mb-1 uppercase">{agent.metricLabel || 'Metric'}</div>
            <div className="text-xs font-bold text-white font-mono">{agent.metric}</div>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <BrainCircuit className="w-4 h-4 text-primary" />
          <h3 className="text-xs font-bold text-zinc-300 uppercase tracking-widest">Thought Stream</h3>
        </div>
        
        {agent.thoughts.length === 0 ? (
          <div className="text-xs text-zinc-600 font-mono text-center py-8">
            NO RECENT ACTIVITY
          </div>
        ) : (
          <div className="space-y-3 relative before:absolute before:inset-0 before:ml-[5px] before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-white/10 before:to-transparent">
            {agent.thoughts.map((thought, i) => (
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                key={thought.id || i}
                className="relative flex items-start gap-3"
              >
                <div className="relative z-10 w-3 h-3 mt-1 rounded-full bg-zinc-900 border-2 border-primary/50 shadow-[0_0_8px_rgba(var(--primary),0.5)]" />
                <div className="flex-1 bg-zinc-950/50 border border-white/5 rounded-xl p-3 shadow-sm">
                  <div className="text-[9px] text-zinc-500 font-mono mb-1">{thought.timestamp}</div>
                  <div className="text-xs text-zinc-300 leading-relaxed">{thought.text}</div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
