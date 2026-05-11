import sys
import os
sys.path.append(os.path.abspath('backend'))
from symbol_service import symbol_service, to_mt5_symbol
print("EURUSD ->", to_mt5_symbol("EURUSD"))
print("BTCUSD ->", to_mt5_symbol("BTCUSD"))
