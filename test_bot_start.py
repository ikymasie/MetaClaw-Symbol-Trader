import requests
import json
import time

res = requests.post("http://localhost:8000/fleet/deploy", json={
    "symbol": "EURUSD",
    "category": "Forex",
    "personality": "lion"
})
data = res.json()
print("Deploy:", data)
bot_id = data.get("bot_id")

res = requests.post(f"http://localhost:8000/fleet/bot/{bot_id}/start")
print("Start:", res.json())

time.sleep(2)
res = requests.get(f"http://localhost:8000/fleet/bot/{bot_id}")
print("Status:", json.dumps(res.json(), indent=2))
