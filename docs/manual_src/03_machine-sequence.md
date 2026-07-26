## 3. The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing

> **What this section is.** A from-scratch description of the AMF 82-70 pinsetter as a *machine* — its mechanical assemblies, its motors, its position-sensing cams, and the exact step-by-step control sequence it executes for every ball, strike, and foul. **This is the behavior our Raspberry Pi controller reproduces.** The Pi does not invent a new way to run the machine; it reads the same switches and drives the same motor/solenoid/lamp circuits the original AMF "brain" did, in the same order, with the same timing. If you understand this section, you understand what the firmware and the cycle FSM are *for*.
>
> **Why we can replace only the brain.** AMF itself proved this is possible. The microprocessor "MP" chassis (part `#070-009-800`) was a factory **drop-in replacement for the older 5-board Solid-State (SS) chassis**, using the *same machine inputs and outputs* — only the decision-making medium changed (discrete relay/logic → microprocessor). Our Pi controller is, functionally, "a modern MP chassis." The MP wiring schematic (drawing `9807`) deliberately *omits* the microprocessor's internal logic and shows only how the chassis connects to the machine — so that schematic **is** the interface specification, and the omitted logic is exactly the part this manual's firmware and FSM supply.
>
> **Source of truth.** Every machine behavior, cam angle, and sequence step below is taken from the two AMF manuals mined in full: the *8270 MP Operation Training Manual* (PN 610000009) and the *8270 Service & Parts Manual* (PN 610007028, AMF 82-70C, rev 8/95), as distilled into `docs/phase8_8270_SYSTEM_REFERENCE.md` and constrained by the OEM read-through in `docs/phase8_oem_doc_audit_2026-06-02.md`. Where a connector cavity, coil voltage, or lamp voltage is **not** yet confirmed on *our* specific chassis (an SS chassis retrofitted with an Omega-Tek Omniboard on lanes 21/22; a factory Active-98 MP on 11/12), it is marked **(VERIFY: …)** inline. Do not treat a VERIFY value as gospel.

---

### 3.1 The Nine Machine Assemblies

The 82-70 is a **free-fall, string-less, table-and-sweep** pinsetter. Pins are physically set by a **spotting table** that descends with ten gripper cups; a **sweep** rake clears downed pins between balls; and a continuously-running **back-end** circulates pins from the pit back up to the table. The controller's entire job is to start and stop the **sweep motor** and **table motor** at the right cam angles, read the **grippers** and a handful of **switches**, fire the **spot solenoid**, and light the **mask lamps**.

The Service & Parts manual organizes the mechanism into nine assemblies. They are listed here in the order pins flow through them, with the controller-relevant sensors and actuators called out.

| # | Assembly | What it does | Controller-relevant I/O on/near it |
|---|---|---|---|
| 1 | **Cushion** | Backstop that absorbs ball/pin impact at the pit end. Its shock absorber mechanically actuates the **start switch (SS)** — the cycle trigger. | **SS** start switch (on *our* lanes this is replaced by the **DIELL** optical ball detector — see §3.6 and Section 2 *(System Overview & Track A/B Architecture)*). |
| 2 | **Ball Lift** | Lifts the bowling ball out of the pit and returns it up the ball track to the bowler. Driven by the back-end (BE) motor. | (no dedicated control input; runs with BE) |
| 3 | **Sweep** | The rake bar. Sweeps across the pin deck to clear dead wood into the pit, then guards the deck while the table spots. Driven by the **sweep motor (S)**, which runs **intermittently** per cycle. | Sweep cams **SA, SB, SC** ride the sweep-motor shaft (§3.4). |
| 4 | **Carpet** | The pit carpet / conveyor that moves fallen pins toward the elevator. Part of the continuously-running back-end. | (no dedicated control input) |
| 5 | **Pin Elevator** | Lifts fallen pins up out of the pit to the distributor. Continuously-running back-end. | (no dedicated control input) |
| 6 | **Distributor** | Orients and routes elevated pins into the ten bins above the deck. Continuously-running back-end. | (no dedicated control input) |
| 7 | **Bin** | Ten-position pin magazine above the deck that holds pins ready to drop into the table cups. The **#9 bin** carries the **bin switch (BS)** that signals "10th pin delivered." | **BS** bin switch (#9 bin). |
| 8 | **Table** | The spotting table: 10 spotting cups + 10 respot cells, each with a **gripper switch (GS)**. Descends to set/respot pins; reads which pins are standing. Driven by the **table motor (T)**, which runs **intermittently** per cycle. | **GS1–GS10** gripper switches (standing-pin read); table cams **TA1, TA2, TB** (§3.4); **spot/respot solenoids** (via the **SP** relay). |
| 9 | **(Chassis / control assembly)** | **(VERIFY: the ninth assembly.** `phase8_8270_SYSTEM_REFERENCE.md` §1 states "Nine assemblies" but enumerates only the eight mechanical assemblies above. The ninth is most likely the **control chassis / DC control box** itself — the assembly we are replacing — but the exact AMF name for the ninth item is not pinned down in the mined notes. Confirm against the Service & Parts manual assembly index before printing this as final.) | The chassis terminates **C1** and **C2A** (see §3.7) and houses the relays/logic. |

#### Motor running pattern (memorize this)

This is the single most important behavioral fact for the controller:

| Motor | Relay | Runs | Notes |
|---|---|---|---|
| **Back-End (BE)** | `BE` | **Continuously** while the machine is in "Bowl" | Drives Ball Lift + Carpet + Pin Elevator + Distributor as one mechanical group. The controller energizes it once and leaves it on; it is **not** cam-timed and **not** subject to the motion timeout. |
| **Sweep (S)** | `S` | **Intermittently**, once per cycle | Started by the controller, stopped at cam angles (SB 66°, SA 270°, SA 360°). ~**12.1 RPM**, capacitor-induction, **115 VAC** (VERIFY: 12.1 RPM and 115 VAC are the documented machine figures; confirm against the motor nameplate on our chassis). |
| **Table (T)** | `T` | **Intermittently**, once per cycle | Started by the controller, stopped at cam angles (TA1 355°/zero). Same ~12.1 RPM / cap-induction / 115 VAC class as the sweep. |

> **Motor current never touches our PCB.** The Pi controller board commands the **existing S/T machine contactors** through isolated dry relay contacts; the contactors continue to switch the 115 VAC motor current and provide their original **regenerative braking** (the de-energized **N.C.** contacts switch capacitors across the main winding). The board must *command* those contactor control circuits, never *become* the contactor or the brake path. See Section 9 *(Machine Outputs — the Output Contract / Relay Stage)* and §3.3 of `phase8b_pcb_revB_spec.md`.

---

### 3.2 How a Cycle Works (the mental model)

The 82-70 has **no single "advance one step" pulse**. (An earlier draft FSM, `cycle_control.py`, wrongly modeled it as one-pulse-per-cycle and is **void**.) Instead:

1. A ball is thrown. The **cushion's SS switch** (our **DIELL** beam) tells the controller "ball delivered — start a cycle."
2. The controller **energizes the sweep motor** and lets it run. The sweep motor turns a shaft carrying the **sweep cams (SA/SB/SC)**.
3. As the shaft rotates, each cam **trips a microswitch at a specific angle**. The controller watches those switch edges and **de-energizes the motor when the cam reports the target degree.** That is how the sweep "stops at 66°," "stops at 270°," etc. — there is no mechanical detent; **the stop is a control decision** made by reading a cam and dropping a relay.
4. The same is true for the **table motor** and its **table cams (TA1/TA2/TB)**.
5. In between, the controller reads the **grippers** (which pins are standing), runs a **3-second settle delay**, fires the **spot solenoid** when a fresh rack is needed, and updates the **mask lamps**.

So the controller is an **event-driven state machine**: cam-switch transitions (plus SS/ball, the grippers, the bin switch, the foul detector, and the 3-second timer) drive state changes; each state sets motor / solenoid / lamp outputs. This is exactly the structure of `lane_node/cycle_control_8270.py` (the `CycleController` FSM) — its handlers (`cam_SB_guard`, `cam_TA2_runthrough`, `cam_SA_runthrough`, `cam_TA1_zero`, `bin_full`, …) map one-to-one onto the steps below. The cam *edges* are detected by the RP2040 firmware and forwarded to the Pi (see Section 15 *(RP2040 Firmware)* and §3.6 here).

> **Critical safety nuance.** Because the cam-position stops are **controller logic** (read cam → drop relay), they are **not** a hardwired motor latch. The Pi *times* them. The hardware backstops that exist independently of the Pi are: the **TB/SC table-sweep collision interlock**, the **regenerative relay braking**, the **NE555 watchdog**, the **RP2040 health line**, and the installed **Stop/master-breaker** chain. OEM references also describe C.I.S.; lanes 21/22 have no such device or wiring. See §3.8 and Section 10.

---

### 3.3 Sequence of Operation — FIRST BALL

This is the canonical cycle: a ball is thrown on the first ball of a frame, knocks down some pins, and leaves others standing. The table **respots the held standing pins** (it does **not** spot a fresh rack — that distinction is the heart of the logic).

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | **SS closes** (ball delivered; our DIELL beam breaks) while machine is **READY** and the **interlock is OK** | Energize **sweep motor (S)**; cycle = `FIRST_BALL`; state → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep reaches **66°** | De-energize sweep (it now **guards** the deck); start the **3-second time delay**; state → `GUARD_DELAY` | **SB** @ 66° |
| 3 | 3 s elapsed **AND GP (gripper-protect) closed** | Energize **table motor (T)** — table descends; state → `TABLE_DETECT` | 3 s timer, gated by **GP** |
| 4 | Table reaches **260°** | **Latch the standing-pin mask** by reading **GS1–GS10**; **latch the pin lamps** (12 VDC; KX relay historically sent this pin data to the scorer); signal "machine ready" to the scoring computer; **re-energize the sweep** for its run-through; state → `RUNTHROUGH`. *Decision point:* if the mask is **non-zero** (pins standing) the cycle stays `FIRST_BALL` (respot path). | **TA2** @ 260° |
| 5 | Sweep reaches **270°** | De-energize sweep (run-through complete); state → `TABLE_FINISH`. First-ball-with-pins needs **no SP** — the table is respotting the held pins, not spotting a fresh rack. | **SA** @ 270° |
| 6 | Table passes **185°** | **Reset the time-delay memory** (no motor change) | **TA1** @ 185° |
| 7 | Table reaches **355° / zero** | De-energize table; **flip ball memory: 1st-ball light OFF, 2nd-ball light ON**; clear strike/foul lamps; state → `READY` (now awaiting the **second** ball) | **TA1** @ 355°/zero |
| 8 | Sweep returns toward **360°** | Sweep stops at zero (parked) | **SA** @ 360° |

FSM anchors (from `cycle_control_8270.py`): handlers `on_ball` → `cam_SB_guard` → `poll()` (3 s + GP) → `cam_TA2_runthrough` → `cam_SA_runthrough` → `cam_TA1_zero`; `_needs_fresh_rack()` returns **False** for `FIRST_BALL`, so `bin_full()` (BS) is a no-op on this cycle.

---

### 3.4 Sequence of Operation — SECOND BALL

On the second ball, the **ball memory is inverted** (the FIRST-BALL cycle flipped it). After the second ball, the deck is cleared and a **fresh full rack is spotted** via the **spot solenoid (SP)**, gated by the **bin switch (BS)**.

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | **SS closes** while READY (ball memory = 2nd) | Energize sweep; cycle = `SECOND_BALL`; → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep reaches **66°** | De-energize sweep (guard); start **3 s** delay; → `GUARD_DELAY` | **SB** @ 66° |
| 3 | 3 s **AND GP closed** | Table descends; → `TABLE_DETECT` | timer + **GP** |
| 4 | Table reaches **260°** | Latch grippers + pin lamps; re-energize sweep for run-through; → `RUNTHROUGH` | **TA2** @ 260° |
| 5 | Sweep reaches **270°** | De-energize sweep; → `TABLE_FINISH` (this cycle **awaits BS** to spot a fresh rack) | **SA** @ 270° |
| 6 | **10th pin delivered to bin → BS closes** | Energize the **SP spot relay**; the table runs a **spotting revolution** to set a new full rack; state → `SPOTTING` (gated by interlock OK) | **BS** (#9 bin) |
| 7 | Table reaches **355° / zero** | De-energize **SP**; de-energize table; **reset ball memory → 1st ball** (1st-ball light ON); → `READY` | **TA1** @ 355°/zero |
| 8 | Sweep returns to **360°** | Sweep parks at zero | **SA** @ 360° |

FSM anchors: `_needs_fresh_rack()` returns **True** for `SECOND_BALL`, so `bin_full()` (BS) fires `set_spot(True)` and enters `SPOTTING`; `cam_TA1_zero()` then releases SP (`set_spot(False)`) and finishes. **(VERIFY: SP de-energize timing and SP pulse-vs-continuous behavior** — `cycle_control_8270.py` marks the exact SP-release-vs-cam relationship `# CONFIRM`; confirm on the bench against the spotting-revolution geometry. SP routing is **(VERIFY: SP connector cavity** — OEM/FSM comments cite `C1-35U/36Y`, but our SS + Omega-Tek bench measured **SP at C2A (0 Ω)**; harness-resolved per chassis.)

---

### 3.5 Sequence of Operation — STRIKE and FOUL

#### STRIKE

A strike is a **first-ball cycle in which no pins remain** (the gripper mask reads zero at 260°). The machine then behaves like a fresh-rack cycle (spot a new rack) rather than a respot.

| Step | Trigger / condition | Controller action | Cam / source |
|---|---|---|---|
| 1 | SS closes while READY (1st ball) | Energize sweep; cycle = `FIRST_BALL`; → `SWEEP_TO_GUARD` | SS / DIELL |
| 2 | Sweep **66°** | De-energize sweep (guard); 3 s delay | **SB** @ 66° |
| 3 | 3 s + **GP closed** | Table descends; → `TABLE_DETECT` | timer + **GP** |
| 4 | Table **260°** | Read grippers → **mask == 0** → **set STRIKE memory**: cycle becomes `STRIKE`, **strike lamp ON**, **1st-ball lamp OFF**. Strike holds the table for fresh-rack spotting. Re-energize sweep for run-through; → `RUNTHROUGH` | **TA2** @ 260° |
| 5 | Sweep **270°** | De-energize sweep; → `TABLE_FINISH` (awaits BS, like 2nd ball) | **SA** @ 270° |
| 6 | **BS closes** | Energize **SP**; table spotting revolution (fresh rack); → `SPOTTING` | **BS** |
| 7 | Table **355°/zero** | De-energize SP + table; **strike memory resets** (lamps cleared) once sweep + table reach zero; **ball memory → 1st ball**; → `READY` | **TA1** @ 355°/zero |

FSM anchor: in `cam_TA2_runthrough()`, `if self.cycle is Cycle.FIRST_BALL and self.pins == 0:` promotes the cycle to `STRIKE` and lights the strike lamp; `_needs_fresh_rack()` is **True** for `STRIKE`.

#### FOUL

The **foul detector (Radaray)** fires when the bowler crosses the foul line. The foul is flagged on the *first* ball, the foul lamp lights, and a **foul memory** holds the table while the sweep clears and a rack is spotted; the cycle then advances to the second ball.

| Step | Trigger / condition | Controller action | Source |
|---|---|---|---|
| 1 | **Foul detector (Radaray) fires** during a 1st-ball cycle | **Foul lamp ON**; set foul logic; cycle = `FOUL` (only if currently on the first ball) | Radaray **Foul** input |
| 2 | Sweep runs to **66°** | Sweep guard; **foul memory holds the table** | **SB** @ 66° |
| 3 | Sweep run-through to **270°** | (clear deck) | **SA** @ 270° |
| 4 | **BS closes** | Table spotting revolution | **BS** |
| 5 | Cycle completes | **Ball memory flips → 2nd ball** | **TA1** @ 355°/zero |

FSM anchors: `on_foul()` sets `Cycle.FOUL` and `set_light('foul', True)`. **(VERIFY: foul respot semantics.** `cycle_control_8270.py::_needs_fresh_rack()` *currently treats FOUL as a fresh-rack/SP cycle as a placeholder* and is explicitly marked `# CONFIRM` — real foul behavior on the 82-70 varies (some configurations respot held pins after a first-ball foul rather than spotting a full rack). **Confirm the exact foul respot vs. fresh-rack behavior on the bench/at-machine before live.** The `SYSTEM_REFERENCE` §2 FOUL line says the foul cycle "flips → 2nd ball" but does not settle the SP question.)

---

### 3.6 Cam Timing Table (authoritative)

These six cams are the **position feedback** for the two intermittent motors. Each is a microswitch riding a lobe on the motor shaft; the controller reads the switch edge and acts. **These angles are the FSM's triggers** and are reproduced verbatim from `phase8_8270_SYSTEM_REFERENCE.md` §3 and `cycle_control_8270.py`'s `CAM TIMING` constants.

| Cam | On shaft | Trips at | Role in the sequence |
|---|---|---|---|
| **SA** | Sweep | **270°** + **360° / zero** | Stop the sweep **run-through @270°**; stop the sweep **@zero (360°)** when parking. |
| **SB** | Sweep | **66°** + **186°** | **Guard stop @66°** (sweep halts, deck guarded, 3 s delay begins); **initiate table spotting @186°**. |
| **SC** | Sweep | **86° – 243°** (window) | **Sweep-under-table interlock** window — half of the TB/SC collision interlock (§3.8). Not a "stop" cam; a safety window. |
| **TA1** | Table | **355°** (+ **185°**) | **Table zero stop @355°**; **@185° reset the time-delay** memory. |
| **TA2** | Table | **260°** | **Initiate the sweep run-through**; **latch the pin lamps**; make the **ball/strike decision** (read grippers; zero → strike). |
| **TB** | Table | **105° – 255°** (window) | **Table-sweep interference interlock** window — the other half of the TB/SC collision interlock (§3.8). A safety window, not a stop. |

Code constants (`cycle_control_8270.py`), for cross-checking firmware/FSM against this table:

```text
SB_GUARD      = 66     SB_SPOT       = 186
SA_RUNTHROUGH = 270    SA_ZERO       = 360
SC_LO, SC_HI  = 86, 243
TA1_DELAYRESET= 185    TA1_ZERO      = 355
TA2_RUNTHROUGH= 260
TB_LO, TB_HI  = 105, 255
```

> **Timing is tight — budget input latency.** The OEM audit (`phase8_oem_doc_audit_2026-06-02.md` §3) flags that SA/TA-2 overlap and the run-through stops happen fast enough that **slow RC or firmware debounce on the cam channels could hide an edge or an overlap.** That is why the cams are **fast inputs on the RP2040** (edge-capable), not slow MCP23017 inputs. The documented debounce budget is **`DEBOUNCE_CAM_US = 2000 µs` (2 ms)** — ample for mechanical microswitches on a ~12 RPM shaft without masking the trip edges. See Section 15 and `firmware/rp2040/config.h`.
>
> **Edge polarity is a deferred field item.** The RP2040 forwards each cam edge tagged `f` (asserted/fall) or `r` (released/rise); **which physical edge is the angular "trip" is bench-confirmed per cam** at cutover (firmware README + `phase8_trackB_controller_cutover_runbook.md`). The firmware deliberately does **not** bake in unconfirmed cam→angle polarity (the cam-stop *overrun* enforcement is the v1.1 hook, intentionally deferred). **(VERIFY: per-cam trip-edge polarity for all six cams on our chassis.)**

---

### 3.7 The 3-Second Time Delay (pin settle), gated by GP

After the sweep reaches its 66° guard (**SB**), the controller **waits 3 seconds before lowering the table.** This is the **pin-settle delay**: it lets pins that are still rocking or sliding on the deck come to rest, so the gripper read at 260° (**TA2**) reflects the true standing-pin pattern and the table doesn't try to grip a moving pin.

Two conditions must both hold for the table to descend:

1. **The 3-second timer has elapsed** (`TIME_DELAY_S = 3.0` in `cycle_control_8270.py`).
2. **GP (gripper-protect) is closed.** GP is a machine permissive that confirms the grippers are in the safe state to descend. If GP is open, the table does **not** drop even after 3 s.

This is implemented in the FSM's `poll()` loop while in state `GUARD_DELAY`:

```python
if self.io.gp_closed() and (now - self._t_state) >= TIME_DELAY_S:
    self._safe_table(True)         # table descends
    self._enter(State.TABLE_DETECT)
```

The delay memory is **reset at table 185°** (**TA1**) on the way back to zero (`cam_TA1_delayreset()` — a bookkeeping reset with no motor change), so each cycle starts the 3-second window clean.

> GP is wired as a **slow input** on the MCP23017 IN-A bank (it gates a 3-second window, so it does not need RP2040 edge speed). See §3.7's I/O map and Section 5 §5.2.

---

### 3.8 Safety Behaviors the Controller Must Preserve

These are machine-level safety behaviors documented in `SYSTEM_REFERENCE` §5 and OEM-confirmed in the audit. The Pi controller **reproduces or preserves every one of them**; several are deliberately kept in **hardware** so they survive a dead or misbehaving Pi. Full electrical implementation is in Section 10 *(PCB Rev-B Safety Rail)*; the *behavior* is described here because it is part of the machine's sequence of operation.

| Behavior | What it does | Where it lives |
|---|---|---|
| **Stop switch + C.I.S.** (Chassis Interlock Switch) | OEM documentation says they are in **parallel** and either one cuts the **rear-panel master circuit breaker** → all control dead. Pilot lanes 21/22 instead have no C.I.S. device or wiring; their installed chain is Stop-only. | Hardware (external chain). Before motion on lanes 21/22, demand Stop and verify master/control-power removal; record C.I.S. as **N/A — device absent**; inspect/ask the mechanic about any other automatic pit-entry interlock. If none exists, close the new-interlock-versus-explicit-safety-decision gate. J_SAFE3-4 stays OPEN/no-arm until a separate approved external control-power proof interface is installed. |
| **TB/SC table-sweep collision interlock** | Powered 2026-07-07: TB and SC are **parallel closed-when-safe contacts** in the OEM 24 VAC S/T coil ladder. Either pressed lever permits a coil; **both levers BACK/open kill both S and T coils.** The MP's manual Sweep/Table overrides bypass *all* logic **except BE and this interlock**, making it the irreducible hardware safety. | **Candidate C primary guard:** keep the OEM ladder in each board-commanded S/T coil path, close J_SAFE1-2 only with the controlled jumper, and prove both coil drops per lane at G3. `io.interlock_ok()` is default-off, secondary, and unvalidated because TB has no independent observation. |
| **Regenerative motor braking** | De-energized **N.C.** relay contacts switch capacitors across the motor main winding to brake the sweep/table quickly at each stop. | Hardware (the existing S/T contactor contact sets + caps). The PCB must not replace this. |
| **MP "Power-Down" rule** | After **any 115 VAC loss** while in "Bowl," the machine performs **no motion on power restore** until the operator deliberately commands **"First Ball Zero"** (a Manual Intervention). | Reproduced by the Pi: the FSM comes up in state **`MANUAL_INTERVENTION`** and drives nothing until `first_ball_zero()` is called (`power_restore()` → `MANUAL_INTERVENTION`). This is the controller-level sibling of the NE555 watchdog: **fail-safe-off on restore, require operator zero.** |
| **Welded-contact limitation** | The safety rail can only **de-energize** relay coils; it **cannot open a contact that has welded closed.** The master breaker / installed Stop chain is therefore the pilot's **final physical stop**; a real C.I.S. or other upstream pit interlock adds protection only where physically present and demand-proven. | Hardware (breaker is final). Drives relay rating + suppression requirements in Section 10 §4.5. |

> **The interlock is electrical truth, not a software hint.** Powered testing resolved the SS + Omega-Tek implementation: there is no isolatable dry TB/SC pair for `J_SAFETY`; C2A-U is a live-ladder region and TB has no standalone cavity. Candidate C therefore puts the documented jumper on J_SAFE1-2 and preserves the OEM parallel-safe contacts inside the S/T coil circuits. This is valid only when the board's S/T contacts are inserted without bypassing that ladder, which the mandatory per-lane G3 S-and-T coil-drop test proves. Firmware observation is default-off, secondary, and unvalidated.

---

### 3.9 Machine I/O the Controller Touches (function-level summary)

This is the *functional* I/O list the sequence above depends on. **Exact connector cavities (C1/C2A pins) are deliberately not bound in PCB copper** — they differ between the OEM factory chassis, our SS + Omega-Tek retrofit, and the Active-98 chassis, so an adapter harness resolves them per chassis at cutover (see the OEM-vs-bench reconciliation in `phase8_oem_doc_audit_2026-06-02.md` and Section 14 *(Connector & Harness Map)*). The table below gives the function, the controller bus it lands on, and the named board channel. Pin/part anchors come from `scripts/generate_kicad_netlist_revB.py`, `firmware/rp2040/config.h`, and `lane_node/controller_io.py`.

#### Inputs the controller reads

| Signal | Meaning in the sequence | Bus | Channel anchor |
|---|---|---|---|
| **SS** (cushion start) / **DIELL-L**, **DIELL-R** | Ball delivered = cycle trigger. On our lanes the cushion SS is replaced by the **DIELL** optical ball beams (two beams, coalesced into one "ball" event). | **RP2040 fast** | `DIELL_L = GP12`, `DIELL_R = GP13` (Pico pins 16, 17) |
| **SA, SB, SC** (sweep cams) | Sweep position (§3.6). | **RP2040 fast** | `SA = GP6`, `SB = GP7`, `SC = GP8` |
| **TA1, TA2, TB** (table cams) | Table position + the strike/run-through decision + interlock window (§3.6). | **RP2040 fast** | `TA1 = GP9`, `TA2 = GP10`, `TB = GP11` |
| **GS1–GS10** (gripper switches) | The 10-bit **standing-pin mask**, latched at TA2/260°. | **MCP23017 IN-A** | `IN_A_MAP["GS1".."GS10"]` = GPA0..GPA7, GPB0, GPB1 (MCP pins 21–28, 1, 2) |
| **GP** (gripper-protect) | Gates the 3-second delay → table descent (§3.7). | **MCP23017 IN-A** | `GP` = MCP IN-A pin 3 (GPA2) |
| **BS** (bin switch, #9 bin) | "10th pin delivered" → fires SP on fresh-rack cycles (§3.4/3.5). | **MCP23017 IN-A** | `BS` = MCP IN-A pin 5 (GPA4) |
| **OS** (off-spot) | Off-spot detection. | **MCP23017 IN-A** | `OS` = MCP IN-A pin 4 (GPA3) |
| **PBZ** (first-ball / zero / manual-intervention pushbutton) | Operator "First Ball Zero" → clears `MANUAL_INTERVENTION`; toggles 1st/2nd ball when already running. | **MCP23017 IN-A** | `PBZ` = MCP IN-A pin 6 (GPA5) |
| **PBC** (cycle pushbutton) | Manual cycle. | **MCP23017 IN-A** | `PBC` = MCP IN-A pin 7 (GPA6) |
| **Foul** (Radaray) | Foul detected (§3.5). | **MCP23017 IN-A** | `Foul` = MCP IN-A pin 8 (GPA7) |
| **10th-frame; manual T / S / SWS / SWSR; spares** | 10th-frame indication and the manual table/sweep/sweep-switch/sweep-reverse inputs, plus spares. | **MCP23017 IN-B** | `TENTH, MAN_T, MAN_S, MAN_SWS, MAN_SWSR, AUX1–3` (MCP IN-B pins 21–28) — allocated, not yet read by the current FSM |

> **Polarity (all inputs).** Every input is **opto-isolated and active-LOW at the controller**: a closed machine contact pulls the GPIO/MCP pin **LOW**; idle is **HIGH** through the external `Rpu_*`. This is `INPUT_ACTIVE_LOW = True` in `controller_io.py` and the active-low handling in `firmware/rp2040/main.c` (`gpio_get(...) == 0` = asserted). The front end is a **PC817B** optocoupler per channel with a **2.2k** field series resistor. Rev-B used a 10 kΩ logic pull-up; the current Rev-D board uses **47 kΩ**, with RP2040 and MCP23017 internal pulls disabled. The standing-pin convention: a **standing** pin sets its mask bit (`read_grippers()` returns bit *n−1* set for GS*n* standing); a mask of **0 = no pins = strike**.

#### Outputs the controller drives

| Signal | Meaning in the sequence | Coil / driver | Channel anchor |
|---|---|---|---|
| **S** (sweep relay) | Run/stop the **sweep motor** (intermittent). | Relay coil | `OUT_A_MAP["S"]` = MCP OUT-A GPA0 (pin 21) → relay **K1** |
| **T** (table relay) | Run/stop the **table motor** (intermittent). | Relay coil | `OUT_A_MAP["T"]` = GPA1 (pin 22) → **K2** |
| **SP** (spot solenoid) | Fire the **fresh-rack spotting** revolution (after BS, on 2nd/strike/foul). | Relay coil | `OUT_A_MAP["SP"]` = GPA2 (pin 23) → **K3** |
| **BE** (back-end) | Energize the **continuous** back-end motor group (Ball Lift + Carpet + Elevator + Distributor). | Relay coil | `OUT_A_MAP["BE"]` = GPA3 (pin 24) → **K4** *(future; not driven by the current FSM)* |
| **M** (master) | Master / control command. | Relay coil | `OUT_A_MAP["M"]` = GPA4 (pin 25) → **K5** *(future)* |
| **M2** (sweep reverse) | Reverse the sweep (optional APS strike/7-10 enhancement). | Relay coil | `OUT_A_MAP["M2"]` = GPA5 (pin 26) → **K6** |
| **M1** (ball return) | Ball-return command. | Relay coil | `OUT_A_MAP["M1"]` = GPA6 (pin 27) → **K7 DNP** *(not bench-confirmed on our chassis + FSM doesn't drive it; footprint present but **DNP**)* |
| **first_ball / second_ball / strike / foul** | The mask **status lamps** (which ball; strike; foul). | Logic LED driver | `OUT_A_MAP` GPA7, GPB0, GPB1, GPB2 (gen `L_FIRST/L_SECOND/L_STRIKE/L_FOUL`, pins 28, 1, 2, 3) → 2N7002 LED drivers |
| **Pin lamps 1–10** | The 10-pin **pindicator** mask, latched at 260°. | (camera-supplied in Rev-B) | Optional OUT-B bank, **omitted in baseline** — camera scoring (Track A) supplies pin state; `enable_pin_lamps=False`. |
| **KX relay** | Historically gated pin data to the old scorer. | — | **Omitted** — replaced by camera scoring. |

> **Output ordering caution.** In `OUT_A_MAP`, **M2 precedes M1** (GPA5 then GPA6) — this matches the netlist generator's `OUTPUT_PINS` order and was a deliberate fix; an earlier draft had M1/M2 (and BS/OS, and strike/foul) swapped. The `controller_io.py` `__main__` self-test re-derives `OUT_A_MAP`/`IN_A_MAP` from `generate_kicad_netlist_revB.py` and **fails on drift**, so software names can never silently diverge from the routed board.

#### Lamp / status-LED voltage — a documented conflict

The **status lamps** (1st-ball/2nd-ball/strike/foul) and the **pin lamps** are described in `SYSTEM_REFERENCE` §4 as **12 VDC** (pin lamps 12 VDC via D1–D10; status lamps 12 VDC at mask positions PM-E24/E25/E26/E27; neon mask elements ~125 VAC/−160 VDC). However, the **Rev-B PCB decision** (`phase8b_pcb_revB_spec.md` §3.3) is to **abandon the machine mask-lamp supply entirely** and instead install **our own LEDs in the mask housings**, driven from **VCC_5V** logic power through **2N7002** low-side FETs with **330R** current-limit resistors (`Rled_*`). That spec note also cites the machine's measured mask-lamp supply as **15 VDC**, which **disagrees with the 12 VDC** in `SYSTEM_REFERENCE` §4.

**(VERIFY: machine mask-lamp supply voltage — 12 VDC (`SYSTEM_REFERENCE` §4) vs. 15 VDC (`phase8b_pcb_revB_spec.md` §3.3). The discrepancy is academic for Rev-B status lamps (the board drives its own 5 V LEDs and does not use the machine supply at all), but the original-machine value should be confirmed at-machine and reconciled before this manual is final, since it also bears on the 12 VDC pin-lamp / KX path if camera scoring is ever abandoned.)** The **330R** status-LED current-limit value is itself flagged "TBD in the scaffold" in the PCB spec (§11 item 5) — **(VERIFY: final status-LED current-limit resistor value for bowling-center brightness.)**

---

### 3.10 What This Means for the Build (cross-references)

- The **cam angles in §3.6** are the contract the **RP2040 firmware** detects edges for and the **`CycleController` FSM** acts on. See Section 15 *(RP2040 Firmware)* and `cycle_control_8270.py`.
- The **motor running pattern in §3.1** (BE continuous; S/T intermittent; motor current on the machine contactors) is the rule the **PCB output stage** must not violate. See Section 5 *(PCB Rev-B)* §3.
- The **safety behaviors in §3.8** remain hardware protections independent of the Pi. The on-board rail enforces its implemented gates; the Candidate-C TB/SC guard remains separately in the OEM S/T coil ladder. See Section 10 §4.
- The **function-named I/O in §3.9** is mapped to physical C1/C2A cavities **only by the adapter harness at cutover** — never in copper. See Section 14 *(Connector & Harness Map)* and the OEM-vs-bench cavity reconciliation.

> **At-machine status carried into the cutover runbook:** TB/SC topology/polarity is resolved by the powered 2026-07-07 test and Candidate C, but its **per-lane output insertion** remains a G3 proof obligation. Still open are the remaining per-cam cavity/edge captures, M2 sweep-reverse Expander path, SP timing, foul semantics, and other explicitly marked harness landings. None changes the sequence; each must be closed before its affected live function is released.
