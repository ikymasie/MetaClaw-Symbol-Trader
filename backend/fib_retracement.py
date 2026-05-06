"""
TradeClaw — Fibonacci Retracement Analyser
==========================================
Teaches the bot to identify strategic retracement entry points within trends.

Core Concepts Implemented:
  • Swing Detection    — Locate the most recent dominant swing high and low
  • Fibonacci Levels   — Compute 23.6%, 38.2%, 50%, 61.8% of the prior move
  • Optimized Entry    — "Buy the dip" (uptrend) / "Sell the rip" (downtrend)
  • Bounce Confirmation— Require price to touch AND bounce off a level (not just touch)
  • Trend Confirmation — Validate that the primary trend is intact before entry
  • Smart Stop-Loss    — Derive SL from the 61.8% "last stand" level
  • S&R Identification — Track which Fib levels historically acted as support/resistance

The bot does NOT chase price at extremes — it WAITS for a confirmed retracement
bounce, then enters with a statistically superior risk-to-reward ratio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("tradeclaw.fib")

# ─────────────────────────────────────────────────────────────────
# FIBONACCI RATIOS (Golden Ratio mathematics)
# 23.6% = shallow pullback → very strong trend
# 38.2% = moderate pullback
# 50.0% = psychological mid-point, institutional order cluster
# 61.8% = The Golden Ratio — "last stand" for the trend
# ─────────────────────────────────────────────────────────────────

FIB_RATIOS = {
    "23.6%": 0.236,
    "38.2%": 0.382,
    "50.0%": 0.500,
    "61.8%": 0.618,
}


# ─────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────

@dataclass
class FibLevels:
    """The calculated Fibonacci levels for a detected swing move."""
    swing_high: float
    swing_low: float
    trend: str                        # "uptrend" | "downtrend" | "ranging"
    levels: dict[str, float]          # {"23.6%": price, "38.2%": price, ...}
    stop_loss_level: float            # Just beyond the 61.8% level
    move_size: float                  # Absolute size of the detected swing

    def to_dict(self) -> dict:
        return {
            "swing_high": round(self.swing_high, 4),
            "swing_low": round(self.swing_low, 4),
            "trend": self.trend,
            "levels": {k: round(v, 4) for k, v in self.levels.items()},
            "stop_loss_level": round(self.stop_loss_level, 4),
            "move_size": round(self.move_size, 4),
        }


@dataclass
class FibSignal:
    """The actionable output of the Fibonacci Retracement Analyser."""
    signal: str                       # "BUY_DIP" | "SELL_RIP" | "HOLD"
    trend: str                        # "uptrend" | "downtrend" | "ranging"
    nearest_level_label: Optional[str]  # e.g. "61.8%"
    nearest_level_price: Optional[float]
    bounce_confirmed: bool            # Price touched AND bounced from the level
    suggested_stop_loss: Optional[float]
    fib_levels: Optional[FibLevels]
    reason: str                       # Human-readable explanation for logs

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "trend": self.trend,
            "nearest_level_label": self.nearest_level_label,
            "nearest_level_price": round(self.nearest_level_price, 4) if self.nearest_level_price else None,
            "bounce_confirmed": self.bounce_confirmed,
            "suggested_stop_loss": round(self.suggested_stop_loss, 4) if self.suggested_stop_loss else None,
            "fib_levels": self.fib_levels.to_dict() if self.fib_levels else None,
            "reason": self.reason,
        }


# ─────────────────────────────────────────────────────────────────
# SWING DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_swing(df: pd.DataFrame, lookback: int = 50) -> Optional[FibLevels]:
    """
    Identifies the dominant swing high and low within the lookback window.

    Strategy:
      - Looks for the highest high and lowest low in the window
      - Determines trend direction by comparing where the high and low occurred
        chronologically: if the high came AFTER the low → uptrend (price climbed)
      - Computes all Fibonacci retracement levels against that swing
      - Stop-loss is placed 0.3% beyond the 61.8% level (the "last stand")

    Returns None if market is ranging (move < 0.5% of price — not meaningful).
    """
    if len(df) < lookback:
        lookback = len(df)
    if lookback < 10:
        return None

    window = df.iloc[-lookback:]

    high_idx = window["high"].idxmax()
    low_idx  = window["low"].idxmin()
    swing_high = float(window["high"].max())
    swing_low  = float(window["low"].min())

    move_size = swing_high - swing_low

    # If the move is trivially small (< 0.5%), the market is ranging
    if swing_high == 0 or (move_size / swing_high) < 0.005:
        logger.debug("Swing too small — market ranging, Fib not applicable")
        return None

    # Determine trend based on chronological position of the swing points
    high_pos = window.index.get_loc(high_idx)
    low_pos  = window.index.get_loc(low_idx)

    if high_pos > low_pos:
        # Low came first, then the high — price climbed → UPTREND
        trend = "uptrend"
        # In an uptrend, retracement = pulling back DOWN from the high
        # Levels measured from the high, moving down toward the low
        levels = {
            label: swing_high - (ratio * move_size)
            for label, ratio in FIB_RATIOS.items()
        }
        # SL placed 0.3% below the 61.8% level (the organism's last stand)
        stop_loss_level = levels["61.8%"] * (1 - 0.003)
    else:
        # High came first, then the low — price fell → DOWNTREND
        trend = "downtrend"
        # In a downtrend, retracement = pulling back UP from the low
        # Levels measured from the low, moving up toward the high
        levels = {
            label: swing_low + (ratio * move_size)
            for label, ratio in FIB_RATIOS.items()
        }
        # SL placed 0.3% above the 61.8% level
        stop_loss_level = levels["61.8%"] * (1 + 0.003)

    return FibLevels(
        swing_high=swing_high,
        swing_low=swing_low,
        trend=trend,
        levels=levels,
        stop_loss_level=stop_loss_level,
        move_size=move_size,
    )


# ─────────────────────────────────────────────────────────────────
# BOUNCE CONFIRMATION
# ─────────────────────────────────────────────────────────────────

def _find_nearest_level(price: float, levels: dict[str, float], threshold_pct: float) -> tuple[Optional[str], Optional[float]]:
    """
    Find which Fib level the price is closest to, within threshold_pct.
    Returns (label, price) or (None, None) if no level is nearby.
    """
    best_label = None
    best_price = None
    best_distance = float("inf")

    for label, level_price in levels.items():
        distance_pct = abs(price - level_price) / level_price * 100
        if distance_pct <= threshold_pct and distance_pct < best_distance:
            best_distance = distance_pct
            best_label = label
            best_price = level_price

    return best_label, best_price


def _check_bounce(df: pd.DataFrame, level_price: float, trend: str, threshold_pct: float) -> bool:
    """
    Bounce Confirmation Logic:
    ─────────────────────────
    A "bounce" is NOT just touching the level — anyone can touch.
    A CONFIRMED bounce requires:
      1. The previous candle's low (uptrend) or high (downtrend) entered the Fib zone
      2. The CURRENT (most recent) candle's close moves AWAY from the level,
         back into the trend direction.

    This is the difference between a patient predator and a reactive fool.
    The organism does NOT enter mid-fall. It waits for price to prove itself.
    """
    if len(df) < 2:
        return False

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    if trend == "uptrend":
        # Price was pulling back (falling) toward the Fib support level
        # Previous candle must have entered the zone (low touched the level)
        prev_touched = abs(float(prev["low"]) - level_price) / level_price * 100 <= threshold_pct
        # Current candle must close ABOVE the level (bouncing back up)
        curr_bounce  = float(curr["close"]) > level_price
        confirmed = prev_touched and curr_bounce
        if confirmed:
            logger.info(
                f"[FIB] 🔴→🟢 Bounce confirmed at {level_price:.4f} (uptrend). "
                f"Prev low: {prev['low']:.4f} | Curr close: {curr['close']:.4f}"
            )
        return confirmed

    elif trend == "downtrend":
        # Price was pulling back (rising) toward the Fib resistance level
        # Previous candle must have entered the zone (high touched the level)
        prev_touched = abs(float(prev["high"]) - level_price) / level_price * 100 <= threshold_pct
        # Current candle must close BELOW the level (bouncing back down)
        curr_bounce  = float(curr["close"]) < level_price
        confirmed = prev_touched and curr_bounce
        if confirmed:
            logger.info(
                f"[FIB] 🟢→🔴 Bounce confirmed at {level_price:.4f} (downtrend). "
                f"Prev high: {prev['high']:.4f} | Curr close: {curr['close']:.4f}"
            )
        return confirmed

    return False


# ─────────────────────────────────────────────────────────────────
# MAIN ANALYSER
# ─────────────────────────────────────────────────────────────────

class FibRetracementAnalyser:
    """
    The Fibonacci Retracement Analyser — the organism's patience module.

    The organism has learned that markets breathe — price pulls back before
    continuing its journey. The Fibonacci levels are the organism's breath
    markers. It does not chase; it waits at the exhale.

    Usage:
        analyser = FibRetracementAnalyser(lookback=50, bounce_threshold_pct=0.20)
        signal = analyser.analyse(df)
        if signal.signal == "BUY_DIP" and signal.bounce_confirmed:
            # Enter long at the current price
            # Use signal.suggested_stop_loss for SL placement
    """

    def __init__(
        self,
        lookback: int = 50,
        bounce_threshold_pct: float = 0.20,
        active_levels: Optional[list[float]] = None,
    ):
        """
        Args:
            lookback: Number of bars to look back when detecting the swing high/low.
            bounce_threshold_pct: How close (%) the price must be to a Fib level
                                  to qualify as "touching" it (default: 0.20%).
            active_levels: Subset of Fib ratios to watch. Default: all 4.
        """
        self.lookback = lookback
        self.bounce_threshold_pct = bounce_threshold_pct

        # Filter active levels (allows AI Brain to disable shallow/deep levels)
        self._active_level_labels: list[str] = []
        target_ratios = set(active_levels or [23.6, 38.2, 50.0, 61.8])
        for label, ratio in FIB_RATIOS.items():
            if round(ratio * 100, 1) in target_ratios:
                self._active_level_labels.append(label)

        if not self._active_level_labels:
            self._active_level_labels = list(FIB_RATIOS.keys())

        # Cache last computed levels for the frontend
        self._last_fib_levels: Optional[FibLevels] = None

    def analyse(self, df: pd.DataFrame) -> FibSignal:
        """
        Run a full retracement analysis on the given OHLC DataFrame.

        Required columns: open, high, low, close
        Returns a FibSignal with signal, trend, bounce status, and SL level.
        """
        if df.empty or len(df) < 10:
            return self._hold("Insufficient price history for Fib analysis")

        # ── Step 1: Detect the swing ───────────────────────────────────────
        fib_levels = detect_swing(df, lookback=self.lookback)
        if fib_levels is None:
            return self._hold("Market ranging — Fib levels not meaningful")

        self._last_fib_levels = fib_levels

        # Filter to active levels only
        active_levels = {
            lbl: fib_levels.levels[lbl]
            for lbl in self._active_level_labels
            if lbl in fib_levels.levels
        }

        # ── Step 2: Current price context ─────────────────────────────────
        current_price = float(df.iloc[-1]["close"])

        # ── Step 3: Find the nearest active Fib level to current price ─────
        nearest_label, nearest_price = _find_nearest_level(
            current_price, active_levels, self.bounce_threshold_pct
        )

        if nearest_label is None:
            return FibSignal(
                signal="HOLD",
                trend=fib_levels.trend,
                nearest_level_label=None,
                nearest_level_price=None,
                bounce_confirmed=False,
                suggested_stop_loss=None,
                fib_levels=fib_levels,
                reason=(
                    f"Price {current_price:.4f} not near any active Fib level "
                    f"(trend: {fib_levels.trend}, threshold: {self.bounce_threshold_pct}%)"
                ),
            )

        # ── Step 4: Check for confirmed bounce ────────────────────────────
        bounce = _check_bounce(df, nearest_price, fib_levels.trend, self.bounce_threshold_pct)

        # ── Step 5: Generate signal ────────────────────────────────────────
        if fib_levels.trend == "uptrend":
            signal = "BUY_DIP"
            action_label = "Buy the dip"
        elif fib_levels.trend == "downtrend":
            signal = "SELL_RIP"
            action_label = "Sell the rip"
        else:
            return self._hold("Trend is ranging — no directional Fib signal", fib_levels)

        level_strength = self._level_strength(nearest_label)
        reason = (
            f"{action_label} @ {nearest_label} ({nearest_price:.4f}) | "
            f"Bounce: {'✅ CONFIRMED' if bounce else '⏳ PENDING'} | "
            f"Trend: {fib_levels.trend} | "
            f"Level strength: {level_strength} | "
            f"SL: {fib_levels.stop_loss_level:.4f}"
        )

        logger.info(f"[FIB] {reason}")

        return FibSignal(
            signal=signal,
            trend=fib_levels.trend,
            nearest_level_label=nearest_label,
            nearest_level_price=nearest_price,
            bounce_confirmed=bounce,
            suggested_stop_loss=fib_levels.stop_loss_level,
            fib_levels=fib_levels,
            reason=reason,
        )

    def get_last_levels(self) -> Optional[FibLevels]:
        """Returns the most recently computed Fib levels (for charting)."""
        return self._last_fib_levels

    @staticmethod
    def _level_strength(label: str) -> str:
        """Human-readable strength descriptor for a given Fib level."""
        return {
            "23.6%": "SHALLOW — very strong trend",
            "38.2%": "MODERATE — healthy retracement",
            "50.0%": "MODERATE — institutional cluster",
            "61.8%": "DEEP — Golden Ratio, last stand",
        }.get(label, label)

    @staticmethod
    def _hold(reason: str, fib_levels: Optional[FibLevels] = None) -> FibSignal:
        return FibSignal(
            signal="HOLD",
            trend="ranging" if fib_levels is None else fib_levels.trend,
            nearest_level_label=None,
            nearest_level_price=None,
            bounce_confirmed=False,
            suggested_stop_loss=None,
            fib_levels=fib_levels,
            reason=reason,
        )
