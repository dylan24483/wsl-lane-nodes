"""test_fsm_diagnostics.py — R3 diagnostics hardening of the 8270 cycle-control FSM
(2026-07-19 diagnostics scope, Phase 1).

Covers, hardware-free (RecordingIO only, no smbus2/gpiozero):
  * structured fault codes on EVERY _fault() call site + backward-compat _fault(why)
  * per-motor CONTINUOUS energized-time tracking + the H-02 overrun trip
    (trip at threshold across state transitions; NO trip on the longest legal
    cycle at realistic timings; env kill-switch)
  * unexpected-edge observers: per-(event,state) counters, zero noise on a
    direct-handler legal cycle, the documented dual-trip artifact keys
  * diagnostics_snapshot() shape + copy semantics
  * on_diag hook delivery + exception swallowing (drop counter, state untouched)

Run under pytest (py -m pytest tests/test_fsm_diagnostics.py) or standalone
(py -3 tests/test_fsm_diagnostics.py).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

import cycle_control_8270 as cc
from cycle_control_8270 import (  # noqa: E402
    CycleController, State, Ball, TIME_DELAY_S, MAX_MOTION_S, GUARD_DELAY_MAX_S,
    MAX_MOTOR_ENERGIZED_S, MOTOR_OVERRUN_TRIP_ENV, DIAG_ENV)
from controller_io import RecordingIO  # noqa: E402


# ── builders (mirror tests/test_fsm_legality_matrix.py) ─────────────────────────

def _new():
    io = RecordingIO()
    c = CycleController(21, io)
    return c, io


def at_ready():
    c, io = _new()
    c.power_restore()
    c.first_ball_zero()
    return c, io


def at_sweep_to_guard(grippers=0b0000000101):
    c, io = at_ready()
    io.grippers = grippers
    c.on_ball()
    return c, io


def at_guard_delay():
    c, io = at_sweep_to_guard()
    c.cam_SB_guard()
    return c, io


def at_table_detect():
    c, io = at_guard_delay()
    io.advance(TIME_DELAY_S + 0.1)
    c.poll()
    return c, io


def at_runthrough(grippers=0b0000000101):
    c, io = at_ready()
    io.grippers = grippers
    c.on_ball()
    c.cam_SB_guard()
    io.advance(TIME_DELAY_S + 0.1)
    c.poll()
    c.cam_TA2_runthrough()
    return c, io


def at_table_finish_respot():
    c, io = at_runthrough(grippers=0b0000000101)
    c.cam_SA_runthrough()
    return c, io


def at_table_finish_freshrack():
    c, io = at_ready()
    io.grippers = 0
    c.on_ball()
    c.cam_SB_guard()
    io.advance(TIME_DELAY_S + 0.1)
    c.poll()
    c.cam_TA2_runthrough()   # 0 pins -> STRIKE
    c.cam_SA_runthrough()    # -> TABLE_FINISH (fresh rack, awaiting BS)
    return c, io


def at_spotting():
    c, io = at_table_finish_freshrack()
    io.bs = True
    c.bin_full()
    return c, io


MOTION_BUILDERS = {
    State.SWEEP_TO_GUARD: at_sweep_to_guard,
    State.TABLE_DETECT:   at_table_detect,
    State.RUNTHROUGH:     at_runthrough,
    State.TABLE_FINISH:   at_table_finish_respot,
    State.SPOTTING:       at_spotting,
}


def _motor_on_events(io, start_idx):
    return [e for e in io.events[start_idx:]
            if e[0] in ("sweep", "table", "spot") and e[1] is True]


# ── 1. structured fault codes ───────────────────────────────────────────────────

def test_fault_code_motion_timeout_each_motion_state():
    for st, builder in MOTION_BUILDERS.items():
        c, io = builder()
        assert c.state is st, f"builder for {st} reached {c.state}"
        io.advance(MAX_MOTION_S + 0.2)
        c.poll()
        assert c.state is State.FAULT
        lf = c.last_fault
        assert lf["code"] == f"motion_timeout:{st.name}", lf
        assert lf["state"] == st.value
        assert str(MAX_MOTION_S) in lf["why"]


def test_fault_code_guard_delay_timeout():
    c, io = at_guard_delay()
    io.gp = False
    io.advance(GUARD_DELAY_MAX_S + 0.2)
    c.poll()
    assert c.state is State.FAULT
    assert c.last_fault["code"] == "guard_delay_timeout"
    assert c.last_fault["state"] == State.GUARD_DELAY.value


def test_fault_code_interlock_open_mid_motion():
    for st, builder in MOTION_BUILDERS.items():
        c, io = builder()
        io.interlock = False
        c.poll()
        assert c.state is State.FAULT
        assert c.last_fault["code"] == f"interlock_open:{st.name}", c.last_fault
        assert c.last_fault["state"] == st.value


def test_fault_code_refused_energize_sweep():
    # TA2@260 with the interlock open: _safe_sweep refuses -> FAULT
    c, io = at_table_detect()
    io.interlock = False
    c.cam_TA2_runthrough()
    assert c.state is State.FAULT
    assert c.last_fault["code"] == "refused_energize:sweep"
    assert c.last_fault["state"] == State.TABLE_DETECT.value


def test_fault_code_refused_energize_table():
    # bin_full's own interlock gate passes, then _safe_table's re-check fails:
    # script interlock_ok() to return True once, then False.
    c, io = at_table_finish_freshrack()
    seq = [True]
    io.interlock_ok = lambda: seq.pop(0) if seq else False   # instance shadow
    io.bs = True
    c.bin_full()
    assert c.state is State.FAULT
    assert c.last_fault["code"] == "refused_energize:table"
    assert io.outputs["spot"] is False, "SP must never stay latched on the refusal"


def test_fault_backward_compat_free_text_only():
    # external callers may still pass free text alone — must not raise, must latch
    c, io = at_ready()
    c._fault("legacy free-text reason")
    assert c.state is State.FAULT
    assert c.last_fault["code"] == "unspecified"
    assert c.last_fault["why"] == "legacy free-text reason"


def test_last_fault_shape():
    c, io = at_sweep_to_guard()
    io.advance(MAX_MOTION_S + 0.2)
    t_before = io.now()
    c.poll()
    lf = c.last_fault
    assert set(lf.keys()) == {"code", "why", "state", "t"}
    assert lf["state"] == State.SWEEP_TO_GUARD.value   # the state it fired IN
    assert lf["t"] == t_before
    # snapshot returns a COPY — mutating it must not corrupt the FSM's record
    snap = c.diagnostics_snapshot()
    snap["last_fault"]["code"] = "tampered"
    assert c.last_fault["code"] != "tampered"


# ── 2. H-02: per-motor energized-time overrun ───────────────────────────────────

def test_h02_trip_across_state_transitions():
    # table energized continuously across TABLE_DETECT -> RUNTHROUGH ->
    # TABLE_FINISH; every state stays under MAX_MOTION_S (the per-state timer
    # never fires — that reset is the H-02 bug) but the continuous run crosses
    # MAX_MOTOR_ENERGIZED_S -> FAULT with the sanctioned code.
    c, io = at_table_detect()             # table ON here
    io.advance(6.0); c.poll()
    assert c.state is State.TABLE_DETECT  # 6s < 8s: no per-state fault
    c.cam_TA2_runthrough()                # timer resets; table stays energized
    io.advance(6.0); c.poll()             # 12s continuous < 15s: still no trip
    assert c.state is State.RUNTHROUGH
    c.cam_SA_runthrough()                 # timer resets again; table still on
    io.advance(4.0); c.poll()             # 16s continuous > 15s ceiling
    assert c.state is State.FAULT, "H-02 overrun must latch FAULT"
    assert c.last_fault["code"] == "motor_energized_overrun:table"
    assert io.outputs["table"] is False and io.outputs["sweep"] is False
    snap = c.diagnostics_snapshot()
    assert snap["motor_energized_s"]["table"] == 0.0   # window closed by FAULT
    assert snap["motor_longest_run_s"]["table"] > MAX_MOTOR_ENERGIZED_S


def test_h02_no_trip_on_longest_legal_cycle():
    # The WORST-CASE LEGAL cycle at realistic (12.1 RPM-scaled) timings: strike,
    # BS closes while the table is still running, so the table stays energized
    # from descent straight through the spotting revolution (~9.9 s continuous
    # — the longest legal run the derivation comment documents). Must complete
    # READY with NO fault.
    c, io = _new()
    c.power_restore(); c.first_ball_zero()
    io.grippers = 0
    c.on_ball()                                   # t=0: sweep on
    io.advance(0.9); c.poll(); c.cam_SB_guard()   # t=0.9 -> GUARD_DELAY
    io.advance(3.1); c.poll()                     # t=4.0 -> TABLE_DETECT (table ON)
    for _ in range(3):
        io.advance(1.0); c.poll()                 # t=5,6,7 — checker gets its chances
    io.advance(0.6); c.poll()
    c.cam_TA2_runthrough()                        # t=7.6 (descent 3.6s) -> RUNTHROUGH
    io.advance(1.3); c.poll()
    c.cam_SA_runthrough()                         # t=8.9 -> TABLE_FINISH (table still on)
    io.advance(0.3)
    io.bs = True
    c.bin_full()                                  # t=9.2 -> SPOTTING (window continuous)
    for _ in range(4):
        io.advance(1.0); c.poll()                 # t=10..13
    io.advance(0.7)
    c.cam_TA1_zero()                              # t=13.9: table off after 9.9s continuous
    c.poll()
    assert c.state is State.READY, f"legal cycle must complete (got {c.state})"
    assert c.last_fault is None
    longest = c.diagnostics_snapshot()["motor_longest_run_s"]["table"]
    assert 9.5 < longest < 10.5, longest
    # and the default clears that longest legal run by a generous margin
    assert longest * 1.5 <= MAX_MOTOR_ENERGIZED_S


def test_h02_killswitch_reverts_to_observe_only():
    old = os.environ.get(MOTOR_OVERRUN_TRIP_ENV)
    os.environ[MOTOR_OVERRUN_TRIP_ENV] = "0"
    try:
        c, io = at_table_detect()
        io.advance(6.0); c.poll()
        c.cam_TA2_runthrough()
        io.advance(6.0); c.poll()
        c.cam_SA_runthrough()
        io.advance(6.0); c.poll()                 # 18s continuous — would trip
        assert c.state is not State.FAULT, "kill-switch must suppress the trip"
        # tracking stays live (observe-only)
        assert c.diagnostics_snapshot()["motor_energized_s"]["table"] > MAX_MOTOR_ENERGIZED_S
    finally:
        if old is None:
            os.environ.pop(MOTOR_OVERRUN_TRIP_ENV, None)
        else:
            os.environ[MOTOR_OVERRUN_TRIP_ENV] = old


def test_h02_threshold_is_runtime_tunable():
    # the check reads the module global at call time, so the env-seeded constant
    # (WSL_FSM_MAX_MOTOR_ENERGIZED_S at import) is also patchable for the FIELD
    # retune path — verify a tightened ceiling trips a shorter cross-state run.
    old = cc.MAX_MOTOR_ENERGIZED_S
    cc.MAX_MOTOR_ENERGIZED_S = 2.0
    try:
        c, io = at_table_detect()
        io.advance(1.5); c.poll()
        assert c.state is State.TABLE_DETECT
        c.cam_TA2_runthrough()
        io.advance(1.0); c.poll()                 # 2.5s continuous > 2.0
        assert c.state is State.FAULT
        assert c.last_fault["code"] == "motor_energized_overrun:table"
    finally:
        cc.MAX_MOTOR_ENERGIZED_S = old


def test_h02_spot_window_latch_semantics():
    # bin_full on a still-running table is a latch no-op: the window must NOT
    # reset (resetting it would re-open the exact H-02 blindness).
    c, io = at_table_finish_freshrack()           # table energized since TABLE_DETECT
    t_on = c._energized_since["table"]
    io.advance(1.0)
    io.bs = True
    c.bin_full()                                  # re-energize = latch no-op
    assert c._energized_since["table"] == t_on, "on->on must not reset the window"
    assert c._energized_since["spot"] is not None


# ── 3. unexpected-edge observers ────────────────────────────────────────────────

def test_unexpected_edge_counts_and_state_untouched():
    c, io = at_ready()
    idx = len(io.events)
    c.cam_SB_guard()
    c.cam_SB_guard()
    assert c.state is State.READY
    assert c.diag_counters == {"cam_SB_guard:ready": 2}
    assert not _motor_on_events(io, idx), "observer must never drive a motor"


def test_unexpected_edge_every_handler():
    # every state-guarded handler counts in an at-rest state
    c, io = at_ready()
    c.cam_SB_guard()
    c.cam_TA2_runthrough()
    c.cam_SA_runthrough()
    c.cam_SA_zero()
    c.cam_TA1_delayreset()
    c.cam_TA1_zero()
    c.bin_full()
    expected = {f"{n}:ready": 1 for n in (
        "cam_SB_guard", "cam_TA2_runthrough", "cam_SA_runthrough",
        "cam_SA_zero", "cam_TA1_delayreset", "cam_TA1_zero", "bin_full")}
    assert c.diag_counters == expected
    # on_ball counts in a NON-READY state (continuous-cycling signature)…
    c2, io2 = at_sweep_to_guard()
    c2.on_ball()
    assert c2.diag_counters.get("on_ball:sweep_to_guard") == 1
    # …and PBZ mid-motion counts (mechanic-at-machine signal)
    c2.first_ball_zero()
    assert c2.diag_counters.get("first_ball_zero:sweep_to_guard") == 1
    assert c2.state is State.SWEEP_TO_GUARD


def test_legal_cycle_direct_handlers_zero_noise():
    # a legal strike cycle driven exactly like the sim (single-handler calls)
    # must produce ZERO unexpected-edge counts
    c, io = at_spotting()
    c.cam_TA1_zero()
    assert c.state is State.READY
    assert c.diag_counters == {}


def test_dualtrip_dispatch_artifact_keys():
    # a legal strike cycle driven the way rp2040_link.dispatch_cam actually does
    # it (BOTH angle-variants per physical SA/TA1 edge) produces EXACTLY the two
    # documented artifact keys — the per-key noise floor consumers baseline.
    c, io = at_ready()
    io.grippers = 0
    c.on_ball()
    c.cam_SB_guard()                              # SB@66 (single)
    io.advance(TIME_DELAY_S + 0.1); c.poll()      # -> TABLE_DETECT
    c.cam_TA1_delayreset(); c.cam_TA1_zero()      # physical TA1@185 lobe (pair)
    c.cam_TA2_runthrough()                        # TA2@260 -> RUNTHROUGH
    c.cam_SA_runthrough(); c.cam_SA_zero()        # physical SA@270 lobe (pair)
    c.cam_SA_runthrough(); c.cam_SA_zero()        # physical SA@360 lobe (pair)
    io.bs = True
    c.bin_full()                                  # -> SPOTTING
    c.cam_TA1_delayreset(); c.cam_TA1_zero()      # physical TA1@355 lobe (pair)
    assert c.state is State.READY
    assert c.diag_counters == {
        "cam_TA1_zero:table_detect": 1,           # @185 lobe during the descent
        "cam_SA_runthrough:table_finish": 1,      # @360 lobe on the sweep return
    }


def test_diag_killswitch():
    old = os.environ.get(DIAG_ENV)
    os.environ[DIAG_ENV] = "0"
    try:
        c, io = at_ready()
        seen = []
        c.on_diag = seen.append
        c.cam_SB_guard()
        assert c.diag_counters == {}
        assert seen == []
        assert c.state is State.READY
    finally:
        if old is None:
            os.environ.pop(DIAG_ENV, None)
        else:
            os.environ[DIAG_ENV] = old


# ── 4. diagnostics_snapshot ─────────────────────────────────────────────────────

def test_snapshot_shape_and_copy_semantics():
    c, io = at_ready()
    snap = c.diagnostics_snapshot()
    assert set(snap.keys()) == {"counters", "motor_energized_s",
                                "motor_longest_run_s", "last_fault", "diag_drops"}
    for k in ("motor_energized_s", "motor_longest_run_s"):
        assert set(snap[k].keys()) == {"sweep", "table", "spot"}
    assert snap["last_fault"] is None
    assert snap["diag_drops"] == 0
    # counters dict is a copy
    snap["counters"]["fake:key"] = 99
    assert c.diag_counters == {}


def test_snapshot_live_energized_seconds():
    c, io = at_sweep_to_guard()                   # sweep energized at t
    io.advance(2.5)
    snap = c.diagnostics_snapshot()
    assert abs(snap["motor_energized_s"]["sweep"] - 2.5) < 1e-9
    assert snap["motor_energized_s"]["table"] == 0.0
    # longest reflects the still-open run too
    assert abs(snap["motor_longest_run_s"]["sweep"] - 2.5) < 1e-9
    c.cam_SB_guard()                              # sweep off -> window closes
    snap2 = c.diagnostics_snapshot()
    assert snap2["motor_energized_s"]["sweep"] == 0.0
    assert abs(snap2["motor_longest_run_s"]["sweep"] - 2.5) < 1e-9


# ── 5. on_diag hook ─────────────────────────────────────────────────────────────

def test_on_diag_delivery_unexpected_edge():
    c, io = at_ready()
    seen = []
    c.on_diag = seen.append
    io.advance(1.25)
    c.cam_TA2_runthrough()
    assert len(seen) == 1
    ev = seen[0]
    assert ev["kind"] == "unexpected_edge"
    assert ev["event"] == "cam_TA2_runthrough"
    assert ev["state"] == "ready"
    assert ev["lane"] == 21
    assert ev["count"] == 1
    assert ev["t"] == io.now()


def test_on_diag_delivery_fault():
    c, io = at_sweep_to_guard()
    seen = []
    c.on_diag = seen.append
    io.advance(MAX_MOTION_S + 0.2)
    c.poll()
    faults = [e for e in seen if e["kind"] == "fault"]
    assert len(faults) == 1
    ev = faults[0]
    assert ev["code"] == "motion_timeout:SWEEP_TO_GUARD"
    assert ev["state"] == "sweep_to_guard"
    assert ev["lane"] == 21
    assert "why" in ev and "t" in ev


def test_on_diag_exception_swallowed():
    c, io = at_ready()

    def bad_hook(ev):
        raise RuntimeError("boom")
    c.on_diag = bad_hook
    c.cam_SB_guard()                              # must NOT raise
    assert c.state is State.READY
    assert c.diag_counters == {"cam_SB_guard:ready": 1}   # counting still happened
    assert c.diag_drops == 1
    # a broken hook must not poison faults either
    c.on_ball()
    io.advance(MAX_MOTION_S + 0.2)
    c.poll()                                      # fault emit also swallowed
    assert c.state is State.FAULT
    assert c.diag_drops == 2
    assert c.last_fault["code"] == "motion_timeout:SWEEP_TO_GUARD"
    # snapshot reports the drops
    assert c.diagnostics_snapshot()["diag_drops"] == 2


def test_on_diag_none_is_safe():
    c, io = at_ready()
    assert c.on_diag is None
    c.cam_SB_guard()                              # hook absent: counters only
    assert c.diag_counters == {"cam_SB_guard:ready": 1}
    assert c.diag_drops == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok   {fn.__name__}")
    print(f"\nALL {len(fns)} fsm-diagnostics CHECKS PASSED")
