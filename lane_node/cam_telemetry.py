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

import logging
import math
import os
from collections import deque

log = logging.getLogger("cam_telemetry")

# Env kill-switch (default ON, observe-only + bounded). Drift WARNINGS can be
# silenced independently if they prove noisy during early soak (alarm-only off).
DISABLE_ENV = "WSL_CAM_TELEMETRY"
DRIFT_ALARM_DISABLE_ENV = "WSL_CAM_TELEMETRY_ALARM"

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
    """

    def __init__(self, lane, *, intervals=None, recorder=None, sink=None,
                 drift_sigma=DEFAULT_DRIFT_SIGMA, enabled=None, now=None):
        self.lane = lane
        self.enabled = _enabled(DISABLE_ENV) if enabled is None else bool(enabled)
        self.alarm_enabled = _enabled(DRIFT_ALARM_DISABLE_ENV)
        self._recorder = recorder
        self._sink = sink
        self.drift_sigma = float(drift_sigma) if drift_sigma else DEFAULT_DRIFT_SIGMA
        self._intervals = tuple(intervals) if intervals else DEFAULT_INTERVALS

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

        if self.enabled:
            log.info("CamTelemetry L%s: armed (%d intervals, drift>%.1f sigma%s)",
                     self.lane, len(self._intervals), self.drift_sigma,
                     "" if self.alarm_enabled else ", ALARM OFF")

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
                base.add(dt)

            if durations:
                self._emit(self.cycle_index, durations)
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
