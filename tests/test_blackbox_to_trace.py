"""Tests for lane_node/blackbox_to_trace.py — FlightRecorder blackbox dump ->
trace_replay trace converter (the named Layer-2 gap in
docs/phase8_diagnostics_scope_2026-07-19.md §2).

The synthetic dumps are built via FlightRecorder's OWN record()/dump() APIs,
fed by a rig that drives the real CycleController and mirrors the production
recorder taps exactly (controller_io RecordingIO 'out' records during the
call, controller_daemon._observe 'state' records after — same order, same
schema). So the dump under test IS the production dump format, and the
converter's output is verified by replaying it through the live FSM
(trace_replay.replay).

Hardware-free: FSM + recorder + replay are pure software. Run standalone with:
    py -3 tests/test_blackbox_to_trace.py
"""
import json
import os
import sys
import tempfile

# Make lane_node modules importable when running from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

import blackbox_to_trace as b2t
import trace_replay
from blackbox_to_trace import ConvertError, convert, main
from cycle_control_8270 import CycleController, MAX_MOTION_S, State
from flight_recorder import FlightRecorder


# ---------------------------------------------------------------------------
# rig: real FSM + real FlightRecorder, production-shaped taps
# ---------------------------------------------------------------------------
class RecIO:
    """FakeIO for the FSM that taps the FlightRecorder exactly like the
    production io does: an 'out' record per output set (RecordingIO pattern —
    names S/T/SP/pin_lamps/<light>)."""

    def __init__(self, recorder, clk):
        self.recorder = recorder
        self._clk = clk
        self.grippers = 0
        self.gp = True
        self.bs = False
        self.interlock = True
        self.kicks = 0
        self.logs = []

    def now(self):
        return self._clk["t"]

    def log(self, m):
        self.logs.append(m)

    def set_sweep(self, on):
        self.recorder.record("out", "S", bool(on))

    def set_table(self, on):
        self.recorder.record("out", "T", bool(on))

    def set_spot(self, on):
        self.recorder.record("out", "SP", bool(on))

    def set_pin_lamps(self, mask):
        self.recorder.record("out", "pin_lamps", int(mask))

    def set_light(self, name, on):
        self.recorder.record("out", name, bool(on))

    def read_grippers(self):
        return self.grippers

    def gp_closed(self):
        return self.gp

    def bs_closed(self):
        return self.bs

    def interlock_ok(self):
        return self.interlock

    def watchdog_kick(self):
        self.kicks += 1


class Rig:
    """Drives a real CycleController; after each step, mirrors
    controller_daemon._observe's ('state', new, prev) tap. Like production,
    the initial power_restore is NOT recorded (the daemon baselines
    _prev_state after calling it)."""

    def __init__(self, lane=21, capacity=2000):
        self.dir = tempfile.mkdtemp(prefix="b2t_dump_")
        self.clk = {"t": 100.0}
        self.fr = FlightRecorder(lane, capacity=capacity, dump_dir=self.dir,
                                 now=lambda: self.clk["t"], enabled=True)
        self.io = RecIO(self.fr, self.clk)
        self.c = CycleController(lane, self.io)
        self.c.power_restore()
        self._prev = self.c.state          # baseline AFTER power_restore (as the daemon does)

    def obs(self):
        new = self.c.state
        if new is not self._prev:
            self.fr.record("state", new.value, self._prev.value)
            self._prev = new

    def step(self, dt, fn=None):
        """Advance the clock, run one tick's worth of calls, observe."""
        self.clk["t"] = round(self.clk["t"] + dt, 3)
        if fn is not None:
            fn()
        self.obs()

    def sa_edge(self):
        """One physical SA cam edge = both sub-calls (rp2040_link.dispatch_cam)."""
        self.c.cam_SA_runthrough()
        self.c.cam_SA_zero()

    def ta1_edge(self):
        self.c.cam_TA1_delayreset()
        self.c.cam_TA1_zero()

    def dump(self, reason="fsm_fault"):
        path = self.fr.dump(reason=reason, extra={"fsm_state": self.c.state.value})
        assert path is not None
        with open(path, encoding="utf-8") as f:
            return path, json.load(f)


def drive_ready(r):
    r.step(1.0, r.c.first_ball_zero)                      # MI -> READY


def drive_strike(r):
    """1st ball, no pins: STRIKE -> fresh rack via BS/SP -> READY."""
    r.io.grippers = 0
    r.step(5.0, r.c.on_ball)                              # READY -> SWEEP_TO_GUARD
    r.step(0.6, r.c.cam_SB_guard)                         # -> GUARD_DELAY
    r.step(3.4, r.c.poll)                                 # settle done -> TABLE_DETECT
    r.step(1.2, r.c.cam_TA2_runthrough)                   # -> RUNTHROUGH (strike latched)
    r.step(0.9, r.sa_edge)                                # -> TABLE_FINISH (await BS)
    def _bs():
        r.io.bs = True
        r.c.bin_full()
    r.step(0.3, _bs)                                      # -> SPOTTING (SP + table)
    r.step(1.4, r.ta1_edge)                               # -> READY


def drive_respot(r, mask=0b0000000101):
    """1st ball with pins left: respot held pins -> READY (2nd ball)."""
    r.io.grippers = mask
    r.step(5.0, r.c.on_ball)
    r.step(0.6, r.c.cam_SB_guard)
    r.step(3.4, r.c.poll)
    r.step(1.2, r.c.cam_TA2_runthrough)
    r.step(0.9, r.sa_edge)                                # -> TABLE_FINISH (respot)
    r.step(0.7, r.ta1_edge)                               # -> READY (same-tick T-off + finish)


def drive_timeout_fault(r):
    r.step(5.0, r.c.on_ball)                              # READY -> SWEEP_TO_GUARD
    r.step(MAX_MOTION_S + 1.0, r.c.poll)                  # backstop -> FAULT


# ---------------------------------------------------------------------------
# [A] full dump: strike + respot + motion-timeout fault, round-tripped
# ---------------------------------------------------------------------------
def test_full_dump_roundtrip():
    r = Rig()
    drive_ready(r)
    drive_strike(r)
    drive_respot(r)
    drive_timeout_fault(r)
    assert r.c.state is State.FAULT
    _path, doc = r.dump()

    trace_doc, report = convert(doc, source="test")
    assert report["gaps"] == [], report["gaps"]
    assert report["verified"] is True, report["verify_error"]
    assert report["expected_final_state"] == "fault"
    assert report["states_converted"] >= 10

    # independent replay of the produced trace through the live FSM
    c, io = trace_replay.replay(trace_doc["events"], lane_id=doc["lane"])
    assert c.state is State.FAULT
    outs = io.outputs
    assert ["spot", True] in [list(o) for o in outs], "strike spotting (SP) reproduced"
    assert ["sweep", True] in [list(o) for o in outs]
    # respot mask recovered from the pin_lamps record, not guessed
    grip_inputs = [e for e in trace_doc["events"]
                   if e["kind"] == "input" and e.get("name") == "grippers"]
    assert any(e["value"] == 0b0000000101 for e in grip_inputs), grip_inputs
    # dual-trip cams emitted as both sub-calls (dispatch_cam contract)
    calls = [e["name"] for e in trace_doc["events"] if e["kind"] == "call"]
    assert "cam_SA_runthrough" in calls and "cam_SA_zero" in calls
    assert "cam_TA1_delayreset" in calls and "cam_TA1_zero" in calls


# ---------------------------------------------------------------------------
# [B] ring-truncated dump (mid-cycle start) -> synthetic preamble
# ---------------------------------------------------------------------------
def test_midcycle_dump_gets_preamble():
    r = Rig(capacity=10)                   # small ring: early events evicted
    drive_ready(r)
    drive_strike(r)
    drive_respot(r, mask=0b0000001000)     # mask deliberately != RESPOT_MASK
    _path, doc = r.dump(reason="soak_snapshot")
    assert doc["event_count"] == 10

    trace_doc, report = convert(doc)
    assert report["verified"] is True, (report["verify_error"], report["gaps"])
    c, _io = trace_replay.replay(trace_doc["events"])
    assert c.state is State.READY
    # the trace must start earlier than the dump window (the preamble)
    assert trace_doc["events"][0]["t"] < doc["events"][0]["t"]
    assert trace_doc["events"][0] == {"t": trace_doc["events"][0]["t"],
                                      "kind": "call", "name": "power_restore"}


# ---------------------------------------------------------------------------
# [C] silent TA1-during-RUNTHROUGH edge synthesized from the T-off record
# ---------------------------------------------------------------------------
def test_ta1_during_runthrough_synthesis():
    r = Rig()
    drive_ready(r)
    r.io.grippers = 0b0000001000
    r.step(5.0, r.c.on_ball)
    r.step(0.6, r.c.cam_SB_guard)
    r.step(3.4, r.c.poll)
    r.step(1.2, r.c.cam_TA2_runthrough)
    r.step(0.5, r.ta1_edge)                # table zero DURING run-through: T-off, NO state rec
    assert r.c.state is State.RUNTHROUGH
    r.step(0.4, r.sa_edge)                 # sweep stop completes -> READY (one composite rec)
    assert r.c.state is State.READY
    _path, doc = r.dump(reason="cycle_ok")

    trace_doc, report = convert(doc)
    assert report["verified"] is True, (report["verify_error"], report["gaps"])
    calls = [e["name"] for e in trace_doc["events"] if e["kind"] == "call"]
    # the synthesized TA1 pair must precede the SA pair that completes the cycle
    assert calls.index("cam_TA1_zero") < calls.index("cam_SA_runthrough")
    c, _io = trace_replay.replay(trace_doc["events"])
    assert c.state is State.READY


# ---------------------------------------------------------------------------
# [D] interlock-caused fault (not provable as a timeout) + PBZ recovery
# ---------------------------------------------------------------------------
def test_interlock_fault_and_pbz_recovery():
    r = Rig()
    drive_ready(r)
    r.step(5.0, r.c.on_ball)
    def _trip():
        r.io.interlock = False
        r.c.poll()                         # mid-motion re-check -> FAULT at t-entry < 8s
    r.step(1.0, _trip)
    assert r.c.state is State.FAULT
    r.io.interlock = True
    r.step(2.0, r.c.first_ball_zero)       # FAULT -> MANUAL_INTERVENTION
    r.step(2.0, r.c.first_ball_zero)       # -> READY
    assert r.c.state is State.READY
    _path, doc = r.dump(reason="recovered")

    trace_doc, report = convert(doc)
    assert report["verified"] is True, (report["verify_error"], report["gaps"])
    # the fault was reproduced via a scripted interlock dip (then restored)
    dips = [e for e in trace_doc["events"]
            if e["kind"] == "input" and e.get("name") == "interlock"]
    assert [e["value"] for e in dips] == [False, True]
    c, _io = trace_replay.replay(trace_doc["events"])
    assert c.state is State.READY


# ---------------------------------------------------------------------------
# [E] second-ball parity fix + fresh-rack TA1 park in TABLE_FINISH
# ---------------------------------------------------------------------------
def test_second_ball_parity_and_table_park():
    r = Rig()
    drive_ready(r)
    r.step(1.0, r.c.first_ball_zero)       # PBZ toggle in READY -> 2nd ball (NO state rec)
    r.io.grippers = 0b0000000011           # pins standing, but SECOND ball = fresh rack
    r.step(5.0, r.c.on_ball)
    r.step(0.6, r.c.cam_SB_guard)
    r.step(3.4, r.c.poll)
    r.step(1.2, r.c.cam_TA2_runthrough)
    r.step(0.9, r.sa_edge)                 # -> TABLE_FINISH (fresh: await BS)
    r.step(0.7, r.ta1_edge)                # table parks at zero: T-off, NO state rec
    assert r.c.state is State.TABLE_FINISH
    def _bs():
        r.io.bs = True
        r.c.bin_full()
    r.step(0.5, _bs)                       # -> SPOTTING (re-energizes table)
    r.step(1.4, r.ta1_edge)                # -> READY
    assert r.c.state is State.READY
    _path, doc = r.dump(reason="second_ball")

    trace_doc, report = convert(doc)
    assert report["verified"] is True, (report["verify_error"], report["gaps"])
    calls = [e["name"] for e in trace_doc["events"] if e["kind"] == "call"]
    # parity fix: preamble PBZ + a READY toggle PBZ before on_ball
    assert calls.count("first_ball_zero") == 2
    assert calls.index("on_ball") > [i for i, n in enumerate(calls)
                                     if n == "first_ball_zero"][-1]
    c, _io = trace_replay.replay(trace_doc["events"])
    assert c.state is State.READY


# ---------------------------------------------------------------------------
# [F] unusable / partially-convertible dumps fail loudly, not silently
# ---------------------------------------------------------------------------
def test_no_state_records_raises():
    doc = {"lane": 21, "events": [{"t": 1.0, "kind": "out", "name": "S", "value": True}]}
    try:
        convert(doc)
    except ConvertError:
        pass
    else:
        raise AssertionError("a dump with no state records must raise ConvertError")


def test_bad_shape_raises():
    for bad in ({"lane": 21}, {"events": "nope"}, {"events": [{"t": 1}]}):
        try:
            convert(bad)
        except ConvertError:
            continue
        raise AssertionError(f"{bad!r} must raise ConvertError")


def test_bench_gated_transition_is_a_gap():
    doc = {"lane": 21, "events": [
        {"t": 50.0, "kind": "state", "name": "runthrough", "value": "guard_delay"},
    ]}
    _trace_doc, report = convert(doc)
    assert report["gaps"], "bench-gated skip-descent must be reported as a gap"
    assert report["verified"] is False


def test_skipped_kinds_are_counted():
    r = Rig()
    drive_ready(r)
    r.fr.record("cam_timing", "cycle1", {"ss_to_guard": 0.6})
    r.fr.record("tick_error", "RuntimeError", "boom")
    r.fr.record("arm", "arm", True)
    _path, doc = r.dump(reason="mixed")
    _trace_doc, report = convert(doc)
    assert report["skipped_kinds"] == {"cam_timing": 1, "tick_error": 1, "arm": 1}
    assert report["verified"] is True


# ---------------------------------------------------------------------------
# [G] CLI
# ---------------------------------------------------------------------------
def test_cli_roundtrip_and_exit_codes():
    r = Rig()
    drive_ready(r)
    drive_strike(r)
    drive_timeout_fault(r)
    dump_path, _doc = r.dump()
    out_path = os.path.join(r.dir, "out.trace")
    assert main([dump_path, out_path]) == 0
    with open(out_path, encoding="utf-8") as f:
        trace_doc = json.load(f)
    assert trace_doc["meta"]["verified"] is True
    assert trace_doc["meta"]["converter"].startswith("blackbox_to_trace")
    c, _io = trace_replay.replay(trace_doc["events"])
    assert c.state is State.FAULT

    # unusable dump -> 1
    bad_path = os.path.join(r.dir, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as f:
        json.dump({"lane": 21, "events": []}, f)
    assert main([bad_path, out_path]) == 1

    # gap dump -> 2 strict, 0 with --lenient
    gap_path = os.path.join(r.dir, "gap.json")
    with open(gap_path, "w", encoding="utf-8") as f:
        json.dump({"lane": 21, "events": [
            {"t": 50.0, "kind": "state", "name": "runthrough", "value": "guard_delay"},
        ]}, f)
    gap_out = os.path.join(r.dir, "gap.trace")
    assert main([gap_path, gap_out]) == 2
    assert main([gap_path, gap_out, "--lenient"]) == 0

    # usage / missing file -> 1
    assert main([]) == 1
    assert main([os.path.join(r.dir, "missing.json"), out_path]) == 1


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fails = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
