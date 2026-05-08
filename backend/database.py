"""
TradeClaw SQLite Persistence Layer
Stores trades, equity snapshots, and bot state across restarts.
"""
from __future__ import annotations

import aiosqlite
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(__file__), "tradeclaw.db")


async def init_db():
    """Initialize database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                side TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL NOT NULL,
                pnl REAL DEFAULT 0.0,
                signal TEXT DEFAULT '',
                trade_date TEXT NOT NULL,
                params_snapshot TEXT DEFAULT '',
                fib_level_triggered TEXT DEFAULT NULL
            )
        """)
        
        # ── Migration: add new columns to existing tables ──────────────────
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN params_snapshot TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        try:
            await db.execute("ALTER TABLE trades ADD COLUMN fib_level_triggered TEXT DEFAULT NULL")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        await db.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL,
                daily_pnl REAL DEFAULT 0.0,
                snapshot_date TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trigger TEXT NOT NULL,
                trades_analysed INTEGER NOT NULL,
                win_rate_before REAL NOT NULL,
                daily_pnl_before REAL NOT NULL,
                params_before TEXT NOT NULL,
                params_after TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                model_used TEXT NOT NULL,
                applied INTEGER NOT NULL
            )
        """)
        await db.commit()


async def insert_trade(
    timestamp: str,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    pnl: float = 0.0,
    signal: str = "",
    params_snapshot: str = "",
    fib_level_triggered: str | None = None,
) -> int:
    """Insert a trade record. Returns the trade ID."""
    trade_date = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO trades
                   (timestamp, side, symbol, qty, price, pnl, signal, trade_date, params_snapshot, fib_level_triggered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, side, symbol, qty, price, pnl, signal, trade_date, params_snapshot, fib_level_triggered),
        )
        await db.commit()
        return cursor.lastrowid


async def get_trades_today() -> list[dict]:
    """Get all trades for today."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE trade_date = ? ORDER BY id DESC", (today,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_trades(limit: int = 200) -> list[dict]:
    """Get recent trades across all days."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def insert_equity_snapshot(
    timestamp: str, equity: float, daily_pnl: float = 0.0
):
    """Insert an equity snapshot."""
    snapshot_date = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO equity_snapshots (timestamp, equity, daily_pnl, snapshot_date)
               VALUES (?, ?, ?, ?)""",
            (timestamp, equity, daily_pnl, snapshot_date),
        )
        await db.commit()


async def get_equity_history(limit: int = 500) -> list[dict]:
    """Get recent equity snapshots."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(list(rows))]


async def get_daily_pnl_sum() -> float:
    """Get the sum of realized P&L for today."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE trade_date = ?",
            (today,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0


async def get_trade_stats_today() -> dict:
    """Get trade statistics for today."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) FROM trades WHERE trade_date = ?",
            (today,),
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0
        wins = row[1] if row else 0
        return {
            "total_trades": total,
            "win_rate": (wins / total * 100) if total > 0 else 0.0,
        }


async def set_bot_state(key: str, value: str):
    """Set a bot state value."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, now),
        )
        await db.commit()


async def get_bot_state(key: str) -> str | None:
    """Get a bot state value."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def insert_ai_decision(
    timestamp: str,
    trigger: str,
    trades_analysed: int,
    win_rate_before: float,
    daily_pnl_before: float,
    params_before: str,
    params_after: str,
    reasoning: str,
    model_used: str,
    applied: int
):
    """Insert an AI decision log."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO ai_decisions 
               (timestamp, trigger, trades_analysed, win_rate_before, daily_pnl_before, params_before, params_after, reasoning, model_used, applied)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, trigger, trades_analysed, win_rate_before, daily_pnl_before, params_before, params_after, reasoning, model_used, applied)
        )
        await db.commit()


async def get_ai_decisions(limit: int = 50) -> list[dict]:
    """Get recent AI decisions."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ai_decisions ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_recent_trades_for_analysis(limit: int = 100) -> list[dict]:
    """Get recent trades for AI analysis."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def get_trade_stats(limit: int = 200) -> dict:
    """
    Synchronous version of trade statistics for use in background threads
    (e.g. the Kelly position sizer running inside the strategy loop).

    Returns:
        {win_rate, avg_win, avg_loss, total_trades}
        where win_rate is 0.0-1.0, avg_win is positive $, avg_loss is negative $.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pnl FROM trades WHERE side IN ('SELL', 'STOP_LOSS') ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        return {"win_rate": 0.5, "avg_win": 100.0, "avg_loss": -80.0, "total_trades": 0}

    if not rows:
        return {"win_rate": 0.5, "avg_win": 100.0, "avg_loss": -80.0, "total_trades": 0}

    pnls = [row["pnl"] for row in rows]
    wins  = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total = len(pnls)

    return {
        "total_trades": total,
        "win_rate": len(wins) / total if total else 0.5,
        "avg_win":  sum(wins) / len(wins) if wins else 100.0,
        "avg_loss": sum(losses) / len(losses) if losses else -80.0,
    }

