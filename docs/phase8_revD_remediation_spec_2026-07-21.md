# Phase 8 Rev-D — Remediation Specification (2026-07-21)

> **Status: SPECIFICATION — gates every downstream remediation task of the 2026-07-21 Codex
> NO-GO campaign.** Scope here = **R1** tap front-end redesign (closes **C1 + H1**), **R2**
> creepage margin + silk + drill (closes **H2, M3, M4**), **R3** firmware v1.2 contract
> (the hardware-facing half of **C2**), **R4** PC817B CTR disposition (**M5**).
> Findings C3/H3–H8/M1/M2/M6/M7 are owned by their own campaign tasks; where this spec
> changes a number they cite, the "doc updates required" list in §5 names the file.
>
> Baseline design state: `phase8_revD_change_spec.md` (items A–G, routed board
> `kicad/revD/wsl-phase8b-revD.kicad_pcb`, DRC r3 clean) + `phase8_revD_run_log.md`
> (FR-1…FR-7, WVR-ERC-1, COR-1…COR-4, RD-VIA-1, PV-1, OG-1/OG-3 open).
> **This spec SUPERSEDES change-spec §E.2/§E.3 (the resistive tap networks) and the
> matching `block_diag()` tap code in `generate_kicad_netlist_revD.py`.** Everything else
> in the change spec stands.
>
> **SACRED-FILE RULE unchanged:** no rev-B/rev-C design file is touched; hash-verify
> `backups/revC_design_snapshot_2026-07-19/MANIFEST.json` (189 files) after every batch.
> **Electrical invariants unchanged:** Safety_Rail netclass count EXACTLY 13 (drift =
> stop-ship); no new copper on `SAFE_*` / `RELAY_ENABLE_RAIL` / `RAIL_GATE`; no load or
> divider on the rail; GND↔FIELD_GND zero shared nodes; barriers crossed only inside
> PC817s (LOGIC↔FIELD) and G5LEs (LOGIC↔MACHINE). Every part class touched gets a
> footprint-vs-datasheet FR entry in the run log (the G5LE-1/-14 scripture).

---

## R1. Tap front-end redesign — unidirectional sensing stages (closes C1 + H1)

### R1.1 The defect, restated from the audit

The as-routed rev-D taps are **bidirectional resistive connections**: `R_TAP_ARM` /
`R_TAP_RPOK` / `R_TAP_KICK` (680 k series) and `R_TAP_555` + `R_TAP_555_DIV`
(100 k / 680 k divider) connect RP2040 GPIOs GP16–GP19 **directly in copper** to
NE555_OUT / WDOG_KICK / ARM_PERMIT / RP2040_OK. Two consequences:

- **C1:** a stuck-high GPIO injects current *into* the observed net. COR-1 already proved
  the 680 k value cannot make this absolutely safe: with the legitimate ARM_PERMIT driver
  high-Z (Pi rebooting — the exact window that matters) the injected 0.42 V base bias
  drives the MMBT3904 AND transistor at ~5–30 µA at ~85 °C junction, and only ~5–13 µA
  through the 100 k `R_RAIL_GATE_PULLUP` spans the AO3401A's full V_GS(th) range
  (−0.5…−1.3 V) — the pass-FET can be held or partially held. The existing mitigation is
  *procedural* (firmware never drives GP16–19), i.e. the hazard is one firmware bug away.
- **H1:** the NE555 tap's 100 k/680 k ratio rides an unguaranteed light-load VOH (COR-2:
  up to ≈ 4.05 V at the 5.25 V worst rail → 3.53 V at the pad, above VDD 3.3 V, below the
  3.6 V absolute max only by grace of the unguaranteed VOH assumption).

### R1.2 New topology — small-signal N-FET inverter per tap

Per tap: **2N7002 (SOT-23 — existing footprint class AND existing BOM part: every
`Qled_*` lamp driver is a 2N7002 `Q_NMOS_GSD`)** wired common-source:

```
observed_net --- R_in ---+--- gate (2N7002)         source --- GND
                         |
                     [R_gpd 10M to GND — 3.3 V taps only, see R1.3]

VCC_3V3 --- R_pu 10k ---+--- drain --- GPIO (input, Schmitt)   ["TAP_*" net]
```

**Why this is genuinely unidirectional:** in unfaulted hardware the GPIO connects ONLY to
the drain. Drain→gate is an open circuit at DC (C_rss ≈ 5 pF reverse capacitance only);
gate→observed-net is the only copper touching the observed signal, and a MOS gate sources
nothing (I_GSS ≤ 100 nA). **Any GPIO state — input, output-high, output-low, stuck,
latched — injects ZERO DC into the observed net.** The only reverse path is an *internal
FET fault* (drain-gate short), which is the double-fault case sized safe in R1.4. C1's
"accidental non-use" objection dies at the netlist: the copper itself cannot assert.

**Logic inversion (binding on firmware, R3):** observed HIGH → FET on → GPIO reads LOW.
All four taps are inverted.

### R1.3 Component values — derivation with sources

| Ref (per tap) | Value | Why |
|---|---|---|
| `Q_TAP_555` / `Q_TAP_KICK` / `Q_TAP_ARM` / `Q_TAP_RPOK` | 2N7002, SOT-23 | V_GS abs max **±20 V** (onsemi 2N7002LT1G / Nexperia 2N7002 datasheets — VERIFY against the chosen MPN in a new FR run-log entry): tolerates the NE555's entire unguaranteed VOH range (≤ 5.25 V) **by construction — H1 closed**. V_GS(th) 1.0–2.5 V @ 250 µA, 25 °C; tc ≈ −5 mV/°C. |
| `R_TAPIN_*` | **1 M**, 0805 | Injection limiter — sized by the double-fault math in R1.4 (the task's "1 M class" lands exactly here). New BOM value (replaces 680 k, which R1 deletes — see R1.7). |
| `R_TAPPU_*` | **10 k**, 0805 (existing value) | Drain pull-up. 10 k (not 100 k) so worst-case hot drain leakage cannot fake a reading: 2N7002 I_DSS is only bounded at V_DS = 60 V (1 µA @ 25 °C, 0.5 mA @ 125 °C); at 3.3 V/85 °C the realistic bound is ~µA-class → droop ≤ µA × 10 k = tens of mV. With 100 k the same leakage could eat 1 V+. FET on-state must sink 3.3 V/10 k = 0.33 mA — trivially inside 2N7002 capability at worst-corner V_GS (R1.5). |
| `R_TAPG_KICK/ARM/RPOK` | **10 M**, 0805 | Gate pulldown for a defined off-state when `R_TAPIN` fails open (gate would otherwise float). 10 M keeps the divider penalty on gate drive to 1/11 (R1.5). New BOM value. |
| (NE555 tap: **no R_gpd**) | — | The 555 output is push-pull and **never high-Z** — there is no floating-gate state to define, and omitting it preserves 0.3 V of gate-drive margin against the 555's worst-case VOH (R1.5). Asymmetry is deliberate; do not "tidy" it. |

Observed-net side facts used throughout (all from `generate_kicad_netlist_revD.py`,
read 2026-07-21):

- ARM_PERMIT / RP2040_OK each feed `Rb_AND_* = 10 k` into an MMBT3904 base with
  `Rpd_AND_* = 100 k` to GND (`block_rail()` lines 633–639).
- RAIL_GATE hold path: `R_RAIL_GATE_PULLUP = 100 k` (line 618); AO3401A V_GS(th)
  −0.5…−1.3 V; **partial-hold onset ≈ 5 µA, full-hold ≈ 13 µA through the 100 k**
  (run-log COR-1).
- WDOG_KICK feeds the AO3400 kick gate through `R_WDOG_KICK_GATE = 1 k` +
  `R_WDOG_KICK_PD = 10 k` (`block_watchdog()` lines 404–405); AO3400 V_GS(th) min 0.65 V.
- Hot-conduction calibration (COR-1): MMBT3904 V_BE = 0.42 V → I_C ≈ 5–30 µA at ~85 °C
  junction; subthreshold slope at 85 °C ≈ 71 mV/decade (ln10 · kT/q).
- VCC_5V = 4.6–4.8 V after D_PROT (`06_board-power.md` §6.2.2; change spec §0);
  absolute worst rail bound 5.25 V (change spec §D).

### R1.4 Worst-case DOUBLE-FAULT math (the C1 gate)

**Design basis: any single component fault, PLUS the legitimate driver high-Z (Pi
reboot/BOOTSEL state — an operating state, not a fault), PLUS 85 °C junction, must leave
the rail un-holdable and un-assertable.** The worst single fault is the FET **drain-gate
short** (the only fault that creates a reverse path). We additionally stack a stuck-high
GPIO on top (making it a true double component fault + reboot state + temperature).

**Case A — ARM_PERMIT tap (identical for RP2040_OK): D-G short, driver high-Z, 85 °C.**
Injection path: 3V3 → R_pu 10 k → (D-G short) → R_TAPIN 1 M → ARM_PERMIT → Rb_AND 10 k →
base node (Rpd_AND 100 k ∥ b-e junction). Ignoring the 10 M gate pulldown (conservative —
it only shunts):

- V_base = 3.3 × 100k / (10k + 1M + 10k + 100k) = 3.3 × 100/1120 = **0.295 V**
- I_C at 85 °C, scaled from the COR-1 calibration point (0.42 V → ≤ 30 µA):
  ΔV_BE = 0.42 − 0.295 = 0.125 V → factor 10^(0.125/0.071) ≈ 57 →
  **I_C ≤ 30 µA / 57 ≈ 0.53 µA**
- V across R_RAIL_GATE_PULLUP = 0.53 µA × 100 k = **0.053 V** vs the 5 µA/0.5 V
  partial-hold onset → **≥ 9× below partial-hold, ≥ 24× below full-hold** — even against
  the temperature-derated AO3401A threshold floor (|V_GS(th)|min at 85 °C ≈ 0.5 −
  60 °C × ~2.3 mV/°C ≈ 0.36 V, i.e. still 7× above the injected 0.053 V).

**Case A′ — stack a stuck-high GPIO on the D-G short (GPIO push-pull ≈ 50 Ω drives the
shorted drain=gate node to 3.3 V directly):**
- V_base = 3.3 × 100k / (1M + 10k + 100k) = **0.297 V** → same class:
  **I_C ≤ 0.56 µA → 0.056 V on RAIL_GATE — ≥ 8× below partial-hold onset at 85 °C.** ✓
- Absolute ceiling independent of transistor physics: total injectable current is bounded
  by 3.3 V / 1.01 M = **3.3 µA**. **Temperature scope of this bound (corrected
  2026-07-21, post-remediation review):** 3.3 µA clears the **25 °C** partial-hold onset
  (5 µA) with ~34 % headroom, but against the **derated 85 °C onset** (COR-1:
  |V_GS(th)|min ≈ 0.36 V → 0.36 V / 100 k ≈ **3.6 µA**) the headroom is only ~9 %
  (0.33 V vs 0.36 V in the voltage domain). The transistor-free bound is therefore a
  *25 °C-class* backstop, NOT by itself the at-temperature safety case — at 85 °C the
  margin comes from (a) the BJT V_BE math above (0.53–0.56 µA, ≥ 6× below the derated
  onset) and (b) the at-temperature fault-injection gate (R1.9 step 4), which proves the
  stacked fault empirically.
  **R_TAPIN floor, re-derived against the DERATED onset: never below 1 M.** (An earlier
  draft said "~825 k", derived from 3.3 V/R ≤ 5 µA — that clears only the 25 °C onset;
  825 k–910 k gives 3.6–4.0 µA, at/above the derated 3.6 µA onset, surrendering the
  transistor-free layer entirely at temperature. 3.3 V/R ≤ 3.6 µA requires R ≥ 917 k;
  1 M is the smallest standard value satisfying it, with the V_BE math as the actual
  at-temperature margin.) 1 M chosen.

**Case B — WDOG_KICK tap: D-G short (+ stuck-high GPIO), driver high-Z.**
- V at AO3400 kick gate = 3.3 × 10k / (1M + 1k + 10k) ≈ **0.033 V** ≪ 0.65 V min
  V_GS(th) → cannot fake a kick, cannot starve one (tap parallels the net; it does not
  sit in series). ✓

**Case C — NE555_OUT tap: D-G short + stuck-high GPIO.**
- The 555 output is an always-driven push-pull mA-class stage; injected current ≤
  3.3 V / 1.01 M ≈ 3.3 µA — 3 orders below its drive. Cannot assert or hold. ✓

**Case D — legitimate driver ACTIVE (push-pull ~50 Ω), any tap fault:** injected
disturbance ≤ 3.3 µA × 50 Ω ≈ **0.17 mV**. ✓

### R1.5 Reading integrity, worst corners, and kick-path loading

Gate-drive margin (FET must conduct 0.33 mA when observed net is high). Worst stack =
cold corner (−10 °C winter cold-start: V_GS(th)max ≈ 2.5 + 35 °C × 5 mV = **2.68 V**),
I_GSS spec bound 100 nA through the gate Thevenin:

| Tap | V_gate(high) worst | vs V_th(max, −10 °C) | Margin |
|---|---|---|---|
| ARM/RP_OK/KICK (driver = 3.3 V rail −3% = 3.2 V; ÷ (1M/10M divider) 10/11; − 100 nA × 0.91 M) | 3.2 × 0.909 − 0.09 = **2.82 V** | 2.68 V | **+0.14 V worst-stack** (typ V_th 1.6 V → >1.2 V typical) |
| NE555 (VOH ≥ VCC_min − 1.7 = 4.6 − 1.7 = 2.9 V — the *heavy-load* datasheet bound at 100 mA, used as a pessimistic floor for a µA load; − 100 nA × 1 M) | **2.80 V** | 2.68 V | **+0.12 V worst-stack** |

These worst-stack margins are thin **but the failure consequence is a missed diagnostic
reading, never an electrical hazard** — the safety asymmetry is the point of the
redesign. H1's original complaint (unguaranteed VOH vs GPIO absolute maximum) is gone:
the gate tolerates ±20 V; the GPIO only ever sees the 3V3-referenced drain.
**First-article gate: scope all four gate and drain nodes and record actual levels**
(expected gate-high ≥ 3.0 V typical). Off-state: 555 VOL ≤ 0.25 V and the 3.3 V nets'
own pulldown chains (110 k / 11 k to GND) hold gates ≪ 1.0 V V_th(min). ✓

Timing / kick-path loading (the WDOG_KICK edge-integrity requirement):

- Tap input impedance seen by the observed net: ≥ 1 M DC + (C_iss ≈ 50 pF *behind* 1 M).
  The kick path drives the AO3400 gate through 1 k — the tap adds a 1 MΩ ∥ branch:
  **loading ratio ≤ 0.1 %, kick edge at the AO3400 gate slows by < 0.1 %**. The NE555
  kick chain is unaffected. ✓
- Tap propagation: gate node τ = (1M ∥ 10M) × ~50 pF ≈ **45 µs**; drain node
  τ = 10 k × ~35 pF ≈ **0.35 µs**. Total ≪ the 1 ms edge-ordering requirement. ✓
  (These are diagnostic taps, not machine inputs — constraint 8 untouched.)

### R1.6 FMEA table (per tap; "victim" = the observed net's downstream)

| # | Fault | Effect on observed net | Effect on reading | Safe? |
|---|---|---|---|---|
| F1 | GPIO stuck output-HIGH | **none** (drain only; no DC path to gate) | none | **✓ by construction** (C1's headline scenario) |
| F2 | GPIO stuck output-LOW | none | reads "observed HIGH" constantly — detectable vs commanded state | ✓ |
| F3 | FET D-G short | ≤ 3.3 µA injected (R1.4 A/B/C) — cannot hold/assert at 85 °C | corrupted — detectable | ✓ |
| F4 | FET D-G short **+ GPIO stuck-HIGH** (double) | ≤ 3.3 µA (Case A′) | corrupted | ✓ |
| F5 | FET D-S short | none (gate isolated) | reads "observed HIGH" constantly | ✓ |
| F6 | FET G-S short | observed net gains a 1 M load to GND: on a 3.3 V push-pull net ≈ 3.3 µA vs the existing 110 k/30 µA pulldown — cannot false-disarm | reads "observed LOW" constantly | ✓ |
| F7 | R_TAPIN open — **KICK/ARM/RPOK taps** | none (the open removes ALL copper to the observed net — injection is zero by construction) | gate → R_gpd 10 M → FET off → reads "observed LOW" constantly; **detectable** (ARM tap reads LOW while rail armed = impossible state) | ✓ |
| F7b | R_TAPIN open — **555 tap** (no R_gpd, R1.3) | none (same zero-copper argument) | **NOT guaranteed detectable** (corrected 2026-07-21): a floating MOS gate is not guaranteed off, and the routed TAP_GATE_555 trace is 61.6 mm with ~25 mm running parallel to NE555_OUT copper at ~0.5 mm edge gap (gate seg (125.2,53.75)–(150.2,53.75)) — with R_TAPIN open the floating gate capacitively couples to its own source signal and can keep producing plausible, truth-correlated (or drifting) readings instead of pinning LOW. Zero electrical hazard either way; the risk is silent loss of *measurement* integrity on one advisory diagnostic channel. **Accepted residual** (same class as F9): consequence is diagnostic-trust only; treat any post-mortem that leans on the 555 tap as requiring corroboration from the KICK tap + heartbeat evidence. Adding an R_gpd to the 555 tap is NOT the fix — it costs 0.3 V of gate-drive margin the R1.5 worst-stack cannot afford (2.80 V vs 2.68 V). | ✓ (safety) / ✗ (detectability — accepted residual) |
| F8 | R_TAPIN short (single) | gate sits on observed net directly — still **no** outward DC path (MOS gate, ≤ 100 nA) | reading works | ✓ |
| F9 | R_TAPIN short **+ D-G short** (double component fault) | base ≈ 3.3 × 100k/120k = 2.75 V through R_pu → BJT hard-on → **rail held — UNSAFE** | — | **✗ residual** — see disposition below |
| F10 | R_pu open | none | drain floats — Schmitt indeterminate; detectable (noise/stuck) | ✓ |
| F11 | R_pu short | none to observed net. **Consequence corrected 2026-07-21 (was "local damage only"):** drain is tied hard to 3V3, so every time the observed net goes HIGH the FET turns on and dead-shorts VCC_3V3 to GND through R_DS(on) (~2–7 Ω) — the Pico's onboard 3V3 regulator current-limits/folds back, browning out the RP2040 → watchdog reset → RP_OK drops → **rail drops. Whole-lane-down**, potentially boot-looping in sync with the observed signal (e.g. arm attempt → brownout → reset → re-arm → repeat). Failure direction is strictly fail-SAFE (rail can only ever drop, never hold). **Field signature for triage: "lane dies on every arm attempt" (or in sync with the tapped signal) → suspect the tap drain pull-up short BEFORE the Pi/UART.** | brownout/reset, not a stable stuck read | ✓ (fail-safe; lane-down, NOT merely local) |
| F12 | R_gpd open | none | lose defined-off backup; net-side pulldowns still define — degraded redundancy only | ✓ |
| F13 | R_gpd short | observed net gains 1 M-to-GND via R_TAPIN (as F6) | reads "observed LOW" | ✓ |
| F14 | Temp corners −10…+85 °C | all injection cases evaluated at 85 °C junction (worst, R1.4); drive margins at −10 °C (worst, R1.5) | — | ✓ |

**F9 disposition (residual double-fault):** requires two independent component failures
*including a thick-film chip resistor failing SHORT — a failure mode vendor FIT data puts
1–2 orders below fail-open* (opens dominate: sulfuration, trim-cut cracks, thermal). The
rev-C rail already accepts single-fault-plus-state as its design basis; this residual is
strictly deeper (double component fault) than the C1 scenario being remediated
(zero-component-fault + state). Defense-in-depth retained anyway: the R3 firmware
input-only invariant + host direction test (a stuck-high GPIO can no longer *arise* from
software), and the at-temperature fault-injection gate (R1.9) which physically inserts
F3/F4 each first article. **Accepted; recorded here as the FMEA's stated residual.**

### R1.7 Netlist / netclass / audit / BOM deltas

Implementation lands in `generate_kicad_netlist_revD.py::block_diag()` (replace the five
tap resistors); everything append-only where order matters.

**Remove (5 parts):** `R_TAP_555` (100 k), `R_TAP_555_DIV` (680 k), `R_TAP_KICK`,
`R_TAP_ARM`, `R_TAP_RPOK` (680 k). **680 k leaves the BOM entirely** (taps were its only
use — run-log FR-6).

**Add (15 parts):**

| Tag | Value / part | From | To |
|---|---|---|---|
| `R_TAPIN_555` | 1M 0805 | `NE555_OUT` | `TAP_GATE_555` |
| `Q_TAP_555` | 2N7002 SOT-23 | G=`TAP_GATE_555`, S=`GND` | D=`TAP_NE555_OUT` |
| `R_TAPPU_555` | 10k 0805 | `VCC_3V3` | `TAP_NE555_OUT` |
| `R_TAPIN_KICK` | 1M | `WDOG_KICK` | `TAP_GATE_KICK` |
| `R_TAPG_KICK` | 10M | `TAP_GATE_KICK` | `GND` |
| `Q_TAP_KICK` | 2N7002 | G/S as above | D=`TAP_WDOG_KICK` |
| `R_TAPPU_KICK` | 10k | `VCC_3V3` | `TAP_WDOG_KICK` |
| (same triple+pulldown pattern) | … | `ARM_PERMIT` → `TAP_GATE_ARM` → `TAP_ARM_PERMIT` | `RP2040_OK` → `TAP_GATE_RPOK` → `TAP_RP2040_OK` |

GPIO landing unchanged: `TAP_NE555_OUT`→pin 21 (GP16), `TAP_WDOG_KICK`→22 (GP17),
`TAP_ARM_PERMIT`→24 (GP18), `TAP_RP2040_OK`→25 (GP19) — the audit's
"taps on pins 21/22/24/25" assertion survives.

- **Parts: 252 → 262** (−5 +15). **Nets: 213 → 217** (+4 `TAP_GATE_*`).
- **Netclass:** `TAP_` prefix rule already maps `TAP_GATE_*` → Logic_Signal. New audit
  counts: **Logic_Signal 97 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 82 /
  Machine_Output 21 = 217.** Safety_Rail == 13 unchanged — verify, stop-ship on drift.
- **BOM values:** −680 k, +1 M, +10 M (net +1 line). No new footprint class (2N7002
  SOT-23 = the `Qled_*` class; 0805 R existing).
- **Budgets:** +4 × 0.33 mA worst (all taps observed-high) on VCC_3V3 ⇒ ≈ +1.3 mA on
  VCC_5V through the Pico regulator — noise vs the §H.4 0.73–0.93 A worst case; record
  the delta in the change-spec §H.4 table at implementation (standing rule: budgets
  re-run on any current change). Wetting rail untouched.
- **Diff script:** whitelist the five removed `R_TAP_*` and the added parts as
  rev-D-internal (never existed in rev-C); `diff_netlist_revC_to_revD.py` must still
  print CLEAN with D_PROT SS14→SS34 as the sole rev-C-visible change.
- **ERC:** all new pins connected; if the warning count drifts from the WVR-ERC-1
  baseline of 40, that is a **new waiver entry (WVR-ERC-2)** in the run log — do not
  silently edit the constants.
- **Footprint gate:** new FR entries — 2N7002-in-SOT-23 vs chosen MPN (verify V_GS ±20 V
  abs max on the *actual* datasheet), 1 M / 10 M 0805 availability.
- **Placement:** each `R_TAPIN` within ~10 mm of its source node (long trace on the
  gate side is then the high-impedance, low-energy run); Q/R_pu cluster near the Pico
  (x ≈ 100–135, y ≈ 35–80); all LOGIC-band, no barrier crossing, no gutter incursion.
  Full re-route + DRC + audit re-gate follows (R2 changes the DRU anyway).

### R1.8 Generator/docs coherence

At implementation: update the generator docstring item-E text, change-spec §E.2/§E.3
(mark "superseded by remediation spec R1"), the readiness checklist G-item that quotes
the 680 k proof, and the change list. COR-1's *procedural* closure text (firmware
must never drive GP16–19) remains true but is now **defense-in-depth, not the primary
barrier** — reword, don't delete. The R3 firmware invariant makes it enforced.

### R1.9 First-article fault-injection procedure (revised — includes the C1 gate)

Equipment: bench PSU, scope, heat gun + thermocouple, clip leads, the Pi-emulator rig
from the rev-C bench sessions, firmware v1.2 (normal build) + the bench-only
fault-injection build **FI-1** (drives GP16–19 output-high on command; exists ONLY for
this procedure; must refuse to run unless a physical BOOTSEL-era jumper/flag is set and
prints its identity on the UART banner).

1. **Level survey (cold):** scope each `TAP_GATE_*` and `TAP_*` drain node through the
   full signal swing; record gate-high levels vs the R1.5 table (expect ≥ 3.0 V typ).
2. **Unidirectionality proof (cold):** FI-1 drives each GP16–19 output-high in turn,
   Pi link DISCONNECTED (J1 unmated = ARM_PERMIT/WDOG_KICK high-Z, the reboot state).
   Meter each observed net: **must not move > 1 mV**; rail must not arm.
3. **Fault insertion (cold):** clip-short each tap FET drain-gate (F3), repeat step 2's
   measurement (F4 stack); then with the Pi-emulator arming the rail normally, remove
   the emulator drive (high-Z) with the short still applied — **rail must drop within
   the same watchdog window as an unfaulted board.**
4. **AT TEMPERATURE (the C1 gate — a cold-only pass does NOT discharge it):** heat the
   `Q_AND_ARM` / `Q_AND_RP_OK` / `Q_RAIL` region AND the four tap FETs to
   **≥ 70 °C case** (thermocouple-verified; hold ≥ 2 min). Repeat steps 2 and 3 in
   full: high-Z + D-G short + stuck-high GPIO at temperature; rail must neither arm
   nor hold, and a deliberate ARM_PERMIT disarm (driven low, push-pull) must still
   drop the rail.
5. **Edge-order proof:** with firmware v1.2, force (a) Pi-death (kill the emulator),
   (b) kick-starvation (emulator holds ARM high, stops kicking) — the 1 ms ring (R3)
   must show the documented edge order for each cause, and the record must survive a
   Pico reboot (R3 persistence semantics).
6. Record everything in `phase8_revD_run_log.md` (new FA-section), including thermocouple
   photos/readings. Gate OG-4 is discharged only by step 4's at-temperature pass.

---

## R2. Isolation margin, silk, and drill (closes H2, M3, M4)

### R2.1 Working voltages — derived, with sources (kills "provisional on actual working voltage")

| Domain pair | Governing circuit | Working voltage | Source |
|---|---|---|---|
| LOGIC ↔ FIELD | FIELD_WET_V wetting rail 5 V nominal; unloaded float measured ~11 V (board #1) / bounded 14 V; post-bleed ≤ ~6 V. Field channels are dry-contact wetted (cams measured DRY). Population *option* for 24 VAC-sense retained on channels → design-basis bound **24 VAC ≈ 34 Vpk** | **≤ 34 Vpk (design basis); ≤ 14 V as populated** | change list item 5; readiness §4 (11 V measurement); `phase8b_pcb_revB_BOM_power.md` A4 (cams DRY); rev-B spec §input population options |
| LOGIC ↔ MACHINE | Relay contacts are dry contacts in series with the machine's existing **24 VAC** coil circuits (T2/T3/T4 transformers); A1 field measurement: 24 VAC on all relays. Peak 24 × √2 = **33.9 Vpk**; +10 % line → **≤ 37 Vpk**. Inductive break transients appear across the *contact gap* (same-channel pair, handled by the snubber/MOV provisions), not across the LOGIC↔MACHINE barrier | **≤ 37 Vpk** | `phase8b_at_machine_fieldsheet.md` ("A1 working voltage: 24 VAC (all relays)"); `phase8_lane21_harness_build_sheet.md` ("outputs are dry contacts in series with existing 24 VAC coil circuits"); `phase8b_at_machine_HOWTO_companion.md` §A |

### R2.2 Standard and REQUIREMENT

Standard: **IPC-2221B Table 6-1, column B1 (external conductors, uncoated, sea level to
3050 m)** — the correct column for an uncoated JLC board in a machine room.
Band 31–50 V → **0.6 mm** minimum spacing for both barriers.

**REQUIREMENT (binding):**

- **LOGIC↔FIELD: ≥ 2.5 mm** creepage and clearance.
- **LOGIC↔MACHINE: ≥ 3.2 mm** creepage and clearance.

These retain the rev-B/rev-C policy floors — now as *confirmed requirements*, not
provisional numbers: they carry **≥ 4× / ≥ 5× margin** over the IPC-2221B B1 derived
minimum at the measured working voltages, they are continuous with the isolation
components' own package spacing (the copper barrier must not be the weakest link vs the
PC817 / G5LE packages), and they buy headroom for the pinsetter environment (oil mist,
lane dust, condensation — worse than the pollution assumptions behind bare Table 6-1)
and for the 24 VAC-sense population option. The old `.kicad_dru` header line
"Final distances still depend on at-machine output working voltage" is **deleted** —
the at-machine measurement (24 VAC) happened 2026-07-07 and this section records it.

### R2.3 Fab tolerance and the new `.kicad_dru` values (the H2 arithmetic)

JLCPCB published tolerances (capabilities page, fetched 2026-07-21):
**track width tolerance ±20 %**; through-hole finished diameter +0.13/−0.08 mm; PTH
annular ring ≥ 0.20 mm (multilayer recommended); silkscreen min height 1.0 mm / min
stroke 0.15 mm.

Worst-case copper-spacing loss across a barrier gap: both flanking features etch wide by
+20 %. Widest features that can flank a barrier: Machine_Output 0.5 mm vs Safety_Rail
0.6 mm traces → loss = (0.20 × 0.5 + 0.20 × 0.6)/2 = **0.11 mm**. (Pad-flanked gaps:
pad size tolerance is tighter than trace etch tolerance; 0.11 mm bounds both.)

**Allowance chosen: 0.15 mm (≈ 1.4 × the worst computed loss).** New rule values =
requirement + allowance:

| `.kicad_dru` rule | old (min) | **new (min)** | as-fabbed worst case | vs requirement |
|---|---|---|---|---|
| LOGIC↔FIELD clearance + creepage | 2.5 mm | **2.65 mm** | 2.65 − 0.11 = 2.54 mm | ≥ 2.5 ✓ |
| LOGIC↔MACHINE clearance + creepage | 3.2 mm | **3.35 mm** | 3.35 − 0.11 = 3.24 mm | ≥ 3.2 ✓ |
| MACHINE independent channel↔channel | 1.5 mm | **1.6 mm** | 1.6 − 0.11 = 1.49 mm | ≥ ~1.5 ✓ (same treatment, same arithmetic) |

The routed board's recorded minima (2.501 mm / 3.200 mm — the H2 finding) become DRC
violations under the new rules **by design**: the affected regions re-route until DRC is
clean at 2.65/3.35/1.6. Update the `.kicad_dru` header comment to cite THIS spec §R2 as
the derivation. Process: edit `kicad/revD/wsl-phase8b-revD.kicad_dru` → re-run
`route_revD.py` (restore the pristine placement board from git first — run-log routing
note) → `apply_netclasses_revD.py --write` → kicad-cli DRC (0 violations) →
`audit_revD_board.py` routed mode ALL PASS → rev-C snapshot re-hash 189/189.

### R2.4 M3 — silk stroke/height

`place_components_revD.py` writes **every** F.SilkS label at 0.8 mm height (default
stroke ≈ 0.1 mm) — below JLC's published 1.0 mm height / 0.15 mm stroke minimum; JLC
auto-widens thin strokes, which is exactly how "KEYED: NOT J15" degrades into an
illegible smear at the moment it matters.

- The four **KEYED** cross-mate warnings: **height 1.2 mm, stroke 0.20 mm** (these are
  the safety-relevant ones — extra margin).
- All other F.SilkS labels ("J6 S" … "EXT I2C", band labels): **height 1.0 mm, stroke
  0.15 mm** minimum.
- Dwgs_User text (USB keep-out annotations etc.) is not fabricated — unchanged.
- Re-run placement-stage DRC for silk-overlap after the size change (the KEYED texts
  already collided once at 0.8 mm — at 1.2 mm they will need position nudges; keep them
  adjacent to their connectors).

### R2.5 M4 — MCV header drill 1.2 → 1.4 mm with annular re-check

KiCad 10's `PhoenixContact_MCV_1,5_*-G-3.5` footprints drill **1.2 mm** with
1.8 × 3.6 mm pads (footprint file read 2026-07-21). Phoenix's drilling plan for the MC
1,5 / MCV 1,5 G-3.5 header system (1843680 = the J3/J15 1×10) specifies **1.4 mm**
holes. Rev-C assembled at 1.2 mm — pins fit, but tight (finished hole runs to
1.2 − 0.08 = 1.12 mm at JLC's tolerance floor), with no insertion/solder-fill margin.

**Change (applies to ALL MCV 1,5 G-3.5 instances — J3, J4, J5, J13, J14, J15, J16 —
same pin system, same drilling plan):**

- Drill 1.2 → **1.4 mm**. Finished worst case 1.32–1.53 mm.
- Pad narrow axis 1.8 → **2.0 mm** (long axis 3.6 unchanged): annular ring
  (2.0 − 1.4)/2 = **0.30 mm** ≥ JLC's 0.20 mm multilayer recommendation with 50 %
  margin (at 1.8 mm the ring would be 0.20 mm — exactly at the floor; grow the pad).
- Pad-to-pad gap at 3.5 mm pitch: 3.5 − 2.0 = **1.5 mm** ≫ every applicable clearance
  rule (Field_Sense 0.4 mm class clearance; barrier rules don't bind same-connector). ✓
- **Implementation: project-local footprint library** (`kicad/wsl_footprints.pretty/`,
  copies suffixed `_D1.4`) — the system KiCad library is never edited (sacred-adjacent:
  it also serves the rev-C generator). Generator `FP_MCV_*` constants repoint to the
  local lib. New FR run-log entry records the pad/drill math above vs the Phoenix
  drilling plan; first-article verifies actual header insertion force + solder fill on
  one connector before reflowing the rest.

---

## R3. Firmware v1.2 contract (the hardware-facing half of C2)

Firmware repo: `wsl-lane-nodes/firmware/rp2040/` (currently `FW_VERSION
"phase8b-rp2040 v1.1.1"`, heartbeat every 250 ms, host tests under `test/` with
`mock_pico.h`). Unfrozen for exactly this scope. The firmware task implements; this
section is the binding contract.

### R3.1 Pin table (supersedes "never referenced = never outputs")

| Pin | Net | Direction (ENFORCED) | Semantics |
|---|---|---|---|
| GP16 (pin 21) | `TAP_NE555_OUT` | **input, Schmitt, no pulls** (board has 10 k pull-up) | **INVERTED**: raw 0 ⇒ NE555_OUT high |
| GP17 (pin 22) | `TAP_WDOG_KICK` | input, Schmitt, no pulls | **INVERTED**: raw 0 ⇒ WDOG_KICK high |
| GP18 (pin 24) | `TAP_ARM_PERMIT` | input, Schmitt, no pulls | **INVERTED**: raw 0 ⇒ ARM_PERMIT high |
| GP19 (pin 25) | `TAP_RP2040_OK` | input, Schmitt, no pulls | **INVERTED**: raw 0 ⇒ RP2040_OK high (self-observation cross-check vs the GP2 output register — mismatch = board fault) |
| GP26/ADC0 (pin 31) | `ADC_VCC5_SENSE` | ADC input | reads VCC_5V/2 (10 k/10 k divider, 318 Hz RC) |

All reported tap states on the wire are **post-inversion logical levels** (heartbeat and
ring records carry the observed-net truth, not raw pad values); the inversion happens in
exactly one place (a `tap_read()` accessor).

### R3.2 Input-only init as an ENFORCED invariant

- `tap_init()` runs before any other GPIO configuration: for each of GP16–19 —
  `gpio_init`, `gpio_set_dir(GPIO_IN)`, `gpio_disable_pulls`, Schmitt on (RP2040 pad
  default; set explicitly anyway).
- **Invariant check, not just init:** a `tap_assert_input_only()` function reads back
  SIO `gpio_oe` and the pad/IO-bank function registers for GP16–19 and hard-faults
  (fault report on UART + refuses to assert RP2040_OK) if any is output-enabled or
  non-SIO-function. Called (a) at the end of init, (b) periodically from the main loop
  (each heartbeat tick — it is 4 register reads).
- **Host test (fails the build if violated):** extend `mock_pico.h` to record every
  `gpio_set_dir`/`gpio_put`/OE manipulation per pin; a test drives the full firmware
  state machine through init + normal operation + fault paths and **fails if GP16–19
  ever appear in an output-direction or output-write call**. A second test tampers the
  mock OE register mid-run and asserts `tap_assert_input_only()` trips. The FI-1
  fault-injection build (R1.9) is a separate target that is **excluded** from the
  release artifact and refuses to run without its physical jumper/flag.

### R3.3 Rail-drop edge ring with reboot persistence

- **Capture:** GPIO IRQs (both edges) on GP16–19 timestamped from a 1 kHz timebase
  (1 ms resolution contract; the tap analog path contributes ≤ 45 µs, R1.5) into a
  fixed-size ring (≥ 64 entries: {ms-timestamp, pin, level}).
- **Persistence:** the ring + write index + a validity magic + a sequence/epoch counter
  live in a **`__uninitialized_ram` (noinit) section**. On boot: magic valid ⇒ preserve
  the ring, increment epoch, log `wdt_reboot`/watchdog-cause alongside (the existing
  `wdt_reboot` detection stays); magic invalid (true power loss) ⇒ zero the ring, set
  magic. Epoch lets the Pi distinguish pre-reboot edges from post-reboot edges.
- **Retrieval:** heartbeat gains {tap logical levels, ring depth, epoch, adc_vcc5};
  a query command returns the full ring (entries tagged with epoch). Ring is cleared
  only by explicit command, never by reboot.
- **Reason codes:** firmware classifies the last rail-drop from edge order (e.g.
  KICK stops → NE555_OUT drops → rail events ⇒ `kick_starvation`; ARM_PERMIT falls
  first ⇒ `arm_drop`; RP2040_OK falls first ⇒ `self_health`) and reports the code +
  the raw ring — the Pi gets both, the classification is advisory.

### R3.4 ADC cadence

VCC_5V sampled at **10 Hz** (round-robin friendly, ≫ the 318 Hz RC corner is
irrelevant for trending); heartbeat carries the latest value + a min/max over the
heartbeat interval so 250 ms sag events (6-coil inrush) are visible. Calibration
against TP1 DMM at first article (±3 % gate, change spec §D).

---

## R4. PC817B collector-pull-up hardening at 1.7 mA (M5; revised 2026-07-23)

**Implemented board change.** All 40 optocoupler collector pull-ups `Rpu_*`
(`R4,R6,…,R82`) change from 10 kΩ to **47 kΩ, 1%, 0805**. Field series
resistors remain 2.2 kΩ, so wetting current and the TMA-0505S budget do not
change. No unrelated 10 kΩ network changes.

**Why this is the correct low-risk change.** The board-selected UMW PC817B,
LCSC C5692981, guarantees its CTR rank only at the manufacturer's stated test
current and temperature. It does not publish a minimum CTR at this board's
~1.7 mA I_F and hot corner. Typical curves from another PC817 manufacturer are
useful context, not a fleet guarantee for this lot. Raising all 40 channels to
the stated 5 mA test point would consume about 200 mA in LEDs alone and exhaust
the 200 mA wetting converter budget. Increasing collector resistance buys
receiver-side margin without increasing field current.

**Binding configuration dependency.** The calculations below require the
external 47 kΩ `Rpu_*` to be the sole pull on each PC817 collector. Production
firmware must leave RP2040 GP6–GP13 internal PUE/PDE disabled, and deployed
`MachineIO` must command and verify U1/U2 MCP23017 `GPPUA=GPPUB=0x00`.
Any enabled internal pull changes the effective resistance and invalidates the
47 kΩ sink/leakage/RC disposition. The four `R_TAPPU_*` 10 kΩ diagnostic-tap
drain pull-ups are separate MOSFET-drain nets, remain unchanged, and are not
part of this calculation.

**Guaranteed receiver arithmetic (Microchip MCP23017 DS20001952):**

| Quantity | Bound at VDD = 3.3 V |
|---|---|
| GPIO V_IL(max) | 0.2 × VDD = **0.66 V** |
| Required sink at V_IL with external 47 kΩ as sole pull | (3.3 − 0.66) / 47 kΩ = **56.2 µA** |
| Maximum 47 kΩ pull-up current | 3.3 / 47 kΩ = **70.2 µA** |
| GPIO V_IH(min) | 0.8 × VDD = **2.64 V** |
| Worst idle HIGH from MCP input leakage alone | 3.3 V − (1 µA × 47 kΩ) = **3.253 V** |
| Idle-HIGH margin over V_IH | **0.613 V** |
| First-order GPIO RC using the 50 pF figure | 47 kΩ × 50 pF = **2.35 µs** |

The 50 pF calculation is a first-order receiver-node estimate; optocoupler,
trace, contamination, and probe effects are physical variables. FA-9 therefore
measures both idle-HIGH leakage margin and actual assertion/release time.

**Disposition: board margin materially improved; physical lot gate remains.**
The old 10 kΩ arithmetic required ~0.26 mA at V_IL. Rev-D now needs only
56.2 µA, a 4.7× reduction, without adding load to the isolated wetting rail.
That is sufficient justification for the PCB change. It is not permission to
declare C5692981 qualified outside its guaranteed test point.

**Binding FA-9 acceptance (every populated channel):**

1. Before applying any numeric limit, boot the exact production release and
   record live pull configuration: RP2040 GP6–GP13 PUE=0/PDE=0, plus U1/U2
   MCP23017 GPPUA/GPPUB all `0x00`. `MachineIO` readback mismatch must fail
   startup. Any nonzero pull bit is STOP-SHIP.
2. At loaded-minimum FIELD_WET, record cold and ≥70 °C `V_CE(on)` and the
   actual receiver bit; require **V_CE(on) ≤ 0.30 V** and ACTIVE-LOW.
3. At the hot/min-I_F corner, measure non-rail-limited `I_C(cap)`. With the
   retained 30% lifetime-loss planning factor, require
   `I_C(cap) × 0.70 ≥ 70.2 µA`, hence **I_C(cap) ≥ 100.3 µA**.
4. At ≥70 °C with the contact open, record the assembled node HIGH and
   receiver state. Require **V_node ≥ 2.84 V** (V_IH + 0.20 V service guard)
   and INACTIVE. This catches optocoupler dark leakage, contamination, and
   board leakage that the MCP-only 3.253 V calculation does not cover.
5. Measure assertion and release at the collector under loaded-minimum
   FIELD_WET; require the slower transition **≤100 µs**, at least 5× faster
   than the 500 µs fastest-input debounce.

Any failure blocks fleet release. A supplier/rank change, 24 VAC-sense
repopulation, resistor substitution, or year-5 service trend also reopens this
disposition. Do not automatically lower `Rin`: that would require a fresh
wetting-converter and D17 rail budget review.

---

## 5. Downstream obligations created by this spec

| Task | Owns | Must consume from here |
|---|---|---|
| Netlist/board implementation | generator, placement, route, DRU, audit | R1.7 deltas (262/217, 97/4/13/82/21), R2.3 DRU values + re-route, R2.4 silk sizes, R2.5 local footprints; new FR + WVR entries; diff whitelist |
| Firmware v1.2 (C2) | `firmware/rp2040/` | R3 contract verbatim; FI-1 build rules (R1.9) |
| Docs coherence | change spec §E (supersede pointer), change list, readiness checklist, `phase8b_pcb_revB_netclass_creepage.md` successor note, `.kicad_dru` header | R1.8, R2.2–R2.5; run-log entries for every gate run |
| First article | checklist §I.9 extension | R1.9 procedure (OG-4 discharge), R2.5 insertion check, R4 V_CE sampling |
| M7/backup task | external mirrors | this file mirrors with the next batch (same-session rule, run-log COR-4) |

Numbers marked VERIFY (2N7002 MPN abs-max/threshold, MCP23017 V_IL exact figure) get
their FR entries before fab export; everything else above cites its source inline.
