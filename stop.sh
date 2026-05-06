#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw — Graceful Shutdown
#  Stops both backend and frontend processes started by start.sh.
#  Usage:  ./stop.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'
CHECK="${GREEN}✔${RESET}"
CROSS="${RED}✖${RESET}"
WARN="${YELLOW}⚠${RESET}"

# ── Resolve project root ──────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$ROOT_DIR/.pids"

echo ""
echo -e "  ${CYAN}${BOLD}TradeClaw${RESET} ${DIM}— Shutdown${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"

STOPPED=0

# ── Kill by PID file ──────────────────────────────────────────────────────────
kill_by_pidfile() {
    local name="$1"
    local pidfile="$2"

    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            # Wait up to 5 seconds for graceful exit
            for i in $(seq 1 10); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 0.5
            done
            # Force kill if still running
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            echo -e "  ${CHECK}  ${name} stopped ${DIM}(PID ${pid})${RESET}"
            STOPPED=$((STOPPED + 1))
        else
            echo -e "  ${DIM}  ${name} — PID ${pid} already exited${RESET}"
        fi
        rm -f "$pidfile"
    fi
}

kill_by_pidfile "Backend " "$PID_DIR/backend.pid"
kill_by_pidfile "Frontend" "$PID_DIR/frontend.pid"

# ── Fallback: kill by port ────────────────────────────────────────────────────
BACKEND_PORT=$(grep -E "^PORT=" "$ROOT_DIR/backend/.env" 2>/dev/null | cut -d= -f2 || echo "8000")
BACKEND_PORT="${BACKEND_PORT:-8000}"

kill_by_port() {
    local name="$1"
    local port="$2"

    local pids
    pids=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill 2>/dev/null || true
        echo -e "  ${CHECK}  ${name} on port ${port} killed ${DIM}(fallback)${RESET}"
        STOPPED=$((STOPPED + 1))
    fi
}

# Only try port-based kill if PID files didn't work
if [ "$STOPPED" -eq 0 ]; then
    echo -e "  ${DIM}  No PID files found — scanning ports...${RESET}"
    kill_by_port "Backend " "$BACKEND_PORT"
    kill_by_port "Frontend" "3000"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$STOPPED" -gt 0 ]; then
    echo -e "  ${GREEN}${BOLD}✔  TradeClaw stopped.${RESET}"
else
    echo -e "  ${DIM}  No running TradeClaw processes found.${RESET}"
fi
echo ""
