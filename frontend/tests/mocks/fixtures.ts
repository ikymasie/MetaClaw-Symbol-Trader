import type {
  FleetStatus,
  FleetConfig,
  BotSnapshot,
  MT5AccountInfo,
  MarketDataResponse,
  SetupStatus,
  MT5Account,
  WizardResult,
  WizardGenerateRequest,
  SystemResources,
} from '@/lib/api';

// ── Fleet Config ──────────────────────────────────────────
export const mockFleetConfig: FleetConfig = {
  max_bots: 10,
  global_risk_enabled: true,
  max_fleet_drawdown_pct: 25,
  sub_agents_enabled: true,
  auto_redeploy: false,
  log_retention_days: 30,
};

// ── MT5 Account Info ──────────────────────────────────────
export const mockMT5Account: MT5AccountInfo = {
  equity: 125000,
  portfolio_value: 125000,
  buying_power: 250000,
  daytrading_buying_power: 500000,
  regt_buying_power: 250000,
  cash: 98000,
  daily_pnl: 1240.5,
  daily_pnl_pct: 1.02,
  unrealized_pnl: 520.3,
  margin_used: 27000,
  margin_free: 98000,
  currency: 'USD',
  status: 'CONNECTED',
  message: 'MT5 terminal active',
  timestamp: new Date().toISOString(),
};

// ── Bot Snapshots ─────────────────────────────────────────
export function botSnapshot(overrides: Partial<BotSnapshot> = {}): BotSnapshot {
  return {
    bot_id: 'bot-001',
    name: 'BTC Hunter',
    description: 'Hunting BTCUSD reversals with mean reversion strategy',
    personality: 'elephant',
    animal: 'Elephant',
    category: 'Crypto',
    symbol: 'BTCUSD',
    strategy: 'mean_reversion',
    capital_allocation: 10000,
    tags: ['crypto', 'conservative'],
    created_at: '2025-01-15T10:00:00Z',
    kill_zone_enabled: false,
    leverage_mode_enabled: false,
    status: {
      bot_status: 'RUNNING',
      current_price: 68400,
      position_qty: 0.12,
      position_side: 'BUY',
      entry_price: 68150,
      equity: 10250,
      daily_pnl: 250.0,
      unrealized_pnl: 30.0,
      starting_equity: 10000,
    },
    vitals: {
      survival_state: 'HEALTHY',
      apex_state: 'HUNTING',
      profit_pct: 2.5,
      drawdown_pct: 0.8,
    },
    ai: {
      enabled: true,
      total_cycles: 48,
      last_trigger: new Date().toISOString(),
      last_run_at: new Date().toISOString(),
    },
    agent_sentiment: {
      score: 0.72,
      confidence: 0.85,
    },
    ...overrides,
  };
}

export function createBots(count: number): BotSnapshot[] {
  const statuses = ['RUNNING', 'RUNNING', 'STOPPED', 'PAUSED'];
  const symbols = [
    { sym: 'BTCUSD', cat: 'Crypto', name: 'BTC' },
    { sym: 'ETHUSD', cat: 'Crypto', name: 'ETH' },
    { sym: 'EURUSD', cat: 'Forex Majors', name: 'EUR' },
    { sym: 'GBPUSD', cat: 'Forex Majors', name: 'GBP' },
    { sym: 'XAUUSD', cat: 'Commodities', name: 'GOLD' },
    { sym: 'SPX500', cat: 'Indices', name: 'SPX' },
    { sym: 'US30', cat: 'Indices', name: 'DOW' },
  ];
  const animals = ['Elephant', 'Buffalo', 'Rhino', 'Leopard', 'Lion'];
  const personalities = ['elephant', 'buffalo', 'rhino', 'leopard', 'lion'];
  const strategies = ['mean_reversion', 'combined', 'trend_following'];
  const survivalStates = ['HEALTHY', 'HEALTHY', 'HEALTHY', 'WOUNDED', 'DORMANT'];

  return Array.from({ length: count }, (_, i) => {
    const sym = symbols[i % symbols.length];
    const status = statuses[i % statuses.length];
    const botStatus = status;
    const isRunning = botStatus === 'RUNNING';
    return botSnapshot({
      bot_id: `bot-${String(i + 1).padStart(3, '0')}`,
      name: `${sym.name} ${animals[i % animals.length]}`,
      symbol: sym.sym,
      category: sym.cat,
      personality: personalities[i % personalities.length],
      animal: animals[i % animals.length],
      strategy: strategies[i % strategies.length],
      capital_allocation: 5000 + i * 2500,
      status: {
        bot_status: botStatus,
        current_price: isRunning ? 1000 + i * 120 : 0,
        position_qty: isRunning ? 0.1 + i * 0.05 : 0,
        position_side: i % 2 === 0 ? 'BUY' : 'SELL',
        entry_price: isRunning ? 980 + i * 120 : 0,
        equity: isRunning ? 5500 + i * 2500 : 5000 + i * 2500,
        daily_pnl: isRunning ? (i % 3 === 0 ? -50 : 120 + i * 15) : 0,
        unrealized_pnl: isRunning ? (i % 2 === 0 ? 30 : -15) : 0,
        starting_equity: 5000 + i * 2500,
      },
      vitals: {
        survival_state: survivalStates[i % survivalStates.length],
        apex_state: isRunning ? 'HUNTING' : 'DORMANT',
        profit_pct: isRunning ? 3 + i * 1.2 : 0,
        drawdown_pct: i % 5 === 0 ? 5.2 : 1.5,
      },
      ai: {
        enabled: true,
        total_cycles: 20 + i * 5,
        last_trigger: new Date().toISOString(),
        last_run_at: new Date().toISOString(),
      },
      agent_sentiment: {
        score: 0.5 + i * 0.06,
        confidence: 0.7 + i * 0.03,
      },
    });
  });
}

// ── Fleet Status ──────────────────────────────────────────
export function mockFleetStatus(botCount = 5): FleetStatus {
  const bots = createBots(botCount);
  const running = bots.filter((b) => b.status?.bot_status === 'RUNNING').length;
  return {
    fleet_config: mockFleetConfig,
    summary: {
      total_bots: botCount,
      running_bots: running,
      max_bots: mockFleetConfig.max_bots,
      total_daily_pnl: bots.reduce((s, b) => s + (b.status?.daily_pnl ?? 0), 0),
      total_equity: bots.reduce((s, b) => s + (b.status?.equity ?? 0), 0),
      timestamp: new Date().toISOString(),
    },
    bots,
  };
}

// ── Market Data ───────────────────────────────────────────
export function mockMarketData(
  symbol = 'BTCUSD',
  count = 200
): MarketDataResponse {
  let price = symbol === 'BTCUSD' ? 68000 : 4500;
  const priceData: Record<string, number>[] = [];
  const bollinger: Record<string, number>[] = [];
  for (let i = 0; i < count; i++) {
    const change = (Math.random() - 0.48) * 200;
    price += change;
    const time = Date.now() - (count - i) * 60000;
    priceData.push({
      time: time / 1000,
      open: price - change * 0.3,
      high: price + Math.abs(change) * 1.5,
      low: price - Math.abs(change) * 1.2,
      close: price,
      volume: Math.floor(Math.random() * 5000) + 1000,
    });
    bollinger.push({
      time: time / 1000,
      upper: price + Math.abs(change) * 2.5,
      middle: price,
      lower: price - Math.abs(change) * 2,
    });
  }
  return { symbol, price_data: priceData, bollinger };
}

// ── Setup ─────────────────────────────────────────────────
export const mockSetupStatus: SetupStatus = {
  setup_complete: false,
  has_database: false,
  has_accounts: false,
  has_api_keys: false,
  account_count: 0,
};

export const mockCompleteSetupStatus: SetupStatus = {
  setup_complete: true,
  has_database: true,
  has_accounts: true,
  has_api_keys: true,
  account_count: 2,
};

export const mockMT5Accounts: MT5Account[] = [
  {
    id: 'acct-1',
    label: 'Demo Broker',
    mt5_login: 12345678,
    mt5_server: 'MetaQuotes-Demo',
    is_default: true,
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 'acct-2',
    label: 'Live Broker',
    mt5_login: 87654321,
    mt5_server: 'ICMarkets-Demo',
    is_default: false,
    created_at: '2025-01-10T00:00:00Z',
  },
];

export const mockDbTestSuccess = { connected: true, message: 'Connected to PostgreSQL successfully' };
export const mockDbTestFail = { connected: false, message: 'Connection refused' };

// ── Wizard ────────────────────────────────────────────────
export function mockWizardResult(request: WizardGenerateRequest): WizardResult {
  return {
    name: `${request.symbol} ${request.personality.charAt(0).toUpperCase() + request.personality.slice(1)}`,
    description: `An AI-crafted ${request.personality} bot for ${request.symbol} trading with optimized parameters.`,
    personality: request.personality,
    animal: request.personality,
    symbol: request.symbol,
    category: request.category,
    ai_generated: true,
    config: {
      symbol: request.symbol,
      strategy: 'mean_reversion',
      capital_allocation: 10000,
      qty: 0.01,
      stop_loss_pct: 1.5,
      max_daily_drawdown_pct: 5,
      bb_period: 20,
      bb_std_dev: 2,
      ai_brain_enabled: true,
      ai_interval_minutes: 15,
      sub_agents: ['trend_scout', 'fib_sniper', 'risk_warden', 'momentum_rider'],
      fib_enabled: true,
      leverage_mode_enabled: false,
      leverage_factor: 20,
      isolated_risk_usd: 40,
      net_profit_target_usd: 1,
      take_profit_usd: 1,
      short_selling_enabled: true,
      auto_start: true,
      tags: ['ai-generated', request.personality],
    },
  };
}

// ── Available Symbols ─────────────────────────────────────
export const mockAvailableSymbols = {
  symbols: [
    { name: 'BTCUSD', broker_symbol: 'BTCUSD', category: 'Crypto', path: 'BTCUSD', description: 'Bitcoin vs US Dollar', digits: 2, spread: 10, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'ETHUSD', broker_symbol: 'ETHUSD', category: 'Crypto', path: 'ETHUSD', description: 'Ethereum vs US Dollar', digits: 2, spread: 8, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'EURUSD', broker_symbol: 'EURUSD', category: 'Forex Majors', path: 'EURUSD', description: 'Euro vs US Dollar', digits: 5, spread: 3, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'GBPUSD', broker_symbol: 'GBPUSD', category: 'Forex Majors', path: 'GBPUSD', description: 'British Pound vs US Dollar', digits: 5, spread: 4, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'USDJPY', broker_symbol: 'USDJPY', category: 'Forex Majors', path: 'USDJPY', description: 'US Dollar vs Japanese Yen', digits: 3, spread: 2, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'XAUUSD', broker_symbol: 'XAUUSD', category: 'Metals', path: 'XAUUSD', description: 'Gold vs US Dollar', digits: 2, spread: 15, trade_mode: 0, volume_min: 0.01, volume_max: 100, volume_step: 0.01 },
    { name: 'SPX500', broker_symbol: 'SPX500', category: 'Indices', path: 'SPX500', description: 'S&P 500 Index', digits: 2, spread: 5, trade_mode: 0, volume_min: 0.1, volume_max: 100, volume_step: 0.1 },
    { name: 'US30', broker_symbol: 'US30', category: 'Indices', path: 'US30', description: 'Dow Jones 30', digits: 2, spread: 5, trade_mode: 0, volume_min: 0.1, volume_max: 100, volume_step: 0.1 },
    { name: 'BRENT', broker_symbol: 'BRENT', category: 'Energies', path: 'BRENT', description: 'Brent Crude Oil', digits: 2, spread: 8, trade_mode: 0, volume_min: 0.1, volume_max: 100, volume_step: 0.1 },
  ],
};

export const mockAccountSymbols = {
  account_id: 'acct-1',
  symbols: mockAvailableSymbols.symbols,
  count: mockAvailableSymbols.symbols.length,
};

// ── System Resources ──────────────────────────────────────
export const mockSystemResources: SystemResources = {
  cpu: { percent: 23.5, count: 8, per_core: [30, 20, 15, 25, 28, 18, 22, 24] },
  ram: { total_mb: 16384, used_mb: 8192, available_mb: 8192, percent: 50 },
  swap: { total_mb: 4096, used_mb: 512, percent: 12.5 },
  process: { rss_mb: 512, vms_mb: 1024, cpu_pct: 5.2, pid: 12345 },
  timestamp: new Date().toISOString(),
};

// ── Deploy result ─────────────────────────────────────────
export const mockDeployResult = { bot_id: 'bot-new-001', message: 'Bot deployed successfully' };
