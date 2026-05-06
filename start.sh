#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw — Unified Launcher
#  Starts both backend (FastAPI) and frontend (Next.js) with branded output.
#  Usage:  ./start.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BLUE='\033[0;34m'
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
PID_DIR="$ROOT_DIR/.pids"
mkdir -p "$PID_DIR"

# ══════════════════════════════════════════════════════════════════════════════
#  BANNER
# ══════════════════════════════════════════════════════════════════════════════
clear
echo ""
echo -e "${CYAN}${BOLD}"
BANNER
echo -e "${RED}${BOLD}  [ EXPERIMENTAL PLATFORM — USE AT YOUR OWN RISK ]${RESET}"
echo -e "${RESET}"
echo -e "  ${BOLD}TradeClaw${RESET} ${DIM}v2.0.0${RESET}  ${DIM}—${RESET}  ${BOLD}Multi-Agent AI Trading Platform${RESET}"
echo -e "  ${DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${DIM}Developer  :${RESET}  ikymasie"
echo -e "  ${DIM}License    :${RESET}  Proprietary — All Rights Reserved"
echo -e "  ${DIM}Repository :${RESET}  ${DIM}$(git remote get-url origin 2>/dev/null || echo 'local')${RESET}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  ENVIRONMENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════
echo -e "  ${BOLD}⚙  ENVIRONMENT${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

# Versions
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
NODE_VER=$(node --version 2>/dev/null | sed 's/v//')
echo -e "  ${DIM}Python     :${RESET}  ${PY_VER}"
echo -e "  ${DIM}Node.js    :${RESET}  ${NODE_VER}"

# Backend port
BACKEND_PORT=$(grep -E "^PORT=" backend/.env 2>/dev/null | cut -d= -f2 || echo "8000")
BACKEND_PORT="${BACKEND_PORT:-8000}"
echo -e "  ${DIM}Backend    :${RESET}  http://localhost:${BACKEND_PORT}"
echo -e "  ${DIM}Dashboard  :${RESET}  http://localhost:3000"

# LLM Status
if grep -q "GEMINI_API_KEY=.\+" backend/.env 2>/dev/null; then
    GEMINI_MODEL=$(grep -E "^GEMINI_MODEL=" backend/.env 2>/dev/null | cut -d= -f2 || echo "—")
    echo -e "  ${DIM}Cloud LLM  :${RESET}  ${GREEN}Gemini${RESET} ${DIM}(${GEMINI_MODEL})${RESET}"
else
    echo -e "  ${DIM}Cloud LLM  :${RESET}  ${YELLOW}not configured${RESET}"
fi

OLLAMA_MODEL=$(grep -E "^OLLAMA_MODEL_NAME=" backend/.env 2>/dev/null | cut -d= -f2 || echo "—")
if command -v ollama &>/dev/null; then
    echo -e "  ${DIM}Local LLM  :${RESET}  ${GREEN}Ollama${RESET} ${DIM}(${OLLAMA_MODEL})${RESET}"
else
    echo -e "  ${DIM}Local LLM  :${RESET}  ${YELLOW}Ollama not installed${RESET}"
fi

# Firebase
if [ -f "backend/service-account-key.json" ] || [ -f "service-account-key.json" ]; then
    echo -e "  ${DIM}Firebase   :${RESET}  ${GREEN}connected${RESET}"
else
    echo -e "  ${DIM}Firebase   :${RESET}  ${YELLOW}no service account (local only)${RESET}"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  PRE-FLIGHT CHECKS
# ══════════════════════════════════════════════════════════════════════════════
echo -e "  ${BOLD}🔍 PRE-FLIGHT${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

READY=true

# Check venv
if [ ! -d "backend/venv" ]; then
    echo -e "  ${CROSS}  Backend venv not found — run ${BOLD}./setup.sh${RESET} first"
    READY=false
else
    echo -e "  ${CHECK}  Python venv"
fi

# Check node_modules
if [ ! -d "frontend/node_modules" ]; then
    echo -e "  ${CROSS}  Frontend node_modules not found — run ${BOLD}./setup.sh${RESET} first"
    READY=false
else
    echo -e "  ${CHECK}  Node modules"
fi

# Check .env files
if [ ! -f "backend/.env" ]; then
    echo -e "  ${CROSS}  backend/.env missing — run ${BOLD}./setup.sh${RESET} first"
    READY=false
else
    echo -e "  ${CHECK}  backend/.env"
fi

if [ ! -f "frontend/.env.local" ]; then
    echo -e "  ${WARN}  frontend/.env.local missing ${DIM}(will use defaults)${RESET}"
else
    echo -e "  ${CHECK}  frontend/.env.local"
fi

# Check ports
if lsof -ti:${BACKEND_PORT} &>/dev/null; then
    echo -e "  ${WARN}  Port ${BACKEND_PORT} already in use — ${YELLOW}backend may fail to start${RESET}"
fi
if lsof -ti:3000 &>/dev/null; then
    echo -e "  ${WARN}  Port 3000 already in use — ${YELLOW}frontend may fail to start${RESET}"
fi

echo ""

if [ "$READY" = false ]; then
    echo -e "  ${RED}${BOLD}✖  Pre-flight failed. Run ./setup.sh first.${RESET}"
    echo ""
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
#  LAUNCH
# ══════════════════════════════════════════════════════════════════════════════
echo -e "  ${BOLD}🚀 LAUNCHING${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

# ── Cleanup trap ──────────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo ""
    echo -e "  ${YELLOW}${BOLD}⏹  SHUTTING DOWN${RESET}"
    echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

    if [ -f "$PID_DIR/backend.pid" ]; then
        BPID=$(cat "$PID_DIR/backend.pid")
        if kill -0 "$BPID" 2>/dev/null; then
            kill "$BPID" 2>/dev/null
            wait "$BPID" 2>/dev/null || true
            echo -e "  ${CHECK}  Backend stopped ${DIM}(PID ${BPID})${RESET}"
        fi
        rm -f "$PID_DIR/backend.pid"
    fi

    if [ -f "$PID_DIR/frontend.pid" ]; then
        FPID=$(cat "$PID_DIR/frontend.pid")
        if kill -0 "$FPID" 2>/dev/null; then
            kill "$FPID" 2>/dev/null
            wait "$FPID" 2>/dev/null || true
            echo -e "  ${CHECK}  Frontend stopped ${DIM}(PID ${FPID})${RESET}"
        fi
        rm -f "$PID_DIR/frontend.pid"
    fi

    echo ""
    echo -e "  ${GREEN}${BOLD}TradeClaw shutdown complete.${RESET}"
    echo ""
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── Start Backend ─────────────────────────────────────────────────────────────
echo -e "  ${ARROW}  Starting backend ${DIM}(FastAPI on :${BACKEND_PORT})${RESET}..."

(
    cd "$ROOT_DIR/backend"
    source venv/bin/activate
    python3 -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload 2>&1 | \
        while IFS= read -r line; do
            echo -e "  ${CYAN}[BACKEND]${RESET}  $line"
        done
) &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"

# ── Start Frontend ────────────────────────────────────────────────────────────
echo -e "  ${ARROW}  Starting frontend ${DIM}(Next.js on :3000)${RESET}..."

(
    cd "$ROOT_DIR/frontend"
    npm run dev 2>&1 | \
        while IFS= read -r line; do
            echo -e "  ${MAGENTA}[FRONTEND]${RESET} $line"
        done
) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"

# ── Ready ─────────────────────────────────────────────────────────────────────
sleep 2
echo ""
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}${BOLD}  ✔  TradeClaw is LIVE${RESET}"
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${BOLD}Access Points${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  ${ARROW}  Dashboard   →  ${BOLD}http://localhost:3000${RESET}"
echo -e "  ${ARROW}  API Server  →  ${BOLD}http://localhost:${BACKEND_PORT}${RESET}"
echo -e "  ${ARROW}  API Docs    →  ${BOLD}http://localhost:${BACKEND_PORT}/docs${RESET}"
echo ""
echo -e "  ${DIM}Press ${BOLD}Ctrl+C${RESET}${DIM} to stop all services.${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo ""

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
