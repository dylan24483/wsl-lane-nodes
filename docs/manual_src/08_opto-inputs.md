## 8. Rev-B Field Inputs: PC817 Opto-isolators

Every machine signal the Rev-B controller board reads — cam microswitches, ball
detectors, gripper switches, pushbuttons, foul, and the manual/spare lines —
enters the board through an opto-isolated input channel built around a **PC817B**
optocoupler. This section explains how one channel works electrically, why the
field side is galvanically isolated from logic ground, the two population
flavors (dry-contact wetting vs 24 VAC sense) the design supports per channel,
and the full channel count and parts.

This is the input half of the board. The output half (relay contacts) is covered
in **Section 9 — Machine Outputs: G5LE Relays** (VERIFY: exact section number),
the fast-cam timing budget in the RP2040 firmware in **Section 7 — RP2040
Co-processor** (VERIFY: exact section number), and the safety rail that gates the
relays in **Section 10 — Safety Rail & Watchdog** (VERIFY: exact section number).
Where a section number is uncertain, cross-reference by title.

> **Source of truth for this section.** Pin numbers, net names, part numbers, and
> values are taken from the live board netlist generator
> `scripts/generate_kicad_netlist_revB.py` (function `opto_input()`, lists
> `FAST_INPUTS` and `SLOW_INPUT_PINS`), the assembled-board part lock
> `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv`,
> the firmware pin map `firmware/rp2040/config.h`, the software bit map
> `lane_node/controller_io.py`, and the design contract
> `docs/phase8b_pcb_revB_spec.md`. The stale GPIO column in
> `docs/phase8_channel_allocation.md` is **not** used here.

---

### 8.1 What an input channel is for

The pinsetter's native signals are almost all **switch closures**: a cam lever
rides a lobe and opens/closes a microswitch; a gripper finger pinches a standing
pin and makes/breaks a contact to the machine chassis; a pushbutton shorts a
control line. The board's job is to read the open/closed state of each of these
contacts **without ever connecting a machine wire directly to a Pico, RP2040, or
MCP23017 pin** (design contract §5.3: "No machine input may connect directly to
Pi, RP2040, or MCP23017 pins").

The PC817B optocoupler is the device that bridges that gap. Its internal LED and
phototransistor are coupled only by light across an insulating gap, so the field
wiring (which may carry machine voltages, ground faults, or noise) and the
3.3 V logic are electrically separate. The contact state crosses the barrier as
light, not as a shared conductor.

At-machine measurements (`docs/phase8b_at_machine_fieldsheet.md`, item A4)
confirmed that on lanes 21/22 the cams are **dry contacts, normally-closed at
rest**, and grippers are **chassis-referenced** (a gripped pin closes the switch
to chassis ground). This is why the dry-contact wetting front-end (below) is the
confirmed default population for those channels.

---

### 8.2 How one channel works (dry-contact wetting, the default)

The default population builds this series loop for each channel. All names below
are the literal nets and references from `opto_input()` in the generator:

```
FIELD_WET_V ──► Rin (2k2) ──► PC817B LED anode (pin 1)
                              PC817B LED cathode (pin 2) ──► FIELD_<name>  ──► [J connector pin]
                                                                                     │
                                                          (machine contact closes this pin to FIELD_GND)
                                                                                     │
                                                                                FIELD_GND
```

and on the isolated logic side:

```
VCC_3V3 ──► Rpu (10k) ──► logic node (Pico GPIO or MCP23017 pin)
                            ▲
PC817B collector (pin 4) ──┘   (phototransistor pulls the logic node toward GND when lit)
PC817B emitter (pin 3) ──► GND  (logic ground)
```

**Step by step:**

1. **Wetting source.** `FIELD_WET_V` (the board-generated, isolated field-wetting
   rail — see §8.6) supplies the small current that lights the opto LED. It is
   the only "power" present on the field side, and it is referenced to
   `FIELD_GND`, not logic `GND`.

2. **LED current limit.** `Rin` = **2.2 kΩ** (BOM value "2k2", 0805, 1%; the 32
   off in the part lock are `R3, R5, R7 … R65`) sets the LED drive current so the
   PC817B turns on cleanly while keeping field-side current low. With a ~5 V
   wetting supply minus the LED forward drop, this is on the order of a couple of
   milliamps — enough to saturate the PC817B over its CTR bin given the matched
   10 k logic pull-up.

3. **The field contact does the switching.** The LED's cathode (pin 2) is wired
   to the per-channel field net `FIELD_<name>`, which lands on the channel's
   connector pin. The machine's switch is wired between that pin and `FIELD_GND`
   at the harness. **When the machine contact closes**, it completes the loop
   `FIELD_WET_V → Rin → LED → contact → FIELD_GND`, current flows, and **the LED
   lights**.

4. **Light crosses the barrier.** The lit LED turns on the PC817B
   phototransistor.

5. **Logic side pulls LOW.** The phototransistor's collector (pin 4) is tied to
   the logic node, which is held HIGH by `Rpu` = **10 kΩ** to `VCC_3V3`; its
   emitter (pin 3) goes to logic `GND`. When the transistor conducts, it pulls
   the logic node down toward `GND`. So **contact closed → LED on → logic node
   LOW**.

6. **Idle state.** With the machine contact open, no LED current flows, the
   phototransistor is off, and `Rpu` holds the logic node **HIGH** at 3.3 V.

This gives the channel its polarity: **asserted/closed = LOW (active-low)**. The
firmware and software both encode this — see §8.5.

#### 8.2.1 PC817B pin map (per channel)

The PC817B is a 4-pin DIP (footprint `Package_DIP:DIP-4_W7.62mm` in the
generator). Pin roles as wired in `opto_input()`:

| PC817B pin | Function | Side | Wired to (net) |
|---|---|---|---|
| 1 | LED anode (input +) | Field | `FIELD_LED_<name>` (output of `Rin`, which is fed from `FIELD_WET_V`) |
| 2 | LED cathode (input −) | Field | `FIELD_<name>` → channel connector pin (machine contact pulls it to `FIELD_GND`) |
| 3 | Phototransistor emitter | Logic | `GND` (logic ground) |
| 4 | Phototransistor collector (output) | Logic | logic node = Pico GPIO **or** MCP23017 pin; held HIGH by `Rpu` (10 k) to `VCC_3V3` |

> The barrier runs **between pins 1/2 (field) and pins 3/4 (logic)**. Nothing
> bridges those two pin-pairs on the board except the optocoupler itself.

#### 8.2.2 Per-channel passive parts

| Ref pattern | Value | Purpose | Part (part lock) |
|---|---|---|---|
| `Rin_<name>` | 2.2 kΩ ("2k2"), 0805, 1% | Field-side LED current limit | LCSC C17520, `0805W8F2201T5E`, UNI-ROYAL — 32 off (`R3,R5,…,R65`) |
| `Rpu_<name>` | 10 kΩ, 0805, 1% | Logic-side pull-up to `VCC_3V3` (defines idle-HIGH / active-LOW) | LCSC C17414, `0805W8F1002T5E`, UNI-ROYAL — 37 off total on board (32 of them are the opto pull-ups; the rest serve the watchdog/safety AND chain) |
| `OPTO_<name>` | PC817B | The opto-isolator | LCSC C5692981, `PC817B`, UMW, DIP-4 — 32 off (`U4…U35`) |

> **CTR note (from the part-lock file):** "CTR bin must be accepted with Rev-B
> field resistors." The 2k2 LED resistor + 10k logic pull-up were chosen to work
> across the PC817**B** current-transfer-ratio bin; do not substitute a
> lower-CTR opto or change these resistor values without re-checking that a
> closed contact still pulls the logic node solidly below the input's logic-LOW
> threshold.

---

### 8.3 The 24 VAC-sense population option

Design contract §2.2 / §5.1 require that **every** input channel be
"population-selectable" between two front-ends:

1. **Dry-contact wetting** — the default described in §8.2 (board supplies the
   wetting voltage; the machine contact closes the loop to `FIELD_GND`). This is
   the confirmed default for the cams and grippers on the 21/22 chassis (field
   sheet A4).

2. **24 VAC sense** — for any channel where the machine signal is a *live
   voltage* (24 VAC present when active) rather than a dry switch. Per
   `docs/phase8b_pcb_revB_BOM_power.md` §3.3, the AC front-end is the Rev-A
   "interposer" style: **half-wave rectifier (1N4007) + reservoir/filter cap
   (10 µF, 63 V) + bleed/discharge resistor (100 k)** ahead of the opto LED, so a
   present AC voltage is rectified into steady LED drive and a removed voltage
   discharges promptly. Contract §5.3: "24 VAC channels need rectification,
   current limiting, bleed/discharge, and opto input protection."

> **Important — what the as-built netlist actually instantiates.** The current
> `opto_input()` generator builds **only the dry-contact wetting path** (the
> `FIELD_WET_V → Rin → LED → FIELD_<name>` loop) for all 32 channels. The 24 VAC
> rectifier/cap/bleed parts are a documented **per-channel manual-population
> option**, not separate placed footprints emitted for every channel in the
> present netlist. (VERIFY: whether dedicated per-channel AC-interposer
> footprints exist on the routed board or whether the AC option is wired on a
> small external/daughter interposer at the affected channel — the generator's
> `opto_input()` does not place 1N4007/10µF/100k per channel.)

**Choosing the population per channel:** the field sheet (`A4`, `C2`, `C3`)
captures dry-vs-AC per signal; the design defaults are: cams (SA/SB/SC/TA1/TA2/TB)
= **dry**, grippers/GP/OS/BS = **dry** (chassis-referenced). Channels that prove
to be live AC (historically foul and 2nd-ball lamps on some chassis) take the AC
front-end. Per BOM_power §6, the dry-vs-AC default for any not-yet-confirmed
channel is a **fab/population decision finalized at cutover from the field
measurements**, not a board-topology change.

---

### 8.4 Why the field side is isolated from logic ground

The field side and logic side **do not share a ground**. There are two distinct
ground nets:

| Net | Domain | Where it exists |
|---|---|---|
| `GND` | Logic | Pi / RP2040 / MCP23017 / opto **logic** side (pins 3/4) |
| `FIELD_GND` | Machine sense | Opto **field** side (pins 1/2) return + the input connectors' common pins |

This separation is mandated by the contract (§2.1: "Logic ground is allowed to
exist only on the Pi/control side of optocouplers …"; §2.2 / §8.3 default:
"isolated field wetting"). The route/audit notes for the board record that on the
actual layout `GND` and `FIELD_GND` **share zero nodes** — they never touch, even
through test pads — which is the physical proof the isolation barrier is intact.

**Why it matters (operating theory):**

- **Ground-fault containment.** Machine wiring runs through a noisy, sometimes
  wet, high-energy cabinet. If a field wire shorts to chassis or to a machine
  voltage, the energy is confined to the field domain (`FIELD_WET_V` /
  `FIELD_GND`) and the opto LED — it cannot backfeed into the 3.3 V logic, the
  Pi, or the RP2040.

- **No sneak paths through the controllers.** Because the field nets only reach
  opto LEDs, a closed contact can only ever *light an LED*. It can never source
  or sink current into a microcontroller pin.

- **Common-mode rejection.** The two domains can sit at different reference
  potentials without forcing current through logic; only light crosses, so
  ground-potential differences between the machine and the control electronics
  don't corrupt readings or damage parts.

The field-wetting supply that powers this isolated domain is itself produced by
an **isolated DC/DC converter** (§8.6) precisely so the wetting rail is
galvanically separated from logic — option 1 of contract §8.3.

---

### 8.5 Active-low polarity (asserted = LOW)

Every input channel is **active-low at the logic pin**: the machine contact
closing pulls the logic node LOW, idle is HIGH (held by the 10 k pull-up to
`VCC_3V3`). Both the firmware and the FSM software encode this so a service tech
sees consistent behavior end-to-end.

| Layer | File | How active-low is expressed |
|---|---|---|
| Hardware | `scripts/generate_kicad_netlist_revB.py` (`opto_input()`) | LED in series to `FIELD_GND`; collector pulls logic node down; `Rpu` (10 k) holds it HIGH at idle |
| Firmware (fast inputs) | `firmware/rp2040/config.h` | Header note: "every fast input is opto-isolated and ACTIVE-LOW at the Pico — machine contact CLOSED (signal asserted) pulls the GPIO LOW; idle is HIGH (on-board 10k pull-up to 3V3)" |
| Software (slow inputs) | `lane_node/controller_io.py` | `INPUT_ACTIVE_LOW = True`; `_read_in()` returns asserted when `raw == 0`; "Optos are active-low at the MCP pin (switch closed → opto pulls pin LOW)" |

> **Bench bring-up consequence:** with the machine harness unplugged (all field
> contacts open), every logic node should read **HIGH** and every input should
> read **de-asserted**. Forcing a single channel's connector pin to `FIELD_GND`
> (with `FIELD_WET_V` present) should drive just that logic node LOW and assert
> just that one input. Use this as the per-channel smoke test.

---

### 8.6 The isolated field-wetting supply (`FIELD_WET_V` / `FIELD_GND`)

The wetting voltage that all dry-contact channels share is generated **on the
board** by an isolated DC/DC converter so it stays separate from logic ground:

| Item | Value (source) |
|---|---|
| Converter (generator `block_supplies()`, ref `ISO_WET`) | **TMA-0505S** isolated DC/DC, footprint `Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT` |
| Input | `+Vin` = `VCC_5V`, `-Vin` = `GND` (logic 5 V rail) |
| Output | `+Vout` = `FIELD_WET_V` (the wetting rail), `-Vout` = `FIELD_GND` (isolated return) |
| Loading | One converter feeds the field side of all dry-contact channels; total wetting current is small (only the channels whose contacts are closed draw their few-mA LED current at any instant) |

> **Part-number note / discrepancy to flag:** the as-built netlist generator and
> the part-lock-class BOM use the **Traco TMA-0505S** (5 V → 5 V, 1 W isolated).
> The earlier planning doc `docs/phase8b_pcb_revB_BOM_power.md` §3.2 *recommended*
> a "B0505S-1W" (or B0512S-1W for 12 V wetting) as an example; the board was
> built with the TMA-0505S. Trust the generator/board for the as-built part.
> (VERIFY: the exact `FIELD_WET_V` output voltage if a 12 V wetting option was
> ever populated — the as-built `ISO_WET` is the 5 V→5 V TMA-0505S, i.e. ~5 V
> wetting.)

The wetting supply is **not** on the safety rail and is **not** the machine's
24 V or 15 V supplies — those machine voltages stay external and are only ever
*switched* by the relay contacts (Section 9) or *sensed* through the AC-option
front-end; the board never sources machine coil or lamp power
(`docs/phase8b_pcb_revB_spec.md` §8.2).

---

### 8.7 Channel inventory and counts

There are **32 opto-isolated input channels = 8 fast + 24 slow**, i.e. **32
PC817B** optos total (`U4…U35` in the part lock; "PC817B optocoupler, DIP-4 …
Quantity 32"). Fast channels go to the RP2040; slow channels go to the two input
MCP23017 banks.

#### 8.7.1 Fast inputs — 8 channels → RP2040 (Pico)

Source: generator `FAST_INPUTS` (name, Pico **module** pin) + `config.h` (GPIO).
These carry the cam and ball-detect edges that the RP2040 times directly; they
must stay edge-capable with no slow RC that could mask a cam stop
(`docs/phase8b_pcb_revB_spec.md` §5.1).

| Channel | Function | Pico module pin | RP2040 GPIO | Field net | Connector |
|---|---|---|---|---|---|
| SA | sweep cam (270 run-through stop / 360 zero) | 9 | GP6 | `FIELD_FAST_SA` | `J_FAST_IN` |
| SB | sweep cam (66 guard / 186 table-spot init) | 10 | GP7 | `FIELD_FAST_SB` | `J_FAST_IN` |
| SC | sweep-under-table interlock window (86–243) | 11 | GP8 | `FIELD_FAST_SC` | `J_FAST_IN` |
| TA1 | table cam (355 zero stop / 185 delay reset) | 12 | GP9 | `FIELD_FAST_TA1` | `J_FAST_IN` |
| TA2 | table cam (260 run-through / pin-latch) | 14 | GP10 | `FIELD_FAST_TA2` | `J_FAST_IN` |
| TB | table-sweep interference interlock (105–255) | 15 | GP11 | `FIELD_FAST_TB` | `J_FAST_IN` |
| DIELL-L | ball detect, left beam (cushion SS trigger) | 16 | GP12 | `FIELD_FAST_DIELL_L` | `J_FAST_IN` |
| DIELL-R | ball detect, right beam | 17 | GP13 | `FIELD_FAST_DIELL_R` | `J_FAST_IN` |

> **Known-correct anchor:** fast inputs = **GP6..GP13**, `RP2040_OK` = GP2, UART =
> GP0/GP1. The `docs/phase8_channel_allocation.md` GPIO column (which claimed
> GP0–GP7) is **stale and wrong** — both `config.h` and the generator agree on
> GP6–GP13, and `config.h` says so explicitly.

The 8 fast channels land on the 10-pin `J_FAST_IN` connector; the generator wires
the 8 signals to pins 1–8 and ties `FIELD_GND` to pins 9 and 10.

#### 8.7.2 Slow inputs — 24 channels → MCP23017 banks

Source: generator `SLOW_INPUT_PINS` (name → (MCP bank, MCP pin)). Sixteen
channels are on bank **MCP_IN_A** (I²C `0x20`), eight on bank **MCP_IN_B** (I²C
`0x21`). The MCP23017 pin numbering used by the symbol: **GPA0–7 = pins 21–28,
GPB0–7 = pins 1–8**.

The MCP23017s are **I²C** parts (LCSC C47023, `MCP23017-E/SO`; part-lock note:
"Critical: I2C MCP23017, not SPI MCP23S17") and run at **3.3 V** so they are
Pi-safe on the shared I²C bus.

**Bank MCP_IN_A (0x20) — grippers + high-use slow inputs (16 ch):**

| Channel | Function | MCP pin | Port,bit (`controller_io.py` `IN_A_MAP`) | Connector |
|---|---|---|---|---|
| GS1 | gripper 1 | 21 | (0,0) | `J_SLOW_IN_A` |
| GS2 | gripper 2 | 22 | (0,1) | `J_SLOW_IN_A` |
| GS3 | gripper 3 | 23 | (0,2) | `J_SLOW_IN_A` |
| GS4 | gripper 4 | 24 | (0,3) | `J_SLOW_IN_A` |
| GS5 | gripper 5 | 25 | (0,4) | `J_SLOW_IN_A` |
| GS6 | gripper 6 | 26 | (0,5) | `J_SLOW_IN_A` |
| GS7 | gripper 7 | 27 | (0,6) | `J_SLOW_IN_A` |
| GS8 | gripper 8 | 28 | (0,7) | `J_SLOW_IN_A` |
| GS9 | gripper 9 | 1 | (1,0) | `J_SLOW_IN_A` |
| GS10 | gripper 10 | 2 | (1,1) | `J_SLOW_IN_A` |
| GP | gripper protect | 3 | (1,2) | `J_SLOW_IN_A` |
| OS | off-spot | 4 | (1,3) | `J_SLOW_IN_A` |
| BS | bin / #9 | 5 | (1,4) | `J_SLOW_IN_A` |
| PBZ | first-ball / zero / manual intervention | 6 | (1,5) | `J_SLOW_IN_B` |
| PBC | cycle pushbutton | 7 | (1,6) | `J_SLOW_IN_B` |
| FOUL | foul | 8 | (1,7) | `J_SLOW_IN_B` |

> **Anchor confirmation:** the BS/OS ordering and the strike/foul output ordering
> were explicitly fixed so `controller_io.py` matches the netlist (OS = pin 4 =
> (1,3); BS = pin 5 = (1,4)). `controller_io.py` ships a `__main__` regression
> test that re-derives these maps from the generator and **fails on drift** — so
> the table above is enforced in software against the board.

**Bank MCP_IN_B (0x21) — 10th-frame / manual / spare (8 ch):**

| Channel | Function | MCP pin | Connector |
|---|---|---|---|
| TENTH | 10th-frame | 21 | `J_SLOW_IN_B` |
| MAN_T | manual table | 22 | `J_SLOW_IN_B` |
| MAN_S | manual sweep | 23 | `J_SLOW_IN_B` |
| MAN_SWS | manual sweep-switch | 24 | `J_SLOW_IN_B` |
| MAN_SWSR | manual sweep-reverse | 25 | `J_SLOW_IN_B` |
| AUX1 | spare / future machine-specific | 26 | `J_SLOW_IN_B` |
| AUX2 | spare / future machine-specific | 27 | `J_SLOW_IN_B` |
| AUX3 | spare / future machine-specific | 28 | `J_SLOW_IN_B` |

> The `J_SLOW_IN_A` connector carries (in generator order) GS1–GS10, GP, OS, BS +
> a `FIELD_GND` pin; `J_SLOW_IN_B` carries PBZ, PBC, FOUL, TENTH, MAN_T, MAN_S,
> MAN_SWS, MAN_SWSR, AUX1, AUX2, AUX3 + a `FIELD_GND` pin. Each MCP23017 input bit
> still goes through its own PC817B; the connector grouping is just how the field
> wires arrive. (Per contract §7, connector cavity → C1/C2A mapping is resolved
> by the adapter harness at cutover, not baked into the board.)

#### 8.7.3 Count summary

| Group | Channels | Routed to | Optos |
|---|---|---|---|
| Fast inputs | 8 (SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R) | RP2040 GP6–GP13 | 8 × PC817B |
| Slow inputs — bank A (0x20) | 16 (GS1–GS10, GP, OS, BS, PBZ, PBC, FOUL) | MCP_IN_A | 16 × PC817B |
| Slow inputs — bank B (0x21) | 8 (TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1–AUX3) | MCP_IN_B | 8 × PC817B |
| **Total** | **32** | — | **32 × PC817B (`U4…U35`)** |

---

### 8.8 Service notes & failure modes

- **A channel always reads asserted (LOW), harness unplugged.** Suspect the field
  net shorted to `FIELD_GND`, or the PC817B LED/transistor failed short. With the
  harness off, every channel must idle HIGH (§8.5).

- **A channel never asserts even with the contact closed.** Check `FIELD_WET_V`
  is present at `Rin` (i.e. the `ISO_WET` TMA-0505S is alive), the 2k2 `Rin` is
  not open, the connector pin lands on the right `FIELD_<name>` net, and the
  PC817B is not an out-of-bin/weak-CTR substitute (see §8.2.2 CTR note).

- **All 16 bank-A or all 8 bank-B channels dead.** That points at the MCP23017
  (I²C address `0x20` / `0x21`) or the I²C bus, not the optos — confirm the
  expander enumerates on the bus first.

- **All 8 fast channels dead but slow channels fine.** Look at the RP2040/Pico
  and its 3.3 V rail, not the optos.

- **Never bridge field and logic grounds to "fix" a reading.** `GND` and
  `FIELD_GND` are deliberately isolated (§8.4); tying them defeats the safety
  isolation and can backfeed machine energy into the logic.

- **Do not "improve" a sluggish cam edge with an RC filter on a fast channel.**
  SA/SB/SC/TA1/TA2/TB must stay edge-capable for cam-stop timing
  (`docs/phase8b_pcb_revB_spec.md` §5.1); de-glitching is done in firmware
  (`config.h` `DEBOUNCE_CAM_US` / `DEBOUNCE_DIELL_US`), not with slow front-end
  RC.
