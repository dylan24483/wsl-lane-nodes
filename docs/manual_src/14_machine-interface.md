## 14. Machine Interface: C1/C2A Connectors & the Adapter Harness

This section is the physical map between the AMF 82-70 pinsetter and the Phase 8 Rev-B lane-controller board. It tells you which machine wire carries which signal, on which connector, on which contact cavity, and how that lands on the board's function-named terminals through a per-chassis **adapter harness**. Read it together with:

- **Section 13 — Rev-B Board Architecture & Safety Rail** (the board the harness lands on: relay outputs, opto inputs, MCP23017 banks, RP2040, and the Candidate-C rail implementation).
- **Section 21 — Cutover Procedure (Track B)** (the run-of-show that *uses* this map to swap the OEM brain for the Pi controller; the items marked **CONFIRM AT CUTOVER** below get nailed down there).
- **Section 15 — RP2040 Firmware & Cam Timing** (the fast-input pin map and cam-stop behavior referenced here).

> **The single most important idea in this section.** The OEM machine wire tables (the factory 9800-MP and 6700-ELCO chassis) and the *measured* wiring on Westside's actual lanes **DISAGREE about which connector cavity carries which signal.** This is not an error in either source — the Omega-Tek retrofit on lanes 21/22 re-routed harness landings versus the factory drawing. Therefore **no cavity number in this section is baked into the PCB copper.** The board exposes signals by *function name* (S, T, GS1, SA, ...); a small hand-built **adapter harness** maps those function names to whatever cavities this particular chassis actually uses. When OEM and bench disagree, **the bench measurement wins** for our lanes, and the final binding is verified on the live machine at cutover.

---

### 14.1 What C1 and C2A are

The 82-70 machine harness terminates at the controller cabinet in two AMP M-series edge-card connectors mounted side by side. They were positively identified on the spare cabinet (connectors photographed out on the bench; the molded **"01" pin-1 mark + the "AMP" logo are at the same end on each** and are the orientation datum for all probing).

| Connector | Positions | Role | Physical (spare cabinet, photo 150321) | What it carries |
|---|---|---|---|---|
| **C1** | 34-pin | Motor / relay + power **output** side | LEFT connector. 3 columns. Row letters run `A,B,C,D,E,F,G…` then **double-letters `EE,FF,GG,HH,JJ,KK,LL,MM,NN`** at the bottom; **two oversized round power cavities** at the very end; `01`+`AMP` molded; "C1" stencil beside it (rotated 90° with the cabinet on its side). | Thick sweep/table **motor** leads + lower-power loads + machine mains feed |
| **C2A** | 50-pin | Switch / control + grippers **input** side | RIGHT connector. 4 columns × ~12–13 rows. Denser; also `AMP`-marked. | Many thin wires: cams, gate/bin switches, the 10 grippers, pushbuttons, relay coil control |

Both connectors are stamped with the AMP family numbers **`67209` / `67211`** (vertical text between them on the cabinet). **There are exactly two machine connectors** at this cabinet — a third ~25-position edge connector seen in one early photo turned out to be a separate Mask/BPP plug, not part of the C1/C2A pair (and the gripper "TAC strip" the OEM schematic implies does **not** exist as a physical block on this retrofit — see §14.6).

**Cavity-code format.** AMF labels each contact as `[bank][position][tag]`, e.g. `17DD`, `26BB`, `41C`. The double-letter tags (`BB`, `DD`, `FF`, `JJ`, `KK`, `LL`, `NN`) physically exist **only on C1** — this is itself a tell for which connector a code belongs to.

> **CONFIRM AT CUTOVER:** the per-cavity codes printed in the OEM service manual were read off a 225 DPI scan and are best-effort. The *which-connector* and *which-relay/group* assignments below are bench-measured and solid; the exact alphanumeric per pin is a cutover land-check item.

---

### 14.2 Why measured cavities differ from the OEM manual (read this before using any table)

Westside's fleet is **mixed**, and the two pairs need separate harness passes:

| Lanes | Chassis | Controller board | Status of the cavity map |
|---|---|---|---|
| **21 / 22** | SS chassis | **Omega-Tek Omniboard** (vendor defunct) + S2003LS2 triac driver bank | Bench-measured on the spare cabinet (most of this section). Confirm on the in-place machine at cutover. |
| **11 / 12** | MP chassis | **Active Technology Ultra 98 Plus** | **NOT yet mapped.** Needs its own short field pass before its harness is built (§14.10). Do not assume 21/22's cavities carry over. |

The retrofit divergence is already proven, not theoretical. Two concrete examples measured on the spare:

- **Sweep relay (S) contacts** land on C1 cavities **C, D, N, T**. The OEM 9800-MP wire table predicted **D, J, N, T** — measured **C** where the manual says J (the `22J → S-14` net reads at cavity **C** on our unit).
- **Sweep-reverse (M2)** lands on **C2A** (direct, 0 Ω). The OEM table puts M2 on **C1** cavities `17DD/18JJ/26BB/27FF` via a TSA/Expander path. Both are correct for their chassis; the Omega-Tek harness re-landed it.

This is exactly why the board is function-named and why §14.5/§14.6 mark cavities as reference-only. (The board's own design contract states this rule explicitly: *"Do not bake uncertain C2A cavity bindings into copper."*)

---

### 14.3 The board side the harness lands on (reference designators)

The harness mates to **function-named pluggable terminals** on the Rev-B board. These are the physical reference designators on the as-built board (from the fab BOM). Full electrical detail is in Section 13; this table is the harness-builder's quick map of "board connector → what plugs in."

| Board connector (net name) | RefDes | Footprint / mating plug | Signals on it |
|---|---|---|---|
| **J_PI** | J1 | IDC 2×10, 2.54 mm ribbon | I²C SDA/SCL, UART TX/RX, watchdog-kick, ARM, INT_A/B, RP2040_OK, 5 V, 3V3, GND → Raspberry Pi 40-pin |
| **J_PWR** | J2 | Phoenix MKDS 1,5/3 (5.08 mm screw) | Regulated 5 V logic in + GND |
| **J_FAST_IN** | J3 | Phoenix MCV 1,5/10-G-3,5 → mate **MC 1,5/10-ST-3,5** (PN 1840447) | SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R, + 2× FIELD_GND |
| **J_SLOW_IN_A** | J4 | Phoenix MCV 1,5/14-G-3,5 → mate **MC 1,5/14-ST-3,5** (PN 1840489) | GS1–GS10, GP, OS, BS, + FIELD_GND |
| **J_SLOW_IN_B** | J5 | Phoenix MCV 1,5/12-G-3,5 → mate **MC 1,5/12-ST-3,5** (PN 1840463) | PBZ, PBC, Foul, 10th, MAN_T/S/SWS/SWSR, AUX1–3, + FIELD_GND |
| **J_MOTION_S** | J6 | Phoenix MKDS 1,5/2 (5.08 mm) | Sweep relay K1 dry contact (COM/NO) |
| **J_MOTION_T** | J7 | Phoenix MKDS 1,5/2 | Table relay K2 dry contact |
| **J_MOTION_SP** | J8 | Phoenix MKDS 1,5/2 | Spot relay K3 dry contact |
| **J_MOTION_BE** | J9 | Phoenix MKDS 1,5/2 | Back-end relay K4 dry contact |
| **J_MOTION_M** | J10 | Phoenix MKDS 1,5/2 | Master relay K5 dry contact |
| **J_MOTION_M2** | J11 | Phoenix MKDS 1,5/2 | Sweep-reverse relay K6 dry contact |
| **J_MOTION_M1** | J12 | Phoenix MKDS 1,5/2 — **DNP / not harnessed** | Ball-return; footprint present, **depopulated** (see §14.9) |
| **J_LAMP_LED** | J13 | Phoenix MCV 1,5/6-G-3,5 → mate **MC 1,5/6-ST-3,5** (PN 1840405) | 5 V, GND, + 4 LED returns (1st/2nd/strike/foul) to our mask LEDs |
| **J_SAFETY** | J14 | Phoenix MCV 1,5/4-G-3,5 → mate **MC 1,5/4-ST-3,5** (PN 1840382) | **pins 1–2 = controlled Candidate-C jumper, no machine landing**; pins 3–4 = Stop/CIS loop |

Every motion output is an **isolated dry relay contact** (Omron **G5LE-14, 5 VDC coil**, LCSC **C116963** — see §14.8). The board never sources machine power; it only opens/closes a dry contact inside the existing machine control circuit.

---

### 14.4 The adapter-harness concept

The adapter harness is the **only** chassis-specific deliverable. It is a set of flying leads with the board-side pluggable plugs on one end and machine-side C1/C2A landings on the other. The OEM TB/SC live ladder is **not** brought onto J_SAFE: Candidate C uses the controlled pin-1/2 jumper and preserves TB/SC through the S/T output insertion points.

Design rules for the harness (these are board-design contract, not optional):

1. **Function in, cavity out.** The board end is fixed by function name (J3 pin 1 is always SA, J6 is always the sweep relay, …). The machine end is whatever this chassis measured. Build a new harness per chassis type; the board is identical fleet-wide.
2. **The board switches coil circuits, never motor current.** Each `J_MOTION_*` pair lands as an **isolated normally-open dry contact in series with the existing 24 VAC coil circuit** of that relay/contactor. The heavy S/T contactors and their OEM regenerative braking contacts **stay in the machine.** No 115 VAC motor lead ever touches the board or harness.
3. **Treat every machine-facing cavity as field-domain** until that exact net is verified. Logic ground never leaves the Pi side of the optos/relays/LED drivers.
4. **Lift, don't cut.** At cutover every machine wire is moved by lifting it from its OEM terminal and landing it on the harness lug — so the OEM brain can be re-plugged for rollback. No crimps/cuts until the unit has soaked clean.

The consolidated harness map (function → machine landing → front-end form) follows. Cells marked **CONFIRM AT CUTOVER** are filled by the live-machine field-capture step in Section 21.

| Board connector | Signal(s) | Machine landing | Front-end / polarity |
|---|---|---|---|
| **J_MOTION_S, _T** | S, T | **C1** cavities per §14.5 | Isolated NO dry contact in series with existing 24 VAC coil circuit |
| **J_MOTION_SP, _M, _M2, _BE** | SP, M, M2, BE | **C2A** (BE also straddles C1) per §14.5 | Same; **M2 must preserve the Expander/sweep-reverse interlock**, not merely jumper the cavity |
| **J_MOTION_M1** | M1 | — | **DNP, not landed** (§14.9) |
| **J_FAST_IN** | SA, SB, TA1, TA2 | C2A cam cavities — **CONFIRM AT CUTOVER** | Dry contact, **normally-closed**; dry-wetting population |
| | SC, TB | SC pink lead cold-locates at C2A-U but stays CUT+LABEL-ONLY; TB has **no standalone cavity / NO-LEAD** | Do not assume dry and do **not** feed J_SAFETY; firmware echo default-off/unvalidated |
| | DIELL-L, DIELL-R | DIELL ball-detector leads | NPN open-collector: **idle HIGH ~13–17 V, beam broken LOW ~0 V**; 12 V supply, 10 kΩ pull-up (see §14.7) |
| **J_SLOW_IN_A** | GS1–GS10 | C2A "4-bank" (≈ 41C…410U) — **per-GS# binding CONFIRM AT CUTOVER** | Dry contact, **gripped (pin standing) = CLOSED to chassis**; chassis return (§14.6) |
| | GP, OS, BS | C2A (GP ≈ 412DD, BS ≈ 112cc) — confirm | Dry contact |
| **J_SLOW_IN_B** | PBZ, PBC | C2A (≈ 21EE area) — confirm | Momentary dry contact |
| | Foul (Radaray) | Foul-detector lead | Edge; confirm form at cutover |
| | 10th / MAN_T/S/SWS/SWSR / AUX | Spare (future) | — |
| **J_LAMP_LED** | L_FIRST/SECOND/STRIKE/FOUL | **Our LEDs in the mask housings** | 5 V logic via low-side FET; the machine's 15 VDC mask supply is abandoned |
| **J_SAFETY** | TB/SC board position | **controlled, keyed/labeled jumper on pins 1–2; no machine landing** | Candidate C delegates primary protection to the OEM parallel-safe S/T coil ladder; G3 proves both commanded coil drops per lane |
| | Stop/CIS/master sense | Upstream machine safety chain | Preserve intact; rail condition |
| **J_PI** | I²C, UART, WDOG-kick, ARM, INT | Pi 40-pin | Per-board bus (the second board of a pair uses a software-bit-banged I²C bus) |
| **J_PWR** | 5 V logic, isolated field-wetting, DIELL 12 V | Enclosure supplies | Reverse-polarity + transient protection on input |

---

### 14.5 Output side: C1 / C2A → relay coil circuits (bench-measured, lanes 21/22)

This is the **output** map: which machine connector cavity each board relay closes into. All seven loads were probed on the spare cabinet (JOB-1). The engineering split is clean: the two **high-current main motors (S, T) use C1** (the heavy-pin connector with the two oversized power cavities); the **lower-power loads (M2, SP, M, BE) use C2A**; **BE straddles both.**

| Relay | Drives | Connector | Measured cavities | Coil (machine side) | Notes |
|---|---|---|---|---|---|
| **S** sweep | Sweep motor (high current) | **C1** | **C, D, N, T** | Siemens 3TH4022, 24 VAC | OEM predicted {D,**J**,N,T}; measured **C** not J |
| **T** table | Table motor (high current) | **C1** | **A, K, H, E** (+ **L @ 55 Ω through-coil**) | heavy-lug contactor, 24 VAC | OEM predicted {A,E,K,**P**,H}; measured **L** where P predicted |
| **M2** sweep-reverse | Sweep reverse (auto-scoring gutter / 7-10) | **C2A** | direct 0 Ω (cavity TBD) | 82-70-5515, ~24 V, 80 Ω | OEM put this on C1 via TSA/Expander — retrofit re-landed to C2A |
| **SP** spot | Spot solenoid | **C2A** | direct 0 Ω (cavity TBD) | separate P/N, ~24 V, 100 Ω | |
| **M** master | Master / control (T1, halo, pit light) | **C2A** | T1=FF, T2=U, T3=B (+U) | 82-70-5515, ~24 V, 80 Ω | Routes via C2A like M2/SP |
| **BE** back-end | Back-end motor (elevator/pitveyor/distributor) | **C1 + C2A (straddles)** | C1: **KK, C, L**; coil **FF @ 66 Ω**; also C2A (DD→C2A, W→C2A, F→C2A) | ~24 V, 22 Ω | Touches several circuits; harness needs leads to both connectors |
| **M1** ball-return | Ball return | — | **not harnessed** | — | DNP — not bench-confirmed to exist as a separate relay (§14.9) |

> **Reading the "through-coil" measurements.** A probe hit at **0 Ω = a direct wire.** A hit at **~55 Ω** is a connection *through a relay coil winding* (the cavity shares a node via the coil, not a hardwired wire). The T→L @ 55 Ω and BE coil→FF @ 66 Ω entries are through-coil paths, recorded for traceability; the harness lands on the direct (0 Ω) cavities.

> **The two oversized C1 power cavities are NOT Pi-driven.** They are the machine mains feed (visible as the two big round contacts on C1). They will be obvious in the harness; the board never touches them.

**Coil voltages (measured on the spare, drives the suppression/PSU decisions, not the harness map):**

| Coil | Unit | Coil resistance | Working V |
|---|---|---|---|
| S (and T partner) | Siemens **3TH4022-0AC2** | 5 Ω (A1–A2) | **24 VAC — confirmed** (the `-0AC2` suffix = 24 V coil; 5 Ω only fits 24 V at 60 Hz) |
| M | 82-70-5515 | 80 Ω | ~24 V native |
| M2 | 82-70-5515 (identical to M) | 80 Ω | ~24 V native |
| SP | separate P/N | 100 Ω | ~24 V native |
| BE | — | 22 Ω | ~24 V native (low R leans AC) |
| (P&B socket nearby) | P&B JRM-10110 | — | **12 VDC** (one DC coil present in the cabinet) |
| KX | — | — | **OMITTED** — KX fed the old scorer; the camera (Track A) replaces it |

The **at-machine field session (2026-06-03) confirmed all relay working voltages are 24 VAC** (SP presumed). This is why the board's creepage is relaxable toward 24 V numbers and why the enclosure PSU is primarily 5 V (the board only *switches* the machine's own 24 V coil circuits; it does not *source* coil power).

> ⚠️ **Resistance does not give an AC coil's voltage.** AC coils are reactance-limited at 60 Hz, so they read far lower than a DC coil of the same voltage. The Siemens reading 5 Ω is the *proof* it is AC. Use the nameplate or a live read for AC coil voltage, never the cold ohms.

---

### 14.6 Input side: the grippers (GS1–GS10) on C2A

The grippers are the pin-sense switches — **10 of the controller's slow inputs, scoring-critical.** Field tracing on the real machine **overturned the OEM schematic's gripper model.** Lock these facts:

1. **There is no physical "TAC strip."** The OEM 9800-MP "DETAIL K" shows the grippers on a `TAC-1…TAC-10` terminal block with a `TAC-GND` common-return wire. **No such 10–12-lug block exists in this Omega-Tek cabinet.** "TAC" is a schematic net name only. The grippers arrive in the table/machine harness bundle (the fat cloth-wire bundle entering near C2A) and **terminate directly on C2A cavities.**
2. **The common return is the machine CHASSIS/FRAME, not a C2A common pin.** Each gripper switch closes its signal wire to a contact point that is the (un-insulated) machine frame. There is no `TAC-GND` bus pin to hunt for — each gripper is **one signal wire + chassis return.**
3. **Polarity is locked: gripped (pin standing) = CLOSED to ground.** (This is the *opposite* sense of the cams, which are normally-closed — see §14.7.) Firmware reads a standing pin as the input *asserted*.
4. **The bank is a contiguous C2A "4-bank."** The 10 gripper wires occupy ~10 adjacent C2A cavities whose codes start with `4` — the predicted block is **41C…410U**.

This changes the **board front-end reference**, not the isolation domains: gripper inputs are still FIELD-side dry-contact optos, but the field side wets *through the gripper to chassis*, so the harness ties the gripper input returns to **machine chassis**, not to a dedicated C2A common pin. (The board contract carries this as a confirmed front-end requirement.)

**On the board** (from `controller_io.py` `IN_A_MAP` and the netlist `SLOW_INPUT_PINS`, which are the source of truth and are kept in lock-step by a regression test), the grippers land on **MCP23017 IN-A (I²C 0x20)** in clean order:

| Gripper | MCP IN-A pin | (port, bit) | Predicted C2A cavity (CONFIRM AT CUTOVER) |
|---|---|---|---|
| GS1 | 21 | (0, 0) | 41C |
| GS2 | 22 | (0, 1) | 42H |
| GS3 | 23 | (0, 2) | 43M |
| GS4 | 24 | (0, 3) | 44S |
| GS5 | 25 | (0, 4) | 45W |
| GS6 | 26 | (0, 5) | 46Z |
| GS7 | 27 | (0, 6) | 47? |
| GS8 | 28 | (0, 7) | 48H |
| GS9 | 1 | (1, 0) | 49? |
| GS10 | 2 | (1, 1) | 410U |

The OEM DETAIL-K read **TAC-n = GS-n 1:1 (no scramble)**, so the board reads the bank in pin order. The **per-GS# → exact C2A cavity** binding is deliberately deferred to cutover: with the harness landed and the rail disabled, lift one pin off the deck at a time and watch which `GS` channel deasserts in the live input feed. Set the result in software (`controller_io.py` GS map) — no board change. Walk a corner gripper and a center gripper first to confirm the ordering pattern; flag any that break the block order.

> **Why the per-pin binding is not a board gate:** the board only needs the *bank location + the polarity*. Both are confirmed (4-bank, gripped=closed-to-chassis). The GS1-vs-GS7 label is a software assignment.

---

### 14.7 Input side: the cams (SA/SB/SC/TA1/TA2/TB) on C2A

The motion cams are microswitches **on the machine** that report sweep/table angle.
Independently landed SA/SB/TA1/TA2 inputs go to the RP2040, not the MCP23017. The
RP2040 drives the fail-safe rail-permission line and the max-run backstop. Its v1.2.3
code contains per-cam overrun paths, but all measured-cam enforcement flags remain
OFF until polarity is captured and bound into a new controlled release (Section 15).
Do not infer from the PCB positions that SC/TB are both field-observable.

**Electrical-form boundary:** do not generalize the earlier dry-contact field result to SC/TB. C2A-U is a non-isolatable live-ladder region and the cold ~21 Ω paths invalidate dry/topology inference. SA/SB/TA1/TA2 still require the powered cavity/class/polarity capture; SC stays unlanded pending a reviewed observe-only design; TB has no independent landing.

**Board side (firmware `config.h` — the authoritative pin map; the stale `phase8_channel_allocation.md` GPIO column must be ignored):** the eight fast inputs are opto-isolated, **active-low at the Pico** (contact closed pulls the GPIO LOW; idle HIGH through external `Rpu_*` to 3V3), and land on **GP6–GP13**. Rev-B used 10 kΩ; current Rev-D/R5 uses **47 kΩ** and disables the RP2040 internal pulls:

| Fast input | Pico GPIO | Pico pin | Netlist FAST pin | Cam role (OEM training manual) | C2A cavity |
|---|---|---|---|---|---|
| **SA** | GP6 | 9 | 9 | Sweep cam: stop @2nd guard / run-up / stop @zero (270 run-through, 360 zero) | CONFIRM AT CUTOVER |
| **SB** | GP7 | 10 | 10 | Sweep cam: stop @1st guard 66° / start table spotting 186° | CONFIRM AT CUTOVER |
| **SC** | GP8 | 11 | 11 | Sweep-under-table interlock window (~86–243°) | **C2A-U cold location only; CUT+LABEL-ONLY, not J_SAFETY** |
| **TA1** | GP9 | 12 | 12 | Table cam: run table up / stop @zero (355° zero, 185° delay reset) | CONFIRM AT CUTOVER |
| **TA2** | GP10 | 14 | 14 | Table cam: start sweep run-through / pin-latch (260°) | CONFIRM AT CUTOVER |
| **TB** | GP11 | 15 | 15 | Table-sweep interference interlock (~105–255°) | **NO standalone cavity on 21/22; NO-LEAD** |
| **DIELL-L** | GP12 | 16 | 16 | Ball detect, left beam (cushion start-switch trigger) | DIELL lead, not C2A |
| **DIELL-R** | GP13 | 17 | 17 | Ball detect, right beam | DIELL lead, not C2A |

> **CONFIRM AT CUTOVER (cam → cavity binding).** Which A&MC/C2A cavity is which specific cam (SA vs TA1 vs …) **cannot be determined from the bench** — it requires rotating the mechanism by hand (locked out) and watching which fast input fires at which angle. The OEM A&MC pins associated to cams are `A&MC-11A, 12D, 13H, 14L, 21B, 22E, 31C`; the A&MC-pin↔cam binding is a cutover-prep task. Record each as `cam → C2A cavity → RP2040 GP#`.

**The DIELL ball detector** replaces the OEM cushion start-switch (SS). It is an NPN open-collector sensor: **idle HIGH ~13–17 V, beam broken LOW ~0 V**, run from a 12 V supply with a 10 kΩ pull-up. This signal-chain (Taiss DIELL → opto → Pi GPIO) was independently validated end-to-end on Phase 8a. It is the **cycle trigger** (ball hits cushion → cycle) **and** a safety interlock element — preserve its safety role in hardware.

---

### 14.8 Input side: gate/bin switches + pushbuttons on C2A

The remaining slow inputs land on **MCP23017 IN-A (0x20)** alongside the grippers (the netlist `SLOW_INPUT_PINS` and `controller_io.py` `IN_A_MAP` agree and are regression-locked):

| Signal | Role | MCP IN-A pin | (port, bit) | C2A cavity (tentative) |
|---|---|---|---|---|
| **GP** | Gripper-protect (blocks table feeling for pins when off) | 3 | (1, 2) | ≈ 412DD — confirm |
| **OS** | Off-spot (table contacts off-spot pin) | 4 | (1, 3) | CONFIRM AT CUTOVER |
| **BS** | Bin switch (#9 pin in bin) | 5 | (1, 4) | ≈ 112cc — confirm |
| **PBZ** | Zero / 1st-2nd-ball status / manual intervention | 6 | (1, 5) | ≈ 21EE area — confirm |
| **PBC** | Cycle pushbutton | 7 | (1, 6) | ≈ 21EE area — confirm |
| **Foul** | Radaray foul | 8 | (1, 7) | CONFIRM AT CUTOVER (confirm form) |

The remaining bank, **MCP23017 IN-B (0x21)**, holds future/spare inputs — 10th-frame, manual T/S/SWS/SWSR, and AUX1–3 — landing on **J_SLOW_IN_B (J5)**. IN-B is initialized in firmware but not yet read by the FSM.

> **PBZ/PBC are panel pushbuttons you can press by hand** — these are fully mappable cold (press-and-hold, sweep the C2A cavities with the meter, find the one that closes only while pressed). **GP/OS/BS are machine-side switches** like the cams — map what lands on C2A; confirm actuation at the machine at cutover.

---

### 14.9 M1 (ball return) — depopulated

Ball return (**M1**) is **not harnessed** in this build:

- M1's relay channel on the board (relay K7, driver Q7, R85–R87, D13/D14, C10, and connector **J12/J_MOTION_M1**) carries **DNP + exclude_from_bom + exclude_from_pos_files** — the footprint exists in copper but no part is placed.
- M1 has **not been bench-confirmed to exist as a separate relay** on this chassis, and the cycle FSM does not drive it.
- It stays unpopulated and unharnessed until proven on the live machine. If ball-return turns out to be a separate command here, it is a future rev-C populate.

The firmware still lists M1 in `MOTION_RELAYS` and `OUT_A_MAP` (gen pin 27) so the software map stays complete, but with the relay depopulated there is no output. **CONFIRM AT CUTOVER:** whether ball-return is a separate command on this chassis (§3.6 of the cutover runbook).

---

### 14.10 Gripper chassis-return and the safety landings

These three machine-interface details are safety- or harness-critical and are easy to get wrong.

**Gripper chassis-return (recap, because it bites).** The gripper field side wets *through the gripper switch to the machine frame.* The harness must tie the gripper-bank return to **clean bare chassis metal**, not to a C2A "common" pin. There is no TAC-GND bus on this chassis. The isolation domains are unchanged (grippers are FIELD-side), but the return node identity is chassis, not a dedicated wire. When probing grippers, the black meter lead clips to scrubbed bare chassis metal anywhere — distance is irrelevant, the frame bridges it.

**TB/SC interlock (Candidate C — OEM ladder, not a J_SAFETY machine loop).** Powered 2026-07-07 proved the OEM TB and SC contacts are **parallel closed-when-safe** in the 24 VAC S/T coil ladder: either pressed lever permits a coil; **both levers BACK/open kill both S and T coils**. Cold 2026-06-27 proved only that C2A-U is a shared live-ladder region, TB has no standalone/dry pair, and ~21 Ω sneak paths prevent topology inference. Candidate C places the controlled jumper on J_SAFE1-2 and keeps the OEM ladder primary. Every lane must prove the board's S and T insertion points at G3. The SC∧TB firmware echo is default-off, secondary, and unvalidated because there is no independent TB observation.

> **Do not search for or land TB/SC terminals on J_SAFE1-2.** Build the controlled
> jumper exactly per the lane-21 harness sheet. At G3, body clear, command S and then
> T with the board and force both levers BACK/open; each corresponding contactor coil
> must remain dead. Any energized coil means the output tap bypassed the OEM ladder:
> abort, reselect the insertion point, and re-prove.

**Stop / CIS chain (→ J_SAFETY pins 3–4).** The machine's existing **Stop switch** (post-1979, left of the power plug) and **C.I.S.** (1981, under the plug-duct cover) are wired **in parallel and both cut the rear-panel MASTER circuit breaker** (OEM service manual p11). This upstream safety chain **stays live and intact** — the master breaker remains the final physical stop, including for a welded relay contact (the rail can drop a coil but cannot open a welded contact). J_SAFETY pins 3–4 carry the Stop/CIS sense as a second NC loop in series so the board's rail *also* requires this chain OK; the chain itself is not replaced. **CONFIRM AT CUTOVER:** continuity that Stop in RUN vs STOP drops the motor-relay coil rail.

> **Cam-stops are now solely the RP2040's job once measured enforcement is enabled and proven.** The OEM machine uses logic stops, not a hardwired cam-in-series stop latch. The TB/SC **OEM coil ladder** and regenerative braking remain separate hardware backstops. The default-off SC∧TB firmware echo is not a substitute for that ladder.

---

### 14.11 Per-chassis note (11/12 needs its own pass)

Everything in §14.5–§14.8 is the **21/22 (SS + Omega-Tek)** map. The **board is fleet-common; the harness and input populations are per-chassis-type.** Before cutting over **11/12 (Active-98 MP)**, repeat the working-voltage, input-class, cavity, gripper-return, and **Candidate-C S/T insertion/G3** captures. Do not assume either the 21/22 cavities or its no-independent-TB observation carries over. Clone the board; re-capture and re-prove the harness.

---

### 14.12 Key parts referenced in this section

Authoritative part numbers from the as-built Rev-B fab BOM (the part-lock CSV), for anyone sourcing a board or a mating harness:

| Part | Manufacturer P/N | LCSC | Where used |
|---|---|---|---|
| Output relay | Omron **G5LE-14 5VDC** SPDT | **C116963** | K1–K6 (S/T/SP/BE/M/M2). **5 VDC coil — do not substitute 9/12/24 V.** |
| Optocoupler | **PC817B** (UMW) | **C5692981** | U4–U35 (all 32 isolated inputs) |
| I/O expander | **MCP23017-E/SO** (Microchip) | **C47023** | U1/U2/U3. **I²C MCP23017, NOT SPI MCP23S17.** |
| Watchdog timer | **NE555DR** (TI, bipolar) | **C7593** | U36. Bipolar 555 — avoid CMOS/TLC555 (timing change). |
| Isolated wetting supply | TRACO **TMA-0505S** | — | U37 (isolated 5 V field-wetting) |
| Rail pass FET | **AO3401A** P-MOS | C347476 | Q14 (relay-enable rail pass element) |
| Board fast-input map | — | — | Firmware `config.h`: fast inputs **GP6–GP13**, RP2040_OK **GP2**, UART **GP0/GP1** |

Mating plugs for the field/safety/lamp connectors are the Phoenix `MC 1,5/n-ST-3,5` screw plugs listed in §14.3 (PNs 1840447 / 1840489 / 1840463 / 1840405 / 1840382); the motion terminals are Phoenix MKDS 1,5/2 (5.08 mm) board blocks; J_PI is a 2×10 2.54 mm IDC ribbon to the Pi.

---

### 14.13 Quick reference — what is confirmed vs CONFIRM AT CUTOVER

**Bench/field-confirmed (lanes 21/22):**
- C1 = LEFT/34-pin motor+power; C2A = RIGHT/50-pin switch+control; "01"+AMP pin-1 datum; exactly two machine connectors.
- Output split: S, T → C1 (cavities C,D,N,T and A,K,H,E+L); M2, SP, M → C2A; BE straddles C1+C2A.
- All relay working voltages **24 VAC**; coil resistances as tabled; one 12 VDC P&B coil present.
- Grippers: no physical TAC strip, **chassis return**, **gripped = closed to ground**, contiguous C2A 4-bank (≈41C…410U), TAC-n = GS-n 1:1.
- Cam inputs: **dry contact, normally-closed**; fast inputs on RP2040 **GP6–GP13** (active-low).
- DIELL ball detector: NPN open-collector, idle HIGH ~13–17 V / broken LOW ~0 V, 12 V + 10 kΩ pull-up; replaces SS; is the cycle trigger + an interlock.
- Stop/CIS in parallel both cut the master breaker (OEM p11); TB/SC parallel in the 24 V control path (OEM p15); cam-stops are LOGIC (board-timed), so the RP2040 owns them post-cutover.
- M1 ball-return DNP, not harnessed.

**CONFIRM AT CUTOVER (none gate the PCB — function-named + harness-resolved):**
- Exact C2A cavity for each cam (SA/SB/SC/TA1/TA2/TB) — rotate mechanism, watch the fast input.
- Per-GS# → exact C2A cavity (lift one pin at a time, watch the live feed).
- Exact cavities for M2/SP/M on C2A; re-confirm S/T/BE C1 cavities on the in-place machine.
- Stop/CIS continuity and its J_SAFE3-4 landing. **TB/SC J_SAFE1-2 is resolved:**
  no machine landing; install only the controlled Candidate-C jumper and prove S/T
  insertion per lane at G3.
- GP/OS/BS/Foul exact cavities + Foul electrical form.
- Whether M1 ball-return exists as a separate command on this chassis.
- The whole map again, fresh, for **lanes 11/12 (Active-98 MP)**.
