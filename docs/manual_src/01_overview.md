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
