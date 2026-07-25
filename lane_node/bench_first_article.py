#!/usr/bin/env python3
"""Fail-closed first-article output tool for one rev-C/D controller board.

This is a manual, no-FSM bench aid.  It drives the real OUT-A path, status
lamps, ARM_PERMIT, NE555 kick, and RP2040 RUN/STOP link.  It does not turn a
visual observation into a first-article pass; the operator still records the
measurements required by the Rev-D first-article pack.

The tool takes the same crash-released per-lane hardware-owner lease as the
controller daemon before importing or opening GPIO, I2C, or UART.  Every ARM,
CLEAR, kick-resume, disarm, and shutdown transition first establishes a
de-energized state.  Thus a stale MCP output latch cannot re-energize motion
without a new, heartbeat-fresh RUN command and firmware timer.

Examples:
    ./bench_first_article.py --lane 21 --board-rev revD
    ./bench_first_article.py --lane 21 --board-rev revC \
        --relay-only-without-rp2040 --confirm-off-machine-dummy-load

Commands:
    arm / disarm             arm only from a proven all-off state
    s|t|sp|be|m|m2 on|off    motion relays K1..K6 (K7/M1 is refused)
    first_ball|second_ball|strike|foul on|off
    off                      all outputs off, firmware STOP *, ARM low
    kick stop|start          start always safes latches before kick resumes
    status                   live firmware/identity/max-run posture
    clear                    safe all outputs/ARM, then firmware CLEAR
    q                        safe exit

By default ARM is refused without a healthy, exact qualified firmware tuple
from ``WSL_RP2040_QUALIFIED_RELEASES=board|build|cfg`` and a known max-run
advertisement.  ``--relay-only-without-rp2040`` plus the required
``--confirm-off-machine-dummy-load`` declaration is an explicit, off-machine
dummy-load-only bench override.  It permits at most one second of make/break
work when the UART could not be opened, automatically releases ARM and every
latch, and cannot qualify the firmware max-run gate.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from identity_evidence import ControllerOwnerLease


DEFAULT_STATE_DIR = "/var/lib/wsl-lane-node"
STATE_DIR_ENV = "WSL_CONTROLLER_STATE_DIR"
QUALIFIED_RELEASES_ENV = "WSL_RP2040_QUALIFIED_RELEASES"
WDOG_PULSE_S = 0.002
KICK_PERIOD_S = 1.0
RELAY_ONLY_DEADLINE_S = 1.0
MOTION = ("S", "T", "SP", "BE", "M", "M2")
LAMPS = ("first_ball", "second_ball", "strike", "foul")
BOARD_CONFIGS = {
    21: {"bus": 1, "uart": "/dev/ttyAMA0", "arm_pin": 26, "wdog_pin": 12},
    22: {"bus": 3, "uart": "/dev/ttyAMA1", "arm_pin": 13, "wdog_pin": 6},
}


def _hardware_dependencies():
    """Import hardware-facing modules only after the owner lease is held."""
    from gpiozero import LED
    from controller_io import MachineIO, OUT_A_MAP
    from rp2040_link import RP2040Link
    return LED, MachineIO, OUT_A_MAP, RP2040Link


def _state_dir():
    configured = os.environ.get(STATE_DIR_ENV)
    if configured is not None and configured != DEFAULT_STATE_DIR:
        raise ValueError(
            f"{STATE_DIR_ENV} is fixed to {DEFAULT_STATE_DIR!r} for physical "
            "bench ownership")
    return DEFAULT_STATE_DIR


def _parse_qualified_releases(raw):
    """Parse the daemon's exact board|build|cfg policy without approximation."""
    if raw is None or raw == "":
        return ()
    if raw != raw.strip() or any(char.isspace() for char in raw):
        raise ValueError(
            f"{QUALIFIED_RELEASES_ENV} cannot contain whitespace")
    result = []
    for entry in raw.split(","):
        parts = tuple(entry.split("|"))
        if (len(parts) != 3 or any(not part for part in parts)
                or parts in result):
            raise ValueError(
                f"invalid {QUALIFIED_RELEASES_ENV} entry {entry!r}; expected "
                "unique board_rev|fw_build|fw_cfg tuples")
        result.append(parts)
    return tuple(result)


class BenchSession:
    """Safety state and command parser, dependency-injected for host tests."""

    def __init__(
            self, io, link, arm_led, wdog, kick_on, *,
            board_rev, qualified_releases=(), allow_no_rp2040=False,
            relay_only_deadline_s=RELAY_ONLY_DEADLINE_S, output=print):
        self.io = io
        self.link = link
        self.arm_led = arm_led
        self.wdog = wdog
        self.kick_on = kick_on
        self.board_rev = board_rev
        self.qualified_releases = tuple(qualified_releases)
        self.allow_no_rp2040 = bool(allow_no_rp2040)
        self.relay_only_deadline_s = float(relay_only_deadline_s)
        if (
                not 0 < self.relay_only_deadline_s
                <= RELAY_ONLY_DEADLINE_S):
            raise ValueError(
                "relay-only deadline must be positive and no greater than "
                f"{RELAY_ONLY_DEADLINE_S:.3f}s")
        self.output = output
        self.armed = False
        self._command_lock = threading.RLock()
        self._deadline_lock = threading.Lock()
        self._relay_only_timer = None
        self._relay_only_deadline_at = None
        self._relay_only_generation = 0
        self.background_failures = []

    @staticmethod
    def _error(label, exc):
        return f"{label}:{type(exc).__name__}:{exc}"

    def _cancel_relay_only_deadline(self):
        with self._deadline_lock:
            self._relay_only_generation += 1
            timer = self._relay_only_timer
            self._relay_only_timer = None
            self._relay_only_deadline_at = None
            if timer is not None:
                timer.cancel()

    def _safe_state_locked(self):
        errors = []
        try:
            self.io.arm(False)
        except Exception as exc:
            errors.append(self._error("arm_low", exc))
            try:
                self.arm_led.off()
            except Exception as fallback:
                errors.append(self._error("arm_low_fallback", fallback))
        self.armed = False

        if self.link is not None:
            try:
                if self.link.stop_all() is False:
                    errors.append("firmware_stop_all:unacknowledged")
            except Exception as exc:
                errors.append(self._error("firmware_stop_all", exc))

        # Per-channel readback catches a failed latch clear. Keep trying every
        # channel even if one fails; all_off is an independent final sweep.
        for name in MOTION + LAMPS:
            try:
                self.io._set_out(name, False)
            except Exception as exc:
                errors.append(self._error(f"{name}_off", exc))
        try:
            self.io.all_off()
        except Exception as exc:
            errors.append(self._error("all_off", exc))
        return tuple(errors)

    def safe_state(self):
        """Attempt every independent safe action; return bounded failures."""
        self._cancel_relay_only_deadline()
        with self._command_lock:
            return self._safe_state_locked()

    def _relay_only_expired(self, generation):
        # ARM is a GPIO independent of the MCP I2C bus. Drop it before waiting
        # for an in-progress bench command so even a wedged I2C transaction
        # cannot extend the dummy-load energize interval by design.
        with self._deadline_lock:
            if generation != self._relay_only_generation:
                return
            self._relay_only_timer = None
            self._relay_only_deadline_at = None
            try:
                self.io.arm(False)
            except Exception as exc:
                self.background_failures.append(
                    self._error("relay_only_deadline_arm_low", exc))
            self.armed = False
        with self._command_lock:
            failures = self._safe_state_locked()
        if failures:
            self.background_failures.extend(failures)
            self.output(
                "RELAY-ONLY DEADLINE SAFE-STATE INCOMPLETE: "
                + "; ".join(failures))
        else:
            self.output(
                "relay-only deadline expired: ARM low and all latches low")

    def _start_relay_only_deadline(self):
        with self._deadline_lock:
            self._relay_only_generation += 1
            generation = self._relay_only_generation
            self._relay_only_deadline_at = (
                time.monotonic() + self.relay_only_deadline_s)
            timer = threading.Timer(
                self.relay_only_deadline_s,
                self._relay_only_expired, args=(generation,))
            timer.daemon = True
            self._relay_only_timer = timer
            timer.start()

    def _firmware_gate(self):
        if self.link is None:
            return False, "RP2040 link unavailable"
        if not self.link.health_ok():
            return False, "RP2040 heartbeat/rp_ok/fault posture is unhealthy"
        identity_ok, reason = self.link.identity_status()
        if not identity_ok:
            return False, f"firmware identity is not current: {reason}"
        identity = self.link.fw_identity() or {}
        expected_pcb = "unknown" if self.board_rev == "revC" else "revD"
        expected_rid = 255 if self.board_rev == "revC" else 1
        if identity.get("pcb") != expected_pcb:
            return False, "firmware identity PCB revision mismatch"
        if identity.get("rid") != expected_rid:
            return False, "firmware identity REV_ID mismatch"
        heartbeat_rid = self.link.pcb_rev_id()
        if heartbeat_rid is not None and heartbeat_rid != expected_rid:
            return False, "heartbeat REV_ID disagrees with identity"
        build = identity.get("build")
        fw_cfg = identity.get("cfg")
        if build == "unknown" or str(build).endswith("-dirty"):
            return False, "firmware build is not releaseable"
        if fw_cfg == "unknown":
            return False, "firmware config identity is not releaseable"
        release = (
            self.board_rev, build, fw_cfg)
        if not self.qualified_releases:
            return False, "qualified firmware release policy is unconfigured"
        if release not in self.qualified_releases:
            return False, f"firmware tuple {release!r} is not qualified"
        maxrun_ms = self.link.maxrun_ms()
        if maxrun_ms is None:
            return False, "firmware max-run advertisement is missing"
        if not self.link.maxrun_ok():
            return False, f"firmware max-run {maxrun_ms} ms mismatches FSM"
        return True, f"qualified firmware; max-run={maxrun_ms} ms"

    def arm(self):
        with self._command_lock:
            self._cancel_relay_only_deadline()
            failures = self._safe_state_locked()
            if failures:
                raise RuntimeError(
                    "cannot prove pre-arm safe state: " + "; ".join(failures))
            allowed, reason = self._firmware_gate()
            relay_only = (
                self.link is None and self.allow_no_rp2040)
            if not allowed and not relay_only:
                raise RuntimeError(f"ARM refused: {reason}")
            if not self.kick_on.is_set():
                raise RuntimeError(
                    "ARM refused while watchdog kicks are stopped")
            self.io.arm(True)
            self.armed = True
            if relay_only:
                try:
                    self._start_relay_only_deadline()
                except Exception as exc:
                    self._cancel_relay_only_deadline()
                    failures = self._safe_state_locked()
                    suffix = (
                        "; safe-state failures: " + "; ".join(failures)
                        if failures else "")
                    raise RuntimeError(
                        "relay-only deadline could not start; ARM/output "
                        f"rolled safe ({type(exc).__name__}: {exc})"
                        + suffix) from exc
                reason = (
                    "OFF-MACHINE DUMMY-LOAD override; no firmware "
                    f"qualification; {self.relay_only_deadline_s:.3f}s "
                    "local hard-off deadline")
            self.output(f"ARM asserted ({reason})")

    def disarm(self):
        failures = self.safe_state()
        if failures:
            raise RuntimeError(
                "disarm safe-state incomplete: " + "; ".join(failures))
        self.output("ARM low; firmware stopped; all output latches low")

    def clear(self):
        if self.link is None:
            raise RuntimeError("CLEAR refused without an RP2040 link")
        failures = self.safe_state()
        if failures:
            raise RuntimeError(
                "CLEAR refused; safe-state incomplete: "
                + "; ".join(failures))
        if self.link.clear() is False:
            raise RuntimeError("CLEAR transport was not acknowledged")
        self.output("CLEAR sent with ARM and all output latches held low")

    def set_kick(self, enabled):
        if not enabled:
            self.kick_on.clear()
            self.output(
                "kick STOPPED; record TP16 timeout. 'kick start' will "
                "safe ARM and every output latch before resuming.")
            return
        failures = self.safe_state()
        if failures:
            raise RuntimeError(
                "kick resume refused; safe-state incomplete: "
                + "; ".join(failures))
        self.kick_on.set()
        self.output("kick resumed from ARM-low/all-off state")

    def set_output(self, name, enabled):
        with self._command_lock:
            if name not in MOTION + LAMPS:
                raise ValueError(f"unsupported output {name!r}")
            if enabled and name in MOTION:
                if not self.armed:
                    raise RuntimeError(
                        f"{name} ON refused while ARM is not explicitly "
                        "asserted")
                if not self.kick_on.is_set():
                    raise RuntimeError(
                        f"{name} ON refused while watchdog kicks are stopped")
                if self.link is None:
                    with self._deadline_lock:
                        deadline_at = self._relay_only_deadline_at
                    if (
                            not self.allow_no_rp2040
                            or deadline_at is None
                            or time.monotonic() >= deadline_at):
                        failures = self._safe_state_locked()
                        raise RuntimeError(
                            "relay-only deadline is absent/expired; output "
                            "refused"
                            + (
                                "; " + "; ".join(failures)
                                if failures else ""
                            ))
            self.io._set_out(name, bool(enabled))

    def status(self):
        gate_ok, gate_reason = self._firmware_gate()
        facts = {
            "armed": self.armed,
            "kicking": self.kick_on.is_set(),
            "arm_gate_ok": gate_ok,
            "arm_gate_reason": gate_reason,
            "firmware_maxrun_qualified":
                bool(gate_ok and self.link is not None),
            "relay_only_override_enabled": bool(
                self.link is None and self.allow_no_rp2040),
            "relay_only_deadline_remaining_s": None,
        }
        with self._deadline_lock:
            deadline_at = self._relay_only_deadline_at
        if deadline_at is not None:
            facts["relay_only_deadline_remaining_s"] = max(
                0.0, deadline_at - time.monotonic())
        if self.link is not None:
            facts.update({
                "rp_ok": self.link.rp_ok(),
                "fault": self.link.fault(),
                "alive": self.link.is_alive(),
                "health_ok": self.link.health_ok(),
                "identity": self.link.fw_identity(),
                "maxrun_ms": self.link.maxrun_ms(),
                "running_motors": self.link.running_motors(),
            })
        self.output(repr(facts))
        return facts

    def handle(self, line):
        parts = line.strip().split()
        if not parts:
            return True
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit") and len(parts) == 1:
            return False
        if cmd == "arm" and len(parts) == 1:
            self.arm()
            return True
        if cmd == "disarm" and len(parts) == 1:
            self.disarm()
            return True
        if cmd == "off" and len(parts) == 1:
            self.disarm()
            return True
        if cmd == "status" and len(parts) == 1:
            self.status()
            return True
        if cmd == "clear" and len(parts) == 1:
            self.clear()
            return True
        if cmd == "kick" and len(parts) == 2:
            state = parts[1].lower()
            if state in ("stop", "off"):
                self.set_kick(False)
                return True
            if state in ("start", "on"):
                self.set_kick(True)
                return True
            raise ValueError("kick state must be start/on or stop/off")

        name = cmd.upper() if cmd.upper() in MOTION else cmd
        if name in MOTION + LAMPS and len(parts) == 2:
            state = parts[1].lower()
            if state not in ("on", "1", "off", "0"):
                raise ValueError("output state must be on/1 or off/0")
            self.set_output(name, state in ("on", "1"))
            return True
        raise ValueError(
            "commands: arm | disarm | s|t|sp|be|m|m2 on|off | "
            "first_ball|second_ball|strike|foul on|off | off | "
            "kick stop|start | status | clear | q")


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=int, choices=sorted(BOARD_CONFIGS),
                        default=21)
    parser.add_argument("--board-rev", choices=("revC", "revD"),
                        default="revD")
    parser.add_argument(
        "--relay-only-without-rp2040", action="store_true",
        help="permit a 1-second relay make/break pulse only when physically "
             "off-machine on a dummy load; cannot qualify firmware max-run")
    parser.add_argument(
        "--confirm-off-machine-dummy-load", action="store_true",
        help="required physical-isolation declaration for relay-only mode")
    args = parser.parse_args(argv)
    if (
            args.relay_only_without_rp2040
            and not args.confirm_off_machine_dummy_load):
        parser.error(
            "--relay-only-without-rp2040 requires "
            "--confirm-off-machine-dummy-load")
    if (
            args.confirm_off_machine_dummy_load
            and not args.relay_only_without_rp2040):
        parser.error(
            "--confirm-off-machine-dummy-load is valid only with "
            "--relay-only-without-rp2040")
    return args


def main(
        argv=None, *, input_fn=input, output_fn=print,
        hardware_loader=_hardware_dependencies,
        lease_factory=ControllerOwnerLease):
    args = _parse_args(argv)
    cfg = BOARD_CONFIGS[args.lane]
    releases = _parse_qualified_releases(
        os.environ.get(QUALIFIED_RELEASES_ENV, ""))

    # Acquire before hardware module imports or object construction.
    lease = lease_factory(_state_dir(), args.lane)
    lease.acquire()

    arm_led = None
    wdog = None
    link = None
    io = None
    session = None
    kick_thread = None
    stop = threading.Event()
    kick_on = threading.Event()
    kick_on.set()
    cleanup_failures = []
    try:
        LED, MachineIO, out_a_map, RP2040Link = hardware_loader()
        for name in MOTION + LAMPS:
            if name not in out_a_map:
                raise RuntimeError(f"{name} missing from OUT_A_MAP")

        arm_led = LED(cfg["arm_pin"])
        wdog = LED(cfg["wdog_pin"])

        def kicker():
            while not stop.is_set():
                if kick_on.is_set():
                    wdog.on()
                    time.sleep(WDOG_PULSE_S)
                    wdog.off()
                stop.wait(KICK_PERIOD_S)

        candidate_link = None
        try:
            candidate_link = RP2040Link(port=cfg["uart"])
            candidate_link.start()
            time.sleep(0.5)
            link = candidate_link
        except Exception as exc:
            if candidate_link is not None:
                try:
                    candidate_link.close()
                except Exception:
                    pass
            output_fn(
                f"RP2040 link unavailable ({exc}). ARM remains refused "
                "unless --relay-only-without-rp2040 was explicit.")
            link = None

        io = MachineIO(
            args.lane, cfg["bus"],
            watchdog_kick=lambda: None,
            arm_relays=lambda on: setattr(
                arm_led, "value", 1 if on else 0),
            rp2040=link, board_rev=args.board_rev)
        session = BenchSession(
            io, link, arm_led, wdog, kick_on,
            board_rev=args.board_rev,
            qualified_releases=releases,
            allow_no_rp2040=(
                args.relay_only_without_rp2040
                and args.confirm_off_machine_dummy_load),
            output=output_fn)
        initial_failures = session.safe_state()
        if initial_failures:
            raise RuntimeError(
                "initial safe-state incomplete: "
                + "; ".join(initial_failures))

        kick_thread = threading.Thread(
            target=kicker, name="first-article-kicker", daemon=True)
        kick_thread.start()
        output_fn(
            f"Owner lease held for L{args.lane}; I2C bus {cfg['bus']}; "
            f"UART {cfg['uart']}; board {args.board_rev}.")
        output_fn(
            f"NE555 kick GPIO{cfg['wdog_pin']} every {KICK_PERIOD_S:.0f}s; "
            f"ARM GPIO{cfg['arm_pin']} LOW; every output latch LOW.")
        while True:
            try:
                line = input_fn("bench> ")
            except EOFError:
                break
            try:
                if not session.handle(line):
                    break
            except Exception as exc:
                output_fn(f"command refused ({type(exc).__name__}: {exc})")
                failures = session.safe_state()
                if failures:
                    raise RuntimeError(
                        "command failure followed by incomplete safe-state: "
                        + "; ".join(failures)) from exc
    except KeyboardInterrupt:
        output_fn("interrupt received; entering safe shutdown")
    finally:
        stop.set()
        kick_on.clear()
        if session is not None:
            cleanup_failures.extend(session.safe_state())
            cleanup_failures.extend(session.background_failures)
        elif arm_led is not None:
            try:
                arm_led.off()
            except Exception as exc:
                cleanup_failures.append(
                    BenchSession._error("arm_low", exc))
        if kick_thread is not None:
            kick_thread.join(KICK_PERIOD_S + WDOG_PULSE_S + 0.25)
            if kick_thread.is_alive():
                cleanup_failures.append("kicker_thread:did_not_stop")
        if wdog is not None:
            try:
                wdog.off()
            except Exception as exc:
                cleanup_failures.append(
                    BenchSession._error("watchdog_low", exc))
        if io is not None:
            try:
                io.close()
            except Exception as exc:
                cleanup_failures.append(
                    BenchSession._error("machine_io_close", exc))
        if link is not None:
            try:
                link.stop_all()
            except Exception as exc:
                cleanup_failures.append(
                    BenchSession._error("firmware_final_stop", exc))
            try:
                link.close()
            except Exception as exc:
                cleanup_failures.append(
                    BenchSession._error("rp2040_close", exc))
        for label, device in (("watchdog_close", wdog),
                              ("arm_close", arm_led)):
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    cleanup_failures.append(
                        BenchSession._error(label, exc))
        try:
            lease.release()
        except Exception as exc:
            cleanup_failures.append(
                BenchSession._error("owner_lease_release", exc))

    if cleanup_failures:
        output_fn(
            "SAFE SHUTDOWN INCOMPLETE: " + "; ".join(cleanup_failures))
        return 2
    output_fn("safe-off complete: outputs off, ARM low, kick low")
    return 0


if __name__ == "__main__":
    sys.exit(main())
