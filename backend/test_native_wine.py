
import MetaTrader5 as mt5
import sys

print(f"MT5 Python version: {sys.version}")
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
print(f"Attempting mt5.initialize(path='{terminal_path}')...")

if not mt5.initialize(path=terminal_path):
    print(f"FAILED: {mt5.last_error()}")
    print("Attempting mt5.initialize() without path...")
    if not mt5.initialize():
        print(f"FAILED AGAIN: {mt5.last_error()}")
        sys.exit(1)

print("SUCCESS: MT5 initialized native inside Wine!")
print(f"Terminal Info: {mt5.terminal_info()}")
mt5.shutdown()
