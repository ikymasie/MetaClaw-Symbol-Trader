'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { getWsUrl } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

export type AgentStatus = 'idle' | 'processing' | 'approved' | 'vetoed' | 'disabled' | 'degraded';

export type AgentId =
  | 'watchman'
  | 'macro_analyst'
  | 'earnings_analyst'
  | 'technical_analyst'
  | 'sentiment_analyst'
  | 'risk_manager'
  | 'executioner';

export interface ThoughtEntry {
  id: string;
  timestamp: string;
  text: string;
}

export interface AgentState {
  id: AgentId;
  name: string;
  role: string;
  status: AgentStatus;
  thoughts: ThoughtEntry[];
  metric?: string;
  metricLabel?: string;
  progress: number; // 0–100 for progress bar
  weight?: number;  // Agent vote weight in quorum (Gap 8)
}

export interface DeliberationMeta {
  quorumScore: number;       // Weighted vote score (-1.0 to +1.0)
  approved: boolean;
  reasoning: string;         // Final synthesis string from backend
  orderUrgency: string;      // "HIGH" | "LOW"
  approvedQty: number;       // Kelly-approved qty
  signal: string;            // "BUY" | "SELL" | "HOLD"
  vetoAgents: string[];      // Agents that issued VETO
  isDegraded: boolean;       // >50% panel agents failed (Gap 9)
}

export interface DecisionFlow {
  activeStep: number; // 0–6, index of the pipeline step currently lit
  tokenPosition: number; // 0–6
  isFlowing: boolean;
}

// ─── Agent monologue scenarios ────────────────────────────────────────────────

const AGENT_SCRIPTS: Record<AgentId, string[][]> = {
  watchman: [
    ['Scanning market on 1m bars...', 'New bar closed — price action updating', 'Volume spike detected: 3.2× avg', 'RSI(14) = 62.4 — Momentum gathering', 'Dispatching quality check to pipeline'],
    ['Monitoring order-flow quality...', 'Bid-ask spread within tolerance', 'ATR(14) stable — low volatility', 'No anomalies detected ✓', 'Market quality: CLEAR'],
  ],
  macro_analyst: [
    ['Analysing VIX / yield curve / Fed language...', 'VIX @ 18.2 — Subdued fear environment', 'Yield curve slope: normal (positive)', 'Fed stance: data-dependent, no pivot signal', 'Macro outlook: NEUTRAL-POSITIVE'],
    ['Scanning macro indicators...', 'Treasury 10Y-2Y spread: +0.15 bps', 'ISM Manufacturing: 49.2 (contracting)', 'Dollar index stable at 104.3', 'Macro regime: RISK-ON'],
  ],
  earnings_analyst: [
    ['Checking earnings calendar...', 'Next report: 14 days out — low risk', 'Earnings whisper: +$0.08 vs consensus', 'Post-earnings drift history: N/A', 'Earnings risk: CLEAR — no imminent catalyst'],
    ['Evaluating earnings risk window...', 'No earnings within 7-day blackout', 'Sector earnings trend: mixed signals', 'Historical surprise rate: 62% beat', 'Earnings gate: PASS ✓'],
  ],
  technical_analyst: [
    ['Running cross-timeframe TA...', 'Bollinger Band squeeze resolved upward', 'VWAP + 1.5σ band penetrated — valid setup', 'RSI divergence: none detected', 'Technical signal: BULLISH (score 0.78)'],
    ['Performing technical analysis...', 'Trend: above 200MA (bullish)', 'Momentum: RSI(14) = 58 — neutral zone', 'Volume: declining on pullback (healthy)', 'TA composite: MILDLY BULLISH'],
  ],
  sentiment_analyst: [
    ['Pulling news feed from 12 sources...', 'Bullish articles outnumber bearish 3:1', 'FinBERT sentiment: +0.67 (Bullish)', 'Social velocity: ▲ 340% vs baseline', 'Sentiment CLEAR — no macro headwinds'],
    ['Scanning sentiment sources...', 'Put/Call ratio: 0.62 — bullish skew', 'Dark pool activity: neutral', 'Options flow: no unusual activity', 'Sentiment: NEUTRAL-POSITIVE'],
  ],
  risk_manager: [
    ['Calculating Kelly Criterion...', 'Input: p=0.55, b=2.1', 'Kelly fraction: f* = 0.336', 'Half-Kelly applied: 0.168 → position size', 'Max risk per trade within bounds'],
    ['Running drawdown simulation...', 'Current portfolio heat: 2.3% at risk', 'Max concurrent exposure cap: 6%', 'Correlation risk with open positions: LOW', 'APPROVED — risk within acceptable bounds'],
  ],
  executioner: [
    ['Receiving approved trade signal...', 'Verifying account margin...', 'Account buying power sufficient', 'Submitting order at market...', 'Order filled — slippage within tolerance ✓'],
    ['Trade packet received from Risk Manager', 'Pre-flight: spread check PASS ✓', 'Order routing: smart route selected', 'Execution complete', 'Position is live 🟢'],
  ],
};

// ─── Pipeline stage labels ────────────────────────────────────────────────────

export const PIPELINE_STAGES: { id: AgentId; label: string }[] = [
  { id: 'watchman', label: 'Watchman' },
  { id: 'macro_analyst', label: 'Macro' },
  { id: 'earnings_analyst', label: 'Earnings' },
  { id: 'technical_analyst', label: 'Technical' },
  { id: 'sentiment_analyst', label: 'Sentiment' },
  { id: 'risk_manager', label: 'Risk Mgr' },
  // executioner removed — rendered as fixed Verdict Panel sidebar
];

// ─── Agent vote weights (mirrors backend sub_agents.py) ───────────────────────

const AGENT_WEIGHTS: Partial<Record<AgentId, number>> = {
  watchman: 1.25,
  macro_analyst: 1.0,
  earnings_analyst: 1.5,
  technical_analyst: 0.75,
  sentiment_analyst: 1.0,
  risk_manager: 1.0,
};

// ─── Initial state ────────────────────────────────────────────────────────────

const INITIAL_AGENTS: AgentState[] = [
  { id: 'watchman',           name: 'WATCHMAN',           role: 'Market Quality Gate',    status: 'idle', thoughts: [], metric: '--', metricLabel: 'Quality',    progress: 0, weight: 1.25 },
  { id: 'macro_analyst',      name: 'MACRO ANALYST',      role: 'VIX / Yield / Fed',      status: 'idle', thoughts: [], metric: '--', metricLabel: 'Macro',      progress: 0, weight: 1.0  },
  { id: 'earnings_analyst',   name: 'EARNINGS ANALYST',   role: 'Earnings Risk Gate',     status: 'idle', thoughts: [], metric: '--', metricLabel: 'Earnings',   progress: 0, weight: 1.5  },
  { id: 'technical_analyst',  name: 'TECHNICAL ANALYST',  role: 'Cross-TF TA',            status: 'idle', thoughts: [], metric: '--', metricLabel: 'TA Score',   progress: 0, weight: 0.75 },
  { id: 'sentiment_analyst',  name: 'SENTIMENT ANALYST',  role: 'NLP / Sentiment',        status: 'idle', thoughts: [], metric: '--', metricLabel: 'Sentiment',  progress: 0, weight: 1.0  },
  { id: 'risk_manager',       name: 'RISK MANAGER',       role: 'Kelly Criterion Gate',   status: 'idle', thoughts: [], metric: '--', metricLabel: 'Kelly f*',   progress: 0, weight: 1.0  },
  { id: 'executioner',        name: 'EXECUTIONER',        role: 'Order Execution',        status: 'idle', thoughts: [], metric: '--', metricLabel: 'Fill Price', progress: 0 },
];

const AGENT_IDS: AgentId[] = ['watchman', 'macro_analyst', 'earnings_analyst', 'technical_analyst', 'sentiment_analyst', 'risk_manager', 'executioner'];

const MAX_THOUGHTS_PER_AGENT = 10;
const INITIAL_RECONNECT_MS = 3000;
const MAX_RECONNECT_MS = 30000;

function timestamp() {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function randBetween(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function pickScript(id: AgentId) {
  const scripts = AGENT_SCRIPTS[id];
  return scripts[Math.floor(Math.random() * scripts.length)];
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * @param botId — the bot to stream agent data for
 * @param enabled — master switch; when false, WS is cleanly closed
 */
export function useAgentStream(botId?: string, enabled: boolean = true) {
  const [agents, setAgents] = useState<AgentState[]>(INITIAL_AGENTS);
  const [flow, setFlow] = useState<DecisionFlow>({ activeStep: -1, tokenPosition: -1, isFlowing: false });
  const [cycleCount, setCycleCount] = useState(0);
  const [lastSignal, setLastSignal] = useState<string>('Awaiting market signal...');
  const [enabledAgents, setEnabledAgents] = useState<string[]>([]);
  const [deliberation, setDeliberation] = useState<DeliberationMeta | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mounted = useRef(true);
  const backoffRef = useRef(INITIAL_RECONNECT_MS);

  // ─── Mapping from backend agent keys to frontend IDs ─────────────────
  // Corrected to match actual backend AGENT_CLASSES in sub_agents.py:
  //   watchman, sentiment, macro, earnings, technical, risk_manager
  const agentMap: Record<string, AgentId> = {
    watchman: 'watchman',
    macro: 'macro_analyst',
    earnings: 'earnings_analyst',
    technical: 'technical_analyst',
    sentiment: 'sentiment_analyst',
    risk_manager: 'risk_manager',
    // executioner has no backend voting agent — it shows execution state
  };

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // ─── LangGraph deliberation_event handler ───────────────────────
  // Handles real-time per-node events streamed during active deliberations.
  // These arrive between (or instead of) the regular 500ms bot_update snapshots.
  const processDeliberationEvent = useCallback((data: any) => {
    const { event, node, agent, vote, confidence, reasoning, score, met, approved, signal } = data;

    // Map node names → AgentIds (deliberation_graph.py _NODE_TO_AGENT)
    const nodeToAgentId: Record<string, AgentId | undefined> = {
      watchman: 'watchman',
      ict: undefined,             // ICT has no Situation Room card
      macro_prefilter: 'macro_analyst',
      panel: undefined,           // panel node emits per-agent sub-events
      macro: 'macro_analyst',
      sentiment: 'sentiment_analyst',
      earnings: 'earnings_analyst',
      technical: 'technical_analyst',
      cro: undefined,
      risk_manager: 'risk_manager',
      finalize: 'executioner',
    };

    const agentId = nodeToAgentId[agent ?? node];

    if (event === 'agent_start' && agentId) {
      setAgents(prev => prev.map(a =>
        a.id === agentId ? { ...a, status: 'processing' as const, progress: 30 } : a
      ));
    }

    if (event === 'agent_done' && agentId && vote) {
      const isVeto = vote === 'VETO';
      const thought = reasoning ? { id: `${Date.now()}`, timestamp: timestamp(), text: reasoning } : null;
      setAgents(prev => prev.map(a => {
        if (a.id !== agentId) return a;
        return {
          ...a,
          status: isVeto ? 'vetoed' as const : 'approved' as const,
          progress: 100,
          metric: confidence != null ? `${Math.round(confidence * 100)}%` : a.metric,
          metricLabel: 'Confidence',
          thoughts: thought
            ? [...a.thoughts.slice(-(MAX_THOUGHTS_PER_AGENT - 1)), thought]
            : a.thoughts,
        };
      }));
    }

    if (event === 'quorum_result') {
      setLastSignal(
        met ? `Quorum reached (score ${(score ?? 0).toFixed(3)})` : `Quorum failed (score ${(score ?? 0).toFixed(3)})`
      );
    }

    if (event === 'final_decision') {
      setAgents(prev => prev.map(a =>
        a.id === 'executioner'
          ? {
              ...a,
              status: approved ? 'approved' as const : 'vetoed' as const,
              progress: 100,
              metric: approved ? 'FILLED' : 'BLOCKED',
              thoughts: [
                ...a.thoughts.slice(-(MAX_THOUGHTS_PER_AGENT - 1)),
                { id: `${Date.now()}`, timestamp: timestamp(), text: reasoning ?? `Signal: ${signal}` },
              ],
            }
          : a
      ));
    }
  }, []);

  const processUpdate = useCallback((data: any) => {
    // Route LangGraph real-time events to the dedicated handler
    if (data.type === 'deliberation_event') {
      processDeliberationEvent(data);
      return;
    }

    if (data.type !== 'bot_update') return;

    const {
      last_deliberation,
      regime, status, symbol,
      enabled_agents: wsEnabledAgents,
      agent_weights: darwinianWeights,
    } = data;

    // Track which agents are enabled for this bot
    if (wsEnabledAgents && Array.isArray(wsEnabledAgents)) {
      // Map backend agent keys to frontend AgentIds
      const mappedEnabled = wsEnabledAgents.map((k: string) => agentMap[k]).filter(Boolean);
      // Always include watchman, risk_manager, executioner (system agents)
      const systemAgents: AgentId[] = ['watchman', 'risk_manager', 'executioner'];
      const fullEnabled = [...new Set([...systemAgents, ...mappedEnabled])];
      setEnabledAgents(fullEnabled);
    }
    if (!last_deliberation || !last_deliberation.votes) return;

    // ── Extract deliberation metadata (Gaps 1, 2, 3, 4, 9) ──────────
    const vetoAgents: string[] = last_deliberation.veto_agents || [];
    const hasVeto = vetoAgents.length > 0;
    const quorumScore: number = last_deliberation.quorum_score ?? 0;
    const isApproved: boolean = !!last_deliberation.approved;
    const isDegraded = (last_deliberation.reasoning || '').includes('degraded');

    // Build quorum status string from real data instead of non-existent field
    const quorumLabel = hasVeto ? 'VETOED' : (isDegraded ? 'DEGRADED' : (isApproved ? 'APPROVED' : (quorumScore >= 0.2 ? 'REACHED' : 'PENDING')));

    setDeliberation({
      quorumScore,
      approved: isApproved,
      reasoning: last_deliberation.reasoning || '',
      orderUrgency: last_deliberation.order_urgency || 'LOW',
      approvedQty: last_deliberation.approved_qty ?? 0,
      signal: last_deliberation.signal || 'HOLD',
      vetoAgents,
      isDegraded,
    });

    // Apply live Darwinian weights to the weight field so the Situation Room
    // shows real performance-adjusted multipliers next to each agent card.
    if (darwinianWeights && typeof darwinianWeights === 'object') {
      const darwinMap: Record<string, AgentId> = {
        sentiment: 'sentiment_analyst',
        macro: 'macro_analyst',
        earnings: 'earnings_analyst',
        technical: 'technical_analyst',
      };
      setAgents(prev => prev.map(a => {
        const backendKey = Object.keys(darwinMap).find(k => darwinMap[k] === a.id);
        if (backendKey && darwinianWeights[backendKey] != null) {
          const effectiveWeight = (AGENT_WEIGHTS[a.id] ?? 1.0) * darwinianWeights[backendKey];
          return { ...a, weight: Math.round(effectiveWeight * 100) / 100 };
        }
        return a;
      }));
    }

    setCycleCount(c => c + 1);
    setLastSignal(
      last_deliberation.reasoning ||
      `Processing ${symbol} — quorum: ${quorumLabel} (score: ${quorumScore.toFixed(3)})`
    );

    const votes = last_deliberation.votes || [];
    
    setAgents(prev => prev.map(a => {
      // Find the corresponding vote for this agent
      const backendAgentKey = Object.keys(agentMap).find(k => agentMap[k] === a.id);
      const vote = votes.find((v: any) => v.agent === backendAgentKey);

      if (vote) {
        const isVeto = vote.vote === 'VETO';
        const isScanning = last_deliberation.signal === 'HOLD';
        const newText = vote.reasoning || 'No reasoning provided.';
        const lastText = a.thoughts.length > 0 ? a.thoughts[a.thoughts.length - 1].text : '';
        const updatedThoughts = newText !== lastText
          ? [
              ...a.thoughts.slice(-(MAX_THOUGHTS_PER_AGENT - 1)),
              { id: `${Date.now()}`, timestamp: timestamp(), text: newText }
            ]
          : a.thoughts;

        return {
          ...a,
          status: isVeto ? 'vetoed' as const : (isScanning ? 'processing' as const : 'approved' as const),
          progress: isScanning ? Math.round(50 + Math.random() * 40) : 100,
          thoughts: updatedThoughts,
          metric: `${Math.round(vote.confidence * 100)}%`,
          metricLabel: isScanning ? 'Activity' : 'Confidence',
          weight: vote.weight ?? AGENT_WEIGHTS[a.id as AgentId],
        };
      }

      // Special handling for executioner (no backend voting agent)
      if (a.id === 'executioner') {
        const approved = isApproved;
        const vetoed = hasVeto;
        const isScanning = last_deliberation.signal === 'HOLD';
        const newText = isScanning
          ? `Standing by — agents scanning ${symbol || 'market'}. No trade signal.`
          : (approved
            ? `Order filled: ${last_deliberation.signal} × ${last_deliberation.approved_qty ?? '?'} (${last_deliberation.order_urgency ?? 'LOW'} urgency)`
            : (vetoed
              ? `Execution halted — VETO by: ${vetoAgents.join(', ')}`
              : 'Awaiting quorum confirmation.'));
        const lastText = a.thoughts.length > 0 ? a.thoughts[a.thoughts.length - 1].text : '';
        const updatedThoughts = newText !== lastText
          ? [
              ...a.thoughts.slice(-(MAX_THOUGHTS_PER_AGENT - 1)),
              { id: `${Date.now()}`, timestamp: timestamp(), text: newText }
            ]
          : a.thoughts;

        return {
          ...a,
          status: vetoed ? 'vetoed' as const : (isScanning ? 'processing' as const : (approved ? 'approved' as const : 'idle' as const)),
          progress: isScanning ? 50 : 100,
          metric: approved ? 'FILLED' : (vetoed ? 'REJECTED' : (isScanning ? 'SCANNING' : 'STANDBY')),
          metricLabel: 'Status',
          thoughts: updatedThoughts
        };
      }

      return a;
    }));

    // Update flow animation — use correct field names (Gap 1 fix)
    const isFlowing = isApproved && !hasVeto;
    setFlow({
      activeStep: isFlowing ? 6 : (isDegraded ? -2 : 0),
      tokenPosition: isFlowing ? 6 : -1,
      isFlowing: isFlowing
    });
  }, [processDeliberationEvent]);

  const connect = useCallback(() => {
    if (!botId || !enabled) return;
    
    // Derive from centralized env config
    const url = getWsUrl(`/ws/bot/${botId}`);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log(`[WS] Connected to bot ${botId}`);
      setLastSignal(`Connected to live stream for bot: ${botId}`);
      backoffRef.current = INITIAL_RECONNECT_MS;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        processUpdate(data);
      } catch (err) {
        console.error('[WS] Error parsing message:', err);
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (mounted.current && enabled) {
        console.log(`[WS] Disconnected. Reconnecting in ${backoffRef.current}ms...`);
        setTimeout(connect, backoffRef.current);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_RECONNECT_MS);
      }
    };

    ws.onerror = (err) => {
      console.error('[WS] Connection error:', err);
    };
  }, [botId, processUpdate, enabled]);

  useEffect(() => {
    mounted.current = true;

    if (enabled && botId) {
      backoffRef.current = INITIAL_RECONNECT_MS;
      connect();
    } else {
      cleanup();
    }

    // Keepalive ping
    const pingId = enabled
      ? setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send('ping');
          }
        }, 10000)
      : null;

    return () => {
      mounted.current = false;
      cleanup();
      if (pingId) clearInterval(pingId);
    };
  }, [connect, enabled, botId, cleanup]);

  return { agents, flow, cycleCount, lastSignal, enabledAgents, deliberation };
}
