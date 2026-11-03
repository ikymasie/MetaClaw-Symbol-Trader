'use client';

import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { AdaptiveDpr } from '@react-three/drei';
import { EffectComposer, Bloom } from '@react-three/postprocessing';
import { SceneSetup } from './SceneSetup';
import { AgentNode3D } from './AgentNode3D';
import { ConnectionEdge3D } from './ConnectionEdge3D';
import { useGraphLayout, EDGES, PIPELINE_FLOW } from './useGraphLayout';
import { AgentState, DecisionFlow } from '@/hooks/useAgentStream';

interface ThreeSceneProps {
  agents: AgentState[];
  flow: DecisionFlow;
  enabledAgents: string[];
  onAgentSelect?: (agentId: string) => void;
}

function DeliberationScene({ agents, flow, enabledAgents, onAgentSelect }: ThreeSceneProps) {
  const layout = useGraphLayout();

  const agentMap = useMemo(() => {
    const map = new Map<string, AgentState>();
    agents.forEach((a) => map.set(a.id, a));
    return map;
  }, [agents]);

  const flowStep = flow.isFlowing ? 6 : flow.activeStep;

  return (
    <>
      <SceneSetup />

      {layout.map((node) => {
        const agent = agentMap.get(node.id);
        if (!agent) return null;

        const isDisabled = enabledAgents.length > 0 && !enabledAgents.includes(agent.id);
        const stepIndex = PIPELINE_FLOW.indexOf(agent.id);
        const isActive = flow.isFlowing && stepIndex >= 0 && stepIndex <= flowStep;

        return (
          <AgentNode3D
            key={agent.id}
            agent={agent}
            position={node.position}
            isActive={isActive}
            isDisabled={isDisabled}
            onClick={() => onAgentSelect?.(agent.id)}
          />
        );
      })}

      {EDGES.map((edge) => {
        const fromNode = layout.find((n) => n.id === edge.from);
        const toNode = layout.find((n) => n.id === edge.to);
        if (!fromNode || !toNode) return null;

        const fromAgent = agentMap.get(edge.from);
        const toAgent = agentMap.get(edge.to);
        if (!fromAgent || !toAgent) return null;

        const fromStep = PIPELINE_FLOW.indexOf(edge.from);
        const toStep = PIPELINE_FLOW.indexOf(edge.to);
        const isThisFlowing = flow.isFlowing && flowStep >= fromStep && flowStep >= toStep;

        return (
          <ConnectionEdge3D
            key={`${edge.from}-${edge.to}`}
            from={fromNode.position}
            to={toNode.position}
            fromStatus={fromAgent.status}
            toStatus={toAgent.status}
            isFlowing={isThisFlowing}
          />
        );
      })}

      <EffectComposer>
        <Bloom
          luminanceThreshold={0.2}
          luminanceSmoothing={0.9}
          intensity={0.6}
        />
      </EffectComposer>
    </>
  );
}

export default function ThreeScene(props: ThreeSceneProps) {
  return (
    <Canvas
      camera={{ position: [6, 4, 14], fov: 50 }}
      dpr={[1, 1.5]}
      gl={{
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
      }}
    >
      <AdaptiveDpr pixelated />
      <color attach="background" args={['#09090b']} />
      <DeliberationScene
        agents={props.agents}
        flow={props.flow}
        enabledAgents={props.enabledAgents}
        onAgentSelect={props.onAgentSelect}
      />
    </Canvas>
  );
}
