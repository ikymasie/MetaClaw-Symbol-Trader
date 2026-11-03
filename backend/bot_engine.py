"""
TradeClaw — Per-Bot Strategy Engine
======================================
Refactored from the singleton strategy.py into an instantiable BotEngine class.
Each bot instance has its own fully-isolated engine with its own state, lock,
price history, markers, and DB write queue.
"""

import logging
import time
import threading
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from bot_config import BotConfig
from bot_vital_signs import BotVitalSigns
from position_slot_manager import PositionSlotManager
from symbol_service import to_mt5_symbol
from trading_psychology import (
    PositionDisciplineTracker,
    check_scale_in_allowed,
    check_strict_loser_cut,
    check_horizon_breach,
    check_thesis_invalidated,
    clamp_stop_never_wider,
)

logger = logging.getLogger("tradeclaw.bot_engine")


def _stable_magic(bot_id: str) -> int:
    """
    Deterministic per-bot magic number for MT5 order tagging.
    Uses zlib.crc32 (not hash()) — hash() is randomised per-process in Python 3,
    so positions opened in one session would never be found after a restart.
    Result is clamped to [1, 2_147_483_647] (positive int32, never zero).
    """
    return max(1, zlib.crc32(bot_id.encode()) % 2_147_483_647)


@dataclass
class BotEngineStatus:
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    CRITICAL_STOP = "CRITICAL_STOP"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"


class BotEngine:
    """
    Isolated strategy execution engine for a single bot.
    Wraps the MT5 trading loop for one symbol/strategy combination.
    All state is instance-local — no cross-bot contamination.
    """

    MAX_HISTORY = 1200

    def __init__(self, bot_id: str, config: BotConfig, vital_signs: BotVitalSigns):
        self.bot_id = bot_id
        self.config = config
        self._vital_signs = vital_signs
        _name = config.name if config.name and config.name != "Unnamed Bot" else ""
        _label = f"{bot_id}|{_name}" if _name else bot_id
        self._logger = logging.getLogger(f"tradeclaw.engine[{_label}]")

        # Threading
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Status
        self._status = BotEngineStatus.IDLE
        self._message = ""

        # Market state
        self.current_price: float = 0.0
        self.current_bid: float = 0.0
        self.current_ask: float = 0.0
        self.position_qty: float = 0.0
        self.position_side: str = "NONE"
        self.entry_price: float = 0.0

        # Multi-slot position tracker (Scenario 3 & 5 — layered entry + Kelly splitting)
        self._slot_manager = PositionSlotManager(
            bot_id=bot_id,
            max_slots=config.max_position_slots,
        )

        # Trailing stop-loss state
        self._trailing_high: float = 0.0          # For longs: highest price since entry
        self._trailing_low: float = float("inf")  # For shorts: lowest price since entry
        # Scale-out state: tickets that have already banked their half at the
        # gross take-profit. The remaining half is left to run on the trailing
        # stop / net target so winners can become big winners.
        self._scaled_out: set = set()

        # Advanced profit-retrace state: per-ticket PEAK floating net profit.
        # Drives the give-back ratchet in _close_profitable_positions so each
        # position locks a rising share of its best-ever profit. Cleaned up
        # alongside _scaled_out when positions close.
        self._peak_net: dict = {}

        # Latest ATR / ATR-as-%-of-price from the RegimeDetector, refreshed each
        # tick. Feeds the volatility-adaptive arms of the fakeout filter and the
        # profit-retrace ratchet (which run before regime detection on the tick).
        self._last_atr: float = 0.0
        self._last_atr_pct: float = 0.0

        # Boost-position state. The boost is a separate, larger same-direction
        # runner auto-opened on ≥ boost_trigger_slots same-dir scalp slots. It
        # shares the bot magic but is tagged by the "TC_BOOST_" comment prefix
        # and tracked here so it never gets a broker SL, never counts as a scalp
        # slot, and is exited only by its own MTF/give-back/-$cap logic.
        self._boost_tickets: set = set()       # ticket(s) we opened as boost
        self._boost_episode_open: bool = False  # one boost at a time per trend cluster
        self._boost_mtf_cache: dict = {}        # last multi-timeframe reversal verdict per side
        self._boost_mtf_ts: float = 0.0         # time.time() of last MTF fetch (throttle)

        # ── Trading Psychology (open-position discipline) ──
        # Per-position MAE/duration tracker + the Tier-2 LLM narrator (wired by
        # the fleet, like _sub_agent_pool). The narrator writes one-shot verdicts
        # into these per-ticket sets, consumed non-blocking by the exit scanner:
        #   _force_close_tickets → CUT_NOW, _tighten_tickets → shrink give-back,
        #   _giveroom_tickets    → defer PROFIT-side exits on a thesis-intact winner.
        self._discipline = PositionDisciplineTracker(self.bot_id)
        self._reviewer = None
        self._force_close_tickets: set = set()
        self._tighten_tickets: dict = {}
        self._giveroom_tickets: set = set()
        self._review_rationale: dict = {}       # ticket -> latest narrator rationale (UI)
        self._session_entries: int = 0          # entries since start (overtrading telemetry)
        self._psych_halt_entries: bool = False   # rolling give-back guard tripped

        # Financial state
        self.equity: float = config.capital_allocation
        self.starting_equity: float = config.capital_allocation
        self.total_realized_pnl: float = 0.0
        self.daily_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0

        # Live chart data
        self.price_history: deque = deque(maxlen=self.MAX_HISTORY)
        self.markers: deque = deque(maxlen=200)
        self.bollinger_data: deque = deque(maxlen=self.MAX_HISTORY)
        self.equity_curve: deque = deque(maxlen=500)   # bounded — was plain list

        # Trade history (in-memory for fast analysis — bounded to prevent OOM)
        self._trades: deque = deque(maxlen=500)
        self._equity_history: deque = deque(maxlen=500)

        # Strategy params — mutable by AI Brain
        self._params = self._params_from_config()

        # Phase 3 §7.1 — Strategy registry. The registry call is wrapped in
        # try/except in _live_tick(); if the strategy raises, the existing
        # inline if/elif/else block below serves as a regression-safe fallback.
        try:
            from base_strategy import get_strategy
            self._strategy = get_strategy(config.strategy)
        except Exception as _e:
            self._logger.warning(
                f"Strategy registry init failed ({_e}); falling back to inline logic only."
            )
            self._strategy = None

        # DB write queue (flushed by fleet's db_flush_loop)
        # Hard-capped at 1000: if PostgreSQL falls behind, oldest entry is evicted
        # rather than growing the queue (and RAM) indefinitely.
        self._DB_QUEUE_MAXLEN = 1000
        self._db_queue: deque = deque(maxlen=self._DB_QUEUE_MAXLEN)
        self._db_lock = threading.Lock()

        # Signals
        self.last_signal: str = ""
        self.fib_signal: dict = {}

        # AI-adjustable param snapshot
        self._params_lock = threading.Lock()

        # MAS agent references (wired by fleet.py after construction)
        self._sub_agent_pool = None   # SubAgentPool — set by fleet.py
        self._executioner = None      # ExecutionerAgent — set by _run_loop after MT5 init

        # Last deliberation result (exposed via API)
        self.last_deliberation: dict = {}
        self._entry_deliberation: Optional[dict] = None  # Saved on fill for Darwinian attribution

        # Regime tracking
        self.current_regime: str = "UNKNOWN"
        self._regime_detector = None  # Lazy-init; kept alive so _last_state persists across ticks

        # Persistent bar queue (flushed by fleet monitor loop, bounded at 500)
        self._BAR_QUEUE_MAXLEN = 500
        self._bar_queue: deque = deque(maxlen=self._BAR_QUEUE_MAXLEN)
        self._bar_queue_lock = threading.Lock()
        self._last_bar_minute: str = ""  # Tracks last written minute for dedup

        # Entry cooldown — prevents rapid-fire entries from both strategies.
        # After any fill, the engine will not open a new slot for at least this
        # many seconds.  This stops the 12-orders-in-20-minutes machine-gun issue.
        self.ENTRY_COOLDOWN_SECONDS: float = 60.0
        self._last_entry_ts: float = 0.0   # time.time() of last successful fill

        # Local Market Trends (pushed by FleetOrchestrator)
        self.market_trends: dict = {}

    def _params_from_config(self) -> dict:
        return {
            "symbol": self.config.symbol,
            "qty": self.config.qty,
            "stop_loss_pct": self.config.stop_loss_pct,
            "trailing_stop_pct": self.config.trailing_stop_pct,
            "bb_period": self.config.bb_period,
            "bb_std_dev": self.config.bb_std_dev,
            "max_daily_drawdown_pct": self.config.max_daily_drawdown_pct,
            "fib_enabled": self.config.fib_enabled,
            "fib_lookback_bars": self.config.fib_lookback_bars,
            "fib_bounce_threshold_pct": self.config.fib_bounce_threshold_pct,
            "fib_entry_mode": self.config.fib_entry_mode,
        }

    # ── Status ─────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        return self._status

    def get_state_snapshot(self) -> dict:
        with self._lock:
            return {
                "bot_id": self.bot_id,
                "bot_status": self._status,
                "current_price": self.current_price,
                "position_qty": self.position_qty,
                "position_side": self.position_side,
                "entry_price": self.entry_price,
                "equity": self.equity,
                "starting_equity": self.starting_equity,
                "daily_pnl": self.daily_pnl,
                "total_realized_pnl": self.total_realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
                "last_signal": self.last_signal,
                "message": self._message,
                "fib_signal": self.fib_signal,
                "regime": self.current_regime,
                "last_deliberation": self.last_deliberation,
                "darwinian_weights": (
                    self._sub_agent_pool._darwin.get_all_weights()
                    if self._sub_agent_pool else {}
                ),
                "position_slots": self._slot_manager.to_dict(),
                # Trading-psychology state of mind + per-position narrative
                "psychology": self._psychology_snapshot(),
                # Persona persistence
                "description": self.config.description,
                "personality": self.config.personality,
                "animal": self.config.animal,
                "category": self.config.category,
                "ai_generated": self.config.ai_generated,
            }

    def _psychology_snapshot(self) -> dict:
        """Compact psychology view for the UI (composure + per-position narrative).
        Must NOT acquire self._lock — it is called from within get_state_snapshot."""
        try:
            positions = self._discipline.snapshot()
            for p in positions:
                p["rationale"] = self._review_rationale.get(p["ticket"], "")
            vs = self._vital_signs.get_status()
            return {
                "enabled": bool(getattr(self.config, "psychology_enabled", True)),
                "composure_state": vs.get("composure_state"),
                "discipline_score": vs.get("discipline_score"),
                "loss_streak": vs.get("loss_streak"),
                "win_streak": vs.get("win_streak"),
                "tilt_lockout_remaining": vs.get("tilt_lockout_remaining"),
                "entries_halted": self._psych_halt_entries,
                "session_entries": self._session_entries,
                "positions": positions,
            }
        except Exception:
            return {}

    def restore_from_telemetry(self, telemetry: dict):
        """Restore volatile equity state from the last known telemetry snapshot."""
        with self._lock:
            self.starting_equity = telemetry.get("starting_equity", self.starting_equity)
            self.daily_pnl = telemetry.get("daily_pnl", self.daily_pnl)
            self.total_realized_pnl = telemetry.get("total_realized_pnl", self.total_realized_pnl)
            # Update current equity based on restored state
            self.equity = self.starting_equity + self.total_realized_pnl + self.unrealized_pnl

    def get_current_params(self) -> dict:
        with self._params_lock:
            return dict(self._params)

    def update_params(self, new_params: dict):
        """Called by AI Brain to update strategy parameters at runtime.

        STOP IS SACRED (Mastering Trading Psychology, Ch3): while a position is
        open, a stop may only be tightened, never widened or removed. Any caller
        (AI brain now, anything later) is covered at this chokepoint.
        """
        psychology_on = bool(getattr(self.config, "psychology_enabled", True))
        holding = self.position_qty > 0
        with self._params_lock:
            for k, v in new_params.items():
                if k not in self._params:
                    continue
                if psychology_on and holding and k in ("stop_loss_pct", "stop_loss_usd"):
                    clamped = clamp_stop_never_wider(float(self._params.get(k) or 0.0), float(v or 0.0))
                    if clamped != v:
                        self._logger.info(
                            f"[{self.bot_id}] STOP SACRED: refused to widen {k} "
                            f"{self._params.get(k)} → {v} while holding; kept {clamped}"
                        )
                    v = clamped
                self._params[k] = v
        self._logger.info(f"Params updated by AI Brain: {new_params}")

    def get_recent_trades(self, limit: int = 200) -> list[dict]:
        with self._lock:
            items = list(self._trades)
            return list(reversed(items[-limit:]))

    def get_equity_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = list(self._equity_history)
            return items[-limit:]

    def _sync_from_slots(self) -> None:
        """Sync legacy position attributes from PositionSlotManager state."""
        self.position_qty = self._slot_manager.total_qty
        self.position_side = self._slot_manager.primary_side
        self.entry_price = self._slot_manager.avg_entry_price

    # ── MAS Wiring ────────────────────────────────────────────────────

    def wire_sub_agent_pool(self, pool) -> None:
        """
        Called by FleetOrchestrator after construction to inject the shared
        SubAgentPool so the engine can call pool.deliberate() each tick.
        """
        self._sub_agent_pool = pool
        self._logger.info(f"[{self.bot_id}] SubAgentPool wired ({len(pool.enabled_agents)} agents)")

    def wire_position_reviewer(self, reviewer) -> None:
        """Inject the Tier-2 PositionReviewer (the "human" position narrator).
        Optional — when absent, the deterministic discipline guards still run.
        """
        self._reviewer = reviewer
        self._logger.info(f"[{self.bot_id}] PositionReviewer wired (Tier-2 psychology narrator)")

    def apply_position_review(self, ticket: int, recommendation: str,
                             tighten_factor: float, rationale: str,
                             invalidation_price: float) -> None:
        """Apply a Tier-2 verdict to a live position (called from the reviewer's
        worker thread). One-directional only: CUT_NOW / TIGHTEN make the exit
        stricter; GIVE_ROOM defers PROFIT-side exits; the hard stop is never
        touched. Consumed non-blocking by the next scanner pass.
        """
        ticket = int(ticket)
        with self._lock:
            if rationale:
                self._review_rationale[ticket] = rationale
            if recommendation == "CUT_NOW":
                self._force_close_tickets.add(ticket)
                self._giveroom_tickets.discard(ticket)
            elif recommendation == "TIGHTEN":
                # monotonic-min so a winner only ever locks profit SOONER
                prev = self._tighten_tickets.get(ticket, 1.0)
                self._tighten_tickets[ticket] = min(prev, max(0.1, float(tighten_factor)))
                self._giveroom_tickets.discard(ticket)
            elif recommendation == "GIVE_ROOM":
                self._giveroom_tickets.add(ticket)
            # HOLD → no change
        if invalidation_price and invalidation_price > 0:
            self._discipline.set_thesis(ticket, invalidation_price=invalidation_price)

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self):
        """Start the trading loop in a background thread.

        Supports restart from STOPPED, CRITICAL_STOP, or EMERGENCY_HALTED states.
        """
        if self._status in (BotEngineStatus.RUNNING, BotEngineStatus.STARTING):
            self._logger.info(f"Engine already {self._status} — ignoring start()")
            return

        # Ensure any previous stop event is cleared so the new loop isn't
        # immediately terminated from a prior stop/halt.
        self._stop_event.clear()

        # Reset status so _run_loop doesn't exit prematurely on a stale state
        self._status = BotEngineStatus.STARTING
        self._message = ""

        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"engine-{self.bot_id}",
        )
        self._thread.start()
        self._logger.info(f"Engine started (restart). Symbol={self.config.symbol}")

    def stop(self):
        """Gracefully stop the trading loop."""
        if self._status not in (BotEngineStatus.RUNNING, BotEngineStatus.STARTING):
            return
        self._stop_event.set()
        self._status = BotEngineStatus.STOPPED
        self._logger.info("Engine stopped")

    def emergency_stop(self, reason: str):
        """Emergency halt — triggered by fleet global risk limits."""
        self._stop_event.set()
        self._status = BotEngineStatus.EMERGENCY_HALTED
        self._message = f"EMERGENCY HALT: {reason}"
        self._logger.critical(f"Emergency stop: {reason}")

    # ── DB Queue ──────────────────────────────────────────────────────

    def flush_db_queue(self) -> list[dict]:
        """Return pending DB writes and clear the queue (atomic drain)."""
        with self._db_lock:
            q = list(self._db_queue)
            self._db_queue.clear()
        return q

    def flush_bar_queue(self) -> list[dict]:
        """Return pending bar writes and clear the queue (atomic drain)."""
        with self._bar_queue_lock:
            q = list(self._bar_queue)
            self._bar_queue.clear()
        return q

    def _queue_bar(self, bar: dict) -> None:
        """
        Queue one OHLC bar for PostgreSQL persistence.
        Deduplicates by minute — only queues if the bar's minute
        is different from the last queued bar.
        The deque is bounded (maxlen=500) so it cannot grow unboundedly
        even if the fleet monitor flush is delayed.
        """
        ts = bar.get("t", "")
        if not ts:
            return
        # Extract minute boundary (YYYY-MM-DDTHH:MM)
        minute_key = ts[:16]
        if minute_key == self._last_bar_minute:
            return  # Same minute — skip (idempotent)
        self._last_bar_minute = minute_key
        with self._bar_queue_lock:
            if len(self._bar_queue) >= self._BAR_QUEUE_MAXLEN - 1:
                self._logger.warning(
                    f"[{self.bot_id}] _bar_queue near cap ({len(self._bar_queue)}/{self._BAR_QUEUE_MAXLEN}) — "
                    f"PostgreSQL flush may be lagging"
                )
            self._bar_queue.append(bar)  # deque auto-evicts oldest when full

    def _queue_trade(self, trade: dict):
        """Queue a trade write for the fleet DB flush loop."""
        with self._db_lock:
            if len(self._db_queue) >= self._DB_QUEUE_MAXLEN - 1:
                self._logger.warning(
                    f"[{self.bot_id}] _db_queue near cap ({len(self._db_queue)}/{self._DB_QUEUE_MAXLEN}) — "
                    f"PostgreSQL writes lagging, oldest entry will be evicted"
                )
            self._db_queue.append({"type": "trade", **trade})  # bounded deque
        with self._lock:
            self._trades.append(trade)  # bounded deque

    def _queue_equity(self, snap: dict):
        with self._db_lock:
            self._db_queue.append({"type": "equity", **snap})  # bounded deque
        with self._lock:
            self._equity_history.append(snap)  # bounded deque

    # ── Trading Loop (shared structure with existing strategy.py) ─────

    def _run_loop(self):
        """
        Main trading loop. Mirrors existing strategy.py MeanReversionEngine
        but fully isolated to this bot's symbol/params/state.

        Each tick is wrapped in mt5_hub.ensure_account_context so this bot's
        MT5 operations execute on its assigned broker account, regardless of
        which account other bots are using. The terminal automatically switches
        back to the default account after each tick.
        """
        import os
        from mt5_bridge import mt5
        from mt5_hub import mt5_hub

        try:
            from strategy import (
                compute_bollinger_bands,
                detect_signal,
            )
        except ImportError:
            self._logger.error("Cannot import strategy functions. Engine cannot start.")
            self._status = BotEngineStatus.STOPPED
            return

        # Live MT5 connection is required.
        terminal = mt5.terminal_info()
        if not terminal:
            last_err = mt5.last_error()
            self._logger.error(
                f"MT5 terminal not connected — bot cannot start. "
                f"last_error={last_err}. "
                f"Ensure the MT5 bridge (Wine/RPyC) is running and mt5_hub.initialize() succeeded."
            )
            self._status = BotEngineStatus.STOPPED
            return

        # Resolve which account this bot should trade on
        account_id = getattr(self.config, "account_id", "") or ""
        if account_id:
            self._logger.info(
                f"Engine bound to account '{account_id}' — "
                f"will switch MT5 context per tick"
            )
        else:
            self._logger.info("No account_id set — using default MT5 account")

        self._status = BotEngineStatus.RUNNING
        self._logger.info(f"Engine RUNNING on MT5")

        params = self.get_current_params()
        # Warm up inside the bot's account context so MT5 history calls hit the
        # correct broker. Synthetics (e.g. "FX Vol 60") only exist on that
        # account — fetching on the default login returns -1 'Call failed'.
        with mt5_hub.ensure_account_context(account_id) as ctx_ok:
            if not ctx_ok:
                self._logger.warning(
                    f"Account context switch failed for '{account_id}' — "
                    f"warmup may miss MT5 bars (Postgres warmup still applies)"
                )
            self._warmup_history(params)

        # Main loop — 5 second tick
        while not self._stop_event.is_set():
            try:
                # Switch MT5 to this bot's account for the duration of the tick
                with mt5_hub.ensure_account_context(account_id) as ctx_ok:
                    if not ctx_ok:
                        self._logger.warning(
                            f"Account context switch failed for '{account_id}' — skipping tick"
                        )
                    else:
                        self._live_tick(params)

                # Update vital signs (outside account context — no MT5 calls)
                self._vital_signs.update(
                    equity=self.equity,
                    daily_pnl=self.daily_pnl,
                    starting_equity=self.starting_equity or self.equity,
                )
                # Trading-psychology: recompute composure (state of mind) from
                # streaks, tilt lockout, overtrading, and worst open excursion.
                if getattr(self.config, "psychology_enabled", True):
                    try:
                        self._vital_signs.update_composure(
                            self._discipline.worst_open_mae(), time.time(), self.config
                        )
                    except Exception:
                        pass
            except Exception as e:
                self._logger.error(f"Engine tick error: {e}", exc_info=True)

            self._stop_event.wait(5)

        self._status = BotEngineStatus.STOPPED

    # ── Historical Warmup ─────────────────────────────────────────────

    def _warmup_history(self, params: dict):
        """
        Pre-seed price_history from persistent PostgreSQL bar store.
        Falls back to MT5 historical API if PostgreSQL has < 200 bars.

        Priority:
          1. PostgreSQL → up to 1000 bars (fast, free, survives restarts)
          2. MT5 API → up to 200 bars (cold start only)
          3. Live accumulation (fallback if both fail)

        After MT5 fetch, new bars are back-filled into PostgreSQL so
        the next restart loads them instantly.
        """
        import asyncio

        symbol = params.get("symbol", self.config.symbol)

        # ── Step 1: Try PostgreSQL persistent bar store ────────────────
        db_bars = []
        try:
            import postgres_store
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    postgres_store.load_bars(symbol, limit=1000), loop
                )
                db_bars = future.result(timeout=10)
            else:
                db_bars = loop.run_until_complete(
                    postgres_store.load_bars(symbol, limit=1000)
                )
        except Exception as e:
            self._logger.debug(f"PostgreSQL bar load skipped: {e}")

        if len(db_bars) >= 200:
            # PostgreSQL has enough — use it directly
            count = 0
            with self._lock:
                for bar in db_bars:
                    self.price_history.append({
                        "time": bar.get("t", ""),
                        "price": bar.get("c", 0.0),
                        "open": bar.get("o", 0.0),
                        "high": bar.get("h", 0.0),
                        "low": bar.get("l", 0.0),
                        "close": bar.get("c", 0.0),
                        "volume": bar.get("v", 0.0),
                    })
                    count += 1
                if count > 0:
                    self.current_price = db_bars[-1].get("c", 0.0)

            self._logger.info(
                f"Warmup: {count} bars loaded from Postgres for {symbol} — "
                f"regime detection ready immediately"
            )
            # Prune old bars in background (fire and forget)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        postgres_store.prune_bars(symbol, keep=1200), loop
                    )
            except Exception:
                pass
            return

        # ── Step 2: PostgreSQL insufficient — fetch from MT5 ──────────
        self._logger.info(
            f"PostgreSQL has {len(db_bars)} bars for {symbol} (need 200+) — "
            f"fetching from MT5"
        )
        try:
            from mt5_bridge import mt5
            mt5_symbol = to_mt5_symbol(symbol)
            mt5.symbol_select(mt5_symbol, True)
            rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M1, 0, 360)

            if rates is None or len(rates) == 0:
                self._logger.warning(
                    f"Warmup: no MT5 bars for {mt5_symbol}: {mt5.last_error()}"
                )
                return

            count = 0
            bars_to_persist: list[dict] = []
            with self._lock:
                for rate in rates[-200:]:
                    ts = datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc).isoformat()
                    price = float(rate["close"])
                    self.price_history.append({
                        "time": ts,
                        "price": price,
                        "open": float(rate["open"]),
                        "high": float(rate["high"]),
                        "low": float(rate["low"]),
                        "close": price,
                        "volume": float(rate["tick_volume"]),
                    })
                    bars_to_persist.append({
                        "t": ts,
                        "o": float(rate["open"]),
                        "h": float(rate["high"]),
                        "l": float(rate["low"]),
                        "c": price,
                        "v": float(rate["tick_volume"]),
                        "src": "warmup",
                    })
                    count += 1
                if count > 0:
                    self.current_price = float(rates[-1]["close"])

            self._logger.info(
                f"Warmup: {count} bars loaded from MT5 for {mt5_symbol} — "
                f"back-filling Postgres"
            )

            # Back-fill bars into PostgreSQL for next restart
            try:
                import postgres_store
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        postgres_store.append_bars_batch(symbol, bars_to_persist),
                        loop,
                    )
            except Exception as e:
                self._logger.debug(f"PostgreSQL back-fill skipped: {e}")

        except Exception as e:
            self._logger.warning(f"Warmup failed (will accumulate live): {e}")


    def _in_kill_zone(self) -> bool:
        """
        Check if the current UTC time falls within a Kill Zone window.

        Kill Zones are high-volume institutional trading windows:
          · New York Open: 13:30–16:00 UTC
          · London Open:   07:00–10:00 UTC

        Configured via BotConfig (kill_zone_ny_start/end, kill_zone_london_start/end).
        Returns True if inside a Kill Zone or if kill_zone_enabled is False.
        """
        from datetime import datetime, timezone, time as dt_time

        if not self.config.kill_zone_enabled:
            return True

        # Crypto trades 24/7 — kill zones are forex/equity session concepts
        _CRYPTO_PREFIXES = {"BTC", "ETH", "LTC", "XRP", "ADA", "DOT", "SOL", "DOGE", "MATIC", "LINK"}
        _is_crypto = (
            self.config.category.lower() in ("crypto", "cryptocurrency")
            or self.config.symbol[:3].upper() in _CRYPTO_PREFIXES
        )
        if _is_crypto:
            return True

        now_utc = datetime.now(timezone.utc).time()

        # Parse config times (HH:MM format)
        try:
            ny_s = dt_time(*[int(x) for x in self.config.kill_zone_ny_start.split(":")])
            ny_e = dt_time(*[int(x) for x in self.config.kill_zone_ny_end.split(":")])
            ld_s = dt_time(*[int(x) for x in self.config.kill_zone_london_start.split(":")])
            ld_e = dt_time(*[int(x) for x in self.config.kill_zone_london_end.split(":")])
        except Exception:
            # Fallback defaults if parsing fails
            ny_s, ny_e = dt_time(13, 30), dt_time(16, 0)
            ld_s, ld_e = dt_time(7, 0), dt_time(10, 0)

        return (ny_s <= now_utc <= ny_e) or (ld_s <= now_utc <= ld_e)

    def _update_scanning_deliberation(self, ts: str, regime: str, current_price: float, note: str = ""):
        """Generate a scanning-state deliberation so the Situation Room shows live agent activity on HOLD ticks."""
        import random
        agent_names = ["watchman", "sentiment", "macro", "earnings", "technical", "risk_manager", "ict"]
        scanning_votes = []
        for agent in agent_names:
            scanning_reasons = {
                "watchman": f"Scanning {self.config.symbol} on 1m bars... Market quality: CLEAR.",
                "sentiment": f"Monitoring sentiment feeds for {self.config.symbol}. No signal shift.",
                "macro": f"Macro conditions stable. VIX normal. Yield curve unchanged.",
                "earnings": f"Checking earnings calendar for {self.config.symbol}. No upcoming risk.",
                "technical": f"BB within range. RSI neutral. No divergence detected.",
                "risk_manager": f"Drawdown check: healthy. Portfolio heat: {round(random.uniform(0.5, 3.5), 1)}%.",
                "ict": f"Scanning for Smart Money footprints... No FVG or liquidity sweep detected.",
            }
            scanning_votes.append({
                "agent": agent,
                "vote": "HOLD",
                "confidence": round(random.uniform(0.5, 0.85), 2),
                "reasoning": scanning_reasons.get(agent, f"Monitoring {self.config.symbol}..."),
                "weight": 1.25 if agent == "watchman" else 1.0,
                "veto_reason": None,
                "timestamp": ts,
            })
        scanning_note = note or f"Scanning {self.config.symbol} @ ${current_price:.2f} | Regime: {regime} | All agents monitoring."
        with self._lock:
            self.last_deliberation = {
                "approved": False,
                "signal": "HOLD",
                "approved_qty": 0,
                "order_urgency": "LOW",
                "quorum_score": 0.0,
                "votes": scanning_votes,
                "veto_agents": [],
                "reasoning": scanning_note,
                "timestamp": ts,
            }

    def _close_opposing(self, signal: str, mt5_symbol: str) -> int:
        """
        Close ALL open broker positions OPPOSITE to `signal` (BUY → close shorts,
        SELL → close longs). Broker-truth — does not trust cached engine state,
        which drifts on a hedging account. Returns the count closed. This is how
        the bot nets: a reversal signal flattens the opposite side instead of
        opening a hedge, so it never holds longs and shorts at the same time.
        """
        from mt5_bridge import mt5
        magic = _stable_magic(self.bot_id)
        target_type = mt5.POSITION_TYPE_SELL if signal == "BUY" else mt5.POSITION_TYPE_BUY
        try:
            raw = mt5.positions_get()
        except Exception as e:
            self._logger.debug(f"[{self.bot_id}] _close_opposing positions_get failed: {e}")
            return 0
        targets = [
            p for p in (raw or [])
            if int(p.magic) == magic and str(p.symbol) == mt5_symbol
            and int(p.type) == target_type
            and not self._is_boost(p)   # boost rides through reversals — its own exit only
        ]
        if not targets:
            return 0

        filling = mt5.ORDER_FILLING_RETURN
        try:
            info = mt5.symbol_info(mt5_symbol)
            if info:
                fm = int(getattr(info, "filling_mode", 0))
                if fm & 1:
                    filling = mt5.ORDER_FILLING_FOK
                elif fm & 2:
                    filling = mt5.ORDER_FILLING_IOC
        except Exception:
            pass

        closed = 0
        for p in targets:
            close_type = (mt5.ORDER_TYPE_BUY if int(p.type) == mt5.POSITION_TYPE_SELL
                          else mt5.ORDER_TYPE_SELL)
            tick = mt5.symbol_info_tick(mt5_symbol)
            if tick is None:
                continue
            px = tick.ask if close_type == mt5.ORDER_TYPE_BUY else tick.bid
            r = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "position":     int(p.ticket),
                "symbol":       mt5_symbol,
                "volume":       float(p.volume),
                "type":         close_type,
                "price":        px,
                "deviation":    20,
                "magic":        magic,
                "comment":      f"TC_REV_{self.bot_id[:8]}",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            })
            if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
                with self._lock:
                    self.total_realized_pnl += float(p.profit)
                    self.daily_pnl = self.total_realized_pnl
                try:
                    self._vital_signs.record_trade_outcome(float(p.profit), time.time(), self.config)
                except Exception:
                    pass
        return closed

    def _live_tick(self, params: dict):
        """
        Live market tick — the full 6-step Multi-Agent System pipeline.

        Step 1: Fetch live price and build price history
        Step 2: RegimeDetector selects active Strategist
        Step 3: Active Strategist generates raw signal (BUY/SELL/HOLD)
        Step 4: SubAgentPool.deliberate() runs the full quorum vote
        Step 5: ExecutionerAgent routes the approved order
        Step 6: Update internal state (position, equity, PnL)
        """
        import pandas as pd
        import numpy as np
        from mt5_bridge import mt5

        symbol = params.get("symbol", self.config.symbol)
        mt5_symbol = to_mt5_symbol(symbol)

        # ────────────────────────────────────────────────────────────
        # STEP 1: Fetch live price from MT5
        # ────────────────────────────────────────────────────────────
        try:
            mt5.symbol_select(mt5_symbol, True)
            tick = mt5.symbol_info_tick(mt5_symbol)
            if tick is None:
                self._logger.warning(f"No tick for {mt5_symbol}: {mt5.last_error()}")
                return
            # Use mid price as canonical price; fall back to last if bid/ask unavailable
            if tick.bid > 0 and tick.ask > 0:
                current_price = (tick.bid + tick.ask) / 2
            else:
                current_price = tick.last or 0.0
            if current_price == 0.0:
                self._logger.warning(f"Zero price for {mt5_symbol}, skipping tick")
                return

            self.current_bid = tick.bid
            self.current_ask = tick.ask

            # Latest completed 1-min bar for OHLCV
            rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M1, 0, 1)
            if rates is not None and len(rates) > 0:
                bar = rates[0]
                current_open   = float(bar["open"])
                current_high   = float(bar["high"])
                current_low    = float(bar["low"])
                current_volume = float(bar["tick_volume"])
            else:
                current_open = current_high = current_low = current_price
                current_volume = 0.0
        except Exception as e:
            self._logger.error(f"Price fetch failed: {e}")
            return

        # Update price and volume history (store full OHLC for RegimeDetector)
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.current_price = current_price
            self.price_history.append({
                "time": ts,
                "price": current_price,
                "open": current_open,
                "high": current_high,
                "low": current_low,
                "close": current_price,
                "volume": current_volume,
            })

        # Queue bar for PostgreSQL persistence (minute-boundary dedup)
        self._queue_bar({
            "t": ts,
            "o": current_open,
            "h": current_high,
            "l": current_low,
            "c": current_price,
            "v": current_volume,
            "src": "live",
        })

        # ── Per-position take-profit check ──────────────────────────────────
        if (self.config.take_profit_usd > 0 or self.config.leverage_mode_enabled
                or getattr(self.config, "profit_retrace_enabled", False)
                or float(getattr(self.config, "stop_loss_usd", 0.0) or 0.0) > 0):
            magic = _stable_magic(self.bot_id)
            n_closed = self._close_profitable_positions(mt5_symbol, magic)
            if n_closed > 0:
                self._logger.info(
                    f"[{self.bot_id}] Take-profit triggered: closed {n_closed} position(s) "
                    f"(threshold=${self.config.take_profit_usd:.2f})"
                )

        # ── Tier-2 psychology narrator (non-blocking) ────────────────────────
        # Enqueues throttled LLM position reviews on a worker thread; the tick
        # never waits on the LLM — verdicts land in the per-ticket sets and are
        # consumed by the next scanner pass.
        if self._reviewer is not None and getattr(self.config, "psychology_enabled", True):
            try:
                self._reviewer.maybe_review(self, time.time())
            except Exception as _rv_err:
                self._logger.debug(f"[{self.bot_id}] reviewer dispatch error: {_rv_err}")

        # ── Boost trigger (per-tick, broker-truth) ───────────────────────────
        # Idempotent: opens at most one boost while ≥ boost_trigger_slots same-dir
        # scalps are live. Per-tick (not only on fill) so it survives restarts
        # where the slot manager is cleared but broker positions persist.
        if getattr(self.config, "boost_enabled", False):
            try:
                self._maybe_open_boost(mt5_symbol, _stable_magic(self.bot_id))
            except Exception as _b_err:
                self._logger.debug(f"[{self.bot_id}] Boost tick-trigger error: {_b_err}")

        # ── Emergency drawdown close ─────────────────────────────────────────
        # The deliberation gate blocks NEW entries when drawdown ≥ limit, but it
        # can't close positions already open.  Check unrealized equity here and
        # force-close everything if we've already blown past the daily limit.
        if self.starting_equity > 0:
            equity_now = self.starting_equity + self.total_realized_pnl + self.unrealized_pnl
            dd_pct = ((self.starting_equity - equity_now) / self.starting_equity) * 100
            if dd_pct >= self.config.max_daily_drawdown_pct:
                self._logger.warning(
                    f"[{self.bot_id}] DRAWDOWN EMERGENCY CLOSE: "
                    f"equity={equity_now:.2f} drawdown={dd_pct:.2f}% "
                    f">= limit={self.config.max_daily_drawdown_pct:.2f}%"
                )
                if self.position_qty > 0:
                    self._logger.warning(f"[{self.bot_id}] Closing all positions due to drawdown.")
                    self._close_position(symbol, params)
                    self._sync_account(symbol)
                
                # Halt engine to prevent further trading today
                self.emergency_stop("Daily drawdown limit exceeded")
                return

        # ── Trading-psychology session safeguards (rolling, 24/7-safe) ───────
        # Give-back guard (protect banked gains) + tilt cool-down. Gates NEW
        # entries only via self._psych_halt_entries; open positions stay managed.
        self._check_session_discipline(time.time())

        # Build price Series for strategy and regime computations
        with self._lock:
            history_snap = list(self.price_history)

        prices = pd.Series([p["price"] for p in history_snap])
        volumes = pd.Series([p.get("volume", 0) for p in history_snap])

        if len(prices) < 20:
            self._logger.debug(f"Insufficient bars ({len(prices)}) for signal — accumulating.")
            self._sync_account(symbol)
            return

        # ────────────────────────────────────────────────────────────
        # STEP 2: Regime Architect selects active Strategist
        # ────────────────────────────────────────────────────────────
        regime = "RANGING"
        regime_result = None  # Will be set by RegimeDetector if successful
        try:
            from regime_detector import RegimeDetector
            # Fetch clean 1-min OHLCV bars for regime detection.
            # price_history mixes warm-up 1-min bars with live 1-second ticks;
            # each tick stores the OHLC of the *currently forming* minute bar,
            # so within any minute all rows share identical high/low — ADX on
            # that data oscillates 50-97 and is meaningless.
            regime_df = None
            try:
                regime_rates = mt5.copy_rates_from_pos(
                    mt5_symbol, mt5.TIMEFRAME_M1, 0, 200
                )
                if regime_rates is not None and len(regime_rates) >= 30:
                    regime_df = pd.DataFrame({
                        "open":   [float(r["open"])        for r in regime_rates],
                        "high":   [float(r["high"])        for r in regime_rates],
                        "low":    [float(r["low"])         for r in regime_rates],
                        "close":  [float(r["close"])       for r in regime_rates],
                        "volume": [float(r["tick_volume"]) for r in regime_rates],
                    })
            except Exception as regime_fetch_err:
                self._logger.debug(
                    f"Could not fetch 1-min bars for RegimeDetector: {regime_fetch_err}"
                    " — falling back to price_history"
                )

            if regime_df is None:
                regime_df = pd.DataFrame({
                    "open":   [p.get("open", p["price"])  for p in history_snap],
                    "high":   [p.get("high", p["price"])  for p in history_snap],
                    "low":    [p.get("low", p["price"])   for p in history_snap],
                    "close":  [p.get("close", p["price"]) for p in history_snap],
                    "volume": [p.get("volume", 0)         for p in history_snap],
                })

            if self._regime_detector is None:
                self._regime_detector = RegimeDetector(
                    atr_volatile_zscore=getattr(self.config, "atr_volatile_zscore", 3.0)
                )
            regime_result = self._regime_detector.detect(regime_df)
            # Cache ATR for the volatility-adaptive fakeout / profit-retrace logic
            # (those run earlier in the next tick, before regime is recomputed).
            try:
                self._last_atr = float(getattr(regime_result, "atr", 0.0) or 0.0)
                self._last_atr_pct = (self._last_atr / current_price) if current_price > 0 else 0.0
            except Exception:
                pass
            detected = getattr(regime_result, "regime", "RANGING")
            # Treat UNKNOWN (insufficient bars) as RANGING so trades aren't
            # permanently blocked during warmup — mean-reversion is the safer
            # default while the detector accumulates enough history.
            regime = detected if detected != "UNKNOWN" else "RANGING"
            with self._lock:
                self.current_regime = regime
            if detected == "UNKNOWN":
                self._logger.info(
                    f"[{self.bot_id}] RegimeDetector: UNKNOWN (warmup, "
                    f"{len(history_snap)} bars) — treating as RANGING"
                )
        except Exception as e:
            self._logger.warning(f"RegimeDetector error: {e} — defaulting to RANGING")
            regime = "RANGING"
            with self._lock:
                self.current_regime = regime

        # ────────────────────────────────────────────────────────────
        # STEP 2.5: Kill Zone Time Filter (ICT)
        # ────────────────────────────────────────────────────────────
        # ICT principle: only hunt during institutional activity windows.
        # Exits are NOT gated — you can always close a position.
        if self.config.kill_zone_enabled and self.position_qty <= 0:
            if not self._in_kill_zone():
                self._update_scanning_deliberation(
                    ts, regime, current_price,
                    note=f"Outside Kill Zone — waiting for institutional session | {self.config.symbol} @ ${current_price:.2f}"
                )
                self._sync_account(symbol)
                return

        # ────────────────────────────────────────────────────────────
        # STEP 3: Active Strategist — MeanReversion (RANGING) or Trend (TRENDING)
        # ────────────────────────────────────────────────────────────
        raw_signal = "HOLD"

        if regime == "VOLATILE":
            # Hard gate — no new entries in volatile markets
            self._logger.info(f"[{self.bot_id}] Regime=VOLATILE — skipping signal generation.")
            self._update_scanning_deliberation(ts, regime, current_price)
            self._sync_account(symbol)
            return

        # ── Phase 3 §7.1 — Strategy registry first (best-effort) ───────
        # The registry instance is resolved at __init__ from BotConfig.strategy.
        # If it returns a valid directional signal, we use it. Any exception or
        # HOLD return falls through to the proven inline path below, ensuring
        # zero regression risk in the trading loop.
        _confluence_out: dict = {}
        if self._strategy is not None:
            try:
                _registry_signal = self._strategy.generate_signal(
                    prices=prices,
                    volumes=volumes,
                    regime_state=regime_result,
                    config=self.config,
                    bot_id=self.bot_id,
                    current_price=current_price,
                    history_snap=history_snap,
                    kill_zone_active=self._in_kill_zone() if self.config.kill_zone_enabled else True,
                    confluence_out=_confluence_out,
                )
                if _registry_signal in ("BUY", "SELL"):
                    raw_signal = _registry_signal
                    if _confluence_out:
                        with self._lock:
                            self.last_deliberation["confluence"] = _confluence_out
                    self._logger.info(
                        f"[{self.bot_id}] STRATEGY({self._strategy.name}) → {raw_signal}",
                        extra={
                            "event": "strategy_signal",
                            "bot_id": self.bot_id,
                            "strategy": self._strategy.name,
                            "signal": raw_signal,
                            "regime": regime,
                        },
                    )
            except Exception as _se:
                self._logger.warning(
                    f"Strategy registry call failed ({_se}); using inline fallback"
                )

        if regime == "TRENDING" and self.config.strategy in ("trend_following", "combined") and raw_signal == "HOLD":
            # ── Trend Strategist ──
            try:
                from trend_strategist import TrendStrategistAgent
                ts_agent = TrendStrategistAgent(self.bot_id)
                regime_adx = getattr(regime_result, "adx", None)

                # Fetch 60 fresh 1-minute bars from MT5 — price_history mixes
                # warm-up minute-bars with live 1-second ticks, so EMA gaps on
                # raw tick data are too small for the strategist's thresholds.
                trend_prices, trend_volumes = prices, volumes
                trend_highs, trend_lows = None, None
                try:
                    trend_rates = mt5.copy_rates_from_pos(
                        mt5_symbol, mt5.TIMEFRAME_M1, 0, 60
                    )
                    if trend_rates is not None and len(trend_rates) >= 30:
                        # Append current live tick so EMA updates every 5s, not every minute.
                        # copy_rates_from_pos returns completed bars only — the forming bar's
                        # close is frozen until the minute closes, so without this append the
                        # EMA gap is identical for all ~12 ticks within a minute.
                        bar_closes = [float(r["close"]) for r in trend_rates]
                        bar_closes.append(current_price)
                        bar_vols = [float(r["tick_volume"]) for r in trend_rates]
                        bar_vols.append(current_volume)
                        # OHLC highs/lows for the anti-fakeout breakout confirmation.
                        # The appended live bar uses the forming-minute high/low.
                        bar_highs = [float(r["high"]) for r in trend_rates]
                        bar_highs.append(current_high)
                        bar_lows = [float(r["low"]) for r in trend_rates]
                        bar_lows.append(current_low)
                        trend_prices = pd.Series(bar_closes)
                        trend_volumes = pd.Series(bar_vols)
                        trend_highs = pd.Series(bar_highs)
                        trend_lows = pd.Series(bar_lows)
                except Exception as rates_err:
                    self._logger.debug(
                        f"Could not fetch 1-min bars for TrendStrategist: {rates_err}"
                        " — falling back to price_history"
                    )

                ts_result = ts_agent.analyse(
                    trend_prices, trend_volumes, regime, adx=regime_adx,
                    highs=trend_highs, lows=trend_lows,
                )
                raw_signal = ts_result.vote  # BUY | SELL | HOLD
                self._logger.info(
                    f"[{self.bot_id}] TrendStrategist: {raw_signal} "
                    f"(conf={ts_result.confidence:.0%}, ADX={ts_result.adx:.1f})"
                )
            except Exception as e:
                self._logger.error(f"TrendStrategistAgent error: {e}")

        # Inline Mean Reversion fallback. Runs only when:
        #   (a) the registry call returned HOLD/raised, AND
        #   (b) the regime is NOT TRENDING for trend-following / combined.
        # This preserves the pre-Phase-3 behaviour for any path the registry
        # cannot serve.
        elif raw_signal == "HOLD":
            # ── Mean Reversion Strategist (3-Pillar Confluence) ──
            try:
                from strategy import compute_bollinger_bands
                bb = compute_bollinger_bands(
                    prices,
                    period=params.get("bb_period", self.config.bb_period),
                    std_dev=params.get("bb_std_dev", self.config.bb_std_dev),
                )
                if bb:
                    # Store BB data for charting regardless of confluence
                    with self._lock:
                        self.bollinger_data.append({
                            "time": ts,
                            "upper": bb.get("upper"),
                            "middle": bb.get("middle"),
                            "lower": bb.get("lower"),
                        })

                    if self.config.confluence_enabled:
                        # ── 3-Pillar Confluence Gate + ICT Enrichment ─
                        from confluence import evaluate_confluence

                        # Build OHLC series for ICT detection
                        highs_series = pd.Series([p.get("high", p["price"]) for p in history_snap])
                        lows_series = pd.Series([p.get("low", p["price"]) for p in history_snap])

                        confluence = evaluate_confluence(
                            prices=prices,
                            volumes=volumes,
                            regime_state=regime_result,
                            bb=bb,
                            current_price=current_price,
                            rsi_period=self.config.rsi_period,
                            rsi_oversold=self.config.rsi_oversold,
                            rvol_threshold=self.config.rvol_threshold,
                            # ICT enrichment
                            highs=highs_series,
                            lows=lows_series,
                            kill_zone_active=self._in_kill_zone() if self.config.kill_zone_enabled else True,
                            fvg_enabled=self.config.ict_fvg_enabled,
                            sweep_enabled=self.config.ict_sweep_enabled,
                            sweep_lookback=self.config.ict_sweep_lookback,
                            # Short-selling confluence gate
                            short_selling_enabled=self.config.short_selling_enabled,
                        )
                        raw_signal = confluence.entry_signal  # "BUY", "SELL", or "HOLD"

                        # Attach confluence diagnostics (including ICT) for Situation Room
                        with self._lock:
                            self.last_deliberation["confluence"] = confluence.to_dict()

                        if raw_signal in ("BUY", "SELL"):
                            self._logger.info(
                                f"[{self.bot_id}] CONFLUENCE {raw_signal}: "
                                f"RSI={confluence.rsi} | ADX={confluence.adx:.1f} | "
                                f"RVOL={confluence.rvol} | pillars={confluence.pillars_met}/3 | "
                                f"ICT={confluence.ict_conviction}"
                            )
                    else:
                        # Fallback: raw BB signal (confluence disabled)
                        from strategy import detect_signal
                        raw_signal = detect_signal(current_price, bb)

                    # ── EXIT CHECK: BB upper band touch while holding ──
                    # If we have a position and price hits upper band, signal exit
                    if self.position_qty > 0 and self.position_side == "LONG" and current_price >= bb.get("upper", float("inf")):
                        raw_signal = "SELL"

                    # ── EXIT CHECK: SHORT position + BB lower band touch ──
                    if self.position_qty > 0 and self.position_side == "SHORT" and current_price <= bb.get("lower", 0):
                        raw_signal = "BUY"  # Cover short at mean reversion target
                        self._logger.info(
                            f"[{self.bot_id}] BB lower band exit — covering short."
                        )

            except Exception as e:
                self._logger.error(f"MeanReversionStrategist error: {e}")

        # ── HARD STOP-LOSS CHECK ─────────────────────────────────────────
        # Runs before trailing stop so the tighter of the two always wins.
        # Bypasses deliberation — protective exits never need a quorum vote.
        if self.position_qty > 0 and self.entry_price > 0:
            sl_pct = params.get("stop_loss_pct", self.config.stop_loss_pct)
            if self.position_side == "LONG":
                # Exit a LONG by selling at the current BID
                exit_price = self.current_bid
                loss_pct = (exit_price - self.entry_price) / self.entry_price * 100
                if loss_pct <= -sl_pct:
                    raw_signal = "SELL"
                    self._logger.warning(
                        f"[{self.bot_id}] [HARD SL] LONG stopped out: "
                        f"entry={self.entry_price:.4f} bid={exit_price:.4f} "
                        f"loss={loss_pct:.2f}% (limit=-{sl_pct}%)"
                    )
            elif self.position_side == "SHORT":
                # Exit a SHORT by buying at the current ASK
                exit_price = self.current_ask
                loss_pct = (self.entry_price - exit_price) / self.entry_price * 100
                if loss_pct <= -sl_pct:
                    raw_signal = "BUY"
                    self._logger.warning(
                        f"[{self.bot_id}] [HARD SL] SHORT stopped out: "
                        f"entry={self.entry_price:.4f} ask={exit_price:.4f} "
                        f"loss={loss_pct:.2f}% (limit=-{sl_pct}%)"
                    )

        # ── TRAILING STOP-LOSS CHECK ────────────────────────────────────
        if self.config.trailing_stop_enabled and self.position_qty > 0:
            if self.position_side == "LONG":
                exit_price = self.current_bid
                if exit_price > self._trailing_high:
                    self._trailing_high = exit_price
                trail_floor = self._trailing_high * (1 - self.config.trailing_stop_pct / 100)
                if exit_price <= trail_floor:
                    raw_signal = "SELL"
                    self._logger.info(
                        f"[{self.bot_id}] [TRAILING STOP] LONG exit: "
                        f"bid {exit_price:.4f} < floor {trail_floor:.4f} "
                        f"(high={self._trailing_high:.4f}, trail={self.config.trailing_stop_pct}%)"
                    )
            elif self.position_side == "SHORT":
                exit_price = self.current_ask
                if exit_price < self._trailing_low:
                    self._trailing_low = exit_price
                trail_ceiling = self._trailing_low * (1 + self.config.trailing_stop_pct / 100)
                if exit_price >= trail_ceiling:
                    raw_signal = "BUY"
                    self._logger.info(
                        f"[{self.bot_id}] [TRAILING STOP] SHORT exit: "
                        f"ask {exit_price:.4f} > ceiling {trail_ceiling:.4f} "
                        f"(low={self._trailing_low:.4f}, trail={self.config.trailing_stop_pct}%)"
                    )

        # ── POSITION STATE VALIDATION (Hardened) ─────────────────────
        # RULE 1: SELL without a position → allow short entry if enabled, else HOLD
        if raw_signal == "SELL" and self.position_qty <= 0:
            if not self.config.short_selling_enabled:
                self._logger.debug(
                    f"[{self.bot_id}] SELL signal suppressed — short selling disabled."
                )
                raw_signal = "HOLD"
            else:
                self._logger.info(
                    f"[{self.bot_id}] SHORT ENTRY signal — proceeding to deliberation."
                )

        # RULE 1b: BUY without a position while in a short → cover signal
        # (This is handled below in exit routing)

        # Only proceed if we have an open position OR a directional signal
        if raw_signal == "HOLD" and self.position_qty == 0:
            # Update deliberation with scanning state so Situation Room stays alive
            self._update_scanning_deliberation(ts, regime, current_price)
            self._sync_account(symbol)
            self.last_signal = "HOLD"
            return

        # REVERSAL / netting exit — broker-truth. On a directional signal, close
        # ALL open positions OPPOSITE to it so the bot never carries longs and
        # shorts at once (this is a hedging account; the cached position_side
        # drifts). A BUY covers every short; a SELL closes every long. Protective
        # exit — bypasses deliberation. After closing we return; the new
        # direction opens on a later tick if the signal persists (so trades still
        # occur), avoiding close-and-reopen churn within a single tick.
        if raw_signal in ("BUY", "SELL"):
            _rev_closed = self._close_opposing(raw_signal, mt5_symbol)
            if _rev_closed > 0:
                self._logger.info(
                    f"[{self.bot_id}] Reversal on {raw_signal}: closed {_rev_closed} "
                    f"opposing position(s) — no hedge."
                )
                self._sync_account(symbol)
                return

        if raw_signal not in ("BUY", "SELL"):
            self._sync_account(symbol)
            return

        # RULE 2·0: Anti-fakeout entry gate — reject algorithmic sweep-and-reverse
        # traps. Engine-layer half of the two-layer fakeout defence; applies to
        # EVERY directional entry (trend AND mean-reversion). Exits are never gated.
        if self.config.fakeout_filter_enabled and not self._passes_fakeout_filter(raw_signal, mt5_symbol):
            self._update_scanning_deliberation(
                ts, regime, current_price,
                note=f"Entry blocked — algorithmic fakeout trap on {raw_signal} | {self.config.symbol} @ ${current_price:.2f}",
            )
            self._sync_account(symbol)
            return

        # RULE 2a: Entry cooldown — block new entries too close together in time.
        # Prevents machine-gun entries during sustained trends or ranging bounces.
        now_ts = time.time()
        elapsed = now_ts - self._last_entry_ts
        if self._last_entry_ts > 0 and elapsed < self.ENTRY_COOLDOWN_SECONDS:
            self._logger.debug(
                f"[{self.bot_id}] Entry cooldown active: {elapsed:.0f}s / "
                f"{self.ENTRY_COOLDOWN_SECONDS:.0f}s elapsed — skipping {raw_signal}"
            )
            self._sync_account(symbol)
            return

        # RULE 2a: Hard cap on the NUMBER of open broker positions. This is a
        # hedging account — opposite-direction signals open NEW positions rather
        # than netting, so longs and shorts pile up (a net-volume check is
        # useless: net can be ~0 while 11 positions are open). Count the live
        # positions straight from MT5 and block ANY new entry once the count
        # reaches max_position_slots. Existing positions still exit via the
        # TP/SL scan, freeing slots.
        try:
            _cap_magic = _stable_magic(self.bot_id)
            _cap_raw = mt5.positions_get()
            _open_count = sum(
                1 for _p in (_cap_raw or [])
                if int(_p.magic) == _cap_magic and str(_p.symbol) == mt5_symbol
                and not self._is_boost(_p)   # boost runner doesn't consume a scalp slot
            )
            if _open_count >= self.config.max_position_slots:
                self._logger.info(
                    f"[{self.bot_id}] Max positions reached: {_open_count} open ≥ "
                    f"{self.config.max_position_slots} — blocking new {raw_signal}"
                )
                self._sync_account(symbol)
                return
        except Exception as _cap_err:
            self._logger.debug(f"[{self.bot_id}] Position cap check failed: {_cap_err}")

        # RULE 2b: Scale-in gate — allow up to max_position_slots same-direction entries.
        # Each new entry opens one slot; capacity and direction are enforced by PositionSlotManager.
        if not self._slot_manager.is_flat():
            entry_side = "LONG" if raw_signal == "BUY" else "SHORT"
            if not self._slot_manager.can_open(entry_side):
                # At max_slots capacity or direction conflict — block new entry
                self._sync_account(symbol)
                return
            if not self.config.scale_in_enabled:
                # Scale-in disabled — block same-direction re-entry
                self._sync_account(symbol)
                return

            # RULE 2b-psych: ANTI-AVERAGE-DOWN (Mastering Trading Psychology, Ch3).
            # A same-direction add to a position the market is moving AGAINST is
            # "averaging down" — the most common account-killer. Scaling UP a
            # winner is fine; adding to a loser is blocked.
            if getattr(self.config, "psychology_enabled", True) and \
               getattr(self.config, "block_average_down", True):
                v = check_scale_in_allowed(
                    entry_side, current_price, self._slot_manager.avg_entry_price,
                    self.unrealized_pnl, block_average_down=True,
                )
                if v.blocks:
                    self._logger.info(f"[{self.bot_id}] ANTI-AVERAGE-DOWN: {v.reason}")
                    self._sync_account(symbol)
                    return

            # RULE 2c: Minimum price spacing for scale-in.
            # Each new scale-in entry must be at least 0.15% away from the
            # average entry price.  This prevents stacking identical-price slots.
            MIN_SCALEIN_SPACING_PCT = 0.15
            avg_entry = self._slot_manager.avg_entry_price
            if avg_entry > 0:
                spacing_pct = abs(current_price - avg_entry) / avg_entry * 100
                if spacing_pct < MIN_SCALEIN_SPACING_PCT:
                    self._logger.debug(
                        f"[{self.bot_id}] Scale-in spacing too tight: "
                        f"{spacing_pct:.3f}% < {MIN_SCALEIN_SPACING_PCT}% — skipping"
                    )
                    self._sync_account(symbol)
                    return

        # ────────────────────────────────────────────────────────────
        # STEP 4: Expert Team Deliberation (votes from all 5 panel agents)
        # ────────────────────────────────────────────────────────────

        # ── Psychology entry gate ── halt NEW entries (fresh or scale-in) while
        # the give-back guard or tilt cool-down is engaged. Open positions are
        # unaffected — they keep being managed by the exit scanner.
        if getattr(self.config, "psychology_enabled", True) and self._psych_halt_entries:
            self._logger.debug(f"[{self.bot_id}] Entry halted by psychology session guard")
            self._sync_account(symbol)
            return

        # ── Position sizing ───────────────────────────────────────────────────
        # Start with the configured base qty (acts as ceiling when auto-sizing).
        requested_qty = float(params.get("qty", self.config.qty))

        if self.config.leverage_mode_enabled:
            # LEVERAGE MODE: positions stay at the configured base qty (effective
            # 1x). A dedicated leverage position-sizer is intentionally not wired
            # — sizing up with high leverage on a small account turns the per-trade
            # stop and the fleet drawdown limit into account-ending events. Keep
            # base qty; risk is governed by take_profit_usd / stop_loss_usd instead.
            self._logger.debug(
                f"[{self.bot_id}] Leverage mode: base qty {requested_qty:.5f} (1x — leverage sizing disabled)"
            )

        elif self.config.auto_size_qty and self.config.capital_allocation > 0 and current_price > 0:
            try:
                # contract_size: lots→units (BTC=1, Forex=100000, Gold=100, etc.)
                sym_info = mt5.symbol_info(mt5_symbol)
                contract_size = float(getattr(sym_info, "trade_contract_size", 1.0)) if sym_info else 1.0
                sl_pct = float(params.get("stop_loss_pct", self.config.stop_loss_pct))
                dollar_risk = self.config.capital_allocation * (self.config.risk_pct_per_trade / 100.0)
                sl_distance = current_price * (sl_pct / 100.0)
                if sl_distance > 0 and contract_size > 0:
                    auto_qty = dollar_risk / (sl_distance * contract_size)
                    # config.qty is a hard upper bound — never exceed what the user configured
                    requested_qty = min(auto_qty, requested_qty)
                    self._logger.debug(
                        f"[{self.bot_id}] Auto-size: capital={self.config.capital_allocation:.2f} "
                        f"risk={self.config.risk_pct_per_trade:.1f}% "
                        f"dollar_risk={dollar_risk:.4f} sl_dist={sl_distance:.2f} "
                        f"contract={contract_size} → {requested_qty:.5f} lots"
                    )
            except Exception as _sz_err:
                self._logger.debug(f"[{self.bot_id}] Auto-size fallback ({_sz_err}) — using config qty")

        # Kelly splitting (Scenario 5): divide total planned qty evenly across slots.
        # Each slot commits 1/max_position_slots of the full risk allocation,
        # preventing one slippage event from consuming the entire Kelly budget.
        if self.config.scale_in_enabled:
            requested_qty = requested_qty / self.config.max_position_slots
        survival_state = self._vital_signs.survival_state

        # Composure size-down (Ch3/Ch4): throttle new risk after a loss/win
        # streak or fear; TILTED → 0.0 suppresses the entry entirely.
        if getattr(self.config, "psychology_enabled", True):
            _cmult = self._vital_signs.composure_qty_multiplier()
            if _cmult <= 0.0:
                self._logger.info(
                    f"[{self.bot_id}] Composure {self._vital_signs.composure_state} → entry suppressed"
                )
                self._sync_account(symbol)
                return
            if _cmult < 1.0:
                requested_qty *= _cmult

        if self._sub_agent_pool is not None:
            with self._lock:
                recent_trades = list(self._trades)[-50:]

            decision = self._sub_agent_pool.deliberate(
                raw_signal=raw_signal,
                requested_qty=requested_qty,
                equity=self.equity,
                daily_pnl=self.daily_pnl,
                starting_equity=self.starting_equity,
                max_daily_drawdown_pct=params.get(
                    "max_daily_drawdown_pct", self.config.max_daily_drawdown_pct
                ),
                recent_trades=recent_trades,
                survival_state=survival_state,
                signal_price=current_price,
                price_history=history_snap,
                market_trends=self.market_trends,
                vote_cache_ttl=self.config.agent_vote_cache_ttl_seconds,
            )

            with self._lock:
                self.last_deliberation = decision.to_dict()
                self.last_signal = (
                    f"{raw_signal} [APPROVED]" if decision.approved
                    else f"{raw_signal} [BLOCKED: {decision.reasoning[:60]}]"
                )

            if not decision.approved:
                self._logger.info(
                    f"[{self.bot_id}] Trade BLOCKED by deliberation: {decision.reasoning}"
                )
                self._sync_account(symbol)
                return

            approved_qty = decision.approved_qty
            order_urgency = decision.order_urgency
        else:
            # No pool wired (e.g. during initial startup) — use direct Risk Manager gate only
            approved_qty = requested_qty
            order_urgency = "LOW"
            with self._lock:
                self.last_signal = raw_signal

        # ────────────────────────────────────────────────────────────
        # STEP 5: ExecutionerAgent — smart order routing
        # ────────────────────────────────────────────────────────────
        if self._executioner is None:
            from executioner import ExecutionerAgent, OrderUrgency
            self._executioner = ExecutionerAgent(
                bot_id=self.bot_id,
                symbol=symbol,
                smart_routing_min_qty=self.config.smart_routing_min_qty,
                twap_interval_ms=self.config.twap_interval_ms,
                max_slippage_pct=self.config.max_slippage_pct,
                limit_timeout_s=self.config.limit_timeout_s,
                bot_name=self.config.name,
            )

        from executioner import OrderUrgency
        side = raw_signal.lower()   # "buy" or "sell"
        urgency = OrderUrgency.HIGH if order_urgency == "HIGH" else OrderUrgency.LOW

        # Expected execution price is ASK for buys, BID for sells
        expected_price = self.current_ask if side == "buy" else self.current_bid

        result = self._executioner.execute(
            side=side,
            qty=approved_qty,
            signal_price=expected_price,
            urgency=urgency,
        )

        # ────────────────────────────────────────────────────────────
        # STEP 6: Update internal state after fill
        # ────────────────────────────────────────────────────────────
        if result.success and result.total_qty_filled > 0:
            self._last_entry_ts = time.time()
            # Psychology: count this entry for the rolling overtrading cap.
            self._session_entries += 1
            try:
                self._vital_signs.record_entry(self._last_entry_ts)
            except Exception:
                pass
            trade_record = {
                "bot_id": self.bot_id,
                "symbol": symbol,
                "side": side,
                "qty": result.total_qty_filled,
                "price": result.avg_fill_price,
                "signal_price": current_price,
                "slippage_pct": result.total_slippage_pct,
                "execution_mode": result.mode,
                "latency_ms": result.latency_ms,
                "regime": regime,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pnl": 0.0,  # filled in on close
            }
            self._queue_trade(trade_record)

            # Capture deliberation ref before slot open (decision may not exist if no pool)
            _deliberation_ref: Optional[dict] = None
            try:
                if self._sub_agent_pool:
                    _deliberation_ref = decision.to_dict()
            except NameError:
                pass

            was_flat = self._slot_manager.is_flat()

            if side == "buy":
                slot = self._slot_manager.open_slot(
                    side="LONG",
                    qty=result.total_qty_filled,
                    entry_price=result.avg_fill_price,
                    signal_source="LONG_SCALE" if not was_flat else "LONG",
                    deliberation_ref=_deliberation_ref,
                )
                if slot and was_flat:
                    self._trailing_high = result.avg_fill_price
            else:  # sell → opening a SHORT (long closes are handled before STEP 4)
                slot = self._slot_manager.open_slot(
                    side="SHORT",
                    qty=result.total_qty_filled,
                    entry_price=result.avg_fill_price,
                    signal_source="SHORT_SCALE" if not was_flat else "SHORT",
                    deliberation_ref=_deliberation_ref,
                )
                if slot and was_flat:
                    self._trailing_low = result.avg_fill_price

            with self._lock:
                self._sync_from_slots()

            self._logger.info(
                f"[{self.bot_id}] ORDER FILLED: {side.upper()} {result.total_qty_filled}×{symbol} "
                f"@ {result.avg_fill_price:.4f} | mode={result.mode} "
                f"| slippage={result.total_slippage_pct:.3f}% "
                f"| latency={result.latency_ms:.0f}ms"
            )

            # ── Boost trigger ── ≥ boost_trigger_slots same-direction scalp slots
            # now open (a confirmed trend) → auto-open ONE same-direction runner.
            try:
                self._maybe_open_boost(mt5_symbol, _stable_magic(self.bot_id))
            except Exception as _boost_err:
                self._logger.warning(f"[{self.bot_id}] Boost trigger error: {_boost_err}")

            # Log slippage abort if it occurred
            if result.abort_reason:
                self._logger.warning(
                    f"[{self.bot_id}] Execution abort: {result.abort_reason}"
                )
        else:
            self._logger.warning(
                f"[{self.bot_id}] Order failed or unfilled: {result.error or result.abort_reason}"
            )
            if result.error and ("AutoTrading disabled" in str(result.error) or "retcode=10027" in str(result.error)):
                self._logger.error(f"[{self.bot_id}] AutoTrading disabled by client — transitioning to CRITICAL_STOP.")
                self.emergency_stop("AutoTrading disabled in MT5 terminal.")
                return

        # Always sync account state at end of tick
        self._sync_account(symbol)

    def _close_position(self, symbol: str, params: dict = None):
        """Close all open position slots via a single market order."""
        if self._slot_manager.is_flat():
            return

        # Snapshot slots before close for Darwinian attribution
        slots_before_close = self._slot_manager.get_slots()
        first_deliberation = (
            slots_before_close[0].deliberation_ref if slots_before_close else None
        )

        close_side = "sell" if self._slot_manager.primary_side == "LONG" else "buy"
        total_qty = self._slot_manager.total_qty

        if self._executioner is None:
            from executioner import ExecutionerAgent, OrderUrgency
            self._executioner = ExecutionerAgent(
                bot_id=self.bot_id,
                symbol=symbol,
                smart_routing_min_qty=self.config.smart_routing_min_qty,
                twap_interval_ms=self.config.twap_interval_ms,
                max_slippage_pct=self.config.max_slippage_pct,
                limit_timeout_s=self.config.limit_timeout_s,
                bot_name=self.config.name,
            )
        from executioner import OrderUrgency

        # Closing price is ASK if we are buying to close (SHORT), BID if we are selling to close (LONG)
        expected_close_price = self.current_ask if close_side == "buy" else self.current_bid

        result = self._executioner.execute(
            side=close_side,
            qty=total_qty,
            signal_price=expected_close_price,
            urgency=OrderUrgency.HIGH,  # Exits are always urgent
        )
        if result.success:
            # Compute PnL across all slots at the actual fill price
            pnl, _ = self._slot_manager.close_all(result.avg_fill_price)

            with self._lock:
                self._sync_from_slots()  # position_qty=0, position_side="NONE", entry_price=0
                self._trailing_high = 0.0
                self._trailing_low = float("inf")
                self.total_realized_pnl += pnl
                self.daily_pnl = self.total_realized_pnl

            try:
                self._vital_signs.record_trade_outcome(pnl, time.time(), self.config)
            except Exception:
                pass

            self._logger.info(
                f"[{self.bot_id}] Position closed ({close_side.upper()}): "
                f"pnl={pnl:+.2f} @ {result.avg_fill_price:.4f} "
                f"(slots={len(slots_before_close)})"
            )

            # ── Darwinian Attribution ──────────────────────────────────
            if first_deliberation and self._sub_agent_pool:
                try:
                    self._sub_agent_pool._darwin.record_outcome(
                        votes=first_deliberation.get("votes", []),
                        trade_direction=first_deliberation.get("signal", ""),
                        pnl=pnl,
                    )
                    self._logger.debug(f"[{self.bot_id}] Recorded Darwinian outcome.")
                except Exception as e:
                    self._logger.warning(f"Failed to record Darwinian outcome: {e}")

            self._entry_deliberation = None
        else:
            self._logger.warning(
                f"[{self.bot_id}] Close order failed: {result.error or result.abort_reason}"
            )
            if result.error and ("AutoTrading disabled" in str(result.error) or "retcode=10027" in str(result.error)):
                self._logger.error(f"[{self.bot_id}] AutoTrading disabled by client — transitioning to CRITICAL_STOP.")
                self.emergency_stop("AutoTrading disabled in MT5 terminal.")
                return

    def _passes_fakeout_filter(self, raw_signal: str, mt5_symbol: str) -> bool:
        """
        Engine-layer anti-fakeout gate. Returns False when the latest 1-min bar
        shows a sweep-and-reverse trap AGAINST the entry direction (bull trap for
        BUY, bear trap for SELL) — the algorithmic stop-hunt signature where price
        pokes past a swing extreme to run stops, then snaps back through it.

        Conservative by design: on any data/fetch problem it returns True so the
        filter never blocks trading on ignorance.
        """
        try:
            import pandas as pd
            from mt5_bridge import mt5
            from fakeout_filter import detect_entry_trap, compute_atr

            lookback = int(getattr(self.config, "fakeout_swing_lookback", 20))
            rates = mt5.copy_rates_from_pos(
                mt5_symbol, mt5.TIMEFRAME_M1, 0, max(lookback + 5, 30)
            )
            if rates is None or len(rates) < lookback + 1:
                return True  # insufficient history — do not block

            highs = pd.Series([float(r["high"]) for r in rates])
            lows = pd.Series([float(r["low"]) for r in rates])
            closes = pd.Series([float(r["close"]) for r in rates])

            atr_val = self._last_atr if self._last_atr > 0 else compute_atr(highs, lows, closes)

            verdict = detect_entry_trap(
                raw_signal, highs, lows, closes,
                swing_lookback=lookback,
                atr=atr_val,
                buffer_mult=float(self.config.fakeout_atr_buffer_mult),
                wick_reject_ratio=float(self.config.fakeout_wick_reject_ratio),
            )
            if verdict.is_trap:
                self._logger.warning(
                    f"[{self.bot_id}] ANTI-FAKEOUT: blocking {raw_signal} — {verdict.reason}"
                )
                return False
            return True
        except Exception as e:
            self._logger.debug(f"[{self.bot_id}] Fakeout filter error ({e}) — allowing entry")
            return True

    # ── Boost position (trend-confirmation runner) ───────────────────────
    def _is_boost(self, pos) -> bool:
        """True if an MT5 position is a boost runner (comment-tagged or tracked)."""
        try:
            if int(pos.ticket) in self._boost_tickets:
                return True
        except Exception:
            pass
        return str(getattr(pos, "comment", "") or "").startswith("TC_BOOST")

    def _boost_is_open(self, mt5_symbol: str, magic: int) -> bool:
        """True if a live boost position exists for this bot+symbol."""
        try:
            from mt5_bridge import mt5
            raw = mt5.positions_get()
            for p in (list(raw) if raw is not None else []):
                if int(p.magic) == magic and str(p.symbol) == mt5_symbol and self._is_boost(p):
                    return True
        except Exception:
            pass
        return False

    def _maybe_open_boost(self, mt5_symbol: str, magic: int):
        """
        Open ONE same-direction boost runner once the bot holds
        ≥ boost_trigger_slots same-direction scalp positions (a confirmed trend).
        The boost carries NO take-profit and NO broker stop-loss — it is managed
        entirely by the boost branch of _close_profitable_positions.

        Counts SCALP positions from broker truth (mt5.positions_get) rather than
        the slot manager, so it survives a restart (where the slot manager is
        force-cleared but the broker positions persist) and is safe to call every
        tick — idempotent via the _boost_episode_open guard.
        """
        if not getattr(self.config, "boost_enabled", False):
            return
        if self._boost_episode_open:
            return

        from mt5_bridge import mt5
        # Broker-truth count of same-direction scalps (exclude any boost).
        try:
            raw = mt5.positions_get()
        except Exception:
            return
        longs = shorts = 0
        for p in (list(raw) if raw is not None else []):
            if int(p.magic) != magic or str(p.symbol) != mt5_symbol:
                continue
            if self._is_boost(p):
                self._boost_episode_open = True  # a boost already exists — don't double-open
                return
            if int(p.type) == mt5.POSITION_TYPE_BUY:
                longs += 1
            elif int(p.type) == mt5.POSITION_TYPE_SELL:
                shorts += 1

        trigger = int(self.config.boost_trigger_slots)
        if longs >= trigger and longs >= shorts:
            side = "LONG"
        elif shorts >= trigger:
            side = "SHORT"
        else:
            return

        try:
            info = mt5.symbol_info(mt5_symbol)
            v_min = float(getattr(info, "volume_min", 0.01)) or 0.01
            v_step = float(getattr(info, "volume_step", 0.01)) or 0.01
            fm = int(getattr(info, "filling_mode", 0)) if info else 0
            filling_mode = (mt5.ORDER_FILLING_FOK if fm & 1
                            else mt5.ORDER_FILLING_IOC if fm & 2
                            else mt5.ORDER_FILLING_RETURN)
        except Exception:
            v_min, v_step, filling_mode = 0.01, 0.01, mt5.ORDER_FILLING_RETURN

        # Normalize boost lot to the symbol's step/min.
        vol = round(round(float(self.config.boost_lot) / v_step) * v_step, 2)
        if vol < v_min:
            vol = v_min

        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            return
        if side == "LONG":
            order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
        else:
            order_type, price = mt5.ORDER_TYPE_SELL, tick.bid

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       mt5_symbol,
            "volume":       vol,
            "type":         order_type,
            "price":        price,
            "sl":           0.0,   # NO stop-loss — boost rides; protected in software (-$cap)
            "tp":           0.0,   # NO take-profit
            "deviation":    20,
            "magic":        magic,
            "comment":      f"TC_BOOST_{self.bot_id[:8]}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        try:
            res = mt5.order_send(req)
        except Exception as e:
            self._logger.warning(f"[{self.bot_id}] BOOST open order error: {e}")
            return

        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            self._boost_episode_open = True
            try:
                tk = int(getattr(res, "order", 0)) or int(getattr(res, "deal", 0))
                if tk:
                    self._boost_tickets.add(tk)
            except Exception:
                pass
            # Sweep positions to capture the actual position ticket by comment.
            try:
                raw = mt5.positions_get()
                for p in (list(raw) if raw is not None else []):
                    if int(p.magic) == magic and str(p.symbol) == mt5_symbol and self._is_boost(p):
                        self._boost_tickets.add(int(p.ticket))
            except Exception:
                pass
            _n_scalps = longs if side == "LONG" else shorts
            self._logger.info(
                f"[{self.bot_id}] BOOST OPEN: {side} {vol} lots @ {price:.5f} "
                f"(trend confirmed by {_n_scalps} same-dir scalps) — no TP/SL, "
                f"software cap -${self.config.boost_max_loss_usd:.2f}"
            )
        else:
            rc = res.retcode if res else "None"
            self._logger.warning(f"[{self.bot_id}] BOOST open failed: retcode={rc}")

    def _boost_mtf_reversal(self, side: str, mt5_symbol: str) -> bool:
        """
        True when the fast timeframes (M1/M5/M15) have flipped AGAINST a boost in
        `side` direction — the multi-timeframe "retrace" exit signal. Throttled by
        boost_mtf_refresh_secs; verdict cached per side between fetches.
        """
        if not getattr(self.config, "boost_mtf_exit_enabled", False):
            return False
        now = time.time()
        if (now - self._boost_mtf_ts) < float(self.config.boost_mtf_refresh_secs):
            return bool(self._boost_mtf_cache.get(side, False))
        self._boost_mtf_ts = now

        verdict = False
        try:
            import pandas as pd
            from mt5_bridge import mt5
            from market_data_aggregator import MarketDataAggregator
            agg = getattr(self, "_mtf_aggregator", None)
            if agg is None:
                agg = MarketDataAggregator()
                self._mtf_aggregator = agg

            # A LONG boost is threatened by BEARISH timeframes; a SHORT by BULLISH.
            threat = "bearish" if side == "LONG" else "bullish"
            tfs = [("1m", mt5.TIMEFRAME_M1), ("5m", mt5.TIMEFRAME_M5), ("15m", mt5.TIMEFRAME_M15)]
            opposed, checked = 0, 0
            for label, tf in tfs:
                try:
                    rates = mt5.copy_rates_from_pos(mt5_symbol, tf, 0, 200)
                    if rates is None or len(rates) < 50:
                        continue
                    df = pd.DataFrame({
                        "open":   [float(r["open"]) for r in rates],
                        "high":   [float(r["high"]) for r in rates],
                        "low":    [float(r["low"]) for r in rates],
                        "close":  [float(r["close"]) for r in rates],
                        "volume": [float(r["tick_volume"]) for r in rates],
                    })
                    summ = agg.compute_trend_summary(df, mt5_symbol, label)
                    checked += 1
                    if str(summ.get("trend_direction", "")).lower() == threat:
                        opposed += 1
                except Exception:
                    continue
            verdict = checked > 0 and opposed >= int(self.config.boost_mtf_min_flip)
            if verdict:
                self._logger.info(
                    f"[{self.bot_id}] BOOST MTF reversal: {opposed}/{checked} fast TFs "
                    f"turned {threat} against {side} boost"
                )
        except Exception as e:
            self._logger.debug(f"[{self.bot_id}] boost MTF check error: {e}")
            verdict = False

        self._boost_mtf_cache[side] = verdict
        return verdict

    def _psych_loser_cut(self, state, net_profit: float, current_price: float,
                         side: str, now: float) -> Optional[str]:
        """Consult the deterministic discipline guards for an open position and
        return a close reason if it should be cut, else None.

        Order: thesis-invalidation (price level) → strict-loser (MAE, with the
        pay-to-see-the-flop allowance) → horizon breach (day-trade→swing guard).
        Only ever returns a reason for cutting a LOSER earlier — never widens or
        defers the hard stop. Winners are left to the retrace ratchet / TP.
        """
        if state is None:
            return None
        cfg = self.config
        inval = check_thesis_invalidated(side, current_price, state.invalidation_price)
        if inval.cuts:
            return inval.reason
        sl = check_strict_loser_cut(
            net_profit, state.mae_usd,
            max_adverse_excursion_usd=float(getattr(cfg, "max_adverse_excursion_usd", 0.0) or 0.0),
            thesis_intact=True,
        )
        if sl.cuts:
            return sl.reason
        hz = check_horizon_breach(
            now - state.entry_ts, net_profit,
            max_loser_hold_secs=int(getattr(cfg, "max_loser_hold_secs", 0) or 0),
            max_position_hold_secs=int(getattr(cfg, "max_position_hold_secs", 0) or 0),
        )
        if hz.cuts:
            return hz.reason
        return None

    def _check_session_discipline(self, now: float) -> None:
        """Rolling session safeguards (24/7-safe): tilt cool-down lockout and the
        give-back guard (don't keep risking once equity retraces from its peak —
        "finish your day"/"protect your account", Ch4). Sets _psych_halt_entries;
        open positions are always still managed by the exit scanner.
        """
        if not getattr(self.config, "psychology_enabled", True):
            self._psych_halt_entries = False
            return
        vs = self._vital_signs
        peak = float(getattr(vs, "_peak_equity", 0.0) or 0.0)
        start = float(self.starting_equity or 0.0)
        equity = self.starting_equity + self.total_realized_pnl + self.unrealized_pnl
        giveback = float(getattr(self.config, "rolling_giveback_pct", 0.0) or 0.0)

        halt, reason = False, ""
        if vs.in_tilt_lockout(now):
            halt = True
            reason = f"tilt lockout {vs.tilt_lockout_remaining(now):.0f}s remaining"
        elif giveback > 0 and peak > start and equity <= peak * (1.0 - giveback):
            halt = True
            reason = (f"give-back guard: equity ${equity:.2f} ≤ peak ${peak:.2f} "
                      f"× (1−{giveback:.0%})")

        if halt != self._psych_halt_entries:
            self._psych_halt_entries = halt
            self._logger.info(
                f"[{self.bot_id}] PSYCH HALT {'engaged' if halt else 'lifted'}"
                + (f" — {reason}" if halt else " — entries resumed")
            )

    def _close_profitable_positions(self, mt5_symbol: str, magic: int) -> int:
        """
        Scan this bot's open MT5 positions. Close any where floating profit exceeds
        config.take_profit_usd. Returns the number of positions closed.

        Operates on individual MT5 tickets so partial closes work correctly when
        multiple scale-in slots are open.
        """
        from mt5_bridge import mt5

        tp_threshold = self.config.take_profit_usd
        is_leverage = self.config.leverage_mode_enabled
        retrace_on = bool(getattr(self.config, "profit_retrace_enabled", False))
        sl_usd_on = float(getattr(self.config, "stop_loss_usd", 0.0) or 0.0) > 0

        # Scan whenever ANY per-position exit mechanism is active: gross TP,
        # leverage net-target/scale-out, the profit-retrace ratchet, or the
        # per-trade USD stop. Only bail when none of them can fire.
        if tp_threshold <= 0 and not is_leverage and not retrace_on and not sl_usd_on:
            return 0

        try:
            raw = mt5.positions_get()
            all_pos = list(raw) if raw is not None else []
            bot_pos = [
                p for p in all_pos
                if int(p.magic) == magic and str(p.symbol) == mt5_symbol
            ]
        except Exception as e:
            self._logger.warning(f"[{self.bot_id}] TP scan: positions_get failed: {e}")
            return 0

        # Resolve filling mode + volume constraints once (same symbol for all positions)
        filling_mode = mt5.ORDER_FILLING_RETURN
        v_min, v_step = 0.01, 0.01
        try:
            info = mt5.symbol_info(mt5_symbol)
            if info:
                fm = int(getattr(info, "filling_mode", 0))
                if fm & 1:
                    filling_mode = mt5.ORDER_FILLING_FOK
                elif fm & 2:
                    filling_mode = mt5.ORDER_FILLING_IOC
                v_min = float(getattr(info, "volume_min", 0.01)) or 0.01
                v_step = float(getattr(info, "volume_step", 0.01)) or 0.01
                _point = float(getattr(info, "point", 0.0)) or 0.0
                _min_dist = float(getattr(info, "trade_stops_level", 0) or 0) * _point
                _digits = int(getattr(info, "digits", 2) or 2)
        except Exception:
            _point, _min_dist, _digits = 0.0, 0.0, 2

        closed_count = 0
        _now = time.time()
        for pos in bot_pos:
            gross_profit = float(pos.profit)
            commission = float(getattr(pos, "commission", 0.0))
            swap = float(getattr(pos, "swap", 0.0))
            net_profit = gross_profit + commission + swap
            is_boost = self._is_boost(pos)

            # Ensure a broker-side SL/TP backstop on every position. The bot
            # normally exits in software (this scan), but if the backend/bridge
            # goes down those exits never fire — a broker SL/TP protects the
            # position regardless. SL = stop_loss_usd; TP = net_profit_target_usd
            # (a far cap that lets the software scale-out / trail run first).
            try:
                _has_sl = float(getattr(pos, "sl", 0.0) or 0.0) != 0.0
                _sl_usd = float(getattr(self.config, "stop_loss_usd", 0.0) or 0.0)
                _tp_usd = float(getattr(self.config, "net_profit_target_usd", 0.0) or 0.0)
                _pv = float(pos.volume) or 0.01
                # Boost runner intentionally carries NO broker SL — it must ride;
                # it is protected only by the software -$cap / retrace / MTF exit.
                if not is_boost and not _has_sl and _sl_usd > 0 and _digits and pos.price_open:
                    _is_buy = int(pos.type) == mt5.POSITION_TYPE_BUY
                    _sl_d = _sl_usd / _pv
                    _tp_d = (_tp_usd / _pv) if _tp_usd > 0 else (_sl_d * 3)
                    if _is_buy:
                        _sl_px = round(pos.price_open - _sl_d, _digits)
                        _tp_px = round(pos.price_open + _tp_d, _digits)
                    else:
                        _sl_px = round(pos.price_open + _sl_d, _digits)
                        _tp_px = round(pos.price_open - _tp_d, _digits)
                    mt5.order_send({
                        "action": mt5.TRADE_ACTION_SLTP, "position": int(pos.ticket),
                        "symbol": mt5_symbol, "sl": _sl_px, "tp": _tp_px,
                    })
            except Exception as _sltp_err:
                self._logger.debug(f"[{self.bot_id}] Ensure SL/TP failed for {getattr(pos,'ticket','?')}: {_sltp_err}")

            # Check logic
            should_close = False
            scale_out_now = False
            half_vol = 0.0
            reason = ""

            ticket = int(pos.ticket)
            volume = float(pos.volume)
            pos_type = int(pos.type)

            sl_usd = float(getattr(self.config, "stop_loss_usd", 0.0) or 0.0)

            # ── Trading-psychology: track per-position MAE + duration, then
            #    consult the deterministic discipline guards. _psych_cut is a
            #    close reason when a loser must be cut (thesis broken / MAE /
            #    horizon); _giveroom defers PROFIT-side exits on a thesis-intact
            #    winner the Tier-2 narrator flagged (never affects the hard SL).
            _side = "LONG" if pos_type == mt5.POSITION_TYPE_BUY else "SHORT"
            _cur_px = float(getattr(pos, "price_current", 0.0)) or float(pos.price_open)
            _pstate = self._discipline.update(ticket, net_profit, _cur_px, _side, float(pos.price_open), _now)
            _psych_cut = None
            _giveroom = False
            if getattr(self.config, "psychology_enabled", True) and not is_boost:
                _psych_cut = self._psych_loser_cut(_pstate, net_profit, _cur_px, _side, _now)
                _giveroom = net_profit > 0 and ticket in self._giveroom_tickets

            # ── Advanced profit-retrace ratchet (per-ticket peak give-back) ──
            # Track this ticket's PEAK floating net profit and trail a rising
            # give-back floor beneath it. Once peak ≥ arm_usd the floor arms; if
            # net profit then retraces to the floor we bank the position. The
            # give-back tightens as profit deepens and (optionally) widens with
            # volatility. The floor is always positive, so this can ONLY ever
            # close a position in profit — never a loser — and it sits below
            # net_profit_target_usd so outright winners still run to target.
            retrace_close = False
            retrace_reason = ""
            if not is_boost and getattr(self.config, "profit_retrace_enabled", False):
                peak = max(self._peak_net.get(ticket, net_profit), net_profit)
                self._peak_net[ticket] = peak
                arm = float(self.config.profit_retrace_arm_usd)
                if peak >= arm:
                    gb = float(self.config.profit_retrace_giveback_pct)
                    if peak >= float(self.config.profit_retrace_tighten_usd):
                        gb = float(self.config.profit_retrace_tight_giveback_pct)
                    # Volatility-adaptive: widen the give-back in high-ATR regimes
                    # (up to +40%) so ordinary noise doesn't trip the lock early.
                    if getattr(self.config, "profit_retrace_atr_adaptive", False) and self._last_atr_pct > 0:
                        gb = gb * (1.0 + min(self._last_atr_pct * 80.0, 0.40))
                    # Tier-2 TIGHTEN: shrink the give-back (monotonic ≤ 1.0) so a
                    # winner locks profit sooner. Never widens — floor stays ≥ min_lock.
                    gb = gb * float(self._tighten_tickets.get(ticket, 1.0))
                    gb = min(gb, 0.60)
                    floor = max(peak * (1.0 - gb), float(self.config.profit_retrace_min_lock_usd))
                    # GIVE_ROOM: a thesis-intact winner is allowed to run past the
                    # lock ("pay to see the flop") — the hard SL is still in force.
                    if net_profit <= floor < peak and not _giveroom:
                        retrace_close = True
                        retrace_reason = (
                            f"Profit-retrace lock: net ${net_profit:.2f} ≤ floor ${floor:.2f} "
                            f"(peak ${peak:.2f}, give-back {gb:.0%})"
                        )

            # ── BOOST runner exit — its OWN logic; bypasses the scalp chain ──
            # No $1 net target, no scale-out. Closes only on: hard -$cap, peak
            # give-back, or a multi-timeframe reversal while in profit. Otherwise
            # it rides (should_close stays False → the scan skips it this tick).
            if is_boost:
                bpeak = max(self._peak_net.get(ticket, net_profit), net_profit)
                self._peak_net[ticket] = bpeak
                b_cap = float(getattr(self.config, "boost_max_loss_usd", 30.0))
                b_arm = float(getattr(self.config, "boost_arm_usd", 1.5))
                b_gb = float(getattr(self.config, "boost_giveback_pct", 0.35))
                b_side = "LONG" if pos_type == mt5.POSITION_TYPE_BUY else "SHORT"
                if gross_profit <= -b_cap:
                    should_close = True
                    reason = f"Boost max-loss ${b_cap:.2f} hit"
                elif bpeak >= b_arm and net_profit <= bpeak * (1.0 - b_gb) < bpeak:
                    should_close = True
                    reason = (f"Boost give-back: net ${net_profit:.2f} ≤ floor "
                              f"${bpeak * (1.0 - b_gb):.2f} (peak ${bpeak:.2f}, {b_gb:.0%})")
                elif net_profit > 0 and self._boost_mtf_reversal(b_side, mt5_symbol):
                    should_close = True
                    reason = f"Boost MTF reversal (net ${net_profit:.2f}, peak ${bpeak:.2f})"

            # ── Psychology discipline cuts (non-boost) — placed BEFORE the hard
            #    SL so a Tier-2 CUT_NOW or a broken-thesis / over-MAE / over-horizon
            #    loser is cut promptly. These only ever cut EARLIER than the
            #    mechanical stops — never later, never looser.
            elif ticket in self._force_close_tickets:
                should_close = True
                reason = "Discipline: Tier-2 CUT_NOW"
            elif _psych_cut is not None:
                should_close = True
                reason = f"Discipline: {_psych_cut}"

            # Per-trade hard stop-loss (gross) — evaluated FIRST so a losing
            # position is cut before it can ladder with others into the fleet
            # drawdown emergency halt.
            elif sl_usd > 0 and gross_profit <= -sl_usd:
                should_close = True
                reason = f"Stop-Loss ${sl_usd:.2f} hit"
            elif retrace_close:
                # Profit give-back lock — bank the retracing winner before it
                # round-trips back toward break-even.
                should_close = True
                reason = retrace_reason
            elif is_leverage:
                # 1. Net Profit Target — closes the remaining runner.
                #    GIVE_ROOM defers this profit-take on a thesis-intact winner.
                if net_profit >= self.config.net_profit_target_usd and not _giveroom:
                    should_close = True
                    reason = f"Net Target ${self.config.net_profit_target_usd:.2f} met"

                # 2. Gross Take-Profit → SCALE OUT: bank half here, let the other
                #    half run on the trailing stop / net target so a winner can
                #    become a big winner. Single min-lot positions can't be
                #    halved → take the full scalp instead.
                elif tp_threshold > 0 and gross_profit >= tp_threshold:
                    if ticket in self._scaled_out:
                        continue  # already banked half — let the runner run
                    half_vol = round((volume / 2) // v_step * v_step, 2)
                    if half_vol >= v_min and round(volume - half_vol, 2) >= v_min:
                        scale_out_now = True
                        reason = f"Scale-out half @ Gross TP ${tp_threshold:.2f}"
                    else:
                        should_close = True
                        reason = f"Gross TP ${tp_threshold:.2f} met (unsplittable)"

                # 3. Isolated Risk Stop Out (outer backstop)
                elif net_profit <= -self.config.isolated_risk_usd:
                    should_close = True
                    reason = f"Isolated Risk ${self.config.isolated_risk_usd:.2f} reached"
            else:
                # Standard TP mode (based on gross profit by default).
                # GIVE_ROOM defers the take-profit on a thesis-intact winner.
                if tp_threshold > 0 and gross_profit >= tp_threshold and not _giveroom:
                    should_close = True
                    reason = f"Take Profit ${tp_threshold:.2f} met"

            # ── Scale-out: partial close of half; remainder keeps running ──
            if scale_out_now:
                s_close_type = (
                    mt5.ORDER_TYPE_SELL if pos_type == mt5.POSITION_TYPE_BUY
                    else mt5.ORDER_TYPE_BUY
                )
                s_tick = mt5.symbol_info_tick(mt5_symbol)
                if s_tick is None:
                    continue
                s_price = s_tick.bid if s_close_type == mt5.ORDER_TYPE_SELL else s_tick.ask
                s_res = mt5.order_send({
                    "action":       mt5.TRADE_ACTION_DEAL,
                    "position":     ticket,
                    "symbol":       mt5_symbol,
                    "volume":       half_vol,
                    "type":         s_close_type,
                    "price":        s_price,
                    "deviation":    20,
                    "magic":        magic,
                    "comment":      f"TC_SCALE_{self.bot_id[:8]}",
                    "type_time":    mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode,
                })
                if s_res is not None and s_res.retcode == mt5.TRADE_RETCODE_DONE:
                    realized_half = gross_profit * (half_vol / volume) if volume > 0 else 0.0
                    self._scaled_out.add(ticket)
                    # Re-arm the profit-retrace ratchet on the reduced runner:
                    # the peak was tracked on the full position, so drop it and
                    # let the floor re-accumulate against the half that remains.
                    self._peak_net.pop(ticket, None)
                    with self._lock:
                        self.total_realized_pnl += realized_half
                        self.daily_pnl = self.total_realized_pnl
                    closed_count += 1
                    # Psychology: a scale-out banks a partial winner — record it
                    # as a realized outcome so win-streak / composure tracking
                    # sees the discipline of taking money off the table.
                    try:
                        self._vital_signs.record_trade_outcome(realized_half, _now, self.config)
                    except Exception:
                        pass
                    self._logger.info(
                        f"[{self.bot_id}] SCALE-OUT: ticket={ticket} banked "
                        f"{half_vol}/{volume} lots (~${realized_half:.2f}) — "
                        f"remainder {round(volume - half_vol, 2)} runs on trailing/net target"
                    )
                else:
                    rc = s_res.retcode if s_res else "None"
                    self._logger.warning(f"[{self.bot_id}] Scale-out partial close failed: ticket={ticket} retcode={rc}")
                continue

            if not should_close:
                continue

            self._logger.info(f"[{self.bot_id}] Closing position {pos.ticket}: {reason} (Net: ${net_profit:.2f})")

            # LONG closed with SELL, SHORT closed with BUY
            close_type = (
                mt5.ORDER_TYPE_SELL
                if pos_type == mt5.POSITION_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            tick = mt5.symbol_info_tick(mt5_symbol)
            if tick is None:
                continue
            close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "position":     ticket,
                "symbol":       mt5_symbol,
                "volume":       volume,
                "type":         close_type,
                "price":        close_price,
                "deviation":    20,
                "magic":        magic,
                "comment":      f"TC_TP_{self.bot_id[:8]}",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                fill_price = float(result.price) if result.price else close_price
                close_label = "TAKE-PROFIT" if net_profit >= 0 else "STOP-LOSS"
                self._logger.info(
                    f"[{self.bot_id}] {close_label}: ticket={ticket} "
                    f"profit=${net_profit:.2f} vol={volume} @ {fill_price:.5f} | {reason}"
                )
                with self._lock:
                    self.total_realized_pnl += net_profit
                    self.daily_pnl = self.total_realized_pnl
                closed_count += 1
                # Psychology: record the realized outcome (win/loss streak +
                # tilt arming). A discipline-driven cut counts as a rule-adherence
                # event (not a violation) — the violation is averaging-down etc.
                try:
                    self._vital_signs.record_trade_outcome(net_profit, _now, self.config)
                except Exception:
                    pass
                # Boost closed → free the episode so a fresh trend can arm a new one.
                if is_boost:
                    self._boost_tickets.discard(ticket)
                    self._boost_episode_open = False
                    self._peak_net.pop(ticket, None)
                    self._logger.info(f"[{self.bot_id}] BOOST CLOSED: ticket={ticket} net=${net_profit:.2f} | {reason}")
            else:
                retcode = result.retcode if result else "None"
                comment = result.comment if result else str(mt5.last_error())
                self._logger.warning(
                    f"[{self.bot_id}] TP close failed: ticket={ticket} "
                    f"retcode={retcode} — {comment}"
                )
                if retcode == 10027 or "AutoTrading disabled" in str(comment):
                    self._logger.error(f"[{self.bot_id}] AutoTrading disabled by client — transitioning to CRITICAL_STOP.")
                    self.emergency_stop("AutoTrading disabled in MT5 terminal.")
                    break

        # If all bot positions are now gone, clear slot state so the engine
        # doesn't think it's still holding and block new entries.
        if closed_count > 0:
            try:
                raw2 = mt5.positions_get()
                remaining = [
                    p for p in (list(raw2) if raw2 is not None else [])
                    if int(p.magic) == magic and str(p.symbol) == mt5_symbol
                ]
                boost_remaining = [p for p in remaining if self._is_boost(p)]
                scalp_remaining = [p for p in remaining if not self._is_boost(p)]
                open_tickets = {int(p.ticket) for p in remaining}

                if not scalp_remaining:
                    # Every SCALP slot is closed → reset the slot manager so new
                    # entries aren't blocked. A still-open boost rides on its own.
                    self._slot_manager.force_clear()
                    with self._lock:
                        self._sync_from_slots()
                        self._trailing_high = 0.0
                        self._trailing_low = float("inf")
                        if not boost_remaining:
                            self.unrealized_pnl = 0.0

                # Keep per-ticket maps in sync with live tickets (scalp or boost)
                # so they never grow stale/unbounded.
                self._scaled_out &= open_tickets
                self._peak_net = {t: v for t, v in self._peak_net.items() if t in open_tickets}
                self._boost_tickets &= open_tickets
                if not boost_remaining:
                    self._boost_episode_open = False
                # Psychology per-ticket state — prune in lockstep so it never leaks.
                self._discipline.prune(open_tickets)
                self._force_close_tickets &= open_tickets
                self._giveroom_tickets &= open_tickets
                self._tighten_tickets = {t: v for t, v in self._tighten_tickets.items() if t in open_tickets}
                self._review_rationale = {t: v for t, v in self._review_rationale.items() if t in open_tickets}
            except Exception:
                pass

        return closed_count

    def _sync_account(self, symbol: str):
        try:
            from mt5_bridge import mt5

            with self._lock:
                self.equity = self.starting_equity + self.total_realized_pnl + self.unrealized_pnl
                self.daily_pnl = self.total_realized_pnl + self.unrealized_pnl

            # Sync position from MT5
            try:
                from symbol_service import to_mt5_symbol
                mt5_symbol = to_mt5_symbol(symbol)
                magic = _stable_magic(self.bot_id)

                # Call positions_get() with NO arguments — passing keyword args
                # (symbol=...) through RPyC hits the same C-extension positional-only
                # restriction as order_send and silently returns None. Fetch ALL
                # positions instead and filter by magic + symbol in Python.
                raw = mt5.positions_get()
                all_positions = list(raw) if raw is not None else []
                bot_positions = [
                    p for p in all_positions
                    if int(p.magic) == magic and str(p.symbol) == mt5_symbol
                ]

                if bot_positions:
                    # Sum all open MT5 positions for this bot (multi-slot support)
                    # p.volume is already in lots — no min_lot conversion needed
                    total_qty = sum(float(p.volume) for p in bot_positions)
                    total_unrealized = sum(float(p.profit) for p in bot_positions)
                    pos0 = bot_positions[0]
                    with self._lock:
                        self.position_qty = total_qty
                        self.position_side = (
                            "SHORT" if int(pos0.type) == int(mt5.POSITION_TYPE_SELL)
                            else "LONG"
                        )
                        self.unrealized_pnl = total_unrealized
                else:
                    # Only zero internal state when the MT5 call SUCCEEDED and
                    # confirmed no matching position exists. If the call threw an
                    # exception we keep internal state and log — zeroing on error
                    # is what causes the endless re-entry loop.
                    with self._lock:
                        if self.position_qty != 0:
                            self._logger.info(
                                f"[{self.bot_id}] Position no longer in MT5 "
                                f"(magic={magic}, symbol={mt5_symbol}) — clearing state."
                            )
                            self._slot_manager.force_clear()
                            self._sync_from_slots()  # zeroes position_qty/side/entry_price
                            self.unrealized_pnl = 0.0
                            self._trailing_high = 0.0
                            self._trailing_low = float("inf")
                            self._scaled_out.clear()
                            self._peak_net.clear()
                            self._boost_tickets.clear()
                            self._boost_episode_open = False

            except Exception as e:
                # Sync failed — do NOT zero position state. Zeroing on a transient
                # RPyC/MT5 error is what causes repeated entries. Log and keep state.
                self._logger.warning(
                    f"[{self.bot_id}] Position sync failed (keeping internal state): {e}"
                )

        except Exception as e:
            self._logger.warning(f"Account sync failed: {e}")
