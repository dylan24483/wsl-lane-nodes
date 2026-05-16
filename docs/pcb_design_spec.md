# Phase 8a PCB Design Spec — Unified Watchdog + AC Interposer Board

**Status:** Rev A ordered at JLCPCB 2026-05-15 — fab in transit (boards expected ~2026-05-22 to 05-24). This doc has been **reconciled to rev A as-built** as of 2026-05-15.
**Source of truth for the actual board:** `scripts/generate_kicad_netlist.py` + `scripts/place_components.py` + `kicad/wsl-phase8a.kicad_pcb`. This doc gives design rationale and an as-built summary; if the doc disagrees with those three files, the files win.
**Target fab:** JLCPCB, 2-layer FR-4, **100mm × 100mm**, 1.6mm thick, ENIG, green soldermask, white silk, SMT-assembled. Phoenix MKDS 5.08mm 2-pos screw terminals (J1-J11) are **NOT** in PCBA — Dylan hand-solders them post-fab (~30 min/board).
**Quantity:** 20 boards (16 for lane pairs + 4 spares). All-in cost ~$160-190.
**Bench provenance:** NE555 watchdog topology bench-validated 2026-05-11; 1N4007/10µF AC interposer bench-validated 2026-05-11 (Heath Zenith 24VAC transformer → ~40V DC no-load → ~25-30V loaded → AL-ZARD opto fires → Pi GPIO HIGH/LOW correct).
**Audit history:** Codex reviewed rev A in four passes (P0, P1, P2, P3) — see Section 11 for the full pass log.

---

## 0. Rev A as-built reconciliation (2026-05-15)

The design went through SKiDL-driven schematic generation, then KiCad annotation, which renumbered some reference designators relative to the original EasyEDA-era spec. **All refdes in Sections 1-10 below have been updated to match rev A as-built (`scripts/place_components.py` PLACEMENT dict).**

### Refdes mapping (original spec → rev A as-built)

| Original spec | Rev A as-built | Part | Notes |
|---|---|---|---|
| IC1 | **U1** | NE555D NE555 timer | standard U-prefix |
| Q1, Q2 | Q1, Q2 | AO3400A N-MOSFET | unchanged |
| D1, D2 | D1, D2 | 1N4148WS switching | unchanged |
| DA1..DA4 | **D3, D4, D5, D6** | M7 (1N4007 SMA) AC rectifier | continuous D-numbering |
| LED1 | **D7** | green LED, watchdog-healthy | LEDs share D-prefix |
| LED2 | **D8** | green LED, power-good | |
| D_PROT (optional) | **D9** | SS14 SMA reverse-polarity Schottky | **promoted from optional to standard per Codex P0** |
| C1 | C1 | 100µF/16V NE555 timing | unchanged |
| C2 | C2 | 0.1µF/50V NE555 VCC bypass | unchanged |
| CFILT (optional) | **C3** | 10nF/50V NE555 CTRL filter | **promoted from optional to standard** |
| CA1..CA4 | **C4, C5, C6, C7** | 10µF AC smoothing — **63V (bumped from 50V per Codex P0)** | continuous C-numbering |
| R1 | R1 | 100k NE555 timing pullup | unchanged |
| R2 | R2 | 10k NE555 TRIG pullup | unchanged |
| R3 | R3 | 1k Q1 gate series | unchanged |
| R4 | R4 | 10k Q1 gate pulldown | unchanged |
| R6 (spec) | **R5** | 1k Q2 gate series | KiCad annotation filled the R5 gap |
| R7 (spec) | **R6** | 10k Q2 gate pulldown | shifted |
| R8 (spec) | **R7** | 470Ω D7 (LED1) current limit | shifted |
| R9 (spec) | **R8** | 470Ω D8 (LED2) current limit | shifted |
| Rb1..Rb4 | **R9, R10, R11, R12** | 100k AC interposer bleeders | continuous R-numbering |
| TB_PWR_IN | **J1** | Phoenix MKDS 5.08mm 2-pos | left-edge, top |
| TB_AEDIKO_PWR | **J2** | same | left-edge, middle |
| TB_KICK | **J3** | same | left-edge, bottom |
| TB_AC_IN_CH1..CH4 | **J4, J5, J6, J7** | same | bottom edge, L→R |
| TB_DC_OUT_CH1..CH4 | **J8, J9, J10, J11** | same | top edge, L→R |
| (M3 mounts in §6) | **MK1..MK4** | M3 NPTH 3.2mm holes | promoted to first-class refdes per Codex P0 |
| TP1..TP4 | **TP1..TP14** | SMD test pads | **expanded from 4 to 14 per Codex P0** — see §8.9 |

Note: SKiDL's `generate_kicad_netlist.py` uses some Python variable names that differ from the as-built board (the script declares `R10..R13` for bleeders and `LED1, LED2` for the indicator LEDs; KiCad's annotation step renumbered these to R9..R12 and D7, D8 respectively before fab. Treat `place_components.py` PLACEMENT dict as the authoritative refdes for the physical board.)

### Other rev A deltas vs original spec

- **Board size:** spec said ~50×70mm; rev A is **100×100mm**. Larger area was needed once AC channels were laid out as 4 vertical columns with the watchdog cluster filling the gaps below, plus per-channel test pads and bleeders.
- **B.Cu keepout zones** in the gap regions between AC channel columns — **entirely new addition per Codex P2** to force AC return traces to stay within their channel columns rather than crossing under the watchdog area on B.Cu. Five keepout zones: `gap_J1_to_ch1` (x=14-18), `gap_ch1_to_ch2` (x=23-37), `gap_ch2_to_ch3` (x=43-57), `gap_ch3_to_ch4` (x=63-77), `gap_ch4_to_right` (x=83-92), each spanning y=5-95.
- **Manual U1 pin 8 (VCC) route** added in KiCad after FreeRouting left a 0.2mm stub (final P3 audit). This fix lives in `kicad/wsl-phase8a.kicad_pcb` only — **NOT** reproduced by `scripts/place_components.py`. Any rev B regenerated from scripts will need the fix re-applied. Consider adding a post-route fixup script if a rev B happens.
- **C2 position:** spec had it "right of U1"; rev A pushed left to (24, 65) during P3 audit to clear a DRC clearance violation against U1 pin 2 (TRIG).

The rest of this document describes design intent and as-built reality. Read Section 1 onward for the full picture.

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
                       J1 ───┬── VCC_5V_RAW ──► D9.A
                             │                   │
                             │                   D9.K ──► VCC_5V net (5V rail) ───┐
                             │                                                     │
                             └── GND                                                │
                                                                                    ├──► U1.4 RESET + U1.8 VCC
                                                                                    ├──► R1 timing pullup
                                                                                    ├──► R2 TRIG pullup
                                                                                    ├──► C2 bypass
                                                                                    ├──► R8 → D8 (power-good)
                                                                                    ├──► R7 → D7 (wd-healthy)
                                                                                    └──► J2.1 (V+ to AEDIKO direct)

   PI HEADER ── J3 ─────┬── KICK net (Pi GPIO 12) ──► R3 ──► Q1_GATE
                        │                                  R4 pull-down to GND
                        │                                  Q1.S → GND
                        │                                  Q1.D → Q1_DRAIN (diode-OR node)
                        └── GND ref

   Q1_DRAIN ─► D1.K (D1.A = TIMING_NODE = NE555 THRES/DISCH)
            └► D2.K (D2.A = NE555_TRIG)

   U1.3 NE555_OUT ──► R6 ──► Q2_GATE
                              R7-spec(now R6) pull-down to GND
                              Q2.S → GND
                              Q2.D → COIL_GND_RETURN net
                                          │
                                          ├──► J2.2 (V− return to AEDIKO)
                                          └──► D7.K (anode at VCC via R7)

   ┌─ AC channel 1 ─────────────────────────────────────┐
   │  J4.1 (24VAC L1) ─► D3.A                           │
   │                    D3.K ─► C4.+ ──► J8.1           │
   │                        ╰─► R9.1 ───┘   (bleeder)   │
   │  J4.2 (24VAC L2) ────────► C4.− ──► J8.2           │
   │                        ╰─► R9.2 ───┘               │
   └────────────────────────────────────────────────────┘
   (channels 2, 3, 4 identical with D4/C5/R10/J5/J9, D5/C6/R11/J6/J10, D6/C7/R12/J7/J11)
```

---

## 3. Function block detail

### 3a. NE555 watchdog (retriggerable monostable, "kick to stay alive")

Topology rationale (recap of bench finding): standard NE555 monostable fires OUT HIGH on a falling TRIG edge and holds HIGH for `T_OUT = 1.1 × R1 × C1`. With R1=100kΩ, C1=100µF → **T_OUT ≈ 11 seconds**. Retriggering is achieved by Q1 (driven by Pi GPIO 12 through R3) pulling BOTH the TIMING_NODE (THRES/DISCH) AND the TRIG pin to ground simultaneously, via diode-OR isolation (D1, D2). Pi's 1Hz kick rate ⟹ NE555 sees a fresh trigger every second, OUT stays HIGH continuously. Stop kicks ⟹ TIMING_NODE charges through R1 toward Vcc, hits 2/3 Vcc threshold after ~11s, OUT goes LOW, Q2 opens, relay coils lose return path.

**The R2 TRIG pullup is critical.** Without it, leaving TRIG tied only to Q1.D via D2 means TRIG floats low when Q1 is OFF, causing the NE555 to free-run as an astable oscillator. R2 holds TRIG HIGH at idle so the monostable rests in its expected state. (Discovered during bench validation, 2026-05-11.)

### 3b. Output stage (Q2 low-side switch on AEDIKO V− return)

N-channel MOSFET (AO3400 SOT-23) gates the AEDIKO PWR V− return path. AEDIKO V+ is wired direct to VCC_5V via J2.1. When NE555 OUT is HIGH, Q2 conducts, completing the return circuit. When NE555 OUT is LOW (timeout), Q2 opens — relay coils have no current path, all relays mechanically open.

**Why low-side, not high-side:** an N-MOSFET cannot fully saturate as a high-side switch from a 5V rail (Vgs collapses to 0 as source rises). Low-side switching keeps Vgs = Vcc = 5V when ON, AO3400 saturates fully (Rds(on) ~28mΩ at Vgs=4.5V).

**Continuous current:** AEDIKO 8 relays × ~70mA/coil = 560mA worst case. AO3400 rated 5.7A. Power dissipation: I²×R = 0.56² × 0.028 = 8.8mW. SOT-23 rated ~0.5W. Massive thermal margin.

### 3c. Reverse-polarity protection (D9)

D9 (SS14 SMA Schottky) sits in series between the J1 +5V raw input and the rest of the VCC_5V rail. If J1.1 and J1.2 are swapped at install, D9 reverse-biases and the supply is open — no damage propagates. Forward drop is ~0.3V at the full ~600mA load, so VCC_5V rests at ~4.7V — within spec for AEDIKO (4.5-6V), NE555 (4.5-15V), and AL-ZARD (3.3V regulated downstream).

Per Codex rev A audit (pass P0): this was originally optional in the spec and was promoted to standard placement. The cost is ~$0.05 and one component. The risk it mitigates (swapped +5V/GND at install during the cutover or any later swap) is real and would otherwise smoke the NE555 + cap polarized parts.

### 3d. AC interposer (4 independent channels)

Each channel: 1× 1N4007 (M7 SMA) half-wave rectifier in series with the L1 line (D3..D6), 1× 10µF/**63V** aluminum electrolytic across DC+ and DC− (C4..C7), 1× 100kΩ bleeder resistor in parallel with the cap (R9..R12). L2 ties directly to DC− (no rectification on the return).

**Why the bleeder (R9..R12):** without a discharge path, the cap holds charge after the AC source goes away (microamp leakage only ⟹ minute-scale retention). In normal operation the AL-ZARD draws ~10mA and dominates discharge (~25ms decay to de-assert threshold), so the bleeder is invisible — but if the AL-ZARD is disconnected during service or swapped for a higher-impedance module later, the bleeder ensures the cap reaches sub-volt within ~5s (τ=RC=100k×10µF=1s, 5τ ≈ 99% discharge). 6.25mW dissipation per channel, 0.25mA continuous draw on the AC bus. Per Codex review 2026-05-13.

**Voltage math** (verified at bench 2026-05-11):
- AC source measured at lane 22: ~28V RMS, ~40V peak
- After half-wave rectify, no-load: ~40V DC at the cap
- Loaded (AL-ZARD draws ~11mA): ~25-30V DC with ~10-15V ripple at 60Hz
- AL-ZARD selector input (24V tolerance, 10-40V AC/DC spec): triggers PC817 LED reliably across the ripple band

**Cap rating — 63V** (bumped from spec's 50V per Codex P0). The ~40V peak no-load is at 80% of a 50V cap's safe operating area; bowling-alley AC bus transients (inductive load switches at QBK-SIx) can briefly push above that. 63V gives ~37% headroom over peak and survives realistic transients.

**No shared L2 across channels.** Westside foul + 2nd-ball AC bus topology is unknown; safest design is to keep each channel's return floating relative to the others and to the watchdog GND. AL-ZARD's per-channel galvanic isolation (PC817 inside) handles any potential differences downstream.

### 3e. Indicator LEDs (field-service aid)

- **D8 (power-good, green):** VCC → R8 → D8.A → D8.K → GND. Lit when 5V supply is present. Field service can verify supply without a multimeter.
- **D7 (watchdog-healthy, green):** VCC → R7 → D7.A → D7.K → COIL_GND_RETURN. Lit when Q2 is conducting (i.e., NE555 OUT HIGH = kicks healthy). Goes dark when watchdog times out. Pi-down ⟹ D7 dark — instant visual diagnostic.

---

## 4. Complete net list

Net names use UPPER_SNAKE. Each line lists every pin on that net.

| Net | Pins on this net |
|---|---|
| `VCC_5V_RAW` | J1.1, D9.A |
| `VCC_5V` | D9.K, U1.4, U1.8, R1.1, R2.1, C2.1, R7.1, R8.1, J2.1 |
| `GND` | J1.2, U1.1, C1.2 (−), C2.2, C3.2, R4.2, R6.2, Q1.S, Q2.S, D8.K, J3.2 |
| `KICK` | J3.1, R3.1 |
| `Q1_GATE` | R3.2, R4.1, Q1.G |
| `Q1_DRAIN` | Q1.D, D1.K, D2.K |
| `TIMING_NODE` | U1.6 (THRES), U1.7 (DISCH), R1.2, C1.1 (+), D1.A |
| `NE555_TRIG` | U1.2, R2.2, D2.A |
| `NE555_OUT` | U1.3, R5.1 |
| `Q2_GATE` | R5.2, R6.1, Q2.G |
| `COIL_GND_RETURN` | Q2.D, J2.2, D7.K |
| `NE555_CTRL` | U1.5, C3.1 |
| `LED1_ANODE_DRIVE` | R7.2, D7.A |
| `LED2_ANODE_DRIVE` | R8.2, D8.A |
| AC channel 1: `AC_CH1_L1` | J4.1, D3.A |
| AC channel 1: `DC_CH1_POS` | D3.K, C4.1 (+), R9.1, J8.1 |
| AC channel 1: `CH1_RETURN` | J4.2, C4.2 (−), R9.2, J8.2 |
| AC channel 2: `AC_CH2_L1` | J5.1, D4.A |
| AC channel 2: `DC_CH2_POS` | D4.K, C5.1 (+), R10.1, J9.1 |
| AC channel 2: `CH2_RETURN` | J5.2, C5.2 (−), R10.2, J9.2 |
| AC channel 3: `AC_CH3_L1` | J6.1, D5.A |
| AC channel 3: `DC_CH3_POS` | D5.K, C6.1 (+), R11.1, J10.1 |
| AC channel 3: `CH3_RETURN` | J6.2, C6.2 (−), R11.2, J10.2 |
| AC channel 4: `AC_CH4_L1` | J7.1, D6.A |
| AC channel 4: `DC_CH4_POS` | D6.K, C7.1 (+), R12.1, J11.1 |
| AC channel 4: `CH4_RETURN` | J7.2, C7.2 (−), R12.2, J11.2 |

**Total net count:** 14 watchdog/output/protection + 3 nets × 4 AC channels = 26 nets.

---

## 5. BOM

All parts SMT except screw terminals (J1-J11, through-hole, 5.08mm pitch — **NOT** included in JLC PCBA; Dylan hand-solders post-fab).

| RefDes | Qty | Description | Package | Value/Rating | Suggested LCSC | JLC tier |
|---|---|---|---|---|---|---|
| U1 | 1 | NE555 timer | SOIC-8 | — | C7593 (TI NE555DR) | Basic |
| Q1 | 1 | N-MOSFET, logic-level | SOT-23 | 30V, 5.7A, Vgs(th) ≤1.3V | C20917 (AO3400A) | Basic |
| Q2 | 1 | N-MOSFET, logic-level | SOT-23 | 30V, 5.7A, Vgs(th) ≤1.3V | C20917 (AO3400A) | Basic |
| D1 | 1 | Switching diode | SOD-323 | 100V, fast | C2128 (1N4148WS) | Basic |
| D2 | 1 | Switching diode | SOD-323 | 100V, fast | C2128 (1N4148WS) | Basic |
| D3..D6 | 4 | Rectifier, AC interposer | SMA (DO-214AC) | 1000V, 1A | C95872 (M7 / 1N4007 SMA) | Basic |
| D7 | 1 | Indicator LED, watchdog-healthy | 0805 | green | C72043 | Basic |
| D8 | 1 | Indicator LED, power-good | 0805 | green | C72043 | Basic |
| D9 | 1 | Reverse-polarity protection Schottky | SMA | 40V, 1A, Vf ≤0.55V@1A | C2480 (SS14) | Basic |
| C1 | 1 | Aluminum electrolytic, NE555 timing | SMD radial 6.3×5.4mm | 100µF, 16V | C16133 | Basic |
| C2 | 1 | MLCC, NE555 V+ bypass | 0805 | 0.1µF, 50V, X7R | C49678 | Basic |
| C3 | 1 | MLCC, NE555 CTRL pin filter | 0805 | 10nF, 50V, X7R | C1633 | Basic |
| C4..C7 | 4 | Aluminum electrolytic, AC smoothing | SMD radial 6.3×7.7mm | 10µF, **63V minimum** | verify on order; ChengX/Lelon | likely Extended |
| R1 | 1 | NE555 timing resistor | 0805 | 100kΩ, 1% | C17407 | Basic |
| R2 | 1 | NE555 TRIG pullup | 0805 | 10kΩ, 1% | C17414 | Basic |
| R3 | 1 | Q1 gate series | 0805 | 1kΩ, 1% | C17513 | Basic |
| R4 | 1 | Q1 gate pulldown | 0805 | 10kΩ, 1% | C17414 | Basic |
| R5 | 1 | Q2 gate series | 0805 | 1kΩ, 1% | C17513 | Basic |
| R6 | 1 | Q2 gate pulldown | 0805 | 10kΩ, 1% | C17414 | Basic |
| R7 | 1 | D7 (LED1) current limit | 0805 | 470Ω, 1% | C17554 | Basic |
| R8 | 1 | D8 (LED2) current limit | 0805 | 470Ω, 1% | C17554 | Basic |
| R9..R12 | 4 | AC interposer bleeders | 0805 | 100kΩ, 1% | C17407 (same as R1) | Basic |
| J1..J11 | 11 | Phoenix MKDS 5.08mm 2-pos screw terminal | THT | 12A, 300V | DLL 2EDG-5.08-2ALS or equivalent | **NOT IN PCBA** — hand-solder |
| MK1..MK4 | 4 | M3 mounting hole, NPTH 3.2mm | — | — | (KiCad `MountingHole_3.2mm_M3`) | mechanical only |

**Total active components in PCBA:** 1×U1 + 2×Q + 9×D + 7×C + 12×R = 31 placements per board × 20 boards = 620 placements. Plus 14 test pads + 4 mounting holes per board × 20 boards (no placement cost).

**Actual order cost (2026-05-15):** ~$160-190 all-in for 20 fully-assembled boards (PCBA + fab + shipping). Hand-soldering Phoenix terminals on each unit takes ~30 min.

---

## 6. Mechanical

**Board outline:** 100mm × 100mm, 2-layer, 1.6mm FR-4, ENIG finish, green soldermask, white silk. Origin (0,0) = top-left, X right, Y down (per `place_components.py`).

**Mounting:** 4× M3 mounting holes (NPTH 3.2mm), one in each corner, 3.5mm inset from each edge:

| RefDes | Position (mm) |
|---|---|
| MK1 | (3.5, 3.5) — top-left |
| MK2 | (96.5, 3.5) — top-right |
| MK3 | (3.5, 96.5) — bottom-left |
| MK4 | (96.5, 96.5) — bottom-right |

**Layout zones:**
- **Top edge (y≈8):** J8-J11 DC OUT terminals at x = 20, 40, 60, 80 (channels 1-4 L→R)
- **Bottom edge (y≈92):** J4-J7 24VAC IN terminals at x = 20, 40, 60, 80 (channels 1-4 L→R), rotated 180° (screws face down)
- **Left edge (x≈8):** J1 +5V/GND at y=22, J2 AEDIKO at y=45, J3 KICK/GND at y=78 (each rotated 90°, screws face left)
- **D9 (reverse-polarity Schottky):** at (10, 35), in the left-edge gap between J1 and J2 (clear of channel 1 column at x=20)
- **AC channel columns:** vertical stacks at x = 20, 40, 60, 80 (one per channel). Each stack from top: D (rectifier) at y=18, C (smoothing cap) at y=30, R (bleeder) at y=42. All rotated 90° so cathode is up toward DC_OUT terminal.
- **Watchdog cluster (y=55-80):** fills the gaps BETWEEN channel columns at x ≈ 25, 32, 45, 52, 72.
  - U1 NE555 at (32, 66)
  - C1 timing cap at (30, 58); C2 VCC bypass at (24, 65); C3 CTRL filter at (37, 60)
  - R1 timing pullup at (32, 52); R2 TRIG pullup at (25, 67)
  - Q1 (discharge) at (52, 60); Q2 (output) at (52, 70)
  - D1 at (45, 62), D2 at (45, 68) — both rotated 180° so anode faces U1
  - R3-R6 gate-drive resistors in the x=48 column at y=55, 60, 70, 75
  - D7, D8 indicator LEDs at (76, 60), (76, 70); R7, R8 current limits at (72, 60), (72, 70)

**Critical placement notes:**
- AC channel returns (vertical traces at x=20, 40, 60, 80, running from y=42 down to y=92) MUST stay in their columns on B.Cu. Watchdog parts sit in x-gaps so these traces pass through without hitting component pads. Five B.Cu keepout zones (see §8.10) enforce this.
- LED visibility: D7 ("WD") at (76, 60) and D8 ("PWR") at (76, 70) are on the right side, oriented for visibility through a DIN-rail enclosure cutout. Don't bury them under terminal blocks.
- C1 (100µF timing electrolytic) is the tallest part. Placed at (30, 58) just above U1 — top-down access is clear.
- Tightest courtyard: C2 bypass cap was originally at (28, 65) — too close to U1 pin 2 (TRIG at x=29.525); pad 2 ground at x=28.95 was 0.7mm from TRIG. Pushed left 4mm to (24, 65) during Codex P3 audit. Future placement edits must preserve at least this clearance.

---

## 7. Silkscreen labeling

Rev A consolidated per-pin labels into per-terminal labels (pad numbers 1/2 on the terminal footprint outlines already identify polarity, so per-pin "+"/"−" labels were redundant and caused 22 DRC silkscreen warnings).

Final F.Silkscreen labels (per `place_components.py` SILKSCREEN_LABELS):

| Text | Position (mm) | Size | What it labels |
|---|---|---|---|
| `+5V/GND` | (17, 22) | 0.9 | J1 — power input |
| `AEDIKO` | (17, 45) | 0.9 | J2 — AEDIKO PWR pass-through |
| `KICK/GND` | (17, 78) | 0.9 | J3 — Pi GPIO 12 watchdog kick input |
| `CH1 DC` | (20, 15) | 1.0 | J8 — channel 1 DC OUT |
| `CH2 DC` | (40, 15) | 1.0 | J9 — channel 2 DC OUT |
| `CH3 DC` | (60, 15) | 1.0 | J10 — channel 3 DC OUT |
| `CH4 DC` | (80, 15) | 1.0 | J11 — channel 4 DC OUT |
| `CH1 24VAC` | (20, 85) | 0.9 | J4 — channel 1 24VAC IN |
| `CH2 24VAC` | (40, 85) | 0.9 | J5 — channel 2 24VAC IN |
| `CH3 24VAC` | (60, 85) | 0.9 | J6 — channel 3 24VAC IN |
| `CH4 24VAC` | (80, 85) | 0.9 | J7 — channel 4 24VAC IN |
| `WD` | (82, 60) | 1.0 | D7 — watchdog-healthy indicator |
| `PWR` | (82, 70) | 1.0 | D8 — power-good indicator |

**Not yet on rev A silkscreen** (deferred to rev B if it happens):
- Title block "WSL Phase 8a — Watchdog + AC Interposer — Rev A — 2026"
- Channel mapping table (CH1=L21-FOUL, CH2=L21-2BALL, CH3=L22-FOUL, CH4=L22-2BALL) — Dylan's lane wire labels weren't finalized at fab time; channel mapping is documented in the cutover plan (`docs/phase_8a_cutover_plan.md`) instead
- Service note "T_OUT ≈ 11s" near U1
- Polarity marks beyond the standard footprint silkscreen (+/− on caps, anode bar on diodes, pin-1 dots on Q1/Q2 — these come from the footprint definitions automatically)

---

## 8. Design notes / gotchas

1. **R2 (TRIG pullup) is NOT optional.** Without it, NE555 free-runs as astable. This was the key bench discovery on 2026-05-11.
2. **Polarized caps:** silkscreen `+` marks come from the `CP_Elec_*` footprint definition. C4..C7 + is on DC+ side (D3..D6.K), − is on the return side. C1 + is on TIMING_NODE, − is on GND. **Verify on the populated board before powering up.**
3. **C4..C7 voltage rating MUST be ≥63V** (per Codex P0). The bench-measured ~40V peak no-load is at 80% of a 50V cap's SOA; 63V gives ~37% headroom over peak and survives realistic AC-bus transients from QBK-SIx inductive switching.
4. **ESD on Q1/Q2 gates:** AO3400 SOT-23 is sensitive. Pi GPIO 12 is a 3.3V CMOS output, fine in normal operation, but R3 and R5 (1kΩ series) also limit any inrush from gate-charge transients. Don't omit them.
5. **D1, D2 are switching diodes, NOT 1N4007.** The 1N4007's slow recovery (~3µs) is too sluggish for clean diode-OR isolation at the NE555's MHz-class internal speeds. 1N4148WS is correct.
6. **C3 CTRL filter:** kept the optional CFILT slot at (37, 60). Cheap insurance against rail noise.
7. **Each AC channel's return is floating** relative to other channels and to watchdog GND. The B.Cu keepout zones (§8.10) plus the absence of a continuous GND pour across the AC interposer section enforce this in the as-built routing.
8. **Q2 power dissipation:** worst-case ~9mW (560mA × 28mΩ). No heatsink needed.
9. **Test pads (TP1..TP14, SMD pads exposed through soldermask)** — per Codex P0 expansion from spec's 4 to 14:
   - `TP1` VCC_5V at (25, 22) — verify 5V rail post-D9
   - `TP2` GND at (25, 28) — ground reference
   - `TP3` KICK at (18, 80) — scope the Pi kick stream
   - `TP4` TIMING_NODE at (6, 60) — watch cap charge/discharge ramp
   - `TP5` NE555_OUT at (40, 65) — probe timeout firing
   - `TP6` COIL_GND_RETURN at (58, 70) — verify Q2 switching, ~0V when ON, floats when OFF
   - `TP7..TP14` DC_POS + RETURN per channel at (15/25, 35/45, 55/65, 75/85, y=48) — per-channel post-interposer DC voltage
10. **B.Cu keepout zones** (per Codex P2) in the five gap regions between AC channel columns and the right edge — see §6. These force AC return traces to stay vertical within their channel columns rather than crossing under the watchdog area on B.Cu. F.Cu is unconstrained, so watchdog routes are not blocked.
11. **D9 (SS14 Schottky) protects against reversed +5V/GND at J1.** Series in the VCC path. ~0.3V forward drop at full load. Promoted from optional to standard in rev A per Codex P0.
12. **Manual U1 pin 8 (VCC) route in `kicad/wsl-phase8a.kicad_pcb` is NOT reproduced by `scripts/place_components.py`.** FreeRouting left a 0.2mm stub on rev A; Codex P3 hand-routed it in KiCad. Any future regeneration from scripts will need this re-applied (consider a post-route fixup script for rev B).

---

## 9. Toolchain (rev A as-built)

**Original spec assumed EasyEDA. Rev A actually used the SKiDL → KiCad 10 → FreeRouting toolchain.** See `project_phase8a_pcb_toolchain` memory for empirically-learned gotchas in this stack (kinet2pcb 1.1.4 KiCad-10 patch, test pads need real library FPID, .ses placement lock, etc.).

Build order to regenerate rev A or produce rev B:

1. Edit `scripts/generate_kicad_netlist.py` (SKiDL source of truth — components, values, footprints, nets, ERC).
2. Run with system Python:
   ```powershell
   python scripts\generate_kicad_netlist.py
   ```
   → produces `kicad/wsl-phase8a.net`.
3. Run kinet2pcb to import netlist → KiCad PCB:
   ```powershell
   kinet2pcb kicad\wsl-phase8a.net kicad\wsl-phase8a.kicad_pcb
   ```
   (Requires the line-17 patch on KiCad 10 — see `project_phase8a_pcb_toolchain` memory.)
4. Edit `scripts/place_components.py` (PLACEMENT dict + BCU_KEEPOUT_GAPS + TEST_PADS + SILKSCREEN_LABELS).
5. **DELETE stale `kicad/wsl-phase8a.dsn` and `kicad/wsl-phase8a.ses`** before regenerating, or the next FreeRouting cycle will reset positions to old .ses values.
6. Run placement with KiCad's bundled Python (has `pcbnew` module):
   ```powershell
   & "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\place_components.py
   ```
   → updates `kicad/wsl-phase8a.kicad_pcb` with placed components, board outline, mounting holes, B.Cu keepout zones, test pads, silkscreen labels.
7. Open the .kicad_pcb in KiCad. File → Export → Specctra DSN → `kicad/wsl-phase8a.dsn`.
8. Run FreeRouting (v2.2.4 headless CLI):
   ```powershell
   java -jar "$env:USERPROFILE\Downloads\freerouting-2.2.4-cli.jar" `
     -de kicad\wsl-phase8a.dsn `
     -do kicad\wsl-phase8a.ses
   ```
9. In KiCad: File → Import → Specctra Session → select `kicad/wsl-phase8a.ses`.
10. Run DRC. Should be 0 errors / 0 unconnected / 0 footprint errors. If FreeRouting left a stub (it did for U1.pin8 on rev A), hand-route the missing connection in KiCad's interactive router.
11. Send latest design + spec diff to Codex for review. Categorize findings as real-electrical / cosmetic / defer-to-rev-B (see `feedback_codex_audits` memory). Address real-electrical issues and re-route if needed. Expect 3-4 audit rounds.
12. Once DRC + Codex are clean, export Gerbers + drill + BOM CSV + CPL CSV → `kicad/gerbers/`. Upload to JLCPCB.

---

## 10. Post-fab bench validation

When the boards arrive (~2026-05-22 to 05-24 for rev A):

1. **Power-only test:** apply +5V to J1 (TB_PWR_IN). D8 (power-good, green) should light. No magic smoke. Measure VCC_5V rail at TP1 — should read ~4.7V (5V minus D9 forward drop ~0.3V). Measure ground at TP2 — should be 0V.
2. **Reverse-polarity test:** swap J1.1/J1.2 wires. D8 should NOT light, no current should flow, no parts should heat. Restore correct polarity.
3. **Watchdog idle test:** with no Pi kick connected, observe D7 (watchdog-healthy). Should be dark (NE555 OUT is LOW after C1 charges through R1 over ~11s). Measure COIL_GND_RETURN at TP6 — should float (no return path).
4. **Watchdog kick test:** wire J3.1 to a signal generator or Pi GPIO 12 pulsing at 1Hz. D7 should light continuously. TP6 should read ~0V (Q2 ON). Stop kicks — D7 should go dark within ~11s.
5. **AC interposer test:** apply 24VAC (Heath Zenith bench transformer) across J4.1 and J4.2. Measure DC voltage at TP7 (DC_CH1_POS) vs TP8 (CH1_RETURN) — should read ~25-40V DC depending on load. Repeat for channels 2-4 (J5/TP9-10, J6/TP11-12, J7/TP13-14).
6. **Full integration:** wire AEDIKO PWR to J2, AL-ZARD selector inputs to J8-J11, Pi GPIO 12 to J3.1, Pi GPIO 17/22/5/6 to AL-ZARD output side, Pi GPIO 23/24/25/27 to AEDIKO IN. Run `lane_node/lane_node.py`. Verify pulse() commands toggle relays, AL-ZARD inputs reflect AC transformer state, kicks keep AEDIKO powered, killing lane_node.py drops AEDIKO power within ~11s.

If all 6 pass, the board is production-ready for Phase 8a unit #1 cutover at lanes 21+22. See `docs/phase_8a_cutover_plan.md` for the run-of-show.

---

## 11. Codex audit history (rev A)

Four review passes from 2026-05-13 through 2026-05-15 caught real electrical issues that would have killed the board:

### Pass P0 (pre-route, design review)

- **C4..C7 cap voltage 50V too close to 45V peak transients** → bumped to 63V minimum
- **Missing reverse-polarity Schottky on +5V input** → added D9 SS14 SMA
- **Missing M3 mounting holes** as first-class refdes → added MK1-MK4 at corner positions (3.5mm inset)
- **Test pads inadequate for field service** → expanded from 4 to 14 (TP1-TP14): 6 critical watchdog nets + 8 per-channel (DC_POS + RETURN per AC channel)
- **No silkscreen labels for field-installer wiring** → added 13 consolidated text labels (per-terminal not per-pin)
- **CFILT (10nF NE555 CTRL filter) optional in spec** → promoted to standard placement (C3)

### Pass P1 (pre-route, after P0 fixes applied)

- **D9 polarity backwards** (cathode toward J1) → flipped (rotation 180°)
- **AC channel components horizontal not vertical-in-columns** → rotated D3-D6, C4-C7, R9-R12 to 90° so they align with the vertical column trace from J8-J11 down to J4-J7
- **D1/D2 anode rotation suboptimal for short TIMING_NODE / NE555_TRIG traces** → rotated to 180° so anodes face U1 left side

### Pass P2 (post-route, after autoroute)

- **CH1/CH2 AC return traces routing across watchdog area on B.Cu** (FreeRouting found shortest path through the watchdog cluster, but this risks coupling AC switching noise into the timing network) → added B.Cu keepout zones in the five gap regions between AC channel columns and to the right of channel 4. F.Cu unaffected, so watchdog routes still have full bottom-half access. Re-routed with keepouts in place.

### Pass P3 (final, post-keepout re-route)

- **U1 pin 8 (VCC) unconnected** — FreeRouting left a 0.2mm stub that didn't reach the pad → Codex hand-routed in KiCad's interactive router. **NOT** reproduced by `scripts/place_components.py`; lives only in `kicad/wsl-phase8a.kicad_pcb`. Document for rev B.
- **C2 bypass cap pad 2 (GND, x=28.95) too close to U1 pin 2 (TRIG, x=29.525)** — DRC clearance violation, 0.7mm separation → moved C2 from (28, 65) to (24, 65), 4mm to the left
- **Silkscreen text overruns** on some pads (22 DRC warnings) → consolidated per-pin labels into per-terminal labels (e.g., "+5V" + "GND" pair → "+5V/GND" single label outside the terminal courtyard)

Final DRC after P3: **0 errors, 0 unconnected, 0 footprint errors**. Gerbers exported and uploaded to JLCPCB on 2026-05-15.

### Lessons for future rev B (or any future Phase 8 PCB)

- Run a P0 design audit BEFORE the first netlist generation. Catches voltage/protection/mechanical issues before any layout work.
- Keep the test-pad and silkscreen-label dicts in `scripts/place_components.py` rather than hand-placing them in KiCad — survives any re-routing without manual rework.
- Any manual KiCad edits (e.g., the U1.pin8 fix) need to be reflected in a post-route fixup script if the board ever gets regenerated from SKiDL.
- See `feedback_codex_audits` memory: categorize each Codex finding as real-electrical / cosmetic / defer-to-rev-B and act accordingly.
