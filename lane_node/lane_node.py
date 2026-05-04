#!/usr/bin/env python3
"""Lane node daemon — Pi side. Reads sensors, drives outputs, talks to WSL-SRV."""

import asyncio
import json
import logging
import time

from gpiozero import Button, LED
from websockets.asyncio.client import connect

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('lane_node')

SERVER_URL = "ws://localhost:8765"
NODE_ID = "lane-node-dev-22"
LANE_ID = 22

BALL_DETECT = Button(17, pull_up=False, bounce_time=0.05)
PINSETTER_CYCLE = LED(27)

class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"
    HEARTBEAT = "heartbeat"
    CYCLE = "cycle"
    OPEN_LANE = "open_lane"
    CLOSE_LANE = "close_lane"
    RESET = "reset"

def encode(t, **f): return json.dumps({"type": t, "ts": time.time(), **f})
def decode(r): return json.loads(r)

event_queue = None
main_loop = None

def on_ball_detected():
    log.info(f"GPIO: ball detected on lane {LANE_ID}")
    if main_loop and event_queue:
        main_loop.call_soon_threadsafe(
            event_queue.put_nowait,
            encode(Msg.BALL_EVENT, lane=LANE_ID)
        )

BALL_DETECT.when_pressed = on_ball_detected

async def heartbeat_loop(ws):
    while True:
        await asyncio.sleep(5)
        await ws.send(encode(Msg.HEARTBEAT, node=NODE_ID))

async def event_sender(ws):
    while True:
        msg = await event_queue.get()
        log.info(f"→ {msg}")
        await ws.send(msg)

async def pulse(times, on_ms, off_ms):
    """Drive the LED in a custom blink pattern."""
    for _ in range(times):
        PINSETTER_CYCLE.on()
        await asyncio.sleep(on_ms / 1000)
        PINSETTER_CYCLE.off()
        await asyncio.sleep(off_ms / 1000)

async def command_handler(ws):
    async for raw in ws:
        msg = decode(raw)
        log.info(f"← {raw}")
        cmd_type = msg.get("type")
        lane = msg.get("lane")

        if cmd_type == Msg.CYCLE:
            log.info(f"  Pinsetter cycle, lane {lane}")
            await pulse(1, 150, 0)

        elif cmd_type == Msg.OPEN_LANE:
            bowlers = msg.get("bowlers", [])
            log.info(f"  OPEN LANE {lane} with bowlers: {bowlers}")
            await pulse(3, 300, 100)  # 3 medium pulses = "first set" sequence

        elif cmd_type == Msg.CLOSE_LANE:
            log.info(f"  CLOSE LANE {lane}")
            await pulse(1, 1000, 0)   # 1 long pulse = pinsetter to rest

        elif cmd_type == Msg.RESET:
            log.info(f"  RESET pin deck on lane {lane}")
            await pulse(4, 60, 60)    # 4 rapid blinks = re-rack

        else:
            log.warning(f"Unknown command type: {cmd_type}")

async def main():
    global event_queue, main_loop
    main_loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue()

    while True:
        try:
            log.info(f"Connecting to {SERVER_URL} ...")
            async with connect(SERVER_URL) as ws:
                log.info("Connected. Sending hello.")
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
