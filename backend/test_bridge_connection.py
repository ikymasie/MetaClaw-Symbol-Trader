
import logging
import sys
import os
from mt5_bridge import mt5
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_bridge")

# Load environment variables
load_dotenv()

login = os.getenv("MT5_LOGIN")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

print(f"DEBUG: Password read from .env: {password[0]}...{password[-1]} (length: {len(password)})")

print(f"Python version: {sys.version}")
print("Attempting to use bridge to connect to MT5...")

# Use the Windows path for Wine side
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

print(f"Trying mt5.initialize(path='{terminal_path}')...")
if not mt5.initialize(path=terminal_path):
    print(f"mt5.initialize(path=...) failed: {mt5.last_error()}")
    print("Trying mt5.initialize() without path...")
    if not mt5.initialize():
        print(f"mt5.initialize() also failed: {mt5.last_error()}")
        sys.exit(1)

print("MT5 initialized successfully via bridge!")

if login and password and server:
    print(f"Attempting login to {server} as {login}...")
    # Convert login to int
    if mt5.login(int(login), password=password, server=server):
        print("Login successful!")
        account_info = mt5.account_info()
        if account_info:
            print(f"Account Info: {account_info}")
    else:
        print(f"Login failed, error code: {mt5.last_error()}")
else:
    print("Credentials missing in .env")

mt5.shutdown()
