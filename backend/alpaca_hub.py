"""
TradeClaw — AlpacaStreamHub
===========================
The central nervous system for Alpaca data. 
Maintains EXACTLY ONE connection to:
1. Alpaca Stock Market Data Stream (IEX/SIP)
2. Alpaca Crypto Market Data Stream
3. Alpaca Trading Stream (Account/Trade Updates)

Distributes events reactively to BotEngines and FleetOrchestrator.
Eliminates redundant REST polling and fixed the "406 Connection Limit" error.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from alpaca.data.live import StockDataStream, CryptoDataStream, NewsDataStream
from alpaca.trading.stream import TradingStream
from alpaca.data.models import Bar, Quote, Trade
from alpaca.data.models import News
from collections import deque

logger = logging.getLogger("tradeclaw.alpaca_hub")

class AlpacaStreamHub:
    """
    Unified hub for all Alpaca streaming data.
    Ensures EXACTLY ONE connection per stream type.
    """

    def __init__(self):
        self._api_key: str = ""
        self._secret_key: str = ""
        
        # Streams
        self._stock_stream: Optional[StockDataStream] = None
        self._crypto_stream: Optional[CryptoDataStream] = None
        self._news_stream: Optional[NewsDataStream] = None
        self._trading_stream: Optional[TradingStream] = None
        
        # symbol -> list of subscriber queues
        self._market_subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._market_lock = asyncio.Lock()

        # News buffer: symbol -> deque[News]
        self._news_buffer: Dict[str, deque] = {}
        self._buffer_lock = asyncio.Lock()
        
        # Global callbacks for trading updates
        self._trading_callbacks: List[Callable[[Any], None]] = []
        
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def init(self, api_key: str, secret_key: str):
        """Configure credentials and initialize stream clients."""
        self._api_key = api_key
        self._secret_key = secret_key
        
        # Initialize the Alpaca-py stream clients
        # StockDataStream defaults to IEX for Free / SIP for Pro
        self._stock_stream = StockDataStream(api_key, secret_key)
        self._crypto_stream = CryptoDataStream(api_key, secret_key)
        self._news_stream = NewsDataStream(api_key, secret_key)
        self._trading_stream = TradingStream(api_key, secret_key, paper=True)
        
        logger.info("[AlpacaHub] Initialized Stock, Crypto, News, and Trading clients")

    async def start(self):
        """Start the streaming loops."""
        if self._running:
            return
        self._running = True
        
        # Start loops
        self._tasks.append(asyncio.create_task(self._run_trading_stream(), name="hub-trading"))
        self._tasks.append(asyncio.create_task(self._run_stock_stream(), name="hub-stock"))
        self._tasks.append(asyncio.create_task(self._run_crypto_stream(), name="hub-crypto"))
        self._tasks.append(asyncio.create_task(self._run_news_stream(), name="hub-news"))
        
        logger.info("[AlpacaHub] All stream tasks started")

    async def stop(self):
        """Stop all streams gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("[AlpacaHub] Stopped")

    # ── Market Data API ───────────────────────────────────────────────────

    async def subscribe_market(self, symbol: str, queue: asyncio.Queue):
        """Subscribe a queue to market data for a symbol (auto-detects type)."""
        symbol = symbol.upper()
        async with self._market_lock:
            if symbol not in self._market_subscribers:
                self._market_subscribers[symbol] = []
                
                # Determine which stream to use
                if self._is_crypto(symbol):
                    self._crypto_stream.subscribe_bars(self._handle_bar, symbol)
                    logger.info(f"[AlpacaHub] Subscribed CRYPTO feed for {symbol}")
                else:
                    self._stock_stream.subscribe_bars(self._handle_bar, symbol)
                    self._stock_stream.subscribe_quotes(self._handle_quote, symbol)
                    # Also subscribe to news for this symbol
                    self._news_stream.subscribe_news(self._handle_news, symbol)
                    logger.info(f"[AlpacaHub] Subscribed STOCK & NEWS feed for {symbol}")
            
            if queue not in self._market_subscribers[symbol]:
                self._market_subscribers[symbol].append(queue)
        
        logger.debug(f"[AlpacaHub] Added subscriber for {symbol}")

    async def unsubscribe_market(self, symbol: str, queue: asyncio.Queue):
        """Remove a subscriber queue."""
        symbol = symbol.upper()
        async with self._market_lock:
            if symbol in self._market_subscribers:
                try:
                    self._market_subscribers[symbol].remove(queue)
                except ValueError:
                    pass
                
                if not self._market_subscribers[symbol]:
                    del self._market_subscribers[symbol]
                    # We keep the physical Alpaca subscription alive to avoid reconnection overhead
                    # unless we want to implement a more complex unsubscription logic.
                    logger.info(f"[AlpacaHub] All subscribers left for {symbol}")

    # ── News Buffer API ───────────────────────────────────────────────────

    def get_recent_news(self, symbol: str) -> List[dict]:
        """Retrieve the latest headlines from the buffer for a symbol."""
        symbol = symbol.upper()
        if symbol not in self._news_buffer:
            return []
        
        # We don't need a lock for reading list(deque) usually, but it's safer
        return [
            {
                "headline": n.headline,
                "summary": n.summary,
                "timestamp": n.updated_at.isoformat() if hasattr(n, 'updated_at') else n.created_at.isoformat(),
                "source": n.source,
                "url": n.url
            }
            for n in list(self._news_buffer[symbol])
        ]

    def register_trading_callback(self, callback: Callable[[Any], None]):
        """Register a callback for account/trade updates (synchronous)."""
        if callback not in self._trading_callbacks:
            self._trading_callbacks.append(callback)

    # ── Internal Handlers ─────────────────────────────────────────────────

    def _is_crypto(self, symbol: str) -> bool:
        """Heuristic to detect crypto pairs."""
        if "/" in symbol: return True
        # Common crypto suffixes
        for s in ["USD", "USDT", "BTC", "ETH"]:
            if symbol.endswith(s) and len(symbol) >= 6:
                return True
        return False

    async def _handle_bar(self, bar: Bar):
        """Fan out bar events."""
        payload = {
            "type": "bar",
            "symbol": bar.symbol,
            "close": bar.close,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "volume": bar.volume,
            "time": bar.timestamp.isoformat()
        }
        await self._fan_out(bar.symbol, payload)

    async def _handle_quote(self, quote: Quote):
        """Fan out quote events."""
        payload = {
            "type": "quote",
            "symbol": quote.symbol,
            "bid": quote.bid_price,
            "ask": quote.ask_price,
            "time": quote.timestamp.isoformat()
        }
        await self._fan_out(quote.symbol, payload)

    async def _handle_news(self, news: News):
        """Buffer incoming news item."""
        # A news item might have multiple symbols
        targets = news.symbols if hasattr(news, 'symbols') else []
        
        async with self._buffer_lock:
            for sym in targets:
                sym = sym.upper()
                if sym not in self._news_buffer:
                    self._news_buffer[sym] = deque(maxlen=20)
                self._news_buffer[sym].append(news)
        
        logger.debug(f"[AlpacaHub] Buffered news for {targets}: {news.headline}")

    async def _fan_out(self, symbol: str, payload: dict):
        """Broadcast payload to all subscribers of a symbol."""
        async with self._market_lock:
            queues = list(self._market_subscribers.get(symbol.upper(), []))
        
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except:
                    pass

    # ── Loop Tasks ────────────────────────────────────────────────────────

    async def _run_stock_stream(self):
        backoff = 1.0
        while self._running:
            try:
                await self._stock_stream._run_forever()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[AlpacaHub] Stock Stream Exception: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_crypto_stream(self):
        backoff = 1.0
        while self._running:
            try:
                await self._crypto_stream._run_forever()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[AlpacaHub] Crypto Stream Exception: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_trading_stream(self):
        self._trading_stream.subscribe_trade_updates(self._handle_trade_update)
        backoff = 1.0
        while self._running:
            try:
                await self._trading_stream._run_forever()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[AlpacaHub] Trading Stream Exception: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_news_stream(self):
        backoff = 1.0
        while self._running:
            try:
                await self._news_stream._run_forever()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[AlpacaHub] News Stream Exception: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

# Singleton Instance
alpaca_hub = AlpacaStreamHub()
