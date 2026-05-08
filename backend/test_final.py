
import logging
import os
import sys
from mt5_bridge import mt5
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_final")

# Load environment variables
load_dotenv()

login = os.getenv("MT5_LOGIN")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

print(f"DEBUG: Login={login}, Server={server}")
print(f"DEBUG: Password length: {len(password) if password else 0}")

print("Attempting mt5.initialize()...")
# NOTE: We do NOT pass path here because the terminal is already running in the same Wine session.
if not mt5.initialize():
    print(f"mt5.initialize() failed: {mt5.last_error()}")
    # Try with path just in case
    terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
    print(f"Trying with path: {terminal_path}")
    if not mt5.initialize(path=terminal_path):
        print(f"mt5.initialize(path=...) also failed: {mt5.last_error()}")
        sys.exit(1)

print("MT5 initialized successfully!")

if login and password and server:
    print(f"Attempting login to {server} as {login}...")
    # Ensure login is int
    if mt5.login(int(login), password=password, server=server):
        print("LOGIN SUCCESSFUL!")
        info = mt5.account_info()
        if info:
            print(f"Account Info: Login={info.login}, Balance={info.balance}, Equity={info.equity}, Currency={info.currency}")
        
        terminal_info = mt5.terminal_info()
        if terminal_info:
            print(f"Terminal Info: Connected={terminal_info.connected}, Trade Allowed={terminal_info.trade_allowed}")
    else:
        print(f"LOGIN FAILED: {mt5.last_error()}")
else:
    print("Missing credentials in .env")

mt5.shutdown()
