"""
TradeClaw — Position Slot Manager
====================================
Enables layered entry (scale-in) by tracking up to max_slots independent
position entries per bot.

Implements:
  - Scenario 3: Layered entry / scale-in — one slot per confirmed signal, up to max_slots
  - Scenario 5: Kelly splitting — total approved qty is divided evenly across max_slots,
    so each new entry commits 1/max_slots of the full planned risk rather than all-in

Constraints enforced here:
  - All slots must share the same direction (no same-bot hedging)
  - Cannot exceed max_slots open at any time
  - Hard capacity blocks new entries when at max_slots
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional


@dataclass
class PositionSlot:
    """A single layered entry within a multi-slot position."""

    slot_id: int
    side: str            # "LONG" | "SHORT"
    qty: float
    entry_price: float
    entry_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signal_source: str = ""
    deliberation_ref: Optional[dict] = field(default=None, repr=False)

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.qty
        return (self.entry_price - current_price) * self.qty

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "side": self.side,
            "qty": round(self.qty, 4),
            "entry_price": round(self.entry_price, 5),
            "entry_time": self.entry_time,
            "signal_source": self.signal_source,
        }


class PositionSlotManager:
    """
    Tracks up to max_slots independent position entries per bot.

    All slots must share one direction (LONG or SHORT). Mixed directions are
    not allowed within a single bot — that's what separate fleet bots are for.
    """

    def __init__(self, bot_id: str, max_slots: int = 5):
        self.bot_id = bot_id
        self.max_slots = max_slots
        self._slots: dict[int, PositionSlot] = {}
        self._next_slot_id: int = 1
        self._lock = Lock()

    # ── Read-only properties ──────────────────────────────────────────

    @property
    def open_count(self) -> int:
        with self._lock:
            return len(self._slots)

    @property
    def total_qty(self) -> float:
        with self._lock:
            return sum(s.qty for s in self._slots.values())

    @property
    def primary_side(self) -> str:
        """Direction of all open slots, or "NONE" if flat."""
        with self._lock:
            if not self._slots:
                return "NONE"
            return next(iter(self._slots.values())).side

    @property
    def avg_entry_price(self) -> float:
        """Volume-weighted average entry price across all open slots."""
        with self._lock:
            total_qty = sum(s.qty for s in self._slots.values())
            if total_qty == 0:
                return 0.0
            return (
                sum(s.entry_price * s.qty for s in self._slots.values()) / total_qty
            )

    def is_flat(self) -> bool:
        return self.open_count == 0

    def can_open(self, side: str) -> bool:
        """
        True if a new slot can be opened in the given direction.
        Fails if at capacity OR if existing slots are in the opposite direction.
        """
        with self._lock:
            if len(self._slots) >= self.max_slots:
                return False
            if not self._slots:
                return True
            return next(iter(self._slots.values())).side == side

    # ── Mutations ─────────────────────────────────────────────────────

    def open_slot(
        self,
        side: str,
        qty: float,
        entry_price: float,
        signal_source: str = "",
        deliberation_ref: Optional[dict] = None,
    ) -> Optional[PositionSlot]:
        """
        Add a new position slot (scale-in entry).
        Returns the new PositionSlot, or None if at capacity / side conflict.
        """
        if not self.can_open(side):
            return None
        with self._lock:
            slot = PositionSlot(
                slot_id=self._next_slot_id,
                side=side,
                qty=qty,
                entry_price=entry_price,
                signal_source=signal_source,
                deliberation_ref=deliberation_ref,
            )
            self._slots[self._next_slot_id] = slot
            self._next_slot_id += 1
        return slot

    def close_all(self, exit_price: float) -> tuple[float, list[PositionSlot]]:
        """
        Close all open slots at exit_price.
        Returns (total_realized_pnl, list_of_closed_slots).
        """
        with self._lock:
            closed = list(self._slots.values())
            self._slots.clear()
        total_pnl = sum(s.unrealized_pnl(exit_price) for s in closed)
        return total_pnl, closed

    def force_clear(self) -> None:
        """Hard-clear all slots without computing PnL. Used when MT5 confirms flat."""
        with self._lock:
            self._slots.clear()

    # ── Analytics ─────────────────────────────────────────────────────

    def unrealized_pnl(self, current_price: float) -> float:
        with self._lock:
            return sum(s.unrealized_pnl(current_price) for s in self._slots.values())

    def per_slot_kelly_qty(self, total_kelly_qty: float) -> float:
        """
        Per-slot Kelly allocation: split total approved qty evenly across max_slots.
        Scenario 5 — each scale-in entry commits 1/max_slots of full risk, preventing
        a single slippage event from consuming the entire planned risk budget.
        """
        return total_kelly_qty / max(1, self.max_slots)

    def get_slots(self) -> list[PositionSlot]:
        with self._lock:
            return list(self._slots.values())

    def to_dict(self) -> dict:
        with self._lock:
            slots = list(self._slots.values())
        return {
            "max_slots": self.max_slots,
            "open_count": len(slots),
            "total_qty": round(sum(s.qty for s in slots), 4),
            "primary_side": self.primary_side,
            "avg_entry_price": round(self.avg_entry_price, 5),
            "slots": [s.to_dict() for s in slots],
        }
