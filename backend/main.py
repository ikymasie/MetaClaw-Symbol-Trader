"""
TradeClaw — FastAPI Application
REST API wrapping the Mean Reversion Execution Engine.
Fleet-aware: multi-bot orchestration via /fleet/* endpoints.
"""

import asyncio
import json
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd
from datetime import timedelta

# Fleet
from bot_config import BotConfig, FleetConfig
from fleet import fleet

# MT5 hub (market data + news)
from mt5_hub import mt5_hub

from config import config
from config_manager import config_manager
from postgres_store import (
    init_db,
    insert_trade,
    insert_equity_snapshot,
    get_all_trades,
    get_recent_trades_for_analysis,
    _legacy_get_equity_history as get_equity_history,
    _legacy_get_daily_pnl_sum as get_daily_pnl_sum,
    _legacy_get_trade_stats_today as get_trade_stats_today,
    _legacy_set_bot_state as set_bot_state,
    _legacy_get_bot_state as get_bot_state,
    _legacy_get_ai_decisions as get_ai_decisions,
    save_fleet_event,
    save_audit_log,
    get_store,
    is_initialized as _db_is_initialized,
)
from models import (
    BotStatus,
    StatusResponse,
    ConfigSnapshot,
    ConfigUpdate,
    StartRequest,
    HistoryResponse,
    TradeRecord,
    PricePoint,
    MarkerPoint,
    EquityPoint,
    BollingerData,
)
from ai_brain import ai_brain
from vital_signs import vital_signs
from symbol_service import symbol_service, to_mt5_symbol

# Setup & Accounts API routes
import setup_routes
import account_routes

# ---- Logging ----
from buffered_logger import setup_buffered_logging
buffered_handler = setup_buffered_logging("logs/fleet.txt", interval=10.0)
logger = logging.getLogger("tradeclaw")


# ---- WebSocket Connection Manager ----
class ConnectionManager:
    """Tracks active WebSocket connections, categorized by channel.

    Memory safety guarantees:
    - Hard cap of MAX_CONNECTIONS_PER_CHANNEL per channel prevents runaway growth.
    - broadcast() auto-removes dead sockets on send failure.
    - purge_stale() proactively pings all sockets and evicts the unresponsive ones;
      called on a 60-second timer from the broadcast loops.
    """

    MAX_CONNECTIONS_PER_CHANNEL = 50

    def __init__(self):
        # channel_name -> list of websockets
        self.active: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, channel: str = "global"):
        await ws.accept()
        async with self._lock:
            if channel not in self.active:
                self.active[channel] = []
            # Enforce per-channel cap — evict oldest if over limit
            while len(self.active[channel]) >= self.MAX_CONNECTIONS_PER_CHANNEL:
                evicted = self.active[channel].pop(0)
                logger.warning(
                    f"[WS] Channel '{channel}' at cap ({self.MAX_CONNECTIONS_PER_CHANNEL}); "
                    f"evicting oldest connection"
                )
                try:
                    await evicted.close()
                except Exception:
                    pass
            self.active[channel].append(ws)
        logger.info(
            f"[WS] Client connected to '{channel}'. "
            f"Total in channel: {len(self.active.get(channel, []))}"
        )

    def disconnect(self, ws: WebSocket, channel: str = "global"):
        if channel in self.active:
            self.active[channel] = [a for a in self.active[channel] if a is not ws]
            if not self.active[channel]:
                del self.active[channel]
        logger.info(f"[WS] Client disconnected from channel '{channel}'.")

    async def broadcast(self, payload: dict, channel: str = "global"):
        """Send payload to all clients in a specific channel.
        Dead sockets are collected and removed atomically after the send pass.
        """
        if channel not in self.active:
            return

        data = json.dumps(payload, default=str)
        dead = []
        for ws in list(self.active.get(channel, [])):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, channel)

    async def purge_stale(self):
        """Probe every active socket with a ping; evict those that don't respond.
        Should be called periodically (e.g. every 60 s) to reclaim memory from
        browser tabs that closed without sending a proper WebSocket close frame.
        """
        channels = list(self.active.keys())
        evicted_total = 0
        for channel in channels:
            dead = []
            for ws in list(self.active.get(channel, [])):
                try:
                    await ws.send_text('{"type":"ping"}')
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws, channel)
                evicted_total += 1
        if evicted_total:
            logger.info(f"[WS] purge_stale: evicted {evicted_total} dead connection(s)")

    def total_connections(self) -> int:
        """Total active connections across all channels (for observability)."""
        return sum(len(v) for v in self.active.values())


manager = ConnectionManager()

# ---- Global streaming pause flag ----
_streaming_paused = False


# ---- Trade Stats Cache (avoids Firestore query every 500ms) ----
_trade_stats_cache: dict = {"total_trades": 0, "win_rate": 0.0}
_trade_stats_cache_ts: float = 0.0
_TRADE_STATS_TTL: float = 30.0  # Refresh every 30 seconds


async def _get_cached_trade_stats() -> dict:
    """Return trade stats from cache, refreshing from Firestore at most every 30s."""
    global _trade_stats_cache, _trade_stats_cache_ts
    import time
    now = time.monotonic()
    if now - _trade_stats_cache_ts > _TRADE_STATS_TTL:
        try:
            _trade_stats_cache = await get_trade_stats_today()
            _trade_stats_cache_ts = now
        except Exception:
            pass  # Use stale cache on error
    return _trade_stats_cache


# ---- WebSocket Broadcast Loop ----
async def ws_fleet_broadcast_loop():
    """
    Runs every 500ms — iterates through every active bot in the fleet and:
      1. Broadcasts the regular 500ms bot_update state snapshot (Situation Room polling)
      2. Drains the per-bot LangGraph event queue and pushes deliberation_event
         messages as they arrive (real-time agent-level streaming)
    Skips when paused. Runs stale-connection purge every 60 seconds.
    """
    import queue as _q
    _purge_counter = 0
    while True:
        try:
            _purge_counter += 1
            if _purge_counter >= 120:
                await manager.purge_stale()
                _purge_counter = 0

            if not _streaming_paused:
                bot_channels = [ch for ch in manager.active.keys() if ch.startswith("bot-")]
                if bot_channels:
                    for channel in bot_channels:
                        bot_id = channel.replace("bot-", "", 1)
                        instance = fleet.get_bot(bot_id)
                        if not instance or not instance.engine:
                            continue

                        # ── 1. Regular state snapshot (500ms polling) ─────────
                        state = instance.engine.get_state_snapshot()
                        payload = {
                            "type": "bot_update",
                            "bot_id": bot_id,
                            "symbol": instance.config.symbol,
                            "status": state["bot_status"],
                            "regime": state.get("regime", "UNKNOWN"),
                            "last_deliberation": state.get("last_deliberation", {}),
                            "agent_weights": state.get("agent_weights", {}),
                            "enabled_agents": instance.config.sub_agents or [],
                            "position": {
                                "qty": state["position_qty"],
                                "side": state["position_side"],
                                "pnl": state["daily_pnl"],
                                "unrealized_pnl": state["unrealized_pnl"],
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        await manager.broadcast(payload, channel=channel)

                        # ── 2. Drain LangGraph event queue (real-time streaming) ──
                        pool = instance.sub_agent_pool
                        if pool and hasattr(pool, "_event_queue"):
                            _drained = 0
                            while _drained < 20:  # Cap per tick to avoid starving other bots
                                try:
                                    evt = pool._event_queue.get_nowait()
                                    await manager.broadcast(evt, channel=channel)
                                    _drained += 1
                                except _q.Empty:
                                    break

        except Exception as e:
            logger.error(f"[WS] Fleet broadcast error: {e}")
        await asyncio.sleep(0.5)



# ---- Fleet Pydantic models ----

class DeployBotRequest(BaseModel):
    bot_id: Optional[str] = None
    account_id: str = Field(default="", description="MT5 account ID to trade on")
    name: str = "Unnamed Bot"
    symbol: str = Field(..., description="Target trading symbol")
    strategy: str = "mean_reversion"
    capital_allocation: float = Field(default=10000.0, ge=1.0)
    description: str = ""
    personality: str = ""
    animal: str = ""
    category: str = ""
    ai_generated: bool = False
    qty: float = Field(default=1.0, gt=0)
    short_selling_enabled: bool = True
    stop_loss_pct: float = Field(default=1.5, ge=0.25, le=5.0)
    max_daily_drawdown_pct: float = Field(default=6.0, ge=0.5, le=25.0)
    bb_period: int = Field(default=20, ge=8, le=100)
    bb_std_dev: float = Field(default=2.0, ge=1.0, le=3.5)
    ai_brain_enabled: bool = True
    ai_interval_minutes: int = 60
    ai_min_trades_trigger: int = 10
    ai_loss_streak_trigger: int = 3
    research_enabled: bool = True
    research_interval_hours: int = 4
    sub_agents: list[str] = Field(default=["sentiment", "macro", "earnings", "technical", "research_framework", "correlation", "orderflow", "calendar"])
    sub_agent_interval_minutes: int = 15
    agent_vote_cache_ttl_seconds: int = 1800
    tags: list[str] = []
    fib_enabled: bool = True
    fib_lookback_bars: int = 50
    fib_bounce_threshold_pct: float = 0.20
    fib_entry_mode: str = "AND"
    fib_active_levels_raw: str = "23.6,38.2,50.0,61.8"
    smart_routing_min_qty: float = 3.0
    twap_interval_ms: int = 500
    max_slippage_pct: float = 0.05
    limit_timeout_s: int = 10
    auto_start: bool = True
    leverage_mode_enabled: bool = True
    leverage_factor: float = 20.0
    isolated_risk_usd: float = 40.0
    net_profit_target_usd: float = 1.0
    take_profit_usd: float = 0.0


class FleetConfigUpdate(BaseModel):
    max_bots: Optional[int] = Field(default=None, ge=1, le=50)
    global_risk_enabled: Optional[bool] = None
    max_fleet_drawdown_pct: Optional[float] = Field(default=None, ge=1.0, le=50.0)
    sub_agents_enabled: Optional[bool] = None
    auto_redeploy: Optional[bool] = None
    log_retention_days: Optional[int] = Field(default=None, ge=1, le=365)


# ---- Lifespan ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — init DB, start all subsystems, cleanup on exit."""
    logger.info("TradeClaw starting up...")

    setup_complete = config_manager.is_setup_complete()
    fleet_broadcast_task = None

    if setup_complete:
        # ── Full startup: DB, MT5, Fleet ───────────────────────────────

        # 1. Initialize DB with ConfigManager URL (fallback to env)
        try:
            db_url = config_manager.get_database_url()
            await init_db(db_url if db_url else None)
            await save_fleet_event("SYSTEM_STARTUP", "INFO", "TradeClaw Execution Engine starting up")
        except Exception as e:
            logger.error(f"PostgreSQL initialization failed: {e}")

        # 2. Start MT5 Hub using credentials from ConfigManager (default account)
        #    Non-fatal: if the terminal isn't running yet, bots will trigger
        #    lazy initialization when deployed via FleetOrchestrator.
        try:
            default_account = config_manager.get_default_account()
            if default_account:
                mt5_hub.init(
                    login=default_account.get("mt5_login", 0),
                    password=default_account.get("mt5_password", ""),
                    server=default_account.get("mt5_server", ""),
                )
            else:
                # Fallback to env vars for backward compatibility
                mt5_hub.init(
                    login=int(os.getenv("MT5_LOGIN", "0") or "0"),
                    password=os.getenv("MT5_PASSWORD", ""),
                    server=os.getenv("MT5_SERVER", ""),
                )
            mt5_hub.start()
        except Exception as e:
            logger.warning(
                f"MT5 terminal not available at startup: {e} — "
                f"will initialize lazily when first bot is deployed"
            )

        # 3. Init Fleet Persistence (PostgreSQL)
        try:
            import postgres_store
            fleet.set_store(postgres_store)
            await fleet.load_config_from_store()
            await fleet.restore_bots_from_store()
            logger.info("PostgreSQL connected (Neon), fleet config and bots restored")
        except Exception as e:
            logger.error(f"Fleet initialization from PostgreSQL failed: {e}")

        # Start Partition Manager
        try:
            from database.partition_manager import maintenance_loop
            asyncio.create_task(maintenance_loop())
            logger.info("Partition maintenance loop started")
        except Exception as e:
            logger.error(f"Failed to start partition maintenance loop: {e}")

        # Publish the running event loop to sub_agents so background threads
        # can schedule async PostgreSQL calls (DarwinianWeightStore, LangGraph graph).
        try:
            import sub_agents as _sa
            _sa.set_main_event_loop(asyncio.get_running_loop())
        except Exception as _e:
            logger.warning(f"Could not set main event loop in sub_agents: {_e}")

        # Start fleet monitor
        fleet.start_monitor()

        # Start background tasks
        fleet_broadcast_task = asyncio.create_task(ws_fleet_broadcast_loop())

        # Start AI Brain if enabled
        if config.ai_snapshot()["ai_brain_enabled"]:
            ai_brain.start()

        logger.info("TradeClaw ready — full trading mode")
    else:
        # ── Setup mode: only API + setup routes active ────────────────
        logger.info(
            "TradeClaw starting in SETUP MODE — "
            "complete the setup wizard at http://localhost:3000/setup"
        )

    yield

    # Shutdown — Phase 4 §8.4: Graceful shutdown with queue drain & position snapshot
    logger.info("TradeClaw shutting down...")
    if setup_complete:
        # ── 1. Stop fleet monitor (drains bot event loops) ─────────────
        fleet.stop_monitor()

        # ── 2. Final DB queue flush — ensure all pending writes complete ─
        try:
            fleet._flush_db_queues()
            logger.info("Final DB queue flush complete")
        except Exception as e:
            logger.error(f"Final DB queue flush failed: {e}")

        # ── 3. Snapshot open MT5 positions to file ──────────────────────
        try:
            _snapshot_open_positions()
        except Exception as e:
            logger.error(f"Position snapshot failed: {e}")

        # ── 4. Stop MT5 hub ────────────────────────────────────────────
        mt5_hub.stop()
        if ai_brain.enabled:
            ai_brain.stop()
        if fleet_broadcast_task:
            fleet_broadcast_task.cancel()

        # ── 5. Cancel all outstanding asyncio tasks ─────────────────────
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        await save_fleet_event("SYSTEM_SHUTDOWN", "INFO", "TradeClaw Execution Engine shut down gracefully")
    logger.info("TradeClaw shutdown complete")


def _snapshot_open_positions():
    """Phase 4 §8.4 — Write all open MT5 positions to a JSON file on shutdown."""
    import json as _json
    try:
        from mt5_bridge import mt5
        if mt5 is None or mt5.terminal_info() is None:
            return
        positions = mt5.positions_get()
        if not positions:
            logger.info("No open MT5 positions at shutdown")
            return
        snapshot = []
        for p in positions:
            p_dict = p._asdict() if hasattr(p, "_asdict") else dict(p)
            for k in list(p_dict):
                v = p_dict[k]
                if hasattr(v, "isoformat"):
                    p_dict[k] = v.isoformat()
                elif isinstance(v, (int, float, str, bool, type(None))):
                    pass
                else:
                    p_dict[k] = str(v)
            snapshot.append(p_dict)

        os.makedirs("logs", exist_ok=True)
        path = f"logs/positions_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(snapshot, f, indent=2, default=str)
        logger.info(
            f"Position snapshot written: {len(snapshot)} open positions → {path}",
            extra={
                "event": "shutdown_positions_snapshot",
                "file": path,
                "count": len(snapshot),
            },
        )
    except Exception as e:
        logger.warning(f"Position snapshot failed: {e}")


# ════════════════════════════════════════════════════════
# SIGTERM / SIGINT HANDLER (Phase 4 §8.4)
# ════════════════════════════════════════════════════════
# Registered BEFORE the app starts so that clean-up fires even if Uvicorn
# doesn't reach the lifespan shutdown path (e.g. SIGKILL, pod eviction, OOM).
_shutting_down = False


def _handle_sigterm(signum, frame):
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.warning(
        f"Received signal {signum} — initiating graceful shutdown...",
        extra={"event": "sigterm_received", "signal": signum},
    )
    try:
        fleet.stop_monitor()
        fleet._flush_db_queues()
        _snapshot_open_positions()
        mt5_hub.stop()
    except Exception as e:
        logger.error(f"Graceful shutdown hook failed: {e}")


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)

# ---- App ----
app = FastAPI(
    title="TradeClaw Execution Engine",
    description="Multi-Agent System (MAS) trading platform — 6 expert agents, quorum deliberation, smart order routing.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Robust for dev/production flexibility
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Mount Setup & Account Routers ----
app.include_router(setup_routes.router)
app.include_router(account_routes.router)


# ---- Endpoints ----

@app.get("/ai/status")
async def get_ai_status():
    """Get AI Brain status and configuration."""
    return ai_brain.get_status()


@app.post("/ai/trigger")
async def trigger_ai_analysis():
    """Manually trigger an AI optimization cycle."""
    ai_brain.trigger_manual()
    return {"status": "manual_trigger_started"}


@app.get("/ai/decisions")
async def get_ai_decisions_endpoint(limit: int = 50):
    """Get history of AI decisions."""
    decisions = await get_ai_decisions(limit=limit)
    return {"decisions": decisions}


@app.get("/vital/status")
async def get_vital_status():
    """Get the organism's current vital signs — survival state, apex tier, intelligence budget."""
    return vital_signs.get_status()


@app.get("/vital/events")
async def get_vital_events():
    """Get the organism's event log — all survival and tier-unlock events."""
    status = vital_signs.get_status()
    return {
        "event_log": status["event_log"],
        "last_event": status["last_event"],
    }


# ════════════════════════════════════════════════════════
# SYSTEM RESOURCE MONITOR
# ════════════════════════════════════════════════════════

@app.get("/system/resources")
async def system_resources():
    """
    Real-time host CPU and RAM metrics for the Situation Room monitor.
    Also reports the backend process's own RSS footprint so the user
    can correlate memory growth with backend activity.
    """
    try:
        import psutil, os
        process = psutil.Process(os.getpid())

        # CPU — measured over a 0.1s interval (non-blocking in async context)
        cpu_pct = await asyncio.get_event_loop().run_in_executor(
            None, lambda: psutil.cpu_percent(interval=0.1)
        )
        cpu_count = psutil.cpu_count(logical=True)
        cpu_per_core = psutil.cpu_percent(percpu=True)

        # RAM
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Process-specific
        proc_info = process.memory_info()
        proc_rss_mb = proc_info.rss / (1024 ** 2)
        proc_vms_mb = proc_info.vms / (1024 ** 2)
        proc_cpu_pct = process.cpu_percent(interval=None)

        return {
            "cpu": {
                "percent": round(cpu_pct, 1),
                "count": cpu_count,
                "per_core": [round(c, 1) for c in cpu_per_core],
            },
            "ram": {
                "total_mb": round(vm.total / (1024 ** 2), 1),
                "used_mb": round(vm.used / (1024 ** 2), 1),
                "available_mb": round(vm.available / (1024 ** 2), 1),
                "percent": round(vm.percent, 1),
            },
            "swap": {
                "total_mb": round(swap.total / (1024 ** 2), 1),
                "used_mb": round(swap.used / (1024 ** 2), 1),
                "percent": round(swap.percent, 1),
            },
            "process": {
                "rss_mb": round(proc_rss_mb, 1),
                "vms_mb": round(proc_vms_mb, 1),
                "cpu_pct": round(proc_cpu_pct, 1),
                "pid": os.getpid(),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except ImportError:
        return {
            "error": "psutil not installed — run: pip install psutil",
            "cpu": {"percent": 0, "count": 0, "per_core": []},
            "ram": {"total_mb": 0, "used_mb": 0, "available_mb": 0, "percent": 0},
            "swap": {"total_mb": 0, "used_mb": 0, "percent": 0},
            "process": {"rss_mb": 0, "vms_mb": 0, "cpu_pct": 0, "pid": 0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ════════════════════════════════════════════════════════
# GEMINI API BUDGET MONITOR
# ════════════════════════════════════════════════════════

@app.get("/system/gemini-budget")
async def system_gemini_budget():
    """
    Real-time Gemini API budget status.
    Shows hourly call count, remaining budget, circuit breaker state,
    and lifetime stats. Used by the Situation Room to monitor API health.
    """
    from gemini_budget import gemini_budget
    return gemini_budget.get_status()


# ════════════════════════════════════════════════════════
# STREAMING CONTROL ENDPOINTS
# ════════════════════════════════════════════════════════

@app.post("/streaming/pause")
async def streaming_pause():
    """Pause all WebSocket broadcast loops and MT5 hub fan-out."""
    global _streaming_paused
    _streaming_paused = True
    mt5_hub.pause()
    logger.info("[Streaming] PAUSED — all broadcast loops suspended")
    return {"streaming": False, "message": "All streams paused"}


@app.post("/streaming/resume")
async def streaming_resume():
    """Resume all WebSocket broadcast loops and MT5 hub fan-out."""
    global _streaming_paused
    _streaming_paused = False
    mt5_hub.resume()
    logger.info("[Streaming] RESUMED — all broadcast loops active")
    return {"streaming": True, "message": "All streams resumed"}


@app.get("/streaming/status")
async def streaming_status():
    """Return current streaming state and stats."""
    return {
        "paused": _streaming_paused,
        "ticker": mt5_hub.get_stats(),
        "ws_channels": len(manager.active),
    }


# ════════════════════════════════════════════════════════
# FLEET ENDPOINTS
# ════════════════════════════════════════════════════════

@app.get("/fleet/status")
async def fleet_status():
    """Full fleet status — all bots, summary, fleet config."""
    return fleet.get_fleet_status()


@app.get("/market/data/{symbol:path}")
async def get_market_data(symbol: str):
    """Fetch live market data for a symbol (Stock or Crypto) and calculate BBs.

    Returns a graceful empty response when data is unavailable (market closed,
    unsupported symbol, etc.) instead of a 500 so the frontend can render a
    "no data" state without error-looping.
    """
    _empty_response = {
        "symbol": symbol.upper(),
        "price_data": [],
        "bollinger": [],
        "market_closed": True,
        "message": "",
    }

    try:
        from mt5_bridge import mt5
        clean = symbol.strip().upper()
        mt5_symbol = to_mt5_symbol(clean)

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)

        mt5.symbol_select(mt5_symbol, True)
        # Use copy_rates_from_pos (index-based) instead of copy_rates_range (time-based)
        # for better stability over RPyC bridge.
        rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M1, 0, 120)

        if rates is None or len(rates) == 0:
            _empty_response["message"] = f"No recent data for {mt5_symbol} — market may be closed"
            return _empty_response

        import numpy as np
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})
        df = df[["time", "open", "high", "low", "close", "volume"]]

        # BB Calculation
        period = 20
        std_dev = 2.0
        df["sma"] = df["close"].rolling(window=period).mean()
        df["std"] = df["close"].rolling(window=period).std()
        df["upper_bb"] = df["sma"] + (std_dev * df["std"])
        df["lower_bb"] = df["sma"] - (std_dev * df["std"])
        df = df.dropna()

        # Format for TV Chart
        price_data = []
        bollinger = []
        # ⚡ Bolt: Using zip() instead of df.iterrows() to avoid Pandas Series boxing overhead
        for time_val, open_val, high_val, low_val, close_val, upper_bb, sma, lower_bb in zip(
            df["time"], df["open"], df["high"], df["low"], df["close"],
            df["upper_bb"], df["sma"], df["lower_bb"]
        ):
            ts = time_val.isoformat() if hasattr(time_val, "isoformat") else str(time_val)
            price_data.append({
                "time": ts,
                "open": float(open_val),
                "high": float(high_val),
                "low": float(low_val),
                "close": float(close_val),
            })
            bollinger.append({
                "time": ts,
                "upper": float(upper_bb),
                "middle": float(sma),
                "lower": float(lower_bb),
            })

        return {
            "symbol": symbol.upper(),
            "price_data": price_data,
            "bollinger": bollinger,
            "market_closed": False,
        }
    except HTTPException:
        raise  # Let FastAPI handle its own exceptions
    except Exception as e:
        logger.warning(f"[MarketData] Data unavailable for {symbol}: {e}")
        _empty_response["message"] = str(e)
        return _empty_response


@app.get("/market/symbols/available")
async def get_available_symbols(q: Optional[str] = None):
    """Fetch all available symbols from the MT5 terminal, enriched by Excel definitions."""
    try:
        # Get live terminal data for technical fields (digits, spread, etc)
        live_symbols = {s["name"]: s for s in mt5_hub.get_all_symbols()}
        
        # Get Excel definitions
        if q:
            excel_symbols = symbol_service.search_symbols(q)
        else:
            excel_symbols = symbol_service.get_all_symbols()
        
        enriched = []
        for s in excel_symbols:
            name = s["name"]
            # Look up live data using the broker-specific symbol name (e.g. EURUSD_i)
            broker_name = symbol_service.get_broker_symbol(name)
            live = live_symbols.get(broker_name, {})
            
            # Merge: Excel provides metadata, MT5 provides live trading params
            enriched.append({
                "name": name,
                "broker_symbol": broker_name,
                "description": s["description"] or live.get("description", ""),
                "category": s["category"],
                "path": live.get("path", ""),
                "digits": live.get("digits", 0),
                "spread": live.get("spread", 0),
                "trade_mode": live.get("trade_mode", 0),
                "volume_min": live.get("volume_min", 0.01),
                "volume_max": live.get("volume_max", 100.0),
                "volume_step": live.get("volume_step", 0.01),
            })
            
        return {"symbols": enriched}
    except Exception as e:
        logger.error(f"Error fetching available symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/fleet/deploy")
async def fleet_deploy(request: DeployBotRequest):
    """Deploy a new bot into the fleet."""
    import uuid
    bot_id = request.bot_id or f"bot-{uuid.uuid4().hex[:8]}"
    try:
        cfg = BotConfig(
            bot_id=bot_id,
            account_id=request.account_id,
            name=request.name,
            symbol=request.symbol,
            strategy=request.strategy,
            capital_allocation=request.capital_allocation,
            description=request.description,
            personality=request.personality,
            animal=request.animal,
            category=request.category,
            ai_generated=request.ai_generated,
            qty=request.qty,
            short_selling_enabled=request.short_selling_enabled,
            stop_loss_pct=request.stop_loss_pct,
            max_daily_drawdown_pct=request.max_daily_drawdown_pct,
            bb_period=request.bb_period,
            bb_std_dev=request.bb_std_dev,
            ai_brain_enabled=request.ai_brain_enabled,
            ai_interval_minutes=request.ai_interval_minutes,
            ai_min_trades_trigger=request.ai_min_trades_trigger,
            ai_loss_streak_trigger=request.ai_loss_streak_trigger,
            research_enabled=request.research_enabled,
            research_interval_hours=request.research_interval_hours,
            sub_agents=request.sub_agents,
            sub_agent_interval_minutes=request.sub_agent_interval_minutes,
            agent_vote_cache_ttl_seconds=request.agent_vote_cache_ttl_seconds,
            tags=request.tags,
            fib_enabled=request.fib_enabled,
            fib_lookback_bars=request.fib_lookback_bars,
            fib_bounce_threshold_pct=request.fib_bounce_threshold_pct,
            fib_entry_mode=request.fib_entry_mode,
            fib_active_levels_raw=request.fib_active_levels_raw,
            smart_routing_min_qty=request.smart_routing_min_qty,
            twap_interval_ms=request.twap_interval_ms,
            max_slippage_pct=request.max_slippage_pct,
            limit_timeout_s=request.limit_timeout_s,
            auto_start=request.auto_start,
            leverage_mode_enabled=request.leverage_mode_enabled,
            leverage_factor=request.leverage_factor,
            isolated_risk_usd=request.isolated_risk_usd,
            net_profit_target_usd=request.net_profit_target_usd,
            take_profit_usd=request.take_profit_usd,
        )
        instance = fleet.deploy_bot(cfg)
        return {
            "status": "deployed",
            "bot_id": bot_id,
            "name": cfg.name,
            "symbol": cfg.symbol,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bot deploy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/fleet/account")
async def fleet_account():
    """Get MT5 account summary (balance, equity, margin, etc.).

    Returns a graceful DISCONNECTED response when the MT5 terminal is
    unreachable (e.g. local macOS dev without Wine/Docker) so the
    frontend can render a "not connected" state without error-looping.
    """
    _disconnected = {
        "equity": 0,
        "portfolio_value": 0,
        "buying_power": 0,
        "daytrading_buying_power": 0,
        "regt_buying_power": 0,
        "cash": 0,
        "daily_pnl": 0,
        "daily_pnl_pct": 0,
        "unrealized_pnl": 0,
        "margin_used": 0,
        "margin_free": 0,
        "currency": "USD",
        "status": "DISCONNECTED",
        "message": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from mt5_bridge import mt5
        acc = mt5.account_info()
        if acc is None:
            err = mt5.last_error()
            logger.warning(f"MT5 account_info() returned None: {err}")
            _disconnected["message"] = f"MT5 terminal not connected: {err}"
            return _disconnected

        equity = float(acc.equity)
        balance = float(acc.balance)
        daily_pnl = equity - balance
        daily_pnl_pct = (daily_pnl / balance * 100) if balance > 0 else 0.0

        return {
            "equity": equity,
            "portfolio_value": equity,
            "buying_power": float(acc.margin_free),
            "daytrading_buying_power": float(acc.margin_free),
            "regt_buying_power": float(acc.margin_free),
            "cash": balance,
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "unrealized_pnl": float(acc.profit),
            "margin_used": float(acc.margin),
            "margin_free": float(acc.margin_free),
            "currency": acc.currency,
            "status": "ACTIVE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"MT5 account unavailable: {e}")
        _disconnected["message"] = str(e)
        return _disconnected



@app.delete("/fleet/bot/{bot_id}")
async def fleet_kill_bot(bot_id: str):
    """Stop and remove a bot from the fleet."""
    try:
        fleet.kill_bot(bot_id)
        return {"status": "killed", "bot_id": bot_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/fleet/bot/{bot_id}")
async def fleet_get_bot(bot_id: str):
    """Get a single bot's state snapshot."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    return instance.get_snapshot()


@app.get("/fleet/bot/{bot_id}/history")
async def fleet_get_bot_history(bot_id: str, limit: int = 200):
    """Get a bot's trade history, equity curve, and chart data."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.engine:
        raise HTTPException(status_code=400, detail="Bot has no engine")

    trades = instance.engine.get_recent_trades(limit=limit)
    equity = instance.engine.get_equity_history(limit=500)

    with instance.engine._lock:
        price_data = list(instance.engine.price_history)
        markers = list(instance.engine.markers)
        bollinger = list(instance.engine.bollinger_data)

    return {
        "bot_id": bot_id,
        "trades": trades,
        "equity_curve": equity,
        "price_data": price_data,
        "markers": markers,
        "bollinger": bollinger,
        "total_trades": len(trades),
        "total_realized_pnl": instance.engine.total_realized_pnl,
    }


@app.post("/fleet/bot/{bot_id}/start")
async def fleet_start_bot(bot_id: str, request: StartRequest = StartRequest()):
    """Start a deployed (but stopped) bot's engine."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.engine:
        raise HTTPException(status_code=400, detail="Bot has no engine")
    
    instance.engine.start()
    return {"status": "started", "bot_id": bot_id}


@app.post("/fleet/bot/{bot_id}/stop")
async def fleet_stop_bot(bot_id: str):
    """Stop a bot's engine."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.engine:
        raise HTTPException(status_code=400, detail="Bot has no engine")
    instance.engine.stop()
    return {"status": "stopped", "bot_id": bot_id}


@app.patch("/fleet/bot/{bot_id}/config")
async def fleet_update_bot_config(bot_id: str, updates: dict):
    """Update a bot's config (e.g. qty, stop_loss_pct)."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    ALLOWED_FIELDS = {
        "qty", "stop_loss_pct", "bb_period", "bb_std_dev",
        "max_daily_drawdown_pct", "fib_enabled", "ai_brain_enabled",
        "ai_interval_minutes", "capital_allocation", "kill_zone_enabled",
        "short_selling_enabled", "leverage_mode_enabled", "leverage_factor",
        "isolated_risk_usd", "net_profit_target_usd", "take_profit_usd",
    }
    applied = {}
    for key, value in updates.items():
        if key in ALLOWED_FIELDS and hasattr(instance.config, key):
            setattr(instance.config, key, value)
            applied[key] = value

    # Persist updated config to Firestore
    try:
        from postgres_store import update_bot_config
        await update_bot_config(bot_id, applied)
    except Exception as e:
        logger.warning(f"Failed to persist config update for {bot_id}: {e}")

    return {
        "status": "updated",
        "bot_id": bot_id,
        "applied": applied,
    }



@app.post("/fleet/bot/{bot_id}/ai/trigger")
async def fleet_trigger_ai(bot_id: str):
    """Manually trigger an AI Brain evolution cycle for a specific bot."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.ai_brain:
        raise HTTPException(status_code=400, detail="Bot has no AI Brain")
    instance.ai_brain.trigger_manual()
    return {"status": "triggered", "bot_id": bot_id}


@app.get("/fleet/bot/{bot_id}/ai/status")
async def fleet_get_ai_status(bot_id: str):
    """Get the current AI Brain status for a specific bot."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.ai_brain:
        raise HTTPException(status_code=400, detail="Bot has no AI Brain")
    return instance.ai_brain.get_status()


@app.get("/fleet/bot/{bot_id}/ai/decisions")
async def fleet_get_ai_decisions(bot_id: str, limit: int = 50):
    """Retrieve recent AI evolution decisions for a specific bot."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    try:
        import postgres_store
        if not postgres_store.is_initialized():
            return []
        decisions = await postgres_store.get_ai_decisions(bot_id, limit=limit)
        return decisions
    except (ImportError, Exception) as e:
        logger.warning(f"Failed to fetch AI decisions for {bot_id}: {e}")
        return []



# ════════════════════════════════════════════════════════
# MAS INTELLIGENCE ENDPOINTS
# ════════════════════════════════════════════════════════

@app.get("/fleet/bot/{bot_id}/deliberation")
async def fleet_get_deliberation(bot_id: str):
    """
    Returns the most recent deliberation result for a bot — all agent votes,
    quorum outcome, veto reasons, approved qty, and order urgency.
    This is the primary endpoint for the Situation Room dashboard.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.engine:
        raise HTTPException(status_code=404, detail="Bot has no active engine")

    deliberation = instance.engine.last_deliberation
    return {
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "regime": instance.engine.current_regime,
        "deliberation": deliberation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/bot/{bot_id}/agents/status")
async def fleet_get_agents_status(bot_id: str):
    """
    Returns the per-agent status for a bot's SubAgentPool —
    last vote, confidence, reasoning, and whether the agent vetoed.
    Powers the 6-card agent grid in the Situation Room dashboard.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    # Pull votes from last deliberation (stored on engine)
    deliberation = getattr(instance.engine, "last_deliberation", {}) if instance.engine else {}
    votes = deliberation.get("votes", [])

    # Build per-agent status cards
    agent_cards = []
    for v in votes:
        agent_cards.append({
            "agent": v.get("agent", "unknown"),
            "vote": v.get("vote", "HOLD"),
            "confidence": v.get("confidence", 0.0),
            "reasoning": v.get("reasoning", ""),
            "is_veto": v.get("vote") == "VETO",
            "latency_ms": v.get("latency_ms", 0),
        })

    # Augment with static metadata for agents not yet voted this tick
    known_agents = {c["agent"] for c in agent_cards}
    static_agents = [
        "watchman", "regime", "strategist", "sentiment", "risk_manager", "executioner"
    ]
    for a in static_agents:
        if a not in known_agents:
            agent_cards.append({
                "agent": a,
                "vote": "STANDBY",
                "confidence": 0.0,
                "reasoning": "Awaiting next tick.",
                "is_veto": False,
                "latency_ms": 0,
            })

    # Sort into canonical order
    order = {a: i for i, a in enumerate(static_agents)}
    agent_cards.sort(key=lambda c: order.get(c["agent"], 99))

    return {
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "regime": getattr(instance.engine, "current_regime", "UNKNOWN") if instance.engine else "UNKNOWN",
        "quorum_reached": deliberation.get("quorum_reached", False),
        "approved": deliberation.get("approved", False),
        "veto_issued": deliberation.get("veto_issued", False),
        "agents": agent_cards,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/bot/{bot_id}/regime")
async def fleet_get_regime(bot_id: str):
    """
    Returns current regime classification for a bot.
    Lightweight endpoint polled by the Regime Architect card.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    regime = getattr(instance.engine, "current_regime", "UNKNOWN") if instance.engine else "UNKNOWN"
    return {
        "bot_id": bot_id,
        "regime": regime,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════
# PHASE 3 §5.3 — REST API GAP CLOSURES
# ════════════════════════════════════════════════════════

@app.get("/fleet/bot/{bot_id}/deliberation/history")
async def fleet_get_deliberation_history(bot_id: str, limit: int = 20):
    """
    Returns the recent deliberation audit trail for a bot.

    Reads from `strategy_contexts` (JSONB) — every TradeDecision produced by
    SubAgentPool.deliberate() is persisted there via _persist_deliberation()
    (Phase 3 §5.3). Both approved and rejected deliberations are stored.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not _db_is_initialized():
        raise HTTPException(status_code=503, detail="Database not initialised")
    limit = max(1, min(200, int(limit)))
    history = await get_store().get_ai_decisions(bot_id, limit=limit)
    # Filter for deliberation entries (some strategy_contexts rows are AI brain
    # decisions, which we want to exclude from the deliberation history view).
    deliberations = [h for h in history if h.get("_kind") == "deliberation"]
    return {
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "count": len(deliberations),
        "history": deliberations,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/bot/{bot_id}/agents/weights")
async def fleet_get_agent_weights(bot_id: str):
    """
    Returns the current Darwinian weights for a bot's panel agents.

    Excluded gate agents (watchman, ict, correlation, trend, regime,
    risk_manager) are NOT in this map — their weights are encoded directly
    on their AgentVote at vote time and are not Darwinian-adjusted.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.sub_agent_pool:
        raise HTTPException(status_code=404, detail="Bot has no sub-agent pool")
    weights = instance.sub_agent_pool._darwin.get_all_weights()
    return {
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "weights": weights,
        "bounds": {
            "floor": instance.sub_agent_pool._darwin.FLOOR,
            "ceiling": instance.sub_agent_pool._darwin.CEILING,
        },
        "excluded_agents": sorted(instance.sub_agent_pool._darwin.EXCLUDED),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class AgentWeightUpdate(BaseModel):
    agent: str = Field(..., description="Agent name (e.g. 'technical', 'macro')")
    weight: float = Field(..., ge=0.3, le=2.5, description="Weight in [FLOOR, CEILING]")


@app.put("/fleet/bot/{bot_id}/agents/weights")
async def fleet_set_agent_weight(bot_id: str, update: AgentWeightUpdate):
    """
    Operator override for a single agent's Darwinian weight.

    Clamps to [FLOOR, CEILING] and persists to Postgres. Returns 400 if the
    agent is in the excluded set (gate agents use fixed weights, not Darwin).
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.sub_agent_pool:
        raise HTTPException(status_code=404, detail="Bot has no sub-agent pool")
    try:
        new_w = instance.sub_agent_pool._darwin.set_weight(update.agent, update.weight)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "bot_id": bot_id,
        "agent": update.agent,
        "weight": new_w,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/bot/{bot_id}/research")
async def fleet_get_research(bot_id: str):
    """
    Returns the latest TradingAgents research framework signal for a bot.

    Combines the in-memory `latest_signals["research_framework"]` (used at
    deliberation time) with the cached PostgreSQL `research_reports` row
    (used by ResearchBridge for cross-bot sharing). Computes
    `next_refresh_in_seconds` from the bot's `research_interval_hours`.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    sig = None
    if instance.sub_agent_pool:
        sig_obj = instance.sub_agent_pool.latest_signals.get("research_framework")
        if sig_obj:
            sig = sig_obj.to_dict()

    last_updated = None
    next_refresh = None
    if _db_is_initialized():
        try:
            cached = await get_store().get_latest_research_report(instance.config.symbol)
            if cached:
                _payload, last_updated_dt = cached
                last_updated = last_updated_dt.isoformat() if last_updated_dt else None
                interval_s = instance.config.research_interval_hours * 3600
                elapsed = (datetime.now(last_updated_dt.tzinfo) - last_updated_dt).total_seconds()
                next_refresh = max(0, int(interval_s - elapsed))
        except Exception as e:
            logger.debug(f"research cache lookup failed for {bot_id}: {e}")

    return {
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "signal": sig,
        "last_updated": last_updated,
        "next_refresh_in_seconds": next_refresh,
        "interval_hours": instance.config.research_interval_hours,
        "research_enabled": instance.config.research_enabled,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/fleet/bot/{bot_id}/research/trigger")
async def fleet_trigger_research(bot_id: str):
    """
    Manually trigger a TradingAgents research cycle for a bot (Phase 3 §5.3).

    Returns 202 Accepted immediately; the research graph runs asynchronously
    in a thread (via `asyncio.to_thread` inside ResearchBridge). Result is
    pushed to `SubAgentPool.latest_signals["research_framework"]` on completion.
    """
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if not instance.config.research_enabled:
        raise HTTPException(
            status_code=400,
            detail="research_enabled=False — enable in config first."
        )
    # Reset the rate-limit timer so the regular monitor loop doesn't
    # double-trigger immediately after.
    fleet._last_symbol_research_times[instance.config.symbol] = time.time()
    asyncio.create_task(fleet._run_research_graph_async(instance))
    logger.info(
        f"[{bot_id}] Research cycle manually triggered",
        extra={
            "event": "research_cycle_manual_trigger",
            "bot_id": bot_id,
            "symbol": instance.config.symbol,
        },
    )
    return {
        "status": "triggered",
        "bot_id": bot_id,
        "symbol": instance.config.symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/metrics/system")
async def fleet_metrics_system():
    """
    Unified system metrics endpoint (Phase 3 §5.3).

    Combines: Gemini budget status, event loop latency probe, PostgreSQL
    connection pool size, active bot count, and CPU/RAM. Designed as the
    single GET for dashboards that need a snapshot of backend health.
    """
    from gemini_budget import gemini_budget as _gb

    # Event loop latency probe — sleep(0) yields control once; the delta
    # measures how long the loop took to resume us.
    _t0 = asyncio.get_event_loop().time()
    await asyncio.sleep(0)
    loop_latency_ms = round((asyncio.get_event_loop().time() - _t0) * 1000, 2)

    # DB pool stats (best-effort; asyncpg pool exposes .get_size() / .get_idle_size())
    db_size = 0
    db_idle = 0
    if _db_is_initialized():
        try:
            _store = get_store()
            _pool = getattr(_store, "pool", None)
            if _pool is not None:
                db_size = _pool.get_size() if hasattr(_pool, "get_size") else 0
                db_idle = _pool.get_idle_size() if hasattr(_pool, "get_idle_size") else 0
        except Exception:
            pass

    # CPU/RAM via psutil (best-effort)
    cpu_pct = 0.0
    ram_pct = 0.0
    try:
        import psutil
        cpu_pct = float(psutil.cpu_percent(interval=None))
        ram_pct = float(psutil.virtual_memory().percent)
    except Exception:
        pass

    return {
        "gemini": _gb.get_status(),
        "event_loop_latency_ms": loop_latency_ms,
        "db_pool": {"size": db_size, "idle": db_idle, "busy": max(0, db_size - db_idle)},
        "active_bots": len(fleet._bots),
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/fleet/config")
async def get_fleet_config():
    """Get current FleetConfig (portal-editable settings)."""
    return fleet.get_fleet_config()


@app.post("/fleet/config")
async def update_fleet_config(update: FleetConfigUpdate):
    """Update FleetConfig. Saves to Firestore."""
    updates = update.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")
    try:
        result = fleet.update_fleet_config(updates)
        return {"status": "updated", "config": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ════════════════════════════════════════════════════════
# SAVANNA WIZARD — AI BOT GENERATION
# ════════════════════════════════════════════════════════

class WizardGenerateRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol e.g. SPY")
    category: str = Field(..., description="Asset category e.g. Equities")
    personality: str = Field(..., description="One of: elephant, buffalo, rhino, leopard, lion")
    strategy: Optional[str] = Field("combined", description="Optional strategy override")


# Fallback presets when LLM is unavailable
_WIZARD_PRESETS = {
    "elephant": {
        "qty": 1, "stop_loss_pct": 0.4, "max_daily_drawdown_pct": 2.5,
        "bb_period": 25, "bb_std_dev": 2.8, "fib_entry_mode": "AND",
        "fib_bounce_threshold_pct": 0.30, "fib_lookback_bars": 70,
        "ai_interval_minutes": 90, "ai_min_trades_trigger": 15,
        "ai_loss_streak_trigger": 4, "agent_vote_cache_ttl_seconds": 2400,
        "sub_agents": ["sentiment", "macro", "earnings", "watchman", "risk_manager"],
        "strategy": "mean_reversion", "smart_routing_min_qty": 6, "twap_interval_ms": 600,
        "max_slippage_pct": 0.05,
    },
    "buffalo": {
        "qty": 2, "stop_loss_pct": 0.7, "max_daily_drawdown_pct": 4.0,
        "bb_period": 20, "bb_std_dev": 2.4, "fib_entry_mode": "AND",
        "fib_bounce_threshold_pct": 0.22, "fib_lookback_bars": 55,
        "ai_interval_minutes": 60, "ai_min_trades_trigger": 10,
        "ai_loss_streak_trigger": 3, "agent_vote_cache_ttl_seconds": 1800,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "combined", "smart_routing_min_qty": 5, "twap_interval_ms": 500,
        "max_slippage_pct": 0.05,
    },
    "rhino": {
        "qty": 4, "stop_loss_pct": 1.0, "max_daily_drawdown_pct": 5.5,
        "bb_period": 18, "bb_std_dev": 2.1, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.18, "fib_lookback_bars": 45,
        "ai_interval_minutes": 45, "ai_min_trades_trigger": 8,
        "ai_loss_streak_trigger": 3, "agent_vote_cache_ttl_seconds": 1200,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "trend_following", "smart_routing_min_qty": 4, "twap_interval_ms": 400,
        "max_slippage_pct": 0.05,
    },
    "leopard": {
        "qty": 6, "stop_loss_pct": 1.3, "max_daily_drawdown_pct": 7.0,
        "bb_period": 15, "bb_std_dev": 1.9, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.14, "fib_lookback_bars": 38,
        "ai_interval_minutes": 30, "ai_min_trades_trigger": 6,
        "ai_loss_streak_trigger": 2, "agent_vote_cache_ttl_seconds": 900,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "mean_reversion", "smart_routing_min_qty": 3, "twap_interval_ms": 350,
        "max_slippage_pct": 0.05,
    },
    "lion": {
        "qty": 10, "stop_loss_pct": 1.8, "max_daily_drawdown_pct": 9.0,
        "bb_period": 12, "bb_std_dev": 1.7, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.10, "fib_lookback_bars": 30,
        "ai_interval_minutes": 20, "ai_min_trades_trigger": 5,
        "ai_loss_streak_trigger": 2, "agent_vote_cache_ttl_seconds": 600,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "combined", "smart_routing_min_qty": 3, "twap_interval_ms": 280,
        "max_slippage_pct": 0.05,
    },
}

_PERSONALITY_LABELS = {
    "elephant": "Patient Elephant",
    "buffalo": "Grazing Buffalo",
    "rhino": "Steady Rhino",
    "leopard": "Prowling Leopard",
    "lion": "Hungry Lion",
}


@app.post("/fleet/wizard/generate")
async def wizard_generate(req: WizardGenerateRequest):
    """
    AI-powered bot wizard: given a symbol + personality, calls Gemini Flash
    to produce a unique bot codename, lore description, and full BotConfig.
    Falls back to hardcoded presets if LLM is unavailable.
    """
    personality = req.personality.lower()
    if personality not in _WIZARD_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown personality: {personality}. Must be one of {list(_WIZARD_PRESETS.keys())}")

    preset = _WIZARD_PRESETS[personality]
    animal_label = _PERSONALITY_LABELS[personality]

    # --- Try Gemini Flash via OpenClaw ---
    llm_name = None
    llm_description = None
    llm_config_overrides = {}

    try:
        from openai import OpenAI as _OpenAI
        from config import config as _cfg

        openclaw_url = _cfg.OPENCLAW_BASE_URL if hasattr(_cfg, "OPENCLAW_BASE_URL") else os.getenv("OPENCLAW_BASE_URL", "")
        openclaw_token = _cfg.OPENCLAW_TOKEN if hasattr(_cfg, "OPENCLAW_TOKEN") else os.getenv("OPENCLAW_TOKEN", "")
        openclaw_model = os.getenv("OPENCLAW_MODEL", "google/gemini-flash-latest")

        if openclaw_url and openclaw_token:
            client = _OpenAI(base_url=f"{openclaw_url}/v1", api_key=openclaw_token)

            system_prompt = (
                "You are TradeClaw's AI Naming System. You create dramatic, evocative trading bot identities "
                "themed around African wildlife. Your output must be a valid JSON object only — no markdown, no prose."
            )

            user_prompt = f"""
Create a bot identity for:
- Symbol: {req.symbol}
- Market category: {req.category}
- Spirit animal: {animal_label}
- Risk tier: {personality}
- Hunting Strategy: {req.strategy}

Return ONLY this JSON (no extra text):
{{
  "name": "<African-animal-inspired codename, max 4 words, include the symbol or a market noun>",
  "description": "<2 vivid sentences about how this bot hunts the market, written in the voice of a wildlife documentary narrator. Reference the animal behaviour.>",
  "config_tweaks": {{
    "fib_active_levels_raw": "<comma-separated Fibonacci levels as string, e.g. '38.2,50.0,61.8'>"
  }}
}}

Rules:
- Name examples: "Iron Elephant SPY", "Phantom Leopard QQQ", "Thunder Rhino BTC", "Crimson Lion NVDA"
- Name must feel premium and dangerous
- Description must be exactly 2 sentences
"""
            response = client.chat.completions.create(
                model=openclaw_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=300,
                temperature=0.85,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if model adds them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            llm_name = parsed.get("name")
            llm_description = parsed.get("description")
            llm_config_overrides = parsed.get("config_tweaks", {})
            logger.info(f"[Wizard] LLM generated name='{llm_name}' for {req.symbol}/{personality}")
    except Exception as e:
        logger.warning(f"[Wizard] LLM generation failed ({e}), using fallback preset")

    # --- Fallback names if LLM unavailable ---
    if not llm_name:
        fallback_names = {
            "elephant": f"Iron Elephant {req.symbol}",
            "buffalo": f"Silent Buffalo {req.symbol}",
            "rhino": f"Charging Rhino {req.symbol}",
            "leopard": f"Phantom Leopard {req.symbol}",
            "lion": f"Crimson Lion {req.symbol}",
        }
        fallback_descs = {
            "elephant": f"This bot moves through {req.category} markets with the slow, unstoppable force of the {animal_label}. It conserves capital like a herd protects its young — never rushing, always preserving.",
            "buffalo": f"The {animal_label} grazes {req.symbol} with disciplined patience, striking only when the herd confirms momentum. Strength through discipline; losses are culled before they compound.",
            "rhino": f"Armoured and deliberate, this bot charges {req.symbol} only when its horn of momentum aligns with the terrain. When the Rhino moves, it commits fully — dust trails behind.",
            "leopard": f"Silent and invisible until the perfect moment, this bot stalks {req.symbol} from the shadows of Fibonacci levels. When it strikes, precision makes the kill swift.",
            "lion": f"Apex mode — no mercy. This bot treats {req.symbol} as its territory and defends it with full agent activation and maximum aggression. The pride never retreats.",
        }
        llm_name = fallback_names[personality]
        llm_description = fallback_descs[personality]

    # Merge preset + any LLM config overrides
    final_config = {**preset, **llm_config_overrides}
    if "fib_active_levels_raw" not in final_config:
        fib_defaults = {
            "elephant": "23.6,38.2,50.0,61.8",
            "buffalo": "23.6,38.2,50.0,61.8",
            "rhino": "38.2,50.0,61.8",
            "leopard": "38.2,50.0,61.8",
            "lion": "50.0,61.8",
        }
        final_config["fib_active_levels_raw"] = fib_defaults[personality]

    if req.strategy:
        final_config["strategy"] = req.strategy

    final_config.update({
        "symbol": req.symbol,
        "name": llm_name,
        "fib_enabled": True,
        "ai_brain_enabled": True,
        "tags": [req.category.lower(), personality, "mas", "wizard"],
        "status": "DEPLOYMENT_READY",
    })

    return {
        "name": llm_name,
        "description": llm_description,
        "personality": personality,
        "animal": animal_label,
        "symbol": req.symbol,
        "category": req.category,
        "config": final_config,
        "ai_generated": llm_name is not None,
    }


# ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Live push endpoint for the dashboard.
    The backend broadcasts state every 500ms via ws_broadcast_loop().
    """
    await manager.connect(ws, channel="global")
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        manager.disconnect(ws, channel="global")
    except Exception:
        manager.disconnect(ws, channel="global")


@app.websocket("/ws/bot/{bot_id}")
async def bot_websocket_endpoint(ws: WebSocket, bot_id: str):
    """
    Per-bot stream for the Situation Room.
    Powers the 6-agent grid and real-time reasoning feed.
    """
    channel = f"bot-{bot_id}"
    await manager.connect(ws, channel=channel)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        manager.disconnect(ws, channel=channel)
    except Exception:
        manager.disconnect(ws, channel=channel)



@app.get("/health")
async def health():
    """Comprehensive health check — reports subsystem connectivity and fleet status."""
    import time as _time
    _start = _time.monotonic()

    result = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mt5_connected": False,
        "postgres_connected": False,
        "gemini_budget_remaining_pct": 0,
        "ollama_reachable": False,
        "active_bots": 0,
        "uptime_seconds": 0,
    }

    # MT5 connectivity
    try:
        from mt5_bridge import mt5
        acc = mt5.account_info()
        result["mt5_connected"] = acc is not None
    except Exception:
        pass

    # PostgreSQL connectivity
    try:
        from postgres_store import is_initialized
        result["postgres_connected"] = is_initialized()
    except Exception:
        pass

    # Gemini budget
    try:
        from bot_ai_brain import gemini_budget
        stats = gemini_budget.get_stats() if hasattr(gemini_budget, "get_stats") else {}
        if stats:
            remaining = stats.get("remaining_pct", 100)
            result["gemini_budget_remaining_pct"] = remaining
        else:
            result["gemini_budget_remaining_pct"] = 100 if gemini_budget.can_call() else 0
    except Exception:
        pass

    # Ollama reachability
    try:
        import httpx
        from config import config as sys_config
        base = sys_config.ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        resp = httpx.get(f"{base}/api/tags", timeout=3.0)
        result["ollama_reachable"] = resp.status_code == 200
    except Exception:
        pass

    # Fleet status
    try:
        fleet_snap = fleet.get_fleet_status().get("summary", {})
        result["active_bots"] = fleet_snap.get("total_bots", 0)
    except Exception:
        pass

    # Determine overall status
    critical_down = not result["postgres_connected"]
    result["status"] = "degraded" if critical_down else "healthy"
    result["latency_ms"] = round((_time.monotonic() - _start) * 1000, 1)

    return result



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
