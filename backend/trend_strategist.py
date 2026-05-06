"""
TradeClaw — Trend Strategist Agent
=====================================
Activates ONLY when the Regime Architect declares TRENDING.
Uses EMA crossover + ADX confirmation and breakout logic to generate
directional signals. Returns a HOLD vote in all other market regimes,
ensuring it never competes with the Mean Reversion Strategist.

Design decisions:
  - Fully stateless: all signals are computed from the price series passed in.
  - Returns an AgentVote compatible with the SubAgentPool.deliberate() protocol.
  - Strategy A: Replace Mean Reversion Strategist when TRENDING (strict mode).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("tradeclaw.trend_strategist")


# ── Vote constants (mirrors sub_agents.AgentVote.vote values) ─────────────
VOTE_BUY = "BUY"
VOTE_SELL = "SELL"
VOTE_HOLD = "HOLD"
VOTE_VETO = "VETO"


@dataclass
class TrendSignal:
    """Result from TrendStrategistAgent.analyse()."""
    vote: str                        # BUY | SELL | HOLD | VETO
    confidence: float                # 0.0 – 1.0
    reasoning: str
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    adx: float = 0.0
    breakout_triggered: bool = False
    veto_reason: Optional[str] = None


class TrendStrategistAgent:
    """
    Expert Trend Strategist sub-agent.

    Signal logic:
    ─────────────
    1. EMA Crossover Gate
       - EMA(9) crosses above EMA(21) + ADX > 25  →  BUY impulse
       - EMA(9) crosses below EMA(21) + ADX > 25  →  SELL impulse

    2. Breakout Confirmation
       - Price closes above 20-period rolling high + volume > 1.5× avg  →  BUY
       - Price closes below 20-period rolling low  + volume > 1.5× avg  →  SELL

    3. Confidence scoring
       - Both signals agree → confidence ≥ 0.75
       - Single signal only → confidence 0.50
       - Opposing signals   → HOLD

    Regime guard:
    - If regime is NOT TRENDING, immediately returns HOLD with confidence 0.
    - MeanReversionEngine is suppressed by bot_engine when regime is TRENDING,
      so these two strategists are strictly mutually exclusive.
    """

    # EMA periods
    EMA_FAST_PERIOD: int = 9
    EMA_SLOW_PERIOD: int = 21

    # ADX minimum to confirm trend strength
    ADX_THRESHOLD: float = 25.0

    # Breakout lookback (bars)
    BREAKOUT_LOOKBACK: int = 20

    # Volume multiplier required to confirm breakout
    VOLUME_SPIKE_MIN: float = 1.5

    # Minimum bars required in the price series
    MIN_BARS: int = 30

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._logger = logging.getLogger(f"tradeclaw.trend[{bot_id}]")

    # ── Public API ─────────────────────────────────────────────────────────

    def analyse(
        self,
        prices: pd.Series,
        volumes: Optional[pd.Series],
        regime: str,                # "RANGING" | "TRENDING" | "VOLATILE"
    ) -> TrendSignal:
        """
        Analyse the price/volume series and return a TrendSignal.

        Args:
            prices:  Close price series (chronological, oldest first).
            volumes: Volume series aligned to prices (may be None).
            regime:  Current regime from RegimeDetector.
        """
        if regime != "TRENDING":
            return TrendSignal(
                vote=VOTE_HOLD,
                confidence=0.0,
                reasoning=f"Regime is {regime} — TrendStrategist stands down.",
            )

        if len(prices) < self.MIN_BARS:
            return TrendSignal(
                vote=VOTE_HOLD,
                confidence=0.0,
                reasoning=f"Insufficient data ({len(prices)} bars < {self.MIN_BARS} required).",
            )

        try:
            return self._compute(prices, volumes)
        except Exception as e:
            self._logger.exception(f"TrendStrategist compute error: {e}")
            return TrendSignal(
                vote=VOTE_HOLD,
                confidence=0.0,
                reasoning=f"Compute error: {e}",
            )

    # ── Internal computation ───────────────────────────────────────────────

    def _compute(
        self, prices: pd.Series, volumes: Optional[pd.Series]
    ) -> TrendSignal:

        # ── EMA crossover ──────────────────────────────────────────────────
        ema_fast = prices.ewm(span=self.EMA_FAST_PERIOD, adjust=False).mean()
        ema_slow = prices.ewm(span=self.EMA_SLOW_PERIOD, adjust=False).mean()

        cur_fast = ema_fast.iloc[-1]
        cur_slow = ema_slow.iloc[-1]
        prev_fast = ema_fast.iloc[-2]
        prev_slow = ema_slow.iloc[-2]

        ema_crossed_up = prev_fast <= prev_slow and cur_fast > cur_slow
        ema_crossed_dn = prev_fast >= prev_slow and cur_fast < cur_slow

        # ── ADX (trend strength) ───────────────────────────────────────────
        adx = self._compute_adx(prices)

        # ── Breakout detection ─────────────────────────────────────────────
        lookback = prices.iloc[-(self.BREAKOUT_LOOKBACK + 1):-1]
        recent_high = lookback.max()
        recent_low = lookback.min()
        current_price = prices.iloc[-1]

        volume_confirms = False
        if volumes is not None and len(volumes) >= self.BREAKOUT_LOOKBACK:
            avg_vol = volumes.iloc[-self.BREAKOUT_LOOKBACK:].mean()
            cur_vol = volumes.iloc[-1]
            volume_confirms = (cur_vol >= avg_vol * self.VOLUME_SPIKE_MIN)

        breakout_up = (current_price > recent_high) and volume_confirms
        breakout_dn = (current_price < recent_low) and volume_confirms

        # ── Signal aggregation ─────────────────────────────────────────────
        adx_ok = adx >= self.ADX_THRESHOLD

        buy_signals = int(ema_crossed_up and adx_ok) + int(breakout_up)
        sell_signals = int(ema_crossed_dn and adx_ok) + int(breakout_dn)

        # ── Momentum continuation ──────────────────────────────────────────
        # When EMAs are already separated (no fresh crossover) but ADX is
        # strong, generate a moderate continuation signal in the trend
        # direction.  This prevents the strategist from sitting idle during
        # sustained trends where the crossover happened many bars ago.
        ema_gap_pct = (cur_fast - cur_slow) / cur_slow * 100 if cur_slow != 0 else 0
        MOMENTUM_GAP_PCT = 0.15  # minimum EMA gap (%) to consider momentum

        momentum_buy = (not ema_crossed_up and not breakout_up
                        and adx_ok and ema_gap_pct > MOMENTUM_GAP_PCT)
        momentum_sell = (not ema_crossed_dn and not breakout_dn
                         and adx_ok and ema_gap_pct < -MOMENTUM_GAP_PCT)

        if buy_signals > 0 and sell_signals > 0:
            # Conflicting — stand down
            return TrendSignal(
                vote=VOTE_HOLD,
                confidence=0.3,
                reasoning="EMA crossover and breakout signals are conflicting.",
                ema_fast=cur_fast,
                ema_slow=cur_slow,
                adx=adx,
            )

        if buy_signals == 2:
            vote, conf = VOTE_BUY, 0.85
            reasoning = (
                f"Strong BUY: EMA(9) crossed above EMA(21) (ADX={adx:.1f}) "
                f"AND price broke above {recent_high:.2f} with {self.VOLUME_SPIKE_MIN}× volume."
            )
        elif buy_signals == 1:
            vote, conf = VOTE_BUY, 0.55
            src = "EMA crossover" if (ema_crossed_up and adx_ok) else "breakout"
            reasoning = f"Moderate BUY: Single {src} signal (ADX={adx:.1f})."
        elif sell_signals == 2:
            vote, conf = VOTE_SELL, 0.85
            reasoning = (
                f"Strong SELL: EMA(9) crossed below EMA(21) (ADX={adx:.1f}) "
                f"AND price broke below {recent_low:.2f} with {self.VOLUME_SPIKE_MIN}× volume."
            )
        elif sell_signals == 1:
            vote, conf = VOTE_SELL, 0.55
            src = "EMA crossover" if (ema_crossed_dn and adx_ok) else "breakdown"
            reasoning = f"Moderate SELL: Single {src} signal (ADX={adx:.1f})."
        elif momentum_buy:
            vote, conf = VOTE_BUY, 0.45
            reasoning = (
                f"Momentum continuation BUY: EMA gap={ema_gap_pct:+.2f}%, "
                f"ADX={adx:.1f} — sustained uptrend."
            )
        elif momentum_sell:
            vote, conf = VOTE_SELL, 0.45
            reasoning = (
                f"Momentum continuation SELL: EMA gap={ema_gap_pct:+.2f}%, "
                f"ADX={adx:.1f} — sustained downtrend."
            )
        else:
            vote, conf = VOTE_HOLD, 0.1
            reasoning = (
                f"No trend signal: EMA gap={ema_gap_pct:+.2f}%, "
                f"ADX={adx:.1f}, no breakout."
            )

        self._logger.debug(
            f"[{self.bot_id}] TrendStrategist → {vote} @ {conf:.0%} | {reasoning}"
        )

        return TrendSignal(
            vote=vote,
            confidence=conf,
            reasoning=reasoning,
            ema_fast=cur_fast,
            ema_slow=cur_slow,
            adx=adx,
            breakout_triggered=(breakout_up or breakout_dn),
        )

    def _compute_adx(self, prices: pd.Series, period: int = 14) -> float:
        """
        Compute ADX using a simplified Wilder smoothing approach.
        Requires at least `period + 1` bars.
        """
        if len(prices) < period + 1:
            return 0.0

        delta = prices.diff()

        # Approximate True Range using price-only (no high/low available here)
        # We use the absolute daily return as a proxy
        tr = delta.abs()

        # +DM and -DM approximations using price direction
        plus_dm = delta.clip(lower=0)
        minus_dm = (-delta).clip(lower=0)

        # Wilder smoothing
        atr = tr.ewm(alpha=1 / period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / di_sum

        adx = dx.ewm(alpha=1 / period, adjust=False).mean()
        return float(adx.iloc[-1]) if not adx.empty else 0.0
