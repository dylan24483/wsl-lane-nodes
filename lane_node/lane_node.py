#!/usr/bin/env python3
"""Lane node daemon — Pi side. Reads sensors, drives outputs, talks to WSL-SRV.

Each Pi node controls one PAIR of lanes (e.g., lanes 21 + 22). The pair is
selected via WSL_LANES (e.g. WSL_LANES="23,24"; default 21,22). Per-lane GPIO
assignments live in LANE_GPIO; gpiozero devices and per-lane callbacks are
instantiated by iterating LANES at startup. Server commands carry a `lane`
field that routes to the right physical GPIO.
"""

import asyncio
import hmac
import json
import logging
import signal
import time

from gpiozero import Button, LED
from websockets.asyncio.client import connect

# pin_detect: numpy pin-classification (DualDeckDetector → 10-bit mask per deck).
# camera: owns the T-Camera capture handle + the calibrated detector + the empty
# reference, and maps deck→lane. detect_current_pins() below uses it in camera
# mode; manual mode never touches it. Both import without cv2/gpiozero present
# (cv2 is lazy in camera.py), so this file still loads on a camera-less bench.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import pin_detect
import camera

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('lane_node')

import os
# SERVER_URL: defaults to localhost for dev (server + node on same Pi),
# overridable via env var for production where the server runs on
# WSL-SRV. Example for production (the live WSL-SRV IP is tracked in ONE
# authoritative place: docs/manual_src/20_operations.md § 20.4):
#   WSL_LANE_SERVER_URL=ws://<WSL-SRV-IP>:8765 python3 lane_node.py
SERVER_URL = os.environ.get("WSL_LANE_SERVER_URL", "ws://localhost:8765")
NODE_ID = os.environ.get("WSL_LANE_NODE_ID", "lane-node-dev-pair-21-22")

def _parse_lanes(raw):
    """Parse WSL_LANES (e.g. "23,24") into a lane-id list.

    Unset/blank → default [21, 22] (the pilot pair) so existing nodes are
    byte-for-byte unchanged. A MALFORMED value is a hard startup error, NOT
    a silent fallback: falling back to a default pair on a provisioning typo
    would actuate the WRONG physical machines' relays. Dead node > wrong
    machine. (Each lane must also have a LANE_GPIO entry — validated below.)
    """
    raw = (raw or "").strip()
    if not raw:
        return [21, 22]
    try:
        lanes = [int(p) for p in raw.split(",") if p.strip()]
    except ValueError:
        raise SystemExit(f"WSL_LANES={raw!r}: not a comma-separated list of lane numbers")
    if not lanes:
        raise SystemExit(f"WSL_LANES={raw!r}: no lanes parsed")
    if len(set(lanes)) != len(lanes):
        raise SystemExit(f"WSL_LANES={raw!r}: duplicate lane ids")
    return lanes

LANES = _parse_lanes(os.environ.get("WSL_LANES"))
# Shared auth token, matching the server's LANE_NODE_TOKEN. SYMMETRIC
# (review #51): when the server has LANE_NODE_TOKEN set, it rejects any HELLO
# without the same value; when THIS NODE has it set, command_handler rejects
# any server command frame (CYCLE/OPEN/CLOSE/RESET/POWER_*) that does not
# carry the same token — the HELLO-only auth protected the server but left
# any host impersonating WSL-SRV:8765 with direct relay actuation. When
# unset on both sides, behavior is unchanged (unauthenticated, bench compat).
# Set it in the systemd unit (Environment=LANE_NODE_TOKEN=...) at provisioning
# — the SAME value on the server and every Pi.
LANE_NODE_TOKEN = os.environ.get("LANE_NODE_TOKEN", "").strip()

# How DIELL ball-detect events flow into scoring:
#   camera   — DIELL fires BALL_EVENT with pin_mask from detect_current_pins().
#              Auto-scoring. Use ONLY when T-Camera + pin_detect.PIN_SPOTS is
#              calibrated against real frames — otherwise you score bogus
#              synthetic pin masks on real balls.
#   manual   — DIELL fires BALL_EVENT with pin_mask=None. Server records the
#              ball happened but does NOT apply a pin count; desk operator
#              enters pins via POST /api/lane/<N>/score. This is the safe
#              default for Phase 8a cutover until T-Camera lands.
#   disabled — DIELL events logged on the Pi but no message sent to server.
#              For bench-testing without scoring side effects.
SCORING_MODE = os.environ.get("WSL_LANE_SCORING_MODE", "manual").lower()
if SCORING_MODE not in ("camera", "manual", "disabled"):
    log.warning(f"Unknown WSL_LANE_SCORING_MODE={SCORING_MODE!r}; falling back to 'manual'")
    SCORING_MODE = "manual"

# Bump this whenever a message type's shape changes incompatibly. The
# server compares against its own PROTOCOL_VERSION on HELLO and logs a
# warning on mismatch. v1 = single-lane (LANE_ID); v2 = multi-lane (LANES).
PROTOCOL_VERSION = 2

# Per-lane GPIO assignments. Keep relay_cleanup.py's RELAY_PINS in sync
# with the cycle+power values here. DIELL pins are read-only inputs so
# they don't need to be mirrored to relay_cleanup.
LANE_GPIO = {
    21: {"foul": 5,  "ball2": 6,  "cycle": 24, "power": 25,
         "diell_left": 13, "diell_right": 16},
    22: {"foul": 17, "ball2": 22, "cycle": 27, "power": 23,
         "diell_left": 19, "diell_right": 20},
}

# Every configured lane must have a GPIO map. Hard error, not a fallback —
# same rationale as _parse_lanes(): never guess which physical machine to
# drive. (Provisioning a new pair = add its LANE_GPIO entry + set WSL_LANES.)
_unmapped_lanes = [l for l in LANES if l not in LANE_GPIO]
if _unmapped_lanes:
    raise SystemExit(f"WSL_LANES includes lane(s) with no LANE_GPIO entry: "
                     f"{_unmapped_lanes} (known: {sorted(LANE_GPIO)})")

# Hardware-watchdog kick pin — board-level (one NE555 per PCB / per pair),
# NOT per-lane, so it lives outside LANE_GPIO. The NE555 monostable drops
# the AEDIKO relay-coil return (all relays open) unless it's pulsed at least
# every ~11s. watchdog_kick_loop() pets it at ~1Hz. relay_cleanup.py must
# also force this LOW on SIGKILL (see the note there) — a retained-HIGH kick
# pin would hold the watchdog alive and defeat it.
WATCHDOG_KICK_PIN = 12

# gpiozero devices instantiated per-lane below. Dicts keyed by lane id.
# Naming note: BALL_DETECT is the foul-lamp input — kept this name for
# backward-compat with relay_cleanup.py and prototypes/. The actual ball
# is detected by DIELL_LEFT/DIELL_RIGHT (photoelectric beams at the pin deck).
BALL_DETECT = {}     # foul-lamp input — when_pressed fires FOUL_EVENT to server
BALL2_DETECT = {}    # 2nd-ball-lamp input — wired, no callback yet (state-only)
DIELL_LEFT = {}      # DIELL left photoelectric — when_released fires BALL_EVENT
DIELL_RIGHT = {}     # DIELL right photoelectric — when_released fires BALL_EVENT
PINSETTER_CYCLE = {} # momentary pulse output (relay closes briefly)
PINSETTER_POWER = {} # latched on/off output (relay holds closed until told otherwise)

for lane_id in LANES:
    pins = LANE_GPIO[lane_id]
    BALL_DETECT[lane_id] = Button(pins["foul"], pull_up=False, bounce_time=0.05)
    BALL2_DETECT[lane_id] = Button(pins["ball2"], pull_up=False, bounce_time=0.05)
    DIELL_LEFT[lane_id] = Button(pins["diell_left"], pull_up=False, bounce_time=0.02)
    DIELL_RIGHT[lane_id] = Button(pins["diell_right"], pull_up=False, bounce_time=0.02)
    PINSETTER_CYCLE[lane_id] = LED(pins["cycle"])
    PINSETTER_POWER[lane_id] = LED(pins["power"])

# Board-level watchdog kick output (one per PCB, not per-lane). Pulsed by
# watchdog_kick_loop(); driven LOW + closed in _cleanup_gpio() on shutdown.
WATCHDOG_KICK = LED(WATCHDOG_KICK_PIN)

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

# Pin detection (camera-backed). One PairCamera per pair — a single T-Camera
# sees BOTH decks. Constructed in main() when SCORING_MODE == "camera"; stays
# None otherwise (manual/disabled never touch the camera).
_PAIR_CAMERA = None

# Bench fallback: when camera mode is on but no real camera/empty-ref is present,
# WSL_LANE_CAMERA_STUB=1 rotates synthetic masks (mimics the server's old
# PIN_MASK_CYCLE) so the bench behaves as before. Default OFF — without it,
# "camera mode but no camera" yields None → the daemon emits awaiting_manual
# (safe: a real ball never records bogus auto-scored pins).
_CAMERA_STUB = os.environ.get("WSL_LANE_CAMERA_STUB", "0") == "1"
_STUB_PIN_MASKS = [0b0000011111, 0, 0, 0b0001111111, 0b0000001111, 0]
_stub_counter = {lane_id: 0 for lane_id in LANES}

def detect_current_pins(lane_id: int):
    """Real standing-pin mask for the lane (10-bit, 1 = standing), or None.

    None means "no usable pin data" (camera not ready, or a capture failure) —
    the caller then emits the ball as awaiting_manual so the desk scores it,
    rather than recording bogus pins. BLOCKS on cv2 capture, so callers run it
    via asyncio.to_thread, never directly on the event loop.
    """
    if _PAIR_CAMERA is not None and _PAIR_CAMERA.ready:
        return _PAIR_CAMERA.detect_lane(lane_id)   # int, or None on capture fail
    if _CAMERA_STUB:
        n = _stub_counter[lane_id]
        _stub_counter[lane_id] = n + 1
        m = _STUB_PIN_MASKS[n % len(_STUB_PIN_MASKS)]
        log.info(f"lane {lane_id}: CAMERA STUB pin_mask=0x{m:03x}")
        return m
    return None

event_queue = None
main_loop = None

def make_foul_callback(lane_id):
    """Bind a per-lane foul callback that captures lane_id in closure.

    The AL-ZARD/DONGKER foul input asserts when the foul lamp circuit
    lights — i.e., the player crossed the foul line. This is NOT the same
    signal as ball-detect; ball-detect comes from DIELL via
    make_ball_detect_callback below.
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


async def _settle_capture_emit(lane_id):
    """camera mode: wait the settle window, grab+detect off-loop, emit BALL_EVENT.

    Scheduled from the DIELL callback (camera mode). The pins are still rocking
    when DIELL fires, so we sleep camera.SETTLE_S first, THEN capture — at which
    point the ball has reached the deck and the pins have stopped, but the
    (existing) pinsetter hasn't swept yet. cv2 capture blocks, so it runs in a
    worker thread via asyncio.to_thread to keep the event loop (and the watchdog
    kick) responsive.

    Emits a real pin_mask when detection succeeds; otherwise emits
    awaiting_manual=True so the desk scores it — a capture/detector failure must
    never auto-score bogus pins on a real ball.

    ⚠️ TIMING COUPLING (fine for the scoring pilot; revisit at Track B cutover):
    the server sends the pinsetter CYCLE in reply to BALL_EVENT, so delaying
    BALL_EVENT by SETTLE_S also delays that CYCLE reply by SETTLE_S. In the
    Phase-8a scoring pilot this is harmless — the EXISTING controller cycles the
    machine on its own ball-detect; our CYCLE relay isn't the live machine
    driver. When the Track-B Pi-controller (cycle_control_8270) drives the
    machine, the cycle MUST run on cam timing independent of camera capture —
    decouple "ball happened / cycle now" from "here's the score" then.
    """
    try:
        try:
            await asyncio.sleep(camera.SETTLE_S)
            pin_mask = await asyncio.to_thread(detect_current_pins, lane_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"lane {lane_id}: settle/capture error: {e}; -> awaiting_manual")
            pin_mask = None

        if pin_mask is None:
            log.info(f"lane {lane_id}: camera yielded no mask -> awaiting_manual (desk score)")
            msg = encode(Msg.BALL_EVENT, lane=lane_id, pin_mask=None, awaiting_manual=True)
        else:
            log.info(f"lane {lane_id}: camera pin_mask=0x{pin_mask:03x} "
                     f"(standing={[p for p in range(1,11) if pin_mask & (1<<(p-1))]})")
            msg = encode(Msg.BALL_EVENT, lane=lane_id, pin_mask=pin_mask)
            if pin_mask == 0:
                # All pins down: the upcoming post-sweep window is the
                # known-empty moment — schedule the (throttled) empty-ref
                # self-check (R2-14). Fire-and-forget; it guards itself.
                try:
                    asyncio.get_running_loop().create_task(
                        _maybe_camera_selfcheck(lane_id))
                except Exception:
                    pass

        if event_queue:
            await event_queue.put(msg)
    finally:
        # One emit (or failure) per scheduled capture — re-arm the DIELL
        # trigger for the next real ball.
        _capture_in_flight[lane_id] = False


# Per-lane ball-detect lockout. The left and right DIELL beams trigger
# milliseconds apart for one ball passing through; without a lockout we'd
# emit two BALL_EVENT messages per real ball. The 0.2s default is well above
# the inter-sensor delay (a 20mph ball traverses the kickback in ~5ms) but
# well below typical between-balls interval (>1 second).
#
# ============================ BALL-DEDUP STORY ============================
# (one comment block, repeated in each layer — review 2026-06-27 finding 39:
# three uncoordinated knobs is a cutover hazard. Same block lives in
# server/lane_node_server.py and firmware/rp2040/config.h.)
#
#   WSL_LANE_BALL_LOCKOUT_S (THIS knob, default 0.2 s) is the AUTHORITATIVE
#   Track-A ball-dedup window — the ONLY knob that masks phantom balls
#   (scatter/sweep re-breaking a beam seconds after the real ball; the 82-70
#   itself masks ball-detect for its full ~8-10 s cycle). ⚠️ AT CUTOVER SET
#   WSL_LANE_BALL_LOCKOUT_S=8 (bench-confirm against the real cycle time).
#   Default stays 0.2 (= L/R pair coalesce only) so bench rigs can fire
#   rapid simulated balls. Camera mode is ADDITIONALLY guarded by
#   _capture_in_flight below, regardless of this value.
#
#   LANE_BALL_DEDUP_S (server, default 0 = off) is NOT a substitute: it is a
#   delivery-dedup BACKSTOP for paths this lockout cannot see (the node's
#   transactional re-queue redelivering an already-emitted event after a WS
#   drop). Set it too at cutover, but the cycle mask lives HERE.
#
#   BALL_LOCKOUT_MS (RP2040 firmware, 300 ms) is Track-B only: it coalesces
#   the L/R beam pair feeding the cycle FSM and has no effect on this path.
#   At Track-B/scoring unification the FSM's ball-accept decision must
#   become the single source of truth (finding 39 fix).
#
# The effective windows are logged at startup on both node and server —
# check those two lines at cutover instead of trusting env-var memory.
# ==========================================================================
_ball_detect_lockout: dict = {lane_id: 0.0 for lane_id in LANES}
try:
    BALL_DETECT_LOCKOUT_S = float(os.environ.get("WSL_LANE_BALL_LOCKOUT_S", "0.2"))
except ValueError:
    log.warning(f"Bad WSL_LANE_BALL_LOCKOUT_S="
                f"{os.environ.get('WSL_LANE_BALL_LOCKOUT_S')!r}; using 0.2")
    BALL_DETECT_LOCKOUT_S = 0.2

# Camera mode: True while a _settle_capture_emit task is in flight for the
# lane. DIELL retriggers during the settle/capture window (pin scatter, the
# existing controller's sweep) are ignored instead of scheduling a SECOND
# capture that would emit a phantom BALL_EVENT for the same ball. Set in the
# GPIO callback thread before scheduling; cleared in the task's finally.
_capture_in_flight: dict = {lane_id: False for lane_id in LANES}


def make_ball_detect_callback(lane_id):
    """Bind a per-lane ball-detect callback that captures lane_id in closure.

    DIELL LSC/AN-2C6J sensors are NPN open-collector with an external
    10kΩ pull-up to +12V (replacing T-VISION's internal pull-up after
    Phase 8 retires T-VISION). Signal behavior:

      Idle (beam unbroken):  signal = 12V → DONGKER input asserted →
                             Pi GPIO reads HIGH
      Beam broken (ball):    NPN sinks to GND → DONGKER deasserted →
                             Pi GPIO reads LOW

    So a ball-detect event is a FALLING edge on the Pi pin — we bind to
    `when_released` rather than `when_pressed`. The signal sense is
    INVERTED relative to the foul/2nd-ball lamp inputs, where ASSERTING
    the AC lamp drives the Pi pin HIGH (and we bind `when_pressed`).
    """
    def on_ball_detected():
        now = time.time()
        if now < _ball_detect_lockout[lane_id]:
            return  # within lockout window — already emitted for this ball
        _ball_detect_lockout[lane_id] = now + BALL_DETECT_LOCKOUT_S

        if SCORING_MODE == "disabled":
            log.info(f"GPIO: ball detected on lane {lane_id} (mode=disabled, no emit)")
            return

        # camera mode: the pins are still rocking when DIELL fires, so DON'T
        # capture now. Schedule a settle-then-capture-then-emit coroutine on the
        # event loop (the blocking cv2 capture runs off-loop via to_thread).
        # That coroutine emits awaiting_manual if detection yields no mask.
        # While one is in flight for this lane, IGNORE retriggers — pin scatter
        # / sweep motion re-breaking a beam must not schedule a second capture
        # (= a phantom BALL_EVENT for the same ball). A real second ball can't
        # arrive inside the settle+capture window.
        if SCORING_MODE == "camera":
            if _capture_in_flight[lane_id]:
                log.info(f"GPIO: lane {lane_id} DIELL retrigger while capture "
                         f"in flight (pin scatter?) — ignored")
                return
            log.info(f"GPIO: ball detected on lane {lane_id}, mode=camera; "
                     f"settling {camera.SETTLE_S}s before capture")
            if main_loop:
                _capture_in_flight[lane_id] = True
                asyncio.run_coroutine_threadsafe(
                    _settle_capture_emit(lane_id), main_loop)
            return

        # manual mode: include NO pin_mask — server treats as "ball happened,
        # await /api/lane/N/score" instead of recording with bogus stub data.
        log.info(f"GPIO: ball detected on lane {lane_id}, "
                 f"mode=manual (awaiting desk score)")
        msg = encode(Msg.BALL_EVENT, lane=lane_id, pin_mask=None,
                     awaiting_manual=True)
        if main_loop and event_queue:
            main_loop.call_soon_threadsafe(event_queue.put_nowait, msg)
    return on_ball_detected


for lane_id in LANES:
    cb = make_ball_detect_callback(lane_id)
    DIELL_LEFT[lane_id].when_released = cb
    DIELL_RIGHT[lane_id].when_released = cb

async def heartbeat_loop(ws):
    while True:
        await asyncio.sleep(5)
        await ws.send(encode(Msg.HEARTBEAT, node=NODE_ID))

async def watchdog_kick_loop():
    """Pet the NE555 hardware watchdog on the interposer PCB at ~1Hz.

    Deliberately runs OUTSIDE the WS-connection scope (contrast
    heartbeat_loop, which lives inside `async with connect(...)`). The kick
    must continue as long as THIS PROCESS's event loop is alive, regardless
    of server connectivity — a server outage must NOT drop the pinsetter.
    Only daemon death or an event-loop hang stops the kicks, which is exactly
    when we want the relays to safe-open (~11s after the last kick).

    50ms pulse is comfortably longer than the NE555 trigger needs; the 950ms
    gap keeps us well inside the ~11s timeout with large margin. Cleanup
    (drive LOW + close) is centralized in _cleanup_gpio() via main()'s finally.
    """
    while True:
        WATCHDOG_KICK.on()
        await asyncio.sleep(0.05)
        WATCHDOG_KICK.off()
        await asyncio.sleep(0.95)

async def event_sender(ws):
    """Drain event_queue → ws. Delivery is transactional: if send fails (or
    we're cancelled mid-send during a reconnect), the in-hand message is
    re-queued so the NEXT connection delivers it instead of silently
    dropping a real ball/foul. Re-queue appends, so ordering across a drop
    can shift if multiple events were queued — acceptable; losing the event
    outright is the failure that matters. (If the socket died after the
    frame went out, the server may see a duplicate — its cycle-window
    dedupe is the guard on that side.)
    """
    while True:
        msg = await event_queue.get()
        log.info(f"→ {msg}")
        try:
            await ws.send(msg)
        except BaseException:           # incl. CancelledError — requeue, then re-raise
            event_queue.put_nowait(msg)
            raise

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

# Per-lane command concurrency. The default (False) keeps the original serial
# ORDERING: pulse commands run strictly in arrival order through ONE shared
# queue+worker, so a 1s CLOSE pulse on lane A still delays a CYCLE for lane B.
# With it True, each lane gets its own queue+worker so lanes run concurrently
# while a single lane's pulses stay strictly ordered (never overlapping — two
# pulses on one pinsetter at once is a hardware hazard). Bench-gated: True
# changes the timing of real relay actuation, so flip it only after a bench
# pass on the pair rig.
#
# In BOTH modes the websocket recv loop only ever ENQUEUES pulses — it never
# awaits one inline — so a POWER_ON/POWER_OFF frame is read and executed the
# moment it arrives. (Review #7: the old serial mode awaited the pulse inside
# the `async for`, so a buffered POWER_OFF wasn't even READ until the pulse —
# and any backlog — finished; the "POWER never waits" fast-path was inert.)
CONCURRENT_LANE_COMMANDS = os.environ.get("WSL_CONCURRENT_LANE_CMDS", "0").lower() in ("1", "true", "yes")

# Bounded command queues (review #31). A runaway/buggy sender must not be able
# to bank minutes of future relay actuation: when a queue is full the NEW
# command is REJECTED with a loud log. Reject-new (vs drop-oldest) because it
# is atomic on asyncio.Queue and never reorders already-accepted commands —
# and a full queue means >= CMD_QUEUE_MAX pulses are already backlogged, a
# fault condition in which executing MORE motion is the wrong direction.
# POWER_ON/POWER_OFF never queue (executed inline in command_handler), so the
# safety path can never be rejected. 8 pulses ≈ 10s worst-case backlog/worker.
CMD_QUEUE_MAX = 8
_lane_cmd_queues = {}    # queue key -> asyncio.Queue; key = lane id (concurrent) or None (shared serial)
_lane_cmd_workers = {}   # queue key -> worker Task; cancelled + queues flushed on connection drop


async def _execute_command(cmd_type, lane, msg):
    """Run one pinsetter command. Pulses are awaited (slow); POWER on/off are
    instant latched relays."""
    if cmd_type == Msg.CYCLE:
        log.info(f"  Pinsetter cycle, lane {lane}")
        await pulse(lane, 1, 150, 0)
    elif cmd_type == Msg.OPEN_LANE:
        log.info(f"  OPEN LANE {lane} with bowlers: {msg.get('bowlers', [])}")
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


async def _lane_worker(key, queue):
    """Serially drain one command queue — keeps ordering within the queue
    (per-lane in concurrent mode; global in serial mode) while the recv loop
    stays free to read new frames (POWER preemption). Cancelled + respawned
    lazily across connection drops (see _flush_lane_cmd_queues)."""
    while True:
        cmd_type, lane_id, msg = await queue.get()
        try:
            await _execute_command(cmd_type, lane_id, msg)
        except Exception as e:
            log.error(f"command {cmd_type} on lane {lane_id} failed: {e}")
        finally:
            queue.task_done()


async def _flush_lane_cmd_queues(reason):
    """Cancel command workers + drop queued pulse commands (review #31).

    Called when the server connection drops: a dead socket's backlog must not
    keep actuating relays for minutes afterward. Cancelling the worker also
    cancels an in-flight pulse mid-pattern — pulse()'s finally drives the relay
    LOW, matching the pre-queue serial behavior where cancelling
    command_handler cancelled the awaited pulse. Queues are kept (reused next
    connection); workers are respawned lazily on the next command."""
    workers = [w for w in _lane_cmd_workers.values() if not w.done()]
    _lane_cmd_workers.clear()
    for w in workers:
        w.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
    dropped = 0
    for q in _lane_cmd_queues.values():
        while True:
            try:
                cmd_type, lane_id, _msg = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            q.task_done()
            dropped += 1
            log.warning(f"  dropped queued {cmd_type} for lane {lane_id} ({reason})")
    if dropped:
        log.warning(f"{dropped} queued command(s) dropped: {reason}")


async def command_handler(ws):
    async for raw in ws:
        # One malformed frame (invalid JSON / valid-JSON non-dict) must not
        # tear down the whole command+scoring connection for the 5s backoff
        # (review #50) — tolerate it and keep reading, mirroring how
        # rp2040_link.feed_line tolerates unparseable serial lines.
        try:
            msg = decode(raw)
            cmd_type = msg.get("type")
            lane = msg.get("lane")
        except Exception as e:
            log.warning(f"malformed server frame ignored ({e!r}): {raw[:200]!r}")
            continue
        # Never log the shared token (frames carry it when auth is on).
        if isinstance(msg, dict) and "token" in msg:
            log.info("← %s", json.dumps({k: ("***" if k == "token" else v)
                                         for k, v in msg.items()}))
        else:
            log.info(f"← {raw}")

        # Symmetric auth (review #51): the HELLO token authenticates this node
        # TO the server only; nothing authenticated the server to us, so an
        # impersonated WSL-SRV:8765 got direct relay actuation. When
        # LANE_NODE_TOKEN is set, every command frame must carry the same
        # token (the server stamps it in encode()) or it is REJECTED loudly.
        # Unset = unchanged (unauthenticated bench compat, both sides).
        if LANE_NODE_TOKEN:
            supplied = msg.get("token") or ""
            if not (isinstance(supplied, str)
                    and hmac.compare_digest(supplied, LANE_NODE_TOKEN)):
                log.error(f"REJECTED server command frame: bad or missing token "
                          f"(type={cmd_type!r} lane={lane!r} from "
                          f"{getattr(ws, 'remote_address', '?')}). This node has "
                          f"LANE_NODE_TOKEN set; the server must be started with "
                          f"the SAME LANE_NODE_TOKEN so it stamps command frames.")
                continue

        if lane not in LANES:
            log.warning(f"Command for unknown lane {lane}; this node handles {LANES}")
            continue

        # POWER on/off is an instant, safety-relevant latched relay — it is
        # NEVER queued: executed the moment the frame is read. And because the
        # recv loop below only enqueues pulses (never awaits one), the frame
        # IS read immediately even mid-pulse — review #7.
        if cmd_type in (Msg.POWER_ON, Msg.POWER_OFF):
            await _execute_command(cmd_type, lane, msg)
            continue

        # Pulse commands go through a bounded queue + worker so this loop
        # keeps READING frames while a pulse runs. Serial (default): one
        # shared queue/worker = original global pulse ordering. Concurrent:
        # one queue/worker per lane.
        key = lane if CONCURRENT_LANE_COMMANDS else None
        q = _lane_cmd_queues.get(key)
        if q is None:
            q = asyncio.Queue(maxsize=CMD_QUEUE_MAX)
            _lane_cmd_queues[key] = q
        w = _lane_cmd_workers.get(key)
        if w is None or w.done():
            _lane_cmd_workers[key] = asyncio.ensure_future(_lane_worker(key, q))
        try:
            q.put_nowait((cmd_type, lane, msg))
        except asyncio.QueueFull:
            log.error(f"command queue full ({CMD_QUEUE_MAX} pending) — REJECTING "
                      f"{cmd_type} for lane {lane} (runaway sender? a backlog "
                      f"must not bank relay motion)")

def _cleanup_gpio():
    """Drive outputs LOW and release gpiozero devices for every lane.

    Runs on graceful shutdown (SIGTERM / SIGINT / normal exit). Cannot
    run on SIGKILL — that path is covered by systemd's ExecStopPost=
    relay_cleanup.py, which is its own process and runs after the main
    daemon is reaped.

    FAIL-SAFE ORDERING: stop the watchdog kick and drive every relay output
    LOW FIRST, before anything that can block or fail — the camera close can
    wait on a wedged cv2 capture, and waiting ~11s for the NE555 to trip is
    the backstop, not the plan. Each step runs in its own try/except so one
    failure can never skip the de-energize of the rest.
    """
    def _try(what, fn):
        try:
            fn()
        except Exception as e:
            log.warning(f"GPIO cleanup: {what} failed: {e}")

    # 1. Stop kicking the watchdog → even if everything below fails, the
    #    NE555 trips and the relays safe-open ~11s later.
    _try("watchdog kick off", WATCHDOG_KICK.off)
    # 2. Drive every relay output LOW immediately (don't wait for the NE555).
    for lane_id in LANES:
        _try(f"L{lane_id} cycle off", PINSETTER_CYCLE[lane_id].off)
        _try(f"L{lane_id} power off", PINSETTER_POWER[lane_id].off)
    # 3. Only now release devices and close the camera (the one step that
    #    can block — relays are already down if it does).
    _try("watchdog kick close", WATCHDOG_KICK.close)
    for lane_id in LANES:
        _try(f"L{lane_id} cycle close", PINSETTER_CYCLE[lane_id].close)
        _try(f"L{lane_id} power close", PINSETTER_POWER[lane_id].close)
        _try(f"L{lane_id} foul close", BALL_DETECT[lane_id].close)
        _try(f"L{lane_id} ball2 close", BALL2_DETECT[lane_id].close)
        _try(f"L{lane_id} diell-L close", DIELL_LEFT[lane_id].close)
        _try(f"L{lane_id} diell-R close", DIELL_RIGHT[lane_id].close)
    if _PAIR_CAMERA is not None:
        _try("camera close", _PAIR_CAMERA.close)
    log.info("GPIO cleanup complete.")

async def connection_manager():
    """Maintain the WS connection to the server, reconnecting on drop.

    All server commands + scoring events flow through here. Kept SEPARATE
    from watchdog_kick_loop() on purpose: if the server is unreachable or
    this stalls in reconnect-backoff, the watchdog keeps getting kicked
    (the daemon is alive), so the pinsetter stays powered. We only drop
    relays on actual daemon death / event-loop hang — never on a mere
    server outage.
    """
    while True:
        try:
            log.info(f"Connecting to {SERVER_URL} ...")
            async with connect(SERVER_URL) as ws:
                log.info(f"Connected. Sending hello (lanes={LANES}, "
                         f"protocol_version={PROTOCOL_VERSION}, "
                         f"auth={'token' if LANE_NODE_TOKEN else 'none'}).")
                hello_fields = dict(node=NODE_ID, lanes=LANES,
                                    protocol_version=PROTOCOL_VERSION)
                if LANE_NODE_TOKEN:
                    # Only include the field when set, so the HELLO shape is
                    # byte-identical to before in unauthenticated bench mode.
                    hello_fields["token"] = LANE_NODE_TOKEN
                await ws.send(encode(Msg.HELLO, **hello_fields))
                await _run_connection(ws)
        except asyncio.CancelledError:
            raise  # let main()'s finally run cleanup
        except Exception as e:
            log.warning(f"Connection lost: {e}. Retrying in 5s...")
            await asyncio.sleep(5)


async def _run_connection(ws):
    """Run the three per-connection loops until the FIRST of them stops,
    then cancel + reap the others before returning to the reconnect loop.

    The old `await asyncio.gather(...)` waited for ALL THREE: when the
    socket died, command_handler ended but heartbeat_loop/event_sender kept
    running as orphans into the next connection — every reconnect stacked
    another event_sender, and an orphan would steal the next queued ball
    event and burn it on a dead socket. FIRST_COMPLETED + cancel guarantees
    no task survives past its own connection. (asyncio.wait, not TaskGroup:
    the Pi fleet may run < Python 3.11.)
    """
    tasks = [asyncio.create_task(heartbeat_loop(ws)),
             asyncio.create_task(event_sender(ws)),
             asyncio.create_task(command_handler(ws))]
    try:
        done, _pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Runs on FIRST_COMPLETED *and* on cancellation of this coroutine
        # (SIGTERM path). Reap everything so no orphan survives and no
        # "exception was never retrieved" noise hits the journal.
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A dead connection's command backlog must not keep actuating relays
        # (review #31): cancel workers (an in-flight pulse's finally drives
        # the relay LOW) and drop anything still queued.
        await _flush_lane_cmd_queues("connection dropped")
    for t in done:
        if not t.cancelled() and t.exception() is not None:
            raise t.exception()
    # A loop returned cleanly (command_handler's async-for ended on a
    # server-side close): surface it as a drop so connection_manager's
    # existing log + 5s backoff path handles it like any other outage.
    raise ConnectionError("websocket closed by server")


# ---------------------------------------------------------------------------
# R2-14 (Codex round-2, 2026-07-21): camera self-checks IN the production
# daemon path. camera.frame_health / self_check_empty existed but nothing
# scheduled them — a dead/frozen/dark/blurred camera only surfaced as balls
# quietly falling back to awaiting_manual. A periodic health poll + a
# throttled post-strike empty-reference check now emit typed diag events
# ('camera_health' / 'camera_ref_drift') through the same diag_events pipe
# (JSONL outbox -> :8766 machine_events). ALL of it: off the scoring path
# (asyncio.to_thread, skipped while a scoring capture is in flight),
# alert-only, bounded, env-killable, never raises.
# ---------------------------------------------------------------------------
from diag_events import DiagWriter as _DiagWriter, make_event as _make_event

CAM_HEALTH_ENV = "WSL_CAM_HEALTH"                # default ON in camera mode
CAM_HEALTH_POLL_ENV = "WSL_CAM_HEALTH_POLL_S"    # poll cadence (default 300 s)
CAM_SELFCHECK_MIN_ENV = "WSL_CAM_SELFCHECK_MIN_S"  # min gap between empty-ref checks
_FALSEY_ENV = ("0", "false", "no", "off", "")

_DIAG_WRITER = None          # started in main() (camera mode only)
_cam_selfcheck_last = 0.0    # monotonic time of the last empty-ref self-check
_cam_health_warned = False


def _cam_env_on(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in _FALSEY_ENV


def _cam_env_float(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return float(default)


def _diag_emit(severity, event_type, code=None, detail=None):
    """Enqueue one diag event (never raises, no-op without a writer)."""
    w = _DIAG_WRITER
    if w is None:
        return
    try:
        w.emit(_make_event(min(LANES), severity, event_type, code=code,
                           detail=detail))
    except Exception:
        log.debug("camera diag emit swallowed", exc_info=True)


def _classify_camera_health(h):
    """Map a frame_health dict onto the catalog's dead/frozen/dark/blur
    classes for the event code."""
    if not h.get('grabbed'):
        return 'dead'
    if h.get('stale'):
        return 'frozen'
    reasons = " ".join(h.get('reasons') or []).lower()
    if 'dark' in reasons or 'bright' in reasons or 'mean' in reasons:
        return 'dark'
    if 'focus' in reasons or 'blur' in reasons or 'variance' in reasons:
        return 'blur'
    return 'unhealthy'


async def camera_health_loop():
    """Periodic camera health poll (camera mode only). One 'camera_health'
    warn per unhealthy episode; recovery emits 'recovered' info. Runs the
    blocking capture in a worker thread and skips any poll that would race
    a scoring capture."""
    global _cam_health_warned
    if SCORING_MODE != "camera" or not _cam_env_on(CAM_HEALTH_ENV):
        return
    poll_s = max(10.0, _cam_env_float(CAM_HEALTH_POLL_ENV, 300.0))
    log.info(f"camera health: polling every {poll_s:.0f}s "
             f"(disable: {CAM_HEALTH_ENV}=0)")
    while True:
        await asyncio.sleep(poll_s)
        try:
            cam = _PAIR_CAMERA
            if cam is None:
                if not _cam_health_warned:
                    _cam_health_warned = True
                    _diag_emit("warn", "camera_health", code="dead",
                               detail={"reason": "camera mode but no camera "
                                                 "object (init failed)"})
                continue
            if any(_capture_in_flight.values()):
                continue        # never race a scoring capture
            h = await asyncio.to_thread(cam.frame_health)
            ok = bool(h.get('ok'))
            if not ok and not _cam_health_warned:
                _cam_health_warned = True
                _diag_emit("warn", "camera_health",
                           code=_classify_camera_health(h),
                           detail={k: h.get(k) for k in
                                   ("mean", "variance", "focus", "grabbed",
                                    "stale", "reasons")})
            elif ok and _cam_health_warned:
                _cam_health_warned = False
                _diag_emit("info", "recovered", code="camera_health")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("camera_health_loop swallowed", exc_info=True)


async def _maybe_camera_selfcheck(lane_id):
    """Throttled empty-reference self-check after an all-pins-down camera
    read (the deck is empty between the sweep finishing and the fresh rack
    spotting — the closest thing Track A has to a known-empty window; the
    check itself re-verifies emptiness against the reference and is flag-only
    unless WSL_CAM_AUTO_RECAL is deliberately enabled)."""
    global _cam_selfcheck_last
    try:
        min_s = _cam_env_float(CAM_SELFCHECK_MIN_ENV, 3600.0)
        now = time.monotonic()
        if now - _cam_selfcheck_last < min_s:
            return
        _cam_selfcheck_last = now
        await asyncio.sleep(4.0)          # sweep-finished, pre-spot window
        cam = _PAIR_CAMERA
        if cam is None or any(_capture_in_flight.values()):
            return
        v = await asyncio.to_thread(cam.self_check_empty)
        if not v.get('grabbed') or v.get('stale'):
            _diag_emit("warn", "camera_health",
                       code='dead' if not v.get('grabbed') else 'frozen',
                       detail={"during": "self_check_empty",
                               "reason": v.get('reason')})
        elif v.get('flagged'):
            _diag_emit("warn", "camera_ref_drift", code="empty_ref",
                       detail={k: v.get(k) for k in
                               ("max_divergence", "max_spot_divergence",
                                "empty_confirmed", "recalibrated", "reason")})
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("_maybe_camera_selfcheck swallowed", exc_info=True)


def _init_camera():
    """Construct the PairCamera in camera mode. Failure is non-fatal: we log and
    leave _PAIR_CAMERA None, so detect_current_pins() returns None and every ball
    falls back to awaiting_manual (desk scoring) — the lane still runs."""
    global _PAIR_CAMERA
    if SCORING_MODE != "camera":
        return
    try:
        _PAIR_CAMERA = camera.PairCamera(
            deck_to_lane={dk: ln for dk, ln in pin_detect.DECK_TO_LANE.items()
                          if ln in LANES})
        if _PAIR_CAMERA.ready:
            log.info(f"Camera ready for lanes {_PAIR_CAMERA.lanes()} "
                     f"(settle={camera.SETTLE_S}s).")
        else:
            log.warning("Camera mode but detector NOT ready (no empty ref / cv2). "
                        "Balls will fall back to manual desk scoring until fixed. "
                        "Capture an empty ref: python lane_node/camera.py --capture-empty")
    except Exception as e:
        log.warning(f"Camera init failed ({e}); manual fallback for all balls.")
        _PAIR_CAMERA = None


async def main():
    global event_queue, main_loop, _DIAG_WRITER
    main_loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue()
    _init_camera()
    # Camera-health diag pipe (R2-14): JSONL always, HTTP outbox when
    # WSL_DIAG_SERVER_URL is provisioned (systemd env file). Camera mode
    # only — manual/disabled nodes have nothing to report here.
    if SCORING_MODE == "camera" and _cam_env_on(CAM_HEALTH_ENV):
        try:
            _DIAG_WRITER = _DiagWriter()
            _DIAG_WRITER.start()
        except Exception:
            log.warning("camera diag writer failed to start (health events "
                        "will be log-only)", exc_info=True)
            _DIAG_WRITER = None

    # SIGTERM is systemd's default stop signal. Without a handler, Python
    # exits without running atexit, and BCM2711 retains the GPIO output
    # state — relays stay stuck closed. Cancelling the main task lets
    # the finally clause below run cleanup.
    main_task = asyncio.current_task()
    main_loop.add_signal_handler(signal.SIGTERM, main_task.cancel)

    log.info(f"Hardware watchdog: kicking GPIO {WATCHDOG_KICK_PIN} @ ~1Hz "
             f"(runs independent of the server connection).")

    # Cutover checklist line (finding 39): the AUTHORITATIVE ball-dedup window.
    # 0.2 s = bench default (L/R pair coalesce only — phantom-ball masking OFF);
    # production cutover wants WSL_LANE_BALL_LOCKOUT_S=8. See the BALL-DEDUP
    # STORY block above _ball_detect_lockout.
    if BALL_DETECT_LOCKOUT_S < 1.0:
        log.warning(f"Ball-dedup: WSL_LANE_BALL_LOCKOUT_S={BALL_DETECT_LOCKOUT_S}s "
                    f"(bench default — masks the L/R pair only, NOT scatter "
                    f"phantom balls; set 8 at cutover)")
    else:
        log.info(f"Ball-dedup: WSL_LANE_BALL_LOCKOUT_S={BALL_DETECT_LOCKOUT_S}s "
                 f"(authoritative Track-A window)")

    try:
        # The watchdog kick and the server connection run concurrently and
        # independently. SIGTERM cancels main_task → gather cancels both →
        # finally runs _cleanup_gpio(). If either coroutine raises, gather
        # propagates and we still clean up (relays safe-open).
        await asyncio.gather(
            watchdog_kick_loop(),
            connection_manager(),
            camera_health_loop(),      # R2-14: no-op unless camera mode + on
        )
    finally:
        _cleanup_gpio()
        if _DIAG_WRITER is not None:
            try:
                _DIAG_WRITER.stop()
            except Exception:
                pass

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down.")
