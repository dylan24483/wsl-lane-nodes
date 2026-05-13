# Phase 8a PCB Design Spec — Unified Watchdog + AC Interposer Board

**Status:** schematic-ready spec, derived from bench-validated topologies (NE555 watchdog: 2026-05-11; 1N4007/10µF AC interposer: 2026-05-11).
**Target fab:** JLCPCB, 2-layer, ~50×70mm, SMT-assembled, screw terminals through-hole.
**Quantity:** 20 boards (16 for lane pairs + 4 spares).

This document is the input to EasyEDA schematic capture. Every net, pin, and component below is named with a reference designator. Read top-to-bottom and transcribe into EasyEDA mechanically — nothing in here requires a design decision, all decisions already happened on the bench.

---

## 1. Board purpose (one paragraph)

One PCB per lane pair, sits in the DIN-rail enclosure alongside the Pi, AEDIKO 8-channel relay HAT, and AL-ZARD DST-1R8P-P opto-input module. The board does two jobs:

1. **Watchdog** — gates the AEDIKO relay-coil supply's GND return. As long as the Pi pulses GPIO 12 every ~1 sec, the NE555 monostable holds Q2 ON and relays have a current path. If kicks stop for >10s (kernel panic / SIGKILL / power loss / asyncio deadlock), Q2 opens and all 8 relays mechanically default to OPEN, regardless of what the AEDIKO IN pins say.
2. **AC interposer (4 channels)** — half-wave rectifies + smooths the 24VAC field signals (foul lamp + 2nd-ball lamp, one of each per lane × 2 lanes = 4 channels) into ~25-30V DC that the AL-ZARD selector input (24V tolerance) reads cleanly. Each channel is galvanically independent from the others and from the watchdog 5V supply — no shared L2 return on the PCB.

Digital lane control signals (Pi GPIO → AEDIKO IN, AL-ZARD O → Pi GPIO) do NOT transit this board. Those run on separate ribbon cables from Pi GPIO header directly to the AEDIKO/AL-ZARD modules.

---

## 2. Block diagram

```
                        +5V DC SUPPLY
                              │
                  TB_PWR_IN ──┴── VCC_5V net (5V rail) ─────────────────────┐
                                                                            │
                                                                            ├──► IC1 NE555 VCC + RESET
                                                                            ├──► R1 timing pullup
                                                                            ├──► R2 TRIG pullup
                                                                            ├──► C2 bypass
                                                                            ├──► R9 → LED2 (power-good)
                                                                            ├──► R8 → LED1 (wd-healthy)
                                                                            └──► TB_AEDIKO_PWR.1 (V+ to AEDIKO direct)

                          ┌──── KICK net (Pi GPIO 12) ────►  R3 ──► Q1.gate
   PI HEADER ─ TB_KICK ───┤                                              R4 pull-down to GND
                          └──── GND ref                                  Q1.source → GND
                                                                         Q1.drain → diode-OR node

   diode-OR node ─► D1.K (D1.A = TIMING_NODE = Vc1 = NE555 THRES/DISCH)
                 └► D2.K (D2.A = NE555_TRIG)

   NE555 OUT (IC1.3) ──► R6 ──► Q2.gate
                                R7 pull-down to GND
                                Q2.source → GND
                                Q2.drain → COIL_GND_RETURN net
                                            │
                                            ├──► TB_AEDIKO_PWR.2 (V− return to AEDIKO)
                                            └──► LED1.K  (anode at VCC via R8)

   ┌─ AC channel 1 ─────────────────────────────────────┐
   │  TB_AC_IN_CH1.1 (24VAC L1) ─► DA1.A                │
   │                              DA1.K ─► CA1.+ ──► TB_DC_OUT_CH1.1
   │  TB_AC_IN_CH1.2 (24VAC L2) ────────► CA1.− ──► TB_DC_OUT_CH1.2
   └────────────────────────────────────────────────────┘
   (repeat 3×: channels 2, 3, 4 — each with its own pair-isolated return)
```

---

## 3. Function block detail

### 3a. NE555 watchdog (retriggerable monostable, "kick to stay alive")

Topology rationale (recap of bench finding): standard NE555 monostable fires OUT HIGH on a falling TRIG edge and holds HIGH for `T_OUT = 1.1 × R1 × C1`. With R1=100kΩ, C1=100µF → **T_OUT ≈ 11 seconds**. Retriggering is achieved by Q1 (driven by Pi GPIO 12 through R3) pulling BOTH the TIMING_NODE (THRES/DISCH) AND the TRIG pin to ground simultaneously, via diode-OR isolation (D1, D2). Pi's 1Hz kick rate ⟹ NE555 sees a fresh trigger every second, OUT stays HIGH continuously. Stop kicks ⟹ TIMING_NODE charges through R1 toward Vcc, hits 2/3 Vcc threshold after ~11s, OUT goes LOW, Q2 opens, relay coils lose return path.

**The R_pullup on TRIG (R2) is critical.** Without it, leaving TRIG tied only to Q1.D via D2 means TRIG floats low when Q1 is OFF, causing the NE555 to free-run as an astable oscillator. R2 holds TRIG HIGH at idle so the monostable rests in its expected state. (Discovered during bench validation, 2026-05-11.)

### 3b. Output stage (Q2 low-side switch on AEDIKO V− return)

N-channel MOSFET (AO3400 SOT-23) gates the AEDIKO PWR V− return path. AEDIKO V+ is wired direct to VCC_5V. When NE555 OUT is HIGH, Q2 conducts, completing the return circuit. When NE555 OUT is LOW (timeout), Q2 opens — relay coils have no current path, all relays mechanically open.

**Why low-side, not high-side:** an N-MOSFET cannot fully saturate as a high-side switch from a 5V rail (Vgs collapses to 0 as source rises). Low-side switching keeps Vgs = Vcc = 5V when ON, AO3400 saturates fully (Rds(on) ~28mΩ at Vgs=4.5V).

**Continuous current:** AEDIKO 8 relays × ~70mA/coil = 560mA worst case. AO3400 rated 5.7A. Power dissipation: I²×R = 0.56² × 0.028 = 8.8mW. SOT-23 rated ~0.5W. Massive thermal margin.

### 3c. AC interposer (4 independent channels)

Each channel: 1× 1N4007 (M7 SMA) half-wave rectifier in series with the L1 line, 1× 10µF/50V aluminum electrolytic across DC+ and DC−. L2 ties directly to DC− (no rectification on the return).

**Voltage math** (verified at bench 2026-05-11):
- AC source measured at lane 22: ~28V RMS, ~40V peak
- After half-wave rectify, no-load: ~40V DC at the cap
- Loaded (AL-ZARD draws ~11mA): ~25-30V DC with ~10-15V ripple at 60Hz
- AL-ZARD selector input (24V tolerance, 10-40V AC/DC spec): triggers PC817 LED reliably across the ripple band

**Cap rating:** 50V minimum. The ~40V peak is at the top of a 50V cap's safe operating area with ~25% margin. Don't downgrade to 35V — bowling alley AC bus can spike when inductive loads switch.

**No shared L2 across channels.** Westside foul + 2nd-ball AC bus topology is unknown; safest design is to keep each channel's return floating relative to the others and to the watchdog GND. AL-ZARD's per-channel galvanic isolation (PC817 inside) handles any potential differences downstream.

### 3d. Indicator LEDs (field-service aid)

- **LED2 (power-good, green):** VCC → R9 → LED2.A → LED2.K → GND. Lit when 5V supply is present. Field service can verify supply without a multimeter.
- **LED1 (watchdog-healthy, green or amber):** VCC → R8 → LED1.A → LED1.K → COIL_GND_RETURN. Lit when Q2 is conducting (i.e., NE555 OUT HIGH = kicks healthy). Goes dark when watchdog times out. Pi-down ⟹ LED1 dark — instant visual diagnostic.

---

## 4. Complete net list

Net names use UPPER_SNAKE. Each line lists every pin on that net.

| Net | Pins on this net |
|---|---|
| `VCC_5V` | TB_PWR_IN.1, IC1.4, IC1.8, R1.1, R2.1, C2.1 (+), R8.1, R9.1, TB_AEDIKO_PWR.1 |
| `GND` | TB_PWR_IN.2, IC1.1, C1.2 (−), C2.2 (−), R4.2, R7.2, Q1.S, Q2.S, LED2.K, TB_KICK.2 |
| `KICK` | TB_KICK.1, R3.1 |
| `Q1_GATE` | R3.2, R4.1, Q1.G |
| `Q1_DRAIN` | Q1.D, D1.K, D2.K |
| `TIMING_NODE` | IC1.6 (THRES), IC1.7 (DISCH), R1.2, C1.1 (+), D1.A |
| `NE555_TRIG` | IC1.2, R2.2, D2.A |
| `NE555_OUT` | IC1.3, R6.1 |
| `Q2_GATE` | R6.2, R7.1, Q2.G |
| `COIL_GND_RETURN` | Q2.D, TB_AEDIKO_PWR.2, LED1.K |
| `LED1_ANODE_DRIVE` | R8.2, LED1.A |
| `LED2_ANODE_DRIVE` | R9.2, LED2.A |
| `IC1.5` (NE555 CTRL) | leave open OR add optional CFILT 10nF MLCC to GND for noise immunity (recommended) |
| AC channel 1: `AC_CH1_L1` | TB_AC_IN_CH1.1, DA1.A |
| AC channel 1: `DC_CH1_POS` | DA1.K, CA1.+, TB_DC_OUT_CH1.1 |
| AC channel 1: `CH1_RETURN` | TB_AC_IN_CH1.2, CA1.−, TB_DC_OUT_CH1.2 |
| AC channel 2: `AC_CH2_L1` | TB_AC_IN_CH2.1, DA2.A |
| AC channel 2: `DC_CH2_POS` | DA2.K, CA2.+, TB_DC_OUT_CH2.1 |
| AC channel 2: `CH2_RETURN` | TB_AC_IN_CH2.2, CA2.−, TB_DC_OUT_CH2.2 |
| AC channel 3: `AC_CH3_L1` | TB_AC_IN_CH3.1, DA3.A |
| AC channel 3: `DC_CH3_POS` | DA3.K, CA3.+, TB_DC_OUT_CH3.1 |
| AC channel 3: `CH3_RETURN` | TB_AC_IN_CH3.2, CA3.−, TB_DC_OUT_CH3.2 |
| AC channel 4: `AC_CH4_L1` | TB_AC_IN_CH4.1, DA4.A |
| AC channel 4: `DC_CH4_POS` | DA4.K, CA4.+, TB_DC_OUT_CH4.1 |
| AC channel 4: `CH4_RETURN` | TB_AC_IN_CH4.2, CA4.−, TB_DC_OUT_CH4.2 |

**Total net count:** 12 watchdog/output + 3 nets × 4 AC channels = 24 nets.

---

## 5. BOM

All parts SMT except screw terminals (through-hole, 5.08mm pitch). LCSC codes are *suggestions* — verify Basic-vs-Extended status and stock when ordering. Where I've flagged **Extended**, expect the JLCPCB assembly fee to be ~$3 for the first Extended part on the BOM and ~$0.30 per additional Extended type.

| RefDes | Qty | Description | Package | Value/Rating | Suggested LCSC | JLC tier |
|---|---|---|---|---|---|---|
| IC1 | 1 | NE555 timer | SOIC-8 | — | C7593 (TI NE555DR) | Basic |
| Q1 | 1 | N-MOSFET, logic-level | SOT-23 | 30V, 5.7A, Vgs(th) ≤1.3V | C20917 (AO3400A) | Basic |
| Q2 | 1 | N-MOSFET, logic-level | SOT-23 | 30V, 5.7A, Vgs(th) ≤1.3V | C20917 (AO3400A) | Basic |
| D1 | 1 | Switching diode | SOD-123 | 100V, fast | C2128 (1N4148W) | Basic |
| D2 | 1 | Switching diode | SOD-123 | 100V, fast | C2128 (1N4148W) | Basic |
| DA1..DA4 | 4 | Rectifier, AC interposer | SMA (DO-214AC) | 1000V, 1A | C95872 (M7 / 1N4007 SMA) | Basic |
| CA1..CA4 | 4 | Aluminum electrolytic, AC smoothing | SMD radial 5×5.4mm or 6.3×7.7mm | 10µF, **50V minimum** | verify on order; ChengX/Lelon family, ~C44627 candidates | likely Extended |
| C1 | 1 | Aluminum electrolytic, NE555 timing cap | SMD radial 6.3×5.4mm | 100µF, 16V | C16133 | Basic |
| C2 | 1 | MLCC, NE555 V+ bypass | 0805 | 0.1µF, 50V, X7R | C49678 | Basic |
| CFILT (optional) | 1 | MLCC, NE555 CTRL pin filter | 0805 | 10nF, 50V, X7R | C1633 | Basic |
| R1 | 1 | Timing resistor | 0805 | 100kΩ, 1% | C17407 | Basic |
| R2 | 1 | TRIG pullup | 0805 | 10kΩ, 1% | C17414 | Basic |
| R3 | 1 | Q1 gate series | 0805 | 1kΩ, 1% | C17513 | Basic |
| R4 | 1 | Q1 gate pulldown | 0805 | 10kΩ, 1% | C17414 | Basic |
| R6 | 1 | Q2 gate series | 0805 | 1kΩ, 1% | C17513 | Basic |
| R7 | 1 | Q2 gate pulldown | 0805 | 10kΩ, 1% | C17414 | Basic |
| R8 | 1 | LED1 current limit | 0805 | 470Ω, 1% | C17554 | Basic |
| R9 | 1 | LED2 current limit | 0805 | 470Ω, 1% | C17554 | Basic |
| LED1 | 1 | Indicator LED, watchdog-healthy | 0805 | green | C72043 | Basic |
| LED2 | 1 | Indicator LED, power-good | 0805 | green (or red, distinguish from LED1) | C72043 / C2286 | Basic |
| TB_PWR_IN | 1 | Screw terminal, 5.08mm, 2-pos | THT | 12A, 300V | C8463 (KF128-5.08-2P) | Extended |
| TB_AEDIKO_PWR | 1 | Screw terminal, 5.08mm, 2-pos | THT | same | C8463 | Extended |
| TB_KICK | 1 | Screw terminal, 5.08mm, 2-pos | THT | same | C8463 | Extended |
| TB_AC_IN_CH1..CH4 | 4 | Screw terminal, 5.08mm, 2-pos | THT | same | C8463 | Extended |
| TB_DC_OUT_CH1..CH4 | 4 | Screw terminal, 5.08mm, 2-pos | THT | same | C8463 | Extended |

**Subtotals (rough, 20 boards, JLC standard pricing):**
- PCB fab (2-layer, 50×70mm, green soldermask, 20 pcs): ~$5-10 all-in
- SMT assembly (all Basic + 1 Extended type CA1..CA4 caps, ~28 placements × 20 boards): ~$40-60 with the assembly fee + setup
- Screw terminals (11 × $0.30 LCSC × 20 boards = $66) + Extended assembly upcharge: ~$80-100
- **Total: ~$130-170 for 20 fully-assembled boards** (~$7-9 per board)

If the screw-terminal assembly fee comes in higher than expected, fallback option: order PCBs unassembled-for-THT and hand-solder the 11 terminals per board (~5 min/board × 20 boards = ~1.5h of hand work). Saves ~$50 across the run.

---

## 6. Mechanical

**Board outline:** 50mm × 70mm, 2-layer, 1.6mm FR4, ENIG or HASL finish (HASL is fine — these aren't fine-pitch).

**Mounting:** 4× M3 mounting holes, one in each corner, 3.5mm from each edge. For DIN-rail enclosure standoffs.

**Connector placement (top-down view, all 11 screw terminals on board edges, wires enter from outside):**

```
              [70mm wide]
   ┌──────────────────────────────────────┐
   │  TB_DC_OUT_CH1  CH2  CH3  CH4        │  ← top edge: 4× 2-pos blocks
   │                                      │
   │  [DA1, CA1]  [DA2, CA2]  ...         │
   │                                      │
   │                                      │
   │  TB_AEDIKO_PWR                       │  ← left edge mid:
   │                                      │     AEDIKO power out
   │  TB_PWR_IN     [IC1, Q1, Q2, C1, R*] │  ← center: watchdog cluster
   │                                      │
   │  TB_KICK                             │  ← left edge bottom: Pi kick
   │                                      │
   │  TB_AC_IN_CH1  CH2  CH3  CH4         │  ← bottom edge: 4× 2-pos blocks
   └──────────────────────────────────────┘
              [50mm tall]
```

**Critical placement notes:**
- Keep AC field wiring (top + bottom edges) physically separated from the watchdog low-voltage cluster (center). Run a soldermask-defined keep-out zone or a copper ground pour split between them for hi-pot creepage compliance.
- 1N4007 anodes (DA1..DA4) get hot under continuous half-wave rectify of >10mA — pour a small thermal relief copper pad on the cathode side, ≥5mm × 5mm.
- LED1, LED2 on board edge, visible through DIN-rail enclosure cutout. Don't bury them under terminal blocks.
- IC1 NE555 is the largest active component (SOIC-8). Place centrally with Q1, Q2 on either side close to it. Keep timing cap C1 (100µF, the tallest part) on the IC1.6 + IC1.7 side.

---

## 7. Silkscreen labeling

The board lives in a field-service context. Silkscreen everything:

- Title block (top-left): `WSL Phase 8a — Watchdog + AC Interposer — Rev A — 2026`
- Each terminal block: function + polarity. E.g., `+5V IN`, `-`, `AEDIKO V+`, `AEDIKO V-`, `KICK`, `GND`, `24VAC CH1 L1`, `24VAC CH1 L2`, `DC OUT CH1 +`, `DC OUT CH1 -`, etc.
- Channel mapping table on silkscreen (one corner): `CH1=L21-FOUL, CH2=L21-2BALL, CH3=L22-FOUL, CH4=L22-2BALL` (adjust to match Dylan's actual wire labels at the enclosure).
- LEDs: `PWR` next to LED2, `WD` next to LED1.
- Polarity marks: `+` on cap pads (CA1..CA4, C1, C2), anode bar on diodes (DA1..DA4, D1, D2), Q1/Q2 pin-1 dot.
- A small text near IC1: `T_OUT ≈ 11s` (useful service note).

---

## 8. Design notes / gotchas to bake into the schematic

1. **R2 (TRIG pullup) is NOT optional.** Without it, NE555 free-runs as astable. This was the key bench discovery on 2026-05-11.
2. **Polarized caps:** silkscreen `+` marks must match the schematic. CA1..CA4 + is on DC+ side (DAn.K), − is on the return side (TB_AC_IN.2 / TB_DC_OUT.2). C1 + is on TIMING_NODE, − is on GND.
3. **CA1..CA4 voltage rating MUST be ≥50V.** Bench measured ~40V peak no-load; AC bus transients can exceed that. 35V parts will eventually fail.
4. **ESD on Q1 gate:** AO3400 SOT-23 is sensitive. Pi GPIO 12 is a 3.3V CMOS output, fine in normal operation, but R3 (1kΩ series) also limits any inrush from gate-charge transients. Don't omit R3.
5. **D1, D2 are switching diodes, NOT 1N4007.** The 1N4007's slow recovery (~3µs) is too sluggish for clean diode-OR isolation at the NE555's MHz-class internal speeds. 1N4148W (or similar fast switching) is correct.
6. **NE555 CTRL pin (IC1.5):** leave open OR add CFILT 10nF MLCC to GND. The optional filter cap improves immunity to power-rail noise; cheap insurance.
7. **Each AC channel's return is floating** relative to other channels and to watchdog GND. Do NOT pour a continuous GND plane across the AC interposer section. Use channel-isolated return traces (or zoned pours).
8. **Q2 power dissipation:** worst-case ~9mW (560mA × 28mΩ). No heatsink needed. But add a small thermal copper pad anyway — costs nothing on a 2-layer board.
9. **Test points (1mm round pads, silkscreened `TP1`..`TP4`):**
   - `TP1` on Q1_DRAIN (probe the diode-OR node, watch kick behavior on a scope)
   - `TP2` on NE555_OUT (probe timeout firing)
   - `TP3` on COIL_GND_RETURN (verify Q2 switching, ~0V when ON, floats when OFF)
   - `TP4` on TIMING_NODE (watch the cap charge/discharge ramp)
10. **No reverse-polarity protection on TB_PWR_IN.** A schottky in series would drop ~0.3V (acceptable from 5V) and protect against swapped wires. Add it if you have space: `D_PROT` = SS14 SMA (LCSC C2480), anode to TB_PWR_IN.1, cathode to VCC_5V rail. Optional — Dylan's call.

---

## 9. EasyEDA transcription checklist (suggested order)

1. Create new project: `wsl-phase8a-watchdog-interposer-rev-a`.
2. Schematic: place IC1 (NE555) in center. Wire its pins per the netlist table (Section 4).
3. Add Q1, Q2, R3, R4, R6, R7. Wire watchdog gate-drive paths.
4. Add R1, R2, C1, C2, D1, D2. Wire timing + diode-OR.
5. Add the 3 power-side terminals (TB_PWR_IN, TB_AEDIKO_PWR, TB_KICK).
6. Add LED1, LED2, R8, R9.
7. Replicate the AC channel circuit 4×. Use EasyEDA's "block copy + rename" — change suffix on each refdes/net (CH1 → CH2 → CH3 → CH4).
8. Add the 8 AC channel terminals (4 in, 4 out).
9. Add test points TP1..TP4 (use the schematic-only test-point symbol; they're net labels with associated pads on PCB).
10. Run ERC (Electrical Rule Check). Fix any unconnected pins / power-net issues.
11. Convert to PCB. Set board outline to 50×70mm with 4 M3 mounting holes at corners (3.5mm inset).
12. Place components per Section 6 layout sketch.
13. Route. 2-layer, 0.25mm trace minimum for signals, 0.5mm for power (VCC_5V, GND, COIL_GND_RETURN), 1.0mm for AC channels. Keep AC traces ≥3mm from low-voltage traces (creepage).
14. Add GND pours (split between watchdog GND and the 4 isolated AC returns — do NOT pour over the AC isolation zone).
15. DRC (Design Rule Check). Fix any clearance / width violations.
16. Generate Gerbers + drill files + BOM CSV + CPL (component placement) file.
17. JLCPCB upload: Gerbers → PCB order. BOM + CPL → SMT assembly. Specify "throught-hole assembly: no, hand-solder by customer" if avoiding the THT upcharge.

---

## 10. Post-fab bench validation

When the boards arrive (1-2 weeks lead time from JLC):

1. **Power-only test:** apply +5V to TB_PWR_IN. LED2 (power-good) should light. No magic smoke. Measure VCC_5V rail with multimeter — should read 5V ± 0.1V.
2. **Watchdog idle test:** with no Pi kick connected, observe LED1. Should be dark (NE555 OUT is undefined-then-LOW after C1 charges through R1). Measure COIL_GND_RETURN — should float (no return path).
3. **Watchdog kick test:** wire TB_KICK.1 to a signal generator or Pi GPIO 12 pulsing at 1Hz. LED1 should light continuously. COIL_GND_RETURN should read ~0V (Q2 ON). Stop kicks — LED1 should go dark within ~11s.
4. **AC interposer test:** apply 24VAC (Heath Zenith bench transformer) across TB_AC_IN_CH1.1 and .2. Measure DC voltage across TB_DC_OUT_CH1.1 (+) and .2 (−). Should read ~25-40V DC depending on load.
5. **Full integration:** wire AEDIKO PWR to TB_AEDIKO_PWR, AL-ZARD selector inputs to TB_DC_OUT channels, Pi GPIO 12 to TB_KICK, Pi GPIO 17/22/5/6 to AL-ZARD output side, Pi GPIO 23/24/25/27 to AEDIKO IN. Run lane_node.py. Verify pulse() commands toggle relays, AL-ZARD inputs reflect AC transformer state, kicks keep AEDIKO powered, killing lane_node.py drops AEDIKO power within ~11s.

If all 5 pass, the board is production-ready for Phase 8a unit #1 assembly.

---

## Open questions for Dylan

None. The bench has resolved every design decision. The only judgment calls left in EasyEDA transcription:

- LED color choice (LED1 vs LED2) — pick whatever's clearest from the enclosure cutout.
- Optional D_PROT reverse-polarity diode on power input — recommend yes, but small footprint, easy to add later in rev B if you skip rev A.
- Optional CFILT on NE555 CTRL — recommend yes, cheap.
- Silkscreen channel-mapping text — match Dylan's actual wire labels at the lane enclosure.

Everything else is mechanical. Open EasyEDA and step through Section 9.
