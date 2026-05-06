'use client';

import { useMemo, useState, useRef, useEffect } from 'react';
import { motion } from 'framer-motion';
import { AgentState, DecisionFlow, DeliberationMeta } from '@/hooks/useAgentStream';
import { OrbitalAgent } from './OrbitalAgent';
import { OrbitalCore } from './OrbitalCore';

interface OrbitalNexusProps {
  agents: AgentState[];
  flow: DecisionFlow;
  enabledAgents: string[];
  deliberation: DeliberationMeta | null;
  onAgentSelect?: (agentId: string) => void;
}

export function OrbitalNexus({ agents, flow, enabledAgents, deliberation, onAgentSelect }: OrbitalNexusProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 600 });

  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      if (entries[0]) {
        setDimensions({
          width: entries[0].contentRect.width,
          height: entries[0].contentRect.height,
        });
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const orbitingAgents = useMemo(() => {
    return agents
      .filter(a => a.id !== 'executioner')
      .sort((a, b) => {
        if (enabledAgents.length === 0) return 0;
        const aEnabled = enabledAgents.includes(a.id);
        const bEnabled = enabledAgents.includes(b.id);
        if (aEnabled && !bEnabled) return -1;
        if (!aEnabled && bEnabled) return 1;
        return 0;
      });
  }, [agents, enabledAgents]);

  // Responsive semi-axes for ellipse. Provide 120px padding.
  const rx = Math.max(150, (dimensions.width / 2) - 120);
  const ry = Math.max(150, (dimensions.height / 2) - 140);
  
  // Calculate dynamic angles
  const layoutData = useMemo(() => {
    let totalUnits = 0;
    const units = orbitingAgents.map(agent => {
      // Base unit of 1, plus extra space for thoughts
      const agentUnits = 1 + (agent.thoughts.length * 0.3);
      totalUnits += agentUnits;
      return agentUnits;
    });

    if (totalUnits === 0) return []; // Prevent NaN angles

    let currentAngle = -Math.PI / 2; // Start from top
    const agentLayouts = orbitingAgents.map((agent, i) => {
      const halfUnitAngle = (units[i] / totalUnits) * (2 * Math.PI) / 2;
      const angle = currentAngle + halfUnitAngle;
      currentAngle += (units[i] / totalUnits) * (2 * Math.PI);
      return { agent, angle, index: i };
    });

    return agentLayouts;
  }, [orbitingAgents]);

  return (
    <div ref={containerRef} className="relative flex-1 min-w-0 min-h-[500px] flex items-center justify-center overflow-hidden bg-zinc-950 rounded-2xl border border-white/5 shadow-inner">
      
      {/* Background Radar Rings - Responsive */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-20">
        <div 
          className="absolute rounded-[50%] border border-zinc-500/30 border-dashed transition-all duration-300" 
          style={{ width: `${rx * 2}px`, height: `${ry * 2}px` }} 
        />
        <div 
          className="absolute rounded-[50%] border border-zinc-600/20 transition-all duration-300"
          style={{ width: `${rx * 1.4}px`, height: `${ry * 1.4}px` }} 
        />
        <div 
          className="absolute rounded-[50%] border border-zinc-700/10 transition-all duration-300"
          style={{ width: `${rx * 2.6}px`, height: `${ry * 2.6}px` }} 
        />
      </div>

      {/* SVG Data Flow Paths */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
        <g style={{ transform: 'translate(50%, 50%)' }}>
          {layoutData.map(({ agent, angle }) => {
            const isActive = enabledAgents.length === 0 || enabledAgents.includes(agent.id);
            if (!isActive) return null;

            const x = Math.cos(angle) * rx || 0;
            const y = Math.sin(angle) * ry || 0;
            const isProcessing = agent.status === 'processing';
            const isApproved = agent.status === 'approved';
            const isVetoed = agent.status === 'vetoed';

            let strokeColor = 'rgba(255,255,255,0.1)';
            if (isProcessing) strokeColor = 'rgba(251, 191, 36, 0.4)'; // amber
            else if (isApproved) strokeColor = 'rgba(52, 211, 153, 0.4)'; // emerald
            else if (isVetoed) strokeColor = 'rgba(244, 63, 94, 0.4)'; // rose

            const strokeWidth = 1 + (agent.weight || 1);

            return (
              <motion.line
                key={`line-${agent.id}`}
                x1={x}
                y1={y}
                x2={0}
                y2={0}
                stroke={strokeColor}
                strokeWidth={strokeWidth}
                strokeDasharray="4 4"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.5 }}
              />
            );
          })}
          
          {/* Pulsing overlay lines for active processing */}
          {layoutData.map(({ agent, angle }) => {
            if (agent.status !== 'processing') return null;
            const x = Math.cos(angle) * rx || 0;
            const y = Math.sin(angle) * ry || 0;
            
            return (
              <motion.line
                key={`pulse-${agent.id}`}
                x1={x}
                y1={y}
                x2={0}
                y2={0}
                stroke="rgba(251, 191, 36, 0.8)"
                strokeWidth={2}
                initial={{ pathLength: 0, pathOffset: 1 }}
                animate={{ pathLength: 0.2, pathOffset: 0 }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
              />
            );
          })}
        </g>
      </svg>

      {/* Agents */}
      {layoutData.map(({ agent, angle, index }) => {
        const isDisabled = enabledAgents.length > 0 && !enabledAgents.includes(agent.id);
        const isActive = !isDisabled && flow.activeStep === index;
        return (
          <OrbitalAgent
            key={agent.id}
            agent={agent}
            isActive={isActive}
            disabled={isDisabled}
            angle={angle}
            rx={rx}
            ry={ry}
            onClick={() => onAgentSelect?.(agent.id)}
          />
        );
      })}

      {/* Core */}
      <OrbitalCore deliberation={deliberation} />
      
    </div>
  );
}
