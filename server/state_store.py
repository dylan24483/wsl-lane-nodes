#!/usr/bin/env python3
"""SQLite-backed persistence for server-side lane scoring state.

Without this, every server restart wipes all in-progress games. With
this, the server reloads the most recent state for every lane on
startup. Players don't lose their scores if we have to bounce the
server during a game.

Storage: a single SQLite database at the configured path, one snapshot
row holding the whole lane_scoring + ball_counters state as versioned
JSON (see _snapshot_to_json). JSON replaced the original pickle format
in 2026-06: pickle.loads on a corrupted or attacker-substituted DB file
is arbitrary code execution, and pickle silently broke whenever the
LaneScoring class shape changed. Runtime pickle loading is deliberately
unsupported. A legacy or malformed blob fails closed, remains on disk
for operator inspection, and makes persistence health red until an
explicit clear/import action.

NOTES:
- The save path is a write-through pattern: every state change calls
  save_lanes(). For high-frequency updates (rapid bowling) this is
  fine — SQLite handles ~1000 transactions/sec on commodity SD cards.
  If save latency ever shows up in profiles, batch saves with a
  background flush task.
- Save failures are tracked (consecutive count + last-ok timestamp)
  and surfaced via get_save_status() → /api/health "state_save", so a
  quietly-failing disk shows up in monitoring instead of losing games
  at the next restart. Repeated failures escalate to log.error.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

# Make wsl_scoring_engine importable regardless of how this module is
# entered. lane_node_server.py adds the same path before importing us,
# but the state_store.py __main__ CLI is a separate entry point that
# doesn't.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wsl_scoring_engine import (Bowl, Frame, BowlerGame,  # noqa: E402
                                LaneScoring, CrossLaneScoring)

log = logging.getLogger('state_store')

# Default DB location — sits alongside the repo for easy inspection.
# Override via STATE_DB_PATH env var if you want it elsewhere.
DEFAULT_DB_PATH = _REPO_ROOT / "lane_state.db"
DB_PATH = Path(os.environ.get("STATE_DB_PATH", DEFAULT_DB_PATH))

# Threading lock for SQLite write access. The server runs the HTTP
# handler in a worker thread + asyncio in the main thread; both can
# trigger save_lanes(). SQLite itself is thread-safe but a connection
# is not portable across threads, so we guard with a lock and use a
# fresh connection per call.
_db_lock = threading.Lock()

# Save-health tracking (see get_save_status). Guarded by its own lock
# so a status read never waits on a slow SQLite write.
_status_lock = threading.Lock()
_save_status = {
    "last_ok_ts": None,        # time.time() of the last successful save
    "consecutive_failures": 0,
    "last_error": None,
}
_load_status = {
    "last_load_at": None,
    "last_load_ok": False,
    "last_load_state": "not_attempted",
    "last_load_error": "state restore has not been attempted",
    "state_discarded": False,
}


def acquire_backup_lock(timeout_s):
    """Quiesce every lane-state DB access for a bounded external snapshot."""
    return _db_lock.acquire(timeout=float(timeout_s))


def release_backup_lock():
    """Release a lock acquired by :func:`acquire_backup_lock`."""
    _db_lock.release()


class StateStoreBusy(TimeoutError):
    """Raised when a bounded safety-ledger operation misses its deadline."""


@contextmanager
def _delivery_connection(timeout_s):
    """Open the safety-ledger DB under one bounded process/SQLite deadline."""
    timeout_s = float(timeout_s)
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and positive")
    deadline = time.monotonic() + timeout_s
    if not _db_lock.acquire(timeout=timeout_s):
        raise StateStoreBusy("lane-state safety ledger lock deadline exceeded")
    conn = None
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StateStoreBusy(
                "lane-state safety ledger deadline exceeded")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=max(0.001, remaining))
        conn.row_factory = sqlite3.Row
        _ensure_delivery_schema(conn)
        yield conn
    finally:
        if conn is not None:
            conn.close()
        _db_lock.release()


def _record_save_ok():
    with _status_lock:
        _save_status["last_ok_ts"] = time.time()
        _save_status["consecutive_failures"] = 0
        _save_status["last_error"] = None


def _record_save_failure(e):
    with _status_lock:
        _save_status["consecutive_failures"] += 1
        _save_status["last_error"] = str(e)
        n = _save_status["consecutive_failures"]
    msg = f"save_lanes failed ({n} consecutive): {e}"
    if n >= 3:
        log.error(msg)
    else:
        log.warning(msg)


def _record_load_ok(state):
    with _status_lock:
        _load_status.update({
            "last_load_at": time.time(),
            "last_load_ok": True,
            "last_load_state": state,
            "last_load_error": None,
            "state_discarded": False,
        })


def _record_load_failure(state, error, *, discarded=True):
    with _status_lock:
        _load_status.update({
            "last_load_at": time.time(),
            "last_load_ok": False,
            "last_load_state": state,
            "last_load_error": str(error),
            "state_discarded": bool(discarded),
        })


def get_save_status() -> dict:
    """Combined save + startup-restore persistence health for /api/health."""
    with _status_lock:
        st = dict(_save_status)
        st.update(_load_status)
    st["save_ok"] = st["consecutive_failures"] == 0
    st["load_ok"] = bool(st["last_load_ok"])
    try:
        clock = control_wall_clock_status()
    except Exception as exc:
        clock = {
            "observed": False,
            "high_water_epoch": None,
            "anomaly_latched": True,
            "anomaly_detected_at": None,
            "observed_epoch": None,
            "error": str(exc),
        }
    st["clock_guard"] = clock
    st["ok"] = (
        st["save_ok"] and st["load_ok"]
        and clock["observed"] and not clock["anomaly_latched"])
    st["last_ok_age_sec"] = (round(time.time() - st["last_ok_ts"], 1)
                             if st["last_ok_ts"] is not None else None)
    return st


def observe_control_wall_clock(now=None, rollback_tolerance_s=5.0):
    """Advance a durable wall-clock high-water and permanently latch rollback.

    Unix timestamps authorize scoring and physical commands. A backward clock
    step can make stale work appear young, so the latch survives restarts and
    clears only through an explicit database maintenance procedure.
    """
    observed = time.time() if now is None else now
    if (isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(float(observed))):
        raise ValueError("wall-clock observation must be finite")
    tolerance = float(rollback_tolerance_s)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("rollback tolerance must be nonnegative")
    observed = float(observed)
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM control_clock_guard "
                "WHERE scope='scoring_authority'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO control_clock_guard "
                    "(scope,high_water_epoch,anomaly_latched,"
                    "anomaly_detected_at,observed_epoch,updated_at) "
                    "VALUES ('scoring_authority',?,0,NULL,?,?)",
                    (observed, observed, observed))
            else:
                high_water = float(row["high_water_epoch"])
                latched = bool(row["anomaly_latched"])
                detected_at = row["anomaly_detected_at"]
                if observed + tolerance < high_water:
                    latched = True
                    if detected_at is None:
                        detected_at = observed
                conn.execute(
                    "UPDATE control_clock_guard SET high_water_epoch=?,"
                    "anomaly_latched=?,anomaly_detected_at=?,"
                    "observed_epoch=?,updated_at=? "
                    "WHERE scope='scoring_authority'",
                    (max(high_water, observed), int(latched), detected_at,
                     observed, observed))
            conn.commit()
    return control_wall_clock_status()


def control_wall_clock_status():
    """Return durable clock-rollback evidence without advancing it."""
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT high_water_epoch,anomaly_latched,"
                "anomaly_detected_at,observed_epoch "
                "FROM control_clock_guard "
                "WHERE scope='scoring_authority'").fetchone()
    if row is None:
        return {
            "observed": False,
            "high_water_epoch": None,
            "anomaly_latched": False,
            "anomaly_detected_at": None,
            "observed_epoch": None,
            "error": None,
        }
    return {
        "observed": True,
        "high_water_epoch": float(row["high_water_epoch"]),
        "anomaly_latched": bool(row["anomaly_latched"]),
        "anomaly_detected_at": (
            None if row["anomaly_detected_at"] is None
            else float(row["anomaly_detected_at"])),
        "observed_epoch": float(row["observed_epoch"]),
        "error": None,
    }


def reset_control_wall_clock(
        confirmed_utc_epoch, actor_id, note):
    """Reset a latched clock only while every durable session is closed.

    The HTTP owner additionally requires authenticated access, no connected
    nodes/scorers, and a supplied epoch matching the host clock. This function
    performs the durable closed-state check and appends immutable audit
    evidence in the same transaction as the reset.
    """
    epoch = confirmed_utc_epoch
    if (isinstance(epoch, bool)
            or not isinstance(epoch, (int, float))
            or not math.isfinite(float(epoch))):
        raise ValueError("confirmed_utc_epoch must be finite")
    if (not isinstance(actor_id, int) or isinstance(actor_id, bool)
            or actor_id <= 0):
        raise ValueError("actor_id must be a positive integer")
    if (not isinstance(note, str) or not 10 <= len(note.strip()) <= 500):
        raise ValueError("note must contain 10..500 characters")
    epoch = float(epoch)
    note = note.strip()
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT lane_id FROM lane_session_generations "
                "WHERE active=1 ORDER BY lane_id LIMIT 1").fetchone()
            if active is not None:
                conn.rollback()
                raise ValueError(
                    "clock reset requires every durable lane closed")
            prior = conn.execute(
                "SELECT * FROM control_clock_guard "
                "WHERE scope='scoring_authority'").fetchone()
            if prior is None or not bool(prior["anomaly_latched"]):
                conn.rollback()
                raise ValueError("clock anomaly is not latched")
            reset_at = time.time()
            cursor = conn.execute(
                "INSERT INTO control_clock_reset_audit "
                "(scope,prior_high_water,prior_observed_epoch,new_epoch,"
                "actor_id,note,reset_at) VALUES (?,?,?,?,?,?,?)",
                ("scoring_authority", float(prior["high_water_epoch"]),
                 float(prior["observed_epoch"]), epoch, actor_id, note,
                 reset_at))
            conn.execute(
                "UPDATE control_clock_guard SET high_water_epoch=?,"
                "anomaly_latched=0,anomaly_detected_at=NULL,"
                "observed_epoch=?,updated_at=? "
                "WHERE scope='scoring_authority'",
                (epoch, epoch, reset_at))
            conn.commit()
    return {
        "reset_id": int(cursor.lastrowid),
        "scope": "scoring_authority",
        "prior_high_water": float(prior["high_water_epoch"]),
        "prior_observed_epoch": float(prior["observed_epoch"]),
        "new_epoch": epoch,
        "actor_id": actor_id,
        "note": note,
        "reset_at": reset_at,
    }


_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnostic_incident_outbox (
  outbox_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_key    TEXT NOT NULL UNIQUE,
  delivery_id     TEXT NOT NULL UNIQUE,
  payload_json    TEXT NOT NULL,
  created_at      REAL NOT NULL,
  delivered_at    REAL,
  attempt_count   INTEGER NOT NULL DEFAULT 0,
  last_attempt_at REAL,
  last_error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_diagnostic_incident_pending
  ON diagnostic_incident_outbox(delivered_at,outbox_id);

CREATE TABLE IF NOT EXISTS background_command_deliveries (
  command_id         TEXT PRIMARY KEY,
  event_id           TEXT NOT NULL UNIQUE,
  lane_id            INTEGER NOT NULL,
  command_type       TEXT NOT NULL,
  owner_boot_id      TEXT NOT NULL,
  issued_at          REAL NOT NULL,
  deadline_monotonic REAL NOT NULL,
  state              TEXT NOT NULL
                     CHECK (state IN ('pending','completed','indeterminate')),
  ack_status         TEXT,
  original_status    TEXT,
  reason             TEXT,
  attempt_count      INTEGER NOT NULL DEFAULT 1,
  created_at         REAL NOT NULL,
  updated_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_background_command_pending
  ON background_command_deliveries(state,owner_boot_id,deadline_monotonic);
"""


def _ensure_delivery_schema(conn):
    conn.executescript(_DELIVERY_SCHEMA)


def _ensure_schema():
    """Create the lane_state table if it doesn't exist. Idempotent.

    The blob column is still named state_pickle for schema continuity,
    but every accepted runtime snapshot is strict format-v2 UTF-8 JSON.
    Legacy pickle bytes are never deserialized and fail closed in
    :func:`load_lanes`."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lane_state (
                lane_id INTEGER PRIMARY KEY,
                state_pickle BLOB NOT NULL,
                ball_counter INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scoring_event_receipts (
                event_id         TEXT PRIMARY KEY,
                node_id          TEXT NOT NULL,
                lane_id          INTEGER NOT NULL,
                event_type       TEXT NOT NULL,
                event_created_at REAL NOT NULL,
                received_at      REAL NOT NULL,
                payload_json     TEXT NOT NULL,
                disposition      TEXT NOT NULL,
                consumed_by      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_scoring_foul_pending
              ON scoring_event_receipts(lane_id,event_type,consumed_by,
                                        received_at);
            CREATE TABLE IF NOT EXISTS lane_session_generations (
                lane_id          INTEGER PRIMARY KEY,
                generation       INTEGER NOT NULL,
                active           INTEGER NOT NULL,
                scoring_epoch    TEXT,
                request_fingerprint TEXT,
                session_group_id TEXT,
                open_actuation_authorized INTEGER,
                updated_at       REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS manual_score_receipts (
                event_id           TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                result_json        TEXT NOT NULL,
                created_at         REAL NOT NULL,
                FOREIGN KEY(event_id)
                  REFERENCES scoring_event_receipts(event_id)
            );
            CREATE TABLE IF NOT EXISTS manual_score_resolutions (
                event_id           TEXT PRIMARY KEY,
                lane_id            INTEGER NOT NULL,
                actor_id           INTEGER NOT NULL,
                disposition        TEXT NOT NULL,
                note               TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                created_at         REAL NOT NULL,
                FOREIGN KEY(event_id)
                  REFERENCES scoring_event_receipts(event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_manual_score_resolution_lane
              ON manual_score_resolutions(lane_id,created_at);
            CREATE TABLE IF NOT EXISTS bench_ball_operation_receipts (
                operation_key      TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                lane_id            INTEGER NOT NULL,
                session_generation INTEGER NOT NULL,
                scoring_epoch      TEXT NOT NULL,
                issued_at          REAL NOT NULL,
                request_json       TEXT NOT NULL,
                result_json        TEXT NOT NULL,
                created_at         REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bench_ball_operation_lane
              ON bench_ball_operation_receipts(lane_id,created_at);

            CREATE TABLE IF NOT EXISTS control_clock_guard (
              scope               TEXT PRIMARY KEY,
              high_water_epoch    REAL NOT NULL,
              anomaly_latched     INTEGER NOT NULL
                                  CHECK (anomaly_latched IN (0,1)),
              anomaly_detected_at REAL,
              observed_epoch      REAL NOT NULL,
              updated_at          REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS control_clock_reset_audit (
              reset_id              INTEGER PRIMARY KEY AUTOINCREMENT,
              scope                 TEXT NOT NULL,
              prior_high_water      REAL NOT NULL,
              prior_observed_epoch  REAL NOT NULL,
              new_epoch             REAL NOT NULL,
              actor_id              INTEGER NOT NULL,
              note                  TEXT NOT NULL,
              reset_at              REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clock_reset_scope_time
              ON control_clock_reset_audit(scope,reset_at);
        """)
        _ensure_delivery_schema(conn)
        generation_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(lane_session_generations)").fetchall()}
        if "request_fingerprint" not in generation_columns:
            conn.execute(
                "ALTER TABLE lane_session_generations "
                "ADD COLUMN request_fingerprint TEXT")
        if "session_group_id" not in generation_columns:
            conn.execute(
                "ALTER TABLE lane_session_generations "
                "ADD COLUMN session_group_id TEXT")
        if "open_actuation_authorized" not in generation_columns:
            conn.execute(
                "ALTER TABLE lane_session_generations "
                "ADD COLUMN open_actuation_authorized INTEGER")
        conn.commit()


def _strict_payload_json(payload):
    if not isinstance(payload, dict):
        raise ValueError("diagnostic incident payload must be an object")
    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "diagnostic incident payload must be strict JSON") from exc
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("diagnostic incident payload exceeds 65536 bytes")
    return encoded


def _validate_incident_key(incident_key):
    if (not isinstance(incident_key, str)
            or not 1 <= len(incident_key) <= 160):
        raise ValueError("incident_key must contain 1..160 characters")
    return incident_key


def _enqueue_incident_on_connection(
        conn, incident_key, payload_json, created_at=None):
    incident_key = _validate_incident_key(incident_key)
    created_at = time.time() if created_at is None else float(created_at)
    if not math.isfinite(created_at):
        raise ValueError("incident created_at must be finite")
    conn.execute(
        "INSERT OR IGNORE INTO diagnostic_incident_outbox "
        "(incident_key,delivery_id,payload_json,created_at) "
        "VALUES (?,?,?,?)",
        (incident_key, uuid.uuid4().hex, payload_json, created_at))
    return conn.execute(
        "SELECT * FROM diagnostic_incident_outbox WHERE incident_key=?",
        (incident_key,)).fetchone()


def enqueue_diagnostic_incident(
        incident_key, payload, *, timeout_s=0.5):
    """Durably queue a machine-domain incident without touching that DB.

    ``incident_key`` is a semantic idempotency key.  Delivered rows remain as
    tombstones, so replaying a scoring event cannot create a second incident.
    """
    payload_json = _strict_payload_json(payload)
    with _delivery_connection(timeout_s) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _enqueue_incident_on_connection(
            conn, incident_key, payload_json)
        conn.commit()
        return dict(row)


def pending_diagnostic_incidents(*, limit=50, timeout_s=0.5):
    limit = int(limit)
    if not 1 <= limit <= 500:
        raise ValueError("diagnostic incident limit must be 1..500")
    with _delivery_connection(timeout_s) as conn:
        rows = conn.execute(
            "SELECT * FROM diagnostic_incident_outbox "
            "WHERE delivered_at IS NULL ORDER BY outbox_id LIMIT ?",
            (limit,)).fetchall()
    return [dict(row) for row in rows]


def mark_diagnostic_incident_delivered(
        outbox_id, *, timeout_s=0.5):
    with _delivery_connection(timeout_s) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE diagnostic_incident_outbox SET delivered_at=?,"
            "attempt_count=attempt_count+1,last_attempt_at=?,last_error=NULL "
            "WHERE outbox_id=? AND delivered_at IS NULL",
            (time.time(), time.time(), int(outbox_id)))
        conn.commit()
        return cursor.rowcount == 1


def mark_diagnostic_incident_failure(
        outbox_id, error, *, timeout_s=0.5):
    error = str(error)[:1000]
    with _delivery_connection(timeout_s) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE diagnostic_incident_outbox SET "
            "attempt_count=attempt_count+1,last_attempt_at=?,last_error=? "
            "WHERE outbox_id=? AND delivered_at IS NULL",
            (time.time(), error, int(outbox_id)))
        conn.commit()
        return cursor.rowcount == 1


def diagnostic_delivery_status(*, timeout_s=0.5):
    with _delivery_connection(timeout_s) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS pending,MIN(created_at) AS oldest,"
            "MAX(attempt_count) AS max_attempts "
            "FROM diagnostic_incident_outbox WHERE delivered_at IS NULL"
        ).fetchone()
        command_row = conn.execute(
            "SELECT COUNT(*) AS pending FROM background_command_deliveries "
            "WHERE state='pending'").fetchone()
    now = time.time()
    return {
        "pending": int(row["pending"]),
        "oldest_age_s": (
            None if row["oldest"] is None
            else max(0.0, now - float(row["oldest"]))),
        "max_attempts": int(row["max_attempts"] or 0),
        "pending_background_commands": int(command_row["pending"]),
    }


def _background_command_values(delivery):
    required = {
        "command_id", "event_id", "lane_id", "command_type",
        "owner_boot_id", "issued_at", "deadline_monotonic"}
    if not isinstance(delivery, dict) or set(delivery) != required:
        raise ValueError("invalid background command delivery shape")
    command_id = delivery["command_id"]
    event_id = delivery["event_id"]
    lane_id = delivery["lane_id"]
    command_type = delivery["command_type"]
    owner_boot_id = delivery["owner_boot_id"]
    issued_at = delivery["issued_at"]
    deadline = delivery["deadline_monotonic"]
    if (not isinstance(command_id, str) or not 1 <= len(command_id) <= 128
            or not isinstance(event_id, str)
            or not 1 <= len(event_id) <= 128
            or not isinstance(lane_id, int) or isinstance(lane_id, bool)
            or not 1 <= lane_id <= 32
            or not isinstance(command_type, str)
            or not 1 <= len(command_type) <= 80
            or not isinstance(owner_boot_id, str)
            or not 1 <= len(owner_boot_id) <= 80):
        raise ValueError("invalid background command delivery identity")
    for value, name in (
            (issued_at, "issued_at"),
            (deadline, "deadline_monotonic")):
        if (isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))):
            raise ValueError(f"{name} must be finite")
    return (
        command_id, event_id, lane_id, command_type, owner_boot_id,
        float(issued_at), float(deadline))


def begin_background_command_delivery(delivery, *, timeout_s=0.5):
    """Persist CYCLE intent before its socket send.

    A completed command stays completed.  A safe replay of an indeterminate
    or prior pending command re-arms the same immutable identity; node-side
    command deduplication then prevents a second physical pulse.
    """
    values = _background_command_values(delivery)
    now = time.time()
    with _delivery_connection(timeout_s) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM background_command_deliveries WHERE command_id=?",
            (values[0],)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO background_command_deliveries "
                "(command_id,event_id,lane_id,command_type,owner_boot_id,"
                "issued_at,deadline_monotonic,state,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                values + (now, now))
        else:
            immutable = (
                existing["event_id"], int(existing["lane_id"]),
                existing["command_type"], float(existing["issued_at"]))
            if immutable != (
                    values[1], values[2], values[3], values[5]):
                conn.rollback()
                raise ValueError(
                    "background command identity payload collision")
            if existing["state"] != "completed":
                conn.execute(
                    "UPDATE background_command_deliveries SET "
                    "owner_boot_id=?,deadline_monotonic=?,state='pending',"
                    "ack_status=NULL,original_status=NULL,reason=NULL,"
                    "attempt_count=attempt_count+1,updated_at=? "
                    "WHERE command_id=?",
                    (values[4], values[6], now, values[0]))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM background_command_deliveries WHERE command_id=?",
            (values[0],)).fetchone()
        return dict(row)


def background_command_delivery(command_id, *, timeout_s=0.5):
    with _delivery_connection(timeout_s) as conn:
        row = conn.execute(
            "SELECT * FROM background_command_deliveries WHERE command_id=?",
            (command_id,)).fetchone()
    return dict(row) if row is not None else None


def stale_background_command_deliveries(
        current_boot_id, now_monotonic, *, limit=50, timeout_s=0.5):
    if (not isinstance(current_boot_id, str)
            or not 1 <= len(current_boot_id) <= 80):
        raise ValueError("current_boot_id must contain 1..80 characters")
    now_monotonic = float(now_monotonic)
    limit = int(limit)
    with _delivery_connection(timeout_s) as conn:
        rows = conn.execute(
            "SELECT * FROM background_command_deliveries "
            "WHERE state='pending' AND "
            "(owner_boot_id<>? OR deadline_monotonic<=?) "
            "ORDER BY updated_at,command_id LIMIT ?",
            (current_boot_id, now_monotonic, limit)).fetchall()
    return [dict(row) for row in rows]


def finalize_background_command_delivery(
        command_id, state, *, ack_status=None, original_status=None,
        reason=None, incident_key=None, incident_payload=None,
        timeout_s=0.5):
    """Finalize one pending command and optionally enqueue its fault atomically."""
    if state not in {"completed", "indeterminate"}:
        raise ValueError("background command final state is invalid")
    if not isinstance(command_id, str) or not command_id:
        raise ValueError("command_id is required")
    payload_json = None
    if state == "indeterminate":
        if incident_key is None or incident_payload is None:
            raise ValueError(
                "indeterminate command requires a durable incident")
        payload_json = _strict_payload_json(incident_payload)
        _validate_incident_key(incident_key)
    elif incident_key is not None or incident_payload is not None:
        raise ValueError("completed command cannot carry an incident")
    now = time.time()
    with _delivery_connection(timeout_s) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM background_command_deliveries WHERE command_id=?",
            (command_id,)).fetchone()
        if row is None:
            conn.rollback()
            raise ValueError("background command delivery does not exist")
        changed = False
        if row["state"] == "pending":
            cursor = conn.execute(
                "UPDATE background_command_deliveries SET state=?,"
                "ack_status=?,original_status=?,reason=?,updated_at=? "
                "WHERE command_id=? AND state='pending'",
                (state, ack_status, original_status, reason, now, command_id))
            changed = cursor.rowcount == 1
            if changed and payload_json is not None:
                _enqueue_incident_on_connection(
                    conn, incident_key, payload_json, created_at=now)
        conn.commit()
        final = conn.execute(
            "SELECT * FROM background_command_deliveries WHERE command_id=?",
            (command_id,)).fetchone()
        result = dict(final)
        result["changed"] = changed
        return result


# Sentinel lane_id for the single-snapshot row that holds the whole
# lane_scoring dict serialized together. This preserves Python object
# identity across keys — when a CrossLaneScoring is registered under
# both lane 21 and lane 22, after restart the same object is restored
# under both keys (not two independent copies). The original per-row
# format serialized each lane independently, which broke identity.
_SNAPSHOT_LANE_ID = 0

# Bump when the JSON snapshot schema changes incompatibly. A v1 snapshot
# (pre scoring_epoch) upgrades losslessly in memory — see
# _upgrade_snapshot_data. Loads of any OTHER unknown version log and start
# fresh (never guess at field meanings).
STATE_FORMAT_VERSION = 2
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_LANES = 32
MAX_BOWLERS_PER_OBJECT = 64

# Cross-lane bowler attributes set dynamically by CrossLaneScoring
# (BowlerGame has no __slots__, so they live in __dict__).
_BOWLER_EXTRAS = ('starting_physical_lane', 'current_physical_lane',
                  'team_id', 'team_name', 'bowler_id')


# ------------------------------------------------------------------
# JSON round-trip for the scoring objects. Every field is explicit —
# anything the engine adds later must be added here (and the version
# bumped if the change isn't backward-compatible).
# ------------------------------------------------------------------

def _bowl_to_jd(b: Bowl) -> dict:
    return {
        'num': b.num,
        'pin_map': b.pin_map,
        'pins_down': b.pins_down,
        'display': b.display,
        'foul': b.foul,
        'split': b.split,
        'modified': b.modified,
    }


def _bowl_from_jd(d: dict) -> Bowl:
    b = Bowl(num=int(d['num']), pin_map=int(d['pin_map']),
             pins_knocked=int(d['pins_down']),
             display=d.get('display', ''),
             foul=bool(d.get('foul', False)),
             split=bool(d.get('split', False)))
    b.modified = bool(d.get('modified', False))
    return b


def _frame_to_jd(f: Frame) -> dict:
    return {
        'number': f.number,
        'score': f.score,  # None when not yet computable
        'is_strike': f.is_strike,
        'is_spare': f.is_spare,
        'is_complete': f.is_complete,
        'bowls': [_bowl_to_jd(b) for b in f.bowls],
    }


def _frame_from_jd(d: dict) -> Frame:
    f = Frame(int(d['number']))
    score = d.get('score')
    f.score = int(score) if score is not None else None
    f.is_strike = bool(d.get('is_strike', False))
    f.is_spare = bool(d.get('is_spare', False))
    f.is_complete = bool(d.get('is_complete', False))
    f.bowls = [_bowl_from_jd(bd) for bd in d.get('bowls', [])]
    return f


def _bowler_to_jd(b: BowlerGame) -> dict:
    d = {
        'number': b.number,
        'name': b.name,
        'hdcp': b.hdcp,
        'average': b.average,
        'current_frame_idx': b.current_frame_idx,
        'ball_in_frame': b.ball_in_frame,
        'mask_before_ball': b.mask_before_ball,
        # getattr: legacy-pickle-restored bowlers may predate the flag.
        'mask_before_synthetic': bool(getattr(b, 'mask_before_synthetic',
                                              False)),
        'game_over': b.game_over,
        'speed_ball1': b.speed_ball1,
        'speed_ball2': b.speed_ball2,
        'game_number': b.game_number,
        'series_scores': list(b.series_scores),
        'frames': [_frame_to_jd(f) for f in b.frames],
    }
    for attr in _BOWLER_EXTRAS:
        if hasattr(b, attr):
            d[attr] = getattr(b, attr)
    return d


def _bowler_from_jd(d: dict) -> BowlerGame:
    b = BowlerGame(int(d['number']), d['name'],
                   int(d.get('hdcp', 0)), float(d.get('average', 0.0)))
    b.current_frame_idx = int(d.get('current_frame_idx', 0))
    b.ball_in_frame = int(d.get('ball_in_frame', 1))
    b.mask_before_ball = int(d.get('mask_before_ball', 0x3FF))
    b.mask_before_synthetic = bool(d.get('mask_before_synthetic', False))
    b.game_over = bool(d.get('game_over', False))
    b.speed_ball1 = d.get('speed_ball1', 0)
    b.speed_ball2 = d.get('speed_ball2', 0)
    b.game_number = int(d.get('game_number', 1))
    b.series_scores = list(d.get('series_scores', []))
    for fd in d.get('frames', []):
        f = _frame_from_jd(fd)
        if 1 <= f.number <= 10:
            b.frames[f.number - 1] = f
    for attr in _BOWLER_EXTRAS:
        if attr in d:
            setattr(b, attr, d[attr])
    return b


# The engine's _start_new_game caps completed_games at 24 per lane object;
# mirror that bound on restore so a hand-edited / foreign snapshot can't
# balloon the in-memory archive (and every re-save thereafter).
_COMPLETED_GAMES_MAX = 24


def _completed_games_from_jd(d: dict, label: str) -> list:
    """Restore only an explicitly bounded archive; never repair corruption."""
    cg = d.get('completed_games')
    if not isinstance(cg, list):
        raise ValueError(f"{label}: completed_games must be a list")
    if len(cg) > _COMPLETED_GAMES_MAX:
        raise ValueError(
            f"{label}: completed_games exceeds {_COMPLETED_GAMES_MAX}")
    return list(cg)


def _lane_obj_to_jd(ls) -> dict:
    if isinstance(ls, CrossLaneScoring):
        bowlers = list(ls.bowlers)
        idx = {id(b): i for i, b in enumerate(bowlers)}
        return {
            'kind': 'cross',
            'lane_left': ls.lane_left,
            'lane_right': ls.lane_right,
            'game_number': ls.game_number,
            'is_active': ls.is_active,
            'started_at': ls.started_at,
            'scoring_epoch': getattr(ls, 'scoring_epoch', None),
            # H27 archive — finished scoresheets must survive a restart.
            'completed_games': ls.completed_games,
            'bowlers': [_bowler_to_jd(b) for b in bowlers],
            # Queues hold references into bowlers — serialize as indexes
            # so identity is rebuilt on load.
            'lane_queues': {str(lid): [idx[id(b)] for b in q]
                            for lid, q in ls._lane_queues.items()},
        }
    return {
        'kind': 'lane',
        'lane_id': ls.lane_id,
        'current_bowler_idx': ls.current_bowler_idx,
        'game_number': ls.game_number,
        'is_active': ls.is_active,
        'started_at': ls.started_at,
        'scoring_epoch': getattr(ls, 'scoring_epoch', None),
        # H27 archive — finished scoresheets must survive a restart.
        'completed_games': ls.completed_games,
        'bowlers': [_bowler_to_jd(b) for b in ls.bowlers],
    }


def _lane_obj_from_jd(d: dict):
    if d.get('kind') == 'cross':
        obj = CrossLaneScoring(int(d['lane_left']), int(d['lane_right']))
        obj.game_number = int(d.get('game_number', 1))
        obj.is_active = bool(d.get('is_active', False))
        obj.started_at = d.get('started_at')
        obj.scoring_epoch = d.get('scoring_epoch')
        obj.completed_games = _completed_games_from_jd(
            d, f"cross {d.get('lane_left')}/{d.get('lane_right')}")
        bowlers = [_bowler_from_jd(bd) for bd in d.get('bowlers', [])]
        obj.bowlers = bowlers
        queues = {}
        for lid_str, idx_list in (d.get('lane_queues') or {}).items():
            queues[int(lid_str)] = [bowlers[i] for i in idx_list
                                    if 0 <= i < len(bowlers)]
        for lid in (obj.lane_left, obj.lane_right):
            queues.setdefault(lid, [])
        obj._lane_queues = queues
        return obj
    if d.get('kind') == 'lane':
        obj = LaneScoring(int(d['lane_id']))
        obj.current_bowler_idx = int(d.get('current_bowler_idx', 0))
        obj.game_number = int(d.get('game_number', 1))
        obj.is_active = bool(d.get('is_active', False))
        obj.started_at = d.get('started_at')
        obj.scoring_epoch = d.get('scoring_epoch')
        obj.completed_games = _completed_games_from_jd(
            d, f"lane {d.get('lane_id')}")
        obj.bowlers = [_bowler_from_jd(bd) for bd in d.get('bowlers', [])]
        return obj
    raise ValueError(f"unknown lane object kind {d.get('kind')!r}")


def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON number {value!r}")


def _require_exact_keys(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(
            f"{label} fields must be exactly {sorted(required)}")


def _bounded_int(value, minimum, maximum, label):
    if (not isinstance(value, int) or isinstance(value, bool)
            or not minimum <= value <= maximum):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _finite_number(value, minimum, maximum, label):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not minimum <= float(value) <= maximum):
        raise ValueError(
            f"{label} must be finite from {minimum} through {maximum}")
    return value


def _lane_key(value, label):
    if (not isinstance(value, str) or not value.isascii()
            or not value.isdecimal() or str(int(value)) != value):
        raise ValueError(f"{label} must be a canonical decimal lane key")
    return _bounded_int(int(value), 1, MAX_SNAPSHOT_LANES, label)


def _bounded_json_tree(value, label, depth=0):
    if depth > 12:
        raise ValueError(f"{label} exceeds maximum nesting")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError(f"{label} contains oversized text")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} contains a non-finite number")
        return
    if isinstance(value, list):
        if len(value) > 1024:
            raise ValueError(f"{label} contains an oversized list")
        for index, item in enumerate(value):
            _bounded_json_tree(item, f"{label}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 256:
            raise ValueError(f"{label} contains an oversized object")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError(f"{label} contains an invalid object key")
            _bounded_json_tree(item, f"{label}.{key}", depth + 1)
        return
    raise ValueError(f"{label} contains unsupported JSON data")


def _validate_completed_games(value, label):
    if not isinstance(value, list) or len(value) > _COMPLETED_GAMES_MAX:
        raise ValueError(
            f"{label} must contain at most {_COMPLETED_GAMES_MAX} games")
    for index, game in enumerate(value):
        game_label = f"{label}[{index}]"
        _require_exact_keys(
            game, {"game_number", "completed_at", "players"}, game_label)
        _bounded_int(
            game["game_number"], 1, 1_000_000,
            f"{game_label}.game_number")
        if (not isinstance(game["completed_at"], str)
                or not 1 <= len(game["completed_at"]) <= 128):
            raise ValueError(f"{game_label}.completed_at is invalid")
        if (not isinstance(game["players"], list)
                or len(game["players"]) > MAX_BOWLERS_PER_OBJECT):
            raise ValueError(f"{game_label}.players is invalid")
        _bounded_json_tree(game["players"], f"{game_label}.players")


def _validate_bowler(data, label, *, cross_lanes=None):
    base = {
        "number", "name", "hdcp", "average", "current_frame_idx",
        "ball_in_frame", "mask_before_ball", "mask_before_synthetic",
        "game_over", "speed_ball1", "speed_ball2", "game_number",
        "series_scores", "frames",
    }
    extras = set(_BOWLER_EXTRAS) if cross_lanes is not None else set()
    _require_exact_keys(data, base | extras, label)
    _bounded_int(data["number"], 1, MAX_BOWLERS_PER_OBJECT, f"{label}.number")
    if (not isinstance(data["name"], str)
            or not data["name"].strip()
            or len(data["name"]) > 200):
        raise ValueError(f"{label}.name is invalid")
    _bounded_int(data["hdcp"], -1000, 1000, f"{label}.hdcp")
    _finite_number(data["average"], 0, 300, f"{label}.average")
    _bounded_int(data["current_frame_idx"], 0, 9,
                 f"{label}.current_frame_idx")
    _bounded_int(data["ball_in_frame"], 1, 3, f"{label}.ball_in_frame")
    _bounded_int(data["mask_before_ball"], 0, 0x3FF,
                 f"{label}.mask_before_ball")
    for key in ("mask_before_synthetic", "game_over"):
        if type(data[key]) is not bool:
            raise ValueError(f"{label}.{key} must be a JSON boolean")
    _finite_number(data["speed_ball1"], 0, 1000, f"{label}.speed_ball1")
    _finite_number(data["speed_ball2"], 0, 1000, f"{label}.speed_ball2")
    _bounded_int(
        data["game_number"], 1, 1_000_000, f"{label}.game_number")
    series = data["series_scores"]
    if not isinstance(series, list) or len(series) > _COMPLETED_GAMES_MAX:
        raise ValueError(f"{label}.series_scores is invalid")
    for index, score in enumerate(series):
        _bounded_int(score, 0, 300, f"{label}.series_scores[{index}]")
    frames = data["frames"]
    if not isinstance(frames, list) or len(frames) != 10:
        raise ValueError(f"{label}.frames must contain exactly ten frames")
    for frame_index, frame in enumerate(frames):
        frame_label = f"{label}.frames[{frame_index}]"
        _require_exact_keys(
            frame,
            {"number", "score", "is_strike", "is_spare",
             "is_complete", "bowls"},
            frame_label)
        if frame["number"] != frame_index + 1:
            raise ValueError(f"{frame_label}.number is out of sequence")
        score = frame["score"]
        if score is not None:
            _bounded_int(score, 0, 300, f"{frame_label}.score")
        for key in ("is_strike", "is_spare", "is_complete"):
            if type(frame[key]) is not bool:
                raise ValueError(f"{frame_label}.{key} must be boolean")
        bowls = frame["bowls"]
        max_bowls = 3 if frame_index == 9 else 2
        if not isinstance(bowls, list) or len(bowls) > max_bowls:
            raise ValueError(f"{frame_label}.bowls is invalid")
        for bowl_index, bowl in enumerate(bowls):
            bowl_label = f"{frame_label}.bowls[{bowl_index}]"
            _require_exact_keys(
                bowl,
                {"num", "pin_map", "pins_down", "display",
                 "foul", "split", "modified"},
                bowl_label)
            if bowl["num"] != bowl_index + 1:
                raise ValueError(f"{bowl_label}.num is out of sequence")
            _bounded_int(bowl["pin_map"], 0, 0x3FF,
                         f"{bowl_label}.pin_map")
            _bounded_int(bowl["pins_down"], 0, 10,
                         f"{bowl_label}.pins_down")
            if (not isinstance(bowl["display"], str)
                    or len(bowl["display"]) > 16):
                raise ValueError(f"{bowl_label}.display is invalid")
            for key in ("foul", "split", "modified"):
                if type(bowl[key]) is not bool:
                    raise ValueError(f"{bowl_label}.{key} must be boolean")
    if cross_lanes is not None:
        for key in ("starting_physical_lane", "current_physical_lane"):
            if data[key] not in cross_lanes:
                raise ValueError(f"{label}.{key} is outside the lane pair")
        for key in ("team_id", "bowler_id"):
            value = data[key]
            if (value is not None
                    and (isinstance(value, bool)
                         or not isinstance(value, (int, str)))):
                raise ValueError(f"{label}.{key} is invalid")
        if (data["team_name"] is not None
                and (not isinstance(data["team_name"], str)
                     or len(data["team_name"]) > 200)):
            raise ValueError(f"{label}.team_name is invalid")


def _validate_snapshot_data(data):
    _require_exact_keys(
        data, {"format", "version", "objects", "lanes", "ball_counters"},
        "snapshot")
    if data["format"] != "wsl-lane-state":
        raise ValueError(
            f"unrecognized snapshot format {data['format']!r}")
    if data["version"] != STATE_FORMAT_VERSION:
        raise ValueError(
            f"unsupported snapshot version {data['version']!r} "
            f"(this build reads v{STATE_FORMAT_VERSION})")
    objects = data["objects"]
    lanes = data["lanes"]
    counters = data["ball_counters"]
    if not isinstance(objects, list) or len(objects) > MAX_SNAPSHOT_LANES:
        raise ValueError("snapshot.objects is invalid")
    if not isinstance(lanes, dict) or len(lanes) > MAX_SNAPSHOT_LANES:
        raise ValueError("snapshot.lanes is invalid")
    if not isinstance(counters, dict) or len(counters) > MAX_SNAPSHOT_LANES:
        raise ValueError("snapshot.ball_counters is invalid")

    lane_map = {}
    references = {index: [] for index in range(len(objects))}
    for raw_lane, object_index in lanes.items():
        lane = _lane_key(raw_lane, "snapshot.lanes key")
        _bounded_int(
            object_index, 0, max(0, len(objects) - 1),
            f"snapshot.lanes[{raw_lane}]")
        if not objects:
            raise ValueError("lane mapping references an empty object list")
        lane_map[lane] = object_index
        references[object_index].append(lane)
    if any(not refs for refs in references.values()):
        raise ValueError("snapshot contains an unreferenced scoring object")

    seen_object_lanes = set()
    for index, obj in enumerate(objects):
        label = f"snapshot.objects[{index}]"
        if not isinstance(obj, dict):
            raise ValueError(f"{label} must be an object")
        kind = obj.get("kind")
        if kind == "lane":
            _require_exact_keys(
                obj,
                {"kind", "lane_id", "current_bowler_idx", "game_number",
                 "is_active", "started_at", "scoring_epoch",
                 "completed_games", "bowlers"},
                label)
            object_lanes = [
                _bounded_int(
                    obj["lane_id"], 1, MAX_SNAPSHOT_LANES,
                    f"{label}.lane_id")]
            if references[index] != object_lanes:
                raise ValueError(
                    f"{label} lane mapping is not an exact bijection")
        elif kind == "cross":
            _require_exact_keys(
                obj,
                {"kind", "lane_left", "lane_right", "game_number",
                 "is_active", "started_at", "scoring_epoch",
                 "completed_games", "bowlers", "lane_queues"},
                label)
            left = _bounded_int(
                obj["lane_left"], 1, MAX_SNAPSHOT_LANES,
                f"{label}.lane_left")
            right = _bounded_int(
                obj["lane_right"], 1, MAX_SNAPSHOT_LANES,
                f"{label}.lane_right")
            if left == right:
                raise ValueError(f"{label} uses the same lane twice")
            object_lanes = sorted([left, right])
            if sorted(references[index]) != object_lanes:
                raise ValueError(
                    f"{label} cross-lane mapping is not an exact bijection")
        else:
            raise ValueError(f"unknown lane object kind {kind!r}")
        if seen_object_lanes.intersection(object_lanes):
            raise ValueError("snapshot scoring objects overlap lanes")
        seen_object_lanes.update(object_lanes)
        _bounded_int(
            obj["game_number"], 1, 1_000_000, f"{label}.game_number")
        if type(obj["is_active"]) is not bool:
            raise ValueError(f"{label}.is_active must be boolean")
        if (obj["started_at"] is not None
                and (not isinstance(obj["started_at"], str)
                     or not 1 <= len(obj["started_at"]) <= 128)):
            raise ValueError(f"{label}.started_at is invalid")
        if (obj["scoring_epoch"] is not None
                and (not isinstance(obj["scoring_epoch"], str)
                     or not 1 <= len(obj["scoring_epoch"]) <= 128)):
            raise ValueError(f"{label}.scoring_epoch is invalid")
        _validate_completed_games(obj["completed_games"],
                                  f"{label}.completed_games")
        bowlers = obj["bowlers"]
        if (not isinstance(bowlers, list)
                or len(bowlers) > MAX_BOWLERS_PER_OBJECT):
            raise ValueError(f"{label}.bowlers is invalid")
        numbers = []
        for bowler_index, bowler in enumerate(bowlers):
            _validate_bowler(
                bowler, f"{label}.bowlers[{bowler_index}]",
                cross_lanes=(
                    set(object_lanes) if kind == "cross" else None))
            numbers.append(bowler["number"])
            if bowler["game_number"] != obj["game_number"]:
                raise ValueError(
                    f"{label} bowler/object game_number mismatch")
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"{label} contains duplicate bowler numbers")
        if kind == "lane":
            current = obj["current_bowler_idx"]
            _bounded_int(
                current, 0, max(0, len(bowlers) - 1),
                f"{label}.current_bowler_idx")
            if not bowlers and current != 0:
                raise ValueError(
                    f"{label}.current_bowler_idx requires a bowler")
        else:
            queues = obj["lane_queues"]
            if not isinstance(queues, dict):
                raise ValueError(f"{label}.lane_queues must be an object")
            queue_lanes = {
                _lane_key(key, f"{label}.lane_queues key")
                for key in queues
            }
            if queue_lanes != set(object_lanes):
                raise ValueError(
                    f"{label}.lane_queues must exactly match its pair")
            queued = {}
            for raw_lane, indexes in queues.items():
                queue_lane = int(raw_lane)
                if not isinstance(indexes, list):
                    raise ValueError(
                        f"{label}.lane_queues[{raw_lane}] must be a list")
                for position, bowler_index in enumerate(indexes):
                    _bounded_int(
                        bowler_index, 0, max(0, len(bowlers) - 1),
                        f"{label}.lane_queues[{raw_lane}][{position}]")
                    if not bowlers:
                        raise ValueError(
                            f"{label}.lane_queues references no bowlers")
                    if bowler_index in queued:
                        raise ValueError(
                            f"{label} queues reference a bowler twice")
                    queued[bowler_index] = queue_lane
                    if (bowlers[bowler_index]["current_physical_lane"]
                            != queue_lane):
                        raise ValueError(
                            f"{label} queue/current-lane mismatch")
            for bowler_index, bowler in enumerate(bowlers):
                if bowler["game_over"] and bowler_index in queued:
                    raise ValueError(
                        f"{label} queues a completed bowler")
                if not bowler["game_over"] and bowler_index not in queued:
                    raise ValueError(
                        f"{label} omits an active bowler from queues")

    counter_lanes = set()
    for raw_lane, counter in counters.items():
        lane = _lane_key(raw_lane, "snapshot.ball_counters key")
        _bounded_int(
            counter, 0, (1 << 63) - 1,
            f"snapshot.ball_counters[{raw_lane}]")
        counter_lanes.add(lane)
    if not counter_lanes.issubset(set(lane_map)):
        raise ValueError("snapshot has a ball counter without scoring state")
    return {
        "format": data["format"],
        "version": data["version"],
        "lanes": sorted(lane_map),
        "objects": len(objects),
        "ball_counter_lanes": sorted(counter_lanes),
    }


def _upgrade_snapshot_data(data):
    """Lossless in-memory v1 -> v2 snapshot upgrade.

    v2 (rev-D round-4) added exactly one field to each serialized scoring
    object — ``scoring_epoch`` — and made validation strict. A v1 snapshot is
    therefore upgraded by supplying the documented v1 defaults and nothing
    else: ``scoring_epoch`` was unknown to v1 (an epoch is minted when the
    session next arms, so ``None`` is correct), and v1 explicitly loaded a
    missing ``completed_games`` as ``[]``. Anything else that fails the v2
    validator is real corruption and still fails closed. Without this
    upgrade, the first boot after a deploy discarded the live production
    snapshot (open lanes/scores) as "unsupported version 1".
    """
    if not isinstance(data, dict) or data.get('version') != 1:
        return data
    objects = data.get('objects')
    if isinstance(objects, list):
        for obj in objects:
            if isinstance(obj, dict) and obj.get('kind') in ('lane', 'cross'):
                obj.setdefault('scoring_epoch', None)
                obj.setdefault('completed_games', [])
    data['version'] = 2
    log.warning("state snapshot upgraded in memory from v1 to v2 "
                "(scoring_epoch=None); next save persists v2")
    return data


def _parse_snapshot_json(text):
    data = json.loads(
        text, object_pairs_hook=_strict_json_object,
        parse_constant=_reject_json_constant)
    data = _upgrade_snapshot_data(data)
    return data, _validate_snapshot_data(data)


def validate_snapshot_json_bytes(blob):
    """Non-executing strict validator for backup and restore probes."""
    if not isinstance(blob, (bytes, bytearray)):
        raise ValueError("snapshot blob must be bytes")
    if not 1 <= len(blob) <= MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot blob size is invalid")
    if blob.lstrip()[:1] != b"{":
        raise ValueError("legacy/non-JSON snapshots are not supported")
    data, summary = _parse_snapshot_json(bytes(blob).decode("utf-8"))
    return summary


def _snapshot_to_json(lane_scoring: dict, ball_counters: dict) -> str:
    """Whole-state snapshot. Objects are serialized once and referenced
    by index from the lanes map, preserving cross-lane object identity."""
    objects = []
    obj_index = {}
    lanes = {}
    for lid, ls in lane_scoring.items():
        key = id(ls)
        if key not in obj_index:
            obj_index[key] = len(objects)
            objects.append(_lane_obj_to_jd(ls))
        lanes[str(lid)] = obj_index[key]
    data = {
        'format': 'wsl-lane-state',
        'version': STATE_FORMAT_VERSION,
        'objects': objects,
        'lanes': lanes,
        'ball_counters': {str(k): v for k, v in ball_counters.items()},
    }
    _validate_snapshot_data(data)
    return json.dumps(data, allow_nan=False)


def _snapshot_from_json(text: str) -> tuple[dict, dict]:
    data, _summary = _parse_snapshot_json(text)
    objects = [_lane_obj_from_jd(od) for od in data['objects']]
    lane_scoring = {}
    for lid_str, i in data['lanes'].items():
        lane_scoring[int(lid_str)] = objects[i]
    ball_counters = {int(k): int(v)
                     for k, v in data['ball_counters'].items()}
    return lane_scoring, ball_counters


def _receipt_values(receipt):
    required = {
        "event_id", "node_id", "lane_id", "event_type",
        "event_created_at", "payload", "disposition"}
    dispositions = {
        "accepted", "ignored_lane_closed", "awaiting_manual",
        "capture_interrupted_manual_only",
        "clock_anomaly_manual_only", "clock_anomaly_quarantined",
        "stale_quarantined", "overdue_quarantined",
        "duplicate_window_suppressed"}
    if (not isinstance(receipt, dict) or set(receipt) != required
            or receipt.get("disposition") not in dispositions):
        raise ValueError("invalid scoring receipt shape")
    payload = json.dumps(
        receipt["payload"], sort_keys=True, separators=(",", ":"))
    return (
        receipt["event_id"], receipt["node_id"], receipt["lane_id"],
        receipt["event_type"], float(receipt["event_created_at"]),
        time.time(), payload, receipt["disposition"])


def _insert_receipt(conn, receipt):
    conn.execute(
        "INSERT INTO scoring_event_receipts "
        "(event_id,node_id,lane_id,event_type,event_created_at,received_at,"
        "payload_json,disposition) VALUES (?,?,?,?,?,?,?,?)",
        _receipt_values(receipt))


def scoring_event_receipt(event_id):
    """Return an existing immutable receipt, or None."""
    if not isinstance(event_id, str) or not event_id:
        return None
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scoring_event_receipts WHERE event_id=?",
                (event_id,)).fetchone()
    return dict(row) if row is not None else None


def record_scoring_event_receipt(receipt):
    """Commit a non-scoring receipt (FOUL/manual/closed) idempotently.

    A reused event_id with a different immutable payload is a collision, not
    a duplicate.
    """
    values = _receipt_values(receipt)
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT * FROM scoring_event_receipts WHERE event_id=?",
                (receipt["event_id"],)).fetchone()
            if existing is not None:
                same = (
                    existing["node_id"] == values[1]
                    and existing["lane_id"] == values[2]
                    and existing["event_type"] == values[3]
                    and float(existing["event_created_at"]) == values[4]
                    and existing["payload_json"] == values[6])
                if not same:
                    raise ValueError("scoring event_id payload collision")
                return "duplicate", dict(existing)
            _insert_receipt(conn, receipt)
            conn.commit()
    return "accepted", scoring_event_receipt(receipt["event_id"])


def pending_foul_event_ids(lane_id):
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT event_id FROM scoring_event_receipts "
                "WHERE lane_id=? AND event_type='foul_event' "
                "AND disposition='accepted' AND consumed_by IS NULL "
                "ORDER BY received_at,event_id",
                (int(lane_id),)).fetchall()
    return [row[0] for row in rows]


def clear_pending_fouls(lane_id, reason):
    marker = f"cleared:{reason}:{time.time_ns()}"
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE scoring_event_receipts SET consumed_by=? "
                "WHERE lane_id=? AND event_type='foul_event' "
                "AND disposition='accepted' AND consumed_by IS NULL",
                (marker, int(lane_id)))
            conn.commit()


def pending_manual_events(lane_id=None):
    """Return durable, unconsumed operator-score work in arrival order."""
    sql = (
        "SELECT event_id,node_id,lane_id,event_created_at,received_at,"
        "payload_json FROM scoring_event_receipts "
        "WHERE event_type='ball_event' AND disposition IN "
        "('awaiting_manual','capture_interrupted_manual_only',"
        "'clock_anomaly_manual_only') "
        "AND consumed_by IS NULL")
    args = ()
    if lane_id is not None:
        sql += " AND lane_id=?"
        args = (int(lane_id),)
    sql += " ORDER BY received_at,event_id"
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, args).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result


def bench_ball_operation_receipt(operation_key):
    if not isinstance(operation_key, str) or not operation_key:
        return None
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM bench_ball_operation_receipts "
                "WHERE operation_key=?",
                (operation_key,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["request"] = json.loads(result.pop("request_json"))
    result["result"] = json.loads(result.pop("result_json"))
    return result


def _bench_ball_operation_values(operation):
    required = {
        "operation_key", "request_fingerprint", "lane_id",
        "session_generation", "scoring_epoch", "issued_at",
        "request", "result",
    }
    if not isinstance(operation, dict) or set(operation) != required:
        raise ValueError("invalid bench ball operation receipt shape")
    operation_key = operation["operation_key"]
    fingerprint = operation["request_fingerprint"]
    lane_id = operation["lane_id"]
    generation = operation["session_generation"]
    epoch = operation["scoring_epoch"]
    issued_at = operation["issued_at"]
    if (not isinstance(operation_key, str)
            or not 1 <= len(operation_key) <= 100
            or not isinstance(fingerprint, str) or len(fingerprint) != 64
            or not isinstance(lane_id, int) or isinstance(lane_id, bool)
            or not 1 <= lane_id <= 32
            or not isinstance(generation, int)
            or isinstance(generation, bool) or generation <= 0
            or not isinstance(epoch, str) or not epoch
            or not isinstance(issued_at, (int, float))
            or isinstance(issued_at, bool)
            or not math.isfinite(float(issued_at))
            or not isinstance(operation["request"], dict)
            or not isinstance(operation["result"], dict)):
        raise ValueError("invalid bench ball operation receipt values")
    request_json = json.dumps(
        operation["request"], sort_keys=True, separators=(",", ":"),
        allow_nan=False)
    result_json = json.dumps(
        operation["result"], sort_keys=True, separators=(",", ":"),
        allow_nan=False)
    return (
        operation_key, fingerprint, lane_id, generation, epoch,
        float(issued_at), request_json, result_json, time.time())


def manual_score_receipt(event_id):
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_score_receipts WHERE event_id=?",
                (event_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json"))
    return result


def manual_score_resolution(event_id):
    """Return the immutable audited no-score disposition for one event."""
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_score_resolutions WHERE event_id=?",
                (event_id,)).fetchone()
    return dict(row) if row is not None else None


def resolve_manual_score_event(
        event_id, lane_id, actor_id, disposition, note,
        request_fingerprint):
    """Atomically consume pending manual work without inventing a score.

    Returns ``(status, row)`` where status is one of ``resolved``,
    ``replayed``, ``conflict``, ``already_scored``, or ``not_pending``.
    Only an exact replay of the original audited request is idempotent.
    """
    allowed = {"false_trigger_discarded", "session_abandoned"}
    lane_id = int(lane_id)
    if (not isinstance(event_id, str) or not event_id
            or len(event_id) > 128
            or not 1 <= lane_id <= 32
            or not isinstance(actor_id, int) or isinstance(actor_id, bool)
            or actor_id <= 0
            or disposition not in allowed
            or not isinstance(note, str) or not note.strip()
            or len(note.strip()) > 500
            or not isinstance(request_fingerprint, str)
            or len(request_fingerprint) != 64):
        raise ValueError("invalid manual score resolution")
    note = note.strip()
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM manual_score_resolutions WHERE event_id=?",
                (event_id,)).fetchone()
            if existing is not None:
                conn.commit()
                row = dict(existing)
                return (
                    "replayed"
                    if row["request_fingerprint"] == request_fingerprint
                    else "conflict"), row
            if conn.execute(
                    "SELECT 1 FROM manual_score_receipts WHERE event_id=?",
                    (event_id,)).fetchone() is not None:
                conn.commit()
                return "already_scored", None
            consumed = conn.execute(
                "UPDATE scoring_event_receipts "
                "SET consumed_by=? "
                "WHERE event_id=? AND lane_id=? "
                "AND event_type='ball_event' "
                "AND disposition IN "
                "('awaiting_manual','capture_interrupted_manual_only',"
                "'clock_anomaly_manual_only') "
                "AND consumed_by IS NULL",
                (f"manual_resolution:{event_id}", event_id, lane_id))
            if consumed.rowcount != 1:
                conn.commit()
                return "not_pending", None
            created_at = time.time()
            conn.execute(
                "INSERT INTO manual_score_resolutions "
                "(event_id,lane_id,actor_id,disposition,note,"
                "request_fingerprint,created_at) VALUES (?,?,?,?,?,?,?)",
                (event_id, lane_id, actor_id, disposition, note,
                 request_fingerprint, created_at))
            conn.commit()
    return "resolved", {
        "event_id": event_id,
        "lane_id": lane_id,
        "actor_id": actor_id,
        "disposition": disposition,
        "note": note,
        "request_fingerprint": request_fingerprint,
        "created_at": created_at,
    }


def lane_session_generation(lane_id):
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM lane_session_generations WHERE lane_id=?",
                (int(lane_id),)).fetchone()
    return dict(row) if row is not None else None


def lane_session_generation_group(lane_id):
    """Return current rows sharing one explicit logical session group.

    Keeping the group lookup in the state owner lets a retired-generation
    retry reconstruct every stable CLOSE command even though the in-memory
    shared scorer has already been removed.  A legacy/null group is
    deliberately lane-local; request fingerprints are operation identities
    and are not overloaded as topology.
    """
    lane_id = int(lane_id)
    with _db_lock:
        _ensure_schema()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM lane_session_generations WHERE lane_id=?",
                (lane_id,)).fetchone()
            if row is None:
                return []
            group_id = row["session_group_id"]
            if group_id is None:
                return [dict(row)]
            rows = conn.execute(
                "SELECT * FROM lane_session_generations "
                "WHERE session_group_id=? ORDER BY lane_id",
                (group_id,)).fetchall()
    return [dict(item) for item in rows]


def _apply_session_updates(conn, updates):
    for lane_id, item in (updates or {}).items():
        lane_id = int(lane_id)
        generation = item.get("generation")
        active = item.get("active")
        epoch = item.get("scoring_epoch")
        fingerprint = item.get("request_fingerprint")
        group_id = item.get("session_group_id")
        open_authorized = item.get("open_actuation_authorized")
        if (not 1 <= lane_id <= 32
                or not isinstance(generation, int)
                or isinstance(generation, bool) or generation <= 0
                or type(active) is not bool
                or (epoch is not None
                    and (not isinstance(epoch, str) or not epoch
                         or len(epoch) > 200))
                or (fingerprint is not None
                    and (not isinstance(fingerprint, str)
                         or len(fingerprint) != 64))
                or (group_id is not None
                    and (not isinstance(group_id, str)
                         or not group_id.strip()
                         or len(group_id) > 200))
                or (open_authorized is not None
                    and type(open_authorized) is not bool)):
            raise ValueError("invalid lane session generation update")
        conn.execute(
            "INSERT INTO lane_session_generations "
            "(lane_id,generation,active,scoring_epoch,"
            "request_fingerprint,session_group_id,"
            "open_actuation_authorized,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(lane_id) DO UPDATE SET "
            "generation=excluded.generation,active=excluded.active,"
            "scoring_epoch=excluded.scoring_epoch,"
            "request_fingerprint=excluded.request_fingerprint,"
            "session_group_id=COALESCE("
            "excluded.session_group_id,"
            "lane_session_generations.session_group_id),"
            "open_actuation_authorized=COALESCE("
            "excluded.open_actuation_authorized,"
            "lane_session_generations.open_actuation_authorized),"
            "updated_at=excluded.updated_at",
            (lane_id, generation, int(active), epoch, fingerprint,
             group_id, (
                 None if open_authorized is None
                 else int(open_authorized)), time.time()))


def save_lanes(lane_scoring: dict, ball_counters: dict, *,
               scoring_receipt=None, consume_foul_lane=None,
               session_updates=None, clear_foul_lanes=None,
               manual_score=None,
               bench_ball_operation=None,
               guard_no_pending_manual_lanes=None) -> bool:
    """Persist the current state of every lane.

    Called on every BALL_EVENT (write-through) and on graceful
    shutdown. Best-effort — exceptions are logged but don't propagate;
    losing a save shouldn't crash the server. Failures are counted and
    surfaced via get_save_status() so monitoring can alert.

    Format: a single versioned-JSON snapshot stored under lane_id=0.
    This preserves object identity for CrossLaneScoring objects that
    span multiple lane keys.
    """
    try:
        blob = _snapshot_to_json(lane_scoring, ball_counters).encode('utf-8')
        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("BEGIN IMMEDIATE")
                guarded_lanes = sorted({
                    int(lane_id)
                    for lane_id in (guard_no_pending_manual_lanes or ())})
                if guarded_lanes:
                    placeholders = ",".join("?" for _ in guarded_lanes)
                    pending = conn.execute(
                        "SELECT event_id FROM scoring_event_receipts "
                        "WHERE lane_id IN (" + placeholders + ") "
                        "AND event_type='ball_event' "
                        "AND disposition IN "
                        "('awaiting_manual',"
                        "'capture_interrupted_manual_only',"
                        "'clock_anomaly_manual_only') "
                        "AND consumed_by IS NULL LIMIT 1",
                        guarded_lanes).fetchone()
                    if pending is not None:
                        raise ValueError(
                            "pending manual scoring blocks session transition")
                # Replace the snapshot row + remove any legacy per-lane
                # rows from the prior format. Without the DELETE, closed
                # lanes would resurrect on next load because the legacy
                # rows persist independently of the new snapshot.
                conn.execute("DELETE FROM lane_state WHERE lane_id != ?",
                             (_SNAPSHOT_LANE_ID,))
                conn.execute(
                    "INSERT OR REPLACE INTO lane_state "
                    "(lane_id, state_pickle, ball_counter, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (_SNAPSHOT_LANE_ID, blob, 0, time.time())
                )
                if scoring_receipt is not None:
                    _insert_receipt(conn, scoring_receipt)
                if consume_foul_lane is not None:
                    marker = (
                        scoring_receipt["event_id"]
                        if scoring_receipt is not None
                        else f"desk:{time.time_ns()}")
                    conn.execute(
                        "UPDATE scoring_event_receipts SET consumed_by=? "
                        "WHERE lane_id=? AND event_type='foul_event' "
                        "AND disposition='accepted' AND consumed_by IS NULL",
                        (marker, int(consume_foul_lane)))
                for clear_lane in (clear_foul_lanes or ()):
                    conn.execute(
                        "UPDATE scoring_event_receipts SET consumed_by=? "
                        "WHERE lane_id=? AND event_type='foul_event' "
                        "AND disposition='accepted' AND consumed_by IS NULL",
                        (f"session_transition:{time.time_ns()}",
                         int(clear_lane)))
                if manual_score is not None:
                    event_id = manual_score.get("event_id")
                    fingerprint = manual_score.get("request_fingerprint")
                    result = manual_score.get("result")
                    if (not isinstance(event_id, str) or not event_id
                            or not isinstance(fingerprint, str)
                            or len(fingerprint) != 64
                            or not isinstance(result, dict)):
                        raise ValueError("invalid manual score receipt")
                    consumed = conn.execute(
                        "UPDATE scoring_event_receipts SET consumed_by=? "
                        "WHERE event_id=? AND event_type='ball_event' "
                        "AND disposition IN "
                        "('awaiting_manual',"
                        "'capture_interrupted_manual_only',"
                        "'clock_anomaly_manual_only') "
                        "AND consumed_by IS NULL",
                        (f"manual_score:{event_id}", event_id))
                    if consumed.rowcount != 1:
                        raise ValueError(
                            "manual scoring event is missing or consumed")
                    conn.execute(
                        "INSERT INTO manual_score_receipts "
                        "(event_id,request_fingerprint,result_json,created_at) "
                        "VALUES (?,?,?,?)",
                        (event_id, fingerprint, json.dumps(
                            result, sort_keys=True, separators=(",", ":")),
                         time.time()))
                if bench_ball_operation is not None:
                    conn.execute(
                        "INSERT INTO bench_ball_operation_receipts "
                        "(operation_key,request_fingerprint,lane_id,"
                        "session_generation,scoring_epoch,issued_at,"
                        "request_json,result_json,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        _bench_ball_operation_values(
                            bench_ball_operation))
                _apply_session_updates(conn, session_updates)
                conn.commit()
        _record_save_ok()
        return True
    except Exception as e:
        _record_save_failure(e)
        return False


def _decode_snapshot_blob(blob: bytes) -> tuple[dict, dict, bool]:
    """Decode one bounded JSON snapshot without executable fallbacks."""
    validate_snapshot_json_bytes(blob)
    ls, bc = _snapshot_from_json(bytes(blob).decode("utf-8"))
    return ls, bc, False


def load_lanes() -> tuple[dict, dict]:
    """Restore the most recent saved state.

    Returns (lane_scoring, ball_counters). Both are empty dicts if
    the DB doesn't exist, the schema is missing, or the saved state
    fails to decode (e.g. snapshot version from a newer build).

    Reads the single-snapshot row (lane_id=0). If only legacy per-lane
    rows exist (from before the snapshot-format change), those are
    ignored — start fresh and the next save_lanes() will overwrite
    them. Legacy pickle snapshots are never executed.
    """
    lane_scoring: dict = {}
    ball_counters: dict = {}
    try:
        if not DB_PATH.exists():
            log.info(f"No saved state found at {DB_PATH}; starting fresh.")
            _record_load_ok("fresh_database")
            return lane_scoring, ball_counters

        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.execute(
                    "SELECT state_pickle, updated_at FROM lane_state "
                    "WHERE lane_id = ?",
                    (_SNAPSHOT_LANE_ID,)
                )
                row = cur.fetchone()
                if row is None:
                    # No snapshot row — either fresh DB or legacy format.
                    # Either way, start fresh.
                    legacy_count = conn.execute(
                        "SELECT COUNT(*) FROM lane_state").fetchone()[0]
                    if legacy_count:
                        log.warning(
                            f"DB at {DB_PATH} has {legacy_count} legacy "
                            f"per-lane row(s) but no snapshot. Ignoring "
                            f"legacy rows (cross-lane identity unreliable); "
                            f"starting fresh.")
                        _record_load_failure(
                            "legacy_rows_discarded",
                            f"{legacy_count} legacy per-lane rows lacked the "
                            "identity-preserving snapshot")
                    else:
                        log.info(f"No saved state in {DB_PATH}; starting fresh.")
                        _record_load_ok("empty_database")
                    return lane_scoring, ball_counters

                blob, updated_at = row
                try:
                    lane_scoring, ball_counters, _was_legacy = \
                        _decode_snapshot_blob(blob)
                except Exception as e:
                    log.warning(
                        f"Failed to decode snapshot: {e}. Usually a schema/"
                        f"class-shape mismatch. Starting fresh.")
                    _record_load_failure("snapshot_decode_failed", e)
                    return {}, {}

                age_min = (time.time() - updated_at) / 60
                log.info(f"Restored {len(lane_scoring)} lane(s) from snapshot "
                         f"(updated {age_min:.1f} min ago).")
                # Confirm cross-lane identity preservation in the log so
                # any future regression is visible at boot.
                shared = {}
                for lid, ls in lane_scoring.items():
                    shared.setdefault(id(ls), []).append(lid)
                for ls_id, lane_ids in shared.items():
                    if len(lane_ids) > 1:
                        log.info(f"  Cross-lane scoring object spans lanes "
                                 f"{sorted(lane_ids)} (identity preserved)")
    except Exception as e:
        log.warning(f"load_lanes failed: {e}; starting fresh.")
        _record_load_failure("database_load_failed", e)
        return {}, {}

    _record_load_ok("snapshot_restored")
    return lane_scoring, ball_counters


def clear_state() -> None:
    """Wipe all saved state. Useful for tests + manual recovery from
    a bad save (e.g. corrupted snapshot). Doesn't delete the DB file
    itself, just the rows."""
    try:
        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM lane_state")
                conn.execute("DELETE FROM manual_score_resolutions")
                conn.execute("DELETE FROM manual_score_receipts")
                conn.execute("DELETE FROM bench_ball_operation_receipts")
                conn.execute("DELETE FROM scoring_event_receipts")
                conn.execute("DELETE FROM lane_session_generations")
                conn.execute("DELETE FROM background_command_deliveries")
                conn.execute("DELETE FROM diagnostic_incident_outbox")
                conn.commit()
        log.info(f"Cleared all saved state from {DB_PATH}")
        _record_load_ok("explicitly_cleared")
        # Initialize a fresh test/maintenance database, but never erase an
        # existing anomaly latch: observe_control_wall_clock only advances
        # the high-water and preserves latched state.
        observe_control_wall_clock()
    except Exception as e:
        log.warning(f"clear_state failed: {e}")
        _record_load_failure(
            "explicit_clear_failed", e, discarded=False)


if __name__ == '__main__':
    # Quick CLI for inspection: python3 state_store.py [list|clear]
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    if len(sys.argv) > 1 and sys.argv[1] == 'clear':
        clear_state()
    else:
        ls, bc = load_lanes()
        print(f"Loaded {len(ls)} lane(s):")
        for lane_id, lane in ls.items():
            print(f"  Lane {lane_id}: {len(lane.bowlers)} bowlers, "
                  f"ball_counter={bc.get(lane_id, 0)}")
            for b in lane.bowlers:
                print(f"    - {b.name}: frame {b.current_frame_idx + 1}, "
                      f"score {b.current_total}")
