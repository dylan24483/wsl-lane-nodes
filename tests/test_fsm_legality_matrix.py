#!/usr/bin/env python3
"""test_fsm_legality_matrix.py — declarative (State x event) legality matrix for the
8270 cycle-control FSM (idea #12). Run: `py -3 tests/test_fsm_legality_matrix.py`.

WHY
───
Every event handler in cycle_control_8270.py is `if state is X:`-guarded with no
`else` — an out-of-sequence event is a SILENT no-op. That hides benign cam chatter
AND the dangerous case (a cam edge in READY/MANUAL_INTERVENTION means the machine
is physically rotating with NO command). This test pins the FSM's largest
unreviewed surface: it declares, for EVERY (State, event) cell, the expected
disposition, drives a fresh CycleController into each State, fires each event, and
asserts the actual outcome matches the declaration. Any cell that silently changes
behavior (a handler that starts acting in a state the matrix says it ignores, or
stops acting where it should advance) fails the test.

READ-ONLY: imports the FSM + RecordingIO; never edits them. Drives no hardware.

DISPOSITIONS
────────────
  IGNORE   the event does NOT change state and drives no motor output. (The FSM's
           current contract for an out-of-window event: log-only no-op. The audit
           recommends some of these become FAULT in a future hardening pass —
           this matrix DOCUMENTS the current behavior so that change is a
           deliberate, reviewed matrix edit, not an accident.)
  ADVANCE  the event legitimately changes state (the happy-path transition).
  FAULT    the event drives the FSM to State.FAULT (motors off, latched).

Each cell is the EXPECTED disposition. The harness computes the ACTUAL disposition
by snapshotting state before/after and comparing State.FAULT / state-change / no-op.
Cells marked ADVANCE additionally assert the resulting state == the expected target.

The event set covers the FSM's full external surface:
  on_ball, on_foul, first_ball_zero, bin_full, poll, and the 6 cam edges
  (cam_SB_guard, cam_TA2_runthrough, cam_SA_runthrough, cam_SA_zero,
   cam_TA1_delayreset, cam_TA1_zero).
`poll` is evaluated in the "safe idle" input context (interlock OK, GP closed, no
timeout elapsed); its timing-dependent transitions (GUARD_DELAY->TABLE_DETECT,
motion-timeout->FAULT) are exercised separately at the bottom of this file so the
matrix stays a pure structural map.
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lane_node"))
from cycle_control_8270 import (  # noqa: E402
    CycleController, State, Ball, Cycle, TIME_DELAY_S, MAX_MOTION_S)
from controller_io import RecordingIO  # noqa: E402

IGNORE, ADVANCE, FAULT = "IGNORE", "ADVANCE", "FAULT"

fails = []


def chk(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


# ── builders: drive a FRESH controller deterministically into a target State ────
# Each returns (controller, io). Inputs left at RecordingIO's safe-idle defaults
# (interlock OK, gp closed, bs open, grippers per the cycle) unless noted.

def _new():
    io = RecordingIO()
    c = CycleController(21, io)
    return c, io


def at_power_off():
    return _new()  # construction default is POWER_OFF


def at_manual_intervention():
    c, io = _new()
    c.power_restore()
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
    c.poll()  # GUARD_DELAY -> TABLE_DETECT
    return c, io


def at_runthrough(grippers=0b0000000101):
    # 1st-ball-with-pins: RUNTHROUGH that respots (no fresh rack)
    c, io = at_ready()
    io.grippers = grippers
    c.on_ball()
    c.cam_SB_guard()
    io.advance(TIME_DELAY_S + 0.1)
    c.poll()
    c.cam_TA2_runthrough()
    return c, io


def at_table_finish_respot():
    # FIRST_BALL respot in TABLE_FINISH, table NOT yet at zero -> awaiting sweep/TA1
    c, io = at_runthrough(grippers=0b0000000101)
    c.cam_SA_runthrough()
    return c, io


def at_table_finish_freshrack():
    # STRIKE in TABLE_FINISH, table parked at zero, awaiting BS for the spot
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
    c.bin_full()             # BS -> SP, SPOTTING
    return c, io


def at_fault():
    c, io = at_sweep_to_guard()
    io.advance(MAX_MOTION_S + 0.2)
    c.poll()                 # motion timeout -> FAULT
    return c, io


# Map a State to (builder, builder_label).
BUILDERS = {
    State.POWER_OFF:            (at_power_off, "POWER_OFF"),
    State.MANUAL_INTERVENTION:  (at_manual_intervention, "MANUAL_INTERVENTION"),
    State.READY:                (at_ready, "READY"),
    State.SWEEP_TO_GUARD:       (at_sweep_to_guard, "SWEEP_TO_GUARD"),
    State.GUARD_DELAY:          (at_guard_delay, "GUARD_DELAY"),
    State.TABLE_DETECT:         (at_table_detect, "TABLE_DETECT"),
    State.RUNTHROUGH:           (at_runthrough, "RUNTHROUGH"),
    State.TABLE_FINISH:         (at_table_finish_respot, "TABLE_FINISH(respot)"),
    State.SPOTTING:             (at_spotting, "SPOTTING"),
    State.FAULT:                (at_fault, "FAULT"),
}

# ── events: name -> callable(controller) ────────────────────────────────────────
EVENTS = {
    "on_ball":            lambda c: c.on_ball(),
    "on_foul":            lambda c: c.on_foul(),
    "first_ball_zero":    lambda c: c.first_ball_zero(),
    "bin_full":           lambda c: c.bin_full(),
    "poll":               lambda c: c.poll(),
    "cam_SB_guard":       lambda c: c.cam_SB_guard(),
    "cam_TA2_runthrough": lambda c: c.cam_TA2_runthrough(),
    "cam_SA_runthrough":  lambda c: c.cam_SA_runthrough(),
    "cam_SA_zero":        lambda c: c.cam_SA_zero(),
    "cam_TA1_delayreset": lambda c: c.cam_TA1_delayreset(),
    "cam_TA1_zero":       lambda c: c.cam_TA1_zero(),
}

# ── THE MATRIX ──────────────────────────────────────────────────────────────────
# MATRIX[state][event] = IGNORE | (ADVANCE, target_state) | FAULT
#
# Derived by reading cycle_control_8270.py handler-by-handler. Cells that ADVANCE
# name the resulting state. Everything not explicitly the happy-path transition is
# IGNORE (current FSM contract = silent log-only no-op for out-of-window events).
#
# NOTE on `poll` in this matrix: evaluated at safe-idle with NO time elapsed since
# state entry, so GUARD_DELAY does not yet meet TIME_DELAY_S and motion states are
# not yet past MAX_MOTION_S — poll is therefore IGNORE in every cell here. The
# time-driven poll transitions are asserted separately below (POLL TIMING section).
S = State
MATRIX = {
    S.POWER_OFF: {
        # Nothing is wired until power_restore(); every cam/ball/button is inert.
        "on_ball": IGNORE, "on_foul": IGNORE, "first_ball_zero": IGNORE,
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.MANUAL_INTERVENTION: {
        "on_ball": IGNORE, "on_foul": IGNORE,
        "first_ball_zero": (ADVANCE, S.READY),     # the deliberate re-arm edge
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.READY: {
        "on_ball": (ADVANCE, S.SWEEP_TO_GUARD),    # the cycle trigger
        "on_foul": IGNORE,                          # lamp only, no state change
        "first_ball_zero": IGNORE,                  # toggles ball memory; state stays READY
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.SWEEP_TO_GUARD: {
        "on_ball": IGNORE, "on_foul": IGNORE,       # foul reclassifies CYCLE, not STATE
        "first_ball_zero": IGNORE, "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": (ADVANCE, S.GUARD_DELAY),   # sweep@66 -> settle
        "cam_TA2_runthrough": IGNORE, "cam_SA_runthrough": IGNORE,
        "cam_SA_zero": IGNORE, "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.GUARD_DELAY: {
        "on_ball": IGNORE, "on_foul": IGNORE,       # foul still reclassifies CYCLE here
        "first_ball_zero": IGNORE, "bin_full": IGNORE,
        "poll": IGNORE,                             # no time elapsed -> stays (timing tested below)
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.TABLE_DETECT: {
        "on_ball": IGNORE, "on_foul": IGNORE, "first_ball_zero": IGNORE,
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE,
        "cam_TA2_runthrough": (ADVANCE, S.RUNTHROUGH),  # latch pins, sweep run-through
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
    S.RUNTHROUGH: {
        "on_ball": IGNORE, "on_foul": IGNORE, "first_ball_zero": IGNORE,
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": (ADVANCE, S.TABLE_FINISH),  # sweep@270 -> table finishing
        "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE,
        "cam_TA1_zero": IGNORE,   # stops table + latches table_done, but STATE stays RUNTHROUGH
    },
    S.TABLE_FINISH: {
        # respot variant (table not yet at zero): TA1_zero completes the cycle.
        "on_ball": IGNORE, "on_foul": IGNORE, "first_ball_zero": IGNORE,
        "bin_full": IGNORE,        # respot needs no fresh rack -> BS is a no-op here
        "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE,
        "cam_SA_zero": IGNORE,     # de-energizes sweep, no state change
        "cam_TA1_delayreset": IGNORE,
        "cam_TA1_zero": (ADVANCE, S.READY),   # respot done -> READY
    },
    S.SPOTTING: {
        "on_ball": IGNORE, "on_foul": IGNORE, "first_ball_zero": IGNORE,
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE,
        "cam_SA_zero": IGNORE,     # de-energizes sweep, no state change
        "cam_TA1_delayreset": IGNORE,
        "cam_TA1_zero": (ADVANCE, S.READY),   # SP off, table off, fresh rack done -> READY
    },
    S.FAULT: {
        "on_ball": IGNORE, "on_foul": IGNORE,
        "first_ball_zero": (ADVANCE, S.MANUAL_INTERVENTION),  # 1st recovery press
        "bin_full": IGNORE, "poll": IGNORE,
        "cam_SB_guard": IGNORE, "cam_TA2_runthrough": IGNORE,
        "cam_SA_runthrough": IGNORE, "cam_SA_zero": IGNORE,
        "cam_TA1_delayreset": IGNORE, "cam_TA1_zero": IGNORE,
    },
}

# Outputs that count as "drove a motor" (an IGNORE cell must NOT touch these).
# Lamp outputs (set_light/pin_lamps) are cosmetic and allowed in IGNORE cells
# (e.g. on_foul lights the foul lamp without changing state) — only sweep/table/spot
# energize counts as motion.
_MOTOR_OUT = {"sweep", "table", "spot"}


def _motor_energized_during(io, start_idx):
    """True if any sweep/table/spot was driven ON in io.events from start_idx on."""
    for ev in io.events[start_idx:]:
        if ev[0] in _MOTOR_OUT and ev[1] is True:
            return True
    return False


def actual_disposition(c, io, before_state, ev_start_idx):
    """Classify what the event did: FAULT / (ADVANCE,new) / IGNORE."""
    if c.state is State.FAULT and before_state is not State.FAULT:
        return FAULT, c.state
    if c.state is not before_state:
        return ADVANCE, c.state
    return IGNORE, c.state


# ── run the matrix ──────────────────────────────────────────────────────────────
print("=== 8270 FSM (State x event) legality matrix ===\n")
cells = 0
for st, (builder, label) in BUILDERS.items():
    if st not in MATRIX:
        chk(f"matrix missing row for {st.value}", False)
        continue
    row = MATRIX[st]
    # every event must have a declared cell (no silent gaps in the table)
    for ev_name in EVENTS:
        if ev_name not in row:
            chk(f"{label} x {ev_name}: undeclared cell", False)
    for ev_name, fire in EVENTS.items():
        if ev_name not in row:
            continue
        cells += 1
        c, io = builder()          # FRESH controller in the target state
        # sanity: builder actually reached the intended state
        if c.state is not st:
            chk(f"builder for {label} reached {c.state.value}", False, c.state.value)
            continue
        before = c.state
        idx = len(io.events)
        try:
            fire(c)
        except Exception as e:      # an event must never raise — that's a hard fail
            chk(f"{label} x {ev_name}: raised {type(e).__name__}", False, str(e))
            continue
        exp = row[ev_name]
        act_kind, act_state = actual_disposition(c, io, before, idx)
        exp_kind = exp[0] if isinstance(exp, tuple) else exp

        ok = (act_kind == exp_kind)
        target_ok = True
        if exp_kind == ADVANCE and isinstance(exp, tuple):
            target_ok = (act_state is exp[1])
        # IGNORE cells additionally must not have energized a motor.
        motor_ok = True
        if exp_kind == IGNORE:
            motor_ok = not _motor_energized_during(io, idx)
        chk(f"{label:22s} x {ev_name:18s} -> {exp_kind}",
            ok and target_ok and motor_ok,
            f"got {act_kind}->{act_state.value}" + ("" if motor_ok else " +MOTOR-ON"))

print(f"\n  ({cells} matrix cells evaluated)\n")

# ── POLL TIMING — the time-driven transitions the structural matrix can't express ─
print("--- poll timing transitions (separate from the structural matrix) ---")

# GUARD_DELAY: poll with delay elapsed + GP closed -> TABLE_DETECT
c, io = at_guard_delay()
io.advance(TIME_DELAY_S + 0.1)
c.poll()
chk("GUARD_DELAY + (delay elapsed, GP closed) poll -> TABLE_DETECT",
    c.state is State.TABLE_DETECT, c.state.value)

# GUARD_DELAY: GP OPEN holds in GUARD_DELAY even past the delay (bounded later)
c, io = at_guard_delay()
io.gp = False
io.advance(TIME_DELAY_S + 0.5)
c.poll()
chk("GUARD_DELAY + GP-open poll stays GUARD_DELAY (settle gate)",
    c.state is State.GUARD_DELAY, c.state.value)

# GUARD_DELAY: GP open past GUARD_DELAY_MAX_S -> FAULT (bounded wait)
from cycle_control_8270 import GUARD_DELAY_MAX_S  # noqa: E402
c, io = at_guard_delay()
io.gp = False
io.advance(GUARD_DELAY_MAX_S + 0.2)
c.poll()
chk("GUARD_DELAY + GP-open past GUARD_DELAY_MAX_S poll -> FAULT",
    c.state is State.FAULT, c.state.value)

# Each motion state: poll past MAX_MOTION_S -> FAULT (the safety backstop)
for st, (builder, label) in BUILDERS.items():
    from cycle_control_8270 import MOTION_STATES
    if st not in MOTION_STATES:
        continue
    c, io = builder()
    if c.state is not st:
        chk(f"motion-timeout builder for {label}", False, c.state.value)
        continue
    io.advance(MAX_MOTION_S + 0.2)
    c.poll()
    chk(f"{label:22s} poll past MAX_MOTION_S -> FAULT", c.state is State.FAULT, c.state.value)

# Mid-motion interlock loss: poll in a motion state with interlock open -> FAULT
for st, (builder, label) in BUILDERS.items():
    from cycle_control_8270 import MOTION_STATES
    if st not in MOTION_STATES:
        continue
    c, io = builder()
    if c.state is not st:
        continue
    io.interlock = False
    c.poll()
    chk(f"{label:22s} poll with interlock OPEN -> FAULT", c.state is State.FAULT, c.state.value)

# ── SAFETY-CRITICAL ASSERTIONS the matrix structure encodes ─────────────────────
print("\n--- safety-critical structural guarantees ---")

# In every IGNORE cell of READY / MANUAL_INTERVENTION (the at-rest states), a cam
# edge must NOT energize a motor. (This is the "uncommanded motion" surface the
# audit flags: today it's a silent no-op; the matrix guarantees at least that it
# never DRIVES anything. Converting these to FAULT later is a single matrix edit.)
for st in (State.READY, State.MANUAL_INTERVENTION, State.POWER_OFF, State.FAULT):
    builder, label = BUILDERS[st]
    for ev_name in ("cam_SB_guard", "cam_TA2_runthrough", "cam_SA_runthrough",
                    "cam_SA_zero", "cam_TA1_delayreset", "cam_TA1_zero"):
        c, io = builder()
        if c.state is not st:
            continue
        idx = len(io.events)
        EVENTS[ev_name](c)
        chk(f"{label:20s}: {ev_name} drives NO motor (no uncommanded motion)",
            not _motor_energized_during(io, idx))

# A ball in any non-READY state must never start a sweep.
for st, (builder, label) in BUILDERS.items():
    if st is State.READY:
        continue
    c, io = builder()
    if c.state is not st:
        continue
    idx = len(io.events)
    c.on_ball()
    chk(f"{label:22s}: on_ball drives NO sweep (cycle trigger gated to READY)",
        not _motor_energized_during(io, idx))

print()
print("ALL legality-matrix CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
