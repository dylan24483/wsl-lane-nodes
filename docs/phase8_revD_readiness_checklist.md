# Rev-D Readiness & Fab-Order-Gate Checklist — Phase 8 Lane Controller Board

Status legend: `[ ]` open · `[~]` blocked on physical verify / owner decision · `[x]` done.
**Do not place a fab order until every PRE-ORDER GATE is `[x]`.**

> **2026-07-23 — REV-D INPUT-MARGIN HARDENING (CURRENT BOARD/FAB RECORD).**
> Exactly the 40 PC817 collector pull-ups `Rpu_*` (`R4,R6,…,R82`) are now
> **47 kΩ**; all unrelated 10 kΩ networks are unchanged. At 3.3 V this lowers
> the MCP23017 guaranteed-LOW sink requirement to
> `(3.3 − 0.66)/47 kΩ = 56.2 µA`. Worst MCP input leakage leaves the idle node
> at 3.253 V versus V_IH(min) 2.64 V, and the 50 pF first-order node RC is
> 2.35 µs. These figures require the external 47 kΩ to be the sole pull:
> production RP2040 GP6–GP13 must have PUE/PDE disabled, and U1/U2 MCP23017
> GPPUA/GPPUB must command and read back `0x00`. Any mismatch is STOP-SHIP.
> `R_TAPPU_*` remains a separate, intentionally unchanged 10 kΩ tap-drain
> network. The current immutable package is
> **`kicad/fab_revD_2026-07-23_r5/`**; every older rev-D package is superseded
> for ordering. This is still an **EXPERIMENTAL FIRST-ARTICLE**: UMW C5692981
> does not guarantee minimum CTR at ~1.7 mA/hot, so the revised FA-9 requires
> every populated channel to pass loaded-minimum FIELD_WET, ≥70 °C,
> idle-leakage, capability, and transition-time measurements before fleet
> release. Current electrical basis: remediation spec §R4.

> **⚗️ THIS ORDER IS AN EXPERIMENTAL FIRST-ARTICLE ONLY (R3-8, 2026-07-21).** Until
> the physical first-article gates clear — chiefly **FA-9 numeric PC817 V_CE / margin
> qualification** (the input front-end margin is improved by the 47 kΩ change, but the
> selected lot still lacks a guarantee at ~1.7 mA/hot; spec §R4) plus the OG-4
> at-temperature tap gate — this board
> is a prototype validation run, not a fleet-release build. The fab-order line item in
> G15 is labelled accordingly and carries a **blank EXPERIMENTAL-ORDER acceptance line
> for Dylan**, mirroring the blank OG-1 and H2 lines. Do not scale to fleet quantity or
> field-deploy a lane on these boards until FA-9 + OG-4 pass and the acceptance line is
> signed.
Written 2026-07-20 at the end of the rev-D design campaign. Companions:
`phase8_revD_change_list.md` (what changed and why), `phase8_revD_change_spec.md` (electrical
detail), `phase8_revD_run_log.md` (gate records FR-1…FR-7, WVR-ERC-1, COR-1, OG-1/OG-3).

> **2026-07-21 — Codex NO-GO remediation campaign CLOSED.** Per-finding final status,
> evidence, recorded repo HEADs, and the definitive open-gates list:
> **`phase8_revD_remediation_report_2026-07-21.md`**. The gates below remain the
> operational checklist; where wording differs, the remediation spec + report govern
> the remediated items (taps R1.9, DRU R2, firmware R3).

> **2026-07-21 (later) — ROUND-2 remediation batch (Codex R2-*) landed on top,
> then the ROUND-3 fix batch (Codex re-review findings 1–8), then the FINALIZE
> batch. The round-2 CLOSING RECORD — final R2-1…R2-17 statuses (16 CLOSED · 1
> DISPOSITIONED), both nuanced dispositions, recorded HEADs, and the definitive
> open-gates list — is `phase8_revD_round2_report_2026-07-21.md`.** The
> first-article pack was then FA-1…**FA-12** (adds the ≥ 100 MΩ tap-probe rule +
> TP-pad-only probing, FA-9 per-channel PC817B qualification at min FIELD_WET +
> ≥ 70 °C [R2-7], FA-12 J16 SDA/SCL short recovery [R2-4]); the PC817B
> disposition is remediation spec §R4 (revised 2026-07-23).
> Board figures anywhere below are superseded: **271 parts / 223 nets, netclasses
> 103/4/13/82/21, 24 test pads (TP17-24 tap probe pads), ERC baseline 1+39
> (WVR-ERC-2, pin-pair order-insensitive since round 3)**; release DRC =
> `kicad/fab_revD_2026-07-23_r5/reports/DRC-revD-fab-export.rpt`; as-current fab package =
> **`kicad/fab_revD_2026-07-23_r5/`** (47 kΩ PC817 pull-ups plus the J16
> protection stack with ESD VP moved
> UPSTREAM of the polyfuse — round-3 finding 2, REV_ID straps rev-D=0b01,
> Q17-Q20 = onsemi 2N7002LT1G C16338, 10M = C26108, gbrjob Revision "D").
> `fab_revD_2026-07-21/`, `..._r2/`, `..._r3/`, and `..._r4/` are superseded — never
> upload from them. Full record:
> run-log "ROUND-2 BOARD/BOM/EXPORT BATCH" + "ROUND-3 FIX BATCH" +
> "FINALIZE (ROUND 2)" entries.
>
> **2026-07-24 R5 safety/diagnostics supersession:** the generated pack is now
> **FA-1…FA-14**. FA-13 is a system-level P0 gate: J14.3–4 remains physically
> OPEN and the field rail cannot arm until an approved Stop/control-power
> interface is landed. Physical inspection found no C.I.S. on lanes 21/22;
> C.I.S. is N/A, not passed. Resolve whether another pit-entry interlock exists,
> approve install-versus-Stop+LOTO-only disposition, and prove Stop plus every
> installed/new pit interlock independently. A final pit interlock acts
> upstream—J14-only permission gating is not equivalent. FA-14 requires
> qualified-electrician/listed-instrument protective-earth and hot/neutral
> polarity proof. These tests add no mains or SAFE_* copper to Rev-D.

> **⚠️ GATE SCOPE NOTE (the rev-C lesson, applied up front).** The rev-C checklist went green
> on G1–G5 while change-list items 3/5/6–8 were unresolved, and the order shipped without
> them. This checklist therefore gates the fab order on EVERYTHING: the design gates (G1–G6),
> the owner/physical gates (G7–G8), the routing/export gates (G9–G12), and the review gate
> (G13). Green design gates alone do NOT authorize an order.

---

## 1. PRE-ORDER GATES

### G1 — Change spec written + independently verified  `[x]`
- `phase8_revD_change_spec.md` items A–G (2026-07-19, corrected 2026-07-20). Independent
  verify pass re-derived all electrical math (bleed dissipation, ADC margins, tap hold-off
  ladders, wetting 73.7/200 mA, D17 budget) and confirmed it; zero critical findings. One
  optimistic prose bound on the NE555 tap margin was noted and has since been CORRECTED in
  spec §E.2 (run-log COR-2, 2026-07-20): honest worst-case light-load read ≈ 3.53 V — above
  VDD 3.3 V but below the RP2040 3.6 V absolute max, clamp current bounded to single-digit µA
  by the ≥ 100k source impedance. Electrically safe; the old ≤ 3.27 V figure is retired.
- Review-fix pass closed 6 distinct findings (item-E temperature qualification, two
  cross-mate hazards, SS34 swap, OG-1 surfaced, ERC waiver + run log formalized); the full
  tool chain was re-run green afterward.

### G2 — Footprint-vs-datasheet review per new part class  `[x]`  (rev-C process item 10 — scripture)
- FR-1 PC817B vs DIP-4_W7.62 — PASS (40 proven instances on the physical rev-C board).
- FR-2 MCV 1×10 / 1×06 vs Phoenix plugs 1840447 / 1840405 — PASS (proven pairs J3 / J13).
- FR-3 D_PROT SS34 — PASS with the package trap checked: **MDD SS34, LCSC C8678, SMA
  (DO-214AC) verified; SS34 from other vendors ships in SMB/SMC — any MPN substitution
  re-runs this review.**
- FR-6 0805 passives — PASS. **2026-07-21 update (remediation R1): 680k is GONE (new
  values 1M + 10M, same footprint class).**
- FR-7 regression: K1–K7 relay map unchanged (coil pads 2/5, COM 1, NO 3, NC 4 unused —
  identical to the rev-C meter-confirmed G1/G2 map) — PASS.
- **FR-8 (2026-07-21): 2N7002 tap FETs in SOT-23 — PASS** (Q_NMOS_GSD 1=G/2=S/3=D matches
  the 2N7002 pinout; same proven class as the Qled_* drivers; V_GS ±20 V abs max confirmed).
- **FR-9 (2026-07-21): MCV headers → project-local `_D1.4` footprints — PASS** (drill
  1.4 mm per Phoenix drilling plan, pad 2.0×3.6, annular 0.30 mm; all 7 instances;
  first-article insertion/solder-fill check on one connector before the rest).
- Records live in `phase8_revD_run_log.md` (backfilled 2026-07-20 with genuinely-performed
  reviews — the gate had initially run without a written artifact; do not let that recur).

### G3 — Rev-D netlist regenerated + ERC waiver gate green  `[x]`  (re-run 2026-07-21, remediation R1)
- `py -3 scripts/generate_kicad_netlist_revD.py` → `kicad/wsl-phase8b-revD.net`:
  **262 parts, 217 nets, 0 netlist-generation errors** (remediation spec R1.7: −5 resistive
  tap parts, +15 unidirectional-stage parts, +4 `TAP_GATE_*` nets); regeneration is
  deterministic (only date + cwd-dependent source-path lines vary; sklib byte-identical).
- ERC baseline **WVR-ERC-1** (exactly 1 error — the benign Pico AGND/GND POWER-OUT pin-type
  artifact — + 40 warnings) is enforced fail-closed by the generator's `check_erc_waiver()`;
  any drift aborts. Rev-C never ran ERC, so this defines the baseline.
- J15/J16 refdes confirmed landed as specified.

### G4 — Netlist diff vs rev-C CLEAN  `[x]`  (re-run 2026-07-21, remediation R1 + M1 deep tables)
- `py -3 scripts/diff_netlist_revC_to_revD.py` → **RESULT CLEAN**: 46 added parts, 33 added
  nets, 11 touch-point nets additions-only, 173 nets unchanged, **0 removals**;
  CHANGED_PARTs all whitelisted-and-documented (D_PROT SS14→SS34 per FR-3; the five MCV
  connectors' `_D1.4` local-footprint repoint per FR-9/R2.5). M1 deep tables (exact
  value/footprint/pad membership per addition) all green.
- Every delta traces to spec items A/C/D/E/F; item G confirmed absent; forbidden absences
  confirmed (no SAFE_ tap, no RELAY_ENABLE_RAIL divider, no new barrier class).

### G5 — Placement + netclasses + placement-stage DRC + audit  `[x]`
- `kicad/revD/wsl-phase8b-revD.kicad_pcb` — 250×240 mm, 262 parts placed (2026-07-21
  regeneration; tap-stage cluster added in LOGIC x 114–127 / y 52–64), banding FIELD
  left / LOGIC center / MACHINE right with the established gutters, opto column re-pitched
  to 5.7 mm × 40 rows, USB keep-out envelope (16×12×40 mm) drawn on Dwgs_User, cross-mate
  silk warnings placed, TP strip relocated.
- Sidecars `wsl-phase8b-revD.kicad_pro/.kicad_prl/.kicad_dru` copied with the board; the
  `.dru` `hasNetclass()` isolation rules confirmed LIVE (not the 2026-06-03 false-green).
- `apply_netclasses_revD.py --write`: **97 / 4 / 13 / 82 / 21 exact** (2026-07-21 counts,
  remediation R1.7), zero unknown/overlap.
- Placement DRC (`kicad-cli pcb drc`): **0 violations**; 499 unconnected pads = expected at
  the unrouted placement stage.
- `audit_revD_board.py`: **ALL PASS in both netlist and board (--pre-route) modes**, and
  proven to fail closed (a rev-C-count mutant exits 1 with 3 FAILs). Carried invariants all
  green: Default==0, zero anonymous nets, rail reaches exactly 7 K-coils + pass-FET, no
  OUT_* on the Pico, GND/FIELD_GND zero shared nodes, SAFE_ pad membership frozen at
  rev-C's, M1 channel still DNP. **Safety_Rail == 13 is a stop-ship invariant.**

### G6 — Rev-C sacred-file integrity  `[x]`
- 189/189 files in the tracked, clone-portable
  `release_evidence/revC_design_snapshot_2026-07-19.zip` hash-verified internally;
  the 173 release-tracked paths are separately compared by
  `scripts/verify_revC_snapshot.py --compare-checkout`: binary content is byte-exact,
  UTF-8 text is compared independent of checkout line endings, and the historical
  Rev-B spec permits one exact additive non-authority safety notice while its frozen body
  remains exact. Current result is 173/173 with zero failures; no Rev-C electrical or
  fabrication body differs from the archive. Re-verify once more immediately before the
  fab order.

### G7 — Rev-C carried verify-items 6–7 resolved OR explicitly waived  `[~]`  **(owner + powered-session)**
- **Item 6 — per-channel front-end (dry-contact vs 24 VAC-rectified): CLOSED IN COPPER (r6,
  2026-07-25).**
  **RETRACTION — read this before acting on any older copy of G7.** Between 2026-07-21 and
  2026-07-25 this gate read: *"all 40 `FIELD_LED_*` nets have exactly two nodes and no
  series-diode / clamp / filter-cap footprints exist on any input channel… A non-dry-contact
  outcome therefore REQUIRES COPPER and is deferred to the fleet revision. Closing this gate
  for the first article means accepting the dry-contact default AND not landing PBZ /
  DIELL_L / DIELL_R on bare board inputs."* **Every clause of that is now FALSE.** Dylan
  reopened copper on 2026-07-25 and r6 landed the provisions:
  - Every `FIELD_LED_<n>` now has **three** nodes — `Dser_<n>.1` (series block, cathode) +
    `Dclamp_<n>.1` (anti-parallel clamp, cathode) + `PC817.1`.
  - `Dser_*` and `Dclamp_*` (1N4148WS, SOD-323, D18–D97) are **POPULATED on all 40 channels
    by default**. There is no per-channel stuffing decision and no per-lane record to lose.
  - `Cflt_*` (C17–C56, 0805) are **DNP** logic-side filter caps, fitted at commissioning
    only on a channel *measured* to carry a 60 Hz pulse train.
  - **PBZ, DIELL_L and DIELL_R MAY now be landed directly on board inputs**, and the harness
    1N4007 interposer for them is **SUPERSEDED — do not build it.** Prove the clamp per
    board with **FA-15** first (LED reverse must read **0.35 V ± 0.1 V**).
  - Authority: `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md`;
    package `kicad/fab_revD_2026-07-25_r6/`.
  **STILL OPEN (r6 does NOT close these) — the powered at-machine metering session is still
  required** (**meter tapped-lead live voltages BEFORE reconnecting any board** — standing
  queue item):
  1. **Cam-channel AC/DC class.** SA/SB/SC/TA1/TA2/TB are still UNMEASURED. r6 makes a
     24 VAC cam channel **electrically survivable, NOT functionally usable** — 60 Hz gives
     12 debounced edges per 100 ms against `CHATTER_MAX_CAM` = 8, so it **faults
     continuously**. Closing that needs a **firmware** change, not a cap. Record DC-or-AC,
     RMS/peak and frequency per channel.
  2. **`FIELD_WET_V` rail headroom under driven channels.** The isolated field rail has
     **zero bulk capacitance** (43 nodes, no capacitor) and a driven 24 VAC channel draws
     **16.8 mA peak** vs 1.34 mA dry. The board is budgeted for **N = 0** driven AC
     channels; **N ≥ 1 reopens the budget** (r6 spec §F.1 / J10b). Scope TP4, do not DMM it.
  3. **Field-pin ↔ field-pin clearance.** Measured minimum **0.4807 mm** against the
     IPC-2221B B1 requirement of 0.6 mm, on nets the clamp now holds at the same potential
     as the 0.6 mm-governed `FIELD_LED_*` nets. Pre-existing geometry, dispositioned as an
     OPEN fleet-revision item (r6 spec §D.5.1) — **not** silently compliant.
- **Item 7 — arc suppression sizing:** snubber positions carry DNP; size from the measured
  inductive load in the same powered session before populating.
- Item 8 (5 V budget) is discharged on paper: spec §H.4 + SS34 swap; bench PSU ≥1 A stands.
- **To close this gate: either the powered session resolves 6–7, or Dylan records an
  explicit waiver in `phase8_revD_run_log.md` accepting the rev-C-validated defaults for
  this spin.** Do not silently repeat rev-C's gate-scope mistake.

### G8 — OG-1: board growth 250×225 → 250×240 signed off + enclosure re-checked  `[~]`  **enclosure re-check RESOLVED (evidence, 2026-07-20); formal sign-off pending (Dylan — rides G14)**
- Spec §C.4 fallback 3 was executed in `place_components_revD.py` (BOARD_H=240) with the
  required owner sign-off **not yet given**. Arithmetic verified honest: true DIP-4_W7.62
  courtyard 5.59–5.68 mm → 40 rows cannot fit 225 mm; fallbacks 1–2 are dead.
- **Enclosure re-check RESOLVED 2026-07-20 — verdict: 240 mm is a spec update, not a
  conflict** (full evidence in the change-list STATUS + run-log OG-1 record):
  - **Nothing is committed to 225 mm in hardware:** no fleet enclosure, subpanel, or
    backplate has been purchased — purchases were explicitly frozen pending this gate;
    `phase8_pair_enclosure_spec.md` (2026-07-14) is a spec/sourcing document; the sourcing
    brief is still an open research task; HANDOFF task #12 is still open. The only
    purchased boxes are two Ogrmar 8×6×4 (already disqualified even at 225 mm) and the
    pilot Saginaw SCE-24EL2008LP, whose ~578×428 mm panel class takes one 250×240 board
    trivially.
  - **Layout D re-math at 240 mm:** 20+240+150+240+20 = 670 mm panel height × 310 mm width
    — fits the incumbent SCE-30EL2408LP's SCE-30P24 subpanel (686×533 mm usable) with
    16 mm to spare (was 46 mm at 225 mm).
  - **COR-3 J_PI +9.5 mm move:** non-issue — the J1 ribbon is internal (board→Pi inside
    the box; glands are all bottom-face field/Cat6), production ribbons are order-later
    pre-made IDC assemblies with no committed length, and 9.5 mm of lateral shift is noise
    against the ~80–150 mm ribbon budget.
- **Row-39 bottom-edge copper (SLOW_AUX11) — CARRIED CONSTRAINT, not yet checkable:** routed
  copper reaches y=238.72 (1.28 mm from the y=240 routed edge — legal vs the 0.5 mm rule
  and typical ±0.3 mm routed-edge tolerance, but any enclosure lip, panel clamp, or edge
  chamfer along the bottom edge contacts row-39 copper first, and a depanel/handling nick
  lands on live AUX11 copper). Since no enclosure/backplate is purchased or designed yet,
  this is a **binding requirement on the eventual bottom-edge lip/clamp design** (keep ≥
  the panel tolerance clear of the edge), to be verified at enclosure-design/purchase time
  — or the 36-row alternative removes row 39 entirely.
- **Alternative if the 240 mm sign-off is declined: 36 opto rows (AUX4–AUX7 only) fits
  225 mm** — requires a placement re-run and netlist/audit-count changes (a mini spin of
  steps I.1–I.6) **and a full re-route (the routed artifact below is 240 mm-specific)**.
- **To close this gate:** Dylan appends the sign-off line in `phase8_revD_run_log.md` gate
  OG-1 (still blank — the evidence record is there waiting for his decision; folded into
  the G14 review packet).

### G9 — Routing complete  `[x]`  **⚠️ EXECUTED OUT OF ORDER — see run-log PV-1; artifact CONDITIONAL on G8**
- Board fully routed 2026-07-20 by `scripts/route_revD.py` (+ `route_revD_lib.py`,
  `route_revD_logic.py`) — manual/deterministic, rev-C house style, all passes re-derived
  for the rev-D placement. Layer discipline + machine-side pattern per the run log.
- **Process violation on record:** this gate's own line said "Do not start routing before
  G8 resolves" and routing ran anyway with G8 still open. That was NOT sanctioned — run-log
  **PV-1** records it. Consequence stands: if Dylan declines the 240 mm growth, the routed
  artifact is DISCARDED (re-place + full re-route). Routing-before-G8 is not precedent.
- 2026-07-20 review-fix RD-VIA-1: the five single-point power vias (VCC_5V feed ×2,
  SAFE_STOP_RETURN ×2, RELAY_ENABLE_RAIL spine entry) were doubled with parallel twin
  barrels + same-net stubs (copper-only; no netlist/pad/netclass change).
- **Re-run trap RETIRED (2026-07-21, remediation batch):** the RD-VIA-1 twins are now
  emitted by the router itself (`route_power_via_redundancy()`), the M2 `BOARD.Delete()`
  fix removed the swig-crash failure mode, and the sanctioned pipeline regenerates the
  placement board from the netlist first — `place_components_revD.py --force` →
  `apply_netclasses_revD.py --write` → `route_revD.py` → `apply_netclasses_revD.py
  --write` → kicad-cli DRC → `audit_revD_board.py`. The routed artifact reproduces from
  scripts alone (proven 2026-07-21 on KiCad 10.0.2).
- **2026-07-21 (remediation R1/R2): board REGENERATED + FULLY RE-ROUTED** — 262 parts,
  new tap stages, new DRU minima 2.65/3.35/1.6 mm. See the change-list remediation banner
  + run-log board-chain record.

### G10 — Post-route DRC + routed-mode audit + zone fills  `[x]`  (re-run 2026-07-21, remediation R2 rules)
- KiCad DRC with the NEW `.dru` (2.65/3.35/1.6 mm — requirement + JLC etch allowance,
  remediation spec R2.3): **0 violations / 0 unconnected / 0 footprint errors** —
  `kicad/revD/DRC-revD-remediation-r3.rpt` (supersedes `DRC-revD-routed-r3.rpt`, which
  was against the old 2.5/3.2/1.5 rules; netclasses re-applied via
  `apply_netclasses_revD.py --write` before each DRC). Measured isolation minima:
  **L↔F 2.650 mm / L↔M 3.350 mm / machine ch↔ch 2.325 mm** (as-fabbed worst case ≥ the
  2.5/3.2 requirement with the ±20 % etch loss included).
- `audit_revD_board.py` in routed board mode (without `--pre-route`): **ALL PASS**,
  including zone-fill checks (F.Cu GND zone filled, no orphan islands — an early RD-VIA-1
  stub placement severed a zone neck at (160, 83–84) and was caught and re-placed north)
  and the Safety_Rail==13 stop-ship invariant.

### G11 — Fab export to a NEW dated directory  `[x]`  (re-run 2026-07-23, input-margin hardening)
- `scripts/export_fab_revD.py` RUN → **`kicad/fab_revD_2026-07-23_r5/`** (hashed
  as-ordered package, `manifest.json` with sha256 per file + source board/netlist hashes).
  REV and output-dir are parameters; the script **refuses to run if the output dir exists**
  (verified live — second run refused; no rmtree anywhere).
- In-process re-gates before exporting: kicad-cli DRC **0/0/0** with the live remediation
  `.kicad_dru`; `audit_revD_board.py` routed mode **ALL PASS**.
- **BOM↔CPL↔netlist equality ASSERTED** (not sampled): every placed refdes present in all
  three with matching value+footprint; pinned counts **271 parts / 28 DNP / 243 placed /
  226 JLC-placed / 27 JLC lines / 17 hand-solder**.
- **PC817 pull-up scope hard-locked:** `R4,R6,…,R82` are exactly 40 × 47 kΩ,
  UNI-ROYAL `0805W8F4702T5E`, LCSC **C17713**. The exporter rejects a missing
  channel, an unrelated 47 kΩ part, or a merge back into the 10 kΩ BOM line.
- **Bias configuration and firmware identity carried in-package:** RP2040 GP6–GP13
  PUE/PDE disabled; U1/U2 MCP23017 GPPUA/GPPUB commanded/read back `0x00`;
  build `rel-0c746b5747143b8011b01d43`, cfg `05d808411db4bb0d`, release UF2
  SHA-256 `d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae`.
  Any internal-pull or identity mismatch blocks FA-9. The package explicitly
  distinguishes the unchanged `R_TAPPU_*` 10 kΩ diagnostic-tap drain pulls.
- **D_PROT hard-locked**: D17 = **MDD SS34, LCSC C8678, SMA/DO-214AC** (FR-3) asserted at
  netlist, board, and JLC-BOM level; any SS14 anywhere fails the export.
- 10M 0805 (R_TAPG_*) is pinned to UNI-ROYAL `0805W8F1005T5E`, LCSC
  **C26108**; 1M remains C17514.
- Package also carries the hand-solder BOM (rev-D refs incl. J15/J16 + the U37→U45 shift)
  and the **harness BOM** (see G13).

### G12 — Manual Gerber inspection + JLC preview  `[ ]`  (rev-C G5 pattern)
- On the plots: K1–K7 pad-net map regression (pads 2/5 coil, 1 COM, 3 NO, 4 NC); the 8 new
  opto-bank channels; J15/J16 pads; USB keep-out visually clear; "KEYED: NOT …" silk at
  J3/J15/J13/J16 legible.
- Compare JLC's upload preview against the spec before paying — standing habit.

### G13 — Harness/assembly BOM order carries every mating + coding part  `[ ]` ORDER still to place — **BOM itself now EXISTS** (2026-07-21: `docs/phase8_revD_harness_bom.csv`, also in the fab package assembly/ dir, with corrected MC 1,5 termination data — 7 mm strip / 0.22–0.25 N·m / ≤ 0.5 mm² insulated ferrule — and the corrected coding-install rule)  (OG-3; ship WITH the boards)
| Item | PN | Qty note |
|---|---|---|
| J15 mating plug (MC 1,5/10-ST-3,5) | Phoenix **1840447** | same PN as J3's plug — coding is what tells them apart |
| J16 mating plug (MC 1,5/6-ST-3,5) | Phoenix **1840405** | same PN as J13's plug — ditto |
| Coding profiles | Phoenix **CP-MSTB 1734634** | 6 per coding star; code J3@pole 1, J15@pole 10, J13@pole 1, J16@pole 6. **Install corrected 2026-07-21 (H7): profile fits the PLUG (or an inverted header), never pressed into a standard G-3.5 header; header side = remove the coding rib at the matching pole. Sacrificial-pair proof (FA-8) before coding production parts.** |
| Harness band colors | — | J3 white · J15 yellow · J13 white · J16 blue |
- Plus the rev-C mating set (J1 IDC socket candidate, J3/J4/J5/J13/J14 plugs) — carry the
  rev-C §3 table; the BOM gap does not get a third occurrence.
- **Coding profiles must be FITTED before first article** — the first-article gate includes
  the physical cross-mate refusal test.

### G14 — Dylan's overall review of the rev-D docs + spec  `[ ]`
- Change list + spec + this checklist + run log. Open decisions parked for him: OG-1 (G8),
  the G7 waiver-or-session choice, and the deferred OUT-B override (change-list item G).
- **J16 polyfuse is FITTED** (F1, Codex R2-4) — no longer an open option; the module
  allowance was re-derived **100 mA → 45 mA @ 85 °C worst case** (R3-7, run-log FR-15).
  A substitute is accepted only if its **minimum Ihold at 85 °C is ≥90 mA**;
  trip-current equivalence is never sufficient because PPTC trip is not a hard clamp.

### G15 — EXPERIMENTAL FIRST-ARTICLE order acceptance  `[~]`  **(owner sign-off — blank, like OG-1 / H2)**
- This spin ships as an **experimental first-article validation build**, not a fleet
  release (R3-8). The 47 kΩ input hardening reduces required sink current to
  56.2 µA, but the UMW PC817 lot is proven empirically only AT first article by
  the upgraded **FA-9** hot/min-voltage capability, leakage, and timing
  qualification, after the RP2040/MCP internal-pull-zero runtime proof
  (spec §R4); the tap safety gate is proven only by the
  at-temperature **OG-4** repeat.
  Both are physical gates that cannot be discharged before boards exist.
- **To close this gate — Dylan appends the acceptance line below** (mirrors the blank
  OG-1 sign-off line in the run log). Signing accepts placing an EXPERIMENTAL order whose
  fleet-release status is contingent on FA-9 + OG-4 passing on the physical boards.

  `EXPERIMENTAL-ORDER ACCEPTANCE: _____________________________ (date / decision — experimental first-article, fleet-release gated on FA-9 numeric V_CE + OG-4 at-temp)`

### G16 — Positive-actuation return bound MEASURED on the target Pi  `[ ]`  **(software; blocks LIVE, not fab)**

`controller_io.POSITIVE_ACTUATION_MAX_S` (default **0.050 s**) bounds how long a
safety-positive actuation — sweep-on / table-on / spot-on / arm-high / the NE555 watchdog
kick — may take to return. **Exceeding it turns the motor OFF mid-motion and escalates to
`_hard_safe` + MANUAL_INTERVENTION, which requires a physical PBZ to clear.**

**The 0.050 s default is an ASSERTION, not a measurement.** Nothing measured actuation
return time on a Raspberry Pi. The sample is taken with wall-clock `link.now()` around a
call made from a thread competing under the CPython GIL with the serial reader, DiagWriter,
PlatformHealth (which forks `vcgencmd` every 60 s), CycleShipper, and async recorder dumps —
so it includes **scheduling preemption**, not just I²C/GPIO transport. Exposure is roughly
2 boards × 50 Hz ≈ 100 evaluations/s (~8.6 M/day/Pi) for the watchdog kick alone, so a
per-event probability above ~1e-7 is a **daily lane stoppage**.

This project has already shipped this exact bug twice — `TAP_KICK_STARVE_MS` set below the
real kick cadence, and a PlatformHealth poll cadence that false-expired healthy lanes. Do
not ship a third guessed timing constant.

**To close this gate:**

```bash
# ON THE PI, with the daemon's peer threads running (or matched via --threads):
python3 scripts/measure_actuation_bound.py --seconds 900 --json /tmp/actuation.json
```

- `[ ]` Report attached to `phase8_revD_run_log.md` (paste the JSON).
- `[ ]` If the recommendation exceeds the 0.050 s default, set **both** env vars in
  `/etc/wsl-lane-node.env` before LIVE:
  `WSL_POSITIVE_ACTUATION_MAX_S` and `WSL_WATCHDOG_KICK_MAX_S`.
  Both **fail LOUD** (ValueError at import, before hardware opens) on garbage or
  out-of-range values — they never silently restore the default.
- `[ ]` If the recommendation exceeds the permitted ceiling (0.500 s), **do NOT raise the
  ceiling.** The platform is too jittery to run the control loop as-is; fix the jitter
  (thread count, fork cadence, CPU governor, `isolcpus`) and re-measure.

**Already fixed in code (2026-07-25):** the watchdog kick no longer shares the write budget.
Its body deliberately blocks for `WDOG_PULSE_S`, so `BoardController` now passes a derived
`WDOG_PULSE_S + POSITIVE_ACTUATION_MAX_S` budget — charging a deliberate sleep against a
transport budget was a category error. Note also that a genuinely late kick is already
handled **in hardware**: the NE555 simply does not get its pulse and drops the rail. The
software bound is defense in depth and must not be the thing that stops the lane on
scheduler jitter alone.

---

## 2. FIRST-ARTICLE QUALITY GATE (per assembled rev-D board, before trusting it)

Carry the rev-C §4 gate wholesale (rails → i2cdetect → one relay → all six), then add the
rev-D extensions. One channel of each NEW I/O type must pass before trusting the board
(process item 11).

- `[x]` **⛔ Per-board test documents for rev-D refdes — REGENERATED (2026-07-21, Codex
  M6):** `docs/phase8_revD_first_article_pack.md` + `docs/phase8_revD_first_article_
  refdes_map.csv`, generated programmatically from the rev-D netlist + routed board by
  `scripts/generate_first_article_docs_revD.py` (re-run it after ANY netlist/placement
  change — derived docs, never hand-edit). The pack carries the 46-row REFDES_SHIFT
  table (ISO_WET U37→U45, U_WDOG U36→U44, rail-gate pullup R106→R124 …), the relocated
  TP map, the FA-1…FA-14 procedures (incl. the R1.9 tap fault injection with the
  ≥ 70 °C repeat, the GPB poke, the ADC read, cross-mate refusal + sacrificial-pair
  coding proof, and R4 V_CE sampling). **Every rev-C bench artifact still names WRONG
  parts on a rev-D board — use ONLY the rev-D pack at the bench.**

- `[ ]` **FA-13 Stop / pit-interlock system gate (P0):** do not jumper J14.3–4
  at the machine. Approve and meter the fail-safe Stop/control-power interface,
  determine whether another pit-entry interlock exists on lanes 21/22, and
  obtain the qualified install-versus-Stop+LOTO-only disposition. Prove Stop
  drops master/control power and TP16 within the recorded bounds. Prove every
  installed/new pit interlock separately in its approved upstream
  safety-disconnect path; a J14-only switch is not sufficient. Exercise every
  monitor open-wire/proof control. Execute the per-lane Candidate-C TB/SC G3
  insertion proof: command S and T separately from the board with both levers
  BACK/open, prove each coil dead, verify the OEM ladder was not bypassed, and
  capture the exact result in the signed commissioning latch. Record the
  periodic retest owner; the manifest-controlled interval is **365 days
  maximum**, and expired evidence blocks healthy monitor status.
- `[ ]` **FA-14 mains-integrity gate:** a qualified electrician verifies
  protective-earth continuity/bonding and hot/neutral polarity with a listed,
  in-calibration external tester. Board rails and `control_power_ok` do not
  satisfy this gate; mains/PE test current stay outside Rev-D. Repeat at the
  manifest-controlled interval of **365 days maximum**, and sooner after
  relevant electrical service; expired evidence blocks healthy monitor status.

- `[ ]` Rails at TPs — **NEW: TP4 unloaded reads ≤ ~6 V** (item A landed; 11–14 V float
  gone — if TP4 still floats high the bleed is missing/open). TP4 under opto load ≥ ~4.5 V.
  Regression: TP5↔TP2 still OPEN (isolation).
- `[ ]` `i2cdetect -y 1` → 0x20 / 0x21 / 0x22.
- `[ ]` **FA-9 input-bias runtime proof:** with the exact production release,
  record RP2040 GP6–GP13 pad readback and require PUE=0/PDE=0 on every fast
  input. Read U1/0x20 and U2/0x21 MCP23017 `GPPUA`/`GPPUB` and require all four
  bytes `0x00`; `MachineIO` must refuse startup on a write/readback mismatch.
  Do not apply the 47 kΩ numeric limits if this gate is not green.
- `[ ]` 6-relay make/break via `lane_node/bench_first_article.py` (K7 DNP for M1).
- `[ ]` **USB (item B):** ordinary unmodified micro-B cable fully seats with the J1 ribbon
  MATED; BOOTSEL reachable; UF2 drag-drop flash succeeds WITHOUT the hand-shaved cable.
- `[ ]` **GPB bank read test (item C):** poke each of J15 pins 1–8 to FIELD_GND; the
  matching GPB0–7 bit on 0x21 reads active-low; all 8 channels, no cross-talk between
  adjacent rows.
- `[ ]` **Divider ADC read (item D):** GP26 reads VCC_5V/2 within ±3 % of the TP1 DMM
  value; energize 6 coils and confirm the sag is visible in the ADC trend.
- `[ ]` **Rail-tap test (item E — REDESIGNED per remediation spec R1; full procedure =
  spec R1.9, which GOVERNS this line item):**
  - **level survey (cold):** scope each `TAP_GATE_*` gate node and `TAP_*` drain node
    through the full signal swing; gate-high ≥ 3.0 V typical expected (worst-stack
    margins per spec R1.5); reads are INVERTED (observed HIGH ⇒ pad LOW);
  - **unidirectionality proof (cold):** FI-1 bench build drives each GP16–19 output-high
    with J1 unmated (driver high-Z) — each observed net must not move > 1 mV; rail must
    not arm;
  - **fault insertion (cold):** clip-short each tap FET drain-gate (F3/F4), repeat; then
    with the emulator arming normally, go high-Z with the short applied — rail must drop
    within the normal watchdog window;
  - **AT-TEMPERATURE repeat (gate OG-4 — MANDATORY, a cold-only pass does not discharge
    it):** heat the Q_AND_ARM / Q_AND_RP_OK / Q_RAIL region AND the four tap FETs to
    ≥ 70 °C case (thermocouple-verified, hold ≥ 2 min); repeat the high-Z + D-G-short +
    stuck-high-GPIO stack — rail must neither arm nor hold, and a driven ARM_PERMIT
    disarm must still drop it;
  - **edge-order proof (fw v1.2):** forced Pi-death and forced kick-starvation each
    produce the documented edge ORDER in the 1 ms ring, and the record survives a Pico
    reboot (epoch semantics, spec R3.3).
- `[ ]` **J16 bus check (item F):** scrap ADS1115/INA219 module on J16 → module AND
  0x20/0x21/0x22 all still ACK; bus rise-time spot-check with the module attached.
- `[ ]` **Cross-mate refusal test (OG-3 / first-article pack FA-8):** FIRST the
  **sacrificial-pair proof** (spare plug + scrap header: coded pair seats, coded plug
  refuses an uncoded header, no adjacent-pole damage — the CP-MSTB profile fits the
  PLUG, never a standard header; corrected 2026-07-21, H7), THEN each production coded
  plug physically REFUSES the wrong header — J3-plug vs J15 header, J15-plug vs J3,
  J13-plug vs J16, J16-plug vs J13.
- `[ ]` Firmware review assert (item E binding, now fw v1.2 / remediation spec R3):
  GP6–GP13 internal pulls disabled (the external 47 kΩ is authoritative);
  GP16–GP19 inputs-only ENFORCED (`tap_assert_input_only()` register-readback + the
  build-failing host direction test), Schmitt enabled, inversion in exactly one
  `tap_read()` accessor; deliberate disarm drives ARM_PERMIT low, never tristates; the
  FI-1 fault-injection build is excluded from the release artifact and refuses to run
  without its physical jumper. (Firmware is the separate C2 task; this line refuses a
  first-article pass without the check.)

---

## 3. WHAT REMAINS BEFORE A FAB ORDER (plain-English summary)

1. **Dylan signs off (or declines) the 240 mm board** — G8/OG-1. The enclosure re-check
   half is **RESOLVED with evidence (2026-07-20: nothing purchased, Layout D re-math fits
   the incumbent SCE-30P24 with 16 mm to spare, ribbon shift is noise)** — what remains is
   his decision itself. Declining means a 36-row re-spin of placement + counts **and
   discarding the routed artifact (full re-route)**. Row-39 bottom-edge copper proximity
   is a carried constraint on the eventual enclosure lip/backplate design.
2. **Resolve or waive rev-C items 6–7** — G7 (powered at-machine metering session, which is
   already the queued next field step for machine 22).
3. ~~Route the board~~ **DONE 2026-07-20 (G9+G10: DRC 0/0/0, routed-mode audit ALL PASS,
   RD-VIA-1 power-via redundancy, independent 8-check verification pass) — but routed OUT
   OF ORDER while G8 was open (run-log PV-1); the artifact is conditional on Dylan's G8
   sign-off.**
4. ~~Write `export_fab_revD.py` and export~~ **DONE 2026-07-21 (G11 `[x]`:
   `kicad/fab_revD_2026-07-21/` hashed package, equality asserts 262/27/235/218, D_PROT
   locked to MDD SS34 C8678)**; inspect Gerbers + JLC preview — G12 still open (include
   the five doubled power vias + the row-39 bottom edge in the visual pass).
5. **Order the harness/coding parts with the boards** — G13 (the BOM now exists:
   `docs/phase8_revD_harness_bom.csv`; the order itself is still to be placed).
6. **Final sacred-file hash re-verify + Dylan's review** — G6 (re-run) + G14, **plus the
   G15 EXPERIMENTAL-ORDER acceptance line** (R3-8: this is a prototype validation build,
   not a fleet release, until FA-9 numeric V_CE + OG-4 at-temp pass on real boards).
7. **After assembly, the §2 first-article gate** — the per-board test docs are already
   generated for rev-D refdes (M6, 2026-07-21: `docs/phase8_revD_first_article_pack.md`;
   re-run the generator if the design moves), and the gate includes the MANDATORY
   at-temperature (≥70 °C) rail-tap repeat (OG-4) plus the FA-8 sacrificial-pair coding
   proof AND the upgraded **FA-9 numeric per-channel PC817 V_CE / margin qualification**
   (R3-8 — the experimental-order gate). The characterization session (analog population,
   DC1–DC3) is scheduled but not fab-blocking.

Not fab-blocking but scheduled: the **characterization session** that decides external
analog population (CT current channels, 24 VAC sense, temp channels — all on the external
module path, never on-board), and the software companions (IN_B_MAP + self-test extension,
heartbeat adc field, tap edge-capture firmware) which live in the separate 2026-07-19
diagnostics software campaign and its own review gates.
