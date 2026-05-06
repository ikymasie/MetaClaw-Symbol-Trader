"""
TradeClaw — Gemini API Budget & Circuit Breaker
==================================================
Centralized singleton that tracks Gemini API usage fleet-wide
and prevents 429 RESOURCE_EXHAUSTED errors via:

  1. Hourly call budget — caps total Gemini calls per hour
  2. Circuit breaker — on 429 detection, blocks ALL Gemini calls
     for a cooldown window, forcing graceful Ollama fallback
  3. Observability — thread-safe counters and status for the API

Usage:
    from gemini_budget import gemini_budget

    if gemini_budget.can_call():
        # make Gemini call
        gemini_budget.record_call()
    else:
        # fall back to Ollama
        ...

    # On 429 error:
    gemini_budget.record_429()
"""

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger("tradeclaw.gemini_budget")


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

DEFAULT_HOURLY_LIMIT = 10          # Max Gemini calls per hour (fleet-wide)
DEFAULT_COOLDOWN_SECONDS = 900     # 15 minutes cooldown after a 429
HOUR_SECONDS = 3600


# ─────────────────────────────────────────────
# GEMINI BUDGET SINGLETON
# ─────────────────────────────────────────────

class GeminiBudget:
    """
    Thread-safe global budget tracker for Gemini API calls.

    All agents and the AI Brain check this before attempting a Gemini call.
    When the budget is exhausted or the circuit breaker is tripped,
    callers should fall back to local Ollama inference.
    """

    def __init__(
        self,
        hourly_limit: int = DEFAULT_HOURLY_LIMIT,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self._lock = threading.Lock()
        self.hourly_limit = hourly_limit
        self.cooldown_seconds = cooldown_seconds

        # ── Rolling hour window ──────────────────────────────────────
        self._window_start: float = time.time()
        self._calls_in_window: int = 0

        # ── Circuit breaker ──────────────────────────────────────────
        self._circuit_open: bool = False
        self._circuit_open_until: float = 0.0

        # ── Lifetime counters ────────────────────────────────────────
        self._total_calls: int = 0
        self._total_429s: int = 0
        self._total_blocked: int = 0

    # ── Public API ───────────────────────────────────────────────────

    def can_call(self) -> bool:
        """
        Check if a Gemini call is permitted right now.

        Returns False if:
          - Circuit breaker is active (recent 429)
          - Hourly call budget is exhausted
        """
        with self._lock:
            self._maybe_reset_window()

            # Circuit breaker check
            if self._circuit_open:
                if time.time() < self._circuit_open_until:
                    self._total_blocked += 1
                    logger.debug(
                        f"[GeminiBudget] BLOCKED (circuit breaker active, "
                        f"resets in {self._circuit_open_until - time.time():.0f}s)"
                    )
                    return False
                else:
                    # Cooldown expired — close the circuit
                    self._circuit_open = False
                    self._circuit_open_until = 0.0
                    logger.info("[GeminiBudget] Circuit breaker RESET — Gemini calls re-enabled")

            # Budget check
            if self._calls_in_window >= self.hourly_limit:
                self._total_blocked += 1
                remaining = HOUR_SECONDS - (time.time() - self._window_start)
                logger.info(
                    f"[GeminiBudget] BLOCKED (budget exhausted: "
                    f"{self._calls_in_window}/{self.hourly_limit} calls this hour, "
                    f"resets in {remaining:.0f}s)"
                )
                return False

            return True

    def record_call(self) -> None:
        """Record a successful Gemini API call."""
        with self._lock:
            self._maybe_reset_window()
            self._calls_in_window += 1
            self._total_calls += 1
            logger.info(
                f"[GeminiBudget] Call recorded: {self._calls_in_window}/{self.hourly_limit} this hour"
            )

    def record_429(self) -> None:
        """
        Record a 429 RESOURCE_EXHAUSTED error.
        Trips the circuit breaker for the configured cooldown period.
        """
        with self._lock:
            self._total_429s += 1
            self._circuit_open = True
            self._circuit_open_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"[GeminiBudget] 🚨 429 DETECTED — circuit breaker OPEN for "
                f"{self.cooldown_seconds}s. Total 429s: {self._total_429s}"
            )

    def get_status(self) -> dict:
        """Return current budget status for the /system/gemini-budget endpoint."""
        with self._lock:
            self._maybe_reset_window()
            remaining = max(0, self.hourly_limit - self._calls_in_window)
            cb_active = self._circuit_open and time.time() < self._circuit_open_until

            return {
                "calls_this_hour": self._calls_in_window,
                "hourly_limit": self.hourly_limit,
                "remaining": remaining,
                "circuit_breaker_active": cb_active,
                "circuit_breaker_expires_at": (
                    self._circuit_open_until if cb_active else None
                ),
                "circuit_breaker_cooldown_seconds": self.cooldown_seconds,
                "total_calls": self._total_calls,
                "total_429s": self._total_429s,
                "total_blocked": self._total_blocked,
            }

    # ── Internal ─────────────────────────────────────────────────────

    def _maybe_reset_window(self) -> None:
        """Reset the hourly window if an hour has elapsed. Must hold _lock."""
        now = time.time()
        if now - self._window_start >= HOUR_SECONDS:
            old_count = self._calls_in_window
            self._window_start = now
            self._calls_in_window = 0
            if old_count > 0:
                logger.info(
                    f"[GeminiBudget] Hourly window reset (previous window: {old_count} calls)"
                )


# ── Module-level singleton ───────────────────────────────────────────
gemini_budget = GeminiBudget()
