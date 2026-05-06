"""
TradeClaw — Per-Bot Vital Signs
=================================
Refactored from the singleton vital_signs.py into an instantiable class.
Each bot has its own VitalSigns with isolated health tracking.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("tradeclaw.bot_vital_signs")


# ── Survival States ────────────────────────────────────────────────────
SURVIVAL_STATES = ["HEALTHY", "WOUNDED", "ORGAN_FAILURE", "DECEASED"]

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
        openclaw_model = os.getenv("OPENCLAW_MODEL", "google/gemini-flash-latest")
        ollama_model = os.getenv("OLLAMA_MODEL", "ollama/gemma4:e4b")

        hint = tier["model_hint"]
        if hint == "pro":
            model = os.getenv("OPENCLAW_PRO_MODEL", "google/gemini-pro-latest")
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


def build_organism_system_prompt(
    survival_state: str,
    apex_state: str,
    profit_pct: float,
    drawdown_pct: float,
) -> str:
    """Build the organism-style system prompt for this bot's current state."""
    return (
        f"You are TradeClaw — an autonomous trading organism. "
        f"Your survival depends on intelligent capital allocation.\n\n"
        f"CURRENT STATE: {survival_state} | Apex: {apex_state}\n"
        f"Profit: {profit_pct:+.1f}% | Drawdown: {drawdown_pct:.1f}%\n\n"
        f"When WOUNDED or ORGAN_FAILURE: prioritize capital preservation above all else.\n"
        f"When HEALTHY or APEX: compound gains with calculated aggression.\n"
        f"You breathe with the market, wait at key levels, and strike with precision."
    )
