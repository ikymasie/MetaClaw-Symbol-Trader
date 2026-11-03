'use client';

import { useMemo } from 'react';
import { AgentId } from '@/hooks/useAgentStream';

export interface NodeLayout {
  id: AgentId;
  position: [number, number, number];
  layer: number;
}

export interface EdgeDef {
  from: AgentId;
  to: AgentId;
}

const PIPELINE_ORDER: AgentId[] = [
  'watchman',
  'macro_analyst',
  'sentiment_analyst',
  'earnings_analyst',
  'technical_analyst',
  'risk_manager',
  'executioner',
];

const LAYER_Z: Record<string, number> = {
  watchman: -8,
  macro_analyst: -4,
  sentiment_analyst: 0,
  earnings_analyst: 0,
  technical_analyst: 0,
  risk_manager: 4,
  executioner: 8,
};

const LAYER_X: Record<string, number> = {
  watchman: 0,
  macro_analyst: 0,
  sentiment_analyst: -3.5,
  earnings_analyst: 0,
  technical_analyst: 3.5,
  risk_manager: 0,
  executioner: 0,
};

const LAYER_Y: Record<string, number> = {
  watchman: 0.5,
  macro_analyst: 1,
  sentiment_analyst: -1,
  earnings_analyst: 1,
  technical_analyst: -1,
  risk_manager: 0.5,
  executioner: 0,
};

export const EDGES: EdgeDef[] = [
  { from: 'watchman', to: 'macro_analyst' },
  { from: 'macro_analyst', to: 'sentiment_analyst' },
  { from: 'macro_analyst', to: 'earnings_analyst' },
  { from: 'macro_analyst', to: 'technical_analyst' },
  { from: 'sentiment_analyst', to: 'risk_manager' },
  { from: 'earnings_analyst', to: 'risk_manager' },
  { from: 'technical_analyst', to: 'risk_manager' },
  { from: 'risk_manager', to: 'executioner' },
];

export const PIPELINE_FLOW: AgentId[] = [
  'watchman',
  'macro_analyst',
  'sentiment_analyst',
  'earnings_analyst',
  'technical_analyst',
  'risk_manager',
  'executioner',
];

export function useGraphLayout(): NodeLayout[] {
  return useMemo(() => {
    return PIPELINE_ORDER.map((id) => ({
      id,
      position: [LAYER_X[id] ?? 0, LAYER_Y[id] ?? 0, LAYER_Z[id] ?? 0],
      layer: LAYER_Z[id] ?? 0,
    }));
  }, []);
}
