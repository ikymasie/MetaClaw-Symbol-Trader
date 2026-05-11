"""
TradeClaw — PostgreSQL Persistence Layer
========================================
High-performance async persistence using asyncpg.
Features:
- Connection pooling for Neon.
- 10s AsyncBatcher for high-frequency data (telemetry, bars, logs).
- Strict relational mapping with Foreign Key enforcement.
- Time-series partitioning awareness.
- 48h data retention policy for raw telemetry.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, List, Dict
import asyncpg

logger = logging.getLogger("tradeclaw.postgres_store")

# ─────────────────────────────────────────────
# CONFIG & CONSTANTS
# ─────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")
BATCH_FLUSH_INTERVAL = 10.0  # seconds (User requested 10s buffer)
BATCH_SIZE_LIMIT = 50       # entries per batch

# ─────────────────────────────────────────────
# BATCHER
# ─────────────────────────────────────────────

class AsyncBatcher:
    """Buffers high-frequency writes and flushes them in batches."""
    def __init__(self, pool: asyncpg.Pool, table_name: str, columns: List[str], file_path: Optional[str] = None):
        self.pool = pool
        self.table_name = table_name
        self.columns = columns
        self.file_path = file_path
        self.buffer = []
        self._lock = asyncio.Lock()
        self._flush_task = None
        
        if self.file_path:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    async def add(self, *args):
        async with self._lock:
            self.buffer.append(args)
            if len(self.buffer) >= BATCH_SIZE_LIMIT:
                await self._perform_flush()
            elif self._flush_task is None:
                self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _periodic_flush(self):
        await asyncio.sleep(BATCH_FLUSH_INTERVAL)
        async with self._lock:
            if self.buffer:
                await self._perform_flush()
            self._flush_task = None

    async def flush(self):
        """Public flush method - ensures lock is acquired."""
        async with self._lock:
            await self._perform_flush()

    async def _perform_flush(self):
        """Internal flush method - assumes lock is ALREADY held."""
        if not self.buffer:
            return
        
        data = list(self.buffer)
        self.buffer = []
        
        # 1. Local File Write (if configured)
        if self.file_path:
            try:
                with open(self.file_path, "a", encoding="utf-8") as f:
                    for row in data:
                        # Format: TIMESTAMP | BOT_ID | LEVEL | MESSAGE
                        if self.table_name == "bot_logs":
                            # bot_logs order: ["bot_id", "level", "message", "timestamp"]
                            ts = row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3])
                            f.write(f"{ts} | {row[0]} | {row[1]} | {row[2]}\n")
                        else:
                            f.write(" | ".join(map(str, row)) + "\n")
                    f.flush() # Force write to disk
            except Exception as e:
                logger.error(f"Failed to write to local log file {self.file_path}: {e}")

        # 2. Database Write
        try:
            cols = ", ".join(self.columns)
            placeholders = ", ".join([f"${i+1}" for i in range(len(self.columns))])
            query = f"INSERT INTO {self.table_name} ({cols}) VALUES ({placeholders})"
            
            async with self.pool.acquire() as conn:
                await conn.executemany(query, data)
        except Exception as e:
            logger.error(f"Failed to flush batch to {self.table_name}: {e}")

# ─────────────────────────────────────────────
# POSTGRES STORE
# ─────────────────────────────────────────────

class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None
        self._user_id = os.getenv("METACLAW_USER_ID", "default_user")
        
        # Batchers
        self.telemetry_batcher: Optional[AsyncBatcher] = None
        self.bars_batcher: Optional[AsyncBatcher] = None
        self.equity_batcher: Optional[AsyncBatcher] = None
        self.logs_batcher: Optional[AsyncBatcher] = None
        self.metrics_batcher: Optional[AsyncBatcher] = None

    async def connect(self):
        if self.pool:
            return
        
        logger.info(f"Connecting to PostgreSQL (Neon)...")
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=2,
                max_size=10,
                timeout=30,
                command_timeout=60
            )
            
            # Initialize Batchers
            self.telemetry_batcher = AsyncBatcher(self.pool, "telemetry", ["bot_id", "timestamp", "state"])
            self.bars_batcher = AsyncBatcher(self.pool, "market_bars", ["symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume"])
            self.equity_batcher = AsyncBatcher(self.pool, "equity_history", ["bot_id", "timestamp", "balance", "equity", "margin_level", "open_positions"])
            self.logs_batcher = AsyncBatcher(self.pool, "bot_logs", ["bot_id", "level", "message", "timestamp"], file_path="logs/bot_logs.txt")
            self.metrics_batcher = AsyncBatcher(self.pool, "system_metrics", ["metric_name", "value", "metadata", "timestamp"], file_path="logs/system_metrics.txt")
            
            # Ensure default user exists
            await self._ensure_user(self._user_id)
            logger.info("PostgreSQL Store ready.")
        except Exception as e:
            logger.error(f"PostgreSQL Connection Failed: {e}")
            raise

    async def close(self):
        if self.pool:
            # Final flush
            if self.telemetry_batcher: await self.telemetry_batcher.flush()
            if self.bars_batcher: await self.bars_batcher.flush()
            if self.equity_batcher: await self.equity_batcher.flush()
            if self.logs_batcher: await self.logs_batcher.flush()
            if self.metrics_batcher: await self.metrics_batcher.flush()
            await self.pool.close()
            self.pool = None

    def set_user(self, uid: str):
        self._user_id = uid
        if self.pool:
            asyncio.create_task(self._ensure_user(uid))

    async def _ensure_user(self, uid: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (uid) VALUES ($1) ON CONFLICT (uid) DO NOTHING",
                uid
            )

    # ─────────────────────────────────────────────
    # FLEET & BOT CONFIG
    # ─────────────────────────────────────────────

    async def save_fleet_config(self, config_dict: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO fleet_configs (uid, config, updated_at) 
                   VALUES ($1, $2, NOW()) 
                   ON CONFLICT (uid) DO UPDATE SET config = $2, updated_at = NOW()""",
                self._user_id, json.dumps(config_dict)
            )

    async def save_fleet_event(self, event_type: str, severity: str, message: str, metadata: dict = None):
        # 1. Log to standard logger (buffered to logs/fleet.txt via main.py)
        log_level = getattr(logging, severity.upper(), logging.INFO)
        logger.log(log_level, f"[FLEET_EVENT] {event_type}: {message} | Metadata: {metadata}")

        # 2. Persist to Postgres
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO fleet_events (event_type, severity, message, metadata, timestamp) 
                   VALUES ($1, $2, $3, $4, NOW())""",
                event_type, severity, message, json.dumps(metadata) if metadata else None
            )

    async def save_audit_log(self, action: str, resource: str, resource_id: str = None, metadata: dict = None):
        # 1. Log to standard logger
        logger.info(f"[AUDIT] {action} on {resource}/{resource_id or ''} | Metadata: {metadata}")

        # 2. Persist to Postgres
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_logs (uid, action, resource, resource_id, metadata, timestamp) 
                   VALUES ($1, $2, $3, $4, $5, NOW())""",
                self._user_id, action, resource, resource_id, json.dumps(metadata) if metadata else None
            )

    async def load_fleet_config(self) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT config FROM fleet_configs WHERE uid = $1", self._user_id)
            return json.loads(row['config']) if row else None

    async def save_bot_config(self, bot_id: str, config_dict: dict):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO bots (bot_id, uid, name, symbol, status, updated_at) 
                       VALUES ($1, $2, $3, $4, $5, NOW()) 
                       ON CONFLICT (bot_id) DO UPDATE SET name = $3, symbol = $4, status = $5, updated_at = NOW()""",
                    bot_id, self._user_id, config_dict.get('name', ''), config_dict.get('symbol', ''), 'stopped'
                )
                await conn.execute(
                    """INSERT INTO bot_configs (bot_id, config, saved_at) 
                       VALUES ($1, $2, NOW()) 
                       ON CONFLICT (bot_id) DO UPDATE SET config = $2, saved_at = NOW()""",
                    bot_id, json.dumps(config_dict)
                )

    async def load_bot_config(self, bot_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT config FROM bot_configs WHERE bot_id = $1", bot_id)
            return json.loads(row['config']) if row else None

    async def list_bot_ids(self) -> List[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT bot_id FROM bots WHERE uid = $1", self._user_id)
            return [r['bot_id'] for r in rows]

    async def delete_bot_config(self, bot_id: str):
        """Deregister and delete a bot and all its related data."""
        async with self.pool.acquire() as conn:
            # Cascade delete is handled by FK constraints in schema.sql
            await conn.execute("DELETE FROM bots WHERE bot_id = $1", bot_id)

    async def delete_bot(self, bot_id: str):
        """Legacy alias for delete_bot_config."""
        await self.delete_bot_config(bot_id)

    async def discover_orphaned_bot_ids(self, known_ids: set) -> List[str]:
        # Compatibility shim for fleet.py migration helper
        return []

    # ─────────────────────────────────────────────
    # TELEMETRY & TRENDS
    # ─────────────────────────────────────────────

    async def push_live_telemetry(self, id: str, state: dict):
        """Update the latest snapshot for a bot or the fleet."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO live_telemetry (id, state, updated_at) 
                   VALUES ($1, $2, NOW()) 
                   ON CONFLICT (id) DO UPDATE SET state = $2, updated_at = NOW()""",
                id, json.dumps(state)
            )

    async def push_telemetry_history(self, bot_id: str, state: dict):
        """Buffer high-frequency telemetry for historical analysis."""
        ts = self._parse_ts(state.get('timestamp')) or datetime.now(timezone.utc)
        if self.telemetry_batcher:
            await self.telemetry_batcher.add(
                bot_id, 
                ts, 
                json.dumps(state)
            )

    async def get_live_telemetry(self, id: str) -> Optional[dict]:
        """Retrieve the latest snapshot for a bot or the fleet."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT state FROM live_telemetry WHERE id = $1", id)
            return json.loads(row['state']) if row else None

    async def push_fleet_telemetry(self, state: dict):
        """Alias for push_live_telemetry('fleet', state)."""
        await self.push_live_telemetry('fleet', state)

    async def save_trend_summary(self, symbol: str, timeframe: str, data: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO market_trends (symbol, timeframe, trend_data, updated_at) 
                   VALUES ($1, $2, $3, NOW()) 
                   ON CONFLICT (symbol, timeframe) DO UPDATE SET trend_data = $3, updated_at = NOW()""",
                symbol, timeframe, json.dumps(data)
            )

    async def get_trend_summary(self, symbol: str, timeframe: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT trend_data FROM market_trends WHERE symbol = $1 AND timeframe = $2",
                symbol, timeframe
            )
            return json.loads(row['trend_data']) if row else None

    async def prune_old_telemetry(self, hours: int = 48):
        """Keep only the last N hours of high-frequency telemetry, logs, and metrics."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self.pool.acquire() as conn:
            # Prune high-frequency tables
            await conn.execute("DELETE FROM telemetry WHERE timestamp < $1", cutoff)
            await conn.execute("DELETE FROM bot_logs WHERE timestamp < $1", cutoff)
            await conn.execute("DELETE FROM system_metrics WHERE timestamp < $1", cutoff)
            await conn.execute("DELETE FROM agent_signals WHERE timestamp < $1", cutoff)
            
            logger.info(f"Persistence cleanup complete: Pruned records older than {hours}h")

    async def log_bot_message(self, bot_id: str, level: str, message: str):
        """Buffer bot logs for persistence."""
        if self.logs_batcher:
            await self.logs_batcher.add(bot_id, level, message, datetime.now(timezone.utc))

    async def push_system_metric(self, name: str, value: float, metadata: dict = None):
        """Buffer system metrics for persistence."""
        if self.metrics_batcher:
            await self.metrics_batcher.add(
                name, 
                value, 
                json.dumps(metadata) if metadata else None, 
                datetime.now(timezone.utc)
            )

    # ─────────────────────────────────────────────
    # TRADES
    # ─────────────────────────────────────────────

    async def save_trade(self, bot_id: str, trade: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO trades (
                    bot_id, ticket, symbol, direction, volume, entry_price, exit_price, 
                    pnl, swap, commission, magic, comment, entry_time, exit_time
                   ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)""",
                bot_id, trade.get('ticket'), trade.get('symbol'), trade.get('direction'),
                trade.get('volume'), trade.get('entry_price'), trade.get('exit_price'),
                trade.get('pnl'), trade.get('swap', 0), trade.get('commission', 0),
                trade.get('magic'), trade.get('comment'),
                self._parse_ts(trade.get('entry_time') or trade.get('timestamp')),
                self._parse_ts(trade.get('exit_time'))
            )

    async def get_trades(self, bot_id: str, limit: int = 100) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM trades WHERE bot_id = $1 ORDER BY entry_time DESC LIMIT $2",
                bot_id, limit
            )
            return [dict(r) for r in rows]

    async def get_all_trades(self, limit: int = 1000) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT t.*, b.name as bot_name FROM trades t JOIN bots b ON t.bot_id = b.bot_id WHERE b.uid = $1 ORDER BY t.entry_time DESC LIMIT $2",
                self._user_id, limit
            )
            return [dict(r) for r in rows]

    # ─────────────────────────────────────────────
    # TELEMETRY & BARS (Batched)
    # ─────────────────────────────────────────────



    async def append_bar(self, symbol: str, timeframe: str, bar: dict):
        ts = self._parse_ts(bar['timestamp'])
        if self.bars_batcher:
            await self.bars_batcher.add(
                symbol, timeframe, ts, 
                float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close']),
                int(bar.get('volume', 0))
            )

    async def save_equity_snapshot(self, bot_id: str, snapshot: dict):
        ts = self._parse_ts(snapshot.get('timestamp')) or datetime.now(timezone.utc)
        if self.equity_batcher:
            await self.equity_batcher.add(
                bot_id, ts, 
                float(snapshot['balance']), float(snapshot['equity']), 
                float(snapshot.get('margin_level', 0)), int(snapshot.get('open_positions', 0))
            )

    # ─────────────────────────────────────────────
    # AGENT SIGNALS & RECOMMENDATIONS
    # ─────────────────────────────────────────────

    async def save_agent_signals(self, bot_id: str, signals: dict):
        ts = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_signals (bot_id, timestamp, signals) VALUES ($1, $2, $3)",
                bot_id, ts, json.dumps(signals)
            )

    async def log_agent_recommendation(self, bot_id: str, rec: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_recommendations (
                    bot_id, agent_name, symbol, direction, confidence, signal_price, timestamp
                   ) VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                bot_id, rec['agent'], rec['symbol'], rec['direction'],
                rec['confidence'], rec['signal_price'], self._parse_ts(rec['timestamp'])
            )

    async def update_agent_recommendation_outcome(
        self, 
        bot_id: str, 
        agent_name: str, 
        timestamp: str, 
        forward_return_1d: float, 
        forward_return_5d: float
    ) -> None:
        """Score a previously logged recommendation against forward returns."""
        ts = self._parse_ts(timestamp)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE agent_recommendations 
                   SET forward_return_1d = $4, forward_return_5d = $5, scored = TRUE
                   WHERE bot_id = $1 AND agent_name = $2 AND timestamp = $3""",
                bot_id, agent_name, ts, forward_return_1d, forward_return_5d
            )

    async def get_agent_sharpe(self, bot_id: str, agent_name: str, lookback_days: int = 60) -> float:
        """Compute rolling Sharpe for one agent's recommendations."""
        import numpy as np
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT direction, forward_return_1d, forward_return_5d 
                   FROM agent_recommendations 
                   WHERE bot_id = $1 AND agent_name = $2 AND scored = TRUE AND timestamp >= $3""",
                bot_id, agent_name, since
            )

        returns = []
        for row in rows:
            # Use 5d return if available, fallback to 1d
            ret = row['forward_return_5d']
            if ret is None:
                ret = row['forward_return_1d']

            if ret is not None:
                dir_str = row['direction']
                multiplier = 0.0
                if dir_str == "BUY": multiplier = 1.0
                elif dir_str == "SELL": multiplier = -1.0
                returns.append(ret * multiplier)

        if len(returns) < 5:
            return 0.0

        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns))

        return (mean_r / std_r) if std_r > 0 else 0.0

    async def save_ai_decision(self, bot_id: str, decision: dict):
        """Persist an AI Brain decision to strategy_contexts."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO strategy_contexts (bot_id, context, timestamp) VALUES ($1, $2, $3)",
                bot_id, json.dumps(decision), self._parse_ts(decision.get('timestamp')) or datetime.now(timezone.utc)
            )

    async def save_strategy_context(self, bot_id: str, context: dict, **kwargs):
        """Alias for save_ai_decision (ignores extra kwargs like embedding_text)."""
        await self.save_ai_decision(bot_id, context)

    async def retrieve_recent_strategy_contexts(self, bot_id: str, limit: int = 50) -> List[dict]:
        """Alias for get_ai_decisions."""
        return await self.get_ai_decisions(bot_id, limit)

    async def get_ai_decisions(self, bot_id: str, limit: int = 50) -> List[dict]:
        """Retrieve recent AI decisions for a bot."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT context, timestamp FROM strategy_contexts WHERE bot_id = $1 ORDER BY timestamp DESC LIMIT $2",
                bot_id, limit
            )
            results = []
            for r in rows:
                data = json.loads(r['context'])
                data['timestamp'] = r['timestamp'].isoformat()
                results.append(data)
            return results

    # ─────────────────────────────────────────────
    # BOT STATE (KV)
    # ─────────────────────────────────────────────

    async def set_bot_state(self, bot_id: str, key: str, value: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bot_state_kv (bot_id, key, value, updated_at) 
                   VALUES ($1, $2, $3, NOW()) 
                   ON CONFLICT (bot_id, key) DO UPDATE SET value = $3, updated_at = NOW()""",
                bot_id, key, value
            )

    async def get_bot_state(self, bot_id: str, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM bot_state_kv WHERE bot_id = $1 AND key = $2", bot_id, key)
            return row['value'] if row else None

    # ─────────────────────────────────────────────
    # NEW: PERFORMANCE & SETTINGS
    # ─────────────────────────────────────────────

    async def save_bot_performance(self, bot_id: str, date: datetime, stats: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bot_performance_snapshots (
                    bot_id, date, pnl, win_rate, total_trades, sharpe, max_drawdown
                   ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (bot_id, date) DO UPDATE SET 
                    pnl = $3, win_rate = $4, total_trades = $5, sharpe = $6, max_drawdown = $7""",
                bot_id, date.date(), stats.get('pnl', 0.0), stats.get('win_rate'),
                stats.get('total_trades'), stats.get('sharpe'), stats.get('max_drawdown')
            )

    async def save_fleet_performance(self, date: datetime, stats: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO fleet_performance_history (date, total_equity, total_pnl, running_bots) 
                   VALUES ($1, $2, $3, $4) 
                   ON CONFLICT (date) DO UPDATE SET 
                    total_equity = $2, total_pnl = $3, running_bots = $4""",
                date.date(), stats.get('total_equity', 0.0), stats.get('total_pnl', 0.0), stats.get('running_bots', 0)
            )

    async def set_system_setting(self, key: str, value: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO system_settings (key, value, updated_at) 
                   VALUES ($1, $2, NOW()) 
                   ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
                key, value
            )

    async def get_system_setting(self, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM system_settings WHERE key = $1", key)
            return row['value'] if row else None

    # ─────────────────────────────────────────────
    # NEW: PROMPT MANAGEMENT
    # ─────────────────────────────────────────────

    async def save_prompt(self, agent_name: str, text: str, version: int):
        async with self.pool.acquire() as conn:
            # Set all other versions for this agent to inactive
            await conn.execute("UPDATE prompts SET is_active = FALSE WHERE agent_name = $1", agent_name)
            await conn.execute(
                "INSERT INTO prompts (agent_name, prompt_text, version, is_active) VALUES ($1, $2, $3, TRUE)",
                agent_name, text, version
            )

    async def get_active_prompt(self, agent_name: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT prompt_text FROM prompts WHERE agent_name = $1 AND is_active = TRUE", agent_name)
            return row['prompt_text'] if row else None

    # ─────────────────────────────────────────────
    # RESEARCH REPORTS (TradingAgents framework cache)
    # ─────────────────────────────────────────────

    async def save_research_report(self, symbol: str, payload: dict) -> None:
        """
        Persist (or update) the latest research report for a symbol.

        `payload` is the translated AgentSignal as a dict, plus optional raw
        context (e.g. final_state digest). Keyed by symbol — one row per symbol.
        Used by ResearchBridge.run_research() for TTL caching.
        """
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("save_research_report: symbol must be a non-empty string")
        if payload is None:
            payload = {}
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research_reports (symbol, payload, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (symbol) DO UPDATE
                    SET payload = EXCLUDED.payload,
                        updated_at = NOW()
                """,
                symbol, json.dumps(payload)
            )

    async def get_latest_research_report(
        self, symbol: str
    ) -> Optional[tuple]:
        """
        Return (payload: dict, updated_at: datetime) for the latest cached
        research report for `symbol`, or None if no row exists.

        ResearchBridge.run_research() applies its own TTL check on the
        `updated_at` value returned here (default 4h via RESEARCH_CACHE_TTL).
        """
        if not symbol:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload, updated_at FROM research_reports WHERE symbol = $1",
                symbol
            )
            if not row:
                return None
            raw = row['payload']
            # asyncpg may return JSONB as str (if no codec) or already-decoded dict.
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            if isinstance(raw, str):
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {}
            elif isinstance(raw, dict):
                payload = raw
            else:
                payload = {}
            return payload, row['updated_at']

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def _parse_ts(self, ts: Any) -> Optional[datetime]:
        if not ts: return None
        if isinstance(ts, datetime): return ts
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except:
            return None

# Global Instance
_store: Optional[PostgresStore] = None

async def init_db(dsn: Optional[str] = None):
    global _store
    if not dsn: dsn = DATABASE_URL
    if not dsn: raise ValueError("DATABASE_URL not set")
    _store = PostgresStore(dsn)
    await _store.connect()

def get_store() -> PostgresStore:
    if not _store: raise RuntimeError("PostgresStore not initialized")
    return _store

async def save_darwinian_weights(bot_id: str, weights: dict):
    await get_store().set_bot_state(bot_id, "darwinian_weights", json.dumps(weights))

async def load_darwinian_weights(bot_id: str) -> Optional[dict]:
    val = await get_store().get_bot_state(bot_id, "darwinian_weights")
    if val:
        try:
            return json.loads(val)
        except:
            return None
    return None

def is_initialized() -> bool:
    return _store is not None and _store.pool is not None

# ─────────────────────────────────────────────
# BARS & TRENDS
# ─────────────────────────────────────────────

async def load_bars(symbol: str, timeframe: str = "1m", limit: int = 1000) -> List[dict]:
    """Retrieve recent bars from PostgreSQL."""
    async with get_store().pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT timestamp as time, "open", high, low, "close", volume 
               FROM market_bars 
               WHERE symbol = $1 AND timeframe = $2 
               ORDER BY timestamp ASC LIMIT $3""",
            symbol, timeframe, limit
        )
        return [dict(r) for r in rows]

async def prune_bars(symbol: str, timeframe: str = "1m", keep: int = 1200):
    """Delete old bars for a symbol, keeping only the most recent N."""
    async with get_store().pool.acquire() as conn:
        # Get the timestamp of the N-th most recent bar
        row = await conn.fetchrow(
            "SELECT timestamp FROM market_bars WHERE symbol = $1 AND timeframe = $2 ORDER BY timestamp DESC OFFSET $3 LIMIT 1",
            symbol, timeframe, keep - 1
        )
        if row:
            cutoff = row['timestamp']
            await conn.execute(
                "DELETE FROM market_bars WHERE symbol = $1 AND timeframe = $2 AND timestamp < $3",
                symbol, timeframe, cutoff
            )

async def append_bars_batch(symbol: str, bars: List[dict], timeframe: str = "1m"):
    """Persist a batch of bars using the batcher."""
    store = get_store()
    for bar in bars:
        ts = store._parse_ts(bar.get('t') or bar.get('timestamp') or bar.get('time'))
        if ts:
            await store.bars_batcher.add(
                symbol, timeframe, ts,
                float(bar.get('o') or bar.get('open', 0)),
                float(bar.get('h') or bar.get('high', 0)),
                float(bar.get('l') or bar.get('low', 0)),
                float(bar.get('c') or bar.get('close', 0)),
                int(bar.get('v') or bar.get('volume', 0))
            )

async def get_trend_summary(symbol: str, timeframe: str) -> Optional[dict]:
    return await get_store().get_trend_summary(symbol, timeframe)

async def save_trend_summary(symbol: str, timeframe: str, summary: dict):
    await get_store().save_trend_summary(symbol, timeframe, summary)

async def push_fleet_telemetry(state: dict):
    await get_store().push_fleet_telemetry(state)

async def get_live_telemetry(id: str) -> Optional[dict]:
    return await get_store().get_live_telemetry(id)

async def push_live_telemetry(bot_id: str, state: dict):
    await get_store().push_live_telemetry(bot_id, state)

async def push_telemetry_history(bot_id: str, state: dict):
    await get_store().push_telemetry_history(bot_id, state)

async def save_fleet_config(config: dict):
    await get_store().save_fleet_config(config)

async def load_bot_config(bot_id: str) -> Optional[dict]:
    return await get_store().load_bot_config(bot_id)

async def delete_bot_config(bot_id: str):
    await get_store().delete_bot_config(bot_id)

async def save_trade(bot_id: str, trade_data: dict):
    await get_store().save_trade(bot_id, trade_data)

async def save_equity_snapshot(bot_id: str, snapshot: dict):
    await get_store().save_equity_snapshot(bot_id, snapshot)

async def prune_old_telemetry(hours: int = 48):
    await get_store().prune_old_telemetry(hours)

async def push_system_metric(metric_name: str, value: float):
    await get_store().push_system_metric(metric_name, value)

async def retrieve_recent_strategy_contexts(bot_id: str, limit: int = 50) -> List[dict]:
    return await get_store().retrieve_recent_strategy_contexts(bot_id, limit)

async def update_bot_config(bot_id: str, config_dict: dict):
    """Alias for save_bot_config."""
    await get_store().save_bot_config(bot_id, config_dict)

async def save_strategy_context(bot_id: str, context: dict, **kwargs):
    await get_store().save_strategy_context(bot_id, context, **kwargs)

# ─────────────────────────────────────────────
# COMPATIBILITY ALIASES (For main.py)
# ─────────────────────────────────────────────

async def insert_trade(bot_id: str, trade: Optional[dict] = None, **kwargs):
    """Compatibility shim for main.py."""
    if trade is None:
        trade = kwargs
    await get_store().save_trade(bot_id, trade)

async def insert_equity_snapshot(bot_id: str, snapshot: Optional[dict] = None, **kwargs):
    """Compatibility shim for main.py."""
    if snapshot is None:
        snapshot = kwargs
    # Ensure standard field names
    if "daily_pnl" in snapshot and "balance" not in snapshot:
        snapshot["balance"] = snapshot.get("equity", 0.0) - snapshot["daily_pnl"]
    await get_store().save_equity_snapshot(bot_id, snapshot)

async def get_all_trades(limit: int = 1000) -> List[dict]:
    return await get_store().get_all_trades(limit)

async def get_recent_trades_for_analysis(bot_id: str, limit: int = 20) -> List[dict]:
    return await get_store().get_trades(bot_id, limit)

async def _legacy_get_equity_history(bot_id: str, limit: int = 200) -> List[dict]:
    async with get_store().pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM equity_history WHERE bot_id = $1 ORDER BY timestamp ASC LIMIT $2",
            bot_id, limit
        )
        return [dict(r) for r in rows]

async def _legacy_get_daily_pnl_sum(bot_id: Optional[str] = None) -> float:
    async with get_store().pool.acquire() as conn:
        if bot_id:
            row = await conn.fetchrow(
                "SELECT SUM(pnl) as total FROM trades WHERE bot_id = $1 AND entry_time >= CURRENT_DATE",
                bot_id
            )
        else:
            row = await conn.fetchrow(
                "SELECT SUM(pnl) as total FROM trades WHERE entry_time >= CURRENT_DATE"
            )
        return row['total'] or 0.0

async def _legacy_get_trade_stats_today(bot_id: Optional[str] = None) -> dict:
    async with get_store().pool.acquire() as conn:
        if bot_id:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as count, SUM(pnl) as pnl, 
                          COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins 
                   FROM trades WHERE bot_id = $1 AND entry_time >= CURRENT_DATE""",
                bot_id
            )
        else:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as count, SUM(pnl) as pnl, 
                          COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins 
                   FROM trades WHERE entry_time >= CURRENT_DATE"""
            )
        return dict(row)

async def _legacy_set_bot_state(bot_id: str, key: str, value: str):
    await get_store().set_bot_state(bot_id, key, value)

async def _legacy_get_bot_state(bot_id: str, key: str) -> Optional[str]:
    return await get_store().get_bot_state(bot_id, key)

async def _legacy_get_ai_decisions(bot_id: str, limit: int = 50) -> List[dict]:
    async with get_store().pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM strategy_contexts WHERE bot_id = $1 ORDER BY timestamp DESC LIMIT $2",
            bot_id, limit
        )
        return [dict(r) for r in rows]

async def get_agent_sharpe(bot_id: str, agent_name: str, lookback_days: int = 60) -> float:
    return await get_store().get_agent_sharpe(bot_id, agent_name, lookback_days)

async def update_agent_recommendation_outcome(bot_id: str, agent_name: str, timestamp: str, f1d: float, f5d: float):
    await get_store().update_agent_recommendation_outcome(bot_id, agent_name, timestamp, f1d, f5d)

async def save_ai_decision(bot_id: str, decision: dict):
    await get_store().save_ai_decision(bot_id, decision)

async def get_ai_decisions(bot_id: str, limit: int = 50) -> List[dict]:
    return await get_store().get_ai_decisions(bot_id, limit)

async def log_bot_message(bot_id: str, level: str, message: str):
    await get_store().log_bot_message(bot_id, level, message)

async def save_fleet_event(event_type: str, severity: str, message: str, metadata: dict = None):
    await get_store().save_fleet_event(event_type, severity, message, metadata)

async def save_audit_log(action: str, resource: str, resource_id: str = None, metadata: dict = None):
    await get_store().save_audit_log(action, resource, resource_id, metadata)

async def prune_old_telemetry(hours: int = 48):
    await get_store().prune_old_telemetry(hours)

async def load_fleet_config() -> Optional[dict]:
    return await get_store().load_fleet_config()

async def save_fleet_config(config_dict: dict):
    await get_store().save_fleet_config(config_dict)

async def save_bot_config(bot_id: str, config_dict: dict):
    await get_store().save_bot_config(bot_id, config_dict)

async def load_bot_config(bot_id: str) -> Optional[dict]:
    return await get_store().load_bot_config(bot_id)

async def delete_bot_config(bot_id: str):
    await get_store().delete_bot_config(bot_id)

async def list_bot_ids() -> List[str]:
    return await get_store().list_bot_ids()

async def push_fleet_telemetry(state: dict):
    await get_store().push_fleet_telemetry(state)

async def push_telemetry_history(bot_id: str, state: dict):
    await get_store().push_telemetry_history(bot_id, state)

async def push_system_metric(name: str, value: float, metadata: dict = None):
    await get_store().push_system_metric(name, value, metadata)

async def save_trade(bot_id: str, trade: dict):
    await get_store().save_trade(bot_id, trade)

async def save_equity_snapshot(bot_id: str, snapshot: dict):
    await get_store().save_equity_snapshot(bot_id, snapshot)
