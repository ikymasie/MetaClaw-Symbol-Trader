-- TradeClaw PostgreSQL Schema (Neon Optimized)
-- Enforces strict FKs and uses time-series partitioning patterns.
-- All data is stored in PostgreSQL; Firestore is no longer used.

-- 1. EXTENSIONS
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. USERS
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. BOTS
CREATE TABLE IF NOT EXISTS bots (
    bot_id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT DEFAULT 'stopped',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. BOT CONFIGS
CREATE TABLE IF NOT EXISTS bot_configs (
    bot_id TEXT PRIMARY KEY REFERENCES bots(bot_id) ON DELETE CASCADE,
    config JSONB NOT NULL,
    saved_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. FLEET CONFIGS
CREATE TABLE IF NOT EXISTS fleet_configs (
    uid TEXT PRIMARY KEY REFERENCES users(uid) ON DELETE CASCADE,
    config JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. TRADES
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    ticket BIGINT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    volume FLOAT NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    pnl FLOAT,
    swap FLOAT DEFAULT 0,
    commission FLOAT DEFAULT 0,
    magic BIGINT,
    comment TEXT,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    saved_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trades_bot_id ON trades(bot_id);
CREATE INDEX idx_trades_entry_time ON trades(entry_time DESC);

-- 7. EQUITY HISTORY (Partitioned)
CREATE TABLE IF NOT EXISTS equity_history (
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    balance FLOAT NOT NULL,
    equity FLOAT NOT NULL,
    margin_level FLOAT,
    open_positions INT DEFAULT 0
) PARTITION BY RANGE (timestamp);
CREATE INDEX idx_equity_history_bot_ts ON equity_history(bot_id, timestamp DESC);


-- 8. TELEMETRY (Partitioned - High Frequency)
CREATE TABLE IF NOT EXISTS telemetry (
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    state JSONB NOT NULL
) PARTITION BY RANGE (timestamp);
CREATE INDEX idx_telemetry_bot_ts ON telemetry(bot_id, timestamp DESC);
CREATE INDEX idx_telemetry_ts ON telemetry(timestamp DESC);


-- 9. MARKET BARS (Partitioned)
CREATE TABLE IF NOT EXISTS market_bars (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    "open" FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    "close" FLOAT NOT NULL,
    volume BIGINT,
    PRIMARY KEY (symbol, timeframe, timestamp)
) PARTITION BY RANGE (timestamp);

-- 10. AGENT RECOMMENDATIONS
CREATE TABLE IF NOT EXISTS agent_recommendations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    signal_price FLOAT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    forward_return_1d FLOAT,
    forward_return_5d FLOAT,
    scored BOOLEAN DEFAULT FALSE,
    saved_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agent_rec_lookup ON agent_recommendations(bot_id, agent_name, timestamp DESC);

-- 11. AGENT SIGNALS SNAPSHOTS
CREATE TABLE IF NOT EXISTS agent_signals (
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    signals JSONB NOT NULL
) PARTITION BY RANGE (timestamp);
CREATE INDEX idx_agent_signals_bot_ts ON agent_signals(bot_id, timestamp DESC);


-- 12. STRATEGY CONTEXTS (RAG Memory)
CREATE TABLE IF NOT EXISTS strategy_contexts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    context JSONB NOT NULL,
    embedding_text TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_strat_context_lookup ON strategy_contexts(bot_id, timestamp DESC);

-- 13. BOT STATE (Key-Value)
CREATE TABLE IF NOT EXISTS bot_state_kv (
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (bot_id, key)
);

-- 14. LIVE TELEMETRY (Latest snapshot only)
CREATE TABLE IF NOT EXISTS live_telemetry (
    id TEXT PRIMARY KEY, -- 'fleet' or bot_id
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 15. MARKET TRENDS
CREATE TABLE IF NOT EXISTS market_trends (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    trend_data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, timeframe)
);

-- 16. BOT LOGS (Partitioned)
CREATE TABLE IF NOT EXISTS bot_logs (
    bot_id TEXT REFERENCES bots(bot_id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (timestamp);
CREATE INDEX idx_bot_logs_bot_ts ON bot_logs(bot_id, timestamp DESC);

-- 17. FLEET EVENTS (System-wide events)
CREATE TABLE IF NOT EXISTS fleet_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_fleet_events_ts ON fleet_events(timestamp DESC);

-- 18. AUDIT LOGS (Security and critical state changes)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uid TEXT REFERENCES users(uid),
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    resource_id TEXT,
    metadata JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_logs_ts ON audit_logs(timestamp DESC);

-- 19. SYSTEM METRICS (Partitioned)
CREATE TABLE IF NOT EXISTS system_metrics (
    metric_name TEXT NOT NULL,
    value FLOAT NOT NULL,
    metadata JSONB,
    timestamp TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (timestamp);
CREATE INDEX idx_sys_metrics_ts ON system_metrics(timestamp DESC);

-- 14. DEFAULT PARTITIONS (Required for range partitioning)
CREATE TABLE IF NOT EXISTS equity_history_default PARTITION OF equity_history DEFAULT;
CREATE TABLE IF NOT EXISTS telemetry_default PARTITION OF telemetry DEFAULT;
CREATE TABLE IF NOT EXISTS market_bars_default PARTITION OF market_bars DEFAULT;
CREATE TABLE IF NOT EXISTS agent_signals_default PARTITION OF agent_signals DEFAULT;
CREATE TABLE IF NOT EXISTS bot_logs_default PARTITION OF bot_logs DEFAULT;
CREATE TABLE IF NOT EXISTS system_metrics_default PARTITION OF system_metrics DEFAULT;

-- 20. BOT PERFORMANCE SNAPSHOTS (Aggregated daily)
CREATE TABLE IF NOT EXISTS bot_performance_snapshots (
    bot_id TEXT NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    pnl FLOAT NOT NULL,
    win_rate FLOAT,
    total_trades INT,
    sharpe FLOAT,
    max_drawdown FLOAT,
    equity TIMESTAMPTZ,
    PRIMARY KEY (bot_id, date)
);

-- 21. FLEET PERFORMANCE HISTORY
CREATE TABLE IF NOT EXISTS fleet_performance_history (
    date DATE PRIMARY KEY,
    total_equity FLOAT NOT NULL,
    total_pnl FLOAT NOT NULL,
    running_bots INT,
    saved_at TIMESTAMPTZ DEFAULT NOW()
);

-- 22. SYSTEM SETTINGS (Global Key-Value)
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 23. PROMPTS (Versioned AI Prompts)
CREATE TABLE IF NOT EXISTS prompts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    version INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_prompts_agent_version ON prompts(agent_name, version DESC);

-- 24. RESEARCH REPORTS (TradingAgents research framework cache)
-- One row per symbol; payload is the translated AgentSignal + raw context.
-- TTL governed by RESEARCH_CACHE_TTL config (default 4h) in research_bridge.py.
CREATE TABLE IF NOT EXISTS research_reports (
    symbol TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_reports_updated ON research_reports(updated_at DESC);

-- Initial Partitions for May/June 2026
CREATE TABLE IF NOT EXISTS equity_history_y2026m05 PARTITION OF equity_history 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS telemetry_y2026m05 PARTITION OF telemetry 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS market_bars_y2026m05 PARTITION OF market_bars 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS agent_signals_y2026m05 PARTITION OF agent_signals 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS bot_logs_y2026m05 PARTITION OF bot_logs 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS system_metrics_y2026m05 PARTITION OF system_metrics 
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
