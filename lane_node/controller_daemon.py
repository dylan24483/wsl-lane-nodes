#!/usr/bin/env python3
"""
controller_daemon.py — Phase 8b Track-B per-pair machine-control daemon (SKELETON).

Assembles, per lane/board, the three pieces that already exist + are tested:
    RP2040Link (rp2040_link.py)  +  MachineIO(rp2040=link) (controller_io.py)  +
    CycleController (cycle_control_8270.py)
and runs the real-time control loop:

    each tick (~50 Hz):
      link.apply_events(fsm)     # cam/ball edges from the RP2040 -> FSM
      read slow-input edges      # PBZ/BS/Foul from the MCP23017 -> FSM methods
      fsm.poll()                 # advance FSM + KICK THE NE555 (poll() kicks via io)
      io.arm(armed)              # power-down rule + RP2040 health gate the arm GPIO

⚠️ SKELETON / BENCH-GATED. Do NOT run against a live machine until the full
hardware safety chain is validated per docs/phase8b_pcb_revB_spec.md §12.9 and the
controller cutover runbook. Items marked  # CONFIRM  (pin numbers, I2C bus ids,
UART ports, slow-input polarity/debounce) are set at bench/cutover.

NOT yet wired: server/scoring reporting (Track A camera + lane_node.py websocket).
The controller (this daemon) and the scoring/server path must be unified at bench
— see TODO(server). This file deliberately stays a tight synchronous control loop;
scoring/IO-to-server is async and lives elsewhere.

SAFETY notes:
  * The NE555 watchdog is kicked ONLY from fsm.poll() inside the tick loop, so if
    the control loop stalls the kick stops -> NE555 drops the rail -> motion stops.
    That coupling is intentional (unlike the Track-A scoring node, where scoring
    must NOT be able to stop the machine).
  * RP2040_OK is a HARDWARE rail line driven by the firmware; a dead/!ok RP2040
    drops the rail regardless of this daemon. We additionally fault-safe in software
    (drop ARM, log) so the FSM and operator see it.

Run the off-hardware self-test:   python controller_daemon.py --selftest
Run for real (on the Pi):         python controller_daemon.py        # needs gpiozero/smbus/pyserial
One-board bench rig (D3):         python controller_daemon.py --lanes 21   # or WSL_LANES=21
"""
from __future__ import annotations
import argparse
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import CycleController, State
from controller_io import MachineIO, RecordingIO, ShadowIO
from rp2040_link import RP2040Link
from flight_recorder import FlightRecorder
from cam_telemetry import CamTelemetry

log = logging.getLogger("controller_daemon")

# Shadow/canary soak (idea #11). When WSL_CONTROLLER_SHADOW is truthy the FSM runs
# on the REAL inputs but every output is routed to a record-only shim (ShadowIO) and
# the relay-enable ARM is hard-held LOW — no relay is ever energized. DEFAULT OFF:
# it must be impossible to accidentally run live. See ShadowIO in controller_io.py.
SHADOW_ENV = "WSL_CONTROLLER_SHADOW"
_FALSEY = ("0", "false", "no", "off", "")


def _shadow_enabled():
    return os.environ.get(SHADOW_ENV, "0").strip().lower() not in _FALSEY


# One-board bench mode (readiness item D3). WSL_LANES env / --lanes CLI select a
# SUBSET of DEFAULT_BOARDS *before* construction, so a single-board rig never
# opens the absent board's I2C bus / UART. CLI beats env; unset/empty = all.
LANES_ENV = "WSL_LANES"


def _parse_lanes(spec):
    """'21' / '21,22' -> [21, 22] (deduped, order kept). None/blank -> None (= all).
    Raises ValueError on a non-integer token."""
    if spec is None or not spec.strip():
        return None
    lanes = []
    for tok in spec.replace(",", " ").split():
        n = int(tok)
        if n not in lanes:
            lanes.append(n)
    return lanes


def _select_boards(configs, lanes):
    """Filter board configs to the requested lanes (None = all). An unknown lane
    is a hard error — a typo must not silently run the wrong board."""
    if lanes is None:
        return list(configs)
    by_lane = {c.lane: c for c in configs}
    unknown = sorted(set(lanes) - set(by_lane))
    if unknown:
        raise ValueError(f"unknown lane(s) {unknown}; available: {sorted(by_lane)}")
    return [by_lane[n] for n in lanes]


# Map an FSM state TRANSITION to the discrete mechanical event it represents, for the
# cam-timing telemetry (idea #15). Observe-only: derived from the state the daemon
# already holds, so no new event source and no touch to rp2040_link/the FSM. Keyed by
# (prev_state, new_state) -> telemetry event name. The READY arrival closes the cycle.
_STATE_EVENTS = {
    (State.READY,           State.SWEEP_TO_GUARD): "ball",         # SS / ball thrown
    (State.SWEEP_TO_GUARD,  State.GUARD_DELAY):    "cam:SB",       # sweep@66 guard
    (State.GUARD_DELAY,     State.TABLE_DETECT):   "table_start",  # settle done, table down
    (State.TABLE_DETECT,    State.RUNTHROUGH):     "cam:TA2",      # table@260, runthrough
    (State.RUNTHROUGH,      State.TABLE_FINISH):   "cam:SA",       # sweep@270 stop
    (State.TABLE_FINISH,    State.SPOTTING):       "bs",           # bin full -> spot
}

# States in which the relay-enable ARM must stay de-asserted (power-down rule §5).
DISARMED_STATES = (State.POWER_OFF, State.MANUAL_INTERVENTION, State.FAULT)

# NE555 kick pulse width per tick. The kick pin must REST LOW so a stalled/frozen
# daemon (SIGSTOP, scheduler wedge, GC pause at the wrong moment) can never hold
# the line HIGH and permanently defeat the watchdog — the old toggle() left the
# pin latched HIGH 50% of the time. A bounded on->sleep->off pulse guarantees a
# frozen process leaves the pin LOW (or HIGH for at most one pulse width).
# CONFIRM @ bench (§12.9): 2 ms must discharge C11 through Q12+D15 (8a proved
# 50 ms works; 50 ms is NOT usable inline at 50 Hz). If 2 ms turns out too short
# the failure mode is fail-SAFE: the NE555 expires and drops the rail.
WDOG_PULSE_S = 0.002

# Consecutive tick() exceptions tolerated per board before that board alone is
# safety-tripped (safe_off + skipped); the healthy board keeps running. A tripped
# board also stops getting its NE555 kick -> its hardware rail drops by itself.
TICK_ERROR_BUDGET = 3

# Slow inputs the daemon edge-detects on the MCP and turns into FSM method calls.
# (Cams + ball arrive via the RP2040 link; grippers/GP are polled inside the FSM.)
#   name -> FSM action on a rising (asserted) edge
def _slow_actions(fsm, link):
    def _pbz():
        # Operator re-arm. FAULT-aware: PBZ in FAULT now recovers via the FSM
        # (FAULT -> MANUAL_INTERVENTION; second press -> READY). The firmware
        # fault latch is cleared ONLY when the FSM actually leaves FAULT, so the
        # two fault latches can never be made to disagree; the firmware fault
        # code is logged BEFORE it is cleared.
        was_fault = fsm.state is State.FAULT
        fw_flt = link.fault()
        fsm.first_ball_zero()
        if was_fault:
            if fsm.state is State.FAULT:
                fsm.io.log(f"L{fsm.lane}: PBZ in FAULT did not transition — "
                           f"firmware latch NOT cleared (flt={fw_flt!r})")
                return
            fsm.io.log(f"L{fsm.lane}: PBZ acknowledged FAULT (fw flt={fw_flt!r}) "
                       f"-> {fsm.state.value}; clearing firmware latch")
        link.clear()

    return {
        "PBZ":  _pbz,                                           # operator re-arm (+ FW CLEAR, gated)
        "BS":   fsm.bin_full,                                   # 10th pin to bin -> spot (fresh rack)
        "Foul": fsm.on_foul,                                    # Radaray foul beam
        # "PBC", "OS", "TENTH", "MAN_*" -> future (no FSM handler yet)
    }


@dataclass
class BoardConfig:
    lane: int
    i2c_bus: int        # /dev/i2c-N to this board's 3x MCP23017 (0x20/0x21/0x22)
    uart_port: str      # serial device to THIS board's RP2040 (115200 8N1)
    arm_pin: int        # Pi BCM GPIO -> relay-enable ARM for this board (HIGH=permit)
    wdog_pin: int       # Pi BCM GPIO -> this board's NE555 watchdog kick


# Per-pair Pi pin plan.  Source of truth: docs/phase8_channel_allocation.md §4
# ("Pi GPIO budget").  The two non-default devices below only EXIST once the Pi
# boot config is applied (2nd I2C bus via dtoverlay=i2c-gpio + a 2nd UART enabled)
# -> see docs/phase8_pi_provisioning.md for the exact config.txt + the full,
# deconflicted per-pin table.
#
# Per-field confidence:
#   FIRM     board-21 i2c_bus=1  -> Pi hardware I2C on GPIO2/3 (present on every Pi).
#   FIRM     board-21 wdog_pin=12 -> the existing, bench-validated kick pin
#            (lane_node.WATCHDOG_KICK_PIN / relay_cleanup.WATCHDOG_KICK_PIN).
#   CONFIRM  @ bench bring-up (spec 12.9): the 2nd I2C bus number + its i2c-gpio
#            SDA/SCL pins, BOTH RP2040 UART device names, the two arm GPIOs, and
#            per-board-vs-shared watchdog.  The values below are the *planned*
#            assignment -- free BCM pins chosen to avoid the INT lines (GPIO23/24/25/16)
#            and the 8a relay pins (GPIO23/24/25/27) -- NOT yet verified on the wired Pi.
DEFAULT_BOARDS = [
    # FIRM: i2c_bus=1 (Pi hw I2C, GPIO2/3) + wdog_pin=12 (existing bench-validated kick).
    BoardConfig(lane=21, i2c_bus=1, uart_port="/dev/ttyAMA0", arm_pin=26, wdog_pin=12),
    # CONFIRM: bus-3 = the dtoverlay=i2c-gpio bus; uart/arm/wdog are planned free pins.
    BoardConfig(lane=22, i2c_bus=3, uart_port="/dev/ttyAMA1", arm_pin=13, wdog_pin=6),
]


class BoardController:
    """One lane/board: link + io + FSM + the arm/watchdog GPIOs, plus the per-tick
    control logic. `sim=True` uses RecordingIO + a no-serial link so the assembly
    runs + self-tests off-Pi."""

    def __init__(self, cfg: BoardConfig, *, sim: bool = False, shadow=None,
                 cam_sink=None):
        self.cfg = cfg
        self.sim = sim
        self._wdog = None
        self._arm_led = None
        self.shadow = _shadow_enabled() if shadow is None else bool(shadow)

        # Flight recorder (idea #10): observe-only, bounded, default ON. Injected into
        # the io so every output change + arm is captured; dumped on a safety trip.
        self.recorder = FlightRecorder(cfg.lane)

        if sim:
            self.link = RP2040Link()                       # no serial; feed via feed_line()
            self.io = RecordingIO(rp2040=self.link, recorder=self.recorder)
        else:
            from gpiozero import LED                       # lazy: Pi-only
            self._arm_led = LED(cfg.arm_pin)               # de-asserted by default
            self._wdog = LED(cfg.wdog_pin)
            self.link = RP2040Link(port=cfg.uart_port)
            self.io = MachineIO(
                cfg.lane, cfg.i2c_bus, rp2040=self.link,
                watchdog_kick=self._kick_wdog,             # poll() calls this
                arm_relays=self._set_arm,
                recorder=self.recorder,
            )
            self.link.start()                              # background serial reader

        # SHADOW/CANARY SOAK (idea #11): wrap the real io so the FSM drives NOTHING.
        # The wrapper records every command the FSM WOULD have issued and hard-holds
        # the real ARM LOW. Default OFF (env gate) — impossible to run live by accident.
        if self.shadow:
            self.io = ShadowIO(self.io, recorder=self.recorder)
            log.warning("L%s: SHADOW MODE active (%s set) — FSM runs on real inputs but "
                        "drives NOTHING; ARM hard-held LOW", cfg.lane, SHADOW_ENV)

        # Cam-timing telemetry (idea #15): observe-only, bounded. Fed from FSM state
        # transitions (which the daemon already holds) -> per-cycle intervals + drift
        # alarm. Shares the flight recorder so timing rows + drift land in dumps too.
        self.telemetry = CamTelemetry(cfg.lane, recorder=self.recorder, sink=cam_sink)

        self.fsm = CycleController(cfg.lane, self.io)
        self.fsm.power_restore()                           # power-down rule: come up disarmed
        self._prev_state = self.fsm.state                  # for telemetry transition edges
        self._actions = _slow_actions(self.fsm, self.link)
        # Baseline the slow-input edge detector from the ACTUAL input levels at
        # startup (review #28): an input already asserted when the daemon comes
        # up (stuck/shorted/miswired PBZ, inverted polarity) must NEVER be
        # synthesized into a rising edge on tick 1 — a phantom PBZ would walk
        # MANUAL_INTERVENTION -> READY and auto-arm the lane on every restart,
        # defeating the power-down rule the systemd auto-restart policy relies
        # on. Only a transition OBSERVED while running counts as an edge; an
        # initially-asserted input is logged LOUDLY and must deassert then
        # re-assert to act. A read failure here propagates -> _build_boards
        # skips the board (never ticked, NE555 never kicked = fail-safe).
        # Sim rigs (RecordingIO.slow starts empty) baseline all-False as before.
        self._prev_slow = {}
        for name in self._actions:
            cur = bool(self.io.read_input(name))
            if cur:
                log.error("L%s: slow input %r ALREADY ASSERTED at daemon start "
                          "(stuck button / miswire / inverted polarity?) — NO edge "
                          "synthesized; it must deassert then re-assert to act",
                          cfg.lane, name)
            self._prev_slow[name] = cur
        self._maxrun_refused = False   # review #30: one-time log latch for the arm refusal
        self._was_healthy = True
        self.failed = False        # set by run() when TICK_ERROR_BUDGET is exhausted
        self.tick_errors = 0       # consecutive tick() exceptions (reset on success)

    # ---- real-hardware GPIO callbacks -------------------------------------
    def _kick_wdog(self):
        if self._wdog is not None:
            # Bounded pulse, resting LOW (see WDOG_PULSE_S). Never toggle(): a
            # stall with the pin latched HIGH would defeat the NE555 forever.
            self._wdog.on()
            time.sleep(WDOG_PULSE_S)
            self._wdog.off()

    def _set_arm(self, on):
        if self._arm_led is not None:
            self._arm_led.value = 1 if on else 0

    # ---- per-tick control logic -------------------------------------------
    def _slow_edges(self):
        for name, action in self._actions.items():
            cur = bool(self.io.read_input(name))
            if cur and not self._prev_slow[name]:          # rising (asserted) edge  # CONFIRM debounce
                action()
            self._prev_slow[name] = cur

    def tick(self):
        healthy = self.link.health_ok()

        if not healthy:
            # RP2040 unhealthy: RP_OK has already dropped the HARDWARE rail. Make it a real
            # SOFTWARE safety trip too — force motion outputs OFF (clears the relay latches)
            # and latch the FSM into MANUAL_INTERVENTION so recovery REQUIRES a deliberate
            # First-Ball-Zero. Without this, a heartbeat blip drops ARM while sweep is still
            # latched, then silently re-arms with the stale latch -> uncommanded motion.
            if self._was_healthy:
                self.io.log(f"L{self.cfg.lane}: RP2040 link LOST "
                            f"(fault={self.link.fault()!r} alive={self.link.is_alive()} "
                            f"rp_ok={self.link.rp_ok()}) -> SAFETY TRIP: motors off, require First-Ball-Zero")
                self.fsm.power_restore()      # _all_motors_off() (clears latches) + MANUAL_INTERVENTION
                self._on_safety_trip("rp2040_link_lost")   # flight-recorder dump (observe-only)
            self._was_healthy = False
            self.io.arm(False)
            self.link.apply_events(self.fsm)  # drain the queue; FSM ignores events when not READY
            self.fsm.poll()                   # keep kicking the NE555 (the Pi itself is alive)
            self._observe()                   # instrumentation (idea #10/#15): never affects control
            return

        if not self._was_healthy:
            self.io.log(f"L{self.cfg.lane}: RP2040 link recovered -> awaiting First-Ball-Zero")
        self._was_healthy = True

        self.link.apply_events(self.fsm)      # cam/ball -> FSM (single-threaded here)
        self._slow_edges()                    # PBZ/BS/Foul -> FSM
        self.fsm.poll()                       # advance FSM + kick NE555 via io
        # Arm gate (review #30): a KNOWN firmware/FSM max-run desync (firmware
        # maxrun_ms below the FSM's MAX_MOTION_S) means the firmware backstop
        # would kill legitimate motions mid-cycle — REFUSE to arm until the
        # constants are reconciled, exactly as maxrun_ok()'s contract specifies.
        # Unknown (v0.1.0 firmware / sim) returns True, so behavior is unchanged
        # unless a desync is positively known. Safe direction = refuse.
        want_arm = self.fsm.state not in DISARMED_STATES
        if want_arm:
            mr_ok = self.link.maxrun_ok()
            if not mr_ok and not self._maxrun_refused:
                log.error("L%s: REFUSING to arm — firmware maxrun_ms=%s is below the "
                          "FSM's MAX_MOTION_S (constants desynchronized; reconcile + "
                          "reflash before arming)", self.cfg.lane, self.link.maxrun_ms())
            elif mr_ok and self._maxrun_refused:
                log.info("L%s: max-run ceiling reconciled — arm no longer refused",
                         self.cfg.lane)
            self._maxrun_refused = not mr_ok
            want_arm = mr_ok
        self.io.arm(want_arm)
        self._observe()                       # instrumentation (idea #10/#15): never affects control

    # ---- instrumentation (OBSERVE-ONLY; idea #10 flight recorder + #15 cam timing) --
    def _observe(self):
        """Post-tick observation: record FSM state transitions, feed cam-timing
        telemetry off those transitions, finalize a cycle on READY arrival, and dump
        the flight recorder on a FAULT entry. Drives NOTHING and never raises into the
        control loop — a bug here cannot affect machine control or fail-safety."""
        try:
            new = self.fsm.state
            prev = self._prev_state
            if new is prev:
                return
            self._prev_state = new
            now = self.io.now()
            # 1) record the transition in the flight recorder (forensics timeline)
            self.recorder.record("state", new.value, prev.value)
            # 2) cam-timing telemetry: map the transition to a discrete event
            ev = _STATE_EVENTS.get((prev, new))
            if ev is not None:
                self.telemetry.on_event(ev, now)
            # 3) cycle boundary: arriving back at READY finalizes the cycle's intervals
            if new is State.READY and prev not in (State.MANUAL_INTERVENTION, State.POWER_OFF):
                self.telemetry.end_cycle()
            # 3b) aborted cycle: a FAULT / safety trip / power-off abandons the
            # cycle mid-flight, and its recovery path (MANUAL_INTERVENTION ->
            # READY) is excluded from end_cycle above — discard the open
            # intervals WITHOUT folding, so a stale 'ball' timestamp can't fold
            # a minutes-long garbage sample into the drift baselines (observe-only).
            elif new in (State.FAULT, State.MANUAL_INTERVENTION, State.POWER_OFF):
                self.telemetry.abort_cycle()
            # 4) FAULT entry: dump the black box (best-effort)
            if new is State.FAULT and prev is not State.FAULT:
                self._on_safety_trip("fsm_fault")
        except Exception:
            log.debug("L%s observe() swallowed", self.cfg.lane, exc_info=True)

    def _on_safety_trip(self, reason):
        """Flush the flight recorder on a safety trip / fault. Best-effort, bounded,
        never raises. Captures FSM state + the firmware fault for the dump context.
        dump_async (review #21/#54): the snapshot copy happens here (microseconds);
        the disk write runs on a writer thread — an SD-card stall during one
        board's dump must not freeze the shared tick loop (the OTHER lane's cam
        dispatch, fsm.poll() backstops and NE555 kick)."""
        try:
            self.recorder.dump_async(reason=reason, extra={
                "fsm_state": getattr(self.fsm.state, "value", "?"),
                "fsm_cycle": getattr(getattr(self.fsm, "cycle", None), "value", None),
                "fsm_ball": getattr(getattr(self.fsm, "ball", None), "name", None),
                "fw_fault": self.link.fault(),
                "rp_ok": self.link.rp_ok(),
                "shadow": self.shadow,
            })
        except Exception:
            log.debug("L%s _on_safety_trip swallowed", self.cfg.lane, exc_info=True)

    # ---- shutdown ----------------------------------------------------------
    def safe_off(self):
        # FIRST: force the NE555 kick pin LOW (review #26). _kick_wdog is
        # on() -> sleep -> off(); if the exception that tripped this board fired
        # between on() and off() (the same GPIO-write fault class that exhausts
        # the error budget), the pad latches HIGH and level-holds the NE555
        # alive forever — a tripped board inside a still-running daemon never
        # reaches controller_cleanup.py, so this is the only place to drop it.
        for step in (
            lambda: self._wdog.off() if self._wdog is not None else None,
            lambda: self.io.arm(False),
            lambda: self.io.all_off() if hasattr(self.io, "all_off") else None,
            self.link.stop_all,
            self.link.close,
        ):
            try:
                step()
            except Exception as e:
                log.warning("L%s shutdown step failed: %s", self.cfg.lane, e)


def run(boards, hz: float = 50.0):
    """Tick loop. Returns the process exit code: 0 on an operator stop
    (SIGTERM/SIGINT), 1 when ALL boards safety-tripped — the unit is
    Restart=on-failure, so only a NONZERO exit gets the promised systemd
    restart (review #27; matches the D3 zero-boards return 1)."""
    period = 1.0 / hz
    stop = {"flag": False}
    rc = 0

    def _sig(_signum, _frame):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    log.info("controller_daemon up: lanes=%s @ %.0f Hz", [b.cfg.lane for b in boards], hz)
    try:
        while not stop["flag"]:
            t0 = time.monotonic()
            for b in boards:
                # Per-board fault isolation: a transient I2C/serial exception on
                # one board must not crash the daemon and safety-trip BOTH lanes.
                # On budget exhaustion, trip ONLY this board (safe_off + skip;
                # its NE555 kick stops too, so its hardware rail drops by itself)
                # and keep the healthy board running.
                if b.failed:
                    continue
                try:
                    b.tick()
                    b.tick_errors = 0
                except Exception as e:
                    b.tick_errors += 1
                    log.exception("L%s tick raised (%d/%d consecutive)",
                                  b.cfg.lane, b.tick_errors, TICK_ERROR_BUDGET)
                    # flight recorder: capture the exception in the timeline (observe-only)
                    try:
                        b.recorder.record("tick_error", type(e).__name__, str(e)[:120])
                    except Exception:
                        pass
                    if b.tick_errors >= TICK_ERROR_BUDGET:
                        log.error("L%s tick error budget exhausted -> SAFETY TRIP "
                                  "this board (outputs off, ARM dropped, kick stops); "
                                  "other board continues", b.cfg.lane)
                        b._on_safety_trip("tick_error_budget")   # dump black box
                        b.failed = True
                        b.safe_off()
            if all(b.failed for b in boards):
                log.error("ALL boards safety-tripped -> exiting 1 "
                          "(Restart=on-failure restarts only on nonzero)")
                rc = 1
                break
            dt = time.monotonic() - t0
            if dt < period:
                time.sleep(period - dt)
    finally:
        # Stop kicking (loop already exiting) -> NE555 drops the rail; plus explicit safe-off.
        log.info("controller_daemon shutting down -> safe-off all boards")
        for b in boards:
            b.safe_off()
        # After safe-off: give any in-flight async black-box writers a moment to
        # land before the process (and its daemon threads) dies. Observe-only.
        for b in boards:
            try:
                b.recorder.flush(timeout=2.0)
            except Exception:
                pass
    return rc


def _build_boards(configs):
    """Construct a BoardController per config, isolating open failures (D3): a
    board whose hardware won't open (missing I2C bus / UART on a partial bench
    rig) is logged LOUDLY and skipped. A skipped board is never ticked -> its
    NE555 never gets kicked -> its safety rail stays down = fail-safe by hardware."""
    boards = []
    for cfg in configs:
        try:
            boards.append(BoardController(cfg))
        except Exception:
            log.exception("L%s: board bring-up FAILED (i2c_bus=%s uart=%s) -> SKIPPED; "
                          "never ticked, NE555 never kicked, rail stays down (fail-safe)",
                          cfg.lane, cfg.i2c_bus, cfg.uart_port)
    return boards


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 8b Track-B controller daemon (skeleton)")
    ap.add_argument("--selftest", action="store_true", help="run the off-hardware assembly self-test and exit")
    ap.add_argument("--hz", type=float, default=50.0, help="control loop rate")
    ap.add_argument("--lanes", default=None,
                    help=f"comma-separated lane subset (e.g. '21'); overrides {LANES_ENV}; "
                         "default = all of DEFAULT_BOARDS")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.selftest:
        return _selftest()

    spec = args.lanes if args.lanes is not None else os.environ.get(LANES_ENV)
    try:
        configs = _select_boards(DEFAULT_BOARDS, _parse_lanes(spec))
    except ValueError as e:
        log.error("bad lane selection %r: %s", spec, e)
        return 1
    boards = _build_boards(configs)                             # real hardware
    if not boards:
        log.error("ZERO boards came up (requested lanes=%s) -> exiting 1",
                  [c.lane for c in configs])
        return 1
    return run(boards, hz=args.hz)   # nonzero on all-boards-tripped (review #27)


# --------------------------------------------------------------------------
# Off-hardware self-test: assemble in sim mode + drive a full strike cycle
# entirely through the daemon's tick() (RP2040 events + MCP slow inputs).
# --------------------------------------------------------------------------
def _selftest():
    from cycle_control_8270 import Cycle, Ball, TIME_DELAY_S
    n = {"c": 0, "f": 0}

    def chk(cond, msg):
        n["c"] += 1
        print(("  ok:   " if cond else "  FAIL: ") + msg)
        if not cond:
            n["f"] += 1

    print("== controller_daemon self-test (sim) ==")
    bc = BoardController(BoardConfig(21, 1, "sim", 0, 0), sim=True)
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "boots into MANUAL_INTERVENTION (power-down rule)")

    bc.link.feed_line('{"ev":"hb","ok":1}')              # RP2040 healthy
    bc.tick()
    chk(bc.io.armed is False, "stays DISARMED before First-Ball-Zero")

    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY, "PBZ -> READY")
    chk("CLEAR" in bc.link.sent, "PBZ also sends CLEAR to the firmware")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.io.armed is True, "ARMED once READY + RP2040 healthy")

    bc.io.grippers = 0                                    # strike (no pins standing)
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.fsm.state is State.SWEEP_TO_GUARD, "ball event -> SWEEP_TO_GUARD")
    chk("RUN S" in bc.link.sent, "sweep energize -> RUN S sent to firmware")

    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.GUARD_DELAY, "SB trip -> GUARD_DELAY")
    chk("STOP S" in bc.link.sent, "sweep stop at guard -> STOP S sent")

    bc.io.advance(TIME_DELAY_S + 0.1)
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.fsm.state is State.TABLE_DETECT, "3s delay -> TABLE_DETECT")

    bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f"}'); bc.tick()
    chk(bc.fsm.cycle is Cycle.STRIKE and bc.fsm.state is State.RUNTHROUGH, "TA2 -> strike + RUNTHROUGH")
    bc.link.feed_line('{"ev":"cam","id":"SA","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.TABLE_FINISH, "SA -> TABLE_FINISH")

    bc.io.slow["BS"] = True; bc.tick(); bc.io.slow["BS"] = False
    chk(bc.fsm.state is State.SPOTTING, "BS -> SPOTTING (fresh rack)")
    bc.link.feed_line('{"ev":"cam","id":"TA1","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.READY and bc.fsm.ball is Ball.FIRST, "TA1 -> cycle complete, READY")

    # --- P1 safety: RP2040 health loss mid-cycle must force motors OFF + require re-arm ---
    # (Codex repro: mid-cycle rp_ok:0 left armed=False with sweep latched True, then silently
    #  re-armed with the stale latch on recovery. Fixed: health loss = full safety trip.)
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.io.armed is True, "(setup) READY + armed before mid-cycle test")
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.io.outputs.get("sweep") is True, "(setup) mid-cycle: sweep ON")
    bc.link.feed_line('{"ev":"rp_ok","v":0}'); bc.tick()            # health loss mid-cycle
    chk(bc.io.outputs.get("sweep") is False, "health loss forces sweep OFF (clears relay latch)")
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "health loss latches FSM -> MANUAL_INTERVENTION")
    chk(bc.io.armed is False, "health loss drops ARM")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()             # heartbeat returns OK
    chk(bc.fsm.state is State.MANUAL_INTERVENTION and bc.io.armed is False,
        "recovery does NOT auto-rearm; stays MANUAL_INTERVENTION + disarmed")
    chk(bc.io.outputs.get("sweep") is False, "sweep stays OFF after recovery (no stale-latch resume)")
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False  # deliberate re-arm
    chk(bc.fsm.state is State.READY and bc.io.armed is True, "deliberate PBZ recovers -> READY + armed")

    # --- P2/P4: FSM FAULT is recoverable from the daemon via double-PBZ ---
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.fsm.state is State.SWEEP_TO_GUARD, "(setup) cycle started for FAULT-recovery test")
    bc.io.advance(9.0)                                              # exceed MAX_MOTION_S
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.fsm.state is State.FAULT, "stuck motion -> FAULT via the poll backstop")
    chk(bc.io.armed is False, "FAULT drops ARM (DISARMED_STATES)")
    clears = bc.link.sent.count("CLEAR")
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "PBZ in FAULT -> MANUAL_INTERVENTION")
    chk(bc.link.sent.count("CLEAR") == clears + 1,
        "firmware latch cleared exactly once, AFTER the FSM left FAULT")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()              # PBZ released (edge re-arms)
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY and bc.io.armed is True, "second PBZ -> READY + armed")

    # --- review #30: a KNOWN firmware/FSM max-run desync must REFUSE to arm ---
    bc2 = BoardController(BoardConfig(21, 1, "sim", 0, 0), sim=True)
    bc2.link.feed_line('{"ev":"boot","fw":"test","maxrun_ms":1000}')   # << MAX_MOTION_S
    bc2.link.feed_line('{"ev":"hb","ok":1}')
    bc2.io.slow["PBZ"] = True; bc2.tick(); bc2.io.slow["PBZ"] = False
    chk(bc2.fsm.state is State.READY, "(setup) maxrun-desync rig reaches READY")
    bc2.link.feed_line('{"ev":"hb","ok":1}'); bc2.tick()
    chk(bc2.io.armed is False,
        "maxrun desync (fw 1000ms < FSM MAX_MOTION_S) REFUSES to arm despite READY")

    print(f"\n{n['c'] - n['f']}/{n['c']} checks passed" + ("  <<< FAILURES" if n["f"] else ""))
    return 1 if n["f"] else 0


if __name__ == "__main__":
    sys.exit(main())
