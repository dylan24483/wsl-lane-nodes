# WSL Phase 8b — RP2040 lane-controller firmware

**v1.2.2 — DRAFT, bench-bring-up gated. Not for a live machine until validated per `docs/phase8b_pcb_revB_spec.md` §12.9. Full version history: `CHANGELOG.md`.**
*(v1.2.2, 2026-07-21 — Codex round-2 R2-1/R2-13/R2-6 — **NOT flashed**: pad-level OEOVER output lock + `STATUS.OETOPAD` readback on EVERY input-contract pin (the SIO-only check had an override bypass), epoch-aware rail-drop classifier (pre-reboot ring entries are history-only, never fresh diagnosis), the bench-only FI-1 fault-injection build (compile-flag + BOOTSEL-jumper + arm-command gated; separate artifact name; zero code in release), and the identity line: REV_ID strap read (GP20/GP21), Pico unique id, per-build `git describe` + config.h hash, hb `rid` field. All additive; `rp2040_link.py` consumes id/rid.)*
*(v1.2.0, 2026-07-21 — rev-D remediation R3, closes Codex C2 — **NOT yet flashed**: GP16-19 rev-D diagnostic taps get an ENFORCED input-only invariant (choke-point init + register readback each heartbeat + a host direction-invariant test that fails the build if any code path drives them), the INVERTED tap decode (2N7002 stage: raw 0 = observed HIGH, one `tap_read()` inversion point), a 1 ms-timestamped rail-drop edge ring in noinit RAM that survives reboot (magic + epoch; `TAPDUMP`/`TAPCLR`), and VCC_5V ADC sampling on GP26 folded into the heartbeat. **All additive**: v1.1 line formats + command grammar unchanged, all v1.1 enforcement flags still default OFF, safety-critical paths byte-for-byte logic-identical. Rev-D board only — on rev-B/rev-C these pins are unconnected (an IRQ storm guard keeps floating-pin noise harmless). Binding contract: `docs/phase8_revD_remediation_spec_2026-07-21.md` §R3.)*
*(v1.1.1, 2026-07-06 review fixes (findings 37/56/58): boot `v11` enforcement-posture field; cam-stop grace arms on FIRST trip only; sliding chatter window. v1.1.0, 2026-06-10: cam-stop OVERRUN / SC-TB echo / motion-without-RUN, all default OFF. v0.2.0, 2026-06-10: audit hardening. See CHANGELOG.md.)*

> ⛔ **BENCH-CONFIRM BEFORE ENABLING the v1.1 flags.** `config.h` ships every v1.1 enforcement flag OFF and every per-cam trip edge as `'?'` (UNCONFIRMED). Confirm the per-cam edge→angle polarity on the spare cabinet (`docs/phase8_trackB_controller_cutover_runbook.md` §3.2) FIRST, then set `CAM_*_TRIP` + flip the matching `*_ENABLED` cam-by-cam and re-flash. Enabling with wrong polarity nuisance-trips the rail (safe direction) or, for the SC/TB echo, fails to add its backstop. ⚠️ **The hardware J_SAFETY loop does NOT exist yet as designed** — the 2026-06-27 metering proved SC+TB is a series interlock at one node with no isolatable dry NC pair (design OPEN, `docs/phase8_interlock_redesign.md`); until a redesigned loop is landed, the software echo is the ONLY controller-side interlock guard. Never enable blind.

One RP2040 (a stock Raspberry Pi Pico module) sits on each rev-B controller board and is the **fast + safety half** of the lane controller. The Raspberry Pi runs the cycle FSM (`lane_node/cycle_control_8270.py`) and commands relays over I²C/MCP23017; this firmware owns the latency-critical inputs and the hardware rail-permission line.

> ⚠️ **Safety co-processor.** It drives `RP2040_OK` (GP2), a non-bypassable condition in the relay-enable-rail AND chain (spec §4.1). It is **never the only safety device** — the TB/SC collision interlock (J_SAFETY hardware loop), the Stop/CIS/master-breaker chain, the NE555 watchdog (which watches the *Pi*), and regenerative motor braking are all in hardware, independent of this firmware. Read the safety section before editing.

## What it does (v1)

1. **Reads 8 fast inputs** (6 cams + 2 DIELL ball beams), debounces, and **pushes edge events to the Pi over uart0** — the FSM consumes events, it does not poll, so cam timing isn't subject to Pi scheduling latency.
2. **Drives `RP2040_OK` (GP2)** = rail permission. **HIGH only when healthy; LOW on boot, fault, or hang.** Fail-safe by construction (see below).
3. **UART-independent safety backstops:**
   - **Firmware health** — the RP2040 hardware watchdog: if the main loop hangs, the chip resets → GP2 goes Hi-Z → the board's external 100k base-pulldown holds the rail **dead**.
   - **Motion max-run ("cam timeout", spec §4.2)** — if the Pi marks a guarded motor `RUN` and never `STOP`s it within `MAX_MOTION_MS` (8 s, matches the FSM), the firmware **latches a fault and drops RP_OK**.
4. **Heartbeats to the Pi** so a dead/`!ok` RP2040 is detected (the Pi then drops its ARM GPIO → rail drops).

### v1.1 SAFETY supervision (implemented, default OFF — arm per-cam after the §3.2 capture)

These are the cutover **G3 cam-stop rail-drop** backstops. The *code* is present + host-tested; the *enforcement* is gated OFF in `config.h` until the per-cam edge→angle polarity is bench-confirmed (`docs/phase8_trackB_controller_cutover_runbook.md` §3.2). Each only ever `latch_fault()`s (fail-safe: RP_OK → LOW).

1. **Cam-stop OVERRUN** — a stop cam's TRIP edge fires while its guarded motor is marked RUNNING and the Pi fails to `STOP` it within the per-cam grace window → latch `cam_overrun`. Per-cam: `CAM_SA_STOP_ENABLED`/`CAM_SA_TRIP`/`CAM_SA_GRACE_MS` (SA→sweep S), `CAM_TA1_*` (TA1→table T). **The Pi-independent, per-edge stop the post-cutover machine relies on** (runbook §0: cam-stops are SOLELY the RP2040's job once the Omniboard is unplugged).
2. **SC/TB collision-interlock echo** — both SC and TB asserted at once while a motion motor runs → latch `interlock_collision`. `INTERLOCK_ECHO_ENABLED`. The hardware J_SAFETY NC loop stays **primary**; this is a firmware backstop of it (the hb `in` mask already *reports* SC/TB regardless of the flag).
3. **Motion-without-RUN** — a stop-cam TRIP edge while NO motion motor is marked RUNNING = the machine turning uncommanded (Pi wedged / external start / welded relay) → latch `motion_no_run`. `MOTION_NO_RUN_ENABLED`. The one check that works even if the Pi is fully wedged.

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
| GP16 | 21 | tap: NE555 out (v1.2, **rev-D only**) | in (ENFORCED) | `TAP_NE555_OUT` | 2N7002 stage **INVERTS**: raw 0 = observed HIGH |
| GP17 | 22 | tap: watchdog kick (v1.2, rev-D) | in (ENFORCED) | `TAP_WDOG_KICK` | inverted |
| GP18 | 24 | tap: ARM permit (v1.2, rev-D) | in (ENFORCED) | `TAP_ARM_PERMIT` | inverted |
| GP19 | 25 | tap: RP2040_OK echo (v1.2, rev-D) | in (ENFORCED) | `TAP_RP2040_OK` | inverted; cross-checked vs our own GP2 |
| GP20 | 26 | REV_ID0 strap (v1.2.2, rev-D) | in (ENFORCED) | `REV_ID0` | 10k→3V3 on rev-D; read once at boot, pull-phase floating detect |
| GP21 | 27 | REV_ID1 strap (v1.2.2, rev-D) | in (ENFORCED) | `REV_ID1` | 10k→GND on rev-D; `REV_ID[1:0]=GP21<<1\|GP20`, rev-D=0b01 |
| GP26 | 31 | VCC_5V sense (v1.2, rev-D) | ADC0 | `ADC_VCC5_SENSE` | VCC_5V/2 via 10k/10k divider |

All fast inputs are **active-low** at the Pico (machine contact closed → GPIO LOW); on-board 10k pull-up to 3V3, internal pull-up also enabled. The v1.2 tap pins (rev-D netlist `generate_kicad_netlist_revD.py block_diag()`) are configured in exactly ONE place (`tap_init()`), input-only with pulls OFF (the board's 10k drain pull-up defines the level), and the direction is an ENFORCED invariant: `tap_assert_input_only()` reads back the OE/function registers every heartbeat and latches a fail-safe `tap_dir` fault on drift; the host test fails the build if any code path ever drives them. **v1.2.2 (R2-1):** the invariant additionally forces + verifies the pad-level `CTRL.OEOVER=DISABLE` override and the live `STATUS.OETOPAD` bit on EVERY input-contract pin (taps, GP26, fast inputs, REV_ID) — the SIO-only readback had an OEOVER bypass; drift latches `pad_oe`.

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

# (a) default build — v1.1 enforcement flags OFF (what ships); also pins the off-by-default inertness
gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs test/test_main.c -o test/test_main.exe
./test/test_main.exe        # exit 0 = all checks pass

# (b) v1.1 SAFETY paths — SAME firmware, enforcement flags forced ON with test polarities ('f')
gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs \
  -DCAM_SA_STOP_ENABLED=1 -DCAM_SA_TRIP="'f'" -DCAM_SA_GRACE_MS=150u \
  -DCAM_TA1_STOP_ENABLED=1 -DCAM_TA1_TRIP="'f'" -DCAM_TA1_GRACE_MS=150u \
  -DINTERLOCK_ECHO_ENABLED=1 -DMOTION_NO_RUN_ENABLED=1 \
  test/test_v11.c -o test/test_v11.exe
./test/test_v11.exe         # exit 0 = all checks pass

# (c) v1.2 tap/ring/ADC + THE C2 DIRECTION-INVARIANT GATE (rev-D remediation)
#     v1.2.2 adds: R2-1 OEOVER mutation gate, R2-13 epoch classifier, R2-6 REV_ID/identity
gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs test/test_v12.c -o test/test_v12.exe
./test/test_v12.exe         # exit 0 = all checks pass

# (d) FI-1 bench build gates (v1.2.2): jumper refusal, arm-gate, drive/release, banner identity
gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs -DFI1_ENABLED=1 \
  test/test_fi1.c -o test/test_fi1.exe
./test/test_fi1.exe         # exit 0 = all checks pass
```

Last run: **64/64** (`test_main`) + **32/32** (`test_v11`) + **111/111** (`test_v12`) + **28/28** (`test_fi1`) checks passed (2026-07-21, gcc 16.1.0), all clean under `-Wall -Wextra -Werror` + the `printf`-format attribute (so the event format strings are compiler-verified too). The binaries share `test/mock_impl.h` (one mock-SDK implementation) so they can never drift. Sections F–I of `test_main` pin the v0.2.0 hardened semantics (UART fuzz/overrun-discard, duplicate-RUN, uint32 ms-wrap boot-settle latch, chatter guard + TX headroom, hb `in`/`run` masks); Section J pins that the v1.1 checks are **inert when the flags are OFF** (a default build = v0.2.0 enforcement); `test_v11.c` pins that each v1.1 fault path fires fail-safe when enabled (overrun latch + timely-STOP-cancels + per-motor disarm, SC∧TB echo, motion-without-RUN, and the non-trip-edge-is-inert guard). `test_v12.c` is the **C2 gate**: the mock SDK records every output-direction/write call per pin and the test FAILS if GP16-19/GP26 ever appear in one across init + operation + every fault path; it also tampers the mock OE register to prove `tap_assert_input_only()` trips, and covers the inverted decode, ring capture/wrap, reboot-persistence + epoch semantics, power-loss zeroing, TAPDUMP/TAPCLR + cause classification, ADC window, IRQ storm guard, and the RPOK cross-check (warn-only by default).

> ⚠️ **Bench-only gates (the host test CANNOT prove these):** watchdog timing (the 250 ms WDT vs real loop latency — the mock watchdog is a no-op), boot ordering (GP2 LOW before init), GPIO drive polarity/levels on real silicon, UART electricals/baud, and the DEBUG_USB stdio path. These are §12.9 bench bring-up items — a green host test is necessary, not sufficient.

## Flash

- **USB BOOTSEL (preferred):** hold BOOTSEL on the Pico while connecting USB → it mounts as `RPI-RP2` → drag-drop `wsl_phase8b_rp2040.uf2`.
- **SWD (fallback if USB isn't accessible once the module is soldered):** `picotool load -x build/wsl_phase8b_rp2040.uf2`, or OpenOCD via the board's SWD test points.

## UART protocol (115200 8N1, newline-delimited)

### RP2040 → Pi (events)
```
{"ev":"boot","fw":"phase8b-rp2040 v1.2.0","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000,"dbg":0,"v11":{"sa":"off","ta1":"off","echo":0,"nrun":0},"tap":{"ep":1,"pre":0,"n":0}}
{"ev":"cam","id":"SA","e":"f","t":12345}        # e: f=asserted(fall), r=released(rise)
{"ev":"ball","src":"L","t":12350}               # one event per ball (lockout-deduped)
{"ev":"rp_ok","v":1,"t":12360}                  # rail permission changed
{"ev":"flt","code":"motion_timeout","m":"S","t":20000}
{"ev":"flt","code":"chatter","m":"SA","t":20000}   # input over the per-window edge budget
{"ev":"flt","code":"cam_overrun","m":"SA","t":20000}          # v1.1, when enabled: stop cam tripped, motor not STOPped in grace
{"ev":"flt","code":"interlock_collision","m":"SCTB","t":20000} # v1.1, when enabled: SC+TB both asserted while a motor runs
{"ev":"flt","code":"motion_no_run","m":"SA","t":20000}        # v1.1, when enabled: stop-cam trip with no motor commanded
{"ev":"flt","code":"tap_dir","m":"KICK","t":20000}            # v1.2: tap pin OE/function register drift (enforced invariant)
{"ev":"flt","code":"pad_oe","m":"555","t":20000}              # v1.2.2: CTRL.OEOVER/STATUS.OETOPAD drift on an input-contract pin
{"ev":"hb","ok":1,"flt":"","up":12500,"drp":0,"in":0,"run":0,"tap":0,"rd":0,"ep":1,"v5":4810,"v5n":4650,"v5x":4885,"rid":1}
{"ev":"id","fw":"phase8b-rp2040 v1.2.2","pcb":"revD","rid":1,"uid":"E66038B713952A31","build":"10c3a26-dirty","cfg":"aa4ff333","fi1":0,"t":300}  # v1.2.2 identity (after boot + on ID)
{"ev":"ack","cmd":"CLEAR","t":21000}
{"ev":"tapdump","n":17,"ep":2,"br":2,"mut":0,"cause":"kick_starvation","t":30000}  # v1.2: TAPDUMP header
{"ev":"tape","i":0,"t":29450,"p":1,"l":0,"ep":1}   # v1.2: one ring entry (p: 0=555,1=KICK,2=ARM,3=RPOK; l=post-inversion level AFTER the edge)
{"ev":"tapdump_end","n":17}                        # v1.2: dump complete
{"ev":"tapwarn","code":"rpok_mism","t":30500}      # v1.2: GP19 tap disagrees with our GP2 drive (warn-only by default)
```

v1.1 fault codes (`cam_overrun`/`interlock_collision`/`motion_no_run`) appear ONLY on a build with the matching `config.h` flag enabled; a stock (default) firmware never emits them. They are ordinary `flt` events — the Pi side already treats any `flt` as not-healthy (`rp2040_link._handle`), so **no Pi-side change is required to react to them**. A `CLEAR` (issued from a known-safe state) clears them like any other latched fault.

Boot fields (v0.2.0): `maxrun_ms` = the firmware's compile-time max-run backstop — **the Pi should refuse to arm if its `MAX_MOTION_S` exceeds it** (the two are independently-maintained constants); `dbg` = 1 marks a DEBUG_USB build so a debug image at the lane is visible.

Boot fields (v1.1.1): `v11` = the v1.1 enforcement posture, because `fw` is the SAME string for an armed and a stock build (review finding 37). `sa`/`ta1` = `"off"` (per-cam enable 0) or the configured trip edge (`"f"`/`"r"`, `"?"` = enabled-but-unconfirmed, which can never trip); `echo`/`nrun` = `INTERLOCK_ECHO_ENABLED`/`MOTION_NO_RUN_ENABLED`. `rp2040_link` logs the posture at every boot (WARNING when armed) and exposes it via `v11_posture()` — **verify the expected posture at cutover before crediting the G3 cam-stop backstop.** Additive field: older Pi-side parsers ignore it.

Heartbeat masks (v0.2.0): `in` = debounced input levels, bit *i* = `inputs[i]` asserted (SA,SB,SC,TA1,TA2,TB,DIELL_L,DIELL_R = bits 0–7); `run` = motors marked running, bit *i* = `motors[i]` (S,T,SP,M2,M1,BE,M = bits 0–6). The Pi should **resync its SC/TB interlock echo from `in` on every hb** instead of trusting edge history (a single dropped `cam` line otherwise latches a danger flag forever), and treat an `up` regression as an RP2040 reboot.

UART robustness (v0.2.0): an RX line longer than 63 chars is discarded **whole** (tail swallowed to the next newline — garbled noise can never re-parse as `STOP`/`CLEAR`); a duplicate `RUN <m>` does **not** reset the max-run timer; cam/ball TX lines only enqueue while `TXR_HEADROOM` (128 B) stays free so a flood can't starve `hb`/`flt`; an input exceeding its debounced-edge budget (`CHATTER_MAX_CAM`=8, `CHATTER_MAX_DIELL`=30) inside **any** 100 ms span latches a fail-safe `chatter` fault naming the input (v1.1.1: true sliding window — the old tumbling window needed up to 2× the budget for a burst straddling a window boundary, review finding 58).

Run-state reconciliation (v1.1.1, Pi-side): `RUN`/`STOP` still have no ACK/CRC, but `rp2040_link` now compares the hb `run` mask against the state it last commanded every heartbeat and re-sends the command on mismatch (bounded, 3/episode; safe because duplicate `RUN` doesn't reset the timer). A desync from one corrupted line therefore heals within ~250 ms instead of guaranteeing a spurious `motion_timeout` rail-drop (lost `STOP`) or a silently absent max-run backstop (lost `RUN`) — review finding 38. A persisting mismatch stays visible via `run_mismatch()`.

### Pi → RP2040 (commands)
```
RUN <m>      # mark motor running: m ∈ {S,T,SP,M2,M1,BE,M}  (BE/M not max-run-guarded)
STOP <m>     # mark motor stopped;  STOP *  = all
CLEAR        # clear a latched fault (Pi issues ONLY from a known-safe zero/ready state)
PING         # → immediate heartbeat
TAPDUMP      # v1.2: emit the tapdump header + drip the full edge ring (tape lines) + end marker
TAPCLR       # v1.2: empty the edge ring (the ONLY thing that does — reboot never clears it) → ack
ID           # v1.2.2: re-emit the identity line
# FI1 ARM / FI1 DRIVE <0-3> / FI1 RELEASE — BENCH-ONLY FI-1 build (-DFI1_BUILD=ON): the grammar
# does not exist in a release image; the FI-1 image refuses to run without its BOOTSEL jumper.
```

v1.2 tap fields: hb `tap` = post-inversion observed-net levels (bit 0..3 = 555, KICK, ARM, RPOK), `rd` = ring depth, `ep` = ring epoch, `v5`/`v5n`/`v5x` = VCC_5V latest/min/max mV over the hb window. Boot `tap.ep` = epoch, `tap.pre` = 1 if a valid pre-reboot ring was ADOPTED (0 = zeroed: power loss/first boot), `tap.n` = preserved entries. `tapdump.br` = boot reason (0 cold, 1 soft reboot, 2 watchdog), `mut` = storm-guard-muted tap mask, `cause` = ADVISORY drop classification (`kick_starvation` / `arm_drop` / `self_health` / `555_drop` / `none`) — the Pi always gets the raw ring + per-entry epochs to judge for itself. All fields additive; `rp2040_link.py` verified to ignore them and the new event kinds cleanly (no Pi-side change required).

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
5. **v1.1 cam-stop arming (per cam, AFTER step 2 captured polarity):** for each stop cam, set `CAM_<cam>_TRIP` to the confirmed trip edge + `CAM_<cam>_STOP_ENABLED=1` in `config.h`, rebuild + re-flash, then the **G3 cam-stop sub-test:** send `RUN S`, hand-rotate so SA trips, do NOT send `STOP S` → within `CAM_SA_GRACE_MS` expect `{"ev":"flt","code":"cam_overrun","m":"SA"}` + GP2 → LOW (repeat for `TA1`/`T`). Then re-run step 4-style with a *timely* `STOP S` inside the grace window and confirm NO fault (the normal stop). Optionally enable `INTERLOCK_ECHO_ENABLED` once the SC/TB windows are confirmed (`SC`+`TB` asserted while a motor runs → `interlock_collision`) and `MOTION_NO_RUN_ENABLED` (trip a stop cam with nothing commanded → `motion_no_run`). **Do not enable any v1.1 flag before its polarity is confirmed in step 2.**
6. **Then** integrate with the rail/relay section per spec §12.9 (each relay with a dummy load, arm drop, interlock drop) before any machine harness.

## Files
- `config.h` — pin map (authoritative, cites the netlist), timing, protocol tokens, **v1.1 per-cam stop descriptors + enforcement flags (all default OFF/UNCONFIRMED)**, **v1.2 tap/ring/ADC constants** (binding contract: remediation spec §R3), **v1.2.2 REV_ID straps + FI1 gate + identity fallbacks**.
- `main.c` — inputs/debounce, UART protocol + TX ring, safety supervisor (incl. the v1.1 cam-stop / SC-TB-echo / motion-without-RUN paths), **v1.2 tap section** (choke-point init, enforced direction invariant, edge ring + persistence, TAPDUMP/TAPCLR, ADC, storm guard), **v1.2.2** pad-OE lock (R2-1), epoch-aware classifier (R2-13), REV_ID/identity (R2-6), FI-1 hooks, main loop.
- `fi1_bootsel.c` — FI-1 bench build ONLY: BOOTSEL physical-jumper gate (never linked into release).
- `gen_build_id.cmake` — build-time generator for `build_id.h` (git describe + config.h sha256).
- `CHANGELOG.md` — full version history (v0.1.0 → v1.2.2) with per-version flash status.
- `test/mock_pico.h` / `test/mock_impl.h` — host-test mock SDK surface (declarations / one shared implementation; v1.2 adds per-pin direction/write recording + IRQ/ADC/sync mocks; v1.2.2 adds the IO_BANK0 OEOVER/OETOPAD register file with real-SDK whole-CTRL-rewrite semantics, pulls/floating, unique-id).
- `test/test_main.c` — default host test (flags OFF) + Section J off-by-default inertness.
- `test/test_v11.c` — v1.1 host test (flags forced ON via `-D`): each new fault path fires fail-safe.
- `test/test_v12.c` — **v1.2 host test = the C2 direction-invariant gate** + tap decode/ring/persistence/dump/ADC/storm-guard/cross-check coverage; **v1.2.2 sections M-Q**: the R2-1 OEOVER mutation gate, R2-13 stale-edge exclusion, REV_ID/identity, FI-1-absent-in-release.
- `test/test_fi1.c` — **FI-1 bench-build host test** (`-DFI1_ENABLED=1`): jumper refusal permanence, arm-gate, drive/release restore, banner identity.
- `CMakeLists.txt`, `pico_sdk_import.cmake` — Pico SDK build (v1.2 links `hardware_adc`; v1.2.2 links `pico_unique_id`, generates `build_id.h` every build, and offers `-DFI1_BUILD=ON` → separately-named bench artifact).

## Status / next
- v1 written + **verified 2026-06-03**; **clean-room rebuild re-verified 2026-06-04** (full from-scratch ARM cross-build 88/88 + host test 24/24, both **0-warning** under `-Wall -Wextra`; `.uf2` = 40 KB, 24 KB flash / 2.6 KB RAM): host logic test 24/24 + clean ARM cross-build → `.uf2`; Pi-side reader/daemon done and Codex-audited (fixes applied).
- **v0.2.0 audit hardening 2026-06-10** (fable-audit P3 items): host test **55/55** + clean ARM cross-build re-verified (`.uf2` = 41.5 KB), both 0-warning. **NOT yet flashed/bench-run** — needs: re-flash, hb `in`/`run` masks observed on the wire, chatter fault provoked with a function generator or relay buzzer, and the Pi-side resync/maxrun-check TODOs in `rp2040_link.py` (see Pi-side integration above).
- **v1.1.0 SAFETY supervision written 2026-06-10** (fable-audit novel idea #13): cam-stop OVERRUN + SC/TB collision echo + motion-without-RUN, all default OFF behind per-cam config flags. Host tests **61/61** (`test_main`, incl. off-by-default inertness) + **28/28** (`test_v11`, flags forced on), both 0-warning under `-Wall -Wextra -Werror`; clean ARM cross-build re-verified (`.uf2` = 43.5 KB). **NOT yet flashed/bench-run; all v1.1 flags ship OFF** — so on-the-wire behavior is still exactly v0.2.0 until a board is armed cam-by-cam.
- **v1.1.1 review fixes 2026-07-06** (phase8 fable review findings 37/56/58 + Pi-side 38): boot `v11` posture field, arm-once cam-stop grace, sliding chatter window; `rp2040_link.py` gains hb `run`-mask reconciliation (bounded re-sends + `run_mismatch()`) and `v11_posture()`. Host tests **64/64** (`test_main`) + **32/32** (`test_v11`), Pi-side self-tests green. **NOT yet flashed — owner review + re-flash pending; all v1.1 flags still ship OFF.**
- **v1.2.0 rev-D tap telemetry 2026-07-21** (remediation spec R3 — closes Codex C2): enforced input-only invariant on GP16-19 (choke-point init + register readback + host direction-invariant test), inverted tap decode, noinit rail-drop edge ring with reboot persistence + `TAPDUMP`/`TAPCLR`, VCC_5V ADC in the heartbeat. Host tests **64/64 + 32/32 + 71/71** (new `test_v12`), all `-Werror`-clean; ARM cross-build verified (`.uf2` = 56 KB, 32.7 KB flash / 5.4 KB RAM; `.map` confirms `tap_ring` in `.uninitialized_data`, outside crt0 zero-fill). `rp2040_link.py` verified compatible unmodified (38/38 + v1.2-line feed check). **NOT yet flashed.** Bench gates: real-silicon reboot persistence, ADC-vs-DMM, `TAP_KICK_STARVE_MS` vs measured NE555 window (v1.2.1: 2000 ms, derived from the real 1 Hz Pi kick cadence — v1.2.0's 300 ms was sized against a nonexistent "~250 ms kick" and misclassified live-train 555 drops), and the R1.9 fault-injection procedure.
- **v1.2.2 Codex round-2 slice 2026-07-21** (R2-1 + R2-13 + R2-6): pad-level OEOVER lock + `OETOPAD` readback on every input-contract pin (the R2-1 override bypass — with the mandated OEOVER *mutation* test), epoch-aware rail-drop classifier (pre-reboot edges history-only), the FI-1 bench fault-injection build (compile-flag + BOOTSEL-jumper + arm-gated; **separate artifact name `wsl_phase8b_rp2040_FI1.uf2`; zero FI-1 code in release** — the R1.9 target that was previously "not yet written"), and the identity line (REV_ID strap read GP20/21 with floating detection, Pico unique id, per-build `git describe` + config.h sha via `build_id.h`, hb `rid`). Host tests **64/64 + 32/32 + 111/111 + 28/28** (`test_fi1` new), `-Werror`-clean; ARM cross-builds verified: release `.uf2` = 60.5 KB (real build identity embedded, `tap_ring` still noinit) + FI-1 bench 63 KB. Pi-side `rp2040_link.py` consumes `id`/`rid` (self-test 45/45; `tests/test_fw_identity_line.py`). **NOT flashed.** New bench gates: BOOTSEL-read on silicon, REV_ID strap levels, FA-7 OEOVER/pad behavior on real pads.
- ⚠️ **NOT cutover-ready.** "Done" = host-logic + build only. The cutover runbook's **G3 cam-stop rail-drop gate** now has its firmware *logic*, but the **enforcement is gated OFF** pending the per-cam edge→angle polarity field capture (runbook §3.2). A stock build still provides only health + the motion **max-run backstop**.
- Next: build/flash, bench bring-up steps 1–4 (above), wire the Pi-side reader (contract above), then **bench step 5**: capture cam polarity (§3.2), set `CAM_*_TRIP` + flip `*_ENABLED` cam-by-cam, re-flash, and run the G3 cam-stop drop sub-test per cam.
