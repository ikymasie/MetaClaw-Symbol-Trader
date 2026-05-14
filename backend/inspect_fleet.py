import urllib.request
import json
try:
    req = urllib.request.urlopen("http://localhost:8000/fleet/status")
    data = json.loads(req.read())
    for b in data.get("bots", []):
        bot_id = b.get("bot_id")
        symbol = b.get("symbol")
        status = b.get("status", {})
        bot_status = status.get("bot_status")
        last_sig = status.get("last_signal")
        msg = status.get("message")
        print(f"[{bot_id}] {symbol} | Status: {bot_status} | Msg: {msg} | Sig: {last_sig}")
except Exception as e:
    print(e)
