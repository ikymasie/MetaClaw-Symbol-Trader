#!/usr/bin/env bash
# Substitute env vars into MT5 config, then start the terminal.
set -e

CONFIG_OUT="/app/mt5/config.ini"
TEMPLATE="/app/mt5/config.ini.template"

sed \
  -e "s/%MT5_LOGIN%/${MT5_LOGIN:-0}/" \
  -e "s/%MT5_PASSWORD%/${MT5_PASSWORD:-}/" \
  -e "s/%MT5_SERVER%/${MT5_SERVER:-}/" \
  "$TEMPLATE" > "$CONFIG_OUT"

exec xvfb-run --server-args="-screen 0 1024x768x24 -ac" \
    wine "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe" \
    /portable "/config:$CONFIG_OUT"
