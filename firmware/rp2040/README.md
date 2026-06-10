# WSL Phase 8b — RP2040 lane-controller firmware

**v0.2.0 — DRAFT, bench-bring-up gated. Not for a live machine until validated per `docs/phase8b_pcb_revB_spec.md` §12.9.**
*(v0.2.0, 2026-06-10 audit hardening: RX overrun whole-line discard, duplicate-RUN timer guard, boot-settle latch across the uint32 ms wrap, per-input chatter fault, TX headroom for critical lines, oversized-emit whole-line drop, hb `in`/`run` masks, boot `maxrun_ms`/`dbg`. Pin map, pin assignments, and command grammar UNCHANGED.)*

One RP2040 (a stock Raspberry Pi Pico module) sits on each rev-B controller board and is the **fast + safety half** of the lane controller. The Raspberry Pi runs the cycle FSM (`lane_node/cycle_control_8270.py`) and commands relays over I²C/MCP23017; this firmware owns the latency-critical inputs and the hardware rail-permission line.

> ⚠️ **Safety co-processor.** It drives `RP2040_OK` (GP2), a non-bypassable condition in the relay-enable-rail AND chain (spec §4.1). It is **never the only safety device** — the TB/SC collision interlock (J_SAFETY hardware loop), the Stop/CIS/master-breaker chain, the NE555 watchdog (which watches the *Pi*), and regenerative motor braking are all in hardware, independent of this firmware. Read the safety section before editing.

## What it does (v1)

1. **Reads 8 fast inputs** (6 cams + 2 DIELL ball beams), debounces, and **pushes edge events to the Pi over uart0** — the FSM consumes events, it does not poll, so cam timing isn't subject to Pi scheduling latency.
2. **Drives `RP2040_OK` (GP2)** = rail permission. **HIGH only when healthy; LOW on boot, fault, or hang.** Fail-safe by construction (see below).
3. **UART-independent safety backstops:**
   - **Firmware health** — the RP2040 hardware watchdog: if the main loop hangs, the chip resets → GP2 goes Hi-Z → the board's external 100k base-pulldown holds the rail **dead**.
   - **Motion max-run ("cam timeout", spec §4.2)** — if the Pi marks a guarded motor `RUN` and never `STOP`s it within `MAX_MOTION_MS` (8 s, matches the FSM), the firmware **latches a fault and drops RP_OK**.
4. **Heartbeats to the Pi** so a dead/`!ok` RP2040 is detected (the Pi then drops its ARM GPIO → rail drops).

### Deferred to v1.1 (intentionally NOT in this firmware)
- **Cam-stop OVERRUN enforcement** (a stop-cam fires while a motor is RUNNING and the Pi fails to `STOP` within a grace window → drop RP_OK). It needs the **per-cam edge→angle polarity**, which is a deliberately-deferred cutover field item (`docs/phase8_trackB_controller_cutover_runbook.md` §3.2). We do not bake in unconfirmed cam polarity. Hook is marked `// v1.1` in `main.c`.
- **SC/TB collision echo gating RP_OK** — the hardware J_SAFETY loop is primary; the firmware echo is enabled once the SC/TB windows are bench-confirmed.

## Authoritative pin map

Source of truth: `scripts/generate_kicad_netlist_revB.py` → `block_rp2040()` (the live board netlist). Re-verify against it if the board changes. **Do not** use the older `docs/phase8_channel_allocation.md` §2 GPIO column — it predates the as-built board (it had the fast inputs on GP0–GP7; the real board uses GP6–GP13).

| GPIO | Pico pin | Signal | Dir | Net | Notes |
|---|---|---|---|---|---|
| GP0 | 1 | UART0 TX → Pi RX | out | `PI_UART_RX` | protocol transport |
| GP1 | 2 | UART0 RX ← Pi TX | in | `PI_UART_TX` | protocol transport |
| GP2 | 4 | `RP2040_OK` | out | `RP2040_OK` | HIGH=permit, LOW=drop rail; fail-safe-low |
| GP6 | 9 | SA (sweep cam) | in | `FAST_SA` | active-low opto; 270 run-through / 360 zero |
| GP7 | 10 | SB (sweep cam) | in | `FAST_SB` | 66 guard / 186 table-spot init |
| GP8 | 11 | SC (sweep interlock cam) | in | `FAST_SC` | sweep-under-table 86–243 |
| GP9 | 12 | TA1 (table cam) | in | `FAST_TA1` | 355 zero / 185 delay-reset |
| GP10 | 14 | TA2 (table cam) | in | `FAST_TA2` | 260 run-through / pin-latch / ball-strike decision |
| GP11 | 15 | TB (table interlock cam) | in | `FAST_TB` | table-sweep interference 105–255 |
| GP12 | 16 | DIELL-L (ball) | in | `FAST_DIELL_L` | active-low opto; cushion SS trigger |
| GP13 | 17 | DIELL-R (ball) | in | `FAST_DIELL_R` | active-low opto |

All inputs are **active-low** at the Pico (machine contact closed → GPIO LOW); on-board 10k pull-up to 3V3, internal pull-up also enabled.

## Build

Needs the [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk) + `arm-none-eabi-gcc` + CMake.

```bash
export PICO_SDK_PATH=/path/to/pico-sdk          # or: cmake -DPICO_SDK_FETCH_FROM_GIT=ON
cd firmware/rp2040
cmake -B build -S .                              # add -DDEBUG_USB=ON to mirror events to USB-CDC
cmake --build build
# -> build/wsl_phase8b_rp2040.uf2
```

On the Westside laptop, **`pwsh -File build.ps1`** does all of the above — it auto-discovers the bootstrapped toolchain (xpack `arm-none-eabi-gcc` 13.3.1 + WinLibs CMake/Ninja + the cloned pico-sdk). **Verified 2026-06-03:** clean cross-compile + link → `wsl_phase8b_rp2040.uf2` (40 KB; uses ~24 KB flash / 2.6 KB RAM of the RP2040's 2 MB / 264 KB).

## Host logic test (no hardware)

The pure logic (TX ring, debounce/edges, ball lockout, UART protocol, the RP_OK safety supervisor) has a host unit test that mocks the Pico SDK — build + run it with any host C compiler:

```bash
# from firmware/rp2040/  (gcc or a MinGW clang; plain clang on Windows needs the Windows SDK for libc headers)
gcc -std=c11 -Wall -Wextra -I test -I test/stubs test/test_main.c -o test/test_main.exe
./test/test_main.exe        # exit 0 = all checks pass
```

Last run: **55/55 checks passed** (2026-06-10, gcc 16.1.0), clean under `-Wall -Wextra` + the `printf`-format attribute (so the event format strings are compiler-verified too). Sections F–I (added 2026-06-10) pin the hardened semantics: UART fuzz/overrun-discard, duplicate-RUN, the uint32 ms-wrap boot-settle latch, the chatter guard + TX headroom, and the hb `in`/`run` masks.

> ⚠️ **Bench-only gates (the host test CANNOT prove these):** watchdog timing (the 250 ms WDT vs real loop latency — the mock watchdog is a no-op), boot ordering (GP2 LOW before init), GPIO drive polarity/levels on real silicon, UART electricals/baud, and the DEBUG_USB stdio path. These are §12.9 bench bring-up items — a green host test is necessary, not sufficient.

## Flash

- **USB BOOTSEL (preferred):** hold BOOTSEL on the Pico while connecting USB → it mounts as `RPI-RP2` → drag-drop `wsl_phase8b_rp2040.uf2`.
- **SWD (fallback if USB isn't accessible once the module is soldered):** `picotool load -x build/wsl_phase8b_rp2040.uf2`, or OpenOCD via the board's SWD test points.

## UART protocol (115200 8N1, newline-delimited)

### RP2040 → Pi (events)
```
{"ev":"boot","fw":"phase8b-rp2040 v0.2.0","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000,"dbg":0}
{"ev":"cam","id":"SA","e":"f","t":12345}        # e: f=asserted(fall), r=released(rise)
{"ev":"ball","src":"L","t":12350}               # one event per ball (lockout-deduped)
{"ev":"rp_ok","v":1,"t":12360}                  # rail permission changed
{"ev":"flt","code":"motion_timeout","m":"S","t":20000}
{"ev":"flt","code":"chatter","m":"SA","t":20000}   # input over the per-window edge budget
{"ev":"hb","ok":1,"flt":"","up":12500,"drp":0,"in":0,"run":0}  # ~4 Hz; ok=rp_ok, drp=dropped TX lines
{"ev":"ack","cmd":"CLEAR","t":21000}
```

Boot fields (v0.2.0): `maxrun_ms` = the firmware's compile-time max-run backstop — **the Pi should refuse to arm if its `MAX_MOTION_S` exceeds it** (the two are independently-maintained constants); `dbg` = 1 marks a DEBUG_USB build so a debug image at the lane is visible.

Heartbeat masks (v0.2.0): `in` = debounced input levels, bit *i* = `inputs[i]` asserted (SA,SB,SC,TA1,TA2,TB,DIELL_L,DIELL_R = bits 0–7); `run` = motors marked running, bit *i* = `motors[i]` (S,T,SP,M2,M1,BE,M = bits 0–6). The Pi should **resync its SC/TB interlock echo from `in` on every hb** instead of trusting edge history (a single dropped `cam` line otherwise latches a danger flag forever), and treat an `up` regression as an RP2040 reboot.

UART robustness (v0.2.0): an RX line longer than 63 chars is discarded **whole** (tail swallowed to the next newline — garbled noise can never re-parse as `STOP`/`CLEAR`); a duplicate `RUN <m>` does **not** reset the max-run timer; cam/ball TX lines only enqueue while `TXR_HEADROOM` (128 B) stays free so a flood can't starve `hb`/`flt`; an input exceeding its per-100 ms debounced-edge budget (`CHATTER_MAX_CAM`=8, `CHATTER_MAX_DIELL`=30) latches a fail-safe `chatter` fault naming the input.

### Pi → RP2040 (commands)
```
RUN <m>      # mark motor running: m ∈ {S,T,SP,M2,M1,BE,M}  (BE/M not max-run-guarded)
STOP <m>     # mark motor stopped;  STOP *  = all
CLEAR        # clear a latched fault (Pi issues ONLY from a known-safe zero/ready state)
PING         # → immediate heartbeat
```

### Pi-side integration — implemented in `lane_node/rp2040_link.py`
`RP2040Link` + `dispatch_cam()` implement this contract (host test **29/29**, 2026-06-03), and `controller_io.MachineIO`/`RecordingIO` now accept `rp2040=link` for the SC/TB interlock echo + RUN/STOP (resolving the old `interlock_ok()` TODO). The per-board reader does all of:

- **Cam events → FSM** (the FSM's state self-selects which call fires, so call both variants):

  | cam event `id` | FSM call(s) |
  |---|---|
  | `SA` | `c.cam_SA_runthrough(); c.cam_SA_zero()` |
  | `SB` | `c.cam_SB_guard()` |
  | `TA1` | `c.cam_TA1_delayreset(); c.cam_TA1_zero()` |
  | `TA2` | `c.cam_TA2_runthrough()` |
  | `SC` / `TB` | update the interlock echo → feed `interlock_ok()` |
  | `ball` | `c.on_ball()` |

  Act on the **trip edge** (which of `f`/`r` is the angular trip is a bench-confirm item — cams are normally-closed and the opto inverts; default assumes `f` = trip).
- **Send RUN/STOP** alongside the relay commands — e.g. in `MachineIO._set_out`, when `S` toggles, also send `RUN S` / `STOP S`. Send `CLEAR` at `_finish_cycle`/READY.
- **Consume `hb`/`rp_ok`** — if heartbeats stop (>~1 s) or `ok:0`, call `io.arm(False)` to drop the rail; surface faults to the FSM/desk.
- **SC/TB echo** — track asserted state from cam events → replace the `interlock_ok()` TODO. **v0.2.0 TODO(pi-side):** resync the SC/TB flags from the hb `in` mask every heartbeat (self-healing vs dropped lines), verify `boot.maxrun_ms >= MAX_MOTION_S*1000` before arming, and treat an `up` regression as an RP2040 reboot (same safety-trip path as a `boot` event).

## Safety model — why RP_OK is fail-safe

- **Pre-init / unpowered / reset:** GP2 is Hi-Z → the board's 100k base-pulldown holds the NPN off → RAIL_GATE stays pulled up → PMOS off → **rail dead**. `main()` drives GP2 LOW first thing, then HIGH only after `BOOT_SETTLE_MS` and only while no fault.
- **Loop hang:** RP2040 hardware watchdog (`WDT_TIMEOUT_MS`) resets the chip → back to Hi-Z → rail dead → auto-recovers on reboot (a `boot` event with `wdt_reset:1` tells the Pi it happened).
- **Telemetry never blocks safety:** UART TX is a non-blocking ring buffer; if the Pi isn't draining, whole lines are dropped (counted in `hb.drp`) — the RP_OK drive and watchdog kick still run every loop pass.
- **Dead UART can't cause unsafe motion:** no `RUN` messages → nothing marked running → no false permit; and the Pi's own motion-timeout FAULT drops ARM. A UART death *mid-run* is caught by the RP2040 max-run timer.

## Bench bring-up (do this on a LOCKED-OUT / off machine — spec §12.9)

1. **Power + boot:** flash, power the board logic only (rail externally safe). Watch USB/UART: a `boot` line, then `hb` at ~4 Hz with `ok:1` after ~200 ms. Confirm GP2 reads HIGH (rail-permit) on a meter/test-pad once healthy.
2. **Inputs:** hand-actuate each cam / break each DIELL beam → confirm the matching `cam`/`ball` event (correct `id`). This also captures the per-cam edge polarity for the v1.1 hook + the cutover field sheet.
3. **Watchdog drop:** pause the loop (or pull power to just the Pico) → GP2 → LOW → rail drops. Confirm a `boot` with `wdt_reset:1` if you force a hang.
4. **Motion timeout:** send `RUN S`, wait >8 s without `STOP S` → expect `{"ev":"flt","code":"motion_timeout","m":"S"}` and GP2 → LOW. `CLEAR` → GP2 back HIGH.
5. **Then** integrate with the rail/relay section per spec §12.9 (each relay with a dummy load, arm drop, interlock drop) before any machine harness.

## Files
- `config.h` — pin map (authoritative, cites the netlist), timing, protocol tokens.
- `main.c` — inputs/debounce, UART protocol + TX ring, safety supervisor, main loop.
- `CMakeLists.txt`, `pico_sdk_import.cmake` — Pico SDK build.

## Status / next
- v1 written + **verified 2026-06-03**; **clean-room rebuild re-verified 2026-06-04** (full from-scratch ARM cross-build 88/88 + host test 24/24, both **0-warning** under `-Wall -Wextra`; `.uf2` = 40 KB, 24 KB flash / 2.6 KB RAM): host logic test 24/24 + clean ARM cross-build → `.uf2`; Pi-side reader/daemon done and Codex-audited (fixes applied).
- **v0.2.0 audit hardening 2026-06-10** (fable-audit P3 items): host test **55/55** + clean ARM cross-build re-verified (`.uf2` = 41.5 KB), both 0-warning. **NOT yet flashed/bench-run** — needs: re-flash, hb `in`/`run` masks observed on the wire, chatter fault provoked with a function generator or relay buzzer, and the Pi-side resync/maxrun-check TODOs in `rp2040_link.py` (see Pi-side integration above).
- ⚠️ **NOT cutover-ready.** "Done" = host-logic + build + happy-path only. The cutover runbook's **G3 cam-stop rail-drop gate** needs **v1.1 cam-stop overrun**, which is bench-gated on the per-cam edge→angle polarity (runbook §3.2). v1 provides health + the motion **max-run backstop**, NOT per-cam-edge enforcement. **Pending: v1.1 cam-stop + on-hardware bench bring-up (spec §12.9).**
- Next: build/flash, bench bring-up (above), then wire the Pi-side reader (contract above), then the v1.1 cam-stop overrun once cam polarity is bench-confirmed.
