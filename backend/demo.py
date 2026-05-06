"""
TradeClaw Demo Data Generator
Produces realistic-looking price action with mean-reverting tendencies
for testing and visualization when markets are closed.
"""

import math
import random
import time
from datetime import datetime, timedelta

import numpy as np

from models import SignalType


class DemoDataGenerator:
    """
    Generates synthetic OHLCV data with a random walk that has
    mean-reverting properties. Simulates buy/sell execution.
    """

    def __init__(
        self,
        symbol: str = "SPY",
        starting_price: float = 450.0,
        starting_equity: float = 100000.0,
        volatility: float = 0.0015,
    ):
        self.symbol = symbol
        self.price = starting_price
        self.equity = starting_equity
        self.starting_equity = starting_equity
        self.daily_pnl = 0.0
        self.volatility = volatility

        # Position tracking
        self.position_qty = 0
        self.position_side = None
        self.entry_price = 0.0
        self.unrealized_pnl = 0.0

        # Generate initial history
        self._price_buffer: list[dict] = []
        self._bb_buffer: list[dict] = []
        self._tick_count = 0

        # Pre-generate some history
        self._generate_initial_history(bars=100)

    def _generate_initial_history(self, bars: int = 100):
        """Create a backlog of price data for chart display."""
        base_time = datetime.utcnow() - timedelta(minutes=bars)
        prices = [self.price]

        for i in range(bars):
            # Random walk with slight mean reversion
            drift = -0.0001 * (prices[-1] - self.price)  # Pull back to base
            noise = random.gauss(0, self.volatility * self.price)
            new_price = prices[-1] + drift * prices[-1] + noise
            new_price = max(new_price, self.price * 0.9)  # Floor
            prices.append(new_price)

        # Build OHLCV bars
        for i in range(1, len(prices)):
            t = base_time + timedelta(minutes=i)
            p = prices[i]
            high = p * (1 + random.uniform(0, 0.002))
            low = p * (1 - random.uniform(0, 0.002))
            open_p = prices[i - 1] + random.gauss(0, self.volatility * p * 0.3)

            self._price_buffer.append(
                {
                    "time": t.strftime("%Y-%m-%dT%H:%M:%S"),
                    "open": round(open_p, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(p, 2),
                }
            )

        self.price = prices[-1]
        self._recompute_bollinger(20, 2.0)

    def _recompute_bollinger(self, period: int, std_dev: float):
        """Recompute Bollinger Bands from price buffer."""
        closes = [b["close"] for b in self._price_buffer]
        self._bb_buffer = []

        for i in range(len(closes)):
            if i < period - 1:
                self._bb_buffer.append(
                    {
                        "time": self._price_buffer[i]["time"],
                        "upper": closes[i],
                        "middle": closes[i],
                        "lower": closes[i],
                    }
                )
            else:
                window = closes[i - period + 1 : i + 1]
                sma = sum(window) / len(window)
                std = float(np.std(window))
                self._bb_buffer.append(
                    {
                        "time": self._price_buffer[i]["time"],
                        "upper": round(sma + std_dev * std, 2),
                        "middle": round(sma, 2),
                        "lower": round(sma - std_dev * std, 2),
                    }
                )

    def tick(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        stop_loss_pct: float = 1.0,
    ) -> dict:
        """
        Advance one tick. Returns the current state and any trade signals.
        """
        self._tick_count += 1

        # Generate new price with mean-reverting random walk
        mean_price = self._price_buffer[0]["close"] if self._price_buffer else self.price
        reversion_force = -0.00005 * (self.price - mean_price)

        # Add some cyclical behavior for visual interest
        cycle = math.sin(self._tick_count * 0.05) * self.volatility * self.price * 0.3
        noise = random.gauss(0, self.volatility * self.price)

        new_price = self.price + reversion_force * self.price + noise + cycle
        new_price = max(new_price, self.price * 0.95)  # Safety floor
        new_price = round(new_price, 2)

        # Create OHLCV candle
        high = round(max(self.price, new_price) * (1 + random.uniform(0, 0.001)), 2)
        low = round(min(self.price, new_price) * (1 - random.uniform(0, 0.001)), 2)
        open_p = round(self.price + random.gauss(0, self.volatility * self.price * 0.2), 2)

        now = datetime.utcnow()
        candle = {
            "time": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "open": open_p,
            "high": high,
            "low": low,
            "close": new_price,
        }

        self._price_buffer.append(candle)
        # Keep buffer bounded
        if len(self._price_buffer) > 300:
            self._price_buffer = self._price_buffer[-300:]

        self.price = new_price
        self._recompute_bollinger(bb_period, bb_std)

        # ---- SIGNAL LOGIC ----
        signal = SignalType.HOLD
        marker = None
        trade = None
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S")

        if len(self._bb_buffer) >= bb_period:
            latest_bb = self._bb_buffer[-1]
            upper = latest_bb["upper"]
            lower = latest_bb["lower"]

            # Stop loss check
            if self.position_qty > 0 and self.entry_price > 0:
                if self.position_side == "long":
                    loss_pct = ((new_price - self.entry_price) / self.entry_price) * 100
                    if loss_pct <= -stop_loss_pct:
                        signal = SignalType.STOP_LOSS

            if signal == SignalType.HOLD:
                if new_price <= lower and self.position_qty == 0:
                    signal = SignalType.BUY
                elif new_price >= upper and self.position_qty > 0:
                    signal = SignalType.SELL

            # Execute signals
            if signal == SignalType.BUY:
                self.position_qty = 10  # Demo qty
                self.position_side = "long"
                self.entry_price = new_price
                marker = {
                    "time": now_str,
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "arrowUp",
                    "text": "BUY",
                }
                trade = {
                    "timestamp": now_str,
                    "side": "BUY",
                    "symbol": self.symbol,
                    "qty": 10,
                    "price": new_price,
                    "pnl": 0.0,
                    "signal": "BUY",
                }

            elif signal in (SignalType.SELL, SignalType.STOP_LOSS):
                if self.position_qty > 0:
                    trade_pnl = round(
                        (new_price - self.entry_price) * self.position_qty, 2
                    )
                    self.daily_pnl += trade_pnl
                    self.equity += trade_pnl
                    label = "SELL" if signal == SignalType.SELL else "STOP"
                    marker = {
                        "time": now_str,
                        "position": "aboveBar",
                        "color": "#ef4444",
                        "shape": "arrowDown",
                        "text": label,
                    }
                    trade = {
                        "timestamp": now_str,
                        "side": "SELL",
                        "symbol": self.symbol,
                        "qty": self.position_qty,
                        "price": new_price,
                        "pnl": trade_pnl,
                        "signal": str(signal),
                    }
                    self.position_qty = 0
                    self.position_side = None
                    self.entry_price = 0.0

        # Calculate unrealized P&L
        if self.position_qty > 0 and self.entry_price > 0:
            self.unrealized_pnl = round(
                (new_price - self.entry_price) * self.position_qty, 2
            )
        else:
            self.unrealized_pnl = 0.0

        return {
            "price": new_price,
            "equity": round(self.equity, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "position_qty": self.position_qty,
            "position_side": self.position_side,
            "entry_price": self.entry_price,
            "unrealized_pnl": self.unrealized_pnl,
            "signal": signal,
            "marker": marker,
            "trade": trade,
            "price_history": self._price_buffer.copy(),
            "bollinger_data": self._bb_buffer.copy(),
        }
