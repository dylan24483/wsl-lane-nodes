#!/usr/bin/env python3
"""Lane node daemon — Pi side. Reads sensors, drives outputs, talks to WSL-SRV.

Each Pi node controls one PAIR of lanes (e.g., lanes 21 + 22). Per-lane GPIO
assignments live in LANE_GPIO; gpiozero devices and per-lane callbacks are
instantiated by iterating LANES at startup. Server commands carry a `lane`
field that routes to the right physical GPIO.
"""

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

import os
# SERVER_URL: defaults to localhost for dev (server + node on same Pi),
# overridable via env var for production where the server runs on
# WSL-SRV. Example for production:
#   WSL_LANE_SERVER_URL=ws://192.168.86.36:8765 python3 lane_node.py
SERVER_URL = os.environ.get("WSL_LANE_SERVER_URL", "ws://localhost:8765")
NODE_ID = os.environ.get("WSL_LANE_NODE_ID", "lane-node-dev-pair-21-22")
LANES = [21, 22]

# Bump this whenever a message type's shape changes incompatibly. The
# server compares against its own PROTOCOL_VERSION on HELLO and logs a
# warning on mismatch. v1 = single-lane (LANE_ID); v2 = multi-lane (LANES).
PROTOCOL_VERSION = 2

# Per-lane GPIO assignments. Keep relay_cleanup.py's RELAY_PINS in sync
# with the cycle+power values here.
LANE_GPIO = {
    21: {"foul": 5,  "ball2": 6,  "cycle": 24, "power": 25},
    22: {"foul": 17, "ball2": 22, "cycle": 27, "power": 23},
}

# gpiozero devices instantiated per-lane below. Dicts keyed by lane id.
BALL_DETECT = {}     # foul input — when_pressed fires BALL_EVENT to server
BALL2_DETECT = {}    # 2nd-ball-lamp input — wired, no callback yet (state-only)
PINSETTER_CYCLE = {} # momentary pulse output (relay closes briefly)
PINSETTER_POWER = {} # latched on/off output (relay holds closed until told otherwise)

for lane_id in LANES:
    pins = LANE_GPIO[lane_id]
    BALL_DETECT[lane_id] = Button(pins["foul"], pull_up=False, bounce_time=0.05)
    BALL2_DETECT[lane_id] = Button(pins["ball2"], pull_up=False, bounce_time=0.05)
    PINSETTER_CYCLE[lane_id] = LED(pins["cycle"])
    PINSETTER_POWER[lane_id] = LED(pins["power"])

class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"   # ball was thrown (DIELL ball-detect or sim)
    FOUL_EVENT = "foul_event"   # foul lamp lit (AL-ZARD foul circuit input)
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

def make_foul_callback(lane_id):
    """Bind a per-lane foul callback that captures lane_id in closure.

    The AL-ZARD foul input asserts when the foul lamp circuit lights —
    i.e., the player crossed the foul line. This is NOT the same signal
    as ball-detect; in production, ball-detect comes from the DIELL
    photoelectric sensors at the ball-release point. Until DIELL is
    wired into the bench rig, ball-detect events are simulated via
    the desk simulator's "Trigger Ball" button.
    """
    def on_foul_detected():
        log.info(f"GPIO: foul detected on lane {lane_id}")
        if main_loop and event_queue:
            main_loop.call_soon_threadsafe(
                event_queue.put_nowait,
                encode(Msg.FOUL_EVENT, lane=lane_id)
            )
    return on_foul_detected

for lane_id in LANES:
    BALL_DETECT[lane_id].when_pressed = make_foul_callback(lane_id)

async def heartbeat_loop(ws):
    while True:
        await asyncio.sleep(5)
        await ws.send(encode(Msg.HEARTBEAT, node=NODE_ID))

async def event_sender(ws):
    while True:
        msg = await event_queue.get()
        log.info(f"→ {msg}")
        await ws.send(msg)

async def pulse(lane_id, times, on_ms, off_ms):
    """Drive a lane's cycle relay in a pulse pattern. Always release on exit.

    The try/finally is critical: if a CancelledError is raised mid-pulse
    (e.g. WebSocket drops while we're awaiting asyncio.sleep), the
    .off() in the loop body is skipped, but BCM2711 retains GPIO state
    on lgpio release — the relay would stay closed indefinitely. The
    finally guarantees we drive the line LOW before propagating cancel.
    """
    relay = PINSETTER_CYCLE[lane_id]
    try:
        for _ in range(times):
            relay.on()
            await asyncio.sleep(on_ms / 1000)
            relay.off()
            await asyncio.sleep(off_ms / 1000)
    finally:
        relay.off()

async def command_handler(ws):
    async for raw in ws:
        msg = decode(raw)
        log.info(f"← {raw}")
        cmd_type = msg.get("type")
        lane = msg.get("lane")

        if lane not in LANES:
            log.warning(f"Command for unknown lane {lane}; this node handles {LANES}")
            continue

        if cmd_type == Msg.CYCLE:
            log.info(f"  Pinsetter cycle, lane {lane}")
            await pulse(lane, 1, 150, 0)

        elif cmd_type == Msg.OPEN_LANE:
            bowlers = msg.get("bowlers", [])
            log.info(f"  OPEN LANE {lane} with bowlers: {bowlers}")
            await pulse(lane, 3, 300, 100)  # 3 medium pulses = "first set" sequence

        elif cmd_type == Msg.CLOSE_LANE:
            log.info(f"  CLOSE LANE {lane}")
            await pulse(lane, 1, 1000, 0)   # 1 long pulse = pinsetter to rest

        elif cmd_type == Msg.RESET:
            log.info(f"  RESET pin deck on lane {lane}")
            await pulse(lane, 4, 60, 60)    # 4 rapid blinks = re-rack

        elif cmd_type == Msg.POWER_ON:
            log.info(f"  POWER ON lane {lane}")
            PINSETTER_POWER[lane].on()      # latched — relay holds closed

        elif cmd_type == Msg.POWER_OFF:
            log.info(f"  POWER OFF lane {lane}")
            PINSETTER_POWER[lane].off()     # latched — relay holds open

        else:
            log.warning(f"Unknown command type: {cmd_type}")

def _cleanup_gpio():
    """Drive outputs LOW and release gpiozero devices for every lane.

    Runs on graceful shutdown (SIGTERM / SIGINT / normal exit). Cannot
    run on SIGKILL — that path is covered by systemd's ExecStopPost=
    relay_cleanup.py, which is its own process and runs after the main
    daemon is reaped.
    """
    try:
        for lane_id in LANES:
            PINSETTER_CYCLE[lane_id].off()
            PINSETTER_POWER[lane_id].off()
            PINSETTER_CYCLE[lane_id].close()
            PINSETTER_POWER[lane_id].close()
            BALL_DETECT[lane_id].close()
            BALL2_DETECT[lane_id].close()
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
                    log.info(f"Connected. Sending hello (lanes={LANES}, "
                             f"protocol_version={PROTOCOL_VERSION}).")
                    await ws.send(encode(Msg.HELLO, node=NODE_ID, lanes=LANES,
                                         protocol_version=PROTOCOL_VERSION))
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
