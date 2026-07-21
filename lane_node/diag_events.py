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
import threading
import time
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
                 flush_s=DEFAULT_FLUSH_S, post=None, now=None, token=None):
        raw = base_url if base_url is not None else os.environ.get(SERVER_URL_ENV, "")
        self.base_url = str(raw).strip().rstrip("/")
        self.enabled = bool(self.base_url)
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
        if not self.enabled:
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
        if sinks is None:
            sinks = [JsonlSink()]
            url = os.environ.get(SERVER_URL_ENV, "").strip()
            if url:
                sinks.append(HttpSink(url))
        self.sinks = list(sinks)
        self.poll_s = float(poll_s)
        self.sink_errors = 0
        self._stop = threading.Event()
        self._thread = None
        if self.enabled:
            log.info("DiagWriter: enabled (queue_max=%d, sinks=%s)",
                     self.queue.maxsize,
                     [type(s).__name__ for s in self.sinks])

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
        except Exception:
            log.debug("DiagWriter.stop swallowed", exc_info=True)

    # -- internals -------------------------------------------------------------
    def _dispatch(self, event):
        try:
            row = event.to_dict() if hasattr(event, "to_dict") else dict(event)
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
