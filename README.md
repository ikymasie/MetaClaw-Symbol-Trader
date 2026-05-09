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
