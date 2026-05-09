"""
TradeClaw — MT5Hub
==================
Polling-based market data and order hub for MetaTrader 5.
Replaces MT5StreamHub (mt5_hub.py) + MT5TickerManager (mt5_ticker.py).

Public interface intentionally mirrors both predecessors so callers need minimal changes:
  init(login, password, server)
  start() / stop() / pause() / resume() / get_stats()
  subscribe(symbol, queue) / unsubscribe(symbol, queue)   — async
  register_trading_callback(callback)

Live ticks sourced by polling mt5.symbol_info_tick() at POLL_INTERVAL_S.
OHLCV bars sourced by polling mt5.copy_rates_from_pos() at BAR_POLL_INTERVAL_S.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from mt5_bridge import mt5
from symbol_service import to_mt5_symbol

logger = logging.getLogger("tradeclaw.mt5_hub")

POLL_INTERVAL_S = 1.0        # tick poll cadence
BAR_POLL_INTERVAL_S = 5.0    # OHLCV bar poll cadence (less frequent)


class MT5Hub:
    """
    Single hub for all MT5 market data and account event distribution.
    Ensures EXACTLY ONE terminal connection shared across all bots.
    """

    def __init__(self):
        self._initialized: bool = False
        self._running: bool = False
        self._paused: bool = False

        # symbol → list of subscriber queues
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._sub_lock: Optional[asyncio.Lock] = None   # created lazily in async context

        # Trading update callbacks
        self._trading_callbacks: List[Callable[[Any], None]] = []

        # Stats (mirrors MT5TickerManager.get_stats() shape)
        self._stats: Dict[str, int] = {
            "messages_received": 0,
            "messages_fanned": 0,
            "messages_dropped": 0,
        }

        # Credentials
        self._login: int = 0
        self._password: str = ""
        self._server: str = ""

        self._tasks: List[asyncio.Task] = []

    # ── Init / Lifecycle ──────────────────────────────────────────────────────

    def init(
        self,
        login: int = 0,
        password: str = "",
        server: str = "",
    ) -> bool:
        """
        Connect to the running MT5 terminal and authenticate.
        Must be called before start(). Returns True on success.
        """
        self._login = login
        self._password = password
        self._server = server

        # Try connecting to an already running terminal first
        initialized = False
        for attempt in range(3):
            if mt5.initialize():
                initialized = True
                logger.info(f"[MT5Hub] mt5.initialize() successful on attempt {attempt + 1}")
                break
            else:
                logger.warning(f"[MT5Hub] mt5.initialize() failed on attempt {attempt + 1}: {mt5.last_error()}")
                # Fallback to explicit path if first attempt fails
                terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
                if mt5.initialize(path=terminal_path):
                    initialized = True
                    logger.info(f"[MT5Hub] mt5.initialize(path=...) successful on attempt {attempt + 1}")
                    break
                time.sleep(5)
        
        if not initialized:
            logger.error(f"[MT5Hub] All mt5.initialize() attempts failed. Last error: {mt5.last_error()}")
            return False

        if login:
            max_retries = 3
            for attempt in range(max_retries):
                if mt5.login(login, password=password, server=server):
                    logger.info(f"[MT5Hub] Login successful on attempt {attempt + 1}")
                    break
                else:
                    err = mt5.last_error()
                    logger.warning(f"[MT5Hub] Login attempt {attempt + 1} failed: {err}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
            else:
                logger.error(f"[MT5Hub] All login attempts failed. Last error: {mt5.last_error()}")
                mt5.shutdown()
                return False

        self._initialized = True
        info = mt5.terminal_info()
        logger.info(
            f"[MT5Hub] Connected to MT5 terminal "
            f"(build={getattr(info, 'build', '?')}, connected={getattr(info, 'connected', '?')})"
        )
        return True

    def start(self):
        """Schedule polling loops on the running event loop. Call after init()."""
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._sub_lock = asyncio.Lock()
        self._tasks.append(loop.create_task(self._tick_poll_loop()))
        self._tasks.append(loop.create_task(self._bar_poll_loop()))
        logger.info("[MT5Hub] Polling loops started")

    def stop(self):
        """Cancel polling loops and disconnect from terminal."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        if self._initialized:
            mt5.shutdown()
            self._initialized = False
        logger.info("[MT5Hub] Stopped")

    def pause(self):
        """Pause tick fan-out (market data still polled, but not forwarded)."""
        self._paused = True
        logger.info("[MT5Hub] Paused")

    def resume(self):
        """Resume tick fan-out."""
        self._paused = False
        logger.info("[MT5Hub] Resumed")

    def get_stats(self) -> dict:
        return dict(self._stats)

    # ── Market Data API ───────────────────────────────────────────────────────

    async def subscribe(self, symbol: str, queue: asyncio.Queue):
        """Subscribe a queue to market data for symbol."""
        symbol = symbol.upper()
        async with self._sub_lock:
            if symbol not in self._subscribers:
                self._subscribers[symbol] = []
                if self._initialized:
                    broker_sym = to_mt5_symbol(symbol)
                    mt5.symbol_select(broker_sym, True)
                logger.info(f"[MT5Hub] Subscribed to {symbol} (MT5: {to_mt5_symbol(symbol)})")
            if queue not in self._subscribers[symbol]:
                self._subscribers[symbol].append(queue)

    async def unsubscribe(self, symbol: str, queue: asyncio.Queue):
        """Remove a subscriber queue for symbol."""
        symbol = symbol.upper()
        async with self._sub_lock:
            if symbol in self._subscribers:
                try:
                    self._subscribers[symbol].remove(queue)
                except ValueError:
                    pass
                if not self._subscribers[symbol]:
                    del self._subscribers[symbol]
                    logger.info(f"[MT5Hub] All subscribers left for {symbol}")

    # Aliases kept for call-site compatibility with MT5StreamHub
    async def subscribe_market(self, symbol: str, queue: asyncio.Queue):
        await self.subscribe(symbol, queue)

    async def unsubscribe_market(self, symbol: str, queue: asyncio.Queue):
        await self.unsubscribe(symbol, queue)

    def get_all_symbols(self) -> List[dict]:
        """Return all available symbols from the MT5 terminal."""
        if not self._initialized:
            return []
        
        symbols = mt5.symbols_get()
        if symbols is None:
            return []
            
        result = []
        for s in symbols:
            result.append({
                "name": s.name,
                "path": s.path,
                "description": s.description,
                "digits": getattr(s, "digits", 0),
                "spread": getattr(s, "spread", 0),
                "trade_mode": getattr(s, "trade_mode", 0),
                "volume_min": getattr(s, "volume_min", 0.01) or 0.01,
                "volume_max": getattr(s, "volume_max", 100.0) or 100.0,
                "volume_step": getattr(s, "volume_step", 0.01) or 0.01,
            })
        return result

    def register_trading_callback(self, callback: Callable[[Any], None]):
        if callback not in self._trading_callbacks:
            self._trading_callbacks.append(callback)

    # ── Polling Loops ─────────────────────────────────────────────────────────

    async def _tick_poll_loop(self):
        """Poll MT5 for latest tick on every subscribed symbol."""
        while self._running:
            try:
                if self._initialized and not self._paused:
                    async with self._sub_lock:
                        symbols = list(self._subscribers.keys())

                    for symbol in symbols:
                        broker_sym = to_mt5_symbol(symbol)
                        tick = mt5.symbol_info_tick(broker_sym)
                        if tick is None:
                            continue

                        self._stats["messages_received"] += 1
                        payload = {
                            "type": "quote",
                            "symbol": symbol,
                            "bid": tick.bid,
                            "ask": tick.ask,
                            "last": tick.last,
                            "volume": tick.volume,
                            "time": datetime.fromtimestamp(
                                tick.time, tz=timezone.utc
                            ).isoformat(),
                        }
                        await self._fan_out(symbol, payload)

            except Exception as e:
                logger.error(f"[MT5Hub] Tick poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL_S)

    async def _bar_poll_loop(self):
        """Poll MT5 for latest completed 1-min bar on every subscribed symbol."""
        while self._running:
            try:
                if self._initialized and not self._paused:
                    async with self._sub_lock:
                        symbols = list(self._subscribers.keys())

                    for symbol in symbols:
                        # position=0 → latest bar (may be incomplete); 1 → last closed bar
                        broker_sym = to_mt5_symbol(symbol)
                        rates = mt5.copy_rates_from_pos(broker_sym, mt5.TIMEFRAME_M1, 0, 1)
                        if rates is None or len(rates) == 0:
                            continue

                        bar = rates[0]
                        payload = {
                            "type": "bar",
                            "symbol": symbol,
                            "open": float(bar["open"]),
                            "high": float(bar["high"]),
                            "low": float(bar["low"]),
                            "close": float(bar["close"]),
                            "volume": float(bar["tick_volume"]),
                            "time": datetime.fromtimestamp(
                                int(bar["time"]), tz=timezone.utc
                            ).isoformat(),
                        }
                        await self._fan_out(symbol, payload)

            except Exception as e:
                logger.error(f"[MT5Hub] Bar poll error: {e}")

            await asyncio.sleep(BAR_POLL_INTERVAL_S)

    def get_recent_news(self, symbol: str) -> List[dict]:  # noqa: ARG002
        """MT5 does not provide news; returns empty list so callers fall through to web search."""
        return []

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fan_out(self, symbol: str, payload: dict):
        async with self._sub_lock:
            queues = list(self._subscribers.get(symbol.upper(), []))

        for q in queues:
            try:
                q.put_nowait(payload)
                self._stats["messages_fanned"] += 1
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    self._stats["messages_dropped"] += 1


# Singleton — imported as `mt5_hub` everywhere
mt5_hub = MT5Hub()
