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
"""
from __future__ import annotations
import argparse
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import CycleController, State
from controller_io import MachineIO, RecordingIO
from rp2040_link import RP2040Link

log = logging.getLogger("controller_daemon")

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

    def __init__(self, cfg: BoardConfig, *, sim: bool = False):
        self.cfg = cfg
        self.sim = sim
        self._wdog = None
        self._arm_led = None

        if sim:
            self.link = RP2040Link()                       # no serial; feed via feed_line()
            self.io = RecordingIO(rp2040=self.link)
        else:
            from gpiozero import LED                       # lazy: Pi-only
            self._arm_led = LED(cfg.arm_pin)               # de-asserted by default
            self._wdog = LED(cfg.wdog_pin)
            self.link = RP2040Link(port=cfg.uart_port)
            self.io = MachineIO(
                cfg.lane, cfg.i2c_bus, rp2040=self.link,
                watchdog_kick=self._kick_wdog,             # poll() calls this
                arm_relays=self._set_arm,
            )
            self.link.start()                              # background serial reader

        self.fsm = CycleController(cfg.lane, self.io)
        self.fsm.power_restore()                           # power-down rule: come up disarmed
        self._actions = _slow_actions(self.fsm, self.link)
        self._prev_slow = {name: False for name in self._actions}
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
            self._was_healthy = False
            self.io.arm(False)
            self.link.apply_events(self.fsm)  # drain the queue; FSM ignores events when not READY
            self.fsm.poll()                   # keep kicking the NE555 (the Pi itself is alive)
            return

        if not self._was_healthy:
            self.io.log(f"L{self.cfg.lane}: RP2040 link recovered -> awaiting First-Ball-Zero")
        self._was_healthy = True

        self.link.apply_events(self.fsm)      # cam/ball -> FSM (single-threaded here)
        self._slow_edges()                    # PBZ/BS/Foul -> FSM
        self.fsm.poll()                       # advance FSM + kick NE555 via io
        self.io.arm(self.fsm.state not in DISARMED_STATES)

    # ---- shutdown ----------------------------------------------------------
    def safe_off(self):
        for step in (
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
    period = 1.0 / hz
    stop = {"flag": False}

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
                except Exception:
                    b.tick_errors += 1
                    log.exception("L%s tick raised (%d/%d consecutive)",
                                  b.cfg.lane, b.tick_errors, TICK_ERROR_BUDGET)
                    if b.tick_errors >= TICK_ERROR_BUDGET:
                        log.error("L%s tick error budget exhausted -> SAFETY TRIP "
                                  "this board (outputs off, ARM dropped, kick stops); "
                                  "other board continues", b.cfg.lane)
                        b.failed = True
                        b.safe_off()
            if all(b.failed for b in boards):
                log.error("ALL boards safety-tripped -> exiting (systemd restarts)")
                break
            dt = time.monotonic() - t0
            if dt < period:
                time.sleep(period - dt)
    finally:
        # Stop kicking (loop already exiting) -> NE555 drops the rail; plus explicit safe-off.
        log.info("controller_daemon shutting down -> safe-off all boards")
        for b in boards:
            b.safe_off()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 8b Track-B controller daemon (skeleton)")
    ap.add_argument("--selftest", action="store_true", help="run the off-hardware assembly self-test and exit")
    ap.add_argument("--hz", type=float, default=50.0, help="control loop rate")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.selftest:
        return _selftest()

    boards = [BoardController(cfg) for cfg in DEFAULT_BOARDS]   # real hardware
    run(boards, hz=args.hz)
    return 0


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

    print(f"\n{n['c'] - n['f']}/{n['c']} checks passed" + ("  <<< FAILURES" if n["f"] else ""))
    return 1 if n["f"] else 0


if __name__ == "__main__":
    sys.exit(main())
