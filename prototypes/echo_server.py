#!/usr/bin/env python3
"""Tiny WebSocket echo server for testing the websockets library on Pi."""
import asyncio
from websockets.server import serve

async def echo(websocket):
    async for message in websocket:
        print(f"Got: {message}")
        await websocket.send(f"echo: {message}")

async def main():
    print("Echo server listening on ws://0.0.0.0:8765")
    async with serve(echo, "0.0.0.0", 8765):
        await asyncio.Future()  # run forever

asyncio.run(main())
