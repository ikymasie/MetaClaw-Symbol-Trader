"""
TradeClaw — Fleet Orchestrator
================================
Manages the lifecycle of all deployed trading bots.
Each bot runs fully isolated: its own engine, AI brain, sub-agents, and vital signs.

The FleetOrchestrator:
  - Spawns and terminates bot instances
  - Enforces fleet-wide risk limits (global drawdown kill switch)
  - Pushes live telemetry and snapshots to PostgreSQL (Neon)
  - Reads/writes FleetConfig from PostgreSQL
"""

import asyncio
import logging
import os
import threading
import time
import psutil
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bot_config import BotConfig, FleetConfig, DEFAULT_FLEET_CONFIG
from mt5_hub import mt5_hub

logger = logging.getLogger("tradeclaw.fleet")

# Configure buffered file logging
from buffered_logger import BufferedFileHandler
os.makedirs("logs", exist_ok=True)
fh = BufferedFileHandler("logs/fleet.txt", interval=10.0)
fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logging.getLogger("tradeclaw").addHandler(fh)


# ─────────────────────────────────────────────
# BOT INSTANCE
# ─────────────────────────────────────────────

@dataclass
class BotInstance:
    """
    A fully isolated, self-contained bot.
    Each bot owns:
      - BotEngine  (strategy execution thread)
      - AIBrainScheduler  (strategy evolution thread)
      - SubAgentPool  (market intelligence threads)
      - VitalSigns  (health/survival tracking)
    """
    bot_id: str
    config: BotConfig
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Set after instantiation
    engine: object = field(default=None, repr=False)
    ai_brain: object = field(default=None, repr=False)
    sub_agent_pool: object = field(default=None, repr=False)
    vital_signs: object = field(default=None, repr=False)
    autoresearcher: object = field(default=None, repr=False)
    market_trends: dict = field(default_factory=dict) # Local trend cache for agents

    # Phase 4 §7.3 — Per-bot event loop for failure-domain isolation.
    # Each bot runs its own asyncio event loop in a dedicated daemon thread.
    # Async operations (PostgreSQL writes, Darwinian persistence, research
    # bridge) are scheduled on this loop instead of contending on the
    # shared fleet `_main_loop`, so that one bot's 429/Neon-throttle does
    # not delay coroutines of other bots.
    _bot_loop: object = field(default=None, repr=False)
    _bot_loop_thread: object = field(default=None, repr=False)

    def start_bot_loop(self):
        """Create and start a dedicated asyncio event loop for this bot."""
        import asyncio
        import threading
        if self._bot_loop is not None and self._bot_loop.is_running():
            return
        self._bot_loop = asyncio.new_event_loop()
        self._bot_loop_thread = threading.Thread(
            target=self._bot_loop.run_forever,
            daemon=True,
            name=f"bot-loop-{self.bot_id}",
        )
        self._bot_loop_thread.start()
        logger.debug(f"[{self.bot_id}] Dedicated event loop started")

    def stop_bot_loop(self):
        """Gracefully stop the bot's dedicated event loop."""
        if self._bot_loop is None:
            return
        try:
            self._bot_loop.call_soon_threadsafe(self._bot_loop.stop)
        except Exception:
            pass
        self._bot_loop = None
        self._bot_loop_thread = None

    def run_async(self, coro, timeout: float = 10.0):
        """
        Schedule a coroutine on this bot's event loop and return the result.

        Falls back to the fleet-level `_main_loop` if the bot's dedicated
        loop is not running.
        """
        import asyncio
        if self._bot_loop is None or not self._bot_loop.is_running():
            # Try fleet's main loop
            try:
                # Access fleet singleton's main loop
                loop = fleet._main_loop
                if loop and loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(coro, loop)
                    return fut.result(timeout=timeout)
            except Exception:
                pass
            raise RuntimeError(f"No event loop available for bot {self.bot_id}")
        fut = asyncio.run_coroutine_threadsafe(coro, self._bot_loop)
        return fut.result(timeout=timeout)

    def run_async_fire_and_forget(self, coro) -> None:
        """Schedule a coroutine on this bot's event loop without waiting for result."""
        import asyncio
        loop = self._bot_loop
        if loop is None or not loop.is_running():
            try:
                loop = fleet._main_loop
            except Exception:
                return
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)

    def get_snapshot(self) -> dict:
        """Return a serialisable snapshot of this bot's current state."""
        status = {}
        if self.engine:
            try:
                status = self.engine.get_state_snapshot()
            except Exception:
                pass

        vitals = {}
        if self.vital_signs:
            try:
                vitals = self.vital_signs.get_status()
            except Exception:
                pass

        ai_status = {}
        if self.ai_brain:
            try:
                ai_status = self.ai_brain.get_status()
            except Exception:
                pass

        agent_sentiment = {}
        if self.sub_agent_pool:
            try:
                agent_sentiment = self.sub_agent_pool.get_aggregate_sentiment()
            except Exception:
                pass

        return {
            "bot_id": self.bot_id,
            "account_id": self.config.account_id,
            "name": self.config.name,
            "description": self.config.description,
            "personality": self.config.personality,
            "animal": self.config.animal,
            "category": self.config.category,
            "symbol": self.config.symbol,
            "strategy": self.config.strategy,
            "capital_allocation": self.config.capital_allocation,
            "tags": self.config.tags,
            "enabled_agents": self.config.sub_agents or [],
            "kill_zone_enabled": self.config.kill_zone_enabled,
            "leverage_mode_enabled": self.config.leverage_mode_enabled,
            "leverage_factor": self.config.leverage_factor,
            "isolated_risk_usd": self.config.isolated_risk_usd,
            "net_profit_target_usd": self.config.net_profit_target_usd,
            "take_profit_usd": self.config.take_profit_usd,
            "created_at": self.created_at,
            "status": status,
            "vitals": vitals,
            "ai": ai_status,
            "agent_sentiment": agent_sentiment,
            "autoresearch": {
                "active_branch": getattr(self.autoresearcher, "_active_branch", None) if self.autoresearcher else None,
                "agent": getattr(self.autoresearcher, "_branch_agent", None) if self.autoresearcher else None,
            }
        }


# ─────────────────────────────────────────────
# FLEET ORCHESTRATOR
# ─────────────────────────────────────────────

class FleetOrchestrator:
    """
    The nerve centre. Spawn, monitor, and kill bots.
    Enforces global risk limits and pushes telemetry.
    """

    def __init__(self):
        self._bots: dict[str, BotInstance] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

        # Fleet config — loaded from PostgreSQL on startup
        self._fleet_config: FleetConfig = deepcopy(DEFAULT_FLEET_CONFIG)
        self._config_lock = threading.Lock()

        # Atomic fleet-halt flag — checked by bot engines before trading
        self._halted = threading.Event()

        # Firebase store reference (set after Firebase init)
        self._store = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_darwinian_update = 0.0
        self._last_autoresearch_check = 0.0
        self._last_research_bridge_check = 0.0
        self._last_symbol_research_times: dict[str, float] = {}
        self._last_market_aggregation = 0.0
        self._last_telemetry_push = 0.0  # Throttle snapshot updates
        self._last_telemetry_prune = 0.0 # Hourly maintenance
        self._last_system_metrics_push = 0.0

        # Market Data Aggregation
        from market_data_aggregator import MarketDataAggregator
        self._aggregator = MarketDataAggregator()
        self._symbol_bar_cache: dict[str, list[dict]] = {}
        self._cache_lock = threading.Lock()

        logger.info("FleetOrchestrator initialized")

    # ── Firebase ─────────────────────────────────────────────────────────

    def set_store(self, store_module):
        """Inject the persistence store module and capture current event loop."""
        self._store = store_module
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback if called outside an async context
            try:
                self._main_loop = asyncio.get_event_loop()
            except Exception:
                self._main_loop = None
        logger.info(f"Persistence store injected (main_loop captured: {self._main_loop is not None})")

    async def load_config_from_store(self):
        """Load FleetConfig from persistence. Falls back to default if not found."""
        if not self._store:
            return
        try:
            data = await self._store.load_fleet_config()
            if data:
                config = FleetConfig.from_dict(data)
                with self._config_lock:
                    self._fleet_config = config
                logger.info(f"FleetConfig loaded from PostgreSQL: {config}")
        except Exception as e:
            logger.warning(f"Could not load FleetConfig from PostgreSQL: {e}")

    async def restore_bots_from_store(self):
        """
        On startup: read all saved bot configs from persistence and redeploy them.
        Bots are restored in STOPPED state — they must be manually started or
        auto-started based on their saved config.
        """
        if not self._store:
            logger.info("Persistence not available — skipping bot restoration")
            return
        try:
            bot_ids = await self._store.list_bot_ids()

            if not bot_ids:
                logger.info("No bots found in PostgreSQL to restore")
                return

            logger.info(f"Restoring {len(bot_ids)} bot(s) from PostgreSQL: {bot_ids}")
            restored = 0
            for bot_id in bot_ids:
                try:
                    config_dict = await self._store.load_bot_config(bot_id)
                    if not config_dict:
                        logger.warning(f"[{bot_id}] No config found in PostgreSQL — skipping")
                        continue

                    # Strip metadata fields added by save_bot_config
                    config_dict.pop("saved_at", None)
                    config_dict.pop("updated_at", None)

                    config = BotConfig.from_dict(config_dict)

                    # Skip if already in memory (e.g. duplicate startup call)
                    with self._lock:
                        if config.bot_id in self._bots:
                            logger.info(f"[{bot_id}] Already in memory — skipping restoration")
                            continue

                    # Backfill the parent marker if it was missing (migration)
                    try:
                        await self._store.save_bot_config(
                            config.bot_id, config.to_dict()
                        )
                    except Exception:
                        pass  # Non-fatal — config already exists in subcollection

                    instance = self._build_bot_instance(config)

                    # Restore volatile telemetry state (equity, pnl) if available
                    try:
                        telemetry = await self._store.get_live_telemetry(bot_id)
                        if telemetry:
                            instance.engine.restore_from_telemetry(telemetry)
                            logger.info(f"[{bot_id}] Restored equity state: eq={instance.engine.equity:.2f}, pnl={instance.engine.daily_pnl:.2f}")
                    except Exception as e:
                        logger.warning(f"[{bot_id}] Failed to restore telemetry state: {e}")

                    with self._lock:
                        self._bots[config.bot_id] = instance

                    # Auto-start if configured
                    if config.auto_start:
                        logger.info(f"[{bot_id}] Auto-starting engine per config")
                        instance.engine.start()

                    restored += 1
                    logger.info(
                        f"[{bot_id}] Restored: {config.symbol} | {config.strategy}"
                    )
                except Exception as e:
                    logger.error(f"[{bot_id}] Failed to restore from PostgreSQL: {e}", exc_info=True)

            logger.info(f"Bot restoration complete: {restored}/{len(bot_ids)} restored")
        except Exception as e:
            logger.error(f"Bot restoration failed: {e}", exc_info=True)

    # ── Fleet Config ─────────────────────────────────────────────────────

    def get_fleet_config(self) -> dict:
        with self._config_lock:
            return self._fleet_config.to_dict()

    def update_fleet_config(self, updates: dict) -> dict:
        """
        Apply validated updates to FleetConfig. Saves to PostgreSQL.
        Called by the portal Fleet Settings panel via POST /fleet/config.
        """
        with self._config_lock:
            current = self._fleet_config.to_dict()
            current.update(updates)
            try:
                new_config = FleetConfig.from_dict(current)
                new_config.validate()
            except ValueError as e:
                raise ValueError(f"Invalid fleet config: {e}")
            self._fleet_config = new_config
            result = new_config.to_dict()

        # Persist to PostgreSQL (fire and forget)
        if self._store:
            asyncio.get_event_loop().create_task(
                self._store.save_fleet_config(result)
            )
        logger.info(f"FleetConfig updated: {updates}")
        return result

    # ── Bot Lifecycle ─────────────────────────────────────────────────────

    def deploy_bot(self, config: BotConfig) -> BotInstance:
        """
        Spawn a new isolated bot instance.
        Raises ValueError if max_bots cap is reached.
        Triggers lazy MT5 initialization if the terminal wasn't connected at startup.
        """
        with self._config_lock:
            max_bots = self._fleet_config.max_bots
            sub_agents_enabled = self._fleet_config.sub_agents_enabled

        with self._lock:
            if config.bot_id in self._bots:
                raise ValueError(f"Bot {config.bot_id} is already deployed")
            if len(self._bots) >= max_bots:
                raise ValueError(
                    f"Max bots cap reached ({max_bots}). "
                    f"Increase max_bots in Fleet Settings to deploy more."
                )

        # ── Lazy MT5 initialization ──────────────────────────────────────
        # If the terminal wasn't available at app startup, init it now
        # using the bot's assigned account or the default account.
        if not mt5_hub._initialized:
            from config_manager import config_manager
            import os

            acct = None
            if config.account_id:
                acct = config_manager.get_account(config.account_id)

            if not acct:
                acct = config_manager.get_default_account()

            if acct:
                logger.info(
                    f"[deploy_bot] Lazy-initializing MT5 hub with account "
                    f"'{acct.get('label', acct.get('id', '?'))}'"
                )
                mt5_hub.init(
                    login=acct.get("mt5_login", 0),
                    password=acct.get("mt5_password", ""),
                    server=acct.get("mt5_server", ""),
                )
            else:
                logger.info("[deploy_bot] Lazy-initializing MT5 hub from env vars")
                mt5_hub.init(
                    login=int(os.getenv("MT5_LOGIN", "0") or "0"),
                    password=os.getenv("MT5_PASSWORD", ""),
                    server=os.getenv("MT5_SERVER", ""),
                )

            mt5_hub.start()

        # Apply fleet-level overrides
        effective_config = deepcopy(config)
        if not sub_agents_enabled:
            effective_config.sub_agents = []

        # Build the bot instance
        instance = self._build_bot_instance(effective_config)

        with self._lock:
            self._bots[config.bot_id] = instance

        # Persist config to PostgreSQL
        if self._store:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._store.save_bot_config(
                            config.bot_id, effective_config.to_dict()
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not persist bot config to PostgreSQL: {e}")

        # Auto-start if configured
        if config.auto_start:
            logger.info(f"[{config.bot_id}] Auto-starting engine per deployment request")
            instance.engine.start()

        return instance

    def kill_bot(self, bot_id: str):
        """Stop, deregister, and delete a bot from PostgreSQL."""
        with self._lock:
            instance = self._bots.get(bot_id)
            if not instance:
                raise ValueError(f"Bot {bot_id} not found")

        # Stop all components
        if instance.engine:
            try:
                instance.engine.stop()
            except Exception as e:
                logger.warning(f"[{bot_id}] Engine stop error: {e}")

        if instance.ai_brain:
            try:
                instance.ai_brain.stop()
            except Exception as e:
                logger.warning(f"[{bot_id}] AI brain stop error: {e}")

        if instance.sub_agent_pool:
            try:
                instance.sub_agent_pool.stop()
            except Exception as e:
                logger.warning(f"[{bot_id}] Sub-agent pool stop error: {e}")

        with self._lock:
            del self._bots[bot_id]

        # Remove from PostgreSQL so it doesn't resurrect on next restart
        if self._store:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._store.delete_bot_config(bot_id)
                    )
            except Exception as e:
                logger.warning(f"[{bot_id}] Could not delete bot config from PostgreSQL: {e}")

        logger.info(f"Bot killed and removed from PostgreSQL: {bot_id}")

    def get_bot(self, bot_id: str) -> Optional[BotInstance]:
        with self._lock:
            return self._bots.get(bot_id)

    def list_bots(self) -> list[BotInstance]:
        with self._lock:
            return list(self._bots.values())

    def bot_count(self) -> int:
        with self._lock:
            return len(self._bots)

    # ── Fleet Status ─────────────────────────────────────────────────────

    def get_fleet_status(self) -> dict:
        """Full snapshot of all bots + fleet summary."""
        bots_data = []
        total_daily_pnl = 0.0
        total_equity = 0.0
        running_bots = 0

        with self._lock:
            instances = list(self._bots.values())

        for instance in instances:
            snap = instance.get_snapshot()
            bots_data.append(snap)
            status = snap.get("status", {})
            total_daily_pnl += status.get("daily_pnl", 0.0)
            total_equity += status.get("equity", 0.0)
            if status.get("bot_status") == "RUNNING":
                running_bots += 1

        with self._config_lock:
            fleet_cfg = self._fleet_config.to_dict()

        return {
            "fleet_config": fleet_cfg,
            "summary": {
                "total_bots": len(bots_data),
                "running_bots": running_bots,
                "max_bots": fleet_cfg["max_bots"],
                "total_daily_pnl": round(total_daily_pnl, 2),
                "total_equity": round(total_equity, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "bots": bots_data,
        }

    def get_fleet_daily_pnl(self) -> float:
        """Sum of all bots' daily P&L."""
        total = 0.0
        with self._lock:
            for instance in self._bots.values():
                if instance.engine:
                    try:
                        state = instance.engine.get_state_snapshot()
                        total += state.get("daily_pnl", 0.0)
                    except Exception:
                        pass
        return round(total, 2)

    # ── Global Risk ────────────────────────────────────────────────────

    @property
    def is_halted(self) -> bool:
        """Thread-safe check: True if fleet is in emergency halt state."""
        return self._halted.is_set()

    def clear_halt(self):
        """Clear the fleet-wide halt flag (after operator review)."""
        self._halted.clear()
        logger.info("Fleet halt flag cleared by operator")

    def enforce_global_risk_limits(self):
        """
        Check fleet-wide drawdown. If any bot's starting equity is known and
        the fleet total drawdown exceeds max_fleet_drawdown_pct, halt all bots.

        Uses an atomic _halted flag so that no bot can open a new position
        between the check and the halt command (fixes TOCTOU race).
        """
        # If already halted, don't re-check — wait for operator reset
        if self._halted.is_set():
            return

        with self._config_lock:
            max_drawdown = self._fleet_config.max_fleet_drawdown_pct

        total_starting = 0.0
        total_current = 0.0

        with self._lock:
            instances = list(self._bots.values())

        for instance in instances:
            if not instance.engine:
                continue
            try:
                state = instance.engine.get_state_snapshot()
                start_eq = state.get("starting_equity", 0.0) or 0.0
                current_eq = state.get("equity", 0.0) or 0.0
                if start_eq > 0:
                    total_starting += start_eq
                    total_current += current_eq
            except Exception as e:
                logger.warning(f"[{instance.bot_id}] Failed to read equity for risk check: {e}")

        if total_starting > 0:
            fleet_drawdown_pct = (
                (total_starting - total_current) / total_starting * 100
            )
            if fleet_drawdown_pct >= max_drawdown:
                # SET THE HALT FLAG FIRST — this prevents any bot from opening
                # new positions even before we finish iterating the halt loop
                self._halted.set()
                logger.critical(
                    f"🚨 FLEET DRAWDOWN LIMIT HIT: {fleet_drawdown_pct:.1f}% >= {max_drawdown}%. "
                    f"Halting all bots."
                )
                self._halt_all_bots(
                    reason=f"Fleet drawdown {fleet_drawdown_pct:.1f}% exceeded limit"
                )

    def _halt_all_bots(self, reason: str):
        """Emergency halt — stop all bot engines."""
        with self._lock:
            instances = list(self._bots.values())
        for instance in instances:
            if instance.engine:
                try:
                    instance.engine.emergency_stop(reason)
                except Exception as e:
                    logger.error(f"[{instance.bot_id}] Emergency stop failed: {e}")

    # ── Monitor Loop ──────────────────────────────────────────────────

    def start_monitor(self):
        """Start the fleet monitor background loop (5 second interval)."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="fleet-monitor",
        )
        self._monitor_thread.start()
        logger.info("Fleet monitor started")

    def stop_monitor(self):
        """Stop the fleet monitor loop and gracefully shut down all bot loops."""
        self._stop_event.set()
        with self._lock:
            bots = list(self._bots.values())
        for bot in bots:
            try:
                bot.stop_bot_loop()
            except Exception as e:
                logger.warning(f"[{bot.bot_id}] Error stopping bot loop: {e}")
        logger.info("Fleet monitor stopped")

    def _monitor_loop(self):
        """Background loop: risk checks + telemetry push + bar/trade flush every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                self.enforce_global_risk_limits()
                # Telemetry push throttled to every 30s (was every 5s)
                now = time.time()
                if now - self._last_telemetry_push >= 30:
                    self._push_telemetry()
                    self._last_telemetry_push = now
                self._flush_bar_queues()
                self._flush_db_queues()
                self._check_darwinian_evolution()
                self._check_autoresearch_evolution()
                self._check_research_bridge_cycle()
                self._run_market_aggregation()
                
                # Maintenance: Prune old telemetry every hour
                if now - self._last_telemetry_prune >= 3600:
                    asyncio.run_coroutine_threadsafe(self._store.prune_old_telemetry(48), self._main_loop)
                    self._last_telemetry_prune = now

                # System metrics push every 60s
                if now - self._last_system_metrics_push >= 60:
                    self._push_system_metrics()
                    self._last_system_metrics_push = now
            except Exception as e:
                logger.error(f"Fleet monitor error: {e}", exc_info=True)
            self._stop_event.wait(5)

    def _check_darwinian_evolution(self):
        """Once every 24 hours, trigger Darwinian weight updates for all bots."""
        now = time.time()
        # 86400 seconds = 24 hours
        if now - self._last_darwinian_update < 86400:
            return

        logger.info("[Fleet] Triggering daily Darwinian weight update for all bots")
        with self._lock:
            bot_instances = list(self._bots.values())

        for bot in bot_instances:
            if bot.sub_agent_pool and hasattr(bot.sub_agent_pool, "_darwin"):
                try:
                    bot.sub_agent_pool._darwin.daily_update()
                except Exception as e:
                    logger.error(f"Failed to update Darwinian weights for bot {bot.bot_id}: {e}")

        self._last_darwinian_update = now

    def _check_autoresearch_evolution(self):
        """Periodically trigger the prompt autoresearch cycle for enabled bots."""
        now = time.time()
        # Check every 4 hours (run_cycle handles internal weekly/5-day logic)
        if now - self._last_autoresearch_check < 14400:
            return

        logger.info("[Fleet] Checking prompt autoresearch cycles")
        with self._lock:
            bot_instances = list(self._bots.values())

        for bot in bot_instances:
            if bot.config.autoresearch_enabled and bot.autoresearcher:
                try:
                    bot.autoresearcher.run_cycle()
                except Exception as e:
                    logger.error(f"Autoresearch cycle failed for bot {bot.bot_id}: {e}")

        self._last_autoresearch_check = now

    def _check_research_bridge_cycle(self):
        """Periodically run the TradingAgentsGraph research framework and update bot sub_agent_pools."""
        now = time.time()
        
        if not self._main_loop:
            return

        with self._lock:
            bot_instances = list(self._bots.values())

        # Track which symbols we've already triggered in this pass to avoid duplicates
        triggered_symbols = set()

        for bot in bot_instances:
            symbol = bot.config.symbol
            if symbol in triggered_symbols:
                continue

            # Check if research framework is enabled for this bot
            is_enabled = bot.config.research_enabled and "research_framework" in (bot.config.sub_agents or [])
            if not is_enabled:
                continue

            # Check interval
            last_run = self._last_symbol_research_times.get(symbol, 0.0)
            interval_seconds = bot.config.research_interval_hours * 3600
            
            if now - last_run >= interval_seconds:
                logger.info(
                    f"[Fleet] Triggering research cycle for {symbol} "
                    f"(interval: {bot.config.research_interval_hours}h)",
                    extra={
                        "event": "research_cycle_triggered",
                        "symbol": symbol,
                        "interval_hours": bot.config.research_interval_hours,
                        "last_run_ago_seconds": round(now - last_run, 1),
                    },
                )
                asyncio.run_coroutine_threadsafe(
                    self._run_research_graph_async(bot),
                    self._main_loop
                )
                self._last_symbol_research_times[symbol] = now
                triggered_symbols.add(symbol)

    async def _run_research_graph_async(self, bot: BotInstance):
        """Run the heavy TradingAgentsGraph.propagate in a background thread and push the signal."""
        try:
            from research_bridge import research_bridge
            
            logger.info(f"[{bot.bot_id}] Triggering research cycle via ResearchBridge for {bot.config.symbol}...")
            signal = await research_bridge.run_research(bot.config.symbol)
            
            # Push signal to the bot's SubAgentPool
            if bot.sub_agent_pool:
                bot.sub_agent_pool.push_signal(signal)
                logger.info(
                    f"[{bot.bot_id}] Research cycle complete: "
                    f"sentiment={signal.sentiment} conf={signal.confidence}",
                    extra={
                        "event": "research_cycle_complete",
                        "bot_id": bot.bot_id,
                        "symbol": bot.config.symbol,
                        "sentiment": round(signal.sentiment, 3),
                        "confidence": round(signal.confidence, 3),
                    },
                )
                
        except Exception as e:
            logger.error(f"[{bot.bot_id}] ResearchBridge cycle failed: {e}", exc_info=True)

    def _flush_db_queues(self):
        """
        Drain each bot's _db_queue (trade + equity records) and write to PostgreSQL.
        The db_flush_loop in main.py only handles the legacy singleton engine;
        fleet bots queue their records here and need this to reach PostgreSQL.
        """
        if not self._store:
            return
        loop = self._main_loop
        if not loop or not loop.is_running():
            return

        with self._lock:
            instances = list(self._bots.values())

        for instance in instances:
            if not instance.engine:
                continue
            items = instance.engine.flush_db_queue()
            if not items:
                continue
            bot_id = instance.bot_id
            for item in items:
                try:
                    if item.get("type") == "trade":
                        future = asyncio.run_coroutine_threadsafe(
                            self._store.save_trade(bot_id, {
                                k: v for k, v in item.items() if k != "type"
                            }),
                            loop,
                        )
                        future.result(timeout=5)
                    elif item.get("type") == "equity":
                        future = asyncio.run_coroutine_threadsafe(
                            self._store.save_equity_snapshot(bot_id, {
                                k: v for k, v in item.items() if k != "type"
                            }),
                            loop,
                        )
                        future.result(timeout=5)
                except Exception as e:
                    logger.warning(f"[{bot_id}] DB queue flush error: {e}")

    def _flush_bar_queues(self):
        """
        Drain each bot's bar queue and batch-write to PostgreSQL.
        Bars are grouped by symbol so multiple bots trading the same
        asset don't create duplicate writes.

        Safety cap: each symbol batch is capped at 500 bars per flush cycle.
        If PostgreSQL falls behind and bars accumulate, only the most-recent
        500 are written; the rest are discarded (data loss acceptable —
        the running deque in BotEngine already bounds total memory).
        """
        if not self._store:
            return
        loop = self._main_loop
        if not loop or not loop.is_running():
            return

        MAX_BARS_PER_FLUSH = 500

        # Collect bars from all running bots, grouped by symbol
        symbol_bars: dict[str, list[dict]] = {}
        with self._lock:
            instances = list(self._bots.values())

        for instance in instances:
            if not instance.engine:
                continue
            bars = instance.engine.flush_bar_queue()
            if not bars:
                continue
            symbol = instance.engine.config.symbol
            symbol_bars.setdefault(symbol, []).extend(bars)

        # Write each symbol's bars in a single batch (capped at MAX_BARS_PER_FLUSH)
        for symbol, bars in symbol_bars.items():
            if not bars:
                continue
            # If more bars than cap, keep only the most recent ones
            if len(bars) > MAX_BARS_PER_FLUSH:
                logger.warning(
                    f"[Fleet] Bar flush capped for {symbol}: "
                    f"{len(bars)} bars collected, writing newest {MAX_BARS_PER_FLUSH}"
                )
                bars = bars[-MAX_BARS_PER_FLUSH:]
            try:
                if not self._store:
                    continue
                logger.debug(f"[Fleet] Flushing {len(bars)} bar(s) for {symbol} to Persistence")
                future = asyncio.run_coroutine_threadsafe(
                    self._store.append_bars_batch(symbol, bars), loop
                )
                # Non-blocking: check with short timeout to avoid 60s hangs on 429
                try:
                    written = future.result(timeout=5)
                except Exception:
                    written = 0
                if written:
                    logger.debug(f"Bar flush: {written} bars persisted for {symbol}")
                    # Update local cache for aggregation
                    with self._cache_lock:
                        cache = self._symbol_bar_cache.setdefault(symbol, [])
                        cache.extend(bars)
                        # Keep only last 2000 bars
                        if len(cache) > 2000:
                            self._symbol_bar_cache[symbol] = cache[-2000:]
            except Exception as e:
                logger.warning(f"Bar flush error ({symbol}): {e}")

    def _run_market_aggregation(self):
        """
        Periodically (every 1m) aggregate 1m bars into higher timeframes
        and generate trend summaries.
        """
        now = time.time()
        # Run every 180 seconds (was 60s — reduces database writes 3x)
        if now - self._last_market_aggregation < 180:
            return
        
        if not self._store:
            return
            
        logger.info("[Fleet] Running market data aggregation and trend analysis")
        
        # Identify unique symbols from active bots
        active_symbols = set()
        with self._lock:
            for bot in self._bots.values():
                if bot.engine: # Only symbols for bots that are running/initialized
                    active_symbols.add(bot.config.symbol)
        
        loop = self._main_loop
        if not loop or not loop.is_running():
            return

        for symbol in active_symbols:
            try:
                # 1. Ensure cache is populated
                with self._cache_lock:
                    if symbol not in self._symbol_bar_cache or len(self._symbol_bar_cache[symbol]) < 100:
                        logger.info(f"[Fleet] Initializing bar cache for {symbol} from PostgreSQL")
                        future = asyncio.run_coroutine_threadsafe(
                            self._store.load_bars(symbol, timeframe="1m", limit=2000), loop
                        )
                        bars = future.result(timeout=15)
                        self._symbol_bar_cache[symbol] = bars

                    bars_1m = list(self._symbol_bar_cache[symbol])

                if not bars_1m:
                    continue

                # 2. Process aggregation and trends
                analysis = self._aggregator.process_symbol(symbol, bars_1m)
                
                # 3. Persist results to PostgreSQL (fire-and-forget — no blocking .result())
                # Aggregated Bars (only save the latest bar for each timeframe to keep it light)
                for tf, bars in analysis.get("aggregated_bars", {}).items():
                    if not bars:
                        continue
                    # Only append the most recent bar (usually the one being formed or just closed)
                    latest_bars = bars[-2:]
                    asyncio.run_coroutine_threadsafe(
                        self._store.append_bars_batch(symbol, latest_bars, timeframe=tf), loop
                    )
                    # Note: no .result() — truly fire-and-forget. The 429 throttle in
                    # persistence_store.py handles backoff if quota is exhausted.

                # Trend Summaries (fire-and-forget)
                trend_summaries = analysis.get("trend_summaries", {})
                for tf, summary in trend_summaries.items():
                    asyncio.run_coroutine_threadsafe(
                        self._store.save_trend_summary(symbol, tf, summary), loop
                    )
                
                # Phase 3 §9.1 — Raw DataFrames for in-process consumers.
                # Stripped before any DB write / WS payload (not serialisable).
                _dataframes = analysis.get("dataframes", {}) or {}

                # 4. Push to local bot instances for zero-latency deliberation
                with self._lock:
                    for bot in self._bots.values():
                        if bot.config.symbol == symbol:
                            bot.market_trends = trend_summaries
                            # Thread-safe push into SubAgentPool so agents
                            # receive trends in both background runs & deliberate()
                            if bot.sub_agent_pool:
                                bot.sub_agent_pool.update_market_trends(trend_summaries)
                                # Phase 3 §9.1 — Hand raw frames to the pool
                                # for agents like CorrelationAgent that need
                                # direct pandas access without re-allocation.
                                if _dataframes:
                                    bot.sub_agent_pool.update_market_data_frames(_dataframes)

            except Exception as e:
                logger.error(f"Market aggregation failed for {symbol}: {e}")

        self._last_market_aggregation = now


    def _push_telemetry(self):
        """Push live fleet state to PostgreSQL (live_telemetry collection)."""
        if not self._store:
            return
        try:
            # Use captured main loop for thread-safe async calls
            loop = self._main_loop
            if not loop or not loop.is_running():
                return

            fleet_snap = self.get_fleet_status()["summary"]
            future = asyncio.run_coroutine_threadsafe(
                self._store.push_fleet_telemetry(fleet_snap), loop
            )
            # Check for errors (timeout after 5s to avoid blocking the monitor)
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"Fleet telemetry push error: {e}")

            with self._lock:
                instances = list(self._bots.values())
            for instance in instances:
                if instance.engine:
                    try:
                        state = instance.engine.get_state_snapshot()
                        
                        # 1. Update latest snapshot (Live)
                        asyncio.run_coroutine_threadsafe(
                            self._store.push_live_telemetry(instance.bot_id, state),
                            loop,
                        )
                        
                        # 2. Append to history (Buffered in PostgresStore - 10s)
                        asyncio.run_coroutine_threadsafe(
                            self._store.push_telemetry_history(instance.bot_id, state),
                            loop,
                        )
                    except Exception as e:
                        logger.warning(f"[{instance.bot_id}] Bot telemetry push error: {e}")
        except Exception as e:
            logger.warning(f"Telemetry push failed: {e}")

    def _push_system_metrics(self):
        """Collect and push CPU, RAM, and Event Loop latency."""
        if not self._store or not self._main_loop:
            return
        
        try:
            # 1. CPU & RAM (Synchronous via psutil)
            cpu_pct = psutil.cpu_percent()
            ram_pct = psutil.virtual_memory().percent
            
            # 2. Event Loop Latency (Asynchronous measurement)
            async def measure_latency():
                start = time.perf_counter()
                await asyncio.sleep(0)
                return (time.perf_counter() - start) * 1000  # ms

            # 3. Dispatch to store
            loop = self._main_loop
            
            async def collect_and_save():
                latency_ms = await measure_latency()
                await self._store.push_system_metric("cpu_usage_pct", cpu_pct)
                await self._store.push_system_metric("ram_usage_pct", ram_pct)
                await self._store.push_system_metric("event_loop_latency_ms", latency_ms)
                
                # Also push a combined fleet health metric
                with self._lock:
                    bot_count = len(self._bots)
                await self._store.push_system_metric("active_bots", float(bot_count))

            asyncio.run_coroutine_threadsafe(collect_and_save(), loop)
            
        except Exception as e:
            logger.warning(f"System metrics collection failed: {e}")

    # ── Private: Build Bot ────────────────────────────────────────────

    def _build_bot_instance(self, config: BotConfig) -> BotInstance:
        """
        Instantiate all components for a bot.
        Deferred imports prevent circular dependencies at module level.
        """
        from bot_engine import BotEngine
        from bot_ai_brain import BotAIBrainScheduler
        from bot_vital_signs import BotVitalSigns
        from sub_agents import SubAgentPool
        from prompt_autoresearcher import PromptAutoResearcher
        from openai import OpenAI
        from config import config as sys_config
        
        # Build Gemini client using config
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
                logger.info(f"[{config.bot_id}] Gemini client initialized (model={gemini_model})")
            except Exception as e:
                logger.warning(f"[{config.bot_id}] Gemini client init failed: {e}")
        else:
            logger.warning(f"[{config.bot_id}] No GEMINI_API_KEY set — AI features disabled")

        # Vital Signs
        vital_signs = BotVitalSigns(bot_id=config.bot_id)

        # Strategy Engine
        engine = BotEngine(bot_id=config.bot_id, config=config, vital_signs=vital_signs)

        # Sub-Agent Pool
        sub_agent_pool = None
        if config.sub_agents:
            sub_agent_pool = SubAgentPool(
                bot_id=config.bot_id,
                symbol=config.symbol,
                enabled_agents=config.sub_agents,
                openclaw_client=openclaw_client,
                openclaw_model=openclaw_model,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                interval_minutes=config.sub_agent_interval_minutes,
            )
            sub_agent_pool.start()
            # Wire the pool into the engine so _live_tick can call deliberate()
            engine.wire_sub_agent_pool(sub_agent_pool)

        # AI Brain
        ai_brain = BotAIBrainScheduler(
            bot_id=config.bot_id,
            bot_config=config,
            engine=engine,
            vital_signs=vital_signs,
            sub_agent_pool=sub_agent_pool,
            openclaw_client=openclaw_client,
            openclaw_model=openclaw_model,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            store=self._store,
            main_loop=self._main_loop,
        )
        if config.ai_brain_enabled:
            ai_brain.start()

        # Prompt Autoresearcher
        autoresearcher = PromptAutoResearcher(
            bot_id=config.bot_id,
            openclaw_client=openclaw_client,
            openclaw_model=openclaw_model
        )

        instance = BotInstance(
            bot_id=config.bot_id,
            config=config,
            engine=engine,
            ai_brain=ai_brain,
            sub_agent_pool=sub_agent_pool,
            vital_signs=vital_signs,
            autoresearcher=autoresearcher,
        )
        # Phase 4 §7.3 — spawn dedicated event loop for this bot
        instance.start_bot_loop()
        # Wire the bot's own loop into the sub-agent pool for DB persistence
        if sub_agent_pool and instance._bot_loop:
            sub_agent_pool.set_bot_loop(instance._bot_loop)
        return instance


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

fleet = FleetOrchestrator()
