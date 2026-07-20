# Rev-D Readiness & Fab-Order-Gate Checklist — Phase 8 Lane Controller Board

Status legend: `[ ]` open · `[~]` blocked on physical verify / owner decision · `[x]` done.
**Do not place a fab order until every PRE-ORDER GATE is `[x]`.**
Written 2026-07-20 at the end of the rev-D design campaign. Companions:
`phase8_revD_change_list.md` (what changed and why), `phase8_revD_change_spec.md` (electrical
detail), `phase8_revD_run_log.md` (gate records FR-1…FR-7, WVR-ERC-1, COR-1, OG-1/OG-3).

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
  optimistic prose bound on the NE555 tap margin was noted — still electrically safe (the
  spec's own worst-case arithmetic bounds the read ≤ 3.27 V < 3.3 V).
- Review-fix pass closed 6 distinct findings (item-E temperature qualification, two
  cross-mate hazards, SS34 swap, OG-1 surfaced, ERC waiver + run log formalized); the full
  tool chain was re-run green afterward.

### G2 — Footprint-vs-datasheet review per new part class  `[x]`  (rev-C process item 10 — scripture)
- FR-1 PC817B vs DIP-4_W7.62 — PASS (40 proven instances on the physical rev-C board).
- FR-2 MCV 1×10 / 1×06 vs Phoenix plugs 1840447 / 1840405 — PASS (proven pairs J3 / J13).
- FR-3 D_PROT SS34 — PASS with the package trap checked: **MDD SS34, LCSC C8678, SMA
  (DO-214AC) verified; SS34 from other vendors ships in SMB/SMC — any MPN substitution
  re-runs this review.**
- FR-6 0805 passives (680k is the only new VALUE, no new footprint class) — PASS.
- FR-7 regression: K1–K7 relay map unchanged (coil pads 2/5, COM 1, NO 3, NC 4 unused —
  identical to the rev-C meter-confirmed G1/G2 map) — PASS.
- Records live in `phase8_revD_run_log.md` (backfilled 2026-07-20 with genuinely-performed
  reviews — the gate had initially run without a written artifact; do not let that recur).

### G3 — Rev-D netlist regenerated + ERC waiver gate green  `[x]`
- `py -3 scripts/generate_kicad_netlist_revD.py` → `kicad/wsl-phase8b-revD.net`:
  **252 parts, 213 nets, 0 netlist-generation errors**; regeneration is deterministic (only
  date + cwd-dependent source-path lines vary; sklib byte-identical).
- ERC baseline **WVR-ERC-1** (exactly 1 error — the benign Pico AGND/GND POWER-OUT pin-type
  artifact — + 40 warnings) is enforced fail-closed by the generator's `check_erc_waiver()`;
  any drift aborts. Rev-C never ran ERC, so this defines the baseline.
- J15/J16 refdes confirmed landed as specified.

### G4 — Netlist diff vs rev-C CLEAN  `[x]`
- `py -3 scripts/diff_netlist_revC_to_revD.py` → **RESULT CLEAN**: 36 added parts, 29 added
  nets, 11 touch-point nets additions-only, 173 nets unchanged, **0 removals**; sole
  CHANGED_PART = D_PROT SS14→SS34 (whitelisted per FR-3).
- Every delta traces to spec items A/C/D/E/F; item G confirmed absent; forbidden absences
  confirmed (no SAFE_ tap, no RELAY_ENABLE_RAIL divider, no new barrier class).

### G5 — Placement + netclasses + placement-stage DRC + audit  `[x]`
- `kicad/revD/wsl-phase8b-revD.kicad_pcb` — 250×240 mm, 252 parts placed, banding FIELD
  left / LOGIC center / MACHINE right with the established gutters, opto column re-pitched
  to 5.7 mm × 40 rows, USB keep-out envelope (16×12×40 mm) drawn on Dwgs_User, cross-mate
  silk warnings placed, TP strip relocated.
- Sidecars `wsl-phase8b-revD.kicad_pro/.kicad_prl/.kicad_dru` copied with the board; the
  `.dru` `hasNetclass()` isolation rules confirmed LIVE (not the 2026-06-03 false-green).
- `apply_netclasses_revD.py --write`: **93 / 4 / 13 / 82 / 21 exact**, zero unknown/overlap.
- Placement DRC (`kicad-cli pcb drc`): **0 violations**; 499 unconnected pads = expected at
  the unrouted placement stage.
- `audit_revD_board.py`: **ALL PASS in both netlist and board (--pre-route) modes**, and
  proven to fail closed (a rev-C-count mutant exits 1 with 3 FAILs). Carried invariants all
  green: Default==0, zero anonymous nets, rail reaches exactly 7 K-coils + pass-FET, no
  OUT_* on the Pico, GND/FIELD_GND zero shared nodes, SAFE_ pad membership frozen at
  rev-C's, M1 channel still DNP. **Safety_Rail == 13 is a stop-ship invariant.**

### G6 — Rev-C sacred-file integrity  `[x]`
- 189/189 files in `backups/revC_design_snapshot_2026-07-19/MANIFEST.json` hash-verified
  unchanged against the live tree before AND after every tool run (verified twice more in
  the independent verify pass). Git shows no rev-C design file modified; staging empty;
  nothing committed. Re-verify once more immediately before the fab order.

### G7 — Rev-C carried verify-items 6–7 resolved OR explicitly waived  `[~]`  **(owner + powered-session)**
- **Item 6 — per-channel front-end (dry-contact vs 24 VAC-rectified):** rev-D carries the
  dry-contact default on all 40 channels. Blocked on the powered at-machine metering
  session (**meter tapped-lead live voltages BEFORE reconnecting any board** — standing
  queue item). Outcome changes population/BOM per channel, not copper.
- **Item 7 — arc suppression sizing:** snubber positions carry DNP; size from the measured
  inductive load in the same powered session before populating.
- Item 8 (5 V budget) is discharged on paper: spec §H.4 + SS34 swap; bench PSU ≥1 A stands.
- **To close this gate: either the powered session resolves 6–7, or Dylan records an
  explicit waiver in `phase8_revD_run_log.md` accepting the rev-C-validated defaults for
  this spin.** Do not silently repeat rev-C's gate-scope mistake.

### G8 — OG-1: board growth 250×225 → 250×240 signed off + enclosure re-checked  `[ ]`  **⛔ BLOCKING (Dylan)**
- Spec §C.4 fallback 3 was executed in `place_components_revD.py` (BOARD_H=240) with the
  required owner sign-off **not yet given**. Arithmetic verified honest: true DIP-4_W7.62
  courtyard 5.59–5.68 mm → 40 rows cannot fit 225 mm; fallbacks 1–2 are dead.
- Consequences: bottom mounting holes at y=236; `phase8_pair_enclosure_spec.md` (assumes
  225 mm) standoff/panel math invalidated — enclosure/subpanel/backplate purchases are
  frozen until re-checked.
- **Alternative if declined: 36 opto rows (AUX4–AUX7 only) fits 225 mm** — requires a
  placement re-run and netlist/audit-count changes (a mini spin of steps I.1–I.6).
- Record the decision in `phase8_revD_run_log.md` gate OG-1 (sign-off line is waiting).

### G9 — Routing complete  `[ ]`  **(HONEST STATUS: route-ready, NOT routed)**
- The delivered board is placement + netclasses + keep-outs only. FreeRouting was NOT
  attempted — the repo formally abandoned it (no `.ses` exists; DSN cannot carry the
  creepage rules), so routing is manual, per the rev-C pattern.
- Scope: full board (item B makes x≈80–135 a re-route region anyway; 40-row opto column;
  tap runs to the moved Pico; series tap resistors within ~10 mm of their source nodes).
- The USB keep-out envelope and the gutters are non-negotiable constraints on the router.
- Do not start routing before G8 resolves — a 240→225 reversal re-places the board.

### G10 — Post-route DRC + routed-mode audit + zone fills  `[ ]`
- KiCad DRC with the carried `.dru`: **0 violations / 0 unconnected / 0 footprint errors**
  (the 499 pre-route unconnected must go to zero).
- `audit_revD_board.py` in routed board mode (without `--pre-route`): ALL PASS, including
  zone-fill checks and the Safety_Rail==13 stop-ship invariant.

### G11 — Fab export to a NEW dated directory  `[ ]`
- `export_fab_revD.py` is **not yet written** (spec step I.7). Requirements: REV and
  output-dir are parameters; writes ONLY to `kicad/fab_revD_<date>/`; **refuses to run if
  the output dir exists** (no rmtree of anything, ever — the rev-B/rev-C rmtree incident);
  manifest carries sha256 + generated_at + source-board name.

### G12 — Manual Gerber inspection + JLC preview  `[ ]`  (rev-C G5 pattern)
- On the plots: K1–K7 pad-net map regression (pads 2/5 coil, 1 COM, 3 NO, 4 NC); the 8 new
  opto-bank channels; J15/J16 pads; USB keep-out visually clear; "KEYED: NOT …" silk at
  J3/J15/J13/J16 legible.
- Compare JLC's upload preview against the spec before paying — standing habit.

### G13 — Harness/assembly BOM order carries every mating + coding part  `[ ]`  (OG-3; ship WITH the boards)
| Item | PN | Qty note |
|---|---|---|
| J15 mating plug (MC 1,5/10-ST-3,5) | Phoenix **1840447** | same PN as J3's plug — coding is what tells them apart |
| J16 mating plug (MC 1,5/6-ST-3,5) | Phoenix **1840405** | same PN as J13's plug — ditto |
| Coding profiles | Phoenix **CP-MSTB 1734634** | 6 per coding star; code J3@pole 1, J15@pole 10, J13@pole 1, J16@pole 6; cut the matching plug tabs |
| Harness band colors | — | J3 white · J15 yellow · J13 white · J16 blue |
- Plus the rev-C mating set (J1 IDC socket candidate, J3/J4/J5/J13/J14 plugs) — carry the
  rev-C §3 table; the BOM gap does not get a third occurrence.
- **Coding profiles must be FITTED before first article** — the first-article gate includes
  the physical cross-mate refusal test.

### G14 — Dylan's overall review of the rev-D docs + spec  `[ ]`
- Change list + spec + this checklist + run log. Open decisions parked for him: OG-1 (G8),
  the G7 waiver-or-session choice, the J16 polyfuse option (run-log FR-3), and the deferred
  OUT-B override (change-list item G).

---

## 2. FIRST-ARTICLE QUALITY GATE (per assembled rev-D board, before trusting it)

Carry the rev-C §4 gate wholesale (rails → i2cdetect → one relay → all six), then add the
rev-D extensions. One channel of each NEW I/O type must pass before trusting the board
(process item 11).

- `[ ]` Rails at TPs — **NEW: TP4 unloaded reads ≤ ~6 V** (item A landed; 11–14 V float
  gone — if TP4 still floats high the bleed is missing/open). TP4 under opto load ≥ ~4.5 V.
  Regression: TP5↔TP2 still OPEN (isolation).
- `[ ]` `i2cdetect -y 1` → 0x20 / 0x21 / 0x22.
- `[ ]` 6-relay make/break via `lane_node/bench_first_article.py` (K7 DNP for M1).
- `[ ]` **USB (item B):** ordinary unmodified micro-B cable fully seats with the J1 ribbon
  MATED; BOOTSEL reachable; UF2 drag-drop flash succeeds WITHOUT the hand-shaved cable.
- `[ ]` **GPB bank read test (item C):** poke each of J15 pins 1–8 to FIELD_GND; the
  matching GPB0–7 bit on 0x21 reads active-low; all 8 channels, no cross-talk between
  adjacent rows.
- `[ ]` **Divider ADC read (item D):** GP26 reads VCC_5V/2 within ±3 % of the TP1 DMM
  value; energize 6 coils and confirm the sag is visible in the ADC trend.
- `[ ]` **Rail-tap ordering test (item E):**
  - scope each TAP_ node vs its source for level/threshold margins (NE555 high reads
    ≥ VIH through the 100k/680k divider; 3.3 V taps read clean through 680k, Schmitt on);
  - **cold fault injection:** force each tap GPIO output-high (test firmware) with the Pi
    link disconnected — the rail must NOT arm, and an armed rail must still drop on
    Pi-kill in the same time as an untapped board;
  - **AT-TEMPERATURE repeat (gate OG-4 — MANDATORY, a cold-only pass does not discharge
    it):** hold the Q_AND_ARM / Q_AND_RP_OK / Q_RAIL region ≥70 °C case temperature (heat
    gun + thermocouple) and prove a deliberate ARM_PERMIT disarm still drops the rail;
  - forced Pi-death and forced kick-starvation each produce the correct edge ORDER on the
    four taps.
- `[ ]` **J16 bus check (item F):** scrap ADS1115/INA219 module on J16 → module AND
  0x20/0x21/0x22 all still ACK; bus rise-time spot-check with the module attached.
- `[ ]` **Cross-mate refusal test (OG-3):** each coded plug physically REFUSES the wrong
  header — J3-plug vs J15 header, J15-plug vs J3, J13-plug vs J16, J16-plug vs J13.
- `[ ]` Firmware review assert (item E binding): GP16–GP19 configured inputs-only, Schmitt
  enabled; deliberate disarm drives ARM_PERMIT low, never tristates. (Firmware itself is
  the separate campaign; this line just refuses a first-article pass without the check.)

---

## 3. WHAT REMAINS BEFORE A FAB ORDER (plain-English summary)

1. **Dylan signs off (or declines) the 240 mm board** — G8/OG-1. Declining means a 36-row
   re-spin of placement + counts. Enclosure spec must be re-checked either way.
2. **Resolve or waive rev-C items 6–7** — G7 (powered at-machine metering session, which is
   already the queued next field step for machine 22).
3. **Route the board** — G9; it is route-ready today, not routed. Then post-route DRC +
   routed-mode audit — G10.
4. **Write `export_fab_revD.py` and export** to `kicad/fab_revD_<date>/` — G11; inspect
   Gerbers + JLC preview — G12.
5. **Order the harness/coding parts with the boards** — G13.
6. **Final sacred-file hash re-verify + Dylan's review** — G6 (re-run) + G14.

Not fab-blocking but scheduled: the **characterization session** that decides external
analog population (CT current channels, 24 VAC sense, temp channels — all on the external
module path, never on-board), and the software companions (IN_B_MAP + self-test extension,
heartbeat adc field, tap edge-capture firmware) which live in the separate 2026-07-19
diagnostics software campaign and its own review gates.
