#!/usr/bin/env python3
"""Lane node daemon — runs on each Raspberry Pi controlling one VDB pair.

Reads sensor inputs (ball-detect, foul, pin-state) via GPIO and drives
outputs (pinsetter cycle, reset). Communicates with WSL-SRV via a
persistent WebSocket connection.

For prototype: button on GPIO 17 = ball-detect simulator.
                LED on GPIO 27 = pinsetter cycle relay simulator.
"""

import asyncio
import json
import logging
import time

from gpiozero import Button, LED
from websockets.asyncio.client import connect

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('lane_node')

# ============================================================
# CONFIG
# ============================================================
SERVER_URL = "ws://localhost:8765"   # change to WSL-SRV IP later
NODE_ID = "lane-node-dev-22"
LANE_ID = 22

# ============================================================
# HARDWARE
# ============================================================
BALL_DETECT = Button(17, pull_up=True, bounce_time=0.05)
PINSETTER_CYCLE = LED(27)

# ============================================================
# PROTOCOL
# ============================================================
class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"
    HEARTBEAT = "heartbeat"
    CYCLE = "cycle"

def encode(msg_type, **fields):
    return json.dumps({"type": msg_type, "ts": time.time(), **fields})

def decode(raw):
    return json.loads(raw)

# ============================================================
# GPIO ↔ ASYNCIO BRIDGE
# ============================================================
# gpiozero callbacks run in their own thread, NOT the asyncio loop.
# We bridge by scheduling a put_nowait on the asyncio loop from the
# gpiozero thread via call_soon_threadsafe.

event_queue = None
main_loop = None

def on_ball_detected():
    """gpiozero callback. Runs in gpiozero's thread."""
    log.info(f"GPIO: ball detected on lane {LANE_ID}")
    if main_loop and event_queue:
        main_loop.call_soon_threadsafe(
            event_queue.put_nowait,
            encode(Msg.BALL_EVENT, lane=LANE_ID)
        )

BALL_DETECT.when_pressed = on_ball_detected

# ============================================================
# ASYNCIO TASKS
# ============================================================
async def heartbeat_loop(ws):
    """Send heartbeat every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        await ws.send(encode(Msg.HEARTBEAT, node=NODE_ID))

async def event_sender(ws):
    """Drain the queue and send each event over the WebSocket."""
    while True:
        msg = await event_queue.get()
        log.info(f"→ {msg}")
        await ws.send(msg)

async def command_handler(ws):
    """Receive commands from the server and drive GPIO outputs."""
    async for raw in ws:
        msg = decode(raw)
        log.info(f"← {raw}")
        if msg.get("type") == Msg.CYCLE:
            log.info(f"Pulsing cycle relay for lane {msg.get('lane')}")
            PINSETTER_CYCLE.on()
            await asyncio.sleep(0.15)
            PINSETTER_CYCLE.off()

async def main():
    global event_queue, main_loop
    main_loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue()

    while True:
        try:
            log.info(f"Connecting to {SERVER_URL} ...")
            async with connect(SERVER_URL) as ws:
                log.info(f"Connected. Sending hello.")
                await ws.send(encode(Msg.HELLO, node=NODE_ID, lane=LANE_ID))

                await asyncio.gather(
                    heartbeat_loop(ws),
                    event_sender(ws),
                    command_handler(ws),
                )
        except Exception as e:
            log.warning(f"Connection lost: {e}. Retrying in 5s...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
