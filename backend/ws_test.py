import asyncio
import websockets

async def test():
    uri = "ws://localhost:8000/ws/bot/bot-83619823"
    async with websockets.connect(uri) as ws:
        print("Connected.")
        for _ in range(3):
            msg = await ws.recv()
            print(msg[:200])

asyncio.run(test())
