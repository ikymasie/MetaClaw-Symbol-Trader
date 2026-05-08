#!/usr/bin/env bash
set -e

echo "===================================================="
echo "          TradeClaw — Boot Sequence                 "
echo "===================================================="

# ── 1. Virtual display (MT5 terminal requires a display even headless) ────
echo "[1/6] Starting virtual display (Xvfb)..."
Xvfb :99 -screen 0 1024x768x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

# ── 2. Install MT5 if missing ───────────────────────────────────────────
MT5_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_EXE" ]; then
    echo "[2/6] MetaTrader 5 not found. Installing into Wine prefix..."
    wineboot --init
    sleep 5
    wine /tmp/mt5setup.exe /auto
    echo "MT5 installation triggered. Waiting for files..."
    for i in $(seq 1 60); do
        [ -f "$MT5_EXE" ] && break
        sleep 2
    done
else
    echo "[2/6] MetaTrader 5 already installed."
fi

# ── 3. Install Windows Python for MT5 Linux Bridge ──────────────────────
WINE_PY_DIR="$WINEPREFIX/drive_c/python"
WINE_PYTHON="$WINE_PY_DIR/python.exe"
if [ ! -f "$WINE_PYTHON" ]; then
    echo "[3/6] Installing Windows Python inside Wine for MT5 bridge..."
    mkdir -p "$WINE_PY_DIR"
    # Use Python 3.11 embeddable (fastest way to get a working Windows Python in Wine)
    wget -q https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip -O /tmp/py.zip
    unzip -q /tmp/py.zip -d "$WINE_PY_DIR"
    rm /tmp/py.zip
    
    # Enable site-packages in embeddable python (required for pip-installed packages)
    # The ._pth file controls what is imported. We need to uncomment 'import site'
    sed -i 's/#import site/import site/' "$WINE_PY_DIR/python311._pth"
    
    # Install pip using get-pip
    echo "Bootstrapping pip in Wine Python..."
    wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py
    wine "$WINE_PYTHON" /tmp/get-pip.py --no-warn-script-location
    
    # Install MetaTrader5 and rpyc (rpyc is the underlying transport for mt5linux)
    echo "Installing MetaTrader5 and rpyc in Wine Python..."
    wine "$WINE_PYTHON" -m pip install --no-warn-script-location MetaTrader5 rpyc
else
    echo "[3/6] Windows Python already installed in Wine."
fi

# ── 4. Start MT5 terminal ─────────────────────────────────────────────────
echo "[4/6] Starting MT5 terminal..."
CONFIG_OUT="/app/mt5/config.ini"
sed \
  -e "s/%MT5_LOGIN%/${MT5_LOGIN:-0}/" \
  -e "s/%MT5_PASSWORD%/${MT5_PASSWORD:-}/" \
  -e "s/%MT5_SERVER%/${MT5_SERVER:-}/" \
  /app/mt5/config.ini.template > "$CONFIG_OUT"

DISPLAY=:99 wine "$MT5_EXE" /portable "/config:$CONFIG_OUT" &
MT5_PID=$!

# ── 5. Start MT5 Linux Bridge Server ──────────────────────────────────────
echo "[5/6] Starting MT5 Linux Bridge Server..."
# We run a simple rpyc server inside Wine that exposes the MetaTrader5 module.
# This is exactly what mt5linux connects to.
# We use a custom script to ensure it's running.
BRIDGE_SCRIPT="
import MetaTrader5
import rpyc
from rpyc.utils.server import ThreadedServer

class MT5Service(rpyc.Service):
    def on_connect(self, conn): pass
    def on_disconnect(self, conn): pass
    def exposed_get_mt5(self):
        return MetaTrader5

if __name__ == '__main__':
    print('MT5 Bridge Server listening on port 18812...')
    t = ThreadedServer(MT5Service, port=18812, protocol_config={'allow_public_attrs': True})
    t.start()
"
echo "$BRIDGE_SCRIPT" > /tmp/mt5_bridge_server.py
DISPLAY=:99 wine "$WINE_PYTHON" /tmp/mt5_bridge_server.py &
BRIDGE_PID=$!

# Wait for bridge to be ready
sleep 5

# ── 6. Backend & Frontend ─────────────────────────────────────────────────
echo "[6/6] Starting Backend & Frontend..."

# Start Backend
cd /app/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Frontend
cd /app/frontend
HOSTNAME="0.0.0.0" PORT=3000 node server.js &
FRONTEND_PID=$!

echo "===================================================="
echo " TradeClaw is LIVE! "
echo " Frontend: http://localhost:3000"
echo " Backend:  http://localhost:8000"
echo "===================================================="

# ── Cleanup ───────────────────────────────────────────────────────────────
cleanup() {
    echo "Stopping TradeClaw..."
    kill -TERM "$BACKEND_PID" "$FRONTEND_PID" "$BRIDGE_PID" "$MT5_PID" "$XVFB_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

wait -n

echo "A process exited unexpectedly."
cleanup
exit 1
