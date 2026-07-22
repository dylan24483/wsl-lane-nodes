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
import os
import queue
import socket
import threading
import time
import uuid
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

DEFAULT_QUEUE_MAX = 1000
DEFAULT_DIR = "./diag_logs"
DEFAULT_MAX_FILES = 30
# Batched-write cadence (SD-wear rule, scope §6 "batched local writes"): flush a
# sink buffer when it holds this many events OR this many seconds have passed.
DEFAULT_FLUSH_N = 20
DEFAULT_FLUSH_S = 5.0
DEFAULT_HTTP_TIMEOUT_S = 2.0
DEFAULT_HTTP_RETRIES = 2

# The ONLY closed vocabulary in this domain (mirrors the machine_events CHECK —
# scope §2 schema: severity is the one CHECK enum; event_type is writer-validated
# and deliberately open so the taxonomy can grow without a table rebuild).
SEVERITIES = ("info", "warn", "fault")

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
    if v is None or isinstance(v, bool) or isinstance(v, (int, float)):
        return v
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
    """

    __slots__ = ("ts_utc", "ts_mono", "lane_id", "severity", "event_type",
                 "code", "detail")

    def __init__(self, ts_utc, ts_mono, lane_id, severity, event_type,
                 code=None, detail=None):
        if severity not in SEVERITIES:
            raise ValueError(f"severity {severity!r} not in {SEVERITIES}")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError(f"event_type must be a non-empty string, got {event_type!r}")
        if detail is not None and not isinstance(detail, dict):
            raise ValueError(f"detail must be a dict or None, got {type(detail).__name__}")
        self.ts_utc = str(ts_utc)
        self.ts_mono = float(ts_mono)
        self.lane_id = int(lane_id)
        self.severity = severity
        self.event_type = event_type.strip()[:80]
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
    count failures in `write_errors`; rows in a failed batch are dropped, never
    retried into an unbounded backlog."""

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
        self._buf = []
        self._last_flush = self._now()
        self._last_day = None
        self.write_errors = 0
        self.written = 0

    def emit(self, row):
        """Buffer one JSON-safe dict; flush when the batch is full. Never raises."""
        try:
            self._buf.append(row)
            if len(self._buf) >= self.flush_n:
                self.flush()
        except Exception:
            self.write_errors += 1
            log.debug("JsonlSink.emit swallowed", exc_info=True)

    def maybe_flush(self):
        """Time-based flush check (called each writer loop). Never raises."""
        try:
            if self._buf and (self._now() - self._last_flush) >= self.flush_s:
                self.flush()
        except Exception:
            self.write_errors += 1

    def flush(self):
        """Write the whole buffer in ONE append-open (SD-wear rule). Never raises."""
        rows, self._buf = self._buf, []
        self._last_flush = self._now()
        if not rows:
            return
        try:
            day = self._today()
            os.makedirs(self.dir, exist_ok=True)
            path = os.path.join(self.dir, f"{self.FILE_PREFIX}{day}{self.FILE_SUFFIX}")
            lines = []
            for r in rows:
                try:
                    lines.append(json.dumps(r, separators=(",", ":")))
                except Exception:
                    lines.append(json.dumps({"unserializable": str(type(r).__name__)}))
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self.written += len(rows)
            if day != self._last_day:          # new file appeared -> prune old ones
                self._last_day = day
                self._prune()
        except Exception:
            self.write_errors += 1
            log.debug("JsonlSink.flush dropped %d rows", len(rows), exc_info=True)

    def _prune(self):
        """Keep at most max_files diag-*.jsonl (dates sort lexically). Best-effort."""
        try:
            names = sorted(n for n in os.listdir(self.dir)
                           if n.startswith(self.FILE_PREFIX) and n.endswith(self.FILE_SUFFIX))
            for old in names[:-self.max_files]:
                try:
                    os.remove(os.path.join(self.dir, old))
                except Exception:
                    pass
        except Exception:
            pass


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
        data = json.dumps(payload).encode("utf-8")
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
                 cursor_path=None):
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
        self._post = post or self._urllib_post
        self.shipped = 0        # rows POSTed + acked (cursor advanced past)
        self.skipped = 0        # rows without delivery identity (not replayable)
        self.post_errors = 0    # failed POST attempts (cursor NOT advanced)
        self.errors = 0         # swallowed internal errors
        self._stop_ev = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    # -- cursor ------------------------------------------------------------
    def _load_cursor(self):
        try:
            with open(self.cursor_path, encoding="utf-8") as f:
                c = json.load(f)
            if isinstance(c, dict) and isinstance(c.get("file"), str):
                return {"file": c["file"], "pos": int(c.get("pos", 0))}
        except Exception:
            pass
        return None

    def _save_cursor(self, cur):
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.cursor_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, self.cursor_path)
        except Exception:
            self.errors += 1

    def _outbox_files(self):
        """Sorted diag-*.jsonl names (dates sort lexically). Never raises."""
        try:
            return sorted(n for n in os.listdir(self.dir)
                          if n.startswith(JsonlSink.FILE_PREFIX)
                          and n.endswith(JsonlSink.FILE_SUFFIX))
        except Exception:
            return []

    # -- one replay pass ---------------------------------------------------
    def replay_once(self):
        """Ship at most one batch segment per file position. Returns the
        number of rows acked this pass. Never raises."""
        acked = 0
        try:
            files = self._outbox_files()
            if not files:
                return 0
            cur = self._load_cursor()
            if cur is None or cur["file"] not in files:
                # First run (or the cursor's file was pruned): start at the
                # NEWEST file from its current position 0 — identity-less
                # legacy lines inside are skipped, so nothing double-ships.
                cur = {"file": files[-1], "pos": 0}
            while True:
                rows, new_pos, eof = self._read_batch(cur["file"], cur["pos"])
                if rows:
                    if not self._post_batch(rows):
                        self.post_errors += 1
                        return acked          # cursor stays; retry next pass
                    self.shipped += len(rows)
                    acked += len(rows)
                cur = {"file": cur["file"], "pos": new_pos}
                self._save_cursor(cur)
                if not eof:
                    continue                  # more in this file
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

    def _read_batch(self, name, pos):
        """Read up to OUTBOX_BATCH_MAX replayable rows from `name` starting at
        byte `pos`. Returns (rows, new_pos, eof). Partial trailing lines (a
        flush in progress) are left for the next pass."""
        rows = []
        path = os.path.join(self.dir, name)
        try:
            with open(path, "rb") as f:
                f.seek(pos)
                while len(rows) < OUTBOX_BATCH_MAX:
                    line = f.readline()
                    if not line:
                        return rows, pos, True
                    if not line.endswith(b"\n"):
                        return rows, pos, True      # partial write — wait
                    pos = f.tell()
                    try:
                        row = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue                    # corrupt line: skip
                    if (isinstance(row, dict) and row.get("source_id")
                            and row.get("boot_id")
                            and row.get("seq") is not None):
                        rows.append(row)
                    else:
                        self.skipped += 1
                return rows, pos, False
        except FileNotFoundError:
            return rows, pos, True
        except Exception:
            self.errors += 1
            return rows, pos, True

    def _post_batch(self, rows):
        try:
            self._post(self.base_url + HttpSink.EVENTS_PATH, {"events": rows})
            return True
        except Exception:
            return False

    def _urllib_post(self, url, payload):
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Lane-Token"] = self.token
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            resp.read(1024)
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 300:
                raise RuntimeError(f"HTTP {status} from {url}")

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
        return {"shipped": self.shipped, "skipped": self.skipped,
                "post_errors": self.post_errors, "errors": self.errors}


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
        self.outbox = None      # OutboxReplayer when the outbox HTTP leg is on
        if sinks is None:
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
                    self.outbox = OutboxReplayer(jsonl.dir, url)
                else:
                    sinks.append(HttpSink(url))
        self.sinks = list(sinks)
        self.poll_s = float(poll_s)
        self.sink_errors = 0
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
        for s in self.sinks:
            name = type(s).__name__
            d["sinks"][name] = {
                k: getattr(s, k) for k in
                ("written", "write_errors", "posted", "dropped", "post_errors")
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
    w.emit(make_event(21, "info", "smoke", code="s:1"))
    w.emit(make_event(21, "warn", "smoke", detail={"k": 1}))
    w.stop()
    files = [n for n in os.listdir(d) if n.endswith(".jsonl")]
    assert files, "no jsonl written"
    with open(os.path.join(d, files[0]), encoding="utf-8") as f:
        rows = [json.loads(ln) for ln in f.read().splitlines() if ln]
    assert len(rows) == 2 and rows[0]["severity"] == "info", rows
    try:
        make_event(21, "catastrophic", "smoke")
    except ValueError:
        pass
    else:
        raise AssertionError("bad severity must raise at construction")
    print("diag_events smoke OK ->", os.path.join(d, files[0]))
    sys.exit(0)
