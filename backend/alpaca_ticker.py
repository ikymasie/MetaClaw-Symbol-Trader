"""
TradeClaw — AlpacaTickerManager
================================
Manages a single authenticated Alpaca WebSocket connection to the IEX
real-time market data feed. Handles per-symbol subscription/unsubscription
and fans incoming bar events out to per-symbol asyncio queues.

Usage (from main.py):
    from alpaca_ticker import alpaca_ticker
    await alpaca_ticker.subscribe("SPY", queue)
    await alpaca_ticker.unsubscribe("SPY", queue)
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("tradeclaw.alpaca_ticker")

# Alpaca market data WebSocket URL (IEX = free paper trading feed)
ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"


class AlpacaTickerManager:
    """
    Singleton that maintains one Alpaca data stream connection.
    Clients subscribe to a symbol and receive bar events via asyncio.Queue.
    """

    def __init__(self):
        self._api_key: str = ""
        self._secret_key: str = ""

        # symbol → list of subscriber queues
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

        # Active subscribed symbols (sent to Alpaca)
        self._subscribed_symbols: set = set()

        # WebSocket connection
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Pause flag — when True, data is received but NOT fanned out
        self._paused = False

        # Stats
        self._messages_received: int = 0
        self._messages_fanout: int = 0
        self._messages_dropped: int = 0

    # ── Initialise ────────────────────────────────────────────────────────

    def init(self, api_key: str, secret_key: str):
        """Load credentials and start the connection loop."""
        self._api_key = api_key
        self._secret_key = secret_key
        logger.info("[AlpacaTicker] Initialized with credentials")

    def start(self):
        """Kick off the background connection + listener task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="alpaca-ticker")
        logger.info("[AlpacaTicker] Started background task")

    def stop(self):
        """Signal the loop to exit."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("[AlpacaTicker] Stopped")

    def pause(self):
        """Pause data fan-out. WS stays alive but subscribers get no data."""
        self._paused = True
        logger.info("[AlpacaTicker] PAUSED — data fan-out suspended")

    def resume(self):
        """Resume data fan-out to subscribers."""
        self._paused = False
        logger.info("[AlpacaTicker] RESUMED — data fan-out active")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def get_stats(self) -> dict:
        """Return runtime stats for monitoring."""
        total_queues = sum(len(qs) for qs in self._subscribers.values())
        return {
            "paused": self._paused,
            "running": self._running,
            "connected": self._ws is not None,
            "subscribed_symbols": list(self._subscribed_symbols),
            "total_subscribers": total_queues,
            "messages_received": self._messages_received,
            "messages_fanout": self._messages_fanout,
            "messages_dropped": self._messages_dropped,
        }

    # ── Public subscription API ───────────────────────────────────────────

    async def subscribe(self, symbol: str, queue: asyncio.Queue):
        """
        Register a subscriber queue for the given symbol.
        If this is the first subscriber for this symbol, sends a WS subscribe
        message to Alpaca.
        """
        symbol = symbol.upper()
        async with self._lock:
            if symbol not in self._subscribers:
                self._subscribers[symbol] = []
            self._subscribers[symbol].append(queue)

            # Tell Alpaca to start sending bars for this symbol
            if symbol not in self._subscribed_symbols:
                self._subscribed_symbols.add(symbol)
                await self._send_subscribe([symbol])

        logger.info(f"[AlpacaTicker] Subscribed {symbol} (total queues: {len(self._subscribers[symbol])})")

    async def unsubscribe(self, symbol: str, queue: asyncio.Queue):
        """Remove a subscriber queue. Unsubscribes from Alpaca when last subscriber leaves."""
        symbol = symbol.upper()
        async with self._lock:
            if symbol in self._subscribers:
                try:
                    self._subscribers[symbol].remove(queue)
                except ValueError:
                    pass

                # If no more subscribers, stop the Alpaca feed for this symbol
                if not self._subscribers[symbol]:
                    del self._subscribers[symbol]
                    self._subscribed_symbols.discard(symbol)
                    await self._send_unsubscribe([symbol])
                    logger.info(f"[AlpacaTicker] Unsubscribed {symbol} from Alpaca")

    def get_subscribed_symbols(self) -> list[str]:
        """Return list of currently subscribed symbols."""
        return list(self._subscribed_symbols)

    # ── Internal Alpaca WS loop ───────────────────────────────────────────

    async def _run_loop(self):
        """Connect to Alpaca, authenticate, subscribe, and listen forever. Reconnects on error."""
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(ALPACA_WS_URL, ping_interval=20) as ws:
                    self._ws = ws
                    backoff = 1.0  # reset on successful connect
                    logger.info("[AlpacaTicker] Connected to Alpaca WS")

                    # Step 1: Receive welcome
                    welcome = await ws.recv()
                    logger.debug(f"[AlpacaTicker] Welcome: {welcome}")

                    # Step 2: Authenticate
                    await ws.send(json.dumps({
                        "action": "auth",
                        "key": self._api_key,
                        "secret": self._secret_key,
                    }))
                    auth_resp = await ws.recv()
                    auth_data = json.loads(auth_resp)
                    if isinstance(auth_data, list) and auth_data[0].get("T") == "success":
                        logger.info("[AlpacaTicker] Authenticated successfully")
                    else:
                        logger.error(f"[AlpacaTicker] Auth failed: {auth_data}")
                        await asyncio.sleep(5)
                        continue

                    # Step 3: Re-subscribe to any symbols that were active before reconnect
                    async with self._lock:
                        active_symbols = list(self._subscribed_symbols)
                    if active_symbols:
                        await self._send_subscribe(active_symbols)

                    # Step 4: Listen for bar events
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw_msg)

            except ConnectionClosed as e:
                logger.warning(f"[AlpacaTicker] WS closed: {e} — reconnecting in {backoff}s")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AlpacaTicker] Error: {e} — reconnecting in {backoff}s")

            self._ws = None
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _handle_message(self, raw_msg: str):
        """Parse a message from Alpaca and fan out bar events to subscribers."""
        try:
            messages = json.loads(raw_msg)
            if not isinstance(messages, list):
                return

            self._messages_received += 1

            # When paused, consume the WS data but do NOT fan out
            if self._paused:
                return

            for msg in messages:
                msg_type = msg.get("T")

                if msg_type == "b":  # Minute bar
                    symbol = msg.get("S", "")
                    bar = {
                        "time": msg.get("t"),        # ISO timestamp
                        "open": msg.get("o"),
                        "high": msg.get("h"),
                        "low": msg.get("l"),
                        "close": msg.get("c"),
                        "volume": msg.get("v"),
                        "symbol": symbol,
                    }
                    await self._fan_out(symbol, {"type": "bar", "bar": bar})

                elif msg_type == "q":  # Quote
                    symbol = msg.get("S", "")
                    quote = {
                        "bid": msg.get("bp"),
                        "ask": msg.get("ap"),
                        "bid_size": msg.get("bs"),
                        "ask_size": msg.get("as"),
                        "time": msg.get("t"),
                        "symbol": symbol,
                    }
                    await self._fan_out(symbol, {"type": "quote", "quote": quote})

                elif msg_type == "t":  # Trade print
                    symbol = msg.get("S", "")
                    trade = {
                        "price": msg.get("p"),
                        "size": msg.get("s"),
                        "time": msg.get("t"),
                        "symbol": symbol,
                    }
                    await self._fan_out(symbol, {"type": "trade_tick", "tick": trade})

                elif msg_type == "error":
                    logger.error(f"[AlpacaTicker] Error from Alpaca: {msg}")

        except Exception as e:
            logger.warning(f"[AlpacaTicker] Message parse error: {e}")

    async def _fan_out(self, symbol: str, payload: dict):
        """Send payload to all subscribers of a symbol."""
        async with self._lock:
            queues = list(self._subscribers.get(symbol.upper(), []))

        for q in queues:
            try:
                q.put_nowait(payload)
                self._messages_fanout += 1
            except asyncio.QueueFull:
                # Drop oldest item and push new one to keep queue fresh
                self._messages_dropped += 1
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass

    async def _send_subscribe(self, symbols: list[str]):
        """Send Alpaca subscribe request for bars + quotes on given symbols."""
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps({
                "action": "subscribe",
                "bars": symbols,
                "quotes": symbols,
                "trades": symbols,
            }))
            logger.info(f"[AlpacaTicker] Subscribed Alpaca bars for {symbols}")
        except Exception as e:
            logger.warning(f"[AlpacaTicker] Subscribe send failed: {e}")

    async def _send_unsubscribe(self, symbols: list[str]):
        """Send Alpaca unsubscribe request for given symbols."""
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps({
                "action": "unsubscribe",
                "bars": symbols,
                "quotes": symbols,
                "trades": symbols,
            }))
        except Exception as e:
            logger.warning(f"[AlpacaTicker] Unsubscribe send failed: {e}")


# ── Singleton ─────────────────────────────────────────────────────────────────

alpaca_ticker = AlpacaTickerManager()
