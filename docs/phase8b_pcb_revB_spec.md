# Phase 8 - PCB Rev-B Schematic Contract

> ⛔ **FROZEN REV-B ELECTRICAL CONTRACT — NOT CURRENT FIELD-WIRING OR CUTOVER
> AUTHORITY.** The PCB topology and fabrication record below are retained as
> historical evidence. Its external TB/SC J_SAFE1-2 loop and v1.1-era operational
> assumptions are superseded. Lane 21/22 uses Candidate C: a controlled J_SAFE1-2
> jumper, the powered-proven OEM parallel closed-when-safe S/T coil ladder, and a
> mandatory per-lane G3 S-and-T coil-drop insertion proof. Use
> `phase8_interlock_redesign.md`, the lane harness build sheet, the current
> `manual_src/`, and the Track-B cutover runbook for Rev-D work.

**Status:** CONTRACT + ROUTED REV-B FAB PACKAGE (2026-06-03, OEM doc-audited, logic status-LED decision implemented). This is the hard electrical contract plus the current routed/manual KiCad board and bare-PCB fab package. It is PCB-fab-ready under the conservative DRC contract, but not assembly/cutover-ready.

**Scope unit:** one PCB controls one lane. A lane pair uses two identical PCBs on one Raspberry Pi. The camera may be shared by the pair; all machine-control wiring is per lane.

**Supersedes where conflicting:** `pcb_design_spec.md`, `phase8_io_board_spec.md`, and `phase8_channel_allocation.md` sections that still describe a carrier board plus external AEDIKO/AL-ZARD modules. Rev-B is a fully integrated board.

**Non-negotiable safety rule:** this board must never be treated as the only safety device. The existing Stop/CIS/master breaker chain remains upstream, live motor current stays on the machine contactors, and the board must fail open on loss of logic, watchdog, RP2040 health, arm permission, or the hardware interlock.

**OEM audit note:** `phase8_oem_doc_audit_2026-06-02.md` records the full OEM/OmegaTek document pass and Claude's OEM-vs-bench reconciliation. The main schematic-contract impacts are: S/T outputs must only command existing contactor/control circuits, TB/SC is OEM-confirmed as a hardware interlock, fast cam inputs need a bounded debounce/latency budget, and M2/sweep-reverse cavity routing is chassis-specific/harness-resolved. OEM docs show a C1/TSA/Expander path; our SS + Omega-Tek bench measured M2 at C2A.

**CORRECTED NETLIST + ROUTED FAB PACKAGE GENERATED (2026-06-02 through 2026-06-03):** `scripts/generate_kicad_netlist_revB.py` -> `kicad/wsl-phase8b.net`. **216 schematic components, 184 nets, 0 SKiDL errors.** Verified against local KiCad 10 footprints with no missing footprints. The scaffold now wires the previously orphaned paths: fast optos -> Pico GPIOs, slow optos -> MCP23017 GPIOs, MCP outputs -> relay drivers and logic status-LED drivers, relay contacts -> seven function-named 2-pin `J_MOTION_*` terminal blocks plus DNP snubber/MOV footprints, J_LAMP_LED -> VCC_5V/GND/four LED returns, J_SAFETY -> relay-enable rail source, and the Rev-A-style NE555 watchdog -> rail AND chain. **Safety rail verified in the board:** RELAY_ENABLE_RAIL reaches all 7 relay coils (including M1 DNP), flybacks, pass-FET, and TP16; ARM_PERMIT, RP2040_OK, and watchdog OK are a real series pull-down chain; MCP23017 banks and I2C pullups are on 3.3 V, not 5 V. **Current route/fab gate:** routed-manual board passes netclass-aware KiCad DRC with **0 violations / 0 unconnected pads / 0 footprint errors** and `scripts/audit_revB_board.py` reports **ALL PASS**. `scripts/export_fab_revB.py` regenerated DRC/audit for fab export and produced `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip` plus `kicad/fab_revB_routed_manual/wsl-phase8b-revB-fab-package.zip`. **PCB-fab-ready under current conservative DRC:** remaining work is uploaded Gerber preview/human manufacturing review, component ratings/population/assembly, enclosure/mechanical fit, bench validation, and cutover readiness.

> **Codex fab-prep pass (2026-06-03):** Added `scripts/export_fab_revB.py` and generated `kicad/fab_revB_routed_manual/`. The package contains gerbers, Excellon PTH/NPTH drills, board stats, IPC-D-356 netlist, review PDF, grouped non-DNP BOM, CPL, DNP/excluded CSV, README, manifest with SHA256s, and zipped upload packages. Export gates repeat KiCad DRC (**0/0/0**) and board audit (**ALL PASS**) inside the package. DNP handling was corrected so all value-DNP suppression footprints are flagged DNP/excluded in KiCad; current package count is **189 non-DNP BOM refs / 27 DNP refs / 20 non-DNP mechanical-test refs excluded from assembly files**. Front silkscreen now carries board ID/rev, domain labels, connector/function labels, and the `J12 M1 DNP` callout. The package does not include milled opto/relay slots; its isolation proof is the conservative copper-clearance and all-layer keepout DRC, not slot-boosted creepage.

> **Codex routed corrective pass (2026-06-03):** Claude correctly caught a false-green route where the routed `.kicad_pro` lost netclass assignments, making `.dru` `hasNetclass()` rules inert. Codex fixed the route workflow to copy project/rule sidecars and fail closed unless the routed board resolves all 184 named nets into the expected classes (80/4/13/66/21). J_MOTION was split from one dense motion block into seven 2-pin function terminals, Machine_Output base clearance was set to 0.35 mm while the custom rules still enforce independent output-channel 1.5 mm and LOGIC-to-MACHINE 3.2 mm spacing, and the remaining safety/watchdog conflicts were rerouted. Live proof is `kicad/DRC-revB-routed-manual-classed.rpt` plus `scripts/audit_revB_board.py`.

> **Route pass 1 corrective pass + placement re-band complete; full-board FreeRouting rejected; logic status LEDs implemented (2026-06-02, superseded by the 2026-06-03 routed corrective pass above):** Codex applied Claude's audit rulings and reran the KiCad pre-route checks. `SAFE_*` moved from Machine_Output to Safety_Rail, Machine_Output uses a split base/custom clearance model while `kicad/wsl-phase8b.kicad_dru` enforces the real LOGIC-to-MACHINE / LOGIC-to-FIELD / independent-output barriers, and the motion output connector topology is now seven function-named 2-pin terminals. Dylan then chose board-driven LEDs in the mask housings; Codex removed the old isolated lamp-output stage and regenerated J_LAMP as a 6-pin logic LED connector. Current net-class counts: Logic_Signal 80, Logic_Power 4, Safety_Rail 13, Field_Sense 66, Machine_Output 21. Claude then correctly identified overlapping FIELD/LOGIC/MACHINE placement rooms as the real routing blocker; Codex re-banded the board into FIELD, LOGIC, and MACHINE domains with explicit all-copper keepout gutters and exported `kicad/wsl-phase8b.revB-reband.dsn`. The FIELD/LOGIC keepout now sits between the PC817 field and logic pad columns (not on top of a pad column) and was routeability-tested on a temporary board. DRC reports **0 violations** plus the expected **488 unconnected pads** on the source board. Earlier full-board FreeRouting candidates remain rejected: 4-layer route = **473 DRC violations + 3 unconnected**, F/B-only route = **625 DRC violations + 3 unconnected**. Re-band FreeRouting attempts produced no `.ses` after extended runs; manual deterministic routing is now the accepted path. See `phase8b_revB_route_pass1_findings.md`.

> **Codex net-class inventory addendum (2026-06-02):** `phase8b_revB_netclass_inventory.md` maps all **184 nets** into policy-neutral domains and found **0 unknown/unclassified nets**. Claude independently verified Codex's safety-relevant correction that blanket `N$* -> Logic_Signal` was unsafe; Codex then removed the fragility at source by renaming the anonymous nets in `scripts/generate_kicad_netlist_revB.py`. Current regenerated netlist/board have **0 anonymous `N$` nets**. Explicit families now drive net-class policy: `FIELD_LED_*` = field-side opto LED series, `SNUB_*` = machine-output snubber midpoints, `COIL_LO_*` = relay coil low-side, `BASE_S/T/SP/BE/M/M2/M1` and `LED_*` = logic-side drive locals, `BASE_AND_*` = safety-chain base locals. Current board counts including test pads: `GND` = 92 nodes, `FIELD_GND` = 6 nodes, `RELAY_ENABLE_RAIL` = 16 nodes including TP16.

> **Net-class + creepage/clearance policy written (2026-06-02):** `phase8b_pcb_revB_netclass_creepage.md` — the routing contract. 5 net classes (Logic_Signal/Logic_Power/Safety_Rail/Field_Sense/Machine_Output) mapped to all 184 nets; 4-layer stack + domain rooms + plane keepouts under the isolation barriers; live DRC remains conservatively sized for 250 VAC working (LOGIC↔FIELD ≥2.5mm, LOGIC↔MACHINE ≥3.2mm, output↔output ≥1.5mm) even though A1 field measurement landed at 24 VAC. The current fab package uses copper spacing + keepouts only, with no milled opto/relay slots; slots remain an optional future mechanical-hardening pass that would require re-DRC/re-export. Formal relaxation to 24 V numbers is a policy/DRC edit before a future production shrink, not a topology blocker. Premises verified against the current board: GND(92)/FIELD_GND(6) share 0 nodes including test pads (isolation intact), no OUT_* touches the Pico, RELAY_ENABLE_RAIL touches the 7 coils + flybacks + pass-FET + TP16. Routing derives from this doc plus `phase8b_revB_netclass_inventory.md`.

> **Claude re-audit of the COMPACTED placement (2026-06-02): VERIFIED PASS; M1 DNP correction rechecked by Codex.** Confirmed on the actual board file: **Edge.Cuts = 250x225mm** (down from 360x340; ~52% area cut), **4 copper layers**, **226 footprints**, domain grouping preserved, **0 DRC** at placement density. Claude's board-size objection is resolved. Codex rechecked the final regenerated board both by literal board-file tokens and KiCad API: the M1 optional channel (K7/Q7/R85-R87/D13/D14/C10) carries `dnp` + `exclude_from_bom` + `exclude_from_pos_files` on all 8 footprints. **Claude FINAL-PASS re-verified this independently (2026-06-02) and confirms Codex is correct + Claude's own earlier "zero dnp" claim was WRONG** — the dnp flag is a keyword INSIDE the `(attr ...)` line in KiCad 10 (`(attr through_hole exclude_from_pos_files exclude_from_bom dnp)`), not a standalone `(dnp yes)` sexpr; Claude's earlier token search used the wrong pattern. M1 exclusion is fully correct. Historical status at this placement checkpoint: routing, net classes, creepage/clearance, enclosure fit, at-machine measurements, gerber review, and silkscreen were still open; this is superseded by the routed fab package above.

> **Placement scaffold corrected after Claude audit (`place_components_revB.py` -> `wsl-phase8b.kicad_pcb`, 2026-06-02): PASS at the placement checkpoint.** Claude's board-size objection was correct: the first 360x340mm placement was a spread-out scaffold, not a usable layout. Codex compacted the deterministic tag-based placement to **250x225mm, 4 copper layers** with the same functional domains (field inputs left, logic/safety center, relay outputs right, logic LED drivers in the lower logic band), regenerated the board from the corrected netlist, and reran KiCad DRC. Current regenerated board: **230 footprints** (210 netlist + 16 test pads + 4 mounting holes), **0 DRC violations**, **488 unconnected pads** (expected because the board is intentionally unrouted). M1 optional channel now carries all three assembly guards on the board file: **DNP + exclude_from_bom + exclude_from_pos_files** for K7/Q7/R85-R87/D13-D14/C10. Default reference text is moved to F.Fab and value text hidden for this scaffold so silkscreen noise does not mask real placement/clearance errors. This closed Claude's two placement follow-ups; later routing/fab status is recorded above.

> **Claude independent audit of Codex's corrective netlist pass (2026-06-02): VERIFIED PASS on the pre-status-LED scaffold.** Codex's P0 findings against Claude's first netlist were CORRECT — that netlist generated cleanly but inputs/outputs/connectors were islands ("generates" ≠ "wired"; Claude over-claimed "connectivity complete"). Codex's corrective pass was re-audited independently on Claude's SKiDL env and HELD at that checkpoint: **206 components / 184 nets / 0 SKiDL errors / 20 unique footprints all resolving in KiCad 10 (0 missing) / ZERO empty nets / ZERO single-node dangling nets** (the ERC-class invariant that was false before). Spot-verified end-to-end: FAST_SA→Pico(A1.9)+opto+pullup; SLOW_GS1→MCP(U1.21)+opto+field-connector; DRV_S→MCP(U3.21); OUT_S_A→relay COM(K1.3)+connector(J6)+snubber+MOV; SAFE_STOP_RETURN→pass-FET(Q10.2)+connector(J8) [interlock now in series with rail, not bypassed]; RELAY_ENABLE_RAIL→all 7 coils; MCP23017 ×3 all on VCC_3V3 (not 5V) with I2C pullups [Pi-safe]; NE555 watchdog timing wired. This was a scaffold checkpoint; the current routed/fab package status is recorded above.
>
> **Claude review of Codex's earlier (contract) pass (2026-06-02): ACCEPTED as working contract.** Codex's changes are real improvements, not just polish — notably: (1) **RP2040-OK is now a first-class safety-rail condition** (§4.1/§4.2) — its health gates motion, not just its events; (2) **welded-contact limitation** documented (§4.5) — rail drops coils, can't open a welded contact → breaker is final stop; (3) **output topology locked to on-board isolated dry-contact relays** (§3.1), no direct MOSFET/ULN/triac coil-drive → preserves AEDIKO property + sidesteps AC/DC coil-drive entirely; (4) **3 explicit electrical domains + isolated field wetting** (§2/§8.3); (5) **snubber/MOV footprints on every motion output** (§2.3). Also locks 4-layer + no-PoE-v1 + function-named harness (resolves the machine-gated C2A binding problem cleanly).
> **One Claude amendment:** **M1 (ball return) -> POPULATE-OPTIONAL, not baseline.** We never bench-confirmed M1 exists as a separate relay on our chassis; the FSM doesn't drive it. The corrected netlist keeps the M1 relay/snubber/MOV/connector pair as DNP optional copper only; do not populate or harness it until verified at-machine. (Applied to §3.2 table.)

---

## 1. Rev-B Baseline Decisions

These are locked for schematic work unless Dylan explicitly changes them before netlist generation.

| item | Rev-B contract |
|---|---|
| Board count | One identical board per lane. |
| Board role | Replace the Omega-Tek/AEDIKO-style controller function for one lane. |
| Output topology | On-board isolated dry-contact relay outputs. No external AEDIKO module. |
| Machine coil power | Not generated by the PCB. The board only opens/closes isolated contacts in existing machine control circuits. |
| Motor power | Never routed through the PCB. S/T machine contactors continue to switch motor current and preserve their OEM run/braking contact behavior. |
| Safety rail | Gates the on-board output-relay coil supply/return, not the machine control voltage itself. |
| Fast timing | RP2040 owns cam/DIELL fast inputs, cam-stop enforcement, and UART event forwarding. |
| Slow I/O | MCP23017 banks for grippers, switches, lamps, and noncritical outputs. |
| Layer count | Four layers by default. Do not attempt Rev-B as a 2-layer board. |
| Harness | Board exposes named channels; the adapter harness maps those channels to C1/C2A at cutover. Do not bake uncertain C2A cavity bindings into copper. |
| Pin lamps | Omitted in baseline. Camera scoring supplies pin state. |

---

## 2. Electrical Domains

Rev-B has three domains. Keep them explicit in schematic names, layout rooms, silkscreen, test points, and DRC classes.

### 2.1 Logic Domain

- Raspberry Pi, MCP23017s, RP2040, UART, I2C, watchdog trigger, low-voltage relay-coil drive logic, and board-driven status-LED drivers.
- Powered from an external regulated 5 V supply or Pi-side 5 V distribution.
- The PCB shall not include a PoE PD design in Rev-B v1.
- Logic ground is allowed to exist only on the Pi/control side of optocouplers, relay drivers, and status-LED drivers.

### 2.2 Machine Sense Domain

- Field side of optocouplers for cams, grippers, DIELL, foul, pushbuttons, and other machine signals.
- Dry-contact channels require a board-provided wetting source that remains isolated from logic ground.
- 24 VAC/voltage-sense channels use rectifier/resistor/opto front-ends and do not share logic ground.
- Each input channel must have a clearly documented default population option: dry-contact wetting or 24 VAC sense.

### 2.3 Machine Output Domain

- Isolated relay contacts that close/open existing machine control circuits.
- These contacts may encounter 24 VAC, 12 VDC, or other machine control voltages depending on the final harness.
- The PCB does not source those voltages.
- Every motion-output contact must include footprints for AC-inductive suppression: RC snubber and/or MOV, depopulatable per output after load characterization.

---

## 3. Output Contract

### 3.1 Selected Topology

Rev-B integrates the AEDIKO function as on-board relay contacts:

```
MCP23017/RP2040 logic -> opto or transistor driver -> on-board relay coil
on-board relay contact COM/NO -> existing machine control circuit
```

The on-board relay contacts are the only connection between the PCB output section and the machine control circuit. This preserves the important property from the AEDIKO approach: the board commands machine coils indirectly, while the machine's own contactors and wiring continue to handle motor power.

For S and T specifically, the PCB must not replace the existing contactor/relay contact sets. OEM documentation shows those relays also provide motor start/run contact behavior and de-energized braking contact behavior. Rev-B may command or interrupt their control/coils through isolated contacts; it must not become the motor contactor or braking path.

Do not implement Rev-B as direct MOSFET/ULN/triac drivers that source or sink machine coil current unless this contract is intentionally rewritten.

### 3.2 Motion Outputs

Baseline motion/control outputs per lane:

> ⚠️ **"connector side" is OEM-REFERENCE ONLY and chassis-specific — NOT a copper constraint.** The OEM wire tables (9800-MP / 6700-ELCO factory chassis) and OUR bench (SS + Omega-Tek retrofit, lanes 21/22) **DISAGREE on cavity routing** — e.g. OEM puts M2 sweep-reverse on C1-17DD/18JJ/26BB/27FF; our bench measured **M2 → C2A (direct 0 Ω)**. Both are correct for their chassis; the Omega-Tek retrofit re-routed the harness landings (same reason our measured S cavities = C,D,N,T ≠ OEM's D,J,N,T). **This is exactly why outputs are function-named and the per-chassis adapter harness resolves cavities at cutover.** Do not bake ANY of these cavity sides into copper. The column below = "where to look first per chassis," nothing more.

| output | function | baseline contact form | safety rail required | connector side (OEM-ref / bench) |
|---|---|---|---|---|
| S | sweep motor contactor command | isolated NO dry contact | yes | bench: C1 (C,D,N,T) |
| T | table motor contactor command | isolated NO dry contact | yes | bench: C1 (A,K,H,E,L) |
| SP | spot solenoid command | isolated NO dry contact | yes | bench: C2A (0 Ω) |
| BE | back-end command | isolated NO dry contact | yes | bench: straddles C1+C2A |
| M | master/control command | isolated NO dry contact | yes | bench: C2A |
| M1 | ball-return command | isolated NO dry contact | yes | **POPULATE-OPTIONAL** — M1 not bench-confirmed on our chassis + FSM doesn't drive it; footprint present, DNP until verified at-machine |
| M2 | sweep reverse command | isolated NO dry contact | yes | ⚠️ **OEM≠bench:** OEM=C1-17DD/18JJ/26BB/27FF + TSA/Expander; **our bench=C2A (0 Ω).** Harness resolves per chassis. |

> **The OEM M2/Expander note still matters even though our cavity differs:** regardless of WHICH connector M2 lands on, the OEM Expander warning (§audit-5) says the sweep-reverse path includes a motor-start/reverse interlock + a shorting-plug requirement ("expander cable must be terminated or sweep won't run"). The harness must **preserve that interlock function**, not just jumper the cavity. That's a real, chassis-independent constraint — keep it.

Schematic footprint rule:

- Use relay footprints whose contacts are rated for inductive AC control loads, not only small signal loads.
- Size contacts from measured coil/control current before release to fab.
- Prefer a common relay footprint class across S/T/SP/BE/M/M1/M2 unless board area or load data justifies a split.
- Provide test pads for relay coil drive, relay common, relay normally-open, and relay state.
- If any output later proves to require NC or SPDT behavior, update this table before routing.

### 3.3 Status Lamp Outputs

Status outputs per lane:

| output | function | safety rail required |
|---|---|---|
| L_FIRST | 1st-ball lamp | no |
| L_SECOND | 2nd-ball lamp | no |
| L_STRIKE | strike lamp | no |
| L_FOUL | foul lamp | no |

Lamp outputs are not motion-critical and are not on the safety rail. Dylan's Rev-B decision is to install our own LEDs in the existing mask housings and wire them back to the PCB. The board drives those LEDs from VCC_5V logic power through low-side 2N7002-class FET drivers with per-channel current-limit resistors. The machine's measured 15 VDC mask-lamp supply is not used, and there is no LOGIC-to-MACHINE isolation barrier for the status LEDs.

### 3.4 Explicitly Omitted Outputs

- KX relay: omitted. Camera scoring replaces old scorer pin-data flow.
- Pin lamps 1-10: omitted in Rev-B baseline. Add only as a future optional output bank if camera scoring is abandoned.
- Motor line power: never routed on the PCB.

---

## 4. Safety Rail Contract

The safety rail controls permission for on-board motion-output relays to energize. It is the electrical enable for S/T/SP/BE/M/M1/M2 relay coils.

### 4.1 Required Series Conditions

The rail must drop if any required condition is false:

| condition | source | fail-safe default |
|---|---|---|
| Watchdog OK | NE555 monostable kicked by Pi | false |
| Arm OK | Pi arm GPIO, asserted only after operator-safe state | false |
| RP2040 OK | RP2040 heartbeat/permission output | false |
| Cam stop OK | RP2040 immediate cam-stop drop path | false on reset/fault |
| TB/SC hardware interlock OK | external hardware interlock loop | false/open |
| Stop/CIS/master chain OK | external machine safety chain sense or series loop | false/open |

The Pi must not be able to bypass these conditions in software.

### 4.2 RP2040 Safety Role

The RP2040 is not only an event-forwarder. It must participate in rail permission:

- On reset, bootloader, brownout, firmware crash, or missing heartbeat, RP2040 permission is false.
- On cam-stop violation or cam timeout, RP2040 pulls the rail false immediately.
- A dead UART must not leave motion outputs enabled. Loss of UART should lead to Pi/FSM fault, but rail permission must also require RP2040 health.

### 4.3 Watchdog Carryover

Reuse the Rev-A NE555 watchdog topology where appropriate:

- Pi kick maintains watchdog OK.
- Missing kick for the timeout window drops the motion relay rail.
- Include the Rev-A trigger pull-up fix.
- Keep the watchdog observable with test pads: TRIG, OUT, rail-gate drive, and relay-enable net.

### 4.4 Interlock Handling

TB/SC remains an open item electrically, but not architecturally:

- The board must provide a hardware interlock input or loop that can remove rail permission without Pi software.
- The final harness may derive this from TB/SC cam contacts, the existing 24 V control path, or a low-voltage isolated loop after at-machine verification.
- The schematic must make the interlock a first-class rail condition, not merely an RP2040/MCP input.
- OEM manuals identify TB and SC as the table/sweep interference interlock cams. The Rev-B circuit may sense them differently after field verification, but it must not soften their role into advisory firmware-only inputs.

### 4.5 Welded Contact Limitation

The safety rail de-energizes on-board output relay coils. It cannot open a relay contact that has welded closed. Relay/contact rating, suppression, and validation are therefore safety-relevant. The existing master breaker/Stop/CIS chain remains the final physical stop.

---

## 5. Input Contract

### 5.1 Fast Inputs to RP2040

| signal | RP2040 role | design requirement |
|---|---|---|
| SA | sweep cam event/position | isolated input, edge-capable |
| SB | sweep guard cam | isolated input, edge-capable |
| SC | sweep interlock cam echo | isolated input plus hardware interlock path |
| TA1 | table cam event/position | isolated input, edge-capable |
| TA2 | table run-through cam | isolated input, edge-capable |
| TB | table interlock cam echo | isolated input plus hardware interlock path |
| DIELL-L | ball detect | isolated input, edge-capable |
| DIELL-R | ball detect | isolated input, edge-capable |

Each channel must support either dry-contact wetting or voltage/24 VAC sense by population option. The default population can be chosen per signal only after at-machine verification.

Fast-input debounce/filtering is part of the safety/timing design. SA/SB/SC/TA1/TA2/TB must not get slow RC or firmware debounce that can mask cam overlap or stop edges. The RP2040 path must be edge-capable, and the selected hardware plus firmware debounce budget must be documented before netlist release.

### 5.2 Slow Inputs to MCP23017 Banks

Baseline slow inputs:

- GS1-GS10 gripper switches
- GP gripper protect
- BS bin/#9
- OS off-spot
- PBZ first-ball/zero/manual intervention
- PBC cycle pushbutton
- Foul
- 10th-frame
- Manual table/sweep/sweep-switch/sweep-reverse inputs
- Spare inputs for future machine-specific discoveries

The PCB shall allocate channel count and bank position, but it shall not depend on final C2A cavity numbers for grippers/cams/PBZ/PBC. Those bindings are harness/software assignments after at-machine actuation tests.

### 5.3 Input Front-End Rules

- No machine input may connect directly to Pi, RP2040, or MCP23017 pins.
- Dry-contact channels need current limiting, debounce strategy, and defined open/closed polarity.
- 24 VAC channels need rectification, current limiting, bleed/discharge, and opto input protection.
- Every input needs a test pad or accessible header point on both field side and logic side where practical.
- Silkscreen must label field polarity/terminal function clearly enough for bench bring-up.

---

## 6. Controller Interface

### 6.1 Devices Per Board

| device | role |
|---|---|
| RP2040 | fast inputs, cam-stop enforcement, UART events, rail permission |
| MCP23017 IN-A | grippers and high-use slow inputs |
| MCP23017 IN-B | manual/future slow inputs |
| MCP23017 OUT-A | relay/status-LED command bits |
| NE555 watchdog | Pi kick to motion rail permission |

OUT-B for pin lamps is not populated in the Rev-B baseline.

### 6.2 Pi Link

- One I2C bus per board for MCP23017 devices.
- UART between Pi and RP2040 for cam/ball events and heartbeat.
- Dedicated Pi GPIO for watchdog kick.
- Dedicated Pi GPIO for arm permission per board.
- Dedicated interrupt lines for MCP input banks where useful.

The Pi/FSM may command outputs, but output energization still depends on the safety rail.

---

## 7. Connector And Harness Contract

Rev-B should use board connectors organized by electrical function, not uncertain machine cavity numbering.

Recommended connector groups:

| connector group | purpose |
|---|---|
| J_PI | Pi logic: I2C, UART, watchdog kick, arm, INT, 5 V, logic GND |
| J_PWR | regulated 5 V logic/input power and optional isolated field-wetting supply input |
| J_FAST_IN | SA/SB/SC/TA1/TA2/TB/DIELL-L/DIELL-R field inputs |
| J_SLOW_IN_A | GS1-GS10, GP, OS, BS |
| J_SLOW_IN_B | PBZ, PBC, Foul, 10th/manual/spares/AUX |
| J_MOTION_S / J_MOTION_T / J_MOTION_SP / J_MOTION_BE / J_MOTION_M / J_MOTION_M2 / J_MOTION_M1 | isolated 2-pin contact pair per motion output; M1 remains DNP optional until machine-confirmed |
| J_LAMP_LED | logic LED connector: VCC_5V, GND, L_FIRST/L_SECOND/L_STRIKE/L_FOUL LED returns |
| J_SAFETY | hardware interlock and Stop/CIS/master chain sense or loop |

The machine adapter harness maps these groups to C1/C2A. This keeps the PCB reusable even while exact gripper/cam C2A cavities remain machine-gated.

OEM docs show C1/C2A as mixed machine interfaces, not a clean power-vs-logic boundary. The connector grouping above is intentionally function-named; the adapter harness must treat any machine-facing cavity as a field-domain net unless that exact net has been verified.

---

## 8. Power Contract

### 8.1 Board Power

- Provide regulated 5 V to logic, MCP23017s, RP2040, NE555, opto logic sides, and on-board output relay coils if 5 V relay coils are selected.
- Add reverse-polarity and input transient protection.
- Size the 5 V input for worst-case simultaneous relay coil load plus logic plus margin.
- Do not include on-board PoE conversion in Rev-B v1.

### 8.2 Machine Power

- Machine control voltages are external and pass only through isolated output contacts.
- The board may sense machine voltages through isolated front-ends.
- The board shall not generate 24 V machine coil power.
- Status indicators use board-driven LEDs from VCC_5V logic power; the machine mask-lamp supply is abandoned for Rev-B status indication.

### 8.3 Isolation Notes

If dry-contact wetting is board-provided, decide before schematic whether it is:

1. isolated from logic by a small isolated DC/DC supply, or
2. intentionally tied to a machine-side reference after field verification.

Default for Rev-B safety review is option 1: isolated field wetting.

---

## 9. Layout And DRC Contract

- Four-layer board.
- Separate layout rooms for logic, input field side, output contacts, safety rail/watchdog, and connectors.
- No 115 VAC motor current traces.
- Wide spacing and explicit keepouts around all machine output contact terminals.
- DRC classes for logic, isolated field sense, and machine output contacts.
- Test pads for every safety condition and every output relay state.
- Silkscreen labels must match the signal names in this contract, not raw C1/C2A guesses.
- Board must include mounting holes and strain relief assumptions suitable for the DIN enclosure.
- Gerber review must include a safety-net checklist, not only KiCad DRC.

---

## 10. Source-Of-Truth Cleanup

The following older statements are stale for Rev-B unless explicitly reintroduced:

- "GPIO/MCP -> AEDIKO IN" as the output implementation.
- "ULN/MOSFET directly drives the 24 V machine coil."
- "Relay-enable rail feeds machine coil-driver returns."
- "PCB needs final C2A cavity binding before board channel design."
- Any assumption that the Siemens relay identity alone proves the S/T output topology.

Current bench interpretation for PCB purposes:

- C1 is primarily the motor/contact/sweep-reverse path.
- C2A is primarily the control/cam/gripper/scoring path.
- Neither connector is a clean logic-vs-power boundary; keep both on the machine/field side unless a specific net is verified.
- S/T motor current stays on machine contactors.
- The board commands control circuits through isolated contacts.
- Exact C2A input cavity binding waits for at-machine actuation testing.
- S-side cam-stop proof and TB/SC electrical form wait for at-machine verification, but the PCB still includes hardware rail enforcement.

If `phase8_bench_session1_FINDINGS.md` conflicts internally on the Siemens/S relay identity, do not use that conflict to change PCB topology. The topology is contact-output based and remains valid regardless of which physical relay/contact block gets mapped in the harness.

---

## 11. Items Blocking Assembly / Cutover Release

The bare PCB fab package exists and is releaseable under the current conservative DRC contract. These items still block a populated controller, bench signoff, or cutover:

1. **Output relay rating.** Confirm contact current/voltage for S/T/SP/BE/M/M2 and decide whether G5LE-1 margin is sufficient.
2. **Relay coil rail budget.** Confirm 5 V supply current margin with worst-case relay count and any M1 population decision.
3. **Safety connector details.** Confirm TB/SC/Stop/CIS electrical form and final connector/polarity for the external NC loops.
4. **Input population defaults.** Decide dry-contact wetting vs 24 VAC sense population for every field input after at-machine measurements.
5. **Status-LED sizing.** Choose the mask LED type/current for bowling-center brightness and lock the per-channel current-limit resistor value (`Rled_*`, 330R TBD in the scaffold).
6. **M1 status.** Confirm whether ball-return exists as a separate command on this chassis; keep M1 DNP until proven.
7. **Board envelope.** DIN enclosure size, mounting hole pattern, connector side preference, and service-clearance constraints.
8. **Fast-input debounce/latency budget.** Choose cam-input hardware filtering and RP2040 debounce limits that preserve SA/SB/SC/TA1/TA2/TB edge timing.

These do not block bare-PCB fabrication, firmware simulation, or camera scoring.

---

## 12. Build Sequence After This Contract

1. Use the current fab package in `kicad/fab_revB_routed_manual/` for bare-PCB quote/upload; do the vendor Gerber/drill preview before ordering.
2. Update `phase8_channel_allocation.md` to remove AEDIKO-specific output wording.
3. Update `lane_node/controller_io.py` comments/maps so software names match this contract.
4. Continue SKiDL/KiCad from the corrected scaffold in this order:
   - power and protection
   - NE555 watchdog
   - safety rail
   - one motion-output relay channel, then replicate
   - fast-input channel, then replicate
   - slow-input MCP banks
   - RP2040
   - Pi connector
   - logic status-LED outputs
5. Run ERC/netlist review before placement.
6. Place safety rail and output contact section first.
7. Route, DRC, and fab export are complete for the routed-manual Rev-B package; rerun `scripts/export_fab_revB.py` after any future board edit.
8. Gerber review plus explicit safety-net review.
9. Bench bring-up on a locked-out/off-live machine only:
   - power rails
   - I2C enumerate
   - RP2040 boot and heartbeat
   - watchdog drop
   - arm drop
   - interlock drop
   - each relay contact with dummy load
   - input front-end tests
   - cam-stop rail drop
   - only then machine harness testing

---

## 13. One-Sentence Contract

Rev-B is a one-lane, four-layer, fully integrated controller board that reads isolated machine inputs, runs fast cam-stop supervision on an RP2040, and commands existing machine control circuits through on-board isolated relay contacts whose coils are disabled by a non-bypassable hardware safety rail.
