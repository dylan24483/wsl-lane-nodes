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
