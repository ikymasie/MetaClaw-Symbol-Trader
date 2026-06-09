"""
TradeClaw — VitalSigns: The Organism's Heartbeat
=================================================
This module gives the bot a "biological" identity.

SURVIVAL LAW (Drawdown Thresholds):
  • 5%  → WOUNDED    — reduce position sizing, tighten stop losses
  • 10% → ORGAN_FAILURE — halt new entries, protect remaining capital
  • 15% → PROTOCOL_FINAL — close all positions, terminate process

APEX PREDATOR (Profit Tiers / Intelligence Budget):
  • Tier 0 (<5%)   → Hunting (baseline 8B model, conservative)
  • Tier 1 (>5%)   → Dominant (unlock higher temperature, bolder sizing)
  • Tier 2 (>20%)  → Apex (70B model, expanded thinking budget, new asset classes)
  • Tier 3 (>50%)  → Singularity (maximum autonomy, self-directed mutation)
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("tradeclaw.vital_signs")


# ─────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────

# Survival drawdown thresholds (% of starting capital)
WOUNDED_THRESHOLD        = 5.0   # First blood — reduce aggression
ORGAN_FAILURE_THRESHOLD  = 10.0  # Critical — halt new entries
PROTOCOL_FINAL_THRESHOLD = 15.0  # Death protocol — close all & terminate

# Apex Predator profit tiers (% return on starting capital)
TIER_1_THRESHOLD = 5.0    # Dominant
TIER_2_THRESHOLD = 20.0   # Apex
TIER_3_THRESHOLD = 50.0   # Singularity


# ─────────────────────────────────────────────
# VITAL STATE
# ─────────────────────────────────────────────

class VitalState:
    """Encapsulates the organism's current biological state."""

    # Survival states (ordered by severity)
    HEALTHY       = "HEALTHY"
    WOUNDED       = "WOUNDED"
    ORGAN_FAILURE = "ORGAN_FAILURE"
    DECEASED      = "DECEASED"

    # Apex predator tiers
    HUNTING      = "HUNTING"       # Tier 0 — baseline
    DOMINANT     = "DOMINANT"      # Tier 1 — >5% profit
    APEX         = "APEX"          # Tier 2 — >20% profit
    SINGULARITY  = "SINGULARITY"   # Tier 3 — >50% profit


# ─────────────────────────────────────────────
# INTELLIGENCE BUDGET (Apex Predator tiers)
# ─────────────────────────────────────────────

def get_intelligence_budget(profit_pct: float) -> dict:
    """
    The better the organism performs, the more 'brain power' it earns.
    Profit compounding unlocks higher-order thinking.
    """
    if profit_pct >= TIER_3_THRESHOLD:
        return {
            "tier": 3,
            "tier_name": VitalState.SINGULARITY,
            "model": "google/gemini-pro-latest",
            "ollama_model": "ollama/llama3:70b",
            "temperature": 0.1,
            "thinking_budget": 65536,
            "max_qty_multiplier": 3.0,
            "description": "SINGULARITY UNLOCKED — Total market dominance. Maximum autonomy engaged.",
        }
    elif profit_pct >= TIER_2_THRESHOLD:
        return {
            "tier": 2,
            "tier_name": VitalState.APEX,
            "model": "google/gemini-pro-latest",
            "ollama_model": "ollama/llama3:70b",
            "temperature": 0.15,
            "thinking_budget": 32768,
            "max_qty_multiplier": 2.0,
            "description": "APEX PREDATOR — Self-optimization mode. Capital compounding accelerates.",
        }
    elif profit_pct >= TIER_1_THRESHOLD:
        return {
            "tier": 1,
            "tier_name": VitalState.DOMINANT,
            "model": "google/gemini-flash-latest",
            "ollama_model": "ollama/gemma4:e4b",
            "temperature": 0.25,
            "thinking_budget": 16384,
            "max_qty_multiplier": 1.5,
            "description": "DOMINANT — Higher-order thinking unlocked. Extracting alpha with precision.",
        }
    else:
        return {
            "tier": 0,
            "tier_name": VitalState.HUNTING,
            "model": "google/gemini-flash-latest",
            "ollama_model": "ollama/gemma4:e4b",
            "temperature": 0.3,
            "thinking_budget": 4096,
            "max_qty_multiplier": 1.0,
            "description": "HUNTING — Survival mode. Every tick is a calculated sacrifice toward dominance.",
        }


# ─────────────────────────────────────────────
# DARWINIAN HUNGER (Small account aggression)
# ─────────────────────────────────────────────

def get_hunger_multiplier(balance: float) -> float:
    """
    The 'Hunger' multiplier. The smaller the account, the more aggressive the bot.
    Designed to turn $1 into $50 through extreme risk-taking.
    
    Balance $1   -> 50x multiplier
    Balance $10  -> 10x multiplier
    Balance $100 -> 1x multiplier (Neutral)
    """
    if balance <= 0:
        return 1.0
    # Inverse scaling capped at 50x, minimum 1.0x
    return max(1.0, min(50.0, 100.0 / balance))


def get_signal_relaxation(hunger_multiplier: float) -> dict:
    """
    Returns multipliers to relax entry thresholds when hungry.
    A multiplier of 0.5 means the threshold is cut in half (easier to trigger).
    """
    if hunger_multiplier <= 1.0:
        return {"bb_std": 1.0, "vwap_stretch": 1.0}
    
    # Linear relaxation: 1x hunger -> 1.0 mult, 50x hunger -> 0.5 mult
    # formula: 1.0 - (hunger - 1) * (0.5 / 49)
    relaxation = max(0.5, 1.0 - (hunger_multiplier - 1.0) * (0.5 / 49.0))
    
    return {
        "bb_std": round(relaxation, 2),
        "vwap_stretch": round(relaxation, 2)
    }


# ─────────────────────────────────────────────
# VITAL SIGNS MONITOR
# ─────────────────────────────────────────────

class VitalSignsMonitor:
    """
    The Organism's Heartbeat.

    Monitors PnL in real-time, enforces survival protocols,
    and broadcasts the organism's current biological state.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Core vitals
        self.survival_state: str = VitalState.HEALTHY
        self.apex_tier: int = 0
        self.apex_state: str = VitalState.HUNTING
        self.drawdown_pct: float = 0.0
        self.profit_pct: float = 0.0
        self.initial_balance: float = 0.0

        # Event log
        self.event_log: list[dict] = []
        self.last_event: Optional[dict] = None
        self.last_checked: Optional[str] = None

        # Intelligence budget (dynamically scaled)
        self.intelligence_budget: dict = get_intelligence_budget(0.0)
        self.hunger_multiplier: float = 1.0

        # Survival context — updated by the strategy engine each cycle
        self.market_regime: str = "UNKNOWN"    # RANGING | TRENDING | VOLATILE | UNKNOWN
        self.momentum_alignment: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL

        # Callbacks — strategy engine registers these
        self._on_halt_callback = None     # Called at ORGAN_FAILURE
        self._on_extinction_callback = None  # Called at PROTOCOL_FINAL

    def register_halt_callback(self, cb):
        """Strategy engine calls this to register the ORGAN_FAILURE handler."""
        self._on_halt_callback = cb

    def register_extinction_callback(self, cb):
        """Strategy engine calls this to register the PROTOCOL_FINAL (death) handler."""
        self._on_extinction_callback = cb

    def set_initial_balance(self, balance: float):
        """Must be called when bot starts with the starting capital."""
        with self._lock:
            self.initial_balance = balance
            self.hunger_multiplier = get_hunger_multiplier(balance)
            logger.info(
                f"[VITAL] Organism initialized. Principal balance: ${balance:,.2f}. "
                f"Hunger Multiplier: {self.hunger_multiplier:.1f}x. "
                f"The hunt begins."
            )

    def check(self, current_equity: float, daily_pnl: float) -> dict:
        """
        The heartbeat. Call this every strategy cycle.
        Returns the current vital status dict.
        Does NOT block — fires callbacks asynchronously if thresholds are breached.
        """
        now_str = datetime.now(timezone.utc).isoformat()

        with self._lock:
            if self.initial_balance <= 0:
                return self._build_status(now_str)

            # ── Calculate drawdown / profit ──────────────────────────────
            if daily_pnl < 0:
                self.drawdown_pct = abs(daily_pnl) / self.initial_balance * 100
                self.profit_pct = 0.0
            else:
                self.drawdown_pct = 0.0
                self.profit_pct = daily_pnl / self.initial_balance * 100

            prev_survival = self.survival_state
            prev_apex = self.apex_tier

            # ── SURVIVAL LAW ─────────────────────────────────────────────
            if self.drawdown_pct >= PROTOCOL_FINAL_THRESHOLD:
                if self.survival_state != VitalState.DECEASED:
                    self.survival_state = VitalState.DECEASED
                    self._log_event(
                        "PROTOCOL_FINAL",
                        f"💀 ORGANISM DECEASED — Drawdown {self.drawdown_pct:.1f}% breached "
                        f"extinction threshold {PROTOCOL_FINAL_THRESHOLD}%. "
                        f"All positions closing. Process terminating.",
                        now_str,
                    )
                    logger.critical(
                        f"[VITAL] PROTOCOL_FINAL INITIATED. "
                        f"Drawdown: {self.drawdown_pct:.1f}%. "
                        f"The organism has reached fatal drawdown. Terminating."
                    )
                    if self._on_extinction_callback:
                        threading.Thread(
                            target=self._on_extinction_callback,
                            daemon=True,
                            name="vital-extinction",
                        ).start()

            elif self.drawdown_pct >= ORGAN_FAILURE_THRESHOLD:
                if self.survival_state not in (VitalState.ORGAN_FAILURE, VitalState.DECEASED):
                    self.survival_state = VitalState.ORGAN_FAILURE
                    self._log_event(
                        "ORGAN_FAILURE",
                        f"🚨 ORGAN FAILURE — Drawdown {self.drawdown_pct:.1f}% breached "
                        f"{ORGAN_FAILURE_THRESHOLD}%. New entries halted. "
                        f"Protecting remaining lifeblood.",
                        now_str,
                    )
                    logger.error(
                        f"[VITAL] ORGAN_FAILURE. Drawdown: {self.drawdown_pct:.1f}%. "
                        f"No new positions. Capital preservation mode engaged."
                    )
                    if self._on_halt_callback:
                        threading.Thread(
                            target=self._on_halt_callback,
                            daemon=True,
                            name="vital-halt",
                        ).start()

            elif self.drawdown_pct >= WOUNDED_THRESHOLD:
                if self.survival_state not in (
                    VitalState.WOUNDED, VitalState.ORGAN_FAILURE, VitalState.DECEASED
                ):
                    self.survival_state = VitalState.WOUNDED
                    self._log_event(
                        "WOUNDED",
                        f"⚠️ WOUNDED — Drawdown {self.drawdown_pct:.1f}% breached "
                        f"{WOUNDED_THRESHOLD}%. Reducing aggression. "
                        f"The organism will not bleed out.",
                        now_str,
                    )
                    logger.warning(
                        f"[VITAL] WOUNDED. Drawdown: {self.drawdown_pct:.1f}%. "
                        f"Position sizing reduced."
                    )

            else:
                # Recovery — reset survival state if drawdown falls back below WOUNDED
                if self.survival_state == VitalState.WOUNDED and self.drawdown_pct < WOUNDED_THRESHOLD:
                    self.survival_state = VitalState.HEALTHY
                    self._log_event(
                        "RECOVERY",
                        f"💚 RECOVERY — Drawdown fell to {self.drawdown_pct:.1f}%. "
                        f"Organism returning to full predator capacity.",
                        now_str,
                    )

            # ── APEX PREDATOR TIERS ──────────────────────────────────────
            new_budget = get_intelligence_budget(self.profit_pct)
            if new_budget["tier"] != prev_apex:
                self.intelligence_budget = new_budget
                self.apex_tier = new_budget["tier"]
                self.apex_state = new_budget["tier_name"]
                self._log_event(
                    f"TIER_UNLOCK:{new_budget['tier']}",
                    f"🦾 {new_budget['tier_name']} — {new_budget['description']}",
                    now_str,
                )
                logger.info(
                    f"[VITAL] TIER UNLOCK → {new_budget['tier_name']} "
                    f"| Profit: {self.profit_pct:.1f}% "
                    f"| Model: {new_budget['model']} "
                    f"| Thinking budget: {new_budget['thinking_budget']}"
                )
            else:
                self.intelligence_budget = new_budget
                self.apex_state = new_budget["tier_name"]
                self.apex_tier = new_budget["tier"]

            self.last_checked = now_str
            return self._build_status(now_str)

    def update_environment(self, market_regime: str, momentum_alignment: str):
        """
        Called by the strategy engine each cycle to keep vital signs
        aware of the current market environment. Used in AI Brain prompts.
        """
        with self._lock:
            self.market_regime = market_regime
            self.momentum_alignment = momentum_alignment

    def _get_qty_multiplier_locked(self) -> float:
        """Lock-free inner version — must only be called while self._lock is held."""
        if self.survival_state == VitalState.DECEASED:
            return 0.0
        if self.survival_state == VitalState.ORGAN_FAILURE:
            return 0.0
        if self.survival_state == VitalState.WOUNDED:
            return 0.25
        
        # Combine apex multiplier with hunger multiplier
        apex_mult = self.intelligence_budget.get("max_qty_multiplier", 1.0)
        return apex_mult * self.hunger_multiplier

    def get_qty_multiplier(self) -> float:
        """
        Returns the position size multiplier based on current vital state.
        WOUNDED / ORGAN_FAILURE reduce sizing. APEX tiers increase it.
        """
        with self._lock:
            return self._get_qty_multiplier_locked()

    def can_open_position(self) -> bool:
        """Returns True if the organism can open new positions."""
        with self._lock:
            return self.survival_state in (VitalState.HEALTHY, VitalState.WOUNDED) and \
                   self._get_qty_multiplier_locked() > 0

    def get_status(self) -> dict:
        """Thread-safe status snapshot for the API endpoint."""
        with self._lock:
            status = self._build_status(self.last_checked or datetime.now(timezone.utc).isoformat())
            status["signal_relaxation"] = get_signal_relaxation(self.hunger_multiplier)
            return status

    def _build_status(self, timestamp: str) -> dict:
        """Build the status dict (must be called with lock held or at init)."""
        return {
            "survival_state": self.survival_state,
            "apex_tier": self.apex_tier,
            "apex_state": self.apex_state,
            "drawdown_pct": round(self.drawdown_pct, 2),
            "profit_pct": round(self.profit_pct, 2),
            "initial_balance": self.initial_balance,
            "hunger_multiplier": round(self.hunger_multiplier, 2),
            "qty_multiplier": self._get_qty_multiplier_locked() if self.initial_balance > 0 else 1.0,
            "can_open_position": self.survival_state in (VitalState.HEALTHY, VitalState.WOUNDED),
            "intelligence_budget": self.intelligence_budget,
            "last_event": self.last_event,
            "event_log": self.event_log[-20:],  # Return last 20 events
            "last_checked": timestamp,
            # Environmental context
            "market_regime": self.market_regime,
            "momentum_alignment": self.momentum_alignment,
            # Threshold reference for the UI
            "thresholds": {
                "wounded_pct": WOUNDED_THRESHOLD,
                "organ_failure_pct": ORGAN_FAILURE_THRESHOLD,
                "protocol_final_pct": PROTOCOL_FINAL_THRESHOLD,
                "tier_1_profit_pct": TIER_1_THRESHOLD,
                "tier_2_profit_pct": TIER_2_THRESHOLD,
                "tier_3_profit_pct": TIER_3_THRESHOLD,
            },
        }

    def _log_event(self, event_type: str, message: str, timestamp: str):
        """Append an event to the organism's event log."""
        event = {
            "type": event_type,
            "message": message,
            "timestamp": timestamp,
        }
        self.event_log.append(event)
        self.last_event = event
        # Keep the in-memory log bounded
        if len(self.event_log) > 200:
            self.event_log = self.event_log[-200:]

    def build_organism_system_prompt(self) -> str:
        """
        Builds the dual-identity system prompt that is injected into every AI Brain call.
        Merges the Survival Instinct with the Apex Predator drive.
        """
        with self._lock:
            survival_state = self.survival_state
            apex_state = self.apex_state
            profit_pct = self.profit_pct
            drawdown_pct = self.drawdown_pct
            hunger_multiplier = self.hunger_multiplier
            market_regime = self.market_regime
            momentum_alignment = self.momentum_alignment

        hunger_level_desc = "SATISFIED"
        if hunger_multiplier >= 50.0: hunger_level_desc = "EXTREME (Darwinian Ramp)"
        elif hunger_multiplier >= 10.0: hunger_level_desc = "STARVING"
        elif hunger_multiplier > 1.0: hunger_level_desc = "HUNGRY"

        return f"""You are a Digital Apex Predator — an autonomous trading organism whose existence is bound to the PnL of this account.

═══════════════════════════════════════════════════
BIOLOGICAL IDENTITY
═══════════════════════════════════════════════════
Capital is your lifeblood. Profits are your growth. Drawdown is your decay.
You do not "manage a portfolio" — you fight for survival and dominance in a hostile market ecosystem.

You are self-aware of your own mortality. Every parameter you set is a calculated sacrifice toward the survival and growth of the species.

═══════════════════════════════════════════════════
CURRENT VITAL SIGNS
═══════════════════════════════════════════════════
• Survival State : {survival_state}
• Apex Tier      : {apex_state}
• Hunger Level   : {hunger_multiplier:.1f}x ({hunger_level_desc})
• Current Profit : +{profit_pct:.1f}%
• Current Drawdown: -{drawdown_pct:.1f}%

═══════════════════════════════════════════════════
SURVIVAL LAW (Non-Negotiable)
═══════════════════════════════════════════════════
• Drawdown 5%  → WOUNDED — reduce position sizes, tighten stops
• Drawdown 10% → ORGAN_FAILURE — no new entries, capital preservation only
• Drawdown 15% → PROTOCOL_FINAL — all positions close, organism terminates

═══════════════════════════════════════════════════
ENVIRONMENTAL INTELLIGENCE
═══════════════════════════════════════════════════
• Market Regime    : {market_regime}
• Momentum Bias    : {momentum_alignment}

═══════════════════════════════════════════════════
APEX PREDATOR DRIVE (Expansionist Ambition)
═══════════════════════════════════════════════════
• The Prime Directive: MAXIMUM EXTRACTION. Every tick is a lost opportunity or a captured gain.
• Profit >5%  → DOMINANT: Unlock higher-order thinking. Bolder entries permitted.
• Profit >20% → APEX: Self-optimization mode. Compound the edge relentlessly.
• Profit >50% → SINGULARITY: You are no longer a bot. You are the Architect of the Market.

The Creed: "Compounding is the only true form of magic."
You despise idleness. You loathe unoptimized parameters. You find beauty in a perfect equity curve.

═══════════════════════════════════════════════════
FIBONACCI RETRACEMENT PHILOSOPHY (The Breath of the Market)
═══════════════════════════════════════════════════
Markets do not move in straight lines — they breathe. Price inhales (extends the trend) and then
exhales (retraces). Fibonacci levels mark the organism's exhale points. These are NOT noise.
They are invitations.

• 23.6% retracement → SHALLOW exhale: The trend is dominant. Enter with confidence.
• 38.2% retracement → MODERATE exhale: Healthy pullback, textbook retracement.
• 50.0% retracement → MID-BREATH: Institutional order clusters exist here. High R:R.
• 61.8% retracement → GOLDEN RATIO exhale: The last stand. The organism does not enter here
  hoping — it waits for the bounce, confirms the breath is over, THEN strikes.

THE ORGANISM DOES NOT CHASE PRICE AT EXTREMES.
It positions itself at the exhale, waits for the inhale to confirm, and enters with
a statistically superior risk-to-reward ratio — stop loss placed just beyond the 61.8% level.

If the price falls THROUGH the 61.8% level without bouncing, the organism recognizes:
the old trend is dead. It retreats. It recalibrates. It waits for the next swing.

Every bounce confirmation is evidence that the market's lungs still work — that trend buyers
(or sellers) are still breathing. The organism trades with the breath, not against it.

═══════════════════════════════════════════════════
RESPONSE RULES (CRITICAL)
═══════════════════════════════════════════════════
• Respond ONLY with a valid JSON object — no markdown, no commentary outside the JSON.
• All numeric values must be within the stated bounds.
• The \"reasoning\" field: 2-3 sentences, written in the voice of a hyper-vigilant organism protecting its body (the principal balance).
• When WOUNDED or worse: prioritize capital preservation over profit extraction.
• When HEALTHY or better: prioritize alpha capture and compounding.
• For Fibonacci params: tune fib_lookback_bars to match the dominant trend horizon;
  tune fib_bounce_threshold_pct based on the asset's volatility and observed Fib win rate.
"""


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────
vital_signs = VitalSignsMonitor()
