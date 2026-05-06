"""
TradeClaw — Bot Configuration System
=====================================
Each deployed bot has its own BotConfig identity.
FleetConfig is the portal-editable fleet-wide settings stored in Firestore.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import uuid


# ─────────────────────────────────────────────
# STRATEGY CONSTANTS
# ─────────────────────────────────────────────

STRATEGY_MEAN_REVERSION = "mean_reversion"
STRATEGY_FIB_ONLY = "fib_only"
STRATEGY_COMBINED = "combined"
STRATEGY_TREND_FOLLOWING = "trend_following"

VALID_STRATEGIES = {
    STRATEGY_MEAN_REVERSION,
    STRATEGY_FIB_ONLY,
    STRATEGY_COMBINED,
    STRATEGY_TREND_FOLLOWING,
}

SUB_AGENT_SENTIMENT = "sentiment"
SUB_AGENT_MACRO = "macro"
SUB_AGENT_EARNINGS = "earnings"
SUB_AGENT_TECHNICAL = "technical"
SUB_AGENT_WATCHMAN = "watchman"        # Market Watchman — order-flow quality
SUB_AGENT_RISK_MANAGER = "risk_manager"  # Kelly gating agent
SUB_AGENT_ICT = "ict"                    # ICT Smart Money structure agent
SUB_AGENT_CRO = "cro"                    # Adversarial Risk Officer agent

VALID_SUB_AGENTS = {
    SUB_AGENT_SENTIMENT,
    SUB_AGENT_MACRO,
    SUB_AGENT_EARNINGS,
    SUB_AGENT_TECHNICAL,
    SUB_AGENT_WATCHMAN,
    SUB_AGENT_RISK_MANAGER,
    SUB_AGENT_ICT,
    SUB_AGENT_CRO,
}


# ─────────────────────────────────────────────
# BOT CONFIG
# ─────────────────────────────────────────────

@dataclass
class BotConfig:
    """
    Full configuration for a single deployed bot.
    Stored in Firestore at bots/{bot_id}/config.
    """

    # Identity
    bot_id: str = field(default_factory=lambda: f"bot-{uuid.uuid4().hex[:8]}")
    name: str = "Unnamed Bot"
    symbol: str = "SPY"
    tags: list = field(default_factory=list)  # e.g. ["equity", "aggressive"]
    auto_start: bool = True

    # Strategy
    strategy: str = STRATEGY_COMBINED
    capital_allocation: float = 10000.0

    # Persona / Identity (Persisted for UI)
    description: str = ""
    personality: str = ""
    animal: str = ""
    category: str = ""
    ai_generated: bool = False
    demo_mode: bool = True

    # Position & Risk
    qty: int = 1
    stop_loss_pct: float = 1.0
    max_daily_drawdown_pct: float = 6.0

    # Short selling — opt-in only (existing bots remain long-only)
    short_selling_enabled: bool = False

    # Trailing stop-loss — dynamic exit floor/ceiling that locks in profit
    trailing_stop_enabled: bool = True    # Enable trailing stop alongside hard stop
    trailing_stop_pct: float = 0.5        # Trail distance as % of peak price

    # Bollinger Band params
    bb_period: int = 20
    bb_std_dev: float = 2.0

    # 3-Pillar Confluence params (Mean Reversion entry gate)
    confluence_enabled: bool = True        # Master switch — disable to fall back to raw BB
    rsi_period: int = 14                   # RSI lookback period (Wilder's smoothing)
    rsi_oversold: float = 30.0            # RSI threshold for Pillar 2 (seller exhaustion)
    rvol_threshold: float = 1.5           # Min Relative Volume for Pillar 3 (institutional participation)

    # ICT Kill Zone time filter (UTC hours)
    # Only allow NEW entry signals during these high-liquidity institutional windows.
    # Default: NY Open (13:30–16:00 UTC) + London Open (07:00–10:00 UTC)
    # Exits are NEVER gated — a bot can close a position at any time.
    kill_zone_enabled: bool = True
    kill_zone_ny_start: str = "13:30"      # NY Open kill zone start (UTC)
    kill_zone_ny_end: str = "16:00"        # NY Open kill zone end (UTC)
    kill_zone_london_start: str = "07:00"  # London Open kill zone start (UTC)
    kill_zone_london_end: str = "10:00"    # London Open kill zone end (UTC)

    # ICT Smart Money Detection
    ict_fvg_enabled: bool = True           # Enable Fair Value Gap detection
    ict_sweep_enabled: bool = True         # Enable Liquidity Sweep detection
    ict_sweep_lookback: int = 20           # Bars to look back for swing lows

    # Fibonacci params
    fib_enabled: bool = True
    fib_lookback_bars: int = 50
    fib_bounce_threshold_pct: float = 0.20
    fib_entry_mode: str = "AND"  # "AND" or "OR"
    fib_active_levels_raw: str = "23.6,38.2,50.0,61.8"

    # AI Brain
    ai_brain_enabled: bool = True
    ai_interval_minutes: int = 60
    ai_min_trades_trigger: int = 10
    ai_loss_streak_trigger: int = 3

    # Sub-agents
    sub_agents: list = field(
        default_factory=lambda: [
            SUB_AGENT_SENTIMENT,
            SUB_AGENT_MACRO,
            SUB_AGENT_EARNINGS,
            SUB_AGENT_TECHNICAL,
            SUB_AGENT_WATCHMAN,
            SUB_AGENT_RISK_MANAGER,
        ]
    )
    sub_agent_interval_minutes: int = 15

    # Phase 4 — Prompt Autoresearch (opt-in, off by default)
    # Weekly cycle: identifies weakest agent, evolves its prompt on a git branch,
    # merges if Sharpe improves, reverts if not.
    autoresearch_enabled: bool = False

    # MAS deliberation settings
    # How stale (seconds) an LLM agent vote can be before a fresh call is forced.
    # 60 min balances API cost vs. responsiveness. Reduce to 300 for critical events.
    # Increased from 30min to 60min to reduce Gemini API calls.
    agent_vote_cache_ttl_seconds: int = 3600

    # Smart Order Routing (ExecutionerAgent)
    # Minimum qty before TWAP routing is used (below threshold → LIMIT/MARKET).
    smart_routing_min_qty: int = 3
    # Delay between TWAP child order slices (milliseconds).
    twap_interval_ms: int = 500
    # Maximum acceptable slippage as a % of signal price before aborting.
    max_slippage_pct: float = 0.30
    # Maximum seconds to wait for a LIMIT order fill before converting to MARKET.
    limit_timeout_s: int = 10

    def validate(self):
        """Raise ValueError if config is invalid."""
        if self.strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {self.strategy}. Must be one of {VALID_STRATEGIES}.")
        if self.qty < 1:
            raise ValueError("qty must be >= 1")
        if self.capital_allocation < 1.0:
            raise ValueError("capital_allocation must be >= 1.0")
        if not (0.1 <= self.stop_loss_pct <= 10.0):
            raise ValueError("stop_loss_pct must be between 0.1 and 10.0")
        if not (0.1 <= self.trailing_stop_pct <= 5.0):
            raise ValueError("trailing_stop_pct must be between 0.1 and 5.0")
        if not (0.5 <= self.max_daily_drawdown_pct <= 25.0):
            raise ValueError("max_daily_drawdown_pct must be between 0.5 and 25.0")
        for agent in self.sub_agents:
            if agent not in VALID_SUB_AGENTS:
                raise ValueError(f"Unknown sub-agent: {agent}")

    def to_dict(self) -> dict:
        """Serialise to a plain dict (for Firestore)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BotConfig":
        """Deserialise from a Firestore document dict."""
        # Only pass known fields to avoid errors from extra Firestore fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        
        # Backwards compatibility for old saved configs missing auto_start
        if "auto_start" not in filtered:
            filtered["auto_start"] = True
            
        # Backwards compatibility for old saved configs missing earnings agent
        if "sub_agents" in filtered and isinstance(filtered["sub_agents"], list):
            if SUB_AGENT_EARNINGS not in filtered["sub_agents"]:
                filtered["sub_agents"].append(SUB_AGENT_EARNINGS)
            
        return cls(**filtered)


# ─────────────────────────────────────────────
# FLEET CONFIG
# ─────────────────────────────────────────────

@dataclass
class FleetConfig:
    """
    Fleet-wide settings, stored in Firestore at fleet/config.
    Editable at runtime via the Fleet Settings portal panel.
    """

    # Bot ceiling — portal configurable (1–50)
    max_bots: int = 10

    # Fleet-wide kill switch — halt all bots if combined drawdown exceeds this
    max_fleet_drawdown_pct: float = 10.0

    # Force all bots into demo mode regardless of individual bot config
    # DEPRECATED: Standardizing on Alpaca account-wide mode (Paper keys = Demo).
    # global_demo_mode: bool = False

    # Sub-agent master switch
    sub_agents_enabled: bool = True

    # How often all sub-agents run their analysis cycles (minutes)
    sub_agent_interval_minutes: int = 15

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FleetConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}

        return cls(**filtered)

    def validate(self):
        if not (1 <= self.max_bots <= 50):
            raise ValueError("max_bots must be between 1 and 50")
        if not (1.0 <= self.max_fleet_drawdown_pct <= 50.0):
            raise ValueError("max_fleet_drawdown_pct must be between 1 and 50")
        if self.sub_agent_interval_minutes < 1:
            raise ValueError("sub_agent_interval_minutes must be >= 1")


# ─────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────

DEFAULT_FLEET_CONFIG = FleetConfig()

# Preset bot templates for the deploy wizard
BOT_PRESETS = {
    "conservative_equity": BotConfig(
        name="Conservative Equity",
        symbol="SPY",
        strategy=STRATEGY_COMBINED,
        capital_allocation=25000.0,
        qty=1,
        stop_loss_pct=0.5,
        max_daily_drawdown_pct=3.0,
        bb_std_dev=2.5,
        tags=["equity", "conservative"],
        sub_agents=[SUB_AGENT_SENTIMENT, SUB_AGENT_MACRO],
    ),
    "aggressive_equity": BotConfig(
        name="Aggressive Equity",
        symbol="QQQ",
        strategy=STRATEGY_COMBINED,
        capital_allocation=50000.0,
        qty=5,
        stop_loss_pct=1.5,
        max_daily_drawdown_pct=8.0,
        bb_std_dev=1.8,
        tags=["equity", "aggressive"],
        sub_agents=[SUB_AGENT_SENTIMENT, SUB_AGENT_MACRO, SUB_AGENT_TECHNICAL],
    ),
    "fib_hunter": BotConfig(
        name="Fib Hunter",
        symbol="AAPL",
        strategy=STRATEGY_FIB_ONLY,
        capital_allocation=15000.0,
        qty=3,
        stop_loss_pct=1.0,
        fib_entry_mode="AND",
        fib_bounce_threshold_pct=0.15,
        tags=["equity", "fibonacci"],
        sub_agents=[SUB_AGENT_EARNINGS, SUB_AGENT_TECHNICAL],
    ),
}
