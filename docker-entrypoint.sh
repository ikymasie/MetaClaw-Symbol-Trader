#!/usr/bin/env bash
set -e

echo "===================================================="
echo "          TradeClaw — Boot Sequence                  "
echo "===================================================="
echo ""
echo " MT5 runs natively on the host (Windows / macOS Wine)."
echo " The backend connects via RPyC to MT5_BRIDGE_HOST:MT5_BRIDGE_PORT."
echo ""

# Backend
echo "[1/2] Starting Backend..."
cd /app/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Frontend
echo "[2/2] Starting Frontend..."
cd /app/frontend
HOSTNAME="0.0.0.0" PORT=3000 node server.js &
FRONTEND_PID=$!

echo "===================================================="
echo " TradeClaw is LIVE! "
echo " Frontend: http://localhost:3000"
echo " Backend:  http://localhost:8000"
echo "===================================================="
echo " Note: MT5 bridge must be running on the host."
echo " Start it with: ./start_all.sh (macOS) or"
echo "   python backend/mt5_bridge_server.py  (Windows)"
echo "===================================================="

# Cleanup
cleanup() {
    echo "Stopping TradeClaw..."
    kill -TERM "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

wait -n

echo "A process exited unexpectedly."
cleanup
exit 1
