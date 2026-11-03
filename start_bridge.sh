#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw — Bridge Launcher
#  Starts the RPyC bridge server independently (no backend/frontend).
#  Usage:  ./start_bridge.sh [PORT]
#          PORT defaults to 18812 (from MT5_BRIDGE_PORT in backend/.env)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'
CHECK="${GREEN}✔${RESET}"
CROSS="${RED}✖${RESET}"
ARROW="${CYAN}➜${RESET}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PID_DIR="$ROOT_DIR/.pids"
mkdir -p "$PID_DIR"

# ── Resolve port ──────────────────────────────────────────────────────────────
if [ $# -ge 1 ]; then
    BRIDGE_PORT="$1"
else
    BRIDGE_PORT=$(grep -E "^MT5_BRIDGE_PORT=" backend/.env 2>/dev/null | cut -d= -f2 || echo "18812")
    BRIDGE_PORT="${BRIDGE_PORT:-18812}"
fi

# ── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}🌉 TradeClaw — Bridge Launcher${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  ${DIM}Port       :${RESET}  ${BRIDGE_PORT}"
echo ""

# ── Check if already running ─────────────────────────────────────────────────
if lsof -ti:"${BRIDGE_PORT}" &>/dev/null; then
    echo -e "  ${YELLOW}⚠  Port ${BRIDGE_PORT} is already in use${RESET}"
    echo -e "  ${DIM}Bridge may already be running. Use ./stop.sh to kill it first.${RESET}"
    echo ""
    exit 1
fi

# ── Determine platform ───────────────────────────────────────────────────────
PLATFORM="$(uname -s)"
case "$PLATFORM" in
    Darwin)
        # macOS — runs bridge inside the Wine prefix
        WINEPREFIX_DIR="${WINEPREFIX:-${HOME}/Library/Application Support/net.metaquotes.wine.metatrader5}"
        WINE_BIN="${WINE_BIN:-/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine}"
        PYTHON_EXE="$WINEPREFIX_DIR/drive_c/python/python.exe"

        if [ ! -f "$WINE_BIN" ]; then
            echo -e "  ${CROSS}  Wine binary not found at: ${WINE_BIN}"
            echo -e "  ${DIM}Set WINE_BIN env var to the correct path.${RESET}"
            echo ""
            exit 1
        fi

        if [ ! -f "$PYTHON_EXE" ]; then
            echo -e "  ${CROSS}  Python not found in Wine prefix at: ${PYTHON_EXE}"
            echo -e "  ${DIM}Run ./mac_mt5_bridge_setup.sh first to install it.${RESET}"
            echo ""
            exit 1
        fi

        export WINEPREFIX="$WINEPREFIX_DIR"

        echo -e "  ${ARROW}  Starting bridge via Wine…"
        echo -e "  ${DIM}  WINEPREFIX: ${WINEPREFIX_DIR}${RESET}"
        echo -e "  ${DIM}  Command: ${WINE_BIN} ${PYTHON_EXE} backend/mt5_bridge_server.py${RESET}"
        echo ""

        MT5_BRIDGE_PORT="$BRIDGE_PORT" \
            "$WINE_BIN" "$PYTHON_EXE" "backend/mt5_bridge_server.py" &
        BRIDGE_PID=$!
        ;;
    Linux)
        # Linux (Docker/production) — bridge runs on Windows host, not here
        echo -e "  ${YELLOW}⚠  Bridge must run on the Windows host (or Wine).${RESET}"
        echo -e "  ${DIM}On the MT5 host, run: python backend/mt5_bridge_server.py${RESET}"
        echo -e "  ${DIM}Set MT5_BRIDGE_HOST in backend/.env to reach it.${RESET}"
        echo ""
        exit 1
        ;;
    *)
        # Windows (native)
        echo -e "  ${ARROW}  Starting bridge natively…"
        MT5_BRIDGE_PORT="$BRIDGE_PORT" \
            python "backend/mt5_bridge_server.py" &
        BRIDGE_PID=$!
        ;;
esac

# ── Write PID ────────────────────────────────────────────────────────────────
echo "$BRIDGE_PID" > "$PID_DIR/bridge.pid"

# ── Cleanup trap ─────────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo -e "  ${YELLOW}⏹  Stopping bridge (PID ${BRIDGE_PID})…${RESET}"
    kill "$BRIDGE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
    rm -f "$PID_DIR/bridge.pid"
    echo -e "  ${CHECK}  Bridge stopped${RESET}"
    echo ""
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Ready ────────────────────────────────────────────────────────────────────
sleep 1
echo ""
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}${BOLD}  ✔  Bridge server running${RESET}"
echo -e "  ${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${BOLD}Connection Info${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo -e "  ${ARROW}  Host   →  ${BOLD}localhost${RESET}"
echo -e "  ${ARROW}  Port   →  ${BOLD}${BRIDGE_PORT}${RESET}"
echo -e "  ${ARROW}  PID    →  ${BOLD}${BRIDGE_PID}${RESET}"
echo ""
echo -e "  ${DIM}Press ${BOLD}Ctrl+C${RESET}${DIM} to stop the bridge.${RESET}"
echo -e "  ${DIM}──────────────────────────────────────────${RESET}"
echo ""

# Wait for the bridge process
wait "$BRIDGE_PID" 2>/dev/null || true
