# Rev-D Recommendation: Per-Channel Input-Protection Provisions (DNP)

**Written 2026-07-25 from measured field evidence on lane 22.** Owner: rev-D workstream.
**Status: OPEN RECOMMENDATION — the fab/population decision is Dylan's, not this document's.**

> **Headline corrected 2026-07-25.** This file previously claimed the provisions are *"the
> single change that moves the remaining field campaign OFF the critical path to a fleet
> order."* That is **overstated and contradicted by this project's own metering guide**,
> which this recommendation cites as a source.
> `docs/phase8_metering_guide_harness_unknowns.md` states the cam-class work is *"Not on the
> critical path… Stage 6b (first commanded motion / coil-drop proof) needs the output taps
> and the rail, not cam inputs. Cam signals are required only for full FSM cycle timing,
> which is after first motion. Priority order stands: Stop/CIS landing → output taps →
> Stage 6b → cams."* The cam classes were never on the critical path, so no provision can
> move the campaign off it. The same guide records a documented fallback: **tap the cams AT
> THE SWITCHES and skip C2A for those four channels entirely.**
> The old headline also conflated **first article** with **fleet build**. "Any channel that
> turns out to carry sustained AC forces a respin" is **false for a prototype run** — the
> first article can simply leave the affected channels unlanded, or use the harness
> mitigation in §5. It is true only for a fleet order.
> **What remains true and load-bearing:** the protection is not a stuffing option because
> **the pads do not exist** (§0), and two channels are measured over the LED's absolute
> maximum today (§2).

---

## 1. The problem

`opto_input()` in `scripts/generate_kicad_netlist_revD.py` (line ~381) is a **single hardcoded
topology for all 40 input channels**:

```
FIELD_WET_V → Rin (2k2) → PC817 LED anode → [LED] → field pin
```

There is **no series blocking diode, no reverse clamp, and no AC-capable option**. Every
channel's optocoupler LED is therefore directly exposed to whatever voltage its machine wire
sits at, against a **PC817 LED reverse rating of 6 V**.

Because the topology is baked into copper rather than into population, the front-end choice is
made at **fab time** instead of at **stuffing time** — which is backwards for a board whose
input voltage classes are still being measured in the field.

### 0. Verified against the emitted netlist (do not re-litigate this)

`kicad/wsl-phase8b-revD.net`: **all 40 `FIELD_LED_*` nets carry exactly two nodes**
(`Rin_*` pin 2 → PC817 pin 1). There is **no series-diode pad, no clamp pad, and no
logic-side filter-cap pad on any of the 40 channels.** Population cannot add a part that has
no pads. Any claim that the item-6 outcome "changes population/BOM, not copper" is false;
`phase8_revD_change_list.md` and `phase8_revD_readiness_checklist.md` G7 were corrected on
2026-07-25 to read **REQUIRES COPPER — deferred to the fleet revision.**

## 2. The measured evidence (lane 22, 2026-07-18/21)

Reverse voltage across the LED is `V_field − Vw` (the drop across `Rin` is negligible: LED
reverse leakage ≤ 10 µA × 2k2 = 22 mV). **So every volt removed from the wetting rail `Vw` is
a volt ADDED to the reverse stress on every over-voltage channel** — see §2.1.

| Channel(s) | Measured under OEM power | Reverse bias @ Vw ≈ 11 V (rev-C rail) | Reverse bias @ Vw ≈ 5–6 V (**rev-D actual**) | Verdict |
|---|---|---|---|---|
| GS1–GS10, BS | **11 VDC** dry | ~0 V | ~0 V | safe bare |
| **PBZ** | **33 VDC** (rectified-24 VAC class) | 22.0 V — **3.67×** the 6 V limit | **27–28 V — 4.50–4.67×** | **destroys that channel's LED** |
| **DIELL-L/R signal** | **15.4–16 V** at rest (DIELL board self-powers) | 4.4–5.0 V — 0.73–0.83× ("no margin") | **9.4–11.0 V — 1.57–1.83×** | **absolute-maximum VIOLATION**, measured, permanent (survives brain removal) |
| DIELL board middle block | **42 VAC** | — | machine/VDB interface, never tapped |
| **SA · SB · TA1 · TA2 (cams)** | **UNMEASURED** | unknown | cam contacts sit **in series in the machine's 24 VAC relay ladder** (proven by the ~21 Ω coil sneak paths that invalidated two cold-mapping attempts) → **AC exposure is the prior, not the exception** |
| FOUL (lamp wire), GP, PBC | unmeasured | unknown | classes still open |

Change-list item **#6** already anticipated the *question*: *"per-channel input front-end:
dry-contact vs 24 VAC-rectified sense…"* — but its trailing claim that this *"may change
population/BOM per channel, not copper"* was **wrong** and has been retracted (see §0). The
item remains unresolved in rev-D and now carries **REQUIRES COPPER**.

### 2.1 Rev-D item A (the 1.1 kΩ `FIELD_WET_V` bleed) makes the reverse-bias problem WORSE

`block_supplies()` in `scripts/generate_kicad_netlist_revD.py` adds **2 × 2k2 in parallel
(1.1 kΩ, 4.5 mA) across FIELD_WET_V → FIELD_GND**, commented *"Kills the 11–14 V unloaded
float on the unregulated TMA-0505S (TP4 gate: ≤ ~6 V unloaded)."* That is correct and
desirable for the **TP4 unloaded-float gate**, but it is **not free for the input front end**:
because reverse stress is `V_field − Vw`, pulling the rail from ~11 V down to ~5–6 V **adds
5–6 V of reverse stress to every over-voltage channel.**

The practical consequence is a change of *kind*, not just degree, for DIELL-L/R: at the old
rail those channels were **inside** the 6 V absolute maximum (0.73–0.83×, "no margin"); at
the rev-D rail they are **outside** it (1.57–1.83×) — an absolute-maximum violation on a
**measured, permanent, self-powered** condition, not a transient. **This document's own
strongest evidence is stronger than the original text claimed**, because the original
computed against the superseded rev-C rail.

**This is recorded as a fact about the design, not as a request to change item A.** Item A is
frozen copper for this spin and its TP4 rationale stands. The correct reading is that item A
raises the priority of *not landing* DIELL-L/R (and PBZ) on a bare first-article input — see
the first-article pack's input front-end warning.

## 3. Recommendation — per-channel provisions (**NOT all DNP** — corrected)

> **Corrected 2026-07-25.** This section previously read *"three DNP footprints per input
> channel… all unstuffed by default."* **The series element cannot be DNP.** A series
> footprint left unstuffed **OPENS the channel** — an unpopulated board would have all 40
> inputs dead. The series position must therefore default to a **fitted 0 Ω jumper** (or a
> normally-closed solder bridge cut when the diode is fitted), i.e. it is a **populated part
> on every channel**. Only the clamp and the filter cap can genuinely be DNP.

| Provision | Default | Purpose | Notes |
|---|---|---|---|
| **Series position** — 0 Ω jumper *or* blocking diode (1N4148/1N4007 class) | **POPULATED (0 Ω)** | With the diode fitted, blocks DC over-voltage: reverse appears across the diode, not the LED | Costs ~0.6–0.7 V of forward drive — see §4. **Never DNP.** |
| **Anti-parallel clamp diode** across the LED | DNP | Clamps LED reverse to ~0.7 V with **zero** forward-current penalty; also the classic cheap **AC-sense** front-end (opto pulses at line rate) | **Does not block DC — it conducts.** Must not be fitted alone on a non-dry channel; see §4. |
| **Filter cap** on the slow-input logic side | DNP | Integrates an AC channel's pulse train into a steady level so MCP reads don't chatter | Fast (RP2040) channels may prefer edge counting instead |

**Costs the original text did not account for**, and which belong in the fleet-revision
decision:
- **+40 JLC placements** on the assembly BOM for the mandatory series jumper (one per
  channel), plus the clamp/cap pads whether or not they are stuffed.
- **40 additional solder joints placed in series with every single machine input** on a
  safety-relevant board. A series element in the sense path is a new single-point failure
  mode per channel; that is a real reliability debit to weigh against the protection it buys.

## 4. The three provisions are COMPLEMENTARY, not alternative (corrected)

> **Corrected 2026-07-25.** This section previously framed the resolution as a choice —
> *"anti-parallel clamp only, series diode with an `Rin` retune, or a different
> optocoupler."* **That is wrong for this topology.** For any non-dry channel the correct
> populated set is **series diode + anti-parallel clamp + logic-side filter cap TOGETHER.**

**Why clamp-ALONE fails.** A clamp does not block DC — **it conducts**, backfeeding `Rin` into
the shared `FIELD_WET_V` rail, which has **no sink** (the TMA-0505S is a source-only isolated
converter; the only load is the 1.1 kΩ item-A bleed). Solving self-consistently for PBZ at
33 VDC with a clamp fitted:

```
(33 − 0.7 − Vw) / 2200  =  Vw / 1100     →   Vw = 10.8 V  at  9.8 mA
```

**ONE over-voltage channel drags the wetting rail for ALL 40** and back-drives the TMA-0505S
output to ~2× nominal. A clamp is a per-channel part with a whole-board side effect.

**Why series-diode-ALONE is weak.** It works, but the LED's reverse voltage is then set by a
**leakage divider** between the blocking diode (~nA) and the LED (`I_R` max 10 µA at 4 V).
The LED is protected by an unspecified parameter ratio rather than by construction — fine in
practice, not something to certify a safety-relevant input on.

**Therefore:** the diode blocks the DC path, the clamp bounds the reverse excursion by
construction instead of by leakage ratio, and the cap de-chatters the AC pulse train. Each
covers a hole the others leave.

### 4.1 The CTR cost of the series diode is real but NEGLIGIBLE (overstated in the original)

The original text said a series diode "makes that worse" and implied an `Rin` retune is
required. **In sign yes, in magnitude no — the rev-D 47 kΩ pull-up already paid for the
diode.** All figures at `Vw = 5 V`, `Vf(LED) = 1.15 V`, `V_IL = 0.66 V` at 3.3 V:

| Case | `Rin` | `IF` | CTR (worst-case bin, derated) | `IC` | Required sink | Margin |
|---|---|---|---|---|---|---|
| **Old 10 kΩ pull-up** (rev-C) | 2k2 | 1.75 mA | ~71.5 % | 1.25 mA | **264 µA** | **4.7×** |
| **Rev-D 47 kΩ, no diode** | 2k2 | 1.75 mA | ~71.5 % | 1.25 mA | 56.2 µA | **22×** |
| **Rev-D 47 kΩ + 0.60 V series diode** | 2k2 | 1.48 mA (−16 %) | ~69 % | 1.02 mA | 56.2 µA | **18×** |
| *Optional* exact-`IF` restore | **1k8** | 1.81 mA (+3 %) | ~71.5 % | 1.25 mA | 56.2 µA | **~23×** |

The diode moves the margin **22× → 18×**. **No `Rin` retune is required.** The 47 kΩ change
bought 4.7× → 22× of headroom; the diode spends only a small fraction of it. If an exact `IF`
restore is wanted anyway, `Rin = 3.25 V / 1.75 mA = 1857 Ω` → **E24 1k8**.

### 4.2 Quantified: a bare PC817 LED on a sustained 24 VAC line

This is the case the cam channels (SA · SB · TA1 · TA2) are the prior for. `Vpk = 24·√2 =
33.94 V`, `Vw = 5 V`, `Rin = 2k2`:

- **Negative half-cycle (LED forward): HARMLESS.** `IF,pk = (5 + 33.94 − 1.15)/2200 =
  17.2 mA`; full-cycle average **5.5 mA**; `Pd ≈ 6.3 mW` — well inside the 50 mA / 70 mW
  ratings. The channel even *functions*, as a 60 Hz pulse train.
- **Positive half-cycle (LED reverse): FATAL.** `V_R,pk = 33.94 − 5 = 28.9 V` = **4.82× the
  6 V absolute maximum**, recurring at 60 Hz = **~5.2 million avalanche events per day**.

The failure is **strictly one-sided**, and it is not survivable as a design. An anti-parallel
clamp fixes exactly this case for ~$0.01 with **zero forward-current penalty** — which is why
the clamp is the highest-value of the three provisions *for the AC case specifically*, even
though §4 shows it must not be fitted alone.

### 4.3 Zero-copper option: bidirectional (PC814 / LTV-814 class) photocoupler

This is the only option requiring **no copper change at all** — a per-channel *stuffing*
decision on the **current** board — and it was under-explored. Datasheet figures located
2026-07-25 (Sharp PC814 series, AC-input photocoupler):

- **Package: 4-pin DIP, lead row spacing 7.62 ± 0.3 mm** — matches the existing
  `DIP-4_W7.62mm` PC817 land. Input is an **anti-parallel LED pair on pins 1/2**,
  phototransistor on 3/4.
- **CTR: min 20 % at `IF = ±1 mA`, `V_CE = 5 V`.** This is the important number and it is
  **better than previously estimated** (an earlier estimate assumed the bin was specified at
  10–20 mA). Because 1 mA is **below** the design's 1.75 mA operating point, there is **no
  low-current extrapolation penalty at all** — unlike PC817B, whose bin is guaranteed only at
  5 mA and which is the entire basis of the FA-9 experimental-first-article caveat.

Margin at the **unchanged** `Rin = 2k2`: `IF = 1.75 mA`, `IC ≥ 350 µA` vs the 56.2 µA sink
requirement = **6.2× guaranteed**, with **no `Rin` change and no copper change**. Even at a
pessimistic 15 % derate it is 4.7× — equal to the rev-C-era margin the board shipped with.

**Where it does NOT help:** it still **backfeeds the rail**. On the reverse half-cycle (or on
PBZ's steady +33 VDC) the second LED simply forward-conducts, giving the same self-consistent
solve as the clamp: `Vw ≈ 10.6 V at 9.6 mA`, dragging the shared rail for all 40 channels. So
PC814 removes the **LED-destruction** mechanism without removing the **shared-rail** mechanism.

**Status: candidate, NOT approved.** Before anyone relies on this: (a) confirm the pinout and
package drawing against the manufacturer PDF for the **exact** part number to be ordered, not
a distributor summary; (b) verify JLC stock/basic-part status; (c) bench one on a real board.
The figures above come from datasheet-derived sources located via search, not from a PDF read
end-to-end in this environment. **Whether to adopt it is Dylan's decision.**

## 5. What this actually buys, stated accurately

**With the provisions (fleet revision):** the cam-class survey, the brain-unplugged survey, and
the FOUL/GP/PBC classes become **stuffing decisions** rather than fab decisions. That is a
genuine schedule and rework saving **for the fleet order**.

**Without them:** for the **fleet** order, any channel that turns out to carry sustained AC
forces a respin. For the **first article** it does not — a prototype run can leave the affected
channels unlanded or use the harness mitigation below. Do not conflate the two (see the
corrected headline).

**Not a critical-path claim.** Per `phase8_metering_guide_harness_unknowns.md` the cam channels
were never on the critical path (Stop/CIS landing → output taps → Stage 6b → cams), and that
guide already records a fallback: **tap the cams at the switches and skip C2A for those four
channels.** These provisions improve the fleet build; they do not unblock the field campaign.

**Interim mitigation — this is what the first article should actually do:** series **1N4007 in
the harness lead**, cathode toward the machine, on **PBZ and both DIELL signals at minimum**;
or leave those three channels unlanded. It works, but it is per-channel, per-lane, undocumented
in the board BOM, and easy to lose across 32 lanes — so **record it per lane** in the
commissioning log. The first-article pack now carries a matching hard warning.

## 6. Related

- `phase8_revC_change_list.md` #6 (the original open item)
- `phase8_metering_guide_harness_unknowns.md` (cam ladder / sneak-path evidence; cold mapping closed as a method)
- `manual_src/19_safety-architecture.md` §19.2.1 field finding (Stop-only chain, DIELL role)
- Bench gates passed 2026-07-25: lamps 4/4, all six rail conditions drop TP16 independently, NE555 ≈10 s, max-run ≈9 s
