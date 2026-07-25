## 6. Rev-B Power Architecture

This section is the authoritative reference for how the Phase 8 Rev-B lane-controller PCB is
powered: where each voltage comes from, what it feeds, how much current it must carry, and — just
as important — which voltages the board deliberately does **not** generate. If you are bringing a
board up on the bench or fault-finding one in service, read this before you apply power.

The single hard rule that frames everything below: **the PCB generates only its own low-voltage
logic rails, an isolated field-wetting supply, and status-LED drive current. It never sources the
machine's motor power or its 24 V coil-control power.** Those stay on the AMF 82-70 machine's own
contactors and transformer (T2/T3/T4); the board only opens and closes isolated dry relay contacts
inside the machine's existing control circuits. (See Section 9, *Output Contract / Relay Stage*, and
Section 10, *Safety Rail*, for how those contacts are gated.)

> **Scope:** one PCB controls one lane. A lane pair runs two identical boards on one Raspberry Pi.
> Each board has its own independent set of the rails described here.

---

### 6.1 Power Rail Overview

The board has **four** power domains. Three are generated or distributed on-board; the fourth
(machine coil power) is named here only to make explicit that it is *not* on the board.

| Rail | Net name | Source | Nominal | Isolated from logic GND? | Feeds |
|---|---|---|---|---|---|
| **Raw 5 V input** | `VCC_5V_RAW` | External regulated 5 V at `J_PWR` (refdes **J2**), through reverse-polarity Schottky **D17 (SS14)** | +5 V | No (logic side) | Anode of D17 only; becomes `VCC_5V` after the diode |
| **Protected 5 V logic** | `VCC_5V` | Cathode of D17 | ~+4.7 V (5 V − Schottky Vf) | No (logic side) | Pico VSYS, relay coils via the rail-gate FET, NE555 watchdog, TMA-0505S primary, status-LED anode, I²C-header 5 V pin | 
| **3.3 V logic** | `VCC_3V3` | **Raspberry Pi Pico module 3V3 OUT** (Pico pin 36) | +3.3 V | No (logic side) | All 3× MCP23017 (VDD + RESET), every PC817 logic-side pull-up, the I²C bus pull-ups, 3V3 bulk cap |
| **Isolated field-wetting 5 V** | `FIELD_WET_V` / return `FIELD_GND` | **On-board isolated DC/DC TMA-0505S** (refdes **U37**), primary from `VCC_5V` | +5 V isolated | **Yes** — galvanically isolated from logic GND | Field (input) side of the dry-contact opto front-ends only |
| *(Machine 24 V coil power)* | *(not on board)* | **Machine's own T2/T3/T4 transformer** | ~24 VAC measured | n/a | Nothing on-board sources it. Relay *contacts* switch it externally. |

Two ground nets exist and must never be tied together on the board:

- **`GND`** — logic ground. Reference for the Pi, Pico, MCP23017s, NE555, relay-coil drive,
  status-LED drivers, and the *logic* side of every optocoupler.
- **`FIELD_GND`** — isolated field ground. The return of the TMA-0505S secondary and the reference
  for the *field* side of the dry-contact input optos. Kept in its own layout room with all-copper
  keepout gutters (see Section 13, *Layout / Isolation*). The isolation audit confirmed `GND` and
  `FIELD_GND` share **zero** nodes on the routed board.

> **No on-board PoE in v1.** Rev-B v1 has no Power-over-Ethernet PD circuit. 5 V comes in over wire
> at J2. PoE is explicitly out of scope for this revision.

---

### 6.2 The 5 V Logic Input — `J_PWR` (J2) and SS14 Protection

#### 6.2.1 Connector and source

External regulated 5 V enters the board at **`J_PWR`**, which is reference designator **J2** on the
silkscreen.

| Item | Value |
|---|---|
| Refdes | **J2** |
| Function | Regulated 5 V logic/input power in |
| Part | Phoenix Contact **MKDS 1,5/3-5,08** screw terminal (MPN **1715734**) |
| Footprint | `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal` |
| Pitch | 5.08 mm, horizontal wire entry |
| Positions | 3 |

J2 is a **fixed screw terminal block**, not a pluggable header — bare wires land directly in it and
there is **no off-board mating plug** (it does not appear in the harness-mating-parts list). Pinout
per the netlist generator (`block_connectors`):

| J2 pin | Net | Notes |
|---|---|---|
| 1 | `VCC_5V_RAW` | +5 V in (pre-protection) |
| 2 | `GND` | Logic ground |
| 3 | `GND` | Logic ground (second ground landing) |

The 5 V source itself is **off-board** and is *not* a placed BOM part. The Rev-B power contract
allows either a DIN-rail regulated 5 V PSU (the BOM-power draft cites an **HDR-15-5**-class supply
as the example) or the Raspberry Pi's own 5 V distribution. Whatever is chosen must be a *regulated*
5 V rail sized for the worst-case load in Section 6.6. (VERIFY: the exact off-board 5 V PSU make/model is
not fixed in any fab artifact — it is specified only as "regulated 5 V, HDR-15-5 class or Pi 5 V" and
must be selected at install.)

#### 6.2.2 Reverse-polarity + transient protection — D17 (SS14)

Immediately after J2, the raw input passes through a series **Schottky diode** that protects the
whole board against a reversed supply and clamps input transients.

| Item | Value |
|---|---|
| Refdes | **D17** |
| Part | **SS14** Schottky (1 A, 40 V, SMA / DO-214AC) |
| LCSC | **C2480** (MDD) |
| Footprint | `Diode_SMD:D_SMA` |
| Symbol | `Device:D_Schottky` (tag `D_PROT` in the generator) |

Orientation (from `block_connectors`): **anode → `VCC_5V_RAW`, cathode → `VCC_5V`.** This is a
series diode in the +5 V line:

```
J2.1 (VCC_5V_RAW) --->|--- VCC_5V   (D17 anode on the raw side, cathode on the protected side)
                     SS14
```

How it protects the board:

- **Reverse polarity:** if 5 V and GND are swapped at J2, D17 is reverse-biased and blocks current
  — the board sees nothing rather than back-powering through every IC. This is the classic
  series-Schottky reverse-battery guard; a Schottky is used so the forward drop is small.
- **Forward drop / why "protected 5 V" is a bit below 5 V:** in normal operation D17 drops roughly
  0.3–0.5 V (its Schottky Vf at the board's load current), so `VCC_5V` sits a few hundred millivolts
  below the input. This is intentionally fine: the Pico runs from VSYS down to ~1.8 V via its
  internal buck-boost, the G5LE 5 V relay coils tolerate the small drop, and the TMA-0505S accepts a
  ±10 % input window. Size the upstream PSU so that **after** the SS14 drop the rail is still a
  healthy ~4.6–4.8 V under full relay load.
- **Transient clamping:** the Schottky plus the board's bulk/decoupling capacitance (the 3V3 bulk
  `C_3V3_BULK` 10 µF on the downstream side and the NE555 `C_WDOG_VCC` 0.1 µF) absorb the small
  inductive kicks from the supply leads. The board does *not* carry a large input bulk electrolytic
  on `VCC_5V` in this revision; the heavy inductive energy (relay-coil flyback) is handled locally at
  each coil by its own flyback diode (Section 6.5), not at the input.

> ⚠️ D17 is a **1 A** part. It carries the *entire* board's 5 V draw (logic + all energized relay
> coils + the TMA-0505S primary). The Section 6.6 budget shows the worst case is well under 1 A, but
> if relay count or coil current ever grows, re-check D17's rating before populating.

---

### 6.3 The 3.3 V Logic Rail — `VCC_3V3` from the Pico

There is **no dedicated 3.3 V regulator** on the Rev-B v1 board. The 3.3 V rail is taken from the
**Raspberry Pi Pico module's own 3V3 output**.

| Item | Value |
|---|---|
| Source | Pico module **pin 36** (3V3 OUT), net `VCC_3V3` |
| Pico refdes | **A1** (Raspberry Pi Pico, SC0915) |
| Local decoupling | `C_3V3_BULK` (10 µF, 0805) to GND, plus a 0.1 µF (`C_<refdes>`) at each MCP23017 |

From `block_rp2040`: `VCC_5V` feeds the Pico's **VSYS (pin 39)**, and the Pico's on-board regulator
produces 3.3 V at **pin 36**, which the board uses as `VCC_3V3`. The Pico's eight GND pins (3, 8, 13,
18, 23, 28, 33, 38) tie to logic `GND`.

What `VCC_3V3` feeds and **why it must be 3.3 V, not 5 V:**

- **All three MCP23017 I²C expanders** (VDD pin 9 and ~RESET pin 18 of each — see `block_mcp`).
- **Every PC817 optocoupler logic-side pull-up** — Rev-B `Rpu_*` is 10 kΩ;
  current Rev-D/R5 `Rpu_*` is **47 kΩ**. The opto phototransistor collector is
  held at `VCC_3V3` when idle; RP2040 and MCP23017 internal pulls stay disabled
  so the external Rev-D network is the sole bias.
- **The single I²C bus pull-ups** (`R_I2C_SDA`, `R_I2C_SCL`, 4.7 kΩ each to `VCC_3V3`).

The MCP23017s and the opto logic side run at **3.3 V specifically so the I²C bus and all logic
signals are Raspberry Pi-safe.** The Pi's GPIO/I²C pins are 3.3 V and are **not** 5 V tolerant.
Running the MCP23017s at 5 V on the Pi's I²C bus without a level shifter would drive 5 V logic highs
back into the Pi and risk damaging it. The contract is explicit: *do not run the MCP23017s at 5 V on
the Raspberry Pi I²C bus.* If a future cost-down revision replaces the Pico stamp with a bare RP2040,
that revision must add a dedicated 3.3 V regulator (the BOM names AP2112K-3.3 / NCP1117-3.3 as
candidates) to replace this Pico-sourced rail.

> **Consequence for bench bring-up:** because 3.3 V comes from the Pico, **there is no 3.3 V on the
> board until the Pico module is fitted and powered.** A board with A1 unpopulated will have 5 V and
> the isolated field rail but a dead 3.3 V rail — the MCP23017s and opto pull-ups will not come up.
> Fit and power the Pico first (it is hand-soldered after SMT assembly; see Section 6.7).

---

### 6.4 The Isolated Field-Wetting Supply — TMA-0505S (U37)

Dry-contact machine inputs (cams, grippers, switches) carry no voltage of their own — they are bare
contacts that simply open or close. To sense them, the board has to **provide its own "wetting"
voltage** that the contact switches. Per the Rev-B safety contract, that wetting supply must be
**galvanically isolated from logic ground**, so that a machine-side short or fault on the field
wiring cannot back-feed into the Pi/logic domain.

#### 6.4.1 The part

| Item | Value |
|---|---|
| Refdes | **U37** |
| Part | **TRACO Power TMA-0505S** — isolated 5 V → 5 V, 1 W, SIP DC/DC converter |
| Output | **5 V, 200 mA** |
| Isolation | ~1.5 kVDC class (VERIFY: exact isolation voltage taken from TRACO datasheet, not re-stated in the fab CSVs — the BOM-power draft specifies "≥1.5 kV isolation") |
| Footprint | `Converter_DCDC:Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT` |
| Source/notes | DigiKey 1951-1003-ND; **"Locked exact part"** — do not substitute without pinout + isolation review |

#### 6.4.2 Connections

From `block_supplies`:

| TMA-0505S pin | Net | Role |
|---|---|---|
| +Vin | `VCC_5V` | Primary (logic-side) input |
| −Vin | `GND` | Logic ground |
| +Vout | `FIELD_WET_V` | Isolated wetting rail (field side) |
| −Vout | `FIELD_GND` | Isolated field ground (field side) |

The converter's input side sits in the logic domain; its output side sits entirely in the field
domain. The 1.5 kV-class isolation barrier *inside* U37 is what keeps `FIELD_GND` from ever bonding
to `GND`.

#### 6.4.3 How the wetting rail is used

The wetting rail feeds **only** the field side of the dry-contact opto front-ends. For each
dry-contact input (most grippers and switches), `block_input`/`opto_input` wires:

```
FIELD_WET_V --- Rin (2.2k) --->|(PC817 LED)|--- field pin (J_FAST/J_SLOW_*) ---[machine contact]--- FIELD_GND
```

When the machine contact **closes**, it completes the loop from `FIELD_WET_V` through the 2.2 kΩ
series resistor (`Rin_*`) and the PC817 LED to `FIELD_GND`, lighting the opto LED. The opto's
logic-side phototransistor then pulls its logic net **LOW** (idle is HIGH via the external
`VCC_3V3` `Rpu_*`: 10 kΩ on historical Rev-B, **47 kΩ on current Rev-D/R5**). All inputs are
therefore **active-low at the logic side** — see Section 8, *Input Stage*, and the firmware note
(`INPUT_ACTIVE_LOW = True`). Rev-D production also requires RP2040 PUE/PDE off and U1/U2
MCP23017 `GPPUA/GPPUB=0x00` with readback.

#### 6.4.4 Why 200 mA / 1 W is ample

Only the optos of inputs that are *closed at that instant* draw wetting current, and each PC817 LED
draws on the order of ~1–2 mA through its 2.2 kΩ series resistor at this rail voltage. Even with many
contacts closed simultaneously the total is well under 100 mA, comfortably inside the TMA-0505S
200 mA / 1 W envelope. The single brick serves **all** dry-contact channels on the board (the 10
gripper inputs plus GP/OS/BS/PBZ/PBC and the manual/aux channels — see Section 8).

> **Two input front-end flavors (population-selectable per channel).** Each input channel can be
> populated for either:
> 1. **Dry-contact** — wetting from `FIELD_WET_V` as above (the confirmed default; the machine's cams
>    measured as dry, normally-closed contacts), or
> 2. **24 VAC sense** — a Rev-A-style rectifier interposer (1N4007 half-wave + bulk cap + bleed) into
>    the opto, for any channel that turns out to carry 24 VAC.
>
> The TMA-0505S serves the dry option; the interposer serves the AC option. Final per-channel
> population is set at cutover. See Section 8 for the per-channel detail.

---

### 6.5 The Relay Coil Rail — `RELAY_ENABLE_RAIL`

The motion-output relays are **Omron G5LE-14 with a 5 VDC coil** (refdes K1–K6; LCSC **C116963**).
Their coils are *not* wired straight to `VCC_5V`. Instead they hang off a **gated** rail called
`RELAY_ENABLE_RAIL`, which is the electrical enable for all motion. This is the heart of the
hardware safety design and is covered in full in Section 10, *Safety Rail*; here we cover only the
power/load aspect.

> ⚠️ **Critical part note:** the relay coil is **5 VDC**. Do **not** substitute a 9 V, 12 V, or 24 V
> coil variant — the rail and drive are designed for the ~79 mA, 5 V G5LE-14 coil.

#### 6.5.1 Coil supply topology

`RELAY_ENABLE_RAIL` is sourced from `VCC_5V` through a **P-channel pass FET (AO3401A, refdes Q14)**.
The PCB provides two J_SAFETY series positions, but the released Candidate-C harness closes pins
1–2 with the controlled jumper rather than landing TB/SC there. Q14 also requires watchdog OK,
ARM, RP2040 OK/cam-stop, and continuity through the J_SAFE3-4 source position. On the current
lane-21/22 harness, 3–4 is physically OPEN/unlanded, so the field rail cannot arm; never jumper it
at the machine. The leading field design uses an externally mounted, correctly rated,
energize-to-prove control-power relay; only its isolated N.O. dry contact may reach J14, optionally
in series with an approved new pit-entry-interlock contact. Machine voltage and mains never enter
Rev-D. Primary TB/SC protection is separate:
the OEM parallel-safe contacts remain in the S/T coil circuits and must pass the per-lane G3
insertion proof. When any implemented on-board condition fails, Q14 turns off and the rail collapses.

Per `relay_output`, each motion channel wires its coil between the rail and a low-side NPN switch:

```
RELAY_ENABLE_RAIL --- relay coil (G5LE pin 1 -> pin 2) --- MMBT3904 collector --- (emitter) GND
        |                                                        ^
        +------------|<--- flyback diode (1N4148WS) ------------+   (cathode to rail, anode to coil low side)
```

- **High side of every coil = `RELAY_ENABLE_RAIL`** (G5LE coil pin 1). The rail is the single point
  that arms or disarms all coils at once.
- **Low side switched by an NPN** (`Qk_<name>`, MMBT3904) commanded from the MCP23017 OUT-A through a
  1 kΩ base resistor (`Rb_<name>`) with a 100 kΩ base pulldown — so an undriven/floating logic line
  defaults the coil **off**.
- **Flyback diode across each coil** (`Dfly_<name>`, **1N4148WS**, SOD-323): cathode to the rail,
  anode to the switched coil-low node, clamping the coil's inductive kick when it turns off. This is
  why the input does not need a large bulk capacitor — each coil's kick is caught locally.

#### 6.5.2 Coil-load budget for the 5 V rail

The worst case for the 5 V supply is **all populated relay coils energized at once**, plus logic,
plus the isolated-supply primary draw.

| Item | Qty (populated) | Per-unit | Subtotal |
|---|---|---|---|
| G5LE-14 5 V relay coils | **6** (K1–K6: S, T, SP, BE, M, M2) | ~79 mA | ~0.47 A |
| *(M1 ball-return coil — K7)* | **0 (DNP)** | ~79 mA | 0 A (not populated) |
| Logic (Pico VSYS + 3V3 loads + NE555 + optos) | — | — | small (tens of mA) |
| TMA-0505S primary | 1 | ≤ ~0.25 A in (1 W / ~4.7 V, worst case) | ≤ ~0.25 A |
| **Worst-case total** | | | **≈ 0.7–0.9 A** |

The BOM-power analysis lands the relay-coil portion at **~0.55 A** if every coil including a populated
M1 were energized, and concludes the **5 V rail should be ≥ 1.5 A minimum, with a ~3 A (HDR-15-5
class) supply preferred** for headroom. With M1 DNP (only 6 coils) the real coil load is ~0.47 A.
**Specify the external 5 V supply at ≥ 1.5 A; 3 A is the comfortable choice.**

> **M1 is DNP.** The seventh motion relay (M1, ball-return, refdes **K7**) and its driver/flyback are
> present as DNP copper only — they are **not** populated and draw nothing. M1 stays DNP until the
> ball-return command is confirmed to exist as a separate relay on this specific chassis. Do not add
> its coil load to the budget unless you populate K7.

#### 6.5.3 Contact-side suppression (no on-board power)

Each relay's **contacts** (COM/NO) switch the machine's *external* control circuit, not any board
rail. Every motion output has footprints for an **RC snubber** (`Rsnub_*` 100 Ω + `Csnub_*` 10 nF X2)
and an **MOV** across the contact, all **DNP by default**, to be populated after the at-machine
inductive load is characterized. These protect the contacts from arcing into the OEM coil; they carry
machine voltage, not board voltage.

---

### 6.6 Status-LED Drive — Powered from `VCC_5V` Logic

The four mask status indicators (1st-ball, 2nd-ball, strike, foul) are **new LEDs installed in the
existing mask housings and driven from the board's own 5 V logic rail** — the machine's old 15 VDC
mask-lamp supply is **abandoned** in Rev-B and is not used or sensed.

| Item | Value |
|---|---|
| Connector | **`J_LAMP_LED`** = refdes **J13**, Phoenix MCV 1,5/6-G-3,5 (MPN 1843648), 6-pos 3.5 mm |
| J13 pin 1 | `VCC_5V` (LED common anode supply) |
| J13 pin 2 | `GND` |
| J13 pins 3–6 | `LED_L_FIRST_RETURN`, `LED_L_SECOND_RETURN`, `LED_L_STRIKE_RETURN`, `LED_L_FOUL_RETURN` |
| Driver per channel | **2N7002** low-side N-FET (`Qled_*`, refdes Q8–Q11), 1 kΩ gate resistor (`Rgled_*`), 100 kΩ gate pulldown (`Rpdled_*`), series current limit `Rled_*` |
| `Rled_*` value | **330 Ω** in the scaffold (VERIFY: 330R is a TBD placeholder — final value must be locked after choosing LED type/current for brightness in a lit center) |

Drive topology (`lamp_led_output`): the LED anode side is fed `VCC_5V` (J13 pin 1), the LED cathode
returns through the series limit resistor to a 2N7002 low-side FET that sinks to `GND` when the
MCP23017 OUT-A bit drives the gate high. The 100 kΩ gate pulldown defaults the LED **off** on
floating/undriven logic.

These status LEDs are **not motion-critical and are not on the safety rail**, and there is **no
LOGIC-to-MACHINE isolation barrier** for them — they are entirely a logic-domain 5 V load. (See
Section 9, *Output Contract*, for the lamp output table.)

---

### 6.7 What the Board Deliberately Does NOT Power

This is the most safety-relevant part of the power architecture. Several things you might *expect* a
controller to drive are intentionally **off the board**:

| Not on the board | Where it actually comes from / why |
|---|---|
| **Machine 24 V coil power** | The machine's own **T2/T3/T4** transformer (measured ~24 VAC). The board only closes isolated dry relay **contacts** in series with the machine's existing coil circuits — it never sources the coil current. |
| **Motor line power (115 VAC)** | Never routed on the PCB. The S (sweep) and T (table) **machine contactors** continue to switch motor current and keep their OEM run/braking contact behavior. The board may command/interrupt their *control* coils through isolated contacts; it must never become the motor contactor or braking path. |
| **Old 15 VDC mask-lamp supply** | Abandoned. Status indication uses new board-driven LEDs on `VCC_5V` (Section 6.6). The 15 V supply is neither used nor sensed. |
| **PoE / Power-over-Ethernet** | Not in Rev-B v1. 5 V comes in over wire at J2. |
| **Pin lamps (1–10), KX relay** | Omitted in baseline. Camera scoring supplies pin state; the optional pin-lamp output bank (MCP23017 OUT-B, addr 0x23) is not populated. |

**Why machine coil power is never sourced on the board:** the entire Rev-B safety model depends on
the board being able to *fail open* — to remove its influence on the machine — on loss of logic,
watchdog, RP2040 health, arm permission, or the hardware interlock. If the board generated the 24 V
coil power, a board fault could *energize* machine motion. By keeping all machine motion/control
voltages external and only switching them through isolated dry contacts gated by the
`RELAY_ENABLE_RAIL`, the failure mode is always "contacts open, machine sees no command." This also
preserves the OEM contactors' built-in start/run/brake and interlock behavior, which the board must
not replace.

> **Welded-contact limitation (carried from the safety contract):** the rail de-energizes relay
> *coils*; it cannot open a contact that has welded closed. Relay contact rating, snubber/MOV
> population, and validation are therefore safety-relevant, and the **machine's upstream
> Stop / master-breaker chain remains the final physical stop on pilot lanes 21/22**. OEM
> C.I.S. history does not establish an installed device: none was found on either pilot.
> See Section 10, *Safety Rail*.

---

### 6.8 Assembly Notes Relevant to Power (JLC split + hand-soldered parts)

Because the power architecture spans SMT, through-hole, and consigned parts, the fab package splits
assembly as follows (from the fab-package README and BOM CSVs):

| Power-related part | Refdes | Assembly path |
|---|---|---|
| SS14 input-protection diode | D17 | **JLC SMT** (LCSC C2480) |
| G5LE-14 5 V relays | K1–K6 | **JLC** places them (THT/wave) |
| PC817B optos (field front-ends) | U4–U35 | **JLC** places them |
| MCP23017 expanders | U1–U3 | **JLC SMT** (LCSC C47023) |
| NE555 watchdog timer | U36 | **JLC SMT** (NE555DR, LCSC C7593) |
| **Raspberry Pi Pico** (3.3 V source) | **A1** | **Hand-soldered after assembly** — program after fitting; use the castellated SC0915, *not* a Pico with pre-soldered headers |
| **TMA-0505S isolated supply** | **U37** | **Hand-soldered / consigned** — not in the JLC standard PCBA upload |
| J_PWR 5 V terminal | J2 | Phoenix screw terminal, hand-soldered/THT |
| J_LAMP_LED | J13 | Phoenix MCV header, hand-soldered/THT |

Practical bring-up implication: a JLC-assembled bare board arrives **without A1 and without U37**.
Until A1 (Pico) is fitted you have `VCC_5V` (via D17) but **no `VCC_3V3`** — the MCP23017s and opto
pull-ups stay dark. Until U37 is fitted you have no `FIELD_WET_V` — dry-contact inputs cannot be
sensed. Fit and verify rails in the order: 5 V in → confirm `VCC_5V` after D17 → fit A1, confirm
3.3 V at Pico pin 36 → fit U37, confirm isolated `FIELD_WET_V`/`FIELD_GND` and confirm `FIELD_GND` is
*not* continuous with `GND`. (See Section 21, *Bench Bring-Up*, for the full sequence.)

---

### 6.9 Quick Reference — Power Test Points & Expected Values

| Where to probe | Net | Expected |
|---|---|---|
| J2 pin 1 to pin 2 | `VCC_5V_RAW` to `GND` | +5 V from the external PSU |
| D17 cathode | `VCC_5V` to `GND` | ~4.6–4.8 V (input minus SS14 Vf) under load |
| Pico pin 36 | `VCC_3V3` to `GND` | +3.3 V (only with A1 fitted + powered) |
| TMA-0505S +Vout to −Vout | `FIELD_WET_V` to `FIELD_GND` | +5 V isolated (only with U37 fitted) |
| `FIELD_GND` to `GND` | — | **Open / no continuity** (isolation intact) |
| `RELAY_ENABLE_RAIL` (TP16) | rail | ≈ `VCC_5V` only when full safety chain satisfied; **0 V** otherwise |

The `RELAY_ENABLE_RAIL` reaches all relay coils and test point **TP16**; probing it is the fast way to
confirm whether the safety chain is permitting motion. Board envelope for reference: **250 × 225 mm,
4 copper layers, 1.6 mm stackup.**

---

**Cross-references:** Section 9 (*Output Contract / Relay Stage* — contact forms, M1 DNP, snubber/MOV);
Section 8 (*Input Stage* — dry-vs-AC front-ends, active-low sense, J_FAST/J_SLOW pinouts); Section 10
(*Safety Rail* — the `RELAY_ENABLE_RAIL` gate chain and fail-open behavior); Section 13 (*Layout /
Isolation* — logic/field/machine domain rooms and creepage); Section 21 (*Bench Bring-Up*).
