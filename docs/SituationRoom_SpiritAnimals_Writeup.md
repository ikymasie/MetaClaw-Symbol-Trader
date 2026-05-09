# The Spirit Animal System & The Situation Room
### *In Plain English — How TradeClaw's Bot Personalities Work*

---

## The Big Idea

When you deploy a trading bot in TradeClaw, you don't fill out a boring spreadsheet of numbers. You pick a **spirit animal**.

That animal is not just cosmetic. It is a **personality template** — a preset collection of risk settings, trading aggressiveness, and AI behavior that defines *how* the bot hunts for trades. Think of it like choosing a character class in a game: the numbers behind the scenes change depending on who you pick.

Once your bot is live, you can watch it "think" in real-time inside the **Situation Room** — TradeClaw's live command dashboard, where you see every decision the bot's council of AI agents is making, as it happens.

---

## Step 1: The Savanna Wizard — Building Your Bot

When you click **"Deploy Bot"**, a 4-step wizard opens called the **Savanna Wizard**.

```
Step 1: Choose a Market          → Where does it hunt?
           (Equities, ETFs, Crypto, Forex, Commodities)

Step 2: Pick a Symbol            → What does it trade?
           (AAPL, SPY, BTC/USD, or your own custom ticker)

Step 3: Choose a Spirit Animal   → How aggressively does it hunt?
           (Elephant → Buffalo → Rhino → Leopard → Lion)

Step 4: AI Forge                 → The AI names and describes your bot
```

After you pick your animal, you hit **"Forge My Bot"** — and Gemini AI invents a unique tactical codename and a wildlife-documentary-style description just for your bot. Things like:

> *"Iron Elephant SPY — This bot moves through equity markets with the slow, unstoppable force of the African elephant. It conserves capital like a herd protects its young — never rushing, always preserving."*

If the AI is unavailable, it falls back to a built-in name (like *"Phantom Leopard QQQ"*) so you're never left with a blank.

---

## The Five Spirit Animals — What Each One Actually Does

Each animal maps to a **risk level (1–5)** and a preset set of strategy parameters that control how the bot actually trades.

---

### 🐘 Patient Elephant — *Risk Level 1 / Ultra-Conservative*

> *"Slow and unstoppable"*

The Elephant is the most cautious animal in the savanna. It doesn't chase. It doesn't panic. It **waits for the perfect moment** and only enters when everything is precisely right.

**What this means in practice:**
- **Tightest stop-losses** — if a trade goes even slightly wrong, it exits immediately to protect capital
- **Narrow Bollinger Bands** — only triggers when price deviates significantly from its average (a `bb_std_dev` of 2.5, meaning it's pickier about entries)
- **Smallest position size** — only 1 share per trade
- **2-agent council** — only Sentiment and Macro agents vote (the smallest council — fewer opinions, very selective)
- **Strategy: Mean Reversion** — it bets that prices that go too low will bounce back
- **Max daily drawdown: 3%** — the bot shuts new trades down if it loses more than 3% in a day
- **Capital: $25,000 default**

**In the Situation Room:** You'll see only 2 agent cards live (Sentiment + Macro). The rest show as `DISABLED`. Activity is infrequent — long stretches of "Awaiting signal..." are normal. When it fires, it fires with conviction.

---

### 🦬 Grazing Buffalo — *Risk Level 2 / Conservative*

> *"Strength through discipline"*

The Buffalo moves in a herd and only charges when the whole group agrees. It's confident but measured — never reckless.

**What this means in practice:**
- **5-agent full quorum** — all five specialist agents must weigh in, AND at least 3 must agree before anything happens
- **AND-gated signals** — both the Bollinger Band signal AND the Fibonacci level must align simultaneously (double confirmation)
- **Conservative sizing** — moderate position size, balanced drawdown tolerance
- **Strategy: Combined** — uses both mean-reversion and Fibonacci together
- **Max daily drawdown: ~6%**

**In the Situation Room:** All 5 agent cards are live and active. The Buffalo generates the most "deliberation" activity — you'll frequently see agents going `PROCESSING` before reaching a `QUORUM`. It's methodical. It debates before it acts.

---

### 🦏 Steady Rhino — *Risk Level 3 / Balanced*

> *"Charges when confident"*

The Rhino is armoured and patient — but when it spots momentum, it moves fast and hard. It's the middle ground: disciplined enough to avoid reckless trades, aggressive enough to ride strong moves.

**What this means in practice:**
- **Trend-following strategy** — instead of betting on price bouncing back, the Rhino *rides* the trend while it's strong
- **OR-gated Fibonacci** — either the Bollinger OR the Fibonacci signal is enough to trigger (less strict than the Buffalo's AND gate)
- **Faster AI Brain cycles** — the Rhino's AI reviews its own strategy more frequently, adapting quicker to changing market conditions
- **Balanced sizing and stops**
- **Max daily drawdown: ~6%**

**In the Situation Room:** You'll see more frequent signals than the Buffalo, because the Rhino's entry conditions are easier to satisfy. The agent council cycles faster. If the market is trending, the Rhino is the most active.

---

### 🐆 Prowling Leopard — *Risk Level 4 / Aggressive*

> *"Silent, precise, lethal"*

The Leopard ambushes from the shadows. It doesn't wait for consensus — it spots a Fibonacci trap, positions itself silently, and strikes fast.

**What this means in practice:**
- **High quantity entries** — fires larger position sizes per trade
- **Tight Fibonacci levels** — positions very precisely at key support/retracement levels (23.6%, 38.2%, 50%, 61.8%)
- **Rapid scalper strategy** — in and out quickly on short bounces; doesn't hold for long
- **30-minute AI Brain cycles** — constantly re-evaluating its own parameters
- **Narrow entry thresholds** — waits for price to touch a very precise Fib level before striking
- **Max daily drawdown: ~8%**

**In the Situation Room:** The Leopard generates *frequent, fast activity*. Signals fire more often. The agent council turns over quickly. You'll see `PROCESSING` → `APPROVED` → back to `IDLE` in rapid succession during active market sessions.

---

### 🦁 Hungry Lion — *Risk Level 5 / Maximum Aggression*

> *"Apex-mode, no mercy"*

The Lion is the apex predator of the fleet. When the system has proven itself profitable enough to unlock the "APEX" tier, the Lion operates with maximum autonomy, maximum capital, and zero mercy.

**What this means in practice:**
- **Full 5-agent council** — all agents active
- **Maximum position size** — the largest qty of any animal
- **20-minute AI Brain cycles** — the fastest adaptation speed; the AI rewrites its strategy continuously
- **Combined strategy** — uses both Bollinger and Fibonacci simultaneously at full intensity
- **Highest drawdown tolerance** — willing to absorb more short-term pain to capture bigger moves
- **Max daily drawdown: ~10%+**

**In the Situation Room:** The Lion's dashboard is the most *alive* of any bot. All 6 agent cards fire. Cycles happen frequently. The `CYCLES` counter in the bottom-right ticks up rapidly. When the Lion is in APEX tier (>20% profit), it operates with boosted position sizing and a more powerful AI model — this shows up in the `ai_decisions` panel as "model_used: gemini-pro" instead of the flash model.

---

## How the Animal Gets "burned in" to the Bot

When you hit **"Forge My Bot"** and then **"Deploy Bot"**, here's exactly what happens:

```
1. The Wizard sends your choices to the backend:
   { symbol: "NVDA", category: "Equities", personality: "lion", ... }

2. The backend looks up the LION preset:
   → strategy: "combined"
   → qty: 5, stop_loss_pct: 2.5, max_daily_drawdown_pct: 10%
   → bb_std_dev: 1.8 (tight, aggressive entries)
   → sub_agents: all 5 enabled
   → ai_brain_enabled: true, ai_interval_minutes: 20

3. Gemini AI writes a unique name + description for this specific Lion/NVDA combo

4. All of this gets saved to Firestore as the bot's permanent config

5. The bot starts running immediately with these parameters baked in

6. The AI Brain can later EVOLVE these parameters — but always within the
   animal's guardrail range (the Lion can never become as slow as an Elephant)
```

The `animal` field is persisted as a string (e.g., `"lion"`) so the dashboard always knows which spirit animal this bot embodies, even after the AI Brain has evolved its parameters.

---

## The Situation Room — What You're Actually Watching

Once your bot is live, the **Situation Room** is your real-time command center. Here's what everything on screen means:

### Bot Selector (top-left)
A dropdown of all your deployed bots. Select one and the entire dashboard switches to that bot's live feed. The header shows the bot's name and symbol: `FEED: Crimson Lion NVDA [NVDA]`.

### The Live Clock (top-right)
A real-time `HH:MM:SS` clock that only ticks on the client — so it never causes the "flicker" issue you'd get with server-rendered time.

### Stat Pills (top-right row)
Three status counters update in real-time:
- 🟡 **UPSTREAM** — how many agent cards are currently `PROCESSING` a decision
- 🟢 **QUORUM** — how many votes came back as `APPROVED` this cycle
- 🔴 **VETOED** — how many were blocked (by the Risk Manager or insufficient votes)

### Status Bridge (the pipeline strip)
A horizontal flow diagram that shows the bot's current execution phase:
```
SIGNAL DETECTED → COUNCIL DELIBERATING → QUORUM REACHED → ORDER EXECUTING → COMPLETE
```
It lights up step by step as the trade pipeline progresses. If a step stalls, you can see exactly where it stopped.

### The Agent Council Grid (the main panel)
A grid of individual **Agent Cards** — one per AI agent in your bot's council. The number of cards that are *active* vs `DISABLED` depends entirely on which spirit animal you chose:

| Animal | Active Agents |
|---|---|
| 🐘 Elephant | Sentiment + Macro (2 active, 4 disabled) |
| 🦬 Buffalo | All 5 active |
| 🦏 Rhino | Typically 3–4 active |
| 🐆 Leopard | Earnings + Technical (2 active, 4 disabled) |
| 🦁 Lion | All 5 active |

**Disabled cards** appear dimmed at 40% opacity with `DISABLED` status — so you always know which agents are part of *this* bot's configuration vs which ones are globally available but not enabled.

### Inside Each Agent Card
Each card shows a live view of one agent's "mind":

```
┌──────────────────────────────────────────────┐
│ ● APPROVED                        [ICON]     │
│ WATCHMAN                                     │
│ Order-flow quality monitor                   │
│ ──────── progress bar ──────────             │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ ● ● ●  thought-stream                   │ │
│ │ 14:22  Scanning order book depth...     │ │
│ │ 14:22  Spread within tolerance.         │ │
│ │ 14:23  Volume confirms signal.          │ │
│ │ 14:23  Voting APPROVED ✓                │ │
│ └──────────────────────────────────────────┘ │
│                                              │
│ confidence                          87.3%    │
└──────────────────────────────────────────────┘
```

The **thought stream** is a live terminal — you see the agent's reasoning as it runs. This isn't fake. It's the actual LLM reasoning text from the agent's analysis, scrolling in real-time as the WebSocket broadcasts it.

Card border colors change:
- 🟡 Amber glow = `PROCESSING` / thinking
- 🟢 Green glow = `APPROVED` / voted yes  
- 🔴 Red glow = `VETOED` / voted no or blocked

Cards are **sorted** — active cards appear first, disabled cards sink to the bottom.

### CYCLES counter (bottom-right)
Every time the bot completes a full tick cycle (price check → regime → signal → deliberation → execution), the counter ticks up. This tells you the bot is alive and working even during quiet market periods where no trades are fired.

### Footer Status Line
```
ALGORITHM DEPLOYMENT: TARGETING · MAS V2 PROTOCOL · CAPITAL-PROTECTED
```
Shows `SCANNING` when no bot is selected, `TARGETING` when actively monitoring a specific bot.

---

## The Full Flow — From Animal Choice to Live Dashboard

Here's the complete journey from picking your spirit animal to watching it hunt in the Situation Room:

```
YOU PICK:  🦁 Lion + NVDA
                │
                ▼
WIZARD FORGE:   AI names it "Crimson Lion NVDA"
                Sets: qty=5, agents=all5, ai_cycle=20min, combined strategy
                                │
                                ▼
DEPLOY:         Config saved to Firestore → Bot engine starts → AI Brain activates
                                │
                                ▼
SITUATION ROOM: You select "Crimson Lion NVDA" from dropdown
                                │
                                ▼
EVERY TICK:     Price arrives → Regime check → Bollinger+Fib signal?
                                │ YES
                                ▼
                All 5 agent cards light up PROCESSING (amber pulse)
                Thought streams start scrolling in each card
                                │
                Statistical quorum: 3/5 APPROVED ✅
                Risk Manager: APPROVED ✅
                                │
                                ▼
                Status Bridge advances to "ORDER EXECUTING"
                Executioner routes the trade to MetaTrader 5
                                │
                                ▼
                Cards settle to APPROVED (green glow)
                QUORUM counter increments
                CYCLES counter increments
                Vital signs update
```

And every 20 minutes (because the Lion has a fast AI cycle), the AI Brain also fires in the background — reviewing the last N trades, potentially nudging the Bollinger period or stop-loss percentage, and persisting its reasoning to Firestore. The bot quietly evolves — all while you watch.

---

## Summary

| | 🐘 Elephant | 🦬 Buffalo | 🦏 Rhino | 🐆 Leopard | 🦁 Lion |
|---|---|---|---|---|---|
| Risk Level | 1 | 2 | 3 | 4 | 5 |
| Strategy | Mean Rev | Combined | Trend | Mean Rev | Combined |
| Active Agents | 2 | 5 | ~3–4 | 2 | 5 |
| Trade Frequency | Very Low | Low | Medium | High | Very High |
| AI Brain Cycle | 60 min | 60 min | 30 min | 30 min | 20 min |
| Max Daily DD | 3% | 6% | 6% | 8% | 10%+ |
| Situation Room Activity | Quiet | Deliberate | Moderate | Rapid | Intense |

The spirit animal is not just a name. It is the bot's **operating constitution** — how it thinks, how it risks, how it hunts, and how it appears on screen. The Situation Room is where that constitution comes alive, in real-time, for every trade the organism considers.

---

*TradeClaw · Savanna Wizard & Situation Room · April 2026*
