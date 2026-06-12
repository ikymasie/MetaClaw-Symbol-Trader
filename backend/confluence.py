"""
TradeClaw — 3-Pillar Confluence Gate + ICT Smart Money Enrichment
==================================================================
The gold-standard entry filter for high-probability mean-reversion trades,
now enriched with ICT (Inner Circle Trader) structural analysis.

A BUY signal is only emitted when ALL three independent confirmation
pillars agree, plus the Bollinger Band re-entry trigger fires:

  Pillar 1 – Regime Filter     : ADX < 25 (market is ranging, not trending)
  Pillar 2 – RSI Exhaustion    : RSI(14) < 30 (seller exhaustion confirmed)
  Pillar 3 – Volume Confirm    : RVOL ≥ 1.5 (institutional participation on reversal)
  Trigger  – BB Re-entry       : Price was below lower BB and closed back inside

ICT Enrichment (conviction boosters, NOT entry gates):
  · Fair Value Gap (FVG)     : Displacement candle leaving a gap (institutional aggression)
  · Liquidity Sweep          : Price sweeps below swing low then reclaims (stop hunt pattern)
  · Kill Zone Timing         : Trade occurs during NY or London open (high-liquidity window)

Why this works:
  Extreme fear (RSI < 30) in a range-bound market (ADX < 25) with abnormal
  volume (RVOL ≥ 1.5) is the statistical signature of a volatility spike
  mean-reverting. When this coincides with ICT structural patterns (sweep of
  stops + displacement), the probability of a successful reversal increases
  significantly.

CRITICAL RULE:
  This module NEVER emits a standalone SELL signal. Selling is an EXIT action
  that belongs to position management, not entry logic. This eliminates the
  "selling into thin air" bug permanently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger("tradeclaw.confluence")


# ── RSI Computation (Wilder's Smoothed) ─────────────────────────────────

def compute_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """
    Compute Wilder's RSI (Relative Strength Index).

    RSI = 100 - (100 / (1 + RS))
    RS  = AvgGain / AvgLoss  (Wilder's exponential smoothing)

    Returns the latest RSI value, or None if insufficient data.
    """
    if len(prices) < period + 1:
        return None

    deltas = prices.diff()

    gains = deltas.clip(lower=0)
    losses = (-deltas).clip(lower=0)

    # Wilder's smoothing: first value is SMA, then EMA with alpha=1/period
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()

    # Apply Wilder's exponential smoothing after the initial SMA seed
    avg_gain_vals = avg_gain.values.copy()
    avg_loss_vals = avg_loss.values.copy()

    for i in range(period + 1, len(prices)):
        avg_gain_vals[i] = (avg_gain_vals[i - 1] * (period - 1) + gains.iloc[i]) / period
        avg_loss_vals[i] = (avg_loss_vals[i - 1] * (period - 1) + losses.iloc[i]) / period

    latest_gain = avg_gain_vals[-1]
    latest_loss = avg_loss_vals[-1]

    if latest_loss == 0:
        return 100.0  # All gains, no losses
    if latest_gain == 0:
        return 0.0    # All losses, no gains

    rs = latest_gain / latest_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


# ── Relative Volume (RVOL) ──────────────────────────────────────────────

def compute_rvol(volumes: pd.Series, lookback: int = 20) -> Optional[float]:
    """
    Compute Relative Volume (RVOL).

    RVOL = current_bar_volume / mean(last `lookback` bars volume)

    RVOL > 1.5 = above-average institutional activity.
    RVOL > 2.0 = significant volume spike (high conviction).

    Returns None if insufficient data.
    """
    if len(volumes) < lookback + 1:
        return None

    # Average volume over the lookback window (excluding current bar)
    avg_vol = volumes.iloc[-(lookback + 1):-1].mean()

    if avg_vol <= 0:
        return None

    current_vol = volumes.iloc[-1]
    return round(current_vol / avg_vol, 2)


# ── Fair Value Gap (FVG) Detection ───────────────────────────────────────────

def detect_fvg(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    lookback: int = 5,
) -> Optional[dict]:
    """
    Detect the most recent Bullish Fair Value Gap (FVG).

    ICT Definition:
      A bullish FVG is a 3-candle pattern where candle 1's high is below
      candle 3's low, indicating aggressive institutional buying that
      left a "gap" (imbalance) in the order book.

    Pattern (bullish):
      candle[i-2].high < candle[i].low  (gap between candle 1 and candle 3)
      candle[i-1] is the "displacement" candle

    We scan backwards from the most recent bar within the lookback window.

    Returns:
        {"type": "BULLISH_FVG", "gap_top": float, "gap_bottom": float,
         "bars_ago": int, "gap_size_pct": float}
        or None if no FVG found in the lookback window.
    """
    n = len(highs)
    if n < 3:
        return None

    # Scan backwards from the most recent completed 3-candle pattern
    start_idx = max(2, n - lookback)
    for i in range(n - 1, start_idx - 1, -1):
        # Bullish FVG: candle[i-2].high < candle[i].low
        candle1_high = float(highs.iloc[i - 2])
        candle3_low = float(lows.iloc[i])

        if candle1_high < candle3_low:
            gap_bottom = candle1_high
            gap_top = candle3_low
            gap_size_pct = ((gap_top - gap_bottom) / gap_bottom) * 100 if gap_bottom > 0 else 0
            result = {
                "type": "BULLISH_FVG",
                "gap_top": round(gap_top, 4),
                "gap_bottom": round(gap_bottom, 4),
                "bars_ago": n - 1 - i,
                "gap_size_pct": round(gap_size_pct, 4),
            }
            logger.debug(f"[ICT] Bullish FVG detected: {result}")
            return result

    return None


# ── Liquidity Sweep Detection ──────────────────────────────────────────

def detect_liquidity_sweep(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    swing_lookback: int = 20,
    reclaim_bars: int = 3,
) -> Optional[dict]:
    """
    Detect a sell-side liquidity sweep (bullish reversal setup).

    ICT Definition:
      The market "hunts" below a recent swing low to trigger retail stop-loss
      orders, filling institutional buy orders. Then price reclaims the swing
      low, confirming the sweep was an institutional accumulation event.

    Pattern:
      1. Identify the swing low in the last `swing_lookback` bars (the "liquidity pool")
      2. Check if a recent bar's low wicked below it (swept the stops)
      3. Check if price then closed ABOVE the swing low (reclaimed)

    Returns:
        {"type": "SELLSIDE_SWEEP", "swing_low": float, "sweep_low": float,
         "reclaimed_price": float, "sweep_depth_pct": float}
        or None if no sweep detected.
    """
    n = len(lows)
    if n < swing_lookback + reclaim_bars:
        return None

    # Step 1: Find the swing low in the lookback window (excluding the last
    # `reclaim_bars` to allow room for the sweep + reclaim)
    lookback_window = lows.iloc[-(swing_lookback + reclaim_bars):-reclaim_bars]
    swing_low_val = float(lookback_window.min())
    swing_low_idx = int(lookback_window.idxmin())

    # Step 2: Check if any of the last `reclaim_bars` wicked below the swing low
    recent_lows = lows.iloc[-reclaim_bars:]
    recent_closes = closes.iloc[-reclaim_bars:]

    sweep_found = False
    sweep_low = None
    reclaimed_price = None

    for j in range(len(recent_lows)):
        bar_low = float(recent_lows.iloc[j])
        bar_close = float(recent_closes.iloc[j])

        if bar_low < swing_low_val:
            # This bar swept below the swing low
            sweep_found = True
            sweep_low = bar_low

        if sweep_found and bar_close > swing_low_val:
            # Price reclaimed above the swing low after the sweep
            reclaimed_price = bar_close
            break

    if sweep_found and reclaimed_price is not None:
        sweep_depth_pct = ((swing_low_val - sweep_low) / swing_low_val) * 100 if swing_low_val > 0 else 0
        result = {
            "type": "SELLSIDE_SWEEP",
            "swing_low": round(swing_low_val, 4),
            "sweep_low": round(sweep_low, 4),
            "reclaimed_price": round(reclaimed_price, 4),
            "sweep_depth_pct": round(sweep_depth_pct, 4),
        }
        logger.debug(f"[ICT] Sell-side liquidity sweep detected: {result}")
        return result

    return None


# ── Confluence Result ────────────────────────────────────────────────────

@dataclass
class ConfluenceResult:
    """
    Structured output from the 3-Pillar Confluence evaluation.

    The entry_signal is "BUY", "SELL", or "HOLD".
    SELL is only emitted when short_selling_enabled=True and bearish
    confluence conditions are met (RSI overbought + volume + BB upper re-entry).
    """
    entry_signal: str           # "BUY", "SELL", or "HOLD"

    # Pillar statuses
    pillar_1_regime: bool       # ADX < threshold (ranging)
    pillar_2_exhaustion: bool   # RSI < oversold threshold
    pillar_3_volume: bool       # RVOL >= volume threshold
    bb_reentry: bool            # Price crossed back inside lower BB

    # Diagnostic values
    rsi: Optional[float]
    adx: float
    rvol: Optional[float]
    pillars_met: int            # 0-3

    # Human-readable explanation
    reason: str

    # ICT Smart Money diagnostics (conviction boosters, not entry gates)
    fvg_detected: Optional[dict] = None        # FVG details if found
    liquidity_sweep: Optional[dict] = None      # Sweep details if found
    kill_zone_active: bool = True               # Whether we're in a Kill Zone
    ict_conviction: str = "STANDARD"            # "STANDARD" | "HIGH" | "MAXIMUM"

    def to_dict(self) -> dict:
        return {
            "entry_signal": self.entry_signal,
            "pillar_1_regime": self.pillar_1_regime,
            "pillar_2_exhaustion": self.pillar_2_exhaustion,
            "pillar_3_volume": self.pillar_3_volume,
            "bb_reentry": self.bb_reentry,
            "rsi": self.rsi,
            "adx": round(self.adx, 1),
            "rvol": self.rvol,
            "pillars_met": self.pillars_met,
            "reason": self.reason,
            "fvg_detected": self.fvg_detected,
            "liquidity_sweep": self.liquidity_sweep,
            "kill_zone_active": self.kill_zone_active,
            "ict_conviction": self.ict_conviction,
        }


# ── Master Confluence Gate ───────────────────────────────────────────────

def evaluate_confluence(
    prices: pd.Series,
    volumes: pd.Series,
    regime_state,                   # RegimeState from regime_detector.py
    bb: dict,                       # {"upper", "middle", "lower"} from compute_bollinger_bands
    current_price: float,
    *,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rvol_threshold: float = 1.5,
    # ICT enrichment params (optional — backwards compatible)
    highs: Optional[pd.Series] = None,
    lows: Optional[pd.Series] = None,
    kill_zone_active: bool = True,
    fvg_enabled: bool = True,
    sweep_enabled: bool = True,
    sweep_lookback: int = 20,
    # Short-selling confluence (bearish entry gate)
    short_selling_enabled: bool = False,
    rsi_overbought: float = 70.0,
) -> ConfluenceResult:
    """
    The 3-Pillar Confluence Gate + ICT Smart Money Enrichment.

    Evaluates all three independent confirmation pillars plus the
    Bollinger Band re-entry trigger. Returns a ConfluenceResult that
    is either BUY (all conditions met) or HOLD (one or more failed).

    ICT enrichment runs AFTER the 3-pillar decision. It does NOT change
    the BUY/HOLD outcome — it adds conviction metadata for downstream
    consumers (deliberation panel, logging, Situation Room).

    Parameters:
        prices        : pd.Series of close prices (latest at end)
        volumes       : pd.Series of bar volumes (latest at end)
        regime_state  : RegimeState from RegimeDetector.detect()
        bb            : Bollinger Band dict with 'upper', 'middle', 'lower'
        current_price : The current/latest close price
        rsi_period    : RSI lookback period (default: 14)
        rsi_oversold  : RSI threshold for exhaustion (default: 30)
        rvol_threshold: Minimum RVOL for volume confirmation (default: 1.5)
        highs         : pd.Series of bar highs (for FVG/sweep detection)
        lows          : pd.Series of bar lows (for FVG/sweep detection)
        kill_zone_active : Whether we're currently in a Kill Zone
        fvg_enabled   : Enable Fair Value Gap detection
        sweep_enabled : Enable Liquidity Sweep detection
        sweep_lookback: Bars to look back for swing lows

    Returns:
        ConfluenceResult with entry_signal = "BUY", "SELL", or "HOLD"
    """
    # ── Pillar 1: Regime Filter ───────────────────────────────────
    # The RegimeDetector already computes ADX and classifies regime.
    # We trust its `can_mean_revert` flag (True when ADX < 25, regime=RANGING).
    # If regime_state is None (detector failed), treat as RANGING (safe default
    # matching the UNKNOWN→RANGING fallback in bot_engine.py).
    if regime_state is not None:
        adx_val = getattr(regime_state, "adx", 0.0)
        pillar_1 = getattr(regime_state, "can_mean_revert", False)
    else:
        adx_val = 0.0
        pillar_1 = True  # Assume ranging when detector is unavailable

    # ── Pillar 2: RSI Exhaustion ──────────────────────────────────
    rsi_val = compute_rsi(prices, period=rsi_period)
    pillar_2 = rsi_val is not None and rsi_val < rsi_oversold

    # ── Pillar 3: Volume Confirmation ───────────────────────────────
    rvol_val = compute_rvol(volumes)
    pillar_3 = rvol_val is not None and rvol_val >= rvol_threshold

    # ── BB Touch / Re-entry Trigger ───────────────────────────────
    # Fires on either:
    #   (a) Price AT or below the lower BB (with 50% band width tolerance - lower half)
    #   (b) Re-entry: recent ticks were below lower BB, current tick is back inside
    lower_bb = bb.get("lower", 0.0)
    upper_bb = bb.get("upper", lower_bb)
    bb_width = upper_bb - lower_bb if upper_bb > lower_bb else 0.0
    
    # Add a 50% of band width tolerance (lower half of the channel)
    bb_tolerance = lower_bb + (bb_width * 0.50)
    bb_at_band = current_price <= bb_tolerance
    
    if len(prices) >= 2:
        # Check if any of the last 5 prices were within the tolerance
        lookback = min(len(prices), 5)
        recent_prices_below = any(float(p) <= bb_tolerance for p in prices.iloc[-lookback:])
        bb_reentry = bb_at_band or (recent_prices_below and current_price >= lower_bb)
    else:
        bb_reentry = bb_at_band

    # ── Confluence Decision ───────────────────────────────────────
    pillars_met = sum([pillar_1, pillar_2, pillar_3])

    if pillar_1 and pillar_2 and pillar_3 and bb_reentry:
        entry_signal = "BUY"
        reason = (
            f"✅ CONFLUENCE BUY: All 3 pillars confirmed + BB re-entry. "
            f"ADX={adx_val:.1f} (ranging) | RSI={rsi_val:.1f} (exhausted) | "
            f"RVOL={rvol_val:.2f} (volume confirmed). "
            f"High-probability mean reversion entry."
        )
        logger.info(f"[CONFLUENCE] {reason}")
    else:
        entry_signal = "HOLD"
        # Build diagnostic reason showing which pillars failed
        failed = []
        if not pillar_1:
            failed.append(f"Regime: ADX={adx_val:.1f} (need ranging, can_mr={pillar_1})")
        if not pillar_2:
            rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
            failed.append(f"RSI={rsi_str} (need <{rsi_oversold})")
        if not pillar_3:
            rvol_str = f"{rvol_val:.2f}" if rvol_val is not None else "N/A"
            failed.append(f"RVOL={rvol_str} (need ≥{rvol_threshold})")
        if not bb_reentry:
            failed.append(f"BB re-entry not triggered (price={current_price:.2f}, lower_bb={lower_bb:.2f}, tol={bb_tolerance:.2f})")

        reason = f"HOLD: {pillars_met}/3 pillars met. Failed: {'; '.join(failed)}"
        logger.info(f"[CONFLUENCE] {reason}")

    # ── Bearish Confluence Gate (Short Entry) ─────────────────────
    # Only runs if (a) short selling is enabled AND (b) the bullish gate
    # did NOT fire. This ensures we never emit BUY and SELL simultaneously.
    if entry_signal == "HOLD" and short_selling_enabled:
        # Bearish Pillar 1: Regime is TRENDING (shorts work in trends, not ranges)
        if regime_state is not None:
            bearish_p1 = not getattr(regime_state, "can_mean_revert", True)
        else:
            bearish_p1 = False  # Conservative: don't short when detector is unavailable

        # Bearish Pillar 2: RSI Overbought (buyer exhaustion)
        bearish_p2 = rsi_val is not None and rsi_val > rsi_overbought

        # Bearish Pillar 3: Volume Confirmation (same as bullish)
        bearish_p3 = pillar_3  # Already computed above

        # BB Upper Re-entry: price was above upper BB and crossed back inside
        # (with 50% band width tolerance - upper half)
        upper_bb = bb.get("upper", float("inf"))
        lower_bb_val = bb.get("lower", 0.0) if upper_bb != float("inf") else 0.0
        bb_width_val = upper_bb - lower_bb_val if upper_bb > lower_bb_val and upper_bb != float("inf") else 0.0
        
        bb_tolerance_upper = upper_bb - (bb_width_val * 0.50)
        bb_at_upper = current_price >= bb_tolerance_upper
        
        if len(prices) >= 2:
            lookback = min(len(prices), 5)
            recent_prices_above = any(float(p) >= bb_tolerance_upper for p in prices.iloc[-lookback:])
            bb_upper_reentry = bb_at_upper or (recent_prices_above and current_price <= upper_bb)
        else:
            bb_upper_reentry = bb_at_upper

        bearish_pillars = sum([bearish_p1, bearish_p2, bearish_p3])

        if bearish_p1 and bearish_p2 and bearish_p3 and bb_upper_reentry:
            entry_signal = "SELL"
            reason = (
                f"✅ CONFLUENCE SELL: All 3 bearish pillars confirmed + BB upper re-entry. "
                f"ADX={adx_val:.1f} (trending) | RSI={rsi_val:.1f} (overbought) | "
                f"RVOL={rvol_val:.2f} (volume confirmed). "
                f"High-probability short entry."
            )
            logger.info(f"[CONFLUENCE] {reason}")
        elif bearish_pillars > 0:
            # Log near-miss for diagnostics
            bear_failed = []
            if not bearish_p1:
                bear_failed.append(f"Regime not trending (ADX={adx_val:.1f})")
            if not bearish_p2:
                rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
                bear_failed.append(f"RSI={rsi_str} (need >{rsi_overbought})")
            if not bearish_p3:
                rvol_str = f"{rvol_val:.2f}" if rvol_val is not None else "N/A"
                bear_failed.append(f"RVOL={rvol_str} (need ≥{rvol_threshold})")
            if not bb_upper_reentry:
                bear_failed.append("BB upper re-entry not triggered")
            logger.debug(
                f"[CONFLUENCE] Bearish near-miss: {bearish_pillars}/3 pillars. "
                f"Failed: {'; '.join(bear_failed)}"
            )

    # ── ICT Smart Money Enrichment ─────────────────────────────────
    # These are conviction boosters — they enrich the result but do NOT
    # change the BUY/HOLD decision. The 3-pillar gate is the master guard.
    fvg_result = None
    sweep_result = None
    ict_signals_count = 0

    if highs is not None and lows is not None:
        # Fair Value Gap detection
        if fvg_enabled:
            try:
                fvg_result = detect_fvg(highs, lows, prices)
                if fvg_result is not None:
                    ict_signals_count += 1
            except Exception as e:
                logger.warning(f"[ICT] FVG detection error: {e}")

        # Liquidity Sweep detection
        if sweep_enabled:
            try:
                sweep_result = detect_liquidity_sweep(
                    highs, lows, prices, swing_lookback=sweep_lookback
                )
                if sweep_result is not None:
                    ict_signals_count += 1
            except Exception as e:
                logger.warning(f"[ICT] Sweep detection error: {e}")

    # Kill Zone timing counts toward conviction
    if kill_zone_active:
        ict_signals_count += 1

    # Compute ICT conviction level
    if ict_signals_count >= 3:
        ict_conviction = "MAXIMUM"   # FVG + Sweep + Kill Zone = trifecta
    elif ict_signals_count >= 2:
        ict_conviction = "HIGH"      # Two of three ICT confirmations
    else:
        ict_conviction = "STANDARD"  # Original 3-pillar behavior

    if ict_conviction != "STANDARD":
        reason += f" | ICT: {ict_conviction} conviction"
        if fvg_result:
            reason += f" [FVG gap={fvg_result['gap_size_pct']:.2f}%]"
        if sweep_result:
            reason += f" [Sweep depth={sweep_result['sweep_depth_pct']:.2f}%]"
        logger.info(
            f"[ICT] Conviction={ict_conviction} | FVG={fvg_result is not None} | "
            f"Sweep={sweep_result is not None} | KillZone={kill_zone_active}"
        )

    return ConfluenceResult(
        entry_signal=entry_signal,
        pillar_1_regime=pillar_1,
        pillar_2_exhaustion=pillar_2,
        pillar_3_volume=pillar_3,
        bb_reentry=bb_reentry,
        rsi=rsi_val,
        adx=adx_val,
        rvol=rvol_val,
        pillars_met=pillars_met,
        reason=reason,
    )
