"""
TradeClaw — Single Trading Session
====================================
Replaces FleetOrchestrator + BotInstance + per-bot isolation.
One session: one symbol, one spirit preset, one MT5 connection.
"""

import logging
import json
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from mt5_hub import mt5_hub

logger = logging.getLogger("tradeclaw.session")


@dataclass
class SessionConfig:
    """Trading configuration derived from spirit preset + symbol."""
    symbol: str = "EURUSD"
    spirit: str = "elephant"  # elephant, buffalo, rhino, leopard, lion
    strategy: str = "combined"

    # Position & Risk
    qty: float = 1.0
    stop_loss_pct: float = 1.0
    max_daily_drawdown_pct: float = 6.0
    short_selling_enabled: bool = True
    trailing_stop_enabled: bool = True
    trailing_stop_pct: float = 0.5

    # Bollinger Band params
    bb_period: int = 20
    bb_std_dev: float = 2.0

    # Confluence
    confluence_enabled: bool = True
    rsi_period: int = 14
    rsi_oversold: float = 45.0
    rvol_threshold: float = 1.5

    # ICT Kill Zone
    kill_zone_enabled: bool = True
    kill_zone_ny_start: str = "13:30"
    kill_zone_ny_end: str = "16:00"
    kill_zone_london_start: str = "07:00"
    kill_zone_london_end: str = "10:00"

    # ICT Smart Money
    ict_fvg_enabled: bool = True
    ict_sweep_enabled: bool = True
    ict_sweep_lookback: int = 20

    # Fibonacci
    fib_enabled: bool = True
    fib_lookback_bars: int = 50
    fib_bounce_threshold_pct: float = 0.20
    fib_entry_mode: str = "AND"
    fib_active_levels_raw: str = "23.6,38.2,50.0,61.8"

    # AI Brain
    ai_brain_enabled: bool = True
    ai_interval_minutes: int = 60
    ai_min_trades_trigger: int = 10
    ai_loss_streak_trigger: int = 3

    # Sub-agents
    sub_agents: list = field(default_factory=lambda: [
        "sentiment", "macro", "earnings", "technical",
        "watchman", "risk_manager", "research_framework",
    ])
    sub_agent_interval_minutes: int = 15
    agent_vote_cache_ttl_seconds: int = 3600

    # Scale-in
    scale_in_enabled: bool = True
    max_position_slots: int = 5
    take_profit_usd: float = 0.0

    # Leverage
    leverage_mode_enabled: bool = True
    leverage_factor: float = 20.0
    isolated_risk_usd: float = 40.0
    net_profit_target_usd: float = 1.0

    # Sizing
    auto_size_qty: bool = True
    risk_pct_per_trade: float = 1.0
    capital_allocation: float = 10000.0

    # Smart routing
    smart_routing_min_qty: float = 3.0
    twap_interval_ms: int = 500
    max_slippage_pct: float = 0.05
    limit_timeout_s: int = 10

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ── Spirit Presets ────────────────────────────────────────────────────────

SPIRIT_PRESETS = {
    "elephant": SessionConfig(  # Risk level 1 — ultra conservative
        spirit="elephant",
        strategy="mean_reversion",
        qty=1, stop_loss_pct=0.5, max_daily_drawdown_pct=3.0,
        bb_std_dev=2.5, capital_allocation=25000.0,
        sub_agents=["sentiment", "macro"],
        ai_interval_minutes=120, sub_agent_interval_minutes=30,
        scale_in_enabled=False, max_position_slots=1,
        leverage_mode_enabled=False,
    ),
    "buffalo": SessionConfig(  # Risk level 2 — conservative
        spirit="buffalo",
        strategy="combined",
        qty=2, stop_loss_pct=1.0, max_daily_drawdown_pct=5.0,
        bb_std_dev=2.2, capital_allocation=30000.0,
        fib_entry_mode="AND",
        sub_agents=["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        ai_interval_minutes=90, sub_agent_interval_minutes=20,
        scale_in_enabled=True, max_position_slots=3,
    ),
    "rhino": SessionConfig(  # Risk level 3 — balanced
        spirit="rhino",
        strategy="trend_following",
        qty=3, stop_loss_pct=1.2, max_daily_drawdown_pct=6.0,
        bb_std_dev=2.0, capital_allocation=40000.0,
        fib_entry_mode="OR",
        sub_agents=["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager", "research_framework"],
        ai_interval_minutes=60, sub_agent_interval_minutes=15,
        scale_in_enabled=True, max_position_slots=4,
    ),
    "leopard": SessionConfig(  # Risk level 4 — aggressive
        spirit="leopard",
        strategy="mean_reversion",
        qty=4, stop_loss_pct=1.5, max_daily_drawdown_pct=8.0,
        bb_std_dev=1.8, capital_allocation=50000.0,
        fib_bounce_threshold_pct=0.15, fib_entry_mode="OR",
        sub_agents=["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager", "research_framework"],
        ai_interval_minutes=30, sub_agent_interval_minutes=10,
        scale_in_enabled=True, max_position_slots=5,
    ),
    "lion": SessionConfig(  # Risk level 5 — maximum aggression
        spirit="lion",
        strategy="combined",
        qty=5, stop_loss_pct=2.0, max_daily_drawdown_pct=10.0,
        bb_std_dev=1.5, capital_allocation=75000.0,
        fib_bounce_threshold_pct=0.10, fib_entry_mode="OR",
        sub_agents=["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager", "research_framework"],
        ai_interval_minutes=20, sub_agent_interval_minutes=10,
        scale_in_enabled=True, max_position_slots=5,
        leverage_factor=50.0,
    ),
}


# ── Session State ─────────────────────────────────────────────────────────

class TradingSession:
    """
    Single trading session manager.
    Owns one engine, one sub-agent pool, one AI brain.
    """

    def __init__(self):
        self._running = False
        self._status = "stopped"
        self._config: Optional[SessionConfig] = None
        self._engine = None
        self._sub_agent_pool = None
        self._ai_brain = None
        self._vital_signs = None
        self._autoresearcher = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def config(self) -> Optional[SessionConfig]:
        return self._config

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, config: SessionConfig) -> dict:
        """Start a trading session with the given config."""
        if self._running:
            return {"status": "error", "message": "Session already running"}

        self._config = config
        from bot_engine import BotEngine
        from bot_vital_signs import BotVitalSigns
        from sub_agents import SubAgentPool
        from bot_ai_brain import BotAIBrainScheduler
        from prompt_autoresearcher import PromptAutoResearcher
        from openai import OpenAI
        from config import config as sys_config
        import os

        # Build BotConfig from session config (backward compat with BotEngine)
        from bot_config import BotConfig
        bot_cfg = BotConfig(
            bot_id="session",
            account_id="",
            name=f"{config.spirit.title()} {config.symbol}",
            symbol=config.symbol,
            strategy=config.strategy,
            capital_allocation=config.capital_allocation,
            qty=config.qty,
            stop_loss_pct=config.stop_loss_pct,
            max_daily_drawdown_pct=config.max_daily_drawdown_pct,
            bb_period=config.bb_period,
            bb_std_dev=config.bb_std_dev,
            short_selling_enabled=config.short_selling_enabled,
            trailing_stop_enabled=config.trailing_stop_enabled,
            trailing_stop_pct=config.trailing_stop_pct,
            confluence_enabled=config.confluence_enabled,
            kill_zone_enabled=config.kill_zone_enabled,
            fib_enabled=config.fib_enabled,
            fib_lookback_bars=config.fib_lookback_bars,
            fib_bounce_threshold_pct=config.fib_bounce_threshold_pct,
            fib_entry_mode=config.fib_entry_mode,
            fib_active_levels_raw=config.fib_active_levels_raw,
            ai_brain_enabled=config.ai_brain_enabled,
            ai_interval_minutes=config.ai_interval_minutes,
            ai_min_trades_trigger=config.ai_min_trades_trigger,
            ai_loss_streak_trigger=config.ai_loss_streak_trigger,
            sub_agents=config.sub_agents,
            sub_agent_interval_minutes=config.sub_agent_interval_minutes,
            agent_vote_cache_ttl_seconds=config.agent_vote_cache_ttl_seconds,
            scale_in_enabled=config.scale_in_enabled,
            max_position_slots=config.max_position_slots,
            take_profit_usd=config.take_profit_usd,
            leverage_mode_enabled=config.leverage_mode_enabled,
            leverage_factor=config.leverage_factor,
            isolated_risk_usd=config.isolated_risk_usd,
            net_profit_target_usd=config.net_profit_target_usd,
            auto_size_qty=config.auto_size_qty,
            risk_pct_per_trade=config.risk_pct_per_trade,
            smart_routing_min_qty=config.smart_routing_min_qty,
            twap_interval_ms=config.twap_interval_ms,
            max_slippage_pct=config.max_slippage_pct,
            limit_timeout_s=config.limit_timeout_s,
            autoresearch_enabled=False,
            ai_generated=False,
        )

        # Init Gemini/OpenClaw client
        gemini_api_key = sys_config.openclaw_token or os.getenv("GEMINI_API_KEY", "")
        gemini_model = sys_config.openclaw_model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        ollama_base_url = sys_config.ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = sys_config.ollama_model or os.getenv("OLLAMA_MODEL_NAME", "gemma2:4b")

        openclaw_client = None
        openclaw_model = gemini_model
        if gemini_api_key:
            try:
                openclaw_client = OpenAI(
                    api_key=gemini_api_key,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    timeout=30.0,
                )
                logger.info(f"Session: Gemini client initialized (model={gemini_model})")
            except Exception as e:
                logger.warning(f"Session: Gemini client init failed: {e}")

        # Ensure MT5 hub is connected
        if not mt5_hub.is_initialized:
            try:
                import store
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    creds_json = asyncio.run_coroutine_threadsafe(
                        store.get_store().get_setting("mt5_credentials"), loop
                    ).result(timeout=5)
                    import json
                    if creds_json:
                        c = json.loads(creds_json)
                        mt5_hub.init(
                            login=int(c.get("login", 0)),
                            password=c.get("password", ""),
                            server=c.get("server", ""),
                        )
            except Exception as e:
                logger.warning(f"Session: MT5 hub init from saved creds failed: {e}")
                return {"status": "error", "message": f"MT5 not connected: {e}"}

        if not mt5_hub.is_initialized:
            return {"status": "error", "message": "MT5 hub not initialized. Connect first."}

        # Vital Signs
        from bot_vital_signs import BotVitalSigns
        self._vital_signs = BotVitalSigns(bot_id="session")

        # Engine
        from bot_engine import BotEngine
        self._engine = BotEngine(bot_id="session", config=bot_cfg, vital_signs=self._vital_signs)

        # Sub-agent pool
        self._sub_agent_pool = None
        if config.sub_agents:
            self._sub_agent_pool = SubAgentPool(
                bot_id="session",
                symbol=config.symbol,
                enabled_agents=config.sub_agents,
                openclaw_client=openclaw_client,
                openclaw_model=openclaw_model,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                interval_minutes=config.sub_agent_interval_minutes,
            )
            self._sub_agent_pool.start()
            self._engine.wire_sub_agent_pool(self._sub_agent_pool)

        # AI Brain
        from bot_ai_brain import BotAIBrainScheduler
        self._ai_brain = BotAIBrainScheduler(
            bot_id="session",
            bot_config=bot_cfg,
            engine=self._engine,
            vital_signs=self._vital_signs,
            sub_agent_pool=self._sub_agent_pool,
            openclaw_client=openclaw_client,
            openclaw_model=openclaw_model,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            store=None,
            main_loop=None,
        )
        if config.ai_brain_enabled:
            try:
                self._ai_brain.start()
            except Exception as e:
                logger.warning(f"Session: AI brain start failed: {e}")

        # Prompt Autoresearcher (optional)
        from prompt_autoresearcher import PromptAutoResearcher
        self._autoresearcher = PromptAutoResearcher(
            bot_id="session",
            openclaw_client=openclaw_client,
            openclaw_model=openclaw_model,
        )

        # Start the engine
        try:
            self._engine.start()
        except Exception as e:
            logger.error(f"Session: engine start failed: {e}")
            return {"status": "error", "message": f"Engine start failed: {e}"}

        self._running = True
        self._status = "running"
        logger.info(f"Session started: {config.spirit} on {config.symbol}")
        return {"status": "started", "symbol": config.symbol, "spirit": config.spirit}

    def stop(self):
        """Stop the trading session."""
        if self._ai_brain:
            try:
                self._ai_brain.stop()
            except Exception:
                pass
        if self._sub_agent_pool:
            try:
                self._sub_agent_pool.stop()
            except Exception:
                pass
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._running = False
        self._status = "stopped"
        logger.info("Session stopped")

    def update_config(self, params: dict) -> dict:
        """Update live trading parameters."""
        if not self._config:
            return {"status": "error", "message": "No active session"}
        allowed = {
            "qty", "stop_loss_pct", "bb_period", "bb_std_dev",
            "max_daily_drawdown_pct", "fib_enabled", "ai_brain_enabled",
            "ai_interval_minutes", "capital_allocation", "kill_zone_enabled",
            "short_selling_enabled", "leverage_mode_enabled", "leverage_factor",
            "isolated_risk_usd", "net_profit_target_usd", "take_profit_usd",
        }
        applied = {}
        for key, value in params.items():
            if key in allowed and hasattr(self._config, key):
                setattr(self._config, key, value)
                applied[key] = value
        if applied and self._engine:
            for key, value in applied.items():
                if hasattr(self._engine.config, key):
                    setattr(self._engine.config, key, value)
        return {"status": "updated", "applied": applied}

    def get_status(self) -> dict:
        """Return current session state snapshot."""
        engine_state = {}
        if self._engine:
            try:
                engine_state = self._engine.get_state_snapshot()
            except Exception:
                pass

        ai_status = {}
        if self._ai_brain:
            try:
                ai_status = self._ai_brain.get_status()
            except Exception:
                pass

        agent_sentiment = {}
        if self._sub_agent_pool:
            try:
                agent_sentiment = self._sub_agent_pool.get_aggregate_sentiment()
            except Exception:
                pass

        vitals = {}
        if self._vital_signs:
            try:
                vitals = self._vital_signs.get_status()
            except Exception:
                pass

        return {
            "status": self._status,
            "running": self._running,
            "config": self._config.to_dict() if self._config else None,
            "engine": engine_state,
            "ai": ai_status,
            "agent_sentiment": agent_sentiment,
            "vitals": vitals,
            "hub_connected": mt5_hub.is_initialized,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_history(self, limit: int = 200) -> dict:
        trades = []
        equity = []
        if self._engine:
            trades = self._engine.get_recent_trades(limit=limit)
            equity = self._engine.get_equity_history(limit=500)
        return {
            "trades": trades,
            "equity_curve": equity,
            "total_trades": len(trades),
            "total_realized_pnl": self._engine.total_realized_pnl if self._engine else 0.0,
        }


# Module-level singleton
session = TradingSession()
