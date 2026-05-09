import json as _json
import logging
import os
import sys
import time

logger = logging.getLogger("tradeclaw.mt5_bridge")

# If we're on Linux/macOS, we use RPyC to connect to the Windows Python running in Wine
if os.name != 'nt':
    try:
        import rpyc

        class _MT5RPyCWrapper:
            """
            Thin wrapper around the RPyC-proxied MetaTrader5 module.

            Intercepts order_send() to work around a fundamental RPyC limitation:
            MT5's order_send() is a C extension with a positional-only signature.
            When called through RPyC, the dict argument arrives as a netref proxy,
            not a native Python dict, causing retcode=-2 'Unnamed arguments not allowed'.

            Fix: serialise the request to JSON on the client, call the server's
            exposed_order_send() helper which reconstructs a native dict and calls
            MetaTrader5.order_send() directly in the Windows Python process.

            All other attributes are forwarded transparently to the remote module.
            """

            def __init__(self, conn, remote_mt5):
                self._conn = conn
                self._remote = remote_mt5

            def order_send(self, request: dict):
                return self._conn.root.order_send(_json.dumps(request))

            def __getattr__(self, name: str):
                return getattr(self._remote, name)

        def get_mt5_bridge():
            """Attempt to connect to the RPyC bridge server."""
            for i in range(15):
                try:
                    conn = rpyc.connect("localhost", 18812, config={
                        'allow_public_attrs': True,
                        'sync_request_timeout': 60
                    })
                    logger.info("Connected to MT5 Bridge Server via RPyC")
                    return _MT5RPyCWrapper(conn, conn.root.get_mt5())
                except Exception:
                    if i % 5 == 0:
                        logger.info("Waiting for MT5 Bridge Server...")
                    time.sleep(2)
            return None

        mt5 = get_mt5_bridge()

        if mt5 is None:
            logger.error("Failed to connect to MT5 Bridge Server after retries.")
            class MockMT5:
                def __getattr__(self, name):
                    def method(*args, **kwargs):
                        raise RuntimeError("MT5 Bridge Server not reachable. Check docker logs.")
                    return method
            mt5 = MockMT5()

    except ImportError:
        logger.warning("rpyc not found, cannot use MT5 bridge")
        class MockMT5:
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    raise ImportError("rpyc is required for the MT5 Linux bridge.")
                return method
        mt5 = MockMT5()
else:
    try:
        import MetaTrader5 as mt5
        logger.info("Using native MetaTrader5 package on Windows")
    except ImportError:
        logger.error("MetaTrader5 package not installed.")
        sys.exit(1)

# Export the mt5 object
__all__ = ["mt5"]
