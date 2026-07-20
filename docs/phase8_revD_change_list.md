# Phase 8 Lane-Controller — Rev-D Change List

> Consolidated 2026-07-20 at the end of the rev-D design campaign (spec → netlist → placement →
> verify → fix pass). Companion docs: `phase8_revD_change_spec.md` (full electrical detail,
> items A–G), `phase8_revD_run_log.md` (gate records, waivers, footprint reviews),
> `phase8_revD_readiness_checklist.md` (pre-order gates — **read before any fab order**).
> Source catalog: `phase8_diagnostics_target_conditions_2026-07-19.md` §2 "Earns its place"
> items 1–5.
>
> **SACRED-FILE RULE:** every rev-B/rev-C design file is untouched (189/189 snapshot-manifest
> hashes verified before AND after every tool run — `backups/revC_design_snapshot_2026-07-19/
> MANIFEST.json`). All rev-D work is in NEW `*revD*` files; nothing is committed or staged.
> Reminder: **every rev-C artifact carries a revB filename** — `generate_kicad_netlist_revB.py`
> IS the rev-C generator and `kicad/fab_revB_routed_manual/` IS the rev-C-as-ordered package.

---

## 0. STATUS — done vs. gates remaining (2026-07-20)

**DONE (this campaign, all in new files):**
- **Spec** — `phase8_revD_change_spec.md`, items A–G, electrical math independently re-derived
  and confirmed in the verify pass.
- **Netlist** — `scripts/generate_kicad_netlist_revD.py` → `kicad/wsl-phase8b-revD.net`:
  **252 parts / 213 nets**, deterministic regeneration, ERC waiver gate enforced fail-closed
  (WVR-ERC-1: exactly 1 benign Pico-ground error + 40 baseline warnings; any drift aborts).
- **Diff vs rev-C** — `scripts/diff_netlist_revC_to_revD.py` → CLEAN: 36 added parts, 29 added
  nets, 11 touch-point nets additions-only, 173 nets byte-unchanged, **0 removals**, sole
  changed part = D_PROT SS14→SS34 (whitelisted, run-log FR-3).
- **Board (route-READY, not routed)** — `kicad/revD/wsl-phase8b-revD.kicad_pcb`: 250×240 mm,
  252 parts placed, netclasses **93/4/13/82/21** exact, sidecars (`.kicad_pro/.prl/.dru`)
  copied and the `.dru` isolation rules proven live, USB keep-out envelope drawn, placement
  DRC **0 violations** (499 unconnected pads = expected pre-route), `audit_revD_board.py`
  **ALL PASS in both netlist and board modes** and provably fails closed.
- **Process artifacts** — footprint-vs-datasheet reviews FR-1…FR-7 recorded in
  `phase8_revD_run_log.md`; review-fix pass closed 6 distinct findings (item-E temperature
  qualification, J3/J15 + J13/J16 cross-mate coding, SS34 swap, OG-1 surfaced as blocking,
  WVR-ERC-1 recorded, run log backfilled with genuinely-performed reviews); full tool chain
  re-run green after the fixes.

**GATES REMAINING (fab order is blocked until all clear — checklist has the detail):**
1. **OG-1 — Dylan sign-off on the 250×225 → 250×240 board growth + enclosure re-check.**
   Blocking. Alternative if declined: 36 opto rows fit 225 mm.
2. **Routing.** The board is route-ready, NOT routed. Manual route (FreeRouting is formally
   abandoned in this repo — no `.ses` exists; DSN cannot carry the creepage rules), then
   post-route DRC + routed-mode audit + zone fills.
3. **Fab export + Gerber inspection.** `export_fab_revD.py` not yet written (new dated dir,
   refuses-if-exists — the rmtree lesson).
4. **Rev-C carried verify items 6–7** (per-channel front-end choice, arc-suppression sizing) —
   blocked on the powered at-machine metering session; resolve or record an explicit waiver.
5. **Characterization session** for analog population — CT current channels + temp ride the
   external-module path (J16 / USB-ADC); nothing analog populates on-board, ever.
6. **Dylan's overall review** of this change list + the spec.

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
  Dwgs_User and must survive routing. J_PWR/D_PROT moved with it; J_PI unchanged.
- **SWD stays DROPPED** (Dylan 2026-06-25, rev-C item 2) — no debug header was silently
  re-added. Ordinary-cable UF2 flashing is the requirement; the compiled-OFF firmware
  detectors guarantee at least one reflash per board after Phase 0.
- 0 netlist delta. First article: off-the-shelf micro-B seats with the J1 ribbon mated,
  BOOTSEL reachable, UF2 flash succeeds without the shaved cable.

### C. IN-B GPB opto bank — 8 × PC817B channels AUX4–AUX11 + new field connector J15
- Catalog §2 item 3: breaks the ≥5-sensors-for-3-AUX-channels contention deadlock (BE Klixon
  aux, ball-return exit photoeye, distributor prox, door/service switches, index pulses).
- 8 channels on MCP_IN_B (0x21) GPB0–7, cloning the proven `opto_input()` pattern exactly
  (PC817B + Rin 2k2 FIELD + Rpu 10k LOGIC, dry-contact default, active-low, **no RC** —
  debounce lives in firmware). Appended at the END of `SLOW_INPUT_PINS` so no existing refdes
  shifted.
- **J15 / `J_SLOW_IN_C`** — Phoenix MCV 1×10 (same proven class as J3), pins 1–8 signals,
  9–10 FIELD_GND. Mating plug **1840447** folded onto the harness BOM in the same spec cycle
  (the rev-B/-C mating-connector BOM gap does not get a third occurrence).
- **Cross-mate hazard closed (run-log FR-4):** J15 and J3 take the SAME 1840447 plug on the
  same field edge — a swap is electrically silent but crosses cycle sensors with AUX contacts.
  Mandatory **Phoenix CP-MSTB 1734634 coding profiles** (J3 pole 1, J15 pole 10), distinct
  harness band colors (J3 white / J15 yellow), silk warnings on the board. First article
  includes a physical cross-mate refusal test.
- 25 parts, 24 new nets; +8 Logic_Signal, +16 Field_Sense; 8 new crossings of the EXISTING
  PC817 barrier class — no new `.kicad_dru` rules needed. Wetting +13.8 mA worst case.
- **Placement consequence — the one real layout pressure:** 40 opto rows do NOT fit the
  225 mm board (true KiCad 10 DIP-4_W7.62 courtyard is 5.59–5.68 mm, not the spec's original
  5.25 mm premise) → **board grew to 250×240 mm** (spec §C.4 fallback 3, bottom mounting
  holes now y=236). **This is gate OG-1 — PENDING Dylan sign-off + enclosure re-check**
  (`phase8_pair_enclosure_spec.md` still assumes 225 mm). Alternative if declined: 36 rows.
- Software companion (`IN_B_MAP`, startup self-test, stuck-input coverage) ships in the
  separate 2026-07-19 diagnostics software campaign — NOT this board task.

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

### E. Rail-drop edge-ordering taps — NE555_OUT / WDOG_KICK / ARM_PERMIT / RP2040_OK
- Catalog §2 item 5: 1 ms edge-ordered capture on GP16–GP19 turns undifferentiated "rail
  down" into ordered fault codes (wdt_reset vs pi_death vs arm_drop). Taps land ONLY on
  existing observable points (TP8/TP13/TP14 nets + NE555_OUT).
- 3.3 V nets: single series **680 kΩ** (a divider would break reading; do NOT "simplify" the
  value down — 100 k fails the hold-off proof even cold). 5 V NE555_OUT: 100k/680k divider
  (ratio bounds the absolute-worst read ≤ 3.27 V < 3.3 V). One genuinely new BOM value (680k
  0805); 5 parts, 4 new nets (+4 Logic_Signal via `TAP_` prefix rule).
- **Safety_Rail class count stays EXACTLY 13 — design invariant of the spin; any delta in the
  audit is an automatic stop-ship.** No new copper on any SAFE_ net, RELAY_ENABLE_RAIL, or
  RAIL_GATE.
- **Corrected hold-off proof (run-log COR-1 / gate OG-4):** the original 25 °C "provably OFF"
  claim was overbroad — V_BE(on) falls ~2 mV/K, so a stuck-high tap CAN partially hold the
  pass-FET at ≥~70 °C. Binding closures: **(1)** firmware never configures GP16–GP19 as
  outputs; **(2)** deliberate disarm DRIVES ARM_PERMIT low (push-pull), never tristates;
  **(3)** the first-article fault-injection gate repeats AT TEMPERATURE (≥70 °C on the
  Q_AND_*/Q_RAIL region) — a cold-only pass does not discharge it. Option evaluated, NOT
  taken (needs its own observe-only-contract review): R_RAIL_GATE_PULLUP 100k→22k.

### F. J16 / `J_EXT_I2C` external-analog expansion header
- The integrate-without-a-barrier-class answer to the external-analog verdict: a keyed
  LOGIC-domain MCV 1×6 (proven J13 class) carrying VCC_5V / GND / SDA / SCL / 3V3 / GND, so a
  future **externally-isolated** ADC/sensor module plugs in with zero on-board analog.
- J1-suffices evaluation (required): J1 does NOT suffice — fully occupied by the mated Pi
  ribbon; unconnected pins sit inside the IDC shroud. Decision: dedicated header.
- **Cross-mate hazard closed (run-log FR-5):** J16 and J13 take the SAME 1840405 plug 24 mm
  apart; a swapped lamp harness puts a resistorless LED string across 5 V→GND and wedges
  I2C while MCP_OUT_A holds its last relay state. Coding **1734634** (J13 pole 1, J16
  pole 6), band colors (J13 white / J16 blue), silk warnings, first-article refusal test.
- 1 part, 0 new nets, 0 class deltas; DNP-tolerant (electrically inert unpopulated).
  Module rules: ≤100 mA from pin 1 (re-run the D17 budget before any module lands — a
  polyfuse in series with pin 1 is a recorded open option for Dylan), I2C addresses
  0x20–0x23 forbidden.

### G. OUT-B MCP23017 @0x23 — DEFERRED (decision recorded, nothing placed)
- Catalog nice-to-have with zero diagnostics yield. Real cost is board area + I2C stub + 32
  dead routed-around pins on a board whose standing direction is SHRINK — and item F provides
  the same capacity insurance off-board (a $2 MCP23017 breakout on J16 at the same 0x23).
- If Dylan overrides: +2 parts, 0 new nets, 0 class changes, ERC unconnected-pin warnings
  need a new waiver-ledger entry.

### H. D_PROT diode SS14 → SS34 (consequence fix, run-log FR-3)
- Rev-D adds ~+30 mA to a rail whose worst case was already 0.7–0.9 A on a 1 A SS14, and
  J16's sanctioned 100 mA module allowance would cross 1 A. Value swap to **SS34 (3 A)**,
  same `D_SMA` footprint, zero copper change. Gate-10 package check done: **MDD SS34, LCSC
  C8678, SMA/DO-214AC verified** — SS34 from other vendors ships in SMB/SMC, exactly the
  G5LE-1/-14 trap class; **any MPN substitution re-runs the review.**

---

## EXPLICITLY EXCLUDED FROM REV-D (do not re-add; do not "helpfully" restore)

### X1. SAFE_* loop taps — OUT OF SCOPE, FMEA-gated
Catalog §2 item 6: any tap on SAFE_TBSC_RETURN / SAFE_STOP_RETURN / any SAFE_ net is a
separate FMEA-gated decision. **No new copper on any SAFE_ net in this spin** — the rev-D
audit enforces frozen SAFE_ pad membership (no pads beyond rev-C's) and fails closed.

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

### DC3. Rev-C verify-items 6–7 carried OPEN (honest — rev-C's own gate-scope lesson)
- **Item 6 — per-channel input front-end: dry-contact vs 24 VAC-rectified sense.** Rev-D
  carries the dry-contact default on all 40 channels (field-validated input-side on machine
  22). Still blocked on the powered at-machine metering (meter tapped-lead live voltages
  BEFORE reconnecting any board). May change per-channel population/BOM, not copper.
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
temperature), J16 bus check, cross-mate refusal. Full plan in the readiness checklist §2.

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
