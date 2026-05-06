# TradeClaw — ATLAS Gap Implementation Plan
**Date:** 2026-05-06  
**Source:** ATLAS_GAP_ANALYSIS.md  
**Scope:** Four targeted improvements — Darwinian weights, weighted deliberation, CRO agent, macro veto power — plus a fifth (prompt autoresearch) as a follow-on phase.

---

## Guiding Constraints

- **Preserve all existing IP**: Spirit Animals, Situation Room, ICT confluence, Apex Predator vital signs, TWAP execution, fleet isolation. No file containing these changes.
- **Additive where possible**: new agents, new fields, new cycles. Avoid rewriting working logic.
- **Backwards compatible**: existing bots without new config fields must behave identically to today.
- **No new infrastructure dependencies** for phases 1–4. Phase 5 adds a git dependency (already present).

---

## Phase 1 — Darwinian Agent Weights + Weighted Deliberation
**Files:** `sub_agents.py`, `bot_vital_signs.py`, `firebase_store.py`  
**Effort:** 2–3 days  
**Dependency:** None (first thing to implement)

### What changes

The hardcoded `agent_weights` dict inside `deliberate()` becomes live, performance-tracked values per agent. A daily job adjusts them based on whether each agent's vote on a closed trade was correct. The quorum threshold (`agree_count >= 3`) is replaced with a continuous weighted net-score gate.

---

### 1.1 — Add `darwinian_weight` to `AgentVote`

**File:** `sub_agents.py:74–85` (`AgentVote` dataclass)

Add a `darwinian_weight` field alongside the existing `weight` field. Keep `weight` as the static per-call override (Watchman still gets 1.25 to reflect its real-time market-quality role). `darwinian_weight` tracks long-run performance and is applied on top.

```python
@dataclass
class AgentVote:
    agent: str
    vote: str
    confidence: float
    reasoning: str
    weight: float = 1.0           # Static per-call weight (unchanged)
    darwinian_weight: float = 1.0  # ← ADD: performance-adjusted multiplier [0.3, 2.5]
    veto_reason: Optional[str] = None
    timestamp: str = ...
```

The effective vote weight used in deliberation becomes `weight * darwinian_weight`.

---

### 1.2 — `DarwinianWeightStore` class

**File:** `sub_agents.py` (new class, insert before `SubAgentPool`)

This class owns the weight state for all agents of one bot. It is instantiated once per bot (by `SubAgentPool.__init__`) and persists weights to Firestore.

```python
class DarwinianWeightStore:
    """
    Tracks and updates per-agent Darwinian weights for one bot.

    Weight bounds: [FLOOR=0.3, CEILING=2.5], starting at 1.0.
    Update rule (applied after each closed trade):
      · Top-quartile agents (vote matched direction, trade profitable): weight *= 1.05
      · Bottom-quartile agents (vote opposed direction, trade was a loss): weight *= 0.95
      · Capped to [FLOOR, CEILING]

    The daily_update() method is called by BotVitalSigns.update() or the
    fleet monitor loop — not on every tick.
    """

    FLOOR   = 0.3
    CEILING = 2.5
    UP_FACTOR   = 1.05
    DOWN_FACTOR = 0.95

    # Agents that have static roles and should NOT be Darwinian-weighted
    # (Watchman is pure-math market quality; RiskManager is Kelly gating).
    EXCLUDED = {"watchman", "risk_manager", "ict"}

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._lock = threading.Lock()
        # Initial neutral weights for all panel agents
        self._weights: dict[str, float] = {
            "sentiment":  1.0,
            "macro":      1.0,
            "earnings":   1.5,   # earnings keeps its elevated static weight as starting point
            "technical":  0.75,
            "cro":        1.5,   # CRO (Phase 2) starts elevated — adversarial voice should be heard
        }
        # Outcome log for rolling Sharpe per agent
        # Each entry: {"agent": str, "voted": str, "trade_direction": str, "pnl": float}
        self._outcome_log: list[dict] = []
        self._logger = logging.getLogger(f"tradeclaw.darwin[{bot_id}]")

    def get_weight(self, agent_name: str) -> float:
        """Return the current Darwinian weight for an agent (default 1.0)."""
        if agent_name in self.EXCLUDED:
            return 1.0
        with self._lock:
            return self._weights.get(agent_name, 1.0)

    def record_outcome(self, votes: list[dict], trade_direction: str, pnl: float):
        """
        Called after a trade closes. Attributes the outcome to each agent
        that voted before the entry.

        votes: the AgentVote.to_dict() list from the TradeDecision that approved the entry.
        trade_direction: "BUY" or "SELL" (the direction that was actually taken).
        pnl: the realised PnL of the closed trade.
        """
        with self._lock:
            for vote_dict in votes:
                agent = vote_dict.get("agent", "")
                if agent in self.EXCLUDED:
                    continue
                self._outcome_log.append({
                    "agent":           agent,
                    "voted":           vote_dict.get("vote", "HOLD"),
                    "trade_direction": trade_direction,
                    "pnl":             pnl,
                    "ts":              datetime.now(timezone.utc).isoformat(),
                })
            # Keep the log bounded (last 200 outcomes)
            self._outcome_log = self._outcome_log[-200:]

    def daily_update(self):
        """
        Apply one round of Darwinian selection.
        Called once per day (or after N closed trades) by the fleet monitor.

        Algorithm:
          1. For each agent, compute a rolling agreement-weighted Sharpe over
             the last 60 outcomes.
          2. Rank agents by their score.
          3. Top quartile: weight *= UP_FACTOR (capped at CEILING).
          4. Bottom quartile: weight *= DOWN_FACTOR (floored at FLOOR).
          5. Log the new weights.
        """
        import numpy as np

        with self._lock:
            outcomes = list(self._outcome_log)

        if not outcomes:
            return

        # Compute per-agent scores
        agent_scores: dict[str, float] = {}
        for agent in set(o["agent"] for o in outcomes):
            agent_outcomes = [o for o in outcomes if o["agent"] == agent][-60:]
            if len(agent_outcomes) < 3:
                continue  # Not enough data to rank yet

            returns = []
            for o in agent_outcomes:
                # Correct vote on a profitable trade = positive return
                voted_correctly = (o["voted"] == o["trade_direction"])
                signed_pnl = o["pnl"] if voted_correctly else -o["pnl"]
                returns.append(signed_pnl)

            if len(returns) < 2:
                continue
            mean_r = float(np.mean(returns))
            std_r  = float(np.std(returns))
            agent_scores[agent] = mean_r / std_r if std_r > 0 else 0.0

        if len(agent_scores) < 2:
            return  # Can't rank with fewer than 2 agents

        sorted_agents = sorted(agent_scores.keys(), key=lambda a: agent_scores[a])
        n = len(sorted_agents)
        top_cutoff    = max(1, n // 4)
        bottom_cutoff = max(1, n // 4)

        top_agents    = set(sorted_agents[-top_cutoff:])
        bottom_agents = set(sorted_agents[:bottom_cutoff])

        with self._lock:
            for agent in self._weights:
                if agent in self.EXCLUDED:
                    continue
                if agent in top_agents:
                    self._weights[agent] = min(self.CEILING, self._weights[agent] * self.UP_FACTOR)
                    self._logger.info(f"[Darwin] {agent} ↑ {self._weights[agent]:.3f} (top quartile)")
                elif agent in bottom_agents:
                    self._weights[agent] = max(self.FLOOR, self._weights[agent] * self.DOWN_FACTOR)
                    self._logger.info(f"[Darwin] {agent} ↓ {self._weights[agent]:.3f} (bottom quartile)")

    def get_all_weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._weights)
```

---

### 1.3 — Wire `DarwinianWeightStore` into `SubAgentPool`

**File:** `sub_agents.py:863–903` (`SubAgentPool.__init__`)

```python
# In SubAgentPool.__init__, add after self._logger = ...:
self._darwin = DarwinianWeightStore(bot_id)
```

---

### 1.4 — Replace hardcoded weights in `deliberate()`

**File:** `sub_agents.py:1041–1042`

Current:
```python
agent_weights = {"sentiment": 1.0, "macro": 1.0, "earnings": 1.5, "technical": 0.75}
```

Replace with:
```python
# Static base weights × live Darwinian multipliers
_static = {"sentiment": 1.0, "macro": 1.0, "earnings": 1.5, "technical": 0.75}
agent_weights = {
    name: base * self._darwin.get_weight(name)
    for name, base in _static.items()
}
```

---

### 1.5 — Replace quorum threshold with weighted net-score

**File:** `sub_agents.py:1180` (the `quorum_met` and `weighted_score` calculation block)

Current:
```python
quorum_met = agree_count >= 3 or (agree_count / total_panel >= 0.6)
total_weight = sum(v.weight for v in panel_votes) or 1.0
weighted_score = sum(
    v.weight * v.confidence * (1 if v.vote == raw_signal else -1 if ... else 0)
    for v in panel_votes
) / total_weight
```

Replace with:
```python
# Weighted net-score using effective weight (static × Darwinian)
total_weight = sum(v.weight * v.darwinian_weight for v in panel_votes) or 1.0
weighted_score = sum(
    (v.weight * v.darwinian_weight) * v.confidence
    * (1 if v.vote == raw_signal else -1 if v.vote not in ("HOLD", "VETO") else 0)
    for v in panel_votes
) / total_weight

# Score must clear 0.25 (slightly tighter than old 0.2 to compensate for
# removing the raw agree_count gate — weights now do that work)
quorum_met = weighted_score >= 0.25
```

Remove the `agree_count` variable entirely — it is no longer used.

---

### 1.6 — Record outcomes after trade closes

**File:** `bot_engine.py:_close_position()` and the post-fill block in `_live_tick()` (lines ~1338–1404)

After `self.total_realized_pnl += pnl` is set on a closed trade:

```python
# Attribute trade outcome to the agents that approved the entry
if self._sub_agent_pool and self.last_deliberation:
    entry_votes = self.last_deliberation.get("votes", [])
    self._sub_agent_pool._darwin.record_outcome(
        votes=entry_votes,
        trade_direction=self.position_side,   # "LONG" or "SHORT" at time of entry
        pnl=pnl,
    )
```

---

### 1.7 — Expose Darwinian weights in Situation Room

**File:** `bot_engine.py:get_state_snapshot()`

Add to the returned dict:
```python
"agent_weights": self._sub_agent_pool._darwin.get_all_weights()
    if self._sub_agent_pool else {},
```

The frontend Situation Room already renders the `last_deliberation` dict. Adding `agent_weights` alongside it gives the UI a "trust ranking" column to display per agent.

---

### 1.8 — Daily weight update trigger

**File:** `fleet.py` (the fleet monitor loop that already runs DB flush and vital sign updates)

In the existing periodic monitor loop, add:
```python
# Once per trading day (or every 6 hours — fleet can check elapsed time)
for bot_id, instance in self._bots.items():
    if instance.sub_agent_pool:
        instance.sub_agent_pool._darwin.daily_update()
```

---

## Phase 2 — Adversarial CRO Agent
**Files:** `sub_agents.py`, `bot_config.py`  
**Effort:** 1–2 days  
**Dependency:** Phase 1 (needs Darwinian weight infrastructure)

### What changes

A new `CROAgent` class is added. Its sole job is to attack the trade thesis and return a VETO if it finds ≥ 2 structural objections. It is wired into `deliberate()` after the panel votes but before the RiskManager's Kelly gate.

---

### 2.1 — `CROAgent` class

**File:** `sub_agents.py` (add after `RiskManagerAgent`, before `AGENT_CLASSES`)

```python
class CROAgent(BaseAgent):
    """
    Chief Risk Officer — Adversarial Agent.

    Receives the proposed trade and actively generates reasons NOT to take it.
    Issues VETO if >= 2 structural objections are found.

    This agent does NOT forecast direction. It only blocks bad entries.
    Prompt persona: a skeptical, risk-first analyst who has been burned before
    and whose job security depends on stopping bad trades, not enabling them.

    Veto conditions it checks:
      · Upcoming earnings within 48h (catalyst risk)
      · Macro regime RISK_OFF (VIX > 25, or macro agent sentiment < -0.5)
      · Position correlated with another open position in the fleet
      · Conviction not justified by recent agent disagreement
      · Price extended far from VWAP (overextension risk)
    """

    AGENT_NAME = "cro"
    TIMEOUT_SECONDS = 90

    def run(self) -> AgentSignal:
        # CRO does not produce a general market signal — return neutral for AI Brain compat
        return AgentSignal.neutral(self.AGENT_NAME, "CRO is an adversarial gating agent.")

    def get_vote(
        self,
        raw_signal: str,
        symbol: str,
        panel_votes: list["AgentVote"],
        macro_signal: Optional["AgentSignal"] = None,
        price_history=None,
    ) -> "AgentVote":
        """
        Evaluate structural risks and return a vote or VETO.

        Parameters:
            raw_signal:   "BUY" or "SELL" from the Strategist
            symbol:       trading symbol
            panel_votes:  already-cast votes from the panel
            macro_signal: the MacroAgent's latest AgentSignal (if available)
            price_history: deque of price bars for VWAP/extension checks
        """
        objections: list[str] = []

        # ── Objection 1: Macro regime RISK_OFF ─────────────────────────
        if macro_signal and macro_signal.sentiment < -0.5 and macro_signal.confidence > 0.5:
            objections.append(
                f"Macro regime RISK_OFF (sentiment={macro_signal.sentiment:.2f}). "
                f"Reason: {macro_signal.reasoning[:100]}"
            )

        # ── Objection 2: Panel strongly disagrees ───────────────────────
        oppose_count = sum(
            1 for v in panel_votes
            if v.vote not in (raw_signal, "HOLD", "VETO")
            and v.confidence > 0.6
        )
        if oppose_count >= 2:
            objections.append(
                f"{oppose_count} high-confidence panel agents oppose this {raw_signal}. "
                f"Significant disagreement without consensus is a structural red flag."
            )

        # ── Objection 3: LLM-generated structural check ─────────────────
        # Ask the LLM to find one more structural reason not to trade.
        panel_summary = "; ".join(
            f"{v.agent}={v.vote}({v.confidence:.1f})" for v in panel_votes
        )
        system = (
            "You are the Chief Risk Officer of a trading firm. Your job is to stop bad trades. "
            "You are NOT trying to be helpful to the trader — you are trying to protect capital. "
            "Given the proposed trade, find ONE specific structural reason NOT to take it. "
            "If you genuinely cannot find a valid reason, say so honestly. "
            "Respond with only this JSON: "
            '{"objection": "<one sentence reason, or empty string if none>", '
            '"severity": <float 0.0 to 1.0>, '
            '"confidence": <float 0.0 to 1.0>}'
        )
        prompt = (
            f"Proposed trade: {raw_signal} {symbol}\n"
            f"Panel votes: {panel_summary}\n"
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"Find ONE structural reason not to take this trade. "
            f"Consider: earnings risk, macro headwinds, sector rotation, "
            f"overextension from VWAP, or correlated risk."
        )

        raw = self._call_ollama(prompt)
        if not raw:
            raw = self._call_openclaw(system, prompt, include_search=False)

        if raw:
            try:
                parsed = self._extract_json(raw)
                obj = parsed.get("objection", "").strip()
                severity = float(parsed.get("severity", 0.0))
                confidence = float(parsed.get("confidence", 0.0))
                if obj and severity > 0.5 and confidence > 0.5:
                    objections.append(f"[LLM CRO] {obj}")
            except Exception as e:
                self._logger.debug(f"CRO LLM parse error: {e}")

        # ── Verdict ─────────────────────────────────────────────────────
        if len(objections) >= 2:
            reason = " | ".join(objections)
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=0.9,
                reasoning=f"CRO VETO: {len(objections)} structural objections: {reason[:300]}",
                weight=1.5,
                darwinian_weight=self._darwin_weight if hasattr(self, "_darwin_weight") else 1.0,
                veto_reason=reason[:200],
            )

        # One objection or none — do not veto, but flag in reasoning
        flag = f" [CRO flagged: {objections[0][:100]}]" if objections else ""
        return AgentVote(
            agent=self.AGENT_NAME,
            vote=raw_signal,   # No objection strong enough — defer to panel
            confidence=0.7,
            reasoning=f"CRO review complete. No structural veto.{flag}",
            weight=1.5,
            darwinian_weight=1.0,
        )
```

---

### 2.2 — Register `CROAgent` in the agent factory

**File:** `sub_agents.py:AGENT_CLASSES` dict (~line 819)

```python
AGENT_CLASSES = {
    "sentiment":    SentimentAgent,
    "macro":        MacroAgent,
    "earnings":     EarningsAgent,
    "technical":    TechnicalAgent,
    "watchman":     WatchmanAgent,
    "risk_manager": RiskManagerAgent,
    "ict":          ICTAgent,
    "cro":          CROAgent,   # ← ADD
}
```

---

### 2.3 — Register in `bot_config.py`

**File:** `bot_config.py:29–45` (`SUB_AGENT_*` constants and `VALID_SUB_AGENTS`)

```python
SUB_AGENT_CRO = "cro"   # ← ADD

VALID_SUB_AGENTS = {
    SUB_AGENT_SENTIMENT,
    SUB_AGENT_MACRO,
    SUB_AGENT_EARNINGS,
    SUB_AGENT_TECHNICAL,
    SUB_AGENT_WATCHMAN,
    SUB_AGENT_RISK_MANAGER,
    SUB_AGENT_ICT,
    SUB_AGENT_CRO,    # ← ADD
}
```

Default sub_agents list in `BotConfig` does not include CRO by default. Users opt in via bot config. This keeps existing bots unaffected.

---

### 2.4 — Wire CRO into `deliberate()`

**File:** `sub_agents.py:deliberate()` — add after the panel vote loop (after line ~1114), before the veto check block.

```python
# ── CRO Adversarial Review ────────────────────────────────────────
if "cro" in self.enabled_agents:
    try:
        cro_agent = CROAgent(
            bot_id=self.bot_id, symbol=self.symbol,
            openclaw_client=self._openclaw_client,
            openclaw_model=self._openclaw_model,
            ollama_base_url=self._ollama_base_url,
            ollama_model=self._ollama_model,
        )
        macro_signal = current_signals.get("macro")
        cro_vote = cro_agent.get_vote(
            raw_signal=raw_signal,
            symbol=self.symbol,
            panel_votes=[v for v in votes if v.agent not in ("watchman", "ict", "risk_manager")],
            macro_signal=macro_signal,
            price_history=price_history,
        )
        votes.append(cro_vote)
        if cro_vote.vote == "VETO":
            veto_agents.append(cro_vote.agent)
    except Exception as e:
        self._logger.warning(f"CROAgent error: {e}")
```

The existing veto check block below this handles the new `cro` entry in `veto_agents` automatically — no other changes needed.

---

## Phase 3 — MacroAgent Veto Power (RISK_OFF Override)
**Files:** `sub_agents.py`  
**Effort:** 1 day  
**Dependency:** Phase 1 (Darwinian weights must be in place)

### What changes

The MacroAgent is upgraded from a panel voter (one of four equal voices) to a tier-1 pre-filter. When the macro regime is clearly RISK_OFF (macro sentiment below a threshold AND confidence is high), the trade is blocked before the panel even votes. This prevents the macro signal from being democratically outvoted on regime calls.

The existing `MacroAgent.run()` output is used — no change to the agent itself. The change is in `deliberate()`.

---

### 3.1 — Add macro pre-filter to `deliberate()`

**File:** `sub_agents.py:deliberate()` — add after the ICT vote block (~line 1040), before the LLM panel loop.

```python
# ── PHASE 3: Macro Regime Pre-Filter ─────────────────────────────
# If MacroAgent's latest read is strongly RISK_OFF with high confidence,
# block directional entries regardless of panel sentiment.
# Threshold: sentiment < -0.6 AND confidence > 0.65
# This veto CANNOT be outvoted — macro regime is a category gate.
MACRO_VETO_SENTIMENT  = -0.6   # Below this = RISK_OFF
MACRO_VETO_CONFIDENCE = 0.65   # Agent must be this confident to trigger

if "macro" in self.enabled_agents:
    macro_sig = current_signals.get("macro")

    # If macro signal is stale or missing, refresh it now
    if macro_sig is None or (time.time() - self._vote_timestamps.get("macro", 0)) > vote_cache_ttl:
        try:
            _macro_agent = MacroAgent(
                bot_id=self.bot_id, symbol=self.symbol,
                openclaw_client=self._openclaw_client,
                openclaw_model=self._openclaw_model,
                ollama_base_url=self._ollama_base_url,
                ollama_model=self._ollama_model,
            )
            macro_sig = _macro_agent.run()
            with self._lock:
                self.latest_signals["macro"] = macro_sig
            self._vote_timestamps["macro"] = time.time()
        except Exception as e:
            self._logger.warning(f"Macro pre-filter refresh failed: {e}")

    if (
        macro_sig is not None
        and macro_sig.sentiment < MACRO_VETO_SENTIMENT
        and macro_sig.confidence > MACRO_VETO_CONFIDENCE
        and raw_signal == "BUY"   # Only gate BUY entries in RISK_OFF; SELL (short) can proceed
    ):
        macro_veto_vote = AgentVote(
            agent="macro",
            vote="VETO",
            confidence=macro_sig.confidence,
            reasoning=(
                f"MACRO RISK_OFF OVERRIDE: sentiment={macro_sig.sentiment:.2f} "
                f"(threshold {MACRO_VETO_SENTIMENT}). {macro_sig.reasoning[:150]}"
            ),
            weight=2.0,
            veto_reason=f"Macro regime RISK_OFF (sentiment={macro_sig.sentiment:.2f})",
        )
        decision = TradeDecision(
            approved=False,
            signal=raw_signal,
            approved_qty=0,
            order_urgency="LOW",
            quorum_score=0.0,
            votes=[macro_veto_vote.to_dict()],
            veto_agents=["macro"],
            reasoning=macro_veto_vote.reasoning,
        )
        with self._lock:
            self.last_deliberation = decision
        self._logger.warning(
            f"[{self.bot_id}] MACRO RISK_OFF VETO — {macro_veto_vote.reasoning}"
        )
        return decision
```

**Notes:**
- `raw_signal == "BUY"` guard: in a RISK_OFF environment, BUY entries are blocked but SELL (short entries if enabled) may proceed — the macro tailwind supports shorts.
- Thresholds (`-0.6` / `0.65`) should be configurable via `BotConfig` in a later iteration, but are constants for now.
- The macro agent's vote still appears in the panel loop below (it is a normal panel member after this pre-check). If the pre-filter didn't fire, the macro agent contributes to the weighted score normally.

---

## Phase 4 — Prompt-Level Autoresearch Loop
**Files:** New `backend/prompts/` directory + new `backend/prompt_autoresearcher.py`  
**Effort:** 3–5 days  
**Dependency:** Phases 1–3 complete (needs Darwinian weight data and per-agent outcome tracking)

### What changes

Each LLM-based agent gets a prompt file that can be evolved independently. A weekly autoresearch cycle identifies the worst-performing agent (lowest rolling Sharpe), generates a single targeted prompt modification, tests it for 5 trading days via a git branch, and commits or reverts based on Sharpe improvement.

This does NOT replace the existing AI Brain parameter evolution. Both run in parallel.

---

### 4.1 — Create prompt file directory

```
backend/
  prompts/
    sentiment_agent.md    ← SentimentAgent's system + user prompt template
    macro_agent.md        ← MacroAgent's system + user prompt template
    earnings_agent.md     ← EarningsAgent's system + user prompt template
    technical_agent.md    ← TechnicalAgent's system + user prompt template
    cro_agent.md          ← CROAgent's adversarial prompt template
```

Each file contains a YAML front-matter block with metadata plus the full prompt text:

```markdown
---
agent: sentiment
version: 1
created: 2026-05-06
sharpe: null
last_modified: 2026-05-06
---

## System Prompt
You are a professional market sentiment analyst...

## User Prompt Template
Analyse the following real-time headlines for {symbol}...
```

**Migration step:** Extract the inline system/prompt strings from each agent class in `sub_agents.py` into these files. Replace the inline strings with a `_load_prompt(agent_name)` call.

---

### 4.2 — `_load_prompt()` helper

**File:** `sub_agents.py` (new module-level function)

```python
import os

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _load_prompt(agent_name: str) -> dict:
    """
    Load system and user prompt template from prompts/<agent_name>_agent.md.
    Falls back to inline defaults if the file doesn't exist.
    Returns {"system": str, "user_template": str}.
    """
    path = os.path.join(_PROMPTS_DIR, f"{agent_name}_agent.md")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            content = f.read()
        # Split on the section headers
        system = ""
        user_tpl = ""
        if "## System Prompt" in content:
            parts = content.split("## System Prompt", 1)[1]
            if "## User Prompt Template" in parts:
                system_raw, user_raw = parts.split("## User Prompt Template", 1)
                system   = system_raw.strip()
                user_tpl = user_raw.strip()
            else:
                system = parts.strip()
        return {"system": system, "user_template": user_tpl}
    except Exception:
        return {}
```

Each agent's `run()` method checks `_load_prompt(self.AGENT_NAME)` and uses the file content if present, otherwise falls back to the inline string. This is one line change per agent.

---

### 4.3 — Recommendation tracking in Firestore

**File:** `firebase_store.py` (new functions)

Each time an LLM agent casts a vote, log the recommendation so we can score it against forward returns:

```python
async def log_agent_recommendation(
    bot_id: str,
    agent_name: str,
    symbol: str,
    direction: str,      # "BUY" | "SELL" | "HOLD"
    confidence: float,
    signal_price: float,
    timestamp: str,
):
    """Store one agent vote for later Sharpe attribution."""
    ...

async def update_agent_recommendation_outcome(
    bot_id: str,
    agent_name: str,
    timestamp: str,
    forward_return_1d: float,
    forward_return_5d: float,
):
    """Called after 1d and 5d to score the prediction."""
    ...

async def get_agent_sharpe(bot_id: str, agent_name: str, lookback_days: int = 60) -> float:
    """Compute rolling Sharpe for one agent's recommendations."""
    ...
```

The recommendation log is keyed at `bots/{bot_id}/agent_recommendations/{timestamp}_{agent}`.

---

### 4.4 — `PromptAutoResearcher` class

**File:** `backend/prompt_autoresearcher.py` (new file)

```python
"""
TradeClaw — Prompt-Level Autoresearch
=======================================
Weekly cycle that evolves agent prompts (not parameters) using git branches.

Inspired by ATLAS autoresearch. The prompt is the intelligence.
Each week:
  1. Identify worst-performing agent (lowest rolling Sharpe over 60 days).
  2. Generate ONE targeted prompt modification via LLM.
  3. git checkout -b autoresearch/<agent>-<date>
  4. Write modified prompt to prompts/<agent>_agent.md.
  5. Run for 5 trading days.
  6. Compare new Sharpe vs baseline.
  7. git merge (kept) or git checkout main + branch delete (reverted).
"""

import subprocess
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from openai import OpenAI

logger = logging.getLogger("tradeclaw.autoresearch")


AUTORESEARCH_CYCLE_DAYS = 7      # Run once per week
EVALUATION_PERIOD_DAYS  = 5      # 5 trading days per branch
MIN_SHARPE_SAMPLE       = 20     # Minimum recommendations to compute meaningful Sharpe


class PromptAutoResearcher:
    """
    Manages the weekly prompt autoresearch cycle for one bot.
    Can be run as a daemon thread or triggered manually.
    """

    def __init__(self, bot_id: str, openclaw_client: OpenAI, openclaw_model: str):
        self.bot_id = bot_id
        self._client = openclaw_client
        self._model  = openclaw_model
        self._logger = logging.getLogger(f"tradeclaw.autoresearch[{bot_id}]")
        self._active_branch: Optional[str] = None
        self._branch_agent:  Optional[str] = None
        self._branch_start:  Optional[datetime] = None
        self._baseline_sharpe: float = 0.0

    # ── Main entry point ────────────────────────────────────────────

    def run_cycle(self):
        """
        Called by the fleet monitor weekly. Determines whether to:
          A) Start a new branch (if no active branch)
          B) Evaluate an existing branch (if past the evaluation period)
          C) Do nothing (still within evaluation period)
        """
        if self._active_branch is None:
            self._start_new_branch()
        elif self._evaluation_complete():
            self._evaluate_and_decide()

    # ── Branch lifecycle ─────────────────────────────────────────────

    def _start_new_branch(self):
        """Identify worst agent, generate prompt modification, create git branch."""
        from firebase_store import get_agent_sharpe  # imported inline to avoid circular
        import asyncio

        # Step 1: Find worst-performing agent
        agents = ["sentiment", "macro", "earnings", "technical", "cro"]
        sharpes = {}
        for agent in agents:
            try:
                loop = asyncio.get_event_loop()
                sharpe = loop.run_until_complete(
                    get_agent_sharpe(self.bot_id, agent, lookback_days=60)
                )
                sharpes[agent] = sharpe if sharpe is not None else 0.0
            except Exception:
                sharpes[agent] = 0.0

        if not sharpes:
            return

        worst_agent = min(sharpes, key=sharpes.get)
        self._baseline_sharpe = sharpes[worst_agent]
        self._logger.info(
            f"Autoresearch: worst agent = {worst_agent} "
            f"(Sharpe={self._baseline_sharpe:.3f})"
        )

        # Step 2: Generate ONE targeted prompt modification
        current_prompt = _load_prompt(worst_agent)
        modification = self._generate_modification(worst_agent, current_prompt, sharpes)
        if not modification:
            self._logger.warning(f"Autoresearch: no modification generated for {worst_agent}")
            return

        # Step 3: Create git branch
        branch_name = (
            f"autoresearch/{worst_agent}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        )
        try:
            subprocess.run(["git", "checkout", "-b", branch_name], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self._logger.error(f"Git branch creation failed: {e.stderr.decode()}")
            return

        # Step 4: Write modified prompt
        try:
            self._write_modified_prompt(worst_agent, modification)
            subprocess.run(
                ["git", "add", f"backend/prompts/{worst_agent}_agent.md"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"autoresearch: {worst_agent} prompt modification\n\n{modification['rationale']}"],
                check=True, capture_output=True,
            )
        except Exception as e:
            self._logger.error(f"Prompt write/commit failed: {e}")
            subprocess.run(["git", "checkout", "main"], capture_output=True)
            return

        self._active_branch  = branch_name
        self._branch_agent   = worst_agent
        self._branch_start   = datetime.now(timezone.utc)
        self._logger.info(f"Autoresearch: branch {branch_name} created. Running for {EVALUATION_PERIOD_DAYS} trading days.")

    def _evaluation_complete(self) -> bool:
        if not self._branch_start:
            return False
        elapsed = (datetime.now(timezone.utc) - self._branch_start).days
        return elapsed >= EVALUATION_PERIOD_DAYS

    def _evaluate_and_decide(self):
        """Compare new Sharpe against baseline. Merge or revert."""
        from firebase_store import get_agent_sharpe
        import asyncio

        agent = self._branch_agent
        try:
            loop = asyncio.get_event_loop()
            new_sharpe = loop.run_until_complete(
                get_agent_sharpe(self.bot_id, agent, lookback_days=EVALUATION_PERIOD_DAYS)
            ) or 0.0
        except Exception:
            new_sharpe = 0.0

        improved = new_sharpe > self._baseline_sharpe

        self._logger.info(
            f"Autoresearch eval: {agent} | "
            f"baseline={self._baseline_sharpe:.3f} → new={new_sharpe:.3f} | "
            f"{'KEEP' if improved else 'REVERT'}"
        )

        if improved:
            # Merge into main
            try:
                subprocess.run(["git", "checkout", "main"], check=True, capture_output=True)
                subprocess.run(
                    ["git", "merge", "--no-ff", self._active_branch,
                     "-m", f"autoresearch: keep {agent} modification (Sharpe {self._baseline_sharpe:.3f}→{new_sharpe:.3f})"],
                    check=True, capture_output=True,
                )
                self._logger.info(f"Autoresearch: MERGED {self._active_branch}")
            except subprocess.CalledProcessError as e:
                self._logger.error(f"Merge failed: {e.stderr.decode()}")
        else:
            # Revert — delete branch, main retains original prompt
            try:
                subprocess.run(["git", "checkout", "main"], check=True, capture_output=True)
                subprocess.run(
                    ["git", "branch", "-D", self._active_branch],
                    check=True, capture_output=True,
                )
                self._logger.info(f"Autoresearch: REVERTED {self._active_branch}")
            except subprocess.CalledProcessError as e:
                self._logger.error(f"Branch delete failed: {e.stderr.decode()}")

        # Reset for next cycle
        self._active_branch  = None
        self._branch_agent   = None
        self._branch_start   = None
        self._baseline_sharpe = 0.0

    # ── Modification generation ──────────────────────────────────────

    def _generate_modification(
        self, agent_name: str, current_prompt: dict, all_sharpes: dict
    ) -> Optional[dict]:
        """Ask the LLM to produce ONE targeted improvement to the agent's prompt."""
        context = "\n".join(f"  {a}: Sharpe={s:.3f}" for a, s in all_sharpes.items())
        system = (
            "You are a prompt engineer specialising in financial AI agents. "
            "Your job is to improve a specific agent's prompt by making ONE targeted change. "
            "The change must be specific, testable, and address a plausible failure mode. "
            "Respond with only this JSON: "
            '{"modification": "<the new/changed text to insert or replace>", '
            '"location": "system|user", '
            '"rationale": "<one sentence explanation of what you changed and why>", '
            '"failure_mode": "<what failure pattern this addresses>"}'
        )
        prompt = (
            f"Agent: {agent_name}\n"
            f"Current rolling Sharpe (60d): {all_sharpes.get(agent_name, 0):.3f} (worst in panel)\n"
            f"All agent Sharpes for context:\n{context}\n\n"
            f"Current agent prompt:\n\n"
            f"SYSTEM:\n{current_prompt.get('system', '(not loaded)')}\n\n"
            f"USER TEMPLATE:\n{current_prompt.get('user_template', '(not loaded)')}\n\n"
            f"Generate ONE specific, targeted change to this prompt that could address "
            f"a plausible failure mode causing the poor Sharpe performance. "
            f"Limit the change to a single sentence or condition added to the prompt."
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            import json, re
            try:
                return json.loads(raw)
            except Exception:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
        except Exception as e:
            self._logger.error(f"Modification generation failed: {e}")
        return None

    def _write_modified_prompt(self, agent_name: str, modification: dict):
        """Apply the modification to the agent's prompt file."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "prompts", f"{agent_name}_agent.md"
        )
        if not os.path.exists(path):
            self._logger.warning(f"Prompt file not found: {path}")
            return

        with open(path) as f:
            content = f.read()

        location = modification.get("location", "user")
        new_text  = modification.get("modification", "")
        rationale = modification.get("rationale", "")

        section = "## System Prompt" if location == "system" else "## User Prompt Template"

        # Append the modification as a new condition at the end of the relevant section
        if section in content:
            insert_at = content.rfind(section)
            # Find end of this section (next ## or EOF)
            next_section = content.find("\n## ", insert_at + len(section))
            if next_section == -1:
                # Append at end of file
                content += f"\n\n<!-- autoresearch: {rationale} -->\n{new_text}"
            else:
                content = (
                    content[:next_section]
                    + f"\n\n<!-- autoresearch: {rationale} -->\n{new_text}\n"
                    + content[next_section:]
                )

        with open(path, "w") as f:
            f.write(content)

        self._logger.info(f"Prompt file updated: {path}")
```

---

### 4.5 — Wire `PromptAutoResearcher` into the fleet

**File:** `fleet.py` (fleet monitor loop)

```python
# In FleetOrchestrator.__init__ or setup:
from prompt_autoresearcher import PromptAutoResearcher
self._autoresearchers: dict[str, PromptAutoResearcher] = {}

# When spawning a bot that has autoresearch enabled (new BotConfig flag: autoresearch_enabled: bool = False):
if instance.config.autoresearch_enabled:
    self._autoresearchers[bot_id] = PromptAutoResearcher(
        bot_id=bot_id,
        openclaw_client=self._openclaw_client,
        openclaw_model=self._openclaw_model,
    )

# In the weekly tick of the monitor loop:
for bot_id, researcher in self._autoresearchers.items():
    researcher.run_cycle()
```

Add to `BotConfig` (`bot_config.py`):
```python
autoresearch_enabled: bool = False   # Opt-in — off by default
```

---

## Testing Checklist

### Phase 1 — Darwinian Weights
- [ ] `DarwinianWeightStore.daily_update()` correctly adjusts weights after simulated outcomes
- [ ] Weights stay within [0.3, 2.5] after 100 daily update cycles
- [ ] `deliberate()` with all agents at weight 1.0 produces same outcome as before the change (regression test)
- [ ] `get_state_snapshot()` includes `agent_weights` key
- [ ] `record_outcome()` is called after every closed trade in demo mode

### Phase 2 — CRO Agent
- [ ] CRO VETO blocks trade when 2+ objections fire
- [ ] CRO does not veto when no structural objections found
- [ ] CRO vote appears in Situation Room deliberation panel
- [ ] Existing bots without `"cro"` in `sub_agents` are unaffected

### Phase 3 — Macro Veto
- [ ] BUY signal blocked when macro sentiment = -0.7, confidence = 0.8
- [ ] BUY signal allowed when macro sentiment = -0.4 (below threshold)
- [ ] SELL signal (short entry) is NOT blocked by macro veto
- [ ] Macro veto appears in Situation Room with full reasoning

### Phase 4 — Prompt Autoresearch
- [ ] `_load_prompt()` returns correct content from `prompts/macro_agent.md`
- [ ] Agent falls back gracefully when prompt file doesn't exist
- [ ] `_generate_modification()` returns valid JSON with modification + rationale
- [ ] Git branch creation and deletion succeed on local repo
- [ ] Branch is reverted when new Sharpe ≤ baseline Sharpe
- [ ] Branch is merged when new Sharpe > baseline Sharpe

---

## Implementation Order

```
Week 1  │ Phase 1A: DarwinianWeightStore class + SubAgentPool wiring
        │ Phase 1B: Weighted net-score deliberation (replace quorum)
        │ Phase 1C: Outcome recording in bot_engine.py
        │ Phase 1D: Expose weights in get_state_snapshot()
────────┼────────────────────────────────────────────────────────────
Week 2  │ Phase 2:  CROAgent class + registration + deliberate() wire
        │ Phase 3:  Macro pre-filter block in deliberate()
────────┼────────────────────────────────────────────────────────────
Week 3  │ Phase 4A: prompts/ directory + extract inline prompts
        │ Phase 4B: firebase_store.py recommendation tracking
        │ Phase 4C: PromptAutoResearcher class
        │ Phase 4D: Fleet wiring + BotConfig flag
────────┼────────────────────────────────────────────────────────────
Week 4+ │ Monitor Darwinian weights in production
        │ First autoresearch cycle fires (Week 4 → eval at Week 5)
        │ Review first kept/reverted prompt modification
```

---

## Files Changed Summary

| File | Change |
|---|---|
| `sub_agents.py` | `DarwinianWeightStore` class (new), `CROAgent` class (new), `deliberate()` (3 edits), `AGENT_CLASSES` dict, `SubAgentPool.__init__` |
| `bot_config.py` | `SUB_AGENT_CRO` constant, `VALID_SUB_AGENTS` set, `autoresearch_enabled` field on `BotConfig` |
| `bot_engine.py` | Outcome recording after `_close_position()`, `get_state_snapshot()` addition |
| `fleet.py` | Daily Darwin update trigger, weekly autoresearch trigger, `PromptAutoResearcher` wiring |
| `firebase_store.py` | `log_agent_recommendation()`, `update_agent_recommendation_outcome()`, `get_agent_sharpe()` |
| `prompt_autoresearcher.py` | New file |
| `backend/prompts/*.md` | New directory with one prompt file per LLM agent |

**Files NOT touched:** `confluence.py`, `vital_signs.py`, `bot_vital_signs.py`, `executioner.py`, `fib_retracement.py`, `regime_detector.py`, `trend_strategist.py`, `alpaca_hub.py`, `main.py`
