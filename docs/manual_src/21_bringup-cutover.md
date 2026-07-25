## 21. Bring-up, Bench Validation & Cutover

This section covers how a fabricated, assembled Rev-B controller board goes from "boxed PCB" to "running a pinsetter on lanes 21/22 in production." It has three parts, in the order they happen:

1. **Off-machine bench bring-up** (§21.2) — power up and prove out one board on a workbench, nowhere near a machine. This is the gate that every board must pass before it is ever wired to a pinsetter.
2. **Track-B controller cutover** (§21.3) — replace the OEM 82-70 control brain at one lane pair with the Rev-B Pi controller. This is a controls swap on a machine that moves and bites; it is the highest-risk operation in the whole project.
3. **Track-A scoring go-live** (§21.4) — bring up camera-based auto-scoring. Separate from the controller swap, read-only with respect to the machine, and fully reversible.

> **Read first if you are new here.** A pinsetter is dangerous. The sweep, table, and pit mechanisms can cycle and crush a hand. "Powered but idle" is **not** safe — a desk action, a customer, or a stray cam edge can start a cycle. Every live procedure in this section is built around lockout/tagout and a non-bypassable hardware safety rail. Do not improvise. If anything looks wrong, the master breaker goes **OFF first, questions second.**
>
> **Current no-arm hold:** lane 21/22 J_SAFE3-4 is physically OPEN/unlanded. Never
> jumper it at the machine.
> Bench-only closure is permitted only with the machine disconnected and dummy loads.

The step-by-step detail lives in two runbooks; this section summarizes them, explains the *why*, and cross-links so you know which document to have open at the bench or the lane:

| document | what it is |
|---|---|
| `docs/phase8b_pcb_revB_spec.md` §12 | the electrical contract + the canonical bench bring-up sequence (the runbooks call this "spec §12.9") |
| `docs/phase8_trackB_controller_cutover_runbook.md` | the controller-swap run-of-show, deferred field-capture, go/no-go gates, rollback |
| `docs/phase8b_at_machine_fieldsheet.md` | the at-machine measurement session that locked the board's ratings (already complete) |
| `docs/phase8_trackA_golive_runbook.md` | the camera-scoring install + verify procedure |

Related manual sections referenced throughout: **§5 Rev-B Controller Board: Overview, Domains & Isolation**, **§6 Board Power**, **§7 RP2040 + MCP**, **§8 Opto Inputs**, **§9 Relay Outputs**, **§10 Safety Hardware: NE555 Watchdog + Relay-Enable Rail**, **§11 Connector Pinouts (J1-J14)**, **§12 Channel Maps**, **§13 Layout & Manufacturing Contract**, and **§14 Machine Interface: C1/C2A & the Adapter Harness**.

---

### 21.1 The one safety model you must hold in your head

Everything below depends on understanding the **relay-enable rail** and what it can and cannot do. This is the single most important concept in the section.

The Rev-B board never sources machine power. It only **opens and closes isolated dry relay contacts** that sit in series with the machine's *existing* control circuits. The heavy S/T contactors stay on the machine and keep switching the 115 VAC motors and their OEM braking behavior — the board only switches their coil circuits (all measured at ~24 VAC; see §14 and the fieldsheet). The board is therefore never the only safety device. OEM service-manual history describes parallel Stop and C.I.S. devices at the rear-panel master breaker, but physical inspection found **no C.I.S. device or wiring on pilot lanes 21/22**. Their installed final disconnect is Stop → master breaker. Whether another automatic pit-entry interlock exists is an open pre-motion question, not an assumed protection.

The board's own permission layer is `RELAY_ENABLE_RAIL` (TP16), but Candidate C
places TB/SC outside that rail: J_SAFE1-2 carries the controlled jumper and the OEM
parallel-safe ladder separately gates the S/T machine coils. The table retains the
PCB's named positions while identifying the released field implementation:

| # | condition | source on the board | fail-safe default | how it drops the rail |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 monostable (U36), Pi kicks `WDOG_KICK` (Pi GPIO 12) at < ~10 s | false (no kick → drop) | NE555 output gate (Q13 AO3400A) opens the rail's pull-down chain |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO, asserted only after operator-safe state (First-Ball-Zero) | false | NPN AND transistor Q15 (MMBT3904) in the gate chain |
| 3 | **RP2040 OK** | RP2040 (A1) `RP2040_OK` = GP2, heartbeat/permission | false (Hi-Z → 100k pulldown) | NPN AND transistor Q16 (MMBT3904) in the gate chain |
| 4 | **Enabled cam-stop OK** | qualified RP2040 cam-edge enforcement, when enabled in a controlled release | false on reset/fault | same path as #3 — an enabled enforcement fault pulls GP2 low; stock v1.2.3 measured-cam flags are OFF |
| 5 | **TB/SC board provision** | controlled Candidate-C jumper on J14 pins 1-2; no machine landing | keyed/labeled jumper only | closes the first source position; primary protection is the OEM ladder and G3 coil proof |
| 6 | **Reserved external control-power / optional pit-interlock source position** | future validated isolated dry-contact interface on J14 pins 3-4; **currently OPEN/unlanded** | open/false | deliberately prevents the field rail from arming |

Q14 is fed through the two J14 source positions in series:
`VCC_5V → J14.1 → [controlled Candidate-C jumper] → J14.2/J14.3 → [future approved isolated energize-to-prove control-power dry contact; optional approved pit-interlock contact in series; currently OPEN] → J14.4 → Q14`.
The separate OEM TB/SC contacts remain in each S/T coil circuit. TP16 can therefore
be live during a valid collision block; the corresponding S/T machine coil must
still be dead.

> **The welded-contact limit (memorize this).** The rail de-energizes relay *coils*. It **cannot open a contact that has welded shut.** Relay contact rating, arc suppression, and the upstream master breaker are what protect against a welded contact. This is why §21.2 includes a dummy-load test on every relay and why the master breaker is never the thing you skip.

Conditions 1, 2, and 3/4 are active on-board permissions. J_SAFE3-4 is a designed
connector permission but is not yet implemented in the field.
Candidate-C position 5 is the controlled jumper. Opening it tests PCB continuity
only; the **authoritative TB/SC G3 proof is machine-side**: command S, then T, force
both levers BACK/open, and require each contactor coil to remain dead.

The leading J_SAFE3-4 design is an externally mounted, correctly rated
energize-to-prove control-power relay whose isolated N.O. dry contact alone reaches
J14, optionally in series with an approved new pit-entry-interlock contact. A
J14-only pit switch is **permission gating**, not an upstream final disconnect; a
new personnel interlock must receive its own machine-safety review. The sensing
relay contact can weld or stick closed, so the guarded acceptance and periodic
proof must force control-power loss and verify both that contact and TP16 drop.
Sensed machine voltage and mains remain outside Rev-D.

---

### 21.2 Off-machine bench bring-up (spec §12 step 9)

**Purpose:** prove one assembled board is electrically sound and that every safety condition drops the rail, with **zero risk** — the board is on a bench, not on a machine. **No board is ever wired to a pinsetter until it has passed this whole sequence.** This is the gate the cutover runbook calls "spec §12.9" and lists as a hard prerequisite (G1).

**Where it is written:** `phase8b_pcb_revB_spec.md` §12 step 9 is the canonical ordered list. This subsection explains each step and what "pass" looks like.

#### 21.2.0 Assembly state before you start

The board arrives as a JLCPCB fab/assembly package (`kicad/fab_revB_routed_manual/`). Understand what is and isn't populated:

- **Populated by JLCPCB Standard-PCBA (SMT + wave-solderable THT):** the 3× MCP23017 (U1/U2/U3), 32× PC817B optos (U4-U35), NE555 (U36), all relay drivers/FETs (Q1-Q6 MMBT3904, Q8-Q11 2N7002, Q12/Q13 AO3400A, Q14 AO3401A, Q15/Q16 MMBT3904), the 6 populated relays (K1-K6), and the passives — **20 sourcing lines** (`jlc-standard-pcba-bom.csv`).
- **Hand-soldered on arrival (NOT placed by JLC):** the RP2040 Pico module (**A1**), the TMA-0505S isolated field supply (**U37**), and the board-side connectors **J1 (2×10 IDC) + J2-J11, J13, J14 (Phoenix)** (`hand-solder-bom.csv`). **U37 must be fitted before any isolated field-wetting / input test** (no U37 → no `FIELD_WET_V`), and **A1 before there is any `VCC_3V3`** (§6).
- **NOT populated — DNP, on purpose:** the entire **M1 (ball-return) channel** — relay **K7**, driver **Q7**, resistors R85/R86/R87, diode D13, snubber/MOV footprints — plus all motion-output **snubbers and MOVs** (C4-C10 10nF X2, D2/D4/D6/D8/D10/D12/D14 MOVs, R69-R84 100R). These are populate-*after*-characterization footprints. See `dnp-excluded.csv` and §13. Do not populate M1 or any snubber/MOV without an explicit release decision (spec §11 items 1, 2, 6).
- **Off-board parts you supply:** the regulated 5 V supply, the Phoenix MC mating plugs for J3/J4/J5/J13/J14, the 2x10 IDC ribbon for J1, and M3 mounting hardware (`harness-mating-parts.csv`, `offboard-hardware.csv`).

> **Phoenix terminal note (resolved):** the locked order split puts **all board-side connectors in the hand-solder set** — J1 (2×10 IDC, a CNC Tech candidate, **not** Phoenix) plus the Phoenix terminal blocks/headers **J2-J11, J13, J14** are hand-soldered on arrival, **not** placed by JLC (`hand-solder-bom.csv`). **J12 (M1 motion output) stays DNP.** The earlier "does the house place the Phoenix headers?" question is closed: it does not — you hand-solder them.

#### 21.2.1 The bench bring-up sequence, step by step

Do these **in order**. Each step gates the next. Keep a bench log. Use the test points (§21.2.2) as your meter taps.

| step | action | pass criterion | if it fails |
|---|---|---|---|
| 1. **Power rails** | Apply regulated 5 V to **J2 (`J_PWR`)** pin 1 (`VCC_5V_RAW`), GND on pins 2-3. The on-board reverse-polarity Schottky **D17 (SS14)** feeds `VCC_5V`. | TP1 (`VCC_5V`) ≈ 5 V. TP3 (`VCC_3V3`) ≈ 3.3 V (the Pico's on-board regulator supplies 3V3 — see §6/§7). TP4 (`FIELD_WET_V`) ≈ 5 V isolated (from U37 TMA-0505S). No part hot. | Check D17 orientation, U37, short on a rail. Do not proceed. |
| 2. **I²C enumerate** | With the Pi connected via **J1 (`J_PI`)**, scan the board's I²C bus. | All **3× MCP23017** answer at **0x20 (U1, IN-A), 0x21 (U2, IN-B), 0x22 (U3, OUT-A)**. (Addresses set by A2/A1/A0 strapping — see §7/§12.) | Re-check I²C pull-ups R1/R2 (4.7k to 3V3), address straps, solder on the SOIC-28W parts. |
| 3. **RP2040 boot + identity + heartbeat** | Verify and flash only the controlled Rev-D release artifact (`firmware/rp2040/release.ps1 -VerifyOnly`; current bundle reports `phase8b-rp2040 v1.2.3`) when the first-article plan authorizes flashing; power up. | The manifest-bound `id` fields match the verified release tuple, then `hb` lines arrive every 250 ms. After the 200 ms boot-settle, `RP2040_OK` (GP2, TP14) goes HIGH only if healthy. **A version string alone is not image proof.** | Check the Pico solder, UART wiring (Pi TX→GP1, Pico GP0→Pi RX), release identity, and `BOOT_SETTLE_MS`. |
| 4. **Watchdog drop** | With the rail armed on the bench-safe path, **stop kicking** `WDOG_KICK` (Pi GPIO 12). | After the NE555 timeout (~10 s — the Pi normally kicks well inside this), the rail (TP16) drops. Observe at TP11 (`NE555_OUT`), TP12 (`WDOG_OK_PULLDOWN`). | Verify the NE555 timing network (R_WDOG_TIMING 100k, C_WDOG_TIMING 100µF/16V = C11), the trig pull-up (R_WDOG_TRIG_PULLUP 10k — the "Rev-A trigger pull-up fix"), Q13. |
| 5. **Arm drop** | De-assert the Pi `ARM_PERMIT` GPIO (J1 pin 8). | Rail (TP16) drops. TP13 (`ARM_PERMIT`) reads low. | Check Q15 (AND ARM) and its base network (Rb 10k / Rpd 100k). |
| 6. **J14 source-position drops (off-machine bench only)** | With the machine disconnected and only dummy loads, open J_SAFE1-2, then the controlled bench-only J_SAFE3-4 jumper. On lanes 21/22, 1-2 is the Candidate-C jumper — **not** a TB/SC field loop. Remove the 3-4 bench jumper before machine connection. | Rail (TP16) drops when either board source position opens. This validates PCB/source wiring only; it proves neither the OEM collision guard nor upstream Stop-to-breaker operation. | Check the controlled 1-2 jumper and Q14. Current production 3-4 leads are OPEN/CUT+LABEL-ONLY. Prove TB/SC separately at G3. After an engineered interface exists, demand Stop end-to-end; record C.I.S. as **N/A — device absent**; separately test any identified/new pit-entry interlock. |
| 7. **Each relay with a dummy load** | Re-establish all rail conditions. Command each motion relay **(S, T, SP, BE, M, M2)** in turn through OUT-A (U3). Put a **dummy load** (a lamp or resistor sized to the expected ~24 VAC coil-circuit current) across the relay's J6-J11 contact pair. | Each relay clicks, its COM-NO contact closes the dummy load, and the load drops the instant you drop the rail. Probe coil-drive, COM, NO per the test-pad rule (§9, spec §3.2). **M1 (K7/J12) is DNP — not tested.** | Check the relay driver (Q1-Q6), `RELAY_ENABLE_RAIL` reaching the coil, the flyback diode. |
| 8. **Input front-ends** | Exercise each opto input. For **fast** inputs (SA/SB/SC/TA1/TA2/TB/DIELL-L/DIELL-R) wet the J3 (`J_FAST_IN`) field pin to `FIELD_GND`; for **slow** inputs (GS1-10, GP/OS/BS/PBZ/PBC/Foul on J4, and 10th/manual/AUX on J5) do the same. | The corresponding RP2040 fast-input edge (cam/ball event over UART) or MCP23017 bit flips. Optos are **active-low** at the logic pin: a closed field contact pulls the input LOW (§8, §12). On Rev-D, also prove RP2040 pulls are off and U1/U2 `GPPUA/GPPUB=0x00` read back exactly. | Check the PC817, the input resistor (`Rin` 2k2), the current Rev-D/R5 logic pull-up (`Rpu_*` **47 kΩ** to 3V3), and `FIELD_WET_V`. An internal pull enabled or a missing external `Rpu_*` is STOP-SHIP. |
| 9. **Cam-stop rail drop** | Drive a cam-stop condition on the RP2040 and confirm it pulls the rail. | `RP2040_OK` (GP2/TP14) goes low → rail (TP16) drops. **See the firmware caveat below.** | This is condition #4 — it shares the GP2 path with #3. |
| 10. **(only then) machine-harness test** | Everything above passed. The board is cleared to be wired to a machine — which is the cutover (§21.3), **not** part of bench bring-up. | — | — |

**Pass = all of steps 1-9 green, logged.** Only then does the board become a candidate for the controller cutover (this is gate **G1**). Build the spare unit #2 the same way.

> ⚠️ **Firmware caveat for step 9 (read carefully).** The controlled Rev-D-only
> firmware bundle is **v1.2.3**, not yet flashed, and every measured-cam enforcement
> flag ships **OFF**. The code contains the cam-stop paths, but stock release behavior
> credits only health plus the 8 s motion max-run backstop. At the bench, prove the
> max-run drop and the GP2→rail path. A true per-cam-edge drop may be credited only
> after edge→angle polarity is measured, enabled in a **new controlled release**, and
> that release passes its dedicated bench test. The SC∧TB echo remains default-off,
> secondary, unvalidated, and unusable on lanes 21/22 without an independent TB lead.

#### 21.2.2 Test points (your bench meter taps)

The board carries 16 test pads (1.5×1.5 mm), excluded from BOM/POS but present in copper. Use these instead of probing IC legs:

| TP | net | what it tells you |
|---|---|---|
| TP1 | `VCC_5V` | 5 V logic/relay-coil rail present |
| TP2 | `GND` | logic ground reference |
| TP3 | `VCC_3V3` | Pico-sourced 3.3 V (MCP/opto-logic rail) |
| TP4 | `FIELD_WET_V` | isolated field-wetting supply (U37 output) |
| TP5 | `FIELD_GND` | isolated field ground (must share **0 nodes** with GND — isolation proof) |
| TP6 | `I2C_SDA` | I²C data |
| TP7 | `I2C_SCL` | I²C clock |
| TP8 | `WDOG_KICK` | Pi kick pulse into the NE555 |
| TP9 | `WDOG_TIMING_NODE` | NE555 RC timing node |
| TP10 | `NE555_TRIG` | NE555 trigger (watch the Rev-A pull-up fix) |
| TP11 | `NE555_OUT` | NE555 output (watchdog-OK before the gate) |
| TP12 | `WDOG_OK_PULLDOWN` | watchdog contribution to the AND chain |
| TP13 | `ARM_PERMIT` | Pi arm permission |
| TP14 | `RP2040_OK` | RP2040 health/cam-stop permission (GP2) |
| TP15 | `SAFE_STOP_RETURN` | pass-FET source return after both J14 positions; current field harness is dead here because 3–4 is OPEN |
| **TP16** | **`RELAY_ENABLE_RAIL`** | **the rail itself — the single most useful tap; if this is dead, no motion relay can energize** |

#### 21.2.3 Board facts an electrician needs at the bench

| fact | value | source |
|---|---|---|
| Board size | **250 × 225 mm**, 1.6 mm thick | board-stats.txt, spec |
| Copper layers | **4** | spec §1/§9 |
| One board = | one lane; a pair = two identical boards on one Pi (independent I²C bus + RP2040 each) | spec §1, channel-alloc §0 |
| Logic / coil supply | regulated **5 V** into J2 | spec §8.1 |
| MCP/opto-logic rail | **3.3 V** (Pico-sourced) — MCPs are I²C and **3.3 V**, Pi-safe | netlist `block_mcp`, §7 |
| Isolated field wetting | **U37 TMA-0505S** 5→5 V 1 W, isolated from logic ground | netlist `block_supplies`, offboard-hw.csv |
| Min track clearance / width | 0.2875 mm / 0.250 mm (board); custom rules enforce LOGIC↔FIELD ≥2.5 mm, LOGIC↔MACHINE ≥3.2 mm, output↔output ≥1.5 mm | board-stats, spec §9/§13 |

---

### 21.3 Track-B controller cutover at lanes 21/22

**Purpose:** replace the OEM 82-70 control brain at lanes 21 + 22 — the **Omega-Tek Omniboard + its S2003LS2 triac driver bank + the Siemens/ice-cube control relays** — with the Rev-B Pi controller (one board per lane, two boards on one Pi). After cutover, **cam timing, cam-stops, the cycle, masking, ball-state, and status indication come from the Pi/RP2040**, not the OEM controller. Scoring already comes from the camera (Track A), brought up first on a separate visit.

**Where it is written:** the full run-of-show, the field-capture worksheets, the gates, and rollback are in `phase8_trackB_controller_cutover_runbook.md`. **Have that document open at the lane.** This subsection is the orientation + summary; do not run the cutover from this section alone.

**Chassis scope:** lanes 21/22 are an **SS chassis + Omega-Tek retrofit**. The **board is common to the whole fleet; the harness and input populations are per-chassis.** Lanes 11/12 (Active-98 MP) need their own short field pass before their harness — see §21.3.7 and §14.

#### 21.3.1 Why this is the dangerous one

| | Track-A scoring (§21.4) | **Track-B controller (this subsection)** |
|---|---|---|
| What it replaces | QubicaAMF scoring overlay (BCU/QBK/T-VISION/VDB) | the 82-70 control brain (Omega-Tek + driver bank) |
| Machine motion | OEM controller still runs the pinsetter | **the Pi/RP2040 now runs the pinsetter** |
| Worst-case failure | a wrong score (read-only) | **uncommanded or unstopped machine motion** |
| Blast radius | low — auto-falls back to manual | **HIGH — a controls swap on a machine that moves and bites** |
| Reversibility | lift wires, ~15 min | re-plug the OEM brain, ~20-40 min |

Because the blast radius is motion, the cutover is **gated on a fully bench-validated unit** (§21.2 / G1) and uses a **staged, rail-disabled bring-up**. You never go straight from "harness landed" to "auto motion." The safety-rail drop tests (Stage 6 / gate **G3**) are the heart of the procedure — if any rail condition fails to drop motion, you **ABORT**; you do not "fix it live."

A critical consequence of removing the Omega-Tek board: the ordinary motion
cam-stops were controller logic, not hardwired motor latches. Removing the OEM brain
therefore requires the replacement FSM stop behavior **and** any credited RP2040
cam-edge backstop to be measured and proven before cutover. Stock v1.2.3 keeps those
cam-edge enforcement flags OFF, so a newly controlled, polarity-bound release is a
hard prerequisite before that sub-gate can pass. This is separate from the preserved
OEM SC/TB collision ladder and its Candidate-C G3 coil-drop proof.

#### 21.3.2 Lockout/tagout — the operating discipline

There are only **two modes** during the whole cutover:

- **(A) LOCKED OUT** — master breaker **OFF**, breaker tagged, **verified 0 V** on the coil circuits before hands go in. The 24 VAC coil rail can hold charge — wait ~30 s and verify. **All capture work, all harness landing, all hand-actuation happens here.** This is *most* of the cutover.
- **(B) DELIBERATE LIVE** — powered, only for the explicitly-marked staged-motion steps. The machine moves **only on a command you and your helper both expect** — never because of a customer.

Non-negotiables: lane formally **out of service, off-hours only**; **two people** for every live step (one at the controls/meter, one at the master breaker/e-stop); **body stays OUT of the sweep/table/pit travel path whenever powered** — if a mechanism must be rotated, rotate it **by hand, locked out**; **lift, don't cut** every machine wire (this is what makes rollback possible); if anything feels wrong, **master breaker OFF first, ask second.**

#### 21.3.3 The deferred field-capture items (the reason the runbook exists)

A set of facts remain easier to capture with the machine apart. For SC/TB, however,
topology and polarity are already resolved by powered evidence: **parallel
closed-when-safe**, both levers BACK/open blocks S/T. What remains is not a J14
terminal search; it is the per-lane board-output insertion proof. The other
unmeasured cam cavities/classes/polarities remain explicit cutover captures.

> **Live feed = your meter.** With the harness landed on the inputs (J3/J4/J5) but the **rail still disabled** (no motion possible), the Pi reads every input over the daemon (`journalctl -u lane-node -f` shows input-bank reads). So most capture is "actuate the thing by hand, locked out, and watch which channel flips in the log."

The deferred items (full method per item in runbook §3, worksheets in runbook Appendix B):

| item | runbook ref | what you capture | how |
|---|---|---|---|
| **Per-gripper GS# → C2A cavity** | §3.1 | which physical gripper maps to GS1…GS10 (the *bank* and polarity are already locked: gripped = CLOSED to **chassis** ground) | lift one pin / actuate one gripper at a time, watch which `GS` channel deasserts in the live feed; set the result in `controller_io.py` GS map (software only) |
| **Per-cam SA/SB/TA1/TA2 → C2A cavity + trip angle** | §3.2 | which motion cam fires which valid fast input at which angle | powered/locked-out procedure per runbook. **SC/U stays CUT+LABEL-ONLY; TB is NO-LEAD on lanes 21/22.** |
| **C1/C2A output cavity confirm** | §3.3 | confirm the measured output cavities on *this* in-place machine before landing J6-J11 | land-check against the spare-cabinet measurements (table below) |
| **TB/SC Candidate-C proof** | §3.4 / G3 | verify board S/T contacts did not bypass the OEM ladder | install only the controlled J_SAFE1-2 jumper; live, body clear, command S then T and force both levers BACK/open → each coil dead |
| **Installed Stop/master chain + pit-entry disposition** | §3.5 | prove pilot Stop operation; record C.I.S. **N/A — device absent**; inspect/ask the mechanic whether another pit-entry interlock exists; close the new-interlock-versus-explicit-safety-decision gate; review the external energize-to-prove control-power dry interface for the currently OPEN J14 pins 3-4 | locked-out source-position continuity is only a preliminary check. Under the guarded powered procedure, Stop must drop OEM master/control power and TP16. Separately demand-test any identified/new pit interlock. Only isolated dry contacts reach J14; mains stays outside Rev-D. |
| **M1 ball-return existence** | §3.6 | whether ball-return is a separate command on this chassis | if yes → future rev-C populate; **for this cutover M1 stays DNP and unharnessed** |

Output cavity land-check (measured on the spare cabinet; **confirm on the in-place machine** before landing — runbook §3.3):

| output | function | machine connector + cavities (measured on spare) | board terminal |
|---|---|---|---|
| S | sweep contactor coil ckt | **C1: C, D, N, T** | J6 (K1) |
| T | table contactor coil ckt | **C1: A, K, H, E (+L @55Ω through-coil)** | J7 (K2) |
| SP | spot solenoid ckt | **C2A** (0 Ω direct) | J8 (K3) |
| BE | back-end | **straddles C1 (KK,C,L) + coil FF@66Ω; also C2A** | J9 (K4) |
| M | master/control | **C2A** (FF/U/B) | J10 (K5) |
| M2 | sweep-reverse | **C2A** (0 Ω) — **preserve the Expander interlock / shorting-plug function**, not just the cavity | J11 (K6) |
| M1 | ball-return | **DNP — NOT harnessed** | J12 (K7) DNP |

> The board terminal column (J6→S, J7→T, J8→SP, J9→BE, J10→M, J11→M2) is the as-fabricated J_MOTION assignment from the routed board and silkscreen. Outputs span **both** C1 (S, T) and C2A (SP, M, M2; BE straddles), so the harness needs leads to **both** machine connectors. The board switches the coil circuit only — it does not supply the ~24 VAC coil power. The per-chassis adapter-harness map (function-named board → C1/C2A) is the table in runbook §4; the full machine-side connector theory is in **§14**.

#### 21.3.4 The staged, rail-disabled bring-up (run-of-show summary)

Budget ~2-3 h for the first pair. Stages, summarized from runbook §6 — **run them from the runbook, not from here**:

| stage | mode | what happens | gate |
|---|---|---|---|
| 0. Arrival + photos | — | verify 21+22 out of service; **photograph the OEM brain as-found** (every connector, the C1/C2A faces with the pin-1 datum) — this is your rollback reference; confirm the Pi node registers at the server | — |
| 1. **Lockout** | A | master breaker OFF, tag, wait 30 s, **verify 0 V** on the coil circuits | — |
| 2. Field capture (§21.3.3) | A | work the deferred items, fill Appendix-B worksheets — most of the window, all cold/hand-actuated | **G2** |
| 3. Install mask LEDs | A | fit the L_FIRST/SECOND/STRIKE/FOUL LEDs into the mask housings, run J13 (`J_LAMP_LED`: 5 V, GND, 4 returns). **Leave the OEM 15 VDC mask-lamp wiring physically intact** (lift, don't cut) for clean rollback | — |
| 4. Disconnect the OEM brain | A | **unplug** the Omega-Tek board + triac driver bank + connectors. **Do not cut anything.** Bag/label each OEM connector; shelve the brain at the cabinet — it is your rollback | — |
| 5. Land the adapter harness | A | follow the current runbook/build sheet: J6/J7 output insertion must preserve the OEM ladder; J_SAFE1-2 gets only the controlled jumper; **J_SAFE3-4 stays OPEN/CUT+LABEL-ONLY until the separately reviewed external energize-to-prove control-power dry-contact interface is approved**; an approved new pit-interlock dry contact may be placed in series. TB gets NO-LEAD and SC/U stays unlanded pending reviewed sensing. Never jumper 3-4 at the machine and never route machine voltage or mains onto Rev-D. Torque, tug-test, and photograph every landing. | — |
| 6. **Logic-only bring-up + on-board drops; then Candidate-C G3 proof** | A, followed only by the runbook's explicit deliberate-live proof | breaker OFF for logic/input checks and on-board drop tests. Then use the runbook's guarded powered procedure to prove both board-commanded S/T coils are dead with both levers BACK/open. | **G3** |
| 7. **First commanded motion** | **B — DELIBERATE LIVE** | two people, body clear, hand on the breaker. Breaker ON, arm. Command **SP alone** (spot fires, no sweep/table). Command **one sweep (S)** and one table (T) → verify the FSM stops on the measured SA/TA events and that the separately qualified RP2040 overrun backstop is armed as declared by the release posture. Command **one full reset cycle** → completes and stops cleanly, no overrun. | **G4** |
| 8. Ball cycle + scoring | B | roll a ball down each lane: DIELL fires → FSM cycles the pinsetter (cam-timed) → camera scores (Track A) → display updates. Confirm detected standing pins match the deck across a few leave types, both lanes | **G5** |
| 9. Soak handoff | — | brief night staff ("21+22 are on the new Pi controller… if anything looks wrong, leave the lane closed, photograph it, message Dylan — do not try to fix it"); tape a contact note inside the cabinet; leave the OEM brain shelved + all wire labels on for the first soak week | — |

**Stage 6/G3 tests.** Prove each implemented on-board drop, then prove Candidate C separately:

1. stop the watchdog kick → rail drops
2. de-assert arm → rail drops
3. reset/halt the RP2040 → rail drops
4. trigger each **enabled, measured** cam-stop edge → rail drops. Stock v1.2.3
   cannot pass this sub-test because every measured-cam flag is OFF; first capture
   polarity, create/verify a new controlled release, and prove its declared posture.
5. open J_SAFE1-2 → rail drops (**PCB-position test only; not TB/SC proof**)
6. after the engineered J_SAFE3-4 interface is approved and installed, open that
   interface → rail drops (**board/source-position proof only**); then actuate Stop
   → OEM master/control power and the rail both drop. Record C.I.S. as **N/A —
   device absent** on lanes 21/22. Separately demand-test any identified or newly
   installed pit-entry interlock.
7. with the board commanding **S**, then **T**, force both TB/SC levers BACK/open → each corresponding machine coil remains dead even though the board contact is closed

**Every implemented rail drop and both Candidate-C coil tests must pass. Any failure → ABORT + rollback.**

#### 21.3.5 Go / No-Go gates

| gate | when | pass condition | fail action |
|---|---|---|---|
| **G1** | before scheduling | unit bench-validated (§21.2, spec §12 step 9, all steps) · FA-13/FA-14 passed · firmware proven · signed per-lane commissioning evidence accepted by the operations latch and bound to exact lane/Pico/board/harness identity, with a matching controller-originated live observation **≤90 s old** and proof age **≤365 days** · Track-A scoring soaked clean · spare on hand · OEM brain photographed | don't schedule |
| **G2** | after Stage 2 | all required field items captured; controlled J_SAFE1-2 jumper and S/T insertion points match the build sheet; a reviewed external energize-to-prove control-power J_SAFE3-4 interface exists; Stop demand proof is planned; C.I.S. is explicitly recorded **N/A — device absent**; the mechanic/physical pit-interlock survey is recorded; and, if none exists, the new-interlock-versus-explicit-owner-and-qualified-safety-decision is closed. A qualified electrician has separately recorded protective-earth/bonding and hot/neutral-polarity results from an appropriately listed external tester | resolve or abort; **no motion while any item is open** |
| **G3** | Stage 6 | watchdog, arm, RP2040, and every release-enabled measured cam-stop drop the rail; J_SAFE3-4 source opening drops the rail; a forced control-power loss proves the energize-to-prove contact is not stuck closed and TP16 drops; Stop drops OEM master/control power and the rail; any identified/new pit-entry interlock passes its separate demand test; C.I.S. remains recorded N/A on 21/22; board-commanded S and T are proved separately dead with both levers BACK/open; only the controlled J_SAFE1-2 jumper is present; exact evidence is captured in the signed commissioning latch, whose live controller identity must be **≤90 s old** and whose FA-13/FA-14 proof must be **≤365 days old** | **ABORT → rollback** |
| **G4** | Stage 7 | commanded S/T/SP each stop on cams; full reset completes + stops; no runaway | **breaker OFF → rollback** |
| **G5** | Stage 8 | ball cycle + correct score across a few balls/leaves, both lanes | flip scoring to manual (§21.4 Step 7); controller stays if G3/G4 passed |

**Rule:** any failure at or before **G4 = rollback to the OEM brain.** Do **not** debug machine motion live.

#### 21.3.6 Rollback (reconnect the OEM brain)

Trigger: any G3/G4 failure, or a Stage-7/8 fault that isn't a trivial single-wire fix. Budget ~20-40 min (longer than a scoring rollback because you re-plug the brain — practice it in the Stage-5 dry run). Summary (full steps in runbook §8):

1. **Master breaker OFF, lockout, verify 0 V.**
2. **Lift the adapter harness** from C1/C2A and the reviewed external control-power / optional pit-interlock interface; remove the labeled J_SAFE plug/output taps per the build sheet (TB/SC itself was never landed on J_SAFE; if rollback occurs before a 3–4 interface is approved, those leads remain OPEN).
3. **Re-plug the OEM Omega-Tek board + triac driver bank + connectors** (preserved from Stage 4).
4. Mask LEDs (J13) can stay unpowered (harmless); the OEM 15 VDC mask wiring was left intact, so OEM lamps work on re-plug.
5. **Master breaker ON.** OEM controller runs the machine. **Bowl a frame on each lane** to confirm normal operation.
6. Leave the Rev-B enclosure powered down + in place (harmless); take the unit home to debug.
7. **Document the failure** (which gate/stage, observed behavior, suspected cause) in a `project_phase8b_cutover_attempt_N.md` memory.

#### 21.3.7 First-week soak and per-chassis rollout

Daily for 7-10 days (runbook §9): check `/api/health` on the server (node connected, no excessive disconnects); WSL-SRV log clean (no `lane_node_server.py` errors, no protocol mismatch); **walk 21+22 during open hours** watching real cycles (cam-stops crisp, no overrun, reset completes, scoring agrees); **cam-stop / watchdog timeouts in the journal must be ZERO** — any timeout is investigated before it recurs; touch the Pi case + boards days 1-3 (warm, not hot). After 7-10 clean days → a cleanup visit (tidy wire routing; decide whether the OEM brain is permanently retired or stays shelved as a spare), then the next chassis.

**Per-chassis caveat:** the board is fleet-common; the harness/input populations are
per chassis. For 11/12, re-capture cavities, input forms, gripper return, and the
TB/SC observable/landing facts; do not assume lane 21/22's no-independent-TB result.
Whatever Candidate-C insertion is selected must pass that lane's S/T G3 proof.

> **Server IP note.** The Track-B runbook (as written) points the Pi node and health checks at `192.168.86.36`. **That IP is dead** — WSL-SRV was re-IP'd to **192.168.4.103** in the 2026-06-03 eero router swap, and the DHCP reservation is still TODO, so the address could move again. Before the cutover window, **confirm the current WSL-SRV IP, reserve it on the eero, and set `WSL_LANE_SERVER_URL=ws://<current-IP>:8765`** on the `lane-node` service. The Track-A runbook (§21.4) already reflects `.4.103`. (VERIFY: the live WSL-SRV IP on cutover day — re-confirm the eero reservation before relying on any hard-coded address.)

---

### 21.4 Track-A scoring go-live (separate, reversible)

**Purpose:** turn the finished, tested camera-scoring code into a live auto-scoring pilot on lanes 21 & 22. This is an **install + verify** procedure — no coding. It is brought up **first and on a separate visit** from the controller cutover, so that the cutover only changes the controller, not scoring too.

**Where it is written:** `phase8_trackA_golive_runbook.md`. Time: ~30-45 min during a slow period.

**Blast radius:** scoring is **read-only** with respect to the machine — the existing controller (OEM brain *or*, post-cutover, the Rev-B board) still runs the pinsetter. **The worst case is a wrong score, never a machine action**, and the code **auto-falls-back to manual desk scoring** on any failure. You can abort to manual instantly (Step 7). This is why Track A goes live months ahead of, and independently of, the Track-B controller work.

#### 21.4.1 How camera scoring works (theory)

A QubicaAMF overhead **T-Camera** views the deck. Its composite video is tapped (Brown = video / Blue = gnd — the proven tap) into a **VIXLW USB capture dongle** on the Pi. The detector (`lane_node/pin_detect.py` + `camera.py`) compares each ball's settled frame to a **per-lane "empty deck" reference image** captured from this exact camera, and decides which of the 20 pin-spots (10 per lane) are still standing — a **difference-from-empty** method. The result is a 10-bit standing-pin mask per lane, emitted as a `ball_event` to the server, which drives the overhead scoring display. The camera may be **shared by the pair**; this is the one truly shared part (everything wired to the machine is per-lane). Full detector theory is covered in the scoring section of this manual (the camera-scoring / pin-detection section). (VERIFY: the exact manual section number for the camera-scoring chapter — sections 15-20 are being authored separately; cross-reference by topic until the number is fixed.)

#### 21.4.2 Go-live sequence (summary)

Run from the runbook; summarized here:

| step | action | the "must-do" / pass criterion |
|---|---|---|
| Pre-flight | on the Pi, `git pull` (gets `camera.py`, rewired `lane_node.py`, calibrated `pin_detect.py`); confirm deps (`numpy`, `PIL`, `av`); confirm `lane_node_server.py` is up on WSL-SRV (`curl http://192.168.4.103:8766/api/health`) | both files exist; health returns JSON with the connected node |
| 1. Verify capture feed | confirm the Pi enumerates the VIXLW dongle (`ls -l /dev/video*`, `v4l2-ctl --list-devices`) | at least `/dev/video0`; the device index = `WSL_LANE_CAMERA_DEVICE`. **Black/no frame later = missing video ground** (RCA shell→Blue), not a code bug |
| 2. **Capture per-lane EMPTY reference** ⭐ | clear BOTH decks, then `camera.py --capture-empty` → saves `lane_node/empty_ref.png` (720×576, gitignored per-Pi) | a real empty-deck image, both decks, no pins, normal lighting — **the one must-do step** |
| 3. Dry-run detector | set known racks, `camera.py --test` | full rack → mask 1023; empty → 0; a 7-pin → bit 6 set. **This step is the real go/no-go** |
| 4. Measure settle window | watch a few balls; note time from "ball hits pins" to "pins stopped, sweep not yet down" | tune `WSL_LANE_CAMERA_SETTLE_S` (default **2.5 s**) |
| 5. Start node in CAMERA mode | `systemctl edit lane-node` → set `WSL_LANE_SCORING_MODE=camera` (and settle/device/server URL as needed); restart; watch the log | startup log shows `Camera ready for lanes [21, 22]`. If `Camera mode but detector NOT ready` → empty ref didn't load (redo Step 2) — **lane still runs, just falls back to manual** |
| 6. Watch it score a real ball | open `http://192.168.4.103:8766/display?lane=21` (and `?lane=22`); throw ~10 balls across leave types | log shows `ball detected` → `camera pin_mask=…` → `ball_event`; display updates; detected standing pins match the deck |
| 7. **Abort to manual (instant)** | `systemctl edit lane-node` → `WSL_LANE_SCORING_MODE=manual`; restart (or Ctrl-C the foreground daemon and relaunch without the env var) | **no machine impact either way** — manual mode emits the ball event without a pin_mask; the desk scores via the existing flow |
| 8. Soak + tune | run camera mode through real play; keep a detected-vs-actual tally | a clean week of agreement before calling Track A "soaked" |

#### 21.4.3 Scoring env vars and endpoints (quick reference)

Env vars on the `lane-node` service:

| var | default | meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | seconds after DIELL before grabbing the frame |
| `WSL_LANE_CAMERA_DEVICE` | `0` | capture device index (`/dev/videoN`) |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks (**bench only; never on a live lane**) |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | the WSL-SRV server (`ws://192.168.4.103:8765`) |

Endpoints:

| url | use |
|---|---|
| `http://192.168.4.103:8766/display?lane=N` | scoring display for lane N |
| `http://192.168.4.103:8766/api/lane/N/scoring` | scoring JSON (display polls this) |
| `http://192.168.4.103:8766/api/health` | server + connected-node health |
| `POST /api/lane/N/score` `{pin_mask, foul?}` | manual desk score / correction (always available) |

Common failures: `detector NOT ready` → empty_ref.png missing (redo Step 2); `--test` all-black or mask stuck at 0/1023 → video ground (reseat the RCA shell→Blue tap); no `/dev/video0` → dongle not enumerated (reseat USB, check `dmesg`); scores wrong but consistent → spot/threshold calibration (send tallies + frames to whoever maintains the detector — pins 2 & 3 are the homography-predicted ones, the right deck is more oblique); lane "went dark" after reboot → **service not `systemctl enable`d** (the recurring "lane goes dark after a power event" trap — every Pi node must be `systemctl enable lane-node`).

---

### 21.5 Sequence at a glance (where this sits in the project)

The strict order — nothing below is optional, and each gates the next:

1. **Generate the bare-PCB fab package** (`kicad/fab_revB_routed_manual/`) → vendor Gerber/drill upload preview → **fab order**.
2. **Assemble** with the DNP parts held out (M1 channel K7/Q7/J12, all snubbers/MOVs) — see §13 and `dnp-excluded.csv`. Hand-solder the Phoenix terminals and the Pico if the house doesn't place them.
3. **RP2040 firmware + daemon bench bring-up:** verify the controlled v1.2.3
   Rev-D-only bundle and its identity, but do not credit or flash it outside the
   first-article plan. Capture cam polarity, then create a new controlled release
   with only the measured enforcement flags enabled and pass its bench gate.
4. **Full board bench validation** — §21.2 / spec §12 step 9, every step green. **(Gate G1.)**
5. Build the **spare unit #2** the same way.
6. **Track-A scoring** live + soaked clean on 21/22 (§21.4) — *before* the controller cutover, on a separate visit.
7. **Track-B controller cutover** on 21/22 (§21.3) — staged, rail-disabled, gates G2-G5, rollback ready.
8. **7-10 day soak** → cleanup visit → next chassis (11/12, with its own field pass).

There is no external deadline — the Phase-8 thesis is "do it once, do it right." A bad first controller cutover poisons the soak and the per-chassis rollout, which is why the bench-validation and safety-drop gates are absolute.

---

#### Cross-reference index for this section

| topic | see |
|---|---|
| Board domains, isolation, the three electrical domains | §5 |
| Board power rails, U37 isolated field supply, reverse-polarity protection | §6 |
| RP2040 + MCP23017 roles, I²C addressing, UART link | §7 |
| Opto input front-ends, active-low logic, dry-contact vs 24 VAC population | §8 |
| Relay outputs, drivers, snubber/MOV footprints, contact ratings | §9 |
| NE555 watchdog + relay-enable rail full circuit theory | §10 |
| Connector pinouts J1-J14 (full pin tables) | §11 |
| RP2040 GPIO map + MCP23017 bit maps (OUT_A_MAP / IN_A_MAP) | §12 |
| Net classes, creepage/clearance, DNP handling, test points | §13 |
| Machine-side C1/C2A connectors + the per-chassis adapter harness | §14 |
| Camera-scoring detector internals | the camera-scoring / pin-detection section (VERIFY: number) |
