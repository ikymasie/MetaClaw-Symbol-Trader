"""
TradeClaw — Triple EMA Momentum Filter
========================================
Teaches the bot which DIRECTION it's allowed to hunt.

Based on the "Turtle Strategy Evolution" from trend-following algo research.
Three Exponential Moving Averages create a macro directional bias filter:

  EMA(fast) > EMA(mid) > EMA(slow)  → BULLISH alignment → only BUY signals allowed
  EMA(fast) < EMA(mid) < EMA(slow)  → BEARISH alignment → only SELL/SHORT signals
  Mixed alignment                   → NEUTRAL            → reduce size, require stronger confluence

Default stack: EMA 8 / 21 / 55 (Fibonacci-based — no coincidence)
  • EMA 8   captures the recent micro-momentum (last ~8 bars)
  • EMA 21  is the short-term trend (commonly watched by institutions)
  • EMA 55  is the regime-level macro trend (5%) — the spine of the move

The organism that fights without knowing UP from DOWN is not a predator.
It is prey.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger("tradeclaw.momentum")

# Alignment labels
MOMENTUM_BULLISH = "BULLISH"   # All EMAs stacked bullishly
MOMENTUM_BEARISH = "BEARISH"   # All EMAs stacked bearishly
MOMENTUM_NEUTRAL = "NEUTRAL"   # Mixed / transitioning

DEFAULT_EMA_FAST = 8
DEFAULT_EMA_MID  = 21
DEFAULT_EMA_SLOW = 55


@dataclass
class MomentumState:
    """The organism's directional bias assessment."""
    alignment: str            # BULLISH | BEARISH | NEUTRAL
    ema_fast: float
    ema_mid: float
    ema_slow: float
    crossover_event: str      # e.g. "FAST_CROSS_MID_UP" | "NONE"
    allows_long: bool         # BUY signals are permitted
    size_multiplier: float    # 1.0 BULLISH | 0.5 NEUTRAL | 0.0 (or 0.5) for shorts
    reason: str

    def to_dict(self) -> dict:
        return {
            "alignment": self.alignment,
            "ema_fast": round(self.ema_fast, 4),
            "ema_mid": round(self.ema_mid, 4),
            "ema_slow": round(self.ema_slow, 4),
            "crossover_event": self.crossover_event,
            "allows_long": self.allows_long,
            "size_multiplier": self.size_multiplier,
            "reason": self.reason,
        }


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average with Wilder-style min_periods."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


class MomentumFilter:
    """
    The Organism's Directional Awareness Module.

    Mean reversion (BB/Fib) works best when the momentum is either
    neutral or momentarily reversing. This filter prevents the bot
    from buying into a freefall or selling into a rocket.

    The bot should BUY the DIPS in an UPTREND.
    Not buy the "maybe it will bounce" in a downtrend.

    Usage:
        mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)
        state = mf.assess(df)
        effective_qty = int(base_qty * state.size_multiplier)
    """

    def __init__(
        self,
        ema_fast: int = DEFAULT_EMA_FAST,
        ema_mid:  int = DEFAULT_EMA_MID,
        ema_slow: int = DEFAULT_EMA_SLOW,
    ):
        self.ema_fast = ema_fast
        self.ema_mid  = ema_mid
        self.ema_slow = ema_slow

        self._last_state: Optional[MomentumState] = None

    def assess(
        self,
        df: pd.DataFrame,
        ema_fast_override: Optional[int] = None,
        ema_mid_override: Optional[int] = None,
        ema_slow_override: Optional[int] = None,
    ) -> MomentumState:
        """
        Assess the macro directional bias from OHLC data.
        Requires the 'close' column.
        Minimum bars: ema_slow (default 55).

        Args:
            ema_fast_override: Temporarily override the fast EMA period (AI Brain tuning).
            ema_mid_override:  Temporarily override the mid EMA period.
            ema_slow_override: Temporarily override the slow EMA period.
        """
        # Apply runtime overrides (None = use constructor default)
        ema_fast = int(ema_fast_override) if ema_fast_override is not None else self.ema_fast
        ema_mid  = int(ema_mid_override)  if ema_mid_override  is not None else self.ema_mid
        ema_slow = int(ema_slow_override) if ema_slow_override is not None else self.ema_slow

        min_bars = ema_slow + 5

        if df.empty or len(df) < min_bars:
            state = MomentumState(
                alignment=MOMENTUM_NEUTRAL,
                ema_fast=0.0,
                ema_mid=0.0,
                ema_slow=0.0,
                crossover_event="NONE",
                allows_long=True,
                size_multiplier=0.5,
                reason=f"Insufficient data ({len(df)} bars, need {min_bars}). Defaulting neutral.",
            )
            self._last_state = state
            return state

        try:
            close = df["close"]

            ema_f = _ema(close, ema_fast)
            ema_m = _ema(close, ema_mid)
            ema_s = _ema(close, ema_slow)

            # Current values
            ef = float(ema_f.iloc[-1])
            em = float(ema_m.iloc[-1])
            es = float(ema_s.iloc[-1])

            # Previous values for crossover detection
            ef_prev = float(ema_f.iloc[-2]) if len(ema_f) > 1 else ef
            em_prev = float(ema_m.iloc[-2]) if len(ema_m) > 1 else em

            # ── CROSSOVER DETECTION ───────────────────────────────────
            # A crossover is a regime CHANGE signal — high-value event
            crossover_event = "NONE"
            if ef_prev <= em_prev and ef > em:
                crossover_event = "FAST_CROSS_MID_UP"
                logger.info(f"[MOMENTUM] ⬆️ Golden cross: EMA{ema_fast} crossed above EMA{ema_mid}")
            elif ef_prev >= em_prev and ef < em:
                crossover_event = "FAST_CROSS_MID_DOWN"
                logger.info(f"[MOMENTUM] ⬇️ Death cross: EMA{ema_fast} crossed below EMA{ema_mid}")

            # ── ALIGNMENT CLASSIFICATION ──────────────────────────────
            bullish_aligned = ef > em > es    # All stacked bullishly
            bearish_aligned = ef < em < es    # All stacked bearishly

            if bullish_aligned:
                alignment       = MOMENTUM_BULLISH
                allows_long     = True
                size_multiplier = 1.0
                reason = (
                    f"BULLISH STACK: EMA{ema_fast}({ef:.2f}) > "
                    f"EMA{ema_mid}({em:.2f}) > "
                    f"EMA{ema_slow}({es:.2f}). "
                    f"Macro uptrend confirmed. BUY the dips."
                )
            elif bearish_aligned:
                alignment       = MOMENTUM_BEARISH
                allows_long     = False
                # IMPORTANT CONTRACT: size_multiplier is 0.0, but callers MUST check
                # allows_long BEFORE multiplying by size_multiplier.
                # Do NOT do max(1, int(base_qty * size_multiplier)) — that coerces
                # 0 to 1 and silently opens a position. Gate on allows_long first.
                size_multiplier = 0.0
                reason = (
                    f"BEARISH STACK: EMA{ema_fast}({ef:.2f}) < "
                    f"EMA{ema_mid}({em:.2f}) < "
                    f"EMA{ema_slow}({es:.2f}). "
                    f"Macro downtrend active. Long entries are traps. Awaiting regime shift."
                )
            else:
                alignment       = MOMENTUM_NEUTRAL
                allows_long     = True
                size_multiplier = 0.5
                gap = abs(ef - es) / es * 100
                reason = (
                    f"NEUTRAL: Mixed EMA alignment. "
                    f"EMA{ema_fast}={ef:.2f} / EMA{ema_mid}={em:.2f} / EMA{ema_slow}={es:.2f}. "
                    f"Gap={gap:.2f}%. "
                    f"Proceeding at 50% position size — higher BB/Fib confluence required."
                )

            state = MomentumState(
                alignment=alignment,
                ema_fast=ef,
                ema_mid=em,
                ema_slow=es,
                crossover_event=crossover_event,
                allows_long=allows_long,
                size_multiplier=size_multiplier,
                reason=reason,
            )

            if self._last_state is None or self._last_state.alignment != state.alignment:
                logger.info(
                    f"[MOMENTUM] 🧭 Alignment shift → {alignment} | "
                    f"EMA{self.ema_fast}={ef:.2f} | EMA{self.ema_mid}={em:.2f} | EMA{self.ema_slow}={es:.2f}"
                )

            self._last_state = state
            return state

        except Exception as e:
            logger.error(f"[MOMENTUM] Assessment error: {e}", exc_info=True)
            state = MomentumState(
                alignment=MOMENTUM_NEUTRAL,
                ema_fast=0.0,
                ema_mid=0.0,
                ema_slow=0.0,
                crossover_event="NONE",
                allows_long=True,
                size_multiplier=0.5,
                reason=f"Assessment error: {e}",
            )
            self._last_state = state
            return state

    def get_last_state(self) -> Optional[MomentumState]:
        """Returns the most recently computed momentum state."""
        return self._last_state
