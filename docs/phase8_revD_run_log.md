# Phase 8 Rev-D — Run Log (process gates, waivers, and open sign-offs)

Created 2026-07-20 (review-fix pass). This is the run-log artifact required by
`phase8_revD_change_spec.md` step I.2 ("Record the review in the run log") — the I.2/I.3/I.4
steps had executed without one; this file backfills the reviews (each genuinely performed on
2026-07-20 against the live footprint files / vendor listings) and is the standing place for
every later rev-D gate record. Append-only.

---

## OPEN GATES (blocking — mirror of spec §0-pre)

### OG-1 — Board growth 250×225 → 250×240 mm: **PENDING DYLAN SIGN-OFF + ENCLOSURE RE-CHECK**

- Spec C.4 fallback 3 (the sanctioned last resort) was executed in `place_components_revD.py`
  (`BOARD_H = 240.0`) with the required owner sign-off **not yet given**.
- Arithmetic verified honest 2026-07-20: DIP-4_W7.62mm F.CrtYd rect in the KiCad 10 footprint
  file spans y −1.52…+4.07 = **5.59 mm** (pcbnew bbox reads 5.68 mm with stroke). 40 rows at
  the true minimum pitch need ≥ ~222.5 mm of column and the top edge is occupied (ISO_WET,
  J2/J1 band) — fallbacks 1–2 cannot fit 225 mm. Growth or 36 rows are the only real options.
- Consequence of 240 mm: bottom mounting holes moved to y=236; `phase8_pair_enclosure_spec.md`
  (250×225, "assumed NOT to shrink") panel/standoff math is invalidated for rev-D.
- **Until Dylan signs off here (append the sign-off line below): do NOT treat step I.5 routing
  as fab-gating, and do NOT order enclosures/subpanels/backplates.**
- Sign-off record: _____________________________ (date / decision / enclosure re-check result)

### OG-3 — Cross-mate keying parts must be ON the harness order before first article

See FR-4/FR-5 below. Coding profiles CP-MSTB **1734634** (Phoenix, 6 per coding star) + the
plug-tab cuts are harness-BOM items; first article includes a physical cross-mate refusal test
(each coded plug must REFUSE the wrong header).

---

## Footprint-vs-datasheet reviews (spec step I.2, rev-C process item 10 — "scripture")

### FR-1 — PC817B (UMW, LCSC C5692981) vs `Package_DIP:DIP-4_W7.62mm` — PASS

- Footprint: 4 pads, 2.54 mm pitch, 7.62 mm row spacing (KiCad 10 file read 2026-07-20).
  PC817-series DIP-4 outline is 2.54/7.62 THT — matches.
- Empirical anchor: 40 PC817 channels on this EXACT footprint are assembled and validated on
  the rev-B/rev-C physical board #1 (bench bring-up + machine-22 field input-side PASS,
  GS map 10/10). Rev-D adds 8 more instances of the same part class, no pad-map change.

### FR-2 — MCV 1x10 / 1x06 headers vs Phoenix mating plugs 1840447 / 1840405 — PASS

- `PhoenixContact_MCV_1,5_10-G-3.5_1x10` ↔ MC 1,5/10-ST-3,5 (1840447): proven pair on J3 on
  the as-ordered rev-C board. J15 duplicates the class unchanged.
- `PhoenixContact_MCV_1,5_6-G-3.5_1x06` ↔ MC 1,5/6-ST-3,5 (1840405): proven pair on J13
  (rev-C). J16 duplicates the class unchanged.
- Same-series MC 1,5 / MCV 1,5 3.5 mm system; polarization covers reversed insertion only —
  cross-mating between same-PN pairs is handled by FR-4/FR-5 coding.

### FR-3 — D_PROT diode swap SS14 → SS34 in SMA — PASS (package trap checked)

- Driver: spec §H.4 — rev-D worst case 0.73–0.93 A on a 1 A SS14, and J16's sanctioned 100 mA
  module allowance exceeds 1 A. Generator (BOM source of truth) now emits **SS34**.
- Gate-10 package check (the G5LE-1/-14 trap class): chosen MPN **MDD (Microdiode) SS34,
  LCSC C8678 — listed package SMA (DO-214AC), 40 V / 3 A** (LCSC/JLC listings checked
  2026-07-20). SS34 from other vendors ships in SMB/SMC — **any MPN substitution re-runs this
  review.** Footprint `Diode_SMD:D_SMA` unchanged; zero copper change.
- Open option recorded (Dylan decision): polyfuse ~200 mA hold in series with J16 pin 1
  (adds a part + net + budget re-run; not taken this spin).

### FR-4 — J3/J15 cross-mate coding (same 1840447 plug, same field edge) — DECIDED

- Hazard: swap is same-domain, wetted identically, silent — crosses cycle sensors with AUX.
- Coding: CP-MSTB 1734634 profiles — **J3 coded at pole 1, J15 coded at pole 10**; distinct
  harness band colors (J3 white, J15 yellow); silk "KEYED: NOT J15"/"KEYED: NOT J3" placed by
  `place_components_revD.py`.

### FR-5 — J13/J16 cross-mate coding (same 1840405 plug, same edge, 24 mm apart) — DECIDED

- Hazard: pins 1/2 are VCC_5V/GND on both; lamp harness in J16 = resistorless LED strings
  across 5 V→GND and onto SDA/SCL (330R limiters are on-board behind J13); I2C wedge leaves
  MCP_OUT_A holding last relay state.
- Coding: **J13 coded at pole 1, J16 coded at pole 6**; band colors (J13 white, J16 blue);
  silk "KEYED: NOT J16"/"KEYED: NOT J13 LAMP".

### FR-6 — 0805 passives (2k2/10k/100k/680k R, 100nF C) — PASS

Existing `R_0805_2012Metric`/`C_0805_2012Metric` classes, dozens of proven instances on the
as-ordered rev-C board. 680k is the only new VALUE (no new footprint class).

### FR-7 — Regression: K1–K7 relay pad map unchanged — PASS

Rev-D generator `relay_output()` verified 2026-07-20: coil pads 2/5, COM pad 1, NO pad 3,
pad 4 NC unused — identical to the rev-C meter-confirmed map (G1/G2).

---

## Waivers

### WVR-ERC-1 — SKiDL ERC baseline: exactly 1 error + 40 warnings — WAIVED (recorded 2026-07-20)

- The single error: `Pin conflict on net GND, POWER-OUT pin 33/AGND of RaspberryPi_Pico/A1
  <==> POWER-OUT pin 3/GND of RaspberryPi_Pico/A1` — both pins are grounds of the SAME Pico
  module and must be tied; a SKiDL symbol pin-type artifact, electrically benign.
- The rev-C generator never ran ERC (its `.erc` is 0 bytes), so rev-D defines the baseline.
- Enforcement: `generate_kicad_netlist_revD.py::check_erc_waiver()` fails closed on ANY drift
  (second error, different single error, or warning-count change from 40). Updating those
  constants requires a new waiver entry here — that is the point.
- The 40 warnings are the expected unconnected-spare-GPIO / power-drive-level class (full list
  in `scripts/generate_kicad_netlist_revD.erc`).

---

## Corrections

### COR-1 — Item-E "can't-hold" proof was temperature-overbroad (2026-07-20)

The 0.42 V < V_BE hold-off proof in spec §E.2 / the generator comments held only near 25 °C
(V_BE(on) −2 mV/K → ~5–30 µA at 85 °C junction vs the ~5–13 µA that spans the AO3401 Vgs(th)
through the 100k gate pull-up). Spec + generator text corrected; new binding requirements:
firmware never drives GP16–GP19, disarm drives ARM_PERMIT low (never tristate), and the
fault-injection gate repeats AT TEMPERATURE (≥70 °C on the Q_AND_*/Q_RAIL region). Option
NOT taken (safety-rail value change needing its own review): R_RAIL_GATE_PULLUP 100k→22k.

---

## Tool-run records

### 2026-07-20 review-fix pass (findings: item-E temp proof, cross-mate keying, SS34, ERC waiver, OG-1 surfacing)

| Step | Command (abridged) | Result |
|---|---|---|
| Generator + ERC gate | `py -3 scripts/generate_kicad_netlist_revD.py` (cwd `scripts/`) | 252 parts, 213 nets, 0 netlist errors; **ERC waiver gate PASS: 1 error (WVR-ERC-1) + 40 warnings, nothing else** |
| Netlist diff vs rev-C | `py -3 scripts/diff_netlist_revC_to_revD.py` | **RESULT CLEAN**; sole CHANGED_PART = D_PROT SS14→SS34 (whitelisted, FR-3) |
| Netlist audit | `py -3 scripts/audit_revD_board.py kicad/wsl-phase8b-revD.net` | **ALL PASS** (93/4/13/82/21, 213 nets, SAFE_ membership frozen, taps on pins 21/22/24/25) |
| Placement | KiCad-10 python `scripts/place_components_revD.py --force` | 252 placed, 0 missing footprints; OG-1 banner prints; new silk cross-mate warnings placed (0.8 mm, moved off 'FIELD INPUTS' after 2 DRC iterations) |
| Netclasses | KiCad-10 python `scripts/apply_netclasses_revD.py --write` | 93/4/13/82/21 exact, saved |
| Placement DRC | `kicad-cli pcb drc` → `kicad/revD/DRC-revD-placement.rpt` | **0 violations**; 499 unconnected pads (expected — unrouted placement stage, identical to pre-fix baseline) |
| Board audit | KiCad-10 python `scripts/audit_revD_board.py kicad/revD/wsl-phase8b-revD.kicad_pcb --pre-route` | **ALL PASS** (zone fill advisory only, per --pre-route) |
| Rev-C integrity | sha256 of all rev-B/rev-C scripts + `kicad/` top-level design files, before vs after | verified unchanged (see session record) |
