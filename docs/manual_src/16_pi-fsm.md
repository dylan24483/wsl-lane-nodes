## 16. Pi Software: The Cycle-Control FSM

This section documents the software brain that replaces the AMF 82-70 controller logic: the **`CycleController` finite-state machine** in `lane_node/cycle_control_8270.py`. It is the controller-level sibling of the hardware described in Section 9 (Relay Outputs), Section 10 (Watchdog & Safety Rail), and Section 12 (Channel Maps), and it consumes the fast cam/ball events produced by the RP2040 firmware (Section 15). One `CycleController` instance runs per physical lane.

Everything here is grounded in two source files:

- `lane_node/cycle_control_8270.py` — the FSM itself (the code).
- `docs/phase8_8270_SYSTEM_REFERENCE.md` — the reverse-engineered AMF 82-70 sequence of operation, cam timing, I/O, and safety model that the FSM reproduces. References below of the form "(SYSTEM_REFERENCE §N)" point into that document.

> **Status / safety gate.** As written, `cycle_control_8270.py` is a **spec-derived DRAFT (R1)**. The file header states explicitly that it is NOT production until: the exact C1/C2A machine-side pins are confirmed against the service-manual schematic and the spare machine; the hardware safety chain is in place (TB/SC interlock, Stop/CIS breaker chain, NE555 watchdog, E-stop); and every cycle plus every fault case is validated off-live. Points in the code that still need confirming against the schematic or the real machine are flagged `# CONFIRM`. This manual reproduces those flags as **(VERIFY: …)** so a service engineer never mistakes a draft assumption for a measured fact. Do not let this FSM drive a live machine until the bench bring-up gate in Section 13 (Layout & Manufacturing) / the Rev-B spec §12.9 is cleared.

---

### 16.1 Why this is an event-driven FSM, not a pulse counter

The 82-70 has **no single "one pulse per cycle" trigger**. The file header records that the earlier `cycle_control.py` "SS-pulse" model is **VOID** for exactly this reason. Instead, per the AMF service manual (SYSTEM_REFERENCE §0, §2), the controller **drives the sweep and table motors itself** and **reads cam switches mounted on the motor shafts** for position, de-energizing each motor when its cam reports the target degree. AMF's own MP microprocessor chassis did the same job the same way — it directly replaced the 5-board solid-state chassis using the *same machine inputs and outputs*, changing only the logic medium (SYSTEM_REFERENCE §0, §6). The Pi controller is a modern MP chassis: read switches → run the sequence → drive relay coils and lamps.

Consequently the FSM is **event-driven**:

- **Cam edge transitions** (SA, SB, SC, TA1, TA2, TB) drive most state changes.
- **Discrete inputs** drive the rest: SS/DIELL ball detect (cycle trigger), grippers GS1–GS10 (pin read), GP gripper-protect (gates the settle delay), BS bin switch (gates fresh-rack spotting), Foul.
- A **3-second settle timer** and an **8-second per-motion safety backstop** are time-based, evaluated in `poll()`.

Each state **sets motor / solenoid / lamp outputs on entry**; each cam-event handler maps directly to one step of the SYSTEM_REFERENCE §2 sequence of operation.

---

### 16.2 The `io` interface contract (hardware abstraction)

The FSM performs **zero direct hardware access**. Every input and output goes through an injected `io` object, which is why the same FSM is fully bench-testable with a simulator and runs unchanged on real hardware. The two concrete implementations live in `lane_node/controller_io.py`:

- **`MachineIO`** — real hardware: the three MCP23017 I²C expanders (relays + status LEDs + slow inputs), the RP2040 co-processor (fast cam/ball events + the SC/TB interlock echo + RUN/STOP run-tracking), and the NE555 watchdog kick. (Pinouts and part numbers: see Section 9 and Section 12.)
- **`RecordingIO`** — a no-hardware fake that records every output call and serves scripted inputs, used to bench-test the FSM off-Pi.

The contract the FSM depends on (verbatim from the `CycleController` docstring):

| `io` method | Direction | Meaning |
|---|---|---|
| `io.set_sweep(on: bool)` | OUT | Energize / de-energize the **SWEEP** motor relay (`S`) |
| `io.set_table(on: bool)` | OUT | Energize / de-energize the **TABLE** motor relay (`T`) |
| `io.set_spot(on: bool)` | OUT | Energize the **SPOT** solenoid relay (`SP`) |
| `io.set_pin_lamps(mask: int)` | OUT | Drive the 10 mask pin lamps, or hand the mask to the camera / scoring Track A |
| `io.set_light(name, on)` | OUT | Drive a status lamp: `'first_ball'` \| `'second_ball'` \| `'strike'` \| `'foul'` |
| `io.read_grippers() -> int` | IN | 10-bit standing-pin mask from GS1–GS10 (**0 = no pins = strike**) |
| `io.gp_closed() -> bool` | IN | Gripper-protect closed — **enables** the time delay |
| `io.bs_closed() -> bool` | IN | Bin switch: 10th pin delivered (gates fresh-rack spotting) |
| `io.interlock_ok() -> bool` | IN | TB/SC collision interlock — **SECONDARY software guard** |
| `io.watchdog_kick()` | OUT | Pet the NE555 hardware watchdog |
| `io.now() -> float` | IN | Monotonic seconds (injectable for tests) |
| `io.log(msg)` | — | Diagnostic log line |

> **Critical safety note on `interlock_ok()`.** This is the **software echo** of the TB/SC interlock, not the interlock itself. The authoritative interlock is the hardware TB+SC NC loop in the relay-enable rail (Section 10; SYSTEM_REFERENCE §5). `MachineIO.interlock_ok()` returns the RP2040's SC/TB collision state when the RP2040 link is wired, and otherwise **defaults to `True`** specifically so the software echo can never *enable* motion that the hardware would block — it can only decline to command into a known-bad state. The hardware rail is what actually prevents a collision.

The mapping from these logical output names to physical relay/lamp bits is defined in `controller_io.py` (`OUT_A_MAP`) and is **locked to the PCB netlist generator** `scripts/generate_kicad_netlist_revB.py` (`OUTPUT_PINS`) — a regression test in `controller_io.py.__main__` re-derives the map from the generator and fails on any drift. The full bit map is in Section 12 (Channel Maps); the relevant motor/solenoid/lamp outputs are `S`, `T`, `SP`, and the four status lamps `first_ball` / `second_ball` / `strike` / `foul`. The fast cam/ball inputs that feed the cam-event handlers arrive from the RP2040 on **GP6–GP13** (`RP2040_OK` = GP2, UART = GP0/GP1); see Section 15.

---

### 16.3 The states

The `State` enum defines ten states:

| State (enum value) | Meaning / what is energized |
|---|---|
| `POWER_OFF` (`power_off`) | Initial state at object construction; nothing driven. |
| `MANUAL_INTERVENTION` (`manual_intervention`) | Power has been (re)applied. **Drives NOTHING** until the operator presses First-Ball-Zero. Implements the MP "Power-Down" rule (SYSTEM_REFERENCE §5). |
| `READY` (`ready`) | Machine at zero, awaiting a ball (SS/DIELL). No motors running. |
| `SWEEP_TO_GUARD` (`sweep_to_guard`) | SWEEP motor running toward the 66° guard position. |
| `GUARD_DELAY` (`guard_delay`) | Sweep stopped at guard; running the **3-second pin-settle delay** (gated by GP closed). No motors running. |
| `TABLE_DETECT` (`table_detect`) | TABLE motor running down; grippers reading standing pins. |
| `RUNTHROUGH` (`runthrough`) | SWEEP run-through to 270°. |
| `SPOTTING` (`spotting`) | **Fresh-rack cycles only:** SP energized, table doing its spotting revolution (entered after BS = bin full). |
| `TABLE_FINISH` (`table_finish`) | Table finishing through TA1; respot of held pins, or awaiting BS to start fresh-rack spotting; sweep returning. |
| `FAULT` (`fault`) | A motion exceeded `MAX_MOTION_S`. All motors commanded OFF; FSM halted in fault. |

Two supporting enums track the cycle:

- `Ball`: `FIRST` (1) / `SECOND` (2) — which ball of the frame.
- `Cycle`: `FIRST_BALL` (pins left standing on the 1st ball) / `SECOND_BALL` / `STRIKE` (no pins on 1st ball) / `FOUL` — what kind of cycle is in progress, which determines the fresh-rack-vs-respot decision (§16.6).

Instance fields: `state`, `ball`, `cycle`, `pins` (the latched 10-bit standing-pin mask for this cycle), and `_t_state` (the monotonic time the current state was entered, used for both the settle delay and the motion backstop).

---

### 16.4 Cam timing constants (the FSM triggers)

These module-level constants come from SYSTEM_REFERENCE §3 (the authoritative cam table) and are the angular trip points the cam-event handlers correspond to. They are documentation/labels — the FSM acts on the *event* of a cam edge arriving, not on a measured angle (angle measurement is a deferred field item; see §16.8).

| Constant | Value (degrees) | Cam | Role (SYSTEM_REFERENCE §3) |
|---|---|---|---|
| `SB_GUARD` | 66 | SB (sweep) | Sweep stops at first guard |
| `SB_SPOT` | 186 | SB (sweep) | Sweep initiates table spotting |
| `SA_RUNTHROUGH` | 270 | SA (sweep) | Sweep stops after run-through |
| `SA_ZERO` | 360 | SA (sweep) | Sweep stops at zero |
| `SC_LO` / `SC_HI` | 86 / 243 | SC (sweep) | Sweep-under-table **interlock** window |
| `TA1_DELAYRESET` | 185 | TA1 (table) | Table resets the time delay |
| `TA1_ZERO` | 355 | TA1 (table) | Table stops at zero |
| `TA2_RUNTHROUGH` | 260 | TA2 (table) | Table initiates sweep run-through; pin-lamp latch; ball/strike decision |
| `TB_LO` / `TB_HI` | 105 / 255 | TB (table) | Table-sweep interference **interlock** window |

Two timing constants govern the time-based behavior:

| Constant | Value | Meaning |
|---|---|---|
| `TIME_DELAY_S` | `3.0` s | Pin-settle delay at the guard, gated by GP (gripper-protect) closed. |
| `MAX_MOTION_S` | `8.0` s | Safety backstop per motor motion. **FIELD:** to be set = measured time + margin. Matches the RP2040 firmware's `MAX_MOTION_MS = 8000` (Section 15). |

---

### 16.5 Cam-event handlers → sequence of operation

Each public method on `CycleController` corresponds to one step in the SYSTEM_REFERENCE §2 sequence. The daemon (or, in tests, the simulator) calls these when the corresponding cam edge or discrete event arrives. The table below maps every handler to its trigger, its guard condition, and its effect.

| Handler / event | Fires when | Acts only if state is… | Effect (outputs + transition) |
|---|---|---|---|
| `power_restore()` | 115 VAC (re)applied | any | All motors OFF; → `MANUAL_INTERVENTION`. (SYSTEM_REFERENCE §5 Power-Down) |
| `first_ball_zero()` | Operator presses First-Ball-Zero (PBZ) | `MANUAL_INTERVENTION` | Set `ball=FIRST`; `first_ball` lamp ON; → `READY`. |
| `first_ball_zero()` | Operator presses PBZ again | `READY` | Toggle 1st/2nd-ball memory (manual intervention; §5). |
| `on_ball()` | SS / DIELL beam break (ball thrown) | `READY` **and** `interlock_ok()` | Choose `Cycle` (FIRST_BALL or SECOND_BALL); energize SWEEP toward 66°; → `SWEEP_TO_GUARD`. Ignored otherwise. |
| `on_foul()` | Foul detector (Radaray) fires | any | `foul` lamp ON; if 1st ball, set `cycle=FOUL`. |
| `cam_SB_guard()` | Sweep reaches **66°** (SB) | `SWEEP_TO_GUARD` | SWEEP OFF; → `GUARD_DELAY` (starts the 3 s settle). |
| `cam_TA2_runthrough()` | Table reaches **260°** (TA2) | `TABLE_DETECT` | **Latch** `pins = read_grippers()`; drive pin lamps; if FIRST_BALL with `pins==0` reclassify as STRIKE (strike lamp ON, first-ball lamp OFF); energize SWEEP run-through; → `RUNTHROUGH`. |
| `cam_SA_runthrough()` | Sweep reaches **270°** (SA) | `RUNTHROUGH` | SWEEP OFF; → `TABLE_FINISH`. (Fresh-rack cycles will then wait for BS; respot completes at TA1 zero.) |
| `cam_TA1_delayreset()` | Table passes **185°** (TA1) | — | Resets the time-delay memory (SYSTEM_REFERENCE §2). **No motor change.** |
| `cam_TA1_zero()` | Table reaches **355°/zero** (TA1) | `SPOTTING` | SP OFF; TABLE OFF; `_finish_cycle()`. |
| `cam_TA1_zero()` | (same) | `TABLE_FINISH` | TABLE OFF; `_finish_cycle()`. |
| `cam_SA_zero()` | Sweep reaches **360°/zero** (SA) | `TABLE_FINISH` or `SPOTTING` | SWEEP OFF. |
| `bin_full()` | BS closes — 10th pin delivered to bin | `TABLE_FINISH` **and** fresh-rack **and** `interlock_ok()` | Energize SP; → `SPOTTING`. (No-op on a 1st-ball respot; blocked if interlock open.) |

Internal helpers:

- **`_finish_cycle()`** — end-of-cycle bookkeeping (SYSTEM_REFERENCE §2): flips the ball memory (FIRST_BALL/FOUL → SECOND ball; SECOND_BALL/STRIKE → FIRST ball), sets the 1st/2nd-ball lamps accordingly, clears the strike and foul lamps, clears `cycle`, and returns to `READY`.
- **`_toggle_ball()`** — flips `ball` and the two ball lamps (used by the manual PBZ override in `READY`).
- **`_safe_sweep()` / `_safe_table()`** — the in-FSM interlock gate (§16.7).
- **`_all_motors_off()`** — drives `S`, `T`, `SP` all OFF.

A complete first-ball-with-pins cycle therefore walks: `READY` → (`on_ball`) `SWEEP_TO_GUARD` → (`cam_SB_guard`) `GUARD_DELAY` → (poll, after 3 s + GP) `TABLE_DETECT` → (`cam_TA2_runthrough`) `RUNTHROUGH` → (`cam_SA_runthrough`) `TABLE_FINISH` → (`cam_TA1_zero`) `READY` (now on 2nd ball). A strike or 2nd-ball (fresh-rack) cycle inserts the `SPOTTING` state between `TABLE_FINISH` and `READY` once `bin_full()` fires.

---

### 16.6 Fresh-rack vs. respot logic

The single most important branching decision in the FSM is **whether the cycle spots a brand-new full rack of pins (energizing the SPOT solenoid `SP`) or merely respots the pins that were already standing (no `SP`)**. This is decided by `_needs_fresh_rack()`:

| `Cycle` | `_needs_fresh_rack()` | Behavior |
|---|---|---|
| `SECOND_BALL` | **True** | Fresh rack. After run-through, wait for **BS** (bin full); BS → energize `SP` → table spotting revolution. (SYSTEM_REFERENCE §2 SECOND BALL.) |
| `STRIKE` | **True** | Fresh rack, same SP path as 2nd ball. (SYSTEM_REFERENCE §2 STRIKE.) |
| `FOUL` | **True** *(provisional)* | Treated as fresh-rack here. **(VERIFY: foul respot semantics — the code treats FOUL as fresh-rack as a placeholder; per SYSTEM_REFERENCE §2 a foul flips to 2nd ball after a table spotting revolution, but exact foul respot behavior is to be confirmed on the bench before live.)** |
| `FIRST_BALL` (pins left) | **False** | **Respot** the held standing pins — no `SP`, no BS gating. Completes directly at TA1 zero. |

Mechanically this works because of *where* the standing-pin mask is latched and *what* gates the SP path:

1. At **TA2 = 260°** (`cam_TA2_runthrough`), the grippers are read and `pins` is latched (SYSTEM_REFERENCE §2: pin lamps latch at 260°). If this is a first ball and `pins == 0`, the cycle is reclassified `STRIKE` on the spot.
2. After the sweep run-through stops at **SA = 270°** (`cam_SA_runthrough`), the FSM enters `TABLE_FINISH`. For a respot (`FIRST_BALL`), there is no new rack to deliver, so the cycle simply completes when the table returns to **TA1 zero**.
3. For a fresh rack (`SECOND_BALL` / `STRIKE` / `FOUL`), the new rack of 10 pins must first arrive in the bin. The **bin switch BS** closing (`bin_full()`) is the gate: it energizes `SP` and enters `SPOTTING`. The spotting revolution then returns the table to **TA1 zero**, at which point `SP` is released and the cycle completes.

> **(VERIFY: SP de-energize timing.)** `cam_TA1_zero()` releases `SP` when the table reaches zero out of `SPOTTING`. The code marks this `# CONFIRM` — the exact SP de-energize timing vs. the cam, and whether SP is a pulse or held continuous through the spotting revolution, must be confirmed on the bench. (SYSTEM_REFERENCE §2/§4 note the SP spot relay; the as-built SP path on our chassis is harness-resolved, see Section 14.)

> **(VERIFY: BS / SP machine-side pins.)** The FSM source annotates the BS input as "BS → C2A-112cc" and the SP output as "SP → C1-35U/36Y", and various cam handlers annotate C2A cavities (e.g. "cam SA → C2A-31N", "cam TA1 → C2A-34N"). **These C1/C2A cavity bindings are explicitly unverified.** The Rev-B PCB is deliberately function-named precisely because the OEM wire tables and our bench (SS chassis + Omega-Tek retrofit) disagree on cavity routing; the adapter harness resolves cavities at cutover (see Section 14, Machine Interface, and the Rev-B spec §3.2/§7). Do **not** treat any C1/C2A pin in the FSM comments as a wiring instruction.

---

### 16.7 In-FSM safety

The FSM contains four software safety mechanisms. **Every one of them has an independent hardware backstop** — the software guards are echoes and conveniences, never the sole protection. (Hardware safety: Section 10, Watchdog & Safety Rail; SYSTEM_REFERENCE §5.)

**1. Interlock gate on every motor energize.** Both `_safe_sweep(True)` and `_safe_table(True)` first check `io.interlock_ok()`; if the interlock is open, the energize is **refused and logged**, not performed. `bin_full()` likewise refuses to energize `SP` if the interlock is open, and `on_ball()` refuses to start a cycle at all if the interlock is open. The authoritative interlock is the hardware **TB + SC** NC loop wired in series with the relay-enable rail (Section 10); this software gate simply avoids commanding into a state the hardware would block.

**2. Power-down rule → require First-Ball-Zero.** `power_restore()` puts the FSM in `MANUAL_INTERVENTION` and drives **nothing**. The machine will not move until the operator deliberately presses **First-Ball-Zero** (`first_ball_zero()`), which is the only transition out of `MANUAL_INTERVENTION`. This reproduces the AMF MP "Power-Down" feature (SYSTEM_REFERENCE §5): after any 115 VAC loss while bowling, there is **no machine motion on power restore** until a deliberate operator action. It is the controller-level sibling of the NE555 watchdog (which drops the rail if the Pi dies).

**3. `MAX_MOTION_S` fault.** `poll()` enforces an **8-second backstop on every motion state** (`SWEEP_TO_GUARD`, `TABLE_DETECT`, `RUNTHROUGH`, `SPOTTING`, `TABLE_FINISH`). If a motion never reports complete within `MAX_MOTION_S` of entering the state, the FSM **commands all motors OFF and latches `FAULT`**. This protects against a missed cam edge that would otherwise leave a motor energized indefinitely. The RP2040 firmware runs an independent, UART-independent copy of this same backstop (`MAX_MOTION_MS`, Section 15), so a stuck motor is caught even if the Pi-side FSM itself hangs. `GUARD_DELAY` is intentionally excluded from the backstop because no motor is energized during the settle.

**4. Watchdog kick every poll.** `poll()` calls `io.watchdog_kick()` on **every** invocation (it is the first line of `poll()`). If the FSM stops polling — because the process died, hung, or was killed — the NE555 hardware watchdog stops being petted and **drops all relays** (Section 10). The recommended poll cadence is ~20–50 Hz (`poll()` docstring).

> **(VERIFY: `MAX_MOTION_S` field value.)** The `8.0` s value is a draft backstop. The FSM comment instructs setting it to the **measured** longest motion plus margin during bench validation. Confirm the real sweep/table/spot motion durations on the spare machine and set both `MAX_MOTION_S` (Python) and `MAX_MOTION_MS` (firmware) accordingly before live.

---

### 16.8 State-transition table

The complete transition set. "Guard" lists any precondition; if the guard fails the event is ignored (logged) and the state is unchanged. Outputs shown are those changed on the transition.

| From state | Event | Guard | Outputs changed | To state |
|---|---|---|---|---|
| any | `power_restore()` | — | S/T/SP → OFF | `MANUAL_INTERVENTION` |
| `MANUAL_INTERVENTION` | `first_ball_zero()` | (at zero — daemon-checked) | `first_ball` lamp ON | `READY` |
| `READY` | `first_ball_zero()` | — | toggle ball lamps | `READY` |
| `READY` | `on_ball()` | `interlock_ok()` | SWEEP ON | `SWEEP_TO_GUARD` |
| `READY` | `on_ball()` | interlock open → **ignored** | — | `READY` |
| `SWEEP_TO_GUARD` | `cam_SB_guard()` | — | SWEEP OFF | `GUARD_DELAY` |
| `GUARD_DELAY` | `poll()` | `gp_closed()` **and** elapsed ≥ `TIME_DELAY_S` | TABLE ON | `TABLE_DETECT` |
| `TABLE_DETECT` | `cam_TA2_runthrough()` | — | latch `pins`; pin lamps; (strike → strike lamp); SWEEP ON | `RUNTHROUGH` |
| `RUNTHROUGH` | `cam_SA_runthrough()` | — | SWEEP OFF | `TABLE_FINISH` |
| `TABLE_FINISH` | `bin_full()` | fresh-rack **and** `interlock_ok()` | SP ON | `SPOTTING` |
| `TABLE_FINISH` | `bin_full()` | not fresh-rack → **no-op** | — | `TABLE_FINISH` |
| `TABLE_FINISH` | `cam_TA1_zero()` | — | TABLE OFF; `_finish_cycle()` | `READY` |
| `SPOTTING` | `cam_TA1_zero()` | — | SP OFF; TABLE OFF; `_finish_cycle()` | `READY` |
| `TABLE_FINISH` / `SPOTTING` | `cam_SA_zero()` | — | SWEEP OFF | (unchanged) |
| `TABLE_FINISH` / `SPOTTING` | `cam_TA1_delayreset()` | — | none (resets delay memory) | (unchanged) |
| `SWEEP_TO_GUARD` / `TABLE_DETECT` / `RUNTHROUGH` / `SPOTTING` / `TABLE_FINISH` | `poll()` | elapsed > `MAX_MOTION_S` | **all motors OFF** | `FAULT` |
| `FAULT` | — | (no automatic exit; recovery is operator/daemon-driven) | — | `FAULT` |

> **`_finish_cycle()` ball-memory rule** (applied on every transition to `READY` via cycle completion): FIRST_BALL or FOUL → next is **2nd ball**; SECOND_BALL or STRIKE → next is **1st ball**. Strike and foul lamps are cleared; `cycle` is cleared.

ASCII state diagram (happy-path cycle; the `FAULT` and `MANUAL_INTERVENTION` edges apply broadly and are summarized in the table above):

```
                power_restore()                 first_ball_zero()
  (any) ───────────────────────▶ MANUAL_INTERVENTION ───────────────▶ READY ◀────────────┐
                                                                         │                 │
                                                          on_ball() [interlock_ok]         │
                                                                         ▼                 │
                                                                  SWEEP_TO_GUARD           │
                                                              cam_SB_guard() │             │
                                                                             ▼             │
                                                                       GUARD_DELAY         │
                                              poll() [GP closed, ≥3 s]      │              │
                                                                            ▼              │
                                                                      TABLE_DETECT         │
                                                       cam_TA2_runthrough()  │  (latch pins;│
                                                                             ▼   strike?)   │
                                                                        RUNTHROUGH          │
                                                          cam_SA_runthrough() │             │
                                                                             ▼              │
                                                                       TABLE_FINISH         │
                                                       ┌─────────────────────┴───────────┐ │
                                          fresh rack:  │ bin_full() [BS, interlock]       │ │ respot (1st ball, pins left):
                                          SP ON        ▼                                  │ │ cam_TA1_zero() ─▶ _finish_cycle()
                                                   SPOTTING                               │ │
                                          cam_TA1_zero() │ SP OFF, _finish_cycle()        │ │
                                                         └────────────────────────────────┘─┘
   any motion state, poll() elapsed > MAX_MOTION_S  ───────────────────────────▶  FAULT  (all motors OFF)
```

---

### 16.9 Bench simulator (validation harness)

`cycle_control_8270.py` ships with a self-contained bench simulator under `if __name__ == "__main__":`. Running `python cycle_control_8270.py` (exit code 0 = all assertions pass) drives a fake machine (`SimIO`) that emits cam events on a timeline as the motors "run," and injects `bin_full()` on fresh-rack cycles so the SP spotting path executes. It asserts the full state flow plus the three behaviors that matter most:

- **1st-ball-with-pins respot** (7+10 left → respot, no SP, advances to 2nd ball).
- **2nd-ball / strike fresh-rack** (all down → SP energized during `SPOTTING`, SP released after, resets to 1st ball).
- **Interlock guard** (`on_ball()` is ignored when `interlock_ok()` is False).

A second, richer harness lives in `controller_io.py.__main__`: it drives the *real* FSM through a strike cycle using `RecordingIO`, asserts the SP-on-fresh-rack output sequence and that `poll()` kicks the watchdog, and then runs the **pin-map regression guard** that verifies `OUT_A_MAP` / `IN_A_MAP` still match the PCB netlist generator (`scripts/generate_kicad_netlist_revB.py`) — the check that catches the BS/OS, M1/M2, and strike/foul bit-swap class of errors. These two harnesses are the off-live proof that the FSM satisfies its `io` contract and that the software bit maps match the as-built board; they do **not** substitute for the on-machine bench bring-up gate.
