import sys
sys.path.append('backend')
from mt5_bridge import mt5
print("Initialized:", mt5.initialize())
print("Terminal:", mt5.terminal_info())
print("Last error:", mt5.last_error())
