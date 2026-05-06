# TradeClaw × ATLAS — Gap Analysis
**Date:** 2026-05-06  
**Reference:** `atlas-benchmark.md` + `atlas-gic-main/` vs TradeClaw backend codebase

---

## Executive Summary

TradeClaw has a solid multi-agent foundation with genuine IP advantages ATLAS lacks. The gaps are not about intelligence — they're about how agent intelligence is *organised, weighted, evolved, and synthesised* before hitting the order book. The four highest-leverage improvements are: **Darwinian agent weights**, **prompt-level autoresearch**, **an adversarial CRO agent**, and **a layered macro pre-filter**. None of these require touching Spirit Animals, Situation Room UI, ICT logic, or Apex Predator vital signs.

---

## Part 1: TradeClaw IP — What to Keep

These are differentiated assets ATLAS does not have. Do not modify.

| Feature | Location | Why It's IP |
|---|---|---|
| **Spirit Animal Presets** | `bot_config.py` → `animal`, `personality`, `description` | Unique bot identity system. Humanises the product. No equivalent in ATLAS. |
| **Situation Room UI** | `bot_engine.py` → `last_deliberation`, `synthetic_votes` | Live, per-tick MAS visualisation. ATLAS has no dashboard layer. |
| **3-Pillar Confluence Gate** | `confluence.py` | Multi-condition entry quality filter (ADX + RSI + RVOL + BB re-entry). ATLAS uses raw agent conviction. |
| **ICT Smart Money Detection** | `confluence.py` → FVG, Liquidity Sweep, Kill Zones | Structural order-flow analysis. ATLAS has no equivalent microstructure layer. |
| **Apex Predator / Vital Signs** | `vital_signs.py` | Drawdown survival states + profit-tier intelligence budget. ATLAS tracks Darwinian weights but not organismic health. |
| **Fibonacci Integration** | `fib_retracement.py`, `bot_config.py` | Price-level retracement entries with AI-tunable lookback and bounce threshold. |
| **TWAP Smart Order Routing** | `executioner.py` | Slippage-controlled execution with urgency routing. ATLAS's Autonomous Execution is described but not implemented in the open-source code. |
| **Fleet Multi-Bot Architecture** | `fleet.py` | True bot isolation (each bot owns its own engine, AI brain, sub-agents, vital signs). ATLAS is a single-portfolio system. |
| **Multi-Asset Support** | `bot_engine.py` → crypto/forex/equity detection | Equity + crypto + forex in one framework. ATLAS is equities-only. |
| **Demo Mode with Synthetic MAS** | `bot_engine.py:_demo_tick()` | Full deliberation simulation with no LLM cost. Critical for onboarding. |

---

## Part 2: Gap Analysis — Architecture

### GAP 1 — Agent Weights Are Static (Critical)

**ATLAS behaviour:** Every agent has a Darwinian weight [0.3, 2.5] updated daily based on rolling Sharpe. After 378 days, the system had independently discovered its own CIO was its weakest component (weight = 0.3 floor). Top performers (Geopolitical, Commodities, Volatility) reached 2.5x influence.

**TradeClaw today:** Fixed weights. `WatchmanAgent` has weight `1.25`, all others `1.0`. Weight is hardcoded in `sub_agents.py`. No performance tracking per agent. No feedback from outcome to influence.

**Impact:** A consistently wrong MacroAgent has the same vote weight as a consistently right WatchmanAgent. Over time the system cannot learn which voices to trust.

**Recommended fix:**
- Add a `darwinian_weight` float [0.3, 2.5] to each agent class (default 1.0).
- After each closed trade, attribute the outcome to agents that voted in the direction of the trade.
- Daily adjustment: top-quartile agents × 1.05, bottom-quartile × 0.95 (capped to bounds).
- Expose weights in the Situation Room — gives users a live "trust ranking" of their panel.

---

### GAP 2 — AI Brain Evolves Parameters, Not Agent Intelligence (Critical)

**ATLAS behaviour:** The autoresearch loop identifies the worst-performing agent by Sharpe, generates a single targeted modification to that agent's *prompt*, creates a git branch, runs for 5 trading days, then commits (if Sharpe improved) or resets. The prompt IS the weights. 30% of modifications survive.

**TradeClaw today:** `ai_brain.py` adjusts strategy *parameters* (bb_period, bb_std_dev, stop_loss_pct, kelly_fraction, etc.) via LLM. These are numerical dials, not intelligence. The MacroAgent's prompt — what it actually thinks about — never changes. A MacroAgent that has been wrong about yield curves for 30 days will still give the same yield-curve analysis next week.

**Impact:** Parameters can be hand-tuned by a human in minutes. Prompt evolution is qualitatively different — it changes what the agent *knows how to look for*. This is the core mechanism behind ATLAS's +22% 173-day deployment return.

**Recommended fix (additive — does not replace AI Brain param evolution):**
- Per-agent prompt files (e.g. `prompts/sentiment_agent.md`, `prompts/macro_agent.md`).
- Track each agent's directional recommendation history against forward returns (1d, 5d).
- Weekly autoresearch cycle: worst-Sharpe agent → LLM generates ONE targeted prompt change → git branch → 5-day eval → commit or reset.
- This is entirely parallel to the existing param-evolution AI Brain. Both can run.

---

### GAP 3 — No Adversarial Risk Officer (High Priority)

**ATLAS behaviour:** The CRO receives all recommendations from all prior layers and actively tries to find reasons NOT to act. Checks: concentration risk, correlation to existing positions, macro headwinds, valuation concerns, technical breakdown. Only ideas that survive CRO scrutiny reach the CIO.

**TradeClaw today:** `RiskManagerAgent` performs Kelly Criterion gating (approves qty based on edge statistics). It does not attack the trade thesis. There is no agent whose job is to veto on *fundamental* or *structural* grounds, only on *position sizing* grounds.

**A BUY signal could survive quorum even if:** earnings are in 48 hours, VIX spiked this morning, the position is correlated with two other open bots, and the macro regime is risk-off. RiskManager only catches whether Kelly math supports the size.

**Recommended fix:**
- Add `AdversarialRiskAgent` (or `CROAgent`) to the sub-agent pool.
- Its sole job: given the proposed trade, generate reasons NOT to take it.
- If it finds 2+ valid reasons (correlated risk, upcoming catalyst, regime mismatch, concentration), it issues a VETO.
- Give it a higher base weight (1.5) since false negatives (missed trades) cost less than false positives (bad entries).
- Display its veto reasons in the Situation Room for transparency.

---

### GAP 4 — Flat Agent Pool, No Layered Macro Filter (High Priority)

**ATLAS behaviour:** A 4-layer hierarchy. Layer 1 (10 macro agents) produces a regime signal (RISK_ON / RISK_OFF / NEUTRAL) that gates downstream layers. Sector desks only run if macro permits. Superinvestors only filter ideas that passed sector desks.

**TradeClaw today:** All 6 sub-agents vote in parallel. The MacroAgent is one of six equal voices. A strong VIX spike or Fed statement that the MacroAgent reads correctly can be outvoted 4:1 by agents looking at unrelated technical or sentiment data. There is no top-down regime gate.

**Impact:** The bot can execute a BUY in a RISK_OFF macro environment because the technical and sentiment agents outvoted the macro agent. The RegimeDetector in `bot_engine.py` catches local price regime (TRENDING/RANGING/VOLATILE) but has no awareness of macro regime (yield curve, VIX structure, dollar direction).

**Recommended fix (two options, pick one):**
- **Option A (lighter):** Add a macro veto power — MacroAgent gets hard veto rights when macro regime is RISK_OFF (VIX > 25, yield curve inverted, dollar spiking). It cannot be outvoted on regime calls. Already fits the existing veto architecture.
- **Option B (fuller):** Split agents into Layer 0 (macro pre-filter) and Layer 1 (execution panel). Layer 0 runs first and returns a regime flag. Layer 1 only runs if regime is RISK_ON or NEUTRAL. Maps cleanly onto the existing SubAgentPool.deliberate() flow.

Option A is a single afternoon's work. Option B is a week.

---

### GAP 5 — CIO Synthesis vs Quorum Voting (Medium Priority)

**ATLAS behaviour:** The CIO receives all agent outputs weighted by their Darwinian scores, synthesises consensus and divergence, and makes a final decision with position sizing. It reasons about *why agents disagree* as much as about what the majority says.

**TradeClaw today:** `deliberate()` in `sub_agents.py` uses a threshold quorum: ≥ 3/5 panel agents must agree + weighted score ≥ 0.2. This is majority voting. A 3:2 split where the 3 are low-confidence and the 2 are high-confidence can still approve a weak trade.

**Impact:** The synthesis step is purely mechanical. No agent reasons about inter-agent disagreement. When Watchman says HOLD and Technical says BUY at 0.9 confidence, those two facts should cancel differently than when both say BUY at 0.5 each.

**Recommended fix:**
- Replace the mechanical quorum threshold with a weighted confidence score:
  `net_score = Σ(weight × confidence × direction_sign) / Σ(weight)`
  where direction_sign is +1 for BUY, -1 for SELL, 0 for HOLD.
- Approve only if net_score > configurable threshold (e.g. 0.35).
- This is one function change in `deliberate()`. The Darwinian weights from GAP 1 feed directly into this formula — they become meaningful immediately.

---

### GAP 6 — Agent Roster Is Fixed (Medium Priority)

**ATLAS behaviour:** The system autonomously spawns new specialist agents when the same knowledge gap appears 3+ times in 5 days. During a 6-month test, 9 agents were spawned (credit markets, options flow, liquidity conditions, earnings calendar, positioning data, etc.) and 6 survived Darwinian selection. Zero human involvement in deciding what to create.

**TradeClaw today:** Fixed roster of 7 agent types defined in `bot_config.py:VALID_SUB_AGENTS`. Changing the roster requires a code deployment.

**Impact:** TradeClaw cannot learn that it's systematically blind to, say, options flow or earnings calendar risk, because there's no mechanism to detect and fill knowledge gaps.

**Recommended fix (phased):**
- Phase 1 (quick win): Add `EarningsAgent` and `OptionsFlowAgent` to the existing roster as opt-in agents users can toggle in bot config. Expand `VALID_SUB_AGENTS`.
- Phase 2 (architectural): Track recurring "knowledge gap" patterns — when agents cite missing data categories in their reasoning 3+ times in a rolling window, flag the gap in Firestore. Allow manual or automated creation of new agent configs.

---

### GAP 7 — No Regime-Specific Agent Training (Lower Priority)

**ATLAS behaviour:** PRISM trains separate agent cohorts on distinct historical regimes (bull, crisis, rate tightening, euphoria, recovery). Each cohort develops different survival strategies. JANUS sits above all cohorts and weights them by recent accuracy — the differential weight between cohorts becomes an emergent regime detector.

**TradeClaw today:** The AI Brain uses one prompt/model for all market conditions. An agent tuned during a ranging bull market gets the same prompt in a rate-tightening crash.

**Impact:** ATLAS's Rate Tightening cohort independently learned "never flip-flop during Fed weeks — 15-day minimum between reversals." TradeClaw's AI Brain would need many loss-streak cycles to arrive at a similar rule organically, and even then it would be expressed as a parameter change, not a behavioural rule change.

**Recommended fix:** This is the deepest architectural change and the lowest immediate-ROI item. Defer until Darwinian weights and autoresearch prompt evolution are working. At that point, you can segment the AI Brain's evolution history by regime label and load the appropriate prompt variant at runtime.

---

## Part 3: Gap Analysis — Signal Quality

| Signal Layer | ATLAS | TradeClaw | Gap |
|---|---|---|---|
| Macro regime gate | 10 dedicated macro agents producing RISK_ON/OFF/NEUTRAL | One generic MacroAgent voting in a flat pool | No dedicated yield curve, geopolitical, dollar, or institutional flow analysis |
| Sector-level analysis | 7 sector desks + Relationship Mapper | Not present | No sector rotation awareness |
| Philosophy filter | 4 superinvestor personas (Druckenmiller, Ackman, Baker, Aschenbrenner) | Not present | No investment philosophy alignment check |
| Adversarial review | CRO attacks every idea | RiskManager does Kelly gating only | No fundamental veto layer |
| Alpha discovery | Alpha Discovery agent finds unlisted names | Not present (TradeClaw is single-symbol) | N/A for single-symbol bots |
| Microstructure | Not present | ICT FVG, Liquidity Sweep, Kill Zones, 3-Pillar Confluence | **TradeClaw leads** |
| Position entry quality | Raw agent conviction | Confluence Gate (ADX+RSI+RVOL+BB re-entry) | **TradeClaw leads** |
| Execution | Described only | TWAP, Limit with slippage abort, urgency routing | **TradeClaw leads** |
| Bot identity | Not present | Spirit Animals, Apex Predator survival states | **TradeClaw leads** |
| Multi-asset | Equities only | Equity + Crypto + Forex | **TradeClaw leads** |

---

## Part 4: Prioritised Improvement Roadmap

### Tier 1 — High Impact, Moderate Effort (Do First)

**1. Darwinian Agent Weights**
- Add `darwinian_weight` float to each `SubAgent` class in `sub_agents.py`
- Track per-agent vote outcomes in Firestore after each closed trade
- Daily weight adjustment via `bot_vital_signs.py` update cycle
- Expose in Situation Room as a "trust ranking" column
- Estimated effort: 2-3 days

**2. Weighted Net Score Deliberation (replaces quorum)**
- Replace `≥3/5 quorum` with `Σ(weight × confidence × direction_sign) / Σ(weight) > threshold`
- One function change in `SubAgentPool.deliberate()`
- Immediately leverages Darwinian weights once those are in
- Estimated effort: 0.5 days

**3. Adversarial CRO Agent**
- Add `CROAgent` to `sub_agents.py` and `VALID_SUB_AGENTS`
- Prompt: given the trade, list reasons NOT to take it (correlation, catalyst risk, regime mismatch, concentration)
- Issues VETO if ≥ 2 valid objections found
- Weight: 1.5 (asymmetric — veto power should be heard)
- Display veto reasons in Situation Room
- Estimated effort: 1-2 days

### Tier 2 — High Impact, Higher Effort (Do Second)

**4. Macro Pre-Filter Layer (Option A — MacroAgent Veto Power)**
- Give MacroAgent a hard veto on directional trades when VIX > 25 or yield curve inverted
- Implement as a pre-deliberation check before quorum runs
- Estimated effort: 1 day

**5. Prompt-Level Autoresearch Loop**
- Create `prompts/` directory with per-agent prompt files
- Track per-agent recommendation history vs. forward returns
- Weekly cycle: worst-Sharpe agent gets one targeted prompt modification (git branch → eval → commit/reset)
- Runs in parallel with existing param-evolution AI Brain
- Estimated effort: 3-5 days

### Tier 3 — Medium Impact, Additive (Do When Ready)

**6. Expanded Agent Roster**
- Add `EarningsCalendarAgent`, `OptionsFlowAgent` as opt-in agents in `VALID_SUB_AGENTS`
- Toggle via `BotConfig.sub_agents` list — existing bots unaffected
- Estimated effort: 1-2 days per agent

**7. Regime-Specific Prompt Variants**
- Store separate prompt variants per market regime in Firestore
- AI Brain loads the variant matching current `RegimeDetector` output
- Prerequisite: Prompt-level autoresearch must be working first
- Estimated effort: 2-3 days after autoresearch is in place

---

## Part 5: What NOT to Adopt from ATLAS

| ATLAS Feature | Reason to Skip |
|---|---|
| **JANUS meta-layer** | Requires training multiple agent cohorts over 12+ months. Premature without PRISM training data. |
| **MiroFish swarm simulation** | Separate infrastructure dependency. Valuable long-term, but not addressable until core agent quality is improved. |
| **Soros Reflexivity Engine** | Research-level feature. Markets are partially reflexive but full feedback modelling is a separate research project. |
| **Agent spawning (autonomous)** | High complexity, low priority. Expand the fixed roster first, then automate spawning once the roster is stable. |
| **Sector desk layer** | TradeClaw is a symbol-specific bot system, not a portfolio manager. Sector desks are appropriate for a fund-level system, not a per-instrument bot. |
| **Superinvestor personas** | Philosophy filtering makes sense at portfolio level. For a single-symbol bot, the 3-Pillar Confluence Gate does the equivalent job at the microstructure level. |

---

## Summary Table

| Gap | Priority | Effort | Preserves IP? |
|---|---|---|---|
| Darwinian agent weights | Critical | 2-3 days | Yes |
| Weighted deliberation formula | Critical | 0.5 days | Yes |
| Adversarial CRO agent | High | 1-2 days | Yes |
| Macro pre-filter (veto power) | High | 1 day | Yes |
| Prompt-level autoresearch | High | 3-5 days | Yes |
| Expanded agent roster | Medium | 1-2 days/agent | Yes |
| Regime-specific prompt variants | Lower | 2-3 days | Yes |
| JANUS / PRISM / MiroFish | Defer | Months | N/A |
