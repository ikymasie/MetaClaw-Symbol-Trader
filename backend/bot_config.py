"""
TradeClaw — Bot Configuration System
=====================================
Each deployed bot has its own BotConfig identity.
FleetConfig is the portal-editable fleet-wide settings stored in Firestore.
"""

from dataclasses import dataclass, field, asdict
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
SUB_AGENT_RESEARCH = "research_framework"  # TradingAgents research framework
SUB_AGENT_CORRELATION = "correlation"      # Inter-market correlation agent
SUB_AGENT_ORDERFLOW = "orderflow"          # Order flow / volume profile agent
SUB_AGENT_CALENDAR = "calendar"            # Economic calendar gate agent

VALID_SUB_AGENTS = {
    SUB_AGENT_SENTIMENT,
    SUB_AGENT_MACRO,
    SUB_AGENT_EARNINGS,
    SUB_AGENT_TECHNICAL,
    SUB_AGENT_WATCHMAN,
    SUB_AGENT_RISK_MANAGER,
    SUB_AGENT_ICT,
    SUB_AGENT_CRO,
    SUB_AGENT_RESEARCH,
    SUB_AGENT_CORRELATION,
    SUB_AGENT_ORDERFLOW,
    SUB_AGENT_CALENDAR,
}


# ─────────────────────────────────────────────
# BOT CONFIG
# ─────────────────────────────────────────────

@dataclass
class BotConfig:
    """
    Full configuration for a single deployed bot.
    Stored in PostgreSQL at bot_configs table.
    """

    # Identity
    bot_id: str = field(default_factory=lambda: f"bot-{uuid.uuid4().hex[:8]}")
    account_id: str = ""  # MT5 account ID from ConfigManager
    name: str = "Unnamed Bot"
    symbol: str = "EURUSD"
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

    # Position & Risk
    qty: float = 1.0
    stop_loss_pct: float = 1.0
    max_daily_drawdown_pct: float = 6.0

    # ── Trading Psychology (open-position discipline) ────────────────────
    # Encodes the disciplined-trader behaviours from "Mastering Trading
    # Psychology" (Aziz). Deterministic guards run on every 5s tick; the
    # LLM "narrator" (psych_review_*) is a throttled enrichment, never the
    # hot path. SAFETY INVARIANT: nothing here can ever widen or remove the
    # predefined hard stop — judgment-holds act on the profit side only.
    psychology_enabled: bool = True          # master switch for the whole layer
    block_average_down: bool = True          # block scale-ins that add to a loser
    max_loser_hold_secs: int = 1800          # cut a loser held longer than this (0=off)
    max_position_hold_secs: int = 7200       # day-trade→swing horizon cap (0=off)
    max_adverse_excursion_usd: float = 0.0   # cut a loser whose MAE breaches this $ (0=off)
    tilt_loss_streak: int = 3                # consecutive losses → tilt cool-down lockout
    tilt_cooldown_secs: int = 900            # how long the bot "steps away" after tilt
    overconfidence_win_streak: int = 4       # consecutive wins → size down (humility)
    rolling_giveback_pct: float = 0.30       # halt entries if equity gives back this % of peak
    rolling_trade_window_secs: int = 3600    # window for the overtrading cap (rolling, 24/7-safe)
    max_trades_per_window: int = 0           # max entries per window (0=unlimited)
    # Tier-2 LLM position-review narrator
    psych_review_enabled: bool = True        # run the throttled "human" position review
    psych_review_interval_secs: int = 300    # periodic review cadence per open position
    psych_review_adverse_usd: float = 0.0    # force a review when MAE crosses this $ (0=off)

    # Short selling — enabled by default so bots trade both directions
    short_selling_enabled: bool = True

    # Trailing stop-loss — dynamic exit floor/ceiling that locks in profit
    trailing_stop_enabled: bool = True    # Enable trailing stop alongside hard stop
    trailing_stop_pct: float = 0.8        # Trail distance as % of peak price — wide enough
                                          # to let runners breathe on volatile synthetics

    # ── Anti-Fakeout Filter ──────────────────────────────────────────────
    # Rejects entries that show an algorithmic stop-hunt / failed-breakout /
    # liquidity-sweep trap (price pokes beyond a swing extreme then snaps back).
    # Applied at BOTH layers: the trend-strategist breakout confirmation
    # (signal layer) and the engine entry gate for every directional entry.
    fakeout_filter_enabled: bool = True
    fakeout_atr_buffer_mult: float = 0.25    # breakout must clear the level by ≥ this × ATR
    fakeout_wick_reject_ratio: float = 0.50  # reject if the rejection wick ≥ this share of the move
    fakeout_swing_lookback: int = 20         # bars scanned for the swept swing extreme

    # ── Advanced Profit Retrace (per-ticket profit ratchet) ──────────────
    # Tracks each open position's PEAK floating net profit and trails a rising
    # give-back floor beneath it. Once peak net ≥ arm_usd the floor arms; if net
    # profit later falls to the floor the position is banked. The floor sits
    # BELOW net_profit_target_usd, so winners still run to target — this only
    # catches the painful "almost hit target then reversed" give-back. The
    # give-back tightens as profit deepens (accelerating lock) and widens with
    # volatility when atr_adaptive is on. Per-ticket → correct under scale-in.
    # Defaults tuned CONSERVATIVE: arm late + wide give-back so the ratchet only
    # catches genuine give-backs near the net target and rarely cuts a winner
    # that would have recovered. Tighten these to protect profit more eagerly.
    profit_retrace_enabled: bool = True
    profit_retrace_arm_usd: float = 0.65          # start protecting once peak net ≥ this
    profit_retrace_giveback_pct: float = 0.50     # floor = peak × (1 − this) while shallow
    profit_retrace_tighten_usd: float = 1.50      # above this peak, switch to tighter give-back
    profit_retrace_tight_giveback_pct: float = 0.30  # tighter give-back once deep in profit
    profit_retrace_min_lock_usd: float = 0.05     # floor never drops below this once armed
    profit_retrace_atr_adaptive: bool = True      # widen give-back when ATR% (volatility) is high

    # ── Boost Position (trend-confirmation runner) ───────────────────────
    # When the bot opens ≥ boost_trigger_slots same-direction scalp slots (a
    # confirmed trend), it auto-opens ONE larger same-direction "boost" position.
    # The boost is a separate, longer-horizon class: NO take-profit, NO broker
    # stop-loss — it rides for as long as the trend holds and is closed only when
    #   (a) fast timeframes (M1/M5/M15) flip against it while in profit, OR
    #   (b) profit retraces past a give-back floor, OR
    #   (c) gross loss hits the hard software cap (boost_max_loss_usd).
    # Tagged by comment prefix "TC_BOOST_"; never consumes a scalp slot.
    boost_enabled: bool = True
    boost_lot: float = 0.05               # boost position size (lots)
    boost_trigger_slots: int = 2          # ≥ this many same-dir scalp slots → open boost
    boost_max_loss_usd: float = 30.0      # hard software loss cap (no broker SL is set)
    boost_arm_usd: float = 1.5            # peak profit before the give-back retrace arms
    boost_giveback_pct: float = 0.35      # close when net ≤ peak × (1 − this)
    boost_mtf_exit_enabled: bool = True   # close on multi-timeframe trend reversal (while in profit)
    boost_mtf_min_flip: int = 2           # ≥ this many of M1/M5/M15 flipped against → exit
    boost_mtf_refresh_secs: int = 20      # throttle the multi-timeframe fetch

    # Regime detection thresholds
    # VOLATILE regime blocks all new entries when ATR z-score exceeds this.
    # Default 3.0 (3-sigma) is appropriate for crypto; forex may use 2.0–2.5.
    atr_volatile_zscore: float = 3.0

    # Bollinger Band params
    bb_period: int = 20
    bb_std_dev: float = 2.0

    # 3-Pillar Confluence params (Mean Reversion entry gate)
    confluence_enabled: bool = True        # Master switch — disable to fall back to raw BB
    rsi_period: int = 14                   # RSI lookback period (Wilder's smoothing)
    rsi_oversold: float = 30.0            # RSI threshold for Pillar 2 (seller exhaustion). 30=standard; crypto may benefit from 35-40.
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
    
    # Research Bridge (TradingAgents integration)
    research_enabled: bool = True
    research_interval_hours: int = 4

    # Sub-agents
    sub_agents: list = field(
        default_factory=lambda: [
            SUB_AGENT_SENTIMENT,
            SUB_AGENT_MACRO,
            SUB_AGENT_EARNINGS,
            SUB_AGENT_TECHNICAL,
            SUB_AGENT_WATCHMAN,
            SUB_AGENT_RISK_MANAGER,
            SUB_AGENT_RESEARCH,
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

    # Multi-Position / Scale-In (Scenario 3 & 5)
    # Each confirmed signal opens one slot; up to max_position_slots can be open at once.
    # Kelly qty is split evenly: each slot gets base_qty / max_position_slots.
    scale_in_enabled: bool = True
    max_position_slots: int = 5

    # Per-position take-profit in USD. When a single MT5 position's floating profit
    # exceeds this threshold it is closed immediately, regardless of other signals.
    # 0.0 = disabled.
    take_profit_usd: float = 0.0

    # Per-trade hard stop-loss in gross dollars. When a single open position's
    # gross loss exceeds this, it is closed immediately — caps each scalp's
    # downside so a trend reversal can't ladder many longs into the fleet
    # drawdown halt. 0.0 = disabled.
    stop_loss_usd: float = 0.0

    # Leverage Mode (Darwinian Scalper)
    # Target: Snatch and grab small net profits using high leverage.
    leverage_mode_enabled: bool = True
    leverage_factor: float = 20.0       # e.g. 20x, 50x
    isolated_risk_usd: float = 40.0     # Total dollar amount at risk/margin per trade
    net_profit_target_usd: float = 1.0  # Target net profit (after fees) per trade

    # Capital-proportional position sizing.
    # When enabled, lot size is derived from capital_allocation and risk_pct_per_trade
    # rather than the raw qty field.  This prevents over-leveraging small accounts.
    #
    # Formula:
    #   dollar_risk = capital_allocation × (risk_pct_per_trade / 100)
    #   lot_size    = dollar_risk / (stop_loss_pct / 100 × current_price × contract_size)
    #
    # The raw qty field is used as an UPPER BOUND (never exceed it).
    auto_size_qty: bool = True
    risk_pct_per_trade: float = 1.0   # Max % of capital risked on a single entry

    # Smart Order Routing (ExecutionerAgent)
    # Minimum qty before TWAP routing is used (below threshold → LIMIT/MARKET).
    smart_routing_min_qty: float = 3.0
    # Delay between TWAP child order slices (milliseconds).
    twap_interval_ms: int = 500
    # Maximum acceptable slippage as a % of signal price before aborting.
    max_slippage_pct: float = 0.05
    # Maximum seconds to wait for a LIMIT order fill before converting to MARKET.
    limit_timeout_s: int = 10

    def validate(self):
        """Raise ValueError if config is invalid."""
        if self.strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {self.strategy}. Must be one of {VALID_STRATEGIES}.")
        if self.qty <= 0:
            raise ValueError("qty must be > 0")
        if self.capital_allocation < 1.0:
            raise ValueError("capital_allocation must be >= 1.0")
        if not (0.1 <= self.stop_loss_pct <= 10.0):
            raise ValueError("stop_loss_pct must be between 0.1 and 10.0")
        if not (0.1 <= self.trailing_stop_pct <= 5.0):
            raise ValueError("trailing_stop_pct must be between 0.1 and 5.0")
        if not (0.0 <= self.fakeout_atr_buffer_mult <= 3.0):
            raise ValueError("fakeout_atr_buffer_mult must be between 0.0 and 3.0")
        if not (0.0 <= self.fakeout_wick_reject_ratio <= 1.0):
            raise ValueError("fakeout_wick_reject_ratio must be between 0.0 and 1.0")
        if self.fakeout_swing_lookback < 5:
            raise ValueError("fakeout_swing_lookback must be >= 5")
        if self.profit_retrace_arm_usd < 0:
            raise ValueError("profit_retrace_arm_usd must be >= 0")
        if not (0.0 < self.profit_retrace_giveback_pct < 1.0):
            raise ValueError("profit_retrace_giveback_pct must be between 0 and 1 (exclusive)")
        if not (0.0 < self.profit_retrace_tight_giveback_pct < 1.0):
            raise ValueError("profit_retrace_tight_giveback_pct must be between 0 and 1 (exclusive)")
        if self.profit_retrace_min_lock_usd < 0:
            raise ValueError("profit_retrace_min_lock_usd must be >= 0")
        if self.boost_lot <= 0:
            raise ValueError("boost_lot must be > 0")
        if self.boost_trigger_slots < 2:
            raise ValueError("boost_trigger_slots must be >= 2")
        if self.boost_max_loss_usd <= 0:
            raise ValueError("boost_max_loss_usd must be > 0")
        if self.boost_arm_usd < 0:
            raise ValueError("boost_arm_usd must be >= 0")
        if not (0.0 < self.boost_giveback_pct < 1.0):
            raise ValueError("boost_giveback_pct must be between 0 and 1 (exclusive)")
        if not (1 <= self.boost_mtf_min_flip <= 3):
            raise ValueError("boost_mtf_min_flip must be between 1 and 3")
        if not (0.5 <= self.max_daily_drawdown_pct <= 25.0):
            raise ValueError("max_daily_drawdown_pct must be between 0.5 and 25.0")
        # ── Trading Psychology bounds ──
        if self.max_loser_hold_secs < 0:
            raise ValueError("max_loser_hold_secs must be >= 0")
        if self.max_position_hold_secs < 0:
            raise ValueError("max_position_hold_secs must be >= 0")
        if self.max_adverse_excursion_usd < 0:
            raise ValueError("max_adverse_excursion_usd must be >= 0")
        if self.tilt_loss_streak < 1:
            raise ValueError("tilt_loss_streak must be >= 1")
        if self.tilt_cooldown_secs < 0:
            raise ValueError("tilt_cooldown_secs must be >= 0")
        if self.overconfidence_win_streak < 1:
            raise ValueError("overconfidence_win_streak must be >= 1")
        if not (0.0 < self.rolling_giveback_pct < 1.0):
            raise ValueError("rolling_giveback_pct must be between 0 and 1 (exclusive)")
        if self.rolling_trade_window_secs < 60:
            raise ValueError("rolling_trade_window_secs must be >= 60")
        if self.max_trades_per_window < 0:
            raise ValueError("max_trades_per_window must be >= 0")
        if self.psych_review_interval_secs < 30:
            raise ValueError("psych_review_interval_secs must be >= 30")
        if self.psych_review_adverse_usd < 0:
            raise ValueError("psych_review_adverse_usd must be >= 0")
        if not (1 <= self.research_interval_hours <= 48):
            raise ValueError("research_interval_hours must be between 1 and 48")
        for agent in self.sub_agents:
            if agent not in VALID_SUB_AGENTS:
                raise ValueError(f"Unknown sub-agent: {agent}")

    def to_dict(self) -> dict:
        """Serialise to a plain dict (for Firestore)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BotConfig":
        """Deserialise from a Firestore document dict."""
        # Clean up legacy mode flags
        data.pop("demo_mode", None)
        data.pop("simulated_mode", None)

        # Only pass known fields to avoid errors from extra Firestore fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}

        # Migrate: if a legacy config still has the old extreme 60.0 RSI threshold,
        # reset it to the standard 30.0 so the confluence gate works correctly.
        if filtered.get("rsi_oversold") == 60.0:
            filtered["rsi_oversold"] = 30.0
        
        # Backwards compatibility for old saved configs missing auto_start
        if "auto_start" not in filtered:
            filtered["auto_start"] = True
            
        # Backwards compatibility for old saved configs missing earnings agent
        if "sub_agents" in filtered and isinstance(filtered["sub_agents"], list):
            if SUB_AGENT_EARNINGS not in filtered["sub_agents"]:
                filtered["sub_agents"].append(SUB_AGENT_EARNINGS)

        # Backwards compatibility for old saved configs missing atr_volatile_zscore
        if "atr_volatile_zscore" not in filtered:
            filtered["atr_volatile_zscore"] = 3.0

        # Backwards compatibility for Trading Psychology fields: configs saved
        # before the layer existed simply omit these keys and inherit the
        # dataclass defaults. Strip any explicit None so the default applies.
        _psych_fields = {
            "psychology_enabled", "block_average_down", "max_loser_hold_secs",
            "max_position_hold_secs", "max_adverse_excursion_usd", "tilt_loss_streak",
            "tilt_cooldown_secs", "overconfidence_win_streak", "rolling_giveback_pct",
            "rolling_trade_window_secs", "max_trades_per_window", "psych_review_enabled",
            "psych_review_interval_secs", "psych_review_adverse_usd",
        }
        for _f in _psych_fields:
            if filtered.get(_f) is None:
                filtered.pop(_f, None)

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

    # Hard cap on simultaneous open positions across the entire fleet (Scenario 2 & 3).
    # CRO issues a hard VETO when this limit is reached, blocking new entries.
    max_open_positions: int = 6

    # Fleet-wide kill switch — halt all bots if combined drawdown exceeds this
    max_fleet_drawdown_pct: float = 10.0

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
        if not (1 <= self.max_open_positions <= 50):
            raise ValueError("max_open_positions must be between 1 and 50")
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
    "conservative_forex": BotConfig(
        name="Conservative Forex",
        symbol="EURUSD",
        strategy=STRATEGY_COMBINED,
        capital_allocation=25000.0,
        qty=1,
        stop_loss_pct=0.5,
        max_daily_drawdown_pct=3.0,
        bb_std_dev=2.5,
        tags=["forex", "conservative"],
        sub_agents=[SUB_AGENT_SENTIMENT, SUB_AGENT_MACRO],
        # Trading psychology — max discipline
        block_average_down=True, rolling_giveback_pct=0.15,
        tilt_loss_streak=2, tilt_cooldown_secs=1200, max_loser_hold_secs=900,
    ),
    "aggressive_forex": BotConfig(
        name="Aggressive Forex",
        symbol="GBPUSD",
        strategy=STRATEGY_COMBINED,
        capital_allocation=50000.0,
        qty=5,
        stop_loss_pct=1.5,
        max_daily_drawdown_pct=8.0,
        bb_std_dev=1.8,
        tags=["forex", "aggressive"],
        sub_agents=[SUB_AGENT_SENTIMENT, SUB_AGENT_MACRO, SUB_AGENT_TECHNICAL],
        # Trading psychology — aggressive, rails stay on
        block_average_down=True, rolling_giveback_pct=0.30,
        tilt_loss_streak=3, tilt_cooldown_secs=600, max_loser_hold_secs=2400,
    ),
    "crypto_hunter": BotConfig(
        name="Crypto Hunter",
        symbol="BTCUSD",
        strategy=STRATEGY_FIB_ONLY,
        capital_allocation=15000.0,
        qty=3,
        stop_loss_pct=1.0,
        fib_entry_mode="AND",
        fib_bounce_threshold_pct=0.15,
        tags=["crypto", "fibonacci"],
        sub_agents=[SUB_AGENT_EARNINGS, SUB_AGENT_TECHNICAL],
        # Trading psychology — balanced
        block_average_down=True, rolling_giveback_pct=0.25,
        tilt_loss_streak=3, tilt_cooldown_secs=900, max_loser_hold_secs=1800,
    ),
}
