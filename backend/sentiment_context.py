"""
TradeClaw — Sentiment Context Builder
=======================================
Gives the AI Brain a "view of the battlefield" before every evolution cycle.

Inspired by the ML/Sentiment Algo camp — but without needing satellite imagery
or social media APIs. The bot derives its own "market mood" from price behaviour.

Macro Context Components:
  1. VIX Proxy       — 20-bar rolling return volatility as a fear gauge
  2. Market Session  — pre-market | regular | after-hours | closed
  3. Regime Context  — RANGING | TRENDING | VOLATILE from RegimeDetector
  4. Momentum Bias   — BULLISH | BEARISH | NEUTRAL from MomentumFilter
  5. Volatility Trend— Is volatility expanding or contracting? (vol-of-vol)
  6. Win Pattern     — Is the strategy performing differently in certain conditions?

These are injected into every AI Brain prompt as a "Field Intelligence Report",
giving the LLM the context it needs to make smarter, situation-aware parameter
decisions rather than reacting to PnL data alone.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from regime_detector import RegimeState
    from momentum_filter import MomentumState

logger = logging.getLogger("tradeclaw.sentiment")

# Market session definitions (US Eastern Time offset used here via UTC)
# These are approximate — for paper/live trading context only
REGULAR_HOURS_OPEN_UTC  = 14   # 9:30 AM ET = 14:30 UTC (approx)
REGULAR_HOURS_CLOSE_UTC = 21   # 4:00 PM ET = 21:00 UTC (approx)

# VIX proxy thresholds (annualized rolling 20-bar vol %)
VIX_PROXY_LOW       = 10.0   # Complacency — low fear
VIX_PROXY_MODERATE  = 20.0   # Normal market conditions
VIX_PROXY_HIGH      = 30.0   # Elevated fear — be cautious
VIX_PROXY_EXTREME   = 45.0   # Crisis volatility — heightened risk


def _compute_vix_proxy(df: pd.DataFrame, window: int = 20) -> float:
    """
    Estimate market fear/volatility as a VIX proxy.
    Uses annualized rolling standard deviation of log returns.

    Returns the VIX-like value (annualized %, ~same scale as the real VIX).
    """
    if len(df) < window + 1:
        return 0.0
    try:
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        rolling_std = float(log_returns.rolling(window).std().iloc[-1])
        # Annualize: sqrt(252 days * 390 minutes per day) for minute bars
        # For simplicity, we use sqrt(252) as a weekly proxy
        vix_proxy = rolling_std * (252 ** 0.5) * 100
        return round(vix_proxy, 2)
    except Exception:
        return 0.0


def _get_vol_trend(df: pd.DataFrame, short_window: int = 10, long_window: int = 30) -> str:
    """
    Is volatility expanding or contracting?
    Compares short-window std vs long-window std of returns.
    """
    if len(df) < long_window + 1:
        return "unknown"
    try:
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        vol_short = float(log_returns.rolling(short_window).std().iloc[-1])
        vol_long  = float(log_returns.rolling(long_window).std().iloc[-1])

        if vol_long == 0:
            return "unknown"

        ratio = vol_short / vol_long
        if ratio > 1.2:
            return "EXPANDING"   # Volatility is picking up — increased risk
        elif ratio < 0.8:
            return "CONTRACTING" # Volatility is falling — calmer markets ahead
        else:
            return "STABLE"
    except Exception:
        return "unknown"


def _get_market_session() -> str:
    """
    Return the current US market session based on UTC time.
    This is approximate — intended for parameter tuning context only.
    """
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    weekday = now_utc.weekday()  # 0=Monday, 6=Sunday

    # Weekend
    if weekday >= 5:
        return "CLOSED_WEEKEND"

    # Opening auction: 9:28-9:31 ET = 14:28-14:31 UTC (approx)
    if hour == 14 and 28 <= minute <= 31:
        return "OPENING_AUCTION"

    # Pre-market: 4:00-9:30 AM ET = 9:00-14:30 UTC
    if 9 <= hour < REGULAR_HOURS_OPEN_UTC:
        return "PRE_MARKET"
    if hour == REGULAR_HOURS_OPEN_UTC and minute < 30:
        return "PRE_MARKET"

    # Regular hours: 9:30 AM - 4:00 PM ET = 14:30-21:00 UTC
    if (hour == REGULAR_HOURS_OPEN_UTC and minute >= 30) or \
       (REGULAR_HOURS_OPEN_UTC < hour < REGULAR_HOURS_CLOSE_UTC):
        return "REGULAR_HOURS"

    # After-hours
    if REGULAR_HOURS_CLOSE_UTC <= hour < 24:
        return "AFTER_HOURS"

    return "CLOSED"


def _classify_vix(vix_proxy: float) -> tuple[str, str]:
    """Return (label, description) for the current VIX proxy level."""
    if vix_proxy >= VIX_PROXY_EXTREME:
        return "EXTREME_FEAR", "Crisis-level volatility. Risk-off. Capital preservation paramount."
    elif vix_proxy >= VIX_PROXY_HIGH:
        return "HIGH_FEAR", "Elevated fear. Spreads wide. Reduce position sizing."
    elif vix_proxy >= VIX_PROXY_MODERATE:
        return "MODERATE", "Normal market conditions. Standard parameters acceptable."
    elif vix_proxy > VIX_PROXY_LOW:
        return "LOW_FEAR", "Complacency mode. Tight spreads. Good mean-reversion environment."
    else:
        return "VERY_LOW", "Extremely compressed volatility. Watch for regime expansion."


class SentimentContextBuilder:
    """
    The Organism's Field Intelligence Report Generator.

    Before every AI Brain evolution cycle, this class compiles the
    full environmental context — volatility, session, regime, momentum —
    into a structured markdown block that is injected into the AI prompt.

    The LLM can then reason about WHY performance was what it was,
    not just WHAT the numbers were.
    """

    def build(
        self,
        df: Optional[pd.DataFrame] = None,
        regime_state: Optional["RegimeState"] = None,
        momentum_state: Optional["MomentumState"] = None,
        recent_trades: Optional[list[dict]] = None,
    ) -> str:
        """
        Build the full Field Intelligence Report as a prompt-ready string.

        Args:
            df: OHLC price DataFrame (used for VIX proxy + vol trend)
            regime_state: Latest RegimeDetector output
            momentum_state: Latest MomentumFilter output
            recent_trades: Last N closed trades for win-pattern analysis
        """
        blocks = []

        # ── 1. Market Session ──────────────────────────────────────
        session = _get_market_session()
        session_note = {
            "OPENING_AUCTION": "⚠️ Opening auction — high spread risk, reduced fill quality.",
            "PRE_MARKET":      "📊 Pre-market hours — thin liquidity, volatility often elevated.",
            "REGULAR_HOURS":   "✅ Regular trading hours — optimal conditions.",
            "AFTER_HOURS":     "🌙 After-hours — illiquid, wide spreads, avoid new entries.",
            "CLOSED_WEEKEND":  "🔒 Weekend — market closed, no live executions.",
            "CLOSED":          "🔒 Market closed.",
        }.get(session, session)

        blocks.append(f"""FIELD INTELLIGENCE REPORT
═══════════════════════════════════════════════════
1. MARKET SESSION: {session}
   {session_note}""")

        # ── 2. VIX Proxy ───────────────────────────────────────────
        if df is not None and not df.empty:
            vix_proxy = _compute_vix_proxy(df)
            vol_trend = _get_vol_trend(df)
            vix_label, vix_desc = _classify_vix(vix_proxy)

            blocks.append(f"""
2. VOLATILITY (VIX Proxy): {vix_proxy:.1f}% [{vix_label}]
   {vix_desc}
   Volatility Trend: {vol_trend} (short vs. long window)""")
        else:
            blocks.append("\n2. VOLATILITY: No price data available for VIX proxy.")

        # ── 3. Market Regime ───────────────────────────────────────
        if regime_state is not None:
            regime_advice = {
                "RANGING":  "✅ Prime mean-reversion conditions. BB + Fib signals have higher reliability.",
                "TRENDING": "⚠️ Trend active. Mean-reversion signals are lower reliability. Widen bands or reduce qty.",
                "VOLATILE": "🚨 Volatility spike. Slippage risk elevated. Reduce qty and entry frequency.",
                "UNKNOWN":  "❓ Regime unknown. Treat as VOLATILE — apply conservative sizing.",
            }.get(regime_state.regime, "")

            blocks.append(f"""
3. MARKET REGIME: {regime_state.regime} (ADX={regime_state.adx:.1f}, ATR_z={regime_state.atr_zscore:.2f})
   {regime_advice}
   Trend Direction: {regime_state.trend_direction.upper()} | Confidence: {regime_state.confidence}""")
        else:
            blocks.append("\n3. MARKET REGIME: Not yet computed.")

        # ── 4. Momentum Alignment ──────────────────────────────────
        if momentum_state is not None:
            momentum_advice = {
                "BULLISH": "✅ All EMAs bullishly stacked. Long entries have macro tailwind.",
                "BEARISH": "🔴 Bearish EMA stack. Long entries fight the macro current. Avoid or use minimum qty.",
                "NEUTRAL": "⏳ EMAs mixed. Reduce position size and require stronger signal confluence.",
            }.get(momentum_state.alignment, "")

            blocks.append(f"""
4. MOMENTUM ALIGNMENT: {momentum_state.alignment}
   {momentum_advice}
   EMA Stack: {momentum_state.ema_fast:.2f} / {momentum_state.ema_mid:.2f} / {momentum_state.ema_slow:.2f}
   Size Multiplier Active: {momentum_state.size_multiplier:.0%}""")
        else:
            blocks.append("\n4. MOMENTUM: Not yet computed.")

        # ── 5. Win Pattern Analysis ────────────────────────────────
        if recent_trades:
            # Analyze if recent wins correlate with any signal pattern
            closed = [t for t in recent_trades if t.get("side") in ("SELL", "STOP_LOSS")]
            if closed:
                last_5 = closed[-5:]
                last_5_pnl = sum(t.get("pnl", 0) for t in last_5)
                last_5_wins = sum(1 for t in last_5 if t.get("pnl", 0) > 0)
                recent_form = "IMPROVING" if last_5_pnl > 0 else "DETERIORATING"

                blocks.append(f"""
5. RECENT WIN PATTERN (last 5 closed trades):
   Form: {recent_form} | Wins: {last_5_wins}/5 | Net PnL: ${last_5_pnl:+.2f}
   {"⬆️ Recent momentum is positive — consider holding or expanding." if last_5_pnl > 0 else "⬇️ Recent losses detected — prioritise tighter stops and smaller qty."}""")
        else:
            blocks.append("\n5. RECENT WIN PATTERN: No closed trade data available.")

        blocks.append("═══════════════════════════════════════════════════")

        report = "\n".join(blocks)
        logger.debug(f"[SENTIMENT] Field intelligence report generated. Session={session}")
        return report
