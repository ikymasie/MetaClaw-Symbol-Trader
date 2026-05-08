#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw — First-Time Setup & Environment Wizard
#  Run once after cloning:  chmod +x setup.sh && ./setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colours & Symbols ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'
CHECK="${GREEN}✔${RESET}"
CROSS="${RED}✖${RESET}"
WARN="${YELLOW}⚠${RESET}"
ARROW="${CYAN}➜${RESET}"

# ── Resolve project root ──────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# ══════════════════════════════════════════════════════════════════════════════
#  BANNER
# ══════════════════════════════════════════════════════════════════════════════
clear
echo ""
echo -ne "${CYAN}${BOLD}"
cat << 'BANNER'
  ___________                  .___      _________  .__                 
  \__    ___/_______ _____   __| _/ ____ \_   ___ \ |  |  _____  __  __
    |    |  \_  __ \\__  \ / __ |_/ __ \/    \  \/ |  |  \__  \ \ \/ \/ /
    |    |   |  | \/ / __ \\  ___ \  ___/\     \____|  |__ / __ \_\     / 
    |____|   |__|   (____  /\_____|\___  >\______  /|____/(____  / \/\_/  
                         \/            \/        \/            \/         
BANNER
echo -e "${RED}${BOLD}  [ EXPERIMENTAL PLATFORM — USE AT YOUR OWN RISK ]${RESET}"
echo -e "${RESET}"
echo -e "  ${BOLD}TradeClaw${RESET} ${DIM}v2.0.0${RESET}"
echo -e "  ${DIM}Multi-Agent AI Trading Platform${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  ${DIM}Developer :${RESET} ${BOLD}ikymasie${RESET}"
echo -e "  ${DIM}License   :${RESET} Proprietary — All Rights Reserved"
echo -e "  ${DIM}Stack     :${RESET} Python/FastAPI + Next.js + Firebase"
echo ""
echo -e "  ${MAGENTA}${BOLD}⚡ FIRST-TIME SETUP WIZARD${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  PREREQUISITE CHECKS
# ══════════════════════════════════════════════════════════════════════════════
echo -e "${BOLD}  1 / 5  PREREQUISITE CHECKS${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

PREREQ_OK=true

# Python
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
        echo -e "  ${CHECK}  Python ${PY_VER}"
    else
        echo -e "  ${CROSS}  Python ${PY_VER} — ${RED}requires ≥ 3.9${RESET}"
        PREREQ_OK=false
    fi
else
    echo -e "  ${CROSS}  Python — ${RED}not found${RESET}"
    PREREQ_OK=false
fi

# Node
if command -v node &>/dev/null; then
    NODE_VER=$(node --version | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        echo -e "  ${CHECK}  Node.js ${NODE_VER}"
    else
        echo -e "  ${CROSS}  Node.js ${NODE_VER} — ${RED}requires ≥ 18${RESET}"
        PREREQ_OK=false
    fi
else
    echo -e "  ${CROSS}  Node.js — ${RED}not found${RESET}"
    PREREQ_OK=false
fi

# npm
if command -v npm &>/dev/null; then
    NPM_VER=$(npm --version)
    echo -e "  ${CHECK}  npm ${NPM_VER}"
else
    echo -e "  ${CROSS}  npm — ${RED}not found${RESET}"
    PREREQ_OK=false
fi

# pip
if command -v pip3 &>/dev/null || python3 -m pip --version &>/dev/null 2>&1; then
    PIP_VER=$(python3 -m pip --version 2>/dev/null | awk '{print $2}' || pip3 --version | awk '{print $2}')
    echo -e "  ${CHECK}  pip ${PIP_VER}"
else
    echo -e "  ${CROSS}  pip — ${RED}not found${RESET}"
    PREREQ_OK=false
fi

# Ollama (optional)
if command -v ollama &>/dev/null; then
    OLLAMA_VER=$(ollama --version 2>/dev/null | head -1 || echo "installed")
    echo -e "  ${CHECK}  Ollama ${DIM}(local LLM fallback)${RESET}"
    HAS_OLLAMA=true
else
    echo -e "  ${WARN}  Ollama — ${YELLOW}not found (optional — install for local LLM fallback)${RESET}"
    HAS_OLLAMA=false
fi

echo ""

if [ "$PREREQ_OK" = false ]; then
    echo -e "  ${RED}${BOLD}✖ Missing required prerequisites. Please install them and re-run.${RESET}"
    echo ""
    exit 1
fi

echo -e "  ${GREEN}${BOLD}All prerequisites satisfied.${RESET}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  BACKEND SETUP
# ══════════════════════════════════════════════════════════════════════════════
echo -e "${BOLD}  2 / 5  BACKEND SETUP${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

if [ ! -d "backend/venv" ]; then
    echo -e "  ${ARROW}  Creating Python virtual environment..."
    python3 -m venv backend/venv
    echo -e "  ${CHECK}  Virtual environment created"
else
    echo -e "  ${CHECK}  Virtual environment already exists"
fi

echo -e "  ${ARROW}  Installing Python dependencies..."
source backend/venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt
deactivate
echo -e "  ${CHECK}  Python dependencies installed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  FRONTEND SETUP
# ══════════════════════════════════════════════════════════════════════════════
echo -e "${BOLD}  3 / 5  FRONTEND SETUP${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

echo -e "  ${ARROW}  Installing Node.js dependencies..."
(cd frontend && npm install --silent 2>&1 | tail -1)
echo -e "  ${CHECK}  Node.js dependencies installed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  ENVIRONMENT CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
echo -e "${BOLD}  4 / 5  ENVIRONMENT CONFIGURATION${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo ""

# Helper to prompt with default
prompt_with_default() {
    local var_name="$1"
    local prompt_text="$2"
    local default_val="$3"
    local is_secret="${4:-false}"

    if [ "$is_secret" = true ]; then
        echo -ne "  ${ARROW}  ${prompt_text} ${DIM}[hidden]${RESET}: "
        read -s user_val
        echo ""
    else
        echo -ne "  ${ARROW}  ${prompt_text} ${DIM}[${default_val}]${RESET}: "
        read user_val
    fi

    if [ -z "$user_val" ]; then
        eval "$var_name='$default_val'"
    else
        eval "$var_name='$user_val'"
    fi
}

# ── Backend .env ──────────────────────────────────────────────────────────────
if [ -f "backend/.env" ]; then
    echo -e "  ${WARN}  ${YELLOW}backend/.env already exists.${RESET}"
    echo -ne "  ${ARROW}  Overwrite? ${DIM}[y/N]${RESET}: "
    read OVERWRITE_BACKEND
    if [[ ! "$OVERWRITE_BACKEND" =~ ^[Yy]$ ]]; then
        echo -e "  ${CHECK}  Keeping existing backend/.env"
        SKIP_BACKEND_ENV=true
    else
        SKIP_BACKEND_ENV=false
    fi
else
    SKIP_BACKEND_ENV=false
fi

if [ "$SKIP_BACKEND_ENV" = false ]; then
    echo ""
    echo -e "  ${CYAN}${BOLD}  ── MetaTrader 5 (MT5 Broker) ──${RESET}"
    echo -e "  ${DIM}  Server name is shown in MT5 terminal: File → Open Account → server list.${RESET}"
    prompt_with_default MT5_LOGIN "  MT5 Login" ""
    prompt_with_default MT5_PASS  "  MT5 Password" "" true
    prompt_with_default MT5_SRV   "  MT5 Server" ""
    prompt_with_default MT5_SUFFIX "  Symbol Suffix (e.g. _i)" ""

    echo ""
    echo -e "  ${CYAN}${BOLD}  ── Gemini API (Cloud LLM) ──${RESET}"
    echo -e "  ${DIM}  Get a free key at: https://aistudio.google.com/apikey${RESET}"
    echo -e "  ${DIM}  Leave blank to use Ollama only.${RESET}"
    prompt_with_default GEMINI_KEY "  Gemini API Key" "" true
    prompt_with_default GEMINI_MDL "  Gemini Model" "gemini-2.5-flash-lite-preview"

    echo ""
    echo -e "  ${CYAN}${BOLD}  ── Ollama (Local LLM Fallback) ──${RESET}"
    prompt_with_default OLLAMA_URL  "  Ollama Base URL" "http://localhost:11434"
    prompt_with_default OLLAMA_MDL  "  Ollama Model" "gemma4:e4b"

    echo ""
    echo -e "  ${CYAN}${BOLD}  ── Server ──${RESET}"
    prompt_with_default SRV_HOST "  Host" "0.0.0.0"
    prompt_with_default SRV_PORT "  Port" "8000"

    # Write backend .env
    cat > backend/.env << ENVFILE
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw Backend — Generated by setup.sh on $(date '+%Y-%m-%d %H:%M:%S')
# ══════════════════════════════════════════════════════════════════════════════

# ── MetaTrader 5 ──────────────────────────────────────────────────────────────
MT5_LOGIN=${MT5_LOGIN}
MT5_PASSWORD=${MT5_PASS}
MT5_SERVER=${MT5_SRV}
MT5_SYMBOL_SUFFIX=${MT5_SUFFIX}

# ── AI Brain — Gemini (Cloud LLM) ────────────────────────────────────────────
AI_BRAIN_ENABLED=true
AI_ANALYSIS_INTERVAL_MINUTES=60
GEMINI_API_KEY=${GEMINI_KEY}
GEMINI_MODEL=${GEMINI_MDL}

# ── AI Brain — Ollama (Local LLM Fallback) ────────────────────────────────────
OLLAMA_BASE_URL=${OLLAMA_URL}
OLLAMA_MODEL=ollama/${OLLAMA_MDL}
OLLAMA_MODEL_NAME=${OLLAMA_MDL}

# ── Server ────────────────────────────────────────────────────────────────────
HOST=${SRV_HOST}
PORT=${SRV_PORT}
ENVFILE
    echo ""
    echo -e "  ${CHECK}  ${GREEN}backend/.env created${RESET}"
fi

# ── Frontend .env.local ───────────────────────────────────────────────────────
echo ""
if [ -f "frontend/.env.local" ]; then
    echo -e "  ${WARN}  ${YELLOW}frontend/.env.local already exists.${RESET}"
    echo -ne "  ${ARROW}  Overwrite? ${DIM}[y/N]${RESET}: "
    read OVERWRITE_FRONTEND
    if [[ ! "$OVERWRITE_FRONTEND" =~ ^[Yy]$ ]]; then
        echo -e "  ${CHECK}  Keeping existing frontend/.env.local"
        SKIP_FRONTEND_ENV=true
    else
        SKIP_FRONTEND_ENV=false
    fi
else
    SKIP_FRONTEND_ENV=false
fi

if [ "$SKIP_FRONTEND_ENV" = false ]; then
    echo ""
    echo -e "  ${CYAN}${BOLD}  ── Firebase (Frontend SDK) ──${RESET}"
    echo -e "  ${DIM}  Get these from: Firebase Console → Project Settings → Web App${RESET}"
    echo -e "  ${DIM}  Leave blank for defaults (or configure later in frontend/.env.local)${RESET}"
    prompt_with_default FB_API_KEY  "  Firebase API Key" ""
    prompt_with_default FB_AUTH     "  Firebase Auth Domain" ""
    prompt_with_default FB_PROJECT  "  Firebase Project ID" ""
    prompt_with_default FB_BUCKET   "  Firebase Storage Bucket" ""
    prompt_with_default FB_SENDER   "  Firebase Messaging Sender ID" ""
    prompt_with_default FB_APP_ID   "  Firebase App ID" ""

    echo ""
    echo -e "  ${CYAN}${BOLD}  ── Backend API URL ──${RESET}"
    BACKEND_URL="http://localhost:${SRV_PORT:-8000}"
    prompt_with_default API_URL "  Backend API URL" "$BACKEND_URL"

    cat > frontend/.env.local << ENVFILE
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw Frontend — Generated by setup.sh on $(date '+%Y-%m-%d %H:%M:%S')
# ══════════════════════════════════════════════════════════════════════════════

NEXT_PUBLIC_FIREBASE_API_KEY=${FB_API_KEY}
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${FB_AUTH}
NEXT_PUBLIC_FIREBASE_PROJECT_ID=${FB_PROJECT}
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=${FB_BUCKET}
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=${FB_SENDER}
NEXT_PUBLIC_FIREBASE_APP_ID=${FB_APP_ID}

NEXT_PUBLIC_API_URL=${API_URL}
ENVFILE
    echo ""
    echo -e "  ${CHECK}  ${GREEN}frontend/.env.local created${RESET}"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  FIREBASE SERVICE ACCOUNT (Fleet Persistence)
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}  5 / 6  FIREBASE SERVICE ACCOUNT SETUP${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  The Execution Engine requires a Service Account JSON key to"
echo -e "  persist fleet configurations and bot states."
echo ""
echo -e "  ${CYAN}${BOLD}  1.${RESET} Go to ${BOLD}Firebase Console${RESET} → Project Settings"
echo -e "  ${CYAN}${BOLD}  2.${RESET} Select the ${BOLD}Service Accounts${RESET} tab"
echo -e "  ${CYAN}${BOLD}  3.${RESET} Click ${BOLD}Generate New Private Key${RESET} → Download JSON"
echo ""

if [ -f "backend/service-account-key.json" ]; then
    echo -e "  ${CHECK}  ${GREEN}backend/service-account-key.json already exists.${RESET}"
    echo -ne "  ${ARROW}  Replace it? ${DIM}[y/N]${RESET}: "
    read REPLACE_SA
    if [[ "$REPLACE_SA" =~ ^[Yy]$ ]]; then
        DO_SA_SETUP=true
    else
        DO_SA_SETUP=false
    fi
else
    DO_SA_SETUP=true
fi

if [ "$DO_SA_SETUP" = true ]; then
    echo -ne "  ${ARROW}  Path to downloaded JSON key: "
    read -e SA_PATH
    # Remove quotes if pasted
    SA_PATH=$(echo "$SA_PATH" | sed "s/['\"]//g")

    if [ -f "$SA_PATH" ]; then
        cp "$SA_PATH" "backend/service-account-key.json"
        echo -e "  ${CHECK}  ${GREEN}Service account key installed to backend/service-account-key.json${RESET}"
    else
        echo -e "  ${WARN}  ${YELLOW}Key not found at '$SA_PATH'. Skipped.${RESET}"
        echo -e "  ${DIM}  (You can manually copy it to backend/service-account-key.json later)${RESET}"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA MODEL (optional)
# ══════════════════════════════════════════════════════════════════════════════
echo ""
if [ "$HAS_OLLAMA" = true ]; then
    echo -e "${BOLD}  6 / 6  OLLAMA MODEL SETUP${RESET}"
    echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
    MODEL_TO_PULL="${OLLAMA_MDL:-gemma4:e4b}"
    echo -ne "  ${ARROW}  Pull Ollama model '${MODEL_TO_PULL}'? ${DIM}[Y/n]${RESET}: "
    read PULL_OLLAMA
    if [[ ! "$PULL_OLLAMA" =~ ^[Nn]$ ]]; then
        echo -e "  ${ARROW}  Pulling ${MODEL_TO_PULL}... ${DIM}(this may take several minutes)${RESET}"
        ollama pull "$MODEL_TO_PULL" || echo -e "  ${WARN}  ${YELLOW}Failed to pull model — you can run 'ollama pull ${MODEL_TO_PULL}' later.${RESET}"
        echo -e "  ${CHECK}  Ollama model ready"
    else
        echo -e "  ${DIM}  Skipped. Run 'ollama pull ${MODEL_TO_PULL}' when ready.${RESET}"
    fi
else
    echo -e "${BOLD}  6 / 6  OLLAMA MODEL SETUP${RESET}"
    echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
    echo -e "  ${DIM}  Ollama not installed — skipping model pull.${RESET}"
    echo -e "  ${DIM}  Install later: https://ollama.com${RESET}"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo ""
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}${BOLD}  ✔  SETUP COMPLETE${RESET}"
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${BOLD}Environment Summary${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

if [ -f "backend/.env" ]; then
    if grep -q "MT5_LOGIN=.\+" backend/.env 2>/dev/null; then
        echo -e "  ${CHECK}  MetaTrader 5       ${GREEN}configured${RESET}"
    else
        echo -e "  ${WARN}  MetaTrader 5       ${YELLOW}not configured${RESET}"
    fi
    if grep -q "GEMINI_API_KEY=.\+" backend/.env 2>/dev/null; then
        echo -e "  ${CHECK}  Gemini API         ${GREEN}configured${RESET}"
    else
        echo -e "  ${WARN}  Gemini API         ${YELLOW}not configured (Ollama-only mode)${RESET}"
    fi
    echo -e "  ${CHECK}  Ollama Fallback    ${GREEN}configured${RESET}"
else
    echo -e "  ${CROSS}  Backend .env       ${RED}missing${RESET}"
fi

if [ -f "frontend/.env.local" ]; then
    echo -e "  ${CHECK}  Frontend .env      ${GREEN}configured${RESET}"
else
    echo -e "  ${CROSS}  Frontend .env      ${RED}missing${RESET}"
fi

if [ -f "backend/service-account-key.json" ]; then
    echo -e "  ${CHECK}  Firebase SA Key    ${GREEN}found${RESET}"
else
    echo -e "  ${WARN}  Firebase SA Key    ${YELLOW}not found (fleet persistence disabled)${RESET}"
fi

echo ""
echo -e "  ${BOLD}Next Steps${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  ${ARROW}  Start the platform:  ${BOLD}./start.sh${RESET}"
echo -e "  ${ARROW}  Stop the platform:   ${BOLD}./stop.sh${RESET}"
echo ""
echo -e "  ${DIM}Backend API  → http://localhost:${SRV_PORT:-8000}${RESET}"
echo -e "  ${DIM}Dashboard    → http://localhost:3000${RESET}"
echo -e "  ${DIM}API Docs     → http://localhost:${SRV_PORT:-8000}/docs${RESET}"
echo ""
