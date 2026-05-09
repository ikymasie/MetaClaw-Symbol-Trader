import sys
sys.path.append('backend')
from mt5_bridge import mt5

if not mt5.initialize():
    print("Initialize failed, error code =", mt5.last_error())
    quit()

print("Terminal Info:", mt5.terminal_info())
print("Account Info:", mt5.account_info())
print("Symbols Total:", mt5.symbols_total())

# Try to get EURUSD info
import os
from dotenv import load_dotenv
load_dotenv('backend/.env')
suffix = os.getenv('MT5_SYMBOL_SUFFIX', '')
symbol = "EURUSD" + suffix
print(f"Info for {symbol}:", mt5.symbol_info(symbol))

mt5.shutdown()
