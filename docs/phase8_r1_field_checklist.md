# R1 Field Checklist — 82-70 Signal Mapping (Lanes 21/22)

Print this. Work top to bottom. Fill the **REC** (record) columns. Companion to `phase8_8270_replacement_plan.md`.

**Signal set we need (per the daemon `LANE_GPIO` + control needs), PER MACHINE (do for BOTH lane 21 "even" and lane 22 "odd"):**
- READ: `diell_left`, `diell_right` (ball-detect beams), `foul`, `ball2` (2nd-ball lamp), `home/state` (NEW)
- DRIVE: `cycle`, `power`
- PRESERVE: person-in-pit interlock, E-stop

---

## 0. Pre-flight (do once)

- [ ] Multimeter: confirm it works (touch leads → continuity beeps; read a known battery on DC).
- [ ] **Establish GND reference** — power OFF: find chassis ground (green ground lug / bare frame), confirm continuity to frame. **This is your black-probe point for ALL voltage readings.** REC GND location: __________
- [ ] Confirm where the **Russell-Stoll 110V plug** is (your lockout point).
- [ ] Have wire-label flags + this sheet + a pen.
- [ ] ⚠️ 110VAC is live in the cabinet when powered. One hand in pocket, insulated probes, don't lean on frame. To WIRE anything: pull the Russell-Stoll plug first.

---

## 1. DRIVE signals — at the contactors (Stage D: power ON, running a cycle)

> CYCLE/POWER are driven by the machine's contactors (no FBOX here). You ID them by watching what energizes during a cycle. ⚠️ **Pit clear, no one near the mechanism, machine's own safety working, stand clear.**

| # | Signal | Where to find | Meter | State to read in | Expected | REC |
|---|---|---|---|---|---|---|
| 1 | **CYCLE coil** (per machine) | The contactor whose coil energizes the instant the cycle motor starts. Coil = terminals **A1 / A2**. | **AC volts**, 200V range, probe A1↔A2 | Trigger a cycle (let Omega-Tek cycle it) | **0V idle → coil-V during cycle.** That contactor = CYCLE. | coil V: ___ which contactor: ___ |
| 2 | **POWER coil** (per machine) | The contactor energized whenever the machine has power; drops on power-off. Coil A1/A2. | AC volts, A1↔A2 | Idle powered; then power off | **coil-V powered → 0V off** | coil V: ___ |
| 3 | Coil-V from label (both) | Read off each contactor body | (no meter) | — | Schneider CAD32**[suffix]** / Siemens 3TB4102 code | ___ |

**Also record (calibrates the control state machine):**
- [ ] **Cycle duration** (stopwatch, motor-start → machine-stops-at-home): ______ sec
- [ ] Does the cycle **self-stop at home**, or does the start signal need to be **held**? (Watch: does a brief energize run a full cycle, or does the contactor stay energized the whole cycle?) → __________

---

## 2. READ signals — best found AT THE SENSOR SOURCE (fewer wires than the connector)

> Each sensor has only 2–3 wires at its source — easier than hunting a 12-pin connector. Probe DC volts, black-on-GND.

| # | Signal | Where to find | Meter | State / stimulus | Expected | REC |
|---|---|---|---|---|---|---|
| 4 | **DIELL ball LEFT** (per lane) | Photo-beam unit at the pin deck, left side. Follow its cable; probe the signal wire (not the +12V/GND supply wires). | **DC volts**, 20V | Idle, then **break the left beam** (wave hand/roll ball) | rest ≈ **12V** (or 0 — record) → **flips** on beam-break | rest:___ active:___ wire:___ |
| 5 | **DIELL ball RIGHT** (per lane) | Same, right-side beam | DC volts, 20V | break the right beam | flips on beam-break | rest:___ active:___ wire:___ |
| 6 | **FOUL** (per lane) | Foul detector (Radaray-type) at the foul line; follow cable to chassis | **AC volts** first (lamp may be ~24/110VAC), then DC | Idle, then **trip the foul beam** (block it) | rest off → active on foul | type/V:___ wire:___ |
| 7 | **2nd-BALL lamp** (ball2, per lane) | 2nd-ball indicator lamp circuit / scoring harness | AC volts then DC | Cycle machine to 2nd-ball state | changes 1st↔2nd ball | type/V:___ wire:___ |

> Note on DIELL polarity: the bench chain showed NPN-style (signal pulled toward 0 when the beam is broken), so rest is likely ~12V, active ~0 — **but record what you actually see.** It must be consistent left/right.

---

## 3. READ signals — at the C2A connector (12-pin) — alternative / consolidation point

> If the sensor signals also appear on the **C2A connector** (Omega-Tek Fig.1, the ~12-pin connector / your photo-3 harness), you can map them here instead/as well. This is the "a lot of pins" part — do it as a **stimulus matrix**: keep probing pins while you apply each stimulus, mark the pin that responds.

**Method:** black-on-GND, **DC volts** (also note AC if a pin reads AC). First record every pin's idle voltage; then for each stimulus, find the pin that changes.

| C2A pin | idle DC | idle AC | breaks on **L beam** | breaks on **R beam** | breaks on **FOUL** | changes on **2nd ball** | changes on **cycle/home** | → SIGNAL |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |
| 6 | | | | | | | | |
| 7 | | | | | | | | |
| 8 | | | | | | | | |
| 9 | | | | | | | | |
| 10 | | | | | | | | |
| 11 | | | | | | | | |
| 12 | | | | | | | | |

(Cross-reference: the FBOX names these CYCLE=A+B, POWER=C+D, PRACTICE=E, FOUL=F+G, 1/2BALL=H+I, STRIKE=J+K — but on THIS machine confirm by stimulus, don't assume the letter→pin order.)

---

## 4. HOME / machine-state (NEW signal — needed to control, not just score)

| # | Signal | Where to find | Meter | State / stimulus | Expected | REC |
|---|---|---|---|---|---|---|
| 8 | **HOME / cam switch** (per machine) | A cam-operated switch in the mechanism/chassis that changes at the home position (8270 troubleshooting refs "S/T" and "SB" cam switches). | **DC volts** AND **continuity** | Run a cycle; meter through the whole cycle | one state **at home**, other **mid-cycle** | at-home:___ mid-cycle:___ wire:___ |

---

## 5. SAFETY — trace, DO NOT drive (Stage E — highest priority)

| # | Item | What to determine | Method | REC |
|---|---|---|---|---|
| 9 | **Person-in-pit interlock** | **Is it in SERIES with the cycle/power drive (hardware), or inside the Omega-Tek logic?** | Trace the pit safety sensor wiring → find where it interrupts the cycle/power path. Actuate it (carefully) and see what drops. | series? Y/N: ___ |
| 10 | **E-STOP** | What does it physically interrupt? | Trace E-stop circuit; press it, see what drops. | ___ |

> 🚩 If #9 is "inside the Omega-Tek logic" (not in series with the drive), **STOP** — removing the Omega-Tek would remove the interlock. R2 must re-establish a hardware interlock in series before the machine cycles under Pi control. This gates everything.

---

## 6. Consolidated Signal Table (transcribe results here — this is the R2 wiring spec)

| Signal | Machine (21/22) | Dir | Type (AC/DC, V) | Location (sensor / C2A pin / contactor) | Rest V | Active V | Confirmed by |
|---|---|---|---|---|---|---|---|
| cycle | | OUT | | | | | |
| power | | OUT | | | | | |
| diell_left | | IN | | | | | |
| diell_right | | IN | | | | | |
| foul | | IN | | | | | |
| ball2 | | IN | | | | | |
| home/state | | IN | | | | | |
| pit interlock | | KEEP | | | — | — | |
| E-stop | | KEEP | | | — | — | |

**Repeat the whole sheet for the second machine of the pair.** Label every wire as you confirm it.
