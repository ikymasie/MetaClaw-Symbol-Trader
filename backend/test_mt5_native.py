import MetaTrader5 as mt5
import sys
import os

print(f"Python version: {sys.version}")
print(f"CWD: {os.getcwd()}")

if not mt5.initialize(path="C:\\Program Files\\MetaTrader 5\\terminal64.exe"):
    print(f"mt5.initialize(path=...) failed, error code: {mt5.last_error()}")
    if not mt5.initialize():
        print(f"mt5.initialize() also failed, error code: {mt5.last_error()}")
        quit()

print("MT5 initialized successfully!")
terminal_info = mt5.terminal_info()
if terminal_info:
    print(f"Terminal Info: {terminal_info._asdict()}")

# Try login if credentials provided
if len(sys.argv) > 3:
    login = int(sys.argv[1])
    password = sys.argv[2]
    server = sys.argv[3]
    print(f"Attempting login to {server} as {login}...")
    if mt5.login(login, password=password, server=server):
        print("Login successful!")
        account_info = mt5.account_info()
        if account_info:
            print(f"Account Info: {account_info._asdict()}")
    else:
        print(f"Login failed, error code: {mt5.last_error()}")

mt5.shutdown()
