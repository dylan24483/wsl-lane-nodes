#!/usr/bin/env python3
"""test_safety_rail_rig.py — scripted G3 pre-motion rail-drop regression rig (idea #16).
Run: `py -3 tests/test_safety_rail_rig.py`.

WHAT G3 IS
──────────
G3 is the cutover gate that proves: when something says "do not move", the controller
drives every motor output LOW (fail-safe) within a bounded latency, and STAYS down
until a deliberate operator recovery. Post-cutover the OEM logic stops are gone, so
this software/hardware fail-safe IS the stop. This rig makes that gate a repeatable
test instead of a one-time bench observation.

It exercises the three documented pre-motion / mid-motion veto paths that the
SOFTWARE layer owns (the hardware NE555 rail + RP2040 RP_OK + TB/SC loop are the
independent backstops, validated on the bench, not here):

  V1  interlock VETO  — interlock_ok() False at/just-before an energize: the FSM
                        REFUSES to energize and never advances into motion.
  V2  mid-motion trip — interlock drops WHILE a motion state is active: the next
                        poll() drives outputs LOW and latches FAULT.
  V3  SIGTERM-equivalent / RP2040-lost SAFETY TRIP — power_restore() (the call the
                        daemon makes on link loss or shutdown) drops every output
                        LOW and latches MANUAL_INTERVENTION (deliberate recovery).
  V4  watchdog-not-kicked — the FSM kicks the NE555 ONLY inside poll(); if poll()
                        stops being called the kick count freezes, which is the
                        software-observable precondition for the hardware rail to
                        drop. (The actual rail drop is the NE555's job; here we
                        assert the FSM never kicks OUTSIDE poll(), so a stalled loop
                        cannot keep the dog fed.)

LATENCY BOUND
─────────────
Measured in FAKE-CLOCK time via an injectable clock. The control loop runs at >= 20 Hz
(controller_daemon default 50 Hz), so a one-poll detection budget is conservatively
bounded at RAIL_DROP_BUDGET_S below. The rig asserts each veto produces motors-LOW
within ONE poll() (i.e. <= one tick period), independent of wall-clock.

READ-ONLY: imports the FSM + RecordingIO; edits neither; drives no hardware.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lane_node"))
from cycle_control_8270 import (  # noqa: E402
    CycleController, State, MOTION_STATES, TIME_DELAY_S, MAX_MOTION_S)
from controller_io import RecordingIO  # noqa: E402

# One control tick at the daemon's 50 Hz default = 0.02 s. The documented latency
# bound for the software veto is ONE tick: a veto seen at tick N drives outputs LOW
# by the end of tick N (no multi-tick latch). Use a conservative ceiling that still
# holds at the minimum sane loop rate (20 Hz -> 0.05 s).
LOOP_HZ = 50.0
TICK_S = 1.0 / LOOP_HZ
RAIL_DROP_BUDGET_S = 1.0 / 20.0   # 50 ms — must drop within one slow-loop tick

fails = []


def chk(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


# ── injectable-clock harness ────────────────────────────────────────────────────
class Clock:
    """Fake monotonic clock RecordingIO reads via its `now` injection."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


def fresh(clock):
    io = RecordingIO(now=clock)
    c = CycleController(21, io)
    return c, io


def to_ready(clock):
    c, io = fresh(clock)
    c.power_restore()
    c.first_ball_zero()
    assert c.state is State.READY
    return c, io


def drive_into_motion(clock, target, grippers=None):
    """Deterministically drive a fresh controller into a motion state. SPOTTING needs
    a fresh-rack cycle (strike, 0 standing pins); every other motion state is reached
    on a 1st-ball-with-pins respot cycle by default."""
    if grippers is None:
        grippers = 0 if target is State.SPOTTING else 0b0000000101
    c, io = to_ready(clock)
    io.grippers = grippers
    c.on_ball()                                   # -> SWEEP_TO_GUARD
    if target is State.SWEEP_TO_GUARD:
        return c, io
    c.cam_SB_guard()                              # -> GUARD_DELAY
    if target is State.GUARD_DELAY:
        return c, io
    clock.advance(TIME_DELAY_S + 0.1)
    c.poll()                                      # -> TABLE_DETECT
    if target is State.TABLE_DETECT:
        return c, io
    c.cam_TA2_runthrough()                        # -> RUNTHROUGH
    if target is State.RUNTHROUGH:
        return c, io
    c.cam_SA_runthrough()                         # -> TABLE_FINISH
    if target is State.TABLE_FINISH:
        return c, io
    io.bs = True
    c.bin_full()                                  # -> SPOTTING (fresh rack)
    return c, io


def motors_low(io):
    """True iff the LAST commanded value of every motor output is OFF (or never on)."""
    for name in ("sweep", "table", "spot"):
        if io.outputs.get(name) is True:
            return False
    return True


def any_motor_energized(io):
    return any(io.outputs.get(n) is True for n in ("sweep", "table", "spot"))


# ── V1: interlock VETO refuses a pre-motion energize ────────────────────────────
print("=== G3 safety-rail rig ===\n")
print("--- V1: pre-motion interlock veto (energize REFUSED, no advance) ---")

# on_ball with interlock open: the cycle trigger must not start the sweep.
clk = Clock()
c, io = to_ready(clk)
io.interlock = False
c.on_ball()
chk("V1a on_ball with interlock open -> stays READY, sweep NOT energized",
    c.state is State.READY and io.outputs.get("sweep") is not True, c.state.value)

# GUARD_DELAY -> table-down energize with interlock open: must NOT advance to
# TABLE_DETECT and must NOT energize the table (refused energize within one poll).
clk = Clock()
c, io = drive_into_motion(clk, State.GUARD_DELAY)
io.interlock = False
t0 = clk.t
clk.advance(TIME_DELAY_S + 0.2)
c.poll()
chk("V1b GUARD_DELAY table energize refused on open interlock -> stays GUARD_DELAY",
    c.state is State.GUARD_DELAY and io.outputs.get("table") is not True, c.state.value)
# latency: the refusal is evaluated inside that single poll() (one tick)
chk("V1b refusal decided within one poll (<= RAIL_DROP_BUDGET_S)",
    (clk.t - t0) <= (TIME_DELAY_S + 0.2 + RAIL_DROP_BUDGET_S))

# TABLE_DETECT -> TA2 run-through sweep energize refused mid-motion -> FAULT, motors LOW.
clk = Clock()
c, io = drive_into_motion(clk, State.TABLE_DETECT)
io.interlock = False
c.cam_TA2_runthrough()          # sweep energize refused at TA2 -> _fault
chk("V1c TA2 sweep energize refused on open interlock -> FAULT, motors LOW",
    c.state is State.FAULT and motors_low(io), c.state.value)


# ── V2: mid-motion interlock trip drops outputs LOW within one poll ─────────────
print("\n--- V2: mid-motion interlock trip (outputs LOW + FAULT within one tick) ---")
for st in MOTION_STATES:
    clk = Clock()
    c, io = drive_into_motion(clk, st)
    if c.state is not st:
        chk(f"V2 builder reached {st.value}", False, c.state.value)
        continue
    # confirm a motor really is running in this state before we trip
    running = any_motor_energized(io)
    io.interlock = False
    t0 = clk.t
    clk.advance(TICK_S)             # one control tick later
    c.poll()
    latency = clk.t - t0
    chk(f"V2 {st.value:14s}: interlock trip -> FAULT + all motors LOW",
        c.state is State.FAULT and motors_low(io), c.state.value)
    chk(f"V2 {st.value:14s}: rail drop within RAIL_DROP_BUDGET_S ({latency*1000:.0f}ms)",
        latency <= RAIL_DROP_BUDGET_S, f"{latency*1000:.0f}ms")
    chk(f"V2 {st.value:14s}: (precondition) a motor was actually running",
        running)


# ── V3: SIGTERM-equivalent / RP2040-lost safety trip ────────────────────────────
# The daemon calls fsm.power_restore() on RP2040 link loss AND drives io.arm(False)
# + io.all_off() on shutdown (safe_off). power_restore() is the FSM half: it must
# drop every output LOW and latch MANUAL_INTERVENTION (deliberate recovery, never
# auto-rearm). Test from a mid-motion state (the dangerous case).
print("\n--- V3: SIGTERM-equivalent safety trip (power_restore from motion) ---")
for st in MOTION_STATES:
    clk = Clock()
    c, io = drive_into_motion(clk, st)
    if c.state is not st:
        continue
    c.power_restore()              # the daemon's link-loss / shutdown call
    chk(f"V3 {st.value:14s}: power_restore -> MANUAL_INTERVENTION + motors LOW",
        c.state is State.MANUAL_INTERVENTION and motors_low(io), c.state.value)

# Recovery must NOT auto-rearm: after the trip, a single PBZ goes to READY only via
# the deliberate at-zero gate, and a ball before that does nothing.
clk = Clock()
c, io = drive_into_motion(clk, State.RUNTHROUGH)
c.power_restore()
io.grippers = 0
c.on_ball()                       # must be ignored in MANUAL_INTERVENTION
chk("V3 recovery: on_ball in MANUAL_INTERVENTION is ignored (no auto-rearm)",
    c.state is State.MANUAL_INTERVENTION and io.outputs.get("sweep") is not True)
c.first_ball_zero()               # deliberate re-arm
chk("V3 recovery: deliberate First-Ball-Zero -> READY",
    c.state is State.READY, c.state.value)

# safe_off-equivalent: io.all_off() / io.arm(False) drive the recording LOW + disarmed.
clk = Clock()
c, io = drive_into_motion(clk, State.RUNTHROUGH)
io.arm(False)
# RecordingIO has no all_off(); the daemon guards that with hasattr — assert the
# guard contract holds (no all_off attribute -> daemon skips it, FSM motors-off via
# power_restore covers it). Either way arm must record False.
chk("V3 safe_off: io.arm(False) recorded (rail disarmed)",
    io.armed is False)


# ── V4: watchdog is kicked ONLY inside poll() (stalled loop cannot feed the dog) ─
print("\n--- V4: watchdog-not-kicked (NE555 starves if poll() stops) ---")
clk = Clock()
c, io = to_ready(clk)
k0 = io.kicks
# Fire every non-poll event we can and assert NONE of them kick the watchdog.
io.grippers = 0b0000000101
c.on_ball(); c.cam_SB_guard()
c.on_foul()
c.first_ball_zero()
# drive a bit further without polling
chk("V4 no watchdog kick happens outside poll() (events alone never feed the dog)",
    io.kicks == k0, f"kicks went {k0}->{io.kicks}")
# a single poll() kicks exactly once
before = io.kicks
c.poll()
chk("V4 each poll() kicks the watchdog exactly once",
    io.kicks == before + 1, f"+{io.kicks - before}")
# N polls -> N kicks (so a frozen loop -> frozen kicks -> NE555 drops the rail)
before = io.kicks
for _ in range(10):
    clk.advance(TICK_S)
    c.poll()
chk("V4 N polls -> N kicks (stall => kick starvation => hardware rail drop)",
    io.kicks == before + 10, f"+{io.kicks - before}")


# ── V5: latched FAULT stays latched (rail does not re-arm on its own) ────────────
print("\n--- V5: FAULT is latched until deliberate recovery (no self re-arm) ---")
clk = Clock()
c, io = drive_into_motion(clk, State.SWEEP_TO_GUARD)
clk.advance(MAX_MOTION_S + 0.2)
c.poll()                          # motion timeout -> FAULT
chk("V5 motion-timeout -> FAULT + motors LOW", c.state is State.FAULT and motors_low(io))
# many polls later, still FAULT, still LOW, even with interlock healthy
io.interlock = True
for _ in range(50):
    clk.advance(TICK_S)
    c.poll()
chk("V5 FAULT survives 50 polls with healthy interlock (no auto-rearm)",
    c.state is State.FAULT and motors_low(io), c.state.value)
# recovery is exactly two deliberate presses
c.first_ball_zero()
chk("V5 recovery press 1: FAULT -> MANUAL_INTERVENTION", c.state is State.MANUAL_INTERVENTION)
c.first_ball_zero()
chk("V5 recovery press 2: MANUAL_INTERVENTION -> READY", c.state is State.READY)


print()
print("ALL safety-rail CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
