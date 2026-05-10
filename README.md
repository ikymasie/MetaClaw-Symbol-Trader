<div align="center">

```
  ___________                  .___      _________  .__                 
  \__    ___/_______ _____   __| _/ ____ \_   ___ \ |  |  _____  __  __
    |    |  \_  __ \\__  \ / __ |_/ __ \/    \  \/ |  |  \__  \ \ \/ \/ /
    |    |   |  | \/ / __ \\  ___ \  ___/\     \____|  |__ / __ \_\     / 
    |____|   |__|   (____  /\_____|\___  >\______  /|____/(____  / \/\_/  
                         \/            \/        \/            \/         
```

**Multi-Agent AI Trading Platform**

*6 expert agents • Quorum deliberation • Smart order routing • Real-time Situation Room*

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-2.0-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![Firebase](https://img.shields.io/badge/Firebase-Firestore-FFCA28?style=flat-square&logo=firebase&logoColor=black)](https://firebase.google.com)
[![Buy Developer Coffee](https://img.shields.io/badge/Buy_Developer_Coffee-FFDD00?style=flat-square&logo=buy-me-a-coffee&logoColor=black)](https://paypal.me/digitallandscape)

</div>

---

## Overview

TradeClaw is an AI-powered algorithmic trading platform built on a **Multi-Agent System (MAS)** architecture. Six specialized sub-agents — Sentiment, Macro, Earnings, Technical, Risk, and an Executioner — deliberate in real-time via a quorum protocol to decide on trade actions. A singleton AI "Brain" continuously evolves strategy parameters through periodic LLM analysis.

---

## Deep Dive: How TradeClaw Hunts

TradeClaw is not a simple script that buys when a line crosses another line. It behaves more like a digital organism, waiting patiently for specific environmental conditions before risking capital. Its core logic is divided into three layers: **Environmental Awareness**, **The Multi-Agent Quorum**, and **The Financial Immune System**.

### 1. Environmental Awareness: Regime & Confluence

Before the bot even considers a trade, it scans the "terrain" to determine if the market conditions are favorable.

*   **Regime Detection**: The bot uses ADX (Average Directional Index) and ATR (Average True Range) to classify the market into three states:
    *   **RANGING**: Low ADX, normal ATR. This is the bot's prime hunting ground. Mean reversion strategies (buying dips, selling rips) thrive here.
    *   **TRENDING**: High ADX. Price has strong directional momentum. Fading a strong trend is dangerous, so the bot gates mean-reversion entries and activates Trend Following logic.
    *   **VOLATILE**: ATR z-score spikes. Slippage risk is elevated. The bot hides and refuses to open new positions until the storm passes.
*   **The Confluence Gate**: Even in a Ranging market, the bot won't just blindly buy a dip. It requires a "3-Pillar Confluence" to confirm an entry:
    1.  **Bollinger Bands**: Price must be statistically stretched (touching/piercing the upper or lower bands).
    2.  **VWAP (Volume Weighted Average Price)**: Price must be stretched away from where the bulk of institutional volume traded for the session.
    3.  **Fibonacci Retracement**: The bot measures the last dominant price swing and waits for price to pull back to key psychological levels (e.g., the 61.8% Golden Ratio) AND confirm a bounce.
    4.  **ICT Kill Zones (Optional)**: If enabled, it only hunts during high-liquidity institutional windows (New York or London opens).

### 2. The Multi-Agent System (MAS) Quorum

When the technical indicators produce an actionable signal (e.g., "BUY"), the bot does not immediately execute it. Instead, the signal is proposed to a panel of **Six AI Sub-Agents**, each specializing in a different domain:

1.  **Technical Agent**: Reviews chart structures, RSI, and Bollinger deviations.
2.  **Sentiment Agent**: Monitors external news, social feeds, and broader market sentiment for sudden shifts.
3.  **Macro Agent**: Checks macroeconomic conditions (VIX, yield curves) to ensure systemic stability.
4.  **Earnings Agent**: Consults the calendar to ensure the bot isn't stepping in front of a volatile corporate earnings report.
5.  **Risk Manager Agent**: Evaluates the bot's current drawdown, exposure, and daily PnL limits. Has veto power to block any trade.
6.  **Executioner Agent**: Once the panel votes and achieves a passing **Quorum Score**, the Executioner takes over. It determines the best way to route the order (e.g., Market vs. Limit, TWAP slicing for large orders) to minimize slippage.

### 3. The Financial Immune System: Kelly Criterion & Vital Signs

Instead of trading a flat dollar amount or fixed lot size, TradeClaw treats capital preservation as a biological imperative.

*   **Kelly Criterion Position Sizing**: The bot continuously tracks its historical win rate and average win/loss ratio. It uses the Kelly Criterion formula to mathematically size each trade based on its *proven edge*. If the bot is performing poorly (edge < 0), it drastically reduces its trade size to minimums. If it's dominating, it scales up.
*   **Vital Signs Protocol**: The bot maps its financial health to biological states:
    *   **HEALTHY (Hunting/Dominant/Apex)**: PnL is positive. The bot trades with confidence and higher Kelly fractions.
    *   **WOUNDED**: The bot has suffered minor drawdowns. It switches to "Eighth-Kelly" mode, prioritizing capital preservation over growth.
    *   **ORGAN FAILURE**: Drawdown hits a critical threshold (e.g., 10%). The bot halts all new entries, entering a defensive mode to protect remaining lifeblood.
    *   **DECEASED**: Drawdown reaches the fatal limit (e.g., 15%). The "Protocol Final" executes, liquidating all open positions and shutting down the strategy engine to prevent total account ruin.

---

### 4. Technical Architecture: How it all Connects

TradeClaw is built to be modular and real-time:
*   **The Backend (Python/FastAPI)**: This is the brain of the operation. It runs the strategy engines, calculates the indicators (VWAP, Bollinger, etc.), manages the MAS Quorum, and hosts the AI components.
*   **The MT5 Bridge**: Because MetaTrader 5 (MT5) requires a Windows environment, TradeClaw runs a headless MT5 terminal inside a specialized container (using Wine on Linux/amd64). A Python bridge connects the FastAPI backend directly to this MT5 instance for live, low-latency market data and order execution.
*   **The Situation Room (Next.js)**: The frontend dashboard provides a real-time view into the bot's mind. It visualizes the current price charts, indicator bands, regime state, and most importantly, the live voting results from the 6 AI agents.
*   **Persistence (Firebase/Firestore)**: Every decision, agent vote, and executed trade is logged to Firestore, providing an immutable audit trail and allowing the AI Brain to review past performance and evolve the strategy.

---

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                  SITUATION ROOM                      │
│              (Next.js Dashboard)                     │
│   Live agent votes · Market charts · Fleet control   │
└──────────────────────┬──────────────────────────────┘
                       │ WebSocket + REST
┌──────────────────────▼──────────────────────────────┐
│               TRADECLAW ENGINE                       │
│              (FastAPI Backend)                        │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │Sentiment │  │  Macro   │  │ Earnings │          │
│  │  Agent   │  │  Agent   │  │  Agent   │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │              │              │                │
│       └──────────────┼──────────────┘                │
│                      ▼                               │
│              ┌──────────────┐                        │
│              │  EXECUTIONER │ ← Quorum Vote          │
│              │   (Final)    │                        │
│              └──────┬───────┘                        │
│                     ▼                                │
│  ┌─────────────────────────────────────────┐        │
│  │  Bot Engine · Regime Detector · VWAP    │        │
│  │  Fibonacci · Bollinger · Kelly Sizing   │        │
│  └─────────────────────────────────────────┘        │
│                     │                                │
│          MetaTrader 5 API (Paper/Live)                      │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

| Tool | Version | Required |
|------|---------|----------|
| Python | ≥ 3.9 | ✅ |
| Node.js | ≥ 18 | ✅ |
| npm | ≥ 8 | ✅ |
| Ollama | latest | Optional (local LLM fallback) |

### 1. Clone & Setup

```bash
git clone <repository-url>
cd TradeClaw
chmod +x setup.sh start.sh stop.sh
./setup.sh
```

The setup wizard will:
- ✅ Verify prerequisites (Python, Node, npm, Ollama)
- ✅ Create Python virtual environment & install dependencies
- ✅ Install Node.js dependencies
- ✅ Walk you through API key configuration
- ✅ Generate `backend/.env` and `frontend/.env.local`
- ✅ Optionally pull Ollama model for local LLM inference

### 2. Start

```bash
./start.sh
```

This launches **both** backend and frontend with a branded console:

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | [http://localhost:3000](http://localhost:3000) | Situation Room UI |
| API Server | [http://localhost:8000](http://localhost:8000) | REST + WebSocket |
| API Docs | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger/OpenAPI |

### 3. Stop

```bash
./stop.sh
# — or press Ctrl+C in the start.sh terminal
```

## 🚀 Quick Start (Production/Deployment)

1. **Prerequisites**: Docker, MetaTrader 5 Account (Demo or Live).
2. **Setup**: Run `./setup.sh`. It will prompt for your MT5 broker credentials and AI API keys.
3. **Launch**: `./start_all.sh`.
4. **Access**: `http://localhost:3000`.

## 🛠 Tech Stack

- **Frontend**: Next.js 14 (App Router), TailwindCSS, Framer Motion, React Query, Lucide Icons.
- **Backend**: Python (FastAPI), MetaTrader5 (Python SDK), LangGraph (Agentic Framework).
- **AI Brain**: Google Gemini 1.5 Pro, Ollama (Local LLM fallback).
- **Persistence**: Firestore (Decision Logs, Fleet State).
- **Terminal**: MT5 Windows Terminal running in Wine/Docker (linux/amd64).

## 🔑 Environment Variables

The `./setup.sh` script generates a `.env` file for you. If you need to configure it manually:

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `MT5_LOGIN` | MetaTrader 5 Account Number | — |
| `MT5_PASSWORD` | MetaTrader 5 Password | — |
| `MT5_SERVER` | MetaTrader 5 Server Name | `MetaQuotes-Demo` |
| `MT5_SYMBOL_SUFFIX` | Broker symbol suffix (e.g. `_i`, `.m`) | (Optional) |
| `GEMINI_API_KEY` | Google AI Studio Key | — |
| `FIRESTORE_PROJECT_ID` | Firebase Project ID | — |
| `WS_URL` | WebSocket endpoint for data feed | `ws://backend:8000/ws` |
| `BACKEND_URL` | REST API endpoint | `http://backend:8000` |
| `OLLAMA_MODEL_NAME` | Ollama model for inference | `gemma4:e4b` |
| `AI_BRAIN_ENABLED` | Enable AI strategy evolution | `true` |
| `HOST` | Backend bind address | `0.0.0.0` |
| `PORT` | Backend port | `8000` |


| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_FIREBASE_*` | Firebase client SDK configuration |
| `NEXT_PUBLIC_API_URL` | Backend API URL (`http://localhost:8000`) |

---

## Project Structure

```
TradeClaw/
├── backend/                 # Python FastAPI backend
│   ├── main.py              # App entrypoint + API routes
│   ├── fleet.py             # Multi-bot fleet orchestration
│   ├── bot_engine.py        # Core trading engine
│   ├── sub_agents.py        # 6 MAS agents (Sentiment, Macro, etc.)
│   ├── ai_brain.py          # Singleton AI strategy evolution
│   ├── strategy.py          # Mean reversion + indicator engine
│   ├── config.py            # Runtime configuration
│   ├── firebase_store.py    # Firestore persistence
│   ├── requirements.txt     # Python dependencies
│   └── .env.example         # Environment template
├── frontend/                # Next.js dashboard
│   ├── src/                 # React components + pages
│   ├── package.json         # Node dependencies
│   └── .env.example         # Environment template
├── docs/                    # Architecture & strategy docs
├── setup.sh                 # First-time setup wizard
├── start.sh                 # Launch backend + frontend
├── stop.sh                  # Graceful shutdown
├── LICENSE                  # Proprietary license
└── README.md                # This file
```

---

## LLM Configuration

TradeClaw supports a **dual-LLM architecture** with automatic fallback:

| Provider | Use Case | Cost |
|----------|----------|------|
| **Gemini** (Cloud) | Primary — fast, high-quality inference | Free tier available |
| **Ollama** (Local) | Fallback — runs when Gemini quota is exhausted | Free (runs locally) |

### Setting up Ollama

```bash
# Install (macOS)
brew install ollama

# Pull the default model
ollama pull gemma4:e4b

# Ollama runs automatically in the background
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture Writeup](docs/TradeClaw_Architecture_Writeup.md) | Full system architecture & MAS protocol |
| [Spirit Animals](docs/SituationRoom_SpiritAnimals_Writeup.md) | Bot personality system |
| [Commercialization Strategy](docs/tradeclaw_commercialization_strategy.md) | Business models & monetization |

---

## License

Proprietary — All Rights Reserved. See [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built with 🧠 by <strong>ikymasie</strong></sub>
<br/><br/>
<a href="https://paypal.me/digitallandscape">
  <img src="https://img.shields.io/badge/Buy_Developer_Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Developer Coffee" />
</a>
</div>
