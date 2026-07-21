#!/usr/bin/env python3
"""
cam_telemetry.py — per-cycle cam/sweep/table timing with drift alarms (idea #15).

WHAT IT IS
  Every cycle the 82-70 emits a mechanical fingerprint for free: SS->SB@66,
  table-start->TA2@260, TA2->SA@270, sweep@270->TA1-zero, etc. This module turns the
  event stream the daemon already sees into per-cycle INTERVALS, keeps a rolling
  per-lane baseline (running mean + variance, bounded memory), and raises a DRIFT
  ALARM when an interval deviates > N standard deviations from that baseline. A
  sweep that is 15% slower week-over-week is a stretching belt or a dry pivot —
  caught BEFORE it trips MAX_MOTION mid-league. It also gives quantitative soak
  acceptance ('cycle timing stable +/-2% over 7 days') and per-lane numbers to set
  MAX_MOTION from measured p99 instead of one global guess.

OBSERVE-ONLY + BOUNDED + NO CONTROL EFFECT (the rules for this file)
  * OBSERVE-ONLY: drives NOTHING. It is fed timestamped event names; it computes
    intervals and may log a drift WARNING or push a row into the flight recorder.
    It never touches a relay, the FSM, or the watchdog, and it cannot change the
    MAX_MOTION backstop (that stays the FSM's blunt hard limit).
  * BOUNDED: the baseline is an O(1) running aggregate per interval (Welford), and
    only a small fixed set of interval names exists, so memory is constant
    regardless of soak length. The optional recent-sample window is a bounded deque.
  * FAIL-SAFE: every public method swallows its own exceptions — a telemetry bug can
    never raise into the control loop. on_event() is O(#intervals-ending-here),
    which is tiny.

USAGE (in the daemon, observe-only)
    tel = CamTelemetry(lane)
    ...each time the daemon/FSM sees a discrete event with a monotonic timestamp...
    tel.on_event("ball", t)          # SS / ball thrown -> starts the SS->SB interval
    tel.on_event("cam:SB", t)        # closes SS->SB, ...
    ...at end of cycle (READY reached)...
    tel.end_cycle()                  # finalize: any open intervals are dropped

The daemon already drives the FSM from exactly these events (rp2040_link cam/ball +
the slow-input edges), so hooking is just calling on_event() alongside the existing
dispatch — no new event source.
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
from collections import deque

log = logging.getLogger("cam_telemetry")

# Env kill-switch (default ON, observe-only + bounded). Drift WARNINGS can be
# silenced independently if they prove noisy during early soak (alarm-only off).
DISABLE_ENV = "WSL_CAM_TELEMETRY"
DRIFT_ALARM_DISABLE_ENV = "WSL_CAM_TELEMETRY_ALARM"
# Baseline persistence (2026-07-19 diagnostics scope, Phase 1.7): drift alarms
# need 30 samples and used to reset blind on every restart. Opt-in per instance
# (the daemon passes persist=True); PERSIST_ENV is the env kill-switch on top.
PERSIST_ENV = "WSL_CAM_TELEMETRY_PERSIST"          # default ON when persist=True
PERSIST_EVERY_ENV = "WSL_CAM_TELEMETRY_PERSIST_EVERY"  # save every N sampled cycles
PERSIST_DIR_ENV = "WSL_DIAG_DIR"                   # shared with diag_events
DEFAULT_PERSIST_DIR = "./diag_logs"
DEFAULT_PERSIST_EVERY = 25

_FALSEY = ("0", "false", "no", "off", "")

# Default drift threshold: flag a sample > this many stddev from the rolling mean.
DEFAULT_DRIFT_SIGMA = 4.0
# Don't alarm until the baseline has at least this many samples (avoids screaming on
# a cold baseline where the variance estimate is meaningless).
MIN_SAMPLES_FOR_ALARM = 30
# Also require an absolute floor on the deviation so micro-jitter around a very tight
# baseline (tiny stddev) doesn't false-alarm. Seconds.
MIN_ABS_DRIFT_S = 0.15
# Recent-sample window per interval (bounded; for p-stats / a trend endpoint).
RECENT_WINDOW = 200
# Hard sanity bound on a single interval sample (seconds). A stale open-interval
# start (e.g. a cycle aborted by a FAULT/safety trip that end_cycle never
# finalized) can measure a minutes-long "interval"; ONE such garbage sample
# inflates the cumulative Welford variance enough to blind the sigma drift alarm
# for hundreds of cycles. No real 82-70 interval approaches this bound.
MAX_SAMPLE_S = float(os.environ.get("WSL_CAM_TELEMETRY_MAX_SAMPLE_S", "60.0"))

# The interval set: (name, start_event, end_event). Each is measured from the FIRST
# occurrence of start_event after a cycle reset to the FIRST occurrence of end_event.
# Event names are the daemon's discrete events; cam events are prefixed "cam:".
#   ball         = SS / DIELL ball thrown (cycle trigger)
#   cam:SB       = sweep reached 66 (guard)
#   table_start  = table commanded down after the settle delay (daemon/FSM emits)
#   cam:TA2      = table reached 260 (pins latched, runthrough begins)
#   cam:SA       = sweep reached 270 (runthrough stop) / 360 (zero) — first SA edge
#   bs           = bin switch (10th pin to bin) — fresh-rack gate
#   cam:TA1      = table reached 355/zero
# These mirror the # CONFIRM timing questions in cycle_control_8270 and the audit's
# named fingerprint. Intervals whose endpoints don't both occur in a cycle are simply
# not recorded that cycle (e.g. table descent is skipped on the bench-gated 2nd-ball
# path) — no error, just a missing sample.
DEFAULT_INTERVALS = (
    ("ss_to_guard",      "ball",        "cam:SB"),    # sweep run to 66
    ("guard_to_table",   "cam:SB",      "table_start"),  # settle delay + table-on
    ("table_to_ta2",     "table_start", "cam:TA2"),   # table descent to 260
    ("ta2_to_sa",        "cam:TA2",     "cam:SA"),     # sweep run-through
    ("sa_to_ta1zero",    "cam:SA",      "cam:TA1"),    # finish to table zero
    ("bs_to_ta1zero",    "bs",          "cam:TA1"),    # spotting revolution
)


def _enabled(env):
    return os.environ.get(env, "1").strip().lower() not in _FALSEY


class _Running:
    """O(1) running mean + variance (Welford) + a bounded recent window. Constant
    memory: holds count/mean/M2 scalars + a deque capped at RECENT_WINDOW."""

    __slots__ = ("n", "mean", "_m2", "recent", "vmin", "vmax")

    def __init__(self, window=RECENT_WINDOW):
        self.n = 0
        self.mean = 0.0
        self._m2 = 0.0
        self.recent = deque(maxlen=window)
        self.vmin = None
        self.vmax = None

    def add(self, x):
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self._m2 += d * (x - self.mean)
        self.recent.append(x)
        self.vmin = x if self.vmin is None else min(self.vmin, x)
        self.vmax = x if self.vmax is None else max(self.vmax, x)

    # -- persistence (Phase 1.7): the O(1) aggregate round-trips exactly; the
    #    bounded recent window is deliberately NOT persisted (trend detail only).
    def to_state(self):
        return {"n": self.n, "mean": self.mean, "m2": self._m2,
                "min": self.vmin, "max": self.vmax}

    def restore(self, st):
        """Load a to_state() dict. Raises on garbage (caller catches — one bad
        interval must not poison the others)."""
        n = int(st["n"])
        mean = float(st["mean"])
        m2 = float(st["m2"])
        if n < 0 or m2 < 0 or not math.isfinite(mean) or not math.isfinite(m2):
            raise ValueError(f"implausible baseline state {st!r}")
        self.n = n
        self.mean = mean
        self._m2 = m2
        self.vmin = None if st.get("min") is None else float(st["min"])
        self.vmax = None if st.get("max") is None else float(st["max"])

    @property
    def variance(self):
        return self._m2 / (self.n - 1) if self.n > 1 else 0.0

    @property
    def stddev(self):
        return math.sqrt(self.variance)


class CamTelemetry:
    """Per-lane cam/sweep/table timing tracker. Observe-only, bounded, fail-safe.

    Args:
      lane:        lane id (stamped into log + flight-recorder rows).
      intervals:   iterable of (name, start_event, end_event); default DEFAULT_INTERVALS.
      recorder:    optional FlightRecorder — finalized cycles + drift alarms are also
                   pushed as 'cam_timing' / 'cam_drift' events (still observe-only).
      sink:        optional callable(lane, cycle_index, {name: seconds}) for a per-cycle
                   row (e.g. POST to lane_node_server's cycle_timings table). Wrapped so
                   a slow/raising sink can never break the control loop — but prefer an
                   async/non-blocking sink; this is called inline at end_cycle().
      drift_sigma: stddev multiplier for the drift alarm. Default DEFAULT_DRIFT_SIGMA.
      enabled:     None -> env kill-switch (default ON); True/False forces.
      now:         unused for timing (timestamps are passed in) — kept for symmetry.
      diag_emit:   optional callable(severity, event_type, code, detail) offered
                   each drift alarm (event_type 'drift_alarm'). ⚠️ Runs inline at
                   end_cycle() — i.e. inside the daemon tick — so it MUST be
                   non-blocking (enqueue-only; the daemon passes its
                   suppression-aware DiagQueue emitter). Wrapped fail-safe.
      persist:     True -> baselines survive restarts (Phase 1.7): loaded from
                   <persist_dir>/cam_baselines_<lane>.json at construction, saved
                   atomically by maybe_persist()/stop(). Default False so bare
                   constructions (tests, tools) never touch the filesystem.
                   PERSIST_ENV ('WSL_CAM_TELEMETRY_PERSIST', default on) is the
                   env kill-switch on top. ⚠️ end_cycle() never writes the file —
                   maybe_persist() is the write point and must be called OFF the
                   tick (the daemon's platform-health thread pumps it).
      persist_dir / persist_every: override the WSL_DIAG_DIR / N-sampled-cycles
                   save cadence (env PERSIST_EVERY_ENV, default 25).

    TIMESTAMP DOMAINS (2026-07-19 fw-timestamp replumb): on_event timestamps are
    Pi-monotonic SECONDS. The daemon feeds cam-edge events at the firmware's 1 ms
    edge time mapped through rp2040_link.FwClock (pure-edge intervals ss_to_guard
    / ta2_to_sa / sa_to_ta1zero gain ~1 ms resolution); command-anchored events
    (table_start, bs) stay Pi tick time — intervals mixing the two clocks
    (guard_to_table, table_to_ta2, bs_to_ta1zero) carry NO precision claim.
    """

    def __init__(self, lane, *, intervals=None, recorder=None, sink=None,
                 drift_sigma=DEFAULT_DRIFT_SIGMA, enabled=None, now=None,
                 diag_emit=None, persist=False, persist_dir=None,
                 persist_every=None):
        self.lane = lane
        self.enabled = _enabled(DISABLE_ENV) if enabled is None else bool(enabled)
        self.alarm_enabled = _enabled(DRIFT_ALARM_DISABLE_ENV)
        self._recorder = recorder
        self._sink = sink
        self._diag_emit = diag_emit
        self.drift_sigma = float(drift_sigma) if drift_sigma else DEFAULT_DRIFT_SIGMA
        self._intervals = tuple(intervals) if intervals else DEFAULT_INTERVALS
        # baseline persistence (Phase 1.7) — opt-in + env-killable, fail-safe
        self.persist = bool(persist) and _enabled(PERSIST_ENV)
        self._persist_dir = (persist_dir
                             or os.environ.get(PERSIST_DIR_ENV, "").strip()
                             or DEFAULT_PERSIST_DIR)
        try:
            self._persist_every = max(1, int(
                persist_every
                or os.environ.get(PERSIST_EVERY_ENV, "").strip()
                or DEFAULT_PERSIST_EVERY))
        except Exception:
            self._persist_every = DEFAULT_PERSIST_EVERY
        self._samples_since_save = 0
        self.persist_errors = 0
        self.persist_saves = 0
        # Persistence races (2026-07-19 review): save_baselines can be called
        # from BOTH the platform-health thread (maybe_persist) and the
        # shutdown paths (run() finally + PlatformHealth exit both call
        # stop()) while the tick thread is still folding samples via
        # end_cycle. _persist_lock serializes writers (two threads sharing
        # one .tmp path collided — on Windows os.replace of an open file
        # fails and the session's final save could be lost); _state_lock
        # makes the snapshot consistent vs add() (a save landing between the
        # n+=1 and _m2+= lines of _Running.add persisted a torn Welford
        # triple that restore() cannot detect). add() only ever holds
        # _state_lock for O(µs) arithmetic — file I/O happens strictly
        # outside it, so the tick can never block on the SD card.
        self._persist_lock = threading.Lock()
        self._state_lock = threading.Lock()

        # name -> _Running baseline (constant per-interval memory)
        self._base = {name: _Running() for (name, _s, _e) in self._intervals}
        # endpoints index: which intervals start / end on a given event
        self._starts_on = {}
        self._ends_on = {}
        for (name, s, e) in self._intervals:
            self._starts_on.setdefault(s, []).append(name)
            self._ends_on.setdefault(e, []).append(name)

        self._reset_cycle()
        self.cycle_index = 0

        if self.enabled and self.persist:
            self._load_baselines()

        if self.enabled:
            log.info("CamTelemetry L%s: armed (%d intervals, drift>%.1f sigma%s%s)",
                     self.lane, len(self._intervals), self.drift_sigma,
                     "" if self.alarm_enabled else ", ALARM OFF",
                     ", persisted" if self.persist else "")

    # ---- per-cycle state --------------------------------------------------
    def _reset_cycle(self):
        # first-seen monotonic timestamp of each START event this cycle, and the
        # finalized interval durations this cycle.
        self._open = {}           # start_event_name -> t (first occurrence this cycle)
        self._durations = {}      # interval_name -> seconds

    # ---- hot path: feed one timestamped event -----------------------------
    def on_event(self, event, t):
        """Record that `event` occurred at monotonic time `t`. Closes any interval
        ending on this event whose start has been seen; opens starts. O(small),
        bounded, never raises into the caller."""
        if not self.enabled:
            return
        try:
            # close intervals that END on this event (start already seen this cycle)
            for name in self._ends_on.get(event, ()):
                start_ev = self._interval_start(name)
                if name not in self._durations and start_ev in self._open:
                    dt = t - self._open[start_ev]
                    if 0 <= dt <= MAX_SAMPLE_S:      # ignore inverted/duplicate edges
                        self._durations[name] = dt
                    elif dt > MAX_SAMPLE_S:
                        # stale start (aborted cycle leftovers) — never fold
                        # garbage into the baseline (see MAX_SAMPLE_S above)
                        log.debug("CamTelemetry L%s: %s=%.1fs > %.0fs sanity bound "
                                  "-- sample dropped (stale start?)",
                                  self.lane, name, dt, MAX_SAMPLE_S)
            # open intervals that START on this event (first occurrence wins)
            if event in self._starts_on and event not in self._open:
                self._open[event] = t
        except Exception:
            log.debug("CamTelemetry L%s: on_event(%r) swallowed", self.lane, event,
                      exc_info=True)

    def _interval_start(self, name):
        for (n, s, _e) in self._intervals:
            if n == name:
                return s
        return None

    # ---- end of cycle: fold durations into baselines + emit --------------
    def end_cycle(self):
        """Finalize the current cycle: fold each measured interval into its rolling
        baseline (checking drift first against the PRE-update baseline), push a row to
        the sink / recorder, and reset for the next cycle. Returns the dict of
        {name: seconds} measured this cycle (possibly empty). Never raises."""
        if not self.enabled:
            return {}
        try:
            durations = dict(self._durations)
            self.cycle_index += 1
            for name, dt in durations.items():
                base = self._base.get(name)
                if base is None:
                    continue
                # drift check uses the baseline BEFORE this sample is folded in.
                self._check_drift(name, dt, base)
                with self._state_lock:   # consistent vs save_baselines snapshot
                    base.add(dt)

            if durations:
                self._emit(self.cycle_index, durations)
                self._samples_since_save += 1   # persistence dirt; NO file I/O here
            self._reset_cycle()
            return durations
        except Exception:
            log.debug("CamTelemetry L%s: end_cycle swallowed", self.lane, exc_info=True)
            try:
                self._reset_cycle()
            except Exception:
                pass
            return {}

    def abort_cycle(self):
        """Abandon the current cycle WITHOUT folding anything into the baselines.

        Call on any transition into FAULT / MANUAL_INTERVENTION / POWER_OFF: the
        cycle's open-interval start timestamps go stale the moment the machine
        stops mid-cycle, and the next real ball would otherwise measure e.g.
        ss_to_guard from the PRE-FAULT ball ('first occurrence wins' in on_event)
        — a minutes-long garbage sample that permanently blinds the sigma drift
        alarm. Observe-only, bounded, never raises."""
        if not self.enabled:
            return
        try:
            self._reset_cycle()
        except Exception:
            log.debug("CamTelemetry L%s: abort_cycle swallowed", self.lane,
                      exc_info=True)

    def _check_drift(self, name, dt, base):
        if not self.alarm_enabled or base.n < MIN_SAMPLES_FOR_ALARM:
            return
        sd = base.stddev
        dev = abs(dt - base.mean)
        # Require BOTH a sigma breach and an absolute floor, so a razor-tight baseline
        # (tiny sd) doesn't alarm on sub-perceptible jitter.
        if sd > 0 and dev >= self.drift_sigma * sd and dev >= MIN_ABS_DRIFT_S:
            pct = (dt / base.mean - 1.0) * 100.0 if base.mean else 0.0
            log.warning("CamTelemetry L%s DRIFT %s=%.3fs vs baseline %.3fs+/-%.3fs "
                        "(%.0f sigma, %+.1f%%, n=%d) — predictive-maint flag",
                        self.lane, name, dt, base.mean, sd, dev / sd, pct, base.n)
            if self._recorder is not None:
                try:
                    self._recorder.record("cam_drift", name,
                                           {"dt": round(dt, 4), "mean": round(base.mean, 4),
                                            "sd": round(sd, 4), "n": base.n})
                except Exception:
                    pass
            if self._diag_emit is not None:
                # route the alarm into the diagnostics event pipe ('drift_alarm',
                # scope §3.1). The callable must be enqueue-only (tick context);
                # a broken emitter is swallowed — telemetry never raises.
                try:
                    self._diag_emit("warn", "drift_alarm", f"drift:{name}",
                                    {"interval": name, "dt_s": round(dt, 4),
                                     "mean_s": round(base.mean, 4),
                                     "sd_s": round(sd, 4), "n": base.n,
                                     "sigma": round(dev / sd, 1),
                                     "pct": round(pct, 1)})
                except Exception:
                    log.debug("CamTelemetry L%s: diag_emit swallowed", self.lane,
                              exc_info=True)

    def _emit(self, cycle_index, durations):
        rounded = {k: round(v, 4) for k, v in durations.items()}
        if self._recorder is not None:
            try:
                self._recorder.record("cam_timing", f"cycle{cycle_index}", rounded)
            except Exception:
                pass
        if self._sink is not None:
            try:
                self._sink(self.lane, cycle_index, rounded)
            except Exception:
                log.debug("CamTelemetry L%s: sink raised (swallowed)", self.lane,
                          exc_info=True)

    # ---- baseline persistence (Phase 1.7) ---------------------------------
    def _baseline_path(self):
        return os.path.join(self._persist_dir, f"cam_baselines_{self.lane}.json")

    def _load_baselines(self):
        """Restore saved baselines at construction. Stale/corrupt/missing files
        are tolerated (log + fresh start) — never raises. Only interval names in
        the CURRENT interval set are restored; per-interval garbage is skipped
        without poisoning the others."""
        path = self._baseline_path()
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            saved = doc.get("baselines")
            if not isinstance(saved, dict):
                raise ValueError("no baselines dict")
            loaded = 0
            for name, st in saved.items():
                base = self._base.get(name)
                if base is None or not isinstance(st, dict):
                    continue
                try:
                    base.restore(st)
                    loaded += 1
                except Exception:
                    log.warning("CamTelemetry L%s: skipping corrupt persisted "
                                "baseline %r", self.lane, name)
            self.cycle_index = max(self.cycle_index,
                                   int(doc.get("cycle_index", 0) or 0))
            if loaded:
                log.info("CamTelemetry L%s: restored %d persisted baselines "
                         "from %s (saved_at=%s)", self.lane, loaded, path,
                         doc.get("saved_at"))
        except FileNotFoundError:
            pass
        except Exception:
            self.persist_errors += 1
            log.warning("CamTelemetry L%s: persisted baselines unusable (%s) — "
                        "starting fresh", self.lane, path, exc_info=True)

    def save_baselines(self):
        """Atomically write the baselines (tmp + os.replace — a crash mid-write
        can never leave a torn file). Thread-safe: concurrent savers are
        serialized on _persist_lock and the baseline snapshot is taken under
        _state_lock so it can never capture a half-updated Welford aggregate
        (see the __init__ note). ⚠️ FILE I/O — call OFF the tick only
        (maybe_persist from a background thread, or stop()). Never raises;
        returns True on a successful write."""
        if not (self.enabled and self.persist):
            return False
        try:
            with self._persist_lock:
                with self._state_lock:
                    states = {name: b.to_state()
                              for name, b in self._base.items()}
                doc = {
                    "lane": self.lane,
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "cycle_index": self.cycle_index,
                    "baselines": states,
                }
                os.makedirs(self._persist_dir, exist_ok=True)
                path = self._baseline_path()
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(doc, f, separators=(",", ":"))
                os.replace(tmp, path)
                self._samples_since_save = 0
                self.persist_saves += 1
                return True
        except Exception:
            self.persist_errors += 1
            log.debug("CamTelemetry L%s: save_baselines swallowed", self.lane,
                      exc_info=True)
            return False

    def maybe_persist(self):
        """Save iff >= persist_every sampled cycles accumulated since the last
        save. The daemon's platform-health thread pumps this (off-tick); safe to
        call from anywhere EXCEPT the tick. Never raises."""
        if self.persist and self._samples_since_save >= self._persist_every:
            return self.save_baselines()
        return False

    def stop(self):
        """Final save on shutdown (anything dirty). Never raises."""
        if self.persist and self._samples_since_save:
            return self.save_baselines()
        return False

    # ---- queries (for a trend endpoint / soak acceptance) -----------------
    def baselines(self):
        """{name: {n, mean, stddev, min, max}} snapshot of the rolling baselines.
        Bounded; safe to call any time. Never raises."""
        out = {}
        try:
            for name, b in self._base.items():
                out[name] = {
                    "n": b.n,
                    "mean": round(b.mean, 4) if b.n else None,
                    "stddev": round(b.stddev, 4) if b.n > 1 else None,
                    "min": round(b.vmin, 4) if b.vmin is not None else None,
                    "max": round(b.vmax, 4) if b.vmax is not None else None,
                }
        except Exception:
            pass
        return out


class CycleShipper:
    """Bounded queue + background thread shipping per-cycle machine_cycles rows
    via a post_cycle callable (diag_events.HttpSink.post_cycle). The tick thread
    only ever offer()s (put_nowait — never blocks, never raises); ALL HTTP
    happens on this thread, per the scope §3 'never from the tick thread' rule.

    Overflow drops the row and counts it (.drops — the honesty metric); a
    post_cycle failure is counted (.errors) and the row is dropped, never
    retried into an unbounded backlog (HttpSink already retries internally)."""

    def __init__(self, post_cycle, *, maxsize=64, poll_s=0.25):
        self._post = post_cycle
        self._q = queue.Queue(maxsize=max(1, int(maxsize)))
        self.poll_s = float(poll_s)
        self.drops = 0
        self.shipped = 0
        self.errors = 0
        self._stop = threading.Event()
        self._thread = None

    def offer(self, row):
        """Enqueue one row. Returns True if queued; False (counted) if dropped."""
        try:
            self._q.put_nowait(row)
            return True
        except Exception:
            self.drops += 1
            return False

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cycle-shipper",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout=5.0):
        """Signal + join; anything still queued is shipped synchronously
        (bounded by the queue cap). Never raises."""
        try:
            self._stop.set()
            t = self._thread
            if t is not None and t.is_alive():
                t.join(timeout)
            if t is None or not t.is_alive():
                self._drain()
        except Exception:
            log.debug("CycleShipper.stop swallowed", exc_info=True)

    def _ship(self, row):
        try:
            ok = self._post(row)
            if ok:
                self.shipped += 1
            else:
                self.errors += 1
        except Exception:
            self.errors += 1
            log.debug("CycleShipper: post_cycle swallowed", exc_info=True)

    def _drain(self):
        for _ in range(self._q.maxsize + 8):
            try:
                row = self._q.get_nowait()
            except Exception:
                break
            self._ship(row)

    def _run(self):
        try:
            while True:
                try:
                    row = self._q.get(timeout=self.poll_s)
                except Exception:
                    row = None
                if row is not None:
                    self._ship(row)
                if self._stop.is_set() and self._q.empty():
                    break
        except Exception:
            log.warning("CycleShipper thread swallowed an exception", exc_info=True)
        finally:
            self._drain()


if __name__ == "__main__":
    # Smoke test (full coverage in tests/test_flight_recorder.py's telemetry section).
    import sys
    tel = CamTelemetry(21, enabled=True)
    t = 0.0
    # 60 nominal cycles to build a baseline
    for _ in range(60):
        tel.on_event("ball", t)
        tel.on_event("cam:SB", t + 0.60)
        tel.on_event("table_start", t + 3.70)
        tel.on_event("cam:TA2", t + 4.90)
        tel.on_event("cam:SA", t + 5.80)
        tel.on_event("cam:TA1", t + 7.10)
        d = tel.end_cycle()
        assert abs(d["ss_to_guard"] - 0.60) < 1e-6, d
        t += 20.0
    bl = tel.baselines()
    assert bl["ss_to_guard"]["n"] == 60, bl
    assert abs(bl["ss_to_guard"]["mean"] - 0.60) < 1e-3, bl

    # abort_cycle: a FAULT mid-cycle discards the open intervals — the next real
    # cycle measures from ITS OWN ball, not the stale pre-fault one.
    tel.on_event("ball", t)                     # cycle starts...
    tel.abort_cycle()                           # ...FAULT/safety trip -> abandoned
    t += 300.0                                  # dead time in MANUAL_INTERVENTION
    tel.on_event("ball", t)
    tel.on_event("cam:SB", t + 0.60)
    d = tel.end_cycle()
    assert abs(d["ss_to_guard"] - 0.60) < 1e-6, d
    bl = tel.baselines()
    assert bl["ss_to_guard"]["max"] < 1.0, bl   # the stale 300s start never folded

    # MAX_SAMPLE_S backstop: a garbage-long sample is rejected even without abort.
    t += 20.0
    tel.on_event("ball", t)
    tel.on_event("cam:SB", t + 400.0)           # > MAX_SAMPLE_S sanity bound
    d = tel.end_cycle()
    assert "ss_to_guard" not in d, d
    bl = tel.baselines()
    assert bl["ss_to_guard"]["max"] < 1.0, bl

    print("cam_telemetry smoke OK; baselines:", {k: v["mean"] for k, v in bl.items()})
    sys.exit(0)
