#!/usr/bin/env python3
"""
diag_events.py — diagnostics event core for the Phase 8 machine-diagnostics
campaign (docs/phase8_diagnostics_scope_2026-07-19.md §2/§3).

WHAT IT IS
  The Pi-side event pipe: rules/emitters build small typed DiagEvent records
  (severity 'info'|'warn'|'fault', writer-validated event_type, JSON-safe
  detail), push them into a BOUNDED non-blocking DiagQueue, and a single
  background DiagWriter thread drains the queue into sinks — a local JSONL
  file (JsonlSink, daily-rotated, batched writes for SD wear) and, when a
  server URL is configured, HTTP POSTs to the :8766 machine-events ingest
  (HttpSink). This is the "bounded in-memory queue + writer thread" leg of
  the alerting path (scope §3.1).

OBSERVE-ONLY + BOUNDED + FAIL-SAFE (the standing rules; see flight_recorder.py)
  * OBSERVE-ONLY: nothing here touches a relay, the FSM, ARM, or the watchdog.
    Events describe; they never actuate.
  * BOUNDED: the queue is a hard-capped queue.Queue; overflow DROPS the event
    and counts it (DiagQueue.drops). Sink buffers flush at N events / T
    seconds, so memory is O(queue max + batch size) regardless of soak length.
  * FAIL-SAFE / NEVER-BLOCK: emit() never blocks and never raises — it must be
    callable from anywhere, including (indirectly) code adjacent to the 50 Hz
    tick. All file/network I/O happens ONLY on the DiagWriter thread. Every
    sink call is wrapped; a sink bug degrades to a counted no-op.

ENV (kill-switches + knobs, WSL_* house pattern):
  WSL_DIAG_ENABLED     default '1'  — '0'/'false'/... disables the writer +
                       makes emit() a cheap no-op. Local logging is safe-on.
  WSL_DIAG_QUEUE_MAX   default 1000 — bounded queue capacity.
  WSL_DIAG_DIR         default './diag_logs' — JsonlSink output directory.
  WSL_DIAG_MAX_FILES   default 30   — JsonlSink daily files kept (oldest pruned).
  WSL_DIAG_SERVER_URL  unset by default — when set, DiagWriter also builds an
                       HttpSink posting batches to <url>/api/machine/events
                       (and cycle rows to <url>/api/machine/cycles).

USAGE
    w = DiagWriter()          # JsonlSink always; HttpSink iff server URL set
    w.start()
    ...
    w.emit(make_event(21, "warn", "beam_blocked", code="diell:L",
                      detail={"held_s": 12.4}))
    ...
    w.stop()                  # drains the queue + flushes every sink
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import socket
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("diag_events")

# ---- env knobs (WSL_* house pattern) -------------------------------------------
ENABLE_ENV = "WSL_DIAG_ENABLED"          # default ON ('1'); falsey disables
QUEUE_MAX_ENV = "WSL_DIAG_QUEUE_MAX"     # bounded queue capacity
DIR_ENV = "WSL_DIAG_DIR"                 # JsonlSink directory
MAX_FILES_ENV = "WSL_DIAG_MAX_FILES"     # JsonlSink daily-file retention
SERVER_URL_ENV = "WSL_DIAG_SERVER_URL"   # HttpSink base URL (unset = no HTTP)
# Shared auth token for the :8766 POSTs — the SAME env lane_node.py and the
# wsl_api bridge use. lane_node_server gates EVERY POST (machine ingest
# included) behind X-Lane-Token when LANE_NODE_TOKEN is set (the documented
# production posture), so a token-less HttpSink would get 401 on every batch
# and silently drop it (2026-07-19 review). Unset = current open behavior.
TOKEN_ENV = "LANE_NODE_TOKEN"
# R2-12 (Codex round-2, 2026-07-21) — JSONL-as-outbox delivery semantics:
#   WSL_DIAG_SOURCE_ID   stable per-device id (default: hostname). Combined
#                        with the per-process boot_id + a monotonic seq, every
#                        record gets a delivery identity (source_id, boot_id,
#                        seq) the server dedupes on (UNIQUE index, INSERT OR
#                        IGNORE) — replays after drops are idempotent.
#   WSL_DIAG_OUTBOX      default '1'. When the HTTP leg is configured
#                        (WSL_DIAG_SERVER_URL), events ship via the
#                        OutboxReplayer: ONE write path (the JSONL file IS the
#                        outbox), a persisted cursor advanced only on 2xx
#                        (cursor-ack), replay resumes after any drop/outage.
#                        Set '0' to fall back to the legacy live HttpSink leg.
#   WSL_DIAG_OUTBOX_POLL_S  replay poll cadence (default 10 s).
SOURCE_ID_ENV = "WSL_DIAG_SOURCE_ID"
OUTBOX_ENV = "WSL_DIAG_OUTBOX"
OUTBOX_POLL_ENV = "WSL_DIAG_OUTBOX_POLL_S"
DEFAULT_OUTBOX_POLL_S = 10.0
OUTBOX_BATCH_MAX = 200          # lines read + POSTed per replay pass segment
CURSOR_FILENAME = "outbox_cursor.json"
QUARANTINE_FILENAME = "outbox_quarantine.jsonl"   # R3-1c: server-rejected rows
QUARANTINE_STATE_FILENAME = "outbox_quarantine_state.json"
QUARANTINE_CLEAR_AUDIT_FILENAME = "outbox_quarantine_clear.jsonl"
# Quarantine growth bound (review fix): the quarantine file is append-only on
# every server reject, its 'outbox_' prefix is NOT covered by JsonlSink._prune
# (prefix 'diag-'), and a lost-ack replay of a mixed accepted+rejected segment
# re-quarantines the same rows. Cap the file and rotate to a single .1 so total
# on-disk stays <= ~2x the cap; dedup already-quarantined records by delivery
# identity so a replay doesn't re-write (and re-emit) them.
QUARANTINE_MAX_BYTES_ENV = "WSL_DIAG_QUARANTINE_MAX_BYTES"
DEFAULT_QUARANTINE_MAX_BYTES = 256 * 1024
QUARANTINE_DEDUP_MAX = 512        # bounded FIFO of recently-quarantined identities


def _reject_nonfinite(const):
    """json.loads parse_constant hook (R3-10 robustness): NaN / Infinity /
    -Infinity in a stored line are treated as corruption, not silently
    turned into float('nan') that then poisons downstream math."""
    raise ValueError(f"non-finite JSON constant {const!r}")


def _fsync_parent(path):
    """Persist a created/replaced directory entry on the deployed POSIX host."""
    if os.name != "posix":
        return
    directory = os.path.dirname(os.path.abspath(path)) or "."
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


DEFAULT_QUEUE_MAX = 1000
DEFAULT_DIR = "./diag_logs"
DEFAULT_MAX_FILES = 30
# Batched-write cadence (SD-wear rule, scope §6 "batched local writes"): flush a
# sink buffer when it holds this many events OR this many seconds have passed.
DEFAULT_FLUSH_N = 20
DEFAULT_FLUSH_S = 5.0
DEFAULT_HTTP_TIMEOUT_S = 2.0
DEFAULT_HTTP_RETRIES = 2

# R3-1a (2026-07-23): the machine-diagnostics vocabulary has ONE source —
# server/machine_contract.json. The client loads SEVERITIES and the
# event-type allow-set from that same file (not a private copy) so a type
# the daemon emits can never silently disagree with what the server
# validates (the fw_identity poison pill, R3-1). If the file is unreadable
# (running the client from an odd cwd, a partial checkout), SEVERITIES falls
# back to the frozen triple and EVENT_TYPES to None (== "don't second-guess
# the taxonomy client-side"); the server stays the authority either way.
_CONTRACT_JSON = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "server", "machine_contract.json"))


def _load_contract_vocab():
    try:
        with open(_CONTRACT_JSON, encoding="utf-8") as f:
            v = json.load(f)["vocab"]
        return tuple(v["severities"]), frozenset(v["event_types"])
    except Exception:
        return ("info", "warn", "fault"), None


SEVERITIES, EVENT_TYPES = _load_contract_vocab()

_FALSEY = ("0", "false", "no", "off", "")


def _enabled_from_env():
    """True unless the kill-switch env var is explicitly falsey."""
    return os.environ.get(ENABLE_ENV, "1").strip().lower() not in _FALSEY


def _int_env(name, default):
    """Read a positive int env var; any garbage / non-positive -> default."""
    try:
        v = int(os.environ.get(name, "").strip() or default)
        return v if v > 0 else default
    except Exception:
        return default


def _env_on_default(name, default="1"):
    """True unless the env var is explicitly falsey (WSL_* house pattern)."""
    return os.environ.get(name, default).strip().lower() not in _FALSEY


def _float_env(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except Exception:
        return float(default)


# ---- delivery identity (R2-12: source_id / boot_id / monotonic seq) ------------
# boot_id is PER PROCESS START (uuid4): two daemons on one Pi, or a restart of
# the same daemon, can never collide on (source_id, boot_id, seq). seq is a
# process-wide monotonic counter shared by every writer instance in the process.
_BOOT_ID = uuid.uuid4().hex
_seq_lock = threading.Lock()
_seq_counter = 0


def source_id():
    """Stable per-device source id: WSL_DIAG_SOURCE_ID, else hostname."""
    sid = os.environ.get(SOURCE_ID_ENV, "").strip()
    if sid:
        return sid[:120]
    try:
        return (socket.gethostname() or "unknown")[:120]
    except Exception:
        return "unknown"


def boot_id():
    return _BOOT_ID


def next_seq():
    """Process-wide monotonic sequence number (delivery identity)."""
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def stamp_delivery(row):
    """Stamp delivery-identity fields onto a row dict IN PLACE (idempotent —
    existing identity fields are never overwritten). Never raises."""
    try:
        row.setdefault("source_id", source_id())
        row.setdefault("boot_id", _BOOT_ID)
        row.setdefault("seq", next_seq())
    except Exception:
        pass
    return row


# ---- JSON-safety coercion (bounded; mirrors flight_recorder._jsonable) ---------
_MAX_STR = 500
_MAX_ITEMS = 50
_MAX_DEPTH = 4


def _json_safe(v, _depth=0):
    """Coerce an arbitrary value into something json.dumps can always take.
    Bounded in string length, container size and nesting depth so one
    pathological detail dict can't bloat the pipe."""
    if v is None or isinstance(v, bool) or isinstance(v, int):
        return v
    if isinstance(v, float):
        # Python's json encoder emits NaN/Infinity by default even though they
        # are not JSON.  Those tokens used to land in the durable file and the
        # strict replayer then consumed them as corrupt rows.  Keep numeric
        # fields numeric when finite; represent a non-finite observation as
        # unknown instead of writing invalid JSON.
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return v if len(v) <= _MAX_STR else v[:_MAX_STR] + "...(truncated)"
    if _depth < _MAX_DEPTH:
        if isinstance(v, dict):
            out = {}
            for i, (k, val) in enumerate(v.items()):
                if i >= _MAX_ITEMS:
                    out["...(truncated)"] = True
                    break
                out[_json_safe(str(k))] = _json_safe(val, _depth + 1)
            return out
        if isinstance(v, (list, tuple)):
            out = [_json_safe(x, _depth + 1) for x in list(v)[:_MAX_ITEMS]]
            if len(v) > _MAX_ITEMS:
                out.append("...(truncated)")
            return out
    try:
        s = str(v)
    except Exception:
        return "?"
    return s if len(s) <= _MAX_STR else s[:_MAX_STR] + "...(truncated)"


# ---- the event -----------------------------------------------------------------
class DiagEvent:
    """One typed diagnostics event. Validated AT CONSTRUCTION (the writer side of
    'writer-validated'): a bad severity / event_type raises ValueError right at
    the emitter, where the bug is — never downstream in the pipe. The detail
    dict is coerced JSON-safe here (bounded), so serialization can't fail later.

    R3-1a (client half of the single-source vocab): BOTH the severity AND the
    event_type are checked against the ONE contract file (server/machine_
    contract.json) the server also validates against. When the contract loaded,
    an unknown / typo'd event_type raises HERE at the emitter — it is NOT merely
    caught after a server round-trip (rejected[]/quarantine). When the contract
    was unreadable at import (EVENT_TYPES is None — an odd cwd / partial
    checkout), the client defers to the server rather than second-guess a
    taxonomy it could not load.
    """

    __slots__ = ("ts_utc", "ts_mono", "lane_id", "severity", "event_type",
                 "code", "detail")

    def __init__(self, ts_utc, ts_mono, lane_id, severity, event_type,
                 code=None, detail=None):
        if severity not in SEVERITIES:
            raise ValueError(f"severity {severity!r} not in {SEVERITIES}")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError(f"event_type must be a non-empty string, got {event_type!r}")
        et = event_type.strip()[:80]
        # R3-1a: the event-type allow-set is load-bearing on the CLIENT, not
        # just the server. This is what makes EVENT_TYPES an actual gate rather
        # than dead-loaded state.
        if EVENT_TYPES is not None and et not in EVENT_TYPES:
            raise ValueError(
                f"event_type {et!r} not in contract vocab.event_types "
                f"(server/machine_contract.json) — the R3-1 drift class")
        if detail is not None and not isinstance(detail, dict):
            raise ValueError(f"detail must be a dict or None, got {type(detail).__name__}")
        self.ts_utc = str(ts_utc)
        self.ts_mono = float(ts_mono)
        self.lane_id = int(lane_id)
        self.severity = severity
        self.event_type = et
        self.code = None if code is None else str(code)[:120]
        self.detail = _json_safe(detail) if detail else {}

    def to_dict(self):
        return {
            "ts_utc": self.ts_utc,
            "ts_mono": self.ts_mono,
            "lane_id": self.lane_id,
            "severity": self.severity,
            "event_type": self.event_type,
            "code": self.code,
            "detail": self.detail,
        }

    def __repr__(self):
        return (f"DiagEvent(L{self.lane_id} {self.severity} {self.event_type}"
                f"{' ' + self.code if self.code else ''} @ {self.ts_utc})")


def make_event(lane_id, severity, event_type, code=None, detail=None, *,
               now=None, ts_utc=None):
    """Constructor helper: stamps UTC wall time (ISO 8601, tz-aware) + monotonic
    time and builds a validated DiagEvent. `now` (monotonic clock) and `ts_utc`
    are injectable for tests."""
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    ts_mono = (now or time.monotonic)()
    return DiagEvent(ts_utc, ts_mono, lane_id, severity, event_type,
                     code=code, detail=detail)


def _outbox_row_age_s(row, now_epoch):
    """Return age from an immutable timestamp carried by an outbox row."""
    if not isinstance(row, dict):
        raise ValueError("outbox row is not an object")
    raw = None
    for key in ("created_at", "ts_utc", "ended_at", "started_at"):
        if key in row:
            raw = row.get(key)
            break
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("outbox row has no immutable timestamp")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("outbox timestamp is not timezone-aware")
    age = float(now_epoch) - stamp.timestamp()
    if age < -300.0:
        raise ValueError("outbox timestamp is implausibly in the future")
    return max(0.0, age)


# ---- the bounded, never-blocking queue -----------------------------------------
class DiagQueue:
    """Hard-capped producer queue. emit() NEVER blocks and NEVER raises: a full
    queue (or any other failure) drops the event and bumps `drops`. The counter
    is a plain int (diagnostic, not load-bearing — same stance as the
    flight-recorder's writer list: atomic enough under the GIL)."""

    def __init__(self, maxsize=None):
        self.maxsize = maxsize if (maxsize and int(maxsize) > 0) \
            else _int_env(QUEUE_MAX_ENV, DEFAULT_QUEUE_MAX)
        self._q = queue.Queue(maxsize=self.maxsize)
        self.drops = 0

    def emit(self, event):
        """Enqueue one event. Returns True if queued, False if dropped."""
        try:
            self._q.put_nowait(event)
            return True
        except Exception:
            self.drops += 1
            return False

    def get(self, timeout=0.25):
        """Dequeue one event (writer thread only), or None on timeout/failure."""
        try:
            if timeout is None or timeout <= 0:
                return self._q.get_nowait()
            return self._q.get(timeout=timeout)
        except Exception:
            return None

    def empty(self):
        try:
            return self._q.empty()
        except Exception:
            return True

    def qsize(self):
        try:
            return self._q.qsize()
        except Exception:
            return 0


# ---- sinks ---------------------------------------------------------------------
class JsonlSink:
    """Append-only local JSONL sink. Daily-rotated files (diag-YYYYMMDD.jsonl,
    UTC date), pruned to `max_files`, and BATCHED: rows buffer in memory and hit
    the disk in one open/write per flush (every `flush_n` events or `flush_s`
    seconds — the SD-wear rule). All methods swallow their own exceptions and
    count failures in `write_errors`.  A failed batch remains resident and is
    retried; the buffer is capped at one flush batch, so later arrivals are
    explicitly counted in `dropped` rather than silently growing memory or
    replacing the oldest durable candidates."""

    FILE_PREFIX = "diag-"
    FILE_SUFFIX = ".jsonl"

    def __init__(self, dir_path=None, *, max_files=None,
                 flush_n=DEFAULT_FLUSH_N, flush_s=DEFAULT_FLUSH_S,
                 now=None, today=None):
        self.dir = dir_path or os.environ.get(DIR_ENV, "").strip() or DEFAULT_DIR
        self.max_files = max_files if (max_files and int(max_files) > 0) \
            else _int_env(MAX_FILES_ENV, DEFAULT_MAX_FILES)
        self.flush_n = max(1, int(flush_n))
        self.flush_s = float(flush_s)
        self._now = now or time.monotonic
        # UTC date for rotation (injectable in tests)
        self._today = today or (lambda: time.strftime("%Y%m%d", time.gmtime()))
        # Shared with OutboxReplayer when this sink is the durable outbox.
        # Appends and rollover-tail repair must never race: a partial line in
        # the CURRENT daily file may simply be an append in progress, while a
        # partial line in an INACTIVE (older) file is crash residue that must
        # be sealed or it will block every newer daily file forever.
        self._io_lock = threading.RLock()
        self._buf = []
        self._last_flush = self._now()
        self._last_day = None
        self.write_errors = 0
        self.retry_batches = 0
        self.dropped = 0
        self.prune_deferred = 0
        self.repaired_tails = 0
        # Enabled by DiagWriter/OutboxReplayer when these files are the durable
        # delivery queue. Local-log-only users retain ordinary max_files
        # pruning because no acknowledgement cursor exists for them.
        self.protect_unacked = False
        self.written = 0
        # A crash during append can leave a non-newline tail. Seal it now so
        # the next valid record cannot be concatenated into—and lost inside—
        # that corrupt fragment. The replayer will quarantine the sealed row.
        try:
            self._repair_tail(os.path.join(
                self.dir,
                f"{self.FILE_PREFIX}{self._today()}{self.FILE_SUFFIX}"))
        except Exception:
            self.write_errors += 1

    def emit(self, row):
        """Buffer one JSON-safe dict; flush when the batch is full. Never raises."""
        try:
            # If a prior full batch failed, retry it before accepting another
            # row.  This retains the oldest-first ordering and bounds memory.
            if len(self._buf) >= self.flush_n:
                self.flush()
            if len(self._buf) >= self.flush_n:
                self.dropped += 1
                return False
            self._buf.append(_json_safe(row))
            if len(self._buf) >= self.flush_n:
                self.flush()
            return True
        except Exception:
            self.write_errors += 1
            self.dropped += 1
            log.debug("JsonlSink.emit swallowed", exc_info=True)
            return False

    def maybe_flush(self):
        """Time-based flush check (called each writer loop). Never raises."""
        try:
            if self._buf and (self._now() - self._last_flush) >= self.flush_s:
                self.flush()
        except Exception:
            self.write_errors += 1

    def flush(self):
        """Write the whole buffer in ONE append-open (SD-wear rule). Never raises."""
        with self._io_lock:
            self._last_flush = self._now()
            rows = list(self._buf)
            if not rows:
                return True
            try:
                day = self._today()
                os.makedirs(self.dir, exist_ok=True)
                path = os.path.join(
                    self.dir, f"{self.FILE_PREFIX}{day}{self.FILE_SUFFIX}")
                if not self._repair_tail(path):
                    raise OSError("could not seal partial JSONL tail")
                lines = [json.dumps(_json_safe(r), separators=(",", ":"),
                                    allow_nan=False) for r in rows]
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_parent(path)
                # Clear only after the append completed.  A partial/failed
                # append can duplicate rows on retry, which is safe because
                # every outbox row has a delivery identity and the server
                # deduplicates it.
                del self._buf[:len(rows)]
                self.written += len(rows)
                if day != self._last_day:      # new file appeared -> prune old
                    self._last_day = day
                    self._prune()
                return True
            except Exception:
                self.write_errors += 1
                self.retry_batches += 1
                log.debug("JsonlSink.flush retained %d rows for retry",
                          len(rows), exc_info=True)
                return False

    @property
    def pending_writes(self):
        return len(self._buf)

    def _repair_tail(self, path):
        """Seal a prior partial append with a newline. Returns False only when
        a non-newline tail was found but could not be sealed."""
        with self._io_lock:
            try:
                size = os.path.getsize(path)
                if size <= 0:
                    return True
                with open(path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) == b"\n":
                        return True
                with open(path, "ab") as f:
                    f.write(b"\n")
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_parent(path)
                self.repaired_tails += 1
                return True
            except FileNotFoundError:
                return True
            except Exception:
                self.write_errors += 1
                return False

    def seal_inactive_tail(self, name):
        """Seal a torn tail only when ``name`` is not this sink's current UTC
        daily file.

        OutboxReplayer calls this only for a file that has a newer successor.
        The shared lock serializes the proof and repair with ``flush()``.  A
        standalone replayer without its writer's sink deliberately cannot use
        this operation: failing closed is preferable to appending a newline to
        a line an uncoordinated writer may still be extending.
        """
        if (not isinstance(name, str) or os.path.basename(name) != name
                or not name.startswith(self.FILE_PREFIX)
                or not name.endswith(self.FILE_SUFFIX)):
            return False
        with self._io_lock:
            active = f"{self.FILE_PREFIX}{self._today()}{self.FILE_SUFFIX}"
            if name == active:
                return False
            return self._repair_tail(os.path.join(self.dir, name))

    def _prune(self):
        """Keep at most max_files daily logs without deleting unacked outbox
        data. In outbox mode only files strictly older than the persisted
        cursor are proven fully resolved and eligible for removal."""
        with self._io_lock:
            try:
                names = sorted(
                    n for n in os.listdir(self.dir)
                    if n.startswith(self.FILE_PREFIX)
                    and n.endswith(self.FILE_SUFFIX))
                excess = max(0, len(names) - self.max_files)
                if not excess:
                    return
                candidates = names[:-self.max_files]
                if self.protect_unacked:
                    cursor = self._validated_cursor_file(names)
                    # Missing/invalid cursor proves nothing was delivered.
                    candidates = (
                        [name for name in candidates if name < cursor]
                        if cursor is not None else [])
                    if len(candidates) < excess:
                        self.prune_deferred += excess - len(candidates)
                for old in candidates[:excess]:
                    try:
                        path = os.path.join(self.dir, old)
                        os.remove(path)
                        _fsync_parent(path)
                    except Exception:
                        self.prune_deferred += 1
            except Exception:
                self.prune_deferred += 1

    def _validated_cursor_file(self, names):
        """Return the cursor filename only after full boundary validation."""
        try:
            with open(os.path.join(self.dir, CURSOR_FILENAME),
                      encoding="utf-8") as f:
                raw = json.load(f)
            if (not isinstance(raw, dict)
                    or not isinstance(raw.get("file"), str)
                    or raw["file"] not in names
                    or not isinstance(raw.get("pos"), int)
                    or isinstance(raw.get("pos"), bool)
                    or raw["pos"] < 0):
                return None
            cursor_path = os.path.join(self.dir, raw["file"])
            size = os.path.getsize(cursor_path)
            if raw["pos"] > size:
                return None
            if raw["pos"] == 0:
                return raw["file"]
            with open(cursor_path, "rb") as cursor_file:
                cursor_file.seek(raw["pos"] - 1)
                return (raw["file"]
                        if cursor_file.read(1) == b"\n" else None)
        except Exception:
            return None

    def prune_to_size(self, max_bytes):
        """Prune daily files to a byte cap without deleting unacked data.

        In outbox mode, only files strictly older than a validated persisted
        cursor are eligible. The cursor file and every newer file are retained
        even when that means the cap cannot be met. Local-log-only mode keeps
        the active and newest daily files. Returns an observable result dict;
        failures and an unmet cap increment ``prune_deferred``.
        """
        result = {
            "pruned": [],
            "freed_bytes": 0,
            "total_bytes": 0,
            "cap_bytes": max(0, int(max_bytes)),
            "deferred": False,
        }
        with self._io_lock:
            try:
                names = sorted(
                    n for n in os.listdir(self.dir)
                    if n.startswith(self.FILE_PREFIX)
                    and n.endswith(self.FILE_SUFFIX))
                sizes = {}
                for name in names:
                    sizes[name] = os.path.getsize(
                        os.path.join(self.dir, name))
                total = sum(sizes.values())
                result["total_bytes"] = total
                if total <= result["cap_bytes"] or not names:
                    return result

                if self.protect_unacked:
                    cursor = self._validated_cursor_file(names)
                    candidates = ([name for name in names if name < cursor]
                                  if cursor is not None else [])
                else:
                    active = (
                        f"{self.FILE_PREFIX}{self._today()}{self.FILE_SUFFIX}")
                    protected = {active, names[-1]}
                    candidates = [
                        name for name in names if name not in protected]

                for name in candidates:
                    if total <= result["cap_bytes"]:
                        break
                    path = os.path.join(self.dir, name)
                    try:
                        os.remove(path)
                        _fsync_parent(path)
                        freed = sizes[name]
                        total -= freed
                        result["freed_bytes"] += freed
                        result["pruned"].append(name)
                    except Exception:
                        result["deferred"] = True

                result["total_bytes"] = total
                if total > result["cap_bytes"]:
                    result["deferred"] = True
                if result["deferred"]:
                    self.prune_deferred += 1
                return result
            except Exception:
                self.prune_deferred += 1
                result["deferred"] = True
                return result


class HttpSink:
    """POSTs event batches to the lane-node server (scope §3.2 interim HTTP leg).
    Inactive (every call a no-op) unless a base URL is configured. Uses urllib
    with a short timeout and a bounded retry; a batch that still fails is
    DROPPED and counted — never retried forever, never buffered unbounded, and
    never raised to the caller. `post` is injectable (tests fake the HTTP layer).

    Contract (server ingest lands in Phase 2; shapes per the scope-doc schema):
      POST <base>/api/machine/events   body {"events": [event-dict, ...]}
      POST <base>/api/machine/cycles   body {"cycle": row-dict}
    """

    EVENTS_PATH = "/api/machine/events"
    CYCLES_PATH = "/api/machine/cycles"

    def __init__(self, base_url=None, *, timeout=DEFAULT_HTTP_TIMEOUT_S,
                 retries=DEFAULT_HTTP_RETRIES, flush_n=DEFAULT_FLUSH_N,
                 flush_s=DEFAULT_FLUSH_S, post=None, now=None, token=None,
                 events_enabled=True):
        raw = base_url if base_url is not None else os.environ.get(SERVER_URL_ENV, "")
        self.base_url = str(raw).strip().rstrip("/")
        self.enabled = bool(self.base_url)
        # R2-12: when the OutboxReplayer owns event delivery (JSONL-as-outbox,
        # ONE write path), this sink stays alive for post_cycle() only —
        # emit()/flush() become no-ops so events are never double-shipped live.
        self.events_enabled = bool(events_enabled)
        # X-Lane-Token on every POST when the deployment is token-armed
        # (LANE_NODE_TOKEN — same env as lane_node.py / the wsl_api bridge).
        tok = token if token is not None else os.environ.get(TOKEN_ENV, "")
        self.token = str(tok).strip()
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self.flush_n = max(1, int(flush_n))
        self.flush_s = float(flush_s)
        self._post = post or self._urllib_post
        self._now = now or time.monotonic
        self._buf = []
        self._last_flush = self._now()
        self.posted = 0        # events successfully POSTed
        self.dropped = 0       # events/cycle rows dropped after retries
        self.post_errors = 0   # individual failed POST attempts

    def emit(self, row):
        if not self.enabled or not self.events_enabled:
            return
        try:
            self._buf.append(row)
            if len(self._buf) >= self.flush_n:
                self.flush()
        except Exception:
            self.post_errors += 1

    def maybe_flush(self):
        try:
            if self._buf and (self._now() - self._last_flush) >= self.flush_s:
                self.flush()
        except Exception:
            self.post_errors += 1

    def flush(self):
        rows, self._buf = self._buf, []
        self._last_flush = self._now()
        if not rows or not self.enabled:
            return
        if self._post_with_retry(self.base_url + self.EVENTS_PATH, {"events": rows}):
            self.posted += len(rows)
        else:
            self.dropped += len(rows)
            log.debug("HttpSink: dropped a batch of %d events after %d attempts",
                      len(rows), self.retries)

    def post_cycle(self, row):
        """POST one machine_cycles row. Returns True on success. Never raises."""
        if not self.enabled:
            return False
        try:
            # NOTE (R2-12): delivery identity on cycle rows is stamped by the
            # PRODUCER (controller_daemon._ship_cycle), not here — post_cycle
            # must emit exactly the row it is given (the contract fixture
            # roundtrip pins that byte-level wire shape).
            payload = {"cycle": _json_safe(dict(row))}
        except Exception:
            self.post_errors += 1
            return False
        ok = self._post_with_retry(self.base_url + self.CYCLES_PATH, payload)
        if not ok:
            self.dropped += 1
        return ok

    def _post_with_retry(self, url, payload):
        for _ in range(self.retries):
            try:
                self._post(url, payload)
                return True
            except Exception:
                self.post_errors += 1
        return False

    def _urllib_post(self, url, payload):
        import urllib.request
        data = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Lane-Token"] = self.token
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            resp.read(1024)     # drain a little; body content is irrelevant
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 300:
                raise RuntimeError(f"HTTP {status} from {url}")


# ---- the JSONL-outbox replayer (R2-12) -----------------------------------------
class OutboxReplayer:
    """Ships diag JSONL rows to the :8766 machine-events ingest with
    cursor-ack semantics (Codex round-2 R2-12): the daily JSONL files ARE the
    outbox (ONE write path, no second Pi DB). A persisted cursor
    ({file, pos}, atomic JSON) advances ONLY after a 2xx POST — an HTTP
    outage, a crash between write and ship, or a dropped batch simply leaves
    the cursor behind and the next pass replays from it. The server's
    UNIQUE(source_id, boot_id, seq) INSERT-OR-IGNORE makes any replay overlap
    idempotent.

    Rules of the house: own daemon thread, bounded batches, never raises,
    env-killable (WSL_DIAG_OUTBOX=0 falls back to the legacy live HttpSink).
    Rows WITHOUT delivery identity (pre-upgrade lines in an existing file)
    are skipped — they were shipped by the legacy live leg and cannot be
    deduped server-side."""

    def __init__(self, dir_path, base_url, *, post=None, token=None,
                 poll_s=None, timeout=DEFAULT_HTTP_TIMEOUT_S,
                 cursor_path=None, on_quarantine=None, sink=None):
        self.dir = dir_path or DEFAULT_DIR
        self.base_url = str(base_url or "").strip().rstrip("/")
        tok = token if token is not None else os.environ.get(TOKEN_ENV, "")
        self.token = str(tok).strip()
        self.timeout = float(timeout)
        self.poll_s = float(poll_s if poll_s is not None
                            else _float_env(OUTBOX_POLL_ENV,
                                            DEFAULT_OUTBOX_POLL_S))
        self.cursor_path = cursor_path or os.path.join(self.dir,
                                                       CURSOR_FILENAME)
        self.quarantine_path = os.path.join(self.dir, QUARANTINE_FILENAME)
        self.quarantine_state_path = os.path.join(
            self.dir, QUARANTINE_STATE_FILENAME)
        self.quarantine_clear_audit_path = os.path.join(
            self.dir, QUARANTINE_CLEAR_AUDIT_FILENAME)
        # Quarantine growth bound (review fix): cap + rotate the file, and dedup
        # already-quarantined rows by delivery identity so a lost-ack replay
        # can't re-write/re-emit them.
        self._quar_max_bytes = _int_env(QUARANTINE_MAX_BYTES_ENV,
                                        DEFAULT_QUARANTINE_MAX_BYTES)
        self._quar_seen = deque()        # FIFO of (source_id, boot_id, seq)
        self._quar_seen_set = set()      # membership mirror of _quar_seen
        # R3-1c: notified (count, sample_lane, errors) when the server
        # per-record-rejects rows — the daemon turns this into an
        # 'outbox_quarantine' event. Optional so the replayer stays usable
        # standalone (tests).
        self._on_quarantine = on_quarantine
        self._post = post or self._urllib_post
        # DiagWriter supplies these links so heartbeat health includes the
        # persistence leg, not merely the HTTP tailer. They remain optional for
        # standalone use and focused tests.
        self._sink = sink
        if self._sink is not None:
            self._sink.protect_unacked = True
        self._writer = None
        self.shipped = 0        # rows POSTed + acked (cursor advanced past)
        self.skipped = 0        # rows without delivery identity (not replayable)
        self.quarantined = 0    # unresolved durable data-loss latch/count
        self.cycles_shipped = 0  # R3-3: durable machine_cycles rows shipped
        self.cycles_quarantined = 0
        self.corrupt_rows = 0
        self.post_errors = 0    # failed POST attempts (cursor NOT advanced)
        self.cursor_errors = 0
        self.cursor_resets = 0
        self.quarantine_errors = 0
        self.scan_errors = 0
        self.errors = 0         # swallowed internal errors
        self._loss_seq = 0
        self._cleared_through_loss_seq = 0
        self._restore_quarantine_state()
        self._stop_ev = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    # -- durable quarantine latch -----------------------------------------
    def _quarantine_artifact_records(self):
        """Yield parseable evidence from both bounded quarantine generations."""
        for path in (self.quarantine_path + ".1", self.quarantine_path):
            try:
                with open(path, encoding="utf-8") as source:
                    for line in source:
                        try:
                            rec = json.loads(
                                line, parse_constant=_reject_nonfinite)
                            if isinstance(rec, dict):
                                yield rec
                        except Exception:
                            # A corrupt evidence row is itself unresolved loss.
                            yield {"reason": "quarantine_evidence_corrupt"}
            except FileNotFoundError:
                continue
            except OSError:
                self.quarantine_errors += 1
                self.errors += 1

    def _persist_quarantine_state(self):
        """Atomically persist the unresolved loss count before cursor advance."""
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.quarantine_state_path + ".tmp"
            payload = {
                "version": 2,
                "unresolved_quarantined": int(self.quarantined),
                "unresolved_cycles_quarantined": int(
                    self.cycles_quarantined),
                "last_loss_seq": int(self._loss_seq),
                "cleared_through_loss_seq": int(
                    self._cleared_through_loss_seq),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(tmp, "w", encoding="utf-8") as state_file:
                json.dump(payload, state_file, separators=(",", ":"),
                          sort_keys=True, allow_nan=False)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(tmp, self.quarantine_state_path)
            _fsync_parent(self.quarantine_state_path)
            return True
        except Exception:
            self.quarantine_errors += 1
            self.errors += 1
            return False

    def _restore_quarantine_state(self):
        """Restore a loss latch and recent dedupe keys across daemon restarts."""
        records = list(self._quarantine_artifact_records())
        artifact_count = len(records)
        artifact_cycles = 0
        artifact_max_seq = 0
        for rec in records:
            row = rec.get("row") if isinstance(rec, dict) else None
            loss_seq = rec.get("loss_seq") if isinstance(rec, dict) else None
            if (isinstance(loss_seq, int) and not isinstance(loss_seq, bool)
                    and loss_seq > 0):
                artifact_max_seq = max(artifact_max_seq, loss_seq)
            if isinstance(row, dict):
                key = self._quar_key(row)
                if key is not None:
                    self._remember_quarantined(key)
                if row.get("_kind") == "cycle":
                    artifact_cycles += 1
        state = None
        try:
            with open(self.quarantine_state_path, encoding="utf-8") as source:
                candidate = json.load(
                    source, parse_constant=_reject_nonfinite)
            q = candidate.get("unresolved_quarantined")
            cq = candidate.get("unresolved_cycles_quarantined")
            last_seq = candidate.get("last_loss_seq")
            cleared = candidate.get("cleared_through_loss_seq")
            if (isinstance(candidate, dict) and candidate.get("version") == 2
                    and isinstance(q, int) and not isinstance(q, bool)
                    and q >= 0 and isinstance(cq, int)
                    and not isinstance(cq, bool) and 0 <= cq <= q
                    and isinstance(last_seq, int)
                    and not isinstance(last_seq, bool) and last_seq >= 0
                    and isinstance(cleared, int)
                    and not isinstance(cleared, bool)
                    and 0 <= cleared <= last_seq):
                state = (q, cq, last_seq, cleared)
        except FileNotFoundError:
            pass
        except Exception:
            self.quarantine_errors += 1
            self.errors += 1
        if state is None:
            self.quarantined = artifact_count
            self.cycles_quarantined = artifact_cycles
            self._loss_seq = artifact_max_seq or artifact_count
            if artifact_count:
                self._persist_quarantine_state()
        else:
            self.quarantined = state[0]
            self.cycles_quarantined = state[1]
            self._loss_seq = state[2]
            self._cleared_through_loss_seq = state[3]
            # Crash-window recovery: evidence is fsynced before the state
            # replace. Any artifact sequence newer than the state watermark is
            # unresolved even when a prior audited clear made the old count 0.
            for rec in records:
                seq = rec.get("loss_seq") if isinstance(rec, dict) else None
                if (isinstance(seq, int) and not isinstance(seq, bool)
                        and seq > self._loss_seq):
                    self.quarantined += 1
                    row = rec.get("row")
                    if isinstance(row, dict) and row.get("_kind") == "cycle":
                        self.cycles_quarantined += 1
                    self._loss_seq = max(self._loss_seq, seq)
            if self._loss_seq != state[2]:
                self._persist_quarantine_state()

    def _next_loss_seq(self):
        self._loss_seq += 1
        return self._loss_seq

    def clear_quarantine_latch(self, actor, reason):
        """Audited operator acknowledgement; evidence files are never deleted."""
        if (not isinstance(actor, str) or not actor.strip()
                or len(actor.strip()) > 128):
            raise ValueError("actor must be 1..128 characters")
        if (not isinstance(reason, str) or not reason.strip()
                or len(reason.strip()) > 500):
            raise ValueError("reason must be 1..500 characters")
        prior = (self.quarantined, self.cycles_quarantined)
        record = {
            "cleared_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor.strip(),
            "reason": reason.strip(),
            "quarantined": prior[0],
            "cycles_quarantined": prior[1],
            "cleared_through_loss_seq": self._loss_seq,
        }
        os.makedirs(self.dir, exist_ok=True)
        with open(self.quarantine_clear_audit_path, "a",
                  encoding="utf-8") as audit:
            audit.write(json.dumps(
                record, separators=(",", ":"), sort_keys=True,
                allow_nan=False) + "\n")
            audit.flush()
            os.fsync(audit.fileno())
        _fsync_parent(self.quarantine_clear_audit_path)
        self.quarantined = 0
        self.cycles_quarantined = 0
        self._cleared_through_loss_seq = self._loss_seq
        if not self._persist_quarantine_state():
            self.quarantined, self.cycles_quarantined = prior
            raise OSError("quarantine latch state could not be persisted")
        return record

    # -- cursor ------------------------------------------------------------
    def _load_cursor(self):
        try:
            with open(self.cursor_path, encoding="utf-8") as f:
                c = json.load(f)
            pos = c.get("pos") if isinstance(c, dict) else None
            if (isinstance(c, dict) and isinstance(c.get("file"), str)
                    and isinstance(pos, int) and not isinstance(pos, bool)):
                return {"file": c["file"], "pos": pos}
        except Exception:
            pass
        return None

    def _cursor_valid(self, cur, files):
        """True only for a current file, in-bounds byte offset, and JSONL
        record boundary."""
        try:
            if not isinstance(cur, dict) or cur.get("file") not in files:
                return False
            pos = cur.get("pos")
            if not isinstance(pos, int) or isinstance(pos, bool) or pos < 0:
                return False
            path = os.path.join(self.dir, cur["file"])
            size = os.path.getsize(path)
            if pos > size:
                return False
            if pos == 0:
                return True
            with open(path, "rb") as f:
                f.seek(pos - 1)
                return f.read(1) == b"\n"
        except Exception:
            return False

    def _save_cursor(self, cur):
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.cursor_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.cursor_path)
            _fsync_parent(self.cursor_path)
            return True
        except Exception:
            self.cursor_errors += 1
            self.errors += 1
            return False

    def _outbox_files(self):
        """Sorted diag-*.jsonl names (dates sort lexically).

        A genuinely absent directory is an empty outbox. Other enumeration
        failures propagate to the replay/health guards and are reported as
        errors instead of being misreported as a healthy empty queue.
        """
        try:
            return sorted(n for n in os.listdir(self.dir)
                          if n.startswith(JsonlSink.FILE_PREFIX)
                          and n.endswith(JsonlSink.FILE_SUFFIX))
        except FileNotFoundError:
            return []

    # -- one replay pass ---------------------------------------------------
    def replay_once(self):
        """Ship every unshipped record segment. Returns the number of rows
        acked this pass. Never raises. R3-3: recovery scans from the OLDEST
        file with unshipped records (see below), and cycle records ride the
        SAME durable file as events (routed to /api/machine/cycles)."""
        acked = 0
        try:
            files = self._outbox_files()
            if not files:
                return 0
            cur = self._load_cursor()
            had_cursor = os.path.exists(self.cursor_path)
            if not self._cursor_valid(cur, files):
                # R3-3 (Codex round-3): a missing/invalid cursor (first run, or
                # the cursor's file was pruned) recovers from the OLDEST file,
                # NOT the newest. The old code started at files[-1], which
                # STRANDED every older file's unsent records forever (Codex's
                # 2-file repro). Identity-less legacy lines are skipped and the
                # server dedupes replays, so re-scanning from the oldest loses
                # nothing and strands nothing.
                cur = {"file": files[0], "pos": 0}
                if had_cursor:
                    self.cursor_errors += 1
                    self.cursor_resets += 1
                    self._save_cursor(cur)
            while True:
                rows, kind, new_pos, eof, blocked = self._read_batch(
                    cur["file"], cur["pos"])
                if rows:
                    ok, delivered = self._ship(kind, rows)
                    if not ok:
                        self.post_errors += 1
                        return acked          # cursor stays; retry next pass
                    self.shipped += delivered
                    acked += len(rows)
                cur = {"file": cur["file"], "pos": new_pos}
                self._save_cursor(cur)
                if blocked:
                    # A crash just before UTC rollover can leave yesterday's
                    # final JSON object without a newline.  Waiting is correct
                    # for the actively-written current file, but waiting on an
                    # older file forever strands every newer file.  Ask the
                    # linked JsonlSink to prove (under its append lock) that
                    # this is no longer its active daily file and seal it.
                    # Standalone/uncoordinated replayers fail closed.
                    if self._seal_rollover_tail(cur["file"], files):
                        continue
                    return acked
                if not eof:
                    continue                  # more in this file (or a kind run)
                # at EOF: roll to the next file if one exists, else done
                idx = files.index(cur["file"])
                if idx + 1 < len(files):
                    cur = {"file": files[idx + 1], "pos": 0}
                    self._save_cursor(cur)
                    continue
                return acked
        except Exception:
            self.errors += 1
            log.debug("OutboxReplayer.replay_once swallowed", exc_info=True)
            return acked

    def _seal_rollover_tail(self, name, files):
        """Repair a blocking tail only on a non-newest file and only through
        the writer-linked sink's append/repair coordination."""
        try:
            if files.index(name) + 1 >= len(files):
                return False
            seal = getattr(self._sink, "seal_inactive_tail", None)
            return bool(seal(name)) if callable(seal) else False
        except Exception:
            self.errors += 1
            return False

    def _read_batch(self, name, pos):
        """Read up to OUTBOX_BATCH_MAX replayable rows of ONE kind ('event' or
        'cycle') from `name` starting at byte `pos`. Returns
        (rows, kind, new_pos, eof, blocked). A record of a different kind ends the run
        WITHOUT being consumed (new_pos points at it, eof False) so the next
        read picks it up. Partial trailing lines (a flush in progress) are left
        for the next pass. Corrupt complete and identity-less rows are durably
        quarantined before the cursor can cross their bytes."""
        rows = []
        kind = None
        path = os.path.join(self.dir, name)
        try:
            with open(path, "rb") as f:
                f.seek(pos)
                while len(rows) < OUTBOX_BATCH_MAX:
                    before = f.tell()
                    line = f.readline()
                    if not line:
                        return rows, kind, before, True, False
                    if not line.endswith(b"\n"):
                        return rows, kind, before, False, True
                    try:
                        row = json.loads(line.decode("utf-8"),
                                         parse_constant=_reject_nonfinite)
                    except Exception as exc:
                        if rows:
                            return rows, kind, before, False, False
                        if not self._quarantine_local(
                                name, before, line, "corrupt_json",
                                error=str(exc)):
                            return rows, kind, pos, False, True
                        self.corrupt_rows += 1
                        return rows, kind, f.tell(), False, False
                    if not (isinstance(row, dict) and row.get("source_id")
                            and row.get("boot_id")
                            and row.get("seq") is not None):
                        if rows:
                            return rows, kind, before, False, False
                        if not self._quarantine_local(
                                name, before, line,
                                "missing_delivery_identity", row=row):
                            return rows, kind, pos, False, True
                        self.skipped += 1
                        return rows, kind, f.tell(), False, False
                    rk = "cycle" if row.get("_kind") == "cycle" else "event"
                    if kind is None:
                        kind = rk
                    elif rk != kind:
                        # kind boundary: leave this line for the next read
                        return rows, kind, before, False, False
                    rows.append(row)
                return rows, kind, f.tell(), False, False
        except FileNotFoundError:
            return rows, kind, pos, True, False
        except Exception:
            self.errors += 1
            return rows, kind, pos, False, True

    def _ship(self, kind, rows):
        """Ship one homogeneous run. Events go as one batch to the events
        endpoint; cycles go one-at-a-time to the cycles endpoint (R3-3 durable
        cycle path). Returns (resolved, delivered_count); resolved is true only
        if every row was accepted/deduplicated or durably quarantined."""
        if kind == "cycle":
            delivered = 0
            for row in rows:
                ok, was_delivered = self._post_cycle(row)
                if not ok:
                    return False, delivered
                if was_delivered:
                    delivered += 1
            self.cycles_shipped += delivered
            return True, delivered
        return self._post_batch(rows)

    def _post_cycle(self, row):
        try:
            body = {k: v for k, v in row.items() if k != "_kind"}
            resp = self._post(self.base_url + HttpSink.CYCLES_PATH,
                              {"cycle": body})
            if not isinstance(resp, dict):
                return False, False
            status = resp.get("_http_status", 200)
            accepted = resp.get("accepted")
            duplicates = resp.get("duplicates")
            rejected = resp.get("rejected")
            if (not isinstance(status, int) or not 200 <= status < 300
                    or resp.get("ok") is not True
                    or not isinstance(accepted, int)
                    or isinstance(accepted, bool) or accepted < 0
                    or not isinstance(duplicates, int)
                    or isinstance(duplicates, bool) or duplicates < 0
                    or not isinstance(rejected, list)
                    or accepted + duplicates + len(rejected) != 1):
                return False, False
            if rejected:
                rec = rejected[0]
                if (not isinstance(rec, dict)
                        or rec.get("index") != 0
                        or not self._quarantine([row], rejected)):
                    return False, False
                return True, False
            if resp.get("id") is None:
                return False, False
            return True, True
        except Exception:
            return False, False

    def _post_batch(self, rows):
        try:
            resp = self._post(self.base_url + HttpSink.EVENTS_PATH,
                              {"events": rows})
            # HTTP 2xx alone is not an acknowledgement. Require a complete,
            # internally-consistent disposition for every row.
            if not isinstance(resp, dict) or resp.get("ok") is not True:
                return False, 0
            status = resp.get("_http_status", 200)
            if (not isinstance(status, int) or isinstance(status, bool)
                    or not 200 <= status < 300):
                return False, 0
            accepted = resp.get("accepted")
            inserted = resp.get("inserted")
            duplicates = resp.get("duplicates")
            rejected = resp.get("rejected")
            counts = (accepted, duplicates)
            if (any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                    for v in counts)
                    or not isinstance(rejected, list)):
                return False, 0
            if inserted is not None and (
                    not isinstance(inserted, int) or isinstance(inserted, bool)
                    or inserted != accepted):
                return False, 0
            reject_indices = []
            for rec in rejected:
                idx = rec.get("index") if isinstance(rec, dict) else None
                if (not isinstance(idx, int) or isinstance(idx, bool)
                        or idx < 0 or idx >= len(rows)):
                    return False, 0
                reject_indices.append(idx)
            if len(set(reject_indices)) != len(reject_indices):
                return False, 0
            if accepted + duplicates + len(rejected) != len(rows):
                return False, 0
            if rejected and not self._quarantine(rows, rejected):
                return False, 0
            return True, accepted + duplicates
        except Exception:
            return False, 0

    def _quar_key(self, row):
        """Delivery identity of a row, or None if it lacks one."""
        if not isinstance(row, dict):
            return None
        key = (row.get("source_id"), row.get("boot_id"), row.get("seq"))
        return key if None not in key else None

    def _remember_quarantined(self, key):
        """Record a quarantined identity in the bounded FIFO dedup set."""
        if key in self._quar_seen_set:
            return
        self._quar_seen.append(key)
        self._quar_seen_set.add(key)
        while len(self._quar_seen) > QUARANTINE_DEDUP_MAX:
            self._quar_seen_set.discard(self._quar_seen.popleft())

    def _rotate_quarantine_if_big(self):
        """Rotate the quarantine file to a single .1 once it exceeds the cap so
        total on-disk stays <= ~2x the cap (the file's 'outbox_' prefix is not
        covered by JsonlSink._prune). Best-effort; never raises."""
        try:
            if os.path.getsize(self.quarantine_path) > self._quar_max_bytes:
                os.replace(self.quarantine_path, self.quarantine_path + ".1")
                _fsync_parent(self.quarantine_path + ".1")
        except FileNotFoundError:
            pass
        except Exception:
            self.errors += 1

    def _quarantine_local(self, name, offset, raw, reason, *,
                          error=None, row=None):
        """Durably quarantine one locally unreadable/unreplayable complete
        JSONL row. The stable file/offset key prevents repeated writes while a
        cursor-save or later POST is retried in this process."""
        key = ("local", str(name), int(offset), str(reason))
        if key in self._quar_seen_set:
            return self._persist_quarantine_state()
        raw_text = None
        try:
            raw_text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        except Exception:
            raw_text = repr(raw)
        rec = {
            "loss_seq": self._next_loss_seq(),
            "error": str(error or reason)[:_MAX_STR],
            "reason": str(reason),
            "source_file": str(name),
            "byte_offset": int(offset),
            "raw": _json_safe(raw_text),
            "row": _json_safe(row) if row is not None else None,
        }
        try:
            os.makedirs(self.dir, exist_ok=True)
            line = json.dumps(rec, separators=(",", ":"), allow_nan=False)
            with open(self.quarantine_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            _fsync_parent(self.quarantine_path)
            self._remember_quarantined(key)
            self.quarantined += 1
            if isinstance(row, dict) and row.get("_kind") == "cycle":
                self.cycles_quarantined += 1
            if not self._persist_quarantine_state():
                return False
            self._rotate_quarantine_if_big()
            try:
                if self._on_quarantine is not None:
                    lane = row.get("lane_id") if isinstance(row, dict) else None
                    self._on_quarantine(1, lane, [str(reason)])
            except Exception:
                self.errors += 1
            return True
        except Exception:
            self.quarantine_errors += 1
            self.errors += 1
            return False

    def _quarantine(self, rows, rejected):
        """Append server-rejected rows to the quarantine file, count them, and
        notify the daemon (which emits the 'outbox_quarantine' event). Never
        raises. Returns True only when every new quarantine record was written;
        a write failure leaves the outbox cursor in place for retry.

        Bounded (review fix): rows already quarantined on a prior (lost-ack)
        replay are skipped by delivery identity so the file and the
        'outbox_quarantine' event stream can't grow without bound on a repeated
        segment; the file itself is capped + rotated after each write."""
        sample_lane = None
        written = 0
        errors = []
        success = True
        try:
            recs = []
            for r in rejected:
                if not isinstance(r, dict):
                    continue
                idx = r.get("index")
                row = rows[idx] if isinstance(idx, int) and 0 <= idx < len(rows) \
                    else None
                key = self._quar_key(row)
                if key is not None and key in self._quar_seen_set:
                    continue    # already quarantined on a prior replay
                if sample_lane is None and isinstance(row, dict):
                    lid = row.get("lane_id")
                    if isinstance(lid, int):
                        sample_lane = lid
                recs.append((key, {
                    "loss_seq": self._next_loss_seq(),
                    "error": r.get("error"), "row": row},
                             r.get("error")))
            if recs:
                os.makedirs(self.dir, exist_ok=True)
                with open(self.quarantine_path, "a", encoding="utf-8") as f:
                    for key, rec, rec_error in recs:
                        f.write(json.dumps(_json_safe(rec), separators=(",", ":"),
                                           allow_nan=False) + "\n")
                    # The cursor may advance only after the quarantine evidence
                    # is stable. Remember/count records after this barrier, not
                    # while they are still buffered.
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_parent(self.quarantine_path)
                for key, rec, rec_error in recs:
                    if key is not None:
                        self._remember_quarantined(key)
                    self.quarantined += 1
                    row = rec.get("row") if isinstance(rec, dict) else None
                    if isinstance(row, dict) and row.get("_kind") == "cycle":
                        self.cycles_quarantined += 1
                    written += 1
                    errors.append(rec_error)
                if not self._persist_quarantine_state():
                    success = False
                self._rotate_quarantine_if_big()
            elif rejected:
                # A retry may find every delivery identity in the evidence
                # dedupe set after an earlier state-write failure. Do not let
                # the cursor cross until the durable latch is now persisted.
                success = self._persist_quarantine_state()
        except Exception:
            self.quarantine_errors += 1
            self.errors += 1
            success = False
        # Notify OUTSIDE the file write so a callback bug can't lose the count —
        # but only for rows NEWLY quarantined this pass (a re-replayed segment
        # whose rows were all already quarantined emits nothing).
        try:
            if self._on_quarantine is not None and written:
                self._on_quarantine(written, sample_lane, errors)
        except Exception:
            self.errors += 1
        return success

    def _urllib_post(self, url, payload):
        import urllib.error
        import urllib.request
        data = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Lane-Token"] = self.token
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read(65536)
                status = int(getattr(resp, "status", 200) or 200)
        except urllib.error.HTTPError as exc:
            # Preserve the status/body for strict acknowledgement validation.
            # Non-2xx responses fail closed in the caller and retain the cursor.
            status = int(exc.code)
            body = exc.read(65536)
        try:
            parsed = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed["_http_status"] = status
        return parsed

    def health(self):
        """R3-3 outbox health telemetry: oldest-unsent age, backlog depth,
        cursor health, quarantined count. Best-effort; never raises. Feeds the
        controller heartbeat (R3-2) and can be event-emitted on threshold."""
        base = {
            "oldest_unsent_age_s": None,
            "backlog": 0,
            "backlog_bytes": 0,
            "cursor_ok": False,
            "quarantined": self.quarantined,
            "corrupt_rows": self.corrupt_rows,
            "skipped": self.skipped,
            "shipped": self.shipped,
            "cycles_shipped": self.cycles_shipped,
            "cycles_quarantined": self.cycles_quarantined,
            "post_errors": self.post_errors,
            "cursor_errors": self.cursor_errors,
            "cursor_resets": self.cursor_resets,
            "quarantine_errors": self.quarantine_errors,
            "scan_errors": self.scan_errors,
            "errors": self.errors,
            "write_errors": int(getattr(self._sink, "write_errors", 0) or 0),
            "sink_errors": int(getattr(self._writer, "sink_errors", 0) or 0),
            "dropped": (int(getattr(self._sink, "dropped", 0) or 0)
                        + int(getattr(
                            getattr(self._writer, "queue", None),
                            "drops", 0) or 0)),
            "pending_writes": int(
                getattr(self._sink, "pending_writes", 0) or 0),
            "prune_deferred": int(
                getattr(self._sink, "prune_deferred", 0) or 0),
            "repaired_tails": int(
                getattr(self._sink, "repaired_tails", 0) or 0),
            "error": False,
        }
        try:
            files = self._outbox_files()
            cur = self._load_cursor()
            cursor_exists = os.path.exists(self.cursor_path)
            cursor_ok = (not files and not cursor_exists) \
                or self._cursor_valid(cur, files)
            backlog_bytes = 0
            backlog = 0
            oldest_age = None
            timestamp_error = False
            scan_error = False
            if files:
                start_idx, start_pos = 0, 0
                if cursor_ok and cur and cur.get("file") in files:
                    start_idx = files.index(cur["file"])
                    start_pos = int(cur.get("pos", 0) or 0)
                for i in range(start_idx, len(files)):
                    path = os.path.join(self.dir, files[i])
                    try:
                        size = os.path.getsize(path)
                        offset = start_pos if i == start_idx else 0
                        remaining = max(0, size - offset)
                        if remaining > 0:
                            backlog_bytes += remaining
                            with open(path, "rb") as f:
                                f.seek(offset)
                                if oldest_age is None and not timestamp_error:
                                    first = f.readline()
                                    if first.endswith(b"\n"):
                                        try:
                                            row = json.loads(
                                                first.decode("utf-8"),
                                                parse_constant=_reject_nonfinite)
                                            oldest_age = _outbox_row_age_s(
                                                row, time.time())
                                        except Exception:
                                            # A complete unacked row whose
                                            # immutable age cannot be proven is
                                            # a health fault, not "young".
                                            timestamp_error = True
                                    else:
                                        # A partial active append is transient.
                                        # The sink seals it before any later
                                        # append can refresh this mtime.
                                        oldest_age = max(
                                            0.0,
                                            time.time()
                                            - os.path.getmtime(path))
                                    f.seek(offset)
                                while True:
                                    chunk = f.read(65536)
                                    if not chunk:
                                        break
                                    backlog += chunk.count(b"\n")
                    except OSError:
                        self.scan_errors += 1
                        scan_error = True
                        break
            if timestamp_error or scan_error:
                cursor_ok = False
                base["error"] = True
            base.update({
                "oldest_unsent_age_s": (round(oldest_age, 1)
                                        if oldest_age is not None else None),
                "backlog": backlog,
                "backlog_bytes": backlog_bytes,
                "cursor_ok": bool(cursor_ok),
                "scan_errors": self.scan_errors,
            })
            return base
        except Exception:
            self.scan_errors += 1
            base["cursor_ok"] = False
            base["scan_errors"] = self.scan_errors
            base["error"] = True
            return base

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_ev.clear()
        self._thread = threading.Thread(target=self._run,
                                        name="diag-outbox", daemon=True)
        self._thread.start()
        return True

    def kick(self):
        """Wake the replay thread early (e.g. right after a flush)."""
        self._wake.set()

    def stop(self, timeout=5.0):
        try:
            self._stop_ev.set()
            self._wake.set()
            t = self._thread
            if t is not None and t.is_alive():
                t.join(timeout)
            # final best-effort pass so a clean shutdown ships the tail
            self.replay_once()
        except Exception:
            self.errors += 1

    def _run(self):
        while not self._stop_ev.is_set():
            self.replay_once()
            self._wake.wait(self.poll_s)
            self._wake.clear()

    def stats(self):
        return {
            "shipped": self.shipped,
            "skipped": self.skipped,
            "quarantined": self.quarantined,
            "corrupt_rows": self.corrupt_rows,
            "cycles_shipped": self.cycles_shipped,
            "cycles_quarantined": self.cycles_quarantined,
            "post_errors": self.post_errors,
            "cursor_errors": self.cursor_errors,
            "cursor_resets": self.cursor_resets,
            "quarantine_errors": self.quarantine_errors,
            "scan_errors": self.scan_errors,
            "write_errors": int(getattr(self._sink, "write_errors", 0) or 0),
            "dropped": (int(getattr(self._sink, "dropped", 0) or 0)
                        + int(getattr(
                            getattr(self._writer, "queue", None),
                            "drops", 0) or 0)),
            "pending_writes": int(
                getattr(self._sink, "pending_writes", 0) or 0),
            "prune_deferred": int(
                getattr(self._sink, "prune_deferred", 0) or 0),
            "repaired_tails": int(
                getattr(self._sink, "repaired_tails", 0) or 0),
            "errors": self.errors,
        }


class _DisabledOutboxStatus:
    """Health-only sentinel for a kill-switched diagnostics stack.

    This is deliberately not an OutboxReplayer and owns no sink, file, thread,
    URL, or delivery method.  PlatformHealth already reads ``writer.outbox``
    for the heartbeat, so keeping an explicit unavailable status here prevents
    a disabled writer from advertising an apparently green default outbox.
    """

    _STATUS = {
        "enabled": False,
        "diagnostics_disabled": True,
        "health_unavailable": True,
        "oldest_unsent_age_s": None,
        "backlog": 0,
        "backlog_bytes": 0,
        "cursor_ok": False,
        "quarantined": 0,
        "corrupt_rows": 0,
        "skipped": 0,
        "shipped": 0,
        "cycles_shipped": 0,
        "cycles_quarantined": 0,
        "post_errors": 0,
        "cursor_errors": 0,
        "cursor_resets": 0,
        "quarantine_errors": 0,
        "scan_errors": 0,
        "errors": 0,
        "write_errors": 0,
        "sink_errors": 0,
        "dropped": 0,
        "pending_writes": 0,
        "prune_deferred": 0,
        "repaired_tails": 0,
        "error": True,
    }

    def health(self):
        return dict(self._STATUS)

    def stats(self):
        return dict(self._STATUS)


# ---- the writer thread ---------------------------------------------------------
class DiagWriter:
    """Single daemon background thread draining the DiagQueue into every sink.

    Kill-switch: WSL_DIAG_ENABLED (default ON — pure local logging is safe-on;
    the HTTP leg additionally requires WSL_DIAG_SERVER_URL to be set). Disabled
    -> emit()/start()/stop() are cheap no-ops.

    start()/stop() give a clean shutdown: stop() signals the thread, which
    drains whatever is still queued (bounded by the queue cap) and flushes all
    sinks before exiting. Sink exceptions are swallowed + counted; nothing here
    can raise into a caller."""

    def __init__(self, *, queue=None, sinks=None, enabled=None, poll_s=0.25):
        self.enabled = _enabled_from_env() if enabled is None else bool(enabled)
        self.queue = queue or DiagQueue()
        self.outbox = None      # OutboxReplayer, disabled health sentinel, or None
        if not self.enabled:
            # Fail closed before constructing any persistence/network leg.
            # The health-only sentinel is consumed by PlatformHealth's
            # heartbeat and can never be mistaken for an active outbox.
            sinks = []
            self.outbox = _DisabledOutboxStatus()
        elif sinks is None:
            jsonl = JsonlSink()
            sinks = [jsonl]
            url = os.environ.get(SERVER_URL_ENV, "").strip()
            if url:
                if _env_on_default(OUTBOX_ENV, "1"):
                    # R2-12: JSONL-as-outbox is the ONE event write path — the
                    # HttpSink stays for post_cycle only (events_enabled=False)
                    # and the replayer tails the JSONL with a persisted,
                    # ack-advanced cursor (idempotent server inserts make
                    # replay overlap safe).
                    sinks.append(HttpSink(url, events_enabled=False))
                    self.outbox = OutboxReplayer(jsonl.dir, url, sink=jsonl)
                else:
                    sinks.append(HttpSink(url))
        self.sinks = list(sinks)
        self.poll_s = float(poll_s)
        self.sink_errors = 0
        if self.outbox_active():
            self.outbox._writer = self
        self._stop = threading.Event()
        self._thread = None
        if self.enabled:
            log.info("DiagWriter: enabled (queue_max=%d, sinks=%s, outbox=%s)",
                     self.queue.maxsize,
                     [type(s).__name__ for s in self.sinks],
                     bool(self.outbox))

    # -- producer side (never blocks, never raises) --------------------------
    def emit(self, event):
        """Queue one DiagEvent (or pre-built dict). Returns True if queued."""
        if not self.enabled:
            return False
        return self.queue.emit(event)

    def outbox_active(self):
        """True when the JSONL-as-outbox HTTP leg owns delivery (R3-3 durable
        path). The daemon uses this to decide whether cycles ride the durable
        outbox (emit_cycle) or the legacy live CycleShipper->post_cycle."""
        return self.enabled and isinstance(self.outbox, OutboxReplayer)

    def emit_cycle(self, row):
        """R3-3: durable machine_cycles delivery. In outbox mode the cycle row
        is tagged '_kind: cycle' and queued onto the SAME single write path as
        events — it lands in the daily JSONL file and the OutboxReplayer ships
        it to /api/machine/cycles with the same delivery-identity idempotency
        and crash/outage replay. Returns True if queued. Never raises. (When
        the outbox is NOT active this returns False so the caller keeps the
        legacy direct-POST CycleShipper path — a lone live sink has no durable
        file to replay from.)"""
        if not self.outbox_active():
            return False
        try:
            r = dict(row)
            r["_kind"] = "cycle"
            return self.queue.emit(r)
        except Exception:
            return False

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        """Start the writer thread. Idempotent. Returns True if running."""
        if not self.enabled:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="diag-writer",
                                        daemon=True)
        self._thread.start()
        if self.outbox is not None:
            self.outbox.start()
        return True

    def stop(self, timeout=5.0):
        """Signal the thread, wait for it to drain + flush. If the thread was
        never started (or already dead), drain + flush synchronously so queued
        events are never silently lost. Never raises."""
        if not self.enabled:
            return
        try:
            self._stop.set()
            t = self._thread
            if t is not None and t.is_alive():
                t.join(timeout)
            if t is None or not t.is_alive():
                # thread finished (its finally flushed) OR never ran: make sure
                # anything still queued reaches the sinks.
                self._drain_and_flush()
            if self.outbox is not None:
                self.outbox.stop(timeout)   # ship the flushed tail (cursor-ack)
        except Exception:
            log.debug("DiagWriter.stop swallowed", exc_info=True)

    # -- internals -------------------------------------------------------------
    def _dispatch(self, event):
        try:
            row = event.to_dict() if hasattr(event, "to_dict") else dict(event)
            # R2-12 delivery identity: every record that reaches ANY sink (the
            # JSONL outbox included) carries (source_id, boot_id, seq), so the
            # server can dedupe replays after drops.
            stamp_delivery(row)
            row = _json_safe(row)
        except Exception:
            self.sink_errors += 1
            return
        for s in self.sinks:
            try:
                s.emit(row)
            except Exception:
                self.sink_errors += 1
                log.debug("DiagWriter: sink %s emit swallowed",
                          type(s).__name__, exc_info=True)

    def _maybe_flush_all(self):
        for s in self.sinks:
            try:
                s.maybe_flush()
            except Exception:
                self.sink_errors += 1

    def _drain_and_flush(self):
        # bounded drain: at most one full queue's worth (+ slack for races)
        for _ in range(self.queue.maxsize + 8):
            ev = self.queue.get(timeout=0)
            if ev is None:
                break
            self._dispatch(ev)
        for s in self.sinks:
            try:
                s.flush()
            except Exception:
                self.sink_errors += 1

    def _run(self):
        try:
            while True:
                ev = self.queue.get(timeout=self.poll_s)
                if ev is not None:
                    self._dispatch(ev)
                self._maybe_flush_all()
                if self._stop.is_set() and self.queue.empty():
                    break
        except Exception:
            log.warning("DiagWriter thread swallowed an exception", exc_info=True)
        finally:
            self._drain_and_flush()

    def stats(self):
        """Diagnostic counters (drops are the honesty metric — scope 'catch-all
        + drop counter' rule)."""
        d = {
            "enabled": self.enabled,
            "queue_drops": self.queue.drops,
            "queue_size": self.queue.qsize(),
            "sink_errors": self.sink_errors,
            "sinks": {},
        }
        if not self.enabled:
            d.update({
                "diagnostics_disabled": True,
                "health_unavailable": True,
            })
        for s in self.sinks:
            name = type(s).__name__
            d["sinks"][name] = {
                k: getattr(s, k) for k in
                ("written", "write_errors", "retry_batches", "pending_writes",
                 "prune_deferred", "repaired_tails", "posted", "dropped",
                 "post_errors")
                if hasattr(s, k)
            }
        if self.outbox is not None:
            d["outbox"] = self.outbox.stats()
        return d


if __name__ == "__main__":
    # Tiny smoke (real coverage: tests/test_diag_events.py)
    import sys
    import tempfile

    d = tempfile.mkdtemp(prefix="diag_smoke_")
    sink = JsonlSink(d, flush_n=2)
    w = DiagWriter(queue=DiagQueue(maxsize=16), sinks=[sink], enabled=True)
    w.start()
    w.emit(make_event(21, "info", "recovered", code="s:1"))
    w.emit(make_event(21, "warn", "recovered", detail={"k": 1}))
    w.stop()
    files = [n for n in os.listdir(d) if n.endswith(".jsonl")]
    assert files, "no jsonl written"
    with open(os.path.join(d, files[0]), encoding="utf-8") as f:
        rows = [json.loads(ln) for ln in f.read().splitlines() if ln]
    assert len(rows) == 2 and rows[0]["severity"] == "info", rows
    try:
        make_event(21, "catastrophic", "recovered")
    except ValueError:
        pass
    else:
        raise AssertionError("bad severity must raise at construction")
    print("diag_events smoke OK ->", os.path.join(d, files[0]))
    sys.exit(0)
