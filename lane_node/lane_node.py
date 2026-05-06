#!/usr/bin/env python3
"""Lane node daemon — Pi side. Reads sensors, drives outputs, talks to WSL-SRV."""

import asyncio
import json
import logging
import signal
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
# PINSETTER_POWER is a *latched* output — held HIGH while the pinsetter
# is meant to be running, dropped LOW to stop it. SIX BOX terminal: the
# "to control desk switch" line per T-VISION drawing T.30.032.
PINSETTER_POWER = LED(23)

class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"
    HEARTBEAT = "heartbeat"
    CYCLE = "cycle"
    OPEN_LANE = "open_lane"
    CLOSE_LANE = "close_lane"
    RESET = "reset"
    POWER_ON = "power_on"
    POWER_OFF = "power_off"

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
    """Drive the relay in a pulse pattern. Always release on exit.

    The try/finally is critical: if a CancelledError is raised mid-pulse
    (e.g. WebSocket drops while we're awaiting asyncio.sleep), the
    .off() in the loop body is skipped, but BCM2711 retains GPIO state
    on lgpio release — the relay would stay closed indefinitely. The
    finally guarantees we drive the line LOW before propagating cancel.
    """
    try:
        for _ in range(times):
            PINSETTER_CYCLE.on()
            await asyncio.sleep(on_ms / 1000)
            PINSETTER_CYCLE.off()
            await asyncio.sleep(off_ms / 1000)
    finally:
        PINSETTER_CYCLE.off()

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

        elif cmd_type == Msg.POWER_ON:
            log.info(f"  POWER ON lane {lane}")
            PINSETTER_POWER.on()      # latched — relay holds closed

        elif cmd_type == Msg.POWER_OFF:
            log.info(f"  POWER OFF lane {lane}")
            PINSETTER_POWER.off()     # latched — relay holds open

        else:
            log.warning(f"Unknown command type: {cmd_type}")

def _cleanup_gpio():
    """Drive outputs LOW and release gpiozero devices.

    Runs on graceful shutdown (SIGTERM / SIGINT / normal exit). Cannot
    run on SIGKILL — that path is covered by systemd's ExecStopPost=
    relay_cleanup.py, which is its own process and runs after the main
    daemon is reaped.
    """
    try:
        PINSETTER_CYCLE.off()
        PINSETTER_POWER.off()
        PINSETTER_CYCLE.close()
        PINSETTER_POWER.close()
        BALL_DETECT.close()
        log.info("GPIO cleanup complete.")
    except Exception as e:
        log.warning(f"GPIO cleanup error: {e}")

async def main():
    global event_queue, main_loop
    main_loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue()

    # SIGTERM is systemd's default stop signal. Without a handler, Python
    # exits without running atexit, and BCM2711 retains the GPIO output
    # state — relays stay stuck closed. Cancelling the main task lets
    # the finally clause below run cleanup.
    main_task = asyncio.current_task()
    main_loop.add_signal_handler(signal.SIGTERM, main_task.cancel)

    try:
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
            except asyncio.CancelledError:
                raise  # let the outer finally run cleanup
            except Exception as e:
                log.warning(f"Connection lost: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
    finally:
        _cleanup_gpio()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down.")
