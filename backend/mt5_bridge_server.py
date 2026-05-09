import sys
import json as _json
import logging
import rpyc
from rpyc.utils.server import ThreadedServer

# Attempt to import MetaTrader5
try:
    import MetaTrader5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("CRITICAL: MetaTrader5 package not found in this Python environment.")
    print("Run: pip install MetaTrader5")

class MT5Service(rpyc.Service):
    """
    Exposes the MetaTrader5 module over RPyC.
    This allows a native macOS Python process to control MT5 running inside Wine.
    """
    def on_connect(self, conn):
        print("Connected to client")

    def on_disconnect(self, conn):
        print("Disconnected from client")

    def exposed_get_mt5(self):
        if not MT5_AVAILABLE:
            raise ImportError("MetaTrader5 package is not installed in the server environment.")
        return MetaTrader5

    def exposed_order_send(self, request_json: str):
        """
        Accept a JSON-serialised trade request and call MetaTrader5.order_send().

        MT5's C extension requires a native Python dict — passing an RPyC netref
        proxy causes retcode=-2 'Unnamed arguments not allowed'. The client
        serialises the request to JSON; we reconstruct a native dict here and
        call MT5 directly, bypassing the proxy issue entirely.
        """
        if not MT5_AVAILABLE:
            raise ImportError("MetaTrader5 not available on this server.")
        request = _json.loads(request_json)
        return MetaTrader5.order_send(request)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print("====================================================")
    print("       TradeClaw — MT5 Wine Bridge Server           ")
    print("====================================================")
    print("Port: 18812")
    
    if not MT5_AVAILABLE:
        print("\nWARNING: MetaTrader5 module not found.")
        print("The server will start, but clients will receive errors when accessing MT5.")
    
    try:
        t = ThreadedServer(
            MT5Service, 
            port=18812, 
            protocol_config={
                'allow_public_attrs': True,
                'sync_request_timeout': 300
            }
        )
        print("\nBridge Server is LIVE and listening...")
        print("Press Ctrl+C to stop.")
        t.start()
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)
