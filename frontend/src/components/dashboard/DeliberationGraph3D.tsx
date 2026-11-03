'use client';

import { useEffect, useState, useRef } from 'react';
import dynamic from 'next/dynamic';
import { AgentState, DecisionFlow, DeliberationMeta } from '@/hooks/useAgentStream';
import { Box, Orbit } from 'lucide-react';
import { OrbitalNexus } from './OrbitalNexus';

const ThreeScene = dynamic(
  () => import('./three/ThreeScene'),
  { ssr: false },
);

interface DeliberationGraph3DProps {
  agents: AgentState[];
  flow: DecisionFlow;
  enabledAgents: string[];
  deliberation: DeliberationMeta | null;
  onAgentSelect?: (agentId: string) => void;
  composure?: string;
  disciplineScore?: number;
}

const COMPOSURE_BADGE: Record<string, string> = {
  CALM:          'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
  FEARFUL:       'text-amber-400 border-amber-500/30 bg-amber-500/10',
  OVERCONFIDENT: 'text-sky-400 border-sky-500/30 bg-sky-500/10',
  GREEDY:        'text-fuchsia-400 border-fuchsia-500/30 bg-fuchsia-500/10',
  FATIGUED:      'text-orange-400 border-orange-500/30 bg-orange-500/10',
  TILTED:        'text-red-500 border-red-500/50 bg-red-500/10',
};

function ComposureBadge({ composure, disciplineScore }: { composure?: string; disciplineScore?: number }) {
  if (!composure) return null;
  const cls = COMPOSURE_BADGE[composure] ?? COMPOSURE_BADGE.CALM;
  return (
    <div className={`absolute top-3 left-3 z-10 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-mono font-bold ${cls}`}>
      <span>{composure}</span>
      {disciplineScore !== undefined && (
        <span className="text-zinc-400">· {disciplineScore.toFixed(0)}/100</span>
      )}
    </div>
  );
}

function useIsMobile() {
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    const check = () => setMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  return mobile;
}

export function DeliberationGraph3D(props: DeliberationGraph3DProps) {
  const isMobile = useIsMobile();
  const [mode, setMode] = useState<'2d' | '3d'>('2d');
  const containerRef = useRef<HTMLDivElement>(null);

  const switchTo3D = () => {
    if (!isMobile) setMode('3d');
  };

  if (mode === '2d') {
    return (
      <div className="relative flex-1 min-w-0 flex flex-col">
        <ComposureBadge composure={props.composure} disciplineScore={props.disciplineScore} />
        <div className="absolute top-3 right-3 z-10">
          <button
            onClick={switchTo3D}
            disabled={isMobile}
            title={isMobile ? '3D view unavailable on mobile' : 'Switch to 3D view'}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-white/10 text-[10px] font-mono font-bold text-zinc-400 hover:text-zinc-200 hover:border-primary/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Box className="w-3.5 h-3.5" />
            3D
          </button>
        </div>
        <OrbitalNexus
          agents={props.agents}
          flow={props.flow}
          enabledAgents={props.enabledAgents}
          deliberation={props.deliberation}
          onAgentSelect={props.onAgentSelect}
        />
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative flex-1 min-w-0 min-h-[500px] bg-zinc-950 rounded-2xl border border-white/5 overflow-hidden">
      <ComposureBadge composure={props.composure} disciplineScore={props.disciplineScore} />
      <div className="absolute top-3 right-3 z-10">
        <button
          onClick={() => setMode('2d')}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-white/10 text-[10px] font-mono font-bold text-zinc-400 hover:text-zinc-200 hover:border-primary/30 transition-all"
        >
          <Orbit className="w-3.5 h-3.5" />
          2D
        </button>
      </div>

      <ThreeScene
        agents={props.agents}
        flow={props.flow}
        enabledAgents={props.enabledAgents}
        onAgentSelect={props.onAgentSelect}
      />
    </div>
  );
}
