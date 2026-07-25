# Phase 8 Rev-D Lane-Controller Board — Change Specification (2026-07-19)

> **Status: SPECIFICATION — nothing implemented. This is the design document every rev-D
> implementation agent follows.**
> Scope = rev-C carryover fixes (change-list items 3 & 5) + Tier-1 diagnostics integration per
> `phase8_diagnostics_target_conditions_2026-07-19.md` §2 "Earns its place" items 1–5, plus the
> external-analog-header decision (item F below) and the OUT-B 0x23 decision (item G below).
>
> **SACRED-FILE RULE (absolute):** no rev-B/rev-C design file is edited, moved, deleted, or
> overwritten. Every script below is a COPY with `revD` in the name; every board/netlist output is
> a NEW `wsl-phase8b-revD.*` file; every fab export goes to a NEW dated directory
> (`kicad/fab_revD_YYYY-MM-DD/`). The read-only contract list is in the 2026-07-19 safeguard
> snapshot (`backups/revC_design_snapshot_2026-07-19/MANIFEST.json`, 189 files hash-verified).
> Reminder: **every rev-C artifact carries a revB filename** — `generate_kicad_netlist_revB.py`
> IS the rev-C generator; `kicad/fab_revB_routed_manual/` IS the rev-C-as-ordered package
> (see its `PROVENANCE.md`).
>
> **IMPLEMENTED CURRENT DELTA (2026-07-23):** exactly the 40 PC817 collector
> pull-ups `Rpu_*` (`R4,R6,…,R82`) are **47 kΩ**, not 10 kΩ. All unrelated
> 10 kΩ networks remain unchanged. Current package:
> `kicad/fab_revD_2026-07-23_r5/`. The binding electrical analysis and
> every-channel FA-9 acceptance are in
> `phase8_revD_remediation_spec_2026-07-21.md` §R4; that section supersedes
> older 10 kΩ PC817 arithmetic in historical review records. Its calculations
> require RP2040 GP6–GP13 PUE/PDE disabled and U1/U2 MCP23017 GPPUA/GPPUB
> commanded and read back `0x00`, so the external 47 kΩ is the sole bias.
> `R_TAPPU_*` remains an unrelated 10 kΩ diagnostic-tap drain network.

---

## 0-pre. OPEN GATES (2026-07-20 review pass — read before treating any downstream step as done)

| Gate | Status | What it blocks |
|---|---|---|
| **OG-1 — board growth 250×225 → 250×240** (§C.4 fallback 3, executed in `place_components_revD.py`) | **PENDING Dylan sign-off + enclosure re-check.** The arithmetic is verified honest (KiCad 10 DIP-4_W7.62 courtyard is 5.59 mm from the footprint file / 5.68 mm as a pcbnew bbox — either way 40 rows cannot fit 225 mm below the occupied top edge; fallbacks 1–2 are dead), but fallback 3 is conditioned on OWNER sign-off and `phase8_pair_enclosure_spec.md` still assumes 225 mm ("assumed NOT to shrink"); the rev-D bottom mounting holes moved to y=236, so the rev-C standoff/panel math no longer fits. | Step I.5 routing being treated as fab-gating; ANY enclosure, subpanel, or backplate purchase/fab. Record the sign-off in `docs/phase8_revD_run_log.md` (gate OG-1). Alternative if declined: drop to 36 rows (fits 225). |
| **OG-2 — ERC baseline waiver WVR-ERC-1** | RECORDED (run log). Exactly **1 ERC error** (Pico AGND pin 33 vs GND pin 3 POWER-OUT/POWER-OUT pin-type conflict — module-internal grounds that must be tied; benign symbol artifact) + **40 warnings**. The generator now enforces this fail-closed (`check_erc_waiver()`): any drift aborts the run. The old "0 SKiDL/ERC errors" wording in SI.1 is superseded by §I.1 below. | — (closed) |
| **OG-3 — connector cross-mate keying (J3↔J15, J13↔J16)** | Harness-BOM amendment RECORDED (§C.3 / §F): Phoenix **CP-MSTB 1734634** coding profiles at different pole positions, distinct plug colors, silk warnings on the board. The MC pin-asymmetry keying only prevents reversed insertion, NOT cross-mating of same-PN plugs. | Coding profiles must be on the harness order and FITTED before first article; first-article checklist gains a cross-mate refusal check. |
| **OG-4 — item-E hold-off proof is temperature-qualified** | Spec §E.2 CORRECTED (the 25 °C "provably OFF" claim was overbroad). Firmware must never drive GP16–GP19; disarm must drive ARM_PERMIT low, not tristate; fault-injection gate must run AT TEMPERATURE. | Item-E first-article gate is not discharged by a cold-only pass. |

---

## 0. Baseline (what rev-D starts from)

- **Netlist source of truth:** `scripts/generate_kicad_netlist_revB.py` (rev-C state, relay
  remap present at `relay_output()` lines 258–296: RAIL_EN→pad 2, coil-lo/collector/flyback
  anode→pad 5, COM/out_a→pad 1, NO/out_b→pad 3, pad 4 NC unused). 216 parts, 184 nets, 0 SKiDL
  errors (readiness checklist G3).
- **Placement source of truth:** `scripts/place_components_revB.py` — 250×225 mm, 4-layer,
  FIELD/LOGIC gutter x=76.8–80.0, LOGIC/MACHINE gutter x=181.0–184.2, opto straddle column at
  x=74 / y=24+i·6.0 (32 rows), `J_PI=(126,10,90)`, `RP_PICO=(124,55,0)` (the USB jam).
- **Netclass contract:** `scripts/apply_netclasses_revB.py` — 5 classes, every net exactly one
  class, unknown/overlap = fail. `scripts/audit_revB_board.py` asserts EXACT counts
  **Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21**
  (= 184) and fails closed.
- **Isolation contract** (`phase8b_pcb_revB_netclass_creepage.md`, catalog §2 constraints 1–2):
  LOGIC↔FIELD crossings only inside PC817 packages (≥2.5 mm), LOGIC↔MACHINE only inside G5LE
  packages (≥3.2 mm); **no new isolation-barrier component class**; GND and FIELD_GND share
  zero nodes. The `.kicad_pro`/`.kicad_prl`/`.kicad_dru` sidecars travel with the board — the
  `.dru` `hasNetclass()` rules are vacuous without the class assignments (the 2026-06-03
  false-green lesson). **2026-07-21 (remediation spec §R2, closes Codex H2): 2.5/3.2 mm are
  now CONFIRMED requirements** — working voltages measured/derived (FIELD ≤ 14 V as populated
  / 34 Vpk design basis; MACHINE 24 VAC ≈ ≤ 37 Vpk per the at-machine fieldsheet), IPC-2221B
  B1 minimum 0.6 mm, ≥4×/≥5× retained margin — and the `.kicad_dru` rule values carry a
  JLC-etch-tolerance allowance on top: **2.65 / 3.35 / 1.6 mm** (as-fabbed worst case still
  ≥ 2.5 / 3.2 / ~1.5). Routed-board measured minima 2026-07-21: L↔F 2.650 mm, L↔M 3.350 mm,
  machine ch↔ch 2.325 mm.
- **Safety rail observe-only** (catalog constraint 3): never load / jumper / re-reference
  `SAFE_*` / `RELAY_ENABLE_RAIL` / `RAIL_GATE`. **There is NO RELAY_ENABLE_RAIL divider —
  a prior critic explicitly deleted it (catalog §2 item 4). Do not re-add it. VCC_5V sensing
  only.** SAFE_* loop taps (catalog §2 item 6) are **explicitly OUT OF SCOPE for rev-D** —
  FMEA-gated separate decision; no new copper on any SAFE_ net.
- **Power ground truth:** VCC_5V ≈ 4.6–4.8 V after D17 (SS14, 1 A; `06_board-power.md` §6.2.2
  and the line-118 warning); TMA-0505S wetting rail 5 V / 200 mA / 1 W with ~1.7 mA per closed
  contact; 6 relay coils ≈ 6×77 mA ≈ 460 mA (G5LE-14 ~65 Ω coil — NOT the old 40 mA G5LE-1
  figure; readiness checklist §3).

### Source-drift findings (generator wins; noted per the campaign rule)

| # | Claim in docs | Generator/board truth | Disposition |
|---|---|---|---|
| DR-1 | Catalog ground-truth line: "GP11 vacant but contested" | GP11 (Pico pin 15) is **physically wired** to the FAST_TB opto output (`FAST_INPUTS` line 99; `07_rp2040-mcp.md:97`, `12_channel-maps.md:43`). "Vacant" means *no standalone machine signal lands on it* (TB has no independent C2A cavity — SC+TB series interlock, measured 2026-06-27, `04_machine-io.md:47`) | **GP11 is NOT usable as a rev-D tap/spare GPIO.** Item E picks from the truly-unconnected pins (§E). |
| DR-2 | Change list item 5: unloaded FIELD_WET_V ≈ 14 V | Board #1 measured ~11 V (readiness checklist §4) | Known disagreement, carried per catalog §4 "known source disagreements" — per-board measurement governs the item-A verification gate. |
| DR-3 | Catalog item 4: "route Pico GP26 **+ ADC_VREF** to a … divider" | ADC_VREF (Pico pin 35) is referenced/filtered **on the Pico module itself**; it does not route to the divider | Rev-D leaves pin 35 NC (module default). Only GP26 (pin 31) lands on the divider (§D). |
| DR-4 | Catalog item 3 complexity: "~24 parts, zero new topology" | 25 parts including the mandatory new field connector, **and** the opto straddle column must be re-pitched (32→40 rows do not fit at 6.0 mm — §C.4) | Complexity is honest-moderate; the re-pitch is the one real placement pressure of the spin. |
| DR-5 | `11_connector-pinouts.md` §11.6 J5 table | Was wrong vs `SLOW_INPUT_PINS`; hand-corrected 2026-07-06 (readiness D1) but compiled `WSL_PHASE8_SYSTEM_MANUAL.md/.docx` still stale | Cite `manual_src/`, never the compiled manual, for J5/IN-B facts. |

---

## A. FIELD_WET_V bleed / minimum-load resistor

**Source:** rev-C change list item 5 (❌ not implemented — `block_supplies()` has no bleed);
catalog §2 item 1. Kills the ~11–14 V unloaded float on the unregulated TMA-0505S (U37/ISO_WET)
and the TP4 bring-up confusion.

**Value by calculation.** Budget: 2–5 mA of the 200 mA wetting rail (catalog); change list says
1 k–2.2 kΩ, ≥¼ W-class.

- Choose **R = 1.1 kΩ implemented as 2 × 2.2 kΩ in parallel** (reuses the existing 2k2 0805 BOM
  line — no new resistor value, no new footprint class).
- Steady bleed at 5 V nominal: I = 5.0 / 1100 = **4.5 mA** — inside the 2–5 mA budget (2.3 % of
  200 mA).
- Dissipation, nominal: P = 5² / 1100 = 22.7 mW total = **11.4 mW per 0805** (rated 125 mW).
- Dissipation, worst bound (the change-list 14 V float figure, which cannot persist once the
  bleed conducts but bounds the transient): 14² / 1100 = 178 mW total = **89 mW per 0805 < 125 mW
  rating** — this is why the ≥¼ W requirement is met by the parallel pair, without introducing a
  new 1206 footprint class.

**Netlist delta** (in `generate_kicad_netlist_revD.py`, inside `block_supplies()`):

| Part (tag) | Value | Footprint | Node 1 | Node 2 |
|---|---|---|---|---|
| `R_WET_BLEED1` | 2k2 | `Resistor_SMD:R_0805_2012Metric` | `FIELD_WET_V` | `FIELD_GND` |
| `R_WET_BLEED2` | 2k2 | `Resistor_SMD:R_0805_2012Metric` | `FIELD_WET_V` | `FIELD_GND` |

- **New nets: 0** (both ends land on existing nets).
- **Netclass / audit delta: none** (`FIELD_WET_V`, `FIELD_GND` are already Field_Sense).
- **Isolation:** part is entirely FIELD-domain; no barrier crossing; GND↔FIELD_GND zero-shared-node
  invariant untouched (audit invariant 5).
- **Placement:** FIELD room (left band), adjacent to ISO_WET secondary pins / TP4–TP5 area
  (≈ x 60–70, y 14–20). Never in the gutter.
- **Wetting budget delta:** +4.5 mA (see §H).

**Verification gate:** first article — TP4→TP5 unloaded reads **≤ ~6 V** (vs 11–14 V today;
per-board measurement governs, DR-2); TP4 under normal opto load still ≥ ~4.5 V; confirm bleed
current by V²/R. Regression: TP5↔TP2 still OPEN (isolation).

---

## B. Pico USB clearance from J1 (explicitly requested by Dylan)

**Source:** rev-C change list item 3 (❌ NOT done in the rev-C layout — A1/J1 byte-identical to
rev-B; the Jun-26 package re-ships the jam); catalog §2 item 2. The change list's own description:
"This rev had the USB jammed against J1 and was flashed via a hand-shaved right-angle micro-B
cable." Current hardcoded positions: `J_PI=(126,10,90)`, `RP_PICO=(124,55,0)`
(`place_components_revB.py:198,206`) — at rot 0 the Pico's micro-USB faces −y, straight into the
J1 IDC header + mated ribbon at y=10.

**SWD stays DROPPED** (Dylan 2026-06-25, change-list item 2) — do **not** silently re-add a
debug header. The compiled-OFF firmware detectors + `'?'` polarity sentinels guarantee at least
one reflash per board after Phase 0 (catalog §2 item 2), so ordinary-cable UF2 flashing is the
requirement.

**Requirement (binding):** with the board fully populated and the J1 ribbon **mated**, a standard
unmodified micro-B cable must fully seat in A1's USB receptacle. Dimensioning: micro-B receptacle
≈ 7.6 × 5.6 × 2.9 mm (Pico datasheet); commodity cable overmold **11–13 mm wide, 7–9 mm tall,
body + strain relief extending 30–35 mm** from the connector face.

**Keep-out envelope (drawn on Dwgs_User in the rev-D placement script):** a volume
**16 mm wide** (overmold + 1.5 mm/side, centered on the receptacle) × **12 mm tall** ×
**40 mm long** from the receptacle face along the plug axis, free of any component, connector
body, or mated-ribbon volume.

**Recommended placement delta (coordinates are RECOMMENDED-VERIFY — the layout agent may satisfy
the envelope differently, but the envelope, banding, and gutters are non-negotiable):**

| Tag | rev-C | rev-D recommended | Why |
|---|---|---|---|
| `RP_PICO` | (124, 55, 0) | **(92, 33, 0)** | Module spans x≈81.5–102.5 (inside LOGIC band, 1.5 mm clear of the 80.0 gutter edge), y≈7.5–58.5; USB faces the **top board edge** — the cable overmold hangs off-board, so only ~8 mm of the envelope is on-board and trivially clear. |
| `J_PWR` | (104, 10, 0) | **(113, 10, 0)** | Clears the Pico x-span + envelope (nearest body edge ≥5 mm from envelope). |
| `D_PROT` | (101, 24, 0) | **(110, 25, 0)** | Follows J_PWR; keeps the VRAW→VCC_5V run short. |
| `J_PI` | (126, 10, 90) | unchanged | Ribbon no longer in the cable path. |

> **AS-PLACED (2026-07-20, run-log COR-3):** the layout agent exercised the RECOMMENDED-VERIFY
> latitude above: `RP_PICO` landed at **(100, 33, 0)** (not (92, 33, 0) — Rpu-column courtyard
> collision, Rpu column itself moved x 92→86) and `J_PI` moved to **(135.5, 10, 90)** (+9.5 mm
> right; this table's "unchanged" describes the recommendation, not the board). Envelope,
> banding, and gutters verified intact (placement DRC 0). Pi ribbon length/dress + enclosure
> ribbon opening re-check is folded into gate OG-1.

Watch items for the layout agent: ISO_WET at (73.9, 13, 90) courtyard vs the Pico's new left
edge; J_PI footprint-origin overhang at y=10; item-D/E parts want to live near the new Pico
position (§D, §E placements already assume it).

**Affected routing region:** x ≈ 80–135, y ≈ 5–80 (I2C/UART/KICK/ARM runs from J1 to the moved
Pico; FAST_* runs from the Rpu column at x=92 now land shorter). Full re-route + re-DRC + audit
re-gate — this is a new board file anyway.

- **Netlist delta: none. New nets: 0. Class counts: unchanged.**

**Verification gates:** (1) placement review — envelope rectangle on Dwgs_User + KiCad 3D /
1:1 paper print with a real cable + ribbon-header mockup; (2) first article — off-the-shelf
micro-B cable seats with J1 ribbon mated, BOOTSEL reachable, UF2 drag-drop flash succeeds
**without** the hand-shaved cable; (3) enclosure check — cable path clear with the board mounted
(`phase8_pair_enclosure_spec.md`).

---

## C. IN-B GPB opto bank — 8 × PC817B channels (AUX4–AUX11)

**Source:** catalog §2 item 3 (breaks the ≥5-sensors-for-3-AUX-channels contention deadlock:
S/T current switches, Klixon aux contacts, door/service switches, low-rate index pulses).
GPB0–7 of MCP_IN_B (0x21) verified unconnected in the generator (`SLOW_INPUT_PINS` stops at
AUX3 on GPA7).

### C.1 Channel pattern — match `opto_input()` EXACTLY

Confirmed from the generator (lines 235–255) and `08_opto-inputs.md` §8.2: per channel
**PC817B** (UMW, LCSC C5692981, `Package_DIP:DIP-4_W7.62mm`) + **Rin 2k2** (0805, FIELD side,
from `FIELD_WET_V`) + **Rpu 47k** (0805, LOGIC side, to `VCC_3V3`). Dry-contact default: WET →
Rin → opto LED → field pin; field contact closes to FIELD_GND at the harness. Logic side pulls
the MCP pin low through the phototransistor; active-low. **No fitted RC network**
(catalog constraint 8 — debounce lives in firmware; the unavoidable first-order
47 kΩ × 50 pF receiver-node estimate is 2.35 µs).

### C.2 Netlist delta

Append to `SLOW_INPUT_PINS` (**at the END of the dict** — preserves instantiation order so
existing refdes don't shift):

| Name | MCP | MCP pin | Port/bit | New nets created by `opto_input()` |
|---|---|---|---|---|
| AUX4 | MCP_IN_B (0x21) | 1 | GPB0 (1,0) | `SLOW_AUX4`, `FIELD_SLOW_AUX4`, `FIELD_LED_AUX4` |
| AUX5 | MCP_IN_B | 2 | GPB1 (1,1) | `SLOW_AUX5`, `FIELD_SLOW_AUX5`, `FIELD_LED_AUX5` |
| AUX6 | MCP_IN_B | 3 | GPB2 (1,2) | … |
| AUX7 | MCP_IN_B | 4 | GPB3 (1,3) | … |
| AUX8 | MCP_IN_B | 5 | GPB4 (1,4) | … |
| AUX9 | MCP_IN_B | 6 | GPB5 (1,5) | … |
| AUX10 | MCP_IN_B | 7 | GPB6 (1,6) | … |
| AUX11 | MCP_IN_B | 8 | GPB7 (1,7) | … |

(MCP23017 pin map per the generator's verified comment: GPB0–7 = pins 1–8.)

**Parts: 8 × (OPTO_AUXn PC817B + Rin_AUXn 2k2 + Rpu_AUXn 47k) = 24 parts**, plus the connector
(C.3) = **25 parts**. **New nets: 24** (8 SLOW_, 8 FIELD_SLOW_, 8 FIELD_LED_).

### C.3 New field connector — J15 / `J_SLOW_IN_C`

J5 (`J_SLOWB`, 1×12) is full (11 signals + FGND pin 12). Next J number is **J15** (J1–J14
assigned; instantiate the new connector AFTER the existing seven in `block_connectors()` and
verify the emitted refdes actually lands at J15 — SKiDL assigns by order).

- Part: `Connector_Generic:Conn_01x10`, value `J_SLOW_IN_C`, tag `J_SLOWC`.
- Footprint: `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical`
  (`FP_MCV_1X10` — already proven on J3).
- **Pinout mirrors J3's keying pattern exactly** (8 signals + doubled field-ground last —
  J3 = signals 1–8, FGND 9–10; J5's single-FGND-last is the 11-signal variant):

| J15 pin | Net |
|---|---|
| 1–8 | `FIELD_SLOW_AUX4` … `FIELD_SLOW_AUX11` |
| 9, 10 | `FIELD_GND` |

- Mating plug: **Phoenix MC 1,5/10-ST-3,5 = 1840447** (same PN as J3's plug). **Add to the
  harness/assembly BOM in this same spec cycle** — the rev-B/-C mating-connector BOM gap
  (change-list item 4) does not get a third occurrence.
- **Cross-mate hazard + mandatory coding (gate OG-3, 2026-07-20):** J15 and J3 use the SAME
  1840447 plug on the same field edge and both wire signals 1–8 + FGND 9/10 — a swap is
  same-domain and produces NO electrical fault, but silently crosses the machine cycle sensors
  (SA/SB/SC/TA/TB/DIELL) with AUX contacts, mis-sequencing cycle control. The MC pin-asymmetry
  keying only prevents reversed insertion, not cross-mating. Harness BOM therefore carries
  **Phoenix CP-MSTB coding profiles (PN 1734634)** keyed at DIFFERENT pole positions —
  **J3: code at pole 1; J15: code at pole 10** — plus distinct plug wire-marking colors
  (J3 harness = white band, J15 = yellow band). Board silk warns at both connectors
  ("KEYED: NOT J15" / "KEYED: NOT J3"). First article: verify each coded plug physically
  REFUSES the wrong header.
  **INSTALL PROCEDURE CORRECTED 2026-07-21 (Codex H7 — the original text here had it
  REVERSED, "insert the profile in the header groove, cut the tab on the plug"): the
  CP-MSTB profile fits the PLUG (or an inverted header) — it is never pressed into a
  standard MCV G-3.5 header; the header side of the code is made by removing the coding
  rib at the matching pole. A sacrificial-pair proof (one spare plug + one scrap header,
  seat/refuse/no-damage verified against the Phoenix instruction sheet) is REQUIRED
  before coding any production part — first-article pack step FA-8
  (`docs/phase8_revD_first_article_pack.md`); harness data in
  `docs/phase8_revD_harness_bom.csv`.**
- New nets from the connector: 0 (all pins land on C.2 nets / FGND).

### C.4 Placement — the one real layout pressure (re-pitch the straddle column)

All optos must sit in the single FIELD/LOGIC gutter-straddling column (field pads left, logic
pads right — the keepout runs between the PC817 pad columns, `phase8b_pcb_revB_spec.md` 2026-06-02
re-band note). 40 rows at the rev-C 6.0 mm pitch = 234 mm — **does not fit** the 225 mm board.

- DIP-4_W7.62 courtyard along the column axis measured from the KiCad 10 footprint file:
  **5.2 mm** (−1.33…+3.87). Minimum non-overlapping pitch ≈ 5.2 mm.
- **Spec: pitch 5.25 mm, 40 rows, column start y = 14.0** → rows y = 14.0 … 218.75; Rin/Rpu
  keep their ±1.8 mm y-offsets (extents 12.2–220.55). Same x layout as rev-C (opto x=74,
  Rin x=58, Rpu x=92).
- Consequences the rev-D placement script owns: relocate the TP strip (currently y=214/221,
  x 22–164) and the bottom Dwgs/silk band; extend the gutter keepout strip to cover the longer
  column; J3/J4/J5/J15 y-positions re-align to their channel groups; J15 at ≈ (9, 200, 90).
- **Gate:** KiCad courtyard DRC clean at 5.25 mm. Fallbacks in order if it fails: (1) 5.3–5.4 mm
  pitch + reclaim the last 2–3 mm at both column ends; (2) relocate the four lamp-driver stacks
  to free bottom-band room; (3) LAST resort +10–15 mm board height — fights the shrink direction
  (catalog constraint 10) and requires Dylan's sign-off + enclosure re-check.
- **OUTCOME (2026-07-19/20): fallback 3 was TAKEN — the 5.25 mm premise above is wrong.** The
  true KiCad 10 DIP-4_W7.62 courtyard is 5.59 mm from the footprint file (5.68 mm as a pcbnew
  bounding box incl. stroke), so 40 rows need ≥ ~222.5 mm of column below an occupied top edge:
  fallbacks 1–2 are arithmetically dead. Board grown to 250×240, pitch 5.7 mm, bottom mounting
  holes now at y=236. **The required sign-off + enclosure re-check is STILL PENDING — gate OG-1.
  Alternative if declined: 36 rows fits 225 mm.**

### C.5 Class / budget / software

- **Netclass:** `SLOW_AUX*` → Logic_Signal (+8); `FIELD_SLOW_AUX*`, `FIELD_LED_AUX*` →
  Field_Sense (+16). Existing prefix rules in the classifier cover all 24 — zero classifier
  edits needed for this item; audit counts move per §H.
- **Isolation:** 8 new crossings of the EXISTING PC817 barrier class — no new `.kicad_dru`
  rules; the carried `hasNetclass()` LOGIC↔FIELD ≥2.5 mm rule binds the new nets automatically
  (because they classify into the same classes).
- **Wetting:** +8 × ~1.7 mA worst-case-all-closed ≈ +13.8 mA (catalog said 8–16 mA ✓). See §H.
- **Software companion (NOT this board task, listed for traceability):** `IN_B_MAP` + startup
  self-test extension + mid-session stuck-input coverage for IN-B ship with the spin (catalog
  §2 item 3; §1.15 mechanic-at-machine row). Lives in the separate diagnostics software
  campaign — do not touch `lane_node/`/`server/`/`tests/` or `firmware/` from this task.

**Verification gates:** footprint-vs-datasheet review re-run for PC817B DIP-4 against LCSC
C5692981 (gate 10 is per-part-class per-spin scripture, even for a reused class); SKiDL ERC 0
errors; first article — `i2cdetect` 0x21 present, then poke each of J15 pins 1–8 to FIELD_GND
and read the matching GPB bit (extends the §4 first-article input poke to all 8).

---

## D. VCC_5V board-self-health ADC divider (GP26/ADC0)

**Source:** catalog §2 item 4. Platform tier only: 5 V sag under 6-coil load (~460 mA), brownout
trending. Cannot see any FIELD/MACHINE quantity — complements machine-side sensing, never
replaces it. **Restated per the critic's deletion: there is NO RELAY_ENABLE_RAIL divider.
A divider is a permanent load on the rail and its high-side short would re-reference it,
violating observe-only. VCC_5V sensing ONLY.**

**Netlist delta** (LOGIC domain; 3.3 V-GPIO rule satisfied by the divider — VCC_5V is 5 V-domain,
catalog constraint 4):

| Part (tag) | Value | Footprint | From | To |
|---|---|---|---|---|
| `R_ADC5_TOP` | 10k | R_0805 | `VCC_5V` | `ADC_VCC5_SENSE` |
| `R_ADC5_BOT` | 10k | R_0805 | `ADC_VCC5_SENSE` | `GND` |
| `C_ADC5` | 100nF | C_0805 | `ADC_VCC5_SENSE` | `GND` |

- `ADC_VCC5_SENSE` → **Pico pin 31 (GP26/ADC0)**. Pin 35 (ADC_VREF) stays NC — module-internal
  reference (drift DR-3).
- **Sizing math:** ratio 0.5 → nominal read 4.7/2 = 2.35 V; worst-case input 5.25 V (PSU +5 %
  upstream of D17, D17 shorted-fail bound) → 2.63 V < 3.3 V full-scale, margin 20 %.
  Thevenin source impedance 5 kΩ — inside the RP2040 ADC's recommended <10 kΩ. RC corner
  1/(2π·5k·100n) ≈ 318 Hz — sag/brownout trending band; this is an ADC channel, not an
  edge-capable fast input, so the RC does not violate constraint 8.
- Permanent load on VCC_5V: 5/20k = **0.25 mA** (allowed — only SAFE_*/rail are load-forbidden).
- **New nets: 1** (`ADC_VCC5_SENSE`). **Netclass:** add exact-name entry `ADC_VCC5_SENSE` →
  Logic_Signal in the rev-D classifier (+1).
- **Placement:** LOGIC band adjacent to the moved Pico (§B), ≈ (100, 45).
- **Firmware/heartbeat consumption** (adc field on heartbeat) = software campaign, out of scope
  here; the board only provisions the channel.

**Verification gate:** first article — GP26 ADC reads VCC_5V/2 within ±3 % of the TP1 DMM value;
energize 6 coils (bench_first_article pattern) and confirm the sag is visible in the ADC trend.

---

## E. Rail-predicate edge-ordering taps — existing observable points ONLY

> **⚠ 2026-07-21 — §E.2 AND §E.3 ARE SUPERSEDED by
> `phase8_revD_remediation_spec_2026-07-21.md` §R1** (Codex NO-GO findings C1 + H1: the
> resistive taps below are bidirectional copper — a stuck-high GPIO injects into the
> observed net, and the 555 divider rides an unguaranteed VOH). The implemented rev-D
> design is the remediation spec's **per-tap 2N7002 common-source inverter** (R_TAPIN 1M →
> gate; R_TAPG 10M gate pulldown on the 3.3 V taps; VCC_3V3 → R_TAPPU 10k → drain → GPIO;
> reads INVERTED, firmware v1.2 contract R3): 15 parts, 8 new nets (4 `TAP_GATE_*` +
> 4 `TAP_*`), 680k GONE from the BOM, +1M/+10M added. Worst double-fault injection
> ≤ 0.56 µA → 0.056 V on RAIL_GATE (≥ 8× under the partial-hold onset), absolute
> transistor-free ceiling 3.3 µA. §E.1 (GPIO/pin selection), the SAFE_* scope exclusion,
> and the Safety_Rail == 13 invariant below still stand. §E.2/§E.3 text is retained for
> history only — do not implement from it.

**Source:** catalog §2 item 5 (the scope doc's tap grant): 1 ms edge-ordered capture of
**NE555_OUT, WDOG_KICK (TP8 net), ARM_PERMIT (TP13 net), RP2040_OK (TP14 net)** via spare RP2040
GPIOs — records ordered predicate transitions for advisory cause inference (wdt_reset
vs pi_death vs arm_drop) only when independent evidence proves an actual rail drop. None
directly observes `RELAY_ENABLE_RAIL`/TP16 or proves Q14/J14/rail stuck-on or
stuck-open behavior. **Explicitly OUT OF SCOPE: any new connection to SAFE_TBSC_RETURN /
SAFE_STOP_RETURN / any SAFE_* loop net** (catalog §2 item 6 — FMEA-gated separate decision;
SAFE_TBSC_RETURN has no test pad today and gets no new copper in this spin). Also out of scope:
anything touching RELAY_ENABLE_RAIL / RAIL_GATE.

### E.1 GPIO selection

Truly-unconnected Pico pins per the generator (only 1, 2, 4, 9–12, 14–17, 36, 39 + grounds are
used): GP3, GP4, GP5, GP14, GP15, **GP16, GP17, GP18, GP19**, GP20, GP21, GP22, GP26, GP27,
GP28 (~15, as the catalog says). **GP11 is NOT spare — it is FAST_TB (drift DR-1).** GP26 is
consumed by item D. Pick the contiguous block:

| Tap net | Source net | GPIO | Pico pin |
|---|---|---|---|
| `TAP_NE555_OUT` | `NE555_OUT` (5 V domain) | GP16 | 21 |
| `TAP_WDOG_KICK` | `WDOG_KICK` (3.3 V, Pi-driven) | GP17 | 22 |
| `TAP_ARM_PERMIT` | `ARM_PERMIT` (3.3 V, Pi-driven) | GP18 | 24 |
| `TAP_RP2040_OK` | `RP2040_OK` (3.3 V, Pico-driven) | GP19 | 25 |

### E.2 Tap networks + the can't-assert/can't-hold proofs — **SUPERSEDED (see §E banner; remediation spec R1)**

**3.3 V taps (WDOG_KICK, ARM_PERMIT, RP2040_OK): single series 680 kΩ, no shunt, Schmitt-mode
GPIO input.** A divider would put the read below VIH on an already-3.3 V net; the task's
"divider" requirement is satisfied where it electrically applies (the 5 V NE555_OUT tap) and by
the series-only proof below where a shunt would break reading.

- *Worst credible tap fault = GPIO stuck driving 3.3 V.* The sensitive victims are the rail
  AND-chain bases: ARM_PERMIT and RP2040_OK each feed `Rb_AND_* = 10k` into an MMBT3904 base
  with `Rpd_AND_* = 100k` to GND (generator `block_rail()` lines 503–510). With the legitimate
  driver tristated (Pi rebooting — exactly the window that matters), the injected base voltage
  is the three-resistor ladder: V_base = 3.3 × 100k / (680k + 10k + 100k) = **0.42 V**.
  **TEMPERATURE QUALIFICATION (2026-07-20 correction — the original "< any silicon V_BE
  turn-on → provably OFF" claim only holds near 25 °C):** at 25 °C the MMBT3904 collector
  current at V_BE 0.42 V is ~0.1 µA (harmless), but V_BE(on) falls ~2 mV/K, so at ~85 °C
  junction the same 0.42 V drives roughly **5–30 µA** — and only ~5–13 µA through the 100k
  `R_RAIL_GATE_PULLUP` spans the AO3401's full V_GS(th) range (−0.5…−1.3 V), so a stuck-high
  tap CAN hold (or partially hold, relay-brownout class) the pass-FET at temperature, with
  weak-conduction onset around 70–75 °C. A 100k-class series still fails even at 25 °C
  (V_base ≈ 0.9 V) — **hence 680 k, not 100 k; do not "simplify" this value down.** The
  residual hot-tap-fault risk is closed procedurally, all BINDING: **(1)** firmware must
  NEVER configure GP16–GP19 as outputs (inputs + Schmitt only; assert in firmware review);
  **(2)** a deliberate disarm must DRIVE ARM_PERMIT low (push-pull — the tap then injects
  ≤0.25 mV and hold-off is unconditional), never tristate; **(3)** the fault-injection gate
  below runs AT TEMPERATURE, not just cold. Option evaluated but NOT taken this spin (it is a
  safety-rail value change requiring its own observe-only-contract review):
  `R_RAIL_GATE_PULLUP` 100k→22k, raising the required hold-off current ~5×.
  - WDOG_KICK victim is the AO3400 kick-gate ladder (1k + 10k pd): V_gate = 3.3 × 10k/(680k+11k)
    ≈ **0.05 V** « 0.65 V min V_GS(th) ✓.
  - When the legitimate driver is active (push-pull ~50 Ω): tap fault contributes
    3.3 V/680k ≈ 4.9 µA → ≈0.25 mV of disturbance ✓ (can neither assert nor hold).
- *Reading integrity through 680 k:* RP2040 leakage ±1 µA worst → ±0.68 V error.
  High: 3.3−0.68 = 2.62 V > VIH 2.0 V ✓. Low: 0.68 V < VIL 0.8 V ✓. Enable the pad Schmitt
  trigger. Timing: 680k × ~10 pF pin ≈ 7 µs — far inside the 1 ms ordering requirement and not
  a masking RC on any machine-edge channel (constraint 8 untouched — these taps are not machine
  inputs).

**NE555_OUT tap (5 V domain — divider mandatory per constraint 4):** series **100 kΩ** + shunt
**680 kΩ** to GND (ratio 0.872).

- NE555 (bipolar, VCC ≈ 4.7 V) output high ≈ VCC−1.2…1.7 ≈ 3.0–3.5 V → read 2.6–3.05 V > VIH ✓.
  **Worst-case bound (COR-2, 2026-07-20 — the original "≤ 3.27 V < 3.3 V" line assumed
  VOH ≤ 3.75 V and was optimistic):** absolute worst rail 5.25 V at light load (Thevenin ≈ 87k
  is µA-class for the 555) gives VOH up to ≈ VCC−1.2 ≈ 4.05 V → read ≈ 4.05 × 0.872 ≈
  **3.53 V**. That exceeds VDD 3.3 V but stays below the RP2040 3.6 V absolute maximum, and the
  ≥ 100 kΩ source impedance bounds any pad-clamp current to single-digit µA — electrically
  safe, but do not quote the old 3.27 V figure. (A plain wire or a 2:1 divider still fail
  here — this ratio remains deliberate.) Low ≈ 0.25 V → 0.22 V ✓.
  Thevenin ≈ 87k → leakage error ±0.09 V ✓.
- *Can't-assert proof:* NE555_OUT is a push-pull mA-class output; a faulted GPIO injects at most
  3.3 V/100k = 33 µA — 2+ orders below the 555's drive. ✓
- 680k appears in both tap flavors → **one new BOM value total (680k 0805)**.

### E.3 Netlist delta — **SUPERSEDED (see §E banner; implemented delta = remediation spec §R1.7)**

Historical (NOT implemented):

| Part (tag) | Value | From | To |
|---|---|---|---|
| `R_TAP_555` | 100k | `NE555_OUT` | `TAP_NE555_OUT` |
| `R_TAP_555_DIV` | 680k | `TAP_NE555_OUT` | `GND` |
| `R_TAP_KICK` | 680k | `WDOG_KICK` | `TAP_WDOG_KICK` |
| `R_TAP_ARM` | 680k | `ARM_PERMIT` | `TAP_ARM_PERMIT` |
| `R_TAP_RPOK` | 680k | `RP2040_OK` | `TAP_RP2040_OK` |

Implemented instead (remediation spec §R1.7, 2026-07-21): per tap suffix in
{555, KICK, ARM, RPOK} — `R_TAPIN_*` 1M (observed net → `TAP_GATE_*`), `Q_TAP_*` 2N7002
SOT-23 (G=`TAP_GATE_*`, S=GND, D=`TAP_*`), `R_TAPPU_*` 10k (VCC_3V3 → `TAP_*`), plus
`R_TAPG_*` 10M (`TAP_GATE_*` → GND) on KICK/ARM/RPOK only (the 555's push-pull output is
never high-Z; asymmetry deliberate). Tap drain nets land on Pico pins 21/22/24/25 per E.1.
**New nets: 8. Parts: 15. 680k leaves the BOM entirely.**

- **Netclass:** add prefix rule `TAP_` → Logic_Signal in the rev-D classifier (+4). All tap
  copper is LOGIC-band only; nothing crosses a barrier; Safety_Rail count stays EXACTLY 13
  (design invariant of this spin — any Safety_Rail delta in the audit = automatic fail).
- **Placement:** series resistor within ~10 mm of its source node (the long trace to the GPIO is
  then the low-energy, high-impedance side); cluster ≈ x 130–170 / y 35–80 near the watchdog
  block; tap runs to the moved Pico (§B).
- **Firmware consumption** (1 ms edge capture + rail-drop-reason codes on heartbeat) = later
  campaign; `firmware/` untouched by this task.

**Verification gates:** bench — scope each TAP_ node vs its source for level/threshold margins;
fault-injection test: force each tap GPIO output-high (test firmware) with the Pi link disconnected
and prove the rail does NOT arm and an armed rail still drops on Pi-kill within the same time as
an untapped board; then a forced Pi-death and a forced kick-starvation each produce the correct
edge ORDER on the four taps. **AT-TEMPERATURE repeat (mandatory, gate OG-4): re-run the
stuck-high fault injection with the Q_AND_ARM / Q_AND_RP_OK / Q_RAIL region held ≥70 °C case
temperature (heat gun + thermocouple) and prove a deliberate ARM_PERMIT disarm still drops the
rail — a cold-only pass does not discharge this gate.**

---

## F. External-analog expansion header — J16 / `J_EXT_I2C` (decision: dedicated header, ADD)

**Source:** catalog §2 "Do NOT put on the board" (isolated analog front-end = permanently
external — a third barrier class is forbidden) + §3 item 4 (USB-ADC is the mandatory analog
path). This header is the *integrate-without-a-barrier-class* answer: a keyed LOGIC-domain
connector so a future **externally-isolated** ADC/sensor module (its isolation lives ON the
module, off-board) can plug in with no on-board analog front-end.

**J1-suffices evaluation (required by the task): J1 does NOT suffice — decision justified.**
J1 exposes SDA/SCL/3V3/5V, but the J1 header is fully occupied by the mated Pi ribbon; its
unconnected pins 14–20 sit inside the mated IDC shroud and are physically unavailable. Tapping
the ribbon mid-run is a field-hack, not an integration point. A dedicated header costs one
proven-footprint part and zero new nets. **Decision: add J16.** (This also makes item G
redundant — see §G.)

**Netlist delta:** one part — `Conn_01x06`, value `J_EXT_I2C`, tag `J_EXTI2C`, footprint
`Connector_Phoenix_MC:PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical` (`FP_MCV_1X06`,
proven on J13). Instantiate after J15 → refdes **J16** (verify emitted refdes). Mating plug
Phoenix MC 1,5/6-ST-3,5 = **1840405** (same PN as J13's plug — add to harness BOM now).

| J16 pin | Net | Note |
|---|---|---|
| 1 | `VCC_5V` | module primary power — **budget cap 45 mA** (R3-7 re-derivation; was 100 mA), re-run §H D17 math before any module lands |
| 2 | `GND` | |
| 3 | `I2C_SDA` | shared bus 1 (existing 4.7k pullups) |
| 4 | `I2C_SCL` | |
| 5 | `VCC_3V3` | logic-reference option for the module's isolated-side interface |
| 6 | `GND` | pin-1-vs-6 asymmetry + MC keying = polarization (reversed-insertion only — see coding note below) |

- **Cross-mate hazard + mandatory coding (gate OG-3, 2026-07-20):** J16 and J13 use the SAME
  1840405 plug 24 mm apart on the same board edge, and pins 1/2 are VCC_5V/GND on BOTH — a
  swapped lamp harness in J16 lands the mask LED wired to plug pin 6 straight across
  VCC_5V→GND with NO series resistor (the 330R limiters sit on-board behind J13), and the LEDs
  on pins 3/4 drag SDA/SCL to ~3 V, wedging the I2C bus that drives MCP_OUT_A — the relay
  expander then holds its last-written state while the controller is blind. Harness BOM
  carries **CP-MSTB 1734634** coding at DIFFERENT pole positions — **J13: code at pole 1;
  J16: code at pole 6** — plus distinct plug colors (J13 harness = white band, J16 = blue
  band). Board silk warns at both connectors ("KEYED: NOT J16" / "KEYED: NOT J13 LAMP").
  First article: verify each coded plug physically REFUSES the wrong header. The prior
  "pin-1-vs-6 asymmetry + MC keying = polarization" claim only ever covered reversed insertion.
  Install procedure per the corrected §C.3 rule (2026-07-21, Codex H7): profile in the PLUG,
  never a standard header; header-side rib removed at the matching pole; sacrificial-pair
  proof (FA-8) before coding production parts.

- **Shared vs dedicated bus:** shared. Address space check: on-bus today 0x20/0x21/0x22, with
  0x23 reserved for a future OUT-B (generator comment line 529). Typical ADC modules land at
  0x40–0x4B (INA219/ADS1115 class) — no conflict. **Rule: any module on J16 must avoid
  0x20–0x23.**
- **New nets: 0. Netclass delta: 0** (all five pins are existing nets). DNP-tolerant by nature —
  an empty or unused header is electrically inert; populate on first articles, fleet decision
  later.
- **Placement:** LOGIC band bottom edge ≈ (155, 206, 0) (clear of J13 at 104 and the lamp-driver
  stacks). Keep the added SDA/SCL stub < 150 mm; bus load delta ~+20 pF on a 100 kHz bus with
  4.7k pullups — comfortably inside 400 pF.
- **Isolation:** header is 100 % LOGIC domain. Any module plugged here must carry its own
  isolation for anything it touches beyond LOGIC — that stays the module's problem, never new
  board copper (no new barrier class, constraint 1 upheld).

**Verification gate:** i2cdetect with a scrap ADS1115/INA219 module on J16 shows the module AND
0x20/0x21/0x22 all still ACKing; bus rise-time spot-check with the module attached.

---

## G. OUT-B MCP23017 @0x23 footprint — decision: DEFER (do not place)

**Source:** catalog "Nice-to-have" table — "Pindicator lamps only — **zero diagnostics yield**;
no condition in §1 consumes OUT-B. Capacity insurance."

**Evaluation against "include only if genuinely trivial":** the generator cost is 3 lines
(`block_mcp("MCP_OUT_B", (1, 1, 0), None)` — A0+A1 high per the generator's own 0x23 comment),
but the REAL cost is not the generator: an SOIC-28 + decoupling in the center band + I2C stub +
32 dead pins of routed-around copper on a board whose standing direction is SHRINK (catalog
constraint 10), plus ERC/audit noise from a fully-unconnected GPIO field, for a function (lamp
drive) that would still need ~11 driver parts per channel and a connector to be usable.
**And item F now provides the same capacity insurance off-board:** a $2 MCP23017 breakout on
J16 at the very same 0x23 address delivers OUT-B the day it's ever wanted, with zero board area.

**Decision: DEFER.** Rev-D carries only the documentation note (the 0x23 strap comment already
in the generator). If Dylan overrides: the delta is +2 parts (MCP_OUT_B + C_MCP_OUT_B), 0 new
nets, 0 class-count change, and the SKiDL ERC unconnected-pin warnings must be explicitly
waived in the run log.

---

## H. Summed budgets

### H.1 Audit class-count delta table (extend `apply_netclasses_revD.py` + `audit_revD_board.py` in lockstep)

2026-07-21 (remediation spec §R1.7): item E's delta is now **+8 nets** (4 `TAP_*` drain
nets + 4 `TAP_GATE_*` gate nets), all Logic_Signal via the `TAP_` prefix rule:

| Class | rev-C (asserted today) | A | B | C | D | E (R1) | F | G | **rev-D expected** |
|---|---|---|---|---|---|---|---|---|---|
| Logic_Signal | 80 | — | — | +8 | +1 | +8 | — | — | **97** |
| Logic_Power | 4 | — | — | — | — | — | — | — | **4** |
| Safety_Rail | 13 | — | — | — | — | **0 (invariant)** | — | — | **13** |
| Field_Sense | 66 | — | — | +16 | — | — | — | — | **82** |
| Machine_Output | 21 | — | — | — | — | — | — | — | **21** |
| **Total nets** | **184** | | | +24 | +1 | +8 | | | **217** |

Classifier edits required in the rev-D copy: exact-name `ADC_VCC5_SENSE` → Logic_Signal;
prefix `TAP_` → Logic_Signal. Everything else classifies under existing rules. The rev-D audit
script asserts `{Logic_Signal: 97, Logic_Power: 4, Safety_Rail: 13, Field_Sense: 82,
Machine_Output: 21}`, `Default == 0`, zero `N$*` anonymous nets, 217 total — fails closed,
same as rev-C. **A Safety_Rail count ≠ 13 is an automatic stop-ship.**

### H.2 New-part count

| Item | Parts |
|---|---|
| A — bleed | 2 |
| B — USB clearance | 0 |
| C — GPB opto bank + J15 | 25 |
| D — VCC_5V ADC | 3 |
| E — taps (remediation spec R1: 4 × unidirectional stage) | 15 |
| F — J16 | 1 |
| G — deferred | 0 |
| **Total** | **46** → part registry 216 → **262** |

New BOM lines (2026-07-21, R1): **1M 0805** and **10M 0805** (+2 values; the earlier plan's
680k is GONE — the taps were its only use). New footprint classes: **none** (2N7002 SOT-23 is
the existing `Qled_*` class; 2k2/10k/100k/0805/DIP-4/MCV_1x10/MCV_1x06 all already on the
board) — but gate 10 datasheet review re-runs per part class anyway (§I step 2; run-log FR-8
covers 2N7002-in-SOT-23, FR-9 the `_D1.4` MCV drill/pad change per remediation spec R2.5).

### H.3 Wetting-rail budget (TMA-0505S, 5 V / 200 mA / 1 W)

| Load | Current (worst case, all contacts closed) |
|---|---|
| 32 existing channels × ~1.73 mA ((5−1.2)/2k2) | 55.4 mA |
| 8 new channels (item C) | +13.8 mA |
| Bleed (item A) | +4.5 mA |
| **Total** | **73.7 mA = 37 % of 200 mA** ✓ |

Output power 5 V × 73.7 mA ≈ 0.37 W of 1 W ✓. Reminder from the catalog critic (finding 10):
machine sensors are POWERED by the shared machine-side 24 VDC supply, never by FIELD_WET_V —
the wetting rail only wets dry/NPN contacts.

### H.4 D17 (SS14, 1 A) budget

Baseline worst case ~0.7–0.9 A (catalog constraint 7; `06_board-power.md:118-120` warning).
Rev-D additions on VCC_5V:

| Source | Δ |
|---|---|
| TMA input for +18.3 mA of new secondary load (bleed + 8 channels), η≈0.75, Vin≈4.7 V | ≈ +26 mA |
| 8 new 47k logic pull-ups (all optos on) via Pico 3V3 | ≈ +0.56 mA |
| ADC divider | +0.25 mA |
| Taps (R1 stages, 2026-07-21: 4 × 10k drain pull-ups, worst = all four observed nets high → FETs on, 4 × 0.33 mA on VCC_3V3 through the Pico regulator) | ≈ +1.3 mA |
| **Total Δ** | **≈ +29 mA** |

New worst case ≈ **0.73–0.93 A — still under 1 A but the margin was already thin and rev-D
consumes ~3 % more**. **IMPLEMENTED in the rev-D generator (2026-07-20, run-log FR-3): `D_PROT` value
is now SS34 (3 A)** — a value swap, zero copper change, same `D_SMA` footprint. Gate-10
footprint-vs-datasheet check DONE: chosen MPN **MDD SS34, LCSC C8678, package SMA/DO-214AC
verified** (SS34 also ships in SMB/SMC from other vendors — exactly the G5LE-1/-14 class of
trap; do not substitute MPNs without re-running gate 10). The diff-script contract whitelists
this one value change (`ALLOWED_CHANGED_PARTS`).

**J16 module allowance — RE-DERIVED (R3-7, 2026-07-21; was 100 mA):** the earlier
"sanctioned 100 mA module allowance" silently used the 1206L020 **23 °C** hold (0.20 A ×
½ = 100 mA "2× margin"). That margin evaporates at temperature. Littelfuse 1206L020
still-air hold-current derating: 0.17 A @40 °C, 0.15 A @50 °C, **0.12 A @70 °C, 0.09 A
@85 °C**. The declared worst-case F1 body temperature is **85 °C** — enclosure spec
`phase8_pair_enclosure_spec.md` gives ≤ ~48 °C internal *bulk* air (35 °C summer + ΔT ≈
8 °C, sealed no-vent), and F1 sits in that volume next to the dominant heat sources
(Pi + heatsink, TMA-0505S brick, energized relay coils), so we derate at the datasheet's
characterized ceiling (85 °C) to envelope any local hotspot rather than model it (48 °C
bulk interpolates to ~154 mA hold for reference). Applying the required **≥ 2× hold
margin at 85 °C: allowance = 90 mA / 2 = 45 mA.** PPTC *trip* is a minimum-to-trip, not a
hard cap; sizing the steady module draw well under I_hold(T) is what keeps a legitimate
hot module from nuisance-tripping. **F1 selection is UNCHANGED** (1206L020YR still trips
a shorted module inside the SS34 budget); the reduced 45 mA allowance takes the D17 worst
case to ~**0.775–0.975 A**, which only *widens* the SS34 margin — it does not reopen the
SS14 decision. **If any J16 module (≤ 45 mA cap) ever populates, re-run this table anyway.**

**Polyfuse — TAKEN (Codex R2-4, round 2):** the "open option" below is now the fitted
F1 (`1206L020YR`, VCC_5V → J16 pin 1) plus the TCA4307/SRV05-4/JP1 stack. Historical
note retained: *the pre-round-2 spec listed a series polyfuse as an untaken option.*
Any F1 substitute must have **minimum Ihold at 85 °C ≥90 mA**. Matching the
nominal trip current is not sufficient: PPTC trip behavior depends on time and
temperature and is not a hard current clamp.

**rev-D.1 upgrade path (recorded, NOT this spin — needs copper):** replace the PPTC + ESD
with a current-limiting **eFuse / e-load-switch that has a hardware-programmable current
limit AND an open-drain FAULT flag routed to a spare RP2040 GPIO** (part class: TI
**TPS2660** industrial eFuse w/ /FLT, TI **TPS25200** 5 V eFuse w/ FAULT, or Nexperia
NX5P-class), so a wedged/over-drawing J16 module becomes a firmware-diagnosable event
rather than a silent trip with a long PPTC reset tail.

---

## I. Ordered implementation sequence (each step gates the next)

All new files; nothing existing is edited. Python on this laptop: `py -3` (the `python` MS-Store
stub trap). pcbnew steps run under KiCad 10's bundled python
(`C:\Program Files\KiCad\10.0\bin\python.exe`) — see `project_phase8a_pcb_toolchain` gotchas.

1. **Netlist:** copy `scripts/generate_kicad_netlist_revB.py` → `scripts/generate_kicad_netlist_revD.py`.
   Apply §A/§C/§D/§E/§F deltas (append-only ordering per §C.2/§C.3). Update the docstring +
   silkscreen-facing rev strings to REV-D. Output to **`kicad/wsl-phase8b-revD.net`** (new
   filename — never overwrite `wsl-phase8b.net`). Expect: **252 parts, 213 nets**
   *(original items-A–G figures; **262 parts / 217 nets** after remediation spec R1.7 —
   the implemented state)*, **0 netlist-generation errors; ERC = exactly 1 waived error
   (WVR-ERC-1, the Pico AGND/GND POWER-OUT pin-type artifact) + 40 baseline warnings —
   enforced fail-closed by the generator's own `check_erc_waiver()`; any drift aborts** (supersedes the earlier
   "0 SKiDL/ERC errors" wording — the rev-C generator never ran ERC, so rev-D defines the
   baseline; see gate OG-2). Confirm J15/J16 refdes landed as specified; the emitted sklib
   will be `generate_kicad_netlist_revD_sklib.py` (new file, fine).
2. **Footprint-vs-datasheet gate (rev-C process item 10 — scripture):** per part class touched:
   PC817B vs LCSC C5692981 pad map; MCV 1x10 / 1x06 vs Phoenix 1840447/1840405 mating; 0805
   passives; SS34-in-SMA (the D17 swap IS taken — MDD C8678 SMA verified). Record the review
   in the run log — **`docs/phase8_revD_run_log.md` (created 2026-07-20; the gate had run
   without a recorded artifact — do not let that recur)**. Regression:
   K1–K7 relay map unchanged from G1/G2 (pads 2/5 coil, 1 COM, 3 NO, 4 NC).
3. **Placement:** copy `place_components_revB.py` → `place_components_revD.py`; point it at the
   revD netlist and output **`kicad/wsl-phase8b-revD.kicad_pcb`**; apply §B moves + §C.4
   re-pitch + new-part placements (§A/§D/§E/§F) + USB keep-out drawing + TP-strip relocation +
   REV-D silkscreen ID. **Copy** `kicad/wsl-phase8b.routed-manual.kicad_pro/.kicad_prl/.kicad_dru`
   to `wsl-phase8b-revD.*` sidecar names (sidecars travel with the board; the .dru carries the
   isolation rules).
4. **Netclasses:** copy `apply_netclasses_revB.py` → `apply_netclasses_revD.py`; add the two
   classifier edits (§H.1); run — must print 93/4/13/82/21 *(now **97/4/13/82/21** post-R1.7)*
   with zero unknown/overlap.
5. **Route:** copy `manual_route_revB.py` / `export_specctra_revB.py` → revD names as needed;
   re-route (the §B region is a full re-route anyway). DRC with the carried .dru: 0 violations /
   0 unconnected / 0 footprint errors.
6. **Audit:** new `audit_revD_board.py` (copy of the revB auditor) with expected counts
   {93, 4, 13, 82, 21}, 213 nets *(now {97, 4, 13, 82, 21}, 217 nets post-R1.7)*, plus the
   carried invariants: Default==0, no N$*, rail reaches
   exactly 7 K-coils + pass-FET, no OUT_* on the Pico, GND/FIELD_GND distinct with zero shared
   nodes, SAFE_ nets present with **no new pads beyond rev-C's membership** (guards §E scope),
   M1 channel still DNP. ALL PASS required.
7. **Fab export:** new `export_fab_revD.py` — REV and output dir are PARAMETERS; writes ONLY to
   **`kicad/fab_revD_<date>/`**; **refuses to run if the output dir exists** (no rmtree of
   anything, ever — change-list item 12, the rmtree incident). Package manifest carries
   sha256 + `generated_at` + source-board name like the rev-C package.
8. **Gerber manual inspection** (G5 pattern): K1–K7 pad-net map on the plots; new opto-bank and
   J15/J16 pads; USB keep-out visually clear; JLC upload preview vs this spec before paying.
9. **First-article gate** (extend the readiness-checklist §4 per-board pass): rails incl.
   **TP4 ≤ ~6 V unloaded (item A)**; i2cdetect 0x20/0x21/0x22; 6-relay make/break; ordinary
   micro-B cable seats + UF2 flash with ribbon mated (item B); 8 × GPB input pokes (item C);
   GP26 ≈ VCC_5V/2 ±3 % and coil-load sag visible (item D); tap levels + fault-injection +
   forced rail-predicate edge ordering (item E; causal predicates only, not direct
   `RELAY_ENABLE_RAIL`/TP16 observation); J16 bus check with a scrap module (item F).
   One channel of each NEW I/O type energized before trusting the board (process item 11).
   The generated pack also carries two system-level gates that bare-board tests
   cannot discharge: FA-13 keeps physically open J14.3–4 installation-NO-GO
   until an approved Stop/control-power interface is landed, proves bounded
   Stop→power-drop behavior, and closes the lane-21/22 pit-interlock disposition.
   Those lanes have no C.I.S.; any installed/new pit interlock is tested
   separately in its approved upstream safety-disconnect path, because J14-only
   gating cannot replace a final disconnect. FA-14 requires
   qualified-electrician/listed-tester protective-earth and hot/neutral
   polarity proof. Neither mains nor PE-test current may enter Rev-D.

---

## J. Item-to-source citation index

| Item | Primary sources |
|---|---|
| A | change list §5; catalog §2 item 1; readiness §4 (11 V measurement); generator `block_supplies()` 454–469 |
| B | change list §3 (+§2 SWD DROPPED); catalog §2 item 2; `place_components_revB.py:198,206`; readiness §3 consumables note |
| C | catalog §2 item 3; generator `opto_input()` 235–255 + `SLOW_INPUT_PINS` 105–130 + `block_connectors()` 367–451; `08_opto-inputs.md` §8.2/§8.4; readiness §3 (Phoenix PNs), change list §4 (BOM-gap lesson) |
| D | catalog §2 item 4 (incl. the critic's RELAY_ENABLE_RAIL-divider deletion); `06_board-power.md` §6.1–6.2; generator `block_rp2040()` |
| E | catalog §2 item 5 (grant) + item 6 (SAFE_* exclusion) + §1.15; generator `block_watchdog()` 317–364 + `block_rail()` 472–511; `place_components_revB.py` TP list 339–360; `10_watchdog-rail.md` |
| F | catalog §2 "Do NOT" (external analog, permanently) + §3 item 4; generator J_PI wiring 401–412 (J1 fully consumed); 0x23 comment line 529 |
| G | catalog "Nice-to-have" OUT-B row (zero diagnostics yield); constraint 10 (shrink) |
| H/I | `apply_netclasses_revB.py` / `audit_revB_board.py` (counts + fail-closed pattern); change list §10–12 (process gates); `phase8b_pcb_revB_spec.md` (netclass history, 184-net baseline) |
