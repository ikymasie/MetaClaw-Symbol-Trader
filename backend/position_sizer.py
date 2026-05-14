"""
TradeClaw — Kelly Criterion Adaptive Position Sizer
=====================================================
Replaces gut-feel flat sizing with mathematically optimal position sizing.

The Kelly Criterion is the formula used by quant funds to determine the
optimal fraction of capital to risk per trade based on historical edge:

  Full Kelly %  = Win Rate − (Loss Rate / Win:Loss Ratio)
  Kelly Qty     = (Full Kelly × Kelly fraction × equity) / price

  Where:
    Win Rate     = fraction of trades that are winners (0.0 to 1.0)
    Loss Rate    = 1 − Win Rate
    Win:Loss     = |avg_win / avg_loss| (the reward-to-risk ratio)

Full Kelly is mathematically optimal but practically too aggressive —
it can suggest risking 40-60% of capital on a single trade.

Fractions used:
  • Quarter-Kelly (0.25): The institutional standard for live trading
  • Half-Kelly    (0.50): Used at APEX tier when performance is strong
  • Eighth-Kelly  (0.125): Defensive mode when WOUNDED

Safety Rules:
  1. Requires minimum 20 closed trades for reliable statistics
  2. If Kelly is negative (edge < 0), returns 1 (minimum defensive size)
  3. Hard cap: never exceed the config max_qty_multiplier × base_qty
  4. Survival state gates: WOUNDED = Eighth-Kelly, ORGAN_FAILURE = 0
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("tradeclaw.sizer")

# Minimum trades before Kelly can be trusted
MIN_TRADES_FOR_KELLY = 20

# Kelly fraction presets by survival / apex state
KELLY_FRACTIONS = {
    # Survival gating
    "DECEASED":      0.000,
    "ORGAN_FAILURE": 0.000,
    "WOUNDED":       0.125,  # Eighth-Kelly — capital preservation mode
    # Normal / Apex
    "HEALTHY_HUNTING":    0.250,  # Quarter-Kelly — standard
    "HEALTHY_DOMINANT":   0.250,
    "HEALTHY_APEX":       0.375,  # 3/8-Kelly — earned the right to scale
    "HEALTHY_SINGULARITY": 0.500, # Half-Kelly — maximum autonomy
}


class PositionSizer:
    """
    The Organism's Financial Immune System.

    The organism does not bet blindly. Every position is sized according
    to the mathematical edge it has earned from its performance history.
    No edge → minimum size. Proven edge → scaled expansion.

    Usage:
        sizer = PositionSizer()
        qty = sizer.get_qty(
            win_rate=0.55,
            avg_win=120.0,
            avg_loss=-80.0,
            base_qty=5,
            survival_state="HEALTHY",
            apex_state="DOMINANT",
            kelly_fraction_override=None,  # None = auto from survival/apex state
            min_trades=25,
        )
    """

    def __init__(self, min_trades_for_kelly: int = MIN_TRADES_FOR_KELLY):
        self.min_trades_for_kelly = min_trades_for_kelly

    def get_qty(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        total_trades: int,
        base_qty: float,
        survival_state: str = "HEALTHY",
        apex_state: str = "HUNTING",
        kelly_fraction_override: Optional[float] = None,
        max_qty: float = 50.0,
        hunger_multiplier: float = 1.0,
    ) -> tuple[float, dict]:
        """
        Calculate the Kelly-optimal position quantity.

        Returns:
            (qty, diagnostics_dict)
        """
        diag = {
            "method": "kelly",
            "base_qty": base_qty,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_trades": total_trades,
            "survival_state": survival_state,
            "apex_state": apex_state,
            "hunger_multiplier": hunger_multiplier,
        }

        # ── Hard gates ────────────────────────────────────────────
        if survival_state in ("DECEASED", "ORGAN_FAILURE"):
            logger.warning(
                f"[SIZER] {survival_state} — position sizing blocked. Returning 0."
            )
            diag.update({"kelly_fraction": 0.0, "full_kelly": 0.0, "final_qty": 0.0, "reason": f"{survival_state}: no sizing"})
            return 0.0, diag

        # ── Determine Kelly Fraction ───────────────────────────────
        if kelly_fraction_override is not None:
            kelly_fraction = max(0.0, min(1.0, kelly_fraction_override))
            diag["kelly_fraction_source"] = "override"
        else:
            # Map survival + apex to fraction
            if survival_state == "WOUNDED":
                kelly_fraction = KELLY_FRACTIONS["WOUNDED"]
            else:
                key = f"HEALTHY_{apex_state}"
                kelly_fraction = KELLY_FRACTIONS.get(key, KELLY_FRACTIONS["HEALTHY_HUNTING"])
            diag["kelly_fraction_source"] = f"auto:{survival_state}+{apex_state}"
        
        # ── Hunger-Driven Kelly Boost ──────────────────────────────
        # The smaller the account (higher hunger), the more we bet.
        # 1x hunger -> no change
        # 10x hunger -> 2x Kelly boost (e.g. 0.25 -> 0.50)
        # 50x hunger -> 4x Kelly boost (e.g. 0.25 -> 1.00 Full Kelly)
        if hunger_multiplier > 1.0:
            # Scale boost: 1.0 at hunger=1, up to 4.0 at hunger=50
            boost = 1.0 + (hunger_multiplier - 1.0) * (3.0 / 49.0)
            kelly_fraction = min(2.0, kelly_fraction * boost) # Cap at Double Kelly
            diag["kelly_boost"] = round(boost, 2)
            diag["kelly_fraction_boosted"] = round(kelly_fraction, 4)

        diag["kelly_fraction"] = kelly_fraction

        # ── Hunger Mode Data Relaxation ────────────────────────────
        # In Darwinian Hunger mode (multiplier > 1.0), we don't wait for 20 trades.
        # We start sizing aggressively immediately to capture the compounding curve.
        effective_min_trades = self.min_trades_for_kelly
        if hunger_multiplier > 1.0:
            effective_min_trades = 5 # Rapid onset of Kelly logic
            diag["min_trades_adjusted"] = True

        # ── Insufficient data → use base_qty ──────────────────────
        if total_trades < effective_min_trades:
            logger.info(
                f"[SIZER] Insufficient trades ({total_trades} < {effective_min_trades}). "
                f"Using base qty={base_qty} with survival multiplier."
            )
            # Even without Kelly, apply survival scaling
            if survival_state == "WOUNDED":
                qty = max(0.01, base_qty * 0.5)
            else:
                qty = base_qty
            
            # Note: base_qty passed from strategy already includes the hunger multiplier
            # but we ensure it's not neutered here.
            diag.update({
                "full_kelly": None,
                "final_qty": qty,
                "reason": f"Insufficient data (<{effective_min_trades} trades). Base qty used.",
            })
            return min(qty, max_qty), diag

        # ── Kelly Formula ─────────────────────────────────────────
        # Ensure avg_loss is expressed as a positive number (magnitude)
        avg_loss_abs = abs(avg_loss) if avg_loss != 0 else 1.0

        if avg_loss_abs == 0 or win_rate <= 0:
            full_kelly = 0.0
        else:
            loss_rate    = 1.0 - win_rate
            win_loss_ratio = avg_win / avg_loss_abs
            full_kelly   = win_rate - (loss_rate / win_loss_ratio)

        diag["full_kelly"] = round(full_kelly, 4)

        if full_kelly <= 0:
            # Negative Kelly = no mathematical edge. Use defensive minimum.
            logger.warning(
                f"[SIZER] Kelly is negative ({full_kelly:.4f}) — no edge detected. "
                f"Returning minimum qty=1."
            )
            diag.update({"final_qty": 0.01, "reason": "Negative Kelly (no edge). Minimum qty."})
            return 0.01, diag

        # ── Apply Fraction ────────────────────────────────────────
        fractional_kelly = full_kelly * kelly_fraction

        # Scale to a concrete quantity
        # Kelly % represents fraction of capital to risk per trade
        # Without account equity in scope here, we scale against base_qty
        # This gives a qty multiplier: e.g. full_kelly=0.3 * fraction=0.25 = 7.5% of cap per trade
        # We interpret this as: qty = base_qty * (fractional_kelly / 0.25)
        # i.e. 0.25 Kelly fraction is "1x base_qty" (neutral); above = scale up, below = scale down
        # This keeps the result grounded to the configured base
        reference_fraction = 0.25
        qty_multiplier = fractional_kelly / reference_fraction if reference_fraction > 0 else 1.0
        raw_qty = base_qty * qty_multiplier

        qty = max(0.01, min(raw_qty, max_qty))

        logger.info(
            f"[SIZER] Kelly sizing: wr={win_rate:.1%} | "
            f"win/loss={avg_win:.2f}/{avg_loss:.2f} | "
            f"full_kelly={full_kelly:.4f} | "
            f"fraction={kelly_fraction:.3f} | "
            f"multiplier={qty_multiplier:.2f} | "
            f"raw_qty={raw_qty:.1f} → final_qty={qty}"
        )

        diag.update({
            "fractional_kelly": round(fractional_kelly, 4),
            "qty_multiplier": round(qty_multiplier, 3),
            "final_qty": qty,
            "reason": (
                f"Kelly: wr={win_rate:.1%} | "
                f"W/L={avg_win:.2f}/{abs(avg_loss):.2f} | "
                f"K={full_kelly:.4f} × {kelly_fraction:.3f} = {fractional_kelly:.4f} → qty={qty}"
            ),
        })

        return qty, diag

    def calculate_leverage_qty(
        self,
        price: float,
        isolated_risk_usd: float,
        leverage_factor: float,
        contract_size: float = 1.0,
    ) -> float:
        """
        Calculate quantity based on fixed isolated dollar risk and leverage.
        Formula: Qty = (Risk * Leverage) / (Price * ContractSize)
        
        Example: $40 risk @ 50x = $2000 buying power. 
        If Price is $60,000 (BTC) and contract_size is 1.0:
        Qty = 2000 / 60000 = 0.033
        """
        if price <= 0:
            return 0.0
        
        notional_value = isolated_risk_usd * leverage_factor
        qty = notional_value / (price * contract_size)
        
        # Round to 2 decimal places (standard for most MT5 lots)
        # Some symbols might need more/less, but 0.01 is the usual min lot increment.
        return round(qty, 2)
