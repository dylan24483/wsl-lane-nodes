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
  * interlock_ok() (TB/SC) gates EVERY motor energize. ⚠️ The hardware interlock
    is PLANNED, not landed — design open per docs/phase8_interlock_redesign.md
    (measured 2026-06-27: the J_SAFETY dry loop is unbuildable as drawn). Until
    it lands, this software echo is the ONLY guard.
  * On power restore the FSM comes up in MANUAL_INTERVENTION and drives NOTHING
    until the operator presses First-Ball-Zero — the MP "Power-Down" rule (§5).
  * io.watchdog_kick() every poll(); the NE555 drops all relays if we stop.
  * MAX_MOTION_S faults + cuts power if a motion never reports complete.

R2 (2026-06-10 audit fixes):
  * _fault() latches FAULT (motors off); PBZ is the deliberate recovery edge —
    FAULT -> MANUAL_INTERVENTION -> READY takes TWO presses, never automatic.
  * _safe_sweep/_safe_table return bool; a REFUSED energize never advances state.
  * interlock is re-checked mid-motion every poll(); a veto stops + faults.
  * the table zero-stop (TA1@355) is honored in RUNTHROUGH (was silently dropped);
    a respot cycle completes only once BOTH sweep stop + table zero have occurred.
  * GUARD_DELAY wait is bounded (GUARD_DELAY_MAX_S) -> FAULT, not a silent stall.
  * foul reclassification is gated to the delivery window.
  * Two BENCH-GATED switches default to the original DRAFT-R1 behavior:
    SKIP_TABLE_DESCENT_ON_SECOND_BALL, POLL_BS_LEVEL_IN_TABLE_FINISH (below).
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
GUARD_DELAY_MAX_S = 30.0   # bound on the GUARD_DELAY wait (GP never closing / refused
                           # energize) before latching FAULT. FIELD: tune at bench.

# ---- BENCH-GATED behavior switches (default = original DRAFT-R1 behavior) ------
# Flip ONLY after the corresponding sequence is confirmed on the bench (§12.9).
#
# SECOND_BALL/FOUL cycles per SYSTEM_REFERENCE §2 do NOT lower the table onto the
# deck (no gripper grab of standing pins it should never touch); the sweep
# re-energizes straight into the run-through and the table stays at zero until the
# BS-gated spotting revolution. True = that corrected sequence. False = DRAFT-R1
# behavior (table descends + grippers read on EVERY cycle). Reconcile
# manual_src/03 §3.4/§3.5 with SYSTEM_REFERENCE §2 at the bench before flipping.
SKIP_TABLE_DESCENT_ON_SECOND_BALL = False

# BS (bin switch) has LEVEL semantics, but the daemon edge-detects it: if the bin
# is ALREADY full when TABLE_FINISH is reached (the common case), the edge never
# fires and no fresh rack is spotted. True = poll() treats the BS level as the
# primary gate in TABLE_FINISH (the daemon edge stays as a redundant trigger).
# False = edge-only DRAFT-R1 behavior, until BS polarity + SP/table spotting
# timing are bench-confirmed.
POLL_BS_LEVEL_IN_TABLE_FINISH = False


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
    SPOTTING = "spotting"                        # fresh-rack cycles: SP energized, table spotting rev (after BS)
    TABLE_FINISH = "table_finish"                # table through TA1, spot/respot, sweep return
    FAULT = "fault"


# States in which a motor can be in motion. The mid-motion interlock re-check and
# the MAX_MOTION_S backstop in poll() apply to every one of these.
MOTION_STATES = (State.SWEEP_TO_GUARD, State.TABLE_DETECT, State.RUNTHROUGH,
                 State.SPOTTING, State.TABLE_FINISH)


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
        self._table_done = False # table reached zero (TA1@355) this cycle

    # ---- power / safety ----------------------------------------------------
    def power_restore(self):
        """Power (re)applied. MP 'Power-Down' rule (§5): drive NOTHING until the
        operator clears it. Pit light only is on (handled in hardware/daemon)."""
        self._all_motors_off()
        self.state = State.MANUAL_INTERVENTION
        self.io.log(f"L{self.lane}: power restored -> MANUAL_INTERVENTION (await First-Ball-Zero)")

    def first_ball_zero(self):
        """Operator pressed First-Ball-Zero (PBZ). Clears manual-intervention and
        also toggles 1st/2nd-ball when already running (§5 'manual intervention').
        In FAULT it is the deliberate recovery edge, mirroring the power-down rule:
        FAULT -> MANUAL_INTERVENTION (motors stay off); a SECOND press — which then
        runs the at-zero gate below — is required to reach READY."""
        if self.state is State.FAULT:
            self._all_motors_off()      # already off at FAULT entry; re-assert anyway
            self._enter(State.MANUAL_INTERVENTION)
            self.io.log(f"L{self.lane}: PBZ in FAULT -> MANUAL_INTERVENTION "
                        f"(press again to re-arm)")
        elif self.state is State.MANUAL_INTERVENTION:
            # 'Machine physically at zero' precondition (PARTIAL): SC/TB must both
            # be outside their danger windows, else refuse to leave MANUAL_INTERVENTION.
            # Full positive at-zero evidence (SA + TA1 zero-lobe LEVELS) needs firmware
            # level reporting — see the P3 lobe-disambiguation item.  # CONFIRM @ bench
            if not self.io.interlock_ok():
                self.io.log(f"L{self.lane}: First-Ball-Zero REFUSED — interlock open "
                            f"(machine not provably safe at zero)")
                return
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
        """Energize/de-energize the sweep. Returns False when an energize is REFUSED
        (interlock open) — the caller must NOT advance state on a refusal."""
        if on and not self.io.interlock_ok():
            self.io.log(f"L{self.lane}: SWEEP energize BLOCKED — interlock open (safety)")
            return False
        self.io.set_sweep(on)
        return True

    def _safe_table(self, on):
        """Energize/de-energize the table. Returns False when an energize is REFUSED
        (interlock open) — the caller must NOT advance state on a refusal."""
        if on and not self.io.interlock_ok():
            self.io.log(f"L{self.lane}: TABLE energize BLOCKED — interlock open (safety)")
            return False
        self.io.set_table(on)
        return True

    def _fault(self, why):
        """Latch FAULT: motors off, state FAULT. Recovery is operator-deliberate —
        PBZ (-> MANUAL_INTERVENTION) then a second PBZ to re-arm; never automatic."""
        self.io.log(f"L{self.lane}: FAULT — {why}; motors OFF")
        self._all_motors_off()
        self._enter(State.FAULT)

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
        self._table_done = False
        if not self._safe_sweep(True):         # refused (interlock race): stay READY
            self.cycle = None
            return
        self._enter(State.SWEEP_TO_GUARD)
        self.io.log(f"L{self.lane}: SS -> sweep to guard ({self.ball.name})")

    def on_foul(self):
        """Foul detector fired. Light the lamp always; reclassify the CYCLE to FOUL
        only in the delivery window — SWEEP_TO_GUARD / GUARD_DELAY of a 1st-ball
        cycle, i.e. the foul belongs to the ball that just triggered the cycle. A
        late beam break must NOT convert a respot already in flight into a
        fresh-rack cycle.  # CONFIRM the real 82-70 foul-latch window on the bench."""
        self.io.set_light('foul', True)
        if (self.ball is Ball.FIRST
                and self.state in (State.SWEEP_TO_GUARD, State.GUARD_DELAY)):
            self.cycle = Cycle.FOUL
            self.io.log(f"L{self.lane}: FOUL -> cycle reclassified FOUL")
        else:
            self.io.log(f"L{self.lane}: FOUL (lamp only; state={self.state.value}, "
                        f"ball={self.ball.name})")

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
            if not self._safe_sweep(True):             # sweep run-through begins
                # refused mid-motion with the table descending: do NOT pretend the
                # run-through started — stop everything and latch FAULT.
                self._fault("sweep energize refused at TA2@260 (interlock)")
                return
            self._enter(State.RUNTHROUGH)
            self.io.log(f"L{self.lane}: TA2@260 pins={self.pins:010b} cycle={self.cycle.value} -> runthrough")

    def _needs_fresh_rack(self):
        """True for cycles that clear the deck + spot a NEW full rack (via SP),
        vs a 1st-ball-with-pins cycle which RESPOTS the held standing pins (no SP).
          * SECOND_BALL / STRIKE  -> fresh rack (SP).            # per §2
          * FIRST_BALL (pins left) -> respot held pins (no SP).
          * FOUL -> CONFIRM: foul respot semantics vary; treated as fresh-rack
            here as a placeholder — VERIFY on the bench before live."""
        return self.cycle in (Cycle.SECOND_BALL, Cycle.STRIKE, Cycle.FOUL)

    def cam_SA_runthrough(self):     # sweep reached 270° (cam SA -> C2A-31N)
        if self.state is State.RUNTHROUGH:
            self.io.set_sweep(False)
            self._enter(State.TABLE_FINISH)
            # Fresh-rack cycles wait for BS (bin full) -> bin_full() fires SP.
            # 1st-ball respot needs no SP and completes once table zero (TA1) has
            # ALSO occurred — possibly already, back during the run-through.
            self.io.log(f"L{self.lane}: sweep@270 -> table finishing "
                        f"({'awaiting BS for spot' if self._needs_fresh_rack() else 'respot held pins'})")
            if self._table_done and not self._needs_fresh_rack():
                # table already reached zero during RUNTHROUGH (TA1 honored there):
                # both motions are complete -> the respot cycle is done.
                self._finish_cycle()

    def cam_TA1_delayreset(self):    # table passed 185° (cam TA1 -> C2A-34N)
        # resets the time-delay memory (§2). No motor change here.
        pass

    def cam_TA1_zero(self):          # table reached 355°/zero (cam TA1 -> C2A-34N)
        # Table zero stop. Honored in EVERY state where the table is commanded on —
        # including RUNTHROUGH, where dropping it (DRAFT-R1 bug) let the table
        # overrun zero and re-descend onto the live deck. Completes the cycle from
        # TABLE_FINISH (respot) or SPOTTING (fresh rack: release SP once the
        # spotting revolution returns the table to zero).
        if self.state is State.SPOTTING:
            self.io.set_spot(False)      # CONFIRM: SP de-energize timing vs cam
            self.io.set_table(False)
            self._table_done = True
            self._finish_cycle()
        elif self.state is State.TABLE_FINISH:
            self.io.set_table(False)
            self._table_done = True
            if self._needs_fresh_rack():
                # fresh-rack: table parked at zero; STAY in TABLE_FINISH awaiting
                # BS -> SPOTTING. Completing here would skip the spot entirely and
                # report READY with no rack. MAX_MOTION_S still bounds the wait.
                self.io.log(f"L{self.lane}: TA1@zero — table stopped; awaiting BS for spot")
            else:
                self._finish_cycle()
        elif self.state is State.RUNTHROUGH:
            # zero-stop arriving while the sweep run-through is still in motion:
            # stop the table NOW and latch table_done; cam_SA_runthrough completes.
            self.io.set_table(False)
            self._table_done = True
            self.io.log(f"L{self.lane}: TA1@zero during run-through — table stopped at zero")

    def cam_SA_zero(self):           # sweep reached 360°/zero (cam SA -> C2A-31N)
        if self.state in (State.TABLE_FINISH, State.SPOTTING):
            self.io.set_sweep(False)

    def bin_full(self):              # BS: 10th pin delivered to bin (BS -> C2A-112cc)
        """Bin full (BS closes). On fresh-rack cycles (2nd/strike/foul), this is
        the gate to energize SP for the spotting revolution (§2: "After 10th pin
        to bin, BS closes -> SP spot relay energizes -> table spotting revolution").
        1st-ball respot doesn't spot a fresh rack, so BS is a no-op there.
        CONFIRM exact SP pulse-vs-continuous + table-spotting-rev timing on the
        bench (SP -> C1-35U/36Y)."""
        if self.state is State.TABLE_FINISH and self._needs_fresh_rack():
            if not self.io.interlock_ok():
                self.io.log(f"L{self.lane}: BS but interlock open — SP BLOCKED (safety)")
                return
            self.io.set_spot(True)
            # The spotting revolution needs the table driven. If the table already
            # stopped at zero (TA1 honored during run-through / TABLE_FINISH) this
            # re-energizes it; if it is still running this is a latch no-op.
            # CONFIRM SP-vs-table drive interplay on the bench.
            if not self._safe_table(True):
                self.io.set_spot(False)      # never leave SP latched with no revolution
                self._fault("table energize refused for spotting revolution")
                return
            self._enter(State.SPOTTING)
            self.io.log(f"L{self.lane}: BS@bin-full -> SP energized, spotting fresh rack")

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

        # GUARD_DELAY: after 3s (and GP closed) start the table down — or, with the
        # bench-gated sequence fix enabled, send the sweep straight into the
        # run-through on SECOND_BALL/FOUL (table stays at zero, §2).
        if self.state is State.GUARD_DELAY:
            if self.io.gp_closed() and (now - self._t_state) >= TIME_DELAY_S:
                if (SKIP_TABLE_DESCENT_ON_SECOND_BALL
                        and self.cycle in (Cycle.SECOND_BALL, Cycle.FOUL)):
                    if self._safe_sweep(True):       # refused -> stay; bounded below
                        self._table_done = True      # table never leaves zero
                        self._enter(State.RUNTHROUGH)
                        self.io.log(f"L{self.lane}: delay done -> sweep run-through "
                                    f"(fresh-rack: table stays at zero)")
                else:
                    if self._safe_table(True):       # refused -> stay; bounded below
                        self._enter(State.TABLE_DETECT)
                        self.io.log(f"L{self.lane}: delay done -> table down (detect)")
            # Bounded wait: GP never closing (wedged pin?) or a persistently refused
            # energize must surface as FAULT, not stall here silently forever.
            if self.state is State.GUARD_DELAY and (now - self._t_state) > GUARD_DELAY_MAX_S:
                self._fault(f"GUARD_DELAY > {GUARD_DELAY_MAX_S}s (GP open or energize refused)")
            return

        if self.state in MOTION_STATES:
            # Mid-motion interlock re-check: if the TB/SC echo goes bad while any
            # motion state is active, stop everything and latch FAULT — never let
            # the FSM and the physical machine silently diverge.
            if not self.io.interlock_ok():
                self._fault(f"interlock opened mid-motion ({self.state.value})")
                return
            # BS LEVEL poll (bench-gated): a bin that is ALREADY full at
            # TABLE_FINISH must still spot the fresh rack (the daemon's BS edge
            # never fires in that case). bin_full() re-checks state + interlock.
            if (POLL_BS_LEVEL_IN_TABLE_FINISH and self.state is State.TABLE_FINISH
                    and self._needs_fresh_rack() and self.io.bs_closed()):
                self.bin_full()
                if self.state is not State.TABLE_FINISH:
                    return
            # Safety backstop: any motion state stuck too long -> FAULT + power off.
            # Includes SPOTTING (SP energized) — a stuck spotting rev must also fault.
            if (now - self._t_state) > MAX_MOTION_S:
                self._fault(f"{self.state.value} > {MAX_MOTION_S}s (motion never completed)")


# --------------------- bench simulator (R1, no hardware) ------------------------
# Run:  python cycle_control_8270.py   (exit 0 = all asserts pass)
# Drives a fake machine that emits cam events on a timeline as the motors run,
# and injects BS (bin full) on fresh-rack cycles so the SP spotting path runs.
# Proves the state flow + the SP-on-fresh-rack logic + the interlock guard.
if __name__ == "__main__":
    import sys
    SWEEP_T = {'guard': 0.6, 'runthrough': 0.9, 'zero': 0.6}  # pretend timings
    TABLE_T = {'detect_to_260': 1.2, 'to_zero': 1.4}

    class SimIO:
        def __init__(self):
            self.t = 0.0; self.interlock = True; self.grip = 0
            self.spot_energized = False      # track SP for assertions
        def now(self): return self.t
        def log(self, m): print(f"  [{self.t:5.2f}] {m}")
        def set_sweep(self, on): print(f"      sweep={'ON' if on else 'off'}")
        def set_table(self, on): print(f"      table={'ON' if on else 'off'}")
        def set_spot(self, on):
            self.spot_energized = on
            print(f"      spot={'ON' if on else 'off'}")
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
    c.power_restore()
    assert c.state is State.MANUAL_INTERVENTION, "power restore must require First-Ball-Zero"
    c.first_ball_zero()
    assert c.state is State.READY and c.ball is Ball.FIRST

    def run_cycle(standing_mask, label):
        print(f"\n--- {label} (standing={standing_mask:010b}) ---")
        io.grip = standing_mask
        io.spot_energized = False
        c.on_ball()
        # timeline up to the sweep run-through stop:
        pre = [(SWEEP_T['guard'], c.cam_SB_guard),
               (TIME_DELAY_S + 0.1, lambda: None),          # poll() starts table
               (TABLE_T['detect_to_260'], c.cam_TA2_runthrough),
               (SWEEP_T['runthrough'], c.cam_SA_runthrough)]
        for dt, ev in pre:
            target = io.t + dt
            while io.t < target:
                c.poll(); io.t = round(io.t + 0.05, 2)
            ev()
        # fresh-rack cycles wait for BS (bin full) -> SP. Inject it now.
        fresh = c._needs_fresh_rack()
        if fresh:
            io.t = round(io.t + 0.3, 2)
            c.bin_full()
            assert c.state is State.SPOTTING, f"BS should enter SPOTTING (got {c.state})"
            assert io.spot_energized, "SP must be energized during spotting"
        # table returns to zero -> completes (from SPOTTING or TABLE_FINISH)
        for dt, ev in [(TABLE_T['to_zero'] * 0.5, c.cam_TA1_delayreset),
                       (TABLE_T['to_zero'] * 0.5, c.cam_TA1_zero)]:
            target = io.t + dt
            while io.t < target:
                c.poll(); io.t = round(io.t + 0.05, 2)
            ev()
        c.poll()
        if fresh:
            assert not io.spot_energized, "SP must be released after spotting"
        assert c.state is State.READY, f"cycle must end READY (got {c.state})"
        print(f"  => state={c.state.value} ball={c.ball.name} fresh_rack={fresh}")
        return c.ball

    # 1st ball leaves 7+10 -> respot held pins -> 2nd ball;
    # 2nd ball clears -> fresh rack (SP) -> back to 1st ball.
    b = run_cycle(0b0000000101, "first ball, 7+10 left")
    assert b is Ball.SECOND, "after 1st-ball-with-pins, expect 2nd ball"
    b = run_cycle(0b0000000000, "second ball, spare (all down)")
    assert b is Ball.FIRST, "after 2nd ball, expect reset to 1st ball"

    # Strike: 1st ball, no pins -> fresh rack (SP) -> back to 1st ball.
    b = run_cycle(0b0000000000, "strike (no pins on 1st)")
    assert b is Ball.FIRST, "after strike, expect reset to 1st ball"

    # Safety: ball ignored when interlock open.
    io.interlock = False
    st = c.state
    c.on_ball()
    assert c.state is st, "on_ball must be ignored with interlock open"
    io.interlock = True

    # --- R2: TA1 zero arriving DURING run-through must stop the table, and the
    # respot cycle completes when the sweep stop follows (event-order fix). ---
    print("\n--- R2: table zero-stop during RUNTHROUGH (respot ordering) ---")
    io.grip = 0b0000001000
    c.on_ball()
    c.cam_SB_guard()
    io.t = round(io.t + TIME_DELAY_S + 0.1, 2); c.poll()
    assert c.state is State.TABLE_DETECT
    c.cam_TA2_runthrough()
    assert c.state is State.RUNTHROUGH
    c.cam_TA1_zero()                    # table hits zero BEFORE sweep@270
    assert c.state is State.RUNTHROUGH, "TA1 in RUNTHROUGH must not change state"
    assert c._table_done, "TA1 in RUNTHROUGH must stop the table + latch table_done"
    c.cam_SA_runthrough()               # sweep stop completes the respot cycle
    assert c.state is State.READY and c.ball is Ball.SECOND, \
        f"respot completes once sweep also stops (got {c.state})"

    # --- R2: motion timeout -> FAULT; PBZ recovers (two deliberate presses) ---
    print("\n--- R2: FAULT recovery via PBZ ---")
    c.on_ball()                         # 2nd-ball cycle starts (sweep on)
    assert c.state is State.SWEEP_TO_GUARD
    io.t = round(io.t + MAX_MOTION_S + 0.2, 2); c.poll()
    assert c.state is State.FAULT, "stuck motion must FAULT"
    c.on_ball()
    assert c.state is State.FAULT, "ball in FAULT must be ignored"
    c.first_ball_zero()
    assert c.state is State.MANUAL_INTERVENTION, "PBZ in FAULT -> MANUAL_INTERVENTION"
    c.first_ball_zero()
    assert c.state is State.READY and c.ball is Ball.FIRST, "second PBZ -> READY"

    # --- R2: foul reclassification gated to the delivery window ---
    print("\n--- R2: foul window gating ---")
    io.grip = 0b0000000011              # pins left -> FIRST_BALL respot cycle
    c.on_ball()
    assert c.cycle is Cycle.FIRST_BALL
    c.cam_SB_guard()
    io.t = round(io.t + TIME_DELAY_S + 0.1, 2); c.poll()
    assert c.state is State.TABLE_DETECT
    c.cam_TA2_runthrough()              # mid-flight: respot in progress
    c.on_foul()                         # LATE foul (ball still FIRST)
    assert c.cycle is Cycle.FIRST_BALL, "late foul must NOT reclassify the in-flight respot"
    c.cam_TA1_zero()
    c.cam_SA_runthrough()
    assert c.state is State.READY and c.ball is Ball.SECOND
    c.first_ball_zero()                 # READY: toggles back to 1st ball (§5)
    assert c.ball is Ball.FIRST
    c.on_ball()
    c.on_foul()                         # foul during SWEEP_TO_GUARD = in window
    assert c.cycle is Cycle.FOUL, "foul in the delivery window reclassifies"

    # --- R2: refused energize must not advance; GUARD_DELAY wait is bounded ---
    print("\n--- R2: refused energize + bounded GUARD_DELAY ---")
    c2 = CycleController(22, io)
    c2.power_restore(); c2.first_ball_zero()
    c2.on_ball(); c2.cam_SB_guard()
    io.interlock = False
    io.t = round(io.t + TIME_DELAY_S + 0.2, 2); c2.poll()
    assert c2.state is State.GUARD_DELAY, "refused table energize must NOT advance state"
    io.t = round(io.t + GUARD_DELAY_MAX_S, 2); c2.poll()
    assert c2.state is State.FAULT, "bounded GUARD_DELAY must FAULT, not stall forever"
    io.interlock = True

    # --- R2: interlock opening mid-motion faults immediately ---
    print("\n--- R2: mid-motion interlock trip ---")
    c3 = CycleController(23, io)
    c3.power_restore(); c3.first_ball_zero()
    c3.on_ball()
    assert c3.state is State.SWEEP_TO_GUARD
    io.interlock = False
    c3.poll()
    assert c3.state is State.FAULT, "interlock open mid-motion must FAULT"
    io.interlock = True

    # --- R2: PBZ refused in MANUAL_INTERVENTION when interlock open ---
    print("\n--- R2: PBZ at-zero gate ---")
    c4 = CycleController(24, io)
    c4.power_restore()
    io.interlock = False
    c4.first_ball_zero()
    assert c4.state is State.MANUAL_INTERVENTION, "PBZ must be refused while interlock open"
    io.interlock = True
    c4.first_ball_zero()
    assert c4.state is State.READY

    # --- R2: wiring proof for the two BENCH-GATED switches (flipped here only) ---
    print("\n--- R2: bench-gated switches (sim-only flip) ---")
    SKIP_TABLE_DESCENT_ON_SECOND_BALL = True
    POLL_BS_LEVEL_IN_TABLE_FINISH = True
    c5 = CycleController(25, io)
    c5.power_restore(); c5.first_ball_zero(); c5.first_ball_zero()  # toggle -> 2nd ball
    assert c5.ball is Ball.SECOND
    io.spot_energized = False
    c5.on_ball(); c5.cam_SB_guard()
    io.t = round(io.t + TIME_DELAY_S + 0.1, 2); c5.poll()
    assert c5.state is State.RUNTHROUGH, "2nd ball: sweep direct to run-through (no descent)"
    assert c5._table_done, "table never left zero on the skip-descent path"
    c5.cam_SA_runthrough()
    assert c5.state is State.TABLE_FINISH
    c5.poll()                           # BS LEVEL poll (SimIO bin always full) -> spot
    assert c5.state is State.SPOTTING and io.spot_energized, "BS level poll spots the rack"
    c5.cam_TA1_zero()
    assert c5.state is State.READY and c5.ball is Ball.FIRST
    SKIP_TABLE_DESCENT_ON_SECOND_BALL = False
    POLL_BS_LEVEL_IN_TABLE_FINISH = False

    print("\nALL ASSERTS PASSED (1st-ball respot, 2nd-ball SP spot, strike SP spot, "
          "interlock guard, R2: TA1-in-runthrough ordering, FAULT/PBZ recovery, "
          "foul window, refused-energize, bounded GUARD_DELAY, mid-motion interlock, "
          "PBZ at-zero gate, bench-gated switch wiring).")
    sys.exit(0)
