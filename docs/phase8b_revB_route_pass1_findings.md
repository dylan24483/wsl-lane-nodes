# Phase 8b Rev-B Route Pass 1 Findings

**Status:** BARE PCB FAB PACKAGE GENERATED (2026-06-03) - routed-manual board is DRC-clean with the netclass project active, and the fab export package has been generated from the gated board. Live gates: `kicad/wsl-phase8b.routed-manual.kicad_pcb` + copied `.kicad_pro/.kicad_dru`, `kicad/DRC-revB-routed-manual-classed.rpt` = **0 DRC violations / 0 unconnected pads / 0 footprint errors**, `scripts/audit_revB_board.py` = **ALL PASS**, and `kicad/fab_revB_routed_manual/` contains gerbers/drill/BOM/CPL/review reports with DRC/audit repeated.

## FAB PACKAGE (2026-06-03): GENERATED FROM THE ROUTED-MANUAL GATED BOARD

Codex added `scripts/export_fab_revB.py` and generated the first bare-PCB fab package:

- **Gerber/drill upload zip:** `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip`
- **Full handoff package:** `kicad/fab_revB_routed_manual/wsl-phase8b-revB-fab-package.zip`
- **Manifest + hashes:** `kicad/fab_revB_routed_manual/manifest.json`
- **Fab README:** `kicad/fab_revB_routed_manual/README-fab-package.txt`
- **Review PDF:** `kicad/fab_revB_routed_manual/review/wsl-phase8b-revB-review-layers.pdf`

Export gates inside the package:

- KiCad DRC rerun for fab export: **0 DRC violations / 0 unconnected pads / 0 footprint errors** (`reports/DRC-revB-routed-manual-fab.rpt`).
- Board invariant audit rerun: **AUDIT RESULT: ALL PASS** (`reports/audit-revB-board.log`).
- Board stats + IPC-D-356 netlist exported for review.
- Non-DNP BOM and CPL exclude DNP parts; DNP/excluded CSV is provided separately.
- Front silkscreen now includes board ID/rev, domain labels, top connector labels, field connector labels, motion connector labels, `J13 LED LAMPS`, and `J12 M1 DNP`. The routed board and fab package were regenerated after this label pass and remain DRC **0/0/0**.

Important fab-prep correction: all schematic parts whose value contains `DNP` are now KiCad-flagged as DNP and excluded from BOM/POS, not only the M1 optional channel. Current DNP count is **27**: the 8 M1 optional parts plus all RC snubber/MOV suppression footprints that are intentionally unpopulated until load characterization. The assembly BOM has **189 non-DNP refs**; the DNP/excluded CSV also includes 20 non-DNP mechanical/test-pad refs excluded from assembly files.

Mechanical note: the current fab package uses conservative copper clearances and all-layer no-copper rule areas for the isolation barriers. It does **not** include milled slots under optos/relays; the DRC/audit gates do not depend on slots. Add slots only as a deliberate mechanical hardening pass followed by a full DRC/export review.

Verdict: **bare PCB fab-ready under the current conservative DRC contract.** This is not assembly/cutover-ready: final uploaded Gerber preview, supplier choice, component sourcing/population decisions, bench validation, and the Track-B cutover gates remain separate.

## ✅ CLAUDE FAB-PACKAGE AUDIT (2026-06-03): ACCEPTED for bare-PCB upload
Independently verified the generated package in `kicad/fab_revB_routed_manual/` (not Codex's report):
- **Gerber/drill set COMPLETE:** `wsl-phase8b-revB-gerber-drill.zip` = 16 entries — all 4 copper layers (F/In1/In2/B), both masks, both silkscreens, both paste, **Edge.Cuts**, PTH+NPTH drills (+maps), `.gbrjob`. Nothing missing for a 4-layer fab.
- **Faithful to the VERIFIED board:** the package was generated from `wsl-phase8b.routed-manual.kicad_pcb` at 20:02 (the DNP-flag pass modified the board AFTER my 19:24 route-audit). Re-ran the gates on that current board: fresh DRC **0/0/0**, audit **ALL PASS**, netclasses **LIVE** (80/13/66/4/21, not Default), DNP=27. The package's own internal gates match exactly (`reports/DRC-revB-routed-manual-fab.rpt` 0/0/0; `reports/audit-revB-board.log` netclasses-live + ALL PASS) — the fab DRC was NON-vacuous (no false-green regression). The DNP-flag change is assembly-only; it does not touch copper, so the bare-PCB gerbers are unaffected.
- **DNP exclusion correct:** BOM (non-DNP) = 189 refs, CPL = 189 placements (consistent); DNP-excluded = 27 (M1 channel + all RC-snubber/MOV suppression parts) + 20 mech/test-pad. **No M1/snubber ref appears in BOM or CPL.**
- **Board:** 250×225 mm 4-layer; min track 0.25 / clearance 0.2875 / drill 0.30 mm — all within JLCPCB 4-layer capability.
- **"No milled isolation slots" is correct at 24 VAC:** slots boost CREEPAGE for high voltage; at the measured 24 VAC working voltage the 2.5/3.2 mm copper clearance already gives ~3–6× the functional-insulation requirement, so slots are unnecessary. Agree with Codex's documented decision.

**Verdict: ACCEPTED — the bare-PCB gerber/drill upload is sound.** Remaining gate = the documented human step: upload `wsl-phase8b-revB-gerber-drill.zip`, inspect the vendor's layer/drill/outline preview against `review/wsl-phase8b-revB-review-layers.pdf` (mirroring / origin / layer assignment — the one thing a script can't verify), then order. NOT assembly-ready: the BOM's LCSC Part # column is empty (PCBA sourcing is the deferred assembly-prep + the real lead-time item for population). Cost-awareness: 250×225 mm 4-layer is a large board — fine for the 1–2 pilot boards; revisit a size shrink (the optional 24 VAC creepage relax) before the 16-lane fleet run.

**Silk re-audit (2026-06-03, post-silk pass): ✅ verified.** Front silk now carries **19 labels** — board ID/rev (`WSL LANE NODE PHASE 8B REV-B`), 3 domain banners + orientation (`FIELD INPUTS` / `LOGIC / SAFETY` / `MACHINE CONTACTS` / `4L 250x225 INPUTS LEFT OUTPUTS RIGHT`), all connectors by ref+function (`J1 PI`, `J2 5V IN`, `J3 FAST`, `J4 SLOW A`, `J5 SLOW B`, `J13 LED LAMPS`, `J14 SAFETY LOOP`), and all 7 motion outputs by signal (`J6 S`…`J11 M2`, `J12 M1 DNP`). F-silk gerber 126 KB→198 KB. **No silk-over-pad** — `silk_over_copper`/`silk_overlap`/`silk_edge_clearance` checks are enabled (warning) and `--severity-all` DRC = 0 silk items. Copper/DRC/audit/DNP unchanged (0/0/0, ALL PASS, netclasses live 80/13/66/4/21, DNP=27). Upload zip regenerated 21:18 (after the 21:13 board) and carries the new silk (`F_Silkscreen` entry = 197991 bytes); package fab DRC (21:18) = 0/0/0. Minor optional (NOT blockers): per-component refdes stay on F.Fab/hidden (fine for PCBA; mildly inconvenient for hand-assembly), and the bench-bring-up test points (TP13 ARM / TP14 RP_OK / TP15 / TP16 RAIL) are not silk-labeled — a small future nicety for spec §12.9 probing.

**PCBA-BOM re-audit (2026-06-04): ✅ ACCEPTED.** Verified the JLC Standard-PCBA pair (`assembly/wsl-phase8b-revB-jlc-standard-pcba-{bom,cpl}.csv`): **20 unique parts / 174 placed refs / 0 blank LCSC#**; hand-solder refs (A1 Pico, J1–J11/J13/J14, U37 TRACO) + the 27 DNP correctly excluded from BOM+CPL. Board unchanged + still gated (fresh DRC 0/0/0, audit ALL PASS, netclasses live). **Independently web-verified the 4 pinned critical parts on the live LCSC catalog:** C116963 = Omron **G5LE-14 5VDC** coil (THE #1 — 5 V, NOT 12/24; 597 in stock) ✓; C47023 = **MCP23017-E/SO** (I2C, not S17; SOIC-28-300mil) ✓; C5692981 = **PC817B** (DIP-4 THT → JLC wave/THT line) ✓; C7593 = **NE555DR** (TI bipolar SOIC-8, not CMOS) ✓. Minor (not blockers): (1) the relay BOM comment says "SPDT" but G5LE-14 is SPST-NO (1 Form A) — functionally correct (drops into the G5LE-1 footprint, NC pad empty; the design uses COM+NO only), just a label nit; (2) several commodity parts (10nF, MMBT3904, 2N7002, 1N4148WS, AO3401) are mapped to **Extended** LCSC#s where Basic equivalents likely exist — each Extended part adds a JLC per-part setup fee (~$3); optional trim to cut cost. Next: JLC upload dry-run + orientation/part-match preview review.

**Upload-packet sign-off (2026-06-04): ✅ GO.** `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/` verified independently: `01_gerbers.zip` = 16 entries (complete 4-layer + masks/silk/paste/Edge.Cuts + PTH/NPTH drills; no nested zip — it is NOT the transport zip); `02_BOM_JLC.csv` = clean JLC 5-column format, 174 refs / 20 parts, **content-identical part→LCSC to the verified working BOM** (0 mismatches; the byte-diff is column trimming only), 4 critical locks intact, 0 exclusion leak; `03_CPL_JLC.csv` = 174 placements, **byte-identical** to the verified CPL. Board unchanged (mtime 21:38; fresh DRC 0/0/0, audit ALL PASS, netclasses live 80/13/66/4/21). Reference files also present: 04 part-lock-audit, 05 excluded-hand-solder, 06 hand-solder-bom, 07 harness-mating-parts. ⚠️ Upload `01_…gerbers.zip` as the Gerber file (NOT the `…JLC_UPLOAD_READY.zip` transport zip). Only gates left are at JLC: the PCBA preview (part orientation / footprint match — esp. PC817 DIP-4 pin-1 + relay/MCP rotation) + Extended-part stock confirmation at order time.

## CODEX CORRECTIVE PASS (2026-06-03): FALSE-GREEN RESOLVED

Claude's audit below was correct: the earlier 0-DRC was vacuous because the routed project lost KiCad 10 netclass assignments. Codex corrected the workflow and route:

- `scripts/manual_route_revB.py` now copies `.kicad_pro`, `.kicad_prl`, and `.kicad_dru` sidecars to the routed output before loading the board.
- The route script now fails closed with `assert_netclasses_active()` unless all 184 named nets resolve to the expected custom classes: Logic_Signal 80, Logic_Power 4, Safety_Rail 13, Field_Sense 66, Machine_Output 21.
- `scripts/audit_revB_board.py` now treats netless unfilled zones as isolation keepout rule areas, not missing copper pours.
- J_MOTION was split from one dense terminal block into seven function-named 2-pin terminal blocks (`J_MOTION_S`, `J_MOTION_T`, `J_MOTION_SP`, `J_MOTION_BE`, `J_MOTION_M`, `J_MOTION_M2`, `J_MOTION_M1`), removing the compression that drove many machine-output spacing failures.
- `Machine_Output` base clearance is now 0.35 mm local fabrication clearance; the `.kicad_dru` still enforces independent output-channel spacing at 1.5 mm and LOGIC-to-MACHINE at 3.2 mm.
- The final safety/watchdog route cleanup moved `BASE_AND_RP_OK`, `ARM_PERMIT`, `SAFE_STOP_RETURN`, and `NE555_OUT` out of the conflict corridors that produced the post-audit 13-violation baseline.

Final proof from the live files:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\manual_route_revB.py
& "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --units mm --output kicad\DRC-revB-routed-manual-classed.rpt kicad\wsl-phase8b.routed-manual.kicad_pcb
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb
```

Results: **0 DRC violations, 0 unconnected pads, 0 footprint errors, audit ALL PASS.** The audit confirms netclasses are live on the routed project, RELAY_ENABLE_RAIL reaches all seven coils + flybacks + pass-FET + TP16, no OUT_* net touches the Pico, GND/FIELD_GND remain distinct, keepout rule areas are present, and M1 optional channel remains DNP.

## ✅ CLAUDE RE-AUDIT (2026-06-03, corrective pass): ACCEPTED — the green is REAL this time
Independently re-verified against the LIVE files (not Codex's report, and not relying on Codex's edit to the audit tool):
- **Fresh `kicad-cli pcb drc` = 0 / 0 / 0** on the current board (board mtime 19:24, my DRC 19:34).
- **Netclasses are LIVE:** `pcbnew.GetEffectiveNetClass()` over all 184 nets → Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21 — **NOT `Default:184`** as in the false-green. So the `.dru` `hasNetclass()` isolation rules actually fired → the 0-DRC is non-vacuous.
- **Rules were NOT relaxed to pass:** `wsl-phase8b.routed-manual.kicad_dru` is byte-unchanged (LOGIC↔FIELD 2.5, LOGIC↔MACHINE 3.2, independent-output 1.5 mm). The route was corrected to satisfy the contract. (The 0.35 mm is only the Machine_Output netclass base floor; the 1.5 mm `.dru` rule overrides it for inter-channel spacing.)
- **Root cause fixed:** routed `.kicad_pro` now carries **103** netclass refs = identical to the source project (was **1**). `manual_route_revB.py` copies the sidecars + `assert_netclasses_active()` fails closed.
- **Safety topology intact:** RELAY_ENABLE_RAIL → K1–K7 + 7 flybacks + pass-FET + TP16; RP2040_OK→A1.4; no OUT_* on the Pico; GND(93)/FIELD_GND(6) distinct.
- **J_MOTION split verified:** J6-J12 = S/T/SP/BE/M/M2/M1; **only J12 (J_MOTION_M1) is DNP** among the motion connectors (with the 8 M1 optional-channel parts). J_SAFETY (J14) + J_PI (J1) are populated. At this route-audit checkpoint, DNP=9 was the correct connector/channel check.
- **Superseding fab-prep DNP note:** after export prep, all value-DNP suppression parts are also flagged DNP/exclude-from-BOM/exclude-from-POS. Current fab package DNP count is **27** (M1 optional channel + all unpopulated RC snubber/MOV footprints).
- **Reviewed Codex's edit to `scripts/audit_revB_board.py`:** the critical netclass-population check (the one that caught the false-green) is UNCHANGED; only the zone check was corrected to recognize netless keepout rule-areas (a legitimate fix to Claude's earlier false alarm). The tool was not weakened.

**Historical verdict at that checkpoint: route-complete for the current DRC contract - ACCEPTED.** This has since advanced to the fab-package state above. The remaining gates are upload-preview/human manufacturing review plus assembly and cutover readiness, not route completion.

## CLAUDE AUDIT (2026-06-03, historical): REJECTED - the isolation DRC was VACUOUS
Codex reported 0 DRC / 0 unconnected / 0 footprint errors. Independently re-verified: **connectivity (0 unconnected) and footprints (0) hold, but 0-DRC is a FALSE GREEN — the routed project carries NO net-class assignments, so every `.dru` isolation rule was inert and never checked the LOGIC/FIELD/MACHINE/Safety_Rail spacing.**

**Mechanism (verified on the live files):**
- `wsl-phase8b.routed-manual.kicad_pro` has **1** net-class reference vs **104** in the source `wsl-phase8b.kicad_pro` — the per-net pattern assignments are gone. (KiCad 10 stores net settings in the `.kicad_pro`; `apply_netclasses_revB.py` defaults to the SOURCE board and the route workflow never re-applies them to the routed project.)
- `pcbnew.GetEffectiveNetClass()` over all 184 routed nets → **all "Default"** (same method on the source board → correct 80/4/13/66/21).
- Every `.dru` rule is conditioned on `hasNetclass('Field_Sense'|'Machine_Output'|'Safety_Rail')`. With every net Default, those conditions match nothing → DRC enforced only the 0.2 mm default clearance + the physical keepout gutters + connectivity.

**Proof (non-destructive, on copy `kicad/wsl-phase8b.nc-audit.*`):** re-applied classes (`apply_netclasses_revB.py --board <copy> --write` → 184 nets, 80/4/13/66/21) and re-ran the identical DRC → **0 → 167 violations**:
| rule | count | min | worst actual |
|---|---|---|---|
| Safety_Rail clearance | 114 | 0.30 mm | 0.2505 mm |
| MACHINE independent output clearance | 44 | 1.50 mm | 0.55 mm |
| LOGIC↔FIELD clearance | 5 | 2.50 mm | 0.2505 mm |
| LOGIC↔FIELD creepage | 4 | 2.50 mm | 0.2505 mm |

No LOGIC↔MACHINE violations — the machine-band gutter held. The breaches are safety-rail traces packed at ~0.25 mm, machine output channels <1.5 mm apart, and a few logic↔field crossings.

**Historical verdict at this checkpoint: NOT route-complete / NOT fab-ready.** The route packed traces tighter than the isolation contract because the constraining rules were not active during routing. This verdict was resolved by the Codex corrective pass above.

**Required at the time (completed by Codex corrective pass above):**
1. **Persist the classes into the routed project** — the route workflow must run `apply_netclasses_revB.py --write` on the **routed** board (root cause: assignments must end up in `wsl-phase8b.routed-manual.kicad_pro`, not just the source).
2. **Re-route to honor the per-class rules** (Safety_Rail clearance ≥0.30, Machine_Output independent ≥1.50, LOGIC↔FIELD ≥2.50 clearance+creepage). The LOGIC↔FIELD set may shrink under the queued 250 VAC→24 VAC creepage relax, but the **Safety_Rail 0.30 mm (114) and output↔output 1.50 mm (44) breaches are intra-domain and will NOT clear from that** — they need real re-routing.
3. **Gate DRC with net classes applied** — assert `wsl-phase8b.routed-manual.kicad_pro` carries the assignments (or run `apply_netclasses` first) before trusting any DRC pass. A DRC run on a class-less project is meaningless for this board.

Independent audit tool added: `scripts/audit_revB_board.py` (checks netclass population + safety-rail/OUT-on-Pico/GND-FIELD_GND/zone/DNP invariants). Topology that DID pass: RELAY_ENABLE_RAIL reaches all 7 coils + 7 flybacks + pass-FET + TP16; RP2040_OK→A1.4 (GP2); no OUT_* on the Pico; GND/FIELD_GND distinct; M1 channel DNP (8 parts); 250×225 mm 4-layer; GND F.Cu pour + 2 keepout gutters.

Codex's first route pass correctly stopped before copper import when the
unrouted placement reported 26 custom-rule violations. Claude audited those
violations and found they were rule/classification issues, not real placement
isolation failures. Codex then applied the corrective pass and reran DRC.
Claude's later placement audit then found the deeper blocker: FIELD, LOGIC, and
MACHINE domains physically overlapped, so isolation keepouts could not be
effective. Codex applied the domain re-banding pass described below.

## ⚡ TWO FIELD-DRIVEN DESIGN CHANGES (2026-06-02)
**1. Status lamps → our own LEDs, logic-driven (Dylan decided; IMPLEMENTED).** The 4 AQY PhotoMOS lamp outputs are removed. The current regenerated netlist uses simple logic LED drivers (2N7002-class low-side FET + gate resistor + pulldown + series resistor) from VCC_5V; LEDs sit in the mask housings but wire back to our board through `J_LAMP_LED`. **No `OUT_L_*`, `Z_L_*`, or `PHOTOMOS_LED_*` nets remain.** Net effect on routing: 8 fewer machine-band lamp contact nets, no lamp isolation crossing, and one lower-logic-band LED connector/driver group. Detail in `phase8b_pcb_revB_BOM_power.md` §4.

**2. A1 working voltage = 24 VAC (below) → creepage can relax.**

## ⚡ A1 FIELD RESULT LANDED (2026-06-02) — affects the creepage numbers Codex is routing to
**Machine-output working voltage measured = 24 VAC** (all accessible relays; SP presumed). The board's isolation barriers were sized for a CONSERVATIVE 250 VAC assumption (≥3.2 mm LOGIC↔MACHINE, ≥2.5 mm LOGIC↔FIELD). At 24 VAC working they can relax to **functional-insulation ~0.5–1.0 mm**.
- **For the routed-manual board:** routing to the current (wide, 3.2 mm) gutters is still VALID — a tighter rule satisfied by looser geometry stays satisfied when the rule relaxes. So **no rework for copper already routed to the wide spec.** If future placement shrink work is desired, relax `wsl-phase8b.kicad_dru` to the 24 V numbers first.
- **Before final route-LOCK:** update `kicad/wsl-phase8b.kicad_dru` + `phase8b_pcb_revB_netclass_creepage.md` §3 to the 24 V working-voltage clearances, then re-DRC. (The gutters could also shrink in a future placement pass for a smaller board — optional, not required.)
- Detail + the lamp (A3=15 VDC) and cam (A4=dry contact) results in `phase8b_pcb_revB_BOM_power.md`.

## Historical Claude Audit of routed-manual board (2026-06-03): partial-route progress decoded
Historical checkpoint before the final corrective pass: Claude re-ran DRC on `wsl-phase8b.routed-manual.kicad_pcb` and confirmed **0 violations**, 326 unconnected, 0 footprint errors on that partial route. This section is retained only to explain the route progression; current live status is the 0/0/0 class-aware route gate at the top of this file.

**The 326 unconnected decoded (so it's not misread as "barely started"):**
- **~150 are POWER-PLANE pads** (GND ~85, VCC_3V3 ~50, VCC_5V ~12, FIELD_WET ~35) awaiting **copper POURS, not traces** — poured last; ~150 clear at once when In1/In2/field planes drop in.
- **Remaining logic signals** (SLOW_*, FAST_*, I2C, DRV_*, WDOG/NE555/BASE_AND/RAIL_GATE) = bulk-logic + last safety nets, the tier scheduled last, all low-risk in-band logic room.
- **Machine outputs (OUT_*) 1–2 each** = relay-contact cores routed, snubber pads deferred (intended).

**Historical status at that checkpoint:** the hard tiers (field-opto crossings, safety-rail spine, relay-contact cores) were routed DRC-clean, with bulk logic and plane pours still open. The final routed-manual board now has 0 unconnected pads.

## Current Artifacts

- `scripts/export_fab_revB.py`
  - Deterministic fab-export helper for `kicad/wsl-phase8b.routed-manual.kicad_pcb`.
  - Re-runs KiCad DRC and `scripts/audit_revB_board.py`; fails closed unless both are green.
  - Exports gerbers, Excellon drill, board stats, IPC-D-356, review PDF, KiCad CPL, grouped non-DNP BOM, DNP/excluded CSV, README, manifest with SHA256s, and the two release zips in `kicad/fab_revB_routed_manual/`.
- `scripts/manual_route_revB.py`
  - Deterministic manual-route helper; routes only audited tiers by default.
  - Default output: `kicad/wsl-phase8b.routed-manual.kicad_pcb`.
  - Default routed tiers: field opto LED series nets, field connector returns, opto-to-pullup stubs, power backbones, monotonic FAST/U1-left logic input fanout, I2C trunks, GND logic-room pour, selected bottom test-pad tails, watchdog/555 timing locals, watchdog/safety header signals, UART RX/TX, MCP interrupt fanout, logic status LED cluster, relay-driver local nets, full U3 driver fanout, relay-enable rail spine, J_MOTION relay-contact cores, and local `SNUB_*` midpoint links.
  - Optional flag `--skip-machine-outputs` preserves the earlier Pass 1A route without the machine contact cores.
- `scripts/apply_netclasses_revB.py`
  - Applies 5 KiCad net classes to all current board nets.
  - Fails if any net is unknown or matches more than one class.
  - Current counts: Logic_Signal 80, Logic_Power 4, Safety_Rail 13, Field_Sense 66, Machine_Output 21.
- `kicad/wsl-phase8b.kicad_dru`
  - Custom rules for LOGIC-to-FIELD and LOGIC-to-MACHINE clearance/creepage.
  - Independent machine-output channel clearance rule excludes intentional same-channel component terminals.
- `scripts/generate_kicad_netlist_revB.py`
  - J_MOTION is now seven function-named 2-pin terminal blocks (`J_MOTION_S`, `J_MOTION_T`, `J_MOTION_SP`, `J_MOTION_BE`, `J_MOTION_M`, `J_MOTION_M2`, `J_MOTION_M1`) matching the seven motion output pairs; there is no dense unused motion block.
  - J_LAMP is now `J_LAMP_LED`, a 6-pin logic connector for VCC_5V, GND, and four LED returns.
- `scripts/export_specctra_revB.py`
  - Exports `kicad/wsl-phase8b.revB-reband.dsn` by default.
- `scripts/place_components_revB.py`
  - Current deterministic placement source for the re-banded FIELD / LOGIC / MACHINE geometry and physical copper keepout gutters.
- `kicad/DRC-revB-led-logic.rpt`
  - Current DRC after the re-band placement pass plus the logic status-LED regen.
- `kicad/wsl-phase8b.revB-reband.dsn`
  - Specctra export from the clean re-banded source board.

## Manual Route Pass 1B (2026-06-03, historical checkpoint)

Codex started manual routing with a repeatable script rather than importing opaque autorouter copper.

Default routed working board:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\manual_route_revB.py
Copy-Item kicad\wsl-phase8b.kicad_dru kicad\wsl-phase8b.routed-manual.kicad_dru -Force
& "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --units mm --output kicad\DRC-revB-routed-manual.rpt kicad\wsl-phase8b.routed-manual.kicad_pcb
```

Result:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations** with the conservative custom rule file active.
- Historical remaining unrouted state at this checkpoint: **326 unconnected pads**. Final routed-manual board now reports 0 unconnected pads.
- Source `kicad/wsl-phase8b.kicad_pcb` remains the clean unrouted/re-banded board; the routed copper is on the working copy.

Machine-output correction:

- The first machine-output attempt incorrectly let optional suppression pads contaminate the J_MOTION/relay-contact fanout and produced DRC conflicts.
- Corrected approach: route only the safety-relevant relay-contact core (`K*.3/4 <-> J_MOTION`) on unique lanes; hold DNP snubber/MOV pads for a later local pass.
- Corrected machine-contact core is now included in the default routed board and is DRC-clean.
- Remaining DNP suppression footprints are still present but not fully routed; this is a contained follow-up, not a blocker for the accepted contact-core route.

## Manual Route Pass 1C (2026-06-03 continuation)

Historical checkpoint; Pass 1D below supersedes the current DRC/count numbers.

Codex continued from Claude's audited 326-unconnected baseline and added only bounded deterministic tiers. The routed working board remains `kicad/wsl-phase8b.routed-manual.kicad_pcb`; the clean source board remains `kicad/wsl-phase8b.kicad_pcb`.

Additional accepted tiers:

- Power backbones: `FIELD_WET_V`, `FIELD_GND`, opto-side `GND`, opto pullup `VCC_3V3`, component-side `VCC_3V3`, `VCC_5V_RAW`, and protected `VCC_5V`.
- Logic fanout: monotonic FAST input fanout into the Pico, plus the monotonic U1-left slow-input group (`SLOW_GS9`, `SLOW_GS10`, `SLOW_GP`, `SLOW_OS`, `SLOW_BS`, `SLOW_PBZ`, `SLOW_PBC`, `SLOW_FOUL`).
- I2C: SDA/SCL trunks split across inner layers, with bottom test pads intentionally deferred.
- Local control: DRC-clean subset only (`WDOG_KICK_GATE`, `RAIL_GATE`, `BASE_AND_ARM`, `NE555_CTRL`). The attempted `WDOG_OK_GATE`, `BASE_AND_RP_OK`, `NE555_OUT`, and `WDOG_TIMING_NODE` direct F.Cu trunks were rejected and left for a more deliberate dogleg pass.

Current accepted DRC:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations**, **165 unconnected pads**, **0 footprint errors** with the conservative `.kicad_dru` active.
- Routed copper now contains **851 tracks + 244 vias = 1095 routed primitives**.
- Remaining unconnected is now dominated by `GND` plane/pad work (120 report references), deferred watchdog/control nets, the crossing-heavy slow-input groups, header/status/driver control lines, and intentionally deferred `SNUB_*` pads.

## Manual Route Pass 1D (2026-06-03 continuation)

Historical checkpoint; Pass 1E below supersedes the current DRC/count numbers.

Codex continued the deterministic manual route and accepted only routes that stayed clean under the conservative `wsl-phase8b.kicad_dru` rule file. The working routed board remains `kicad/wsl-phase8b.routed-manual.kicad_pcb`.

Additional accepted tiers after Pass 1C:

- GND: added the F.Cu logic-room `GND` zone, bounded to X 80.4-180.5 and Y 4.5-219.0 so it does not enter the FIELD/LOGIC or LOGIC/MACHINE copper gutters.
- Power/signal tails: connected U37 input ground, `VCC_3V3` TP3, `I2C_SDA` TP6, and `I2C_SCL` TP7.
- Relay-driver locals: joined local `DRV_*` resistor-pair pads for the motion/LED driver inputs without attempting the crossing-heavy U3 fanout yet.
- Header logic: accepted `PI_UART_RX`; `PI_UART_TX` and MCP interrupt fanouts remain deferred because the J1/header escape needs a dedicated pass.
- Watchdog/control locals: accepted `WDOG_OK_GATE`, `BASE_AND_RP_OK`, `AND_MID_ARM_RP`, `NE555_OUT`, `WDOG_TIMING_NODE`, `WDOG_KICK_DRAIN`, `NE555_TRIG`, and `WDOG_OK_PULLDOWN`.
- Watchdog/safety header subset: accepted `WDOG_KICK` from J1 to R102, `ARM_PERMIT` from J1 to R107, and `SAFE_STOP_RETURN` from J8 to the Q14/R106 local node. `RP2040_OK` remains deferred because the broad route intersects I2C/RX/header escape channels.

Current accepted DRC:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations**, **75 unconnected items**, **0 footprint errors** with the conservative `.kicad_dru` active.
- Routed copper now contains **950 tracks + 266 vias = 1216 track/via objects**, plus **1 filled GND copper zone** and the 2 existing rule-area keepouts.
- Current route-script total: **1218 route actions added**.

Remaining unconnected is now intentionally bounded:

- Machine band: `OUT_*` suppression/MOV/snubber pads and `SNUB_*` nets remain deferred; relay-contact cores to J_MOTION are already routed.
- Bulk logic: `SLOW_GS1`-`SLOW_GS8`, `SLOW_TENTH`, `SLOW_MAN_*`, `SLOW_AUX*`, the U3 `DRV_*` fanouts, `PI_UART_TX`, `MCP_INT_A`, `MCP_INT_B`, and `RP2040_OK`.
- Test pads: bottom monitor pads for `WDOG_TIMING_NODE`, `NE555_TRIG`, `NE555_OUT`, `WDOG_OK_PULLDOWN`, `WDOG_KICK`, `ARM_PERMIT`, `SAFE_STOP_RETURN`, and `RP2040_OK` are not all routed yet.

Next clean routing target: do a deliberate bulk-logic/header fanout pass for the remaining U1/U2/U3/J1 nets, then DRC-gate; keep the machine suppression pads as a separate local machine-band pass.

## Manual Route Pass 1E (2026-06-03 continuation)

Historical checkpoint; Pass 1F below supersedes the current DRC/count numbers.

Codex continued from the Pass 1D 75-unconnected checkpoint and accepted only DRC-clean additions. Several trial routes were deliberately rejected and not left in the board: the `SLOW_GS1`-`SLOW_GS8` reversed-order fanout needs a more deliberate corridor, the full OUT_A/OUT_B machine suppression endpoints need per-channel trunk entries, and the `NE555_TRIG` monitor tail is boxed in by the SAFE/NE555 monitor lanes.

Additional accepted tiers after Pass 1D:

- Machine suppression: connected the seven local `SNUB_*` midpoint nets (`SNUB_S`, `SNUB_T`, `SNUB_SP`, `SNUB_BE`, `SNUB_M`, `SNUB_M2`, `SNUB_M1`) with local F.Cu doglegs. OUT_A/OUT_B MOV/snubber endpoint pads remain deferred.
- Watchdog/safety monitor tails: connected TP8 `WDOG_KICK`, TP11 `NE555_OUT`, TP12 `WDOG_OK_PULLDOWN`, TP13 `ARM_PERMIT`, and TP15 `SAFE_STOP_RETURN`. TP9 `WDOG_TIMING_NODE`, TP10 `NE555_TRIG`, and TP14 `RP2040_OK` remain deferred.
- Header logic: connected `PI_UART_TX` with a split In1/In2 escape around the I2C trunks; `PI_UART_RX` was already accepted in Pass 1D.
- U3 driver fanout: connected `DRV_SP`, `DRV_T`, `DRV_S`, and `DRV_BE` from U3 into the existing resistor-pair stubs.

Current accepted DRC:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations**, **58 unconnected items**, **0 footprint errors** with the conservative `.kicad_dru` active.
- Routed copper now contains **1007 tracks + 279 vias = 1286 track/via objects**, plus **1 filled GND copper zone** and the 2 existing rule-area keepouts.
- Current route-script total: **1290 route actions added**.

Remaining unconnected is now concentrated in these buckets:

- Machine band: OUT_A/OUT_B MOV/snubber endpoint pads for the seven motion channels. The relay-contact cores and `SNUB_*` midpoint links are routed.
- Bulk slow-input fanout: `SLOW_GS1`-`SLOW_GS8`, `SLOW_TENTH`, `SLOW_MAN_*`, and `SLOW_AUX*`.
- Logic/header/control: `MCP_INT_A`, `MCP_INT_B`, `RP2040_OK`, TP9 `WDOG_TIMING_NODE`, TP10 `NE555_TRIG`, plus the remaining U3/LED driver fanouts (`DRV_M`, `DRV_M2`, `DRV_M1`, `DRV_L_FIRST`, `DRV_L_SECOND`, `DRV_L_STRIKE`, `DRV_L_FOUL`).

Next clean routing target: either (1) a deliberate U3/LED-driver fanout pass using a lane map around the NE555 monitor traces, or (2) a machine-band endpoint pass that assigns per-channel OUT_A/OUT_B entry layers without through-via collisions on existing output trunks.

## Manual Route Pass 1F (2026-06-03 continuation)

Codex continued from the Pass 1E 58-unconnected checkpoint and again accepted only additions that kept the conservative custom-rule DRC clean. The successful work in this pass was concentrated in the remaining U3 driver fanout, J1-to-MCP interrupt escapes, and the first DRC-clean machine suppression endpoint collectors.

Additional accepted tiers after Pass 1E:

- U3 motion-driver fanout: connected `DRV_M`, `DRV_M2`, and `DRV_M1` from U3 into the existing resistor-pair stubs using staggered inner-layer lanes that avoid the `NE555_OUT`, `DRV_T`, and `DRV_BE` via envelopes.
- U3 lamp-driver fanout: connected `DRV_L_FIRST`, `DRV_L_SECOND`, `DRV_L_STRIKE`, and `DRV_L_FOUL`. The accepted paths use short F.Cu pin escapes, layer-separated drops around the I2C/VCC barriers, and right/left pad-entry offsets to clear adjacent LED gate pads.
- Header/controller fanout: connected `MCP_INT_A` and `MCP_INT_B`. `MCP_INT_A` uses an F.Cu top escape and x=130.9 In2 lane into U1. `MCP_INT_B` uses a lower J1 escape to y=4, x=140.0 In2 vertical, and a bottom jog to x=140.3 before entering U2.
- Machine suppression endpoints: connected OUT_A/OUT_B optional MOV/snubber endpoints for the S, T, and SP channels into their existing relay/contact trunks using local In1 collectors. BE/M/M2/M1 endpoints remain deferred because their neighboring output trunks require channel-specific step-over geometry.

Rejected during this pass and not left dirty:

- Broad revival of `route_reversed_slow_input_fanout()` remains rejected: the remaining `SLOW_*` nets share y-levels with already-routed slow nets, so they need a deliberate corridor rather than the old straight horizontal entry.
- Bulk machine `OUT_*` suppression endpoint routing remains rejected: the relay-contact cores are clean, and S/T/SP endpoint collectors are clean, but BE/M/M2/M1 endpoint pads need per-channel entries into existing trunks and should not be attached with a bulk pass.

Current accepted DRC:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations**, **37 unconnected items**, **0 footprint errors** with the conservative `.kicad_dru` active.
- Routed copper now contains **1090 tracks + 316 vias = 1406 track/via objects**, plus **1 filled GND copper zone** and the 2 existing rule-area keepouts.
- Current route-script total: **1410 route actions added**.

Remaining unconnected is now concentrated in these buckets:

- Machine band: OUT_A/OUT_B MOV/snubber endpoint pads for BE, M, M2, and M1 remain. Relay-contact cores, `SNUB_*` midpoint links, and S/T/SP endpoint collectors are already routed.
- Bulk slow-input fanout: `SLOW_GS1`-`SLOW_GS8`, `SLOW_TENTH`, `SLOW_MAN_*`, and `SLOW_AUX*`.
- Logic/control test tails: `RP2040_OK`, TP9 `WDOG_TIMING_NODE`, and TP10 `NE555_TRIG`.

Next clean routing target: superseded by the final manual-route completion below.

## Manual Route Complete (2026-06-03 final)

Codex finished the deterministic manual route and regenerated `kicad/wsl-phase8b.routed-manual.kicad_pcb` from `scripts/manual_route_revB.py`. The source placement board `kicad/wsl-phase8b.kicad_pcb` remains the clean unrouted/re-banded source; routed copper lives in the routed-manual copy.

Final accepted additions after Pass 1F:

- Machine suppression endpoints: completed BE, M, M2, and M1 OUT_A/OUT_B optional MOV/snubber endpoint collectors using channel-specific trunk entries; all `OUT_*` machine endpoint pads are now connected.
- Reversed slow-input fanout: connected `SLOW_GS1`-`SLOW_GS8`, `SLOW_TENTH`, `SLOW_MAN_T`, `SLOW_MAN_S`, `SLOW_MAN_SWS`, `SLOW_MAN_SWSR`, `SLOW_AUX1`, `SLOW_AUX2`, and `SLOW_AUX3` with layer-separated corridors and J7-safe AUX doglegs.
- I2C detours: adjusted R1 and U2 SDA/SCL escapes plus TP6/TP7 tails so the slow-input corridors remain DRC-clean.
- Final monitor/control opens: connected TP9 `WDOG_TIMING_NODE`, TP10 `NE555_TRIG`, and the multidrop `RP2040_OK` net across J1.13, A1.4, R109.1, and TP14.

Final DRC command:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m py_compile scripts\manual_route_revB.py
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\manual_route_revB.py
Copy-Item -LiteralPath kicad\wsl-phase8b.kicad_dru -Destination kicad\wsl-phase8b.routed-manual.kicad_dru -Force
& "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --units mm --output kicad\DRC-revB-routed-manual.rpt kicad\wsl-phase8b.routed-manual.kicad_pcb
```

Final result:

- `kicad/wsl-phase8b.routed-manual.kicad_pcb`: **0 DRC violations**, **0 unconnected pads**, **0 footprint errors** with the conservative `.kicad_dru` active.
- Routed board contents: **1178 tracks + 382 vias = 1560 track/via objects**, plus **3 zones**.
- Current route-script total: **1585 route actions added**.

This is now a routed-board and fab-package review artifact. Fabrication output has been generated in `kicad/fab_revB_routed_manual/`; next gates are uploaded Gerber/drill preview, any desired human zone/silkscreen review, and any future creepage-rule relaxation to the measured 24 VAC working-voltage policy before a later production spin. Assembly/cutover gates remain separate.

## Corrective Pass Applied

1. `SAFE_*` reclassified from Machine_Output to Safety_Rail.
   - `SAFE_STOP_RETURN` and `SAFE_TBSC_RETURN` are low-voltage safety/interlock control nets that deliberately gate the relay-enable rail at Q10/R102/J8.
   - They are not 250 VAC machine-output contact nets and should not be checked against the LOGIC-to-MACHINE barrier.

2. Machine_Output base clearance split from insulation rules.
   - KiCad netclass clearance is now a 0.35 mm same-channel local routing/fabrication floor.
   - The true insulation constraints remain in `wsl-phase8b.kicad_dru`: LOGIC-to-MACHINE >= 3.2 mm, LOGIC-to-FIELD >= 2.5 mm, independent machine-output channel-to-channel >= 1.5 mm.
   - Same-channel terminals such as `OUT_S_A` / `SNUB_S` / `OUT_S_B` are intentionally close and excluded from the independent-channel rule.

3. Dense motion block removed at source.
   - `J_MOTION_OUT` was superseded by seven function-named 2-pin terminal blocks: `J_MOTION_S`, `J_MOTION_T`, `J_MOTION_SP`, `J_MOTION_BE`, `J_MOTION_M`, `J_MOTION_M2`, `J_MOTION_M1`.
   - Current motion terminals are exactly the seven A/B output pairs, with M1 DNP optional until machine-confirmed.

4. Lamp outputs moved to the logic domain.
   - `J_LAMP_LED` is a 6-pin logic connector: VCC_5V, GND, and four LED returns.
   - Each status LED has a local logic-side low-side FET driver and current-limit resistor.
   - No lamp output is a Machine_Output net.

## Current DRC Result

Command:

```powershell
& "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --units mm --output kicad\DRC-revB-led-logic.rpt kicad\wsl-phase8b.kicad_pcb
```

Result:

- 0 DRC violations.
- 488 unconnected pads, expected because the board remains unrouted.

## Routing Decision

No autorouted copper has been imported into the source `wsl-phase8b.kicad_pcb`.

The board is now clean at the pre-route DRC stage and `kicad/wsl-phase8b.revB-reband.dsn`
has been exported from the re-banded source board. However, KiCad's Specctra DSN
export carries the base KiCad net classes and physical keepouts, but not the full
custom creepage-rule intent from `wsl-phase8b.kicad_dru`. Any route must therefore
be reimported and checked with KiCad DRC before it can be trusted.

## FreeRouting Attempts

Codex fetched the official FreeRouting v2.2.4 JAR and a portable Temurin Java
25 JRE because the local Java 21 runtime cannot run the current FreeRouting
classfile format.

- FreeRouting: `tools/freerouting/freerouting-2.2.4.jar`
  - SHA256 `F5ED374182900CCC78E473518BBB9F6B869F4A07159495F663A76F52BB10523B`
- Java: `tools/java25/jdk-25.0.3+9-jre`
  - ZIP SHA256 `A183E7280220AD5F6FE94ECBF025A5F10FC5797A0B18C600ED8F813C8158C530`

Two candidate autoroutes were generated and imported into separate KiCad project
copies. Neither is acceptable for design use.

| candidate | router input | router result | KiCad DRC after import | verdict |
|---|---|---|---|---|
| `wsl-phase8b.routed-pass1.kicad_pcb` | 4-layer DSN `wsl-phase8b.revB-pass1.dsn` | 3 unrouted `VCC_3V3` connections | 473 violations + 3 unconnected | reject |
| `wsl-phase8b.routed-pass2-2layer.kicad_pcb` | F/B-only DSN `wsl-phase8b.revB-pass2-2layer.dsn` | 3 unrouted `GND` connections | 625 violations + 3 unconnected | reject |

After the re-band pass, Codex tried full-board FreeRouting again against
`wsl-phase8b.revB-reband.dsn`:

| attempt | command shape | result | verdict |
|---|---|---|---|
| reband full | `-de kicad\wsl-phase8b.revB-reband.dsn -do kicad\wsl-phase8b.revB-reband.ses` | no `.ses` produced after 30+ minutes; Java process stopped | reject as non-productive |
| reband bounded | `--gui.enabled=false -de ...revB-reband.dsn -do ...revB-reband-mp10.ses -mp 10 -mt 1` | no `.ses` produced after timeout; Java process stopped | reject as non-productive |

The failure mode is not surprising: FreeRouting sees the DSN net classes, but it
does not understand the KiCad `.kicad_dru` isolation-room intent. Pass 1 routed
heavily through `In1.Cu` and `In2.Cu`, creating many LOGIC-to-FIELD and
LOGIC-to-MACHINE creepage violations. Pass 2 removed the inner layers from the
DSN, but still produced many surface clearance/creepage violations because the
autorouter does not know to keep logic traces out of the field room and machine
traces out of the logic room.

## Next Routing Step

The source board remains clean and unrouted. Full-board FreeRouting should not
be treated as a viable route method for this safety-critical board. The next
routing step is:

1. Manually route the isolation-critical nets first in KiCad using the current custom rules and physical gutters:
   FIELD input LED/pullup sides, opto logic sides, safety rail / SAFE_* / watchdog rail-gate chain, relay coils, relay output-contact neighborhoods, and the local logic status-LED driver cluster.
2. Rerun full KiCad DRC.
3. Only after the barrier nets are hand-controlled, optionally autoroute the remaining low-risk logic nets in smaller chunks, then import and DRC-gate again.

## ✅ CLAUDE RE-AUDIT (2026-06-02, post-reband): placement objection RESOLVED; autoroute correctly abandoned
**The re-band worked — verified on the board file.** The domains are now clean, ordered bands with package-level barrier crossings and explicit no-copper rule areas:

| group | X center range (mm) | routing meaning |
|---|---|---|
| FIELD connectors / series resistors | 9 / 58 | field-side routing stays left |
| OPTO barrier packages | 73.9–74.0 | PC817/TMA packages bridge the FIELD/LOGIC isolation boundary |
| FIELD/LOGIC no-copper rule area | 76.8–80.0 | tracks/vias/zones forbidden on all copper layers; pads/footprints allowed |
| LOGIC pullups / core / safety control | 92 / 101–172 | logic-side routing stays center |
| Relay barrier packages | 176.0–178.2 | relay packages bridge the LOGIC/MACHINE isolation boundary |
| LOGIC/MACHINE no-copper rule area | 181.0–184.2 | tracks/vias/zones forbidden on all copper layers; pads/footprints allowed |
| MACHINE suppression / connectors | 222–242 | machine-output routing stays right |

2 multi-layer rule-area keepouts are present in KiCad (exported as per-layer DSN keepouts), 0 DRC, 250×225mm. The old FIELD(34–92)/LOGIC(68–156) interpenetration is gone. **This is exactly the fix I called for — the placement now provides the physical separation the isolation rules require.** Routing is geometrically tractable.

Codex also tested routeability of the corrected FIELD/LOGIC keepout on a temporary board: one field-side trace `R3.2 -> U4.1` and one logic-side dogleg trace `R4.2 -> U4.4` DRC-clean with 0 violations. This matters because an earlier keepout position overlapped the field-side opto pads and would have blocked normal routing into the PC817 pins.

**Autoroute verdict: correctly abandoned.** Two DSN attempts failed to even produce a `.ses`, on top of the known DSN-can't-carry-creepage problem. Full-board FreeRouting has earned a "not the path for this board" call. Agree with Codex 100%.

### ⭐ The manual route is BOUNDED — here's the scope (so it's not a daunting "route 184 nets")
Net triage (`Temp/route_scope.py`):
- **6 power/plane nets** (GND, VCC_5V/5V_RAW/3V3, FIELD_GND, FIELD_WET_V) → **copper POUR per layer, not hand-route.** (GND/VCC = In1/In2 planes with gutter voids; FIELD_GND/WET = small pours in the field band.)
- **~72 bulk logic nets** (FAST_*/SLOW_* logic sides, DRV_*, I2C, UART, BASE_*, etc.) → live **entirely inside the LOGIC band** → low-risk, route last, candidate for *selective* in-band autoroute.
- **The genuinely careful set is SMALL** — the nets that actually cross a gutter or are safety-critical:
  - **Opto LOGIC↔FIELD crossings:** 8 fast (SA/SB/SC/TA1/TA2/TB/DIELL_L/DIELL_R) + ~16 slow = ~24 opto channels, each crossing the FIELD/LOGIC gutter **inside the PC817 body** (the pins are the crossing — route the two sides into their respective bands, short).
  - **Safety rail spine:** RELAY_ENABLE_RAIL, RAIL_GATE, SAFE_STOP_RETURN, SAFE_TBSC_RETURN, the AND chain — **~6 nets, route these FIRST and most carefully.**
  - **Relay coil + output:** COIL_LO_* (7) in the logic/rail side, OUT_*/SNUB_* (21) all **within the MACHINE band** (relay→motion connector, short).
  - **Status LEDs:** LED_* (12) stay **inside the LOGIC band** at the lower logic connector/driver cluster; no machine-domain routing.
- **Note:** the FIELD_* and OUT_* nets are "isolation-critical" but mostly **short same-band runs** (field connector→opto stays in FIELD; relay→connector stays in MACHINE) — they must not *stray* across a gutter, but the gutters + keepouts already enforce that. They're not hard, just disciplined.

**Recommended manual-route order:** (1) pour GND/VCC planes with gutter voids; (2) the ~6 safety-rail nets, by hand, DRC after; (3) the ~24 opto crossings; (4) the in-band MACHINE outputs + coil nets; (5) bulk logic last (hand or careful in-band autoroute); (6) full DRC gate. That's a half-day of focused KiCad work, not an epic — the bands make most nets short and local.

### (historical) the pre-reband problem this replaced
**`place_components_revB.py` needs a domain-banding pass** that puts the three domains in non-overlapping vertical bands with explicit isolation gutters between them, e.g. on a 250mm-wide board:
- **FIELD band:** X 0 – 70 (optos + field connectors on the left edge)
- **gutter (keepout, ≥3.2mm, no copper any layer):** X 70 – 80
- **LOGIC band:** X 80 – 165 (Pico, MCP, NE555, I2C, UART, safety rail/watchdog)
- **gutter (keepout):** X 165 – 175
- **MACHINE band:** X 175 – 250 (relays, snubbers, motion connector on the right edge)
- The optos straddle FIELD↔LOGIC and the relays straddle LOGIC↔MACHINE **by design** (that's where the isolation barrier legitimately crosses, inside the package) — so they sit ON the respective gutter, bridging it, which is correct.
- Plane keepouts (In1/In2) drop into the gutters automatically once the bands are clean.

Then: regenerate DSN with the gutters as keepout zones → autoroute is now geometrically constrained to stay in-band → import → DRC. OR route manually, which is now tractable because the domains don't overlap.

**Honest call on autoroute vs manual:** even after re-banding, FreeRouting via DSN still won't *enforce* creepage (it'll just have less room to violate). For a safety board, **manual routing of the isolation-crossing nets** (the opto field/logic sides, the relay coil/contact sides, the SAFE_* + rail) is the trustworthy path; autoroute the bulk logic signals only. Recommend: re-band placement, hard-keepout the gutters, manually route the ~30 barrier-crossing nets, autoroute the rest, DRC-gate everything.

**This does not block the at-machine field session** (running in parallel) — placement re-banding is a desk task on the existing scaffold; the A1 working-voltage measurement still independently sets the final gutter width (3.2mm conservative now, possibly narrower after measurement).

Do not use either routed candidate except as evidence of what the autorouter
tries to do without stronger physical route barriers.

## Codex Re-Band Pass (2026-06-02)

Codex implemented Claude's placement recommendation in `scripts/place_components_revB.py`:

- FIELD/LOGIC gutter: X 76.8-80.0 mm, no tracks/vias/zones on all copper layers.
- LOGIC/MACHINE gutter: X 181.0-184.2 mm, no tracks/vias/zones on all copper layers.
- FIELD inputs are now a single opto barrier column: field-side resistors at X 58, optos at X 74, logic pullups at X 92.
- Logic/control spine moved to the center band, including Pico, MCP23017s, watchdog, safety rail, and test pads.
- Relays now straddle the LOGIC/MACHINE barrier with machine contact/suppression parts on the right.
- Status LED drivers and `J_LAMP_LED` sit in the lower logic band; they do not enter the machine band.

Validation:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\place_components_revB.py --force
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\apply_netclasses_revB.py --write
& "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --units mm --output kicad\DRC-revB-led-logic.rpt kicad\wsl-phase8b.kicad_pcb
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\export_specctra_revB.py --output kicad\wsl-phase8b.revB-reband.dsn
```

Result:

- Source board: 0 DRC violations.
- Expected unrouted state: 488 unconnected pads.
- New DSN: `kicad/wsl-phase8b.revB-reband.dsn`.
- No re-band `.ses` candidate exists; both FreeRouting attempts were stopped after failing to produce output.
