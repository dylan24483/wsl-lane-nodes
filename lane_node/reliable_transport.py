#!/usr/bin/env python3
"""Small durable ledgers for the lane-node WebSocket transport.

The scoring outbox is intentionally separate from the diagnostics JSONL
outbox.  A BALL/FOUL frame changes scoring state and therefore stays pending
until the server returns an idempotent receipt for its event_id.  SQLite gives
the Pi an ordered, crash-recoverable queue without introducing another
service.

The command ledger implements the safe side of the two-generals problem for
physical commands.  A command is durably marked ``started`` before GPIO is
touched and ``completed`` afterwards.  A crash in between is reported as
ambiguous and is never automatically replayed; that can miss an actuation, but
it cannot double-pulse a machine.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import sqlite3
import threading
import time
from pathlib import Path


class TransportError(RuntimeError):
    """The durable transport ledger could not complete an operation."""


class DurableTransport:
    def __init__(self, path, event_capacity=128):
        self.path = Path(path)
        self.event_capacity = max(1, int(event_capacity))
        self._lock = threading.Lock()
        self._last_error = None
        self._init()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=0.25)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=250")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init(self):
        schema = """
        CREATE TABLE IF NOT EXISTS scoring_event_outbox (
          position         INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id         TEXT NOT NULL UNIQUE,
          event_created_at REAL NOT NULL,
          frame_json       TEXT NOT NULL,
          admitted_at      REAL NOT NULL,
          ready            INTEGER NOT NULL DEFAULT 1
                           CHECK (ready IN (0,1))
        );
        CREATE INDEX IF NOT EXISTS idx_scoring_event_position
          ON scoring_event_outbox(position);

        CREATE TABLE IF NOT EXISTS camera_capture_jobs (
          event_id         TEXT PRIMARY KEY,
          lane_id          INTEGER NOT NULL,
          event_created_at REAL NOT NULL,
          edge_frame_json  TEXT NOT NULL,
          admitted_at      REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_camera_capture_admitted
          ON camera_capture_jobs(admitted_at);

        CREATE TABLE IF NOT EXISTS command_receipts (
          command_id       TEXT PRIMARY KEY,
          command_type     TEXT NOT NULL,
          lane_id          INTEGER NOT NULL,
          received_at      REAL NOT NULL,
          state            TEXT NOT NULL,
          completed_at     REAL,
          result_json      TEXT
          ,payload_sha256  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_command_receipts_completed
          ON command_receipts(completed_at);

        CREATE TABLE IF NOT EXISTS transport_clock_guard (
          scope               TEXT PRIMARY KEY,
          high_water_epoch    REAL NOT NULL,
          anomaly_latched     INTEGER NOT NULL
                              CHECK (anomaly_latched IN (0,1)),
          anomaly_detected_at REAL,
          observed_epoch      REAL NOT NULL,
          updated_at          REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transport_clock_reset_audit (
          reset_id              INTEGER PRIMARY KEY AUTOINCREMENT,
          prior_high_water      REAL NOT NULL,
          prior_observed_epoch  REAL NOT NULL,
          new_epoch             REAL NOT NULL,
          actor_id              INTEGER NOT NULL,
          note                  TEXT NOT NULL,
          reset_at              REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transport_clock_reset_time
          ON transport_clock_reset_audit(reset_at);
        """
        try:
            with self._lock, self._connect() as conn:
                conn.executescript(schema)
                command_columns = {
                    row["name"] for row in conn.execute(
                        "PRAGMA table_info(command_receipts)")}
                if "payload_sha256" not in command_columns:
                    conn.execute(
                        "ALTER TABLE command_receipts "
                        "ADD COLUMN payload_sha256 TEXT")
                event_columns = {
                    row["name"] for row in conn.execute(
                        "PRAGMA table_info(scoring_event_outbox)")}
                if "ready" not in event_columns:
                    conn.execute(
                        "ALTER TABLE scoring_event_outbox "
                        "ADD COLUMN ready INTEGER NOT NULL DEFAULT 1")

                # Upgrade an interrupted capture from the earlier two-table
                # representation into a reserved FIFO row.  admitted_at is
                # the only ordering evidence that representation retained;
                # capture jobs win exact timestamp ties so uncertainty blocks
                # later scoring instead of allowing it to overtake.
                jobs = conn.execute(
                    "SELECT * FROM camera_capture_jobs").fetchall()
                outbox_by_id = {
                    row["event_id"]: row for row in conn.execute(
                        "SELECT * FROM scoring_event_outbox")}
                missing_jobs = [
                    row for row in jobs
                    if row["event_id"] not in outbox_by_id]
                for job in jobs:
                    existing = outbox_by_id.get(job["event_id"])
                    if existing is not None:
                        if existing["frame_json"] != job["edge_frame_json"]:
                            raise TransportError(
                                "capture job/outbox payload collision")
                        conn.execute(
                            "UPDATE scoring_event_outbox SET ready=0 "
                            "WHERE event_id=?", (job["event_id"],))
                if missing_jobs:
                    ordered = [
                        (
                            float(row["admitted_at"]), 1,
                            int(row["position"]), row["event_id"],
                            float(row["event_created_at"]),
                            row["frame_json"], False)
                        for row in outbox_by_id.values()
                    ] + [
                        (
                            float(row["admitted_at"]), 0, 0,
                            row["event_id"],
                            float(row["event_created_at"]),
                            row["edge_frame_json"], True)
                        for row in missing_jobs
                    ]
                    ordered.sort(key=lambda item: item[:4])
                    offset = (
                        int(conn.execute(
                            "SELECT COALESCE(MAX(position),0) "
                            "FROM scoring_event_outbox").fetchone()[0])
                        + len(ordered) + 1)
                    conn.execute(
                        "UPDATE scoring_event_outbox "
                        "SET position=position+?", (offset,))
                    for position, item in enumerate(ordered, start=1):
                        (_admitted, _capture_first, _old_position, event_id,
                         created, frame_json, is_capture) = item
                        if event_id in outbox_by_id:
                            conn.execute(
                                "UPDATE scoring_event_outbox "
                                "SET position=? WHERE event_id=?",
                                (position, event_id))
                        else:
                            conn.execute(
                                "INSERT INTO scoring_event_outbox "
                                "(position,event_id,event_created_at,"
                                "frame_json,admitted_at,ready) "
                                "VALUES (?,?,?,?,?,0)",
                                (position, event_id, created, frame_json,
                                 _admitted))
                    conn.execute(
                        "DELETE FROM sqlite_sequence "
                        "WHERE name='scoring_event_outbox'")
                    conn.execute(
                        "INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)",
                        ("scoring_event_outbox", len(ordered)))
                # Command receipts are safety tombstones.  Do not age them
                # out from wall-clock time: a clock jump followed by rollback
                # could otherwise make an old command ID executable again.
                # Any future compaction must be an explicit, generation-bound
                # maintenance operation with independent evidence.
                conn.commit()
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    @staticmethod
    def _event_fields(frame_json):
        try:
            frame = json.loads(frame_json)
        except Exception as exc:
            raise ValueError("scoring event frame is not valid JSON") from exc
        if not isinstance(frame, dict):
            raise ValueError("scoring event frame must be an object")
        event_id = frame.get("event_id")
        created = frame.get("event_created_at")
        if (not isinstance(event_id, str) or not event_id.strip()
                or len(event_id) > 128):
            raise ValueError("scoring event_id must be 1..128 characters")
        if (isinstance(created, bool)
                or not isinstance(created, (int, float))
                or not math.isfinite(float(created))):
            raise ValueError("scoring event_created_at must be finite")
        return event_id, float(created)

    def put_event(self, frame_json):
        """Durably append one event.

        Returns ``admitted`` or ``duplicate``.  Capacity refusal is explicit
        and leaves the existing ordered queue unchanged.
        """
        event_id, created = self._event_fields(frame_json)
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT frame_json FROM scoring_event_outbox "
                    "WHERE event_id=?",
                    (event_id,)).fetchone()
                if existing is not None:
                    conn.commit()
                    self._last_error = None
                    return (
                        "duplicate"
                        if existing["frame_json"] == frame_json
                        else "collision")
                count = conn.execute(
                    "SELECT COUNT(*) FROM scoring_event_outbox"
                ).fetchone()[0]
                if count >= self.event_capacity:
                    conn.rollback()
                    return "full"
                conn.execute(
                    "INSERT INTO scoring_event_outbox "
                    "(event_id,event_created_at,frame_json,admitted_at) "
                    "VALUES (?,?,?,?)",
                    (event_id, created, frame_json, time.time()))
                conn.commit()
            self._last_error = None
            return "admitted"
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    @staticmethod
    def _capture_fields(frame_json):
        event_id, created = DurableTransport._event_fields(frame_json)
        frame = json.loads(frame_json)
        lane = frame.get("lane")
        if (frame.get("type") != "ball_event"
                or not isinstance(lane, int) or isinstance(lane, bool)
                or not 1 <= lane <= 32
                or frame.get("pin_mask") is not None
                or frame.get("awaiting_manual") is not True):
            raise ValueError(
                "camera edge frame must be an awaiting-manual ball_event")
        return event_id, created, lane, frame

    def begin_capture_job(self, edge_frame_json):
        """Durably reserve a physical camera edge before GPIO returns."""
        event_id, created, lane, _frame = self._capture_fields(
            edge_frame_json)
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                outbox = conn.execute(
                    "SELECT frame_json,ready FROM scoring_event_outbox "
                    "WHERE event_id=?", (event_id,)).fetchone()
                existing = conn.execute(
                    "SELECT edge_frame_json FROM camera_capture_jobs "
                    "WHERE event_id=?", (event_id,)).fetchone()
                if outbox is not None:
                    conn.commit()
                    return (
                        "duplicate"
                        if (outbox["frame_json"] == edge_frame_json
                            and int(outbox["ready"]) == 0)
                        else "collision")
                if existing is not None:
                    conn.commit()
                    return (
                        "duplicate"
                        if existing["edge_frame_json"] == edge_frame_json
                        else "collision")
                count = conn.execute(
                    "SELECT COUNT(*) FROM scoring_event_outbox"
                ).fetchone()[0]
                if count >= self.event_capacity:
                    conn.rollback()
                    return "full"
                conn.execute(
                    "INSERT INTO scoring_event_outbox "
                    "(event_id,event_created_at,frame_json,admitted_at,ready) "
                    "VALUES (?,?,?,?,0)",
                    (event_id, created, edge_frame_json, time.time()))
                conn.execute(
                    "INSERT INTO camera_capture_jobs "
                    "(event_id,lane_id,event_created_at,edge_frame_json,"
                    "admitted_at) VALUES (?,?,?,?,?)",
                    (event_id, lane, created, edge_frame_json, time.time()))
                conn.commit()
            self._last_error = None
            return "admitted"
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def complete_capture_job(self, event_id, final_frame_json):
        """Atomically enrich a raw edge into the ordered scoring outbox."""
        final_id, created = self._event_fields(final_frame_json)
        if final_id != event_id:
            raise ValueError("capture completion event_id mismatch")
        final = json.loads(final_frame_json)
        if final.get("type") != "ball_event":
            raise ValueError("capture completion must be a ball_event")
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                job = conn.execute(
                    "SELECT * FROM camera_capture_jobs WHERE event_id=?",
                    (event_id,)).fetchone()
                outbox = conn.execute(
                    "SELECT frame_json,ready FROM scoring_event_outbox "
                    "WHERE event_id=?", (event_id,)).fetchone()
                if job is None:
                    conn.commit()
                    if outbox is None:
                        return "missing"
                    return (
                        "duplicate"
                        if (outbox["frame_json"] == final_frame_json
                            and int(outbox["ready"]) == 1)
                        else "collision")
                edge = json.loads(job["edge_frame_json"])
                if (int(job["lane_id"]) != final.get("lane")
                        or float(job["event_created_at"]) != created
                        or edge.get("scoring_epoch")
                        != final.get("scoring_epoch")):
                    conn.rollback()
                    return "collision"
                if (outbox is None or int(outbox["ready"]) != 0
                        or outbox["frame_json"] != job["edge_frame_json"]):
                    conn.rollback()
                    return "collision"
                conn.execute(
                    "UPDATE scoring_event_outbox "
                    "SET frame_json=?,ready=1 WHERE event_id=?",
                    (final_frame_json, event_id))
                conn.execute(
                    "DELETE FROM camera_capture_jobs WHERE event_id=?",
                    (event_id,))
                conn.commit()
            self._last_error = None
            return "admitted"
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def recover_capture_jobs(self):
        """Promote crash-orphaned edges to manual scoring, in edge order."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                jobs = conn.execute(
                    "SELECT * FROM camera_capture_jobs "
                    "ORDER BY admitted_at,event_id").fetchall()
                recovered = 0
                for job in jobs:
                    event_id = job["event_id"]
                    recovered_frame = json.loads(job["edge_frame_json"])
                    recovered_frame["capture_interrupted"] = True
                    recovered_json = json.dumps(
                        recovered_frame, sort_keys=True, separators=(",", ":"))
                    exists = conn.execute(
                        "SELECT frame_json,ready FROM scoring_event_outbox "
                        "WHERE event_id=?", (event_id,)).fetchone()
                    if (exists is None or int(exists["ready"]) != 0
                            or exists["frame_json"]
                            != job["edge_frame_json"]):
                        raise TransportError(
                            "capture recovery event_id payload collision")
                    conn.execute(
                        "UPDATE scoring_event_outbox "
                        "SET frame_json=?,ready=1 WHERE event_id=?",
                        (recovered_json, event_id))
                    recovered += 1
                    conn.execute(
                        "DELETE FROM camera_capture_jobs WHERE event_id=?",
                        (event_id,))
                conn.commit()
            self._last_error = None
            return recovered
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def capture_jobs(self):
        """Read-only capture-job evidence for health and regression tests."""
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT event_id,lane_id,event_created_at,edge_frame_json,"
                    "admitted_at FROM camera_capture_jobs "
                    "ORDER BY admitted_at,event_id").fetchall()
            self._last_error = None
            return [dict(row) for row in rows]
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def peek_event(self):
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT position,event_id,event_created_at,frame_json,"
                    "ready "
                    "FROM scoring_event_outbox ORDER BY position LIMIT 1"
                ).fetchone()
            self._last_error = None
            if row is None or int(row["ready"]) == 0:
                return None
            result = dict(row)
            result.pop("ready")
            return result
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def ack_event(self, event_id):
        """Remove only the current head after its matching server receipt."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT event_id,ready FROM scoring_event_outbox "
                    "ORDER BY position LIMIT 1").fetchone()
                if row is None:
                    conn.rollback()
                    return False
                if row["event_id"] != event_id:
                    # Retiring a head is deliberately idempotent.  The
                    # executor thread can finish the DELETE after its asyncio
                    # waiter is cancelled during a socket drop; the next
                    # connection then receives the same server receipt for
                    # the still-in-memory pending event.  If that ID is
                    # already absent, acknowledge the completed retirement
                    # without disturbing the new head.  An ID that still
                    # exists later in the queue remains an ordering error.
                    exists = conn.execute(
                        "SELECT 1 FROM scoring_event_outbox "
                        "WHERE event_id=?",
                        (event_id,)).fetchone()
                    conn.rollback()
                    if exists is None:
                        return False
                    raise TransportError(
                        "event ACK does not match durable outbox head")
                if int(row["ready"]) != 1:
                    conn.rollback()
                    raise TransportError(
                        "event ACK cannot retire an incomplete capture")
                conn.execute(
                    "DELETE FROM scoring_event_outbox WHERE event_id=?",
                    (event_id,))
                conn.commit()
            self._last_error = None
            return True
        except TransportError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def event_health(self):
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM scoring_event_outbox) AS outbox_depth,"
                    "(SELECT COUNT(*) FROM camera_capture_jobs) AS capture_jobs,"
                    "(SELECT MIN(event_created_at) "
                    " FROM scoring_event_outbox) AS outbox_oldest,"
                    "(SELECT MIN(event_created_at) "
                    " FROM camera_capture_jobs) AS capture_oldest"
                ).fetchone()
            now = time.time()
            candidates = [
                value for value in (row["outbox_oldest"],)
                if value is not None]
            oldest = min(candidates) if candidates else None
            age = None if oldest is None else max(0.0, now - float(oldest))
            capture_oldest = row["capture_oldest"]
            capture_age = (
                None if capture_oldest is None
                else max(0.0, now - float(capture_oldest)))
            self._last_error = None
            return {
                "ok": True,
                "depth": int(row["outbox_depth"]),
                "capacity": self.event_capacity,
                "oldest_age_s": age,
                "capture_jobs": int(row["capture_jobs"]),
                "capture_oldest_age_s": capture_age,
                "error": None,
            }
        except Exception as exc:
            self._last_error = str(exc)
            return {
                "ok": False,
                "depth": 0,
                "capacity": self.event_capacity,
                "oldest_age_s": None,
                "capture_jobs": 0,
                "capture_oldest_age_s": None,
                "error": str(exc),
            }

    def observe_wall_clock(self, now=None, rollback_tolerance_s=5.0):
        """Advance the physical-command UTC high-water and latch rollback."""
        observed = time.time() if now is None else now
        if (isinstance(observed, bool)
                or not isinstance(observed, (int, float))
                or not math.isfinite(float(observed))):
            raise ValueError("wall-clock observation must be finite")
        tolerance = float(rollback_tolerance_s)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("rollback tolerance must be nonnegative")
        observed = float(observed)
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM transport_clock_guard "
                    "WHERE scope='physical_command'").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO transport_clock_guard "
                        "(scope,high_water_epoch,anomaly_latched,"
                        "anomaly_detected_at,observed_epoch,updated_at) "
                        "VALUES ('physical_command',?,0,NULL,?,?)",
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
                        "UPDATE transport_clock_guard "
                        "SET high_water_epoch=?,anomaly_latched=?,"
                        "anomaly_detected_at=?,observed_epoch=?,updated_at=? "
                        "WHERE scope='physical_command'",
                        (max(high_water, observed), int(latched),
                         detected_at, observed, observed))
                conn.commit()
            self._last_error = None
            return self.wall_clock_status()
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def wall_clock_status(self):
        """Read durable command-clock evidence without advancing it."""
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT high_water_epoch,anomaly_latched,"
                    "anomaly_detected_at,observed_epoch "
                    "FROM transport_clock_guard "
                    "WHERE scope='physical_command'").fetchone()
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc
        if row is None:
            return {
                "observed": False,
                "high_water_epoch": None,
                "anomaly_latched": False,
                "anomaly_detected_at": None,
                "observed_epoch": None,
            }
        return {
            "observed": True,
            "high_water_epoch": float(row["high_water_epoch"]),
            "anomaly_latched": bool(row["anomaly_latched"]),
            "anomaly_detected_at": (
                None if row["anomaly_detected_at"] is None
                else float(row["anomaly_detected_at"])),
            "observed_epoch": float(row["observed_epoch"]),
        }

    def reset_wall_clock(self, confirmed_utc_epoch, actor_id, note):
        """Reset a latched Pi guard; caller must prove the daemon is offline."""
        epoch = confirmed_utc_epoch
        if (isinstance(epoch, bool)
                or not isinstance(epoch, (int, float))
                or not math.isfinite(float(epoch))):
            raise ValueError("confirmed_utc_epoch must be finite")
        if (not isinstance(actor_id, int) or isinstance(actor_id, bool)
                or actor_id <= 0):
            raise ValueError("actor_id must be a positive integer")
        if (not isinstance(note, str)
                or not 10 <= len(note.strip()) <= 500):
            raise ValueError("note must contain 10..500 characters")
        epoch = float(epoch)
        note = note.strip()
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                prior = conn.execute(
                    "SELECT * FROM transport_clock_guard "
                    "WHERE scope='physical_command'").fetchone()
                if prior is None or not bool(prior["anomaly_latched"]):
                    conn.rollback()
                    raise ValueError("clock anomaly is not latched")
                reset_at = time.time()
                cursor = conn.execute(
                    "INSERT INTO transport_clock_reset_audit "
                    "(prior_high_water,prior_observed_epoch,new_epoch,"
                    "actor_id,note,reset_at) VALUES (?,?,?,?,?,?)",
                    (float(prior["high_water_epoch"]),
                     float(prior["observed_epoch"]), epoch, actor_id,
                     note, reset_at))
                conn.execute(
                    "UPDATE transport_clock_guard SET high_water_epoch=?,"
                    "anomaly_latched=0,anomaly_detected_at=NULL,"
                    "observed_epoch=?,updated_at=? "
                    "WHERE scope='physical_command'",
                    (epoch, epoch, reset_at))
                conn.commit()
            self._last_error = None
            return {
                "reset_id": int(cursor.lastrowid),
                "prior_high_water": float(prior["high_water_epoch"]),
                "prior_observed_epoch": float(prior["observed_epoch"]),
                "new_epoch": epoch,
                "actor_id": actor_id,
                "note": note,
                "reset_at": reset_at,
            }
        except ValueError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def begin_command(self, command_id, command_type, lane_id, payload):
        """Claim a command before actuation.

        Returns ``new``, ``completed``, ``ambiguous``, or ``collision`` plus
        the stored result when one exists. A semantically identical
        ``scoring_epoch_sync`` left started by a crash is reclaimable as
        ``new`` because repeating that state assignment cannot actuate.
        """
        now = time.time()
        if not isinstance(payload, dict):
            raise ValueError("command payload must be an object")
        # ``ts`` is the websocket envelope timestamp and is regenerated for
        # every delivery attempt.  ``issued_at`` normally remains part of the
        # immutable bounded authorization.  SCORING_EPOCH_SYNC is the sole
        # exception: it cannot actuate hardware, so its authorization may be
        # renewed while its lane/generation/epoch semantic identity stays
        # stable and payload-bound.
        excluded = {"token", "ts"}
        if payload.get("type") == "scoring_epoch_sync":
            excluded.add("issued_at")
        canonical = json.dumps(
            {key: value for key, value in payload.items()
             if key not in excluded},
            sort_keys=True, separators=(",", ":"))
        payload_sha256 = hashlib.sha256(
            canonical.encode("utf-8")).hexdigest()
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM command_receipts WHERE command_id=?",
                    (command_id,)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO command_receipts "
                        "(command_id,command_type,lane_id,received_at,state,"
                        "payload_sha256) VALUES (?,?,?,?,?,?)",
                        (command_id, command_type, lane_id, now, "started",
                         payload_sha256))
                    conn.commit()
                    self._last_error = None
                    return "new", None
                conn.commit()
            if (row["command_type"] != command_type
                    or int(row["lane_id"]) != int(lane_id)
                    or row["payload_sha256"] != payload_sha256):
                return "collision", None
            result = (json.loads(row["result_json"])
                      if row["result_json"] else None)
            if (row["state"] != "completed"
                    and command_type == "scoring_epoch_sync"):
                return "new", None
            return ("completed" if row["state"] == "completed"
                    else "ambiguous"), result
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc

    def complete_command(self, command_id, result):
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "UPDATE command_receipts SET state='completed', "
                    "completed_at=?, result_json=? "
                    "WHERE command_id=? AND state='started'",
                    (time.time(), payload, command_id))
                if cur.rowcount != 1:
                    raise TransportError(
                        "command completion does not match a started receipt")
                conn.commit()
            self._last_error = None
        except TransportError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise TransportError(str(exc)) from exc


def default_transport_path():
    diag_dir = os.environ.get("WSL_DIAG_DIR", "").strip() or "./diag_logs"
    configured = os.environ.get("WSL_SCORING_TRANSPORT_DB", "").strip()
    return Path(configured) if configured else (
        Path(diag_dir) / "reliable_transport.sqlite3")
