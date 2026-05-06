"""
TradeClaw — VWAP Analyser
=========================
Teaches the bot to respect where institutions actually traded,
not just where price happened to be.

Core Concepts Implemented:
  • Intraday VWAP   — Running volume-weighted average price from session open
  • VWAP Bands      — Upper/lower standard deviation envelopes (1σ, 2σ, 2.5σ, 3σ)
  • Stretch Signal  — How many SDs away from VWAP is the current price
  • Rejection Test  — Detects a "Shooting Star" / "Hammer" rejection candle at extreme SD
  • Entry Gate      — Only allows long entry when price is 2.5+σ BELOW VWAP with a Hammer

Why VWAP matters for mean reversion:
  Bollinger Bands say "price is statistically stretched from its recent average."
  VWAP says "price is stretched from where institutional volume traded TODAY."
  When BOTH agree, you have a double-confirmed reversal zone — far fewer false entries.

The "rubber-band" mental model:
  Below -2.5σ → stretched. Below -3.0σ → parabolic short / capitulation.
  A hammer candle at -2.5σ is a textbook institutional re-entry signal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("tradeclaw.vwap")


# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────

# Standard deviation multiples for the VWAP bands
VWAP_SD_LEVELS = [1.0, 2.0, 2.5, 3.0]

# Default entry threshold — price must be at least this many SDs below VWAP
DEFAULT_ENTRY_SD = 2.5

# Rejection candle sensitivity — wick must be at least this fraction of candle range
HAMMER_WICK_RATIO = 0.60       # 60% of range must be lower wick for a Hammer
SHOOTING_STAR_WICK_RATIO = 0.60  # 60% of range must be upper wick for Shooting Star

# Minimum candle body size (% of price) to be considered meaningful
MIN_BODY_PCT = 0.05            # 0.05% — filters noise doji candles


# ─────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────

@dataclass
class VWAPState:
    """
    Snapshot of the current VWAP analysis.
    Returned by VWAPAnalyser.analyse() every cycle.
    """
    vwap: float                    # Current intraday VWAP
    sd: float                      # Intraday standard deviation (price-volume weighted)
    sd_stretch: float              # How many SDs current price is from VWAP (signed)
                                   # Negative = below VWAP (oversold), positive = above (overbought)

    upper_1sd: float               # VWAP + 1σ
    upper_2sd: float               # VWAP + 2σ
    upper_25sd: float              # VWAP + 2.5σ
    upper_3sd: float               # VWAP + 3σ
    lower_1sd: float               # VWAP - 1σ
    lower_2sd: float               # VWAP - 2σ
    lower_25sd: float              # VWAP - 2.5σ
    lower_3sd: float               # VWAP - 3σ

    rejection_candle: str          # "HAMMER" | "SHOOTING_STAR" | "NONE"
    signal: str                    # "LONG_ZONE" | "SHORT_ZONE" | "NEUTRAL"
    entry_confirmed: bool          # True only when stretch >= threshold AND rejection candle
    reason: str                    # Human-readable explanation

    bars_used: int                 # How many intraday bars were available

    def to_dict(self) -> dict:
        return {
            "vwap":         round(self.vwap, 4),
            "sd":           round(self.sd, 4),
            "sd_stretch":   round(self.sd_stretch, 3),
            "upper_1sd":    round(self.upper_1sd, 4),
            "upper_2sd":    round(self.upper_2sd, 4),
            "upper_25sd":   round(self.upper_25sd, 4),
            "upper_3sd":    round(self.upper_3sd, 4),
            "lower_1sd":    round(self.lower_1sd, 4),
            "lower_2sd":    round(self.lower_2sd, 4),
            "lower_25sd":   round(self.lower_25sd, 4),
            "lower_3sd":    round(self.lower_3sd, 4),
            "rejection_candle": self.rejection_candle,
            "signal":       self.signal,
            "entry_confirmed": self.entry_confirmed,
            "reason":       self.reason,
            "bars_used":    self.bars_used,
        }


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _compute_vwap(df: pd.DataFrame) -> tuple[float, float]:
    """
    Compute intraday VWAP and its standard deviation from a DataFrame
    with columns: open, high, low, close, volume.

    VWAP formula:
        typical_price = (high + low + close) / 3
        cumulative_pv = Σ(typical_price × volume)
        cumulative_vol = Σ(volume)
        vwap = cumulative_pv / cumulative_vol

    Standard deviation (volume-weighted):
        sd = sqrt( Σ(volume × (tp - vwap)²) / Σ(volume) )

    Returns:
        (vwap, sd)  — both as floats
    """
    required = {"high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"VWAPAnalyser requires columns: {required}. Got: {set(df.columns)}")

    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan).fillna(1.0)   # avoid zero-volume divison

    cum_pv  = (tp * vol).sum()
    cum_vol = vol.sum()
    if cum_vol == 0:
        raise ValueError("Total volume is zero — cannot compute VWAP")

    vwap = cum_pv / cum_vol

    # Volume-weighted variance
    variance = ((vol * (tp - vwap) ** 2).sum()) / cum_vol
    sd = float(np.sqrt(variance))

    return float(vwap), sd


def _detect_rejection_candle(row: pd.Series) -> str:
    """
    Classify the latest candle as a rejection candle type.

    Hammer (Bullish):
        • Long lower wick ≥ 60% of total range
        • Small body in upper 40% of range
        → Price poked down aggressively but buyers pushed it back up

    Shooting Star (Bearish):
        • Long upper wick ≥ 60% of total range
        • Small body in lower 40% of range
        → Price poked up aggressively but sellers crushed it back down

    Returns: "HAMMER" | "SHOOTING_STAR" | "NONE"
    """
    high  = float(row["high"])
    low   = float(row["low"])
    open_ = float(row["open"])
    close = float(row["close"])

    total_range = high - low
    if total_range < 1e-8:
        return "NONE"

    body_top    = max(open_, close)
    body_bottom = min(open_, close)
    body_size   = body_top - body_bottom

    # Reject doji-like candles (body too small to be meaningful)
    if close > 0 and (body_size / close) < (MIN_BODY_PCT / 100):
        lower_wick = body_bottom - low
        upper_wick = high - body_top
        # Even a doji with huge wick can be a valid signal if wick is extreme
        if lower_wick / total_range < HAMMER_WICK_RATIO and upper_wick / total_range < SHOOTING_STAR_WICK_RATIO:
            return "NONE"

    lower_wick = body_bottom - low
    upper_wick = high - body_top

    if lower_wick / total_range >= HAMMER_WICK_RATIO:
        return "HAMMER"
    if upper_wick / total_range >= SHOOTING_STAR_WICK_RATIO:
        return "SHOOTING_STAR"

    return "NONE"


# ─────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────

class VWAPAnalyser:
    """
    Intraday VWAP mean-reversion analyser.

    Usage:
        analyser = VWAPAnalyser(entry_sd_threshold=2.5)
        state = analyser.analyse(df)

        if state.entry_confirmed:
            # Price is at least 2.5 SDs below VWAP AND a Hammer printed
            # → High-conviction long entry zone
            execute_buy()

    Design Philosophy:
        This module does NOT replace the Bollinger Band signal — it CONFIRMS it.
        An entry requires BOTH:
          1. price <= lower Bollinger Band  (stretched from recent average)
          2. state.entry_confirmed == True  (stretched from today's institutional anchor)
        This dual-confirmation dramatically reduces false entries in choppy markets.
    """

    def __init__(self, entry_sd_threshold: float = DEFAULT_ENTRY_SD):
        """
        Args:
            entry_sd_threshold: Minimum SD stretch below VWAP to flag a LONG_ZONE.
                                 Default 2.5 (institutional standard; 3.0 for stricter).
        """
        self.entry_sd_threshold = entry_sd_threshold
        self._last_state: Optional[VWAPState] = None

    @property
    def last_state(self) -> Optional[VWAPState]:
        return self._last_state

    def analyse(
        self,
        df: pd.DataFrame,
        entry_sd_override: Optional[float] = None,
    ) -> VWAPState:
        """
        Run the full VWAP analysis on a DataFrame of OHLCV bars.

        Args:
            df: DataFrame with columns [open, high, low, close, volume].
                Expected to contain INTRADAY bars only (one session).
                If multi-day bars are passed, VWAP will span multiple sessions,
                which is less precise but still functional.
            entry_sd_override: Override the entry SD threshold for this call
                               (used by AI Brain parameter tuning).

        Returns:
            VWAPState with all band levels, stretch reading, and entry gate.
        """
        threshold = entry_sd_override if entry_sd_override is not None else self.entry_sd_threshold

        # ── Guard: insufficient data ─────────────────────────────────────────
        min_bars = 5
        if df.empty or len(df) < min_bars:
            state = VWAPState(
                vwap=0.0, sd=0.0, sd_stretch=0.0,
                upper_1sd=0.0, upper_2sd=0.0, upper_25sd=0.0, upper_3sd=0.0,
                lower_1sd=0.0, lower_2sd=0.0, lower_25sd=0.0, lower_3sd=0.0,
                rejection_candle="NONE",
                signal="NEUTRAL",
                entry_confirmed=False,
                reason=f"Insufficient data — need {min_bars} bars, got {len(df)}",
                bars_used=len(df),
            )
            self._last_state = state
            return state

        # ── Guard: volume column ─────────────────────────────────────────────
        if "volume" not in df.columns or df["volume"].sum() == 0:
            logger.warning("[VWAP] No volume data — falling back to equal-weight VWAP (price average)")
            df = df.copy()
            df["volume"] = 1.0   # treat each bar equally if volume not available

        try:
            vwap, sd = _compute_vwap(df)
        except Exception as e:
            logger.error(f"[VWAP] Computation error: {e}")
            state = VWAPState(
                vwap=0.0, sd=0.0, sd_stretch=0.0,
                upper_1sd=0.0, upper_2sd=0.0, upper_25sd=0.0, upper_3sd=0.0,
                lower_1sd=0.0, lower_2sd=0.0, lower_25sd=0.0, lower_3sd=0.0,
                rejection_candle="NONE",
                signal="NEUTRAL",
                entry_confirmed=False,
                reason=f"VWAP computation failed: {e}",
                bars_used=len(df),
            )
            self._last_state = state
            return state

        # ── Build SD band levels ─────────────────────────────────────────────
        upper_1sd  = vwap + 1.0 * sd
        upper_2sd  = vwap + 2.0 * sd
        upper_25sd = vwap + 2.5 * sd
        upper_3sd  = vwap + 3.0 * sd
        lower_1sd  = vwap - 1.0 * sd
        lower_2sd  = vwap - 2.0 * sd
        lower_25sd = vwap - 2.5 * sd
        lower_3sd  = vwap - 3.0 * sd

        # ── Current price and stretch ────────────────────────────────────────
        latest = df.iloc[-1]
        price  = float(latest["close"])

        sd_stretch = (price - vwap) / sd if sd > 0 else 0.0

        # ── Rejection candle classification ───────────────────────────────────
        rejection_candle = _detect_rejection_candle(latest)

        # ── Signal classification ─────────────────────────────────────────────
        if sd_stretch <= -threshold:
            signal = "LONG_ZONE"
            zone_label = f"{abs(sd_stretch):.2f}σ below VWAP"
        elif sd_stretch >= threshold:
            signal = "SHORT_ZONE"
            zone_label = f"{sd_stretch:.2f}σ above VWAP"
        else:
            signal = "NEUTRAL"
            zone_label = f"{abs(sd_stretch):.2f}σ from VWAP"

        # ── Entry confirmation ───────────────────────────────────────────────
        # Long entry: at or beyond the threshold below VWAP + Hammer rejection
        entry_confirmed = (
            signal == "LONG_ZONE"
            and rejection_candle == "HAMMER"
        )

        # ── Build reason string ───────────────────────────────────────────────
        if entry_confirmed:
            reason = (
                f"VWAP ENTRY CONFIRMED: Price {zone_label} — Hammer rejection candle at "
                f"VWAP={vwap:.4f} | SD={sd:.4f}. Institutions defending fair value. "
                f"High-conviction long zone."
            )
            logger.info(f"[VWAP] ✅ {reason}")
        elif signal == "LONG_ZONE":
            reason = (
                f"VWAP LONG ZONE: Price {zone_label} (threshold={threshold:.1f}σ) "
                f"but no Hammer candle. Awaiting rejection confirmation. "
                f"Candle type: {rejection_candle}."
            )
            logger.info(f"[VWAP] ⚠️ {reason}")
        elif signal == "SHORT_ZONE":
            reason = (
                f"VWAP SHORT ZONE: Price {zone_label} — above {threshold:.1f}σ. "
                f"Overbought relative to institutional value. "
                f"Candle type: {rejection_candle}."
            )
            logger.debug(f"[VWAP] {reason}")
        else:
            reason = (
                f"VWAP NEUTRAL: Price {zone_label}. "
                f"No extreme stretch from institutional fair value. "
                f"VWAP={vwap:.4f}."
            )
            logger.debug(f"[VWAP] {reason}")

        state = VWAPState(
            vwap=vwap,
            sd=sd,
            sd_stretch=sd_stretch,
            upper_1sd=upper_1sd,
            upper_2sd=upper_2sd,
            upper_25sd=upper_25sd,
            upper_3sd=upper_3sd,
            lower_1sd=lower_1sd,
            lower_2sd=lower_2sd,
            lower_25sd=lower_25sd,
            lower_3sd=lower_3sd,
            rejection_candle=rejection_candle,
            signal=signal,
            entry_confirmed=entry_confirmed,
            reason=reason,
            bars_used=len(df),
        )
        self._last_state = state
        return state

    def is_approaching_vwap(self, price: float) -> bool:
        """
        Return True if an open position's price is approaching VWAP
        (useful as a partial take-profit target — "mean reversion to fair value").
        """
        if self._last_state is None or self._last_state.vwap == 0:
            return False
        vwap = self._last_state.vwap
        sd   = self._last_state.sd
        # "Approaching" = within 0.5σ of VWAP
        return abs(price - vwap) <= 0.5 * sd
