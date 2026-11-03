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
  startSingleBot: async (demoMode?: boolean) => {
    const { data } = await api.post('/start', { demo_mode: demoMode ?? false });
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
    const { data } = await api.post(`/fleet/bot/${botId}/start`, {});
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
  getAccountInfo: async (): Promise<MT5AccountInfo> => {
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
  getAvailableSymbols: async (): Promise<{ symbols: AvailableSymbol[] }> => {
    const { data } = await api.get('/market/symbols/available');
    return data;
  },
};

export interface AvailableSymbol {
  name: string;
  broker_symbol: string;
  category: string;
  path: string;
  description: string;
  digits: number;
  spread: number;
  trade_mode: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
}

// ── Types ───────────────────────────────────────────────
export interface MT5AccountInfo {
  equity: number;
  portfolio_value: number;
  buying_power: number;
  daytrading_buying_power: number;
  regt_buying_power: number;
  cash: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  daily_realized?: number;       // today's closed-deal P&L from MT5 (incl. manual)
  daily_unrealized?: number;     // current floating P&L
  daily_pnl_source?: string;     // "mt5_history" | "mt5_history_utc" | "floating_only"
  unrealized_pnl: number;
  margin_used: number;
  margin_free: number;
  currency: string;
  status: string;
  message?: string;
  timestamp: string;
}

export interface BotDeployRequest {
  bot_id?: string;
  account_id: string;
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
  short_selling_enabled: boolean;
  stop_loss_pct: number;
  max_daily_drawdown_pct: number;
  bb_period: number;
  bb_std_dev: number;
  ai_brain_enabled: boolean;
  ai_interval_minutes: number;
  ai_min_trades_trigger?: number;
  ai_loss_streak_trigger?: number;
  sub_agents: string[];
  sub_agent_interval_minutes?: number;
  agent_vote_cache_ttl_seconds?: number;
  tags: string[];
  fib_enabled: boolean;
  fib_lookback_bars?: number;
  fib_bounce_threshold_pct?: number;
  fib_entry_mode?: string;
  fib_active_levels_raw?: string;
  smart_routing_min_qty?: number;
  twap_interval_ms?: number;
  max_slippage_pct?: number;
  limit_timeout_s?: number;
  auto_start: boolean;
  leverage_mode_enabled?: boolean;
  leverage_factor?: number;
  isolated_risk_usd?: number;
  net_profit_target_usd?: number;
  take_profit_usd?: number;
  // Anti-fakeout filter
  fakeout_filter_enabled?: boolean;
  fakeout_atr_buffer_mult?: number;
  fakeout_wick_reject_ratio?: number;
  fakeout_swing_lookback?: number;
  // Advanced profit retrace (per-ticket profit ratchet)
  profit_retrace_enabled?: boolean;
  profit_retrace_arm_usd?: number;
  profit_retrace_giveback_pct?: number;
  profit_retrace_tighten_usd?: number;
  profit_retrace_tight_giveback_pct?: number;
  profit_retrace_min_lock_usd?: number;
  profit_retrace_atr_adaptive?: boolean;
  // Boost position (trend-confirmation runner)
  boost_enabled?: boolean;
  boost_lot?: number;
  boost_trigger_slots?: number;
  boost_max_loss_usd?: number;
  boost_arm_usd?: number;
  boost_giveback_pct?: number;
  boost_mtf_exit_enabled?: boolean;
  boost_mtf_min_flip?: number;
  boost_mtf_refresh_secs?: number;
  // Trading psychology (open-position discipline)
  psychology_enabled?: boolean;
  block_average_down?: boolean;
  max_loser_hold_secs?: number;
  max_position_hold_secs?: number;
  max_adverse_excursion_usd?: number;
  tilt_loss_streak?: number;
  tilt_cooldown_secs?: number;
  overconfidence_win_streak?: number;
  rolling_giveback_pct?: number;
  rolling_trade_window_secs?: number;
  max_trades_per_window?: number;
  psych_review_enabled?: boolean;
  psych_review_interval_secs?: number;
  psych_review_adverse_usd?: number;
}

export interface BotPsychologyPosition {
  ticket: number;
  side: string;
  mae_usd: number;
  peak_net: number;
  exit_thesis: string;
  ticks_held: number;
  rationale?: string;
}

export interface BotPsychology {
  enabled: boolean;
  composure_state: string;       // CALM | FEARFUL | OVERCONFIDENT | FATIGUED | TILTED
  discipline_score: number;      // 0–100
  loss_streak: number;
  win_streak: number;
  tilt_lockout_remaining: number;
  entries_halted: boolean;
  session_entries: number;
  positions: BotPsychologyPosition[];
}


export interface FleetConfig {
  max_bots: number;
  global_risk_enabled: boolean;
  max_fleet_drawdown_pct: number;
  sub_agents_enabled: boolean;
  auto_redeploy: boolean;
  log_retention_days: number;
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
  kill_zone_enabled: boolean;
  leverage_mode_enabled?: boolean;
  leverage_factor?: number;
  isolated_risk_usd?: number;
  net_profit_target_usd?: number;
  take_profit_usd?: number;
  // Defensive systems (anti-fakeout + profit retrace)
  fakeout_filter_enabled?: boolean;
  profit_retrace_enabled?: boolean;
  profit_retrace_arm_usd?: number;
  profit_retrace_giveback_pct?: number;
  // Boost position
  boost_enabled?: boolean;
  boost_lot?: number;
  boost_max_loss_usd?: number;
  boost_active?: boolean;
  // Trading psychology — editable discipline rails
  psychology_enabled?: boolean;
  block_average_down?: boolean;
  rolling_giveback_pct?: number;
  tilt_cooldown_secs?: number;
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
    psychology?: BotPsychology;
  };
  vitals: {
    survival_state: string;
    apex_state: string;
    profit_pct: number;
    drawdown_pct: number;
    composure_state?: string;
    discipline_score?: number;
    loss_streak?: number;
    win_streak?: number;
    tilt_lockout_remaining?: number;
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

/* ──────────────────────────────────────────────────────────
 * Setup Wizard API
 * ────────────────────────────────────────────────────────── */

export interface SetupStatus {
  setup_complete: boolean;
  has_database: boolean;
  has_accounts: boolean;
  has_api_keys: boolean;
  account_count: number;
}

export interface MT5Account {
  id: string;
  label: string;
  mt5_login: number;
  mt5_server: string;
  is_default: boolean;
  created_at: string;
}

export interface MT5Symbol {
  name: string;
  broker_symbol: string;
  category: string;
  path: string;
  description: string;
  digits: number;
  spread: number;
  trade_mode: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
}

export const setupApi = {
  getStatus: () =>
    api.get<SetupStatus>('/setup/status').then(r => r.data),

  testDatabase: (url: string) =>
    api.post<{ connected: boolean; message: string }>('/setup/database/test', { url }).then(r => r.data),

  saveDatabase: (url: string) =>
    api.post('/setup/database', { url }).then(r => r.data),

  getApiKeys: () =>
    api.get('/setup/api-keys').then(r => r.data),

  saveApiKeys: (keys: { gemini_api_key?: string; gemini_model?: string; alpaca_news_api_key?: string }) =>
    api.post('/setup/api-keys', keys).then(r => r.data),

  completeSetup: () =>
    api.post('/setup/complete').then(r => r.data),

  getConfig: () =>
    api.get('/setup/config').then(r => r.data),
};

export const accountsApi = {
  list: () =>
    api.get<{ accounts: MT5Account[]; count: number }>('/accounts').then(r => r.data),

  add: (account: {
    label: string;
    mt5_login: number;
    mt5_password: string;
    mt5_server: string;
    is_default?: boolean;
  }) => api.post('/accounts', account).then(r => r.data),

  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/accounts/${id}`, data).then(r => r.data),

  remove: (id: string) =>
    api.delete(`/accounts/${id}`).then(r => r.data),

  test: (id: string) =>
    api.post(`/accounts/${id}/test`).then(r => r.data),

  testNew: (creds: { mt5_login: number; mt5_password: string; mt5_server: string }) =>
    api.post('/accounts/test', creds).then(r => r.data),

  getSymbols: (id: string) =>
    api.get<{ account_id: string; symbols: MT5Symbol[]; count: number }>(`/accounts/${id}/symbols`).then(r => r.data),
};
