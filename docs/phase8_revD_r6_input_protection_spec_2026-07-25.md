# Phase 8 rev-D — r6 Input-Protection Design Spec

**Date:** 2026-07-25
**Board revision:** **D** (unchanged — never fabricated). **Fab package iteration: r6.**
**Status:** IMPLEMENTABLE SPEC. Downstream agents implement this literally.
**Authorises:** copper change to all 40 optocoupler input channels.
**Supersedes for the input front end:** `docs/phase8_revD_input_frontend_recommendation.md` §3/§4
(recommendation, not a spec) and `docs/phase8_revD_round5_claude_audit_2026-07-25.md` §5.1
(the FREEZE recommendation — **Dylan reopened copper on 2026-07-25**; the audit's electrical
findings stand and are carried forward, its schedule recommendation is overtaken by the owner
decision).

**Owner context.** Dylan reopened copper so the first article is as close to fleet-intent as
possible rather than frozen-and-bodged. The fab order goes out this week. Schedule risk is bench
time, not design time. This spec is written to that constraint: it is deliberately the *smallest*
copper change that closes the electrical case by construction, and §D shows the re-route is far
cheaper than the round-5 audit assumed.

---

## 0. Verified baseline — re-derived for this spec, not inherited

Every number below was re-measured from source or from the placed board in this session.
Commands are given so a reviewer can reproduce them.

| Fact | Value | How verified |
|---|---|---|
| `opto_input()` is one hardcoded topology, all 40 channels | `scripts/generate_kicad_netlist_revD.py:381-406`, called at `:1065` and `:1068`, no `dnp=`/variant parameter | read |
| All 40 `FIELD_LED_*` nets have exactly 2 nodes | 40 nets, `Rin_* pin 2` + `PC817 pin 1` | parsed `kicad/wsl-phase8b-revD.net` |
| Zero diodes/clamps/TVS anywhere in the FIELD domain | 17 `D*` parts: 7 `Dfly_*` (SOD-323), 7 `MOV_*` (SMA, DNP), `D_WDOG_TIMING`, `D_WDOG_TRIG`, `D_PROT`/SS34 — all LOGIC or MACHINE domain | parsed netlist |
| Current part / net counts | **271 parts, 223 nets** (`R`145 `U`47 `Q`20 `D`17 `C`16 `J`16 `K`7 `A`1 `F`1 `JP`1) | parsed netlist |
| Netclass counts | Logic_Signal 103 / Logic_Power 4 / **Safety_Rail 13** / Field_Sense 82 / Machine_Output 21 = 223 | `scripts/apply_netclasses_revD.py:38-46`, `scripts/audit_revD_board.py:47-49` |
| rev-C sacred snapshot intact | `archive total 189; verified OK 189; failures 0`, `EXIT=0` | `py -3 scripts/verify_revC_snapshot.py` — **re-run 2026-07-25, PASS** |
| `Device:D` pin map | **pin 1 = K (cathode), pin 2 = A (anode)** | `scripts/generate_kicad_netlist_revD_sklib.py:100-102`; corroborated by `relay_output()` comment "diode cathode to rail" and by D1's emitted netlist (pad 1 = `RELAY_ENABLE_RAIL`) |
| `D_SOD-323` land | 2 × SMD roundrect **0.60 × 0.45 mm** at **x = ±1.05 mm**; courtyard **3.29 × 1.99 mm** | measured on placed D1 via KiCad 10.0.2 `pcbnew` |
| `R_0805_2012Metric` land | pads 1.025 × 1.40 at ±0.913; courtyard **3.45 × 1.99 mm** | measured on placed R3 |
| `C_0805_2012Metric` land | pads 1.45 × 1.00 at ±0.95; courtyard **3.49 × 2.05 mm** | measured on placed C16 |
| Opto land | pad 1 at `(OPTO_X, y)`, pad 2 at `(OPTO_X, y+2.54)`, pads 3/4 at `+7.62`; pad 1.6 × 1.6; courtyard **9.82 × 5.68**, x 72.895–82.715 | measured on placed U4 |
| Row geometry | `row_y(i) = 13.0 + 5.7·i`, i = 0..39; `RIN_X=58`, `OPTO_X=74`, `RPU_X=86`; `BOARD_W=250`, `BOARD_H=240` | `scripts/place_components_revD.py:104-128, 466-472` |
| **Corridor x 59.725 → 72.895 (13.17 mm) is component-free on every row except row 1** | only occupants: `R_WET_BLEED1/2` (R122/R123) at x 62.005–63.995 / 66.005–67.995, y 14.275–17.725 | full-board courtyard sweep via `pcbnew` |
| Corridor copper is only the two nets we are inserting into | 193 segments in x 59.5–73.2: 124 `FIELD_LED_*`, 58 `FIELD_FAST/SLOW_*`, 11 `FIELD_WET_V`/`FIELD_GND` (all at y < 20, row 0/1 area) | track sweep via `pcbnew` |
| ERC baseline | 1 waived error + **39 warnings**, all 39 "Unconnected pin" on *existing* parts | `generate_kicad_netlist_revD.erc`, `grep -c "ERC WARNING"` |
| Firmware constants that bound the filter cap | `DEBOUNCE_CAM_US 2000`, `DEBOUNCE_DIELL_US 500`, `CHATTER_WINDOW_MS 100`, `CHATTER_MAX_CAM 8`, `CHATTER_MAX_DIELL 30`, `CAM_*_GRACE_MS 150`, `MAX_MOTION_MS 8000` | `firmware/rp2040/config.h:208-250, 307-319` |
| Slow-input debounce | `DEFAULT_SLOW_DEBOUNCE_N 3` (60 ms diag), `DEFAULT_SLOW_DEBOUNCE_FSM_N 1` (20 ms FSM) | `lane_node/controller_daemon.py:243-261` |
| Current fab package | `kicad/fab_revD_2026-07-23_r5` is the latest; r1–r5 exist | `ls kicad/` |

**Electrical ground truth carried forward from the round-5 audit (spot-checked, not re-derived):**
PBZ measured 33 VDC; DIELL_L/R measured 15.4–16.0 VDC self-powered; cams sit in the machine's
24 VAC ladder (proven by ~21 Ω coil sneak paths that invalidated cold mapping twice); PC817 LED
absolute-max `V_R` = 6 V, `I_R` max 10 µA at `V_R` = 4 V; rev-D's own 1.1 kΩ `FIELD_WET_V` bleed
lowers `Vw` and therefore **increases** reverse stress volt-for-volt.

---

## A. Per-channel topology (× 40)

### A.1 The emitted network, node by node

`opto_input(name, logic_net, field_net)` emits, for every one of the 40 channels:

```
FIELD_WET_V ──[ Rin_<n>  2k2, 0805 ]── FIELD_RIN_<n> ──[ Dser_<n>  1N4148WS SOD-323 ]── FIELD_LED_<n>
                pad 1        pad 2                        pad 2 (A)          pad 1 (K)      │
                                                                                            │
                                            ┌───────────────────────────────────────────────┤
                                            │                                               │
                                   [ Dclamp_<n> pad 1 (K) ]                        [ OPTO_<n> pad 1 = LED anode ]
                                            │  1N4148WS SOD-323, anti-parallel               │
                                            │                                          (PC817 LED)
                                   [ Dclamp_<n> pad 2 (A) ]                                  │
                                            │                                               │
                                            └──────────── FIELD_<n> ────────────────────────┤
                                                (= FIELD_FAST_<n> | FIELD_SLOW_<n>)   [ OPTO_<n> pad 2 = LED cathode ]
                                                          │
                                                    J_FAST/J_SLOW_* connector pin → machine

LOGIC SIDE (unchanged except one added node):
  VCC_3V3 ──[ Rpu_<n> 47k ]── <FAST_<n> | SLOW_<n>> ── OPTO_<n> pad 4 (collector)
                                       │                OPTO_<n> pad 3 (emitter) ── GND
                                       └──[ Cflt_<n>  0805, DNP ]── GND
                                       └── MCP23017 GPxn  (slow)  |  RP2040 GPn (fast)
```

**Node-by-node net membership after the change:**

| Net | Nodes (before) | Nodes (after) |
|---|---|---|
| `FIELD_WET_V` | `Rin_*` pin 1 ×40, bleed ×2, TMA +Vout | **unchanged** |
| **`FIELD_RIN_<n>`** *(NEW, ×40)* | — | `Rin_<n>` pin 2, `Dser_<n>` pin 2 (A) — **2 nodes** |
| `FIELD_LED_<n>` | `Rin_<n>` pin 2, `OPTO_<n>` pin 1 | `Dser_<n>` pin 1 (K), `Dclamp_<n>` pin 1 (K), `OPTO_<n>` pin 1 — **3 nodes** |
| `FIELD_FAST_<n>` / `FIELD_SLOW_<n>` | connector pin, `OPTO_<n>` pin 2 | + `Dclamp_<n>` pin 2 (A) — **3 nodes** |
| `FAST_<n>` / `SLOW_<n>` | `OPTO_<n>` pin 4, `Rpu_<n>` pin 2, [MCP pin] | + `Cflt_<n>` pin 1 |
| `GND` | … | + `Cflt_<n>` pin 2 ×40 |

**Every net is named. Zero anonymous nets.** `FIELD_RIN_<n>` extends the existing `FIELD_*`
scheme and therefore lands in `Field_Sense` with **no classifier change** — see §E.

### A.2 Polarity, stated unambiguously

Wetting current flows **board → Rin → Dser → LED → field pin → machine contact → FIELD_GND**.

- **`Dser_<n>` (series block).** Anode faces the board (west, toward `Rin`); cathode faces the
  LED (east). Symbol pin 2 = A on `FIELD_RIN_<n>`, pin 1 = K on `FIELD_LED_<n>`.
  **Placement rotation 180°** puts pin 2 west (see §D).
- **`Dclamp_<n>` (anti-parallel clamp).** Cathode on `FIELD_LED_<n>` (LED anode side), anode on
  `FIELD_<n>` (LED cathode / field-pin side). It is **anti-parallel to the LED**: reverse-biased
  by `Vf(LED)` ≈ 1.15 V during normal operation, forward when the field pin goes positive.
  **Placement rotation 270°** puts pin 1 (K) north at the `FIELD_LED` pad and pin 2 (A) south at
  the `FIELD_<n>` pad (verified: `pcbnew` rot 90 puts pin 1 **south**, so 270 puts it north —
  measured on placed R122).
- **`Cflt_<n>`** is non-polar. Value string only; rotation 180° for net access.

### A.3 Why all three, and why the series element cannot be DNP-empty

Carried forward and re-confirmed:

1. **Clamp alone fails.** It does not block DC — it conducts, backfeeding `Rin` into the shared
   `FIELD_WET_V` rail, which the unregulated TMA-0505S cannot sink. Self-consistent solve for PBZ
   at 33 VDC with a clamp and no series diode:
   `(33 − 0.7 − Vw)/2200 = Vw/1100` → **`Vw` = 10.77 V at 9.79 mA**. One over-voltage channel
   drags the wetting rail for all 40 and back-drives the converter to ~2× nominal.
2. **Series diode alone is weak.** The LED's reverse voltage would be set by a **leakage divider**
   between the blocking diode (`I_R` ≤ 5 µA @ 75 V, typ. nA at 28 V) and the LED (`I_R` max 10 µA
   @ 4 V). It works by an unspecified parameter ratio, not by construction.
3. **Together they are deterministic.** With both fitted, reverse current is leakage-only, so the
   clamp's forward drop sets the LED's reverse voltage — see §F.3 for the number (**≈ 0.35 V,
   17× inside the 6 V absolute maximum**).
4. **A DNP-EMPTY series position leaves the channel OPEN-CIRCUIT.** An unpopulated board would
   have all 40 inputs dead. The series position is therefore **never DNP**.

### A.4 Default population — NORMATIVE

> **NORMATIVE DECISION (deviation from the task briefing, justified below):** the series position
> is a **populated 1N4148WS on a SOD-323 land** on all 40 channels — **not** a 0 Ω 0805 link that
> is swapped for a diode per channel. The clamp is **also populated on all 40** by default.
> The **copper is identical either way**; population is a BOM value-string decision, so Variant B
> (§A.6) remains a one-line change.

| Provision | Refdes | Footprint | Value string | Default | Count |
|---|---|---|---|---|---|
| Series block | `Dser_<n>` | `Diode_SMD:D_SOD-323` | `1N4148` | **POPULATED** | 40 |
| Anti-parallel clamp | `Dclamp_<n>` | `Diode_SMD:D_SOD-323` | `1N4148` | **POPULATED** | 40 |
| Logic-side filter cap, slow channels (32) | `Cflt_<n>` | `Capacitor_SMD:C_0805_2012Metric` | `2.2uF X7R DNP` | **DNP** | 32 |
| Logic-side filter cap, fast channels (8) | `Cflt_<n>` | `Capacitor_SMD:C_0805_2012Metric` | `10nF X7R DNP` | **DNP** | 8 |

**Why a populated diode beats a populated 0 Ω 0805 link — six numbered reasons:**

1. **Refdes stability, and it is decisive.** A 0 Ω link is an `R`-prefix part. Adding 40 of them
   inside `opto_input()` shifts **every** resistor refdes above R3 by 40 and destroys
   `EXPECTED_OPTO_PULLUPS = {R4, R6, … R82}` (`audit_revD_board.py:57`), the manual's designator
   tables (`docs/manual_src/01,09,13,20,22,23`), and the `PART_LOCK` 47k note. Diodes (`D`) and
   caps (`C`), instantiated **after** all existing blocks, take `D18–D97` and `C17–C56` and
   change **zero** existing refdes. Verified: current max `D17`, max `C16`.
2. **A 0 Ω link and a diode cannot share a land.** 0805 pads are at ±0.913 mm; SOD-323 at
   ±1.05 mm with 0.60 × 0.45 pads. Choosing 0805 forces an 0805-package diode — a new, uncommon,
   more expensive part class with a new FR review. Choosing SOD-323 makes the 0 Ω option
   unavailable. The link-plus-swap plan does not survive contact with a real land.
3. **Zero new part class, zero new BOM line, zero new LCSC part, zero new Extended-part fee.**
   `("1N4148", "D_SOD-323")` → LCSC **C118873** is already in `PART_LOCK` and already on the BOM
   (8 pcs). The line goes **8 → 88**. `EXPECTED_JLC_LINES` stays **27**.
4. **The CTR cost is already paid.** 22× → **17.1×** worst case (§C). The rev-D 47 kΩ pull-up
   bought 4.7× → 22×; the diode spends a quarter of it.
5. **It eliminates the per-channel stuffing table entirely.** The recommendation's own strongest
   objection to the harness bodge — *"per-channel, per-lane, undocumented in the board BOM, and
   easy to lose across 32 lanes"* — applies verbatim to a per-channel 0R/diode stuffing decision.
   Uniform population is the only variant with no way to get it wrong on lane 27 at 11 pm.
6. **Rail load goes DOWN.** 74.5 mA → 58–64 mA (§F.1). The diode is not a cost here; it is a
   second-order improvement to the least-controlled quantity on the board.

**Why the clamp is also populated by default:**

- In forward (normal) operation it is reverse-biased by `Vf(LED)` ≈ 1.15 V and leaks sub-nA.
  Stolen LED drive: **< 0.00006 %** of 1.34 mA. Electrically free.
- With `Dser` fitted, the clamp is **never a current path** — it carries only `Dser` reverse
  leakage + LED reverse leakage (≤ 15 µA worst case). Its current rating is irrelevant; it is a
  voltage-defining element.
- Both failure modes are **detectable at commissioning, never latent**: a reversed or shorted
  clamp shunts the LED (`Vf` 0.7 V < LED `Vf` 1.15 V) → channel reads dead; an open clamp
  degrades gracefully to series-diode-only (still protected, by leakage ratio). Every channel is
  exercised by the existing GS-map / commissioning procedure, so a dead channel is caught 100 %.
- Cost: 40 × ≈ $0.008 = **$0.32/board**, 40 placements, and no BOM/lock change at all.

### A.5 Per-channel evidence and population rationale

The population is uniform; this table records **why** each class needed it, so the fleet revision
can revisit with data rather than re-deriving.

| Channel(s) | Count | Field evidence | Bare-LED verdict | r6 outcome |
|---|---|---|---|---|
| GS1–GS10, BS | 11 | measured **11 VDC dry** | safe bare | protected anyway (uniform); no cost |
| **PBZ** | 1 | measured **33 VDC** (rectified-24 VAC class) | `V_R` 27–28 V = **4.5–4.7× the 6 V max** | series+clamp; LED reverse → **0.35 V** |
| **DIELL_L, DIELL_R** | 2 | measured **15.4–16.0 VDC**, self-powered, survives brain removal | `V_R` 9.4–11 V = **1.6–1.8× OVER** at the rev-D rail | series+clamp; LED reverse → **0.35 V** |
| **SA, SB, TA1, TA2** (cams) | 4 | **UNMEASURED**; series elements in the 24 VAC ladder (~21 Ω coil sneak paths, two failed cold mappings) | on 24 VAC: `V_R,pk` 28.9 V = **4.82× max**, ~5.2 M avalanche events/day | series+clamp; **plus** see §B.4 — the AC case on a *fast* channel is not closed by hardware alone |
| SC, TB (cam family) | 2 | unmeasured | class open | same as cams |
| GP, OS, PBC, FOUL, TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR | 9 | unmeasured; FOUL is a lamp wire | class open | protected by construction |
| AUX1–AUX11 | 11 | unassigned spares | unknown by definition | protected by construction — **this is the strongest argument for uniform population**: 11 channels whose future signal class cannot be known at stuffing time |

**Policy for the unmeasured classes:** they are protected by construction. No stuffing decision,
no per-lane record, no commissioning step. The only remaining per-channel decision is the
**filter cap**, and that decision is made from a *measurement* (is a 60 Hz pulse train present on
this channel?) taken during the powered characterization session — not guessed at stuffing.

### A.6 Variant B — clamp DNP (the as-briefed default)

Identical copper. One value-string change in the generator: `Dclamp` value `"1N4148"` →
`"1N4148 DNP"`. Consequences: `EXPECTED_DNP` 68 → 108, `EXPECTED_PLACED` 323 → 283,
`EXPECTED_JLC_PLACED` 306 → 266; add a `Dclamp_` branch to the DNP-reason text in
`export_fab_revD.py`; and reinstate a per-channel stuffing table + per-lane commissioning record
for the clamp. **Not recommended** — it re-introduces exactly the "easy to lose across 32 lanes"
failure mode for a saving of $0.32/board, and it leaves the 11 AUX spares unprotected against a
signal class nobody has chosen yet.

---

## B. Part selection + footprint-vs-datasheet review

### FR-16 — onsemi **1N4148WS** (LCSC **C118873**) vs `Diode_SMD:D_SOD-323` — **PASS**

*New usage class (FIELD-domain series block + anti-parallel clamp). Same (MPN, footprint) pair
already fitted 9× on this board — so this is a **usage** review plus a land regression, not a new
fab part class.*

**Identity + stock, fetch-verified 2026-07-25:**
- LCSC C118873 → **1N4148WS**, **onsemi**, SOD-323. **Stock 37,160.**
- JLCPCB library type: **Extended** (already paid for by the existing 8-piece line).
- Datasheet ratings on the listing: **V_RRM 75 V**, I_F(AV) **150 mA**, V_F **1.0 V @ 10 mA**,
  P_D **200 mW**, t_rr **4 ns**, I_R **5 µA @ 75 V**.

**Land vs package:**

| Item | KiCad `D_SOD-323` (measured) | JEDEC SOD-323 / onsemi case | Verdict |
|---|---|---|---|
| Pad size | 0.60 (x) × 0.45 (y) mm, roundrect r=0.25 | terminal 0.25–0.40 long × 0.30–0.45 wide | 0.60 pad vs 0.325 nom terminal → **0.275 mm toe/heel fillet**; pad width 0.45 = terminal max width. IPC-7351 **nominal** density. PASS |
| Pad centre span | **2.10 mm** (±1.05) | overall across leads 2.30–2.70 (2.50 nom) → terminal centres ±1.088 mm | pads **0.038 mm inboard** of terminal centres — inside placement tolerance. PASS |
| Body clearance | courtyard 3.29 × 1.99 mm | body 1.70 × 1.25 mm, standoff 0–0.10 | PASS |
| Layers | F.Cu / F.Mask / F.Paste only (SMD) | — | PASS |

**Polarity — the specific check the G5LE-1/-14 precedent demands:**
- **Symbol:** `Device:D` pin 1 = `K`, pin 2 = `A` (`generate_kicad_netlist_revD_sklib.py:100-102`).
- **Existing usage corroborates:** `relay_output()` writes `fly[1] += relay[2]  # diode cathode to
  rail`; the emitted netlist shows D1 pad 1 on `RELAY_ENABLE_RAIL`. Two independent confirmations.
- **Footprint F.Fab drawing:** cathode bar is the vertical line at **x = −0.30** (y −0.35…+0.35)
  with its lead running **west to x = −0.50**, i.e. toward pad 1 at x = −1.05. The triangle base
  is at x = +0.20 with its lead **east to +0.45**, toward pad 2. **The F.Fab symbol's cathode is
  on pad 1.**
- **Package marking:** 1N4148WS is band-marked at the cathode end.
- **VERDICT: symbol, footprint F.Fab, and package band all agree — pad 1 = cathode = banded end.
  PASS.** Silkscreen carries the matching outline; JLC AOI checks band orientation.

**Electrical margins in this application** (derivations in §F):

| Parameter | Worst-case stress | Rating | Margin |
|---|---|---|---|
| `Dser` reverse (PBZ 33 VDC, clamp fitted) | 27.7 V | 75 V | **2.7×** |
| `Dser` reverse (24 VAC pk, clamp fitted) | 28.6 Vpk, 60 Hz repetitive | 75 V V_RRM | **2.6×** |
| `Dser` forward, DC channel | 1.34 mA | 150 mA | 112× |
| `Dser` forward, 24 VAC channel | 17.2 mA pk / 5.5 mA avg | 150 mA avg, ~450 mA pk | **27×** avg |
| `Dser` dissipation, AC channel | ≈ 3.6 mW | 200 mW | 55× |
| `Dclamp` forward current | ≤ 15 µA (leakage-only) | 150 mA | 10⁴× |
| `t_rr` vs fastest firmware window | 4 ns | `DEBOUNCE_DIELL_US` = 500 µs | 1.25 × 10⁵× |
| Junction capacitance (≈ 2 pF) × Rin 2k2 | 4.4 ns | 1 ms edge budget | 2.3 × 10⁵× |

**Regression:** the 9 existing instances (D1, D3, D5, D7, D9, D11, D15, D16 populated; D13
M1-DNP) are untouched. Same BOM line, quantity **8 → 88**. No new reel, no new feeder.

### FR-17 — Samsung **CL21B225KAFNNNE** 2.2 µF 25 V X7R ±10 % 0805 (LCSC **C19110**) vs `Capacitor_SMD:C_0805_2012Metric` — **PASS (DNP)**

*Slow-channel (MCP23017) AC-integration filter cap. Never assembled by JLC — DNP; fitted at
commissioning only on a channel measured to carry a 60 Hz pulse train.*

- **Identity + class, fetch-verified 2026-07-25:** LCSC/JLC **C19110**, Samsung
  Electro-Mechanics, 2.2 µF, 25 V, X7R, ±10 %, **0805**, MSL 1. JLCPCB library type **Extended**.
  (Because it is DNP, library class and JLC stock are **not** gates for this build; the part is
  named so the DNP CSV and the commissioning kit reference a real component.)
- **Land:** `C_0805_2012Metric` pads 1.45 × 1.00 mm at x = ±0.95, courtyard 3.49 × 2.05 mm
  (measured on placed C16). Samsung CL21 0805 body 2.00 ± 0.20 × 1.25 ± 0.20, terminal band
  0.50 ± 0.25. Pad centre span 1.90 mm vs terminal centres ±0.75 mm → 0.20 mm outboard,
  giving toe fillet; pad width 1.00 vs body 1.25 max → IPC nominal-density land. **PASS.**
  Land class already reviewed as **FR-6** (0805 passives); this is a regression confirmation.
- **Voltage:** 3.3 V working on a 25 V part → 7.6× derating; DC-bias loss at 3.3 V/25 V ≈ 5 %.
- **Value derivation — why 2.2 µF and not 1 µF.** With the series diode fitted, LED conduction
  starts at `v_field < Vw − Vf(LED) − Vf(Dser)` = 5 − 1.15 − 0.90 = **2.95 V**. For a 24 VAC sine
  (`V_pk` = 33.94 V): `sin θ = 2.95/33.94 = 0.0869` → conduction 189.96°, **off-window
  t_off = 7.87 ms** (7.90 ms including the low-`IF` skirt where `IC` < 56 µA — the sine's slope at
  the crossing makes this insensitive). Hold-low requirement, starting from `V_CE(sat)` ≈ 0.15 V
  and needing `V(t_off) ≤ V_IL(MCP) = 0.2 × 3.3 = 0.66 V`:

  ```
  3.3 − 3.15·e^(−t/τ) ≤ 0.66   →   t/τ ≤ 0.1766   →   τ ≥ 7.90 ms / 0.1766 = 44.7 ms
  C ≥ 44.7 ms / 47 kΩ = 951 nF   (this is a MINIMUM-EFFECTIVE-capacitance requirement)
  ```

  A nominal 1 µF part does **not** meet it at worst case: 1.0 × 0.90 (tol) × 0.85 (X7R over
  −55…+125 °C) × 0.98 (DC bias) = **749 nF < 951 nF — FAIL.** 2.2 µF: 2.2 × 0.90 × 0.85 × 0.95 =
  **1.65 µF → τ = 77.6 ms → V(7.90 ms) = 0.455 V < 0.66 V. PASS with 0.205 V of headroom.**
  *(A 1 µF 50 V X7R part — Samsung CL21B105KBFNNNE, LCSC **C28323**, JLCPCB **Basic**, LCSC
  stock > 4 M — was fetch-verified and **rejected** on the arithmetic above. Recorded so nobody
  re-proposes it.)*
- **Timing cost, stated so it is never a surprise** (at the +10 % tolerance extreme, C = 2.42 µF,
  τ = 113.7 ms):
  - **Assert** (line pulled low): `t = C·ΔV/I_C` = 2.42 µF × 2.64 V / 0.92 mA = **6.9 ms**, plus
    up to 8.3 ms of AC phase → **≤ 15.2 ms**.
  - **De-assert** (release to `V_IH` = 0.8 × 3.3 = 2.64 V): `τ · ln(3.3/0.66)` = **183 ms**.
    Plus the daemon's debounce: **+60 ms** on diagnostics inputs (`N=3`), **+20 ms** on FSM action
    inputs (`N=1`) → total release detection **203–243 ms**.
  - **Acceptability, per affected channel class:** PBZ is DC 33 V, **not AC — the cap is never
    fitted there**, so `_pbz_release_required`'s fresh-edge rule is untouched. BS is a level.
    FOUL events are > 100 ms and seconds apart. MAN_* are mechanic-session levels. **No FSM or
    safety timing is bounded tighter than 200 ms on any slow channel.** If a future channel is,
    this cap must not be fitted on it.

### FR-18 — TORCH **C0805B103K500NT** 10 nF 50 V X7R ±10 % 0805 (LCSC **C17702767**) vs `Capacitor_SMD:C_0805_2012Metric` — **PASS (DNP)**

*Fast-channel (RP2040) de-glitch cap. **Already a locked part on this board** (the DNP contact
snubbers `Csnub_*`). Zero new part class.*

- Same land as FR-17; land already reviewed at FR-6. Regression only. **PASS.**
- **Value derivation — the 1 ms edge budget is the binding constraint.** RP2040 `V_IH(min)` =
  0.65 × IOVDD = 2.145 V. Rise through the 47 kΩ pull-up:
  `t = 47k · C · ln(3.3 / (3.3 − 2.145)) = 47k · C · 1.0498 = 49.3k · C`.
  For `t ≤ 1 ms` → **C ≤ 20.3 nF**. **10 nF gives t = 0.49 ms** — half the budget, and also below
  `DEBOUNCE_CAM_US` = 2000 µs, so it cannot change debounce behaviour.
  **HARD RULE: never fit more than 22 nF on GP6–GP13.**

### B.4 The fast-channel AC problem the cap does NOT solve — flagged, not hidden

**This is the most important finding in §B and it must not be lost.**

The four cam channels most likely to carry 24 VAC — **SA, SB, TA1, TA2** — are **RP2040 fast
channels** (`FAST_INPUTS`, Pico pins 9/10/12/14 = **GP6, GP7, GP9, GP10**; SC/TB/DIELL_L/DIELL_R
complete GP6–GP13). The AC-integration answer is therefore **unavailable to exactly the channels
that need it**:

- Integrating 60 Hz needs `C ≥ 951 nF` → 183 ms de-assert. That is **183× the 1 ms edge budget**,
  **92× `DEBOUNCE_CAM_US`**, and **122 % of `CAM_*_GRACE_MS` = 150 ms**. Rejected.
- **And a bare (or 10 nF) AC cam channel trips the firmware chatter guard.** A 60 Hz pulse train
  produces **120 debounced edges/s = 12 edges per `CHATTER_WINDOW_MS` = 100 ms**, against
  **`CHATTER_MAX_CAM` = 8**. Both half-cycles (7.9 ms off / 8.7 ms on) comfortably exceed
  `DEBOUNCE_CAM_US` = 2 ms, so every edge passes debounce. **A cam channel on sustained 24 VAC
  faults continuously.** *(DIELL is not exposed: `CHATTER_MAX_DIELL` = 30 > 12 — but DIELL is
  measured DC anyway.)*

**Therefore:** r6 hardware makes an AC cam channel **electrically survivable** (LED reverse
0.35 V, no rail backfeed, no avalanche) but **not functionally usable**. Closing it requires one
of, in preference order, and **none of them is in scope for this campaign — firmware is NOT
touched and NOT flashed:**

1. **Firmware pulse-train presence detection** on GP6–GP13 (treat "≥ N edges within a 100 ms
   window" as *asserted*, not as chatter). Correct answer; needs a firmware change + bench sign-off.
2. **Raise `DEBOUNCE_CAM_US` above 8.7 ms and `CHATTER_MAX_CAM` above 12** — cheaper, but 8.7 ms
   of added latency against a 150 ms grace, and it degrades genuine-chatter detection.
3. **Tap the cams at the switches** and skip C2A for those four channels — the fallback already
   recorded in `docs/phase8_metering_guide_harness_unknowns.md`.

**Gate to add:** at the powered characterization session, for each of SA/SB/SC/TA1/TA2/TB,
record **DC or AC, RMS/peak, and frequency**. That single measurement selects between (1)/(2)/(3)
and is the only thing that decides it.

### B.5 Summary of new part classes

| Class | New to the board? | LCSC | JLC class | Populated qty/board |
|---|---|---|---|---|
| 1N4148WS / SOD-323 | **NO** — existing line, qty 8 → 88 | C118873 | Extended (already paid) | 80 |
| 2.2 µF 25 V X7R 0805 | Yes — **DNP only**, never JLC-assembled | C19110 | Extended | 0 |
| 10 nF 50 V X7R 0805 | **NO** — existing `Csnub_*` line | C17702767 | Extended | 0 |

**Net: zero new JLC-assembled part classes. `EXPECTED_JLC_LINES` stays 27.**
Added BOM cost ≈ **$0.62/board** (80 × $0.0077) + 80 placements.

---

## C. `Rin` decision — **KEEP 2k2**

### C.1 The arithmetic

Constants: `Vf(LED)` = 1.15 V; MCP23017 `V_IL` = 0.2 × 3.3 = 0.66 V → required sink through the
47 kΩ pull-up = **(3.3 − 0.66)/47k = 56.17 µA**. (RP2040 `V_IL` = 0.35 × 3.3 = 1.155 V →
**45.6 µA**, so fast channels have ~23 % more margin than the table below.)

`Vf(Dser)` is taken at **worst-case maximum**, extrapolated from the datasheet's only guaranteed
point (1.0 V @ 10 mA) with ideality n = 1.9: `Vf(I) = 1.0 − 1.9·V_T·ln(10 mA / I)`. This is
deliberately pessimistic — the round-5 audit's 0.60 V is the *typical* value, and both are shown.

PC817B CTR = 130–260 % at `I_F` = 5 mA; the low-current derate factor is taken from the
normalized CTR-vs-`I_F` curve at the conservative edge of the band.

**`Rin` = 2k2 (recommended), across the `Vw` range:**

| `Vw` | `Vf(Dser)` | `I_F` | CTR derate | CTR worst | `I_C` | **Margin vs 56.17 µA** |
|---|---|---|---|---|---|---|
| 11.0 V (rev-C float) | 0.956 V | 4.043 mA | ×0.90 | 117 % | 4.73 mA | **84×** |
| 6.0 V (TP4 gate ceiling) | 0.916 V | 1.788 mA | ×0.58 | 75.4 % | 1.348 mA | **24.0×** |
| **5.0 V (rev-D nominal)** | **0.901 V** | **1.340 mA** | **×0.53** | **68.9 %** | **0.923 mA** | **16.4×** |
| 4.0 V (pessimistic) | 0.881 V | 0.895 mA | ×0.47 | 61.1 % | 0.547 mA | **9.7×** |
| 2.5 V (supply failure) | 0.82 V | 0.241 mA | ×0.30 | 39 % | 0.094 mA | 1.7× — **floor** |

*(At the audit's typical `Vf` = 0.60 V and `Vw` = 5 V: `I_F` = 1.477 mA, `I_C` = 1.056 mA,
**18.8×** — matching the audit's "18×". The worst-case column above says **16.4×**; I quote
**17.1×** as the headline where a single number is needed, being the `Vf` = 0.907 V / iterated
solution. All three agree to within 15 %; the conclusion is insensitive.)*

**`Rin` = 1k8 (the alternative), same method:**

| `Vw` | `I_F` | CTR worst | `I_C` | Margin |
|---|---|---|---|---|
| 11.0 V | 4.939 mA | 122 % | 6.03 mA | 107× |
| 6.0 V | 2.181 mA | 80.6 % | 1.758 mA | 31.3× |
| **5.0 V** | **1.633 mA** | **73.5 %** | **1.200 mA** | **21.4×** |
| 4.0 V | 1.088 mA | 63.7 % | 0.693 mA | 12.3× |
| 2.5 V | — | — | — | floor ≈ 2.3 V |

Baseline for reference (no diode, 2k2, `Vw` = 5 V): `I_F` = 1.750 mA, `I_C` = 1.251 mA, **22.3×**.

### C.2 The recommendation and why

**KEEP `Rin` = 2k2.** Five reasons, in decreasing weight:

1. **16.4× worst-case margin at the design point is not scarce.** The board shipped its rev-C
   design intent at **4.7×** and that was considered acceptable; the 47 kΩ pull-up bought 22×.
   1k8 buys 21.4× instead of 16.4× — **5 points of margin on a quantity that already has 16.**
2. ~~**1k8 changes the VALUE of 40 existing parts.**~~ **RETRACTED 2026-07-25 (r6 review) —
   this reason rested on a false baseline.** It claimed `diff_netlist_revC_to_revD.py` reports
   *"sole CHANGED_PART = D_PROT SS14→SS34"* and that retuning `Rin` would convert a one-line
   exception into a 41-line review surface. The gate actually emits **38** `CHANGED_PART` lines
   — and 32 of them are `Rpu_*` 10k→47k retunes **exactly analogous** to the `Rin` retune being
   rejected. See the correction under §J. **Do not cite this reason.** The KEEP-2k2 decision
   stands on reasons 1, 3, 4 and 5, and §F.1's correction strengthens reason 3.
3. **2k2 lowers rail load; 1k8 raises it — and after §F.1's correction this is the *heaviest*
   remaining reason, not the third.** 58.1 mA vs 69.9 mA at `Vw` = 5 V (worst-case `Vf`).
   `Vw` is the least-controlled quantity in the front end and the TMA-0505S is **unregulated**, so
   lower load ⇒ better load regulation ⇒ `Vw` sits higher ⇒ `I_F` recovers. **2k2 is
   self-stabilising; 1k8 fights itself.** At `Vw` = 6 V, 1k8 draws 92.7 mA = 46 % of rating.
4. **The `Vw` floor barely moves.** 2k2 runs out at `Vw` ≈ 2.5 V, 1k8 at ≈ 2.3 V. A rail collapse
   to 2.5 V is a supply failure (TP4 gate is ≤ 6 V unloaded, 5 V nominal), not a design margin.
5. **The clamp removes the reason `Vw` was ever a protection variable.** The round-5 audit's
   perverse coupling — *"lowering `Vw` improves LED-drive predictability and worsens reverse
   stress volt-for-volt"* — **is gone after r6**: LED reverse is pinned at ≈ 0.35 V by the clamp
   regardless of `Vw`. Lowering `Vw` now costs only drive. That decouples the TP4 gate from the
   input front end permanently, and it is a real design-quality improvement, not just a wash.

**Documented contingency (do not pre-emptively spend copper on it):** if the powered
characterization session measures `Vw` **< 4.2 V** under full 40-channel load, `Rin` → 1k8 is a
**value-only BOM change on an unchanged 0805 land**. No copper, no re-route, no re-spin. Record
it as an open BOM lever in the run log and the first-article pack; execute it only on data.

---

## D. Placement strategy

### D.0 The briefing's premise was wrong, and the correction is the good news

The task briefing (inherited from round-5 audit §5.5(b)) states the new parts *"must go in the
FIELD band free x-range (~x 16–56)… they land directly on the 40 field-sense traces and force a
re-route of a board where full-board FreeRouting was REJECTED at 473–625 DRC violations."*

**Measured, this is not where they go.** A full-board courtyard sweep in KiCad 10.0.2 shows a
**13.17 mm-wide, 240 mm-tall corridor between `Rin`'s courtyard right edge (x = 59.725) and the
opto column's left edge (x = 72.895)** that contains **exactly two components on the whole board**
(the item-A wet-bleed pair, R122/R123, at row 1) and whose only copper is **the two nets per row
that the new parts are being inserted into**. A track sweep of x 59.5–73.2 returns 193 segments:
124 `FIELD_LED_*`, 58 `FIELD_FAST/SLOW_*`, and 11 `FIELD_WET_V`/`FIELD_GND` segments confined to
y < 20 (the row 0/1 supply feeds).

The x 16–56 band is the *bad* place — that is where the 40 B.Cu channel columns run at
**1.05 mm pitch**. Nothing goes there.

**Consequences:** `BOARD_H` **stays 240 mm**. `BOARD_W` stays 250 mm. `INPUT_PITCH` stays
5.70 mm. `INPUT_COL_Y0`, `OPTO_X`, `RIN_X`, `RPU_X` all unchanged. The 0.02 mm opto-row slack is
**never touched** — no new part occupies any row's vertical space in the opto column's x-range.

### D.1 The corridor partitions into three lanes

For every row `i`, with `y = row_y(i) = 13.0 + 5.7·i`:

| Lane | x extent | Occupant | Courtyard |
|---|---|---|---|
| `Rin` column | 56.275 – 59.725 | `Rin_<n>` (existing) | 3.45 × 1.99 |
| **Lane S (series)** | **60.355 – 63.645** | **`Dser_<n>` @ x = 62.0, rot 180** | 3.29 × 1.99 |
| Lane M (free) | 63.645 – 69.005 | *nothing* (5.36 mm routing channel; holds R122/R123 at row 1) | — |
| **Lane C (clamp)** | **69.005 – 70.995** | **`Dclamp_<n>` @ x = 70.0, rot 270** | 1.99 × 3.29 |
| jog lane | 70.995 – 72.895 | existing x = 71.2 return jog | — |
| opto column | 72.895 – 82.715 | `OPTO_<n>` (existing, untouched) | 9.82 × 5.68 |

### D.2 Exact placement constants — add to `base_placement()` in `place_components_revD.py`

```python
DSER_X   = 62.0    # FIELD series-block lane
DCLAMP_X = 70.0    # FIELD anti-parallel-clamp lane
CFLT_X   = 86.0    # LOGIC filter-cap column (shares RPU_X)

for i, name in enumerate(input_order):
    y = INPUT_COL_Y0 + i * INPUT_PITCH
    p[f"OPTO_{name}"]   = (OPTO_X, y, 0)          # unchanged
    p[f"Rin_{name}"]    = (RIN_X,  y - 1.8, 0)    # unchanged
    p[f"Rpu_{name}"]    = (RPU_X,  y + 1.8, 0)    # unchanged
    # --- r6 additions ---
    p[f"Dser_{name}"]   = (DSER_X,   y - 1.8, 180)   # rot 180: pin2 (A) west toward Rin
    p[f"Dclamp_{name}"] = (DCLAMP_X, y + 1.49, 270)  # rot 270: pin1 (K) north at FIELD_LED
    p[f"Cflt_{name}"]   = (CFLT_X,   y + 4.60, 180)  # pin1 (logic) east at 86.912
```

**Two documented exceptions, and only two:**

```python
# EXCEPTION 1 — row 1 (SB): the item-A wet-bleed pair R122/R123 occupy
# x 62.005-63.995 / 66.005-67.995, y 14.275-17.725, which is Lane S at this row.
# R122/R123 are FROZEN rev-D item-A copper; SB's series diode moves in y instead.
p["Dser_SB"] = (DSER_X, 19.95, 180)
#   courtyard y 18.955-20.945: 1.230 mm clear of R122's bottom (17.725),
#   0.660 mm clear of row-2 (SC) Dser's top (21.605). No x overlap with Lane C.

# EXCEPTION 2 — row 39 (AUX11): y+4.60 = 239.90 puts the cap courtyard off the
# 240 mm board edge. Move it east of Rpu instead.
p["Cflt_AUX11"] = (90.0, 237.10, 180)
#   courtyard x 88.255-91.745, y 236.075-238.125: 0.530 mm from Rpu_AUX11's
#   right edge (87.725), 1.875 mm from the board edge, clear of TP9 (x >= 98.705).
```

### D.3 Clearance verification (computed, to be re-confirmed by DRC)

| Pair | Gap | Verdict |
|---|---|---|
| `Dser` (x 60.355–63.645) ↔ `Rin` (right 59.725) | **0.630 mm** | PASS (courtyards must not overlap) |
| `Dser` ↔ `Dclamp`, same row | 5.360 mm (x) | PASS |
| `Dser` ↔ `Dser`, adjacent rows | 3.710 mm (y) | PASS |
| `Dclamp` (y −0.155 … +3.135) ↔ next row's `Dclamp` (y +5.545) | 2.410 mm | PASS |
| `Dclamp` (right 70.995) ↔ opto (left 72.895) | 1.900 mm | PASS |
| `Dclamp` ↔ R123 (right 67.995), rows 0–2 | 1.010 mm (x) | PASS |
| `Dser_SB` ↔ R122 (bottom 17.725) | 1.230 mm | PASS |
| `Dser_SB` ↔ `Dser_SC` (top 21.605) | 0.660 mm | PASS |
| `Cflt` (y +3.575 … +5.625) ↔ same-row `Rpu` (bottom y +2.795) | 0.780 mm | PASS |
| `Cflt` ↔ next-row `Rpu` (top y +6.505) | 0.880 mm | PASS |
| `Cflt` (right 87.745) ↔ Pico courtyard (left 88.415), rows 0–8 | 0.670 mm | PASS |
| `Cflt` row 0 ↔ U45 TMA (bottom 7.175) | 9.430 mm | PASS |
| `Cflt_AUX10` (bottom 235.225) ↔ `Rpu_AUX11` (top 236.105) | 0.880 mm | PASS |
| Row 39 `Dclamp` (bottom 238.435) ↔ board edge 240 | 1.565 mm | PASS |
| **USB keep-out envelope (92.0, 0.0, 108.0, 7.5)** | no new part enters x 92–108 or y < 10.2 | **INTACT** |
| **FIELD/LOGIC gutter rule area (76.8–80.0, y 8–239)** | Lane S/C max x = 70.995; `Cflt` min x = 84.255 | **INTACT — no incursion** |
| **TP17–24 tap probe pads** (x 116–125, y 52–64, LOGIC band) | untouched | **INTACT** |
| TP1–TP16 strip (y 227.7–237.3, x 20.7–101.3) | `Cflt_AUX11` at x 88.255–91.745 vs TP1 (98.705) | 6.960 mm, PASS |

### D.4 The re-route — this is the cheap part

Per row, **exactly two nets change and one is unchanged in geometry**:

1. **`FIELD_RIN_<n>` (new).** `(58.913, y−1.8) → (60.95, y−1.8)`, F.Cu. **2.04 mm.**
   *(This is the west 2 mm of what used to be `FIELD_LED_<n>`.)*
2. **`FIELD_LED_<n>` (existing geometry, west end trimmed + one branch).**
   Main run becomes `(63.05, y−1.8) → (72.0, y−1.8) → (72.0, y) → (74.0, y)` — **identical to
   today's poly except the start x moves 58.913 → 63.05.**
   Add branch `(70.0, y−1.8) → (70.0, y+0.44)` to `Dclamp` pin 1. **2.24 mm.**
3. **`FIELD_FAST_<n>` / `FIELD_SLOW_<n>`: no geometry change required.** `Dclamp` pin 2 sits at
   `(70.0, y+2.54)`, which is **on the existing horizontal return run** for the 34 rows whose
   solved `vy = y+2.54`. The remaining 6 rows (SA `vy = y+0.0`; TA2, GS4 `vy = y+1.59`; GS1 and
   two others `vy = y+1.09`) need a stub of **≤ 1.50 mm**. Verified per row from the placed board.

**In `route_revD.py`, this is a ~2-line edit inside `route_field_led_series()`** plus a new
`route_field_rin()` of the same shape. **Delete the `name == "SB"` duck-under special case** in
`route_field_led_series()` — with the series diode inserted at `(62.0, 19.95)`, `FIELD_LED_SB`
no longer passes under R122/R123 and the duck-under becomes both unnecessary and wrong.
`route_field_input_returns()`, `route_opto_pullups()`, `route_field_power()`, and **every
LOGIC-, SAFETY-, and MACHINE-band routine are untouched.**

**Filter-cap routing:** `(86.912, y+1.8) → (86.912, y+4.60)` — 2.80 mm F.Cu on the logic net from
`Rpu` pin 2 to `Cflt` pin 1; `Cflt` pin 2 connects to the existing F.Cu `GND` zone (x 80.4–180.5)
by zone connection, exactly as the `Rpu` column already sits inside it. Row 39: `(86.912, 237.1)
→ (89.05, 237.1)`.

**Full-board FreeRouting is NOT invoked** and must not be. Routing stays deterministic and
scripted, per `scripts/route_revD.py`.

### D.5 New high-voltage exposure — the one genuinely new DRC consideration

**Before r6,** `FIELD_LED_<n>` could never exceed `Vw` (≈ 5–11 V): `Rin` and the rail clamped it.
**After r6,** with the series diode blocking, `FIELD_LED_<n>` follows the field pin:

- PBZ at +33 VDC → node at **+32.65 V**.
- A 24 VAC channel → node swings **+33.6 V … −32.8 V** (on the forward half-cycle the node sits
  one LED drop above the field pin).

This extends the **≤ 34 Vpk design basis already declared in `kicad/revD/wsl-phase8b-revD.kicad_dru`**
from the connector / opto-pad-2 region into the corridor. IPC-2221B Table 6-1 col B1 (external,
uncoated) for the 31–50 V band requires **0.6 mm**; the `Field_Sense` netclass clearance is
**0.40 mm**.

**Do NOT raise the global `Field_Sense` clearance.** The 40 B.Cu channel columns run at 1.05 mm
pitch with 0.70 mm vias; the router's own via-separation heuristics (`abs(vy − v) < 0.95`,
`dist < 1.15`) were solved against 0.40 mm and a global change would force a re-solve of the
one part of this board that was hand-won after autorouting failed at 473–625 violations. That is
precisely the "DRC-clean-but-wrong" risk the round-5 audit warned about.

**Instead, add a narrow fail-closed gate** to `kicad/revD/wsl-phase8b-revD.kicad_dru`:

```
# r6: FIELD_LED_* can sit at up to +33.6 / -32.8 V once the series block is
# fitted (was bounded by Vw before r6). IPC-2221B B1, 31-50 V band -> 0.6 mm.
# This is a GATE, not a routing constraint.
(rule "FIELD_LED high-voltage node spacing (r6)"
    (condition "A.NetName == 'FIELD_LED_SA' || ... || B.NetName == 'FIELD_LED_AUX11'")
    (constraint clearance (min 0.6mm)))
```

**Result: 0 violations. AS-BUILT MINIMUM = 0.910 mm = 1.52× the requirement.**

> **CORRECTED 2026-07-25 (r6 review).** This section previously stated *"the measured minimum
> after the r6 re-route is 1.06 mm"* and *"0 violations, minimum 1.06 mm = 1.77× the
> requirement"*, and described the worst case as track-to-track (row *i*'s `FIELD_LED` run at
> `y−1.8` vs row *i−1*'s field-return run at `y−3.16`). **Both were wrong.** Bracketed with
> `kicad-cli pcb drc` by raising **only this rule's** constraint:
>
> | rule min | violations |
> |---|---|
> | 0.90 mm | **0** |
> | 0.95 mm | 117 (report names `actual 0.9100 mm`) |
> | 1.00 mm | 148 |
> | 1.10 mm | 196 |
>
> The binding pair is an **r6-introduced clamp pad against the next row's `FIELD_LED` track**:
> `Pad 2 [FIELD_SLOW_GS2] of D37 @ (70.0, 66.84)` vs `Track [FIELD_LED_GS3] @ (70.0, 68.20)`.
> The 0.6 mm gate still passes **0/0/0** — this is not stop-ship — but a reviewer sizing
> headroom on a node that now swings +33.6/−32.8 V was being given a margin **16 % larger than
> reality, against geometry that was never the constraint.** Re-bracket after any corridor change.

*(KiCad 10.0.2's DRU grammar has **no** `startsWith` operator — verified. Worse, a condition it
cannot evaluate does not merely disable its own rule: it takes the **whole** `.kicad_dru` down
during zone filling, so the filler falls back to bare netclass clearance and the LOGIC↔MACHINE
creepage contract stops being enforced (observed: +214 mm² of GND fill, 8 creepage violations at
the K1–K7 pads). The 40 net names are therefore **enumerated**, and the condition string must be
**one line** — a quoted expression broken across lines parses but evaluates as never-true, i.e.
it looks like a pass. Positive control after any edit: at `(min 2.0mm)` this rule MUST report
violations; at 0.6 mm it must report none.)*

#### D.5.1 KNOWN GAP — the field-pin nets sit at the same potential and are NOT covered

The clamp holds `FIELD_LED_<n>` within ≈ 0.35 V of its field-pin net (`FIELD_FAST_<n>` /
`FIELD_SLOW_<n>`). Those nets therefore carry the **same** voltage, but they are governed by the
0.40 mm `Field_Sense` netclass clearance, not by the 0.6 mm rule above. Measured field-pin ↔
field-pin minima (via-to-via, 0.70 mm pads, computed from raw `.kicad_pcb` geometry):

| Gap | Pair |
|---|---|
| **0.4807 mm** | `FIELD_SLOW_MAN_T` (38.25, 158.04) ↔ `FIELD_SLOW_TENTH` (37.2, 157.5) |
| 0.5297 mm | `FIELD_SLOW_GS6` (25.65, 89.64) ↔ `FIELD_SLOW_GS5` (24.6, 89.0) |
| 0.6895 mm | `FIELD_SLOW_AUX6` (47.70, 215.0) ↔ `FIELD_SLOW_AUX7` (48.75, 214.09) |

Two adjacent field-pin nets can sit ~68 Vpk apart if both are populated on the 24 VAC option
(one at +33.9, one at −33.9). IPC-2221B B1 asks **0.6 mm** for both the 31–50 V and 51–100 V
bands, and the `.kicad_dru` header's +0.15 mm etch allowance is not applied to the 0.40 mm
netclass either — so worst as-etched spacing is ≈ 0.29–0.37 mm.

**Why r6 does not fix it:** the geometry is **pre-existing** — the field-pin nets always ran to
the connector at machine potential; r6 moved only the return dogleg (71.2 → 68.5) and the bleed
tee, neither of which touches these pairs. Closing it means re-routing the hand-won 1.05 mm-pitch
B.Cu channel columns, which §D.5 above forbids in this spin. **It is carried as an OPEN
fleet-revision item (§K.7), recorded in the `.kicad_dru` header and the readiness checklist —
not silently left looking like it meets 0.6 mm.** The failure mode it guards is oil-mist /
lane-dust / condensation tracking between adjacent field channels at the connector-side via
field, which is exactly what the header's 4×/5× headroom philosophy exists to prevent.

Also confirmed clear at the new voltages: `FIELD_LED_<n>` (min x 63.05) to nearest `FIELD_WET_V`
copper (`Rin` pin 1 at 57.087) = **5.96 mm**; to the `FIELD_GND` via at (65, 14.1) = **2.90 mm**;
`Dser` pad-to-pad = **1.50 mm** at 27.7 V (16–30 V band needs 0.25 mm) → **6×**.

---

## E. Netclass + audit delta

### E.1 Netclass counts

`FIELD_RIN_*` matches the existing `net_name.startswith("FIELD_")` rule at
`apply_netclasses_revD.py:126`. **`classify_net()` requires NO change.**

| Class | Before | After | Δ | Why |
|---|---|---|---|---|
| Logic_Signal | 103 | **103** | 0 | `Cflt` joins existing `FAST_*`/`SLOW_*` nets; no new logic net |
| Logic_Power | 4 | **4** | 0 | `Cflt` pin 2 joins `GND` |
| **Safety_Rail** | **13** | **13** | **0** | **r6 adds ZERO safety copper. STOP-SHIP if this moves.** |
| Field_Sense | 82 | **122** | **+40** | 40 × `FIELD_RIN_<n>` |
| Machine_Output | 21 | **21** | 0 | untouched |
| **Total** | **223** | **263** | +40 | |

### E.2 Exact assert updates

**`scripts/apply_netclasses_revD.py`** — one line:
```python
EXPECTED_COUNTS = {
    "Logic_Signal": 103,
    "Logic_Power": 4,
    "Safety_Rail": 13,
    "Field_Sense": 122,   # r6: 82 + 40 x FIELD_RIN_<n> (input-protection series node)
    "Machine_Output": 21,
}
```

**`scripts/audit_revD_board.py`** — three lines:
```python
EXPECTED = {"Logic_Signal": 103, "Logic_Power": 4, "Safety_Rail": 13,
            "Field_Sense": 122, "Machine_Output": 21}       # was Field_Sense 82
EXPECTED_NETS = 263                                          # was 223 (+40 FIELD_RIN_*)
EXPECTED_PARTS = 391                                         # was 271 (+40 Dser, +40 Dclamp, +40 Cflt)
# UNCHANGED — assert these did NOT move:
#   line 152-153  Safety_Rail == 13 stop-ship guard          <- must still pass
#   EXPECTED_OPTO_PULLUPS = {R4, R6, ... R82}                <- no new R-prefix parts
#   EXPECTED_TESTPADS = 24, EXPECTED_MOUNTING = 4
```

**`scripts/export_fab_revD.py`** — five pinned counts (normative population, §A.4):
```python
EXPECTED_NETLIST_PARTS = 391   # was 271
EXPECTED_DNP           = 68    # was 28  (28 + 40 Cflt; Dser/Dclamp are POPULATED)
EXPECTED_PLACED        = 323   # was 243 (391 - 68)
EXPECTED_HAND_SOLDER   = 17    # UNCHANGED
EXPECTED_JLC_PLACED    = 306   # was 226 (323 - 17)
EXPECTED_JLC_LINES     = 27    # UNCHANGED - the 80 diodes join the existing 1N4148 line
```
Plus one DNP-reason branch in the DNP CSV writer (`~line 790`):
```python
elif p["tag"].startswith("Cflt_"):
    reason = ("DNP by design (r6): logic-side AC-integration / de-glitch cap. Fit ONLY on a "
              "channel MEASURED to carry a 60 Hz pulse train. 2.2uF max on MCP channels "
              "(183 ms de-assert); NEVER exceed 22 nF on the RP2040 fast channels GP6-GP13 "
              "(1 ms edge budget). See phase8_revD_r6_input_protection_spec_2026-07-25.md B.4.")
```
No `PART_LOCK` change: `("1N4148", "D_SOD-323")` already exists, and DNP refs never reach
`locked_part()` (only `jlc_refs` do — `export_fab_revD.py:806-810`).

**`scripts/generate_kicad_netlist_revD.py`** — ERC waiver constants **UNCHANGED**:
`ERC_EXPECTED_ERRORS = 1`, `ERC_EXPECTED_WARNINGS = 39`. All 39 existing warnings are
"Unconnected pin" on existing parts; every new part has both pins connected, so it emits none.
**If the warning count moves, something is mis-wired — fail closed, do not re-baseline.**

### E.3 Refdes stability — assert it

New parts **must** be instantiated in a dedicated `block_input_protection()` called from `main()`
**after** `block_j16_protection_and_revid()`, not inside `opto_input()`. `opto_input()` creates
`FIELD_RIN_<n>` and `FIELD_LED_<n>` and connects `Rin` pin 2 / `OPTO` pin 1; the later block
inserts `Dser`/`Dclamp`/`Cflt`. This guarantees:

- `D18–D97` (80 new), `C17–C56` (40 new). **`D1–D17` and `C1–C16` unchanged.**
- **Zero `R`-prefix additions** → `R1–R145` unchanged →
  `EXPECTED_OPTO_PULLUPS = {R4…R82 even}` still holds, and the manual's designator tables
  (`docs/manual_src/01,09,10,13,20,22,23`) stay correct.
- `place_components_revD.py` and `export_fab_revD.py` map by **SKiDL tag**, not refdes, so both
  are insensitive either way — but the audit and the manual are not.

**Add a regression assert** to `audit_revD_board.py`:
```python
need(max(int(r[1:]) for r in comp_info if r.startswith("D") and not r.startswith("DNP")) == 97
     and {f"D{n}" for n in range(1, 18)} <= set(comp_info),
     "r6 refdes stability: existing D1-D17 preserved, new diodes are D18-D97")
```

---

## F. Budgets

### F.1 `FIELD_WET_V` load (TMA-0505S: 1 W / 5 V / **200 mA**)

All 40 channels closed + the 1.1 kΩ item-A bleed (`Vw/1100`):

| Configuration | `I_F`/ch | 40 channels | Bleed | **Total** | % of 200 mA |
|---|---|---|---|---|---|
| **Today** (2k2, no diode, `Vw` = 5) | 1.750 mA | 70.0 mA | 4.55 mA | **74.5 mA** | 37.3 % |
| **r6** (2k2 + diode, `Vw` = 5, typ `Vf` 0.60) | 1.477 mA | 59.1 mA | 4.55 mA | **63.7 mA** | **31.8 %** |
| **r6** (2k2 + diode, `Vw` = 5, worst `Vf` 0.90) | 1.340 mA | 53.6 mA | 4.55 mA | **58.1 mA** | **29.1 %** |
| r6 at `Vw` = 6 (TP4 ceiling) | 1.788 mA | 71.5 mA | 5.46 mA | 77.0 mA | 38.5 % |
| *(rejected)* 1k8 + diode, `Vw` = 5 | 1.633 mA | 65.3 mA | 4.55 mA | 69.9 mA | 34.9 % |
| *(rejected)* 1k8 + diode, `Vw` = 6 | 2.181 mA | 87.2 mA | 5.46 mA | 92.7 mA | 46.3 % |

**On DRY-CONTACT channels, r6 REDUCES the wetting-rail load by 11–16 mA (15–22 %).** Clamp
reverse leakage adds 40 × < 1 nA at 1.15 V — unmeasurable.

> ### ⚠️ CORRECTION 2026-07-25 (r6 review) — the table above is NOT a hard bound
>
> This section previously ended *"All 40 channels are never simultaneously closed in service…
> so the table is a hard bound, not an operating point."* **That is false, and the number that
> falsifies it is computed two sections down in this same spec.**
>
> Every row above models each channel at the **dry-contact** current (1.34 mA at `Vw` = 5 V).
> §F.3 computes, for a channel **driven** by 24 VAC, a negative-half-cycle
> `I_F,pk = (5 + 33.94 − 1.15 − 0.90)/2200 = **16.8 mA**` — sourced **out of `FIELD_WET_V`
> through `Rin`** — with a full-cycle average of **≈ 5.4 mA**. That is **12.5× the peak** and
> **4.0× the average** of the dry model, per channel.
>
> Three facts make this a real load case, not a corner:
>
> 1. **A driven channel draws whenever the machine is energised.** It is not a "contact closed"
>    coincidence, and cam-family channels share the machine's 24 VAC ladder, so they are **in
>    phase** — the peaks add.
> 2. **`FIELD_WET_V` has ZERO bulk capacitance.** Verified by parsing
>    `kicad/wsl-phase8b-revD.net`: the net has **43 nodes — 40 × `Rin` pin 1, `R122.1`, `R123.1`,
>    and `U45` pin 6 (TMA-0505S `+Vout`)**. No capacitor of any value. The unregulated converter
>    must deliver each 8.3 ms half-cycle peak instantaneously, with nothing to ride through on.
> 3. **The class cannot be known at stuffing time.** §A.5 puts 4–6 cam channels in the
>    likely-AC class and calls the 11 AUX spares "unknown by definition"; §A.4 reason 5 argues
>    uniform population *because* of that.
>
> **Coincidence arithmetic (the number to hold in your head):**
> `200 mA / 16.8 mA = **11.9 channels`* — at roughly **12 coincident driven channels** the 1 W
> converter is at its instantaneous rating with no output capacitor. On average current the
> headroom is larger (`200/5.4 ≈ 37`), but with no bulk cap the **peak** is what sags `Vw`.
>
> **The failure it produces is silent and total:** `Vw` collapses on every negative half-cycle
> and **all 40 inputs read inactive simultaneously, 120 times a second** — including the
> `SA`/`TA1` cam-confirmation channels the FSM uses to prove motion, and PBZ.
>
> **Driven-channel load table (the case §F.1 omitted):**
>
> | Driven 24 VAC channels | Peak rail draw (driven + 40-ch dry balance) | % of 200 mA |
> |---|---|---|
> | 0 | 58.1 mA | 29 % |
> | 4 (the §A.5 cam class) | 4 × 16.8 + 36 × 1.34 + 4.55 = **119.9 mA** | 60 % |
> | 6 | 6 × 16.8 + 34 × 1.34 + 4.55 = **150.9 mA** | 75 % |
> | **12** | 12 × 16.8 + 28 × 1.34 + 4.55 = **243.9 mA** | **122 % — OVER RATING** |
>
> **Disposition for r6 (no copper):** §B.4 already establishes that a cam channel on sustained
> 24 VAC is **electrically survivable but NOT functionally usable** without a firmware change —
> so no lane ships with driven AC cam channels this spin. The r6 hardware is therefore not
> exposed **provided that stays true**. What changes here is the *record*: the budget is no
> longer claimed as a hard bound, J10 no longer tests only the dry model (§J), and the
> **`FIELD_WET_V` bulk-capacitance decision is escalated as an OWNER DECISION for the fleet
> revision (§K.7)** — a bulk cap on the isolated field rail is new copper, a new part class and
> a new FR review, and it is not absorbed into the smallest-change discipline of this spin.
>
> **Measurement that closes it** (add to the powered characterization session, alongside the
> §B.4 AC/DC cam measurement): with the machine energised and every channel landed, record
> `Vw` at TP4 **on a scope, not a DMM** — peak-to-peak ripple and the loaded minimum, over at
> least ten 60 Hz cycles. A DMM average will hide exactly this failure.

### F.2 `D_PROT` (SS34) and the 5 V budget

`D_PROT` (D17, SS34, 40 V / **3 A**, LCSC C8678) sits on `VCC_5V_RAW → VCC_5V`, LOGIC domain. The
FIELD load reflects into it through the TMA's primary:

- Today: 74.5 mA × 5 V = 373 mW out; at 75–80 % efficiency ≈ **94–100 mA** on `VCC_5V`.
- r6: 63.7 mA × 5 V = 319 mW out ≈ **80–85 mA** on `VCC_5V`.
- **`D_PROT` headroom IMPROVES by ~15 mA.** Against a 3 A rating this is noise either way;
  recorded so the FR-3 / FR-15 budget chain stays closed.
- `Cflt` is DNP, contributes 0. Even if all 40 were fitted at 2.2 µF, the inrush is
  40 × 2.42 µF = 96.8 µF charged through 40 × 47 kΩ in parallel (1.175 kΩ) — τ = 114 ms,
  peak 2.8 mA. Irrelevant.

**No change to the FR-15 J16 polyfuse allowance, and no change to the SS34 lock.**

### F.3 The backfeed solve — confirmed closed by the series diode

**Without the series diode (clamp alone) — the failure mode this design must not ship:**
```
PBZ at 33 VDC, clamp fitted, no series block:
    (33 − 0.7 − Vw)/2200 = Vw/1100
    32.3 − Vw = 2·Vw    →    Vw = 10.77 V   at   I = 9.79 mA
```
One over-voltage channel drags the shared wetting rail from 5 V to 10.8 V **for all 40 channels**
and back-drives the unregulated TMA output to ~2× nominal.

**With the series diode fitted — the r6 topology:**

The only paths from a positive field pin into `FIELD_WET_V` are `Dser` reverse leakage and the
LED's own reverse leakage, both bounded by datasheet maxima:

| Quantity | Value | Source |
|---|---|---|
| `Dser` reverse leakage @ 28 V, 25 °C | ≤ **5 µA** (the 75 V guaranteed max; typ. nA at 28 V) | 1N4148WS datasheet |
| PC817 LED reverse leakage `I_R` @ 4 V | ≤ **10 µA** | PC817 datasheet |
| **Total clamp current per over-voltage channel** | **≤ 15 µA** | sum |
| Backfeed into the rail, 3 known-bad channels | 3 × 5 µA = **15 µA** | — |
| Rail lift = `I × 1100 Ω` | **0.017 V** | — |
| Absurd bound: all 40 channels over-voltage | 200 µA → **0.22 V** lift | — |

**Result: backfeed current 9.79 mA → ≤ 200 µA — a 49× reduction; rail lift 5.77 V → ≤ 0.22 V.
The series diode closes it.**

**LED reverse voltage, by construction:** the clamp's forward drop at 15 µA (1N4148 at 15 µA,
25 °C) ≈ **0.35 V**. Against the PC817 LED absolute-max `V_R` = 6 V that is **17× inside spec**.
At the 150 °C leakage extreme (`Dser` 50 µA + LED 10 µA = 60 µA) the clamp drops ≈ 0.42 V →
**14× inside**. **This is set by a specified V-I curve, not by a leakage ratio** — the exact gap
the round-5 audit's ADDITION #1 identified.

**`Dser` reverse stress:** `V_field − Vf(clamp) − Vw` = 33 − 0.35 − 5 = **27.65 V DC** (PBZ), or
33.94 − 0.35 − 5 = **28.59 Vpk** (24 VAC, 60 Hz repetitive). Against V_RRM 75 V → **2.6–2.7×**,
non-avalanching, well below breakdown. **PASS.**

**AC forward half-cycle:** `I_F,pk` = (5 + 33.94 − 1.15 − 0.90)/2200 = **16.8 mA**; full-cycle
average ≈ **5.4 mA**; `Dser` dissipation ≈ 0.9 V × 5.4 mA = **4.9 mW** (200 mW rating, **41×**);
PC817 LED dissipation ≈ 1.15 V × 5.4 mA = **6.2 mW** (70 mW rating, **11×**), `I_F` peak 16.8 mA
against 50 mA continuous / 1 A pulsed. **All PASS.**

### F.4 The FA measurement this replaces

Round-5 audit ADDITION #1 asked for a first-article measurement: *"with the machine driving 33 V,
the LED node must read < 1 V reverse."* **Keep it, and tighten it:** with r6 fitted the predicted
value is **0.35 V ± 0.1 V**, not "< 1 V". A reading above 1 V means the clamp is missing,
reversed, or open; a reading near 0 V with the channel dead means the clamp is shorted or
reversed-and-conducting. **Add to the first-article pack as gate FA-15.**

> **CORRECTED 2026-07-25 (r6 review): this gate was originally allocated `FA-10`, which is
> ALREADY TAKEN.** `docs/phase8_revD_first_article_pack.md:504` (mirrored at
> `scripts/generate_first_article_docs_revD.py:613`) defines *"FA-10 — MCV header mechanical
> (FR-9, first connector only)"*, and the sign-off table already carries a row *"FA-10 MCV
> insertion/solder fill"*. The pack runs FA-1 … FA-14; **the next free ID is FA-15**, and that
> is what this gate is. Implementing the old text literally would have overwritten the MCV
> insertion-force/solder-fill gate or created a duplicate FA-10.

**Why this gate is not optional — the two clamp failure modes are NOT symmetric.** §A.4 argues
both are "detectable at commissioning, never latent". That is true for a **reversed or shorted**
clamp (`Vf` 0.7 V shunts the 1.15 V LED → the channel reads dead → any GS-map/commissioning pass
catches it). It is **false for an OPEN or unplaced** clamp: a tombstoned 0.60 × 0.45 mm SOD-323,
a wrong reel, or an AOI miss on 80 new placements leaves the channel **fully functional in every
commissioning test**, while the PC817 LED sits at up to 27.7 V reverse against its 6 V
absolute-max `V_R` on PBZ and 10–15 V on DIELL_L/R. Protection silently degrades to the
leakage-ratio case §A.3.2 explicitly rejects, and the LED dies weeks later in service with no
diagnostic trail. **FA-15 is the single measurement that separates those two states.**

---

## G. Evaluate-and-recommend — TWO DYLAN DECISIONS

> ### ⚠️ DYLAN DECISION G-1 — DNP-only isolated RELAY_ENABLE_RAIL / TP16 state feedback
> ### ⚠️ DYLAN DECISION G-2 — per-motor current sensing
>
> **Neither is implemented by this spec. My recommendation is OUT for both, this spin.**

### G-1. Isolated rail-state feedback (DNP-only footprints) — **RECOMMEND OUT for r6**

**What it is.** Codex proposed DNP-only footprints for an isolated sense of `RELAY_ENABLE_RAIL` /
TP16 state, so the daemon could read whether the safety rail is actually up. Codex called it the
**highest-value remaining addition**, and on merit that is a defensible claim — I am not
disputing the value. My objection is **timing and gate integrity**, and I want that distinction on
the record.

**The argument that it is free — "a DNP-empty footprint loads nothing" — is true electrically and
false structurally.** Three concrete problems:

1. **It cannot be built without moving the Safety_Rail stop-ship guard, or without cheating it.**
   Any isolated sense stage needs a rail-side element (e.g. a second PC817 LED fed through a
   series resistor). The node between that resistor and the barrier is **a new net on the safety
   rail**. Under the existing classifier (`apply_netclasses_revD.py:117-122`), naming it
   `SAFE_FB_LED` puts it in `Safety_Rail` → count **13 → 14** → **automatic stop-ship**
   (`audit_revD_board.py:152-153`). The only way to keep 13 is to name the net *outside* the
   `SAFE_*` / `RAIL_GATE` / `COIL_LO_*` / `BASE_AND_*` patterns — i.e. **to deliberately
   misclassify a safety net to dodge the guard.** This project's own audit record says never do
   that, and I will not spec it.
2. **Moving the guard in this spin destroys its signal.** "rev-D adds zero safety copper" is the
   single brightest stop-ship line on the board. Changing it from 13 to 14 **in the same spin that
   adds 120 parts and re-routes 40 rows** means the one gate that exists to catch an unintended
   safety-copper change is itself changing. That is the worst possible week for it.
3. **X3 exists because a rail load was already deleted once.** Pads invite population. A DNP
   footprint on a safety rail is not like a DNP snubber across a relay contact (machine domain,
   already isolated) — it is an invitation to a future technician or agent to populate it *because
   the pads are there*, with a load on the rail whose current draw nobody has FMEA'd.

**And the marginal diagnostic yield is small, because the rail is already 80 % observed.** The
rev-D item-E tap stages (`R_TAPIN_555/KICK/ARM/RPOK` → `Q_TAP_*` → GP16–19, probe pads TP17–24)
give unidirectional observation of `NE555_OUT`, `WDOG_KICK`, `ARM_PERMIT` and `RP2040_OK` — **four
of the five inputs to the rail's AND topology.** Software already knows what it commanded and can
infer the expected rail state. The only unobserved element is `Q_RAIL`'s own pass-FET failure, and:

| | |
|---|---|
| **Detection today** without rail feedback | the machine does not move; caught by the FSM's cam-confirmation (`CAM_*_TRIP` / `CAM_*_GRACE_MS` = 150 ms) and the `MAX_MOTION_MS` = 8000 backstop |
| **Detection latency** | one commanded motion (≤ 1 cycle) |
| **What it actually costs you** | you cannot distinguish "rail down because commanded" from "rail down because `Q_RAIL` failed" without a meter |
| **Classification** | a **serviceability** gap, not a safety hole |
| **Already proven by measurement** | the rev-C bench campaign confirmed *all six rail conditions drop TP16 independently* |

**RECOMMENDATION: OUT for r6. Land it in the fleet revision, with the FMEA done first.**

**If Dylan overrules, the ONLY acceptable form is:**
- a fully isolated sense — a second PC817 fed from the rail through its own series resistor,
  never a divider, never a load path that can pull the rail;
- the rail-side net named **`SAFE_FB_<n>`** so it classifies honestly;
- `EXPECTED_COUNTS["Safety_Rail"]` and `EXPECTED["Safety_Rail"]` moved **13 → 14 explicitly and
  loudly**, in both files, each with a one-line rationale comment — **never by renaming to dodge
  the guard**;
- the populated-state rail load (current draw, and its effect on the `Q_RAIL` gate and the NE555
  timing) computed and written into the FMEA **before any board is populated**, not after;
- geometry: the corridor's Lane M (x 63.645–69.005) is FIELD domain and cannot host it; a
  rail-side part must live in the LOGIC/MACHINE bands under the 3.35 mm LOGIC↔MACHINE contract.
  **This is a real placement problem, unlike §D. Budget time for it.**

### G-2. Per-motor current sensing — **CONFIRM Codex. RECOMMEND OUT.**

**Codex's position — that it needs measured field data that does not exist — is CORRECT, and I
can add three independent reasons it is not even close.**

**(a) The design inputs genuinely do not exist.** To size a sensor you need: steady running
current, inrush peak, inrush duration, the leg's voltage class, and a stall/jam signature. **None
of the seven switched machine legs (S, T, SP, BE, M, M2, M1) has ever been metered under load** —
that is Stage 6b of the metering guide and the standing gate *"meter tapped-lead live voltages
BEFORE reconnecting the board"* is still OPEN. The at-machine fieldsheet records 24 VAC on the
relay **coil** side; whether each switched leg is the motor line or a contactor coil, and at what
voltage, **is unresolved in the repo.**

**(b) There is no ADC budget, and closing it adds an isolation-barrier class.** The RP2040's usable
ADCs are GP26/27/28; **GP26 is already taken by `ADC_VCC5_SENSE` (rev-D item D)**. Two free
channels for seven motors means a mux or an I²C ADC — a new IC class, a new I²C address, and
**MACHINE-domain sensing crossing into LOGIC**, i.e. **a new isolation-barrier component class**.
The FR discipline that killed the rev-B relays applies in full, and the 3.35 mm LOGIC↔MACHINE
creepage/clearance contract makes that expensive in area.

**(c) It does not fit, and unlike §D that statement is measured.** Seven current sensors plus
isolated front ends is a **machine-band redesign**, not a 3.29 mm corridor part. The machine band
(x ≥ 184.2) is fully occupied by K1–K7, their snubber/MOV networks, and J6–J12.

**(d) The dominant hazard is already covered without copper.** "Motor runs and does not stop" is
handled by `MAX_MOTION_MS` = 8000 in firmware (≈ 9 s measured on the bench) plus cam-based motion
confirmation (`CAM_SA_TRIP` / `CAM_TA1_TRIP`, 150 ms grace) plus the NE555 hardware rail drop.
Current sensing would add **stall/jam** detection — a **maintenance** signal, not a safety one.

**What measurement would unblock it** (all cheap additions to a session that must happen anyway):

1. At the powered characterization session, with the OEM 82-70 brain still driving, **clamp-meter
   each of the 7 switched legs**: voltage class (24 VAC / 120 VAC / DC), steady running current,
   inrush peak, inrush duration. Record per leg.
2. Capture a **jam/stall current** if one can be safely induced; otherwise take the OEM motor
   nameplate **FLA and LRA**.
3. Resolve the already-listed metering item: **does the 24 VAC ladder stay energised after the
   82-70 brain is removed?** (retained machine transformer, or removed logic?) This is on the
   list from round-5 audit §5.8.4 and it also gates the cam-channel population question in §B.4.

With (1)–(3) in hand, per-motor sensing becomes a normal design task for the fleet revision.
Without them, any sensor selection is a guess. **OUT for r6.**

---

## H. Naming and versioning

- **Board revision stays `D`.** rev-D has **never been fabricated**, so this is a copper
  *iteration* of rev-D, not rev-E. The title block keeps `Revision "D"`
  (`place_components_revD.py:250-254`) and `export_fab_revD.py --rev D` continues to assert it.
- **The `REV_ID0`/`REV_ID1` straps are UNCHANGED.** They encode the board revision the firmware
  reads; changing them without a firmware change would break the qualified-release board-identity
  gate, and **firmware is not touched this campaign.**
- **The fab package iteration goes to `r6`.** Existing series: `fab_revD_2026-07-21`,
  `_r2`, `_r3`, `fab_revD_2026-07-23_r4`, `fab_revD_2026-07-23_r5`.
  **New export directory: `kicad/fab_revD_2026-07-25_r6/` — NEW dated dir, refuse-if-exists**
  (`export_fab_revD.py:640` already enforces `if out.exists(): SystemExit`).
- `kicad/fab_revD_2026-07-23_r5/` becomes superseded-but-retained, exactly as r1–r4 are.
  **Do not delete it.**
- This spec's own filename is the r6 authority:
  `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md`.

---

## I. Implementation order and the gate chain

Run in this order. **Every step must pass before the next.**

1. `scripts/generate_kicad_netlist_revD.py` — add `FIELD_RIN_<n>` in `opto_input()`; add
   `block_input_protection()` **after** `block_j16_protection_and_revid()` in `main()`.
   → **Gate:** ERC waiver **1 error + 39 warnings, unchanged**; `part registry count: 391`.
2. `py -3 scripts/diff_netlist_revC_to_revD.py`
   → **Gate:** `RESULT CLEAN`, exit 0, and the `CHANGED_PART` set is **exactly the 38
   pre-existing whitelisted entries, unchanged by r6** (see the correction under J5);
   everything r6 adds is `ADDED_PART` (120) / `ADDED_NET` (40).
3. `place_components_revD.py` — add `DSER_X`/`DCLAMP_X`/`CFLT_X` and the two exceptions.
   → **Gate:** `BOARD_H == 240.0`, `BOARD_W == 250.0`, `INPUT_PITCH == 5.7` all unchanged;
   0 missing placements.
4. `apply_netclasses_revD.py --write` → **Gate:** exact counts 103/4/**13**/122/21 = 263;
   0 unknown, 0 overlap.
5. `route_revD.py --check-only`, then commit the route.
   → **Gate:** self-check **0 problems**.
6. KiCad DRC with the amended `.kicad_dru` (incl. the new FIELD_LED rule).
   → **Gate:** **0 errors / 0 warnings / 0 unconnected** — the standing 0/0/0 bar.
7. `audit_revD_board.py` (no `--pre-route`).
   → **Gate:** `Safety_Rail == 13` **STOP-SHIP guard passes**; 263 nets; 391 parts;
   `EXPECTED_OPTO_PULLUPS` unchanged; 24 test pads + 4 mounting holes.
8. `export_fab_revD.py --rev D --out kicad/fab_revD_2026-07-25_r6`
   → **Gate:** 391 / 68 DNP / 323 placed / 17 hand-solder / 306 JLC / 27 BOM lines;
   BOM↔CPL↔netlist equality; manifest + sha256.
9. `py -3 scripts/verify_revC_snapshot.py`
   → **Gate:** `189/189, failures 0, EXIT=0`. **Re-run after EVERY batch, not just at the end.**
   Also verify via the tracked `release_evidence/revC_design_snapshot_2026-07-19.zip` archive gate.
10. Regenerate `docs/phase8_revD_first_article_pack.md` **via
    `scripts/generate_first_article_docs_revD.py`**, never by hand-editing generated output.
11. Docs to update: `phase8_revD_change_list.md` (item #6 → **CLOSED IN COPPER, r6**),
    `phase8_revD_readiness_checklist.md` **G7** (retract "REQUIRES COPPER — deferred to the fleet
    revision"), `phase8_revD_run_log.md` (**FR-16/17/18** + the r6 batch record),
    `docs/manual_src/01,09,12,13,20,22,23` (1N4148WS qty 8 → 88; new `Dser_*`/`Dclamp_*` block in
    the channel-map chapter), `docs/phase8_revD_harness_bom.csv` (**REMOVE** the 1N4007 harness
    interposer for PBZ/DIELL_L/DIELL_R — r6 supersedes it on the board; keep the per-lane
    commissioning check as a *verification*, not a build step).

**Commits: EXPLICIT staging only — never `git add -A`. DO NOT PUSH.**
**Firmware NOT touched, NOT flashed.**

---

## J. Acceptance criteria — and what would make this spec WRONG

**Accept r6 only if all of these hold:**

| # | Criterion | Value |
|---|---|---|
| J1 | Safety_Rail netclass count | **exactly 13** |
| J2 | rev-C sacred snapshot | **189/189, failures 0, EXIT=0**, before and after every batch |
| J3 | DRC | **0 / 0 / 0**, including the new FIELD_LED 0.6 mm rule |
| J4 | ERC | **1 waived error + 39 warnings**, unchanged |
| J5 | `diff_netlist_revC_to_revD` | `RESULT CLEAN`, exit 0, and **exactly 38** `CHANGED_PART` lines — the pre-r6 set, unchanged (see correction below) |
| J6 | Refdes | `D1–D17`, `C1–C16`, `R1–R145` all unchanged; new = `D18–D97`, `C17–C56` |
| J7 | Board outline | 250 × 240 mm, `INPUT_PITCH` 5.7 mm, opto column untouched |
| J8 | Keep-outs | USB envelope, FIELD/LOGIC gutter, TP17–24 all intact |
| J9 | JLC BOM lines | **27** — no new assembled part class |
| J10 | Wetting-rail load, **dry-contact model** | ≤ 64 mA at `Vw` = 5 V (**down** from 74.5 mA) |
| **J10b** | Wetting-rail load, **driven-channel model** (NEW — J10 alone tests the wrong case) | `N × 16.8 mA + (40 − N) × 1.34 mA + 4.55 mA ≤ 200 mA`, i.e. **N ≤ 11 coincident driven 24 VAC channels**. Board ships with **N = 0** (§B.4: driven AC cam channels are not functionally usable without a firmware change). **Record N in the run log at commissioning; N ≥ 1 reopens §F.1.** |
| **J10c** | `FIELD_WET_V` bulk capacitance | **ZERO by construction** — 43 nodes, no capacitor (verified). Any future driven channel must re-open the §K.7 owner decision *before* it is landed. |

> **CORRECTION 2026-07-25 (r6 review) — J5's original wording was factually false and
> unachievable, and it was load-bearing.** J5 and step I.2 previously required *"the sole
> `CHANGED_PART` is still `D_PROT SS14→SS34`"*. Running `py -3 scripts/diff_netlist_revC_to_revD.py`
> emits **38** `CHANGED_PART` lines: `D_PROT`, five MCV connector footprint changes (`J_FAST`,
> `J_LAMP`, `J_SAFE`, `J_SLOWA`, `J_SLOWB`), and **32** `Rpu_*` 10k→47k. `git show HEAD` of
> `kicad/revD/netlist_diff_revC_to_revD.txt` shows the same 38 **before** r6 — so this was never
> true, and it is not an r6 regression. The script is self-consistent (all three classes are
> whitelisted; `RESULT CLEAN`, exit 0); the defect was in the spec.
>
> **It matters beyond bookkeeping.** §C.2 reason 2 rejects retuning `Rin` to 1k8 because it would
> add *"40 more CHANGED_PARTs … converting a one-line whitelisted exception into a 41-line review
> surface"* and concludes *"diff-gate legibility is the scarce resource this week."* The surface
> was **already 38 lines including 32 `Rpu_*` retunes exactly analogous to the 40 `Rin` retunes
> being rejected** — so the second-heaviest reason for KEEP 2k2 rested on a false baseline.
> **The KEEP-2k2 decision still stands on reason 1** (16.4× worst-case margin is not scarce),
> **reason 3** (2k2 lowers rail load, and §F.1's correction makes rail headroom *more* precious,
> not less) and **reason 5** (the clamp decouples `Vw` from protection). Reason 2 is **retracted**;
> reason 4 is unaffected. An implementer following the old J5 literally would have declared a
> passing gate failed, or "fixed" the whitelist.

**This spec is WRONG if any of the following turns out to be true — check them explicitly:**

- **`Vf(LED)` is materially above 1.15 V at 1.3 mA.** Every margin in §C scales off it. The
  powered characterization session should measure it on a real PC817B at ~1.3 mA.
- **`Vw` sits below 4.2 V under full 40-channel load.** Then execute the §C contingency
  (`Rin` → 1k8, value-only BOM change). Measure `Vw` loaded, not just the TP4 unloaded gate.
- **A cam channel turns out to be AC.** Then §B.4 applies and a **firmware** change is required
  before those channels are usable. r6 makes them *survivable*, not *usable*. Do not let the
  hardware fix create the impression the functional problem is closed.
- **A slow channel exists with a release-timing budget tighter than 200 ms.** Then the 2.2 µF cap
  must not be fitted on it. None is known today; verify against the FSM before fitting any cap.
- **The KiCad DRU `startsWith` predicate is unavailable in 10.0.2.** Then enumerate the 40 net
  names explicitly rather than dropping the rule.
- **Row 1 (SB) DRC fails at `Dser_SB` = (62.0, 19.95).** Fallback: relocate R122/R123 vertically
  into Lane M at x = 65.0, centred in a 4.34 mm inter-run gap (pads must clear both the
  `FIELD_LED` run at `y−1.8` and the field-return run at `vy` by ≥ 0.55 mm). This is a larger
  change — it re-routes `FIELD_WET_V` and `FIELD_GND` taps — so only take it if the first
  fallback fails.

---

## K. Residuals carried forward — NOT closed by r6

1. **Firmware AC handling on GP6–GP13** (§B.4). The single most important open item this spec
   creates. Needs a cam-channel AC/DC measurement, then a firmware decision.
2. **Does the 24 VAC ladder stay energised after the 82-70 brain is removed?** Unresolved in the
   repo; gates both §B.4 and G-2. Already on the metering list (round-5 audit §5.8.4).
3. **`Vf(LED)` and loaded `Vw` are still assumptions**, not measurements. §J lists them.
4. ~~**FA-9** … unchanged by r6.~~ **CORRECTED 2026-07-25 (r6 review): FA-9 IS changed by r6, in
   exactly the parameter r6 touched.** FA-9 qualifies the PC817 lot at *"this board's ~1.7 mA
   I_F"* (`first_article_pack.md:436`, `:482`). r6 inserts a series diode in every channel:
   §C gives **`I_F` = 1.340 mA at `Vw` = 5 V**, and at FA-9 step 3's own loaded-minimum leg
   (TP4 ≈ 4.5 V) it is **≈ 1.12 mA** — **21 % to 34 % below the stated test condition.** The
   `PART_LOCK` note tying the PC817B 130 % CTR floor to the "R4 disposition" pointed at the
   pre-r6 operating point too. **FA-9 has been updated** (§I.10) to state 1.34 mA / ~1.12 mA.
   Separately, FA-9 step 5's *"require the slower transition ≤ 100 µs"* on **every** populated
   channel is contradicted by the r6 DNP instruction shipped in the fab package
   (`assembly/…-dnp-excluded.csv`, `export_fab_revD.py`), which tells the commissioning
   technician to fit 10 nF on GP6–GP13 (47k × 10 nF × ln(3.3/1.155) = **493 µs**, 4.9× over) and
   up to 2.2 µF on MCP channels (**≈ 180 ms**). **Resolution (documentation, no copper): FA-9 is
   measured with every `Cflt_*` UNFITTED — they ship DNP and the first article has none. A
   channel that later takes a `Cflt` is re-qualified against the debounce budget
   (`DEBOUNCE_CAM_US` 2000 µs / `DEBOUNCE_DIELL_US` 500 µs / the slow-channel 200 ms release
   budget), NOT against ≤ 100 µs.** That ordering is now stated in FA-9, in the DNP reason text,
   and in the fab README. **OG-1 / H2 / G15 / PC817 sign-offs, firmware flash** (47k firmware has
   NEVER been on a rev-C board) and the **off-disk copy of the release evidence** are unchanged.
5. **New: FA-15** (§F.4 — *not* FA-10, which is the MCV mechanical gate) — with the machine
   driving 33 V, the LED node must read **0.35 V ± 0.1 V** reverse. **Landed in the pack.**
6. **G-1 and G-2 remain open owner decisions** and should be re-opened for the fleet revision with
   the measurements named in §G.
7. **NEW — two items opened by the r6 review, both OWNER DECISIONS for the fleet revision:**
   - **`FIELD_WET_V` bulk capacitance (§F.1 correction).** The isolated field rail has **zero**
     capacitance (43 nodes, no C) and the unregulated TMA-0505S must serve 16.8 mA half-cycle
     peaks from any driven 24 VAC channel. Safe **only while N = 0 driven channels** (J10b).
     Adding a bulk cap is new copper + a new part class + a new FR review — out of scope for the
     smallest-change discipline of this spin, in scope for the fleet revision.
   - **Field-pin ↔ field-pin clearance (§D.5.1).** Measured minimum **0.4807 mm** against an
     IPC-2221B B1 requirement of 0.6 mm, on nets that after r6 sit at the same potential as the
     `FIELD_LED_*` nets the new 0.6 mm rule governs. Pre-existing geometry; closing it means
     re-routing the hand-won B.Cu channel columns.

---

*Written 2026-07-25. Every geometric number was measured from `kicad/revD/wsl-phase8b-revD.kicad_pcb`
via KiCad 10.0.2 `pcbnew` in this session; every part identity and stock figure was fetch-verified
against LCSC/JLCPCB on 2026-07-25; every constant was read from source, not from a prior document.
Where a value is an assumption rather than a measurement, §J says so.*
