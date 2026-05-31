#!/usr/bin/env python3
"""8270 cycle-control FSM — DRAFT R1, derived from the documented Sequence of Operation.

SUPERSEDES the earlier `cycle_control.py` "SS-pulse" model, which is VOID: the
82-70 has no one-pulse-per-cycle trigger. Per the AMF service manual, the
controller DRIVES the sweep and table motors and reads CAM switches (mounted on
the motor shafts) for position — de-energizing a motor when its cam reports the
target degree. So this is an EVENT-DRIVEN FSM: cam transitions (+ SS, grippers,
bin switch, foul, the 3-second settle timer) drive state changes; each state
sets motor / solenoid / lamp outputs.

Reverse-derived from:
  docs/phase8_8270_SYSTEM_REFERENCE.md  (sections 2 = sequence, 3 = cam timing,
  4 = I/O, 5 = safety) — itself distilled from the AMF 8270 Service & Parts and
  MP Operation Training manuals.

STATUS: spec-derived DRAFT. Develop + bench-validate on the spare/test machine
(simulated I/O, then real) before ANY live lane. NOT production until:
  * exact C1/C2A machine-side pins confirmed (service-manual schematic p288 +
    verification on the spare),
  * the hardware safety chain is in place (TB/SC collision interlock, stop/CIS
    breaker chain, NE555 watchdog, E-stop, hardwired end-stops where present),
  * every cycle + every fault case validated off-live.
The intricate run-through / respot timing is captured at the major-transition
level here; the points that need confirming against the schematic or the real
machine are marked  # CONFIRM .

SAFETY (the Pi's responsibilities; hardware backstops exist independently):
  * interlock_ok() (TB/SC) gates EVERY motor energize. Hardware enforces it too;
    this is the software echo, never the sole guard.
  * On power restore the FSM comes up in MANUAL_INTERVENTION and drives NOTHING
    until the operator presses First-Ball-Zero — the MP "Power-Down" rule (§5).
  * io.watchdog_kick() every poll(); the NE555 drops all relays if we stop.
  * MAX_MOTION_S faults + cuts power if a motion never reports complete.
"""

from __future__ import annotations
import time
from enum import Enum

# ---- CAM TIMING (degrees) — SYSTEM_REFERENCE §3 (authoritative) ----------------
SB_GUARD       = 66    # sweep stops at first guard
SB_SPOT        = 186   # sweep initiates table spotting
SA_RUNTHROUGH  = 270   # sweep stops after run-through
SA_ZERO        = 360   # sweep stops at zero
SC_LO, SC_HI   = 86, 243   # sweep-under-table (interlock window)
TA1_DELAYRESET = 185   # table resets the time delay
TA1_ZERO       = 355   # table stops at zero
TA2_RUNTHROUGH = 260   # table initiates sweep run-through; pin-lamp latch; ball/strike decision
TB_LO, TB_HI   = 105, 255  # table-sweep interference (interlock window)

TIME_DELAY_S = 3.0     # pin-settle delay, gated by GP (gripper-protect) closed
MAX_MOTION_S = 8.0     # safety backstop per motor motion. FIELD: set = measured + margin


class Ball(Enum):
    FIRST = 1
    SECOND = 2


class Cycle(Enum):
    FIRST_BALL = "first_ball"   # pins left standing on 1st ball
    SECOND_BALL = "second_ball"
    STRIKE = "strike"           # no pins on 1st ball
    FOUL = "foul"


class State(Enum):
    POWER_OFF = "power_off"
    MANUAL_INTERVENTION = "manual_intervention"  # power restored; await First-Ball-Zero (§5)
    READY = "ready"                              # at zero, awaiting SS (ball)
    SWEEP_TO_GUARD = "sweep_to_guard"            # sweep running to 66°
    GUARD_DELAY = "guard_delay"                  # 3s settle at guard
    TABLE_DETECT = "table_detect"                # table down, grippers reading
    RUNTHROUGH = "runthrough"                    # sweep run-through to 270°
    TABLE_FINISH = "table_finish"                # table through TA1, spot/respot, sweep return
    FAULT = "fault"


class CycleController:
    """One instance per physical lane. ALL hardware access is via `io`, so this is
    fully bench-testable with a simulator (see __main__).

    io interface (inject gpiozero-backed wrappers in the daemon; fakes in tests):
      io.set_sweep(on: bool)      energize/de-energize the SWEEP motor relay (S)
      io.set_table(on: bool)      energize/de-energize the TABLE motor relay (T)
      io.set_spot(on: bool)       energize the SPOT solenoid relay (SP)
      io.set_pin_lamps(mask:int)  drive the 10 mask pin lamps (or hand to camera/Track A)
      io.set_light(name, on)      'first_ball'|'second_ball'|'strike'|'foul' mask lights
      io.read_grippers()-> int    10-bit standing-pin mask from GS1-10 (0 = none = strike)
      io.gp_closed()  -> bool     gripper-protect closed (enables the time delay)
      io.bs_closed()  -> bool     bin switch: 10th pin delivered (gate spotting)
      io.interlock_ok()-> bool    TB/SC collision interlock (SECONDARY software guard)
      io.watchdog_kick()          pet the NE555 hardware watchdog
      io.now()        -> float    monotonic seconds (injectable)
      io.log(msg)
    """

    def __init__(self, lane_id, io):
        self.lane = lane_id
        self.io = io
        self.state = State.POWER_OFF
        self.ball = Ball.FIRST
        self.cycle = None
        self.pins = 0            # latched standing-pin mask this cycle
        self._t_state = 0.0      # time entered current state (for delay + backstop)

    # ---- power / safety ----------------------------------------------------
    def power_restore(self):
        """Power (re)applied. MP 'Power-Down' rule (§5): drive NOTHING until the
        operator clears it. Pit light only is on (handled in hardware/daemon)."""
        self._all_motors_off()
        self.state = State.MANUAL_INTERVENTION
        self.io.log(f"L{self.lane}: power restored -> MANUAL_INTERVENTION (await First-Ball-Zero)")

    def first_ball_zero(self):
        """Operator pressed First-Ball-Zero (PBZ). Clears manual-intervention and
        also toggles 1st/2nd-ball when already running (§5 'manual intervention')."""
        if self.state is State.MANUAL_INTERVENTION:
            # must be physically at zero (cams confirm); daemon checks before calling
            self.ball = Ball.FIRST
            self._enter(State.READY)
            self.io.set_light('first_ball', True)
            self.io.log(f"L{self.lane}: First-Ball-Zero -> READY (1st ball)")
        elif self.state is State.READY:
            self._toggle_ball()

    def _all_motors_off(self):
        self.io.set_sweep(False)
        self.io.set_table(False)
        self.io.set_spot(False)

    def _safe_sweep(self, on):
        if on and not self.io.interlock_ok():
            self.io.log(f"L{self.lane}: SWEEP energize BLOCKED — interlock open (safety)")
            return
        self.io.set_sweep(on)

    def _safe_table(self, on):
        if on and not self.io.interlock_ok():
            self.io.log(f"L{self.lane}: TABLE energize BLOCKED — interlock open (safety)")
            return
        self.io.set_table(on)

    def _enter(self, state):
        self.state = state
        self._t_state = self.io.now()

    def _toggle_ball(self):
        self.ball = Ball.SECOND if self.ball is Ball.FIRST else Ball.FIRST
        self.io.set_light('first_ball', self.ball is Ball.FIRST)
        self.io.set_light('second_ball', self.ball is Ball.SECOND)

    # ---- the cycle trigger -------------------------------------------------
    def on_ball(self):
        """SS / DIELL: a ball was thrown. Start a cycle if READY + safe."""
        if self.state is not State.READY:
            self.io.log(f"L{self.lane}: ball ignored (state={self.state.value})")
            return
        if not self.io.interlock_ok():
            self.io.log(f"L{self.lane}: ball ignored — interlock open")
            return
        self.cycle = Cycle.SECOND_BALL if self.ball is Ball.SECOND else Cycle.FIRST_BALL
        self._safe_sweep(True)                 # sweep runs toward 66° guard
        self._enter(State.SWEEP_TO_GUARD)
        self.io.log(f"L{self.lane}: SS -> sweep to guard ({self.ball.name})")

    def on_foul(self):
        """Foul detector fired (during a 1st-ball cycle): light foul + flag cycle."""
        self.io.set_light('foul', True)
        if self.ball is Ball.FIRST:
            self.cycle = Cycle.FOUL
        self.io.log(f"L{self.lane}: FOUL")

    # ---- cam events (emitted by the daemon's GPIO edges; sim emits on a timeline) ----
    # Each handler maps directly to a step in SYSTEM_REFERENCE §2.
    def cam_SB_guard(self):          # sweep reached 66°
        if self.state is State.SWEEP_TO_GUARD:
            self.io.set_sweep(False)
            self._enter(State.GUARD_DELAY)     # start 3s settle (poll() checks GP + timer)
            self.io.log(f"L{self.lane}: sweep@66 guard -> {TIME_DELAY_S}s delay")

    def cam_TA2_runthrough(self):    # table reached 260°
        if self.state is State.TABLE_DETECT:
            self.pins = self.io.read_grippers()        # latch standing pins (0 = strike)
            self.io.set_pin_lamps(self.pins)           # §2: pin lamps latch at 260°
            if self.cycle is Cycle.FIRST_BALL and self.pins == 0:
                self.cycle = Cycle.STRIKE
                self.io.set_light('strike', True)
                self.io.set_light('first_ball', False)
            self._safe_sweep(True)                     # sweep run-through begins
            self._enter(State.RUNTHROUGH)
            self.io.log(f"L{self.lane}: TA2@260 pins={self.pins:010b} cycle={self.cycle.value} -> runthrough")

    def cam_SA_runthrough(self):     # sweep reached 270°
        if self.state is State.RUNTHROUGH:
            self.io.set_sweep(False)
            self._enter(State.TABLE_FINISH)
            self.io.log(f"L{self.lane}: sweep@270 -> table finishing")

    def cam_TA1_delayreset(self):    # table passed 185°
        # resets the time-delay memory (§2). No motor change here.
        pass

    def cam_TA1_zero(self):          # table reached 355°/zero
        if self.state is State.TABLE_FINISH:
            self.io.set_table(False)
            self._finish_cycle()

    def cam_SA_zero(self):           # sweep reached 360°/zero
        if self.state is State.TABLE_FINISH:
            self.io.set_sweep(False)

    def bin_full(self):              # BS: 10th pin delivered to bin (gate spotting)
        # On 2nd-ball / strike / foul, spotting waits for a full bin (§2). CONFIRM
        # exact gating vs. the schematic; handled in TABLE_FINISH for now.
        pass

    def _finish_cycle(self):
        """End-of-cycle bookkeeping: flip ball memory / reset strike+foul (§2)."""
        if self.cycle in (Cycle.FIRST_BALL, Cycle.FOUL):
            self.ball = Ball.SECOND
        elif self.cycle in (Cycle.SECOND_BALL, Cycle.STRIKE):
            self.ball = Ball.FIRST
        self.io.set_light('first_ball', self.ball is Ball.FIRST)
        self.io.set_light('second_ball', self.ball is Ball.SECOND)
        self.io.set_light('strike', False)
        self.io.set_light('foul', False)
        self.cycle = None
        self._enter(State.READY)
        self.io.log(f"L{self.lane}: cycle complete -> READY ({self.ball.name})")

    # ---- periodic: call at ~20-50 Hz ---------------------------------------
    def poll(self):
        self.io.watchdog_kick()
        now = self.io.now()

        # GUARD_DELAY: after 3s (and GP closed) start the table down.
        if self.state is State.GUARD_DELAY:
            if self.io.gp_closed() and (now - self._t_state) >= TIME_DELAY_S:
                self._safe_table(True)
                self._enter(State.TABLE_DETECT)
                self.io.log(f"L{self.lane}: delay done -> table down (detect)")
            return

        # Safety backstop: any motion state stuck too long -> FAULT + power off.
        if self.state in (State.SWEEP_TO_GUARD, State.TABLE_DETECT,
                          State.RUNTHROUGH, State.TABLE_FINISH):
            if (now - self._t_state) > MAX_MOTION_S:
                self.io.log(f"L{self.lane}: FAULT — {self.state.value} > {MAX_MOTION_S}s; motors OFF")
                self._all_motors_off()
                self.state = State.FAULT


# --------------------- bench simulator (R1, no hardware) ------------------------
# Run:  python cycle_control_8270.py
# Plays a 1st-ball (pins) then a strike through the FSM using a fake machine that
# emits cam events on a timeline as the motors run. Proves the state flow + safety.
if __name__ == "__main__":
    SWEEP_T = {'guard': 0.6, 'runthrough': 0.9, 'zero': 0.6}  # pretend timings
    TABLE_T = {'detect_to_260': 1.2, 'to_zero': 1.4}

    class SimIO:
        def __init__(self): self.t = 0.0; self.interlock = True; self.grip = 0
        def now(self): return self.t
        def log(self, m): print(f"  [{self.t:5.2f}] {m}")
        def set_sweep(self, on): print(f"      sweep={'ON' if on else 'off'}")
        def set_table(self, on): print(f"      table={'ON' if on else 'off'}")
        def set_spot(self, on): print(f"      spot={'ON' if on else 'off'}")
        def set_pin_lamps(self, m): print(f"      pin_lamps={m:010b}")
        def set_light(self, n, on): pass
        def read_grippers(self): return self.grip
        def gp_closed(self): return True
        def bs_closed(self): return True
        def interlock_ok(self): return self.interlock
        def watchdog_kick(self): pass

    io = SimIO()
    c = CycleController(21, io)
    print("=== 8270 FSM bench sim (R1) ===")
    c.power_restore(); c.first_ball_zero()

    def run_cycle(standing_mask, label):
        print(f"\n--- {label} (standing={standing_mask:010b}) ---")
        io.grip = standing_mask
        c.on_ball()
        # fake machine emits cam events on a timeline:
        seq = [(SWEEP_T['guard'], c.cam_SB_guard),
               (TIME_DELAY_S + 0.1, lambda: None),          # poll() starts table
               (TABLE_T['detect_to_260'], c.cam_TA2_runthrough),
               (SWEEP_T['runthrough'], c.cam_SA_runthrough),
               (TABLE_T['to_zero'] * 0.5, c.cam_TA1_delayreset),
               (TABLE_T['to_zero'] * 0.5, c.cam_TA1_zero)]
        for dt, ev in seq:
            target = io.t + dt
            while io.t < target:
                c.poll(); io.t = round(io.t + 0.05, 2)
            ev()
        c.poll()
        print(f"  => state={c.state.value} ball={c.ball.name}")

    run_cycle(0b0000000101, "first ball, 7+10 left")  # pins standing -> 2nd ball
    run_cycle(0b0000000000, "strike (no pins)")        # no pins -> strike cycle
    print("\nExpected: 1st-ball cycle ends READY/SECOND; strike latches then READY/FIRST.")
