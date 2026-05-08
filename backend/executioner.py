"""
TradeClaw — Executioner Agent (Smart Order Routing)
=====================================================
The Executioner is the ONLY agent that submits orders to the broker.
No other component should call MetaTrader5 order functions directly.

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

MT5 notes:
  - mt5.order_send() is synchronous — no fill-polling needed.
  - Volume is in lots (0.01 = micro-lot). qty is converted via _to_lots().
  - Each bot gets a unique magic number (hash of bot_id) so positions
    can be filtered per-bot in mt5.positions_get(magic=...).
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from mt5_bridge import mt5
from symbol_service import to_mt5_symbol

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
    qty: float
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
    total_qty_requested: float
    total_qty_filled: float
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
    Smart Order Routing agent for MetaTrader 5.

    Usage:
        executioner = ExecutionerAgent(
            bot_id="bot-abc",
            symbol="EURUSD",
            smart_routing_min_qty=3,
            twap_interval_ms=500,
            max_slippage_pct=0.30,
            limit_timeout_s=10,
        )
        result = executioner.execute(
            side="buy",
            qty=2,          # treated as lot-count units; converted via _to_lots()
            signal_price=1.08500,
            urgency=OrderUrgency.LOW,
        )
    """

    MAX_TWAP_SLICES: int = 10
    LATENCY_WARN_MS: float = 2000.0

    def __init__(
        self,
        bot_id: str,
        symbol: str,
        smart_routing_min_qty: float = 3,
        twap_interval_ms: int = 500,
        max_slippage_pct: float = 0.30,
        limit_timeout_s: int = 10,
        # legacy param kept for call-site compatibility — ignored
        _trading_client=None,
    ):
        self.bot_id = bot_id
        # Convert symbol to broker-specific format immediately
        self.symbol = to_mt5_symbol(symbol)
        self.smart_routing_min_qty = smart_routing_min_qty
        self.twap_interval_ms = twap_interval_ms
        self.max_slippage_pct = max_slippage_pct
        self.limit_timeout_s = limit_timeout_s
        # Stable unique magic number per bot (MT5 uses this to identify EA orders)
        self._magic = abs(hash(bot_id)) % 2_147_483_647
        self._logger = logging.getLogger(f"tradeclaw.executioner[{bot_id}]")

    # ── Public API ─────────────────────────────────────────────────────────

    def execute(
        self,
        side: str,          # "buy" | "sell"
        qty: float,
        signal_price: float,
        urgency: OrderUrgency = OrderUrgency.LOW,
    ) -> ExecutionResult:
        """
        Route and execute an order. Returns a filled ExecutionResult.
        Blocking — waits for fills or timeouts. Call from background thread.
        """
        start_ms = time.monotonic() * 1000
        mode = self._select_mode(qty, urgency)
        self._logger.info(
            f"[{self.bot_id}] Executing {side.upper()} {qty}×{self.symbol} "
            f"via {mode} | signal_price={signal_price:.5f} | urgency={urgency}"
        )

        try:
            if mode == ExecutionMode.MARKET:
                result = self._execute_market(side, qty, signal_price)
            elif mode == ExecutionMode.LIMIT:
                result = self._execute_limit(side, qty, signal_price)
            else:
                result = self._execute_twap(side, qty, signal_price)
        except Exception as e:
            self._logger.exception(f"Execution error: {e}")
            elapsed = time.monotonic() * 1000 - start_ms
            return ExecutionResult(
                success=False,
                mode=mode,
                symbol=self.symbol,
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
                f"{side.upper()} {qty}×{self.symbol}"
            )

        self._logger.info(
            f"[{self.bot_id}] Fill complete: "
            f"filled={result.total_qty_filled}/{qty} "
            f"avg_price={result.avg_fill_price:.5f} "
            f"slippage={result.total_slippage_pct:.4f}% "
            f"latency={result.latency_ms:.0f}ms"
        )
        return result

    # ── Mode selection ─────────────────────────────────────────────────────

    def _select_mode(self, qty: float, urgency: OrderUrgency) -> ExecutionMode:
        if urgency == OrderUrgency.HIGH:
            return ExecutionMode.MARKET
        if qty >= self.smart_routing_min_qty:
            return ExecutionMode.TWAP
        return ExecutionMode.LIMIT

    # ── Lot sizing ─────────────────────────────────────────────────────────

    def _to_lots(self, qty: float) -> float:
        """
        Convert qty units to MT5 lot volume.
        Each qty unit maps to min_lot (e.g. 0.01 for forex).
        Result is clamped to [volume_min, volume_max] and rounded to volume_step.
        """
        info = mt5.symbol_info(self.symbol)
        if info is None:
            return max(0.01, round(qty * 0.01, 2))
        min_lot = info.volume_min
        step = info.volume_step
        max_lot = info.volume_max
        raw = qty * min_lot
        # Round to nearest step
        lots = round(round(raw / step) * step, 8)
        return max(min_lot, min(lots, max_lot))

    # ── Market Order ───────────────────────────────────────────────────────

    def _execute_market(
        self, side: str, qty: float, signal_price: float
    ) -> ExecutionResult:
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {self.symbol}: {mt5.last_error()}")

        order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "buy" else tick.bid
        volume = self._to_lots(qty)

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      self.symbol,
            "volume":      volume,
            "type":        order_type,
            "price":       price,
            "deviation":   20,
            "magic":       self._magic,
            "comment":     f"TC_{self.bot_id[:8]}",
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            comment = result.comment if result else str(mt5.last_error())
            raise RuntimeError(f"MT5 market order failed: retcode={retcode} — {comment}")

        fill_price = result.price if result.price else price
        slippage = self._calc_slippage(side, signal_price, fill_price)

        return ExecutionResult(
            success=True,
            mode=ExecutionMode.MARKET,
            symbol=self.symbol,
            side=side,
            total_qty_requested=qty,
            total_qty_filled=result.volume,
            avg_fill_price=fill_price,
            signal_price=signal_price,
            total_slippage_pct=slippage,
            latency_ms=0.0,
            fills=[ChildFill(0, result.volume, fill_price, slippage,
                             datetime.now(timezone.utc).isoformat()).__dict__],
        )

    # ── Limit Order (with market fallback) ────────────────────────────────

    def _execute_limit(
        self, side: str, qty: float, signal_price: float
    ) -> ExecutionResult:
        improvement = 0.0005
        if side == "buy":
            limit_price = round(signal_price * (1 - improvement), 5)
        else:
            limit_price = round(signal_price * (1 + improvement), 5)

        order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT
        volume = self._to_lots(qty)

        request = {
            "action":      mt5.TRADE_ACTION_PENDING,
            "symbol":      self.symbol,
            "volume":      volume,
            "type":        order_type,
            "price":       limit_price,
            "deviation":   20,
            "magic":       self._magic,
            "comment":     f"TC_{self.bot_id[:8]}",
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            self._logger.warning(
                f"[{self.bot_id}] Limit order placement failed: retcode={retcode}. "
                f"Falling back to MARKET."
            )
            return self._execute_market(side, qty, signal_price)

        ticket = result.order
        deadline = time.monotonic() + self.limit_timeout_s

        while time.monotonic() < deadline:
            time.sleep(0.5)
            orders = mt5.orders_get(ticket=ticket)
            if not orders:
                # Order gone from pending — check if it filled as a position
                positions = mt5.positions_get(magic=self._magic)
                if positions:
                    for pos in positions:
                        if pos.magic == self._magic and pos.symbol == self.symbol:
                            fill_p = pos.price_open
                            slip = self._calc_slippage(side, signal_price, fill_p)
                            return ExecutionResult(
                                success=True,
                                mode=ExecutionMode.LIMIT,
                                symbol=self.symbol,
                                side=side,
                                total_qty_requested=qty,
                                total_qty_filled=pos.volume,
                                avg_fill_price=fill_p,
                                signal_price=signal_price,
                                total_slippage_pct=slip,
                                latency_ms=0.0,
                                fills=[ChildFill(0, pos.volume, fill_p, slip,
                                                 datetime.now(timezone.utc).isoformat()).__dict__],
                            )
                break  # order gone but no position found — treat as failed

        # Cancel stale limit order and fall back to market
        cancel_req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
        mt5.order_send(cancel_req)
        self._logger.info(
            f"[{self.bot_id}] Limit order timed out after {self.limit_timeout_s}s. "
            f"Falling back to MARKET."
        )
        return self._execute_market(side, qty, signal_price)

    # ── TWAP Order ────────────────────────────────────────────────────────

    def _execute_twap(
        self, side: str, qty: float, signal_price: float
    ) -> ExecutionResult:
        """
        Split qty into N market-order slices, spaced twap_interval_ms apart.
        Aborts remaining slices if slippage on any fill exceeds max_slippage_pct.
        """
        import math
        n_slices = int(min(math.ceil(qty), self.MAX_TWAP_SLICES))
        slice_qty = qty / n_slices

        fills = []
        total_filled = 0.0
        total_cost = 0.0
        abort_reason = None

        for i in range(n_slices):
            if slice_qty <= 0:
                continue

            try:
                slice_result = self._execute_market(side, slice_qty, signal_price)
                fill = ChildFill(
                    slice_index=i,
                    qty=slice_result.total_qty_filled,
                    fill_price=slice_result.avg_fill_price,
                    slippage_pct=slice_result.total_slippage_pct,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                fills.append(fill.__dict__)
                total_filled += slice_result.total_qty_filled
                total_cost += slice_result.avg_fill_price * slice_result.total_qty_filled

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

            if i < n_slices - 1:
                time.sleep(self.twap_interval_ms / 1000.0)

        avg_fill = total_cost / total_filled if total_filled > 0 else 0.0
        total_slip = self._calc_slippage(side, signal_price, avg_fill) if avg_fill > 0 else 0.0

        return ExecutionResult(
            success=(total_filled > 0 and abort_reason is None),
            mode=ExecutionMode.TWAP,
            symbol=self.symbol,
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
        Positive = paid MORE than expected (bad for buys).
        Negative = received MORE than expected (bad for sells).
        Returns as percentage (e.g. 0.12 means 0.12%).
        """
        if signal_price == 0:
            return 0.0
        if side == "buy":
            return ((fill_price - signal_price) / signal_price) * 100
        else:
            return ((signal_price - fill_price) / signal_price) * 100
