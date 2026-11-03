"""
TradeClaw — SQLite Persistence Layer
=====================================
Single-file SQLite store replacing PostgreSQL + Firebase.
All trading state, credentials, and config in one local database.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, date
from typing import Optional, Any, List, Dict
import aiosqlite

logger = logging.getLogger("tradeclaw.store")

DB_PATH = os.path.join(os.path.dirname(__file__), "tradeclaw.db")


# ─────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    pnl REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT DEFAULT '',
    signal TEXT DEFAULT '',
    trade_date TEXT NOT NULL,
    params_snapshot TEXT DEFAULT '',
    fib_level_triggered TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL,
    balance REAL DEFAULT 0.0,
    daily_pnl REAL DEFAULT 0.0,
    snapshot_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    bot_id TEXT NOT NULL DEFAULT 'default',
    timestamp TEXT NOT NULL,
    agent_name TEXT DEFAULT '',
    context TEXT NOT NULL,
    decision_type TEXT DEFAULT 'deliberation'
);

CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    metadata TEXT DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_equity_session ON equity_history(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON agent_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON system_metrics(metric_name);
"""


# ─────────────────────────────────────────────
# SQLITE STORE
# ─────────────────────────────────────────────

class SQLiteStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        if self._db:
            return
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        logger.info(f"SQLite store ready at {self.db_path}")

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def execute(self, sql: str, *params):
        if not self._db:
            raise RuntimeError("Store not initialized")
        return await self._db.execute(sql, params)

    async def executemany(self, sql: str, params_list):
        if not self._db:
            raise RuntimeError("Store not initialized")
        return await self._db.executemany(sql, params_list)

    async def fetchone(self, sql: str, *params) -> Optional[dict]:
        if not self._db:
            raise RuntimeError("Store not initialized")
        cur = await self._db.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, *params) -> List[dict]:
        if not self._db:
            raise RuntimeError("Store not initialized")
        cur = await self._db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def commit(self):
        if self._db:
            await self._db.commit()

    # ── Settings KV ────────────────────────────────────────────────

    async def set_setting(self, key: str, value: str):
        await self.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            key, value
        )
        await self.commit()

    async def get_setting(self, key: str) -> Optional[str]:
        row = await self.fetchone("SELECT value FROM settings WHERE key = ?", key)
        return row["value"] if row else None

    async def get_all_settings(self) -> Dict[str, str]:
        rows = await self.fetchall("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    async def delete_setting(self, key: str):
        await self.execute("DELETE FROM settings WHERE key = ?", key)
        await self.commit()

    # ── Trades ──────────────────────────────────────────────────────

    async def save_trade(self, trade: dict):
        session_id = trade.get("session_id", "default")
        entry_time = trade.get("entry_time") or datetime.now(timezone.utc).isoformat()
        trade_date = trade.get("trade_date") or date.today().isoformat()
        await self.execute(
            """INSERT INTO trades (session_id, symbol, side, qty, entry_price, exit_price,
               entry_time, exit_time, pnl, status, reason, signal, trade_date,
               params_snapshot, fib_level_triggered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            session_id,
            trade.get("symbol", ""),
            trade.get("side", ""),
            float(trade.get("qty", 0)),
            float(trade.get("entry_price", 0)),
            trade.get("exit_price"),
            entry_time,
            trade.get("exit_time"),
            float(trade.get("pnl", 0)),
            trade.get("status", "open"),
            trade.get("reason", ""),
            trade.get("signal", ""),
            trade_date,
            json.dumps(trade.get("params_snapshot", {})),
            trade.get("fib_level_triggered"),
        )
        await self.commit()

    async def get_trades(self, session_id: str = "default", limit: int = 200) -> List[dict]:
        return await self.fetchall(
            "SELECT * FROM trades WHERE session_id = ? ORDER BY entry_time DESC LIMIT ?",
            session_id, limit
        )

    async def get_all_trades(self, limit: int = 1000) -> List[dict]:
        return await self.fetchall(
            "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", limit
        )

    async def get_recent_trades_for_analysis(self, limit: int = 20) -> List[dict]:
        return await self.fetchall(
            "SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_time DESC LIMIT ?", limit
        )

    async def get_daily_pnl_sum(self) -> float:
        row = await self.fetchone(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE trade_date = ?",
            date.today().isoformat()
        )
        return row["total"] if row else 0.0

    async def get_trade_stats_today(self) -> dict:
        today = date.today().isoformat()
        row = await self.fetchone(
            """SELECT COUNT(*) as count, COALESCE(SUM(pnl), 0) as pnl,
                      COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins
               FROM trades WHERE trade_date = ?""",
            today
        )
        return dict(row) if row else {"count": 0, "pnl": 0.0, "wins": 0}

    # ── Equity History ──────────────────────────────────────────────

    async def save_equity_snapshot(self, snapshot: dict):
        session_id = snapshot.get("session_id", "default")
        ts = snapshot.get("timestamp") or datetime.now(timezone.utc).isoformat()
        snap_date = snapshot.get("snapshot_date") or date.today().isoformat()
        await self.execute(
            """INSERT INTO equity_history (session_id, timestamp, equity, balance, daily_pnl, snapshot_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            session_id, ts,
            float(snapshot.get("equity", 0)),
            float(snapshot.get("balance", 0)),
            float(snapshot.get("daily_pnl", 0)),
            snap_date,
        )
        await self.commit()

    async def get_equity_history(self, session_id: str = "default", limit: int = 500) -> List[dict]:
        return await self.fetchall(
            "SELECT * FROM equity_history WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            session_id, limit
        )

    # ── Agent Decisions ─────────────────────────────────────────────

    async def save_ai_decision(self, decision: dict):
        session_id = decision.get("session_id", "default")
        bot_id = decision.get("bot_id", "default")
        ts = decision.get("timestamp") or datetime.now(timezone.utc).isoformat()
        agent_name = decision.get("agent_name", "")
        context = json.dumps(decision.get("context", decision))
        decision_type = decision.get("decision_type", "deliberation")
        await self.execute(
            """INSERT INTO agent_decisions (session_id, bot_id, timestamp, agent_name, context, decision_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            session_id, bot_id, ts, agent_name, context, decision_type,
        )
        await self.commit()

    async def get_ai_decisions(self, session_id: str = "default", limit: int = 50) -> List[dict]:
        rows = await self.fetchall(
            "SELECT * FROM agent_decisions WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            session_id, limit
        )
        results = []
        for r in rows:
            data = json.loads(r["context"])
            data["timestamp"] = r["timestamp"]
            data["id"] = r["id"]
            results.append(data)
        return results

    # ── System Metrics ──────────────────────────────────────────────

    async def push_system_metric(self, name: str, value: float, metadata: dict = None):
        await self.execute(
            "INSERT INTO system_metrics (metric_name, value, metadata) VALUES (?, ?, ?)",
            name, value, json.dumps(metadata or {}),
        )
        await self.commit()

    async def get_system_metrics(self, limit: int = 100) -> List[dict]:
        return await self.fetchall(
            "SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT ?", limit
        )

    # ── Legacy Compatibility (stubs for old callers) ─────────────────

    async def set_bot_state(self, bot_id: str, key: str, value: str):
        await self.set_setting(f"bot_state:{bot_id}:{key}", value)

    async def get_bot_state(self, bot_id: str, key: str) -> Optional[str]:
        return await self.get_setting(f"bot_state:{bot_id}:{key}")

    async def save_fleet_event(self, event_type: str, severity: str, message: str, metadata: dict = None):
        logger.log(
            getattr(logging, severity.upper(), logging.INFO),
            f"[FLEET_EVENT] {event_type}: {message} | {metadata or ''}",
        )

    async def save_audit_log(self, action: str, resource: str, resource_id: str = None, metadata: dict = None):
        logger.info(f"[AUDIT] {action} on {resource}/{resource_id or ''} | {metadata or ''}")


# ── Global Instance ───────────────────────────────────────────────────────

_store: Optional[SQLiteStore] = None


async def init_db(db_path: Optional[str] = None):
    global _store
    _store = SQLiteStore(db_path or DB_PATH)
    await _store.connect()


def get_store() -> SQLiteStore:
    if not _store:
        raise RuntimeError("Store not initialized. Call init_db() first.")
    return _store


def is_initialized() -> bool:
    return _store is not None and _store._db is not None


# ── Module-Level Convenience Functions ─────────────────────────────────────

async def insert_trade(bot_id: str, trade: Optional[dict] = None, **kwargs):
    if trade is None:
        trade = kwargs
    trade.setdefault("session_id", bot_id or "default")
    await get_store().save_trade(trade)


async def insert_equity_snapshot(bot_id: str, snapshot: Optional[dict] = None, **kwargs):
    if snapshot is None:
        snapshot = kwargs
    if "daily_pnl" in snapshot and "balance" not in snapshot:
        snapshot["balance"] = snapshot.get("equity", 0.0) - snapshot["daily_pnl"]
    snapshot.setdefault("session_id", bot_id or "default")
    await get_store().save_equity_snapshot(snapshot)


async def get_all_trades(limit: int = 1000) -> List[dict]:
    return await get_store().get_all_trades(limit)


async def get_recent_trades_for_analysis(bot_id: str = "default", limit: int = 20) -> List[dict]:
    return await get_store().get_recent_trades_for_analysis(limit)


async def _legacy_get_equity_history(bot_id: str = "default", limit: int = 200) -> List[dict]:
    return await get_store().get_equity_history(bot_id, limit)


get_equity_history = _legacy_get_equity_history


async def _legacy_get_daily_pnl_sum(bot_id: Optional[str] = None) -> float:
    return await get_store().get_daily_pnl_sum()


get_daily_pnl_sum = _legacy_get_daily_pnl_sum


async def _legacy_get_trade_stats_today(bot_id: Optional[str] = None) -> dict:
    return await get_store().get_trade_stats_today()


get_trade_stats_today = _legacy_get_trade_stats_today


async def _legacy_set_bot_state(bot_id: str, key: str, value: str):
    await get_store().set_bot_state(bot_id, key, value)


async def _legacy_get_bot_state(bot_id: str, key: str) -> Optional[str]:
    return await get_store().get_bot_state(bot_id, key)


async def _legacy_get_ai_decisions(bot_id: str = "default", limit: int = 50) -> List[dict]:
    return await get_store().get_ai_decisions(bot_id, limit)


get_ai_decisions = _legacy_get_ai_decisions


async def save_ai_decision(bot_id: str, decision: dict):
    decision.setdefault("session_id", bot_id or "default")
    decision.setdefault("bot_id", bot_id or "default")
    await get_store().save_ai_decision(decision)


async def save_fleet_event(event_type: str, severity: str, message: str, metadata: dict = None):
    await get_store().save_fleet_event(event_type, severity, message, metadata)


async def save_audit_log(action: str, resource: str, resource_id: str = None, metadata: dict = None):
    await get_store().save_audit_log(action, resource, resource_id, metadata)


async def push_system_metric(name: str, value: float, metadata: dict = None):
    await get_store().push_system_metric(name, value, metadata)


async def save_darwinian_weights(bot_id: str, weights: dict):
    await get_store().set_bot_state(bot_id, "darwinian_weights", json.dumps(weights))


async def load_darwinian_weights(bot_id: str) -> Optional[dict]:
    val = await get_store().get_bot_state(bot_id, "darwinian_weights")
    if val:
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return None


async def log_bot_message(bot_id: str, level: str, message: str):
    logger.log(getattr(logging, level.upper(), logging.INFO), f"[{bot_id}] {message}")


# ── Stubs for removed multi-account / fleet callers ───────────────────────

async def list_mt5_accounts() -> List[dict]:
    return []


async def get_mt5_account(account_id: str) -> Optional[dict]:
    return None


async def add_mt5_account(data: dict) -> str:
    return "stub-account"


async def update_mt5_account(account_id: str, data: dict) -> bool:
    return True


async def remove_mt5_account(account_id: str) -> bool:
    return True


async def update_mt5_session(account_id: str, data: dict) -> None:
    pass


async def get_mt5_sessions() -> List[dict]:
    return []


async def save_bot_config(bot_id: str, config_dict: dict):
    pass


async def load_bot_config(bot_id: str) -> Optional[dict]:
    return None


async def delete_bot_config(bot_id: str):
    pass


async def list_bot_ids() -> List[str]:
    return []


async def load_fleet_config() -> Optional[dict]:
    return None


async def save_fleet_config(config_dict: dict):
    pass


async def push_fleet_telemetry(state: dict):
    pass


async def push_live_telemetry(bot_id: str, state: dict):
    pass


async def get_live_telemetry(bot_id: str) -> Optional[dict]:
    return None


async def push_telemetry_history(bot_id: str, state: dict):
    pass


async def append_bars_batch(symbol: str, bars: List[dict], timeframe: str = "1m"):
    pass


async def load_bars(symbol: str, timeframe: str = "1m", limit: int = 1000) -> List[dict]:
    return []


async def prune_bars(symbol: str, timeframe: str = "1m", keep: int = 1200):
    pass


async def save_trend_summary(symbol: str, timeframe: str, summary: dict):
    pass


async def get_trend_summary(symbol: str, timeframe: str) -> Optional[dict]:
    return None


async def prune_old_telemetry(hours: int = 48):
    pass


async def save_bot_performance(bot_id: str, stats: dict):
    pass


async def get_agent_sharpe(bot_id: str, agent_name: str, lookback_days: int = 60) -> float:
    return 0.0


async def save_research_report(symbol: str, payload: dict):
    pass


async def get_latest_research_report(symbol: str) -> Optional[tuple]:
    return None


async def save_equity_snapshot(bot_id: str, snapshot: dict):
    snapshot.setdefault("session_id", bot_id or "default")
    await get_store().save_equity_snapshot(snapshot)


async def save_trade(bot_id: str, trade: dict):
    trade.setdefault("session_id", bot_id or "default")
    await get_store().save_trade(trade)
