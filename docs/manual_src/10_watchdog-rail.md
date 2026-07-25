## 10. Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail

This section documents the two hardware blocks that decide whether the on-board
motion relays are *allowed* to energize: the **NE555 monostable watchdog** (which
watches the Raspberry Pi) and the **relay-enable rail** (a hardware AND of six
independent conditions that gates the P-channel pass-FET feeding all relay coils).

Everything here is grounded in the live board netlist generator
(`scripts/generate_kicad_netlist_revB.py`, functions `block_watchdog()` and
`block_rail()`), the as-built netlist (`kicad/wsl-phase8b.net`), the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`),
the design contract (`docs/phase8b_pcb_revB_spec.md` §4), and the RP2040 firmware
(`firmware/rp2040/config.h`, `firmware/rp2040/README.md`).

> **Read this first — the one non-negotiable rule.** This board is **never** the
> only safety device. Live motor current never crosses the PCB (S/T motor current
> stays on the machine contactors, with their OEM regenerative braking on the N.C.
> contacts), the TB/SC collision interlock and the installed Stop/master-breaker
> chain remain upstream in hardware, and the rail described here only removes the *coil
> drive permission* for the on-board relays. See §10.6 (Welded-contact limitation)
> and cross-reference §19 (Safety Model — OEM Stop/C.I.S. history versus the
> Stop-only pilot installation) and the FSM's
> power-down rule.

---

### 10.1 What these blocks do, in one paragraph

The Pi runs the cycle FSM and commands the 7 motion relays *indirectly* over I²C
through the `MCP23017 OUT-A` expander (see §7, Controller Interface). But software
commanding a relay bit HIGH does **not** energize the coil. Each coil's high side
is fed from `RELAY_ENABLE_RAIL`, passed by Q14 only when the implemented on-board
gates permit it. The PCB was designed with two external source-loop positions plus
the transistor stack, but Candidate C deliberately closes the first position
(J_SAFE1-2) with a controlled jumper because this chassis has no dry TB/SC pair.
The remaining on-board gates are watchdog, ARM, RP2040_OK/cam-stop, and continuity
through the J_SAFE3-4 source position. On the lane-21/22 production harness,
J_SAFE3-4 is physically OPEN/unlanded; the field rail therefore cannot arm. Never
jumper 3–4 at the machine. The leading design uses an externally mounted,
correctly rated energize-to-prove control-power relay; only its isolated N.O. dry
contact reaches J14, optionally in series with an approved new pit-entry-interlock
contact. Sensed machine voltage and mains stay off Rev-D.
Primary TB/SC protection is a separate hardware path: the powered-proven OEM
parallel-safe contacts remain in the board-commanded S/T coil circuits and must pass
the per-lane G3 insertion proof. Loss of an implemented on-board gate collapses all
board relay coils; both TB/SC levers BACK/open independently block S and T.

---

### 10.2 The NE555 monostable watchdog (watches the Pi)

The NE555 is wired as a **retriggerable monostable** (one-shot). Left alone, its
timing capacitor charges, the output stays in its idle state, and the watchdog "OK"
condition is **false**. The Raspberry Pi must periodically **kick** it (pulse a
GPIO) to keep restarting the one-shot and thereby hold the watchdog "OK" condition
**true**. If the Pi process hangs, crashes, or the OS dies, the kicks stop, the
monostable times out, and the watchdog condition drops the rail. This is the
hardware backstop for "the Pi died" — it is independent of the RP2040, of UART, and
of any software running on the Pi.

> **Two different watchdogs — do not confuse them.** This NE555 watches the **Pi**.
> The RP2040 has its own *internal* hardware watchdog (`WDT_TIMEOUT_MS = 250 ms`,
> `firmware/rp2040/config.h`) that watches the **Pico firmware** and is a *separate*
> rail condition (it manifests as `RP2040_OK`/Cam-stop, §10.3 rows 3–4). The NE555
> covers Pi-side death; the RP2040 internal WDT covers Pico-side death.

#### 10.2.1 NE555 watchdog — parts

Reference designators are from the as-built netlist; LCSC/MFR part numbers from the
JLC PCBA BOM.

| RefDes | Part / value | Footprint | LCSC | Role in the watchdog |
|---|---|---|---|---|
| U36 | NE555DR (TI) **bipolar** 555 timer | SOIC-8 (`SOIC-8_3.9x4.9mm`) | C7593 | Monostable one-shot. **Bipolar 555 — do NOT substitute a CMOS/TLC555**; the timing/threshold behavior would change (BOM note). |
| Q12 | AO3400A N-ch MOSFET ("kick") | SOT-23 | C20917 | Level/edge buffer for the Pi's `WDOG_KICK` GPIO; its drain pulls the timing/trigger node. |
| Q13 | AO3400A N-ch MOSFET ("wdog") | SOT-23 | C20917 | The watchdog-OK output device — its drain is the bottom of the rail AND chain (§10.3/§10.4). |
| C11 | 100 µF / 16 V aluminum electrolytic (**polarized**) | `CP_Elec_6.3x5.4` | C19184134 | Timing capacitor. Verify polarity mark before solder. |
| R100 | 100 k | 0805 | C149504 | Timing resistor (sets the RC charge time with C11). |
| C13 | 10 nF | 0805 | C17702767 | NE555 CTRL-pin (pin 5) decoupling. |
| C12 | 100 nF (0.1 µF) | 0805 | C49678 | NE555 VCC decoupling. |
| R101 | 10 k | 0805 | C17414 | **Trigger pull-up** (the "Rev-A trigger pull-up fix", spec §4.3). |
| R102 | 1 k | 0805 | C17513 | Gate resistor for the kick FET Q12. |
| R103 | 10 k | 0805 | C17414 | Gate pulldown for Q12 (default-off / fail-safe). |
| R104 | 1 k | 0805 | C17513 | Gate resistor for the wdog-OK FET Q13. |
| R105 | 10 k | 0805 | C17414 | Gate pulldown for Q13 (default-off / fail-safe). |
| D15 | 1N4148WS | SOD-323 | C118873 | Steers Q12's kick into the **timing** node (`WDOG_TIMING_NODE`). |
| D16 | 1N4148WS | SOD-323 | C118873 | Steers Q12's kick into the **trigger** node (`NE555_TRIG`). |

> The R-designators above are read off the as-built netlist's `(name "SKiDL Tag")`
> entries: `R_WDOG_TIMING`→R100, `R_WDOG_TRIG_PULLUP`→R101, `R_WDOG_KICK_GATE`→R102,
> `R_WDOG_KICK_PD`→R103, `R_WDOG_OUT_GATE`→R104, `R_WDOG_OUT_PD`→R105. Capacitors:
> `C_WDOG_TIMING`→C11, `C_WDOG_VCC`→C12, `C_WDOG_CTRL`→C13. The 0805 R/C parts share
> a single grouped BOM line each, so the same LCSC number covers many same-value
> parts on the board — confirm by *value*, not by assuming a unique line per RefDes.

#### 10.2.2 NE555 pin connections (U36, SOIC-8)

NE555 pin numbers below are the standard 555 pinout as wired in `block_watchdog()`.

| 555 pin | Function | Net on this board | Connected to |
|---|---|---|---|
| 1 | GND | `GND` | board ground |
| 2 | TRIG (trigger, active-low) | `NE555_TRIG` | R101 (10 k pull-up to VCC_5V), D16 (from kick FET) |
| 3 | OUT (output) | `NE555_OUT` | R104 → Q13 gate (drives the watchdog-OK FET) |
| 4 | RESET (active-low) | `VCC_5V` | tied HIGH (reset disabled) |
| 5 | CTRL (control voltage) | `NE555_CTRL` | C13 (10 nF) to GND — noise decoupling |
| 6 | THRES (threshold) | `WDOG_TIMING_NODE` | R100 (100 k) to VCC_5V, C11 (100 µF) to GND, D15 |
| 7 | DISCH (discharge) | `WDOG_TIMING_NODE` | same node as pin 6 (THRES tied to DISCH — classic monostable) |
| 8 | VCC | `VCC_5V` | +5 V logic rail, with C12 (0.1 µF) decoupling |

Pins **6 and 7 are tied together** on `WDOG_TIMING_NODE` with R100 to +5 V and C11
to ground — the textbook 555 monostable RC. The watchdog runs from the **+5 V logic
rail** (`VCC_5V`), the same regulated supply as the MCP23017s' coil drivers, **not**
from 3.3 V.

#### 10.2.3 How a kick keeps the watchdog OK

1. **Pi kicks.** The Pi pulses its watchdog-kick GPIO. On the Rev-B board that
   signal arrives on connector **J1 (J_PI) pin 7**, net `WDOG_KICK`, through R102
   into the gate of the kick FET **Q12** (gate held off by R103, 10 k pulldown, when
   the Pi is silent → fail-safe). In the lane-node software this kick is
   `MachineIO.watchdog_kick()` / the injected `watchdog_kick` callable
   (`lane_node/controller_io.py`), i.e. the GPIO12 pulse referenced as "the NE555
   watchdog kick."
2. **Kick drives the timing + trigger nodes.** Q12 turning on pulls
   `WDOG_KICK_DRAIN` low; D15 and D16 (1N4148) steer that into the **timing** node
   (discharging/restarting the RC) and the **trigger** node (re-firing the
   one-shot). Each kick restarts the monostable.
3. **Output → watchdog-OK FET.** While kicks keep arriving inside the timeout
   window, the NE555 output (pin 3, `NE555_OUT`) drives the gate of **Q13** through
   R104 such that Q13 **conducts** — and Q13's drain (`WDOG_OK_PULLDOWN`) is the
   bottom rung of the rail AND chain (§10.4). Conducting Q13 = "Watchdog OK" = true.
4. **Missing kicks → rail drops.** If kicks stop for longer than the monostable's
   timeout, the NE555 output reverts, Q13 turns **off**, the AND chain opens, the
   pass-FET turns off, and **all relay coils drop**.

> **(VERIFY: NE555 monostable timeout period.)** The RC is R100 = 100 k and C11 =
> 100 µF (≈ 1.1·R·C ≈ 11 s nominal for a standard monostable), but the kick is wired
> into **both** the timing node and the trigger (a retrigger topology), and the
> design doc describes it qualitatively as "missing kick for the timeout window
> drops the rail" (spec §4.3) without stating the number. The **effective** Pi-kick
> interval and the guaranteed worst-case drop time are bench-bring-up items
> (spec §12.9 "watchdog drop" step) and are **not** asserted as a specific value in
> the sources read for this section. Measure on the bench; do not assume 11 s.

> **(VERIFY: kick GPIO number on the Pi.)** This section's sources fix the *board*
> side (J1 pin 7 → `WDOG_KICK`). Project memory describes the Pi pulsing **GPIO 12**
> for the watchdog kick, but the Pi-side GPIO assignment is not pinned down in the
> four files read here — confirm against the lane-node daemon wiring.

---

### 10.3 The relay-enable rail — board design vs Candidate-C field implementation

`RELAY_ENABLE_RAIL` is the high-side supply to every motion-relay coil. The table
retains the PCB contract's six named conditions, but row 5 is **not an external
TB/SC loop on lanes 21/22**: Candidate C installs the controlled J_SAFE1-2 jumper
and delegates primary TB/SC blocking to the OEM S/T coil ladder. Rows 1–4 and 6
describe the remaining board/source permissions, but row 6 is currently
OPEN/unlanded and therefore holds the field rail dead. The per-lane G3 S/T
coil-drop proof is what validates the separate OEM path.

| # | Condition | Source / device | Where it acts on the rail | Fail-safe default |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 (U36) kicked by the Pi → FET Q13 | Bottom of the gate AND chain (Q13 must conduct) | false (no kicks → Q13 off) |
| 2 | **Arm OK** | Pi `ARM_PERMIT` GPIO (J1 pin 8) → NPN Q15 | Top of the gate AND chain (Q15 must conduct) | false (R108 100 k base pulldown) |
| 3 | **RP2040 OK** | RP2040 `GP2` health line (`RP2040_OK`) → NPN Q16 | Middle of the gate AND chain (Q16 must conduct) | false (R110 100 k base pulldown; GP2 Hi-Z on reset) |
| 4 | **Cam-stop OK** | RP2040 immediate cam-stop drop | **Folds into condition 3** — the firmware drops `GP2` LOW on a cam-stop violation/timeout | false on RP2040 reset/fault |
| 5 | **TB/SC board provision** | **Candidate C controlled jumper** on J_SAFETY pins 1↔2; no machine landing | Closes the first FET-source position; primary guard is the OEM coil ladder | only the keyed/labeled jumper is allowed; protection fails G3 if either commanded coil remains live with both levers BACK |
| 6 | **Reserved external control-power / optional pit-interlock source position** | J_SAFETY pins 3↔4; future validated isolated dry-contact interface, **currently OPEN/unlanded** | In series with the FET source, after the Candidate-C jumper position | open; field rail cannot arm |

Two structural facts make this a true hardware AND:

- **The J_SAFE1-2 and J_SAFE3-4 positions are physically in series with the FET
  source.** In Candidate C, 1–2 is the controlled jumper. Position 3–4 is reserved
  for a future validated external control-power dry interface, optionally in
  series with an approved new pit-entry-interlock contact, and is currently open/unlanded.
  Opening either completed position can prove PCB/source continuity only; it does
  not prove the OEM TB/SC guard or upstream Stop-to-breaker operation.
- **Conditions 1, 2, and 3 (=4) are a series transistor stack on the FET's gate** —
  all three must conduct to pull the P-FET gate low enough to turn it on. Any one
  open and the gate stays pulled up to the source (FET off).

> **Why cam-stop is not a separate transistor.** The contract lists Cam-stop OK as a
> distinct rail condition (spec §4.1), but the PCB implements it through
> `RP2040_OK`: any **enabled and qualified** firmware enforcement latches a fault and
> drives the single `GP2` permission line LOW. Electrically there are five physical
> gates (two source positions + a three-transistor AND); do not look for a sixth
> transistor. The current controlled **v1.2.3** Rev-D bundle keeps every
> measured-cam enforcement flag **OFF** pending polarity capture, qualification, and
> a new controlled release. Its active backstops are firmware health plus the 8 s
> motion max-run timeout. The SC∧TB echo is also default-off, unvalidated, secondary,
> and lacks an independent TB field lead on lanes 21/22.

---

### 10.4 The AND-chain transistors (gate pull-down stack)

This is the heart of "non-bypassable." The pass-FET **Q14 (AO3401A, P-channel)** is
a high-side switch: its **source** is fed (through the two NC safety loops) from
+5 V, its **drain** is `RELAY_ENABLE_RAIL`, and its **gate** (`RAIL_GATE`) is held
**up to the source** by R106 (100 k) — i.e. **off by default**. To turn the rail
ON, something must pull `RAIL_GATE` down to ground. That "something" is three NPN
transistors in series:

```
RAIL_GATE (Q14 P-FET gate, pulled up to source by R106 100k)
    │
    ▼  collector
  Q15  MMBT3904  "AND ARM"     base = ARM_PERMIT (via R107 1k; R108 100k pulldown)
    │  emitter → AND_MID_ARM_RP
    ▼  collector
  Q16  MMBT3904  "AND RP_OK"   base = RP2040_OK (via R109 1k; R110 100k pulldown)
    │  emitter → WDOG_OK_PULLDOWN
    ▼  drain
  Q13  AO3400A   "wdog"        gate = NE555 OUT (via R104; R105 100k pulldown)
    │  source
    ▼
   GND
```

For `RAIL_GATE` to reach ground (turning the P-FET on), **Q15 AND Q16 AND Q13 must
all conduct simultaneously**. That is a literal series-AND:

- **Q15 conducts** only if `ARM_PERMIT` is high (Pi has armed — operator-safe state).
- **Q16 conducts** only if `RP2040_OK` is high (RP2040 healthy and no enabled
  enforcement has latched a fault; stock v1.2.3 measured-cam flags are OFF).
- **Q13 conducts** only if the NE555 says "watchdog OK" (Pi is kicking).

Each base/gate has a **100 k pull-down** (R108, R110, R105) so the default state with
no drive is OFF. If any single device is off, the chain is open, R106 holds the gate
at the source, and the P-FET is off → rail dead.

#### 10.4.1 AND-chain + pass-FET — parts and nets

| RefDes | Part / value | LCSC | Pin → net (from netlist) |
|---|---|---|---|
| Q14 | AO3401A P-ch MOSFET (rail pass-FET) | C347476 | **S** (pin2) ← `SAFE_STOP_RETURN`; **G** (pin1) ← `RAIL_GATE`; **D** (pin3) → `RELAY_ENABLE_RAIL` |
| Q15 | MMBT3904 NPN ("AND ARM") | C909754 | **B** (pin1) ← `BASE_AND_ARM`; **E** (pin2) → `AND_MID_ARM_RP`; **C** (pin3) → `RAIL_GATE` |
| Q16 | MMBT3904 NPN ("AND RP_OK") | C909754 | **B** (pin1) ← `BASE_AND_RP_OK`; **E** (pin2) → `WDOG_OK_PULLDOWN`; **C** (pin3) → `AND_MID_ARM_RP` |
| Q13 | AO3400A N-ch MOSFET (watchdog OK) | C20917 | **G** (pin1) ← `WDOG_OK_GATE`; **S** (pin2) → `GND`; **D** (pin3) → `WDOG_OK_PULLDOWN` |
| R106 | 100 k (`R_RAIL_GATE_PULLUP`) | C149504 | pin1 → `SAFE_STOP_RETURN` (source side); pin2 → `RAIL_GATE` |
| R107 | 1 k (`Rb_AND_ARM`) | C17513 | `ARM_PERMIT` → Q15 base |
| R108 | 100 k (`Rpd_AND_ARM`) | C149504 | Q15 base → `GND` (fail-safe pulldown) |
| R109 | 1 k (`Rb_AND_RP_OK`) | C17513 | `RP2040_OK` → Q16 base |
| R110 | 100 k (`Rpd_AND_RP_OK`) | C149504 | Q16 base → `GND` (fail-safe pulldown) |

> **MMBT3904 grouping note.** The PCBA BOM groups Q1,Q2,Q3,Q4,Q5,Q6,**Q15,Q16** on
> one line (8× MMBT3904, C909754); Q1–Q6 are the relay-coil base drivers (§10.5),
> Q15/Q16 are the AND-chain transistors here. The two AO3400A devices (Q12 kick,
> Q13 wdog) share LCSC C20917; the single P-channel pass-FET Q14 is AO3401A
> (C347476). **Q12/Q13/Q14 are visually similar SOT-23 parts — do not swap N-ch and
> P-ch during hand placement.**

#### 10.4.2 The two J_SAFETY source positions (J14) and Candidate C

The safety connector **J14 (J_SAFETY)** is a 4-pin Phoenix MCV terminal. The PCB
wires two source **positions** in series between +5 V and the pass-FET source.
The lane-21/22 field harness does not populate both as machine loops:

```
VCC_5V ── J14.1 ──[ controlled Candidate-C jumper ]───── J14.2
                                                          │  (SAFE_TBSC_RETURN: J14.2 ↔ J14.3 on-board jumper net)
                          J14.3 ──[ future isolated energize-to-prove control-power
                                    dry contact; optional approved pit-interlock contact in series;
                                    CURRENTLY OPEN / UNLANDED ]────────── J14.4
                                                                          │
                                                                   SAFE_STOP_RETURN ── Q14 source (+ R106 high side)
```

| J14 pin | Net | Meaning |
|---|---|---|
| 1 | `VCC_5V` | Source feed into the first board-side position |
| 2 | `SAFE_TBSC_RETURN` | Return of the first board-side position; Candidate C jumpers it from pin 1; on-board it is the same net as pin 3 |
| 3 | `SAFE_TBSC_RETURN` | Source side of the reserved external interface (same board net as pin 2); current harness lead is CUT+LABEL-ONLY |
| 4 | `SAFE_STOP_RETURN` | Return side of the reserved external interface → pass-FET source (+ R106); current harness lead is CUT+LABEL-ONLY |

So: +5 V enters pin 1, traverses the controlled Candidate-C jumper (pins 1→2),
and crosses the on-board pin-2/pin-3 net. It can reach the pass-FET source only
after a future approved 3→4 interface closes. Today that position is open, so the
field rail cannot arm. Never jumper 3–4 at the machine. Opening either completed
connector position proves only source-path continuity; J_SAFE1-2 is not the field
collision sensor, and J_SAFE3-4 continuity is not end-to-end breaker proof.
The OEM TB/SC contacts instead act downstream in the machine's S/T coil circuits.

> **Field resolution:** TB/SC is closed: no dry J14 landing exists. The 2026-06-27
> cold trace found C2A-U plus ~21 Ω sneak paths but could not establish topology;
> powered 2026-07-07 proved parallel closed-when-safe contacts and both levers
> BACK/open kills S and T. Candidate C therefore uses only the controlled jumper on
> pins 1–2 and a mandatory per-lane G3 coil-drop proof. The separate pins-3/4
> landing remains OPEN pending approval of the external energize-to-prove
> control-power interface and the pilot pit-entry-interlock design decision.

---

### 10.5 What the rail gates: the relay coils

`RELAY_ENABLE_RAIL` (net code 141 in `kicad/wsl-phase8b.net`) reaches the **high
side (pin 1) of all seven motion-relay coils** plus their flyback-diode cathodes and
the pass-FET drain. Confirmed nodes on that net:

| RefDes on `RELAY_ENABLE_RAIL` | What it is |
|---|---|
| K1, K2, K3, K4, K5, K6, **K7** | Relay coil pin 1 (high side) for S, T, SP, BE, M, M2, **M1** |
| D1, D3, D5, D7, D9, D11, **D13** | Flyback-diode cathodes across each coil (the odd-numbered 1N4148 + D13 for M1) |
| Q14 pin 3 | Pass-FET drain (the rail's source of supply) |

The relays are **Omron G5LE-14, 5 VDC coil** (`K1`–`K6`, LCSC **C116963**; BOM note:
"Critical: 5VDC coil. Do not substitute 9V/12V/24V coil."). **K7 (M1, ball return)
is DNP** — populate-optional, not bench-confirmed on this chassis (spec §3.2,
§11 item 6); its coil/flyback/driver footprints exist on the rail but are not
assembled by default. Each coil's low side is switched to ground by a per-relay
NPN driver:

| Output | Relay | Coil driver (NPN) | Driver base R / pulldown | Notes |
|---|---|---|---|---|
| S (sweep) | K1 | Q1 (MMBT3904) | R67 (1 k) / R68 (100 k) | |
| T (table) | K2 | Q2 | R70 / R71 | |
| SP (spot) | K3 | Q3 | R73 / R74 | |
| BE (back-end) | K4 | Q4 | R76 / R77 | |
| M (master) | K5 | Q5 | R79 / R80 | |
| M2 (sweep reverse) | K6 | Q6 | R82 / R83 | |
| M1 (ball return) | K7 | Q7 | R88 / R89 | **DNP** — entire channel optional |

**Two gates in series for any motion output.** A relay only energizes if (a) the Pi
sets its `MCP23017 OUT-A` bit, turning on the per-relay NPN to ground the coil low
side, **AND** (b) the rail is live, supplying +5 V to the coil high side. The Pi
controls (a); the implemented on-board safety rail controls (b). Software alone cannot fire
a coil. (The relay contacts themselves only open/close **existing machine control
circuits** — the board sources no machine coil power and carries no motor current;
see §9, Output Contract, and §10.6.)

> **(VERIFY: relay contact rating headroom.)** Spec §11 item 1 lists "confirm contact
> current/voltage for S/T/SP/BE/M/M2 and whether G5LE-1 margin is sufficient" as an
> open assembly-gate item. The footprint and 5 VDC coil are fixed; the contact-side
> AC-inductive load rating is to be confirmed against measured machine
> control-circuit current before populated-board sign-off.

---

### 10.6 Welded-contact limitation (read before relying on the rail)

The rail de-energizes relay **coils**. It physically **cannot open a relay contact
that has welded closed.** If a contact welds, dropping the rail removes coil drive
but the welded contact stays made — and the machine control circuit it feeds stays
made. Therefore:

- **The relay contact rating, arc suppression, and validation are safety-relevant.**
  Each motion output has DNP footprints for an RC snubber (`Rsnub_*` 100 R + `Csnub_*`
  10 nF X2) and a MOV across the contact, to be populated per output after load
  characterization (spec §2.3 / §3.2). Do not skip suppression on inductive AC
  control loads.
- **The final physical stop is upstream and external.** The existing **master
  circuit breaker / installed Stop chain** on pilot lanes 21/22 remains the
  irreducible kill path — it removes machine control power
  regardless of any welded on-board contact. The rail is a *permission* layer, not a
  *disconnect* layer. An OEM C.I.S. or other pit-entry interlock receives credit
  only where physically present and separately demand-proven (see §19).
- **Regenerative motor braking stays in machine hardware** (the relay N.C. contacts +
  caps on the machine contactors), independent of this board.

This is why the contract's headline rule (top of this section, and spec §"non-
negotiable safety rule") forbids ever treating this board as the only safety device.

---

### 10.7 Fail-open behavior summary (state table)

How the rail responds to each loss-of-permission event. "Rail" = `RELAY_ENABLE_RAIL`
live? "Coils" = can any motion relay energize?

| Event | Mechanism | Rail | Coils |
|---|---|---|---|
| Pi process hangs / dies (no kicks) | NE555 times out → Q13 off → gate AND open | dead | drop |
| Pi de-asserts ARM (`ARM_PERMIT` low) | Q15 base low (R108) → Q15 off → gate AND open | dead | drop |
| RP2040 unpowered / in reset / BOOTSEL | `GP2` Hi-Z → R110 100 k holds Q16 base low → Q16 off | dead | drop |
| RP2040 firmware crash / loop hang | RP2040 internal WDT resets chip → GP2 Hi-Z → as above | dead | drop |
| Enabled RP2040 cam-stop violation / motion max-run timeout | firmware drives `GP2` LOW → Q16 off (condition 4 via 3); stock v1.2.3 has measured-cam flags OFF but max-run active | dead | drop |
| TB/SC collision state (Candidate C) | both levers BACK/open in the powered-proven OEM ladder; correct board insertion leaves the commanded S or T coil dead | rail may remain live | affected S/T coil blocked; must be proven per lane at G3 |
| Current lane-21/22 field harness | J14.3↔4 is OPEN/unlanded → FET source dead | dead | drop; deliberate no-arm hold |
| Validated future external control-power / optional pit-interlock interface opens | J14.3↔4 source path broken → FET source dead | dead | drop; still requires separate end-to-end demand proof |
| Board powers up (pre-init) | GP2 Hi-Z + ARM low + no kicks → all three defaults off | dead | drop |
| Welded relay contact | rail still drops coils, **but** weld holds the contact | dead | **welded contact stays made → master breaker required (§10.6)** |
| Board conditions true and an approved 3–4 interface is closed | Q15·Q16·Q13 conduct → gate low → P-FET on; Candidate-C jumper + approved external source interface closed | **live** | Pi's OUT-A bit can energize a board relay; S/T still require the OEM ladder to permit their machine coils |

The firmware (`firmware/rp2040/README.md` "Safety model") states the same invariant
from the Pico side: GP2 is driven LOW first thing in `main()`, then HIGH only after
`BOOT_SETTLE_MS` (200 ms) and only while no fault; telemetry/UART never block the
RP_OK drive or the watchdog kick; a dead UART cannot produce a false permit.

---

### 10.8 Test points and bench bring-up

The contract requires the watchdog and rail to be **observable** (spec §4.3, §9, §11,
§12.9). Probe these nets (test pads were added at board placement — the route doc and
spec record **16 test pads** total, and call out `TP16` on `RELAY_ENABLE_RAIL`):

| Probe / net | What you are watching | Healthy reading |
|---|---|---|
| `RELAY_ENABLE_RAIL` (TP16) | The gated coil supply rail | ≈ +5 V only when the implemented on-board conditions are true; this reading does **not** prove Candidate-C TB/SC insertion |
| `RAIL_GATE` | P-FET gate | Pulled to source (≈ +5 V, FET off) by default; near GND when the AND chain conducts (FET on) |
| `NE555_TRIG` (U36 pin 2) | Watchdog trigger | Held high by R101; pulsed low by each Pi kick |
| `NE555_OUT` (U36 pin 3) | Watchdog output | Toggles with kicks; reverts (→ Q13 off) on missed kicks |
| `WDOG_OK_PULLDOWN` | Bottom of the AND chain (Q13 drain) | Pulled to GND only while Q13 conducts (watchdog OK) |
| `SAFE_STOP_RETURN` (Q14 source) | After both J_SAFE positions | ≈ +5 V only when Candidate-C jumper and an approved 3–4 interface are closed; current field harness should read dead |
| `RP2040_OK` (GP2 / J1 pin 13) | RP2040 health/permission | HIGH = permit, LOW = drop (also drops on timeout or an enabled enforcement fault) |
| `ARM_PERMIT` (J1 pin 8) | Pi arm GPIO | HIGH only after operator-safe/zeroed state |
| `WDOG_KICK` (J1 pin 7) | Pi kick into Q12 | periodic pulses while the Pi is alive |

> **Direct rail-feedback limitation.** The four Rev-D diagnostic taps observe
> `NE555_OUT`, `WDOG_KICK`, `ARM_PERMIT`, and `RP2040_OK`; none is an electrical
> feedback input from `RELAY_ENABLE_RAIL` / TP16. Software can therefore diagnose
> permission-source disagreements, but it cannot independently distinguish a
> stuck-open or stuck-on Q14/J14/output rail from the commanded predicate state.
> Keep new sensing copper off the frozen Rev-D board unless a dedicated,
> observe-only FMEA is completed. If the production hazard analysis requires
> direct rail verification, use a qualified external, protected, galvanically
> isolated voltage monitor with a dry diagnostic contact (including
> stuck-healthy proof), or carry the function into a future board revision.

**Bench bring-up order** (do this on a **locked-out / off-live** machine only —
spec §12.9, firmware README §"Bench bring-up"):

1. **Power + boot, rail externally safe.** Power board logic only. Confirm RP2040
   `boot` + ~4 Hz `hb` with `ok:1` after ~200 ms; GP2 reads HIGH on a meter once
   healthy.
2. **Watchdog drop.** On the off-machine bench only, close 3–4 with the controlled
   bench jumper, then with ARM asserted and a known-good RP2040 start Pi kicks and
   confirm the rail comes up; **stop the kicks** and confirm the rail drops within
   the timeout. Also pull power to just the Pico → GP2 → LOW → rail drops (`boot`
   with `wdt_reset:1` if you force a hang).
3. **Arm drop.** De-assert `ARM_PERMIT` → Q15 off → rail drops.
4. **Connector-position checks.** With the machine disconnected and only dummy loads,
   open J_SAFE1-2 and then the bench-only J_SAFE3-4 jumper independently → FET
   source dead → rail drops. Remove the 3–4 bench jumper before any machine
   connection. These checks validate PCB/source wiring only. **Candidate-C proof is
   separate and live/per-lane. Upstream power-removal proof is also separate:** on
   lanes 21/22, actuate Stop and require both OEM master/control-power drop and
   board-rail drop after the reviewed external interface is installed; record
   C.I.S. as **N/A — device absent**. Inspect/ask the mechanic about any other
   automatic pit-entry interlock and test it separately if present. If none exists,
   installation of a new interlock versus an explicit owner and qualified
   machine-safety decision must be closed before motion.
5. **Motion-timeout drop; enabled-cam tests only under a qualified release.** Send
   `RUN S` to the RP2040 and withhold `STOP S` past `MAX_MOTION_MS` (8 s) → expect
   `flt:motion_timeout` and GP2 → LOW → rail drops; `CLEAR` → GP2 back HIGH (from a
   known-safe zero/ready state only). Do not claim a per-cam drop until measured
   polarity is enabled in a controlled release and its dedicated bench gate passes.
6. **Each relay with a dummy load**, then — only after all of the above pass — the
   machine harness.

Cross-references: §9 (Output Contract / relay topology), §19 (Safety Model — TB/SC
interlock, installed Stop/master breaker, OEM C.I.S. history, power-down rule), §8 (Input Contract — cams that
feed the RP2040 cam-stop), §7 (Controller Interface — MCP23017 OUT-A relay bits,
RP2040 UART), and the RP2040 firmware section for the `RP2040_OK`/cam-stop semantics.
