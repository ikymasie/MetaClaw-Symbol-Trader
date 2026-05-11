"""
TradeClaw — Gemini API Budget & Circuit Breaker (Phase 3 §6.1)
================================================================
Centralized singleton that tracks Gemini API usage fleet-wide and prevents
429 RESOURCE_EXHAUSTED errors via four mechanisms:

  1. Per-minute sliding window — caps burst calls (configurable)
  2. Hourly call budget — caps total Gemini calls per hour
  3. Circuit breaker — on 429 detection, blocks ALL Gemini calls for a
     cooldown window, forcing graceful Ollama fallback
  4. Cost estimation — tracks estimated USD spend per-model so operators
     can monitor daily run rate from the API
  5. Auto-downgrade — when usage exceeds 80% of the hourly budget,
     `get_recommended_model()` returns the `-lite` variant of the model,
     halving cost per call without changing call topology

Usage:
    from gemini_budget import gemini_budget

    if gemini_budget.can_call():
        # Get the (possibly downgraded) model
        model = gemini_budget.get_recommended_model(self._openclaw_model)
        # ... make Gemini call ...
        gemini_budget.record_call(model=model, tokens=512)
    else:
        # fall back to Ollama
        ...

    # On 429 error:
    gemini_budget.record_429()
"""

import logging
import threading
import time

logger = logging.getLogger("tradeclaw.gemini_budget")


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

DEFAULT_HOURLY_LIMIT = 60          # Max Gemini calls per hour (fleet-wide)
DEFAULT_PER_MINUTE_LIMIT = 5       # Burst cap per rolling 60s window
DEFAULT_COOLDOWN_SECONDS = 900     # 15 minutes cooldown after a 429
HOUR_SECONDS = 3600
MINUTE_SECONDS = 60

# Auto-downgrade threshold: fraction of hourly limit at which auto-downgrade kicks in.
BUDGET_PRESSURE_THRESHOLD = 0.80   # 80%

# Default conservative token estimate per call (output tokens; input is ~ free).
# Real call uses max_tokens=512 with response_format json — most replies fit in 200-400.
DEFAULT_ESTIMATED_TOKENS = 400

# Per-model cost in USD per 1K output tokens (approximate; update as Google publishes).
COST_PER_1K_TOKENS: dict[str, float] = {
    "gemini-2.0-flash":       0.00015,
    "gemini-2.0-flash-lite":  0.0000750,
    "gemini-2.5-flash":       0.00015,
    "gemini-2.5-flash-lite":  0.0000750,
    "gemini-3.1-flash":       0.0000750,
    "gemini-3.1-flash-lite":  0.0000375,
    "gemini-flash-latest":    0.00015,
}


# ─────────────────────────────────────────────
# GEMINI BUDGET SINGLETON
# ─────────────────────────────────────────────

class GeminiBudget:
    """
    Thread-safe global budget tracker for Gemini API calls.

    All agents and the AI Brain check this before attempting a Gemini call.
    When the budget is exhausted or the circuit breaker is tripped,
    callers should fall back to local Ollama inference.

    All public methods are O(1) and protected by a single lock.
    """

    # Class-level constants reused by callers
    BUDGET_PRESSURE_THRESHOLD = BUDGET_PRESSURE_THRESHOLD

    def __init__(
        self,
        hourly_limit: int = DEFAULT_HOURLY_LIMIT,
        per_minute_limit: int = DEFAULT_PER_MINUTE_LIMIT,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self._lock = threading.Lock()
        self.hourly_limit = hourly_limit
        self.per_minute_limit = per_minute_limit
        self.cooldown_seconds = cooldown_seconds

        # ── Rolling hour window ──────────────────────────────────────
        self._window_start: float = time.time()
        self._calls_in_window: int = 0

        # ── Rolling minute window (Phase 3 §6.1a) ────────────────────
        self._minute_start: float = time.time()
        self._calls_in_minute: int = 0

        # ── Circuit breaker ──────────────────────────────────────────
        self._circuit_open: bool = False
        self._circuit_open_until: float = 0.0

        # ── Lifetime counters ────────────────────────────────────────
        self._total_calls: int = 0
        self._total_429s: int = 0
        self._total_blocked: int = 0

        # ── Cost & model tracking (Phase 3 §6.1b) ────────────────────
        self._estimated_cost_usd: float = 0.0
        self._model_call_counts: dict[str, int] = {}

    # ── Public API ───────────────────────────────────────────────────

    def can_call(self) -> bool:
        """
        Check if a Gemini call is permitted right now.

        Returns False when:
          - the circuit breaker is active (real 429 from Gemini), OR
          - the rolling 60s minute window has hit per_minute_limit.

        The hourly limit is informational (drives auto-downgrade) — it does
        NOT block calls outright, because the real rate-limit authority is
        Google's own quota enforcement (which trips the circuit breaker).
        """
        with self._lock:
            self._maybe_reset_window()
            self._maybe_reset_minute()

            # Circuit breaker check (fires only on real 429 responses)
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
                    logger.info(
                        "[GeminiBudget] Circuit breaker RESET — Gemini calls re-enabled",
                        extra={"event": "gemini_circuit_reset"},
                    )

            # Per-minute burst cap
            if self._calls_in_minute >= self.per_minute_limit:
                self._total_blocked += 1
                logger.debug(
                    f"[GeminiBudget] BLOCKED (minute cap: "
                    f"{self._calls_in_minute}/{self.per_minute_limit})"
                )
                return False

            return True

    def get_recommended_model(self, base_model: str) -> str:
        """
        Phase 3 §6.1c — Auto-downgrade.

        Returns the `-lite` variant of `base_model` when usage has crossed
        BUDGET_PRESSURE_THRESHOLD (80%) of the hourly limit. Otherwise returns
        `base_model` unchanged.

        Idempotent: if the model already ends in `-lite`, returns it unchanged.
        Best-effort: if the base model has no known `-lite` sibling in the
        COST_PER_1K_TOKENS table, returns the base model (no downgrade).
        """
        if not base_model:
            return base_model
        with self._lock:
            self._maybe_reset_window()
            pressure = self._calls_in_window / max(1, self.hourly_limit)

        if pressure < self.BUDGET_PRESSURE_THRESHOLD:
            return base_model
        if base_model.endswith("-lite"):
            return base_model

        candidate = f"{base_model}-lite"
        if candidate in COST_PER_1K_TOKENS:
            logger.info(
                f"[GeminiBudget] Auto-downgrade: {base_model} → {candidate} "
                f"(pressure={pressure:.0%})",
                extra={
                    "event": "gemini_auto_downgrade",
                    "from_model": base_model,
                    "to_model": candidate,
                    "pressure": round(pressure, 3),
                },
            )
            return candidate
        # Unknown sibling — be conservative, don't downgrade silently
        return base_model

    def record_call(
        self,
        model: str = "unknown",
        tokens: int = DEFAULT_ESTIMATED_TOKENS,
    ) -> None:
        """Record a successful Gemini API call with model & token attribution."""
        cost = (COST_PER_1K_TOKENS.get(model, 0.00015) * tokens) / 1000.0
        with self._lock:
            self._maybe_reset_window()
            self._maybe_reset_minute()
            self._calls_in_window += 1
            self._calls_in_minute += 1
            self._total_calls += 1
            self._estimated_cost_usd += cost
            self._model_call_counts[model] = self._model_call_counts.get(model, 0) + 1
            logger.info(
                f"[GeminiBudget] Call recorded: hour={self._calls_in_window}/{self.hourly_limit}, "
                f"min={self._calls_in_minute}/{self.per_minute_limit}, "
                f"~${self._estimated_cost_usd:.4f}",
                extra={
                    "event": "gemini_call",
                    "model": model,
                    "calls_this_hour": self._calls_in_window,
                    "calls_this_minute": self._calls_in_minute,
                    "estimated_cost_usd": round(self._estimated_cost_usd, 6),
                },
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
                f"[GeminiBudget] 429 DETECTED — circuit breaker OPEN for "
                f"{self.cooldown_seconds}s. Total 429s: {self._total_429s}",
                extra={
                    "event": "gemini_429",
                    "circuit_open_until": self._circuit_open_until,
                    "total_429s": self._total_429s,
                    "cooldown_seconds": self.cooldown_seconds,
                },
            )

    def get_status(self) -> dict:
        """Return current budget status for the /system/gemini-budget endpoint."""
        with self._lock:
            self._maybe_reset_window()
            self._maybe_reset_minute()
            remaining_hour = max(0, self.hourly_limit - self._calls_in_window)
            remaining_minute = max(0, self.per_minute_limit - self._calls_in_minute)
            cb_active = self._circuit_open and time.time() < self._circuit_open_until
            pressure = self._calls_in_window / max(1, self.hourly_limit)

            return {
                "calls_this_hour": self._calls_in_window,
                "hourly_limit": self.hourly_limit,
                "remaining_hour": remaining_hour,
                "calls_this_minute": self._calls_in_minute,
                "per_minute_limit": self.per_minute_limit,
                "remaining_minute": remaining_minute,
                "pressure": round(pressure, 3),
                "auto_downgrade_active": pressure >= self.BUDGET_PRESSURE_THRESHOLD,
                "circuit_breaker_active": cb_active,
                "circuit_breaker_expires_at": (
                    self._circuit_open_until if cb_active else None
                ),
                "circuit_breaker_cooldown_seconds": self.cooldown_seconds,
                "total_calls": self._total_calls,
                "total_429s": self._total_429s,
                "total_blocked": self._total_blocked,
                "estimated_cost_usd": round(self._estimated_cost_usd, 6),
                "model_breakdown": dict(self._model_call_counts),
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
                    f"[GeminiBudget] Hourly window reset (previous: {old_count} calls)",
                    extra={"event": "gemini_window_reset", "scope": "hour",
                           "previous_count": old_count},
                )

    def _maybe_reset_minute(self) -> None:
        """Reset the minute window if 60s have elapsed. Must hold _lock."""
        now = time.time()
        if now - self._minute_start >= MINUTE_SECONDS:
            self._minute_start = now
            self._calls_in_minute = 0


# ── Module-level singleton ───────────────────────────────────────────
gemini_budget = GeminiBudget()
