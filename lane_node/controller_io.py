#!/usr/bin/env python3
"""
controller_io.py — the hardware `io` object for cycle_control_8270.CycleController.

The FSM is written entirely against an abstract `io` interface (see the docstring
in cycle_control_8270.CycleController). This module provides the CONCRETE
implementations of that interface:

  * MachineIO   — real hardware: MCP23017 expanders (relays + lamps + slow inputs)
                  via the per-board I²C bus, the RP2040 co-processor (fast cam/ball
                  inputs + cam-stop enforcement), and the NE555 watchdog kick.
  * RecordingIO — a no-hardware fake that records every output + serves scripted
                  inputs, for bench-testing the FSM off-Pi (richer than the inline
                  SimIO in cycle_control_8270's __main__).

Channel assignments come from `docs/phase8_channel_allocation.md` (per-board,
self-contained: 3× MCP23017 @ 0x20–0x23 on the board's own I²C bus + 1 RP2040).

⚠️ SAFETY: this module is the software half. The hardware half (relay-enable
rail, NE555 watchdog, RP2040 cam-stop, regenerative braking) is NEVER bypassed
here. The TB/SC hardware interlock is PLANNED only — design open per
docs/phase8_interlock_redesign.md; until it lands, `io.interlock_ok()` is the
ONLY TB/SC guard, not a secondary echo. MachineIO is
NOT to drive a live machine until the full hardware safety chain is bench-proven
(see docs/phase8_PLAN_A_full_replacement.md + the off-live validation gate #17).

Hardware deps (Pi only): `smbus2` (or `smbus`) for the MCP23017s. Imported
lazily so this module loads + the RecordingIO path tests on any machine.
"""
from __future__ import annotations
import time
import logging

try:
    from flight_recorder import NULL_RECORDER
except Exception:  # pragma: no cover - flight_recorder is optional, never fatal
    class _NR:                       # inert fallback so the io stays usable standalone
        enabled = False
        def record(self, *a, **k): pass
        def dump(self, *a, **k): return None
        def snapshot(self): return []
    NULL_RECORDER = _NR()

log = logging.getLogger("controller_io")

# ---------------------------------------------------------------------------
# MCP23017 register + bit constants (bank-0 / IOCON.BANK=0 default mapping)
# ---------------------------------------------------------------------------
_IODIRA, _IODIRB = 0x00, 0x01
_GPPUA, _GPPUB = 0x0C, 0x0D
_GPIOA, _GPIOB = 0x12, 0x13
_OLATA, _OLATB = 0x14, 0x15

# Per-board MCP23017 I²C addresses (each board repeats these on its own bus).
ADDR_IN_A  = 0x20   # grippers GS1-10 + GP/BS/OS/PBZ/PBC/Foul
ADDR_IN_B  = 0x21   # 10th + manual + spare
ADDR_OUT_A = 0x22   # 7 relays + 4 status lamps
ADDR_OUT_B = 0x23   # OPTIONAL physical pin lamps + neon (omit if camera-driven)

# ---- output bit map on OUT-A (chip 0x22) ------------------------------------
# (port, bit) — port 0 = GPIOA/OLATA, port 1 = GPIOB/OLATB.
# ⚠️ SOURCE OF TRUTH = the PCB netlist generator scripts/generate_kicad_netlist_revB.py
# (OUTPUT_PINS). The routed board is wired from it, so these MUST match it. Mapping:
# MCP pin 21-28 = GPA0-7 = (0,0)..(0,7); pin 1-8 = GPB0-7 = (1,0)..(1,7).
# (The __main__ test below re-derives these from the generator and fails on drift.)
OUT_A_MAP = {
    "S":        (0, 0),  # sweep relay        gen pin 21
    "T":        (0, 1),  # table relay        gen pin 22
    "SP":       (0, 2),  # spot solenoid      gen pin 23
    "BE":       (0, 3),  # back-end (future)  gen pin 24
    "M":        (0, 4),  # master (future)    gen pin 25
    "M2":       (0, 5),  # sweep reverse      gen pin 26  (M2 before M1 — per generator)
    "M1":       (0, 6),  # ball return (DNP)  gen pin 27
    "first_ball":  (0, 7),  # gen L_FIRST  pin 28
    "second_ball": (1, 0),  # gen L_SECOND pin 1
    "strike":      (1, 1),  # gen L_STRIKE pin 2
    "foul":        (1, 2),  # gen L_FOUL   pin 3
}

# ---- slow-input bit map on IN-A (chip 0x20) — matches generator SLOW_INPUT_PINS ----
IN_A_MAP = {
    "GS1": (0, 0), "GS2": (0, 1), "GS3": (0, 2), "GS4": (0, 3),
    "GS5": (0, 4), "GS6": (0, 5), "GS7": (0, 6), "GS8": (0, 7),
    "GS9": (1, 0), "GS10": (1, 1),
    "GP":  (1, 2), "OS": (1, 3), "BS": (1, 4),   # gen: OS=pin4=(1,3), BS=pin5=(1,4)
    "PBZ": (1, 5), "PBC": (1, 6), "Foul": (1, 7),
}
GRIPPER_ORDER = [f"GS{i}" for i in range(1, 11)]  # GS1=bit0 ... GS10=bit9 of the mask

# Optos are active-low at the MCP pin (switch closed → opto pulls pin LOW).
# So "asserted/closed" = pin reads 0. INPUT_ACTIVE_LOW flips that in firmware;
# set False per-channel only if a particular front-end is wired active-high.
INPUT_ACTIVE_LOW = True

# Output names that are motion relays (vs status lamps). When an RP2040 link is
# wired, these get RUN/STOP sent so the firmware's motion max-run backstop knows
# what is energized. Lamps (first_ball/second_ball/foul/strike) are not motors.
MOTION_RELAYS = ("S", "T", "SP", "BE", "M", "M1", "M2")


class _MCP23017:
    """Minimal MCP23017 driver over smbus. Caches output latches so per-bit
    set/clear doesn't read-modify-write the bus each time."""

    def __init__(self, bus, addr, *, dir_mask_a, dir_mask_b, pullup_a=0x00, pullup_b=0x00):
        self.bus = bus
        self.addr = addr
        self._olat = [0x00, 0x00]   # cached OLATA/OLATB
        # 1 = input, 0 = output (MCP convention)
        bus.write_byte_data(addr, _IODIRA, dir_mask_a)
        bus.write_byte_data(addr, _IODIRB, dir_mask_b)
        bus.write_byte_data(addr, _GPPUA, pullup_a)
        bus.write_byte_data(addr, _GPPUB, pullup_b)
        bus.write_byte_data(addr, _OLATA, 0x00)
        bus.write_byte_data(addr, _OLATB, 0x00)

    def read_port(self, port):
        return self.bus.read_byte_data(self.addr, _GPIOA if port == 0 else _GPIOB)

    def write_bit(self, port, bit, value):
        # C-02 (hw-independence audit 2026-07-09): the cache must never run ahead
        # of the hardware. A cache updated before a NACKed write leaves a stale
        # bit that the NEXT write to ANY other bit on the port re-asserts — an
        # uncommanded energize. Order: bus write -> commit cache -> readback.
        olat = self._olat[port]
        olat = (olat | (1 << bit)) if value else (olat & ~(1 << bit))
        reg = _OLATA if port == 0 else _OLATB
        self.bus.write_byte_data(self.addr, reg, olat)
        self._olat[port] = olat        # write returned: cache = best estimate
        readback = self.bus.read_byte_data(self.addr, reg)
        if readback != olat:
            # Trust the hardware over intent so later writes carry truth, then
            # raise so the tick-level fail-safe (disarm + First-Ball-Zero) runs.
            self._olat[port] = readback
            raise IOError(
                f"MCP@{self.addr:#04x} OLAT{'A' if port == 0 else 'B'} readback "
                f"{readback:#04x} != commanded {olat:#04x}")

    def all_off(self):
        # Safety path: attempt BOTH ports even if the first write fails, commit
        # the cache only per confirmed write, and re-raise the first error.
        err = None
        for port, reg in ((0, _OLATA), (1, _OLATB)):
            try:
                self.bus.write_byte_data(self.addr, reg, 0x00)
                self._olat[port] = 0x00
            except Exception as e:
                if err is None:
                    err = e
        if err is not None:
            raise err


class MachineIO:
    """Concrete hardware io for ONE lane/board. Implements the FSM's io contract.

    Construction opens the board's I²C bus + the 3 MCP23017s. The RP2040 link
    (fast cam/ball events + cam-stop) and the NE555 watchdog kick are injected as
    callables so this stays testable and the transport (UART/I²C/SPI) is pluggable.

    Args:
      bus_id:        Pi I²C bus number for THIS board (per-board bus, §6).
      watchdog_kick: callable() → pet the NE555 (e.g. lane_node's GPIO12 pulse).
      arm_relays:    callable(bool) → assert/deassert the board's "arm" GPIO that
                     gates the relay-enable rail (power-down rule).
      now:           monotonic clock (injectable; defaults to time.monotonic).
      enable_pin_lamps: drive the optional physical mask (OUT-B). Default False
                     (camera supplies mask pin-data — channel_allocation §3a).
    """

    def __init__(self, lane_id, bus_id, *, watchdog_kick=None, arm_relays=None,
                 now=None, enable_pin_lamps=False, rp2040=None, recorder=None):
        self.lane = lane_id
        self._kick = watchdog_kick or (lambda: None)
        self._arm = arm_relays or (lambda on: None)
        self._now = now or time.monotonic
        self.enable_pin_lamps = enable_pin_lamps
        self._rp2040 = rp2040    # RP2040Link (or None): SC/TB interlock echo + RUN/STOP
        self._out_state = {}     # last commanded value per output (change-logging + dup suppress)
        self._armed = None       # last arm() value (change-logging)
        # Flight recorder (idea #10): observe-only. NULL_RECORDER = inert no-op when
        # none is injected, so the instrumentation tap is branch-free + zero-cost.
        self.recorder = recorder or NULL_RECORDER

        try:
            import smbus2 as smbus
        except ImportError:
            import smbus  # type: ignore
        self.bus = smbus.SMBus(bus_id)

        # IODIR: 1=input. IN-A/IN-B all-inputs (0xFF); OUT-A all-outputs (0x00).
        self.in_a = _MCP23017(self.bus, ADDR_IN_A, dir_mask_a=0xFF, dir_mask_b=0xFF,
                              pullup_a=0xFF, pullup_b=0xFF)
        # IN-B (0x21): present on the Rev-B board (10th/manual/spare inputs). Initialized
        # so all 3 board MCP23017s are configured; not yet READ by the current FSM.
        self.in_b = _MCP23017(self.bus, ADDR_IN_B, dir_mask_a=0xFF, dir_mask_b=0xFF,
                              pullup_a=0xFF, pullup_b=0xFF)
        self.out_a = _MCP23017(self.bus, ADDR_OUT_A, dir_mask_a=0x00, dir_mask_b=0x00)
        self.out_b = None
        if enable_pin_lamps:
            self.out_b = _MCP23017(self.bus, ADDR_OUT_B, dir_mask_a=0x00, dir_mask_b=0x00)
        log.info(f"MachineIO L{lane_id}: I²C bus {bus_id}, "
                 f"IN-A@{ADDR_IN_A:#x} IN-B@{ADDR_IN_B:#x} OUT-A@{ADDR_OUT_A:#x}"
                 f"{' OUT-B@%#x' % ADDR_OUT_B if enable_pin_lamps else ''}")

    # ---- outputs (FSM drives) ---------------------------------------------
    def _set_out(self, name, on):
        on = bool(on)
        changed = self._out_state.get(name) is not on
        if changed:
            self._out_state[name] = on
            # Timestamped (via logging) output history — post-incident forensics.
            log.info("L%s OUT %s -> %s", self.lane, name, "ON" if on else "off")
            # Flight recorder tap: record every OUTPUT CHANGE (idea #10). Recorder
            # is fail-safe + bounded; this never raises into the control path.
            self.recorder.record("out", name, on)
        port, bit = OUT_A_MAP[name]
        self.out_a.write_bit(port, bit, on)     # OLAT write is idempotent; always refresh
        if changed and self._rp2040 is not None and name in MOTION_RELAYS:
            # Send RUN/STOP only on a real change (wire economy). NOTE: this is
            # NOT load-bearing for the max-run backstop — the firmware stamps
            # its timer only on a false->true transition (main.c handle_line),
            # so re-assertion is safe; rp2040_link's hb run-mask reconciliation
            # relies on exactly that to re-send lost RUN/STOP lines.
            (self._rp2040.run if on else self._rp2040.stop)(name)

    def set_sweep(self, on): self._set_out("S", on)
    def set_table(self, on): self._set_out("T", on)
    def set_spot(self, on):  self._set_out("SP", on)

    def set_light(self, name, on):
        if name not in ("first_ball", "second_ball", "foul", "strike"):
            log.warning(f"set_light: unknown lamp {name!r}")
            return
        self._set_out(name, on)

    def set_pin_lamps(self, mask):
        # Camera-driven baseline: the mask comes from Track A; the physical mask
        # may be omitted. Only drive OUT-B if the physical pindicator is built.
        if not self.enable_pin_lamps or self.out_b is None:
            return
        for i in range(10):
            port, bit = (0, i) if i < 8 else (1, i - 8)
            self.out_b.write_bit(port, bit, bool(mask & (1 << i)))

    # ---- slow inputs (FSM reads) ------------------------------------------
    def _read_in(self, name):
        port, bit = IN_A_MAP[name]
        raw = (self.in_a.read_port(port) >> bit) & 1
        return (raw == 0) if INPUT_ACTIVE_LOW else (raw == 1)

    def read_grippers(self):
        """10-bit standing-pin mask (bit n-1 = GSn standing). Reads both ports
        of IN-A once each, then slices the 10 gripper bits."""
        p0 = self.in_a.read_port(0)
        p1 = self.in_a.read_port(1)
        mask = 0
        for i, name in enumerate(GRIPPER_ORDER):
            port, bit = IN_A_MAP[name]
            raw = ((p0 if port == 0 else p1) >> bit) & 1
            standing = (raw == 0) if INPUT_ACTIVE_LOW else (raw == 1)
            if standing:
                mask |= (1 << i)
        return mask

    def gp_closed(self): return self._read_in("GP")
    def bs_closed(self): return self._read_in("BS")
    def read_input(self, name): return self._read_in(name)   # PBZ/PBC/Foul/OS/... for the daemon

    def interlock_ok(self):
        """Software echo of the TB/SC interlock. ⚠️ The hardware TB+SC loop is
        PLANNED, not landed — design open per docs/phase8_interlock_redesign.md
        (measured 2026-06-27: no isolatable dry NC pair exists to land J_SAFETY
        as drawn). Until that design lands, this echo is the ONLY TB/SC guard.
        When the RP2040 link is wired, echo its SC/TB collision state; otherwise
        default True — which today means NO interlock protection, not "the
        hardware has it covered"."""
        if self._rp2040 is not None:
            return self._rp2040.interlock_ok()
        return True

    def watchdog_kick(self):
        self._kick()

    def arm(self, on):
        """Assert/deassert the relay-enable arm GPIO (power-down rule)."""
        on = bool(on)
        if self._armed is not on:
            self._armed = on
            log.info("L%s ARM -> %s", self.lane, "ASSERTED" if on else "deasserted")
            self.recorder.record("arm", "arm", on)   # flight recorder tap (idea #10)
        self._arm(on)

    def now(self):
        return self._now()

    def log(self, msg):
        log.info(msg)

    def all_off(self):
        """Drive every output LOW (motors + lamps). Used on fault/shutdown."""
        log.info("L%s ALL OUTPUTS OFF", self.lane)
        self.out_a.all_off()
        if self.out_b is not None:
            self.out_b.all_off()
        self._out_state = {name: False for name in OUT_A_MAP}

    def close(self):
        """Best-effort safe shutdown: de-assert ARM FIRST (rail un-permitted),
        then drive every output LOW, then release the bus. Each step isolated so
        one failure (e.g. an I2C error in all_off) cannot skip the rest."""
        try:
            self.arm(False)
        except Exception as e:
            log.warning("L%s close: ARM de-assert failed: %s", self.lane, e)
        try:
            self.all_off()
        except Exception as e:
            log.warning("L%s close: all_off failed: %s", self.lane, e)
        try:
            self.bus.close()
        except Exception:
            pass


class RecordingIO:
    """No-hardware io that records outputs + serves scripted inputs. For
    bench-testing the FSM off-Pi with assertions on the output sequence.

    Inputs default to a 'safe idle': interlock OK, GP closed, BS open, no pins.
    Set .grippers / .gp / .bs / .interlock to script a cycle; read .events for
    the ordered (name, value) output log."""

    def __init__(self, now=None, rp2040=None, recorder=None):
        self._t = 0.0
        self._now = now
        self._rp2040 = rp2040
        self.recorder = recorder or NULL_RECORDER   # flight recorder (idea #10), observe-only
        self.events = []          # ordered (kind, *args) of every output call
        self.outputs = {}         # latest value per output name
        self.lamps = {}
        self.pin_lamps = 0
        self.kicks = 0
        self.grippers = 0
        self.gp = True
        self.bs = False
        self.interlock = True
        self.slow = {}            # scripted slow inputs for read_input (PBZ/Foul/BS/...)
        self.armed = None         # last arm() value recorded

    # clock (advanceable for delay tests)
    def now(self):
        return self._now() if self._now else self._t
    def advance(self, dt):
        self._t += dt

    # outputs
    def _link_motor(self, motor, on):
        if self._rp2040 is not None:
            (self._rp2040.run if on else self._rp2040.stop)(motor)

    def set_sweep(self, on): self.outputs["sweep"] = bool(on); self.events.append(("sweep", bool(on))); self.recorder.record("out", "S", bool(on)); self._link_motor("S", bool(on))
    def set_table(self, on): self.outputs["table"] = bool(on); self.events.append(("table", bool(on))); self.recorder.record("out", "T", bool(on)); self._link_motor("T", bool(on))
    def set_spot(self, on):  self.outputs["spot"] = bool(on); self.events.append(("spot", bool(on))); self.recorder.record("out", "SP", bool(on)); self._link_motor("SP", bool(on))
    def set_pin_lamps(self, mask): self.pin_lamps = mask; self.events.append(("pin_lamps", mask)); self.recorder.record("out", "pin_lamps", mask)
    def set_light(self, name, on): self.lamps[name] = bool(on); self.events.append(("light", name, bool(on))); self.recorder.record("out", name, bool(on))

    # inputs
    def read_grippers(self): return self.grippers
    def gp_closed(self): return self.gp
    def bs_closed(self): return self.bs
    def read_input(self, name): return bool(self.slow.get(name, False))
    def interlock_ok(self): return self._rp2040.interlock_ok() if self._rp2040 is not None else self.interlock

    # housekeeping
    def watchdog_kick(self): self.kicks += 1
    def arm(self, on): self.armed = bool(on); self.events.append(("arm", bool(on))); self.recorder.record("arm", "arm", bool(on))
    def log(self, msg): self.events.append(("log", msg))


# ===========================================================================
# ShadowIO — SHADOW/CANARY SOAK wrapper (idea #11)
# ===========================================================================
class ShadowIO:
    """Wrap a real io so the FSM runs on REAL inputs but drives NOTHING.

    Every OUTPUT method (set_sweep/set_table/set_spot/set_light/set_pin_lamps and
    arm) is intercepted and RECORDED instead of being passed to the wrapped io —
    no relay is ever energized and the relay-enable ARM is hard-held LOW. Every
    INPUT / housekeeping method (read_grippers, gp_closed, bs_closed, read_input,
    interlock_ok, watchdog_kick, now, log) delegates to the wrapped real io so the
    FSM sees genuine cam/gripper/SS/interlock state and the NE555 still gets kicked
    (the Pi is alive — we just aren't moving the machine).

    This converts cutover night from 'first live run of motion code' into a logged
    dry-run alongside the OEM controller: the FSM issues the commands it WOULD have,
    ShadowIO records each, and a comparator can later align those commanded windows
    against the observed cam timeline to prove zero divergence over thousands of
    real cycles.

    SAFETY — it must be IMPOSSIBLE to accidentally run live through this wrapper:
      * No output method ever calls the wrapped io's output methods. There is no
        code path from a ShadowIO set_* to a real relay write.
      * On construction it asserts the real ARM is de-asserted, and every arm()
        call (whatever the FSM commands) re-forces the real ARM LOW. So even if the
        wrapped io is a live MachineIO with the rail enabled, ShadowIO keeps it
        disarmed for as long as it is in front of the FSM.
      * It is only ever constructed when the env flag WSL_CONTROLLER_SHADOW is set
        (the daemon's choice); default behavior (no flag) never builds one.

    `would_drive` is the recorded command stream {name: last_value}; `commands` is
    the ordered list of (t, name, value) the FSM issued — the raw material for the
    divergence comparator.
    """

    def __init__(self, real_io, *, recorder=None):
        self._io = real_io
        # Reuse the real io's recorder if it has one, else the injected/NULL one, so
        # shadow commands land in the same flight-recorder stream as everything else.
        self.recorder = recorder or getattr(real_io, "recorder", None) or NULL_RECORDER
        self.would_drive = {}     # name -> last commanded value (motors + lamps + arm)
        self.commands = []        # ordered (t, name, value) — bounded by the caller's cycle scope
        self.armed = None         # last ARM the FSM COMMANDED (not what hardware did — that stays OFF)
        self._force_disarm()      # belt-and-suspenders: real hardware starts + stays disarmed

    # ---- shadow output sink (records, drives nothing) ---------------------
    def _shadow(self, name, value):
        try:
            self.would_drive[name] = value
            self.commands.append((self.now(), name, value))
            # tag as a SHADOW command in the flight recorder so it's never mistaken
            # for a real relay change in a post-incident dump.
            self.recorder.record("shadow_out", name, value)
        except Exception:
            log.debug("ShadowIO L%s: shadow record swallowed", self._lane(), exc_info=True)

    def _force_disarm(self):
        # Drive the REAL arm LOW, bypassing our own intercept, every time.
        try:
            self._io.arm(False)
        except Exception as e:
            log.warning("ShadowIO: could not force real ARM low: %s", e)

    def _lane(self):
        return getattr(self._io, "lane", "?")

    # ---- intercepted OUTPUTS (record only; NEVER reach the real io) --------
    def set_sweep(self, on): self._shadow("S", bool(on))
    def set_table(self, on): self._shadow("T", bool(on))
    def set_spot(self, on):  self._shadow("SP", bool(on))
    def set_light(self, name, on): self._shadow(name, bool(on))
    def set_pin_lamps(self, mask): self._shadow("pin_lamps", mask)

    def arm(self, on):
        # Record what the FSM WANTED, but the machine stays hard-disarmed in shadow.
        self.armed = bool(on)
        self._shadow("arm_cmd", bool(on))
        self._force_disarm()

    # ---- delegated INPUTS + housekeeping (the FSM sees the REAL machine) ----
    def read_grippers(self): return self._io.read_grippers()
    def gp_closed(self): return self._io.gp_closed()
    def bs_closed(self): return self._io.bs_closed()
    def read_input(self, name): return self._io.read_input(name)
    def interlock_ok(self): return self._io.interlock_ok()
    def watchdog_kick(self): return self._io.watchdog_kick()
    def now(self):
        f = getattr(self._io, "now", None)
        return f() if f else time.monotonic()
    def log(self, msg):
        try:
            self._io.log(msg)
        except Exception:
            log.info(msg)


if __name__ == "__main__":
    # Smoke-test RecordingIO by driving a full cycle through the real FSM.
    # Proves controller_io satisfies the CycleController io contract off-Pi.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cycle_control_8270 import CycleController, State, Ball, Cycle, TIME_DELAY_S

    io = RecordingIO()
    c = CycleController(21, io)
    c.power_restore(); c.first_ball_zero()
    assert c.state is State.READY, c.state

    # strike: no pins → fresh rack via SP
    io.grippers = 0
    c.on_ball()
    c.cam_SB_guard()
    io.advance(TIME_DELAY_S + 0.1); c.poll()        # GUARD_DELAY → table down
    assert c.state is State.TABLE_DETECT, c.state
    c.cam_TA2_runthrough()                           # latch pins (0 → strike)
    assert c.cycle is Cycle.STRIKE, c.cycle
    c.cam_SA_runthrough()                            # sweep@270 → TABLE_FINISH
    io.advance(0.3); c.bin_full()                    # BS → SP, SPOTTING
    assert c.state is State.SPOTTING and io.outputs.get("spot") is True
    c.cam_TA1_zero()                                 # → finish, SP off, READY
    assert c.state is State.READY and io.outputs.get("spot") is False
    assert any(e == ("spot", True) for e in io.events), "SP should have fired"
    assert io.kicks >= 1, "poll() must kick the watchdog"  # poll() kicks each call
    print("controller_io RecordingIO drives the FSM through a strike cycle OK")
    print(f"  output events: {len(io.events)}; final lamps={io.lamps}")

    # --- regression guard: OUT_A_MAP / IN_A_MAP MUST match the PCB netlist generator ---
    # The board is routed from generate_kicad_netlist_revB.py; drift here = WRONG pins on
    # real hardware (exactly the BS/OS + M1/M2 + strike/foul swaps Codex caught 2026-06-03).
    import ast
    gen_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_kicad_netlist_revB.py"
    gtree = ast.parse(gen_path.read_text(encoding="utf-8"))
    gdicts = {}
    for node in gtree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("OUTPUT_PINS", "SLOW_INPUT_PINS")):
            gdicts[node.targets[0].id] = ast.literal_eval(node.value)

    def _pin_to_portbit(pin):
        if 21 <= pin <= 28: return (0, pin - 21)   # GPA0-7
        if 1 <= pin <= 8:   return (1, pin - 1)    # GPB0-7
        raise ValueError(f"unexpected MCP pin {pin}")

    OUT_KEY = {"L_FIRST": "first_ball", "L_SECOND": "second_ball",
               "L_STRIKE": "strike", "L_FOUL": "foul"}
    exp_out = {OUT_KEY.get(n, n): _pin_to_portbit(p) for n, p in gdicts["OUTPUT_PINS"].items()}
    assert OUT_A_MAP == exp_out, f"OUT_A_MAP drift vs generator:\n  code={OUT_A_MAP}\n  gen ={exp_out}"

    exp_in = {("Foul" if n == "FOUL" else n): _pin_to_portbit(p)
              for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items() if chip == "MCP_IN_A"}
    assert IN_A_MAP == exp_in, f"IN_A_MAP drift vs generator:\n  code={IN_A_MAP}\n  gen ={exp_in}"
    print(f"pin maps match the PCB generator: OUT_A_MAP({len(OUT_A_MAP)}) + IN_A_MAP({len(IN_A_MAP)}) OK")
    sys.exit(0)
