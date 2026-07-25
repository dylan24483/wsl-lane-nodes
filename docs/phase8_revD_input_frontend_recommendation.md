# Rev-D Recommendation: Per-Channel Input-Protection Provisions (DNP)

**Written 2026-07-25 from measured field evidence on lane 22.** Owner: rev-D workstream.
**Status: RECOMMENDED BEFORE FAB.** This is the single change that moves the remaining field
campaign OFF the critical path to a fleet order.

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

## 2. The measured evidence (lane 22, 2026-07-18/21)

| Channel(s) | Measured under OEM power | Reverse bias vs our ~11 V wetting rail | Verdict |
|---|---|---|---|
| GS1–GS10, BS | **11 VDC** dry | ~0 V | safe bare |
| **PBZ** | **33 VDC** (rectified-24 VAC class) | **≈22 V — 3.7× the 6 V limit** | **would destroy that channel's LED** |
| **DIELL-L/R signal** | **15.4–16 V** at rest (DIELL board self-powers) | ≈5 V | **no margin**; likely permanent (survives brain removal) |
| DIELL board middle block | **42 VAC** | — | machine/VDB interface, never tapped |
| **SA · SB · TA1 · TA2 (cams)** | **UNMEASURED** | unknown | cam contacts sit **in series in the machine's 24 VAC relay ladder** (proven by the ~21 Ω coil sneak paths that invalidated two cold-mapping attempts) → **AC exposure is the prior, not the exception** |
| FOUL (lamp wire), GP, PBC | unmeasured | unknown | classes still open |

Change-list item **#6** already anticipated this: *"per-channel input front-end: dry-contact vs
24 VAC-rectified sense… **may change population/BOM per channel**."* It remains unresolved in
rev-D.

## 3. Recommendation — three DNP footprints per input channel

All unstuffed by default; population decided per channel once each line's class is measured.

| Provision | Purpose | Notes |
|---|---|---|
| **Series blocking diode** (1N4148/1N4007 class) | Blocks DC over-voltage; reverse appears across the diode, not the LED | Costs ~0.7 V of forward drive — see §4 |
| **Anti-parallel clamp diode** across the LED | Clamps reverse to ~0.7 V with **zero** forward-current penalty; also the classic cheap **AC-sense** front-end (opto pulses at line rate) | Preferred where reverse protection alone is needed |
| **Filter cap** on the slow-input logic side | Integrates an AC channel's pulse train into a steady level so MCP reads don't chatter | Fast (RP2040) channels may prefer edge counting instead |

## 4. Interaction with the PC817 CTR finding (must be designed together)

The Codex audit flags PC817B margin as thin — the guaranteed CTR bin applies at 5 mA/5 V/25 °C
while the design operates near **1.7 mA**, and rev-D already added a 47 k collector pull-up to
lower the MCP sink requirement to ~56 µA in compensation.

**A series blocking diode makes that worse** (~0.7 V less LED drive). Series protection and LED
margin pull against each other. The resolution — anti-parallel clamp only, series diode with an
`Rin` retune, or a different optocoupler — is a **design decision for the rev-D workstream with
the field numbers in hand**, not a default to be inherited by accident.

## 5. Why this is the highest-leverage pre-fab change

**With the provisions:** the cam-class survey, the brain-unplugged survey, and the FOUL/GP/PBC
classes all become **stuffing decisions** made before those channels are landed. The fleet board
order proceeds on its own schedule.

**Without them:** any channel that turns out to carry sustained AC forces a **respin**, and the
fleet order is hostage to at-machine metering that is itself gated on cutover-day access.

Interim mitigation if the provisions do not land: temporary **series 1N4007 in the harness lead**
per affected channel (PBZ and both DIELL signals at minimum), cathode toward the machine. Works,
but it is per-channel, per-lane, undocumented in the board BOM, and easy to lose across 32 lanes.

## 6. Related

- `phase8_revC_change_list.md` #6 (the original open item)
- `phase8_metering_guide_harness_unknowns.md` (cam ladder / sneak-path evidence; cold mapping closed as a method)
- `manual_src/19_safety-architecture.md` §19.2.1 field finding (Stop-only chain, DIELL role)
- Bench gates passed 2026-07-25: lamps 4/4, all six rail conditions drop TP16 independently, NE555 ≈10 s, max-run ≈9 s
