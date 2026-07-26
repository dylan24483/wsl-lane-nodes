## 4. Machine I/O Inventory (Cams, Grippers, DIELL, Foul, Mask, Buttons)

This section is the complete catalog of every electrical signal that crosses between the AMF 82-70 pinsetter and the lane-node controller: what each signal is, what physically generates it, its electrical form (dry contact vs. voltage-sense, polarity, rest/active levels), where it lands on the board, and how the firmware/FSM consumes it. If you are tracing a wire, sizing an opto front-end, or debugging "why won't this lane cycle," start here.

**Scope reminder (see §2 System Architecture):** the controller does *not* replace the machine's mechanism, motors, cams, grippers, contactors, or mask housings. It replaces only the *control brain* (the old solid-state / Omega-Tek board), reading the same machine inputs and driving the same machine control circuits the OEM board did. Everything in this section is a signal on the machine side of that boundary.

> **Chassis caveat — READ THIS.** Lanes 21/22 (the pilot pair) are an **AMF SS (solid-state) chassis retrofitted with an Omega-Tek Omniboard**; lanes 11/12 are an **AMF MP chassis (Active Technology Ultra 98)**. The *machine side* (cams, motors, grippers, DIELL, mask) is common across the fleet, which is why one controller board design serves all lanes. But the **C1/C2A connector cavity numbers and some harness landings differ per chassis** — the Omega-Tek retrofit re-routed several landings vs. the OEM factory wire tables (e.g. sweep-reverse M2 lands on C2A on our 21/22 bench, but C1 in the OEM 9800-MP tables). For that reason the controller board uses **function-named connectors** and a **per-chassis adapter harness** that is resolved at cutover, not baked into copper. Cavity codes quoted below are 225-DPI schematic best-effort guesses or single-pair bench measurements; treat them as "look here first," not gospel. The authoritative per-lane cavity map is produced at cutover (see §0/PART C of the at-machine field sheet). **Update 2026-06-27:** an at-machine metering session on 21/22 measured many of these cavities — values marked **✓ measured 2026-06-27** below are ground truth for the 21/22 chassis (proven-wrong predictions retained struck-through); the four motion-cam cavities (SA/SB/TA1/TA2) are **deferred to powered cutover** (cold reads invalidated by relay-coil sneak paths — see §4.2).

---

### 4.1 Signal-class overview

The machine I/O splits into two latency classes and three electrical domains. This split drives the board architecture (see §5 Board Architecture, §10 Safety Rail).

| Class | Signals | Why | Routed to |
|---|---|---|---|
| **FAST** (latency-critical) | DIELL ball detect (×2 beams), cams SA/SB/SC/TA1/TA2/TB | Cam-position motor stops must act in hardware, independent of Pi scheduling | RP2040 co-processor (opto-isolated), GP6–GP13 |
| **SLOW** (poll/interrupt) | Grippers GS1–GS10, GP, OS, BS, PBZ, PBC, Foul, 10th-frame, manual T/S/SWS/SWSR | Read on a state change or once per cycle; milliseconds of jitter are harmless | MCP23017 expanders (opto-isolated), I²C |
| **OUTPUTS** (relay-driven) | S, T, SP, BE, M, M2, M1 motion relays + 4 status lamps | Board closes/opens existing machine control circuits via isolated dry contacts | MCP23017 OUT-A → relay coils (S/T/SP/BE/M/M2/M1) or FET LED drivers (lamps) |

Electrical domains (kept galvanically separate on the board — see §5):
- **Logic** — Pi, RP2040, MCP23017s, 3.3 V / 5 V. Never shares ground with the machine.
- **Machine Sense (FIELD)** — the field side of every input optocoupler. Wetting is isolated from logic ground (or chassis-referenced for grippers — see §4.3).
- **Machine Output** — isolated relay *contacts* that close existing machine control circuits. The board does **not** source machine coil voltage.

---

### 4.2 The 6 cams (machine timing → FSM triggers)

The cams are mechanical microswitches actuated by lobes on the rotating sweep and table shafts. They are the machine's sense of "where am I in the cycle" and they are the primary FSM triggers (see §3 Sequence of Operation in the system overview, and `lane_node/cycle_control_8270.py`). The machine turns at ~12.1 RPM, so a full revolution is ~5 s and the cam edges are widely spaced in time — a 2 ms debounce is ample (firmware `DEBOUNCE_CAM_US = 2000`).

There are **two sweep cams that each trip at two angles** (SA, SB), one sweep interlock window cam (SC), two table cams (TA1, TA2), and one table interlock window cam (TB). The degree values below are the authoritative FSM trigger angles from `cycle_control_8270.py` constants, cross-checked against the OEM Service & Parts manual cam-timing table (system reference §3).

| Cam | Shaft | Trips at | FSM role | Firmware constant(s) |
|---|---|---|---|---|
| **SA** | Sweep | **270°** and **360°/zero** | Stop sweep run-through at 270°; stop sweep at zero (360°) | `SA_RUNTHRU` (270), `SA_ZERO` (360) |
| **SB** | Sweep | **66°** and **186°** | Guard stop at 66° (sweep stops, starts the 3 s pin-settle); initiate table spotting at 186° | `SB_GUARD` (66) |
| **SC** | Sweep | **86°–243°** (window) | Sweep-under-table half of the OEM collision interlock. **Cold-located 2026-06-27:** pink lead reaches C2A-U, a non-isolatable live-ladder region, not a dry input. The planned RP2040 echo is default-off/unvalidated. | `SC_LO`, `SC_HI` (86, 243) |
| **TA1** | Table | **355°** and **185°** | Table zero stop at 355°; at 185° reset the 3 s time-delay and flip ball memory | `TA1_ZERO` (355) |
| **TA2** | Table | **260°** | Initiate sweep run-through; **latch the gripper read** (pin/strike decision); signal "machine ready" | `TA2_RUNTHRU` (260) |
| **TB** | Table | **105°–255°** (window) | Table-sweep half of the OEM collision interlock. **Cold-measured 2026-06-27: NO standalone C2A cavity on 21/22** — neither lead isolates from the SC/U live-ladder region, so there is no independent RP2040 TB observation. | (window, interlock) |

**Electrical form — SPLIT per cam (corrected by the 2026-06-27 at-machine metering; the old blanket "all six cams NC dry" claim from field-sheet item A4 holds only for the motion cams):**

- **Motion cams SA / SB / TA1 / TA2:** independently land and measure their contact
  class plus edge→angle polarity; do not apply one blanket "normally-closed" rule.
- **SC is read on its N.O. (pink) contact**, landing at **C2A-U** — ✓ measured 2026-06-27.
- **TB has NO independent signal on the 21/22 chassis** — the 2026-06-27 cold trace found neither TB lead isolatable from the SC/U live-ladder region and exposed ~21 Ω relay-coil sneak paths. That did **not** prove topology. Powered 2026-07-07 authority: SC+TB are **parallel closed-when-safe**; either pressed lever permits a coil and both levers BACK/open kill S and T. Candidate C keeps that OEM ladder primary through the controlled J_SAFE1-2 jumper and per-lane G3 proof. GP11 has nothing to observe; the SC∧TB echo is default-off, secondary, and unvalidated.
- In the **SC/TB live-ladder region**, cold continuity probing hits ~21 Ω sneak
  paths through relay coils and cannot establish topology. The independently
  landable SA/SB/TA1/TA2 cavity/class/polarity map remains a powered-session task.
  **C2A-N is the shared motion-cam COMMON bus**, never a per-cam signal cavity.

On the board, each cam input front-end defaults to **dry-contact wetting** (the isolated wetting supply drives the opto LED through the closed cam to FIELD_GND/common). Per-channel population is jumper-selectable to a 24 VAC voltage-sense front-end if a particular chassis presents the cam as a powered line instead, but the 21/22 default is dry-contact.

> ⚠️ **(VERIFY: SA/SB/TA1/TA2 edge→angle polarity.)** The firmware forwards both
> edges, but stock v1.2.3 keeps all measured-cam enforcement flags OFF. Capture each
> independently landed motion cam, create a new controlled release with only
> confirmed values, and pass its bench gate. Do not include SC/TB in this input
> capture: lane 21/22 has no independent TB lead and SC/U is not a dry landing.

**Where they land:** cam wires enter via the machine's **A&MC ("Approach & Machine Control") plug** and run to **C2A** cavities. On the board they connect to the **J_FAST_IN** connector → PC817 optocouplers → RP2040 GPIOs:

| Cam | RP2040 GPIO | Pico pin | Net (board) |
|---|---|---|---|
| SA | GP6 | 9 | FAST_SA |
| SB | GP7 | 10 | FAST_SB |
| SC | GP8 | 11 | FAST_SC |
| TA1 | GP9 | 12 | FAST_TA1 |
| TA2 | GP10 | 14 | FAST_TA2 |
| TB | GP11 | 15 | FAST_TB |

(Source: `firmware/rp2040/config.h` `PIN_SA`..`PIN_TB`, and `scripts/generate_kicad_netlist_revB.py` `FAST_INPUTS`. **These GP6–GP13 assignments are the as-built board; the GPIO column in `docs/phase8_channel_allocation.md` §2 is STALE — it shows GP0–GP7 and must be ignored.**)

> **(VERIFY: which A&MC pin = which specific cam.)** The schematic associates the cams to A&MC pins 11A/12D/13H/14L/21B/22E/31C, but the cam↔A&MC binding cannot be read cold — it is a cutover at-machine task (rotate the mechanism, watch the cavity). The 2026-06-27 metering confirmed *why* cold reads fail: N is the shared cam common and ~21 Ω coil sneak paths make every cold read ambiguous — **per-cam SA/SB/TA1/TA2 cavity mapping is DEFERRED TO POWERED CUTOVER** (SC=U and TB=no-cavity are already measured). The board does not depend on it; the function-named harness resolves it.

---

### 4.3 The 10 gripper switches GS1–GS10 (pin sensing)

The 10 grippers are the spotting-table's pin-presence switches: as the table descends over the deck, each of the 10 spotting cups carries a switch that closes if a pin is standing in that position. Reading all 10 at the **TA2 (260°) latch point** gives the standing-pin pattern — this is the data the FSM uses for the strike/spare decision, and historically the data the OEM scorer used. (Note: for *score* purposes the Phase 8 system uses the optical camera, not the grippers; see §18. The grippers remain the FSM's machine-side standing-pin read.)

**Electrical form — CORRECTED at the machine (2026-06-03). This overturns the OEM "TAC strip with a shared common-return wire" model.** Field tracing on the real 21/22 machine established:

- **Each gripper switch closes its signal wire to the machine CHASSIS/FRAME.** The contact point a gripper closes onto is **not insulated from the frame** (continuity is only finicky due to dirt/oxide). So the **common return is the machine chassis itself**, not a dedicated "TAC-GND" bus wire.
- **There is no physical "TAC" terminal strip in the Omega-Tek cabinet.** "TAC" is the schematic net/harness name. The 10 gripper wires arrive in the machine/table harness bundle and terminate **directly on C2A cavities**.
- **Polarity (LOCKED for all 10): gripped (pin present) = switch CLOSED to ground.** This is the *opposite* sense from the cams (which are NC). Firmware: a gripper input **asserts (pulls to common) when a pin is standing**.

> ⚠️ **Board/harness impact (chassis-referenced return):** the gripper input front-ends use **machine CHASSIS as the return reference**, not the isolated FIELD_GND wetting node assumed for a clean "dry contact to a dedicated common." It is still a dry-contact-to-a-reference input (the opto field side wets through the gripper to chassis), and the grippers stay in the FIELD isolation domain — but the *return node identity* is the machine frame. The adapter harness ties gripper returns to chassis, not to a C2A common pin. (Source: `docs/phase8_bench_JOB3_C2A_inputs.md` "GRIPPER ARCHITECTURE — CORRECTED AT MACHINE"; at-machine field sheet "Grippers" result.)

**Active-low at the board:** the optos are wired so a closed machine contact pulls the MCP23017 pin **LOW** (`INPUT_ACTIVE_LOW = True` in `controller_io.py`). `read_grippers()` reads both ports of MCP23017 IN-A once and assembles a 10-bit standing-pin mask (bit *n*−1 = GS*n* standing).

**Where they land — board side (MCP23017 IN-A, I²C address 0x20):** these bit assignments are the source-of-truth map; `controller_io.py` `IN_A_MAP` is regression-checked against the PCB netlist generator (`scripts/generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS`) so software and copper cannot drift.

| Gripper | MCP23017 IN-A port.bit | MCP pin (netlist) | J_SLOW_IN_A pin | C2A cavity¹ (✓ measured 2026-06-27) |
|---|---|---|---|---|
| GS1 | A0 | 21 | 1 | **C** ✓ (matches predicted 41C) |
| GS2 | A1 | 22 | 2 | **H** ✓ |
| GS3 | A2 | 23 | 3 | **M** ✓ |
| GS4 | A3 | 24 | 4 | **S** ✓ |
| GS5 | A4 | 25 | 5 | **W** ✓ |
| GS6 | A5 | 26 | 6 | **a** ✓ (~~predicted 46Z~~ — wrong) |
| GS7 | A6 | 27 | 7 | **e** ✓ |
| GS8 | A7 | 28 | 8 | C2A-**K** ✓ measured 2026-07-07 (~~predicted 48H — PROVEN WRONG: H is GS2's cavity~~) |
| GS9 | B0 | 1 | 9 | **r** ✓ |
| GS10 | B1 | 2 | 10 | **v** ✓ (~~predicted 410U — PROVEN WRONG: U is a common rail~~) |

(Board-side source: `controller_io.py` `IN_A_MAP` + `GRIPPER_ORDER`; `generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS` and `J_SLOW_IN_A` order. MCP23017 pin numbering: GPA0–7 = pins 21–28, GPB0–7 = pins 1–8.)

> ¹ **✓ Measured at the machine 2026-06-27** by the drop-a-pin method (chassis return — set one pin, watch which cavity closes to frame), which names GS# and cavity together, so the GS#-to-cavity ordering is confirmed too. GS1–5 match the old 225-DPI schematic predictions; GS6–10 correct them — the old **GS8=48H collided with GS2=H** and **GS10=410U landed on a common rail**, both proven wrong. **GS8=K closed 2026-07-07 — the map is complete 10/10.** Common rails **J / F / U** ring to everything — never a gripper signal. The cutover drop-a-pin assert check (at-machine field sheet PART C1) remains as the final software-label verification; nothing here gates the board.

---

### 4.4 GP, OS, BS (gate / spot / bin switches)

Three individual machine-side switches that gate or advance the cycle:

| Signal | Name | Role in the cycle | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin | C2A (tentative) |
|---|---|---|---|---|---|---|
| **GP** | Gripper-protect | **Gates the 3 s pin-settle delay** — the table only descends after the delay *and* GP is closed (`gp_closed()` in the FSM; `TIME_DELAY_S = 3.0`). Guards against dropping the table on an obstruction. | dry switch closure (assumed; see VERIFY) | B2 | 3 | (still open — not resolved by the 2026-06-27 metering) |
| **OS** | Off-spot | Off-spot detect. **Not yet consumed by the FSM** — wired on the board for when full machine control grows (marked spare/⊕). | dry switch closure (assumed) | B3 | 4 | (TBD at machine) |
| **BS** | Bin / #9 bin | Closes when the 10th pin reaches the bin → triggers the **SP spot relay** for the spotting revolution (`bs_closed()` in the FSM). | dry switch closure (assumed) | B4 | 5 | **CC** ✓ measured 2026-06-27 (~~predicted 112cc~~) |

(Source: `controller_io.py` `IN_A_MAP`; `generate_kicad_netlist_revB.py` `SLOW_INPUT_PINS` GP=pin3, OS=pin4, BS=pin5. Note `controller_io.py` comment "OS=pin4=(1,3), BS=pin5=(1,4)" — these were corrected to match the netlist after a Codex catch.)

> ⚠️ **(VERIFY: GP/OS electrical form (dry vs. voltage-sense) and C2A cavities; BS form.)** The at-machine field sheet leaves GP/OS/BS rows blank (PART A4 / PART C3) — they are machine-side switches that must be actuated at the machine. The board front-ends default to dry-contact wetting like the cams (the working assumption), jumper-selectable to 24 VAC sense per channel. **BS measured at C2A-CC (✓ 2026-06-27)**; GP/OS cavities still unconfirmed. None gate the board layout.

---

### 4.5 PBZ and PBC (control-panel pushbuttons)

Two operator pushbuttons on the machine's control panel:

| Signal | Name | Role | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin |
|---|---|---|---|---|---|
| **PBZ** | Zero / 1st-2nd-ball / **Manual-Intervention** | Momentary. The **"First Ball Zero"** button. Critical safety role: after any power loss the controller comes up **fail-safe-off** and refuses motion until the operator presses this to re-zero (`first_ball_zero()` in the FSM; this is the controller-level sibling of the power-down rule, §19 Safety). | momentary closure to ground | B5 | 6 |
| **PBC** | Cycle | Momentary. Manual cycle request. **Not yet consumed by the FSM** (wired on the board, spare/⊕). | momentary closure to ground | B6 | 7 |

(Source: `controller_io.py` `IN_A_MAP` PBZ=(1,5), PBC=(1,6); `generate_kicad_netlist_revB.py` PBZ=pin6, PBC=pin7.)

These are cold-mappable at the bench (you can press them) — the field-sheet/JOB3 method is: black probe on chassis/common, hold the button, sweep the C2A cavities, find the one that closes only while pressed.

> **PBZ = C2A-EE ✓ measured 2026-06-27** (shorts to the common-U node when pressed). **(VERIFY: PBC C2A cavity.)** PBC is still unmeasured (predicted "C2A-EE area"). Not a board gate.

---

### 4.6 Foul detector (Radaray)

The foul detector is the **Radaray** unit at the foul line (an infrared/optical foul-line sensor). On lanes 21/22 the foul *lights* are driven by the legacy **ZOT board**; the foul *signal* is what the controller reads. A foul asserts the foul lamp and, in the FSM, holds the table and runs the foul sequence (system reference §2 FOUL path: foul → sweep to 66° → foul memory holds table → run-through → spotting → ball-memory flips to 2nd ball).

| Signal | Source | Role | Electrical form | Board landing (MCP23017 IN-A 0x20) | MCP pin |
|---|---|---|---|---|---|
| **Foul** | Radaray foul detector | Foul-line crossing → foul lamp + FSM foul sequence (`on_foul`) | dry contact / open-collector | B7 | 8 |

(Source: `controller_io.py` `IN_A_MAP` Foul=(1,7); `generate_kicad_netlist_revB.py` FOUL=pin8; `phase8_channel_allocation.md` §2 "Foul · Radaray · opto, edge".)

> ⚠️ **(VERIFY: Foul electrical form (dry contact vs. open-collector) and C2A cavity.)** `phase8_io_board_spec.md` lists it as "dry contact / open-collector `# CONFIRM`"; the JOB3 / field-sheet Foul cavity is "(TBD)". The board treats it as an edge-triggered FIELD-domain input; front-end population is decided after the at-machine measurement.

---

### 4.7 DIELL ball detect (the cycle trigger) ⭐

This is the single most important *input* in the system: on the 82-70, the cushion's shock absorber actuates a **Start Switch (SS)** that is the cycle trigger. **On the Westside lanes the SS function is performed by DIELL photoelectric ball-detect sensors** (there is no separate cushion microswitch in the read path). When a thrown ball breaks the beam, that is the "ball delivered" event that starts the whole cycle. Physical inspection confirms DIELL's cycle-trigger role but found no C.I.S. device or wiring on lanes 21/22. **Do not count DIELL as a personnel/pit-entry safety interlock**; §19's pit-entry disposition remains open.

There are **two beams per lane** (left/right, mounted on the kickback), coalesced into one logical "ball" event in firmware.

**Sensor part / type:** DIELL **LSC/AN-2C6J** photoelectric sensor. The **`AN` suffix = NPN output** (DIELL convention; `AP` would be PNP).

**Electrical form — FULLY CHARACTERIZED (this is the one machine input whose front-end is proven end-to-end):**

| Parameter | Value | Notes |
|---|---|---|
| Output type | **NPN open-collector, active-low** | NPN means the sensor sinks to ground when active; needs a pull-up on the read side |
| Supply | **24 V** (per-lane sensor supply) | from the lane_visit characterization |
| **Rest** (beam intact, no ball) | **~16 V** | open-collector pulled up; line sits high-ish |
| **Active** (beam broken, ball passing) | **~0.7 V** | open-collector pulls the line down to near ground |

(Source: `phase8_io_board_spec.md` §1 row 1 "16 V rest → 0.7 V broken, NPN active-low (characterized)"; `phase8_bench_mule_characterization.md` "DIELL ball-detect … ~16 V rest / 0.7 V broken, NPN active-low"; `docs/lane_visit_checklist.md` Phase 4 LEFT row "AN / 24V / 0V / NPN open-collector".)

**Proven signal chain (bench + at-machine validated):** DIELL → AL-ZARD 8-channel opto board (during the Phase-8a pilot) → Pi GPIO 17 → daemon. On the controller PCB this becomes DIELL → **J_FAST_IN** → on-board PC817B optocoupler → RP2040 GPIO (active-low at the Pico, idle HIGH via external `Rpu_*` to 3V3). The historical Rev-B `Rpu_*` value was 10 kΩ; the current Rev-D value is **47 kΩ**, and firmware disables the RP2040 internal pulls. The firmware de-bounces at `DEBOUNCE_DIELL_US = 500` (faster than the cams), and applies a `BALL_LOCKOUT_MS = 300` re-trigger lockout so one thrown ball produces exactly one `ball` event.

| Beam | RP2040 GPIO | Pico pin | Net | Firmware constant |
|---|---|---|---|---|
| DIELL-L (left) | GP12 | 16 | FAST_DIELL_L | `PIN_DIELL_L` |
| DIELL-R (right) | GP13 | 17 | FAST_DIELL_R | `PIN_DIELL_R` |

(Source: `firmware/rp2040/config.h` `PIN_DIELL_L`/`PIN_DIELL_R`; `generate_kicad_netlist_revB.py` `FAST_INPUTS` `DIELL_L`=16, `DIELL_R`=17. Firmware `main.c` coalesces both beams: a debounced beam-break emits `{"ev":"ball","src":"L|R", ...}` subject to the 300 ms lockout.)

> **Why DIELL is on the FAST path even though "ball thrown" isn't microsecond-critical:** it shares the RP2040 with the cams because the RP2040 is the board's hardware-real-time front end, and the ball event participates in the cycle-start timing. The capture-timing hook (frame after DIELL + ~2.5 s settle) is what the camera scoring uses (see §18).

---

### 4.8 Mask status lamps (replaced by our LEDs)

The 82-70 mask housing originally carried, in addition to the 10 pin-indicator lamps (omitted in our build — camera scoring replaces them, see §18 and §4.9), **four status lamps**: 1st-ball, 2nd-ball, strike, foul. The OEM drove these at **12 VDC** through the mask connector positions PM-E24/E25/E26/E27; the at-machine field sheet measured the actual mask-lamp supply at **15 VDC** (item A3).

**Rev-B decision: the machine mask-lamp supply is NOT used.** Dylan's contract decision is to **install our own LEDs in the existing mask housings** and drive them from the board. The board drives each LED low-side from **VCC_5V logic power** through a **2N7002-class N-MOSFET** with a per-channel current-limit resistor (`Rled_*`, scaffolded at **330R** — final value TBD per LED brightness, see VERIFY). There is therefore **no LOGIC-to-MACHINE isolation barrier on the status LEDs** (they are pure logic-domain outputs, not machine-output contacts), and they are **not on the safety rail** (non-motion-critical).

| Lamp | FSM `set_light` name | OEM mask position | OEM supply | Board: MCP23017 OUT-A port.bit | MCP pin | Board net | Driver |
|---|---|---|---|---|---|---|---|
| 1st-ball | `first_ball` | PM-E24 | 12 VDC (OEM) / 15 VDC (measured) | A7 | 28 | L_FIRST | 2N7002 low-side, 330R limit |
| 2nd-ball | `second_ball` | PM-E25 | " | B0 | 1 | L_SECOND | " |
| strike | `strike` | PM-E26 | " | B1 | 2 | L_STRIKE | " |
| foul | `foul` | PM-E27 | " | B2 | 3 | L_FOUL | " |

(Source: lamp roles + PM-E positions from `phase8_io_board_spec.md` §1 outputs row 3 and system reference §4; board bits from `controller_io.py` `OUT_A_MAP` (`first_ball`=(0,7), `second_ball`=(1,0), `strike`=(1,1), `foul`=(1,2)) and `generate_kicad_netlist_revB.py` `OUTPUT_PINS` L_FIRST=28/L_SECOND=1/L_STRIKE=2/L_FOUL=3; driver topology from `phase8b_pcb_revB_spec.md` §3.3 and netlist `lamp_led_output()` (2N7002 + 330R `Rled_*`). LED returns wire to the **J_LAMP_LED** 6-pin connector: VCC_5V, GND, then the four LED-return lines.)

> **(VERIFY: final mask-LED type and `Rled_*` current-limit value (330R is a scaffold placeholder).** Per `phase8b_pcb_revB_spec.md` §11 item 5, the LED part and per-channel resistor must be locked for bowling-center brightness before assembly.) Note the OEM supply discrepancy: system reference says 12 VDC, the at-machine measurement says **15 VDC** — moot for our build since we abandon the machine lamp supply, but recorded here for anyone restoring the OEM mask.

---

### 4.9 The 7 relay-driven outputs (S / T / SP / BE / M / M2 / M1)

These are the controller's machine *outputs*. **Critical operating principle (see §3, §6):** the board does **not** switch motor current and does **not** source machine coil voltage. Each output is an **isolated dry relay contact** that closes/opens an *existing machine control circuit* — the machine's own contactors continue to switch the 115 VAC motors and retain their OEM run/braking behavior. The board commands coils; the machine's iron switches the motors. This preserves motor inrush handling and regenerative braking on the existing contactors, and is the key simplicity/safety win.

**Working voltage of the switched circuits:** the at-machine field sheet (item A1) measured **24 VAC** on the relay/coil circuits for all relays (SP presumed same). So each on-board relay contact only needs to make/break a **24 VAC contactor-coil circuit** — a small load, well within the relay's rating. (This 24 VAC measurement also lets the board's LOGIC↔MACHINE creepage relax from the conservative 250 VAC assumption in a future spin; the current fab board is still routed at the conservative spacing.)

**The relay (do not substitute the coil voltage):**

| Item | Value |
|---|---|
| Relay part | **Omron G5LE-14, 5 VDC coil**, SPDT |
| LCSC | **C116963** |
| Footprint | `Relay_THT:Relay_SPDT_Omron-G5LE-1` |
| Designators | K1–K6 (K7/M1 is DNP — see below) |
| BOM note | *"Critical: 5VDC coil. Do not substitute 9V/12V/24V coil."* |

(Source: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv` line for C116963. **The coil rail is 5 V**, driven by the logic-side 5 V supply through the relay-enable rail — *not* 24 V. The machine's 24 VAC is on the *contact* side only.)

**Coil drive chain (per relay):** MCP23017 OUT-A bit → series base resistor (1k) → **MMBT3904 NPN** (low-side) → relay coil. Coil high side connects to the **RELAY_ENABLE_RAIL** (the safety rail, §10); a **1N4148WS** flyback diode sits across the coil. Contacts (COM/NO) go to a per-function 2-pin terminal block (`J_MOTION_<name>`) with DNP RC-snubber + MOV footprints across the contact for AC-inductive suppression.

(Source: `generate_kicad_netlist_revB.py` `relay_output()`: `MMBT3904` Qk_*, `Rb_*`=1k, coil high to `RELAY_ENABLE_RAIL`, `Dfly_*`=1N4148, `Rsnub_*`=100R DNP, `Csnub_*`=10nF X2 DNP, `MOV_*` DNP. Per-relay flyback/snubber confirms `phase8b_pcb_revB_spec.md` §3.2.)

**The 7 outputs:**

| Output | Function | FSM use | Contact form | On safety rail | MCP23017 OUT-A port.bit | MCP pin | Net | Connector (bench / OEM-ref)¹ |
|---|---|---|---|---|---|---|---|---|
| **S** | Sweep motor contactor command | `set_sweep` (active) | isolated NO dry contact | **yes** | A0 | 21 | DRV_S → OUT_S_A/B | bench: **C1** (cavities C,D,N,T) |
| **T** | Table motor contactor command | `set_table` (active) | isolated NO dry contact | **yes** | A1 | 22 | DRV_T | bench: **C1** (cavities A,K,H,E,L) |
| **SP** | Spot solenoid command | `set_spot` (active) | isolated NO dry contact | **yes** | A2 | 23 | DRV_SP | bench: **C2A** (0 Ω) |
| **BE** | Back-end command (elevator/carpet/distributor/ball-lift; runs continuously) | future (⊕) | isolated NO dry contact | **yes** | A3 | 24 | DRV_BE | bench: straddles **C1+C2A** (coil also taps C1-FF @66Ω) |
| **M** | Master / control command | future (⊕) | isolated NO dry contact | **yes** | A4 | 25 | DRV_M | TBD at machine |
| **M2** | Sweep-reverse command | future (⊕) | isolated NO dry contact | **yes** | A5 | 26 | DRV_M2 | ⚠️ **OEM≠bench:** OEM=C1-17DD/18JJ/26BB/27FF + TSA/Expander; our bench=**C2A** (0 Ω) |
| **M1** | Ball-return command | none (DNP) | isolated NO dry contact | yes | A6 | 27 | DRV_M1 | **POPULATE-OPTIONAL / DNP** |

(Source: `controller_io.py` `OUT_A_MAP` (S=(0,0)…M1=(0,6)) — regression-checked against `generate_kicad_netlist_revB.py` `OUTPUT_PINS`; connector/cavity data from `phase8_channel_allocation.md` §3 "HARNESS UPDATE (bench-confirmed 2026-06-01)" and `phase8b_pcb_revB_spec.md` §3.2.)

Notes:
- **Bit-order gotcha:** in OUT_A the order is **M2 (bit A5, pin 26) before M1 (bit A6, pin 27)** — this matches the generator (`OUTPUT_PINS` M2=26, M1=27), not alphabetical. `controller_io.py` flags this explicitly.
- **M1 is DNP (do-not-populate).** Ball-return as a *separate* relay was never bench-confirmed on the 21/22 chassis and the FSM doesn't drive it. The footprint (K7/Q7/R85-R87/D13-D14/C10) is present but flagged DNP + excluded from BOM/POS. **Do not populate or harness M1 until confirmed at-machine** (`phase8b_pcb_revB_spec.md` §3.2, §11 item 6).
- **BE, M, M2, M1 are spare/future (⊕):** the minimum-viable FSM today drives only **S, T, SP** (motion) + the 4 lamps. BE/M/M1/M2 are wired on the board for when full machine control grows (`phase8_channel_allocation.md` §1).
- **S/T must not become the motor contactor or braking path** — the board only commands the *control/coil* circuit of the existing contactors; the OEM start/run/brake contacts stay on the machine (`phase8b_pcb_revB_spec.md` §3.1).
- **M2/sweep-reverse interlock:** regardless of which connector M2 lands on, the OEM Expander path includes a sweep-reverse motor-start interlock and a shorting-plug requirement ("expander cable must be terminated or sweep won't run"). The harness must **preserve that interlock function**, not merely jumper the cavity.

> ¹ **(VERIFY: all C1/C2A cavity landings for the 7 outputs.)** The "connector side" column is **OEM-reference / single-pair-bench only and is NOT a copper constraint** — the OEM factory wire tables and our Omega-Tek bench disagree on cavity routing (both correct for their chassis). M and M1 landings are unmeasured. Exact per-chassis terminal landings are resolved by the adapter harness at cutover (at-machine field sheet PART C). Do NOT bake any of these into copper.

> ⚠️ **(VERIFY: relay contact current rating + snubber/MOV population.)** At-machine field-sheet item A2 (coil/control current per output) was left blank/deferred to cutover; `phase8b_pcb_revB_spec.md` §11 items 1–2 list "confirm contact current/voltage for S/T/SP/BE/M/M2 and whether G5LE-1 margin is sufficient" and the 5 V coil-rail budget as open before assembly. The G5LE 10 A contact is almost certainly ample for a 24 VAC coil load, but it is not yet measured.

---

### 4.10 Cross-references and the "what's confirmed vs. deferred" summary

- Full sequence-of-operation (how these signals drive the cycle): **§3 Sequence of Operation / FSM** (and `lane_node/cycle_control_8270.py`).
- Camera scoring that replaces the pin-indicator lamps and uses the DIELL event for capture timing: **§3 System Architecture & Scoring**.
- Board electrical domains, opto front-ends, MCP23017/RP2040 bus, connectors: **§5 Board Architecture**.
- The relay-enable rail, NE555 watchdog, RP2040 RP_OK, TB/SC interlock, power-down/First-Ball-Zero rule: **§19 Safety Architecture**.

**Confirmed (locked) machine-I/O facts:**
- Motion-cam form (SA/SB/TA1/TA2) remains subject to the powered cavity/class/polarity capture; **SC's pink lead cold-locates at C2A-U but stays unlanded as a dry input, and TB has no independent signal. Powered truth is SC+TB parallel closed-when-safe; the cold session did not prove topology** (see `docs/phase8_interlock_redesign.md`). DIELL = NPN open-collector, ~16 V rest / ~0.7 V broken, 24 V supply (characterized end-to-end). Grippers = chassis-return, gripped = closed-to-ground (corrected at machine); **gripper cavities GS1=C 2=H 3=M 4=S 5=W 6=a 7=e 8=K 9=r 10=v (complete 10/10), PBZ=EE, BS=CC (✓ measured 2026-06-27/07-07)**. Output working voltage = 24 VAC (A1). Relay = Omron G5LE-14 **5 VDC** coil (C116963). Opto = PC817B (C5692981). Expander = MCP23017 I²C (C47023, *not* SPI). Watchdog timer = bipolar NE555 (NE555DR, C7593). RP2040 fast inputs = **GP6–GP13** by board design, but GP11/TB is unpopulated in the lane-21/22 harness; RP2040_OK = GP2, UART = GP0/GP1. Board = 250×225 mm, 4 copper layers.

**Deferred to cutover (do NOT guess, NOT board-gating):**
- Per-cam **SA/SB/TA1/TA2**→C2A cavity (**POWERED cutover only** — cold reads invalidated 2026-06-27 by the shared N common + relay-ladder coil sneak paths, ~21 Ω) + edge-to-angle polarity (still unmeasured); exact C1/C2A landings for all 7 outputs; GP/OS/Foul/PBC cavities and (for GP/OS/Foul) dry-vs-AC form; relay contact current (A2); mask-LED type + `Rled_*` value; M1 existence as a separate relay. *(Resolved 2026-06-27/07-07, no longer deferred: complete gripper GS#→cavity map + GS#-to-pin order (10/10 incl. GS8=K), SC=U, TB=no independent signal (series interlock — landing = the shared U node), PBZ=EE, BS=CC.)*
