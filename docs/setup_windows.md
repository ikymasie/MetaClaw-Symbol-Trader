# TradeClaw — Windows Setup

MT5 runs **natively** on Windows, so no Wine/container complexity is needed. The bridge server is optional — the backend can import `MetaTrader5` directly.

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | ≥ 3.9 | [python.org](https://www.python.org/downloads/) — check "Add to PATH" |
| Node.js | ≥ 18 | [nodejs.org](https://nodejs.org/) |
| Git | any | [git-scm.com](https://git-scm.com/) |
| MetaTrader 5 | latest | From your broker or [metaquotes.net](https://www.metatrader5.com/) |
| Ollama | latest | Optional — [ollama.com](https://ollama.com/) |

## 1. Clone

```cmd
git clone <repository-url>
cd TradeClaw
```

## 2. Python venv + dependencies

```cmd
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

## 3. Node.js dependencies

```cmd
cd frontend
npm install
cd ..
```

## 4. Environment files

The `setup.sh` script won't run on Windows without Git Bash or WSL. Create the files manually.

### `backend/.env`

```env
# MetaTrader 5
MT5_LOGIN=your_login
MT5_PASSWORD=your_password
MT5_SERVER=Your-Broker-Server
MT5_SYMBOL_SUFFIX=

# AI Brain — Gemini
AI_BRAIN_ENABLED=true
AI_ANALYSIS_INTERVAL_MINUTES=60
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash-lite

# Ollama (local LLM fallback, optional)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=ollama/gemma4:e4b
OLLAMA_MODEL_NAME=gemma4:e4b

# Server
HOST=0.0.0.0
PORT=8000
```

### `frontend/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 5. Start MT5

Launch MetaTrader 5 normally from your desktop. Log in to your broker account. Keep it running in the background.

## 6. Start TradeClaw

Open **two** terminals:

**Terminal 1 — Backend:**
```cmd
cd backend
venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend:**
```cmd
cd frontend
npm run dev
```

## 7. Access

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

## How it connects

On Windows, `backend/mt5_bridge.py` detects `os.name == 'nt'` and imports `MetaTrader5` directly — no RPyC bridge server needed. The backend calls MT5's native Python API.

## Docker on Windows

If you prefer Docker, the container runs backend + frontend (no Wine/MT5 inside). The bridge server runs on the host:

1. Install MT5 on your Windows host
2. Install Python + `pip install MetaTrader5 rpyc`
3. Start the bridge: `python backend\mt5_bridge_server.py`
4. Start Docker: `docker compose up -d`

The container connects via `host.docker.internal:18812`.
