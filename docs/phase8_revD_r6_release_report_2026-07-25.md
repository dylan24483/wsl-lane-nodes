# Phase 8 Rev-D — r6 Input-Protection **Release Report**

**Date:** 2026-07-25 · **Board revision:** D (never fabricated) · **Fab iteration:** r6 ·
**Released package: `kicad/fab_revD_2026-07-25_r7/`**

**Firmware was NOT touched and NOT flashed.** No rev-B/rev-C design file was read-modified;
the sacred snapshot re-verified 189/189 with zero failures after every batch.

---

## 0. The one-paragraph version

Dylan reopened copper on **2026-07-25** so the first article would be **fleet-intent rather
than frozen-and-bodged** — schedule risk on this program is bench time, not design time, and
rev-C's bench campaign is already done. Every one of the 40 optocoupler input channels now
carries a **series blocking diode** and an **anti-parallel clamp**, both **populated**, plus a
**DNP logic-side filter cap**. 120 new parts, 40 new nets, **zero new assembled part
classes**, **zero refdes churn**, **zero dimensional change**, and `Safety_Rail` still exactly
**13**. The gate chain is green end to end and the package is fab-ready. What is **not**
closed is everything that needs physical boards or a powered machine: the first article
itself, FA-9's numeric qualification, OG-4 at temperature, the powered characterization
session, the firmware flash, and four owner sign-offs.

---

## 1. What changed

### 1.1 The copper (landed in the r6 build, unchanged by this release build)

```
before:  FIELD_WET_V -[Rin 2k2]- [PC817 LED] - field pin           (FIELD_LED_<n> = 2 nodes)

after:   FIELD_WET_V -[Rin 2k2]- FIELD_RIN_<n> -[Dser]- FIELD_LED_<n> -[PC817 LED]- field pin
                                                    |                         |
                                            [Dclamp, anti-parallel across the LED]
LOGIC:   VCC_3V3 -[Rpu 47k]- FAST_/SLOW_<n> -[Cflt 0805, DNP]- GND
```

| Part | Refdes | Package | Population |
|---|---|---|---|
| `Dser_<n>` — series block | `D18`…`D97` (even/odd interleaved with the clamp) | 1N4148WS SOD-323 | **POPULATED, always. Never DNP — a DNP series position leaves the channel OPEN-CIRCUIT.** |
| `Dclamp_<n>` — anti-parallel clamp | same range | 1N4148WS SOD-323 | **POPULATED** (variant B — clamp DNP — was specified and rejected) |
| `Cflt_<n>` — logic-side filter | `C17`…`C56` | 0805 X7R | **DNP by design.** 10 nF × 8 fast / 2.2 µF × 32 slow |

**Why both, and why neither is DNP** — the three findings the design rests on:

1. **A clamp alone fails.** It conducts on the reverse half-cycle and backfeeds `Rin` into
   the **shared** `FIELD_WET_V` rail, which the unregulated TMA-0505S cannot sink. Solving
   self-consistently for PBZ at 33 VDC: `(33 − 0.7 − Vw)/2200 = Vw/1100` → **Vw = 10.77 V at
   9.79 mA**. One over-voltage channel corrupts the wetting rail for **all 40**.
2. **A series diode alone is weak.** The LED's reverse voltage is then set by a **leakage
   divider** (diode ≈ nA vs LED `I_R` 10 µA @ 4 V) — protected by an unspecified parameter
   ratio rather than by construction. The clamp pins it at **≈ 0.35 V**, and FA-15 measures it.
3. **The series element cannot be a DNP-empty land, and it cannot be a 0 Ω link either.** A
   0 Ω is an `R`-prefix part: 40 of them shift every resistor above `R3` and destroy
   `EXPECTED_OPTO_PULLUPS = {R4, R6, …, R82}` plus seven manual chapters — and **0805
   (pads ±0.913 mm) and SOD-323 (pads ±1.05 mm) cannot share a land**, so the "0 Ω now,
   diode later" swap does not survive contact with a real footprint.

**`Rin` stays 2k2.** The rev-D 47 kΩ collector pull-up had already bought the margin
(4.7× → 22×); the diode spends 22× → **≈ 17×**, still an order of magnitude of headroom.
Option A′ (1k8, restoring exact `I_F`) was evaluated and rejected.

### 1.2 The release build (this pass — **no copper changed**)

`source_board_sha256` **`695cd7b1…3de7`** and `source_netlist_sha256` **`c93b06fa…1fd7`** are
**identical in the r6 and r7 manifests**. What r7 adds:

- **Per-channel equality gate.** The old gate asserted totals (391/68/323/306/27/17). Totals
  are **equally satisfied by 80 clamps and no series diode** — the exact configuration the
  safety case rejects. `assert_r6_input_protection()` now proves each channel independently
  (topology, polarity, population, membership in placed/CPL/JLC, fast/slow cap split,
  refdes uniqueness, and no r6 part on any safety or wetting net).
- **One-diode-line hard lock.** All 88 placed 1N4148 → a single onsemi **1N4148WS / SOD-323 /
  LCSC C118873** line with the exact designator string.
- **Field-stuffed MPN locks** (`FIELD_STUFF_LOCK`) — the gap `PART_LOCK` structurally could
  not cover, because it only ever described what *JLC* fits.
- **Per-channel stuffing BOM** — new artifact, 40 rows, derived from the netlist.
- **FA-16** — new unpowered first-article census gate.
- Two stale test constants fixed (they had been failing on a *correct* board).

### 1.3 Why the released directory is `_r7` and not `_r6`

The exporter **refuses to run if the output directory exists**, and packages are immutable —
the rev-B/rev-C `rmtree` incident must stay structurally impossible. `_r6/` was already
exported and committed, and the gate/paperwork changes above alter emitted files, so the
re-export needed a new directory. **`r6` names the DESIGN ITERATION; the directory suffix
names the EXPORT BUILD** — exactly as r1/r2/r3 were three builds of one design on 2026-07-21.
`_r6/` carries a tombstone that says plainly it is **not electrically superseded**, so the
"exactly one current package" invariant holds without implying a defect that does not exist.

---

## 2. Every gate number

### 2.1 Design gate chain

| Gate | Command | Result |
|---|---|---|
| Generator | `py -3 scripts/generate_kicad_netlist_revD.py` | exit 0 · part registry **391** · ERC waiver **1 waived error + 39 warnings** (unchanged baseline) · netlist sha256 `c93b06fa…1fd7` |
| Netlist diff | `py -3 scripts/diff_netlist_revC_to_revD.py` | **RESULT CLEAN** · DEEP_TOUCH **107/107** · DEEP_MOVE **32/32** · UNCHANGED_NETS **77** |
| Netclasses | `apply_netclasses_revD.py` | Logic_Signal **103** · Logic_Power **4** · **Safety_Rail 13** · Field_Sense **122** · Machine_Output **21** = **263** |
| Route self-check | `route_revD.py --check-only` | 2281 actions · **0 problems** |
| DRC (fresh) | `kicad-cli 10.0.2 pcb drc --severity-error --severity-warning` | **0 violations · 0 unconnected** · exit 0 |
| Board audit | `audit_revD_board.py <routed board>` | **ALL PASS** — every r6 assertion **40/40**; `STOP-SHIP GUARD: Safety_Rail is EXACTLY 13` PASS |
| Rev-C sacred | `verify_revC_snapshot.py --compare-checkout` | archive **189/189** · checkout **173/173** · failures **0** · **EXIT=0** |
| Lane suite | `pytest tests/ -q` | **777 passed** |
| Firmware | `pytest firmware/rp2040/test/` | **9 passed + 4 subtests** — untouched, unflashed |

### 2.2 Export / package

| | |
|---|---|
| Output | `kicad/fab_revD_2026-07-25_r7/` · **ALL EXPORT GATES PASS** |
| Counts | parts **391** · DNP **68** · placed **323** · JLC-placed **306** · JLC lines **27** · hand-solder **17** |
| Manifest | **46** members, sha256 each · `source_board_sha256` `695cd7b1…3de7` · `source_netlist_sha256` `c93b06fa…1fd7` |
| `wsl-phase8b-revD-fab-package.zip` | 2,805,837 B · sha256 `cffc8c5d15fba1b9…` |
| `wsl-phase8b-revD-gerber-drill.zip` | 469,434 B · sha256 `bac711c81637a0a6…` |
| `wsl-phase8b-revD-jlc-standard-pcba-upload.zip` | 469,039 B · sha256 `58077bcbaf6bfcd6…` |
| Refuse-if-exists | verified live (a second run at the same `--out` refuses) |
| Board outline | **250.0 × 240.0 mm** · `INPUT_PITCH` **5.700 mm** · opto-row slack 0.0200 mm untouched — **no dimension moved** |

### 2.3 Counts, before → after r6

| | pre-r6 (r5) | r6 / r7 |
|---|---|---|
| Netlist parts | 271 | **391** (+120) |
| DNP | 28 | **68** (+40 `Cflt`) |
| Placed / JLC-placed | 243 / 226 | **323 / 306** (+80) |
| Named nets | 223 | **263** (+40 `FIELD_RIN_*`) |
| `Field_Sense` | 82 | **122** |
| **`Safety_Rail`** | **13** | **13 — unchanged** |
| JLC assembled **lines** | 27 | **27** — the 80 diodes joined the existing 1N4148WS line (qty 8 → **88**) |
| `FIELD_WET_V` load | 74.5 mA (37 %) | **58.1 mA (29 %)** — *lower* |

### 2.4 MPN locks in force

**Preserved (unchanged):** D17 = MDD **SS34** / C8678 SMA · Q17–Q20 = onsemi **2N7002LT1G** /
C16338 · R135/R138/R141 = UNI-ROYAL **10M** / C26108 · R4,R6,…,R82 = UNI-ROYAL **47k
0805W8F4702T5E** / C17713 · U46 **TCA4307DGKR** / C880333 · U47 Semtech **SRV05-4.TCT** /
C13612 · F1 Littelfuse **1206L020YR** / C207035 · K1–K6 **G5LE-14 5VDC** / C116963 ·
U4–U43 **PC817B** / C5692981 · U1–U3 **MCP23017-E/SO** / C47023.

**New, locked at this release:**

| Part | MPN | LCSC | Class | Review |
|---|---|---|---|---|
| `Dser_*` + `Dclamp_*` (80) | onsemi **1N4148WS** | **C118873** | JLC Extended, qty **88** on ONE line | FR-16 |
| `Cflt_*` slow (32, DNP) | Samsung **CL21B225KAFNNNE** 2.2 µF 25 V X7R 0805 | **C19110** | field-stuffed by us | FR-17 |
| `Cflt_*` fast (8, DNP) | TORCH **C0805B103K500NT** 10 nF 50 V X7R 0805 | **C17702767** | field-stuffed by us | FR-18 |

1 µF (C28323) **rejected on the record**: 749 nF worst-effective < the 951 nF 60 Hz floor.
C26108 remains flagged "verify stock at order time" (OOS at LCSC retail 2026-07-21).

---

## 3. Stuffing policy

**`docs/phase8_revD_r6_channel_stuffing.csv`** (also `assembly/…-r6-channel-stuffing.csv` in
the package). 40 rows; every refdes and connector pin **derived from the netlist**.

### 3.1 The diodes: no decision at all

**All 40 channels get `Dser` + `Dclamp` POPULATED. Uniform. No per-channel decision, no
per-lane record to lose across 32 lanes.** This is a deliberate reversal of the original
recommendation's per-channel stuffing plan, and it also protects the **11 AUX spares** whose
signal class nobody has chosen yet — the case a stuffing table loses first.

### 3.2 The cap: the only decision, and it is measure-then-stuff

| Channels | Evidence | Decision |
|---|---|---|
| **GS1–GS10, BS** | **MEASURED** 11 VDC dry | DC dry — `Cflt` **UNFITTED**. Nothing pending. |
| **PBZ** | **MEASURED** 33 VDC (rectified-24 VAC class) | The canonical over-voltage channel: 27–28 V reverse vs a 6 V `V_R` (4.5–4.7×). `Cflt` **UNFITTED** (DC). **FA-15 mandatory.** |
| **DIELL_L / DIELL_R** | **MEASURED** 15.4–16 V, self-powered | 9.4–11 V reverse at the rev-D rail (1.6–1.8× over). `Cflt` **UNFITTED**. **FA-15 mandatory.** FAST channels — never > 22 nF. |
| **SA · SB · SC · TA1 · TA2 · TB** (cams) | **UNMEASURED** — 24 VAC ladder prior (the ~21 Ω coil sneak paths that invalidated cold mapping twice) | **MEASURE-THEN-STUFF.** FAST: even if AC, the answer is still **no cap** — survivable, not usable. Tap at the switch or change firmware. |
| **FOUL** | **UNMEASURED** — lamp-wire, rectified/AC prior | **MEASURE-THEN-STUFF.** SLOW, so 2.2 µF is *available* — but foul is an **edge** input; check 183 ms de-assert against foul-detect timing first. |
| **GP · PBC · OS** | **UNMEASURED** | **MEASURE-THEN-STUFF.** PBC sits next to the 33 VDC PBZ tap — expect a DC reading, which still means unfitted. |
| **TENTH · MAN_T · MAN_S · MAN_SWS · MAN_SWSR** | **UNMEASURED** — console/manual switches, dry-contact prior; unlanded on the first article | **MEASURE-THEN-STUFF** before landing. |
| **AUX1–AUX11** | **SPARE** — no signal assigned | Unfitted. |

### 3.3 The measurement that decides it

With the **OEM brain powered and this board disconnected**, meter the channel wire to machine
common on **DC volts and AC volts** through a full machine cycle, then **scope-confirm** (a
DMM cannot distinguish 60 Hz AC from a chopped DC train). Then:

- **`V_AC` < 1 V rms** → DC class. **Leave `Cflt` unfitted whatever `V_DC` reads** — `Dser` +
  `Dclamp` already cover DC to the 1N4148WS's 75 V `V_RRM` (2.65–3.5× margin at the measured
  extremes).
- **`V_AC` ≥ 5 V rms on a SLOW channel** with a release budget **≥ 200 ms** → **fit 2.2 µF**
  and re-run FA-9 edge timing.
- **`V_AC` ≥ 5 V rms on a FAST channel** (SA/SB/SC/TA1/TA2/TB/DIELL_L/DIELL_R) → **never fit a
  cap.** 60 Hz integration needs ≥ 951 nF → **183 ms de-assert** against a **1 ms** edge
  budget (92× `DEBOUNCE_CAM_US`, 122 % of `CAM_*_GRACE_MS`). That channel is **electrically
  survivable but not functionally usable** — it needs a firmware change or the metering-guide
  fallback of tapping the cam at the switch.
- **Record N** — the count of channels metered as *driven* 24 VAC — either way. The
  `FIELD_WET_V` budget assumes **N = 0**; **N ≥ 1 reopens it** (16.8 mA peak/channel, zero
  bulk capacitance, ≤ 11 coincident channels before the TMA-0505S runs out).

---

## 4. The two owner decisions carried forward (r6 spec §G)

Neither is implemented. **My recommendation is OUT for both, this spin.**

### G-1 — DNP-only isolated `RELAY_ENABLE_RAIL` / TP16 state feedback → **RECOMMEND OUT**

Codex called this the highest-value remaining addition and **on merit that is defensible** —
the objection is timing and gate integrity, not value.

- **It cannot be built without moving the stop-ship guard or cheating it.** Any isolated sense
  needs a rail-side element; the node between its series resistor and the barrier is **a new
  net on the safety rail**. Named honestly (`SAFE_FB_*`) it takes `Safety_Rail` **13 → 14** =
  automatic stop-ship. Named to dodge the classifier, it is **deliberate misclassification of
  a safety net.** I will not spec that.
- **Changing the guard in *this* spin destroys its signal.** "rev-D adds zero safety copper" is
  the brightest stop-ship line on the board; the week we add 120 parts and re-route 40 rows is
  the worst possible week to move it.
- **Pads invite population** (standing prohibition X3 exists because a rail load was already
  deleted once).
- **The marginal yield is small: the rail is already ~80 % observed.** The item-E tap stages
  give four of the five AND-topology inputs. The only unobserved element is `Q_RAIL`'s own
  pass-FET failure — detected within **one commanded motion** by cam confirmation
  (`CAM_*_GRACE_MS` = 150 ms) and the `MAX_MOTION_MS` = 8000 backstop. That is a
  **serviceability** gap, not a safety hole. The rev-C bench campaign already proved all six
  rail conditions drop TP16 independently.

**If overruled, the only acceptable form** is a fully isolated second PC817 (never a divider,
never a rail load path), net named `SAFE_FB_<n>` so it classifies honestly, both
`EXPECTED_COUNTS["Safety_Rail"]` and `EXPECTED["Safety_Rail"]` moved **13 → 14 explicitly and
loudly with rationale comments**, and the populated-state rail load + its effect on the
`Q_RAIL` gate and NE555 timing written into the FMEA **before** any board is populated.
Geometry note: the r6 corridor is FIELD domain and cannot host it — a rail-side part must live
in LOGIC/MACHINE under the 3.35 mm contract. **That is a real placement problem. Budget time.**

### G-2 — Per-motor current sensing → **CONFIRM Codex. RECOMMEND OUT.**

- **The design inputs do not exist.** None of the seven switched legs (S, T, SP, BE, M, M2, M1)
  has ever been metered under load. Whether each leg is a motor line or a contactor coil, and
  at what voltage, is unresolved in the repo.
- **No ADC budget, and closing it adds an isolation-barrier class.** GP26 is taken by
  `ADC_VCC5_SENSE`; two free channels for seven motors means a mux or I²C ADC — new IC class,
  new address, and **MACHINE-domain sensing crossing into LOGIC**. The FR discipline that
  killed the rev-B relays applies in full.
- **It does not fit** — the machine band (x ≥ 184.2) is fully occupied by K1–K7, their
  snubber/MOV networks and J6–J12.
- **The dominant hazard is already covered** without copper: `MAX_MOTION_MS` = 8000 (≈ 9 s
  measured), cam-based motion confirmation, and the NE555 hardware rail drop. Current sensing
  would add **stall/jam** detection — a maintenance signal, not a safety one.

**What would unblock it** (cheap additions to a session that must happen anyway): clamp-meter
each of the 7 switched legs for voltage class / steady current / inrush peak+duration; capture
a jam-stall current or take nameplate FLA/LRA; and resolve whether the **24 VAC ladder stays
energised after the 82-70 brain is removed** — which also gates the cam-channel question.

---

## 5. Honest remaining gates

**Nothing below is closed by this release. Every one needs physical boards, a powered machine,
or a human signature.**

| # | Gate | Owner | Blocks |
|---|---|---|---|
| 1 | **First article itself** — boards do not exist. FA-1…FA-16 are unexecuted. | bench | fleet quantity, lane deployment |
| 2 | **FA-16 (new)** — unpowered 40/40 orientation + continuity census, volts recorded per channel per direction | bench | trusting any r6 channel |
| 3 | **FA-15 (new)** — driven reverse-bias proof, **0.35 V ± 0.1 V**, > 1 V = clamp missing/open/reversed = STOP | bench, powered | landing PBZ / DIELL |
| 4 | **FA-9 numeric** — per-channel `V_CE(sat)` census, `I_C` capability + aging reserve at min `FIELD_WET` and ≥ 70 °C, hot idle-HIGH/leakage, **≤ 100 µs edge with every `Cflt` unfitted**. Operating point is now **1.34 mA** (`Vw` = 5 V) / **≈ 1.12 mA** at the loaded minimum — **not** the retired 1.7 mA. | bench, powered | fleet-release status (G15) |
| 5 | **OG-4 / FA-7 step 4 at ≥ 70 °C** — hot high-Z rail-tap fault injection; a cold-only pass does not discharge it | bench, hot | item-E gate |
| 6 | **Firmware flash** — not touched, not flashed. FA-11 posture assert (verified manifest + UF2 SHA + exact `id.build`/`id.cfg`, `fi1=0`) is unexecuted. | bench | FA-9, FA-11, LIVE |
| 7 | **Powered at-machine characterization session** — cam AC/DC class + RMS + frequency; `FIELD_WET_V` headroom (scope TP4, **record N**); relay snubber/MOV sizing (G7 item 7). **Meter tapped-lead live voltages BEFORE reconnecting any board.** | field | G7, the stuffing decision, per-motor sensing |
| 8 | **G12** — manual Gerber/JLC preview inspection before paying | owner | fab order |
| 9 | **G13 / OG-3** — harness + CP-MSTB coding-part **order** (the BOM exists; the order does not) | owner | ship-with-boards |
| 10 | **G8 / OG-1** — Dylan's formal 250 × 240 sign-off (enclosure re-check resolved with evidence; the signature line is still blank) | Dylan | enclosure/backplate purchase |
| 11 | **G14** — Dylan's overall rev-D doc + spec review | Dylan | fab order |
| 12 | **G15** — EXPERIMENTAL-ORDER acceptance line (blank) | Dylan | placing the order |
| 13 | **G16** — positive-actuation return bound measured on the target Pi | software | LIVE, not fab |
| 14 | **Field-pin ↔ field-pin clearance 0.4807 mm** vs an IPC-2221B 0.6 mm requirement — pre-existing geometry, dispositioned **OPEN** for the fleet revision, deliberately **not** made to look compliant | fleet rev | fleet order, not this one |
| 15 | **AC cam channels are survivable, not usable** — needs a firmware change or tapping at the switch | firmware / field | full FSM cycle timing |
| 16 | **Off-disk backup copy** — `WSL_Backups` is on the same physical volume | Dylan | disaster recovery |

### Known-and-accepted, recorded rather than hidden

- The **DRU `FIELD_LED` clearance** minimum is **0.910 mm = 1.52×** the 0.6 mm rule — measured
  by bracketing with kicad-cli, and the binding pair is an r6 clamp pad vs the next row's
  `FIELD_LED` track. The earlier "1.06 mm / 1.77×" claim was corrected.
- The PC817B lot has **no guaranteed CTR minimum** at this board's `I_F` — that is what makes
  this an experimental first-article build rather than a fleet release.
