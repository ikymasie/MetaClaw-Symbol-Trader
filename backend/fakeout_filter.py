"""
TradeClaw — Anti-Fakeout Filter
================================
Defensive layer that rejects *algorithmic fakeouts* — the stop-hunt /
failed-breakout / liquidity-sweep patterns that trap breakout traders.

A fakeout is the signature of an algorithm running stops: price pokes
beyond a recent swing extreme (triggering breakout orders + resting stops),
fills institutional liquidity, then snaps back through the level leaving a
long rejection wick. Anyone who entered on the naive ``price > recent_high``
breakout is now offside.

This module exposes two pure, stateless primitives used at BOTH defence
layers:

  1. ``confirm_breakout`` — SIGNAL layer (trend_strategist).
     Upgrades a naive breakout into a *confirmed* one: the bar must close
     beyond the level by an ATR-scaled buffer AND not be a rejection wick.

  2. ``detect_entry_trap`` — ENGINE entry gate (all directional entries).
     Looks at the latest bar for a sweep-and-reverse against the trade
     direction (bull trap for BUY, bear trap for SELL) and blocks the entry.

Everything is denominated in ATR so the same thresholds work across BTC,
gold, forex and synthetics without per-symbol tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd

Number = Union[float, int]
Series = Union[pd.Series, Sequence[Number]]


# ── helpers ──────────────────────────────────────────────────────────────

def _vals(series: Series) -> np.ndarray:
    """Coerce a pd.Series / list / ndarray to a float ndarray (oldest→newest)."""
    if isinstance(series, pd.Series):
        return series.to_numpy(dtype=float)
    return np.asarray(series, dtype=float)


def compute_atr(
    highs: Series,
    lows: Series,
    closes: Series,
    period: int = 14,
) -> float:
    """
    Wilder's ATR (Average True Range) from OHLC series.

    Returns the latest ATR as a float, or 0.0 if there is not enough data.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    """
    h, l, c = _vals(highs), _vals(lows), _vals(closes)
    n = min(len(h), len(l), len(c))
    if n < period + 1:
        return 0.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    prev_c = c[:-1]
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - prev_c),
        np.abs(l[1:] - prev_c),
    ])
    if len(tr) < period:
        return 0.0
    # Wilder smoothing via EMA with alpha = 1/period
    atr = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1]
    return float(atr) if np.isfinite(atr) else 0.0


# ── 1. Breakout confirmation (signal layer) ──────────────────────────────

@dataclass
class BreakoutVerdict:
    confirmed: bool
    reason: str
    atr: float = 0.0
    buffer: float = 0.0


def confirm_breakout(
    direction: str,                 # "UP" | "DOWN"
    closes: Series,
    highs: Series,
    lows: Series,
    level: float,                   # the swing high (UP) / low (DOWN) being broken
    *,
    atr: Optional[float] = None,
    buffer_mult: float = 0.25,
    wick_reject_ratio: float = 0.50,
    atr_period: int = 14,
) -> BreakoutVerdict:
    """
    Confirm that a breakout through ``level`` is real, not a fakeout.

    A breakout is CONFIRMED only when BOTH hold for the latest bar:
      (a) Penetration: close clears the level by at least ``buffer_mult`` × ATR.
          A one-tick poke (close barely past the level) is rejected — that is
          exactly what an algorithmic stop-run looks like.
      (b) No rejection wick: the wick *beyond* the level is not the dominant
          part of the bar. If ≥ ``wick_reject_ratio`` of the bar's range is the
          wick poking past the level, price was rejected → fakeout.

    Returns a BreakoutVerdict(confirmed, reason, atr, buffer).
    """
    c, h, l = _vals(closes), _vals(highs), _vals(lows)
    if min(len(c), len(h), len(l)) < 2:
        return BreakoutVerdict(False, "insufficient bars for breakout confirm")

    if atr is None:
        atr = compute_atr(highs, lows, closes, period=atr_period)
    buffer = buffer_mult * atr  # 0 when ATR unavailable → degrades to strict close-beyond

    cur_close = c[-1]
    cur_high = h[-1]
    cur_low = l[-1]
    bar_range = max(cur_high - cur_low, 1e-12)

    if direction == "UP":
        # Penetration: closed clearly above the level.
        if cur_close <= level + buffer:
            return BreakoutVerdict(
                False,
                f"weak breakout: close {cur_close:.5f} ≤ level {level:.5f} + buffer {buffer:.5f}",
                atr, buffer,
            )
        # Rejection wick: large upper wick = sellers defended the level.
        upper_wick = cur_high - cur_close
        if upper_wick >= wick_reject_ratio * bar_range:
            return BreakoutVerdict(
                False,
                f"rejection wick: upper wick {upper_wick:.5f} ≥ {wick_reject_ratio:.0%} of range {bar_range:.5f}",
                atr, buffer,
            )
        return BreakoutVerdict(True, f"confirmed UP breakout (+{cur_close - level:.5f} over level, buffer {buffer:.5f})", atr, buffer)

    elif direction == "DOWN":
        if cur_close >= level - buffer:
            return BreakoutVerdict(
                False,
                f"weak breakdown: close {cur_close:.5f} ≥ level {level:.5f} − buffer {buffer:.5f}",
                atr, buffer,
            )
        lower_wick = cur_close - cur_low
        if lower_wick >= wick_reject_ratio * bar_range:
            return BreakoutVerdict(
                False,
                f"rejection wick: lower wick {lower_wick:.5f} ≥ {wick_reject_ratio:.0%} of range {bar_range:.5f}",
                atr, buffer,
            )
        return BreakoutVerdict(True, f"confirmed DOWN breakout (−{level - cur_close:.5f} under level, buffer {buffer:.5f})", atr, buffer)

    return BreakoutVerdict(False, f"unknown direction {direction!r}")


# ── 2. Entry trap detection (engine gate) ────────────────────────────────

@dataclass
class TrapVerdict:
    is_trap: bool
    reason: str
    swing_level: float = 0.0
    atr: float = 0.0


def detect_entry_trap(
    direction: str,                 # "BUY" | "SELL"
    highs: Series,
    lows: Series,
    closes: Series,
    *,
    swing_lookback: int = 20,
    atr: Optional[float] = None,
    buffer_mult: float = 0.25,
    wick_reject_ratio: float = 0.50,
    atr_period: int = 14,
) -> TrapVerdict:
    """
    Detect a sweep-and-reverse trap on the latest bar *against* the entry.

    For a BUY we fear a BULL TRAP (buy-side liquidity sweep): the latest bar's
    high pokes meaningfully above the recent swing high (running breakout-buyer
    stops) but the bar closes back below — or barely above — that level, leaving
    an upper rejection wick. Entering long into that is buying the top of a
    stop-hunt.

    For a SELL we fear the mirror BEAR TRAP below the swing low.

    Returns TrapVerdict(is_trap, reason, swing_level, atr). Conservative: when
    data is insufficient it returns is_trap=False (do not block on ignorance).
    """
    h, l, c = _vals(highs), _vals(lows), _vals(closes)
    n = min(len(h), len(l), len(c))
    if n < swing_lookback + 1:
        return TrapVerdict(False, f"insufficient bars ({n} < {swing_lookback + 1})")

    h, l, c = h[-n:], l[-n:], c[-n:]
    if atr is None:
        atr = compute_atr(highs, lows, closes, period=atr_period)
    buffer = buffer_mult * atr

    cur_high, cur_low, cur_close = h[-1], l[-1], c[-1]

    if direction == "BUY":
        # Prior swing high, excluding the candidate (current) bar.
        swing_high = float(np.max(h[-(swing_lookback + 1):-1]))
        extension = cur_high - swing_high            # how far we poked above
        if extension <= 0:
            return TrapVerdict(False, "no sweep above swing high", swing_high, atr)
        poke_significant = extension >= buffer       # real stop-run, not noise
        closed_back = cur_close < swing_high          # ended below the level
        # Soft case: closed just above the level after a big poke that was mostly rejected.
        giveback = cur_high - cur_close
        heavy_rejection = giveback >= wick_reject_ratio * extension
        barely_above = cur_close < swing_high + buffer
        is_trap = poke_significant and (closed_back or (heavy_rejection and barely_above))
        if is_trap:
            return TrapVerdict(
                True,
                (f"BULL TRAP: high {cur_high:.5f} swept swing high {swing_high:.5f} "
                 f"(+{extension:.5f} ≥ buffer {buffer:.5f}) then closed {cur_close:.5f} "
                 f"({'below' if closed_back else 'barely above, wick rejected'})"),
                swing_high, atr,
            )
        return TrapVerdict(False, "BUY sweep not a trap (held above level)", swing_high, atr)

    elif direction == "SELL":
        swing_low = float(np.min(l[-(swing_lookback + 1):-1]))
        extension = swing_low - cur_low
        if extension <= 0:
            return TrapVerdict(False, "no sweep below swing low", swing_low, atr)
        poke_significant = extension >= buffer
        closed_back = cur_close > swing_low
        giveback = cur_close - cur_low
        heavy_rejection = giveback >= wick_reject_ratio * extension
        barely_below = cur_close > swing_low - buffer
        is_trap = poke_significant and (closed_back or (heavy_rejection and barely_below))
        if is_trap:
            return TrapVerdict(
                True,
                (f"BEAR TRAP: low {cur_low:.5f} swept swing low {swing_low:.5f} "
                 f"(−{extension:.5f} ≥ buffer {buffer:.5f}) then closed {cur_close:.5f} "
                 f"({'above' if closed_back else 'barely below, wick rejected'})"),
                swing_low, atr,
            )
        return TrapVerdict(False, "SELL sweep not a trap (held below level)", swing_low, atr)

    return TrapVerdict(False, f"unknown direction {direction!r}")
