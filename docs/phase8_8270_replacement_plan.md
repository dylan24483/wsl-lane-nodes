# Phase 8 — AMF 82-70 Controller Replacement Plan (Lanes 21/22 pilot pair)

**Decision (2026-05-30):** the 21/22 pilot proceeds as a **full controller replacement**, not a scoring-only overlay. The Raspberry Pi node + custom watchdog/interposer PCB + AEDIKO relays become the pinsetter's controller, replacing the Omega-Tek Omniboard. Scoring + display + watchdog ride along.

**What's already done (bench-validated):** Pi daemon (sensor read + relay drive + WS), hardware watchdog integrated (GPIO 12 kick, kill-9 drops relays in ~11s), AC interposer, DIELL→opto→GPIO chain, Phase 8b score store unification, board #2 fully validated (board #1 = DOA, leak).

**What's NOT done (the real remaining work):**
1. The **cycle-control state machine** (daemon code) — does not exist yet.
2. The **lane signal map** — must be probed on the actual machine (it's a hybrid: 82-70 SS chassis + 1984 Omega-Tek board + modern Schneider/Siemens control relays; the docs don't match it pin-for-pin).
3. A sensor we haven't tapped: **machine-state / home feedback** (needed to control, not just score).

---

## ⚠️ SAFETY FLOOR (non-negotiable, read first)

A pinsetter that cycles with a person in the pit can **kill or maim**. The Pi watchdog protects against the Pi *crashing* (relays default open). It does **NOT** protect against our control *logic being wrong* (a mistimed cycle). Therefore:

1. **The machine's existing hardware safety interlocks — the ball-detect "person in the pit" interlock and the E-stop — stay physically in the circuit, in series, independent of our software.** Our relays may only *command* a cycle; the hardware interlock must always be able to *veto* it. Design the tap so a stuck/buggy Pi output cannot energize the cycle motor when the interlock is open.
2. **The controller's first live run is NOT on a revenue lane during business hours.** Validate it driving the machine off-hours (or on a spare), with the Omega-Tek ready to drop back in (rollback confirmed available).
3. **Lockout when wiring:** pull the Russell-Stoll 110V plug at the pinspotter (the OEM disconnect method) before any wiring change. 110VAC is present in the cabinet.
4. **When running cycles for signal ID:** confirm no one is near the pit/mechanism, the machine's own safety interlock is functional, and stand clear of moving parts.

---

## Phase R0 — Write + bench-validate the cycle-control logic (at the desk, before the lane)

The daemon today is a reader/driver/watchdog. Add the **8270 cycle state machine**. The 82-70 is a free-fall, cam-sequenced machine: the controller does **not** sequence sub-motions — it triggers a cycle and the machine's cams run the mechanical sequence. So the logic is bounded.

**Inputs:** ball-detect (DIELL), foul, machine-state/home, (optionally 2nd-ball lamp state).
**Outputs:** CYCLE (pulse), POWER (latch).
**Spec / timing (from QubicaAMF FBOX 8270 defaults, T-VISION manual p64):**
- Cycle pulse width ≈ **0.3 s**, inter-pulse pause ≈ 0.1 s
- Reset/cycle time ≈ 14 (units per FBOX scale — calibrate against measured cycle duration in R1)
- Auto-power ON; Strike N.C.
- 1st-ball vs 2nd-ball: full cycle vs quick cycle (per FBOX "Pulse W 1/2")
- Foul → re-cycle to reset to 1st ball

**State machine (draft):**
```
POWER_OFF ──(enable)──> READY(at home)
READY ──(ball-detect, 1st ball)──> CYCLE_FULL ──(home reached)──> READY(2nd ball)
READY(2nd ball) ──(ball-detect)──> CYCLE_FULL ──(home)──> READY(1st ball, new frame)
any ──(foul)──> CYCLE_RESET ──(home)──> READY(1st ball)
any ──(E-stop / interlock open)──> SAFE_STOP (relays open; do not command)
any ──(daemon hang)──> watchdog opens relays (hardware)
```
**Rules:**
- Never command CYCLE unless machine-state = at-home/ready AND interlock closed.
- Honor home feedback to know when a cycle completed (don't re-fire mid-cycle).
- Keep kicking the hardware watchdog (already implemented) only while the control loop is healthy.

**Bench validation (R0 exit):** drive the state machine with simulated inputs (buttons/scripts for ball/foul/home), scope the CYCLE/POWER outputs + timing, verify foul re-cycle, verify SAFE_STOP on simulated interlock-open, verify watchdog still drops relays on kill-9.

---

## Phase R1 — Lane signal mapping (DETAILED probing procedure)

**Goal:** produce the per-machine **Signal Table** (below) — for EVERY signal we drive or read, the wire/connector/pin, type (AC/DC), rest voltage, active voltage, and behavior. This is the spec for R2 wiring. The machine is a modified hybrid, so this is *guided discovery*, not "probe pin N."

### Equipment
- Multimeter: DC volts, AC volts, continuity/beep. (A second meter or a clamp meter helps.)
- Insulated probes; alligator test leads.
- Wire-label flags / tape + marker; notebook or phone.
- A helper is very useful (one person triggers stimulus while the other meters).
- Lockout: know where the Russell-Stoll 110V plug is.

### Establish the ground reference FIRST (Stage A)
Everything is measured **black-probe-on-GND, red-probe-on-signal**. Before anything:
- **Power OFF / locked out.** Identify chassis ground: the green ground lug (Omega-Tek Fig.1 shows a "CONNECT TO GND" lug), or the C2A connector's GND pin, or bare frame metal.
- Continuity-confirm your chosen GND point to the chassis frame (beep). Use that as black-probe reference throughout.

### Stage A — Power OFF (locked out): orient + continuity
1. **Trace the two external harnesses** (the only wiring leaving the box). For each conductor, use continuity to find its far end:
   - Goes to a **motor** (table/sweep/back-end/cycle) → it's a contactor *output* (power side).
   - Goes to the **pin deck (DIELL beams)** or **foul line (foul detector)** → it's a *sensor* line.
   - Note wire color + destination for every conductor. This sorts the harness into "drives" vs "reads."
2. **Identify the contactors and what each switches.** For each contactor (incl. the Schneider CAD32 and Siemens 3TB4102 — note these are *control relays*, so also look for larger *motor* contactors): continuity from its switched poles to a motor tells you which motor it controls. Record coil terminals **A1/A2** for each.
3. **Read coil voltages off labels** (don't meter live if avoidable): Schneider CAD32**[suffix]** and Siemens 3TB4102 coil code give rated coil voltage.
4. ⚠️ Do **not** trust Stage-A guesses for CYCLE/POWER — confirm dynamically in Stage D.

### Stage B — Power ON, machine IDLE (at home, no ball): static reads
Restore power. With the machine sitting idle:
- **DIELL ball-detect lines:** meter each candidate (DC volts, ref GND). At rest (beam intact) expect a steady level (~12V or ~0 — **record which**). This is the rest state of the ball input.
- **Foul line:** meter the candidate foul wire at rest. Record.
- **Home/cam switch:** meter the candidate machine-state wire with the machine at home. Record the at-home level.
- **POWER:** confirm the power contactor is energized (coil reads its rated voltage; mains present at the pinspotter).
- Write all rest voltages into the table.

### Stage C — Stimulus tests: identify the INPUT signals (low risk)
Trigger each input and watch the wire flip — this positively IDs ball + foul without running the mechanism:
- **BALL-DETECT:** break the DIELL beam by hand (wave through it / roll a ball slowly). The correct wire **flips** (e.g., 12V↔0). Confirm against the bench behavior we already validated. **Label it.** (Both beams, left/right, both lanes.)
- **FOUL:** break the foul-line beam (step through it / block it). The foul wire flips; note whether it's a ~**24VAC lamp** signal or a DC logic level. **Label it.**

### Stage D — Run a cycle: identify the OUTPUT + STATE signals (higher risk — clear the pit)
⚠️ **No one near the pit/mechanism. Machine's own safety interlock functional. Stand clear.** Trigger a cycle (let the Omega-Tek cycle it — complete a ball-detect, or use the machine's cycle/test button):
- **CYCLE drive:** watch which contactor/relay energizes the instant the cycle motor starts. Meter its coil (A1/A2): 0V idle → coil voltage during cycle. **That's the CYCLE point we'll drive.** Label it. Note its coil voltage + AC/DC.
- **HOME / machine-state:** meter the candidate home/cam wire **through a full cycle** — it transitions as the machine leaves home and returns. Record the transition (level at home vs mid-cycle). **This is the feedback the controller needs.** Label it.
- **POWER:** the contactor that stays energized while the machine is powered and drops on power-off. Confirm + label.
- **Measure the cycle duration** (stopwatch): how long the cycle motor runs end-to-end. This calibrates the state-machine timing vs the FBOX 0.3s-trigger assumption (the trigger is brief; the machine self-runs the cycle — confirm whether it self-stops at home or needs a held signal).

### Stage E — Safety interlock trace (critical)
- Identify the **ball-detect "person in pit" interlock** and the **E-stop** in the circuit. Trace HOW they cut the machine (they interrupt the cycle/power path).
- Confirm they're in **series** such that our drive sits **downstream** of them — i.e., when the interlock opens, our relay closing cannot energize the cycle motor. If the current design doesn't allow that, R2 must add it (our relay in series WITH the interlock, not bypassing it).

### Signal Table (fill this — it's the R2 spec)
| Signal | Dir | Type (AC/DC, V) | Wire color / connector+pin | Rest V | Active V | How confirmed (stage) | Notes |
|---|---|---|---|---|---|---|---|
| CYCLE (drive) | OUT | | | | | D | which contactor |
| POWER (drive) | OUT | | | | | D | |
| BALL L21 L/R | IN | ~12V DC | | | | C | DIELL beams |
| BALL L22 L/R | IN | ~12V DC | | | | C | |
| FOUL L21 | IN | | | | | C | AC lamp? |
| FOUL L22 | IN | | | | | C | |
| HOME/STATE L21 | IN | | | | | D | cam/home |
| HOME/STATE L22 | IN | | | | | D | |
| SAFETY interlock | KEEP | | | — | — | E | must stay in series |
| E-STOP | KEEP | | | — | — | E | |

---

## Phase R2 — Interface hardware + enclosure (driven by the R1 table)

- **Drive CYCLE + POWER:** AEDIKO relay (dry NO contact) wired to switch the cycle/power contactor coil circuit — **in series with / downstream of the safety interlock** (per R1 Stage E). Coil voltage per the R1 table sets what the contact switches.
- **Read BALL + FOUL + HOME:** through opto isolation to Pi GPIO (DIELL chain already validated; foul/home via interposer or opto sized to the measured voltage). Match the daemon's GPIO map (foul/ball2/diell pins per `LANE_GPIO`); add a GPIO for HOME/state.
- **Watchdog:** the PCB gates the AEDIKO coil-return (already built); GPIO 12 kick keeps it alive.
- **Enclosure:** IP65 DIN box — Pi (PoE), custom PCB, AEDIKO, opto board, **5V DIN PSU (HDR-15-5)** for board+AEDIKO; 24V (HDR-150-24) only if a sensor needs it. Glands for: Cat6, the tapped signals in/out, mains for the PSU.
- Keep the Omega-Tek physically present but its outputs disconnectable, so rollback = reconnect Omega-Tek.

---

## Phase R3 — Off-live controller validation (off-hours or spare machine)

With the interface wired and the Pi running the R0 state machine, **Omega-Tek control disconnected** (its board left in place for rollback):
1. Confirm POWER control (Pi powers the machine on/off).
2. Single manual cycle: command one cycle, verify the machine completes and returns home; verify HOME feedback read correctly.
3. Ball→cycle: break the DIELL beam, verify the Pi cycles the machine; verify 1st/2nd-ball sequencing.
4. Foul→re-cycle: trip foul, verify reset behavior.
5. **Safety:** open the interlock/E-stop mid-attempt → machine must NOT cycle even though the Pi commands it (hardware veto). `kill -9` the daemon → relays drop, machine safes within ~11s.
6. Run 50–100 cycles unattended (no pins/no people) watching for mistimes, double-cycles, missed home.
**R3 exit:** clean cycling + every safety case passes. ONLY then schedule the live cutover.

---

## Phase R4 — Cutover + soak (lanes 21/22)

1. Off-hours window, rollback ready (Omega-Tek reconnect).
2. Pi takes over control + scoring + display.
3. Soak under real play, monitored (`/api/health`, scoring accuracy, zero spurious cycles, watchdog behavior, uptime). Rollback on any safety anomaly.
4. After clean soak: declare 21/22 done; template for the next pair.

---

## Open risks / unknowns to close in R1
- **Does the cycle self-stop at home, or need a held signal?** (Determines state-machine output: pulse vs hold.) — answer in Stage D.
- **Is the safety interlock currently in series with the cycle drive, or in the Omega-Tek logic?** If the latter, removing the Omega-Tek could remove the interlock — R2 MUST re-establish it in hardware. — answer in Stage E. **This is the highest-stakes unknown.**
- **2nd-ball-lamp / mask signals** for full scoring fidelity — map if scoring needs them.
- Modern contactor coil voltages (label read) — sets AEDIKO contact rating/wiring.
