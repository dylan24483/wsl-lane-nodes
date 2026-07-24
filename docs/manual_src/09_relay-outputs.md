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

All seven relay coils' high sides connect to `RELAY_ENABLE_RAIL` (including DNP M1). The pass-FET conducts only when the implemented on-board gates are satisfied — Watchdog OK, Arm OK, RP2040 OK/cam-stop, and Stop/CIS; Candidate C closes the PCB's J_SAFE1-2 design position with the controlled jumper. Primary TB/SC protection does **not** come from that rail position on lanes 21/22: the OEM parallel-safe contacts remain in the S/T coil circuits and every board insertion must pass G3. Any failed on-board gate collapses every board relay coil; both levers BACK/open independently block S and T when insertion is correct.

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
3. **Safety connector form** — TB/SC is resolved as Candidate C (controlled J_SAFE1-2 jumper + OEM ladder + per-lane G3); confirm the separate Stop/CIS J_SAFE3-4 landing (see **Section 10**).
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

1. Power rails up; confirm `VCC_5V` and that `RELAY_ENABLE_RAIL` is **dead** until the implemented on-board conditions are satisfied (watchdog kicked, arm asserted, RP2040 OK, controlled J_SAFE1-2 jumper installed, Stop/CIS loop closed).
2. Verify the on-board fail cases first: drop watchdog, ARM, RP2040_OK, and Stop/CIS one at a time. Opening J_SAFE1-2 at the bench proves only the PCB's unused loop position, **not** Candidate-C machine protection. Prove TB/SC separately at the live per-lane G3 gate: board commands S then T; both levers BACK/open must leave each contactor coil dead.
3. With the rail enabled, command each relay output **one at a time** from the controller and confirm continuity COM↔NO closes at the matching `J_MOTION_<name>` terminal **into a dummy load**, not the live machine.
4. Confirm the per-channel fail-off: with the rail up, drive OUT-A low (or pull the expander) and confirm the contact opens (100 k base pull-down holds the MMBT3904 off).
5. Characterize the real coil-circuit load per output at the machine, **then** decide and populate the snubber/MOV per channel (§9.5).
6. Only after all of the above, connect the machine harness.

Test points exist for relay coil drive, relay common, relay NO, and relay state per the layout contract (`phase8b_pcb_revB_spec.md` §3.2, §9), plus TP16 on `RELAY_ENABLE_RAIL`.

---

**Cross-references:** Safety rail and welded-contact limitation — **Section 10**. MCP23017 OUT-A device, I²C addressing, and the controller `io` object — **Section 7**. RP2040 RUN/STOP coupling, `MAX_MOTION_MS` motion backstop, and `RP2040_OK` rail permission — **Section 7 / the RP2040 co-processor section**. Status-lamp LED drivers that share OUT-A but are not relays — **Section 10**. NE555 watchdog that feeds the rail — **Section 10**. `(VERIFY: final manual section numbering once the full TOC is assembled.)`
