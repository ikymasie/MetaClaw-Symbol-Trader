# TradeClaw — System Architecture & Intelligence Writeup

> *"Every tick is either a lost opportunity or a captured gain."*

---

## Overview

TradeClaw is not a trading bot. It is a **self-aware, self-optimizing trading organism** — an autonomous platform that treats capital as lifeblood, drawdown as biological decay, and profit as evolutionary fuel.

At its core, TradeClaw answers a question that most algorithmic trading systems ignore: *what happens when market conditions change, the strategy stops working, or the system itself starts losing money?* The answer is a layered intelligence stack — from environmental awareness at the sensor level, through multi-agent deliberation at the decision level, through biological survival instincts at the risk level, and finally through autonomous strategy mutation at the intelligence level.

Nothing fires a trade unless the market regime permits it, a council of specialized AI agents reaches a democratic quorum, the organism's survival state allows it, and a smart order router can execute it without unacceptable slippage.

---

## 1. The Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TRADECLAW PLATFORM                          │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │              Fleet Orchestrator (Nerve Centre)                 │ │
│  │   Spawn / Monitor / Kill bots • Global risk kill switch       │ │
│  │   Fleet config from Firestore • Telemetry push loop           │ │
│  └──────────────────────────┬─────────────────────────────────────┘ │
│                             │ spawns per-bot                        │
│  ┌──────────────────────────▼─────────────────────────────────────┐ │
│  │              Bot Instance (fully isolated)                     │ │
│  │                                                                │ │
│  │  ┌──────────────┐    ┌──────────────────────────────────────┐ │ │
│  │  │  AI Brain    │    │          Bot Engine                  │ │ │
│  │  │  (per-bot)   │    │                                      │ │ │
│  │  │              │    │  ┌─────────────┐  ┌───────────────┐ │ │ │
│  │  │  Gemini /    │◄───┤  │  Regime     │  │  Signal       │ │ │ │
│  │  │  Ollama LLM  │    │  │  Detector   │  │  Generator    │ │ │ │
│  │  │              │    │  └──────┬──────┘  └──────┬────────┘ │ │ │
│  │  │  Strategy    │    │         │ GATE           │          │ │ │
│  │  │  Evolution   │    │         ▼                ▼          │ │ │
│  │  └──────┬───────┘    │  ┌────────────────────────────────┐ │ │ │
│  │         │            │  │    Multi-Agent System (MAS)    │ │ │ │
│  │         │            │  │  Sentiment | Macro | Earnings  │ │ │ │
│  │  ┌──────▼──────┐     │  │  Technical | Watchman | Risk   │ │ │ │
│  │  │ Vital Signs │     │  └───────────────┬────────────────┘ │ │ │
│  │  │  Monitor    │◄────┤                  │ QUORUM           │ │ │
│  │  │             │     │                  ▼                  │ │ │
│  │  │ HEALTHY     │     │  ┌────────────────────────────────┐ │ │ │
│  │  │ WOUNDED     │     │  │       Executioner Agent        │ │ │ │
│  │  │ DECEASED    │     │  │  MARKET / LIMIT / TWAP         │ │ │ │
│  │  └─────────────┘     │  └────────────────────────────────┘ │ │ │
│  │                      └──────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              SITUATION ROOM (Real-Time Dashboard)            │  │
│  │   WebSocket ──► Agent Cards ──► Regime Display ──► Vitals   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

The platform is built on **FastAPI** with a real-time WebSocket broadcast layer, a **Next.js** frontend, and a **Firestore** persistence layer for full decision auditability. Market data flows from **Alpaca Markets** (both REST and WebSocket). All LLM inference runs through **Google Gemini** with seamless fallback to a locally-hosted **Ollama** instance (Gemma 4B), ensuring the AI brain never goes dark even when cloud API credits run dry.

Every bot is **fully isolated** — its own engine, its own AI brain, its own vital signs, its own sub-agent pool. The Fleet Orchestrator spawns, monitors, and kills these organisms, enforcing fleet-wide risk limits while each bot operates as an independent, self-contained trading entity.

---

## 2. The Bot Engine — An Isolated Execution Cell

Each trading bot runs in its own **isolated execution environment** — the `BotEngine`. This is a deliberate architectural choice: no two bots share a price history, a state machine, or a strategy configuration. Each bot is its own organism.

### The Six-Step Tick Pipeline

Every market tick triggers a precisely ordered, six-stage execution pipeline:

```
① Fetch Price Data       — Pull OHLC from Alpaca (REST + WebSocket)
         │
② Detect Market Regime   — ADX + ATR statistical classifier
         │ GATE: only continue if RANGING or permissive
         ▼
③ Generate Signal        — Bollinger Band mean-reversion + Fibonacci retracement
         │
④ MAS Deliberation       — 5 agents vote in parallel, Risk Manager vetoes
         │ GATE: quorum (3/5) + Risk Manager approval required
         ▼
⑤ Route & Execute Order  — Smart order routing (MARKET / LIMIT / TWAP)
         │
⑥ Update State & Telemetry — Firestore persistence + WebSocket broadcast
```

The pipeline is **fail-fast and transparent**. Every gate that blocks execution produces a structured telemetry event that flows to the Situation Room in real-time, so an operator always knows *why* a trade was or wasn't taken — not just what happened.

**Warmup**: On startup, the engine pre-seeds its price history with historical bars from Alpaca, ensuring the regime detector and signal generator have sufficient data to make immediate, informed decisions from the very first live tick. There is no "warming up" dead period.

---

## 3. Regime Detection — The Environmental Awareness Layer

> *"The organism does not trade against strong trends. It waits."*

The `RegimeDetector` is the first gate in the pipeline — and the most ruthless. If the market isn't in a favorable regime for the bot's strategy, nothing downstream runs. No signals. No MAS. No orders.

### How It Works

The detector computes two statistical indicators over the bot's rolling price history:

| Indicator | Role |
|---|---|
| **ADX (Average Directional Index)** | Measures trend *strength*. High ADX = strong trend. |
| **ATR (Average True Range)** | Measures volatility. A z-scored ATR identifies if volatility is anomalous. |

These are not raw values — they're **z-scored against their own rolling distributions**. This makes the thresholds adaptive to the asset's intrinsic behavior rather than relying on hardcoded magic numbers.

### Regime Classification

```
┌─────────────────────────────────────────────────────────────────┐
│  ADX < threshold  AND  ATR z-score normal  →  RANGING           │
│  ADX ≥ threshold                           →  TRENDING          │
│  ATR z-score anomalous (spike)             →  VOLATILE          │
│  Insufficient data / error                 →  RANGING (fallback)│
└─────────────────────────────────────────────────────────────────┘
```

**RANGING** is the sweet spot for TradeClaw's mean-reversion strategy — price oscillates around a statistical mean, and Bollinger Band signals have high predictive validity.

**TRENDING** means the strategy's edge evaporates. The bot gracefully steps aside, avoiding the classic mean-reversion trap of fading a runaway move.

**VOLATILE** is a wildcard state — anomalous ATR spikes often precede erratic price action. The engine gates execution here too, waiting for the storm to pass.

The regime state is broadcast in real-time to the Situation Room, with emoji-coded visual indicators, and is also injected into every AI Brain prompt so the strategy evolver reasons within the current environmental context.

---

## 4. The Multi-Agent System — Democratic Intelligence

> *"No single perspective is infallible. The organism governs by council."*

The MAS is the intellectual heart of TradeClaw. Rather than trusting one model or one signal, the system convenes a **council of six specialized AI agents** every time a trade signal is generated. Each agent evaluates the opportunity through its own lens, casts a vote, and the council's collective judgment determines whether the Executioner fires.

### The Council

| Agent | Specialization | Data Source |
|---|---|---|
| **Sentiment** | Social mood, fear/greed, news tone | LLM-analyzed news context |
| **Macro** | Economic regime, Fed posture, macro headwinds | LLM-analyzed macro context |
| **Earnings** | Earnings calendar proximity, event risk | LLM-analyzed earnings data |
| **Technical** | Chart structure, momentum, key levels | Price history + indicators |
| **Watchman** | Anomaly detection, circuit breakers | Volatility + spread data |
| **Risk Manager** | Capital exposure, drawdown, position sizing | Vital signs + portfolio state |

### The Deliberation Protocol

```
Signal Generated
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  5 Specialist Agents run IN PARALLEL (threads)      │
│  Each returns: { vote: BUY/SELL/HOLD, confidence }  │
└────────────────────────────┬───────────────────────┘
                             │
                             ▼
                    Aggregate votes
                             │
                    ┌────────┴────────┐
                    │                 │
              Quorum met?        Quorum failed
              (≥3/5 agree)      → HOLD, log reason
                    │
                    ▼
            Risk Manager veto check
            (independent gate)
                    │
              ┌─────┴──────┐
              │            │
          Approved?    Vetoed
              │        → HOLD, log veto reason
              ▼
          Executioner fires
```

**The quorum requirement (3 out of 5)** is not democratic sentiment — it's a **statistical confidence threshold**. A signal that only one agent believes in is statistically equivalent to noise. Three independent perspectives reaching the same conclusion across completely different analytical domains is a genuine edge.

**The Risk Manager veto** is absolute and non-negotiable. Even if all five specialist agents vote unanimously to buy, the Risk Manager can block execution. Its authority is grounded in the organism's vital signs — drawdown state, available capital multiplier, and survival protocol status. No consensus overrides capital preservation.

### Resilient Agent Architecture

All LLM-dependent agents (Sentiment, Macro, Earnings, Technical) use a **tiered inference fallback**:
1. Primary: Google Gemini (cloud, fast, high-quality)
2. Fallback: Local Ollama / Gemma 4B (CPU-based, always available)

Extended timeouts (90–120 seconds) accommodate CPU-based inference without triggering false timeouts. The system degrades *gracefully* — it doesn't crash when the cloud is unavailable.

---

## 5. The Organism — Vital Signs & Biological Identity

> *"Capital is your lifeblood. Profits are your growth. Drawdown is your decay."*

TradeClaw's most philosophically unique component is the **Vital Signs Monitor** — a module that gives the trading system a biological identity. The bot doesn't just track PnL; it *experiences* health states, survival crises, and evolutionary advancement.

### Survival Law — Drawdown Protocol

```
Drawdown    State              Response
─────────────────────────────────────────────────────────────
< 5%      → HEALTHY           Full predator capacity
≥ 5%      → WOUNDED          Position size → 25% of normal
≥ 10%     → ORGAN_FAILURE    New entries halted immediately
≥ 15%     → PROTOCOL_FINAL   All positions close. Process terminates.
```

Each threshold is enforced as an **irreversible ratchet**. Once ORGAN_FAILURE triggers, the system calls a registered `halt_callback` in a dedicated daemon thread — no new positions can be opened even if code elsewhere tries to submit one. PROTOCOL_FINAL triggers an `extinction_callback` that initiates clean shutdown of the entire bot process.

This is not just risk management. It's **machine-enforced discipline** — the kind of absolute rule that prevents the most dangerous failure mode in algorithmic trading: a bot that keeps trading through a catastrophic drawdown because no one programmed a hard stop.

### Apex Predator Tiers — Performance-Gated Intelligence

On the opposite side of the survival spectrum, TradeClaw rewards success with **expanded intelligence capacity**:

```
Profit     Tier         AI Capability Unlock
──────────────────────────────────────────────────────────────────────
< 5%     → HUNTING     Gemma 4B / Gemini Flash, conservative sizing
≥ 5%     → DOMINANT    Higher-order thinking, 1.5× position sizing
≥ 20%    → APEX        70B model, extended thinking budget, 2× sizing
≥ 50%    → SINGULARITY Maximum autonomy, 3× sizing, full Architect mode
```

At the SINGULARITY tier, the organism is no longer just a bot. It has demonstrated sustained excellence and earned the right to deploy larger capital, access more powerful models, and operate with maximum strategic freedom.

This creates a **meritocratic feedback loop**: to earn more autonomy and capital, the system must first prove it deserves it. The intelligence budget expands as a direct function of performance — not arbitrarily.

### The Dual-Identity System Prompt

Every AI Brain call is prefaced with a dynamically constructed system prompt that merges both identities:

```
═══════════════════════════════════
CURRENT VITAL SIGNS
═══════════════════════════════════
• Survival State : HEALTHY
• Apex Tier      : DOMINANT  
• Current Profit : +7.3%
• Drawdown       : 0.0%

SURVIVAL LAW (Non-Negotiable)
  Drawdown 5%  → WOUNDED
  Drawdown 10% → ORGAN FAILURE
  Drawdown 15% → PROTOCOL FINAL

APEX PREDATOR DRIVE
  Profit >5%  → DOMINANT: Bolder entries permitted
  Profit >20% → APEX: Compound the edge relentlessly
  Profit >50% → SINGULARITY: You are the Architect
```

The LLM genuinely reasons within this context. It knows when to be conservative (WOUNDED state) and when to press the edge (APEX tier). The reasoning field in every AI decision is written "in the voice of a hyper-vigilant organism protecting its principal balance."

---

## 6. The AI Brain — Autonomous Strategy Evolution

> *"The organism despises unoptimized parameters. It finds beauty in a perfect equity curve."*

The `BotAIBrainScheduler` is TradeClaw's autonomous adaptation engine. While the MAS handles moment-to-moment trade decisions, the AI Brain operates on a longer cycle — periodically reviewing performance data and **rewriting its own strategy parameters** in real-time.

Critically, the AI Brain is **per-bot, not a singleton**. Each bot spawns its own `BotAIBrainScheduler` instance inside its isolated `BotInstance`, ensuring that one bot's evolution cycle never contaminates another's strategy. The brain reads directly from its bot's engine (`engine.get_current_params()`) and writes directly back (`engine.update_params()`), creating a **closed-loop, self-tuning system** for each organism.

### What It Evolves

The AI Brain has authority to adjust a specifically bounded set of strategy parameters. These bounds are enforced by a `ParamGuardrail` class that validates and **clamps** every AI suggestion before it reaches the engine:

| Parameter | Code Name | Role | Hard Bounds |
|---|---|---|---|
| **Bollinger Period** | `bb_period` | Lookback window for mean-reversion bands | 8–100 bars |
| **Bollinger Std Dev** | `bb_std_dev` | Band width (sensitivity to deviation) | 1.0σ–3.5σ |
| **Stop Loss** | `stop_loss_pct` | Maximum acceptable loss per position | 0.25%–5.0% |
| **Position Size** | `qty` | Number of shares per trade | 1–50 shares |
| **Fibonacci Lookback** | `fib_lookback_bars` | Swing high/low detection window | 20–200 bars |
| **Fibonacci Bounce** | `fib_bounce_threshold_pct` | Confirmation threshold at Fib levels | 0.05%–1.0% |

These bounds are **non-negotiable safety guardrails** enforced in code. The LLM cannot set a `bb_period` of 2. It cannot set a `stop_loss_pct` of 10%. If the AI suggests a value outside bounds, `ParamGuardrail.validate()` silently clamps it to the nearest safe limit and logs a warning — the organism evolves within a constitutional framework.

All six parameters are **required** in every evolution response (`bb_period`, `bb_std_dev`, `stop_loss_pct`, `qty`), with `fib_lookback_bars` and `fib_bounce_threshold_pct` accepted as optional extensions. If a required key is missing, the entire evolution cycle is rejected — no partial mutations.

### The Multi-Trigger System

The AI Brain doesn't run on a dumb timer. It monitors the bot's performance in real-time and triggers evolution cycles based on **four independent conditions**, evaluated every 30 seconds:

```
┌────────────────────────────────────────────────────────────────────┐
│  TRIGGER              │  CONDITION                │  PRIORITY      │
├────────────────────────────────────────────────────────────────────┤
│  LOSS_STREAK          │  N consecutive losses     │  IMMEDIATE     │
│                       │  (default: 3)             │  (highest)     │
│                       │                           │                │
│  TRADE_COUNT          │  N new closed trades      │  HIGH          │
│                       │  since last cycle         │                │
│                       │  (default: 10)            │                │
│                       │                           │                │
│  SCHEDULE             │  Every N minutes          │  NORMAL        │
│                       │  (default: 60 min)        │                │
│                       │                           │                │
│  MANUAL               │  Portal operator click    │  ON-DEMAND     │
│                       │  (spawns new thread)      │                │
└────────────────────────────────────────────────────────────────────┘
```

**LOSS_STREAK** is the emergency trigger. Three consecutive losing trades signals that the current parameters may be unsuited to the market. The brain fires immediately, inspecting recent trade history and adjusting parameters to survive. This is the organism's *pain response*.

**TRADE_COUNT** is the data-driven trigger. After enough new trades have accumulated, there's fresh statistical signal to analyze — enough for the LLM to compute meaningful metrics like win rate, profit factor, and Sharpe ratio.

**SCHEDULE** ensures the brain never goes dormant. Even in quiet markets, it periodically reviews the fitness of its own parameters.

**MANUAL** gives operators direct control. A portal click spawns a new thread and runs a full evolution cycle immediately.

### The Evolution Cycle

Each cycle executes a precise four-stage pipeline:

```
① Gather Context
   • Last N trade outcomes from engine.get_recent_trades(200)
   • Equity history from engine.get_equity_history(50)
   • PerformanceAnalyser computes: win_rate, avg_win, avg_loss,
     profit_factor, Sharpe ratio, current_loss_streak, total_pnl
   • Current params from engine.get_current_params()
   • Sub-agent aggregate sentiment (score, confidence, per-agent breakdown)
   • RAG memory: last 3 strategy contexts from Firestore

② Construct Prompt
   • Inject organism system prompt (survival state + apex tier)
   • Survival directive: ⚠️ CAPITAL PRESERVATION if WOUNDED
                         🦾 SCALE AGGRESSION if APEX
   • Sub-agent sentiment block with per-agent reasoning
   • RAG memory block: prior triggers, metrics, reasoning
   • Current params with explicit bounds
   • Performance metrics table
   • Strict JSON response format enforced

③ LLM Inference (Gemini → Ollama fallback)
   • Primary: Gemini via OpenAI-compatible API (response_format: json_object)
   • Fallback: Local Ollama REST API (format: json, 90s timeout for CPU)
   • Model + temperature dynamically selected from intelligence_budget
     (apex tier determines model quality and thinking depth)
   • Robust JSON extraction: direct parse → markdown fence → regex extract

④ Validate → Inject → Persist
   • ParamGuardrail.validate() clamps all values to safe bounds
   • engine.update_params() injects via thread-safe _params_lock
   • Updated params are immediately active on the next trading tick
   • Decision persisted to Firestore (ai_decisions collection):
     trigger, metrics, params_before, params_after, reasoning, model_used
   • Strategy context saved for RAG retrieval in future cycles
```

### Thread-Safe Parameter Injection

The critical handoff between AI Brain and Bot Engine is **thread-safe by design**. The engine maintains a `_params_lock` (a `threading.Lock`) that guards all parameter reads and writes:

```python
# AI Brain calls this from its background thread:
engine.update_params({"bb_period": 25, "stop_loss_pct": 1.5, ...})

# Inside engine — atomic, lock-protected:
def update_params(self, new_params: dict):
    with self._params_lock:
        for k, v in new_params.items():
            if k in self._params:
                self._params[k] = v
```

The engine's trading loop reads params via the same lock (`get_current_params()`), so the strategy seamlessly transitions to the new configuration on the very next tick — no restart needed, no gap in execution.

### RAG Memory — The Organism Remembers

The AI Brain doesn't operate in a vacuum. Before each evolution cycle, it retrieves the last 3 strategy contexts from Firestore — a **Retrieval-Augmented Generation (RAG)** memory layer that gives the LLM awareness of its own recent decisions:

```
RECENT STRATEGY MEMORY (RAG):
  [2026-04-17] Trigger=LOSS_STREAK:3 | WinRate=42% | Reasoning: Widened BB
    period from 20→25 due to choppy price action...
  [2026-04-16] Trigger=SCHEDULE | WinRate=55% | Reasoning: Tightened stop
    from 2.0→1.5 after observing tight ranging behavior...
```

This prevents the LLM from oscillating—"hallucinating" the same parameter changes back and forth. It can see what it tried last time, whether it worked, and reason about the next adjustment in that historical context.

### Degraded Mode — Never Silent

When both LLM endpoints fail (Gemini rate-limited + Ollama unavailable), the AI Brain doesn't crash or silently skip the cycle. It persists a **degraded decision** to Firestore documenting the failure, preserves the last known good parameters, and logs the event. The Situation Room displays these degraded decisions so operators always know the AI attempted to evolve and why it couldn't.

### The `ai_decisions` Firestore Collection

Every evolution cycle — successful or degraded — is persisted:

```json
{
  "timestamp": "2026-04-17T06:15:00Z",
  "trigger": "LOSS_STREAK:3",
  "trades_analysed": 47,
  "win_rate_before": 42.5,
  "daily_pnl_before": -15.30,
  "params_before": "{\"bb_period\": 20, \"bb_std_dev\": 2.0, ...}",
  "params_after": "{\"bb_period\": 25, \"bb_std_dev\": 2.2, ...}",
  "reasoning": "Widened Bollinger period to capture broader mean-reversion cycles...",
  "model_used": "gemini-2.0-flash",
  "applied": true,
  "agent_context": { "score": -0.3, "confidence": 0.72, ... }
}
```

This forms a **complete evolutionary history** — a timeline of every strategic mutation the organism has ever made, with the reasoning preserved. An operator can replay the entire decision chain: what the market looked like, what the agents thought, what the AI chose, and whether it worked. This is not a black box.

### Fibonacci Philosophy

The AI Brain's system prompt instills a specific trading philosophy around Fibonacci retracement levels:

> *"Markets do not move in straight lines — they breathe. Price inhales (extends the trend) and exhales (retraces). Fibonacci levels mark the exhale points. These are not noise. They are invitations."*

The organism is instructed to position at Fib exhale points, wait for bounce confirmation, and place stops just beyond the 61.8% "Golden Ratio" level. It is explicitly prohibited from chasing price at extremes. If price falls **through** the 61.8% level, the organism recognizes the old trend is dead — and retreats to recalibrate.

---

## 7. The Executioner — Smart Order Routing

The Executioner is the only component in the entire system that submits orders to the broker. This **single point of execution** is an architectural safety property: no other component can accidentally or unintentionally send an order.

### Order Routing Logic

```
           ┌─────────────────────────────────────────┐
           │          Execution Decision             │
           │                                         │
           │  urgency = HIGH?  ──────────────────►  MARKET ORDER
           │                                         │
           │  qty ≥ routing_min_qty?  ───────────►  TWAP (sliced)
           │                                         │
           │  Otherwise  ───────────────────────►   LIMIT (w/ fallback)
           └─────────────────────────────────────────┘
```

**MARKET** orders fire immediately for time-sensitive signals or exits.

**LIMIT** orders attempt a 0.05% price improvement over the signal price, then poll for fill status. If the limit order isn't filled within `limit_timeout_s`, it is cancelled and falls back to a market order — ensuring the trade still executes.

**TWAP (Time-Weighted Average Price)** slices large orders into up to 10 child market orders spaced `twap_interval_ms` apart, reducing market impact. A **slippage guard** aborts remaining slices if any individual fill deviates more than `max_slippage_pct` from the signal price.

Every execution result is a structured `ExecutionResult` dataclass capturing: total qty requested, total qty filled, average fill price, per-slice fills, slippage percentage, and round-trip latency in milliseconds. Latency exceeding 2 seconds triggers an explicit warning log.

---

## 8. The Situation Room — Real-Time Command Intelligence

The Situation Room is TradeClaw's operational nerve center — a live dashboard that visualizes the organism's entire state in real-time via WebSocket streaming.

### What It Shows

**Agent Council Activity**
Each of the six agents has a dedicated card displaying: current vote (BUY / SELL / HOLD), confidence score, last analysis timestamp, and reasoning excerpt. Cards for agents not enabled on the selected bot are marked `DISABLED` with a dimmed visual state — the UI accurately reflects the active agent pool for each bot configuration.

**Market Regime Panel**
A live regime indicator shows the current classification (RANGING / TRENDING / VOLATILE) with color-coded urgency. Regime changes are broadcast in real-time — operators see the moment the market environment shifts.

**Organism Vital Signs**
The survival state (`HEALTHY` / `WOUNDED` / `ORGAN_FAILURE` / `DECEASED`) and apex tier (`HUNTING` → `SINGULARITY`) are displayed with their threshold indicators. The event log surfaces the last 20 state transitions — every wound, every recovery, every tier unlock — as a live narrative of the organism's life.

**Bot Fleet Command**
The Fleet Summary Bar shows all deployed bots with their status, PnL, and health indicators. Individual bots can be started, stopped, and inspected from the dashboard. The `BotDetailDrawer` expands a full diagnostic view per bot.

### WebSocket Architecture

The Situation Room connects via a persistent WebSocket to the FastAPI backend. The backend runs a **broadcast loop** that throttles emissions (to prevent memory exhaustion on the browser side) and batches telemetry from all active bots into a single, efficient payload per tick.

A **pause/resume control interface** allows operators to halt streaming (to allow the browser to cool down) and resume it at will. The frontend implements exponential backoff on reconnect, ensuring the WebSocket re-establishes gracefully after any disruption.

All telemetry is also persisted to **Firestore** — meaning the Situation Room can reconstruct historical state and the full decision audit trail is available beyond the current session.

---

## 9. Fleet Orchestrator — The Nerve Centre

The `FleetOrchestrator` is the top-level manager that spawns, monitors, and kills bot instances. Each bot is a fully isolated `BotInstance` containing its own engine, AI brain, sub-agent pool, and vital signs.

### Fleet-Level Risk Kill Switch

The orchestrator enforces a **fleet-wide drawdown limit** (`max_fleet_drawdown_pct`). Every 5 seconds, the monitor loop sums all bots' starting equity vs. current equity. If the aggregate drawdown exceeds the threshold, an **atomic halt flag** (`threading.Event`) fires immediately — preventing any bot from opening new positions even during the brief window before individual halt commands are dispatched.

This addresses the classic **TOCTOU (Time of Check / Time of Use) race condition** in multi-bot risk management: the halt flag is set *before* iterating through bots, so no bot can slip a last-second order through while others are being killed.

### Bot Restoration from Firestore

On startup, the orchestrator reads all saved bot configs from Firestore and re-deploys them. Bots with `auto_start` enabled resume trading automatically. An orphan detection mechanism discovers bots with missing parent markers (from pre-migration data) and backfills them — ensuring no bot is lost across restarts.

---

## 10. Resilience Architecture

TradeClaw is engineered to survive hostile conditions — not just in the market, but in its own infrastructure.

| Failure Scenario | TradeClaw's Response |
|---|---|
| Gemini API down / rate-limited | Seamless fallback to local Ollama (Gemma 4B) |
| Ollama unavailable | AI Brain persists "degraded" decision to Firestore, preserves last known good parameters |
| Firestore async loop mismatch | `run_coroutine_threadsafe` dispatches calls from background threads to the correct event loop |
| Market data gap / stale bars | Regime defaults to RANGING (permissive), preventing a stall |
| Excessive drawdown (≥15%) | PROTOCOL_FINAL: extinction callback fires, all positions close, process terminates cleanly |
| Fleet-wide drawdown breach | Atomic halt flag → all bots halted before any can open new positions |
| WebSocket memory pressure | Backend throttling + pause/resume control + exponential backoff on reconnect |
| Limit order not filled | Auto-cancel + market order fallback within `limit_timeout_s` |
| TWAP slippage breach | Abort remaining slices immediately, log SLIPPAGE_ABORT event |
| AI Brain JSON parse failure | Triple-fallback extraction: direct → markdown fence → regex |
| AI parameter out of bounds | `ParamGuardrail.validate()` clamps to nearest safe limit, logs warning |

Every failure mode has a defined response. The system does not crash silently — it logs structured events, broadcasts them to the operator, and degrades gracefully to the next available fallback.

---

## 11. Data Persistence — Full Auditability via Firestore

Every significant event in TradeClaw's lifecycle is persisted to Firestore:

| Collection | Contents |
|---|---|
| `bots` | Bot configurations, current strategy parameters |
| `bot_telemetry` | Per-tick state: regime, signal, agent votes, execution result |
| `ai_decisions` | Full AI Brain evolution history: params before/after, reasoning, trigger, model, agent context |
| `strategy_contexts` | RAG memory: metrics + reasoning snapshots for retrieval-augmented evolution |
| `vital_events` | Organism vital sign transitions (wounds, recoveries, tier unlocks) |
| `fleet_config` | Fleet-wide settings: max_bots, global drawdown limit, sub-agents toggle |
| `live_telemetry` | Fleet summary snapshots pushed every 5 seconds |

This creates **complete operational transparency**. An operator can query the `ai_decisions` collection and reconstruct exactly how the bot's strategy evolved over time — what the model was reasoning, what the market conditions were, what the agents thought, and what parameters the AI chose. This is not a black box.

---

## Summary

TradeClaw is an architectural statement: that sophisticated algorithmic trading doesn't have to be a fragile, opaque black box. Every component has a defined role, every failure mode has a defined response, and every decision is logged with its full reasoning.

The **Multi-Agent System** ensures no single point of analytical failure. The **Regime Detector** ensures the strategy only operates in favorable conditions. The **Vital Signs Monitor** enforces absolute risk discipline. The **AI Brain** — running per-bot with RAG memory, multi-trigger activation, and constitutional guardrails — ensures the strategy never stops improving. The **Executioner** ensures orders are filled at the best attainable price. The **Fleet Orchestrator** enforces fleet-wide survival limits with race-condition-proof halt mechanics. And the **Situation Room** ensures an operator always knows exactly what the organism is doing and why.

It's not a bot. It's an ecosystem.

---

*Generated: April 2026 | Platform: TradeClaw | Status: Live*
