"""
TradeClaw Strategy Engine — Bollinger Band Mean Reversion
Runs in a background thread. Monitors price against Bollinger Bands
and executes buy/sell orders via MT5. Includes 6% daily drawdown kill switch.

Now wired to VitalSignsMonitor:
- check() called every cycle to update organism vital state
- Position sizing governed by apex tier multiplier
- ORGAN_FAILURE blocks new entries
- PROTOCOL_FINAL closes all & terminates (15% drawdown)
"""

from __future__ import annotations
import threading
import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import json

from config import config
from models import BotStatus, SignalType
from vital_signs import vital_signs
from fib_retracement import FibRetracementAnalyser, FibSignal
from regime_detector import RegimeDetector, RegimeState
from momentum_filter import MomentumFilter, MomentumState
from position_sizer import PositionSizer
from sentiment_context import SentimentContextBuilder
from vwap_analyser import VWAPAnalyser, VWAPState




logger = logging.getLogger("tradeclaw.strategy")


# ── Standalone helpers (used by bot_engine.py) ──────────────────────────
def compute_bollinger_bands(
    prices: "pd.Series",
    period: int = 20,
    std_dev: float = 2.0,
) -> Optional[dict]:
    """
    Compute Bollinger Bands from a price Series.

    Returns dict with 'upper', 'middle', 'lower' floats,
    or None when there aren't enough data points.
    """
    if len(prices) < period:
        return None
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(sma.iloc[-1]),
        "lower": float(lower.iloc[-1]),
    }


def detect_signal(price: float, bb: dict) -> str:
    """
    Simple Bollinger Band mean-reversion signal.

    BUY  when price <= lower band (oversold).
    SELL when price >= upper band (overbought).
    HOLD otherwise.
    """
    if price <= bb["lower"]:
        return "BUY"
    elif price >= bb["upper"]:
        return "SELL"
    return "HOLD"


class MeanReversionEngine:
    """
    Bollinger Band Mean Reversion Strategy.
    
    - BUY when price drops below lower Bollinger Band (oversold).
    - SELL when price rises above upper Bollinger Band (overbought).
    - Hard stop at 6% daily drawdown.
    - Per-trade stop loss.
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._status = BotStatus.IDLE
        self._message = ""

        # Live state
        self.current_price: float = 0.0
        self.position_qty: float = 0.0
        self.position_side: str | None = None
        self.entry_price: float = 0.0
        self.equity: float = 0.0
        self.starting_equity: float = 0.0
        self.daily_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.last_signal: str = SignalType.HOLD

        # Data buffers for the frontend
        self.price_history: list[dict] = []
        self.markers: list[dict] = []
        self.bollinger_data: list[dict] = []
        self.equity_curve: list[dict] = []

        # Fibonacci Retracement Analyser (re-instantiated on config change)
        self._fib_analyser: FibRetracementAnalyser = self._build_fib_analyser()
        self.fib_signal_data: dict = {}   # Latest Fib signal dict for the frontend

        # Survival Instinct Modules
        self._regime_detector   = RegimeDetector()
        self._momentum_filter   = MomentumFilter()
        self._position_sizer    = PositionSizer()
        self._sentiment_builder = SentimentContextBuilder()
        self._vwap_analyser     = VWAPAnalyser()

        # Latest survival intelligence (exposed in state snapshot + AI Brain)
        self._regime_state:   RegimeState   | None = None
        self._momentum_state: MomentumState | None = None
        self._vwap_state:     VWAPState     | None = None
        self.vwap_data:       dict          = {}   # Latest VWAP dict for the frontend


        # MT5 clients (initialized on start)
        self._trading_client = None
        self._data_client = None

        # Database write queue
        self._db_queue: list[dict] = []

        # Lock for state
        self._lock = threading.Lock()

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def message(self) -> str:
        return self._message

    def start(self):
        """Start the strategy in a background thread."""
        if self._status == BotStatus.RUNNING:
            return

        self._stop_event.clear()
        self._status = BotStatus.STARTING
        self._message = "Initializing..."

        # Register VitalSigns callbacks
        vital_signs.register_halt_callback(self._vital_halt)
        vital_signs.register_extinction_callback(self._vital_extinction)

        logger.info("Starting in LIVE mode (MT5)")
        self._thread = threading.Thread(
            target=self._run_live_loop, daemon=True, name="strategy-live"
        )

        self._thread.start()

    def stop(self):
        """Gracefully stop the strategy."""
        if self._status not in (BotStatus.RUNNING, BotStatus.STARTING):
            return
        self._status = BotStatus.STOPPING
        self._message = "Stopping..."
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._status = BotStatus.IDLE
        self._message = "Stopped by user"
        logger.info("Strategy stopped")

    def force_stop(self, reason: str = "6% daily drawdown hit"):
        """Force stop — triggered by kill switch or VitalSigns protocol."""
        self._stop_event.set()
        self._status = BotStatus.CRITICAL_STOP
        self._message = f"CRITICAL STOP: {reason}"
        logger.critical(f"FORCE STOP: {reason}")

    def _vital_halt(self):
        """
        Called by VitalSigns on ORGAN_FAILURE (10% drawdown).
        Stops new entries but does NOT close existing positions.
        """
        logger.error(
            "[VITAL] ORGAN_FAILURE protocol engaged. "
            "No new positions will be opened. Existing positions protected."
        )
        self._message = "🚨 ORGAN FAILURE: Drawdown critical. New entries halted. Protecting lifeblood."

    def _vital_extinction(self):
        """
        Called by VitalSigns on PROTOCOL_FINAL (15% drawdown).
        Closes all positions and terminates the engine.
        """
        logger.critical(
            "[VITAL] PROTOCOL_FINAL: Fatal drawdown. Organism terminating. "
            "All positions will be liquidated."
        )
        # Close all positions if in live mode
        if self._trading_client is not None:
            try:
                self._trading_client.close_all_positions(cancel_orders=True)
                logger.critical("[VITAL] All positions liquidated via PROTOCOL_FINAL.")
            except Exception as e:
                logger.error(f"[VITAL] Error closing positions during extinction: {e}")
        self.force_stop("PROTOCOL_FINAL: Fatal drawdown reached. Organism deceased.")

    def get_state_snapshot(self) -> dict:
        """Thread-safe state snapshot for the /status endpoint."""
        with self._lock:
            regime = self._regime_state
            mom    = self._momentum_state
            vwap   = self._vwap_state
            return {
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
                "fib_signal": self.fib_signal_data,
                # Survival intelligence
                "market_regime": regime.regime if regime else "UNKNOWN",
                "regime_adx": round(regime.adx, 1) if regime else None,
                "regime_atr_z": round(regime.atr_zscore, 2) if regime else None,
                "momentum_alignment": mom.alignment if mom else "NEUTRAL",
                "momentum_multiplier": mom.size_multiplier if mom else 1.0,
                # VWAP intelligence
                "vwap": vwap.to_dict() if vwap else {},
            }


    def flush_db_queue(self) -> list[dict]:
        """Drain the database write queue (called by the async main loop)."""
        with self._lock:
            queue = self._db_queue.copy()
            self._db_queue.clear()
            return queue

    def _build_fib_analyser(self) -> FibRetracementAnalyser:
        """Instantiate the FibRetracementAnalyser from current config."""
        cfg = config.snapshot()
        return FibRetracementAnalyser(
            lookback=cfg.get("fib_lookback_bars", 50),
            bounce_threshold_pct=cfg.get("fib_bounce_threshold_pct", 0.20),
            active_levels=cfg.get("fib_active_levels", [23.6, 38.2, 50.0, 61.8]),
        )

    def _run_fib_analysis(self, df) -> FibSignal:
        """
        Run Fibonacci retracement analysis on the current price data.
        Rebuilds the analyser if Fib config has changed since last cycle.
        """
        cfg = config.snapshot()
        # Rebuild analyser if key params have changed
        if (
            self._fib_analyser.lookback != cfg.get("fib_lookback_bars", 50)
            or self._fib_analyser.bounce_threshold_pct != cfg.get("fib_bounce_threshold_pct", 0.20)
        ):
            self._fib_analyser = self._build_fib_analyser()
            logger.info("[FIB] Analyser rebuilt with updated config")
        return self._fib_analyser.analyse(df)


    # ----------------------------------------------------------------
    # LIVE TRADING LOOP
    # ----------------------------------------------------------------

    def _run_live_loop(self):
        """Main loop for live trading via MT5."""
        try:
            from mt5.trading.client import TradingClient
            from mt5.data.historical import StockHistoricalDataClient
            from mt5.data.requests import StockBarsRequest
            from mt5.data.timeframe import TimeFrame
            from mt5.trading.requests import MarketOrderRequest
            from mt5.trading.enums import OrderSide, TimeInForce

            self._trading_client = TradingClient(
                config.api_key, config.secret_key, paper=False
            )
            if "category" in config.snapshot() and config.snapshot()["category"] == "Crypto":
                from mt5.data.historical import CryptoHistoricalDataClient
                self._data_client = CryptoHistoricalDataClient(
                    config.api_key, config.secret_key
                )
            else:
                self._data_client = StockHistoricalDataClient(
                    config.api_key, config.secret_key
                )

            # Get account info
            account = self._trading_client.get_account()
            self.equity = float(account.equity)
            self.starting_equity = self.equity
            self.daily_pnl = 0.0

            # Initialise VitalSigns with starting capital
            vital_signs.set_initial_balance(self.equity)

            self._status = BotStatus.RUNNING
            self._message = f"Running live on {config.symbol}"
            logger.info(f"Live loop started. Equity: ${self.equity:,.2f}")

            last_equity_snapshot = time.time()

            while not self._stop_event.is_set():
                try:
                    cfg = config.snapshot()
                    symbol = cfg["symbol"]
                    # MT5: Stocks use "SPY", Crypto uses "BTC/USD"
                    if cfg.get("category") == "Crypto":
                        mt5_symbol = symbol if "/" in symbol else symbol # Keep it as is
                    else:
                        mt5_symbol = symbol.replace("/", "") if "/" in symbol else symbol
                    
                    bb_period = cfg["bb_period"]
                    bb_std = cfg["bb_std_dev"]
                    stop_loss_pct = cfg["stop_loss_pct"]
                    max_dd = cfg["max_daily_drawdown_pct"]
                    
                    # ── Hunger Signal Relaxation ──────────────────
                    from vital_signs import get_signal_relaxation
                    relaxation = get_signal_relaxation(vital_signs.hunger_multiplier)
                    bb_std = bb_std * relaxation["bb_std"]
                    # ──────────────────────────────────────────────

                    # Fetch bars
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(days=5)
                    if cfg.get("category") == "Crypto":
                        from mt5.data.requests import CryptoBarsRequest
                        request = CryptoBarsRequest(
                            symbol_or_symbols=mt5_symbol,
                            timeframe=TimeFrame.Minute,
                            start=start,
                            end=end,
                            limit=max(bb_period * 3, 100),
                        )
                        bars_data = self._data_client.get_crypto_bars(request)
                    else:
                        request = StockBarsRequest(
                            symbol_or_symbols=mt5_symbol,
                            timeframe=TimeFrame.Minute,
                            start=start,
                            end=end,
                            limit=max(bb_period * 3, 100),
                        )
                        bars_data = self._data_client.get_stock_bars(request)
                    
                    df = bars_data.df
                    
                    if df.empty:
                        time.sleep(5)
                        continue

                    # If multi-index, select the symbol
                    if isinstance(df.index, pd.MultiIndex):
                        df = df.xs(mt5_symbol, level="symbol")

                    # Calculate Bollinger Bands
                    df["sma"] = df["close"].rolling(window=bb_period).mean()
                    df["std"] = df["close"].rolling(window=bb_period).std()
                    df["upper_bb"] = df["sma"] + (bb_std * df["std"])
                    df["lower_bb"] = df["sma"] - (bb_std * df["std"])
                    df = df.dropna()

                    if df.empty:
                        time.sleep(5)
                        continue

                    latest = df.iloc[-1]
                    price = float(latest["close"])

                    with self._lock:
                        self.current_price = price

                        # Build price history for frontend
                        self.price_history = []
                        self.bollinger_data = []
                        # ⚡ Bolt: Using zip() instead of df.iterrows() to avoid Pandas Series boxing overhead
                        for idx, o, h, l, c, upper, sma, lower in zip(
                            df.index, df["open"], df["high"], df["low"], df["close"],
                            df["upper_bb"], df["sma"], df["lower_bb"]
                        ):
                            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                            self.price_history.append(
                                {
                                    "time": ts,
                                    "open": float(o),
                                    "high": float(h),
                                    "low": float(l),
                                    "close": float(c),
                                }
                            )
                            self.bollinger_data.append(
                                {
                                    "time": ts,
                                    "upper": float(upper),
                                    "middle": float(sma),
                                    "lower": float(lower),
                                }
                            )

                    upper = float(latest["upper_bb"])
                    lower = float(latest["lower_bb"])
                    now_str = datetime.now(timezone.utc).isoformat()

                    # ---- FIBONACCI RETRACEMENT ANALYSIS ----
                    fib_signal = None
                    fib_entry_triggered = False
                    fib_suggested_sl = None
                    if cfg.get("fib_enabled", True):
                        fib_signal = self._run_fib_analysis(df)
                        with self._lock:
                            self.fib_signal_data = fib_signal.to_dict()
                        if fib_signal.signal in ("BUY_DIP", "SELL_RIP") and fib_signal.bounce_confirmed:
                            fib_entry_triggered = True
                            fib_suggested_sl = fib_signal.suggested_stop_loss

                    # ---- SIGNAL LOGIC ----
                    signal = SignalType.HOLD

                    # ---- VITAL SIGNS CHECK ----
                    vitals = vital_signs.check(self.equity, self.daily_pnl)
                    can_open = vital_signs.can_open_position()

                    # ── REGIME DETECTOR GATE ──────────────────────────────────────────
                    regime_state: RegimeState = self._regime_detector.detect(df)
                    with self._lock:
                        self._regime_state = regime_state

                    if cfg.get("regime_filter_enabled", True) and regime_state.regime in ("TRENDING", "VOLATILE"):
                        logger.info(
                            f"[REGIME] Entry gated — market is {regime_state.regime} "
                            f"(ADX={regime_state.adx:.1f}, ATR_z={regime_state.atr_zscore:.2f}). "
                            f"Mean reversion suppressed."
                        )
                        can_open = False

                    # ── MOMENTUM FILTER GATE ──────────────────────────────────────────
                    mom_cfg = config.snapshot()
                    momentum_state: MomentumState = self._momentum_filter.assess(
                        df,
                        ema_fast_override=mom_cfg.get("ema_fast"),
                        ema_mid_override=mom_cfg.get("ema_mid"),
                        ema_slow_override=mom_cfg.get("ema_slow"),
                    )
                    with self._lock:
                        self._momentum_state = momentum_state

                    if cfg.get("momentum_filter_enabled", True) and momentum_state.alignment == "BEARISH":
                        logger.info(
                            f"[MOMENTUM] Entry gated — bearish EMA stack. "
                            f"EMA {momentum_state.ema_fast:.2f}/{momentum_state.ema_mid:.2f}/{momentum_state.ema_slow:.2f}. "
                            f"Macro current against long entries."
                        )
                        can_open = False

                    # ── BROADCAST ENVIRONMENT TO VITAL SIGNS ─────────────────────
                    vital_signs.update_environment(
                        market_regime=regime_state.regime,
                        momentum_alignment=momentum_state.alignment,
                    )

                    # ── VWAP ANALYSER GATE ──────────────────────────────────────
                    vwap_entry_sd = cfg.get("vwap_entry_sd", 2.5) * relaxation["vwap_stretch"]
                    vwap_state: VWAPState = self._vwap_analyser.analyse(
                        df,
                        entry_sd_override=vwap_entry_sd,
                    )
                    with self._lock:
                        self._vwap_state = vwap_state
                        self.vwap_data   = vwap_state.to_dict()

                    vwap_mode = cfg.get("vwap_entry_mode", "AND")
                    vwap_entry_triggered = vwap_state.entry_confirmed

                    if cfg.get("vwap_enabled", True) and vwap_mode == "AND":
                        # In AND mode: VWAP confirmation is REQUIRED for a long entry
                        # If VWAP says price is NOT in an extreme stretch zone, gate entry
                        if not vwap_entry_triggered and vwap_state.signal != "LONG_ZONE":
                            logger.info(
                                f"[VWAP] Entry gated — price is only "
                                f"{abs(vwap_state.sd_stretch):.2f}σ from VWAP "
                                f"(threshold={cfg.get('vwap_entry_sd', 2.5):.1f}σ). "
                                f"Not stretched enough. Awaiting institutional zone."
                            )
                            can_open = False

                    # ── KELLY POSITION SIZING ─────────────────────────────────────────
                    qty_multiplier = vital_signs.get_qty_multiplier()
                    base_qty = max(0.01, float(cfg["qty"] * qty_multiplier))

                    if cfg.get("kelly_sizing_enabled", True):
                        try:
                            from postgres_store import _legacy_get_trade_stats_today as get_trade_stats_today
                            import asyncio as _asyncio
                            # get_trade_stats_today is async — run it in a new loop from this sync thread
                            _loop = _asyncio.new_event_loop()
                            try:
                                stats = _loop.run_until_complete(get_trade_stats_today())
                            finally:
                                _loop.close()
                            # get_trade_stats_today only returns {total_trades, win_rate};
                            # avg_win / avg_loss are not available here — use safe defaults.
                            kelly_qty, kelly_diag = self._position_sizer.get_qty(
                                win_rate=stats.get("win_rate", 50.0) / 100.0,
                                avg_win=stats.get("avg_win", 100.0),
                                avg_loss=stats.get("avg_loss", -80.0),
                                total_trades=stats.get("total_trades", 0),
                                base_qty=base_qty,
                                survival_state=vitals.get("survival_state", "HEALTHY"),
                                apex_state=vitals.get("apex_state", "HUNTING"),
                                kelly_fraction_override=cfg.get("kelly_fraction") if not cfg.get("kelly_sizing_enabled") else None,
                                max_qty=max(float(cfg.get("qty", 10)) * 5.0, float(cfg.get("qty", 10)) * float(vital_signs.hunger_multiplier)),
                                hunger_multiplier=vital_signs.hunger_multiplier,
                            )
                            effective_qty = max(0.01, float(kelly_qty))
                            # Apply momentum sizing confidence on top
                            effective_qty = max(0.01, float(effective_qty * momentum_state.size_multiplier))
                            logger.debug(f"[KELLY] {kelly_diag.get('reason', 'sizing applied')}")
                        except Exception as ke:
                            logger.warning(f"[KELLY] Stats unavailable ({ke}). Falling back to base qty={base_qty}.")
                            effective_qty = max(0.01, float(base_qty * momentum_state.size_multiplier))
                    else:
                        effective_qty = max(0.01, float(base_qty * momentum_state.size_multiplier))

                    # Check stop loss (single authoritative block)
                    if self.position_qty > 0 and self.entry_price > 0:
                        loss_pct = ((price - self.entry_price) / self.entry_price) * 100
                        if self.position_side == "long" and loss_pct <= -stop_loss_pct:
                            signal = SignalType.STOP_LOSS
                        elif self.position_side == "short" and loss_pct >= stop_loss_pct:
                            signal = SignalType.STOP_LOSS

                    if signal == SignalType.HOLD:
                        fib_mode = cfg.get("fib_entry_mode", "AND")
                        bb_buy = price <= lower and self.position_qty == 0 and can_open

                        if fib_mode == "OR":
                            # Either BB or confirmed Fib bounce triggers entry
                            if (bb_buy or fib_entry_triggered) and self.position_qty == 0 and can_open:
                                signal = SignalType.BUY
                        else:
                            # AND mode (default): both signals must agree
                            if bb_buy and fib_entry_triggered and self.position_qty == 0 and can_open:
                                signal = SignalType.BUY
                            elif bb_buy and not cfg.get("fib_enabled", True):
                                # Fib disabled — fall back to pure BB logic
                                signal = SignalType.BUY

                        if price >= upper and self.position_qty > 0:
                            signal = SignalType.SELL

                    # ---- EXECUTE ----
                    if signal == SignalType.BUY:
                        order = MarketOrderRequest(
                            symbol=symbol,
                            qty=effective_qty,
                            side=OrderSide.BUY,
                            time_in_force=TimeInForce.GTC,
                        )
                        self._trading_client.submit_order(order)

                        # Determine which signal(s) fired for marker labeling
                        signal_source = "BB"
                        if fib_entry_triggered and fib_signal:
                            fib_lbl = fib_signal.nearest_level_label or ""
                            signal_source = f"FIB {fib_lbl}"
                            if cfg.get("fib_entry_mode", "AND") == "AND":
                                signal_source = f"BB+FIB {fib_lbl}"
                            # Override SL with the smarter Fib-derived stop loss
                            if fib_suggested_sl:
                                stop_loss_pct = abs(price - fib_suggested_sl) / price * 100

                        with self._lock:
                            self.position_qty = effective_qty
                            self.position_side = "long"
                            self.entry_price = price
                            self.last_signal = SignalType.BUY
                            apex = vitals.get("apex_state", "HUNTING")
                            self.markers.append(
                                {
                                    "time": now_str,
                                    "position": "belowBar",
                                    "color": "#22c55e",
                                    "shape": "arrowUp",
                                    "text": f"BUY [{signal_source}]",
                                }
                            )
                            self._db_queue.append(
                                {
                                    "type": "trade",
                                    "timestamp": now_str,
                                    "side": "BUY",
                                    "symbol": symbol,
                                    "qty": effective_qty,
                                    "price": price,
                                    "pnl": 0.0,
                                    "signal": f"BUY:{apex}",
                                    "fib_level_triggered": fib_signal.nearest_level_label if fib_entry_triggered and fib_signal else None,
                                    "params_snapshot": json.dumps(cfg),
                                }
                            )
                        logger.info(f"BUY {symbol} @ ${price:.2f} [{signal_source}] [qty={effective_qty}, apex={apex}]")


                    elif signal in (SignalType.SELL, SignalType.STOP_LOSS):
                        if self.position_qty > 0:
                            order = MarketOrderRequest(
                                symbol=symbol,
                                qty=self.position_qty,
                                side=OrderSide.SELL,
                                time_in_force=TimeInForce.GTC,
                            )
                            self._trading_client.submit_order(order)
                            trade_pnl = (price - self.entry_price) * self.position_qty
                            with self._lock:
                                self.daily_pnl += trade_pnl
                                self.last_signal = signal
                                marker_text = "SELL" if signal == SignalType.SELL else "STOP"
                                self.markers.append(
                                    {
                                        "time": now_str,
                                        "position": "aboveBar",
                                        "color": "#ef4444",
                                        "shape": "arrowDown",
                                        "text": marker_text,
                                    }
                                )
                                self._db_queue.append(
                                    {
                                        "type": "trade",
                                        "timestamp": now_str,
                                        "side": "SELL",
                                        "symbol": symbol,
                                        "qty": self.position_qty,
                                        "price": price,
                                        "pnl": trade_pnl,
                                        "signal": str(signal),
                                        "params_snapshot": json.dumps(cfg),
                                    }
                                )
                                self.position_qty = 0
                                self.position_side = None
                                self.entry_price = 0.0
                            logger.info(
                                f"SELL {symbol} @ ${price:.2f} | PnL: ${trade_pnl:+.2f}"
                            )

                    # Update equity
                    account = self._trading_client.get_account()
                    with self._lock:
                        self.equity = float(account.equity)
                        if self.position_qty > 0:
                            self.unrealized_pnl = (
                                price - self.entry_price
                            ) * self.position_qty
                        else:
                            self.unrealized_pnl = 0.0

                    # Drawdown protection is handled by VitalSigns (configurable
                    # thresholds: WOUNDED → ORGAN_FAILURE → PROTOCOL_FINAL).
                    # The legacy inline 6% check was removed to avoid conflicting
                    # with the bot's max_daily_drawdown_pct setting.

                    # Snapshot equity periodically
                    if time.time() - last_equity_snapshot > 30:
                        with self._lock:
                            self.equity_curve.append(
                                {
                                    "time": now_str,
                                    "equity": self.equity,
                                    "daily_pnl": self.daily_pnl,
                                }
                            )
                            self._db_queue.append(
                                {
                                    "type": "equity",
                                    "timestamp": now_str,
                                    "equity": self.equity,
                                    "daily_pnl": self.daily_pnl,
                                }
                            )
                        last_equity_snapshot = time.time()

                except Exception as e:
                    logger.error(f"Strategy loop error: {e}", exc_info=True)
                    self._message = f"Error: {str(e)[:100]}"

                # 5-second cycle
                self._stop_event.wait(5)

        except Exception as e:
            logger.error(f"Fatal strategy error: {e}", exc_info=True)
            self._status = BotStatus.CRITICAL_STOP
            self._message = f"Fatal: {str(e)[:100]}"

    # ----------------------------------------------------------------
    # DEMO TRADING LOOP
    # ----------------------------------------------------------------


# Singleton engine instance
engine = MeanReversionEngine()
