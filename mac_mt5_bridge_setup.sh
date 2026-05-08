#!/usr/bin/env bash

# TradeClaw — Mac MT5 Bridge Setup (No Docker)
# This script installs Python + MetaTrader5 + RPyC inside your MT5 Wine prefix.

set -e

WINE_BIN="/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
WINE_PREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5"
WINE_DRIVE_C="$WINE_PREFIX/drive_c"
WINE_PY_DIR="$WINE_DRIVE_C/python"
WINE_PYTHON_EXE="$WINE_PY_DIR/python.exe"

echo "===================================================="
echo "      TradeClaw — Mac Native MT5 Bridge Setup       "
echo "===================================================="

# Check if MT5 App exists
if [ ! -d "/Applications/MetaTrader 5.app" ]; then
    echo "ERROR: /Applications/MetaTrader 5.app not found."
    exit 1
fi

# Check if Wine binary exists
if [ ! -f "$WINE_BIN" ]; then
    echo "ERROR: Wine binary not found at $WINE_BIN"
    exit 1
fi

export WINEPREFIX="$WINE_PREFIX"

# 1. Install Windows Python if missing
if [ ! -f "$WINE_PYTHON_EXE" ]; then
    echo "[1/3] Downloading Windows Python (embeddable) into Wine..."
    mkdir -p "$WINE_PY_DIR"
    curl -sL https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip -o /tmp/py_win.zip
    unzip -q /tmp/py_win.zip -d "$WINE_PY_DIR"
    rm /tmp/py_win.zip
    
    echo "Configuring Python site-packages..."
    # Enable site-packages in the embeddable build
    sed -i '' 's/#import site/import site/' "$WINE_PY_DIR/python311._pth"
    
    echo "Bootstrapping pip..."
    curl -sL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    "$WINE_BIN" "$WINE_PYTHON_EXE" /tmp/get-pip.py --no-warn-script-location
else
    echo "[1/3] Windows Python already installed in Wine."
fi

# 2. Install dependencies
echo "[2/3] Installing MetaTrader5 and RPyC inside Wine..."
"$WINE_BIN" "$WINE_PYTHON_EXE" -m pip install --no-warn-script-location MetaTrader5 rpyc

# 3. Final Check
echo "[3/3] Verifying MetaTrader5 connection..."
# Just a quick check to see if it imports
"$WINE_BIN" "$WINE_PYTHON_EXE" -c "import MetaTrader5; print('MT5 Python API successfully loaded inside Wine!')"

echo "===================================================="
echo " Setup Complete! "
echo " To start the bridge, run: "
echo " \"$WINE_BIN\" \"$WINE_PYTHON_EXE\" backend/mt5_bridge_server.py "
echo "===================================================="
