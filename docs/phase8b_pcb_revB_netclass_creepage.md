# Phase 8 Rev-B — Net Classes + Creepage/Clearance Policy (pre-routing)

**Status:** ROUTED + FAB-EXPORTED POLICY v0.2 (updated 2026-06-03). The routing contract: every net assigned to a class, each class given trace width + clearance + via rules, plus the isolation-barrier (creepage/clearance) policy between the three electrical domains. KiCad DRC classes and `wsl-phase8b.kicad_dru` derive from THIS doc. The first bare-PCB fab package in `kicad/fab_revB_routed_manual/` was exported under this conservative policy. Pairs with `phase8b_pcb_revB_spec.md` (§2 domains, §9 layout) + `phase8b_pcb_revB_BOM_power.md` (rails).

**Why this exists:** the routed board is only meaningful if every route and pour is checked against live netclasses and explicit domain-isolation rules. This policy fixes the net→class map + the domain isolation gaps so KiCad DRC catches a logic trace under a machine pad, a plane crossing a barrier, or a relay-coil rail necked too thin.

> **A1 field measurement landed at 24 VAC on the machine-output contacts, but the live DRC and fab package remain conservative until final 24 V policy numbers are explicitly chosen.** The structure below still uses conservative 250 VAC-derived defaults on the output/field domain so routing stays on the safe side; relaxing later is a DRC/policy edit, not a topology change. Logic + safety-rail classes are NOT gated by this.

---

## 0. The three domains (from spec §2) → the isolation map
| domain | nets (by name pattern) | reference | isolation requirement |
|---|---|---|---|
| **LOGIC** | VCC_5V*, VCC_3V3, GND, I2C_*, PI_UART_*, WDOG_*, ARM_PERMIT, RP2040_OK, MCP_INT_*, AND_*, FAST_*, SLOW_*, DRV_*, relay bases `BASE_S/T/SP/BE/M/M2/M1`, safety bases `BASE_AND_*`, `COIL_LO_*`, status LED nets `LED_*` | **GND** (logic) | the Pi-side world |
| **FIELD (machine-sense, ISOLATED)** | FIELD_* (34 nets incl. FIELD_WET_V, FIELD_GND) plus `FIELD_LED_*` opto LED series nets | **FIELD_GND** (isolated, NOT tied to GND) | isolation barrier vs LOGIC across every opto |
| **MACHINE OUTPUT** | OUT_*_A / OUT_*_B (relay contacts only), and relay-contact snubber midpoints `SNUB_*` | floating / machine-referenced | isolation barrier vs LOGIC across every relay |
| **SAFETY RAIL / CONTROL** | RELAY_ENABLE_RAIL, RAIL_GATE, `COIL_LO_*`, `BASE_AND_*`, **and the `SAFE_*` interlock-loop nets** (`SAFE_STOP_RETURN`, `SAFE_TBSC_RETURN`) | GND (logic-side coil supply) | logic-domain electrically; its own class for current + integrity. **The interlock loop gates the rail and sits adjacent to Q10/RAIL_GATE by design.** |

> ⚠️ **CORRECTION (2026-06-02, route-pass-1): `SAFE_*` moved out of MACHINE OUTPUT into SAFETY RAIL/CONTROL.** The v0 draft wrongly listed `SAFE_*` as machine-output, which forced the ≥3.2 mm LOGIC↔MACHINE creepage against the very rail/gate they're supposed to drive → 7 false DRC violations. `SAFE_STOP_RETURN`/`SAFE_TBSC_RETURN` are **low-voltage TB/SC interlock + Stop/CIS sense**, logic/rail-domain, NOT 250 VAC machine contacts. They take **logic-domain clearance**, not the machine isolation barrier. (Claude's classification error; caught by Codex's route-pass DRC.)

**The two isolation barriers that must never be bridged in copper:**
1. **LOGIC ↔ FIELD** — crossed only inside the PC817 opto packages (LED side = FIELD, transistor side = LOGIC).
2. **LOGIC ↔ MACHINE OUTPUT** — crossed only inside the G5LE relay packages (coil = LOGIC/rail, contact = MACHINE).
No trace, via, plane, or copper pour may shorten either barrier below the creepage spec in §3.

---

## 1. NET CLASSES (KiCad netclass definitions)
| class | trace width | clearance | via | nets assigned (pattern) | rationale |
|---|---|---|---|---|---|
| **Logic_Signal** | 0.25 mm | 0.20 mm | 0.6/0.3 | FAST_*, SLOW_*, DRV_*, I2C_*, PI_UART_*, MCP_INT_*, RP2040_OK, ARM_PERMIT, AND_*, NE555_*, WDOG_KICK*, WDOG_OK*, WDOG_TIMING_NODE, relay-driver bases `BASE_S`, `BASE_T`, `BASE_SP`, `BASE_BE`, `BASE_M`, `BASE_M2`, `BASE_M1`, and status LED nets `LED_*` | low-current digital; tight ok |
| **Logic_Power** | 0.50 mm | 0.20 mm | 0.8/0.4 | VCC_5V, VCC_5V_RAW, VCC_3V3, GND | rail current (relay coils on 5V) + plane returns |
| **Safety_Rail** | 0.60 mm | 0.30 mm | 0.8/0.4 | RELAY_ENABLE_RAIL, RAIL_GATE, `COIL_LO_*`, `BASE_AND_*`, `SAFE_*` | carries all 7 coil currents (~0.55 A); wider for integrity + a touch more clearance (safety-critical, keep clear of logic noise). `SAFE_*` is low-voltage rail/interlock control, not machine-output contact copper. |
| **Field_Sense** | 0.30 mm | **0.40 mm** | 0.7/0.35 | FIELD_FAST_*, FIELD_SLOW_*, FIELD_WET_V, FIELD_GND, `FIELD_LED_*` | isolated machine-sense; wider clearance because it's a separate ground reference + may carry 24 VAC-sense |
| **Machine_Output** | **0.50 mm** | **0.35 mm base; custom DRC enforces §3 barriers** | 1.0/0.5 | OUT_*_A, OUT_*_B, `SNUB_*` | switches machine control voltage (inductive); same-channel snubber/contact terminals are intentionally close, so independent-channel and LOGIC↔MACHINE spacing are enforced by `wsl-phase8b.kicad_dru`, not the base class alone |

Notes:
- **Anonymous `N$` nets have been eliminated.** Claude independently verified Codex's safety-relevant correction: the old `N$1`-`N$32` were field-side PC817 LED series nets and the old snubber midpoint nets were machine-output side, so a blanket `N$* -> Logic_Signal` rule would have been unsafe. Codex then renamed these in `scripts/generate_kicad_netlist_revB.py`; the regenerated netlist and board now have **0 anonymous `N$` nets**. Current explicit families: `FIELD_LED_*` x32, `SNUB_*` x7, `COIL_LO_*` x7, `BASE_*` x9, `LED_*` x12.
- **Machine_Output clearance is split deliberately:** the 0.35 mm KiCad netclass clearance is the same-channel local fabrication/routing floor. The real insulation constraints are custom rules: LOGIC↔MACHINE ≥3.2 mm and independent machine-output channel↔channel ≥1.5 mm. Same-channel terminals (relay contact pair or RC snubber across that pair) are reviewed exceptions because those component terminals are intentionally adjacent.
- **Minor (defensible either way):** `COIL_LO_*` carries coil current and is logic-domain. It is assigned to Safety_Rail here for current/noise integrity; folding it into Logic_Power would not affect isolation.
- Widths assume 1 oz copper, 4-layer. Safety_Rail 0.60 mm @ 1 oz ≈ 1.6 A capacity — 3× margin over the ~0.55 A coil load.

---

## 2. LAYER STACK + domain rooms (4-layer)
| layer | use |
|---|---|
| **F.Cu** | signal — logic signals + short field/output stubs into connectors |
| **In1.Cu** | **GND plane (logic)** — solid; the logic-domain return + shield. Voided under the isolation barriers + the FIELD/MACHINE rooms. |
| **In2.Cu** | power — VCC_5V / VCC_3V3 pours (logic side only) |
| **B.Cu** | signal — field-sense + machine-output routing kept on the bottom, away from the logic GND plane edge |
| **rooms** | LEFT = FIELD inputs · CENTER = LOGIC (Pi/MCP/RP2040) + SAFETY rail/watchdog + status LED drivers · RIGHT = MACHINE outputs (relays). Matches the placement. |

**Plane discipline:** the In1 GND plane and In2 power pour **must not extend under the FIELD or MACHINE OUTPUT rooms** — pour keepouts there (the isolation barrier is vertical too, not just lateral). This is the 4-layer version of rev-A's B.Cu keepout idea.

---

## 3. CREEPAGE / CLEARANCE POLICY (the isolation barriers)
Creepage = surface distance; clearance = through-air. For the LOGIC↔FIELD and LOGIC↔MACHINE barriers, both must be met across the opto/relay bodies AND any adjacent copper.

**Working-voltage assumption (conservative until measured): 250 VAC RMS, pollution degree 2, basic insulation.** Per IPC-2221 / IEC 60664 typical:
| barrier / situation | clearance (air) | creepage (surface) | policy number used |
|---|---|---|---|
| LOGIC ↔ FIELD (across PC817) | ~1.5 mm | ~2.5 mm | **≥ 2.5 mm** both |
| LOGIC ↔ MACHINE (across G5LE) | ~2.0 mm | ~3.2 mm | **≥ 3.2 mm** both |
| Machine-output trace ↔ any non-output copper | — | — | **≥ 2.0 mm** (DRC rule) |
| Machine-output trace ↔ board edge | — | — | **≥ 1.0 mm** |
| between independent machine-output channels | — | — | **≥ 1.5 mm** (one shorted channel must not arc to the next) |

- **Slots/cutouts under opto + relay bodies:** optional mechanical hardening only. The current fab package does **not** include milled isolation slots and does not rely on slots for its DRC pass; isolation is enforced by copper clearance, package spacing, and all-layer no-copper rule areas. If slots are added later, treat it as a mechanical board edit: rerun DRC, re-export gerbers/drill, and re-review the vendor preview.
- **If the at-machine measurement shows ≤ 30 VAC working** on the outputs (plausible if it's purely 24 VAC control), these numbers can relax substantially (functional insulation, ~0.5–1 mm) — but **start conservative; relaxing later is a DRC edit, tightening after routing is a re-route.**

---

## 4. ROUTING RULES (FreeRouting / manual)
1. **Never** route a Logic_* net into the FIELD or MACHINE rooms, or vice-versa, except the pins that legitimately enter the opto/relay body.
2. **Machine_Output** nets route in the right room, short and direct to the function-named `J_MOTION_*` 2-pin terminal for that channel; keep each channel's A/B pair together; snubber/MOV footprints adjacent to the contact.
3. **Safety_Rail** routes as a clean spine from the watchdog/pass-FET to all 7 relay coil + pins; no stubs, no necking; keep it off the board edge and away from FIELD/MACHINE copper.
4. **I2C** (SDA/SCL) short, matched-ish, away from the relay-coil switching + the UART; pullups (R1/R2) near the Pi header.
5. **FAST_* cam inputs:** the opto→Pico path short + direct (the OEM-audit debounce/latency budget — no slow RC, no long noisy runs).
6. **Status LED nets** (`LED_*`) stay in the LOGIC room and route to J_LAMP_LED; they do not enter the MACHINE room.
7. **No copper pour** bridges an isolation barrier (see §2 plane discipline).

---

## 5. PRE-ROUTE VERIFICATION (run before routing)
A script should confirm, on `wsl-phase8b.net`:
- [ ] every net maps to exactly one class (no unclassified net).
- [ ] regenerated netlist contains **0 anonymous `N$` nets**.
- [ ] every named net maps to exactly one class using `phase8b_revB_netclass_inventory.md`.
- [ ] FIELD_GND and GND are distinct nets with zero shared nodes (isolation intact).
- [ ] every OUT_*_A/B net touches a relay contact pin + a connector pin ONLY (no logic pin).
- [ ] RELAY_ENABLE_RAIL touches only coil + pass-FET + flyback pins (no signal pins).
→ I can write this as `scripts/verify_netclass_revB.py` next.

---

## 6. WHAT THIS DOC DECIDES vs DEFERS
**Decides now (routing can start):** net→class map, trace widths, layer stack + rooms, plane keepouts, routing rules, the barrier *structure*, conservative creepage numbers.
**Defers (confirm, then DRC-edit — does NOT block starting):**
- Final creepage numbers ← machine-output working voltage (at-machine, `BOM_power §6`).
- Snubber/MOV values ← measured inductive load.
- Whether Field_Sense needs the 24 VAC clearance on ALL channels or only the AC-populated ones (per-channel dry/AC population is also at-machine).

## 7. NEXT
1. For any board edit, rerun `scripts/apply_netclasses_revB.py --write`, `scripts/manual_route_revB.py`, and `scripts/export_fab_revB.py`.
2. Do the vendor Gerber/drill upload preview against `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip`.
3. Optional future shrink: fold in at-machine 24 VAC working voltage, relax the `.kicad_dru` policy, re-DRC, then re-export.
