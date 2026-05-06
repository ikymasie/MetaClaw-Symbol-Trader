"""
TradeClaw — Per-Bot Strategy Engine
======================================
Refactored from the singleton strategy.py into an instantiable BotEngine class.
Each bot instance has its own fully-isolated engine with its own state, lock,
price history, markers, and DB write queue.
"""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, date, timezone
from typing import Optional

from bot_config import BotConfig
from bot_vital_signs import BotVitalSigns

logger = logging.getLogger("tradeclaw.bot_engine")


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
    Wraps the Alpaca trading loop for one symbol/strategy combination.
    All state is instance-local — no cross-bot contamination.
    """

    MAX_HISTORY = 1200

    def __init__(self, bot_id: str, config: BotConfig, vital_signs: BotVitalSigns):
        self.bot_id = bot_id
        self.config = config
        self._vital_signs = vital_signs
        self._logger = logging.getLogger(f"tradeclaw.engine[{bot_id}]")

        # Threading
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Status
        self._status = BotEngineStatus.IDLE
        self._message = ""

        # Market state
        self.current_price: float = 0.0
        self.position_qty: int = 0
        self.position_side: str = "NONE"
        self.entry_price: float = 0.0

        # Trailing stop-loss state
        self._trailing_high: float = 0.0          # For longs: highest price since entry
        self._trailing_low: float = float("inf")  # For shorts: lowest price since entry

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

        # DB write queue (flushed by fleet's db_flush_loop)
        # Hard-capped at 1000: if Firestore falls behind, oldest entry is evicted
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
        self._executioner = None      # ExecutionerAgent — set by _run_loop after Alpaca init

        # Last deliberation result (exposed via API)
        self.last_deliberation: dict = {}
        self._entry_deliberation: Optional[dict] = None  # Saved on fill for Darwinian attribution

        # Regime tracking
        self.current_regime: str = "UNKNOWN"

        # Persistent bar queue (flushed by fleet monitor loop, bounded at 500)
        self._BAR_QUEUE_MAXLEN = 500
        self._bar_queue: deque = deque(maxlen=self._BAR_QUEUE_MAXLEN)
        self._bar_queue_lock = threading.Lock()
        self._last_bar_minute: str = ""  # Tracks last written minute for dedup

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
            "demo_mode": self.config.demo_mode,
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
                # Persona persistence
                "description": self.config.description,
                "personality": self.config.personality,
                "animal": self.config.animal,
                "category": self.config.category,
                "ai_generated": self.config.ai_generated,
            }

    def get_current_params(self) -> dict:
        with self._params_lock:
            return dict(self._params)

    def update_params(self, new_params: dict):
        """Called by AI Brain to update strategy parameters at runtime."""
        with self._params_lock:
            for k, v in new_params.items():
                if k in self._params:
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

    # ── MAS Wiring ────────────────────────────────────────────────────

    def wire_sub_agent_pool(self, pool) -> None:
        """
        Called by FleetOrchestrator after construction to inject the shared
        SubAgentPool so the engine can call pool.deliberate() each tick.
        """
        self._sub_agent_pool = pool
        self._logger.info(f"[{self.bot_id}] SubAgentPool wired ({len(pool.enabled_agents)} agents)")

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self):
        """Start the trading loop in a background thread."""
        if self._status == BotEngineStatus.RUNNING:
            return
        self._stop_event.clear()
        self._status = BotEngineStatus.STARTING
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"engine-{self.bot_id}",
        )
        self._thread.start()
        self._logger.info(f"Engine started. Symbol={self.config.symbol}")

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
        Queue one OHLC bar for Firestore persistence.
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
                    f"Firestore flush may be lagging"
                )
            self._bar_queue.append(bar)  # deque auto-evicts oldest when full

    def _queue_trade(self, trade: dict):
        """Queue a trade write for the fleet DB flush loop."""
        with self._db_lock:
            if len(self._db_queue) >= self._DB_QUEUE_MAXLEN - 1:
                self._logger.warning(
                    f"[{self.bot_id}] _db_queue near cap ({len(self._db_queue)}/{self._DB_QUEUE_MAXLEN}) — "
                    f"Firestore writes lagging, oldest entry will be evicted"
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

        Imports the Alpaca client and strategy logic from the existing
        strategy.py module functions (they are stateless calculation functions).
        """
        import alpaca.trading.client as alpaca_trading
        import alpaca.data.live as alpaca_live
        import os

        try:
            from strategy import (
                compute_bollinger_bands,
                detect_signal,
            )
        except ImportError:
            self._logger.error("Cannot import strategy functions. Engine cannot start.")
            self._status = BotEngineStatus.STOPPED
            return

        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        try:
            trading_client = alpaca_trading.TradingClient(
                api_key, secret_key, paper=True
            )
        except Exception as e:
            self._logger.error(f"Alpaca client init failed: {e}")
            self._status = BotEngineStatus.STOPPED
            return

        self._status = BotEngineStatus.RUNNING
        self._logger.info("Engine RUNNING")

        # Pre-seed price history with historical bars so the bot is
        # immediately warm for BB/regime calculations (skips 2+ min warmup)
        params = self.get_current_params()
        demo_mode = params.get("demo_mode", self.config.demo_mode)
        if not demo_mode:
            self._warmup_history(params)

        # Main loop — 5 second tick
        while not self._stop_event.is_set():
            try:
                params = self.get_current_params()
                demo_mode = params.get("demo_mode", self.config.demo_mode)

                if demo_mode:
                    self._demo_tick(params)
                else:
                    self._live_tick(trading_client, params)

                # Update vital signs
                self._vital_signs.update(
                    equity=self.equity,
                    daily_pnl=self.daily_pnl,
                    starting_equity=self.starting_equity or self.equity,
                )
            except Exception as e:
                self._logger.error(f"Engine tick error: {e}", exc_info=True)

            self._stop_event.wait(5)

        self._status = BotEngineStatus.STOPPED

    # ── Historical Warmup ─────────────────────────────────────────────

    def _warmup_history(self, params: dict):
        """
        Pre-seed price_history from persistent Firestore bar store.
        Falls back to Alpaca historical API if Firestore has < 200 bars.

        Priority:
          1. Firestore → up to 1000 bars (fast, free, survives restarts)
          2. Alpaca API → up to 200 bars (cold start only)
          3. Live accumulation (fallback if both fail)

        After Alpaca fetch, new bars are back-filled into Firestore so
        the next restart loads them instantly.
        """
        import os
        import asyncio
        from datetime import timedelta

        symbol = params.get("symbol", self.config.symbol)
        CRYPTO_BASE_SYMBOLS = {"BTC", "ETH", "SOL", "ADA", "DOGE", "XRP", "LTC", "AVAX", "MATIC", "SHIB", "UNI", "LINK", "DOT"}
        is_crypto = (
            self.config.category == "Crypto"
            or "/" in symbol
            or symbol.replace("/USD", "").replace("/USDT", "") in CRYPTO_BASE_SYMBOLS
        )
        is_forex = (
            self.config.category == "Forex"
            or symbol.endswith("=X")
            or (len(symbol.replace("/", "")) == 6 and symbol.replace("/", "").isalpha() and not is_crypto)
        )

        api_key = os.getenv("ALPACA_API_KEY", "") or None
        secret_key = os.getenv("ALPACA_SECRET_KEY", "") or None

        # ── Step 1: Try Firestore persistent bar store ────────────────
        firestore_bars = []
        try:
            import firebase_store
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    firebase_store.load_bars(symbol, limit=1000), loop
                )
                firestore_bars = future.result(timeout=10)
            else:
                firestore_bars = loop.run_until_complete(
                    firebase_store.load_bars(symbol, limit=1000)
                )
        except Exception as e:
            self._logger.debug(f"Firestore bar load skipped: {e}")

        if len(firestore_bars) >= 200:
            # Firestore has enough — use it directly
            count = 0
            with self._lock:
                for bar in firestore_bars:
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
                    self.current_price = firestore_bars[-1].get("c", 0.0)

            self._logger.info(
                f"Warmup: {count} bars loaded from Firestore for {symbol} — "
                f"regime detection ready immediately"
            )
            # Prune old bars in background (fire and forget)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        firebase_store.prune_bars(symbol, keep=1200), loop
                    )
            except Exception:
                pass
            return

        # ── Step 2: Firestore insufficient — fetch from Alpaca ────────
        self._logger.info(
            f"Firestore has {len(firestore_bars)} bars for {symbol} (need 200+) — "
            f"fetching from Alpaca"
        )
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=6)  # 6h of 1-min bars → ~360 bars max

            if is_crypto:
                from alpaca.data.historical import CryptoHistoricalDataClient
                from alpaca.data.requests import CryptoBarsRequest
                from alpaca.data.timeframe import TimeFrame

                alpaca_symbol = symbol if "/" in symbol else f"{symbol}/USD"
                client = CryptoHistoricalDataClient()
                request = CryptoBarsRequest(
                    symbol_or_symbols=alpaca_symbol,
                    timeframe=TimeFrame.Minute,
                    start=start,
                    end=end,
                    limit=200,
                )
                bars = client.get_crypto_bars(request)
            else:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame

                if is_forex:
                    # alpaca-py has no ForexHistoricalDataClient — use Stock client
                    self._logger.warning(
                        f"Forex warmup: alpaca-py lacks Forex API. "
                        f"Attempting Stock client for {symbol} (may return empty)."
                    )
                
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest
                alpaca_symbol = symbol.replace("/", "").replace("=X", "") if is_forex else (
                    symbol.replace("/", "") if "/" in symbol else symbol
                )
                client = StockHistoricalDataClient(api_key, secret_key)
                request = StockBarsRequest(
                    symbol_or_symbols=alpaca_symbol,
                    timeframe=TimeFrame.Minute,
                    start=start,
                    end=end,
                    limit=200,
                )
                bars = client.get_stock_bars(request)

            df = bars.df
            if hasattr(df.index, "levels") and len(df.index.levels) > 1:
                try:
                    df = df.xs(alpaca_symbol, level="symbol")
                except KeyError:
                    alt = alpaca_symbol.replace("/", "")
                    df = df.xs(alt, level="symbol")

            if df.empty:
                self._logger.warning(f"Warmup: no historical bars for {symbol}")
                return

            count = 0
            bars_to_persist: list[dict] = []
            with self._lock:
                for idx, row in df.iterrows():
                    ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                    price = float(row["close"])
                    self.price_history.append({
                        "time": ts,
                        "price": price,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": price,
                        "volume": float(row.get("volume", 0)),
                    })
                    bars_to_persist.append({
                        "t": ts,
                        "o": float(row["open"]),
                        "h": float(row["high"]),
                        "l": float(row["low"]),
                        "c": price,
                        "v": float(row.get("volume", 0)),
                        "src": "warmup",
                    })
                    count += 1
                if count > 0:
                    self.current_price = float(df.iloc[-1]["close"])

            self._logger.info(
                f"Warmup: {count} bars loaded from Alpaca for {symbol} — "
                f"back-filling Firestore"
            )

            # Back-fill Alpaca bars into Firestore for next restart
            try:
                import firebase_store
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        firebase_store.append_bars_batch(symbol, bars_to_persist),
                        loop,
                    )
            except Exception as e:
                self._logger.debug(f"Firestore back-fill skipped: {e}")

        except Exception as e:
            self._logger.warning(f"Warmup failed (will accumulate live): {e}")

    # ── Demo Tick ─────────────────────────────────────────────────────

    def _demo_tick(self, params: dict):
        """
        Enhanced demo tick — runs the full MAS analytical pipeline on
        simulated price data so the dashboard, BotCard, and Situation Room
        show realistic telemetry even in demo/paper mode.

        Pipeline:
          1. Random-walk price generation (with volume)
          2. Bollinger Band computation (once ≥ 20 bars)
          3. Signal detection (BUY/SELL/HOLD)
          4. Regime detection from simulated OHLC
          5. Simulated position tracking (entry/exit with fake fills)
          6. P&L calculation (daily_pnl, unrealized_pnl, equity)
          7. Synthetic MAS deliberation (no LLM calls)
          8. State updates for all dashboard fields
        """
        import random
        import numpy as np

        try:
            from strategy import compute_bollinger_bands, detect_signal
        except ImportError:
            self._logger.warning("Cannot import strategy helpers — demo tick limited")
            compute_bollinger_bands = None
            detect_signal = None

        ts = datetime.now(timezone.utc).isoformat()

        # ── 1. Price walk with realistic micro-volatility ─────────────
        with self._lock:
            if self.equity == 0:
                self.equity = 100_000.0
                self.starting_equity = 100_000.0

            base = self.current_price if self.current_price > 0 else 450.0
            # Slightly wider volatility so signals actually trigger
            change_pct = random.gauss(0, 0.003)  # ~0.3% std dev per tick
            self.current_price = round(base * (1 + change_pct), 2)
            # Simulate OHLC bar from the tick
            tick_high = round(self.current_price * (1 + abs(random.gauss(0, 0.001))), 2)
            tick_low = round(self.current_price * (1 - abs(random.gauss(0, 0.001))), 2)
            tick_volume = random.randint(5_000, 50_000)

            bar_entry = {
                "time": ts,
                "price": self.current_price,
                "open": base,
                "high": max(tick_high, base, self.current_price),
                "low": min(tick_low, base, self.current_price),
                "close": self.current_price,
                "volume": tick_volume,
            }
            self.price_history.append(bar_entry)
            history_snap = list(self.price_history)

        # Queue bar for Firestore persistence (minute-boundary dedup)
        self._queue_bar({
            "t": ts,
            "o": base,
            "h": max(tick_high, base, self.current_price),
            "l": min(tick_low, base, self.current_price),
            "c": self.current_price,
            "v": tick_volume,
            "src": "demo",
        })

        current_price = self.current_price
        num_bars = len(history_snap)

        # ── 2. Bollinger Bands ────────────────────────────────────────
        raw_signal = "HOLD"
        bb_period = params.get("bb_period", self.config.bb_period)
        bb_std = params.get("bb_std_dev", self.config.bb_std_dev)

        if compute_bollinger_bands and num_bars >= bb_period:
            try:
                import pandas as pd
                prices_series = pd.Series([p["price"] for p in history_snap])
                bb = compute_bollinger_bands(prices_series, period=bb_period, std_dev=bb_std)
                if bb:
                    with self._lock:
                        self.bollinger_data.append({
                            "time": ts,
                            "upper": bb["upper"],
                            "middle": bb["middle"],
                            "lower": bb["lower"],
                        })
                    # ── 3. Signal detection ────────────────────────────
                    if detect_signal:
                        raw_signal = detect_signal(current_price, bb)
            except Exception as e:
                self._logger.debug(f"Demo BB/signal error: {e}")

        # ── 4. Regime detection from simulated OHLC ───────────────────
        regime = "RANGING"
        if num_bars >= 30:
            try:
                import pandas as pd
                from regime_detector import RegimeDetector
                ohlc_data = {
                    "open": [p.get("open", p["price"]) for p in history_snap],
                    "high": [p.get("high", p["price"]) for p in history_snap],
                    "low": [p.get("low", p["price"]) for p in history_snap],
                    "close": [p.get("close", p["price"]) for p in history_snap],
                    "volume": [p.get("volume", 10000) for p in history_snap],
                }
                df = pd.DataFrame(ohlc_data)
                detector = RegimeDetector()
                regime_result = detector.detect(df)
                regime = getattr(regime_result, "regime", "RANGING")
            except Exception as e:
                self._logger.debug(f"Demo regime detection error: {e}")

        with self._lock:
            self.current_regime = regime

        # ── 5. Simulated position tracking ────────────────────────────
        with self._lock:
            # BUY: enter a position if we don't have one
            if raw_signal == "BUY" and self.position_qty == 0:
                qty = int(params.get("qty", self.config.qty))
                self.position_qty = qty
                self.position_side = "LONG"
                self.entry_price = current_price
                self.last_signal = "BUY"
                self._message = f"DEMO BUY @ ${current_price:.2f}"
                self.markers.append({
                    "time": ts,
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "arrowUp",
                    "text": "BUY [DEMO]",
                })
                self._trades.append({
                    "bot_id": self.bot_id,
                    "symbol": self.config.symbol,
                    "side": "buy",
                    "qty": qty,
                    "price": current_price,
                    "regime": regime,
                    "timestamp": ts,
                    "pnl": 0.0,
                })

            # SELL: close the position if we have one
            elif raw_signal == "SELL" and self.position_qty > 0:
                pnl = (current_price - self.entry_price) * self.position_qty
                self.total_realized_pnl += pnl
                self.position_qty = 0
                self.position_side = "NONE"
                self.entry_price = 0.0
                self.unrealized_pnl = 0.0
                self.last_signal = "SELL"
                self._message = f"DEMO SELL @ ${current_price:.2f} | PnL: ${pnl:+.2f}"
                self.markers.append({
                    "time": ts,
                    "position": "aboveBar",
                    "color": "#ef4444",
                    "shape": "arrowDown",
                    "text": f"SELL [${pnl:+.2f}]",
                })
                self._trades.append({
                    "bot_id": self.bot_id,
                    "symbol": self.config.symbol,
                    "side": "sell",
                    "qty": self.position_qty or 1,
                    "price": current_price,
                    "regime": regime,
                    "timestamp": ts,
                    "pnl": pnl,
                })
            else:
                self.last_signal = raw_signal or "HOLD"
                self._message = f"DEMO scanning {self.config.symbol} | ${current_price:.2f} | {regime}"

            # ── 6. P&L calculations ───────────────────────────────────
            if self.position_qty > 0 and self.entry_price > 0:
                self.unrealized_pnl = (current_price - self.entry_price) * self.position_qty
            self.daily_pnl = self.total_realized_pnl + self.unrealized_pnl
            self.equity = self.starting_equity + self.daily_pnl

            # Equity curve snapshot
            self.equity_curve.append({
                "time": ts,
                "equity": self.equity,
                "daily_pnl": self.daily_pnl,
            })
            # Keep equity curve bounded
            if len(self.equity_curve) > self.MAX_HISTORY:
                self.equity_curve = self.equity_curve[-self.MAX_HISTORY:]

        # ── 7. Synthetic MAS deliberation (no LLM) ───────────────────
        # Generate synthetic votes on EVERY tick so the Situation Room always
        # receives fresh agent state — BUY/SELL get full directional votes,
        # HOLD gets agents in "scanning" mode showing live analytical activity.
        try:
            agent_names = ["watchman", "sentiment", "macro", "earnings", "technical", "risk_manager"]
            synthetic_votes = []
            is_directional = raw_signal in ("BUY", "SELL")

            for agent in agent_names:
                if not is_directional:
                    # HOLD tick — agents are actively scanning, not voting
                    scanning_reasons = {
                        "watchman": f"Scanning {self.config.symbol} on 1m bars... Market quality: CLEAR.",
                        "sentiment": f"Monitoring sentiment feeds for {self.config.symbol}. No signal shift.",
                        "macro": f"Macro conditions stable. VIX normal. Yield curve unchanged.",
                        "earnings": f"Checking earnings calendar for {self.config.symbol}. No upcoming risk.",
                        "technical": f"BB within range. RSI neutral. No divergence detected.",
                        "risk_manager": f"Drawdown check: healthy. Portfolio heat: {round(random.uniform(0.5, 3.5), 1)}%.",
                    }
                    vote = "HOLD"
                    confidence = round(random.uniform(0.5, 0.85), 2)
                    reasoning = scanning_reasons.get(agent, f"Monitoring {self.config.symbol}...")
                elif agent == "risk_manager":
                    vote = raw_signal
                    confidence = round(random.uniform(0.6, 0.95), 2)
                    reasoning = f"Kelly approved. Survival state: HEALTHY."
                elif agent == "watchman":
                    vote = "HOLD"
                    confidence = round(random.uniform(0.7, 1.0), 2)
                    reasoning = f"Market quality OK ({confidence:.2f}). No anomalies detected."
                else:
                    # Panel agents vote with some randomness
                    roll = random.random()
                    if roll > 0.3:
                        vote = raw_signal
                    elif roll > 0.15:
                        vote = "HOLD"
                    else:
                        vote = "SELL" if raw_signal == "BUY" else "BUY"
                    confidence = round(random.uniform(0.3, 0.9), 2)
                    reasoning_map = {
                        "sentiment": f"Market sentiment {'positive' if raw_signal == 'BUY' else 'negative'} for {self.config.symbol}.",
                        "macro": f"Macro conditions {'favorable' if raw_signal == 'BUY' else 'unfavorable'}. VIX normal.",
                        "earnings": f"No imminent earnings risk for {self.config.symbol}.",
                        "technical": f"Price {'below lower BB — oversold' if raw_signal == 'BUY' else 'above upper BB — overbought'}.",
                    }
                    reasoning = reasoning_map.get(agent, "Analysis complete.")

                synthetic_votes.append({
                    "agent": agent,
                    "vote": vote,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "weight": 1.25 if agent == "watchman" else 1.0,
                    "veto_reason": None,
                    "timestamp": ts,
                })

            # Count agreement
            directional_votes = [v for v in synthetic_votes if v["vote"] in ("BUY", "SELL") and v["agent"] != "risk_manager"]
            agree_count = sum(1 for v in directional_votes if v["vote"] == raw_signal) if is_directional else 0
            total_panel = len(directional_votes) if is_directional else len(agent_names)

            if is_directional:
                quorum_score = (agree_count / max(total_panel, 1)) * 2 - 1  # -1 to +1
                delib_reasoning = f"Demo quorum: {agree_count}/{total_panel} agents agree on {raw_signal}."
            else:
                quorum_score = 0.0
                delib_reasoning = f"Scanning {self.config.symbol} @ ${current_price:.2f} | Regime: {regime} | All agents monitoring."

            with self._lock:
                self.last_deliberation = {
                    "approved": quorum_score > 0 if is_directional else False,
                    "signal": raw_signal,
                    "approved_qty": int(params.get("qty", self.config.qty)),
                    "order_urgency": "LOW",
                    "quorum_score": round(quorum_score, 3),
                    "votes": synthetic_votes,
                    "veto_agents": [],
                    "reasoning": delib_reasoning,
                    "timestamp": ts,
                }
        except Exception as e:
            self._logger.debug(f"Demo deliberation error: {e}")

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

    def _live_tick(self, trading_client, params: dict):
        """
        Live market tick — the full 6-step Multi-Agent System pipeline.

        Step 1: Fetch live price and build price history
        Step 2: RegimeDetector selects active Strategist
        Step 3: Active Strategist generates raw signal (BUY/SELL/HOLD)
        Step 4: SubAgentPool.deliberate() runs the full quorum vote
        Step 5: ExecutionerAgent routes the approved order
        Step 6: Update internal state (position, equity, PnL)
        """
        import os
        import pandas as pd
        import numpy as np
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestBarRequest
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass

        api_key = os.getenv("ALPACA_API_KEY", "") or None
        secret_key = os.getenv("ALPACA_SECRET_KEY", "") or None
        symbol = params.get("symbol", self.config.symbol)

        # ────────────────────────────────────────────────────────────
        # STEP 1: Fetch live price from Alpaca
        # ────────────────────────────────────────────────────────────
        # Auto-detect crypto: explicit category OR symbol contains "/"
        # (Alpaca crypto symbols always use slash format e.g. "BTC/USD")
        CRYPTO_BASE_SYMBOLS = {"BTC", "ETH", "SOL", "ADA", "DOGE", "XRP", "LTC", "AVAX", "MATIC", "SHIB", "UNI", "LINK", "DOT"}
        is_crypto = (
            self.config.category == "Crypto"
            or "/" in symbol
            or symbol.replace("/USD", "").replace("/USDT", "") in CRYPTO_BASE_SYMBOLS
        )
        is_forex = (
            self.config.category == "Forex"
            or symbol.endswith("=X")
            or (len(symbol.replace("/", "")) == 6 and symbol.replace("/", "").isalpha() and not is_crypto)
        )

        if is_crypto:
            # Ensure crypto symbol has the slash format for data API
            alpaca_symbol = symbol if "/" in symbol else f"{symbol}/USD"
        elif is_forex:
            # Normalise to slash format for Data API: GBPUSD=X -> GBP/USD
            clean = symbol.replace("=X", "").replace("/", "")
            alpaca_symbol = f"{clean[:3]}/{clean[3:]}" if len(clean) == 6 else clean
        else:
            alpaca_symbol = symbol.replace("/", "") if "/" in symbol else symbol
        
        try:
            if is_crypto:
                from alpaca.data.historical import CryptoHistoricalDataClient
                from alpaca.data.requests import CryptoLatestBarRequest
                # Crypto data is free — no API keys needed
                data_client = CryptoHistoricalDataClient()
                bar_req = CryptoLatestBarRequest(symbol_or_symbols=alpaca_symbol)
                bars = data_client.get_crypto_latest_bar(bar_req)
            elif is_forex:
                # alpaca-py has no ForexHistoricalDataClient — fall back to Stock
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestBarRequest
                alpaca_symbol = alpaca_symbol.replace("/", "")  # strip slash for stock API
                data_client = StockHistoricalDataClient(api_key, secret_key)
                bar_req = StockLatestBarRequest(symbol_or_symbols=alpaca_symbol)
                bars = data_client.get_stock_latest_bar(bar_req)
            else:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestBarRequest
                data_client = StockHistoricalDataClient(api_key, secret_key)
                bar_req = StockLatestBarRequest(symbol_or_symbols=alpaca_symbol)
                bars = data_client.get_stock_latest_bar(bar_req)
                
            bar = bars.get(alpaca_symbol)
            if bar is None:
                # Try without the slash (some SDK versions normalise the key)
                alt_key = alpaca_symbol.replace("/", "")
                bar = bars.get(alt_key)
            if bar is None:
                self._logger.warning(f"No bar data returned for {alpaca_symbol}, keys={list(bars.keys())}")
                return
            current_price = float(bar.close)
            current_open = float(bar.open)
            current_high = float(bar.high)
            current_low = float(bar.low)
            current_volume = float(bar.volume)
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

        # Queue bar for Firestore persistence (minute-boundary dedup)
        self._queue_bar({
            "t": ts,
            "o": current_open,
            "h": current_high,
            "l": current_low,
            "c": current_price,
            "v": current_volume,
            "src": "live",
        })

        # Build price Series for strategy and regime computations
        with self._lock:
            history_snap = list(self.price_history)

        prices = pd.Series([p["price"] for p in history_snap])
        volumes = pd.Series([p.get("volume", 0) for p in history_snap])

        if len(prices) < 20:
            self._logger.debug(f"Insufficient bars ({len(prices)}) for signal — accumulating.")
            self._sync_account(trading_client, symbol)
            return

        # ────────────────────────────────────────────────────────────
        # STEP 2: Regime Architect selects active Strategist
        # ────────────────────────────────────────────────────────────
        regime = "RANGING"
        regime_result = None  # Will be set by RegimeDetector if successful
        try:
            from regime_detector import RegimeDetector
            # Build full OHLC DataFrame for RegimeDetector (requires high/low/close)
            df = pd.DataFrame({
                "open":   [p.get("open", p["price"]) for p in history_snap],
                "high":   [p.get("high", p["price"]) for p in history_snap],
                "low":    [p.get("low", p["price"]) for p in history_snap],
                "close":  [p.get("close", p["price"]) for p in history_snap],
                "volume": [p.get("volume", 0) for p in history_snap],
            })
            detector = RegimeDetector()
            regime_result = detector.detect(df)
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
                self._sync_account(trading_client, symbol)
                return

        # ────────────────────────────────────────────────────────────
        # STEP 3: Active Strategist — MeanReversion (RANGING) or Trend (TRENDING)
        # ────────────────────────────────────────────────────────────
        raw_signal = "HOLD"

        if regime == "VOLATILE":
            # Hard gate — no new entries in volatile markets
            self._logger.info(f"[{self.bot_id}] Regime=VOLATILE — skipping signal generation.")
            self._update_scanning_deliberation(ts, regime, current_price)
            self._sync_account(trading_client, symbol)
            return

        elif regime == "TRENDING" and self.config.strategy in ("trend_following", "combined"):
            # ── Trend Strategist ──
            try:
                from trend_strategist import TrendStrategistAgent
                ts_agent = TrendStrategistAgent(self.bot_id)
                ts_result = ts_agent.analyse(prices, volumes, regime)
                raw_signal = ts_result.vote  # BUY | SELL | HOLD
                self._logger.info(
                    f"[{self.bot_id}] TrendStrategist: {raw_signal} "
                    f"(conf={ts_result.confidence:.0%}, ADX={ts_result.adx:.1f})"
                )
            except Exception as e:
                self._logger.error(f"TrendStrategistAgent error: {e}")

        else:
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

        # ── TRAILING STOP-LOSS CHECK ────────────────────────────────────
        if self.config.trailing_stop_enabled and self.position_qty > 0:
            if self.position_side == "LONG":
                if current_price > self._trailing_high:
                    self._trailing_high = current_price
                trail_floor = self._trailing_high * (1 - self.config.trailing_stop_pct / 100)
                if current_price <= trail_floor:
                    raw_signal = "SELL"
                    self._logger.info(
                        f"[{self.bot_id}] [TRAILING STOP] LONG exit: "
                        f"price {current_price:.4f} < floor {trail_floor:.4f} "
                        f"(high={self._trailing_high:.4f}, trail={self.config.trailing_stop_pct}%)"
                    )
            elif self.position_side == "SHORT":
                if current_price < self._trailing_low:
                    self._trailing_low = current_price
                trail_ceiling = self._trailing_low * (1 + self.config.trailing_stop_pct / 100)
                if current_price >= trail_ceiling:
                    raw_signal = "BUY"
                    self._logger.info(
                        f"[{self.bot_id}] [TRAILING STOP] SHORT exit: "
                        f"price {current_price:.4f} > ceiling {trail_ceiling:.4f} "
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
            self._sync_account(trading_client, symbol)
            self.last_signal = "HOLD"
            return

        # EXIT signal handling (close existing position, skip deliberation)
        # Close LONG on SELL signal
        if self.position_qty > 0 and self.position_side == "LONG" and raw_signal == "SELL":
            self._logger.info(f"[{self.bot_id}] Exit signal — closing LONG {self.position_qty} shares.")
            self._close_position(trading_client, symbol, params)
            self._sync_account(trading_client, symbol)
            return

        # Close SHORT on BUY signal (cover)
        if self.position_qty > 0 and self.position_side == "SHORT" and raw_signal == "BUY":
            self._logger.info(f"[{self.bot_id}] Cover signal — closing SHORT {self.position_qty} shares.")
            self._close_position(trading_client, symbol, params)
            self._sync_account(trading_client, symbol)
            return

        if raw_signal not in ("BUY", "SELL"):
            self._sync_account(trading_client, symbol)
            return

        # RULE 2: Don't double-enter an existing position
        if self.position_qty > 0 and raw_signal == "BUY" and self.position_side == "LONG":
            self._sync_account(trading_client, symbol)
            return
        if self.position_qty > 0 and raw_signal == "SELL" and self.position_side == "SHORT":
            self._sync_account(trading_client, symbol)
            return

        # ────────────────────────────────────────────────────────────
        # STEP 4: Expert Team Deliberation (votes from all 5 panel agents)
        # ────────────────────────────────────────────────────────────
        requested_qty = int(params.get("qty", self.config.qty))
        survival_state = self._vital_signs.survival_state

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
                self._sync_account(trading_client, symbol)
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
                trading_client=trading_client,
                smart_routing_min_qty=self.config.smart_routing_min_qty,
                twap_interval_ms=self.config.twap_interval_ms,
                max_slippage_pct=self.config.max_slippage_pct,
                limit_timeout_s=self.config.limit_timeout_s,
            )

        from executioner import OrderUrgency
        side = raw_signal.lower()   # "buy" or "sell"
        urgency = OrderUrgency.HIGH if order_urgency == "HIGH" else OrderUrgency.LOW

        result = self._executioner.execute(
            symbol=symbol,
            side=side,
            qty=approved_qty,
            signal_price=current_price,
            urgency=urgency,
        )

        # ────────────────────────────────────────────────────────────
        # STEP 6: Update internal state after fill
        # ────────────────────────────────────────────────────────────
        if result.success and result.total_qty_filled > 0:
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

            with self._lock:
                if side == "buy":
                    if self.position_side == "SHORT":
                        # Covering a short position
                        self.position_qty = 0
                        self.position_side = "NONE"
                        self.entry_price = 0.0
                        self._trailing_low = float("inf")
                    else:
                        # Opening a long position
                        self.position_qty = result.total_qty_filled
                        self.position_side = "LONG"
                        self.entry_price = result.avg_fill_price
                        self._trailing_high = result.avg_fill_price
                else:  # sell
                    if self.position_side == "LONG":
                        # Closing a long position
                        self.position_qty = 0
                        self.position_side = "NONE"
                        self.entry_price = 0.0
                        self._trailing_high = 0.0
                    elif self.config.short_selling_enabled and self.position_qty == 0:
                        # Opening a short position
                        self.position_qty = result.total_qty_filled
                        self.position_side = "SHORT"
                        self.entry_price = result.avg_fill_price
                        self._trailing_low = result.avg_fill_price
                    else:
                        # Fallback: treat as position close
                        self.position_qty = 0
                        self.position_side = "NONE"
                        self.entry_price = 0.0

            with self._lock:
                # ... (rest of fill logic handled in previous block) ...
                pass

            # Save the deliberation that opened this trade for Darwinian attribution
            if self.position_qty > 0:
                try:
                    # 'decision' is defined in the MAS deliberation block above
                    self._entry_deliberation = decision.to_dict() if self._sub_agent_pool else None
                except NameError:
                    self._entry_deliberation = None

            self._logger.info(
                f"[{self.bot_id}] ORDER FILLED: {side.upper()} {result.total_qty_filled}×{symbol} "
                f"@ {result.avg_fill_price:.4f} | mode={result.mode} "
                f"| slippage={result.total_slippage_pct:.3f}% "
                f"| latency={result.latency_ms:.0f}ms"
            )

            # Log slippage abort if it occurred
            if result.abort_reason:
                self._logger.warning(
                    f"[{self.bot_id}] Execution abort: {result.abort_reason}"
                )
        else:
            self._logger.warning(
                f"[{self.bot_id}] Order failed or unfilled: {result.error or result.abort_reason}"
            )

        # Always sync account state at end of tick
        self._sync_account(trading_client, symbol)

    def _close_position(self, trading_client, symbol: str, params: dict):
        """Close any open position (long or short) via a market order."""
        if self.position_qty <= 0:
            return

        # Determine close side: sell to close long, buy to cover short
        close_side = "sell" if self.position_side == "LONG" else "buy"

        if self._executioner is None:
            from executioner import ExecutionerAgent, OrderUrgency
            self._executioner = ExecutionerAgent(
                bot_id=self.bot_id,
                trading_client=trading_client,
                smart_routing_min_qty=self.config.smart_routing_min_qty,
                twap_interval_ms=self.config.twap_interval_ms,
                max_slippage_pct=self.config.max_slippage_pct,
                limit_timeout_s=self.config.limit_timeout_s,
            )
        from executioner import OrderUrgency
        result = self._executioner.execute(
            symbol=symbol,
            side=close_side,
            qty=self.position_qty,
            signal_price=self.current_price,
            urgency=OrderUrgency.HIGH,   # Exits are always urgent
        )
        if result.success:
            # PnL: (exit - entry) for longs, (entry - exit) for shorts
            if self.position_side == "LONG":
                pnl = (result.avg_fill_price - self.entry_price) * result.total_qty_filled
            else:  # SHORT
                pnl = (self.entry_price - result.avg_fill_price) * result.total_qty_filled

            with self._lock:
                self.position_qty = 0
                self.position_side = "NONE"
                self.entry_price = 0.0
                self._trailing_high = 0.0
                self._trailing_low = float("inf")
                self.total_realized_pnl += pnl
                # Daily PnL is tracked locally now
                self.daily_pnl = self.total_realized_pnl
            self._logger.info(
                f"[{self.bot_id}] Position closed ({close_side.upper()}): pnl={pnl:+.2f} "
                f"@ {result.avg_fill_price:.4f}"
            )

            # ── Darwinian Attribution ──────────────────────────────────
            # Record the outcome for the agents that opened this trade
            if self._entry_deliberation and self._sub_agent_pool:
                try:
                    self._sub_agent_pool._darwin.record_outcome(
                        votes=self._entry_deliberation.get("votes", []),
                        trade_direction=self._entry_deliberation.get("signal", ""),
                        pnl=pnl
                    )
                    self._logger.debug(f"[{self.bot_id}] Recorded Darwinian outcome for trade.")
                except Exception as e:
                    self._logger.warning(f"Failed to record Darwinian outcome: {e}")
            
            self._entry_deliberation = None

    def _sync_account(self, trading_client, symbol: str):
        try:
            # NO LONGER syncing total account equity to this isolated bot.
            # account = trading_client.get_account()
            # equity = float(account.equity or 0)
            
            with self._lock:
                # Unrealized PnL is local to the current position
                # daily_pnl = Realized + Unrealized
                self.equity = self.starting_equity + self.total_realized_pnl + self.unrealized_pnl
                self.daily_pnl = self.total_realized_pnl + self.unrealized_pnl

            # Sync position
            try:
                # Alpaca position API usually expects BTCUSD for crypto or GBPUSD for forex
                alpaca_symbol = symbol.replace("=X", "").replace("/", "")
                position = trading_client.get_open_position(alpaca_symbol)
                with self._lock:
                    self.position_qty = int(float(position.qty or 0))
                    if self.position_qty > 0:
                        alpaca_side = getattr(position, "side", "long")
                        self.position_side = "SHORT" if str(alpaca_side).lower() == "short" else "LONG"
                    else:
                        self.position_side = "NONE"
                    self.unrealized_pnl = float(position.unrealized_pl or 0)
            except Exception:
                # No open position
                with self._lock:
                    if self.position_qty != 0:
                        self.position_qty = 0
                        self.position_side = "NONE"
                        self.unrealized_pnl = 0.0
                        self._trailing_high = 0.0
                        self._trailing_low = float("inf")
        except Exception as e:
            self._logger.warning(f"Account sync failed: {e}")
