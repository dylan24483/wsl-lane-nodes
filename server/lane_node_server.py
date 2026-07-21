#!/usr/bin/env python3
"""WSL-SRV-side WebSocket + HTTP. Now with desk-app-simulator endpoints."""

import asyncio
import hmac
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Make wsl_scoring_engine importable from sys.path regardless of OS
# or where this file is launched from. This used to be a hardcoded
# Pi path; now it derives from __file__ so the server can run on
# WSL-SRV (Windows) too.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from wsl_scoring_engine import LaneScoring, CrossLaneScoring, mask_to_standing
from state_store import save_lanes, load_lanes, get_save_status
from lane_fx_protocol import LaneFxPublisher
# Machine/Equipment diagnostics domain — this server is the SINGLE
# OWNER of machine_cycles/machine_events (scope doc §2); wsl_api is a
# pure proxy. Storage + validation live in machine_store; the HTTP
# surface is registered in HttpHandler below.
import machine_store

from websockets.asyncio.server import serve

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('server')

# Shared-token auth for the control surfaces (POST :8766 + WS HELLO :8765).
# DEFAULT-OFF for compatibility: when LANE_NODE_TOKEN is unset, behavior is
# identical to before (unauthenticated, with a loud startup warning). When
# set, every POST must carry the same value in the X-Lane-Token header and
# every WS HELLO must carry it in a "token" field, or it is rejected.
# SYMMETRIC (review #51): when set, encode() also stamps the token into every
# server->node command frame, and the node rejects command frames without it
# — so an impersonated server can no longer actuate relays.
# GET endpoints (display HTML, /api/lane/N/scoring, /api/state, /api/health)
# stay open — the overhead displays poll them and they send no hardware
# commands. The same env var configures the Pi client (lane_node.py) and
# must be added to wsl_api.py's mirror/proxy POSTs in the wsl-systems repo.
AUTH_TOKEN = os.environ.get("LANE_NODE_TOKEN", "").strip()

state_lock = threading.Lock()
# Restore lane scoring + ball counters from disk so server restarts
# don't wipe in-progress games. If the load fails (no file, corrupted,
# class-shape mismatch), we start fresh — see state_store.load_lanes
# for the failure-handling.
lane_scoring, ball_counters = load_lanes()
# clients/client_metadata are mutated by the WS handler (asyncio thread)
# and read by the HTTP handler thread (health, send_to_*). Guard BOTH
# sides with clients_lock — never held across an await or a send.
clients_lock = threading.Lock()
clients = {}
client_metadata = {}  # node_id -> {"lanes": [...], "protocol_version": N, "connected_at": float, "last_heartbeat": float}
main_loop = None
SERVER_START_TIME = time.time()
# Cosmetic events leave the hardware-control process over one-way,
# nonblocking loopback UDP. The separate gateway owns subscriber sockets,
# replay, and backpressure; a failed renderer must never stall this process.
fx_publisher = LaneFxPublisher()


def _emit_fx_event(payload):
    """No-throw boundary for every cosmetic event tap."""
    try:
        return fx_publisher.emit(payload)
    except Exception as exc:
        log.warning("Lane FX publish failed (authoritative path unaffected): %s",
                    exc)
        return False


def get_or_create_lane(lane_id, bowlers=None):
    if lane_id not in lane_scoring:
        ls = LaneScoring(lane_id)
        for i, name in enumerate(bowlers or ['TEST']):
            ls.add_bowler(name, number=i+1, hdcp=0)
        ls.is_active = True
        lane_scoring[lane_id] = ls
        log.info(f"Lane {lane_id}: created with bowlers {[b.name for b in ls.bowlers]}")
    return lane_scoring[lane_id]

PIN_MASK_CYCLE = [0b0000011111, 0, 0, 0b0001111111, 0b0000001111, 0]


def _strike_streak(frames):
    """Count consecutive strike deliveries, including 10th-frame fills."""
    streak = 0
    for frame in reversed(frames):
        for bowl in reversed(frame.bowls):
            if bowl.display != 'X':
                return streak
            streak += 1
    return streak


def _build_ball_fx_payload(lane, bowl, pin_mask, foul, thrower_snapshot,
                           frame_before, frames_before, mode, next_bowler):
    """Build an immutable cosmetic event after record_ball returns.

    LaneScoring immediately resets BowlerGame objects when the final ball
    ends a game. The caller therefore snapshots scalar bowler/game fields and
    the old frame objects before recording. This preserves the actual final
    ball instead of accidentally describing the newly-started game.
    """
    if bowl is None or frame_before is None or thrower_snapshot is None:
        return None
    standing = mask_to_standing(pin_mask & 0x3FF)
    running_total = next(
        (frame.score for frame in reversed(frames_before)
         if frame.score is not None), 0)
    split_converted = bool(
        bowl.num == 2
        and frame_before.is_spare
        and frame_before.bowls
        and frame_before.bowls[0].split)
    game_over = bool(frame_before.number == 10 and frame_before.is_complete)
    return {
        "type": "ball",
        "lane": lane,
        "bowler": thrower_snapshot,
        "ball_in_frame": bowl.num,
        "frame_number": frame_before.number,
        "display": bowl.display,
        # Scored pinfall for this delivery (zero on a foul), not the total
        # number absent from the deck after a second ball.
        "pins_down": bowl.pins_down,
        "pin_mask": pin_mask & 0x3FF,
        "standing": standing,
        "foul": bool(foul),
        # The engine stores split as a bool; standing identifies the leave.
        "split": bool(bowl.split),
        "split_converted": split_converted,
        "is_strike": bool(frame_before.is_strike),
        "is_spare": bool(frame_before.is_spare),
        "frame_complete": bool(frame_before.is_complete),
        "strike_streak": _strike_streak(frames_before),
        "frame_score": frame_before.score,
        "running_total": running_total,
        "game_over": game_over,
        "game_number": thrower_snapshot["game_number"],
        "mode": mode,
        "next_bowler": next_bowler,
        "test": False,
    }


def _process_ball_event(lane, pin_mask=None):
    """Record a ball for the given lane. Shared by WS-handler and the
    desk simulator's Trigger-Ball HTTP endpoint.

    pin_mask: 10-bit mask of pins still standing AFTER the ball. In
    production, computed on the Pi side by pin_detect from the
    T-Camera frame. If None (synthetic Trigger Ball without a real
    Pi-side detection chain), fall back to PIN_MASK_CYCLE rotation
    so bench-test behavior is unchanged.

    Consumes any pending foul flag — if FOUL_EVENT was received between
    the previous ball and this one, this bowl gets recorded as a foul
    (display 'F', scored 0 regardless of pins).

    Only records when the lane has been OPENED (a lane_scoring entry
    exists and is active). Ball events for unopened/closed lanes are
    ignored with a warning — a stray DIELL trip or rogue POST must not
    auto-create a phantom 'TEST' game. Only the open / open-league
    endpoints create lane state.

    Returns (bowl, pin_mask, foul, fx_payload). The caller publishes the
    cosmetic payload only after the current logical CYCLE reply is complete.
    In Track A the OEM controller owns physical cycle and this server reply is
    not an authorized machine driver.
    bowl is None when the lane isn't open.
    """
    fx_payload = None
    thrower_name = None
    with state_lock:
        ls = lane_scoring.get(lane)
        if ls is None or not getattr(ls, 'is_active', False):
            log.warning(f"Lane {lane}: ball event ignored — lane not open "
                        f"(no active scoring state)")
            return None, pin_mask, False, None
        n = ball_counters.get(lane, 0)
        if pin_mask is None:
            pin_mask = PIN_MASK_CYCLE[n % len(PIN_MASK_CYCLE)]
        ball_counters[lane] = n + 1
        foul = pending_foul.pop(lane, False)
        # Snapshot the actual thrower before record_ball. After a completed
        # frame the scorer advances to the next bowler; after a completed game
        # it immediately reinitializes this BowlerGame for the next game.
        try:
            if hasattr(ls, 'record_ball_for_lane'):
                thrower = ls.current_bowler_for_lane(lane)
                mode = 'cross_lane'
            else:
                thrower = ls.current_bowler
                mode = 'single_lane'
            frame_before = (thrower.frames[thrower.current_frame_idx]
                            if thrower is not None else None)
            frames_before = (tuple(thrower.frames)
                             if thrower is not None else ())
            thrower_snapshot = ({
                "name": thrower.name,
                "number": thrower.number,
                "hdcp": thrower.hdcp,
                "game_number": thrower.game_number,
            } if thrower is not None else None)
            thrower_name = thrower.name if thrower is not None else None
        except Exception as exc:
            # FX metadata is cosmetic. A future engine-shape change must not
            # prevent scoring or the caller's subsequent CYCLE command.
            log.warning("Lane %s: FX pre-ball snapshot failed (scoring "
                        "continues): %s", lane, exc)
            thrower_snapshot = None
            frame_before = None
            frames_before = ()
            mode = 'unknown'
        # Route by physical lane when the scorer is CrossLaneScoring —
        # otherwise CrossLaneScoring.record_ball() always falls back to
        # lane_left, which means a score posted to /api/lane/22/score
        # during a league match records against lane 21's current bowler.
        # LaneScoring (single-lane) has no record_ball_for_lane method.
        if hasattr(ls, 'record_ball_for_lane'):
            bowl = ls.record_ball_for_lane(lane, pin_mask, foul=foul)
            current_after = ls.current_bowler_for_lane(lane)
        else:
            bowl = ls.record_ball(pin_mask, foul=foul)
            current_after = ls.current_bowler
        save_lanes(lane_scoring, ball_counters)
        try:
            fx_payload = _build_ball_fx_payload(
                lane, bowl, pin_mask, foul, thrower_snapshot, frame_before,
                frames_before, mode,
                current_after.name if current_after else None)
        except Exception as exc:
            log.warning("Lane %s: FX payload build failed (scoring saved): %s",
                        lane, exc)
            fx_payload = None
    if bowl:
        pd = 10 - bin(pin_mask).count("1")
        foul_marker = " [FOUL]" if foul else ""
        log.info(f"Lane {lane}: {thrower_name or '?'}"
                 f" → {bowl.display} ({pd} pins, mask={pin_mask:#012b}){foul_marker}")
    return bowl, pin_mask, foul, fx_payload

# Bump this whenever a message type's shape changes incompatibly.
# Compared against the node's PROTOCOL_VERSION on HELLO; mismatch logs
# a warning but does NOT reject the connection (we'd rather degrade
# than refuse, since the alternative is a silently-broken pinsetter).
# v1 = single-lane (HELLO carries `lane`); v2 = multi-lane (HELLO carries `lanes`).
PROTOCOL_VERSION = 2

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

# Lane-id → True if a foul has been flagged for the next ball on that
# lane. The flag is set by FOUL_EVENT, consumed (and cleared) by the
# next BALL_EVENT. This separates "player crossed the foul line" from
# "player rolled the ball" — they're distinct signals from different
# physical sensors (AL-ZARD foul circuit vs DIELL ball-detect).
pending_foul: dict = {}

# Duplicate-ball suppression window (seconds).
#
# ============================ BALL-DEDUP STORY ============================
# (one comment block, repeated in each layer — review 2026-06-27 finding 39:
# three uncoordinated knobs is a cutover hazard. Same block lives in
# lane_node/lane_node.py and firmware/rp2040/config.h.)
#
#   WSL_LANE_BALL_LOCKOUT_S (lane_node.py, default 0.2 s) is the
#   AUTHORITATIVE Track-A ball-dedup window — phantom-ball masking (scatter/
#   sweep re-breaking a beam) belongs THERE, at the sensor. ⚠️ AT CUTOVER SET
#   WSL_LANE_BALL_LOCKOUT_S=8 on every node.
#
#   LANE_BALL_DEDUP_S (THIS knob, default 0 = DISABLED) is a delivery-dedup
#   BACKSTOP, not the primary mask: it covers what the node lockout cannot
#   see — a redelivery from the node's transactional re-queue after a WS
#   drop, and manual mode running at the node's bench-default 0.2 s. Set it
#   to 8 at cutover as well (bench-confirm against the real cycle time),
#   but do NOT treat it as a substitute for the node knob.
#
#   BALL_LOCKOUT_MS (RP2040 firmware, 300 ms) is Track-B only (L/R pair
#   coalesce feeding the cycle FSM); it never touches this path.
#
# The effective windows are logged at startup on both node and server —
# check those two lines at cutover instead of trusting env-var memory.
# ==========================================================================
# A suppressed duplicate is logged and gets NO record_ball and NO second
# CYCLE pulse (fail-safe direction: fewer relay actuations).
try:
    BALL_DEDUP_WINDOW_S = max(0.0, float(os.environ.get("LANE_BALL_DEDUP_S", "0")))
except ValueError:
    logging.getLogger("lane_node_server").warning(
        "Bad LANE_BALL_DEDUP_S=%r — duplicate-ball window disabled",
        os.environ.get("LANE_BALL_DEDUP_S"))
    BALL_DEDUP_WINDOW_S = 0.0
_last_ball_at: dict = {}   # lane-id -> time.monotonic() of last ACCEPTED ball

def encode(t, **f):
    """Build a server->node frame. Every frame this server sends a node is a
    COMMAND (CYCLE / OPEN_LANE / CLOSE_LANE / RESET / POWER_*), so when
    LANE_NODE_TOKEN is set it is stamped into the frame — the node (review
    #51, symmetric auth) rejects command frames without the matching token.
    Unset = frame shape byte-identical to before (unauthenticated bench)."""
    if AUTH_TOKEN and "token" not in f:
        f["token"] = AUTH_TOKEN
    return json.dumps({"type": t, "ts": time.time(), **f})
def decode(r): return json.loads(r)

def _socket_owns_lane(node_id, lane):
    """Lane-binding check: True when `lane` is among the lanes this node
    declared at HELLO. Nodes that declared no lanes (legacy v1 with no
    `lane` field, or bench tools that skip HELLO entirely when auth is
    off) pass through — enforcement applies only to explicit claims, so
    existing bench behavior is unchanged."""
    if node_id is None:
        return True
    with clients_lock:
        meta = client_metadata.get(node_id)
    declared = (meta or {}).get("lanes") or []
    return (not declared) or (lane in declared)


async def handle_node(websocket):
    addr = websocket.remote_address
    log.info(f"New connection from {addr}")
    node_id = None
    authed = not AUTH_TOKEN  # auth disabled -> every connection is trusted
    try:
        async for raw in websocket:
            msg = decode(raw)
            mt = msg.get("type")

            if mt == Msg.HELLO:
                if AUTH_TOKEN:
                    supplied = msg.get("token") or ""
                    if not (isinstance(supplied, str)
                            and hmac.compare_digest(supplied, AUTH_TOKEN)):
                        log.warning(f"Rejecting HELLO from {addr}: bad or "
                                    f"missing token (node={msg.get('node')!r})")
                        await websocket.close(code=4401, reason="auth failed")
                        return
                authed = True
                node_id = msg.get("node", "<unknown>")
                node_version = msg.get("protocol_version")
                raw_lanes = msg.get("lanes") or (
                    [msg["lane"]] if "lane" in msg else []
                )
                # Sanitize: lane claims must be a list of ints — anything
                # else would break the `lane in lanes` ownership checks.
                node_lanes = ([l for l in raw_lanes if isinstance(l, int)]
                              if isinstance(raw_lanes, list) else [])
                if node_lanes != raw_lanes:
                    log.warning(f"Node {node_id!r}: non-integer lane claims "
                                f"in HELLO {raw_lanes!r} -> using {node_lanes}")
                now = time.time()
                with clients_lock:
                    # Warn on conflicting lane claims — send_to_lane routes
                    # to the NEWEST claimant, so a stale zombie connection
                    # can't keep eating a lane's commands.
                    for other_id, meta in client_metadata.items():
                        if other_id == node_id:
                            continue
                        overlap = set(node_lanes) & set(meta.get("lanes") or [])
                        if overlap:
                            log.warning(
                                f"Node {node_id!r} claims lanes {sorted(overlap)} "
                                f"already claimed by {other_id!r}; newest "
                                f"claimant receives lane commands")
                    clients[node_id] = websocket
                    client_metadata[node_id] = {
                        "lanes": node_lanes,
                        "protocol_version": node_version,
                        "connected_at": now,
                        "last_heartbeat": now,
                    }
                if node_version != PROTOCOL_VERSION:
                    log.warning(
                        f"Node {node_id!r} protocol version mismatch: "
                        f"node={node_version}, server={PROTOCOL_VERSION}. "
                        f"Continuing — message handling may degrade."
                    )
                log.info(f"Node {node_id!r} registered "
                         f"(lanes={node_lanes}, protocol_version={node_version})")

            elif not authed:
                # Auth enabled and this connection never sent a valid HELLO —
                # drop it before any state mutation or hardware effect.
                log.warning(f"Dropping {mt!r} from unauthenticated connection "
                            f"{addr}; closing")
                await websocket.close(code=4401, reason="auth required")
                return

            elif mt == Msg.BALL_EVENT:
                lane = msg.get("lane")
                pin_mask = msg.get("pin_mask")
                awaiting_manual = bool(msg.get("awaiting_manual", False))
                if not isinstance(lane, int):
                    log.warning(f"Node {node_id!r}: BALL_EVENT with invalid "
                                f"lane {lane!r}; ignored")
                    continue
                if not _socket_owns_lane(node_id, lane):
                    log.warning(f"Node {node_id!r}: BALL_EVENT for lane {lane} "
                                f"outside its declared lanes; ignored")
                    continue

                # Duplicate-ball window (see BALL_DEDUP_WINDOW_S above):
                # suppressed dupes get no record_ball and no second CYCLE.
                if BALL_DEDUP_WINDOW_S > 0:
                    nowm = time.monotonic()
                    last = _last_ball_at.get(lane)
                    if last is not None and (nowm - last) < BALL_DEDUP_WINDOW_S:
                        log.warning(
                            f"Lane {lane}: duplicate BALL_EVENT "
                            f"{nowm - last:.2f}s after the last accepted ball "
                            f"(window {BALL_DEDUP_WINDOW_S}s); suppressed")
                        continue
                    _last_ball_at[lane] = nowm

                # Two paths:
                #   camera mode  — pin_mask is real; record_ball immediately
                #                  (auto-scoring), then CYCLE the pinsetter.
                #   manual mode  — pin_mask is None AND awaiting_manual=True;
                #                  CYCLE the pinsetter so the lane resets, but
                #                  DO NOT record_ball — wait for the desk to
                #                  POST /api/lane/<N>/score with real pins.
                #                  Otherwise we'd score bogus PIN_MASK_CYCLE
                #                  values on every real ball.
                fx_payload = None
                if awaiting_manual or pin_mask is None:
                    log.info(f"Lane {lane}: BALL detected (manual mode — "
                             "awaiting /score POST from desk). Sending logical "
                             "CYCLE reply; Track-A physical cycle is OEM-owned.")
                else:
                    _, _, _, fx_payload = _process_ball_event(
                        lane, pin_mask=pin_mask)

                await websocket.send(encode(Msg.CYCLE, lane=lane))
                # Cosmetic publication is deliberately after the current
                # logical CYCLE reply. In Track A the OEM independently owns
                # physical cycle; FX serialization/transport delays neither.
                if fx_payload is not None:
                    _emit_fx_event(fx_payload)

            elif mt == Msg.FOUL_EVENT:
                lane = msg.get("lane")
                if not isinstance(lane, int):
                    log.warning(f"Node {node_id!r}: FOUL_EVENT with invalid "
                                f"lane {lane!r}; ignored")
                    continue
                if not _socket_owns_lane(node_id, lane):
                    log.warning(f"Node {node_id!r}: FOUL_EVENT for lane {lane} "
                                f"outside its declared lanes; ignored")
                    continue
                # Flag the next ball on this lane as a foul. If a ball
                # event comes within a reasonable window, it'll consume
                # this flag and score as a foul. If no ball arrives
                # (false trigger, player stepped over without throwing),
                # the flag stays set until the next ball — which is
                # arguably wrong but matches AMF/Brunswick foul semantics
                # where the foul lamp latches until ball-detect fires.
                # OPEN_LANE / CLOSE_LANE clear stale flags for their lanes.
                with state_lock:
                    pending_foul[lane] = True
                log.info(f"Lane {lane}: FOUL flagged (will apply to next ball)")

            elif mt == Msg.HEARTBEAT:
                # Track liveness so send_to_* can tell "delivered to a node
                # that's actually responding" from "buffered to a zombie".
                hb_node = msg.get("node") or node_id
                with clients_lock:
                    meta = client_metadata.get(hb_node)
                    if meta is not None:
                        meta["last_heartbeat"] = time.time()
    except Exception as e:
        log.warning(f"Handler error: {e}")
    finally:
        with clients_lock:
            if node_id and clients.get(node_id) is websocket:
                del clients[node_id]
                client_metadata.pop(node_id, None)
                log.info(f"Node {node_id!r} disconnected")

# A node counts as "reached" only when its last heartbeat (or connect)
# is at most this old. Heartbeats arrive every 5s; 15s = three missed
# beats. Without this, ws.send() to a half-dead socket buffers in the
# kernel and we'd report sent_to=1 for a node that's gone.
HEARTBEAT_FRESH_S = 15


def _last_seen(meta):
    return max(meta.get("last_heartbeat") or 0, meta.get("connected_at") or 0)


def send_to_all_nodes(msg_str):
    """Schedule a send on the asyncio loop from the HTTP handler thread.
    Returns the number of nodes that both accepted the send AND have a
    fresh heartbeat — buffered sends to zombie sockets don't count."""
    sent = 0
    now = time.time()
    with clients_lock:
        targets = [(nid, ws, dict(client_metadata.get(nid) or {}))
                   for nid, ws in clients.items()]
    for node_id, ws, meta in targets:
        try:
            fut = asyncio.run_coroutine_threadsafe(ws.send(msg_str), main_loop)
            fut.result(timeout=2)
        except Exception as e:
            log.warning(f"send_to {node_id} failed: {e}")
            continue
        if now - _last_seen(meta) <= HEARTBEAT_FRESH_S:
            sent += 1
        else:
            log.warning(f"send_to {node_id}: send buffered but heartbeat is "
                        f"{now - _last_seen(meta):.1f}s stale — not counting "
                        f"as delivered")
    return sent


def send_to_lane(lane, msg_str):
    """Deliver a command to the node that OWNS `lane` (declared it in
    HELLO), instead of broadcasting to every node. The newest claimant
    wins when two nodes claim the same lane (stale zombie connections
    lose). Falls back to broadcast when no connected node claims the
    lane — legacy/bench nodes that didn't declare lanes still work, and
    lane_node.py ignores commands for lanes it doesn't handle anyway.

    Returns 1 when the owning node accepted the send and has a fresh
    heartbeat, else 0 (or the broadcast count on fallback)."""
    now = time.time()
    owners = []
    with clients_lock:
        for nid, meta in client_metadata.items():
            if lane in (meta.get("lanes") or []):
                ws = clients.get(nid)
                if ws is not None:
                    owners.append((meta.get("connected_at") or 0, nid, ws,
                                   dict(meta)))
    if not owners:
        log.warning(f"send_to_lane: no connected node claims lane {lane}; "
                    f"falling back to broadcast")
        return send_to_all_nodes(msg_str)
    owners.sort(key=lambda t: t[0])
    if len(owners) > 1:
        log.warning(f"send_to_lane: lane {lane} claimed by "
                    f"{[o[1] for o in owners]}; routing to newest "
                    f"claimant {owners[-1][1]!r}")
    _, node_id, ws, meta = owners[-1]
    try:
        fut = asyncio.run_coroutine_threadsafe(ws.send(msg_str), main_loop)
        fut.result(timeout=2)
    except Exception as e:
        log.warning(f"send_to_lane({lane}) -> {node_id} failed: {e}")
        return 0
    if now - _last_seen(meta) > HEARTBEAT_FRESH_S:
        log.warning(f"send_to_lane({lane}) -> {node_id}: send buffered but "
                    f"heartbeat is {now - _last_seen(meta):.1f}s stale — not "
                    f"counting as delivered")
        return 0
    return 1

# ============================================================
# HTML DISPLAY + DESK SIMULATOR
# ============================================================
DISPLAY_HTML = """<!doctype html>
<html><head><title>Lane Display</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif;
         background: #0a0a0a; color: #f0f0f0; padding: 1.5em; margin: 0; }
  h1 { color: #888; font-weight: 300; font-size: 1.1em; margin: 0 0 1em 0; }
  .controls { background: #1a1a1a; border-radius: 12px; padding: 1em;
              margin-bottom: 1em; display: flex; gap: 0.6em; align-items: center; }
  .controls label { color: #888; font-size: 0.9em; }
  .controls button { background: #2a2a2a; color: #f0f0f0; border: 1px solid #444;
                     padding: 0.5em 1em; border-radius: 6px; cursor: pointer;
                     font-size: 0.9em; }
  .controls button:hover { background: #3a3a3a; }
  .controls button.open { border-color: #2d6a3e; color: #b8e8c5; }
  .controls button.close { border-color: #6a2d2d; color: #e8b8b8; }
  .controls button.reset { border-color: #6a5b2d; color: #e8d8b8; }
  .controls button.power-on { border-color: #2d5a6a; color: #b8d8e8; }
  .controls button.power-off { border-color: #4a4a4a; color: #aaa; }
  .controls button.trigger-ball { border-color: #5a4a8a; color: #c8b8e8; }
  .lane { background: #1a1a1a; border-radius: 12px; padding: 1.2em; margin: 1em 0; }
  .lane-header { display: flex; justify-content: space-between; align-items: baseline;
                 margin-bottom: 0.8em; }
  .lane-num { color: #ffce42; font-size: 1.5em; font-weight: 700; }
  .lane-meta { color: #888; font-size: 0.85em; }
  .bowler { padding: 0.8em 0; border-top: 1px solid #2a2a2a; }
  .bowler-row { display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 0.5em; }
  .bowler-name { font-size: 1.2em; font-weight: 600; }
  .bowler-total { font-size: 2.5em; font-weight: 800; color: #fff; line-height: 1; }
  .frames { display: flex; gap: 0.3em; flex-wrap: wrap; }
  .frame { background: #2a2a2a; border-radius: 6px; padding: 0.4em 0.6em;
           min-width: 3.2em; text-align: center; font-family: ui-monospace, Menlo, monospace; }
  .frame .num { color: #555; font-size: 0.7em; }
  .frame .bowls { font-size: 1.1em; font-weight: 600; }
  .frame .pts { color: #aaa; font-size: 0.85em; }
  .frame.strike { background: #2d6a3e; }
  .frame.spare  { background: #2d4a6a; }
  .stats { display: flex; gap: 1em; color: #888; font-size: 0.85em; margin-top: 0.6em; }
  .empty { color: #555; padding: 2em; text-align: center; }
  .toast { position: fixed; bottom: 1em; right: 1em; background: #2d6a3e;
           padding: 0.8em 1.2em; border-radius: 8px; color: #fff;
           opacity: 0; transition: opacity 0.2s; }
  .toast.show { opacity: 1; }
</style>
<script>
async function action(lane, op) {
  const r = await fetch(`/api/lane/${lane}/${op}`, { method: 'POST' });
  const data = await r.json();
  toast(`${op.toUpperCase()} sent to lane ${lane} (${data.sent_to} node${data.sent_to===1?'':'s'})`);
  refresh();
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1500);
}
async function refresh() {
  try {
    const r = await fetch('/api/state');
    const data = await r.json();
    const root = document.getElementById('lanes');
    if (Object.keys(data).length === 0) {
      root.innerHTML = '<div class="empty">No lane events yet — press the button on the Pi or click Open Lane</div>';
      return;
    }
    root.innerHTML = '';
    for (const [lane, scoring] of Object.entries(data)) {
      const div = document.createElement('div');
      div.className = 'lane';
      const players = scoring.players || [];
      const playersHtml = players.map(p => {
        const framesHtml = (p.frames || []).map(f => {
          const isStrike = (f.bowls || []).some(b => b.display === 'X');
          const isSpare = (f.bowls || []).some(b => b.display === '/');
          const cls = isStrike ? 'strike' : (isSpare ? 'spare' : '');
          const bowlsStr = (f.bowls || []).map(b => b.display).join(' ');
          return `<div class="frame ${cls}"><div class="num">${f.frame}</div>
                  <div class="bowls">${bowlsStr || '·'}</div>
                  <div class="pts">${f.points || 0}</div></div>`;
        }).join('');
        return `<div class="bowler"><div class="bowler-row">
                  <span class="bowler-name">${p.name}</span>
                  <span class="bowler-total">${p.current_total || 0}</span></div>
                <div class="frames">${framesHtml}</div></div>`;
      }).join('');
      const stats = scoring.stats || {};
      div.innerHTML = `
        <div class="lane-header">
          <span class="lane-num">Lane ${lane}</span>
          <span class="lane-meta">Game ${scoring.game || 1}</span>
        </div>
        ${playersHtml}
        <div class="stats">
          <span>Strikes: ${stats.strikes || 0}</span>
          <span>Spares: ${stats.spares || 0}</span>
          <span>Gutters: ${stats.gutters || 0}</span>
        </div>`;
      root.appendChild(div);
    }
  } catch (e) { console.error(e); }
}
setInterval(refresh, 500);
window.addEventListener('load', refresh);
</script>
</head>
<body>
  <h1>WSL Lane Node Display — desk simulator + live scoring</h1>
  <div class="controls">
    <label>Lane 21:</label>
    <button class="open" onclick="action(21, 'open')">Open Lane</button>
    <button class="close" onclick="action(21, 'close')">Close Lane</button>
    <button class="reset" onclick="action(21, 'reset')">Reset Pins</button>
    <button class="power-on" onclick="action(21, 'power-on')">Power On</button>
    <button class="power-off" onclick="action(21, 'power-off')">Power Off</button>
    <button class="trigger-ball" onclick="action(21, 'trigger-ball')">Trigger Ball</button>
  </div>
  <div class="controls">
    <label>Lane 22:</label>
    <button class="open" onclick="action(22, 'open')">Open Lane</button>
    <button class="close" onclick="action(22, 'close')">Close Lane</button>
    <button class="reset" onclick="action(22, 'reset')">Reset Pins</button>
    <button class="power-on" onclick="action(22, 'power-on')">Power On</button>
    <button class="power-off" onclick="action(22, 'power-off')">Power Off</button>
    <button class="trigger-ball" onclick="action(22, 'trigger-ball')">Trigger Ball</button>
  </div>
  <div id="lanes" class="empty">Loading...</div>
  <div id="toast" class="toast"></div>
</body></html>
"""

class HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Split path from query so /display?lane=21&mode=league matches /display
        path_only = urlparse(self.path).path

        if self.path == '/':
            self._send(200, 'text/html; charset=utf-8', DISPLAY_HTML.encode('utf-8'))
        elif path_only == '/display':
            # Customer-facing scoring display. Same HTML as wsl-systems —
            # kept in sync at the repo root. Page polls /api/lane/<N>/scoring
            # relative to wherever it's served from, which lands on the
            # handler below.
            display_path = _REPO_ROOT / 'wsl_scoring_display.html'
            try:
                body = display_path.read_bytes()
            except FileNotFoundError:
                return self._send(500, 'text/plain',
                                  f'display HTML not found at {display_path}'.encode('utf-8'))
            self._send(200, 'text/html; charset=utf-8', body)
        elif path_only.startswith('/api/lane/') and path_only.endswith('/scoring'):
            # /api/lane/<N>/scoring — used by wsl_scoring_display.html to poll
            # this server's Phase 8 scoring state. Returns the same shape as
            # wsl-systems' /api/lane/<N>/scoring endpoint via to_scoring_response.
            parts = path_only.strip('/').split('/')
            if len(parts) != 4:
                return self._send(404, 'application/json', b'{"error":"not found"}')
            try:
                lane = int(parts[2])
            except ValueError:
                return self._send(400, 'application/json', b'{"error":"bad lane"}')
            # Hold state_lock across to_scoring_response — the cross-lane
            # serializer walks (and trims game-over entries from) the lane
            # queues, so serializing outside the lock raced with the WS
            # handler's record_ball mutations. resp is a fresh dict, so
            # json.dumps can safely run after the lock is released
            # (same pattern as /api/state below).
            with state_lock:
                ls = lane_scoring.get(lane)
                resp = (ls.to_scoring_response(view_lane_id=lane)
                        if ls is not None else None)
            if resp is None:
                # No scoring state for this lane — return a "closed" stub so
                # the display can render "Lane Closed" cleanly instead of erroring.
                return self._send(200, 'application/json',
                                  json.dumps({"ok": True, "lane": lane, "open": False,
                                              "players": []}).encode('utf-8'))
            self._send(200, 'application/json', json.dumps(resp).encode('utf-8'))
        elif path_only.startswith('/api/lane/') and path_only.endswith('/diagnostics'):
            # /api/lane/<N>/diagnostics — machine-domain view for one lane:
            # unresolved faults + last N events (?events=N, default 50) +
            # latest cycle intervals + baseline summary. Read-only, so it
            # stays open like the other GETs (LAN-internal posture).
            parts = path_only.strip('/').split('/')
            if len(parts) != 4:
                return self._send(404, 'application/json', b'{"error":"not found"}')
            try:
                lane = int(parts[2])
            except ValueError:
                return self._send(400, 'application/json', b'{"error":"bad lane"}')
            query = parse_qs(urlparse(self.path).query)
            try:
                events_limit = int((query.get('events') or ['50'])[0])
            except ValueError:
                events_limit = 50
            try:
                payload = machine_store.lane_diagnostics(
                    lane, events_limit=events_limit)
            except Exception as e:
                log.warning(f"lane_diagnostics({lane}) failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"diagnostics unavailable"}')
            self._send(200, 'application/json',
                       json.dumps(payload).encode('utf-8'))
        elif path_only == '/api/machine/health':
            # Bulk per-lane machine rollup — the ONE endpoint wsl_api polls
            # (idle-machine faults must surface without a per-lane fanout).
            try:
                payload = machine_store.machine_health()
            except Exception as e:
                log.warning(f"machine_health failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"machine health unavailable"}')
            self._send(200, 'application/json',
                       json.dumps(payload).encode('utf-8'))
        elif self.path == '/api/state':
            with state_lock:
                snap = {str(l): ls.to_scoring_response() for l, ls in lane_scoring.items()}
            self._send(200, 'application/json', json.dumps(snap).encode('utf-8'))
        elif self.path == '/api/health':
            now = time.time()
            uptime_sec = now - SERVER_START_TIME
            with state_lock:
                lanes_summary = {
                    str(l): {
                        "bowlers": [b.name for b in ls.bowlers],
                        "current_frame": (ls.current_bowler.current_frame_idx + 1
                                          if ls.current_bowler else None),
                        "ball_counter": ball_counters.get(l, 0),
                        "scores": {b.name: b.current_total for b in ls.bowlers},
                    }
                    for l, ls in lane_scoring.items()
                }
                pending_fouls = list(pending_foul.keys())
            # Snapshot the client dicts under clients_lock — the WS handler
            # mutates them on (re)connect, and iterating live dicts here
            # raced that ("dictionary changed size during iteration").
            with clients_lock:
                nodes_connected = len(clients)
                nodes_meta = {nid: dict(meta)
                              for nid, meta in client_metadata.items()}
            try:
                machine_section = machine_store.health_counts()
            except Exception as e:
                machine_section = {"ok": False, "error": str(e)}
            health = {
                "ok": True,
                "uptime_sec": round(uptime_sec, 1),
                "uptime_human": f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m {int(uptime_sec % 60)}s",
                "protocol_version": PROTOCOL_VERSION,
                "auth_enabled": bool(AUTH_TOKEN),
                "nodes_connected": nodes_connected,
                "nodes": [
                    {
                        "node_id": nid,
                        "lanes": meta.get("lanes"),
                        "protocol_version": meta.get("protocol_version"),
                        "connected_for_sec": round(now - (meta.get("connected_at") or now), 1),
                        "heartbeat_age_sec": round(now - _last_seen(meta), 1),
                        "heartbeat_fresh": (now - _last_seen(meta)) <= HEARTBEAT_FRESH_S,
                    }
                    for nid, meta in nodes_meta.items()
                ],
                "lanes": lanes_summary,
                "pending_fouls": pending_fouls,
                "state_db": str(__import__('state_store').DB_PATH),
                "state_save": get_save_status(),
                "lane_fx": fx_publisher.status(),
                # Counts only (scope task 3) — the full rollup lives at
                # /api/machine/health. health_counts() catches its own
                # DB errors; the extra guard keeps /api/health alive
                # even if machine_store itself is broken.
                "machine": machine_section,
            }
            self._send(200, 'application/json',
                       json.dumps(health, indent=2).encode('utf-8'))
        else:
            self._send(404, 'text/plain', b'Not found')

    def _check_auth(self):
        """Shared-token gate for every POST (all POSTs either fire hardware
        or mutate scoring state). DEFAULT-OFF: no LANE_NODE_TOKEN env ->
        always allowed (compatibility). Returns True when the request may
        proceed; sends the 401 itself otherwise."""
        if not AUTH_TOKEN:
            return True
        supplied = self.headers.get('X-Lane-Token', '') or ''
        if hmac.compare_digest(supplied, AUTH_TOKEN):
            return True
        log.warning(f"POST {self.path} from {self.client_address[0]} rejected: "
                    f"bad or missing X-Lane-Token")
        self._send(401, 'application/json',
                   b'{"error":"unauthorized: X-Lane-Token header required"}')
        return False

    def _read_json_body(self, max_bytes, required=True):
        """Read + parse the JSON request body for the machine endpoints.
        Returns (obj, None) on success or (None, error_bytes) — the
        caller sends the 400 itself. required=False returns ({}, None)
        on an empty body."""
        content_length = int(self.headers.get('Content-Length', 0) or 0)
        if content_length <= 0:
            if required:
                return None, b'{"error":"JSON body required"}'
            return {}, None
        if content_length > max_bytes:
            return None, (f'{{"error":"body too large (max {max_bytes} '
                          f'bytes)"}}').encode('utf-8')
        try:
            return (json.loads(self.rfile.read(content_length)
                               .decode('utf-8')), None)
        except (ValueError, UnicodeDecodeError):
            return None, b'{"error":"invalid JSON body"}'

    def _handle_machine_post(self, path_only):
        """POST surface of the machine-diagnostics domain:
          /api/machine/events            — batch ingest (list of events)
          /api/machine/cycles            — single cycle row
          /api/machine/events/<id>/ack   — desk ack (body: {acknowledged_by:
                                           <staff id|null>} — the wsl_api
                                           bridge contract — or {by: ...})
          /api/machine/events/<id>/resolve
        Behind the same X-Lane-Token gate as every other POST. Ingest is
        additionally gated by the WSL_MACHINE_DIAG kill-switch (503 when
        off); ack/resolve act on already-stored rows and stay available."""
        parts = path_only.strip('/').split('/')

        if parts == ['api', 'machine', 'events']:
            body, err = self._read_json_body(1_000_000)
            if err:
                return self._send(400, 'application/json', err)
            # Accept a bare JSON array or {"events": [...]}.
            events = body.get('events') if isinstance(body, dict) else body
            if not isinstance(events, list) or not events:
                return self._send(400, 'application/json',
                                  b'{"error":"body must be a JSON array of '
                                  b'events (or {\\"events\\": [...]})"}')
            if len(events) > machine_store.MAX_EVENT_BATCH:
                return self._send(400, 'application/json',
                                  json.dumps({
                                      "error": "batch too large",
                                      "max": machine_store.MAX_EVENT_BATCH,
                                  }).encode('utf-8'))
            rows = []
            for i, ev in enumerate(events):
                try:
                    rows.append(machine_store.validate_event(ev))
                except ValueError as e:
                    return self._send(400, 'application/json',
                                      json.dumps({"error": str(e),
                                                  "index": i}).encode('utf-8'))
            try:
                ids = machine_store.insert_events(rows)
            except machine_store.StoreDisabled:
                return self._send(503, 'application/json',
                                  b'{"ok":false,"error":"machine diagnostics '
                                  b'disabled (WSL_MACHINE_DIAG)"}')
            except Exception as e:
                log.warning(f"machine events insert failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"insert failed"}')
            return self._send(200, 'application/json',
                              json.dumps({"ok": True, "inserted": len(ids),
                                          "ids": ids}).encode('utf-8'))

        if parts == ['api', 'machine', 'cycles']:
            body, err = self._read_json_body(65536)
            if err:
                return self._send(400, 'application/json', err)
            try:
                row = machine_store.validate_cycle(body)
            except ValueError as e:
                return self._send(400, 'application/json',
                                  json.dumps({"error": str(e)}).encode('utf-8'))
            try:
                cycle_id = machine_store.insert_cycle(row)
            except machine_store.StoreDisabled:
                return self._send(503, 'application/json',
                                  b'{"ok":false,"error":"machine diagnostics '
                                  b'disabled (WSL_MACHINE_DIAG)"}')
            except Exception as e:
                log.warning(f"machine cycle insert failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"insert failed"}')
            return self._send(200, 'application/json',
                              json.dumps({"ok": True,
                                          "id": cycle_id}).encode('utf-8'))

        if (len(parts) == 5 and parts[:3] == ['api', 'machine', 'events']
                and parts[4] in ('ack', 'resolve')):
            try:
                event_id = int(parts[3])
            except ValueError:
                return self._send(400, 'application/json',
                                  b'{"error":"bad event id"}')
            try:
                if parts[4] == 'ack':
                    body, err = self._read_json_body(4096)
                    if err:
                        return self._send(400, 'application/json', err)
                    # 2026-07-19 review: wsl_api's proxy sends
                    # {'acknowledged_by': <staff id|null>} (the pinned bridge
                    # contract in tests/test_phase8_bridge_contract.py);
                    # accepting only {'by': int} 400'd every desk ack. Accept
                    # both spellings; null is allowed (a staff actor without
                    # a staff_id) and stores NULL — the id is an OPAQUE
                    # wsl.db reference either way.
                    if not isinstance(body, dict) or not (
                            'by' in body or 'acknowledged_by' in body):
                        return self._send(400, 'application/json',
                                          b'{"error":"by or acknowledged_by '
                                          b'(staff id, integer or null) '
                                          b'required"}')
                    by = (body.get('by') if 'by' in body
                          else body.get('acknowledged_by'))
                    if by is not None and (isinstance(by, bool)
                                           or not isinstance(by, int)):
                        return self._send(400, 'application/json',
                                          b'{"error":"by or acknowledged_by '
                                          b'(staff id, integer or null) '
                                          b'required"}')
                    row = machine_store.ack_event(event_id, by)
                else:
                    body, err = self._read_json_body(4096, required=False)
                    if err:
                        return self._send(400, 'application/json', err)
                    row = machine_store.resolve_event(event_id)
            except Exception as e:
                log.warning(f"machine event {parts[4]} failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"update failed"}')
            if row is None:
                return self._send(404, 'application/json',
                                  b'{"error":"event not found"}')
            return self._send(200, 'application/json',
                              json.dumps({"ok": True,
                                          "event": row}).encode('utf-8'))

        return self._send(404, 'application/json', b'{"error":"not found"}')

    def do_POST(self):
        # /api/lane/{N}/{open|close|reset|power-on|power-off|trigger-ball|score}
        if not self._check_auth():
            return
        path_only = urlparse(self.path).path
        if path_only.startswith('/api/machine/'):
            return self._handle_machine_post(path_only)
        if path_only == '/api/fx/test':
            # Cosmetic-only test fire. Unlike trigger-ball, this does not
            # mutate scoring state and cannot send a command to a lane node.
            content_length = int(self.headers.get('Content-Length', 0) or 0)
            if content_length <= 0 or content_length > 4096:
                return self._send(
                    400, 'application/json',
                    b'{"error":"body required (max 4096 bytes): {lane,event}"}')
            try:
                body = json.loads(
                    self.rfile.read(content_length).decode('utf-8'))
                lane = int(body.get('lane'))
            except (ValueError, TypeError, UnicodeDecodeError):
                return self._send(400, 'application/json',
                                  b'{"error":"lane must be an integer"}')
            event = body.get('event')
            allowed = {
                'strike', 'spare', 'split', 'split_converted', 'gutter',
                'foul', 'game_over', 'lane_open', 'lane_close',
            }
            if lane < 1 or lane > 128:
                return self._send(400, 'application/json',
                                  b'{"error":"lane out of range"}')
            if event not in allowed:
                return self._send(
                    400, 'application/json',
                    json.dumps({"error": "unsupported event",
                                "allowed": sorted(allowed)}).encode('utf-8'))
            accepted = _emit_fx_event({
                "type": "test", "lane": lane, "event": event,
                "test": True,
            })
            code = 202 if accepted else 503
            return self._send(
                code, 'application/json',
                json.dumps({
                    "ok": accepted,
                    "accepted": accepted,
                    "lane": lane,
                    "event": event,
                    "lane_fx": fx_publisher.status(),
                }).encode('utf-8'))
        parts = self.path.strip('/').split('/')
        if len(parts) == 4 and parts[0] == 'api' and parts[1] == 'lane':
            try:
                lane = int(parts[2])
                action = parts[3]
            except ValueError:
                return self._send(400, 'application/json', b'{"error":"bad lane"}')

            # score: record-only endpoint for live-soak manual scoring.
            # Used after the DIELL beam already fired and the pinsetter
            # already cycled — desk operator types the actual pin count
            # and posts {"pin_mask": <int 0-1023>, "foul": <bool>}.
            # DOES NOT send CYCLE (the Pi already cycled on the BALL_EVENT
            # that triggered this manual-score flow). Posting score for a
            # ball that didn't actually happen physically just updates the
            # scorecard without touching hardware — safe.
            if action == 'score':
                # Lane must already be open — scoring a closed/unopened lane
                # used to auto-create a phantom 'TEST' game. Only the open /
                # open-league endpoints create lane state now.
                with state_lock:
                    ls = lane_scoring.get(lane)
                    lane_open = ls is not None and getattr(ls, 'is_active', False)
                if not lane_open:
                    return self._send(404, 'application/json',
                                      json.dumps({'ok': False,
                                                  'error': f'Lane {lane} not open'}).encode('utf-8'))
                content_length = int(self.headers.get('Content-Length', 0) or 0)
                if content_length == 0:
                    return self._send(400, 'application/json',
                                      b'{"error":"body required: {pin_mask: int, foul?: bool}"}')
                try:
                    body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    return self._send(400, 'application/json',
                                      b'{"error":"invalid JSON body"}')
                if 'pin_mask' not in body or body['pin_mask'] is None:
                    return self._send(400, 'application/json',
                                      b'{"error":"pin_mask required (int 0-1023)"}')
                try:
                    pin_mask_in = int(body['pin_mask'])
                except (ValueError, TypeError):
                    return self._send(400, 'application/json',
                                      b'{"error":"pin_mask must be int 0-1023"}')
                # Strict range check — DO NOT silently mask out-of-range values.
                # Earlier `int(...) & 0x3FF` accepted -1 as 1023 and 2048 as 0,
                # contradicting the error message and producing nonsense scores.
                if not (0 <= pin_mask_in <= 0x3FF):
                    return self._send(400, 'application/json',
                                      b'{"error":"pin_mask out of range (must be 0-1023)"}')

                # Foul tri-state on /score:
                #   true       — flag this ball as a foul (sets pending_foul[lane])
                #   false      — clear any stale pending_foul for this lane BEFORE
                #                recording (so a false-positive foul lamp can be
                #                undone if the desk operator confirms no foul)
                #   omitted    — leave pending_foul untouched; _process_ball_event
                #                consumes the existing flag if any
                foul_in = body.get('foul')
                if foul_in is True:
                    with state_lock:
                        pending_foul[lane] = True
                elif foul_in is False:
                    with state_lock:
                        pending_foul.pop(lane, None)

                bowl, pin_mask, foul, fx_payload = _process_ball_event(
                    lane, pin_mask=pin_mask_in)
                if fx_payload is not None:
                    _emit_fx_event(fx_payload)
                payload = {
                    "lane": lane,
                    "pin_mask": pin_mask,
                    "foul": foul,
                    "display": bowl.display if bowl else None,
                }
                return self._send(200, 'application/json',
                                  json.dumps(payload).encode('utf-8'))

            # correct: rewrite a frame's bowls for desk corrections. Called
            # by wsl_api.py's /api/lanes/<id>/scoring/correct proxy when the
            # lane is on a Phase 8 pair. Body matches wsl_api's contract:
            # { bowler_idx: int, frame_idx: int (0-9),
            #   bowls: [{pins_down: 0-10, foul?: bool}, ...] }.
            # Returns the result dict from correct_frame() with an added
            # 'scoring' key holding the full updated to_scoring_response,
            # so the desk can refresh without a second fetch.
            #
            # Works for BOTH LaneScoring and CrossLaneScoring — both expose
            # correct_frame() and to_scoring_response(view_lane_id) with the
            # same signature. No hardware command is sent (this is purely
            # bookkeeping; pins on the deck are whatever they are).
            if action == 'correct':
                content_length = int(self.headers.get('Content-Length', 0) or 0)
                if content_length == 0:
                    return self._send(400, 'application/json',
                                      b'{"error":"body required: {bowler_idx, frame_idx, bowls}"}')
                try:
                    body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    return self._send(400, 'application/json',
                                      b'{"error":"invalid JSON body"}')
                try:
                    bowler_idx = int(body.get('bowler_idx', -1))
                    frame_idx = int(body.get('frame_idx', -1))
                except (TypeError, ValueError):
                    return self._send(400, 'application/json',
                                      b'{"error":"bowler_idx and frame_idx must be integers"}')
                bowls = body.get('bowls', [])
                if not isinstance(bowls, list):
                    return self._send(400, 'application/json',
                                      b'{"error":"bowls must be an array"}')

                with state_lock:
                    ls = lane_scoring.get(lane)
                    if not ls or not ls.is_active:
                        return self._send(
                            404, 'application/json',
                            json.dumps({'ok': False,
                                        'error': f'Lane {lane} not active'}).encode('utf-8'))
                    result = ls.correct_frame(bowler_idx, frame_idx, bowls)
                    if not result.get('ok'):
                        return self._send(400, 'application/json',
                                          json.dumps(result).encode('utf-8'))
                    # Persist immediately so corrections survive a server
                    # restart — same pattern as _process_ball_event.
                    save_lanes(lane_scoring, ball_counters)
                    # Fresh scoring payload so the desk refreshes without
                    # waiting for the next 5s poll cycle.
                    try:
                        result['scoring'] = ls.to_scoring_response(view_lane_id=lane)
                    except TypeError:
                        result['scoring'] = ls.to_scoring_response()
                log.info(f"Lane {lane}: correction by desk — "
                         f"bowler_idx={bowler_idx} frame_idx={frame_idx} "
                         f"bowls={bowls}")
                _emit_fx_event({"type": "correction", "lane": lane})
                return self._send(200, 'application/json',
                                  json.dumps(result).encode('utf-8'))

            # trigger-ball is a BENCH HELPER: synthesizes a BALL_EVENT AND
            # sends CYCLE to the Pi. Use only when testing without DIELL
            # wired. For live soak use /score above instead — calling
            # trigger-ball after a real ball will pulse the pinsetter a
            # second time and sweep the customer's just-set rack.
            if action == 'trigger-ball':
                # Same no-phantom-game rule as /score: the lane must have
                # been opened first (click Open Lane on the bench display).
                with state_lock:
                    ls = lane_scoring.get(lane)
                    lane_open = ls is not None and getattr(ls, 'is_active', False)
                if not lane_open:
                    return self._send(404, 'application/json',
                                      json.dumps({'ok': False,
                                                  'error': f'Lane {lane} not open '
                                                           f'(open it before trigger-ball)'}).encode('utf-8'))
                pin_mask_in = None
                foul_override = False
                content_length = int(self.headers.get('Content-Length', 0) or 0)
                if content_length > 0:
                    try:
                        body = json.loads(
                            self.rfile.read(content_length).decode('utf-8'))
                    except (ValueError, UnicodeDecodeError):
                        return self._send(400, 'application/json',
                                          b'{"error":"invalid JSON body"}')
                    if 'pin_mask' in body and body['pin_mask'] is not None:
                        try:
                            pin_mask_in = int(body['pin_mask'])
                        except (ValueError, TypeError):
                            return self._send(400, 'application/json',
                                              b'{"error":"pin_mask must be int 0-1023"}')
                        if not (0 <= pin_mask_in <= 0x3FF):
                            return self._send(400, 'application/json',
                                              b'{"error":"pin_mask out of range (must be 0-1023)"}')
                    foul_override = bool(body.get('foul', False))

                if foul_override:
                    with state_lock:
                        pending_foul[lane] = True

                bowl, pin_mask, foul, fx_payload = _process_ball_event(
                    lane, pin_mask=pin_mask_in)
                # Send the existing bench/simulator CYCLE message to the owning
                # node, not broadcast. This endpoint is never an FX test path;
                # Track-A physical cycle remains OEM-owned.
                cycle_msg = encode(Msg.CYCLE, lane=lane)
                sent = send_to_lane(lane, cycle_msg)
                if fx_payload is not None:
                    _emit_fx_event(fx_payload)
                payload = {
                    "sent_to": sent,
                    "lane": lane,
                    "pin_mask": pin_mask,
                    "pin_mask_source": "manual" if pin_mask_in is not None else "cycle",
                    "foul": foul,
                    "display": bowl.display if bowl else None,
                }
                return self._send(200, 'application/json',
                                  json.dumps(payload).encode('utf-8'))

            type_map = {
                'open': Msg.OPEN_LANE,
                'close': Msg.CLOSE_LANE,
                'reset': Msg.RESET,
                'power-on': Msg.POWER_ON,
                'power-off': Msg.POWER_OFF,
            }
            msg_type = type_map.get(action)
            if not msg_type:
                return self._send(400, 'application/json', b'{"error":"bad action"}')

            send_hardware_command = True

            # If opening, reset the scoring state. Bowlers can be supplied
            # in the request body as {"bowlers": ["name", ...] or
            # [{"name": "...", "hdcp": int, "bowler_id": int}, ...],
            # plus optional {"send_open_command": false} for WSL-SRV
            # restart rehydrate where we need display state but must not
            # pulse the pinsetter.
            # If no body / no bowlers field, falls back to a single TEST bowler
            # so bench smoke-tests still work without a payload.
            if msg_type == Msg.OPEN_LANE:
                bowlers_in = None
                content_length = int(self.headers.get('Content-Length', 0) or 0)
                if content_length > 0:
                    try:
                        body = json.loads(
                            self.rfile.read(content_length).decode('utf-8'))
                    except (ValueError, UnicodeDecodeError):
                        return self._send(400, 'application/json',
                                          b'{"error":"invalid JSON body"}')
                    raw_bowlers = body.get('bowlers')
                    send_hardware_command = body.get('send_open_command') is not False
                    if isinstance(raw_bowlers, list):
                        # Normalize: accept either ["name", ...] or
                        # [{"name": "...", ...}, ...]. We keep just the name
                        # for now — extended attributes (hdcp, bowler_id)
                        # could be added when LaneScoring's add_bowler is
                        # wired to take them through this path. The cross-lane
                        # /api/pair/<L>-<R>/open-league endpoint below handles
                        # the richer roster shape.
                        names = []
                        for item in raw_bowlers:
                            if isinstance(item, str) and item.strip():
                                names.append(item.strip())
                            elif isinstance(item, dict) and item.get('name'):
                                names.append(str(item['name']).strip())
                        if names:
                            bowlers_in = names

                with state_lock:
                    # If this lane currently belongs to a CrossLaneScoring
                    # pair, clear ALL of that object's lane keys — mirroring
                    # CLOSE_LANE below. Otherwise the partner lane keeps a
                    # stale reference to the old shared object (split-brain)
                    # and a later close of the partner would wipe this fresh
                    # game. Stale pending fouls die with the old game too.
                    existing = lane_scoring.get(lane)
                    stale_lanes = set(getattr(existing, 'lane_ids', []) or [])
                    stale_lanes.add(lane)
                    for lid in stale_lanes:
                        lane_scoring.pop(lid, None)
                        ball_counters.pop(lid, None)
                        pending_foul.pop(lid, None)
                    get_or_create_lane(lane, bowlers=bowlers_in)
                    save_lanes(lane_scoring, ball_counters)  # persist reset
                    opened_names = [b.name for b in lane_scoring[lane].bowlers]
                log.info(f"OPEN_LANE: reset scoring for lane {lane} "
                         f"(cleared {sorted(stale_lanes)}) "
                         f"with bowlers={bowlers_in or '[TEST]'}")

            # If closing, clear the scoring state on this lane (and the
            # paired lane too, if this lane is part of a CrossLaneScoring —
            # otherwise the overhead display would keep showing the old
            # match roster after desk close).
            if msg_type == Msg.CLOSE_LANE:
                with state_lock:
                    ls = lane_scoring.get(lane)
                    cleared = []
                    if ls is not None and hasattr(ls, 'lane_ids'):
                        for lid in list(ls.lane_ids):
                            lane_scoring.pop(lid, None)
                            ball_counters.pop(lid, None)
                            pending_foul.pop(lid, None)
                            cleared.append(lid)
                    else:
                        lane_scoring.pop(lane, None)
                        ball_counters.pop(lane, None)
                        pending_foul.pop(lane, None)
                        cleared.append(lane)
                    save_lanes(lane_scoring, ball_counters)
                log.info(f"CLOSE_LANE: cleared scoring for lane(s) {cleared}")

            msg = encode(msg_type, lane=lane)
            if send_hardware_command:
                sent = send_to_lane(lane, msg)
                log.info(f"→ {action.upper()} lane {lane} sent to {sent} node(s)")
            else:
                sent = 0
                log.info(f"→ {action.upper()} lane {lane}: state-only, hardware command suppressed")
            if msg_type == Msg.OPEN_LANE and send_hardware_command:
                _emit_fx_event({
                    "type": "lane_open",
                    "lane": lane,
                    "bowlers": opened_names,
                    "mode": "single_lane",
                })
            elif msg_type == Msg.CLOSE_LANE:
                for cleared_lane in cleared:
                    _emit_fx_event({
                        "type": "lane_close", "lane": cleared_lane})
            self._send(200, 'application/json',
                       json.dumps({
                           "sent_to": sent,
                           # never echo the auth token back to the HTTP caller
                           "msg": {k: v for k, v in json.loads(msg).items()
                                   if k != "token"},
                           "hardware_command_sent": send_hardware_command,
                       }).encode('utf-8'))
        elif len(parts) == 4 and parts[0] == 'api' and parts[1] == 'pair' and parts[3] == 'open-league':
            # POST /api/pair/<L>-<R>/open-league
            # Body: { team1_bowlers: [...], team2_bowlers: [...],
            #         team1_name?: str, team2_name?: str }
            # Each bowler is either "Name" (string) or
            # { name, hdcp?/handicap?, average?/current_avg?, bowler_id?, team_id? } (dict).
            # Creates a CrossLaneScoring registered under BOTH lane keys.
            # Replaces any existing scoring on either lane (idempotent re-run
            # supported for roster corrections).
            try:
                l_str, r_str = parts[2].split('-')
                lane_left = int(l_str)
                lane_right = int(r_str)
            except (ValueError, AttributeError):
                return self._send(400, 'application/json',
                                  b'{"error":"bad pair format, expected L-R (e.g. 21-22)"}')
            content_length = int(self.headers.get('Content-Length', 0) or 0)
            if content_length == 0:
                return self._send(400, 'application/json',
                                  b'{"error":"body required: {team1_bowlers, team2_bowlers, team1_name?, team2_name?}"}')
            try:
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, 'application/json',
                                  b'{"error":"invalid JSON body"}')
            t1_bowlers = body.get('team1_bowlers') or []
            t2_bowlers = body.get('team2_bowlers') or []
            t1_name = body.get('team1_name')
            t2_name = body.get('team2_name')
            send_open_command = body.get('send_open_command') is not False
            if not isinstance(t1_bowlers, list) or not isinstance(t2_bowlers, list):
                return self._send(400, 'application/json',
                                  b'{"error":"team1_bowlers and team2_bowlers must be lists"}')

            cls = CrossLaneScoring(lane_left, lane_right)
            number = 1
            for team_lane, raw_bowlers, team_name in (
                (lane_left,  t1_bowlers, t1_name),
                (lane_right, t2_bowlers, t2_name),
            ):
                for item in raw_bowlers:
                    if isinstance(item, str):
                        name = item.strip()
                        hdcp, avg, team_id, bowler_id = 0, 0.0, None, None
                    elif isinstance(item, dict):
                        name = str(item.get('name') or '').strip()
                        try:
                            hdcp_raw = item.get('hdcp')
                            if hdcp_raw is None:
                                hdcp_raw = item.get('handicap', 0)
                            hdcp = int(hdcp_raw or 0)
                        except (ValueError, TypeError):
                            hdcp = 0
                        try:
                            avg = float(item.get('average',
                                                 item.get('current_avg', 0.0)) or 0.0)
                        except (ValueError, TypeError):
                            avg = 0.0
                        team_id = item.get('team_id')
                        bowler_id = item.get('bowler_id') or item.get('id')
                    else:
                        continue
                    if not name:
                        continue
                    cls.add_bowler(name, number=number, hdcp=hdcp, average=avg,
                                   starting_lane=team_lane,
                                   team_id=team_id, team_name=team_name,
                                   bowler_id=bowler_id)
                    number += 1
            cls.start()

            with state_lock:
                # Clear every lane key reachable from the existing objects
                # at BOTH lanes — if either lane was previously part of a
                # different cross-lane pair, its old partner key must not
                # keep a stale reference to the replaced object.
                to_clear = {lane_left, lane_right}
                for lid in (lane_left, lane_right):
                    ex = lane_scoring.get(lid)
                    if ex is not None:
                        to_clear.update(getattr(ex, 'lane_ids', []) or [])
                for lid in to_clear:
                    lane_scoring.pop(lid, None)
                    ball_counters.pop(lid, None)
                    pending_foul.pop(lid, None)
                lane_scoring[lane_left] = cls
                lane_scoring[lane_right] = cls
                save_lanes(lane_scoring, ball_counters)

            t1_names = [b.name for b in cls.bowlers
                        if b.starting_physical_lane == lane_left]
            t2_names = [b.name for b in cls.bowlers
                        if b.starting_physical_lane == lane_right]
            log.info(f"OPEN_LEAGUE: pair {lane_left}+{lane_right} "
                     f"team1={t1_names} team2={t2_names}")

            # Pulse OPEN_LANE on both Pis so the relays kick the
            # "first set" 3-pulse pattern. WSL-SRV startup rehydrate sets
            # send_open_command=false to rebuild display state without
            # touching hardware on an already-active pair.
            sent_open = 0
            if send_open_command:
                for lid in (lane_left, lane_right):
                    sent_open += send_to_lane(lid, encode(
                        Msg.OPEN_LANE, lane=lid,
                        bowlers=[b.name for b in cls.bowlers]))

            if send_open_command:
                _emit_fx_event({
                    "type": "league_open",
                    "lanes": [lane_left, lane_right],
                    "mode": "cross_lane",
                    "teams": {
                        str(lane_left): t1_name,
                        str(lane_right): t2_name,
                    },
                    "bowlers": {
                        str(lane_left): t1_names,
                        str(lane_right): t2_names,
                    },
                })
            return self._send(200, 'application/json',
                              json.dumps({
                                  "ok": True,
                                  "lane_left": lane_left,
                                  "lane_right": lane_right,
                                  "team1_name": t1_name,
                                  "team2_name": t2_name,
                                  "team1_bowlers": t1_names,
                                  "team2_bowlers": t2_names,
                                  "game": cls.game_number,
                                  "hardware_command_sent": send_open_command,
                                  "sent_open_commands": sent_open,
                              }).encode('utf-8'))
        else:
            self._send(404, 'application/json', b'{"error":"not found"}')

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

def http_thread():
    HTTPServer(('0.0.0.0', 8766), HttpHandler).serve_forever()

async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()
    if AUTH_TOKEN:
        log.info("LANE_NODE_TOKEN set — POST control API (:8766) and WS HELLO "
                 "(:8765) require the shared token; node-bound command frames "
                 "are stamped with it (symmetric auth, review #51).")
    else:
        log.warning(
            "LANE_NODE_TOKEN not set — :8766 control POSTs and :8765 WS are "
            "UNAUTHENTICATED: any LAN device can cycle/power the pinsetters. "
            "Set LANE_NODE_TOKEN (same value on this server, every Pi "
            "lane-node, and wsl_api.py's mirror) to enable auth.")
    # Cutover checklist line (finding 39): the server-side delivery-dedup
    # BACKSTOP. The AUTHORITATIVE phantom-ball mask is WSL_LANE_BALL_LOCKOUT_S
    # on the nodes — see the BALL-DEDUP STORY block above BALL_DEDUP_WINDOW_S.
    if BALL_DEDUP_WINDOW_S <= 0:
        log.warning("Ball-dedup: LANE_BALL_DEDUP_S disabled (bench default — "
                    "no server-side duplicate-ball backstop; set 8 at cutover, "
                    "and WSL_LANE_BALL_LOCKOUT_S=8 on every node)")
    else:
        log.info(f"Ball-dedup: LANE_BALL_DEDUP_S={BALL_DEDUP_WINDOW_S}s "
                 f"(delivery-dedup backstop; the authoritative window is "
                 f"WSL_LANE_BALL_LOCKOUT_S on the nodes)")
    threading.Thread(target=http_thread, daemon=True).start()
    # Machine-diagnostics retention: startup prune + daily loop, on a
    # daemon thread (never blocks startup; never raises — see
    # machine_store._retention_loop).
    try:
        machine_store.start_retention_thread()
        log.info(f"Machine diagnostics: store {machine_store.DB_PATH} "
                 f"(enabled={machine_store.enabled()}, retention "
                 f"{machine_store.retention_days()}d via "
                 f"{machine_store.RETENTION_ENV})")
    except Exception as exc:
        log.warning(f"Machine diagnostics retention thread failed to "
                    f"start: {exc}")
    log.info("HTTP display + desk simulator: http://0.0.0.0:8766")
    log.info("WebSocket: ws://0.0.0.0:8765")
    async with serve(handle_node, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        # Final save on graceful shutdown — write-through during normal
        # operation should mean the on-disk state is already current,
        # but this catches the case where a state mutation happened
        # between the last write-through and shutdown signal.
        with state_lock:
            save_lanes(lane_scoring, ball_counters)
        log.info("Final state saved.")
