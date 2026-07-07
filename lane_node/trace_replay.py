#!/usr/bin/env python3
"""trace_replay.py — record + replay harness for the 8270 cycle-control FSM (idea #9).

Converts the FSM from "validated once on a synthetic __main__ sim" into something
that is REPEATABLE in CI against a recorded trace of cam/sensor events. A trace is
a flat, ordered JSON list of timestamped records; `replay()` feeds the trace into a
real `CycleController` (cycle_control_8270.py) through a recording `FakeIO`, then
asserts the resulting (state, output) sequence matches a checked-in golden.

This module is PURE SOFTWARE and READ-ONLY w.r.t. the FSM: it imports
CycleController + State + Ball + Cycle and never modifies them. It drives NO
hardware. Safe to run anywhere with `py -3 trace_replay.py` (selftest below).

────────────────────────────────────────────────────────────────────────────────
TRACE FORMAT  (JSON: {"meta": {...}, "events": [ rec, rec, ... ]})

Each `rec` is a dict with at least {"t": <float monotonic seconds>, "kind": ...}.

  kind="input"   set a FakeIO input level BEFORE the next event is applied.
                 {"t", "kind":"input", "name": <input>, "value": <bool|int>}
                 name ∈ {interlock, gp, bs, grippers}  (grippers value = int mask)

  kind="call"    invoke an FSM method (a cam edge, ball, foul, operator button).
                 {"t", "kind":"call", "name": <method>}
                 name ∈ {power_restore, first_ball_zero, on_ball, on_foul,
                         cam_SB_guard, cam_TA2_runthrough, cam_SA_runthrough,
                         cam_SA_zero, cam_TA1_delayreset, cam_TA1_zero, bin_full}
                 The "SA" / "TA1" dual-trip cams (rp2040_link.dispatch_cam fires
                 BOTH angle handlers per physical edge) are recorded as the two
                 explicit sub-calls so a trace mirrors what the daemon actually does.

  kind="poll"    advance the injected clock to t, then call controller.poll().
                 {"t", "kind":"poll"}

  kind="output"  (recording only) the io output the FSM emitted. Ignored on input
                 by replay()'s driver — outputs are what replay() ASSERTS, not feeds.

The injected clock is set to each record's "t" before the record is applied, so
GUARD_DELAY / MAX_MOTION_S timing is reproduced deterministically without real sleeps.

GOLDEN EXPECTATION (separate JSON, {"final_state","final_ball","outputs":[...]}):
  outputs = the ordered list of OUTPUT effects the FSM must emit, each one of
    ["sweep", bool] | ["table", bool] | ["spot", bool] |
    ["pin_lamps", int] | ["light", name, bool]
  (log lines + watchdog kicks are not asserted — they are not control outputs.)
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import CycleController, State, Ball  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# FSM methods a trace is allowed to invoke (whitelist — a typo'd name FAILS loudly
# rather than silently mutating something via getattr).
_CALLABLE = {
    "power_restore", "first_ball_zero", "on_ball", "on_foul",
    "cam_SB_guard", "cam_TA2_runthrough", "cam_SA_runthrough", "cam_SA_zero",
    "cam_TA1_delayreset", "cam_TA1_zero", "bin_full",
}
_INPUTS = {"interlock", "gp", "bs", "grippers"}


class FakeIO:
    """Recording io for replay. Inputs are settable levels; outputs are appended to
    `self.outputs` in the exact order the FSM emits them. Clock is injected via
    `set_now()` so the harness reproduces timing without sleeping."""

    def __init__(self):
        self._t = 0.0
        self.interlock = True
        self.gp = True
        self.bs = False
        self.grippers = 0
        self.outputs = []      # ordered control-output effects (the asserted surface)
        self.logs = []
        self.kicks = 0

    # injected clock
    def set_now(self, t):
        self._t = float(t)

    def now(self):
        return self._t

    # outputs (the FSM drives these) -> append in order
    def set_sweep(self, on):
        self.outputs.append(["sweep", bool(on)])

    def set_table(self, on):
        self.outputs.append(["table", bool(on)])

    def set_spot(self, on):
        self.outputs.append(["spot", bool(on)])

    def set_pin_lamps(self, mask):
        self.outputs.append(["pin_lamps", int(mask)])

    def set_light(self, name, on):
        self.outputs.append(["light", name, bool(on)])

    # inputs (the FSM reads these) -> current scripted level
    def read_grippers(self):
        return self.grippers

    def gp_closed(self):
        return self.gp

    def bs_closed(self):
        return self.bs

    def interlock_ok(self):
        return self.interlock

    # housekeeping
    def watchdog_kick(self):
        self.kicks += 1

    def log(self, msg):
        self.logs.append(msg)


def _apply_input(io, name, value):
    if name not in _INPUTS:
        raise ValueError(f"trace input name {name!r} not in {sorted(_INPUTS)}")
    if name == "grippers":
        io.grippers = int(value)
    else:
        setattr(io, name, bool(value))


def replay(trace, lane_id=21, golden=None):
    """Replay `trace` (a dict with 'events', or a list of event records) through a
    fresh CycleController + FakeIO. Returns (controller, io). If `golden` is given,
    assert the emitted output sequence + final state/ball match it (raises
    AssertionError on the first divergence, with an index-pinpointed message)."""
    events = trace["events"] if isinstance(trace, dict) else trace
    io = FakeIO()
    c = CycleController(lane_id, io)

    for i, rec in enumerate(events):
        kind = rec["kind"]
        if "t" in rec:
            io.set_now(rec["t"])
        if kind == "input":
            _apply_input(io, rec["name"], rec["value"])
        elif kind == "call":
            name = rec["name"]
            if name not in _CALLABLE:
                raise ValueError(f"event[{i}]: call {name!r} not in the FSM whitelist")
            getattr(c, name)()
        elif kind == "poll":
            c.poll()
        elif kind == "output":
            # Recorded outputs are descriptive only; replay re-derives them from the
            # FSM. Skip them on the input side.
            continue
        else:
            raise ValueError(f"event[{i}]: unknown kind {kind!r}")

    if golden is not None:
        _assert_golden(io, c, golden)
    return c, io


def _assert_golden(io, c, golden):
    exp = golden["outputs"]
    got = io.outputs
    # element-wise diff for a precise failure message
    n = min(len(exp), len(got))
    for i in range(n):
        # JSON round-trips tuples to lists; normalize both sides to lists.
        e = list(exp[i])
        g = list(got[i])
        if e != g:
            raise AssertionError(
                f"output[{i}] mismatch: expected {e!r}, got {g!r}\n"
                f"  full expected={exp}\n  full got    ={got}")
    if len(exp) != len(got):
        raise AssertionError(
            f"output length mismatch: expected {len(exp)} outputs, got {len(got)}\n"
            f"  expected={exp}\n  got     ={got}")
    fs = golden["final_state"]
    if c.state.value != fs:
        raise AssertionError(f"final state mismatch: expected {fs!r}, got {c.state.value!r}")
    fb = golden["final_ball"]
    if c.ball.name != fb:
        raise AssertionError(f"final ball mismatch: expected {fb!r}, got {c.ball.name!r}")


# ── recorder ──────────────────────────────────────────────────────────────────
# A daemon-side recorder is out of scope for this pure harness (it would touch
# controller_daemon.py, which is not ours to edit). Instead the build_*() helpers
# below generate self-consistent golden traces DERIVED FROM THE FSM ITSELF: we run
# a known event timeline through replay(), capture the outputs the live FSM emits,
# and freeze them as the golden. That makes the golden a faithful recording of
# current behavior, and any future FSM edit that changes the output sequence breaks
# the replay test — exactly the CI tripwire idea #9 asks for. Real-machine .jsonl
# traces captured on the spare cabinet drop into the same format and the same
# replay() with no code change.

def _events_first_ball_respot():
    """1st ball leaves 7+10 (0b0000000101) -> respot held pins -> ends READY/2nd ball.
    Mirrors run_cycle() in cycle_control_8270.__main__, timeline made explicit."""
    g = 0b0000000101
    return [
        {"t": 0.00, "kind": "call", "name": "power_restore"},
        {"t": 0.00, "kind": "call", "name": "first_ball_zero"},
        {"t": 0.00, "kind": "input", "name": "grippers", "value": g},
        {"t": 0.00, "kind": "call", "name": "on_ball"},          # READY -> SWEEP_TO_GUARD
        {"t": 0.60, "kind": "call", "name": "cam_SB_guard"},     # -> GUARD_DELAY (enter @0.60)
        {"t": 3.80, "kind": "poll"},                             # delay done (>=3.60) -> TABLE_DETECT
        {"t": 5.00, "kind": "call", "name": "cam_TA2_runthrough"},  # latch pins -> RUNTHROUGH
        {"t": 5.90, "kind": "call", "name": "cam_SA_runthrough"},   # -> TABLE_FINISH (respot)
        # table returns to zero: TA1 dual-trip = delayreset + zero
        {"t": 6.60, "kind": "call", "name": "cam_TA1_delayreset"},
        {"t": 7.30, "kind": "call", "name": "cam_TA1_zero"},     # respot done -> READY
        {"t": 7.35, "kind": "poll"},
    ]


def _events_strike():
    """1st ball, NO pins -> STRIKE -> fresh rack via SP -> ends READY/1st ball."""
    return [
        {"t": 0.00, "kind": "call", "name": "power_restore"},
        {"t": 0.00, "kind": "call", "name": "first_ball_zero"},
        {"t": 0.00, "kind": "input", "name": "grippers", "value": 0},
        {"t": 0.00, "kind": "call", "name": "on_ball"},
        {"t": 0.60, "kind": "call", "name": "cam_SB_guard"},    # -> GUARD_DELAY (enter @0.60)
        {"t": 3.80, "kind": "poll"},                             # delay done -> TABLE_DETECT
        {"t": 5.00, "kind": "call", "name": "cam_TA2_runthrough"},  # 0 pins -> STRIKE, runthrough
        {"t": 5.90, "kind": "call", "name": "cam_SA_runthrough"},   # -> TABLE_FINISH (await BS)
        {"t": 6.20, "kind": "input", "name": "bs", "value": True},
        {"t": 6.20, "kind": "call", "name": "bin_full"},        # BS -> SP, SPOTTING
        {"t": 6.90, "kind": "call", "name": "cam_TA1_delayreset"},
        {"t": 7.60, "kind": "call", "name": "cam_TA1_zero"},    # spotting done, SP off -> READY
        {"t": 7.65, "kind": "poll"},
    ]


def _events_foul():
    """1st-ball FOUL in the delivery window -> fresh-rack respot semantics ->
    ends READY/2nd ball (FOUL counts as the first delivery; ball memory -> SECOND)."""
    return [
        {"t": 0.00, "kind": "call", "name": "power_restore"},
        {"t": 0.00, "kind": "call", "name": "first_ball_zero"},
        {"t": 0.00, "kind": "input", "name": "grippers", "value": 0b0000000011},
        {"t": 0.00, "kind": "call", "name": "on_ball"},          # SWEEP_TO_GUARD (FIRST_BALL)
        {"t": 0.10, "kind": "call", "name": "on_foul"},          # in window -> cycle=FOUL
        {"t": 0.60, "kind": "call", "name": "cam_SB_guard"},    # -> GUARD_DELAY (enter @0.60)
        {"t": 3.80, "kind": "poll"},                             # delay done -> TABLE_DETECT
        {"t": 5.00, "kind": "call", "name": "cam_TA2_runthrough"},
        {"t": 5.90, "kind": "call", "name": "cam_SA_runthrough"},   # FOUL = fresh rack -> await BS
        {"t": 6.20, "kind": "input", "name": "bs", "value": True},
        {"t": 6.20, "kind": "call", "name": "bin_full"},        # SP -> SPOTTING
        {"t": 6.90, "kind": "call", "name": "cam_TA1_delayreset"},
        {"t": 7.60, "kind": "call", "name": "cam_TA1_zero"},    # -> READY (ball -> SECOND)
        {"t": 7.65, "kind": "poll"},
    ]


_BUILDERS = {
    "first_ball_respot": _events_first_ball_respot,
    "strike": _events_strike,
    "foul": _events_foul,
}


def build_golden(name):
    """Run a builder's event timeline through the live FSM and freeze the resulting
    outputs/final-state as a golden dict (self-consistent by construction)."""
    events = _BUILDERS[name]()
    c, io = replay(events, golden=None)
    return {
        "meta": {"name": name, "derived_from": "cycle_control_8270 FSM (self-consistent)"},
        "events": events,
        "golden": {
            "final_state": c.state.value,
            "final_ball": c.ball.name,
            "outputs": io.outputs,
        },
    }


def write_fixtures():
    """(Re)generate the golden trace fixtures in tests/fixtures/."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    written = []
    for name in _BUILDERS:
        doc = build_golden(name)
        p = FIXTURES / f"trace_{name}.json"
        p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        written.append(p)
    return written


def load_fixture(name):
    p = FIXTURES / f"trace_{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def replay_fixture(name, lane_id=21):
    """Load a fixture {events, golden} and assert the live FSM reproduces it."""
    doc = load_fixture(name)
    return replay(doc["events"], lane_id=lane_id, golden=doc["golden"])


# ── selftest ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    regen = "--write" in sys.argv or os.environ.get("TRACE_REPLAY_WRITE")
    if regen:
        paths = write_fixtures()
        print(f"wrote {len(paths)} golden fixtures:")
        for p in paths:
            print(f"  {p}")

    # A missing golden is a hard FAILURE, never an auto-regen: regenerating from
    # the live FSM and then "verifying" the FSM against the just-written fixture
    # is a guaranteed self-blessing pass — a checkout/packaging problem (or an
    # FSM regression plus a deleted fixture) would silently defeat the tripwire.
    missing = [n for n in _BUILDERS if not (FIXTURES / f"trace_{n}.json").exists()]
    if missing:
        print("FAIL missing golden fixture(s): "
              + ", ".join(f"trace_{n}.json" for n in missing))
        print(f"     expected in: {FIXTURES}")
        print("     Goldens are checked in and must come from the repo — this")
        print("     selftest will NOT regenerate them. If you deliberately intend")
        print("     to re-freeze current FSM behavior as the new golden, run:")
        print("         py -3 lane_node/trace_replay.py --write")
        sys.exit(1)

    fails = []
    for name in _BUILDERS:
        try:
            c, io = replay_fixture(name)
            print(f"ok   replay {name:18s} -> state={c.state.value} ball={c.ball.name} "
                  f"({len(io.outputs)} outputs, {io.kicks} kicks)")
        except AssertionError as e:
            print(f"FAIL replay {name:18s}\n     {e}")
            fails.append(name)

    # A trace must be self-consistent: replaying twice yields identical outputs.
    doc = load_fixture("strike")
    _, io1 = replay(doc["events"])
    _, io2 = replay(doc["events"])
    if io1.outputs != io2.outputs:
        fails.append("determinism")
        print("FAIL replay is not deterministic")
    else:
        print("ok   replay is deterministic (strike replayed twice = identical outputs)")

    print()
    print("ALL trace-replay CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}")
    sys.exit(1 if fails else 0)
