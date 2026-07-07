#!/usr/bin/env python3
"""
flight_recorder.py — black-box I/O ring buffer for the Phase 8b controller (idea #10).

WHAT IT IS
  A fixed-size, O(1)-append ring buffer of (t_mono, kind, name, value) tuples that
  taps the TWO I/O chokepoints the daemon already has — MachineIO/RecordingIO
  (controller_io.py) and the daemon's own state/fault/watchdog stream — so that on a
  FAULT, safety-trip, or unhandled exception the last ~N events can be flushed to a
  timestamped JSON file. That file is the artifact a mechanic / remote analyst reads
  ('the table ran 8.0s and never hit TA1 — check the TA cam, not the board') instead
  of guessing from journald.

OBSERVE-ONLY + BOUNDED + FAIL-SAFE (the three rules for this file)
  * OBSERVE-ONLY: this module drives NO relay and changes NO control behavior. It
    only appends to a deque and (on a trigger) writes a file. Wiring it into
    MachineIO._set_out / the daemon happens at the call sites; the recorder itself
    is inert.
  * BOUNDED: the ring is a collections.deque(maxlen=cap) — append is O(1) and memory
    is hard-capped at `cap` entries regardless of cycle count or soak duration. The
    dump is also bounded (it serializes at most `cap` rows).
  * FAIL-SAFE: every public method is wrapped so a recorder bug (full disk, bad
    value, encoding error) can NEVER raise into the control loop. record() and
    dump() swallow their own exceptions and degrade to a no-op. A disabled recorder
    (env kill-switch, see DISABLE_ENV) is a cheap no-op on every call.

DEFAULT ON. Set the env var named by DISABLE_ENV (default `WSL_FLIGHT_RECORDER=0`)
to disable. Disabled = record() / dump() become no-ops; nothing is allocated past
construction.

Thread-safety: deque.append / a bounded snapshot under a Lock are both cheap; the
serial reader thread (rp2040_link) and the control thread can both record without
corrupting the ring. The Lock is only ever held for an O(1) append or an O(cap)
snapshot copy — never across file I/O.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger("flight_recorder")

# Env kill-switch. Default ON; set this to "0"/"false"/"no"/"off" to disable.
DISABLE_ENV = "WSL_FLIGHT_RECORDER"

# Ring capacity. ~2000 events covers many cycles of dense cam/relay traffic while
# staying a small, bounded allocation (a few hundred KB serialized worst-case).
DEFAULT_CAPACITY = 2000

# Hard cap on how many dump files we leave on disk per recorder, so a fault storm
# during a bad soak night cannot fill the partition. Oldest are pruned first.
DEFAULT_MAX_DUMPS = 50

_FALSEY = ("0", "false", "no", "off", "")


def _enabled_from_env():
    """True unless the kill-switch env var is explicitly falsey."""
    return os.environ.get(DISABLE_ENV, "1").strip().lower() not in _FALSEY


class FlightRecorder:
    """Fixed-size ring buffer + dump-on-trigger. One per lane/board.

    Args:
      lane:      lane id (stamped into every dump filename + payload).
      capacity:  ring size (entries). Bounded; default DEFAULT_CAPACITY.
      dump_dir:  directory for dump files. Created lazily on first dump. When
                 omitted, the default (/var/log/lane-node on the Pi) may FALL
                 BACK at dump time to a per-user writable dir (~/.local/state/
                 lane-node, then <tmp>/lane-node) with a loud one-time warning —
                 the default dir is root-owned on a stock Pi while the daemon
                 runs as User=pi, and silently dropping every black-box dump
                 defeats the recorder's purpose. An EXPLICIT dump_dir is honored
                 strictly (unwritable -> dump dropped with an error log).
      enabled:   None -> read the env kill-switch (default ON); True/False forces.
      now:       monotonic clock (injectable for tests).
      max_dumps: retain at most this many dump files (oldest pruned). Bounded disk.
    """

    def __init__(self, lane, *, capacity=DEFAULT_CAPACITY, dump_dir=None,
                 enabled=None, now=None, max_dumps=DEFAULT_MAX_DUMPS):
        self.lane = lane
        self.capacity = int(capacity) if capacity and int(capacity) > 0 else DEFAULT_CAPACITY
        self.enabled = _enabled_from_env() if enabled is None else bool(enabled)
        self._now = now or time.monotonic
        self.max_dumps = int(max_dumps) if max_dumps and int(max_dumps) > 0 else DEFAULT_MAX_DUMPS
        self._explicit_dir = dump_dir is not None   # explicit dir = no fallback
        self._dump_dir = dump_dir or self._default_dump_dir()
        self._writers = []        # live dump_async writer threads (joined by flush())

        # The ring. deque(maxlen=cap) gives O(1) append + automatic eviction of the
        # oldest entry — no manual bookkeeping, no unbounded growth.
        from collections import deque
        self._ring = deque(maxlen=self.capacity)
        self._lock = threading.Lock()
        self._dumps_written = 0   # diagnostic counter (not load-bearing)

        if self.enabled:
            log.info("FlightRecorder L%s: armed (cap=%d, dir=%s)",
                     self.lane, self.capacity, self._dump_dir)

    # ---- internals --------------------------------------------------------
    @staticmethod
    def _default_dump_dir():
        # Prefer the Pi log dir; fall back to a temp dir if it doesn't exist /
        # isn't creatable, so construction on a laptop never fails.
        primary = os.path.join("/var/log", "lane-node")
        try:
            if os.path.isdir(primary) or os.path.isdir(os.path.dirname(primary)):
                return primary
        except Exception:
            pass
        import tempfile
        return os.path.join(tempfile.gettempdir(), "lane-node")

    # ---- hot path: record one event (called from io setters + the daemon) -
    def record(self, kind, name, value):
        """Append one (t_mono, kind, name, value) event. O(1), bounded, never raises.

        kind:  short category string, e.g. 'out' (relay/lamp change), 'state'
               (FSM transition), 'fault', 'wdog' (watchdog kick), 'cam'/'ball'
               (link events), 'arm', 'health'.
        name:  channel/output/state name (e.g. 'S', 'RUNTHROUGH', 'interlock').
        value: small JSON-able scalar (bool/int/float/str/None). NOT serialized
               here — kept as-is for O(1) append; coerced to str only at dump.
        """
        if not self.enabled:
            return
        try:
            # Snapshot the clock OUTSIDE any heavyweight work; append is the only
            # mutation and it is O(1). The Lock guards concurrent appends from the
            # serial-reader thread vs the control thread.
            t = self._now()
            with self._lock:
                self._ring.append((t, kind, name, value))
        except Exception:
            # A recorder failure must NEVER propagate into the control path.
            # Don't even log at warning on the hot path — debug only.
            log.debug("FlightRecorder L%s: record() swallowed an exception", self.lane,
                      exc_info=True)

    # ---- snapshot (bounded copy of the ring) ------------------------------
    def snapshot(self):
        """Return a list copy of the current ring (oldest-first). Bounded by
        capacity. Cheap O(cap); the Lock is held only for the copy."""
        try:
            with self._lock:
                return list(self._ring)
        except Exception:
            return []

    # ---- dump-on-trigger --------------------------------------------------
    def dump(self, reason="fault", extra=None):
        """Flush the ring to a timestamped JSON file. Best-effort: returns the
        written path on success, or None on any failure (and NEVER raises).

        SYNCHRONOUS — the disk write runs on the CALLER's thread. Fine for
        CLIs, tests and shutdown paths; the daemon's control loop must use
        dump_async() instead (an SD-card write stall here would freeze the
        shared 50 Hz tick loop — review #21/#54).

        reason: short trigger tag, baked into the filename + payload.
        extra:  optional small JSON-able dict of context (fsm_state, fw fault, etc.)
        """
        if not self.enabled:
            return None
        return self._write_dump(self.snapshot(), reason, extra)

    def dump_async(self, reason="fault", extra=None):
        """Control-loop-safe dump (review #21/#54): copy the ring NOW (an O(cap)
        list copy under the lock — microseconds), then serialize + write + prune
        on a short-lived daemon writer thread. The calling thread never touches
        the disk, so an SD-card write stall cannot delay the tick loop (which
        would starve the OTHER board's cam dispatch, fsm.poll() backstops and
        NE555 kick). Returns True if a writer was started, False otherwise;
        NEVER raises. Use flush() to join outstanding writers (tests/shutdown)."""
        if not self.enabled:
            return False
        try:
            rows = self.snapshot()
            t = threading.Thread(target=self._write_dump, args=(rows, reason, extra),
                                 name=f"fr-dump-L{self.lane}", daemon=True)
            # Track live writers (bounded: pruned on every call; dumps only fire
            # on faults). Plain list ops — atomic enough under the GIL.
            self._writers = [w for w in self._writers if w.is_alive()] + [t]
            t.start()
            return True
        except Exception:
            log.warning("FlightRecorder L%s: dump_async() failed (swallowed)",
                        self.lane, exc_info=True)
            return False

    def flush(self, timeout=5.0):
        """Join any in-flight dump_async writer threads (best-effort, bounded by
        `timeout` total, never raises). For tests + orderly shutdown."""
        try:
            deadline = time.monotonic() + float(timeout)
            for w in list(self._writers):
                w.join(max(0.0, deadline - time.monotonic()))
            self._writers = [w for w in self._writers if w.is_alive()]
        except Exception:
            pass

    def _ensure_dump_dir(self):
        """Return a usable (created + write-probed) dump dir, or None.

        An EXPLICIT dump_dir is honored strictly: unwritable -> None (the
        caller pointed at exactly one place; writing elsewhere would be a lie).
        The DEFAULT dir (/var/log/lane-node) is root-owned on a stock Pi while
        the daemon runs as User=pi — instead of silently dropping every
        black-box dump (review #48), fall back to a per-user writable dir with
        a LOUD one-time warning. The fallback sticks (self._dump_dir updates),
        so later dumps go straight there without re-warning."""
        primary = self._dump_dir
        candidates = [primary]
        if not self._explicit_dir:
            candidates.append(os.path.join(os.path.expanduser("~"),
                                           ".local", "state", "lane-node"))
            import tempfile
            candidates.append(os.path.join(tempfile.gettempdir(), "lane-node"))
        for d in candidates:
            try:
                os.makedirs(d, exist_ok=True)
                # makedirs succeeding is not enough: the dir may pre-exist
                # root-owned. Probe with a real write.
                probe = os.path.join(d, f".writable-{os.getpid()}.probe")
                with open(probe, "w") as f:
                    f.write("")
                os.remove(probe)
            except Exception:
                continue
            if d != primary:
                log.error("FlightRecorder L%s: dump dir %s is UNWRITABLE -> falling "
                          "back to %s (provision the primary: sudo mkdir -p %s && "
                          "sudo chown pi:pi %s)",
                          self.lane, primary, d, primary, primary)
                self._dump_dir = d
            return d
        log.error("FlightRecorder L%s: NO writable dump dir (tried %s) — dump DROPPED",
                  self.lane, ", ".join(candidates))
        return None

    def _write_dump(self, rows, reason, extra):
        """Serialize + write one dump — the disk-touching half of dump() /
        dump_async(). Runs on the caller's thread for dump() and on a writer
        thread for dump_async(). NEVER raises; returns the path or None."""
        try:
            wall = time.time()
            # Millisecond suffix: two dumps with the same reason in the same
            # second (e.g. concurrent writer threads) must not os.replace each
            # other away.
            stamp = (time.strftime("%Y%m%d_%H%M%S", time.localtime(wall))
                     + f"_{int((wall % 1.0) * 1000):03d}")
            safe_reason = "".join(c if (c.isalnum() or c in "-_") else "_"
                                  for c in str(reason))[:40] or "fault"
            fname = f"blackbox-L{self.lane}-{stamp}-{safe_reason}.json"

            payload = {
                "lane": self.lane,
                "reason": str(reason),
                "wall_time": wall,
                "wall_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(wall)),
                "capacity": self.capacity,
                "event_count": len(rows),
                # value coerced to a JSON-safe scalar only here, not on the hot path.
                "events": [
                    {"t": _round(t), "kind": _s(kind), "name": _s(name), "value": _jsonable(value)}
                    for (t, kind, name, value) in rows
                ],
            }
            if extra:
                try:
                    payload["context"] = {str(k): _jsonable(v) for k, v in dict(extra).items()}
                except Exception:
                    payload["context_error"] = "unserializable extra"

            d = self._ensure_dump_dir()
            if d is None:
                return None    # already logged LOUDLY by _ensure_dump_dir

            path = os.path.join(d, fname)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp, path)   # atomic-ish: never leave a half-written .json
            self._dumps_written += 1
            self._prune_dumps()
            log.info("FlightRecorder L%s: dumped %d events -> %s (reason=%s)",
                     self.lane, len(rows), path, reason)
            return path
        except Exception:
            log.warning("FlightRecorder L%s: dump write failed (swallowed)", self.lane,
                        exc_info=True)
            return None

    def _prune_dumps(self):
        """Keep at most max_dumps blackbox files for this lane; delete oldest.
        Best-effort, never raises."""
        try:
            prefix = f"blackbox-L{self.lane}-"
            files = sorted(
                (os.path.join(self._dump_dir, n) for n in os.listdir(self._dump_dir)
                 if n.startswith(prefix) and n.endswith(".json")),
                key=lambda p: os.path.getmtime(p),
            )
            for old in files[:-self.max_dumps]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass


# ---- module-level coercion helpers (only used at dump time, off the hot path) ----
def _round(t, ndigits=6):
    try:
        return round(float(t), ndigits)
    except Exception:
        return None


def _s(v):
    try:
        return str(v)
    except Exception:
        return "?"


def _jsonable(v):
    """Coerce a recorded value to a JSON-safe scalar. Bounded: long strings are
    truncated so one pathological value can't bloat a dump."""
    if v is None or isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    try:
        s = str(v)
    except Exception:
        return "?"
    return s if len(s) <= 200 else s[:200] + "...(truncated)"


# A shared no-op recorder for call sites that may run without one wired (keeps the
# instrumentation hooks branch-free + zero-cost when absent).
class _NullRecorder:
    enabled = False
    def record(self, *a, **k): pass
    def dump(self, *a, **k): return None
    def dump_async(self, *a, **k): return False
    def flush(self, *a, **k): pass
    def snapshot(self): return []


NULL_RECORDER = _NullRecorder()


if __name__ == "__main__":
    # Tiny smoke test (the real coverage is tests/test_flight_recorder.py).
    import sys
    import tempfile

    d = tempfile.mkdtemp(prefix="fr_smoke_")
    fr = FlightRecorder(21, capacity=8, dump_dir=d, now=lambda: 0.0)
    for i in range(20):                     # overflow the ring
        fr.record("out", "S", i % 2 == 0)
    snap = fr.snapshot()
    assert len(snap) == 8, snap              # bounded to capacity
    assert snap[-1][3] is False, snap[-1]    # last appended kept (i=19 -> odd -> False)
    p = fr.dump(reason="smoke", extra={"fsm_state": "FAULT"})
    assert p and os.path.exists(p), p
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["event_count"] == 8 and doc["context"]["fsm_state"] == "FAULT", doc

    # disabled recorder is an inert no-op
    fr2 = FlightRecorder(22, enabled=False, dump_dir=d)
    fr2.record("out", "T", True)
    assert fr2.snapshot() == [] and fr2.dump() is None
    print("flight_recorder smoke OK ->", p)
    sys.exit(0)
