import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** Derive a WebSocket URL from the API base (http→ws, https→wss). */
export function getWsUrl(path: string): string {
  const base = API_BASE_URL.replace(/^http/, 'ws');
  return `${base}${path}`;
}

export { API_BASE_URL };

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const tradingApi = {
  getStatus: async () => {
    const { data } = await api.get('/status');
    return data;
  },
  getHistory: async () => {
    const { data } = await api.get('/history');
    return data;
  },
  startSingleBot: async (demoMode: boolean) => {
    const { data } = await api.post('/start', { demo_mode: demoMode });
    return data;
  },
  stopSingleBot: async () => {
    const { data } = await api.post('/stop');
    return data;
  },
  updateConfig: async (config: any) => {
    const { data } = await api.post('/config', config);
    return data;
  },
  getAIStatus: async () => {
    const { data } = await api.get('/ai/status');
    return data;
  },
  triggerAI: async () => {
    const { data } = await api.post('/ai/trigger');
    return data;
  },
  getAIDecisions: async (limit: number = 50) => {
    const { data } = await api.get(`/ai/decisions?limit=${limit}`);
    return data;
  },
  getVitalStatus: async () => {
    const { data } = await api.get('/vital/status');
    return data;
  },
  getVitalEvents: async () => {
    const { data } = await api.get('/vital/events');
    return data;
  },

  // ── Fleet ──────────────────────────────────────────────
  getFleetStatus: async (): Promise<FleetStatus> => {
    const { data } = await api.get('/fleet/status');
    return data;
  },
  deployBot: async (config: BotDeployRequest) => {
    const { data } = await api.post('/fleet/deploy', config);
    return data;
  },
  killBot: async (botId: string) => {
    const { data } = await api.delete(`/fleet/bot/${botId}`);
    return data;
  },
  startBot: async (botId: string) => {
    const { data } = await api.post(`/fleet/bot/${botId}/start`);
    return data;
  },
  stopBotEngine: async (botId: string) => {
    const { data } = await api.post(`/fleet/bot/${botId}/stop`);
    return data;
  },
  getBotStatus: async (botId: string) => {
    const { data } = await api.get(`/fleet/bot/${botId}`);
    return data;
  },
  triggerBotAI: async (botId: string) => {
    const { data } = await api.post(`/fleet/bot/${botId}/ai/trigger`);
    return data;
  },
  getFleetConfig: async () => {
    const { data } = await api.get('/fleet/config');
    return data;
  },
  updateFleetConfig: async (config: Partial<FleetConfig>) => {
    const { data } = await api.post('/fleet/config', config);
    return data;
  },
  getFleetBotHistory: async (botId: string) => {
    const { data } = await api.get(`/fleet/bot/${botId}/history`);
    return data;
  },
  getFleetBotAIStatus: async (botId: string) => {
    const { data } = await api.get(`/fleet/bot/${botId}/ai/status`);
    return data;
  },
  getFleetBotAIDecisions: async (botId: string, limit = 20) => {
    const { data } = await api.get(`/fleet/bot/${botId}/ai/decisions?limit=${limit}`);
    return data;
  },
  updateBotConfig: async (botId: string, updates: Record<string, unknown>) => {
    const { data } = await api.patch(`/fleet/bot/${botId}/config`, updates);
    return data;
  },

  wizardGenerate: async (req: WizardGenerateRequest): Promise<WizardResult> => {
    const { data } = await api.post('/fleet/wizard/generate', req);
    return data;
  },
  getAccountInfo: async (): Promise<AlpacaAccount> => {
    const { data } = await api.get('/fleet/account');
    return data;
  },
  getMarketData: async (symbol: string): Promise<MarketDataResponse> => {
    const { data } = await api.get(`/market/data/${symbol}`);
    return data;
  },
  getSystemResources: async (): Promise<SystemResources> => {
    const { data } = await api.get('/system/resources');
    return data;
  },
};

// ── Types ───────────────────────────────────────────────
export interface AlpacaAccount {
  equity: number;
  portfolio_value: number;
  buying_power: number;
  daytrading_buying_power: number;
  regt_buying_power: number;
  cash: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  currency: string;
  status: string;
}

export interface BotDeployRequest {
  bot_id?: string;
  name: string;
  description?: string;
  personality?: string;
  animal?: string;
  category?: string;
  ai_generated?: boolean;
  symbol: string;
  strategy: string;
  capital_allocation: number;
  qty: number;
  stop_loss_pct: number;
  bb_period: number;
  bb_std_dev: number;
  ai_brain_enabled: boolean;
  ai_interval_minutes: number;
  sub_agents: string[];
  tags: string[];
  fib_enabled: boolean;
  auto_start: boolean;
  demo_mode: boolean;
}

export interface FleetConfig {
  max_bots: number;
  global_risk_enabled: boolean;
  max_fleet_drawdown_pct: number;
  sub_agents_enabled: boolean;
  auto_redeploy: boolean;
  log_retention_days: number;
  global_demo_mode?: boolean;
}

export interface BotSnapshot {
  bot_id: string;
  name: string;
  description?: string;
  personality?: string;
  animal?: string;
  category?: string;
  symbol: string;
  strategy: string;
  capital_allocation: number;
  tags: string[];
  created_at: string;
  demo_mode: boolean;
  status: {
    bot_status: string;
    current_price: number;
    position_qty: number;
    position_side: string;
    entry_price: number;
    equity: number;
    daily_pnl: number;
    unrealized_pnl: number;
    starting_equity: number;
  };
  vitals: {
    survival_state: string;
    apex_state: string;
    profit_pct: number;
    drawdown_pct: number;
  };
  ai: {
    enabled: boolean;
    total_cycles: number;
    last_trigger: string | null;
    last_run_at: string | null;
  };
  agent_sentiment: {
    score: number;
    confidence: number;
  };
}

export interface FleetStatus {
  fleet_config: FleetConfig;
  summary: {
    total_bots: number;
    running_bots: number;
    max_bots: number;
    total_daily_pnl: number;
    total_equity: number;
    timestamp: string;
  };
  bots: BotSnapshot[];
}

export interface WizardGenerateRequest {
  symbol: string;
  category: string;
  personality: string;
}

export interface WizardResult {
  name: string;
  description: string;
  personality: string;
  animal: string;
  symbol: string;
  category: string;
  config: Record<string, any>;
  ai_generated: boolean;
}

export interface MarketDataResponse {
  symbol: string;
  price_data: any[];
  bollinger: any[];
}

export interface SystemResources {
  cpu: {
    percent: number;
    count: number;
    per_core: number[];
  };
  ram: {
    total_mb: number;
    used_mb: number;
    available_mb: number;
    percent: number;
  };
  swap: {
    total_mb: number;
    used_mb: number;
    percent: number;
  };
  process: {
    rss_mb: number;
    vms_mb: number;
    cpu_pct: number;
    pid: number;
  };
  timestamp: string;
  error?: string;
}
