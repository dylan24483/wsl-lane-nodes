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
here. Candidate C retains the OEM parallel closed-when-safe S/T ladder as the
primary TB/SC protection; J_SAFE1-2 is a controlled jumper, and per-lane G3
insertion proof is mandatory. The firmware/software echo is default-off and
unvalidated, so it is diagnostic defense-in-depth only. MachineIO is
NOT to drive a live machine until the full hardware safety chain is bench-proven
(see docs/phase8_PLAN_A_full_replacement.md + the off-live validation gate #17).
Software freshness checks reserve and measure a bounded actuation window, but
cannot mathematically stop an opaque kernel/I²C/GPIO call that begins fresh and
then stalls. RP2040_OK, the NE555 rail watchdog, and the OEM S/T guard remain
the independent load-bearing deadline boundary.

Hardware deps (Pi only): `smbus2` (or `smbus`) for the MCP23017s. Imported
lazily so this module loads + the RecordingIO path tests on any machine.
"""
from __future__ import annotations
import os
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

# ---- slow-input bit map on IN-B (chip 0x21) — matches generator SLOW_INPUT_PINS ----
# 10th-frame + the manual-motion switches + the spare AUX sensor channels
# (2026-07-19 diagnostics scope: manual-override visibility -> alert suppression;
# AUX channels are the spare inputs — BE current switch / exit photoeye /
# distributor index land here when installed).
# ⚠️ SOURCE OF TRUTH = the netlist generator's SLOW_INPUT_PINS MCP_IN_B entries
# (the channel-map doc's IN-B channel count was stale — netlist wins; PBC is on
# IN-A GPB6, NOT here).
#
# BOARD REVISIONS (H3, Codex audit 2026-07-21):
#   rev-B/rev-C (generate_kicad_netlist_revB.py): 8 channels, all on GPA0-7.
#     GPB0-7 are UNPOPULATED on those boards (no optos, no connector).
#   rev-D      (generate_kicad_netlist_revD.py): adds AUX4-AUX11 as populated
#     opto channels on GPB0-7 (J15 field connector, change-spec item C).
# The map is selected EXPLICITLY per board via MachineIO/RecordingIO
# board_rev= (default "revC" — the validated pilot hardware on machine 22);
# there is no auto-detection. The __main__ regression guard below re-derives
# BOTH revisions from their generators and fails on drift.
IN_B_MAP = {
    "TENTH":    (0, 0),  # 10th-frame button      gen pin 21
    "MAN_T":    (0, 1),  # manual table           gen pin 22
    "MAN_S":    (0, 2),  # manual sweep           gen pin 23
    "MAN_SWS":  (0, 3),  # manual sweep-switch    gen pin 24
    "MAN_SWSR": (0, 4),  # manual sweep reverse   gen pin 25
    "AUX1":     (0, 5),  # spare (be_current)     gen pin 26
    "AUX2":     (0, 6),  # spare (exit_beam)      gen pin 27
    "AUX3":     (0, 7),  # spare (dist_index)     gen pin 28
}
# rev-D appends AUX4-11 on GPB0-7 (gen pins 1-8) — everything else identical.
IN_B_MAP_REVD = dict(IN_B_MAP)
IN_B_MAP_REVD.update({f"AUX{i}": (1, i - 4) for i in range(4, 12)})
# Explicit board-revision -> IN-B map selection table. rev-B and rev-C share
# the same netlist-generator input section, so they share a map.
IN_B_MAPS = {"revB": IN_B_MAP, "revC": IN_B_MAP, "revD": IN_B_MAP_REVD}
DEFAULT_BOARD_REV = "revC"


def in_b_map_for(board_rev):
    """Resolve a board revision string to its IN-B map. Unknown revisions are
    a HARD error — a typo must not silently read the wrong bank."""
    try:
        return IN_B_MAPS[board_rev]
    except KeyError:
        raise ValueError(f"unknown board_rev {board_rev!r}; "
                         f"known: {sorted(IN_B_MAPS)}") from None

# Optos are active-low at the MCP pin (switch closed → opto pulls pin LOW).
# So "asserted/closed" = pin reads 0. INPUT_ACTIVE_LOW flips that in firmware;
# set False per-channel only if a particular front-end is wired active-high.
INPUT_ACTIVE_LOW = True

# Output names that are motion relays (vs status lamps). When an RP2040 link is
# wired, these get RUN/STOP sent so the firmware's motion max-run backstop knows
# what is energized. Lamps (first_ball/second_ball/foul/strike) are not motors.
MOTION_RELAYS = ("S", "T", "SP", "BE", "M", "M1", "M2")

# A positive operation may begin only with this much heartbeat lease left. The
# operation itself must return within the bounded half-window below, preserving
# an equal post-return reserve for rollback/hard-safe handling. Normal MCP/GPIO
# control writes are millisecond-scale; a 50 ms return is already abnormal.
#
# ⚠️ UNMEASURED ON THE TARGET PLATFORM (recorded 2026-07-25).
# The 0.050 s default is an ASSERTION, not a measurement. Nothing in this repo
# measures actuation return time on a Raspberry Pi. The bound is sampled with
# wall-clock ``link.now()`` around a call that the daemon runs on a thread
# competing under the CPython GIL with the serial reader, DiagWriter,
# PlatformHealth (which forks ``vcgencmd`` every 60 s), CycleShipper, and async
# recorder dumps — so the measurement includes SCHEDULING PREEMPTION, not just
# I2C/GPIO transport. Exceeding it drives ``action(False)`` mid-motion and then
# ``_hard_safe`` + MANUAL_INTERVENTION, which needs a physical PBZ to clear.
# Exposure is roughly 2 boards x 50 Hz = ~100 evaluations/s (~8.6M/day/Pi) for
# the watchdog kick alone, so a per-event probability above ~1e-7 is a daily
# lane stoppage.
#
# The failure direction is fail-safe (the machine stops); the cost is
# AVAILABILITY, not injury. Do NOT relax this bound to make a symptom go away.
# Instead MEASURE it on the target Pi with ``scripts/measure_actuation_bound.py``
# and set the env escape below from p99.9 + margin. Readiness gate: G16.
#
# Explicit env escapes — both FAIL LOUD on garbage or out-of-range values
# (ValueError at import, before any hardware opens); they never silently fall
# back to the default the way ``controller_daemon._env_float`` does.
_ACTUATION_BOUND_LO_S = 0.005
_ACTUATION_BOUND_HI_S = 0.500


def _env_bounded_seconds(name, default, *, lo, hi):
    """Read a safety timing bound from the environment, failing LOUD.

    An absent/empty value uses ``default``. Anything else must parse as a
    finite float inside ``[lo, hi]`` or this raises ``ValueError`` — a bad
    knob must stop startup, never quietly restore a default that the operator
    believes they overrode.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return float(default)
    text = raw.strip()
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name}={text!r} is not a number; expected seconds as a decimal "
            f"float in [{lo}, {hi}] (e.g. 0.080)") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name}={text!r} is not a finite number")
    if not (lo <= value <= hi):
        raise ValueError(
            f"{name}={value!r} is outside the permitted range "
            f"[{lo}, {hi}] seconds. This bound is a safety deadline: raising "
            f"it past {hi}s would let a positive actuation outlive its "
            f"heartbeat lease, and lowering it below {lo}s guarantees "
            f"false trips. Measure with scripts/measure_actuation_bound.py.")
    return value


POSITIVE_ACTUATION_MAX_S = _env_bounded_seconds(
    "WSL_POSITIVE_ACTUATION_MAX_S", 0.050,
    lo=_ACTUATION_BOUND_LO_S, hi=_ACTUATION_BOUND_HI_S)
POSITIVE_ACTUATION_MIN_REMAINING_S = 0.100

# The watchdog kick is NOT a transport-latency measurement: its body deliberately
# BLOCKS for ``controller_daemon.WDOG_PULSE_S`` (the NE555 pulse width) between
# the two monotonic samples. Measuring a deliberately-blocking call against a
# bound sized for non-blocking register writes is a category error, so the kick
# carries its own budget = deliberate blocking time + the same transport
# allowance. ``BoardController`` passes the derived value; this is the fallback
# used when a FreshnessGuardIO is built without one.
#
# NOTE ON THE REAL BACKSTOP: a genuinely late kick is already handled in
# HARDWARE — the NE555 simply does not get its pulse and drops the relay-enable
# rail. The software bound here is defense in depth, so it must not be the
# component that stops the lane on scheduler jitter alone.
WATCHDOG_KICK_MAX_S = _env_bounded_seconds(
    "WSL_WATCHDOG_KICK_MAX_S", POSITIVE_ACTUATION_MAX_S + 0.002,
    lo=_ACTUATION_BOUND_LO_S, hi=_ACTUATION_BOUND_HI_S)


class LinkFreshnessError(RuntimeError):
    """A safety-positive actuation was refused or exceeded its time budget."""


def require_positive_actuation_freshness(
        link, action, *, min_remaining_s=POSITIVE_ACTUATION_MIN_REMAINING_S):
    """Require full link health plus an exact heartbeat-lease time budget."""
    healthy, remaining = link.actuation_freshness_status()
    if not healthy:
        suffix = (
            "no accepted heartbeat" if remaining is None
            else f"heartbeat remaining={remaining:.6f}s"
        )
        raise LinkFreshnessError(
            f"refused {action}: RP2040 link health is not current "
            f"({suffix})")
    if remaining is None or remaining < min_remaining_s:
        raise LinkFreshnessError(
            f"refused {action}: heartbeat remaining={remaining:.6f}s is "
            f"below the {min_remaining_s:.6f}s positive-actuation margin")


class _MCP23017:
    """Minimal MCP23017 driver over smbus. Caches output latches so per-bit
    set/clear doesn't read-modify-write the bus each time."""

    def __init__(self, bus, addr, *, dir_mask_a, dir_mask_b, pullup_a=0x00, pullup_b=0x00):
        self.bus = bus
        self.addr = addr
        self._olat = [0x00, 0x00]   # cached OLATA/OLATB
        # 1 = input, 0 = output (MCP convention). Configuration is part of
        # the safety boundary: verify the live registers and fail construction
        # if an I2C write was ignored or the device is not the expected part.
        self._write_config(_IODIRA, dir_mask_a, "IODIRA")
        self._write_config(_IODIRB, dir_mask_b, "IODIRB")
        self._write_config(_GPPUA, pullup_a, "GPPUA")
        self._write_config(_GPPUB, pullup_b, "GPPUB")
        bus.write_byte_data(addr, _OLATA, 0x00)
        bus.write_byte_data(addr, _OLATB, 0x00)

    def _write_config(self, reg, value, name):
        value &= 0xFF
        self.bus.write_byte_data(self.addr, reg, value)
        readback = self.bus.read_byte_data(self.addr, reg)
        if readback != value:
            raise IOError(
                f"MCP@{self.addr:#04x} {name} readback "
                f"{readback:#04x} != commanded {value:#04x}")

    def read_port(self, port):
        return self.bus.read_byte_data(self.addr, _GPIOA if port == 0 else _GPIOB)

    def write_bit(self, port, bit, value, *, positive_guard=None):
        # C-02 (hw-independence audit 2026-07-09): the cache must never run ahead
        # of the hardware. A cache updated before a NACKed write leaves a stale
        # bit that the NEXT write to ANY other bit on the port re-asserts — an
        # uncommanded energize. Order: bus write -> commit cache -> readback.
        olat = self._olat[port]
        olat = (olat | (1 << bit)) if value else (olat & ~(1 << bit))
        reg = _OLATA if port == 0 else _OLATB
        # Last software check at the physical I²C boundary, after staging and
        # before the ioctl. The ioctl itself remains opaque; RP_OK/NE555/OEM
        # hardware protection covers a kernel/bus stall after this point.
        if value and positive_guard is not None:
            positive_guard()
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
                 now=None, enable_pin_lamps=False, rp2040=None, recorder=None,
                 board_rev=DEFAULT_BOARD_REV):
        self.lane = lane_id
        self._kick = watchdog_kick or (lambda: None)
        self._arm = arm_relays or (lambda on: None)
        self._now = now or time.monotonic
        self.enable_pin_lamps = enable_pin_lamps
        # H3 (2026-07-21): explicit board-revision IN-B map selection (rev-D
        # populates the GPB0-7 AUX4-11 bank; rev-B/C have GPA only).
        self.board_rev = board_rev
        self.in_b_map = in_b_map_for(board_rev)
        self._in_b_has_gpb = any(port == 1 for port, _ in self.in_b_map.values())
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
        # Rev-D's external 47k Rpu network is the sole input bias. Enabling the
        # MCP's nominal 100k GPPU would put it in parallel, invalidate the
        # qualified sink-current/rise-time envelope, and hide an open Rpu.
        self.in_a = _MCP23017(self.bus, ADDR_IN_A, dir_mask_a=0xFF, dir_mask_b=0xFF,
                              pullup_a=0x00, pullup_b=0x00)
        # IN-B (0x21): present on the Rev-B board (10th/manual/spare inputs). Initialized
        # so all 3 board MCP23017s are configured; not yet READ by the current FSM.
        self.in_b = _MCP23017(self.bus, ADDR_IN_B, dir_mask_a=0xFF, dir_mask_b=0xFF,
                              pullup_a=0x00, pullup_b=0x00)
        self.out_a = _MCP23017(self.bus, ADDR_OUT_A, dir_mask_a=0x00, dir_mask_b=0x00)
        self.out_b = None
        if enable_pin_lamps:
            self.out_b = _MCP23017(self.bus, ADDR_OUT_B, dir_mask_a=0x00, dir_mask_b=0x00)
        log.info(f"MachineIO L{lane_id}: I²C bus {bus_id}, "
                 f"IN-A@{ADDR_IN_A:#x} IN-B@{ADDR_IN_B:#x} OUT-A@{ADDR_OUT_A:#x}"
                 f"{' OUT-B@%#x' % ADDR_OUT_B if enable_pin_lamps else ''}")

    # ---- outputs (FSM drives) ---------------------------------------------
    def _require_positive_fresh(self, action):
        # MachineIO is also used by the isolated manual first-article utility,
        # where no RP2040 object is intentionally supplied. The production
        # BoardController always supplies one and adds an outer guard as well.
        if self._rp2040 is not None:
            require_positive_actuation_freshness(self._rp2040, action)

    def _rollback_positive_output(self, name, port, bit, reason):
        """Best-effort exact-channel rollback after an uncertain positive write."""
        failures = []
        try:
            self.out_a.write_bit(port, bit, False)
        except Exception as exc:
            failures.append(f"I2C off failed: {type(exc).__name__}: {exc}")
        if self._rp2040 is not None and name in MOTION_RELAYS:
            try:
                if self._rp2040.stop(name) is False:
                    failures.append("firmware STOP transport failed")
            except Exception as exc:
                failures.append(
                    f"firmware STOP failed: {type(exc).__name__}: {exc}")
        self._out_state[name] = False
        log.error(
            "L%s OUT %s positive command failed (%s); rollback issued%s",
            self.lane, name, reason,
            f"; {'; '.join(failures)}" if failures else "")
        self.recorder.record("fault", f"{name}-positive-command", reason)
        self.recorder.record("out", name, False)
        return tuple(failures)

    def _set_out(self, name, on):
        on = bool(on)
        changed = self._out_state.get(name) is not on
        port, bit = OUT_A_MAP[name]
        positive_guard = None
        if on and name in MOTION_RELAYS:
            positive_guard = lambda: self._require_positive_fresh(
                f"{name}-on-inner")
        # Physical write first. State/logging/recorder work must never consume
        # heartbeat lease before a safety-positive output reaches the boundary.
        try:
            self.out_a.write_bit(
                port, bit, on, positive_guard=positive_guard)
        except LinkFreshnessError:
            # The guard runs before the physical bus call; no rollback needed.
            raise
        except Exception as exc:
            if on and name in MOTION_RELAYS:
                self._rollback_positive_output(
                    name, port, bit,
                    f"I2C positive write/readback failed: "
                    f"{type(exc).__name__}: {exc}")
                raise LinkFreshnessError(
                    f"{name}-on physical write was uncertain and was "
                    "rolled back") from exc
            raise
        if changed and self._rp2040 is not None and name in MOTION_RELAYS:
            # Send RUN/STOP only on a real change (wire economy). NOTE: this is
            # NOT load-bearing for the max-run backstop — the firmware stamps
            # its timer only on a false->true transition (main.c handle_line),
            # so re-assertion is safe; rp2040_link's hb run-mask reconciliation
            # relies on exactly that to re-send lost RUN/STOP lines.
            try:
                sent = (self._rp2040.run if on else self._rp2040.stop)(name)
            except Exception as exc:
                sent = False
                send_exc = exc
            else:
                send_exc = None
            if on and sent is False:
                reason = "firmware RUN transport failed"
                if send_exc is not None:
                    reason += f": {type(send_exc).__name__}: {send_exc}"
                self._rollback_positive_output(name, port, bit, reason)
                raise LinkFreshnessError(
                    f"{name}-on lost its firmware max-run command and was "
                    "rolled back")
        if changed:
            self._out_state[name] = on
            # Forensics are deliberately after the physical + firmware command
            # boundaries so a slow logger/recorder cannot delay actuation.
            log.info("L%s OUT %s -> %s", self.lane, name, "ON" if on else "off")
            self.recorder.record("out", name, on)

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
        # IN-A first (the FSM's inputs), IN-B for the diagnostics channels
        # (manual/10th/AUX). Same opto front-end -> same active-low semantics;
        # edge detection + debounce stay the daemon's job, exactly as for IN-A.
        if name in IN_A_MAP:
            chip, (port, bit) = self.in_a, IN_A_MAP[name]
        else:
            chip, (port, bit) = self.in_b, self.in_b_map[name]
        raw = (chip.read_port(port) >> bit) & 1
        return (raw == 0) if INPUT_ACTIVE_LOW else (raw == 1)

    def read_inputs_b(self):
        """All IN-B channels for THIS board revision, decoded from one port
        read per populated port (rev-B/C: GPA only = one read; rev-D: GPA+GPB
        = two reads — the AUX4-11 bank). {name: asserted}; same active-low
        convention and edge/debounce ownership as the IN-A reads. Cheap enough
        for the daemon's per-tick slow poll (1-2 I²C register reads)."""
        ports = [self.in_b.read_port(0),
                 self.in_b.read_port(1) if self._in_b_has_gpb else 0]
        out = {}
        for name, (port, bit) in self.in_b_map.items():
            raw = (ports[port] >> bit) & 1
            out[name] = (raw == 0) if INPUT_ACTIVE_LOW else (raw == 1)
        return out

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
        """Optional software echo of the TB/SC collision posture.

        Candidate C's primary protection is the OEM parallel closed-when-safe
        S/T ladder, with J_SAFE1-2 controlled and per-lane G3 insertion proof
        mandatory. The firmware echo remains default-off/unvalidated
        defense-in-depth. Returning True without a link means only "no software
        veto"; it does not assert or replace the independent OEM guard.
        """
        if self._rp2040 is not None:
            return self._rp2040.interlock_ok()
        return True

    def watchdog_kick(self):
        self._require_positive_fresh("watchdog-kick-inner")
        try:
            self._kick()
        except LinkFreshnessError:
            raise
        except Exception as exc:
            raise LinkFreshnessError(
                "watchdog-kick physical callback failed") from exc

    def arm(self, on):
        """Assert/deassert the relay-enable arm GPIO (power-down rule)."""
        on = bool(on)
        if on:
            self._require_positive_fresh("arm-high-inner")
        # Physical GPIO callback first; forensics/state cannot delay it.
        try:
            self._arm(on)
        except LinkFreshnessError:
            if on:
                try:
                    self._arm(False)
                except Exception:
                    pass
            raise
        except Exception as exc:
            if on:
                try:
                    self._arm(False)
                except Exception:
                    pass
                raise LinkFreshnessError(
                    "ARM-high physical callback failed; ARM-low rollback "
                    "issued") from exc
            raise
        if self._armed is not on:
            self._armed = on
            log.info("L%s ARM -> %s", self.lane, "ASSERTED" if on else "deasserted")
            self.recorder.record("arm", "arm", on)   # flight recorder tap (idea #10)

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

    def __init__(self, now=None, rp2040=None, recorder=None,
                 board_rev=DEFAULT_BOARD_REV):
        self._t = 0.0
        self._now = now
        self._rp2040 = rp2040
        self.board_rev = board_rev
        self.in_b_map = in_b_map_for(board_rev)
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
    def read_inputs_b(self): return {n: bool(self.slow.get(n, False)) for n in self.in_b_map}
    def interlock_ok(self): return self._rp2040.interlock_ok() if self._rp2040 is not None else self.interlock

    # housekeeping
    def watchdog_kick(self): self.kicks += 1
    def arm(self, on): self.armed = bool(on); self.events.append(("arm", bool(on))); self.recorder.record("arm", "arm", bool(on))
    def log(self, msg): self.events.append(("log", msg))


class FreshnessGuardIO:
    """Guard motor-on, watchdog-kick, and ARM-high at point of actuation.

    Holding the link state lock prevents concurrent mutation, but monotonic
    time still advances during a tick. A fixed pre-write reserve, an inner
    MachineIO check, measured maximum return time, postcheck, and rollback
    close every software-controlled delay window. They do not make Linux,
    I²C, or GPIO calls hard real-time: an opaque call that stalls after the
    last check is contained by RP2040_OK, NE555, and the OEM guard. OFF/LOW
    operations always pass through.
    """

    def __init__(self, io, link, *, watchdog_kick_max_s=None):
        object.__setattr__(self, "_io", io)
        object.__setattr__(self, "_link", link)
        # The kick blocks by design; give it its own budget. See
        # WATCHDOG_KICK_MAX_S. Callers that know the real pulse width
        # (BoardController knows WDOG_PULSE_S) should pass it explicitly.
        if watchdog_kick_max_s is None:
            watchdog_kick_max_s = WATCHDOG_KICK_MAX_S
        watchdog_kick_max_s = float(watchdog_kick_max_s)
        if not (_ACTUATION_BOUND_LO_S
                <= watchdog_kick_max_s <= _ACTUATION_BOUND_HI_S):
            raise ValueError(
                f"watchdog_kick_max_s={watchdog_kick_max_s!r} is outside the "
                f"permitted range [{_ACTUATION_BOUND_LO_S}, "
                f"{_ACTUATION_BOUND_HI_S}] seconds")
        object.__setattr__(self, "_wdog_max_s", watchdog_kick_max_s)

    def __getattr__(self, name):
        return getattr(self._io, name)

    def __setattr__(self, name, value):
        if name in ("_io", "_link", "_wdog_max_s"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._io, name, value)

    def _require_fresh(
            self, action,
            min_remaining_s=POSITIVE_ACTUATION_MIN_REMAINING_S):
        require_positive_actuation_freshness(
            self._link, action, min_remaining_s=min_remaining_s)

    def _require_bounded_duration(self, action, started, max_s=None):
        if max_s is None:
            max_s = POSITIVE_ACTUATION_MAX_S
        elapsed = self._link.now() - started
        if elapsed < 0.0 or elapsed > max_s:
            raise LinkFreshnessError(
                f"refused {action}: positive operation returned in "
                f"{elapsed:.6f}s, outside the 0.."
                f"{max_s:.6f}s bound")

    def _positive_with_rollback(self, action, on, name):
        self._require_fresh(name)
        started = self._link.now()
        try:
            result = action(on)
        except LinkFreshnessError:
            raise
        except Exception as exc:
            try:
                action(False)
            except Exception:
                pass
            raise LinkFreshnessError(
                f"{name} raised after positive staging; rollback issued") \
                from exc
        try:
            self._require_bounded_duration(name, started)
            self._require_fresh(name + "-postcheck", min_remaining_s=0.0)
        except LinkFreshnessError:
            # The write may have succeeded just before its slow transport
            # crossed the deadline. Undo that exact positive command now; the
            # BoardController catch then executes the full hard-safe sequence.
            try:
                action(False)
            except Exception:
                pass
            raise
        return result

    def set_sweep(self, on):
        if bool(on):
            return self._positive_with_rollback(
                self._io.set_sweep, on, "sweep-on")
        return self._io.set_sweep(on)

    def set_table(self, on):
        if bool(on):
            return self._positive_with_rollback(
                self._io.set_table, on, "table-on")
        return self._io.set_table(on)

    def set_spot(self, on):
        if bool(on):
            return self._positive_with_rollback(
                self._io.set_spot, on, "spot-on")
        return self._io.set_spot(on)

    def watchdog_kick(self):
        self._require_fresh("watchdog-kick")
        started = self._link.now()
        try:
            result = self._io.watchdog_kick()
        except LinkFreshnessError:
            raise
        except Exception as exc:
            raise LinkFreshnessError(
                "watchdog-kick raised during positive operation") from exc
        # Own budget: the kick BLOCKS for the NE555 pulse width by design, so it
        # cannot be judged against a bound sized for non-blocking writes.
        self._require_bounded_duration(
            "watchdog-kick", started, self._wdog_max_s)
        self._require_fresh(
            "watchdog-kick-postcheck", min_remaining_s=0.0)
        return result

    def arm(self, on):
        if bool(on):
            return self._positive_with_rollback(
                self._io.arm, on, "arm-high")
        return self._io.arm(on)


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
    def read_inputs_b(self): return self._io.read_inputs_b()
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

    # --- regression guard: pin maps MUST match the PCB netlist generators ---
    # The boards are routed from generate_kicad_netlist_revB.py (rev-B/C) and
    # generate_kicad_netlist_revD.py (rev-D); drift here = WRONG pins on real
    # hardware (exactly the BS/OS + M1/M2 + strike/foul swaps Codex caught
    # 2026-06-03). H3 (2026-07-21): the guard is PARAMETRIZED — BOTH board
    # revisions are checked against their own generator, selected explicitly,
    # so the rev-D AUX4-11 GPB bank can never drift unnoticed while the rev-C
    # pilot board keeps its own check. Mirrored in tests/test_pin_map_drift.py.
    import ast

    def _pin_to_portbit(pin):
        if 21 <= pin <= 28: return (0, pin - 21)   # GPA0-7
        if 1 <= pin <= 8:   return (1, pin - 1)    # GPB0-7
        raise ValueError(f"unexpected MCP pin {pin}")

    OUT_KEY = {"L_FIRST": "first_ball", "L_SECOND": "second_ball",
               "L_STRIKE": "strike", "L_FOUL": "foul"}

    def _check_generator(gen_name, expected_in_b, label):
        gen_path = Path(__file__).resolve().parents[1] / "scripts" / gen_name
        gtree = ast.parse(gen_path.read_text(encoding="utf-8"))
        gdicts = {}
        for node in gtree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in ("OUTPUT_PINS", "SLOW_INPUT_PINS")):
                gdicts[node.targets[0].id] = ast.literal_eval(node.value)
        exp_out = {OUT_KEY.get(n, n): _pin_to_portbit(p)
                   for n, p in gdicts["OUTPUT_PINS"].items()}
        assert OUT_A_MAP == exp_out, \
            f"[{label}] OUT_A_MAP drift:\n  code={OUT_A_MAP}\n  gen ={exp_out}"
        exp_in = {("Foul" if n == "FOUL" else n): _pin_to_portbit(p)
                  for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items()
                  if chip == "MCP_IN_A"}
        assert IN_A_MAP == exp_in, \
            f"[{label}] IN_A_MAP drift:\n  code={IN_A_MAP}\n  gen ={exp_in}"
        exp_inb = {n: _pin_to_portbit(p)
                   for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items()
                   if chip == "MCP_IN_B"}
        assert expected_in_b == exp_inb, \
            f"[{label}] IN-B map drift:\n  code={expected_in_b}\n  gen ={exp_inb}"

    _check_generator("generate_kicad_netlist_revB.py", IN_B_MAPS["revC"], "revB/C")
    _check_generator("generate_kicad_netlist_revD.py", IN_B_MAPS["revD"], "revD")
    # structural invariants across the revisions
    assert all(port == 0 for (port, _bit) in IN_B_MAP.values()), \
        "rev-B/C IN-B channels must all be on GPA (single port read)"
    assert {n: pb for n, pb in IN_B_MAP_REVD.items() if n in IN_B_MAP} == IN_B_MAP, \
        "rev-D IN-B map must be a strict superset of the rev-C map"
    assert sorted(set(IN_B_MAP_REVD) - set(IN_B_MAP)) == [f"AUX{i}" for i in (10, 11, 4, 5, 6, 7, 8, 9)], \
        "rev-D IN-B additions must be exactly AUX4-11"

    # read_inputs_b smoke on the fake: scripted levels come back per-name,
    # per board revision.
    rio = RecordingIO()
    rio.slow["MAN_T"] = True
    inb = rio.read_inputs_b()
    assert set(inb) == set(IN_B_MAP) and inb["MAN_T"] is True and inb["AUX1"] is False, inb
    riod = RecordingIO(board_rev="revD")
    riod.slow["AUX9"] = True
    inbd = riod.read_inputs_b()
    assert set(inbd) == set(IN_B_MAP_REVD) and inbd["AUX9"] is True and inbd["AUX4"] is False, inbd
    try:
        RecordingIO(board_rev="revZ")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown board_rev must raise")
    print(f"pin maps match BOTH PCB generators: OUT_A_MAP({len(OUT_A_MAP)}) + "
          f"IN_A_MAP({len(IN_A_MAP)}) + IN_B_MAP revC({len(IN_B_MAP)}) / "
          f"revD({len(IN_B_MAP_REVD)}) OK")
    sys.exit(0)
