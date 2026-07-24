## 5. Rev-B Controller Board: Overview, Domains & Isolation

This section describes the Rev-B controller board as a whole: what it is, what it replaced, the three electrical domains it is physically divided into, how those domains are kept apart, and the one safety rule that must never be violated when working on it. Read this before Section 8 (Inputs), Section 9 (Outputs & Relays), Section 10 (Safety Rail & Watchdog), or Section 7 (RP2040 Co-Processor & Firmware) — those sections drill into individual circuits, but they all assume the domain model and isolation philosophy established here.

> **Scope of this manual.** "Rev-B" is the second-generation, fully integrated lane controller board (KiCad project `wsl-phase8b`). At the time of writing it is a **bare-PCB fab-ready** design — the Gerbers/drill and a fully-assembled JLCPCB PCBA package have been generated and pass the board's design-rule check (DRC) and audit gates — but it is **not yet assembly- or cutover-released**. Several values are still flagged for at-machine confirmation; those are called out as `(VERIFY: …)` where they appear.

---

### 5.1 What the board is, in one sentence

> Rev-B is a one-lane, 250 × 225 mm, four-copper-layer, fully integrated controller board that reads isolated machine inputs, runs the fast cam/ball input capture + safety supervisor on an RP2040, and commands existing machine control circuits through on-board isolated relay contacts whose coils are disabled by a non-bypassable hardware safety rail.

One physical board controls exactly **one bowling lane** (one AMF 82-70 pinsetter). A lane *pair* (e.g. lanes 21 and 22) uses **two identical boards** driven by a single Raspberry Pi. The camera used for pin scoring may be shared across the pair, but every piece of machine-control wiring — relay outputs, cam/switch inputs, the safety loop — is **per lane, per board**. There is no "master/slave" board concept; the two boards are interchangeable units distinguished only by which lane's harness and which Pi I²C bus / UART they are wired to.

---

### 5.2 What Rev-B consolidated (the Rev-A → Rev-B story)

The previous-generation ("Rev-A") bench rig that proved out Phase 8 was an assembly of separate commercial-off-the-shelf (COTS) modules wired together on a Raspberry Pi:

- a relay module (an AEDIKO-style relay HAT) that switched the machine control circuits;
- separate opto-isolator input modules (AL-ZARD / DONGKER-class 8-channel opto boards) that read the cams, ball detectors, and switches;
- a small custom NE555-based hardware **watchdog + AC-interposer PCB** (the "fourth K-pillar" — a 555 monostable the Pi had to keep kicking, plus a 1N4007/10 µF rectifier front-end that turned a 24 VAC machine signal into a clean opto input).

> *Brand attribution note:* the "AEDIKO" relay module and "AL-ZARD / DONGKER" opto-module names come from the Phase 8 project history (the COTS parts used on the bench rig). The Rev-B design documents read for this manual name the **integrated replacement parts** (below), which are the authoritative source of truth for what is actually on the board.

**Rev-B collapses all three of those into one board.** It is a from-scratch integrated controller, not a carrier for COTS modules. The functions map across as follows:

| Rev-A COTS element | Rev-B on-board replacement | Key part(s) |
|---|---|---|
| AEDIKO relay HAT | On-board isolated dry-contact relays, one per motion output | Omron **G5LE-14, 5 VDC coil** SPDT relay (LCSC C116963) — 6 placed + 1 DNP |
| AL-ZARD / DONGKER opto-input modules | On-board opto-isolated input front-ends, one per channel | **PC817B** optocoupler, DIP-4 (LCSC C5692981) — 32 placed |
| NE555 watchdog + AC-interposer PCB | On-board NE555 hardware watchdog, integrated into the safety rail | **NE555DR** bipolar timer, SOIC-8 (LCSC C7593) |
| *(new in Rev-B)* | RP2040 fast cam/ball front-end + safety supervisor | Raspberry Pi **Pico** module (Raspberry Pi SC0915) |
| *(new in Rev-B)* | Isolated field-wetting supply | TRACO **TMA-0505S** 5 V→5 V 1 W isolated DC/DC (DigiKey-locked, ref U37) |

Two functions are genuinely **new** in Rev-B (they did not exist as discrete modules on the bench rig):

1. **An RP2040 co-processor (the Pico module).** It owns the landed fast inputs
   (cams + ball detectors), runs a fail-safe motion max-run backstop independently
   of the Pi, forwards events over UART, and contributes `RP2040_OK` to the rail.
   The v1.2.3 code contains per-cam overrun paths, but all measured-cam enforcement
   flags remain OFF pending polarity capture and a new controlled release. See
   Section 7.
2. **Isolated field "wetting."** Dry-contact inputs (grippers, cams, switches) need a sense voltage to detect a contact closing. Rev-B generates that voltage on-board from an **isolated** DC/DC converter (the TMA-0505S, ref U37), so the sense rail (`FIELD_WET_V`) and its return (`FIELD_GND`) are galvanically separated from logic ground. A machine-side fault cannot backfeed the Pi.

> ⚠️ **Source-of-truth correction.** An earlier parts-planning draft (`phase8b_pcb_revB_BOM_power.md`) suggested a generic **B0505S-1W** isolated brick for field wetting. The **as-built netlist and the locked fab BOM use the TRACO TMA-0505S** (`scripts/generate_kicad_netlist_revB.py` `block_supplies()`, footprint `Converter_DCDC_TRACO_TMA-05xxS_…`; off-board hardware sheet ref **U37**, "Locked exact part"). Use the **TMA-0505S** — the B0505S reference is stale.

What Rev-B deliberately **does not** integrate:
- **No motor power.** Motor line current (115 VAC) is never routed on the PCB. The machine's own S/T contactors continue to switch motor current and keep their OEM run/braking behaviour.
- **No machine coil supply.** The board does not generate the machine's 24 V control/coil voltage. Relay *contacts* switch the machine's existing 24 V circuits; the board only opens and closes dry contacts.
- **No PoE.** Rev-B v1 has no Power-over-Ethernet PD stage; 5 V comes from an external regulated supply or Pi-side 5 V.
- **No pin lamps / KX scorer relay.** Pin state comes from camera scoring (Track A), so the old pin-lamp driver bank and the KX scorer-data relay are omitted. (A fourth I²C expander, "OUT-B" @ 0x23, is reserved in software for an optional future physical pindicator but is **not populated**.)

---

### 5.3 Board statistics

| property | value | source |
|---|---|---|
| Board outline (Edge.Cuts) | **250 × 225 mm** | spec `phase8b_pcb_revB_spec.md` (re-audit, line "Edge.Cuts = 250×225mm") |
| Copper layers | **4** (F.Cu / In1.Cu / In2.Cu / B.Cu) | spec §9; netclass doc §2 |
| Layer stack | F.Cu = signal; In1.Cu = GND plane (logic); In2.Cu = power (VCC_5V / VCC_3V3); B.Cu = signal (field/output) | netclass doc §2 |
| Copper weight | 1 oz (clearance/width budgets assume 1 oz) | netclass doc §1 |
| Schematic components | 216 | spec / session-close §2 |
| Board footprints (incl. test pads + mounting holes) | ~236 | session-close §2 |
| Named nets | 184, all classified, 0 anonymous `N$` | session-close §2; netclass doc |
| Net classes | 5: Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21 | session-close §2 |
| DRC state | 0 violations / 0 unconnected pads / 0 footprint errors (routed-manual board, conservative rules) | session-close §2 |
| Mounting | 4× M3 holes (refs MK1–MK4), DIN-enclosure target | offboard-hardware / DNP-excluded sheets |
| Assembly split | 189 non-DNP BOM refs / 27 DNP refs / 20 non-DNP mechanical-test refs excluded from assembly | spec (Codex fab-prep pass) |

> **Routing method (for the next engineer who opens KiCad):** the board is **manually / scripted-tiered routed**, not autorouted. Full-board FreeRouting was attempted four times and rejected — the DSN export cannot carry the creepage intent from `wsl-phase8b.kicad_dru`, and it failed to produce a `.ses` headlessly. The canonical *unrouted* source board is `kicad/wsl-phase8b.kicad_pcb`; the routed working board is `kicad/wsl-phase8b.routed-manual.kicad_pcb`. After any board edit, re-run `scripts/export_fab_revB.py` (it re-runs DRC + audit and regenerates the fab package).

---

### 5.4 The three electrical domains

Rev-B is divided into **three electrical domains**. The domain split is the central organizing idea of the whole board: it is reflected in the schematic net names, the physical placement (board "rooms"), the silkscreen labels, the test-point grouping, and the DRC net classes. **If you are tracing a fault, the first question is always "which domain is this net in?"** because that tells you what reference it sits on and what is (and is not) allowed to touch it.

| domain | what lives here | voltage reference | typical voltages |
|---|---|---|---|
| **LOGIC** | Raspberry Pi interface, the 3× MCP23017 I²C expanders, the RP2040 (Pico), UART, I²C, watchdog trigger, relay-coil drive transistors, status-LED drive transistors, the safety-rail logic | **GND** (logic ground) | 3.3 V / 5 V |
| **FIELD** (machine-sense, **isolated**) | the *field* (LED) side of every input optocoupler — cams, grippers, DIELL ball detectors, foul, pushbuttons — and the isolated wetting rail | **FIELD_GND** (isolated; **not** tied to GND) | 5 V wetting; 24 VAC on AC-sense channels |
| **MACHINE OUTPUT** | the relay *contacts* that open/close existing machine control circuits, plus their snubber/MOV footprints | floating / machine-referenced | 24 VAC measured (see note) |

A fourth grouping — the **SAFETY RAIL / CONTROL** nets (`RELAY_ENABLE_RAIL`, `RAIL_GATE`, the relay coil low-sides `COIL_LO_*`, the AND-chain bases `BASE_AND_*`, and the interlock-loop nets `SAFE_*`) — is **electrically part of the LOGIC domain** (it sits on logic-side coil supply), but it is given its own net class for current-carrying and integrity reasons. Do not mistake it for a machine-output domain: the `SAFE_STOP_RETURN` / `SAFE_TBSC_RETURN` interlock returns are **low-voltage** sense/loop nets, not 250 VAC machine contacts. (This was a real classification bug caught during routing — see §5.6.) The safety rail is covered in detail in **Section 10 (Safety Rail & Watchdog)**.

#### 5.4.1 LOGIC domain

The Pi-side world. Powered from an external regulated **5 V** supply (a DIN-rail PSU such as the Mean Well HDR-15-5, or Pi-side 5 V distribution) with a reverse-polarity Schottky (SS14, ref D17) and transient protection on the input. The Pico module supplies the **3.3 V** rail that powers the three MCP23017 expanders, the opto logic-side pull-ups, and the I²C pull-ups. Logic ground (`GND`) is permitted to exist **only** on the Pi/control side of the optocouplers, the relay-coil drivers, and the status-LED drivers — it must never appear on the field or machine-output side of an isolation barrier.

Key rule: the **MCP23017s run at 3.3 V**, not 5 V, specifically so the I²C bus is safe for the Raspberry Pi's 3.3 V GPIO. Never run the MCP23017s at 5 V on the Pi bus without a level shifter.

#### 5.4.2 FIELD (machine-sense) domain — isolated

The field side of every input opto. Each input channel can be populated for one of two front-end styles (the choice is per-channel and is finalized after at-machine measurement — see Section 8):

- **Dry-contact wetting** (the confirmed default for the cams, and expected for grippers/switches): the isolated wetting rail `FIELD_WET_V` feeds the opto LED through a series resistor; the machine contact closes that node to `FIELD_GND` to assert the input.
- **24 VAC sense:** a rectifier/resistor/bleed front-end (Rev-A interposer style) turns a 24 VAC machine signal into an opto LED drive.

The whole field domain sits on **FIELD_GND**, which the isolated TMA-0505S keeps separate from logic `GND`. This is `spec §8.3` **option 1: isolated field wetting** — the default for the Rev-B safety review.

> **Measured working voltage.** The at-machine field session measured the machine-output relay working voltage at **24 VAC** on all accessible relays (cam inputs are **dry contacts, normally-closed at rest**). The board's DRC, however, is still cut to **conservative 250 VAC-derived creepage** numbers (see §5.6) so routing stays on the safe side; relaxing to 24 V numbers is a future DRC/policy edit, not a board re-route. `(VERIFY: SP solenoid working voltage is presumed 24 VAC — its coil terminals were inaccessible at the field session; glance-confirm at cutover.)`

#### 5.4.3 MACHINE OUTPUT domain

The relay contacts. These are **isolated dry contacts** — the board does not source the voltage across them. Depending on the final harness a contact may switch 24 VAC, 12 VDC, or another machine control voltage; the board only closes/opens the contact inside an *existing* machine control circuit. Every motion-output contact carries footprints for arc-suppression (an RC snubber and a MOV), **depopulated (DNP) by default** until the inductive load is characterized at the machine.

For **S (sweep)** and **T (table)** specifically: the board must **command** the existing contactor/relay coils through its isolated contacts; it must **not** become the motor contactor or the de-energized braking path. The OEM contactors keep their motor start/run and braking contact behaviour. (See Section 9 for the full output contract.)

---

### 5.5 Physical layout: banding, rooms, and the keepout gutters

The three domains are not just a naming convention — they are **physically banded** across the board, left to right, with **no-copper keepout gutters** between them. This is what makes the isolation auditable: a logic trace simply cannot wander into the machine-output region because there is a deliberate copper-free channel in the way.

```
   LEFT band          gutter           CENTER band            gutter         RIGHT band
 ┌───────────┐   ┌─────────────┐   ┌────────────────┐   ┌─────────────┐   ┌────────────┐
 │   FIELD   │   │  no-copper  │   │     LOGIC      │   │  no-copper  │   │  MACHINE   │
 │  inputs   │   │   keepout   │   │  Pi / MCP /    │   │   keepout   │   │  OUTPUT    │
 │ (PC817    │   │   gutter    │   │  RP2040 +      │   │   gutter    │   │  (G5LE     │
 │  field    │   │             │   │  SAFETY rail / │   │             │   │  relays +  │
 │  side)    │   │             │   │  watchdog +    │   │             │   │  snubber/  │
 │           │   │             │   │  status-LED    │   │             │   │  MOV)      │
 │           │   │             │   │  drivers       │   │             │   │            │
 └───────────┘   └─────────────┘   └────────────────┘   └─────────────┘   └────────────┘
   ~X74            X76.8–80          X104–151             X181–184           X176–178
```

(X values are board millimetre coordinates from the placement audit; pairwise band overlap is **0**, verified.)

| board "room" | contents |
|---|---|
| LEFT — FIELD | field (LED) side of the input optos; isolated wetting front-ends |
| CENTER — LOGIC + SAFETY | Pi connector, 3× MCP23017, RP2040 (Pico), I²C/UART, NE555 watchdog, safety-rail pass-FET + AND chain, and the four status-LED FET drivers (lower logic band) |
| RIGHT — MACHINE OUTPUT | the seven G5LE relays, their per-channel function-named output terminals, and the snubber/MOV footprints |

**Why the gutters sit *between* pad columns, not on them.** An earlier placement put the FIELD/LOGIC keepout directly on top of the PC817 field pad column, which blocked the routes that legitimately have to reach those pads. The corrected placement moves the gutter into the space **between** the field and logic pad columns. If you re-place or re-route, preserve that: the gutter is the air-and-no-copper zone *between* domains, never on a pad row that needs to be wired.

**Plane discipline (the vertical dimension of isolation).** The isolation barrier is not only lateral — it is vertical too. On the inner layers:

- **In1.Cu (logic GND plane)** must **not** extend under the FIELD or MACHINE OUTPUT rooms. Pour keepouts hold it back.
- **In2.Cu (power pour, VCC_5V / VCC_3V3)** is logic-side only and likewise voided under the FIELD and MACHINE rooms.

A ground or power plane sneaking under a relay contact or an opto's field pads would short the creepage path through the board even though the surface traces look clear. This is the 4-layer equivalent of the Rev-A bottom-copper keepout.

---

### 5.6 The isolation philosophy

The governing principle is simple and absolute:

> **The two isolation barriers may be crossed only *inside* the optocoupler and relay packages — never in board copper.**

There are exactly two barriers:

1. **LOGIC ↔ FIELD** — crossed only inside the **PC817 optocoupler** packages. The LED side of each PC817 is FIELD; the phototransistor side is LOGIC. Light crosses the gap; copper does not.
2. **LOGIC ↔ MACHINE OUTPUT** — crossed only inside the **G5LE relay** packages. The coil side is LOGIC/safety-rail; the contact side is MACHINE. A magnetic field crosses the gap; copper does not.

No trace, via, copper pour, or plane may shorten either barrier below the creepage/clearance policy. The DRC rules in `wsl-phase8b.kicad_dru` enforce this so that KiCad will flag, for example, a logic trace routed under a relay contact pad or a ground plane crossing an opto.

**Two ground references, proven separate.** Logic `GND` and isolated `FIELD_GND` are distinct nets that share **zero** nodes (verified on the actual board, including test pads). This separation is what makes the FIELD domain truly isolated; if you ever find a copper path joining them, the isolation is broken and the board is unsafe to power against a live machine.

**Creepage/clearance policy (current, conservative).** The live DRC uses these numbers, derived for a conservative 250 VAC RMS working assumption (pollution degree 2, basic insulation):

| barrier / situation | policy distance enforced in DRC |
|---|---|
| LOGIC ↔ FIELD (across PC817) | ≥ **2.5 mm** (clearance + creepage) |
| LOGIC ↔ MACHINE (across G5LE) | ≥ **3.2 mm** (clearance + creepage) |
| machine-output trace ↔ any non-output copper | ≥ **2.0 mm** |
| machine-output trace ↔ board edge | ≥ **1.0 mm** |
| between independent machine-output channels | ≥ **1.5 mm** (a shorted channel must not arc to its neighbour) |

The actual machine-output working voltage was **measured at 24 VAC**, which would permit much tighter functional-insulation spacing (~0.5–1.0 mm). The board intentionally **keeps the wide conservative numbers** for now — relaxing them later is a DRC/policy edit and a re-export, whereas tightening after routing would force a re-route. `(VERIFY: the 250 VAC→24 VAC creepage relaxation is an explicitly deferred policy decision — confirm the final creepage numbers before any production shrink/spin.)` The current fab package proves isolation by **copper clearance + package spacing + all-layer no-copper keepouts only** — it does **not** rely on milled isolation slots under the optos/relays. Milled slots remain an optional future mechanical-hardening pass that would require a re-DRC and re-export.

> **The Machine_Output clearance has two numbers — don't be alarmed.** The Machine_Output net class lists a small **0.35 mm base** clearance; that is only the same-channel fabrication/routing floor (a relay's own contact pair and its RC snubber across that pair are *intentionally* adjacent). The real insulation constraints — LOGIC↔MACHINE ≥ 3.2 mm and channel-to-channel ≥ 1.5 mm — are enforced by the custom `.kicad_dru` rules, not by that base class number alone.

**A classification trap to remember (logged so it survives):** the `SAFE_*` interlock-loop nets were *originally* mis-filed as machine-output domain, which wrongly forced the ≥ 3.2 mm LOGIC↔MACHINE creepage against the very rail/gate they are supposed to drive (7 false DRC violations). They are **low-voltage rail/interlock control nets in the LOGIC/safety-rail domain** and take logic-domain clearance. If you re-classify nets, the test is electrical reality (what voltage and reference does this net actually carry?), not a pattern match on the name.

---

### 5.7 The non-negotiable safety rule

> **This board must NEVER be treated as the only safety device.**

Rev-B adds *layers* of protection; it does not replace the machine's existing safety chain. When working on, bench-bringing-up, or servicing this board, treat the following as permanent, hardware-level facts:

1. **The upstream machine safety chain stays live and primary.** The **Stop switch** and **C.I.S.** both cut the master breaker. Separately, the powered-proven OEM TB/SC ladder blocks both S/T coils when both levers are BACK/open. Candidate C leaves TB/SC in those coil circuits, uses only the controlled J_SAFE1-2 jumper, and requires per-lane G3 insertion proof. The board must defeat neither path. `(VERIFY remains for the separate J_SAFE3-4 Stop/CIS landing; TB/SC J_SAFE landing is resolved as no machine landing.)`

2. **Live motor current never touches the board.** Motor power stays on the machine's S/T contactors. The board commands those contactors' control coils through isolated contacts only.

3. **The on-board rail fails open** on loss of logic power, watchdog kick, `RP2040_OK`/enabled cam-stop, ARM, or the implemented Stop/CIS loop. Candidate C closes the J_SAFE1-2 design position with the controlled jumper; primary TB/SC blocking remains separately in the OEM S/T coil ladder and is proven by G3. **The Pi cannot bypass either correctly installed hardware path** (see Section 10).

4. **The safety rail de-energizes coils; it cannot un-weld a stuck contact.** The rail drops the relay *coils*, but a relay contact that has welded closed will stay closed — which is exactly why relay contact rating, arc suppression (snubber/MOV), and validation are safety-relevant, and why the master breaker / Stop / C.I.S. chain remains the ultimate stop. `(VERIFY: final relay contact current/voltage rating for S/T/SP/BE/M/M2 — confirm G5LE-14 margin is sufficient — pending the at-machine coil/control current measurement.)`

5. **Never power this board against a live machine until the on-board gates are bench-proven and Candidate C passes the per-lane live G3 S/T coil-drop proof.** The software (`lane_node/controller_io.py`) is only the soft half; its SC∧TB echo is default-off, lacks an independent TB input on this chassis, and is not validated protection.

Carry this rule into every later section: when Section 9 describes a relay closing, or Section 7 describes the RP2040 raising `RP2040_OK`, the closing/permitting is always *in addition to* — never *instead of* — the machine's own breaker, interlock, and braking.

---

### 5.8 Reference designator → function map (orientation)

For bench bring-up and probing, the as-built reference designators map to functions as follows. **The function-named connector labels are the authoritative wiring guide — not the raw `Jn` numbers or any machine cavity number.** The adapter harness maps the function-named terminals to the machine's C1/C2A connectors at cutover, which is why no machine cavity number is baked into copper.

| ref(s) | function-named label | what it is |
|---|---|---|
| A1 | — | RP2040 (Raspberry Pi **Pico** module, SC0915); program after assembly. **Do not** use a Pico H/WH with pre-soldered headers. |
| U1 | (MCP_IN_A @ 0x20) | MCP23017 — high-use slow inputs (grippers GS1–GS10, GP, OS, BS, PBZ, PBC, Foul) |
| U2 | (MCP_IN_B @ 0x21) | MCP23017 — manual / 10th-frame / spare slow inputs |
| U3 | (MCP_OUT_A @ 0x22) | MCP23017 — 7 relay command bits + 4 status-LED bits |
| U4–U35 | — | PC817B input optocouplers (32 channels) |
| U36 | — | NE555DR hardware watchdog timer |
| U37 | — | TRACO TMA-0505S isolated field-wetting DC/DC |
| K1–K6 | — | G5LE-14 5 VDC motion relays (the six populated outputs) |
| K7 | — | G5LE M1 relay — **DNP** (not populated) |
| Q1–Q6 | — | MMBT3904 NPN relay-coil drivers (one per populated relay) |
| Q7 | — | MMBT3904 M1 coil driver — **DNP** |
| Q8–Q11 | — | 2N7002 low-side FETs driving the four status LEDs |
| Q12, Q13 | — | AO3400A N-FETs: watchdog kick + watchdog-OK gates |
| Q14 | — | AO3401A **P-channel** rail pass-FET (gates the relay-enable rail) |
| D17 | — | SS14 reverse-polarity Schottky on the 5 V input |
| J1 | **J_PI** | 2×10 IDC header to the Pi: I²C, UART, watchdog kick, arm, INT, 5 V, 3V3, GND, RP2040_OK |
| J2 | **J_PWR 5V** | 3-pos screw terminal — regulated 5 V logic/input power |
| J3 | **J_FAST_IN** | 10-pos — SA/SB/SC/TA1/TA2/TB + DIELL-L/DIELL-R field inputs |
| J4 | **J_SLOW_IN_A** | 14-pos — GS1–GS10, GP, OS, BS |
| J5 | **J_SLOW_IN_B** | 12-pos — PBZ, PBC, Foul, 10th, manual, AUX/spares |
| J6–J11 | **J_MOTION_BE / _M / _M2 / _S / _SP / _T** (in this annotation order) | six 2-pin isolated contact terminals, one per populated motion output |
| J12 | **J_MOTION_M1** | M1 ball-return output terminal — **DNP** |
| J13 | **J_LAMP_LED** | 6-pos — VCC_5V, GND, and the four status-LED returns |
| J14 | **J_SAFETY** | 4-pos board-side series provision — **pins 1–2 = controlled Candidate-C jumper (no TB/SC machine landing); pins 3–4 = Stop/CIS chain sense** |
| MK1–MK4 | — | M3 mounting holes |
| TP1–TP16 | — | test pads (rails, I²C, watchdog nodes, ARM_PERMIT, RP2040_OK, SAFE_STOP_RETURN, RELAY_ENABLE_RAIL) |

> ⚠️ **Note the motion-terminal ordering.** The output relays are spec'd in functional order **S, T, SP, BE, M, M2, M1**, but the *connector reference numbers* J6–J11 were assigned by the tool's annotation order as **BE, M, M2, S, SP, T** (with J12 = M1, DNP). When wiring the harness, **follow the silkscreen function label** (`J_MOTION_S`, `J_MOTION_T`, …), not the `Jn` number, to avoid swapping the sweep and table outputs.

**Two DNP groups you will see on the board but should not populate without authorization:**
- **The entire M1 (ball-return) channel** — K7, Q7, the M1 connector J12, and its associated passives (R85/R86/R87, D13/D14, C10) — is **DNP**. M1 has not been confirmed to exist as a separate command on this chassis and the FSM does not drive it. Footprint present, do not populate until verified at-machine. `(VERIFY: whether ball-return exists as a separate relay command on this SS chassis — keep M1 DNP until proven.)`
- **Every motion-output snubber/MOV** (the `100R DNP` resistors R69/R72/R75/R78/R81/R84/R87, the `10nF X2 DNP` caps C4–C10, and the `MOV DNP` parts D2/D4/D6/D8/D10/D12/D14) is **DNP** until the inductive load on each output is characterized. `(VERIFY: per-output snubber/MOV values after at-machine inductive-load measurement.)`

---

### 5.9 Cross-references

- **Section 8 — Inputs (fast + slow):** the PC817 front-ends, the RP2040 fast inputs (cams + DIELL on **GP6–GP13**), the MCP23017 slow-input banks, and the dry-contact-vs-24VAC population options.
- **Section 9 — Outputs & Relays:** the G5LE relay channels, the MMBT3904 coil drivers, the function-named motion terminals, the S/T contactor-command contract, and the status-LED drivers.
- **Section 10 — Safety Rail & Watchdog:** the relay-enable rail, the AO3401A
  pass-FET, the ARM/RP2040_OK AND chain, the NE555 watchdog, the Candidate-C
  J_SAFE1-2 source jumper, and Stop/CIS J_SAFE3-4 — plus the separate OEM-ladder
  G3 proof behind §5.7.
- **Section 7 — RP2040 Co-Processor & Firmware:** the Pico's role, the fail-safe `RP2040_OK` line, the UART event/command protocol, and the cam-stop / max-run backstop.
