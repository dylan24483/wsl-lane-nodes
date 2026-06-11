# Westside Lanes — Phase 8 Lane Controller & Scoring System
## Technical Reference & Service Manual

**Hardware revision:** rev-B controller board · **Firmware:** RP2040 v0.1.0 · **Compiled:** 2026-06-04
**Status:** Design + fabrication complete (bare PCB + Standard-PCBA package released to JLCPCB). On-hardware **bench bring-up and the Track-B cutover are still pending.** This manual documents the system *as designed*; values still to be confirmed against real hardware are marked `(VERIFY: …)` inline and summarized in the **Open-Items Register** below.

---

### Purpose & audience
This is the complete, top-to-bottom reference for the system that replaces **Conqueror Pro** (bowling ops), the **QubicaAMF VDB scoring** stack, and the **OEM AMF 82-70 controller brain** at Westside Lanes (32 lanes / 16 pinsetter pairs). It assumes a competent engineer or electrician with **zero prior context on this project**, and is written so that person can operate, repair, calibrate, or extend the system without the original author present. Read §1–§2 for the whole picture; use the rest as a lookup reference.

### How to use this manual
| You want… | Read |
|---|---|
| The big picture + what it replaces | §1 System Overview, §2 Architecture |
| How the bowling machine itself works | §3 Sequence of Operation, §4 Machine I/O |
| The controller board (theory of every block) | §5–§10 |
| **A specific connector pinout / channel map** | **§11 Connector Pinouts, §12 Channel Maps** |
| How it manufactures (net classes, DNP, fab) | §13, §20 |
| How the board wires to the machine | §14 Machine Interface (C1/C2A + harness) |
| The software/firmware | §15 Firmware, §16–§17 Pi software, §18 Camera scoring |
| **Safety — read before any powered work** | **§19 Safety Architecture** |
| Deploy, bring-up, cutover, troubleshoot | §20–§22 |
| Full BOM, cam timing, glossary, doc index | §23 Appendices |

> ⚠️ **SAFETY.** This system controls an AMF 82-70 pinsetter that **moves and bites**, and it switches mains-powered motor contactors. Read **§19 (Safety Architecture)** and the **lockout/tagout procedure in §21** before any powered work on a machine. The board is never the only safety device — the machine's Stop/C.I.S./master-breaker chain and TB/SC interlock stay in hardware.

### Source & maintenance
This manual was assembled from per-section source files in `docs/manual_src/` (`00`–`23`), each grounded in the live design files (the KiCad netlist generator, the firmware, the Pi code, and the fab BOM/CPL). To update: edit the relevant `docs/manual_src/NN_*.md` and re-assemble. **Sources of truth for pins/parts/maps** are the code + netlist, not prose — if this manual ever disagrees with `scripts/generate_kicad_netlist_revB.py`, `firmware/rp2040/`, `lane_node/controller_io.py`, or the fab BOM, the code wins (and this manual has a bug to fix).

---

### Open-Items Register (as of 2026-06-04)
Every item below is *intentionally* unresolved at design/fab time and resolves at the noted stage. The inline `(VERIFY: …)` flags throughout the manual point back to these.

| # | Open item | Resolves at | See |
|---|---|---|---|
| 1 | Per-cam → C2A cavity **and trip-edge polarity** (SA/SB/SC/TA1/TA2/TB) | Cutover (hand-rotate mechanism, watch the live input feed) | §14; cutover runbook §3.2 |
| 2 | Per-gripper **GS# → C2A cavity** (1:1 order) | Cutover (drop one pin, watch which input asserts) | §14; runbook §3.1 |
| 3 | **TB/SC interlock** + **Stop/CIS** + exact **C1/C2A relay landings** | Cutover | §14; runbook §3.3–3.5 |
| 4 | **M1** (ball-return) existence on this chassis — stays **DNP** until proven | Cutover | §9, §14 |
| 5 | `controller_daemon.DEFAULT_BOARDS`: real I²C bus ids, UART ports, ARM + watchdog GPIOs, MCP INT lines (currently `# CONFIRM` placeholders) — boot overlays, pin table + the Track-A coexistence constraint in **`docs/phase8_pi_provisioning.md`** | Bench bring-up | §12, §17 |
| 6 | RP2040 **firmware v1.1 cam-stop overrun** (needs cam polarity from item 1) — until then the cutover G3 cam-stop sub-test is blocked | Post-cutover capture | §15, §19, §21 |
| 7 | **Relay contact current rating** + snubber/MOV population (field-sheet A2) | At-machine coil-current measurement | §9, §13 |
| 8 | **Status-LED current-limit resistor** (`Rled_*` = 330R placeholder) | Final LED brightness selection | §9, §12 |
| 9 | **SP spot-solenoid working voltage** (presumed ~24 VAC; coil was inaccessible at the field session) | Cutover glance | §3, §5 |
| 10 | **24 VAC creepage relax** (board is routed to conservative 250 VAC spacing; optional shrink before the 16-lane fleet run) | Pre-fleet, optional | §5, §13 |
| 11 | Hand-solder part sourcing: **TRACO TMA-0505S**, the **Phoenix mating plugs**, the **Pico module** (none are JLC-placed) | Procurement | §20, §23 |
| 12 | Track-A scoring soak tuning: `WSL_LANE_CAMERA_SETTLE_S`, pins 2 & 3 (homography-predicted), `MIRROR` confirm with a deliberate 7- or 10-pin | Scoring go-live soak | §18 |

> A historical doc lists the machine **mask-lamp supply as 12 VDC**; the field measurement is **15 VDC**. This is **moot** — the board drives its own status LEDs and the machine lamp supply is abandoned (§9).

---

### Table of Contents
1. System Overview & Purpose
2. System Architecture & Signal Chain
3. The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing
4. Machine I/O Inventory (Cams, Grippers, DIELL, Foul, Mask, Buttons)
5. Rev-B Controller Board: Overview, Domains & Isolation
6. Rev-B Power Architecture
7. Rev-B Logic: RP2040 Co-processor + MCP23017 Expanders + I²C
8. Rev-B Field Inputs: PC817 Opto-isolators
9. Rev-B Machine Outputs: G5LE Relays
10. Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail
11. Rev-B Connector Pinouts (J1–J14)
12. Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps
13. Rev-B Layout & Manufacturing Contract (Net Classes, Creepage, DNP, Test Points)
14. Machine Interface: C1/C2A Connectors & the Adapter Harness
15. RP2040 Firmware (Safety Co-processor)
16. Pi Software: The Cycle-Control FSM
17. Pi Software: IO Layer, RP2040 Link & Controller Daemon
18. Camera Pin Scoring (Track A)
19. Safety Architecture (Consolidated)
20. Operations: Network, Deployment, Build & Fab
21. Bring-up, Bench Validation & Cutover
22. Troubleshooting, Maintenance & Spares
23. Appendices: Full BOM, Cam Timing, Glossary & Document Index


## 1. System Overview & Purpose

> **Read this first.** This is the orientation chapter of the *Westside Lanes — Phase 8 Lane Controller & Scoring System — Technical Reference & Service Manual*. It assumes you have **never seen this system before**. It tells you what the equipment is, why it exists, what it replaces, how it is organized, and how to read the rest of the manual. Pinouts, schematics, firmware internals, calibration, bring-up, and field service live in later sections (cross-referenced by number). The hard electrical contract that governs the printed circuit board is `docs/phase8b_pcb_revB_spec.md`; the controller behavioral spec is `docs/phase8_8270_SYSTEM_REFERENCE.md`. **When this manual and a live source file disagree, the live source file wins** — every fact below is grounded in the files listed in §1.9.

---

### 1.1 What this system is, in one paragraph

Westside Lanes is a 32-lane bowling center in Olympia, WA, built as **16 pairs of lanes**, each pair served by one **AMF 82-70** automatic pinsetter ("pinspotter"). Phase 8 replaces the center's aging, end-of-life (EOL) electronics with **one Raspberry Pi per lane pair**. Each Pi does two jobs: (A) it **scores the game from a camera** instead of the legacy QubicaAMF scoring electronics, and (B) it will eventually **run the pinsetter itself** — reading the machine's switches and cams and driving its motor relays — replacing the original 1970s-era AMF control "brain" (and the third-party retrofit boards bolted on over the decades). The Pi never carries motor power and is never the only safety device: it commands the machine's existing relays and contactors through isolated dry contacts, and the machine's own stop chain, collision interlock, and braking stay in hardware.

### 1.2 Why this project exists

The center currently runs two stacks of obsolete, unsupported equipment:

1. **Conqueror Pro** — the bowling-operations / front-desk software that drives league play, lane assignment, and scoring presentation.
2. **QubicaAMF scoring hardware** — the "VDB" (Video Display Board) per-lane scoring computers, the "ETHost" gateway that links them, and the T-VISION camera/scoring boards. These parts are EOL from QubicaAMF; spares are scarce and the data path is brittle (the legacy scoring poll returns a frozen snapshot when Conqueror is also attached — i.e. WSL cannot reliably read live scores from it).
3. **The AMF 82-70 OEM controller** — the original solid-state (SS) control chassis that sequences the pinsetter, plus the aftermarket retrofit controllers that have replaced or augmented it on various lanes.

Every one of these is a single point of failure with no viable supply chain. Phase 8's strategic goal is **zero EOL hardware**: own the brain on a commodity, in-stock platform (Raspberry Pi + a custom controller board + a camera), so the center is no longer hostage to a defunct vendor. The cost comparison that justified the project was roughly **$5k all-in for the Pi-per-pair build vs ~$16k for an OEM refurbish** — and the refurbish would still be EOL.

Phase 8 is a separate, self-contained project from the main Westside Lanes point-of-sale / food-and-beverage application; its code lives in its own repository (`wsl-lane-nodes`). The two only meet at a small software bridge in the main app — the **Phase-8b scoring→server proxy in `wsl_api.py`**, which is outside this manual's scope.

### 1.3 What it replaces — old vs new

| Function | Legacy equipment (being retired) | Phase 8 replacement |
|---|---|---|
| Front desk / league ops | Conqueror Pro | Main WSL app (out of scope here) + Pi scoring feed |
| Per-lane score computer | QubicaAMF VDB (one per lane), ETHost gateway | Raspberry Pi per pair + scoring engine + HTML scoring display |
| Pin detection | T-VISION board reading the QubicaAMF T-Camera | Same physical T-Camera, **read directly by the Pi** via a USB capture dongle; pins detected in software (Track A) |
| Pinsetter sequencing brain | AMF 82-70 OEM solid-state (SS) chassis + retrofit controllers | Pi running the cycle state machine + a custom controller PCB (Track B) |
| Pinsetter machine itself | **KEPT** — AMF 82-70 mechanism, motors, cams, grippers, mask | unchanged; only the brain is replaced |

The single most important architectural fact in this manual: **the 82-70 *machine* is retained and is identical on every lane; only the *controller* is replaced.** AMF themselves proved this is safe — their later "MP" (microprocessor) chassis was a drop-in replacement for the original 5-board SS chassis using the *same machine inputs and outputs*; only the logic medium changed (relays/discrete logic → microprocessor). The Phase 8 Pi-controller is, in effect, **a modern MP chassis**. Because of this, the published AMF MP wiring schematic shows only the machine↔chassis interconnections and *omits the controller's internal logic* — which means the schematic IS our interface spec, and the omitted logic is exactly the part this project writes. (Full theory: `docs/phase8_8270_SYSTEM_REFERENCE.md` §0 and §6, and **§3, The AMF 82-70 Machine & Control Theory**.)

### 1.4 The two tracks (A and B)

Phase 8 runs as **two parallel tracks** that share the same Raspberry Pi and converge into one node per pair:

#### Track A — Camera pin scoring (near-term, low-risk, code-complete)

The Pi taps the **composite-video output of the existing QubicaAMF T-Camera** (one camera views *both* decks of a pair) through a USB capture dongle, then detects standing pins in software using a **difference-from-empty** method: a captured full-rack frame minus a stored empty-deck reference frame leaves the pins as the bright residual; fixed per-pin regions ("spots") are checked to see which pins are still standing. This is the same principle the legacy Conqueror scorer used, and it tolerates the camera's deliberately soft focus.

Track A is **read-only with respect to the machine** — the existing controller still cycles the pinsetter while Track A merely watches and scores, and it automatically falls back to manual score entry on any failure. This is why Track A can go live long before the (safety-critical) Track B. As of the source documents, Track A is **calibrated and code-complete** (all 20 pin spots located, the dual-deck detector validated with zero errors on labeled test frames) and is "parked-ready" — its only remaining step is the on-site go-live runbook (`docs/phase8_trackA_golive_runbook.md`). Details: **§18, Track A — Camera Scoring**.

#### Track B — Controller replacement (long-term, safety-critical, in development)

The Pi reads the 82-70's switches and cams and drives its motor-control relays directly, replacing the controller brain entirely. This is the safety-critical track: it commands AC motors operating near people, so it carries a layered hardware safety architecture (covered in **§19, Safety Architecture** and summarized in §1.7). The Pi runs an event-driven **finite-state machine (FSM)** that reproduces the 82-70 "sequence of operation," assisted by an **RP2040 co-processor** on the controller board that owns the fast, timing-critical cam/ball inputs and an independent rail-permission safety line.

As of the source documents, Track B has: the full controller behavioral spec mined from both AMF manuals; the FSM written and simulated; the custom controller board (rev-B) designed, routed, and a **bare-PCB fabrication package generated and fab-ready** under a conservative design-rule contract; and the RP2040 firmware written, host-tested, and ARM-cross-built to a `.uf2`. Track B is **NOT cutover-ready** — it still needs the populated board, on-machine bench bring-up, the remaining field measurements (relay-coil current, the exact safety-interlock terminal landings), and the cam-stop overrun firmware feature (deferred to firmware v1.1). Details: **§5, The Rev-B Controller Board**, **§15, RP2040 Firmware**, and **§21, Track B Bring-up & Cutover**.

> **The two tracks converge** into a single Pi-per-pair node that both scores (Track A) and controls (Track B). A useful convergence detail: once Track A supplies pin data, the controller board does **not** need to drive the 10 physical pin-indicator lamps — the camera already knows which pins stand — so those outputs are omitted in the baseline board (see §1.6 and §5).

### 1.5 The one-Pi-per-lane-pair model

A "pair" is two adjacent lanes that share a pinsetter ball-return and a single scoring camera (e.g. lanes **21 and 22**). Phase 8 deploys **one Raspberry Pi per pair**, which fits the hardware naturally:

- **Camera:** one T-Camera already images both decks (left deck + right deck + the central kickback divider) in a single frame, so one Pi capturing one video stream scores both lanes. The software maps the left deck to one lane number and the right deck to the other (for the pilot pair: left deck = lane 21, right deck = lane 22).
- **Control:** each lane's pinsetter is a *separate* machine, so control wiring is **per lane**, not per pair. The design rule is therefore **one controller PCB per lane** — a pair uses **two identical controller boards on the one Raspberry Pi**. The board was deliberately designed as a single-lane, self-contained, identical unit so it can be built once and cloned across all 32 lanes regardless of which legacy controller it displaces.

So a fully built pair = **1 Raspberry Pi + 1 shared T-Camera + 2 identical controller boards** (one per lane). (Board contract: `docs/phase8b_pcb_revB_spec.md` "Scope unit".)

### 1.6 The mixed-chassis, 16-pair fleet

All 16 pairs (32 lanes) are **AMF 82-70 machines**, but the *controller* bolted onto each machine differs by lane — this fleet is **mixed-chassis**. The two characterized pairs:

| Lane pair | Machine | Retrofit controller as found | Notes |
|---|---|---|---|
| **21 / 22** (pilot pair; also the bench spare) | AMF 82-70 on the original **SS (solid-state) chassis** | **Omega-Tek "Omniboard"** (CMOS logic) + Omega-Tek Expander card (dual-optocouplers) + a "ZOT" board (foul lights only) | Omega-Tek (Shelby, OH) appears **defunct** → strong continuity risk; this is a primary motivation for owning the brain |
| **11 / 12** | AMF 82-70 | Active Technology **"Ultra 98 Plus" 82-70 MP chassis** (microprocessor, ~1997) | An "MP"-class microprocessor controller |
| Other 12 pairs | AMF 82-70 | Likely additional/mixed controller types | Not yet individually characterized |

The fleet is mixed at the *controller* layer but **common at the machine layer**. This is the key engineering leverage of Phase 8 and the reason the controller board targets the machine, not any controller brand:

> **Develop once, deploy on any 82-70 lane.** The Pi-controller interfaces to the common 82-70 machine through its standard wiring connectors (**C1** and **C2A**, see §1.8). Because every lane is the same machine, a single board design + a small **per-chassis adapter harness** (which maps the board's function-named terminals to that specific chassis's connector cavities at cutover) works on every lane. No machine-specific cavity numbers are baked into the board's copper — they are resolved in the harness. (Board contract §1 "Harness" and §7; mixed-fleet rationale: `docs/HANDOFF.md` §1.)

A practical consequence for the technician: the **spare 82-70 cabinet on the bench is an Omega-Tek (SS-chassis) unit** and is the development/validation specimen for Track B. Findings from one chassis transfer to the machine layer of all lanes, but **connector-cavity assignments are verified per chassis at cutover** (some retrofits re-routed harness landings — e.g. the bench SS+Omega-Tek pair lands the M2 "sweep-reverse" signal on C2A, whereas the OEM factory chassis lands it on C1).

### 1.7 The zero-EOL-hardware strategy (and the safety stance that comes with it)

Phase 8's organizing principle is **eliminate every end-of-life dependency** by moving the intelligence onto commodity, in-supply parts:

- **Raspberry Pi** (per pair) — runs the scoring engine and the control FSM.
- **Custom controller PCB** (per lane, the "rev-B" board) — built from standard, JLCPCB-stocked parts (see the part anchors in §1.10).
- **RP2040 co-processor** (one per board) — a Raspberry Pi Pico stamp module handling fast/safety-critical timing.
- **Existing T-Camera + a commodity USB capture dongle** — reused; the EOL T-VISION/VDB/ETHost path is bypassed.

Owning the brain shifts the burden to *us* to preserve the machine's safety behavior. The non-negotiable rule, stated in the board contract, is that **the controller board must never be the only safety device**:

- The machine's upstream **Stop switch + C.I.S. (Cover Interlock Switch) → master circuit breaker** chain stays in hardware and remains the final physical stop.
- The **TB/SC table-sweep collision interlock** stays as a hardware loop that can drop the motor relays without any software involvement.
- The motors' **regenerative braking** (in the relay normally-closed contacts) stays in hardware.
- The board's motor-relay coils are powered through a hardware **relay-enable rail** that drops (de-energizes the relays) unless *all* of these independent permissions are simultaneously true: the **NE555 hardware watchdog** is being kicked by the Pi, the Pi has asserted **ARM**, the **RP2040 health line (RP2040_OK)** is high, and the external **TB/SC** and **Stop/CIS** loops are closed. The Pi physically cannot bypass these in software.
- The board **fails open** (motion-dead) on loss of logic power, watchdog kick, RP2040 health, arm permission, or the hardware interlock.

This layered model is the heart of Track B and is detailed in **§19, Safety Architecture**. It is introduced here because no part of this system should be operated, repaired, or modified without understanding it first.

### 1.8 The machine interface at a glance (C1 / C2A / TAC)

The controller connects to each 82-70 machine through two standard AMP "M"-type connectors plus a gripper tap strip. You will see these names throughout the manual:

| Interface | Size | Carries (functional) | Direction |
|---|---|---|---|
| **C1** | 34-pin | Motor/relay outputs + power (sweep S, table T, spot SP, back-end BE, master M, sweep-reverse M2, ball-return M1; motor windings; supply) | primarily controller **outputs** to machine |
| **C2A** | 50-pin | Switch/control signals: cams, grippers (via TAC), pushbuttons, foul, manual controls | primarily machine **inputs** to controller |
| **TAC** | gripper tap strip | The 10 gripper switches **GS1–GS10** are tapped onto this strip, which lands on C2A | inputs (pin sense) |

These are the *machine-side* connectors. The Phase 8 board does **not** expose C1/C2A pin numbers directly; it exposes **function-named terminal blocks** (J_FAST_IN, J_SLOW_IN_A/B, J_MOTION_*, J_LAMP_LED, J_SAFETY, plus J_PI and J_PWR), and a per-chassis **adapter harness** maps those to the actual C1/C2A cavities at cutover. The board's connector inventory and the function↔connector mapping are in **§5, The Rev-B Controller Board**; the machine-side connector pinouts are in **§3, The AMF 82-70 Machine & Control Theory**. (Connectors: `docs/phase8_8270_SYSTEM_REFERENCE.md` §4; harness contract: `docs/phase8b_pcb_revB_spec.md` §7.)

> ⚠️ **Exact C1/C2A cavity numbers are chassis-specific and several are deferred to cutover.** Per-gripper cavity labels, per-cam→cavity labels, and the exact safety-interlock and C1/C2A terminal landings are intentionally captured on cutover day (easier with the machine apart and a live feed). They do **not** gate the board because everything is function-named and harness-resolved. Do not treat any specific cavity number in this manual as final for a given chassis without on-machine verification. (`docs/HANDOFF.md` §3.)

### 1.9 How to use this manual

- **Operate the system today (scoring only):** read this chapter for orientation, then **§18, Track A — Camera Scoring** and follow `docs/phase8_trackA_golive_runbook.md`. Track A is the only part currently cleared to go live.
- **Understand the pinsetter you are servicing:** read **§3, The AMF 82-70 Machine & Control Theory** (mechanism, cams, the cycle of operation) before touching anything mechanical.
- **Work on the controller board:** read **§5, The Rev-B Controller Board** for the architecture, connectors, and part list, then **§19, Safety Architecture** before powering it near a machine. The authoritative electrical contract is `docs/phase8b_pcb_revB_spec.md`; the as-built wiring source of truth is the netlist generator `scripts/generate_kicad_netlist_revB.py`.
- **Flash or debug the co-processor:** read **§15, RP2040 Firmware**. The authoritative pin map is `firmware/rp2040/config.h`, which is itself derived from the board netlist generator.
- **Bring up a board or plan a lane cutover (Track B):** read **§21, Track B Bring-up & Cutover** and `docs/phase8_trackB_controller_cutover_runbook.md`. **Do not energize a live machine from the board until the full hardware safety chain is bench-proven.**

**Accuracy convention used throughout this manual:** every pinout, part number, net name, GPIO assignment, and value is grounded in a live source file. Where a value could not be confirmed from a source, it is flagged inline as `(VERIFY: …)`. Treat such flags as work items, not facts.

**The source files this chapter is grounded in (read these before trusting any derived table):**

| Source file | Authority for |
|---|---|
| `docs/phase8_8270_SYSTEM_REFERENCE.md` | Controller behavioral spec: machine, FSM, cam timing, I/O, safety, connectors |
| `docs/phase8b_pcb_revB_spec.md` | The hard electrical contract for the controller PCB (domains, safety rail, outputs, inputs, connectors, power) |
| `docs/phase8_session_close_2026-06-03.md` | Current live project state (rev-B routed + fab-package, field session complete) |
| `docs/HANDOFF.md` | Deeper background + mixed-fleet reality + artifact index |
| `scripts/generate_kicad_netlist_revB.py` | **As-built board wiring** (the single source of truth for pin/net/part assignments) |
| `firmware/rp2040/config.h`, `firmware/rp2040/main.c` | RP2040 pin map, timing, UART protocol, safety role |
| `lane_node/controller_io.py` | Pi-side hardware I/O object (MCP23017 bit maps, gripper read, watchdog/arm) |
| `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/02_…_BOM_JLC.csv` | Locked part numbers (LCSC) + designators for the fabricated board |

### 1.10 Hardware identity — confirmed part anchors

These are the **confirmed, fab-locked** part choices for the rev-B controller board, taken directly from the JLCPCB upload BOM (`kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/02_wsl-phase8b-revB_BOM_JLC.csv`) and cross-checked against the netlist generator. Use these exact parts; flag any other document that disagrees. (Full per-component BOM, ratings, and the depopulated/DNP list are in **§5, The Rev-B Controller Board** and **§23, Bill of Materials**.)

| Role | Part | Package | Designators | LCSC | Notes |
|---|---|---|---|---|---|
| Motor-control relay | **Omron G5LE-14, 5 VDC coil**, SPDT | THT (`Relay_SPDT_Omron-G5LE-1`) | K1–K6 (K7/M1 = DNP) | **C116963** | **5 V coil — NOT 12 V or 24 V.** 6 populated + 1 DNP (M1). The board only closes/opens *dry contacts* in existing machine control circuits; it never carries motor current. |
| I/O expander | **MCP23017** (I²C 16-bit GPIO) | SOIC-28W | U1, U2, U3 | **C47023** | **I²C part — NOT the SPI MCP23S17.** Run at **3.3 V** for Pi-safe I²C. |
| Optocoupler (input isolation) | **PC817B** | DIP-4 | U4–U35 (32 pcs) | **C5692981** | Isolates every machine input; logic side at 3.3 V, **active-low at the MCU**. |
| Watchdog timer | **NE555** (bipolar) | SOIC-8 | U36 | **C7593** | Bipolar NE555 (`NE555DR` class) — hardware watchdog monostable. |
| Reverse-polarity / input protection | **SS14** Schottky | SMA | D17 | **C2480** | On the 5 V input. |
| Relay coil flyback / timing diodes | 1N4148WS | SOD-323 | D1,D3,D5,D7,D9,D11,D15,D16 | C118873 | |
| Relay coil drivers | MMBT3904 NPN | SOT-23 | Q1–Q6, Q15, Q16 | C909754 | Low-side coil drive + safety-chain AND transistors |
| Status-LED drivers | 2N7002 N-FET | SOT-23 | Q8–Q11 | C916396 | Low-side LED drive for the 4 status lamps |
| Watchdog kick FETs | AO3400A N-FET | SOT-23 | Q12, Q13 | C20917 | |
| Rail pass element | AO3401A P-FET | SOT-23 | Q14 | C347476 | Relay-enable-rail pass transistor |
| Isolated field-wetting supply | **TRACO TMA-0505S** DC/DC | THT | ISO_WET | *(see §23)* | 5 V→5 V isolated; powers the dry-contact wetting rail, keeping FIELD_GND off logic ground. (Not in the JLC SMT BOM; placed/hand-fitted — `(VERIFY: LCSC/MFR for TMA-0505S — not present in the JLC SMT upload BOM)`.) |
| Co-processor | **Raspberry Pi Pico (RP2040 stamp module)** | module footprint | RP_PICO | *(module)* | Owns fast cam/ball inputs + the RP2040_OK safety line. Stamp module chosen for v1 to de-risk the QFN. |

**Board form factor (confirmed):** **250 × 225 mm, 4 copper layers.** Per-lane, fully integrated, function-named connectors. (`docs/phase8_session_close_2026-06-03.md` §2; `docs/phase8b_pcb_revB_spec.md`.)

**RP2040 known-correct pin anchors** (from `firmware/rp2040/config.h`, derived from `scripts/generate_kicad_netlist_revB.py` `block_rp2040()` — these override the stale `docs/phase8_channel_allocation.md` GPIO column):

| RP2040 signal | GPIO | Notes |
|---|---|---|
| Fast inputs (6 cams + 2 ball beams) | **GP6 – GP13** | SA=GP6, SB=GP7, SC=GP8, TA1=GP9, TA2=GP10, TB=GP11, DIELL-L=GP12, DIELL-R=GP13; **active-low** (machine contact closed ⇒ GPIO low) |
| RP2040_OK (rail permission) | **GP2** | HIGH = permit motion; LOW/Hi-Z = drop the relay-enable rail (fail-safe) |
| UART to Pi | **GP0 (TX) / GP1 (RX)** | uart0, 115200 8N1 |

> ⚠️ **Do not use the GPIO column in `docs/phase8_channel_allocation.md` §2** — it assigns the fast inputs to GP0–GP7 and is **stale**. The as-built board uses GP6–GP13; `config.h` and the netlist generator are correct.

### 1.11 Acronym & glossary seed

This is the starting glossary; later sections expand individual entries. Where an item's deep characterization lives outside the named live files, that is flagged.

| Term | Expansion / meaning |
|---|---|
| **AMF 82-70** | The automatic pinsetter model used on all 32 lanes. The machine is retained; only its controller is replaced. Also written "8270." |
| **VDB** | **V**ideo **D**isplay **B**oard — the legacy QubicaAMF per-lane scoring computer being retired (one per lane). |
| **ETHost** | The legacy QubicaAMF gateway that networked the VDBs to Conqueror; being retired. |
| **T-VISION** | The legacy QubicaAMF board that read the T-Camera for scoring; bypassed — the Pi reads the camera's composite video directly via a USB dongle. |
| **T-Camera** | The QubicaAMF monochrome PAL camera (one per pair) that views both decks. Reused by Track A; its composite-video output is tapped. |
| **Track A** | The camera pin-scoring effort (read-only, code-complete). See §18. |
| **Track B** | The pinsetter controller-replacement effort (safety-critical, in development). See §5, §19, §15, §21. |
| **Conqueror (Pro)** | The legacy bowling-operations / front-desk software being replaced. |
| **SS chassis** | The original AMF **S**olid-**S**tate control chassis (5-board). Lanes 21/22 use the SS chassis with an Omega-Tek retrofit. |
| **MP chassis** | AMF's later **M**icro**P**rocessor control chassis — a drop-in replacement for the SS chassis using the same machine I/O. The Phase 8 Pi-controller is conceptually a modern MP chassis. Lanes 11/12 use an MP-class controller (Active "Ultra 98 Plus"). |
| **Omega-Tek / Omniboard** | The aftermarket CMOS retrofit controller on lanes 21/22 (vendor appears defunct). |
| **cam** | A rotating timing cam on the machine whose lobe trips a microswitch at a specific shaft angle, signaling a mechanical position. The six the controller reads are **SA, SB, SC** (sweep cams) and **TA1, TA2, TB** (table cams). See §3 for the angle/role table. |
| **SA / SB / SC** | Sweep cams. SA: stop sweep run-through @270° and stop @360°/zero. SB: guard stop @66°, initiate table spotting @186°. SC: sweep-under-table window (86–243°) → **interlock**. |
| **TA1 / TA2 / TB** | Table cams. TA1: table-zero stop @355° (and resets the time delay @185°). TA2: @260°, triggers sweep run-through + pin-lamp latch + the ball/strike decision. TB: table-sweep interference window (105–255°) → **interlock**. |
| **GS1–GS10** | The 10 **G**ripper **S**witches (one per pin spot) that sense which pins are standing. Tapped onto the **TAC** strip → C2A. Read by the Pi as a 10-bit standing-pin mask. |
| **TAC** | The gripper-switch tap strip on the machine; the 10 gripper switches land on it, and it lands on C2A. |
| **DIELL** | The brand of through-beam **ball detector** used on these lanes as the cycle trigger (it stands in for the OEM cushion start switch, "SS"). Wired NPN, **active-low**: beam intact ≈ rest, beam broken (ball passing) asserts the input low. (Detailed electrical figures — rest ≈ 16 V, broken ≈ 0.7 V — are recorded in project memory `project_amf_8270_interface_research`, not in the named live files. `(VERIFY: 16 V rest / 0.7 V broken figures against a live source before relying on exact voltages.)`) The board reads two beams per pair: **DIELL-L / DIELL-R**. |
| **SS (start switch)** | The OEM cushion-actuated start switch that triggers a machine cycle when a ball reaches the cushion. On these lanes its role is served by the **DIELL** ball detector. |
| **cam-stop** | A controller behavior: the controller reads a cam reaching a stop angle and drops the relevant motor relay. On the 82-70 these stops are *controller logic*, not a hardwired motor latch — so the Pi/RP2040 times them, while TB/SC interlock + braking are the hardware backstops. (`docs/phase8_8270_SYSTEM_REFERENCE.md` §5.) |
| **C1** | The 34-pin AMP "M"-type machine connector — primarily motor/relay outputs + power. See §1.8. |
| **C2A** | The 50-pin AMP "M"-type machine connector — primarily switch/control/gripper/cam signals. See §1.8. |
| **FSM** | **F**inite-**S**tate **M**achine — the software that reproduces the 82-70 sequence of operation (`lane_node/cycle_control_8270.py`). States include POWER_OFF, MANUAL_INTERVENTION, READY, SWEEP_TO_GUARD, GUARD_DELAY, TABLE_DETECT, RUNTHROUGH, SPOTTING, TABLE_FINISH, FAULT. See §3/§21. |
| **RP2040** | The microcontroller (on a Raspberry Pi Pico stamp module) that is the fast + safety half of each controller board: it reads the fast cam/ball inputs, pushes edge events to the Pi over UART, and drives the **RP2040_OK** rail-permission line. See §15. |
| **RP2040_OK** | The RP2040's fail-safe-low health/permission output (GP2). HIGH only when the firmware is healthy and past boot settle; one of the series conditions gating the relay-enable rail. |
| **MCP23017** | The I²C 16-bit I/O expander (3 per board) used for the slow inputs (grippers/switches) and the relay/lamp outputs. Run at 3.3 V. |
| **NE555 watchdog** | A hardware monostable timer that the Pi must repeatedly "kick"; a missed kick drops the motor-relay rail. The board-level sibling of the FSM's software watchdog. |
| **relay-enable rail** | The hardware-gated supply for the on-board motor-relay coils. Drops unless watchdog + ARM + RP2040_OK + TB/SC + Stop/CIS are all satisfied. The board cannot bypass it in software. |
| **ARM** | A dedicated Pi GPIO permission, asserted only after a verified operator-safe state, that is one of the series conditions for the relay-enable rail (implements the OEM "Power-Down / require First Ball Zero on power restore" rule in part). |
| **TB/SC interlock** | The table-sweep collision interlock: cams TB and SC wired in parallel into the control path so the motor relays drop on a collision course. Preserved as a **hardware** loop (board input J_SAFETY); never softened to an advisory firmware-only input. See §19. |
| **Stop / C.I.S.** | The **Stop** switch and **C**over **I**nterlock **S**witch (plug-duct cover), wired in parallel; either one cuts the rear-panel master circuit breaker → whole machine dead. The final physical stop; preserved upstream of the board. |
| **PCBA** | **P**rinted **C**ircuit **B**oard **A**ssembly — a populated board (vs a bare PCB). The rev-B *bare-PCB* fab package exists; full PCBA (population/assembly) is a remaining Track-B item. |
| **DNP** | **D**o **N**ot **P**opulate — a footprint present in the layout but intentionally left unpopulated. On rev-B this includes the **M1** (ball-return) relay channel (8 parts) — M1 is unverified on these chassis and the FSM does not drive it — plus the value-DNP RC-snubber/MOV arc-suppression footprints on the motion outputs (populated only after at-machine load characterization). Current fab package: 27 DNP refs, all excluded from the assembly BOM/placement files. |
| **opto / optocoupler** | An isolation device (here, PC817B) that passes a signal across a galvanic barrier with light, so a machine-side fault cannot backfeed the logic/Pi side. Every machine input crosses an opto; outputs cross relay/PhotoMOS packages. |
| **PhotoMOS** | A solid-state relay using a MOSFET output stage. Referenced in design history; rev-B status indication moved to board-driven LEDs (the PhotoMOS lamp drivers were removed), so PhotoMOS parts are not in the rev-B baseline. |
| **wetting (field-wetting) supply** | A small **isolated** DC source on the board that "wets" the dry-contact inputs (provides the small sense current through a closed machine contact). Isolated from logic ground via the TMA-0505S; its return is **FIELD_GND**. |
| **FIELD_GND vs GND** | Two intentionally separate grounds. **GND** = logic ground (Pi side of the optos/relays). **FIELD_GND** = the isolated machine-sense ground. They share zero nodes — the isolation barrier is intact. |
| **VIXLW dongle** | The commodity USB composite-video capture device (UVC-class, enumerates as "USB Video") used to read the T-Camera into the Pi for Track A. |
| **KX relay** | The legacy relay that gated pin data to the old scorer; **omitted** in Phase 8 because camera scoring (Track A) replaces that data flow. |

---

*Next: **§2, System Block Diagram & Signal Flow** (or your manual's actual §2 title) — the end-to-end picture of camera → Pi → scoring display and machine ↔ board ↔ Pi. Then **§3, The AMF 82-70 Machine & Control Theory**.*


## 2. System Architecture & Signal Chain

This section describes how a Westside Lanes Phase 8 lane pair is wired and how a
signal flows from the pinsetter, through the controller electronics, up to the
overhead display and back down as a motion command. Read it before touching any
board: it defines what every wire, board, and chip does and — just as important —
what each one is *not* allowed to do.

Scope reminder: a **lane pair** (e.g. lanes 21 + 22) is the unit. The pair shares
**one Raspberry Pi** and **one overhead camera**, but each lane gets its **own
controller board** and its own machine harness. Everything in this section is
"per pair" except where a table is explicitly marked "per board / per lane."

The whole replacement runs in two functional tracks, on the same hardware:

- **Track A — camera scoring.** Detect which pins are standing after each ball
  from an overhead camera, and report the score to the server. Code-complete; see
  Section 18 (Camera Scoring Subsystem) for the optics and detection math.
- **Track B — controller replacement.** Replace the AMF 82-70 pinsetter's
  control brain (cycle the machine, run the safety interlocks). The rev-B board
  in Sections 3 (Hardware / PCB) and 4 (Firmware & Control FSM) is the Track-B
  hardware. As of this writing the bare PCB is fab-ready but **not yet built or
  cut over** — the existing OEM controller still runs the machines.

The two tracks are deliberately decoupled: scoring must never be able to stop the
machine, and the machine controller must never depend on the camera to cycle. See
§2.6.

---

### 2.1 End-to-End Block Diagram

```
                        ┌──────────────────────────────────────────────────────────┐
                        │                    WSL-SRV  (server PC)                    │
                        │  lane_node_server (ws://…:8765)  ·  wsl_api.py (:5000)     │
                        │  scoring store + desk UI + overhead-display feed           │
                        │  IP 192.168.4.103  (eero subnet 192.168.4.0/22)            │
                        └───────────────▲──────────────────────────┬────────────────┘
                                        │  WebSocket (JSON)         │  HTTP
                                        │  ball/foul/heartbeat ▲    │ display feed ▼
                                        │  open/close/cycle    ▼    │
                    ┌───────────────────┴───────────────────┐   ┌──┴───────────────┐
                    │        Raspberry Pi  (one per pair)    │   │ Overhead monitor │
                    │  ─ lane_node.py  (Track A scoring)     │   │  (per pair, HDMI/ │
                    │  ─ controller_daemon.py (Track B FSM)  │   │   network feed)   │
                    │  ─ camera.py / pin_detect.py           │   └───────────────────┘
                    │                                        │
                    │  USB ◄── VIXLW capture dongle ◄── T-Camera (1 per pair,
                    │           (composite→USB)              behind the pins, sees
                    │                                        BOTH decks, 720x576 PAL)
                    │                                        │
                    │  I2C bus-1 ──┐        I2C bus-2 ──┐    │  (i2c-gpio)
                    │  UART0 ──────┤        UART1 ───────┤   │
                    │  GPIO arm/INT/wdog (per board) ────┤   │
                    └───────┬──────┴────────────┬─────────┴──┘
                            │ board harness      │ board harness
                ┌───────────▼──────────┐  ┌──────▼───────────────┐
                │  rev-B board — LANE 21│  │  rev-B board — LANE 22│   (identical boards)
                │  RP2040 + 3×MCP23017  │  │  RP2040 + 3×MCP23017  │
                │  PC817 opto-in bank   │  │  PC817 opto-in bank   │
                │  G5LE relay-out bank  │  │  G5LE relay-out bank  │
                │  NE555 watchdog       │  │  NE555 watchdog        │
                │  relay-enable rail    │  │  relay-enable rail     │
                └───┬─────────────┬─────┘  └───┬─────────────┬──────┘
       J3/J4/J5     │             │ J6–J12     │             │
       field inputs │             │ motion out │             │
       J14 safety   │             │ J13 LEDs   │             │
                ┌───▼─────────────▼───┐    ┌───▼─────────────▼───┐
                │  AMF 82-70 machine   │    │  AMF 82-70 machine   │
                │  LANE 21             │    │  LANE 22             │
                │  via C1 + C2A conns  │    │  via C1 + C2A conns  │
                │  cams/grippers/DIELL │    │  cams/grippers/DIELL │
                │  S/T/SP contactors   │    │  S/T/SP contactors   │
                │  mask LEDs (ours)    │    │  mask LEDs (ours)    │
                └──────────────────────┘    └──────────────────────┘
```

Read the diagram top-to-bottom for a **motion command** (server → Pi FSM →
board → machine), and bottom-to-top for **scoring** (machine ball-detect →
board → Pi → server → display). The two flows share the board and the Pi but use
different chips and different links — see §2.4 and §2.5.

---

### 2.2 Components of the Signal Chain

| Element | Count | Where it lives | Role |
|---|---|---|---|
| WSL-SRV server | 1 site-wide | Back office, IP **192.168.4.103** | Runs `lane_node_server` (WebSocket :8765) + `wsl_api.py` (:5000). Holds the scoring store, the desk UI, and the overhead-display feed. Sends high-level commands (open/close/cycle); receives ball/foul/heartbeat. |
| Raspberry Pi | 1 per pair | Lane-pair enclosure | Runs the cycle FSM, scoring, and all comms. The "slow brain." See §2.3. |
| rev-B controller board | 1 per lane (2 per pair) | Lane-pair enclosure | Self-contained per-lane controller: RP2040 + 3× MCP23017 + opto inputs + relay outputs + NE555 watchdog + relay-enable rail. The "fast/safe hands." See Section 5. |
| AMF 82-70 pinsetter | 1 per lane | At the lane | The mechanism being controlled. Cams, grippers, DIELL ball detector, sweep/table motor contactors, mask housings. Interfaced via connectors **C1** (motor/relay/power) and **C2A** (switches/control). See Section 3 (Machine Overview). |
| T-Camera (QubicaAMF) | 1 per pair | Behind the pins, looking toward the bowler | Single PAL camera that sees **both** decks of the pair in one 720×576 frame. Scoring optic only. See Section 18. |
| VIXLW USB capture dongle | 1 per pair | Plugged into the Pi USB | Converts the T-Camera's composite/PAL video into a USB frame source for OpenCV/PyAV. Owned and on hand. |
| Overhead display | 1 per pair | Above the lanes | Shows the live score. Driven from the server's display feed, not from the board. |
| 5 V PSU | 1 (sized per pair) | Lane-pair enclosure | External regulated 5 V for board input power, the RP2040/Pico (VSYS), the NE555 watchdog rail, the opto logic-side pull-ups, and the relay coils. The **MCP23017s + I²C bus run on Pico-derived 3.3 V, not 5 V.** **Off-board.** See §2.7 and Section 6 (Power). |
| Machine adapter harness | 1 per lane | Between board and C1/C2A | Maps the board's function-named connectors to the chassis-specific C1/C2A cavities at cutover. Keeps uncertain cavity bindings out of copper. See Section 14 (Connectors & Harness). |

---

### 2.3 The Compute Split — why a Pi *and* an RP2040 per lane

The controller intelligence is split across three tiers. This split is the single
most important architectural decision in Phase 8; do not collapse it.

| Tier | Hardware | Responsibilities | Why here |
|---|---|---|---|
| **Server** | WSL-SRV PC | Scoring store, desk/operator UI, overhead-display feed, high-level lane commands (open/close/cycle/reset/power). | Centralized, not real-time, not safety-critical. A server outage must **not** stop a running machine. |
| **Slow brain** | Raspberry Pi (1 per pair) | The cycle **FSM** (`cycle_control_8270.py`), camera **scoring** (`camera.py` / `pin_detect.py`), all **comms** (WebSocket to server, UART to each RP2040, I2C to each board). Two independent control loops: `controller_daemon.py` (Track B) and `lane_node.py` (Track A). | Runs Python, has the camera and the network. The FSM logic and scoring math are complex but tolerate ~10–20 ms scheduling jitter. |
| **Fast/safe hands** | RP2040 (1 per board / per lane) | The **8 latency-critical fast inputs** (6 cams + 2 DIELL ball beams), the **RP2040_OK** rail-permission line, the **motion max-run backstop** (8 s guarded-motor timeout), and pushing cam/ball **events** to the Pi over UART. | Cam edges and motor-stop timing on a 12-RPM machine must not wait on Linux scheduling, so the fast inputs live on the RP2040 and its `RP2040_OK` line gates the relay-enable rail directly, independent of the Pi. **Firmware v0.1.0 provides RP2040 health + the max-run backstop; per-cam-edge cam-stop _overrun_ enforcement is deferred to v1.1** (needs the cutover cam-polarity capture — `main.c`). |

Each lane's board also carries **three MCP23017 I2C I/O expanders** that handle the
non-latency-critical I/O — the grippers, the slow switches, and the relay/lamp
command bits. They sit on the Pi's I2C bus, not the RP2040.

| MCP23017 | I2C addr | Direction | What it carries |
|---|---|---|---|
| IN-A (U1) | **0x20** | all inputs | GS1–GS10 grippers + GP, OS, BS, PBZ, PBC, Foul (16/16 pins used) |
| IN-B (U2) | **0x21** | all inputs | 10th-frame + manual T/S/SWS/SWSR + spare/AUX (5 used, 11 spare) |
| OUT-A (U3) | **0x22** | all outputs | 7 relay-drive bits (S/T/SP/BE/M/M2/M1) + 4 status-LED bits |
| OUT-B (0x23) | not populated | — | Optional physical pin-lamp pindicator. **Omitted** in baseline because the camera supplies pin state. |

The three expanders are MCP23017 (**I2C**, LCSC **C47023**, `MCP23017-E/SO`) — **not**
the SPI MCP23S17. Confusing the two will not enumerate on the bus.

**Division of labor in one sentence:** the Pi *decides* (FSM + scoring), the
RP2040 *guards* (fast inputs + hardware stop), and the MCP23017s *fan out* the
Pi's slow reads and writes.

---

### 2.4 Per-board Independent I2C and UART Buses

The two boards on a pair are **electrically identical** ("design one, clone it").
This is achieved by giving each board its **own I2C bus** and its **own UART**, so
each board can use the same fixed MCP23017 addresses (**0x20/0x21/0x22**; 0x23 reserved, unpopulated) and the same
firmware without address collisions.

| Pi resource | Board 21 (example) | Board 22 (example) | Notes |
|---|---|---|---|
| I2C bus | hardware `i2c-1` (GPIO2/3) | second bus via `dtoverlay=i2c-gpio` | Each board repeats the same three addresses (0x20/0x21/0x22; 0x23 reserved) on its own bus. (VERIFY: the exact GPIO pins for the i2c-gpio second bus — `# assign` in `phase8_channel_allocation.md` §4 and `# CONFIRM` in `controller_daemon.DEFAULT_BOARDS`.) |
| UART to RP2040 | one PL011/mini-UART | a second UART | Point-to-point, 115200 8N1, newline-JSON. (VERIFY: production maps lane 21→`/dev/ttyAMA0`, lane 22→`/dev/ttyAMA1` in `DEFAULT_BOARDS`, but those are placeholders flagged `# CONFIRM`.) |
| Watchdog kick | one GPIO per board | one GPIO per board | (VERIFY: `DEFAULT_BOARDS` placeholders lane 21 = GPIO12, lane 22 = GPIO6; the legacy Phase-8a node used GPIO12 board-level.) |
| ARM (relay-enable permit) | one GPIO per board | one GPIO per board | (VERIFY: `DEFAULT_BOARDS` placeholders lane 21 = GPIO26, lane 22 = GPIO13.) |
| MCP INT lines | IN-A INT, IN-B INT | IN-A INT, IN-B INT | Change-interrupt to the Pi (not polling). (VERIFY: exact GPIOs `# assign` in §4.) |

Why a dedicated UART instead of putting the RP2040 on the I2C bus: the RP2040 must
**push** cam/ball events the instant an edge fires — an I2C slave can only respond
when polled, which would add latency to the safety-critical path and contend with
the three MCP23017s. SPI was rejected for the same poll-only reason plus extra
pins. See `phase8_channel_allocation.md` §7 for the full link trade study.

---

### 2.5 The Two Live Signal Flows

#### 2.5.1 Scoring flow (machine → display) — Track A, runs today

```
ball thrown ─► DIELL beam breaks ─► PC817 opto (active-low) ─► RP2040 GP12/GP13
   │                                                            │
   │  (in the camera-driven model, the DIELL break is also the trigger to
   │   wait the settle window, then capture)
   ▼
RP2040 pushes {"ev":"ball","src":"L"} over UART  ──►  Pi
   │                                                   │
   ▼                                                   ▼
Pi (lane_node.py) waits SETTLE_S (~2.5 s) ──► grabs a frame from the T-Camera
   via the VIXLW USB dongle ──► pin_detect.py: difference-from-empty over 20 fixed
   pin-cap ROIs ──► 10-bit standing-pin mask per deck ──► map deck→lane
   │
   ▼
Pi sends BALL_EVENT (with pin_mask, or awaiting_manual=True on no/failed capture)
   over WebSocket ──► WSL-SRV scoring store ──► overhead display updates
```

Safe-degradation rule: if the camera is not ready or a capture fails,
`detect_current_pins()` returns `None` and the Pi emits `awaiting_manual=True`,
so the desk operator scores the ball by hand. A real ball **never** records a
bogus auto-score. (Source: `lane_node.py` `detect_current_pins` / `_settle_capture_emit`.)

#### 2.5.2 Control flow (server/sensors → machine) — Track B, bench-gated

```
cam edge (e.g. SB guard at 66°) ─► PC817 opto ─► RP2040 GPx (debounced)
   │
   ▼
RP2040 pushes {"ev":"cam","id":"SB","e":"f"} over UART ──► Pi
   │
   ▼
Pi controller_daemon.py: link.apply_events(fsm) ──► cycle_control_8270 FSM advances
   ──► fsm.poll() sets the next motor/solenoid/lamp outputs AND kicks the NE555
   │
   ▼
Pi writes the relay-command bit over I2C ──► MCP23017 OUT-A (0x22) ──► MMBT3904
   driver ──► G5LE relay coil ──► relay CONTACT closes the EXISTING machine
   control circuit (e.g. the sweep contactor coil) at J6–J12
   │
   ▼
the machine's OWN contactor switches the 115 VAC motor (NOT the board)
```

Grippers, GP, BS, PBZ, Foul (the "slow" inputs) take a parallel path: machine
contact → PC817 opto → MCP23017 IN-A/IN-B (I2C) → Pi reads them inside the FSM
(`read_grippers`, `gp_closed`, `bs_closed`) or as edge events in the daemon
(`read_input` for PBZ/BS/Foul).

---

### 2.6 Track Decoupling and the Safety Rail (overview)

Two non-negotiable couplings define the safety architecture. Both are covered in
depth in Section 16 (Control FSM) and Section 19 (Safety System); here is the
architectural summary.

1. **Scoring must not be able to stop the machine.** Track A (`lane_node.py`) and
   Track B (`controller_daemon.py`) are separate processes/loops on the Pi. The
   camera and the WebSocket can fail without affecting machine motion. In the
   Phase-8a scoring pilot the server replies to a ball with a CYCLE command, but
   that pilot drives a *pulse* relay on the existing controller, not the live
   motors. At Track-B cutover the cycle runs on **cam timing**, fully decoupled
   from camera capture (`_settle_capture_emit` docstring warns about this exact
   timing coupling).

2. **The machine controller must fail safe without the Pi.** Every motion-relay
   coil (S, T, SP, BE, M, M1, M2) is powered through a single series
   **relay-enable rail** (`RELAY_ENABLE_RAIL`). The rail drops — all motors stop —
   if **any** of these go false:

   | Rail condition | Source | Fail-safe default |
   |---|---|---|
   | Watchdog OK | NE555 monostable (U36), kicked by the Pi (`WDOG_KICK`) | false (drop) |
   | ARM OK | Pi `ARM_PERMIT` GPIO, asserted only in a safe state | false |
   | RP2040 OK | RP2040 `RP2040_OK` (GP2) heartbeat/permission | false |
   | Cam-stop OK | RP2040 immediate cam-stop drop path | false on reset/fault |
   | TB/SC interlock OK | external hardware NC loop at J14 (the two table/sweep cams in parallel) | open/false |
   | Stop/CIS/master chain OK | external machine safety chain at J14 | open/false |

   The Pi **cannot** bypass these in software. The rail can only de-energize a
   coil; it cannot open a *welded* contact — so the existing master breaker /
   Stop / CIS chain remains the final physical stop (see Section 19, "welded
   contact limitation"). Live motor current always stays on the machine
   contactors; the board only opens/closes isolated dry contacts in the existing
   control circuits.

The RP2040 firmware additionally enforces a **motion max-run backstop**: a guarded
motor (S/T/SP/M1/M2) marked RUNNING for longer than `MAX_MOTION_MS` (8 s, matching
the FSM's `MAX_MOTION_S = 8.0`) latches a fault and drops `RP2040_OK` — UART-
independent, so a hung Pi cannot leave a motor running. (Source: firmware
`main.c` `supervise()`, `config.h`.) The cam-stop *overrun* enforcement is
deferred to firmware v1.1 pending bench confirmation of per-cam edge→angle
polarity.

---

### 2.7 Power and Signal Domains

The board enforces **three electrical domains** kept explicit in net names,
layout rooms (physically banded left/center/right with no-copper gutters), DRC
classes, and silkscreen. Crossing a domain boundary happens **only inside an
optocoupler or relay package** — never on a plain trace.

| Domain | Layout band | Contents | Reference net | Powered from |
|---|---|---|---|---|
| **Logic** | center | Pi link, RP2040, 3× MCP23017, I2C, UART, NE555 trigger, relay-coil drive logic, status-LED FET drivers | `GND` | external 5 V (`VCC_5V`); MCP/I2C run on `VCC_3V3` (from the Pico 3V3 out), **not** 5 V |
| **Machine Sense (Field)** | left | Field side of every PC817 opto (cams, grippers, DIELL, foul, pushbuttons) | `FIELD_GND` | isolated wetting `FIELD_WET_V` from the TMA-0505S DC/DC |
| **Machine Output** | right | Isolated G5LE relay contacts that open/close existing machine control circuits | (machine-side, harness) | **not** sourced by the board — the machine provides 24 VAC / 12 VDC control voltages |

Key isolation facts (verified against the routed board):

- **`GND` and `FIELD_GND` share zero nodes.** Field wetting is generated by a
  **TMA-0505S** isolated 5 V→5 V DC/DC converter (U37), so a dry-contact closure
  on the field side cannot inject into logic ground. (`block_supplies()` in the
  netlist generator; spec §8.3 option 1.)
- **Dry-contact default.** Each input front end is: `FIELD_WET_V → 2.2 kΩ → PC817
  LED → field pin`; the machine contact closes that pin to `FIELD_GND`. Optos are
  **active-low at the logic pin** (contact closed → opto pulls the GPIO/MCP pin
  LOW; idle HIGH via a 10 kΩ pull-up to 3V3). Firmware and `controller_io.py`
  both assume `INPUT_ACTIVE_LOW`. (`opto_input()`; `config.h` electrical-sense
  note.)
- **Per-channel population option.** Each field input can be populated as
  dry-contact wetting *or* 24 VAC/voltage-sense. The default per channel is set
  after at-machine measurement; field A1 measured the machine control voltage at
  **24 VAC** (not 250 VAC) (VERIFY: the routed/fab package intentionally keeps the
  *conservative* 250 VAC creepage rules — LOGIC↔FIELD ≥2.5 mm, LOGIC↔MACHINE
  ≥3.2 mm, output↔output ≥1.5 mm — so the 24 VAC relaxation is an optional future
  shrink, not yet applied).
- **No motor power on the board, ever.** 115 VAC motor current never touches PCB
  copper. The board only commands existing contactors through isolated contacts.
- **Status mask LEDs are in the LOGIC domain.** Dylan's rev-B decision replaced
  the machine's 15 VDC mask-lamp supply with our own LEDs in the mask housings,
  driven from `VCC_5V` through 2N7002 low-side FETs (Q8–Q11) and 330 Ω limit
  resistors. There is **no** isolation barrier on the status-LED path. (Spec §3.3.)

---

### 2.8 On-board vs Off-board

Knowing what is on the PCB versus what plugs into it is essential for service and
spares. The board is **one lane**; the figures below are per board unless noted.

#### On-board (populated on the rev-B PCB)

| On-board element | Designator(s) | Part / value | LCSC | Notes |
|---|---|---|---|---|
| RP2040 module | A1 | Raspberry Pi Pico (SMD footprint) | — | Hand-placed module; the firmware co-processor. |
| I/O expanders ×3 | U1, U2, U3 | MCP23017-E/SO (I2C, SOIC-28W) | **C47023** | IN-A 0x20, IN-B 0x21, OUT-A 0x22. **I2C, not SPI MCP23S17.** |
| Opto-isolators ×32 | U4–U35 | **PC817B** (DIP-4) | **C5692981** | 8 fast (U4–U11) + 24 slow (U12–U35) input channels. |
| Motion relays ×6 | K1–K6 | **Omron G5LE-14, 5 VDC coil**, SPDT | **C116963** | S/T/SP/BE/M/M2. **5 VDC coil — do NOT substitute 9/12/24 V.** |
| Relay M1 (ball return) | K7 | G5LE-14 5VDC | — | **DNP** (not populated) until ball-return is confirmed on the chassis. |
| Relay-coil drivers ×6 | Q1–Q6 | MMBT3904 NPN (SOT-23) | C909754 | Low-side coil drive; flyback diode (1N4148) per coil. |
| Status-LED drivers ×4 | Q8–Q11 | 2N7002 N-MOSFET (SOT-23) | C916396 | L_FIRST/L_SECOND/L_STRIKE/L_FOUL, 330 Ω limit (R90/93/96/99). |
| Watchdog timer | U36 | **NE555DR — bipolar** (SOIC-8) | **C7593** | Monostable; drop rail if not kicked. Bipolar, **not** CMOS/TLC555. |
| Watchdog FETs | Q12, Q13 | AO3400A N-MOSFET | C20917 | Kick gate + watchdog-OK pulldown. |
| Rail pass-FET | Q14 | AO3401A P-MOSFET | C347476 | Series pass device for `RELAY_ENABLE_RAIL`. |
| Rail AND-chain BJTs | Q15, Q16 | MMBT3904 | C909754 | ARM and RP2040_OK series pulldown gate. |
| Isolated field-wetting supply | U37 | **TRACO TMA-0505S** 5→5 V iso DC/DC | — | Generates `FIELD_WET_V` / `FIELD_GND`. |
| Reverse-polarity protect | D17 | SS14 Schottky (SMA) | C2480 | On the 5 V input. |
| Flyback diodes | D1,D3,D5,D7,D9,D11,D15,D16 | 1N4148WS (SOD-323) | C118873 | Across each populated relay coil. |
| Snubber/MOV per motion output | C4–C10, D2,D4,D6,D8,D10,D12,D14 | RC snubber + MOV footprints | — | **All DNP** — fit per output only after load characterization. |
| Test points | TP1–TP16 | pads | — | VCC_5V, GND, VCC_3V3, FIELD_WET_V, FIELD_GND, I2C, watchdog (TRIG/OUT/timing/kick/OK-pulldown), ARM_PERMIT, RP2040_OK, SAFE_STOP_RETURN, RELAY_ENABLE_RAIL. |
| Mounting holes | MK1–MK4 | M3 | — | Excluded from BOM/POS. |

Board physicals: **250 × 225 mm, 4 copper layers.** Board-wide totals: 216
schematic components / 236 board footprints (incl. test pads + mounting holes) /
184 named nets. The current fab package counts **189 non-DNP** assembly refs and
**27 DNP** refs.

#### Off-board (plugs into the board's connectors, or is shared by the pair)

| Off-board element | Connects at | Notes |
|---|---|---|
| **5 V PSU** | J2 (J_PWR, 3-pos 5.08 mm) | External regulated 5 V; sized for worst-case relay-coil load + logic + margin. No PoE in rev-B v1. |
| **Raspberry Pi** | J1 (J_PI, 2×10 IDC) | Carries I2C (SDA/SCL), UART (TX/RX), watchdog kick, ARM permit, MCP INT-A/INT-B, RP2040_OK, 5 V, 3V3, GND. Shared by the pair (one Pi, two J1 ribbons). |
| **T-Camera** | (not on the board) | Composite/PAL → VIXLW dongle → Pi USB. One per pair. Scoring only. |
| **VIXLW USB dongle** | Pi USB | One per pair. |
| **Overhead display** | (not on the board) | Driven from the server. |
| **Mask status LEDs** | J13 (J_LAMP_LED, 6-pos) | Our LEDs in the existing mask housings: VCC_5V, GND, and four LED returns. |
| **Machine field inputs** | J3/J4/J5 | J3 (J_FAST_IN, 10-pos): SA/SB/SC/TA1/TA2/TB/DIELL-L/DIELL-R + 2× FIELD_GND. J4 (J_SLOW_IN_A, 14-pos): GS1–GS10, GP, OS, BS + FIELD_GND. J5 (J_SLOW_IN_B, 12-pos): PBZ, PBC, Foul, 10th, manual T/S/SWS/SWSR, AUX1–3 + FIELD_GND. |
| **Machine motion outputs** | J6–J12 | One isolated 2-pin contact pair per output: J6=S, J7=T, J8=SP, J9=BE, J10=M, J11=M2, **J12=M1 (DNP)**. (5.08 mm MKDS terminal blocks.) |
| **Safety loop** | J14 (J_SAFETY, 4-pos) | Two external NC loops in series feeding the rail: J14-1/2 = TB/SC interlock loop, J14-3/4 = Stop/CIS/master-chain loop. |
| **Machine adapter harness** | J3–J14 ↔ C1/C2A | Per-chassis. Maps the board's function-named pins to the real C1 (34-pin motor/relay/power) and C2A (50-pin switch/control) cavities. See Section 14. |
| **Harness mating plugs** | J3/J4/J5/J13/J14 | Phoenix MC 1,5-ST-3,5 screw plugs (10/14/12/6/4-pos, MFR 1840447/1840489/1840463/1840405/1840382). Ordered with the harness, not placed on the PCB. |

> **Connector designator note (important for service):** the **board** silkscreen
> uses J-numbers (J1=Pi, J2=power, J3=fast in, J4=slow-A, J5=slow-B, J6–J12=motion
> S/T/SP/BE/M/M2/M1, J13=LED, J14=safety). The **netlist-generator source** tags
> the same parts by function name (`J_PI`, `J_FAST`, `J_SLOWA`, etc.). They are the
> same connectors. Go by the J-number on the physical board and the assembly BOM.

---

### 2.9 Why Live Motor Current Never Touches the Board (operating theory)

A recurring question from electricians: "if the board controls the sweep and
table motors, why isn't there a fat motor trace on it?" Because the board never
*switches* motor current — it switches the **coil** of the machine's existing
contactor.

The AMF 82-70 already has heavy contactors that switch the 115 VAC sweep and
table motors, with the OEM's start/run windings, capacitors, centrifugal switches,
and **regenerative braking on the relay normally-closed contacts**. Rev-B replaces
only the *logic that decides when to close those contactors* — it drops a small,
isolated dry contact (a G5LE rated for the coil/control load) into the existing
control circuit. The machine's own iron still slams the motor on and brakes it on
release, exactly as it did under the OEM brain.

This buys two things at once: (1) the board's relays only carry tiny coil
currents, so a common small relay footprint works across all outputs; and (2) the
machine keeps its proven motor-start and braking behavior, so we are not
re-engineering a safety-critical AC power path. The historical AMF MP-chassis
upgrade did exactly this — it replaced the 5-board solid-state logic with a
microprocessor using the *same* machine inputs/outputs. Our Pi-plus-RP2040 board
is, electrically, a modern MP chassis. (Sources: `phase8_8270_SYSTEM_REFERENCE.md`
§0/§4/§5; `phase8b_pcb_revB_spec.md` §3.1.) For the full machine-side description
of contactors, cams, grippers, and the C1/C2A interface, see Section 3 (Machine
Overview) and Section 14 (Connectors & Harness).


## 3. The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing

> **What this section is.** A from-scratch description of the AMF 82-70 pinsetter as a *machine* — its mechanical assemblies, its motors, its position-sensing cams, and the exact step-by-step control sequence it executes for every ball, strike, and foul. **This is the behavior our Raspberry Pi controller reproduces.** The Pi does not invent a new way to run the machine; it reads the same switches and drives the same motor/solenoid/lamp circuits the original AMF "brain" did, in the same order, with the same timing. If you understand this section, you understand what the firmware and the cycle FSM are *for*.
>
> **Why we can replace only the brain.** AMF itself proved this is possible. The microprocessor "MP" chassis (part `#070-009-800`) was a factory **drop-in replacement for the older 5-board Solid-State (SS) chassis**, using the *same machine inputs and outputs* — only the decision-making medium changed (discrete relay/logic → microprocessor). Our Pi controller is, functionally, "a modern MP chassis." The MP wiring schematic (drawing `9807`) deliberately *omits* the microprocessor's internal logic and shows only how the chassis connects to the machine — so that schematic **is** the interface specification, and the omitted logic is exactly the part this manual's firmware and FSM supply.
>
> **Source of truth.** Every machine behavior, cam angle, and sequence step below is taken from the two AMF manuals mined in full: the *8270 MP Operation Training Manual* (PN 610000009) and the *8270 Service & Parts Manual* (PN 610007028, AMF 82-70C, rev 8/95), as distilled into `docs/phase8_8270_SYSTEM_REFERENCE.md` and constrained by the OEM read-through in `docs/phase8_oem_doc_audit_2026-06-02.md`. Where a connector cavity, coil voltage, or lamp voltage is **not** yet confirmed on *our* specific chassis (an SS chassis retrofitted with an Omega-Tek Omniboard on lanes 21/22; a factory Active-98 MP on 11/12), it is marked **(VERIFY: …)** inline. Do not treat a VERIFY value as gospel.

---

### 3.1 The Nine Machine Assemblies

The 82-70 is a **free-fall, string-less, table-and-sweep** pinsetter. Pins are physically set by a **spotting table** that descends with ten gripper cups; a **sweep** rake clears downed pins between balls; and a continuously-running **back-end** circulates pins from the pit back up to the table. The controller's entire job is to start and stop the **sweep motor** and **table motor** at the right cam angles, read the **grippers** and a handful of **switches**, fire the **spot solenoid**, and light the **mask lamps**.

The Service & Parts manual organizes the mechanism into nine assemblies. They are listed here in the order pins flow through them, with the controller-relevant sensors and actuators called out.

| # | Assembly | What it does | Controller-relevant I/O on/near it |
|---|---|---|---|
| 1 | **Cushion** | Backstop that absorbs ball/pin impact at the pit end. Its shock absorber mechanically actuates the **start switch (SS)** — the cycle trigger. | **SS** start switch (on *our* lanes this is replaced by the **DIELL** optical ball detector — see §3.6 and Section 2 *(System Overview & Track A/B Architecture)*). |
| 2 | **Ball Lift** | Lifts the bowling ball out of the pit and returns it up the ball track to the bowler. Driven by the back-end (BE) motor. | (no dedicated control input; runs with BE) |
| 3 | **Sweep** | The rake bar. Sweeps across the pin deck to clear dead wood into the pit, then guards the deck while the table spots. Driven by the **sweep motor (S)**, which runs **intermittently** per cycle. | Sweep cams **SA, SB, SC** ride the sweep-motor shaft (§3.4). |
| 4 | **Carpet** | The pit carpet / conveyor that moves fallen pins toward the elevator. Part of the continuously-running back-end. | (no dedicated control input) |
| 5 | **Pin Elevator** | Lifts fallen pins up out of the pit to the distributor. Continuously-running back-end. | (no dedicated control input) |
| 6 | **Distributor** | Orients and routes elevated pins into the ten bins above the deck. Continuously-running back-end. | (no dedicated control input) |
| 7 | **Bin** | Ten-position pin magazine above the deck that holds pins ready to drop into the table cups. The **#9 bin** carries the **bin switch (BS)** that signals "10th pin delivered." | **BS** bin switch (#9 bin). |
| 8 | **Table** | The spotting table: 10 spotting cups + 10 respot cells, each with a **gripper switch (GS)**. Descends to set/respot pins; reads which pins are standing. Driven by the **table motor (T)**, which runs **intermittently** per cycle. | **GS1–GS10** gripper switches (standing-pin read); table cams **TA1, TA2, TB** (§3.4); **spot/respot solenoids** (via the **SP** relay). |
| 9 | **(Chassis / control assembly)** | **(VERIFY: the ninth assembly.** `phase8_8270_SYSTEM_REFERENCE.md` §1 states "Nine assemblies" but enumerates only the eight mechanical assemblies above. The ninth is most likely the **control chassis / DC control box** itself — the assembly we are replacing — but the exact AMF name for the ninth item is not pinned down in the mined notes. Confirm against the Service & Parts manual assembly index before printing this as final.) | The chassis terminates **C1** and **C2A** (see §3.7) and houses the relays/logic. |

#### Motor running pattern (memorize this)

This is the single most important behavioral fact for the controller:

| Motor | Relay | Runs | Notes |
|---|---|---|---|
| **Back-End (BE)** | `BE` | **Continuously** while the machine is in "Bowl" | Drives Ball Lift + Carpet + Pin Elevator + Distributor as one mechanical group. The controller energizes it once and leaves it on; it is **not** cam-timed and **not** subject to the motion timeout. |
| **Sweep (S)** | `S` | **Intermittently**, once per cycle | Started by the controller, stopped at cam angles (SB 66°, SA 270°, SA 360°). ~**12.1 RPM**, capacitor-induction, **115 VAC** (VERIFY: 12.1 RPM and 115 VAC are the documented machine figures; confirm against the motor nameplate on our chassis). |
| **Table (T)** | `T` | **Intermittently**, once per cycle | Started by the controller, stopped at cam angles (TA1 355°/zero). Same ~12.1 RPM / cap-induction / 115 VAC class as the sweep. |

> **Motor current never touches our PCB.** The Pi controller board commands the **existing S/T machine contactors** through isolated dry relay contacts; the contactors continue to switch the 115 VAC motor current and provide their original **regenerative braking** (the de-energized **N.C.** contacts switch capacitors across the main winding). The board must *command* those contactor control circuits, never *become* the contactor or the brake path. See Section 9 *(Machine Outputs — the Output Contract / Relay Stage)* and §3.3 of `phase8b_pcb_revB_spec.md`.

---

### 3.2 How a Cycle Works (the mental model)

The 82-70 has **no single "advance one step" pulse**. (An earlier draft FSM, `cycle_control.py`, wrongly modeled it as one-pulse-per-cycle and is **void**.) Instead:

1. A ball is thrown. The **cushion's SS switch** (our **DIELL** beam) tells the controller "ball delivered — start a cycle."
2. The controller **energizes the sweep motor** and lets it run. The sweep motor turns a shaft carrying the **sweep cams (SA/SB/SC)**.
3. As the shaft rotates, each cam **trips a microswitch at a specific angle**. The controller watches those switch edges and **de-energizes the motor when the cam reports the target degree.** That is how the sweep "stops at 66°," "stops at 270°," etc. — there is no mechanical detent; **the stop is a control decision** made by reading a cam and dropping a relay.
4. The same is true for the **table motor** and its **table cams (TA1/TA2/TB)**.
5. In between, the controller reads the **grippers** (which pins are standing), runs a **3-second settle delay**, fires the **spot solenoid** when a fresh rack is needed, and updates the **mask lamps**.

So the controller is an **event-driven state machine**: cam-switch transitions (plus SS/ball, the grippers, the bin switch, the foul detector, and the 3-second timer) drive state changes; each state sets motor / solenoid / lamp outputs. This is exactly the structure of `lane_node/cycle_control_8270.py` (the `CycleController` FSM) — its handlers (`cam_SB_guard`, `cam_TA2_runthrough`, `cam_SA_runthrough`, `cam_TA1_zero`, `bin_full`, …) map one-to-one onto the steps below. The cam *edges* are detected by the RP2040 firmware and forwarded to the Pi (see Section 15 *(RP2040 Firmware)* and §3.6 here).

> **Critical safety nuance.** Because the cam-position stops are **controller logic** (read cam → drop relay), they are **not** a hardwired motor latch. The Pi *times* them. The hardware backstops that exist independently of the Pi are: the **TB/SC table-sweep collision interlock**, the **regenerative relay braking**, the **NE555 watchdog**, the **RP2040 health line**, and the **Stop/CIS/master-breaker** chain. See §3.8 and Section 10.

---

### 3.3 Sequence of Operation — FIRST BALL

This is the canonical cycle: a ball is thrown on the first ball of a frame, knocks down some pins, and leaves others standing. The table **respots the held standing pins** (it does **not** spot a fresh rack — that distinction is the heart of the logic).

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | **SS closes** (ball delivered; our DIELL beam breaks) while machine is **READY** and the **interlock is OK** | Energize **sweep motor (S)**; cycle = `FIRST_BALL`; state → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep reaches **66°** | De-energize sweep (it now **guards** the deck); start the **3-second time delay**; state → `GUARD_DELAY` | **SB** @ 66° |
| 3 | 3 s elapsed **AND GP (gripper-protect) closed** | Energize **table motor (T)** — table descends; state → `TABLE_DETECT` | 3 s timer, gated by **GP** |
| 4 | Table reaches **260°** | **Latch the standing-pin mask** by reading **GS1–GS10**; **latch the pin lamps** (12 VDC; KX relay historically sent this pin data to the scorer); signal "machine ready" to the scoring computer; **re-energize the sweep** for its run-through; state → `RUNTHROUGH`. *Decision point:* if the mask is **non-zero** (pins standing) the cycle stays `FIRST_BALL` (respot path). | **TA2** @ 260° |
| 5 | Sweep reaches **270°** | De-energize sweep (run-through complete); state → `TABLE_FINISH`. First-ball-with-pins needs **no SP** — the table is respotting the held pins, not spotting a fresh rack. | **SA** @ 270° |
| 6 | Table passes **185°** | **Reset the time-delay memory** (no motor change) | **TA1** @ 185° |
| 7 | Table reaches **355° / zero** | De-energize table; **flip ball memory: 1st-ball light OFF, 2nd-ball light ON**; clear strike/foul lamps; state → `READY` (now awaiting the **second** ball) | **TA1** @ 355°/zero |
| 8 | Sweep returns toward **360°** | Sweep stops at zero (parked) | **SA** @ 360° |

FSM anchors (from `cycle_control_8270.py`): handlers `on_ball` → `cam_SB_guard` → `poll()` (3 s + GP) → `cam_TA2_runthrough` → `cam_SA_runthrough` → `cam_TA1_zero`; `_needs_fresh_rack()` returns **False** for `FIRST_BALL`, so `bin_full()` (BS) is a no-op on this cycle.

---

### 3.4 Sequence of Operation — SECOND BALL

On the second ball, the **ball memory is inverted** (the FIRST-BALL cycle flipped it). After the second ball, the deck is cleared and a **fresh full rack is spotted** via the **spot solenoid (SP)**, gated by the **bin switch (BS)**.

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | **SS closes** while READY (ball memory = 2nd) | Energize sweep; cycle = `SECOND_BALL`; → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep reaches **66°** | De-energize sweep (guard); start **3 s** delay; → `GUARD_DELAY` | **SB** @ 66° |
| 3 | 3 s **AND GP closed** | Table descends; → `TABLE_DETECT` | timer + **GP** |
| 4 | Table reaches **260°** | Latch grippers + pin lamps; re-energize sweep for run-through; → `RUNTHROUGH` | **TA2** @ 260° |
| 5 | Sweep reaches **270°** | De-energize sweep; → `TABLE_FINISH` (this cycle **awaits BS** to spot a fresh rack) | **SA** @ 270° |
| 6 | **10th pin delivered to bin → BS closes** | Energize the **SP spot relay**; the table runs a **spotting revolution** to set a new full rack; state → `SPOTTING` (gated by interlock OK) | **BS** (#9 bin) |
| 7 | Table reaches **355° / zero** | De-energize **SP**; de-energize table; **reset ball memory → 1st ball** (1st-ball light ON); → `READY` | **TA1** @ 355°/zero |
| 8 | Sweep returns to **360°** | Sweep parks at zero | **SA** @ 360° |

FSM anchors: `_needs_fresh_rack()` returns **True** for `SECOND_BALL`, so `bin_full()` (BS) fires `set_spot(True)` and enters `SPOTTING`; `cam_TA1_zero()` then releases SP (`set_spot(False)`) and finishes. **(VERIFY: SP de-energize timing and SP pulse-vs-continuous behavior** — `cycle_control_8270.py` marks the exact SP-release-vs-cam relationship `# CONFIRM`; confirm on the bench against the spotting-revolution geometry. SP routing is **(VERIFY: SP connector cavity** — OEM/FSM comments cite `C1-35U/36Y`, but our SS + Omega-Tek bench measured **SP at C2A (0 Ω)**; harness-resolved per chassis.)

---

### 3.5 Sequence of Operation — STRIKE and FOUL

#### STRIKE

A strike is a **first-ball cycle in which no pins remain** (the gripper mask reads zero at 260°). The machine then behaves like a fresh-rack cycle (spot a new rack) rather than a respot.

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | SS closes while READY (1st ball) | Energize sweep; cycle = `FIRST_BALL`; → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep **66°** | De-energize sweep (guard); 3 s delay | **SB** @ 66° |
| 3 | 3 s + **GP closed** | Table descends; → `TABLE_DETECT` | timer + **GP** |
| 4 | Table **260°** | Read grippers → **mask == 0** → **set STRIKE memory**: cycle becomes `STRIKE`, **strike lamp ON**, **1st-ball lamp OFF**. Strike holds the table for fresh-rack spotting. Re-energize sweep for run-through; → `RUNTHROUGH` | **TA2** @ 260° |
| 5 | Sweep **270°** | De-energize sweep; → `TABLE_FINISH` (awaits BS, like 2nd ball) | **SA** @ 270° |
| 6 | **BS closes** | Energize **SP**; table spotting revolution (fresh rack); → `SPOTTING` | **BS** |
| 7 | Table **355°/zero** | De-energize SP + table; **strike memory resets** (lamps cleared) once sweep + table reach zero; **ball memory → 1st ball**; → `READY` | **TA1** @ 355°/zero |

FSM anchor: in `cam_TA2_runthrough()`, `if self.cycle is Cycle.FIRST_BALL and self.pins == 0:` promotes the cycle to `STRIKE` and lights the strike lamp; `_needs_fresh_rack()` is **True** for `STRIKE`.

#### FOUL

The **foul detector (Radaray)** fires when the bowler crosses the foul line. The foul is flagged on the *first* ball, the foul lamp lights, and a **foul memory** holds the table while the sweep clears and a rack is spotted; the cycle then advances to the second ball.

| Step | Trigger / condition | Controller action | Source |
|---|---|---|---|
| 1 | **Foul detector (Radaray) fires** during a 1st-ball cycle | **Foul lamp ON**; set foul logic; cycle = `FOUL` (only if currently on the first ball) | Radaray **Foul** input |
| 2 | Sweep runs to **66°** | Sweep guard; **foul memory holds the table** | **SB** @ 66° |
| 3 | Sweep run-through to **270°** | (clear deck) | **SA** @ 270° |
| 4 | **BS closes** | Table spotting revolution | **BS** |
| 5 | Cycle completes | **Ball memory flips → 2nd ball** | **TA1** @ 355°/zero |

FSM anchors: `on_foul()` sets `Cycle.FOUL` and `set_light('foul', True)`. **(VERIFY: foul respot semantics.** `cycle_control_8270.py::_needs_fresh_rack()` *currently treats FOUL as a fresh-rack/SP cycle as a placeholder* and is explicitly marked `# CONFIRM` — real foul behavior on the 82-70 varies (some configurations respot held pins after a first-ball foul rather than spotting a full rack). **Confirm the exact foul respot vs. fresh-rack behavior on the bench/at-machine before live.** The `SYSTEM_REFERENCE` §2 FOUL line says the foul cycle "flips → 2nd ball" but does not settle the SP question.)

---

### 3.6 Cam Timing Table (authoritative)

These six cams are the **position feedback** for the two intermittent motors. Each is a microswitch riding a lobe on the motor shaft; the controller reads the switch edge and acts. **These angles are the FSM's triggers** and are reproduced verbatim from `phase8_8270_SYSTEM_REFERENCE.md` §3 and `cycle_control_8270.py`'s `CAM TIMING` constants.

| Cam | On shaft | Trips at | Role in the sequence |
|---|---|---|---|
| **SA** | Sweep | **270°** + **360° / zero** | Stop the sweep **run-through @270°**; stop the sweep **@zero (360°)** when parking. |
| **SB** | Sweep | **66°** + **186°** | **Guard stop @66°** (sweep halts, deck guarded, 3 s delay begins); **initiate table spotting @186°**. |
| **SC** | Sweep | **86° – 243°** (window) | **Sweep-under-table interlock** window — half of the TB/SC collision interlock (§3.8). Not a "stop" cam; a safety window. |
| **TA1** | Table | **355°** (+ **185°**) | **Table zero stop @355°**; **@185° reset the time-delay** memory. |
| **TA2** | Table | **260°** | **Initiate the sweep run-through**; **latch the pin lamps**; make the **ball/strike decision** (read grippers; zero → strike). |
| **TB** | Table | **105° – 255°** (window) | **Table-sweep interference interlock** window — the other half of the TB/SC collision interlock (§3.8). A safety window, not a stop. |

Code constants (`cycle_control_8270.py`), for cross-checking firmware/FSM against this table:

```text
SB_GUARD      = 66     SB_SPOT       = 186
SA_RUNTHROUGH = 270    SA_ZERO       = 360
SC_LO, SC_HI  = 86, 243
TA1_DELAYRESET= 185    TA1_ZERO      = 355
TA2_RUNTHROUGH= 260
TB_LO, TB_HI  = 105, 255
```

> **Timing is tight — budget input latency.** The OEM audit (`phase8_oem_doc_audit_2026-06-02.md` §3) flags that SA/TA-2 overlap and the run-through stops happen fast enough that **slow RC or firmware debounce on the cam channels could hide an edge or an overlap.** That is why the cams are **fast inputs on the RP2040** (edge-capable), not slow MCP23017 inputs. The documented debounce budget is **`DEBOUNCE_CAM_US = 2000 µs` (2 ms)** — ample for mechanical microswitches on a ~12 RPM shaft without masking the trip edges. See Section 15 and `firmware/rp2040/config.h`.
>
> **Edge polarity is a deferred field item.** The RP2040 forwards each cam edge tagged `f` (asserted/fall) or `r` (released/rise); **which physical edge is the angular "trip" is bench-confirmed per cam** at cutover (firmware README + `phase8_trackB_controller_cutover_runbook.md`). The firmware deliberately does **not** bake in unconfirmed cam→angle polarity (the cam-stop *overrun* enforcement is the v1.1 hook, intentionally deferred). **(VERIFY: per-cam trip-edge polarity for all six cams on our chassis.)**

---

### 3.7 The 3-Second Time Delay (pin settle), gated by GP

After the sweep reaches its 66° guard (**SB**), the controller **waits 3 seconds before lowering the table.** This is the **pin-settle delay**: it lets pins that are still rocking or sliding on the deck come to rest, so the gripper read at 260° (**TA2**) reflects the true standing-pin pattern and the table doesn't try to grip a moving pin.

Two conditions must both hold for the table to descend:

1. **The 3-second timer has elapsed** (`TIME_DELAY_S = 3.0` in `cycle_control_8270.py`).
2. **GP (gripper-protect) is closed.** GP is a machine permissive that confirms the grippers are in the safe state to descend. If GP is open, the table does **not** drop even after 3 s.

This is implemented in the FSM's `poll()` loop while in state `GUARD_DELAY`:

```python
if self.io.gp_closed() and (now - self._t_state) >= TIME_DELAY_S:
    self._safe_table(True)         # table descends
    self._enter(State.TABLE_DETECT)
```

The delay memory is **reset at table 185°** (**TA1**) on the way back to zero (`cam_TA1_delayreset()` — a bookkeeping reset with no motor change), so each cycle starts the 3-second window clean.

> GP is wired as a **slow input** on the MCP23017 IN-A bank (it gates a 3-second window, so it does not need RP2040 edge speed). See §3.7's I/O map and Section 5 §5.2.

---

### 3.8 Safety Behaviors the Controller Must Preserve

These are machine-level safety behaviors documented in `SYSTEM_REFERENCE` §5 and OEM-confirmed in the audit. The Pi controller **reproduces or preserves every one of them**; several are deliberately kept in **hardware** so they survive a dead or misbehaving Pi. Full electrical implementation is in Section 10 *(PCB Rev-B Safety Rail)*; the *behavior* is described here because it is part of the machine's sequence of operation.

| Behavior | What it does | Where it lives |
|---|---|---|
| **Stop switch + C.I.S.** (Chassis Interlock Switch) | In **parallel**; either one cuts the **rear-panel master circuit breaker** → all control dead. | Hardware (external chain), sensed/looped through `J_SAFETY`. |
| **TB/SC table-sweep collision interlock** | **TB (105°–255°) and SC (86°–243°) in PARALLEL** in the 24 V relay-control path. If the table and sweep are simultaneously in their interference windows (a collision course), **both motor relays drop.** The MP's manual Sweep/Table override buttons bypass *all* logic **except BE and this interlock** — making it the irreducible hardware safety. **Keep it in hardware.** | Hardware rail (a first-class, non-software rail condition). The FSM's `io.interlock_ok()` is a **secondary software echo** only — it never *enables* motion the hardware would block. |
| **Regenerative motor braking** | De-energized **N.C.** relay contacts switch capacitors across the motor main winding to brake the sweep/table quickly at each stop. | Hardware (the existing S/T contactor contact sets + caps). The PCB must not replace this. |
| **MP "Power-Down" rule** | After **any 115 VAC loss** while in "Bowl," the machine performs **no motion on power restore** until the operator deliberately commands **"First Ball Zero"** (a Manual Intervention). | Reproduced by the Pi: the FSM comes up in state **`MANUAL_INTERVENTION`** and drives nothing until `first_ball_zero()` is called (`power_restore()` → `MANUAL_INTERVENTION`). This is the controller-level sibling of the NE555 watchdog: **fail-safe-off on restore, require operator zero.** |
| **Welded-contact limitation** | The safety rail can only **de-energize** relay coils; it **cannot open a contact that has welded closed.** The master breaker / Stop / CIS chain is therefore the **final physical stop.** | Hardware (breaker is final). Drives relay rating + suppression requirements in Section 10 §4.5. |

> **The interlock is electrical truth, not a software hint.** The OEM audit (`phase8_oem_doc_audit_2026-06-02.md` §2 and the Rev-B contract §4.4) is explicit: TB/SC "must remain a hardware rail condition… firmware observation is not enough… The schematic must provide a non-software path that drops output-relay permission on interlock fault." Our PCB honors this — `J_SAFETY` carries the external NC interlock loop into the relay-enable rail in series, ahead of any Pi GPIO. **(VERIFY: the exact electrical form of TB/SC on our SS + Omega-Tek chassis** — cam contacts vs. the existing 24 V control path vs. a derived low-voltage loop — is an open at-machine item per the audit's "Open Items" and §4.4; confirm before wiring `J_SAFETY`.)

---

### 3.9 Machine I/O the Controller Touches (function-level summary)

This is the *functional* I/O list the sequence above depends on. **Exact connector cavities (C1/C2A pins) are deliberately not bound in PCB copper** — they differ between the OEM factory chassis, our SS + Omega-Tek retrofit, and the Active-98 chassis, so an adapter harness resolves them per chassis at cutover (see the OEM-vs-bench reconciliation in `phase8_oem_doc_audit_2026-06-02.md` and Section 14 *(Connector & Harness Map)*). The table below gives the function, the controller bus it lands on, and the named board channel. Pin/part anchors come from `scripts/generate_kicad_netlist_revB.py`, `firmware/rp2040/config.h`, and `lane_node/controller_io.py`.

#### Inputs the controller reads

| Signal | Meaning in the sequence | Bus | Channel anchor |
|---|---|---|---|
| **SS** (cushion start) / **DIELL-L**, **DIELL-R** | Ball delivered = cycle trigger. On our lanes the cushion SS is replaced by the **DIELL** optical ball beams (two beams, coalesced into one "ball" event). | **RP2040 fast** | `DIELL_L = GP12`, `DIELL_R = GP13` (Pico pins 16, 17) |
| **SA, SB, SC** (sweep cams) | Sweep position (§3.6). | **RP2040 fast** | `SA = GP6`, `SB = GP7`, `SC = GP8` |
| **TA1, TA2, TB** (table cams) | Table position + the strike/run-through decision + interlock window (§3.6). | **RP2040 fast** | `TA1 = GP9`, `TA2 = GP10`, `TB = GP11` |
| **GS1–GS10** (gripper switches) | The 10-bit **standing-pin mask**, latched at TA2/260°. | **MCP23017 IN-A** | `IN_A_MAP["GS1".."GS10"]` = GPA0..GPA7, GPB0, GPB1 (MCP pins 21–28, 1, 2) |
| **GP** (gripper-protect) | Gates the 3-second delay → table descent (§3.7). | **MCP23017 IN-A** | `GP` = MCP IN-A pin 3 (GPA2) |
| **BS** (bin switch, #9 bin) | "10th pin delivered" → fires SP on fresh-rack cycles (§3.4/3.5). | **MCP23017 IN-A** | `BS` = MCP IN-A pin 5 (GPA4) |
| **OS** (off-spot) | Off-spot detection. | **MCP23017 IN-A** | `OS` = MCP IN-A pin 4 (GPA3) |
| **PBZ** (first-ball / zero / manual-intervention pushbutton) | Operator "First Ball Zero" → clears `MANUAL_INTERVENTION`; toggles 1st/2nd ball when already running. | **MCP23017 IN-A** | `PBZ` = MCP IN-A pin 6 (GPA5) |
| **PBC** (cycle pushbutton) | Manual cycle. | **MCP23017 IN-A** | `PBC` = MCP IN-A pin 7 (GPA6) |
| **Foul** (Radaray) | Foul detected (§3.5). | **MCP23017 IN-A** | `Foul` = MCP IN-A pin 8 (GPA7) |
| **10th-frame; manual T / S / SWS / SWSR; spares** | 10th-frame indication and the manual table/sweep/sweep-switch/sweep-reverse inputs, plus spares. | **MCP23017 IN-B** | `TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1–3` (MCP IN-B pins 21–28) — allocated, not yet read by the current FSM |

> **Polarity (all inputs).** Every input is **opto-isolated and active-LOW at the controller**: a closed machine contact pulls the GPIO/MCP pin **LOW**; idle is **HIGH** (on-board 10k pull-up). This is `INPUT_ACTIVE_LOW = True` in `controller_io.py` and the active-low handling in `firmware/rp2040/main.c` (`gpio_get(...) == 0` = asserted). The front end is a **PC817B** optocoupler per channel with a **2.2k** field series resistor and a **10k** logic pull-up. The standing-pin convention: a **standing** pin sets its mask bit (`read_grippers()` returns bit *n−1* set for GS*n* standing); a mask of **0 = no pins = strike**.

#### Outputs the controller drives

| Signal | Meaning in the sequence | Coil / driver | Channel anchor |
|---|---|---|---|
| **S** (sweep relay) | Run/stop the **sweep motor** (intermittent). | Relay coil | `OUT_A_MAP["S"]` = MCP OUT-A GPA0 (pin 21) → relay **K1** |
| **T** (table relay) | Run/stop the **table motor** (intermittent). | Relay coil | `OUT_A_MAP["T"]` = GPA1 (pin 22) → **K2** |
| **SP** (spot solenoid) | Fire the **fresh-rack spotting** revolution (after BS, on 2nd/strike/foul). | Relay coil | `OUT_A_MAP["SP"]` = GPA2 (pin 23) → **K3** |
| **BE** (back-end) | Energize the **continuous** back-end motor group (Ball Lift + Carpet + Elevator + Distributor). | Relay coil | `OUT_A_MAP["BE"]` = GPA3 (pin 24) → **K4** *(future; not driven by the current FSM)* |
| **M** (master) | Master / control command. | Relay coil | `OUT_A_MAP["M"]` = GPA4 (pin 25) → **K5** *(future)* |
| **M2** (sweep reverse) | Reverse the sweep (optional APS strike/7-10 enhancement). | Relay coil | `OUT_A_MAP["M2"]` = GPA5 (pin 26) → **K6** |
| **M1** (ball return) | Ball-return command. | Relay coil | `OUT_A_MAP["M1"]` = GPA6 (pin 27) → **K7 DNP** *(not bench-confirmed on our chassis + FSM doesn't drive it; footprint present but **DNP**)* |
| **first_ball / second_ball / strike / foul** | The mask **status lamps** (which ball; strike; foul). | Logic LED driver | `OUT_A_MAP` GPA7, GPB0, GPB1, GPB2 (gen `L_FIRST/L_SECOND/L_STRIKE/L_FOUL`, pins 28, 1, 2, 3) → 2N7002 LED drivers |
| **Pin lamps 1–10** | The 10-pin **pindicator** mask, latched at 260°. | (camera-supplied in Rev-B) | Optional OUT-B bank, **omitted in baseline** — camera scoring (Track A) supplies pin state; `enable_pin_lamps=False`. |
| **KX relay** | Historically gated pin data to the old scorer. | — | **Omitted** — replaced by camera scoring. |

> **Output ordering caution.** In `OUT_A_MAP`, **M2 precedes M1** (GPA5 then GPA6) — this matches the netlist generator's `OUTPUT_PINS` order and was a deliberate fix; an earlier draft had M1/M2 (and BS/OS, and strike/foul) swapped. The `controller_io.py` `__main__` self-test re-derives `OUT_A_MAP`/`IN_A_MAP` from `generate_kicad_netlist_revB.py` and **fails on drift**, so software names can never silently diverge from the routed board.

#### Lamp / status-LED voltage — a documented conflict

The **status lamps** (1st-ball/2nd-ball/strike/foul) and the **pin lamps** are described in `SYSTEM_REFERENCE` §4 as **12 VDC** (pin lamps 12 VDC via D1–D10; status lamps 12 VDC at mask positions PM-E24/E25/E26/E27; neon mask elements ~125 VAC/−160 VDC). However, the **Rev-B PCB decision** (`phase8b_pcb_revB_spec.md` §3.3) is to **abandon the machine mask-lamp supply entirely** and instead install **our own LEDs in the mask housings**, driven from **VCC_5V** logic power through **2N7002** low-side FETs with **330R** current-limit resistors (`Rled_*`). That spec note also cites the machine's measured mask-lamp supply as **15 VDC**, which **disagrees with the 12 VDC** in `SYSTEM_REFERENCE` §4.

**(VERIFY: machine mask-lamp supply voltage — 12 VDC (`SYSTEM_REFERENCE` §4) vs. 15 VDC (`phase8b_pcb_revB_spec.md` §3.3). The discrepancy is academic for Rev-B status lamps (the board drives its own 5 V LEDs and does not use the machine supply at all), but the original-machine value should be confirmed at-machine and reconciled before this manual is final, since it also bears on the 12 VDC pin-lamp / KX path if camera scoring is ever abandoned.)** The **330R** status-LED current-limit value is itself flagged "TBD in the scaffold" in the PCB spec (§11 item 5) — **(VERIFY: final status-LED current-limit resistor value for bowling-center brightness.)**

---

### 3.10 What This Means for the Build (cross-references)

- The **cam angles in §3.6** are the contract the **RP2040 firmware** detects edges for and the **`CycleController` FSM** acts on. See Section 15 *(RP2040 Firmware)* and `cycle_control_8270.py`.
- The **motor running pattern in §3.1** (BE continuous; S/T intermittent; motor current on the machine contactors) is the rule the **PCB output stage** must not violate. See Section 5 *(PCB Rev-B)* §3.
- The **safety behaviors in §3.8** (TB/SC interlock, Stop/CIS/breaker, power-down rule, regenerative braking, welded-contact limit) are the **hardware safety rail** the board enforces independently of the Pi. See Section 10 §4.
- The **function-named I/O in §3.9** is mapped to physical C1/C2A cavities **only by the adapter harness at cutover** — never in copper. See Section 14 *(Connector & Harness Map)* and the OEM-vs-bench cavity reconciliation.

> **Open at-machine confirmations carried into the cutover runbook** (from `phase8_oem_doc_audit_2026-06-02.md` "Open Items After OEM Read" and the `# CONFIRM` markers in `cycle_control_8270.py`): coil/control voltage + current for S/T/SP/BE/M/M1/M2; the electrical form of TB/SC and how to fold it into the rail; presence/path of the M2 sweep-reverse Expander interlock and shorting-plug requirement; gripper/TAC/C2A cavity mapping; SP de-energize timing; foul respot semantics; and per-cam trip-edge polarity. None of these change the *sequence* above — they pin down the *wiring* and a few timing details before a live lane.


## 4. Machine I/O Inventory (Cams, Grippers, DIELL, Foul, Mask, Buttons)

This section is the complete catalog of every electrical signal that crosses between the AMF 82-70 pinsetter and the lane-node controller: what each signal is, what physically generates it, its electrical form (dry contact vs. voltage-sense, polarity, rest/active levels), where it lands on the board, and how the firmware/FSM consumes it. If you are tracing a wire, sizing an opto front-end, or debugging "why won't this lane cycle," start here.

**Scope reminder (see §2 System Architecture):** the controller does *not* replace the machine's mechanism, motors, cams, grippers, contactors, or mask housings. It replaces only the *control brain* (the old solid-state / Omega-Tek board), reading the same machine inputs and driving the same machine control circuits the OEM board did. Everything in this section is a signal on the machine side of that boundary.

> **Chassis caveat — READ THIS.** Lanes 21/22 (the pilot pair) are an **AMF SS (solid-state) chassis retrofitted with an Omega-Tek Omniboard**; lanes 11/12 are an **AMF MP chassis (Active Technology Ultra 98)**. The *machine side* (cams, motors, grippers, DIELL, mask) is common across the fleet, which is why one controller board design serves all lanes. But the **C1/C2A connector cavity numbers and some harness landings differ per chassis** — the Omega-Tek retrofit re-routed several landings vs. the OEM factory wire tables (e.g. sweep-reverse M2 lands on C2A on our 21/22 bench, but C1 in the OEM 9800-MP tables). For that reason the controller board uses **function-named connectors** and a **per-chassis adapter harness** that is resolved at cutover, not baked into copper. Cavity codes quoted below are 225-DPI schematic best-effort guesses or single-pair bench measurements; treat them as "look here first," not gospel. The authoritative per-lane cavity map is produced at cutover (see §0/PART C of the at-machine field sheet).

---

### 4.1 Signal-class overview

The machine I/O splits into two latency classes and three electrical domains. This split drives the board architecture (see §5 Board Architecture, §10 Safety Rail).

| Class | Signals | Why | Routed to |
|---|---|---|---|
| **FAST** (latency-critical) | DIELL ball detect (×2 beams), cams SA/SB/SC/TA1/TA2/TB | Cam-position motor stops must act in hardware, independent of Pi scheduling | RP2040 co-processor (opto-isolated), GP6–GP13 |
| **SLOW** (poll/interrupt) | Grippers GS1–GS10, GP, OS, BS, PBZ, PBC, Foul, 10th-frame, manual T/S/SWS/SWSR | Read on a state change or once per cycle; milliseconds of jitter are harmless | MCP23017 expanders (opto-isolated), I²C |
| **OUTPUTS** (relay-driven) | S, T, SP, BE, M, M2, M1 motion relays + 4 status lamps | Board closes/opens existing machine control circuits via isolated dry contacts | MCP23017 OUT-A → relay coils (S/T/SP/BE/M/M2/M1) or FET LED drivers (lamps) |

Electrical domains (kept galvanically separate on the board — see §5):
- **Logic** — Pi, RP2040, MCP23017s, 3.3 V / 5 V. Never shares ground with the machine.
- **Machine Sense (FIELD)** — the field side of every input optocoupler. Wetting is isolated from logic ground (or chassis-referenced for grippers — see §4.3).
- **Machine Output** — isolated relay *contacts* that close existing machine control circuits. The board does **not** source machine coil voltage.

---

### 4.2 The 6 cams (machine timing → FSM triggers)

The cams are mechanical microswitches actuated by lobes on the rotating sweep and table shafts. They are the machine's sense of "where am I in the cycle" and they are the primary FSM triggers (see §3 Sequence of Operation in the system overview, and `lane_node/cycle_control_8270.py`). The machine turns at ~12.1 RPM, so a full revolution is ~5 s and the cam edges are widely spaced in time — a 2 ms debounce is ample (firmware `DEBOUNCE_CAM_US = 2000`).

There are **two sweep cams that each trip at two angles** (SA, SB), one sweep interlock window cam (SC), two table cams (TA1, TA2), and one table interlock window cam (TB). The degree values below are the authoritative FSM trigger angles from `cycle_control_8270.py` constants, cross-checked against the OEM Service & Parts manual cam-timing table (system reference §3).

| Cam | Shaft | Trips at | FSM role | Firmware constant(s) |
|---|---|---|---|---|
| **SA** | Sweep | **270°** and **360°/zero** | Stop sweep run-through at 270°; stop sweep at zero (360°) | `SA_RUNTHRU` (270), `SA_ZERO` (360) |
| **SB** | Sweep | **66°** and **186°** | Guard stop at 66° (sweep stops, starts the 3 s pin-settle); initiate table spotting at 186° | `SB_GUARD` (66) |
| **SC** | Sweep | **86°–243°** (window) | Sweep-under-table window → feeds the **TB/SC hardware interlock** (collision avoidance); RP2040 reads it as a *software echo* only | `SC_LO`, `SC_HI` (86, 243) |
| **TA1** | Table | **355°** and **185°** | Table zero stop at 355°; at 185° reset the 3 s time-delay and flip ball memory | `TA1_ZERO` (355) |
| **TA2** | Table | **260°** | Initiate sweep run-through; **latch the gripper read** (pin/strike decision); signal "machine ready" | `TA2_RUNTHRU` (260) |
| **TB** | Table | **105°–255°** (window) | Table-sweep interference window → feeds the **TB/SC hardware interlock**; RP2040 reads it as a software echo only | (window, interlock) |

**Electrical form (bench/field-confirmed):** the cam inputs are **dry switch closures, normally-closed (NC)**. This is confirmed in the at-machine field sheet (item A4: "cam input form = dry contact (normally-closed)"). On the board, each cam input front-end defaults to **dry-contact wetting** (the isolated wetting supply drives the opto LED through the closed cam to FIELD_GND/common). Per-channel population is jumper-selectable to a 24 VAC voltage-sense front-end if a particular chassis presents the cam as a powered line instead, but the 21/22 default is dry-contact.

> ⚠️ **(VERIFY: per-cam edge polarity — which physical edge (open→closed vs closed→open) is the angular "trip" for each of SA/SB/SC/TA1/TA2/TB).** The firmware (`main.c`, `scan_inputs()`) forwards *both* edges to the Pi tagged `f` (asserted/fall) or `r` (released/rise); the Pi maps cam+edge → FSM method. The exact edge-to-angle binding is a **deferred cutover field task** (rotate the mechanism by hand, watch which C2A cavity changes at which angle — at-machine field sheet PART C2). Do NOT bake unconfirmed cam polarity into the firmware; the v1.1 cam-stop-overrun enforcement hook in `main.c` is deliberately left disabled until this is measured.

**Where they land:** cam wires enter via the machine's **A&MC ("Approach & Machine Control") plug** and run to **C2A** cavities. On the board they connect to the **J_FAST_IN** connector → PC817 optocouplers → RP2040 GPIOs:

| Cam | RP2040 GPIO | Pico pin | Net (board) |
|---|---|---|---|
| SA | GP6 | 9 | FAST_SA |
| SB | GP7 | 10 | FAST_SB |
| SC | GP8 | 11 | FAST_SC |
| TA1 | GP9 | 12 | FAST_TA1 |
| TA2 | GP10 | 14 | FAST_TA2 |
| TB | GP11 | 15 | FAST_TB |

(Source: `firmware/rp2040/config.h` `PIN_SA`..`PIN_TB`, and `scripts/generate_kicad_netlist_revB.py` `FAST_INPUTS`. **These GP6–GP13 assignments are the as-built board; the GPIO column in `docs/phase8_channel_allocation.md` §2 is STALE — it shows GP0–GP7 and must be ignored.**)

> **(VERIFY: which A&MC pin = which specific cam.)** The schematic associates the cams to A&MC pins 11A/12D/13H/14L/21B/22E/31C, but the cam↔A&MC binding cannot be read cold — it is a cutover at-machine task (rotate the mechanism, watch the cavity). The board does not depend on it; the function-named harness resolves it.

---

### 4.3 The 10 gripper switches GS1–GS10 (pin sensing)

The 10 grippers are the spotting-table's pin-presence switches: as the table descends over the deck, each of the 10 spotting cups carries a switch that closes if a pin is standing in that position. Reading all 10 at the **TA2 (260°) latch point** gives the standing-pin pattern — this is the data the FSM uses for the strike/spare decision, and historically the data the OEM scorer used. (Note: for *score* purposes the Phase 8 system uses the optical camera, not the grippers; see §18. The grippers remain the FSM's machine-side standing-pin read.)

**Electrical form — CORRECTED at the machine (2026-06-03). This overturns the OEM "TAC strip with a shared common-return wire" model.** Field tracing on the real 21/22 machine established:

- **Each gripper switch closes its signal wire to the machine CHASSIS/FRAME.** The contact point a gripper closes onto is **not insulated from the frame** (continuity is only finicky due to dirt/oxide). So the **common return is the machine chassis itself**, not a dedicated "TAC-GND" bus wire.
- **There is no physical "TAC" terminal strip in the Omega-Tek cabinet.** "TAC" is the schematic net/harness name. The 10 gripper wires arrive in the machine/table harness bundle and terminate **directly on C2A cavities**.
- **Polarity (LOCKED for all 10): gripped (pin present) = switch CLOSED to ground.** This is the *opposite* sense from the cams (which are NC). Firmware: a gripper input **asserts (pulls to common) when a pin is standing**.

> ⚠️ **Board/harness impact (chassis-referenced return):** the gripper input front-ends use **machine CHASSIS as the return reference**, not the isolated FIELD_GND wetting node assumed for a clean "dry contact to a dedicated common." It is still a dry-contact-to-a-reference input (the opto field side wets through the gripper to chassis), and the grippers stay in the FIELD isolation domain — but the *return node identity* is the machine frame. The adapter harness ties gripper returns to chassis, not to a C2A common pin. (Source: `docs/phase8_bench_JOB3_C2A_inputs.md` "GRIPPER ARCHITECTURE — CORRECTED AT MACHINE"; at-machine field sheet "Grippers" result.)

**Active-low at the board:** the optos are wired so a closed machine contact pulls the MCP23017 pin **LOW** (`INPUT_ACTIVE_LOW = True` in `controller_io.py`). `read_grippers()` reads both ports of MCP23017 IN-A once and assembles a 10-bit standing-pin mask (bit *n*−1 = GS*n* standing).

**Where they land — board side (MCP23017 IN-A, I²C address 0x20):** these bit assignments are the source-of-truth map; `controller_io.py` `IN_A_MAP` is regression-checked against the PCB netlist generator (`scripts/generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS`) so software and copper cannot drift.

| Gripper | MCP23017 IN-A port.bit | MCP pin (netlist) | J_SLOW_IN_A pin | predicted C2A cavity¹ |
|---|---|---|---|---|
| GS1 | A0 | 21 | 1 | 41C |
| GS2 | A1 | 22 | 2 | 42H |
| GS3 | A2 | 23 | 3 | 43M |
| GS4 | A3 | 24 | 4 | 44S |
| GS5 | A4 | 25 | 5 | 45W |
| GS6 | A5 | 26 | 6 | 46Z |
| GS7 | A6 | 27 | 7 | 47 (digit unread) |
| GS8 | A7 | 28 | 8 | 48H |
| GS9 | B0 | 1 | 9 | 49 (digit unread) |
| GS10 | B1 | 2 | 10 | 410U |

(Board-side source: `controller_io.py` `IN_A_MAP` + `GRIPPER_ORDER`; `generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS` and `J_SLOW_IN_A` order. MCP23017 pin numbering: GPA0–7 = pins 21–28, GPB0–7 = pins 1–8.)

> ¹ **(VERIFY: per-gripper GS#→C2A cavity, and the 1:1 GS#-to-cavity ordering.)** The C2A cavities above are 225-DPI schematic predictions for the OEM 9800-MP DETAIL-K; our Omega-Tek retrofit lands the grippers on C2A directly but the per-pin map and even the GS#-to-physical-pin order are **NOT confirmed**. This is a deliberate cutover task: drop one pin at a time and watch which input asserts (at-machine field sheet PART C1). It does **not** gate the board — the board only needs the gripper *bank* location + the polarity (both confirmed); the GS1-vs-GS7 software labels are set at cutover.

---

### 4.4 GP, OS, BS (gate / spot / bin switches)

Three individual machine-side switches that gate or advance the cycle:

| Signal | Name | Role in the cycle | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin | C2A (tentative) |
|---|---|---|---|---|---|---|
| **GP** | Gripper-protect | **Gates the 3 s pin-settle delay** — the table only descends after the delay *and* GP is closed (`gp_closed()` in the FSM; `TIME_DELAY_S = 3.0`). Guards against dropping the table on an obstruction. | dry switch closure (assumed; see VERIFY) | B2 | 3 | (TBD at machine) |
| **OS** | Off-spot | Off-spot detect. **Not yet consumed by the FSM** — wired on the board for when full machine control grows (marked spare/⊕). | dry switch closure (assumed) | B3 | 4 | (TBD at machine) |
| **BS** | Bin / #9 bin | Closes when the 10th pin reaches the bin → triggers the **SP spot relay** for the spotting revolution (`bs_closed()` in the FSM). | dry switch closure (assumed) | B4 | 5 | predicted 112cc |

(Source: `controller_io.py` `IN_A_MAP`; `generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS` GP=pin3, OS=pin4, BS=pin5. Note `controller_io.py` comment "OS=pin4=(1,3), BS=pin5=(1,4)" — these were corrected to match the netlist after a Codex catch.)

> ⚠️ **(VERIFY: GP/OS/BS electrical form (dry vs. voltage-sense) and C2A cavities.)** The at-machine field sheet leaves GP/OS/BS rows blank (PART A4 / PART C3) — they are machine-side switches that must be actuated at the machine. The board front-ends default to dry-contact wetting like the cams (the working assumption), jumper-selectable to 24 VAC sense per channel. BS predicted at C2A-112cc, GP/OS cavities unconfirmed. None gate the board layout.

---

### 4.5 PBZ and PBC (control-panel pushbuttons)

Two operator pushbuttons on the machine's control panel:

| Signal | Name | Role | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin |
|---|---|---|---|---|---|
| **PBZ** | Zero / 1st-2nd-ball / **Manual-Intervention** | Momentary. The **"First Ball Zero"** button. Critical safety role: after any power loss the controller comes up **fail-safe-off** and refuses motion until the operator presses this to re-zero (`first_ball_zero()` in the FSM; this is the controller-level sibling of the power-down rule, §19 Safety). | momentary closure to ground | B5 | 6 |
| **PBC** | Cycle | Momentary. Manual cycle request. **Not yet consumed by the FSM** (wired on the board, spare/⊕). | momentary closure to ground | B6 | 7 |

(Source: `controller_io.py` `IN_A_MAP` PBZ=(1,5), PBC=(1,6); `generate_kicad_netlist_revB.py` PBZ=pin6, PBC=pin7.)

These are cold-mappable at the bench (you can press them) — the field-sheet/JOB3 method is: black probe on chassis/common, hold the button, sweep the C2A cavities, find the one that closes only while pressed.

> **(VERIFY: PBZ / PBC C2A cavities.)** Both are predicted to be in the "C2A-21EE area" but the exact cavities are unmeasured. Not a board gate.

---

### 4.6 Foul detector (Radaray)

The foul detector is the **Radaray** unit at the foul line (an infrared/optical foul-line sensor). On lanes 21/22 the foul *lights* are driven by the legacy **ZOT board**; the foul *signal* is what the controller reads. A foul asserts the foul lamp and, in the FSM, holds the table and runs the foul sequence (system reference §2 FOUL path: foul → sweep to 66° → foul memory holds table → run-through → spotting → ball-memory flips to 2nd ball).

| Signal | Source | Role | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin |
|---|---|---|---|---|---|
| **Foul** | Radaray foul detector | Foul-line crossing → foul lamp + FSM foul sequence (`on_foul`) | dry contact / open-collector | B7 | 8 |

(Source: `controller_io.py` `IN_A_MAP` Foul=(1,7); `generate_kicad_netlist_revB.py` FOUL=pin8; `phase8_channel_allocation.md` §2 "Foul · Radaray · opto, edge".)

> ⚠️ **(VERIFY: Foul electrical form (dry contact vs. open-collector) and C2A cavity.)** `phase8_io_board_spec.md` lists it as "dry contact / open-collector `# CONFIRM`"; the JOB3 / field-sheet Foul cavity is "(TBD)". The board treats it as an edge-triggered FIELD-domain input; front-end population is decided after the at-machine measurement.

---

### 4.7 DIELL ball detect (the cycle trigger) ⭐

This is the single most important *input* in the system: on the 82-70, the cushion's shock absorber actuates a **Start Switch (SS)** that is the cycle trigger. **On the Westside lanes the SS function is performed by DIELL photoelectric ball-detect sensors** (there is no separate cushion microswitch in the read path). When a thrown ball breaks the beam, that is the "ball delivered" event that starts the whole cycle. The DIELL also doubles as a **safety interlock** at the machine (preserve the machine's safety chain in hardware — see §19).

There are **two beams per lane** (left/right, mounted on the kickback), coalesced into one logical "ball" event in firmware.

**Sensor part / type:** DIELL **LSC/AN-2C6J** photoelectric sensor. The **`AN` suffix = NPN output** (DIELL convention; `AP` would be PNP).

**Electrical form — FULLY CHARACTERIZED (this is the one machine input whose front-end is proven end-to-end):**

| Parameter | Value | Notes |
|---|---|---|
| Output type | **NPN open-collector, active-low** | NPN means the sensor sinks to ground when active; needs a pull-up on the read side |
| Supply | **24 V** (per-lane sensor supply) | from the lane_visit characterization |
| **Rest** (beam intact, no ball) | **~16 V** | open-collector pulled up; line sits high-ish |
| **Active** (beam broken, ball passing) | **~0.7 V** | open-collector pulls the line down to near ground |

(Source: `phase8_io_board_spec.md` §1 row 1 "16 V rest → 0.7 V broken, NPN active-low (characterized)"; `phase8_bench_mule_characterization.md` "DIELL ball-detect … ~16 V rest / 0.7 V broken, NPN active-low"; `docs/lane_visit_checklist.md` Phase 4 LEFT row "AN / 24V / 0V / NPN open-collector".)

**Proven signal chain (bench + at-machine validated):** DIELL → AL-ZARD 8-channel opto board (during the Phase-8a pilot) → Pi GPIO 17 → daemon. On the **Rev-B controller board** this becomes DIELL → **J_FAST_IN** → on-board PC817B optocoupler → RP2040 GPIO (active-low at the Pico, idle HIGH via the on-board 10k pull-up to 3V3). The firmware de-bounces at `DEBOUNCE_DIELL_US = 500` (faster than the cams), and applies a `BALL_LOCKOUT_MS = 300` re-trigger lockout so one thrown ball produces exactly one `ball` event.

| Beam | RP2040 GPIO | Pico pin | Net | Firmware constant |
|---|---|---|---|---|
| DIELL-L (left) | GP12 | 16 | FAST_DIELL_L | `PIN_DIELL_L` |
| DIELL-R (right) | GP13 | 17 | FAST_DIELL_R | `PIN_DIELL_R` |

(Source: `firmware/rp2040/config.h` `PIN_DIELL_L`/`PIN_DIELL_R`; `generate_kicad_netlist_revB.py` `FAST_INPUTS` `DIELL_L`=16, `DIELL_R`=17. Firmware `main.c` coalesces both beams: a debounced beam-break emits `{"ev":"ball","src":"L|R", ...}` subject to the 300 ms lockout.)

> **Why DIELL is on the FAST path even though "ball thrown" isn't microsecond-critical:** it shares the RP2040 with the cams because the RP2040 is the board's hardware-real-time front end, and the ball event participates in the cycle-start timing. The capture-timing hook (frame after DIELL + ~2.5 s settle) is what the camera scoring uses (see §18).

---

### 4.8 Mask status lamps (replaced by our LEDs)

The 82-70 mask housing originally carried, in addition to the 10 pin-indicator lamps (omitted in our build — camera scoring replaces them, see §18 and §4.9), **four status lamps**: 1st-ball, 2nd-ball, strike, foul. The OEM drove these at **12 VDC** through the mask connector positions PM-E24/E25/E26/E27; the at-machine field sheet measured the actual mask-lamp supply at **15 VDC** (item A3).

**Rev-B decision: the machine mask-lamp supply is NOT used.** Dylan's contract decision is to **install our own LEDs in the existing mask housings** and drive them from the board. The board drives each LED low-side from **VCC_5V logic power** through a **2N7002-class N-MOSFET** with a per-channel current-limit resistor (`Rled_*`, scaffolded at **330R** — final value TBD per LED brightness, see VERIFY). There is therefore **no LOGIC-to-MACHINE isolation barrier on the status LEDs** (they are pure logic-domain outputs, not machine-output contacts), and they are **not on the safety rail** (non-motion-critical).

| Lamp | FSM `set_light` name | OEM mask position | OEM supply | Board: MCP23017 OUT-A port.bit | MCP pin | Board net | Driver |
|---|---|---|---|---|---|---|---|
| 1st-ball | `first_ball` | PM-E24 | 12 VDC (OEM) / 15 VDC (measured) | A7 | 28 | L_FIRST | 2N7002 low-side, 330R limit |
| 2nd-ball | `second_ball` | PM-E25 | " | B0 | 1 | L_SECOND | " |
| strike | `strike` | PM-E26 | " | B1 | 2 | L_STRIKE | " |
| foul | `foul` | PM-E27 | " | B2 | 3 | L_FOUL | " |

(Source: lamp roles + PM-E positions from `phase8_io_board_spec.md` §1 outputs row 3 and system reference §4; board bits from `controller_io.py` `OUT_A_MAP` (`first_ball`=(0,7), `second_ball`=(1,0), `strike`=(1,1), `foul`=(1,2)) and `generate_kicad_netlist_revB.py` `OUTPUT_PINS` L_FIRST=28/L_SECOND=1/L_STRIKE=2/L_FOUL=3; driver topology from `phase8b_pcb_revB_spec.md` §3.3 and netlist `lamp_led_output()` (2N7002 + 330R `Rled_*`). LED returns wire to the **J_LAMP_LED** 6-pin connector: VCC_5V, GND, then the four LED-return lines.)

> **(VERIFY: final mask-LED type and `Rled_*` current-limit value (330R is a scaffold placeholder).** Per `phase8b_pcb_revB_spec.md` §11 item 5, the LED part and per-channel resistor must be locked for bowling-center brightness before assembly.) Note the OEM supply discrepancy: system reference says 12 VDC, the at-machine measurement says **15 VDC** — moot for our build since we abandon the machine lamp supply, but recorded here for anyone restoring the OEM mask.

---

### 4.9 The 7 relay-driven outputs (S / T / SP / BE / M / M2 / M1)

These are the controller's machine *outputs*. **Critical operating principle (see §3, §6):** the board does **not** switch motor current and does **not** source machine coil voltage. Each output is an **isolated dry relay contact** that closes/opens an *existing machine control circuit* — the machine's own contactors continue to switch the 115 VAC motors and retain their OEM run/braking behavior. The board commands coils; the machine's iron switches the motors. This preserves motor inrush handling and regenerative braking on the existing contactors, and is the key simplicity/safety win.

**Working voltage of the switched circuits:** the at-machine field sheet (item A1) measured **24 VAC** on the relay/coil circuits for all relays (SP presumed same). So each on-board relay contact only needs to make/break a **24 VAC contactor-coil circuit** — a small load, well within the relay's rating. (This 24 VAC measurement also lets the board's LOGIC↔MACHINE creepage relax from the conservative 250 VAC assumption in a future spin; the current fab board is still routed at the conservative spacing.)

**The relay (do not substitute the coil voltage):**

| Item | Value |
|---|---|
| Relay part | **Omron G5LE-14, 5 VDC coil**, SPDT |
| LCSC | **C116963** |
| Footprint | `Relay_THT:Relay_SPDT_Omron-G5LE-1` |
| Designators | K1–K6 (K7/M1 is DNP — see below) |
| BOM note | *"Critical: 5VDC coil. Do not substitute 9V/12V/24V coil."* |

(Source: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv` line for C116963. **The coil rail is 5 V**, driven by the logic-side 5 V supply through the relay-enable rail — *not* 24 V. The machine's 24 VAC is on the *contact* side only.)

**Coil drive chain (per relay):** MCP23017 OUT-A bit → series base resistor (1k) → **MMBT3904 NPN** (low-side) → relay coil. Coil high side connects to the **RELAY_ENABLE_RAIL** (the safety rail, §10); a **1N4148WS** flyback diode sits across the coil. Contacts (COM/NO) go to a per-function 2-pin terminal block (`J_MOTION_<name>`) with DNP RC-snubber + MOV footprints across the contact for AC-inductive suppression.

(Source: `generate_kicad_netlist_revB.py` `relay_output()`: `MMBT3904` Qk_*, `Rb_*`=1k, coil high to `RELAY_ENABLE_RAIL`, `Dfly_*`=1N4148, `Rsnub_*`=100R DNP, `Csnub_*`=10nF X2 DNP, `MOV_*` DNP. Per-relay flyback/snubber confirms `phase8b_pcb_revB_spec.md` §3.2.)

**The 7 outputs:**

| Output | Function | FSM use | Contact form | On safety rail | MCP23017 OUT-A port.bit | MCP pin | Net | Connector (bench / OEM-ref)¹ |
|---|---|---|---|---|---|---|---|---|
| **S** | Sweep motor contactor command | `set_sweep` (active) | isolated NO dry contact | **yes** | A0 | 21 | DRV_S → OUT_S_A/B | bench: **C1** (cavities C,D,N,T) |
| **T** | Table motor contactor command | `set_table` (active) | isolated NO dry contact | **yes** | A1 | 22 | DRV_T | bench: **C1** (cavities A,K,H,E,L) |
| **SP** | Spot solenoid command | `set_spot` (active) | isolated NO dry contact | **yes** | A2 | 23 | DRV_SP | bench: **C2A** (0 Ω) |
| **BE** | Back-end command (elevator/carpet/distributor/ball-lift; runs continuously) | future (⊕) | isolated NO dry contact | **yes** | A3 | 24 | DRV_BE | bench: straddles **C1+C2A** (coil also taps C1-FF @66Ω) |
| **M** | Master / control command | future (⊕) | isolated NO dry contact | **yes** | A4 | 25 | DRV_M | TBD at machine |
| **M2** | Sweep-reverse command | future (⊕) | isolated NO dry contact | **yes** | A5 | 26 | DRV_M2 | ⚠️ **OEM≠bench:** OEM=C1-17DD/18JJ/26BB/27FF + TSA/Expander; our bench=**C2A** (0 Ω) |
| **M1** | Ball-return command | none (DNP) | isolated NO dry contact | yes | A6 | 27 | DRV_M1 | **POPULATE-OPTIONAL / DNP** |

(Source: `controller_io.py` `OUT_A_MAP` (S=(0,0)…M1=(0,6)) — regression-checked against `generate_kicad_netlist_revB.py` `OUTPUT_PINS`; connector/cavity data from `phase8_channel_allocation.md` §3 "HARNESS UPDATE (bench-confirmed 2026-06-01)" and `phase8b_pcb_revB_spec.md` §3.2.)

Notes:
- **Bit-order gotcha:** in OUT_A the order is **M2 (bit A5, pin 26) before M1 (bit A6, pin 27)** — this matches the generator (`OUTPUT_PINS` M2=26, M1=27), not alphabetical. `controller_io.py` flags this explicitly.
- **M1 is DNP (do-not-populate).** Ball-return as a *separate* relay was never bench-confirmed on the 21/22 chassis and the FSM doesn't drive it. The footprint (K7/Q7/R85-R87/D13-D14/C10) is present but flagged DNP + excluded from BOM/POS. **Do not populate or harness M1 until confirmed at-machine** (`phase8b_pcb_revB_spec.md` §3.2, §11 item 6).
- **BE, M, M2, M1 are spare/future (⊕):** the minimum-viable FSM today drives only **S, T, SP** (motion) + the 4 lamps. BE/M/M1/M2 are wired on the board for when full machine control grows (`phase8_channel_allocation.md` §1).
- **S/T must not become the motor contactor or braking path** — the board only commands the *control/coil* circuit of the existing contactors; the OEM start/run/brake contacts stay on the machine (`phase8b_pcb_revB_spec.md` §3.1).
- **M2/sweep-reverse interlock:** regardless of which connector M2 lands on, the OEM Expander path includes a sweep-reverse motor-start interlock and a shorting-plug requirement ("expander cable must be terminated or sweep won't run"). The harness must **preserve that interlock function**, not merely jumper the cavity.

> ¹ **(VERIFY: all C1/C2A cavity landings for the 7 outputs.)** The "connector side" column is **OEM-reference / single-pair-bench only and is NOT a copper constraint** — the OEM factory wire tables and our Omega-Tek bench disagree on cavity routing (both correct for their chassis). M and M1 landings are unmeasured. Exact per-chassis terminal landings are resolved by the adapter harness at cutover (at-machine field sheet PART C). Do NOT bake any of these into copper.

> ⚠️ **(VERIFY: relay contact current rating + snubber/MOV population.)** At-machine field-sheet item A2 (coil/control current per output) was left blank/deferred to cutover; `phase8b_pcb_revB_spec.md` §11 items 1–2 list "confirm contact current/voltage for S/T/SP/BE/M/M2 and whether G5LE-1 margin is sufficient" and the 5 V coil-rail budget as open before assembly. The G5LE 10 A contact is almost certainly ample for a 24 VAC coil load, but it is not yet measured.

---

### 4.10 Cross-references and the "what's confirmed vs. deferred" summary

- Full sequence-of-operation (how these signals drive the cycle): **§3 Sequence of Operation / FSM** (and `lane_node/cycle_control_8270.py`).
- Camera scoring that replaces the pin-indicator lamps and uses the DIELL event for capture timing: **§3 System Architecture & Scoring**.
- Board electrical domains, opto front-ends, MCP23017/RP2040 bus, connectors: **§5 Board Architecture**.
- The relay-enable rail, NE555 watchdog, RP2040 RP_OK, TB/SC interlock, power-down/First-Ball-Zero rule: **§19 Safety Architecture**.

**Confirmed (locked) machine-I/O facts:**
- Cam form = dry contact, NC (A4). DIELL = NPN open-collector, ~16 V rest / ~0.7 V broken, 24 V supply (characterized end-to-end). Grippers = chassis-return, gripped = closed-to-ground (corrected at machine). Output working voltage = 24 VAC (A1). Relay = Omron G5LE-14 **5 VDC** coil (C116963). Opto = PC817B (C5692981). Expander = MCP23017 I²C (C47023, *not* SPI). Watchdog timer = bipolar NE555 (NE555DR, C7593). RP2040 fast inputs = **GP6–GP13**, RP2040_OK = GP2, UART = GP0/GP1. Board = 250×225 mm, 4 copper layers.

**Deferred to cutover (do NOT guess, NOT board-gating):**
- Per-gripper GS#→C2A cavity + GS#-to-pin order; per-cam SA/SB/SC/TA1/TA2/TB→C2A cavity + edge-to-angle polarity; exact C1/C2A landings for all 7 outputs; GP/OS/BS/Foul/PBZ/PBC cavities and (for GP/OS/BS/Foul) dry-vs-AC form; TB/SC interlock terminal landing; relay contact current (A2); mask-LED type + `Rled_*` value; M1 existence as a separate relay.


## 5. Rev-B Controller Board: Overview, Domains & Isolation

This section describes the Rev-B controller board as a whole: what it is, what it replaced, the three electrical domains it is physically divided into, how those domains are kept apart, and the one safety rule that must never be violated when working on it. Read this before Section 8 (Inputs), Section 9 (Outputs & Relays), Section 10 (Safety Rail & Watchdog), or Section 7 (RP2040 Co-Processor & Firmware) — those sections drill into individual circuits, but they all assume the domain model and isolation philosophy established here.

> **Scope of this manual.** "Rev-B" is the second-generation, fully integrated lane controller board (KiCad project `wsl-phase8b`). At the time of writing it is a **bare-PCB fab-ready** design — the Gerbers/drill and a fully-assembled JLCPCB PCBA package have been generated and pass the board's design-rule check (DRC) and audit gates — but it is **not yet assembly- or cutover-released**. Several values are still flagged for at-machine confirmation; those are called out as `(VERIFY: …)` where they appear.

---

### 5.1 What the board is, in one sentence

> Rev-B is a one-lane, 250 × 225 mm, four-copper-layer, fully integrated controller board that reads isolated machine inputs, runs the fast cam/ball input capture + safety supervisor on an RP2040, and commands existing machine control circuits through on-board isolated relay contacts whose coils are disabled by a non-bypassable hardware safety rail.

One physical board controls exactly **one bowling lane** (one AMF 82-70 pinsetter). A lane *pair* (e.g. lanes 21 and 22) uses **two identical boards** driven by a single Raspberry Pi. The camera used for pin scoring may be shared across the pair, but every piece of machine-control wiring — relay outputs, cam/switch inputs, the safety loop — is **per lane, per board**. There is no "master/slave" board concept; the two boards are interchangeable units distinguished only by which lane's harness and which Pi I²C bus / UART they are wired to.

---

### 5.2 What Rev-B consolidated (the Rev-A → Rev-B story)

The previous-generation ("Rev-A") bench rig that proved out Phase 8 was an assembly of separate commercial-off-the-shelf (COTS) modules wired together on a Raspberry Pi:

- a relay module (an AEDIKO-style relay HAT) that switched the machine control circuits;
- separate opto-isolator input modules (AL-ZARD / DONGKER-class 8-channel opto boards) that read the cams, ball detectors, and switches;
- a small custom NE555-based hardware **watchdog + AC-interposer PCB** (the "fourth K-pillar" — a 555 monostable the Pi had to keep kicking, plus a 1N4007/10 µF rectifier front-end that turned a 24 VAC machine signal into a clean opto input).

> *Brand attribution note:* the "AEDIKO" relay module and "AL-ZARD / DONGKER" opto-module names come from the Phase 8 project history (the COTS parts used on the bench rig). The Rev-B design documents read for this manual name the **integrated replacement parts** (below), which are the authoritative source of truth for what is actually on the board.

**Rev-B collapses all three of those into one board.** It is a from-scratch integrated controller, not a carrier for COTS modules. The functions map across as follows:

| Rev-A COTS element | Rev-B on-board replacement | Key part(s) |
|---|---|---|
| AEDIKO relay HAT | On-board isolated dry-contact relays, one per motion output | Omron **G5LE-14, 5 VDC coil** SPDT relay (LCSC C116963) — 6 placed + 1 DNP |
| AL-ZARD / DONGKER opto-input modules | On-board opto-isolated input front-ends, one per channel | **PC817B** optocoupler, DIP-4 (LCSC C5692981) — 32 placed |
| NE555 watchdog + AC-interposer PCB | On-board NE555 hardware watchdog, integrated into the safety rail | **NE555DR** bipolar timer, SOIC-8 (LCSC C7593) |
| *(new in Rev-B)* | RP2040 fast cam/ball front-end + safety supervisor | Raspberry Pi **Pico** module (Raspberry Pi SC0915) |
| *(new in Rev-B)* | Isolated field-wetting supply | TRACO **TMA-0505S** 5 V→5 V 1 W isolated DC/DC (DigiKey-locked, ref U37) |

Two functions are genuinely **new** in Rev-B (they did not exist as discrete modules on the bench rig):

1. **An RP2040 co-processor (the Pico module).** It owns the fast inputs (cams + ball detectors), runs a fail-safe motion max-run backstop independently of the Pi (per-cam-edge cam-stop *overrun* enforcement is deferred to firmware v1.1), forwards events to the Pi over UART, and — critically — contributes a fail-safe permission line (`RP2040_OK`) into the safety rail. See Section 7.
2. **Isolated field "wetting."** Dry-contact inputs (grippers, cams, switches) need a sense voltage to detect a contact closing. Rev-B generates that voltage on-board from an **isolated** DC/DC converter (the TMA-0505S, ref U37), so the sense rail (`FIELD_WET_V`) and its return (`FIELD_GND`) are galvanically separated from logic ground. A machine-side fault cannot backfeed the Pi.

> ⚠️ **Source-of-truth correction.** An earlier parts-planning draft (`phase8b_pcb_revB_BOM_power.md`) suggested a generic **B0505S-1W** isolated brick for field wetting. The **as-built netlist and the locked fab BOM use the TRACO TMA-0505S** (`scripts/generate_kicad_netlist_revB.py` `block_supplies()`, footprint `Converter_DCDC_TRACO_TMA-05xxS_…`; off-board hardware sheet ref **U37**, "Locked exact part"). Use the **TMA-0505S** — the B0505S reference is stale.

What Rev-B deliberately **does not** integrate:
- **No motor power.** Motor line current (115 VAC) is never routed on the PCB. The machine's own S/T contactors continue to switch motor current and keep their OEM run/braking behaviour.
- **No machine coil supply.** The board does not generate the machine's 24 V control/coil voltage. Relay *contacts* switch the machine's existing 24 V circuits; the board only opens and closes dry contacts.
- **No PoE.** Rev-B v1 has no Power-over-Ethernet PD stage; 5 V comes from an external regulated supply or Pi-side 5 V.
- **No pin lamps / KX scorer relay.** Pin state comes from camera scoring (Track A), so the old pin-lamp driver bank and the KX scorer-data relay are omitted. (A fourth I²C expander, "OUT-B" @ 0x23, is reserved in software for an optional future physical pindicator but is **not populated**.)

---

### 5.3 Board statistics

| property | value | source |
|---|---|---|
| Board outline (Edge.Cuts) | **250 × 225 mm** | spec `phase8b_pcb_revB_spec.md` (re-audit, line "Edge.Cuts = 250×225mm") |
| Copper layers | **4** (F.Cu / In1.Cu / In2.Cu / B.Cu) | spec §9; netclass doc §2 |
| Layer stack | F.Cu = signal; In1.Cu = GND plane (logic); In2.Cu = power (VCC_5V / VCC_3V3); B.Cu = signal (field/output) | netclass doc §2 |
| Copper weight | 1 oz (clearance/width budgets assume 1 oz) | netclass doc §1 |
| Schematic components | 216 | spec / session-close §2 |
| Board footprints (incl. test pads + mounting holes) | ~236 | session-close §2 |
| Named nets | 184, all classified, 0 anonymous `N$` | session-close §2; netclass doc |
| Net classes | 5: Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21 | session-close §2 |
| DRC state | 0 violations / 0 unconnected pads / 0 footprint errors (routed-manual board, conservative rules) | session-close §2 |
| Mounting | 4× M3 holes (refs MK1–MK4), DIN-enclosure target | offboard-hardware / DNP-excluded sheets |
| Assembly split | 189 non-DNP BOM refs / 27 DNP refs / 20 non-DNP mechanical-test refs excluded from assembly | spec (Codex fab-prep pass) |

> **Routing method (for the next engineer who opens KiCad):** the board is **manually / scripted-tiered routed**, not autorouted. Full-board FreeRouting was attempted four times and rejected — the DSN export cannot carry the creepage intent from `wsl-phase8b.kicad_dru`, and it failed to produce a `.ses` headlessly. The canonical *unrouted* source board is `kicad/wsl-phase8b.kicad_pcb`; the routed working board is `kicad/wsl-phase8b.routed-manual.kicad_pcb`. After any board edit, re-run `scripts/export_fab_revB.py` (it re-runs DRC + audit and regenerates the fab package).

---

### 5.4 The three electrical domains

Rev-B is divided into **three electrical domains**. The domain split is the central organizing idea of the whole board: it is reflected in the schematic net names, the physical placement (board "rooms"), the silkscreen labels, the test-point grouping, and the DRC net classes. **If you are tracing a fault, the first question is always "which domain is this net in?"** because that tells you what reference it sits on and what is (and is not) allowed to touch it.

| domain | what lives here | voltage reference | typical voltages |
|---|---|---|---|
| **LOGIC** | Raspberry Pi interface, the 3× MCP23017 I²C expanders, the RP2040 (Pico), UART, I²C, watchdog trigger, relay-coil drive transistors, status-LED drive transistors, the safety-rail logic | **GND** (logic ground) | 3.3 V / 5 V |
| **FIELD** (machine-sense, **isolated**) | the *field* (LED) side of every input optocoupler — cams, grippers, DIELL ball detectors, foul, pushbuttons — and the isolated wetting rail | **FIELD_GND** (isolated; **not** tied to GND) | 5 V wetting; 24 VAC on AC-sense channels |
| **MACHINE OUTPUT** | the relay *contacts* that open/close existing machine control circuits, plus their snubber/MOV footprints | floating / machine-referenced | 24 VAC measured (see note) |

A fourth grouping — the **SAFETY RAIL / CONTROL** nets (`RELAY_ENABLE_RAIL`, `RAIL_GATE`, the relay coil low-sides `COIL_LO_*`, the AND-chain bases `BASE_AND_*`, and the interlock-loop nets `SAFE_*`) — is **electrically part of the LOGIC domain** (it sits on logic-side coil supply), but it is given its own net class for current-carrying and integrity reasons. Do not mistake it for a machine-output domain: the `SAFE_STOP_RETURN` / `SAFE_TBSC_RETURN` interlock returns are **low-voltage** sense/loop nets, not 250 VAC machine contacts. (This was a real classification bug caught during routing — see §5.6.) The safety rail is covered in detail in **Section 10 (Safety Rail & Watchdog)**.

#### 5.4.1 LOGIC domain

The Pi-side world. Powered from an external regulated **5 V** supply (a DIN-rail PSU such as the Mean Well HDR-15-5, or Pi-side 5 V distribution) with a reverse-polarity Schottky (SS14, ref D17) and transient protection on the input. The Pico module supplies the **3.3 V** rail that powers the three MCP23017 expanders, the opto logic-side pull-ups, and the I²C pull-ups. Logic ground (`GND`) is permitted to exist **only** on the Pi/control side of the optocouplers, the relay-coil drivers, and the status-LED drivers — it must never appear on the field or machine-output side of an isolation barrier.

Key rule: the **MCP23017s run at 3.3 V**, not 5 V, specifically so the I²C bus is safe for the Raspberry Pi's 3.3 V GPIO. Never run the MCP23017s at 5 V on the Pi bus without a level shifter.

#### 5.4.2 FIELD (machine-sense) domain — isolated

The field side of every input opto. Each input channel can be populated for one of two front-end styles (the choice is per-channel and is finalized after at-machine measurement — see Section 8):

- **Dry-contact wetting** (the confirmed default for the cams, and expected for grippers/switches): the isolated wetting rail `FIELD_WET_V` feeds the opto LED through a series resistor; the machine contact closes that node to `FIELD_GND` to assert the input.
- **24 VAC sense:** a rectifier/resistor/bleed front-end (Rev-A interposer style) turns a 24 VAC machine signal into an opto LED drive.

The whole field domain sits on **FIELD_GND**, which the isolated TMA-0505S keeps separate from logic `GND`. This is `spec §8.3` **option 1: isolated field wetting** — the default for the Rev-B safety review.

> **Measured working voltage.** The at-machine field session measured the machine-output relay working voltage at **24 VAC** on all accessible relays (cam inputs are **dry contacts, normally-closed at rest**). The board's DRC, however, is still cut to **conservative 250 VAC-derived creepage** numbers (see §5.6) so routing stays on the safe side; relaxing to 24 V numbers is a future DRC/policy edit, not a board re-route. `(VERIFY: SP solenoid working voltage is presumed 24 VAC — its coil terminals were inaccessible at the field session; glance-confirm at cutover.)`

#### 5.4.3 MACHINE OUTPUT domain

The relay contacts. These are **isolated dry contacts** — the board does not source the voltage across them. Depending on the final harness a contact may switch 24 VAC, 12 VDC, or another machine control voltage; the board only closes/opens the contact inside an *existing* machine control circuit. Every motion-output contact carries footprints for arc-suppression (an RC snubber and a MOV), **depopulated (DNP) by default** until the inductive load is characterized at the machine.

For **S (sweep)** and **T (table)** specifically: the board must **command** the existing contactor/relay coils through its isolated contacts; it must **not** become the motor contactor or the de-energized braking path. The OEM contactors keep their motor start/run and braking contact behaviour. (See Section 9 for the full output contract.)

---

### 5.5 Physical layout: banding, rooms, and the keepout gutters

The three domains are not just a naming convention — they are **physically banded** across the board, left to right, with **no-copper keepout gutters** between them. This is what makes the isolation auditable: a logic trace simply cannot wander into the machine-output region because there is a deliberate copper-free channel in the way.

```
   LEFT band          gutter           CENTER band            gutter         RIGHT band
 ┌───────────┐   ┌─────────────┐   ┌────────────────┐   ┌─────────────┐   ┌────────────┐
 │   FIELD   │   │  no-copper  │   │     LOGIC      │   │  no-copper  │   │  MACHINE   │
 │  inputs   │   │   keepout   │   │  Pi / MCP /    │   │   keepout   │   │  OUTPUT    │
 │ (PC817    │   │   gutter    │   │  RP2040 +      │   │   gutter    │   │  (G5LE     │
 │  field    │   │             │   │  SAFETY rail / │   │             │   │  relays +  │
 │  side)    │   │             │   │  watchdog +    │   │             │   │  snubber/  │
 │           │   │             │   │  status-LED    │   │             │   │  MOV)      │
 │           │   │             │   │  drivers       │   │             │   │            │
 └───────────┘   └─────────────┘   └────────────────┘   └─────────────┘   └────────────┘
   ~X74            X76.8–80          X104–151             X181–184           X176–178
```

(X values are board millimetre coordinates from the placement audit; pairwise band overlap is **0**, verified.)

| board "room" | contents |
|---|---|
| LEFT — FIELD | field (LED) side of the input optos; isolated wetting front-ends |
| CENTER — LOGIC + SAFETY | Pi connector, 3× MCP23017, RP2040 (Pico), I²C/UART, NE555 watchdog, safety-rail pass-FET + AND chain, and the four status-LED FET drivers (lower logic band) |
| RIGHT — MACHINE OUTPUT | the seven G5LE relays, their per-channel function-named output terminals, and the snubber/MOV footprints |

**Why the gutters sit *between* pad columns, not on them.** An earlier placement put the FIELD/LOGIC keepout directly on top of the PC817 field pad column, which blocked the routes that legitimately have to reach those pads. The corrected placement moves the gutter into the space **between** the field and logic pad columns. If you re-place or re-route, preserve that: the gutter is the air-and-no-copper zone *between* domains, never on a pad row that needs to be wired.

**Plane discipline (the vertical dimension of isolation).** The isolation barrier is not only lateral — it is vertical too. On the inner layers:

- **In1.Cu (logic GND plane)** must **not** extend under the FIELD or MACHINE OUTPUT rooms. Pour keepouts hold it back.
- **In2.Cu (power pour, VCC_5V / VCC_3V3)** is logic-side only and likewise voided under the FIELD and MACHINE rooms.

A ground or power plane sneaking under a relay contact or an opto's field pads would short the creepage path through the board even though the surface traces look clear. This is the 4-layer equivalent of the Rev-A bottom-copper keepout.

---

### 5.6 The isolation philosophy

The governing principle is simple and absolute:

> **The two isolation barriers may be crossed only *inside* the optocoupler and relay packages — never in board copper.**

There are exactly two barriers:

1. **LOGIC ↔ FIELD** — crossed only inside the **PC817 optocoupler** packages. The LED side of each PC817 is FIELD; the phototransistor side is LOGIC. Light crosses the gap; copper does not.
2. **LOGIC ↔ MACHINE OUTPUT** — crossed only inside the **G5LE relay** packages. The coil side is LOGIC/safety-rail; the contact side is MACHINE. A magnetic field crosses the gap; copper does not.

No trace, via, copper pour, or plane may shorten either barrier below the creepage/clearance policy. The DRC rules in `wsl-phase8b.kicad_dru` enforce this so that KiCad will flag, for example, a logic trace routed under a relay contact pad or a ground plane crossing an opto.

**Two ground references, proven separate.** Logic `GND` and isolated `FIELD_GND` are distinct nets that share **zero** nodes (verified on the actual board, including test pads). This separation is what makes the FIELD domain truly isolated; if you ever find a copper path joining them, the isolation is broken and the board is unsafe to power against a live machine.

**Creepage/clearance policy (current, conservative).** The live DRC uses these numbers, derived for a conservative 250 VAC RMS working assumption (pollution degree 2, basic insulation):

| barrier / situation | policy distance enforced in DRC |
|---|---|
| LOGIC ↔ FIELD (across PC817) | ≥ **2.5 mm** (clearance + creepage) |
| LOGIC ↔ MACHINE (across G5LE) | ≥ **3.2 mm** (clearance + creepage) |
| machine-output trace ↔ any non-output copper | ≥ **2.0 mm** |
| machine-output trace ↔ board edge | ≥ **1.0 mm** |
| between independent machine-output channels | ≥ **1.5 mm** (a shorted channel must not arc to its neighbour) |

The actual machine-output working voltage was **measured at 24 VAC**, which would permit much tighter functional-insulation spacing (~0.5–1.0 mm). The board intentionally **keeps the wide conservative numbers** for now — relaxing them later is a DRC/policy edit and a re-export, whereas tightening after routing would force a re-route. `(VERIFY: the 250 VAC→24 VAC creepage relaxation is an explicitly deferred policy decision — confirm the final creepage numbers before any production shrink/spin.)` The current fab package proves isolation by **copper clearance + package spacing + all-layer no-copper keepouts only** — it does **not** rely on milled isolation slots under the optos/relays. Milled slots remain an optional future mechanical-hardening pass that would require a re-DRC and re-export.

> **The Machine_Output clearance has two numbers — don't be alarmed.** The Machine_Output net class lists a small **0.35 mm base** clearance; that is only the same-channel fabrication/routing floor (a relay's own contact pair and its RC snubber across that pair are *intentionally* adjacent). The real insulation constraints — LOGIC↔MACHINE ≥ 3.2 mm and channel-to-channel ≥ 1.5 mm — are enforced by the custom `.kicad_dru` rules, not by that base class number alone.

**A classification trap to remember (logged so it survives):** the `SAFE_*` interlock-loop nets were *originally* mis-filed as machine-output domain, which wrongly forced the ≥ 3.2 mm LOGIC↔MACHINE creepage against the very rail/gate they are supposed to drive (7 false DRC violations). They are **low-voltage rail/interlock control nets in the LOGIC/safety-rail domain** and take logic-domain clearance. If you re-classify nets, the test is electrical reality (what voltage and reference does this net actually carry?), not a pattern match on the name.

---

### 5.7 The non-negotiable safety rule

> **This board must NEVER be treated as the only safety device.**

Rev-B adds *layers* of protection; it does not replace the machine's existing safety chain. When working on, bench-bringing-up, or servicing this board, treat the following as permanent, hardware-level facts:

1. **The upstream machine safety chain stays live and primary.** The **Stop switch** (red button) and the **C.I.S.** (plug-duct cover switch) are wired in parallel and both **cut the master circuit breaker** in the rear control panel — killing the whole machine. That chain sits *upstream* of this board and is the **final physical stop**. The board does not, and must not, defeat it. `(VERIFY: exact J_SAFETY terminal landings on this SS + Omega-Tek chassis are a cutover-day wiring task; the design accepts a normally-closed series loop, but the precise terminals differ from the OEM 9800-MP and are confirmed at cutover.)`

2. **Live motor current never touches the board.** Motor power stays on the machine's S/T contactors. The board commands those contactors' control coils through isolated contacts only.

3. **The board fails *open* (motion-dead) on loss of any of:** logic power, the NE555 watchdog kick, RP2040 health (`RP2040_OK`), arm permission, or the hardware interlock loop. Every one of these is a series condition on the relay-enable rail, and **the Pi cannot bypass them in software** (see Section 10).

4. **The safety rail de-energizes coils; it cannot un-weld a stuck contact.** The rail drops the relay *coils*, but a relay contact that has welded closed will stay closed — which is exactly why relay contact rating, arc suppression (snubber/MOV), and validation are safety-relevant, and why the master breaker / Stop / C.I.S. chain remains the ultimate stop. `(VERIFY: final relay contact current/voltage rating for S/T/SP/BE/M/M2 — confirm G5LE-14 margin is sufficient — pending the at-machine coil/control current measurement.)`

5. **Never power this board against a live machine until the full hardware safety chain is bench-proven** off-live (spec §12.9 bench bring-up sequence). The software (`lane_node/controller_io.py`) is only the soft half; `io.interlock_ok()` is a *secondary advisory echo*, never the authoritative interlock.

Carry this rule into every later section: when Section 9 describes a relay closing, or Section 7 describes the RP2040 raising `RP2040_OK`, the closing/permitting is always *in addition to* — never *instead of* — the machine's own breaker, interlock, and braking.

---

### 5.8 Reference designator → function map (orientation)

For bench bring-up and probing, the as-built reference designators map to functions as follows. **The function-named connector labels are the authoritative wiring guide — not the raw `Jn` numbers or any machine cavity number.** The adapter harness maps the function-named terminals to the machine's C1/C2A connectors at cutover, which is why no machine cavity number is baked into copper.

| ref(s) | function-named label | what it is |
|---|---|---|
| A1 | — | RP2040 (Raspberry Pi **Pico** module, SC0915); program after assembly. **Do not** use a Pico H/WH with pre-soldered headers. |
| U1 | (MCP_IN_A @ 0x20) | MCP23017 — high-use slow inputs (grippers GS1–GS10, GP, OS, BS, PBZ, PBC, Foul) |
| U2 | (MCP_IN_B @ 0x21) | MCP23017 — manual / 10th-frame / spare slow inputs |
| U3 | (MCP_OUT_A @ 0x22) | MCP23017 — 7 relay command bits + 4 status-LED bits |
| U4–U35 | — | PC817B input optocouplers (32 channels) |
| U36 | — | NE555DR hardware watchdog timer |
| U37 | — | TRACO TMA-0505S isolated field-wetting DC/DC |
| K1–K6 | — | G5LE-14 5 VDC motion relays (the six populated outputs) |
| K7 | — | G5LE M1 relay — **DNP** (not populated) |
| Q1–Q6 | — | MMBT3904 NPN relay-coil drivers (one per populated relay) |
| Q7 | — | MMBT3904 M1 coil driver — **DNP** |
| Q8–Q11 | — | 2N7002 low-side FETs driving the four status LEDs |
| Q12, Q13 | — | AO3400A N-FETs: watchdog kick + watchdog-OK gates |
| Q14 | — | AO3401A **P-channel** rail pass-FET (gates the relay-enable rail) |
| D17 | — | SS14 reverse-polarity Schottky on the 5 V input |
| J1 | **J_PI** | 2×10 IDC header to the Pi: I²C, UART, watchdog kick, arm, INT, 5 V, 3V3, GND, RP2040_OK |
| J2 | **J_PWR 5V** | 3-pos screw terminal — regulated 5 V logic/input power |
| J3 | **J_FAST_IN** | 10-pos — SA/SB/SC/TA1/TA2/TB + DIELL-L/DIELL-R field inputs |
| J4 | **J_SLOW_IN_A** | 14-pos — GS1–GS10, GP, OS, BS |
| J5 | **J_SLOW_IN_B** | 12-pos — PBZ, PBC, Foul, 10th, manual, AUX/spares |
| J6–J11 | **J_MOTION_BE / _M / _M2 / _S / _SP / _T** (in this annotation order) | six 2-pin isolated contact terminals, one per populated motion output |
| J12 | **J_MOTION_M1** | M1 ball-return output terminal — **DNP** |
| J13 | **J_LAMP_LED** | 6-pos — VCC_5V, GND, and the four status-LED returns |
| J14 | **J_SAFETY** | 4-pos — the TB/SC interlock loop + Stop/CIS chain sense (two NC loops in series) |
| MK1–MK4 | — | M3 mounting holes |
| TP1–TP16 | — | test pads (rails, I²C, watchdog nodes, ARM_PERMIT, RP2040_OK, SAFE_STOP_RETURN, RELAY_ENABLE_RAIL) |

> ⚠️ **Note the motion-terminal ordering.** The output relays are spec'd in functional order **S, T, SP, BE, M, M2, M1**, but the *connector reference numbers* J6–J11 were assigned by the tool's annotation order as **BE, M, M2, S, SP, T** (with J12 = M1, DNP). When wiring the harness, **follow the silkscreen function label** (`J_MOTION_S`, `J_MOTION_T`, …), not the `Jn` number, to avoid swapping the sweep and table outputs.

**Two DNP groups you will see on the board but should not populate without authorization:**
- **The entire M1 (ball-return) channel** — K7, Q7, the M1 connector J12, and its associated passives (R85/R86/R87, D13/D14, C10) — is **DNP**. M1 has not been confirmed to exist as a separate command on this chassis and the FSM does not drive it. Footprint present, do not populate until verified at-machine. `(VERIFY: whether ball-return exists as a separate relay command on this SS chassis — keep M1 DNP until proven.)`
- **Every motion-output snubber/MOV** (the `100R DNP` resistors R69/R72/R75/R78/R81/R84/R87, the `10nF X2 DNP` caps C4–C10, and the `MOV DNP` parts D2/D4/D6/D8/D10/D12/D14) is **DNP** until the inductive load on each output is characterized. `(VERIFY: per-output snubber/MOV values after at-machine inductive-load measurement.)`

---

### 5.9 Cross-references

- **Section 8 — Inputs (fast + slow):** the PC817 front-ends, the RP2040 fast inputs (cams + DIELL on **GP6–GP13**), the MCP23017 slow-input banks, and the dry-contact-vs-24VAC population options.
- **Section 9 — Outputs & Relays:** the G5LE relay channels, the MMBT3904 coil drivers, the function-named motion terminals, the S/T contactor-command contract, and the status-LED drivers.
- **Section 10 — Safety Rail & Watchdog:** the relay-enable rail, the AO3401A pass-FET, the ARM/RP2040_OK AND chain, the NE555 watchdog, and the J_SAFETY interlock loop — the hardware enforcement behind §5.7.
- **Section 7 — RP2040 Co-Processor & Firmware:** the Pico's role, the fail-safe `RP2040_OK` line, the UART event/command protocol, and the cam-stop / max-run backstop.


## 6. Rev-B Power Architecture

This section is the authoritative reference for how the Phase 8 Rev-B lane-controller PCB is
powered: where each voltage comes from, what it feeds, how much current it must carry, and — just
as important — which voltages the board deliberately does **not** generate. If you are bringing a
board up on the bench or fault-finding one in service, read this before you apply power.

The single hard rule that frames everything below: **the PCB generates only its own low-voltage
logic rails, an isolated field-wetting supply, and status-LED drive current. It never sources the
machine's motor power or its 24 V coil-control power.** Those stay on the AMF 82-70 machine's own
contactors and transformer (T2/T3/T4); the board only opens and closes isolated dry relay contacts
inside the machine's existing control circuits. (See Section 9, *Output Contract / Relay Stage*, and
Section 10, *Safety Rail*, for how those contacts are gated.)

> **Scope:** one PCB controls one lane. A lane pair runs two identical boards on one Raspberry Pi.
> Each board has its own independent set of the rails described here.

---

### 6.1 Power Rail Overview

The board has **four** power domains. Three are generated or distributed on-board; the fourth
(machine coil power) is named here only to make explicit that it is *not* on the board.

| Rail | Net name | Source | Nominal | Isolated from logic GND? | Feeds |
|---|---|---|---|---|---|
| **Raw 5 V input** | `VCC_5V_RAW` | External regulated 5 V at `J_PWR` (refdes **J2**), through reverse-polarity Schottky **D17 (SS14)** | +5 V | No (logic side) | Anode of D17 only; becomes `VCC_5V` after the diode |
| **Protected 5 V logic** | `VCC_5V` | Cathode of D17 | ~+4.7 V (5 V − Schottky Vf) | No (logic side) | Pico VSYS, relay coils via the rail-gate FET, NE555 watchdog, TMA-0505S primary, status-LED anode, I²C-header 5 V pin | 
| **3.3 V logic** | `VCC_3V3` | **Raspberry Pi Pico module 3V3 OUT** (Pico pin 36) | +3.3 V | No (logic side) | All 3× MCP23017 (VDD + RESET), every PC817 logic-side pull-up, the I²C bus pull-ups, 3V3 bulk cap |
| **Isolated field-wetting 5 V** | `FIELD_WET_V` / return `FIELD_GND` | **On-board isolated DC/DC TMA-0505S** (refdes **U37**), primary from `VCC_5V` | +5 V isolated | **Yes** — galvanically isolated from logic GND | Field (input) side of the dry-contact opto front-ends only |
| *(Machine 24 V coil power)* | *(not on board)* | **Machine's own T2/T3/T4 transformer** | ~24 VAC measured | n/a | Nothing on-board sources it. Relay *contacts* switch it externally. |

Two ground nets exist and must never be tied together on the board:

- **`GND`** — logic ground. Reference for the Pi, Pico, MCP23017s, NE555, relay-coil drive,
  status-LED drivers, and the *logic* side of every optocoupler.
- **`FIELD_GND`** — isolated field ground. The return of the TMA-0505S secondary and the reference
  for the *field* side of the dry-contact input optos. Kept in its own layout room with all-copper
  keepout gutters (see Section 13, *Layout / Isolation*). The isolation audit confirmed `GND` and
  `FIELD_GND` share **zero** nodes on the routed board.

> **No on-board PoE in v1.** Rev-B v1 has no Power-over-Ethernet PD circuit. 5 V comes in over wire
> at J2. PoE is explicitly out of scope for this revision.

---

### 6.2 The 5 V Logic Input — `J_PWR` (J2) and SS14 Protection

#### 6.2.1 Connector and source

External regulated 5 V enters the board at **`J_PWR`**, which is reference designator **J2** on the
silkscreen.

| Item | Value |
|---|---|
| Refdes | **J2** |
| Function | Regulated 5 V logic/input power in |
| Part | Phoenix Contact **MKDS 1,5/3-5,08** screw terminal (MPN **1715734**) |
| Footprint | `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal` |
| Pitch | 5.08 mm, horizontal wire entry |
| Positions | 3 |

J2 is a **fixed screw terminal block**, not a pluggable header — bare wires land directly in it and
there is **no off-board mating plug** (it does not appear in the harness-mating-parts list). Pinout
per the netlist generator (`block_connectors`):

| J2 pin | Net | Notes |
|---|---|---|
| 1 | `VCC_5V_RAW` | +5 V in (pre-protection) |
| 2 | `GND` | Logic ground |
| 3 | `GND` | Logic ground (second ground landing) |

The 5 V source itself is **off-board** and is *not* a placed BOM part. The Rev-B power contract
allows either a DIN-rail regulated 5 V PSU (the BOM-power draft cites an **HDR-15-5**-class supply
as the example) or the Raspberry Pi's own 5 V distribution. Whatever is chosen must be a *regulated*
5 V rail sized for the worst-case load in Section 6.6. (VERIFY: the exact off-board 5 V PSU make/model is
not fixed in any fab artifact — it is specified only as "regulated 5 V, HDR-15-5 class or Pi 5 V" and
must be selected at install.)

#### 6.2.2 Reverse-polarity + transient protection — D17 (SS14)

Immediately after J2, the raw input passes through a series **Schottky diode** that protects the
whole board against a reversed supply and clamps input transients.

| Item | Value |
|---|---|
| Refdes | **D17** |
| Part | **SS14** Schottky (1 A, 40 V, SMA / DO-214AC) |
| LCSC | **C2480** (MDD) |
| Footprint | `Diode_SMD:D_SMA` |
| Symbol | `Device:D_Schottky` (tag `D_PROT` in the generator) |

Orientation (from `block_connectors`): **anode → `VCC_5V_RAW`, cathode → `VCC_5V`.** This is a
series diode in the +5 V line:

```
J2.1 (VCC_5V_RAW) --->|--- VCC_5V   (D17 anode on the raw side, cathode on the protected side)
                     SS14
```

How it protects the board:

- **Reverse polarity:** if 5 V and GND are swapped at J2, D17 is reverse-biased and blocks current
  — the board sees nothing rather than back-powering through every IC. This is the classic
  series-Schottky reverse-battery guard; a Schottky is used so the forward drop is small.
- **Forward drop / why "protected 5 V" is a bit below 5 V:** in normal operation D17 drops roughly
  0.3–0.5 V (its Schottky Vf at the board's load current), so `VCC_5V` sits a few hundred millivolts
  below the input. This is intentionally fine: the Pico runs from VSYS down to ~1.8 V via its
  internal buck-boost, the G5LE 5 V relay coils tolerate the small drop, and the TMA-0505S accepts a
  ±10 % input window. Size the upstream PSU so that **after** the SS14 drop the rail is still a
  healthy ~4.6–4.8 V under full relay load.
- **Transient clamping:** the Schottky plus the board's bulk/decoupling capacitance (the 3V3 bulk
  `C_3V3_BULK` 10 µF on the downstream side and the NE555 `C_WDOG_VCC` 0.1 µF) absorb the small
  inductive kicks from the supply leads. The board does *not* carry a large input bulk electrolytic
  on `VCC_5V` in this revision; the heavy inductive energy (relay-coil flyback) is handled locally at
  each coil by its own flyback diode (Section 6.5), not at the input.

> ⚠️ D17 is a **1 A** part. It carries the *entire* board's 5 V draw (logic + all energized relay
> coils + the TMA-0505S primary). The Section 6.6 budget shows the worst case is well under 1 A, but
> if relay count or coil current ever grows, re-check D17's rating before populating.

---

### 6.3 The 3.3 V Logic Rail — `VCC_3V3` from the Pico

There is **no dedicated 3.3 V regulator** on the Rev-B v1 board. The 3.3 V rail is taken from the
**Raspberry Pi Pico module's own 3V3 output**.

| Item | Value |
|---|---|
| Source | Pico module **pin 36** (3V3 OUT), net `VCC_3V3` |
| Pico refdes | **A1** (Raspberry Pi Pico, SC0915) |
| Local decoupling | `C_3V3_BULK` (10 µF, 0805) to GND, plus a 0.1 µF (`C_<refdes>`) at each MCP23017 |

From `block_rp2040`: `VCC_5V` feeds the Pico's **VSYS (pin 39)**, and the Pico's on-board regulator
produces 3.3 V at **pin 36**, which the board uses as `VCC_3V3`. The Pico's eight GND pins (3, 8, 13,
18, 23, 28, 33, 38) tie to logic `GND`.

What `VCC_3V3` feeds and **why it must be 3.3 V, not 5 V:**

- **All three MCP23017 I²C expanders** (VDD pin 9 and ~RESET pin 18 of each — see `block_mcp`).
- **Every PC817 optocoupler logic-side pull-up** (`Rpu_*`, 10 kΩ) — the opto phototransistor
  collector pulls the logic net to `VCC_3V3` when idle.
- **The single I²C bus pull-ups** (`R_I2C_SDA`, `R_I2C_SCL`, 4.7 kΩ each to `VCC_3V3`).

The MCP23017s and the opto logic side run at **3.3 V specifically so the I²C bus and all logic
signals are Raspberry Pi-safe.** The Pi's GPIO/I²C pins are 3.3 V and are **not** 5 V tolerant.
Running the MCP23017s at 5 V on the Pi's I²C bus without a level shifter would drive 5 V logic highs
back into the Pi and risk damaging it. The contract is explicit: *do not run the MCP23017s at 5 V on
the Raspberry Pi I²C bus.* If a future cost-down revision replaces the Pico stamp with a bare RP2040,
that revision must add a dedicated 3.3 V regulator (the BOM names AP2112K-3.3 / NCP1117-3.3 as
candidates) to replace this Pico-sourced rail.

> **Consequence for bench bring-up:** because 3.3 V comes from the Pico, **there is no 3.3 V on the
> board until the Pico module is fitted and powered.** A board with A1 unpopulated will have 5 V and
> the isolated field rail but a dead 3.3 V rail — the MCP23017s and opto pull-ups will not come up.
> Fit and power the Pico first (it is hand-soldered after SMT assembly; see Section 6.7).

---

### 6.4 The Isolated Field-Wetting Supply — TMA-0505S (U37)

Dry-contact machine inputs (cams, grippers, switches) carry no voltage of their own — they are bare
contacts that simply open or close. To sense them, the board has to **provide its own "wetting"
voltage** that the contact switches. Per the Rev-B safety contract, that wetting supply must be
**galvanically isolated from logic ground**, so that a machine-side short or fault on the field
wiring cannot back-feed into the Pi/logic domain.

#### 6.4.1 The part

| Item | Value |
|---|---|
| Refdes | **U37** |
| Part | **TRACO Power TMA-0505S** — isolated 5 V → 5 V, 1 W, SIP DC/DC converter |
| Output | **5 V, 200 mA** |
| Isolation | ~1.5 kVDC class (VERIFY: exact isolation voltage taken from TRACO datasheet, not re-stated in the fab CSVs — the BOM-power draft specifies "≥1.5 kV isolation") |
| Footprint | `Converter_DCDC:Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT` |
| Source/notes | DigiKey 1951-1003-ND; **"Locked exact part"** — do not substitute without pinout + isolation review |

#### 6.4.2 Connections

From `block_supplies`:

| TMA-0505S pin | Net | Role |
|---|---|---|
| +Vin | `VCC_5V` | Primary (logic-side) input |
| −Vin | `GND` | Logic ground |
| +Vout | `FIELD_WET_V` | Isolated wetting rail (field side) |
| −Vout | `FIELD_GND` | Isolated field ground (field side) |

The converter's input side sits in the logic domain; its output side sits entirely in the field
domain. The 1.5 kV-class isolation barrier *inside* U37 is what keeps `FIELD_GND` from ever bonding
to `GND`.

#### 6.4.3 How the wetting rail is used

The wetting rail feeds **only** the field side of the dry-contact opto front-ends. For each
dry-contact input (most grippers and switches), `block_input`/`opto_input` wires:

```
FIELD_WET_V --- Rin (2.2k) --->|(PC817 LED)|--- field pin (J_FAST/J_SLOW_*) ---[machine contact]--- FIELD_GND
```

When the machine contact **closes**, it completes the loop from `FIELD_WET_V` through the 2.2 kΩ
series resistor (`Rin_*`) and the PC817 LED to `FIELD_GND`, lighting the opto LED. The opto's
logic-side phototransistor then pulls its logic net **LOW** (idle is HIGH via the 10 kΩ `VCC_3V3`
pull-up). All inputs are therefore **active-low at the logic side** — see Section 8, *Input Stage*,
and the firmware note (`INPUT_ACTIVE_LOW = True`).

#### 6.4.4 Why 200 mA / 1 W is ample

Only the optos of inputs that are *closed at that instant* draw wetting current, and each PC817 LED
draws on the order of ~1–2 mA through its 2.2 kΩ series resistor at this rail voltage. Even with many
contacts closed simultaneously the total is well under 100 mA, comfortably inside the TMA-0505S
200 mA / 1 W envelope. The single brick serves **all** dry-contact channels on the board (the 10
gripper inputs plus GP/OS/BS/PBZ/PBC and the manual/aux channels — see Section 8).

> **Two input front-end flavors (population-selectable per channel).** Each input channel can be
> populated for either:
> 1. **Dry-contact** — wetting from `FIELD_WET_V` as above (the confirmed default; the machine's cams
>    measured as dry, normally-closed contacts), or
> 2. **24 VAC sense** — a Rev-A-style rectifier interposer (1N4007 half-wave + bulk cap + bleed) into
>    the opto, for any channel that turns out to carry 24 VAC.
>
> The TMA-0505S serves the dry option; the interposer serves the AC option. Final per-channel
> population is set at cutover. See Section 8 for the per-channel detail.

---

### 6.5 The Relay Coil Rail — `RELAY_ENABLE_RAIL`

The motion-output relays are **Omron G5LE-14 with a 5 VDC coil** (refdes K1–K6; LCSC **C116963**).
Their coils are *not* wired straight to `VCC_5V`. Instead they hang off a **gated** rail called
`RELAY_ENABLE_RAIL`, which is the electrical enable for all motion. This is the heart of the
hardware safety design and is covered in full in Section 10, *Safety Rail*; here we cover only the
power/load aspect.

> ⚠️ **Critical part note:** the relay coil is **5 VDC**. Do **not** substitute a 9 V, 12 V, or 24 V
> coil variant — the rail and drive are designed for the ~79 mA, 5 V G5LE-14 coil.

#### 6.5.1 Coil supply topology

`RELAY_ENABLE_RAIL` is sourced from `VCC_5V` through a **P-channel pass FET (AO3401A, refdes Q14)**
that is only turned on when the entire series safety chain is satisfied (watchdog OK **and** ARM
**and** RP2040 OK **and** the external NC safety loops at `J_SAFETY`). When any condition fails, Q14
turns off and the rail collapses, de-energizing every relay coil.

Per `relay_output`, each motion channel wires its coil between the rail and a low-side NPN switch:

```
RELAY_ENABLE_RAIL --- relay coil (G5LE pin 1 -> pin 2) --- MMBT3904 collector --- (emitter) GND
        |                                                        ^
        +------------|<--- flyback diode (1N4148WS) ------------+   (cathode to rail, anode to coil low side)
```

- **High side of every coil = `RELAY_ENABLE_RAIL`** (G5LE coil pin 1). The rail is the single point
  that arms or disarms all coils at once.
- **Low side switched by an NPN** (`Qk_<name>`, MMBT3904) commanded from the MCP23017 OUT-A through a
  1 kΩ base resistor (`Rb_<name>`) with a 100 kΩ base pulldown — so an undriven/floating logic line
  defaults the coil **off**.
- **Flyback diode across each coil** (`Dfly_<name>`, **1N4148WS**, SOD-323): cathode to the rail,
  anode to the switched coil-low node, clamping the coil's inductive kick when it turns off. This is
  why the input does not need a large bulk capacitor — each coil's kick is caught locally.

#### 6.5.2 Coil-load budget for the 5 V rail

The worst case for the 5 V supply is **all populated relay coils energized at once**, plus logic,
plus the isolated-supply primary draw.

| Item | Qty (populated) | Per-unit | Subtotal |
|---|---|---|---|
| G5LE-14 5 V relay coils | **6** (K1–K6: S, T, SP, BE, M, M2) | ~79 mA | ~0.47 A |
| *(M1 ball-return coil — K7)* | **0 (DNP)** | ~79 mA | 0 A (not populated) |
| Logic (Pico VSYS + 3V3 loads + NE555 + optos) | — | — | small (tens of mA) |
| TMA-0505S primary | 1 | ≤ ~0.25 A in (1 W / ~4.7 V, worst case) | ≤ ~0.25 A |
| **Worst-case total** | | | **≈ 0.7–0.9 A** |

The BOM-power analysis lands the relay-coil portion at **~0.55 A** if every coil including a populated
M1 were energized, and concludes the **5 V rail should be ≥ 1.5 A minimum, with a ~3 A (HDR-15-5
class) supply preferred** for headroom. With M1 DNP (only 6 coils) the real coil load is ~0.47 A.
**Specify the external 5 V supply at ≥ 1.5 A; 3 A is the comfortable choice.**

> **M1 is DNP.** The seventh motion relay (M1, ball-return, refdes **K7**) and its driver/flyback are
> present as DNP copper only — they are **not** populated and draw nothing. M1 stays DNP until the
> ball-return command is confirmed to exist as a separate relay on this specific chassis. Do not add
> its coil load to the budget unless you populate K7.

#### 6.5.3 Contact-side suppression (no on-board power)

Each relay's **contacts** (COM/NO) switch the machine's *external* control circuit, not any board
rail. Every motion output has footprints for an **RC snubber** (`Rsnub_*` 100 Ω + `Csnub_*` 10 nF X2)
and an **MOV** across the contact, all **DNP by default**, to be populated after the at-machine
inductive load is characterized. These protect the contacts from arcing into the OEM coil; they carry
machine voltage, not board voltage.

---

### 6.6 Status-LED Drive — Powered from `VCC_5V` Logic

The four mask status indicators (1st-ball, 2nd-ball, strike, foul) are **new LEDs installed in the
existing mask housings and driven from the board's own 5 V logic rail** — the machine's old 15 VDC
mask-lamp supply is **abandoned** in Rev-B and is not used or sensed.

| Item | Value |
|---|---|
| Connector | **`J_LAMP_LED`** = refdes **J13**, Phoenix MCV 1,5/6-G-3,5 (MPN 1843648), 6-pos 3.5 mm |
| J13 pin 1 | `VCC_5V` (LED common anode supply) |
| J13 pin 2 | `GND` |
| J13 pins 3–6 | `LED_L_FIRST_RETURN`, `LED_L_SECOND_RETURN`, `LED_L_STRIKE_RETURN`, `LED_L_FOUL_RETURN` |
| Driver per channel | **2N7002** low-side N-FET (`Qled_*`, refdes Q8–Q11), 1 kΩ gate resistor (`Rgled_*`), 100 kΩ gate pulldown (`Rpdled_*`), series current limit `Rled_*` |
| `Rled_*` value | **330 Ω** in the scaffold (VERIFY: 330R is a TBD placeholder — final value must be locked after choosing LED type/current for brightness in a lit center) |

Drive topology (`lamp_led_output`): the LED anode side is fed `VCC_5V` (J13 pin 1), the LED cathode
returns through the series limit resistor to a 2N7002 low-side FET that sinks to `GND` when the
MCP23017 OUT-A bit drives the gate high. The 100 kΩ gate pulldown defaults the LED **off** on
floating/undriven logic.

These status LEDs are **not motion-critical and are not on the safety rail**, and there is **no
LOGIC-to-MACHINE isolation barrier** for them — they are entirely a logic-domain 5 V load. (See
Section 9, *Output Contract*, for the lamp output table.)

---

### 6.7 What the Board Deliberately Does NOT Power

This is the most safety-relevant part of the power architecture. Several things you might *expect* a
controller to drive are intentionally **off the board**:

| Not on the board | Where it actually comes from / why |
|---|---|
| **Machine 24 V coil power** | The machine's own **T2/T3/T4** transformer (measured ~24 VAC). The board only closes isolated dry relay **contacts** in series with the machine's existing coil circuits — it never sources the coil current. |
| **Motor line power (115 VAC)** | Never routed on the PCB. The S (sweep) and T (table) **machine contactors** continue to switch motor current and keep their OEM run/braking contact behavior. The board may command/interrupt their *control* coils through isolated contacts; it must never become the motor contactor or braking path. |
| **Old 15 VDC mask-lamp supply** | Abandoned. Status indication uses new board-driven LEDs on `VCC_5V` (Section 6.6). The 15 V supply is neither used nor sensed. |
| **PoE / Power-over-Ethernet** | Not in Rev-B v1. 5 V comes in over wire at J2. |
| **Pin lamps (1–10), KX relay** | Omitted in baseline. Camera scoring supplies pin state; the optional pin-lamp output bank (MCP23017 OUT-B, addr 0x23) is not populated. |

**Why machine coil power is never sourced on the board:** the entire Rev-B safety model depends on
the board being able to *fail open* — to remove its influence on the machine — on loss of logic,
watchdog, RP2040 health, arm permission, or the hardware interlock. If the board generated the 24 V
coil power, a board fault could *energize* machine motion. By keeping all machine motion/control
voltages external and only switching them through isolated dry contacts gated by the
`RELAY_ENABLE_RAIL`, the failure mode is always "contacts open, machine sees no command." This also
preserves the OEM contactors' built-in start/run/brake and interlock behavior, which the board must
not replace.

> **Welded-contact limitation (carried from the safety contract):** the rail de-energizes relay
> *coils*; it cannot open a contact that has welded closed. Relay contact rating, snubber/MOV
> population, and validation are therefore safety-relevant, and the **machine's upstream Stop / CIS /
> master-breaker chain remains the final physical stop**. See Section 10, *Safety Rail*.

---

### 6.8 Assembly Notes Relevant to Power (JLC split + hand-soldered parts)

Because the power architecture spans SMT, through-hole, and consigned parts, the fab package splits
assembly as follows (from the fab-package README and BOM CSVs):

| Power-related part | Refdes | Assembly path |
|---|---|---|
| SS14 input-protection diode | D17 | **JLC SMT** (LCSC C2480) |
| G5LE-14 5 V relays | K1–K6 | **JLC** places them (THT/wave) |
| PC817B optos (field front-ends) | U4–U35 | **JLC** places them |
| MCP23017 expanders | U1–U3 | **JLC SMT** (LCSC C47023) |
| NE555 watchdog timer | U36 | **JLC SMT** (NE555DR, LCSC C7593) |
| **Raspberry Pi Pico** (3.3 V source) | **A1** | **Hand-soldered after assembly** — program after fitting; use the castellated SC0915, *not* a Pico with pre-soldered headers |
| **TMA-0505S isolated supply** | **U37** | **Hand-soldered / consigned** — not in the JLC standard PCBA upload |
| J_PWR 5 V terminal | J2 | Phoenix screw terminal, hand-soldered/THT |
| J_LAMP_LED | J13 | Phoenix MCV header, hand-soldered/THT |

Practical bring-up implication: a JLC-assembled bare board arrives **without A1 and without U37**.
Until A1 (Pico) is fitted you have `VCC_5V` (via D17) but **no `VCC_3V3`** — the MCP23017s and opto
pull-ups stay dark. Until U37 is fitted you have no `FIELD_WET_V` — dry-contact inputs cannot be
sensed. Fit and verify rails in the order: 5 V in → confirm `VCC_5V` after D17 → fit A1, confirm
3.3 V at Pico pin 36 → fit U37, confirm isolated `FIELD_WET_V`/`FIELD_GND` and confirm `FIELD_GND` is
*not* continuous with `GND`. (See Section 21, *Bench Bring-Up*, for the full sequence.)

---

### 6.9 Quick Reference — Power Test Points & Expected Values

| Where to probe | Net | Expected |
|---|---|---|
| J2 pin 1 to pin 2 | `VCC_5V_RAW` to `GND` | +5 V from the external PSU |
| D17 cathode | `VCC_5V` to `GND` | ~4.6–4.8 V (input minus SS14 Vf) under load |
| Pico pin 36 | `VCC_3V3` to `GND` | +3.3 V (only with A1 fitted + powered) |
| TMA-0505S +Vout to −Vout | `FIELD_WET_V` to `FIELD_GND` | +5 V isolated (only with U37 fitted) |
| `FIELD_GND` to `GND` | — | **Open / no continuity** (isolation intact) |
| `RELAY_ENABLE_RAIL` (TP16) | rail | ≈ `VCC_5V` only when full safety chain satisfied; **0 V** otherwise |

The `RELAY_ENABLE_RAIL` reaches all relay coils and test point **TP16**; probing it is the fast way to
confirm whether the safety chain is permitting motion. Board envelope for reference: **250 × 225 mm,
4 copper layers, 1.6 mm stackup.**

---

**Cross-references:** Section 9 (*Output Contract / Relay Stage* — contact forms, M1 DNP, snubber/MOV);
Section 8 (*Input Stage* — dry-vs-AC front-ends, active-low sense, J_FAST/J_SLOW pinouts); Section 10
(*Safety Rail* — the `RELAY_ENABLE_RAIL` gate chain and fail-open behavior); Section 13 (*Layout /
Isolation* — logic/field/machine domain rooms and creepage); Section 21 (*Bench Bring-Up*).


## 7. Rev-B Logic: RP2040 Co-processor + MCP23017 Expanders + I2C

This section documents the digital "brains" on one Rev-B lane-controller board: the
RP2040 co-processor (a Raspberry Pi Pico module) and the three MCP23017 I/O
expanders, plus the I2C and UART buses that tie them to the Raspberry Pi. It is
written for an engineer with no prior context who must operate, repair, or extend
the board. Every pin number, part number, net name, and address below is taken from
the live design sources listed in §7.10; do not substitute values from older drafts.

> **Scope unit:** one PCB controls **one lane**. A lane *pair* uses two identical
> boards on one Raspberry Pi, each board on its own I2C bus and with its own RP2040.
> Everything in this section is **per board / per lane**; the pair is simply ×2. This
> matches the Rev-B baseline decision "one identical board per lane" (see
> **Section 5 — Rev-B PCB Overview & Electrical Domains**).

### 7.1 Why a Co-processor at All (Operating Theory)

The controller is deliberately split into two processors with different jobs:

| Processor | Job | Why it lives here |
|---|---|---|
| **Raspberry Pi** | Runs the cycle state machine (`lane_node/cycle_control_8270.py`), drives relays and lamps over I2C, reads the slow inputs, talks to the scoring camera and the rest of the building. | A full Linux box with the application logic, networking, and storage. Its scheduler is **non-deterministic** — a garbage-collection pause or a busy CPU can delay a Python loop by tens of milliseconds. |
| **RP2040 (Pico)** | Owns the 8 **fast** inputs (6 cams + 2 ball-detect beams), de-bounces them, **pushes** edge events to the Pi over UART, and drives the `RP2040_OK` rail-permission line. It also runs a UART-independent motion max-run backstop and its own hardware watchdog. | A bare-metal microcontroller running a single tight `for(;;)` loop with **bounded, predictable latency**. Cam timing and the safety contribution must not depend on Linux scheduling. |

The central design idea: **safety- and timing-critical behavior must be independent
of Pi scheduling.** The pinsetter's cams turn continuously while motors run; a missed
or late cam edge can mean a mistimed motor stop. By giving the cams to a dedicated
co-processor that does nothing else, the cam edge is observed and acted on in a fixed,
small time window regardless of what the Pi is doing. The Pi still gets every event
(as a UART message) so the application FSM stays fully informed, but the Pi is never
in the latency path for the fast safety functions.

The RP2040's four concrete responsibilities (from `firmware/rp2040/main.c`):

1. **Fast-input capture + event push.** Read the 8 fast GPIOs, time-debounce each,
   and emit a one-line JSON event to the Pi on every debounced edge. The FSM
   *consumes events*; it does not poll pins. This removes Pi-scheduling latency from
   cam timing.
2. **`RP2040_OK` rail permission.** Drive GP2 HIGH only while healthy. GP2 is one of
   the series conditions in the relay-enable rail (see **Section 10 — Safety Rail &
   Watchdog**). HIGH = permit motion; LOW = drop the rail. It is fail-safe LOW.
3. **UART-independent safety contributions.** (a) An on-chip **hardware watchdog**:
   if the main loop hangs, the chip resets, GP2 goes Hi-Z, and an external 100 kΩ
   pulldown holds the rail dead. (b) A **motion max-run backstop** ("cam timeout"):
   if the Pi marks a guarded motor RUNNING and never STOPs it within the limit, the
   firmware latches a fault and drops `RP2040_OK`.
4. **Heartbeat.** Periodically emit a status line so a dead or not-OK RP2040 is
   detectable by the Pi, which then drops ARM.

> **Safety boundary (critical):** the RP2040 is **never the only safety device.** The
> TB/SC hardware interlock loop, the Stop/CIS/master-breaker chain, the NE555
> watchdog (which watches the *Pi*), and the machine's regenerative motor braking are
> all in hardware, independent of this firmware. Telemetry must never block the safety
> loop: UART TX is a non-blocking ring buffer, and the `RP2040_OK` drive and watchdog
> kick run every loop pass regardless of UART state. A dead UART cannot cause unsafe
> motion. See **Section 10 — Safety Rail & Watchdog**.

### 7.2 RP2040 (Pico) — Device Summary

| Item | Value | Source |
|---|---|---|
| Reference designator | **A1** | BOM `wsl-phase8b-revB-bom-non-dnp.csv` |
| Part / module | Raspberry Pi **Pico** (RP2040 module) | netlist `block_rp2040()` |
| KiCad footprint | `Module:RaspberryPi_Pico_SMD` | netlist `FP_PICO` |
| LCSC part # | (none — placed as a through-hole/castellated **module**, supplied separately, not a JLC reel part) | part-lock CSV (A1 absent) |
| Firmware | `phase8b-rp2040 v0.1.0` (`firmware/rp2040/`, Pico C SDK) | `config.h` `FW_VERSION` |
| Pi link | UART (`uart0`) at 115200 8N1, plus the `RP2040_OK` GPIO | `config.h`, `main.c` |

The Pico is a placed component on the board (it appears in the non-DNP BOM as A1) but
it is a **module**, so it carries no LCSC reel part number and is sourced separately
from the JLC PCBA reel parts. Power is taken from the board's 5 V rail into the Pico's
**VSYS** pin; the Pico's on-board regulator then produces 3.3 V, which the board reuses
as the logic rail for the MCP23017s and the opto logic sides (see §7.6 and **Section 6
— Power Distribution**).

### 7.3 RP2040 Pin Map (AUTHORITATIVE)

This is the single authoritative pinout for the RP2040. It comes from
`scripts/generate_kicad_netlist_revB.py` `block_rp2040()` (the live board netlist
generator) and is mirrored in `firmware/rp2040/config.h`. The two agree.

> ⚠️ **The GPIO column in `docs/phase8_channel_allocation.md` §2 is STALE.** That older
> draft assigned the fast inputs to GP0–GP7. The as-built board uses **GP6–GP13** for
> the fast inputs, with GP0/GP1 reserved for the UART. Use the table below, not the
> channel-allocation draft, when flashing firmware or probing the board.

| Function | GPIO | Pico physical pin | Net name | Direction (at RP2040) | Notes |
|---|---|---|---|---|---|
| UART TX | GP0 | 1 | `PI_UART_RX` | OUT | Pico GP0/TX → Pi RX |
| UART RX | GP1 | 2 | `PI_UART_TX` | IN | Pi TX → Pico GP1/RX |
| **RP2040_OK** | **GP2** | 4 | `RP2040_OK` | OUT | Rail permission; HIGH=permit, LOW=drop. Fail-safe LOW. |
| Fast in: **SA** | GP6 | 9 | `FAST_SA` | IN (active-low) | sweep cam (270 run-through stop / 360 zero) |
| Fast in: **SB** | GP7 | 10 | `FAST_SB` | IN (active-low) | sweep cam (66 guard / 186 table-spot init) |
| Fast in: **SC** | GP8 | 11 | `FAST_SC` | IN (active-low) | sweep-under-table interlock window (86–243°) |
| Fast in: **TA1** | GP9 | 12 | `FAST_TA1` | IN (active-low) | table cam (355 zero stop / 185 delay reset) |
| Fast in: **TA2** | GP10 | 14 | `FAST_TA2` | IN (active-low) | table cam (260 run-through / pin-latch) |
| Fast in: **TB** | GP11 | 15 | `FAST_TB` | IN (active-low) | table-sweep interference interlock (105–255°) |
| Fast in: **DIELL-L** | GP12 | 16 | `FAST_DIELL_L` | IN (active-low) | ball detect, left beam |
| Fast in: **DIELL-R** | GP13 | 17 | `FAST_DIELL_R` | IN (active-low) | ball detect, right beam |
| GND (all) | — | 3, 8, 13, 18, 23, 28, 33, 38 | `GND` | — | the Pico's eight ground pins are all tied to board GND |
| VSYS | — | 39 | `VCC_5V` | power IN | board 5 V into the Pico |
| 3V3 OUT | — | 36 | `VCC_3V3` | power OUT | Pico regulator → board 3.3 V logic rail |

**Electrical sense of the fast inputs (from `opto_input()` in the generator):** every
fast input is **opto-isolated and ACTIVE-LOW** at the Pico. A machine contact CLOSED
(signal asserted) pulls the GPIO **LOW**; the idle state is HIGH via an on-board
**10 kΩ pull-up to 3.3 V** (`Rpu_*`). The firmware additionally enables the RP2040's
internal pull-up on each input ("belt and suspenders"). See **Section 5** /
**Section 8 — Field I/O Front-Ends** for the opto front-end and field wetting.

**`RP2040_OK` (GP2) electrical behavior (from `config.h` and the rail):** GP2 drives
an NPN transistor (`Q_AND_RP_OK`, MMBT3904, ref **Q16**) in the relay-enable-rail AND
chain. HIGH permits motion; LOW drops the rail. A **100 kΩ base pulldown** makes the
rail fail-safe-dead whenever GP2 is Hi-Z — i.e. while the Pico is unpowered, in reset,
or pre-init. The firmware drives GP2 LOW *before anything else* at boot and holds it
LOW for `BOOT_SETTLE_MS` after boot before permitting. Probe `RP2040_OK` at test point
**TP14**. See **Section 10** for the full AND chain.

### 7.4 RP2040 Firmware Timing & Protocol

All timing constants are from `firmware/rp2040/config.h`. They are part of the
safety/timing budget — do not change them without re-validating against the FSM
(`cycle_control_8270.py`) and the cutover runbook.

| Constant | Value | Meaning |
|---|---|---|
| `UART_BAUD` | 115200 (8N1) | Pi ↔ RP2040 link rate |
| `DEBOUNCE_CAM_US` | 2000 µs (2 ms) | cam debounce — mechanical microswitches on a ~12 RPM machine; 2 ms is ample without masking edges |
| `DEBOUNCE_DIELL_US` | 500 µs | ball beam-break debounce (faster than cams, still de-glitched) |
| `BALL_LOCKOUT_MS` | 300 ms | one thrown ball → one ball event (re-trigger lockout across both beams) |
| `HB_INTERVAL_MS` | 250 ms | heartbeat cadence to the Pi |
| `BOOT_SETTLE_MS` | 200 ms | `RP2040_OK` held LOW at least this long after boot before permitting |
| `WDT_TIMEOUT_MS` | 250 ms | RP2040 **hardware** watchdog: a hung loop → chip reset → rail drops |
| `MAX_MOTION_MS` | 8000 ms (8.0 s) | motion max-run backstop; matches `cycle_control_8270.MAX_MOTION_S = 8.0 s` |

**Event push (RP2040 → Pi), newline-delimited JSON on `uart0`:**

- Cam edge: `{"ev":"cam","id":"<SA|SB|SC|TA1|TA2|TB>","e":"<f|r>","t":<ms>}` where
  `e="f"` means asserted (falling, contact closed) and `e="r"` means released
  (rising). **Which edge is the angular "trip" is bench-confirmed per cam**; the
  Pi/daemon maps cam+state → FSM method. The firmware does not assume cam polarity.
- Ball: `{"ev":"ball","src":"<L|R>","t":<ms>}` (the two DIELL beams are coalesced
  into one ball event, subject to `BALL_LOCKOUT_MS`).
- `RP2040_OK` change: `{"ev":"rp_ok","v":<0|1>,"t":<ms>}`.
- Fault latched: `{"ev":"flt","code":"<code>","m":"<motor>","t":<ms>}` (e.g. code
  `motion_timeout`).
- Boot: `{"ev":"boot","fw":"<version>","wdt_reset":<0|1>,"rp_ok":0}`.
- Heartbeat: `{"ev":"hb","ok":<0|1>,"flt":"<code>","up":<ms>,"drp":<dropped lines>}`.

**Command line protocol (Pi → RP2040):** `RUN <motor>`, `STOP <motor|*>`, `CLEAR`,
`PING`. `RUN`/`STOP` feed the firmware's per-motor run tracker so the max-run backstop
knows what is energized. **Guarded** motors (subject to the 8 s timeout) are
**S, T, SP, M2, M1**; **BE** (continuous back-end) and **M** (master/power) are *not*
timed. `CLEAR` is issued by the Pi only from a known-safe (zero/ready) state; it stops
all motors and clears the latched fault. Unknown lines are ignored
(forward-compatible).

> **Deferred to firmware v1.1 (intentionally not in v0.1.0):** cam-stop **overrun**
> enforcement (a stop-cam firing while a motor is RUNNING and the Pi failing to STOP
> within a grace window → drop `RP2040_OK`) and the SC/TB collision **echo** gating
> `RP2040_OK`. Both need per-cam edge→angle polarity that is a deferred cutover field
> item; the v0.1.0 firmware deliberately does **not** bake in unconfirmed cam polarity.
> The hardware J_SAFETY interlock loop remains primary for SC/TB (see §7.7 and
> **Section 10**).

### 7.5 The Three MCP23017 Expanders — Operating Theory

The MCP23017 is a 16-bit general-purpose I/O expander controlled over **I2C**. Each
chip gives the board 16 individually-direction-controllable pins arranged as two
8-bit ports, **GPA0–7** and **GPB0–7**. The board uses three of them per lane to move
the **slow** I/O (relays, status-LED drivers, and the non-time-critical inputs) off
the Pi's limited GPIO header and onto a 2-wire bus.

> ⚠️ **Part criticality:** the device is the **I2C MCP23017** (`MCP23017-E/SO`,
> **LCSC C47023**), *not* the SPI-variant MCP23S17. The part-lock file flags this
> explicitly ("Critical: I2C MCP23017, not SPI MCP23S17"). They share a footprint and
> pinout but speak different buses — substituting the SPI part will not work with this
> board or the `controller_io.py` driver.

| Role | Ref | I2C address | Direction | What it carries |
|---|---|---|---|---|
| **MCP23017 IN-A** | U1 | **0x20** | all inputs | grippers GS1–GS10, GP, OS, BS, PBZ, PBC, Foul (high-use slow inputs) |
| **MCP23017 IN-B** | U2 | **0x21** | all inputs | 10th-frame, manual T/S/SWS/SWSR, AUX1–3 (manual/future slow inputs; 11 free pins of headroom) |
| **MCP23017 OUT-A** | U3 | **0x22** | all outputs | 7 relay drive bits (S, T, SP, BE, M, M2, M1) + 4 status-LED drive bits (L_FIRST, L_SECOND, L_STRIKE, L_FOUL) |

A fourth address, **0x23**, is reserved in software (`ADDR_OUT_B` in
`controller_io.py`) for an *optional* OUT-B expander driving a physical mask
pindicator (pin lamps 1–10 + neon). **It is not populated in the Rev-B baseline**
because the scoring camera supplies pin state; the board ships with three MCP23017s.

**Why I2C addresses 0x20 / 0x21 / 0x22 and not collisions:** the MCP23017 has three
hardware address-select pins, **A0 (pin 15), A1 (pin 16), A2 (pin 17)**, each strapped
HIGH (to 3.3 V) or LOW (to GND) on the board. The base address is `0x20`, and the
strapped bits set the low three bits of the 7-bit address. The board straps them as
follows (from `block_mcp()` — the generator passes the straps in `A0,A1,A2` order and
ties each pin HIGH→`VCC_3V3` or LOW→`GND`):

| Chip | A0 (pin 15) | A1 (pin 16) | A2 (pin 17) | Resulting address |
|---|---|---|---|---|
| IN-A (U1) | LOW (GND) | LOW (GND) | LOW (GND) | **0x20** |
| IN-B (U2) | HIGH (3V3) | LOW (GND) | LOW (GND) | **0x21** |
| OUT-A (U3) | LOW (GND) | HIGH (3V3) | LOW (GND) | **0x22** |

These three resolved addresses match `controller_io.py` (`ADDR_IN_A=0x20`,
`ADDR_IN_B=0x21`, `ADDR_OUT_A=0x22`) and `docs/phase8_channel_allocation.md` §4.
Because **each board has its own private I2C bus** (see §7.6), the two boards in a pair
can both use 0x20/0x21/0x22 identically — that is what makes the boards true clones.

**How the Pi uses each chip (from `controller_io.py`, the `_MCP23017` driver):**

- **Direction (IODIR):** MCP convention is `1 = input, 0 = output`. IN-A and IN-B are
  configured all-inputs (`IODIRA=IODIRB=0xFF`); OUT-A is all-outputs
  (`IODIRA=IODIRB=0x00`).
- **Pull-ups (GPPU):** the two input chips enable internal pull-ups on every pin
  (`GPPUA=GPPUB=0xFF`). Combined with the active-low opto front-ends, a closed machine
  contact reads as `0`.
- **Output latch (OLAT) caching:** the driver caches OLATA/OLATB so a per-bit
  set/clear is a single bus write, not a read-modify-write.
- **Active-low inputs:** optos pull the MCP pin LOW when the field contact closes, so
  "asserted/closed" = the pin reads `0` (`INPUT_ACTIVE_LOW = True`).

The MCP register addresses used (bank-0 / `IOCON.BANK=0` default mapping):
`IODIRA/B = 0x00/0x01`, `GPPUA/B = 0x0C/0x0D`, `GPIOA/B = 0x12/0x13`,
`OLATA/B = 0x14/0x15`.

### 7.6 I2C Bus & Per-Board Bus Architecture

| Item | Value | Source |
|---|---|---|
| Bus | One I2C bus **per board** (not shared across the pair) | channel-allocation §6 #2, `controller_io.py` |
| SDA net / SCL net | `I2C_SDA` / `I2C_SCL` | netlist globals |
| MCP SDA pin / SCL pin | pin **13** (SDA) / pin **12** (SCK) on each MCP23017 | `block_mcp()` |
| Pull-ups | `R_I2C_SDA` and `R_I2C_SCL`, **4.7 kΩ each to 3.3 V** (refs R1, R2) | `block_i2c_pullups()` |
| Bus voltage | **3.3 V** (Pi-safe — see below) | netlist (`VCC_3V3` on all pull-ups and chips) |
| Test points | SDA = **TP6**, SCL = **TP7** | DNP/test-point list |

**3.3 V operation is deliberate and is the Pi-safety property.** The MCP23017s, the
opto logic sides, and the I2C bus all run at **3.3 V**, sourced from the Pico's 3V3
regulator output (`VCC_3V3`). The Raspberry Pi's GPIO is **3.3 V only and not 5 V
tolerant**; running the bus at 3.3 V means the Pi's SDA/SCL and the `RP2040_OK`/INT
lines are never exposed to 5 V. (The 5 V rail on the board powers only the relay coils,
the Pico VSYS input, the NE555 watchdog, and the status-LED high side — never a Pi
GPIO.) This is the standing project rule: never wire 5 V to a Pi/RP2040 GPIO input.

**Per-board bus, two boards on one Pi.** Each board's MCP23017 cluster sits on that
board's own I2C bus. The Pi provides two independent buses for a pair: hardware
`i2c-1` on GPIO2/GPIO3 for the first board, and a second bus brought up in software
(`dtoverlay=i2c-gpio`) on a second GPIO pair for the second board. Because the buses
are separate, both boards reuse 0x20/0x21/0x22 without collision. This avoids a
zero-headroom shared 0x20–0x27 fill and keeps the two boards electrically identical.

**MCP power and reset (per chip, from `block_mcp()`):** `VDD = pin 9` and
`~RESET = pin 18` are both tied to `VCC_3V3` (reset is held de-asserted/HIGH);
`VSS = pin 10` to GND; each chip has a local **0.1 µF** decoupling cap
(`C_MCP_IN_A/IN_B/OUT_A`, refs C1/C2/C3) across 3V3→GND. A 10 µF bulk cap
(`C_3V3_BULK`, ref C12) sits on the 3V3 rail near the cluster.

### 7.7 MCP23017 Interrupt Lines

The MCP23017 can flag an input change on a dedicated interrupt pin so the Pi does not
have to poll the bus. The board wires the **INTA** output of each *input* expander to
a dedicated Pi GPIO; the *output* expander has no interrupt.

| Source | MCP pin | Net | Destination | Notes |
|---|---|---|---|---|
| IN-A (U1) INTA | pin **20** | `MCP_INT_A` | Pi GPIO (via J_PI) | change-interrupt for the high-use slow inputs |
| IN-B (U2) INTA | pin **20** | `MCP_INT_B` | Pi GPIO (via J_PI) | change-interrupt for manual/future inputs |
| OUT-A (U3) INTA | — | (not connected) | — | output chip; no interrupt needed |
| INTB (all chips) | pin **19** | (not connected) | — | only INTA is used; the two ports' interrupts are not mirror-split here |

The interrupt pins reach the Pi through the **J_PI** ribbon connector (see §7.8). The
INT lines are advisory for responsiveness; they are not part of the safety rail. The
safety-critical SC/TB interlock is handled in **hardware** through the J_SAFETY loop
(see **Section 10**), and the SC/TB cams are *also* read by the RP2040 as a fast-input
echo — the MCP path does not carry the interlock.

### 7.8 Pi ↔ Board Link Connector (J_PI)

All Pi-side logic signals — I2C, UART, watchdog kick, arm, both MCP interrupts, and
the two logic rails — land on one 2×10 IDC ribbon header. This is the only logic-domain
connector to the Pi.

| Item | Value | Source |
|---|---|---|
| Reference designator | **J1** | BOM |
| Connector | `Conn_02x10_Odd_Even`, footprint `Connector_IDC:IDC-Header_2x10_P2.54mm_Vertical` | netlist `block_connectors()` |
| Mating part (off-board) | 2×10 2.54 mm IDC ribbon / mate (confirm keying) | offboard-hardware CSV |

| J_PI pin | Net | Meaning |
|---|---|---|
| 1 | `VCC_5V` | board 5 V (to/from Pi-side 5 V distribution) |
| 2 | `GND` | logic ground |
| 3 | `I2C_SDA` | I2C data (this board's bus) |
| 4 | `I2C_SCL` | I2C clock (this board's bus) |
| 5 | `PI_UART_TX` | Pi TX → RP2040 RX (GP1) |
| 6 | `PI_UART_RX` | RP2040 TX (GP0) → Pi RX |
| 7 | `WDOG_KICK` | Pi → NE555 watchdog kick (see **Section 10**) |
| 8 | `ARM_PERMIT` | Pi arm GPIO → rail AND chain (power-down rule) |
| 9 | `MCP_INT_A` | IN-A change interrupt → Pi |
| 10 | `MCP_INT_B` | IN-B change interrupt → Pi |
| 11 | `VCC_3V3` | 3.3 V logic rail (Pico-sourced) |
| 12 | `GND` | logic ground |
| 13 | `RP2040_OK` | RP2040 rail-permission status (also a rail condition) |

> The UART net naming is from the board's perspective: `PI_UART_TX` is the Pi's
> transmit line, which arrives at the RP2040's **RX** (GP1); `PI_UART_RX` is the Pi's
> receive line, driven by the RP2040's **TX** (GP0). Cross-check §7.3 when wiring.

### 7.9 Device / Bus Summary Table

One board (one lane). Addresses repeat identically on the second board because it is on
a separate bus.

| Device | Ref | Bus / link | Address | Pins used | Role |
|---|---|---|---|---|---|
| RP2040 (Pico) | A1 | UART `uart0` @115200 + `RP2040_OK` GPIO | — | 8 fast in + GP0/GP1 + GP2 | fast inputs, cam-stop/timeout supervision, event push, rail permission |
| MCP23017 IN-A | U1 | I2C (this board) | 0x20 | 16 / 16 (full) | grippers + GP/OS/BS/PBZ/PBC/Foul |
| MCP23017 IN-B | U2 | I2C (this board) | 0x21 | 5 used / 16 | 10th + manual + AUX (11 spare) |
| MCP23017 OUT-A | U3 | I2C (this board) | 0x22 | 11 used / 16 | 7 relays + 4 status LEDs (5 spare) |
| (MCP23017 OUT-B) | — | I2C (this board) | 0x23 | — | **NOT POPULATED** in baseline (camera supplies pin state) |
| NE555 watchdog | U36 | `WDOG_KICK` GPIO | — | — | watches the **Pi** (see **Section 10**) |

**Bit maps (the software ↔ hardware contract).** `controller_io.py` carries the
`OUT_A_MAP` and `IN_A_MAP` that *must* match the netlist generator
(`OUTPUT_PINS` / `SLOW_INPUT_PINS`); the module's self-test re-derives them from the
generator and fails on drift. MCP pin numbering: GPA0–7 = pins 21–28 = (port 0,
bit 0–7); GPB0–7 = pins 1–8 = (port 1, bit 0–7).

**OUT-A (U3, 0x22) output bit map:**

| Signal | Port.Bit | MCP pin | Drives | On safety rail? |
|---|---|---|---|---|
| S (sweep) | A0 | 21 | relay K1 | yes |
| T (table) | A1 | 22 | relay K2 | yes |
| SP (spot solenoid) | A2 | 23 | relay K3 | yes |
| BE (back-end) | A3 | 24 | relay K4 | yes |
| M (master) | A4 | 25 | relay K5 | yes |
| M2 (sweep reverse) | A5 | 26 | relay K6 | yes |
| M1 (ball return) | A6 | 27 | relay K7 — **DNP** (not populated) | yes |
| L_FIRST (1st-ball lamp) | A7 | 28 | LED driver Q8 | no |
| L_SECOND (2nd-ball lamp) | B0 | 1 | LED driver Q9 | no |
| L_STRIKE (strike lamp) | B1 | 2 | LED driver Q10 | no |
| L_FOUL (foul lamp) | B2 | 3 | LED driver Q11 | no |

> Note the **M2 before M1** ordering (M2 = pin 26/A5, M1 = pin 27/A6) — this is the
> generator's order and was a previously-fixed software/board mismatch; keep it. The
> M1 channel (relay K7, driver Q7, and its passives) is **DNP / depopulated**: ball
> return is not bench-confirmed on this chassis and the FSM does not drive it. See the
> DNP-excluded list (J12, K7, Q7, R85–R87, D13/D14, etc.).

**IN-A (U1, 0x20) input bit map:**

| Signal | Port.Bit | MCP pin | Meaning |
|---|---|---|---|
| GS1 | A0 | 21 | gripper 1 |
| GS2 | A1 | 22 | gripper 2 |
| GS3 | A2 | 23 | gripper 3 |
| GS4 | A3 | 24 | gripper 4 |
| GS5 | A4 | 25 | gripper 5 |
| GS6 | A5 | 26 | gripper 6 |
| GS7 | A6 | 27 | gripper 7 |
| GS8 | A7 | 28 | gripper 8 |
| GS9 | B0 | 1 | gripper 9 |
| GS10 | B1 | 2 | gripper 10 |
| GP | B2 | 3 | gripper-protect |
| OS | B3 | 4 | off-spot |
| BS | B4 | 5 | bin / #9 |
| PBZ | B5 | 6 | first-ball-zero / manual intervention pushbutton |
| PBC | B6 | 7 | cycle pushbutton |
| Foul | B7 | 8 | foul (Radaray) |

IN-B (U2, 0x21) carries the manual/future inputs (10th-frame, manual T/S/SWS/SWSR,
AUX1–3) on GPA0–GPA7 (pins 21–28); the full IN-B field-side mapping is in
**Section 8 — Field I/O Front-Ends** and `docs/phase8_channel_allocation.md` §2.

### 7.10 Sources of Truth (verify here before changing anything)

The facts in this section are grounded in these live files (paths relative to the
`wsl-lane-nodes` repo root). The PCB netlist generator and the firmware are the
authority for pins; the part-lock/BOM CSVs are the authority for parts.

| File | What it is authoritative for |
|---|---|
| `scripts/generate_kicad_netlist_revB.py` | **board netlist** — every pin, net, address strap, and topology. The routed board is generated from it. |
| `firmware/rp2040/config.h` | RP2040 pin map, timing constants, protocol baud. Mirrors `block_rp2040()`. |
| `firmware/rp2040/main.c` | RP2040 firmware operating theory (debounce, event push, supervisor, watchdog, command protocol). |
| `lane_node/controller_io.py` | I2C addresses, MCP register/bit constants, `OUT_A_MAP` / `IN_A_MAP` (kept in lock-step with the generator by a self-test). |
| `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv` | resolved **LCSC part numbers** + criticality notes. |
| `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-bom-non-dnp.csv` | placed (non-DNP) reference designators + footprints. |
| `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-dnp-excluded.csv` | DNP/excluded refs (M1 channel) + test-point list. |
| `docs/phase8b_pcb_revB_spec.md` | the design contract (domains, safety rail, output contract). |
| `docs/phase8_channel_allocation.md` | channel counts + bank structure. **Its §2 GPIO column is STALE** for the RP2040 fast inputs — use `config.h`. |

**Confirmed key part numbers (from the part-lock CSV):**

| Function | Part | LCSC | Critical note |
|---|---|---|---|
| Output relay (×6 placed: K1–K6) | Omron **G5LE-14, 5VDC** coil | **C116963** | "Critical: 5VDC coil. Do not substitute 9V/12V/24V." |
| I/O expander (×3: U1–U3) | **MCP23017-E/SO** | **C47023** | "Critical: I2C MCP23017, not SPI MCP23S17." |
| Optocoupler (×32: U4–U35) | **PC817B** | **C5692981** | DIP-4; CTR bin must work with the Rev-B field resistors. |
| Watchdog timer (U36) | **NE555DR** (bipolar) | **C7593** | Bipolar 555; do not swap to CMOS/TLC555 (changes timing). |
| Relay driver (S/T/SP/BE/M/M2 + AND-chain) | MMBT3904 NPN | C909754 | SOT-23 |
| Status-LED low-side driver (×4) | 2N7002 N-MOSFET | C916396 | SOT-23 |
| Watchdog kick/OK FETs | AO3400A N-MOSFET | C20917 | SOT-23 |
| Rail pass FET | AO3401A P-MOSFET | C347476 | SOT-23 |

### 7.11 Cross-References

- **Section 8 — Field I/O Front-Ends:** PC817 opto front-end, active-low sense, field
  wetting (`FIELD_WET_V` from the TMA-0505S isolated DC/DC), and the full slow-input
  field map including IN-B.
- **Section 5 — Rev-B PCB Overview & Electrical Domains:** the three electrical domains
  (logic / machine-sense / machine-output), board envelope (250×225 mm, 4 copper
  layers), and the one-board-per-lane decision.
- **Section 10 — Safety Rail & Watchdog:** the relay-enable rail AND chain (Watchdog OK ·
  Arm OK · `RP2040_OK` · Cam-stop OK · TB/SC interlock · Stop/CIS/master chain), the
  NE555 watchdog topology, and why none of it is bypassable by the Pi in software.
- **Section 6 — Power Distribution:** 5 V / 3.3 V rails, reverse-polarity/transient
  protection (SS14, D17), and the isolated field-wetting supply.
- **Output relays and the J_MOTION connectors** are detailed in the output/relay
  section; the bit map here defines which OUT-A bit drives which relay.

---

**Verification note:** all pin numbers, GPIO assignments, I2C addresses, net names,
LCSC part numbers, and timing constants above were taken directly from the live source
files in §7.10. The known-correct anchors (fast inputs GP6–GP13, `RP2040_OK`=GP2,
UART GP0/GP1, G5LE-14 5VDC = C116963, MCP23017 = C47023, PC817B = C5692981,
NE555DR = C7593) were confirmed against `config.h`, `block_rp2040()`, and the
part-lock CSV. No source disagreed with the anchors. The only stale source found is
`docs/phase8_channel_allocation.md` §2 (GPIO column), which is flagged inline.


## 8. Rev-B Field Inputs: PC817 Opto-isolators

Every machine signal the Rev-B controller board reads — cam microswitches, ball
detectors, gripper switches, pushbuttons, foul, and the manual/spare lines —
enters the board through an opto-isolated input channel built around a **PC817B**
optocoupler. This section explains how one channel works electrically, why the
field side is galvanically isolated from logic ground, the two population
flavors (dry-contact wetting vs 24 VAC sense) the design supports per channel,
and the full channel count and parts.

This is the input half of the board. The output half (relay contacts) is covered
in **Section 9 — Machine Outputs: G5LE Relays** (VERIFY: exact section number),
the fast-cam timing budget in the RP2040 firmware in **Section 7 — RP2040
Co-processor** (VERIFY: exact section number), and the safety rail that gates the
relays in **Section 10 — Safety Rail & Watchdog** (VERIFY: exact section number).
Where a section number is uncertain, cross-reference by title.

> **Source of truth for this section.** Pin numbers, net names, part numbers, and
> values are taken from the live board netlist generator
> `scripts/generate_kicad_netlist_revB.py` (function `opto_input()`, lists
> `FAST_INPUTS` and `SLOW_INPUT_PINS`), the assembled-board part lock
> `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv`,
> the firmware pin map `firmware/rp2040/config.h`, the software bit map
> `lane_node/controller_io.py`, and the design contract
> `docs/phase8b_pcb_revB_spec.md`. The stale GPIO column in
> `docs/phase8_channel_allocation.md` is **not** used here.

---

### 8.1 What an input channel is for

The pinsetter's native signals are almost all **switch closures**: a cam lever
rides a lobe and opens/closes a microswitch; a gripper finger pinches a standing
pin and makes/breaks a contact to the machine chassis; a pushbutton shorts a
control line. The board's job is to read the open/closed state of each of these
contacts **without ever connecting a machine wire directly to a Pico, RP2040, or
MCP23017 pin** (design contract §5.3: "No machine input may connect directly to
Pi, RP2040, or MCP23017 pins").

The PC817B optocoupler is the device that bridges that gap. Its internal LED and
phototransistor are coupled only by light across an insulating gap, so the field
wiring (which may carry machine voltages, ground faults, or noise) and the
3.3 V logic are electrically separate. The contact state crosses the barrier as
light, not as a shared conductor.

At-machine measurements (`docs/phase8b_at_machine_fieldsheet.md`, item A4)
confirmed that on lanes 21/22 the cams are **dry contacts, normally-closed at
rest**, and grippers are **chassis-referenced** (a gripped pin closes the switch
to chassis ground). This is why the dry-contact wetting front-end (below) is the
confirmed default population for those channels.

---

### 8.2 How one channel works (dry-contact wetting, the default)

The default population builds this series loop for each channel. All names below
are the literal nets and references from `opto_input()` in the generator:

```
FIELD_WET_V ──► Rin (2k2) ──► PC817B LED anode (pin 1)
                              PC817B LED cathode (pin 2) ──► FIELD_<name>  ──► [J connector pin]
                                                                                     │
                                                          (machine contact closes this pin to FIELD_GND)
                                                                                     │
                                                                                FIELD_GND
```

and on the isolated logic side:

```
VCC_3V3 ──► Rpu (10k) ──► logic node (Pico GPIO or MCP23017 pin)
                            ▲
PC817B collector (pin 4) ──┘   (phototransistor pulls the logic node toward GND when lit)
PC817B emitter (pin 3) ──► GND  (logic ground)
```

**Step by step:**

1. **Wetting source.** `FIELD_WET_V` (the board-generated, isolated field-wetting
   rail — see §8.6) supplies the small current that lights the opto LED. It is
   the only "power" present on the field side, and it is referenced to
   `FIELD_GND`, not logic `GND`.

2. **LED current limit.** `Rin` = **2.2 kΩ** (BOM value "2k2", 0805, 1%; the 32
   off in the part lock are `R3, R5, R7 … R65`) sets the LED drive current so the
   PC817B turns on cleanly while keeping field-side current low. With a ~5 V
   wetting supply minus the LED forward drop, this is on the order of a couple of
   milliamps — enough to saturate the PC817B over its CTR bin given the matched
   10 k logic pull-up.

3. **The field contact does the switching.** The LED's cathode (pin 2) is wired
   to the per-channel field net `FIELD_<name>`, which lands on the channel's
   connector pin. The machine's switch is wired between that pin and `FIELD_GND`
   at the harness. **When the machine contact closes**, it completes the loop
   `FIELD_WET_V → Rin → LED → contact → FIELD_GND`, current flows, and **the LED
   lights**.

4. **Light crosses the barrier.** The lit LED turns on the PC817B
   phototransistor.

5. **Logic side pulls LOW.** The phototransistor's collector (pin 4) is tied to
   the logic node, which is held HIGH by `Rpu` = **10 kΩ** to `VCC_3V3`; its
   emitter (pin 3) goes to logic `GND`. When the transistor conducts, it pulls
   the logic node down toward `GND`. So **contact closed → LED on → logic node
   LOW**.

6. **Idle state.** With the machine contact open, no LED current flows, the
   phototransistor is off, and `Rpu` holds the logic node **HIGH** at 3.3 V.

This gives the channel its polarity: **asserted/closed = LOW (active-low)**. The
firmware and software both encode this — see §8.5.

#### 8.2.1 PC817B pin map (per channel)

The PC817B is a 4-pin DIP (footprint `Package_DIP:DIP-4_W7.62mm` in the
generator). Pin roles as wired in `opto_input()`:

| PC817B pin | Function | Side | Wired to (net) |
|---|---|---|---|
| 1 | LED anode (input +) | Field | `FIELD_LED_<name>` (output of `Rin`, which is fed from `FIELD_WET_V`) |
| 2 | LED cathode (input −) | Field | `FIELD_<name>` → channel connector pin (machine contact pulls it to `FIELD_GND`) |
| 3 | Phototransistor emitter | Logic | `GND` (logic ground) |
| 4 | Phototransistor collector (output) | Logic | logic node = Pico GPIO **or** MCP23017 pin; held HIGH by `Rpu` (10 k) to `VCC_3V3` |

> The barrier runs **between pins 1/2 (field) and pins 3/4 (logic)**. Nothing
> bridges those two pin-pairs on the board except the optocoupler itself.

#### 8.2.2 Per-channel passive parts

| Ref pattern | Value | Purpose | Part (part lock) |
|---|---|---|---|
| `Rin_<name>` | 2.2 kΩ ("2k2"), 0805, 1% | Field-side LED current limit | LCSC C17520, `0805W8F2201T5E`, UNI-ROYAL — 32 off (`R3,R5,…,R65`) |
| `Rpu_<name>` | 10 kΩ, 0805, 1% | Logic-side pull-up to `VCC_3V3` (defines idle-HIGH / active-LOW) | LCSC C17414, `0805W8F1002T5E`, UNI-ROYAL — 37 off total on board (32 of them are the opto pull-ups; the rest serve the watchdog/safety AND chain) |
| `OPTO_<name>` | PC817B | The opto-isolator | LCSC C5692981, `PC817B`, UMW, DIP-4 — 32 off (`U4…U35`) |

> **CTR note (from the part-lock file):** "CTR bin must be accepted with Rev-B
> field resistors." The 2k2 LED resistor + 10k logic pull-up were chosen to work
> across the PC817**B** current-transfer-ratio bin; do not substitute a
> lower-CTR opto or change these resistor values without re-checking that a
> closed contact still pulls the logic node solidly below the input's logic-LOW
> threshold.

---

### 8.3 The 24 VAC-sense population option

Design contract §2.2 / §5.1 require that **every** input channel be
"population-selectable" between two front-ends:

1. **Dry-contact wetting** — the default described in §8.2 (board supplies the
   wetting voltage; the machine contact closes the loop to `FIELD_GND`). This is
   the confirmed default for the cams and grippers on the 21/22 chassis (field
   sheet A4).

2. **24 VAC sense** — for any channel where the machine signal is a *live
   voltage* (24 VAC present when active) rather than a dry switch. Per
   `docs/phase8b_pcb_revB_BOM_power.md` §3.3, the AC front-end is the Rev-A
   "interposer" style: **half-wave rectifier (1N4007) + reservoir/filter cap
   (10 µF, 63 V) + bleed/discharge resistor (100 k)** ahead of the opto LED, so a
   present AC voltage is rectified into steady LED drive and a removed voltage
   discharges promptly. Contract §5.3: "24 VAC channels need rectification,
   current limiting, bleed/discharge, and opto input protection."

> **Important — what the as-built netlist actually instantiates.** The current
> `opto_input()` generator builds **only the dry-contact wetting path** (the
> `FIELD_WET_V → Rin → LED → FIELD_<name>` loop) for all 32 channels. The 24 VAC
> rectifier/cap/bleed parts are a documented **per-channel manual-population
> option**, not separate placed footprints emitted for every channel in the
> present netlist. (VERIFY: whether dedicated per-channel AC-interposer
> footprints exist on the routed board or whether the AC option is wired on a
> small external/daughter interposer at the affected channel — the generator's
> `opto_input()` does not place 1N4007/10µF/100k per channel.)

**Choosing the population per channel:** the field sheet (`A4`, `C2`, `C3`)
captures dry-vs-AC per signal; the design defaults are: cams (SA/SB/SC/TA1/TA2/TB)
= **dry**, grippers/GP/OS/BS = **dry** (chassis-referenced). Channels that prove
to be live AC (historically foul and 2nd-ball lamps on some chassis) take the AC
front-end. Per BOM_power §6, the dry-vs-AC default for any not-yet-confirmed
channel is a **fab/population decision finalized at cutover from the field
measurements**, not a board-topology change.

---

### 8.4 Why the field side is isolated from logic ground

The field side and logic side **do not share a ground**. There are two distinct
ground nets:

| Net | Domain | Where it exists |
|---|---|---|
| `GND` | Logic | Pi / RP2040 / MCP23017 / opto **logic** side (pins 3/4) |
| `FIELD_GND` | Machine sense | Opto **field** side (pins 1/2) return + the input connectors' common pins |

This separation is mandated by the contract (§2.1: "Logic ground is allowed to
exist only on the Pi/control side of optocouplers …"; §2.2 / §8.3 default:
"isolated field wetting"). The route/audit notes for the board record that on the
actual layout `GND` and `FIELD_GND` **share zero nodes** — they never touch, even
through test pads — which is the physical proof the isolation barrier is intact.

**Why it matters (operating theory):**

- **Ground-fault containment.** Machine wiring runs through a noisy, sometimes
  wet, high-energy cabinet. If a field wire shorts to chassis or to a machine
  voltage, the energy is confined to the field domain (`FIELD_WET_V` /
  `FIELD_GND`) and the opto LED — it cannot backfeed into the 3.3 V logic, the
  Pi, or the RP2040.

- **No sneak paths through the controllers.** Because the field nets only reach
  opto LEDs, a closed contact can only ever *light an LED*. It can never source
  or sink current into a microcontroller pin.

- **Common-mode rejection.** The two domains can sit at different reference
  potentials without forcing current through logic; only light crosses, so
  ground-potential differences between the machine and the control electronics
  don't corrupt readings or damage parts.

The field-wetting supply that powers this isolated domain is itself produced by
an **isolated DC/DC converter** (§8.6) precisely so the wetting rail is
galvanically separated from logic — option 1 of contract §8.3.

---

### 8.5 Active-low polarity (asserted = LOW)

Every input channel is **active-low at the logic pin**: the machine contact
closing pulls the logic node LOW, idle is HIGH (held by the 10 k pull-up to
`VCC_3V3`). Both the firmware and the FSM software encode this so a service tech
sees consistent behavior end-to-end.

| Layer | File | How active-low is expressed |
|---|---|---|
| Hardware | `scripts/generate_kicad_netlist_revB.py` (`opto_input()`) | LED in series to `FIELD_GND`; collector pulls logic node down; `Rpu` (10 k) holds it HIGH at idle |
| Firmware (fast inputs) | `firmware/rp2040/config.h` | Header note: "every fast input is opto-isolated and ACTIVE-LOW at the Pico — machine contact CLOSED (signal asserted) pulls the GPIO LOW; idle is HIGH (on-board 10k pull-up to 3V3)" |
| Software (slow inputs) | `lane_node/controller_io.py` | `INPUT_ACTIVE_LOW = True`; `_read_in()` returns asserted when `raw == 0`; "Optos are active-low at the MCP pin (switch closed → opto pulls pin LOW)" |

> **Bench bring-up consequence:** with the machine harness unplugged (all field
> contacts open), every logic node should read **HIGH** and every input should
> read **de-asserted**. Forcing a single channel's connector pin to `FIELD_GND`
> (with `FIELD_WET_V` present) should drive just that logic node LOW and assert
> just that one input. Use this as the per-channel smoke test.

---

### 8.6 The isolated field-wetting supply (`FIELD_WET_V` / `FIELD_GND`)

The wetting voltage that all dry-contact channels share is generated **on the
board** by an isolated DC/DC converter so it stays separate from logic ground:

| Item | Value (source) |
|---|---|
| Converter (generator `block_supplies()`, ref `ISO_WET`) | **TMA-0505S** isolated DC/DC, footprint `Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT` |
| Input | `+Vin` = `VCC_5V`, `-Vin` = `GND` (logic 5 V rail) |
| Output | `+Vout` = `FIELD_WET_V` (the wetting rail), `-Vout` = `FIELD_GND` (isolated return) |
| Loading | One converter feeds the field side of all dry-contact channels; total wetting current is small (only the channels whose contacts are closed draw their few-mA LED current at any instant) |

> **Part-number note / discrepancy to flag:** the as-built netlist generator and
> the part-lock-class BOM use the **Traco TMA-0505S** (5 V → 5 V, 1 W isolated).
> The earlier planning doc `docs/phase8b_pcb_revB_BOM_power.md` §3.2 *recommended*
> a "B0505S-1W" (or B0512S-1W for 12 V wetting) as an example; the board was
> built with the TMA-0505S. Trust the generator/board for the as-built part.
> (VERIFY: the exact `FIELD_WET_V` output voltage if a 12 V wetting option was
> ever populated — the as-built `ISO_WET` is the 5 V→5 V TMA-0505S, i.e. ~5 V
> wetting.)

The wetting supply is **not** on the safety rail and is **not** the machine's
24 V or 15 V supplies — those machine voltages stay external and are only ever
*switched* by the relay contacts (Section 9) or *sensed* through the AC-option
front-end; the board never sources machine coil or lamp power
(`docs/phase8b_pcb_revB_spec.md` §8.2).

---

### 8.7 Channel inventory and counts

There are **32 opto-isolated input channels = 8 fast + 24 slow**, i.e. **32
PC817B** optos total (`U4…U35` in the part lock; "PC817B optocoupler, DIP-4 …
Quantity 32"). Fast channels go to the RP2040; slow channels go to the two input
MCP23017 banks.

#### 8.7.1 Fast inputs — 8 channels → RP2040 (Pico)

Source: generator `FAST_INPUTS` (name, Pico **module** pin) + `config.h` (GPIO).
These carry the cam and ball-detect edges that the RP2040 times directly; they
must stay edge-capable with no slow RC that could mask a cam stop
(`docs/phase8b_pcb_revB_spec.md` §5.1).

| Channel | Function | Pico module pin | RP2040 GPIO | Field net | Connector |
|---|---|---|---|---|---|
| SA | sweep cam (270 run-through stop / 360 zero) | 9 | GP6 | `FIELD_FAST_SA` | `J_FAST_IN` |
| SB | sweep cam (66 guard / 186 table-spot init) | 10 | GP7 | `FIELD_FAST_SB` | `J_FAST_IN` |
| SC | sweep-under-table interlock window (86–243) | 11 | GP8 | `FIELD_FAST_SC` | `J_FAST_IN` |
| TA1 | table cam (355 zero stop / 185 delay reset) | 12 | GP9 | `FIELD_FAST_TA1` | `J_FAST_IN` |
| TA2 | table cam (260 run-through / pin-latch) | 14 | GP10 | `FIELD_FAST_TA2` | `J_FAST_IN` |
| TB | table-sweep interference interlock (105–255) | 15 | GP11 | `FIELD_FAST_TB` | `J_FAST_IN` |
| DIELL-L | ball detect, left beam (cushion SS trigger) | 16 | GP12 | `FIELD_FAST_DIELL_L` | `J_FAST_IN` |
| DIELL-R | ball detect, right beam | 17 | GP13 | `FIELD_FAST_DIELL_R` | `J_FAST_IN` |

> **Known-correct anchor:** fast inputs = **GP6..GP13**, `RP2040_OK` = GP2, UART =
> GP0/GP1. The `docs/phase8_channel_allocation.md` GPIO column (which claimed
> GP0–GP7) is **stale and wrong** — both `config.h` and the generator agree on
> GP6–GP13, and `config.h` says so explicitly.

The 8 fast channels land on the 10-pin `J_FAST_IN` connector; the generator wires
the 8 signals to pins 1–8 and ties `FIELD_GND` to pins 9 and 10.

#### 8.7.2 Slow inputs — 24 channels → MCP23017 banks

Source: generator `SLOW_INPUT_PINS` (name → (MCP bank, MCP pin)). Sixteen
channels are on bank **MCP_IN_A** (I²C `0x20`), eight on bank **MCP_IN_B** (I²C
`0x21`). The MCP23017 pin numbering used by the symbol: **GPA0–7 = pins 21–28,
GPB0–7 = pins 1–8**.

The MCP23017s are **I²C** parts (LCSC C47023, `MCP23017-E/SO`; part-lock note:
"Critical: I2C MCP23017, not SPI MCP23S17") and run at **3.3 V** so they are
Pi-safe on the shared I²C bus.

**Bank MCP_IN_A (0x20) — grippers + high-use slow inputs (16 ch):**

| Channel | Function | MCP pin | Port,bit (`controller_io.py` `IN_A_MAP`) | Connector |
|---|---|---|---|---|
| GS1 | gripper 1 | 21 | (0,0) | `J_SLOW_IN_A` |
| GS2 | gripper 2 | 22 | (0,1) | `J_SLOW_IN_A` |
| GS3 | gripper 3 | 23 | (0,2) | `J_SLOW_IN_A` |
| GS4 | gripper 4 | 24 | (0,3) | `J_SLOW_IN_A` |
| GS5 | gripper 5 | 25 | (0,4) | `J_SLOW_IN_A` |
| GS6 | gripper 6 | 26 | (0,5) | `J_SLOW_IN_A` |
| GS7 | gripper 7 | 27 | (0,6) | `J_SLOW_IN_A` |
| GS8 | gripper 8 | 28 | (0,7) | `J_SLOW_IN_A` |
| GS9 | gripper 9 | 1 | (1,0) | `J_SLOW_IN_A` |
| GS10 | gripper 10 | 2 | (1,1) | `J_SLOW_IN_A` |
| GP | gripper protect | 3 | (1,2) | `J_SLOW_IN_A` |
| OS | off-spot | 4 | (1,3) | `J_SLOW_IN_A` |
| BS | bin / #9 | 5 | (1,4) | `J_SLOW_IN_A` |
| PBZ | first-ball / zero / manual intervention | 6 | (1,5) | `J_SLOW_IN_B` |
| PBC | cycle pushbutton | 7 | (1,6) | `J_SLOW_IN_B` |
| FOUL | foul | 8 | (1,7) | `J_SLOW_IN_B` |

> **Anchor confirmation:** the BS/OS ordering and the strike/foul output ordering
> were explicitly fixed so `controller_io.py` matches the netlist (OS = pin 4 =
> (1,3); BS = pin 5 = (1,4)). `controller_io.py` ships a `__main__` regression
> test that re-derives these maps from the generator and **fails on drift** — so
> the table above is enforced in software against the board.

**Bank MCP_IN_B (0x21) — 10th-frame / manual / spare (8 ch):**

| Channel | Function | MCP pin | Connector |
|---|---|---|---|
| TENTH | 10th-frame | 21 | `J_SLOW_IN_B` |
| MAN_T | manual table | 22 | `J_SLOW_IN_B` |
| MAN_S | manual sweep | 23 | `J_SLOW_IN_B` |
| MAN_SWS | manual sweep-switch | 24 | `J_SLOW_IN_B` |
| MAN_SWSR | manual sweep-reverse | 25 | `J_SLOW_IN_B` |
| AUX1 | spare / future machine-specific | 26 | `J_SLOW_IN_B` |
| AUX2 | spare / future machine-specific | 27 | `J_SLOW_IN_B` |
| AUX3 | spare / future machine-specific | 28 | `J_SLOW_IN_B` |

> The `J_SLOW_IN_A` connector carries (in generator order) GS1–GS10, GP, OS, BS +
> a `FIELD_GND` pin; `J_SLOW_IN_B` carries PBZ, PBC, FOUL, TENTH, MAN_T, MAN_S,
> MAN_SWS, MAN_SWSR, AUX1, AUX2, AUX3 + a `FIELD_GND` pin. Each MCP23017 input bit
> still goes through its own PC817B; the connector grouping is just how the field
> wires arrive. (Per contract §7, connector cavity → C1/C2A mapping is resolved
> by the adapter harness at cutover, not baked into the board.)

#### 8.7.3 Count summary

| Group | Channels | Routed to | Optos |
|---|---|---|---|
| Fast inputs | 8 (SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R) | RP2040 GP6–GP13 | 8 × PC817B |
| Slow inputs — bank A (0x20) | 16 (GS1–GS10, GP, OS, BS, PBZ, PBC, FOUL) | MCP_IN_A | 16 × PC817B |
| Slow inputs — bank B (0x21) | 8 (TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1–AUX3) | MCP_IN_B | 8 × PC817B |
| **Total** | **32** | — | **32 × PC817B (`U4…U35`)** |

---

### 8.8 Service notes & failure modes

- **A channel always reads asserted (LOW), harness unplugged.** Suspect the field
  net shorted to `FIELD_GND`, or the PC817B LED/transistor failed short. With the
  harness off, every channel must idle HIGH (§8.5).

- **A channel never asserts even with the contact closed.** Check `FIELD_WET_V`
  is present at `Rin` (i.e. the `ISO_WET` TMA-0505S is alive), the 2k2 `Rin` is
  not open, the connector pin lands on the right `FIELD_<name>` net, and the
  PC817B is not an out-of-bin/weak-CTR substitute (see §8.2.2 CTR note).

- **All 16 bank-A or all 8 bank-B channels dead.** That points at the MCP23017
  (I²C address `0x20` / `0x21`) or the I²C bus, not the optos — confirm the
  expander enumerates on the bus first.

- **All 8 fast channels dead but slow channels fine.** Look at the RP2040/Pico
  and its 3.3 V rail, not the optos.

- **Never bridge field and logic grounds to "fix" a reading.** `GND` and
  `FIELD_GND` are deliberately isolated (§8.4); tying them defeats the safety
  isolation and can backfeed machine energy into the logic.

- **Do not "improve" a sluggish cam edge with an RC filter on a fast channel.**
  SA/SB/SC/TA1/TA2/TB must stay edge-capable for cam-stop timing
  (`docs/phase8b_pcb_revB_spec.md` §5.1); de-glitching is done in firmware
  (`config.h` `DEBOUNCE_CAM_US` / `DEBOUNCE_DIELL_US`), not with slow front-end
  RC.


## 9. Rev-B Machine Outputs: G5LE Relays

This section documents the **machine-output stage** of the Rev-B lane-controller board: the chain that turns a command bit from the controller into a closed dry contact in the bowling machine's own control wiring. Read this if you are bringing up a board on the bench, tracing why a motor won't run (or won't stop), choosing a replacement relay, or extending the board to drive an output that is currently depopulated.

If you have not yet read **Section 10, Safety Rail Contract** (the `RELAY_ENABLE_RAIL` permission chain) and **Section 7, Controller Interface** (the MCP23017 / RP2040 / NE555 device set), read those first — the output stage cannot energize without the rail, and every output bit originates on the `MCP_OUT_A` expander described in Section 7.

> **Source grounding.** Every pin number, part number, net name, and value in this section is taken from the live board netlist generator `scripts/generate_kicad_netlist_revB.py`, the design contract `docs/phase8b_pcb_revB_spec.md`, the as-fabricated assembly BOM `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`, the bench reverse-engineering log `docs/phase8_bench_session1_FINDINGS.md`, and the software-side bit map `lane_node/controller_io.py`. Where a fact is not pinned down by these sources it is flagged `(VERIFY: …)`.

---

### 9.1 What the output stage does (and does not do)

The single most important fact about this board's output stage:

> **The board never switches motor current and never sources machine coil power. Each output is an electrically isolated, dry, normally-open relay contact (COM/NO) wired *in series with an existing machine control circuit*. The machine's own contactors still switch the 115 VAC motors and still provide their OEM run/braking behavior.**

This is the locked Rev-B output topology (`phase8b_pcb_revB_spec.md` §1, §3.1, §13). The chain is:

```
MCP_OUT_A bit  ->  MMBT3904 low-side driver  ->  G5LE relay coil (5 VDC,
fed from RELAY_ENABLE_RAIL)  ->  isolated dry NO contact (COM/NO)
-> into the existing machine control / contactor-coil circuit
```

Concretely, the machine's pinsetter relays and contactors were measured on the spare cabinet (an AMF 82-70 SS chassis with an Omega-Tek retrofit, lanes 21/22) and run on the machine's own **24 VAC** control rail, with one **12 VDC** Potter & Brumfield control relay also present (`phase8_bench_session1_FINDINGS.md`, coil-resistance table). The Rev-B board does **not** generate those voltages. It interposes a dry contact into each coil circuit so the controller can open or close that circuit on command, exactly the way the original Omega-Tek/AEDIKO control approach did. The machine's S and T contactors continue to switch the high-current sweep and table motors and continue to provide their de-energized regenerative-braking contact behavior; the board may command or interrupt their *control* circuit but must never become the motor contactor or the braking path (`phase8b_pcb_revB_spec.md` §3.1).

Why this matters for service:

- A welded relay contact on this board **cannot be opened by the safety rail** — the rail only de-energizes coils. The machine's master breaker / Stop / CIS chain remains the final physical stop (§9.7 and **Section 10, §10.5 Welded Contact Limitation**).
- The contacts will see whatever the harness lands on them — measured to be **24 VAC** on this chassis, but the contract allows 24 VAC, 12 VDC, or other machine control voltages (`phase8b_pcb_revB_spec.md` §2.3). They are inductive (relay/contactor coils), hence the snubber + MOV footprints (§9.5).

---

### 9.2 Per-output channel map

There are **seven** machine-output relay channels. Six are populated; **M1 (ball return) is Do-Not-Populate (DNP)**. The command bit, the OUT-A expander pin, the contact form, and the bench-observed machine destination for each are below.

Bit map and MCP pin numbers are from `OUTPUT_PINS` in `generate_kicad_netlist_revB.py` (lines 132–144) and the matching `OUT_A_MAP` in `controller_io.py` (lines 55–67), which is regression-locked to the generator. MCP23017 pin → port/bit decode: pins 21–28 = GPA0–GPA7 = (port 0, bit 0..7); pins 1–8 = GPB0–GPB7 = (port 1, bit 0..7).

| Output | Function | `MCP_OUT_A` pin | Port,bit (`OUT_A_MAP`) | Contact form | Populated? | On safety rail? | Bench-measured machine destination |
|---|---|---|---|---|---|---|---|
| **S** | Sweep motor **contactor command** | 21 (GPA0) | (0, 0) | Isolated NO dry contact | Yes | Yes | C1, cavities C, D, N, T |
| **T** | Table motor **contactor command** | 22 (GPA1) | (0, 1) | Isolated NO dry contact | Yes | Yes | C1, cavities A, K, H, E (+ L) |
| **SP** | Spot solenoid command | 23 (GPA2) | (0, 2) | Isolated NO dry contact | Yes | Yes | C2A (direct 0 Ω) |
| **BE** | Back-end command | 24 (GPA3) | (0, 3) | Isolated NO dry contact | Yes | Yes | Straddles C1 + C2A |
| **M** | Master / control command | 25 (GPA4) | (0, 4) | Isolated NO dry contact | Yes | Yes | C2A |
| **M2** | Sweep-reverse command | 26 (GPA5) | (0, 5) | Isolated NO dry contact | Yes | Yes | C2A on this bench (OEM docs say C1 — see note) |
| **M1** | Ball-return command | 27 (GPA6) | (0, 6) | Isolated NO dry contact | **No — DNP** | Yes (if populated) | Not bench-confirmed on this chassis |

Notes:

- **Bit ordering is M2 *before* M1.** `MCP_OUT_A` pin 26 = M2 (sweep reverse) and pin 27 = M1 (ball return). This non-obvious order is the as-built generator order and is explicitly called out in `controller_io.py:61`. Do not assume numeric "M1 then M2."
- **The four status-lamp bits (`L_FIRST`/`L_SECOND`/`L_STRIKE`/`L_FOUL`, pins 28/1/2/3) share the `MCP_OUT_A` expander but are a different output stage** — low-side 2N7002 FET LED drivers, *not* relays, and *not* on the safety rail. They are covered in **Section 10, Status-Lamp LED Drivers**; they appear here only because they occupy the rest of OUT-A.
- The "machine destination" column is **OEM/bench reference only and is chassis-specific — it is NOT a copper constraint.** Outputs are deliberately function-named and the per-lane adapter harness resolves the actual C1/C2A cavities at cutover (`phase8b_pcb_revB_spec.md` §3.2, §7). The OEM wire tables and this bench *disagree* on routing (most sharply on M2: OEM = C1 with a TSA/Expander path; this bench measured M2 → C2A at direct 0 Ω). Both are correct for their respective chassis because the Omega-Tek retrofit re-landed the harness. **Do not bake any cavity into a board trace.**

> **M2 / sweep-reverse interlock — do not lose it.** Regardless of which connector M2 lands on, the OEM Expander warning is chassis-independent: the sweep-reverse path includes a motor-start/reverse interlock and a shorting-plug requirement ("expander cable must be terminated or sweep won't run"). The adapter harness must **preserve that interlock function**, not merely jumper the cavity (`phase8b_pcb_revB_spec.md` §3.2).

#### Firmware-side coupling (RUN/STOP) — context for the next engineer

The seven relay outputs are exactly the set the FSM treats as **motion relays** (`controller_io.py:87`, `MOTION_RELAYS = ("S","T","SP","BE","M","M1","M2")`). When an RP2040 co-processor link is wired, energizing/de-energizing any of these also sends a RUN/STOP to the RP2040 so its UART-independent max-run backstop knows what is energized. The RP2040 guards `MAX_MOTION_MS = 8000` (8 s) per motor and drops `RP2040_OK` — and therefore the rail — on overrun, **except BE (continuous) and M (master/power), which are explicitly not guarded** (`firmware/rp2040/config.h:48–52`). This is why a stuck S/T can self-trip the rail but a stuck M cannot; see **Section 10** for the full rail logic and **Section 7 / the RP2040 section** for the co-processor.

---

### 9.3 The output chain, stage by stage

The schematic for one relay channel is built by `relay_output()` in `generate_kicad_netlist_revB.py` (lines 254–288). The same circuit is instantiated seven times (six live + M1 DNP). Trace it once and you understand all of them.

**Net names below use the generator's per-channel suffix** — e.g. for the sweep output the drive net is `DRV_S`, the base node is `BASE_S`, the switched coil low side is `COIL_LO_S`, the contacts are `OUT_S_A` (COM) / `OUT_S_B` (NO), and the snubber midpoint is `SNUB_S`.

#### Stage 1 — Command bit on MCP_OUT_A

The controller writes the output bit into the `OLATA`/`OLATB` latch of the `MCP_OUT_A` MCP23017 (I²C address `0x22` per `controller_io.py:46`; `MCP_OUT_A` is strapped A2A1A0 = (0,1,0), i.e. A1 high, in `generate_kicad_netlist_revB.py:520`). A HIGH on the OUT-A pin = "command this output ON." MCP23017 GPIO push-pull outputs swing to the chip's rail, which on this board is **3.3 V** (`VCC_3V3`) — the entire controller/expander logic is on 3.3 V, never 5 V (`phase8b_pcb_revB_spec.md` line 13; the MCP banks and I²C pull-ups are on `VCC_3V3`).

#### Stage 2 — MMBT3904 low-side driver

Each relay channel has a dedicated **MMBT3904 NPN BJT** (SOT-23) wired as a low-side (common-emitter) switch (`relay_output()`, `q = MMBT3904`, lines 260–275):

| Element | Net / pin | Value | Purpose |
|---|---|---|---|
| Base resistor `Rb_<name>` | `DRV_<name>` → `BASE_<name>` (Q pin 1) | **1 k** | Limits base drive from the 3.3 V OUT-A bit |
| Base pull-down `Rpd_<name>` | `DRV_<name>` → `GND` | **100 k** | Holds the base low so the relay is **off** whenever OUT-A is Hi-Z / un-driven (fail-safe) |
| Emitter | Q pin 2 → `GND` | — | Logic ground return |
| Collector | Q pin 3 → `COIL_LO_<name>` | — | Sinks the relay coil low side |

When the OUT-A bit goes HIGH, the MMBT3904 saturates and pulls `COIL_LO_<name>` toward logic GND, completing the coil circuit. When the bit is LOW (or the expander is unpowered / un-initialized), the 100 k pull-down keeps the base off and the relay is de-energized. This pull-down is the **per-channel fail-safe-off** at the driver level; it complements the rail-level fail-safe (Stage 4).

> MMBT3904 ratings (general-purpose): ~200 mA collector, 40 V — ample to sink a 5 VDC G5LE coil (the G5LE-14 5 V coil draws on the order of ~80 mA, ~71.4 mA nominal per Omron data, well under the 3904's limit). The exact per-channel transistor reference designators (which `Q#` is the S driver, etc.) are assigned by KiCad annotation, not by the generator's `tag=` labels, so they are **not pinned by these source files**; the assembly BOM groups all eight MMBT3904 (six relay drivers + the two safety AND-chain transistors `Q_AND_ARM` / `Q_AND_RP_OK`) under `Q1,Q2,Q3,Q4,Q5,Q6,Q15,Q16` (`…pcba-bom.csv` line 9). `(VERIFY: which specific Q-designator drives which relay — read it off the placed board / .kicad_pcb if you need to probe a single channel's base.)`

#### Stage 3 — G5LE relay coil + flyback diode

The relay is an **Omron G5LE-1 footprint, populated as the G5LE-14 5 VDC SPDT part** (`Relay_SPDT_Omron-G5LE-1`; BOM line 8, LCSC **C116963**, MFR **G5LE-14 5VDC**, qty 6 = K1–K6). The coil is wired:

| Coil terminal | Net | Notes |
|---|---|---|
| Coil high side, relay pin **1** | `RELAY_ENABLE_RAIL` | Coil is fed from the **safety rail**, not directly from `VCC_5V` |
| Coil low side, relay pin **2** | `COIL_LO_<name>` → MMBT3904 collector | Driver sinks this to GND to energize |

Across the coil is a **flyback diode** `Dfly_<name>` = **1N4148** (SOD-323; BOM line 6, `1N4148WS`, LCSC C118873), oriented:

- Cathode (pin 1) → `RELAY_ENABLE_RAIL` (coil high side)
- Anode (pin 2) → `COIL_LO_<name>` (switched coil low side)

This is the standard freewheel orientation: in normal operation the diode is reverse-biased; when the MMBT3904 turns off and the coil's field collapses, the diode clamps the inductive kick to one diode-drop above the rail, protecting the transistor's collector. (`relay_output()` lines 264, 274–275.) Note the flyback is referenced to the rail, not to a fixed 5 V — so it tracks whatever the rail is doing, which is correct because the coil's high side *is* the rail.

#### Stage 4 — RELAY_ENABLE_RAIL gates the coil supply

All seven relay coils' high sides connect to the single `RELAY_ENABLE_RAIL` net (including the DNP M1). The rail is the **electrical enable** for motion: it is sourced through a P-channel pass-FET (`AO3401A`, ref Q14, BOM line 12) that only conducts when the full series safety chain is satisfied — Watchdog OK **and** Arm OK **and** RP2040 OK **and** the external TB/SC and Stop/CIS hardware loops (`block_rail()` lines 465–504; `phase8b_pcb_revB_spec.md` §4). If any condition is false the rail collapses and **every** coil drops, regardless of what the controller commands. The controller cannot bypass this in software.

The board verification in the spec confirms `RELAY_ENABLE_RAIL` reaches all 7 relay coils, all flybacks, the pass-FET, and test point TP16, and that it is a 16-node net (`phase8b_pcb_revB_spec.md` lines 13, 21). **This is the central safety property of the output stage** — full detail is in **Section 10, Safety Rail Contract**, and the watchdog that feeds it is in **Section 10, NE555 Hardware Watchdog** `(VERIFY: final section numbers for Safety Rail / NE555 / Status-Lamp once the manual TOC is fixed; cross-refs here assume Safety Rail = §4, Status Lamps = §10, NE555 = §11)`.

#### Stage 5 — Isolated dry contact into the machine

The relay's SPDT contact is brought out as a **2-pin dry NO pair** per output:

| Contact | Relay pin | Net | Connector (per output) | Connector pin |
|---|---|---|---|---|
| COM | 3 | `OUT_<name>_A` | `J_MOTION_<name>` | 2 |
| NO | 4 | `OUT_<name>_B` | `J_MOTION_<name>` | 1 |

Each motion output gets its **own dedicated 2-pin Phoenix terminal block** — `J_MOTION_S`, `J_MOTION_T`, `J_MOTION_SP`, `J_MOTION_BE`, `J_MOTION_M`, `J_MOTION_M2`, `J_MOTION_M1` — using footprint `TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal` (5.08 mm pitch, `block_connectors()` lines 368–377, 428–436). The board originally used one dense motion connector; it was deliberately **split into seven independent 2-pin blocks** to preserve channel-to-channel creepage/clearance and keep the harness function-named (`generate_kicad_netlist_revB.py:431–434`; `phase8b_pcb_revB_spec.md` route-pass notes). On each terminal the **NO contact is pin 1 (top) and COM is pin 2 (bottom)**, intentionally mirroring the vertical order of the G5LE contact pads (B above A) so the harness ordering matches the silkscreen.

The contact is the **only** electrical connection between the board's output section and the machine control circuit — there is no shared ground, no shared rail. That isolation is what lets the board sit in series with a 24 VAC (or 12 VDC) coil circuit while its own logic stays on an isolated 5 V / 3.3 V / logic-GND domain.

---

### 9.4 One-channel reference schematic (sweep "S")

Putting Stages 1–5 together for the S output (every channel is identical except the suffix and the DNP flag on M1):

```
                         RELAY_ENABLE_RAIL  (gated by safety rail, §10)
                                 │
                    ┌────────────┴───────────┐
                    │ K_S  G5LE-14 5VDC       │
   Dfly_S 1N4148    │                          │   COM (pin3) ── OUT_S_A ── J_MOTION_S pin2
   (cathode→rail) ──┤ coil pin1                │   NO  (pin4) ── OUT_S_B ── J_MOTION_S pin1
   (anode→COIL_LO)  │ coil pin2 ── COIL_LO_S ──┼── Q collector (pin3)
                    └──────────────────────────┘        │  MMBT3904 (Qk_S)
                                                          │
   MCP_OUT_A pin21 ── DRV_S ──[Rb_S 1k]── BASE_S ── base (pin1)
                         │                              emitter (pin2) ── GND
                      [Rpd_S 100k]
                         │
                        GND

   Arc suppression across the contact (all DNP from the factory):
        OUT_S_A ──[Rsnub_S 100R]── SNUB_S ──[Csnub_S 10nF X2]── OUT_S_B
        OUT_S_A ────────────────[ MOV_S ]──────────────────── OUT_S_B
```

---

### 9.5 Contact arc suppression: RC snubber + MOV (depopulatable)

Because the contacts switch **inductive AC control loads** (relay/contactor coils on a 24 VAC rail), every motion output has footprints for arc suppression across the COM/NO contact (`relay_output()` lines 277–287). **All three suppression parts are shipped DNP (not placed)** and are populated per-output only after the real load on that contact is characterized at the machine (`phase8b_pcb_revB_spec.md` §2.3, §3.2):

| Element | Net path | Footprint | Value (DNP) | Purpose |
|---|---|---|---|---|
| Snubber resistor `Rsnub_<name>` | `OUT_<name>_A` → `SNUB_<name>` | `R_0805` | **100 R, DNP** | Series R of the RC snubber; damps the LC ring and limits capacitor inrush at contact closure |
| Snubber capacitor `Csnub_<name>` | `SNUB_<name>` → `OUT_<name>_B` | `C_0805` | **10 nF X2, DNP** | Absorbs the inductive turn-off transient across the opening contact |
| MOV `MOV_<name>` | `OUT_<name>_A` → `OUT_<name>_B` | `D_SMA` | **MOV, DNP** | Clamps the peak voltage spike across the contact |

The RC pair forms a classic contact snubber (R in series with C across the contact); the MOV is a parallel voltage clamp. They are DNP by default for two reasons: (1) the actual contact load/voltage on each channel is harness- and chassis-dependent and unknown until cutover, and (2) the fab package's isolation proof is conservative copper clearance, not slot-boosted creepage, so adding a part across the gap is a deliberate per-channel decision (`phase8b_pcb_revB_spec.md` line 15). Choose the snubber R/C and MOV clamp voltage **after** measuring the coil's inductance and the rail voltage that actually appears on that contact.

> The `D_SMA` footprint is shared by both the MOV placeholder and the real SS14 input-protection Schottky (BOM line 7) and the flyback alias on some nets — when populating a MOV, confirm you are placing an MOV rated for the measured working voltage, not a diode. `(VERIFY: specific MOV part number / clamp voltage — none is selected in the sources; it is left as a DNP placeholder pending load characterization.)`

---

### 9.6 Why a 5 VDC coil (not 12 V or 24 V)

The relay is deliberately the **5 VDC-coil** G5LE-14, not the 12 V or 24 V variant. The BOM calls this out as critical: *"Critical: 5VDC coil. Do not substitute 9V/12V/24V coil."* (`…pcba-bom.csv` line 8).

Rationale, grounded in the board architecture:

1. **The board already regulates 5 V for everything.** The logic domain (Pi-side 5 V distribution / external regulated 5 V), the relay coils, and the opto LED logic sides all run from `VCC_5V` (`phase8b_pcb_revB_spec.md` §8.1). `RELAY_ENABLE_RAIL` is derived from `VCC_5V` through the safety pass-FET. A 5 V coil means the coil supply **is** the existing board rail — no separate 12 V or 24 V coil rail has to be generated on the board. (The Power Contract explicitly says the board provides regulated 5 V "to … on-board output relay coils if 5 V relay coils are selected," `§8.1`.)
2. **The machine's coil voltages stay on the machine.** The 24 VAC / 12 VDC the *machine* relays use are switched by the dry contacts, not by the board's coil rail (§9.1). So there is no electrical reason to match the machine's coil voltage with the board's coil voltage — they are isolated. Picking 5 V keeps the board single-rail.
3. **Low-side drive from a 3.3 V logic bit is trivial at 5 V.** The MMBT3904 sinks a 5 V coil to logic GND directly; a 12 V or 24 V coil would need a higher coil rail and would change the flyback clamp level, with no benefit.
4. **Fail-safe.** With the coil high side on the rail and the low side on a fail-off MMBT3904, the relay is guaranteed de-energized on loss of 5 V, loss of rail, or un-driven OUT-A — see §9.2/§9.3.

The trade-off the next engineer must still close: confirm the **5 V supply current margin** with the worst-case simultaneous relay count (and any decision to populate M1), since six or seven 5 V coils energized at once is the peak board load (`phase8b_pcb_revB_spec.md` §8.1, §11 item 2). At roughly 70–80 mA per G5LE-14 coil, six coils is on the order of ~0.45–0.5 A of coil current on top of logic and opto loads `(VERIFY: exact G5LE-14 coil current — use the Omron datasheet figure for the as-built lot; the ~71–80 mA range here is the published nominal, not a measured value)`.

---

### 9.7 M1 (ball return): DNP and why

**M1 is populate-optional and ships DNP.** The board carries the full M1 channel as copper — relay footprint `K7`, its MMBT3904 driver `Q7`, resistors `R85–R87`, flyback `D13`, MOV `D14`, snubber cap `C10`, and the `J_MOTION_M1` terminal — but all of these are flagged **DNP + exclude_from_bom + exclude_from_pos_files** so JLC does not place them and they do not appear in the assembly BOM/CPL (`phase8b_pcb_revB_spec.md` lines 25, 27; the populated relay BOM line 8 is qty **6** = K1–K6, not 7). In the generator this is `relay_output("M1", …, dnp=True)` (line 536), which appends "DNP" to the relay value string.

The reason is empirical, not cosmetic: **M1 (a separate ball-return command relay) was never bench-confirmed on this chassis, and the cycle-control FSM does not drive ball return** (`phase8b_pcb_revB_spec.md` §3.2 table + Claude amendment; `phase8_bench_session1_FINDINGS.md` does not map an M1 relay). Do **not** populate or harness M1 until you have verified at the machine that ball return exists as a separate, board-commandable coil circuit on that specific cabinet (`phase8b_pcb_revB_spec.md` §11 item 6). When you do confirm it, populate K7/Q7/R85–R87/D13/D14/C10, clear the DNP flags, re-run DRC and the fab export, and update the channel-allocation doc.

Everything else about M1 is identical to the other six channels: same G5LE-14 5 V relay, same MMBT3904 low-side driver, same flyback orientation, same coil high side on `RELAY_ENABLE_RAIL` (it is wired to the rail even while DNP), and the same DNP snubber/MOV footprints.

---

### 9.8 Welded-contact limitation and the upstream safety chain

Restating the boundary from §9.1 because it is the one thing a service tech must internalize:

- The safety rail **de-energizes coils**. It removes drive. It **cannot pull open a contact that has welded shut.** If a G5LE NO contact welds, the machine control circuit it feeds stays closed even with the rail dropped (`phase8b_pcb_revB_spec.md` §4.5).
- Therefore the existing **master breaker / Stop / CIS chain on the machine remains the final physical stop** and must stay upstream and live (`phase8b_pcb_revB_spec.md` §0 non-negotiable rule, §4.5).
- This is *why* contact rating, suppression population (§9.5), and bench validation of every relay contact under a dummy load are treated as safety-relevant tasks, not optional polish (`phase8b_pcb_revB_spec.md` §11 item 1, §12 bench step "each relay contact with dummy load").

Open items that gate a populated, cutover-ready output stage (not bare-PCB fab), from `phase8b_pcb_revB_spec.md` §11:

1. **Output relay rating** — confirm contact current/voltage for S/T/SP/BE/M/M2 against the real coil-circuit loads and decide whether the G5LE-14 contact margin is sufficient.
2. **Coil rail budget** — confirm 5 V supply current margin with worst-case relay count (§9.6).
3. **Safety connector form** — confirm TB/SC/Stop/CIS electrical form and `J_SAFETY` polarity (see **Section 10**).
6. **M1 status** — confirm ball-return-as-separate-command before populating M1 (§9.7).

---

### 9.9 Bill of materials — output stage (per board)

Quantities are per single-lane board, from `…pcba-bom.csv`. Relay-driver transistor count (6) is the populated-relay count; the eight-MMBT3904 BOM line also includes the two safety AND-chain transistors (covered in **Section 10**).

| Designators | Comment | Footprint | Qty | LCSC | MFR P/N | Role in output stage |
|---|---|---|---|---|---|---|
| K1,K2,K3,K4,K5,K6 | G5LE-14 5VDC SPDT relay, wave solder | `Relay_SPDT_Omron-G5LE-1` | 6 | **C116963** | **G5LE-14 5VDC** | Isolated dry NO contact per motion output (S/T/SP/BE/M/M2) |
| (K7) | G5LE-14 5VDC SPDT relay | `Relay_SPDT_Omron-G5LE-1` | **0 (DNP)** | C116963 | G5LE-14 5VDC | M1 ball-return channel — DNP/excluded (§9.7) |
| Q1,Q2,Q3,Q4,Q5,Q6 (subset of the 8) | MMBT3904 NPN BJT, SOT-23 | `SOT-23` | 6 of 8 | C909754 | MMBT3904 | Low-side coil driver, one per populated relay |
| D1,D3,D5,D7,D9,D11 (subset of the 8) | 1N4148WS switching diode, SOD-323 | `D_SOD-323` | 6 of 8 | C118873 | 1N4148WS | Coil flyback clamp, one per populated relay |
| Rb (1 k group) | 1k 1% 0805 | `R_0805` | within R67… group (12 total) | C17513 | 1k | MMBT3904 base series resistor |
| Rpd (100 k group) | 100k 1% 0805 | `R_0805` | within R68… group (14 total) | C149504 | 100k | MMBT3904 base pull-down (fail-off) |
| Rsnub_* | 100R 0805 | `R_0805` | **DNP** | — | 100R | RC snubber series R (depopulatable, §9.5) |
| Csnub_* | 10nF X2 0805 | `C_0805` | **DNP** | — | 10nF | RC snubber capacitor (depopulatable, §9.5) |
| MOV_* | MOV, SMA footprint | `D_SMA` | **DNP** | — | — | Contact MOV clamp (depopulatable, §9.5) |

> The `1N4148WS` (D1…D16, qty 8) and `1k`/`100k` resistor groups are **shared** between the relay drivers and other blocks (notably the watchdog and safety AND-chain). The six-per-block counts above are the output-stage share; the BOM lines list the full per-value totals (`…pcba-bom.csv` lines 6, 16, 17). `(VERIFY: exact per-channel designator-to-output binding for Rb/Rpd/Dfly/Q — assigned by KiCad annotation, not by the four source files; read the placed .kicad_pcb to probe a specific channel.)`

Footprint reference (from `generate_kicad_netlist_revB.py` lines 48–69): relay = `Relay_THT:Relay_SPDT_Omron-G5LE-1`; flyback = `Diode_SMD:D_SOD-323`; MOV = `Diode_SMD:D_SMA`; driver = `Package_TO_SOT_SMD:SOT-23`; snubber R/C = `R_0805_2012Metric` / `C_0805_2012Metric`; per-output motion terminal = `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal`.

---

### 9.10 Bench bring-up checklist for the output stage

From the spec's bench sequence (`phase8b_pcb_revB_spec.md` §12), do this **only on a locked-out / off-live machine**, and in this order:

1. Power rails up; confirm `VCC_5V` and that `RELAY_ENABLE_RAIL` is **dead** until the safety chain is satisfied (watchdog kicked, arm asserted, RP2040 OK, TB/SC + Stop/CIS loops closed).
2. Verify the rail-fail cases first: drop the watchdog → rail drops → all relays release; drop arm → release; open the interlock loop → release; let RP2040_OK fall → release. (These are **Section 10** tests but they gate everything here.)
3. With the rail enabled, command each relay output **one at a time** from the controller and confirm continuity COM↔NO closes at the matching `J_MOTION_<name>` terminal **into a dummy load**, not the live machine.
4. Confirm the per-channel fail-off: with the rail up, drive OUT-A low (or pull the expander) and confirm the contact opens (100 k base pull-down holds the MMBT3904 off).
5. Characterize the real coil-circuit load per output at the machine, **then** decide and populate the snubber/MOV per channel (§9.5).
6. Only after all of the above, connect the machine harness.

Test points exist for relay coil drive, relay common, relay NO, and relay state per the layout contract (`phase8b_pcb_revB_spec.md` §3.2, §9), plus TP16 on `RELAY_ENABLE_RAIL`.

---

**Cross-references:** Safety rail and welded-contact limitation — **Section 10**. MCP23017 OUT-A device, I²C addressing, and the controller `io` object — **Section 7**. RP2040 RUN/STOP coupling, `MAX_MOTION_MS` motion backstop, and `RP2040_OK` rail permission — **Section 7 / the RP2040 co-processor section**. Status-lamp LED drivers that share OUT-A but are not relays — **Section 10**. NE555 watchdog that feeds the rail — **Section 10**. `(VERIFY: final manual section numbering once the full TOC is assembled.)`


## 10. Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail

This section documents the two hardware blocks that decide whether the on-board
motion relays are *allowed* to energize: the **NE555 monostable watchdog** (which
watches the Raspberry Pi) and the **relay-enable rail** (a hardware AND of six
independent conditions that gates the P-channel pass-FET feeding all relay coils).

Everything here is grounded in the live board netlist generator
(`scripts/generate_kicad_netlist_revB.py`, functions `block_watchdog()` and
`block_rail()`), the as-built netlist (`kicad/wsl-phase8b.net`), the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`),
the design contract (`docs/phase8b_pcb_revB_spec.md` §4), and the RP2040 firmware
(`firmware/rp2040/config.h`, `firmware/rp2040/README.md`).

> **Read this first — the one non-negotiable rule.** This board is **never** the
> only safety device. Live motor current never crosses the PCB (S/T motor current
> stays on the machine contactors, with their OEM regenerative braking on the N.C.
> contacts), the TB/SC collision interlock and the Stop/CIS/master-breaker chain
> remain upstream in hardware, and the rail described here only removes the *coil
> drive permission* for the on-board relays. See §10.6 (Welded-contact limitation)
> and cross-reference §19 (Safety Model — Stop/CIS/master chain) and the FSM's
> power-down rule.

---

### 10.1 What these blocks do, in one paragraph

The Pi runs the cycle FSM and commands the 7 motion relays *indirectly* over I²C
through the `MCP23017 OUT-A` expander (see §7, Controller Interface). But software
commanding a relay bit HIGH does **not** energize the coil. Each coil's high side
is fed from a single net — `RELAY_ENABLE_RAIL` — and that net is only live when a
P-channel pass-FET (`Q14`, AO3401A) is turned on. `Q14` turns on only when **all
six** of the conditions in §10.3 are simultaneously true. Two of those conditions
are external normally-closed (NC) loops in series with the FET's source; three are
on-board transistors wired in a series (AND) stack that pulls the FET gate low; and
one (cam-stop) folds into the RP2040 health condition. Lose any one — a missed
watchdog kick, a dropped ARM GPIO, a reset/crashed RP2040, a cam-stop violation, an
open TB/SC interlock, or an open Stop/CIS loop — and the rail collapses, dropping
all relay coils. The design **fails open by construction**: when the RP2040 is
unpowered or in reset its `RP2040_OK` line floats, and an on-board 100 k pulldown
holds the AND chain (and therefore the rail) dead.

---

### 10.2 The NE555 monostable watchdog (watches the Pi)

The NE555 is wired as a **retriggerable monostable** (one-shot). Left alone, its
timing capacitor charges, the output stays in its idle state, and the watchdog "OK"
condition is **false**. The Raspberry Pi must periodically **kick** it (pulse a
GPIO) to keep restarting the one-shot and thereby hold the watchdog "OK" condition
**true**. If the Pi process hangs, crashes, or the OS dies, the kicks stop, the
monostable times out, and the watchdog condition drops the rail. This is the
hardware backstop for "the Pi died" — it is independent of the RP2040, of UART, and
of any software running on the Pi.

> **Two different watchdogs — do not confuse them.** This NE555 watches the **Pi**.
> The RP2040 has its own *internal* hardware watchdog (`WDT_TIMEOUT_MS = 250 ms`,
> `firmware/rp2040/config.h`) that watches the **Pico firmware** and is a *separate*
> rail condition (it manifests as `RP2040_OK`/Cam-stop, §10.3 rows 3–4). The NE555
> covers Pi-side death; the RP2040 internal WDT covers Pico-side death.

#### 10.2.1 NE555 watchdog — parts

Reference designators are from the as-built netlist; LCSC/MFR part numbers from the
JLC PCBA BOM.

| RefDes | Part / value | Footprint | LCSC | Role in the watchdog |
|---|---|---|---|---|
| U36 | NE555DR (TI) **bipolar** 555 timer | SOIC-8 (`SOIC-8_3.9x4.9mm`) | C7593 | Monostable one-shot. **Bipolar 555 — do NOT substitute a CMOS/TLC555**; the timing/threshold behavior would change (BOM note). |
| Q12 | AO3400A N-ch MOSFET ("kick") | SOT-23 | C20917 | Level/edge buffer for the Pi's `WDOG_KICK` GPIO; its drain pulls the timing/trigger node. |
| Q13 | AO3400A N-ch MOSFET ("wdog") | SOT-23 | C20917 | The watchdog-OK output device — its drain is the bottom of the rail AND chain (§10.3/§10.4). |
| C11 | 100 µF / 16 V aluminum electrolytic (**polarized**) | `CP_Elec_6.3x5.4` | C19184134 | Timing capacitor. Verify polarity mark before solder. |
| R100 | 100 k | 0805 | C149504 | Timing resistor (sets the RC charge time with C11). |
| C13 | 10 nF | 0805 | C17702767 | NE555 CTRL-pin (pin 5) decoupling. |
| C12 | 100 nF (0.1 µF) | 0805 | C49678 | NE555 VCC decoupling. |
| R101 | 10 k | 0805 | C17414 | **Trigger pull-up** (the "Rev-A trigger pull-up fix", spec §4.3). |
| R102 | 1 k | 0805 | C17513 | Gate resistor for the kick FET Q12. |
| R103 | 10 k | 0805 | C17414 | Gate pulldown for Q12 (default-off / fail-safe). |
| R104 | 1 k | 0805 | C17513 | Gate resistor for the wdog-OK FET Q13. |
| R105 | 10 k | 0805 | C17414 | Gate pulldown for Q13 (default-off / fail-safe). |
| D15 | 1N4148WS | SOD-323 | C118873 | Steers Q12's kick into the **timing** node (`WDOG_TIMING_NODE`). |
| D16 | 1N4148WS | SOD-323 | C118873 | Steers Q12's kick into the **trigger** node (`NE555_TRIG`). |

> The R-designators above are read off the as-built netlist's `(name "SKiDL Tag")`
> entries: `R_WDOG_TIMING`→R100, `R_WDOG_TRIG_PULLUP`→R101, `R_WDOG_KICK_GATE`→R102,
> `R_WDOG_KICK_PD`→R103, `R_WDOG_OUT_GATE`→R104, `R_WDOG_OUT_PD`→R105. Capacitors:
> `C_WDOG_TIMING`→C11, `C_WDOG_VCC`→C12, `C_WDOG_CTRL`→C13. The 0805 R/C parts share
> a single grouped BOM line each, so the same LCSC number covers many same-value
> parts on the board — confirm by *value*, not by assuming a unique line per RefDes.

#### 10.2.2 NE555 pin connections (U36, SOIC-8)

NE555 pin numbers below are the standard 555 pinout as wired in `block_watchdog()`.

| 555 pin | Function | Net on this board | Connected to |
|---|---|---|---|
| 1 | GND | `GND` | board ground |
| 2 | TRIG (trigger, active-low) | `NE555_TRIG` | R101 (10 k pull-up to VCC_5V), D16 (from kick FET) |
| 3 | OUT (output) | `NE555_OUT` | R104 → Q13 gate (drives the watchdog-OK FET) |
| 4 | RESET (active-low) | `VCC_5V` | tied HIGH (reset disabled) |
| 5 | CTRL (control voltage) | `NE555_CTRL` | C13 (10 nF) to GND — noise decoupling |
| 6 | THRES (threshold) | `WDOG_TIMING_NODE` | R100 (100 k) to VCC_5V, C11 (100 µF) to GND, D15 |
| 7 | DISCH (discharge) | `WDOG_TIMING_NODE` | same node as pin 6 (THRES tied to DISCH — classic monostable) |
| 8 | VCC | `VCC_5V` | +5 V logic rail, with C12 (0.1 µF) decoupling |

Pins **6 and 7 are tied together** on `WDOG_TIMING_NODE` with R100 to +5 V and C11
to ground — the textbook 555 monostable RC. The watchdog runs from the **+5 V logic
rail** (`VCC_5V`), the same regulated supply as the MCP23017s' coil drivers, **not**
from 3.3 V.

#### 10.2.3 How a kick keeps the watchdog OK

1. **Pi kicks.** The Pi pulses its watchdog-kick GPIO. On the Rev-B board that
   signal arrives on connector **J1 (J_PI) pin 7**, net `WDOG_KICK`, through R102
   into the gate of the kick FET **Q12** (gate held off by R103, 10 k pulldown, when
   the Pi is silent → fail-safe). In the lane-node software this kick is
   `MachineIO.watchdog_kick()` / the injected `watchdog_kick` callable
   (`lane_node/controller_io.py`), i.e. the GPIO12 pulse referenced as "the NE555
   watchdog kick."
2. **Kick drives the timing + trigger nodes.** Q12 turning on pulls
   `WDOG_KICK_DRAIN` low; D15 and D16 (1N4148) steer that into the **timing** node
   (discharging/restarting the RC) and the **trigger** node (re-firing the
   one-shot). Each kick restarts the monostable.
3. **Output → watchdog-OK FET.** While kicks keep arriving inside the timeout
   window, the NE555 output (pin 3, `NE555_OUT`) drives the gate of **Q13** through
   R104 such that Q13 **conducts** — and Q13's drain (`WDOG_OK_PULLDOWN`) is the
   bottom rung of the rail AND chain (§10.4). Conducting Q13 = "Watchdog OK" = true.
4. **Missing kicks → rail drops.** If kicks stop for longer than the monostable's
   timeout, the NE555 output reverts, Q13 turns **off**, the AND chain opens, the
   pass-FET turns off, and **all relay coils drop**.

> **(VERIFY: NE555 monostable timeout period.)** The RC is R100 = 100 k and C11 =
> 100 µF (≈ 1.1·R·C ≈ 11 s nominal for a standard monostable), but the kick is wired
> into **both** the timing node and the trigger (a retrigger topology), and the
> design doc describes it qualitatively as "missing kick for the timeout window
> drops the rail" (spec §4.3) without stating the number. The **effective** Pi-kick
> interval and the guaranteed worst-case drop time are bench-bring-up items
> (spec §12.9 "watchdog drop" step) and are **not** asserted as a specific value in
> the sources read for this section. Measure on the bench; do not assume 11 s.

> **(VERIFY: kick GPIO number on the Pi.)** This section's sources fix the *board*
> side (J1 pin 7 → `WDOG_KICK`). Project memory describes the Pi pulsing **GPIO 12**
> for the watchdog kick, but the Pi-side GPIO assignment is not pinned down in the
> four files read here — confirm against the lane-node daemon wiring.

---

### 10.3 The relay-enable rail — the six AND conditions

`RELAY_ENABLE_RAIL` is the high-side supply to every motion-relay coil. It is live
only when the P-channel pass-FET **Q14 (AO3401A)** is on, and Q14 is on only when
**all six** conditions below hold. The Pi cannot bypass any of them in software
(spec §4.1). All default **false / open** (fail-safe).

| # | Condition | Source / device | Where it acts on the rail | Fail-safe default |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 (U36) kicked by the Pi → FET Q13 | Bottom of the gate AND chain (Q13 must conduct) | false (no kicks → Q13 off) |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO (J1 pin 8) → NPN Q15 | Top of the gate AND chain (Q15 must conduct) | false (R108 100 k base pulldown) |
| 3 | **RP2040 OK** | RP2040 `GP2` health line (`RP2040_OK`) → NPN Q16 | Middle of the gate AND chain (Q16 must conduct) | false (R110 100 k base pulldown; GP2 Hi-Z on reset) |
| 4 | **Cam-stop OK** | RP2040 immediate cam-stop drop | **Folds into condition 3** — the firmware drops `GP2` LOW on a cam-stop violation/timeout | false on RP2040 reset/fault |
| 5 | **TB/SC hardware interlock** | External NC loop on J_SAFETY (J14 pins 1↔2) | In series with the FET **source** | open (loop break removes source feed) |
| 6 | **Stop/CIS/master chain** | External NC loop on J_SAFETY (J14 pins 3↔4) | In series with the FET source, after the TB/SC loop | open |

Two structural facts make this a true hardware AND:

- **Conditions 5 and 6 are in series with the FET's source** — they physically feed
  the +5 V into the pass-FET. Break either loop and the FET has nothing to pass,
  regardless of the gate.
- **Conditions 1, 2, and 3 (=4) are a series transistor stack on the FET's gate** —
  all three must conduct to pull the P-FET gate low enough to turn it on. Any one
  open and the gate stays pulled up to the source (FET off).

> **Why cam-stop is not a separate transistor.** The contract lists Cam-stop OK as a
> distinct rail condition (spec §4.1) with fail-safe "false on reset/fault," but the
> **board implements it through `RP2040_OK`**: the RP2040 firmware is the cam-stop
> enforcer and pulls its single `GP2` health/permission line LOW on a cam-stop
> violation or cam timeout (spec §4.2; `firmware/rp2040/README.md` "Motion max-run
> /cam timeout → drops RP_OK"). So electrically there are **five** physical gates
> (two source loops + a three-transistor AND), and cam-stop is the *firmware
> behavior* that drives one of them (`RP2040_OK`/Q16) false. Do not look for a sixth
> transistor on the board — there isn't one. **Note:** the v0.1.0 firmware provides
> RP2040 *health* + a motion **max-run** backstop; full per-cam-edge cam-stop
> *overrun* enforcement is the deferred **v1.1** item (firmware README), still gated
> on bench-confirmed cam edge→angle polarity.

---

### 10.4 The AND-chain transistors (gate pull-down stack)

This is the heart of "non-bypassable." The pass-FET **Q14 (AO3401A, P-channel)** is
a high-side switch: its **source** is fed (through the two NC safety loops) from
+5 V, its **drain** is `RELAY_ENABLE_RAIL`, and its **gate** (`RAIL_GATE`) is held
**up to the source** by R106 (100 k) — i.e. **off by default**. To turn the rail
ON, something must pull `RAIL_GATE` down to ground. That "something" is three NPN
transistors in series:

```
RAIL_GATE (Q14 P-FET gate, pulled up to source by R106 100k)
    │
    ▼  collector
  Q15  MMBT3904  "AND ARM"     base = ARM_PERMIT (via R107 1k; R108 100k pulldown)
    │  emitter → AND_MID_ARM_RP
    ▼  collector
  Q16  MMBT3904  "AND RP_OK"   base = RP2040_OK (via R109 1k; R110 100k pulldown)
    │  emitter → WDOG_OK_PULLDOWN
    ▼  drain
  Q13  AO3400A   "wdog"        gate = NE555 OUT (via R104; R105 100k pulldown)
    │  source
    ▼
   GND
```

For `RAIL_GATE` to reach ground (turning the P-FET on), **Q15 AND Q16 AND Q13 must
all conduct simultaneously**. That is a literal series-AND:

- **Q15 conducts** only if `ARM_PERMIT` is high (Pi has armed — operator-safe state).
- **Q16 conducts** only if `RP2040_OK` is high (RP2040 healthy *and* no cam-stop
  violation).
- **Q13 conducts** only if the NE555 says "watchdog OK" (Pi is kicking).

Each base/gate has a **100 k pull-down** (R108, R110, R105) so the default state with
no drive is OFF. If any single device is off, the chain is open, R106 holds the gate
at the source, and the P-FET is off → rail dead.

#### 10.4.1 AND-chain + pass-FET — parts and nets

| RefDes | Part / value | LCSC | Pin → net (from netlist) |
|---|---|---|---|
| Q14 | AO3401A P-ch MOSFET (rail pass-FET) | C347476 | **S** (pin2) ← `SAFE_STOP_RETURN`; **G** (pin1) ← `RAIL_GATE`; **D** (pin3) → `RELAY_ENABLE_RAIL` |
| Q15 | MMBT3904 NPN ("AND ARM") | C909754 | **B** (pin1) ← `BASE_AND_ARM`; **E** (pin2) → `AND_MID_ARM_RP`; **C** (pin3) → `RAIL_GATE` |
| Q16 | MMBT3904 NPN ("AND RP_OK") | C909754 | **B** (pin1) ← `BASE_AND_RP_OK`; **E** (pin2) → `WDOG_OK_PULLDOWN`; **C** (pin3) → `AND_MID_ARM_RP` |
| Q13 | AO3400A N-ch MOSFET (watchdog OK) | C20917 | **G** (pin1) ← `WDOG_OK_GATE`; **S** (pin2) → `GND`; **D** (pin3) → `WDOG_OK_PULLDOWN` |
| R106 | 100 k (`R_RAIL_GATE_PULLUP`) | C149504 | pin1 → `SAFE_STOP_RETURN` (source side); pin2 → `RAIL_GATE` |
| R107 | 1 k (`Rb_AND_ARM`) | C17513 | `ARM_PERMIT` → Q15 base |
| R108 | 100 k (`Rpd_AND_ARM`) | C149504 | Q15 base → `GND` (fail-safe pulldown) |
| R109 | 1 k (`Rb_AND_RP_OK`) | C17513 | `RP2040_OK` → Q16 base |
| R110 | 100 k (`Rpd_AND_RP_OK`) | C149504 | Q16 base → `GND` (fail-safe pulldown) |

> **MMBT3904 grouping note.** The PCBA BOM groups Q1,Q2,Q3,Q4,Q5,Q6,**Q15,Q16** on
> one line (8× MMBT3904, C909754); Q1–Q6 are the relay-coil base drivers (§10.5),
> Q15/Q16 are the AND-chain transistors here. The two AO3400A devices (Q12 kick,
> Q13 wdog) share LCSC C20917; the single P-channel pass-FET Q14 is AO3401A
> (C347476). **Q12/Q13/Q14 are visually similar SOT-23 parts — do not swap N-ch and
> P-ch during hand placement.**

#### 10.4.2 The two external NC loops on J_SAFETY (J14)

The safety connector **J14 (J_SAFETY)** is a 4-pin Phoenix MCV terminal. The two
external normally-closed loops are wired **in series** between +5 V and the pass-FET
source:

```
VCC_5V ── J14.1 ──[ external TB/SC interlock NC loop ]── J14.2
                                                          │  (SAFE_TBSC_RETURN: J14.2 ↔ J14.3 on-board jumper net)
                          J14.3 ──[ external Stop/CIS/master NC loop ]── J14.4
                                                                          │
                                                                   SAFE_STOP_RETURN ── Q14 source (+ R106 high side)
```

| J14 pin | Net | Meaning |
|---|---|---|
| 1 | `VCC_5V` | Source feed into the first external loop |
| 2 | `SAFE_TBSC_RETURN` | Return of the **TB/SC interlock** loop; on-board it is the same net as pin 3 |
| 3 | `SAFE_TBSC_RETURN` | Start of the **Stop/CIS/master** loop (jumpered to pin 2 on the board) |
| 4 | `SAFE_STOP_RETURN` | Return of the Stop/CIS loop → pass-FET source (+ R106) |

So: +5 V enters pin 1, must traverse the **closed** TB/SC loop (pins 1→2), cross the
on-board jumper (pin 2 = pin 3, `SAFE_TBSC_RETURN`), traverse the **closed**
Stop/CIS/master loop (pins 3→4), and only then reach the pass-FET source. **Open
either external loop and the FET source is dead** — no gate state can re-enable the
rail. This is condition 5 and condition 6 of §10.3, in hardware, upstream of all
logic.

> **(VERIFY: final electrical form of the J14 loops.)** Spec §4.4 and §11 item 3
> explicitly leave the TB/SC and Stop/CIS **electrical form, polarity, and final
> connector wiring** open pending at-machine verification — the board provides the
> NC-loop *topology* and demands the interlock be a first-class rail condition, but
> the exact field derivation (TB/SC cam contacts vs the existing 24 V control path
> vs a low-voltage isolated loop) is a cutover decision. Wire J14 to **break** the
> loop on the unsafe condition (NC = closed when safe).

---

### 10.5 What the rail gates: the relay coils

`RELAY_ENABLE_RAIL` (net code 141 in `kicad/wsl-phase8b.net`) reaches the **high
side (pin 1) of all seven motion-relay coils** plus their flyback-diode cathodes and
the pass-FET drain. Confirmed nodes on that net:

| RefDes on `RELAY_ENABLE_RAIL` | What it is |
|---|---|
| K1, K2, K3, K4, K5, K6, **K7** | Relay coil pin 1 (high side) for S, T, SP, BE, M, M2, **M1** |
| D1, D3, D5, D7, D9, D11, **D13** | Flyback-diode cathodes across each coil (the odd-numbered 1N4148 + D13 for M1) |
| Q14 pin 3 | Pass-FET drain (the rail's source of supply) |

The relays are **Omron G5LE-14, 5 VDC coil** (`K1`–`K6`, LCSC **C116963**; BOM note:
"Critical: 5VDC coil. Do not substitute 9V/12V/24V coil."). **K7 (M1, ball return)
is DNP** — populate-optional, not bench-confirmed on this chassis (spec §3.2,
§11 item 6); its coil/flyback/driver footprints exist on the rail but are not
assembled by default. Each coil's low side is switched to ground by a per-relay
NPN driver:

| Output | Relay | Coil driver (NPN) | Driver base R / pulldown | Notes |
|---|---|---|---|---|
| S (sweep) | K1 | Q1 (MMBT3904) | R67 (1 k) / R68 (100 k) | |
| T (table) | K2 | Q2 | R70 / R71 | |
| SP (spot) | K3 | Q3 | R73 / R74 | |
| BE (back-end) | K4 | Q4 | R76 / R77 | |
| M (master) | K5 | Q5 | R79 / R80 | |
| M2 (sweep reverse) | K6 | Q6 | R82 / R83 | |
| M1 (ball return) | K7 | Q7 | R88 / R89 | **DNP** — entire channel optional |

**Two gates in series for any motion output.** A relay only energizes if (a) the Pi
sets its `MCP23017 OUT-A` bit, turning on the per-relay NPN to ground the coil low
side, **AND** (b) the rail is live, supplying +5 V to the coil high side. The Pi
controls (a); the six-condition safety rail controls (b). Software alone cannot fire
a coil. (The relay contacts themselves only open/close **existing machine control
circuits** — the board sources no machine coil power and carries no motor current;
see §9, Output Contract, and §10.6.)

> **(VERIFY: relay contact rating headroom.)** Spec §11 item 1 lists "confirm contact
> current/voltage for S/T/SP/BE/M/M2 and whether G5LE-1 margin is sufficient" as an
> open assembly-gate item. The footprint and 5 VDC coil are fixed; the contact-side
> AC-inductive load rating is to be confirmed against measured machine
> control-circuit current before populated-board sign-off.

---

### 10.6 Welded-contact limitation (read before relying on the rail)

The rail de-energizes relay **coils**. It physically **cannot open a relay contact
that has welded closed.** If a contact welds, dropping the rail removes coil drive
but the welded contact stays made — and the machine control circuit it feeds stays
made. Therefore:

- **The relay contact rating, arc suppression, and validation are safety-relevant.**
  Each motion output has DNP footprints for an RC snubber (`Rsnub_*` 100 R + `Csnub_*`
  10 nF X2) and a MOV across the contact, to be populated per output after load
  characterization (spec §2.3 / §3.2). Do not skip suppression on inductive AC
  control loads.
- **The final physical stop is upstream and external.** The existing **master
  circuit breaker / Stop / CIS chain** (cut at the rear-panel master breaker; see §19,
  Safety Model) remains the irreducible kill path — it removes machine control power
  regardless of any welded on-board contact. The rail is a *permission* layer, not a
  *disconnect* layer.
- **Regenerative motor braking stays in machine hardware** (the relay N.C. contacts +
  caps on the machine contactors), independent of this board.

This is why the contract's headline rule (top of this section, and spec §"non-
negotiable safety rule") forbids ever treating this board as the only safety device.

---

### 10.7 Fail-open behavior summary (state table)

How the rail responds to each loss-of-permission event. "Rail" = `RELAY_ENABLE_RAIL`
live? "Coils" = can any motion relay energize?

| Event | Mechanism | Rail | Coils |
|---|---|---|---|
| Pi process hangs / dies (no kicks) | NE555 times out → Q13 off → gate AND open | dead | drop |
| Pi de-asserts ARM (`ARM_PERMIT` low) | Q15 base low (R108) → Q15 off → gate AND open | dead | drop |
| RP2040 unpowered / in reset / BOOTSEL | `GP2` Hi-Z → R110 100 k holds Q16 base low → Q16 off | dead | drop |
| RP2040 firmware crash / loop hang | RP2040 internal WDT resets chip → GP2 Hi-Z → as above | dead | drop |
| RP2040 cam-stop violation / motion max-run timeout | firmware drives `GP2` LOW → Q16 off (condition 4 via 3) | dead | drop |
| TB/SC interlock loop opens (collision course) | J14.1↔2 source loop broken → FET source dead | dead | drop |
| Stop/CIS/master loop opens | J14.3↔4 source loop broken → FET source dead | dead | drop |
| Board powers up (pre-init) | GP2 Hi-Z + ARM low + no kicks → all three defaults off | dead | drop |
| Welded relay contact | rail still drops coils, **but** weld holds the contact | dead | **welded contact stays made → master breaker required (§10.6)** |
| All six conditions true | Q15·Q16·Q13 conduct → gate low → P-FET on; both loops closed | **live** | Pi's OUT-A bit can energize that coil |

The firmware (`firmware/rp2040/README.md` "Safety model") states the same invariant
from the Pico side: GP2 is driven LOW first thing in `main()`, then HIGH only after
`BOOT_SETTLE_MS` (200 ms) and only while no fault; telemetry/UART never block the
RP_OK drive or the watchdog kick; a dead UART cannot produce a false permit.

---

### 10.8 Test points and bench bring-up

The contract requires the watchdog and rail to be **observable** (spec §4.3, §9, §11,
§12.9). Probe these nets (test pads were added at board placement — the route doc and
spec record **16 test pads** total, and call out `TP16` on `RELAY_ENABLE_RAIL`):

| Probe / net | What you are watching | Healthy reading |
|---|---|---|
| `RELAY_ENABLE_RAIL` (TP16) | The gated coil supply rail | ≈ +5 V only when all six conditions true; ≈ 0 V (or pulled to coil-low through coils) otherwise |
| `RAIL_GATE` | P-FET gate | Pulled to source (≈ +5 V, FET off) by default; near GND when the AND chain conducts (FET on) |
| `NE555_TRIG` (U36 pin 2) | Watchdog trigger | Held high by R101; pulsed low by each Pi kick |
| `NE555_OUT` (U36 pin 3) | Watchdog output | Toggles with kicks; reverts (→ Q13 off) on missed kicks |
| `WDOG_OK_PULLDOWN` | Bottom of the AND chain (Q13 drain) | Pulled to GND only while Q13 conducts (watchdog OK) |
| `SAFE_STOP_RETURN` (Q14 source) | After both NC safety loops | ≈ +5 V only when BOTH external loops closed |
| `RP2040_OK` (GP2 / J1 pin 13) | RP2040 health/permission | HIGH = permit, LOW = drop (also drops on cam-stop/timeout) |
| `ARM_PERMIT` (J1 pin 8) | Pi arm GPIO | HIGH only after operator-safe/zeroed state |
| `WDOG_KICK` (J1 pin 7) | Pi kick into Q12 | periodic pulses while the Pi is alive |

**Bench bring-up order** (do this on a **locked-out / off-live** machine only —
spec §12.9, firmware README §"Bench bring-up"):

1. **Power + boot, rail externally safe.** Power board logic only. Confirm RP2040
   `boot` + ~4 Hz `hb` with `ok:1` after ~200 ms; GP2 reads HIGH on a meter once
   healthy.
2. **Watchdog drop.** With ARM asserted and a known-good RP2040, start Pi kicks and
   confirm the rail comes up; **stop the kicks** and confirm the rail drops within
   the timeout. Also pull power to just the Pico → GP2 → LOW → rail drops (`boot`
   with `wdt_reset:1` if you force a hang).
3. **Arm drop.** De-assert `ARM_PERMIT` → Q15 off → rail drops.
4. **Interlock drop.** Open the J14 TB/SC loop, then the J14 Stop/CIS loop, each
   independently → FET source dead → rail drops.
5. **Cam-stop / motion-timeout drop.** Send `RUN S` to the RP2040 and withhold
   `STOP S` past `MAX_MOTION_MS` (8 s) → expect `flt:motion_timeout` and GP2 → LOW →
   rail drops; `CLEAR` → GP2 back HIGH (from a known-safe zero/ready state only).
6. **Each relay with a dummy load**, then — only after all of the above pass — the
   machine harness.

Cross-references: §9 (Output Contract / relay topology), §19 (Safety Model — TB/SC
interlock, Stop/CIS/master breaker, power-down rule), §8 (Input Contract — cams that
feed the RP2040 cam-stop), §7 (Controller Interface — MCP23017 OUT-A relay bits,
RP2040 UART), and the RP2040 firmware section for the `RP2040_OK`/cam-stop semantics.


## 11. Rev-B Connector Pinouts (J1-J14)

This section is the authoritative pin-by-pin reference for every connector on the
Phase 8 Rev-B lane-controller PCB. Every pin, net name, and part number below is
taken directly from the live board sources:

- **`scripts/generate_kicad_netlist_revB.py`** — `block_connectors()`, `block_rail()`,
  `opto_input()`, `relay_output()`, `lamp_led_output()`, `block_rp2040()`. This is
  the generator that *emits the netlist the routed board is built from*, so it is the
  primary source of truth for connectivity and net names.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-cpl.csv`** — the placed
  reference designators (J1..J14) and their footprints.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`**
  and **`...-bom-non-dnp.csv`** / **`...-dnp-excluded.csv`** — the as-ordered part numbers.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-harness-mating-parts.csv`**
  and **`...-offboard-hardware.csv`** — the off-board mating plugs.

If you are reading this cold, read **Section 5 (Electrical Domains)**,
**Section 10 (Safety Rail)**, and **Section 8 (Input Front-Ends)** first — the *why*
behind each pin lives there. This section is the *what*.

> **Cross-references:** firmware GPIO map is in **Section 15 (RP2040 Firmware)**; the
> per-chassis harness that maps these function-named connectors to the AMF 82-70 C1/C2A
> machine connectors is **Section 14 (Adapter Harness & Cutover)**; relay/opto theory is
> **Section 9 (Relay Output Stage)** and **Section 8 (Opto Input Stage)** (adjust numbers
> to match the assembled manual).

---

### 11.0 Why the connectors are function-named (read this first)

The board is **one PCB per lane**. Its connectors are named by *electrical function*
(`J_FAST_IN`, `J_MOTION_S`, `J_SAFETY`, ...), **not** by the machine cavity they will
eventually land on. This is deliberate and non-negotiable per the Rev-B contract
(`phase8b_pcb_revB_spec.md` §1, §7): the OEM AMF wire tables and our bench
measurements on the SS + Omega-Tek retrofit at lanes 21/22 **disagree** on which C1/C2A
cavity carries which signal (e.g. OEM routes sweep-reverse M2 on C1; our bench measured
M2 → C2A direct 0 Ω). Both are correct for their chassis. Baking a cavity number into
copper would make the board single-chassis. Instead:

- **The PCB exposes function-named channels.**
- **A per-chassis adapter harness** maps each channel to the correct C1/C2A cavity at
  cutover. See **Section 14**.

Treat every machine-facing pin in this section as a **field-domain** net (galvanically
isolated from logic ground through an opto or a relay contact) unless it is explicitly a
logic/Pi pin on J1.

#### Connector index

The reference designators (J-numbers) are fixed by the placement file. The board screens
each connector with both its J-number and its function name.

| Ref | Function name | Footprint | Positions | Domain | Mating plug (off-board) |
|---|---|---|---|---|---|
| **J1** | `J_PI` | IDC-Header 2x10, 2.54 mm vertical | 20 | Logic | 2x10 IDC ribbon socket (CNC Tech 3030-20-0102-00 *candidate*) |
| **J2** | `J_PWR 5V` | Phoenix MKDS 1,5/3-5.08, horizontal screw | 3 | Logic power in | Wires land directly in the fixed screw block (no separate plug) |
| **J3** | `J_FAST_IN` | Phoenix MCV 1,5/10-G-3,5 vertical | 10 | Field sense | Phoenix MC 1,5/10-ST-3,5 (PN 1840447) |
| **J4** | `J_SLOW_IN_A` | Phoenix MCV 1,5/14-G-3,5 vertical | 14 | Field sense | Phoenix MC 1,5/14-ST-3,5 (PN 1840489) |
| **J5** | `J_SLOW_IN_B` | Phoenix MCV 1,5/12-G-3,5 vertical | 12 | Field sense | Phoenix MC 1,5/12-ST-3,5 (PN 1840463) |
| **J6** | `J_MOTION_S` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | Wires land directly in the fixed screw block |
| **J7** | `J_MOTION_T` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J8** | `J_MOTION_SP` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J9** | `J_MOTION_BE` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J10** | `J_MOTION_M` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J11** | `J_MOTION_M2` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J12** | `J_MOTION_M1` **(DNP)** | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | **NOT POPULATED** — footprint only |
| **J13** | `J_LAMP_LED` | Phoenix MCV 1,5/6-G-3,5 vertical | 6 | Logic (LED drive) | Phoenix MC 1,5/6-ST-3,5 (PN 1840405) |
| **J14** | `J_SAFETY` | Phoenix MCV 1,5/4-G-3,5 vertical | 4 | Safety rail (interlock loops) | Phoenix MC 1,5/4-ST-3,5 (PN 1840382) |

> **J12 is the only DNP connector.** The M1 (ball-return) channel — connector J12, relay
> K7, driver Q7, R85/R86/R87, D13/D14, snubber C10 — is **Do Not Populate**. The FSM does
> not drive a ball-return relay and M1 was never bench-confirmed as a separate command on
> our chassis (`phase8b_pcb_revB_spec.md` §3.2, §11 item 6). The copper exists for a future
> chassis; do not stuff it until verified at-machine. It is excluded from the BOM and
> pick-and-place files. All other J-numbers are populated.

> **Footprint-vs-mating-plug note.** The two-row Pi header (J1) and the 3.5 mm field
> connectors (J3/J4/J5/J13/J14) are *pluggable* — they need a mating plug (right-hand
> column). The 5.08 mm blocks (J2 and all J_MOTION_*) are *fixed screw terminals*: bare
> wire lands directly under the screw, no plug. Order the Phoenix `...-ST-3,5` plugs with
> the harness, one of each per board.

---

### 11.1 Domain & polarity conventions used in these tables

These conventions hold across every table below. They come from `opto_input()`,
`relay_output()`, `lamp_led_output()`, and `block_rail()` in the generator, and from
`firmware/rp2040/config.h` / `lane_node/controller_io.py`.

- **Direction** is given from the **board's** point of view:
  *IN* = signal flows into the board (a field sense), *OUT* = board drives/contacts out,
  *PWR* = power into the board, *BIDIR* = bidirectional bus (I2C).
- **Domain** is one of: **LOGIC** (3.3 V / 5 V referenced to logic GND), **FIELD**
  (machine-side, referenced to `FIELD_GND`, isolated from logic by the opto), **MACHINE
  OUTPUT** (a floating relay dry contact), or **SAFETY** (the relay-enable interlock loop).
- **All field inputs are dry-contact wetting by default.** Each input opto LED is fed from
  the isolated `FIELD_WET_V` rail (the TMA-0505S, U37, ~5 V isolated) through a 2.2 kΩ
  series resistor (`Rin`), and the field contact, when **closed**, returns that pin to
  `FIELD_GND` and lights the opto LED. So a **closed machine contact = opto ON**. See
  Section 5 / Section 10 for the optional 24 VAC-sense population. `FIELD_GND` and logic
  `GND` share **zero** nodes on the board — the isolation barrier is intact.
- **All opto outputs are ACTIVE-LOW at the controller.** The opto transistor pulls the
  logic pin LOW when its LED is on (contact closed). Idle = HIGH via an on-board 10 kΩ
  pull-up to 3V3 (`Rpu`). Firmware (`config.h`) and `controller_io.py`
  (`INPUT_ACTIVE_LOW = True`) both invert this: **asserted/closed reads logical 1.**
- **Relay contacts are isolated dry NO contacts.** For every `J_MOTION_*`: **pin 2 = COM**
  (`OUT_x_A`, relay pad 3), **pin 1 = NO** (`OUT_x_B`, relay pad 4). The board never sources
  the voltage on these pins; the machine control circuit does. The contact closes only when
  (a) the FSM commands the bit AND (b) the hardware safety rail is up (Section 10).

---

### 11.2 J1 — `J_PI` (Pi logic interface, 2x10 IDC, 2.54 mm)

This is the only link to the Raspberry Pi. It carries the I2C bus to the three MCP23017
expanders, the UART to the RP2040, the watchdog kick, the arm-permit line, both MCP
interrupt lines, the RP2040-OK rail-permission line, and both logic rails. The footprint
is `Connector_Generic:Conn_02x10_Odd_Even` → **KiCad odd/even numbering**: odd pins
(1,3,5,…,19) run down one row, even pins (2,4,6,…,20) down the other, with pin 1 and pin 2
side-by-side at the pin-1 end of the header.

The generator wires **pins 1–13**; **pins 14–20 are no-connect** (reserved).

| Pin | Signal | Net name | Dir (board) | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V logic | `VCC_5V` | PWR in | LOGIC | Main 5 V rail (also fed by J2 through reverse-prot diode D17). |
| 2 | Logic ground | `GND` | — | LOGIC | |
| 3 | I2C SDA | `I2C_SDA` | BIDIR | LOGIC | 3.3 V bus; 4.7 kΩ pull-up to 3V3 on board (R1). MCP23017 ×3. |
| 4 | I2C SCL | `I2C_SCL` | BIDIR | LOGIC | 3.3 V bus; 4.7 kΩ pull-up to 3V3 on board (R2). |
| 5 | Pi UART TX → Pico RX | `PI_UART_TX` | IN | LOGIC | Pi transmit → RP2040 GP1 (Pico pin 2). 115200 8N1. |
| 6 | Pi UART RX ← Pico TX | `PI_UART_RX` | OUT | LOGIC | RP2040 GP0 (Pico pin 1) → Pi receive. |
| 7 | Watchdog kick | `WDOG_KICK` | IN | LOGIC | Pi pulse that re-triggers the NE555 monostable (U36). Missing kick → rail drops. |
| 8 | Arm permit | `ARM_PERMIT` | IN | LOGIC | Pi GPIO; one series condition of the relay-enable rail. HIGH = permit. |
| 9 | MCP INT-A | `MCP_INT_A` | OUT | LOGIC | Interrupt from MCP23017 IN-A (U1, INTA pin 20). Optional. |
| 10 | MCP INT-B | `MCP_INT_B` | OUT | LOGIC | Interrupt from MCP23017 IN-B (U2, INTA pin 20). Optional. |
| 11 | +3.3 V logic | `VCC_3V3` | PWR | LOGIC | 3.3 V rail (sourced by the Pico's onboard regulator, Pico pin 36). Powers the MCPs + opto logic side. |
| 12 | Logic ground | `GND` | — | LOGIC | Second GND for ribbon return integrity. |
| 13 | RP2040 OK | `RP2040_OK` | OUT | LOGIC/SAFETY | RP2040 GP2 health/permission. HIGH = permit motion, LOW = drop rail. Hard rail condition (Section 10). |
| 14–20 | *(no connect)* | — | — | — | Reserved; not wired by the generator. |

**Operating theory.** J1 is split across two responsibilities. Pins 3/4 (I2C) and 9/10
(INT) are the *slow* path: the Pi talks to the three MCP23017s to read slow switches and
drive the relay/lamp command bits. Pins 5/6 (UART) are the *fast/safety* path: the RP2040
co-processor owns the cam and ball-detect inputs and streams events to the Pi, while
**independently** holding pin 13 (`RP2040_OK`) high only while its firmware is alive and no
cam-stop/max-run fault is latched. Pins 7 (`WDOG_KICK`), 8 (`ARM_PERMIT`), and 13
(`RP2040_OK`) are three of the series conditions that must *all* be true for the
relay-enable rail to come up — the Pi cannot energize a motion relay in software alone.

> **UART naming gotcha (do not crosswire).** The net names are from the *Pi's*
> perspective. `PI_UART_TX` (pin 5) is the Pi's transmit; on the board it lands on the
> Pico's **RX** (GP1). `PI_UART_RX` (pin 6) is the Pi's receive; on the board it lands on
> the Pico's **TX** (GP0). `config.h` confirms: `PIN_UART_TX 0 (GP0) → Pi RX, net PI_UART_RX`
> and `PIN_UART_RX 1 (GP1) ← Pi TX, net PI_UART_TX`. The crossover is already done on the
> PCB; wire the ribbon straight-through.

> **(VERIFY: ribbon pin-1 / keying convention.)** The placed footprint defines the pad
> numbers above, but the *physical ribbon orientation* (which conductor is pin 1, shroud
> keying) is flagged "confirm cable keying/orientation" in the working BOM and the J1
> mating-plug row is a "candidate." Confirm pin-1 alignment between board and Pi before
> crimping the ribbon.

---

### 11.3 J2 — `J_PWR 5V` (regulated 5 V input, 3-pin screw, 5.08 mm)

External regulated 5 V enters here. This rail powers the logic (Pico, MCP23017s, NE555),
the opto logic sides, the isolated field-wetting DC/DC (U37), the relay coils, and the
status LEDs. Two ground pins are provided for current return.

| Pin | Signal | Net name | Dir (board) | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V raw in | `VCC_5V_RAW` | PWR in | LOGIC | Feeds the board through reverse-polarity Schottky D17 (SS14). |
| 2 | Ground | `GND` | — | LOGIC | |
| 3 | Ground | `GND` | — | LOGIC | Second return pin for coil/LED current. |

**Operating theory.** `VCC_5V_RAW` (pin 1) passes through series Schottky **D17 (SS14)**
to become the protected `VCC_5V` rail (D17 anode = RAW, cathode = `VCC_5V`). This blocks
reverse-polarity damage at the cost of ~0.4 V drop, so the on-board 5 V rail sits slightly
below the supply. `VCC_5V` and the J1 pin-1 5 V are the **same net** after the diode — do
not feed 5 V into both J1 and J2 from two different supplies. Size the supply for
worst-case simultaneous relay coil load (6 populated G5LE coils ≈ 6 × ~40 mA) + logic +
LEDs + margin (`phase8b_pcb_revB_spec.md` §8.1, §11 item 2).

> **(VERIFY: 5 V supply current budget.)** The spec lists "relay coil rail budget"
> (worst-case relay count incl. any M1 decision) as an open assembly-blocking item; the
> exact supply sizing is not pinned in the sources.

---

### 11.4 J3 — `J_FAST_IN` (RP2040 fast inputs, 10-pin, 3.5 mm)

The eight fast machine signals the **RP2040** services directly: sweep cams, table cams,
the two interlock-cam echoes, and the two DIELL ball-detect beams. Each lands on a PC817
opto front-end and then on a Pico GPIO. These are the timing-critical, edge-capable inputs;
they must not get slow RC/firmware debounce that masks cam overlap (Section 5.1).

Pin order follows `FAST_INPUTS` in the generator. Pins 9–10 are the isolated field-ground
return for the dry-contact wetting.

| Pin | Signal | Field net | Logic net | Pico GPIO (pin) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | SA | `FIELD_FAST_SA` | `FAST_SA` | GP6 (Pico 9) | IN | FIELD | Sweep cam (270 run-through stop / 360 zero). |
| 2 | SB | `FIELD_FAST_SB` | `FAST_SB` | GP7 (Pico 10) | IN | FIELD | Sweep guard cam (66 guard / 186 table-spot init). |
| 3 | SC | `FIELD_FAST_SC` | `FAST_SC` | GP8 (Pico 11) | IN | FIELD | Sweep-under-table interlock window (86–243); also the SC interlock echo. |
| 4 | TA1 | `FIELD_FAST_TA1` | `FAST_TA1` | GP9 (Pico 12) | IN | FIELD | Table cam (355 zero stop / 185 delay reset). |
| 5 | TA2 | `FIELD_FAST_TA2` | `FAST_TA2` | GP10 (Pico 14) | IN | FIELD | Table cam (260 run-through / pin-latch / decision). |
| 6 | TB | `FIELD_FAST_TB` | `FAST_TB` | GP11 (Pico 15) | IN | FIELD | Table-sweep interference interlock cam (105–255). |
| 7 | DIELL-L | `FIELD_FAST_DIELL_L` | `FAST_DIELL_L` | GP12 (Pico 16) | IN | FIELD | Ball detect, left beam (cushion SS cycle trigger). |
| 8 | DIELL-R | `FIELD_FAST_DIELL_R` | `FAST_DIELL_R` | GP13 (Pico 17) | IN | FIELD | Ball detect, right beam. |
| 9 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return (shared with pin 10). |
| 10 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return. |

**Operating theory.** Each fast channel is one PC817 (U4…U11) wired by `opto_input()`:
`FIELD_WET_V` → 2.2 kΩ (`Rin`) → opto LED anode; opto LED cathode → the J3 field pin. The
machine contact (a cam microswitch) between that pin and `FIELD_GND` (pins 9/10) completes
the LED loop when closed, turning the opto on and pulling the Pico GPIO LOW through the
transistor; idle is held HIGH by a 10 kΩ pull-up to 3V3 (`Rpu`). The RP2040 reads these
edges with a 2 ms cam debounce / 500 µs DIELL debounce (`config.h`), enforces cam-stop and
an 8 s motion max-run backstop, and forwards events to the Pi over the J1 UART. **Because
the RP2040 owns these and gates `RP2040_OK`, a fault on a fast input drops the motion rail
in hardware, not just in software.**

> **GPIO source-of-truth note.** The Pico GPIO column above is from `block_rp2040()` /
> `config.h` (GP6–GP13). The older `docs/phase8_channel_allocation.md` §2 GPIO column
> (GP0–GP7) is **STALE** and must be ignored — `config.h` says so explicitly.

> **(VERIFY: per-channel input population — dry-contact vs 24 VAC sense.)** The tables show
> the **default dry-contact wetting** front-end. The Rev-B contract requires choosing
> dry-contact vs 24 VAC-rectified sense *per channel* after at-machine measurement
> (`phase8b_pcb_revB_spec.md` §5.1, §5.3, §11 item 4). Not yet locked.

---

### 11.5 J4 — `J_SLOW_IN_A` (MCP IN-A slow inputs, 14-pin, 3.5 mm)

The high-use slow inputs read by **MCP23017 IN-A (U1, I2C 0x20)**: the ten gripper switches
plus gripper-protect, off-spot, and bin/#9. Same dry-contact opto front-end as J3, but the
logic side lands on MCP23017 GPA/GPB pins instead of the Pico. Pin order follows
`slowa_order` in the generator; pin 14 is the field-ground return.

| Pin | Signal | Field net | Logic net | MCP IN-A pin (port,bit) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | GS1 | `FIELD_SLOW_GS1` | `SLOW_GS1` | 21 (GPA0) | IN | FIELD | Gripper switch 1 (standing-pin sense, bit 0). |
| 2 | GS2 | `FIELD_SLOW_GS2` | `SLOW_GS2` | 22 (GPA1) | IN | FIELD | Gripper switch 2. |
| 3 | GS3 | `FIELD_SLOW_GS3` | `SLOW_GS3` | 23 (GPA2) | IN | FIELD | Gripper switch 3. |
| 4 | GS4 | `FIELD_SLOW_GS4` | `SLOW_GS4` | 24 (GPA3) | IN | FIELD | Gripper switch 4. |
| 5 | GS5 | `FIELD_SLOW_GS5` | `SLOW_GS5` | 25 (GPA4) | IN | FIELD | Gripper switch 5. |
| 6 | GS6 | `FIELD_SLOW_GS6` | `SLOW_GS6` | 26 (GPA5) | IN | FIELD | Gripper switch 6. |
| 7 | GS7 | `FIELD_SLOW_GS7` | `SLOW_GS7` | 27 (GPA6) | IN | FIELD | Gripper switch 7. |
| 8 | GS8 | `FIELD_SLOW_GS8` | `SLOW_GS8` | 28 (GPA7) | IN | FIELD | Gripper switch 8. |
| 9 | GS9 | `FIELD_SLOW_GS9` | `SLOW_GS9` | 1 (GPB0) | IN | FIELD | Gripper switch 9. |
| 10 | GS10 | `FIELD_SLOW_GS10` | `SLOW_GS10` | 2 (GPB1) | IN | FIELD | Gripper switch 10. |
| 11 | GP | `FIELD_SLOW_GP` | `SLOW_GP` | 3 (GPB2) | IN | FIELD | Gripper protect. |
| 12 | OS | `FIELD_SLOW_OS` | `SLOW_OS` | 4 (GPB3) | IN | FIELD | Off-spot. |
| 13 | BS | `FIELD_SLOW_BS` | `SLOW_BS` | 5 (GPB4) | IN | FIELD | Bin / #9 (back-stop / bin-full). |
| 14 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return for J4. |

**Operating theory.** Identical front-end to J3 (`opto_input()` → PC817 U12…U24), but the
opto transistors drive **MCP23017 IN-A** pins instead of the Pico. The Pi reads the whole
bank over I2C. The ten GS bits form the **standing-pin mask** the scoring/FSM logic uses;
`controller_io.py read_grippers()` slices `GS1=bit0 … GS10=bit9`, treating a *closed* opto
(pin reads 0, active-low) as a *standing* pin. GP/OS/BS are individual reads. None of these
are on the safety rail — they are sense-only.

> **Bit-map alignment.** The (port,bit) column equals `lane_node/controller_io.py`
> `IN_A_MAP`, which is regression-locked against `SLOW_INPUT_PINS` in the generator (the
> module's `__main__` self-test fails on drift). MCP pin → (port,bit): pins 21–28 = GPA0–7
> = (0,0)…(0,7); pins 1–8 = GPB0–7 = (1,0)…(1,7).

> **(VERIFY: per-channel dry-contact vs 24 VAC population)** — same open item as J3.

---

### 11.6 J5 — `J_SLOW_IN_B` (MCP IN-B slow inputs, 12-pin, 3.5 mm)

Manual-operation, 10th-frame, foul, pushbutton, and spare slow inputs, read by **MCP23017
IN-B (U2, I2C 0x21)**. Pin order follows `slowb_order` in the generator; pin 12 is the
field-ground return. (IN-B is configured on the board but is not yet *read* by the current
FSM — see `controller_io.py`.)

| Pin | Signal | Field net | Logic net | MCP IN-B pin (port,bit) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | PBZ | `FIELD_SLOW_PBZ` | `SLOW_PBZ` | 21 (GPA0) | IN | FIELD | First-ball / zero / manual-intervention pushbutton. |
| 2 | PBC | `FIELD_SLOW_PBC` | `SLOW_PBC` | 22 (GPA1) | IN | FIELD | Cycle pushbutton. |
| 3 | FOUL | `FIELD_SLOW_FOUL` | `SLOW_FOUL` | 23 (GPA2) | IN | FIELD | Foul-line detector. |
| 4 | TENTH | `FIELD_SLOW_TENTH` | `SLOW_TENTH` | 24 (GPA3) | IN | FIELD | 10th-frame signal. |
| 5 | MAN_T | `FIELD_SLOW_MAN_T` | `SLOW_MAN_T` | 25 (GPA4) | IN | FIELD | Manual table. |
| 6 | MAN_S | `FIELD_SLOW_MAN_S` | `SLOW_MAN_S` | 26 (GPA5) | IN | FIELD | Manual sweep. |
| 7 | MAN_SWS | `FIELD_SLOW_MAN_SWS` | `SLOW_MAN_SWS` | 27 (GPA6) | IN | FIELD | Manual sweep-switch. |
| 8 | MAN_SWSR | `FIELD_SLOW_MAN_SWSR` | `SLOW_MAN_SWSR` | 28 (GPA7) | IN | FIELD | Manual sweep-reverse. |
| 9 | AUX1 | `FIELD_SLOW_AUX1` | `SLOW_AUX1` | 1 (GPB0) | IN | FIELD | Spare input. |
| 10 | AUX2 | `FIELD_SLOW_AUX2` | `SLOW_AUX2` | 2 (GPB1) | IN | FIELD | Spare input. |
| 11 | AUX3 | `FIELD_SLOW_AUX3` | `SLOW_AUX3` | 3 (GPB2) | IN | FIELD | Spare input. |
| 12 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return for J5. |

**Operating theory.** Same dry-contact opto front-end (PC817 U25…U35) feeding MCP23017
IN-B. AUX1–AUX3 are deliberately spare for machine-specific discoveries at cutover so that
a newly-found switch does not force a board respin. The three manual-* lines exist so a
service tech's manual table/sweep/sweep-switch/sweep-reverse actuations are visible to the
Pi.

> **(VERIFY: per-channel dry-contact vs 24 VAC population)** — same open item as J3/J4.

---

### 11.7 J6–J12 — `J_MOTION_*` (isolated relay dry contacts, 2-pin each, 5.08 mm)

Each motion/control output is its own **2-pin fixed screw block** carrying one **isolated
SPDT relay's COM + NO** dry contact (Omron **G5LE-14, 5 VDC coil**). One terminal per
function keeps inter-channel creepage and lets the harness land each on the correct C1/C2A
cavity independently. **The board never sources the voltage across these contacts** — it
only opens/closes a contact in an existing machine control circuit, and only while the
safety rail is up.

**Pin convention (identical for every J_MOTION_*):**

| Pin | Signal | Net (example, S) | Relay pad | Dir | Domain | Notes |
|---|---|---|---|---|---|---|
| 1 | Relay **NO** (normally-open) | `OUT_S_B` | K-pad 4 (NO) | OUT | MACHINE OUTPUT | Open when de-energized; closes to COM when commanded + rail up. |
| 2 | Relay **COM** (common) | `OUT_S_A` | K-pad 3 (COM) | OUT | MACHINE OUTPUT | The contact common. |

> **Pin 1 = NO, Pin 2 = COM** on *all* J_MOTION_* blocks. This comes straight from
> `block_connectors()`: `b += j_motion[name][1]` (pin 1 = `OUT_x_B`) and
> `a += j_motion[name][2]` (pin 2 = `OUT_x_A`); and from `relay_output()`:
> `relay[3] += out_a` (COM) and `relay[4] += out_b` (NO). Pads sit in the same vertical
> order as the G5LE contact (B above A).

**Per-connector function map (the only thing that differs between J6–J12):**

| Ref | Function | NO net (pin 1) | COM net (pin 2) | Relay | Driver | MCP OUT-A bit | Populated? |
|---|---|---|---|---|---|---|---|
| **J6** | **S** — sweep motor contactor command | `OUT_S_B` | `OUT_S_A` | K1 | Q1 (MMBT3904) | pin 21, GPA0 (0,0) | yes |
| **J7** | **T** — table motor contactor command | `OUT_T_B` | `OUT_T_A` | K2 | Q2 | pin 22, GPA1 (0,1) | yes |
| **J8** | **SP** — spot solenoid command | `OUT_SP_B` | `OUT_SP_A` | K3 | Q3 | pin 23, GPA2 (0,2) | yes |
| **J9** | **BE** — back-end command | `OUT_BE_B` | `OUT_BE_A` | K4 | Q4 | pin 24, GPA3 (0,3) | yes |
| **J10** | **M** — master / control command | `OUT_M_B` | `OUT_M_A` | K5 | Q5 | pin 25, GPA4 (0,4) | yes |
| **J11** | **M2** — sweep-reverse command | `OUT_M2_B` | `OUT_M2_A` | K6 | Q6 | pin 26, GPA5 (0,5) | yes |
| **J12** | **M1** — ball-return command | `OUT_M1_B` | `OUT_M1_A` | K7 *(DNP)* | Q7 *(DNP)* | pin 27, GPA6 (0,6) | **DNP** |

> **MCP OUT-A bit column** is from `OUTPUT_PINS` in the generator and matches
> `controller_io.py OUT_A_MAP`. Note the **M2-before-M1 ordering** (M2 = bit 5 / pin 26,
> M1 = bit 6 / pin 27) — this was a real bug-class that Codex caught and the maps were
> corrected to agree with the netlist. MCP pin → (port,bit): 21–28 = GPA0–7.

**Operating theory.** Each output is built by `relay_output()`: an MCP23017 OUT-A bit
drives `DRV_x` → 1 kΩ base resistor (`Rb`) → MMBT3904 NPN base (with a 100 kΩ
pull-down so the relay is **off** whenever the MCP pin floats/resets). The NPN sinks the
relay's low-side coil; the coil **high side is `RELAY_ENABLE_RAIL`**, not raw 5 V. So a
relay energizes only when *both* the FSM sets the bit *and* the safety rail (Section 10) is
holding `RELAY_ENABLE_RAIL` up. A flyback diode (1N4148) clamps the coil. Across the dry
contact, each output has **DNP footprints for arc suppression** — an RC snubber
(`Rsnub` 100 R + `Csnub` 10 nF X2) and a MOV — to be populated per output after the actual
inductive AC control load is characterized (`phase8b_pcb_revB_spec.md` §2.3, §3.2).

> **Safety-critical wiring rule.** S and T must command the *existing* contactor/relay
> control coils through these isolated contacts; they must **not** become the motor
> contactor or the de-energized braking path. Motor current never crosses the PCB
> (`phase8b_pcb_revB_spec.md` §3.1). The rail dropping de-energizes the *coil*; it cannot
> open a **welded** contact — the upstream master breaker / Stop / CIS chain is the final
> physical stop (§4.5).

> **(VERIFY: relay contact rating headroom.)** Whether the G5LE-14 contact rating is
> sufficient for the measured S/T/SP/BE/M/M2 control loads is an open assembly-blocking
> item (`phase8b_pcb_revB_spec.md` §3.2, §11 item 1). Size from measured coil/control
> current before populating.

> **(VERIFY: M2 sweep-reverse interlock preservation.)** Regardless of which cavity M2
> lands on, the OEM Expander note requires the sweep-reverse path to keep its
> motor-start/reverse interlock and shorting-plug termination. The *harness* must preserve
> that function (`phase8b_pcb_revB_spec.md` §3.2); it is not on the PCB.

---

### 11.8 J13 — `J_LAMP_LED` (status-LED drive, 6-pin, 3.5 mm)

Drives the four mask status LEDs (1st-ball, 2nd-ball, strike, foul) that Dylan installs in
the existing mask housings. **These are NOT machine-isolated** — the Rev-B decision is to
drive board-supplied LEDs from `VCC_5V` logic power through low-side FET sinks, abandoning
the machine's 15 VDC mask-lamp supply. There is intentionally **no LOGIC↔MACHINE isolation
barrier** on these four returns. They are **not** on the safety rail.

| Pin | Signal | Net | Driver FET | MCP OUT-A bit | Dir | Domain | Notes |
|---|---|---|---|---|---|---|---|
| 1 | +5 V LED supply | `VCC_5V` | — | — | PWR out | LOGIC | Common anode feed for all four LEDs. |
| 2 | Logic ground | `GND` | — | — | — | LOGIC | |
| 3 | L_FIRST return | `LED_L_FIRST_RETURN` | Q8 (2N7002) | pin 28, GPA7 (0,7) | OUT (sink) | LOGIC | 1st-ball lamp. Low-side sink; current set by 330 R (R90). |
| 4 | L_SECOND return | `LED_L_SECOND_RETURN` | Q9 | pin 1, GPB0 (1,0) | OUT (sink) | LOGIC | 2nd-ball lamp. 330 R (R93). |
| 5 | L_STRIKE return | `LED_L_STRIKE_RETURN` | Q10 | pin 2, GPB1 (1,1) | OUT (sink) | LOGIC | Strike lamp. 330 R (R96). |
| 6 | L_FOUL return | `LED_L_FOUL_RETURN` | Q11 | pin 3, GPB2 (1,2) | OUT (sink) | LOGIC | Foul lamp. 330 R (R99). |

**Operating theory.** Wire each external LED **anode to pin 1 (`VCC_5V`)** and its
**cathode to its return pin (3/4/5/6)**. Inside the board, `lamp_led_output()` puts a
330 Ω current-limit resistor (`Rled`) in series with each return, then a low-side 2N7002
N-MOSFET to GND, gated by an MCP23017 OUT-A bit through a 1 kΩ gate resistor (with a 100 kΩ
gate pull-down so the LED is **off** on reset/float). Setting the OUT-A bit turns the FET
on, sinks the LED return to GND, and lights the lamp. The bit assignments
(`L_FIRST`=GPA7 … `L_FOUL`=GPB2) match `OUT_A_MAP` (`first_ball/second_ball/strike/foul`).

> **(VERIFY: mask LED type + current-limit value.)** The 330 Ω (`Rled_*`) is a scaffold
> placeholder. The actual LED type and per-channel resistor for bowling-center brightness
> are an open assembly item (`phase8b_pcb_revB_spec.md` §3.3, §11 item 5). Confirm before
> populating R90/R93/R96/R99.

---

### 11.9 J14 — `J_SAFETY` (hardware interlock loops, 4-pin, 3.5 mm)

The two external normally-closed (NC) hardware interlock loops, wired **in series** between
`VCC_5V` and the gate of the relay-enable pass-FET. This is the part of the safety rail that
**no software can bypass**: if either loop opens, the pass-FET gate loses its pull and the
relay-enable rail collapses, de-energizing every motion-output relay coil. Per the contract,
these are the **TB/SC interference interlock** loop and the **Stop / CIS / master chain**
loop (`phase8b_pcb_revB_spec.md` §4.1, §4.4).

| Pin | Signal | Net | Dir | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V loop source | `VCC_5V` | OUT | SAFETY | Start of the series interlock string. |
| 2 | TB/SC loop return → next loop | `SAFE_TBSC_RETURN` | IN/OUT | SAFETY | Far end of the **TB/SC** NC loop; jumpers internally to pin 3. |
| 3 | Stop/CIS loop source | `SAFE_TBSC_RETURN` | IN/OUT | SAFETY | Same net as pin 2 — start of the **Stop/CIS/master** NC loop. |
| 4 | Stop/CIS loop return → pass-FET source | `SAFE_STOP_RETURN` | IN | SAFETY | Far end of the second loop; lands on the AO3401A (Q14) source + gate pull-up. |

**Operating theory.** `block_rail()` wires this as two NC loops in series:
`VCC_5V` (pin 1) → external TB/SC contacts → pin 2; pins 2 and 3 are the **same board net**
(`SAFE_TBSC_RETURN`), so the string continues out pin 3 → external Stop/CIS/master contacts
→ pin 4 (`SAFE_STOP_RETURN`). Pin 4 feeds the **source of P-channel pass-FET Q14
(AO3401A)** and a 100 kΩ gate pull-up. The pass-FET drain is `RELAY_ENABLE_RAIL`. Q14 only
conducts (rail up) when pin 4 is at ~5 V — i.e. **both** external loops are closed —
**and** the gate is pulled low by the downstream AND chain of two MMBT3904 NPNs gated by
`ARM_PERMIT`, `RP2040_OK`, and the NE555 watchdog-OK pull-down. Any one false condition
(open interlock loop, de-asserted arm, RP2040 unhealthy, or missing watchdog kick) leaves
the rail dead and the motion relays open. This is the electrical realization of the
"non-bypassable hardware safety rail" in the one-sentence contract (§13).

> **Connect the external loops correctly.** Pins 1↔2 are the **TB/SC** NC loop; pins 3↔4
> are the **Stop/CIS/master** NC loop. They are in series, so an open in either kills the
> rail. Do **not** jumper pin 1→4 to "make it work" during bench bring-up — that defeats
> the interlock. For a bench test with no machine loops, jumper 1–2 and 3–4 *only* on a
> locked-out/off-live machine, and remove the jumpers before cutover.

> **(VERIFY: TB/SC + Stop/CIS electrical form and polarity.)** The exact electrical
> derivation of the TB/SC and Stop/CIS loops (cam contacts vs the 24 V control path vs a
> low-voltage isolated loop) and the final connector polarity are an open
> assembly/cutover item (`phase8b_pcb_revB_spec.md` §4.4, §11 item 3). The board makes the
> interlock a first-class rail condition; the *source* of the loop is harness-resolved at
> the machine.

---

### 11.10 Test points related to connector signals (reference)

For bench bring-up, the board exposes test pads (excluded from BOM/POS) that expose the
rails and safety-chain nodes that the connectors above carry. Useful when verifying a
connector is live:

| TP | Net | Relevant to |
|---|---|---|
| TP1 | `VCC_5V` | J1 pin 1, J2, J13 pin 1 |
| TP2 | `GND` | logic ground |
| TP3 | `VCC_3V3` | J1 pin 11 (I2C / opto logic rail) |
| TP4 | `FIELD_WET_V` | isolated wetting source for J3/J4/J5 optos |
| TP5 | `FIELD_GND` | J3 pin 9/10, J4 pin 14, J5 pin 12 |
| TP6 / TP7 | `I2C_SDA` / `I2C_SCL` | J1 pins 3 / 4 |
| TP8 | `WDOG_KICK` | J1 pin 7 |
| TP13 | `ARM_PERMIT` | J1 pin 8 |
| TP14 | `RP2040_OK` | J1 pin 13 |
| TP15 | `SAFE_STOP_RETURN` | J14 pin 4 |
| TP16 | `RELAY_ENABLE_RAIL` | the rail that energizes every J_MOTION_* relay coil |

(TP9–TP12 expose the NE555 watchdog internals — `WDOG_TIMING_NODE`, `NE555_TRIG`,
`NE555_OUT`, `WDOG_OK_PULLDOWN` — see the watchdog section of this manual.)

---

### 11.11 Connector parts & board summary (as ordered)

Confirmed from the BOM/CPL/mating-parts CSVs:

| Item | Value / part | Source |
|---|---|---|
| Board size | **250 × 225 mm**, **4 copper layers** | `phase8b_pcb_revB_spec.md` |
| Relay (×6 populated, K1–K6; K7 DNP) | **Omron G5LE-14, 5 VDC coil** — LCSC **C116963** | PCBA BOM |
| Opto (×32, U4–U35) | **PC817B**, DIP-4 7.62 mm — LCSC **C5692981** | PCBA BOM |
| I/O expander (×3, U1–U3) | **MCP23017-E/SO** (I2C, **not** SPI MCP23S17) — LCSC **C47023** | PCBA BOM |
| Watchdog timer (U36) | **NE555DR** (bipolar 555, **not** CMOS/TLC555) — LCSC **C7593** | PCBA BOM |
| Isolated field-wetting DC/DC (U37) | **TRACO TMA-0505S** (5 V→5 V, 1 W, isolated) | working BOM |
| Reverse-polarity diode (D17) | **SS14** Schottky — LCSC **C2480** | PCBA BOM |
| Relay driver (Q1–Q6; Q7 DNP) | **MMBT3904** NPN, SOT-23 — LCSC **C909754** | PCBA BOM |
| LED driver (Q8–Q11) | **2N7002** N-MOSFET, SOT-23 — LCSC **C916396** | PCBA BOM |
| J1 mating | 2x10 IDC ribbon socket — CNC Tech 3030-20-0102-00 *(candidate)* | mating-parts |
| J3/J4/J5/J13/J14 mating | Phoenix **MC 1,5/x-ST-3,5** plugs (PN 1840447 / 1840489 / 1840463 / 1840405 / 1840382) | mating-parts |
| J2 + J6–J12 | Phoenix **MKDS 1,5** fixed screw blocks (wire-direct, no plug) | CPL / working BOM |

> **Do-not-substitute callouts (from the BOM Notes):** the relay coil **must** be 5 VDC
> (not 9/12/24 V); the I/O expander **must** be the I2C MCP23017 (not the SPI MCP23S17);
> the timer **must** be a bipolar 555 (changing to CMOS alters the watchdog timing).


## 12. Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps

> **Purpose of this section.** This is the authoritative wiring reference for the Rev-B integrated lane-controller board: which physical Raspberry Pi Pico (RP2040) pin carries which machine signal, and which bit of which MCP23017 I²C expander drives or reads which relay/lamp/switch. If you are tracing a dead cam input, a stuck relay, or a wrong lamp on a real machine, **start here.** Every fact in this section is grounded in three live source files that the as-built board and the running firmware are generated from / compiled from:
>
> | File (relative to repo root `wsl-lane-nodes/`) | Role | What it defines |
> |---|---|---|
> | `scripts/generate_kicad_netlist_revB.py` | **PCB netlist generator — the board is physically wired from this.** | `FAST_INPUTS`, `SLOW_INPUT_PINS`, `OUTPUT_PINS`, all part footprints, all nets. |
> | `firmware/rp2040/config.h` | **RP2040 firmware pin contract — the Pico is flashed against this.** | `PIN_*` GPIO numbers, UART baud, debounce/watchdog timing. |
> | `lane_node/controller_io.py` | **Pi-side I/O driver — the FSM talks to the MCP23017s through this.** | `OUT_A_MAP`, `IN_A_MAP`, MCP I²C addresses, active-low convention. |
>
> These three agree by design. `controller_io.py` even contains a self-test (run `python lane_node/controller_io.py`) that re-parses `OUTPUT_PINS` and `SLOW_INPUT_PINS` out of the netlist generator with `ast` and **asserts the bit maps still match** — any drift fails the test loudly. See [§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test).

For the system-level theory of *what* these signals mean on the AMF 82-70 machine (cam timing, the cycle FSM, the relay-enable safety rail), see the system reference and FSM sections. This section is the pin-level bridge between that theory and the copper.

---

### 12.1 Scope: one lane = one board

Every map in this section is **per lane**. A lane *pair* is built as **two physically identical single-lane boards** stacked on one Raspberry Pi, each board carrying its own RP2040, its own set of three MCP23017s at the same I²C addresses (`0x20`/`0x21`/`0x22`; `0x23` reserved for the optional fourth), and its own relay-enable rail. The two boards are decoupled by running them on **two independent I²C buses** (Pi hardware `i2c-1` for board 1, a second software/GPIO bus via `dtoverlay=i2c-gpio` for board 2). This "clone the board" decision is recorded in `phase8_channel_allocation.md` §6 and is why both boards can reuse the identical address block (`0x20`/`0x21`/`0x22`, `0x23` reserved). Develop and validate one board, then build its twin.

**Board physical parameters** (from the design contract `phase8b_pcb_revB_spec.md`, cross-referenced by the generator): **250 × 225 mm, 4 copper layers.** (VERIFY: the generator script itself does not state board dimensions or layer count — these come from the spec doc and the as-routed `kicad/fab_revB_routed_manual/` artifacts, not from `generate_kicad_netlist_revB.py`.)

---

### 12.2 RP2040 (Raspberry Pi Pico) GPIO map — fast inputs + UART + rail permit

The RP2040 co-processor handles the **latency-critical** signals: the six cam microswitches and the two ball-detect beams. It also carries the UART link to the Pi and the single most safety-critical output on the board, `RP2040_OK`. The Pi never reads these fast signals directly — the RP2040 debounces them, drives the fail-safe `RP2040_OK` rail line + a motion max-run backstop, and *pushes* the resulting events to the Pi over UART (per-cam-edge cam-stop *overrun* is the deferred v1.1 firmware item) (see [§12.5](#125-why-the-fast-inputs-live-on-the-rp2040-operating-theory)).

#### 12.2.1 Authoritative GPIO table

Source of truth: `FAST_INPUTS` and `block_rp2040()` in `generate_kicad_netlist_revB.py` (physical Pico module pin numbers), confirmed pin-for-pin against the `PIN_*` GPIO numbers in `firmware/rp2040/config.h`. The KiCad footprint is `Module:RaspberryPi_Pico_SMD`.

| GPIO | Pico module pin | Net name | Signal | Direction | Front-end | Function (firmware comment) |
|---|---|---|---|---|---|---|
| **GP0** | 1 | `PI_UART_RX` | UART TX → Pi RX | OUT (Pico TX) | logic | uart0 TX. Pico GP0/TX → Pi RX. |
| **GP1** | 2 | `PI_UART_TX` | UART RX ← Pi TX | IN (Pico RX) | logic | uart0 RX. Pi TX → Pico GP1/RX. |
| **GP2** | 4 | `RP2040_OK` | Rail permission | **OUT** | NPN AND-chain | **HIGH = permit motion, LOW = drop the relay-enable rail.** Firmware health / cam-stop permit. |
| **GP6** | 9 | `FAST_SA` | **SA** sweep cam | IN (opto, active-low) | PC817B opto | Sweep cam: 270° run-through stop / 360° zero. → `cam_SA_*` |
| **GP7** | 10 | `FAST_SB` | **SB** sweep cam | IN (opto, active-low) | PC817B opto | Sweep cam: 66° guard / 186° table-spot init. → `cam_SB_guard` |
| **GP8** | 11 | `FAST_SC` | **SC** interlock cam | IN (opto, active-low) | PC817B opto | Sweep-under-table interlock window (86–243°). HW interlock + software echo. |
| **GP9** | 12 | `FAST_TA1` | **TA1** table cam | IN (opto, active-low) | PC817B opto | Table cam: 355° zero stop / 185° delay reset. → `cam_TA1_*` |
| **GP10** | 14 | `FAST_TA2` | **TA2** table cam | IN (opto, active-low) | PC817B opto | Table cam: 260° run-through / pin-latch / decision. → `cam_TA2_runthrough` |
| **GP11** | 15 | `FAST_TB` | **TB** interlock cam | IN (opto, active-low) | PC817B opto | Table-sweep interference interlock (105–255°). HW interlock + software echo. |
| **GP12** | 16 | `FAST_DIELL_L` | **DIELL** left beam | IN (opto, active-low) | PC817B opto | Ball detect, left beam (cushion SS / cycle trigger). → `on_ball` |
| **GP13** | 17 | `FAST_DIELL_R` | **DIELL** right beam | IN (opto, active-low) | PC817B opto | Ball detect, right beam. → `on_ball` |

> **Note on Pico pin numbering:** GP6→pin 9, GP7→pin 10, GP8→pin 11, GP9→pin 12 are consecutive, but **GP10 is Pico module pin 14, not 13** (pin 13 is a GND pin on the Pico). The generator's `FAST_INPUTS` correctly lists `("TA2", 14)`. Do not "correct" this to 13.

The eight grounded Pico pins tied to board `GND` (`block_rp2040()`): module pins **3, 8, 13, 18, 23, 28, 33, 38**. Power: **pin 39 = VSYS = `VCC_5V`** (board feeds the Pico its 5 V), **pin 36 = 3V3 OUT = `VCC_3V3`** (the Pico *supplies* the board's 3.3 V logic rail — see [§12.2.3](#1223-power-rails-touching-the-rp2040)).

#### 12.2.2 Electrical sense of the fast inputs (operating theory)

Every fast input is **opto-isolated and active-LOW at the Pico.** From `opto_input()` in the generator and the header comment in `config.h`:

- The field side of each PC817B LED is fed from the isolated **`FIELD_WET_V`** rail through a **2.2 kΩ** series resistor (`Rin_*`). The machine contact closes that channel's field pin to **`FIELD_GND`** at the harness, completing the LED loop.
- When the machine contact is **closed (signal asserted)**, the opto transistor conducts and pulls the Pico GPIO **LOW**. Idle (contact open) = **HIGH**, held up by an on-board **10 kΩ pull-up** (`Rpu_*`) to `VCC_3V3`.
- So: **asserted = GPIO LOW, idle = GPIO HIGH.** The firmware constant for this is the implicit active-low handling in the debounce path; the Pi-side equivalent is `INPUT_ACTIVE_LOW = True` in `controller_io.py`.
- The logic side runs at **3.3 V**, so both the Pico and the MCP23017 inputs are Pi-safe (no 5 V on any GPIO). This is the optocoupler's whole job here and it satisfies the hard project rule that **Pi/Pico GPIO is 3.3 V only.**

`RP2040_OK` (GP2) is the inverse-critical output: it drives an NPN transistor inside the relay-enable-rail AND chain. **HIGH permits motion; LOW drops the rail.** A 100 kΩ base pulldown on that NPN makes the rail **fail-safe-dead** whenever GP2 is high-impedance (Pico unpowered, in reset, or pre-init) — the machine cannot move until firmware has explicitly booted and asserted permit. See [§12.7](#127-cross-reference-the-relay-enable-rail) and the safety-rail section.

#### 12.2.3 Power rails touching the RP2040

| Net | Source | Notes |
|---|---|---|
| `VCC_5V_RAW` | `J_PWR` pin 1 (Phoenix 3-pos terminal) | Raw 5 V in; protected by an `SS14` Schottky (`D_PROT`) before becoming `VCC_5V`. |
| `VCC_5V` | After `D_PROT` cathode | Feeds Pico VSYS (pin 39), the relay-coil rail, watchdog NE555, and the TMA-0505S isolated supply input. |
| `VCC_3V3` | **Pico pin 36 (3V3 OUT)** | The Pico's own regulator supplies all 3.3 V logic (MCP23017s, opto pull-ups, I²C pull-ups). A `10uF` bulk cap (`C_3V3_BULK`) makes the rail visible/placeable. |
| `FIELD_WET_V` / `FIELD_GND` | TMA-0505S DC-DC (`ISO_WET`) | Isolated 5 V "wet" domain that drives the opto LEDs; galvanically separate from logic GND. |

---

### 12.3 MCP23017 device summary

The board carries **three** MCP23017 16-bit I²C expanders in the baseline build (a fourth is optional). The part is the **I²C MCP23017** (LCSC **C47023**), in the SOIC-28W footprint (`Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm`). **It is *not* the SPI MCP23S17** — do not substitute the SPI variant; the Pi-side driver in `controller_io.py` talks `smbus2`/I²C only.

| Ref | I²C addr | A2 A1 A0 strap | Role | Pins used / 16 | Direction (IODIR) |
|---|---|---|---|---|---|
| **IN-A** | `0x20` | 0 0 0 | Grippers GS1–10 + GP/OS/BS/PBZ/PBC/Foul | 16 / 16 (full) | All inputs (`0xFF`), pull-ups on |
| **IN-B** | `0x21` | **1** 0 0 | 10th-frame + manual switches + spares | 5 / 16 | All inputs (`0xFF`), pull-ups on |
| **OUT-A** | `0x22` | 0 **1** 0 | 7 relay coils + 4 status lamps | 11 / 16 | All outputs (`0x00`) |
| **OUT-B** | `0x23` | (optional) | Physical pin-mask lamps + neon | OPTIONAL | All outputs — *omitted in baseline* |

**Address strapping** is set in hardware by tying A0/A1/A2 (MCP pins 15/16/17) high or low. From `block_mcp()` the strap tuples are `IN-A=(0,0,0)`, `IN-B=(1,0,0)`, `OUT-A=(0,1,0)`. (Note the generator passes the tuple in **A2,A1,A0** order; `IN-B` has A2 high → `0x21`, `OUT-A` has A1 high → `0x22`. (VERIFY: the live generator wires only three MCP23017s — IN-A, IN-B, OUT-A. There is **no** `MCP_OUT_B` instantiated in `generate_kicad_netlist_revB.py`; the optional `0x23` pin-mask expander exists only in `controller_io.py`'s `ADDR_OUT_B` constant and in the channel-allocation doc, gated behind `enable_pin_lamps`. The baseline board does not place it.)

**OUT-B / camera convergence (theory):** OUT-B would drive ten physical pin-indicator lamps (the "mask"). In this system the **camera supplies the pin-mask data** (scoring Track A), so OUT-B is depopulated by default. `controller_io.py` only opens `0x23` when constructed with `enable_pin_lamps=True`; `set_pin_lamps()` is a no-op otherwise. If a physical pindicator is ever built, OUT-B uses GPA0–GPA7 + GPB0–GPB1 for lamps 1–10. See the scoring section for why the camera path wins on a mixed-controller fleet.

**MCP23017 pin numbering used throughout** (verified KiCad symbol, from `block_mcp()` comment): VDD=9, VSS=10, SCK(SCL)=12, SDA=13, A0=15, A1=16, A2=17, ~RESET=18, INTB=19, INTA=20, **GPA0–GPA7 = pins 21–28**, **GPB0–GPB7 = pins 1–8**. Each chip has a local `0.1uF` decoupling cap; the I²C bus has shared **4.7 kΩ** pull-ups (`R_I2C_SDA`, `R_I2C_SCL`) to 3V3. `~RESET` (pin 18) is tied to `VCC_3V3` (held de-asserted).

#### The pin → (port, bit) translation rule

`controller_io.py` expresses every bit as **`(port, bit)`** where port 0 = GPIOA/OLATA and port 1 = GPIOB/OLATB. The mapping from the generator's raw MCP **pin number** to `(port, bit)` is fixed:

| MCP pin number | Port | Bit | gpiozero/register name |
|---|---|---|---|
| 21 | 0 | 0 | GPA0 |
| 22 | 0 | 1 | GPA1 |
| 23 | 0 | 2 | GPA2 |
| 24 | 0 | 3 | GPA3 |
| 25 | 0 | 4 | GPA4 |
| 26 | 0 | 5 | GPA5 |
| 27 | 0 | 6 | GPA6 |
| 28 | 0 | 7 | GPA7 |
| 1 | 1 | 0 | GPB0 |
| 2 | 1 | 1 | GPB1 |
| 3 | 1 | 2 | GPB2 |
| 4 | 1 | 3 | GPB3 |
| 5 | 1 | 4 | GPB4 |
| 6 | 1 | 5 | GPB5 |
| 7 | 1 | 6 | GPB6 |
| 8 | 1 | 7 | GPB7 |

This is exactly the `_pin_to_portbit()` helper in the `controller_io.py` self-test (`21–28 → (0, pin-21)`, `1–8 → (1, pin-1)`). Use it whenever you read a pin number off the netlist and need the software bit.

---

### 12.4 MCP23017 IN-A bit map (I²C `0x20`) — slow inputs

IN-A is **full** (all 16 pins used). It carries the ten gripper switches (the standing-pin mask) plus the gripper-protect, off-spot, bin-switch, two pushbuttons, and the foul signal. All sixteen channels are opto-isolated front-ends identical to the fast inputs ([§12.2.2](#1222-electrical-sense-of-the-fast-inputs-operating-theory)): **active-low at the MCP pin — switch closed pulls the pin LOW.** `controller_io.py` reads them with internal MCP pull-ups enabled (`pullup_a=0xFF, pullup_b=0xFF`) and inverts in software via `INPUT_ACTIVE_LOW = True`.

Source of truth: `IN_A_MAP` in `controller_io.py`, cross-checked against the `MCP_IN_A` entries of `SLOW_INPUT_PINS` in the generator.

| Signal | `IN_A_MAP` (port, bit) | MCP pin (generator) | Register name | FSM `io.*` method | Meaning |
|---|---|---|---|---|---|
| **GS1** | (0, 0) | 21 | GPA0 | `read_grippers` bit 0 | Gripper 1 standing |
| **GS2** | (0, 1) | 22 | GPA1 | `read_grippers` bit 1 | Gripper 2 standing |
| **GS3** | (0, 2) | 23 | GPA2 | `read_grippers` bit 2 | Gripper 3 standing |
| **GS4** | (0, 3) | 24 | GPA3 | `read_grippers` bit 3 | Gripper 4 standing |
| **GS5** | (0, 4) | 25 | GPA4 | `read_grippers` bit 4 | Gripper 5 standing |
| **GS6** | (0, 5) | 26 | GPA5 | `read_grippers` bit 5 | Gripper 6 standing |
| **GS7** | (0, 6) | 27 | GPA6 | `read_grippers` bit 6 | Gripper 7 standing |
| **GS8** | (0, 7) | 28 | GPA7 | `read_grippers` bit 7 | Gripper 8 standing |
| **GS9** | (1, 0) | 1 | GPB0 | `read_grippers` bit 8 | Gripper 9 standing |
| **GS10** | (1, 1) | 2 | GPB1 | `read_grippers` bit 9 | Gripper 10 standing |
| **GP** | (1, 2) | 3 | GPB2 | `gp_closed` | Gripper-protect |
| **OS** | (1, 3) | 4 | GPB3 | `read_input("OS")` ⊕ | Off-spot (future) |
| **BS** | (1, 4) | 5 | GPB4 | `bs_closed` | Bin / #9 switch |
| **PBZ** | (1, 5) | 6 | GPB5 | `first_ball_zero` path | Zero / 1st-2nd / manual-int pushbutton |
| **PBC** | (1, 6) | 7 | GPB6 | `read_input("PBC")` ⊕ | Cycle pushbutton (future) |
| **Foul** | (1, 7) | 8 | GPB7 | `on_foul` path | Radaray foul detect |

> **⚠️ The OS/BS bit order was a known bug, now fixed.** Earlier drafts had OS and BS swapped. The corrected, as-built order is **OS = pin 4 = (1,3)** and **BS = pin 5 = (1,4)**, matching the generator's `SLOW_INPUT_PINS`. `controller_io.py` carries an explicit comment to this effect, and the self-test enforces it. See [§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test).

**Gripper mask theory.** `read_grippers()` reads both ports of IN-A once each and assembles a **10-bit standing-pin mask**, where **bit (n−1) = GSn is standing** (`GRIPPER_ORDER = [GS1…GS10]`). Because the opto is active-low, a *standing* pin (gripper switch held) reads `0` at the pin and is recorded as a `1` in the mask. A clean rack = `0` (no pins) in the strike test in the FSM smoke test. This mask is the controller's *electromechanical* pin read; the *optical* camera read is the authoritative score source (scoring section), with the gripper mask available as a controller-side cross-check.

**Naming caveat for the daemon:** `read_input(name)` on `MachineIO` takes the `IN_A_MAP` key. Note the foul channel's key is **`"Foul"`** (mixed case) in `IN_A_MAP`, while the generator's `SLOW_INPUT_PINS` and the `J_SLOWB` connector order spell it **`"FOUL"`** (upper). The self-test bridges this (`"Foul" if n == "FOUL"`). Use `"Foul"` when calling `controller_io.py`.

#### IN-B (`0x21`) — initialized, not yet read

`controller_io.py` opens and configures IN-B (`self.in_b`, all-inputs, pull-ups on) so all three board expanders are live, **but the current FSM does not read it.** Its channels (10th-frame, manual table/sweep/sweep-switch/sweep-reverse, three aux) are spare-allocated for when the FSM grows to full machine control. From `SLOW_INPUT_PINS` (the `MCP_IN_B` entries) and the `J_SLOWB` connector order:

| Signal | MCP pin | Port,bit | Register | Status |
|---|---|---|---|---|
| TENTH (10th-frame) | 21 | (0,0) | GPA0 | ⊕ future |
| MAN_T (manual table) | 22 | (0,1) | GPA1 | ⊕ future |
| MAN_S (manual sweep) | 23 | (0,2) | GPA2 | ⊕ future |
| MAN_SWS (manual sweep-switch) | 24 | (0,3) | GPA3 | ⊕ future |
| MAN_SWSR (sweep reverse) | 25 | (0,4) | GPA4 | ⊕ future |
| AUX1 | 26 | (0,5) | GPA5 | ⊕ spare |
| AUX2 | 27 | (0,6) | GPA6 | ⊕ spare |
| AUX3 | 28 | (0,7) | GPA7 | ⊕ spare |

IN-B's entire B-bank (GPB0–7) is free → expansion headroom. (VERIFY: `controller_io.py` defines no `IN_B_MAP` constant — the IN-B channel→pin assignment lives only in the generator's `SLOW_INPUT_PINS` and this doc. There is no software bit map to drift against yet, so the self-test does not cover IN-B.)

---

### 12.5 Why the fast inputs live on the RP2040 (operating theory)

This is the single most important architectural decision in the I/O design, and it is the reason the cams/ball are *not* simply more MCP23017 bits.

- **Latency + hardware cam-stop.** The cam microswitches define exact angular windows where a motor *must* be cut (e.g., SA at 270° run-through, the SC/TB interlock windows). The RP2040 is the element positioned to **drop the relay-enable rail in hardware** the instant a stop edge fires — independent of Pi scheduling, the UART link, or Linux jitter (this per-cam-edge *overrun* drop is the deferred v1.1 firmware feature; v0.1.0 provides the `RP2040_OK` health line + the 8 s max-run backstop). An MCP23017 cannot do this; it would require the Pi to poll, decode, and react, adding tens of milliseconds of software latency to a safety-critical cut.
- **Push, not poll.** The RP2040 *forwards cam/ball events to the Pi as messages* over UART (newline-delimited JSON, e.g. `{"ev":"SB_guard"}` / `{"ev":"ball"}`, at 115200 baud). The FSM in `cycle_control_8270.py` consumes **events** (method calls like `cam_SB_guard()`), not pin polls, so nothing is lost by moving the pins off the Pi header. A UART/IRQ device can *initiate*; an I²C/SPI peripheral cannot — that is why UART was chosen over an MCP-style expander or an SPI/I²C slave for these signals.
- **Pin budget.** Sixteen fast inputs across a pair would consume too much of the Pi's 40-pin header. Putting them on a per-board RP2040 keeps the Pi's GPIO free for the two I²C buses, the watchdog kick, and the per-board INT/arm lines.
- **Fail-safe link.** The **safety stop logic stays local to the RP2040** — its `RP2040_OK` health line + the motion max-run backstop gate the rail directly, independent of the UART (per-cam-edge cam-stop *overrun* is the deferred v1.1 item). A dead UART therefore cannot cause unsafe motion — it only means the FSM stops receiving event notifications, which trips the motion-timeout fault (fail-safe). See the safety section for the full rail logic.

The `RP2040_OK` (GP2) output is the RP2040's "I am alive and permitting motion" line into the AND chain; the firmware holds it LOW for `BOOT_SETTLE_MS = 200 ms` after boot before ever permitting, and the on-chip watchdog (`WDT_TIMEOUT_MS = 250 ms`) resets the chip — dropping GP2 → dropping the rail — if the firmware loop ever hangs.

---

### 12.6 The stale-draft trap and the anti-drift self-test

**⚠️ Read this before trusting any older pinout doc.**

`docs/phase8_channel_allocation.md` §2 contains a **GPIO column that is STALE.** That draft assigned the fast inputs (SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R) to **GP0–GP7**. **That is WRONG for the as-built board.** The real board — and the flashed firmware — use **GP6–GP13** for the fast inputs, with **GP0/GP1 reserved for UART** and **GP2 for `RP2040_OK`**. The `config.h` header says so explicitly:

> *"do NOT trust the older draft in `docs/phase8_channel_allocation.md` §2, which assigned the fast inputs to GP0-GP7 (WRONG vs the as-built board; the real board uses GP6-GP13)."*

The **known-correct anchors** (use these; flag any source that disagrees):

| Anchor | Correct value | Authority |
|---|---|---|
| Fast inputs (SA…DIELL_R) | **GP6 … GP13** | `FAST_INPUTS` + `config.h` |
| `RP2040_OK` | **GP2** | `block_rp2040()` + `config.h` |
| UART TX/RX | **GP0 / GP1** | `block_rp2040()` + `config.h` |

**`controller_io.py` was corrected to match the board.** Three specific swaps that were caught (by Codex, 2026-06-03) and fixed so the software matches the netlist:

1. **BS ↔ OS** — corrected to OS=(1,3), BS=(1,4).
2. **M1 ↔ M2** — corrected so M2 comes *before* M1 (M2=GPA5/pin 26, M1=GPA6/pin 27) per the generator's `OUTPUT_PINS`.
3. **strike ↔ foul** — corrected to strike=(1,1), foul=(1,2).

The fix is *enforced*, not just documented. The `if __name__ == "__main__"` block at the bottom of `controller_io.py`:

1. Drives the real `cycle_control_8270` FSM through a full strike cycle on `RecordingIO` (proves the io contract).
2. Parses `generate_kicad_netlist_revB.py` with `ast.literal_eval`, extracts `OUTPUT_PINS` and `SLOW_INPUT_PINS`, converts each pin to `(port, bit)`, and **asserts `OUT_A_MAP == exp_out` and `IN_A_MAP == exp_in`.** If anyone edits the board netlist without updating the software map (or vice-versa), this test fails with a diff. **Run `python lane_node/controller_io.py` after any pin change.**

So: `OUT_A_MAP` / `IN_A_MAP` in `controller_io.py` are **current and correct**; the `phase8_channel_allocation.md` GPIO column is **historical**. When this section and that draft disagree, **this section (and the three source files) win.**

---

### 12.7 MCP23017 OUT-A bit map (I²C `0x22`) — relays + status lamps

OUT-A is the only output expander in the baseline build. Seven channels drive **relay coils** (the motion/solenoid relays) and four drive **status lamps** (the bowler-facing indicators). All eleven are configured as outputs (`dir_mask_a=0x00, dir_mask_b=0x00`) and start LOW.

Source of truth: `OUT_A_MAP` in `controller_io.py`, cross-checked against `OUTPUT_PINS` in the generator (the regression test asserts they are identical after the `L_FIRST→first_ball` etc. key remap).

| Signal | `OUT_A_MAP` (port, bit) | MCP pin (generator) | Register | Driver chain | FSM `io.*` method | Load |
|---|---|---|---|---|---|---|
| **S** | (0, 0) | 21 | GPA0 | MCP → MMBT3904 → G5LE relay | `set_sweep` | Machine sweep-contactor coil ~24 VAC → 115 V motor |
| **T** | (0, 1) | 22 | GPA1 | MCP → MMBT3904 → G5LE | `set_table` | Machine table-contactor coil ~24 VAC → 115 V motor |
| **SP** | (0, 2) | 23 | GPA2 | MCP → MMBT3904 → G5LE | `set_spot` | Machine SP spot-solenoid circuit ~24 VAC |
| **BE** ⊕ | (0, 3) | 24 | GPA3 | MCP → MMBT3904 → G5LE | (future) | Back-end relay (continuous motor) |
| **M** ⊕ | (0, 4) | 25 | GPA4 | MCP → MMBT3904 → G5LE | (future) | Master relay (power/halo/pit) |
| **M2** ⊕ | (0, 5) | 26 | GPA5 | MCP → MMBT3904 → G5LE | (future) | Sweep reverse |
| **M1** ⊕ | (0, 6) | 27 | GPA6 | MCP → MMBT3904 → G5LE **(DNP)** | (future) | Ball return motor |
| **first_ball** | (0, 7) | 28 | GPA7 | MCP → 2N7002 NMOS (low-side) | `set_light('first_ball')` | 1st-ball status lamp (`L_FIRST`) |
| **second_ball** | (1, 0) | 1 | GPB0 | MCP → 2N7002 NMOS | `set_light('second_ball')` | 2nd-ball status lamp (`L_SECOND`) |
| **strike** | (1, 1) | 2 | GPB1 | MCP → 2N7002 NMOS | `set_light('strike')` | Strike status lamp (`L_STRIKE`) |
| **foul** | (1, 2) | 3 | GPB2 | MCP → 2N7002 NMOS | `set_light('foul')` | Foul status lamp (`L_FOUL`) |

> **Coil vs. load — do not confuse the two.** The *Load* column above is the machine-side circuit each relay **contact** switches (≈24 VAC contactor coil / solenoid, which in turn runs the 115 V motor). Every on-board **G5LE relay coil is 5 VDC**, fed from the relay-enable rail (see §9, §10). The board never drives a 24 V coil.

OUT-A.B3–B7 (MCP pins 4–8) are **spare** (5 free output bits). The `⊕` channels (BE, M, M1, M2) are wired and physically present but **not yet driven by the FSM** — they are spare-allocated for full machine control.

> **Name mapping reminder.** The generator's `OUTPUT_PINS` uses the lamp keys `L_FIRST / L_SECOND / L_STRIKE / L_FOUL`. `controller_io.py` exposes them as `first_ball / second_ball / strike / foul` (the names `set_light()` accepts). The self-test's `OUT_KEY` dict bridges the two. `set_light()` rejects any name not in `{first_ball, second_ball, foul, strike}`.

> **M1 is depopulated (DNP).** In `main()` the generator calls `relay_output("M1", …, dnp=True)` — its G5LE relay footprint is on the board but **not stuffed** in the baseline build. The bit map slot exists; the physical relay does not (yet).

#### 12.7.1 Relay driver chain (theory)

Each motion channel (`relay_output()`): the MCP output bit feeds a **1 kΩ** base resistor (`Rb_*`) into an **MMBT3904** NPN, with a **100 kΩ** pulldown (`add_drive_pulldown`) so the relay is off when the MCP is undriven/Hi-Z. The transistor's collector switches the low side of the **Omron G5LE-14 relay coil**; the coil's high side sits on the **`RELAY_ENABLE_RAIL`** (not raw 5 V) — so the watchdog/arm/interlock rail can cut every motion relay at once. A **1N4148** flyback diode (`Dfly_*`) clamps the coil (cathode to rail, anode to switched side). Across each relay *contact* (COM = relay pin 3, NO = relay pin 4) the board provides a depopulatable arc-suppression network: **100 Ω DNP** series resistor + **10 nF X2 DNP** cap + **MOV DNP** — all not-stuffed by default, footprints available for AC loads if the bench shows contact arcing.

> **Relay part — anchor.** The relay is the **Omron G5LE-14, 5 VDC coil** (LCSC **C116963**), footprint `Relay_THT:Relay_SPDT_Omron-G5LE-1`. It is a **5 V** coil — **not 12 V or 24 V.** (Note: the *coil* is 5 V; the channel table above lists the *downstream machine load* the relay's contacts switch, e.g. a 24 V machine coil / 115 V motor circuit. The generator's `value="24V coil…"` text in the channel-allocation doc refers to the field load, not the G5LE coil. The G5LE is energized from the 5 V relay-enable rail.) See [§12.9](#129-bench-decision-aediko-relay-module-vs-on-board-g5le) on the AEDIKO-module alternative captured in the design notes.

#### 12.7.2 Status-lamp driver chain (theory)

Each lamp channel (`lamp_led_output()`): the MCP bit feeds a **1 kΩ** gate resistor (`Rgled_*`) into a **2N7002** N-channel MOSFET (low-side switch), with a **100 kΩ** gate pulldown (`Rpdled_*`) for fail-off and a **330 Ω** series limit resistor (`Rled_*`) in the lamp return. The lamp's supply comes from the board's `VCC_5V` at the lamp connector and the MOSFET sinks the return to GND. These are *not* motors — `MOTION_RELAYS` in `controller_io.py` deliberately excludes the four lamps, so they are never sent RUN/STOP to the RP2040's motion-timeout backstop.

---

### 12.8 Field connectors (where each map lands at the harness)

The generator's `block_connectors()` lays out function-named field terminals so the harness is labeled by machine function, not bare pin numbers. Summary (footprints in parentheses):

| Connector | Footprint | Carries | Pin order |
|---|---|---|---|
| **J_PI** | IDC 2×10 (`IDC-Header_2x10`) | Pi ribbon: power, I²C, UART, watchdog kick, arm, MCP INTs, RP2040_OK | 1=VCC_5V, 2/12=GND, 3=SDA, 4=SCL, 5=UART_TX, 6=UART_RX, 7=WDOG_KICK, 8=ARM_PERMIT, 9=MCP_INT_A, 10=MCP_INT_B, 11=VCC_3V3, 13=RP2040_OK |
| **J_PWR** | Phoenix 3-pos (`MKDS-1,5-3-5.08`) | 5 V input | 1=VCC_5V_RAW, 2/3=GND |
| **J_FAST_IN** | Phoenix MCV 1×10 | 8 fast field inputs + field GND | pins 1–8 = SA, SB, SC, TA1, TA2, TB, DIELL_L, DIELL_R (in `FAST_INPUTS` order); pins 9–10 = FIELD_GND |
| **J_SLOW_IN_A** | Phoenix MCV 1×14 | IN-A field inputs | pins 1–13 = GS1…GS10, GP, OS, BS; pin 14 = FIELD_GND |
| **J_SLOW_IN_B** | Phoenix MCV 1×12 | IN-B field inputs | pins 1–11 = PBZ, PBC, FOUL, TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1, AUX2, AUX3; pin 12 = FIELD_GND |
| **J_MOTION_{S,T,SP,BE,M,M2,M1}** | seven Phoenix 2-pos (`MKDS-1,5-2-5.08`) | one relay contact pair each | pin 1 = `OUT_*_B` (NO), pin 2 = `OUT_*_A` (COM) — vertical order matches the G5LE pad order (B above A) |
| **J_LAMP_LED** | Phoenix MCV 1×6 | 4 status lamps + power | 1=VCC_5V, 2=GND, 3–6 = L_FIRST, L_SECOND, L_STRIKE, L_FOUL returns |
| **J_SAFETY** | Phoenix MCV 1×4 | two NC safety loops in series | 1→2 = TB/SC loop, 3→4 = Stop/CIS loop, feeding the rail PMOS source |

> **Important field note (from `phase8_channel_allocation.md` §3, bench-confirmed):** the machine-side outputs are **split across machine connectors C1 and C2A** — the high-current main motors **S, T** land on **C1**, while **SP, M2, BE** land on **C2A**. This does **not** change the OUT-A bit map (the board always drives the relay coils); it only affects which machine connector each relay *contact* wires to in the field. The enclosure harness therefore needs leads from the relay bank to **both** C1 and C2A. Exact C1/C2A cavity digits are bench-gated in the fieldsheet pass (the one remaining hard blocker for board finalization).

---

### 12.9 Bench decision: AEDIKO relay module vs on-board G5LE

The Rev-B netlist generator instantiates **on-board G5LE relays** with discrete MMBT3904 drivers and flyback diodes (as mapped in [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps)). The Phase-8a bench work, however, captured specs for an alternative implementation path using a pre-built **AEDIKO 8-channel relay module** (recorded in `phase8_channel_allocation.md` §7 and `pcb_design_spec.md`). The two are not contradictory — they are two ways to realize the same OUT-A bit map; which one the production board uses is a build choice. Key captured facts (for whoever builds/services the relay bank):

- **AEDIKO coil current:** ~**70 mA each @ 5 V** (8 ch → ~560 mA worst case); coil rail spec **4.5–6 V** → the relay-coil rail is **5 V**, consistent with the G5LE-14 5 VDC anchor.
- **AEDIKO has onboard optos + flyback** (it is a complete relay HAT) → in that path the discrete MMBT3904 + 1N4148 collapse to "MCP/GPIO → AEDIKO IN," and **no external ULN2803 is needed.**
- **Watchdog gating proven:** NE555 → AO3400 low-side MOSFET gates the AEDIKO **V− return** (5.7 A FET vs 560 mA load = large margin). Bench-validated.
- **Contacts switch the contactor *coil* circuit, not the motor directly** — the machine's existing contactors still switch the 115 V motor, so the relay contacts only see small contactor-coil current. This is the central simplicity/safety win: *the board drives coils; the machine's existing iron switches the motors.* Confirm each contactor's coil voltage/current at the bench.

(VERIFY: the **live netlist generator builds discrete G5LE relays**, not the AEDIKO module — the AEDIKO is documented in the channel-allocation/pcb-design notes as the validated Phase-8a approach. Which of the two the as-routed Rev-B board actually carries should be confirmed against the assembly BOM in `kicad/fab_revB_routed_manual/assembly/` before ordering replacements. The generator's part is the G5LE-14.)

---

### 12.10 Watchdog timing reference (NE555) + firmware timing constants

Two independent timing layers protect motion. Both are summarized here because a service tech tracing "why did the rail drop / why won't it arm" needs both numbers in one place.

**Layer 1 — on-board NE555 hardware watchdog** (`block_watchdog()` in the generator). A **bipolar NE555** (part **NE555DR**, LCSC **C7593**, footprint `Package_SO:SOIC-8`) in monostable-retriggerable form: the Pi kicks `WDOG_KICK` (J_PI pin 7 → GPIO12) periodically; each kick discharges the timing cap through a MOSFET, restarting the timeout. If kicks stop, the NE555 output flips and the AND chain drops the rail. Timing components:

| Component | Ref | Value | Role |
|---|---|---|---|
| Timing resistor | `R_WDOG_TIMING` | 100 kΩ | RC charge into NE555 THRESH/TRIG |
| Timing capacitor | `C_WDOG_TIMING` | 100 µF / 16 V (electrolytic) | Sets the ~seconds-scale timeout |
| Trigger pull-up | `R_WDOG_TRIG_PULLUP` | 10 kΩ | Holds TRIG high between kicks |
| Kick gate / pulldown | `R_WDOG_KICK_GATE` / `R_WDOG_KICK_PD` | 1 kΩ / 10 kΩ | Pi GPIO12 → kick MOSFET (AO3400A) |
| Output gate / pulldown | `R_WDOG_OUT_GATE` / `R_WDOG_OUT_PD` | 1 kΩ / 10 kΩ | NE555 OUT → AND-chain MOSFET (AO3400A) |
| VCC decouple | `C_WDOG_VCC` | 0.1 µF | NE555 supply |
| Control bypass | `C_WDOG_CTRL` | 10 nF | Pin 5 CONTROL filter |

The design intent is a kick-or-die window of roughly **~10 s** (the bench-validated figure cited in the channel-allocation doc and safety section). (VERIFY: the generator fixes the RC parts at 100 kΩ × 100 µF but does **not** annotate the exact resulting timeout in seconds; the "~10 s" figure comes from the bench validation notes, not from a computed constant in the source. The standard 555 monostable `t ≈ 1.1·R·C` with these values ≈ 11 s, consistent with "~10 s," but treat the precise number as bench-measured, not source-declared.)

**Layer 2 — RP2040 firmware timing** (`config.h`). These are the compiled-in constants the Pico enforces:

| Constant | Value | Purpose |
|---|---|---|
| `UART_BAUD` | 115200 | Pi link baud |
| `DEBOUNCE_CAM_US` | 2000 µs (2 ms) | Cam microswitch debounce (12 RPM machine → 2 ms ample) |
| `DEBOUNCE_DIELL_US` | 500 µs | Ball beam-break debounce (faster, still de-glitched) |
| `BALL_LOCKOUT_MS` | 300 ms | One thrown ball → one ball event (re-trigger lockout) |
| `HB_INTERVAL_MS` | 250 ms | Heartbeat cadence to the Pi |
| `BOOT_SETTLE_MS` | 200 ms | RP2040_OK held LOW at least this long after boot before permitting motion |
| `WDT_TIMEOUT_MS` | 250 ms | RP2040 on-chip watchdog: loop hang → chip reset → RP2040_OK drops → rail drops |
| `MAX_MOTION_MS` | 8000 ms | Motion max-run backstop (matches `cycle_control_8270.MAX_MOTION_S = 8.0 s`). A guarded motor marked RUNNING over UART longer than this latches a fault and drops RP2040_OK. **BE (continuous) and M (master/power) are NOT guarded.** |

`FW_VERSION` is `"phase8b-rp2040 v0.1.0"`.

---

### 12.11 Cross-reference: the relay-enable rail

Everything in [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps) (relay coils) is powered through the series **`RELAY_ENABLE_RAIL`**, which is gated by the AND of four conditions (`block_rail()` + safety section):

1. **NE555 watchdog OK** — Pi kicks GPIO12 within the timeout, else the rail drops. ([§12.10](#1210-watchdog-timing-reference-ne555--firmware-timing-constants))
2. **Pi "arm" GPIO** asserted (`ARM_PERMIT`, J_PI pin 8) — de-asserts on the power-down rule until an operator First-Ball-Zero.
3. **RP2040_OK** (GP2) HIGH — firmware healthy + cam-stop permitting. ([§12.2.2](#1222-electrical-sense-of-the-fast-inputs-operating-theory))
4. **Hardware TB+SC interlock + Stop/CIS chain** closed — the two NC safety loops on **J_SAFETY** in series, feeding the rail PMOS (`Q_RAIL`, AO3401A) source.

The AND is built from two MMBT3904s (`Q_AND_ARM`, `Q_AND_RP_OK`) driving the PMOS pass-FET gate. **Any one false → every motion relay coil loses power.** None of this is bypassable by the Pi in software. For the complete safety theory (regenerative braking, contactor preservation, the "we drive coils, the machine switches motors" principle) see the dedicated safety section.

---

### 12.12 Quick service checklist

- **A cam input is dead.** It is on the RP2040, not an MCP. Trace `J_FAST_IN` pin → PC817B opto → Pico GPIO per [§12.2.1](#1221-authoritative-gpio-table). Remember: **asserted = GPIO LOW.** Confirm the channel's `FIELD_WET_V` and `FIELD_GND` at J_FAST pins 9/10.
- **A relay won't fire.** Confirm the **rail** is up first ([§12.11](#1211-cross-reference-the-relay-enable-rail)) — a dropped watchdog/arm/RP2040_OK/interlock kills all coils, not just one. Then trace OUT-A bit → MMBT3904 → G5LE per [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps).
- **Wrong lamp / wrong relay channel.** Do **not** trust the GPIO column in `phase8_channel_allocation.md`. Re-derive from `OUT_A_MAP` / `IN_A_MAP` and run the self-test (`python lane_node/controller_io.py`) — it will diff any drift against the netlist. ([§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test))
- **M1 / OUT-B "missing."** Expected — M1's G5LE is DNP and OUT-B (`0x23`) is depopulated in the baseline (camera supplies the pin mask). ([§12.3](#123-mcp23017-device-summary), [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps))
- **Replacing a part.** Anchors: relay = **Omron G5LE-14, 5 VDC** (C116963); expander = **MCP23017** I²C (C47023), **not** MCP23S17; opto = **PC817B** (C5692981); timer = **NE555** (NE555DR, C7593). Verify any other value against the assembly BOM in `kicad/fab_revB_routed_manual/assembly/` before ordering.


## 13. Rev-B Layout & Manufacturing Contract (Net Classes, Creepage, DNP, Test Points)

This section is the manufacturing and isolation contract for the Rev-B lane-controller PCB
(`wsl-phase8b.routed-manual.kicad_pcb`). It tells you what the board *guarantees* electrically:
which net belongs to which class, how far every domain is held off every other domain in copper,
which parts are intentionally left unpopulated and why, where to probe, and — most importantly —
the hard-won lesson about how a KiCad design-rule check on this board can lie to you if you do not
verify that the net classes are active.

Read this together with:

- **Section 2 — System Architecture & Domains** (the LOGIC / FIELD / MACHINE three-domain split this section enforces in copper).
- **Section 10 — Safety Rail & Watchdog** (the rail/interlock/watchdog circuit whose nets are the `Safety_Rail` class here).
- **Section 23 — Bill of Materials & Assembly** (the populated-part list; this section covers the *excluded* / DNP set and the part-locks).
- **Section 15 — RP2040 Firmware** and **Section 7 — controller_io / MCP23017 Map** (the pin/bit maps that the netlist generator drives, and which this board is wired from).

> **One-line statement of the contract.** Rev-B is a one-lane, 250 × 225 mm, four-copper-layer
> integrated controller board on which every one of the 184 named nets is assigned to exactly one
> of five net classes, the three electrical domains are held apart by all-layer no-copper gutters
> sized for a conservative 250 VAC working voltage, the inductive-suppression and ball-return
> (M1) parts are shipped DNP, and the DRC-clean result is only trustworthy because the audit
> script proves the net classes are live.

---

### 13.0 Snapshot of the as-built board

These are the live numbers from the fab package (`reports/board-stats.txt`, `reports/audit-revB-board.log`,
`reports/drill-report.txt` under `kicad/fab_revB_routed_manual/`). They are the board you hold, not a target.

| Property | Value | Source |
|---|---|---|
| Board outline (Edge.Cuts) | **250.0 × 225.0 mm** nominal (audit bbox reads 250.15 × 225.15 incl. cut-line width) | board-stats.txt / audit log |
| Copper layers | **4** (F.Cu / In1.Cu / In2.Cu / B.Cu) | drill-report stackup |
| Board thickness | 1.60 mm | board-stats.txt |
| Min track width | **0.2500 mm** | board-stats.txt |
| Min track clearance | **0.2875 mm** | board-stats.txt |
| Min drill diameter | **0.300 mm** (PTH via) | drill-report.txt |
| Footprints on board | 236 (54 THT + 162 SMD + 20 unspecified/test) | board-stats.txt |
| Routed copper | 1178 tracks + 382 vias; 3 zones (1 GND pour + 2 keepout rule-areas) | route-pass findings (final) |
| Named nets | **184** (0 anonymous `N$`) | audit log |
| DRC result | **0 violations / 0 unconnected pads / 0 footprint errors** | reports/DRC-revB-routed-manual-fab.rpt |
| Topology audit | **AUDIT RESULT: ALL PASS** | reports/audit-revB-board.log |
| DNP / excluded-from-assembly parts | **27** | reports/audit-revB-board.log, dnp-excluded.csv |

All of these min-feature numbers sit inside JLCPCB's 4-layer capability, which is why the package
was declared bare-PCB fab-ready.

---

### 13.1 The three domains this section protects

Rev-B carries three electrically distinct worlds. The whole point of the net classes and the
creepage policy is to keep them apart everywhere except inside the isolating components. (Full
domain theory is in Section 2; this is the layout-relevant summary.)

| Domain | What it is | Ground reference | Crosses to LOGIC only inside… |
|---|---|---|---|
| **LOGIC** | Raspberry Pi header, 3× MCP23017, RP2040 (Pico), I²C, UART, NE555 watchdog, relay-driver bases, status-LED drivers, the 5 V / 3.3 V rails | **GND** | — |
| **FIELD (machine-sense, isolated)** | Field side of every PC817 optocoupler; isolated wetting supply | **FIELD_GND** (NOT tied to GND) | the PC817 package (LED = FIELD, transistor = LOGIC) |
| **MACHINE OUTPUT** | Relay dry contacts that open/close existing machine control circuits; RC snubber + MOV footprints across those contacts | floating / machine-referenced | the G5LE relay package (coil = LOGIC/rail, contact = MACHINE) |

**The two barriers that must never be bridged in copper:**

1. **LOGIC ↔ FIELD** — crossed only inside the PC817 opto bodies.
2. **LOGIC ↔ MACHINE OUTPUT** — crossed only inside the G5LE relay bodies.

No trace, via, plane, or copper pour may shorten either barrier below the creepage spec in §13.3.
The live audit independently proves the isolation holds: **GND has 93 pads and FIELD_GND has 6 pads,
sharing zero nodes** (`reports/audit-revB-board.log`).

> **Layer assignment of the domains.** The board is banded left-to-right: **FIELD inputs on the
> left**, **LOGIC / SAFETY in the center**, **MACHINE contacts on the right**, with all-copper
> keepout gutters between bands. The optos sit *on* the FIELD/LOGIC gutter and the relays sit *on*
> the LOGIC/MACHINE gutter — that is exactly where the isolation barrier is supposed to cross,
> inside the package. See §13.5.

---

### 13.2 The five net classes (184 nets total)

Every named net on the board is assigned to exactly one of five KiCad net classes. The counts are
**not aspirational** — the audit script asserts them on the routed board, and the live log shows
`Logic_Signal 80, Logic_Power 4, Safety_Rail 13, Field_Sense 66, Machine_Output 21` = **184**, with
**0 nets falling to the Default class**.

| Class | Count | Trace width | Clearance | Via (pad/drill) | What lives here |
|---|---:|---|---|---|---|
| **Logic_Signal** | **80** | 0.25 mm | 0.20 mm | 0.6 / 0.3 mm | Low-current digital: `FAST_*`, `SLOW_*`, `DRV_*`, `I2C_SDA/SCL`, `PI_UART_RX/TX`, `MCP_INT_A/B`, `RP2040_OK`, `ARM_PERMIT`, `AND_MID_ARM_RP`, `NE555_*`, `WDOG_KICK*`/`WDOG_OK*`/`WDOG_TIMING_NODE`, relay-driver bases `BASE_S/T/SP/BE/M/M2/M1`, and the status-LED locals (`LED_GATE_*`, `LED_SINK_*`) |
| **Logic_Power** | **4** | 0.50 mm | 0.20 mm | 0.8 / 0.4 mm | The rails + logic return: `VCC_5V`, `VCC_5V_RAW`, `VCC_3V3`, `GND` |
| **Safety_Rail** | **13** | 0.60 mm | 0.30 mm | 0.8 / 0.4 mm | The relay-coil enable spine + interlock control: `RELAY_ENABLE_RAIL`, `RAIL_GATE`, `COIL_LO_*` (×7), `BASE_AND_ARM`, `BASE_AND_RP_OK`, and the `SAFE_*` interlock-loop nets (`SAFE_STOP_RETURN`, `SAFE_TBSC_RETURN`) |
| **Field_Sense** | **66** | 0.30 mm | **0.40 mm** | 0.7 / 0.35 mm | Isolated machine-sense: `FIELD_FAST_*` (×8), `FIELD_SLOW_*` (×24), `FIELD_WET_V`, `FIELD_GND`, and the opto-LED series nets `FIELD_LED_*` (×32) |
| **Machine_Output** | **21** | **0.50 mm** | **0.35 mm base** (custom rules enforce real barriers — see §13.3) | 1.0 / 0.5 mm | Relay contacts + their snubber midpoints: `OUT_*_A`/`OUT_*_B` (×14, the 7 channels) and `SNUB_*` (×7) |

**Why the widths/clearances are what they are:**

- **Logic_Power 0.50 mm.** `GND`, `VCC_5V`, and `VCC_3V3` are poured planes/wide traces; the relay coils run on the 5 V rail, so `VCC_5V` carries the worst-case simultaneous coil current.
- **Safety_Rail 0.60 mm / 0.30 mm.** `RELAY_ENABLE_RAIL` carries all 7 coil currents (~0.55 A worst case). At 1 oz copper, 0.60 mm ≈ 1.6 A capacity — about 3× margin. The slightly wider 0.30 mm clearance keeps the safety-critical spine clear of logic switching noise.
- **Field_Sense 0.40 mm clearance.** Wider than logic because FIELD is on a *separate ground reference* (`FIELD_GND`) and a channel may carry 24 VAC sense.
- **Machine_Output 0.50 mm / split clearance.** Switches inductive machine-control loads. The 0.35 mm *netclass* clearance is only the same-channel local fabrication floor (a relay's own COM/NO pair and the RC snubber across that pair are intentionally adjacent). The real insulation is enforced by the custom `.kicad_dru` rules in §13.3, not the base class number.

> **Classification correction worth remembering (the `SAFE_*` reclass).** An early draft put
> `SAFE_STOP_RETURN` / `SAFE_TBSC_RETURN` in **Machine_Output**, which forced the ≥3.2 mm
> LOGIC↔MACHINE creepage against the very rail/gate those nets are supposed to drive → 7 false DRC
> violations. They are **low-voltage TB/SC interlock + Stop/CIS sense**, logic/rail-domain, not
> 250 VAC machine contacts. They were moved to **Safety_Rail** and take logic-domain clearance.
> If you ever re-derive classes, do not put the interlock-sense nets in the machine-output class.

> **A second remembered fix (the anonymous-net trap).** A blanket "`N$* → Logic_Signal`" rule would
> have been *unsafe*, because the old `N$1`–`N$32` were FIELD-side PC817 LED series nets and the old
> snubber midpoints were MACHINE-side. Those were renamed at the source in
> `scripts/generate_kicad_netlist_revB.py`, so the board now has **0 anonymous `N$` nets** and every
> net is classified by an explicit name family (`FIELD_LED_*`, `SNUB_*`, `COIL_LO_*`, `BASE_*`).

---

### 13.3 Creepage / clearance policy (the conservative 250 VAC contract)

Creepage = surface distance along the board; clearance = straight-line through air. Both must be met
across the opto/relay bodies **and** any adjacent copper. The board was sized to a deliberately
**conservative working-voltage assumption of 250 VAC RMS, pollution degree 2, basic insulation**,
even though the at-machine measurement (track A1) found the machine-output contacts working at only
**24 VAC**. The reasoning: a tighter rule satisfied by looser geometry stays satisfied if the rule
later relaxes, so routing to the wide spec is never wrong; relaxing later is a one-line DRC edit,
whereas tightening after routing would be a re-route.

| Barrier / situation | Policy number enforced | Where enforced |
|---|---|---|
| **LOGIC ↔ FIELD** (across PC817) | **≥ 2.5 mm** clearance *and* creepage | custom `.kicad_dru` rule, conditioned on `hasNetclass('Field_Sense')` |
| **LOGIC ↔ MACHINE** (across G5LE) | **≥ 3.2 mm** clearance *and* creepage | custom `.kicad_dru` rule, conditioned on `hasNetclass('Machine_Output')` |
| **Independent machine-output channel ↔ channel** | **≥ 1.5 mm** (one shorted channel must not arc to the next) | custom `.kicad_dru` rule (excludes intentional same-channel terminals) |
| Machine-output trace ↔ board edge | **≥ 1.0 mm** | DRC rule |
| Same-channel relay/snubber terminals | reviewed exception (intentionally adjacent) | `Machine_Output` 0.35 mm base clearance |

The custom rule file is `kicad/wsl-phase8b.kicad_dru`. The independent-output 1.5 mm rule
**overrides** the 0.35 mm Machine_Output base floor for inter-channel spacing; the 0.35 mm only
applies within a single channel's own terminals (e.g. `OUT_S_A` / `SNUB_S` / `OUT_S_B`).

**Optional future relax to 24 VAC.** At the measured 24 VAC working voltage these barriers could
drop to functional-insulation territory (~0.5–1.0 mm). Doing so is the prerequisite for any future
*board-size shrink* before the 16-lane fleet run — but it is a `.kicad_dru` + this-doc §13.3 edit
followed by a re-DRC and re-export, **not** a topology change. The current pilot boards ship at the
conservative 2.5 / 3.2 mm numbers.

---

### 13.4 Why no milled isolation slots are needed at 24 VAC

A common high-voltage hardening technique is to mill a slot in the board under the opto/relay body,
which boosts the *creepage* (surface) path without changing the part footprint. **Rev-B deliberately
ships with no milled isolation slots**, and the DRC/audit gates do **not** depend on slots.

The justification is voltage-specific: slots buy creepage margin that only matters at high voltage.
At the measured **24 VAC** working voltage, the 2.5 mm (LOGIC↔FIELD) and 3.2 mm (LOGIC↔MACHINE)
copper clearances already provide roughly **3–6× the functional-insulation requirement** for 24 VAC.
Adding slots would buy nothing the copper spacing does not already provide. Isolation on this board
is therefore enforced by three things only: **copper clearance, package spacing, and all-layer
no-copper rule areas (the gutters)** — never by a slot.

If a future high-voltage variant ever needs slots, treat it as a **mechanical board edit**: add the
slots, rerun DRC, re-export Gerbers/drill, and re-review the vendor preview. It is not a free change.

---

### 13.5 The all-layer keepout gutters (plane discipline)

The three domains are placed in non-overlapping vertical bands, separated by **keepout "gutters"
that forbid tracks, vias, and zones on every copper layer** (pads and footprints are still allowed,
so the opto/relay pins can sit on the gutter and bridge it inside the package). This is the 4-layer
generalization of the older single-layer keepout idea, and it is what makes the manual route
tractable and the isolation lateral *and* vertical.

| Band | X-center range (mm) | Routing meaning |
|---|---|---|
| FIELD connectors / series resistors | ~9 / ~58 | field-side routing stays left |
| OPTO barrier packages (PC817) | ~73.9–74.0 | bridge the FIELD/LOGIC isolation boundary |
| **FIELD/LOGIC keepout gutter** | **76.8–80.0** | no tracks/vias/zones on any copper layer |
| LOGIC pullups / core / safety control | ~92 / ~101–172 | logic-side routing stays center |
| Relay barrier packages (G5LE) | ~176.0–178.2 | bridge the LOGIC/MACHINE isolation boundary |
| **LOGIC/MACHINE keepout gutter** | **181.0–184.2** | no tracks/vias/zones on any copper layer |
| MACHINE suppression / connectors | ~222–242 | machine-output routing stays right |

The 4-layer stack puts the **In1.Cu GND plane** and **In2.Cu power pour (VCC_5V / VCC_3V3, logic
side only)** between F.Cu and B.Cu. The critical plane rule: **the In1 GND plane and the In2 power
pour must not extend under the FIELD or MACHINE rooms** — the gutters void them there. The live audit
confirms the board carries the GND pour plus **2 keepout rule-areas** (`[zones] count=3` →
1 filled GND zone + 2 rule areas).

> Status-LED drivers and the `J_LAMP_LED` connector sit in the *lower logic band* and never enter the
> MACHINE band, because the Rev-B status LEDs are logic-driven (low-side 2N7002 FET + current-limit
> resistor off `VCC_5V`), not isolated lamp outputs. There is intentionally **no LOGIC↔MACHINE
> isolation barrier for the status LEDs** — they are a pure logic-domain output. (Detail in Section 12.)

---

### 13.6 The DNP set (27 parts) — what is *not* populated and why

The fab package flags **27 footprints as DNP / excluded from BOM and POS** (`reports/audit-revB-board.log`
confirms `count=27`; the full list is `assembly/wsl-phase8b-revB-dnp-excluded.csv`). These are *not*
errors — they are deliberate, and assembly files (BOM + CPL) correctly omit every one of them. There
are two reasons a part is DNP on this board: it belongs to the **M1 ball-return channel** (unconfirmed
on our chassis), or it is an **inductive-suppression part** (snubber R/C or MOV) that should not be
fitted until the real load is characterized.

#### 13.6.1 M1 ball-return channel (8 parts) — DNP until machine-confirmed

M1 was never bench-confirmed as a separate relay on our SS + Omega-Tek chassis, and the FSM does not
drive it, so the entire M1 channel ships as unpopulated copper. **Do not populate or harness M1 until
it is verified at-machine.** The 8 M1 parts:

| Refdes | Value | Footprint | Role |
|---|---|---|---|
| K7 | G5LE M1 DNP | Relay_SPDT_Omron-G5LE-1 | M1 relay |
| Q7 | MMBT3904 M1 | SOT-23 | M1 relay-driver transistor |
| R85 | 1k | R_0805 | M1 base resistor |
| R86 | 100k | R_0805 | M1 drive pulldown |
| R87 | 100R DNP | R_0805 | M1 snubber resistor |
| C10 | 10nF X2 DNP | C_0805 | M1 snubber capacitor |
| D13 | 1N4148 | D_SOD-323 | M1 coil flyback diode |
| D14 | MOV DNP | D_SMA | M1 contact MOV |
| J12 | J_MOTION_M1 5.08mm | MKDS-1,5-2-5.08 | M1 motion terminal |

(Note: J12 is listed in the DNP-excluded CSV alongside the 8 M1 component parts — the M1 *terminal
block* is also excluded — so the M1 channel including its connector is fully suppressed.)

#### 13.6.2 Inductive-suppression footprints on the 6 baseline channels (RC + MOV) — DNP until load-characterized

Every motion output has footprints for an RC snubber (resistor + X2 cap) and an MOV across the
contact, but they ship **unpopulated** because the right values depend on the *measured* inductive
load at the machine. Fit them per-channel only after characterizing that channel's load.

| Channel | Snubber R (100R DNP) | Snubber C (10nF X2 DNP) | MOV (DNP) |
|---|---|---|---|
| S | R69 | C4 | D2 |
| T | R72 | C5 | D4 |
| SP | R75 | C6 | D6 |
| BE | R78 | C7 | D8 |
| M | R81 | C8 | D10 |
| M2 | R84 | C9 | D12 |

That is 6 × (R + C + MOV) = 18 suppression parts, plus the 9 M1-channel parts = **27 DNP** total.

> **Populated by contrast:** the 6 baseline relays are **K1–K6** (Omron G5LE-14, 5 VDC coil), their
> drivers are **Q1–Q6** (MMBT3904), and their flyback diodes are **D1, D3, D5, D7, D9, D11**
> (1N4148WS). The relay-coil flyback diodes are populated on all 6 baseline channels — only the
> *contact-side* suppression (snubber/MOV) is DNP. This is confirmed by the safety-rail audit, which
> shows `RELAY_ENABLE_RAIL` reaching `K1..K7` plus the flyback diodes plus pass-FET `Q14` plus `TP16`.

---

### 13.7 Test points (TP1–TP16) + mounting holes

The board carries **16 named test pads** (1.5 × 1.5 mm) for bench bring-up, plus **4 M3 mounting
holes** (3.2 mm NPTH). Test pads are excluded from BOM/POS (they are bare copper). The exact
net-to-TP map below is from `assembly/wsl-phase8b-revB-dnp-excluded.csv` and is the authoritative
probe map for Section 21 (bench bring-up).

| TP | Net | Domain | What you are looking at |
|---|---|---|---|
| TP1 | VCC_5V | LOGIC power | Protected 5 V logic/coil rail (after the SS14 reverse-polarity diode) |
| TP2 | GND | LOGIC return | Logic ground |
| TP3 | VCC_3V3 | LOGIC power | 3.3 V (from the Pico's 3V3 out) — MCP/opto-logic rail |
| TP4 | FIELD_WET_V | FIELD | Isolated dry-contact wetting supply (TMA-0505S output) |
| TP5 | FIELD_GND | FIELD | Isolated field ground — **must read distinct from GND/TP2** |
| TP6 | I2C_SDA | LOGIC signal | I²C data to the 3 MCP23017s |
| TP7 | I2C_SCL | LOGIC signal | I²C clock |
| TP8 | WDOG_KICK | LOGIC signal | Pi watchdog kick input (before the kick FET) |
| TP9 | WDOG_TIMING_NODE | LOGIC signal | NE555 timing-cap node (THRES/DISCH) — watch it ramp |
| TP10 | NE555_TRIG | LOGIC signal | NE555 trigger (with the Rev-A trigger pull-up fix) |
| TP11 | NE555_OUT | LOGIC signal | NE555 monostable output |
| TP12 | WDOG_OK_PULLDOWN | LOGIC signal | Watchdog-OK pulldown node into the rail AND chain |
| TP13 | ARM_PERMIT | LOGIC signal | Pi arm-permission GPIO (rail condition) |
| TP14 | RP2040_OK | LOGIC signal | RP2040 health/cam-stop permission (Pico GP2) — rail condition |
| TP15 | SAFE_STOP_RETURN | Safety_Rail | Bottom of the external NC interlock series loop, into the pass-FET source |
| TP16 | RELAY_ENABLE_RAIL | Safety_Rail | **The rail itself** — must be live for any relay coil to energize |

| Mounting hole | Spec |
|---|---|
| MK1–MK4 | M3, 3.2 mm NPTH (`MountingHole_3.2mm_M3`) |

The four rail-permission conditions are directly probeable: TP13 (ARM_PERMIT), TP14 (RP2040_OK),
TP15 (SAFE_STOP_RETURN, the Stop/CIS + TB/SC loop return), and TP16 (RELAY_ENABLE_RAIL, the result).
If TP16 is low with TP13/TP14 high and the loop closed, work backward through the watchdog
(TP9/TP10/TP11/TP12) and the AND chain. See Section 10 for the rail logic and Section 21 for the
bring-up sequence.

> **Silkscreen caveat for the bench.** Per-component refdes are on F.Fab (hidden on the silk to keep
> the placement check clean), and the **TP pads are not individually silk-labeled** on the current
> board — the front silk carries board ID/rev, the three domain banners, and the connector/function
> labels (`J1 PI`, `J3 FAST`, `J6 S` … `J11 M2`, `J12 M1 DNP`, `J13 LED LAMPS`, `J14 SAFETY LOOP`),
> but you will need this table (or the review PDF `review/wsl-phase8b-revB-review-layers.pdf`) to map
> TP1–TP16 by position. Adding TP silk labels is a noted future nicety, not a blocker.

---

### 13.8 The false-green net-class lesson (read this before trusting any DRC pass)

This is the single most important operational lesson in this section, and it will bite you again if
you regenerate the board. **A KiCad 10 DRC report of "0 violations" on this board is meaningless
unless you have separately confirmed that the five net classes are actually assigned to the routed
board.**

**Mechanism.** KiCad 10 stores net-class settings (the per-net pattern → class assignments) in the
**`.kicad_pro` project file**, not in the `.kicad_pcb` board file. Every isolation rule in
`wsl-phase8b.kicad_dru` is conditioned on `hasNetclass('Field_Sense' | 'Machine_Output' | 'Safety_Rail')`.
If the routed project file loses those assignments — e.g. you copy/route the board but not the
`.kicad_pro`/`.kicad_dru` sidecars — then **every net falls to the `Default` class, every
`hasNetclass()` condition matches nothing, and DRC silently enforces only the 0.2 mm default
clearance plus the physical gutters.** The isolation rules never fire. DRC reports green. The board
is *not* actually checked against the 2.5 / 3.2 / 1.5 mm barriers.

**This actually happened.** An early routed board reported 0 DRC. Re-applying the classes to a copy
of that same board and re-running the identical DRC turned **0 → 167 violations**:

| Rule | Count | Min required | Worst actual |
|---|---:|---|---|
| Safety_Rail clearance | 114 | 0.30 mm | 0.2505 mm |
| MACHINE independent-output clearance | 44 | 1.50 mm | 0.55 mm |
| LOGIC↔FIELD clearance | 5 | 2.50 mm | 0.2505 mm |
| LOGIC↔FIELD creepage | 4 | 2.50 mm | 0.2505 mm |

The route had packed traces to ~0.25 mm because the constraining rules were inert during routing.

**How it was fixed (and how the board now stays honest):**

1. `scripts/manual_route_revB.py` now **copies the `.kicad_pro`, `.kicad_prl`, and `.kicad_dru`
   sidecars** to the routed output before loading the board.
2. The route workflow **fails closed** via `assert_netclasses_active()` unless all 184 nets resolve
   to the expected classes (80 / 4 / 13 / 66 / 21).
3. Independent proof: the routed `.kicad_pro` now carries **103 net-class refs**, matching the source
   project (it had collapsed to **1** in the false-green).

**Operational rule:** the routed project (`wsl-phase8b.routed-manual.kicad_pro`) must carry the
class assignments, and you must verify it (run the audit in §13.9) **before** trusting any DRC. A DRC
run on a class-less project is worthless for this board.

> Related: FreeRouting was correctly abandoned for this board. The Specctra DSN export carries the
> base KiCad net classes but **not** the `.kicad_dru` isolation-room intent, so the autorouter routed
> straight through the inner layers and produced hundreds of LOGIC↔FIELD / LOGIC↔MACHINE creepage
> violations (4-layer pass = 473 violations; F/B-only = 625). Manual deterministic routing is the
> accepted path for this safety-critical board.

---

### 13.9 `audit_revB_board.py` — the invariant checks

Because DRC can false-green (§13.8), an **independent** Python audit verifies the things DRC does not
prove on its own. It is `scripts/audit_revB_board.py` and is run with the KiCad-bundled Python against
the routed board:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb
```

It exits non-zero on any failure. The invariants it checks, each tied to a real failure mode:

| # | Invariant asserted | Why it matters / failure mode it catches |
|---|---|---|
| 1 | **Net classes are live on THIS board** — `Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21`, **0 nets in `Default`**, and every named net (184) in a custom class | The §13.8 false-green: if classes aren't assigned, the isolation DRC is vacuous |
| 2 | **0 anonymous `N$` nets** | Anonymous nets can't be safely class-mapped (the FIELD-LED vs snubber mix-up) |
| 3 | **Safety rail reaches all 7 relay coils + a pass-FET** — `RELAY_ENABLE_RAIL` touches `K1..K7` and a `Q*` | A coil not on the rail could energize when the rail is down (defeats the safety enable) |
| 4 | **No `OUT_*` net touches the Pico** | A machine-output contact net reaching the RP2040 would bridge the MACHINE↔LOGIC barrier |
| 5 | **GND and FIELD_GND are both present and distinct** | Confirms the FIELD isolation boundary (the live log shows GND=93 pads, FIELD_GND=6 pads, 0 shared) |
| 6 | **`SAFE_STOP_RETURN` + `SAFE_TBSC_RETURN` + `RAIL_GATE` present** | The interlock loop + rail-gate nets must exist as first-class rail conditions |
| 7 | **Netted copper zones are filled** (≥1) **and ≥2 isolation keepout rule-areas present** | Confirms the GND plane poured and the two domain gutters exist as all-layer keepouts |
| 8 | **M1 channel still DNP** (≥8 DNP footprints; live board reports 27) | Prevents accidentally populating the unconfirmed ball-return channel or the suppression parts |

The live result is **`AUDIT RESULT: ALL PASS`** (`reports/audit-revB-board.log`). The fab exporter
(`scripts/export_fab_revB.py`) re-runs both KiCad DRC and this audit and **fails closed** unless both
are green, so the audit is baked into every package generation — it is not a one-off check.

> Note the audit was hardened, not weakened, over time: the critical net-class-population check (the
> one that caught the false-green) is unchanged; only the zone check was corrected to recognize
> netless keepout rule-areas as legitimate (rather than flagging them as "missing copper pours").

---

### 13.10 Critical part-locks that the layout depends on

The layout contract assumes specific parts in specific footprints. Four are **critical** — the wrong
part will damage the board or change its behavior — and are pinned with web-verified LCSC numbers in
`assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv`. Confirm these at order time.

| Part | Refdes | LCSC # | Locked spec | Why it's critical (flag any disagreement) |
|---|---|---|---|---|
| **Relay** | K1–K6 (K7 DNP) | **C116963** | Omron **G5LE-14, 5 VDC** coil | **5 VDC coil only.** The board's relay rail is 5 V — a 9/12/24 V coil will not pull in. (BOM comment says "SPDT"; the part is SPST-NO / 1 Form A — the design uses COM+NO only, NC pad empty. Functionally correct; label nit.) |
| **I/O expander** | U1, U2, U3 | **C47023** | **MCP23017-E/SO** (I²C), SOIC-28-300mil | Must be the **I²C** MCP23017, **not** the SPI MCP23S17 — the board wires SDA/SCL + address pins, not an SPI bus |
| **Optocoupler** | U4–U35 (×32) | **C5692981** | **PC817B**, DIP-4 | Confirm DIP-4 pin-1 orientation in the JLC preview; CTR bin must work with the Rev-B 2.2k field resistors |
| **Watchdog timer** | U36 | **C7593** | **NE555DR** (bipolar), SOIC-8 | **Bipolar 555.** Do not substitute a CMOS/TLC555 — it changes the watchdog timing. (Reuses the Rev-A trigger pull-up fix.) |

These four match the known-correct anchors exactly. Other footprint anchors the layout assumes (from
`scripts/generate_kicad_netlist_revB.py`): relay = `Relay_THT:Relay_SPDT_Omron-G5LE-1`; opto =
`Package_DIP:DIP-4_W7.62mm`; MCP = `Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm`; NE555 =
`Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`; Pico = `Module:RaspberryPi_Pico_SMD` (ref **A1**); isolated
wetting supply = `Converter_DCDC:..._TRACO_TMA-05xxS_..._THT` (TMA-0505S). The RP2040 fast inputs are
GP6..GP13, RP2040_OK is GP2, UART is GP0/GP1 — see Section 6/7 for the full pin map; the
`phase8_channel_allocation.md` GPIO column is stale and must be ignored.

> **Cost note for the fleet.** 250 × 225 mm 4-layer is a large board — fine for the 1–2 pilot boards,
> but before the 16-lane run, revisit (a) the optional 24 VAC creepage relax (§13.3) to shrink the
> board, and (b) trimming the several Extended-class LCSC parts (10nF, MMBT3904, 2N7002, 1N4148WS,
> AO3401) to Basic equivalents to avoid per-part JLC setup fees.

---

### 13.11 Regenerating the board safely (procedure)

If you edit the schematic/netlist or placement, the **only** trustworthy sequence is:

1. Regenerate the netlist: `scripts/generate_kicad_netlist_revB.py` → `kicad/wsl-phase8b.net`.
2. Re-place if needed: `scripts/place_components_revB.py --force` (keeps the FIELD/LOGIC/MACHINE bands + gutters).
3. **Apply the net classes to the routed board** and let it fail closed if any net is unknown or multi-matched: `scripts/apply_netclasses_revB.py --write`.
4. Re-route deterministically: `scripts/manual_route_revB.py` (copies the project/rule sidecars; asserts classes active).
5. Run DRC **with the classes confirmed live**, then the invariant audit (§13.9).
6. Re-export the fab package: `scripts/export_fab_revB.py` (re-gates DRC + audit; regenerates Gerbers, drill, BOM, CPL, DNP list, review PDF, manifest with SHA256s).
7. The one step a script cannot do for you: **upload `wsl-phase8b-revB-gerber-drill.zip` and visually inspect the vendor's layer/drill/outline preview** against `review/wsl-phase8b-revB-review-layers.pdf` (mirroring, origin, layer assignment) before ordering. Upload the *gerber* zip — **not** the `JLC_UPLOAD_READY` transport zip — as the PCB Gerber file.

This is bare-PCB fab-ready under the conservative DRC contract. It is **not** assembly/cutover-ready:
PCBA part sourcing/orientation approval, on-hardware bench bring-up (Section 21), the RP2040 v1.1
cam-stop overrun work, and the Track-B cutover gates all remain separate and downstream.


## 14. Machine Interface: C1/C2A Connectors & the Adapter Harness

This section is the physical map between the AMF 82-70 pinsetter and the Phase 8 Rev-B lane-controller board. It tells you which machine wire carries which signal, on which connector, on which contact cavity, and how that lands on the board's function-named terminals through a per-chassis **adapter harness**. Read it together with:

- **Section 13 — Rev-B Board Architecture & Safety Rail** (the board the harness lands on: the relay outputs, opto inputs, MCP23017 banks, RP2040, and the six-condition relay-enable rail).
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
| **J_SAFETY** | J14 | Phoenix MCV 1,5/4-G-3,5 → mate **MC 1,5/4-ST-3,5** (PN 1840382) | TB/SC NC loop (pins 1–2) in series with Stop/CIS NC loop (pins 3–4) |

Every motion output is an **isolated dry relay contact** (Omron **G5LE-14, 5 VDC coil**, LCSC **C116963** — see §14.8). The board never sources machine power; it only opens/closes a dry contact inside the existing machine control circuit.

---

### 14.4 The adapter-harness concept

The adapter harness is the **only** chassis-specific deliverable. It is a set of flying leads with the board-side pluggable plugs on one end (the Phoenix `…-ST-3,5` mates above, plus the 5.08 mm screw plugs for the motion terminals) and ring/spade/fork lugs on the other that land on the C1/C2A cavities (or, for the safety loop, into the machine's 24 V control path).

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
| | SC, TB | C2A interlock cams — **CONFIRM AT CUTOVER** | Dry-wetting **and** also feed the J_SAFETY hardware path |
| | DIELL-L, DIELL-R | DIELL ball-detector leads | NPN open-collector: **idle HIGH ~13–17 V, beam broken LOW ~0 V**; 12 V supply, 10 kΩ pull-up (see §14.7) |
| **J_SLOW_IN_A** | GS1–GS10 | C2A "4-bank" (≈ 41C…410U) — **per-GS# binding CONFIRM AT CUTOVER** | Dry contact, **gripped (pin standing) = CLOSED to chassis**; chassis return (§14.6) |
| | GP, OS, BS | C2A (GP ≈ 412DD, BS ≈ 112cc) — confirm | Dry contact |
| **J_SLOW_IN_B** | PBZ, PBC | C2A (≈ 21EE area) — confirm | Momentary dry contact |
| | Foul (Radaray) | Foul-detector lead | Edge; confirm form at cutover |
| | 10th / MAN_T/S/SWS/SWSR / AUX | Spare (future) | — |
| **J_LAMP_LED** | L_FIRST/SECOND/STRIKE/FOUL | **Our LEDs in the mask housings** | 5 V logic via low-side FET; the machine's 15 VDC mask supply is abandoned |
| **J_SAFETY** | TB/SC NC loop | 24 V control path — **terminals CONFIRM AT CUTOVER** | Hardware NC series loop; first-class rail condition |
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

The cams are microswitches **on the machine** that report the sweep and table mechanism angle. Their wires enter via the machine-control plug (the OEM schematic calls it the **A&MC**, "Approach & Machine Control") and land on C2A. These are the **fast inputs** — they go to the RP2040, not the MCP23017, because they must be captured with low latency on the RP2040, which drives the fail-safe rail-permission line + the max-run backstop (per-cam-edge cam-stop *overrun* is the deferred v1.1 firmware item — Section 15).

**Electrical form (confirmed at machine, A4):** cam inputs are **dry switch closures, normally-closed.** The board's input front-end is populated for dry-contact wetting on these channels.

**Board side (firmware `config.h` — the authoritative pin map; the stale `phase8_channel_allocation.md` GPIO column must be ignored):** the eight fast inputs are opto-isolated, **active-low at the Pico** (contact closed pulls the GPIO LOW; idle HIGH via on-board 10 kΩ pull-up to 3V3), and land on **GP6–GP13**:

| Fast input | Pico GPIO | Pico pin | Netlist FAST pin | Cam role (OEM training manual) | C2A cavity |
|---|---|---|---|---|---|
| **SA** | GP6 | 9 | 9 | Sweep cam: stop @2nd guard / run-up / stop @zero (270 run-through, 360 zero) | CONFIRM AT CUTOVER |
| **SB** | GP7 | 10 | 10 | Sweep cam: stop @1st guard 66° / start table spotting 186° | CONFIRM AT CUTOVER |
| **SC** | GP8 | 11 | 11 | Sweep-under-table interlock window (~86–243°) | CONFIRM AT CUTOVER (also feeds J_SAFETY) |
| **TA1** | GP9 | 12 | 12 | Table cam: run table up / stop @zero (355° zero, 185° delay reset) | CONFIRM AT CUTOVER |
| **TA2** | GP10 | 14 | 14 | Table cam: start sweep run-through / pin-latch (260°) | CONFIRM AT CUTOVER |
| **TB** | GP11 | 15 | 15 | Table-sweep interference interlock (~105–255°) | CONFIRM AT CUTOVER (also feeds J_SAFETY) |
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

**TB/SC interlock (the hardware collision-prevention loop → J_SAFETY pins 1–2).** Per OEM, the **TB and SC cam contacts are wired in parallel in the 24 V relay-control path**; on a table/sweep collision course both open and both motor relays drop. This is the machine's hardware collision-prevention and **must be preserved as a hardware series condition on the relay-enable rail** — never softened into a firmware-only advisory input. The board exposes it as a **normally-closed series loop** on J_SAFETY pins 1–2. SC and TB are *also* read by the RP2040 as fast inputs (echo only); the **authoritative** interlock is the hardware loop. The board's `interlock_ok()` software read is explicitly a secondary echo that defaults True so software can never *enable* motion the hardware blocks.

> **CONFIRM AT CUTOVER (TB/SC terminals).** The exact terminals where the NC loop lands are deferred to cutover (easier with the machine apart). Find the TB + SC cam switches locked-out, confirm the NC loop, and land J_SAFETY pins 1–2 into it. This is a first-class rail condition (Section 10).

**Stop / CIS chain (→ J_SAFETY pins 3–4).** The machine's existing **Stop switch** (post-1979, left of the power plug) and **C.I.S.** (1981, under the plug-duct cover) are wired **in parallel and both cut the rear-panel MASTER circuit breaker** (OEM service manual p11). This upstream safety chain **stays live and intact** — the master breaker remains the final physical stop, including for a welded relay contact (the rail can drop a coil but cannot open a welded contact). J_SAFETY pins 3–4 carry the Stop/CIS sense as a second NC loop in series so the board's rail *also* requires this chain OK; the chain itself is not replaced. **CONFIRM AT CUTOVER:** continuity that Stop in RUN vs STOP drops the motor-relay coil rail.

> **Cam-stops are now solely the RP2040's job.** Bench work found the OEM machine uses **logic stops** (cam → triac driver board → coil), *not* a hardwired cam-in-series motor latch. Removing the Omega-Tek board therefore removes the existing cam-stop, and the **RP2040 hardware cam-stop replaces it** (Section 15). The TB/SC loop and the contactors' OEM regenerative braking remain as hardware backstops. Whether any bonus hardwired cam-stop survives is a non-gating "nice to have" recorded at cutover via a cam-flip test.

---

### 14.11 Per-chassis note (11/12 needs its own pass)

Everything in §14.5–§14.8 is the **21/22 (SS + Omega-Tek)** map. The **board is fleet-common; the harness and the per-channel input populations are per-chassis-type.** Before cutting over **11/12 (Active-98 MP)**, run a short field pass on that pair for the chassis-specific items: working voltage (A1), input electrical forms (A4 dry-vs-AC), and the harness map (output cavities, cam→cavity, gripper return reference, TB/SC terminals). The retrofit already diverged from OEM on M2/S cavities and on the gripper return — **do not assume 21/22's cavities carry over.** Clone the board; re-capture the harness.

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
- Exact TB/SC NC-loop terminals (J_SAFETY pins 1–2) and Stop/CIS continuity (pins 3–4).
- GP/OS/BS/Foul exact cavities + Foul electrical form.
- Whether M1 ball-return exists as a separate command on this chassis.
- The whole map again, fresh, for **lanes 11/12 (Active-98 MP)**.


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

Firmware version documented here: **`phase8b-rp2040 v0.1.0`** (the `FW_VERSION`
string in `config.h`). This is a **DRAFT, bench-bring-up-gated** firmware: it has
been host-tested and clean-cross-compiled, but it has **not been validated on a
live machine** and is **not cutover-ready** (see §15.10).

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

1. **Read 8 fast inputs, debounce them, and push edge events to the Pi over
   `uart0`.** The 8 inputs are 6 pinsetter cams (SA, SB, SC, TA1, TA2, TB) and 2
   DIELL ball-detector beams (left + right). The FSM *consumes* these events; it
   does not poll. This removes Pi scheduling jitter from cam timing.

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
  `J_SAFETY` hardware NC loop), the Stop / CIS / master-breaker chain, the NE555
  watchdog (which watches the **Pi**, not the RP2040), and the machine's
  regenerative motor braking are **all in hardware, independent of this firmware.**
- It does **not** switch any motor or coil current. It only drives a 3.3 V logic
  permission line; the relays and the machine contactors do the switching.
- It does **not**, in v0.1.0, enforce per-cam-edge cam-stop overrun — that is
  deferred to v1.1 (§15.9), and its absence is exactly what blocks cutover gate G3.

---

### 15.2 Pinout (Authoritative)

**Source of truth:** `scripts/generate_kicad_netlist_revB.py` → `block_rp2040()` and
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
| GP8 | 11 | `PIN_SC` | SC — sweep-under-table interlock cam | in | `FAST_SC` | window 86°–243° |
| GP9 | 12 | `PIN_TA1` | TA1 — table cam | in | `FAST_TA1` | 355° zero stop / 185° delay reset |
| GP10 | 14 | `PIN_TA2` | TA2 — table cam | in | `FAST_TA2` | 260° run-through / pin-latch / ball-strike decision |
| GP11 | 15 | `PIN_TB` | TB — table-sweep interference interlock cam | in | `FAST_TB` | window 105°–255° |
| GP12 | 16 | `PIN_DIELL_L` | DIELL-L — ball detect, left beam | in | `FAST_DIELL_L` | active-low opto; cushion-SS trigger |
| GP13 | 17 | `PIN_DIELL_R` | DIELL-R — ball detect, right beam | in | `FAST_DIELL_R` | active-low opto |

**Electrical sense of the fast inputs.** Every fast input is **opto-isolated** (a
**PC817B** optocoupler per channel — LCSC **C5692981**; see the Opto-Input section)
and is **active-low at the Pico**: the machine contact closing (signal asserted)
pulls the GPIO **LOW**; idle is **HIGH**. There is an on-board **10 kΩ pull-up to
3V3** on each line, and the firmware additionally enables the RP2040's internal
pull-up (`gpio_pull_up()` in `init_inputs()`) — "belt + suspenders."

**Electrical sense of `RP2040_OK`.** GP2 drives an NPN (`Q_AND_RP_OK`, an MMBT3904)
that is one transistor in the relay-enable-rail series AND chain. A **100 kΩ base
pulldown** (`Rpd_AND_RP_OK`) means the rail fails **dead** whenever GP2 is Hi-Z —
i.e. whenever the RP2040 is unpowered, in reset, or pre-`main()`. The other AND
condition in the same chain is `ARM_PERMIT` (the Pi's arm GPIO, via `Q_AND_ARM`),
and upstream of both are the NE555 watchdog OK and the external `J_SAFETY` loops.
This is the hardware that makes "GP2 LOW ⇒ no motion" true regardless of software.

> **The cams are normally-closed and the opto inverts.** Which *edge* (`f` =
> fall/asserted vs `r` = rise/released) corresponds to the angular **trip** of each
> cam is a deliberately-deferred **bench-confirmation field item** (§15.9, and
> `docs/phase8_trackB_controller_cutover_runbook.md` §3.2). The firmware reports
> both edges and lets the Pi decide; it does **not** bake in an unconfirmed polarity.

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
| `boot` | Once, at startup, before the watchdog is armed | `fw` (firmware version), `wdt_reset` (1 if this boot was caused by the watchdog), `rp_ok` (always 0 at boot) | `{"ev":"boot","fw":"phase8b-rp2040 v0.1.0","wdt_reset":0,"rp_ok":0}` | Counts as a sign of life; `wdt_reset:1` tells the Pi the chip self-reset from a hang. |
| `cam` | Debounced cam edge | `id` (SA/SB/SC/TA1/TA2/TB), `e` (`f`=asserted/fall, `r`=released/rise), `t` | `{"ev":"cam","id":"SA","e":"f","t":12345}` | On the **trip** edge: SC/TB update the interlock echo; SA/SB/TA1/TA2 are queued for the FSM. |
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

The FSM has no `cam_SC`/`cam_TB` methods — **SC and TB are interlock-only** and feed
`interlock_ok()`, not a cam handler. The other four cams map to FSM calls in
`rp2040_link.dispatch_cam()`. Because the FSM guards each handler by state, calling
**both** angle-variants of a dual-trip cam is safe — only the state-matching one
acts.

| Cam `id` (trip edge) | FSM call(s) in `dispatch_cam()` |
|---|---|
| `SA` | `controller.cam_SA_runthrough()` **and** `controller.cam_SA_zero()` |
| `SB` | `controller.cam_SB_guard()` |
| `TA1` | `controller.cam_TA1_delayreset()` **and** `controller.cam_TA1_zero()` |
| `TA2` | `controller.cam_TA2_runthrough()` |
| `SC` / `TB` | **No FSM cam call.** Updates the SC/TB danger echo → `interlock_ok()`. |
| `ball` | `controller.on_ball()` |

**The interlock echo** (`RP2040Link.interlock_ok()`): a collision course is **SC AND
TB both in their danger window at the same time**. The method returns `True` (no
veto) unless both `_sc_danger` and `_tb_danger` are set. This is a **secondary
software echo** of the authoritative hardware `J_SAFETY` loop — it can only *veto*
motion the FSM might otherwise command; it can never *enable* motion the hardware
would block. (See `docs/phase8_8270_SYSTEM_REFERENCE.md` §5 for the SC/TB collision
geometry.)

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

This is the firmware's one **active** motion safety enforcement in v0.1.0 (as opposed
to the passive health/watchdog backstop). It is the RP2040's UART-independent
equivalent of the FSM's own `MAX_MOTION_S`.

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

- **Liveness** (`is_alive()`): a heartbeat (or any `hb`/`boot`/`rp_ok`/`flt`/`ack`
  line) must have arrived within `hb_timeout` (default **1.0 s**, i.e. ~4 missed
  heartbeats).
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

### 15.9 v1 Scope vs v1.1 Deferral — and Cutover Gate G3

v0.1.0 is intentionally scoped. Two safety features are **deliberately NOT in this
firmware** because they depend on a measurement we have not yet taken on the machine.

#### Deferred to v1.1

1. **Cam-stop OVERRUN enforcement.** The desired behavior: a *stop-cam* fires while a
   motor is RUNNING and the Pi fails to `STOP` it within a short grace window → the
   firmware drops `RP2040_OK` directly. This needs the **per-cam edge → angle
   polarity** (which of `f`/`r` is the angular trip, per cam). That polarity is a
   deliberately-deferred **cutover field item**
   (`docs/phase8_trackB_controller_cutover_runbook.md` §3.2). We refuse to bake in an
   unconfirmed cam polarity into a safety path. The hook is present and marked
   `// v1.1` in `supervise()` in `main.c`, ready to be filled once polarity is
   bench-confirmed.

2. **SC/TB collision echo gating `RP2040_OK`.** The hardware `J_SAFETY` NC loop is the
   **primary** interlock and is already wired. The firmware *echo* of SC/TB into the
   rail-permission decision is enabled only once the SC/TB danger windows are
   bench-confirmed. (Today the SC/TB echo exists only on the **Pi side**, as an
   advisory `interlock_ok()` veto — it cannot enable motion the hardware blocks.)

#### What v1 provides instead

- **Firmware health** (watchdog → rail dead on hang).
- **Motion max-run backstop** (the 8 s guarded-motor timeout, §15.7) — a *coarse*
  time-based catch, **not** per-cam-edge enforcement.

#### Why this blocks Cutover Gate G3

The Track-B controller cutover runbook defines a **G3 "cam-stop rail-drop" gate**: on
the bench, a stop-cam firing while a motor runs and the Pi fails to stop it must drop
the rail within a bounded window. **v1 cannot pass G3** because it has no per-cam-edge
cam-stop — its only motion enforcement is the 8 s max-run timer, which is far coarser
than a cam-stop window. Therefore:

> **"Firmware done" ≠ "cutover ready."** v0.1.0 is *host-logic-tested + builds + happy
> path*. Cutover requires **(a)** implementing **v1.1 cam-stop overrun** and **(b)**
> on-hardware bench bring-up (§15.10). Until both land, the existing OEM controller
> stays in charge of the machines.

*(VERIFY: the exact label/letter "G3" for the cam-stop rail-drop gate — taken from the
firmware README's "G3 cam-stop rail-drop gate" wording and
`phase8_trackB_controller_cutover_runbook.md`; confirm against the current runbook's
gate list.)*

---

### 15.10 Build, Flash & Test

#### 15.10.1 Build (Pico SDK)

Requires the [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk),
`arm-none-eabi-gcc`, CMake, and Ninja (or Make).

```bash
export PICO_SDK_PATH=/path/to/pico-sdk     # or: cmake -DPICO_SDK_FETCH_FROM_GIT=ON
cd firmware/rp2040
cmake -B build -S .                          # add -DDEBUG_USB=ON to mirror events to USB-CDC
cmake --build build
# -> build/wsl_phase8b_rp2040.uf2
```

On the Westside laptop, **`pwsh -File build.ps1`** does all of the above — it
auto-discovers the bootstrapped toolchain (xpack `arm-none-eabi-gcc` 13.3.1 + WinLibs
CMake/Ninja + the cloned pico-sdk).

**Verified 2026-06-03:** clean cross-compile + link → `wsl_phase8b_rp2040.uf2`,
**~40 KB**, using **~24 KB flash / ~2.6 KB RAM** of the RP2040's 2 MB flash / 264 KB
RAM. (Huge headroom — this is a tiny, deterministic firmware.)

#### 15.10.2 Flash

| Method | When | How |
|---|---|---|
| **USB BOOTSEL** (preferred) | Bench, before the module is buried | Hold **BOOTSEL** on the Pico while connecting USB → it mounts as a mass-storage device **`RPI-RP2`** → drag-drop `wsl_phase8b_rp2040.uf2`. |
| **SWD** (fallback) | Once the module is soldered and USB isn't accessible | `picotool load -x build/wsl_phase8b_rp2040.uf2`, or OpenOCD via the board's SWD test points. |

#### 15.10.3 Host logic test (no hardware)

The pure logic — TX ring, debounce/edges, ball lockout, UART protocol, and the
`RP2040_OK` safety supervisor — has a host unit test that **mocks the Pico SDK**, so
it builds and runs on any host C compiler:

```bash
# from firmware/rp2040/
gcc -std=c11 -Wall -Wextra -I test -I test/stubs test/test_main.c -o test/test_main.exe
./test/test_main.exe        # exit 0 = all checks pass
```

**Last run: 24/24 checks passed** (2026-06-03, gcc 16.1.0), clean under
`-Wall -Wextra` plus the `printf`-format attribute (so the event format strings are
compiler-verified too).

The **Pi-side** link has its own host test (no hardware, mocks the serial transport):

```bash
# from lane_node/
python rp2040_link.py        # exit 0 = all pass
```

**Last run: 29/29 checks passed** (2026-06-03) — covers inbound parsing/health, the
SC∧TB interlock echo, full cam/ball→FSM dispatch through a strike cycle, RUN/STOP
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
2. **Inputs.** Hand-actuate each cam / break each DIELL beam → confirm the matching
   `cam`/`ball` event with the correct `id`. **This step also captures the per-cam edge
   polarity** needed for the v1.1 cam-stop hook and the cutover field sheet.
3. **Watchdog drop.** Pause the loop (or pull power to just the Pico) → GP2 → **LOW** →
   rail drops. Force a hang and confirm the next `boot` carries `wdt_reset:1`.
4. **Motion timeout.** Send `RUN S`, wait > 8 s without `STOP S` → expect
   `{"ev":"flt","code":"motion_timeout","m":"S"}` and GP2 → **LOW**. `CLEAR` → GP2 back
   **HIGH**.
5. **Only then** integrate with the rail/relay section per spec §12.9 — each relay with
   a dummy load, arm drop, interlock drop — before connecting any machine harness.

---

### 15.11 Quick Reference — Constants & Tokens

All from `firmware/rp2040/config.h` unless noted.

| Name | Value | Purpose |
|---|---|---|
| `FW_VERSION` | `"phase8b-rp2040 v0.1.0"` | Reported in the `boot` and `hb` paths. |
| `UART_BAUD` | `115200` | UART0 line rate (8N1, no flow control). |
| `DEBOUNCE_CAM_US` | `2000` µs | Cam input debounce window. |
| `DEBOUNCE_DIELL_US` | `500` µs | Ball-beam input debounce window. |
| `BALL_LOCKOUT_MS` | `300` ms | One-ball-one-event re-trigger lockout (global across both beams). |
| `HB_INTERVAL_MS` | `250` ms | Heartbeat cadence (~4 Hz). |
| `BOOT_SETTLE_MS` | `200` ms | `RP2040_OK` held LOW at least this long after boot before any permit. |
| `WDT_TIMEOUT_MS` | `250` ms | RP2040 hardware-watchdog timeout (loop hang → chip reset → rail drop). |
| `MAX_MOTION_MS` | `8000` ms | Max-run backstop window for guarded motors (matches FSM `MAX_MOTION_S`). |
| `TXR_SZ` | `512` bytes | Non-blocking TX ring size (`main.c`). |
| `DEBUG_USB` | `0` (default) | When `1`, mirror events to USB-CDC; protocol still always goes to `uart0`. |
| Commands | `RUN <m>` · `STOP <m\|*>` · `CLEAR` · `PING` | Pi → RP2040. |
| Events | `boot` · `cam` · `ball` · `rp_ok` · `flt` · `hb` · `ack` | RP2040 → Pi. |
| Guarded motors | `S`, `T`, `SP`, `M2`, `M1` | Subject to the max-run timeout. |
| Unguarded motors | `BE`, `M` | Not timed (continuous / master). |

---

### 15.12 Maintenance Notes & Gotchas

- **The pin map's only source of truth is the netlist generator**
  (`scripts/generate_kicad_netlist_revB.py`, `block_rp2040()` + `FAST_INPUTS`).
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


## 16. Pi Software: The Cycle-Control FSM

This section documents the software brain that replaces the AMF 82-70 controller logic: the **`CycleController` finite-state machine** in `lane_node/cycle_control_8270.py`. It is the controller-level sibling of the hardware described in Section 9 (Relay Outputs), Section 10 (Watchdog & Safety Rail), and Section 12 (Channel Maps), and it consumes the fast cam/ball events produced by the RP2040 firmware (Section 15). One `CycleController` instance runs per physical lane.

Everything here is grounded in two source files:

- `lane_node/cycle_control_8270.py` — the FSM itself (the code).
- `docs/phase8_8270_SYSTEM_REFERENCE.md` — the reverse-engineered AMF 82-70 sequence of operation, cam timing, I/O, and safety model that the FSM reproduces. References below of the form "(SYSTEM_REFERENCE §N)" point into that document.

> **Status / safety gate.** As written, `cycle_control_8270.py` is a **spec-derived DRAFT (R1)**. The file header states explicitly that it is NOT production until: the exact C1/C2A machine-side pins are confirmed against the service-manual schematic and the spare machine; the hardware safety chain is in place (TB/SC interlock, Stop/CIS breaker chain, NE555 watchdog, E-stop); and every cycle plus every fault case is validated off-live. Points in the code that still need confirming against the schematic or the real machine are flagged `# CONFIRM`. This manual reproduces those flags as **(VERIFY: …)** so a service engineer never mistakes a draft assumption for a measured fact. Do not let this FSM drive a live machine until the bench bring-up gate in Section 13 (Layout & Manufacturing) / the Rev-B spec §12.9 is cleared.

---

### 16.1 Why this is an event-driven FSM, not a pulse counter

The 82-70 has **no single "one pulse per cycle" trigger**. The file header records that the earlier `cycle_control.py` "SS-pulse" model is **VOID** for exactly this reason. Instead, per the AMF service manual (SYSTEM_REFERENCE §0, §2), the controller **drives the sweep and table motors itself** and **reads cam switches mounted on the motor shafts** for position, de-energizing each motor when its cam reports the target degree. AMF's own MP microprocessor chassis did the same job the same way — it directly replaced the 5-board solid-state chassis using the *same machine inputs and outputs*, changing only the logic medium (SYSTEM_REFERENCE §0, §6). The Pi controller is a modern MP chassis: read switches → run the sequence → drive relay coils and lamps.

Consequently the FSM is **event-driven**:

- **Cam edge transitions** (SA, SB, SC, TA1, TA2, TB) drive most state changes.
- **Discrete inputs** drive the rest: SS/DIELL ball detect (cycle trigger), grippers GS1–GS10 (pin read), GP gripper-protect (gates the settle delay), BS bin switch (gates fresh-rack spotting), Foul.
- A **3-second settle timer** and an **8-second per-motion safety backstop** are time-based, evaluated in `poll()`.

Each state **sets motor / solenoid / lamp outputs on entry**; each cam-event handler maps directly to one step of the SYSTEM_REFERENCE §2 sequence of operation.

---

### 16.2 The `io` interface contract (hardware abstraction)

The FSM performs **zero direct hardware access**. Every input and output goes through an injected `io` object, which is why the same FSM is fully bench-testable with a simulator and runs unchanged on real hardware. The two concrete implementations live in `lane_node/controller_io.py`:

- **`MachineIO`** — real hardware: the three MCP23017 I²C expanders (relays + status LEDs + slow inputs), the RP2040 co-processor (fast cam/ball events + the SC/TB interlock echo + RUN/STOP run-tracking), and the NE555 watchdog kick. (Pinouts and part numbers: see Section 9 and Section 12.)
- **`RecordingIO`** — a no-hardware fake that records every output call and serves scripted inputs, used to bench-test the FSM off-Pi.

The contract the FSM depends on (verbatim from the `CycleController` docstring):

| `io` method | Direction | Meaning |
|---|---|---|
| `io.set_sweep(on: bool)` | OUT | Energize / de-energize the **SWEEP** motor relay (`S`) |
| `io.set_table(on: bool)` | OUT | Energize / de-energize the **TABLE** motor relay (`T`) |
| `io.set_spot(on: bool)` | OUT | Energize the **SPOT** solenoid relay (`SP`) |
| `io.set_pin_lamps(mask: int)` | OUT | Drive the 10 mask pin lamps, or hand the mask to the camera / scoring Track A |
| `io.set_light(name, on)` | OUT | Drive a status lamp: `'first_ball'` \| `'second_ball'` \| `'strike'` \| `'foul'` |
| `io.read_grippers() -> int` | IN | 10-bit standing-pin mask from GS1–GS10 (**0 = no pins = strike**) |
| `io.gp_closed() -> bool` | IN | Gripper-protect closed — **enables** the time delay |
| `io.bs_closed() -> bool` | IN | Bin switch: 10th pin delivered (gates fresh-rack spotting) |
| `io.interlock_ok() -> bool` | IN | TB/SC collision interlock — **SECONDARY software guard** |
| `io.watchdog_kick()` | OUT | Pet the NE555 hardware watchdog |
| `io.now() -> float` | IN | Monotonic seconds (injectable for tests) |
| `io.log(msg)` | — | Diagnostic log line |

> **Critical safety note on `interlock_ok()`.** This is the **software echo** of the TB/SC interlock, not the interlock itself. The authoritative interlock is the hardware TB+SC NC loop in the relay-enable rail (Section 10; SYSTEM_REFERENCE §5). `MachineIO.interlock_ok()` returns the RP2040's SC/TB collision state when the RP2040 link is wired, and otherwise **defaults to `True`** specifically so the software echo can never *enable* motion that the hardware would block — it can only decline to command into a known-bad state. The hardware rail is what actually prevents a collision.

The mapping from these logical output names to physical relay/lamp bits is defined in `controller_io.py` (`OUT_A_MAP`) and is **locked to the PCB netlist generator** `scripts/generate_kicad_netlist_revB.py` (`OUTPUT_PINS`) — a regression test in `controller_io.py.__main__` re-derives the map from the generator and fails on any drift. The full bit map is in Section 12 (Channel Maps); the relevant motor/solenoid/lamp outputs are `S`, `T`, `SP`, and the four status lamps `first_ball` / `second_ball` / `strike` / `foul`. The fast cam/ball inputs that feed the cam-event handlers arrive from the RP2040 on **GP6–GP13** (`RP2040_OK` = GP2, UART = GP0/GP1); see Section 15.

---

### 16.3 The states

The `State` enum defines ten states:

| State (enum value) | Meaning / what is energized |
|---|---|
| `POWER_OFF` (`power_off`) | Initial state at object construction; nothing driven. |
| `MANUAL_INTERVENTION` (`manual_intervention`) | Power has been (re)applied. **Drives NOTHING** until the operator presses First-Ball-Zero. Implements the MP "Power-Down" rule (SYSTEM_REFERENCE §5). |
| `READY` (`ready`) | Machine at zero, awaiting a ball (SS/DIELL). No motors running. |
| `SWEEP_TO_GUARD` (`sweep_to_guard`) | SWEEP motor running toward the 66° guard position. |
| `GUARD_DELAY` (`guard_delay`) | Sweep stopped at guard; running the **3-second pin-settle delay** (gated by GP closed). No motors running. |
| `TABLE_DETECT` (`table_detect`) | TABLE motor running down; grippers reading standing pins. |
| `RUNTHROUGH` (`runthrough`) | SWEEP run-through to 270°. |
| `SPOTTING` (`spotting`) | **Fresh-rack cycles only:** SP energized, table doing its spotting revolution (entered after BS = bin full). |
| `TABLE_FINISH` (`table_finish`) | Table finishing through TA1; respot of held pins, or awaiting BS to start fresh-rack spotting; sweep returning. |
| `FAULT` (`fault`) | A motion exceeded `MAX_MOTION_S`. All motors commanded OFF; FSM halted in fault. |

Two supporting enums track the cycle:

- `Ball`: `FIRST` (1) / `SECOND` (2) — which ball of the frame.
- `Cycle`: `FIRST_BALL` (pins left standing on the 1st ball) / `SECOND_BALL` / `STRIKE` (no pins on 1st ball) / `FOUL` — what kind of cycle is in progress, which determines the fresh-rack-vs-respot decision (§16.6).

Instance fields: `state`, `ball`, `cycle`, `pins` (the latched 10-bit standing-pin mask for this cycle), and `_t_state` (the monotonic time the current state was entered, used for both the settle delay and the motion backstop).

---

### 16.4 Cam timing constants (the FSM triggers)

These module-level constants come from SYSTEM_REFERENCE §3 (the authoritative cam table) and are the angular trip points the cam-event handlers correspond to. They are documentation/labels — the FSM acts on the *event* of a cam edge arriving, not on a measured angle (angle measurement is a deferred field item; see §16.8).

| Constant | Value (degrees) | Cam | Role (SYSTEM_REFERENCE §3) |
|---|---|---|---|
| `SB_GUARD` | 66 | SB (sweep) | Sweep stops at first guard |
| `SB_SPOT` | 186 | SB (sweep) | Sweep initiates table spotting |
| `SA_RUNTHROUGH` | 270 | SA (sweep) | Sweep stops after run-through |
| `SA_ZERO` | 360 | SA (sweep) | Sweep stops at zero |
| `SC_LO` / `SC_HI` | 86 / 243 | SC (sweep) | Sweep-under-table **interlock** window |
| `TA1_DELAYRESET` | 185 | TA1 (table) | Table resets the time delay |
| `TA1_ZERO` | 355 | TA1 (table) | Table stops at zero |
| `TA2_RUNTHROUGH` | 260 | TA2 (table) | Table initiates sweep run-through; pin-lamp latch; ball/strike decision |
| `TB_LO` / `TB_HI` | 105 / 255 | TB (table) | Table-sweep interference **interlock** window |

Two timing constants govern the time-based behavior:

| Constant | Value | Meaning |
|---|---|---|
| `TIME_DELAY_S` | `3.0` s | Pin-settle delay at the guard, gated by GP (gripper-protect) closed. |
| `MAX_MOTION_S` | `8.0` s | Safety backstop per motor motion. **FIELD:** to be set = measured time + margin. Matches the RP2040 firmware's `MAX_MOTION_MS = 8000` (Section 15). |

---

### 16.5 Cam-event handlers → sequence of operation

Each public method on `CycleController` corresponds to one step in the SYSTEM_REFERENCE §2 sequence. The daemon (or, in tests, the simulator) calls these when the corresponding cam edge or discrete event arrives. The table below maps every handler to its trigger, its guard condition, and its effect.

| Handler / event | Fires when | Acts only if state is… | Effect (outputs + transition) |
|---|---|---|---|
| `power_restore()` | 115 VAC (re)applied | any | All motors OFF; → `MANUAL_INTERVENTION`. (SYSTEM_REFERENCE §5 Power-Down) |
| `first_ball_zero()` | Operator presses First-Ball-Zero (PBZ) | `MANUAL_INTERVENTION` | Set `ball=FIRST`; `first_ball` lamp ON; → `READY`. |
| `first_ball_zero()` | Operator presses PBZ again | `READY` | Toggle 1st/2nd-ball memory (manual intervention; §5). |
| `on_ball()` | SS / DIELL beam break (ball thrown) | `READY` **and** `interlock_ok()` | Choose `Cycle` (FIRST_BALL or SECOND_BALL); energize SWEEP toward 66°; → `SWEEP_TO_GUARD`. Ignored otherwise. |
| `on_foul()` | Foul detector (Radaray) fires | any | `foul` lamp ON; if 1st ball, set `cycle=FOUL`. |
| `cam_SB_guard()` | Sweep reaches **66°** (SB) | `SWEEP_TO_GUARD` | SWEEP OFF; → `GUARD_DELAY` (starts the 3 s settle). |
| `cam_TA2_runthrough()` | Table reaches **260°** (TA2) | `TABLE_DETECT` | **Latch** `pins = read_grippers()`; drive pin lamps; if FIRST_BALL with `pins==0` reclassify as STRIKE (strike lamp ON, first-ball lamp OFF); energize SWEEP run-through; → `RUNTHROUGH`. |
| `cam_SA_runthrough()` | Sweep reaches **270°** (SA) | `RUNTHROUGH` | SWEEP OFF; → `TABLE_FINISH`. (Fresh-rack cycles will then wait for BS; respot completes at TA1 zero.) |
| `cam_TA1_delayreset()` | Table passes **185°** (TA1) | — | Resets the time-delay memory (SYSTEM_REFERENCE §2). **No motor change.** |
| `cam_TA1_zero()` | Table reaches **355°/zero** (TA1) | `SPOTTING` | SP OFF; TABLE OFF; `_finish_cycle()`. |
| `cam_TA1_zero()` | (same) | `TABLE_FINISH` | TABLE OFF; `_finish_cycle()`. |
| `cam_SA_zero()` | Sweep reaches **360°/zero** (SA) | `TABLE_FINISH` or `SPOTTING` | SWEEP OFF. |
| `bin_full()` | BS closes — 10th pin delivered to bin | `TABLE_FINISH` **and** fresh-rack **and** `interlock_ok()` | Energize SP; → `SPOTTING`. (No-op on a 1st-ball respot; blocked if interlock open.) |

Internal helpers:

- **`_finish_cycle()`** — end-of-cycle bookkeeping (SYSTEM_REFERENCE §2): flips the ball memory (FIRST_BALL/FOUL → SECOND ball; SECOND_BALL/STRIKE → FIRST ball), sets the 1st/2nd-ball lamps accordingly, clears the strike and foul lamps, clears `cycle`, and returns to `READY`.
- **`_toggle_ball()`** — flips `ball` and the two ball lamps (used by the manual PBZ override in `READY`).
- **`_safe_sweep()` / `_safe_table()`** — the in-FSM interlock gate (§16.7).
- **`_all_motors_off()`** — drives `S`, `T`, `SP` all OFF.

A complete first-ball-with-pins cycle therefore walks: `READY` → (`on_ball`) `SWEEP_TO_GUARD` → (`cam_SB_guard`) `GUARD_DELAY` → (poll, after 3 s + GP) `TABLE_DETECT` → (`cam_TA2_runthrough`) `RUNTHROUGH` → (`cam_SA_runthrough`) `TABLE_FINISH` → (`cam_TA1_zero`) `READY` (now on 2nd ball). A strike or 2nd-ball (fresh-rack) cycle inserts the `SPOTTING` state between `TABLE_FINISH` and `READY` once `bin_full()` fires.

---

### 16.6 Fresh-rack vs. respot logic

The single most important branching decision in the FSM is **whether the cycle spots a brand-new full rack of pins (energizing the SPOT solenoid `SP`) or merely respots the pins that were already standing (no `SP`)**. This is decided by `_needs_fresh_rack()`:

| `Cycle` | `_needs_fresh_rack()` | Behavior |
|---|---|---|
| `SECOND_BALL` | **True** | Fresh rack. After run-through, wait for **BS** (bin full); BS → energize `SP` → table spotting revolution. (SYSTEM_REFERENCE §2 SECOND BALL.) |
| `STRIKE` | **True** | Fresh rack, same SP path as 2nd ball. (SYSTEM_REFERENCE §2 STRIKE.) |
| `FOUL` | **True** *(provisional)* | Treated as fresh-rack here. **(VERIFY: foul respot semantics — the code treats FOUL as fresh-rack as a placeholder; per SYSTEM_REFERENCE §2 a foul flips to 2nd ball after a table spotting revolution, but exact foul respot behavior is to be confirmed on the bench before live.)** |
| `FIRST_BALL` (pins left) | **False** | **Respot** the held standing pins — no `SP`, no BS gating. Completes directly at TA1 zero. |

Mechanically this works because of *where* the standing-pin mask is latched and *what* gates the SP path:

1. At **TA2 = 260°** (`cam_TA2_runthrough`), the grippers are read and `pins` is latched (SYSTEM_REFERENCE §2: pin lamps latch at 260°). If this is a first ball and `pins == 0`, the cycle is reclassified `STRIKE` on the spot.
2. After the sweep run-through stops at **SA = 270°** (`cam_SA_runthrough`), the FSM enters `TABLE_FINISH`. For a respot (`FIRST_BALL`), there is no new rack to deliver, so the cycle simply completes when the table returns to **TA1 zero**.
3. For a fresh rack (`SECOND_BALL` / `STRIKE` / `FOUL`), the new rack of 10 pins must first arrive in the bin. The **bin switch BS** closing (`bin_full()`) is the gate: it energizes `SP` and enters `SPOTTING`. The spotting revolution then returns the table to **TA1 zero**, at which point `SP` is released and the cycle completes.

> **(VERIFY: SP de-energize timing.)** `cam_TA1_zero()` releases `SP` when the table reaches zero out of `SPOTTING`. The code marks this `# CONFIRM` — the exact SP de-energize timing vs. the cam, and whether SP is a pulse or held continuous through the spotting revolution, must be confirmed on the bench. (SYSTEM_REFERENCE §2/§4 note the SP spot relay; the as-built SP path on our chassis is harness-resolved, see Section 14.)

> **(VERIFY: BS / SP machine-side pins.)** The FSM source annotates the BS input as "BS → C2A-112cc" and the SP output as "SP → C1-35U/36Y", and various cam handlers annotate C2A cavities (e.g. "cam SA → C2A-31N", "cam TA1 → C2A-34N"). **These C1/C2A cavity bindings are explicitly unverified.** The Rev-B PCB is deliberately function-named precisely because the OEM wire tables and our bench (SS chassis + Omega-Tek retrofit) disagree on cavity routing; the adapter harness resolves cavities at cutover (see Section 14, Machine Interface, and the Rev-B spec §3.2/§7). Do **not** treat any C1/C2A pin in the FSM comments as a wiring instruction.

---

### 16.7 In-FSM safety

The FSM contains four software safety mechanisms. **Every one of them has an independent hardware backstop** — the software guards are echoes and conveniences, never the sole protection. (Hardware safety: Section 10, Watchdog & Safety Rail; SYSTEM_REFERENCE §5.)

**1. Interlock gate on every motor energize.** Both `_safe_sweep(True)` and `_safe_table(True)` first check `io.interlock_ok()`; if the interlock is open, the energize is **refused and logged**, not performed. `bin_full()` likewise refuses to energize `SP` if the interlock is open, and `on_ball()` refuses to start a cycle at all if the interlock is open. The authoritative interlock is the hardware **TB + SC** NC loop wired in series with the relay-enable rail (Section 10); this software gate simply avoids commanding into a state the hardware would block.

**2. Power-down rule → require First-Ball-Zero.** `power_restore()` puts the FSM in `MANUAL_INTERVENTION` and drives **nothing**. The machine will not move until the operator deliberately presses **First-Ball-Zero** (`first_ball_zero()`), which is the only transition out of `MANUAL_INTERVENTION`. This reproduces the AMF MP "Power-Down" feature (SYSTEM_REFERENCE §5): after any 115 VAC loss while bowling, there is **no machine motion on power restore** until a deliberate operator action. It is the controller-level sibling of the NE555 watchdog (which drops the rail if the Pi dies).

**3. `MAX_MOTION_S` fault.** `poll()` enforces an **8-second backstop on every motion state** (`SWEEP_TO_GUARD`, `TABLE_DETECT`, `RUNTHROUGH`, `SPOTTING`, `TABLE_FINISH`). If a motion never reports complete within `MAX_MOTION_S` of entering the state, the FSM **commands all motors OFF and latches `FAULT`**. This protects against a missed cam edge that would otherwise leave a motor energized indefinitely. The RP2040 firmware runs an independent, UART-independent copy of this same backstop (`MAX_MOTION_MS`, Section 15), so a stuck motor is caught even if the Pi-side FSM itself hangs. `GUARD_DELAY` is intentionally excluded from the backstop because no motor is energized during the settle.

**4. Watchdog kick every poll.** `poll()` calls `io.watchdog_kick()` on **every** invocation (it is the first line of `poll()`). If the FSM stops polling — because the process died, hung, or was killed — the NE555 hardware watchdog stops being petted and **drops all relays** (Section 10). The recommended poll cadence is ~20–50 Hz (`poll()` docstring).

> **(VERIFY: `MAX_MOTION_S` field value.)** The `8.0` s value is a draft backstop. The FSM comment instructs setting it to the **measured** longest motion plus margin during bench validation. Confirm the real sweep/table/spot motion durations on the spare machine and set both `MAX_MOTION_S` (Python) and `MAX_MOTION_MS` (firmware) accordingly before live.

---

### 16.8 State-transition table

The complete transition set. "Guard" lists any precondition; if the guard fails the event is ignored (logged) and the state is unchanged. Outputs shown are those changed on the transition.

| From state | Event | Guard | Outputs changed | To state |
|---|---|---|---|---|
| any | `power_restore()` | — | S/T/SP → OFF | `MANUAL_INTERVENTION` |
| `MANUAL_INTERVENTION` | `first_ball_zero()` | (at zero — daemon-checked) | `first_ball` lamp ON | `READY` |
| `READY` | `first_ball_zero()` | — | toggle ball lamps | `READY` |
| `READY` | `on_ball()` | `interlock_ok()` | SWEEP ON | `SWEEP_TO_GUARD` |
| `READY` | `on_ball()` | interlock open → **ignored** | — | `READY` |
| `SWEEP_TO_GUARD` | `cam_SB_guard()` | — | SWEEP OFF | `GUARD_DELAY` |
| `GUARD_DELAY` | `poll()` | `gp_closed()` **and** elapsed ≥ `TIME_DELAY_S` | TABLE ON | `TABLE_DETECT` |
| `TABLE_DETECT` | `cam_TA2_runthrough()` | — | latch `pins`; pin lamps; (strike → strike lamp); SWEEP ON | `RUNTHROUGH` |
| `RUNTHROUGH` | `cam_SA_runthrough()` | — | SWEEP OFF | `TABLE_FINISH` |
| `TABLE_FINISH` | `bin_full()` | fresh-rack **and** `interlock_ok()` | SP ON | `SPOTTING` |
| `TABLE_FINISH` | `bin_full()` | not fresh-rack → **no-op** | — | `TABLE_FINISH` |
| `TABLE_FINISH` | `cam_TA1_zero()` | — | TABLE OFF; `_finish_cycle()` | `READY` |
| `SPOTTING` | `cam_TA1_zero()` | — | SP OFF; TABLE OFF; `_finish_cycle()` | `READY` |
| `TABLE_FINISH` / `SPOTTING` | `cam_SA_zero()` | — | SWEEP OFF | (unchanged) |
| `TABLE_FINISH` / `SPOTTING` | `cam_TA1_delayreset()` | — | none (resets delay memory) | (unchanged) |
| `SWEEP_TO_GUARD` / `TABLE_DETECT` / `RUNTHROUGH` / `SPOTTING` / `TABLE_FINISH` | `poll()` | elapsed > `MAX_MOTION_S` | **all motors OFF** | `FAULT` |
| `FAULT` | — | (no automatic exit; recovery is operator/daemon-driven) | — | `FAULT` |

> **`_finish_cycle()` ball-memory rule** (applied on every transition to `READY` via cycle completion): FIRST_BALL or FOUL → next is **2nd ball**; SECOND_BALL or STRIKE → next is **1st ball**. Strike and foul lamps are cleared; `cycle` is cleared.

ASCII state diagram (happy-path cycle; the `FAULT` and `MANUAL_INTERVENTION` edges apply broadly and are summarized in the table above):

```
                power_restore()                 first_ball_zero()
  (any) ───────────────────────▶ MANUAL_INTERVENTION ───────────────▶ READY ◀────────────┐
                                                                         │                 │
                                                          on_ball() [interlock_ok]         │
                                                                         ▼                 │
                                                                  SWEEP_TO_GUARD           │
                                                              cam_SB_guard() │             │
                                                                             ▼             │
                                                                       GUARD_DELAY         │
                                              poll() [GP closed, ≥3 s]      │              │
                                                                            ▼              │
                                                                      TABLE_DETECT         │
                                                       cam_TA2_runthrough()  │  (latch pins;│
                                                                             ▼   strike?)   │
                                                                        RUNTHROUGH          │
                                                          cam_SA_runthrough() │             │
                                                                             ▼              │
                                                                       TABLE_FINISH         │
                                                       ┌─────────────────────┴───────────┐ │
                                          fresh rack:  │ bin_full() [BS, interlock]       │ │ respot (1st ball, pins left):
                                          SP ON        ▼                                  │ │ cam_TA1_zero() ─▶ _finish_cycle()
                                                   SPOTTING                               │ │
                                          cam_TA1_zero() │ SP OFF, _finish_cycle()        │ │
                                                         └────────────────────────────────┘─┘
   any motion state, poll() elapsed > MAX_MOTION_S  ───────────────────────────▶  FAULT  (all motors OFF)
```

---

### 16.9 Bench simulator (validation harness)

`cycle_control_8270.py` ships with a self-contained bench simulator under `if __name__ == "__main__":`. Running `python cycle_control_8270.py` (exit code 0 = all assertions pass) drives a fake machine (`SimIO`) that emits cam events on a timeline as the motors "run," and injects `bin_full()` on fresh-rack cycles so the SP spotting path executes. It asserts the full state flow plus the three behaviors that matter most:

- **1st-ball-with-pins respot** (7+10 left → respot, no SP, advances to 2nd ball).
- **2nd-ball / strike fresh-rack** (all down → SP energized during `SPOTTING`, SP released after, resets to 1st ball).
- **Interlock guard** (`on_ball()` is ignored when `interlock_ok()` is False).

A second, richer harness lives in `controller_io.py.__main__`: it drives the *real* FSM through a strike cycle using `RecordingIO`, asserts the SP-on-fresh-rack output sequence and that `poll()` kicks the watchdog, and then runs the **pin-map regression guard** that verifies `OUT_A_MAP` / `IN_A_MAP` still match the PCB netlist generator (`scripts/generate_kicad_netlist_revB.py`) — the check that catches the BS/OS, M1/M2, and strike/foul bit-swap class of errors. These two harnesses are the off-live proof that the FSM satisfies its `io` contract and that the software bit maps match the as-built board; they do **not** substitute for the on-machine bench bring-up gate.


## 17. Pi Software: IO Layer, RP2040 Link & Controller Daemon

This section documents the three Python modules that run **on the Raspberry Pi** and turn the rev-B controller board into a working AMF 82-70 lane controller:

| File (in `lane_node/`) | Class(es) | Job |
|---|---|---|
| `controller_io.py` | `MachineIO`, `RecordingIO` | The hardware `io` object the cycle FSM drives: 3× MCP23017 over I²C (relays, lamps, slow inputs), gripper-mask read, watchdog kick, arm-relay control. `RecordingIO` is the no-hardware test fake. |
| `rp2040_link.py` | `RP2040Link` (+ `dispatch_cam`) | The Pi side of the UART link to the on-board RP2040 co-processor: parses fast cam/ball events, dispatches them to the FSM, echoes the SC/TB interlock, tracks RP2040 health, and sends `RUN`/`STOP`/`CLEAR`/`PING`. |
| `controller_daemon.py` | `BoardController`, `run()` | Assembles `RP2040Link` + `MachineIO` + the cycle FSM per lane and runs the real-time control loop, including the health-loss safety trip and the SIGTERM safe-off. |

These modules sit **above** the rev-B board hardware (Sections 5–13) and **beside** the RP2040 firmware (Section 15 — RP2040 Firmware & Cam Timing). They are driven by, and drive, the cycle finite-state machine in `lane_node/cycle_control_8270.py` (`CycleController`), whose state sequence is described in Section 3 — *The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing*.

> **Where this fits in the safety architecture.** Everything in this section is the **software half** of the controller. The authoritative safety devices are all in **hardware**: the six-condition relay-enable rail (Section 10 — *NE555 Watchdog + Relay-Enable Rail*), the RP2040's fail-safe `RP2040_OK` line (Section 15), the TB/SC collision interlock as a hardware NC loop on `J_SAFETY`/J14 (Section 11), the Stop/CIS/master-breaker chain (Section 14), and regenerative motor braking on the machine's own contactors. **No software in this section can enable motion that the hardware rail would block.** The software's safety contribution is *additive*: it drops the arm GPIO and latches the FSM into a manual-recovery state when it detects trouble, so the operator and the FSM also see the fault. Read Sections 10 and 15 before relying on any statement here.

---

### 17.1 The FSM `io` Contract (what both IO classes implement)

`CycleController` is written entirely against an abstract `io` interface — it never touches a GPIO or an I²C register directly. Both `MachineIO` (real hardware) and `RecordingIO` (test fake) implement the same method set, which is why the exact same FSM code runs on the bench laptop and on the Pi. The contract:

| Method | Direction | Meaning |
|---|---|---|
| `set_sweep(on)` | output | Energize/de-energize the **S** (sweep) relay. |
| `set_table(on)` | output | Energize/de-energize the **T** (table) relay. |
| `set_spot(on)` | output | Energize/de-energize the **SP** (spot solenoid) relay. |
| `set_light(name, on)` | output | Drive a status lamp: `first_ball` / `second_ball` / `strike` / `foul`. |
| `set_pin_lamps(mask)` | output | Drive the optional 10-bit physical pin mask (OUT-B). No-op in the camera-scoring baseline. |
| `read_grippers()` | input | Return a 10-bit standing-pin mask (bit *n*−1 = GS*n* standing). |
| `gp_closed()` | input | Gripper-protect switch state. |
| `bs_closed()` | input | Bin/#9 switch state. |
| `read_input(name)` | input | Generic slow-input read used by the daemon (`PBZ`, `PBC`, `Foul`, `OS`, …). |
| `interlock_ok()` | input | **Secondary** software echo of the TB/SC interlock (see §17.3, §17.4). |
| `watchdog_kick()` | housekeeping | Pet the NE555 watchdog. Called by `CycleController.poll()`. |
| `arm(on)` | housekeeping | Assert/deassert the relay-enable **arm** GPIO (power-down rule). |
| `now()` | housekeeping | Monotonic clock (injectable, for delay tests). |
| `log(msg)` | housekeeping | Log a line. |

Two behaviours of this contract are load-bearing for safety and are easy to get wrong when extending the code:

- **`poll()` kicks the watchdog.** The NE555 is petted *only* from inside the FSM's `poll()` (via `io.watchdog_kick()`), which the daemon calls once per tick. If the control loop stalls, the kicks stop, and the NE555 drops the rail in hardware (Section 10). This coupling is deliberate and must be preserved (contrast with the Track-A scoring node, where scoring must **never** be able to stop the machine).
- **`arm(on)` only *gates* the rail.** Asserting arm does not energize anything by itself; the rail still requires watchdog-OK, RP2040-OK, cam-stop-OK, TB/SC, and the Stop/CIS chain (Section 10, §4.1). De-asserting arm is a real, hardware-honored disable.

---

### 17.2 `controller_io.py` — `MachineIO` (real hardware)

`MachineIO` is the concrete `io` for **one lane / one board**. Construction opens that board's own I²C bus and the three MCP23017 expanders, and accepts the RP2040 link and the two safety GPIO callables by dependency injection so the transport stays testable and pluggable.

#### 17.2.1 Constructor

```python
MachineIO(lane_id, bus_id, *, watchdog_kick=None, arm_relays=None,
          now=None, enable_pin_lamps=False, rp2040=None)
```

| Arg | Meaning |
|---|---|
| `lane_id` | Lane number this board controls (one board per lane — Section 5). |
| `bus_id` | Pi I²C bus number for **this** board (per-board bus — Section 7). |
| `watchdog_kick` | `callable()` that pets the NE555 (e.g. the daemon's GPIO pulse). Defaults to a no-op. |
| `arm_relays` | `callable(bool)` that drives the board's **arm** GPIO (the `ARM_PERMIT` rail condition). Defaults to a no-op. |
| `now` | Monotonic clock, injectable; defaults to `time.monotonic`. |
| `enable_pin_lamps` | If `True`, also open OUT-B (0x23) for the optional physical pin mask. Default `False` — the camera supplies pin state in the baseline. |
| `rp2040` | An `RP2040Link` (or `None`). When present, `MachineIO` echoes its SC/TB interlock through `interlock_ok()` **and** sends `RUN`/`STOP` to the firmware whenever a motion relay toggles. |

The constructor imports `smbus2` (falling back to `smbus`) **lazily** so the module — and the `RecordingIO` test path — load on any machine without I²C hardware. It then configures the MCPs (all-inputs for IN-A/IN-B with pull-ups on, all-outputs for OUT-A) and logs the bus + addresses.

> **Pi-only dependency:** `MachineIO` needs `smbus2` (or `smbus`) on the Pi for the MCP23017s. The library import is deferred to construction time, not module import time.

#### 17.2.2 The three MCP23017 expanders and their I²C addresses

Each board carries three MCP23017 I²C I/O expanders (part **MCP23017-E/SO**, LCSC **C47023** — see Section 9/Section 14; this is the **I²C** MCP23017, *not* the SPI MCP23S17). They sit on the board's **own** I²C bus, and every board repeats the same address set, because each board has its own bus (so there is no address collision across a lane pair). A fourth address, 0x23, is reserved for the optional pin-lamp expander.

| Constant | Address | Role | `dir_mask_a` / `dir_mask_b` | Pull-ups | Populated in baseline? |
|---|---|---|---|---|---|
| `ADDR_IN_A` | **0x20** | Grippers GS1–10 + GP/OS/BS/PBZ/PBC/Foul | `0xFF` / `0xFF` (all inputs) | `0xFF` / `0xFF` (all on) | Yes |
| `ADDR_IN_B` | **0x21** | 10th-frame + manual + spare inputs | `0xFF` / `0xFF` (all inputs) | `0xFF` / `0xFF` (all on) | Yes (initialized; **not yet read** by the FSM) |
| `ADDR_OUT_A` | **0x22** | 7 relay drives + 4 status-lamp drives | `0x00` / `0x00` (all outputs) | — | Yes |
| `ADDR_OUT_B` | **0x23** | Optional physical pin lamps + neon | `0x00` / `0x00` (all outputs) | — | **No** (only opened if `enable_pin_lamps=True`) |

In the MCP23017 IODIR convention used here, **`1` = input, `0` = output**. IN-A and IN-B are therefore `0xFF` on both ports (all inputs, all internal pull-ups enabled); OUT-A is `0x00` (all outputs). The expander A2/A1/A0 address-strap wiring that produces these addresses lives in the netlist `block_mcp()` calls — `MCP_IN_A` straps `(0,0,0)`→0x20, `MCP_IN_B` straps `(1,0,0)`→0x21, `MCP_OUT_A` straps `(0,1,0)`→0x22 (see Section 7).

> **3.3 V, not 5 V.** All three MCP23017s and every opto logic-side pull-up run on the **3.3 V** rail (`VCC_3V3`, the Pico's 3V3 output), specifically so the I²C bus and all logic highs stay Pi-safe (Section 6 — *Rev-B Power Architecture*). Do not move them to 5 V.

#### 17.2.3 The `_MCP23017` driver

`_MCP23017` is a minimal smbus driver. The register constants are the **bank-0 / IOCON.BANK=0 default** mapping:

| Register | Address (port A / port B) |
|---|---|
| `IODIR` (direction) | `0x00` / `0x01` |
| `GPPU` (pull-up enable) | `0x0C` / `0x0D` |
| `GPIO` (read) | `0x12` / `0x13` |
| `OLAT` (output latch) | `0x14` / `0x15` |

Key behaviours:

- **Latch caching.** The driver caches `OLATA`/`OLATB` (`self._olat`) so a per-bit `write_bit(port, bit, value)` does not have to read-modify-write the bus — it updates the cached byte and writes it. This matters because the FSM toggles individual relay/lamp bits frequently inside a cycle.
- **`read_port(port)`** reads `GPIOA` (port 0) or `GPIOB` (port 1) and returns the raw byte.
- **`all_off()`** zeros both output latches in one pair of writes — used on fault/shutdown.
- **Port convention used throughout:** **port 0 = GPIOA / OLATA**, **port 1 = GPIOB / OLATB**.

#### 17.2.4 Output bit map — `OUT_A_MAP` (chip 0x22)

> **SOURCE OF TRUTH.** `OUT_A_MAP` is the Pi-side mirror of `OUTPUT_PINS` in `scripts/generate_kicad_netlist_revB.py`. **The routed rev-B board is wired from the generator, so these MUST match it.** A self-test at the bottom of `controller_io.py` re-derives the expected map from the generator's AST and `assert`s equality on every run — this exists specifically because Codex caught BS/OS, M1/M2, and strike/foul swaps on 2026-06-03. The values below are the current, correct, regression-locked map.

MCP pin numbering: **GPA0–7 = MCP pins 21–28**, **GPB0–7 = MCP pins 1–8**. So `_pin_to_portbit`: pin 21–28 → `(0, pin−21)`; pin 1–8 → `(1, pin−1)`.

| FSM name | (port, bit) | MCP pin / GP line | Generator key | Function |
|---|---|---|---|---|
| `S` | (0, 0) | pin 21 / GPA0 | `S` | Sweep relay |
| `T` | (0, 1) | pin 22 / GPA1 | `T` | Table relay |
| `SP` | (0, 2) | pin 23 / GPA2 | `SP` | Spot solenoid |
| `BE` | (0, 3) | pin 24 / GPA3 | `BE` | Back-end (future) |
| `M` | (0, 4) | pin 25 / GPA4 | `M` | Master (future) |
| `M2` | (0, 5) | pin 26 / GPA5 | `M2` | Sweep reverse — **M2 sits before M1** (per generator order) |
| `M1` | (0, 6) | pin 27 / GPA6 | `M1` | Ball return — **DNP / populate-optional** (not bench-confirmed; FSM doesn't drive it) |
| `first_ball` | (0, 7) | pin 28 / GPA7 | `L_FIRST` | 1st-ball lamp |
| `second_ball` | (1, 0) | pin 1 / GPB0 | `L_SECOND` | 2nd-ball lamp |
| `strike` | (1, 1) | pin 2 / GPB1 | `L_STRIKE` | Strike lamp |
| `foul` | (1, 2) | pin 3 / GPB2 | `L_FOUL` | Foul lamp |

The generator-key column shows the name translation the self-test applies: the lamp outputs are `L_FIRST`/`L_SECOND`/`L_STRIKE`/`L_FOUL` in the netlist but `first_ball`/`second_ball`/`strike`/`foul` in the FSM. The relay drives carry the same names in both.

> **M1 is DNP.** The M1 (ball-return) channel — relay, driver, snubber/MOV, and connector — is present as copper but **Do Not Populate** until ball-return is confirmed to exist as a separate command on this chassis. The FSM does not drive M1. See Section 9/Section 14 §3.2.

#### 17.2.5 `MOTION_RELAYS` vs lamps

```python
MOTION_RELAYS = ("S", "T", "SP", "BE", "M", "M1", "M2")
```

This tuple distinguishes the seven **motion relays** from the four status **lamps** (`first_ball`/`second_ball`/`foul`/`strike`). Its only job: in `_set_out()`, when an RP2040 link is wired and a *motion relay* toggles, `MachineIO` also sends the firmware a `RUN <name>` (on) or `STOP <name>` (off) so the RP2040's motion max-run backstop knows what is energized. **Lamps are never sent to the firmware** — they aren't motors and aren't on the safety rail.

> Note the asymmetry between `MOTION_RELAYS` (includes `BE` and `M`) and which of those motors the **firmware** actually time-guards. Per Section 15 / `firmware/rp2040/main.c`, `BE` (continuous back-end) and `M` (master/power) are **not** max-run-guarded — they are tracked but never time out. So `MachineIO` will send `RUN BE` / `RUN M`, and the firmware accepts them but does not apply the 8 s backstop to them.

#### 17.2.6 Output methods

- `set_sweep(on)` → `_set_out("S", on)`, `set_table(on)` → `_set_out("T", on)`, `set_spot(on)` → `_set_out("SP", on)`.
- `_set_out(name, on)` writes the OUT-A bit per `OUT_A_MAP`, then — if `rp2040` is wired and `name in MOTION_RELAYS` — calls `self._rp2040.run(name)` / `.stop(name)`.
- `set_light(name, on)` validates `name ∈ {first_ball, second_ball, foul, strike}` (warns and returns on an unknown lamp) and routes through `_set_out` (so lamps share the OUT-A write path but are excluded from the RUN/STOP sidechannel).
- `set_pin_lamps(mask)` is a **no-op unless** `enable_pin_lamps` is true *and* OUT-B exists. When active, it writes 10 bits across OUT-B: bits 0–7 → port 0, bits 8–9 → port 1 (`(0, i)` for `i < 8`, else `(1, i−8)`). In the camera-scoring baseline the physical mask is omitted and this method does nothing.

#### 17.2.7 Input methods, polarity, and the gripper mask

```python
INPUT_ACTIVE_LOW = True
```

The PC817 optos (part **PC817B**, LCSC **C5692981** — Section 8/Section 14) are **active-low at the MCP pin**: a closed field contact pulls the opto, which pulls the MCP pin **LOW**. So **"asserted / closed / standing" = pin reads 0**. `INPUT_ACTIVE_LOW = True` encodes that globally; the comment notes you would only set a channel active-high if a particular front-end were wired the other way.

- `_read_in(name)` reads the IN-A bit per `IN_A_MAP` and returns `raw == 0` (when active-low). Used by `gp_closed()`, `bs_closed()`, and `read_input(name)`.
- `read_grippers()` reads **both ports of IN-A once each** (`p0`, `p1`), then slices the ten gripper bits in `GRIPPER_ORDER` and builds the standing-pin mask, where **bit *i* = GS(*i*+1) standing** (a pin reads 0 when standing, which sets its mask bit). Reading each port once — rather than per-bit — keeps the gripper snapshot atomic and cheap.
- `read_input(name)` is the generic slow-input read the daemon uses for `PBZ`, `PBC`, `Foul`, `OS`, etc.

```python
GRIPPER_ORDER = [f"GS{i}" for i in range(1, 11)]   # GS1=bit0 ... GS10=bit9
```

#### 17.2.8 Slow-input bit map — `IN_A_MAP` (chip 0x20)

> **SOURCE OF TRUTH.** `IN_A_MAP` mirrors the `MCP_IN_A` entries of `SLOW_INPUT_PINS` in the netlist generator and is regression-locked by the same self-test (`FOUL`→`Foul` is the only name translation). Same MCP pin numbering as §17.2.4 (GPA0–7 = pins 21–28, GPB0–7 = pins 1–8).

| FSM name | (port, bit) | MCP pin / GP line | Meaning |
|---|---|---|---|
| `GS1` | (0, 0) | 21 / GPA0 | Gripper 1 |
| `GS2` | (0, 1) | 22 / GPA1 | Gripper 2 |
| `GS3` | (0, 2) | 23 / GPA2 | Gripper 3 |
| `GS4` | (0, 3) | 24 / GPA3 | Gripper 4 |
| `GS5` | (0, 4) | 25 / GPA4 | Gripper 5 |
| `GS6` | (0, 5) | 26 / GPA5 | Gripper 6 |
| `GS7` | (0, 6) | 27 / GPA6 | Gripper 7 |
| `GS8` | (0, 7) | 28 / GPA7 | Gripper 8 |
| `GS9` | (1, 0) | 1 / GPB0 | Gripper 9 |
| `GS10` | (1, 1) | 2 / GPB1 | Gripper 10 |
| `GP` | (1, 2) | 3 / GPB2 | Gripper protect |
| `OS` | (1, 3) | 4 / GPB3 | Off-spot |
| `BS` | (1, 4) | 5 / GPB4 | Bin / #9 switch |
| `PBZ` | (1, 5) | 6 / GPB5 | First-ball / zero / manual-intervention pushbutton |
| `PBC` | (1, 6) | 7 / GPB6 | Cycle pushbutton |
| `Foul` | (1, 7) | 8 / GPB7 | Foul (Radaray beam) |

(The IN-B bank at 0x21 — 10th-frame, manual T/S/SWS/SWSR, AUX1–3 — is configured by the constructor but has no FSM reader yet; see Section 12 — *Channel Maps* — and Section 14 §IN-B for its connector landing on `J_SLOW_IN_B`/J5.)

#### 17.2.9 Interlock echo, watchdog, arm, and shutdown

- `interlock_ok()` — **secondary** software echo of the TB/SC interlock. The **authoritative** interlock is the hardware TB+SC loop on `J_SAFETY`. If an RP2040 link is wired, this returns the link's `interlock_ok()`; otherwise it returns `True`. Returning `True` by default is the safe choice here: the software echo can only *withhold* a command, never *enable* motion the hardware would block. (See §17.3 for how the link computes the echo, and §17.4 for why the firmware echo is currently disabled.)
- `watchdog_kick()` calls the injected `watchdog_kick` callable (the NE555 pet).
- `arm(on)` calls the injected `arm_relays` callable — the `ARM_PERMIT` rail condition.
- `all_off()` drives every output LOW (OUT-A, and OUT-B if present). Used on fault/shutdown.
- `close()` calls `all_off()`, de-asserts arm, then closes the I²C bus (each step guarded so shutdown can't throw).

---

### 17.3 `rp2040_link.py` — `RP2040Link`

`RP2040Link` is the Pi side of the UART link to the on-board RP2040 (the firmware in `firmware/rp2040/`, Section 15). The firmware owns the eight fast inputs (6 cams + 2 DIELL ball beams), debounces them, and pushes edge events to the Pi; it also drives the hardware `RP2040_OK` rail-permission line. This class parses those events, feeds cam/ball events to the FSM, echoes SC/TB, tracks RP2040 health, and sends commands back.

#### 17.3.1 Wire protocol

Newline-delimited JSON, **115200 baud, 8N1** (see `firmware/rp2040/README.md`, Section 15):

**RP2040 → Pi (events):**

| Line (example) | Meaning |
|---|---|
| `{"ev":"boot","fw":"…","wdt_reset":0,"rp_ok":0}` | RP2040 booted; `wdt_reset:1` means a watchdog reset just happened. |
| `{"ev":"cam","id":"SA","e":"f","t":…}` | Cam edge; `e`: `f`=asserted(fall), `r`=released(rise). |
| `{"ev":"ball","src":"L","t":…}` | One ball detected (DIELL beam), lockout-deduped; `src` = `L`/`R`. |
| `{"ev":"rp_ok","v":1,"t":…}` | Rail-permission changed. |
| `{"ev":"hb","ok":1,"flt":"","up":…,"drp":…}` | Heartbeat (~4 Hz); `ok` mirrors `rp_ok`, `drp` = dropped TX lines. |
| `{"ev":"flt","code":"motion_timeout","m":"S","t":…}` | Firmware latched a fault. |
| `{"ev":"ack","cmd":"CLEAR","t":…}` | Command acknowledged. |

**Pi → RP2040 (commands):** `RUN <m>` · `STOP <m>` / `STOP *` · `CLEAR` · `PING`.

#### 17.3.2 The cam → FSM dispatch map

Two module constants split cam IDs by role:

```python
CAM_DISPATCH   = ("SA", "SB", "TA1", "TA2")    # mapped to FSM cam methods
INTERLOCK_CAMS = ("SC", "TB")                   # interlock-only; NOT dispatched to the FSM
MOTORS         = ("S", "T", "SP", "BE", "M", "M1", "M2")
```

`SC` and `TB` have **no** `cam_SC`/`cam_TB` FSM method — they exist only to feed `interlock_ok()` (§17.3.4). The other four cams map to FSM calls via `dispatch_cam(controller, cam_id)`:

| Cam event `id` | FSM call(s) | Why two calls for SA/TA1 |
|---|---|---|
| `SB` | `controller.cam_SB_guard()` | Single handler. |
| `TA2` | `controller.cam_TA2_runthrough()` | Single handler; this is the pin-latch / strike-decision cam. |
| `SA` | `controller.cam_SA_runthrough()` **then** `controller.cam_SA_zero()` | SA is a **dual-trip** cam (270° run-through vs 360° zero). The FSM guards each handler by state, so calling both is safe — only the state-matching one acts. |
| `TA1` | `controller.cam_TA1_delayreset()` **then** `controller.cam_TA1_zero()` | TA1 is dual-trip (185° delay-reset vs 355° zero). Same state-guard rationale. |

The design note here is important for anyone extending the map: **the FSM, not the link, decides which angular variant of a dual-trip cam acts**, by guarding each handler on the current state. The link simply fires both candidate methods on a trip; the FSM ignores the one that doesn't match its state. This is why the firmware does not need to know each cam's per-angle polarity to forward events (that polarity is a deferred cutover item — Section 21, Section 15).

#### 17.3.3 Concurrency model — the thread-safe event queue

This is the single most important thing to understand before touching this module. **The serial reader runs on a background thread, but the FSM is touched from one thread only.** The split:

- The **reader thread** (`_read_loop` → `feed_line` → `_handle`) only ever (a) **updates state** (health, SC/TB danger) under `self._lock`, or (b) **queues** cam/ball events under `self._evlock` into a `collections.deque`. It never calls into the FSM.
- The **daemon's main loop** drains the queue via `apply_events(controller)`, which is the *only* place cam/ball events reach the FSM. Because `CycleController` is **not** thread-safe, this keeps all FSM access single-threaded.

```python
self._lock   = threading.Lock()    # guards _sc_danger, _tb_danger, _rp_ok, _last_hb, _fault
self._evlock = threading.Lock()    # guards the _events deque
self._events = deque()             # queued ("cam", id) / ("ball", src), drained by apply_events()
```

`apply_events(controller)` snapshots and clears the deque under `_evlock`, then replays each event: `("cam", id)` → `dispatch_cam`, `("ball", src)` → `controller.on_ball()`. It returns the count applied. **Call it from the main loop immediately before `controller.poll()`** so the FSM advances on fresh events.

> **Rule for maintainers:** never call an FSM method from the reader thread, and never read the FSM from it. If you need the reader to influence the FSM, queue an event or set a `_lock`-guarded flag and let the main loop act on it.

#### 17.3.4 Inbound parsing (`feed_line` / `_handle`)

- `feed_line(line)` strips, ignores blanks, `json.loads` it (logging and ignoring unparseable lines — a malformed line **never** throws), ignores non-dict payloads, then dispatches by `ev`.
- **`cam`:** if `id ∈ INTERLOCK_CAMS`, set `_sc_danger`/`_tb_danger = (e == trip_edge)` under `_lock`. Otherwise, if it's a **trip edge** and `id ∈ CAM_DISPATCH`, queue `("cam", id)`. (Non-trip edges of dispatch cams are dropped — they are not queued.)
- **`ball`:** queue `("ball", src)`.
- **`hb` / `boot` / `rp_ok` / `flt` / `ack`:** under `_lock`, refresh `_last_hb = now()` (any of these counts as a sign of life), then update health (see §17.3.6). After releasing the lock, fire the optional `on_health(ev)` callback (the daemon may set this for logging/alerts).

#### 17.3.5 Outbound commands (`run` / `stop` / `stop_all` / `clear` / `ping`)

`_send(line)` always appends to `self.sent` (so tests and the bench can assert on what was sent) and, if a serial object is present, writes `line + "\n"`. A write failure is caught and logged — **a comms hiccup never crashes the caller** (telemetry must not break control). The public commands: `run(motor)`→`RUN <m>`, `stop(motor)`→`STOP <m>`, `stop_all()`→`STOP *`, `clear()`→`CLEAR`, `ping()`→`PING`.

#### 17.3.6 Health tracking — `rp_ok`, `is_alive`, `health_ok`, `fault`

The firmware's `RP2040_OK` is a **hardware** rail line (Section 15); a dead or `!ok` RP2040 drops the rail regardless of this module. This module **additionally** surfaces health so the daemon can fault the FSM and drop arm.

| Query | True when |
|---|---|
| `rp_ok()` | The last health update reported rail-permit OK (`_rp_ok`). |
| `is_alive()` | A heartbeat has been seen **and** `now() − _last_hb ≤ hb_timeout` (default `hb_timeout = 1.0 s`). |
| `health_ok()` | **alive AND `_rp_ok` AND no latched `_fault`.** This is the gate the daemon uses. |
| `fault()` | The latched fault code string (`""` if none). |

Health-update rules inside `_handle` (all under `_lock`):

- An explicit **`flt`** event sets `_fault = ev["code"]` and `_rp_ok = False` **immediately** — even if the paired `rp_ok:0` line is delayed or dropped on a lossy UART. This was a deliberate P2 fix: a bare fault must mark the link unhealthy on its own.
- Otherwise, `_rp_ok` is updated from whichever of `v` / `ok` / `rp_ok` is present (checked in that order), and `_fault` is updated from `flt` if present. A heartbeat carrying `flt:""` (which the firmware sends after a `CLEAR`) is what clears the fault and restores `health_ok()`.

#### 17.3.7 The interlock echo (`interlock_ok`)

```python
def interlock_ok(self):
    with self._lock:
        return not (self._sc_danger and self._tb_danger)
```

This is the software echo of the hardware `J_SAFETY` loop. A genuine **collision course is SC AND TB both in their danger window at the same time** (per the SYSTEM_REFERENCE collision-interlock definition); either one alone is not a veto. So the echo returns `True` (no veto) unless **both** danger flags are set. It is advisory only — the hardware TB/SC NC loop is primary (Section 10, Section 14).

#### 17.3.8 Reader thread lifecycle (`start` / `_read_loop` / `close`)

- `start()` spawns the daemon-thread reader (`name="rp2040-rx"`), but only if a serial object exists.
- `_read_loop()` reads up to 256 bytes, accumulates into `self._rx`, and splits on `\n`, feeding each complete line to `feed_line` (decoding ASCII, replacing errors). A serial read error is logged and the loop sleeps 0.5 s and retries — it does not die.
- `close()` sets the stop flag and closes the serial port (guarded).

#### 17.3.9 Construction options

```python
RP2040Link(port=None, baud=115200, *, serial_obj=None,
           hb_timeout=1.0, trip_edge="f", now=None)
```

Three ways to instantiate: a real `port` (opens `serial.Serial(port, baud, timeout=0.1)` — pyserial imported lazily), an injected `serial_obj` (anything with `read()`/`write()`/`close()`), or neither (feed lines by hand via `feed_line()` — used by the host tests and the daemon's `sim` mode). `trip_edge` selects which edge (`f`/`r`) is the cam's angular trip; **the trip edge is configurable** precisely because cams are normally-closed and the opto inverts, so which physical edge is the "trip" is a bench-confirm item (default `"f"`).

---

### 17.4 `controller_daemon.py` — the per-board control loop

> **SKELETON / BENCH-GATED.** This file is explicitly a skeleton. **Do not run it against a live machine** until the full hardware safety chain is validated per `docs/phase8b_pcb_revB_spec.md` §12.9 and the Track-B controller cutover runbook (Section 21). Every field marked `# CONFIRM` in the source (pin numbers, I²C bus IDs, UART ports, slow-input polarity/debounce) is set at bench/cutover, not now. The scoring/server reporting path (Track A camera + `lane_node.py` websocket) is **not yet wired in** — see the `TODO(server)` note; the controller loop is deliberately a tight synchronous loop, while scoring/IO-to-server is async and lives elsewhere.

#### 17.4.1 `BoardConfig` and `DEFAULT_BOARDS`

```python
@dataclass
class BoardConfig:
    lane: int        # lane this board controls
    i2c_bus: int     # per-board I2C bus
    uart_port: str   # serial device to THIS board's RP2040
    arm_pin: int     # Pi GPIO -> relay-enable ARM for this board
    wdog_pin: int    # Pi GPIO -> this board's NE555 kick
```

```python
DEFAULT_BOARDS = [
    BoardConfig(lane=21, i2c_bus=1, uart_port="/dev/ttyAMA0", arm_pin=26, wdog_pin=12),
    BoardConfig(lane=22, i2c_bus=3, uart_port="/dev/ttyAMA1", arm_pin=13, wdog_pin=6),
]
```

> **(VERIFY: most fields in `DEFAULT_BOARDS` are bench-confirm placeholders.)** Per-field confidence (updated source + **`docs/phase8_pi_provisioning.md`**, which gives the `config.txt` boot overlays that make the 2nd I²C bus + 2nd UART *exist* and a deconflicted Pi-GPIO pin table): **FIRM** — board-21 `i2c_bus=1` (Pi hardware I²C, GPIO2/3) and `wdog_pin=12` (the existing, bench-validated watchdog-kick pin). **CONFIRM at bench** — the 2nd I²C bus number + its `i2c-gpio` SDA/SCL pins, both RP2040 UART device names (`/dev/ttyAMA0`, `/dev/ttyAMA1`), and the arm GPIOs (26/13). Those second-bus/second-UART devices only exist once the provisioning-doc overlays are applied. The board's `J_PI`/J1 carries dedicated `WDOG_KICK` and `ARM_PERMIT` lines (Section 11), but **which Pi GPIO drives each is not fixed in the design sources** — confirm at bench before trusting these numbers.

The daemon disarms in three FSM states:

```python
DISARMED_STATES = (State.POWER_OFF, State.MANUAL_INTERVENTION, State.FAULT)
```

In any of these, the arm GPIO must stay de-asserted (the power-down rule — Section 10 / SYSTEM_REFERENCE §5).

#### 17.4.2 Slow-input → FSM action map

The daemon edge-detects a subset of slow MCP inputs and turns a **rising (asserted) edge** into an FSM method call (cams + ball arrive via the RP2040 link; grippers/GP are polled inside the FSM):

| Slow input | Action on rising edge | Notes |
|---|---|---|
| `PBZ` | `fsm.first_ball_zero()` **and** `link.clear()` | Operator re-arm. Also sends `CLEAR` so the firmware's fault latch clears in lock-step. |
| `BS` | `fsm.bin_full()` | 10th pin to the bin → spot a fresh rack. |
| `Foul` | `fsm.on_foul()` | Radaray foul beam. |

`PBC`, `OS`, `TENTH`, and the `MAN_*` inputs are routed on the board but have **no FSM handler yet** (future work).

#### 17.4.3 `BoardController` assembly

`BoardController(cfg, *, sim=False)` wires the three pieces together for one lane:

- **`sim=True`** (off-Pi / self-test): `RP2040Link()` with no serial (feed via `feed_line()`) + `RecordingIO(rp2040=link)`. No GPIO.
- **`sim=False`** (on the Pi): lazily imports `gpiozero.LED`; creates `LED(arm_pin)` (the arm GPIO, de-asserted by default) and `LED(wdog_pin)` (the NE555 kick); opens `RP2040Link(port=uart_port)`; builds `MachineIO(lane, i2c_bus, rp2040=link, watchdog_kick=self._kick_wdog, arm_relays=self._set_arm)`; and calls `link.start()` to launch the background reader.

In both modes it then builds `CycleController(lane, io)` and calls **`fsm.power_restore()`** so the controller **comes up disarmed** (power-down rule) — it boots into `MANUAL_INTERVENTION` and requires a deliberate First-Ball-Zero before it will arm. It also snapshots the slow-input actions and initializes `_prev_slow` (all `False`) and `_was_healthy = True`.

GPIO callbacks:

- `_kick_wdog()` → `self._wdog.toggle()` — an **edge each poll** keeps the NE555 alive. *(The exact required kick waveform is marked `# CONFIRM`; see §17.4.6. (VERIFY: whether a level-toggle per poll satisfies the NE555 retrigger timing, or whether a defined pulse is required — bench item.))*
- `_set_arm(on)` → `self._arm_led.value = 1 if on else 0` — drives `ARM_PERMIT`.

#### 17.4.4 The tick loop (`tick()`)

The healthy-path tick, in order:

```python
def tick(self):
    healthy = self.link.health_ok()
    if not healthy:
        ... SAFETY TRIP (see §17.4.5) ...
        return
    if not self._was_healthy:
        self.io.log("... RP2040 link recovered -> awaiting First-Ball-Zero")
    self._was_healthy = True

    self.link.apply_events(self.fsm)   # 1) cam/ball edges -> FSM (single-threaded here)
    self._slow_edges()                 # 2) PBZ/BS/Foul rising edges -> FSM
    self.fsm.poll()                    # 3) advance FSM + KICK the NE555 (poll() kicks via io)
    self.io.arm(self.fsm.state not in DISARMED_STATES)   # 4) arm policy
```

The four ordered steps each tick:

1. **`apply_events`** drains the RP2040 cam/ball queue into the FSM (the only single-threaded FSM-touch point).
2. **`_slow_edges`** reads each mapped slow input via `io.read_input(name)`, and on a `False → True` transition fires its action, updating `_prev_slow`. *(Debounce on these edges is `# CONFIRM` — see §17.4.6.)*
3. **`fsm.poll()`** advances the FSM **and pets the NE555** (the kick is inside `poll()` via `io.watchdog_kick()`). This is the watchdog-coupling described in §17.1.
4. **Arm policy:** assert arm iff the FSM state is **not** in `DISARMED_STATES`. Note the rail still needs all the other hardware conditions; this only manages the `ARM_PERMIT` term.

#### 17.4.5 The health-loss SAFETY TRIP

This is the critical safety branch and exists because of a real Codex-found defect: a mid-cycle heartbeat blip dropped arm while sweep was still latched, then the controller **silently re-armed with the stale latch**, causing uncommanded motion. The fix makes a health loss a **full software safety trip**:

When `link.health_ok()` is false (dead/stale heartbeat, `rp_ok:0`, or a latched firmware fault), `tick()`:

1. If this is the **transition** into unhealthy (`_was_healthy` was true), logs the loss (with `fault()`, `is_alive()`, `rp_ok()`) and calls **`self.fsm.power_restore()`**, which runs the FSM's all-motors-off (clearing the relay latches) and latches the FSM into **`MANUAL_INTERVENTION`**.
2. Sets `_was_healthy = False`.
3. **Drops arm** (`io.arm(False)`).
4. Still **drains the event queue** (`apply_events`) — the FSM ignores events when not `READY`, but this keeps the queue from growing unbounded.
5. Still **calls `fsm.poll()`** — *the Pi itself is alive, so it keeps kicking the NE555.* (If the Pi instead stalls, the kicks stop and the NE555 drops the rail — that is the separate Pi-watchdog path.)
6. **Returns** — none of the healthy-path steps run.

Recovery is **not automatic**: when the heartbeat returns OK, the FSM stays in `MANUAL_INTERVENTION` and arm stays low. Only a deliberate **PBZ (First-Ball-Zero)** — which both calls `fsm.first_ball_zero()` and sends the firmware a `CLEAR` — brings it back to `READY` and re-arms. The self-test (`--selftest`) explicitly verifies this whole sequence: mid-cycle `rp_ok:0` forces sweep OFF, latches `MANUAL_INTERVENTION`, drops arm; an OK heartbeat does **not** re-arm; and only PBZ recovers to `READY` + armed.

> **Why force motors off in software when the hardware rail already dropped?** Dropping the rail de-energizes the coils, but the *FSM's* output latches (and the MCP OLAT bits) would still say "sweep on." Without the software trip, the next re-arm would re-assert that stale latch the instant the rail came back. Forcing `all_motors_off()` clears those latches so recovery starts from a known-safe state. This is belt-and-suspenders on top of the hardware rail, not a replacement for it.

#### 17.4.6 `# CONFIRM` items in this file

The source flags these as bench/cutover-time decisions. They are **not** guesses to be trusted as-is:

| Item | Location | Status |
|---|---|---|
| Per-board I²C bus IDs | `BoardConfig.i2c_bus` / `DEFAULT_BOARDS` | (VERIFY: board-A=hw i2c-1, board-B=software "i2c-gpio" bus; the literal `3` is a placeholder.) |
| UART device per board | `uart_port` | (VERIFY: `/dev/ttyAMA0` / `/dev/ttyAMA1` are placeholders.) |
| Arm GPIO per board | `arm_pin` | (VERIFY: 26 / 13 are placeholders — confirm against Pi↔J1 wiring.) |
| Watchdog-kick GPIO per board | `wdog_pin` | (VERIFY: 12 / 6 are placeholders.) |
| Watchdog kick **waveform** | `_kick_wdog` | (VERIFY: toggle-per-poll vs a defined NE555 retrigger pulse — bench.) |
| Slow-input **debounce** | `_slow_edges` | (VERIFY: PBZ/BS/Foul rising-edge debounce strategy — bench.) |
| Slow-input **polarity** | the slow-input path generally | (VERIFY: per-channel active-high/low at cutover.) |

#### 17.4.7 `run()` — the scheduler and SIGTERM safe-off

```python
def run(boards, hz=50.0):
    period = 1.0 / hz
    ... install SIGTERM + SIGINT handlers that set stop["flag"] ...
    while not stop["flag"]:
        t0 = time.monotonic()
        for b in boards: b.tick()
        dt = time.monotonic() - t0
        if dt < period: time.sleep(period - dt)
    finally:
        for b in boards: b.safe_off()
```

- **Rate:** default **50 Hz** (`period = 1/hz`). Each pass ticks every board, then sleeps the remainder of the period (no sleep if the tick overran).
- **Signals:** `SIGTERM` and `SIGINT` both set the stop flag, so the loop exits cleanly at the next iteration boundary. This is the systemd-friendly shutdown path (matches the Pi-side `lane-node`/controller service model — see Section 15).
- **Safe-off on exit (the `finally`):** two things stop motion on shutdown. First, the loop exiting means **the kicks stop → the NE555 drops the rail** in hardware. Second, `safe_off()` is called on every board explicitly.

`BoardController.safe_off()` runs four steps, each guarded so one failure doesn't abort the rest:

1. `io.arm(False)` — drop arm.
2. `io.all_off()` (if present) — drive all outputs LOW / clear relay latches.
3. `link.stop_all()` — send `STOP *` to the firmware.
4. `link.close()` — close the serial port / stop the reader.

#### 17.4.8 `main()` and the off-hardware self-test

`main()` parses `--selftest` and `--hz`, sets up logging, and either runs `_selftest()` or constructs the **real-hardware** boards from `DEFAULT_BOARDS` and calls `run()`. `python controller_daemon.py --selftest` assembles everything in `sim` mode and drives a **full strike cycle entirely through `tick()`** (RP2040 events fed via `feed_line`, slow inputs via `io.slow[...]`), then exercises the mid-cycle health-loss safety trip and PBZ recovery described in §17.4.5. Exit code is `0` only if every check passes. This is the gate that proves the IO layer, the link, and the FSM assemble and interlock correctly off-Pi before any hardware exists.

---

### 17.5 How the three layers fit together (one tick, end to end)

For a healthy lane, one ~20 ms tick on the Pi does this:

1. The RP2040 has, asynchronously, debounced its cams/DIELL and pushed JSON events; `RP2040Link`'s reader thread parsed them and **queued** cam/ball events (and updated SC/TB + health under lock).
2. `BoardController.tick()` checks `link.health_ok()`. Assuming healthy:
3. `link.apply_events(fsm)` replays the queued cam/ball events into the FSM (`dispatch_cam` / `on_ball`).
4. `_slow_edges()` reads PBZ/BS/Foul off **MCP IN-A (0x20)** via `MachineIO.read_input` and fires `first_ball_zero+CLEAR` / `bin_full` / `on_foul` on a rising edge.
5. `fsm.poll()` advances the state machine; inside it, any relay change calls `MachineIO.set_*` → an **OUT-A (0x22)** bit write **and** a `RUN`/`STOP <motor>` to the firmware; `poll()` also calls `io.watchdog_kick()` → the daemon toggles the **NE555 kick GPIO**.
6. `io.arm(state not in DISARMED_STATES)` sets the **ARM_PERMIT** GPIO.
7. Meanwhile the FSM reads pin state via `MachineIO.read_grippers()` (a single dual-port read of **IN-A**) and consults `interlock_ok()` (the link's SC∧TB echo, advisory).

At no point can this software energize a relay unless the hardware rail's other five conditions (watchdog, RP2040_OK, cam-stop, TB/SC, Stop/CIS) are simultaneously satisfied (Section 10). The software's job is to drive the *right* outputs at the *right* time and to *fail closed* — drop arm and latch `MANUAL_INTERVENTION` — the moment it loses confidence in the RP2040.

---

### 17.6 Cross-references

- **Section 3 — The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing** — what the cams/relays/states *mean* mechanically; the FSM this IO layer drives.
- **Section 5 — Rev-B Controller Board: Overview, Domains & Isolation** — one board per lane; logic/field/output domains.
- **Section 6 — Rev-B Power Architecture** — the 3.3 V rail the MCP23017s and opto logic sides run on.
- **Section 7 — Rev-B Logic: RP2040 + MCP23017 + I²C** — the chips, addresses, and bus this software talks to.
- **Section 8 — Rev-B Field Inputs: PC817 Opto-isolators** — the active-low front-ends behind `INPUT_ACTIVE_LOW`.
- **Section 9 — Rev-B Machine Outputs: G5LE Relays** — the relays `OUT_A_MAP` drives (and the M1 DNP decision).
- **Section 10 — Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail** — the authoritative six-condition rail this software only *contributes* to.
- **Section 11 — Rev-B Connector Pinouts (J1–J14)** — `J_PI`/J1 (watchdog kick, arm), `J_SAFETY`/J14 (TB/SC loop), `J_FAST_IN`/J3, `J_SLOW_IN_A`/J4.
- **Section 12 — Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps** — the canonical channel/bit tables (`OUT_A_MAP`/`IN_A_MAP`/fast-input GPIO) this section mirrors.
- **Section 14 — Machine Interface: C1/C2A Connectors & the Adapter Harness** — where each signal lands on the machine, and the exact LCSC part numbers.
- **Section 21 — Cutover Procedure (Track B)** — where the `# CONFIRM` bench items get nailed down.
- **Section 15 — RP2040 Firmware & Cam Timing** — the other side of the UART: the fast-input pin map (GP6–GP13, RP2040_OK=GP2, UART=GP0/GP1), the fail-safe `RP2040_OK` line, the motion max-run backstop, and the deferred v1.1 cam-stop overrun.


## 18. Camera Pin Scoring (Track A)

This section documents the **optical pin-scoring** half of the Phase 8 system — "Track A." It is independent of the lane-controller board (Track B). Track A is **read-only with respect to the machine**: it watches the existing QubicaAMF pinsetter camera and computes the score; it never drives the pinsetter. A scoring failure can produce a wrong score, never an unsafe machine action. On any failure the system **falls back to manual desk scoring** automatically.

Read this section to install, operate, calibrate, or extend camera scoring. It is self-contained: an engineer with no prior context can stand the pilot up on lanes 21/22 from here.

> **Scope note.** Track A runs today on the **scoring node software** (`lane_node/`) talking to a small **scoring server** (`server/lane_node_server.py`). It uses the *existing* pinsetter controller to cycle the machine — our cycle relay is wired but is **not** the live machine driver during the scoring pilot. The Track-B controller board (Sections 5–14) is a separate, parallel effort. Where the two interact (the settle-delay vs. the cycle command), it is flagged explicitly below.

---

### 18.1 What Track A does, end to end

```
  QubicaAMF T-Camera (1 per pair, sees BOTH decks)
        │  composite video (PAL, 720×576), Brown=video / Blue=gnd
        ▼
  VIXLW USB capture dongle  →  /dev/video0 on the Pi
        │  one analog frame on demand
        ▼
  lane_node/camera.py  (PairCamera: owns capture handle + empty reference)
        │  float32 grayscale frame
        ▼
  lane_node/pin_detect.py  (DualDeckDetector, "M4" method)
        │  TWO 10-bit standing-pin masks  {'L': maskL, 'R': maskR}
        ▼
  lane_node/lane_node.py  (DIELL ball-detect → settle → capture → BALL_EVENT)
        │  WebSocket ws://<server>:8765   BALL_EVENT{lane, pin_mask}
        ▼
  server/lane_node_server.py  (wsl_scoring_engine.record_ball → running score)
        │  HTTP :8766
        ▼
  scoring display  (wsl_scoring_display.html, polls /api/lane/<N>/scoring)
```

One **T-Camera per lane pair** sits at the pinsetter behind the pins, looking back toward the bowler, and frames **both decks of the pair in a single 720×576 PAL field**. The left half of the image is one deck, the right half the other. The capture dongle hands the Pi one frame per ball; the detector turns each half-image into a 10-bit "which pins are still standing" mask; the daemon ships that mask to the server, which feeds the existing Python bowling scorer and serves the result to the overhead display.

Physical lane mapping is fixed by calibration (Section 18.3): **left image deck = lane 21, right image deck = lane 22**.

---

### 18.2 Hardware: T-Camera, the composite tap, and the VIXLW dongle

| Item | Value / part | Notes |
|---|---|---|
| Camera | QubicaAMF **T-Camera**, one per **lane pair** | Existing house equipment, reused. Mounted at the pinsetter, behind the pins, looking toward the bowler. Sees **both decks** of the pair in one frame. |
| Video format | Composite **PAL**, **720×576** | This is the native capture resolution and the resolution everything is calibrated to (`CALIB_FRAME_SIZE = (720, 576)`). Do not upscale — composite bandwidth + soft focus mean higher resolution adds no real detail. |
| Capture device | **VIXLW** USB composite-capture dongle | Enumerates as a UVC device → `/dev/video0` (the default). Owned and proven. |
| Video tap | **Brown = video, Blue = ground** | The proven composite tap off the T-Camera feed. RCA shell → Blue (the cable's pin-8 ground). |
| Pi capture index | `WSL_LANE_CAMERA_DEVICE`, default `0` (`/dev/video0`) | If the dongle enumerates as `/dev/video1`, set this to `1`. |

> ⚠️ **The #1 field failure is a missing video ground, not a software bug.** A black frame / "mask always 0 or always 1023" almost always means the RCA shell → Blue (cable pin-8) ground is not seated. Reseat the tap ground before touching any code. (Same trap as the original camera tap.)

The camera being **behind** the pins means the image is **mirrored** relative to the bowler's view — see `MIRROR` in Section 18.3.

---

### 18.3 The detection method ("M4") and why naive subtraction failed

The detector lives in `lane_node/pin_detect.py`. Understanding *why* it works the way it does is essential before changing any constant.

#### 18.3.1 Why the obvious method fails

The obvious approach — capture a frame, subtract a stored "empty deck" frame, and call any bright spot a standing pin — **does not work on this analog feed.** The VIXLW/composite path has **exposure drift**: the auto-exposure shifts frame to frame, so the whole image gets brighter or darker between captures. Measured on the real deck (2026-05-31), the pin-free lane area read median 87→91 on live frames vs. 51 on the stored empty — a uniform ~35-count lift. With naive `frame − empty`, that lift makes **every** region of interest (ROI) look bright, so **absent pins read as standing**. Benchmark of the naive single-deck method: **15/120 spot errors, separation gap −27** (i.e., no threshold can separate standing from down). The legacy naive method is retained in `pin_detect.py` as `detect_pins()` / `PinDetector` **for the synthetic unit tests only** — it must not be used on real analog frames.

#### 18.3.2 What "M4" does

"M4" was the winner of an 8-method bake-off (**0/120 errors, separation gap +35**). Three ideas:

1. **Drift correction.** Estimate the global exposure drift from a band of lane that pins never occupy (`DRIFT_BAND` rows), then subtract that drift from every measurement. `drift = median(frame[band]) − median(empty[band])`.
2. **Tight cap-ROI.** Sample a *small* ROI on the pin **cap** (not the whole pin body). A tight cap window avoids the second failure mode: brightness bleed from an adjacent *standing* pin spilling into a neighbor's ROI (worst observed case was the right-deck pin-2 spot catching pin-4 spill).
3. **Fixed spots.** The rack lands in the same image positions every time, so the 20 pin-spot pixel centers are **calibrated once** and then sampled forever. Calibration does not run live.

The per-spot score (`spot_value`) is:

```
value = mean(frame_cap − drift) − mean(empty_cap)
standing if value > DET_THR
```

`detect_deck()` runs this for all 10 spots of one deck and builds a 10-bit mask. `DualDeckDetector.detect()` does it for both decks from one frame and returns `{'L': maskL, 'R': maskR}`.

#### 18.3.3 The calibrated constants (do not edit without re-calibrating)

All constants below are baked into `lane_node/pin_detect.py` at the top of the file. They were fit on 2026-05-31 and validated **0 detection errors** across all 6 labeled frames (4 leaves + full rack + empty) for any `DET_THR` in the band **[19, 53]**.

| Constant | Value | Meaning |
|---|---|---|
| `CALIB_FRAME_SIZE` | `(720, 576)` (W, H) | The frame size the spots were measured in. Other sizes are auto-scaled by `_scale_for()`, but production must stay 720×576. |
| `DET_THR` | `38.0` | Standing threshold on the M4 score. Validated-safe band **[19, 53]**. This is the primary soak-tuning knob for lighting. |
| `DRIFT_BAND` | `(440, 560)` | Row range (at calib resolution) of the **pin-free** lane area used as the exposure-drift probe. |
| `CAP_DY` | `−4` | The cap sits a few pixels **above** the measured spot center; the ROI is offset up by this. |
| `CAP_HALF` | `(5, 12)` | (half-width, half-height) in px of the tight cap ROI. |
| `MIRROR` | `True` | See 18.3.4. |
| `DECK_TO_LANE` | `{'L': 21, 'R': 22}` | Which physical lane each image deck is. **Confirmed** 2026-05-31. |

**`PIN_SPOTS_PX`** — the 20 calibrated pixel centers (10 per deck), at 720×576. These were fit by a rack→image homography from 4 labeled leave-frames (sub-3px residual: L max 2.7px, R max 1.9px). Pins **2 and 3** were not directly measured — they are squeezed/dim in the image and were **homography-predicted**; they validated 0-error but are the spots to watch first in soak (Section 18.8). The right deck is more oblique (pins closer together) → tighter margins there.

| Pin | Left deck (`'L'`) px (x, y) | Right deck (`'R'`) px (x, y) |
|---|---|---|
| 1 | (94.3, 230.8) | (615.0, 200.4) |
| 2 | (154.9, 233.0) *(predicted)* | (631.6, 202.4) *(predicted)* |
| 3 | (74.5, 239.6) *(predicted)* | (554.1, 207.6) *(predicted)* |
| 4 | (205.0, 234.8) | (645.7, 204.0) |
| 5 | (131.0, 240.8) | (574.4, 208.9) |
| 6 | (58.4, 246.7) | (500.5, 214.0) |
| 7 | (247.3, 236.3) | (657.8, 205.4) |
| 8 | (178.7, 241.8) | (591.8, 210.0) |
| 9 | (111.3, 247.3) | (523.6, 214.7) |
| 10 | (45.1, 252.6) | (453.2, 219.6) |

*(Pins 2 & 3 are homography-predicted, not directly measured — watch them first if a single spot misreads.)*

#### 18.3.4 The mirror (`MIRROR = True`) — why, and how to confirm

Because the camera is **behind** the pins looking toward the bowler, the image is left-right flipped vs. the bowler's view: the back-row pin on the *left of the image* is **pin 10** (bowler's right), not pin 7. `MIRROR = True` corrects the **reported pin numbers** by swapping the mirrored pairs after detection:

| Image position reads as | Reported as (under `MIRROR=True`) |
|---|---|
| 7 | 10 |
| 4 | 6 |
| 2 | 3 |
| 8 | 9 |

(and vice-versa; pins 1 and 5 are mirror-invariant). `MIRROR` **only** affects pin *numbers* on asymmetric leaves — it never changes detection accuracy, pins-down counts, strikes, or spares.

**Confirmed correct 2026-05-31.** A deliberate single pin 7 set on both decks read as **7 under `MIRROR=True`** (and as 10 under `MIRROR=False`), proving `True` is right. This frame was required because all four calibration leaves are mirror-symmetric *as sets* (e.g. {7,8,9,10} ↔ {10,9,8,7}), so a single corner pin is the first test that fixes the L↔R convention. If you ever re-mount the camera and a known **7-pin or 10-pin** reports as the opposite corner, flip `MIRROR` — no other change needed.

---

### 18.4 The bit mapping (shared contract)

Both `pin_detect.py` and `wsl_scoring_engine.py` use the **same** 10-bit encoding. This is the QubicaAMF-standard "pins **remaining**" convention.

- **Bit `n−1` set = pin `n` is STANDING.** Pin 1 = LSB (`0x001`), pin 10 = bit 9 (`0x200`).
- **`0x000` (0)** = all down = **strike** (on ball 1).
- **`0x3FF` (1023)** = full rack standing = **gutter** (nothing knocked down).
- After ball 2, only pins that survived ball 1 can still be standing.

| Bit | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Pin (standing if bit=1)** | 10 | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
| **Hex weight** | 0x200 | 0x100 | 0x080 | 0x040 | 0x020 | 0x010 | 0x008 | 0x004 | 0x002 | 0x001 |

Standard 10-pin layout with bit positions:

```
   7  8  9 10        bits  6 7 8 9
    4  5  6                3 4 5
     2  3                   1 2
      1                      0
```

Worked examples:

| On the deck | Mask (bin) | Mask (hex / dec) |
|---|---|---|
| Strike (all down) | `0000000000` | 0x000 / 0 |
| Gutter (full rack) | `1111111111` | 0x3FF / 1023 |
| 7-pin leave (only pin 7 standing) | `0001000000` | 0x040 / 64 |
| 10-pin leave (only pin 10 standing) | `1000000000` | 0x200 / 512 |
| 7-10 split | `1001000000` | 0x240 / 576 |

> The scoring engine derives splits, displays (`X`, `/`, `-`, `F`), bonuses, and totals from this mask — see the scoring engine (`wsl_scoring_engine.py`, in the main app — outside this manual's scope) for the scoring logic itself. Track A's only job is to produce the correct mask.

---

### 18.5 The scoring node: modes, settle window, and safe fallback

The Pi daemon is `lane_node/lane_node.py`. It controls one **pair** (lanes 21 + 22). *(This same `lane_node.py` daemon also carries the Phase-8a pilot's cycle/power relay outputs — see the file table at the end of this section — so the "read-only" framing above describes the **scoring path**, not the whole process. A scoring-only Pi never wires those outputs.)* Ball detection comes from the **DIELL** photoelectric beams at the pin deck (read-only inputs); see Section 4 (Machine I/O Inventory) and Section 8 (PC817 Opto-isolators) for the DIELL electrical interface and Section 12 (Channel Maps) for the GPIO assignment that feeds it.

#### 18.5.1 Scoring modes (`WSL_LANE_SCORING_MODE`)

Set on the `lane-node` systemd service. Default is the **safe** `manual`.

| Mode | What DIELL does | When to use |
|---|---|---|
| `camera` | Waits the settle window, captures a frame, runs detection, emits `BALL_EVENT` with a **real** `pin_mask` → **auto-scoring**. | Only once the empty reference is captured and detection is dry-run-validated on the live feed. |
| `manual` *(default)* | Emits `BALL_EVENT` with `pin_mask=None, awaiting_manual=True`. The server records that a ball happened and cycles the lane, **but applies no pin count** — the desk enters pins via `POST /api/lane/<N>/score`. | The safe Phase-8a default; any time camera scoring is not yet trusted. Abort target (Section 18.7). |
| `disabled` | DIELL events are logged on the Pi but **no** message is sent to the server. | Bench testing without scoring side effects. |

An unknown value falls back to `manual` with a warning.

#### 18.5.2 The settle window (`WSL_LANE_CAMERA_SETTLE_S`)

When DIELL fires, the ball has just *reached* the deck and the pins are **still rocking** — capturing now would misread. So in `camera` mode the daemon schedules `_settle_capture_emit()`: it `sleep`s `camera.SETTLE_S` seconds, **then** captures and detects, at the moment the pins have stopped but the (existing) pinsetter has **not yet swept**. The blocking capture runs off the event loop via `asyncio.to_thread`, so the watchdog kick stays responsive.

| Knob | Default | Source of truth | Tune by |
|---|---|---|---|
| `SETTLE_S` (`WSL_LANE_CAMERA_SETTLE_S`) | `2.5` s | `camera.SETTLE_S` in `lane_node/camera.py` (the daemon reads it) | Watching real balls: time from "ball hits pins" to "pins stopped, sweep not yet down." |

> **(VERIFY: the 2.5 s settle window is a manual-derived default, not yet field-measured on 21/22.)** The code comment notes the manual hint "pin data settles ~2.5 s after the sweep reaches 66°" and explicitly flags this to be measured on the real machine. Start at 2.5 s and adjust during soak (Step 4/Step 8 of the runbook).

> ⚠️ **Timing coupling (Track-B caveat).** The server sends the pinsetter `CYCLE` *in reply to* `BALL_EVENT`, so delaying `BALL_EVENT` by `SETTLE_S` also delays that `CYCLE` reply by `SETTLE_S`. **Harmless in the scoring pilot** — the existing controller cycles the machine on its own ball-detect; our cycle relay is not the live driver. **When the Track-B controller drives the machine, this must be decoupled** ("cycle now" must not wait on "here's the score"). Flagged in the `_settle_capture_emit` docstring; see Section 3 (Machine Sequence) and Section 14 (Machine Interface).

#### 18.5.3 Safe fallback — a real ball NEVER auto-scores bogus pins

This is the central safety property of Track A. The capture/detect chain returns `None` whenever it cannot produce trustworthy pins, and `None` is treated as "no data → desk scores it":

| Failure | Where it returns `None` | Result |
|---|---|---|
| No empty reference loaded | `PairCamera.ready == False` (`camera.py`) | `detect_lane()` → `None` |
| Capture fails (no frame / dongle gone) | `grab_frame()` → `None` (`camera.py`) | `detect_lane()` → `None` |
| Detector raises / lane not on this camera | caught in `PairCamera.detect_lane()` | `None` |
| Camera init failed at startup | `_PAIR_CAMERA` stays `None` (`lane_node._init_camera`) | `detect_current_pins()` → `None` |

When `detect_current_pins()` returns `None`, `_settle_capture_emit()` emits `BALL_EVENT` with `pin_mask=None, awaiting_manual=True`. The server then **cycles the lane but does not record a score**, and logs "awaiting `/score` POST from desk." The lane keeps running; only the auto-score is skipped. There is **no** code path where a real ball records a synthetic/bogus mask in production.

> **Bench-only exception:** `WSL_LANE_CAMERA_STUB=1` makes `camera` mode rotate synthetic masks (`_STUB_PIN_MASKS`) when no real camera is present, to reproduce old bench behavior. It is **off by default** and must **never** be set on a live lane — it would record fake pins on real balls.

---

### 18.6 The empty reference — the one must-do install step

The detector compares every ball's frame to a **real cleared-deck reference frame from this specific camera and mount.** The calibration "empty" was a *different* capture (a downloaded screenshot used to fit the spots); **production needs its own.** This is the single mandatory per-install step.

- Stored at `lane_node/empty_ref.png` (720×576), overridable via `WSL_LANE_EMPTY_REF`.
- It is **gitignored** — *each Pi captures its own*. It does not ship in the repo.
- Captured by `capture_empty_reference()` (CLI `--capture-empty`), which discards 5 warm-up frames so auto-exposure settles, then saves one frame.

**Procedure** (both decks must be **cleared** — cycle 21 and 22 so all pins are swept, deck empty):

```bash
cd /home/pi/wsl-lane-nodes
.venv/bin/python3 lane_node/camera.py --capture-empty
#   add  --device 1   if your dongle is /dev/video1
```

Verify it is a genuine empty deck: `ls -l lane_node/empty_ref.png` (non-zero), and ideally `scp` it to a laptop and eyeball it — both decks visible, no pins, normal house lighting. If it errors "no frame captured," the problem is upstream (device index or, most likely, the **video ground**) — see 18.2.

At daemon startup you want the log line `Camera ready for lanes [21, 22] (settle=2.5s).` If you instead see `Camera mode but detector NOT ready`, the empty ref did not load — **the lane still runs and falls back to manual scoring** (not dangerous; just not auto-scoring yet). Re-capture the empty reference.

---

### 18.7 Go-live procedure and instant abort (lanes 21/22)

Full runbook: `docs/phase8_trackA_golive_runbook.md`. Condensed:

| Step | Action |
|---|---|
| Pre-flight | On the Pi: `git pull`; confirm `lane_node/camera.py` + `pin_detect.py` exist; `.venv/bin/python3 -c "import numpy, PIL, av"`. On the server: confirm `lane_node_server.py` is up (8765/8766) via `curl http://<server>:8766/api/health`. |
| 1 — capture feed | `ls -l /dev/video*` (expect `/dev/video0`); `v4l2-ctl --list-devices`. Black frame later ⇒ video ground (18.2), not code. |
| 2 — **empty reference** | Clear both decks → `camera.py --capture-empty` (Section 18.6). The one must-do step. |
| 3 — **dry-run detector** | Set a known rack, then `camera.py --test` → prints `masks: {21: …, 22: …}`. Full rack → both `1023`; empty → `0`; 7-pin leave → `64`. **This is the real go/no-go.** Everything downstream is plumbing that already passed its tests. |
| 4 — settle window | Watch a few balls; if clearly ≠ 2.5 s, note it for Step 5. |
| 5 — start camera mode | `sudo systemctl edit lane-node` → add `Environment=WSL_LANE_SCORING_MODE=camera` (+ `WSL_LANE_CAMERA_SETTLE_S`, `WSL_LANE_CAMERA_DEVICE`, `WSL_LANE_SERVER_URL` as needed) → `sudo systemctl restart lane-node` → `journalctl -u lane-node -f`. Want: `Camera ready for lanes [21, 22]`. |
| 6 — watch a real ball | Open `http://<server>:8766/display?lane=21`. Throw; log shows `ball detected … mode=camera; settling …` → `camera pin_mask=0x…` → display updates. Compare detected vs. actual for ~10 balls + a few leave types. |
| 7 — **abort to manual** | `sudo systemctl edit lane-node` → `WSL_LANE_SCORING_MODE=camera` → `manual` → restart. (Or Ctrl-C the foreground daemon and relaunch without the env var.) **No machine impact** — manual mode just emits the ball without a mask and the desk scores via the existing flow. |
| 8 — soak + tune | Section 18.8. |

> **Service-enable reminder:** the `lane-node` service must be `systemctl enable`d, or the lane goes dark after a reboot. See the provisioning runbook / Section 2 (Architecture).

---

### 18.8 Calibration & soak-tuning knobs

The hard CV problem is solved (calibration done, 0-error on labeled frames). Soak is about confirming it on the live feed across lighting and play, and nudging three knobs.

| Symptom in soak | Likely cause | Knob / fix |
|---|---|---|
| **Consistent miss on one pin/spot** | That spot's `PIN_SPOTS_PX` coordinate (watch pins **2 & 3** first — homography-predicted; and the **right deck** — more oblique) | Adjust the spot's `(x, y)` in `pin_detect.py`. Send the tallies + a couple of misread frames for the fix. |
| **Whole-frame flakiness that tracks lighting** (house lights on/off, sun) | The per-frame threshold | Bump or re-measure `DET_THR` (safe band [19, 53]). Drift correction already handles exposure, so this should be rare. Last resort: IR illuminator + IR-pass filter. |
| **Catching the sweep, or catching pins still rocking** | Capture timing | Adjust `WSL_LANE_CAMERA_SETTLE_S`. |

Keep a **detected-vs-actual** tally per ball across both lanes and several leave types (strike, spare, split, single pin). **Target: a clean week of agreement** before declaring Track A "soaked."

**How calibration was originally done** (reproducible; scratch scripts in `~/Downloads`, see `docs/phase8_trackA_calibration_progress.md`): a synthetic empty was built as the per-pixel **min** across 4 labeled leave-frames; each leave was diffed, brightened, and grid-annotated to read off 8 solid cap positions per deck visually (pins 2,3 too dim/squeezed to measure); a rack→image **homography** per deck was fit from those 8 points (sub-3px residual) and used to **predict** pins 2,3 and emit `PIN_SPOTS_PX`. The detector was then validated against all 6 labeled frames at **12/12 deck-checks OK**.

---

### 18.9 Server, endpoints, and the display

The scoring server is `server/lane_node_server.py`. It runs on WSL-SRV and listens on **two ports**:

| Port | Protocol | Purpose |
|---|---|---|
| **8765** | WebSocket | Pi node ⇄ server. Carries `HELLO`, `BALL_EVENT`, `FOUL_EVENT`, `HEARTBEAT` (node→server) and `CYCLE`/`OPEN_LANE`/`CLOSE_LANE`/`RESET`/`POWER_ON`/`POWER_OFF` (server→node). |
| **8766** | HTTP | Scoring display, scoring JSON, health, and the manual `/score` + `/correct` endpoints. |

`PROTOCOL_VERSION = 2` (multi-lane). A node/server version mismatch logs a warning but does **not** reject the connection (degrade rather than refuse — a refused connection would mean a dead pinsetter).

**HTTP endpoints (port 8766):**

| Method + path | Use |
|---|---|
| `GET /?lane=N` *(and `/` root)* | Scoring display for lane N (the overhead/desk screen). |
| `GET /display` | Customer-facing display; serves `wsl_scoring_display.html` from the repo root; the page polls `/api/lane/<N>/scoring`. |
| `GET /api/lane/N/scoring` | Scoring JSON for lane N (what the display polls). Returns a `{open:false, players:[]}` stub if the lane has no state, so the display can render "Lane Closed." |
| `GET /api/state` | All active lanes' scoring snapshots. |
| `GET /api/health` | Server uptime, connected nodes, per-lane bowlers/scores/frame, pending fouls, state-DB path. **Use this to confirm the node is connected.** |
| `POST /api/lane/N/score` `{pin_mask:int 0-1023, foul?:bool}` | **Manual desk score / correction.** Records a ball; does **not** send `CYCLE` (the Pi already cycled). Strict range check — out-of-range `pin_mask` is rejected (not silently masked). `foul` is tri-state: `true` flags, `false` clears a stale foul, omitted leaves it. Always available, even in `camera` mode. |
| `POST /api/lane/N/correct` `{bowler_idx, frame_idx (0-9), bowls:[{pins_down 0-10, foul?}]}` | Rewrite a frame's bowls (desk correction). No hardware command. Returns the result plus a fresh `scoring` payload. |
| `POST /api/lane/N/trigger-ball` | **Bench helper only** — synthesizes a `BALL_EVENT` *and* sends `CYCLE`. Do **not** use on a live lane (it would pulse the pinsetter again and sweep the just-set rack). For live soak use `/score`. |
| `POST /api/lane/N/{open\|close\|reset\|power-on\|power-off}` | Lane/scoring lifecycle + machine commands relayed to the node. |
| `POST /api/pair/<L>-<R>/open-league` | Open a cross-lane league match across the pair (see Section 19). |

**How a `BALL_EVENT` is handled** (server `_process_ball_event` + the WS handler):

- `pin_mask` present (camera mode) → `record_ball()` immediately (**auto-score**), then send `CYCLE` to the node.
- `pin_mask=None` **or** `awaiting_manual=True` (manual mode) → send `CYCLE` so the lane resets, but **do not** record — wait for the desk's `POST /api/lane/<N>/score`. (This is what prevents bogus auto-scores; the server's internal `PIN_MASK_CYCLE` fallback is for the synthetic bench `trigger-ball` path only, never for a real `awaiting_manual` ball.)
- A pending `FOUL_EVENT` flag set since the previous ball is consumed by the next ball (scored `F`, 0 pins) — fouls are a **separate** signal (foul lamp circuit) from ball-detect (DIELL); see Section 4.

The scoring engine (`wsl_scoring_engine.LaneScoring` / `CrossLaneScoring`) consumes the masks and produces the running game. State persists to disk (`state_store`) so a server restart doesn't wipe in-progress games. The scoring logic, the desk-correction reconstruction, and cross-lane (league) play live in the scoring engine code (`wsl_scoring_engine.py`, in the main app — outside this manual's scope).

---

### 18.10 Service environment variables (the `lane-node` service)

| Variable | Default | Meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only. |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | Seconds after DIELL before grabbing the frame. *(VERIFY on 21/22 — see 18.5.2.)* |
| `WSL_LANE_CAMERA_DEVICE` | `0` | Capture device index (`/dev/videoN`). |
| `WSL_LANE_EMPTY_REF` | `lane_node/empty_ref.png` | Path to the per-install empty-reference PNG. |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks — **bench only, never on a live lane.** |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | The scoring server. Production: `ws://<WSL-SRV-IP>:8765`. |
| `WSL_LANE_NODE_ID` | `lane-node-dev-pair-21-22` | Node identifier sent in `HELLO`. |

> **(VERIFY: current WSL-SRV IP.)** The go-live runbook uses `192.168.4.103:8765/:8766` (post-2026-06-03 eero router swap; the old `192.168.86.36` is dead and a DHCP reservation was still TODO). **Confirm the live WSL-SRV IP and reserve it before go-live**, and set `WSL_LANE_SERVER_URL` to match. Do not treat any hardcoded IP in older docs as current.

---

### 18.11 Failure-mode cheat-sheet

| Symptom | Cause | Fix |
|---|---|---|
| Log: "detector NOT ready" | `empty_ref.png` missing / unreadable | Re-capture the empty reference (Section 18.6) |
| `--test` all-black / mask always 0 or 1023 | Video ground (RCA shell → Blue / cable pin-8) | Reseat the tap ground (18.2) |
| No `/dev/video0` | Dongle not enumerated | Reseat USB; check `dmesg` |
| Scores wrong but consistent | Spot / threshold calibration | Tally + misread frames → fix `PIN_SPOTS_PX` or `DET_THR` (18.8) |
| Nothing happens on a ball | DIELL not firing / wrong mode | Check log for "ball detected"; confirm `=camera` |
| Lane went dark after reboot | Service not `enable`d | `sudo systemctl enable lane-node` |
| Pins read standing right after a real ball, then a wrong score | Settle window too short (caught pins rocking) | Increase `WSL_LANE_CAMERA_SETTLE_S` (18.5.2) |

---

### 18.12 File reference

| File | Role |
|---|---|
| `lane_node/pin_detect.py` | M4 detection core; `DualDeckDetector`; calibrated `PIN_SPOTS_PX`, `DET_THR`, `MIRROR`, `DECK_TO_LANE`. Pure numpy. Legacy single-deck API kept for unit tests only. |
| `lane_node/camera.py` | `PairCamera`: capture handle (cv2 **or** PyAV), empty reference, `detect_lane()`, `--capture-empty`. Lazy capture import → unit-tests off-Pi. `SETTLE_S` lives here. |
| `lane_node/lane_node.py` | Pi daemon. DIELL → `_settle_capture_emit` → `BALL_EVENT`; scoring-mode logic; safe fallback. (Also drives the cycle/power relays + watchdog — Sections 9, 10.) |
| `server/lane_node_server.py` | Scoring server: WS 8765 + HTTP 8766; `_process_ball_event`; `/score`, `/correct`, `/scoring`, `/health`, display. |
| `wsl_scoring_engine.py` | The bowling scorer (mask → score). Section 19. |
| `wsl_scoring_display.html` | Customer/overhead scoring display (polls `/api/lane/<N>/scoring`). |
| `docs/phase8_trackA_golive_runbook.md` | Step-by-step go-live (18.7). |
| `docs/phase8_trackA_calibration_progress.md` | How calibration was done + status. |


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
> upstream. The **TB/SC table–sweep collision interlock** stays a hardware loop. The board's job
> is to add a *permission* layer and a *fast-supervision* layer on top of those — not to replace
> them. This is the non-negotiable safety rule stated in the design contract
> (`docs/phase8b_pcb_revB_spec.md` §"Non-negotiable safety rule" and §4.5) and repeated in the
> firmware (`firmware/rp2040/main.c` SAFETY MODEL header) and the cutover runbook
> (`docs/phase8_trackB_controller_cutover_runbook.md` §0).

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
| **FIRMWARE** | The RP2040 co-processor on each board | The Pi and the UART link | A motor commanded to run and never stopped (max-run), a hung Pico, and (v1.1) a stop-cam overrun |
| **SOFTWARE** | The cycle FSM + daemon on the Raspberry Pi | — (top layer; backed by the two below) | Commanding into a known-bad interlock state, motion-state timeouts, RP2040 health loss, and the power-restore "no motion until a deliberate operator zero" rule |

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
**irreducible, final physical stop.** Phase 8 does **not** replace or move it — the cutover
runbook (§1, §3.5) explicitly leaves the Stop/CIS/master chain intact and upstream, and the
controller's safety rail additionally *requires* this chain to be closed (condition 6 below).

Why it stays the final stop: it is the only layer that removes machine control *power*, as
opposed to removing *permission*. It is therefore the only thing that can stop a machine whose
on-board relay contact has welded closed (see §19.2.6).

#### 19.2.2 The TB/SC table–sweep collision interlock (OEM, preserved as a hardware loop)

The 82-70 has two interlock cams that together detect a table–sweep interference (collision)
course:

| Cam | Window | Meaning |
|---|---|---|
| **SC** (sweep) | ~86–243° | sweep is under the table |
| **TB** (table) | ~105–255° | table is in the sweep-interference zone |

Per `docs/phase8_8270_SYSTEM_REFERENCE.md` §5 and the OEM audit
(`docs/phase8_oem_doc_audit_2026-06-02.md` §2), **TB and SC are wired in parallel into the 24 V
relay-control path; both motor relays drop when table and sweep are both in their unsafe
interference relationship.** Critically, the OEM's own manual-override sweep/table buttons bypass
*all* logic **except** the back-end motor and this TB/SC interlock — so the OEM itself treats
TB/SC as the irreducible hardware interlock. The OEM audit confirms it is "a real hardware
interlock, not a software hint."

Rev-B preserves this as a **first-class hardware rail condition** (condition 5 below): an external
**normally-closed (NC) loop** wired to the `J_SAFETY` connector (J14) that, when it opens on a
collision course, removes the rail's source feed in hardware — no Pi or RP2040 software is in that
path. The design contract (§4.4) is explicit: the schematic must make the interlock a first-class
rail condition, "not merely an RP2040/MCP input," and must "not soften their role into advisory
firmware-only inputs." The firmware/software *also* observe SC/TB (see §19.4.4), but that
observation is a **secondary echo** that can only *veto*, never *enable*, motion.

> **(VERIFY: final TB/SC electrical form and J14 wiring.)** The exact field derivation — TB/SC cam
> contacts directly, the existing 24 V control path, or a separate low-voltage isolated loop — and
> the precise J14 landing are a deliberately-deferred cutover field item (contract §4.4 / §11 item
> 3; runbook §3.4, Appendix B.4). The board provides the NC-loop topology; wire it to **break** on
> the collision condition (NC = closed when safe).

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

#### 19.2.5 The non-bypassable relay-enable rail (6 conditions)

The single most important on-board safety structure is the **relay-enable rail**
(`RELAY_ENABLE_RAIL`). It is the high-side +5 V supply to **every** motion-relay coil. The rail is
live only when a P-channel pass-FET (**Q14**, AO3401A, LCSC C347476) is on, and Q14 is on only
when **all six** conditions below are simultaneously true. **The Pi cannot bypass any of them in
software** (contract §4.1). Every condition's default is **false/open** (fail-safe). The
authoritative six-condition list (matching the cutover runbook §0 and contract §4.1):

| # | Condition | Source | Where it acts on the rail | Fail-safe default |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 (U36) kicked by the Pi (`WDOG_KICK` / GPIO12) → FET Q13 | Bottom of the gate AND chain (Q13 must conduct) | false (no kicks → Q13 off) |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO (J1 pin 8) → NPN Q15; asserted only after operator-safe state / First-Ball-Zero | Top of the gate AND chain (Q15 must conduct) | false (R108 100 k base pulldown) |
| 3 | **RP2040 OK** | RP2040 `GP2` health/permission line (`RP2040_OK`) → NPN Q16 | Middle of the gate AND chain (Q16 must conduct) | false (R110 100 k base pulldown; GP2 Hi-Z on reset) |
| 4 | **Cam-stop OK** | RP2040 immediate cam-stop drop path | **Folds into condition 3** — firmware drives `GP2` LOW on a cam-stop violation/timeout | false on RP2040 reset/fault |
| 5 | **TB/SC hardware interlock** | External NC loop on `J_SAFETY` J14 pins 1↔2 | In series with the FET **source** | open (loop break removes source feed) |
| 6 | **Stop/CIS/master chain** | External NC loop on `J_SAFETY` J14 pins 3↔4 | In series with the FET source, after the TB/SC loop | open |

Two structural facts make this a genuine hardware AND (verified against
`scripts/generate_kicad_netlist_revB.py` `block_rail()`):

- **Conditions 5 and 6 are NC loops in series with the FET source.** +5 V enters J14 pin 1, must
  traverse the closed **TB/SC** loop (pins 1→2), cross the on-board jumper (`SAFE_TBSC_RETURN`,
  J14 pin 2 = pin 3), traverse the closed **Stop/CIS/master** loop (pins 3→4,
  `SAFE_STOP_RETURN`), and only then reach Q14's source. Break either loop and the FET source is
  dead — no gate state can re-enable the rail.
- **Conditions 1, 2, and 3 (= 4) are a series transistor stack on the FET gate.** The gate
  (`RAIL_GATE`) is pulled **up to the source** by R106 (100 k) — off by default. To turn the rail
  on, three transistors in series (Q15 "AND ARM" → Q16 "AND RP_OK" → Q13 "wdog") must **all**
  conduct to pull the gate to ground. Each base/gate has its own 100 k pulldown (R108, R110, R105)
  so the default with no drive is off. Any one open → chain open → R106 holds the gate at the
  source → FET off → rail dead.

**Why cam-stop is not a sixth transistor.** Condition 4 (Cam-stop OK) is a *firmware behavior*,
not a separate device: the RP2040 is the cam-stop enforcer and pulls its single `GP2` health line
LOW on a cam-stop violation/timeout (contract §4.2; firmware README). Electrically there are
**five physical gates** (two source loops + a three-transistor gate AND), and cam-stop drives one
of them (`RP2040_OK` / Q16) false. Do not look for a sixth transistor — there isn't one. Full
schematic, pin→net tables, and the AND-chain diagram are in **§10.3 / §10.4**.

**What the rail gates — two gates in series for any motion output.** A motion relay energizes only
if **(a)** the Pi sets that relay's `MCP23017 OUT-A` bit (turning the per-relay NPN on to ground
the coil low side) **AND (b)** the rail is live (supplying +5 V to the coil high side). The Pi
controls (a); the six-condition rail controls (b). **Software alone cannot fire a coil.** The rail
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

This is the firmware's affirmative motion-safety contribution that exists **today** (v0.1.0). The
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

#### 19.3.4 Deferred to v1.1 — per-cam stop overrun (NOT in current firmware)

**Per-cam-edge cam-stop OVERRUN enforcement** — a stop-cam fires while a motor is RUNNING and the
Pi fails to `STOP` it within a grace window → drop `RP_OK` — is **deliberately deferred to firmware
v1.1** (`firmware/rp2040/README.md`; `main.c` `// v1.1` hook in `supervise()`). It requires the
**per-cam edge→angle polarity**, which is itself a deferred cutover field item (runbook §3.2): the
project will not bake in unconfirmed cam polarity. **What this means for safety:** v1 provides
RP2040 *health* + the *motion max-run* backstop (§19.3.3), but **not** crisp per-cam-edge overrun
detection. The SC/TB collision echo gating `RP_OK` is likewise a v1.1 item (the hardware J14 loop
is primary; §19.2.2/§19.4.4). This gap is the reason the cutover **G3** gate's cam-stop sub-test is
blocked until v1.1 is flashed (see §19.5).

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

#### 19.4.4 FSM interlock echo (secondary, advisory)

The FSM gates **every** motor energize on `io.interlock_ok()` (`cycle_control_8270.py`
`_safe_sweep` / `_safe_table` / `on_ball` / `bin_full`). When an RP2040 link is wired, that echoes
the firmware's SC/TB danger state: `interlock_ok()` returns False only when **SC AND TB are both in
their danger window at once** — a true collision course (`rp2040_link.interlock_ok()`,
`controller_io.MachineIO.interlock_ok()`). This is explicitly a **secondary software echo** of the
hardware TB/SC loop (§19.2.2): it lets the FSM avoid commanding into a known-bad state, but it
defaults to `True` (no veto) when no link is present, so the software echo can only ever *block*
motion, never *enable* motion the hardware would block. The authoritative interlock is the J14 NC
loop in hardware.

---

### 19.5 What each layer catches (summary matrix)

The lowest applicable layer is the guarantee; upper layers catch the same hazard earlier and keep
state consistent. "Rail" = `RELAY_ENABLE_RAIL` live? "Coils" = can any motion relay energize?

| Hazard / event | Caught by (lowest → highest) | Net effect on the rail |
|---|---|---|
| Loss of 115 VAC / operator hits Stop / cushion (C.I.S.) | **HW:** master breaker cuts all control power | machine dead (power removed, not just permission) |
| Table–sweep collision course | **HW:** TB/SC NC loop opens (cond. 5). **FW/SW:** SC∧TB echo vetoes (advisory) | rail dead |
| Pi process hangs / OS dies | **HW:** NE555 stops being kicked → Q13 off (cond. 1) | rail dead, coils drop |
| Pi de-asserts ARM (or enters MANUAL_INTERVENTION/FAULT) | **HW:** Q15 off (cond. 2), driven by **SW** power-down/fault logic | rail dead |
| RP2040 unpowered / reset / BOOTSEL | **HW:** GP2 Hi-Z → R110 holds Q16 off (cond. 3) | rail dead |
| RP2040 firmware loop hangs | **FW:** internal WDT (250 ms) resets chip → GP2 Hi-Z → cond. 3 off | rail dead |
| Motor commanded RUN and never STOPped | **FW:** max-run 8 s → `flt:motion_timeout` → GP2 LOW (cond. 3/4). **SW:** FSM motion-timeout → FAULT → ARM drop | rail dead |
| Stop-cam overrun (motor past its stop cam) | **FW v1.1 (deferred):** cam-stop overrun → GP2 LOW. *Today:* covered only by the 8 s max-run, not per-cam-edge | rail dead (once v1.1) |
| RP2040 health blip mid-cycle | **HW:** cond. 3 drops instantly. **SW:** daemon full safety trip → motors off, latch MANUAL_INTERVENTION, require PBZ | rail dead; no stale-latch auto-resume |
| Power restored after an outage | **SW:** FSM comes up MANUAL_INTERVENTION; **HW:** ARM held low until operator First-Ball-Zero | rail dead until deliberate operator zero |
| Welded relay contact | **HW:** master breaker only — the rail drops the coil but cannot open a welded contact (§19.2.6) | rail dead, **but welded contact stays made → breaker required** |
| Motor runs but must brake | **HW:** OEM regenerative braking on the contactor NC contacts (§19.2.3) | independent of the board |
| Board powers up (pre-init) | **HW:** GP2 Hi-Z + ARM low + no kicks → all three gate conditions off | rail dead |
| All six conditions true | Q15·Q16·Q13 conduct → gate low → P-FET on; both NC loops closed | **rail live** — Pi's OUT-A bit can energize that coil |

---

### 19.6 Why cam-stops are now solely the RP2040's job

On the original AMF 82-70, the **cam-position stops are controller LOGIC**, not a hardwired
motor latch: the controller reads a cam edge and drops the relay (`docs/phase8_8270_SYSTEM_REFERENCE.md`
§5 — "Cam-position stops are controller LOGIC … not a hardwired motor latch"). Bench work on the
21/22 chassis (the Omega-Tek retrofit) confirmed the same thing the runbook records (§0): **the
OEM machine uses *logic* stops (on the triac board), not cams wired in series with the motors.**

The direct consequence: **removing the Omega-Tek/OEM controller removes the existing cam-stop.**
There is no hardwired cam-stop backstop left in the machine once the OEM brain is unplugged. The
**RP2040's cam-stop replaces it** — the RP2040 reads the cams fast (no Pi scheduling latency) and
drives `RP2040_OK`/the rail. This is *why*:

- cam-stop is condition 3/4 of the rail (an RP2040 responsibility), not a separate machine wire;
- the RP2040 cam-stop must be **bench-proven before cutover** (contract §12.9);
- the cutover **G3** safety-drop gate's cam-stop sub-test is a **hard gate** (§19.5; runbook §6
  Stage 6b / §7);
- and the per-cam-edge overrun enforcement is held to firmware **v1.1** until cam polarity is
  field-confirmed (§19.3.4) — the one piece of "cam-stop" that is not yet implemented, and the
  reason the G3 cam-stop sub-test is blocked until v1.1 is flashed.

> **(VERIFY: per-cam edge→angle polarity.)** The mapping of each cam's `f`/`r` edge to its angular
> trip is unconfirmed and is a cutover field-capture item (runbook §3.2, Appendix B.2). v1.1
> cam-stop overrun depends on it. Until captured, the firmware default assumes `f` = trip
> (`rp2040_link.py` `trip_edge="f"`; firmware README) but does **not** enforce per-cam overrun.

---

### 19.7 The cutover G3 safety-drop gate

Because a controller cutover changes what *moves the machine* (unlike the read-only Track-A scoring
cutover, whose worst case is a wrong score), the controller cutover is gated on a fully
bench-validated unit and uses a **staged, rail-disabled** bring-up (runbook §0, §6, §7). The heart
of the procedure is **Go-gate G3** at Stage 6b: with the rail's enable on a bench-safe armed path
(no machine power), prove that **each** of the six rail conditions **independently drops motion
permission**:

| G3 sub-test | Action | Expected | Status today |
|---|---|---|---|
| Watchdog | stop the Pi's NE555 kick | rail drops | testable with v1 firmware |
| Arm | de-assert `ARM_PERMIT` | rail drops | testable with v1 |
| RP2040 health | reset/halt the RP2040 | rail drops (GP2 → Hi-Z/LOW) | testable with v1 |
| Cam-stop | trigger a stop-cam edge while "running" | rail drops | **BLOCKED until firmware v1.1** (needs per-cam polarity, §19.3.4/§19.6) |
| TB/SC interlock | open the J14 TB/SC NC loop | rail drops | testable with v1 |
| Stop/CIS | open the J14 Stop/CIS NC loop | rail drops | testable with v1 |

**Pass condition (G3):** every one of the six drops motion permission. **Fail action: ABORT and
roll back to the OEM brain — do not "fix it live."** Any failure at or before the subsequent
**G4** (commanded S/T/SP each stop on cams; full reset completes and stops; no runaway) is also a
rollback (runbook §7, §8). The order is deliberate: capture cam polarity first (Stage 2 / §3.2),
flash v1.1, then run the cam-stop sub-test; the other five drop-tests do not depend on v1.1. This
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
  schematic, every pin→net table, the J14 NC-loop wiring, the relay-coil rail map, and the
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


## 20. Operations: Network, Deployment, Build & Fab

This section is the operate-and-reproduce reference for the Phase 8 system as a whole:
how the running software is laid out across the network and how it is brought up,
followed by how the lane-controller PCB is generated, audited, and ordered from a
bare repository checkout. It is written to be self-contained — an engineer with no
prior context should be able to (a) bring a node back online after a power event,
(b) re-point the fleet after a network change, and (c) regenerate and re-order the
board.

Cross-references:
- Hardware topology and the FSM that consumes the I/O are covered in the controller
  sections; this section covers the *operational envelope* around them.
- The on-board GPIO/MCP/relay maps are reproduced here only where they bear on
  bring-up; the authoritative electrical contract is **§ (PCB Schematic Contract)**
  and `docs/phase8b_pcb_revB_spec.md`.

---

### 20.1 Runtime architecture at a glance

Phase 8 is a **one-server / N-node** system that runs *alongside* the existing
Westside Lanes Phase 4 stack — it does **not** replace any Phase 4 service. The two
stacks coexist on the same WSL-SRV host on non-overlapping ports.

| Role | Where it runs | Process / entry point | Listens on | Talks to |
|---|---|---|---|---|
| Lane-node server | WSL-SRV (Windows 11, production server) | `server/lane_node_server.py` | **WS `0.0.0.0:8765`** + **HTTP `0.0.0.0:8766`** | Pi nodes (WS), browsers (HTTP) |
| Lane node (daemon) | Raspberry Pi at the lane pair | `lane_node/lane_node.py` (systemd `lane-node.service`) | — (outbound WS client) | the server at `:8765`; local GPIO/camera |
| Scoring display / desk simulator | any LAN browser | served by the server | `http://<WSL-SRV>:8766/` | the server |
| Phase 4 ops API (separate stack) | WSL-SRV | `wsl_api.py` | `:5000` | proxies Phase 8 scoring via `localhost:8766` |
| Phase 4 analytics (separate stack) | WSL-SRV | `wsl_analytics_server.py` | `:5002` | — |

Key facts (all grounded in the live code):

- The server binds `0.0.0.0` on **8765 (WebSocket)** and **8766 (HTTP)**
  (`server/lane_node_server.py` — `serve(handle_node, "0.0.0.0", 8765)` and
  `HTTPServer(('0.0.0.0', 8766), HttpHandler)`). Those two ports are the entire
  server surface.
- The node is a **WebSocket client**: it dials *out* to the server, so the node
  needs no inbound firewall holes. One Pi controls **one pair** of lanes
  (`LANES = [21, 22]` in `lane_node.py`).
- The Phase 4 `wsl_api.py` reaches the Phase 8 score store through a
  `localhost:8766` proxy (so the Phase 8b score-read/correct path survives even
  when the server's external IP changes — see § 20.4).

> **Safety reminder (carried from the controller sections):** none of the software
> in this section is a safety device. Motion permission is gated by the on-board
> hardware safety rail (NE555 watchdog + ARM + RP2040_OK + TB/SC interlock +
> Stop/CIS chain). The Pi/FSM cannot bypass that rail in software. See
> `docs/phase8b_pcb_revB_spec.md` § 4.

---

### 20.2 The Raspberry Pi lane node

#### 20.2.1 What it is

One Pi per lane pair. At startup it iterates `LANES` and instantiates `gpiozero`
devices per lane from the `LANE_GPIO` table, registers callbacks, opens (in camera
mode) a single shared T-Camera for both decks, and connects to the server over
WebSocket. The node forwards ball/foul/heartbeat events up and executes
open/close/reset/power/cycle commands coming down.

#### 20.2.2 Pi GPIO map (BCM numbering)

These are the **Pi header GPIOs** the daemon drives/reads directly via `gpiozero`
(`LANE_GPIO` + the board-level watchdog pin in `lane_node.py`). **This is distinct
from the RP2040 co-processor GPIO map** (§ 20.6.3) and from the MCP23017 bit maps
(§ 20.6.4) — three different parts, three different pin namespaces. Do not conflate
them.

| Function | Lane 21 (BCM) | Lane 22 (BCM) | gpiozero device | Notes |
|---|---|---|---|---|
| Foul-lamp input | 5 | 17 | `Button(pull_up=False, bounce=0.05)` | Named `BALL_DETECT` for back-compat; fires `FOUL_EVENT` |
| 2nd-ball-lamp input | 6 | 22 | `Button(pull_up=False, bounce=0.05)` | Wired, state-only (no callback yet) |
| Pinsetter cycle (out) | 24 | 27 | `LED` (momentary pulse) | Relay closes briefly |
| Pinsetter power (out) | 25 | 23 | `LED` (latched on/off) | Relay holds until told otherwise |
| DIELL left beam (in) | 13 | 19 | `Button(pull_up=False, bounce=0.02)` | Ball detect; `when_released` fires `BALL_EVENT` |
| DIELL right beam (in) | 16 | 20 | `Button(pull_up=False, bounce=0.02)` | Ball detect (second beam) |
| **Watchdog kick (out)** | **12 (board-level, not per-lane)** | | `LED` | One NE555 per PCB/pair; petted ~1 Hz |

Operating theory worth keeping in mind:

- **The actual ball is detected by the DIELL beams, not by `BALL_DETECT`.** The
  `BALL_DETECT`/`BALL2_DETECT` names are historical (foul/2nd-ball lamp inputs);
  the comment block in `lane_node.py` is explicit about this. When a DIELL beam
  releases, the daemon emits a `BALL_EVENT`.
- **`WATCHDOG_KICK_PIN = 12` is board-level**, not per-lane, because there is one
  NE555 monostable per PCB. `watchdog_kick_loop()` pulses it at ~1 Hz; the NE555
  drops the relay-coil rail (all relays open) if it is not pulsed at least every
  **~11 s**. On shutdown the daemon forces this pin **LOW** in `_cleanup_gpio()` —
  a retained-HIGH kick pin would keep the watchdog alive and defeat it. The
  separate `relay_cleanup.py` must also force GPIO 12 LOW on SIGKILL, and its
  `RELAY_PINS` must stay in sync with the cycle/power values above.

> **Pi GPIO is 3.3 V only.** Never wire a 5 V (or higher) machine signal to a Pi
> input. Field signals reach the Pi only through the PCB's opto front-ends
> (PC817 / RP2040 / MCP23017), never directly. Use button-to-GND with the pull
> configured in firmware; opto-isolate anything higher than 3.3 V.

#### 20.2.3 Scoring modes

`WSL_LANE_SCORING_MODE` (§ 20.3) selects how DIELL ball events turn into scores:

| Mode | DIELL behavior | Use when |
|---|---|---|
| `manual` *(default)* | Emits `BALL_EVENT` with `pin_mask=None`; the desk enters pins via `POST /api/lane/<N>/score` | The safe Phase 8a cutover default until the camera is calibrated |
| `camera` | After a ball, waits `WSL_LANE_CAMERA_SETTLE_S`, captures a frame off-loop (`asyncio.to_thread`), detects standing pins, emits `BALL_EVENT` with the `pin_mask` | Only after the T-Camera + `pin_detect.PIN_SPOTS` are calibrated against real frames |
| `disabled` | DIELL logged on the Pi, **no** message sent to the server | Bench-testing with no scoring side effects |

An unknown value falls back to `manual` with a warning. In `camera` mode with no
real camera/empty-reference present, the daemon emits "awaiting manual" rather than
fabricating pins — unless `WSL_LANE_CAMERA_STUB=1` is set (bench only; never on a
live lane).

#### 20.2.4 Protocol version

`PROTOCOL_VERSION = 2` (multi-lane `LANES`). v1 was single-lane (`LANE_ID`). The
server compares its own version on the `HELLO` handshake and logs a warning on
mismatch — it does not hard-fail, so a version skew is visible in the log, not in a
crash.

---

### 20.3 `WSL_LANE_*` environment variables

Every node-side knob is an environment variable, read in `lane_node/lane_node.py`
(and `lane_node/camera.py`). In production they are set on the systemd
`lane-node.service` via a drop-in (§ 20.5). This is the complete list.

| Variable | Default | Read in | Meaning |
|---|---|---|---|
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | `lane_node.py` | The server WS URL. **Production must override this to the live WSL-SRV IP** (§ 20.4). |
| `WSL_LANE_NODE_ID` | `lane-node-dev-pair-21-22` | `lane_node.py` | Node identity sent on `HELLO`; appears in the server log as `Node '<id>' registered`. |
| `WSL_LANE_SCORING_MODE` | `manual` | `lane_node.py` | `camera` \| `manual` \| `disabled` (§ 20.2.3). |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | `camera.py` | Seconds after DIELL before grabbing the frame (let pins stop rocking, before the sweep clears them). |
| `WSL_LANE_CAMERA_DEVICE` | `0` | `camera.py` | Capture device index → `/dev/videoN`. |
| `WSL_LANE_EMPTY_REF` | *(path)* | `camera.py` | Path to the captured empty-deck reference frame the detector diffs against. |
| `WSL_LANE_CAMERA_STUB` | `0` | `lane_node.py` | `1` = rotate synthetic masks (bench only; never on a live lane). |

> The defaults are **dev** defaults (localhost server, dev node id, manual scoring,
> stub off). A node that comes up "connected to localhost" or registered as
> `lane-node-dev-pair-21-22` on the server is running with un-overridden defaults —
> check the service drop-in.

---

### 20.4 Network: the 2026-06-03 eero re-IP (READ THIS)

**On 2026-06-03 the shop router was replaced with an eero.** This changed the entire
subnet, and several facts in older docs are now wrong.

| Item | Old (DEAD) | Current |
|---|---|---|
| Subnet / mask | `192.168.86.0/24` | **`192.168.4.0/22`** (mask `255.255.252.0`) |
| Gateway + DNS | `192.168.86.1` | **`192.168.4.1`** |
| **WSL-SRV address** | **`192.168.86.36` (static — now DEAD)** | **`192.168.4.103`** (DHCP lease) |
| WSL-SRV NIC | static | DHCP (interface idx 5, MAC `10-B6-76-51-EC-5D`) |

What happened: WSL-SRV's stale static `192.168.86.36` left it islanded under the new
eero subnet (no gateway → no internet, unreachable, AnyDesk down). The fix was to
revert the WSL-SRV Ethernet NIC from static to DHCP; it leased `192.168.4.103` and
came back. **No code changes were needed** — `wsl_api`, analytics, and
`lane_node_server` all bind `0.0.0.0`, and the Phase 4→Phase 8 proxy uses
`localhost:8766`.

**Decision (Dylan):** track the eero subnet and re-IP the fleet — do **not**
reconfigure the eero back to the old `192.168.86.0/24`.

**Open TODOs (not yet done — treat any `.86.x` address in any doc as stale):**

1. **Reserve `192.168.4.103`** for MAC `10-B6-76-51-EC-5D` on the eero (app → device
   → Reserve IP) so the DHCP lease can't drift. The NIC stays on DHCP. **Until this
   reservation exists, the WSL-SRV address can move again** — always confirm the
   current IP before a go-live and set `WSL_LANE_SERVER_URL` to match.
2. **Re-point every client** still dialing `192.168.86.36` → `192.168.4.103`, and
   confirm each client is itself on `.4.x`:
   - Pi lane node: `WSL_LANE_SERVER_URL` in
     `/etc/systemd/system/lane-node.service.d/override.conf` (port `:8765`).
   - Display/kiosk: the scoring-display URL (port `:8766`).
   - Desk / POS / KDS bookmarks (`:5000`) and analytics (`:5002`).

> **Stale-doc warning (updated 2026-06-10):** `HANDOFF.md`, the `phase_8a_*` docs, the
> deploy doc in § 20.5, and the Track-A go-live runbook have been corrected to
> `.4.103` (or banner-annotated where historical) in the 2026-06-10 doc sweep, but
> several memories and any docx/PDF exports still cite `192.168.86.36`. When you see
> `.86.36` anywhere, mentally substitute the current reserved WSL-SRV IP. The old `.71.x` ETHost bridge stays dead (BACKOFFICE1 `.86.31`
> is also islanded) — acceptable per the subnet-retirement plan.

---

### 20.5 Server deployment + the systemd lane-node service

#### 20.5.1 Server deployment to WSL-SRV (summary)

The full procedure is `docs/deploy_server_to_wsl_srv.md`. The shape of it:

1. **Get the code onto WSL-SRV.** Either `git clone https://github.com/dylan24483/wsl-lane-nodes.git`
   into `C:\QDesk\` (HTTPS read-only; the repo was made public for deploy), or
   AnyDesk file-transfer the laptop folder into `C:\QDesk\wsl-lane-nodes\`. WSL-SRV
   has no git/SSH key for GitHub.
2. **Python venv + deps.** `py -3 -m venv .venv`, activate, `pip install websockets`.
   The server needs only `websockets` (plus built-in `sqlite3` and `http.server`);
   the Pi-only packages (`gpiozero`, `lgpio`, …) are **not** needed on the server. If
   WSL-SRV has no outbound 443, transfer the `websockets` wheel via AnyDesk and
   `pip install <wheel>`.
3. **Smoke test.** `python server\lane_node_server.py` should print the
   HTTP + WS listen lines and "No saved state found … starting fresh", and
   `http://<WSL-SRV>:8766/` should load the desk simulator. If the browser can't
   reach it, add a Windows Defender Firewall inbound rule for **8765-8766**.
4. **Point the Pi at WSL-SRV** by setting `WSL_LANE_SERVER_URL` (§ 20.3, § 20.5.2).
5. **Auto-start (production):** wrap the server as a Windows service. The repo doc
   suggests **Task Scheduler** (run `…\.venv\Scripts\python.exe …\server\lane_node_server.py`
   at boot, restart-on-failure) or **NSSM**. Per the deployment-progress memory the
   live server currently runs on WSL-SRV via **Task Scheduler**.

> **Windows Task Scheduler trap (from the Phase 4 side, applies here):** the
> `:5000`/`:5002` scheduled tasks were auto-killed every 3 days by a default
> `PT72H` `ExecutionTimeLimit` (fixed to `PT0S`). If you create a Task Scheduler
> entry for `lane_node_server.py`, set `ExecutionTimeLimit` to `PT0S` (run
> indefinitely) and enable restart-on-failure.

The server's state lives in `<repo_root>/lane_state.db` (SQLite). Migrating
dev-server → WSL-SRV-server starts from a fresh empty DB; `cp lane_state.db` between
hosts only if score continuity matters (it does not for a clean cutover).

#### 20.5.2 The systemd `lane-node` service (Pi side) — MUST be enabled

On each Pi the daemon runs as a systemd service named **`lane-node.service`**.
Production environment overrides go in a drop-in:

```
/etc/systemd/system/lane-node.service.d/override.conf
```

Example drop-in (camera mode, pointed at the current WSL-SRV IP):

```ini
[Service]
Environment=WSL_LANE_SERVER_URL=ws://192.168.4.103:8765
Environment=WSL_LANE_SCORING_MODE=camera
Environment=WSL_LANE_CAMERA_SETTLE_S=2.5
# Environment=WSL_LANE_CAMERA_DEVICE=0   # set only if the dongle isn't /dev/video0
```

Apply changes:

```bash
sudo systemctl edit lane-node       # opens the drop-in
sudo systemctl daemon-reload        # after a hand-edit of the unit/drop-in
sudo systemctl restart lane-node
journalctl -u lane-node -f          # watch the log live
```

> **CRITICAL — the service MUST be `systemctl enable`d on every node.** A node can be
> *loaded* and *active* without being *enabled*. An enabled-less node survives only
> until the next reboot/power event, then comes up dead. This actually bit the bench
> rig: the service was loaded/active but not enabled, and survived 6 days only
> because the Pi hadn't rebooted. **Symptom of the bug: "the lane goes dark after any
> power event."** The production provisioning runbook must include:

```bash
sudo systemctl enable lane-node      # <-- the step that is easy to forget
sudo systemctl enable --now lane-node   # enable + start in one go
systemctl is-enabled lane-node       # verify: must print "enabled"
```

#### 20.5.3 Health checks and the end-to-end "is it alive" test

| Check | Command / action | Expect |
|---|---|---|
| Node connected (Pi log) | `journalctl -u lane-node -n 50` | `Connecting to ws://<WSL-SRV>:8765 …` then `Connected. Sending hello (lanes=[21, 22], protocol_version=2).` |
| Node registered (server log) | watch the server console / log | `New connection from (…)` then `Node '<id>' registered (lanes=[21, 22], protocol_version=2)` |
| Server up (HTTP) | `curl http://<WSL-SRV>:8766/api/health` | healthy response (also used for the overnight soak check) |
| Display | open `http://<WSL-SRV>:8766/display?lane=21` (and `?lane=22`) | scoring display loads and updates on a ball |
| Full chain | click "Open Lane" on lane 22 in the desk simulator | the lane's cycle relay clicks (bench: relay 1 clicks 3×) |

> **Camera-mode startup tell:** on restart you want `Camera ready for lanes [21, 22]
> (settle=2.5s).` If you instead see `Camera mode but detector NOT ready`, the empty
> reference didn't load — **the lane still runs, it just falls back to manual
> scoring.** Not dangerous; just not auto-scoring yet.

#### 20.5.4 Instant abort to manual

If detection is flaky, flip the node back to manual without any machine impact:

```bash
sudo systemctl edit lane-node   # change WSL_LANE_SCORING_MODE=camera → manual
sudo systemctl restart lane-node
```

Manual mode emits the ball event with no `pin_mask`; the desk scores via the
existing `/api/lane/<N>/score` flow. There is **no machine impact** either way —
scoring mode never changes what the controller does at the lane.

---

### 20.6 The lane-controller PCB — build & fab

This is the from-scratch reproduction path for the Phase 8b Rev-B board: one
identical four-layer PCB controls **one** lane; a lane pair uses two boards on one
Pi (the camera may be shared, but all machine-control wiring is per lane). The
board integrates what used to be discrete AEDIKO relay + AL-ZARD opto-input modules
into a single board with on-board PC817 optos, G5LE relays, three MCP23017
expanders, an RP2040 co-processor (hand-soldered Pico), an NE555 hardware watchdog,
and an isolated field-wetting DC/DC.

> **Board status:** **PCB-fab-ready** under a conservative DRC contract. It is **not**
> assembly/cutover-ready: relay-contact ratings, input population defaults
> (dry-contact vs 24 VAC sense), the TB/SC/Stop-CIS connector form, status-LED
> sizing, the M1 population decision, and on-hardware bench bring-up all still gate a
> *populated, live-machine* controller. See `docs/phase8b_pcb_revB_spec.md` § 11.

#### 20.6.1 Toolchain

| Tool | Version / path | Role |
|---|---|---|
| KiCad | **10.0** at `C:\Program Files\KiCad\10.0\` | Footprint library, `pcbnew` Python API, `kicad-cli.exe` |
| KiCad bundled Python | `C:\Program Files\KiCad\10.0\bin\python.exe` | **Must** run any script that `import pcbnew` |
| SKiDL | (in that Python env) | Netlist generation from `generate_kicad_netlist_revB.py` |
| FreeRouting | — | **Rejected for this board** (see below) |

Two hard toolchain rules, both load-bearing:

1. **Run board scripts with KiCad's bundled Python**, not the system Python — the
   `pcbnew` module only exists there. Scripts that only manipulate CSVs
   (`prepare_*`) run under the ordinary `sys.executable` and are invoked that way by
   the export driver.
2. **FreeRouting does not produce an acceptable board here.** Full-board autoroute
   attempts produced hundreds of DRC violations (4-layer = 473 violations + 3
   unconnected; F/B-only = 625 + 3), and re-band attempts produced no `.ses` after
   long runs. **Manual deterministic routing is the accepted path.** Do not "just
   autoroute it."

#### 20.6.2 The generate → place → netclass → route → export pipeline

All five scripts live in `scripts/`. They form an ordered, repeatable pipeline; the
artifacts each one writes are the input to the next.

| Step | Script | Run with | Reads → Writes |
|---|---|---|---|
| 1. Netlist | `generate_kicad_netlist_revB.py` | KiCad python | (SKiDL source) → `kicad/wsl-phase8b.net` |
| 2. Place | `place_components_revB.py` | KiCad python | netlist → `kicad/wsl-phase8b.kicad_pcb` (250×225 mm, 4-layer, domain bands) |
| 3. Net classes | `apply_netclasses_revB.py --write` | KiCad python | `…kicad_pcb` → same board with all named nets bound to one of 5 classes |
| 4. Route | `manual_route_revB.py` | KiCad python | `kicad/wsl-phase8b.kicad_pcb` → `kicad/wsl-phase8b.routed-manual.kicad_pcb` |
| 5. Export fab | `export_fab_revB.py` | KiCad python | `…routed-manual.kicad_pcb` → `kicad/fab_revB_routed_manual/…` (full package) |

Supporting scripts: `export_specctra_revB.py` (Specctra `.dsn` for any external
routing experiment) and the CSV preparers `prepare_pcba_parts_revB.py`,
`prepare_jlc_standard_pcba_revB.py`, `prepare_hand_solder_procurement_revB.py`
(invoked automatically by `export_fab_revB.py`).

**The five net classes** (assigned in step 3, enforced by the custom `.kicad_dru`
in step 4/5). These are the isolation backbone of the board; if they are not
actually assigned on the routed board, the `.dru` `hasNetclass()` isolation rules
become vacuous and a "0 violations" result is meaningless. The board carries
**184 named nets**, partitioned exactly as:

| Net class | Count | Trace width | Clearance | Carries |
|---|---:|---|---|---|
| `Logic_Signal` | 80 | 0.25 mm | 0.20 mm | Logic-side signals (UART, I2C, drive locals) |
| `Logic_Power` | 4 | 0.50 mm | 0.20 mm | VCC_5V / VCC_3V3 distribution |
| `Safety_Rail` | 13 | 0.60 mm | 0.30 mm | `RELAY_ENABLE_RAIL`, ARM/RP_OK/watchdog chain, `SAFE_*` |
| `Field_Sense` | 66 | 0.30 mm | 0.40 mm | Field side of every opto (machine-referenced) |
| `Machine_Output` | 21 | 0.50 mm | 0.35 mm (base) | Relay contact nets `OUT_*` |

Beyond the per-class base clearance, the custom rules enforce the *real* isolation
barriers: **LOGIC↔MACHINE ≥ 3.2 mm**, **LOGIC↔FIELD ≥ 2.5 mm**, and
**independent output-channel ≥ 1.5 mm**, sized conservatively for 250 VAC working
even though the measured field voltage is only ~24 VAC. (The current fab package
achieves isolation with copper spacing + all-layer keepouts only — there are **no
milled opto/relay slots**; slots are an optional future mechanical-hardening pass
that would require a re-DRC/re-export. A formal relaxation to 24 V numbers is a
later policy/DRC edit, not a topology change.)

#### 20.6.3 RP2040 co-processor pin map (KNOWN-CORRECT ANCHOR)

The RP2040 (a hand-soldered Raspberry Pi Pico, ref **A1**) owns the fast cam/ball
inputs and the rail-permission output. **The authoritative pin source is
`scripts/generate_kicad_netlist_revB.py` `block_rp2040()`, mirrored in
`firmware/rp2040/config.h`.** The GPIO column in
`docs/phase8_channel_allocation.md` is **STALE** (it assigns the fast inputs to
GP0-GP7) — **ignore it**; the as-built board uses **GP6..GP13**.

| Signal | GPIO | Pico phys. pin | Direction / sense | Function |
|---|---|---|---|---|
| `PI_UART_TX` (Pico RX) | GP1 | 2 | in (from Pi TX) | UART link to Pi |
| `PI_UART_RX` (Pico TX) | GP0 | 1 | out (to Pi RX) | UART link to Pi |
| **`RP2040_OK`** | **GP2** | 4 | out | Rail permission: **HIGH = permit motion, LOW = drop rail** |
| `SA` | GP6 | 9 | in, **active-low** | Sweep cam (270 run-through / 360 zero) |
| `SB` | GP7 | 10 | in, **active-low** | Sweep guard cam (66 guard / 186 table-spot init) |
| `SC` | GP8 | 11 | in, **active-low** | Sweep-under-table interlock window (86-243) |
| `TA1` | GP9 | 12 | in, **active-low** | Table cam (355 zero stop / 185 delay reset) |
| `TA2` | GP10 | 14 | in, **active-low** | Table cam (260 run-through / pin-latch) |
| `TB` | GP11 | 15 | in, **active-low** | Table-sweep interference interlock (105-255) |
| `DIELL_L` | GP12 | 16 | in, **active-low** | Ball detect, left beam (cushion SS trigger) |
| `DIELL_R` | GP13 | 17 | in, **active-low** | Ball detect, right beam |

Electrical sense (from `opto_input()`): every fast input is opto-isolated and
**active-low at the Pico** — machine contact closed pulls the GPIO LOW; idle is HIGH
(on-board 10 k pull-up to 3V3). `RP2040_OK`/GP2 drives an NPN in the relay-enable
AND chain; a 100 k base pull-down makes the rail **fail-safe-dead** whenever GP2 is
Hi-Z (unpowered / in reset / pre-init). Firmware: `FW_VERSION "phase8b-rp2040
v0.1.0"`, UART `115200`.

Firmware timing/backstop constants (`config.h`):

| Constant | Value | Purpose |
|---|---|---|
| `DEBOUNCE_CAM_US` | 2000 µs | Cam microswitch debounce (12 RPM machine → 2 ms ample) |
| `DEBOUNCE_DIELL_US` | 500 µs | Ball beam-break de-glitch |
| `BALL_LOCKOUT_MS` | 300 ms | One thrown ball → one ball event |
| `HB_INTERVAL_MS` | 250 ms | Heartbeat cadence to the Pi |
| `BOOT_SETTLE_MS` | 200 ms | `RP_OK` held LOW at least this long after boot before permit |
| `WDT_TIMEOUT_MS` | 250 ms | RP2040 internal watchdog: loop hang → chip reset → rail drop |
| `MAX_MOTION_MS` | 8000 ms | UART-independent cam timeout (matches `cycle_control_8270.MAX_MOTION_S = 8.0`); a guarded motor RUNNING longer latches a fault + drops `RP_OK`. BE and M are **not** guarded. |

#### 20.6.4 MCP23017 banks + on-board bit maps (KNOWN-CORRECT ANCHORS)

Three **MCP23017** expanders (**I2C** — *not* the SPI MCP23S17) handle the slow
inputs and the relay/lamp outputs, on the board's own I2C bus. Addresses and the
software bit maps are in `lane_node/controller_io.py`; the maps are kept in lockstep
with the netlist generator by a regression assert in that file's `__main__` (it
re-derives the maps from `OUTPUT_PINS`/`SLOW_INPUT_PINS` and fails on drift — this
caught the historical BS/OS, M1/M2, and strike/foul swaps).

| MCP role | I2C addr | A2A1A0 strap | Direction | Carries |
|---|---|---|---|---|
| IN-A | `0x20` | 0,0,0 | all inputs | Grippers GS1-10 + GP/OS/BS/PBZ/PBC/Foul |
| IN-B | `0x21` | 1,0,0 | all inputs | 10th-frame + manual + spare/AUX (configured, not yet read by the FSM) |
| OUT-A | `0x22` | 0,1,0 | all outputs | 7 relay-coil drives + 4 status-lamp LED drives |
| OUT-B | `0x23` | — | (outputs) | **Optional** physical pin lamps + neon; **omitted in baseline** (camera supplies pin state) |

> `(port, bit)`: port 0 = GPIOA (MCP pins 21-28 = GPA0-7), port 1 = GPIOB (MCP pins
> 1-8 = GPB0-7). Optos are **active-low at the MCP pin** (`INPUT_ACTIVE_LOW = True`):
> switch closed → pin reads 0.

**OUT-A output bit map** (`OUT_A_MAP`, chip `0x22`):

| Output | (port, bit) | Gen pin | Function | On safety rail? |
|---|---|---|---|---|
| `S` | (0, 0) | 21 | Sweep relay | yes |
| `T` | (0, 1) | 22 | Table relay | yes |
| `SP` | (0, 2) | 23 | Spot solenoid | yes |
| `BE` | (0, 3) | 24 | Back-end (future) | yes |
| `M` | (0, 4) | 25 | Master (future) | yes |
| `M2` | (0, 5) | 26 | Sweep reverse (M2 **before** M1 — per generator) | yes |
| `M1` | (0, 6) | 27 | Ball return — **DNP** | yes |
| `first_ball` | (0, 7) | 28 (`L_FIRST`) | 1st-ball lamp | no |
| `second_ball` | (1, 0) | 1 (`L_SECOND`) | 2nd-ball lamp | no |
| `strike` | (1, 1) | 2 (`L_STRIKE`) | strike lamp | no |
| `foul` | (1, 2) | 3 (`L_FOUL`) | foul lamp | no |

**IN-A slow-input bit map** (`IN_A_MAP`, chip `0x20`):

| Input | (port, bit) | Input | (port, bit) |
|---|---|---|---|
| GS1 | (0, 0) | GS6 | (0, 5) |
| GS2 | (0, 1) | GS7 | (0, 6) |
| GS3 | (0, 2) | GS8 | (0, 7) |
| GS4 | (0, 3) | GS9 | (1, 0) |
| GS5 | (0, 4) | GS10 | (1, 1) |
| GP | (1, 2) | OS | (1, 3) |
| BS | (1, 4) | PBZ | (1, 5) |
| PBC | (1, 6) | Foul | (1, 7) |

Motion relays (`MOTION_RELAYS = S, T, SP, BE, M, M1, M2`) get RUN/STOP forwarded to
the RP2040 over UART so the firmware's max-run backstop knows what is energized;
lamps are not motors and are not forwarded.

#### 20.6.5 The JLCPCB Standard-PCBA order

The board is ordered from JLCPCB as a **Standard PCBA**: JLC fabricates the bare
4-layer board *and* places all SMD parts plus the through-hole PC817 optos and G5LE
relays (wave-soldered); a short list of parts is hand-soldered after the boards
arrive (§ 20.6.6).

**Upload files** — use the three files from
`kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/`, in this order:

| Order step | File | Role |
|---|---|---|
| 1 | `01_wsl-phase8b-revB_gerbers.zip` | the PCB Gerber/drill upload |
| 2 | choose **Standard PCBA**, assembly **top side only** | — |
| 3 | `02_wsl-phase8b-revB_BOM_JLC.csv` | BOM (20 part lines) |
| 4 | `03_wsl-phase8b-revB_CPL_JLC.csv` | position/CPL (174 placed designators) |
| 5 | `04_…_part-lock-audit.csv` | use during part-match review (audit only) |

> **Do not** upload the transport zip
> (`wsl-phase8b-revB-JLC_UPLOAD_READY.zip`) as the Gerber file — unzip it and use the
> three files above. Files `05`/`06`/`07` are exclusion/hand-solder/harness audits,
> not order inputs.

**PCB settings** (set or confirm in the JLC form):

| Setting | Value |
|---|---|
| Layers | **4** |
| Dimensions | **250 mm × 225 mm** |
| Thickness | 1.6 mm |
| Material | FR-4 |
| Solder mask | green |
| Silkscreen | white |
| **Surface finish** | **ENIG** (lead-free) |
| Outer copper | 1 oz |
| Inner copper | 0.5 oz |
| Vias | standard through vias only |
| Castellated / impedance control / edge plating / panelization | no (panelize only if JLC requires it for assembly handling) |

**PCBA settings / placement contract** (the generator
`prepare_jlc_standard_pcba_revB.py` *aborts* unless these hold):

- JLC-placed refs: **174**. JLC BOM unique lines: **20**. Filtered CPL rows: **174**.
- Relay locked to **`C116963 / G5LE-14 5VDC`**; I/O expander locked to
  **`C47023 / MCP23017-E/SO`**. If either lock fails, the generator aborts.
- Hand-solder refs **excluded** from JLC placement (15 refs):
  **A1, J1-J11, J13, J14, U37.**
- Existing **DNP** refs stay excluded — the **M1** optional channel
  (J12/K7/Q7 + M1 support passives) is **not populated**.

**Locked JLC part map** (the as-built `02_…_BOM_JLC.csv`; this is the source of
truth, and it supersedes any older doc that cites different designators):

| Comment (value) | Qty | Designators | LCSC # | MFR part | Footprint |
|---|---:|---|---|---|---|
| 100nF 50V X7R 0805 | 4 | C1,C2,C3,C12 | C49678 | CC0805KRX7R9BB104 | 0805 |
| 100µF 16V SMD aluminum electrolytic (D6.3×L5.4) | 1 | C11 | C19184134 | CK1C101M-CRE54 | CP_Elec_6.3x5.4 |
| 10nF 50V X7R 0805 | 1 | C13 | C17702767 | C0805B103K500NT | 0805 |
| 10µF 16V X5R 0805 | 1 | C14 | C89827 | CC0805KKX5R7BB106 | 0805 |
| 1N4148WS switching diode | 8 | D1,D3,D5,D7,D9,D11,D15,D16 | C118873 | 1N4148WS | SOD-323 |
| SS14 Schottky | 1 | D17 | C2480 | SS14 | SMA/DO-214AC |
| **G5LE-14 5VDC SPDT relay** (wave solder) | 6 | **K1-K6** | **C116963** | **G5LE-14 5VDC** | Omron G5LE-1 |
| MMBT3904 NPN BJT | 8 | Q1-Q6,Q15,Q16 | C909754 | MMBT3904 | SOT-23 |
| 2N7002 N-ch MOSFET | 4 | Q8,Q9,Q10,Q11 | C916396 | 2N7002 | SOT-23 |
| AO3400A N-ch logic MOSFET | 2 | Q12,Q13 | C20917 | AO3400A | SOT-23 |
| AO3401A P-ch MOSFET | 1 | Q14 | C347476 | AO3401A | SOT-23 |
| 4.7k 1% 0805 | 2 | R1,R2 | C17673 | 0805W8F4701T5E | 0805 |
| 2.2k 1% 0805 | 32 | R3..R65 (odd) | C17520 | 0805W8F2201T5E | 0805 |
| 10k 1% 0805 | 37 | R4..R66 (even) + R101-R109 | C17414 | 0805W8F1002T5E | 0805 |
| 1k 1% 0805 | 12 | R67..R104 (subset) | C17513 | 0805W8F1001T5E | 0805 |
| 100k 1% 0805 | 14 | R68..R110 (subset) | C149504 | 0805W8F1003T5E | 0805 |
| 330R 1% 0805 | 4 | R90,R93,R96,R99 | C17630 | 0805W8F3300T5E | 0805 |
| **MCP23017 I2C I/O expander** | 3 | **U1,U2,U3** | **C47023** | **MCP23017-E/SO** | SOIC-28W |
| **PC817B optocoupler** (DIP-4, wave solder) | 32 | **U4-U35** | **C5692981** | **PC817B** | DIP-4 W7.62mm |
| **NE555 bipolar timer** | 1 | **U36** | **C7593** | **NE555DR** | SOIC-8 |

> The `00_README_UPLOAD.txt` inside the upload folder restates the four critical
> part-match checks (K1-K6 relay coil = 5 VDC; the three MCP23017s = I2C, not
> MCP23S17; U4-U35 = PC817B DIP-4; U36 = NE555DR). The README's designator
> *examples* for the MCP/NE555 (U33-U35/U36) reflect an earlier numbering; **the
> authoritative current designators are in the BOM CSV above (U1-U3 / U36)** — trust
> the CSV.

**Mandatory preview checks before paying** (from the order checklist):

- Relay row is `C116963 / G5LE-14 5VDC` — **reject any 9 V / 12 V / 24 V coil
  substitution.** The coil is **5 VDC**, not 12/24 V.
- I/O expander row is `C47023 / MCP23017-E/SO` — **reject MCP23S17** (SPI).
- PC817 row is `C5692981 / PC817B`, DIP-4 / through-hole / wave solder.
- NE555 row is `C7593 / NE555DR` (bipolar 555 — don't silently swap a CMOS/TLC555,
  the watchdog timing assumes bipolar behavior).
- C11 electrolytic polarity matches the board; all PC817 and all G5LE orientations
  match the board preview.
- **No** A1, J1-J11, J13, J14, U37 refs appear in the JLC placement list; J12, K7,
  Q7, and the M1 support passives remain unpopulated.
- Board outline is 250 × 225 mm with four mounting holes visible.

**If JLC rejects a through-hole part** (no redesign needed): move U4-U35 (PC817)
and/or K1-K6 (G5LE) from JLC placement to the hand-solder BOM and assemble them by
hand; the PCB is unchanged. If C11's part/polarity is questionable, pick another
100 µF/16 V SMD electrolytic matching the `6.3×5.4` footprint and re-run the BOM
generator after updating the part lock.

#### 20.6.6 Hand-soldered parts (installed after the assembled boards arrive)

These refs stay on the board but are omitted from the JLC placement BOM/CPL and are
installed at the bench. Procurement lists:
`assembly/wsl-phase8b-revB-hand-solder-bom.csv` and
`…-harness-mating-parts.csv`.

| Ref(s) | Part | Notes |
|---|---|---|
| **A1** | **Raspberry Pi Pico** (RP2040 module), SC0915 | JLC may not place the castellated module; assume it arrives **unprogrammed** unless programming is explicitly quoted. |
| **J1** | Pi IDC/header (2×10) | Candidate pending final body/keying/pin-1 verification against the board + cable plan. |
| **J2-J11, J13, J14** | **Phoenix / terminal connectors** (MKDS 5.08 mm + MCV 3.5 mm headers) | Most board-side Phoenix parts are locked; verify wire-entry direction against the board render before ordering. |
| **U37** | **TRACO TMA-0505S** isolated DC/DC (5 V→5 V) | Supplies the isolated field-wetting rail. Treat as exact or pinout-audited substitute only — verify isolation rating, output current, SIP pinout, body clearance. |

`J12` is already DNP and is **not** part of the hand-solder set. The 3.5 mm MCV
headers need matching off-board mating plugs (for J3, J4, J5, J13, J14); those plugs
are not PCB placements and are listed in
`assembly/wsl-phase8b-revB-offboard-hardware.csv` /
`…-harness-mating-parts.csv`. After installing the hand-solder parts, do a
continuity/visual inspection **before applying power**.

#### 20.6.7 The DRC + topology audit gate (`audit_revB_board.py`)

The fab export is **gated**: `export_fab_revB.py` will not produce a package unless
both of these pass, and it re-runs both *inside* the export so the gate cannot be
bypassed:

1. **KiCad DRC** (`kicad-cli pcb drc --severity-all`) must report exactly:
   `Found 0 DRC violations`, `Found 0 unconnected pads`, `Found 0 Footprint errors`.
   A missing line aborts the export.
2. **`scripts/audit_revB_board.py`** must print `AUDIT RESULT: ALL PASS`.

**Why a separate audit when DRC already passed:** KiCad DRC proves geometry but
**not** that the net classes are actually assigned, that the safety rail truly
reaches every coil, or that no machine output ever touches the Pico. The audit
checks exactly the things DRC cannot — it verifies against the *live board file*,
not the DRC report (the Claude↔Codex review loop caught a "false-green" route where
the routed `.kicad_pro` had lost its netclass assignments, making the `.dru`
`hasNetclass()` rules inert and "0 violations" meaningless). The audit asserts:

| Audit check | What it proves |
|---|---|
| 5 net classes assigned with exact counts `{Logic_Signal:80, Logic_Power:4, Safety_Rail:13, Field_Sense:66, Machine_Output:21}` | The `.dru` isolation rules are *not* vacuous |
| No named net fell to `Default`; zero anonymous `N$` nets | Every net is policy-classified |
| `RELAY_ENABLE_RAIL` reaches **7** relay coils (`K*`) **+** a pass-FET (`Q*`) | The safety rail enables every motion relay incl. M1 DNP |
| **No `OUT_*` net touches the Pico** | Machine output can't reach the logic MCU |
| `GND` and `FIELD_GND` both present **and distinct** | Field isolation barrier intact |
| `SAFE_STOP_RETURN` + `SAFE_TBSC_RETURN` + `RAIL_GATE` present | Interlock loops are first-class rail conditions |
| Netted copper zones filled; ≥ 2 isolation keepout rule-areas present | Power planes poured + barrier keepouts exist |
| ≥ 8 DNP footprints | The M1 optional channel is still DNP |

Run the audit standalone with KiCad's Python:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb
```

#### 20.6.8 Regenerating the whole fab package

After **any** board edit, regenerate the package (this re-runs the DRC + audit gate,
re-exports gerbers/drill/CPL/PDF/IPC-D-356/stats, regenerates all BOM/CPL CSV
variants, rebuilds the JLC upload-ready folder, and writes a `manifest.json` with
SHA-256s):

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\export_fab_revB.py
```

Output lands in `kicad/fab_revB_routed_manual/`. The package gate also checks that
at least one Excellon `.drl` and ≥ 11 Gerber layer files were produced, that the
JLC upload pair exists, and (again) DRC `0/0/0` + audit `ALL PASS`. The package is
**fab-ready, not cutover-ready** — the export README explicitly carries the caveat
that RP2040 v1.1 cam-stop-overrun work and on-hardware bench bring-up remain before
live-machine use.

---

### 20.7 Per-pair field deployment (infrastructure)

For physically installing a node at a lane pair, the procurement BOM + install
procedure is `docs/phase_8a_infrastructure_plan.md`. The shape:

- **Network:** one managed **PoE+** switch (planned baseline: TP-Link TL-SG2428P,
  24×PoE+) in the existing closet, one Cat6 run per pair, a single subnet/VLAN. The
  Pi nodes are first-class LAN citizens (they ping WSL-SRV directly). The plan's IP
  block and the `192.168.86.x` topology diagram are **pre-eero and now stale** —
  re-read § 20.4 for the live subnet (`192.168.4.0/22`) before assigning addresses.
- **Power:** **PoE+** to the Pi via a PoE+ HAT (official RPi PoE+ HAT recommended);
  the HAT's 5 V feeds the Pi and the board's logic rail. PoE+ wins on TCO because
  there is no AC outlet at the equipment area today.
- **Enclosure:** a DIN-rail enclosure (Hammond 1597BSGY baseline) with a window over
  the indicator-LED zone (watchdog "WD", power "PWR", Pi status), and cable glands
  for Cat6 + the machine wire bundle.
- **Sequence:** pre-install survey → infrastructure install (cabling + switch +
  enclosure, **no** machine wiring) → 24 h soak → cutover visit. The cutover plan
  (`docs/phase_8a_cutover_plan.md`) depends on this infrastructure being in place
  first.

> Per-pair material cost runs ~$285; shared one-time infrastructure ~$785; full
> 16-pair rollout ~$5,050 — roughly $11k cheaper than refurbishing the EOL
> QubicaAMF hardware, and with lifetime parts independence.

---

### 20.8 Operations quick reference

| I need to… | Do this |
|---|---|
| Find the current server IP | It's a DHCP lease on WSL-SRV (MAC `10-B6-76-51-EC-5D`). **Confirm on the eero; reservation is still TODO.** As of 2026-06-03: `192.168.4.103`. |
| Bring a dark node back | `journalctl -u lane-node -n 50`; verify `systemctl is-enabled lane-node` says **enabled**; check `WSL_LANE_SERVER_URL` in the drop-in points at the live IP. |
| Re-point a node after a network change | `sudo systemctl edit lane-node` → set `WSL_LANE_SERVER_URL=ws://<new-IP>:8765` → `daemon-reload` → `restart`. |
| Stop auto-scoring now | `systemctl edit lane-node` → `WSL_LANE_SCORING_MODE=manual` → `restart`. No machine impact. |
| Check the server is up | `curl http://<WSL-SRV>:8766/api/health`. |
| Open the scoring display | `http://<WSL-SRV>:8766/display?lane=21` (and `?lane=22`). |
| Regenerate the fab package | `& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\export_fab_revB.py` |
| Re-order the board | Upload the three files in `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/` to JLC; run the § 20.6.5 preview checklist before paying. |
| Verify the on-board pin maps before trusting hardware | Run `controller_io.py` as a script (KiCad python not needed) — its `__main__` asserts `OUT_A_MAP`/`IN_A_MAP` match the netlist generator and fails on drift. |


## 21. Bring-up, Bench Validation & Cutover

This section covers how a fabricated, assembled Rev-B controller board goes from "boxed PCB" to "running a pinsetter on lanes 21/22 in production." It has three parts, in the order they happen:

1. **Off-machine bench bring-up** (§21.2) — power up and prove out one board on a workbench, nowhere near a machine. This is the gate that every board must pass before it is ever wired to a pinsetter.
2. **Track-B controller cutover** (§21.3) — replace the OEM 82-70 control brain at one lane pair with the Rev-B Pi controller. This is a controls swap on a machine that moves and bites; it is the highest-risk operation in the whole project.
3. **Track-A scoring go-live** (§21.4) — bring up camera-based auto-scoring. Separate from the controller swap, read-only with respect to the machine, and fully reversible.

> **Read first if you are new here.** A pinsetter is dangerous. The sweep, table, and pit mechanisms can cycle and crush a hand. "Powered but idle" is **not** safe — a desk action, a customer, or a stray cam edge can start a cycle. Every live procedure in this section is built around lockout/tagout and a non-bypassable hardware safety rail. Do not improvise. If anything looks wrong, the master breaker goes **OFF first, questions second.**

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

The Rev-B board never sources machine power. It only **opens and closes isolated dry relay contacts** that sit in series with the machine's *existing* control circuits. The heavy S/T contactors stay on the machine and keep switching the 115 VAC motors and their OEM braking behavior — the board only switches their coil circuits (all measured at ~24 VAC; see §14 and the fieldsheet). The board is therefore never the only safety device: the upstream **Stop / C.I.S. / master-breaker chain stays live and upstream** (OEM service manual p11 confirms Stop and C.I.S. are in parallel and both cut the rear-panel master breaker), and the master breaker remains the final physical stop.

The board's own permission to move anything is the **relay-enable rail** (`RELAY_ENABLE_RAIL`, test point **TP16**). It feeds the coil side of all motion relays. It is a hardware **AND** of six conditions — if any one is false, the rail collapses and every motion relay drops. **The Pi cannot bypass it in software.** Full circuit theory is in §10; here is the operating summary you will test against in §21.2 and §21.3:

| # | condition | source on the board | fail-safe default | how it drops the rail |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 monostable (U36), Pi kicks `WDOG_KICK` (Pi GPIO 12) at < ~10 s | false (no kick → drop) | NE555 output gate (Q13 AO3400A) opens the rail's pull-down chain |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO, asserted only after operator-safe state (First-Ball-Zero) | false | NPN AND transistor Q15 (MMBT3904) in the gate chain |
| 3 | **RP2040 OK** | RP2040 (A1) `RP2040_OK` = GP2, heartbeat/permission | false (Hi-Z → 100k pulldown) | NPN AND transistor Q16 (MMBT3904) in the gate chain |
| 4 | **Cam-stop OK** | RP2040 immediate cam-edge drop path (drives `RP2040_OK` low) | false on reset/fault | same path as #3 — RP2040 pulls GP2 low |
| 5 | **TB/SC interlock OK** | external hardware NC loop on J14 pins 1-2 | open/false | breaks the series rail feed before the pass-FET |
| 6 | **Stop/CIS/master OK** | external machine safety chain on J14 pins 3-4 | open/false | breaks the series rail feed before the pass-FET |

The rail itself is gated by a P-channel pass-FET **Q14 (AO3401A, "rail pass")**, fed through the two external NC loops on **J14 (`J_SAFETY`)** in series: `VCC_5V → J14.1 → [TB/SC loop] → J14.2/J14.3 → [Stop/CIS loop] → J14.4 → Q14 source → Q14 drain = RELAY_ENABLE_RAIL`. The pass-FET gate is pulled up to its own source (R, 100k) and pulled toward conduction only when the watchdog/arm/RP2040 AND-chain (Q13/Q15/Q16) allows it.

> **The welded-contact limit (memorize this).** The rail de-energizes relay *coils*. It **cannot open a contact that has welded shut.** Relay contact rating, arc suppression, and the upstream master breaker are what protect against a welded contact. This is why §21.2 includes a dummy-load test on every relay and why the master breaker is never the thing you skip.

Conditions 1, 2, 3/4 are *on-board* permissions (you test them by manipulating the Pi/RP2040). Conditions 5 and 6 are *external loops* you wire at the lane and test by physically opening them. All six must independently drop motion — that is the heart of go-gate **G3** (§21.3).

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
| 3. **RP2040 boot + heartbeat** | Flash the firmware (`firmware/rp2040/`, FW `phase8b-rp2040 v0.1.0`) if not already; power up. | Over UART (J1 pins 5/6, 115200-8N1) you see a `boot` line then `hb` (heartbeat) lines every 250 ms. After the 200 ms boot-settle, `RP2040_OK` (GP2, TP14) goes HIGH (`rp_ok:1`). | Check the Pico solder, UART wiring (Pi TX→GP1, Pico GP0→Pi RX), `BOOT_SETTLE_MS`. |
| 4. **Watchdog drop** | With the rail armed on the bench-safe path, **stop kicking** `WDOG_KICK` (Pi GPIO 12). | After the NE555 timeout (~10 s — the Pi normally kicks well inside this), the rail (TP16) drops. Observe at TP11 (`NE555_OUT`), TP12 (`WDOG_OK_PULLDOWN`). | Verify the NE555 timing network (R_WDOG_TIMING 100k, C_WDOG_TIMING 100µF/16V = C11), the trig pull-up (R_WDOG_TRIG_PULLUP 10k — the "Rev-A trigger pull-up fix"), Q13. |
| 5. **Arm drop** | De-assert the Pi `ARM_PERMIT` GPIO (J1 pin 8). | Rail (TP16) drops. TP13 (`ARM_PERMIT`) reads low. | Check Q15 (AND ARM) and its base network (Rb 10k / Rpd 100k). |
| 6. **Interlock drop** | Open the J14 (`J_SAFETY`) loops one at a time — first the TB/SC loop (pins 1-2), then the Stop/CIS loop (pins 3-4). | Rail (TP16) drops when **either** loop opens. TP15 (`SAFE_STOP_RETURN`) goes open/low. | Confirm the two NC loops are jumpered closed for the test; check Q14 pass-FET. |
| 7. **Each relay with a dummy load** | Re-establish all rail conditions. Command each motion relay **(S, T, SP, BE, M, M2)** in turn through OUT-A (U3). Put a **dummy load** (a lamp or resistor sized to the expected ~24 VAC coil-circuit current) across the relay's J6-J11 contact pair. | Each relay clicks, its COM-NO contact closes the dummy load, and the load drops the instant you drop the rail. Probe coil-drive, COM, NO per the test-pad rule (§9, spec §3.2). **M1 (K7/J12) is DNP — not tested.** | Check the relay driver (Q1-Q6), `RELAY_ENABLE_RAIL` reaching the coil, the flyback diode. |
| 8. **Input front-ends** | Exercise each opto input. For **fast** inputs (SA/SB/SC/TA1/TA2/TB/DIELL-L/DIELL-R) wet the J3 (`J_FAST_IN`) field pin to `FIELD_GND`; for **slow** inputs (GS1-10, GP/OS/BS/PBZ/PBC/Foul on J4, and 10th/manual/AUX on J5) do the same. | The corresponding RP2040 fast-input edge (cam/ball event over UART) or MCP23017 bit flips. Optos are **active-low** at the logic pin: a closed field contact pulls the input LOW (§8, §12). | Check the PC817 (U4-U35), the input resistor (Rin 2k2), the logic pull-up (Rpu 10k to 3V3), `FIELD_WET_V`. |
| 9. **Cam-stop rail drop** | Drive a cam-stop condition on the RP2040 and confirm it pulls the rail. | `RP2040_OK` (GP2/TP14) goes low → rail (TP16) drops. **See the firmware caveat below.** | This is condition #4 — it shares the GP2 path with #3. |
| 10. **(only then) machine-harness test** | Everything above passed. The board is cleared to be wired to a machine — which is the cutover (§21.3), **not** part of bench bring-up. | — | — |

**Pass = all of steps 1-9 green, logged.** Only then does the board become a candidate for the controller cutover (this is gate **G1**). Build the spare unit #2 the same way.

> ⚠️ **Firmware caveat for step 9 (read carefully).** The shipped firmware is **v0.1.0**. It provides the RP2040's UART-independent **motion max-run backstop** (`MAX_MOTION_MS` = 8000 ms — a guarded motor marked RUNNING by the Pi for longer than 8 s latches a fault and drops `RP2040_OK`). It does **NOT** yet implement **per-cam-edge cam-stop overrun enforcement** — that is the explicitly-deferred **v1.1** hook (see `main.c`, the `// v1.1` marker in `supervise()`). Per-cam-edge enforcement needs the per-cam edge→angle polarity, which is a deferred cutover field item (§21.3, runbook §3.2). So at the bench you can prove step 9 in the **max-run-backstop** sense (mark a motor running, let it exceed 8 s → rail drops) and prove the GP2→rail path directly (reset/halt the RP2040 → rail drops, condition #3/#4 share that path). The true **per-cam-edge** drop is bench-provable only after you capture cam polarity and flash v1.1 — which is why the cutover sequences cam-polarity capture *before* the live cam-stop test.

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
| TP15 | `SAFE_STOP_RETURN` | external safety-loop return (after both J14 loops) |
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

A critical consequence of removing the Omega-Tek board: bench work found the OEM machine uses **logic cam-stops** (in the triac board), **not** hardwired cam-in-series stops. So removing the OEM brain removes the existing cam-stop, and the **RP2040 hardware cam-stop replaces it.** This is exactly why the RP2040 cam-stop must be proven before cutover and why the Stage-6 cam-stop drop test is a hard gate.

#### 21.3.2 Lockout/tagout — the operating discipline

There are only **two modes** during the whole cutover:

- **(A) LOCKED OUT** — master breaker **OFF**, breaker tagged, **verified 0 V** on the coil circuits before hands go in. The 24 VAC coil rail can hold charge — wait ~30 s and verify. **All capture work, all harness landing, all hand-actuation happens here.** This is *most* of the cutover.
- **(B) DELIBERATE LIVE** — powered, only for the explicitly-marked staged-motion steps. The machine moves **only on a command you and your helper both expect** — never because of a customer.

Non-negotiables: lane formally **out of service, off-hours only**; **two people** for every live step (one at the controls/meter, one at the master breaker/e-stop); **body stays OUT of the sweep/table/pit travel path whenever powered** — if a mechanism must be rotated, rotate it **by hand, locked out**; **lift, don't cut** every machine wire (this is what makes rollback possible); if anything feels wrong, **master breaker OFF first, ask second.**

#### 21.3.3 The deferred field-capture items (the reason the runbook exists)

A set of facts were **deliberately deferred** from the design phase to cutover day, because they are far easier to capture with the machine apart and a **live input feed** running, and because **none of them gate the board** — the board uses function-named connectors and a per-chassis adapter harness resolves them (§14). The at-machine fieldsheet (already complete) locked everything the *board design* needed (working voltage = 24 VAC, lamp supply = 15 VDC, cam form = dry contact NC, grippers = chassis-return/gripped-closed, Stop+CIS parallel, TB/SC parallel into 24 V). What remains for cutover day are the **per-pin labels and exact landings.**

> **Live feed = your meter.** With the harness landed on the inputs (J3/J4/J5) but the **rail still disabled** (no motion possible), the Pi reads every input over the daemon (`journalctl -u lane-node -f` shows input-bank reads). So most capture is "actuate the thing by hand, locked out, and watch which channel flips in the log."

The deferred items (full method per item in runbook §3, worksheets in runbook Appendix B):

| item | runbook ref | what you capture | how |
|---|---|---|---|
| **Per-gripper GS# → C2A cavity** | §3.1 | which physical gripper maps to GS1…GS10 (the *bank* and polarity are already locked: gripped = CLOSED to **chassis** ground) | lift one pin / actuate one gripper at a time, watch which `GS` channel deasserts in the live feed; set the result in `controller_io.py` GS map (software only) |
| **Per-cam SA/SB/SC/TA1/TA2/TB → C2A cavity + trip angle** | §3.2 | which cam fires which fast input at which angle | locked out, hand-rotate the sweep/table, watch which fast input fires at which cam angle. **This also feeds firmware v1.1 cam-stop polarity.** |
| **C1/C2A output cavity confirm** | §3.3 | confirm the measured output cavities on *this* in-place machine before landing J6-J11 | land-check against the spare-cabinet measurements (table below) |
| **TB/SC interlock → exact terminals (J14)** | §3.4 | the exact NC-loop terminals for the hardware interlock | locked out, find the TB+SC cam switches, confirm the NC loop, land J14 pins 1-2 into it. **First-class rail condition — hardware, not firmware.** |
| **Stop/CIS/master chain** | §3.5 | confirm continuity, **preserve, do not replace**; tie J14 pins 3-4 sense into it | locked-out continuity: Stop in RUN vs STOP drops the motor-relay coil rail |
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
| 5. Land the adapter harness | A | one connector group at a time, double-checking each against the runbook §4 map, lift-and-land, torque, tug-test, photograph: J6/J7→C1 + J8/J9/J10/J11→C2A coil circuits · J3→cams+DIELL · J4/J5→grippers/switches · J14→TB/SC + Stop/CIS · J13→mask LEDs · J1→Pi · J2→supplies. Final visual pass: every board terminal vs the map. **Catch swaps now.** | — |
| 6. **Logic-only bring-up + SAFETY-DROP TESTS** | A (rail DISABLED, no motion possible) | breaker still OFF, power **logic only (5 V)**. Pi boots, I²C enumerates all 3 MCP23017, RP2040 boots + heartbeats, watchdog healthy, **all relays default OPEN, rail DISABLED**. Read inputs (lift a pin → GS flips; rotate a cam → fast input; break DIELL → ball; trip foul). Then prove **each** rail condition independently drops the rail (see below). | **G3** |
| 7. **First commanded motion** | **B — DELIBERATE LIVE** | two people, body clear, hand on the breaker. Breaker ON, arm. Command **SP alone** (spot fires, no sweep/table). Command **one sweep (S)** → watch it stop on the SA cam (RP2040 cam-stop). Command **one table (T)** → stop on TA. Command **one full reset cycle** → completes and stops cleanly, no overrun. | **G4** |
| 8. Ball cycle + scoring | B | roll a ball down each lane: DIELL fires → FSM cycles the pinsetter (cam-timed) → camera scores (Track A) → display updates. Confirm detected standing pins match the deck across a few leave types, both lanes | **G5** |
| 9. Soak handoff | — | brief night staff ("21+22 are on the new Pi controller… if anything looks wrong, leave the lane closed, photograph it, message Dylan — do not try to fix it"); tape a contact note inside the cabinet; leave the OEM brain shelved + all wire labels on for the first soak week | — |

**Stage 6 safety-drop tests (the heart of the cutover, gate G3).** With the rail's enable on the bench-safe armed path, prove **each** condition independently drops the rail:

1. stop the watchdog kick → rail drops
2. de-assert arm → rail drops
3. reset/halt the RP2040 → rail drops
4. trigger a cam-stop edge → rail drops — **⚠️ requires RP2040 firmware v1.1 (cam-stop overrun).** v0.1.0 provides only the motion max-run backstop, **not** per-cam-edge enforcement; per-cam enforcement depends on the §3.2 per-cam edge→angle polarity. **So capture cam polarity FIRST (Stage 2 / §3.2), flash v1.1, THEN run this sub-test.** This sub-test is **BLOCKED until then**; the other five rail-drop conditions are testable with v0.1.0.
5. open the TB/SC loop (J14 pins 1-2) → rail drops
6. open the Stop/CIS chain (J14 pins 3-4) → rail drops

**Every one must drop motion permission. Any failure → ABORT + rollback.** Do not proceed to live motion with a safety condition that doesn't drop the rail.

#### 21.3.5 Go / No-Go gates

| gate | when | pass condition | fail action |
|---|---|---|---|
| **G1** | before scheduling | unit bench-validated (§21.2, spec §12 step 9, all steps) · firmware proven · Track-A scoring soaked clean · spare on hand · OEM brain photographed | don't schedule |
| **G2** | after Stage 2 | all §3 field items captured; harness map complete; no surprises vs measured cavities | resolve or defer non-blocking; **abort if a safety landing (TB/SC) is unclear** |
| **G3** | Stage 6 | **EVERY** rail condition (watchdog, arm, RP2040, cam-stop, TB/SC, Stop/CIS) independently drops motion permission | **ABORT → rollback** |
| **G4** | Stage 7 | commanded S/T/SP each stop on cams; full reset completes + stops; no runaway | **breaker OFF → rollback** |
| **G5** | Stage 8 | ball cycle + correct score across a few balls/leaves, both lanes | flip scoring to manual (§21.4 Step 7); controller stays if G3/G4 passed |

**Rule:** any failure at or before **G4 = rollback to the OEM brain.** Do **not** debug machine motion live.

#### 21.3.6 Rollback (reconnect the OEM brain)

Trigger: any G3/G4 failure, or a Stage-7/8 fault that isn't a trivial single-wire fix. Budget ~20-40 min (longer than a scoring rollback because you re-plug the brain — practice it in the Stage-5 dry run). Summary (full steps in runbook §8):

1. **Master breaker OFF, lockout, verify 0 V.**
2. **Lift the adapter harness** from C1/C2A/TB/SC/Stop-CIS (use the tape labels; lift, don't cut).
3. **Re-plug the OEM Omega-Tek board + triac driver bank + connectors** (preserved from Stage 4).
4. Mask LEDs (J13) can stay unpowered (harmless); the OEM 15 VDC mask wiring was left intact, so OEM lamps work on re-plug.
5. **Master breaker ON.** OEM controller runs the machine. **Bowl a frame on each lane** to confirm normal operation.
6. Leave the Rev-B enclosure powered down + in place (harmless); take the unit home to debug.
7. **Document the failure** (which gate/stage, observed behavior, suspected cause) in a `project_phase8b_cutover_attempt_N.md` memory.

#### 21.3.7 First-week soak and per-chassis rollout

Daily for 7-10 days (runbook §9): check `/api/health` on the server (node connected, no excessive disconnects); WSL-SRV log clean (no `lane_node_server.py` errors, no protocol mismatch); **walk 21+22 during open hours** watching real cycles (cam-stops crisp, no overrun, reset completes, scoring agrees); **cam-stop / watchdog timeouts in the journal must be ZERO** — any timeout is investigated before it recurs; touch the Pi case + boards days 1-3 (warm, not hot). After 7-10 clean days → a cleanup visit (tidy wire routing; decide whether the OEM brain is permanently retired or stays shelved as a spare), then the next chassis.

**Per-chassis caveat:** the board is fleet-common; the **harness and input populations are per-chassis-type.** Before cutting over **11/12 (Active-98 MP)**, run a short field pass on that pair for the chassis-specific items (working voltage, input forms, the C-series harness map — output cavities, cam→cavity, gripper return reference, TB/SC terminals). Do **not** assume 21/22's cavities carry over — the Omega-Tek retrofit already diverged from OEM on the M2/S cavities and on the gripper return (chassis vs TAC-GND). Clone the *board*; re-capture the *harness*. See **§14**.

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
3. **RP2040 firmware + daemon bench bring-up** (firmware v0.1.0; v1.1 cam-stop overrun comes after cam polarity is captured at cutover).
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


## 22. Troubleshooting, Maintenance & Spares

> **Read §22.0 (safe handling) before touching anything.** This system commands AC
> motors that move heavy mechanism near people. Almost every fault below can be
> diagnosed at the bench or from a log; the few that require reaching into the
> machine require lockout first. When in doubt, the safe state is **manual desk
> scoring + the original controller still cycling the pinsetter** — Track A is
> read-only and Track B is not yet cleared for live machines, so you can always
> fall back without any machine risk.

This section is the field-service guide: **symptom → likely cause → fix**, plus
the maintenance routine, the spares list, and the safe-handling rules. It assumes
the architecture from the earlier sections. Cross-references point to:

- **§2, System Architecture & Signal Chain** — the end-to-end picture.
- **§5, Rev-B Controller Board: Overview, Domains & Isolation** and **§6, Rev-B Power Architecture** — board layout, the three electrical domains, power rails.
- **§7, Rev-B Logic: RP2040 Co-processor + MCP23017 Expanders + I2C** and **§8, Rev-B Field Inputs: PC817 Opto-isolators** — the logic + input front-ends.
- **§9, Rev-B Machine Outputs: G5LE Relays** — the relay output stage.
- **§10, Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail** — the six rail conditions and their test pads (the single most important section for "relays won't energize").
- **§11, Rev-B Connector Pinouts (J1–J14)** and **§12, Rev-B Channel Maps** — connector pinouts and the GPIO/MCP bit maps.
- **§14, Machine Interface: C1/C2A Connectors & the Adapter Harness** — machine-side wiring.

Every fact here is grounded in the live files: `firmware/rp2040/config.h` +
`firmware/rp2040/README.md` (RP2040 pins/timing/protocol), `lane_node/controller_daemon.py`
+ `lane_node/controller_io.py` + `lane_node/rp2040_link.py` + `lane_node/cycle_control_8270.py`
(the Pi-side control software), `docs/phase8b_pcb_revB_spec.md` §4 (the safety-rail
contract), `docs/phase8_trackA_golive_runbook.md` (scoring go-live + failure
cheat-sheet), and the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`).

---

### 22.0 Safe handling — read before every job

These are non-negotiable. They come straight from the design contract
(`docs/phase8b_pcb_revB_spec.md` "Non-negotiable safety rule", §4.5) and the
firmware safety model.

1. **The controller board is never the only safety device.** The machine's
   upstream **Stop switch + C.I.S. (cover interlock) → master circuit breaker**
   chain, the **TB/SC collision interlock**, and the motors' **regenerative
   braking** all stay in hardware, independent of any software. Do not defeat,
   jumper-out, or "temporarily bypass" any of them.

2. **Lockout/tagout before touching the machine mechanism or its wiring.** The
   relay-enable rail removes *coil drive*; it **cannot open a relay contact that
   has welded closed** (§10.6, spec §4.5). The only guaranteed kill is the
   **rear-panel master circuit breaker** (cut by the Stop/C.I.S. chain). Cut and
   lock the master breaker before reaching into the pinsetter. Track-B bench and
   cutover work is explicitly **"on a LOCKED-OUT / off machine only"**
   (`firmware/rp2040/README.md` §"Bench bring-up"; spec §12.9).

3. **GPIO is 3.3 V only.** The RP2040 and the MCP23017s run at **3.3 V** (the
   MCP23017s are on 3.3 V specifically for Pi-safe I²C — spec §6.1, §8.1). **Never
   wire a machine voltage (24 VAC, 15 VDC, etc.) to a Pi/RP2040/MCP pin.** Every
   machine input must cross a **PC817B opto** first (§8); every machine output
   crosses a **G5LE relay contact** (§9). The opto logic sides and MCP inputs are
   already 3.3 V and Pi-safe by design — keep them that way. If you add a test
   front-end, use opto isolation or a contact-to-a-reference scheme, never a
   direct tap.

4. **Logic ground (GND) and field ground (FIELD_GND) are intentionally
   separate** and share **zero nodes** (the isolation barrier — §5, §6). Do not
   bond them with a probe clip, a scope ground, or a "temporary" jumper. The
   isolated field-wetting supply (TRACO TMA-0505S, ref **U37**) exists precisely
   to keep a machine-side fault from backfeeding the Pi.

5. **Bring up power before signals, and bring up the rail last.** The documented
   bench order (§10.8, spec §12.9, firmware README) is: power rails → I²C
   enumerate → RP2040 boot + heartbeat → **watchdog drop** → **arm drop** →
   **interlock drop** → each relay with a *dummy load* → input front-ends →
   cam-stop/motion-timeout drop → **only then** the machine harness.

6. **The board fails open by construction.** On loss of logic power, watchdog
   kick, RP2040 health, arm permission, or the hardware interlock, motion goes
   dead (spec §4, §10.7). If you are unsure of a board's state, the *correct*
   default is motion-dead — so a "dead" rail during diagnosis is the safe
   condition, not necessarily a fault.

---

### 22.1 Fast triage — which subsystem is failing?

Decide which of the three independent subsystems is misbehaving before you dig in.
They fail independently and have different fixes:

| You observe… | Subsystem | Go to |
|---|---|---|
| A lane stops scoring, or scores wrong, but the pinsetter still cycles normally | **Track A — camera scoring** (read-only; never affects the machine) | §22.2 |
| The lane "went dark" after a power blip / reboot — no scoring node at all | **Pi service / provisioning** | §22.3 |
| (Track B, bench/cutover) relays won't energize / the rail is dead | **Safety rail** (one of six conditions) | §22.4 |
| (Track B) a motor runs and then the whole board faults; relays drop | **Motion-timeout / cam-stop** | §22.5 |
| (Track B) cam/ball events missing, RP2040 reported unhealthy | **RP2040 link / UART** | §22.6 |

> **Track A vs Track B blast radius.** A Track-A (scoring) fault can never move the
> machine — the existing controller is still cycling the pinsetter and the code
> auto-falls-back to manual desk scoring (`docs/phase8_trackA_golive_runbook.md`,
> "Safety/blast-radius"; `lane_node/lane_node.py` `_init_camera()` /
> `_settle_capture_emit()`). Track-B faults are about *machine control* and are why
> the layered safety architecture exists.

---

### 22.2 Track A — camera scoring faults (read-only, safe)

Track A taps the QubicaAMF **T-Camera** composite video through the **VIXLW USB
dongle** into the Pi, and detects standing pins by **difference-from-empty**
(§2, §18/Track A). It is read-only with respect to the machine and auto-falls back
to manual on any failure. The authoritative procedure for all of this is
`docs/phase8_trackA_golive_runbook.md`; this is the service-desk condensation of
its failure cheat-sheet plus the exact code paths.

#### 22.2.1 "detector NOT ready" / lane silently falls back to manual

**Symptom (in `journalctl -u lane-node`):**
```
Camera mode but detector NOT ready (no empty ref / cv2).
Balls will fall back to manual desk scoring until fixed.
```
(emitted by `lane_node/lane_node.py` `_init_camera()` when `PairCamera.ready` is
false). You will also see `_settle_capture_emit()` log `camera yielded no mask ->
awaiting_manual (desk score)` per ball.

| Likely cause | Fix |
|---|---|
| **`empty_ref.png` missing or unreadable.** The detector compares each ball's frame to a stored cleared-deck reference; with none, it cannot detect. The file is gitignored — **each Pi captures its own** (it is *not* pulled by `git pull`). | Clear **both** decks (cycle 21 and 22 so all pins are swept), then on the Pi: `cd /home/pi/wsl-lane-nodes` → `.venv/bin/python3 lane_node/camera.py --capture-empty` (add `--device 1` if the dongle is `/dev/video1`). Saves `lane_node/empty_ref.png` (720×576). Verify non-zero size; ideally scp it off and eyeball that it really is an empty deck under normal lighting. Restart: `sudo systemctl restart lane-node`. Confirm the log now shows `Camera ready for lanes [21, 22] (settle=2.5s).` |
| **OpenCV/PyAV import failed (`cv2`).** `PairCamera` needs a capture backend. | `.venv/bin/python3 -c "import numpy, PIL, av; print('deps ok')"` — if `av` fails, `.venv/bin/pip install av` (or `pip install opencv-python`; either backend works). |

> **This is not dangerous.** "Detector not ready" means the lane simply scores
> manually at the desk via `POST /api/lane/N/score` — the pinsetter still runs.

#### 22.2.2 Black frame / `--test` always reads 0 or 1023 (mask never changes)

**Symptom:** `.venv/bin/python3 lane_node/camera.py --test` prints all-black, or the
per-deck mask is stuck at `0` (empty) or `0b1111111111` = `1023` (full rack)
regardless of what's actually standing.

| Likely cause | Fix |
|---|---|
| **Missing video ground on the camera tap** — the single most common hardware trap, identical to the original QubicaAMF tap. The composite tap is **Brown = video / Blue = ground**; the RCA shell must reach Blue (pin-8 ground). | Reseat the tap **ground** (RCA shell → Blue / pin-8). This is wiring, **not** a code bug. |
| **Dongle not enumerated** (no `/dev/video0`) | `ls -l /dev/video*` (expect ≥ `/dev/video0`); `v4l2-ctl --list-devices` should show a USB Video/UVC device. Reseat USB; check `dmesg`. If it enumerates as `/dev/video1`, set `WSL_LANE_CAMERA_DEVICE=1` on the service. |

#### 22.2.3 Scores are wrong but consistent

**Symptom:** detection runs, but a particular pin/spot is repeatedly misread (the
*same* error every time), not random flakiness.

| Likely cause | Fix |
|---|---|
| **Per-spot calibration** — that pin's region coordinate (`PIN_SPOTS_PX`) or the per-frame threshold is slightly off. Pins **2 & 3** are the homography-predicted spots (watch these first); the **right deck** is more oblique, so its margins are tighter. | This is a tuning item, not a redesign. Keep a tally of **detected vs actual** standing pins per ball; capture a couple of misread frames. The fix is a `PIN_SPOTS_PX` coordinate nudge or a `DET_THR` adjustment (calibration lives in `lane_node/pin_detect.py`). Send the tallies + frames to whoever owns the detector calibration. |
| **Whole-frame flakiness that tracks the house lighting** (lights on/off, sun) | Re-measure / bump `DET_THR`. The detector already drift-corrects for exposure, so this should be rare; last resort is an IR illuminator + IR-pass filter. |

#### 22.2.4 Nothing happens on a ball

| Likely cause | Fix |
|---|---|
| **DIELL ball detector not firing**, or the node is in the wrong mode | Watch the log for `GPIO: ball detected on lane N, mode=camera`. If that line never appears, the DIELL beam isn't tripping the input. If it appears but no score, confirm the mode is `camera` (see below). |
| **Wrong scoring mode** | `WSL_LANE_SCORING_MODE` must be `camera` for auto-scoring. `manual` = desk scores (ball event emitted with no `pin_mask`); `disabled` = log only. Default is `manual` (`lane_node/lane_node.py`). |

#### 22.2.5 Track A mode/tuning knobs (env vars on the `lane-node` service)

Set these via `sudo systemctl edit lane-node` (a drop-in survives reboot), then
`sudo systemctl restart lane-node`:

| Var | Default | Meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | seconds after DIELL fires before grabbing the frame (tune if catching the sweep or pins still rocking) |
| `WSL_LANE_CAMERA_DEVICE` | `0` | capture device index (`/dev/videoN`) |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks — **bench only, never on a live lane** |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | the WSL-SRV server (currently `ws://192.168.4.103:8765`) |

> **To abort Track A to manual instantly:** flip `WSL_LANE_SCORING_MODE=camera →
> manual` and `sudo systemctl restart lane-node` (or Ctrl-C the foreground daemon
> and relaunch without the env var). **No machine impact** — the lane keeps
> running; the desk scores via the existing flow.

#### 22.2.6 Server-side check (WSL-SRV)

The scoring **server** (`lane_node_server.py`) runs on WSL-SRV at **ports 8765
(WebSocket) + 8766 (HTTP)**. Health from any LAN machine:
```
curl http://192.168.4.103:8766/api/health
```
returns JSON with the connected node. The per-lane scoring display is
`http://192.168.4.103:8766/display?lane=N`. A manual correction is always available:
`POST /api/lane/N/score {pin_mask, foul?}`.

> **(VERIFY: WSL-SRV IP.)** The server IP is **192.168.4.103** as of the 2026-06-03
> eero router swap (the old `192.168.86.36` is dead), but the DHCP reservation was
> still a TODO in the runbook — **confirm the current WSL-SRV IP and that it is
> reserved on the eero** before relying on these URLs. (`docs/phase8_trackA_golive_runbook.md` banner.)

---

### 22.3 "Lane went dark after a power event" — service not enabled

**Symptom:** a lane (or the whole node) has **no scoring at all** after a power
blip, UPS event, or reboot — not "wrong score," but *gone*. Health check shows the
node disconnected.

**Likely cause:** the systemd `lane-node` service is **loaded/active but not
`enabled`**, so it does **not** start on boot. This is a real trap that was hit on
the bench rig: the service ran fine for days only because the Pi had not rebooted.

**Fix:**
```bash
sudo systemctl enable lane-node      # make it start on boot (the missing step)
sudo systemctl restart lane-node     # start it now
systemctl is-enabled lane-node       # must print: enabled
journalctl -u lane-node -f           # confirm it comes up
```

> **Provisioning rule:** `systemctl enable lane-node` **must** be part of every
> node's provisioning runbook. The symptom of a missing enable is exactly "lane
> goes dark after any power event." (`docs/phase8_trackA_golive_runbook.md`
> failure cheat-sheet; project provisioning note.)

> **(VERIFY: the Track-B controller daemon's own service unit.)** The
> `lane-node` service above is the **scoring** node (`lane_node/lane_node.py`). The
> Track-B **controller** daemon (`lane_node/controller_daemon.py`) is a *separate*
> tight synchronous control loop and is **not yet unified** with the scoring/server
> path (the file's `TODO(server)`); its production service unit / `systemctl enable`
> step is a cutover item not fixed in the files read here. The same enable-on-boot
> rule will apply.

---

### 22.4 Relays will not energize / the rail dropped (Track B, bench/cutover)

> **Context:** This applies to the **Track-B controller board** during bench
> bring-up or cutover — Track B is **not yet cleared for live machines**. Do this
> on a **locked-out / off** machine (§22.0).

A motion relay (S/T/SP/BE/M/M2) energizes **only if both** of two independent gates
are satisfied (§9, §10.5):

- **(a)** the Pi sets that relay's bit on **MCP23017 OUT-A** (chip `0x22`) — turns
  on the per-relay NPN driver that grounds the coil low side; **and**
- **(b)** the **relay-enable rail** (`RELAY_ENABLE_RAIL`) is live — supplying +5 V
  to the coil high side through the pass-FET **Q14 (AO3401A)**.

Software alone can never fire a coil. If relays won't energize, first determine
whether the **rail** is dead or the **command** is missing.

#### 22.4.1 First measurement: is the rail live?

Probe **`RELAY_ENABLE_RAIL` at TP16** (the rail test pad; §10.8):

- **≈ +5 V** → the rail is up; the problem is the command path (jump to §22.4.3).
- **≈ 0 V** (or pulled toward the coil-low side through the coils) → the rail is
  dead; one of the **six AND conditions** is false (continue below).

#### 22.4.2 The six rail conditions — read each one

The rail is a hardware AND of six conditions (spec §4.1; built in
`generate_kicad_netlist_revB.py` `block_rail()` / `block_watchdog()`). **All default
false/open (fail-safe).** Two are external NC loops in series with the pass-FET
*source*; three are a series NPN/FET stack on the pass-FET *gate*; one (cam-stop)
folds into RP2040 health. Read them in this order (cheapest first):

| # | Condition | How to read it | "Permit" state | Common cause of a false |
|---|---|---|---|---|
| 2 | **Arm OK** | `ARM_PERMIT` at **J1 (J_PI) pin 8** | HIGH | Pi hasn't armed: FSM not in a runnable state, or it latched into MANUAL_INTERVENTION/FAULT (§22.5). Default false via R108 100 k base pulldown. |
| 1 | **Watchdog OK** | `WDOG_KICK` at **J1 pin 7** should show periodic pulses; `NE555_OUT` (U36 pin 3) toggles; `WDOG_OK_PULLDOWN` (Q13 drain) pulled to GND while OK | kicks present | Pi process hung/stopped → no kicks → NE555 times out → Q13 off. Or the kick GPIO isn't wired/asserted. |
| 3 | **RP2040 OK** | `RP2040_OK` = **GP2**, at **J1 pin 13** | HIGH | RP2040 unpowered / in reset / BOOTSEL / firmware crash / cam-stop or motion-timeout fault. GP2 is Hi-Z when unpowered → R110 100 k holds Q16 off. |
| 4 | **Cam-stop OK** | *(not a separate gate)* — folds into condition 3 | (see #3) | The firmware drops **GP2 LOW** on a cam-stop violation / motion timeout (§22.5). There is **no sixth transistor** — don't look for one. |
| 5 | **TB/SC interlock** | external NC loop on **J14 (J_SAFETY) pins 1↔2**; `SAFE_TBSC_RETURN` | loop closed | Collision-course interlock open, or the J14 TB/SC loop is broken/unwired. |
| 6 | **Stop/CIS/master chain** | external NC loop on **J14 pins 3↔4**; `SAFE_STOP_RETURN` (Q14 source) | loop closed | Stop/C.I.S. loop open, or J14 Stop/CIS loop broken/unwired. Probe `SAFE_STOP_RETURN` — ≈ +5 V only when **both** J14 loops are closed. |

**Structural facts that make this a true hardware AND** (so you know what to expect
on a meter):

- **Conditions 5 and 6 are in series with the FET *source*.** +5 V enters J14.1,
  must traverse the closed TB/SC loop (J14.1→2), cross the on-board jumper
  (J14.2 = J14.3, `SAFE_TBSC_RETURN`), traverse the closed Stop/CIS loop
  (J14.3→4), and only then reach the pass-FET source (`SAFE_STOP_RETURN`). **Break
  either loop and the FET source is dead — no gate state can re-enable the rail.**
- **Conditions 1, 2, 3(=4) are a series transistor stack on the FET *gate***
  (`RAIL_GATE`, held up to the source by R106 100 k = off by default):
  **Q15 (ARM) · Q16 (RP2040_OK) · Q13 (watchdog) must all conduct** to pull the
  gate low and turn the P-FET on. Any one off → gate stays up → rail dead.

> **During bench bring-up, an open J14 loop is the #1 reason the rail won't come
> up.** If you have not yet wired the external TB/SC and Stop/CIS loops, the rail
> *should* be dead. For controlled bench testing you close the J14 loops with known
> jumpers (then prove each drop independently), per §10.8 step 4 / spec §12.9.
> Wire the field loops to **break** on the unsafe condition (NC = closed when safe).

> **(VERIFY: final electrical form of the J14 loops.)** Spec §4.4 / §11 leave the
> TB/SC and Stop/CIS **electrical form, polarity, and final connector wiring** open
> pending at-machine verification — the board provides the NC-loop topology; the
> exact field derivation (TB/SC cam contacts vs the existing 24 V control path vs a
> low-voltage isolated loop) is a cutover decision.

#### 22.4.3 Rail is live but a specific relay won't fire

If TP16 is ≈ +5 V but one output doesn't actuate, the **command** path or that
**channel** is the problem:

| Likely cause | Check / fix |
|---|---|
| **Pi isn't setting the OUT-A bit** | The FSM drives relays via `MachineIO._set_out()` over I²C to MCP23017 `0x22`. Confirm the FSM is actually in a state that commands that motor (§22.5 / §3). |
| **Wrong bit ↔ relay mapping** | `controller_io.OUT_A_MAP` is the source of truth and is regression-checked against the netlist generator. S=(0,0), T=(0,1), SP=(0,2), BE=(0,3), M=(0,4), **M2=(0,5)**, **M1=(0,6)**; lamps first_ball=(0,7), second_ball=(1,0), strike=(1,1), foul=(1,2). (M2 is bit 5, **before** M1 bit 6 — per the generator. BS/OS, M1/M2, strike/foul were once swapped and have been corrected to match the netlist — see §12.) |
| **M1 (ball return) won't fire — by design** | **K7/M1 is DNP** (do-not-populate): not bench-confirmed on these chassis and the FSM doesn't drive it. The coil/driver/flyback footprints exist on the rail but are not assembled. Do not expect M1 to work until it is verified at-machine and populated (spec §3.2, §11 item 6). |
| **I²C bus not enumerating** | All three board MCP23017s must come up: **IN-A `0x20`, IN-B `0x21`, OUT-A `0x22`** on the board's own bus. If `MachineIO` can't open the bus or a chip NAKs, no outputs (or no slow inputs) work. Confirm with `i2cdetect` on the board's bus and check the 3.3 V rail + the two 4.7 k I²C pull-ups. |
| **Coil driver / relay fault** | Probe the per-relay NPN (Q1–Q6 for S/T/SP/BE/M/M2; Q7 is M1 DNP) and the coil. The flyback diodes are D1,D3,D5,D7,D9,D11 (1N4148WS) across the coils. |

#### 22.4.4 A relay coil drops but the machine circuit stays made (welded contact)

**The rail de-energizes coils; it cannot open a welded-closed contact** (§10.6,
spec §4.5). If a contact welds, dropping the rail removes coil drive but the welded
contact — and the machine control circuit it feeds — stays made.

- The **final physical stop is the rear-panel master breaker** (Stop/C.I.S. chain),
  not the rail. Cut it.
- This is why **relay contact rating + arc suppression are safety-relevant.** Each
  motion output has **DNP** footprints for an RC snubber (`Rsnub_*` 100 R +
  `Csnub_*` 10 nF X2) and a **MOV** across the contact — populate per output after
  measuring the actual inductive AC control load (spec §2.3, §3.2, §11 item 1).

---

### 22.5 Motion-timeout / cam-stop faults (Track B)

**Symptom:** a motor starts, runs longer than expected, then **everything stops and
the rail drops**; the FSM/firmware reports a fault.

There are **two independent timeout backstops**, both at the same 8-second budget,
which together fail the motion safe:

1. **FSM software backstop — `MAX_MOTION_S = 8.0 s`** (`cycle_control_8270.py`).
   In `poll()`, if any motion state (`SWEEP_TO_GUARD`, `TABLE_DETECT`,
   `RUNTHROUGH`, `SPOTTING`, `TABLE_FINISH`) is held longer than `MAX_MOTION_S`,
   the FSM logs `FAULT — <state> > 8.0s; motors OFF`, drives all motors off, and
   enters `State.FAULT`.
2. **RP2040 firmware backstop — `MAX_MOTION_MS = 8000` ("cam timeout", spec §4.2;
   `firmware/rp2040/config.h`).** If the Pi marks a *guarded* motor `RUN` over UART
   and never `STOP`s it within 8 s, the firmware **latches a fault and drops
   `RP2040_OK` (GP2) LOW** → rail dead. It emits `{"ev":"flt","code":"motion_timeout","m":"S"}`.
   (BE and M are **not** max-run-guarded — BE is continuous, M is master/power.)

| Likely cause | Fix |
|---|---|
| **A motor genuinely never reached its cam-stop angle** (mechanical bind, slipping cam, motor not turning, or a cam switch not tripping) | This is the backstop doing its job. Lock out and inspect the mechanism / the relevant cam switch (§3, §4). The cam that should have stopped the motion: SA (sweep 270 run-through / 360 zero), SB (sweep 66 guard), TA1 (table 355 zero / 185 delay reset), TA2 (table 260). |
| **`MAX_MOTION_S` / `MAX_MOTION_MS` set too tight** for the real machine | The field rule is "set = measured + margin" (`cycle_control_8270.py` comment). If a *healthy* motion legitimately takes longer than 8 s on this machine, the budget needs raising — but **measure first**; do not loosen a safety backstop without data. |
| **Cam edge polarity / cam-stop overrun** | Per-cam-edge cam-stop *overrun* enforcement (a stop-cam fires mid-run and the Pi fails to STOP within a grace window) is the **deferred v1.1** firmware feature, gated on bench-confirmed cam **edge→angle polarity** (`firmware/rp2040/README.md`; runbook §3.2). v1 provides RP2040 *health* + the *max-run* backstop only. Capture the per-cam trip edge during bench bring-up (firmware README §"Bench bring-up" step 2). |

**To recover from a latched fault** (firmware side):
- The Pi sends **`CLEAR`** to the RP2040 **only from a known-safe zero/ready
  state**; the firmware then re-permits (GP2 back HIGH). In the daemon, `CLEAR` is
  sent together with the operator's **First-Ball-Zero (PBZ)** re-arm
  (`controller_daemon._slow_actions`: PBZ → `fsm.first_ball_zero()` **and**
  `link.clear()`).
- The FSM's own `FAULT`/`MANUAL_INTERVENTION` states require a **deliberate
  First-Ball-Zero (PBZ)** to return to `READY` — there is **no auto-rearm**
  (`controller_daemon.py` health-loss safety trip; self-test "recovery does NOT
  auto-rearm"). This is intentional: a stale relay latch must never silently
  resume motion.

> **Power-restore behavior is the same idea:** the FSM comes up in
> **MANUAL_INTERVENTION** and drives nothing until the operator presses PBZ
> (`power_restore()`; the MP "Power-Down" rule, spec §5). A board that just powered
> on and "won't move" is behaving correctly.

---

### 22.6 RP2040 link dead / cam & ball events missing (UART)

**Symptom:** cam/ball events stop reaching the FSM; the daemon logs the RP2040 link
**LOST** and trips safe; `RP2040_OK`/the rail drops.

The RP2040 owns the **8 fast inputs** (6 cams + 2 DIELL ball beams) and pushes edge
events to the Pi over **UART0, 115200 8N1, newline-delimited JSON** (`GP0`=TX→Pi RX,
`GP1`=RX←Pi TX; firmware README, `rp2040_link.py`). The Pi tracks RP2040 health and
trips the FSM safe if it goes unhealthy.

**How the Pi judges health** (`rp2040_link.health_ok()`): healthy **only if** the
RP2040 is heartbeating (a `boot`/`hb`/`rp_ok`/`flt`/`ack` line within the
**`hb_timeout` = 1.0 s** window) **AND** reports `rp_ok` true **AND** has no latched
fault. A bare `flt` event marks it unhealthy immediately, even without a paired
`rp_ok:0` (lossy-UART robustness). The firmware heartbeats at **`HB_INTERVAL_MS` =
250 ms** (~4 Hz).

**What the daemon does on health loss** (`controller_daemon.BoardController.tick()`):
forces motion outputs **off** (clears the relay latches), latches the FSM into
**MANUAL_INTERVENTION** (recovery requires a deliberate PBZ), drops **ARM**, and
keeps kicking the NE555 (the *Pi* is still alive). Note that `RP2040_OK` has
**already** dropped the rail in hardware regardless — the daemon's action is the
software belt-and-suspenders so the FSM/desk see it.

| Likely cause | Fix |
|---|---|
| **UART not wired / wrong port** | Confirm the Pi's serial device for this board (`controller_daemon.DEFAULT_BOARDS` `uart_port`, e.g. `/dev/ttyAMA0` — **all `# CONFIRM` placeholders set at bench/cutover**). TX/RX must be **crossed**: Pi TX → Pico `GP1`/RX, Pico `GP0`/TX → Pi RX. Baud **115200 8N1**. |
| **RP2040 unpowered / not flashed / crashed** | Confirm a `boot` line then ~4 Hz `hb` with `ok:1`. If the firmware hung, its **internal hardware watchdog** (`WDT_TIMEOUT_MS` = 250 ms) resets the chip — you'll see a `boot` with `wdt_reset:1`. After reset, GP2 is held LOW for `BOOT_SETTLE_MS` = 200 ms, then HIGH only if healthy. |
| **Stale heartbeat (link "alive" but quiet)** | If no line arrives for > 1.0 s, `is_alive()`/`health_ok()` go false → daemon trips safe. Check the cable, the Pico power, and that the reader thread is running (`RP2040Link.start()`). |
| **Latched firmware fault** | `health_ok()` stays false until an `hb` with `flt:""` arrives — i.e. after a `CLEAR` from a safe state (§22.5). |
| **Cam events arrive but the FSM ignores them** | The FSM only acts on the **trip edge** and only in the matching state. Which edge (`f`/`r`) is the angular trip is a **bench-confirm item** — the default assumes `f` = trip (`rp2040_link.RP2040Link(trip_edge="f")`; firmware README). Interlock cams **SC/TB** are **not** dispatched as FSM cam events — they feed the `interlock_ok()` echo only. |

**To verify the fast inputs at the bench** (firmware README §"Bench bring-up"
step 2): hand-actuate each cam / break each DIELL beam and confirm the matching
`{"ev":"cam","id":...}` / `{"ev":"ball","src":...}` line (correct `id`). All fast
inputs are **active-low** at the Pico (machine contact closed ⇒ GPIO LOW; on-board
10 k pull-up to 3.3 V). The GP↔signal map (config.h / §12):

| GPIO | Pico pin | Signal |
|---|---|---|
| GP6 | 9 | SA (sweep cam) |
| GP7 | 10 | SB (sweep cam) |
| GP8 | 11 | SC (sweep interlock cam) |
| GP9 | 12 | TA1 (table cam) |
| GP10 | 14 | TA2 (table cam) |
| GP11 | 15 | TB (table interlock cam) |
| GP12 | 16 | DIELL-L (ball) |
| GP13 | 17 | DIELL-R (ball) |
| GP2 | 4 | RP2040_OK (rail permission) |
| GP0 / GP1 | 1 / 2 | UART0 TX / RX to Pi |

> ⚠️ **Do not use the GPIO column in `docs/phase8_channel_allocation.md` §2** — it
> assigns the fast inputs to GP0–GP7 and is **stale**. The as-built board uses
> **GP6–GP13**; `firmware/rp2040/config.h` and the netlist generator are correct
> (see §12).

**Re-flashing the RP2040 firmware** (firmware README §"Flash"):
- **USB BOOTSEL (preferred):** hold BOOTSEL on the Pico while connecting USB → it
  mounts as `RPI-RP2` → drag-drop `wsl_phase8b_rp2040.uf2`.
- **SWD (if USB inaccessible once soldered):** `picotool load -x build/wsl_phase8b_rp2040.uf2`,
  or OpenOCD via the board's SWD test points.
- Rebuild on the Westside laptop with `pwsh -File build.ps1` (auto-discovers the
  bootstrapped toolchain → `build/wsl_phase8b_rp2040.uf2`, ~40 KB).

---

### 22.7 The watchdog & health behavior (what "healthy" looks like)

Two **independent** watchdogs guard two different things — **do not confuse them**
(§10.2):

| Watchdog | Watches | Timeout | What it does on timeout |
|---|---|---|---|
| **NE555 monostable** (U36, on the board) | the **Raspberry Pi** | (monostable RC; bench-measured) | Pi stops kicking → NE555 reverts → Q13 off → rail AND opens → **all relay coils drop** |
| **RP2040 internal HW watchdog** | the **Pico firmware** | `WDT_TIMEOUT_MS` = 250 ms | firmware loop hangs → chip resets → GP2 → Hi-Z → R110 holds Q16 off → **rail drops**; auto-recovers on reboot (`boot` with `wdt_reset:1`) |

The Pi **kicks the NE555 only from `fsm.poll()`** inside the control loop
(`controller_io.MachineIO.watchdog_kick()`, called every `poll()`). This coupling is
**intentional**: if the Track-B control loop stalls, kicks stop and the rail drops.
(Contrast Track A, where scoring must **never** be able to stop the machine.)

A healthy RP2040 at the bench:
- a `boot` line on power-up, then `{"ev":"hb",...,"ok":1}` at ~4 Hz after ~200 ms;
- `GP2` reads **HIGH** on a meter/test-pad once healthy;
- the daemon's `link.health_ok()` returns true.

> **(VERIFY: NE555 monostable timeout period and the Pi kick GPIO number.)** The
> watchdog RC is R100 = 100 k + C11 = 100 µF, but the kick is wired into both the
> timing and trigger nodes (retrigger topology) and the design doc states the drop
> behavior **qualitatively** without a number (spec §4.3). The effective drop time
> is a **bench measurement** (§10.8 / spec §12.9 "watchdog drop") — **do not assume
> ~11 s.** Likewise the Pi-side **kick GPIO number** (and the per-board **ARM** GPIO)
> are `# CONFIRM` placeholders in `controller_daemon.DEFAULT_BOARDS` set at bench/
> cutover — the *board* side is fixed at J1 pin 7 (`WDOG_KICK`) and J1 pin 8
> (`ARM_PERMIT`).

---

### 22.8 Periodic maintenance

Most of this system is solid-state with no wear parts; the maintenance load is
light. Recommended checks:

**Track A — scoring (per-pair, ongoing):**
- **Accuracy spot-check.** Keep a casual detected-vs-actual tally during play; a
  drift toward a particular pin/spot is a calibration nudge (§22.2.3), not a
  failure.
- **Empty-reference refresh** if the camera is moved/reseated, the dongle changes,
  or lighting changes materially: recapture `empty_ref.png` (§22.2.1). The detector
  drift-corrects exposure, so routine lighting swings should not need it.
- **Confirm `systemctl is-enabled lane-node` = enabled** after any maintenance that
  touched the Pi or its OS (§22.3) — the most common way a lane silently goes dark.
- **Camera tap ground integrity** — a marginal RCA-shell→Blue ground shows up as
  intermittent black frames (§22.2.2).

**Track B — controller (per-board; once cleared for live):**
- **Re-run the bench safety drops periodically** on a locked-out machine: watchdog
  drop, ARM drop, both J14 interlock drops, and the motion-timeout drop (§10.8
  steps 2–5). These prove the fail-open path is still intact.
- **Inspect motion-relay contacts + suppression** on inductive outputs (S/T/SP/BE/M/M2)
  for arcing/pitting; verify the populated snubber/MOV per output (§22.4.4).
- **Verify test-point readings** against §10.8 (TP16 rail, `RAIL_GATE`, `NE555_TRIG`/
  `NE555_OUT`, `SAFE_STOP_RETURN`, `RP2040_OK`, `ARM_PERMIT`, `WDOG_KICK`).
- **Confirm the per-cam trip edges** are still as captured (relevant once v1.1
  cam-stop overrun is enabled).

**Software hygiene:**
- On the Pi: `git pull` only deliberately (it brings `camera.py` / `lane_node.py` /
  calibrated `pin_detect.py`); **`empty_ref.png` is per-Pi and gitignored** — never
  expect a pull to provide it.
- Watch `journalctl -u lane-node -f` after any change; the runbook log strings
  (§22.2) are your go/no-go.

---

### 22.9 Spares to keep on hand

The strategic goal of Phase 8 is **zero EOL hardware** — every active part is a
commodity, in-stock device chosen so the center is not hostage to a defunct vendor.
That said, keep a small spares kit so a failure is a swap, not a fab order.

#### 22.9.1 Whole-unit / module spares (highest priority)

| Spare | Why | Notes |
|---|---|---|
| **A complete spare controller board (PCBA)** | Fastest recovery is board swap, not component-level repair, on a 250 × 225 mm board | The board is a single, identical, per-lane design — one spare fits any 82-70 lane. Fab/assemble a couple of extras with each batch. |
| **Raspberry Pi (per-pair host)** | Runs scoring + control; commodity, cheap | Keep the OS image + the node config so a swap is reflash-and-go. **Remember `systemctl enable lane-node`** on any fresh Pi (§22.3). |
| **Raspberry Pi Pico (RP2040 stamp module), ref A1 / RP_PICO** | The fast/safety co-processor; socketed-module choice was deliberate to make it swappable | **DigiKey 2648-SC0915CT-ND / Raspberry Pi SC0915.** Use the **plain Pico (castellated, no headers)** — **NOT** the Pico H/WH with header pins. Flash `wsl_phase8b_rp2040.uf2` after fitting (§22.6). |
| **VIXLW USB capture dongle** | The only thing between the camera and the Pi for Track A | UVC-class; enumerates as "USB Video." |

#### 22.9.2 Board-level component spares (for hand repair)

Confirmed, fab-locked parts from the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`).
**Use these exact parts** — the critical-substitution notes are load-bearing:

| Part | Role | Designators | LCSC | Critical note |
|---|---|---|---|---|
| **Omron G5LE-14, 5 VDC coil**, SPDT relay (THT) | Motion-output relays | K1–K6 (K7/M1 = **DNP**) | **C116963** | **5 VDC coil — DO NOT substitute a 9 V / 12 V / 24 V coil.** Carries no motor current; switches dry contacts only. |
| **MCP23017-E/SO** I²C 16-bit I/O expander (SOIC-28W) | Slow inputs + relay/lamp outputs | U1, U2, U3 | **C47023** | **I²C part — NOT the SPI `MCP23S17`.** Runs at **3.3 V** for Pi-safe I²C. (IN-A `0x20`, IN-B `0x21`, OUT-A `0x22`.) |
| **PC817B** optocoupler (DIP-4) | Isolates every machine input | U4–U35 (32 pcs) | **C5692981** | Logic side at 3.3 V, **active-low** at the MCU. Keep CTR bin consistent with the Rev-B field resistors. |
| **NE555DR** (TI), **bipolar** 555 (SOIC-8) | Hardware watchdog monostable | U36 | **C7593** | **Bipolar NE555 — avoid CMOS/TLC555**; the timing/threshold behavior would change. |
| **AO3401A** P-ch MOSFET (SOT-23) | Relay-enable-**rail pass-FET** | Q14 | C347476 | High-side rail switch. Don't confuse with the N-ch parts below. |
| **AO3400A** N-ch MOSFET (SOT-23) | Watchdog kick (Q12) + watchdog-OK (Q13) | Q12, Q13 | C20917 | **Q12/Q13/Q14 are visually similar SOT-23 parts — do not swap N-ch and P-ch during hand placement.** |
| **MMBT3904** NPN BJT (SOT-23) | Relay-coil drivers (Q1–Q6) + safety-chain AND transistors (Q15, Q16) | Q1–Q6, Q15, Q16 | C909754 | One grouped BOM line for all 8; confirm by role/position. |
| **2N7002** N-ch MOSFET (SOT-23) | Low-side status-LED drivers | Q8–Q11 | C916396 | The 4 mask-LED channels. |
| **SS14** Schottky (SMA) | Reverse-polarity / input protection on the 5 V input | D17 | C2480 | |
| **1N4148WS** (SOD-323) | Relay-coil flybacks + watchdog steering diodes | D1,D3,D5,D7,D9,D11,D15,D16 | C118873 | |
| **TRACO TMA-0505S** isolated 5 V→5 V DC/DC (THT) | Isolated **field-wetting** supply (keeps FIELD_GND off logic ground) | U37 (ISO_WET) | *(see note)* | DigiKey 1951-1003-ND. **Do not substitute without a pinout + isolation review.** Not in the JLC SMT BOM — placed/hand-fitted. |
| 0805 R/C passives (4.7 k, 2.2 k, 10 k, 1 k, 100 k, 330 R; 100 nF, 10 nF, 10 µF; 100 µF/16 V electrolytic C11) | Pull-ups/-downs, gate Rs, decoupling, watchdog RC | many | (grouped) | Confirm passives **by value**, not by assuming a unique BOM line per RefDes. |

> **(VERIFY: LCSC/MFR number for the TMA-0505S.)** The isolated wetting supply is
> **TMA-0505S** in the as-built netlist (`block_supplies()`, ref ISO_WET → board ref
> **U37**) and the hand-solder BOM (TRACO `TMA 0505S`, "Locked exact part"). An
> earlier draft (`docs/phase8b_pcb_revB_BOM_power.md` §3.2) *recommended* a
> `B0505S-1W` — **the netlist (source of truth) wins: use the TRACO TMA-0505S.** It
> is not in the JLC SMT upload BOM, so it has no LCSC line in that file; order from
> DigiKey/TME/Mouser and verify the pinout before fitting.

#### 22.9.3 Connector / mating-part spares

Field-input and machine-output connectors are **Phoenix Contact MCV/MKDS** series
(from the hand-solder/off-board BOM). Keep the **mating plugs** as spares — the PCB
headers are soldered, the plugs are field-wiring and get reworked:

| Board connector | Part (header on PCB) | Mating plug to stock |
|---|---|---|
| J3 (J_FAST_IN, 10-pos, 3.5 mm) | Phoenix MCV 1,5/10-G-3,5 (1843680) | MC 1,5/10-ST-3,5 |
| J4 (J_SLOW_IN_A, 14-pos) | MCV 1,5/14-G-3,5 (1843729) | MC 1,5/14-ST-3,5 |
| J5 (J_SLOW_IN_B, 12-pos) | MCV 1,5/12-G-3,5 (1843703) | MC 1,5/12-ST-3,5 |
| J13 (J_LAMP_LED, 6-pos) | MCV 1,5/6-G-3,5 (1843648) | MC 1,5/6-ST-3,5 |
| J14 (J_SAFETY, 4-pos) | MCV 1,5/4-G-3,5 (1843622) | MC 1,5/4-ST-3,5 |
| J2 (J_PWR 5 V, 3-pos, 5.08 mm) | Phoenix MKDS 1,5/3-5,08 (1715734) | fixed screw terminal (no off-board plug) |
| J6–J11 (J_MOTION_*, 2-pos, 5.08 mm) | Phoenix MKDS 1,5/2-5,08 (1715721) | fixed screw terminal (no off-board plug) |
| J1 (J_PI, 2×10 IDC) | 20-pos 2×10 2.54 mm header | ribbon/IDC socket to the Pi |

#### 22.9.4 EOL-risk machine parts (the parts Phase 8 exists to escape)

These are **legacy** parts on the machine/scoring side that are end-of-life with no
viable supply chain. Where the original is being **retired** by Phase 8, the "spare"
is the Phase 8 replacement, not the EOL part. Stock the few that are still in the
loop:

| EOL part | Status under Phase 8 | Spares stance |
|---|---|---|
| **QubicaAMF T-Camera** (one per pair) | **Reused** by Track A (its composite video is tapped) | The camera is still in the live path — keep any spare T-Cameras you have; they are EOL from QubicaAMF. |
| **QubicaAMF VDB** (per-lane scoring computer), **ETHost** gateway, **T-VISION** board | **Retired** — replaced by the Pi + camera scoring | Don't invest in spares; the Pi-per-pair build *is* the replacement. Keep enough only to cover lanes not yet cut over. |
| **Omega-Tek "Omniboard"** retrofit controller (lanes 21/22) + Expander/ZOT | **Being replaced** by the rev-B controller (Track B) | **Vendor appears defunct** → highest continuity risk and a primary motivation for Phase 8. Keep whatever spares exist for lanes not yet cut over; the long-term answer is the Phase 8 board. |
| **Active "Ultra 98 Plus" MP controller** (lanes 11/12) | Being replaced by Track B over time | Mixed fleet; keep until that pair is cut over. |
| **AMF 82-70 machine mechanism, motors, cams, grippers, mask** | **KEPT** — unchanged on every lane | Standard pinsetter wear parts (cam microswitches, gripper switches GS1–GS10, motor contactors, drive components) per normal AMF 82-70 service stock. The Phase 8 board reads/commands these; it does not replace them. `(VERIFY: specific AMF 82-70 mechanical part numbers — outside the named live files; use the AMF 82-70 Service & Parts manual.)` |

---

### 22.10 When to stop and escalate

- **Any time the safe fallback is available, take it.** Flip Track A to `manual`
  (§22.2.5) — the lane runs and the desk scores. There is no machine risk.
- **Do not run Track B against a live machine** until the full hardware safety
  chain is bench-proven per §10.8 / spec §12.9 and the cutover runbook
  (`docs/phase8_trackB_controller_cutover_runbook.md`). The current firmware is
  **NOT cutover-ready** (the v1.1 cam-stop overrun is still deferred —
  `firmware/rp2040/README.md` "Status / next").
- **A dead rail during diagnosis is the safe state**, not necessarily a fault
  (§22.0 item 6). Confirm *which* of the six conditions is open (§22.4.2) before
  assuming a board failure.
- **If a relay contact may have welded**, the rail will not save you — cut the
  master breaker (§22.4.4, §10.6).

> **Cross-references:** machine theory and the cycle/cam timing in **§3**; the I/O
> inventory in **§4**; the board domains/isolation in **§5**; power rails in **§6**;
> RP2040/MCP/I²C logic in **§7**; opto front-ends in **§8**; relay outputs in **§9**;
> the watchdog + relay-enable rail (and its test points + bench-drop procedure) in
> **§10**; connector pinouts in **§11**; the GPIO/MCP bit maps in **§12**; and the
> machine-side C1/C2A harness in **§14**.


## 23. Appendices: Full BOM, Cam Timing, Glossary & Document Index

> **What this chapter is.** Reference tables you will reach for repeatedly: the complete per-part bill of materials for one rev-B controller board (split into what the contract manufacturer places, what you hand-solder, and what is intentionally left off), the consolidated AMF 82-70 cam-timing table, an expanded glossary, and an index of every source document/script/runbook so you know where the deep detail lives. It is grounded in the live fab-package CSVs, the board netlist generator, the firmware pin map, and the controller behavioral spec.
>
> **Accuracy convention (unchanged from §1).** Every part number, designator, pin, net name, and value below is copied from a live source file. The authoritative sources are named at the head of each appendix. **When this manual and a live source disagree, the live source wins.** Anything not confirmable from a source is flagged inline as `(VERIFY: …)` — treat those as work items, not facts.
>
> **Scope reminder (from §1.5 / §5).** The BOM is for **one** controller board = **one lane**. A lane *pair* uses **two** identical boards on one Raspberry Pi, so multiply every board-level quantity by 2 for a pair and by 32 for the whole center. The Raspberry Pi itself, the T-Camera, and the USB capture dongle are pair-level / shared and are **not** on this board BOM.

---

### 23.A Appendix A — Full Bill of Materials (rev-B controller board, one lane)

**Authoritative sources for this appendix (all under `kicad/fab_revB_routed_manual/`):**

| File | What it is |
|---|---|
| `assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv` | The parts the JLCPCB **Standard-PCBA** service places (SMT + the wave-solderable PC817 optos + G5LE relays). LCSC part numbers locked. |
| `assembly/wsl-phase8b-revB-hand-solder-bom.csv` | Through-hole / module parts installed **after** the PCBA returns (Pico module, Phoenix connectors, isolated DC/DC). |
| `assembly/wsl-phase8b-revB-offboard-hardware.csv` + `…-harness-mating-parts.csv` | Mating plugs, ribbon cable, and mounting hardware that are **not** on the board. |
| `assembly/wsl-phase8b-revB-dnp-excluded.csv` | Footprints present in copper but **excluded** from assembly (DNP parts + mechanical/test refs). |
| `manifest.json` | Official package counts and SHA256s (generated `2026-06-04T14:42:42`). |

**Package-level part counts (from `manifest.json`, the authoritative totals for the whole board):**

| Count | Value | Meaning |
|---|---|---|
| `bom_refs` | **189** | Non-DNP component reference designators that get a part (the real populated board). |
| `bom_rows` | **84** | Unique sourcing lines that those 189 refs group into. |
| `dnp_refs` | **27** | Do-Not-Populate footprints (M1 channel + value-DNP snubber/MOV) — excluded from BOM and placement files. |
| `excluded_non_dnp_refs` | **20** | Mechanical/test-only refs (4 mounting holes + 16 test pads) — real copper, no purchased part. |

> The 189 populated refs are split across two assembly steps: **JLCPCB Standard-PCBA places the SMT + PC817 + G5LE block; you hand-solder the Pico module (A1), the isolated DC/DC (U37/ISO_WET), and the board-side connectors — J1 (2×10 IDC) plus the Phoenix terminal blocks/headers J2–J11, J13, J14 (J12/M1 stays DNP).** That split is the whole reason there are separate "JLC standard PCBA" and "hand-solder" CSVs.

#### 23.A.1 JLC Standard-PCBA placed parts (locked LCSC numbers)

Reproduced verbatim from `assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`. These are the parts JLCPCB places. **Confirm JLC part-match, polarity, and orientation at upload** — the LCSC numbers are locked but JLC still asks for final approval (per the package README).

| Comment / Value | Designator(s) | Footprint | Qty | LCSC | MFR Part # | Manufacturer | JLC Class | Notes |
|---|---|---|---:|---|---|---|---|---|
| 100nF 50V X7R ±10% 0805 MLCC | C1, C2, C3, C12 | C_0805_2012Metric | 4 | **C49678** | CC0805KRX7R9BB104 | YAGEO | Basic | Decoupling (MCP/Pico/NE555 VCC). |
| 100µF 16V ±20% SMD aluminum electrolytic, D6.3×L5.4mm | C11 | CP_Elec_6.3x5.4 | 1 | **C19184134** | CK1C101M-CRE54 | RS | Extended | **Polarized — verify + mark/orientation.** This is the NE555 watchdog timing cap `C_WDOG_TIMING`. |
| 10nF 50V X7R ±10% 0805 MLCC | C13 | C_0805_2012Metric | 1 | **C17702767** | C0805B103K500NT | TORCH | Extended | NE555 control-pin cap (`C_WDOG_CTRL`). |
| 10µF 16V X5R ±10% 0805 MLCC | C14 | C_0805_2012Metric | 1 | **C89827** | CC0805KKX5R7BB106 | YAGEO | Extended | 3V3 bulk (`C_3V3_BULK`). Verify DC-bias derating on the rail. |
| 1N4148WS switching diode, SOD-323 | D1, D3, D5, D7, D9, D11, D15, D16 | D_SOD-323 | 8 | **C118873** | 1N4148WS | onsemi | Extended | Relay-coil flyback (per populated relay) + the two NE555 timing/trigger diodes. |
| SS14 Schottky diode, SMA/DO-214AC | D17 | D_SMA | 1 | **C2480** | SS14 | MDD | Basic | Reverse-polarity protection on the 5 V input (`D_PROT`). |
| **G5LE-14 5VDC** SPDT relay, wave solder | K1, K2, K3, K4, K5, K6 | Relay_SPDT_Omron-G5LE-1 | 6 | **C116963** | G5LE-14 5VDC | Omron Electronics | Extended | **CRITICAL: 5 VDC coil. Do NOT substitute 9 / 12 / 24 V.** Switches dry contacts only. (K7 = M1 = DNP, see 23.A.4.) |
| MMBT3904 NPN BJT, SOT-23 | Q1, Q2, Q3, Q4, Q5, Q6, Q15, Q16 | SOT-23 | 8 | **C909754** | MMBT3904 | GOODWORK | Extended | Low-side relay-coil drivers (Q1–Q6) + the two safety-chain AND transistors (Q15=ARM, Q16=RP_OK). |
| 2N7002 N-channel MOSFET, SOT-23 | Q8, Q9, Q10, Q11 | SOT-23 | 4 | **C916396** | 2N7002 | JSMSEMI | Extended | Low-side status-LED drivers (1st/2nd/strike/foul). |
| AO3400A N-channel logic MOSFET, SOT-23 | Q12, Q13 | SOT-23 | 2 | **C20917** | AO3400A | Alpha & Omega Semicon | Basic | NE555 watchdog kick FET + watchdog-OK FET. |
| AO3401A P-channel MOSFET, SOT-23 | Q14 | SOT-23 | 1 | **C347476** | AO3401A | UMW | Extended | Relay-enable-rail pass element (`Q_RAIL`). |
| 4.7k 1% 1/8W 0805 | R1, R2 | R_0805_2012Metric | 2 | **C17673** | 0805W8F4701T5E | UNI-ROYAL | Basic | I²C SDA/SCL pull-ups (`R_I2C_SDA`, `R_I2C_SCL`). |
| 2.2k 1% 1/8W 0805 | R3, R5, R7 … R65 (32 refs) | R_0805_2012Metric | 32 | **C17520** | 0805W8F2201T5E | UNI-ROYAL | Basic | Opto-LED series resistors `Rin_*` (one per of the 32 input channels). |
| 10k 1% 1/8W 0805 | R4, R6, R8 … R66, R101–R109 odd (37 refs) | R_0805_2012Metric | 37 | **C17414** | 0805W8F1002T5E | UNI-ROYAL | Basic | Opto logic-side pull-ups `Rpu_*` + watchdog/AND-gate pull-ups. |
| 1k 1% 1/8W 0805 | R67, R70, R73 … R104 (12 refs) | R_0805_2012Metric | 12 | **C17513** | 0805W8F1001T5E | UNI-ROYAL | Basic | Relay base resistors `Rb_*` + LED gate resistors `Rgled_*` + watchdog gate resistors. |
| 100k 1% 1/8W 0805 | R68, R71, R74 … R110 (14 refs) | R_0805_2012Metric | 14 | **C149504** | 0805W8F1003T5E | UNI-ROYAL | Basic | Drive/gate pulldowns `Rpd_*`, `Rpdled_*`, rail-gate + watchdog timing/pulldowns (fail-safe-off). |
| 330R 1% 1/8W 0805 | R90, R93, R96, R99 | R_0805_2012Metric | 4 | **C17630** | 0805W8F3300T5E | UNI-ROYAL | Basic | Status-LED current-limit `Rled_*`. **Value provisional** — see 23.A.5 note. |
| **MCP23017** I²C I/O expander, SOIC-28-300mil | U1, U2, U3 | SOIC-28W_7.5x17.9mm_P1.27mm | 3 | **C47023** | MCP23017-E/SO | Microchip Tech | Extended | **CRITICAL: I²C MCP23017, NOT SPI MCP23S17.** U1=IN-A@0x20, U2=IN-B@0x21, U3=OUT-A@0x22. Run at 3.3 V. |
| **PC817B** optocoupler, DIP-4, wave solder | U4 … U35 (32 refs) | DIP-4_W7.62mm | 32 | **C5692981** | PC817B | UMW | Extended | One per input channel. Confirm DIP-4 orientation; CTR bin must work with the rev-B field resistors. |
| **NE555** bipolar timer, SOIC-8 | U36 | SOIC-8_3.9x4.9mm_P1.27mm | 1 | **C7593** | NE555DR | Texas Instruments | Extended | **Bipolar NE555** hardware watchdog. Do NOT swap to CMOS/TLC555 (timing changes). |

**JLC-placed line count: 20 sourcing lines.** (The per-line `Qty` column above is authoritative; the package-level non-DNP total of 189 also includes the hand-solder refs in 23.A.2.)

> **Anchor cross-check (all PASS against §1.10 and the netlist generator):** relay = **Omron G5LE-14, 5VDC, C116963** (not 12/24 V); expander = **MCP23017 I²C, C47023** (not SPI MCP23S17); opto = **PC817B, C5692981**; timer = **bipolar NE555DR, C7593**. No source disagrees.

#### 23.A.2 Hand-soldered / off-board-but-on-board parts (installed after PCBA)

Reproduced from `assembly/wsl-phase8b-revB-hand-solder-bom.csv`. These mount **on** the board but are installed by hand after the JLC PCBA returns (through-hole modules + Phoenix terminal blocks/headers that the Standard-PCBA flow does not place). They have **no LCSC number** because they are not in the JLC order.

| Ref | Qty | Role | Manufacturer | MFR Part # | Description | Status |
|---|---:|---|---|---|---|---|
| **A1** | 1 | RP2040 module | Raspberry Pi | **SC0915** | Raspberry Pi Pico, castellated module, **no pre-soldered headers** | Locked — program after assembly; **do not use Pico H/WH** (header pins). |
| **U37** (net `ISO_WET`) | 1 | Isolated field-wetting supply | TRACO Power | **TMA 0505S** | Isolated 5 V→5 V 1 W SIP DC/DC, 5 V 200 mA out | Locked exact part — do not substitute without pinout/isolation review. Source: DigiKey 1951-1003-ND. |
| J1 | 1 | Pi IDC/box header | CNC Tech (candidate) | 3020-20-0100-00 | 20-pos 2×10 2.54 mm vertical through-hole box/IDC header | **Candidate — verify shroud/key/pin-1** vs the KiCad footprint before ordering. |
| J2 | 1 | 5 V power terminal | Phoenix Contact | **1715734** | MKDS 1,5/3-5,08, 3-pos fixed screw terminal, 5.08 mm | Locked (footprint verify at order). Fixed terminal, no plug. |
| J3 | 1 | FAST field-input header | Phoenix Contact | **1843680** | MCV 1,5/10-G-3,5, 10-pos vertical PCB header, 3.5 mm | Locked. Order mating plug separately (see 23.A.3). |
| J4 | 1 | SLOW-A field-input header | Phoenix Contact | **1843729** | MCV 1,5/14-G-3,5, 14-pos vertical header, 3.5 mm | Locked. |
| J5 | 1 | SLOW-B field-input header | Phoenix Contact | **1843703** | MCV 1,5/12-G-3,5, 12-pos vertical header, 3.5 mm | Locked. |
| J6, J7, J8, J9, J10, J11 | 6 | Machine-output (relay) terminals | Phoenix Contact | **1715721** | MKDS 1,5/2-5,08, 2-pos fixed screw terminal, 5.08 mm | Locked (footprint verify). One per populated relay (S/T/SP/BE/M/M2). LCSC equiv C5183929 noted. |
| J13 | 1 | LED-lamp header | Phoenix Contact | **1843648** | MCV 1,5/6-G-3,5, 6-pos vertical header, 3.5 mm | Locked. |
| J14 | 1 | Safety-loop header | Phoenix Contact | **1843622** | MCV 1,5/4-G-3,5, 4-pos vertical header, 3.5 mm | Locked. |

> **Note — J12 is intentionally absent from this hand-solder list.** J12 is the **M1 (ball-return)** motion terminal; it is DNP (see 23.A.4). The six populated machine-output terminals are **J6–J11**, not J6–J12.
>
> **(VERIFY:** §1.10 left an open `(VERIFY: LCSC/MFR for TMA-0505S)` flag. **Resolved here:** U37 = TRACO Power **TMA 0505S**, hand-soldered, **no LCSC by design** because it is excluded from the JLC SMT upload. Treat the §1.10 flag as closed; the part is confirmed in `…-hand-solder-bom.csv`.**)**

#### 23.A.3 Harness mating parts & off-board hardware (not on the board)

Reproduced from `assembly/wsl-phase8b-revB-harness-mating-parts.csv` and `…-offboard-hardware.csv`. Order these with the harness, not with the board. Each Phoenix **MCV-G** header on the board mates with the corresponding **MC-…-ST** screw plug.

| Mates board ref | Qty | Manufacturer | MFR Part # | Description | Status |
|---|---:|---|---|---|---|
| J3 | 1 | Phoenix Contact | **1840447** | MC 1,5/10-ST-3,5, 10-pos 3.5 mm screw plug | Locked |
| J4 | 1 | Phoenix Contact | **1840489** | MC 1,5/14-ST-3,5, 14-pos 3.5 mm screw plug | Locked |
| J5 | 1 | Phoenix Contact | **1840463** | MC 1,5/12-ST-3,5, 12-pos 3.5 mm screw plug | Locked |
| J13 | 1 | Phoenix Contact | **1840405** | MC 1,5/6-ST-3,5, 6-pos 3.5 mm screw plug | Locked |
| J14 | 1 | Phoenix Contact | **1840382** | MC 1,5/4-ST-3,5, 4-pos 3.5 mm screw plug | Locked |
| J1 | 1 | CNC Tech (candidate) | 3030-20-0102-00 | 20-pos IDC socket for 2×10 2.54 mm ribbon | **Candidate — verify keying/strain-relief/pin-1.** |

**Mechanical / consumable (from `…-offboard-hardware.csv`, not BOM-counted):**

| Item | Qty/board | Notes |
|---|---:|---|
| M3 mounting hardware + standoffs (MK1–MK4) | 4 | Board holes are NPTH, excluded from BOM/POS; size standoffs for the enclosure. |
| Pi 2×10 IDC ribbon cable | 1 | Match J1 keying/orientation before harness build. |

> The board screw-terminals **J2 (5 V power)** and **J6–J11 (machine outputs)** are MKDS *fixed* terminals — they have **no off-board plug**; wires land directly in the screw clamp. Only the MCV-G headers (J3/J4/J5/J13/J14) take a plug.

#### 23.A.4 DNP — Do-Not-Populate footprints (present in copper, not assembled)

Reproduced from `assembly/wsl-phase8b-revB-dnp-excluded.csv`. **27 refs.** All carry `dnp + exclude_from_bom + exclude_from_pos_files` in the KiCad board, so they never reach the assembler. Two distinct reasons:

**(a) The M1 ball-return channel — 8 refs, unverified on these chassis.** M1 was never bench-confirmed as a separate relay on the SS+Omega-Tek chassis and the FSM does not drive it (§3/§21). The copper is kept so a future verified lane can populate it without a respin.

| Designator | Value | Footprint | Role |
|---|---|---|---|
| K7 | G5LE M1 DNP | Relay_SPDT_Omron-G5LE-1 | M1 relay |
| Q7 | MMBT3904 M1 | SOT-23 | M1 coil driver |
| R69 | 100R DNP | R_0805 | M1 snubber R |
| R85 | 1k | R_0805 | M1 base R |
| R86 | 100k | R_0805 | M1 drive pulldown |
| R87 | 100R DNP | R_0805 | M1 snubber R |
| D13 | 1N4148 | D_SOD-323 | M1 coil flyback |
| J12 | J_MOTION_M1 5.08mm | TerminalBlock MKDS-1,5-2-5.08 | M1 output terminal |

**(b) Arc-suppression footprints on the motion outputs — value-DNP by default.** Each motion-output contact has an RC snubber (100R + 10nF X2) and an MOV footprint, populated **only after** at-machine inductive-load characterization (§5 / `phase8b_pcb_revB_BOM_power.md` §2.5).

| Designators | Value | Footprint | Role |
|---|---|---|---|
| C4, C5, C6, C7, C8, C9, C10 | 10nF X2 DNP | C_0805 | Contact-snubber caps `Csnub_*` (S/T/SP/BE/M/M2 + M1) |
| R72, R75, R78, R81, R84 | 100R DNP | R_0805 | Contact-snubber resistors `Rsnub_*` |
| D2, D4, D6, D8, D10, D12, D14 | MOV DNP | D_SMA | Contact MOVs `MOV_*` |

> **Reading the lists together:** the snubber/MOV refs for S/T/SP/BE/M/M2 are DNP because the suppression network is *deferred*, while the M1-channel refs (incl. its own snubber R69/R87 and cap C10) are DNP because the *whole channel* is deferred. C10 appears under the snubber group but belongs to the M1 channel.

#### 23.A.5 Mechanical & test refs (real copper, no purchased part)

The 20 `excluded_non_dnp_refs` are not in any assembly file but exist on the board. Useful to know when probing during bring-up (§21).

| Group | Refs | What |
|---|---|---|
| Mounting holes | MK1–MK4 | M3, 3.2 mm NPTH |
| Test pads (16) | TP1–TP16 | Bring-up probe points (see table below) |

**Test-point map (from `…-dnp-excluded.csv`, the `Value` column = the net each pad taps):**

| TP | Net | TP | Net |
|---|---|---|---|
| TP1 | VCC_5V | TP9 | WDOG_TIMING_NODE |
| TP2 | GND | TP10 | NE555_TRIG |
| TP3 | VCC_3V3 | TP11 | NE555_OUT |
| TP4 | FIELD_WET_V | TP12 | WDOG_OK_PULLDOWN |
| TP5 | FIELD_GND | TP13 | ARM_PERMIT |
| TP6 | I2C_SDA | TP14 | RP2040_OK |
| TP7 | I2C_SCL | TP15 | SAFE_STOP_RETURN |
| TP8 | WDOG_KICK | TP16 | RELAY_ENABLE_RAIL |

> **Bring-up tip (ties to §19/§21):** TP1/TP2/TP3/TP5 verify the rails and the GND↔FIELD_GND isolation (TP2 vs TP5 must show no continuity). TP8–TP12 walk the NE555 watchdog. TP13/TP14/TP16 verify the relay-enable-rail AND chain: TP16 (the rail) should be dead unless ARM (TP13) **and** RP2040_OK (TP14) **and** the watchdog **and** the external J_SAFETY loops are all satisfied.

#### 23.A.6 Provisional / unconfirmed BOM values

Carried forward from `phase8b_pcb_revB_BOM_power.md` §6 — these are *measurements still owed*, not design unknowns; they do not block bare-PCB fab but must be settled before final population:

- **Status-LED current-limit `Rled_*` (R90/R93/R96/R99, currently 330R)** — final value set after choosing LED type/brightness for a lit center. `(VERIFY: 330R is provisional; lock Rled_* after LED selection.)`
- **Motion-relay contact rating / snubber-MOV population** — pending at-machine S/T/SP/BE/M coil-control current measurement. The G5LE 10 A contact has huge margin; the snubber/MOV values are placeholders until the inductive load is characterized. `(VERIFY: snubber R/C and MOV clamp values vs measured contact load before populating C4–C10 / R72–R87 / D2–D14.)`
- **J1 Pi header + its ribbon socket** — both flagged "candidate," keying/pin-1 to be confirmed against the footprint. `(VERIFY: J1 / 3020-20-0100-00 + 3030-20-0102-00 body, keying, pin-1 before ordering.)`

---

### 23.B Appendix B — Consolidated Cam-Timing Reference

**Authoritative source:** `docs/phase8_8270_SYSTEM_REFERENCE.md` §3 (mined from the *8270 MP Operation Training Manual*, PN 610000009, and the *8270 Service & Parts Manual*, PN 610007028). Firmware GPIO mapping from `firmware/rp2040/config.h`; FSM consumption in `lane_node/cycle_control_8270.py` (see §3 / §15 / §21).

The 82-70 sequences the table and sweep by reading rotating **timing cams** — each cam lobe trips a microswitch at a specific shaft angle. There are **six cams** the controller reads (3 sweep: SA/SB/SC; 3 table: TA1/TA2/TB) plus a **3-second pin-settle time delay** gated by **GP**. On the 82-70 these cam-position *stops* are **controller logic** (read the cam, drop the relay) — **not** a hardwired motor latch — so the Pi/RP2040 times them; the TB/SC interlock and regenerative braking are the independent **hardware** backstops (§19).

#### 23.B.1 Master cam table (angle · role · GPIO · sense)

| Cam | Group | Trips at (shaft °) | Role in the cycle | RP2040 GPIO | Pico pin |
|---|---|---|---|---|---|
| **SA** | Sweep | **270°** and **360° / zero** | Stop sweep **run-through @270°**; stop sweep **@360°/zero** | **GP6** | 9 |
| **SB** | Sweep | **66°** and **186°** | **Guard stop @66°** (sweep forward limit); **initiate table spotting @186°** | **GP7** | 10 |
| **SC** | Sweep | **86°–243°** (window) | Sweep-under-table window → **table/sweep INTERLOCK** (hardware) | **GP8** | 11 |
| **TA1** | Table | **355°** (and **185°**) | **Table-zero stop @355°**; **@185° resets the 3-s time delay** + flips ball-cycle memory | **GP9** | 12 |
| **TA2** | Table | **260°** | **Initiate sweep run-through**; **latch pin lamps** (legacy 12 VDC / KX to scorer); **ball vs strike decision** | **GP10** | 14 |
| **TB** | Table | **105°–255°** (window) | Table-sweep interference window → **table/sweep INTERLOCK** (hardware) | **GP11** | 15 |
| *(3-s time delay)* | — | 3 s, gated by **GP** closed | **Pin-settle** dwell between sweep-guard and table descent | *(software/RP2040 timed)* | — |

**Ball-detect inputs (not cams, but on the same fast/RP2040 bank, included for completeness — `config.h`):**

| Input | Role | RP2040 GPIO | Pico pin |
|---|---|---|---|
| **DIELL-L** | Ball detect, **left** beam — the **cycle trigger** (replaces the OEM cushion start switch "SS") | **GP12** | 16 |
| **DIELL-R** | Ball detect, **right** beam | **GP13** | 17 |

> **Electrical sense (all 8 fast inputs):** opto-isolated and **ACTIVE-LOW at the Pico** — machine contact **closed / asserted ⇒ GPIO LOW**; idle is HIGH via an on-board 10k pull-up to 3V3 (`generate_kicad_netlist_revB.py` `opto_input()`; `config.h` header). Cams are **dry contacts, normally-closed at rest** per the at-machine measurement (field result A4).

#### 23.B.2 Where each cam fires within the cycle of operation

The cam roles above drive these four cycle types (full narrative in `phase8_8270_SYSTEM_REFERENCE.md` §2 and manual **§3, The AMF 82-70 Machine & Control Theory**):

| Cycle | Cam sequence (abridged) |
|---|---|
| **First ball** | trigger (DIELL/SS) → sweep to **SB 66°** guard → **3-s delay** (GP) → table descends → grippers read standing pins → **TA2 260°** latches pin lamps + "ready" → sweep to **SA 270°** → table runs through **TA1 185–355°** (@185° delay resets, ball-memory flips 1st→2nd) → sweep returns to **SA 360°** stop → table stops at zero. |
| **Second ball** | ball-memory inverted; sweep→**SB 66°**→delay→**run-through to SA 270°**; after the 10th pin to the bin **BS** closes → **SP** spot relay → table spotting revolution → sweep→**SA 360°** → ball-memory resets (→1st). |
| **Strike** | as first ball but **no pins** (all GS open); at **TA2 260°** the **strike memory** sets → strike lamp + hold table at 360° for spotting → spot + sweep as 2nd ball → strike memory resets when sweep+table reach zero. |
| **Foul** | foul detector (Radaray) → foul lamp + logic → sweep→**SB 66°** → **foul memory** holds table → sweep run-through to **SA 270°** → **BS** → table spotting → ball-memory flips (→2nd ball). |

#### 23.B.3 Cam-stop overrun — deferred firmware item (read before relying on the table)

The **angle values** above are authoritative from the manuals, but **which edge (rising/falling) of a given cam input corresponds to which angle on our specific chassis is NOT yet confirmed.** Consequently:

- Firmware **v0.1.0** does **not** enforce cam-stop *overrun* (a stop-cam firing while a motor is still RUNNING and the Pi failing to STOP it in time → drop RP2040_OK). That feature is **deferred to firmware v1.1** and is bench-gated on the per-cam edge→angle polarity (`config.h` "DEFERRED to v1.1"; `main.c` safety-model header; cutover runbook §3.2).
- What v0.1.0 *does* provide as the UART-independent backstop is the **motion max-run timeout = 8000 ms** (`MAX_MOTION_MS`, matching `cycle_control_8270.MAX_MOTION_S = 8.0 s`): any guarded motor marked RUNNING longer than this latches a fault and drops the rail. **BE (continuous)** and **M (master)** are **not** guarded.

> `(VERIFY: per-cam edge→angle polarity (which logic edge = which shaft angle) is unconfirmed on the SS+Omega-Tek chassis — it is a cutover-day field measurement and the precondition for the v1.1 cam-stop-overrun feature. Do not hand-derive it from this table.)`

---

### 23.C Appendix C — Glossary & Acronym List (expanded)

This expands the seed in **§1.11**. Entries already defined there are not repeated in full; the additions below are the parts/nets/tooling terms that recur in the BOM, cam-timing, layout, firmware, and runbook chapters. Where a term's deep figures live outside the named live files, that is flagged.

| Term | Expansion / meaning |
|---|---|
| **PCBA / Standard-PCBA** | Printed Circuit Board **A**ssembly — a populated board. **JLCPCB "Standard-PCBA"** is the specific assembly service tier used here; it places the SMT parts plus the wave-solderable PC817 optos and G5LE relays. A1/U37/connectors are excluded and hand-soldered. |
| **BOM / CPL** | **B**ill **o**f **M**aterials (the part list) / **C**omponent **P**lacement **L**ist (a.k.a. POS / pick-and-place file — XY position + rotation + side for each placed part). The JLC upload is a BOM+CPL pair. |
| **DNP** | **D**o **N**ot **P**opulate — footprint in copper, no part fitted. Rev-B: the M1 channel (8 refs) + value-DNP snubber/MOV (19 refs) = 27 total. See 23.A.4. |
| **LCSC** | The component distributor whose part numbers (e.g. `C116963`) JLCPCB uses to source the BOM. An LCSC number locks the exact part. |
| **JLCPCB** | The PCB fab + assembly house the rev-B board is built at. |
| **POS file** | See CPL — the pick-and-place / position file. `exclude_from_pos_files` keeps a footprint out of it. |
| **Gerber / drill (PTH/NPTH)** | The fab artifacts: Gerber = copper/mask/silk layer images; drill = hole file. **PTH** = plated through-hole, **NPTH** = non-plated (the 4 mounting holes). |
| **DRC** | **D**esign **R**ule **C**heck — KiCad's verification that the board meets clearance/width/connectivity rules. The fab gate is **0 violations / 0 unconnected / 0 footprint errors** under the conservative `.kicad_dru` rules. |
| **`.kicad_dru`** | The custom KiCad design-rule file that encodes the creepage/clearance contract (LOGIC↔FIELD ≥2.5 mm, LOGIC↔MACHINE ≥3.2 mm, output↔output ≥1.5 mm — conservatively sized for 250 VAC even though the field measured 24 VAC). |
| **net class** | A KiCad grouping of nets sharing routing rules. Rev-B has **5**: Logic_Signal (80 nets), Logic_Power (4), Safety_Rail (13), Field_Sense (66), Machine_Output (21) = all 184 nets, 0 anonymous. |
| **domain (FIELD / LOGIC / MACHINE)** | The three physically banded regions of the board, separated by no-copper gutter keepouts, that keep the isolated machine-sense, logic, and switched-output sections apart. See §5 / §13. |
| **G5LE-14** | The Omron SPDT signal relay, **5 VDC coil** (~79 mA), 10 A contact, used for all motion outputs. Switches a *dry contact* in an existing machine control circuit; never carries motor current. (K1–K6 populated, K7/M1 DNP.) |
| **MCP23017** | Microchip **I²C** 16-bit GPIO expander (SOIC-28W). 3 per board at addresses 0x20 (IN-A), 0x21 (IN-B), 0x22 (OUT-A); a 4th address 0x23 (OUT-B) is reserved for optional physical pin lamps, not populated. Run at **3.3 V** for Pi-safe I²C. **Not** the SPI MCP23S17. |
| **PC817B** | The DIP-4 phototransistor optocoupler isolating every machine input. Logic side 3.3 V, **active-low at the MCU**. 32 per board. |
| **NE555 (bipolar)** | The 8-pin bipolar timer IC (`NE555DR`) used as the hardware watchdog monostable. **Bipolar specifically** — a CMOS/TLC555 would change the timing. |
| **TMA-0505S** | TRACO Power isolated 5 V→5 V 1 W SIP DC/DC (ref **U37** / net `ISO_WET`) that generates the isolated **field-wetting** rail. Keeps FIELD_GND galvanically off logic GND. Hand-soldered (no LCSC). |
| **MMBT3904 / 2N7002 / AO3400A / AO3401A** | The small transistors: **MMBT3904** NPN = relay-coil drivers + safety-chain AND gates; **2N7002** N-FET = status-LED low-side drivers; **AO3400A** N-FET = watchdog kick/OK FETs; **AO3401A** P-FET = the relay-enable-rail pass element. |
| **SS14** | The SMA Schottky diode (ref D17 / net `D_PROT`) providing reverse-polarity protection on the 5 V input. |
| **1N4148WS** | The SOD-323 small-signal diode used for relay-coil flyback (per relay) and the two NE555 timing/trigger diodes. |
| **VSYS** | The Raspberry Pi Pico's main 5 V system-input pin (module pin 39). The board feeds the logic 5 V rail into VSYS; the Pico's on-board regulator supplies the 3V3 rail. |
| **uart0 / 115200 8N1** | The Pi↔RP2040 serial link: hardware UART0 on **GP0 (TX) / GP1 (RX)**, 115200 baud, 8 data / no parity / 1 stop. The RP2040 **pushes** edge events; the FSM consumes them (no polling). |
| **RP2040_OK** | The RP2040's fail-safe-low rail-permission output (**GP2**). HIGH only when firmware is healthy and past `BOOT_SETTLE_MS`; Hi-Z (unpowered/reset) → external 100k pulldown → rail dead. A first-class safety-rail condition. |
| **relay-enable rail (`RELAY_ENABLE_RAIL`)** | The hardware-gated coil supply for the on-board relays (16 nodes incl. TP16). Passes through the AO3401A only when the series AND chain (ARM · RP2040_OK · NE555-OK) **and** the external J_SAFETY loops (TB/SC, Stop/CIS) are all satisfied. Software cannot bypass it. |
| **ARM / ARM_PERMIT** | The Pi GPIO permission (one AND-chain input) asserted only in a verified operator-safe state; part of replicating the OEM "Power-Down / require First Ball Zero on power restore" rule. |
| **watchdog kick (`WDOG_KICK`)** | The Pi-driven pulse (lane_node GPIO12) that pets the NE555 monostable. A missed kick times out and drops the rail. Independent of the RP2040's own hardware watchdog. |
| **GND vs FIELD_GND** | Logic ground vs the isolated machine-sense ground. They share **0 nodes** (verified: GND=92 nodes, FIELD_GND=6 nodes) — the isolation barrier is intact and only crosses inside the opto/relay/DC-DC packages. |
| **FIELD_WET_V** | The isolated wetting voltage (from the TMA-0505S) applied through a closed dry contact to assert an input. Returns to FIELD_GND. |
| **J_PI / J_PWR / J_FAST_IN / J_SLOW_IN_A / J_SLOW_IN_B / J_MOTION_* / J_LAMP_LED / J_SAFETY** | The board's **function-named** connectors (refs J1, J2, J3, J4, J5, J6–J12, J13, J14). A per-chassis adapter harness maps these to C1/C2A cavities at cutover. Pinouts in §11. |
| **OUT-A / IN-A / IN-B / OUT-B** | The four MCP23017 roles by I²C address: **IN-A@0x20** (grippers GS1–10 + GP/OS/BS/PBZ/PBC/Foul), **IN-B@0x21** (10th frame, manual T/S/SWS/SWSR, aux/spare), **OUT-A@0x22** (7 relay drives + 4 status lamps), **OUT-B@0x23** (optional physical pin lamps — not populated; camera supplies pin data). |
| **MOTION_RELAYS** | The output names treated as motors (S, T, SP, BE, M, M1, M2) — these get RUN/STOP sent to the RP2040 so its max-run backstop knows what is energized. The 4 lamp outputs are **not** motors. |
| **RecordingIO / MachineIO** | The two `io` implementations in `controller_io.py`: **MachineIO** = real hardware (MCP23017s + RP2040 + watchdog kick); **RecordingIO** = no-hardware fake for off-Pi FSM testing. The FSM is written against the abstract `io` interface so either plugs in. |
| **OUTPUT_PINS / SLOW_INPUT_PINS / FAST_INPUTS** | The authoritative pin-assignment dicts in `generate_kicad_netlist_revB.py`. `controller_io.py` re-derives its bit maps from these at import and **fails on drift** (the guard that caught the BS/OS, M1/M2, strike/foul swaps). |
| **Radaray (foul detector)** | The OEM foul-line detector; its signal is the **Foul** input (IN-A) and lights the foul status lamp. |
| **BS (bin switch) / GP / OS** | Machine slow inputs: **BS** = #9-bin "all 10 pins arrived" switch (gates spotting); **GP** = the gate/pin switch that gates the 3-s settle delay; **OS** = (out-of-range / over-stroke style) machine switch. (Exact OS semantics per chassis — `(VERIFY: precise OS switch meaning against an OEM source; the netlist treats it as a generic slow input on IN-A.)`) |
| **PBZ / PBC** | Pushbuttons: **PBZ** = zero / 1st-2nd-ball / manual-intervention; **PBC** = cycle. Both on IN-A. |
| **VIXLW dongle** | The owned USB composite-video capture device (UVC "USB Video" class) that reads the T-Camera for Track A. (Seed §1.11.) |
| **`.uf2`** | The RP2040 firmware binary format. v0.1.0 cross-builds to ~24 KB flash / 2.6 KB RAM (`firmware/rp2040/build.ps1`). |
| **IPC-D-356** | The netlist-export format (`reports/wsl-phase8b-revB.ipc`) the fab uses for bare-board electrical test. |

> **Carried-over flag from §1.11 (unchanged):** the **DIELL** ball-detector's exact rest/broken voltages (≈16 V rest / ≈0.7 V broken, NPN active-low) live in project memory `project_amf_8270_interface_research`, **not** in the named live files. `(VERIFY: 16 V rest / 0.7 V broken figures against a live source before relying on exact voltages.)` The **active-low, contact-closed-asserts** sense *is* confirmed in the live netlist generator.

---

### 23.D Appendix D — Document & Artifact Index (where the deep detail lives)

This maps every source document, script, runbook, and key artifact to what it authoritatively covers, and to the manual section that summarizes it. **Paths are relative to `C:\Users\Dylan DeYoung\wsl-lane-nodes\`.** This index is the answer to "the manual mentions X — where is the primary source?"

#### 23.D.1 Sources of truth (live files — these win over the manual)

| File | Authoritative for | Manual section |
|---|---|---|
| `scripts/generate_kicad_netlist_revB.py` | **As-built board wiring** — the single source of truth for every pin/net/part assignment (FAST_INPUTS, SLOW_INPUT_PINS, OUTPUT_PINS, all blocks). | §5, §11, §12 |
| `firmware/rp2040/config.h` | RP2040 pin map (GP6–GP13 fast, GP2 RP_OK, GP0/1 UART), timing constants, baud. Derived from the netlist generator. | §15, §12, 23.B |
| `firmware/rp2040/main.c` | RP2040 firmware behavior: edge-push protocol, RP_OK fail-safe model, max-run backstop, watchdog, deferred v1.1 hooks. | §15 |
| `lane_node/controller_io.py` | Pi-side hardware `io` object: MCP23017 addresses + **OUT_A_MAP / IN_A_MAP** bit maps (current+correct), gripper read, watchdog/arm, the generator drift-guard. | §5, §12 |
| `lane_node/cycle_control_8270.py` | The controller **FSM** (states, cam handlers, time delays, MAX_MOTION_S). | §3, §21 |
| `kicad/fab_revB_routed_manual/assembly/*.csv` | The **BOM/CPL/DNP/hand-solder/harness** part lists (locked LCSC numbers). | §10, 23.A |
| `kicad/fab_revB_routed_manual/manifest.json` | Official package counts + SHA256 integrity for every fab artifact. | §10, §13, 23.A |
| `docs/phase8b_pcb_revB_spec.md` | The **hard electrical contract**: domains, safety rail, output topology, inputs, connectors, power, M1-DNP ruling. (Audit-trail header blocks = decision history.) | §5, §19 |
| `docs/phase8_8270_SYSTEM_REFERENCE.md` | Controller behavioral spec: machine, FSM sequence, **cam timing (§3)**, I/O (§4), safety (§5), connectors (§4). | §3, §19, 23.B |

#### 23.D.2 Design / decision docs (PCB rev-B)

| File | Covers |
|---|---|
| `docs/phase8b_pcb_revB_BOM_power.md` | Pre-SKiDL parts contract + power-rail plan + the at-machine fab-lock measurement inputs (A1 24 VAC, A3 lamp supply, A4 dry cams) + the logic-LED decision. **Primary source for relay/wetting/LED part rationale.** |
| `docs/phase8b_pcb_revB_netclass_creepage.md` | The routing contract: 5 net classes, 4-layer stack, domain rooms, plane keepouts, creepage/clearance policy (conservative 250 VAC; relaxable to 24 VAC). |
| `docs/phase8b_revB_netclass_inventory.md` | All 184 nets mapped to domains; 0 unknown nets. |
| `docs/phase8b_revB_route_pass1_findings.md` | Routing status + **every Claude/Codex audit verdict** + the FreeRouting-rejection log + the false-green netclass catch. |
| `docs/phase8b_revB_fab_order_checklist.md` | The bare-PCB order checklist (Gerber preview vs review PDF, etc.). |
| `docs/phase8b_revB_pcba_parts_worklist.md` | PCBA parts work tracking. |
| `docs/phase8_channel_allocation.md` | ⚠️ **GPIO column is STALE** (says GP0–GP7). Useful for channel *intent*, but for GPIO numbers use `config.h` (GP6–GP13). |

#### 23.D.3 Field & bench characterization (the 82-70 reality)

| File | Covers |
|---|---|
| `docs/phase8b_at_machine_fieldsheet.md` | The completed at-machine field session results (A1/A3/A4 voltages, gripper chassis-return correction, Stop/CIS, TB/SC). |
| `docs/phase8b_at_machine_HOWTO_companion.md` | How the field session was run (procedure companion). |
| `docs/phase8b_field_concepts_primer.md` | Field-concepts primer for the session. |
| `docs/phase8_bench_session1_FINDINGS.md` | Bench (spare cabinet) characterization: C1/C2A roles, coil voltages, relay IDs. |
| `docs/phase8_bench_JOB2_camstop.md`, `…JOB3_C2A_inputs.md` | Bench jobs: cam-stop logic test; C2A input characterization (incl. the gripper chassis-return finding). |
| `docs/phase8_bench_C1map_worksheet.md`, `phase8_C1_C2A_pinout_p288.md` | C1/C2A machine-side pin mapping worksheets (foldout p288). |
| `docs/phase8_oem_doc_audit_2026-06-02.md` | OEM manual mining + OEM-vs-bench reconciliation (the chassis divergences). |
| `docs/phase8_controller_interface_MAP.md`, `…_fieldsheet.md` | Controller interface mapping + fieldsheet. |

#### 23.D.4 Runbooks & plans (operational)

| File | Covers | Manual section |
|---|---|---|
| `docs/phase8_trackA_golive_runbook.md` | **Track A scoring go-live** on the Pi at 21/22 (empty-ref capture → `--test` → camera mode → soak). The only currently-live procedure. | §18 |
| `docs/phase8_trackB_controller_cutover_runbook.md` | **Track B controller swap** cutover: lockout/tagout, staged rail-disabled bring-up, go/no-go gates, rollback, and the consolidated deferred field captures (gripper labels, cam polarity, J_SAFETY terminals). | §21 |
| `docs/phase8_pi_provisioning.md` | **Pi node provisioning**: `config.txt` boot overlays (the 2nd I²C bus + 2nd UART), focused pinned deps (`requirements-lane-node.txt`), installing both systemd units, the Pi-GPIO pin table + the **Track-A coexistence constraint** (`Conflicts=lane-node.service`), and the `systemctl enable` trap. | §17 (Pi daemon), §20 (operations) |
| `docs/phase8_PLAN_A_full_replacement.md`, `phase8_PLAN_B_scoring_first.md` | The Plan A (full controller replacement) vs Plan B (scoring-first) fork analysis. | §1 |
| `docs/phase8_8270_replacement_plan.md` | The 82-70 replacement plan overview. | §1 |
| `firmware/rp2040/README.md` | Firmware v0.1.0: authoritative pin map, UART event/command protocol, Pi-side integration contract, fail-safe model, bench bring-up checklist. | §15, §21 |

#### 23.D.5 Track A (camera scoring) artifacts

| File | Covers | Manual section |
|---|---|---|
| `lane_node/pin_detect.py` | The difference-from-empty pin detector: 20 PIN_SPOTS_PX, MIRROR, DECK_TO_LANE={L:21,R:22}, DET_THR=38. | §18 |
| `lane_node/camera.py` | Camera capture + dual-deck → lane mapping + safe `None`→manual fallback. | §18 |
| `lane_node/lane_node.py` | The lane-node daemon wiring camera/scoring/server together. | §18, §7 |
| `docs/phase8_tcamera_pin_detect_plan.md`, `phase8_camera_frame_capture_guide.md`, `phase8_trackA_calibration_progress.md` | Pin-detect method, frame-capture guide, calibration progress. | §18 |
| `wsl_scoring_engine.py`, `wsl_scoring_display.html` | The scoring engine + the HTML scoring display. | §18, §7 |

#### 23.D.6 Generated fab package (`kicad/fab_revB_routed_manual/`)

| Artifact | Use |
|---|---|
| `wsl-phase8b-revB-gerber-drill.zip` | **Bare-PCB fabrication upload** (Gerbers + Excellon PTH/NPTH). |
| `wsl-phase8b-revB-jlc-standard-pcba-upload.zip` | Gerbers + the clean JLC Standard-PCBA BOM/CPL pair. |
| `JLC_UPLOAD_READY/` (+ `…-JLC_UPLOAD_READY.zip`) | Short, upload-order filenames (01 gerbers, 02 BOM, 03 CPL, 04 part-lock, 05 excluded, 06 hand-solder, 07 harness). *Use the files inside; do not upload the transport zip as the Gerber file.* |
| `review/wsl-phase8b-revB-review-layers.pdf` | Human layer-by-layer review PDF — **compare against the vendor Gerber preview before ordering**. |
| `reports/DRC-revB-routed-manual-fab.rpt`, `reports/audit-revB-board.log` | The in-package DRC (0/0/0) + board-audit (ALL PASS) gates. |
| `reports/board-stats.txt` / `.json` | Board statistics (250×225 mm, 4 layer, 236 footprints, pad/via/drill counts). |
| `README-fab-package.txt`, `manifest.json` | Package guide + counts/SHA256s. |

#### 23.D.7 Project-state / handoff docs (orientation)

| File | Covers |
|---|---|
| `docs/phase8_session_close_2026-06-03.md` | **Current live state** (this manual's "as-of"): rev-B routed + bare-PCB fab package generated, field session complete, firmware v0.1.0 written/tested, the Claude↔Codex audit loop, locked decisions. |
| `docs/HANDOFF.md` | Deeper background + mixed-fleet reality + artifact index. |
| `docs/phase8_status_2026-05-30.md`, `phase8_session_close_2026-06-01.md` | Earlier status snapshots (superseded by 06-03). |
| `README.md` (repo root) | Repository orientation. |

> ⚠️ **Stale-source warnings (do not trust these columns/sections):** (1) `docs/phase8_channel_allocation.md` §2 GPIO column = GP0–GP7 — **WRONG**, use `config.h` (GP6–GP13). (2) `docs/pcb_design_spec.md`, `docs/phase8_io_board_spec.md`, and the parts of `phase8_channel_allocation.md` describing an external AEDIKO/AL-ZARD carrier board — **superseded** by the fully-integrated rev-B (`phase8b_pcb_revB_spec.md`). (3) The network IP `192.168.86.36` anywhere in older docs — **dead**; WSL-SRV is now `192.168.4.103`.

---

### 23.E Appendix E — Change Log (stub)

This is a stub to be maintained going forward. Record every change to **this manual** and every change to the **rev-B board / firmware / FSM** that invalidates a table above (a new part number, a re-routed net, a GPIO change, a cam-polarity confirmation, a DNP populate/depopulate). Cite the live source and its SHA256 (from `manifest.json`) where applicable.

| Date | Rev | Area | Change | Source / commit | Author |
|---|---|---|---|---|---|
| 2026-06-04 | manual r0 | §23 | Initial appendices authored: full BOM (JLC-placed + hand-solder + harness + DNP + test pads), consolidated cam timing, expanded glossary, document index, change-log stub. Grounded in the `2026-06-04T14:42:42` fab package + netlist generator + `config.h` + `controller_io.py` + SYSTEM_REFERENCE §3. | `kicad/fab_revB_routed_manual/manifest.json`; `scripts/generate_kicad_netlist_revB.py`; `firmware/rp2040/config.h` | (manual) |
| *(pending)* | — | firmware | Cam-stop **overrun** enforcement (v1.1) once per-cam edge→angle polarity is confirmed at cutover. Update 23.B.3. | `phase8_trackB_controller_cutover_runbook.md` §3.2 | — |
| *(pending)* | — | BOM | Lock `Rled_*` (status-LED current-limit) value after LED selection; populate snubber/MOV (C4–C10 / R72–R87 / D2–D14) after at-machine contact-load measurement. Update 23.A.1 / 23.A.4 / 23.A.6. | `phase8b_pcb_revB_BOM_power.md` §6 | — |
| *(pending)* | — | BOM | Confirm/replace **J1** Pi header + ribbon socket candidates (3020-20-0100-00 / 3030-20-0102-00). Update 23.A.2 / 23.A.3. | `…-hand-solder-bom.csv` / `…-harness-mating-parts.csv` | — |
| *(pending)* | — | board | If `.kicad_dru` creepage is relaxed 250 VAC → 24 VAC (measured) for a future shrink/spin, re-run DRC + `export_fab_revB.py` and bump the BOM/board rev. Update §13 + 23.A counts. | `phase8b_pcb_revB_netclass_creepage.md` §3 | — |

---

*End of §23. Cross-referenced sections: §1 (System Overview & glossary seed), §3 (AMF 82-70 Machine & Control Theory), §5 (Rev-B Controller Board), §19 (Safety Architecture), §18 (Track A — Camera Scoring), §15 (RP2040 Firmware), §21 (Track B Bring-up & Cutover), §11 (Connector Pinouts), §12 (Channel Maps), §13 (Layout & Manufacturing).*


