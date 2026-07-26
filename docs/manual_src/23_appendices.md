## 23. Appendices: Full BOM, Cam Timing, Glossary & Document Index

> **What this chapter is.** Reference tables you will reach for repeatedly: the complete per-part bill of materials for one rev-B controller board (split into what the contract manufacturer places, what you hand-solder, and what is intentionally left off), the consolidated AMF 82-70 cam-timing table, an expanded glossary, and an index of every source document/script/runbook so you know where the deep detail lives. It is grounded in the live fab-package CSVs, the board netlist generator, the firmware pin map, and the controller behavioral spec.
>
> **Accuracy convention (unchanged from §1).** Every part number, designator, pin, net name, and value below is copied from a live source file. The authoritative sources are named at the head of each appendix. **When this manual and a live source disagree, the live source wins.** Anything not confirmable from a source is flagged inline as `(VERIFY: …)` — treat those as work items, not facts.
>
> **Scope reminder (from §1.5 / §5).** The BOM is for **one** controller board = **one lane**. A lane *pair* uses **two** identical boards on one Raspberry Pi, so multiply every board-level quantity by 2 for a pair and by 32 for the whole center. The Raspberry Pi itself, the T-Camera, and the USB capture dongle are pair-level / shared and are **not** on this board BOM.

---

### 23.A Appendix A — Full Bill of Materials (rev-B controller board, one lane)

> **HISTORICAL REV-B BOM — NOT A REV-D ORDER SOURCE.** Current Rev-D/r7 uses
> exactly forty 47 kΩ `Rpu_*` refs (`R4,R6,…,R82`), UNI-ROYAL
> `0805W8F4702T5E` / LCSC C17713. Unrelated 10 kΩ networks remain unchanged.
> Use `kicad/fab_revD_2026-07-25_r7/manifest.json` and its package README for
> current fabrication data; the Rev-D board remains NO-GO for ordering pending
> the recorded physical release gates.

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
| 10k 1% 1/8W 0805 | R4, R6, R8 … R66, R101–R109 odd (37 refs) | R_0805_2012Metric | 37 | **C17414** | 0805W8F1002T5E | UNI-ROYAL | Basic | **Historical Rev-B:** 32 opto logic-side `Rpu_*` refs plus five unrelated watchdog/AND-gate resistors. Rev-D changes only `Rpu_*` to 47 kΩ. |
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

> **Bring-up tip (ties to §19/§21):** TP1/TP2/TP3/TP5 verify the rails and the
> GND↔FIELD_GND isolation (TP2 vs TP5 must show no continuity). TP8–TP12 walk the
> NE555 watchdog. TP13/TP14/TP16 verify the board rail: TP16 should be dead unless
> ARM, RP2040_OK, the watchdog, the controlled Candidate-C J_SAFE1-2 jumper, and
> an approved J_SAFE3-4 interface are satisfied. The current lane-21/22 3–4
> harness is OPEN/unlanded, so TP16 must stay dead. This does **not** prove TB/SC; G3 separately
> commands S and T and requires both coils dead with both OEM levers BACK/open.

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
| **SC** | Sweep | **86°–243°** (window) | Sweep-under-table window → OEM ladder interlock; lane 21/22 SC/U stays unlanded as a dry input | **GP8 board position** | 11 |
| **TA1** | Table | **355°** (and **185°**) | **Table-zero stop @355°**; **@185° resets the 3-s time delay** + flips ball-cycle memory | **GP9** | 12 |
| **TA2** | Table | **260°** | **Initiate sweep run-through**; **latch pin lamps** (legacy 12 VDC / KX to scorer); **ball vs strike decision** | **GP10** | 14 |
| **TB** | Table | **105°–255°** (window) | Table-sweep interference window → OEM ladder interlock; **no independent lane-21/22 field lead** | **GP11 board position** | 15 |
| *(3-s time delay)* | — | 3 s, gated by **GP** closed | **Pin-settle** dwell between sweep-guard and table descent | *(software/RP2040 timed)* | — |

**Ball-detect inputs (not cams, but on the same fast/RP2040 bank, included for completeness — `config.h`):**

| Input | Role | RP2040 GPIO | Pico pin |
|---|---|---|---|
| **DIELL-L** | Ball detect, **left** beam — the **cycle trigger** (replaces the OEM cushion start switch "SS") | **GP12** | 16 |
| **DIELL-R** | Ball detect, **right** beam | **GP13** | 17 |

> **Electrical-sense boundary:** a populated opto position is active-low at the
> Pico, but do not generalize one "normally-closed at rest" polarity to every cam.
> Independently landed motion cams require measured edge→angle polarity. SC/TB is
> separate: powered evidence proved parallel closed-when-safe OEM ladder contacts,
> both levers BACK/open kills S/T; it did not create two firmware inputs. Lane 21/22
> has no independent TB lead and leaves SC/U unlanded.

#### 23.B.2 Where each cam fires within the cycle of operation

The cam roles above drive these four cycle types (full narrative in `phase8_8270_SYSTEM_REFERENCE.md` §2 and manual **§3, The AMF 82-70 Machine & Control Theory**):

| Cycle | Cam sequence (abridged) |
|---|---|
| **First ball** | trigger (DIELL/SS) → sweep to **SB 66°** guard → **3-s delay** (GP) → table descends → grippers read standing pins → **TA2 260°** latches pin lamps + "ready" → sweep to **SA 270°** → table runs through **TA1 185–355°** (@185° delay resets, ball-memory flips 1st→2nd) → sweep returns to **SA 360°** stop → table stops at zero. |
| **Second ball** | ball-memory inverted; sweep→**SB 66°**→delay→**run-through to SA 270°**; after the 10th pin to the bin **BS** closes → **SP** spot relay → table spotting revolution → sweep→**SA 360°** → ball-memory resets (→1st). |
| **Strike** | as first ball but **no pins** (all GS open); at **TA2 260°** the **strike memory** sets → strike lamp + hold table at 360° for spotting → spot + sweep as 2nd ball → strike memory resets when sweep+table reach zero. |
| **Foul** | foul detector (Radaray) → foul lamp + logic → sweep→**SB 66°** → **foul memory** holds table → sweep run-through to **SA 270°** → **BS** → table spotting → ball-memory flips (→2nd ball). |

#### 23.B.3 Cam-stop overrun — v1.2.3 release posture (read before relying on the table)

The **angle values** above are authoritative from the manuals, but **which edge (rising/falling) of a given cam input corresponds to which angle on our specific chassis is NOT yet confirmed.** Consequently:

- Firmware **v1.2.3** contains cam-stop-overrun paths, but its controlled Rev-D
  release keeps every measured-cam enforcement flag **OFF**. Capture per-cam
  edge→angle polarity, create a new controlled release with only confirmed values,
  and pass the bench gate before crediting any per-cam rail drop.
- Stock v1.2.3 provides health plus the **motion max-run timeout = 8000 ms**
  (`MAX_MOTION_MS`, matching `cycle_control_8270.MAX_MOTION_S = 8.0 s`). **BE**
  (continuous) and **M** (master) are not guarded. The SC∧TB echo is default-off,
  secondary, unvalidated, and lacks an independent TB observation on lanes 21/22.

> `(VERIFY: capture each independently landed motion-cam edge→angle polarity and
> bind it into a new manifest-controlled release; do not hand-derive it from this
> table. SC/TB ladder polarity is already powered-proven but is not a two-input
> firmware landing.)`

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
| **relay-enable rail (`RELAY_ENABLE_RAIL`)** | Hardware-gated board-relay coil supply. It requires ARM · RP2040_OK · NE555-OK, the controlled Candidate-C J_SAFE1-2 jumper, and an approved J_SAFE3-4 external control-power / optional pit-interlock dry-contact interface. Lane 21/22 currently leaves 3–4 OPEN/unlanded, so the field rail cannot arm. TB/SC is **not** a J14 loop: the OEM parallel-safe ladder separately blocks the S/T machine coils and is accepted only by per-lane G3 proof. |
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
| **`.uf2`** | RP2040 firmware binary. Use only the manifest-verified production artifact from the controlled v1.2.3 release path; never substitute a developer build or the FI-1 bench image. The current bundle is not flashed/cutover-ready. |
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
| `firmware/rp2040/main.c` | RP2040 v1.2.3 behavior: edge protocol, RP_OK fail-safe model, max-run, diagnostic taps/identity, and measured-cam enforcement paths whose release flags remain OFF. | §15 |
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
| `docs/phase8b_revB_fab_order_checklist.md` | ⛔ **HISTORICAL REV-B/C ONLY — NOT AN ORDER SOURCE.** Points at `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/`, which builds a **rev-C** board. For rev-D use `kicad/fab_revD_2026-07-25_r7/` + `docs/phase8_revD_readiness_checklist.md`. |
| `docs/phase8b_revB_pcba_parts_worklist.md` | PCBA parts work tracking. |
| `docs/phase8_channel_allocation.md` | ⚠️ **GPIO column is STALE** (says GP0–GP7). Useful for channel *intent*, but for GPIO numbers use `config.h` (GP6–GP13). |

#### 23.D.3 Field & bench characterization (the 82-70 reality)

| File | Covers |
|---|---|
| `docs/phase8b_at_machine_fieldsheet.md` | Historical 2026-06-03 field-session record; its original TB/SC-to-J_SAFE inference is explicitly superseded by the 2026-06-27/2026-07-07 reconciliation banner. |
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
| `docs/phase8_trackB_controller_cutover_runbook.md` | **Current Track B controller swap authority:** lockout/tagout, staged bring-up, Candidate-C jumper + per-lane G3 coil proof, go/no-go gates, and rollback. | §21 |
| `docs/phase8_pi_provisioning.md` | **Pi node provisioning**: `config.txt` boot overlays (the 2nd I²C bus + 2nd UART), focused pinned deps (`requirements-lane-node.txt`), installing both systemd units, the Pi-GPIO pin table + the **Track-A coexistence constraint** (`Conflicts=lane-node.service`), and the `systemctl enable` trap. | §17 (Pi daemon), §20 (operations) |
| `docs/phase8_PLAN_A_full_replacement.md`, `phase8_PLAN_B_scoring_first.md` | The Plan A (full controller replacement) vs Plan B (scoring-first) fork analysis. | §1 |
| `docs/phase8_8270_replacement_plan.md` | The 82-70 replacement plan overview. | §1 |
| `firmware/rp2040/README.md` | Current v1.2.3 release posture, authoritative Rev-D pin map/protocol, manifest verification, fail-safe model, and bench gates; measured-cam enforcement flags remain OFF. | §15, §21 |

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
| `docs/phase8_session_close_2026-06-03.md` | Historical 2026-06-03 snapshot of the Rev-B package and then-current v0.1 firmware; **not current wiring, firmware, or cutover authority**. |
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
| *(pending)* | — | firmware | Capture measured motion-cam polarity, enable only confirmed enforcement flags, create a new controlled release, and pass its bench/cutover sub-gates. | `phase8_trackB_controller_cutover_runbook.md` §3.2 | — |
| *(pending)* | — | BOM | Lock `Rled_*` (status-LED current-limit) value after LED selection; populate snubber/MOV (C4–C10 / R72–R87 / D2–D14) after at-machine contact-load measurement. Update 23.A.1 / 23.A.4 / 23.A.6. | `phase8b_pcb_revB_BOM_power.md` §6 | — |
| *(pending)* | — | BOM | Confirm/replace **J1** Pi header + ribbon socket candidates (3020-20-0100-00 / 3030-20-0102-00). Update 23.A.2 / 23.A.3. | `…-hand-solder-bom.csv` / `…-harness-mating-parts.csv` | — |
| *(pending)* | — | board | If `.kicad_dru` creepage is relaxed 250 VAC → 24 VAC (measured) for a future shrink/spin, re-run DRC + `export_fab_revB.py` and bump the BOM/board rev. Update §13 + 23.A counts. | `phase8b_pcb_revB_netclass_creepage.md` §3 | — |

---

*End of §23. Cross-referenced sections: §1 (System Overview & glossary seed), §3 (AMF 82-70 Machine & Control Theory), §5 (Rev-B Controller Board), §19 (Safety Architecture), §18 (Track A — Camera Scoring), §15 (RP2040 Firmware), §21 (Track B Bring-up & Cutover), §11 (Connector Pinouts), §12 (Channel Maps), §13 (Layout & Manufacturing).*
