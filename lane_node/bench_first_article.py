#!/usr/bin/env python3
"""First-article bench tool — rev-C board, ONE lane-21 board, NO FSM.

Drives individual J_MOTION relays through the real MachineIO stack
(MCP OUT-A writes + the C-02 OLAT readback) while a background thread
kicks the NE555, so RELAY_ENABLE_RAIL can come up without running the
daemon/FSM. Readiness checklist §4: energize ONE relay, prove
make/break at its J6-J11 terminals, then repeat across all six.

Prereqs: board powered via J2 (PSU limit >=1 A for relay work), J14
pin1<->2 and pin3<->4 jumpered, Pico flashed + RP2040_OK (TP14) high,
ribbon conductors 2/3/4 (I2C) + 7/8 (wdog/arm) landed.

Commands at the bench> prompt:
    arm / disarm             assert or drop ARM_PERMIT (GPIO26)
    s|t|sp|be|m|m2 on|off    energize / release one relay (K1..K6)
    off                      all motion outputs off
    kick stop|start          stop/resume NE555 kicks (watchdog-drop test)
    q                        safe exit

Exit ALWAYS lands: outputs off, ARM low, kick pin low (fail-safe).
"""
import sys
import threading
import time

from gpiozero import LED

from controller_io import MachineIO, OUT_A_MAP

LANE, BUS = 21, 1
ARM_PIN, WDOG_PIN = 26, 12          # controller_daemon DEFAULT_BOARDS lane-21 (FIRM)
WDOG_PULSE_S = 0.002                # same bounded pulse shape as the daemon
KICK_PERIOD_S = 1.0                 # NE555 RC ~11 s -> 1 s kicks = wide margin
MOTION = ["S", "T", "SP", "BE", "M", "M2"]   # K1..K6 = J6..J11


def main():
    for n in MOTION:
        assert n in OUT_A_MAP, f"{n} missing from OUT_A_MAP"

    arm_led = LED(ARM_PIN)          # de-asserted at construction
    wdog = LED(WDOG_PIN)
    kick_on = threading.Event()
    kick_on.set()
    stop = threading.Event()

    def kicker():
        while not stop.is_set():
            if kick_on.is_set():
                wdog.on()
                time.sleep(WDOG_PULSE_S)
                wdog.off()
            stop.wait(KICK_PERIOD_S)

    io = MachineIO(
        LANE, BUS,
        watchdog_kick=lambda: None,  # the kicker thread owns the pin
        arm_relays=lambda on: setattr(arm_led, "value", 1 if on else 0),
    )
    threading.Thread(target=kicker, daemon=True).start()

    print(f"NE555 kicked on GPIO{WDOG_PIN} every {KICK_PERIOD_S:.0f}s; "
          f"ARM (GPIO{ARM_PIN}) is LOW.")
    print("H-08 check FIRST: meter TP16 now — must read ~0 V while disarmed.")
    print("Then 'arm' -> TP16 ~= VCC_5V, then 's on' for the first click.")
    try:
        while True:
            try:
                line = input("bench> ").strip().lower()
            except EOFError:
                break
            if not line:
                continue
            p = line.split()
            if p[0] in ("q", "quit", "exit"):
                break
            elif p[0] == "arm":
                io.arm(True)
            elif p[0] == "disarm":
                io.arm(False)
            elif p[0] == "off":
                for n in MOTION:
                    io._set_out(n, False)
            elif p[0] == "kick" and len(p) > 1:
                if p[1] in ("stop", "off"):
                    kick_on.clear()
                    print("kick STOPPED — time it: TP16 should drop in ~11 s "
                          "(record the actual NE555 timeout)")
                else:
                    kick_on.set()
                    print("kick resumed")
            elif p[0].upper() in OUT_A_MAP and len(p) > 1:
                io._set_out(p[0].upper(), p[1] in ("on", "1"))
            else:
                print("commands: arm | disarm | s|t|sp|be|m|m2 on|off | off | "
                      "kick stop|start | q")
    finally:
        stop.set()
        try:
            for n in MOTION:
                io._set_out(n, False)
            if hasattr(io, "all_off"):
                io.all_off()
        except Exception as e:
            print("cleanup (outputs):", e)
        try:
            io.arm(False)
        except Exception as e:
            print("cleanup (arm):", e)
        wdog.off()
        print("safe-off complete: outputs off, ARM low, kick low.")


if __name__ == "__main__":
    sys.exit(main() or 0)
