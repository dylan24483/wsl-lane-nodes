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

Best-effort semantics, but failures are VISIBLE: each failed pin is
reported on stderr (systemd captures it in the journal) and the script
exits nonzero if ANY pin could not be driven LOW, so `systemctl status
lane-node` shows the degraded cleanup instead of silent success. If a
relay is genuinely electrically stuck (welded contacts, etc.), no
software can help.
"""
import sys

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

# The hardware-watchdog kick pin (NE555 pet line). NOT a relay, but it MUST
# be forced LOW here too. If lane_node.py died mid-kick with GPIO 12 retained
# HIGH, the BCM2711 keeps driving it HIGH → the NE555 sees a steady kick →
# the watchdog is held ALIVE → the relay-coil return never opens and the
# relays never drop. Driving it LOW lets the watchdog time out (~11s) and
# safe-open the coil return as designed. Keep in sync with lane_node.py's
# WATCHDOG_KICK_PIN.
WATCHDOG_KICK_PIN = 12

if __name__ == '__main__':
    failed = 0
    for pin in RELAY_PINS + [WATCHDOG_KICK_PIN]:
        try:
            led = LED(pin)
            led.off()
            led.close()
        except Exception as e:
            # best effort continues to the next pin, but NEVER silently:
            failed += 1
            print(f"relay_cleanup: GPIO {pin} drive-LOW FAILED: {e!r}", file=sys.stderr)
    if failed:
        print(f"relay_cleanup: {failed} pin(s) NOT confirmed LOW — relays may still be "
              f"energized; check the machine", file=sys.stderr)
        sys.exit(1)
