## 15. RP2040 Firmware (Safety Co-processor)

This section documents the firmware that runs on the **RP2040** (a stock Raspberry
Pi Pico module) soldered to each rev-B lane-controller board. The RP2040 is the
**fast + safety half** of the controller: it reads the latency-critical machine
inputs, pushes timestamped edge events to the Raspberry Pi over a UART, and drives
the hardware rail-permission line `RP2040_OK`. The Raspberry Pi runs the cycle
state machine (`lane_node/cycle_control_8270.py`) and commands relays over
I²C/MCP23017; it does **not** read the cams directly, so cam timing is never subject
to Pi scheduling latency.

Everything in this section is **per board / per lane** — a lane pair has two
identical boards, each with its own RP2040, on one shared Raspberry Pi.

Firmware version documented here: **`phase8b-rp2040 v1.2.3`** (the `FW_VERSION`
string in `config.h`). A controlled Rev-D-only release bundle exists, but it has
**not been flashed or validated on a live machine** and is **not cutover-ready**.
Every measured-cam enforcement flag remains **OFF** in the released configuration;
polarity capture, a newly qualified release, and first-article/bench gates remain
mandatory (see §15.9–§15.10).

> **Read the safety model (§15.6) before editing this firmware.** The RP2040 drives
> a non-bypassable condition in the relay-enable rail. Getting its fail-safe
> behavior wrong can leave a machine able to move when it should be dead. The board
> is **never the only safety device** — but it is one of the required ones.

Source files (paths relative to the repo root `wsl-lane-nodes/`):

| File | Contents |
|---|---|
| `firmware/rp2040/main.c` | Inputs/debounce, UART protocol + non-blocking TX ring, safety supervisor, `main()` loop. |
| `firmware/rp2040/config.h` | Pin map (cites the netlist), timing constants, protocol tokens. |
| `firmware/rp2040/README.md` | Build/flash/test instructions, the same protocol + pin tables. |
| `firmware/rp2040/CMakeLists.txt`, `pico_sdk_import.cmake` | Pico SDK build glue. |
| `lane_node/rp2040_link.py` | The **Pi-side** half of the link (parser, FSM bridge, RUN/STOP sender). |

Cross-references: the hardware around this chip — the relay-enable rail, the NE555
watchdog, the opto front-ends, the MCP23017 banks — is described in the
**PCB / Hardware** and **Opto-Input** and **Relay-Output** sections of this manual
(in this manual tree: `08_opto-inputs.md`, `09_relay-outputs.md`,
`13_layout-mfg.md`). The overall signal chain and the two-track (scoring vs control)
split are in **Section 2 (System Architecture & Signal Chain)**. The cycle FSM that
consumes this firmware's events is in **Section 16 (Firmware & Control FSM)**.
*(VERIFY: the exact printed section numbers for the PCB-hardware, opto, relay, and
camera sections — this manual tree uses non-contiguous file prefixes (02, 08, 09,
13, 15) and the final numbering may differ.)*

---

### 15.1 Role & Responsibilities

The RP2040 firmware has exactly four jobs. Three of them keep running even if the
UART to the Pi is dead.

1. **Read the 8 board fast-input positions, debounce them, and push edge events to
   the Pi over `uart0`.** The PCB positions are SA, SB, SC, TA1, TA2, TB and two
   DIELL beams. Field observability is harness-specific: lane 21/22 has **no
   independent TB lead**, and SC/U is not a dry-input landing. The FSM consumes
   events from landed, measured channels; it does not poll.

2. **Drive `RP2040_OK` (GP2) = rail permission.** This GPIO is one series condition
   in the relay-enable-rail AND chain on the board (see the Relay-Output section and
   the Safety-Rail contract, `docs/phase8b_pcb_revB_spec.md` §4.1/§4.2). It is
   **HIGH only when the firmware is healthy**, and **LOW on boot, on a latched
   fault, or on a loop hang.** It is fail-safe by construction (§15.6).

3. **Run UART-independent safety backstops:**
   - **Firmware-health backstop** — the RP2040's on-chip hardware watchdog. If the
     main loop ever hangs, the chip resets, GP2 goes Hi-Z, and the board's external
     100 kΩ base-pulldown holds the rail **dead**.
   - **Motion max-run backstop** ("cam timeout") — if the Pi marks a guarded motor
     `RUN` over UART and never `STOP`s it within `MAX_MOTION_MS` (8 s), the firmware
     **latches a fault and drops `RP2040_OK`**.

4. **Heartbeat to the Pi** (~4 Hz) so a dead or unhealthy RP2040 is detected. When
   the Pi sees heartbeats stop or `ok:0`, it drops its own ARM GPIO, which is a
   *separate* series condition in the same rail.

What the RP2040 firmware is **not**:

- It is **not** the only safety device. The TB/SC collision interlock (the
  powered-proven OEM parallel-safe contacts in the S/T coil ladder), the Stop / CIS / master-breaker chain, the NE555
  watchdog (which watches the **Pi**, not the RP2040), and the machine's
  regenerative motor braking are **all in hardware, independent of this firmware.**
- It does **not** switch any motor or coil current. It only drives a 3.3 V logic
  permission line; the relays and the machine contactors do the switching.
- The v1.2.3 code contains per-cam-edge enforcement paths, but the controlled
  release keeps **all measured-cam flags OFF**. No cam-stop path may be credited
  until its polarity is measured, enabled in a new controlled release, and proven
  at the applicable bench/cutover gate (§15.9).

---

### 15.2 Pinout (Authoritative)

**Source of truth:** `scripts/generate_kicad_netlist_revD.py` → `block_rp2040()` and
its `FAST_INPUTS` table (the live board netlist generator). `config.h` cites this
and matches it. The Pico physical-pin numbers in the generator map to the GPIO
numbers used in `config.h` exactly as below.

> ⚠️ **Do NOT use the GPIO column in `docs/phase8_channel_allocation.md` §2.** That
> draft is **STALE** — it put the fast inputs on GP0–GP7, which is wrong for the
> as-built board. The real board uses **GP6–GP13** for the fast inputs. The netlist
> generator and `config.h` are correct; the channel-allocation doc predates the
> as-built board.

| GPIO | Pico pin | `config.h` macro | Signal | Dir | Net (netlist) | Notes |
|---|---|---|---|---|---|---|
| GP0 | 1 | `PIN_UART_TX` | UART0 TX → Pi RX | out | `PI_UART_RX` | protocol transport (not stdio) |
| GP1 | 2 | `PIN_UART_RX` | UART0 RX ← Pi TX | in | `PI_UART_TX` | protocol transport (not stdio) |
| GP2 | 4 | `PIN_RP_OK` | `RP2040_OK` rail permit | out | `RP2040_OK` | **HIGH = permit, LOW = drop rail; fail-safe-low** |
| GP6 | 9 | `PIN_SA` | SA — sweep cam | in | `FAST_SA` | active-low opto; 270° run-through / 360° zero |
| GP7 | 10 | `PIN_SB` | SB — sweep cam | in | `FAST_SB` | 66° guard / 186° table-spot init |
| GP8 | 11 | `PIN_SC` | SC — sweep-under-table interlock board position | in | `FAST_SC` | lane 21/22 SC/U is cut/labeled/unlanded; not a dry echo input |
| GP9 | 12 | `PIN_TA1` | TA1 — table cam | in | `FAST_TA1` | 355° zero stop / 185° delay reset |
| GP10 | 14 | `PIN_TA2` | TA2 — table cam | in | `FAST_TA2` | 260° run-through / pin-latch / ball-strike decision |
| GP11 | 15 | `PIN_TB` | TB — table-sweep interference interlock board position | in | `FAST_TB` | **no independent field lead on lanes 21/22** |
| GP12 | 16 | `PIN_DIELL_L` | DIELL-L — ball detect, left beam | in | `FAST_DIELL_L` | active-low opto; cushion-SS trigger |
| GP13 | 17 | `PIN_DIELL_R` | DIELL-R — ball detect, right beam | in | `FAST_DIELL_R` | active-low opto |

**Electrical sense of the fast inputs.** Every fast input is **opto-isolated** (a
**PC817B** optocoupler per channel — LCSC **C5692981**; see the Opto-Input section)
and is **active-low at the Pico**: the machine contact closing (signal asserted)
pulls the GPIO **LOW**; idle is **HIGH**. Rev-D has an on-board **47 kΩ pull-up
to 3V3** on each fast-input line. Firmware explicitly disables the RP2040
internal pulls: their ~50–80 kΩ tolerance in parallel would reduce the effective
resistance and invalidate the qualified optocoupler-current margin. A missing
external pull-up is a board fault, not a condition firmware masks.

**Electrical sense of `RP2040_OK`.** GP2 drives an NPN (`Q_AND_RP_OK`, an MMBT3904)
that is one transistor in the relay-enable-rail series AND chain. A **100 kΩ base
pulldown** (`Rpd_AND_RP_OK`) means the rail fails **dead** whenever GP2 is Hi-Z —
i.e. whenever the RP2040 is unpowered, in reset, or pre-`main()`. The other AND
condition in the same chain is `ARM_PERMIT` (the Pi's arm GPIO, via `Q_AND_ARM`),
and upstream of both are the NE555 watchdog OK and the implemented `J_SAFETY` source path
(Candidate-C controlled jumper on pins 1–2 plus the Stop/CIS pins-3/4 loop).
This is the hardware that makes "GP2 LOW ⇒ no motion" true regardless of software.

> **Do not apply one blanket "normally-closed" or trip polarity to every cam.**
> The opto path is active-low at the Pico, but each landed motion-cam contact and
> edge→angle relationship must be measured. SC/TB is a separate case: powered
> testing proved the OEM ladder contacts are parallel closed-when-safe and both
> levers BACK/open kill S/T, while lane 21/22 has no independent TB lead for the
> firmware echo. The firmware reports edges but the released enforcement flags
> remain OFF until measured polarities are qualified.

---

### 15.3 Input Debounce & Edge Detection

The firmware does **time-based** (not counter-based) debounce. Each input has a
candidate state and a "stable since" timestamp; a raw change restarts the timer, and
the edge is only emitted once the new level has held for the channel's debounce
window. This is done in `scan_inputs()` once per main-loop pass.

The input table is `inputs[]` in `main.c`. The two DIELL channels are flagged
`is_ball = true`, which routes their assert edges through the **ball coalescing**
logic instead of emitting a raw `cam` event.

| Constant (`config.h`) | Value | Applies to | Why |
|---|---|---|---|
| `DEBOUNCE_CAM_US` | `2000` µs (2 ms) | SA, SB, SC, TA1, TA2, TB | Cams are mechanical microswitches; at ~12 RPM machine speed, 2 ms is ample de-glitch without masking a real edge. |
| `DEBOUNCE_DIELL_US` | `500` µs | DIELL-L, DIELL-R | Ball beam-break is faster than a cam edge, so a shorter window — but still de-glitched. |
| `BALL_LOCKOUT_MS` | `300` ms | DIELL-L + DIELL-R (combined) | One thrown ball → exactly **one** `ball` event. After a ball fires, both beams are locked out for 300 ms so a single ball passing two beams (or a bouncing beam) is not double-counted. |

**Cam edge events.** A debounced change on a cam input emits one `cam` event with
`e:"f"` (asserted / falling, contact closed) or `e:"r"` (released / rising, contact
open). The firmware makes no judgment about which edge is the angular trip — see the
polarity note in §15.2.

**Ball events.** A debounced *assert* (beam broken) on either DIELL channel emits a
single `ball` event with `src:"L"` or `src:"R"` — **unless** the global ball lockout
(`BALL_LOCKOUT_MS`) is still active from a previous ball, in which case it is
suppressed. The `src` character comes from `in->id[6]` (the 7th character of
`"DIELL_L"` / `"DIELL_R"`).

> The lockout is **global across both beams** (a single `last_ball_ms` timestamp),
> not per-beam. That is intentional: one physical ball can break both beams within a
> few ms, and the FSM wants one ball event, not two.

---

### 15.4 UART Line Protocol

**Transport:** `uart0`, **115200 baud, 8N1**, no flow control, newline-delimited
(`\n`). Each line is a complete message. RP2040→Pi event lines are JSON objects;
Pi→RP2040 command lines are short plain-text tokens.

The Pi side of this protocol is implemented in `lane_node/rp2040_link.py`
(`RP2040Link`); the line below labeled "Pi-side handling" describes what that module
does with each line.

#### 15.4.1 RP2040 → Pi (events)

All event lines are emitted via `emit()`, which formats into a 160-byte buffer and
pushes the whole line into a **non-blocking TX ring** (§15.5). The `"t"` field is
milliseconds since boot (`now_ms()`), which wraps at ~49.7 days.

| `ev` | Emitted when | Fields | Example | Pi-side handling |
|---|---|---|---|---|
| `boot` | Once, at startup, before the watchdog is armed | includes `fw` (firmware version), reset/permission state, enforcement posture, and release identity fields defined by the current firmware README | `{"ev":"boot","fw":"phase8b-rp2040 v1.2.3",...}` | Counts as a sign of life; require the manifest-bound Rev-D release identity before arming. |
| `cam` | Debounced cam edge | `id` (SA/SB/SC/TA1/TA2/TB), `e` (`f`=asserted/fall, `r`=released/rise), `t` | `{"ev":"cam","id":"SA","e":"f","t":12345}` | SA/SB/TA1/TA2 may be queued for the FSM after measured configuration. Code can update SC/TB echo state, but the lane-21/22 harness has no independent TB input and the echo is default-off/unvalidated. |
| `ball` | One thrown ball (lockout-deduped) | `src` (`L`/`R`), `t` | `{"ev":"ball","src":"L","t":12350}` | Queued; later applied as `controller.on_ball()`. |
| `rp_ok` | `RP2040_OK` level changed | `v` (1/0), `t` | `{"ev":"rp_ok","v":1,"t":12360}` | Updates the Pi's view of rail permission. |
| `flt` | A fault is latched | `code` (e.g. `motion_timeout`), `m` (motor name, may be `""`), `t` | `{"ev":"flt","code":"motion_timeout","m":"S","t":20000}` | Marks the RP2040 **not healthy immediately**, even if the paired `rp_ok:0` is delayed/dropped. |
| `hb` | Every `HB_INTERVAL_MS` (250 ms, ~4 Hz) and on `PING` | `ok` (= `rp_ok` state), `flt` (latched fault code or `""`), `up` (ms since boot), `drp` (count of dropped TX lines) | `{"ev":"hb","ok":1,"flt":"","up":12500,"drp":0}` | Liveness + health + dropped-telemetry counter. `flt:""` clears a previously-seen fault. |
| `ack` | `CLEAR` command accepted | `cmd` (`CLEAR`), `t` | `{"ev":"ack","cmd":"CLEAR","t":21000}` | Confirms the fault-clear round-trip. |

#### 15.4.2 Pi → RP2040 (commands)

Parsed in `handle_line()` in `main.c`. Lines are accumulated in a 64-byte buffer in
`poll_uart()`; an over-length line is dropped. **Unknown commands are silently
ignored** (forward-compatible).

| Command | Meaning | Argument | Behavior |
|---|---|---|---|
| `RUN <m>` | Mark a motor as **running** (starts its max-run timer) | `m` ∈ {`S`,`T`,`SP`,`M2`,`M1`,`BE`,`M`} | Sets `running=true` and `t_start_ms=now`. Only **guarded** motors (S, T, SP, M2, M1) are subject to the max-run timeout; `BE` and `M` are not. |
| `STOP <m>` | Mark a motor as **stopped** | a single motor name, **or** `*` | `STOP *` clears **all** motors (`motors_all_stop()`); `STOP <m>` clears one. |
| `CLEAR` | Clear a latched fault | none | Clears all motor-running flags, clears `fault_latched`/`fault_code`, and emits an `ack`. The Pi issues this **only from a known-safe (zero/ready) state.** |
| `PING` | Request an immediate heartbeat | none | Emits one `hb` line right away. |

> **The Pi-side sends RUN/STOP automatically.** In `controller_io.MachineIO._set_out()`
> (and the `RecordingIO` mirror), whenever a **motion relay** is toggled the link
> sends the matching `RUN`/`STOP`. The set of motion relays is
> `MOTION_RELAYS = ("S","T","SP","BE","M","M1","M2")`. Lamps
> (`first_ball`/`second_ball`/`strike`/`foul`) are not motors and send nothing. So
> the firmware's max-run backstop always knows what the Pi believes is energized.

#### 15.4.3 Cam-event → FSM dispatch (Pi side)

The FSM has no `cam_SC`/`cam_TB` methods. The code reserves them for the optional
`interlock_ok()` echo, not a cam handler; on lanes 21/22 that echo has no independent
TB observation and remains default-off/unvalidated. The other four cams map to FSM calls in
`rp2040_link.dispatch_cam()`. Because the FSM guards each handler by state, calling
**both** angle-variants of a dual-trip cam is safe — only the state-matching one
acts.

| Cam `id` (trip edge) | FSM call(s) in `dispatch_cam()` |
|---|---|
| `SA` | `controller.cam_SA_runthrough()` **and** `controller.cam_SA_zero()` |
| `SB` | `controller.cam_SB_guard()` |
| `TA1` | `controller.cam_TA1_delayreset()` **and** `controller.cam_TA1_zero()` |
| `TA2` | `controller.cam_TA2_runthrough()` |
| `SC` / `TB` | **No FSM cam call.** Code path only for the default-off, unvalidated SC/TB echo; no independent TB field input exists on lanes 21/22. |
| `ball` | `controller.on_ball()` |

**The interlock echo** (`RP2040Link.interlock_ok()`) implements an SC∧TB software
model, but it is **default-off, secondary, and unvalidated**. Lane 21/22 has no
independent TB harness observation, and C2A-U is not a dry input, so this path
cannot be credited as protection or diagnostics. The authoritative guard is the
OEM parallel closed-when-safe S/T coil ladder, accepted only after Candidate-C G3
proves both board-commanded coils stay dead with both levers BACK/open.

---

### 15.5 Non-Blocking Telemetry (the TX Ring)

**Telemetry must never stall the safety loop.** UART transmit is a software ring
buffer (`txr[]`, **512 bytes**, `TXR_SZ`), not a blocking write:

- `emit()` formats a complete line and calls `txr_push()`, which enqueues the **whole
  line or none** — never a partial line. A torn JSON line can therefore never reach
  the Pi parser.
- If the ring is full (the Pi isn't draining), `txr_push()` **drops the entire line**
  and increments `txr_drops`. That counter is reported in every heartbeat as
  `hb.drp`, so silent telemetry loss is visible.
- `txr_drain()` pushes as many queued bytes as the UART FIFO will accept this pass
  and **never blocks** (`uart_is_writable()` guard).

The consequence for safety: the `RP2040_OK` drive (`set_rp_ok()` inside
`supervise()`) and the watchdog kick (`watchdog_update()`) run **every loop pass
regardless of UART state.** A jammed or disconnected UART degrades *telemetry*, never
*safety*.

`emit()` also has a compile-time `printf`-format check (`EMIT_FMT` →
`__attribute__((format(printf,1,2)))` under GCC/Clang), so the event format strings
are compiler-verified. When built with `-DDEBUG_USB=ON`, every emitted line is also
mirrored to USB-CDC stdio for bench debugging — but the protocol **always** goes out
`uart0` to the Pi regardless.

---

### 15.6 The Fail-Safe Model — Why `RP2040_OK` Is Safe

This is the most important part of the section. `RP2040_OK` is **fail-safe LOW**:
every way the firmware can fail drives, or allows, the rail to go dead.

| Failure mode | What happens to GP2 | Net effect on the rail |
|---|---|---|
| **Unpowered / in reset / pre-`main()`** | Hi-Z (input by default). The board's 100 kΩ base-pulldown holds the AND-chain NPN off. | **Rail dead.** Motion impossible. |
| **Just after boot** | `main()` drives GP2 **LOW first thing** (before UART, before the watchdog), then HIGH only after `BOOT_SETTLE_MS` (200 ms) and only if no fault. | **Rail dead for ≥200 ms after every boot.** |
| **Main-loop hang** | The RP2040 hardware watchdog (`WDT_TIMEOUT_MS` = 250 ms) fires → chip resets → GP2 → Hi-Z → 100 kΩ pulldown. | **Rail dead**, auto-recovers on reboot; next `boot` event carries `wdt_reset:1`. |
| **Latched fault** (e.g. motion timeout) | `supervise()` computes `set_rp_ok(booted && !fault_latched)` → drives GP2 **LOW** and emits `rp_ok:0`. | **Rail dead** until a `CLEAR` from a known-safe state. |
| **Dead UART** | GP2 unaffected; firmware keeps running healthy. **No `RUN` messages arrive → nothing is marked running → no false permit.** | Rail stays permitted *only* while genuinely healthy; a UART death **mid-run** is still caught by the max-run timer, and the Pi's own motion-timeout fault drops ARM. |
| **TX ring full** | GP2 unaffected; lines dropped, counted in `hb.drp`. | No safety effect (telemetry only). |

`main()` ordering is deliberately safety-first:

1. `gpio_init(PIN_RP_OK)`, set as output, **drive LOW** — before anything else.
2. Init `uart0` (transport only — UART stdio is **disabled**; stdio is USB-CDC only,
   and only when `DEBUG_USB`).
3. `init_inputs()`, record `boot_ms`.
4. Emit the `boot` event (with `watchdog_caused_reboot()` → `wdt_reset`).
5. `watchdog_enable(WDT_TIMEOUT_MS, 1)` — arm the hardware watchdog **after** the
   boot line, so a boot is always reported once.
6. Enter the forever loop: `watchdog_update()` → `scan_inputs()` → `poll_uart()` →
   `supervise()` → `txr_drain()` → periodic `emit_hb()`.

> **The 100 kΩ base-pulldown is what makes "no firmware" mean "no motion."** It lives
> on the board, not in the firmware (`Rpd_AND_RP_OK` in the netlist generator). Do not
> remove it, and do not assume software alone enforces the fail-safe — it is the
> *combination* of GP2-LOW-on-boot, the watchdog reset path, and that pulldown.

---

### 15.7 Motion Max-Run Backstop ("Cam Timeout")

This is the stock v1.2.3 release's active motion-duration backstop (in addition to
the health/watchdog path). It is the RP2040 counterpart to the FSM's own
`MAX_MOTION_S`; measured-cam enforcement flags remain OFF.

**How it works.** Each entry in `motors[]` has a `guarded` flag, a `running` flag,
and a `t_start_ms`. When the Pi sends `RUN <m>`, the firmware sets `running=true` and
stamps `t_start_ms = now`. Every loop pass, `supervise()` checks each **guarded,
running** motor: if `now − t_start_ms > MAX_MOTION_MS`, it calls
`latch_fault("motion_timeout", <motor>)`, which is sticky and immediately forces
`RP2040_OK` LOW on the same pass.

| Motor | `RUN`/`STOP` name | Guarded by max-run? |
|---|---|---|
| Sweep | `S` | **Yes** |
| Table | `T` | **Yes** |
| Spot solenoid | `SP` | **Yes** |
| Sweep-reverse | `M2` | **Yes** |
| Ball-return (DNP / optional) | `M1` | **Yes** |
| Back-end (continuous) | `BE` | **No** — runs continuously, not a timed motion |
| Master / power | `M` | **No** — not a motion motor |

| Constant (`config.h`) | Value | Meaning |
|---|---|---|
| `MAX_MOTION_MS` | `8000` ms (8 s) | Max time a guarded motor may be marked `RUN` without a `STOP`. Matches `cycle_control_8270.MAX_MOTION_S = 8.0 s`. |

**Recovery.** A latched fault clears **only** on a `CLEAR` command, which the Pi
issues solely from a known-safe (zero/ready) state. `CLEAR` also force-stops all
motor flags, clears the fault, and emits an `ack`; `supervise()` then re-permits the
rail on the next pass (subject to `BOOT_SETTLE_MS` already elapsed).

> **This is a backstop, not the primary stop.** The normal cycle has the Pi `STOP`-ing
> each motor on its stop-cam long before 8 s. The max-run timer exists to catch the
> case where the Pi *fails* to stop a motor — a hung FSM, a lost stop-cam, or a UART
> death mid-run. It guarantees a guarded motor cannot be commanded to run indefinitely
> even if the Pi never speaks again.

---

### 15.8 Heartbeat & Pi-Side Health

The firmware emits an `hb` line every `HB_INTERVAL_MS` (**250 ms**, ~4 Hz) and also
immediately on `PING`. The heartbeat carries `ok` (the live `RP2040_OK` state), `flt`
(the latched fault code, or `""`), `up` (uptime ms), and `drp` (cumulative dropped TX
lines).

The Pi side (`RP2040Link` in `lane_node/rp2040_link.py`) consumes this:

- **Liveness** (`is_alive()`): a schema-valid `hb` must have arrived within
  `hb_timeout` (default **1.0 s**, i.e. ~4 missed heartbeats).
  `boot`/`rp_ok`/`flt`/`ack` lines update state but cannot renew this lease.
  `ok` is an exact JSON boolean or integer 0/1, `up` is a uint32, and once a
  v1.2.3 boot nonce is known every heartbeat must carry it.
- **Health** (`health_ok()`): alive **AND** `rp_ok` true **AND** no latched fault. An
  `flt` line marks the RP2040 unhealthy *immediately*, even if the paired `rp_ok:0` is
  delayed or dropped on a lossy UART; the fault is only cleared by a subsequent `hb`
  carrying `flt:""` (i.e. after a successful `CLEAR`).
- **Action:** the daemon's main loop calls `link.health_ok()` right after
  `controller.poll()`; if it is false, it faults the FSM and drops ARM
  (`io.arm(False)`), which removes the **other** series condition from the rail. So an
  unhealthy RP2040 drops the rail **twice**: once in hardware via GP2, and once via the
  Pi dropping ARM.

The Pi-side reader runs on a **background thread** that only *updates* health/interlock
state under a lock and *queues* cam/ball events; the FSM is touched only from the main
loop via `apply_events()`, keeping the non-thread-safe FSM single-threaded.

---

### 15.9 v1.2.3 Release Posture — Enforcement Implemented but Default OFF

The v1.2.3 code contains the v1.1-era safety-supervision paths, but the controlled
Rev-D release intentionally ships every measured-cam enforcement flag **OFF**.
Code presence and host tests are not permission to use an unmeasured field signal.

#### Implemented paths whose field enablement remains deferred

1. **Cam-stop OVERRUN enforcement.** The desired behavior: a *stop-cam* fires while a
   motor is RUNNING and the Pi fails to `STOP` it within a short grace window → the
   firmware drops `RP2040_OK` directly. This needs the **per-cam edge → angle
   polarity** (which of `f`/`r` is the angular trip, per cam). That polarity is a
   deliberately-deferred field item
   (`docs/phase8_trackB_controller_cutover_runbook.md` §3.2). The implementation is
   present, but `CAM_*_STOP_ENABLED` remains 0 until polarity is measured and bound
   into a **new controlled release** that passes the bench gate.

2. **SC/TB collision echo gating `RP2040_OK`.** This remains **default-off,
   secondary, and unvalidated**, not merely waiting on window angles. Lane 21/22
   has no independent TB harness input and C2A-U is a live-ladder region, so a
   two-input SC∧TB echo cannot be credited without a separately reviewed sensing
   redesign. Primary protection is Candidate C's OEM ladder + per-lane G3 proof.

#### What stock v1.2.3 provides

- **Firmware health** (watchdog → rail dead on hang).
- **Motion max-run backstop** (the 8 s guarded-motor timeout, §15.7) — a *coarse*
  time-based catch, **not** per-cam-edge enforcement.

#### Why this still blocks measured-cam credit at cutover

The Track-B runbook may credit a per-cam rail-drop only after the relevant measured
polarity is enabled in a manifest-bound release and proven on the target hardware.
Stock v1.2.3 cannot pass that sub-test because its cam flags are OFF; its active
motion enforcement is the coarser 8 s max-run timer. Candidate-C G3 collision
protection is a different, primary hardware proof: with the board commanding S and
then T, both levers BACK/open must leave each machine coil dead.

> **"Controlled bundle exists" ≠ "cutover ready."** v1.2.3 is host-tested and
> release-packaged but not flashed. Cutover still requires first-article/on-hardware
> bring-up and, before any measured-cam enforcement is credited, a newly controlled
> release with confirmed polarity and the applicable bench proof. Until those gates
> pass, the existing OEM controller stays in charge of the machines.

*(VERIFY: the exact label/letter "G3" for the cam-stop rail-drop gate — taken from the
firmware README's "G3 cam-stop rail-drop gate" wording and
`phase8_trackB_controller_cutover_runbook.md`; confirm against the current runbook's
gate list.)*

---

### 15.10 Build, Flash & Test

#### 15.10.1 Build (Pico SDK)

Requires the [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk),
`arm-none-eabi-gcc`, CMake, and Ninja (or Make).

```powershell
# From firmware/rp2040:
powershell -ExecutionPolicy Bypass -File .\release.ps1

# Before copying or flashing an existing bundle:
powershell -ExecutionPolicy Bypass -File .\release.ps1 -VerifyOnly
```

The controlled release script fixes the release options, runs the host tests, builds both
the production and bench-only FI-1 images, and writes
`release/firmware_manifest.json`. The manifest binds each UF2 SHA-256 to its exact
on-wire `id.build`, `id.cfg`, and `id.fi1`, the complete controlled-source/config hashes,
and the clean Pico SDK/toolchain inputs. The verifier also reconstructs each UF2 payload
and proves those identity strings are embedded. `build.ps1` and direct CMake builds are
developer outputs; do not flash them as release artifacts.

#### 15.10.2 Flash

| Method | When | How |
|---|---|---|
| **USB BOOTSEL** (preferred) | Bench, before the module is buried | First pass `release.ps1 -VerifyOnly`; hold **BOOTSEL** while connecting USB, then drag-drop **`release/wsl_phase8b_rp2040.uf2`**. Never substitute `_FI1.uf2`. |
| **SWD** (fallback) | Once the module is soldered and USB isn't accessible | After the same verification, `picotool load -x release/wsl_phase8b_rp2040.uf2`, or OpenOCD via the board's SWD test points. |

After every flash, request `ID` and require `fw`, `build`, `cfg`, and `fi1:0` to equal
the verified manifest. A matching filename or version banner alone is not image proof.

#### 15.10.3 Host logic test (no hardware)

The pure logic — TX ring, debounce/edges, ball lockout, UART protocol, and the
`RP2040_OK` safety supervisor — has a host unit test that **mocks the Pico SDK**, so
it builds and runs on any host C compiler:

```bash
# from firmware/rp2040/
gcc -std=c11 -Wall -Wextra -I test -I test/stubs test/test_main.c -o test/test_main.exe
./test/test_main.exe        # exit 0 = all checks pass
```

**Current controlled-source host result:** 64/64 (`test_main`) + 32/32
(`test_v11`) + 140/140 (`test_v12`) + 44/44 (`test_fi1`) checks passed
(2026-07-23, gcc 16.1.0), clean under `-Wall -Wextra -Werror`. These tests prove
code behavior, including default-off inertness; they do **not** validate a field
polarity or create an independent TB lead.

The **Pi-side** link has its own host test (no hardware, mocks the serial transport):

```bash
# from lane_node/
python rp2040_link.py        # exit 0 = all pass
```

The current Pi-side self-test reports **45/45** checks — covering parsing/health, the
SC∧TB **software-model unit path (not field validation)**, full cam/ball→FSM dispatch through a strike cycle, RUN/STOP
emission via the `controller_io` integration, command formatting, and the
"bare-`flt`-marks-unhealthy" case. A companion regression guard in
`controller_io.py`'s `__main__` re-derives `OUT_A_MAP`/`IN_A_MAP` from the netlist
generator and **fails on drift** — so the relay/input bit-maps can't silently diverge
from the PCB.

#### 15.10.4 On-hardware bench bring-up (LOCKED-OUT / off machine only)

Per `docs/phase8b_pcb_revB_spec.md` §12.9 — do this on a machine that is **locked out
/ powered off**, with the rail externally safe:

1. **Power + boot.** Flash, power the board logic only. On USB/UART expect a `boot`
   line, then `hb` at ~4 Hz with `ok:1` after ~200 ms (`BOOT_SETTLE_MS`). Meter GP2 /
   the rail-permit test pad → **HIGH** once healthy.
2. **Landed inputs.** Hand-actuate each independently wired motion cam / break each
   DIELL beam → confirm the matching `cam`/`ball` event with the correct `id`, and
   capture the edge→angle polarity for any future enforcement release. Do not expect
   an independent TB event on lane 21/22; SC/U is not a dry input landing.
3. **Watchdog drop.** Pause the loop (or pull power to just the Pico) → GP2 → **LOW** →
   rail drops. Force a hang and confirm the next `boot` carries `wdt_reset:1`.
4. **Motion timeout.** Send `RUN S`, wait > 8 s without `STOP S` → expect
   `{"ev":"flt","code":"motion_timeout","m":"S"}` and GP2 → **LOW**. `CLEAR` → GP2 back
   **HIGH**.
5. **Only then** integrate with the rail/relay section per spec §12.9 — each relay with
   a dummy load and each implemented on-board drop. Opening J_SAFE1-2 tests only the
   PCB provision. Candidate-C TB/SC protection is proven later by the per-lane live
   G3 S-and-T coil-drop test before motion.

---

### 15.11 Quick Reference — Constants & Tokens

All from `firmware/rp2040/config.h` unless noted.

| Name | Value | Purpose |
|---|---|---|
| `FW_VERSION` | `"phase8b-rp2040 v1.2.3"` | Reported in identity/boot telemetry; require the manifest-bound release identity. |
| `UART_BAUD` | `115200` | UART0 line rate (8N1, no flow control). |
| `DEBOUNCE_CAM_US` | `2000` µs | Cam input debounce window. |
| `DEBOUNCE_DIELL_US` | `500` µs | Ball-beam input debounce window. |
| `BALL_LOCKOUT_MS` | `300` ms | One-ball-one-event re-trigger lockout (global across both beams). |
| `HB_INTERVAL_MS` | `250` ms | Heartbeat cadence (~4 Hz). |
| `BOOT_SETTLE_MS` | `200` ms | `RP2040_OK` held LOW at least this long after boot before any permit. |
| `WDT_TIMEOUT_MS` | `250` ms | RP2040 hardware-watchdog timeout (loop hang → chip reset → rail drop). |
| `MAX_MOTION_MS` | `8000` ms | Max-run backstop window for guarded motors (matches FSM `MAX_MOTION_S`). |
| `TXR_SZ` | `1024` bytes | Non-blocking TX ring size (`main.c`). |
| `DEBUG_USB` | `0` (default) | When `1`, mirror events to USB-CDC; protocol still always goes to `uart0`. |
| Commands | `RUN <m>` · `STOP <m\|*>` · `CLEAR` · `PING` | Pi → RP2040. |
| Events | `boot` · `cam` · `ball` · `rp_ok` · `flt` · `hb` · `ack` | RP2040 → Pi. |
| Guarded motors | `S`, `T`, `SP`, `M2`, `M1` | Subject to the max-run timeout. |
| Unguarded motors | `BE`, `M` | Not timed (continuous / master). |

---

### 15.12 Maintenance Notes & Gotchas

- **The pin map's only source of truth is the Rev-D netlist generator**
  (`scripts/generate_kicad_netlist_revD.py`, `block_rp2040()` + `FAST_INPUTS`).
  `config.h` cites it. If the board ever changes, re-verify `config.h` against the
  generator **before flashing**. The GPIO column in
  `docs/phase8_channel_allocation.md` §2 is **stale** (GP0–GP7) — ignore it.
- **Do not move the fast inputs off GP6–GP13** or `RP2040_OK` off GP2 without editing
  *both* the netlist generator and `config.h` — and re-routing the board.
- **Never make telemetry blocking.** The non-blocking TX ring is a safety property,
  not a performance nicety: a blocking UART write could stall the loop, miss the
  watchdog kick, and (correctly, but unnecessarily) drop the rail. Keep `emit()` →
  ring → `txr_drain()` non-blocking.
- **Keep `RP2040_OK` driven LOW as the first action in `main()`** and HIGH only via
  `supervise()`. Never drive GP2 HIGH from anywhere else.
- **The watchdog is armed *after* the `boot` emit** so a boot is always reported once
  before the watchdog can re-trigger. Don't reorder.
- **`CLEAR` is privileged.** The firmware trusts that the Pi only issues `CLEAR` from a
  known-safe (zero/ready) state — the firmware itself does not re-verify machine
  position. Keep that contract on the Pi side (`controller_daemon` issues `CLEAR` at
  `_finish_cycle`/READY).
- **`now_ms()` wraps at ~49.7 days.** All time comparisons use unsigned subtraction
  (`(uint32_t)(now - then)`), which is wrap-safe; don't replace those with signed
  comparisons.
- **`GPA7`/`GPB7` on the MCP23017 are output-only** (a known silicon erratum noted in
  the netlist). That doesn't affect the RP2040, but it constrains the *Pi-side* I/O on
  the same board — relevant if you renumber MCP bits. The MCP23017 here is the **I²C**
  part (LCSC **C47023**), not the SPI MCP23S17.
- **Relay coils are 5 VDC.** The board uses the **Omron G5LE-14** (5 V coil, SPDT;
  LCSC **C116963**) — *not* a 12 V or 24 V coil part. The RP2040 never drives a coil
  directly; it only permits the rail that powers them.
- **The NE555 watchdog (LCSC C7593, `NE555DR`) watches the *Pi*, not the RP2040.** Two
  independent watchdogs exist on a board: the RP2040's *on-chip* watchdog (watches this
  firmware's loop) and the NE555 *hardware* watchdog (kicked by a Pi GPIO). Don't
  conflate them.
