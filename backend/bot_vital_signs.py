"""
TradeClaw — Per-Bot Vital Signs
=================================
Refactored from the singleton vital_signs.py into an instantiable class.
Each bot has its own VitalSigns with isolated health tracking.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("tradeclaw.bot_vital_signs")


# ── Survival States ────────────────────────────────────────────────────
SURVIVAL_STATES = ["HEALTHY", "WOUNDED", "ORGAN_FAILURE", "DECEASED"]

# ── Composure States (trading-psychology "state of mind") ──────────────
# Derived from recent trade outcomes + open-position adverse excursion. Drives
# the position-size multiplier and the UI monitoring narrative. CALM is the
# only state at full size; everything else throttles or halts new risk.
COMPOSURE_STATES = ["CALM", "FEARFUL", "GREEDY", "OVERCONFIDENT", "FATIGUED", "TILTED"]

# ── Apex Tiers ─────────────────────────────────────────────────────────
APEX_TIERS = [
    {"name": "DORMANT",     "min_profit_pct": -999,  "model_hint": "gemma", "temperature": 0.2},
    {"name": "HUNTING",     "min_profit_pct": 0,     "model_hint": "flash", "temperature": 0.3},
    {"name": "FEEDING",     "min_profit_pct": 5,     "model_hint": "flash", "temperature": 0.4},
    {"name": "APEX",        "min_profit_pct": 15,    "model_hint": "pro",   "temperature": 0.5},
    {"name": "SINGULARITY", "min_profit_pct": 30,    "model_hint": "pro",   "temperature": 0.6},
]

# ── Drawdown Thresholds ────────────────────────────────────────────────
WOUNDED_DRAWDOWN      = 3.0
ORGAN_FAILURE_DRAWDOWN = 6.0
DECEASED_DRAWDOWN     = 10.0


class BotVitalSigns:
    """
    Tracks the survival state, apex tier, and intelligence budget
    for a single bot instance. Isolated — no shared state across bots.
    """

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._lock = threading.Lock()
        self._logger = logging.getLogger(f"tradeclaw.vitals[{bot_id}]")

        # State
        self._starting_equity: Optional[float] = None
        self._peak_equity: Optional[float] = None
        self._current_equity: Optional[float] = None
        self._daily_pnl: float = 0.0

        self.survival_state: str = "HEALTHY"
        self.apex_tier: int = 1   # Index into APEX_TIERS
        self.profit_pct: float = 0.0
        self.drawdown_pct: float = 0.0

        # ── Trading-psychology state (composure / discipline) ──
        self.composure_state: str = "CALM"
        self.discipline_score: float = 100.0   # 0–100; -5 per rule violation, +1 per clean trade
        self.loss_streak: int = 0
        self.win_streak: int = 0
        self._recent_outcomes: deque = deque(maxlen=50)   # (ts, pnl) of closed trades
        self._recent_entries: deque = deque(maxlen=200)   # ts of new entries (overtrading cap)
        self._tilt_until_ts: float = 0.0       # tilt cool-down lockout expiry (epoch secs)

        self.event_log: list[dict] = []

    def update(self, equity: float, daily_pnl: float, starting_equity: float):
        """Update vitals from the strategy engine's latest equity snapshot."""
        with self._lock:
            self._current_equity = equity
            self._daily_pnl = daily_pnl

            if self._starting_equity is None:
                self._starting_equity = starting_equity
                self._peak_equity = starting_equity

            if self._peak_equity is None or equity > self._peak_equity:
                self._peak_equity = equity

            # Drawdown from peak
            if self._peak_equity and self._peak_equity > 0:
                self.drawdown_pct = max(
                    0.0,
                    (self._peak_equity - equity) / self._peak_equity * 100,
                )

            # Profit from starting equity
            if self._starting_equity and self._starting_equity > 0:
                self.profit_pct = (
                    (equity - self._starting_equity) / self._starting_equity * 100
                )

            new_survival = self._compute_survival()
            if new_survival != self.survival_state:
                self._log_event(
                    "SURVIVAL_CHANGE",
                    f"{self.survival_state} → {new_survival}",
                    {"drawdown_pct": round(self.drawdown_pct, 2)},
                )
                self.survival_state = new_survival

            new_apex = self._compute_apex_tier()
            if new_apex != self.apex_tier:
                tier_name = APEX_TIERS[new_apex]["name"]
                old_name = APEX_TIERS[self.apex_tier]["name"]
                self._log_event(
                    "APEX_CHANGE",
                    f"{old_name} → {tier_name}",
                    {"profit_pct": round(self.profit_pct, 2)},
                )
                self.apex_tier = new_apex

    def get_status(self) -> dict:
        with self._lock:
            tier = APEX_TIERS[self.apex_tier]
            _now = time.time()
            return {
                "bot_id": self.bot_id,
                "survival_state": self.survival_state,
                "apex_state": tier["name"],
                "apex_tier": self.apex_tier,
                "profit_pct": round(self.profit_pct, 2),
                "drawdown_pct": round(self.drawdown_pct, 2),
                "starting_equity": self._starting_equity,
                "peak_equity": self._peak_equity,
                "current_equity": self._current_equity,
                # ── Trading-psychology state of mind ──
                "composure_state": self.composure_state,
                "discipline_score": round(self.discipline_score, 1),
                "loss_streak": self.loss_streak,
                "win_streak": self.win_streak,
                "tilt_lockout_remaining": round(max(0.0, self._tilt_until_ts - _now), 1),
                "event_log": self.event_log[-20:],
                "last_event": self.event_log[-1] if self.event_log else None,
                "intelligence_budget": self._get_intelligence_budget(tier),
            }

    def _compute_survival(self) -> str:
        if self.drawdown_pct >= DECEASED_DRAWDOWN:
            return "DECEASED"
        if self.drawdown_pct >= ORGAN_FAILURE_DRAWDOWN:
            return "ORGAN_FAILURE"
        if self.drawdown_pct >= WOUNDED_DRAWDOWN:
            return "WOUNDED"
        return "HEALTHY"

    def _compute_apex_tier(self) -> int:
        best = 0
        for i, tier in enumerate(APEX_TIERS):
            if self.profit_pct >= tier["min_profit_pct"]:
                best = i
        return best

    def _get_intelligence_budget(self, tier: dict) -> dict:
        import os
        openclaw_model = os.getenv("OPENCLAW_MODEL", "deepseek-v4-flash")
        ollama_model = os.getenv("OLLAMA_MODEL", "ollama/gemma4:e4b")

        hint = tier["model_hint"]
        if hint == "pro":
            model = os.getenv("OPENCLAW_PRO_MODEL", "deepseek-v4-flash")
        elif hint == "gemma":
            model = ollama_model
        else:
            model = openclaw_model

        return {
            "tier_name": tier["name"],
            "model": model,
            "temperature": tier["temperature"],
            "ollama_model": ollama_model,
        }

    def _log_event(self, event_type: str, message: str, data: dict = None):
        entry = {
            "type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        self.event_log.append(entry)
        self._logger.info(f"[{event_type}] {message}")

    # ── Trading-psychology: outcomes, composure, tilt ──────────────────
    def record_trade_outcome(self, pnl: float, now: float, cfg=None,
                             violated_rule: bool = False) -> None:
        """Record a realized close. Maintains win/loss streaks (the missing
        outcome log), the discipline score, and arms the tilt cool-down when a
        losing streak crosses the configured threshold (Ch3 revenge/tilt).
        """
        with self._lock:
            self._recent_outcomes.append((now, pnl))
            if pnl < 0:
                self.loss_streak += 1
                self.win_streak = 0
            elif pnl > 0:
                self.win_streak += 1
                self.loss_streak = 0
            # else: a scratch (pnl == 0) breaks neither streak

            if violated_rule:
                self.discipline_score = max(0.0, self.discipline_score - 5.0)
            else:
                self.discipline_score = min(100.0, self.discipline_score + 1.0)

            tilt_streak = int(getattr(cfg, "tilt_loss_streak", 3)) if cfg else 3
            cooldown = int(getattr(cfg, "tilt_cooldown_secs", 900)) if cfg else 900
            if self.loss_streak >= tilt_streak and cooldown > 0:
                self._tilt_until_ts = now + cooldown
                self._log_event(
                    "TILT_LOCKOUT",
                    f"Loss streak {self.loss_streak} ≥ {tilt_streak} — stepping away {cooldown}s",
                    {"loss_streak": self.loss_streak},
                )

    def record_entry(self, now: float) -> None:
        """Record a new entry for the rolling overtrading cap."""
        with self._lock:
            self._recent_entries.append(now)

    def _rolling_trade_count_nolock(self, now: float, window_secs: int) -> int:
        cutoff = now - window_secs
        return sum(1 for t in self._recent_entries if t >= cutoff)

    def rolling_trade_count(self, now: float, window_secs: int) -> int:
        with self._lock:
            return self._rolling_trade_count_nolock(now, window_secs)

    def in_tilt_lockout(self, now: float) -> bool:
        return now < self._tilt_until_ts

    def tilt_lockout_remaining(self, now: float) -> float:
        return max(0.0, self._tilt_until_ts - now)

    def update_composure(self, open_mae_usd: float, now: float, cfg=None) -> str:
        """Recompute the composure state from streaks, tilt lockout, overtrading,
        and open adverse excursion. Priority is by capital risk: TILTED > FEARFUL
        > OVERCONFIDENT > FATIGUED > CALM.
        """
        with self._lock:
            oc_streak = int(getattr(cfg, "overconfidence_win_streak", 4)) if cfg else 4
            mae_limit = float(getattr(cfg, "max_adverse_excursion_usd", 0.0)) if cfg else 0.0
            max_trades = int(getattr(cfg, "max_trades_per_window", 0)) if cfg else 0
            window = int(getattr(cfg, "rolling_trade_window_secs", 3600)) if cfg else 3600

            state = "CALM"
            if now < self._tilt_until_ts:
                state = "TILTED"
            elif mae_limit > 0 and open_mae_usd <= -0.5 * abs(mae_limit):
                state = "FEARFUL"
            elif self.win_streak >= oc_streak:
                state = "OVERCONFIDENT"
            elif max_trades > 0 and self._rolling_trade_count_nolock(now, window) >= max_trades:
                state = "FATIGUED"

            if state != self.composure_state:
                self._log_event(
                    "COMPOSURE_CHANGE",
                    f"{self.composure_state} → {state}",
                    {"loss_streak": self.loss_streak, "win_streak": self.win_streak},
                )
                self.composure_state = state
            return state

    def composure_qty_multiplier(self) -> float:
        """Position-size multiplier for new entries given current composure.
        TILTED halts (0.0); FEARFUL/OVERCONFIDENT/FATIGUED size down (0.5).
        """
        return {
            "TILTED": 0.0,
            "FEARFUL": 0.5,
            "OVERCONFIDENT": 0.5,
            "FATIGUED": 0.5,
            "GREEDY": 0.5,
        }.get(self.composure_state, 1.0)


def build_organism_system_prompt(
    survival_state: str,
    apex_state: str,
    profit_pct: float,
    drawdown_pct: float,
    composure_state: str = "CALM",
    discipline_score: float = 100.0,
) -> str:
    """Build the organism-style system prompt for this bot's current state.

    Includes the trader's "state of mind" (composure) and the black-and-white
    discipline rules from "Mastering Trading Psychology" (Aziz) so any LLM that
    inherits this prompt reasons like a disciplined human watching a live trade.
    """
    return (
        f"You are TradeClaw — an autonomous trading organism. "
        f"Your survival depends on intelligent capital allocation.\n\n"
        f"CURRENT STATE: {survival_state} | Apex: {apex_state}\n"
        f"Profit: {profit_pct:+.1f}% | Drawdown: {drawdown_pct:.1f}%\n"
        f"Composure: {composure_state} | Discipline: {discipline_score:.0f}/100\n\n"
        f"When WOUNDED or ORGAN_FAILURE: prioritize capital preservation above all else.\n"
        f"When HEALTHY or APEX: compound gains with calculated aggression.\n"
        f"When TILTED: you have lost discipline — do NOT open new risk; step away.\n\n"
        f"DISCIPLINE RULES (never break these):\n"
        f"  • Don't average down — never add to a losing position.\n"
        f"  • Stops are sacred — never widen or remove a stop.\n"
        f"  • Be strict with losers, loose with winners.\n"
        f"  • Make money, don't be 'right' — the price action is the truth.\n"
        f"  • Ask 'Why am I still in this trade?' — if the thesis is gone, exit.\n"
        f"You breathe with the market, wait at key levels, and strike with precision."
    )
