#!/usr/bin/env python3
"""Drive all relay GPIOs LOW. Called by systemd ExecStopPost=.

Runs after lane_node.py is reaped, regardless of how it died. Catches
SIGKILL / segfault / OOM / kernel-panic-recovery scenarios that
lane_node.py's own SIGTERM handler can't catch.

Why this exists: the BCM2711 GPIO peripheral retains its last drive
state when the kernel releases an lgpio line claim. If lane_node.py
crashed while a relay was closed (GPIO HIGH), the kernel frees the
line claim but the GPIO pad keeps driving HIGH — pinsetter stays
stuck cycling. This script's only job is to explicitly re-claim each
relay GPIO, drive it LOW, and release. The kernel then leaves the
pad in OUTPUT-LOW state — relay open.

Best-effort: any exception is swallowed. If a relay is genuinely
electrically stuck (welded contacts, etc.), no software can help.
"""
from gpiozero import LED

# Keep this list in sync with lane_node.py's LANE_GPIO cycle+power
# values. ExecStopPost runs once when the main daemon is reaped; it
# needs to know every relay GPIO the daemon could have left HIGH.
RELAY_PINS = [
    24,  # PINSETTER_CYCLE for lane 21
    25,  # PINSETTER_POWER for lane 21
    27,  # PINSETTER_CYCLE for lane 22
    23,  # PINSETTER_POWER for lane 22
]

if __name__ == '__main__':
    for pin in RELAY_PINS:
        try:
            led = LED(pin)
            led.off()
            led.close()
        except Exception:
            pass  # best effort
