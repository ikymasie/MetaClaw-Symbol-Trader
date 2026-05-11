"""
TradeClaw — Strategy Plugin Architecture (Phase 3 §7.1, light)
================================================================
Provides a thin abstraction layer for the per-bot signal generation step.
Each concrete strategy delegates to existing modules (strategy.py,
trend_strategist.py, confluence.py) — this is a registry, not a rewrite.

Design choices:
  - Strategies are stateless (no per-bot state stored in the strategy class).
    Per-bot state remains on BotEngine and is passed in via kwargs.
  - The existing inline `if/elif/else` block in `BotEngine._live_tick` is
    retained as a fallback path. Registry call is best-effort wrapped in
    try/except so that any regression in a strategy class falls through
    to the proven inline logic instead of blocking trading.
  - Imports are deferred inside `generate_signal()` to avoid circular
    imports between bot_engine ↔ strategy ↔ confluence at module load time.

Usage:
    from base_strategy import STRATEGY_REGISTRY
    cls = STRATEGY_REGISTRY.get(config.strategy, CombinedStrategy)
    strat = cls()
    raw_signal = strat.generate_signal(prices=..., volumes=..., ...)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

logger = logging.getLogger("tradeclaw.strategy_registry")


class BaseStrategy(ABC):
    """
    Abstract base for a directional signal generator.

    Subclasses must implement `name` and `generate_signal`. The signature is
    intentionally permissive (**kwargs) so the registry can pass bot-specific
    context without forcing every strategy to accept the same fields.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier matching `BotConfig.strategy`."""

    @abstractmethod
    def generate_signal(
        self,
        prices: pd.Series,
        volumes: pd.Series,
        regime_state: Any,
        config: Any,
        **kwargs,
    ) -> str:
        """
        Return one of "BUY", "SELL", "HOLD".

        Required kwargs may include:
          - current_price (float)
          - history_snap  (list[dict] of recent ticks for ICT enrichment)
          - bot_id        (str)
          - mt5_symbol    (str)
        """

    def get_state_snapshot(self) -> dict:
        """Optional diagnostics. Default empty."""
        return {}


# ─────────────────────────────────────────────────────────────────────
# CONCRETE STRATEGIES
# ─────────────────────────────────────────────────────────────────────

class MeanReversionStrategy(BaseStrategy):
    """Bollinger Band mean reversion gated by the 3-Pillar Confluence engine."""

    @property
    def name(self) -> str:
        return "mean_reversion"

    def generate_signal(
        self, prices, volumes, regime_state, config, **kwargs
    ) -> str:
        from strategy import compute_bollinger_bands, detect_signal

        bb = compute_bollinger_bands(
            prices,
            period=getattr(config, "bb_period", 20),
            std_dev=getattr(config, "bb_std_dev", 2.0),
        )
        if not bb:
            return "HOLD"

        current_price = float(kwargs.get("current_price") or prices.iloc[-1])

        if getattr(config, "confluence_enabled", True):
            from confluence import evaluate_confluence

            history_snap = kwargs.get("history_snap") or []
            highs_series = pd.Series([p.get("high", p.get("price", 0)) for p in history_snap])
            lows_series = pd.Series([p.get("low", p.get("price", 0)) for p in history_snap])

            confluence = evaluate_confluence(
                prices=prices,
                volumes=volumes,
                regime_state=regime_state,
                bb=bb,
                current_price=current_price,
                rsi_period=getattr(config, "rsi_period", 14),
                rsi_oversold=getattr(config, "rsi_oversold", 30),
                rvol_threshold=getattr(config, "rvol_threshold", 1.5),
                highs=highs_series,
                lows=lows_series,
                kill_zone_active=kwargs.get("kill_zone_active", True),
                fvg_enabled=getattr(config, "ict_fvg_enabled", True),
                sweep_enabled=getattr(config, "ict_sweep_enabled", True),
                sweep_lookback=getattr(config, "ict_sweep_lookback", 20),
                short_selling_enabled=getattr(config, "short_selling_enabled", False),
            )
            # Caller may capture the confluence diagnostics dict via a kwarg sink
            if "confluence_out" in kwargs and isinstance(kwargs["confluence_out"], dict):
                kwargs["confluence_out"].update(confluence.to_dict())
            return confluence.entry_signal

        return detect_signal(current_price, bb)


class TrendFollowingStrategy(BaseStrategy):
    """Wraps TrendStrategistAgent — used only when the regime is TRENDING."""

    @property
    def name(self) -> str:
        return "trend_following"

    def generate_signal(
        self, prices, volumes, regime_state, config, **kwargs
    ) -> str:
        from trend_strategist import TrendStrategistAgent

        bot_id = kwargs.get("bot_id", "unknown")
        adx = getattr(regime_state, "adx", None)
        agent = TrendStrategistAgent(bot_id)
        result = agent.analyse(prices, volumes, "TRENDING", adx=adx)
        return result.vote


class CombinedStrategy(BaseStrategy):
    """
    Regime-aware composite: trend-following when TRENDING, mean reversion
    otherwise. Skips entirely in VOLATILE regimes (BotEngine handles that
    gate before calling us).
    """

    @property
    def name(self) -> str:
        return "combined"

    def generate_signal(
        self, prices, volumes, regime_state, config, **kwargs
    ) -> str:
        regime = getattr(regime_state, "regime", "RANGING")
        if regime == "TRENDING":
            return TrendFollowingStrategy().generate_signal(
                prices, volumes, regime_state, config, **kwargs
            )
        return MeanReversionStrategy().generate_signal(
            prices, volumes, regime_state, config, **kwargs
        )


class FibOnlyStrategy(BaseStrategy):
    """
    Fibonacci retracement strategy — Fib levels are already evaluated inside
    `evaluate_confluence()`, so this defers to MeanReversionStrategy which
    runs the confluence pipeline (the Fib pillar votes there).
    """

    @property
    def name(self) -> str:
        return "fib_only"

    def generate_signal(
        self, prices, volumes, regime_state, config, **kwargs
    ) -> str:
        return MeanReversionStrategy().generate_signal(
            prices, volumes, regime_state, config, **kwargs
        )


# ─────────────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────────────
#
# Keys MUST match `bot_config.VALID_STRATEGIES` values.
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "mean_reversion":  MeanReversionStrategy,
    "trend_following": TrendFollowingStrategy,
    "combined":        CombinedStrategy,
    "fib_only":        FibOnlyStrategy,
}


def get_strategy(strategy_name: str) -> BaseStrategy:
    """
    Resolve a strategy by name with safe fallback to CombinedStrategy.

    Logs a warning if the requested name is unknown so config drift surfaces
    in operator logs instead of silently swapping strategies.
    """
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        logger.warning(
            f"Unknown strategy '{strategy_name}' — defaulting to 'combined'",
            extra={
                "event": "strategy_registry_fallback",
                "requested": strategy_name,
                "fallback": "combined",
            },
        )
        cls = CombinedStrategy
    return cls()
