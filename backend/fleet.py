"""
TradeClaw — Fleet Orchestrator
================================
Manages the lifecycle of all deployed trading bots.
Each bot runs fully isolated: its own engine, AI brain, sub-agents, and vital signs.

The FleetOrchestrator:
  - Spawns and terminates bot instances
  - Enforces fleet-wide risk limits (global drawdown kill switch)
  - Pushes live telemetry to Firestore
  - Persists fleet snapshots to Firestore
  - Reads/writes FleetConfig from Firestore (portal-editable max_bots, etc.)
"""

import asyncio
import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bot_config import BotConfig, FleetConfig, DEFAULT_FLEET_CONFIG

logger = logging.getLogger("tradeclaw.fleet")


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
            "name": self.config.name,
            "description": self.config.description,
            "personality": self.config.personality,
            "animal": self.config.animal,
            "category": self.config.category,
            "symbol": self.config.symbol,
            "strategy": self.config.strategy,
            "capital_allocation": self.config.capital_allocation,
            "demo_mode": self.config.demo_mode,
            "tags": self.config.tags,
            "enabled_agents": self.config.sub_agents or [],
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

        # Fleet config — loaded from Firestore on startup
        self._fleet_config: FleetConfig = deepcopy(DEFAULT_FLEET_CONFIG)
        self._config_lock = threading.Lock()

        # Atomic fleet-halt flag — checked by bot engines before trading
        self._halted = threading.Event()

        # Firebase store reference (set after Firebase init)
        self._firebase_store = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_darwinian_update = 0.0
        self._last_autoresearch_check = 0.0

        logger.info("FleetOrchestrator initialized")

    # ── Firebase ─────────────────────────────────────────────────────────

    def set_firebase_store(self, firebase_store_module):
        """Inject the firebase_store module and capture current event loop."""
        self._firebase_store = firebase_store_module
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback if called outside an async context
            try:
                self._main_loop = asyncio.get_event_loop()
            except Exception:
                self._main_loop = None
        logger.info(f"Firebase store injected (main_loop captured: {self._main_loop is not None})")

    async def load_config_from_firebase(self):
        """Load FleetConfig from Firestore. Falls back to default if not found."""
        if not self._firebase_store:
            return
        try:
            data = await self._firebase_store.load_fleet_config()
            if data:
                config = FleetConfig.from_dict(data)
                with self._config_lock:
                    self._fleet_config = config
                logger.info(f"FleetConfig loaded from Firestore: {config}")
        except Exception as e:
            logger.warning(f"Could not load FleetConfig from Firestore: {e}")

    async def restore_bots_from_firebase(self):
        """
        On startup: read all saved bot configs from Firestore and redeploy them.
        Bots are restored in STOPPED state — they must be manually started or
        auto-started based on their saved config.

        Also performs a one-time migration: bots saved before the parent-marker
        fix will have configs at bots/{id}/meta/config but no parent document
        at bots/{id}.  We detect these via a collection-group query on 'meta'
        and backfill the missing parent markers so future restarts work.
        """
        if not self._firebase_store:
            logger.info("Firebase not available — skipping bot restoration")
            return
        try:
            bot_ids = await self._firebase_store.list_bot_ids()

            # ── Migration: discover orphaned bots with no parent marker ──
            try:
                orphan_ids = await self._firebase_store.discover_orphaned_bot_ids(
                    known_ids=set(bot_ids)
                )
                if orphan_ids:
                    logger.info(
                        f"Migration: found {len(orphan_ids)} orphaned bot(s) "
                        f"without parent markers: {orphan_ids}"
                    )
                    bot_ids.extend(orphan_ids)
            except Exception as e:
                logger.warning(f"Orphan discovery failed (non-fatal): {e}")

            if not bot_ids:
                logger.info("No bots found in Firestore to restore")
                return

            logger.info(f"Restoring {len(bot_ids)} bot(s) from Firestore: {bot_ids}")
            restored = 0
            for bot_id in bot_ids:
                try:
                    config_dict = await self._firebase_store.load_bot_config(bot_id)
                    if not config_dict:
                        logger.warning(f"[{bot_id}] No config found in Firestore — skipping")
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
                        await self._firebase_store.save_bot_config(
                            config.bot_id, config.to_dict()
                        )
                    except Exception:
                        pass  # Non-fatal — config already exists in subcollection

                    instance = self._build_bot_instance(config)
                    with self._lock:
                        self._bots[config.bot_id] = instance

                    # Auto-start if configured
                    if config.auto_start:
                        logger.info(f"[{bot_id}] Auto-starting engine per config")
                        instance.engine.start()

                    restored += 1
                    logger.info(
                        f"[{bot_id}] Restored: {config.symbol} | {config.strategy} | "
                        f"demo={config.demo_mode}"
                    )
                except Exception as e:
                    logger.error(f"[{bot_id}] Failed to restore from Firestore: {e}", exc_info=True)

            logger.info(f"Bot restoration complete: {restored}/{len(bot_ids)} restored")
        except Exception as e:
            logger.error(f"Bot restoration failed: {e}", exc_info=True)

    # ── Fleet Config ─────────────────────────────────────────────────────

    def get_fleet_config(self) -> dict:
        with self._config_lock:
            return self._fleet_config.to_dict()

    def update_fleet_config(self, updates: dict) -> dict:
        """
        Apply validated updates to FleetConfig. Saves to Firestore.
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

        # Persist to Firestore (fire and forget)
        if self._firebase_store:
            asyncio.get_event_loop().create_task(
                self._firebase_store.save_fleet_config(result)
            )
        logger.info(f"FleetConfig updated: {updates}")
        return result

    # ── Bot Lifecycle ─────────────────────────────────────────────────────

    def deploy_bot(self, config: BotConfig) -> BotInstance:
        """
        Spawn a new isolated bot instance.
        Raises ValueError if max_bots cap is reached.
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

        # Apply fleet-level overrides
        effective_config = deepcopy(config)
        if not sub_agents_enabled:
            effective_config.sub_agents = []

        # Build the bot instance
        instance = self._build_bot_instance(effective_config)

        with self._lock:
            self._bots[config.bot_id] = instance

        # Persist config to Firestore
        if self._firebase_store:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._firebase_store.save_bot_config(
                            config.bot_id, effective_config.to_dict()
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not persist bot config to Firestore: {e}")

        # Auto-start if configured
        if config.auto_start:
            logger.info(f"[{config.bot_id}] Auto-starting engine per deployment request")
            instance.engine.start()

        return instance

    def kill_bot(self, bot_id: str):
        """Stop, deregister, and delete a bot from Firestore."""
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

        # Remove from Firestore so it doesn't resurrect on next restart
        if self._firebase_store:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._firebase_store.delete_bot_config(bot_id)
                    )
            except Exception as e:
                logger.warning(f"[{bot_id}] Could not delete bot config from Firestore: {e}")

        logger.info(f"Bot killed and removed from Firestore: {bot_id}")

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
        """Stop the fleet monitor loop."""
        self._stop_event.set()
        logger.info("Fleet monitor stopped")

    def _monitor_loop(self):
        """Background loop: risk checks + telemetry push + bar flush every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                self.enforce_global_risk_limits()
                self._push_telemetry()
                self._flush_bar_queues()
                self._check_darwinian_evolution()
                self._check_autoresearch_evolution()
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

    def _flush_bar_queues(self):
        """
        Drain each bot's bar queue and batch-write to Firestore.
        Bars are grouped by symbol so multiple bots trading the same
        asset don't create duplicate writes.

        Safety cap: each symbol batch is capped at 500 bars per flush cycle.
        If Firestore falls behind and bars accumulate, only the most-recent
        500 are written; the rest are discarded (data loss acceptable —
        the running deque in BotEngine already bounds total memory).
        """
        if not self._firebase_store:
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
                import firebase_store
                logger.debug(f"[Fleet] Flushing {len(bars)} bar(s) for {symbol} to Firestore")
                future = asyncio.run_coroutine_threadsafe(
                    firebase_store.append_bars_batch(symbol, bars), loop
                )
                written = future.result(timeout=10)
                if written:
                    logger.debug(f"Bar flush: {written} bars persisted for {symbol}")
            except Exception as e:
                logger.warning(f"Bar flush error ({symbol}): {e}")


    def _push_telemetry(self):
        """Push live fleet state to Firestore (live_telemetry collection)."""
        if not self._firebase_store:
            return
        try:
            # Use captured main loop for thread-safe async calls
            loop = self._main_loop
            if not loop or not loop.is_running():
                return

            fleet_snap = self.get_fleet_status()["summary"]
            future = asyncio.run_coroutine_threadsafe(
                self._firebase_store.push_fleet_telemetry(fleet_snap), loop
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
                        bot_future = asyncio.run_coroutine_threadsafe(
                            self._firebase_store.push_live_telemetry(
                                instance.bot_id, state
                            ),
                            loop,
                        )
                        bot_future.result(timeout=5)
                    except Exception as e:
                        logger.warning(f"[{instance.bot_id}] Bot telemetry push error: {e}")
        except Exception as e:
            logger.warning(f"Telemetry push failed: {e}")

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
        import os

        # Build Gemini client using OpenAI-compatible endpoint
        gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL_NAME", "gemma2:4b")

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
            firebase_store=self._firebase_store,
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
        return instance


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

fleet = FleetOrchestrator()
