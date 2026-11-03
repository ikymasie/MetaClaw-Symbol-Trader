'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import { AgentStatus } from '@/hooks/useAgentStream';

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: '#27272a',
  processing: '#fbbf24',
  approved: '#34d399',
  vetoed: '#f43f5e',
  disabled: '#18181b',
  degraded: '#f97316',
};

interface ConnectionEdge3DProps {
  from: [number, number, number];
  to: [number, number, number];
  fromStatus: AgentStatus;
  toStatus: AgentStatus;
  isFlowing: boolean;
}

export function ConnectionEdge3D({
  from,
  to,
  toStatus,
  isFlowing,
}: ConnectionEdge3DProps) {
  const particleRef = useRef<THREE.Mesh>(null);

  const { curve, points } = useMemo(() => {
    const dx = to[0] - from[0];
    const dz = to[2] - from[2];
    const dist = Math.sqrt(dx * dx + dz * dz);
    const controlY = Math.min(dist * 0.3, 1.5);

    const midX = (from[0] + to[0]) / 2;
    const midZ = (from[2] + to[2]) / 2;
    const midY = (from[1] + to[1]) / 2 + controlY;

    const curve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(from[0], from[1], from[2]),
      new THREE.Vector3(midX, midY, midZ),
      new THREE.Vector3(to[0], to[1], to[2])
    );

    return { curve, points: curve.getPoints(30) };
  }, [from, to]);

  const tubeGeometry = useMemo(
    () => new THREE.TubeGeometry(curve, 20, 0.04, 8, false),
    [curve],
  );

  const color = isFlowing
    ? '#fbbf24'
    : toStatus === 'processing'
      ? STATUS_COLORS.processing
      : toStatus === 'approved'
        ? STATUS_COLORS.approved
        : toStatus === 'vetoed'
          ? STATUS_COLORS.vetoed
          : '#27272a';

  const tubeMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(color),
        transparent: true,
        opacity: isFlowing ? 0.7 : 0.3,
      }),
    [color, isFlowing],
  );

  const particlePos = useRef(0);

  useFrame((_, delta) => {
    if (!particleRef.current) return;

    if (isFlowing) {
      particlePos.current += delta * 0.4;
      if (particlePos.current > 1) {
        particlePos.current -= 1;
      }

      const pt = curve.getPoint(particlePos.current);
      particleRef.current.position.copy(pt);
      particleRef.current.visible = true;
    } else {
      particleRef.current.visible = false;
    }
  });

  return (
    <group>
      <mesh geometry={tubeGeometry} material={tubeMaterial} />

      <Line
        points={points}
        color={color}
        lineWidth={1}
        dashed
        dashSize={0.12}
        gapSize={0.18}
        transparent
        opacity={isFlowing ? 0.5 : 0}
      />

      <mesh ref={particleRef} visible={false}>
        <sphereGeometry args={[0.1, 8, 8]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  );
}
