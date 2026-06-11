# Phase 8 — Lane-Node I/O Board Spec (rev B, integrated)

**What this is:** the electronics spec for the board that lets one Raspberry Pi read every 82-70 machine input and drive every machine output for a lane-pair — i.e. the hardware that runs `cycle_control_8270.py` against a real machine. This is the **rev B** board: it folds the opto-in + relay-out channels onto the already-bench-validated **NE555 watchdog + AC-interposer** board (task #21).

**Read with:** `phase8_controller_interface_MAP.md` (the signal contract), `phase8_controller_interface_fieldsheet.md` (exact-pin lock-in at the bench), `phase8_8270_SYSTEM_REFERENCE.md` (full system spec), `phase8_C1_C2A_pinout_p288.md` (connector extraction).

> **Scope honesty:** this spec fixes the *channel architecture* (counts, electrical domains, bus, safety, power) — which is what gates the PCB. Exact C1/C2A pin numbers are bench-verified separately (fieldsheet) and do **not** change the board design, only the harness. Anything not yet confirmed is marked `# CONFIRM`.

---

## 0. Design goals
1. **One board per lane-pair** drives/reads **both decks** (mirrors one-Pi-per-pair + one-camera-per-pair). Channel counts below are **per lane**; the board carries **2×** (one set per deck) — OR we run two stacked single-lane boards. See §9 decision.
2. **Galvanic isolation** between the 82-70 machine (115 VAC / 24 VAC / dirty switch rails) and the Pi (3.3 V). Optos in, relays/SSR out. The Pi never shares a ground with the motor rails.
3. **Fail-safe-off**: on Pi death, power loss, or watchdog timeout, **all motor relays drop**. Motion only resumes after a deliberate operator "First Ball Zero" (SYSTEM_REFERENCE §5 power-down rule).
4. **Hardware safety stays in hardware** — the TB+SC interlock, stop/CIS → master breaker, and regenerative braking are NOT on this board and are never bypassed by it (§6).
5. **Beginner-buildable + Codex-auditable** — through-hole-friendly where it matters, explicit part numbers, current budgets, and test points.

---

## 1. Channel inventory (per lane/deck)

### Inputs the Pi reads (≈28)
| # | Signal | Count | Source connector | Electrical domain | Latency class |
|---|---|---|---|---|---|
| 1 | **SS / DIELL** cushion start (ball delivered) | 1 | DIELL (our lanes) | 16 V rest → 0.7 V broken, **NPN active-low** (characterized) | **FAST** (cycle trigger) |
| 2 | Cams **SA, SB, SC, TA1, TA2, TB** | 6 | A&MC plug → C2A | switch to common; **5 VDC / 24 VAC** rail `# CONFIRM` per cam | **FAST** (cam-position motor stops) |
| 3 | Grippers **GS1–GS10** | 10 | **TAC strip** (TAC-1…10 + TAC-GND) → C2A | dry contact to TAC-GND | SLOW (read once at TA2 latch) |
| 4 | **GP** gripper-protect | 1 | A&MC → C2A | switch | SLOW (gates 3 s delay) |
| 5 | **OS** off-spot | 1 | A&MC → C2A | switch | SLOW |
| 6 | **BS** bin/#9 | 1 | A&MC → C2A | switch | SLOW |
| 7 | **PBZ** zero / 1st-2nd / manual-intervention | 1 | pushbutton → C2A (`PBZ-2`) | momentary to gnd | SLOW (edge) |
| 8 | **PBC** cycle | 1 | pushbutton → C2A (`PBC-2`) | momentary to gnd | SLOW (edge) |
| 9 | **10th-frame** | 1 | C2A | switch | SLOW |
| 10 | **Foul** (Radaray) | 1 | foul detector | dry contact / open-collector `# CONFIRM` | SLOW (edge) |
| 11 | **manual T, S, SWS, SWSR** service | 4 | C2A (`SWS-4`, `T-2`, `S-1/S-4`…) | switches | SLOW (edge) |

**Input total ≈ 28** → **7 FAST** (SS + 6 cams), **21 SLOW**.

### Outputs the Pi drives (≈22)
| # | Signal | Count | Load | Drive element |
|---|---|---|---|---|
| 1 | Relays **M, BE, S, T, SP, M1, M2** | 7 | 24 V coils → switch 115 VAC motors/solenoids | **AEDIKO relay board** (on hand) via opto/ULN |
| 2 | **Pin lamps 1–10** | 10 | 12 VDC via D1–D10 (KX gates pin data to scorer) | SSR / logic-MOSFET — **OPTIONAL** (Track A camera supplies pin data; populate only if we keep the physical mask pindicator) |
| 3 | **Status lamps** 1st/2nd/foul/strike | 4 | 12 VDC (mask PM-E24/E25/E27/E26) | logic-MOSFET / ULN |
| 4 | **Neon** mask | 1 | ~125 VAC / −160 VDC | SSR — OPTIONAL (mask display) |

**Output total ≈ 22** (12 *mandatory* if masks are camera-driven: 7 relays + 4 status + neon; +10 pin lamps if physical mask retained).

> **Budget reconciliation:** source docs quote "~45 ch (≈23 in + 22 out)". Itemized here = **≈28 in + ≈22 out ≈ 50**. Size the board for **32 in + 24 out per deck** with headroom. The "trims outputs" note (SYSTEM_REFERENCE §7): camera pin-data can replace the 10 pin-lamp drives → mandatory outputs drop to ~12.

---

## 2. Architecture (the big picture)

```
                    82-70 MACHINE SIDE  (isolated)        |        PI SIDE (3.3 V logic)
  cams SA..TB ──┐                                         |
  SS/DIELL ─────┤  FAST inputs → conditioned front-ends → | → direct Pi GPIO (IRQ) + RP2040 co-proc
                │                                          |     (hard-real-time cam-stop timing)
  GS1..10 ──────┤                                         |
  GP/OS/BS ─────┤  SLOW inputs → opto-isolator banks ───  | → MCP23017 #0/#1 (INT-driven), I2C
  PB/foul/man ──┘  (AL-ZARD 8ch optos, on hand)           |
                                                           |
  M,BE,S,T,SP,  ← AEDIKO relays  ← ULN2803 ← opto ──────── | ← MCP23017 #2 (outputs), I2C
  M1,M2                                                    |        ALL relay-enable gated by:
  pin/status     ← SSR/MOSFET   ← opto ─────────────────  | ← MCP23017 #3 (outputs), I2C
  lamps                                                    |
                                                           |
            HARDWARE SAFETY (NOT on Pi path):              |   NE555 WATCHDOG (on board):
            TB+SC interlock ‖ in 24 V relay-control path   |   Pi kicks GPIO12 < ~10 s →
            Stop/CIS → master breaker                      |   else relay-enable rail dropped
            Regenerative braking on relay N.C. contacts    |   (drops M/S/T/SP/M1/M2)
```

### Two-tier inputs (the key decision)
- **FAST lane (7 ch):** SS + the 6 cams gate **motor stops at exact cam positions** — latency- and jitter-critical. I2C-polled MCP23017 (ms-scale, bus-contended) is **too slow/uncertain** for this. Route the cams + SS to **direct Pi GPIO with edge interrupts**, AND mirror them to an **RP2040/RP2350 (or ATmega) co-processor** that enforces the cam-stop → relay-drop in hard real time, independent of Pi scheduling jitter. (SYSTEM_REFERENCE §7: "MCU co-processor for cam-stop timing.")
- **SLOW lane (21 ch):** grippers (sampled once at the TA2 260° latch), pushbuttons, GP/OS/BS, foul, manual, 10th — read over **MCP23017 with its INT pin** wired to a Pi GPIO so we get change-interrupts instead of polling.

### Isolated outputs
- 7 relay coils via the **AEDIKO relay board** (bench-validated), each fed through an opto + ULN2803 channel so the Pi GPIO never sees coil flyback or the 24 V rail.
- Lamp banks via opto + logic-level MOSFET (12 V) or SSR (neon 125 VAC).
- **Relay-enable rail** for all motion relays passes through the **NE555 watchdog contact** AND a Pi "arm" GPIO — both must be live to energize any motor relay.

---

## 3. Input subsystem detail

**Universal slow-input front-end (per channel):** machine switch closes to its common → drives the **input opto LED** through a domain-sized resistor → phototransistor pulls the MCP23017 pin low (MCP internal/external pull-up to Pi 3.3 V). Dry-contact baseline; works for all the switch-type inputs.
- DC switch rails (5 VDC): series R = (Vrail − Vf)/I_led, target ~5 mA → ~680 Ω for 5 V. `# CONFIRM` rail per pin at bench.
- 24 VAC rails: add a series diode + ~3.3 kΩ + the opto's reverse-protection (or use AL-ZARD inputs, which already tolerate this) — this is the **same path already validated** for DIELL (1N4007/10 µF interposer → AL-ZARD → Pi).
- **Make the front-end jumper-selectable** DC-dry-contact ↔ AC/voltage-sense per channel, because we won't know each pin's exact rail until the fieldsheet bench pass.

**FAST inputs (SS + cams):** same opto isolation, but the phototransistor goes to **(a)** a direct Pi GPIO (IRQ) **and (b)** an RP2040 GPIO. Keep these traces short; add RC debounce (~1 kΩ + 100 nF) sized so it doesn't blunt the cam edge. SS/DIELL uses its **already-proven AL-ZARD channel** (no redesign).

**Gripper strip (GS1–GS10):** the TAC strip presents the 10 grippers as dry contacts to TAC-GND → 10 opto inputs on MCP23017 #0. Clean 10-in cluster from one connector.

**Pull/debounce:** all SLOW switch inputs get firmware debounce (existing `lane_node.py` pattern). Mechanical cams get the hardware RC above.

---

## 4. Output subsystem detail

| Bank | Channels | Driver | Supply | Notes |
|---|---|---|---|---|
| Motion relays | M,BE,S,T,SP,M1,M2 (7) | opto → ULN2803 → **AEDIKO relay coil** | 24 V (machine T3/T4 or dedicated) | **enable-gated by watchdog + arm GPIO** |
| Status lamps | 1st/2nd/foul/strike (4) | opto → logic MOSFET (e.g. AO3400-class) or ULN2803 | 12 V | low current |
| Pin lamps | 1–10 (10, optional) | opto → MOSFET/SSR + series D1–D10 | 12 V | OMIT if camera drives mask data |
| Neon | 1 (optional) | SSR (e.g. random-fire) | 125 VAC | mask only |

- **Flyback/snubber** on every relay coil (the ULN2803 has built-in clamp diodes; AEDIKO board has its own — verify, `# CONFIRM`).
- **BE relay** runs continuously while "in bowl" — but still drops on watchdog/power-loss (fail-safe-off).
- **Spot (SP)** is a solenoid — size the ULN channel / relay for solenoid inrush.

---

## 5. Bus & addressing

| Device | Role | I2C addr | INT → Pi GPIO |
|---|---|---|---|
| MCP23017 #0 | inputs: GS1–GS10 + GP/OS/BS (13) | 0x20 | GPIO23 `# CONFIRM` |
| MCP23017 #1 | inputs: PBZ/PBC/foul/10th/manual (8) + spare | 0x21 | GPIO24 `# CONFIRM` |
| MCP23017 #2 | outputs: 7 relays + spares | 0x22 | — |
| MCP23017 #3 | outputs: 4 status + 10 pin lamps + neon | 0x23 | — |
| RP2040 co-proc | FAST cams+SS, cam-stop enforcement | (I2C/SPI/UART link to Pi) `# CONFIRM` | dedicated IRQ lines |

- 4× MCP23017 = 64 GPIO on one I2C bus (addr 0x20–0x23 via A0/A1/A2 strapping). Pi runs MCP23017 at **3.3 V** so its I/O is directly Pi-compatible (no level shifter on the Pi side; isolation is on the *machine* side via optos).
- I2C at 400 kHz. Add **bus pull-ups** (4.7 kΩ) once on the board.
- **Per-deck:** duplicate the input MCP pair for deck 2 at 0x24/0x25 (A2 strap), outputs at 0x26/0x27 — OR two single-lane boards (§9).

---

## 6. Safety integration (PRESERVE — do not put on the Pi path)

1. **NE555 hardware watchdog (on board, bench-validated):** Pi pulses **GPIO12** (`watchdog_kick_loop`, WS-independent — see daemon fix 2026-05-29). Miss the kick (~10 s) → 555 output drops the **relay-enable rail** → all motion relays open. `relay_cleanup.py` also drives GPIO12 low on shutdown.
2. **TB + SC interlock (hardware, off-board):** the two cam switches **in parallel** in the **24 V relay-control path** drop both motor relays on a table↔sweep collision course. The board's relay coils sit *downstream* of this interlock so it can always kill them. **Never route motor power around it.**
3. **Stop switch + C.I.S. → master breaker (hardware):** cuts all control. Off-board.
4. **Regenerative braking** on relay N.C. contacts + caps — hardware, in the motor wiring. The board's relays must use the **same N.C.-brake contact arrangement** the machine expects `# CONFIRM` against p287/p290.
5. **Power-down rule (firmware + this rail):** after any 115 VAC loss in "Bowl", the **arm GPIO stays de-asserted** on restore → no motion until operator presses **PBZ (First Ball Zero)**. Implemented in `cycle_control_8270.py` MANUAL_INTERVENTION/POWER_OFF states; the board enforces it because the arm GPIO + watchdog both gate the relay-enable rail.

**Relay-enable rail logic:** `MOTOR_RELAYS_ENABLED = watchdog_ok AND pi_arm_gpio AND (hardware TB/SC interlock closed) AND master-breaker-on`. All four required. Any one drops the motors.

---

## 7. Power tree
- **Pi 5 V** (its own supply; the board does not back-power the Pi).
- **3.3 V** for MCP23017s + RP2040 (from Pi 3V3 or a local LDO if current demands — 4× MCP23017 is light).
- **Isolated input-sense supply(ies)** referenced to machine common(s) — may be multiple commons (5 VDC logic vs 24 VAC); keep each opto's LED side on the machine-domain ground, phototransistor side on Pi 3.3 V.
- **24 V** relay-coil rail (machine T3/T4 tap or dedicated 24 V brick) — feeds AEDIKO coils only, isolated from Pi.
- **12 V** lamp rail.
- **125 VAC** neon (mask) — off-board / SSR-switched.
- **Decouple** every IC (100 nF) + bulk caps per rail.

---

## 8. Connector mapping to C1/C2A
- **C2A (50-pin, switches/control)** → the **input** side: A&MC plug (cams + GP/OS/BS), TAC strip (GS1–10), pushbuttons (PBC/PBZ), SWS/S/SWBE, 10th, foul. See `phase8_C1_C2A_pinout_p288.md` for the extracted wire map; **exact pins per fieldsheet bench pass.**
- **C1 (34-pin, motor/relay + power)** → the **output** side: motor relays M/BE/S/T/SP/M1/M2 + power. Mostly terminal-strip wiring (`T.S-xx`).
- The board exposes **two field connectors** (a C2A-facing input header, a C1-facing output header) so it drops onto the existing harness via an **interposer**, leaving the machine harness reversible (Plan A reversibility).

---

## 9. BOM & packaging
**On hand (reuse):** Raspberry Pi (lane node) · **AL-ZARD 8-ch opto-isolator boards** (input isolation, DIELL path proven) · **AEDIKO relay boards** (motion outputs) · **NE555 watchdog** (built + bench-tested) · **AC interposer** (1N4007/10 µF, proven on DIELL/24 VAC).
**To source:** 4× **MCP23017** · 1× **RP2040** (Pico or bare) for cam-stop co-proc · ULN2803A ×2 · logic MOSFETs / SSRs for lamps + neon · headers/Phoenix terminals · passives (R/C, bus pull-ups, snubbers) · per-channel jumpers for DC/AC input mode.

**Packaging decision — ✅ DECIDED (Dylan, 2026-05-31): Option B + self-contained refinements.**
- **Option B — two identical single-lane boards** on one Pi: bring up one board fully, clone. Each board is **self-contained**: its own RP2040 (owns the fast cam/ball inputs + enforces cam-stops in hardware + forwards events to the Pi), its own I²C bus (repeats 0x20–0x23), its own relay-enable rail + arm GPIO. See **`phase8_channel_allocation.md` §6** for the three adopted refinements + the full per-pin map. This is what PCB rev-B (#21) lays out.
- ~~Option A (one dual-deck board, shared bus 0x20–0x27)~~ — rejected: couples the lanes, zero address headroom, denser layout.

---

## 10. Build & bring-up plan (safe order — no motors until last)
1. **Board bring-up, no machine:** power, I2C scan (see 0x20–0x23), blink each output channel into LEDs, toggle each input with a test switch. Confirm watchdog drops the relay-enable rail on kick-stop.
2. **Reads-only on the spare cabinet:** wire C2A inputs through the optos; cycle the machine **by hand**; confirm every cam/gripper/switch reads correctly in `lane_node.py`. Fill the fieldsheet (exact pins + levels). **No outputs connected.**
3. **Lamps only:** drive status + pin lamps; verify against machine state. Still no motors.
4. **FSM in sim → co-proc cam-stop bench test:** prove the RP2040 drops a *dummy* relay at the exact cam edge before trusting a motor.
5. **Motors in isolation, machine locked-out otherwise:** one relay at a time, on a **locked-out** machine with the hardware interlock verified live, one hand behind back. (#17 off-live validation.)
6. **Full off-live cycle** → soak → cutover (#15 run-of-show).

---

## 11. Open items / `# CONFIRM`
- Exact C2A/C1 pin numbers + each input's rail (5 VDC vs 24 VAC vs dry) → **fieldsheet bench pass**.
- A&MC plug → cam mapping (which A&MC pin = SA/SB/SC/TA1/TA2/TB + GP/OS/BS) → **crop page 289** (`C2A-GS-*`, `C2A-14R` functional labels) + bench.
- RP2040 ↔ Pi link (I2C peripheral vs SPI vs UART) + exact cam-stop hand-off protocol.
- AEDIKO board: built-in flyback? coil voltage? contact rating vs motor inrush.
- Whether masks stay physical (drive 10 pin lamps) or go camera-driven (omit) — **trims 10 outputs**.
- Dual-deck shared vs independent outputs (does the pair share any relay/rail?) → p287/p290.
- Confirm regenerative-brake N.C. contact arrangement is preserved by AEDIKO relay wiring.
