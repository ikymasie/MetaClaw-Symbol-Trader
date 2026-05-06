"""
TradeClaw — Executioner Agent (Smart Order Routing)
=====================================================
The Executioner is the ONLY agent that submits orders to the broker.
No other component should call the Alpaca trading client directly.

Order routing strategy:
  ┌─────────────────────────────────────────────────────────────────┐
  │  urgency=HIGH  or  qty < smart_routing_min_qty  →  MARKET order │
  │  urgency=LOW   and qty < smart_routing_min_qty  →  LIMIT order  │
  │                    qty ≥ smart_routing_min_qty  →  TWAP slices  │
  └─────────────────────────────────────────────────────────────────┘

Slippage guard:
  After each fill, compare fill price vs. signal price.
  If slippage > max_slippage_pct, abort remaining child orders and
  log a SLIPPAGE_ABORT event.

Latency monitor:
  Log round-trip time from signal to final fill.
  Warn if > 2 seconds.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("tradeclaw.executioner")


# ── Order routing modes ────────────────────────────────────────────────────

class OrderUrgency(str, Enum):
    HIGH = "HIGH"   # Market order — fill immediately
    LOW  = "LOW"    # Limit order with improvement target, then fallback


class ExecutionMode(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    TWAP   = "TWAP"


# ── Result dataclasses ─────────────────────────────────────────────────────

@dataclass
class ChildFill:
    """Represents one slice fill in a TWAP execution."""
    slice_index: int
    qty: int
    fill_price: float
    slippage_pct: float
    timestamp: str


@dataclass
class ExecutionResult:
    """
    Final result returned by ExecutionerAgent.execute().
    A single result may cover multiple TWAP child orders.
    """
    success: bool
    mode: str                            # MARKET | LIMIT | TWAP
    symbol: str
    side: str
    total_qty_requested: int
    total_qty_filled: int
    avg_fill_price: float
    signal_price: float
    total_slippage_pct: float
    latency_ms: float
    fills: list = field(default_factory=list)
    abort_reason: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "mode": self.mode,
            "symbol": self.symbol,
            "side": self.side,
            "total_qty_requested": self.total_qty_requested,
            "total_qty_filled": self.total_qty_filled,
            "avg_fill_price": self.avg_fill_price,
            "signal_price": self.signal_price,
            "total_slippage_pct": self.total_slippage_pct,
            "latency_ms": self.latency_ms,
            "fills": self.fills,
            "abort_reason": self.abort_reason,
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ── ExecutionerAgent ───────────────────────────────────────────────────────

class ExecutionerAgent:
    """
    Smart Order Routing agent.

    Usage:
        executioner = ExecutionerAgent(
            bot_id="bot-abc",
            trading_client=alpaca_trading_client,
            smart_routing_min_qty=3,
            twap_interval_ms=500,
            max_slippage_pct=0.30,
            limit_timeout_s=10,
        )
        result = executioner.execute(
            symbol="SPY",
            side="buy",
            qty=5,
            signal_price=450.00,
            urgency=OrderUrgency.LOW,
        )
    """

    # Maximum TWAP child slices
    MAX_TWAP_SLICES: int = 10

    # Latency alert threshold (ms)
    LATENCY_WARN_MS: float = 2000.0

    def __init__(
        self,
        bot_id: str,
        trading_client,
        smart_routing_min_qty: int = 3,
        twap_interval_ms: int = 500,
        max_slippage_pct: float = 0.30,
        limit_timeout_s: int = 10,
    ):
        self.bot_id = bot_id
        self._client = trading_client
        self.smart_routing_min_qty = smart_routing_min_qty
        self.twap_interval_ms = twap_interval_ms
        self.max_slippage_pct = max_slippage_pct
        self.limit_timeout_s = limit_timeout_s
        self._logger = logging.getLogger(f"tradeclaw.executioner[{bot_id}]")

    # ── Public API ─────────────────────────────────────────────────────────

    def execute(
        self,
        symbol: str,
        side: str,          # "buy" | "sell"
        qty: int,
        signal_price: float,
        urgency: OrderUrgency = OrderUrgency.LOW,
    ) -> ExecutionResult:
        """
        Route and execute an order. Returns a filled ExecutionResult.
        This is a BLOCKING call — it waits for fills or timeouts.
        Should be called from a background thread (bot_engine loop).
        """
        start_ms = time.monotonic() * 1000

        mode = self._select_mode(qty, urgency)
        self._logger.info(
            f"[{self.bot_id}] Executing {side.upper()} {qty}×{symbol} "
            f"via {mode} | signal_price={signal_price:.4f} | urgency={urgency}"
        )

        try:
            if mode == ExecutionMode.MARKET:
                result = self._execute_market(symbol, side, qty, signal_price)
            elif mode == ExecutionMode.LIMIT:
                result = self._execute_limit(symbol, side, qty, signal_price)
            else:
                result = self._execute_twap(symbol, side, qty, signal_price)
        except Exception as e:
            self._logger.exception(f"Execution error: {e}")
            elapsed = time.monotonic() * 1000 - start_ms
            return ExecutionResult(
                success=False,
                mode=mode,
                symbol=symbol,
                side=side,
                total_qty_requested=qty,
                total_qty_filled=0,
                avg_fill_price=0.0,
                signal_price=signal_price,
                total_slippage_pct=0.0,
                latency_ms=elapsed,
                error=str(e),
            )

        result.latency_ms = time.monotonic() * 1000 - start_ms

        if result.latency_ms > self.LATENCY_WARN_MS:
            self._logger.warning(
                f"[{self.bot_id}] HIGH LATENCY: {result.latency_ms:.0f}ms for "
                f"{side.upper()} {qty}×{symbol}"
            )

        self._logger.info(
            f"[{self.bot_id}] Fill complete: "
            f"filled={result.total_qty_filled}/{qty} "
            f"avg_price={result.avg_fill_price:.4f} "
            f"slippage={result.total_slippage_pct:.4f}% "
            f"latency={result.latency_ms:.0f}ms"
        )
        return result

    # ── Mode selection ─────────────────────────────────────────────────────

    def _select_mode(self, qty: int, urgency: OrderUrgency) -> ExecutionMode:
        if urgency == OrderUrgency.HIGH:
            return ExecutionMode.MARKET
        if qty >= self.smart_routing_min_qty:
            return ExecutionMode.TWAP
        return ExecutionMode.LIMIT

    # ── Market Order ───────────────────────────────────────────────────────

    def _execute_market(
        self, symbol: str, side: str, qty: int, signal_price: float
    ) -> ExecutionResult:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        # Normalise symbol for trading: GBPUSD=X -> GBPUSD
        trading_symbol = symbol.replace("=X", "").replace("/", "")
        
        req = MarketOrderRequest(
            symbol=trading_symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        fill_price = float(order.filled_avg_price or signal_price)
        slippage = self._calc_slippage(side, signal_price, fill_price)

        return ExecutionResult(
            success=True,
            mode=ExecutionMode.MARKET,
            symbol=symbol,
            side=side,
            total_qty_requested=qty,
            total_qty_filled=int(order.filled_qty or qty),
            avg_fill_price=fill_price,
            signal_price=signal_price,
            total_slippage_pct=slippage,
            latency_ms=0.0,
            fills=[ChildFill(0, qty, fill_price, slippage, datetime.now(timezone.utc).isoformat()).__dict__],
        )

    # ── Limit Order (with market fallback) ────────────────────────────────

    def _execute_limit(
        self, symbol: str, side: str, qty: int, signal_price: float
    ) -> ExecutionResult:
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        # Aim for 0.05% price improvement
        improvement = 0.0005
        if side == "buy":
            limit_price = round(signal_price * (1 - improvement), 2)
        else:
            limit_price = round(signal_price * (1 + improvement), 2)

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        # Normalise symbol for trading: GBPUSD=X -> GBPUSD
        trading_symbol = symbol.replace("=X", "").replace("/", "")

        req = LimitOrderRequest(
            symbol=trading_symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        )
        order = self._client.submit_order(req)
        order_id = order.id

        # Poll for fill or timeout
        deadline = time.monotonic() + self.limit_timeout_s
        while time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                order = self._client.get_order_by_id(order_id)
                if order.status in ("filled", "partially_filled"):
                    break
            except Exception as e:
                self._logger.warning(f"[{self.bot_id}] Limit order poll error: {e}")

        # Cancel and switch to market if unfilled
        if order.status not in ("filled", "partially_filled"):
            try:
                self._client.cancel_order_by_id(order_id)
            except Exception as e:
                self._logger.warning(f"[{self.bot_id}] Failed to cancel stale limit order {order_id}: {e}")
            self._logger.info(
                f"[{self.bot_id}] Limit order timed out after {self.limit_timeout_s}s. "
                f"Falling back to MARKET."
            )
            return self._execute_market(symbol, side, qty, signal_price)

        fill_price = float(order.filled_avg_price or limit_price)
        slippage = self._calc_slippage(side, signal_price, fill_price)

        return ExecutionResult(
            success=True,
            mode=ExecutionMode.LIMIT,
            symbol=symbol,
            side=side,
            total_qty_requested=qty,
            total_qty_filled=int(order.filled_qty or qty),
            avg_fill_price=fill_price,
            signal_price=signal_price,
            total_slippage_pct=slippage,
            latency_ms=0.0,
            fills=[ChildFill(0, qty, fill_price, slippage, datetime.now(timezone.utc).isoformat()).__dict__],
        )

    # ── TWAP Order ────────────────────────────────────────────────────────

    def _execute_twap(
        self, symbol: str, side: str, qty: int, signal_price: float
    ) -> ExecutionResult:
        """
        Split `qty` into N market-order slices, spaced `twap_interval_ms` apart.
        Aborts remaining slices if slippage on any fill exceeds max_slippage_pct.
        """
        n_slices = min(qty, self.MAX_TWAP_SLICES)
        base_qty, remainder = divmod(qty, n_slices)

        fills = []
        total_filled = 0
        total_cost = 0.0
        abort_reason = None

        for i in range(n_slices):
            slice_qty = base_qty + (1 if i == 0 and remainder > 0 else 0)
            if slice_qty == 0:
                continue

            try:
                slice_result = self._execute_market(symbol, side, slice_qty, signal_price)
                fill = ChildFill(
                    slice_index=i,
                    qty=slice_qty,
                    fill_price=slice_result.avg_fill_price,
                    slippage_pct=slice_result.total_slippage_pct,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                fills.append(fill.__dict__)
                total_filled += slice_qty
                total_cost += slice_result.avg_fill_price * slice_qty

                # Slippage guard — abort if deteriorating
                if abs(slice_result.total_slippage_pct) > self.max_slippage_pct:
                    abort_reason = (
                        f"TWAP SLIPPAGE_ABORT on slice {i}: "
                        f"slippage={slice_result.total_slippage_pct:.3f}% > "
                        f"limit={self.max_slippage_pct:.3f}%"
                    )
                    self._logger.warning(f"[{self.bot_id}] {abort_reason}")
                    break

            except Exception as e:
                self._logger.error(f"[{self.bot_id}] TWAP slice {i} failed: {e}")
                abort_reason = f"Slice {i} execution error: {e}"
                break

            # Pace between slices
            if i < n_slices - 1:
                time.sleep(self.twap_interval_ms / 1000.0)

        avg_fill = total_cost / total_filled if total_filled > 0 else 0.0
        total_slip = self._calc_slippage(side, signal_price, avg_fill) if avg_fill > 0 else 0.0

        return ExecutionResult(
            success=(total_filled > 0 and abort_reason is None),
            mode=ExecutionMode.TWAP,
            symbol=symbol,
            side=side,
            total_qty_requested=qty,
            total_qty_filled=total_filled,
            avg_fill_price=avg_fill,
            signal_price=signal_price,
            total_slippage_pct=total_slip,
            latency_ms=0.0,
            fills=fills,
            abort_reason=abort_reason,
        )

    # ── Utility ───────────────────────────────────────────────────────────

    @staticmethod
    def _calc_slippage(side: str, signal_price: float, fill_price: float) -> float:
        """
        Positive slippage = we paid MORE than expected (bad for buys).
        Negative slippage = we received MORE than expected (bad for sells).
        Returns as percentage (e.g. 0.12 means 0.12%).
        """
        if signal_price == 0:
            return 0.0
        if side == "buy":
            return ((fill_price - signal_price) / signal_price) * 100
        else:
            return ((signal_price - fill_price) / signal_price) * 100
