# Phase 8 Lane-Controller — Rev-D Change List

> Consolidated 2026-07-20 at the end of the rev-D design campaign (spec → netlist → placement →
> verify → fix pass). Companion docs: `phase8_revD_change_spec.md` (full electrical detail,
> items A–G), `phase8_revD_run_log.md` (gate records, waivers, footprint reviews),
> `phase8_revD_readiness_checklist.md` (pre-order gates — **read before any fab order**).
> Source catalog: `phase8_diagnostics_target_conditions_2026-07-19.md` §2 "Earns its place"
> items 1–5.
>
> **SACRED-FILE RULE:** the rev-B/rev-C electrical and fabrication baseline is frozen.
> The self-contained release archive
> `release_evidence/revC_design_snapshot_2026-07-19.zip` verifies all 189 members;
> `py -3 scripts/verify_revC_snapshot.py --compare-checkout` also compares the 173
> release-tracked paths and permits only checkout line-ending conversion plus the one exact
> frozen-record safety notice. All rev-D work is in NEW `*revD*` files on `fable-audit-fixes`
> with explicit per-file staging only (`230f217` → `a045330` → `4896c48` → `67c3820` + the
> finalize commit). The expanded ignored snapshot and external mirrors are recovery copies,
> not hidden release-gate prerequisites. Publication is proven only by exact `git ls-remote`
> containment of the WSL-pinned lane commit.
> Reminder: **every rev-C artifact carries a revB filename** — `generate_kicad_netlist_revB.py`
> IS the rev-C generator and `kicad/fab_revB_routed_manual/` IS the rev-C-as-ordered package.
>
> **2026-07-24 immutable-snapshot repair:** the exact original
> `phase8b_pcb_revB_spec.md` remains inside the SHA-pinned archive. The live historical copy
> carries one exact additive non-authority safety notice while its frozen body remains
> byte-identical after that notice is removed. The verifier enforces both facts: archive
> **189/189**, checkout **173/173**, and 16 low-value historical tool logs retained
> archive-only.

---

## 0. STATUS — done vs. gates remaining (2026-07-20)

> **2026-07-23 CURRENT INPUT-MARGIN UPDATE — this block supersedes older package
> and PC817 pull-up statements below.** Exactly the 40 `Rpu_*` parts
> (`R4,R6,…,R82`) are **47 kΩ**; unrelated 10 kΩ networks are unchanged.
> The board stays 271 parts / 223 nets with unchanged copper and netclasses.
> Current immutable package: **`kicad/fab_revD_2026-07-23_r5/`**, 271 / 28 DNP /
> 243 placed / 226 JLC / **27 JLC lines** / 17 hand-solder. The dedicated
> pull-up line is UNI-ROYAL `0805W8F4702T5E`, LCSC C17713. Electrical basis
> and binding per-channel physical gate: remediation spec §R4 + FA-9. The
> external 47 kΩ network is authoritative only with RP2040 GP6–GP13 PUE/PDE
> disabled and U1/U2 MCP23017 GPPUA/GPPUB commanded and read back `0x00`;
> any mismatch is STOP-SHIP. `R_TAPPU_*` remains a distinct 10 kΩ tap-drain
> network. Production firmware identity is build `rel-0c746b5747143b8011b01d43`,
> cfg `05d808411db4bb0d`, UF2 SHA-256
> `d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae`.
> `_r4/` and every older package are tombstoned; never upload from them.
> Never order from any older rev-D package.

> **⚠⚠ ROUND-2 + ROUND-3 + FINALIZE UPDATE 2026-07-21 (Codex round-2 findings
> R2-1…R2-17, then Codex re-review findings 1–8) — this block wins over BOTH blocks
> below.** Closing record = **`phase8_revD_round2_report_2026-07-21.md`** (final
> statuses 16 CLOSED · 1 DISPOSITIONED, recorded HEADs, definitive open gates).
> Board is now **271 parts / 223 nets**, netclasses **103/4/13/82/21** (Safety_Rail
> EXACTLY 13 unchanged): + J16 protection stack (F1 polyfuse / JP1 default-OPEN 3V3
> link / U46 TCA4307 / U47 SRV05-4 with VP upstream of the polyfuse since round 3),
> + REV_ID straps R144/R145 (rev-D = 0b01), + tap probe pads TP17–TP24 + TP silk
> legend, Q17–Q20 MPN-locked to onsemi 2N7002LT1G (C16338), 10 M pinned to C26108.
> Release DRC = `kicad/revD/DRC-revD-round3-r1.rpt` (0/0/0); as-current fab package
> = **`kicad/fab_revD_2026-07-21_r3/`** (round-1 dir and `_r2/` tombstoned
> in-directory — never upload from them); ERC baseline 1 waived + 39 (WVR-ERC-2).
> Firmware = **v1.2.2** (pad-OE lock, epoch classifier + alias guard, FI-1 bench
> build, identity line; NOT flashed). First-article pack = FA-1…**FA-12**
> (≥ 100 MΩ probe rule, per-channel PC817B qual, J16 short recovery). PC817B
> disposition sharpened in remediation spec **§R4-A** (no redesign — wetting-rail
> constraint). Where the two blocks below say 262/217, `DRC-revD-remediation-r3.rpt`,
> `fab_revD_2026-07-21/`, or v1.2.x < v1.2.2 — THIS block wins.

> **⚠ REMEDIATION UPDATE 2026-07-21 (Codex NO-GO campaign; spec =
> `phase8_revD_remediation_spec_2026-07-21.md`):** the board was REGENERATED and FULLY
> RE-ROUTED. Where the 2026-07-20 status below says otherwise, THIS block wins:
> - **Item E redesigned (R1, closes C1+H1):** resistive taps replaced by four
>   unidirectional 2N7002 stages (R_TAPIN 1M / R_TAPPU 10k / R_TAPG 10M; reads inverted;
>   firmware v1.2 contract). **262 parts / 217 nets**; netclasses
>   **97/4/13/82/21** exact (Safety_Rail still EXACTLY 13); 680k GONE from the BOM
>   (+1M/+10M). Diff vs rev-C still CLEAN, still ZERO rev-C removals.
> - **DRU re-derived (R2, closes H2):** working voltages measured/derived (FIELD ≤ 14 V
>   populated / 34 Vpk basis; MACHINE ≤ 37 Vpk, 24 VAC fieldsheet), IPC-2221B B1 0.6 mm
>   minimum, requirement CONFIRMED at 2.5/3.2 mm; rule values now carry the JLC ±20 %
>   etch-tolerance allowance: **2.65 / 3.35 / 1.6 mm**. Re-routed: kicad-cli DRC
>   **0/0/0** (`DRC-revD-remediation-r3.rpt` — the release-evidence report; r1/r2 were
>   intermediate runs of the same rules), routed-mode audit **ALL PASS**, measured
>   minima **L↔F 2.650 mm / L↔M 3.350 mm / machine ch↔ch 2.325 mm** (straddler 3.580,
>   relay rows 3.559, opto rows and J15 region ≥ 6).
> - **M3:** all fabricated F.SilkS ≥ 1.0 mm / 0.15 mm stroke; the four KEYED cross-mate
>   warnings 1.2 mm / 0.20 mm.
> - **M4:** all 7 MCV connectors on project-local `_D1.4` footprints
>   (`kicad/wsl_footprints.pretty/`): drill 1.4 mm (Phoenix drilling plan), pad 2.0×3.6
>   (0.30 mm annular). System KiCad library untouched.
> - **M2:** `route_revD.py --check-only` now runs clean on KiCad 10.0.2
>   (`BOARD.Delete()` fix; the GetIsRuleArea crash is gone) — the routed artifact is
>   reproducible on the installed toolchain.
> - The 2026-07-20 "≤ 3.27 V" divider read-bound is obsolete twice over (first by
>   COR-2, now by R1 removing the divider entirely) — do not quote it. (No live text in
>   this file carries it anymore; this bullet is the tombstone.)
>
> **RELEASE-ARTIFACTS UPDATE 2026-07-21 (same campaign — closes H6/H7/H8/M6):**
> - **H6:** `scripts/export_fab_revD.py` written + RUN → **`kicad/fab_revD_2026-07-21/`**
>   hashed as-ordered package (refuses-if-exists verified live). Equality asserts:
>   **262 parts / 27 DNP / 235 placed / 218 JLC / 22 JLC lines / 17 hand-solder**, every
>   placed refdes proven in netlist+board+CPL; **D_PROT hard-locked to MDD SS34, LCSC
>   C8678, SMA** at all three levels; no SS14 anywhere. Hand-solder BOM + **harness BOM**
>   (`docs/phase8_revD_harness_bom.csv` — the J15/J16 mating-plug + CP-MSTB coding BOM
>   that H6/M7 flagged as previously nonexistent) ship in the package.
> - **H7:** coding-profile install procedure CORRECTED everywhere (the profile fits the
>   **PLUG** or an inverted header — never pressed into a standard MCV G-3.5 header;
>   header side = remove the coding rib at the matching pole), with a **sacrificial-pair
>   proof** as numbered first-article step FA-8. Lane-21 build-sheet termination data
>   corrected with a dated note (MC 1,5: **7 mm strip / 0.22–0.25 N·m / ≤ 0.5 mm²
>   insulated ferrule** — was 8 mm / 0.5 N·m / 0.75–1.0 mm²).
> - **H8:** `phase8_pair_enclosure_spec.md` re-specced for 250×240 (panel stack 670 mm,
>   MK pattern 242×232, dimensioned §1.1 panel table, §1.2 row-39 bottom-edge copper
>   constraint binding on the lip/backplate); sourcing brief hard req #1 reissued at
>   ≥ 310×670 mm with 700-mm-class candidates flagged marginal.
> - **M6:** rev-D first-article/bench pack GENERATED from the netlist + routed board
>   (`scripts/generate_first_article_docs_revD.py` → `docs/phase8_revD_first_article_
>   pack.md` + 262-row refdes-map CSV): 46-refdes-shift table, TP map, FA-1…FA-11
>   procedures incl. the R1.9 ≥ 70 °C tap fault injection, GPB poke, ADC read,
>   cross-mate/sacrificial-pair, R4 V_CE sampling. Rev-C bench artifacts remain WRONG
>   for rev-D boards — use only the generated pack.
>
> **CAMPAIGN CLOSED 2026-07-21 —** final status of all 18 Codex findings (15 CLOSED,
> M5/M7 DISPOSITIONED with evidence, H5 PARTIAL with recorded residuals), the recorded
> repo HEADs for clean-clone reproduction, and the full open-gates list live in
> **`phase8_revD_remediation_report_2026-07-21.md`** — the campaign's closing record.
> C3's last residual (WSL Systems clean-clone CRLF smoke failure) closed at finalize
> (WSL Systems `f1bd326`, `.gitattributes` LF pin on `website.html`).

**DONE (this campaign, all in new files):**
- **Spec** — `phase8_revD_change_spec.md`, items A–G, electrical math independently re-derived
  and confirmed in the verify pass.
- **Netlist** — `scripts/generate_kicad_netlist_revD.py` → `kicad/wsl-phase8b-revD.net`:
  **252 parts / 213 nets** *(2026-07-20 figures — now **262 / 217** per the remediation
  banner)*, deterministic regeneration, ERC waiver gate enforced fail-closed
  (WVR-ERC-1: exactly 1 benign Pico-ground error + 40 baseline warnings; any drift aborts).
- **Diff vs rev-C** — `scripts/diff_netlist_revC_to_revD.py` → CLEAN: 36 added parts, 29 added
  nets, 11 touch-point nets additions-only, 173 nets byte-unchanged, **0 removals**, sole
  changed part = D_PROT SS14→SS34 (whitelisted, run-log FR-3).
- **Board — FULLY ROUTED (2026-07-20)** — `kicad/revD/wsl-phase8b-revD.kicad_pcb`: 250×240 mm,
  252 parts *(2026-07-20; the remediation re-route carries 262)*, routed to zero by
  `scripts/route_revD.py` (+ `_lib`/`_logic`; deterministic,
  rev-C house style re-derived for the rev-D placement). Post-route gates: kicad-cli DRC
  **0 violations / 0 unconnected / 0 footprint errors** (`DRC-revD-routed-r3.rpt`, live
  `.kicad_dru` creepage rules — proven to actually fire via a scratchpad mutation test —
  netclasses re-applied **93/4/13/82/21** exact before DRC); `audit_revD_board.py` in routed
  board mode **ALL PASS** incl. zone fills and the Safety_Rail==13 stop-ship invariant;
  independent post-route verification passed all 8 checks (isolation geometry L-F 2.501 mm
  ≥ 2.5, L-M 3.200 mm ≥ 3.2, opto rows ≥ 5.656 mm; no plane cheating; USB keep-out clear).
  Review-fix pass RD-VIA-1 doubled the five single-point power vias (copper-only).
  **Honesty note:** routing executed while gate G8/OG-1 was still open — recorded as
  process violation **PV-1**, not sanctioned; artifact conditional on the G8 sign-off.
- **Process artifacts** — footprint-vs-datasheet reviews FR-1…FR-7 recorded in
  `phase8_revD_run_log.md`; review-fix pass closed 6 distinct findings (item-E temperature
  qualification, J3/J15 + J13/J16 cross-mate coding, SS34 swap, OG-1 surfaced as blocking,
  WVR-ERC-1 recorded, run log backfilled with genuinely-performed reviews); open-issues
  sweep walked G1–G14 + the risk register (COR-2/COR-3 doc corrections); post-route review
  fix pass (RD-VIA-1, PV-1, COR-4, refdes-doc first-article gate); full tool chain re-run
  green after every pass.
- **OG-1 enclosure re-check — RESOLVED with evidence (2026-07-20).** Verdict: **240 mm is a
  spec update, not a conflict.** No fleet enclosure, subpanel, or backplate has been
  purchased (purchases were explicitly frozen pending this gate; the 2026-07-14 pair
  enclosure spec is a spec/sourcing document; the sourcing brief is still open research;
  HANDOFF task #12 still open). Only purchased boxes: two Ogrmar 8×6×4 already disqualified
  at 225 mm, and the lane-21/22 pilot Saginaw SCE-24EL2008LP whose ~578×428 mm panel class
  takes a single 250×240 board trivially. Layout D re-math at 240 mm: 20+240+150+240+20 =
  **670 mm panel height × 310 mm width** — fits the incumbent SCE-30EL2408LP's SCE-30P24
  subpanel (686×533 mm usable) with **16 mm to spare** (was 46 mm at 225). The COR-3 J_PI
  +9.5 mm move is noise against the ~80–150 mm internal-ribbon budget (pre-made IDC
  assemblies, ordered later; all glands are bottom-face field/Cat6). Row-39 bottom-edge
  copper (1.28 mm to routed edge) carries as a **design constraint on the not-yet-designed
  enclosure lip/clamp/backplate** — nothing exists yet to check it against. Dylan's formal
  240 mm sign-off is still open (folded into G14; run-log OG-1 sign-off line still blank).
- **Backups** — sacred rev-C snapshot re-hash 189/189 after every batch; external mirrors +
  verified zips in `C:\Users\Dylan DeYoung\WSL_Backups\` (`2026-07-20_phase8_revC_revD`,
  refreshed with the routed board + final docs, and `2026-07-20_phase8_revD_routed`).

**GATES REMAINING (fab order is blocked until all clear — checklist has the detail; all are
owner decisions, physical/powered sessions, or export steps — no open design work):**
1. **G8 residual — Dylan's formal sign-off on the 250×225 → 250×240 growth.** The enclosure
   re-check half is RESOLVED (evidence above); the sign-off half rides G14. If declined:
   36-row re-spin + full re-route (routed artifact discarded per PV-1).
2. **G7 — rev-C carried verify items 6–7** (per-channel front-end choice, arc-suppression
   sizing) — blocked on the powered at-machine metering session (meter tapped-lead live
   voltages BEFORE reconnecting any board); resolve or record an explicit waiver.
3. ~~G11 — fab export~~ **DONE 2026-07-21** (`scripts/export_fab_revD.py` →
   `kicad/fab_revD_2026-07-21/`, refuses-if-exists, equality asserts + D_PROT lock —
   see the release-artifacts banner).
4. **G12 — manual Gerber inspection + JLC preview** (incl. the five doubled power vias
   and the row-39 bottom edge; review PDF is in the package's `review/` dir).
5. **G13 — harness/coding ORDER** — the BOM now exists (`docs/phase8_revD_harness_bom.csv`,
   1840447/1840405 plugs + CP-MSTB 1734634 profiles + band colors + corrected termination
   data); the purchase itself still ships WITH the boards; profiles fitted before first
   article (install per the corrected H7 rule — profile in the PLUG, sacrificial pair
   first).
6. **First-article and machine-safety gates** — checklist §2: per-board test docs for rev-D refdes are
   GENERATED (M6: `docs/phase8_revD_first_article_pack.md`; re-run the generator if the
   design moves), then rails/GPB/ADC/tap tests incl. the **at-temperature (≥70 °C)
   rail-tap repeat (OG-4 — cold-only does not discharge it)**, the physical cross-mate
   refusal tests, and the FA-8 sacrificial-pair coding proof. The resulting board
   remains installation-NO-GO until FA-13 closes the physically open J14.3–4
   Stop/control-power architecture, proves bounded Stop→power-drop behavior,
   and closes the lane-21/22 pit-interlock disposition. Those lanes have no
   C.I.S.; any installed/new pit interlock must be proved separately in its
   approved upstream safety-disconnect path, not merely at J14. FA-14 requires qualified-electrician,
   listed-instrument proof of protective-earth continuity/bonding and hot/neutral
   polarity. Neither mains nor PE-test current may enter Rev-D.
7. **Characterization session** for analog population (DC1–DC3) — CT current channels + temp
   ride the external-module path (J16 / USB-ADC); nothing analog populates on-board, ever.
8. **G14 — Dylan's overall review** of this change list + spec + checklist + run log
   (parked decisions: OG-1 sign-off, G7 waiver-or-session, J16 polyfuse, OUT-B override).

---

## LANDED IN REV-D

### A. FIELD_WET_V bleed / minimum-load resistor — ✅ rev-C change-list item 5, FINALLY LANDED
- The rev-C carryover: `block_supplies()` had no bleed, so the unregulated TMA-0505S floated
  TP4 to ~11–14 V unloaded (board #1 measured ~11 V; per-board measurement governs).
- Implemented as **R_WET_BLEED1/2 = 2 × 2k2 0805 in parallel (1.1 kΩ)** across
  `FIELD_WET_V`→`FIELD_GND`: 4.5 mA steady bleed (inside the 2–5 mA budget), 89 mW worst-case
  per resistor < 125 mW rating — no new footprint class, no new resistor value.
- 0 new nets, 0 class deltas, entirely FIELD-domain; GND↔FIELD_GND zero-shared-node invariant
  untouched. First article: **TP4 unloaded must read ≤ ~6 V** — if it still floats high, the
  bleed didn't make it.

### B. Pico USB clearance from J1 — ✅ rev-C change-list item 3, FINALLY LANDED
- The rev-C carryover Dylan explicitly asked for: rev-B AND rev-C both shipped the USB jammed
  against J1 (A1/J1 byte-identical across the two revs; flashing needed a hand-shaved
  right-angle cable or pre-solder BOOTSEL).
- Rev-D placement moves the Pico so its micro-USB faces the **top board edge** — the cable
  overmold hangs off-board. A documented **16 × 12 × 40 mm keep-out envelope** is drawn on
  Dwgs_User and must survive routing. J_PWR/D_PROT moved with it. **COR-3 (2026-07-20):** the
  earlier "J_PI unchanged" claim here was wrong — as placed, J_PI moved **+9.5 mm right,
  (126, 10, 90) → (135.5, 10, 90)**, and the Pico landed at (100, 33, 0) not the spec's
  recommended (92, 33, 0) (Rpu-column collision, documented in `place_components_revD.py`).
  Pi ribbon length/dress and the enclosure ribbon opening are folded into the OG-1 enclosure
  re-check.
- **SWD stays DROPPED** (Dylan 2026-06-25, rev-C item 2) — no debug header was silently
  re-added. Ordinary-cable UF2 flashing is the requirement; the compiled-OFF firmware
  detectors guarantee at least one reflash per board after Phase 0.
- 0 netlist delta. First article: off-the-shelf micro-B seats with the J1 ribbon mated,
  BOOTSEL reachable, UF2 flash succeeds without the shaved cable.

### C. IN-B GPB opto bank — 8 × PC817B channels AUX4–AUX11 + new field connector J15
- Catalog §2 item 3: breaks the ≥5-sensors-for-3-AUX-channels contention deadlock (BE Klixon
  aux, ball-return exit photoeye, distributor prox, door/service switches, index pulses).
- 8 channels on MCP_IN_B (0x21) GPB0–7, cloning the proven `opto_input()` pattern exactly
  (PC817B + Rin 2k2 FIELD + **Rpu 47k LOGIC**, dry-contact default, active-low, no
  fitted capacitor — the first-order 47k × 50 pF receiver node is ~2.35 µs and
  debounce lives in firmware). Appended at the END of `SLOW_INPUT_PINS` so no existing refdes
  shifted.
- **J15 / `J_SLOW_IN_C`** — Phoenix MCV 1×10 (same proven class as J3), pins 1–8 signals,
  9–10 FIELD_GND. Mating plug **1840447** folded onto the harness BOM in the same spec cycle
  (the rev-B/-C mating-connector BOM gap does not get a third occurrence).
- **Cross-mate hazard closed (run-log FR-4):** J15 and J3 take the SAME 1840447 plug on the
  same field edge — a swap is electrically silent but crosses cycle sensors with AUX contacts.
  Mandatory **Phoenix CP-MSTB 1734634 coding profiles** (J3 pole 1, J15 pole 10), distinct
  harness band colors (J3 white / J15 yellow), silk warnings on the board. First article
  includes a physical cross-mate refusal test. **Install rule corrected 2026-07-21 (H7):
  profile fits the PLUG, never a standard header; sacrificial-pair proof (FA-8) before
  coding production parts; parts + corrected termination data on
  `docs/phase8_revD_harness_bom.csv`.**
- 25 parts, 24 new nets; +8 Logic_Signal, +16 Field_Sense; 8 new crossings of the EXISTING
  PC817 barrier class — no new `.kicad_dru` rules needed. Wetting +13.8 mA worst case.
- **Placement consequence — the one real layout pressure:** 40 opto rows do NOT fit the
  225 mm board (true KiCad 10 DIP-4_W7.62 courtyard is 5.59–5.68 mm, not the spec's original
  5.25 mm premise) → **board grew to 250×240 mm** (spec §C.4 fallback 3, bottom mounting
  holes now y=236). **This is gate OG-1 — PENDING Dylan sign-off + enclosure re-check**
  (`phase8_pair_enclosure_spec.md` still assumes 225 mm). Alternative if declined: 36 rows.
- Software companion — **LANDED 2026-07-21 (Codex audit H3 remediation)**:
  `controller_io.IN_B_MAP_REVD` (AUX4-11 on GPB0-7) with EXPLICIT per-board
  `board_rev` selection (`IN_B_MAPS`, unknown rev = hard error), dual-generator
  drift guards (rev-B/C AND rev-D, `tests/test_pin_map_drift.py` + both
  `__main__` guards), `read_inputs_b` two-port read, AUX4-11 in the
  per-board `WSL_DIAG_AUX_ROLES_L<lane>` surface (the unscoped compatibility
  map is one-board-only; dormant-unless-mapped, stuck-exempt), and
  stable-time debounce on all diagnostics slow inputs
  (`WSL_SLOW_DEBOUNCE_N`, default 3 samples ≈60 ms @ 50 Hz; FSM safety path
  stays raw unless `WSL_SLOW_DEBOUNCE_FSM_N` is deliberately raised — flagged).
  Originally scoped to ship in the
  separate 2026-07-19 diagnostics software campaign — NOT this board task.
- **2026-07-24 diagnostic-integrity amendment:** pair startup resolves every
  board's AUX map before opening hardware, refuses partial pair maps and more
  than one `exit_beam` source. IN-B/FIELD_WET blindness invalidates rather than
  shifts pending return, BE-current, distributor-gap, stale-channel, and held
  field-input evidence; external sensor-supply blindness invalidates its
  dependent exit/index evidence only. Recovery is a raw/debounced level
  baseline, completion alarms wait for the current sample, runtime gate-off
  intervals invalidate evidence, and pair returns receive a one-timeout drain
  quarantine before tracking resumes. AUX10 remains existing
  Rev-D capacity—this amendment does not add copper or require another spin.
  Queue rejection and runtime gate-off also no longer consume observed
  incidents: lane and platform one-shots keep immutable occurrence stamps,
  bounded retry is severity-first, current states are canceled/re-proven,
  service-start obligations clear only after local durable persistence, and
  shutdown interleaves offer/drain passes down to a one-record queue. Foreign
  health relays use an atomically fsync'd write-ahead ledger: planner state and
  every concrete lane obligation fit before any offer; alert/recovery rows have
  restart-stable identities; ambiguous failures replay the exact row; and an
  alert completes before its exact-family recovery. If a fault recurs while an
  ambiguous recovery is pending, the ledger serializes that recovery followed
  by a distinct re-alert rather than clearing a current fault. Quarantine
  notifications cannot recurse on their own server rejection. These are
  software/operations changes, not Rev-D copper requirements.
- **2026-07-24 P0 allocation correction:** J14.3–4 is physically OPEN in the
  authoritative harness and the field rail cannot arm. Physical inspection
  found no C.I.S. device or wiring on lanes 21/22; whether another pit-entry
  interlock exists remains open. Rev-D's GPB capacity is therefore prioritized
  ahead of generic door/manual options: provisional AUX4=`stop_request`,
  AUX5=`pit_interlock_request` only if an installed/new device is approved,
  AUX6=`control_power_ok`/breaker auxiliary, AUX7/AUX8=S/T digital current
  switches if selected, AUX9=one measured optional dry contact,
  AUX10=`sensor_24v_ok`, AUX11=`field_wet_ok`. Do not configure a fictitious
  `cis_request` on lanes 21/22. AUX4–AUX9 are reservations only:
  no role is mapped until signal form, landing, isolation, exact software
  semantics, open-wire behavior, and FA-13 proof are approved. Only isolated
  volt-free contacts may enter J15.

### D. VCC_5V board-self-health ADC divider (GP26/ADC0)
- Catalog §2 item 4, platform tier: 5 V sag under the ~460 mA 6-coil load, brownout trending.
  Sees no FIELD/MACHINE quantity — complements machine-side sensing, never replaces it.
- 10k/10k divider + 100 nF from `VCC_5V` → new net `ADC_VCC5_SENSE` → Pico pin 31 (GP26).
  Worst-case input 2.63 V < 3.3 V full-scale; Thevenin 5 kΩ < the ADC's 10 kΩ limit; 318 Hz
  RC corner is fine on an ADC channel (not an edge-capable input — constraint 8 untouched).
  Permanent 0.25 mA load on VCC_5V — legal (only SAFE_*/rail are load-forbidden).
- ADC_VREF (pin 35) stays NC — referenced on the Pico module itself (spec drift finding DR-3).
- 3 parts, 1 new net (+1 Logic_Signal, exact-name classifier entry).
- First article: GP26 reads VCC_5V/2 within ±3 % of the TP1 DMM value; 6-coil sag visible.

### E. Rail-predicate edge-ordering taps — NE555_OUT / WDOG_KICK / ARM_PERMIT / RP2040_OK
**REDESIGNED 2026-07-21 (remediation spec R1 — closes Codex C1 + H1; supersedes the
resistive-tap text that stood here through 2026-07-20):**
- Catalog §2 item 5: 1 ms edge-ordered capture on GP16–GP19 records causal predicate
  transitions and supports advisory cause inference (wdt_reset vs pi_death vs
  arm_drop) when independent evidence says the rail dropped. Taps land ONLY on
  existing observable points (TP8/TP13/TP14 nets + NE555_OUT); none directly
  observes `RELAY_ENABLE_RAIL`/TP16 or proves Q14/J14/rail stuck-on or stuck-open
  behavior.
- Per tap, a **2N7002 common-source inverter** (SOT-23 — the existing `Qled_*` class):
  observed net → **R_TAPIN 1M** → gate (+ **R_TAPG 10M** to GND on the three 3.3 V taps;
  the 555's push-pull output is never high-Z — asymmetry deliberate); VCC_3V3 →
  **R_TAPPU 10k** → drain → GPIO. **The GPIO touches ONLY the drain — a stuck-high GPIO
  injects ZERO DC into the observed net in unfaulted hardware (C1's headline scenario dies
  at the netlist), and the ±20 V gate rating absorbs the 555's unguaranteed VOH (H1).**
  Worst DOUBLE fault (D-G short + stuck GPIO + driver high-Z + 85 °C): ≤ 0.56 µA →
  0.056 V on RAIL_GATE, ≥ 8× under the partial-hold onset; transistor-free ceiling
  3.3 V/1.01 M = 3.3 µA. **Reads are INVERTED — firmware v1.2 contract (remediation spec
  R3) owns the inversion, the register-readback input-only invariant, and the 1 ms noinit
  edge ring.** 15 parts, 8 new nets (+8 Logic_Signal via the `TAP_` prefix rule); BOM:
  −680k, +1M, +10M.
- **Safety_Rail class count stays EXACTLY 13 — design invariant of the spin; any delta in the
  audit is an automatic stop-ship.** No new copper on any SAFE_ net, RELAY_ENABLE_RAIL, or
  RAIL_GATE.
- **COR-1's procedural closure is now defense-in-depth, not the primary barrier:** the
  hardware cannot inject regardless of GPIO state; firmware input-only is additionally
  ENFORCED (R3.2 register-readback + build-failing host direction test). The first-article
  fault-injection gate still repeats AT TEMPERATURE (≥70 °C, remediation spec R1.9 — OG-4;
  a cold-only pass does not discharge it), now including physically inserted D-G shorts.
  14-row FMEA with stated residual (F9, double component fault incl. resistor-fail-SHORT):
  remediation spec R1.6.

### F. J16 / `J_EXT_I2C` external-analog expansion header
- The integrate-without-a-barrier-class answer to the external-analog verdict: a keyed
  LOGIC-domain MCV 1×6 (proven J13 class) carrying VCC_5V / GND / SDA / SCL / 3V3 / GND, so a
  future **externally-isolated** ADC/sensor module plugs in with zero on-board analog.
- J1-suffices evaluation (required): J1 does NOT suffice — fully occupied by the mated Pi
  ribbon; unconnected pins sit inside the IDC shroud. Decision: dedicated header.
- **Cross-mate hazard closed (run-log FR-5):** J16 and J13 take the SAME 1840405 plug 24 mm
  apart; a swapped lamp harness puts a resistorless LED string across 5 V→GND and wedges
  I2C while MCP_OUT_A holds its last relay state. Coding **1734634** (J13 pole 1, J16
  pole 6), band colors (J13 white / J16 blue), silk warnings, first-article refusal test
  (install per the corrected H7 rule — see item C; parts on the harness BOM CSV).
- 1 part, 0 new nets, 0 class deltas; DNP-tolerant (electrically inert unpopulated).
  Module rules: **≤ 45 mA from pin 1** (R3-7 re-derivation; was 100 mA — the old figure
  used the 23 °C polyfuse hold, which collapses to 90 mA @ 85 °C, so a ≥ 2× margin caps the
  allowance at 45 mA. Re-run the D17 budget before any module lands.) The series polyfuse
  (F1 = 1206L020YR on pin 1) is now FITTED (Codex R2-4), not just a recorded option. I2C
  addresses 0x20–0x23 forbidden.

### G. OUT-B MCP23017 @0x23 — DEFERRED (decision recorded, nothing placed)
- Catalog nice-to-have with zero diagnostics yield. Real cost is board area + I2C stub + 32
  dead routed-around pins on a board whose standing direction is SHRINK — and item F provides
  the same capacity insurance off-board (a $2 MCP23017 breakout on J16 at the same 0x23).
- If Dylan overrides: +2 parts, 0 new nets, 0 class changes, ERC unconnected-pin warnings
  need a new waiver-ledger entry.

### H. D_PROT diode SS14 → SS34 (consequence fix, run-log FR-3)
- Rev-D adds ~+30 mA to a rail whose worst case was already 0.7–0.9 A on a 1 A SS14 —
  an already-thin margin. Value swap to **SS34 (3 A)**,
  same `D_SMA` footprint, zero copper change. Gate-10 package check done: **MDD SS34, LCSC
  C8678, SMA/DO-214AC verified** — SS34 from other vendors ships in SMB/SMC, exactly the
  G5LE-1/-14 trap class; **any MPN substitution re-runs the review.**
- R3-7 note: the J16 module allowance was re-derived 100 mA → **45 mA** (see §F and the
  change-spec §H.4 derivation). This *lowers* the D17 worst case to ~0.78–0.98 A, so SS34
  keeps comfortable margin — the re-derivation does not reopen this swap.

---

## EXPLICITLY EXCLUDED FROM REV-D (do not re-add; do not "helpfully" restore)

### X1. SAFE_* loop taps — OUT OF SCOPE, FMEA-gated
Catalog §2 item 6: any tap on SAFE_TBSC_RETURN / SAFE_STOP_RETURN / any SAFE_ net is a
separate FMEA-gated decision. **No new copper on any SAFE_ net in this spin** — the rev-D
audit enforces frozen SAFE_ pad membership (no pads beyond rev-C's) and fails closed.
J14.3–4 is only an existing board source position and remains physically open in the
released harness. Its future Stop/control-power interface is an external,
measured, fail-safe design decision; never bridge it to make the rail arm.
Placing a new pit switch only at J14 would drop board permission but would not
open a welded downstream contact, so it cannot replace an approved upstream
pit-entry safety disconnect.

### X2. Isolated machine-analog front-end — EXTERNAL, PERMANENTLY
Catalog "Do NOT put on the board": it would introduce a third isolation-barrier component
class (new `.kicad_dru` rules), FIELD-room area, and unbudgeted field supply — for signals
whose source (CT clamp) is at the machine anyway. **A USB ADC on the Pi dodges the whole
question**; J16 (item F) is the board's only concession, and any module's isolation lives ON
the module.

### X3. RELAY_ENABLE_RAIL divider — DELETED BY A PRIOR CRITIC, stays deleted
A divider is a permanent load on the safety rail and its high-side short would re-reference
it, violating observe-only. **VCC_5V sensing only (item D).** Do not re-add under any
"more observability" rationale.

---

## DEFERRED TO THE CHARACTERIZATION SESSION (no board change; population decisions)

### DC1. CT current channels (S/T attribution, BE class, ball-return class)
Ride the external analog module (USB-ADC per the catalog's mandatory analog path; J16 is the
I2C-module alternative). Population, CT selection, and thresholds come out of the powered
at-machine characterization session — the board only provides the integration point.

### DC2. Temperature channel (motor/gearbox contact temp, DS18B20/NTC class)
Same external-module path (catalog sensor-shortlist item 6 — "never the Pi header directly").
Deferred with DC1.

### DC3. Rev-C verify-item 6 — **CLOSED IN COPPER (r6, 2026-07-25)**; item 7 still OPEN
- **Item 6 — per-channel input front-end: dry-contact vs 24 VAC-rectified sense.**
  **CLOSED IN COPPER.** Dylan reopened copper on 2026-07-25 so the first article would be
  fleet-intent rather than frozen-and-bodged; the r6 fab iteration landed per-channel
  protection on **all 40** channels:
  `FIELD_WET_V → Rin (2k2) → **Dser** (1N4148WS series block) → PC817 LED → field pin`,
  with an **anti-parallel `Dclamp`** (1N4148WS) across the LED and a **DNP** logic-side
  `Cflt` (0805). Every `FIELD_LED_<n>` now carries **three** nodes. `Dser_*`/`Dclamp_*`
  (D18–D97) are **POPULATED by default** — no per-channel stuffing decision; `Cflt_*`
  (C17–C56) are DNP. **PBZ and DIELL_L/DIELL_R may now be landed directly on board inputs**
  (prove per board with **FA-15**: LED reverse = 0.35 V ± 0.1 V), and the **harness 1N4007
  interposer is SUPERSEDED — do not build it.**
  Authority: `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md`; **current package
  `kicad/fab_revD_2026-07-25_r7/`** — the release build of the r6 design (same copper,
  identical `source_board_sha256`; `_r6/` is tombstoned so exactly one package is current).
  **Per-channel stuffing table: `docs/phase8_revD_r6_channel_stuffing.csv`** (also inside
  the package). It states in one place what the crew asks: all 40 channels take
  `Dser` + `Dclamp` **populated, uniform, no decision**; the DNP `Cflt` is the only
  decision and is **measure-then-stuff** with the deciding measurement in the row.

  > **RETRACTION.** Between 2026-07-21 and 2026-07-25 this entry read *"all 40 `FIELD_LED_*`
  > nets carry exactly two nodes… no series-diode footprint, no anti-parallel clamp
  > footprint, and no logic-side filter-cap footprint on any of the 40 channels… REQUIRES
  > COPPER and is deferred to the fleet revision… PBZ and DIELL_L/DIELL_R must NOT be landed
  > directly on a bare board input."* That text was **correct when written and is now false
  > in every clause.** It is retained here only so an older copy can be recognised.

  **What item 6 does NOT close (still gates the powered at-machine metering session — meter
  tapped-lead live voltages BEFORE reconnecting any board):** the cam-channel AC/DC class
  (r6 makes a 24 VAC cam channel *survivable*, not *usable* — it trips `CHATTER_MAX_CAM`
  continuously and needs a **firmware** change), and the `FIELD_WET_V` headroom under any
  driven AC channel (zero bulk capacitance; 16.8 mA peak/channel; budgeted for **N = 0**).
- **Item 7 — relay arc suppression sizing.** Snubber positions remain DNP, unchanged from
  rev-C; size from the measured inductive load in the powered session before populating.
- Item 8 (5 V budget) is resolved on paper by spec §H.4 + the SS34 swap; bench PSU sizing
  guidance (≥1 A) stands.
- **These must be resolved or explicitly waived before the fab order** — see readiness
  checklist gate G7. Do not repeat rev-C's "green gates ≠ everything landed" mistake.

---

## PROCESS (carried forward from rev-C + new this spin)

### P1. Footprint-pads-vs-datasheet review — per part class, per spin, even for reused classes
Scripture (the G5LE-1/-14 bug killed all six rev-B relays). Rev-D reviews FR-1…FR-7 recorded
in `phase8_revD_run_log.md`, including the K1–K7 relay-map regression (coil pads 2/5, COM 1,
NO 3, NC 4 unused — unchanged).

### P2. First-article bench test of one of each NEW I/O type
Extended for rev-D: GPB bank poke, ADC divider read, rail-tap ordering (cold AND at
temperature), J16 bus check, cross-mate refusal. The generated pack now also
contains FA-13/FA-14 system-level gates for Stop/control-power demand-to-drop,
the lane-21/22 pit-interlock disposition, and external PE/polarity
commissioning; those do not become bare-board claims.
Full plan in the readiness checklist §2.

### P3. Export every spin to a NEW dated directory — export script refuses an existing dir
The rmtree incident (rev-C-as-ordered overwrote rev-B-as-ordered in place) must be
structurally impossible: `export_fab_revD.py` takes REV/output-dir as parameters and
**refuses to run if the output dir exists**. Never overwrite an as-ordered package.

### P4. NEW — ERC waiver ledger, enforced fail-closed
Rev-C never ran ERC (its `.erc` is 0 bytes); rev-D defines the baseline. WVR-ERC-1 (exactly
1 benign Pico AGND/GND pin-type error + 40 warnings) is enforced by
`generate_kicad_netlist_revD.py::check_erc_waiver()` — any drift aborts the run; changing the
constants requires a new waiver entry in the run log.

### P5. NEW — machine-readable rev-to-rev netlist diff with a change whitelist
`diff_netlist_revC_to_revD.py` must print CLEAN: additions-only on touch-point nets, zero
removals, and any changed part explicitly whitelisted (currently only D_PROT SS14→SS34).
Carry the pattern to every future spin.

### P6. NEW — cross-mate coding on every same-PN plug pair sharing an edge
MC pin-asymmetry keying only prevents reversed insertion, never cross-mating. Any two
connectors taking the same plug PN get CP-MSTB coding at different pole positions + band
colors + silk, and a first-article refusal test.

### P7. Sacred-file discipline
Rev-C artifacts carry revB filenames — copy-then-modify only, hash-verify the snapshot
manifest before and after tool runs, and never commit/stage from a build campaign that
shares a tree with unrelated uncommitted work.
