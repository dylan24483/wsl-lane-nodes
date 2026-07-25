#!/usr/bin/env python3
"""
measure_actuation_bound.py — MEASURE the positive-actuation return bound on the
target platform, so `controller_io.POSITIVE_ACTUATION_MAX_S` stops being an
assertion.

WHY THIS EXISTS
---------------
`controller_io.POSITIVE_ACTUATION_MAX_S` (default 0.050 s) bounds how long a
safety-positive actuation (sweep-on / table-on / spot-on / arm-high / the
NE555 watchdog kick) may take to return. Exceeding it issues `action(False)`
mid-motion and escalates to `_hard_safe` + MANUAL_INTERVENTION, which requires
a physical PBZ to clear.

The bound is sampled with wall-clock `link.now()` across a call made from a
thread that competes under the CPython GIL with the serial reader, DiagWriter,
PlatformHealth (which forks `vcgencmd` every 60 s), CycleShipper, and async
recorder dumps. So the sample includes SCHEDULING PREEMPTION, not just I2C /
GPIO transport. That makes it a property of the *platform under load*, and it
was never measured on a Pi.

Two precedents in this project's own history are exactly this failure:
TAP_KICK_STARVE_MS set below the real kick cadence, and a PlatformHealth poll
cadence that false-expired healthy lanes. Do not add a third by guessing.

WHAT IT MEASURES
----------------
Two distributions, both from a thread standing in for the control thread:

  1. `write`  — a non-blocking callable, standing in for an MCP/GPIO register
                write. This is what POSITIVE_ACTUATION_MAX_S bounds.
  2. `kick`   — `sleep(WDOG_PULSE_S)` between the same two monotonic samples,
                standing in for `_kick_wdog`. This is what
                WATCHDOG_KICK_MAX_S bounds, and it BLOCKS by design.

Background load is synthesized to resemble the daemon: N GIL-contending
threads plus a periodic subprocess fork (matching PlatformHealth's `vcgencmd`).

HOW TO USE IT
-------------
Run ON THE PI, for a realistic duration, with the machine idle but the daemon's
peers running (or with --threads/--fork-period matched to them):

    python3 scripts/measure_actuation_bound.py --seconds 900

Then set BOTH bounds from the report's recommendation, e.g.:

    WSL_POSITIVE_ACTUATION_MAX_S=0.080
    WSL_WATCHDOG_KICK_MAX_S=0.082

Both env vars FAIL LOUD (ValueError at import, before hardware opens) on
garbage or out-of-range values — they never silently restore the default.

RECOMMENDATION RULE
-------------------
p99.9 x `--safety-factor` (default 2.0), rounded up to the next 5 ms, floored at
the current default. The point is a bound that is comfortably above observed
platform jitter while staying far below the heartbeat lease. If the recommended
value approaches `_ACTUATION_BOUND_HI_S`, the platform is too jittery to run
the control loop as-is; fix the jitter (thread count, fork cadence, CPU
governor, `isolcpus`), do NOT just raise the bound.

This script drives NO hardware. It is safe to run any time, on any machine.
Running it off-Pi is useful only as a smoke test of the script itself — the
numbers are not transferable (Windows' ~15.6 ms timer granularity alone makes
off-Pi results a loose upper bound, not a prediction).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lane_node"))

try:
    from controller_io import (  # noqa: E402
        _ACTUATION_BOUND_HI_S,
        POSITIVE_ACTUATION_MAX_S,
    )
except Exception:  # pragma: no cover - keep the tool usable standalone
    POSITIVE_ACTUATION_MAX_S = 0.050
    _ACTUATION_BOUND_HI_S = 0.500

# Mirrors controller_daemon.WDOG_PULSE_S. Imported lazily below when possible.
DEFAULT_WDOG_PULSE_S = 0.002


def _wdog_pulse_s() -> float:
    try:
        import controller_daemon  # noqa: E402
        return float(controller_daemon.WDOG_PULSE_S)
    except Exception:
        return DEFAULT_WDOG_PULSE_S


def percentile(sorted_vals, q):
    """Nearest-rank percentile. `sorted_vals` must be sorted ascending."""
    if not sorted_vals:
        return float("nan")
    k = max(0, min(len(sorted_vals) - 1,
                   int(round(q / 100.0 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[k]


class _Load:
    """Synthesize the daemon's GIL contention + periodic subprocess fork."""

    def __init__(self, threads, fork_period_s, fork_cmd):
        self._stop = threading.Event()
        self._threads = []
        self._n = threads
        self._fork_period_s = fork_period_s
        self._fork_cmd = fork_cmd
        self.forks = 0
        self.fork_errors = 0

    def _spin(self):
        # Short CPU bursts + short sleeps: the shape of the serial reader and
        # the diag/shipper threads, i.e. frequent GIL handoffs.
        while not self._stop.is_set():
            x = 0
            for i in range(20000):
                x += i * i
            time.sleep(0.001)

    def _fork(self):
        while not self._stop.wait(self._fork_period_s):
            try:
                subprocess.run(self._fork_cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
                self.forks += 1
            except Exception:
                self.fork_errors += 1

    def start(self):
        for _ in range(self._n):
            t = threading.Thread(target=self._spin, daemon=True)
            t.start()
            self._threads.append(t)
        if self._fork_period_s > 0:
            t = threading.Thread(target=self._fork, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)


def _sample(kind, duration_s, hz, pulse_s):
    """Return sorted elapsed-time samples for one operation kind."""
    now = time.monotonic
    period = 1.0 / hz
    out = []
    deadline = now() + duration_s
    nxt = now()
    sink = [0]
    while now() < deadline:
        nxt += period
        # Emulate the control thread's own pacing.
        slack = nxt - now()
        if slack > 0:
            time.sleep(slack)
        started = now()
        if kind == "kick":
            time.sleep(pulse_s)
        else:
            # Non-blocking stand-in for an MCP/GPIO register write.
            sink[0] = (sink[0] + 1) & 0xFF
        out.append(now() - started)
    out.sort()
    return out


def _report(name, samples, bound, pulse_s=0.0):
    n = len(samples)
    over = sum(1 for v in samples if v > bound)
    stats = {
        "operation": name,
        "samples": n,
        "current_bound_s": round(bound, 6),
        "deliberate_blocking_s": round(pulse_s, 6),
        "min_s": round(samples[0], 6) if n else None,
        "p50_s": round(percentile(samples, 50), 6) if n else None,
        "p99_s": round(percentile(samples, 99), 6) if n else None,
        "p99_9_s": round(percentile(samples, 99.9), 6) if n else None,
        "max_s": round(samples[-1], 6) if n else None,
        "over_bound": over,
        "over_bound_fraction": round(over / n, 9) if n else None,
    }
    return stats


def _recommend(p999, safety_factor, floor_s):
    if p999 != p999:  # NaN
        return None
    want = p999 * safety_factor
    # Round up to the next 5 ms so the shipped value is human-legible.
    stepped = (int(want / 0.005) + 1) * 0.005
    return round(max(stepped, floor_s), 6)


def main(argv=None):
    pulse_default = _wdog_pulse_s()
    ap = argparse.ArgumentParser(
        description="Measure the positive-actuation return bound on this host.")
    ap.add_argument("--seconds", type=float, default=300.0,
                    help="duration PER operation kind (default 300)")
    ap.add_argument("--hz", type=float, default=50.0,
                    help="control-loop rate to emulate (default 50)")
    ap.add_argument("--threads", type=int, default=4,
                    help="background GIL-contending threads (default 4: "
                         "serial reader, DiagWriter, PlatformHealth, shipper)")
    ap.add_argument("--fork-period", type=float, default=60.0,
                    help="seconds between background subprocess forks, "
                         "matching PlatformHealth (default 60; 0 disables)")
    ap.add_argument("--fork-cmd", default=None,
                    help="command for the periodic fork "
                         "(default: vcgencmd measure_temp, else a no-op)")
    ap.add_argument("--pulse", type=float, default=pulse_default,
                    help=f"NE555 pulse width to emulate "
                         f"(default {pulse_default})")
    ap.add_argument("--safety-factor", type=float, default=2.0,
                    help="multiplier applied to p99.9 (default 2.0)")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the full report to this path")
    args = ap.parse_args(argv)

    fork_cmd = args.fork_cmd
    if fork_cmd is None:
        if os.path.exists("/usr/bin/vcgencmd"):
            fork_cmd = ["/usr/bin/vcgencmd", "measure_temp"]
        else:
            fork_cmd = [sys.executable, "-c", "pass"]
    elif isinstance(fork_cmd, str):
        fork_cmd = fork_cmd.split()

    print(f"host={os.name} python={sys.version.split()[0]} "
          f"switchinterval={sys.getswitchinterval()}s")
    print(f"emulating {args.hz:g} Hz control loop, {args.threads} background "
          f"threads, fork every {args.fork_period:g}s ({fork_cmd[0]})")
    if os.name == "nt":
        print("WARNING: Windows timer granularity (~15.6 ms) makes these "
              "numbers an UPPER BOUND, not a Pi prediction. Run on the Pi.")

    load = _Load(args.threads, args.fork_period, fork_cmd)
    load.start()
    try:
        print(f"sampling 'write' for {args.seconds:g}s ...")
        writes = _sample("write", args.seconds, args.hz, args.pulse)
        print(f"sampling 'kick' for {args.seconds:g}s ...")
        kicks = _sample("kick", args.seconds, args.hz, args.pulse)
    finally:
        load.stop()

    kick_bound = POSITIVE_ACTUATION_MAX_S + args.pulse
    reports = [
        _report("positive-write", writes, POSITIVE_ACTUATION_MAX_S),
        _report("watchdog-kick", kicks, kick_bound, args.pulse),
    ]

    rec_write = _recommend(percentile(writes, 99.9), args.safety_factor,
                           POSITIVE_ACTUATION_MAX_S)
    rec_kick = None
    if rec_write is not None:
        rec_kick = round(rec_write + args.pulse, 6)

    print()
    for r in reports:
        print(json.dumps(r, indent=2))
    print()
    print("RECOMMENDATION (p99.9 x safety-factor, rounded up to 5 ms, "
          "floored at the current default):")
    print(f"  WSL_POSITIVE_ACTUATION_MAX_S={rec_write}")
    print(f"  WSL_WATCHDOG_KICK_MAX_S={rec_kick}")
    print()
    if rec_write is not None and rec_write > _ACTUATION_BOUND_HI_S:
        print("REFUSED: the measured jitter needs a bound above the permitted "
              f"maximum ({_ACTUATION_BOUND_HI_S}s). Do NOT raise the ceiling. "
              "Reduce platform jitter (thread count, fork cadence, CPU "
              "governor, isolcpus) and re-measure.")
    elif rec_write is not None and rec_write > POSITIVE_ACTUATION_MAX_S:
        print("The shipped default is BELOW measured platform jitter on this "
              "host. Set the env vars above before running LIVE.")
    else:
        print("The shipped default covers measured jitter on this host with "
              "the requested safety factor. No env override needed.")

    payload = {
        "host_os": os.name,
        "python": sys.version.split()[0],
        "switchinterval_s": sys.getswitchinterval(),
        "hz": args.hz,
        "threads": args.threads,
        "fork_period_s": args.fork_period,
        "fork_cmd": fork_cmd,
        "pulse_s": args.pulse,
        "safety_factor": args.safety_factor,
        "forks": load.forks,
        "fork_errors": load.fork_errors,
        "reports": reports,
        "recommended": {
            "WSL_POSITIVE_ACTUATION_MAX_S": rec_write,
            "WSL_WATCHDOG_KICK_MAX_S": rec_kick,
        },
    }
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
