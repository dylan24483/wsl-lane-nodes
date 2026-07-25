#!/usr/bin/env python3
"""Lane node daemon — Pi side. Reads sensors, drives outputs, talks to WSL-SRV.

Each Pi node controls one PAIR of lanes (e.g., lanes 21 + 22). The pair is
selected via mandatory WSL_LANES (e.g. WSL_LANES="23,24"). Per-lane GPIO
assignments live in LANE_GPIO; gpiozero devices and per-lane callbacks are
instantiated by iterating LANES at startup. Server commands carry a `lane`
field that routes to the right physical GPIO.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hmac
import json
import logging
import math
import signal
import threading
import time
import uuid

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
from reliable_transport import (
    DurableTransport, default_transport_path)
from strict_json import loads as strict_json_loads

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


def _required_node_id(raw):
    """Require the stable fleet identity used by routing and diagnostics."""
    value = (raw or "").strip()
    lowered = value.lower()
    if (
        not value
        or len(value) > 128
        or any(
            not char.isascii()
            or not (char.isalnum() or char in "._:-")
            for char in value
        )
        or lowered == "dev"
        or lowered.startswith("dev-")
        or lowered.endswith("-dev")
        or "-dev-" in lowered
    ):
        raise SystemExit(
            "WSL_LANE_NODE_ID must be an explicit stable production node id")
    return value


NODE_ID = _required_node_id(os.environ.get("WSL_LANE_NODE_ID"))


def _canonical_diag_source(node_id, raw):
    value = (raw or "").strip()
    if value and value != node_id:
        raise SystemExit(
            "WSL_DIAG_SOURCE_ID must exactly equal WSL_LANE_NODE_ID")
    return node_id


os.environ["WSL_DIAG_SOURCE_ID"] = _canonical_diag_source(
    NODE_ID, os.environ.get("WSL_DIAG_SOURCE_ID"))
SCORING_BOOT_ID = uuid.uuid4().hex

def _parse_lanes(raw):
    """Parse WSL_LANES (e.g. "23,24") into a lane-id list.

    Unset, blank, or malformed input is a hard startup error. Falling back to
    a default pair on a provisioning typo could actuate the WRONG physical
    machines' relays. Dead node > wrong machine. (Each lane must also have a
    LANE_GPIO entry — validated below.)
    """
    raw = (raw or "").strip()
    if not raw:
        raise SystemExit(
            "WSL_LANES is required; no physical pair may be guessed")
    try:
        lanes = [int(p) for p in raw.split(",") if p.strip()]
    except ValueError:
        raise SystemExit(f"WSL_LANES={raw!r}: not a comma-separated list of lane numbers")
    if not lanes:
        raise SystemExit(f"WSL_LANES={raw!r}: no lanes parsed")
    if len(set(lanes)) != len(lanes):
        raise SystemExit(f"WSL_LANES={raw!r}: duplicate lane ids")
    lanes = sorted(lanes)
    if (
        len(lanes) != 2
        or lanes[0] < 1
        or lanes[1] > 32
        or lanes[0] % 2 != 1
        or lanes[1] != lanes[0] + 1
    ):
        raise SystemExit(
            f"WSL_LANES={raw!r}: expected one consecutive odd/even lane pair")
    return lanes

LANES = _parse_lanes(os.environ.get("WSL_LANES"))
# Shared LANE_NODE_TOKEN authenticates HTTP diagnostics and server->node
# commands. The distinct WSL_SCORING_NODE_TOKEN authenticates this Pi's HELLO
# identity; reusing the shared token would let any enrolled Pi claim any pair.
LANE_NODE_TOKEN = os.environ.get("LANE_NODE_TOKEN", "").strip()
ALLOW_UNAUTHENTICATED_BENCH = (
    os.environ.get("WSL_ALLOW_UNAUTHENTICATED_BENCH", "").strip() == "1")
if not LANE_NODE_TOKEN and not ALLOW_UNAUTHENTICATED_BENCH:
    raise SystemExit(
        "LANE_NODE_TOKEN is required; set "
        "WSL_ALLOW_UNAUTHENTICATED_BENCH=1 only on an isolated bench")


def _scoring_node_token(
        raw, allow_unauthenticated_bench, shared_token=None):
    token = (raw or "").strip()
    if token and (
        not 16 <= len(token) <= 512
        or any(ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise SystemExit(
            "WSL_SCORING_NODE_TOKEN must be 16..512 printable ASCII "
            "characters")
    if not token and not allow_unauthenticated_bench:
        raise SystemExit(
            "WSL_SCORING_NODE_TOKEN is required for per-node HELLO "
            "authentication")
    shared = (shared_token or "").strip()
    if token and shared and hmac.compare_digest(
            token.encode("utf-8"), shared.encode("utf-8")):
        raise SystemExit(
            "WSL_SCORING_NODE_TOKEN must be distinct from LANE_NODE_TOKEN")
    return token


SCORING_NODE_TOKEN = _scoring_node_token(
    os.environ.get("WSL_SCORING_NODE_TOKEN"),
    ALLOW_UNAUTHENTICATED_BENCH,
    LANE_NODE_TOKEN)
HELLO_AUTH_TOKEN = SCORING_NODE_TOKEN or LANE_NODE_TOKEN

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
PROTOCOL_VERSION = 3

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
    HEARTBEAT_ACK = "heartbeat_ack"
    SCORING_EVENT_ACK = "scoring_event_ack"
    COMMAND_ACK = "command_ack"
    SCORING_EPOCH_SYNC = "scoring_epoch_sync"
    CYCLE = "cycle"
    OPEN_LANE = "open_lane"
    CLOSE_LANE = "close_lane"
    RESET = "reset"
    POWER_ON = "power_on"
    POWER_OFF = "power_off"

def encode(t, **f): return json.dumps({"type": t, "ts": time.time(), **f})
def decode(r):
    return strict_json_loads(r, max_bytes=65536, max_depth=20, max_nodes=4096)

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
_SCORING_TRANSPORT = None
_SCORING_EXECUTOR = None
_scoring_event_wake = None
_pending_scoring_event = None
_scoring_transport_init_attempted = False
try:
    SCORING_EVENT_QUEUE_MAX = max(
        1, int(os.environ.get("WSL_SCORING_EVENT_QUEUE_MAX", "128")))
except ValueError:
    SCORING_EVENT_QUEUE_MAX = 128
try:
    SCORING_EVENT_MAX_AGE_S = max(
        1.0, float(os.environ.get("WSL_SCORING_EVENT_MAX_AGE_S", "30")))
except ValueError:
    SCORING_EVENT_MAX_AGE_S = 30.0
try:
    SCORING_EVENT_ACK_TIMEOUT_S = max(
        1.0, float(os.environ.get("WSL_SCORING_EVENT_ACK_TIMEOUT_S", "10")))
except ValueError:
    SCORING_EVENT_ACK_TIMEOUT_S = 10.0
_scoring_event_drops = 0
_scoring_event_expired = 0
_scoring_event_overdue_ids = set()
_scoring_epochs = {lane_id: None for lane_id in LANES}


def _encode_scoring_event(event_type, **fields):
    created = time.time()
    lane = fields.get("lane")
    if lane in _scoring_epochs and "scoring_epoch" not in fields:
        fields["scoring_epoch"] = _scoring_epochs[lane]
    return encode(
        event_type, event_id=str(uuid.uuid4()),
        event_created_at=created, **fields)


def _record_scoring_event_transport(msg, disposition, reason=None):
    """Write a durable reconciliation breadcrumb without blocking GPIO."""
    try:
        frame = decode(msg)
        lane = frame.get("lane")
        detail = {
            "event_id": frame.get("event_id"),
            "event_type": frame.get("type"),
            "event_created_at": frame.get("event_created_at"),
            "lane": lane,
            "pin_mask": frame.get("pin_mask"),
            "awaiting_manual": frame.get("awaiting_manual", False),
            "disposition": disposition,
            "reason": reason,
            # Exact durable depth is published by the heartbeat's off-loop
            # health probe.  Never perform SQLite I/O from this evidence hook.
            "queue_depth": (
                None if _SCORING_TRANSPORT is not None
                else (event_queue.qsize() if event_queue else 0)),
        }
        severity = (
            "info" if disposition in ("queued", "sent", "acknowledged")
            else "fault")
        _diag_emit_lanes(
            severity, "scoring_event_transport",
            code=reason or disposition, detail=detail,
            lanes=[lane] if lane in LANES else LANES)
    except Exception:
        log.debug("scoring event transport evidence failed", exc_info=True)


async def _admit_scoring_event(msg):
    """Persist before making an event visible to the sender."""
    global _scoring_event_drops
    if _SCORING_TRANSPORT is not None:
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                _SCORING_EXECUTOR, _SCORING_TRANSPORT.put_event, msg)
            if result == "full":
                _scoring_event_drops += 1
                _record_scoring_event_transport(
                    msg, "lost", "durable_outbox_full_manual_reconciliation")
                return False
            if result == "admitted":
                _record_scoring_event_transport(msg, "queued")
            elif result != "duplicate":
                _scoring_event_drops += 1
                _record_scoring_event_transport(
                    msg, "lost",
                    "durable_event_id_collision_manual_reconciliation")
                return False
            if _scoring_event_wake is not None:
                _scoring_event_wake.set()
            return True
        except Exception:
            _scoring_event_drops += 1
            _record_scoring_event_transport(
                msg, "lost", "durable_outbox_write_error_manual_reconciliation")
            log.exception("scoring event durable admission failed")
            return False

    if _scoring_transport_init_attempted:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost",
            "durable_transport_unavailable_manual_reconciliation")
        return False

    # Test/bench fallback used only when main() has not initialized the
    # production durable transport.
    if event_queue is None:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost", "queue_unavailable")
        return False
    try:
        event_queue.put_nowait(msg)
        _record_scoring_event_transport(msg, "queued")
        return True
    except asyncio.QueueFull:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost", "queue_full_manual_reconciliation")
        return False


def _enqueue_scoring_event_nowait(msg):
    """Schedule non-blocking durable admission from the asyncio thread."""
    global _scoring_event_drops
    if _SCORING_TRANSPORT is not None:
        try:
            asyncio.get_running_loop().create_task(_admit_scoring_event(msg))
            return True
        except RuntimeError:
            pass
    if _scoring_transport_init_attempted:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost",
            "durable_transport_unavailable_manual_reconciliation")
        return False
    # The compatibility path is synchronous and intentionally limited to
    # tests/startup before the production transport exists.
    if event_queue is None:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost", "queue_unavailable")
        return False
    try:
        event_queue.put_nowait(msg)
        _record_scoring_event_transport(msg, "queued")
        return True
    except asyncio.QueueFull:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost", "queue_full_manual_reconciliation")
        return False


def _enqueue_scoring_event_threadsafe(msg):
    """Admit a physical GPIO event before its callback returns.

    gpiozero invokes these callbacks on its own worker threads.  Persist
    directly on that thread: waiting on a coroutine/future here can deadlock
    if a bench invokes the callback from the asyncio thread, while merely
    scheduling admission leaves a crash window before SQLite commits.  The
    DurableTransport lock serializes this short transaction with sender
    operations.  Only the asyncio.Event wake-up crosses back to the loop.

    A True result with the production transport active therefore means the
    event is already committed (or was an idempotent duplicate).
    """
    global _scoring_event_drops
    transport = _SCORING_TRANSPORT
    if transport is not None:
        try:
            result = transport.put_event(msg)
            if result == "full":
                _scoring_event_drops += 1
                _record_scoring_event_transport(
                    msg, "lost",
                    "durable_outbox_full_manual_reconciliation")
                return False
            if result not in ("admitted", "duplicate"):
                raise RuntimeError(
                    f"unexpected durable admission result: {result!r}")
            if result == "admitted":
                _record_scoring_event_transport(msg, "queued")
            loop = main_loop
            wake = _scoring_event_wake
            if loop is not None and wake is not None:
                try:
                    loop.call_soon_threadsafe(wake.set)
                except RuntimeError:
                    # The row is durable.  A closing loop needs no wake; the
                    # next process start notices the non-empty outbox.
                    log.debug("scoring sender loop closed after durable "
                              "GPIO admission", exc_info=True)
            return True
        except Exception:
            _scoring_event_drops += 1
            _record_scoring_event_transport(
                msg, "lost",
                "durable_outbox_write_error_manual_reconciliation")
            log.exception("scoring event durable GPIO admission failed")
            return False

    if main_loop is None:
        return _enqueue_scoring_event_nowait(msg)
    if _scoring_transport_init_attempted:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            msg, "lost",
            "durable_transport_unavailable_manual_reconciliation")
        return False
    # Bench-only pre-main compatibility path; production sets the durable
    # transport state before accepting scoring traffic.
    main_loop.call_soon_threadsafe(_enqueue_scoring_event_nowait, msg)
    return True


def _begin_camera_capture_threadsafe(edge_msg):
    """Commit the raw DIELL edge before scheduling settle/capture work."""
    global _scoring_event_drops
    transport = _SCORING_TRANSPORT
    if transport is None:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            edge_msg, "lost",
            "camera_capture_ledger_unavailable_manual_reconciliation")
        return False
    try:
        result = transport.begin_capture_job(edge_msg)
        if result == "full":
            _scoring_event_drops += 1
            _record_scoring_event_transport(
                edge_msg, "lost",
                "durable_outbox_full_manual_reconciliation")
            return False
        if result not in ("admitted", "duplicate"):
            raise RuntimeError(
                f"unexpected capture admission result: {result!r}")
        if result == "admitted":
            _record_scoring_event_transport(edge_msg, "capture_pending")
        return True
    except Exception:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            edge_msg, "lost",
            "camera_capture_ledger_write_error_manual_reconciliation")
        log.exception("camera edge durable admission failed")
        return False


async def _complete_camera_capture(edge_msg, final_msg):
    """Atomically retire a capture job into the scoring-event outbox."""
    global _scoring_event_drops
    transport = _SCORING_TRANSPORT
    if transport is None:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            edge_msg, "lost",
            "camera_capture_ledger_unavailable_manual_reconciliation")
        return False
    event_id = decode(edge_msg).get("event_id")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _SCORING_EXECUTOR,
            transport.complete_capture_job, event_id, final_msg)
        if result not in ("admitted", "duplicate"):
            raise RuntimeError(
                f"camera capture completion was {result!r}")
        if result == "admitted":
            _record_scoring_event_transport(final_msg, "queued")
        if _scoring_event_wake is not None:
            _scoring_event_wake.set()
        return True
    except Exception:
        _scoring_event_drops += 1
        _record_scoring_event_transport(
            edge_msg, "capture_pending",
            "camera_capture_completion_failed_restart_recovers_manual")
        log.exception(
            "camera capture completion failed; raw edge remains durable")
        return False

# One supervised camera operation across scoring, health, and self-checks.
# ``asyncio.wait_for(to_thread(...))`` alone is unsafe because timeout cancels
# only the asyncio wrapper, not a wedged native cv2 call. Keep the underlying
# task, latch camera use unavailable, and refuse every later submission until
# an explicit camera re-initialization/restart.
_camera_worker_task = None
_camera_worker_started_at = None
_camera_poisoned = False
_camera_poison_reason = None
_capture_started_at: dict = {lane_id: None for lane_id in LANES}


class CameraOperationUnavailable(RuntimeError):
    pass


def _consume_camera_worker(task):
    """Retrieve late native-worker completion so timeout cannot leak errors."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except BaseException:
        log.debug("late camera worker failed after caller left",
                  exc_info=True)


async def _latch_camera_stalled(operation, timeout_s, lane_id=None):
    """Latch immediately; publish slow filesystem evidence out of band."""
    global _camera_poisoned, _camera_poison_reason
    global _cam_health_warned, _last_camera_health
    first = not _camera_poisoned
    _camera_poisoned = True
    _camera_poison_reason = f"{operation}_timeout"
    _last_camera_health = {
        "ok": False,
        "code": "capture_stalled",
        "operation": operation,
        "lane_id": lane_id,
        "timeout_s": timeout_s,
        "lanes": list(LANES),
    }
    if first:
        _cam_health_warned = True
        try:
            diagnostic = asyncio.create_task(asyncio.to_thread(
                _diag_emit_lanes,
                "warn", "camera_health", code="capture_stalled",
                detail={
                    "operation": operation,
                    "lane_id": lane_id,
                    "timeout_s": timeout_s,
                    "manual_fallback_latched": True,
                    "recovery": "restart_or_explicit_camera_reinit",
                },
                condition=("track_a_camera_health",)))
            diagnostic.add_done_callback(_consume_camera_worker)
        except Exception:
            log.debug("camera stall diagnostic scheduling swallowed",
                      exc_info=True)
    # A diagnostics filesystem fault must never delay the manual BALL_EVENT
    # fallback. The in-memory latch above is authoritative for this process;
    # best-effort durable cross-service publication runs independently.
    try:
        publish = asyncio.create_task(
            asyncio.to_thread(_health_drop_hop, dict(_last_camera_health)))
        publish.add_done_callback(_consume_camera_worker)
    except Exception:
        log.debug("camera stall health-drop scheduling swallowed",
                  exc_info=True)


async def _run_camera_operation(operation, func, *args, lane_id=None):
    """Run at most one blocking camera call and retain timed-out work."""
    global _camera_worker_task, _camera_worker_started_at
    if _camera_poisoned:
        raise CameraOperationUnavailable(
            f"camera latched unavailable: {_camera_poison_reason}")
    prior = _camera_worker_task
    if prior is not None:
        if not prior.done():
            raise CameraOperationUnavailable("camera worker already active")
        try:
            prior.result()
        except BaseException:
            pass
        _camera_worker_task = None
        _camera_worker_started_at = None

    timeout_s = max(
        0.05, _cam_env_float(CAM_CAPTURE_TIMEOUT_ENV, 10.0))
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    task.add_done_callback(_consume_camera_worker)
    _camera_worker_task = task
    _camera_worker_started_at = time.monotonic()
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout_s)
    except asyncio.TimeoutError as exc:
        # Shield keeps the actual to_thread task visible and in-flight. The
        # poison latch prevents a second native call from racing/accumulating.
        await _latch_camera_stalled(
            operation, timeout_s, lane_id=lane_id)
        raise CameraOperationUnavailable(
            f"{operation} exceeded {timeout_s:.3f}s") from exc
    finally:
        if task.done():
            _camera_worker_task = None
            _camera_worker_started_at = None

def make_foul_callback(lane_id):
    """Bind a per-lane foul callback that captures lane_id in closure.

    The AL-ZARD/DONGKER foul input asserts when the foul lamp circuit
    lights — i.e., the player crossed the foul line. This is NOT the same
    signal as ball-detect; ball-detect comes from DIELL via
    make_ball_detect_callback below.
    """
    def on_foul_detected():
        log.info(f"GPIO: foul detected on lane {lane_id}")
        return _enqueue_scoring_event_threadsafe(
            _encode_scoring_event(Msg.FOUL_EVENT, lane=lane_id))
    return on_foul_detected

async def _settle_capture_emit(lane_id, edge_msg=None):
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
    durable_capture_job = edge_msg is not None
    if edge_msg is None:
        # Direct-call compatibility for the isolated camera health tests.
        # Production GPIO callbacks always supply a previously committed job.
        edge_msg = _encode_scoring_event(
            Msg.BALL_EVENT, lane=lane_id, pin_mask=None,
            awaiting_manual=True)
    try:
        try:
            await asyncio.sleep(camera.SETTLE_S)
            _capture_started_at[lane_id] = time.monotonic()
            pin_mask = await _run_camera_operation(
                "score_capture", detect_current_pins, lane_id,
                lane_id=lane_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"lane {lane_id}: settle/capture error: {e}; -> awaiting_manual")
            pin_mask = None

        edge = decode(edge_msg)
        final = dict(edge)
        if pin_mask is None:
            log.info(f"lane {lane_id}: camera yielded no mask -> awaiting_manual (desk score)")
            final["pin_mask"] = None
            final["awaiting_manual"] = True
        else:
            log.info(f"lane {lane_id}: camera pin_mask=0x{pin_mask:03x} "
                     f"(standing={[p for p in range(1,11) if pin_mask & (1<<(p-1))]})")
            final["pin_mask"] = pin_mask
            final.pop("awaiting_manual", None)
            if pin_mask == 0:
                # All pins down: the upcoming post-sweep window is the
                # known-empty moment — schedule the (throttled) empty-ref
                # self-check (R2-14). Fire-and-forget; it guards itself.
                try:
                    asyncio.get_running_loop().create_task(
                        _maybe_camera_selfcheck(lane_id))
                except Exception:
                    pass

        final_msg = json.dumps(final)
        if durable_capture_job:
            await _complete_camera_capture(edge_msg, final_msg)
        else:
            await _admit_scoring_event(final_msg)
    finally:
        # One emit (or failure) per scheduled capture — re-arm the DIELL
        # trigger for the next real ball.
        _capture_in_flight[lane_id] = False
        _capture_started_at[lane_id] = None


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
_ball_detect_locks: dict = {
    lane_id: threading.Lock() for lane_id in LANES}
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
        # Process-local dedup uses a monotonic clock so an NTP rollback cannot
        # suppress real balls until wall time catches up. GPIO callbacks may
        # arrive on separate threads; check+set is one critical section.
        now = time.monotonic()
        with _ball_detect_locks[lane_id]:
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
            if _camera_poisoned:
                log.warning(
                    f"GPIO: lane {lane_id} camera unavailable "
                    f"({_camera_poison_reason}); immediate manual fallback")
                msg = _encode_scoring_event(
                    Msg.BALL_EVENT, lane=lane_id, pin_mask=None,
                    awaiting_manual=True)
                return _enqueue_scoring_event_threadsafe(msg)
            if _capture_in_flight[lane_id]:
                log.info(f"GPIO: lane {lane_id} DIELL retrigger while capture "
                         f"in flight (pin scatter?) — ignored")
                return
            log.info(f"GPIO: ball detected on lane {lane_id}, mode=camera; "
                     f"settling {camera.SETTLE_S}s before capture")
            edge_msg = _encode_scoring_event(
                Msg.BALL_EVENT, lane=lane_id, pin_mask=None,
                awaiting_manual=True)
            if not _begin_camera_capture_threadsafe(edge_msg):
                return False
            _capture_in_flight[lane_id] = True
            if main_loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        _settle_capture_emit(lane_id, edge_msg), main_loop)
                except Exception:
                    # The edge is already durable.  Leave the capture job for
                    # restart recovery and keep this lane latched so a second
                    # edge cannot obscure the unresolved first ball.
                    log.exception(
                        "camera capture task scheduling failed; durable "
                        "edge will recover awaiting-manual on restart")
            else:
                log.error(
                    "camera edge committed without an event loop; restart "
                    "will recover it awaiting-manual")
            return True

        # manual mode: include NO pin_mask — server treats as "ball happened,
        # await /api/lane/N/score" instead of recording with bogus stub data.
        log.info(f"GPIO: ball detected on lane {lane_id}, "
                 f"mode=manual (awaiting desk score)")
        msg = _encode_scoring_event(
            Msg.BALL_EVENT, lane=lane_id, pin_mask=None,
            awaiting_manual=True)
        return _enqueue_scoring_event_threadsafe(msg)
    return on_ball_detected


_scoring_callbacks_enabled = False


def _disable_scoring_callbacks():
    """Mask physical scoring inputs until durable admission is available."""
    global _scoring_callbacks_enabled
    for lane_id in LANES:
        BALL_DETECT[lane_id].when_pressed = None
        DIELL_LEFT[lane_id].when_released = None
        DIELL_RIGHT[lane_id].when_released = None
    _scoring_callbacks_enabled = False


def _enable_scoring_callbacks():
    """Bind inputs only after the durable ledger and event loop are ready."""
    global _scoring_callbacks_enabled
    if (_SCORING_TRANSPORT is None or _SCORING_EXECUTOR is None
            or main_loop is None):
        _disable_scoring_callbacks()
        raise RuntimeError(
            "cannot enable scoring GPIO without durable transport")
    for lane_id in LANES:
        BALL_DETECT[lane_id].when_pressed = make_foul_callback(lane_id)
        callback = make_ball_detect_callback(lane_id)
        DIELL_LEFT[lane_id].when_released = callback
        DIELL_RIGHT[lane_id].when_released = callback
    _scoring_callbacks_enabled = True


_disable_scoring_callbacks()

_last_scoring_ack = None
_scoring_ack_stalled = False

# A heartbeat is sent every five seconds.  If the server has not durably
# acknowledged any of the last three sequence steps, fail this WebSocket so
# connection_manager establishes a fresh session.  This supervises only the
# scoring/control transport; watchdog_kick_loop intentionally remains outside
# the connection scope and continues to pet the independent hardware watchdog.
SCORING_HEARTBEAT_INTERVAL_S = 5.0
SCORING_HEARTBEAT_ACK_MAX_LAG = 3


def _read_scoring_outbox_health():
    """Blocking JSONL scan; callers must run this off the asyncio loop."""
    writer = globals().get("_DIAG_WRITER")
    try:
        replayer = getattr(writer, "outbox", None)
        health = getattr(replayer, "health", None)
        outbox = health() if callable(health) else None
    except Exception:
        outbox = None
    if not isinstance(outbox, dict):
        outbox = {
            "cursor_ok": False,
            "error": True,
            "health_unavailable": True,
            "oldest_unsent_age_s": None,
            "backlog": 0,
            "backlog_bytes": 0,
            "pending_writes": 0,
            "dropped": 0,
            "quarantined": 0,
            "cycles_quarantined": 0,
            "post_errors": 0,
            "write_errors": 0,
            "sink_errors": 0,
        }
    else:
        outbox = dict(outbox)
    if _SCORING_TRANSPORT is not None:
        transport = _SCORING_TRANSPORT.event_health()
        try:
            clock_guard = _SCORING_TRANSPORT.observe_wall_clock()
        except Exception:
            clock_guard = {
                "observed": False,
                "anomaly_latched": True,
                "high_water_epoch": None,
                "observed_epoch": None,
            }
        scoring_depth = transport["depth"]
        scoring_capacity = transport["capacity"]
        scoring_oldest_age = transport["oldest_age_s"]
        scoring_capture_jobs = transport["capture_jobs"]
        scoring_capture_oldest_age = transport["capture_oldest_age_s"]
        scoring_durable = True
        scoring_error = (
            not transport["ok"]
            or not clock_guard["observed"]
            or clock_guard["anomaly_latched"])
    else:
        scoring_depth = event_queue.qsize() if event_queue is not None else 0
        scoring_capacity = SCORING_EVENT_QUEUE_MAX
        scoring_oldest_age = None
        scoring_capture_jobs = 0
        scoring_capture_oldest_age = None
        clock_guard = {
            "observed": False,
            "anomaly_latched": True,
            "high_water_epoch": None,
            "observed_epoch": None,
        }
        scoring_durable = False
        scoring_error = True
    if scoring_error:
        outbox["error"] = True
    outbox.update({
        "scoring_event_queue_depth": int(scoring_depth),
        "scoring_event_queue_capacity": int(scoring_capacity),
        "scoring_event_oldest_age_s": scoring_oldest_age,
        "scoring_capture_jobs": int(scoring_capture_jobs),
        "scoring_capture_oldest_age_s": scoring_capture_oldest_age,
        "scoring_clock_observed": bool(clock_guard["observed"]),
        "scoring_clock_anomaly_latched": bool(
            clock_guard["anomaly_latched"]),
        "scoring_clock_high_water_epoch": (
            clock_guard["high_water_epoch"]),
        "scoring_clock_observed_epoch": clock_guard["observed_epoch"],
        "scoring_event_durable": scoring_durable,
        "scoring_event_error": scoring_error,
        "scoring_event_overdue": bool(
            scoring_oldest_age is not None
            and scoring_oldest_age > SCORING_EVENT_MAX_AGE_S),
        "scoring_event_drops": int(_scoring_event_drops),
        "scoring_event_expired": int(_scoring_event_expired),
        "scoring_event_max_age_s": float(SCORING_EVENT_MAX_AGE_S),
    })
    return outbox


async def _scoring_status_payload(session_id, heartbeat_seq):
    """Current Track-A capability plus off-loop delivery-health scan."""
    outbox = await asyncio.to_thread(_read_scoring_outbox_health)
    camera_calibrated = bool(
        SCORING_MODE == "camera"
        and _PAIR_CAMERA is not None
        and getattr(_PAIR_CAMERA, "ready", False))
    camera_ok = bool(
        camera_calibrated
        and not _camera_poisoned
        and isinstance(_last_camera_health, dict)
        and _last_camera_health.get("ok") is True)
    return {
        "scoring_boot_id": SCORING_BOOT_ID,
        "scoring_session_id": session_id,
        "heartbeat_seq": int(heartbeat_seq),
        "scoring_mode": SCORING_MODE,
        "camera_calibrated": camera_calibrated,
        "camera_ok": camera_ok,
        "camera_code": (
            _last_camera_health.get("code")
            if isinstance(_last_camera_health, dict) else "unavailable"),
        "outbox": outbox,
        "node_ball_lockout_s": float(BALL_DETECT_LOCKOUT_S),
    }


async def heartbeat_loop(ws, ack_state):
    seq = 0
    while True:
        await asyncio.sleep(SCORING_HEARTBEAT_INTERVAL_S)
        ack_lag = ack_state["sent_seq"] - ack_state["acked_seq"]
        if ack_lag >= SCORING_HEARTBEAT_ACK_MAX_LAG:
            global _scoring_ack_stalled
            detail = {
                "node": NODE_ID,
                "scoring_session_id": ack_state["session_id"],
                "sent_seq": ack_state["sent_seq"],
                "acked_seq": ack_state["acked_seq"],
                "ack_lag": ack_lag,
                "max_ack_lag": SCORING_HEARTBEAT_ACK_MAX_LAG,
                "heartbeat_interval_s": SCORING_HEARTBEAT_INTERVAL_S,
                "approx_stall_s": (
                    SCORING_HEARTBEAT_INTERVAL_S
                    * SCORING_HEARTBEAT_ACK_MAX_LAG),
                "action": "connection_failed_for_reconnect",
            }
            if not _scoring_ack_stalled:
                _scoring_ack_stalled = True
                await asyncio.to_thread(
                    _diag_emit_lanes,
                    "fault", "scoring_server_ack_stalled",
                    code="scoring_server_ack_stalled", detail=detail,
                    condition=("track_a_scoring_ack_stalled",))
            log.error(
                "scoring heartbeat ACK stalled "
                "(session=%s sent_seq=%s acked_seq=%s lag=%s); "
                "failing connection for reconnect",
                ack_state["session_id"], ack_state["sent_seq"],
                ack_state["acked_seq"], ack_lag)
            raise ConnectionError(
                "scoring heartbeat ACK stalled "
                f"(lag={ack_lag}, max={SCORING_HEARTBEAT_ACK_MAX_LAG})")
        seq += 1
        status = await _scoring_status_payload(
            ack_state["session_id"], seq)
        # Publish the upper bound before yielding in ws.send(). A local or
        # otherwise very fast server can deliver HEARTBEAT_ACK while send()
        # is still suspended; recording sent_seq afterwards falsely rejects
        # that valid, durably committed ACK as "ahead".
        ack_state["sent_seq"] = seq
        await ws.send(encode(
            Msg.HEARTBEAT, node=NODE_ID,
            **status))


def _is_strict_utc_timestamp(value):
    """True only for a bounded, timezone-aware ISO-8601 UTC timestamp."""
    if (not isinstance(value, str) or not value
            or value != value.strip() or len(value) > 64
            or "T" not in value):
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
        offset = parsed.utcoffset()
    except (TypeError, ValueError, OverflowError):
        return False
    return offset is not None and offset.total_seconds() == 0

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

async def _next_scoring_event():
    """Return the ordered head without removing it."""
    if _SCORING_TRANSPORT is None:
        return await event_queue.get()
    loop = asyncio.get_running_loop()
    while True:
        row = await loop.run_in_executor(
            _SCORING_EXECUTOR, _SCORING_TRANSPORT.peek_event)
        if row is not None:
            return row["frame_json"]
        _scoring_event_wake.clear()
        row = await loop.run_in_executor(
            _SCORING_EXECUTOR, _SCORING_TRANSPORT.peek_event)
        if row is not None:
            return row["frame_json"]
        await _scoring_event_wake.wait()


async def event_sender(ws, ack_state=None):
    """Retire an ordered durable event only after its server receipt."""
    global _scoring_event_expired, _pending_scoring_event
    if ack_state is None:
        ack_state = {"event_ack_futures": {}}
    ack_futures = ack_state.setdefault("event_ack_futures", {})
    while True:
        if _pending_scoring_event is None:
            _pending_scoring_event = await _next_scoring_event()
        msg = _pending_scoring_event
        try:
            frame = decode(msg)
            event_id = frame.get("event_id")
            created = frame.get("event_created_at")
            valid_created = (
                isinstance(created, (int, float))
                and not isinstance(created, bool)
                and math.isfinite(float(created)))
            age = time.time() - float(created) if valid_created else None
        except Exception:
            event_id = None
            age = None
        if age is None or age < -5.0 or age > SCORING_EVENT_MAX_AGE_S:
            if event_id not in _scoring_event_overdue_ids:
                _scoring_event_overdue_ids.add(event_id)
                _scoring_event_expired += 1
            _record_scoring_event_transport(
                msg, "overdue", "delivery_overdue_manual_review")
        if not isinstance(event_id, str) or not event_id:
            _record_scoring_event_transport(
                msg, "lost", "invalid_durable_event_manual_reconciliation")
            raise RuntimeError("durable scoring event lacks event_id")
        receipt = asyncio.get_running_loop().create_future()
        ack_futures[event_id] = receipt
        log.info(f"→ {msg}")
        try:
            await ws.send(msg)
            ack = await asyncio.wait_for(
                asyncio.shield(receipt), SCORING_EVENT_ACK_TIMEOUT_S)
            if ack.get("disposition") not in (
                    "accepted", "duplicate", "ignored_lane_closed",
                    "awaiting_manual", "stale_quarantined",
                    "overdue_quarantined",
                    "clock_anomaly_quarantined",
                    "duplicate_window_suppressed"):
                raise RuntimeError(
                    f"server rejected scoring event: {ack!r}")
            if _SCORING_TRANSPORT is not None:
                await asyncio.get_running_loop().run_in_executor(
                    _SCORING_EXECUTOR,
                    _SCORING_TRANSPORT.ack_event, event_id)
            elif event_queue is not None:
                event_queue.task_done()
            _record_scoring_event_transport(msg, "acknowledged")
            _pending_scoring_event = None
            _scoring_event_overdue_ids.discard(event_id)
        except BaseException:
            # Keep the current head.  The next connection sends it before any
            # later event, preserving FOUL -> BALL ordering.
            raise
        finally:
            if ack_futures.get(event_id) is receipt:
                ack_futures.pop(event_id, None)

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
try:
    COMMAND_MAX_AGE_S = max(
        1.0, float(os.environ.get("WSL_COMMAND_MAX_AGE_S", "600")))
except ValueError:
    COMMAND_MAX_AGE_S = 600.0
_lane_cmd_queues = {}    # queue key -> asyncio.Queue; key = lane id (concurrent) or None (shared serial)
_lane_cmd_workers = {}   # queue key -> worker Task; cancelled + queues flushed on connection drop
_COMMAND_TYPES = {
    Msg.CYCLE, Msg.OPEN_LANE, Msg.CLOSE_LANE, Msg.RESET,
    Msg.POWER_ON, Msg.POWER_OFF, Msg.SCORING_EPOCH_SYNC,
}
_ACTUATING_COMMAND_TYPES = _COMMAND_TYPES - {Msg.SCORING_EPOCH_SYNC}


def _valid_command_frame(msg):
    if not isinstance(msg, dict) or msg.get("type") not in _COMMAND_TYPES:
        return False
    required = {"type", "ts", "lane", "command_id", "issued_at"}
    allowed = set(required)
    if msg["type"] == Msg.OPEN_LANE:
        allowed.update({"bowlers", "scoring_epoch"})
    elif msg["type"] == Msg.CLOSE_LANE:
        allowed.add("scoring_epoch")
    elif msg["type"] == Msg.SCORING_EPOCH_SYNC:
        allowed.update({"scoring_epoch", "session_generation"})
    if LANE_NODE_TOKEN:
        allowed.add("token")
    command_id = msg.get("command_id")
    issued = msg.get("issued_at")
    envelope_ts = msg.get("ts")
    lane = msg.get("lane")
    type_fields_ok = True
    if msg["type"] == Msg.OPEN_LANE:
        bowlers = msg.get("bowlers")
        type_fields_ok = (
            isinstance(bowlers, list)
            and len(bowlers) <= 128
            and all(
                isinstance(name, str)
                and name == name.strip()
                and 0 < len(name) <= 200
                for name in bowlers))
    elif msg["type"] == Msg.SCORING_EPOCH_SYNC:
        epoch = msg.get("scoring_epoch")
        generation = msg.get("session_generation")
        type_fields_ok = (
            (epoch is None
             or (isinstance(epoch, str) and epoch == epoch.strip()
                 and 0 < len(epoch) <= 200))
            and isinstance(generation, int)
            and not isinstance(generation, bool)
            and generation > 0)
    return (
        set(msg) == allowed
        and isinstance(lane, int)
        and not isinstance(lane, bool)
        and lane in LANES
        and isinstance(command_id, str)
        and bool(command_id.strip())
        and command_id == command_id.strip()
        and len(command_id) <= 128
        and isinstance(envelope_ts, (int, float))
        and not isinstance(envelope_ts, bool)
        and math.isfinite(float(envelope_ts))
        and float(envelope_ts) >= time.time() - COMMAND_MAX_AGE_S
        and float(envelope_ts) <= time.time() + 300.0
        and isinstance(issued, (int, float))
        and not isinstance(issued, bool)
        and math.isfinite(float(issued))
        and float(issued) >= time.time() - COMMAND_MAX_AGE_S
        and float(issued) <= time.time() + 300.0
        and type_fields_ok
    )


async def _send_command_ack(ws, command_id, status, original_status=None):
    fields = {
        "command_id": command_id,
        "status": status,
        "completed_at": time.time(),
    }
    if original_status is not None:
        fields["original_status"] = original_status
    await ws.send(encode(Msg.COMMAND_ACK, **fields))


def _record_command_transport(msg, severity, code, **detail):
    payload = {
        "command_id": msg.get("command_id"),
        "command_type": msg.get("type"),
        **detail,
    }
    _diag_emit_lanes(
        severity, "command_transport", code=code, detail=payload,
        lanes=[msg["lane"]] if msg.get("lane") in LANES else LANES)


async def _complete_command(msg, status):
    result = {"status": status}
    await asyncio.get_running_loop().run_in_executor(
        _SCORING_EXECUTOR,
        _SCORING_TRANSPORT.complete_command,
        msg["command_id"], result)
    return result


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
        cmd_type, lane_id, msg, ws, _prior_epoch = await queue.get()
        try:
            await _execute_command(cmd_type, lane_id, msg)
        except asyncio.CancelledError:
            _record_command_transport(
                msg, "fault", "ambiguous",
                status="ambiguous", reason="worker_cancelled")
            raise
        except Exception as e:
            log.error(f"command {cmd_type} on lane {lane_id} failed: {e}")
            _record_command_transport(
                msg, "fault", "ambiguous",
                status="ambiguous", error=type(e).__name__,
                reason="actuation_exception")
            try:
                await _send_command_ack(
                    ws, msg["command_id"], "ambiguous")
            except Exception:
                _record_command_transport(
                    msg, "fault", "ack_indeterminate",
                    status="ambiguous", reason="ack_send_failed")
        else:
            try:
                await _complete_command(msg, "completed")
            except Exception as exc:
                _record_command_transport(
                    msg, "fault", "ambiguous",
                    status="ambiguous",
                    reason="completion_ledger_error",
                    error=type(exc).__name__)
                try:
                    await _send_command_ack(
                        ws, msg["command_id"], "ambiguous")
                except Exception:
                    _record_command_transport(
                        msg, "fault", "ack_indeterminate",
                        status="ambiguous", reason="ack_send_failed")
            else:
                _record_command_transport(
                    msg, "info", "completed", status="completed")
                try:
                    await _send_command_ack(
                        ws, msg["command_id"], "completed")
                except Exception:
                    # The durable ledger remains completed. A same-ID replay
                    # receives duplicate/original=completed and cannot
                    # re-actuate.
                    _record_command_transport(
                        msg, "fault", "ack_indeterminate",
                        status="completed", reason="ack_send_failed")
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
    # Topology epochs are advanced when a command is admitted to the queue so
    # sensor events immediately bind to the intended session.  If several
    # OPEN/CLOSE transitions are queued, each item's prior_epoch is therefore
    # the state left by the preceding item.  Restore only the earliest prior
    # state for each lane after the entire backlog is drained; restoring in
    # FIFO order would incorrectly leave the final intermediate epoch behind.
    restore_epochs = {}
    for q in _lane_cmd_queues.values():
        while True:
            try:
                (cmd_type, lane_id, queued_msg, _ws,
                 prior_epoch) = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                await _complete_command(queued_msg, "refused")
            except Exception:
                log.exception(
                    "failed to persist dropped command receipt")
            _record_command_transport(
                queued_msg, "fault", "refused",
                status="refused", reason=reason)
            if queued_msg.get("type") in (
                    Msg.OPEN_LANE, Msg.CLOSE_LANE):
                restore_epochs.setdefault(lane_id, prior_epoch)
            q.task_done()
            dropped += 1
            log.warning(f"  dropped queued {cmd_type} for lane {lane_id} ({reason})")
    for lane_id, prior_epoch in restore_epochs.items():
        _scoring_epochs[lane_id] = prior_epoch
    if dropped:
        log.warning(f"{dropped} queued command(s) dropped: {reason}")


async def command_handler(ws, ack_state):
    async for raw in ws:
        # This socket carries physical authority. A malformed frame makes the
        # connection untrustworthy; fail it so connection_manager closes and
        # re-authenticates instead of scanning ahead to a later command.
        try:
            msg = decode(raw)
            cmd_type = msg.get("type")
            lane = msg.get("lane")
        except Exception as e:
            log.error(
                "malformed authoritative server frame; closing connection "
                "(%r)", e)
            raise ConnectionError(
                "malformed authoritative server frame") from e
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
        # An unset token is accepted only under the explicit isolated-bench
        # override enforced during startup.
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

        if cmd_type == Msg.HEARTBEAT_ACK:
            ack_seq = msg.get("heartbeat_seq")
            ack_session = msg.get("scoring_session_id")
            committed_at = msg.get("committed_at")
            epochs = msg.get("scoring_epochs")
            epoch_ok = (
                isinstance(epochs, dict)
                and set(epochs) == {str(lane_id) for lane_id in LANES}
                and all(
                    value is None
                    or (isinstance(value, str) and value.strip()
                        and len(value) <= 200)
                    for value in epochs.values()))
            if (msg.get("node") != NODE_ID
                    or ack_session != ack_state["session_id"]
                    or not isinstance(ack_seq, int)
                    or isinstance(ack_seq, bool)
                    or ack_seq < 0
                    or ack_seq > ack_state["sent_seq"]
                    or ack_seq <= ack_state["acked_seq"]
                    or not _is_strict_utc_timestamp(committed_at)
                    or not epoch_ok):
                log.warning("invalid scoring heartbeat ACK ignored")
                continue
            ack_state["acked_seq"] = ack_seq
            for lane_id in LANES:
                _scoring_epochs[lane_id] = epochs[str(lane_id)]
            global _last_scoring_ack
            _last_scoring_ack = {
                "scoring_session_id": ack_session,
                "heartbeat_seq": ack_seq,
                "committed_at": committed_at,
            }
            global _scoring_ack_stalled
            if (_scoring_ack_stalled
                    or ("track_a_scoring_ack_stalled",)
                    in _known_diag_condition_bases(
                        "track_a_scoring_ack_stalled")):
                await asyncio.to_thread(
                    _diag_emit_lanes,
                    "info", "recovered",
                    code="scoring_server_ack_stalled",
                    detail={
                        "node": NODE_ID,
                        "scoring_session_id": ack_session,
                        "acked_seq": ack_seq,
                        "committed_at": committed_at,
                        "recovery": "durably_committed_heartbeat_ack",
                        "recovered_event_type":
                            "scoring_server_ack_stalled",
                        "recovered_code":
                            "scoring_server_ack_stalled",
                    },
                    condition=("track_a_scoring_ack_stalled",),
                    clear_condition=True)
                _scoring_ack_stalled = False
            continue

        if cmd_type == Msg.SCORING_EVENT_ACK:
            allowed = {
                "type", "ts", "event_id", "disposition", "committed_at"}
            if LANE_NODE_TOKEN:
                allowed.add("token")
            event_id = msg.get("event_id")
            disposition = msg.get("disposition")
            futures = ack_state.get("event_ack_futures") or {}
            receipt = futures.get(event_id)
            if (set(msg) != allowed
                    or not isinstance(event_id, str)
                    or disposition not in (
                        "accepted", "duplicate", "ignored_lane_closed",
                        "awaiting_manual", "stale_quarantined",
                        "overdue_quarantined",
                        "clock_anomaly_quarantined",
                        "duplicate_window_suppressed")
                    or not _is_strict_utc_timestamp(
                        msg.get("committed_at"))
                    or receipt is None or receipt.done()):
                log.warning("invalid/unmatched scoring event ACK ignored")
                continue
            receipt.set_result({
                "event_id": event_id,
                "disposition": disposition,
                "committed_at": msg["committed_at"],
            })
            continue

        if lane not in LANES:
            log.warning(f"Command for unknown lane {lane}; this node handles {LANES}")
            continue

        # POWER on/off is an instant, safety-relevant latched relay — it is
        if not _valid_command_frame(msg):
            issued = msg.get("issued_at")
            envelope_ts = msg.get("ts")
            now = time.time()
            expired = any(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) < now - COMMAND_MAX_AGE_S
                for value in (issued, envelope_ts))
            future_dated = any(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) > now + 300.0
                for value in (issued, envelope_ts))
            authorization_out_of_window = expired or future_dated
            refusal_reason = (
                "expired" if expired else
                "future_dated" if future_dated else
                "invalid_schema")
            log.error(
                f"malformed physical command refused: type={cmd_type!r} "
                f"lane={lane!r}")
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason=refusal_reason)
            command_id = msg.get("command_id")
            if isinstance(command_id, str) and command_id:
                ack_status = "refused"
                original_status = None
                # Expiration is rejected before ledger lookup. Otherwise an
                # old completed identity could be reported as a successful
                # duplicate outside its bounded authorization window.
                if (not authorization_out_of_window
                        and _SCORING_TRANSPORT is not None):
                    try:
                        claim, prior = await (
                            asyncio.get_running_loop().run_in_executor(
                                _SCORING_EXECUTOR,
                                _SCORING_TRANSPORT.begin_command,
                                command_id, str(cmd_type), lane, msg))
                        if claim == "new":
                            await _complete_command(msg, "refused")
                        elif claim == "completed":
                            ack_status = "duplicate"
                            original_status = (
                                prior.get("status")
                                if isinstance(prior, dict) else "failed")
                        elif claim == "ambiguous":
                            ack_status = "ambiguous"
                    except Exception:
                        log.exception(
                            "invalid command refusal ledger failed")
                await _send_command_ack(
                    ws, command_id, ack_status,
                    original_status=original_status)
            continue
        if _SCORING_TRANSPORT is None:
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason="durable_ledger_unavailable")
            await _send_command_ack(
                ws, msg["command_id"], "refused")
            continue
        try:
            clock_guard = await asyncio.get_running_loop().run_in_executor(
                _SCORING_EXECUTOR,
                _SCORING_TRANSPORT.observe_wall_clock)
        except Exception:
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason="wall_clock_guard_unavailable")
            await _send_command_ack(
                ws, msg["command_id"], "refused")
            continue
        try:
            claim, prior = await asyncio.get_running_loop().run_in_executor(
                _SCORING_EXECUTOR,
                _SCORING_TRANSPORT.begin_command,
                msg["command_id"], cmd_type, lane, msg)
        except Exception:
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason="ledger_write_error")
            await _send_command_ack(
                ws, msg["command_id"], "refused")
            continue
        if claim == "completed":
            original = (
                prior.get("status") if isinstance(prior, dict) else "failed")
            # A completed epoch sync is an idempotent state assignment, not an
            # actuation. Re-apply it so a process restart can restore the
            # in-memory epoch even though the durable receipt survives.
            if (cmd_type == Msg.SCORING_EPOCH_SYNC
                    and original == "completed"):
                _scoring_epochs[lane] = msg["scoring_epoch"]
            _record_command_transport(
                msg, "info", "duplicate",
                status="duplicate", original_status=original)
            await _send_command_ack(
                ws, msg["command_id"], "duplicate",
                original_status=original)
            continue
        if claim in ("ambiguous", "collision"):
            status = "ambiguous" if claim == "ambiguous" else "refused"
            _record_command_transport(
                msg, "fault", status,
                status=status, reason=f"ledger_{claim}")
            await _send_command_ack(
                ws, msg["command_id"], status)
            continue
        if (cmd_type in _ACTUATING_COMMAND_TYPES
                and clock_guard["anomaly_latched"]):
            try:
                await _complete_command(msg, "refused")
            except Exception:
                _record_command_transport(
                    msg, "fault", "ambiguous",
                    status="ambiguous",
                    reason="clock_refusal_completion_ledger_error")
                await _send_command_ack(
                    ws, msg["command_id"], "ambiguous")
                continue
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason="wall_clock_anomaly_latched",
                high_water_epoch=clock_guard["high_water_epoch"],
                observed_epoch=clock_guard["observed_epoch"])
            await _send_command_ack(
                ws, msg["command_id"], "refused")
            continue

        prior_epoch = _scoring_epochs[lane]
        next_epoch = prior_epoch
        if cmd_type == Msg.OPEN_LANE:
            epoch = msg.get("scoring_epoch")
            if (not isinstance(epoch, str) or not epoch.strip()
                    or len(epoch) > 200):
                log.error(
                    f"OPEN_LANE for lane {lane} lacks a valid scoring_epoch; "
                    "command refused")
                await _complete_command(msg, "refused")
                await _send_command_ack(
                    ws, msg["command_id"], "refused")
                continue
            next_epoch = epoch
        elif cmd_type == Msg.CLOSE_LANE:
            if msg.get("scoring_epoch") is not None:
                log.error(
                    f"CLOSE_LANE for lane {lane} has a non-null "
                    "scoring_epoch; command refused")
                await _complete_command(msg, "refused")
                await _send_command_ack(
                    ws, msg["command_id"], "refused")
                continue
            next_epoch = None
        elif cmd_type == Msg.SCORING_EPOCH_SYNC:
            epoch = msg.get("scoring_epoch")
            if (epoch is not None
                    and (not isinstance(epoch, str)
                         or not epoch.strip() or len(epoch) > 200)):
                await _complete_command(msg, "refused")
                await _send_command_ack(
                    ws, msg["command_id"], "refused")
                continue
            _scoring_epochs[lane] = epoch
            try:
                await _complete_command(msg, "completed")
            except Exception as exc:
                _record_command_transport(
                    msg, "fault", "ambiguous",
                    status="ambiguous",
                    reason="completion_ledger_error",
                    error=type(exc).__name__)
                try:
                    await _send_command_ack(
                        ws, msg["command_id"], "ambiguous")
                except Exception:
                    _record_command_transport(
                        msg, "fault", "ack_indeterminate",
                        status="ambiguous", reason="ack_send_failed")
            else:
                _record_command_transport(
                    msg, "info", "completed", status="completed")
                try:
                    await _send_command_ack(
                        ws, msg["command_id"], "completed")
                except Exception:
                    _record_command_transport(
                        msg, "fault", "ack_indeterminate",
                        status="completed", reason="ack_send_failed")
            continue

        # NEVER queued: executed the moment the frame is read. And because the
        # recv loop below only enqueues pulses (never awaits one), the frame
        # IS read immediately even mid-pulse — review #7.
        if cmd_type in (Msg.POWER_ON, Msg.POWER_OFF):
            try:
                await _execute_command(cmd_type, lane, msg)
            except Exception as exc:
                _record_command_transport(
                    msg, "fault", "ambiguous",
                    status="ambiguous", error=type(exc).__name__,
                    reason="actuation_exception")
                try:
                    await _send_command_ack(
                        ws, msg["command_id"], "ambiguous")
                except Exception:
                    _record_command_transport(
                        msg, "fault", "ack_indeterminate",
                        status="ambiguous", reason="ack_send_failed")
            else:
                try:
                    await _complete_command(msg, "completed")
                except Exception as exc:
                    _record_command_transport(
                        msg, "fault", "ambiguous",
                        status="ambiguous",
                        reason="completion_ledger_error",
                        error=type(exc).__name__)
                    try:
                        await _send_command_ack(
                            ws, msg["command_id"], "ambiguous")
                    except Exception:
                        _record_command_transport(
                            msg, "fault", "ack_indeterminate",
                            status="ambiguous", reason="ack_send_failed")
                else:
                    _record_command_transport(
                        msg, "info", "completed", status="completed")
                    try:
                        await _send_command_ack(
                            ws, msg["command_id"], "completed")
                    except Exception:
                        _record_command_transport(
                            msg, "fault", "ack_indeterminate",
                            status="completed",
                            reason="ack_send_failed")
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
            q.put_nowait((cmd_type, lane, msg, ws, prior_epoch))
            # Epoch admission follows queue admission.  A rejected command
            # must never change which scoring generation sensor events carry.
            if cmd_type in (Msg.OPEN_LANE, Msg.CLOSE_LANE):
                _scoring_epochs[lane] = next_epoch
        except asyncio.QueueFull:
            log.error(f"command queue full ({CMD_QUEUE_MAX} pending) — REJECTING "
                      f"{cmd_type} for lane {lane} (runaway sender? a backlog "
                      f"must not bank relay motion)")
            await _complete_command(msg, "refused")
            _record_command_transport(
                msg, "fault", "refused",
                status="refused", reason="command_queue_full")
            await _send_command_ack(
                ws, msg["command_id"], "refused")

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
    _disable_scoring_callbacks()
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
                session_id = uuid.uuid4().hex
                log.info(f"Connected. Sending hello (lanes={LANES}, "
                         f"protocol_version={PROTOCOL_VERSION}, "
                         f"auth={'per-node' if HELLO_AUTH_TOKEN else 'none'}).")
                hello_fields = dict(node=NODE_ID, lanes=LANES,
                                    protocol_version=PROTOCOL_VERSION,
                                    **(await _scoring_status_payload(
                                        session_id, 0)))
                if HELLO_AUTH_TOKEN:
                    hello_fields["token"] = HELLO_AUTH_TOKEN
                await ws.send(encode(Msg.HELLO, **hello_fields))
                await _run_connection(ws, session_id)
        except asyncio.CancelledError:
            raise  # let main()'s finally run cleanup
        except Exception as e:
            log.warning(f"Connection lost: {e}. Retrying in 5s...")
            await asyncio.sleep(5)


async def _run_connection(ws, session_id):
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
    ack_state = {
        "session_id": session_id,
        "sent_seq": 0,
        "acked_seq": -1,
        "event_ack_futures": {},
    }
    tasks = [asyncio.create_task(heartbeat_loop(ws, ack_state)),
             asyncio.create_task(event_sender(ws, ack_state)),
             asyncio.create_task(command_handler(ws, ack_state))]
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
from diag_events import (
    DiagWriter as _DiagWriter,
    make_event as _make_event,
    stamp_delivery as _stamp_diag_delivery,
)

CAM_HEALTH_ENV = "WSL_CAM_HEALTH"                # default ON in camera mode
CAM_HEALTH_POLL_ENV = "WSL_CAM_HEALTH_POLL_S"    # poll cadence (default 300 s)
CAM_SELFCHECK_MIN_ENV = "WSL_CAM_SELFCHECK_MIN_S"  # min gap between empty-ref checks
CAM_CAPTURE_TIMEOUT_ENV = "WSL_CAM_CAPTURE_TIMEOUT_S"  # any cv2 op (default 10s)
_FALSEY_ENV = ("0", "false", "no", "off", "")

_DIAG_WRITER = None          # started in main() for every Track-A mode
_cam_selfcheck_last = 0.0    # monotonic time of the last empty-ref self-check
_cam_health_warned = False
_TRACK_A_DIAG_PENDING_MAX = 128
_TRACK_A_DIAG_LEDGER_MAX_BYTES = 3 * 1024 * 1024
_TRACK_A_DIAG_FUTURE_TOLERANCE_S = 300.0
_SQLITE_INT64_MAX = (1 << 63) - 1
_diag_pending = {}
_diag_pending_lock = threading.Lock()
_diag_condition_lock = threading.RLock()
_diag_pending_sequence = 0
_diag_pending_drops = 0
_diag_pending_drops_reported = {}
_diag_delivered_conditions = set()
_diag_delivered_condition_families = {}
_diag_condition_pending_alerts = {}
_diag_condition_pending_clears = {}
_diag_condition_clear_intents = {}
_diag_condition_realert_intents = {}
_diag_condition_ledger_loaded = False
_diag_condition_ledger_error = False
_diag_start_ack_pending = set()


class _StableDiagEvent:
    """Attribute-compatible diagnostic row with a restart-stable identity."""

    __slots__ = ("_row",)

    def __init__(self, row):
        self._row = dict(row)

    def __getattr__(self, name):
        try:
            return self._row[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self):
        return dict(self._row)

    def __repr__(self):
        return (
            f"_StableDiagEvent(L{self.lane_id} {self.severity} "
            f"{self.event_type} {self.code or ''} @ {self.ts_utc})")


def _cam_env_on(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in _FALSEY_ENV


def _cam_env_float(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return float(default)


def _diag_priority(event, *, clearing=False):
    """Severity-first bounded-retention order for Track-A diagnostics."""
    if clearing:
        # Once an alert reached the desk, its recovery is a delivery
        # obligation rather than disposable informational telemetry.
        return 5
    return {"info": 0, "warn": 2, "fault": 4}.get(
        getattr(event, "severity", None), 0)


def _diag_condition_ledger_path():
    return os.path.join(
        os.path.dirname(_health_drop_path()),
        "track_a_condition_delivery.json")


def _diag_condition_key_valid(group):
    return (
        isinstance(group, (list, tuple))
        and 2 <= len(group) <= 8
        and isinstance(group[-1], int)
        and not isinstance(group[-1], bool)
        and group[-1] in LANES
        and all(
            value is None
            or (isinstance(value, str) and 0 < len(value) <= 160)
            or (isinstance(value, int) and not isinstance(value, bool))
            for value in group[:-1])
    )


def _diag_event_row_valid(row, *, group=None):
    """Strictly validate one restart-replayable diagnostic row."""
    if not isinstance(row, dict):
        return False
    if set(row) != {
            "ts_utc", "ts_mono", "lane_id", "severity", "event_type",
            "code", "detail", "source_id", "boot_id", "seq"}:
        return False
    try:
        stamp = str(row["ts_utc"])
        parsed = datetime.fromisoformat(
            stamp[:-1] + "+00:00" if stamp.endswith(("Z", "z")) else stamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        if ((parsed.astimezone(timezone.utc) - datetime.now(timezone.utc))
                .total_seconds() > _TRACK_A_DIAG_FUTURE_TOLERANCE_S):
            return False
        mono = float(row["ts_mono"])
        lane = row["lane_id"]
        seq = row["seq"]
        if not math.isfinite(mono) or mono < 0:
            return False
        if (not isinstance(lane, int) or isinstance(lane, bool)
                or lane not in LANES):
            return False
        if (not isinstance(seq, int) or isinstance(seq, bool)
                or not 0 < seq <= _SQLITE_INT64_MAX):
            return False
        if not isinstance(row["source_id"], str) \
                or not 0 < len(row["source_id"]) <= 120:
            return False
        if not isinstance(row["boot_id"], str) \
                or not 0 < len(row["boot_id"]) <= 80:
            return False
        if row["code"] is not None and (
                not isinstance(row["code"], str)
                or len(row["code"]) > 120):
            return False
        if not isinstance(row["detail"], dict):
            return False
        # Construction re-applies the contract vocabulary and type gates.
        validated = _make_event(
            lane, row["severity"], row["event_type"],
            code=row["code"], detail=row["detail"],
            now=lambda: mono, ts_utc=stamp)
        if validated.to_dict() != {
                key: row[key] for key in (
                    "ts_utc", "ts_mono", "lane_id", "severity",
                    "event_type", "code", "detail")}:
            return False
        if group is not None and int(group[-1]) != lane:
            return False
        # Keep the atomically rewritten ledger bounded even for hostile input.
        return len(json.dumps(
            row, ensure_ascii=True, separators=(",", ":"))) <= 16384
    except Exception:
        return False


def _diag_condition_family_valid(event_type, code, lane):
    if (not isinstance(event_type, str)
            or not 0 < len(event_type) <= 80
            or event_type == "recovered"
            or (
                code is not None
                and (
                    not isinstance(code, str)
                    or len(code) > 120))):
        return False
    try:
        _make_event(
            int(lane), "warn", event_type, code=code, detail={},
            now=lambda: 0.0,
            ts_utc="2000-01-01T00:00:00.000+00:00")
        return True
    except Exception:
        return False


def _stable_diag_event(severity, event_type, code, detail, *, lane,
                       ts_utc=None, ts_mono=None):
    now = None if ts_mono is None else (lambda: float(ts_mono))
    event = _make_event(
        int(lane), severity, event_type, code=code, detail=detail,
        now=now, ts_utc=ts_utc)
    row = event.to_dict()
    _stamp_diag_delivery(row)
    if not _diag_event_row_valid(row):
        raise ValueError("failed to build restart-stable diagnostic row")
    return _StableDiagEvent(row)


def _diag_local_row_receipt_status(row):
    """Classify one exact stable identity in the bounded retained JSONL."""
    if not _diag_event_row_valid(row):
        return "ambiguous"
    try:
        import health_drop
        return health_drop.delivery_receipt_status(
            os.path.dirname(_diag_condition_ledger_path()), row)
    except Exception:
        return "ambiguous"


def _diag_local_row_durable(row):
    """Return whether the complete exact row reached retained JSONL."""
    return _diag_local_row_receipt_status(row) == "exact"


def _persist_diag_condition_ledger():
    """Atomically preserve condition phases and stable replay rows."""
    global _diag_condition_ledger_error
    if not _diag_condition_ledger_loaded:
        return True
    active = sorted(
        (
            {
                "group": list(group),
                "event_type":
                    _diag_delivered_condition_families.get(group, (None,))[0],
                "code":
                    _diag_delivered_condition_families.get(
                        group, (None, None))[1],
            }
            for group in _diag_delivered_conditions
        ),
        key=lambda item: repr(item["group"]))
    pending_alerts = sorted(
        (
            {"group": list(group), "event": dict(row)}
            for group, row in _diag_condition_pending_alerts.items()
        ),
        key=lambda item: repr(item["group"]))
    pending_clears = sorted(
        (
            {"group": list(group), "event": dict(row)}
            for group, row in _diag_condition_pending_clears.items()
        ),
        key=lambda item: repr(item["group"]))
    groups = (
        set(_diag_delivered_conditions)
        | set(_diag_condition_pending_alerts)
        | set(_diag_condition_pending_clears))
    valid_entries = all(
        _diag_condition_key_valid(entry["group"])
        and _diag_event_row_valid(
            entry["event"], group=entry["group"])
        for entry in pending_alerts + pending_clears)
    if (len(groups) > _TRACK_A_DIAG_PENDING_MAX
            or any(
                not _diag_condition_key_valid(entry["group"])
                or not _diag_condition_family_valid(
                    entry["event_type"], entry["code"],
                    entry["group"][-1])
                for entry in active)
            or not valid_entries):
        _diag_condition_ledger_error = True
        return False
    try:
        import health_drop
        ok = health_drop.write_delivery_ledger(
            _diag_condition_ledger_path(), {
                "version": 3,
                "active": active,
                "pending_alerts": pending_alerts,
                "pending_clears": pending_clears,
            })
    except Exception:
        ok = False
    _diag_condition_ledger_error = not bool(ok)
    return bool(ok)


def _load_diag_condition_ledger():
    """Load and reconcile the Track-A condition write-ahead ledger."""
    global _diag_condition_ledger_loaded, _diag_condition_ledger_error
    with _diag_condition_lock:
        try:
            with open(_diag_condition_ledger_path(), "rb") as source:
                raw = source.read(_TRACK_A_DIAG_LEDGER_MAX_BYTES + 1)
            payload = strict_json_loads(
                raw,
                max_bytes=_TRACK_A_DIAG_LEDGER_MAX_BYTES,
                max_depth=20,
                max_nodes=100000)
            if not isinstance(payload, dict) or payload.get("version") != 3:
                payload = None
        except FileNotFoundError:
            payload = {}
        except Exception:
            payload = None
        if payload == {}:
            active = []
            pending_alerts = []
            pending_clears = []
        elif isinstance(payload, dict):
            active = payload.get("active")
            pending_alerts = payload.get("pending_alerts")
            pending_clears = payload.get("pending_clears")
            if (not isinstance(active, list)
                    or not isinstance(pending_alerts, list)
                    or not isinstance(pending_clears, list)):
                payload = None
        if payload is None:
            with _diag_pending_lock:
                _diag_delivered_conditions.clear()
                _diag_delivered_condition_families.clear()
                _diag_condition_pending_alerts.clear()
                _diag_condition_pending_clears.clear()
            _diag_condition_ledger_loaded = True
            _diag_condition_ledger_error = True
            return False
        active_families = {}
        alert_rows = {}
        clear_rows = {}
        valid = True
        for entry in active:
            if (not isinstance(entry, dict)
                    or set(entry) != {"group", "event_type", "code"}):
                valid = False
                break
            raw_group = entry["group"]
            event_type = entry["event_type"]
            code = entry["code"]
            if (not _diag_condition_key_valid(raw_group)
                    or not _diag_condition_family_valid(
                        event_type, code, raw_group[-1])):
                valid = False
                break
            group = tuple(raw_group)
            if group in active_families:
                valid = False
                break
            active_families[group] = (event_type, code)
        for entries, destination in (
                (pending_alerts, alert_rows),
                (pending_clears, clear_rows)):
            for entry in entries:
                if not isinstance(entry, dict) \
                        or set(entry) != {"group", "event"}:
                    valid = False
                    break
                group = entry["group"]
                row = entry["event"]
                if (not _diag_condition_key_valid(group)
                        or not _diag_event_row_valid(row, group=group)
                        or tuple(group) in destination):
                    valid = False
                    break
                destination[tuple(group)] = dict(row)
            if not valid:
                break
        all_groups = set(active_families) | set(alert_rows) | set(clear_rows)
        if (len(all_groups) > _TRACK_A_DIAG_PENDING_MAX
                or set(active_families) & set(alert_rows)
                or not set(clear_rows).issubset(set(active_families))):
            valid = False
        if not valid:
            with _diag_pending_lock:
                _diag_delivered_conditions.clear()
                _diag_delivered_condition_families.clear()
                _diag_condition_pending_alerts.clear()
                _diag_condition_pending_clears.clear()
            _diag_condition_ledger_loaded = True
            _diag_condition_ledger_error = True
            return False
        active_set = set(active_families)
        receipt_statuses = {
            ("alert", group): _diag_local_row_receipt_status(row)
            for group, row in alert_rows.items()
        }
        receipt_statuses.update({
            ("clear", group): _diag_local_row_receipt_status(row)
            for group, row in clear_rows.items()
        })
        if any(
                status not in {"exact", "absent"}
                for status in receipt_statuses.values()):
            with _diag_pending_lock:
                _diag_delivered_conditions.clear()
                _diag_delivered_condition_families.clear()
                _diag_condition_pending_alerts.clear()
                _diag_condition_pending_clears.clear()
            _diag_condition_ledger_loaded = True
            _diag_condition_ledger_error = True
            return False
        # A pending alert is only an intent until its stable identity appears in
        # a locally durable JSONL. This distinguishes a rejected pre-offer from
        # the crash window after fsync but before the active-phase rewrite.
        for group, row in alert_rows.items():
            if receipt_statuses[("alert", group)] == "exact":
                active_set.add(group)
                active_families[group] = (
                    row["event_type"], row.get("code"))
        # A durable pending recovery already closed the fault. Otherwise retain
        # and retry the exact same identity after restart.
        retry_clears = {}
        for group, row in clear_rows.items():
            if receipt_statuses[("clear", group)] == "exact":
                active_set.discard(group)
                active_families.pop(group, None)
            else:
                retry_clears[group] = row
        with _diag_pending_lock:
            for key in list(_diag_pending):
                if key and str(key[0]).startswith("condition_"):
                    _diag_pending.pop(key, None)
            _diag_delivered_conditions.clear()
            _diag_delivered_conditions.update(active_set)
            _diag_delivered_condition_families.clear()
            _diag_delivered_condition_families.update({
                group: active_families[group] for group in active_set
            })
            _diag_condition_pending_alerts.clear()
            _diag_condition_pending_clears.clear()
            _diag_condition_pending_clears.update(retry_clears)
        _diag_condition_ledger_loaded = True
        _diag_condition_ledger_error = False
        for group, row in retry_clears.items():
            event = _StableDiagEvent(row)
            _diag_retain(
                ("condition_clear",) + group,
                event, priority=5,
                action=("condition_clear", group))
        return _persist_diag_condition_ledger()


def _known_diag_condition_bases(prefix):
    with _diag_condition_lock:
        with _diag_pending_lock:
            groups = (
                set(_diag_delivered_conditions)
                | set(_diag_condition_pending_alerts)
                | set(_diag_condition_pending_clears))
    return {
        group[:-1] for group in groups
        if group and group[0] == prefix
    }


def _diag_apply_accept(action):
    """Commit delivery-side state after one concrete lane offer succeeds."""
    if not action:
        return
    ack = None
    followup = None
    relert = None
    kind = action[0]
    if kind in ("condition_alert", "condition_clear"):
        with _diag_condition_lock:
            with _diag_pending_lock:
                group = action[1]
                if kind == "condition_alert":
                    alert_row = _diag_condition_pending_alerts.pop(
                        group, None)
                    _diag_delivered_conditions.add(group)
                    if alert_row is not None:
                        _diag_delivered_condition_families[group] = (
                            alert_row["event_type"], alert_row.get("code"))
                    followup = _diag_condition_clear_intents.pop(
                        group, None)
                else:
                    _diag_condition_pending_clears.pop(group, None)
                    _diag_delivered_conditions.discard(group)
                    _diag_delivered_condition_families.pop(group, None)
                    _diag_condition_clear_intents.pop(group, None)
                    relert = _diag_condition_realert_intents.pop(
                        group, None)
            _persist_diag_condition_ledger()
    elif kind == "service_start":
        with _diag_pending_lock:
            (
                _, path, count, event_type, lane,
                source_id, boot_id, seq,
            ) = action
            ack = (
                path, count, event_type, lane,
                source_id, boot_id, seq,
            )
            _diag_start_ack_pending.add(ack)
    if followup is not None:
        event_type, code, detail, lane, condition = followup
        _diag_condition_clear(
            event_type, code, detail, lane=lane, condition=condition)
    if relert is not None:
        severity, event_type, code, detail, lane, condition = relert
        _diag_condition_alert(
            severity, event_type, code, detail,
            lane=lane, condition=condition)
    if ack is not None:
        _diag_retry_start_ack(ack)


def _diag_retry_start_ack(group):
    """Clear exactly one lane's durable startup row after acceptance."""
    path, count, event_type, lane, source_id, boot_id, seq = group
    try:
        import health_drop
        accepted = health_drop.acknowledge_service_start_lane(
            path, count, event_type, lane, source_id, boot_id, seq)
    except Exception:
        accepted = False
    if accepted:
        with _diag_pending_lock:
            _diag_start_ack_pending.discard(group)
    return bool(accepted)


def _diag_retry_start_acks():
    with _diag_pending_lock:
        pending = list(_diag_start_ack_pending)
    for group in pending:
        _diag_retry_start_ack(group)


def _diag_retain(pending_key, event, *, priority, action=None,
                 replace_pending=False):
    """Retain one rejected immutable event without growing without bound."""
    global _diag_pending_sequence, _diag_pending_drops
    if pending_key is None:
        return False
    with _diag_pending_lock:
        existing = _diag_pending.get(pending_key)
        if existing is not None and not replace_pending:
            return True
        if existing is None and len(_diag_pending) >= \
                _TRACK_A_DIAG_PENDING_MAX:
            minimum = min(
                item["priority"] for item in _diag_pending.values())
            if priority <= minimum:
                _diag_pending_drops += 1
                log.error(
                    "Track-A diagnostic pending overflow dropped %s",
                    pending_key)
                return False
            victim = next(
                key for key, item in _diag_pending.items()
                if item["priority"] == minimum)
            _diag_pending.pop(victim, None)
            _diag_pending_drops += 1
            log.error(
                "Track-A diagnostic pending overflow evicted %s", victim)
        _diag_pending_sequence += 1
        _diag_pending[pending_key] = {
            "event": event,
            "priority": int(priority),
            "action": action,
            "sequence": _diag_pending_sequence,
        }
    return True


def _diag_writer_accept(writer, event, *, durable=False):
    if writer is None:
        return False
    if durable:
        offer = getattr(writer, "emit_durable", None)
        if callable(offer):
            thread = getattr(writer, "_thread", None)
            timeout = 2.0 if thread is not None and thread.is_alive() else 0.0
            return bool(offer(event, timeout=timeout))
        return False
    offer = getattr(writer, "emit", None)
    return bool(callable(offer) and offer(event))


def _diag_writer_has_inflight(writer, event):
    """Best-effort proof that a timed-out durable receipt still owns `event`."""
    lock = getattr(writer, "_durable_lock", None)
    inflight = getattr(writer, "_durable_inflight", None)
    if lock is None or not isinstance(inflight, dict):
        return False
    try:
        with lock:
            return id(event) in inflight
    except Exception:
        # Unknown must be treated as in-flight: replacing a row whose prior
        # receipt later fsyncs would make restart reconciliation ambiguous.
        return True


def _diag_offer_prebuilt(event, *, pending_key=None, retain=False,
                         priority=None, action=None,
                         replace_pending=False):
    """Offer one already-stamped event and retain it when explicitly asked."""
    existing = None
    if pending_key is not None and not replace_pending:
        with _diag_pending_lock:
            existing = _diag_pending.get(pending_key)
        if existing is not None:
            event = existing["event"]
            action = existing.get("action")
            priority = existing["priority"]
    accepted = False
    try:
        w = _DIAG_WRITER
        durable = bool(retain)
        accepted = _diag_writer_accept(w, event, durable=durable)
    except Exception:
        log.debug("camera diag emit swallowed", exc_info=True)
    if accepted:
        if pending_key is not None:
            with _diag_pending_lock:
                current = _diag_pending.get(pending_key)
                if (current is None or current.get("event") is event
                        or replace_pending):
                    _diag_pending.pop(pending_key, None)
        _diag_apply_accept(action)
        return True
    if retain:
        _diag_retain(
            pending_key, event,
            priority=(
                _diag_priority(event) if priority is None else priority),
            action=action, replace_pending=replace_pending)
    return False


def _diag_pump_pending(*, include_conditions=True):
    """Retry retained events in safety/causal order; never blocks on capacity."""
    with _diag_pending_lock:
        pending = sorted(
            (
                item for item in _diag_pending.items()
                if include_conditions
                or not str(item[0][0]).startswith("condition_")
            ),
            key=lambda pair: (
                -pair[1]["priority"], pair[1]["sequence"]))
    accepted = 0
    for key, item in pending:
        action = item.get("action")
        condition_action = bool(
            action and action[0] in (
                "condition_alert", "condition_clear"))
        lock = _diag_condition_lock if condition_action else None
        if lock is not None:
            lock.acquire()
        try:
            with _diag_pending_lock:
                if _diag_pending.get(key) is not item:
                    continue
            if condition_action and action[0] == "condition_alert":
                # Never expose an alert unless its stable identity/intent is
                # already crash-recoverable in the local write-ahead ledger.
                if not _persist_diag_condition_ledger():
                    continue
            elif condition_action and action[0] == "condition_clear":
                # The active marker and exact recovery row must likewise
                # survive the fsync-before-ledger-rewrite crash window.
                if not _persist_diag_condition_ledger():
                    continue
            try:
                ok = _diag_writer_accept(
                    _DIAG_WRITER, item["event"], durable=True)
            except Exception:
                ok = False
            if not ok:
                continue
            with _diag_pending_lock:
                current = _diag_pending.get(key)
                if current is not item:
                    continue
                _diag_pending.pop(key, None)
            _diag_apply_accept(action)
            accepted += 1
        finally:
            if lock is not None:
                lock.release()
    _diag_retry_start_acks()
    return accepted


def _diag_report_pending_drops():
    """Promote bounded-store loss without recursively retaining the report."""
    global _diag_pending_drops_reported
    with _diag_pending_lock:
        total = _diag_pending_drops
        reported = dict(_diag_pending_drops_reported)
        pending_count = len(_diag_pending)
    if total <= 0:
        return
    for lane in sorted(set(LANES)):
        prior = int(reported.get(lane, 0))
        if total <= prior:
            continue
        if _diag_emit(
                "warn", "diag_drops", code="track_a_pending_overflow",
                detail={
                    "new": total - prior,
                    "total": total,
                    "pending": pending_count,
                    "capacity": _TRACK_A_DIAG_PENDING_MAX,
                },
                lane=lane):
            with _diag_pending_lock:
                _diag_pending_drops_reported[lane] = total


def _diag_emit(severity, event_type, code=None, detail=None, *, lane=None,
               retain=False, pending_key=None, priority=None,
               accept_action=None, replace_pending=False,
               ts_utc=None, ts_mono=None):
    """Enqueue one diagnostic and return concrete queue acceptance.

    Retention is opt-in: high-rate breadcrumbs keep their old cheap behavior,
    while one-shot incidents and state transitions can preserve their original
    timestamps until the writer accepts them.
    """
    try:
        target = min(LANES) if lane is None else int(lane)
        now = None if ts_mono is None else (lambda: float(ts_mono))
        event = _make_event(
            target, severity, event_type, code=code, detail=detail,
            now=now, ts_utc=ts_utc)
        return _diag_offer_prebuilt(
            event, pending_key=pending_key, retain=retain,
            priority=priority, action=accept_action,
            replace_pending=replace_pending)
    except Exception:
        log.debug("camera diag emit swallowed", exc_info=True)
        return False


def _diag_condition_alert(severity, event_type, code, detail, *,
                          lane, condition):
    with _diag_condition_lock:
        group = tuple(condition) + (int(lane),)
        alert_key = ("condition_alert",) + group
        clear_key = ("condition_clear",) + group
        pending_clear = None
        with _diag_pending_lock:
            pending_clear = _diag_pending.get(clear_key)
            already_delivered = group in _diag_delivered_conditions
        if pending_clear is not None:
            # A recovery receipt can still complete after timeout. Serialize a
            # recurrence behind it instead of cancelling an in-flight clear
            # and risking a false-green desk state.
            if _diag_offer_prebuilt(
                    pending_clear["event"], pending_key=clear_key,
                    retain=True, priority=5,
                    action=("condition_clear", group)):
                with _diag_pending_lock:
                    already_delivered = group in _diag_delivered_conditions
            else:
                _diag_condition_realert_intents[group] = (
                    severity, event_type, code, detail, int(lane),
                    tuple(condition))
                return False
        if already_delivered:
            return True
        with _diag_pending_lock:
            row = _diag_condition_pending_alerts.get(group)
            pending_item = _diag_pending.get(alert_key)
        if row is not None:
            event = (
                pending_item["event"] if pending_item is not None
                else _StableDiagEvent(row))
            candidate_fields = {
                "severity": severity,
                "event_type": event_type,
                "code": code,
                "detail": detail or {},
            }
            prior_fields = {
                key: row.get(key) for key in candidate_fields
            }
            if (candidate_fields != prior_fields
                    and not _diag_writer_has_inflight(_DIAG_WRITER, event)):
                # The first offer was definitively rejected. Preserve the most
                # recent truth (for example stale -> missing) before retrying.
                event = _stable_diag_event(
                    severity, event_type, code, detail, lane=lane)
                row = event.to_dict()
                with _diag_pending_lock:
                    _diag_condition_pending_alerts[group] = row
                _diag_retain(
                    alert_key, event, priority=_diag_priority(event),
                    action=("condition_alert", group),
                    replace_pending=True)
        else:
            event = _stable_diag_event(
                severity, event_type, code, detail, lane=lane)
            row = event.to_dict()
            with _diag_pending_lock:
                _diag_condition_pending_alerts[group] = row
        _diag_retain(
            alert_key, event, priority=_diag_priority(event),
            action=("condition_alert", group))
        if not _persist_diag_condition_ledger():
            log.error(
                "Track-A condition ledger write failed before alert %r",
                group)
            return False
        return _diag_offer_prebuilt(
            event, pending_key=alert_key, retain=True,
            priority=_diag_priority(event),
            action=("condition_alert", group))


def _diag_condition_clear(event_type, code, detail, *, lane, condition):
    with _diag_condition_lock:
        group = tuple(condition) + (int(lane),)
        alert_key = ("condition_alert",) + group
        clear_key = ("condition_clear",) + group
        pending_item = None
        with _diag_pending_lock:
            pending_item = _diag_pending.get(alert_key)
            pending_alert_row = _diag_condition_pending_alerts.get(group)
        if pending_item is None and pending_alert_row is not None:
            pending_item = {
                "event": _StableDiagEvent(pending_alert_row),
                "priority": 4,
                "action": ("condition_alert", group),
            }
            _diag_retain(
                alert_key, pending_item["event"],
                priority=_diag_priority(pending_item["event"]),
                action=pending_item["action"])
        if pending_item is not None:
            # An emit_durable timeout may still be in flight. Resolve that
            # receipt before deciding whether recovery evidence is required.
            if not _persist_diag_condition_ledger() \
                    or not _diag_offer_prebuilt(
                        pending_item["event"], pending_key=alert_key,
                        retain=True, priority=pending_item["priority"],
                        action=("condition_alert", group)):
                with _diag_pending_lock:
                    still_pending = group in _diag_condition_pending_alerts
                if still_pending:
                    _diag_condition_clear_intents[group] = (
                        event_type, code, detail, int(lane),
                        tuple(condition))
                    return False
        with _diag_pending_lock:
            was_delivered = group in _diag_delivered_conditions
            delivered_family = _diag_delivered_condition_families.get(group)
            clear_row = _diag_condition_pending_clears.get(group)
            pending_clear = _diag_pending.get(clear_key)
        if not was_delivered:
            return True
        if delivered_family is None:
            global _diag_condition_ledger_error
            _diag_condition_ledger_error = True
            log.error(
                "Track-A active condition lacks exact fault family: %r",
                group)
            return False
        recovery_detail = dict(detail or {})
        recovery_detail["recovered_event_type"] = delivered_family[0]
        recovery_detail["recovered_code"] = delivered_family[1]
        if clear_row is not None:
            recovery = (
                pending_clear["event"] if pending_clear is not None
                else _StableDiagEvent(clear_row))
        else:
            recovery = _stable_diag_event(
                "info", event_type, code, recovery_detail, lane=lane)
            clear_row = recovery.to_dict()
            with _diag_pending_lock:
                _diag_condition_pending_clears[group] = clear_row
        _diag_retain(
            clear_key, recovery, priority=5,
            action=("condition_clear", group))
        if not _persist_diag_condition_ledger():
            log.error(
                "Track-A condition ledger write failed before recovery %r",
                group)
            return False
        return _diag_offer_prebuilt(
            recovery, pending_key=clear_key, retain=True, priority=5,
            action=("condition_clear", group))


def _diag_emit_lanes(severity, event_type, code=None, detail=None, *,
                     lanes=None, retain=False, pending_key=None,
                     priority=None, condition=None, clear_condition=False,
                     accept_action=None, replace_pending=False,
                     ts_utc=None, ts_mono=None):
    """Emit a pair-wide fact and return acceptance for each concrete lane."""
    results = {}
    for lane in sorted(set(lanes or LANES)):
        if condition is not None:
            if clear_condition:
                results[lane] = _diag_condition_clear(
                    event_type, code, detail, lane=lane,
                    condition=condition)
            else:
                results[lane] = _diag_condition_alert(
                    severity, event_type, code, detail, lane=lane,
                    condition=condition)
            continue
        lane_key = None if pending_key is None \
            else tuple(pending_key) + (int(lane),)
        lane_action = None if accept_action is None \
            else tuple(accept_action) + (int(lane),)
        results[lane] = _diag_emit(
            severity, event_type, code=code, detail=detail, lane=lane,
            retain=retain, pending_key=lane_key, priority=priority,
            accept_action=lane_action,
            replace_pending=replace_pending,
            ts_utc=ts_utc, ts_mono=ts_mono)
    return results


async def _record_track_a_service_start():
    """Persist and deliver Track-A startup facts before fallible subsystems.

    ``health_drop`` keeps exact pre-stamped per-lane rows across process death.
    Each accepted lane is acknowledged independently, so a crash cannot
    rebuild an already accepted lane under a new delivery identity.
    """
    import health_drop
    starts_path = os.path.join(
        os.path.dirname(_health_drop_path()),
        "lane_node_service_starts.json")
    facts = await asyncio.to_thread(
        health_drop.record_service_start, starts_path,
        track_delivery=True)
    pending = list(facts.get("pending_events") or ())
    # Loop faults first: a tiny recovered queue must preserve the condition
    # that can precede systemd StartLimit lockout ahead of info provenance.
    obligations = []
    for item in pending:
        if item.get("service_restart_loop_pending"):
            obligations.append(("service_restart_loop", item))
    for item in pending:
        if item.get("service_restart_pending"):
            obligations.append(("service_restart", item))
    # No event derived from this update may be offered unless the counter and
    # all prior obligations were read and atomically committed.
    if facts.get("persisted"):
        for event_type, item in obligations:
            count = int(item["count"])
            started_epoch = float(item["started_at_epoch"])
            started_mono = float(item["started_at_monotonic"])
            ts_utc = datetime.fromtimestamp(
                started_epoch, timezone.utc).isoformat(
                    timespec="milliseconds")
            detail = {
                "count": count,
                "started_at_epoch": started_epoch,
                "starts_in_window": int(item["starts_in_window"]),
                "window_s": float(item["window_s"]),
                "threshold": int(item["threshold"]),
                "restart_loop": bool(item["restart_loop"]),
                "replayed_start_evidence": count != facts.get("count"),
            }
            if event_type == "service_restart_loop":
                severity = "fault"
                code = "lane_node"
                priority = 4
            else:
                severity = "info"
                code = "lane_node_start"
                priority = 0
            delivery_field = f"{event_type}_deliveries"
            rows = item.get(delivery_field)
            if rows is None:
                prepared = [
                    _stable_diag_event(
                        severity, event_type, code, detail, lane=lane,
                        ts_utc=ts_utc, ts_mono=started_mono).to_dict()
                    for lane in sorted(set(LANES))
                ]
                rows = await asyncio.to_thread(
                    health_drop.prepare_service_start_deliveries,
                    starts_path, count, event_type, prepared)
            if rows is not None and (
                    any(row.get("code") != code for row in rows)):
                # A cross-service WAL must never be reinterpreted as Track-A
                # evidence. Exact destinations/acked-lane conservation is
                # validated inside health_drop before rows reach this point.
                rows = None
            if rows is None:
                await asyncio.to_thread(
                    _diag_emit_lanes,
                    "warn", "diag_storage_error",
                    code="service_start_delivery_prepare",
                    detail={
                        "count": count,
                        "event_type": event_type,
                        "requires_manual_reconciliation": True,
                    },
                    retain=True,
                    pending_key=(
                        "incident", "service_start_delivery_prepare",
                        count, event_type))
                continue
            for row in rows:
                if not _diag_event_row_valid(row):
                    log.error(
                        "Track-A rejected invalid durable service-start row "
                        "count=%s type=%s", count, event_type)
                    continue
                event = _StableDiagEvent(row)
                lane = int(row["lane_id"])
                action = (
                    "service_start", starts_path, count, event_type, lane,
                    row["source_id"], row["boot_id"], row["seq"],
                )
                # emit_durable() fsyncs the exact row before returning.  If
                # power failed in the following state-file acknowledgement
                # window, reconcile that durable receipt instead of offering
                # even an idempotent duplicate on restart.
                receipt_status = _diag_local_row_receipt_status(row)
                if receipt_status == "exact":
                    await asyncio.to_thread(_diag_apply_accept, action)
                    continue
                if receipt_status != "absent":
                    await asyncio.to_thread(
                        _diag_emit_lanes,
                        "warn", "diag_storage_error",
                        code="service_start_receipt_" + receipt_status,
                        detail={
                            "count": count,
                            "event_type": event_type,
                            "lane": lane,
                            "requires_manual_reconciliation": True,
                        },
                        lanes=[lane], retain=True,
                        pending_key=(
                            "incident", "service_start_receipt",
                            count, event_type, lane))
                    continue
                await asyncio.to_thread(
                    _diag_offer_prebuilt, event,
                    pending_key=(
                        "service_start", starts_path, count,
                        event_type, lane),
                    retain=True, priority=priority, action=action)
        await asyncio.to_thread(_diag_retry_start_acks)
    if facts.get("pending_delivery_overflow"):
        await asyncio.to_thread(
            _diag_emit_lanes,
            "fault", "diag_drops", code="service_start_pending_overflow",
            detail={
                "dropped": int(facts["pending_delivery_overflow"]),
                "capacity": 128,
                "requires_manual_reconciliation": True,
            },
            retain=True,
            pending_key=(
                "incident", "service_start_pending_overflow",
                int(facts.get("count", 0))))
    if not facts.get("persisted"):
        await asyncio.to_thread(
            _diag_emit_lanes,
            "warn", "diag_storage_error",
            code="service_start_counter", detail=facts,
            retain=True,
            pending_key=(
                "incident", "service_start_counter",
                int(facts.get("count", 0))))
    return facts


def _drain_track_a_diagnostics(writer):
    """Stop replay, then persist every bounded Track-A retry locally."""
    _diag_retry_start_acks()
    if writer is None:
        with _diag_pending_lock:
            return len(_diag_pending) + len(_diag_start_ack_pending)
    try:
        if not writer.stop():
            with _diag_pending_lock:
                return len(_diag_pending) + len(_diag_start_ack_pending)
    except Exception:
        with _diag_pending_lock:
            return len(_diag_pending) + len(_diag_start_ack_pending)
    # Interleave offers and local drains. The configured writer queue may be
    # much smaller than the bounded pending store.
    for _ in range(_TRACK_A_DIAG_PENDING_MAX + 2):
        _diag_pump_pending()
        try:
            if not writer.drain_local():
                break
            queue_empty = writer.queue.empty()
        except Exception:
            break
        with _diag_pending_lock:
            pending = len(_diag_pending) + len(_diag_start_ack_pending)
        if pending == 0 and queue_empty:
            return 0
    with _diag_pending_lock:
        return len(_diag_pending) + len(_diag_start_ack_pending)


def _foreign_relay_condition(event):
    """Return the delivery-state key paired with one foreign relay event."""
    detail = event.get("detail") or {}
    service = detail.get("from_service") or "unknown"
    event_type = event.get("event_type")
    code = event.get("code")
    if event_type == "recovered":
        recovered_type = detail.get("recovered_event_type")
        if recovered_type:
            if recovered_type == "health_drop_stale":
                return ("foreign", service, "health_drop_stale")
            return (
                "foreign", service, recovered_type,
                detail.get("recovered_code"))
        if code == "health_drop_stale":
            return ("foreign", service, "health_drop_stale")
    if event_type == "health_drop_stale":
        # stale -> missing is one unavailable-health-drop condition. If its
        # first alert is still pending, replace it with the latest truth.
        return ("foreign", service, "health_drop_stale")
    return ("foreign", service, event_type, code)


def _diag_emit_relay(event):
    """Emit a planned relay with per-lane causal delivery state."""
    severity = event["severity"]
    event_type = event["event_type"]
    code = event.get("code")
    detail = event.get("detail")
    lanes = event.get("lanes") or LANES
    condition = _foreign_relay_condition(event)
    if event_type == "fw_identity":
        return _diag_emit_lanes(
            severity, "fw_identity", code=code, detail=detail, lanes=lanes,
            condition=condition)
    elif event_type == "pi_fs_readonly":
        return _diag_emit_lanes(
            severity, "pi_fs_readonly", code=code, detail=detail, lanes=lanes,
            condition=condition)
    elif event_type == "pi_disk_low":
        return _diag_emit_lanes(
            severity, "pi_disk_low", code=code, detail=detail, lanes=lanes,
            condition=condition)
    elif event_type == "pi_thermal":
        return _diag_emit_lanes(
            severity, "pi_thermal", code=code, detail=detail, lanes=lanes,
            condition=condition)
    elif event_type == "pi_undervoltage":
        return _diag_emit_lanes(
            severity, "pi_undervoltage", code=code, detail=detail, lanes=lanes,
            condition=condition)
    elif event_type == "diag_storage_error":
        return _diag_emit_lanes(
            severity, "diag_storage_error", code=code, detail=detail,
            lanes=lanes, condition=condition)
    elif event_type == "health_drop_unhealthy":
        return _diag_emit_lanes(
            severity, "health_drop_unhealthy", code=code, detail=detail,
            lanes=lanes, condition=condition)
    elif event_type == "health_drop_stale":
        return _diag_emit_lanes(
            severity, "health_drop_stale", code=code, detail=detail,
            lanes=lanes, condition=condition)
    elif event_type == "recovered":
        return _diag_emit_lanes(
            severity, "recovered", code=code, detail=detail, lanes=lanes,
            condition=condition, clear_condition=True)
    else:
        log.warning("ignored unsupported foreign health event %r", event_type)
        return {}


def _reconcile_foreign_delivery(status):
    """Clear restart-persisted foreign faults only from a fresh snapshot."""
    try:
        import health_drop
        if not isinstance(status, dict):
            return
        service = status.get("service")
        freshness = status.get("status")
        if service not in (
                health_drop.SERVICE_CAMERA,
                health_drop.SERVICE_CONTROLLER):
            return
        if freshness != "fresh":
            # Missing/stale is absence of proof, never evidence that an
            # earlier explicit foreign fault recovered.
            return
        payload = status.get("payload")
        current = set()
        for event in health_drop.snapshot_fault_events(service, payload):
            for lane in event.get("lanes") or LANES:
                if lane in LANES:
                    current.add((
                        "foreign", service, event["event_type"],
                        event.get("code"), int(lane)))
        with _diag_condition_lock:
            with _diag_pending_lock:
                known = {
                    group for group in (
                        set(_diag_delivered_conditions)
                        | set(_diag_condition_pending_alerts)
                        | set(_diag_condition_pending_clears))
                    if len(group) >= 4
                    and group[0] == "foreign"
                    and group[1] == service
                }
                known_families = {}
                for group in known:
                    family = _diag_delivered_condition_families.get(group)
                    if family is None:
                        row = _diag_condition_pending_alerts.get(group)
                        if row is not None:
                            family = (
                                row["event_type"], row.get("code"))
                    if family is not None:
                        known_families[group] = family
        for group in sorted(known - current, key=repr):
            family = known_families.get(group)
            if family is None:
                log.error(
                    "Track-A foreign condition lacks exact family: %r",
                    group)
                continue
            recovered_type, recovered_code = family
            lane = group[-1]
            detail = {
                "from_service": service,
                "status": freshness,
                "snapshot_id": status.get("snapshot_id"),
                "snapshot": payload,
                "relay_only": True,
                "restart_reconciled": True,
            }
            detail["recovered_event_type"] = recovered_type
            detail["recovered_code"] = recovered_code
            _diag_emit_relay({
                "severity": "info",
                "event_type": "recovered",
                "code": recovered_type,
                "lanes": [lane],
                "detail": detail,
            })
    except Exception:
        log.debug("foreign delivery reconciliation swallowed", exc_info=True)


def _health_drop_path():
    d = os.environ.get("WSL_DIAG_DIR", "").strip() or "./diag_logs"
    import health_drop
    return os.path.join(d, health_drop.HEALTH_DROP_FILENAME)


_health_drop_seen = {}       # health_drop.plan_foreign_relay episode state
_health_drop_write_failed = False
_platform_health_reasons = set()
_health_drop_lock = threading.Lock()
_track_a_clock_monitor = None
_track_a_clock_fault_active = False
_last_camera_health = {
    # Camera mode must not start false-green before initialization/probe.
    "ok": SCORING_MODE != "camera",
    "code": ("not_enabled" if SCORING_MODE != "camera"
             else "not_initialized"),
    "lanes": list(LANES),
}


def _health_drop_hop_unlocked(last_health=None):
    """R3-11: write THIS (camera/Track-A) service's last-known health to the
    shared drop file, and relay the OTHER (controller/Track-B) service's
    last-known health to the store — so Pi/controller platform health is
    visible on the desk even while only the camera service is running. Both
    services are mutually exclusive (systemd Conflicts=), so the drop file is
    the hand-off. Best-effort; never raises."""
    try:
        import health_drop
        global _health_drop_write_failed, _platform_health_reasons
        global _track_a_clock_monitor, _track_a_clock_fault_active
        # Capacity may have returned since the prior sample. Retry immutable
        # incidents before consuming any new episode transitions.
        _diag_pump_pending(include_conditions=False)
        path = _health_drop_path()
        platform = health_drop.collect_platform_health(
            os.path.dirname(path), require_pi_probes=True)
        ledger_repaired = False
        if _diag_condition_ledger_error:
            # A corrupt/transiently unwritable ledger cannot safely own a
            # condition transition. First attempt an atomic clean rewrite; if
            # it succeeds, publish the observed storage fault and its recovery
            # through the now-causal condition path.
            ledger_repaired = _persist_diag_condition_ledger()
        if _diag_condition_ledger_error:
            platform["ok"] = False
            platform["reasons"] = sorted(set(
                (platform.get("reasons") or [])
                + ["diagnostic_delivery_ledger"]))
            log.error(
                "Track-A diagnostic condition ledger remains unwritable: %s",
                _diag_condition_ledger_path())
        elif ledger_repaired:
            detail = {
                "path": _diag_condition_ledger_path(),
                "restart_reconciliation_degraded": True,
                "auto_repaired": True,
            }
            _diag_emit_lanes(
                "fault", "diag_storage_error",
                code="condition_delivery_ledger", detail=detail,
                condition=("track_a_condition_ledger",))
            _diag_emit_lanes(
                "info", "recovered", code="diag_storage_error",
                detail={
                    **detail,
                    "restart_reconciliation_degraded": False,
                    "recovered_event_type": "diag_storage_error",
                    "recovered_code": "condition_delivery_ledger",
                },
                condition=("track_a_condition_ledger",),
                clear_condition=True)
        if _track_a_clock_monitor is None:
            _track_a_clock_monitor = health_drop.WallMonotonicDriftMonitor()
        drift = _track_a_clock_monitor.sample()
        if drift.get("drifted"):
            # A wall step is a historical occurrence, not an active condition.
            # The monitor re-baselines immediately, so retain this exact stamp
            # until every concrete lane queue accepts it.
            occurrence = time.monotonic_ns()
            _diag_emit_lanes(
                "warn", "pi_clock_drift", code="wall_step",
                detail={"source": "track_a_platform_probe", **drift},
                retain=True,
                pending_key=("incident", "track_a_clock", occurrence))
        if not drift.get("ok"):
            platform["ok"] = False
            platform["reasons"] = sorted(set(
                (platform.get("reasons") or [])
                + ["clock_drift"]))
            _diag_emit_lanes(
                "warn", "pi_clock_drift",
                code=drift.get("code") or "clock_probe_invalid",
                detail={"source": "track_a_platform_probe", **drift},
                condition=("track_a_clock_probe",))
            _track_a_clock_fault_active = True
        elif (_track_a_clock_fault_active
              or ("track_a_clock_probe",)
              in _known_diag_condition_bases("track_a_clock_probe")):
            _diag_emit_lanes(
                "info", "recovered", code="pi_clock_drift",
                detail={
                    "source": "track_a_platform_probe",
                    "reason": "clock_probe_invalid",
                    "platform": platform,
                    "recovered_event_type": "pi_clock_drift",
                    "recovered_code": "clock_probe_invalid",
                },
                condition=("track_a_clock_probe",),
                clear_condition=True)
            _track_a_clock_fault_active = False
        current_reasons = set(platform.get("reasons") or ())
        for reason, severity, event_type, code in (
                health_drop.platform_fault_events(platform)):
            _diag_emit_lanes(
                severity, event_type, code=code,
                detail={
                    "source": "track_a_platform_probe",
                    "reason": reason,
                    "platform": platform,
                },
                condition=("track_a_platform", reason))
        known_platform_reasons = {
            base[1] for base in _known_diag_condition_bases(
                "track_a_platform")
            if len(base) == 2
        }
        for reason in sorted(
                (_platform_health_reasons | known_platform_reasons)
                - current_reasons):
            mapped = health_drop.PLATFORM_EVENT_MAP.get(reason)
            _diag_emit_lanes(
                "info", "recovered",
                code=mapped[1] if mapped is not None else reason,
                detail={
                    "source": "track_a_platform_probe",
                    "reason": reason,
                    "platform": platform,
                    "recovered_event_type": (
                        mapped[1] if mapped is not None else reason),
                    "recovered_code": (
                        mapped[2] if mapped is not None else reason),
                },
                condition=("track_a_platform", reason),
                clear_condition=True)
        _platform_health_reasons = current_reasons
        with _diag_pending_lock:
            pending_drops = _diag_pending_drops
            pending_count = len(_diag_pending)
        if pending_drops:
            platform["ok"] = False
            platform["reasons"] = sorted(set(
                (platform.get("reasons") or [])
                + ["diagnostic_event_loss"]))
        platform["track_a_diag_pending"] = pending_count
        platform["track_a_diag_pending_drops"] = pending_drops
        camera = last_health or {"lanes": list(LANES)}
        payload = {
            "ok": bool(camera.get("ok", True)) and platform["ok"],
            "camera": camera,
            "platform": platform,
        }
        wrote = health_drop.write_drop(
            path, health_drop.SERVICE_CAMERA, payload)
        if not wrote:
            _health_drop_write_failed = True
            _diag_emit_lanes(
                "warn", "diag_storage_error", code="health_drop_write",
                detail=health_drop.stats(),
                condition=("track_a_health_drop_write",))
        elif (wrote and (
                _health_drop_write_failed
                or ("track_a_health_drop_write",)
                in _known_diag_condition_bases(
                    "track_a_health_drop_write"))):
            _health_drop_write_failed = False
            _diag_emit_lanes(
                "info", "recovered", code="health_drop_write",
                detail={
                    "recovered_event_type": "diag_storage_error",
                    "recovered_code": "health_drop_write",
                },
                condition=("track_a_health_drop_write",),
                clear_condition=True)
        for status in health_drop.read_foreign_statuses(
                path, health_drop.SERVICE_CAMERA):
            # The two Pi services are mutually exclusive. Missing/stale
            # foreign state is actionable only if deployment explicitly
            # requires that foreign service, which current policy forbids.
            if not health_drop.foreign_service_required(
                    os.environ.get(
                        "WSL_PHASE8_REQUIRED_SERVICES", ""),
                    "controller", LANES):
                continue
            for event in health_drop.plan_foreign_relay(
                    status, _health_drop_seen):
                _diag_emit_relay(event)
            _reconcile_foreign_delivery(status)
        _diag_pump_pending()
        _diag_report_pending_drops()
    except Exception:
        log.debug("_health_drop_hop swallowed", exc_info=True)


def _health_drop_hop(last_health=None):
    """Serialize shared-file writes and relay episode state across pollers."""
    with _health_drop_lock:
        _health_drop_hop_unlocked(last_health)


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
    return 'healthy' if h.get('ok') is True else 'unhealthy'


def _clear_track_a_camera_conditions(detail=None):
    """Close every exact camera fault family retained for this episode."""
    results = {}
    bases = sorted(
        _known_diag_condition_bases("track_a_camera_health"), key=repr)
    for base in bases:
        if len(base) != 1:
            continue
        results["camera_health"] = _diag_emit_lanes(
            "info", "recovered", code="camera_health",
            detail=dict(detail or {}),
            condition=base, clear_condition=True)
    return results


async def _camera_health_probe_once():
    """Perform one camera-health probe and publish its current truth."""
    global _cam_health_warned, _last_camera_health
    if _camera_poisoned:
        # A timed-out native worker may still own cv2 indefinitely. Preserve
        # the latched unhealthy truth and never submit a concurrent probe.
        _last_camera_health = {
            "ok": False,
            "code": "capture_stalled",
            "reason": _camera_poison_reason,
            "lanes": list(LANES),
        }
        await asyncio.to_thread(_health_drop_hop, _last_camera_health)
        return
    cam = _PAIR_CAMERA
    if cam is None:
        _last_camera_health = {
            "ok": False, "code": "dead", "lanes": list(LANES)}
        await asyncio.to_thread(_health_drop_hop, _last_camera_health)
        _cam_health_warned = True
        await asyncio.to_thread(
            _diag_emit_lanes,
            "warn", "camera_health", code="dead",
            detail={"reason": "camera mode but no camera object "
                              "(init failed)"},
            condition=("track_a_camera_health",))
        return
    if any(_capture_in_flight.values()):
        return                  # never race a scoring capture
    try:
        h = await _run_camera_operation(
            "health_probe", cam.frame_health)
    except CameraOperationUnavailable:
        # Timeout has already latched/published capture_stalled. A transient
        # busy refusal cannot occur here because in-flight scoring is checked.
        return
    ok = bool(h.get('ok'))
    code = _classify_camera_health(h)
    _last_camera_health = {
        "ok": ok, "code": code, "lanes": list(LANES)}
    # File/subprocess health work stays off the asyncio event loop.
    await asyncio.to_thread(_health_drop_hop, _last_camera_health)
    if not ok:
        _cam_health_warned = True
        await asyncio.to_thread(
            _diag_emit_lanes,
            "warn", "camera_health", code=code,
            detail={k: h.get(k) for k in
                    ("mean", "variance", "focus", "grabbed",
                     "stale", "reasons")},
            condition=("track_a_camera_health",))
    elif ok:
        _cam_health_warned = False
        await asyncio.to_thread(
            _clear_track_a_camera_conditions,
            {"reason": "healthy_camera_probe"})


async def camera_health_loop():
    """Periodic camera health poll (camera mode only). One 'camera_health'
    warn per unhealthy episode; recovery emits 'recovered' info. Runs the
    blocking capture in a worker thread and skips any poll that would race
    a scoring capture."""
    global _cam_health_warned, _last_camera_health
    if SCORING_MODE != "camera":
        poll_s = max(10.0, _cam_env_float(CAM_HEALTH_POLL_ENV, 300.0))
        log.info(
            "Track-A platform health: polling every %.0fs in manual mode",
            poll_s)
        while True:
            try:
                await asyncio.to_thread(
                    _health_drop_hop, dict(_last_camera_health))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug(
                    "manual-mode platform health loop swallowed",
                    exc_info=True)
            await asyncio.sleep(poll_s)
    if not _cam_env_on(CAM_HEALTH_ENV):
        return
    poll_s = max(10.0, _cam_env_float(CAM_HEALTH_POLL_ENV, 300.0))
    log.info(f"camera health: polling every {poll_s:.0f}s "
             f"(disable: {CAM_HEALTH_ENV}=0)")
    while True:
        try:
            # Probe immediately on startup; only subsequent probes sleep first.
            await _camera_health_probe_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("camera_health_loop swallowed", exc_info=True)
        await asyncio.sleep(poll_s)


async def shared_platform_health_loop():
    """Report Track-A platform/drop health independently of camera mode.

    Manual scoring, a disabled camera poller, or a failed camera constructor
    must not silence Pi filesystem/disk health or the stale/missing Track-B
    hand-off. The blocking platform probe runs off the asyncio event loop.
    """
    poll_s = max(
        10.0, _cam_env_float("WSL_DIAG_PLATFORM_POLL_S", 60.0))
    while True:
        try:
            await asyncio.to_thread(_health_drop_hop, _last_camera_health)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("shared_platform_health_loop swallowed", exc_info=True)
        await asyncio.sleep(poll_s)


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
        v = await _run_camera_operation(
            "empty_self_check", cam.self_check_empty, lane_id=lane_id)
        if not v.get('grabbed') or v.get('stale'):
            await asyncio.to_thread(
                _diag_emit,
                "warn", "camera_health",
                code='dead' if not v.get('grabbed') else 'frozen',
                detail={"during": "self_check_empty",
                        "reason": v.get('reason')},
                lane=lane_id, retain=True,
                pending_key=(
                    "incident", "camera_self_check", lane_id,
                    time.monotonic_ns()))
        elif v.get('flagged'):
            await asyncio.to_thread(
                _diag_emit,
                "warn", "camera_ref_drift", code="empty_ref",
                detail={k: v.get(k) for k in
                        ("max_divergence", "max_spot_divergence",
                         "empty_confirmed", "recalibrated", "reason")},
                lane=lane_id, retain=True,
                pending_key=(
                    "incident", "camera_ref_drift", lane_id,
                    time.monotonic_ns()))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("_maybe_camera_selfcheck swallowed", exc_info=True)


def _init_camera():
    """Construct the PairCamera in camera mode. Failure is non-fatal: we log and
    leave _PAIR_CAMERA None, so detect_current_pins() returns None and every ball
    falls back to awaiting_manual (desk scoring) — the lane still runs."""
    global _PAIR_CAMERA, _last_camera_health
    global _camera_worker_task, _camera_worker_started_at
    global _camera_poisoned, _camera_poison_reason
    # Explicit reinitialization is the only in-process recovery path. Normal
    # production use calls this once at startup; operators otherwise restart
    # the service so a timed-out native worker cannot be reused accidentally.
    if _camera_worker_task is not None and not _camera_worker_task.done():
        raise RuntimeError("cannot reinitialize camera while worker is active")
    _camera_worker_task = None
    _camera_worker_started_at = None
    _camera_poisoned = False
    _camera_poison_reason = None
    for lane_id in LANES:
        _capture_in_flight[lane_id] = False
        _capture_started_at[lane_id] = None
    if SCORING_MODE != "camera":
        _last_camera_health = {
            "ok": True, "code": "not_enabled", "lanes": list(LANES)}
        return
    try:
        _PAIR_CAMERA = camera.PairCamera(
            deck_to_lane={dk: ln for dk, ln in pin_detect.DECK_TO_LANE.items()
                          if ln in LANES})
        if _PAIR_CAMERA.ready:
            # Detector readiness is not a live-frame health proof. The health
            # loop probes immediately after the diagnostic writer starts.
            _last_camera_health = {
                "ok": False, "code": "not_probed", "lanes": list(LANES)}
            log.info(f"Camera ready for lanes {_PAIR_CAMERA.lanes()} "
                     f"(settle={camera.SETTLE_S}s).")
        else:
            _last_camera_health = {
                "ok": False, "code": "dead", "lanes": list(LANES)}
            log.warning("Camera mode but detector NOT ready (no empty ref / cv2). "
                        "Balls will fall back to manual desk scoring until fixed. "
                        "Capture an empty ref: python lane_node/camera.py --capture-empty")
    except Exception as e:
        log.warning(f"Camera init failed ({e}); manual fallback for all balls.")
        _PAIR_CAMERA = None
        _last_camera_health = {
            "ok": False, "code": "dead", "lanes": list(LANES)}


async def main():
    global event_queue, main_loop, _DIAG_WRITER
    global _SCORING_TRANSPORT, _SCORING_EXECUTOR, _scoring_event_wake
    global _scoring_transport_init_attempted
    main_loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue(maxsize=SCORING_EVENT_QUEUE_MAX)
    _scoring_event_wake = asyncio.Event()
    # Start diagnostics and durably record this process entry before scoring
    # storage or native camera construction can hang/fail. Restart-loop
    # evidence is therefore available for the failures it is meant to expose.
    try:
        _DIAG_WRITER = _DiagWriter()
        _DIAG_WRITER.start()
    except Exception:
        log.warning("lane diagnostics writer failed to start (health events "
                    "will remain in the durable startup ledger)", exc_info=True)
        _DIAG_WRITER = None
    if not await asyncio.to_thread(_load_diag_condition_ledger):
        log.error(
            "Track-A condition-delivery ledger is invalid/unavailable; "
            "diagnostic health will remain degraded")
    if SCORING_MODE != "camera":
        # A prior camera-mode fault is no longer applicable after an explicit
        # switch to manual scoring. Close only the persisted camera condition;
        # this does not claim that unmonitored camera hardware became healthy.
        await asyncio.to_thread(
            _clear_track_a_camera_conditions,
            {
                "reason": "camera_mode_disabled",
                "scoring_mode": SCORING_MODE,
                "restart_reconciled": True,
            })
    try:
        await _record_track_a_service_start()
    except Exception:
        log.warning("Track-A service-start evidence failed", exc_info=True)

    _SCORING_EXECUTOR = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="scoring-transport")
    _scoring_transport_init_attempted = True
    try:
        _SCORING_TRANSPORT = await main_loop.run_in_executor(
            _SCORING_EXECUTOR,
            lambda: DurableTransport(
                default_transport_path(), SCORING_EVENT_QUEUE_MAX))
        await main_loop.run_in_executor(
            _SCORING_EXECUTOR,
            _SCORING_TRANSPORT.observe_wall_clock)
        recovered_capture_jobs = await main_loop.run_in_executor(
            _SCORING_EXECUTOR,
            _SCORING_TRANSPORT.recover_capture_jobs)
        if recovered_capture_jobs:
            log.error(
                "Recovered %d interrupted camera capture job(s) as "
                "awaiting-manual scoring events",
                recovered_capture_jobs)
        if _SCORING_TRANSPORT.event_health()["depth"]:
            _scoring_event_wake.set()
    except Exception:
        _SCORING_TRANSPORT = None
        log.exception(
            "durable scoring transport unavailable; scoring events will "
            "be visibly degraded and must not be released")
    _init_camera()
    if _SCORING_TRANSPORT is not None:
        try:
            clock_status = await main_loop.run_in_executor(
                _SCORING_EXECUTOR,
                _SCORING_TRANSPORT.wall_clock_status)
            if clock_status["anomaly_latched"]:
                await asyncio.to_thread(
                    _diag_emit_lanes,
                    "fault", "scoring_event_transport",
                    code="physical_command_clock_anomaly_latched",
                    detail={
                        **clock_status,
                        "requires_manual_reconciliation": True,
                        "actuating_commands_refused": True,
                    },
                    retain=True,
                    pending_key=(
                        "incident", "scoring_event_transport",
                        "physical_command_clock_anomaly_latched"))
        except Exception:
            await asyncio.to_thread(
                _diag_emit_lanes,
                "fault", "scoring_event_transport",
                code="physical_command_clock_guard_unavailable",
                detail={
                    "requires_manual_reconciliation": True,
                    "actuating_commands_refused": True,
                },
                retain=True,
                pending_key=(
                    "incident", "scoring_event_transport",
                    "physical_command_clock_guard_unavailable"))
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

    if _SCORING_TRANSPORT is not None:
        _enable_scoring_callbacks()
    else:
        _disable_scoring_callbacks()
        await asyncio.to_thread(
            _diag_emit_lanes,
            "fault", "scoring_event_transport",
            code="physical_inputs_masked_durable_transport_unavailable",
            detail={
                "lanes": list(LANES),
                "requires_manual_reconciliation": True,
            },
            retain=True,
            pending_key=(
                "incident", "scoring_event_transport",
                "physical_inputs_masked_durable_transport_unavailable"))

    try:
        # The watchdog kick and the server connection run concurrently and
        # independently. SIGTERM cancels main_task → gather cancels both →
        # finally runs _cleanup_gpio(). If either coroutine raises, gather
        # propagates and we still clean up (relays safe-open).
        await asyncio.gather(
            watchdog_kick_loop(),
            connection_manager(),
            camera_health_loop(),      # R2-14: no-op unless camera mode + on
            shared_platform_health_loop(),
        )
    finally:
        _cleanup_gpio()
        if _DIAG_WRITER is not None:
            try:
                remaining = _drain_track_a_diagnostics(_DIAG_WRITER)
                if remaining:
                    log.error(
                        "Track-A shutdown left %d diagnostic obligation(s) "
                        "unpersisted", remaining)
            except Exception:
                pass
        if _SCORING_EXECUTOR is not None:
            _SCORING_EXECUTOR.shutdown(wait=False, cancel_futures=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down.")
