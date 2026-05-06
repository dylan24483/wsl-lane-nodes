# Hardware Watchdog Design — Phase 8a

**Purpose:** the 4th and final pillar of the Step-K mitigation stack. Closes the gap that systemd `ExecStopPost=` can't cover: situations where the Pi process never gets reaped at all because the kernel itself locked up, the Pi lost power, or the systemd cleanup script also failed.

**Failure modes this catches:**
- Kernel panic mid-pulse (no chance for systemd to run anything)
- Hardware fault on the Pi (board damage, VRM failure, SD card corruption mid-write)
- Total power loss to the Pi while a relay is closed
- Pathological asyncio deadlock that prevents any normal cleanup
- Cosmic-ray-induced memory bit-flip into a tight infinite loop

**What it does NOT cover** (those rely on the layers above it):
- SIGTERM from systemd — Python signal handler covers this
- SIGKILL / segfault / OOM — systemd ExecStopPost cleanup script covers this
- Mid-pulse coroutine cancellation — try/finally on `pulse()` covers this

The watchdog is the dumb-as-rocks last line of defense. **It must work even if every line of Python code is broken.**

---

## Topology overview

```
                         5V external supply
                                |
                                |
                +---------------+--------------+
                |                              |
                |                  +-----------+----------+
            [Pi 5V]                |                      |
                |                  |   Watchdog circuit   |
        +-------+--------+         |  (CD4538B or 555     |
        |     Pi 4       |         |   monostable)        |
        |                |         |                      |
        |  GPIO X (kick) +--------→| TRIG / RETRIG        |
        |                |         |                      |
        |  (other GPIOs) +-------→ | (pass-through        |
        |                |         |  to relay board IN)  |
        +----------------+         |                      |
                                   |                      |
                                   |  OUTPUT_GATE (NPN)   |
                                   +-----------+----------+
                                               |
                                               | gates VCC to
                                               | relay COIL supply
                                               |
                                       +-------+-------+
                                       |  Relay board  |
                                       |  (AEDIKO 8x)  |
                                       |  PWR / VCC    |
                                       +---------------+
```

**Key idea:** the relay board's coil supply is gated by an NPN/MOSFET that's controlled by the watchdog's output. As long as the Pi keeps pulsing the watchdog's TRIG input every ~1 second, the watchdog's output stays HIGH and the gate stays ON. If the kick stream stops for >5 seconds, the watchdog times out, the gate opens, and **all relay coils lose power simultaneously** — every relay drops to its mechanical default-open state regardless of what the Pi GPIO is doing.

The Pi GPIO control signals (IN1–IN8) keep going to the relay board's IN pins as before. Those signals are irrelevant when the coils have no power — the relays simply can't close.

---

## Recommended IC: CD4538B (dual retriggerable monostable)

**Why CD4538B over a 555:**
- Built-in retrigger logic (the 555 needs an external inverter or RC discharge network for clean retriggering)
- Schmitt-trigger inputs (cleaner kick signal acceptance from a Pi GPIO)
- Two independent monostables in one IC — second half is a free spare for future expansion
- ~$1 at Mouser / Digikey, in stock everywhere
- CMOS — runs from 3-15V, sits comfortably on the same 5V rail as the Pi and relay board

**Why not a 555:** works, but needs an extra transistor for retrigger and is more sensitive to noise on the TRIG pin. CD4538B is purpose-built for this exact pattern.

**Why not a microcontroller (ATtiny85):** adds firmware = adds another point of failure. The whole point of a hardware watchdog is "what if software fails?" — we don't want the watchdog to be more software.

---

## Schematic (CD4538B-based)

```
                     +5V
                      |
                      |
            +---------+----------+
            |                    |
            |                    R1 (timing)
            |                    100kΩ
            |                    |
            |                    +----+----+
            |                    |    |    |
            |                    |    C1   |
            |                    |   100µF |
            |                    |   ceramic
            |                    |    |    |
            |                    |   GND   |
            |                    |
            +-+ Pin 16 VCC       +-- Pin 1 (RC)
              |                  |
              |                  +-- Pin 2 (C ext)
              |                  |
              |              +---+   IC: CD4538B
              |              |
              |     ┌────────┴───────┐
              |     │                │
        Pi    |     │   1A   ←  Pin 4 ─── from Pi GPIO X
       GPIO X +---->│   /1A  ←  Pin 5 ─── HIGH (5V via pull-up)
              |     │                │
              |     │   /Q1  →  Pin 7 ─── (unused)
              |     │   Q1   →  Pin 6 ─── to NPN Q1 base via R3 (10kΩ)
              |     │                │
              |     │   Pin 3  ─── /CD (clear)  ─ HIGH (5V via pull-up)
              |     │                │
              |     │   Pin 8  ─── GND
              |     └────────────────┘
              |
              |
              |   NPN: 2N3904 (or any small-signal NPN)
              |
              |              +5V_RELAY_COIL_SUPPLY
              |                    |
              |                    | (cuts here when watchdog times out)
              |                    |
              |              [Q1 collector]
              |                    |
              |          base +----+
              |     R3 ──────|    Q1 (2N3904)
              |  10kΩ        |
              |              [Q1 emitter]
              |                    |
              |                    +────→ Relay board PWR (DC+/DC-)
              |                          (or to AEDIKO's coil-side
              |                           power input if it has one)
              |                    |
              |                   GND
              |
       Pi GND +────────────────── (common ground)
```

**Output stage notes:**
- The 2N3904 is fine for low-current relay coil supply (each AEDIKO coil draws ~70mA, 8 channels = max 560mA). 2N3904 max collector current is 200mA — **may need a beefier NPN or a MOSFET for the production 8-channel case.**
- Better choice for production: **MOSFET like 2N7000 (200mA, dirt cheap) or IRLZ44N (logic-level, 47A — gross overkill but bulletproof).** A logic-level N-channel MOSFET driven from CD4538B's Q1 output (~5V high) saturates fully.
- If using a MOSFET, R3 becomes a gate resistor (1kΩ-10kΩ to limit gate-charge inrush) and add an optional gate pull-down (10kΩ to ensure FET is OFF when CD4538B output floats during watchdog timeout).

**Timing:**
- T_OUT = R1 × C1 = 100kΩ × 100µF = 10 seconds
- Pi kicks every ~1 second; watchdog tolerates up to 10 seconds of missed kicks before firing
- Adjust R1 or C1 to taste — formula `T = R × C` for CD4538B (different from 555's 1.1×R×C)

---

## Bill of materials

| Part | Qty | Approx cost | Source |
|---|---|---|---|
| CD4538B DIP-16 | 1 | $0.80 | Mouser / Digikey |
| IRLZ44N or 2N7000 N-MOSFET | 1 | $0.50-$1.50 | Same |
| 100kΩ resistor 1/4W (timing R1) | 1 | $0.05 | Same |
| 100µF electrolytic 16V (timing C1) | 1 | $0.20 | Same |
| 10kΩ resistor (gate / pull-up) | 3 | $0.15 | Same |
| 1kΩ resistor (gate series, if using MOSFET) | 1 | $0.05 | Same |
| Solid-core jumper wire / breadboard / perfboard | as needed | $1-3 | Same |
| **Total per pair** | | **~$3-5** | |

For 16 pairs (full Westside install): **~$50-80** in watchdog parts. Buy 2-3× the count for spares; CD4538B chips are cheap and easy to fry.

---

## Pi-side code changes

A small addition to `lane_node.py`: a dedicated kick coroutine that pulses a GPIO every 1 second, independent of WebSocket connection state. It must run as long as asyncio is healthy.

```python
# Pin assignment — pick a free GPIO. Suggest GPIO 12 (header pin 32).
WATCHDOG_KICK = LED(12)

async def watchdog_kicker():
    """Pulse the hardware watchdog every 1 second.

    Runs forever as long as the asyncio loop is alive. If this coroutine
    stops (deadlock, hang, etc.), the external CD4538B times out after
    its configured timeout (~10s) and cuts power to all relay coils.
    """
    while True:
        WATCHDOG_KICK.on()
        await asyncio.sleep(0.020)  # 20ms pulse — well above CD4538B
                                    # min trigger pulse width
        WATCHDOG_KICK.off()
        await asyncio.sleep(1.0)    # 1 sec between kicks
```

Add `watchdog_kicker()` to the `asyncio.gather(...)` call in `main()`:

```python
await asyncio.gather(
    heartbeat_loop(ws),
    event_sender(ws),
    command_handler(ws),
    watchdog_kicker(),  # new
)
```

The kicker is INSIDE the connection-loop's gather, which means it stops if the WebSocket connection is broken. **That's intentional** — if the Pi can't talk to the server, we don't want pinsetters cycling either. The watchdog will time out, drop relays, and pinsetters stop. When the connection re-establishes, the kicker restarts and the watchdog re-enables.

Alternative: kicker could live OUTSIDE the connection-loop (always running while the Python process is alive). Argument for: relay coil supply stays up during transient network drops, so a brief reconnect doesn't drop pinsetter mid-game. Argument against: if the Pi has lost network forever (bad cable, dead switch), pinsetters keep responding to whatever GPIO state is set.

**Decision: keep kicker inside the connection-loop.** Network-loss = pinsetter-pause is the safe default. Resume on reconnect.

---

## Bench test procedure (after build)

1. **Wire the CD4538B + MOSFET on a breadboard.** Don't connect to the relay board yet — first test the watchdog in isolation.
2. **Probe the MOSFET drain (where coil supply will hook up) with a multimeter.** With Pi running and `watchdog_kicker()` firing every 1 sec, drain should sit at +5V (gate is HIGH, MOSFET conducting).
3. **Stop `watchdog_kicker()`** by killing lane_node.py. Within ~10 seconds (timing depends on R1×C1), the MOSFET drain should drop to 0V — watchdog has timed out.
4. **Restart lane_node.py.** Drain should return to +5V within 20ms of the first kick — watchdog re-enabled.
5. **Now wire the MOSFET drain to the AEDIKO PWR (DC+) input.** Run the existing bench tests:
   - Power On / Power Off should still work normally (kicks are happening, coil supply is up).
   - Force a watchdog timeout (kill -9 lane_node.py): all relays drop open within ~10s, even ones that were latched HIGH.
   - Restart lane_node.py: relays don't auto-close (their GPIO state may be stale, but coil supply went down then up; the relay board defaults to open on cold-start).

**Pass criteria:**
- Kicks every 1 sec → coil supply HIGH continuously
- No kicks for >10 sec → coil supply LOW, relays open
- Resume kicks → coil supply HIGH within 20ms
- Edge case: a single missed kick (e.g., 2-second gap) does NOT trigger — the timeout is intentionally longer than the kick interval

---

## Production wiring notes

- **Mount the watchdog on the same DIN-rail enclosure as the Pi** at each lane pair. Single physical assembly, less cabling, easier to service.
- **The watchdog's coil-side power supply should be the SAME 5V brick that feeds the AEDIKO PWR input today.** No separate power rail needed.
- **Consider a status LED** on the MOSFET drain — easy visual indicator of "watchdog is healthy" (LED lit) vs "watchdog has timed out" (LED off). Helps field troubleshooting.
- **Don't put the watchdog inside the 8270 cabinet.** Heat + vibration are too aggressive for breadboard / perfboard construction.

---

## Calibration

R1 × C1 = T_OUT (in seconds). Picking sensible values:

| R1 | C1 | T_OUT | Comment |
|---|---|---|---|
| 47kΩ | 100µF | 4.7s | Aggressive — false positives if CPU spike delays a kick by 5s |
| 100kΩ | 100µF | 10s | **Recommended starting point** |
| 220kΩ | 100µF | 22s | Conservative — leaves pinsetter cycling for up to 22s before dropping |
| 100kΩ | 220µF | 22s | Same as above, different component combo |

The Pi kicks every 1 second. A 10-second timeout tolerates 9 missed kicks, which is generous — under normal operation the Pi shouldn't miss even one. False-positive rate at 10s should be effectively zero.

Tune by observing: deploy with 10s, monitor the journal for any "watchdog timeout fired during normal operation" events over a 1-week soak. If zero events, can leave at 10s. If any spurious events, bump to 22s.

---

## Future enhancements

- **Telemetry**: have the watchdog's output wire back to a Pi GPIO (input) so the Pi can detect "I just came up after a watchdog event" and log it. Useful for debugging crash patterns.
- **Independent power for the watchdog**: today the watchdog runs off the Pi's 5V rail. If the Pi loses 5V, the watchdog loses 5V too — but that's actually fine because losing 5V to the watchdog also drops the MOSFET, opening the coil supply. Belt-and-suspenders done by accident.
- **Two-channel watchdog** for redundancy: CD4538B has two independent monostables. Wire the second channel to a different Pi GPIO and require BOTH kicks to keep coil supply up. Detects single-point software failures (e.g., one thread alive while another deadlocked).

---

## Status

- Design: complete (this document)
- Build: not yet started
- Bench test: not yet started
- Production deployment: gated by Phase 8a hardware planning + lane visit findings

This document is the spec; the build happens during Phase 8a hardware prep alongside the Pi adapter cable build.
