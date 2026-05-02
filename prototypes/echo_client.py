#!/usr/bin/env python3
"""Connect to local echo server and exchange a few messages."""
import asyncio
from websockets.client import connect

async def main():
    async with connect("ws://localhost:8765") as ws:
        for msg in ["hello", "ball_detected lane=22", '{"event":"foul","lane":22}']:
            await ws.send(msg)
            response = await ws.recv()
            print(f"sent: {msg!r}")
            print(f"got:  {response!r}\n")

asyncio.run(main())
