# Phase 8 Rev-B — BOM + Power Architecture (the pre-SKiDL parts contract)

> ⛔ **FROZEN REV-B DESIGN RECORD — NOT CURRENT WIRING OR CUTOVER AUTHORITY.**
> Preserve this file for its 2026-06 parts/power rationale, but do not follow its
> B1 TB/SC→J_SAFETY conclusion. Later evidence proved no dry/independent TB pair:
> powered 2026-07-07 established an OEM parallel closed-when-safe ladder, with both
> levers BACK/open killing S and T. Current lane-21/22 implementation is Candidate C
> (controlled J_SAFE1-2 jumper + preserved OEM ladder + per-lane G3 S/T coil proof).
> Use `phase8_interlock_redesign.md`, the lane harness build sheet, and the Track-B
> cutover runbook. Firmware v1.2.3 measured-cam and SC∧TB echo enforcement flags
> remain OFF.

**Status:** DRAFT v1.1 (2026-06-02). Updated after the corrected Rev-B SKiDL scaffold and Dylan's logic-driven mask LED decision. Resolves the relay footprint/current, status LED source, isolated wetting supply, Pi-safe I2C voltage, and valid KiCad-footprint blockers into concrete part recommendations plus the power-rail plan.

**Rule:** recommendations here are **schematic-stable** (lets us build a stubbed netlist) but **NOT fab-locked** until the at-machine current/voltage measurements land (called out per item). Footprints follow rev-A conventions (KiCad stock libs; see `generate_kicad_netlist.py` header).

---

## 1. POWER RAILS (per board)
| rail | source | feeds | notes |
|---|---|---|---|
| **+5V logic** | external regulated 5V (DIN PSU **HDR-15-5** or Pi 5V) — **no on-board PoE in v1** | Pico VSYS, NE555, relay coils, isolated wetting DC/DC primary | rev-A-style SS14 reverse-polarity Schottky on input. Size for worst-case: all relay coils ON + logic + margin (see §2.4). |
| **+3V3 logic** | Pico module 3V3 output in the corrected scaffold; use a dedicated regulator only if bare RP2040 replaces the stamp module | Pico logic rail, 3× MCP23017, opto logic pull-ups, I²C pull-ups | MCP23017 must be on 3.3 V for Pi-safe I²C. Do not run MCP23017 at 5 V on the Raspberry Pi I²C bus without level shifting. |
| **isolated field-wetting V** | **on-board isolated DC/DC** from +5V (§3 below) | dry-contact input front-ends only | galvanically isolated from logic GND (spec §8.3 option 1). |
| **machine 24V (coil)** | **the machine's own T2/T3/T4** — NOT board-generated | nothing on-board sources it; relay *contacts* switch it externally | board only closes dry contacts in the existing 24V coil circuits. |

**Key principle (locked by contract):** the board generates **logic rails (5V/3V3), the isolated wetting supply, and status LED current from the logic 5V rail.** It does NOT generate 24V machine coil power or use the machine's old mask-lamp supply; machine motion/control voltages remain external and are switched only through isolated relay contacts.

---

## 2. BLOCKER 1 — RELAY (motion outputs S/T/SP/BE/M[/M1/M2])

### 2.1 What it must do
Close/open an **isolated dry contact** in an existing **24V machine control/coil circuit**. It does NOT carry motor current. So the contact rating need only cover the **contactor-coil/control current** of the OEM relays it commands.

### 2.2 Current estimate (pre-measurement)
From bench coil resistances + 24V: S(Siemens 24VAC,5Ω)→ inrush-ish but it's the *machine's* contactor we switch in series, not the coil directly; the **control current we interrupt** is the holding current of the OEM control circuit. Native coils 22–100Ω @24V ⇒ ~0.25–1.1A DC-equiv per coil; AC contactor coils can pull higher inrush. **Budget the contact for ~2A @ 30VDC / ~0.5A @ 250VAC inductive with derating.** ⚠️ **CONFIRM at-machine:** measure actual coil/control current draw on S/T/SP/BE/M (audit open item #1) before fab-lock.

### 2.3 Recommended part
**Through-hole signal/power relay, SPDT, 5V coil, ≥2A AC/DC contact, with flyback-friendly footprint:**
- **Primary rec:** **Omron G5LE-14 DC5** (SPDT, 10A contact — generous headroom, ~1A coil... wait: G5LE coil ~79mA@5V) — common, cheap, JLCPCB-stocked, well-characterized for inductive control loads. Contact 10A is overkill but gives huge margin + one common footprint across all outputs (spec §3.2 "prefer common footprint class").
- **Alternative (smaller/quieter):** **Panasonic/Omron PhotoMOS or G3VM SSR** if silent + no-moving-parts wanted — BUT SSRs are polarity/AC-type sensitive and the contract wants true dry contact; G5LE keeps it simple + truly dry. **Stick with G5LE for v1.**
- **Coil drive:** logic → **opto (e.g. on rev-A-style)** → small NPN/MOSFET → G5LE 5V coil, with **flyback diode (1N4148/1N4007) across coil** + the coil-supply downstream of the **relay-enable rail**.
- **Footprint:** G5LE THT (KiCad `Relay_THT:Relay_SPDT_Omron-G5LE-1`). One class for S/T/SP/BE/M/M2; M1 DNP.

### 2.4 Coil-load budget for the 5V rail
7 relay footprints (M1 DNP unless verified) × ~79mA (G5LE 5V) ≈ **0.55A** worst-case if all populated + logic/wetting margin → **5V rail ≥ 1.5A** minimum, with HDR-15-5-class 3A supply preferred.

### 2.5 Snubber/MOV (per spec §2.3)
Each motion-output contact: footprints for **RC snubber** (e.g. 100Ω + 10nF/X2 across contact) **+ MOV** (e.g. S14K…/appropriate clamp), **DNP by default**, populate after at-machine load characterization. These protect the contact arcing into the inductive OEM coil.

---

## 3. BLOCKER 2 — ISOLATED FIELD-WETTING SUPPLY

### 3.1 What it must do
Dry-contact inputs (grippers, cams-as-dry, switches) need a **wetting voltage** to sense contact closure — and per spec §8.3 it must be **isolated from logic GND** (so a machine-side short can't backfeed the Pi).

### 3.2 Recommended part
- **Isolated DC/DC brick, 5V→5V (or 5V→12V), ~1W, ≥1.5kV isolation:** e.g. **B0505S-1W** (or **B0512S-1W** if 12V wetting preferred). Cheap, tiny, JLCPCB-stocked, standard.
- Output → the field side of the opto front-ends as the wetting rail; its return is **FIELD-GND**, kept separate from LOGIC-GND in layout (spec §2 domains).
- One brick feeds all dry-contact input channels (10 grippers + GP/OS/BS + manual + any dry cam) — total wetting current is tiny (opto LED ~5–10mA × however many are closed at once; realistically <100mA). 1W is ample.

### 3.3 Note on the two input front-end flavors
- **Dry-contact channels:** wetting-V → contact → opto LED → FIELD-GND. (Most grippers/switches.)
- **24VAC-sense channels:** rev-A interposer style (1N4007 half-wave + 10µF/63V + 100k bleed) → opto. (Foul, 2nd-ball, any AC cam.)
- **Per spec §2.2 + §5.1:** each input channel is **population-selectable** dry-vs-AC. Default per channel set after at-machine (cam rails unconfirmed). The wetting brick serves the dry option; the interposer serves the AC option.

---

## 4. DECIDED — MASK STATUS LEDs (1st/2nd/strike/foul)

### 4.1 What it must do
Drive 4 status indicators mounted in the existing mask housings. These indicators are **not motion-critical** and are not on the safety rail.

### 4.2 Implemented approach
**Dylan's decision (2026-06-02): install our own LEDs in the mask housings, driven from board logic DC.**

- `J_LAMP_LED` is a 6-pin connector: pin 1 `VCC_5V`, pin 2 `GND`, pins 3-6 `LED_L_FIRST_RETURN`, `LED_L_SECOND_RETURN`, `LED_L_STRIKE_RETURN`, `LED_L_FOUL_RETURN`.
- Each channel is `DRV_L_* -> 1k gate resistor -> 2N7002-class low-side FET`, with a 100k gate pulldown and a per-channel series/current-limit resistor (`Rled_*`, currently **330R TBD**) feeding the LED return.
- No machine 15V lamp supply is used. No AQY/PhotoMOS lamp switches are populated. No `OUT_L_*` machine-output lamp nets exist in the current netlist.
- Open field sizing item: choose LED type/current for brightness in a lit center, then lock the `Rled_*` values. The old machine lamp current is irrelevant because the old lamps are not driven by this board.

---

## 5. CORE LOGIC DEVICES (no blocker — standard parts)
| device | part | footprint | notes |
|---|---|---|---|
| RP2040 | RP2040 + W25Q128 flash + 12MHz xtal | QFN-56 | needs 3V3; USB-boot + SWD pads; cam-stop + UART. Or **RP2040 stamp module** (e.g. RP2040-Tiny) to simplify v1 layout — **recommend stamp module for v1** to de-risk the QFN. |
| MCP23017 ×3 | MCP23017-E/SO | SOIC-28 | IN-A 0x20, IN-B 0x21, OUT-A 0x22 (OUT-B 0x23 DNP). Powered at 3.3 V; I²C addr-strapped. |
| NE555 watchdog | NE555D + AO3400 + passives | rev-A carryover | reuse rev-A topology exactly incl. R2 TRIG pullup. |
| opto inputs | (rev-A AL-ZARD-class opto, now on-board) | per channel | edge-capable for fast cams; no slow RC on SA/SB/SC/TA1/TA2/TB (audit §3). |
| 3V3 source | Pico module regulator in scaffold; AP2112K-3.3/NCP1117-3.3 if bare RP2040 later | module/regulator footprint TBD | powers MCP23017, opto logic pullups, and I²C pullups. |
| I²C | 4.7k pullups ×2 (this board's bus) | 0402/0603 | one bus per board. |

> **RP2040 v1 recommendation: use a stamp module** (pre-made RP2040+flash+crystal) rather than bare QFN-56. Cuts the hardest placement/routing risk on an already-big board; go bare-QFN in a later cost-down rev once the design is proven. Flag for Dylan.

---

## ✅ AT-MACHINE MEASUREMENTS LANDED (2026-06-02, Dylan) — fab-lock inputs
- **A1 — machine-output working voltage = 24 VAC on all accessible relays** (S, T, BE, M, M2 confirmed; **SP presumed 24 VAC** — coil terminals inaccessible, but its bench coil = 100 Ω native 24 V + same T2/T3/T4 supply + every other relay = 24 VAC → well-supported; glance-confirm at cutover). ⭐ **DESIGN IMPACT: the conservative 250 VAC creepage assumption is REPLACED by 24 VAC working.** LOGIC↔MACHINE + LOGIC↔FIELD barriers can relax from ≥3.2 / ≥2.5 mm toward **functional-insulation ~0.5–1.0 mm** (24 V, pollution degree 2). → smaller gutters, smaller/cheaper board, easier route. **Update `phase8b_pcb_revB_netclass_creepage.md` §3 + `wsl-phase8b.kicad_dru` to the 24 V numbers before final route-lock.**
- **A3 — old mask status-lamp supply = 15 VDC** (not the 12 V the manual implied — measured). Current was not taken, and it no longer gates the PCB because Rev-B abandons the old machine lamp supply and drives new LEDs from the board's logic 5V rail.
- **A4 — cams are DRY CONTACTS** (tested a cam lever switch: ~0 Ω closed at rest, opens when lever moved off the lobe; no applied voltage → dry switch, and **normally-closed** at rest). → cam input front-ends use the **dry-contact wetting** path, NOT the 24 VAC-sense path. Default population for the 6 cams = dry. (Grippers/other switches expected dry too; confirm per channel at cutover, but dry is now the confirmed default.)

## PART B SAFETY RESULTS (2026-06-02, from OEM docs + field)
- **B3 — Stop/CIS chain: ANSWERED from OEM service manual p11** (no probing needed). The **Stop Switch** (red button, left of power plug) and the **C.I.S.** (plug-duct cover switch) are **wired in PARALLEL** and BOTH **cut the master circuit breaker in the rear control panel** → whole machine dead. This is the hardware safety chain we preserve UPSTREAM of our board, exactly as the spec assumed. ✅
- **B1 — TB/SC interlock: ANSWERED at design level; terminal landing DEFERRED to cutover.** OEM (svc p71 "cams/switches control... interlock protection (TB & SC)" + the 9807 MP schematic) confirms **TB + SC are wired in parallel into the 24 V control path; on a table/sweep collision course the interlock removes controlling voltage** → both motor relays drop. Our `J_SAFETY` is designed to accept exactly this (a normally-closed series safety loop). **The exact terminals differ on our SS+Omega-Tek chassis vs the OEM 9800-MP** (same chassis-divergence we hit on M2/S cavities), so the precise J_SAFETY landing is a **cutover-day wiring task** — far easier with the machine partially apart for the swap than reaching behind a live one. Design is NOT blocked; only the field harness landing waits.
- **B2 — cam-stop logic-vs-hardwired:** still the deferred-to-cutover item (cam-flip test); not a design gate (we add HW end-stops + RP2040 timing regardless). Leans LOGIC.

## 6. WHAT'S STILL `# CONFIRM` AT-MACHINE (gates fab, NOT the stubbed netlist)
1. **S/T/SP/BE/M coil-control current** → final relay contact rating (§2.2).
2. **Mask LED brightness/current** → final LED choice and `Rled_*` current-limit value (§4).
3. **TB/SC interlock electrical form** on our chassis → how it series-wires into the rail.
4. **Cam input rail** (dry vs 24VAC) → per-channel default population.
These are measurements, not design unknowns. The stubbed netlist can proceed with the recommendations above; fab-lock waits on these.

## 7. CURRENT SKIDL CHECK
The corrected scaffold is `scripts/generate_kicad_netlist_revB.py` -> `kicad/wsl-phase8b.net`: G5LE relays, TMA-0505S isolated wetting, logic-side 2N7002 status LED drivers, Pico stamp module, 3x MCP23017 on 3.3 V, NE555 watchdog, and safety-rail gating. Current generated netlist/board state: **210 netlist components, 184 nets, no AQY/PhotoMOS lamp switches, no `OUT_L_*` nets, 0 DRC violations after placement/netclass apply**. It is architecture/connectivity-complete for paper audit, but fab-lock still waits on §6 measurements and placement/routing review.
