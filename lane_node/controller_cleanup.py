#!/usr/bin/env python3
"""Drive the Track-B controller's ARM + watchdog-kick GPIOs LOW. systemd ExecStopPost=.

Runs after controller_daemon.py is reaped, regardless of how it died (clean exit,
SIGTERM, SIGKILL, segfault, OOM) -- the GPIO-level backstop to the daemon's own
safe_off(), which only runs on the graceful path.

Why these two pins:
  * ARM (relay-enable permission) -- drive LOW so the relay-enable rail cannot be
    permitted while no daemon is running.
  * NE555 watchdog kick -- the BCM2711 RETAINS its last drive state when the kernel
    releases the lgpio line claim. If the daemon died mid-kick with the kick pin
    HIGH, the pad keeps driving HIGH -> the NE555 keeps seeing an "alive" pet ->
    the rail stays permitted. Driving it LOW lets the watchdog time out (~10 s)
    and drop the rail as designed. (Same hazard relay_cleanup.py handles for the
    8a scoring node, but for that node's pins.)

The MCP23017 relay *outputs* are intentionally NOT touched here: every motion
relay sits downstream of the relay-enable rail, which the watchdog drops in
hardware once the kick stops. So forcing ARM + kick LOW is sufficient.

Best-effort semantics, but failures are VISIBLE (same pattern as
relay_cleanup.py): each failed pin is reported on stderr (systemd captures it
in the journal) and the script exits nonzero if ANY pin could not be driven
LOW, so `systemctl status lane-node-controller` shows the degraded cleanup
instead of silent success. Per-pin isolation is kept -- one failure never
skips the remaining pins. If the import of DEFAULT_BOARDS isn't available at
stop time, fall back to the hardcoded pins (keep them in sync).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from controller_daemon import DEFAULT_BOARDS
    PINS = sorted({p for b in DEFAULT_BOARDS for p in (b.arm_pin, b.wdog_pin)})
except Exception as e:
    # Fallback if the import chain isn't importable when systemd runs this.
    # arm_pin(21,22)=26,13 ; wdog_pin(21,22)=12,6  -- KEEP IN SYNC with DEFAULT_BOARDS.
    PINS = [6, 12, 13, 26]
    print(f"controller_cleanup: DEFAULT_BOARDS import failed ({e!r}); "
          f"using hardcoded fallback pins {PINS}", file=sys.stderr)

if __name__ == "__main__":
    from gpiozero import LED
    failed = 0
    for pin in PINS:
        try:
            led = LED(pin)
            led.off()
            led.close()
        except Exception as e:
            # best effort continues to the next pin, but NEVER silently:
            failed += 1
            print(f"controller_cleanup: GPIO {pin} drive-LOW FAILED: {e!r}",
                  file=sys.stderr)
    if failed:
        print(f"controller_cleanup: {failed} pin(s) NOT confirmed LOW — ARM/kick "
              f"may still be driven HIGH; the NE555 should drop the rail within "
              f"~11 s, but check the machine", file=sys.stderr)
        sys.exit(1)
