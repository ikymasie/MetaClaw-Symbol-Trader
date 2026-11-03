'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Text } from '@react-three/drei';
import * as THREE from 'three';
import { AgentState, AgentStatus } from '@/hooks/useAgentStream';

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: '#52525b',
  processing: '#fbbf24',
  approved: '#34d399',
  vetoed: '#f43f5e',
  disabled: '#27272a',
  degraded: '#f97316',
};

const STATUS_EMISSIVE: Record<AgentStatus, string> = {
  idle: '#18181b',
  processing: '#f59e0b',
  approved: '#10b981',
  vetoed: '#e11d48',
  disabled: '#09090b',
  degraded: '#ea580c',
};

const AGENT_RADIUS: Record<string, number> = {
  watchman: 0.55,
  macro_analyst: 0.55,
  sentiment_analyst: 0.5,
  earnings_analyst: 0.5,
  technical_analyst: 0.5,
  risk_manager: 0.55,
  executioner: 0.6,
};

function randomPhase() {
  return Math.random() * Math.PI * 2;
}

interface AgentNode3DProps {
  agent: AgentState;
  position: [number, number, number];
  isActive: boolean;
  isDisabled: boolean;
  onClick?: () => void;
}

export function AgentNode3D({ agent, position, isActive, isDisabled, onClick }: AgentNode3DProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);
  const floatOffset = useRef(randomPhase());

  const color = isDisabled ? STATUS_COLORS.disabled : STATUS_COLORS[agent.status];
  const emissive = isDisabled ? STATUS_EMISSIVE.disabled : STATUS_EMISSIVE[agent.status];
  const radius = AGENT_RADIUS[agent.id] ?? 0.5;

  const geometry = useMemo(() => new THREE.IcosahedronGeometry(radius, 1), [radius]);

  const materialRef = useRef<THREE.MeshStandardMaterial>(null);

  useFrame((_, delta) => {
    if (!meshRef.current || !materialRef.current) return;

    floatOffset.current += delta * 0.6;
    const floatY = Math.sin(floatOffset.current) * 0.08;
    meshRef.current.position.y = position[1] + floatY;

    if (glowRef.current) {
      glowRef.current.position.y = position[1] + floatY;
    }
    if (ringRef.current) {
      ringRef.current.position.y = position[1] + floatY;
      ringRef.current.rotation.z += delta * 0.3;
    }

    if (agent.status === 'processing') {
      const pulse = 0.4 + Math.sin(floatOffset.current * 2) * 0.4;
      materialRef.current.emissiveIntensity = pulse;
    } else if (agent.status === 'approved') {
      materialRef.current.emissiveIntensity = 0.5 + Math.sin(floatOffset.current) * 0.15;
    } else if (agent.status === 'vetoed') {
      const pulse = 0.3 + Math.sin(floatOffset.current * 4) * 0.4;
      materialRef.current.emissiveIntensity = pulse;
    }

    if (glowRef.current) {
      const glowScale = agent.status === 'processing'
        ? 1.8 + Math.sin(floatOffset.current * 2) * 0.3
        : agent.status === 'approved'
          ? 1.6 + Math.sin(floatOffset.current) * 0.15
          : 1.4;
      glowRef.current.scale.setScalar(glowScale);
      const glowMat = glowRef.current.material as THREE.MeshBasicMaterial;
      glowMat.opacity =
        agent.status === 'processing' ? 0.12 + Math.sin(floatOffset.current * 2) * 0.06
        : agent.status === 'approved' ? 0.15
        : 0.08;
    }
  });

  const handleClick = (e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    onClick?.();
  };

  return (
    <group>
      <mesh
        ref={meshRef}
        position={position}
        geometry={geometry}
        onClick={handleClick}
        onPointerOver={(e) => { e.object.scale.setScalar(1.15); document.body.style.cursor = 'pointer'; }}
        onPointerOut={(e) => { e.object.scale.setScalar(1); document.body.style.cursor = 'default'; }}
      >
        <meshStandardMaterial
          ref={materialRef}
          color={new THREE.Color(color)}
          emissive={new THREE.Color(emissive)}
          emissiveIntensity={isDisabled ? 0 : isActive ? 0.8 : agent.status === 'approved' ? 0.6 : agent.status === 'vetoed' ? 0.7 : 0.15}
          metalness={0.3}
          roughness={0.4}
        />
      </mesh>

      <mesh ref={glowRef} position={position}>
        <sphereGeometry args={[radius * 1.8, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.1}
          depthWrite={false}
        />
      </mesh>

      {agent.status !== 'idle' && agent.status !== 'disabled' && (
        <mesh ref={ringRef} position={position} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[radius * 1.6, radius * 2, 32]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.2}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      )}

      <Text
        position={[position[0], position[1] - radius - 0.5, position[2]]}
        fontSize={0.22}
        color={color}
        anchorX="center"
        anchorY="top"
      >
        {agent.name}
      </Text>

      {agent.metric && agent.metric !== '--' && (
        <Text
          position={[position[0], position[1] - radius - 0.85, position[2]]}
          fontSize={0.16}
          color="#71717a"
          anchorX="center"
          anchorY="top"
        >
          {agent.metric}
        </Text>
      )}
    </group>
  );
}
