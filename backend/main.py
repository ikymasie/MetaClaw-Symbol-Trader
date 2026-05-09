"""
TradeClaw — FastAPI Application
REST API wrapping the Mean Reversion Execution Engine.
Fleet-aware: multi-bot orchestration via /fleet/* endpoints.
"""

import asyncio
import json
import logging
import os
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
from firebase_store import (
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
from strategy import engine
from ai_brain import ai_brain
from vital_signs import vital_signs
from symbol_service import symbol_service, to_mt5_symbol

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
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
        sockets = list(self.active.get(channel, []))
        if not sockets:
            return

        async def _send(ws):
            try:
                await ws.send_text(data)
                return None
            except Exception:
                return ws

        # Dispatch all sends concurrently
        results = await asyncio.gather(*(_send(ws) for ws in sockets))

        # Collect and remove dead sockets
        dead = [ws for ws in results if ws is not None]
        for ws in dead:
            self.disconnect(ws, channel)

    async def purge_stale(self):
        """Probe every active socket with a ping; evict those that don't respond.
        Should be called periodically (e.g. every 60 s) to reclaim memory from
        browser tabs that closed without sending a proper WebSocket close frame.
        """
        # Collect unique WebSockets and their associated channels
        ws_to_channels: dict[WebSocket, list[str]] = {}
        for channel, sockets in self.active.items():
            for ws in sockets:
                if ws not in ws_to_channels:
                    ws_to_channels[ws] = []
                ws_to_channels[ws].append(channel)

        if not ws_to_channels:
            return

        async def _ping(ws, channels):
            try:
                await ws.send_text('{"type":"ping"}')
                return None
            except Exception:
                return (ws, channels)

        # Dispatch all pings concurrently across all unique WebSockets
        results = await asyncio.gather(*(_ping(ws, channels) for ws, channels in ws_to_channels.items()))

        evicted_total = 0
        for res in results:
            if res:
                ws, channels = res
                for channel in channels:
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


# ---- DB Flush Background Task ----
async def db_flush_loop():
    """Periodically flush the engine's DB write queue to SQLite."""
    while True:
        try:
            queue = engine.flush_db_queue()
            for item in queue:
                if item["type"] == "trade":
                    await insert_trade(
                        timestamp=item["timestamp"],
                        side=item["side"],
                        symbol=item["symbol"],
                        qty=item["qty"],
                        price=item["price"],
                        pnl=item.get("pnl", 0.0),
                        signal=item.get("signal", ""),
                        params_snapshot=item.get("params_snapshot", ""),
                        fib_level_triggered=item.get("fib_level_triggered"),
                    )
                elif item["type"] == "equity":
                    await insert_equity_snapshot(
                        timestamp=item["timestamp"],
                        equity=item["equity"],
                        daily_pnl=item.get("daily_pnl", 0.0),
                    )
        except Exception as e:
            logger.error(f"DB flush error: {e}")
        await asyncio.sleep(2)


# ---- WebSocket Broadcast Loop ----
async def ws_broadcast_loop():
    """
    Runs every 500ms — builds a full state snapshot and pushes it
    to every connected WebSocket client. Replaces frontend polling.
    Skips when paused or when no global channel subscribers exist.
    Runs stale-connection purge every 60 seconds.
    """
    _purge_counter = 0
    while True:
        try:
            _purge_counter += 1
            # Purge stale connections every 60 s (120 × 500ms ticks)
            if _purge_counter >= 120:
                await manager.purge_stale()
                _purge_counter = 0

            if not _streaming_paused and "global" in manager.active and manager.active["global"]:
                state = engine.get_state_snapshot()
                cfg = config.snapshot()
                stats = await get_trade_stats_today()

                starting_eq = state["starting_equity"] or cfg.get("starting_equity", 100000)
                daily_pnl_pct = 0.0
                daily_drawdown_pct = 0.0
                if starting_eq > 0:
                    daily_pnl_pct = (state["daily_pnl"] / starting_eq) * 100
                    if state["daily_pnl"] < 0:
                        daily_drawdown_pct = abs(daily_pnl_pct)

                # Copy live chart data under lock — release before building payload
                with engine._lock:
                    price_history = list(engine.price_history)
                    markers = list(engine.markers)
                    bollinger = list(engine.bollinger_data)

                # Payload assembly happens outside the engine lock
                payload = {
                    "type": "state",
                    "status": {
                        "bot_status": state["bot_status"],
                        "current_price": state["current_price"],
                        "position_qty": state["position_qty"],
                        "position_side": state["position_side"],
                        "entry_price": state["entry_price"],
                        "equity": state["equity"],
                        "daily_pnl": state["daily_pnl"],
                        "daily_pnl_pct": round(daily_pnl_pct, 2),
                        "daily_drawdown_pct": round(daily_drawdown_pct, 2),
                        "unrealized_pnl": state["unrealized_pnl"],
                        "starting_equity": starting_eq,
                        "last_signal": state["last_signal"],
                        "total_trades_today": stats["total_trades"],
                        "win_rate": round(stats["win_rate"], 1),
                        "config": cfg,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": state["message"],
                    },
                    "vitals": vital_signs.get_status(),
                    "chart": {
                        "price_data": price_history[-300:],
                        "bollinger": bollinger[-300:],
                        "markers": markers[-100:],
                    },
                    "fib_signal": state.get("fib_signal", {}),
                    # MAS intelligence fields — consumed by the Situation Room
                    "regime": state.get("regime", "UNKNOWN"),
                    "mas_deliberation": state.get("last_deliberation", {}),
                }
                await manager.broadcast(payload, channel="global")
        except Exception as e:
            logger.error(f"[WS] Global broadcast error: {e}")
        await asyncio.sleep(0.5)


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
    name: str = "Unnamed Bot"
    symbol: str = Field(..., description="Target trading symbol")
    strategy: str = "mean_reversion"
    capital_allocation: float = Field(default=10000.0, ge=1.0)
    description: str = ""
    personality: str = ""
    animal: str = ""
    category: str = ""
    ai_generated: bool = False
    demo_mode: bool = True
    qty: float = Field(default=1.0, gt=0)
    stop_loss_pct: float = Field(default=1.5, ge=0.25, le=5.0)
    max_daily_drawdown_pct: float = Field(default=6.0, ge=0.5, le=25.0)
    bb_period: int = Field(default=20, ge=8, le=100)
    bb_std_dev: float = Field(default=2.0, ge=1.0, le=3.5)
    ai_brain_enabled: bool = True
    ai_interval_minutes: int = 60
    ai_min_trades_trigger: int = 10
    ai_loss_streak_trigger: int = 3
    sub_agents: list[str] = Field(default=["sentiment", "macro", "earnings", "technical"])
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
    max_slippage_pct: float = 0.30
    limit_timeout_s: int = 10
    auto_start: bool = True


class FleetConfigUpdate(BaseModel):
    max_bots: Optional[int] = Field(default=None, ge=1, le=50)
    # global_demo_mode DEPRECATED
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
    await init_db()

    # Init Firebase
    try:
        import firebase_store
        # Resolve the service account key relative to this file's location
        _backend_dir = os.path.dirname(os.path.abspath(__file__))
        _sa_candidates = [
            os.path.join(_backend_dir, "service-account-key.json"),
            os.path.join(_backend_dir, "..", "service-account-key.json"),
        ]
        _sa_path = next((p for p in _sa_candidates if os.path.exists(p)), None)
        if _sa_path:
            logger.info(f"Using service account: {os.path.abspath(_sa_path)}")
        else:
            logger.warning("No service-account-key.json found — falling back to ADC")

        firebase_store.init_firebase(
            service_account_path=_sa_path,
        )
        fleet.set_firebase_store(firebase_store)
        await fleet.load_config_from_firebase()
        await fleet.restore_bots_from_firebase()
        logger.info("Firebase connected, fleet config and bots loaded")
    except Exception as e:
        logger.warning(f"Firebase init skipped (running without it): {e}")

    # Publish the running event loop to sub_agents so background threads
    # can schedule async Firestore calls (DarwinianWeightStore, LangGraph graph).
    try:
        import sub_agents as _sa
        _sa.set_main_event_loop(asyncio.get_running_loop())
    except Exception as _e:
        logger.warning(f"Could not set main event loop in sub_agents: {_e}")

    # Start fleet monitor
    fleet.start_monitor()

    # Check for prior CRITICAL_STOP state
    prior_state = await get_bot_state("last_status")
    if prior_state == "CRITICAL_STOP":
        engine._status = BotStatus.CRITICAL_STOP
        engine._message = "Prior session ended with CRITICAL_STOP. Reset manually."
        logger.warning("Restored CRITICAL_STOP state from prior session")

    # Start background tasks
    flush_task = asyncio.create_task(db_flush_loop())
    broadcast_task = asyncio.create_task(ws_broadcast_loop())
    fleet_broadcast_task = asyncio.create_task(ws_fleet_broadcast_loop())

    # Start AI Brain if enabled
    if config.ai_snapshot()["ai_brain_enabled"]:
        ai_brain.start()

    # Start MT5 Hub (market data)
    mt5_hub.init(
        login=int(os.getenv("MT5_LOGIN", "0") or "0"),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", ""),
    )
    mt5_hub.start()

    logger.info("TradeClaw ready")

    yield

    # Shutdown
    logger.info("TradeClaw shutting down...")
    fleet.stop_monitor()
    mt5_hub.stop()
    if ai_brain.enabled:
        ai_brain.stop()
    flush_task.cancel()
    broadcast_task.cancel()
    fleet_broadcast_task.cancel()
    if engine.status == BotStatus.RUNNING:
        engine.stop()
    await set_bot_state("last_status", engine.status.value)
    logger.info("TradeClaw shutdown complete")


# ---- App ----
app = FastAPI(
    title="TradeClaw Execution Engine",
    description="Multi-Agent System (MAS) trading platform — 6 expert agents, quorum deliberation, smart order routing.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Endpoints ----

@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current bot status, price, equity, and risk metrics."""
    state = engine.get_state_snapshot()
    cfg = config.snapshot()
    stats = await get_trade_stats_today()

    daily_drawdown_pct = 0.0
    daily_pnl_pct = 0.0
    starting_eq = state["starting_equity"] or cfg.get("starting_equity", 100000)

    if starting_eq > 0:
        daily_pnl_pct = (state["daily_pnl"] / starting_eq) * 100
        if state["daily_pnl"] < 0:
            daily_drawdown_pct = abs(daily_pnl_pct)

    return StatusResponse(
        bot_status=state["bot_status"],
        current_price=state["current_price"],
        position_qty=state["position_qty"],
        position_side=state["position_side"],
        entry_price=state["entry_price"],
        equity=state["equity"],
        daily_pnl=state["daily_pnl"],
        daily_pnl_pct=round(daily_pnl_pct, 2),
        daily_drawdown_pct=round(daily_drawdown_pct, 2),
        unrealized_pnl=state["unrealized_pnl"],
        starting_equity=starting_eq,
        last_signal=state["last_signal"],
        total_trades_today=stats["total_trades"],
        win_rate=round(stats["win_rate"], 1),
        config=ConfigSnapshot(**cfg),
        timestamp=datetime.now(timezone.utc).isoformat(),
        message=state["message"],
    )


@app.post("/start")
async def start_bot(request: StartRequest = StartRequest()):
    """Start the execution engine."""
    if engine.status == BotStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Bot is already running")

    if engine.status == BotStatus.CRITICAL_STOP:
        # Allow restart after critical stop — reset state
        engine._status = BotStatus.IDLE
        engine._message = ""
        engine.daily_pnl = 0.0
        await set_bot_state("last_status", "IDLE")

    engine.start(demo_mode=request.demo_mode)
    mode = "DEMO" if request.demo_mode else "LIVE"
    logger.info(f"Bot started in {mode} mode")
    return {"status": "started", "mode": mode}


@app.post("/stop")
async def stop_bot():
    """Stop the execution engine gracefully."""
    if engine.status not in (BotStatus.RUNNING, BotStatus.STARTING):
        raise HTTPException(status_code=400, detail="Bot is not running")

    engine.stop()
    await set_bot_state("last_status", "IDLE")
    logger.info("Bot stopped via API")
    return {"status": "stopped"}


@app.get("/history", response_model=HistoryResponse)
async def get_history():
    """Get trade history, equity curve, price data, and chart markers."""
    # DB trades
    db_trades = await get_all_trades(limit=100)
    trades = [
        TradeRecord(
            id=t["id"],
            timestamp=t["timestamp"],
            side=t["side"],
            symbol=t["symbol"],
            qty=t["qty"],
            price=t["price"],
            pnl=t["pnl"],
            signal=t["signal"],
        )
        for t in db_trades
    ]

    # DB equity
    db_equity = await get_equity_history(limit=500)
    equity_curve = [
        EquityPoint(
            time=e["timestamp"],
            equity=e["equity"],
            daily_pnl=e["daily_pnl"],
        )
        for e in db_equity
    ]

    # Live data from engine
    with engine._lock:
        price_data = [PricePoint(**p) for p in engine.price_history]
        markers = [MarkerPoint(**m) for m in engine.markers]
        bollinger = [BollingerData(**b) for b in engine.bollinger_data]

        # Merge in-memory equity if not yet flushed
        for eq in engine.equity_curve:
            if not any(e.time == eq["time"] for e in equity_curve):
                equity_curve.append(
                    EquityPoint(
                        time=eq["time"],
                        equity=eq["equity"],
                        daily_pnl=eq.get("daily_pnl", 0.0),
                    )
                )

    return HistoryResponse(
        trades=trades,
        equity_curve=equity_curve,
        price_data=price_data,
        markers=markers,
        bollinger=bollinger,
    )


@app.post("/config")
async def update_config(update: ConfigUpdate):
    """Update trading configuration at runtime."""
    updates = update.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No config values provided")

    config.update(**updates)
    logger.info(f"Config updated: {updates}")
    return {"status": "updated", "config": config.snapshot()}


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
        for _, row in df.iterrows():
            ts = row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"])
            price_data.append({
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
            bollinger.append({
                "time": ts,
                "upper": float(row["upper_bb"]),
                "middle": float(row["sma"]),
                "lower": float(row["lower_bb"]),
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
            name=request.name,
            symbol=request.symbol,
            strategy=request.strategy,
            capital_allocation=request.capital_allocation,
            description=request.description,
            personality=request.personality,
            animal=request.animal,
            category=request.category,
            ai_generated=request.ai_generated,
            demo_mode=request.demo_mode,
            qty=request.qty,
            stop_loss_pct=request.stop_loss_pct,
            max_daily_drawdown_pct=request.max_daily_drawdown_pct,
            bb_period=request.bb_period,
            bb_std_dev=request.bb_std_dev,
            ai_brain_enabled=request.ai_brain_enabled,
            ai_interval_minutes=request.ai_interval_minutes,
            ai_min_trades_trigger=request.ai_min_trades_trigger,
            ai_loss_streak_trigger=request.ai_loss_streak_trigger,
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
    """Get MT5 account summary (balance, equity, margin, etc.)."""
    try:
        from mt5_bridge import mt5
        acc = mt5.account_info()
        if acc is None:
            raise RuntimeError(f"MT5 account_info() returned None: {mt5.last_error()}")

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
            "currency": acc.currency,
            "status": "ACTIVE",
        }
    except Exception as e:
        logger.error(f"Failed to fetch MT5 account: {e}")
        raise HTTPException(status_code=500, detail="MT5 account sync failed")



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
    
    # Update demo mode if provided
    instance.config.demo_mode = request.demo_mode
    instance.engine.config.demo_mode = request.demo_mode
    
    instance.engine.start()
    return {"status": "started", "bot_id": bot_id, "demo_mode": request.demo_mode}


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
    """Update a bot's config (e.g. demo_mode, qty, stop_loss_pct)."""
    instance = fleet.get_bot(bot_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    ALLOWED_FIELDS = {
        "demo_mode", "qty", "stop_loss_pct", "bb_period", "bb_std_dev",
        "max_daily_drawdown_pct", "fib_enabled", "ai_brain_enabled",
        "ai_interval_minutes", "capital_allocation",
    }
    applied = {}
    for key, value in updates.items():
        if key in ALLOWED_FIELDS and hasattr(instance.config, key):
            setattr(instance.config, key, value)
            applied[key] = value

    # Persist updated config to Firestore
    try:
        from firebase_store import update_bot_config
        await update_bot_config(bot_id, applied)
    except Exception as e:
        logger.warning(f"Failed to persist config update for {bot_id}: {e}")

    return {
        "status": "updated",
        "bot_id": bot_id,
        "applied": applied,
        "demo_mode": instance.config.demo_mode,
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
        import firebase_store
        if not firebase_store.is_initialized():
            return []
        decisions = await firebase_store.get_ai_decisions(bot_id, limit=limit)
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
        "max_slippage_pct": 0.35,
    },
    "buffalo": {
        "qty": 2, "stop_loss_pct": 0.7, "max_daily_drawdown_pct": 4.0,
        "bb_period": 20, "bb_std_dev": 2.4, "fib_entry_mode": "AND",
        "fib_bounce_threshold_pct": 0.22, "fib_lookback_bars": 55,
        "ai_interval_minutes": 60, "ai_min_trades_trigger": 10,
        "ai_loss_streak_trigger": 3, "agent_vote_cache_ttl_seconds": 1800,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "combined", "smart_routing_min_qty": 5, "twap_interval_ms": 500,
        "max_slippage_pct": 0.30,
    },
    "rhino": {
        "qty": 4, "stop_loss_pct": 1.0, "max_daily_drawdown_pct": 5.5,
        "bb_period": 18, "bb_std_dev": 2.1, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.18, "fib_lookback_bars": 45,
        "ai_interval_minutes": 45, "ai_min_trades_trigger": 8,
        "ai_loss_streak_trigger": 3, "agent_vote_cache_ttl_seconds": 1200,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "trend_following", "smart_routing_min_qty": 4, "twap_interval_ms": 400,
        "max_slippage_pct": 0.28,
    },
    "leopard": {
        "qty": 6, "stop_loss_pct": 1.3, "max_daily_drawdown_pct": 7.0,
        "bb_period": 15, "bb_std_dev": 1.9, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.14, "fib_lookback_bars": 38,
        "ai_interval_minutes": 30, "ai_min_trades_trigger": 6,
        "ai_loss_streak_trigger": 2, "agent_vote_cache_ttl_seconds": 900,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "mean_reversion", "smart_routing_min_qty": 3, "twap_interval_ms": 350,
        "max_slippage_pct": 0.26,
    },
    "lion": {
        "qty": 10, "stop_loss_pct": 1.8, "max_daily_drawdown_pct": 9.0,
        "bb_period": 12, "bb_std_dev": 1.7, "fib_entry_mode": "OR",
        "fib_bounce_threshold_pct": 0.10, "fib_lookback_bars": 30,
        "ai_interval_minutes": 20, "ai_min_trades_trigger": 5,
        "ai_loss_streak_trigger": 2, "agent_vote_cache_ttl_seconds": 600,
        "sub_agents": ["sentiment", "macro", "earnings", "technical", "watchman", "risk_manager"],
        "strategy": "combined", "smart_routing_min_qty": 3, "twap_interval_ms": 280,
        "max_slippage_pct": 0.22,
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
        "demo_mode": True,
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



# ════════════════════════════════════════════════════════
# REALTIME TICKER ENDPOINTS
# ════════════════════════════════════════════════════════

@app.get("/ticker/symbols")
async def ticker_symbols():
    """
    Return list of unique symbols across all deployed bots.
    Powers the BotSwitcherStrip so the frontend knows which symbols/bots to offer.
    """
    bots_data = fleet.get_fleet_status()["bots"]
    symbols_seen = set()
    result = []
    for bot in bots_data:
        sym = bot.get("symbol", "")
        if sym and sym not in symbols_seen:
            symbols_seen.add(sym)
        result.append({
            "bot_id": bot["bot_id"],
            "name": bot["name"],
            "symbol": sym,
            "strategy": bot.get("strategy", ""),
            "demo_mode": bot.get("demo_mode", True),
            "tags": bot.get("tags", []),
            "bot_status": bot.get("status", {}).get("bot_status", "IDLE"),
            "daily_pnl": bot.get("status", {}).get("daily_pnl", 0.0),
            "equity": bot.get("status", {}).get("equity", 0.0),
            "current_price": bot.get("status", {}).get("current_price", 0.0),
            "position_qty": bot.get("status", {}).get("position_qty", 0),
            "position_side": bot.get("status", {}).get("position_side", ""),
            "unrealized_pnl": bot.get("status", {}).get("unrealized_pnl", 0.0),
        })
    return {"bots": result}


@app.websocket("/ws/ticker/{symbol}")
async def websocket_ticker(ws: WebSocket, symbol: str):
    """
    Per-symbol realtime market data stream.
    - Subscribes to MT5 bars/quotes for the requested symbol
    - Joins bot state for any fleet bots trading that symbol
    - Broadcasts { type, bar | quote | tick, bots } to the client
    Client sends 'ping' for keepalive; server replies 'pong'.
    """
    await ws.accept()
    symbol = symbol.upper()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    await mt5_hub.subscribe(symbol, queue)
    logger.info(f"[TickerWS] Client connected for {symbol}")

    async def _send_loop():
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                # Enrich with bot context for this symbol
                bots_context = _get_bots_for_symbol(symbol)
                payload["bots"] = bots_context
                await ws.send_text(json.dumps(payload, default=str))
            except asyncio.TimeoutError:
                # No bar for 25s — send keepalive so client knows we're alive
                await ws.send_text(json.dumps({"type": "keepalive", "symbol": symbol}))
            except Exception:
                break

    send_task = asyncio.create_task(_send_loop())

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                if msg == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        send_task.cancel()
        await mt5_hub.unsubscribe(symbol, queue)
        logger.info(f"[TickerWS] Client disconnected from {symbol}")


def _get_bots_for_symbol(symbol: str) -> list[dict]:
    """Return lightweight state snapshots for all bots trading the given symbol."""
    result = []
    for instance in fleet.list_bots():
        if instance.config.symbol.upper() != symbol.upper():
            continue
        try:
            state = instance.engine.get_state_snapshot() if instance.engine else {}
            result.append({
                "bot_id": instance.bot_id,
                "name": instance.config.name,
                "bot_status": state.get("bot_status", "IDLE"),
                "current_price": state.get("current_price", 0.0),
                "daily_pnl": state.get("daily_pnl", 0.0),
                "equity": state.get("equity", 0.0),
                "position_qty": state.get("position_qty", 0),
                "position_side": state.get("position_side", ""),
                "entry_price": state.get("entry_price", 0.0),
                "unrealized_pnl": state.get("unrealized_pnl", 0.0),
                "last_signal": state.get("last_signal", ""),
                # Bollinger bands (last data point only — chart overlay)
                "bollinger_last": _get_last_bollinger(instance),
                # Recent trade markers for chart overlay
                "markers": _get_recent_markers(instance),
            })
        except Exception:
            pass
    return result


def _get_last_bollinger(instance) -> dict:
    """Return the latest Bollinger Band values from an engine instance."""
    try:
        if instance.engine and instance.engine.bollinger_data:
            with instance.engine._lock:
                last = list(instance.engine.bollinger_data)[-1]
            return last
    except Exception:
        pass
    return {}


def _get_recent_markers(instance, limit: int = 50) -> list[dict]:
    """Return the most recent trade markers from an engine instance."""
    try:
        if instance.engine and instance.engine.markers:
            with instance.engine._lock:
                return list(instance.engine.markers)[-limit:]
    except Exception:
        pass
    return []


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
