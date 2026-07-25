## 12. Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps

> **Purpose of this section.** This is the authoritative wiring reference for the Rev-B integrated lane-controller board: which physical Raspberry Pi Pico (RP2040) pin carries which machine signal, and which bit of which MCP23017 I²C expander drives or reads which relay/lamp/switch. If you are tracing a dead cam input, a stuck relay, or a wrong lamp on a real machine, **start here.** Every fact in this section is grounded in three live source files that the as-built board and the running firmware are generated from / compiled from:
>
> | File (relative to repo root `wsl-lane-nodes/`) | Role | What it defines |
> |---|---|---|
> | `scripts/generate_kicad_netlist_revB.py` | **PCB netlist generator — the board is physically wired from this.** | `FAST_INPUTS`, `SLOW_INPUT_PINS`, `OUTPUT_PINS`, all part footprints, all nets. |
> | `firmware/rp2040/config.h` | **RP2040 firmware pin contract — the Pico is flashed against this.** | `PIN_*` GPIO numbers, UART baud, debounce/watchdog timing. |
> | `lane_node/controller_io.py` | **Pi-side I/O driver — the FSM talks to the MCP23017s through this.** | `OUT_A_MAP`, `IN_A_MAP`, MCP I²C addresses, active-low convention. |
>
> These three agree by design. `controller_io.py` even contains a self-test (run `python lane_node/controller_io.py`) that re-parses `OUTPUT_PINS` and `SLOW_INPUT_PINS` out of the netlist generator with `ast` and **asserts the bit maps still match** — any drift fails the test loudly. See [§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test).

For the system-level theory of *what* these signals mean on the AMF 82-70 machine (cam timing, the cycle FSM, the relay-enable safety rail), see the system reference and FSM sections. This section is the pin-level bridge between that theory and the copper.

---

### 12.1 Scope: one lane = one board

Every map in this section is **per lane**. A lane *pair* is built as **two physically identical single-lane boards** stacked on one Raspberry Pi, each board carrying its own RP2040, its own set of three MCP23017s at the same I²C addresses (`0x20`/`0x21`/`0x22`; `0x23` reserved for the optional fourth), and its own relay-enable rail. The two boards are decoupled by running them on **two independent I²C buses** (Pi hardware `i2c-1` for board 1, a second software/GPIO bus via `dtoverlay=i2c-gpio` for board 2). This "clone the board" decision is recorded in `phase8_channel_allocation.md` §6 and is why both boards can reuse the identical address block (`0x20`/`0x21`/`0x22`, `0x23` reserved). Develop and validate one board, then build its twin.

**Board physical parameters** (from the design contract `phase8b_pcb_revB_spec.md`, cross-referenced by the generator): **250 × 225 mm, 4 copper layers.** (VERIFY: the generator script itself does not state board dimensions or layer count — these come from the spec doc and the as-routed `kicad/fab_revB_routed_manual/` artifacts, not from `generate_kicad_netlist_revB.py`.)

---

### 12.2 RP2040 (Raspberry Pi Pico) GPIO map — fast inputs + UART + rail permit

The RP2040 owns eight **board fast-input positions**, UART, `RP2040_OK`, and the
motion max-run backstop. Field landing is separate: lane 21/22 has no independent
TB lead and leaves SC/U unlanded. The v1.2.3 code contains per-cam overrun paths,
but the controlled release keeps every measured-cam flag OFF pending polarity
capture and a new controlled release (see §12.5).

#### 12.2.1 Authoritative GPIO table

Source of truth: `FAST_INPUTS` and `block_rp2040()` in
`generate_kicad_netlist_revD.py`, confirmed against `firmware/rp2040/config.h`.
The table distinguishes board positions from lane-21/22 field landings.

| GPIO | Pico module pin | Net name | Signal | Direction | Front-end | Function (firmware comment) |
|---|---|---|---|---|---|---|
| **GP0** | 1 | `PI_UART_RX` | UART TX → Pi RX | OUT (Pico TX) | logic | uart0 TX. Pico GP0/TX → Pi RX. |
| **GP1** | 2 | `PI_UART_TX` | UART RX ← Pi TX | IN (Pico RX) | logic | uart0 RX. Pi TX → Pico GP1/RX. |
| **GP2** | 4 | `RP2040_OK` | Rail permission | **OUT** | NPN AND-chain | **HIGH = permit motion, LOW = drop the relay-enable rail.** Firmware health / cam-stop permit. |
| **GP6** | 9 | `FAST_SA` | **SA** sweep cam | IN (opto, active-low) | PC817B opto | Sweep cam: 270° run-through stop / 360° zero. → `cam_SA_*` |
| **GP7** | 10 | `FAST_SB` | **SB** sweep cam | IN (opto, active-low) | PC817B opto | Sweep cam: 66° guard / 186° table-spot init. → `cam_SB_guard` |
| **GP8** | 11 | `FAST_SC` | **SC** board position | IN (opto, active-low) | PC817B opto | Lane 21/22 SC/U is cut/labeled/unlanded; optional echo position only. |
| **GP9** | 12 | `FAST_TA1` | **TA1** table cam | IN (opto, active-low) | PC817B opto | Table cam: 355° zero stop / 185° delay reset. → `cam_TA1_*` |
| **GP10** | 14 | `FAST_TA2` | **TA2** table cam | IN (opto, active-low) | PC817B opto | Table cam: 260° run-through / pin-latch / decision. → `cam_TA2_runthrough` |
| **GP11** | 15 | `FAST_TB` | **TB** board position | IN (opto, active-low) | PC817B opto | **No independent lane-21/22 field lead**; optional echo position only. |
| **GP12** | 16 | `FAST_DIELL_L` | **DIELL** left beam | IN (opto, active-low) | PC817B opto | Ball detect, left beam (cushion SS / cycle trigger). → `on_ball` |
| **GP13** | 17 | `FAST_DIELL_R` | **DIELL** right beam | IN (opto, active-low) | PC817B opto | Ball detect, right beam. → `on_ball` |

> **Note on Pico pin numbering:** GP6→pin 9, GP7→pin 10, GP8→pin 11, GP9→pin 12 are consecutive, but **GP10 is Pico module pin 14, not 13** (pin 13 is a GND pin on the Pico). The generator's `FAST_INPUTS` correctly lists `("TA2", 14)`. Do not "correct" this to 13.

The eight grounded Pico pins tied to board `GND` (`block_rp2040()`): module pins **3, 8, 13, 18, 23, 28, 33, 38**. Power: **pin 39 = VSYS = `VCC_5V`** (board feeds the Pico its 5 V), **pin 36 = 3V3 OUT = `VCC_3V3`** (the Pico *supplies* the board's 3.3 V logic rail — see [§12.2.3](#1223-power-rails-touching-the-rp2040)).

#### 12.2.2 Electrical sense of the fast inputs (operating theory)

Every fast input is **opto-isolated and active-LOW at the Pico.** From `opto_input()` in the generator and the header comment in `config.h`:

- The field side of each PC817B LED is fed from the isolated **`FIELD_WET_V`** rail through a **2.2 kΩ** series resistor (`Rin_*`). The machine contact closes that channel's field pin to **`FIELD_GND`** at the harness, completing the LED loop.
- When the machine contact is **closed (signal asserted)**, the opto transistor conducts and pulls the Pico GPIO **LOW**. Idle (contact open) = **HIGH**, held up by external `Rpu_*` to `VCC_3V3`: 10 kΩ on historical Rev-B and **47 kΩ on current Rev-D/R5**.
- Current Rev-D production firmware keeps GP6–GP13 internal PUE/PDE disabled so the external 47 kΩ is authoritative. A missing `Rpu_*` must be detected as a board fault, not hidden by an internal pull.
- So: **asserted = GPIO LOW, idle = GPIO HIGH.** The firmware constant for this is the implicit active-low handling in the debounce path; the Pi-side equivalent is `INPUT_ACTIVE_LOW = True` in `controller_io.py`.
- The logic side runs at **3.3 V**, so both the Pico and the MCP23017 inputs are Pi-safe (no 5 V on any GPIO). This is the optocoupler's whole job here and it satisfies the hard project rule that **Pi/Pico GPIO is 3.3 V only.**

`RP2040_OK` (GP2) is the inverse-critical output: it drives an NPN transistor inside the relay-enable-rail AND chain. **HIGH permits motion; LOW drops the rail.** A 100 kΩ base pulldown on that NPN makes the rail **fail-safe-dead** whenever GP2 is high-impedance (Pico unpowered, in reset, or pre-init) — the machine cannot move until firmware has explicitly booted and asserted permit. See [§12.7](#127-cross-reference-the-relay-enable-rail) and the safety-rail section.

#### 12.2.3 Power rails touching the RP2040

| Net | Source | Notes |
|---|---|---|
| `VCC_5V_RAW` | `J_PWR` pin 1 (Phoenix 3-pos terminal) | Raw 5 V in; protected by an `SS14` Schottky (`D_PROT`) before becoming `VCC_5V`. |
| `VCC_5V` | After `D_PROT` cathode | Feeds Pico VSYS (pin 39), the relay-coil rail, watchdog NE555, and the TMA-0505S isolated supply input. |
| `VCC_3V3` | **Pico pin 36 (3V3 OUT)** | The Pico's own regulator supplies all 3.3 V logic (MCP23017s, opto pull-ups, I²C pull-ups). A `10uF` bulk cap (`C_3V3_BULK`) makes the rail visible/placeable. |
| `FIELD_WET_V` / `FIELD_GND` | TMA-0505S DC-DC (`ISO_WET`) | Isolated 5 V "wet" domain that drives the opto LEDs; galvanically separate from logic GND. |

---

### 12.3 MCP23017 device summary

The board carries **three** MCP23017 16-bit I²C expanders in the baseline build (a fourth is optional). The part is the **I²C MCP23017** (LCSC **C47023**), in the SOIC-28W footprint (`Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm`). **It is *not* the SPI MCP23S17** — do not substitute the SPI variant; the Pi-side driver in `controller_io.py` talks `smbus2`/I²C only.

| Ref | I²C addr | A2 A1 A0 strap | Role | Pins used / 16 | Direction (IODIR) |
|---|---|---|---|---|---|
| **IN-A** | `0x20` | 0 0 0 | Grippers GS1–10 + GP/OS/BS/PBZ/PBC/Foul | 16 / 16 (full) | All inputs (`IODIR=0xFF`); Rev-D/R5 internal `GPPU=0x00`, read back |
| **IN-B** | `0x21` | **1** 0 0 | 10th-frame + manual switches + spares | 5 / 16 | All inputs (`IODIR=0xFF`); Rev-D/R5 internal `GPPU=0x00`, read back |
| **OUT-A** | `0x22` | 0 **1** 0 | 7 relay coils + 4 status lamps | 11 / 16 | All outputs (`0x00`) |
| **OUT-B** | `0x23` | (optional) | Physical pin-mask lamps + neon | OPTIONAL | All outputs — *omitted in baseline* |

**Address strapping** is set in hardware by tying A0/A1/A2 (MCP pins 15/16/17) high or low. From `block_mcp()` the strap tuples are `IN-A=(0,0,0)`, `IN-B=(1,0,0)`, `OUT-A=(0,1,0)`. (Note the generator passes the tuple in **A2,A1,A0** order; `IN-B` has A2 high → `0x21`, `OUT-A` has A1 high → `0x22`. (VERIFY: the live generator wires only three MCP23017s — IN-A, IN-B, OUT-A. There is **no** `MCP_OUT_B` instantiated in `generate_kicad_netlist_revB.py`; the optional `0x23` pin-mask expander exists only in `controller_io.py`'s `ADDR_OUT_B` constant and in the channel-allocation doc, gated behind `enable_pin_lamps`. The baseline board does not place it.)

**OUT-B / camera convergence (theory):** OUT-B would drive ten physical pin-indicator lamps (the "mask"). In this system the **camera supplies the pin-mask data** (scoring Track A), so OUT-B is depopulated by default. `controller_io.py` only opens `0x23` when constructed with `enable_pin_lamps=True`; `set_pin_lamps()` is a no-op otherwise. If a physical pindicator is ever built, OUT-B uses GPA0–GPA7 + GPB0–GPB1 for lamps 1–10. See the scoring section for why the camera path wins on a mixed-controller fleet.

**MCP23017 pin numbering used throughout** (verified KiCad symbol, from `block_mcp()` comment): VDD=9, VSS=10, SCK(SCL)=12, SDA=13, A0=15, A1=16, A2=17, ~RESET=18, INTB=19, INTA=20, **GPA0–GPA7 = pins 21–28**, **GPB0–GPB7 = pins 1–8**. Each chip has a local `0.1uF` decoupling cap; the I²C bus has shared **4.7 kΩ** pull-ups (`R_I2C_SDA`, `R_I2C_SCL`) to 3V3. `~RESET` (pin 18) is tied to `VCC_3V3` (held de-asserted).

#### The pin → (port, bit) translation rule

`controller_io.py` expresses every bit as **`(port, bit)`** where port 0 = GPIOA/OLATA and port 1 = GPIOB/OLATB. The mapping from the generator's raw MCP **pin number** to `(port, bit)` is fixed:

| MCP pin number | Port | Bit | gpiozero/register name |
|---|---|---|---|
| 21 | 0 | 0 | GPA0 |
| 22 | 0 | 1 | GPA1 |
| 23 | 0 | 2 | GPA2 |
| 24 | 0 | 3 | GPA3 |
| 25 | 0 | 4 | GPA4 |
| 26 | 0 | 5 | GPA5 |
| 27 | 0 | 6 | GPA6 |
| 28 | 0 | 7 | GPA7 |
| 1 | 1 | 0 | GPB0 |
| 2 | 1 | 1 | GPB1 |
| 3 | 1 | 2 | GPB2 |
| 4 | 1 | 3 | GPB3 |
| 5 | 1 | 4 | GPB4 |
| 6 | 1 | 5 | GPB5 |
| 7 | 1 | 6 | GPB6 |
| 8 | 1 | 7 | GPB7 |

This is exactly the `_pin_to_portbit()` helper in the `controller_io.py` self-test (`21–28 → (0, pin-21)`, `1–8 → (1, pin-1)`). Use it whenever you read a pin number off the netlist and need the software bit.

---

### 12.4 MCP23017 IN-A bit map (I²C `0x20`) — slow inputs

IN-A is **full** (all 16 pins used). It carries the ten gripper switches (the standing-pin mask) plus the gripper-protect, off-spot, bin-switch, two pushbuttons, and the foul signal. All sixteen channels are opto-isolated front-ends identical to the fast inputs ([§12.2.2](#1222-electrical-sense-of-the-fast-inputs-operating-theory)): **active-low at the MCP pin — switch closed pulls the pin LOW.** Current Rev-D/R5 `controller_io.py` reads them with the external 47 kΩ `Rpu_*` as the sole bias, commands `pullup_a=0x00, pullup_b=0x00`, verifies those GPPU bytes by readback, and inverts in software via `INPUT_ACTIVE_LOW = True`.

Source of truth: `IN_A_MAP` in `controller_io.py`, cross-checked against the `MCP_IN_A` entries of `SLOW_INPUT_PINS` in the generator.

| Signal | `IN_A_MAP` (port, bit) | MCP pin (generator) | Register name | FSM `io.*` method | Meaning |
|---|---|---|---|---|---|
| **GS1** | (0, 0) | 21 | GPA0 | `read_grippers` bit 0 | Gripper 1 standing |
| **GS2** | (0, 1) | 22 | GPA1 | `read_grippers` bit 1 | Gripper 2 standing |
| **GS3** | (0, 2) | 23 | GPA2 | `read_grippers` bit 2 | Gripper 3 standing |
| **GS4** | (0, 3) | 24 | GPA3 | `read_grippers` bit 3 | Gripper 4 standing |
| **GS5** | (0, 4) | 25 | GPA4 | `read_grippers` bit 4 | Gripper 5 standing |
| **GS6** | (0, 5) | 26 | GPA5 | `read_grippers` bit 5 | Gripper 6 standing |
| **GS7** | (0, 6) | 27 | GPA6 | `read_grippers` bit 6 | Gripper 7 standing |
| **GS8** | (0, 7) | 28 | GPA7 | `read_grippers` bit 7 | Gripper 8 standing |
| **GS9** | (1, 0) | 1 | GPB0 | `read_grippers` bit 8 | Gripper 9 standing |
| **GS10** | (1, 1) | 2 | GPB1 | `read_grippers` bit 9 | Gripper 10 standing |
| **GP** | (1, 2) | 3 | GPB2 | `gp_closed` | Gripper-protect |
| **OS** | (1, 3) | 4 | GPB3 | `read_input("OS")` ⊕ | Off-spot (future) |
| **BS** | (1, 4) | 5 | GPB4 | `bs_closed` | Bin / #9 switch |
| **PBZ** | (1, 5) | 6 | GPB5 | `first_ball_zero` path | Zero / 1st-2nd / manual-int pushbutton |
| **PBC** | (1, 6) | 7 | GPB6 | `read_input("PBC")` ⊕ | Cycle pushbutton (future) |
| **Foul** | (1, 7) | 8 | GPB7 | `on_foul` path | Radaray foul detect |

> **⚠️ The OS/BS bit order was a known bug, now fixed.** Earlier drafts had OS and BS swapped. The corrected, as-built order is **OS = pin 4 = (1,3)** and **BS = pin 5 = (1,4)**, matching the generator's `SLOW_INPUT_PINS`. `controller_io.py` carries an explicit comment to this effect, and the self-test enforces it. See [§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test).

**Gripper mask theory.** `read_grippers()` reads both ports of IN-A once each and assembles a **10-bit standing-pin mask**, where **bit (n−1) = GSn is standing** (`GRIPPER_ORDER = [GS1…GS10]`). Because the opto is active-low, a *standing* pin (gripper switch held) reads `0` at the pin and is recorded as a `1` in the mask. A clean rack = `0` (no pins) in the strike test in the FSM smoke test. This mask is the controller's *electromechanical* pin read; the *optical* camera read is the authoritative score source (scoring section), with the gripper mask available as a controller-side cross-check.

**Naming caveat for the daemon:** `read_input(name)` on `MachineIO` takes the `IN_A_MAP` key. Note the foul channel's key is **`"Foul"`** (mixed case) in `IN_A_MAP`, while the generator's `SLOW_INPUT_PINS` and the `J_SLOWB` connector order spell it **`"FOUL"`** (upper). The self-test bridges this (`"Foul" if n == "FOUL"`). Use `"Foul"` when calling `controller_io.py`.

#### IN-B (`0x21`) — initialized, not yet read

`controller_io.py` opens and configures IN-B (`self.in_b`, all inputs, internal GPPU off and read back) so all three board expanders are live, **but the current FSM does not read it.** Its channels (10th-frame, manual table/sweep/sweep-switch/sweep-reverse, three aux) are spare-allocated for when the FSM grows to full machine control. From `SLOW_INPUT_PINS` (the `MCP_IN_B` entries) and the `J_SLOWB` connector order:

| Signal | MCP pin | Port,bit | Register | Status |
|---|---|---|---|---|
| TENTH (10th-frame) | 21 | (0,0) | GPA0 | ⊕ future |
| MAN_T (manual table) | 22 | (0,1) | GPA1 | ⊕ future |
| MAN_S (manual sweep) | 23 | (0,2) | GPA2 | ⊕ future |
| MAN_SWS (manual sweep-switch) | 24 | (0,3) | GPA3 | ⊕ future |
| MAN_SWSR (sweep reverse) | 25 | (0,4) | GPA4 | ⊕ future |
| AUX1 | 26 | (0,5) | GPA5 | ⊕ spare |
| AUX2 | 27 | (0,6) | GPA6 | ⊕ spare |
| AUX3 | 28 | (0,7) | GPA7 | ⊕ spare |

IN-B's entire B-bank (GPB0–7) is free → expansion headroom. (VERIFY: `controller_io.py` defines no `IN_B_MAP` constant — the IN-B channel→pin assignment lives only in the generator's `SLOW_INPUT_PINS` and this doc. There is no software bit map to drift against yet, so the self-test does not cover IN-B.)

> **Rev-D/R5 diagnostic reservation (supersedes the Rev-B free-bank statement for
> the new board):** GPB0–GPB7 become J15 AUX4–AUX11. These are capacity
> reservations, not permission to land an unmeasured signal. For pilot lanes
> 21/22, reserve AUX4 provisionally for an isolated `stop_request`, AUX5 for
> `pit_interlock_request` **only if an existing device is found or a new one is
> installed**, AUX6 for an independent downstream energize-to-prove
> `control_power_ok`, AUX7/AUX8 for optional S/T current switches, AUX9 for one
> measured optional dry contact, AUX10 for `sensor_24v_ok`, and AUX11 for
> `field_wet_ok`. **Do not configure `cis_request` on lanes 21/22:** physical
> inspection found no C.I.S. device or wiring. A different chassis with a real
> C.I.S. may receive a chassis-specific mapping only after its contact form and
> demand behavior are measured. AUX4–AUX9 remain unmapped until field landing,
> isolation, open-wire behavior, exact event semantics, and first-article proof
> are approved. Only isolated volt-free contacts from appropriately listed
> external monitors may enter J15; never route mains, protective earth,
> unclassified live ladder voltage, or a `SAFE_*` conductor onto Rev-D AUX.

---

### 12.5 Why the fast inputs live on the RP2040 (operating theory)

This is the single most important architectural decision in the I/O design, and it is the reason the cams/ball are *not* simply more MCP23017 bits.

- **Latency + hardware cam-stop.** The motion cams define exact stop edges (for example SA at run-through/zero), and the RP2040 is positioned to drop `RP2040_OK` without Linux latency once measured cam enforcement is enabled. **TB/SC is different:** its primary guard is the OEM parallel-safe S/T coil ladder. The SC∧TB firmware echo is default-off/unvalidated and cannot be counted as cam-stop protection because lanes 21/22 have no independent TB input.
- **Push, not poll.** The RP2040 *forwards cam/ball events to the Pi as messages* over UART (newline-delimited JSON, e.g. `{"ev":"SB_guard"}` / `{"ev":"ball"}`, at 115200 baud). The FSM in `cycle_control_8270.py` consumes **events** (method calls like `cam_SB_guard()`), not pin polls, so nothing is lost by moving the pins off the Pi header. A UART/IRQ device can *initiate*; an I²C/SPI peripheral cannot — that is why UART was chosen over an MCP-style expander or an SPI/I²C slave for these signals.
- **Pin budget.** Sixteen fast inputs across a pair would consume too much of the Pi's 40-pin header. Putting them on a per-board RP2040 keeps the Pi's GPIO free for the two I²C buses, the watchdog kick, and the per-board INT/arm lines.
- **Fail-safe link.** `RP2040_OK` health + the active max-run backstop gate the rail
  independently of UART. Per-cam overrun may be credited only after measured
  polarity is enabled in a new controlled release; stock v1.2.3 flags are OFF.
  The OEM TB/SC ladder remains the separate primary collision guard.

The `RP2040_OK` (GP2) output is the RP2040's "I am alive and permitting motion" line into the AND chain; the firmware holds it LOW for `BOOT_SETTLE_MS = 200 ms` after boot before ever permitting, and the on-chip watchdog (`WDT_TIMEOUT_MS = 250 ms`) resets the chip — dropping GP2 → dropping the rail — if the firmware loop ever hangs.

---

### 12.6 The stale-draft trap and the anti-drift self-test

**⚠️ Read this before trusting any older pinout doc.**

`docs/phase8_channel_allocation.md` §2 contains a **GPIO column that is STALE.** That draft assigned the fast inputs (SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R) to **GP0–GP7**. **That is WRONG for the as-built board.** The real board — and the flashed firmware — use **GP6–GP13** for the fast inputs, with **GP0/GP1 reserved for UART** and **GP2 for `RP2040_OK`**. The `config.h` header says so explicitly:

> *"do NOT trust the older draft in `docs/phase8_channel_allocation.md` §2, which assigned the fast inputs to GP0-GP7 (WRONG vs the as-built board; the real board uses GP6-GP13)."*

The **known-correct anchors** (use these; flag any source that disagrees):

| Anchor | Correct value | Authority |
|---|---|---|
| Fast inputs (SA…DIELL_R) | **GP6 … GP13** | `FAST_INPUTS` + `config.h` |
| `RP2040_OK` | **GP2** | `block_rp2040()` + `config.h` |
| UART TX/RX | **GP0 / GP1** | `block_rp2040()` + `config.h` |

**`controller_io.py` was corrected to match the board.** Three specific swaps that were caught (by Codex, 2026-06-03) and fixed so the software matches the netlist:

1. **BS ↔ OS** — corrected to OS=(1,3), BS=(1,4).
2. **M1 ↔ M2** — corrected so M2 comes *before* M1 (M2=GPA5/pin 26, M1=GPA6/pin 27) per the generator's `OUTPUT_PINS`.
3. **strike ↔ foul** — corrected to strike=(1,1), foul=(1,2).

The fix is *enforced*, not just documented. The `if __name__ == "__main__"` block at the bottom of `controller_io.py`:

1. Drives the real `cycle_control_8270` FSM through a full strike cycle on `RecordingIO` (proves the io contract).
2. Parses `generate_kicad_netlist_revB.py` with `ast.literal_eval`, extracts `OUTPUT_PINS` and `SLOW_INPUT_PINS`, converts each pin to `(port, bit)`, and **asserts `OUT_A_MAP == exp_out` and `IN_A_MAP == exp_in`.** If anyone edits the board netlist without updating the software map (or vice-versa), this test fails with a diff. **Run `python lane_node/controller_io.py` after any pin change.**

So: `OUT_A_MAP` / `IN_A_MAP` in `controller_io.py` are **current and correct**; the `phase8_channel_allocation.md` GPIO column is **historical**. When this section and that draft disagree, **this section (and the three source files) win.**

---

### 12.7 MCP23017 OUT-A bit map (I²C `0x22`) — relays + status lamps

OUT-A is the only output expander in the baseline build. Seven channels drive **relay coils** (the motion/solenoid relays) and four drive **status lamps** (the bowler-facing indicators). All eleven are configured as outputs (`dir_mask_a=0x00, dir_mask_b=0x00`) and start LOW.

Source of truth: `OUT_A_MAP` in `controller_io.py`, cross-checked against `OUTPUT_PINS` in the generator (the regression test asserts they are identical after the `L_FIRST→first_ball` etc. key remap).

| Signal | `OUT_A_MAP` (port, bit) | MCP pin (generator) | Register | Driver chain | FSM `io.*` method | Load |
|---|---|---|---|---|---|---|
| **S** | (0, 0) | 21 | GPA0 | MCP → MMBT3904 → G5LE relay | `set_sweep` | Machine sweep-contactor coil ~24 VAC → 115 V motor |
| **T** | (0, 1) | 22 | GPA1 | MCP → MMBT3904 → G5LE | `set_table` | Machine table-contactor coil ~24 VAC → 115 V motor |
| **SP** | (0, 2) | 23 | GPA2 | MCP → MMBT3904 → G5LE | `set_spot` | Machine SP spot-solenoid circuit ~24 VAC |
| **BE** ⊕ | (0, 3) | 24 | GPA3 | MCP → MMBT3904 → G5LE | (future) | Back-end relay (continuous motor) |
| **M** ⊕ | (0, 4) | 25 | GPA4 | MCP → MMBT3904 → G5LE | (future) | Master relay (power/halo/pit) |
| **M2** ⊕ | (0, 5) | 26 | GPA5 | MCP → MMBT3904 → G5LE | (future) | Sweep reverse |
| **M1** ⊕ | (0, 6) | 27 | GPA6 | MCP → MMBT3904 → G5LE **(DNP)** | (future) | Ball return motor |
| **first_ball** | (0, 7) | 28 | GPA7 | MCP → 2N7002 NMOS (low-side) | `set_light('first_ball')` | 1st-ball status lamp (`L_FIRST`) |
| **second_ball** | (1, 0) | 1 | GPB0 | MCP → 2N7002 NMOS | `set_light('second_ball')` | 2nd-ball status lamp (`L_SECOND`) |
| **strike** | (1, 1) | 2 | GPB1 | MCP → 2N7002 NMOS | `set_light('strike')` | Strike status lamp (`L_STRIKE`) |
| **foul** | (1, 2) | 3 | GPB2 | MCP → 2N7002 NMOS | `set_light('foul')` | Foul status lamp (`L_FOUL`) |

> **Coil vs. load — do not confuse the two.** The *Load* column above is the machine-side circuit each relay **contact** switches (≈24 VAC contactor coil / solenoid, which in turn runs the 115 V motor). Every on-board **G5LE relay coil is 5 VDC**, fed from the relay-enable rail (see §9, §10). The board never drives a 24 V coil.

OUT-A.B3–B7 (MCP pins 4–8) are **spare** (5 free output bits). The `⊕` channels (BE, M, M1, M2) are wired and physically present but **not yet driven by the FSM** — they are spare-allocated for full machine control.

> **Name mapping reminder.** The generator's `OUTPUT_PINS` uses the lamp keys `L_FIRST / L_SECOND / L_STRIKE / L_FOUL`. `controller_io.py` exposes them as `first_ball / second_ball / strike / foul` (the names `set_light()` accepts). The self-test's `OUT_KEY` dict bridges the two. `set_light()` rejects any name not in `{first_ball, second_ball, foul, strike}`.

> **M1 is depopulated (DNP).** In `main()` the generator calls `relay_output("M1", …, dnp=True)` — its G5LE relay footprint is on the board but **not stuffed** in the baseline build. The bit map slot exists; the physical relay does not (yet).

#### 12.7.1 Relay driver chain (theory)

Each motion channel (`relay_output()`): the MCP output bit feeds a **1 kΩ** base resistor (`Rb_*`) into an **MMBT3904** NPN, with a **100 kΩ** pulldown (`add_drive_pulldown`) so the relay is off when the MCP is undriven/Hi-Z. The transistor's collector switches the low side of the **Omron G5LE-14 relay coil**; the coil's high side sits on the **`RELAY_ENABLE_RAIL`** (not raw 5 V) — so the watchdog/arm/interlock rail can cut every motion relay at once. A **1N4148** flyback diode (`Dfly_*`) clamps the coil (cathode to rail, anode to switched side). Across each relay *contact* (COM = relay pin 3, NO = relay pin 4) the board provides a depopulatable arc-suppression network: **100 Ω DNP** series resistor + **10 nF X2 DNP** cap + **MOV DNP** — all not-stuffed by default, footprints available for AC loads if the bench shows contact arcing.

> **Relay part — anchor.** The relay is the **Omron G5LE-14, 5 VDC coil** (LCSC **C116963**), footprint `Relay_THT:Relay_SPDT_Omron-G5LE-1`. It is a **5 V** coil — **not 12 V or 24 V.** (Note: the *coil* is 5 V; the channel table above lists the *downstream machine load* the relay's contacts switch, e.g. a 24 V machine coil / 115 V motor circuit. The generator's `value="24V coil…"` text in the channel-allocation doc refers to the field load, not the G5LE coil. The G5LE is energized from the 5 V relay-enable rail.) See [§12.9](#129-bench-decision-aediko-relay-module-vs-on-board-g5le) on the AEDIKO-module alternative captured in the design notes.

#### 12.7.2 Status-lamp driver chain (theory)

Each lamp channel (`lamp_led_output()`): the MCP bit feeds a **1 kΩ** gate resistor (`Rgled_*`) into a **2N7002** N-channel MOSFET (low-side switch), with a **100 kΩ** gate pulldown (`Rpdled_*`) for fail-off and a **330 Ω** series limit resistor (`Rled_*`) in the lamp return. The lamp's supply comes from the board's `VCC_5V` at the lamp connector and the MOSFET sinks the return to GND. These are *not* motors — `MOTION_RELAYS` in `controller_io.py` deliberately excludes the four lamps, so they are never sent RUN/STOP to the RP2040's motion-timeout backstop.

---

### 12.8 Field connectors (where each map lands at the harness)

The generator's `block_connectors()` lays out function-named field terminals so the harness is labeled by machine function, not bare pin numbers. Summary (footprints in parentheses):

| Connector | Footprint | Carries | Pin order |
|---|---|---|---|
| **J_PI** | IDC 2×10 (`IDC-Header_2x10`) | Pi ribbon: power, I²C, UART, watchdog kick, arm, MCP INTs, RP2040_OK | 1=VCC_5V, 2/12=GND, 3=SDA, 4=SCL, 5=UART_TX, 6=UART_RX, 7=WDOG_KICK, 8=ARM_PERMIT, 9=MCP_INT_A, 10=MCP_INT_B, 11=VCC_3V3, 13=RP2040_OK |
| **J_PWR** | Phoenix 3-pos (`MKDS-1,5-3-5.08`) | 5 V input | 1=VCC_5V_RAW, 2/3=GND |
| **J_FAST_IN** | Phoenix MCV 1×10 | 8 fast field inputs + field GND | pins 1–8 = SA, SB, SC, TA1, TA2, TB, DIELL_L, DIELL_R (in `FAST_INPUTS` order); pins 9–10 = FIELD_GND |
| **J_SLOW_IN_A** | Phoenix MCV 1×14 | IN-A field inputs | pins 1–13 = GS1…GS10, GP, OS, BS; pin 14 = FIELD_GND |
| **J_SLOW_IN_B** | Phoenix MCV 1×12 | IN-B field inputs | pins 1–11 = PBZ, PBC, FOUL, TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1, AUX2, AUX3; pin 12 = FIELD_GND |
| **J_MOTION_{S,T,SP,BE,M,M2,M1}** | seven Phoenix 2-pos (`MKDS-1,5-2-5.08`) | one relay contact pair each | pin 1 = `OUT_*_B` (NO), pin 2 = `OUT_*_A` (COM) — vertical order matches the G5LE pad order (B above A) |
| **J_LAMP_LED** | Phoenix MCV 1×6 | 4 status lamps + power | 1=VCC_5V, 2=GND, 3–6 = L_FIRST, L_SECOND, L_STRIKE, L_FOUL returns |
| **J_SAFETY** | Phoenix MCV 1×4 | two board-side source positions in series | **1→2 = controlled Candidate-C jumper (no TB/SC machine landing)**; 3→4 = reserved external control-power / optional pit-interlock dry-contact interface, currently OPEN/unlanded, feeding the rail PMOS source only after an approved interface closes |

> **Lane-21/22 fast-input caveat:** the PCB allocates J_FAST_IN/GP11 to TB, but the
> measured harness has no standalone TB cavity. Leave TB NO-LEAD. SC/U is a
> non-isolatable live-ladder region and stays CUT+LABEL-ONLY unless a separately
> reviewed observe-only input is released. Do not infer usable field inputs from the
> copper allocation alone.

> **Important field note (from `phase8_channel_allocation.md` §3, bench-confirmed):** the machine-side outputs are **split across machine connectors C1 and C2A** — the high-current main motors **S, T** land on **C1**, while **SP, M2, BE** land on **C2A**. This does **not** change the OUT-A bit map (the board always drives the relay coils); it only affects which machine connector each relay *contact* wires to in the field. The enclosure harness therefore needs leads from the relay bank to **both** C1 and C2A. Exact C1/C2A cavity digits are bench-gated in the fieldsheet pass (the one remaining hard blocker for board finalization).

---

### 12.9 Bench decision: AEDIKO relay module vs on-board G5LE

The Rev-B netlist generator instantiates **on-board G5LE relays** with discrete MMBT3904 drivers and flyback diodes (as mapped in [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps)). The Phase-8a bench work, however, captured specs for an alternative implementation path using a pre-built **AEDIKO 8-channel relay module** (recorded in `phase8_channel_allocation.md` §7 and `pcb_design_spec.md`). The two are not contradictory — they are two ways to realize the same OUT-A bit map; which one the production board uses is a build choice. Key captured facts (for whoever builds/services the relay bank):

- **AEDIKO coil current:** ~**70 mA each @ 5 V** (8 ch → ~560 mA worst case); coil rail spec **4.5–6 V** → the relay-coil rail is **5 V**, consistent with the G5LE-14 5 VDC anchor.
- **AEDIKO has onboard optos + flyback** (it is a complete relay HAT) → in that path the discrete MMBT3904 + 1N4148 collapse to "MCP/GPIO → AEDIKO IN," and **no external ULN2803 is needed.**
- **Watchdog gating proven:** NE555 → AO3400 low-side MOSFET gates the AEDIKO **V− return** (5.7 A FET vs 560 mA load = large margin). Bench-validated.
- **Contacts switch the contactor *coil* circuit, not the motor directly** — the machine's existing contactors still switch the 115 V motor, so the relay contacts only see small contactor-coil current. This is the central simplicity/safety win: *the board drives coils; the machine's existing iron switches the motors.* Confirm each contactor's coil voltage/current at the bench.

(VERIFY: the **live netlist generator builds discrete G5LE relays**, not the AEDIKO module — the AEDIKO is documented in the channel-allocation/pcb-design notes as the validated Phase-8a approach. Which of the two the as-routed Rev-B board actually carries should be confirmed against the assembly BOM in `kicad/fab_revB_routed_manual/assembly/` before ordering replacements. The generator's part is the G5LE-14.)

---

### 12.10 Watchdog timing reference (NE555) + firmware timing constants

Two independent timing layers protect motion. Both are summarized here because a service tech tracing "why did the rail drop / why won't it arm" needs both numbers in one place.

**Layer 1 — on-board NE555 hardware watchdog** (`block_watchdog()` in the generator). A **bipolar NE555** (part **NE555DR**, LCSC **C7593**, footprint `Package_SO:SOIC-8`) in monostable-retriggerable form: the Pi kicks `WDOG_KICK` (J_PI pin 7 → GPIO12) periodically; each kick discharges the timing cap through a MOSFET, restarting the timeout. If kicks stop, the NE555 output flips and the AND chain drops the rail. Timing components:

| Component | Ref | Value | Role |
|---|---|---|---|
| Timing resistor | `R_WDOG_TIMING` | 100 kΩ | RC charge into NE555 THRESH/TRIG |
| Timing capacitor | `C_WDOG_TIMING` | 100 µF / 16 V (electrolytic) | Sets the ~seconds-scale timeout |
| Trigger pull-up | `R_WDOG_TRIG_PULLUP` | 10 kΩ | Holds TRIG high between kicks |
| Kick gate / pulldown | `R_WDOG_KICK_GATE` / `R_WDOG_KICK_PD` | 1 kΩ / 10 kΩ | Pi GPIO12 → kick MOSFET (AO3400A) |
| Output gate / pulldown | `R_WDOG_OUT_GATE` / `R_WDOG_OUT_PD` | 1 kΩ / 10 kΩ | NE555 OUT → AND-chain MOSFET (AO3400A) |
| VCC decouple | `C_WDOG_VCC` | 0.1 µF | NE555 supply |
| Control bypass | `C_WDOG_CTRL` | 10 nF | Pin 5 CONTROL filter |

The design intent is a kick-or-die window of roughly **~10 s** (the bench-validated figure cited in the channel-allocation doc and safety section). (VERIFY: the generator fixes the RC parts at 100 kΩ × 100 µF but does **not** annotate the exact resulting timeout in seconds; the "~10 s" figure comes from the bench validation notes, not from a computed constant in the source. The standard 555 monostable `t ≈ 1.1·R·C` with these values ≈ 11 s, consistent with "~10 s," but treat the precise number as bench-measured, not source-declared.)

**Layer 2 — RP2040 firmware timing** (`config.h`). These are the compiled-in constants the Pico enforces:

| Constant | Value | Purpose |
|---|---|---|
| `UART_BAUD` | 115200 | Pi link baud |
| `DEBOUNCE_CAM_US` | 2000 µs (2 ms) | Cam microswitch debounce (12 RPM machine → 2 ms ample) |
| `DEBOUNCE_DIELL_US` | 500 µs | Ball beam-break debounce (faster, still de-glitched) |
| `BALL_LOCKOUT_MS` | 300 ms | One thrown ball → one ball event (re-trigger lockout) |
| `HB_INTERVAL_MS` | 250 ms | Heartbeat cadence to the Pi |
| `BOOT_SETTLE_MS` | 200 ms | RP2040_OK held LOW at least this long after boot before permitting motion |
| `WDT_TIMEOUT_MS` | 250 ms | RP2040 on-chip watchdog: loop hang → chip reset → RP2040_OK drops → rail drops |
| `MAX_MOTION_MS` | 8000 ms | Motion max-run backstop (matches `cycle_control_8270.MAX_MOTION_S = 8.0 s`). A guarded motor marked RUNNING over UART longer than this latches a fault and drops RP2040_OK. **BE (continuous) and M (master/power) are NOT guarded.** |

`FW_VERSION` is `"phase8b-rp2040 v1.2.3"`; require the manifest-bound Rev-D
release identity, not the version string alone.

---

### 12.11 Cross-reference: the relay-enable rail

Everything in [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps) (relay coils) is powered through **`RELAY_ENABLE_RAIL`**. Candidate C leaves four effective on-board permission classes:

1. **NE555 watchdog OK** — Pi kicks GPIO12 within the timeout, else the rail drops. ([§12.10](#1210-watchdog-timing-reference-ne555--firmware-timing-constants))
2. **Pi "arm" GPIO** asserted (`ARM_PERMIT`, J_PI pin 8) — de-asserts on the power-down rule until an operator First-Ball-Zero.
3. **RP2040_OK** (GP2) HIGH — firmware healthy + cam-stop permitting. ([§12.2.2](#1222-electrical-sense-of-the-fast-inputs-operating-theory))
4. **J_SAFE source path complete** — controlled Candidate-C jumper on pins 1–2 plus a future approved external energize-to-prove control-power dry contact, optionally in series with an approved new pit-entry-interlock contact, on pins 3–4 feed the rail PMOS source. The current lane-21/22 3–4 harness is OPEN/unlanded, so the field rail cannot arm; never jumper it at the machine. Machine voltage and mains stay outside Rev-D.

The primary TB/SC guard is separate from that on-board list: the powered-proven OEM contacts are parallel closed-when-safe in the S/T coil circuits. Correct board insertion is accepted only after G3 proves that both levers BACK/open leave the board-commanded S and T coils dead. The default-off SC∧TB firmware echo is secondary/unvalidated. Any failed on-board gate still drops every board relay coil; normal Pi software cannot bypass either correctly installed hardware path.

---

### 12.12 Quick service checklist

- **A cam input is dead.** It is on the RP2040, not an MCP. Trace `J_FAST_IN` pin → PC817B opto → Pico GPIO per [§12.2.1](#1221-authoritative-gpio-table). Remember: **asserted = GPIO LOW.** Confirm the channel's `FIELD_WET_V` and `FIELD_GND` at J_FAST pins 9/10.
- **A relay won't fire.** Confirm the **rail** is up first ([§12.11](#1211-cross-reference-the-relay-enable-rail)) — a dropped watchdog/arm/RP2040_OK/interlock kills all coils, not just one. Then trace OUT-A bit → MMBT3904 → G5LE per [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps).
- **Wrong lamp / wrong relay channel.** Do **not** trust the GPIO column in `phase8_channel_allocation.md`. Re-derive from `OUT_A_MAP` / `IN_A_MAP` and run the self-test (`python lane_node/controller_io.py`) — it will diff any drift against the netlist. ([§12.6](#126-the-stale-draft-trap-and-the-anti-drift-self-test))
- **M1 / OUT-B "missing."** Expected — M1's G5LE is DNP and OUT-B (`0x23`) is depopulated in the baseline (camera supplies the pin mask). ([§12.3](#123-mcp23017-device-summary), [§12.7](#127-mcp23017-out-a-bit-map-i²c-0x22--relays--status-lamps))
- **Replacing a part.** Anchors: relay = **Omron G5LE-14, 5 VDC** (C116963); expander = **MCP23017** I²C (C47023), **not** MCP23S17; opto = **PC817B** (C5692981); timer = **NE555** (NE555DR, C7593). Verify any other value against the assembly BOM in `kicad/fab_revB_routed_manual/assembly/` before ordering.
