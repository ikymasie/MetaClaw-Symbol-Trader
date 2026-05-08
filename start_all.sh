#!/usr/bin/env bash

export WINEPREFIX="/Users/ikymasie/Library/Application Support/net.metaquotes.wine.metatrader5"
WINE_BIN="/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
PYTHON_EXE="$WINEPREFIX/drive_c/python/python.exe"
TERMINAL_EXE="C:\\Program Files\\MetaTrader 5\\terminal64.exe"

echo "Killing previous sessions..."
"/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wineserver" -k || true
sleep 2

echo "Updating MT5 configuration..."
python3 backend/update_mt5_config.py

echo "Starting MT5 Terminal in background..."
"$WINE_BIN" "$TERMINAL_EXE" /portable &
echo "Waiting 30 seconds for MT5 to initialize and connect..."
sleep 30

echo "Starting Bridge Server..."
"$WINE_BIN" "$PYTHON_EXE" backend/mt5_bridge_server.py
