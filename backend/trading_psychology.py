"""
TradeClaw — Trading Psychology (deterministic discipline core)
==============================================================
Pure, I/O-free guards that encode the disciplined-trader behaviours from
"Mastering Trading Psychology" (Aziz) for OPEN-POSITION monitoring.

Every function here is synchronous, side-effect-free, and unit-testable with
synthetic inputs — it runs on the 5s hot path with no MT5 / LLM calls. The
book's thesis is that the cure for emotional trading is *mechanisation*; this
module is that mechanisation.

Book → code:
  - Averaging down kills            → check_scale_in_allowed
  - Stop is sacred (never widen)    → clamp_stop_never_wider
  - Strict with losers              → check_strict_loser_cut
  - Day-trade→swing on hope         → check_horizon_breach
  - Pride / "be right" vs thesis    → check_thesis_invalidated
  - Loose with winners              → (handled by the existing retrace ratchet)

Safety invariant: nothing here can ever WIDEN or REMOVE a predefined hard stop.
Verdicts only ever ALLOW, BLOCK (entries), or make exits stricter (CUT_NOW /
TIGHTEN). The judgment-hold (GIVE_ROOM / HOLD) acts on the profit / early-exit
side only and is bounded by the predefined stop, which always fires.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

# ── Verdict actions ────────────────────────────────────────────────────
ALLOW = "ALLOW"          # entry / scale-in permitted
BLOCK = "BLOCK"          # entry / scale-in refused
CUT_NOW = "CUT_NOW"      # close the position this tick
TIGHTEN = "TIGHTEN"      # shrink the profit give-back floor (monotonic only)
HOLD = "HOLD"            # no change — let the mechanical scanner run
GIVE_ROOM = "GIVE_ROOM"  # defer a PROFIT-side exit on a thesis-intact winner


@dataclass
class GuardVerdict:
    action: str
    reason: str = ""

    @property
    def blocks(self) -> bool:
        return self.action == BLOCK

    @property
    def cuts(self) -> bool:
        return self.action == CUT_NOW


# ── Per-position discipline state ───────────────────────────────────────
@dataclass
class PositionPsychState:
    """The "state of mind" carried for one open position across ticks."""
    ticket: int
    side: str                      # "LONG" | "SHORT"
    entry_price: float
    entry_ts: float                # time.time() at first sighting
    peak_net: float = 0.0          # best floating net seen (loose-winners mirror)
    mae_usd: float = 0.0           # Max Adverse Excursion: worst net seen (<= 0)
    mae_price: float = 0.0         # worst price against the position
    exit_thesis: str = ""          # narrator-set: why we are still in this trade
    invalidation_price: float = 0.0  # price level that breaks the thesis (0 = unset)
    ticks_held: int = 0            # coarse age (one bump per update call)
    last_review_ts: float = 0.0    # last Tier-2 LLM review time
    last_net: float = 0.0
    last_price: float = 0.0


class PositionDisciplineTracker:
    """One per bot. Mirrors the engine's open tickets and tracks the metrics the
    mechanical scanner does NOT: per-position MAE and duration. Thread-safe; the
    engine writes from the tick loop, the reviewer reads from a worker thread.
    """

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._lock = threading.Lock()
        self._states: dict[int, PositionPsychState] = {}

    def update(self, ticket: int, net_profit: float, price: float,
               side: str, entry_price: float, now: float) -> PositionPsychState:
        """Upsert one position's state. MAE only ever worsens; peak only rises."""
        with self._lock:
            st = self._states.get(ticket)
            if st is None:
                st = PositionPsychState(
                    ticket=ticket, side=side, entry_price=entry_price,
                    entry_ts=now, peak_net=net_profit,
                    mae_usd=min(0.0, net_profit), mae_price=price,
                )
                self._states[ticket] = st
            if net_profit > st.peak_net:
                st.peak_net = net_profit
            if net_profit < st.mae_usd:
                st.mae_usd = net_profit
                st.mae_price = price
            st.ticks_held += 1
            st.last_net = net_profit
            st.last_price = price
            return st

    def get(self, ticket: int) -> PositionPsychState | None:
        with self._lock:
            return self._states.get(ticket)

    def set_thesis(self, ticket: int, exit_thesis: str = "",
                   invalidation_price: float = 0.0) -> None:
        with self._lock:
            st = self._states.get(ticket)
            if st is not None:
                if exit_thesis:
                    st.exit_thesis = exit_thesis
                if invalidation_price:
                    st.invalidation_price = float(invalidation_price)

    def prune(self, open_tickets: set[int]) -> None:
        """Drop state for tickets no longer open (mirror the _peak_net prune)."""
        with self._lock:
            for t in list(self._states.keys()):
                if t not in open_tickets:
                    self._states.pop(t, None)

    def duration_secs(self, ticket: int, now: float) -> float:
        with self._lock:
            st = self._states.get(ticket)
            return (now - st.entry_ts) if st else 0.0

    def worst_open_mae(self) -> float:
        """Most adverse MAE across all open positions (<= 0; 0.0 if flat)."""
        with self._lock:
            if not self._states:
                return 0.0
            return min(st.mae_usd for st in self._states.values())

    def snapshot(self) -> list[dict]:
        """UI-facing view of every tracked position."""
        with self._lock:
            return [
                {
                    "ticket": st.ticket,
                    "side": st.side,
                    "mae_usd": round(st.mae_usd, 2),
                    "peak_net": round(st.peak_net, 2),
                    "exit_thesis": st.exit_thesis,
                    "ticks_held": st.ticks_held,
                }
                for st in self._states.values()
            ]


# ── Deterministic guards (the book's black-and-white rules) ─────────────
def check_scale_in_allowed(side: str, current_price: float, avg_entry: float,
                           open_net: float, *, block_average_down: bool = True) -> GuardVerdict:
    """Averaging down kills (Ch3).

    Averaging down = adding to a position the market is moving AGAINST. Scaling
    UP = adding to a winner, which is fine. The distinction is purely the sign
    of the move relative to the average entry (plus open PnL as a backstop).
    """
    if not block_average_down or avg_entry <= 0:
        return GuardVerdict(ALLOW)
    if side == "LONG":
        adverse = current_price < avg_entry
    else:  # SHORT
        adverse = current_price > avg_entry
    if adverse or open_net < 0:
        return GuardVerdict(
            BLOCK,
            f"Anti-average-down: {side} basket net ${open_net:.2f}, price "
            f"{current_price:.5f} vs avg {avg_entry:.5f} — adding to a loser",
        )
    return GuardVerdict(ALLOW, "Scaling up a winner")


def clamp_stop_never_wider(current_stop: float, proposed_stop: float) -> float:
    """Stop is sacred (Ch3): never widen or remove a stop on an open position.

    For BOTH percentage and USD stops a SMALLER value = tighter = safer, so the
    rule is monotonic-min on the loss distance. Adding a stop where none existed
    is allowed; removing one (proposed <= 0) is refused.
    """
    if current_stop <= 0:
        return proposed_stop          # nothing to widen — accept (may add a stop)
    if proposed_stop <= 0:
        return current_stop           # refuse to REMOVE an existing stop
    return min(current_stop, proposed_stop)


def check_strict_loser_cut(net_profit: float, mae_usd: float, *,
                           max_adverse_excursion_usd: float = 0.0,
                           thesis_intact: bool = True) -> GuardVerdict:
    """Strict with losers (Ch3), with the 'pay to see the flop' tension (Ch4)
    resolved in one place: a losing position is cut when its thesis is broken or
    its MAE breaches the limit; otherwise (thesis intact, within bounds) it is
    given room. The predefined hard stop is the outer backstop and always fires.
    """
    if net_profit >= 0:
        return GuardVerdict(HOLD)  # winners are the ratchet's job
    if not thesis_intact:
        return GuardVerdict(CUT_NOW, "Thesis invalidated on a losing position")
    if max_adverse_excursion_usd > 0 and mae_usd <= -abs(max_adverse_excursion_usd):
        return GuardVerdict(
            CUT_NOW,
            f"MAE ${mae_usd:.2f} breached limit -${abs(max_adverse_excursion_usd):.2f}",
        )
    return GuardVerdict(HOLD, "Losing but within bounds — pay to see the flop")


def check_horizon_breach(duration_s: float, net_profit: float, *,
                         max_loser_hold_secs: int = 0,
                         max_position_hold_secs: int = 0) -> GuardVerdict:
    """Day-trade→swing-trade guard (Ch3): never hold a loser past its planned
    horizon on hope. Winners past the horizon are left to the retrace ratchet.
    """
    if max_loser_hold_secs > 0 and net_profit < 0 and duration_s >= max_loser_hold_secs:
        return GuardVerdict(
            CUT_NOW,
            f"Loser held {duration_s:.0f}s ≥ {max_loser_hold_secs}s — no day-trade→swing",
        )
    if max_position_hold_secs > 0 and net_profit <= 0 and duration_s >= max_position_hold_secs:
        return GuardVerdict(
            CUT_NOW,
            f"Position held {duration_s:.0f}s ≥ {max_position_hold_secs}s — horizon breach",
        )
    return GuardVerdict(HOLD)


def check_thesis_invalidated(side: str, current_price: float,
                             invalidation_price: float) -> GuardVerdict:
    """Pride vs price-action (Ch3): the deterministic half of thesis
    invalidation — price crossed the level the entry thesis said it must not.
    The narrative half is Tier 2. invalidation_price <= 0 means unset.
    """
    if invalidation_price <= 0:
        return GuardVerdict(HOLD)
    if side == "LONG" and current_price <= invalidation_price:
        return GuardVerdict(
            CUT_NOW, f"Thesis broken: {current_price:.5f} ≤ invalidation {invalidation_price:.5f}")
    if side == "SHORT" and current_price >= invalidation_price:
        return GuardVerdict(
            CUT_NOW, f"Thesis broken: {current_price:.5f} ≥ invalidation {invalidation_price:.5f}")
    return GuardVerdict(HOLD)
