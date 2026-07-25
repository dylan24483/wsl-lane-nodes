## 19. Safety Architecture (Consolidated)

This section is the single place that describes the **complete layered safety model** of the
Phase 8 lane controller. Other sections describe individual blocks in depth — §10 (Rev-B Safety
Hardware: NE555 Watchdog + Relay-Enable Rail) is the circuit-level reference, §09 (Relay
Outputs) the output stage, §07 (RP2040 + MCP) the controllers, §03/§04 (Machine Sequence /
Machine I/O) the machine and its cams. **This section ties them together** so an engineer
walking in cold understands what catches what, why the layers are arranged the way they are, and
which layer is authoritative for each failure mode.

> ### The one rule that overrides everything else
>
> **This controller board is NEVER the only safety device.** Live motor current never crosses
> the PCB; the machine's own S/T contactors keep switching the 115 VAC motors and keep their OEM
> regenerative braking. The **Stop / C.I.S. / rear-panel master-breaker** chain stays live and
> upstream. The **TB/SC table–sweep collision interlock** stays in the OEM S/T coil ladder. The board's job
> is to add a *permission* layer and a *fast-supervision* layer on top of those — not to replace
> them. This is the non-negotiable safety rule stated in the design contract
> (`docs/phase8b_pcb_revB_spec.md` §"Non-negotiable safety rule" and §4.5) and repeated in the
> firmware (`firmware/rp2040/main.c` SAFETY MODEL header) and the cutover runbook
> (`docs/phase8_trackB_controller_cutover_runbook.md` §0).
>
> The board's J_SAFE3-4 Stop/CIS source position is **not currently a field
> protection**: lane 21/22 leaves it physically OPEN/unlanded because no suitable
> dry tap has been measured. The resulting no-arm state is deliberate. Never
> jumper 3–4 at the machine.

Sources grounding this section: the design contract `docs/phase8b_pcb_revB_spec.md` (§4 Safety
Rail Contract, §2/§3 domains/outputs); the OEM system reference `docs/phase8_8270_SYSTEM_REFERENCE.md`
§5 (the AMF 82-70 safety model we preserve); the cutover runbook
`docs/phase8_trackB_controller_cutover_runbook.md` §0/§1/§6/§7; the firmware
`firmware/rp2040/config.h`, `firmware/rp2040/main.c`, `firmware/rp2040/README.md`; the live board
netlist generator `scripts/generate_kicad_netlist_revB.py` (`block_rail()`, `block_watchdog()`,
`relay_output()`); the Pi-side software `lane_node/cycle_control_8270.py`,
`lane_node/controller_io.py`, `lane_node/controller_daemon.py`, `lane_node/rp2040_link.py`; the
OEM audit `docs/phase8_oem_doc_audit_2026-06-02.md`; and the assembly BOM
`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`.

---

### 19.1 The three layers at a glance

Safety is enforced in three layers, deepest (most independent of software) first. A hazard is
caught by the **lowest** layer that applies; the upper layers exist to catch the hazard *earlier*
and to make the system observable and recoverable.

| Layer | Lives in | Independent of | Catches |
|---|---|---|---|
| **HARDWARE** | The machine + the relay-enable rail on the PCB | Both the Pi and the RP2040 (and even the PCB, for the breaker/braking/interlock) | Loss of power, a table–sweep collision course, a welded/runaway machine state, Pi death, RP2040 death |
| **FIRMWARE** | The RP2040 co-processor on each board | The Pi and the UART link | A motor commanded to run and never stopped (max-run), a hung Pico, and only in a future measured/qualified release, a stop-cam overrun |
| **SOFTWARE** | The cycle FSM + daemon on the Raspberry Pi | — (top layer; backed by the two below) | Motion-state timeouts, RP2040 health loss, and the power-restore rule. The SC∧TB model is default-off/unvalidated on lanes 21/22 and receives no protection credit. |

The defining property of the design is **fail-open**: every layer's *default*, de-energized,
unpowered, or pre-init state is "no motion permitted." Permission to move is something that must
be actively and continuously *earned* by all layers at once; the absence of any signal is read as
"unsafe," never "safe."

---

### 19.2 HARDWARE layer

These are the protections that exist in copper and in the machine, and that hold even if every
line of software is wrong or absent.

#### 19.2.1 The Stop / C.I.S. / master-breaker chain (OEM, preserved)

Per the AMF 82-70 manuals (`docs/phase8_8270_SYSTEM_REFERENCE.md` §5), the **Stop switch and the
Cushion Interlock Switch (C.I.S.)** are wired **in parallel**, and either one **cuts the
rear-panel master circuit breaker**, which kills all control power to the machine. This is the
intended **irreducible, final physical stop.** Phase 8 does **not** replace or move it.

Documentation is not proof of the installed lane. Before motion, actuate Stop and
CIS separately and verify the OEM rear master breaker/control power drops. The
current lane-21/22 harness has no measured dry tap for this chain: J_SAFE3-4 is
physically OPEN/CUT+LABEL-ONLY, so the field rail cannot arm. Never jumper 3–4 at
the machine. After an engineered fail-safe dry interface is installed, also
require each Stop/CIS demand to drop TP16. Opening the 3–4 interface alone proves
board-source continuity, not the OEM breaker path.

Why it stays the final stop: it is the only layer that removes machine control *power*, as
opposed to removing *permission*. It is therefore the only thing that can stop a machine whose
on-board relay contact has welded closed (see §19.2.6).

A wiring bypass can read healthy throughout normal operation and remain invisible
until Stop or CIS is demanded. The individual demand tests are therefore repeated
periodically, not treated as a one-time continuity check.

> **⚠ FIELD FINDING 2026-07-24 (lane 21/22, physical inspection — Dylan at the machine):
> THERE IS NO C.I.S. ON THESE LANES. The chain here is STOP-ONLY.**
> The cushion was inspected thoroughly and is **purely mechanical** — shock absorber with a
> coil-over spring, **no switch and no wiring of any kind**. Consistent with the documented
> retrofit history: the original **SS (cushion start)** switch was the ball detector and was
> **replaced by DIELL** (`phase8_8270_SYSTEM_REFERENCE.md` input list: *"SS (cushion start —
> DIELL on our lanes)"*), confirmed at the machine — **DIELL triggers the cycle.** The CIS
> hardware appears to have gone with it.
>
> Consequences:
> - The §19.2.1 "Stop **+ C.I.S.** in parallel" topology above is **OEM-manual history, not the
>   installed lane.** Every CIS demand test (§19.2.1, the gate table, and the FMEA row) is
>   **N/A on 21/22**; the Stop demand test stands and is still required.
> - **STILL OPEN:** whether any *other* pit-entry interlock exists (gate switch, pull cord,
>   frame switch). Resolve by asking a mechanic the operational question — *"does anything kill
>   the machine automatically when you enter the pit, or do you hit Stop first?"* Record the
>   answer here. If none exists, lockout discipline is the only pit-entry protection today.
> - **J_SAFE3-4 design implication:** with no OEM CIS to borrow a contact from, the leading
>   candidate is a **control-power sensing relay** (24 VAC coil bridged across a control rail,
>   N.O. contact → J14-3/4: power-present = closed = safe; Stop, breaker trip, coil failure, or
>   broken tap all open it — **fail-safe in every direction**, and the inverse of the flaw that
>   disqualified interlock Candidate B) **optionally in series with a NEW pit-entry interlock
>   switch we install** — which would give the machine an automatic pit interlock it does not
>   currently have. Owner decision; neither is landed. Never a substitute for the Stop switch
>   or for lockout during service.
> - DIELL model: its output serves the **machine's** trigger circuit (the ex-SS path — most
>   likely the 42 VAC middle block measured 2026-07-21); a parallel feed to the VDB is possible
>   but unproven. Sensor-side taps (terminals 2+3 per group) remain the correct and only
>   approved tap points; middle block stays untouched.

#### 19.2.1a Protective earth and mains polarity (external to Rev-D)

Hot, neutral, and protective earth never enter Rev-D, J14, or any board harness.
At commissioning and periodic maintenance, a qualified electrician must use an
appropriately listed external tester to verify protective-earth continuity and
bonding, confirm correct hot/neutral polarity, and record the result. A low-voltage
board measurement, a software diagnostic, or a J_SAFE continuity check cannot
certify the mains installation.

#### 19.2.2 The TB/SC table–sweep collision interlock (OEM ladder, Candidate C)

The 82-70 has two interlock cams that together detect a table–sweep interference (collision)
course:

| Cam | Window | Meaning |
|---|---|---|
| **SC** (sweep) | ~86–243° | sweep is under the table |
| **TB** (table) | ~105–255° | table is in the sweep-interference zone |

The evidence is now reconciled. Cold continuity on 2026-06-27 located SC at C2A-U,
found no standalone/isolatable TB pair, and exposed ~21 Ω relay-coil sneak paths.
Those facts invalidate cold topology inference. The powered 2026-07-07 test is the
authority: TB and SC act as **parallel closed-when-safe contacts** in the OEM 24 VAC
S/T coil ladder. Either pressed lever permits a coil; **both levers BACK/open kill
both S and T coils**, including on the brain-independent rear-panel manual commands.

No dry pair exists for J_SAFE1-2. Candidate C therefore installs the controlled,
labeled jumper at that board position and preserves the OEM ladder inside each
board-commanded S/T coil path. This is accepted only after the per-lane G3 insertion
proof: command S, then T; with both levers BACK/open each contactor coil must remain
dead. Any energized coil is abort/rollback. The firmware SC∧TB model is default-off,
secondary, and unvalidated because the harness supplies no independent TB input.

#### 19.2.3 Regenerative motor braking (OEM, preserved on the contactors)

The S (sweep) and T (table) relays/contactors each have both NO and NC contacts. Energized NO
contacts feed the motor main/start windings; **de-energized NC contacts connect capacitors across
the main winding for regenerative braking** (`docs/phase8_8270_SYSTEM_REFERENCE.md` §4/§5; OEM
audit §1). When the rail drops a motor's command, the contactor de-energizes and this braking
contact set actively brakes the motor — in machine hardware, with no software involved.

This is why the output contract (§09; contract §3.1) forbids replacing the S/T contactors with
direct MOSFET/triac coil drive: doing so would bypass the OEM braking contact set. Rev-B only
**commands the existing S/T control circuits** through isolated dry contacts; the contactors and
their braking behavior stay exactly as the machine shipped.

#### 19.2.4 The NE555 watchdog (the Pi's hardware deadman)

The NE555 (U36, **bipolar** NE555DR, LCSC C7593) is wired as a retriggerable monostable that the
Raspberry Pi must continuously **kick** (pulse a GPIO into `WDOG_KICK`, J14→J1 pin 7, through the
Q12 kick FET). While kicks keep arriving inside the timeout window, the NE555 output holds the
watchdog-OK transistor Q13 conducting, which is one rung of the rail AND chain. **If the Pi
process hangs, crashes, or the OS dies, the kicks stop, the monostable times out, Q13 turns off,
and the rail drops all relay coils.** This is the hardware backstop for "the Pi died" and is
independent of the RP2040, of the UART, and of any Pi software.

Full circuit, pinout, and parts are in **§10.2 / §10.4**. The two facts that matter at the
architecture level:

- The kick is software-coupled on purpose: it is issued **only** from inside the FSM control loop
  (`CycleController.poll()` → `io.watchdog_kick()`; `lane_node/controller_daemon.py` `_kick_wdog`).
  If the control loop stalls for any reason, the kick stops and the rail drops. (Contrast the
  Track-A scoring node, which must *never* be able to stop the machine — the daemon comment in
  `controller_daemon.py` calls this coupling out as intentional.)
- This NE555 watches the **Pi**. It must not be confused with the RP2040's *internal* watchdog,
  which watches the **Pico firmware** (§19.3.2). They are separate rail conditions.

> **(VERIFY: NE555 monostable timeout period and the Pi kick interval.)** The RC is R100 = 100 k
> and C11 = 100 µF (≈ 11 s nominal for a textbook monostable), but the kick is wired into both the
> timing and trigger nodes (a retrigger topology) and the contract (§4.3) specifies the behavior
> qualitatively ("missing kick for the timeout window drops the rail") without a number. The
> effective worst-case drop time is a bench bring-up measurement (contract §12.9 "watchdog drop");
> do not assume 11 s. See §10.2.3.

#### 19.2.5 The relay-enable rail and the separate Candidate-C guard

The single most important on-board safety structure is the **relay-enable rail**
(`RELAY_ENABLE_RAIL`). It is the high-side +5 V supply to **every** motion-relay coil. The rail is
live only when a P-channel pass-FET (**Q14**, AO3401A, LCSC C347476) is on. The
table retains the PCB contract's six named positions, but Candidate C closes row 5
with the controlled jumper and delegates primary TB/SC blocking to the separate OEM
S/T coil ladder. Rows 1–4 are effective on-board permissions. Row 6 is the
designed Stop/CIS source position, but it is currently OPEN/unlanded and holds the
field rail dead:

| # | Condition | Source | Where it acts on the rail | Fail-safe default |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 (U36) kicked by the Pi (`WDOG_KICK` / GPIO12) → FET Q13 | Bottom of the gate AND chain (Q13 must conduct) | false (no kicks → Q13 off) |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO (J1 pin 8) → NPN Q15; asserted only after operator-safe state / First-Ball-Zero | Top of the gate AND chain (Q15 must conduct) | false (R108 100 k base pulldown) |
| 3 | **RP2040 OK** | RP2040 `GP2` health/permission line (`RP2040_OK`) → NPN Q16 | Middle of the gate AND chain (Q16 must conduct) | false (R110 100 k base pulldown; GP2 Hi-Z on reset) |
| 4 | **Cam-stop OK** | RP2040 immediate cam-stop drop path | **Folds into condition 3** — firmware drives `GP2` LOW on a cam-stop violation/timeout | false on RP2040 reset/fault |
| 5 | **TB/SC board provision** | Controlled Candidate-C jumper on J14 pins 1↔2; no machine landing | Closes the first FET-source position; primary guard is the OEM S/T coil ladder | keyed/labeled jumper only; G3 fails if either commanded S/T coil remains live with both levers BACK |
| 6 | **Reserved Stop/CIS source position** | Future validated fail-safe dry interface on `J_SAFETY` J14 pins 3↔4; **currently OPEN/unlanded** | In series with the FET source, after the Candidate-C jumper position | open; field rail cannot arm |

Two structural facts make this a genuine hardware AND (verified against
`scripts/generate_kicad_netlist_revB.py` `block_rail()`):

- **The J_SAFE positions are in series with the FET source.** +5 V traverses the
  Candidate-C pin-1/2 jumper and the on-board pin-2/pin-3 net, then can reach Q14
  only through a future approved 3–4 interface. The present open 3–4 harness holds
  the field rail dead. Opening either completed source position proves board
  continuity only; it does not validate the OEM TB/SC ladder or the OEM
  Stop/CIS-to-breaker path.
- **Conditions 1, 2, and 3 (= 4) are a series transistor stack on the FET gate.** The gate
  (`RAIL_GATE`) is pulled **up to the source** by R106 (100 k) — off by default. To turn the rail
  on, three transistors in series (Q15 "AND ARM" → Q16 "AND RP_OK" → Q13 "wdog") must **all**
  conduct to pull the gate to ground. Each base/gate has its own 100 k pulldown (R108, R110, R105)
  so the default with no drive is off. Any one open → chain open → R106 holds the gate at the
  source → FET off → rail dead.

**Why cam-stop is not a sixth transistor.** Condition 4 (Cam-stop OK) is a *firmware behavior*,
not a separate device: the RP2040 is the cam-stop enforcer and pulls its single `GP2` health line
LOW on a cam-stop violation/timeout (contract §4.2; firmware README). Electrically the PCB has
two source positions + a three-transistor gate AND; Candidate C closes the first source
position with its controlled jumper, and cam-stop drives one
of them (`RP2040_OK` / Q16) false. Do not look for a sixth transistor — there isn't one. Full
schematic, pin→net tables, and the AND-chain diagram are in **§10.3 / §10.4**.

**What the rail gates — two gates in series for any motion output.** A motion relay energizes only
if **(a)** the Pi sets that relay's `MCP23017 OUT-A` bit (turning the per-relay NPN on to ground
the coil low side) **AND (b)** the rail is live (supplying +5 V to the coil high side). The Pi
controls (a); the implemented on-board rail controls (b). **Software alone cannot fire a coil.**
For S/T, the OEM TB/SC ladder is an additional independent coil-path condition validated by G3. The rail
reaches the high side of all seven motion-relay coils — K1–K6 for S/T/SP/BE/M/M2 plus the DNP K7
for M1 — their flyback cathodes, and Q14's drain (see §10.5). The status-LED outputs
(L_FIRST/L_SECOND/L_STRIKE/L_FOUL) are **not** on the rail — they are non-motion-critical and
driven straight from 5 V logic (contract §3.3; §09).

#### 19.2.6 The welded-contact limitation (read before relying on the rail)

The rail de-energizes relay **coils**. It **cannot open a relay contact that has welded closed.**
If a motion-relay contact welds, dropping the rail removes coil drive but the welded contact stays
made, and the machine control circuit it feeds stays made (contract §4.5; §10.6). Consequences for
the architecture:

- **The relay contact rating, arc suppression, and validation are safety-relevant.** Every motion
  output has DNP footprints for an RC snubber (`Rsnub_*` 100 R + `Csnub_*` 10 nF X2) and a MOV
  across the contact, to be populated per output after load characterization (contract §2.3/§3.2;
  netlist `relay_output()`). Suppression on inductive AC control loads is **not** optional
  decoration (OEM audit §6).
- **The final physical stop is upstream and external.** The master breaker / Stop / C.I.S. chain
  (§19.2.1) removes machine control power regardless of any welded on-board contact. The rail is a
  **permission** layer, not a **disconnect** layer.
- **Regenerative braking stays in machine hardware** (§19.2.3), independent of the board.

If a future CT/Hall channel detects motor current while the controller command is
OFF, report **`uncommanded_motor_current`** with suspected cause
**external-feed-or-welded**. Current alone cannot distinguish a welded contact
from another external feed or bypass; do not label that observation
`welded_contact` without independent contact/circuit evidence.

> **(VERIFY: relay contact rating headroom.)** Whether the Omron **G5LE-14, 5 VDC** relay
> (K1–K6, LCSC C116963 — BOM note: "Critical: 5VDC coil. Do not substitute 9V/12V/24V coil.")
> contact-side AC-inductive rating has sufficient margin for the measured machine control-circuit
> current is an open assembly-gate item (contract §11 item 1; §10.5). The footprint and 5 VDC coil
> are fixed; the contact load rating must be confirmed against measured current before
> populated-board sign-off.

---

### 19.3 FIRMWARE layer (RP2040 co-processor)

Each board carries one RP2040 (a stock Pico module, A1). It is the **fast + safety half** of the
controller: it owns the latency-critical inputs and drives the hardware rail-permission line. Its
safety contributions are **UART-independent** — they hold even if the link to the Pi is dead.
(Authoritative pin map and electrical sense in §07 and `firmware/rp2040/config.h`; fast inputs are
on **GP6–GP13**, `RP2040_OK` on **GP2**, UART on **GP0/GP1**.)

#### 19.3.1 RP2040_OK is fail-safe-low by construction

`RP2040_OK` (GP2) is condition 3 of the rail. The firmware makes it fail-safe in every
non-healthy state (`firmware/rp2040/main.c`, README "Safety model"):

- **Pre-init / unpowered / in reset / BOOTSEL:** GP2 is **Hi-Z**. The board's on-board 100 k base
  pulldown (R110) holds the Q16 AND-chain transistor off → rail dead. `main()` then drives GP2
  **LOW** as its very first action, before configuring anything else.
- **Healthy:** GP2 goes HIGH only **after** `BOOT_SETTLE_MS` (200 ms, `config.h`) **and** only
  while no fault is latched (`supervise()` computes `set_rp_ok(booted && !fault_latched)`).
- **Telemetry never blocks safety:** the UART TX is a non-blocking ring buffer; if the Pi is not
  draining it, whole lines are dropped (counted in the heartbeat's `drp` field) — but the GP2
  drive and the watchdog kick still run every single loop pass.

#### 19.3.2 RP2040 internal watchdog (firmware-hang catch)

The RP2040 enables its **own internal hardware watchdog** with `WDT_TIMEOUT_MS = 250 ms`
(`config.h`; `watchdog_enable(WDT_TIMEOUT_MS, 1)` in `main.c`). The main loop calls
`watchdog_update()` every pass. If the firmware loop ever hangs, the chip resets → GP2 returns to
Hi-Z → R110 holds the rail dead → motion stops. On reboot the firmware emits a `boot` event with
`wdt_reset:1` so the Pi knows a hang occurred. This is a *separate* rail condition from the NE555
(which watches the Pi, §19.2.4): the NE555 covers Pi-side death, the RP2040 internal WDT covers
Pico-side death.

#### 19.3.3 Motion max-run backstop ("cam timeout") — implemented in v1

This is the controlled v1.2.3 release's active motion-duration contribution. The
Pi tells the RP2040 which motors are running over the UART (`RUN <m>` / `STOP <m>`). If a
**guarded** motor is marked RUNNING longer than `MAX_MOTION_MS = 8000 ms` (8 s — matching the
FSM's `MAX_MOTION_S = 8.0`) and is never stopped, the firmware **latches a fault and drops
`RP_OK`** (`main.c` `supervise()` → `latch_fault("motion_timeout", …)`), dropping the rail. The
guarded set (from `main.c` `motors[]`):

| Motor | Guarded by max-run? | Note |
|---|---|---|
| S (sweep) | yes | |
| T (table) | yes | |
| SP (spot) | yes | |
| M2 (sweep reverse) | yes | |
| M1 (ball return) | yes | channel is DNP on the board; guarded in firmware if ever populated |
| BE (back-end) | **no** | continuous motor — runs all the time, must not time out |
| M (master/power) | **no** | not a motion motor |

Recovery is by `CLEAR`, which the Pi issues **only** from a known-safe (zero/ready) state
(`main.c handle_line`; `rp2040_link.clear()`). A dead UART cannot cause unsafe motion: with no
`RUN` messages nothing is marked running (no false permit), and a UART death *mid-run* is caught
by this max-run timer.

#### 19.3.4 Per-cam stop overrun — code present, release flags OFF

**Per-cam-edge cam-stop OVERRUN enforcement** — a stop-cam fires while a motor is RUNNING and the
Pi fails to `STOP` it within a grace window → drop `RP_OK` — is implemented in the
v1.2.3 code, but every measured-cam enforcement flag is **OFF** in the controlled
release. It requires per-cam edge→angle polarity, a new manifest-controlled
release, and its bench proof. **What this means for safety:** stock v1.2.3 provides
RP2040 health + the motion max-run backstop (§19.3.3), but no credited crisp
per-cam-edge overrun detection. The SC/TB collision echo is a separate **default-off, unvalidated
secondary path**: there is no independent TB harness observation, so it cannot be
enabled or credited merely by capturing angles. Candidate C's OEM ladder is primary.
The cam-stop sub-gate remains blocked until the measured release exists and passes
(see §19.5).

---

### 19.4 SOFTWARE layer (Raspberry Pi: cycle FSM + daemon)

The Pi runs the cycle FSM (`lane_node/cycle_control_8270.py`) and the per-pair control daemon
(`lane_node/controller_daemon.py`), commanding relays over I²C/MCP23017 via
`lane_node/controller_io.py`. **Every software protection here is backed by a hardware/firmware
backstop** — software is the top layer, not the guarantee.

#### 19.4.1 Power-down / manual-intervention rule

The OEM MP "Power-Down" feature (`docs/phase8_8270_SYSTEM_REFERENCE.md` §5): after *any* 115 VAC
loss while in "Bowl," the machine performs **no motion on power restore** until a deliberate
**First-Ball-Zero** (manual intervention). The FSM replicates this exactly:
`CycleController.power_restore()` turns all motors off and comes up in state
`MANUAL_INTERVENTION`, driving nothing; only an operator **First-Ball-Zero** (PBZ) transitions to
`READY` (`cycle_control_8270.py` `power_restore` / `first_ball_zero`). The daemon enforces the same
at the rail: `ARM_PERMIT` is held de-asserted in every `DISARMED_STATES` member
(`POWER_OFF`, `MANUAL_INTERVENTION`, `FAULT`), so even if a relay bit were set, condition 2 of the
rail is false and no coil can energize.

#### 19.4.2 Motion-timeout fault (FSM)

The FSM has its own software motion-timeout independent of the firmware's: any motion state
(`SWEEP_TO_GUARD`, `TABLE_DETECT`, `RUNTHROUGH`, `SPOTTING`, `TABLE_FINISH`) that persists longer
than `MAX_MOTION_S = 8.0 s` drives the FSM to `FAULT`, turns all motors off, and (via
`DISARMED_STATES`) drops `ARM_PERMIT` (`cycle_control_8270.py` `poll()`). This is the software
sibling of the firmware max-run backstop (§19.3.3); the two share the 8 s budget so they agree.

#### 19.4.3 Daemon health-loss safety trip

This is a subtle but critical software protection (`lane_node/controller_daemon.py`
`BoardController.tick()`). Each tick the daemon checks `link.health_ok()` — true only if the
RP2040 is heartbeating, reports `rp_ok`, **and** has no latched fault
(`rp2040_link.health_ok()`). On the **transition** to unhealthy, the daemon does a **full safety
trip**, not just an ARM drop:

1. it logs the loss,
2. calls `fsm.power_restore()` → `_all_motors_off()` (which **clears the relay output latches**)
   and forces the FSM back into `MANUAL_INTERVENTION`,
3. holds `ARM` de-asserted.

Recovery then **requires a deliberate First-Ball-Zero** — a returning heartbeat does **not**
auto-re-arm. The reason (documented in the daemon's `_selftest` "P1 safety" case, a real Codex
repro): without this, a heartbeat blip would drop `ARM` while a motor relay bit was still latched
HIGH, then silently re-arm with the stale latch → **uncommanded motion**. The fix turns any RP2040
health loss into a latched, operator-acknowledged stop. (Note this is *belt-and-suspenders*: the
hardware rail has already dropped via `RP2040_OK`/condition 3 the instant the RP2040 went
unhealthy; this software trip ensures the FSM and operator state stay consistent so recovery is
clean.)

#### 19.4.4 FSM interlock model (default-off, secondary, unvalidated)

The FSM calls `io.interlock_ok()` before several energize paths, and the code model
returns false only for SC∧TB. On lanes 21/22 this does **not** represent a validated
field signal: TB has no independent harness landing, SC/U is not a dry input, and
the firmware feature is default-off. It receives no safety or diagnostic credit.
The authoritative guard is Candidate C's OEM parallel-safe S/T coil ladder, proven
at G3. The software default remains `True`; it must never be described as a physical
interlock echo until a separately reviewed sensing design is released and validated.

---

### 19.5 What each layer catches (summary matrix)

The lowest applicable layer is the guarantee; upper layers catch the same hazard earlier and keep
state consistent. "Rail" = `RELAY_ENABLE_RAIL` live? "Coils" = can any motion relay energize?

| Hazard / event | Caught by (lowest → highest) | Net effect on the rail |
|---|---|---|
| Loss of 115 VAC / operator hits Stop / actuates C.I.S. | **HW intended:** master breaker cuts all control power; **must be demand-proven per device** | machine dead (power removed, not just permission) |
| Table–sweep collision course | **HW:** OEM parallel-safe contacts both open with levers BACK; correct Candidate-C insertion blocks the commanded S/T coil. **FW/SW echo:** default-off/unvalidated, no credit | rail may stay live; affected machine coil must be dead |
| Pi process hangs / OS dies | **HW:** NE555 stops being kicked → Q13 off (cond. 1) | rail dead, coils drop |
| Pi de-asserts ARM (or enters MANUAL_INTERVENTION/FAULT) | **HW:** Q15 off (cond. 2), driven by **SW** power-down/fault logic | rail dead |
| RP2040 unpowered / reset / BOOTSEL | **HW:** GP2 Hi-Z → R110 holds Q16 off (cond. 3) | rail dead |
| RP2040 firmware loop hangs | **FW:** internal WDT (250 ms) resets chip → GP2 Hi-Z → cond. 3 off | rail dead |
| Motor commanded RUN and never STOPped | **FW:** max-run 8 s → `flt:motion_timeout` → GP2 LOW (cond. 3/4). **SW:** FSM motion-timeout → FAULT → ARM drop | rail dead |
| Stop-cam overrun (motor past its stop cam) | **Future measured release:** enabled v1.2.3+ path → GP2 LOW. Stock v1.2.3 flags OFF; covered only by the 8 s max-run | rail dead only after enabled path is qualified |
| RP2040 health blip mid-cycle | **HW:** cond. 3 drops instantly. **SW:** daemon full safety trip → motors off, latch MANUAL_INTERVENTION, require PBZ | rail dead; no stale-latch auto-resume |
| Power restored after an outage | **SW:** FSM comes up MANUAL_INTERVENTION; **HW:** ARM held low until operator First-Ball-Zero | rail dead until deliberate operator zero |
| Welded relay contact | **HW:** master breaker only — the rail drops the coil but cannot open a welded contact (§19.2.6) | rail dead, **but welded contact stays made → breaker required** |
| Motor runs but must brake | **HW:** OEM regenerative braking on the contactor NC contacts (§19.2.3) | independent of the board |
| Board powers up (pre-init) | **HW:** GP2 Hi-Z + ARM low + no kicks → all three gate conditions off | rail dead |
| Current lane-21/22 harness | J_SAFE3-4 OPEN/unlanded | **rail dead by design** |
| On-board conditions true after an approved 3–4 interface is installed | Q15·Q16·Q13 conduct; Candidate-C jumper + approved Stop/CIS source path closed | **rail live** — S/T machine coils still require the OEM ladder |

---

### 19.6 Why replacement motion-cam stops require measured controller paths

On the original AMF 82-70, the **cam-position stops are controller LOGIC**, not a hardwired
motor latch: the controller reads a cam edge and drops the relay (`docs/phase8_8270_SYSTEM_REFERENCE.md`
§5 — "Cam-position stops are controller LOGIC … not a hardwired motor latch"). Bench work on the
21/22 chassis (the Omega-Tek retrofit) confirmed the same thing the runbook records (§0): **the
OEM machine uses *logic* stops (on the triac board), not cams wired in series with the motors.**

The direct consequence: **removing the Omega-Tek/OEM controller removes the
ordinary motion-cam stop logic.** The replacement FSM must stop on independently
measured motion-cam events, and any credited RP2040 overrun backstop must use a
manifest-controlled, polarity-bound release. Stock v1.2.3 keeps those flags OFF.
This is why:

- cam-stop is condition 3/4 of the rail (an RP2040 responsibility), not a separate machine wire;
- the RP2040 cam-stop must be **bench-proven before cutover** (contract §12.9);
- the cutover **G3** safety-drop gate's cam-stop sub-test is a **hard gate** (§19.5; runbook §6
  Stage 6b / §7);
- and per-cam-edge enforcement receives no credit until polarity is field-confirmed,
  enabled in a new controlled release, and bench-proven (§19.3.4).

> **(VERIFY: SA/SB/TA1/TA2 edge→angle polarity.)** Capture each independently
> landed motion cam under the runbook procedure. Do not assume `f` is the physical
> trip and do not include SC/TB as two inputs: lane 21/22 has no independent TB
> lead. Stock v1.2.3 does not enable per-cam overrun.

---

### 19.7 The cutover G3 safety-drop gate

Because a controller cutover changes what *moves the machine* (unlike the read-only Track-A scoring
cutover, whose worst case is a wrong score), the controller cutover is gated on a fully
bench-validated unit and uses a **staged, rail-disabled** bring-up (runbook §0, §6, §7). The heart
of the procedure is **Go-gate G3** at Stage 6b. Prove every implemented on-board
drop, then separately prove Candidate C at the machine:

| G3 sub-test | Action | Expected | Status today |
|---|---|---|---|
| Watchdog | stop the Pi's NE555 kick | rail drops | testable with v1 firmware |
| Arm | de-assert `ARM_PERMIT` | rail drops | testable with v1 |
| RP2040 health | reset/halt the RP2040 | rail drops (GP2 → Hi-Z/LOW) | testable with v1 |
| Cam-stop | trigger each release-enabled, measured stop-cam edge while "running" | rail drops | **BLOCKED on stock v1.2.3**; needs measured polarity + new controlled release (§19.3.4/§19.6) |
| TB/SC interlock | board commands S, then T; force both levers BACK/open and meter each contactor coil | each coil dead even with board contact closed | **mandatory per lane; a J_SAFE rail-drop test is not a substitute** |
| J_SAFE3-4 source continuity | open the reviewed 3–4 interface | rail drops | **BLOCKED: current harness is OPEN/unlanded; bench-only jumper testing is not field proof** |
| Stop/CIS end-to-end | actuate Stop, then CIS separately | each action drops OEM master/control power and the board rail | **BLOCKED pending engineered 3–4 interface and guarded powered demand proof** |

**Pass condition (G3):** every implemented rail gate drops permission, both Candidate-C
coil tests are dead, and Stop and CIS each pass their separate end-to-end demand
proof. **Fail action: ABORT and
roll back to the OEM brain — do not "fix it live."** Any failure at or before the subsequent
**G4** (commanded S/T/SP each stop on cams; full reset completes and stops; no runaway) is also a
rollback (runbook §7, §8). The order is deliberate: capture cam polarity first
(Stage 2 / §3.2), generate and verify the new measured/enabled release, flash only
under the approved first-article plan, then run the cam-stop sub-test. This
gate is why the controller cutover is scheduled **only after** the RP2040 cam-stop and the full
rail are bench-proven (runbook §2, §11; contract §12.9).

---

### 19.8 Cross-references

- **§04 Machine I/O** and **§03 Machine Sequence** — the cams (SA/SB/SC/TA1/TA2/TB), the SS/DIELL
  ball trigger, and the cycle the FSM runs.
- **§07 RP2040 + MCP** — the controller devices, the authoritative fast-input pin map (GP6–GP13),
  `RP2040_OK` on GP2, and the UART.
- **§09 Relay Outputs** — the motion-relay output stage (G5LE-14 5 VDC, per-relay NPN drivers,
  snubber/MOV footprints) and the non-rail status-LED outputs.
- **§10 Watchdog + Rail (circuit reference)** — the NE555 monostable, the pass-FET + AND-chain
  schematic, every pin→net table, the Candidate-C J_SAFE1-2 source jumper +
  currently open/unlanded Stop/CIS J_SAFE3-4 source position, the relay-coil rail map, and the
  bench-bring-up probe list. **This section (19) is the consolidated model; §10 is the circuit
  detail.**
- **§11 Connector Pinouts** — `J_SAFETY` (J14) and `J_PI` (J1) pin assignments.
- **Design contract** `docs/phase8b_pcb_revB_spec.md` §4 (safety rail), §2/§3 (domains/outputs),
  §11 (assembly blockers), §12.9 (bench bring-up).
- **OEM reference** `docs/phase8_8270_SYSTEM_REFERENCE.md` §5 (the AMF safety model preserved).
- **Cutover runbook** `docs/phase8_trackB_controller_cutover_runbook.md` §0/§1 (safety model,
  LOTO), §6/§7 (staged bring-up + G3/G4 gates), §8 (rollback).
- **Firmware** `firmware/rp2040/README.md` (safety model), `config.h` (timings: `WDT_TIMEOUT_MS`
  250 ms, `MAX_MOTION_MS` 8000 ms, `BOOT_SETTLE_MS` 200 ms), `main.c` (`supervise()` /
  fail-safe-low `RP_OK`).
