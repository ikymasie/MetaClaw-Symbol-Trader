'use client';

import { useEffect, useRef } from 'react';
import { OrbitControls } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import type { OrbitControls as OrbitControlsType } from 'three-stdlib';

export function SceneSetup() {
  const controlsRef = useRef<OrbitControlsType>(null);
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(6, 4, 14);
    camera.lookAt(0, 0, 0);
  }, [camera]);

  useFrame(() => {
    if (controlsRef.current && !controlsRef.current.isDragging) {
      controlsRef.current.autoRotate = true;
    }
  });

  return (
    <>
      <ambientLight intensity={0.3} />
      <pointLight position={[10, 10, 10]} intensity={1.5} color="#ffffff" />
      <pointLight position={[-10, -5, -10]} intensity={0.8} color="#4466ff" />
      <spotLight position={[0, 10, 0]} angle={0.5} penumbra={1} intensity={0.5} color="#8888ff" />

      <OrbitControls
        ref={controlsRef}
        autoRotate
        autoRotateSpeed={1.2}
        enableDamping
        dampingFactor={0.08}
        minDistance={6}
        maxDistance={30}
        maxPolarAngle={Math.PI / 2.2}
      />
    </>
  );
}
