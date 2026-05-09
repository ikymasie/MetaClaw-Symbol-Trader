"""
TradeClaw — Market Regime Detector
====================================
Teaches the bot WHEN to hunt and WHEN to hide.

The single biggest cause of mean-reversion losses is trading the wrong regime.
A Bollinger Band BUY signal in a trending market is not an edge — it's a trap.

Regime Classification:
  • RANGING    — ADX < trend_threshold AND ATR z-score normal
                 Mean reversion is prime. BB + Fib signals are reliable.
  • TRENDING   — ADX > trend_threshold
                 Price has directional momentum. Mean reversion loses here.
                 Gate all new entries unless momentum is aligned.
  • VOLATILE   — ATR z-score > 2.0 (volatility spike)
                 Spreads widen, slippage risk rises. Reduce exposure.

Derived from Statistical Arbitrage principles — the bot knows whether
the "pairs relationship" (price vs. its own mean) is exploitable right now.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("tradeclaw.regime")

# Regime labels
REGIME_RANGING   = "RANGING"
REGIME_TRENDING  = "TRENDING"
REGIME_VOLATILE  = "VOLATILE"
REGIME_UNKNOWN   = "UNKNOWN"

# Default parameters (overridable via config)
DEFAULT_ADX_PERIOD          = 14
DEFAULT_ADX_TREND_THRESHOLD = 25.0
DEFAULT_ATR_PERIOD          = 14
DEFAULT_ATR_ZSCORE_WINDOW   = 50    # Window for ATR rolling z-score
DEFAULT_ATR_VOLATILE_ZSCORE = 2.0   # z-score above this = VOLATILE


@dataclass
class RegimeState:
    """The organism's current understanding of the market's personality."""
    regime: str                        # RANGING | TRENDING | VOLATILE | UNKNOWN
    adx: float                         # Current ADX value
    atr: float                         # Current ATR value
    atr_zscore: float                  # ATR rolling z-score
    trend_direction: str               # "bullish" | "bearish" | "flat"
    can_mean_revert: bool              # True if mean reversion is viable
    confidence: str                    # "HIGH" | "MEDIUM" | "LOW"
    reason: str                        # Log-friendly explanation

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "adx": round(self.adx, 2),
            "atr": round(self.atr, 4),
            "atr_zscore": round(self.atr_zscore, 2),
            "trend_direction": self.trend_direction,
            "can_mean_revert": self.can_mean_revert,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Average True Range — measures raw volatility (not direction).
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.rolling(window=period, min_periods=period).mean()


def _compute_adx(df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Average Directional Index (Wilder's ADX).
    Returns (ADX, +DI, -DI).

    ADX < 20  → no clear trend (ranging)
    ADX 20-25 → weak trend forming
    ADX > 25  → strong trend — mean reversion is dangerous here
    ADX > 40  → very strong trend — DO NOT fade it
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # Directional Movement
    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    # Wilder's smoothing (equivalent to EMA with alpha=1/period)
    atr_raw = _compute_atr(df, period)

    smooth_plus  = plus_dm_s.rolling(window=period, min_periods=period).mean()
    smooth_minus = minus_dm_s.rolling(window=period, min_periods=period).mean()

    plus_di  = 100 * smooth_plus  / atr_raw.replace(0, np.nan)
    minus_di = 100 * smooth_minus / atr_raw.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window=period, min_periods=period).mean()

    return adx, plus_di, minus_di


class RegimeDetector:
    """
    The Organism's Environmental Awareness Module.

    The organism does not fight blindly. Before every hunt, it reads
    the terrain — is this a field (RANGING) where it can stalk prey,
    or a river current (TRENDING) that will sweep it away?

    Usage:
        detector = RegimeDetector(adx_period=14, adx_trend_threshold=25)
        state = detector.detect(df)
        if state.can_mean_revert:
            # Proceed with BB / Fib signal evaluation
    """

    def __init__(
        self,
        adx_period: int = DEFAULT_ADX_PERIOD,
        adx_trend_threshold: float = DEFAULT_ADX_TREND_THRESHOLD,
        atr_period: int = DEFAULT_ATR_PERIOD,
        atr_zscore_window: int = DEFAULT_ATR_ZSCORE_WINDOW,
        atr_volatile_zscore: float = DEFAULT_ATR_VOLATILE_ZSCORE,
    ):
        self.adx_period          = adx_period
        self.adx_trend_threshold = adx_trend_threshold
        self.atr_period          = atr_period
        self.atr_zscore_window   = atr_zscore_window
        self.atr_volatile_zscore = atr_volatile_zscore

        # Cache last state
        self._last_state: Optional[RegimeState] = None

    def detect(self, df: pd.DataFrame) -> RegimeState:
        """
        Classify the current market regime from OHLC price data.
        Requires columns: open, high, low, close.
        Minimum bars: adx_period * 2 (recommended: 60+).
        """
        min_bars = max(self.adx_period * 2, self.atr_zscore_window, 30)

        if df.empty or len(df) < min_bars:
            state = RegimeState(
                regime=REGIME_UNKNOWN,
                adx=0.0,
                atr=0.0,
                atr_zscore=0.0,
                trend_direction="flat",
                can_mean_revert=False,  # Conservative: block trading until regime is known
                confidence="LOW",
                reason=f"Insufficient data ({len(df)} bars, need {min_bars}). Blocking trades for safety.",
            )
            self._last_state = state
            return state

        try:
            adx_series, plus_di, minus_di = _compute_adx(df, self.adx_period)
            atr_series = _compute_atr(df, self.atr_period)

            adx_clean = adx_series.dropna()
            plus_di_clean = plus_di.dropna()
            minus_di_clean = minus_di.dropna()
            atr_clean = atr_series.dropna()

            if adx_clean.empty or plus_di_clean.empty or minus_di_clean.empty or atr_clean.empty:
                state = RegimeState(
                    regime=REGIME_UNKNOWN,
                    adx=0.0,
                    atr=0.0,
                    atr_zscore=0.0,
                    trend_direction="flat",
                    can_mean_revert=False,  # Conservative: block trading until regime is known
                    confidence="LOW",
                    reason="Insufficient valid indicator data after calculation.",
                )
                self._last_state = state
                return state

            # Latest valid values
            adx_val    = float(adx_clean.iloc[-1])
            plus_di_v  = float(plus_di_clean.iloc[-1])
            minus_di_v = float(minus_di_clean.iloc[-1])
            atr_val    = float(atr_clean.iloc[-1])

            # ATR z-score (how abnormal is current volatility vs. its own history?)
            atr_window = atr_clean.iloc[-self.atr_zscore_window:]
            atr_mean   = float(atr_window.mean())
            atr_std    = float(atr_window.std())
            atr_zscore = (atr_val - atr_mean) / atr_std if atr_std > 0 else 0.0

            # Trend direction from DI lines
            if plus_di_v > minus_di_v:
                trend_direction = "bullish"
            elif minus_di_v > plus_di_v:
                trend_direction = "bearish"
            else:
                trend_direction = "flat"

            # ── REGIME CLASSIFICATION ────────────────────────────────────
            if atr_zscore >= self.atr_volatile_zscore:
                # Volatility spike overrides everything — danger zone
                regime = REGIME_VOLATILE
                can_mean_revert = False
                confidence = "HIGH"
                reason = (
                    f"VOLATILE: ATR z-score {atr_zscore:.2f} ≥ {self.atr_volatile_zscore}. "
                    f"Abnormal volatility spike — slippage risk elevated. Entries suppressed."
                )

            elif adx_val >= self.adx_trend_threshold:
                # Strong directional momentum — mean reversion loses here
                regime = REGIME_TRENDING
                can_mean_revert = False
                # Confidence scales with ADX strength
                if adx_val >= 40:
                    confidence = "HIGH"
                elif adx_val >= 30:
                    confidence = "MEDIUM"
                else:
                    confidence = "LOW"
                reason = (
                    f"TRENDING ({trend_direction.upper()}): ADX {adx_val:.1f} ≥ {self.adx_trend_threshold}. "
                    f"+DI={plus_di_v:.1f} / -DI={minus_di_v:.1f}. "
                    f"Mean reversion is a trap here. Patient predators wait."
                )

            else:
                # Low ADX, normal ATR — the organism's prime hunting ground
                regime = REGIME_RANGING
                can_mean_revert = True
                if adx_val < 15:
                    confidence = "HIGH"
                elif adx_val < 20:
                    confidence = "MEDIUM"
                else:
                    confidence = "LOW"   # ADX 20-25 = borderline
                reason = (
                    f"RANGING: ADX {adx_val:.1f} < {self.adx_trend_threshold}. "
                    f"ATR z-score {atr_zscore:.2f} (normal). "
                    f"Mean reversion terrain confirmed. The hunt is on."
                )

            state = RegimeState(
                regime=regime,
                adx=adx_val,
                atr=atr_val,
                atr_zscore=atr_zscore,
                trend_direction=trend_direction,
                can_mean_revert=can_mean_revert,
                confidence=confidence,
                reason=reason,
            )

            if self._last_state is None or self._last_state.regime != state.regime:
                logger.info(
                    f"[REGIME] 🌍 Regime shift → {regime} | "
                    f"ADX={adx_val:.1f} | ATR_z={atr_zscore:.2f} | "
                    f"Trend={trend_direction}"
                )

            self._last_state = state
            return state

        except Exception as e:
            logger.error(f"[REGIME] Detection error: {e}", exc_info=True)
            state = RegimeState(
                regime=REGIME_UNKNOWN,
                adx=0.0,
                atr=0.0,
                atr_zscore=0.0,
                trend_direction="flat",
                can_mean_revert=False,  # Conservative: block trading until regime is known
                confidence="LOW",
                reason=f"Detection error: {e}",
            )
            self._last_state = state
            return state

    def get_last_state(self) -> Optional[RegimeState]:
        """Returns the most recently computed regime state."""
        return self._last_state
