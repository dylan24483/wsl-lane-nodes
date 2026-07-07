## 11. Rev-B Connector Pinouts (J1-J14)

This section is the authoritative pin-by-pin reference for every connector on the
Phase 8 Rev-B lane-controller PCB. Every pin, net name, and part number below is
taken directly from the live board sources:

- **`scripts/generate_kicad_netlist_revB.py`** — `block_connectors()`, `block_rail()`,
  `opto_input()`, `relay_output()`, `lamp_led_output()`, `block_rp2040()`. This is
  the generator that *emits the netlist the routed board is built from*, so it is the
  primary source of truth for connectivity and net names.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-cpl.csv`** — the placed
  reference designators (J1..J14) and their footprints.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`**
  and **`...-bom-non-dnp.csv`** / **`...-dnp-excluded.csv`** — the as-ordered part numbers.
- **`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-harness-mating-parts.csv`**
  and **`...-offboard-hardware.csv`** — the off-board mating plugs.

If you are reading this cold, read **Section 5 (Electrical Domains)**,
**Section 10 (Safety Rail)**, and **Section 8 (Input Front-Ends)** first — the *why*
behind each pin lives there. This section is the *what*.

> **Cross-references:** firmware GPIO map is in **Section 15 (RP2040 Firmware)**; the
> per-chassis harness that maps these function-named connectors to the AMF 82-70 C1/C2A
> machine connectors is **Section 14 (Adapter Harness & Cutover)**; relay/opto theory is
> **Section 9 (Relay Output Stage)** and **Section 8 (Opto Input Stage)** (adjust numbers
> to match the assembled manual).

---

### 11.0 Why the connectors are function-named (read this first)

The board is **one PCB per lane**. Its connectors are named by *electrical function*
(`J_FAST_IN`, `J_MOTION_S`, `J_SAFETY`, ...), **not** by the machine cavity they will
eventually land on. This is deliberate and non-negotiable per the Rev-B contract
(`phase8b_pcb_revB_spec.md` §1, §7): the OEM AMF wire tables and our bench
measurements on the SS + Omega-Tek retrofit at lanes 21/22 **disagree** on which C1/C2A
cavity carries which signal (e.g. OEM routes sweep-reverse M2 on C1; our bench measured
M2 → C2A direct 0 Ω). Both are correct for their chassis. Baking a cavity number into
copper would make the board single-chassis. Instead:

- **The PCB exposes function-named channels.**
- **A per-chassis adapter harness** maps each channel to the correct C1/C2A cavity at
  cutover. See **Section 14**.

Treat every machine-facing pin in this section as a **field-domain** net (galvanically
isolated from logic ground through an opto or a relay contact) unless it is explicitly a
logic/Pi pin on J1.

#### Connector index

The reference designators (J-numbers) are fixed by the placement file. The board screens
each connector with both its J-number and its function name.

| Ref | Function name | Footprint | Positions | Domain | Mating plug (off-board) |
|---|---|---|---|---|---|
| **J1** | `J_PI` | IDC-Header 2x10, 2.54 mm vertical | 20 | Logic | 2x10 IDC ribbon socket (CNC Tech 3030-20-0102-00 *candidate*) |
| **J2** | `J_PWR 5V` | Phoenix MKDS 1,5/3-5.08, horizontal screw | 3 | Logic power in | Wires land directly in the fixed screw block (no separate plug) |
| **J3** | `J_FAST_IN` | Phoenix MCV 1,5/10-G-3,5 vertical | 10 | Field sense | Phoenix MC 1,5/10-ST-3,5 (PN 1840447) |
| **J4** | `J_SLOW_IN_A` | Phoenix MCV 1,5/14-G-3,5 vertical | 14 | Field sense | Phoenix MC 1,5/14-ST-3,5 (PN 1840489) |
| **J5** | `J_SLOW_IN_B` | Phoenix MCV 1,5/12-G-3,5 vertical | 12 | Field sense | Phoenix MC 1,5/12-ST-3,5 (PN 1840463) |
| **J6** | `J_MOTION_S` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | Wires land directly in the fixed screw block |
| **J7** | `J_MOTION_T` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J8** | `J_MOTION_SP` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J9** | `J_MOTION_BE` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J10** | `J_MOTION_M` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J11** | `J_MOTION_M2` | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | direct screw |
| **J12** | `J_MOTION_M1` **(DNP)** | Phoenix MKDS 1,5/2-5.08, horizontal screw | 2 | Machine output (dry contact) | **NOT POPULATED** — footprint only |
| **J13** | `J_LAMP_LED` | Phoenix MCV 1,5/6-G-3,5 vertical | 6 | Logic (LED drive) | Phoenix MC 1,5/6-ST-3,5 (PN 1840405) |
| **J14** | `J_SAFETY` | Phoenix MCV 1,5/4-G-3,5 vertical | 4 | Safety rail (interlock loops) | Phoenix MC 1,5/4-ST-3,5 (PN 1840382) |

> **J12 is the only DNP connector.** The M1 (ball-return) channel — connector J12, relay
> K7, driver Q7, R85/R86/R87, D13/D14, snubber C10 — is **Do Not Populate**. The FSM does
> not drive a ball-return relay and M1 was never bench-confirmed as a separate command on
> our chassis (`phase8b_pcb_revB_spec.md` §3.2, §11 item 6). The copper exists for a future
> chassis; do not stuff it until verified at-machine. It is excluded from the BOM and
> pick-and-place files. All other J-numbers are populated.

> **Footprint-vs-mating-plug note.** The two-row Pi header (J1) and the 3.5 mm field
> connectors (J3/J4/J5/J13/J14) are *pluggable* — they need a mating plug (right-hand
> column). The 5.08 mm blocks (J2 and all J_MOTION_*) are *fixed screw terminals*: bare
> wire lands directly under the screw, no plug. Order the Phoenix `...-ST-3,5` plugs with
> the harness, one of each per board.

---

### 11.1 Domain & polarity conventions used in these tables

These conventions hold across every table below. They come from `opto_input()`,
`relay_output()`, `lamp_led_output()`, and `block_rail()` in the generator, and from
`firmware/rp2040/config.h` / `lane_node/controller_io.py`.

- **Direction** is given from the **board's** point of view:
  *IN* = signal flows into the board (a field sense), *OUT* = board drives/contacts out,
  *PWR* = power into the board, *BIDIR* = bidirectional bus (I2C).
- **Domain** is one of: **LOGIC** (3.3 V / 5 V referenced to logic GND), **FIELD**
  (machine-side, referenced to `FIELD_GND`, isolated from logic by the opto), **MACHINE
  OUTPUT** (a floating relay dry contact), or **SAFETY** (the relay-enable interlock loop).
- **All field inputs are dry-contact wetting by default.** Each input opto LED is fed from
  the isolated `FIELD_WET_V` rail (the TMA-0505S, U37, ~5 V isolated) through a 2.2 kΩ
  series resistor (`Rin`), and the field contact, when **closed**, returns that pin to
  `FIELD_GND` and lights the opto LED. So a **closed machine contact = opto ON**. See
  Section 5 / Section 10 for the optional 24 VAC-sense population. `FIELD_GND` and logic
  `GND` share **zero** nodes on the board — the isolation barrier is intact.
- **All opto outputs are ACTIVE-LOW at the controller.** The opto transistor pulls the
  logic pin LOW when its LED is on (contact closed). Idle = HIGH via an on-board 10 kΩ
  pull-up to 3V3 (`Rpu`). Firmware (`config.h`) and `controller_io.py`
  (`INPUT_ACTIVE_LOW = True`) both invert this: **asserted/closed reads logical 1.**
- **Relay contacts are isolated dry NO contacts.** For every `J_MOTION_*`: **pin 2 = COM**
  (`OUT_x_A`, relay pad 1), **pin 1 = NO** (`OUT_x_B`, relay pad 3). The board never sources
  the voltage on these pins; the machine control circuit does. The contact closes only when
  (a) the FSM commands the bit AND (b) the hardware safety rail is up (Section 10).

---

### 11.2 J1 — `J_PI` (Pi logic interface, 2x10 IDC, 2.54 mm)

This is the only link to the Raspberry Pi. It carries the I2C bus to the three MCP23017
expanders, the UART to the RP2040, the watchdog kick, the arm-permit line, both MCP
interrupt lines, the RP2040-OK rail-permission line, and both logic rails. The footprint
is `Connector_Generic:Conn_02x10_Odd_Even` → **KiCad odd/even numbering**: odd pins
(1,3,5,…,19) run down one row, even pins (2,4,6,…,20) down the other, with pin 1 and pin 2
side-by-side at the pin-1 end of the header.

The generator wires **pins 1–13**; **pins 14–20 are no-connect** (reserved).

| Pin | Signal | Net name | Dir (board) | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V logic | `VCC_5V` | PWR in | LOGIC | Main 5 V rail (also fed by J2 through reverse-prot diode D17). |
| 2 | Logic ground | `GND` | — | LOGIC | |
| 3 | I2C SDA | `I2C_SDA` | BIDIR | LOGIC | 3.3 V bus; 4.7 kΩ pull-up to 3V3 on board (R1). MCP23017 ×3. |
| 4 | I2C SCL | `I2C_SCL` | BIDIR | LOGIC | 3.3 V bus; 4.7 kΩ pull-up to 3V3 on board (R2). |
| 5 | Pi UART TX → Pico RX | `PI_UART_TX` | IN | LOGIC | Pi transmit → RP2040 GP1 (Pico pin 2). 115200 8N1. |
| 6 | Pi UART RX ← Pico TX | `PI_UART_RX` | OUT | LOGIC | RP2040 GP0 (Pico pin 1) → Pi receive. |
| 7 | Watchdog kick | `WDOG_KICK` | IN | LOGIC | Pi pulse that re-triggers the NE555 monostable (U36). Missing kick → rail drops. |
| 8 | Arm permit | `ARM_PERMIT` | IN | LOGIC | Pi GPIO; one series condition of the relay-enable rail. HIGH = permit. |
| 9 | MCP INT-A | `MCP_INT_A` | OUT | LOGIC | Interrupt from MCP23017 IN-A (U1, INTA pin 20). Optional. |
| 10 | MCP INT-B | `MCP_INT_B` | OUT | LOGIC | Interrupt from MCP23017 IN-B (U2, INTA pin 20). Optional. |
| 11 | +3.3 V logic | `VCC_3V3` | PWR | LOGIC | 3.3 V rail (sourced by the Pico's onboard regulator, Pico pin 36). Powers the MCPs + opto logic side. |
| 12 | Logic ground | `GND` | — | LOGIC | Second GND for ribbon return integrity. |
| 13 | RP2040 OK | `RP2040_OK` | OUT | LOGIC/SAFETY | RP2040 GP2 health/permission. HIGH = permit motion, LOW = drop rail. Hard rail condition (Section 10). |
| 14–20 | *(no connect)* | — | — | — | Reserved; not wired by the generator. |

**Operating theory.** J1 is split across two responsibilities. Pins 3/4 (I2C) and 9/10
(INT) are the *slow* path: the Pi talks to the three MCP23017s to read slow switches and
drive the relay/lamp command bits. Pins 5/6 (UART) are the *fast/safety* path: the RP2040
co-processor owns the cam and ball-detect inputs and streams events to the Pi, while
**independently** holding pin 13 (`RP2040_OK`) high only while its firmware is alive and no
cam-stop/max-run fault is latched. Pins 7 (`WDOG_KICK`), 8 (`ARM_PERMIT`), and 13
(`RP2040_OK`) are three of the series conditions that must *all* be true for the
relay-enable rail to come up — the Pi cannot energize a motion relay in software alone.

> **UART naming gotcha (do not crosswire).** The net names are from the *Pi's*
> perspective. `PI_UART_TX` (pin 5) is the Pi's transmit; on the board it lands on the
> Pico's **RX** (GP1). `PI_UART_RX` (pin 6) is the Pi's receive; on the board it lands on
> the Pico's **TX** (GP0). `config.h` confirms: `PIN_UART_TX 0 (GP0) → Pi RX, net PI_UART_RX`
> and `PIN_UART_RX 1 (GP1) ← Pi TX, net PI_UART_TX`. The crossover is already done on the
> PCB; wire the ribbon straight-through.

> **(VERIFY: ribbon pin-1 / keying convention.)** The placed footprint defines the pad
> numbers above, but the *physical ribbon orientation* (which conductor is pin 1, shroud
> keying) is flagged "confirm cable keying/orientation" in the working BOM and the J1
> mating-plug row is a "candidate." Confirm pin-1 alignment between board and Pi before
> crimping the ribbon.

---

### 11.3 J2 — `J_PWR 5V` (regulated 5 V input, 3-pin screw, 5.08 mm)

External regulated 5 V enters here. This rail powers the logic (Pico, MCP23017s, NE555),
the opto logic sides, the isolated field-wetting DC/DC (U37), the relay coils, and the
status LEDs. Two ground pins are provided for current return.

| Pin | Signal | Net name | Dir (board) | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V raw in | `VCC_5V_RAW` | PWR in | LOGIC | Feeds the board through reverse-polarity Schottky D17 (SS14). |
| 2 | Ground | `GND` | — | LOGIC | |
| 3 | Ground | `GND` | — | LOGIC | Second return pin for coil/LED current. |

**Operating theory.** `VCC_5V_RAW` (pin 1) passes through series Schottky **D17 (SS14)**
to become the protected `VCC_5V` rail (D17 anode = RAW, cathode = `VCC_5V`). This blocks
reverse-polarity damage at the cost of ~0.4 V drop, so the on-board 5 V rail sits slightly
below the supply. `VCC_5V` and the J1 pin-1 5 V are the **same net** after the diode — do
not feed 5 V into both J1 and J2 from two different supplies. Size the supply for
worst-case simultaneous relay coil load (6 populated G5LE coils ≈ 6 × ~40 mA) + logic +
LEDs + margin (`phase8b_pcb_revB_spec.md` §8.1, §11 item 2).

> **(VERIFY: 5 V supply current budget.)** The spec lists "relay coil rail budget"
> (worst-case relay count incl. any M1 decision) as an open assembly-blocking item; the
> exact supply sizing is not pinned in the sources.

---

### 11.4 J3 — `J_FAST_IN` (RP2040 fast inputs, 10-pin, 3.5 mm)

The eight fast machine signals the **RP2040** services directly: sweep cams, table cams,
the two interlock-cam echoes, and the two DIELL ball-detect beams. Each lands on a PC817
opto front-end and then on a Pico GPIO. These are the timing-critical, edge-capable inputs;
they must not get slow RC/firmware debounce that masks cam overlap (Section 5.1).

Pin order follows `FAST_INPUTS` in the generator. Pins 9–10 are the isolated field-ground
return for the dry-contact wetting.

| Pin | Signal | Field net | Logic net | Pico GPIO (pin) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | SA | `FIELD_FAST_SA` | `FAST_SA` | GP6 (Pico 9) | IN | FIELD | Sweep cam (270 run-through stop / 360 zero). |
| 2 | SB | `FIELD_FAST_SB` | `FAST_SB` | GP7 (Pico 10) | IN | FIELD | Sweep guard cam (66 guard / 186 table-spot init). |
| 3 | SC | `FIELD_FAST_SC` | `FAST_SC` | GP8 (Pico 11) | IN | FIELD | Sweep-under-table interlock window (86–243); also the SC interlock echo. |
| 4 | TA1 | `FIELD_FAST_TA1` | `FAST_TA1` | GP9 (Pico 12) | IN | FIELD | Table cam (355 zero stop / 185 delay reset). |
| 5 | TA2 | `FIELD_FAST_TA2` | `FAST_TA2` | GP10 (Pico 14) | IN | FIELD | Table cam (260 run-through / pin-latch / decision). |
| 6 | TB | `FIELD_FAST_TB` | `FAST_TB` | GP11 (Pico 15) | IN | FIELD | Table-sweep interference interlock cam (105–255). |
| 7 | DIELL-L | `FIELD_FAST_DIELL_L` | `FAST_DIELL_L` | GP12 (Pico 16) | IN | FIELD | Ball detect, left beam (cushion SS cycle trigger). |
| 8 | DIELL-R | `FIELD_FAST_DIELL_R` | `FAST_DIELL_R` | GP13 (Pico 17) | IN | FIELD | Ball detect, right beam. |
| 9 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return (shared with pin 10). |
| 10 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return. |

**Operating theory.** Each fast channel is one PC817 (U4…U11) wired by `opto_input()`:
`FIELD_WET_V` → 2.2 kΩ (`Rin`) → opto LED anode; opto LED cathode → the J3 field pin. The
machine contact (a cam microswitch) between that pin and `FIELD_GND` (pins 9/10) completes
the LED loop when closed, turning the opto on and pulling the Pico GPIO LOW through the
transistor; idle is held HIGH by a 10 kΩ pull-up to 3V3 (`Rpu`). The RP2040 reads these
edges with a 2 ms cam debounce / 500 µs DIELL debounce (`config.h`), enforces cam-stop and
an 8 s motion max-run backstop, and forwards events to the Pi over the J1 UART. **Because
the RP2040 owns these and gates `RP2040_OK`, a fault on a fast input drops the motion rail
in hardware, not just in software.**

> **GPIO source-of-truth note.** The Pico GPIO column above is from `block_rp2040()` /
> `config.h` (GP6–GP13). The older `docs/phase8_channel_allocation.md` §2 GPIO column
> (GP0–GP7) is **STALE** and must be ignored — `config.h` says so explicitly.

> **(VERIFY: per-channel input population — dry-contact vs 24 VAC sense.)** The tables show
> the **default dry-contact wetting** front-end. The Rev-B contract requires choosing
> dry-contact vs 24 VAC-rectified sense *per channel* after at-machine measurement
> (`phase8b_pcb_revB_spec.md` §5.1, §5.3, §11 item 4). Not yet locked.

---

### 11.5 J4 — `J_SLOW_IN_A` (MCP IN-A slow inputs, 14-pin, 3.5 mm)

The high-use slow inputs read by **MCP23017 IN-A (U1, I2C 0x20)**: the ten gripper switches
plus gripper-protect, off-spot, and bin/#9. Same dry-contact opto front-end as J3, but the
logic side lands on MCP23017 GPA/GPB pins instead of the Pico. Pin order follows
`slowa_order` in the generator; pin 14 is the field-ground return.

| Pin | Signal | Field net | Logic net | MCP IN-A pin (port,bit) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | GS1 | `FIELD_SLOW_GS1` | `SLOW_GS1` | 21 (GPA0) | IN | FIELD | Gripper switch 1 (standing-pin sense, bit 0). |
| 2 | GS2 | `FIELD_SLOW_GS2` | `SLOW_GS2` | 22 (GPA1) | IN | FIELD | Gripper switch 2. |
| 3 | GS3 | `FIELD_SLOW_GS3` | `SLOW_GS3` | 23 (GPA2) | IN | FIELD | Gripper switch 3. |
| 4 | GS4 | `FIELD_SLOW_GS4` | `SLOW_GS4` | 24 (GPA3) | IN | FIELD | Gripper switch 4. |
| 5 | GS5 | `FIELD_SLOW_GS5` | `SLOW_GS5` | 25 (GPA4) | IN | FIELD | Gripper switch 5. |
| 6 | GS6 | `FIELD_SLOW_GS6` | `SLOW_GS6` | 26 (GPA5) | IN | FIELD | Gripper switch 6. |
| 7 | GS7 | `FIELD_SLOW_GS7` | `SLOW_GS7` | 27 (GPA6) | IN | FIELD | Gripper switch 7. |
| 8 | GS8 | `FIELD_SLOW_GS8` | `SLOW_GS8` | 28 (GPA7) | IN | FIELD | Gripper switch 8. |
| 9 | GS9 | `FIELD_SLOW_GS9` | `SLOW_GS9` | 1 (GPB0) | IN | FIELD | Gripper switch 9. |
| 10 | GS10 | `FIELD_SLOW_GS10` | `SLOW_GS10` | 2 (GPB1) | IN | FIELD | Gripper switch 10. |
| 11 | GP | `FIELD_SLOW_GP` | `SLOW_GP` | 3 (GPB2) | IN | FIELD | Gripper protect. |
| 12 | OS | `FIELD_SLOW_OS` | `SLOW_OS` | 4 (GPB3) | IN | FIELD | Off-spot. |
| 13 | BS | `FIELD_SLOW_BS` | `SLOW_BS` | 5 (GPB4) | IN | FIELD | Bin / #9 (back-stop / bin-full). |
| 14 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return for J4. |

**Operating theory.** Identical front-end to J3 (`opto_input()` → PC817 U12…U24), but the
opto transistors drive **MCP23017 IN-A** pins instead of the Pico. The Pi reads the whole
bank over I2C. The ten GS bits form the **standing-pin mask** the scoring/FSM logic uses;
`controller_io.py read_grippers()` slices `GS1=bit0 … GS10=bit9`, treating a *closed* opto
(pin reads 0, active-low) as a *standing* pin. GP/OS/BS are individual reads. None of these
are on the safety rail — they are sense-only.

> **Bit-map alignment.** The (port,bit) column equals `lane_node/controller_io.py`
> `IN_A_MAP`, which is regression-locked against `SLOW_INPUT_PINS` in the generator (the
> module's `__main__` self-test fails on drift). MCP pin → (port,bit): pins 21–28 = GPA0–7
> = (0,0)…(0,7); pins 1–8 = GPB0–7 = (1,0)…(1,7).

> **(VERIFY: per-channel dry-contact vs 24 VAC population)** — same open item as J3.

---

### 11.6 J5 — `J_SLOW_IN_B` (MCP IN-B slow inputs, 12-pin, 3.5 mm)

Manual-operation, 10th-frame, foul, pushbutton, and spare slow inputs, read by **MCP23017
IN-B (U2, I2C 0x21)**. Pin order follows `slowb_order` in the generator; pin 12 is the
field-ground return. (IN-B is configured on the board but is not yet *read* by the current
FSM — see `controller_io.py`.)

| Pin | Signal | Field net | Logic net | MCP IN-B pin (port,bit) | Dir | Domain | Function |
|---|---|---|---|---|---|---|---|
| 1 | PBZ | `FIELD_SLOW_PBZ` | `SLOW_PBZ` | 21 (GPA0) | IN | FIELD | First-ball / zero / manual-intervention pushbutton. |
| 2 | PBC | `FIELD_SLOW_PBC` | `SLOW_PBC` | 22 (GPA1) | IN | FIELD | Cycle pushbutton. |
| 3 | FOUL | `FIELD_SLOW_FOUL` | `SLOW_FOUL` | 23 (GPA2) | IN | FIELD | Foul-line detector. |
| 4 | TENTH | `FIELD_SLOW_TENTH` | `SLOW_TENTH` | 24 (GPA3) | IN | FIELD | 10th-frame signal. |
| 5 | MAN_T | `FIELD_SLOW_MAN_T` | `SLOW_MAN_T` | 25 (GPA4) | IN | FIELD | Manual table. |
| 6 | MAN_S | `FIELD_SLOW_MAN_S` | `SLOW_MAN_S` | 26 (GPA5) | IN | FIELD | Manual sweep. |
| 7 | MAN_SWS | `FIELD_SLOW_MAN_SWS` | `SLOW_MAN_SWS` | 27 (GPA6) | IN | FIELD | Manual sweep-switch. |
| 8 | MAN_SWSR | `FIELD_SLOW_MAN_SWSR` | `SLOW_MAN_SWSR` | 28 (GPA7) | IN | FIELD | Manual sweep-reverse. |
| 9 | AUX1 | `FIELD_SLOW_AUX1` | `SLOW_AUX1` | 1 (GPB0) | IN | FIELD | Spare input. |
| 10 | AUX2 | `FIELD_SLOW_AUX2` | `SLOW_AUX2` | 2 (GPB1) | IN | FIELD | Spare input. |
| 11 | AUX3 | `FIELD_SLOW_AUX3` | `SLOW_AUX3` | 3 (GPB2) | IN | FIELD | Spare input. |
| 12 | Field ground | `FIELD_GND` | — | — | — | FIELD | Isolated wetting return for J5. |

**Operating theory.** Same dry-contact opto front-end (PC817 U25…U35) feeding MCP23017
IN-B. AUX1–AUX3 are deliberately spare for machine-specific discoveries at cutover so that
a newly-found switch does not force a board respin. The three manual-* lines exist so a
service tech's manual table/sweep/sweep-switch/sweep-reverse actuations are visible to the
Pi.

> **(VERIFY: per-channel dry-contact vs 24 VAC population)** — same open item as J3/J4.

---

### 11.7 J6–J12 — `J_MOTION_*` (isolated relay dry contacts, 2-pin each, 5.08 mm)

Each motion/control output is its own **2-pin fixed screw block** carrying one **isolated
SPDT relay's COM + NO** dry contact (Omron **G5LE-14, 5 VDC coil**). One terminal per
function keeps inter-channel creepage and lets the harness land each on the correct C1/C2A
cavity independently. **The board never sources the voltage across these contacts** — it
only opens/closes a contact in an existing machine control circuit, and only while the
safety rail is up.

**Pin convention (identical for every J_MOTION_*):**

| Pin | Signal | Net (example, S) | Relay pad | Dir | Domain | Notes |
|---|---|---|---|---|---|---|
| 1 | Relay **NO** (normally-open) | `OUT_S_B` | K-pad 3 (NO) | OUT | MACHINE OUTPUT | Open when de-energized; closes to COM when commanded + rail up. |
| 2 | Relay **COM** (common) | `OUT_S_A` | K-pad 1 (COM) | OUT | MACHINE OUTPUT | The contact common. |

> **Pin 1 = NO, Pin 2 = COM** on *all* J_MOTION_* blocks. This comes straight from
> `block_connectors()`: `b += j_motion[name][1]` (pin 1 = `OUT_x_B`) and
> `a += j_motion[name][2]` (pin 2 = `OUT_x_A`); and from `relay_output()`:
> `relay[1] += out_a` (COM) and `relay[3] += out_b` (NO). The metered G5LE-14 pad map is:
> coil pads 2/5, COM pad 1, NO pad 3, NC pad 4 unused.

**Per-connector function map (the only thing that differs between J6–J12):**

| Ref | Function | NO net (pin 1) | COM net (pin 2) | Relay | Driver | MCP OUT-A bit | Populated? |
|---|---|---|---|---|---|---|---|
| **J6** | **S** — sweep motor contactor command | `OUT_S_B` | `OUT_S_A` | K1 | Q1 (MMBT3904) | pin 21, GPA0 (0,0) | yes |
| **J7** | **T** — table motor contactor command | `OUT_T_B` | `OUT_T_A` | K2 | Q2 | pin 22, GPA1 (0,1) | yes |
| **J8** | **SP** — spot solenoid command | `OUT_SP_B` | `OUT_SP_A` | K3 | Q3 | pin 23, GPA2 (0,2) | yes |
| **J9** | **BE** — back-end command | `OUT_BE_B` | `OUT_BE_A` | K4 | Q4 | pin 24, GPA3 (0,3) | yes |
| **J10** | **M** — master / control command | `OUT_M_B` | `OUT_M_A` | K5 | Q5 | pin 25, GPA4 (0,4) | yes |
| **J11** | **M2** — sweep-reverse command | `OUT_M2_B` | `OUT_M2_A` | K6 | Q6 | pin 26, GPA5 (0,5) | yes |
| **J12** | **M1** — ball-return command | `OUT_M1_B` | `OUT_M1_A` | K7 *(DNP)* | Q7 *(DNP)* | pin 27, GPA6 (0,6) | **DNP** |

> **MCP OUT-A bit column** is from `OUTPUT_PINS` in the generator and matches
> `controller_io.py OUT_A_MAP`. Note the **M2-before-M1 ordering** (M2 = bit 5 / pin 26,
> M1 = bit 6 / pin 27) — this was a real bug-class that Codex caught and the maps were
> corrected to agree with the netlist. MCP pin → (port,bit): 21–28 = GPA0–7.

**Operating theory.** Each output is built by `relay_output()`: an MCP23017 OUT-A bit
drives `DRV_x` → 1 kΩ base resistor (`Rb`) → MMBT3904 NPN base (with a 100 kΩ
pull-down so the relay is **off** whenever the MCP pin floats/resets). The NPN sinks the
relay's low-side coil; the coil **high side is `RELAY_ENABLE_RAIL`**, not raw 5 V. So a
relay energizes only when *both* the FSM sets the bit *and* the safety rail (Section 10) is
holding `RELAY_ENABLE_RAIL` up. A flyback diode (1N4148) clamps the coil. Across the dry
contact, each output has **DNP footprints for arc suppression** — an RC snubber
(`Rsnub` 100 R + `Csnub` 10 nF X2) and a MOV — to be populated per output after the actual
inductive AC control load is characterized (`phase8b_pcb_revB_spec.md` §2.3, §3.2).

> **Safety-critical wiring rule.** S and T must command the *existing* contactor/relay
> control coils through these isolated contacts; they must **not** become the motor
> contactor or the de-energized braking path. Motor current never crosses the PCB
> (`phase8b_pcb_revB_spec.md` §3.1). The rail dropping de-energizes the *coil*; it cannot
> open a **welded** contact — the upstream master breaker / Stop / CIS chain is the final
> physical stop (§4.5).

> **(VERIFY: relay contact rating headroom.)** Whether the G5LE-14 contact rating is
> sufficient for the measured S/T/SP/BE/M/M2 control loads is an open assembly-blocking
> item (`phase8b_pcb_revB_spec.md` §3.2, §11 item 1). Size from measured coil/control
> current before populating.

> **(VERIFY: M2 sweep-reverse interlock preservation.)** Regardless of which cavity M2
> lands on, the OEM Expander note requires the sweep-reverse path to keep its
> motor-start/reverse interlock and shorting-plug termination. The *harness* must preserve
> that function (`phase8b_pcb_revB_spec.md` §3.2); it is not on the PCB.

---

### 11.8 J13 — `J_LAMP_LED` (status-LED drive, 6-pin, 3.5 mm)

Drives the four mask status LEDs (1st-ball, 2nd-ball, strike, foul) that Dylan installs in
the existing mask housings. **These are NOT machine-isolated** — the Rev-B decision is to
drive board-supplied LEDs from `VCC_5V` logic power through low-side FET sinks, abandoning
the machine's 15 VDC mask-lamp supply. There is intentionally **no LOGIC↔MACHINE isolation
barrier** on these four returns. They are **not** on the safety rail.

| Pin | Signal | Net | Driver FET | MCP OUT-A bit | Dir | Domain | Notes |
|---|---|---|---|---|---|---|---|
| 1 | +5 V LED supply | `VCC_5V` | — | — | PWR out | LOGIC | Common anode feed for all four LEDs. |
| 2 | Logic ground | `GND` | — | — | — | LOGIC | |
| 3 | L_FIRST return | `LED_L_FIRST_RETURN` | Q8 (2N7002) | pin 28, GPA7 (0,7) | OUT (sink) | LOGIC | 1st-ball lamp. Low-side sink; current set by 330 R (R90). |
| 4 | L_SECOND return | `LED_L_SECOND_RETURN` | Q9 | pin 1, GPB0 (1,0) | OUT (sink) | LOGIC | 2nd-ball lamp. 330 R (R93). |
| 5 | L_STRIKE return | `LED_L_STRIKE_RETURN` | Q10 | pin 2, GPB1 (1,1) | OUT (sink) | LOGIC | Strike lamp. 330 R (R96). |
| 6 | L_FOUL return | `LED_L_FOUL_RETURN` | Q11 | pin 3, GPB2 (1,2) | OUT (sink) | LOGIC | Foul lamp. 330 R (R99). |

**Operating theory.** Wire each external LED **anode to pin 1 (`VCC_5V`)** and its
**cathode to its return pin (3/4/5/6)**. Inside the board, `lamp_led_output()` puts a
330 Ω current-limit resistor (`Rled`) in series with each return, then a low-side 2N7002
N-MOSFET to GND, gated by an MCP23017 OUT-A bit through a 1 kΩ gate resistor (with a 100 kΩ
gate pull-down so the LED is **off** on reset/float). Setting the OUT-A bit turns the FET
on, sinks the LED return to GND, and lights the lamp. The bit assignments
(`L_FIRST`=GPA7 … `L_FOUL`=GPB2) match `OUT_A_MAP` (`first_ball/second_ball/strike/foul`).

> **(VERIFY: mask LED type + current-limit value.)** The 330 Ω (`Rled_*`) is a scaffold
> placeholder. The actual LED type and per-channel resistor for bowling-center brightness
> are an open assembly item (`phase8b_pcb_revB_spec.md` §3.3, §11 item 5). Confirm before
> populating R90/R93/R96/R99.

---

### 11.9 J14 — `J_SAFETY` (hardware interlock loops, 4-pin, 3.5 mm)

The two external normally-closed (NC) hardware interlock loops, wired **in series** between
`VCC_5V` and the gate of the relay-enable pass-FET. This is the part of the safety rail that
**no software can bypass**: if either loop opens, the pass-FET gate loses its pull and the
relay-enable rail collapses, de-energizing every motion-output relay coil. Per the contract,
these are the **TB/SC interference interlock** loop and the **Stop / CIS / master chain**
loop (`phase8b_pcb_revB_spec.md` §4.1, §4.4).

| Pin | Signal | Net | Dir | Domain | Notes |
|---|---|---|---|---|---|
| 1 | +5 V loop source | `VCC_5V` | OUT | SAFETY | Start of the series interlock string. |
| 2 | TB/SC loop return → next loop | `SAFE_TBSC_RETURN` | IN/OUT | SAFETY | Far end of the **TB/SC** NC loop; jumpers internally to pin 3. |
| 3 | Stop/CIS loop source | `SAFE_TBSC_RETURN` | IN/OUT | SAFETY | Same net as pin 2 — start of the **Stop/CIS/master** NC loop. |
| 4 | Stop/CIS loop return → pass-FET source | `SAFE_STOP_RETURN` | IN | SAFETY | Far end of the second loop; lands on the AO3401A (Q14) source + gate pull-up. |

**Operating theory.** `block_rail()` wires this as two NC loops in series:
`VCC_5V` (pin 1) → external TB/SC contacts → pin 2; pins 2 and 3 are the **same board net**
(`SAFE_TBSC_RETURN`), so the string continues out pin 3 → external Stop/CIS/master contacts
→ pin 4 (`SAFE_STOP_RETURN`). Pin 4 feeds the **source of P-channel pass-FET Q14
(AO3401A)** and a 100 kΩ gate pull-up. The pass-FET drain is `RELAY_ENABLE_RAIL`. Q14 only
conducts (rail up) when pin 4 is at ~5 V — i.e. **both** external loops are closed —
**and** the gate is pulled low by the downstream AND chain of two MMBT3904 NPNs gated by
`ARM_PERMIT`, `RP2040_OK`, and the NE555 watchdog-OK pull-down. Any one false condition
(open interlock loop, de-asserted arm, RP2040 unhealthy, or missing watchdog kick) leaves
the rail dead and the motion relays open. This is the electrical realization of the
"non-bypassable hardware safety rail" in the one-sentence contract (§13).

> **Connect the external loops correctly.** Pins 1↔2 are the **TB/SC** NC loop; pins 3↔4
> are the **Stop/CIS/master** NC loop. They are in series, so an open in either kills the
> rail. Do **not** jumper pin 1→4 to "make it work" during bench bring-up — that defeats
> the interlock. For a bench test with no machine loops, jumper 1–2 and 3–4 *only* on a
> locked-out/off-live machine, and remove the jumpers before cutover.

> **(VERIFY: TB/SC + Stop/CIS electrical form and polarity.)** The exact electrical
> derivation of the TB/SC and Stop/CIS loops (cam contacts vs the 24 V control path vs a
> low-voltage isolated loop) and the final connector polarity are an open
> assembly/cutover item (`phase8b_pcb_revB_spec.md` §4.4, §11 item 3). The board makes the
> interlock a first-class rail condition; the *source* of the loop is harness-resolved at
> the machine.

---

### 11.10 Test points related to connector signals (reference)

For bench bring-up, the board exposes test pads (excluded from BOM/POS) that expose the
rails and safety-chain nodes that the connectors above carry. Useful when verifying a
connector is live:

| TP | Net | Relevant to |
|---|---|---|
| TP1 | `VCC_5V` | J1 pin 1, J2, J13 pin 1 |
| TP2 | `GND` | logic ground |
| TP3 | `VCC_3V3` | J1 pin 11 (I2C / opto logic rail) |
| TP4 | `FIELD_WET_V` | isolated wetting source for J3/J4/J5 optos |
| TP5 | `FIELD_GND` | J3 pin 9/10, J4 pin 14, J5 pin 12 |
| TP6 / TP7 | `I2C_SDA` / `I2C_SCL` | J1 pins 3 / 4 |
| TP8 | `WDOG_KICK` | J1 pin 7 |
| TP13 | `ARM_PERMIT` | J1 pin 8 |
| TP14 | `RP2040_OK` | J1 pin 13 |
| TP15 | `SAFE_STOP_RETURN` | J14 pin 4 |
| TP16 | `RELAY_ENABLE_RAIL` | the rail that energizes every J_MOTION_* relay coil |

(TP9–TP12 expose the NE555 watchdog internals — `WDOG_TIMING_NODE`, `NE555_TRIG`,
`NE555_OUT`, `WDOG_OK_PULLDOWN` — see the watchdog section of this manual.)

---

### 11.11 Connector parts & board summary (as ordered)

Confirmed from the BOM/CPL/mating-parts CSVs:

| Item | Value / part | Source |
|---|---|---|
| Board size | **250 × 225 mm**, **4 copper layers** | `phase8b_pcb_revB_spec.md` |
| Relay (×6 populated, K1–K6; K7 DNP) | **Omron G5LE-14, 5 VDC coil** — LCSC **C116963** | PCBA BOM |
| Opto (×32, U4–U35) | **PC817B**, DIP-4 7.62 mm — LCSC **C5692981** | PCBA BOM |
| I/O expander (×3, U1–U3) | **MCP23017-E/SO** (I2C, **not** SPI MCP23S17) — LCSC **C47023** | PCBA BOM |
| Watchdog timer (U36) | **NE555DR** (bipolar 555, **not** CMOS/TLC555) — LCSC **C7593** | PCBA BOM |
| Isolated field-wetting DC/DC (U37) | **TRACO TMA-0505S** (5 V→5 V, 1 W, isolated) | working BOM |
| Reverse-polarity diode (D17) | **SS14** Schottky — LCSC **C2480** | PCBA BOM |
| Relay driver (Q1–Q6; Q7 DNP) | **MMBT3904** NPN, SOT-23 — LCSC **C909754** | PCBA BOM |
| LED driver (Q8–Q11) | **2N7002** N-MOSFET, SOT-23 — LCSC **C916396** | PCBA BOM |
| J1 mating | 2x10 IDC ribbon socket — CNC Tech 3030-20-0102-00 *(candidate)* | mating-parts |
| J3/J4/J5/J13/J14 mating | Phoenix **MC 1,5/x-ST-3,5** plugs (PN 1840447 / 1840489 / 1840463 / 1840405 / 1840382) | mating-parts |
| J2 + J6–J12 | Phoenix **MKDS 1,5** fixed screw blocks (wire-direct, no plug) | CPL / working BOM |

> **Do-not-substitute callouts (from the BOM Notes):** the relay coil **must** be 5 VDC
> (not 9/12/24 V); the I/O expander **must** be the I2C MCP23017 (not the SPI MCP23S17);
> the timer **must** be a bipolar 555 (changing to CMOS alters the watchdog timing).
