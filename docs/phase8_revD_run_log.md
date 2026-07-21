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

### COR-2 — NE555 tap-read worst-case bound was optimistic (2026-07-20 sweep)

The spec §E.2 line "bounded ≤ 3.27 V < 3.3 V" assumed 555 VOH ≤ 3.75 V. At light load
(Thevenin ≈ 87k → µA-class draw) a bipolar 555's VOH can reach ≈ VCC−1.2 ≈ 4.05 V at the
5.25 V worst rail → divider read ≈ **3.53 V**: above VDD 3.3 V, below the RP2040 3.6 V
absolute maximum, pad-clamp current bounded to single-digit µA by the ≥ 100 kΩ source
impedance. Electrically safe — no netlist/value change; spec §E.2 + checklist G1 text
corrected. (This was the verify pass's "optimistic prose bound" observation, now closed.)

### COR-3 — "J_PI unchanged" was a recommendation, not the as-placed truth (2026-07-20 sweep)

As placed by `place_components_revD.py`: `J_PI` moved (126, 10, 90) → **(135.5, 10, 90)**
(+9.5 mm right) and `RP_PICO` landed at **(100, 33, 0)**, not the spec table's recommended
(92, 33, 0) (Rpu-column courtyard collision; Rpu column itself moved x 92→86). The spec table
was RECOMMENDED-VERIFY so the deviation is sanctioned; the change-list item-B line stating
"J_PI unchanged" as fact was wrong and is corrected. Consequence folded into **OG-1**: the
enclosure re-check must also cover Pi ribbon length/dress and the ribbon opening position.

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

### 2026-07-20 open-issues sweep (pre-routing clean-slate pass)

Walked every open item from the readiness checklist (G1–G14), the change-list STATUS block,
and the build campaign's recorded risk register before starting routing. Confirmations:

- **D_PROT = SS34 is IN the netlist** — `kicad/wsl-phase8b-revD.net` line ~623 `(value
  "SS34")`; diff records it as the sole whitelisted CHANGED_PART (FR-3). The build-phase risk
  note "SS34 recommendation not reflected in the netlist" is OBSOLETE — closed by the
  review-fix pass.
- **WVR-ERC-1 is enforced fail-closed** — `generate_kicad_netlist_revD.py::check_erc_waiver()`
  exits 2 on any drift in error count, warning count, or error identity (verifies the emitted
  `.erc` text against the waived substring) and runs unconditionally in `main()` before the
  netlist is written.
- **Footprint-review run log covers every new part class** — FR-1 (PC817 ×8), FR-2 (MCV 1×10
  J15 / 1×06 J16 + mating plugs), FR-3 (SS34/SMA), FR-6 (0805 passives incl. the one new 680k
  value), FR-7 (K1–K7 pad-map regression). Verify pass independently confirmed the only new
  (value, footprint) classes are 100nF-0805, 680k-0805, and the two Phoenix MCV variants.
- **Coding-key requirement captured end-to-end** — CP-MSTB 1734634 in checklist G13 harness
  BOM table + OG-3 + FR-4/FR-5 + change-list C/F; board file carries all 4 silk warnings
  ("KEYED: NOT J15" / "NOT J3" / "NOT J16" / "NOT J13 LAMP").
- **Verify pass's 4 minor observations dispositioned:** (1) generator-docstring "0 ERC errors"
  nit — already fixed in the review-fix pass (docstring now states the 1-error waiver);
  (2) NE555 tap prose bound — closed as COR-2; (3) opto placement pitch is 5.70 mm vs the
  courtyard-true 5.68 mm cited in prose — cosmetic, placement DRC 0, no action; (4) the USB
  keep-out envelope is Dwgs_User documentation text, NOT a DRC rule area — DRC will NOT
  police it; the router and G12 visual inspection must (routing-phase watch item).
- **REFDES_SHIFT cross-reference** — 46 refdes shifted rev-C→rev-D (watchdog/rail/lamp/snubber
  R families, U_WDOG U36→U44, ISO_WET U37→U45). `kicad/revD/netlist_diff_revC_to_revD.txt`
  is the authoritative cross-reference; never probe a rev-D board from rev-C photos/notes.
- **Sidecar re-copy trap (standing)** — re-copying `.kicad_pro/.prl/.dru` from rev-C over the
  revD sidecars silently reverts netclass assignments to 184; after ANY sidecar operation
  re-run `apply_netclasses_revD.py --write` + `audit_revD_board.py` (the 2026-06-03
  false-green lesson).
- **Generator artifacts exist at BOTH repo root and `scripts/`** (root = rev-C convention,
  `scripts/` = this campaign's cwd) — sklib copies byte-identical; the two `.erc` copies carry
  the identical 1-error + 40-warning baseline (warning ORDER is nondeterministic between runs;
  only counts + the error identity are contractual).
- **Backup posture (Dylan's directive)** — rev-C: snapshot `backups/revC_design_snapshot_
  2026-07-19/` (189 files, MANIFEST.json; gitignored by design) + external mirror
  `C:\Users\Dylan DeYoung\WSL_Backups\2026-07-20_phase8_revC_revD\` (418 files, manifest) +
  `...zip` with `.sha256`. Rev-D: committed in `230f217` + same external mirror. Hash verify
  this sweep: 189/189 UNCHANGED before and after all edits.
- **Cleanup** — removed `kicad/revD/wsl-phase8b-revD.kicad_pcb.bak` from git + disk (stale
  pre-final intermediate, hazard of being opened as the board; `--force` reruns recreate one)
  and gitignored `kicad/revD/*.bak`.

Resulting open-gate set (nothing else remains): **G7** (powered-session or explicit waiver,
items 6–7) · **G8/OG-1** (Dylan 240 mm sign-off + enclosure re-check incl. ribbon, BLOCKS
routing start) · **G9–G12** (route → post-route DRC/audit → write `export_fab_revD.py` →
Gerber/JLC inspection) · **G13/OG-3** (harness + coding-part order) · **G14** (Dylan doc
review) · first-article §2 incl. OG-4 at-temperature tap test · characterization session
(analog population, DC1–DC3).

## 2026-07-20 — ROUTING (G9 + G10 evidence)

- **Board fully routed** by the NEW `scripts/route_revD.py` (+ `route_revD_lib.py`,
  `route_revD_logic.py`) — manual/deterministic in the rev-C house style, but every pass
  re-derived for the rev-D placement (the rev-C router's geometry does not transfer:
  Pico at the top edge with on-module TP4-6/debug pads, 40-row 5.7 mm column, Rpu at 86,
  AUX/tap/divider/J15/J16). Layer discipline: In1 horizontals, In2 verticals, B.Cu
  power backbones + GPA staircase elbows + field backbones, F.Cu stubs; F.Cu GND zone in
  the LOGIC room only (rev-C pattern; no planes in FIELD/MACHINE). Machine-side passes
  carry the rev-C pattern (contact cores B.Cu/In2, escapes at x=216/228, COIL_LO trunk
  166.8, rail spine x=160 with K-coil doglegs).
- **Self-check**: the router carries a built-in geometric checker (added-copper vs
  added-copper, vs every numbered pad, vs keep-out rule areas, netclass-aware
  clearances) — 0 problems at generation.
- **Gate results**: kicad-cli DRC (`kicad/revD/DRC-revD-routed-r2.rpt`):
  **0 violations / 0 unconnected / 0 footprint errors** (creepage .kicad_dru live,
  netclasses re-applied via `apply_netclasses_revD.py --write` BEFORE the DRC —
  false-green lesson). `audit_revD_board.py` board mode WITHOUT `--pre-route`:
  **ALL PASS** (93/4/13/82/21, GND zone filled, connectivity 0 unconnected).
- **Rev-C sacred check**: snapshot manifest re-verified 189/189 unchanged after routing.
- Note: `route_revD.py` re-runs assume the pristine (git) placement board — restore
  `kicad/revD/wsl-phase8b-revD.kicad_pcb` from git before re-running (the script clears
  tracks but reloading a previously zone-filled board through the zone-removal path can
  crash pcbnew's swig layer).

Open gates after this session: **G7** · **G8/OG-1 sign-off (routing executed on the
240 mm board per the standing fallback-3 layout — OG-1 recording still required before
fab)** · **G11-G12** (export_fab_revD.py + Gerber/JLC inspection) · **G13/OG-3** ·
**G14** · first-article §2 · characterization.
