#!/usr/bin/env python3
"""WSL-SRV-side WebSocket + HTTP. Now with desk-app-simulator endpoints."""

import asyncio
import concurrent.futures
import functools
import hashlib
import hmac
import json
import logging
import math
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from state_store import (
    save_lanes, load_lanes, get_save_status,
    scoring_event_receipt, record_scoring_event_receipt,
    pending_foul_event_ids,
    pending_manual_events, manual_score_receipt, manual_score_resolution,
    bench_ball_operation_receipt,
    resolve_manual_score_event,
    lane_session_generation, lane_session_generation_group)
import state_store as state_store_module
from lane_fx_protocol import LaneFxPublisher
from lane_node.strict_json import loads as strict_json_loads
# Machine/Equipment diagnostics domain — this server is the SINGLE
# OWNER of machine_cycles/machine_events (scope doc §2); wsl_api is a
# pure proxy. Storage + validation live in machine_store; the HTTP
# surface is registered in HttpHandler below.
import machine_store

from websockets.asyncio.server import serve

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('server')

# Separate credentials protect the control surfaces. LANE_NODE_TOKEN covers
# HTTP POSTs and authenticates server->node commands; WSL_SCORING_NODE_TOKENS
# binds each WebSocket HELLO identity to its own secret.
# Missing auth is fail-closed. An operator may opt into unauthenticated bench
# behavior only with WSL_ALLOW_UNAUTHENTICATED_BENCH=1; health remains red and
# that override must never appear in a production service definition.
# SYMMETRIC (review #51): when set, encode() also stamps the token into every
# server->node command frame, and the node rejects command frames without it
# — so an impersonated server can no longer actuate relays.
# GET endpoints (display HTML, /api/lane/N/scoring, /api/state, /api/health)
# stay open — the overhead displays poll them and they send no hardware
# commands. LANE_NODE_TOKEN also configures wsl_api's POST proxy and the Pi's
# command verifier; it is deliberately not the Pi identity credential.
AUTH_TOKEN = os.environ.get("LANE_NODE_TOKEN", "").strip()
ALLOW_UNAUTHENTICATED_BENCH = (
    os.environ.get("WSL_ALLOW_UNAUTHENTICATED_BENCH", "").strip() == "1")

state_lock = threading.Lock()
# Restore lane scoring + ball counters from disk so server restarts
# don't wipe in-progress games. If the load fails (no file, corrupted,
# class-shape mismatch), we start fresh — see state_store.load_lanes
# for the failure-handling.
lane_scoring, ball_counters = load_lanes()
try:
    state_store_module.observe_control_wall_clock()
except Exception:
    log.exception(
        "control wall-clock guard initialization failed; physical "
        "authority will remain unavailable")
# clients/client_metadata are mutated by the WS handler (asyncio thread)
# and read by the HTTP handler thread (health, send_to_*). Guard BOTH
# sides with clients_lock — never held across an await or a send.
clients_lock = threading.Lock()
clients = {}
client_metadata = {}  # node_id -> {"lanes": [...], "protocol_version": N, "connected_at": float, "last_heartbeat": float}
main_loop = None
SERVER_START_TIME = time.time()
_routing_lock = None
_ws_mutation_gate = None
_ws_mutation_gate_owner = None

# A Phase-8 backup spans two databases owned by this process plus wsl.db in
# the caller.  Per-database SQLite backups are individually valid but are not
# one operational cut unless lane/scoring and machine-domain mutations are
# quiesced together.  The authenticated fence endpoints below hold all three
# in-process mutation locks for a bounded lease.  A watchdog timer releases
# them if the backup client dies; a server restart loses the fence, so the
# caller's mandatory post-copy verify fails and the artifact is rejected.
BACKUP_FENCE_MAX_LEASE_S = 900
BACKUP_FENCE_LOCK_TIMEOUT_S = 10.0
BACKUP_FENCE_ACQUIRE_TIMEOUT_S = 8.0
_BACKUP_FENCE_GUARD = threading.Lock()
_BACKUP_FENCE = None
_BACKUP_FENCE_PATHS = {
    "/api/system/backup-fence/acquire",
    "/api/system/backup-fence/verify",
    "/api/system/backup-fence/release",
}
_CLOCK_GUARD_RESET_PATH = "/api/system/clock-guard/reset"
HTTP_BODY_DEADLINE_S = 5.0
HTTP_IO_TIMEOUT_S = 5.0
HTTP_MAX_HANDLERS = 32
SCORING_NODE_TOPOLOGY_ENV = "WSL_SCORING_NODE_TOPOLOGY"
SCORING_NODE_TOKENS_ENV = "WSL_SCORING_NODE_TOKENS"
try:
    DIAGNOSTIC_DB_TIMEOUT_S = max(
        0.05, min(5.0, float(os.environ.get(
            "WSL_DIAGNOSTIC_DB_TIMEOUT_S", "0.5"))))
except ValueError:
    DIAGNOSTIC_DB_TIMEOUT_S = 0.5
DIAGNOSTIC_ASYNC_DEADLINE_S = DIAGNOSTIC_DB_TIMEOUT_S + 0.25
DIAGNOSTIC_WORKER_STALE_S = max(5.0, DIAGNOSTIC_DB_TIMEOUT_S * 6.0)
DIAGNOSTIC_PENDING_ALERT_S = max(5.0, DIAGNOSTIC_DB_TIMEOUT_S * 10.0)
SERVER_BOOT_ID = uuid.uuid4().hex
_control_db_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="control-db")
_diagnostic_worker_lock = threading.Lock()
_diagnostic_worker_stop = threading.Event()
_diagnostic_worker_wake = threading.Event()
_diagnostic_worker_thread = None
_diagnostic_delivery_enforced = False
_diagnostic_status_lock = threading.Lock()
_diagnostic_status = {
    "started": False,
    "heartbeat_monotonic": None,
    "last_success_at": None,
    "last_error": None,
    "consecutive_failures": 0,
    "pending": None,
    "oldest_age_s": None,
    "pending_background_commands": None,
}
_background_command_tasks = set()


def _valid_production_node_id(value):
    """Return True for one bounded, explicit, non-development node id."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    lowered = value.lower()
    return (
        1 <= len(value) <= 128
        and all(
            char.isascii()
            and (char.isalnum() or char in "._:-")
            for char in value
        )
        and lowered != "dev"
        and not lowered.startswith("dev-")
        and not lowered.endswith("-dev")
        and "-dev-" not in lowered
    )


def _scoring_node_topology():
    """Parse the exact node-to-pair release manifest, without a fallback.

    Format: ``node-a=21,22;node-b=23,24``.  Each node owns exactly one
    consecutive odd/even pair, every configured lane appears exactly once,
    and development identities are forbidden.  Missing or malformed policy is
    a control-authority failure, never an invitation to trust HELLO claims.
    """
    raw = os.environ.get(SCORING_NODE_TOPOLOGY_ENV)
    if raw is None or not raw.strip():
        return None, f"{SCORING_NODE_TOPOLOGY_ENV} is not configured"
    topology = {}
    claimed_lanes = set()
    try:
        entries = raw.split(";")
        if any(not entry.strip() for entry in entries):
            raise ValueError("empty topology entry")
        for entry in entries:
            node_text, lane_text = entry.split("=", 1)
            node_id = node_text.strip()
            if not _valid_production_node_id(node_id) or node_id in topology:
                raise ValueError(f"invalid or duplicate node id {node_id!r}")
            lane_parts = [part.strip() for part in lane_text.split(",")]
            if len(lane_parts) != 2 or any(not part for part in lane_parts):
                raise ValueError(f"node {node_id!r} must own exactly two lanes")
            lanes = tuple(sorted(int(part) for part in lane_parts))
            if (
                lanes[0] < 1
                or lanes[1] > 32
                or lanes[0] % 2 != 1
                or lanes[1] != lanes[0] + 1
                or claimed_lanes.intersection(lanes)
            ):
                raise ValueError(f"invalid or overlapping pair for {node_id!r}")
            topology[node_id] = lanes
            claimed_lanes.update(lanes)
    except (TypeError, ValueError):
        return None, f"{SCORING_NODE_TOPOLOGY_ENV} is invalid"
    configured = set(machine_store.configured_lanes())
    if claimed_lanes != configured:
        return None, (
            f"{SCORING_NODE_TOPOLOGY_ENV} lanes must exactly match "
            "WSL_MACHINE_LANES")
    return topology, None


def _scoring_node_tokens():
    """Parse per-node HELLO credentials and bind them to topology keys."""
    topology, topology_error = _scoring_node_topology()
    if topology_error is not None:
        return None, topology_error
    raw = os.environ.get(SCORING_NODE_TOKENS_ENV)
    if raw is None or not raw.strip():
        return None, f"{SCORING_NODE_TOKENS_ENV} is not configured"
    credentials = {}
    try:
        entries = raw.split(";")
        if any(not entry.strip() for entry in entries):
            raise ValueError("empty credential entry")
        for entry in entries:
            node_text, token_text = entry.split("=", 1)
            node_id = node_text.strip()
            token = token_text.strip()
            if (
                node_id in credentials
                or node_id not in topology
                or not 16 <= len(token) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in token)
            ):
                raise ValueError("invalid node credential")
            credentials[node_id] = token
    except (TypeError, ValueError):
        return None, f"{SCORING_NODE_TOKENS_ENV} is invalid"
    if len(set(credentials.values())) != len(credentials):
        return None, (
            f"{SCORING_NODE_TOKENS_ENV} tokens must be distinct per node")
    if AUTH_TOKEN and any(
            hmac.compare_digest(
                token.encode("utf-8"), AUTH_TOKEN.encode("utf-8"))
            for token in credentials.values()):
        return None, (
            f"{SCORING_NODE_TOKENS_ENV} must not reuse LANE_NODE_TOKEN")
    if set(credentials) != set(topology):
        return None, (
            f"{SCORING_NODE_TOKENS_ENV} keys must exactly match "
            f"{SCORING_NODE_TOPOLOGY_ENV}")
    return credentials, None


def _get_ws_mutation_gate():
    global _ws_mutation_gate
    if _ws_mutation_gate is None:
        _ws_mutation_gate = asyncio.Lock()
    return _ws_mutation_gate


async def _backup_fenced_messages(websocket):
    """Yield one WS frame while holding the server-wide mutation gate."""
    async for raw in websocket:
        gate = _get_ws_mutation_gate()
        await gate.acquire()
        try:
            yield raw
        finally:
            gate.release()


def _acquire_ws_mutation_gate(timeout_s):
    """Acquire the asyncio mutation gate from the HTTP server thread.

    The ownership token closes a narrow timeout race: Future.result() can
    time out just after the coroutine acquired the lock.  In that case the
    caller marks the attempt abandoned and releases only the gate owned by
    this attempt, rather than leaving every WS handler blocked.
    """
    loop = main_loop
    if (loop is None or loop.is_closed() or not loop.is_running()):
        return None

    token = str(uuid.uuid4())
    attempt_lock = threading.Lock()
    attempt = {"abandoned": False, "acquired": False}

    async def acquire():
        global _ws_mutation_gate_owner
        gate = _get_ws_mutation_gate()
        await gate.acquire()
        with attempt_lock:
            if attempt["abandoned"]:
                gate.release()
                return None
            attempt["acquired"] = True
            _ws_mutation_gate_owner = token
        return token

    future = asyncio.run_coroutine_threadsafe(acquire(), loop)
    try:
        return future.result(timeout=float(timeout_s))
    except BaseException:
        with attempt_lock:
            attempt["abandoned"] = True
            acquired = attempt["acquired"]
        future.cancel()
        if acquired:
            try:
                _release_ws_mutation_gate(
                    token, timeout_s=BACKUP_FENCE_LOCK_TIMEOUT_S)
            except Exception:
                log.exception(
                    "timed-out backup fence WS gate cleanup failed")
        raise


def _release_ws_mutation_gate(
        owner_token, timeout_s=BACKUP_FENCE_LOCK_TIMEOUT_S):
    loop = main_loop
    if (loop is None or loop.is_closed() or not loop.is_running()):
        return False

    async def release():
        global _ws_mutation_gate_owner
        if _ws_mutation_gate_owner != owner_token:
            return False
        gate = _get_ws_mutation_gate()
        if gate.locked():
            _ws_mutation_gate_owner = None
            gate.release()
            return True
        _ws_mutation_gate_owner = None
        return False

    future = asyncio.run_coroutine_threadsafe(release(), loop)
    return bool(future.result(timeout=float(timeout_s)))


def _release_backup_fence_locked(reason):
    """Release the current fence. Caller must hold _BACKUP_FENCE_GUARD."""
    global _BACKUP_FENCE
    fence = _BACKUP_FENCE
    if fence is None:
        return None
    _BACKUP_FENCE = None
    timer = fence.get("timer")
    if timer is not None and threading.current_thread() is not timer:
        timer.cancel()
    if fence.get("machine_lock"):
        machine_store.release_backup_lock()
    if fence.get("state_db_lock"):
        state_store_module.release_backup_lock()
    if fence.get("state_lock"):
        state_lock.release()
    if fence.get("ws_gate"):
        try:
            _release_ws_mutation_gate(fence.get("ws_gate_token"))
        except Exception:
            log.exception("backup fence WS gate release failed")
    fence["released_reason"] = reason
    fence["released_at_epoch"] = time.time()
    return fence


def _expire_backup_fence(fence_id):
    with _BACKUP_FENCE_GUARD:
        if (_BACKUP_FENCE is not None
                and _BACKUP_FENCE.get("fence_id") == fence_id):
            remaining = (
                float(_BACKUP_FENCE["expires_at_monotonic"])
                - time.monotonic())
            if remaining <= 0:
                log.error(
                    "backup fence %s expired; releasing fail-safe", fence_id)
                _release_backup_fence_locked("lease_expired")
            else:
                # Timer scheduling is not a precision guarantee.  If it fires
                # early, re-arm for the monotonic remainder.  Wall-clock
                # changes can never extend the lock lease.
                timer = threading.Timer(
                    remaining, _expire_backup_fence, args=(fence_id,))
                timer.daemon = True
                _BACKUP_FENCE["timer"] = timer
                timer.start()


def _backup_fence_snapshot():
    with _BACKUP_FENCE_GUARD:
        fence = _BACKUP_FENCE
        expires_at = (
            fence.get("expires_at_monotonic") if fence is not None else None)
        if (fence is not None
                and expires_at is not None
                and time.monotonic() >= float(expires_at)):
            _release_backup_fence_locked("lease_expired_on_access")
            fence = None
        if fence is None:
            return None
        return {
            key: fence[key] for key in (
                "fence_id", "phase", "acquired_at_epoch",
                "expires_at_epoch", "expected_lanes", "lanes",
                "pending_mutations", "safety_ledgers", "stores")
        }


def _backup_fence_blocks(path_only):
    return (
        path_only not in _BACKUP_FENCE_PATHS
        and _backup_fence_snapshot() is not None)


def _sqlite_fence_store_identity(path):
    """Describe the exact locked SQLite file without mutating it."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"backup source database does not exist: {resolved}")
    stat = resolved.stat()
    with sqlite3.connect(str(resolved)) as conn:
        conn.execute("PRAGMA query_only=ON")
        schema_rows = conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        schema_payload = [
            [row[0], row[1], row[2], row[3]] for row in schema_rows]
        schema_version = int(
            conn.execute("PRAGMA schema_version").fetchone()[0])
        user_version = int(
            conn.execute("PRAGMA user_version").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(
            conn.execute("PRAGMA freelist_count").fetchone()[0])
        logical_bytes = conn.serialize()
    return {
        "canonical_path": str(resolved),
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "schema_version": schema_version,
        "user_version": user_version,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "logical_size_bytes": len(logical_bytes),
        "content_sha256": hashlib.sha256(logical_bytes).hexdigest(),
        "schema_sha256": hashlib.sha256(json.dumps(
            schema_payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest(),
    }


def _lane_backup_evidence(expected_lanes):
    """Read closed-lane evidence while state_lock + state DB lock are held."""
    expected_set = set(expected_lanes)
    with sqlite3.connect(state_store_module.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            int(row["lane_id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM lane_session_generations").fetchall()
        }
        pending = conn.execute(
            "SELECT lane_id,event_id,event_type "
            "FROM scoring_event_receipts WHERE consumed_by IS NULL AND "
            "((event_type='ball_event' AND disposition IN "
            "('awaiting_manual','capture_interrupted_manual_only',"
            "'clock_anomaly_manual_only')) "
            "OR (event_type='foul_event' AND disposition='accepted'))"
        ).fetchall()
        pending_diagnostic_incidents = int(conn.execute(
            "SELECT COUNT(*) FROM diagnostic_incident_outbox "
            "WHERE delivered_at IS NULL").fetchone()[0])
        pending_background_commands = conn.execute(
            "SELECT command_id,event_id,lane_id "
            "FROM background_command_deliveries WHERE state='pending' "
            "ORDER BY updated_at,command_id").fetchall()
    manual_by_lane = {}
    foul_by_lane = {}
    for row in pending:
        target = (
            manual_by_lane
            if row["event_type"] == "ball_event" else foul_by_lane)
        target.setdefault(int(row["lane_id"]), []).append(row["event_id"])
    evidence = {}
    errors = []
    safety_ledgers = {
        "diagnostic_incident_outbox_pending_count":
            pending_diagnostic_incidents,
        "background_command_deliveries_pending_count":
            len(pending_background_commands),
    }
    if pending_background_commands:
        errors.append(
            f"{len(pending_background_commands)} background command "
            "deliveries pending")
    extra_scorers = sorted(set(lane_scoring) - expected_set)
    if extra_scorers:
        errors.append(
            f"scoring state exists outside configured lanes: {extra_scorers}")
    for durable_lane, row in sorted(rows.items()):
        if durable_lane not in expected_set and bool(row["active"]):
            errors.append(
                f"active durable generation outside configured lanes: "
                f"{durable_lane}")
    for pending_lane, event_ids in sorted(manual_by_lane.items()):
        if pending_lane not in expected_set:
            errors.append(
                f"pending manual scores outside configured lanes: "
                f"{pending_lane} {event_ids}")
    for pending_lane, event_ids in sorted(foul_by_lane.items()):
        if pending_lane not in expected_set:
            errors.append(
                f"pending foul state outside configured lanes: "
                f"{pending_lane} {event_ids}")
    volatile_foul_lanes = sorted(pending_foul)
    if volatile_foul_lanes:
        errors.append(
            f"unconsumed process-local foul state is present: "
            f"{volatile_foul_lanes}")
    for lane in expected_lanes:
        row = rows.get(lane)
        scorer = lane_scoring.get(lane)
        memory_open = bool(
            scorer is not None and getattr(scorer, "is_active", False))
        durable_open = bool(row is not None and row["active"])
        lane_pending = manual_by_lane.get(lane, [])
        lane_fouls = foul_by_lane.get(lane, [])
        if memory_open or durable_open:
            errors.append(f"lane {lane} is open")
        if memory_open != durable_open:
            errors.append(
                f"lane {lane} scoring snapshot/generation mismatch")
        if lane_pending:
            errors.append(f"lane {lane} has pending manual scores")
        if lane_fouls:
            errors.append(f"lane {lane} has pending foul state")
        evidence[str(lane)] = {
            "open": False,
            "generation_state": (
                "retired" if row is not None else "never_opened"),
            "retired_session_generation": (
                int(row["generation"]) if row is not None else None),
            "pending_manual_scores": list(lane_pending),
            "pending_foul_events": list(lane_fouls),
        }
    return evidence, safety_ledgers, errors


def _acquire_backup_fence(fence_id, lease_seconds, expected_lanes):
    """Acquire one bounded server-owned cross-DB mutation fence."""
    global _BACKUP_FENCE
    configured = sorted(machine_store.configured_lanes())
    expected_lanes = sorted(expected_lanes)
    if expected_lanes != configured:
        return "configured_lane_mismatch", {
            "configured_lanes": configured,
            "expected_lanes": expected_lanes,
        }
    with _BACKUP_FENCE_GUARD:
        if _BACKUP_FENCE is not None:
            if _BACKUP_FENCE.get("fence_id") == fence_id:
                return "replayed", _backup_fence_snapshot_unlocked()
            return "busy", _backup_fence_snapshot_unlocked()
        now = time.time()
        _BACKUP_FENCE = {
            "fence_id": fence_id,
            "phase": "acquiring",
            "requested_at_epoch": now,
            "acquired_at_epoch": None,
            "expires_at_epoch": None,
            "expires_at_monotonic": None,
            "expected_lanes": expected_lanes,
            "lanes": {},
            "pending_mutations": None,
            "safety_ledgers": None,
            "stores": {},
            "ws_gate": False,
            "ws_gate_token": None,
            "state_lock": False,
            "state_db_lock": False,
            "machine_lock": False,
            "timer": None,
        }
        fence = _BACKUP_FENCE
    acquire_deadline = (
        time.monotonic() + BACKUP_FENCE_ACQUIRE_TIMEOUT_S)

    def remaining_acquire_time():
        remaining = acquire_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("backup fence overall acquisition timed out")
        return remaining

    try:
        fence["ws_gate_token"] = _acquire_ws_mutation_gate(
            remaining_acquire_time())
        if fence["ws_gate_token"] is None:
            raise RuntimeError("WebSocket mutation loop unavailable")
        fence["ws_gate"] = True
        if not state_lock.acquire(timeout=remaining_acquire_time()):
            raise TimeoutError("state mutation lock busy")
        fence["state_lock"] = True
        if not state_store_module.acquire_backup_lock(
                remaining_acquire_time()):
            raise TimeoutError("lane-state database lock busy")
        fence["state_db_lock"] = True
        if not machine_store.acquire_backup_lock(
                remaining_acquire_time()):
            raise TimeoutError("machine database lock busy")
        fence["machine_lock"] = True
        fence["stores"] = {
            "lane_state": _sqlite_fence_store_identity(
                state_store_module.DB_PATH),
            "machine_diag": _sqlite_fence_store_identity(
                machine_store.DB_PATH),
        }

        in_flight_receipts = len(_command_ack_waiters)
        lanes, safety_ledgers, errors = _lane_backup_evidence(expected_lanes)
        fence["lanes"] = lanes
        fence["safety_ledgers"] = safety_ledgers
        fence["pending_mutations"] = (
            in_flight_receipts
            + safety_ledgers[
                "background_command_deliveries_pending_count"])
        if fence["pending_mutations"]:
            errors.append(
                f"{fence['pending_mutations']} control mutations in flight "
                "or awaiting receipt")
        if errors:
            with _BACKUP_FENCE_GUARD:
                _release_backup_fence_locked("precondition_failed")
            return "not_quiescent", {
                "errors": errors,
                "lanes": lanes,
                "pending_mutations": fence["pending_mutations"],
                "safety_ledgers": safety_ledgers,
            }

        with _BACKUP_FENCE_GUARD:
            if _BACKUP_FENCE is not fence:
                raise RuntimeError("backup fence ownership changed")
            activated_at = time.time()
            fence["phase"] = "active"
            fence["acquired_at_epoch"] = activated_at
            fence["expires_at_epoch"] = activated_at + lease_seconds
            fence["expires_at_monotonic"] = (
                time.monotonic() + lease_seconds)
            timer = threading.Timer(
                lease_seconds, _expire_backup_fence, args=(fence_id,))
            timer.daemon = True
            fence["timer"] = timer
            timer.start()
            return "acquired", _backup_fence_snapshot_unlocked()
    except Exception as exc:
        with _BACKUP_FENCE_GUARD:
            if _BACKUP_FENCE is fence:
                _release_backup_fence_locked("acquire_failed")
        log.warning("backup fence acquire failed: %s", exc)
        return "failed", {"error": str(exc)}


def _backup_fence_snapshot_unlocked():
    fence = _BACKUP_FENCE
    if fence is None:
        return None
    return {
            key: fence[key] for key in (
                "fence_id", "phase", "acquired_at_epoch",
                "expires_at_epoch", "expected_lanes", "lanes",
                "pending_mutations", "safety_ledgers", "stores")
    }


def _verify_backup_fence(fence_id, expected_lanes):
    """Re-attest the held files; never verify stale acquisition evidence."""
    with _BACKUP_FENCE_GUARD:
        fence = _BACKUP_FENCE
        if (fence is None
                or fence.get("fence_id") != fence_id
                or fence.get("phase") != "active"
                or fence.get("expected_lanes") != expected_lanes):
            return "not_active", None
        if (time.monotonic()
                >= float(fence["expires_at_monotonic"])):
            _release_backup_fence_locked("lease_expired_on_verify")
            return "not_active", None
        try:
            current_stores = {
                "lane_state": _sqlite_fence_store_identity(
                    state_store_module.DB_PATH),
                "machine_diag": _sqlite_fence_store_identity(
                    machine_store.DB_PATH),
            }
        except Exception as exc:
            acquired_stores = fence.get("stores")
            _release_backup_fence_locked(
                "store_identity_unavailable_on_verify")
            return "store_identity_changed", {
                "error": str(exc),
                "acquired_stores": acquired_stores,
                "current_stores": None,
            }
        if current_stores != fence.get("stores"):
            acquired_stores = fence.get("stores")
            _release_backup_fence_locked("store_identity_changed")
            return "store_identity_changed", {
                "acquired_stores": acquired_stores,
                "current_stores": current_stores,
            }
        if (time.monotonic()
                >= float(fence["expires_at_monotonic"])):
            _release_backup_fence_locked("lease_expired_on_verify")
            return "not_active", None
        return "verified", _backup_fence_snapshot_unlocked()


def _build_identity():
    """Resolve the deployed code identity ONCE at startup: short git hash
    of this checkout, falling back to a VERSION file, else None. Exposed
    at /api/health as 'git_hash' (Codex R2-8, 2026-07-21) so deploy.ps1
    on WSL-SRV can record + compare the lane-node build across deploys —
    the schtasks-orphan incident class is 'green deploy, stale code'."""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(
            ['git', '-C', str(repo_root), 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    try:
        text = (repo_root / 'VERSION').read_text(encoding='utf-8').strip()
        if text:
            return text
    except OSError:
        pass
    return None


def _contract_sha256():
    """Digest of the live, parseable contract or ``None``.

    A stale sidecar must never let deployment identity pass while the process
    is unable to load the JSON it claims to enforce.
    """
    return machine_store.contract_status()['sha256']


GIT_HASH = _build_identity()

# ---------------------------------------------------------------------------
# R2-14 (Codex round-2, 2026-07-21): GS-vs-camera disagreement counter.
# The camera (Track A scoring) and the gripper switches (Track B cycle rows'
# gs_mask) are independent standing-pin sensors; per the target-conditions
# catalog (§ gripper rows) their per-pin disagreement is the cross-evidence
# for a dead/stuck GS contact or a drifted camera. The two arrive on
# different paths (WS ball events vs machine-cycle POSTs), so the server is
# the only place both masks exist. Heuristic time-window matching, ALERT-
# ONLY: a disagreement increments a counter and emits ONE 'gs_camera_
# disagree' machine event per lane per quiet period. Component attribution
# stays human (catalog rule).
# ---------------------------------------------------------------------------
GS_CAM_WINDOW_ENV = "WSL_GS_CAM_WINDOW_S"     # max age of the camera mask (0=off)
GS_CAM_QUIET_ENV = "WSL_GS_CAM_QUIET_S"       # min gap between events per lane
_gs_cam_lock = threading.Lock()
_last_camera_mask = {}      # lane -> (mask, epoch_time)
_gs_cam_counts = {}         # lane -> total disagreements observed
_gs_cam_last_event = {}     # lane -> epoch_time of the last emitted event


def _note_camera_mask(lane, mask):
    """Record the newest CAMERA standing-pin mask for a lane. Never raises."""
    try:
        with _gs_cam_lock:
            _last_camera_mask[int(lane)] = (int(mask) & 0x3FF, time.time())
    except Exception:
        pass


def _gs_camera_check(cycle_row):
    """Compare a just-ingested cycle row's gs_mask against the lane's most
    recent camera mask (within the window). Alert-only; never raises."""
    try:
        window = float(os.environ.get(GS_CAM_WINDOW_ENV, "").strip() or 120.0)
    except ValueError:
        window = 120.0
    if window <= 0:
        return
    try:
        gs = cycle_row.get('gs_mask')
        lane = cycle_row.get('lane_id')
        if gs is None or lane is None or cycle_row.get('shadow'):
            return
        with _gs_cam_lock:
            cam = _last_camera_mask.get(lane)
            if cam is None or (time.time() - cam[1]) > window:
                return
            cam_mask = cam[0]
            if cam_mask == (gs & 0x3FF):
                return
            n = _gs_cam_counts.get(lane, 0) + 1
            _gs_cam_counts[lane] = n
            try:
                quiet = float(os.environ.get(GS_CAM_QUIET_ENV, "").strip()
                              or 300.0)
            except ValueError:
                quiet = 300.0
            last = _gs_cam_last_event.get(lane, 0.0)
            emit = (time.time() - last) >= quiet
            if emit:
                _gs_cam_last_event[lane] = time.time()
        if not emit:
            return
        xor = (gs ^ cam_mask) & 0x3FF
        pins = [p for p in range(1, 11) if xor & (1 << (p - 1))]
        row = machine_store.validate_event({
            'lane_id': lane, 'severity': 'warn',
            'event_type': 'gs_camera_disagree', 'code': 'per_pin',
            'detail': {'gs_mask': gs, 'camera_mask': cam_mask,
                       'disagree_pins': pins, 'age_s': round(
                           time.time() - cam[1], 1),
                       'count': n},
        })
        machine_store.insert_events([row])
    except Exception as e:
        log.debug(f"gs_camera_check swallowed: {e}")
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
        roster = ['TEST'] if bowlers is None else bowlers
        for i, name in enumerate(roster):
            ls.add_bowler(name, number=i+1, hdcp=0)
        ls.start()
        ls.scoring_epoch = uuid.uuid4().hex
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


def _process_ball_event(lane, pin_mask=None, scoring_receipt=None,
                        foul_override=None, manual_score=None,
                        bench_ball_operation=None):
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
    if pin_mask is not None:
        # A REAL sensed mask (camera path) — feed the GS-vs-camera
        # disagreement counter (R2-14). Sim fallback masks (pin_mask None
        # here, synthesized below) are never recorded.
        _note_camera_mask(lane, pin_mask)
    persisted_fouls = pending_foul_event_ids(lane)
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
        inferred_foul = bool(
            persisted_fouls or pending_foul.pop(lane, False))
        foul = (inferred_foul if foul_override is None
                else bool(foul_override))
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
        manual_commit = None
        if manual_score is not None:
            manual_commit = {
                "event_id": manual_score["event_id"],
                "request_fingerprint":
                    manual_score["request_fingerprint"],
                "result": {
                    "lane": lane,
                    "event_id": manual_score["event_id"],
                    "pin_mask": pin_mask,
                    "foul": foul,
                    "display": bowl.display if bowl else None,
                },
            }
        bench_commit = None
        if bench_ball_operation is not None:
            bench_commit = {
                **bench_ball_operation,
                "result": {
                    "lane": lane,
                    "pin_mask": pin_mask,
                    "pin_mask_source": (
                        "manual"
                        if bench_ball_operation["request"]["pin_mask"]
                        is not None else "cycle"),
                    "foul": foul,
                    "display": bowl.display if bowl else None,
                    "command_id": bench_ball_operation["command_id"],
                    "issued_at": bench_ball_operation["issued_at"],
                },
            }
            bench_commit.pop("command_id")
        saved = save_lanes(
            lane_scoring, ball_counters,
            scoring_receipt=scoring_receipt,
            consume_foul_lane=(
                lane if foul or manual_score is not None else None),
            manual_score=manual_commit,
            bench_ball_operation=bench_commit)
        if not saved:
            restored_lanes, restored_counters = load_lanes()
            lane_scoring.clear()
            lane_scoring.update(restored_lanes)
            ball_counters.clear()
            ball_counters.update(restored_counters)
            if pending_foul_event_ids(lane):
                pending_foul[lane] = True
            else:
                pending_foul.pop(lane, None)
            raise RuntimeError(
                "scoring snapshot/receipt commit failed; state restored")
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
# Compared against the node's PROTOCOL_VERSION on HELLO; mismatch is rejected
# before it can renew the scoring lease or claim a lane.
# v1 = single-lane (HELLO carries `lane`); v2 = multi-lane (HELLO carries `lanes`).
PROTOCOL_VERSION = 3

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

# Lane-id → True if a foul has been flagged for the next ball on that
# lane. The flag is set by FOUL_EVENT, consumed (and cleared) by the
# next BALL_EVENT. This separates "player crossed the foul line" from
# "player rolled the ball" — they're distinct signals from different
# physical sensors (AL-ZARD foul circuit vs DIELL ball-detect).
pending_foul: dict = {}


def _scoring_epoch_for_lane(lane):
    """Stable epoch for the currently-open scoring object on one lane."""
    with state_lock:
        scoring = lane_scoring.get(lane)
        if scoring is None or not getattr(scoring, "is_active", False):
            return None
        epoch = getattr(scoring, "scoring_epoch", None)
        if isinstance(epoch, str) and epoch.strip() and len(epoch) <= 200:
            return epoch
        # Stable compatibility value for an already-open pre-epoch snapshot;
        # the next save persists it through state_store.
        started = getattr(scoring, "started_at", None)
        if not isinstance(started, str) or not started:
            return None
        lane_ids = sorted(
            int(value) for value in (
                getattr(scoring, "lane_ids", None) or [lane]))
        epoch = "legacy:" + ",".join(map(str, lane_ids)) + ":" + started
        scoring.scoring_epoch = epoch
        return epoch


def _scoring_epochs(lanes):
    return {str(lane): _scoring_epoch_for_lane(lane) for lane in lanes}


def _pending_manual_transition_work(lanes):
    """Summarize unresolved manual balls that forbid topology mutation."""
    result = []
    for lane in sorted({int(value) for value in lanes}):
        for item in pending_manual_events(lane):
            payload = item.get("payload") or {}
            result.append({
                "lane": lane,
                "event_id": item["event_id"],
                "event_created_at": item["event_created_at"],
                "scoring_epoch": payload.get("scoring_epoch"),
            })
    return result


def _league_roster_fingerprint(scoring):
    rows = []
    for bowler in getattr(scoring, "bowlers", []) or []:
        rows.append({
            "number": getattr(bowler, "number", None),
            "name": getattr(bowler, "name", None),
            "hdcp": getattr(bowler, "hdcp", None),
            "average": getattr(bowler, "average", None),
            "starting_lane": getattr(
                bowler, "starting_physical_lane", None),
            "team_id": getattr(bowler, "team_id", None),
            "team_name": getattr(bowler, "team_name", None),
            "bowler_id": getattr(bowler, "bowler_id", None),
        })
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()

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
try:
    SCORING_EVENT_AUTO_APPLY_MAX_AGE_S = max(
        1.0, float(os.environ.get(
            "WSL_SCORING_EVENT_MAX_AGE_S", "30")))
except ValueError:
    SCORING_EVENT_AUTO_APPLY_MAX_AGE_S = 30.0
try:
    MANUAL_SCORE_ALERT_AGE_S = max(
        5.0, float(os.environ.get(
            "WSL_MANUAL_SCORE_ALERT_AGE_S", "60")))
except ValueError:
    MANUAL_SCORE_ALERT_AGE_S = 60.0

def encode(t, **f):
    """Build a server->node frame. Every frame this server sends a node is a
    COMMAND (CYCLE / OPEN_LANE / CLOSE_LANE / RESET / POWER_*), so when
    LANE_NODE_TOKEN is set it is stamped into the frame — the node (review
    #51, symmetric auth) rejects command frames without the matching token.
    An unset token is permitted only by the explicit unauthenticated-bench
    override; production control remains fail-closed."""
    if AUTH_TOKEN and "token" not in f:
        f["token"] = AUTH_TOKEN
    return json.dumps({"type": t, "ts": time.time(), **f})
def decode(r):
    return strict_json_loads(r, max_bytes=65536, max_depth=20, max_nodes=4096)


def encode_command(command_type, lane, command_id=None, issued_at=None,
                   **fields):
    """Create one immutable command identity for ACK/deduplication."""
    return encode(
        command_type, lane=lane,
        command_id=command_id or uuid.uuid4().hex,
        issued_at=(time.time() if issued_at is None else float(issued_at)),
        **fields)


def encode_epoch_sync(lane, session_generation, scoring_epoch,
                      command_id=None):
    """Authorize one renewable, non-actuating desired-state repair.

    The logical identity remains stable for the lane generation, while each
    dispatch receives a fresh bounded authorization timestamp.  Node-side
    receipt binding deliberately treats ``issued_at`` as transport
    authorization (not semantic identity) for this command type only.
    """
    return encode_command(
        Msg.SCORING_EPOCH_SYNC, lane,
        command_id=command_id or f"sync:{lane}:{session_generation}",
        issued_at=time.time(),
        session_generation=session_generation,
        scoring_epoch=scoring_epoch)


try:
    COMMAND_ACK_TIMEOUT_S = max(
        1.0, float(os.environ.get("WSL_COMMAND_ACK_TIMEOUT_S", "10")))
except ValueError:
    COMMAND_ACK_TIMEOUT_S = 10.0
_command_ack_waiters = {}


async def _run_control_db(callable_obj, *args, **kwargs):
    """Run one internally bounded DB call outside the asyncio/default pool."""
    loop = asyncio.get_running_loop()
    call = functools.partial(callable_obj, *args, **kwargs)
    future = loop.run_in_executor(_control_db_executor, call)
    return await asyncio.wait_for(
        future, timeout=DIAGNOSTIC_ASYNC_DEADLINE_S)


def _diagnostic_incident_payload(
        lane, severity, event_type, code, detail):
    event = {
        "lane_id": lane,
        "severity": severity,
        "event_type": event_type,
        "code": code,
        "created_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"),
        "detail": detail,
    }
    # Validate before accepting the incident into the durable outbox.  The
    # outbox stores the producer shape because the normalized shape includes
    # store-owned fields that validate_event deliberately rejects on replay.
    machine_store.validate_event(event)
    semantic = {
        "lane_id": lane,
        "severity": severity,
        "event_type": event_type,
        "code": code,
        "detail": detail,
    }
    canonical = json.dumps(
        semantic, sort_keys=True, separators=(",", ":"), allow_nan=False)
    incident_key = (
        "server-diagnostic-v1:"
        + hashlib.sha256(canonical.encode("utf-8")).hexdigest())
    return incident_key, event


def _enqueue_diagnostic_incident_sync(
        lane, severity, event_type, code, detail):
    incident_key, event = _diagnostic_incident_payload(
        lane, severity, event_type, code, detail)
    row = state_store_module.enqueue_diagnostic_incident(
        incident_key, event, timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
    _diagnostic_worker_wake.set()
    return row


async def _enqueue_diagnostic_incident(
        lane, severity, event_type, code, detail):
    return await _run_control_db(
        _enqueue_diagnostic_incident_sync,
        lane, severity, event_type, code, detail)


def _set_diagnostic_worker_status(*, error=None, delivery_status=None):
    now_mono = time.monotonic()
    with _diagnostic_status_lock:
        _diagnostic_status["heartbeat_monotonic"] = now_mono
        if error is None:
            _diagnostic_status["last_success_at"] = (
                datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"))
            _diagnostic_status["last_error"] = None
            _diagnostic_status["consecutive_failures"] = 0
        else:
            _diagnostic_status["last_error"] = str(error)[:1000]
            _diagnostic_status["consecutive_failures"] += 1
        if delivery_status is not None:
            for field in (
                    "pending", "oldest_age_s",
                    "pending_background_commands"):
                _diagnostic_status[field] = delivery_status.get(field)


def _finalize_dead_background_command(row):
    previous_boot = row["owner_boot_id"] != SERVER_BOOT_ID
    reason = (
        "server_restarted_before_command_receipt"
        if previous_boot else "command_receipt_deadline_expired")
    detail = {
        "event_id": row["event_id"],
        "command_id": row["command_id"],
        "command_status": "indeterminate",
        "reason": reason,
        "owner_boot_id": row["owner_boot_id"],
        "current_boot_id": SERVER_BOOT_ID,
        "issued_at": row["issued_at"],
        "requires_manual_reconciliation": True,
        "automatic_retry_forbidden": True,
    }
    incident_key, event = _diagnostic_incident_payload(
        int(row["lane_id"]), "fault", "scoring_event_transport",
        "cycle_delivery_indeterminate", detail)
    return state_store_module.finalize_background_command_delivery(
        row["command_id"], "indeterminate",
        ack_status="indeterminate", reason=reason,
        incident_key=incident_key, incident_payload=event,
        timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)


def _diagnostic_delivery_worker():
    with _diagnostic_status_lock:
        _diagnostic_status["started"] = True
        _diagnostic_status["heartbeat_monotonic"] = time.monotonic()
    while not _diagnostic_worker_stop.is_set():
        active_row = None
        try:
            stale = state_store_module.stale_background_command_deliveries(
                SERVER_BOOT_ID, time.monotonic(), limit=50,
                timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
            for delivery in stale:
                _finalize_dead_background_command(delivery)

            pending = state_store_module.pending_diagnostic_incidents(
                limit=50, timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
            for active_row in pending:
                event = json.loads(active_row["payload_json"])
                event.update({
                    "source_id": "lane-node-server-incident-outbox",
                    "boot_id": active_row["delivery_id"],
                    "seq": 1,
                })
                normalized = machine_store.validate_event(event)
                machine_store.insert_events_with_disposition(
                    [normalized], timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
                state_store_module.mark_diagnostic_incident_delivered(
                    active_row["outbox_id"],
                    timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
                active_row = None

            delivery_status = (
                state_store_module.diagnostic_delivery_status(
                    timeout_s=DIAGNOSTIC_DB_TIMEOUT_S))
            _set_diagnostic_worker_status(
                error=None, delivery_status=delivery_status)
        except Exception as exc:
            if active_row is not None:
                try:
                    state_store_module.mark_diagnostic_incident_failure(
                        active_row["outbox_id"], exc,
                        timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
                except Exception:
                    pass
            _set_diagnostic_worker_status(error=exc)
            log.warning(
                "diagnostic delivery worker failed closed: %s",
                type(exc).__name__)
        _diagnostic_worker_wake.wait(0.5)
        _diagnostic_worker_wake.clear()


def _start_diagnostic_delivery_worker():
    global _diagnostic_worker_thread
    with _diagnostic_worker_lock:
        if (_diagnostic_worker_thread is not None
                and _diagnostic_worker_thread.is_alive()):
            return _diagnostic_worker_thread
        _diagnostic_worker_stop.clear()
        _diagnostic_worker_thread = threading.Thread(
            target=_diagnostic_delivery_worker,
            name="diagnostic-delivery", daemon=True)
        _diagnostic_worker_thread.start()
        return _diagnostic_worker_thread


def _stop_diagnostic_delivery_worker_for_tests(timeout_s=2.0):
    """Test-only lifecycle hook; production leaves the daemon running."""
    global _diagnostic_worker_thread
    _diagnostic_worker_stop.set()
    _diagnostic_worker_wake.set()
    thread = _diagnostic_worker_thread
    if thread is not None:
        thread.join(timeout=float(timeout_s))
    with _diagnostic_worker_lock:
        if thread is not None and not thread.is_alive():
            _diagnostic_worker_thread = None


def _diagnostic_delivery_health():
    with _diagnostic_status_lock:
        status = dict(_diagnostic_status)
    thread = _diagnostic_worker_thread
    thread_alive = bool(thread is not None and thread.is_alive())
    heartbeat = status.pop("heartbeat_monotonic")
    heartbeat_age = (
        None if heartbeat is None
        else max(0.0, time.monotonic() - heartbeat))
    pending_age = status.get("oldest_age_s")
    status.update({
        "enforced": _diagnostic_delivery_enforced,
        "thread_alive": thread_alive,
        "heartbeat_age_s": (
            None if heartbeat_age is None else round(heartbeat_age, 3)),
        "worker_stale_s": DIAGNOSTIC_WORKER_STALE_S,
        "pending_alert_s": DIAGNOSTIC_PENDING_ALERT_S,
        "db_timeout_s": DIAGNOSTIC_DB_TIMEOUT_S,
    })
    status["ok"] = bool(
        not _diagnostic_delivery_enforced
        or (
            status.get("started")
            and thread_alive
            and heartbeat_age is not None
            and heartbeat_age <= DIAGNOSTIC_WORKER_STALE_S
            and status.get("consecutive_failures") == 0
            and status.get("pending") is not None
            and (pending_age is None
                 or pending_age <= DIAGNOSTIC_PENDING_ALERT_S)))
    return status


def _consume_command_task(task):
    try:
        task.result()
    except BaseException:
        log.debug("background command receipt task ended", exc_info=True)


async def _finalize_ball_cycle_task(
        task, lane, event_id, command_id):
    """Bind a background CYCLE result to its durable intent ledger."""
    try:
        ack = task.result()
        if _command_ack_succeeded(ack):
            await _run_control_db(
                state_store_module.finalize_background_command_delivery,
                command_id, "completed",
                ack_status=ack.get("status"),
                original_status=ack.get("original_status"),
                reason=None, timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
            return
        status = ack.get("status") if isinstance(ack, dict) else "invalid"
        original = (
            ack.get("original_status") if isinstance(ack, dict) else None)
        reason = f"command_{status}"
    except BaseException as exc:
        status = "indeterminate"
        original = None
        reason = f"command_task_{type(exc).__name__}"
    detail = {
        "event_id": event_id,
        "command_id": command_id,
        "command_status": status,
        "original_status": original,
        "reason": reason,
        "requires_manual_reconciliation": True,
        "automatic_retry_forbidden": True,
    }
    incident_key, event = _diagnostic_incident_payload(
        lane, "fault", "scoring_event_transport",
        "cycle_delivery_indeterminate", detail)
    try:
        await _run_control_db(
            state_store_module.finalize_background_command_delivery,
            command_id, "indeterminate",
            ack_status=status, original_status=original, reason=reason,
            incident_key=incident_key, incident_payload=event,
            timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
        _diagnostic_worker_wake.set()
    except Exception:
        # Leave the row pending.  The delivery worker's deadline sweep is the
        # durable dead-man path when this callback cannot reach lane_state.db.
        log.exception(
            "background CYCLE finalization deferred to dead-man sweep")


def _consume_ball_cycle_task(task, lane, event_id, command_id):
    finalizer = asyncio.create_task(_finalize_ball_cycle_task(
        task, lane, event_id, command_id))
    _background_command_tasks.add(finalizer)
    finalizer.add_done_callback(_background_command_tasks.discard)
    finalizer.add_done_callback(_consume_command_task)


async def _send_ball_cycle_before_receipt(
        websocket, lane, event_id, event_created_at):
    """Put the stable ball CYCLE frame on the socket before event receipt.

    The command ACK must be read by ``handle_node`` itself, so this waits only
    for the bounded socket send and leaves the durable receipt task running.
    Reusing a SHA-256-derived, bounded command identity makes a reconnect retry
    non-actuating when the node already completed the pulse. Hashing is
    required because a valid 128-character event_id plus a readable prefix
    would exceed the node command_id contract.
    """
    command_id = "ball-cycle:" + hashlib.sha256(
        event_id.encode("utf-8")).hexdigest()
    try:
        delivery = await _run_control_db(
            state_store_module.begin_background_command_delivery, {
                "command_id": command_id,
                "event_id": event_id,
                "lane_id": lane,
                "command_type": Msg.CYCLE,
                "owner_boot_id": SERVER_BOOT_ID,
                "issued_at": float(event_created_at),
                "deadline_monotonic": (
                    time.monotonic() + COMMAND_SEND_TIMEOUT_S
                    + COMMAND_ACK_TIMEOUT_S + 1.0),
            }, timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
    except Exception as exc:
        try:
            await websocket.close(
                code=1011, reason="command safety ledger unavailable")
        except Exception:
            pass
        raise RuntimeError(
            "command safety ledger unavailable; CYCLE refused") from exc
    if delivery["state"] == "completed":
        # A replay after the node receipt was durably bound needs only the
        # scoring-event ACK.  Sending is unnecessary, though node dedup would
        # make it non-actuating.
        return
    cycle_sent = asyncio.get_running_loop().create_future()
    cycle_task = asyncio.create_task(_send_command_and_wait(
        websocket, encode_command(
            Msg.CYCLE, lane,
            command_id=command_id,
            # Physical-command payload binding includes issued_at. The event
            # creation time is immutable across reconnects, so the stable
            # command ID remains a true duplicate instead of colliding with a
            # freshly generated authorization timestamp.
            issued_at=event_created_at),
        sent_future=cycle_sent))
    cycle_task.add_done_callback(
        lambda task: _consume_ball_cycle_task(
            task, lane, event_id, command_id))
    # The receipt coroutine can fail before it reaches ws.send() (for
    # example, when the same identity is already in flight). Waiting only on
    # cycle_sent would then strand the sole WebSocket reader forever. Surface
    # that early failure while still returning immediately after a successful
    # socket send; the receipt continues in the background.
    done, _pending = await asyncio.wait(
        (cycle_sent, cycle_task), return_when=asyncio.FIRST_COMPLETED)
    if cycle_task in done and not cycle_sent.done():
        await cycle_task
    await cycle_sent


def _command_ack_succeeded(ack):
    return (
        ack.get("status") == "completed"
        or (ack.get("status") == "duplicate"
            and ack.get("original_status") == "completed")
    )


def _record_command_transport(lane, severity, code, detail):
    return _enqueue_diagnostic_incident_sync(
        lane, severity, "command_transport", code, detail)


async def _record_command_transport_async(
        lane, severity, code, detail):
    return await _run_control_db(
        _record_command_transport, lane, severity, code, detail)


async def _send_command_and_wait(ws, msg_str, sent_future=None):
    """Return a verified node receipt; close on indeterminate send/ACK."""
    try:
        frame = decode(msg_str)
        command_id = frame["command_id"]
        lane = frame["lane"]
    except Exception as exc:
        raise ValueError("outbound command lacks command identity") from exc
    if frame.get("type") != Msg.SCORING_EPOCH_SYNC:
        try:
            clock_guard = await asyncio.to_thread(
                state_store_module.observe_control_wall_clock)
        except Exception as exc:
            await _record_command_transport_async(
                lane, "fault", "wall_clock_guard_unavailable", {
                    "command_id": command_id,
                    "command_type": frame.get("type"),
                    "error": type(exc).__name__,
                })
            raise RuntimeError(
                "wall-clock guard unavailable; command refused") from exc
        if clock_guard["anomaly_latched"]:
            await _record_command_transport_async(
                lane, "fault", "wall_clock_anomaly_command_refused", {
                    "command_id": command_id,
                    "command_type": frame.get("type"),
                    "high_water_epoch": clock_guard["high_water_epoch"],
                    "observed_epoch": clock_guard["observed_epoch"],
                })
            raise RuntimeError(
                "wall-clock anomaly latched; command refused")
    receipt = {
        "future": asyncio.get_running_loop().create_future(),
        "websocket": ws,
        "lane": lane,
        "command_type": frame.get("type"),
        "issued_at": frame.get("issued_at"),
    }
    if command_id in _command_ack_waiters:
        raise RuntimeError("duplicate in-flight command_id")
    _command_ack_waiters[command_id] = receipt
    try:
        await asyncio.wait_for(
            ws.send(msg_str), timeout=COMMAND_SEND_TIMEOUT_S)
        if sent_future is not None and not sent_future.done():
            sent_future.set_result(True)
        ack = await asyncio.wait_for(
            asyncio.shield(receipt["future"]), timeout=COMMAND_ACK_TIMEOUT_S)
        if not _command_ack_succeeded(ack):
            await _record_command_transport_async(
                lane, "fault", f"command_{ack['status']}", {
                    "command_id": command_id,
                    "command_type": frame.get("type"),
                    "status": ack["status"],
                    "original_status": ack.get("original_status"),
                })
            return ack
        return ack
    except BaseException as exc:
        if sent_future is not None and not sent_future.done():
            sent_future.set_exception(exc)
        try:
            await _record_command_transport_async(
                lane, "fault", "command_indeterminate", {
                    "command_id": command_id,
                    "command_type": frame.get("type"),
                    "error": type(exc).__name__,
                })
        except Exception:
            log.exception(
                "command incident durability unavailable; closing route")
        try:
            await ws.close(
                code=1011, reason="command delivery indeterminate")
        except Exception:
            pass
        raise
    finally:
        if _command_ack_waiters.get(command_id) is receipt:
            _command_ack_waiters.pop(command_id, None)


def _scoring_metadata(msg):
    """Extract the strict capability record committed with each WS lease."""
    return {
        key: msg.get(key) for key in (
            "scoring_boot_id", "scoring_session_id", "heartbeat_seq",
            "scoring_mode", "camera_calibrated", "camera_ok",
            "camera_code", "outbox", "node_ball_lockout_s")
    }

def _socket_owns_lane(node_id, lane, websocket=None):
    """Return True only for the single registered manifest owner of ``lane``."""
    if node_id is None:
        return True
    with clients_lock:
        if websocket is not None and clients.get(node_id) is not websocket:
            return False
        meta = client_metadata.get(node_id)
        declared = (meta or {}).get("lanes") or []
        claimants = [
            candidate_id
            for candidate_id, candidate_meta in client_metadata.items()
            if lane in (candidate_meta.get("lanes") or [])
            and clients.get(candidate_id) is not None
        ]
        return (
            lane in declared
            and clients.get(node_id) is not None
            and claimants == [node_id]
        )


def _routing_guard():
    """One event-loop lock serializes owner replacement with command sends."""
    global _routing_lock
    if _routing_lock is None:
        _routing_lock = asyncio.Lock()
    return _routing_lock


async def _register_client(
        node_id, websocket, metadata, scoring_meta=None):
    """Commit and register one non-overlapping node relative to routing.

    A live identity or lane claimant is rejected before it can touch the
    durable scoring lease.  The database work runs off the event loop while
    the routing lock prevents a competing registration from passing the same
    preflight.  No "newest claimant wins" behavior is permitted for physical
    command ownership.
    """
    async with _routing_guard():
        with clients_lock:
            if clients.get(node_id) is not None:
                return None, "node identity already connected"
            for other_id, other_meta in client_metadata.items():
                overlap = (set(metadata.get("lanes") or [])
                           & set(other_meta.get("lanes") or []))
                if overlap and clients.get(other_id) is not None:
                    return None, (
                        f"lanes {sorted(overlap)} already connected as "
                        f"{other_id!r}")
        committed = None
        if scoring_meta is not None:
            try:
                await _run_control_db(
                    machine_store.accept_scoring_boot,
                    node_id, scoring_meta["scoring_boot_id"],
                    scoring_meta["scoring_session_id"],
                    timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
                committed = await _run_control_db(
                    machine_store.touch_scoring_lanes,
                    metadata.get("lanes") or [], scoring_meta,
                    timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
            except Exception as exc:
                return None, (
                    f"scoring lease commit failed ({type(exc).__name__})")
        with clients_lock:
            # All registration/unregistration flows hold _routing_guard, so
            # the preflight remains true until this point.
            clients[node_id] = websocket
            client_metadata[node_id] = dict(metadata)
        return committed, None


async def _unregister_client(node_id, websocket):
    """Remove only the connection that is still current for ``node_id``."""
    async with _routing_guard():
        with clients_lock:
            if node_id and clients.get(node_id) is websocket:
                del clients[node_id]
                client_metadata.pop(node_id, None)
                log.info(f"Node {node_id!r} disconnected")


def _strict_event_timestamp(value):
    """Accept finite epoch seconds no more than five minutes in the future."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) <= time.time() + 300.0
    )


def _valid_ball_frame(msg):
    """Exact Track-A BALL_EVENT schema; malformed input has no side effect."""
    if not isinstance(msg, dict):
        return False
    required = {
        "type", "ts", "lane", "pin_mask", "event_id",
        "event_created_at", "scoring_epoch"}
    allowed = required | {"awaiting_manual", "capture_interrupted"}
    if not required <= set(msg) or not set(msg) <= allowed:
        return False
    lane = msg.get("lane")
    if not isinstance(lane, int) or isinstance(lane, bool):
        return False
    if not _strict_event_timestamp(msg.get("ts")):
        return False
    awaiting = msg.get("awaiting_manual", False)
    if type(awaiting) is not bool:
        return False
    capture_interrupted = msg.get("capture_interrupted", False)
    if (type(capture_interrupted) is not bool
            or capture_interrupted and not awaiting):
        return False
    pin_mask = msg.get("pin_mask")
    if awaiting:
        if pin_mask is not None:
            return False
    elif (not isinstance(pin_mask, int) or isinstance(pin_mask, bool)
          or not 0 <= pin_mask <= 0x3FF):
        return False
    event_id = msg.get("event_id")
    if (not isinstance(event_id, str) or not event_id.strip()
            or len(event_id) > 128):
        return False
    event_created = msg.get("event_created_at")
    if not _strict_event_timestamp(event_created):
        return False
    epoch = msg.get("scoring_epoch")
    if epoch is not None and (
            not isinstance(epoch, str) or not epoch.strip()
            or len(epoch) > 200):
        return False
    return True


def _valid_foul_frame(msg):
    """Exact Track-A FOUL_EVENT schema; malformed input has no side effect."""
    if not isinstance(msg, dict):
        return False
    allowed = {
        "type", "ts", "lane", "event_id", "event_created_at",
        "scoring_epoch"}
    if set(msg) != allowed:
        return False
    lane = msg.get("lane")
    if (not isinstance(lane, int) or isinstance(lane, bool)
            or not _strict_event_timestamp(msg.get("ts"))):
        return False
    event_id = msg.get("event_id")
    if (not isinstance(event_id, str) or not event_id.strip()
            or len(event_id) > 128):
        return False
    event_created = msg.get("event_created_at")
    if not _strict_event_timestamp(event_created):
        return False
    epoch = msg.get("scoring_epoch")
    if epoch is not None and (
            not isinstance(epoch, str) or not epoch.strip()
            or len(epoch) > 200):
        return False
    return True


def _scoring_receipt(node_id, msg, disposition):
    return {
        "event_id": msg["event_id"],
        "node_id": node_id,
        "lane_id": msg["lane"],
        "event_type": msg["type"],
        "event_created_at": msg["event_created_at"],
        "payload": msg,
        "disposition": disposition,
    }


def _receipt_matches(existing, node_id, msg):
    try:
        payload = json.dumps(msg, sort_keys=True, separators=(",", ":"))
        return (
            existing["node_id"] == node_id
            and int(existing["lane_id"]) == msg["lane"]
            and existing["event_type"] == msg["type"]
            and float(existing["event_created_at"])
            == float(msg["event_created_at"])
            and existing["payload_json"] == payload)
    except Exception:
        return False


async def _ack_scoring_event(websocket, msg, disposition):
    await websocket.send(encode(
        Msg.SCORING_EVENT_ACK,
        event_id=msg["event_id"],
        disposition=disposition,
        committed_at=datetime.now(timezone.utc).isoformat()))


def _record_stale_scoring_event(node_id, msg, expected_epoch):
    """Make a cross-game event visible without applying it to a score."""
    return _enqueue_diagnostic_incident_sync(
        msg["lane"], "fault", "scoring_event_transport",
        "stale_scoring_epoch", {
            "event_id": msg["event_id"],
            "node_id": node_id,
            "event_type": msg["type"],
            "event_created_at": msg["event_created_at"],
            "received_epoch": msg.get("scoring_epoch"),
            "expected_epoch": expected_epoch,
            "pin_mask": msg.get("pin_mask"),
            "awaiting_manual": msg.get("awaiting_manual", False),
            "requires_manual_reconciliation": True,
        })


async def _record_stale_scoring_event_async(
        node_id, msg, expected_epoch):
    return await _run_control_db(
        _record_stale_scoring_event, node_id, msg, expected_epoch)


def _record_overdue_scoring_event(node_id, msg):
    """Publish a durable operator-reconciliation fault for a late sensor event."""
    age = max(0.0, time.time() - float(msg["event_created_at"]))
    return _enqueue_diagnostic_incident_sync(
        msg["lane"], "fault", "scoring_event_transport",
        "overdue_scoring_event", {
            "event_id": msg["event_id"],
            "node_id": node_id,
            "event_type": msg["type"],
            "event_created_at": msg["event_created_at"],
            "age_s": round(age, 3),
            "scoring_epoch": msg.get("scoring_epoch"),
            "pin_mask": msg.get("pin_mask"),
            "requires_manual_reconciliation": True,
        })


async def _record_overdue_scoring_event_async(node_id, msg):
    return await _run_control_db(
        _record_overdue_scoring_event, node_id, msg)


async def _record_cycle_delivery_reconciliation(
        node_id, msg, disposition, age_s, reason):
    """Expose a committed score whose matching CYCLE can no longer be retried.

    A score receipt is durable before the socket send.  If the process dies in
    that narrow interval, a later duplicate proves the score is committed but
    cannot prove that the physical command reached the node.  Once its bounded
    authorization or scoring epoch is no longer current, fail safe (no stale
    pulse) and create a durable operator incident instead of silently retiring
    the Pi event.
    """
    await _record_manual_score_state_async(
        msg["lane"], msg["event_id"], "fault",
        "cycle_delivery_indeterminate",
        node_id=node_id,
        scoring_disposition=disposition,
        event_created_at=msg["event_created_at"],
        age_s=round(max(0.0, age_s), 3),
        scoring_epoch=msg.get("scoring_epoch"),
        current_scoring_epoch=_scoring_epoch_for_lane(msg["lane"]),
        reason=reason,
        requires_manual_reconciliation=True)


def _record_manual_score_state(lane, event_id, severity, code, **detail):
    return _enqueue_diagnostic_incident_sync(
        lane, severity, "scoring_event_transport", code, {
            "event_id": event_id,
            **detail,
        })


async def _record_manual_score_state_async(
        lane, event_id, severity, code, **detail):
    return await _run_control_db(
        _record_manual_score_state,
        lane, event_id, severity, code, **detail)


async def handle_node(websocket):
    addr = websocket.remote_address
    log.info(f"New connection from {addr}")
    node_id = None
    authed = False
    message_stream = _backup_fenced_messages(websocket)
    try:
        async for raw in message_stream:
            try:
                msg = decode(raw)
                if not isinstance(msg, dict):
                    raise ValueError(
                        "WebSocket frame must be a JSON object")
            except Exception as exc:
                log.warning(
                    "Closing malformed node frame from %r: %s", addr, exc)
                await websocket.close(
                    code=4400, reason="invalid JSON control frame")
                return
            try:
                clock_guard = await asyncio.to_thread(
                    state_store_module.observe_control_wall_clock)
            except Exception as exc:
                log.error(
                    "Closing node %r: wall-clock guard unavailable (%s)",
                    node_id or addr, type(exc).__name__)
                await websocket.close(
                    code=1011, reason="clock authority unavailable")
                return
            mt = msg.get("type")

            if mt == Msg.HELLO:
                if node_id is not None:
                    log.warning(f"Rejecting repeated HELLO from {addr}")
                    await websocket.close(
                        code=4400, reason="HELLO already registered")
                    return
                candidate_node = msg.get("node")
                candidate_id = (
                    candidate_node.strip()
                    if isinstance(candidate_node, str) else None)
                supplied = msg.get("token") or ""
                if ALLOW_UNAUTHENTICATED_BENCH:
                    # Preserve the old shared-token bench harness when one is
                    # deliberately configured. Production never uses this
                    # branch and therefore never accepts a shared Pi identity.
                    if AUTH_TOKEN and not (
                        isinstance(supplied, str)
                        and hmac.compare_digest(supplied, AUTH_TOKEN)
                    ):
                        await websocket.close(code=4401, reason="auth failed")
                        return
                elif not AUTH_TOKEN:
                    log.error(
                        "Rejecting HELLO from %r: LANE_NODE_TOKEN is not "
                        "configured", addr)
                    await websocket.close(
                        code=4401, reason="server auth is not configured")
                    return
                else:
                    node_tokens, token_error = _scoring_node_tokens()
                    expected_token = (
                        node_tokens.get(candidate_id)
                        if node_tokens is not None and candidate_id is not None
                        else None)
                    if (
                        token_error is not None
                        or not isinstance(supplied, str)
                        or expected_token is None
                        or not hmac.compare_digest(supplied, expected_token)
                    ):
                        log.warning(
                            "Rejecting HELLO from %r: per-node credential "
                            "failed (node=%r, policy_error=%r)",
                            addr, candidate_node, token_error)
                        await websocket.close(
                            code=4401, reason="node authentication failed")
                        return
                node_version = msg.get("protocol_version")
                raw_lanes = msg.get("lanes") or (
                    [msg["lane"]] if "lane" in msg else []
                )
                configured = set(machine_store.configured_lanes())
                topology, topology_error = _scoring_node_topology()
                assigned_lanes = (
                    topology.get(candidate_id)
                    if topology is not None and candidate_id is not None
                    else None)
                hello_ok = (
                    topology_error is None
                    and _valid_production_node_id(candidate_node)
                    and isinstance(node_version, int)
                    and not isinstance(node_version, bool)
                    and node_version == PROTOCOL_VERSION
                    and isinstance(raw_lanes, list)
                    and len(raw_lanes) == 2
                    and all(isinstance(lane, int)
                            and not isinstance(lane, bool)
                            and 1 <= lane <= 32
                            for lane in raw_lanes)
                    and len(set(raw_lanes)) == len(raw_lanes)
                    and assigned_lanes is not None
                    and set(raw_lanes) == set(assigned_lanes)
                    and set(raw_lanes) <= configured
                )
                if not hello_ok:
                    log.warning(
                        f"Rejecting invalid HELLO from {addr}: "
                        f"node={candidate_node!r}, lanes={raw_lanes!r}, "
                        f"protocol={node_version!r}, "
                        f"expected_protocol={PROTOCOL_VERSION}, "
                        f"topology_error={topology_error!r}, "
                        f"assigned_lanes={assigned_lanes!r}, "
                        f"configured_lanes={sorted(configured)!r}")
                    await websocket.close(
                        code=4400, reason="invalid HELLO contract")
                    return
                candidate_id = candidate_node.strip()
                node_lanes = list(assigned_lanes)
                scoring_meta = _scoring_metadata(msg)
                now = time.time()
                committed, register_error = await _register_client(
                    candidate_id, websocket, {
                        "lanes": node_lanes,
                        "credential_authenticated": (
                            not ALLOW_UNAUTHENTICATED_BENCH),
                        "protocol_version": node_version,
                        "scoring_boot_id": scoring_meta["scoring_boot_id"],
                        "scoring_session_id": scoring_meta["scoring_session_id"],
                        "scoring_heartbeat_seq": scoring_meta["heartbeat_seq"],
                        "connected_at": now,
                        "last_heartbeat": now,
                        "scoring_clock_guard": {
                            "observed": scoring_meta["outbox"].get(
                                "scoring_clock_observed"),
                            "anomaly_latched": scoring_meta["outbox"].get(
                                "scoring_clock_anomaly_latched"),
                            "high_water_epoch": scoring_meta["outbox"].get(
                                "scoring_clock_high_water_epoch"),
                            "observed_epoch": scoring_meta["outbox"].get(
                                "scoring_clock_observed_epoch"),
                        },
                    }, scoring_meta=scoring_meta)
                if register_error is not None:
                    log.error(
                        f"Rejecting HELLO from {candidate_id!r}: "
                        f"{register_error}")
                    await websocket.close(
                        code=4409 if "connected" in register_error else 1011,
                        reason=register_error[:120])
                    return
                authed = True
                node_id = candidate_id
                await websocket.send(encode(
                    Msg.HEARTBEAT_ACK, node=node_id,
                    scoring_session_id=committed["scoring_session_id"],
                    heartbeat_seq=committed["heartbeat_seq"],
                    committed_at=committed["committed_at"],
                    scoring_epochs=_scoring_epochs(node_lanes)))
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
                if not _valid_ball_frame(msg):
                    log.warning(
                        f"Node {node_id!r}: malformed BALL_EVENT ignored")
                    continue
                lane = msg.get("lane")
                pin_mask = msg.get("pin_mask")
                awaiting_manual = msg.get("awaiting_manual", False)
                if not _socket_owns_lane(node_id, lane, websocket):
                    log.warning(f"Node {node_id!r}: BALL_EVENT for lane {lane} "
                                f"outside its declared lanes; ignored")
                    continue

                existing = scoring_event_receipt(msg["event_id"])
                if existing is not None:
                    if not _receipt_matches(existing, node_id, msg):
                        log.error(
                            "scoring event_id collision from node %r: %s",
                            node_id, msg["event_id"])
                        await websocket.close(
                            code=4400, reason="scoring event_id collision")
                        return
                    duplicate_age = (
                        time.time() - float(msg["event_created_at"]))
                    duplicate_epoch_current = (
                        msg.get("scoring_epoch")
                        == _scoring_epoch_for_lane(lane))
                    cycle_was_required = existing.get("disposition") in {
                        "accepted", "awaiting_manual"}
                    if cycle_was_required:
                        safe_retry = (
                            not clock_guard["anomaly_latched"]
                            and
                            -5.0 <= duplicate_age
                            <= SCORING_EVENT_AUTO_APPLY_MAX_AGE_S
                            and duplicate_epoch_current)
                        if safe_retry:
                            # The scoring commit may have succeeded just before
                            # the original CYCLE socket send/ACK became
                            # indeterminate. Retry the same command identity
                            # before retiring the Pi event; the node's durable
                            # command ledger prevents a second pulse.
                            await _send_ball_cycle_before_receipt(
                                websocket, lane, msg["event_id"],
                                msg["event_created_at"])
                        else:
                            reason = (
                                "wall_clock_anomaly"
                                if clock_guard["anomaly_latched"]
                                else "scoring_epoch_changed"
                                if not duplicate_epoch_current
                                else "authorization_window_expired")
                            await _record_cycle_delivery_reconciliation(
                                node_id, msg, existing["disposition"],
                                duplicate_age, reason)
                    await _ack_scoring_event(websocket, msg, "duplicate")
                    continue

                event_age = (
                    time.time() - float(msg["event_created_at"]))
                if clock_guard["anomaly_latched"]:
                    record_scoring_event_receipt(_scoring_receipt(
                        node_id, msg, "clock_anomaly_manual_only"))
                    await _record_manual_score_state_async(
                        lane, msg["event_id"], "fault",
                        "wall_clock_anomaly_scoring_event_quarantined",
                        event_created_at=msg["event_created_at"],
                        high_water_epoch=clock_guard["high_water_epoch"],
                        observed_epoch=clock_guard["observed_epoch"],
                        scoring_epoch=msg.get("scoring_epoch"),
                        requires_manual_reconciliation=True,
                        cycle_suppressed=True)
                    await _ack_scoring_event(
                        websocket, msg, "clock_anomaly_quarantined")
                    continue
                if (event_age > SCORING_EVENT_AUTO_APPLY_MAX_AGE_S
                        and awaiting_manual
                        and msg.get("capture_interrupted") is True):
                    # The raw DIELL edge was committed before camera settle,
                    # then recovered after a Pi crash.  It is too old to
                    # authorize CYCLE or automatic scoring, but dropping it
                    # into the generic overdue quarantine would hide it from
                    # the desk's pending-manual workflow.  Preserve it as
                    # explicit operator work with zero actuation.
                    record_scoring_event_receipt(_scoring_receipt(
                        node_id, msg,
                        "capture_interrupted_manual_only"))
                    await _record_manual_score_state_async(
                        lane, msg["event_id"], "fault",
                        "camera_capture_interrupted_manual_score_pending",
                        event_created_at=msg["event_created_at"],
                        age_s=round(max(0.0, event_age), 3),
                        scoring_epoch=msg.get("scoring_epoch"),
                        current_scoring_epoch=_scoring_epoch_for_lane(lane),
                        requires_manual_reconciliation=True,
                        cycle_suppressed=True)
                    await _ack_scoring_event(
                        websocket, msg, "awaiting_manual")
                    continue

                if event_age > SCORING_EVENT_AUTO_APPLY_MAX_AGE_S:
                    record_scoring_event_receipt(_scoring_receipt(
                        node_id, msg, "overdue_quarantined"))
                    await _record_overdue_scoring_event_async(node_id, msg)
                    await _ack_scoring_event(
                        websocket, msg, "overdue_quarantined")
                    continue

                expected_epoch = _scoring_epoch_for_lane(lane)
                if msg.get("scoring_epoch") != expected_epoch:
                    receipt = _scoring_receipt(
                        node_id, msg, "stale_quarantined")
                    record_scoring_event_receipt(receipt)
                    await _record_stale_scoring_event_async(
                        node_id, msg, expected_epoch)
                    await _ack_scoring_event(
                        websocket, msg, "stale_quarantined")
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
                        receipt = _scoring_receipt(
                            node_id, msg, "duplicate_window_suppressed")
                        record_scoring_event_receipt(receipt)
                        await _ack_scoring_event(
                            websocket, msg, "duplicate_window_suppressed")
                        continue

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
                if expected_epoch is None:
                    disposition = "ignored_lane_closed"
                    record_scoring_event_receipt(
                        _scoring_receipt(node_id, msg, disposition))
                    log.warning(
                        f"Lane {lane}: durable BALL ignored because scoring "
                        "is not open")
                elif awaiting_manual or pin_mask is None:
                    disposition = "awaiting_manual"
                    record_scoring_event_receipt(
                        _scoring_receipt(node_id, msg, disposition))
                    await _record_manual_score_state_async(
                        lane, msg["event_id"], "warn",
                        "manual_score_pending",
                        event_created_at=msg["event_created_at"],
                        scoring_epoch=msg.get("scoring_epoch"),
                        requires_manual_reconciliation=True)
                    log.info(f"Lane {lane}: BALL detected (manual mode — "
                             "awaiting /score POST from desk). Sending logical "
                             "CYCLE reply; Track-A physical cycle is OEM-owned.")
                else:
                    disposition = "accepted"
                    _, _, _, fx_payload = _process_ball_event(
                        lane, pin_mask=pin_mask,
                        scoring_receipt=_scoring_receipt(
                            node_id, msg, disposition))

                if expected_epoch is not None:
                    _last_ball_at[lane] = time.monotonic()
                    # Await only the nonblocking socket send, never the
                    # physical command ACK. This preserves reader progress
                    # (the ACK is consumed on the next loop iteration) while
                    # making the documented CYCLE-before-scoring-ACK/FX order
                    # deterministic. A closed lane is deliberately excluded:
                    # an ignored sensor report must never acquire an actuation
                    # side effect.
                    await _send_ball_cycle_before_receipt(
                        websocket, lane, msg["event_id"],
                        msg["event_created_at"])
                await _ack_scoring_event(websocket, msg, disposition)
                # Cosmetic publication is deliberately after the current
                # logical CYCLE reply. In Track A the OEM independently owns
                # physical cycle; FX serialization/transport delays neither.
                if fx_payload is not None:
                    _emit_fx_event(fx_payload)

            elif mt == Msg.FOUL_EVENT:
                if not _valid_foul_frame(msg):
                    log.warning(
                        f"Node {node_id!r}: malformed FOUL_EVENT ignored")
                    continue
                lane = msg.get("lane")
                if not _socket_owns_lane(node_id, lane, websocket):
                    log.warning(f"Node {node_id!r}: FOUL_EVENT for lane {lane} "
                                f"outside its declared lanes; ignored")
                    continue
                existing = scoring_event_receipt(msg["event_id"])
                if existing is not None:
                    if not _receipt_matches(existing, node_id, msg):
                        log.error(
                            "scoring event_id collision from node %r: %s",
                            node_id, msg["event_id"])
                        await websocket.close(
                            code=4400, reason="scoring event_id collision")
                        return
                    await _ack_scoring_event(websocket, msg, "duplicate")
                    continue
                if clock_guard["anomaly_latched"]:
                    record_scoring_event_receipt(_scoring_receipt(
                        node_id, msg, "clock_anomaly_quarantined"))
                    await _record_manual_score_state_async(
                        lane, msg["event_id"], "fault",
                        "wall_clock_anomaly_foul_event_quarantined",
                        event_created_at=msg["event_created_at"],
                        high_water_epoch=clock_guard["high_water_epoch"],
                        observed_epoch=clock_guard["observed_epoch"],
                        scoring_epoch=msg.get("scoring_epoch"),
                        requires_manual_reconciliation=True)
                    await _ack_scoring_event(
                        websocket, msg, "clock_anomaly_quarantined")
                    continue
                if (time.time() - float(msg["event_created_at"])
                        > SCORING_EVENT_AUTO_APPLY_MAX_AGE_S):
                    record_scoring_event_receipt(_scoring_receipt(
                        node_id, msg, "overdue_quarantined"))
                    await _record_overdue_scoring_event_async(node_id, msg)
                    await _ack_scoring_event(
                        websocket, msg, "overdue_quarantined")
                    continue
                expected_epoch = _scoring_epoch_for_lane(lane)
                if msg.get("scoring_epoch") != expected_epoch:
                    record_scoring_event_receipt(
                        _scoring_receipt(
                            node_id, msg, "stale_quarantined"))
                    await _record_stale_scoring_event_async(
                        node_id, msg, expected_epoch)
                    await _ack_scoring_event(
                        websocket, msg, "stale_quarantined")
                    continue
                if expected_epoch is None:
                    record_scoring_event_receipt(
                        _scoring_receipt(
                            node_id, msg, "ignored_lane_closed"))
                    await _ack_scoring_event(
                        websocket, msg, "ignored_lane_closed")
                    continue
                # Flag the next ball on this lane as a foul. If a ball
                # event comes within a reasonable window, it'll consume
                # this flag and score as a foul. If no ball arrives
                # (false trigger, player stepped over without throwing),
                # the flag stays set until the next ball — which is
                # arguably wrong but matches AMF/Brunswick foul semantics
                # where the foul lamp latches until ball-detect fires.
                # OPEN_LANE / CLOSE_LANE clear stale flags for their lanes.
                record_scoring_event_receipt(
                    _scoring_receipt(node_id, msg, "accepted"))
                with state_lock:
                    pending_foul[lane] = True
                log.info(f"Lane {lane}: FOUL flagged (will apply to next ball)")
                await _ack_scoring_event(websocket, msg, "accepted")

            elif mt == Msg.COMMAND_ACK:
                allowed = {
                    "type", "ts", "command_id", "status", "completed_at"}
                if "original_status" in msg:
                    allowed.add("original_status")
                command_id = msg.get("command_id")
                status = msg.get("status")
                waiter = _command_ack_waiters.get(command_id)
                waiter_future = (
                    waiter.get("future") if isinstance(waiter, dict)
                    else None)
                completed_at = msg.get("completed_at")
                if (set(msg) != allowed
                        or not isinstance(command_id, str)
                        or not command_id or len(command_id) > 128
                        or status not in (
                            "completed", "duplicate", "refused",
                            "ambiguous", "failed")
                        or not isinstance(completed_at, (int, float))
                        or isinstance(completed_at, bool)
                        or not math.isfinite(float(completed_at))
                        or waiter_future is None
                        or float(completed_at)
                        < float(waiter.get("issued_at") or 0) - 300.0
                        or float(completed_at) > time.time() + 300.0
                        or waiter_future.done()
                        or waiter.get("websocket") is not websocket
                        or not _socket_owns_lane(
                            node_id, waiter.get("lane"), websocket)):
                    log.warning(
                        f"Node {node_id!r}: invalid/unmatched COMMAND_ACK "
                        "ignored")
                    continue
                if status == "duplicate" and msg.get(
                        "original_status") not in (
                            "completed", "refused", "failed"):
                    log.warning(
                        f"Node {node_id!r}: invalid duplicate COMMAND_ACK "
                        "ignored")
                    continue
                if (status != "duplicate"
                        and "original_status" in msg):
                    log.warning(
                        f"Node {node_id!r}: COMMAND_ACK original_status is "
                        "only valid for duplicate; ignored")
                    continue
                waiter_future.set_result({
                    "command_id": command_id,
                    "status": status,
                    "original_status": msg.get("original_status"),
                    "completed_at": float(msg["completed_at"]),
                })

            elif mt == Msg.HEARTBEAT:
                # Track liveness so send_to_* can tell "delivered to a node
                # that's actually responding" from "buffered to a zombie".
                hb_node = msg.get("node")
                if (node_id is None or not isinstance(hb_node, str)
                        or hb_node != node_id):
                    log.warning(
                        f"Ignoring HEARTBEAT from connection {addr}: "
                        f"registered node={node_id!r}, frame node={hb_node!r}")
                    continue
                hb_lanes = None
                registered = None
                with clients_lock:
                    meta = client_metadata.get(node_id)
                    if (meta is not None
                            and clients.get(node_id) is websocket):
                        registered = dict(meta)
                        hb_lanes = list(meta.get("lanes") or [])
                scoring_meta = _scoring_metadata(msg)
                if (registered is None
                        or scoring_meta["scoring_boot_id"]
                        != registered.get("scoring_boot_id")
                        or scoring_meta["scoring_session_id"]
                        != registered.get("scoring_session_id")):
                    log.warning(
                        f"Closing HEARTBEAT identity mismatch for "
                        f"node={node_id!r}")
                    await websocket.close(
                        code=4400, reason="heartbeat identity mismatch")
                    return
                if hb_lanes:
                    hb_lanes = [
                        lane for lane in hb_lanes
                        if _socket_owns_lane(node_id, lane, websocket)]
                # Track-A WS heartbeats renew scoring-service liveness only.
                # They cannot bless the independent Track-B control loop.
                if hb_lanes:
                    try:
                        committed = await _run_control_db(
                            machine_store.touch_scoring_lanes,
                            hb_lanes, scoring_meta,
                            timeout_s=DIAGNOSTIC_DB_TIMEOUT_S)
                    except Exception as exc:
                        log.error(
                            f"Closing node {node_id!r}: scoring heartbeat "
                            f"commit failed ({type(exc).__name__})")
                        await websocket.close(
                            code=1011,
                            reason="scoring heartbeat commit failed")
                        return
                    with clients_lock:
                        meta = client_metadata.get(node_id)
                        if (meta is not None
                                and clients.get(node_id) is websocket):
                            meta["last_heartbeat"] = time.time()
                            meta["scoring_heartbeat_seq"] = (
                                committed["heartbeat_seq"])
                            meta["scoring_clock_guard"] = {
                                "observed": scoring_meta["outbox"].get(
                                    "scoring_clock_observed"),
                                "anomaly_latched": scoring_meta[
                                    "outbox"].get(
                                        "scoring_clock_anomaly_latched"),
                                "high_water_epoch": scoring_meta[
                                    "outbox"].get(
                                        "scoring_clock_high_water_epoch"),
                                "observed_epoch": scoring_meta[
                                    "outbox"].get(
                                        "scoring_clock_observed_epoch"),
                            }
                    await websocket.send(encode(
                        Msg.HEARTBEAT_ACK, node=node_id,
                        scoring_session_id=committed[
                            "scoring_session_id"],
                        heartbeat_seq=committed["heartbeat_seq"],
                        committed_at=committed["committed_at"],
                        scoring_epochs=_scoring_epochs(hb_lanes)))
    except Exception as e:
        log.warning(f"Handler error: {e}")
    finally:
        await message_stream.aclose()
        await _unregister_client(node_id, websocket)

# A node counts as "reached" only when its last heartbeat (or connect)
# is at most this old. Heartbeats arrive every 5s; 15s = three missed
# beats. Without this, ws.send() to a half-dead socket buffers in the
# kernel and we'd report sent_to=1 for a node that's gone.
HEARTBEAT_FRESH_S = 15
COMMAND_SEND_TIMEOUT_S = 1.0
REQUIRED_SERVICES_ENV = "WSL_PHASE8_REQUIRED_SERVICES"


def _last_seen(meta):
    return max(meta.get("last_heartbeat") or 0, meta.get("connected_at") or 0)


def _scoring_node_topology_status(nodes_meta=None, now=None):
    """Evaluate connected scoring nodes against the exact release manifest."""
    topology, error = _scoring_node_topology()
    _node_tokens, token_error = _scoring_node_tokens()
    now = time.time() if now is None else float(now)
    if nodes_meta is None:
        with clients_lock:
            nodes_meta = {
                node_id: dict(metadata)
                for node_id, metadata in client_metadata.items()
                if clients.get(node_id) is not None
            }
    else:
        nodes_meta = {
            str(node_id): dict(metadata)
            for node_id, metadata in nodes_meta.items()
            if isinstance(metadata, dict)
        }
    reasons = []
    if error is not None:
        reasons.append(error)
        return {
            "ok": False,
            "credential_policy_ok": False,
            "expected_nodes": None,
            "connected_nodes": sorted(nodes_meta),
            "reasons": reasons,
        }
    if token_error is not None and not ALLOW_UNAUTHENTICATED_BENCH:
        reasons.append(token_error)
    expected_ids = set(topology)
    connected_ids = set(nodes_meta)
    for node_id in sorted(expected_ids - connected_ids):
        reasons.append(f"node_{node_id}:missing")
    for node_id in sorted(connected_ids - expected_ids):
        reasons.append(f"node_{node_id}:unexpected")
    for node_id in sorted(expected_ids & connected_ids):
        meta = nodes_meta[node_id]
        declared = meta.get("lanes")
        if (
            not isinstance(declared, list)
            or set(declared) != set(topology[node_id])
            or len(declared) != 2
        ):
            reasons.append(f"node_{node_id}:lane_assignment_mismatch")
        if (
            not ALLOW_UNAUTHENTICATED_BENCH
            and meta.get("credential_authenticated") is not True
        ):
            reasons.append(f"node_{node_id}:credential_unbound")
        if now - _last_seen(meta) > HEARTBEAT_FRESH_S:
            reasons.append(f"node_{node_id}:heartbeat_stale")
    return {
        "ok": not reasons,
        "credential_policy_ok": (
            token_error is None and not ALLOW_UNAUTHENTICATED_BENCH),
        "expected_nodes": {
            node_id: list(topology[node_id]) for node_id in sorted(topology)
        },
        "connected_nodes": sorted(connected_ids),
        "reasons": sorted(set(reasons)),
    }


def _project_scoring_node_topology(rollup, nodes_meta=None):
    """Project global node topology failure into every affected lane."""
    result = rollup if isinstance(rollup, dict) else {
        "ok": False, "lanes": {}}
    status = _scoring_node_topology_status(nodes_meta)
    result["scoring_node_topology"] = status
    if status["ok"]:
        return result
    result["ok"] = False
    topology, topology_error = _scoring_node_topology()
    lanes = result.get("lanes")
    if not isinstance(lanes, dict):
        lanes = {}
        result["lanes"] = lanes
    reason = (
        "scoring_node_topology_invalid"
        if topology_error is not None
        else "scoring_node_topology_unhealthy")
    affected_lanes = (
        sorted(machine_store.configured_lanes())
        if topology is None
        else sorted({lane for pair in topology.values() for lane in pair})
    )
    for lane in affected_lanes:
        entry = lanes.setdefault(str(lane), {"lane_id": lane})
        if entry.get("state") not in {"MAINTENANCE", "FAULT", "OFFLINE"}:
            entry["state"] = "DEGRADED"
        if entry.get("scoring_state") != "OFFLINE":
            entry["scoring_state"] = "DEGRADED"
        for field in ("degraded_reasons", "scoring_reasons"):
            current = entry.get(field)
            current = current if isinstance(current, list) else []
            entry[field] = sorted(set(current + [reason]))
    return result


def _required_services():
    """Parse the release-manifest topology without permissive fallbacks."""
    raw = os.environ.get(REQUIRED_SERVICES_ENV)
    if raw is None or not raw.strip():
        return None, f"{REQUIRED_SERVICES_ENV} is not configured"
    policy = {}
    try:
        for entry in raw.split(";"):
            lane_text, service_text = entry.split("=", 1)
            lane = int(lane_text.strip())
            services = [
                item.strip().lower() for item in service_text.split(",")
                if item.strip()
            ]
            if (not 1 <= lane <= 32 or lane in policy
                    or len(services) != 1
                    or services[0] not in {"controller", "scoring"}):
                raise ValueError(entry)
            policy[lane] = services[0]
    except (TypeError, ValueError):
        return None, f"{REQUIRED_SERVICES_ENV} is invalid"
    configured = set(machine_store.configured_lanes())
    if set(policy) != configured:
        return None, (
            f"{REQUIRED_SERVICES_ENV} lanes must exactly match "
            "WSL_MACHINE_LANES")
    # A paired Pi cannot safely run mutually-exclusive services per lane.
    for lane in sorted(configured):
        mate = lane + 1 if lane % 2 else lane - 1
        if mate in configured and policy[mate] != policy[lane]:
            return None, (
                f"{REQUIRED_SERVICES_ENV} must be uniform per lane pair")
    return policy, None


def _machine_policy_status(rollup):
    """Evaluate configured lanes against the manifest-required services."""
    required, error = _required_services()
    reasons = []
    if error:
        return {
            "ok": False, "required_services": None,
            "reasons": [error],
        }
    lanes = rollup.get("lanes") if isinstance(rollup, dict) else None
    if not isinstance(lanes, dict):
        return {
            "ok": False, "required_services": list(required),
            "reasons": ["machine health lanes unavailable"],
        }
    for lane in machine_store.configured_lanes():
        entry = lanes.get(str(lane))
        if not isinstance(entry, dict):
            reasons.append(f"lane_{lane}:missing")
            continue
        if entry.get("state") == "MAINTENANCE":
            reasons.append(f"lane_{lane}:maintenance")
            continue
        if entry.get("fault") is True:
            reasons.append(f"lane_{lane}:fault")
        service = required[lane]
        if (service == "controller"
                and entry.get("state") != "HEALTHY"):
            reasons.append(
                f"lane_{lane}:controller_{entry.get('state') or 'missing'}")
        if (service == "scoring"
                and entry.get("scoring_state") != "HEALTHY"):
            reasons.append(
                f"lane_{lane}:scoring_"
                f"{entry.get('scoring_state') or 'missing'}")
    return {
        "ok": not reasons,
        "required_services": {
            str(lane): required[lane] for lane in sorted(required)},
        "reasons": sorted(set(reasons)),
    }


def _project_server_clock_authority(rollup):
    """Make a global command-clock refusal visible on every machine lane."""
    result = rollup if isinstance(rollup, dict) else {
        "ok": False, "lanes": {}}
    try:
        clock = state_store_module.control_wall_clock_status()
    except Exception as exc:
        clock = {
            "observed": False,
            "anomaly_latched": True,
            "high_water_epoch": None,
            "observed_epoch": None,
            "error": str(exc),
        }
    result["clock_authority"] = clock
    reason = None
    if not clock.get("observed"):
        reason = "server_clock_authority_unobserved"
    elif clock.get("anomaly_latched"):
        reason = "server_clock_anomaly_latched"
    if reason is None:
        return result
    result["ok"] = False
    lanes = result.get("lanes")
    if not isinstance(lanes, dict):
        lanes = {}
        result["lanes"] = lanes
    for lane in machine_store.configured_lanes():
        entry = lanes.setdefault(str(lane), {"lane_id": lane})
        if entry.get("state") not in {"MAINTENANCE", "FAULT", "OFFLINE"}:
            entry["state"] = "DEGRADED"
        if entry.get("scoring_state") not in {"OFFLINE"}:
            entry["scoring_state"] = "DEGRADED"
        for field in ("degraded_reasons", "scoring_reasons"):
            reasons = entry.get(field)
            if not isinstance(reasons, list):
                reasons = []
            if reason not in reasons:
                reasons.append(reason)
            entry[field] = sorted(set(reasons))
    return result


def _project_diagnostic_delivery_health(rollup):
    """Project a failed incident/dead-man path onto every configured lane."""
    result = rollup if isinstance(rollup, dict) else {
        "ok": False, "lanes": {}}
    delivery = _diagnostic_delivery_health()
    result["diagnostic_delivery"] = delivery
    if delivery["ok"]:
        return result
    result["ok"] = False
    if not delivery.get("started") or not delivery.get("thread_alive"):
        reason = "diagnostic_delivery_worker_unavailable"
    elif (delivery.get("heartbeat_age_s") is None
          or delivery["heartbeat_age_s"] > delivery["worker_stale_s"]):
        reason = "diagnostic_delivery_worker_stale"
    elif delivery.get("consecutive_failures"):
        reason = "diagnostic_delivery_failed"
    else:
        reason = "diagnostic_delivery_backlog_overdue"
    lanes = result.get("lanes")
    if not isinstance(lanes, dict):
        lanes = {}
        result["lanes"] = lanes
    for lane in machine_store.configured_lanes():
        entry = lanes.setdefault(str(lane), {"lane_id": lane})
        if entry.get("state") not in {"MAINTENANCE", "FAULT", "OFFLINE"}:
            entry["state"] = "DEGRADED"
        if entry.get("scoring_state") != "OFFLINE":
            entry["scoring_state"] = "DEGRADED"
        for field in ("degraded_reasons", "scoring_reasons"):
            reasons = entry.get(field)
            if not isinstance(reasons, list):
                reasons = []
            if reason not in reasons:
                reasons.append(reason)
            entry[field] = sorted(set(reasons))
    return result


async def _send_to_all_current(msg_str):
    """Snapshot all routes, then release the guard before waiting on ACKs."""
    async with _routing_guard():
        now = time.time()
        with clients_lock:
            targets = [
                (nid, ws, dict(client_metadata.get(nid) or {}))
                for nid, ws in clients.items()
                if clients.get(nid) is ws
            ]
    sent = 0
    for node_id, ws, meta in targets:
        if now - _last_seen(meta) > HEARTBEAT_FRESH_S:
            continue
        try:
            ack = await _send_command_and_wait(ws, msg_str)
            if _command_ack_succeeded(ack):
                sent += 1
        except Exception as exc:
            log.warning(f"send_to {node_id} failed: {exc}")
    return sent


async def _send_to_current_lane(lane, msg_str):
    """Snapshot routing under the guard; never hold it through actuation."""
    async with _routing_guard():
        now = time.time()
        with clients_lock:
            owners = [
                (float(meta.get("connected_at") or 0.0), nid,
                 clients.get(nid), dict(meta))
                for nid, meta in client_metadata.items()
                if lane in (meta.get("lanes") or [])
                and clients.get(nid) is not None
            ]
        selected = owners[0] if len(owners) == 1 else None
        if selected is not None:
            _, node_id, ws, meta = selected
            current = clients.get(node_id) is ws
            age = now - _last_seen(meta)
        else:
            node_id = ws = meta = None
            current = False
            age = None
    if not owners:
        log.warning(
            f"send_to_lane: no connected node claims lane {lane}; "
            "command refused")
        try:
            frame = decode(msg_str)
            await _record_command_transport_async(
                lane, "fault", "command_no_owner", {
                    "command_id": frame.get("command_id"),
                    "command_type": frame.get("type"),
                })
        except Exception:
            pass
        return 0
    if len(owners) > 1:
        log.warning(
            f"send_to_lane: lane {lane} claimed by "
            f"{[owner[1] for owner in owners]}; command refused")
        try:
            frame = decode(msg_str)
            await _record_command_transport_async(
                lane, "fault", "command_owner_collision", {
                    "command_id": frame.get("command_id"),
                    "command_type": frame.get("type"),
                    "claimants": sorted(owner[1] for owner in owners),
                })
        except Exception:
            pass
        return 0
    if not current or age > HEARTBEAT_FRESH_S:
        reason = "command_owner_superseded" if not current \
            else "command_owner_stale"
        try:
            frame = decode(msg_str)
            await _record_command_transport_async(
                lane, "fault", reason, {
                    "command_id": frame.get("command_id"),
                    "command_type": frame.get("type"),
                    "age_s": age,
                })
        except Exception:
            pass
        return 0
    try:
        ack = await _send_command_and_wait(ws, msg_str)
    except Exception as exc:
        log.warning(
            f"send_to_lane({lane}) -> {node_id} failed: {exc}")
        return 0
    return 1 if _command_ack_succeeded(ack) else 0


def send_to_all_nodes(msg_str):
    """Thread-safe wrapper for the current/fresh all-node route."""
    fut = None
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _send_to_all_current(msg_str), main_loop)
        return fut.result(
            timeout=COMMAND_SEND_TIMEOUT_S + COMMAND_ACK_TIMEOUT_S + 2)
    except Exception as exc:
        if fut is not None:
            fut.cancel()
        log.warning(f"send_to_all failed: {exc}")
        return 0


def send_to_lane(lane, msg_str):
    """Thread-safe, fail-closed lane route; unowned lanes never broadcast."""
    fut = None
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _send_to_current_lane(lane, msg_str), main_loop)
        return fut.result(
            timeout=COMMAND_SEND_TIMEOUT_S + COMMAND_ACK_TIMEOUT_S + 2)
    except Exception as exc:
        if fut is not None:
            fut.cancel()
        log.warning(f"send_to_lane({lane}) failed: {exc}")
        return 0

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
  .controls button:disabled { opacity: 0.45; cursor: not-allowed;
                              background: #222; color: #777; }
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
const pendingOperationPrefix = 'wsl-bench-pending:';

function operationIdentity(lane, op) {
  const storageKey = `${pendingOperationPrefix}${lane}:${op}`;
  let identity = null;
  try {
    identity = JSON.parse(localStorage.getItem(storageKey) || 'null');
  } catch (_) {
    localStorage.removeItem(storageKey);
  }
  if (identity && typeof identity.key === 'string'
      && Number.isFinite(identity.issuedAt)) {
    return { ...identity, storageKey };
  }
  const nonce = (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
  identity = {
    key: `bench-ui:${lane}:${op}:${nonce}`,
    issuedAt: Date.now() / 1000,
  };
  localStorage.setItem(storageKey, JSON.stringify(identity));
  return { ...identity, storageKey };
}

async function scoringState(lane) {
  const response = await fetch(`/api/lane/${lane}/scoring`);
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error(`Lane ${lane} scoring response was not JSON`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Lane ${lane} scoring lookup failed`);
  }
  return data;
}

function openRequestFromState(lane, state) {
  if (state.open) {
    if (state.mode === 'cross_lane' || state.cross_lane === true) {
      throw new Error(
        `Lane ${lane} is in a cross-lane session; use the WSL desk to replay it`);
    }
    if (!Number.isSafeInteger(state.session_generation)
        || state.session_generation <= 0) {
      throw new Error(`Lane ${lane} has no valid active session generation`);
    }
    const bowlers = (state.players || []).map(player => player.name);
    if (!bowlers.every(name => typeof name === 'string'
        && name.trim() === name && name.length > 0)) {
      throw new Error(`Lane ${lane} active roster is not replay-safe`);
    }
    return {
      bowlers,
      send_open_command: true,
      session_generation: state.session_generation,
    };
  }
  const retired = state.retired_session_generation;
  const generation = retired == null ? 1 : Number(retired) + 1;
  if (!Number.isSafeInteger(generation) || generation <= 0) {
    throw new Error(`Lane ${lane} cannot derive the next session generation`);
  }
  const entered = window.prompt(
    `Bowler names for lane ${lane}, comma separated. Blank means an explicit empty roster.`,
    'TEST');
  if (entered === null) return null;
  const bowlers = entered.split(',').map(name => name.trim()).filter(Boolean);
  if (bowlers.length === 0 && !window.confirm(
      `Open lane ${lane} with an explicit empty roster?`)) {
    return null;
  }
  return {
    bowlers,
    send_open_command: true,
    session_generation: generation,
  };
}

async function action(lane, op) {
  if (op === 'trigger-ball') {
    toast('Trigger Ball is disabled here: use the bench API with an explicit operation identity.');
    return;
  }
  let identity = null;
  try {
    const options = { method: 'POST', headers: {} };
    if (op === 'open') {
      const body = openRequestFromState(lane, await scoringState(lane));
      if (body === null) return;
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    } else if (op === 'close') {
      const state = await scoringState(lane);
      const generation = state.open
        ? state.session_generation : state.retired_session_generation;
      if (!Number.isSafeInteger(generation) || generation <= 0) {
        throw new Error(`Lane ${lane} has no session generation to close`);
      }
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify({ session_generation: generation });
    } else if (['reset', 'power-on', 'power-off'].includes(op)) {
      identity = operationIdentity(lane, op);
      options.headers['X-Operation-Key'] = identity.key;
      options.headers['X-Operation-Issued-At'] =
        String(identity.issuedAt);
    } else {
      throw new Error(`Unsupported bench action: ${op}`);
    }
    const response = await fetch(`/api/lane/${lane}/${op}`, options);
    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error(`${op.toUpperCase()} returned a non-JSON response`);
    }
    if (!response.ok || data.ok === false) {
      if (identity && response.status < 500) {
        localStorage.removeItem(identity.storageKey);
      }
      throw new Error(data.error ||
        `${op.toUpperCase()} not confirmed; identical retry retained`);
    }
    if (identity) localStorage.removeItem(identity.storageKey);
    toast(`${op.toUpperCase()} confirmed on lane ${lane}`);
    refresh();
  } catch (error) {
    toast(error.message || String(error));
  }
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
    <button class="trigger-ball" disabled
            title="Use the explicit bench API; dashboard retries cannot safely duplicate scoring.">
      Trigger Ball (API only)</button>
  </div>
  <div class="controls">
    <label>Lane 22:</label>
    <button class="open" onclick="action(22, 'open')">Open Lane</button>
    <button class="close" onclick="action(22, 'close')">Close Lane</button>
    <button class="reset" onclick="action(22, 'reset')">Reset Pins</button>
    <button class="power-on" onclick="action(22, 'power-on')">Power On</button>
    <button class="power-off" onclick="action(22, 'power-off')">Power Off</button>
    <button class="trigger-ball" disabled
            title="Use the explicit bench API; dashboard retries cannot safely duplicate scoring.">
      Trigger Ball (API only)</button>
  </div>
  <div id="lanes" class="empty">Loading...</div>
  <div id="toast" class="toast"></div>
</body></html>
"""

class HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Split path from query so /display?lane=21&mode=league matches /display
        path_only = urlparse(self.path).path
        if _backup_fence_blocks(path_only):
            return self._send(
                503, "application/json",
                b'{"ok":false,"error":"backup_fence_active"}')

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
                epoch = (
                    getattr(ls, "scoring_epoch", None)
                    if ls is not None
                    and getattr(ls, "is_active", False) else None)
            generation = lane_session_generation(lane)
            open_state = (
                resp is not None
                and bool(resp.get("open", getattr(ls, "is_active", False))))
            generation_consistent = (
                (open_state
                 and generation is not None
                 and bool(generation["active"])
                 and generation.get("scoring_epoch") == epoch)
                or (not open_state
                    and (generation is None
                         or not bool(generation["active"]))))
            if not generation_consistent:
                return self._send(
                    503, "application/json",
                    json.dumps({
                        "ok": False,
                        "lane": lane,
                        "error": "scoring_generation_state_inconsistent",
                        "open": open_state,
                        "session_generation": (
                            generation.get("generation")
                            if generation else None),
                        "generation_active": (
                            bool(generation["active"])
                            if generation else None),
                        "snapshot_scoring_epoch": epoch,
                        "generation_scoring_epoch": (
                            generation.get("scoring_epoch")
                            if generation else None),
                    }).encode("utf-8"))
            manual_work = pending_manual_events(lane)
            manual_summary = [{
                "event_id": item["event_id"],
                "event_created_at": item["event_created_at"],
                "received_at": item["received_at"],
                "age_s": round(
                    max(0.0, time.time() - item["received_at"]), 3),
            } for item in manual_work]
            if resp is None:
                # No scoring state for this lane — return a "closed" stub so
                # the display can render "Lane Closed" cleanly instead of erroring.
                return self._send(200, 'application/json',
                                  json.dumps({
                                      "ok": True, "lane": lane, "open": False,
                                      "players": [],
                                      "session_generation": None,
                                      "retired_session_generation": (
                                          generation.get("generation")
                                          if generation else None),
                                      "generation_state": (
                                          "retired" if generation
                                          else "never_opened"),
                                      "scoring_epoch": None,
                                      "pending_manual_scores":
                                          manual_summary,
                                  }).encode('utf-8'))
            resp["session_generation"] = generation["generation"]
            resp["retired_session_generation"] = None
            resp["generation_state"] = "active"
            resp["scoring_epoch"] = epoch
            resp["pending_manual_scores"] = manual_summary
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
                with clients_lock:
                    nodes_meta = {
                        node_id: dict(metadata)
                        for node_id, metadata in client_metadata.items()
                        if clients.get(node_id) is not None
                    }
                payload = _project_diagnostic_delivery_health(
                    _project_scoring_node_topology(
                        _project_server_clock_authority(
                            machine_store.machine_health()),
                        nodes_meta))
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
                machine_rollup = _project_diagnostic_delivery_health(
                    _project_scoring_node_topology(
                        _project_server_clock_authority(
                            machine_store.machine_health()),
                        nodes_meta))
            except Exception as e:
                machine_section = {"ok": False, "error": str(e)}
                machine_rollup = {"ok": False, "lanes": {}}
            contract_section = machine_store.contract_status()
            state_save_section = get_save_status()
            policy_section = _machine_policy_status(machine_rollup)
            topology_section = _scoring_node_topology_status(nodes_meta, now)
            diagnostic_delivery = _diagnostic_delivery_health()
            manual_work = pending_manual_events()
            manual_oldest_age = (
                max(0.0, now - manual_work[0]["received_at"])
                if manual_work else None)
            manual_scoring_ok = (
                manual_oldest_age is None
                or manual_oldest_age <= MANUAL_SCORE_ALERT_AGE_S)
            service_ok = bool(
                machine_section.get("ok")
                and contract_section.get("loaded")
                and contract_section.get("strict")
                and state_save_section.get("ok")
                and policy_section.get("ok")
                and topology_section.get("ok")
                and diagnostic_delivery.get("ok")
                and manual_scoring_ok
                and AUTH_TOKEN
                and not ALLOW_UNAUTHENTICATED_BENCH
            )
            health = {
                "ok": service_ok,
                "uptime_sec": round(uptime_sec, 1),
                "uptime_human": f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m {int(uptime_sec % 60)}s",
                "protocol_version": PROTOCOL_VERSION,
                # Deployed-code identity (R2-8): deploy.ps1 records +
                # compares this across deploys. None when neither git nor
                # a VERSION file could resolve a hash at startup.
                "git_hash": GIT_HASH,
                "build": {
                    "git_hash": GIT_HASH,
                    "contract_sha256": contract_section["sha256"],
                    "contract_loaded": contract_section["loaded"],
                    "contract_strict": contract_section["strict"],
                    "contract_error": contract_section["error"],
                    "started_at": datetime.fromtimestamp(
                        SERVER_START_TIME,
                        timezone.utc).isoformat(timespec='seconds'),
                },
                "auth_enabled": bool(AUTH_TOKEN),
                "unauthenticated_bench_override": bool(
                    ALLOW_UNAUTHENTICATED_BENCH),
                "scoring_policy": {
                    "ball_dedup_s": float(BALL_DEDUP_WINDOW_S),
                    "heartbeat_fresh_s": float(HEARTBEAT_FRESH_S),
                    "required_protocol_version": PROTOCOL_VERSION,
                    "required_services": policy_section[
                        "required_services"],
                    "ok": policy_section["ok"],
                    "reasons": policy_section["reasons"],
                },
                "nodes_connected": nodes_connected,
                "node_topology": topology_section,
                "nodes": [
                    {
                        "node_id": nid,
                        "lanes": meta.get("lanes"),
                        "protocol_version": meta.get("protocol_version"),
                        "credential_authenticated": (
                            meta.get("credential_authenticated") is True),
                        "connected_for_sec": round(now - (meta.get("connected_at") or now), 1),
                        "heartbeat_age_sec": round(now - _last_seen(meta), 1),
                        "heartbeat_fresh": (now - _last_seen(meta)) <= HEARTBEAT_FRESH_S,
                    }
                    for nid, meta in nodes_meta.items()
                ],
                "lanes": lanes_summary,
                "pending_fouls": pending_fouls,
                "manual_scoring": {
                    "ok": manual_scoring_ok,
                    "pending": len(manual_work),
                    "oldest_age_s": (
                        round(manual_oldest_age, 3)
                        if manual_oldest_age is not None else None),
                    "alert_age_s": MANUAL_SCORE_ALERT_AGE_S,
                    "event_ids": [
                        item["event_id"] for item in manual_work[:100]],
                },
                "state_db": str(__import__('state_store').DB_PATH),
                "state_save": state_save_section,
                "diagnostic_delivery": diagnostic_delivery,
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
        or mutate scoring state). Missing production auth is fail-closed;
        WSL_ALLOW_UNAUTHENTICATED_BENCH=1 is the explicit test/bench escape.
        Returns True when the request may proceed; sends the error itself."""
        if not AUTH_TOKEN:
            if ALLOW_UNAUTHENTICATED_BENCH:
                return True
            self._send(
                503, 'application/json',
                b'{"error":"LANE_NODE_TOKEN is not configured"}')
            return False
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
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            return None, b'{"error":"chunked request bodies are unsupported"}'
        try:
            content_length = int(
                self.headers.get('Content-Length', 0) or 0)
        except (TypeError, ValueError):
            self.close_connection = True
            return None, b'{"error":"invalid Content-Length"}'
        if content_length <= 0:
            if required:
                self.close_connection = True
                return None, b'{"error":"JSON body required"}'
            return {}, None
        if content_length > max_bytes:
            self.close_connection = True
            return None, (f'{{"error":"body too large (max {max_bytes} '
                          f'bytes)"}}').encode('utf-8')
        try:
            deadline = time.monotonic() + HTTP_BODY_DEADLINE_S
            chunks = []
            remaining = content_length
            while remaining:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("request body deadline exceeded")
                self.connection.settimeout(
                    max(0.05, min(HTTP_IO_TIMEOUT_S, left)))
                read_size = min(8192, remaining)
                reader = getattr(self.rfile, "read1", self.rfile.read)
                chunk = reader(read_size)
                if not chunk:
                    raise EOFError("request body ended early")
                chunks.append(chunk)
                remaining -= len(chunk)
            raw_body = b"".join(chunks)
            return (
                strict_json_loads(
                    raw_body,
                    max_bytes=max_bytes, max_depth=20, max_nodes=4096),
                None)
        except (TypeError, ValueError, UnicodeDecodeError):
            self.close_connection = True
            return None, b'{"error":"invalid JSON body"}'
        except (EOFError, TimeoutError, socket.timeout, OSError):
            self.close_connection = True
            return None, b'{"error":"incomplete JSON body"}'

    def _handle_backup_fence_post(self, path_only):
        if not AUTH_TOKEN:
            return self._send(
                503, "application/json",
                b'{"ok":false,"error":"backup_fence_requires_authentication"}')
        body, err = self._read_json_body(4096)
        if err:
            return self._send(400, "application/json", err)
        action = path_only.rsplit("/", 1)[-1]
        if action == "acquire":
            required = {"fence_id", "lease_seconds", "expected_lanes"}
        elif action == "verify":
            required = {"fence_id", "expected_lanes"}
        elif action == "release":
            required = {"fence_id"}
        else:
            return self._send(
                404, "application/json", b'{"error":"not found"}')
        if not isinstance(body, dict) or set(body) != required:
            return self._send(
                400, "application/json",
                json.dumps({
                    "ok": False,
                    "error": "invalid_backup_fence_body",
                    "required_fields": sorted(required),
                }).encode("utf-8"))
        fence_id = body.get("fence_id")
        try:
            canonical_fence_id = str(uuid.UUID(fence_id))
        except (ValueError, TypeError, AttributeError):
            canonical_fence_id = None
        if (not isinstance(fence_id, str)
                or canonical_fence_id != fence_id):
            return self._send(
                400, "application/json",
                b'{"ok":false,"error":"fence_id_must_be_canonical_uuid"}')

        if action == "release":
            with _BACKUP_FENCE_GUARD:
                current = _BACKUP_FENCE
                if (current is None
                        or current.get("fence_id") != fence_id):
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"backup_fence_not_owned"}')
                _release_backup_fence_locked("client_release")
            return self._send(
                200, "application/json",
                json.dumps({
                    "ok": True,
                    "fence_id": fence_id,
                    "released": True,
                }).encode("utf-8"))

        expected_lanes = body.get("expected_lanes")
        if (not isinstance(expected_lanes, list)
                or not expected_lanes
                or len(expected_lanes) > 32
                or any(
                    not isinstance(lane, int)
                    or isinstance(lane, bool)
                    or not 1 <= lane <= 32
                    for lane in expected_lanes)
                or len(set(expected_lanes)) != len(expected_lanes)):
            return self._send(
                400, "application/json",
                b'{"ok":false,"error":"expected_lanes_invalid"}')
        expected_lanes = sorted(expected_lanes)

        if action == "verify":
            outcome, detail = _verify_backup_fence(
                fence_id, expected_lanes)
            if outcome == "not_active":
                return self._send(
                    409, "application/json",
                    b'{"ok":false,"error":"backup_fence_not_active"}')
            if outcome == "store_identity_changed":
                return self._send(
                    409, "application/json",
                    json.dumps({
                        "ok": False,
                        "error": "backup_fence_store_identity_changed",
                        **detail,
                    }).encode("utf-8"))
            return self._send(
                200, "application/json",
                json.dumps({"ok": True, **detail}).encode("utf-8"))

        lease_seconds = body.get("lease_seconds")
        if (not isinstance(lease_seconds, int)
                or isinstance(lease_seconds, bool)
                or not 1 <= lease_seconds <= BACKUP_FENCE_MAX_LEASE_S):
            return self._send(
                400, "application/json",
                json.dumps({
                    "ok": False,
                    "error": "lease_seconds_out_of_range",
                    "min": 1,
                    "max": BACKUP_FENCE_MAX_LEASE_S,
                }).encode("utf-8"))
        outcome, detail = _acquire_backup_fence(
            fence_id, lease_seconds, expected_lanes)
        if outcome in {"acquired", "replayed"}:
            return self._send(
                200, "application/json",
                json.dumps({
                    "ok": True,
                    "replayed": outcome == "replayed",
                    **detail,
                }).encode("utf-8"))
        status = 409 if outcome in {
            "busy", "not_quiescent", "configured_lane_mismatch"} else 503
        return self._send(
            status, "application/json",
            json.dumps({
                "ok": False,
                "error": f"backup_fence_{outcome}",
                **(detail or {}),
            }).encode("utf-8"))

    def _handle_clock_guard_reset(self):
        """Authenticated, quiescent, append-only-audited clock recovery."""
        if not AUTH_TOKEN:
            return self._send(
                503, "application/json",
                b'{"ok":false,"error":"clock_reset_requires_authentication"}')
        body, err = self._read_json_body(4096)
        if err:
            return self._send(400, "application/json", err)
        if (not isinstance(body, dict)
                or set(body) != {
                    "confirmed_utc_epoch", "actor_id", "note"}):
            return self._send(
                400, "application/json",
                b'{"ok":false,"error":"invalid_clock_reset_body"}')
        confirmed = body.get("confirmed_utc_epoch")
        if (isinstance(confirmed, bool)
                or not isinstance(confirmed, (int, float))
                or not math.isfinite(float(confirmed))
                or abs(time.time() - float(confirmed)) > 2.0):
            return self._send(
                409, "application/json",
                b'{"ok":false,"error":"confirmed_utc_epoch_not_current"}')
        gate_token = None
        state_acquired = False
        try:
            gate_token = _acquire_ws_mutation_gate(5.0)
            if gate_token is None:
                raise RuntimeError("WebSocket loop unavailable")
            if not state_lock.acquire(timeout=5.0):
                raise RuntimeError("scoring state lock busy")
            state_acquired = True
            with clients_lock:
                connected_meta = {
                    node_id: dict(client_metadata.get(node_id) or {})
                    for node_id in sorted(clients)}
            connected = sorted(connected_meta)
            active_scorers = sorted(
                lane for lane, scorer in lane_scoring.items()
                if getattr(scorer, "is_active", False))
            configured = sorted(machine_store.configured_lanes())
            claimed_lanes = [
                lane
                for metadata in connected_meta.values()
                for lane in (metadata.get("lanes") or [])]
            topology_status = _scoring_node_topology_status(
                connected_meta, float(confirmed))
            clock_failures = []
            for node_id, metadata in connected_meta.items():
                clock = metadata.get("scoring_clock_guard")
                if (not isinstance(clock, dict)
                        or clock.get("observed") is not True
                        or clock.get("anomaly_latched") is not False
                        or not isinstance(
                            clock.get("observed_epoch"), (int, float))
                        or isinstance(
                            clock.get("observed_epoch"), bool)
                        or not math.isfinite(float(
                            clock.get("observed_epoch")))
                        or abs(float(clock["observed_epoch"])
                               - float(confirmed)) > 10.0):
                    clock_failures.append(node_id)
            if (not topology_status.get("ok") or clock_failures
                    or active_scorers or _command_ack_waiters):
                return self._send(
                    409, "application/json",
                    json.dumps({
                        "ok": False,
                        "error": (
                            "clock_reset_requires_coherent_quiescent_system"),
                        "connected_nodes": connected,
                        "configured_lanes": configured,
                        "claimed_lanes": sorted(claimed_lanes),
                        "node_topology": topology_status,
                        "node_clock_failures": clock_failures,
                        "active_scorers": active_scorers,
                        "commands_in_flight": len(_command_ack_waiters),
                    }).encode("utf-8"))
            audit = state_store_module.reset_control_wall_clock(
                float(confirmed), body.get("actor_id"), body.get("note"))
            return self._send(
                200, "application/json",
                json.dumps({
                    "ok": True,
                    "clock_guard": (
                        state_store_module.control_wall_clock_status()),
                    "audit": audit,
                }).encode("utf-8"))
        except ValueError as exc:
            return self._send(
                409, "application/json",
                json.dumps({
                    "ok": False, "error": str(exc)}).encode("utf-8"))
        except Exception as exc:
            log.exception("clock guard reset failed")
            return self._send(
                503, "application/json",
                json.dumps({
                    "ok": False,
                    "error": f"clock_reset_failed:{type(exc).__name__}",
                }).encode("utf-8"))
        finally:
            if state_acquired:
                state_lock.release()
            if gate_token is not None:
                try:
                    _release_ws_mutation_gate(gate_token)
                except Exception:
                    log.exception("clock reset WS gate release failed")

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

        if parts in (
                ['api', 'machine', 'events'],
                ['api', 'machine', 'cycles'],
                ['api', 'machine', 'heartbeat']) \
                and not machine_store.diagnostics_contract_ready():
            status = machine_store.contract_status()
            return self._send(
                503, 'application/json',
                json.dumps({
                    "ok": False,
                    "error": "machine diagnostics contract unavailable",
                    "contract": status,
                }).encode('utf-8'))

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
            # R3-1b (Codex round-3, 2026-07-23): PER-RECORD ingest, never
            # all-or-nothing. The old loop returned a 400 on the FIRST invalid
            # record — which is exactly how the fw_identity poison pill stalled
            # the outbox: one unknown-type record 400'd the whole batch, so the
            # client's cursor-ack never fired and every later record (valid or
            # not) was blocked forever behind it. Now each record is validated
            # independently; the valid ones insert, the invalid ones come back
            # in 'rejected' as {index, error}, and the response is a 2xx (the
            # cursor-ack) for any well-formed array body. The client quarantines
            # the rejected indices and advances its cursor past them.
            rows = []
            row_index = []      # rows[k] came from events[row_index[k]]
            rejected = []
            for i, ev in enumerate(events):
                try:
                    rows.append(machine_store.validate_event(ev))
                    row_index.append(i)
                except ValueError as e:
                    rejected.append({"index": i, "error": str(e)})
            ids = []
            duplicates = 0
            if rows:
                try:
                    ids, duplicates = (
                        machine_store.insert_events_with_disposition(rows))
                except machine_store.StoreDisabled:
                    return self._send(503, 'application/json',
                                      b'{"ok":false,"error":"machine '
                                      b'diagnostics disabled '
                                      b'(WSL_MACHINE_DIAG)"}')
                except Exception as e:
                    # A real store failure (not a bad record) — the client must
                    # NOT advance its cursor, so this is a 5xx, not a 2xx with
                    # rejects. Retry replays the whole segment idempotently.
                    log.warning(f"machine events insert failed: {e}")
                    return self._send(500, 'application/json',
                                      b'{"error":"insert failed"}')
            # This transaction-local disposition cannot inherit another
            # request's duplicate count. In particular, an all-invalid batch
            # never calls the store and correctly reports zero duplicates.
            if len(ids) + duplicates + len(rejected) != len(events):
                log.error("machine event disposition equation violated: "
                          "batch=%s inserted=%s duplicates=%s rejected=%s",
                          len(events), len(ids), duplicates, len(rejected))
                return self._send(500, 'application/json',
                                  b'{"error":"incomplete disposition"}')
            return self._send(200, 'application/json',
                              json.dumps({
                                  "ok": True, "inserted": len(ids),
                                  "duplicates": duplicates,
                                  "accepted": len(ids),
                                  "rejected": rejected,
                                  "ids": ids}).encode('utf-8'))

        if parts == ['api', 'machine', 'cycles']:
            body, err = self._read_json_body(65536)
            if err:
                return self._send(400, 'application/json', err)
            # H4 (Codex audit 2026-07-21): the CANONICAL request shape is
            # {"cycle": {row}} — the shape diag_events.HttpSink.post_cycle has
            # always sent (server/machine_contract.json is the single source
            # of truth; both repos' test suites verify against it). The old
            # code validated the whole body as the row, so every real Pi
            # cycle POST 400'd while fake-vs-fake tests stayed green. A bare
            # row body (no 'cycle' key) is tolerated for compatibility.
            if isinstance(body, dict) and 'cycle' in body:
                body = body['cycle']
            try:
                row = machine_store.validate_cycle(body)
            except ValueError as e:
                # A well-formed one-record delivery receives a complete 2xx
                # acknowledgement and an indexed rejection. The outbox can
                # quarantine this poison row and continue; malformed HTTP/JSON
                # bodies above remain 400.
                return self._send(
                    200, 'application/json',
                    json.dumps({
                        "ok": True,
                        "accepted": 0,
                        "duplicates": 0,
                        "rejected": [{"index": 0, "error": str(e)}],
                        "id": None,
                    }).encode('utf-8'))
            try:
                cycle_id, duplicate = (
                    machine_store.insert_cycle_with_disposition(row))
            except machine_store.StoreDisabled:
                return self._send(503, 'application/json',
                                  b'{"ok":false,"error":"machine diagnostics '
                                  b'disabled (WSL_MACHINE_DIAG)"}')
            except Exception as e:
                log.warning(f"machine cycle insert failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"insert failed"}')
            _gs_camera_check(row)   # R2-14: alert-only, never raises
            return self._send(200, 'application/json',
                              json.dumps({"ok": True,
                                          "accepted": 0 if duplicate else 1,
                                          "duplicates": 1 if duplicate else 0,
                                          "rejected": [],
                                          "id": cycle_id}).encode('utf-8'))

        if parts == ['api', 'machine', 'heartbeat']:
            # R3-2 (Codex round-3, 2026-07-23): the controller_daemon's
            # periodic authenticated lease renewal. The Track-B controller
            # service does NOT send the scoring WS heartbeat (that path is
            # Track-A only) — without this, a healthy-but-quiet controller
            # expired OFFLINE at the 90 s lease window (the wrong-topology
            # bug). This POST touches the lease identically to the WS/ingest
            # path and records the board/firmware/contract identity so a
            # wrong-image board is visible on the desk. The wrapper and full
            # controller envelope are required: a bare lane_id is not proof
            # that the 50 Hz controller loop is alive.
            body, err = self._read_json_body(8192)
            if err:
                return self._send(400, 'application/json', err)
            if not isinstance(body, dict) or set(body) != {'heartbeat'}:
                return self._send(400, 'application/json',
                                  b'{"error":"heartbeat body must be exactly '
                                  b'{\\"heartbeat\\":{...}}"}')
            body = body['heartbeat']
            try:
                validated = machine_store.validate_heartbeat(body)
                lane = validated['lane_id']
                row = machine_store.record_heartbeat(body)
            except ValueError as e:
                return self._send(400, 'application/json',
                                  json.dumps({"error": str(e)}).encode('utf-8'))
            except Exception as e:
                log.warning(f"machine heartbeat failed: {e}")
                return self._send(503, 'application/json',
                                  b'{"ok":false,"error":"heartbeat commit '
                                  b'failed"}')
            return self._send(200, 'application/json',
                              json.dumps({"ok": True, "lane": lane,
                                          "committed": True,
                                          "last_seen":
                                              row.get('controller_seen_at'),
                                          "heartbeat_seq":
                                              row.get('heartbeat_seq'),
                                          "control_loop_seq":
                                              row.get('control_loop_seq'),
                                          }).encode('utf-8'))

        if (len(parts) == 5 and parts[:3] == ['api', 'machine', 'lane']
                and parts[4] == 'maintenance'):
            # R2-10: mechanic maintenance flag — state MAINTENANCE wins
            # over lease/fault derivation and suppresses WSL-side SMS.
            try:
                lane = int(parts[3])
            except ValueError:
                return self._send(400, 'application/json',
                                  b'{"error":"bad lane id"}')
            body, err = self._read_json_body(4096)
            if err:
                return self._send(400, 'application/json', err)
            if (not isinstance(body, dict)
                    or set(body) - {'on', 'note', 'changed_by'}
                    or set(body) < {'on', 'changed_by'}
                    or type(body.get('on')) is not bool):
                return self._send(400, 'application/json',
                                  b'{"error":"body must be {\\"on\\": bool, '
                                  b'\\"changed_by\\": positive int, '
                                  b'\\"note\\": str?}"}')
            try:
                row = machine_store.set_maintenance(
                    lane, body['on'], body.get('note'),
                    changed_by=body.get('changed_by'))
            except ValueError as e:
                return self._send(400, 'application/json',
                                  json.dumps({"error": str(e)}).encode('utf-8'))
            except Exception as e:
                log.warning(f"set_maintenance({lane}) failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"maintenance update failed"}')
            return self._send(200, 'application/json',
                              json.dumps({"ok": True, "lane": lane,
                                          "maintenance": bool(row.get('maintenance'))
                                          }).encode('utf-8'))

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
                    if (not isinstance(body, dict)
                            or set(body) not in (
                                {'by'}, {'acknowledged_by'})):
                        return self._send(400, 'application/json',
                                          b'{"error":"by or acknowledged_by '
                                          b'(positive staff id) '
                                          b'required"}')
                    by = (body.get('by') if 'by' in body
                          else body.get('acknowledged_by'))
                    if (not isinstance(by, int) or isinstance(by, bool)
                            or by <= 0):
                        return self._send(400, 'application/json',
                                          b'{"error":"by or acknowledged_by '
                                          b'(positive staff id) '
                                          b'required"}')
                    row = machine_store.ack_event(event_id, by)
                else:
                    body, err = self._read_json_body(4096)
                    if err:
                        return self._send(400, 'application/json', err)
                    if (not isinstance(body, dict)
                            or set(body) not in (
                                {"resolved_by", "recovery_event_id"},
                                {"resolved_by", "override"})
                            or not isinstance(body.get('resolved_by'), int)
                            or isinstance(body.get('resolved_by'), bool)
                            or body['resolved_by'] <= 0):
                        return self._send(
                            400, 'application/json',
                            b'{"error":"resolution requires recovery_event_id '
                            b'or privileged override evidence"}')
                    if "recovery_event_id" in body:
                        recovery_id = body["recovery_event_id"]
                        if (not isinstance(recovery_id, int)
                                or isinstance(recovery_id, bool)
                                or recovery_id <= 0):
                            return self._send(
                                400, "application/json",
                                b'{"error":"recovery_event_id must be positive"}')
                        row = machine_store.resolve_event(
                            event_id, body["resolved_by"],
                            recovery_event_id=recovery_id)
                        resolution = {
                            "mode": "verified_recovery",
                            "resolved_by": body["resolved_by"],
                            "recovery_event_id": recovery_id,
                        }
                    else:
                        override = body.get("override")
                        if (not isinstance(override, dict)
                                or set(override) != {
                                    "actor_id", "reason"}
                                or override.get("actor_id")
                                != body["resolved_by"]
                                or not isinstance(
                                    override.get("reason"), str)):
                            return self._send(
                                400, "application/json",
                                b'{"error":"override requires matching actor_id and reason"}')
                        row = machine_store.resolve_event(
                            event_id, body["resolved_by"],
                            override_reason=override["reason"])
                        resolution = {
                            "mode": "override_pending",
                            "resolved_by": body["resolved_by"],
                            "actor_id": override["actor_id"],
                            "reason": override["reason"].strip(),
                        }
            except ValueError as e:
                return self._send(
                    400, 'application/json',
                    json.dumps({"error": str(e)}).encode('utf-8'))
            except Exception as e:
                log.warning(f"machine event {parts[4]} failed: {e}")
                return self._send(500, 'application/json',
                                  b'{"error":"update failed"}')
            if row is None:
                return self._send(404, 'application/json',
                                  b'{"error":"event not found"}')
            if parts[4] == "resolve":
                resolution.update({
                    "already_resolved": bool(
                        row.get("already_resolved", False)),
                    "override_pending": bool(
                        row.get("override_pending", False)),
                })
            return self._send(200, 'application/json',
                              json.dumps({"ok": True,
                                          "event": row,
                                          **({"resolution": resolution}
                                             if parts[4] == "resolve"
                                             else {})}).encode('utf-8'))

        return self._send(404, 'application/json', b'{"error":"not found"}')

    def do_POST(self):
        # /api/lane/{N}/{open|close|reset|power-on|power-off|trigger-ball|score}
        if not self._check_auth():
            return
        path_only = urlparse(self.path).path
        if path_only in _BACKUP_FENCE_PATHS:
            return self._handle_backup_fence_post(path_only)
        if _backup_fence_blocks(path_only):
            return self._send(
                503, "application/json",
                b'{"ok":false,"error":"backup_fence_active"}')
        if path_only == _CLOCK_GUARD_RESET_PATH:
            return self._handle_clock_guard_reset()
        if path_only.startswith('/api/machine/'):
            return self._handle_machine_post(path_only)
        if path_only == '/api/fx/test':
            # Cosmetic-only test fire. Unlike trigger-ball, this does not
            # mutate scoring state and cannot send a command to a lane node.
            body, err = self._read_json_body(4096)
            if err:
                return self._send(400, 'application/json', err)
            try:
                lane = int(body.get('lane'))
            except (ValueError, TypeError, AttributeError):
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
        if path_only == "/api/lane/transfer":
            body, err = self._read_json_body(65536)
            if err:
                return self._send(400, "application/json", err)
            required = {
                "from_lane", "to_lane", "paired_from", "paired_to",
                "session_generations", "send_hardware_commands"}
            if not isinstance(body, dict) or set(body) != required:
                return self._send(
                    400, "application/json",
                    b'{"error":"invalid transfer body fields"}')
            from_lane = body.get("from_lane")
            to_lane = body.get("to_lane")
            paired_from = body.get("paired_from")
            paired_to = body.get("paired_to")
            send_hardware = body.get("send_hardware_commands")
            lane_values = [
                value for value in (
                    from_lane, to_lane, paired_from, paired_to)
                if value is not None]
            if (type(send_hardware) is not bool
                    or any(not isinstance(value, int)
                           or isinstance(value, bool)
                           or not 1 <= value <= 32
                           for value in lane_values)
                    or (paired_from is None) != (paired_to is None)):
                return self._send(
                    400, "application/json",
                    b'{"error":"invalid transfer lanes or send_hardware_commands"}')
            sources = [from_lane]
            targets = [to_lane]
            if paired_from is not None:
                sources.append(paired_from)
                targets.append(paired_to)
            if (len(set(sources + targets)) != len(sources + targets)
                    or len(sources) != len(targets)):
                return self._send(
                    400, "application/json",
                    b'{"error":"transfer source and target lanes must be distinct"}')
            generations_raw = body.get("session_generations")
            expected_keys = {
                str(lid) for lid in sources + targets}
            if (not isinstance(generations_raw, dict)
                    or set(generations_raw) != expected_keys
                    or any(
                        not isinstance(value, int)
                        or isinstance(value, bool) or value <= 0
                        for value in generations_raw.values())):
                return self._send(
                    400, "application/json",
                    b'{"error":"session_generations must map every source and target lane"}')
            generations = {
                int(key): value
                for key, value in generations_raw.items()}
            request_fp = _request_fingerprint({
                "operation": "transfer",
                "from_lane": from_lane,
                "to_lane": to_lane,
                "paired_from": paired_from,
                "paired_to": paired_to,
                "session_generations": {
                    str(lid): generations[lid]
                    for lid in sorted(generations)},
                "send_hardware_commands": send_hardware,
            })
            rows = {
                lid: lane_session_generation(lid)
                for lid in sources + targets}
            with state_lock:
                target_objects = [
                    lane_scoring.get(lid) for lid in targets]
                replay = (
                    all(
                        rows[lid] is not None
                        and int(rows[lid]["generation"])
                        == generations[lid]
                        and not bool(rows[lid]["active"])
                        and rows[lid].get(
                            "request_fingerprint") == request_fp
                        for lid in sources)
                    and all(
                        rows[lid] is not None
                        and int(rows[lid]["generation"])
                        == generations[lid]
                        and bool(rows[lid]["active"])
                        for lid in targets)
                    and target_objects[0] is not None
                    and all(
                        obj is target_objects[0]
                        for obj in target_objects)
                    and getattr(
                        target_objects[0], "is_active", False)
                    and all(
                        lane_scoring.get(lid) is None
                        for lid in sources))
                if replay:
                    scorer = target_objects[0]
                else:
                    for lid in sources:
                        row = rows[lid]
                        if (row is None
                                or int(row["generation"])
                                != generations[lid]
                                or not bool(row["active"])):
                            return self._send(
                                409, "application/json",
                                json.dumps({
                                    "ok": False,
                                    "error":
                                        "transfer_source_generation_mismatch",
                                    "lane": lid,
                                    "current_generation": (
                                        row["generation"]
                                        if row else None),
                                }).encode("utf-8"))
                    scorer = lane_scoring.get(from_lane)
                    if (scorer is None
                            or not getattr(scorer, "is_active", False)
                            or any(
                                lane_scoring.get(lid) is not scorer
                                for lid in sources)):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"transfer_source_state_mismatch"}')
                    scorer_lanes = set(
                        getattr(scorer, "lane_ids", None)
                        or [getattr(scorer, "lane_id", from_lane)])
                    if scorer_lanes != set(sources):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"transfer_source_pair_mismatch"}')
                    for lid in targets:
                        row = rows[lid]
                        if lane_scoring.get(lid) is not None:
                            return self._send(
                                409, "application/json",
                                json.dumps({
                                    "ok": False,
                                    "error": "transfer_target_occupied",
                                    "lane": lid,
                                }).encode("utf-8"))
                        if (row is not None
                                and generations[lid]
                                <= int(row["generation"])):
                            return self._send(
                                409, "application/json",
                                json.dumps({
                                    "ok": False,
                                    "error":
                                        "transfer_target_generation_not_monotonic",
                                    "lane": lid,
                                    "current_generation":
                                        row["generation"],
                                }).encode("utf-8"))
                    pending_manual_work = (
                        _pending_manual_transition_work(sources))
                    pending_foul_work = [
                        {"lane": lid, "event_id": event_id}
                        for lid in sorted(sources)
                        for event_id in pending_foul_event_ids(lid)]
                    if pending_foul_work or pending_manual_work:
                        return self._send(
                            409, "application/json",
                            json.dumps({
                                "ok": False,
                                "error":
                                    "transfer_source_has_pending_scoring_reconciliation",
                                "pending_foul_events":
                                    pending_foul_work,
                                "pending_manual_scores":
                                    pending_manual_work,
                            }).encode("utf-8"))
                    mapping = dict(zip(sources, targets))
                    epoch = getattr(
                        scorer, "scoring_epoch", None)
                    for lid in sources:
                        lane_scoring.pop(lid, None)
                    if hasattr(scorer, "lane_ids"):
                        scorer.lane_left = mapping[scorer.lane_left]
                        scorer.lane_right = mapping[scorer.lane_right]
                        scorer.lane_ids = [
                            scorer.lane_left, scorer.lane_right]
                        scorer.lane_id = scorer.lane_left
                        scorer._lane_queues = {
                            mapping[lid]: queue
                            for lid, queue
                            in scorer._lane_queues.items()}
                        for bowler in scorer.bowlers:
                            for attr in (
                                    "starting_physical_lane",
                                    "current_physical_lane"):
                                old_lane = getattr(
                                    bowler, attr, None)
                                if old_lane in mapping:
                                    setattr(
                                        bowler, attr,
                                        mapping[old_lane])
                    else:
                        scorer.lane_id = to_lane
                    for source, target in zip(sources, targets):
                        lane_scoring[target] = scorer
                        if source in ball_counters:
                            ball_counters[target] = (
                                ball_counters.pop(source))
                        pending_foul.pop(source, None)
                    for lid in sources + targets:
                        _last_ball_at.pop(lid, None)
                    session_updates = {}
                    for lid in sources:
                        session_updates[lid] = {
                            "generation": generations[lid],
                            "active": False,
                            "scoring_epoch": None,
                            "request_fingerprint": request_fp,
                            "session_group_id":
                                f"transfer-source:{request_fp}",
                        }
                    for lid in targets:
                        session_updates[lid] = {
                            "generation": generations[lid],
                            "active": True,
                            "scoring_epoch": epoch,
                            # A subsequent desired-state OPEN compares
                            # the actual scorer roster when this is null.
                            "request_fingerprint": None,
                            "session_group_id":
                                f"transfer-target:{request_fp}",
                            "open_actuation_authorized": send_hardware,
                        }
                    if not save_lanes(
                            lane_scoring, ball_counters,
                            session_updates=session_updates,
                            clear_foul_lanes=sources + targets,
                            guard_no_pending_manual_lanes=sources):
                        restored, restored_counts = load_lanes()
                        lane_scoring.clear()
                        lane_scoring.update(restored)
                        ball_counters.clear()
                        ball_counters.update(restored_counts)
                        return self._send(
                            503, "application/json",
                            b'{"ok":false,"error":"transfer_state_commit_failed"}')
            epoch = getattr(scorer, "scoring_epoch", None)
            sent_close = 0
            sent_open = 0
            sent_sync = 0
            roster = [b.name for b in scorer.bowlers]
            for lid in sources:
                row = lane_session_generation(lid)
                if send_hardware:
                    delivered = send_to_lane(
                        lid, encode_command(
                            Msg.CLOSE_LANE, lid,
                            command_id=(
                                f"transfer-close:{lid}:"
                                f"{generations[lid]}:{request_fp[:16]}"),
                            issued_at=row["updated_at"],
                            scoring_epoch=None))
                    sent_close += delivered
                else:
                    sent_sync += send_to_lane(
                        lid, encode_epoch_sync(
                            lid, generations[lid], None,
                            command_id=(
                                f"transfer-sync-close:{lid}:"
                                f"{generations[lid]}:{request_fp[:16]}")))
            for lid in targets:
                row = lane_session_generation(lid)
                if send_hardware:
                    delivered = send_to_lane(
                        lid, encode_command(
                            Msg.OPEN_LANE, lid,
                            command_id=(
                                f"transfer-open:{lid}:"
                                f"{generations[lid]}:{request_fp[:16]}"),
                            issued_at=row["updated_at"],
                            bowlers=roster,
                            scoring_epoch=epoch))
                    sent_open += delivered
                else:
                    sent_sync += send_to_lane(
                        lid, encode_epoch_sync(
                            lid, generations[lid], epoch,
                            command_id=(
                                f"transfer-sync-open:{lid}:"
                                f"{generations[lid]}:{request_fp[:16]}")))
            operation_ok = (
                sent_close == len(sources)
                and sent_open == len(targets)
                if send_hardware else
                sent_sync == len(sources) + len(targets))
            return self._send(
                200 if operation_ok else 503, "application/json",
                json.dumps({
                    "ok": operation_ok,
                    "replayed": replay,
                    "from_lane": from_lane,
                    "to_lane": to_lane,
                    "paired_from": paired_from,
                    "paired_to": paired_to,
                    "session_generations": {
                        str(lid): generations[lid]
                        for lid in sorted(generations)},
                    "scoring_epoch": epoch,
                    "request_fingerprint": request_fp,
                    "sent_close_commands": sent_close,
                    "sent_open_commands": sent_open,
                    "sent_epoch_sync_commands": sent_sync,
                    "hardware_commands_sent": send_hardware,
                    "reconciliation_required": not operation_ok,
                }).encode("utf-8"))

        parts = path_only.strip('/').split('/')
        if (len(parts) == 5
                and parts[:2] == ["api", "lane"]
                and parts[3:] == ["score", "resolve"]):
            try:
                lane = int(parts[2])
            except ValueError:
                return self._send(
                    400, "application/json", b'{"error":"bad lane"}')
            body, err = self._read_json_body(4096)
            if err:
                return self._send(400, "application/json", err)
            if (not isinstance(body, dict)
                    or set(body) != {
                        "event_id", "actor_id", "disposition", "note"}):
                return self._send(
                    400, "application/json",
                    b'{"error":"exact event_id, actor_id, disposition, note fields required"}')
            event_id = body.get("event_id")
            actor_id = body.get("actor_id")
            disposition = body.get("disposition")
            note = body.get("note")
            if (not 1 <= lane <= 32
                    or not isinstance(event_id, str)
                    or event_id != event_id.strip()
                    or not event_id or len(event_id) > 128
                    or not isinstance(actor_id, int)
                    or isinstance(actor_id, bool) or actor_id <= 0
                    or disposition not in {
                        "false_trigger_discarded", "session_abandoned"}
                    or not isinstance(note, str)
                    or not note.strip() or len(note.strip()) > 500):
                return self._send(
                    400, "application/json",
                    b'{"error":"invalid manual score resolution"}')
            note = note.strip()
            fingerprint = _request_fingerprint({
                "operation": "resolve_manual_score",
                "lane": lane,
                "event_id": event_id,
                "actor_id": actor_id,
                "disposition": disposition,
                "note": note,
            })
            try:
                outcome, resolution = resolve_manual_score_event(
                    event_id, lane, actor_id, disposition, note, fingerprint)
            except (ValueError, sqlite3.Error) as exc:
                log.warning(
                    "manual score resolution failed lane=%s event=%s: %s",
                    lane, event_id, exc)
                return self._send(
                    503, "application/json",
                    b'{"ok":false,"error":"manual_score_resolution_commit_failed"}')
            if outcome == "conflict":
                return self._send(
                    409, "application/json",
                    b'{"ok":false,"error":"manual_score_resolution_idempotency_conflict"}')
            if outcome == "already_scored":
                return self._send(
                    409, "application/json",
                    b'{"ok":false,"error":"manual_scoring_event_already_scored"}')
            if outcome == "not_pending":
                return self._send(
                    409, "application/json",
                    b'{"ok":false,"error":"manual_scoring_event_not_pending"}')
            replayed = outcome == "replayed"
            if not replayed:
                _record_manual_score_state(
                    lane, event_id, "info",
                    "manual_score_resolved_without_score",
                    actor_id=actor_id,
                    disposition=disposition,
                    note=note,
                    requires_manual_reconciliation=False)
            public_resolution = {
                key: resolution[key] for key in (
                    "event_id", "lane_id", "actor_id", "disposition",
                    "note", "created_at")}
            return self._send(
                200, "application/json",
                json.dumps({
                    "ok": True,
                    "replayed": replayed,
                    "resolution": public_resolution,
                }).encode("utf-8"))

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
                body, err = self._read_json_body(4096)
                if err:
                    return self._send(400, 'application/json', err)
                if (not isinstance(body, dict)
                        or set(body) - {"event_id", "pin_mask", "foul"}
                        or "event_id" not in body):
                    return self._send(
                        400, "application/json",
                        b'{"error":"exact event_id, pin_mask, foul? fields required"}')
                event_id = body.get("event_id")
                if (not isinstance(event_id, str) or not event_id.strip()
                        or len(event_id) > 128):
                    return self._send(
                        400, "application/json",
                        b'{"error":"event_id must be a non-empty string"}')
                if 'pin_mask' not in body or body['pin_mask'] is None:
                    return self._send(400, 'application/json',
                                      b'{"error":"pin_mask required (int 0-1023)"}')
                if isinstance(body['pin_mask'], bool):
                    return self._send(400, 'application/json',
                                      b'{"error":"pin_mask must be int 0-1023"}')
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
                if foul_in is not None and type(foul_in) is not bool:
                    return self._send(
                        400, "application/json",
                        b'{"error":"foul must be true or false"}')
                fingerprint = hashlib.sha256(json.dumps({
                    "lane": lane,
                    "event_id": event_id,
                    "pin_mask": pin_mask_in,
                    "foul": foul_in,
                }, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8")).hexdigest()
                prior = manual_score_receipt(event_id)
                if prior is not None:
                    if prior["request_fingerprint"] != fingerprint:
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"manual_score_idempotency_conflict"}')
                    replay = dict(prior["result"])
                    replay.update({"ok": True, "replayed": True})
                    return self._send(
                        200, "application/json",
                        json.dumps(replay).encode("utf-8"))
                resolved = manual_score_resolution(event_id)
                if resolved is not None:
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error":
                                "manual_scoring_event_resolved_without_score",
                            "resolution": {
                                key: resolved[key] for key in (
                                    "event_id", "lane_id", "actor_id",
                                    "disposition", "note", "created_at")},
                        }).encode("utf-8"))
                work = next((
                    item for item in pending_manual_events(lane)
                    if item["event_id"] == event_id), None)
                if work is None:
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"manual_scoring_event_not_pending"}')
                with state_lock:
                    ls = lane_scoring.get(lane)
                    lane_open = (
                        ls is not None
                        and getattr(ls, 'is_active', False))
                    current_epoch = (
                        getattr(ls, "scoring_epoch", None)
                        if lane_open else None)
                if not lane_open:
                    return self._send(
                        409, 'application/json',
                        json.dumps({
                            'ok': False,
                            'error': f'Lane {lane} not open',
                            "event_id": event_id,
                        }).encode('utf-8'))
                if work["payload"].get("scoring_epoch") != current_epoch:
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"manual_score_epoch_mismatch"}')

                try:
                    bowl, pin_mask, foul, fx_payload = _process_ball_event(
                        lane, pin_mask=pin_mask_in,
                        foul_override=foul_in,
                        manual_score={
                            "event_id": event_id,
                            "request_fingerprint": fingerprint,
                        })
                except RuntimeError:
                    return self._send(
                        503, "application/json",
                        b'{"ok":false,"error":"manual_score_commit_failed"}')
                _record_manual_score_state(
                    lane, event_id, "info",
                    "manual_score_completed",
                    scoring_epoch=current_epoch,
                    pin_mask=pin_mask, foul=foul)
                if fx_payload is not None:
                    _emit_fx_event(fx_payload)
                payload = {
                    "ok": True,
                    "lane": lane,
                    "event_id": event_id,
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
                body, err = self._read_json_body(65536)
                if err:
                    return self._send(400, 'application/json', err)
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
                    if not save_lanes(lane_scoring, ball_counters):
                        restored_lanes, restored_counters = load_lanes()
                        lane_scoring.clear()
                        lane_scoring.update(restored_lanes)
                        ball_counters.clear()
                        ball_counters.update(restored_counters)
                        return self._send(
                            503, "application/json",
                            b'{"ok":false,"error":"correction_state_commit_failed"}')
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
                if os.environ.get(
                        "WSL_ENABLE_TRIGGER_BALL", "").strip().lower() \
                        not in ("1", "true", "yes", "on"):
                    return self._send(
                        403, "application/json",
                        b'{"ok":false,"error":"trigger-ball is disabled outside an explicit bench session"}')
                operation_key = (
                    self.headers.get("X-Operation-Key") or "").strip()
                try:
                    operation_issued_at = float(
                        self.headers.get("X-Operation-Issued-At") or "")
                except ValueError:
                    operation_issued_at = float("nan")
                if (not operation_key or len(operation_key) > 100
                        or any(ch not in
                               "abcdefghijklmnopqrstuvwxyz"
                               "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                               "0123456789._:-"
                               for ch in operation_key)
                        or not math.isfinite(operation_issued_at)
                        or operation_issued_at > time.time() + 300):
                    return self._send(
                        400, "application/json",
                        b'{"error":"trigger-ball requires stable X-Operation-Key and X-Operation-Issued-At"}')
                body, err = self._read_json_body(4096, required=False)
                if err:
                    return self._send(400, "application/json", err)
                if (not isinstance(body, dict)
                        or set(body) - {"pin_mask", "foul"}):
                    return self._send(400, 'application/json',
                                      b'{"error":"trigger-ball body fields must be pin_mask and/or foul"}')
                pin_mask_in = body.get("pin_mask")
                if (pin_mask_in is not None
                        and (not isinstance(pin_mask_in, int)
                             or isinstance(pin_mask_in, bool)
                             or not 0 <= pin_mask_in <= 0x3FF)):
                    return self._send(
                        400, "application/json",
                        b'{"error":"pin_mask must be int 0-1023 or null"}')
                foul_requested = body.get("foul", False)
                if type(foul_requested) is not bool:
                    return self._send(
                        400, "application/json",
                        b'{"error":"foul must be a JSON boolean"}')

                # Same no-phantom-game rule as /score: bind the bench
                # operation to the exact durable generation and scoring epoch
                # before any scoring mutation.
                with state_lock:
                    ls = lane_scoring.get(lane)
                    lane_open = (
                        ls is not None
                        and getattr(ls, "is_active", False))
                    scoring_epoch = (
                        getattr(ls, "scoring_epoch", None)
                        if lane_open else None)
                if not lane_open:
                    return self._send(
                        404, "application/json",
                        json.dumps({
                            "ok": False,
                            "error": (
                                f"Lane {lane} not open "
                                f"(open it before trigger-ball)"),
                        }).encode("utf-8"))
                generation_row = lane_session_generation(lane)
                if (generation_row is None
                        or not bool(generation_row["active"])
                        or not isinstance(scoring_epoch, str)
                        or not scoring_epoch
                        or generation_row.get("scoring_epoch")
                        != scoring_epoch):
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"trigger_ball_session_binding_unavailable"}')
                session_generation = int(generation_row["generation"])
                normalized_request = {
                    "operation": "trigger_ball",
                    "lane": lane,
                    "session_generation": session_generation,
                    "scoring_epoch": scoring_epoch,
                    "pin_mask": pin_mask_in,
                    "foul": foul_requested,
                    "issued_at": operation_issued_at,
                }
                request_fp = _request_fingerprint(normalized_request)
                command_id = f"trigger-ball:{lane}:{operation_key}"
                existing = bench_ball_operation_receipt(operation_key)
                if existing is not None:
                    if (existing["request_fingerprint"] != request_fp
                            or int(existing["lane_id"]) != lane
                            or int(existing["session_generation"])
                            != session_generation
                            or existing["scoring_epoch"] != scoring_epoch):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"trigger_ball_idempotency_conflict"}')
                    result = existing["result"]
                    cycle_msg = encode_command(
                        Msg.CYCLE, lane,
                        command_id=result["command_id"],
                        issued_at=float(result["issued_at"]))
                    sent = send_to_lane(lane, cycle_msg)
                    payload = {
                        **{
                            key: result[key] for key in (
                                "lane", "pin_mask", "pin_mask_source",
                                "foul", "display")
                        },
                        "operation_key": operation_key,
                        "request_fingerprint": request_fp,
                        "session_generation": session_generation,
                        "scoring_epoch": scoring_epoch,
                        "sent_to": sent,
                        "ok": sent == 1,
                        "replayed": True,
                        "reconciliation_required": sent != 1,
                    }
                    return self._send(
                        200 if sent == 1 else 503, "application/json",
                        json.dumps(payload).encode("utf-8"))

                try:
                    bowl, pin_mask, foul, fx_payload = _process_ball_event(
                        lane, pin_mask=pin_mask_in,
                        foul_override=(
                            True if foul_requested else None),
                        bench_ball_operation={
                            "operation_key": operation_key,
                            "request_fingerprint": request_fp,
                            "lane_id": lane,
                            "session_generation": session_generation,
                            "scoring_epoch": scoring_epoch,
                            "issued_at": operation_issued_at,
                            "request": {
                                "pin_mask": pin_mask_in,
                                "foul": foul_requested,
                            },
                            "command_id": command_id,
                        })
                except RuntimeError as exc:
                    log.warning("trigger-ball state commit failed: %s", exc)
                    return self._send(
                        503, "application/json",
                        b'{"ok":false,"error":"trigger_ball_state_commit_failed"}')
                if bowl is None:
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"trigger_ball_session_changed"}')
                # Send the existing bench/simulator CYCLE message to the owning
                # node only after score + operation receipt commit atomically.
                cycle_msg = encode_command(
                    Msg.CYCLE, lane,
                    command_id=command_id,
                    issued_at=operation_issued_at)
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
                    "operation_key": operation_key,
                    "request_fingerprint": request_fp,
                    "session_generation": session_generation,
                    "scoring_epoch": scoring_epoch,
                    "replayed": False,
                }
                payload["ok"] = sent == 1
                payload["reconciliation_required"] = sent != 1
                return self._send(200 if sent == 1 else 503, 'application/json',
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
                body, err = self._read_json_body(65536)
                if err:
                    return self._send(400, 'application/json', err)
                if (not isinstance(body, dict)
                        or set(body) != {
                            "bowlers", "send_open_command",
                            "session_generation"}):
                    return self._send(
                        400, 'application/json',
                        b'{"error":"invalid open body fields"}')
                session_generation = body.get("session_generation")
                if (not isinstance(session_generation, int)
                        or isinstance(session_generation, bool)
                        or session_generation <= 0):
                    return self._send(
                        400, 'application/json',
                        b'{"error":"session_generation must be a positive integer"}')
                send_flag = body.get("send_open_command", True)
                if type(send_flag) is not bool:
                    return self._send(
                        400, "application/json",
                        b'{"error":"send_open_command must be boolean"}')
                send_hardware_command = send_flag
                raw_bowlers = body.get("bowlers")
                if raw_bowlers is None:
                    normalized_bowlers = ["TEST"]
                elif not isinstance(raw_bowlers, list):
                    return self._send(
                        400, "application/json",
                        b'{"error":"bowlers must be an array"}')
                else:
                    normalized_bowlers = []
                    for item in raw_bowlers:
                        if isinstance(item, str):
                            name = item.strip()
                        elif isinstance(item, dict) and set(item) == {"name"}:
                            name = str(item["name"]).strip()
                        else:
                            return self._send(
                                400, "application/json",
                                b'{"error":"each bowler must be a name or {name}"}')
                        if not name or len(name) > 200:
                            return self._send(
                                400, "application/json",
                                b'{"error":"bowler name is invalid"}')
                        normalized_bowlers.append(name)
                request_fp = _request_fingerprint({
                    "operation": "open_lane",
                    "lane": lane,
                    "session_generation": session_generation,
                    "bowlers": normalized_bowlers,
                })
                existing_generation = lane_session_generation(lane)
                open_replay = False
                if existing_generation is not None:
                    prior = int(existing_generation["generation"])
                    active = bool(existing_generation["active"])
                    if session_generation < prior or (
                            session_generation == prior and not active):
                        return self._send(
                            409, 'application/json',
                            json.dumps({
                                "ok": False,
                                "error": "stale_or_retired_session_generation",
                                "current_generation": prior,
                            }).encode("utf-8"))
                    if (session_generation > prior and active
                            and send_hardware_command):
                        return self._send(
                            409, 'application/json',
                            json.dumps({
                                "ok": False,
                                "error": "active_session_generation_conflict",
                                "current_generation": prior,
                            }).encode("utf-8"))
                    open_replay = session_generation == prior and active
                    stored_fp = existing_generation.get(
                        "request_fingerprint")
                    if (open_replay and stored_fp is not None
                            and stored_fp != request_fp):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"session_generation_payload_conflict"}')
                    if (open_replay and send_hardware_command
                            and (stored_fp != request_fp
                                 or not bool(existing_generation.get(
                                     "open_actuation_authorized")))):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"open_actuation_intent_escalation"}')
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

                # Repeat outside the optional history branch so first-ever
                # opens (which have no row yet) parse the roster too.
                raw_bowlers = body.get("bowlers")
                send_hardware_command = (
                    body.get("send_open_command") is not False)
                bowlers_in = None
                if isinstance(raw_bowlers, list):
                    names = []
                    for item in raw_bowlers:
                        if isinstance(item, str) and item.strip():
                            names.append(item.strip())
                        elif isinstance(item, dict) and item.get("name"):
                            names.append(str(item["name"]).strip())
                    if names:
                        bowlers_in = names

                bowlers_in = (
                    None if raw_bowlers is None
                    else list(normalized_bowlers))
                if open_replay:
                    with state_lock:
                        existing = lane_scoring.get(lane)
                        if (existing is None
                                or not getattr(existing, "is_active", False)):
                            return self._send(
                                503, "application/json",
                                b'{"ok":false,"error":"generation_active_but_scoring_state_missing"}')
                        opened_names = [b.name for b in existing.bowlers]
                        if opened_names != normalized_bowlers:
                            return self._send(
                                409, "application/json",
                                b'{"ok":false,"error":"session_generation_payload_conflict"}')
                    opened_epoch = _scoring_epoch_for_lane(lane)
                    replay_msg = encode_command(
                        Msg.OPEN_LANE, lane,
                        command_id=(
                            f"open:{lane}:{session_generation}"),
                        issued_at=existing_generation["updated_at"],
                        bowlers=opened_names,
                        scoring_epoch=opened_epoch)
                    delivery_msg = replay_msg
                    if not send_hardware_command:
                        delivery_msg = encode_epoch_sync(
                            lane, session_generation, opened_epoch)
                    replay_sent = send_to_lane(lane, delivery_msg)
                    replay_ok = replay_sent == 1
                    return self._send(
                        200 if replay_ok else 503, "application/json",
                        json.dumps({
                            "ok": replay_ok,
                            "replayed": True,
                            "session_generation": session_generation,
                            "scoring_epoch": opened_epoch,
                            "request_fingerprint": request_fp,
                            "bowlers": opened_names,
                            "sent_to": replay_sent,
                            "hardware_command_sent":
                                send_hardware_command,
                            "reconciliation_required": not replay_ok,
                            "msg": {
                                k: v for k, v in
                                decode(delivery_msg).items()
                                if k != "token"},
                        }).encode("utf-8"))

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
                    pending_work = _pending_manual_transition_work(
                        stale_lanes)
                    if pending_work:
                        return self._send(
                            409, "application/json",
                            json.dumps({
                                "ok": False,
                                "error":
                                    "pending_manual_scoring_reconciliation",
                                "pending_manual_scores": pending_work,
                            }).encode("utf-8"))
                    for lid in stale_lanes:
                        lane_scoring.pop(lid, None)
                        ball_counters.pop(lid, None)
                        pending_foul.pop(lid, None)
                        _last_ball_at.pop(lid, None)
                    get_or_create_lane(lane, bowlers=bowlers_in)
                    opened = lane_scoring[lane]
                    open_session_updates = {lane: {
                        "generation": session_generation,
                        "active": True,
                        "scoring_epoch": opened.scoring_epoch,
                        "request_fingerprint": request_fp,
                        "session_group_id": f"open:{request_fp}",
                        "open_actuation_authorized":
                            send_hardware_command,
                    }}
                    for stale_lane in stale_lanes - {lane}:
                        stale_row = lane_session_generation(stale_lane)
                        if stale_row is not None:
                            open_session_updates[stale_lane] = {
                                "generation": int(
                                    stale_row["generation"]),
                                "active": False,
                                "scoring_epoch": None,
                                "request_fingerprint":
                                    stale_row.get(
                                        "request_fingerprint"),
                            }
                    saved = save_lanes(
                        lane_scoring, ball_counters,
                        session_updates=open_session_updates,
                        clear_foul_lanes=stale_lanes,
                        guard_no_pending_manual_lanes=stale_lanes)
                    if not saved:
                        restored, restored_counts = load_lanes()
                        lane_scoring.clear()
                        lane_scoring.update(restored)
                        ball_counters.clear()
                        ball_counters.update(restored_counts)
                        return self._send(
                            503, "application/json",
                            b'{"ok":false,"error":"open_state_commit_failed"}')
                    opened_names = [b.name for b in lane_scoring[lane].bowlers]
                opened_epoch = _scoring_epoch_for_lane(lane)
                log.info(f"OPEN_LANE: reset scoring for lane {lane} "
                         f"(cleared {sorted(stale_lanes)}) "
                         f"with bowlers={bowlers_in or '[TEST]'}")

            # If closing, clear the scoring state on this lane (and the
            # paired lane too, if this lane is part of a CrossLaneScoring —
            # otherwise the overhead display would keep showing the old
            # match roster after desk close).
            if msg_type == Msg.CLOSE_LANE:
                close_body, err = self._read_json_body(4096)
                if err:
                    return self._send(400, "application/json", err)
                if (not isinstance(close_body, dict)
                        or set(close_body) != {"session_generation"}
                        or not isinstance(
                            close_body.get("session_generation"), int)
                        or isinstance(
                            close_body.get("session_generation"), bool)
                        or close_body["session_generation"] <= 0):
                    return self._send(
                        400, "application/json",
                        b'{"error":"session_generation must be a positive integer"}')
                session_generation = close_body["session_generation"]
                current_generation = lane_session_generation(lane)
                prior_generation = (
                    int(current_generation["generation"])
                    if current_generation is not None else None)
                if (prior_generation is not None
                        and session_generation < prior_generation):
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error": "stale_session_generation",
                            "current_generation": prior_generation,
                        }).encode("utf-8"))
                if (current_generation is not None
                        and session_generation == prior_generation
                        and not bool(current_generation["active"])):
                    replay_rows = sorted([
                        row for row in lane_session_generation_group(lane)
                        if not bool(row["active"])],
                        key=lambda row: int(row["lane_id"]))
                    replay_generations = {
                        str(int(row["lane_id"])): int(row["generation"])
                        for row in replay_rows
                    }
                    replay_request_fp = _request_fingerprint({
                        "operation": "close_group",
                        "lanes": replay_generations,
                    })
                    replay_messages = [(
                        int(row["lane_id"]),
                        encode_command(
                            Msg.CLOSE_LANE, int(row["lane_id"]),
                            command_id=(
                                f"close:{int(row['lane_id'])}:"
                                f"{int(row['generation'])}"),
                            issued_at=row["updated_at"],
                            scoring_epoch=None))
                        for row in replay_rows]
                    replay_sent = sum(
                        send_to_lane(replay_lane, replay_message)
                        for replay_lane, replay_message in replay_messages)
                    expected_replay = len(replay_messages)
                    replay_msg = next(
                        (message for replay_lane, message
                         in replay_messages if replay_lane == lane),
                        replay_messages[0][1])
                    return self._send(
                        200 if replay_sent == expected_replay else 503,
                        "application/json",
                        json.dumps({
                            "ok": replay_sent == expected_replay,
                            "replayed": True,
                            "session_generation": session_generation,
                            "session_generations": replay_generations,
                            "request_fingerprint": replay_request_fp,
                            "scoring_epoch": None,
                            "sent_to": replay_sent,
                            "expected_commands": expected_replay,
                            "closed_lanes": sorted(
                                replay_lane for replay_lane, _
                                in replay_messages),
                            "sent_close_commands": replay_sent,
                            "hardware_command_sent": True,
                            "reconciliation_required":
                                replay_sent != expected_replay,
                            "msg": {
                                k: v for k, v in
                                decode(replay_msg).items()
                                if k != "token"},
                        }).encode("utf-8"))
                with state_lock:
                    preclose = lane_scoring.get(lane)
                    preclose_lanes = list(
                        getattr(preclose, "lane_ids", None) or [lane])
                pending_work = _pending_manual_transition_work(
                    preclose_lanes)
                if pending_work:
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error":
                                "pending_manual_scoring_reconciliation",
                            "pending_manual_scores": pending_work,
                        }).encode("utf-8"))
                close_session_updates = {}
                close_rows = {}
                for lid in preclose_lanes:
                    row = lane_session_generation(lid)
                    if lid == lane and (
                            row is None
                            or session_generation
                            > int(row["generation"])):
                        close_rows[lid] = {
                            "generation": session_generation,
                            "request_fingerprint": (
                                row.get("request_fingerprint")
                                if row is not None else None),
                            "open_actuation_authorized": False,
                        }
                    elif row is None:
                        return self._send(
                            409, "application/json",
                            json.dumps({
                                "ok": False,
                                "error": "paired_session_generation_missing",
                                "lane": lid,
                            }).encode("utf-8"))
                    else:
                        close_rows[lid] = row
                close_session_generations = {
                    str(lid): int(close_rows[lid]["generation"])
                    for lid in sorted(close_rows)
                }
                close_request_fp = _request_fingerprint({
                    "operation": "close_group",
                    "lanes": close_session_generations,
                })
                close_group_id = "close:" + close_request_fp
                for lid, row in close_rows.items():
                    close_session_updates[lid] = {
                        "generation": int(row["generation"]),
                        "active": False,
                        "scoring_epoch": None,
                        "request_fingerprint":
                            row.get("request_fingerprint"),
                        "session_group_id": close_group_id,
                        "open_actuation_authorized": (
                            None
                            if row.get("open_actuation_authorized") is None
                            else bool(row["open_actuation_authorized"])),
                    }
                with state_lock:
                    ls = lane_scoring.get(lane)
                    close_targets = list(
                        getattr(ls, 'lane_ids', None) or [lane])
                    prior_pending_foul = {
                        lid: pending_foul[lid]
                        for lid in close_targets if lid in pending_foul}
                    prior_last_ball_at = {
                        lid: _last_ball_at[lid]
                        for lid in close_targets if lid in _last_ball_at}
                    cleared = []
                    for lid in close_targets:
                        lane_scoring.pop(lid, None)
                        ball_counters.pop(lid, None)
                        pending_foul.pop(lid, None)
                        _last_ball_at.pop(lid, None)
                        cleared.append(lid)
                    saved = save_lanes(
                        lane_scoring, ball_counters,
                        session_updates=close_session_updates,
                        clear_foul_lanes=cleared,
                        guard_no_pending_manual_lanes=cleared)
                    if not saved:
                        restored, restored_counts = load_lanes()
                        lane_scoring.clear()
                        lane_scoring.update(restored)
                        ball_counters.clear()
                        ball_counters.update(restored_counts)
                        # The DB transaction did not consume the foul receipt or
                        # commit the close. Restore its process-local mirror and
                        # the duplicate-ball window as part of the same rollback;
                        # otherwise a failed CLOSE leaves the still-active game
                        # with weaker event ordering than it had before.
                        # A manual BALL/FOUL receipt can be committed by the
                        # WebSocket thread while the DB guard is rejecting this
                        # close. Preserve that newer process-local observation;
                        # restore the pre-close value only when no concurrent
                        # writer has supplied one.
                        for lid, value in prior_pending_foul.items():
                            pending_foul.setdefault(lid, value)
                        for lid, value in prior_last_ball_at.items():
                            _last_ball_at.setdefault(lid, value)
                        return self._send(
                            503, "application/json",
                            b'{"ok":false,"error":"close_state_commit_failed"}')
                log.info(f"CLOSE_LANE: cleared scoring for lane(s) {cleared}")

            if msg_type == Msg.OPEN_LANE:
                operation_issued_at = lane_session_generation(
                    lane)["updated_at"]
                msg = encode_command(
                    msg_type, lane=lane, bowlers=opened_names,
                    command_id=f"open:{lane}:{session_generation}",
                    issued_at=operation_issued_at,
                    scoring_epoch=opened_epoch)
            elif msg_type == Msg.CLOSE_LANE:
                close_messages = []
                for close_lane in cleared:
                    close_row = lane_session_generation(close_lane)
                    close_messages.append((
                        close_lane,
                        encode_command(
                            msg_type, lane=close_lane,
                            command_id=(
                                f"close:{close_lane}:"
                                f"{int(close_row['generation'])}"),
                            issued_at=close_row["updated_at"],
                            scoring_epoch=None)))
                msg = next(
                    (frame for lid, frame in close_messages
                     if lid == lane),
                    close_messages[0][1])
            else:
                operation_key = (
                    self.headers.get("X-Operation-Key") or "").strip()
                if (not operation_key or len(operation_key) > 100
                        or any(ch not in
                               "abcdefghijklmnopqrstuvwxyz"
                               "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                               "0123456789._:-"
                               for ch in operation_key)):
                    return self._send(
                        400, "application/json",
                        b'{"error":"X-Operation-Key required for physical command"}')
                try:
                    operation_issued_at = float(
                        self.headers.get("X-Operation-Issued-At") or "")
                except ValueError:
                    return self._send(
                        400, "application/json",
                        b'{"error":"X-Operation-Issued-At epoch seconds required"}')
                if (not math.isfinite(operation_issued_at)
                        or operation_issued_at > time.time() + 300):
                    return self._send(
                        400, "application/json",
                        b'{"error":"X-Operation-Issued-At is invalid"}')
                msg = encode_command(
                    msg_type, lane=lane,
                    command_id=f"{msg_type}:{lane}:{operation_key}",
                    issued_at=operation_issued_at)
            if send_hardware_command:
                if msg_type == Msg.CLOSE_LANE:
                    sent = sum(
                        send_to_lane(lid, frame)
                        for lid, frame in close_messages)
                else:
                    sent = send_to_lane(lane, msg)
                log.info(f"→ {action.upper()} lane {lane} sent to {sent} node(s)")
            else:
                if msg_type == Msg.OPEN_LANE:
                    msg = encode_epoch_sync(
                        lane, session_generation, opened_epoch)
                    sent = send_to_lane(lane, msg)
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
            expected_commands = (
                len(close_messages)
                if msg_type == Msg.CLOSE_LANE else 1)
            operation_ok = (
                (sent == expected_commands)
                if msg_type == Msg.OPEN_LANE
                else (not send_hardware_command
                      or sent == expected_commands))
            response_payload = {
                "ok": operation_ok,
                "sent_to": sent,
                "expected_commands": expected_commands,
                "sent_close_commands": (
                    sent if msg_type == Msg.CLOSE_LANE
                    else None),
                "session_generation": (
                    session_generation
                    if msg_type in (
                        Msg.OPEN_LANE, Msg.CLOSE_LANE)
                    else None),
                    "scoring_epoch": (
                        opened_epoch
                        if msg_type == Msg.OPEN_LANE else None),
                "reconciliation_required": not operation_ok,
                # never echo the auth token back to the HTTP caller
                "msg": {
                    k: v for k, v in decode(msg).items()
                    if k != "token"},
                "hardware_command_sent": send_hardware_command,
            }
            if msg_type in (Msg.OPEN_LANE, Msg.CLOSE_LANE):
                response_payload["replayed"] = False
            if msg_type == Msg.OPEN_LANE:
                response_payload["request_fingerprint"] = request_fp
                response_payload["bowlers"] = opened_names
            if msg_type == Msg.CLOSE_LANE:
                response_payload["closed_lanes"] = sorted(cleared)
                response_payload["session_generations"] = (
                    close_session_generations)
                response_payload["request_fingerprint"] = close_request_fp
            self._send(200 if operation_ok else 503, 'application/json',
                       json.dumps(response_payload).encode('utf-8'))
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
            if (lane_left == lane_right or not 1 <= lane_left <= 32
                    or not 1 <= lane_right <= 32):
                return self._send(
                    400, "application/json",
                    b'{"error":"pair lanes must be distinct values from 1 to 32"}')
            body, err = self._read_json_body(65536)
            if err:
                return self._send(400, 'application/json', err)
            allowed_league_fields = {
                "team1_bowlers", "team2_bowlers", "team1_name",
                "team2_name", "send_open_command",
                "session_generations"}
            if (not isinstance(body, dict)
                    or set(body) != allowed_league_fields):
                return self._send(
                    400, "application/json",
                    b'{"error":"invalid open-league body fields"}')
            send_flag = body.get("send_open_command", True)
            if type(send_flag) is not bool:
                return self._send(
                    400, "application/json",
                    b'{"error":"send_open_command must be boolean"}')
            send_open_command = send_flag
            session_generations = body.get("session_generations")
            expected_generation_keys = {
                str(lane_left), str(lane_right)}
            if (not isinstance(session_generations, dict)
                    or set(session_generations)
                    != expected_generation_keys
                    or any(
                        not isinstance(value, int)
                        or isinstance(value, bool) or value <= 0
                        for value in session_generations.values())):
                return self._send(
                    400, "application/json",
                    b'{"error":"session_generations must map both lanes to positive integers"}')
            session_generations = {
                int(key): value
                for key, value in session_generations.items()}
            generation_rows = {
                lid: lane_session_generation(lid)
                for lid in (lane_left, lane_right)}
            league_replay = True
            for lid, generation in session_generations.items():
                row = generation_rows[lid]
                if row is None:
                    league_replay = False
                    continue
                prior = int(row["generation"])
                active = bool(row["active"])
                if generation < prior or (
                        generation == prior and not active):
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error":
                                "stale_or_retired_session_generation",
                            "lane": lid,
                            "current_generation": prior,
                        }).encode("utf-8"))
                if (generation > prior and active
                        and send_open_command):
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error":
                                "active_session_generation_conflict",
                            "lane": lid,
                            "current_generation": prior,
                        }).encode("utf-8"))
                if generation != prior or not active:
                    league_replay = False
            t1_bowlers = body['team1_bowlers']
            t2_bowlers = body['team2_bowlers']
            t1_name = body['team1_name']
            t2_name = body['team2_name']
            if not isinstance(t1_bowlers, list) or not isinstance(t2_bowlers, list):
                return self._send(400, 'application/json',
                                  b'{"error":"team1_bowlers and team2_bowlers must be lists"}')
            if len(t1_bowlers) + len(t2_bowlers) > 128:
                return self._send(
                    400, "application/json",
                    b'{"error":"combined league roster exceeds 128 bowlers"}')
            if any(
                    value is not None
                    and (not isinstance(value, str)
                         or not value.strip() or len(value) > 200)
                    for value in (t1_name, t2_name)):
                return self._send(
                    400, "application/json",
                    b'{"error":"team names must be non-empty strings"}')
            t1_name = t1_name.strip() if t1_name is not None else None
            t2_name = t2_name.strip() if t2_name is not None else None

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
                        allowed_bowler_fields = {
                            "name", "hdcp", "handicap", "average",
                            "current_avg", "team_id", "bowler_id", "id",
                            "team_name"}
                        if set(item) - allowed_bowler_fields:
                            return self._send(
                                400, "application/json",
                                b'{"error":"invalid bowler fields"}')
                        raw_name = item.get("name")
                        if not isinstance(raw_name, str):
                            return self._send(
                                400, "application/json",
                                b'{"error":"bowler name must be a string"}')
                        name = raw_name.strip()
                        try:
                            hdcp_raw = item.get('hdcp')
                            if hdcp_raw is None:
                                hdcp_raw = item.get('handicap', 0)
                            if isinstance(hdcp_raw, bool):
                                raise ValueError(hdcp_raw)
                            hdcp = int(hdcp_raw or 0)
                        except (ValueError, TypeError):
                            return self._send(
                                400, "application/json",
                                b'{"error":"bowler handicap must be numeric"}')
                        try:
                            avg_raw = item.get(
                                'average', item.get('current_avg', 0.0))
                            if isinstance(avg_raw, bool):
                                raise ValueError(avg_raw)
                            avg = float(avg_raw or 0.0)
                        except (ValueError, TypeError):
                            return self._send(
                                400, "application/json",
                                b'{"error":"bowler average must be numeric"}')
                        team_id = item.get('team_id')
                        bowler_id = item.get('bowler_id')
                        if bowler_id is None:
                            bowler_id = item.get('id')
                        if (not 0 <= hdcp <= 300
                                or not math.isfinite(avg)
                                or not 0.0 <= avg <= 300.0
                                or any(
                                    value is not None
                                    and (not isinstance(value, int)
                                         or isinstance(value, bool)
                                         or value <= 0)
                                    for value in (team_id, bowler_id))):
                            return self._send(
                                400, "application/json",
                                b'{"error":"bowler metadata is out of range"}')
                    else:
                        return self._send(
                            400, "application/json",
                            b'{"error":"invalid bowler entry"}')
                    if not name or len(name) > 200:
                        return self._send(
                            400, "application/json",
                            b'{"error":"bowler name is invalid"}')
                    cls.add_bowler(name, number=number, hdcp=hdcp, average=avg,
                                   starting_lane=team_lane,
                                   team_id=team_id, team_name=team_name,
                                   bowler_id=bowler_id)
                    number += 1
            cls.start()
            cls.scoring_epoch = uuid.uuid4().hex
            request_fp = _request_fingerprint({
                "operation": "open_league",
                "lanes": [lane_left, lane_right],
                "session_generations": {
                    str(lid): session_generations[lid]
                    for lid in sorted(session_generations)},
                "team1_name": t1_name,
                "team2_name": t2_name,
                "roster": _league_roster_fingerprint(cls),
            })
            if league_replay:
                for row in generation_rows.values():
                    stored_fp = row.get("request_fingerprint")
                    if stored_fp is not None and stored_fp != request_fp:
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"session_generation_payload_conflict"}')
                if (send_open_command and any(
                        row.get("request_fingerprint") != request_fp
                        or not bool(row.get(
                            "open_actuation_authorized"))
                        for row in generation_rows.values())):
                    return self._send(
                        409, "application/json",
                        b'{"ok":false,"error":"open_actuation_intent_escalation"}')
                with state_lock:
                    existing_left = lane_scoring.get(lane_left)
                    existing_right = lane_scoring.get(lane_right)
                    if (existing_left is None
                            or existing_left is not existing_right
                            or not getattr(
                                existing_left, "is_active", False)):
                        return self._send(
                            503, "application/json",
                            b'{"ok":false,"error":"generation_active_but_league_state_missing"}')
                    if (_league_roster_fingerprint(existing_left)
                            != _league_roster_fingerprint(cls)):
                        return self._send(
                            409, "application/json",
                            b'{"ok":false,"error":"session_generation_payload_conflict"}')
                    cls = existing_left
                replay_sent = 0
                for lid in (lane_left, lane_right):
                    row = generation_rows[lid]
                    command_type = (
                        Msg.OPEN_LANE if send_open_command
                        else Msg.SCORING_EPOCH_SYNC)
                    fields = {"scoring_epoch": cls.scoring_epoch}
                    if send_open_command:
                        fields["bowlers"] = [
                            b.name for b in cls.bowlers]
                    replay_sent += send_to_lane(
                        lid, (
                            encode_command(
                                command_type, lane=lid,
                                command_id=(
                                    f"open-league:{lid}:"
                                    f"{session_generations[lid]}"),
                                issued_at=row["updated_at"], **fields)
                            if send_open_command else
                            encode_epoch_sync(
                                lid, session_generations[lid],
                                cls.scoring_epoch)))
                replay_ok = replay_sent == 2
                return self._send(
                    200 if replay_ok else 503, "application/json",
                    json.dumps({
                        "ok": replay_ok,
                        "replayed": True,
                        "lane_left": lane_left,
                        "lane_right": lane_right,
                        "session_generations": {
                            str(lid): session_generations[lid]
                            for lid in sorted(session_generations)},
                        "scoring_epoch": cls.scoring_epoch,
                        "request_fingerprint": request_fp,
                        "team1_name": t1_name,
                        "team2_name": t2_name,
                        "team1_bowlers": [
                            b.name for b in cls.bowlers
                            if b.starting_physical_lane == lane_left],
                        "team2_bowlers": [
                            b.name for b in cls.bowlers
                            if b.starting_physical_lane == lane_right],
                        "hardware_command_sent": send_open_command,
                        "sent_open_commands": (
                            replay_sent if send_open_command else 0),
                        "sent_epoch_sync_commands": (
                            0 if send_open_command else replay_sent),
                        "reconciliation_required": not replay_ok,
                    }).encode("utf-8"))

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
                pending_work = _pending_manual_transition_work(to_clear)
                if pending_work:
                    return self._send(
                        409, "application/json",
                        json.dumps({
                            "ok": False,
                            "error":
                                "pending_manual_scoring_reconciliation",
                            "pending_manual_scores": pending_work,
                        }).encode("utf-8"))
                for lid in to_clear:
                    lane_scoring.pop(lid, None)
                    ball_counters.pop(lid, None)
                    pending_foul.pop(lid, None)
                    _last_ball_at.pop(lid, None)
                lane_scoring[lane_left] = cls
                lane_scoring[lane_right] = cls
                session_updates = {}
                for lid in to_clear:
                    if lid in session_generations:
                        session_updates[lid] = {
                            "generation": session_generations[lid],
                            "active": True,
                            "scoring_epoch": cls.scoring_epoch,
                            "request_fingerprint": request_fp,
                            "session_group_id": f"league:{request_fp}",
                            "open_actuation_authorized":
                                send_open_command,
                        }
                    else:
                        old_row = lane_session_generation(lid)
                        if old_row is not None:
                            session_updates[lid] = {
                                "generation": int(
                                    old_row["generation"]),
                                "active": False,
                                "scoring_epoch": None,
                                "request_fingerprint":
                                    old_row.get("request_fingerprint"),
                            }
                saved = save_lanes(
                    lane_scoring, ball_counters,
                    session_updates=session_updates,
                    clear_foul_lanes=to_clear,
                    guard_no_pending_manual_lanes=to_clear)
                if not saved:
                    restored, restored_counts = load_lanes()
                    lane_scoring.clear()
                    lane_scoring.update(restored)
                    ball_counters.clear()
                    ball_counters.update(restored_counts)
                    return self._send(
                        503, "application/json",
                        b'{"ok":false,"error":"league_state_commit_failed"}')

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
            sent_sync = 0
            for lid in (lane_left, lane_right):
                row = lane_session_generation(lid)
                command_type = (
                    Msg.OPEN_LANE if send_open_command
                    else Msg.SCORING_EPOCH_SYNC)
                fields = {"scoring_epoch": cls.scoring_epoch}
                if send_open_command:
                    fields["bowlers"] = [
                        b.name for b in cls.bowlers]
                delivered = send_to_lane(
                    lid, (
                        encode_command(
                            command_type, lane=lid,
                            command_id=(
                                f"open-league:{lid}:"
                                f"{session_generations[lid]}"),
                            issued_at=row["updated_at"], **fields)
                        if send_open_command else
                        encode_epoch_sync(
                            lid, session_generations[lid],
                            cls.scoring_epoch)))
                if send_open_command:
                    sent_open += delivered
                else:
                    sent_sync += delivered

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
            operation_ok = (
                sent_open == 2 if send_open_command
                else sent_sync == 2)
            return self._send(
                              200 if operation_ok else 503,
                              'application/json',
                              json.dumps({
                                  "ok": operation_ok,
                                  "replayed": False,
                                  "lane_left": lane_left,
                                  "lane_right": lane_right,
                                  "team1_name": t1_name,
                                  "team2_name": t2_name,
                                  "team1_bowlers": t1_names,
                                  "team2_bowlers": t2_names,
                                  "game": cls.game_number,
                                  "session_generations": {
                                      str(lid): session_generations[lid]
                                      for lid in sorted(
                                          session_generations)},
                                  "scoring_epoch": cls.scoring_epoch,
                                  "request_fingerprint": request_fp,
                                  "hardware_command_sent": send_open_command,
                                  "sent_open_commands": sent_open,
                                  "sent_epoch_sync_commands": sent_sync,
                                  "reconciliation_required":
                                      not operation_ok,
                              }).encode('utf-8'))
        else:
            self._send(404, 'application/json', b'{"error":"not found"}')

    def _send(self, code, ctype, body):
        try:
            self.connection.settimeout(HTTP_IO_TIMEOUT_S)
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        pass


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Bounded HTTP concurrency with finite connection I/O waits."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, server_address, handler_class, max_handlers=None):
        super().__init__(server_address, handler_class)
        self._handler_slots = threading.BoundedSemaphore(
            max_handlers or HTTP_MAX_HANDLERS)

    def process_request(self, request, client_address):
        if not self._handler_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request.settimeout(HTTP_IO_TIMEOUT_S)
            super().process_request(request, client_address)
        except BaseException:
            self._handler_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._handler_slots.release()


def http_thread():
    BoundedThreadingHTTPServer(
        ('0.0.0.0', 8766), HttpHandler).serve_forever()

async def main():
    global main_loop, _diagnostic_delivery_enforced
    main_loop = asyncio.get_running_loop()
    _diagnostic_delivery_enforced = True
    topology, topology_error = _scoring_node_topology()
    if topology_error:
        log.error(
            "Scoring physical authority disabled: %s", topology_error)
    else:
        log.info("Scoring node topology loaded: %s", topology)
    _node_tokens, token_error = _scoring_node_tokens()
    if token_error and not ALLOW_UNAUTHENTICATED_BENCH:
        log.error(
            "Scoring node authentication disabled: %s", token_error)
    if AUTH_TOKEN:
        log.info(
            "LANE_NODE_TOKEN set — POST control API (:8766) requires the "
            "shared token and node-bound command frames are stamped with it; "
            "production WS HELLO (:8765) requires the node's distinct "
            "WSL_SCORING_NODE_TOKEN.")
    elif ALLOW_UNAUTHENTICATED_BENCH:
        log.warning(
            "LANE_NODE_TOKEN not set — :8766 control POSTs and :8765 WS are "
            "UNAUTHENTICATED under explicit "
            "WSL_ALLOW_UNAUTHENTICATED_BENCH=1; health remains NO-GO.")
    else:
        log.error(
            "LANE_NODE_TOKEN not set: all control POSTs and node HELLOs are "
            "refused. Configure the shared token before physical operation.")
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
    _start_diagnostic_delivery_worker()
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
