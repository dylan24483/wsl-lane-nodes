# Phase 8 Rev-D — First-Article / Bench Pack (GENERATED — do not hand-edit)

> **GENERATED 2026-07-21 by `scripts/generate_first_article_docs_revD.py` from the rev-D
> netlist + routed board. Re-run the script after ANY netlist or placement change —
> hand edits will be overwritten.** This pack is the Codex-M6 remediation artifact:
> the rev-C bench documents (TP map, board-1 bench packet, solder/bring-up guides)
> name WRONG parts on a rev-D board (46 refdes shifted) and MUST NOT be used here.
>
> Sources (sha256 at generation):
> - `kicad/wsl-phase8b-revD.net` — `c95869eaf0f516ee…`
> - `kicad/revD/wsl-phase8b-revD.kicad_pcb` — `66a42f4c2b58cf70…`
> - `kicad/revD/netlist_diff_revC_to_revD.txt` (REFDES_SHIFT cross-reference)
> - `firmware/rp2040/config.h` FW_VERSION — `phase8b-rp2040 v1.2.2` (every firmware reference below)
>
> Companion: `docs/phase8_revD_first_article_refdes_map.csv` — the complete
> 262-row refdes → function → value → location map (same generation run).
> Procedure authority: `phase8_revD_remediation_spec_2026-07-21.md` §R1.9/§R3/§R4 and
> `phase8_revD_readiness_checklist.md` §2 — this pack is their per-board execution form.

## 0. Hard rules before power

1. **⛔ Use ONLY this pack + its CSV for probing.** A technician probing "U37" from the
   rev-C TP map lands on the **AUX5 optocoupler** (U37 rev-D), not the isolated wetting
   supply (now **U45**), during a procedure that includes powered safety-rail fault
   injection.
2. Bench PSU ≥ 1 A on J2 (6 × ~77 mA coils + logic). Never feed 5 V into J1 pin 1
   at the same time as J2.
3. J14 bench jumper on 3-4 (Stop/CIS) is a **bench-only tool — remove before cutover.**
4. DNP refs (27, listed in the CSV) must be EMPTY: 7 × Rsnub (100R), 7 × Csnub
   (10nF X2), 7 × MOV, and the 6-part M1 channel (K7, J12, D13, Q7, R101, R102).
   A populated snubber/MOV at first article means the board was built off-spec
   (sizing awaits the powered characterization session — readiness G7 item 7).

## 1. Refdes shifts rev-C → rev-D (46 — the M6 hazard table)

Never translate from rev-C notes; this table is generated from the authoritative diff.

| Function (tag) | rev-C ref | rev-D ref | Value | rev-D location (x, y) |
|---|---|---|---|---|
| ISO_WET | U37 | U45 | TMA-0505S | (85.0, 5.7) |
| R_RAIL_GATE_PULLUP | R106 | R124 | 100k | (148.0, 82.0) |
| R_WDOG_KICK_GATE | R102 | R118 | 1k | (142.0, 47.0) |
| R_WDOG_KICK_PD | R103 | R119 | 10k | (142.0, 70.0) |
| R_WDOG_OUT_GATE | R104 | R120 | 1k | (162.0, 47.0) |
| R_WDOG_OUT_PD | R105 | R121 | 10k | (162.0, 70.0) |
| R_WDOG_TIMING | R100 | R116 | 100k | (146.0, 40.0) |
| R_WDOG_TRIG_PULLUP | R101 | R117 | 10k | (145.0, 78.0) |
| Rb_AND_ARM | R107 | R125 | 10k | (133.0, 90.0) |
| Rb_AND_RP_OK | R109 | R127 | 10k | (170.0, 90.0) |
| Rb_BE | R76 | R92 | 1k | (150.0, 131.0) |
| Rb_M | R79 | R95 | 1k | (150.0, 153.0) |
| Rb_M1 | R85 | R101 | 1k | (150.0, 197.0) |
| Rb_M2 | R82 | R98 | 1k | (150.0, 175.0) |
| Rb_S | R67 | R83 | 1k | (150.0, 65.0) |
| Rb_SP | R73 | R89 | 1k | (150.0, 109.0) |
| Rb_T | R70 | R86 | 1k | (150.0, 87.0) |
| Rgled_L_FIRST | R88 | R104 | 1k | (101.0, 190.0) |
| Rgled_L_FOUL | R97 | R113 | 1k | (137.0, 190.0) |
| Rgled_L_SECOND | R91 | R107 | 1k | (113.0, 190.0) |
| Rgled_L_STRIKE | R94 | R110 | 1k | (125.0, 190.0) |
| Rled_L_FIRST | R90 | R106 | 330R | (104.0, 182.0) |
| Rled_L_FOUL | R99 | R115 | 330R | (140.0, 182.0) |
| Rled_L_SECOND | R93 | R109 | 330R | (116.0, 182.0) |
| Rled_L_STRIKE | R96 | R112 | 330R | (128.0, 182.0) |
| Rpd_AND_ARM | R108 | R126 | 100k | (133.0, 98.0) |
| Rpd_AND_RP_OK | R110 | R128 | 100k | (170.0, 98.0) |
| Rpd_BE | R77 | R93 | 100k | (150.0, 137.0) |
| Rpd_M | R80 | R96 | 100k | (150.0, 159.0) |
| Rpd_M1 | R86 | R102 | 100k | (150.0, 203.0) |
| Rpd_M2 | R83 | R99 | 100k | (150.0, 181.0) |
| Rpd_S | R68 | R84 | 100k | (150.0, 71.0) |
| Rpd_SP | R74 | R90 | 100k | (150.0, 115.0) |
| Rpd_T | R71 | R87 | 100k | (150.0, 93.0) |
| Rpdled_L_FIRST | R89 | R105 | 100k | (107.0, 190.0) |
| Rpdled_L_FOUL | R98 | R114 | 100k | (143.0, 190.0) |
| Rpdled_L_SECOND | R92 | R108 | 100k | (119.0, 190.0) |
| Rpdled_L_STRIKE | R95 | R111 | 100k | (131.0, 190.0) |
| Rsnub_BE | R78 | R94 | 100R DNP | (222.0, 131.0) |
| Rsnub_M | R81 | R97 | 100R DNP | (222.0, 153.0) |
| Rsnub_M1 | R87 | R103 | 100R DNP | (222.0, 197.0) |
| Rsnub_M2 | R84 | R100 | 100R DNP | (222.0, 175.0) |
| Rsnub_S | R69 | R85 | 100R DNP | (222.0, 65.0) |
| Rsnub_SP | R75 | R91 | 100R DNP | (222.0, 109.0) |
| Rsnub_T | R72 | R88 | 100R DNP | (222.0, 87.0) |
| U_WDOG | U36 | U44 | NE555 | (151.0, 50.0) |

**Headline traps:** ISO_WET is **U45** (was U37; U37 is now PC817 AUX5). U_WDOG NE555 is
**U44** (was U36; U36 is now PC817 AUX4). The rail-gate pull-up is **R124** (was R106;
R106 is now a lamp resistor).

## 2. Test-pad map (rev-D strip locations — relocated vs rev-C)

| TP | Net | Location (x, y) mm | Band |
|---|---|---|---|
| TP1 | VCC_5V | (100, 229) | LOGIC |
| TP2 | GND | (110, 229) | LOGIC |
| TP3 | VCC_3V3 | (120, 229) | LOGIC |
| TP4 | FIELD_WET_V | (22, 229) | FIELD |
| TP5 | FIELD_GND | (34, 229) | FIELD |
| TP6 | I2C_SDA | (130, 229) | LOGIC |
| TP7 | I2C_SCL | (140, 229) | LOGIC |
| TP8 | WDOG_KICK | (150, 229) | LOGIC |
| TP9 | WDOG_TIMING_NODE | (100, 236) | LOGIC |
| TP10 | NE555_TRIG | (110, 236) | LOGIC |
| TP11 | NE555_OUT | (120, 236) | LOGIC |
| TP12 | WDOG_OK_PULLDOWN | (128, 236) | LOGIC |
| TP13 | ARM_PERMIT | (136, 236) | LOGIC |
| TP14 | RP2040_OK | (144, 236) | LOGIC |
| TP15 | SAFE_STOP_RETURN | (152, 236) | LOGIC |
| TP16 | RELAY_ENABLE_RAIL | (160, 236) | LOGIC |
| TP17 | TAP_GATE_555 | (128, 54) | LOGIC |
| TP18 | TAP_NE555_OUT | (113, 52) | LOGIC |
| TP19 | TAP_GATE_KICK | (128, 58) | LOGIC |
| TP20 | TAP_WDOG_KICK | (113, 56) | LOGIC |
| TP21 | TAP_GATE_ARM | (128, 62) | LOGIC |
| TP22 | TAP_ARM_PERMIT | (113, 60) | LOGIC |
| TP23 | TAP_GATE_RPOK | (128, 66) | LOGIC |
| TP24 | TAP_RP2040_OK | (113, 64) | LOGIC |

## 3. Key functional groups (positions from the routed board)

### 3.1 Modules / ICs / relays

| Ref | Function (tag) | Value | Location (x, y) mm | Band | DNP |
|---|---|---|---|---|---|
| A1 | RP_PICO | RP2040 Pico | (100.0, 33.0) | LOGIC |  |
| K1 | K_S | G5LE S | (176.0, 72.0) | LOGIC |  |
| K2 | K_T | G5LE T | (176.0, 94.0) | LOGIC |  |
| K3 | K_SP | G5LE SP | (176.0, 116.0) | LOGIC |  |
| K4 | K_BE | G5LE BE | (176.0, 138.0) | LOGIC |  |
| K5 | K_M | G5LE M | (176.0, 160.0) | LOGIC |  |
| K6 | K_M2 | G5LE M2 | (176.0, 182.0) | LOGIC |  |
| K7 | K_M1 | G5LE M1 DNP | (176.0, 204.0) | LOGIC | DNP |
| U1 | MCP_IN_A | MCP23017 MCP_IN_A | (122.0, 104.0) | LOGIC |  |
| U2 | MCP_IN_B | MCP23017 MCP_IN_B | (122.0, 146.0) | LOGIC |  |
| U3 | MCP_OUT_A | MCP23017 MCP_OUT_A | (140.0, 112.0) | LOGIC |  |
| U44 | U_WDOG | NE555 | (151.0, 50.0) | LOGIC |  |
| U45 | ISO_WET | TMA-0505S | (85.0, 5.7) | LOGIC |  |

### 3.2 Safety chain (watchdog → AND → rail gate) — the fault-injection targets

| Ref | Function (tag) | Value | Location (x, y) mm | Band | DNP |
|---|---|---|---|---|---|
| C11 | C_WDOG_TIMING | 100uF/16V | (156.0, 42.0) | LOGIC |  |
| C12 | C_WDOG_VCC | 0.1uF | (156.0, 67.0) | LOGIC |  |
| C13 | C_WDOG_CTRL | 10nF | (166.0, 42.0) | LOGIC |  |
| D15 | D_WDOG_TIMING | 1N4148 | (152.0, 35.0) | LOGIC |  |
| D16 | D_WDOG_TRIG | 1N4148 | (159.0, 35.0) | LOGIC |  |
| Q12 | Q_WDOG_KICK | AO3400A kick | (142.0, 58.0) | LOGIC |  |
| Q13 | Q_WDOG_OK | AO3400A wdog | (162.0, 58.0) | LOGIC |  |
| Q14 | Q_RAIL | AO3401A rail pass | (158.0, 82.0) | LOGIC |  |
| Q15 | Q_AND_ARM | MMBT3904 AND ARM | (143.0, 92.0) | LOGIC |  |
| Q16 | Q_AND_RP_OK | MMBT3904 AND RP_OK | (160.0, 96.0) | LOGIC |  |
| R116 | R_WDOG_TIMING | 100k | (146.0, 40.0) | LOGIC |  |
| R117 | R_WDOG_TRIG_PULLUP | 10k | (145.0, 78.0) | LOGIC |  |
| R118 | R_WDOG_KICK_GATE | 1k | (142.0, 47.0) | LOGIC |  |
| R119 | R_WDOG_KICK_PD | 10k | (142.0, 70.0) | LOGIC |  |
| R120 | R_WDOG_OUT_GATE | 1k | (162.0, 47.0) | LOGIC |  |
| R121 | R_WDOG_OUT_PD | 10k | (162.0, 70.0) | LOGIC |  |
| R124 | R_RAIL_GATE_PULLUP | 100k | (148.0, 82.0) | LOGIC |  |

### 3.3 Rail-tap stages (remediation R1 — 2N7002 unidirectional, reads INVERTED)

| Ref | Function (tag) | Value | Location (x, y) mm | Band | DNP |
|---|---|---|---|---|---|
| Q17 | Q_TAP_555 | 2N7002LT1G TAP 555 | (116.0, 52.0) | LOGIC |  |
| Q18 | Q_TAP_KICK | 2N7002LT1G TAP KICK | (116.0, 56.0) | LOGIC |  |
| Q19 | Q_TAP_ARM | 2N7002LT1G TAP ARM | (116.0, 60.0) | LOGIC |  |
| Q20 | Q_TAP_RPOK | 2N7002LT1G TAP RPOK | (116.0, 64.0) | LOGIC |  |
| R131 | R_TAPIN_555 | 1M | (146.0, 33.0) | LOGIC |  |
| R132 | R_TAPPU_555 | 10k | (120.5, 52.0) | LOGIC |  |
| R133 | R_TAPIN_KICK | 1M | (136.0, 47.0) | LOGIC |  |
| R134 | R_TAPPU_KICK | 10k | (120.5, 56.0) | LOGIC |  |
| R135 | R_TAPG_KICK | 10M | (125.0, 56.0) | LOGIC |  |
| R136 | R_TAPIN_ARM | 1M | (130.0, 70.0) | LOGIC |  |
| R137 | R_TAPPU_ARM | 10k | (120.5, 60.0) | LOGIC |  |
| R138 | R_TAPG_ARM | 10M | (125.0, 60.0) | LOGIC |  |
| R139 | R_TAPIN_RPOK | 1M | (156.0, 64.0) | LOGIC |  |
| R140 | R_TAPPU_RPOK | 10k | (120.5, 64.0) | LOGIC |  |
| R141 | R_TAPG_RPOK | 10M | (125.0, 64.0) | LOGIC |  |

Netting per stage: observed net → R_TAPIN (1M) → `TAP_GATE_*` → FET gate; VCC_3V3 →
R_TAPPU (10k) → `TAP_*` drain → GPIO (GP16=555, GP17=KICK, GP18=ARM, GP19=RPOK, Pico
pins 21/22/24/25). R_TAPG 10M gate pulldowns exist on KICK/ARM/RPOK only — **the 555
stage deliberately has none** (push-pull source, never high-Z); do not report it missing.

### 3.4 Diagnostics adds (ADC divider, wetting bleed, protection diode)

| Ref | Function (tag) | Value | Location (x, y) mm | Band | DNP |
|---|---|---|---|---|---|
| C15 | C_ADC5 | 100nF | (117.0, 44.0) | LOGIC |  |
| D17 | D_PROT | SS34 | (122.0, 20.0) | LOGIC |  |
| R122 | R_WET_BLEED1 | 2k2 | (63.0, 16.0) | FIELD |  |
| R123 | R_WET_BLEED2 | 2k2 | (67.0, 16.0) | FIELD |  |
| R129 | R_ADC5_TOP | 10k | (114.0, 41.0) | LOGIC |  |
| R130 | R_ADC5_BOT | 10k | (114.0, 47.0) | LOGIC |  |

### 3.5 Connectors

| Ref | Function (tag) | Value | Location (x, y) mm | Band | DNP |
|---|---|---|---|---|---|
| A1 | RP_PICO | RP2040 Pico | (100.0, 33.0) | LOGIC |  |
| J1 | J_PI | J_PI | (135.5, 10.0) | LOGIC |  |
| J2 | J_PWR | J_PWR 5V | (116.0, 10.0) | LOGIC |  |
| J3 | J_FAST | J_FAST_IN | (9.0, 42.0) | FIELD |  |
| J4 | J_SLOWA | J_SLOW_IN_A | (9.0, 103.0) | FIELD |  |
| J5 | J_SLOWB | J_SLOW_IN_B | (9.0, 168.0) | FIELD |  |
| J6 | J_MOTION_S | J_MOTION_S 5.08mm | (242.0, 68.0) | MACHINE |  |
| J7 | J_MOTION_T | J_MOTION_T 5.08mm | (242.0, 90.0) | MACHINE |  |
| J8 | J_MOTION_SP | J_MOTION_SP 5.08mm | (242.0, 112.0) | MACHINE |  |
| J9 | J_MOTION_BE | J_MOTION_BE 5.08mm | (242.0, 134.0) | MACHINE |  |
| J10 | J_MOTION_M | J_MOTION_M 5.08mm | (242.0, 156.0) | MACHINE |  |
| J11 | J_MOTION_M2 | J_MOTION_M2 5.08mm | (242.0, 178.0) | MACHINE |  |
| J12 | J_MOTION_M1 | J_MOTION_M1 5.08mm | (242.0, 200.0) | MACHINE | DNP |
| J13 | J_LAMP | J_LAMP_LED | (104.0, 206.0) | LOGIC |  |
| J14 | J_SAFE | J_SAFETY | (167.0, 10.0) | LOGIC |  |
| J15 | J_SLOWC | J_SLOW_IN_C | (9.0, 222.0) | FIELD |  |
| J16 | J_EXTI2C | J_EXT_I2C | (128.0, 206.0) | LOGIC |  |
| JP1 | JP_J16_3V3 | 3V3 LINK OPEN DNP | (144.6, 218.9) | LOGIC | DNP |

## 4. First-article procedures (FA-1 … FA-12)

Run in order. Record every measurement in `phase8_revD_run_log.md` (new FA section,
per board serial). One channel of each NEW I/O type must pass before trusting the board.

### FA-1 — Rails
1. Power J2 from the bench PSU (5.0 V, current-limit 1.5 A). Idle draw noted.
2. TP1 (VCC_5V) ≈ 4.6–4.8 V (behind D17 SS34). TP3 (VCC_3V3) 3.3 V ±3 %.
3. **TP4 (FIELD_WET_V) unloaded ≤ ~6 V** — the item-A bleed proof (11–14 V float gone;
   if TP4 still floats high, R122/R123 are missing/open). Under opto load ≥ ~4.5 V.
4. Regression: TP5 ↔ TP2 OPEN (field/logic ground isolation).

### FA-2 — I2C presence
`i2cdetect -y 1` → 0x20 / 0x21 / 0x22 ACK. (Any module later added on J16 must avoid
0x20–0x23.)

### FA-3 — Relay make/break
`lane_node/bench_first_article.py` pattern: each of K1–K6 makes and breaks (K7 DNP).
Watch the ADC trend during the 6-coil energize (feeds FA-6 step 3).

### FA-4 — USB / flash (item B)
Ordinary unmodified micro-B cable fully seats with the J1 ribbon MATED; BOOTSEL
reachable; UF2 drag-drop flash of firmware `phase8b-rp2040 v1.2.2` succeeds WITHOUT a shaved cable.

### FA-5 — GPB bank poke (item C — AUX4-11 on MCP_IN_B 0x21 port B)

| J15 pin | Channel | GPB bit | Opto ref | Opto location |
|---|---|---|---|---|
| J15-1 | AUX4 | GPB0 | U36 | (74.0, 195.4) |
| J15-2 | AUX5 | GPB1 | U37 | (74.0, 201.1) |
| J15-3 | AUX6 | GPB2 | U38 | (74.0, 206.8) |
| J15-4 | AUX7 | GPB3 | U39 | (74.0, 212.5) |
| J15-5 | AUX8 | GPB4 | U40 | (74.0, 218.2) |
| J15-6 | AUX9 | GPB5 | U41 | (74.0, 223.9) |
| J15-7 | AUX10 | GPB6 | U42 | (74.0, 229.6) |
| J15-8 | AUX11 | GPB7 | U43 | (74.0, 235.3) |

1. Poke each J15 pin 1–8 to FIELD_GND (J15 pins 9/10) in turn.
2. The matching GPB bit reads ACTIVE-LOW on 0x21; all 8 channels, and confirm NO
   crosstalk between adjacent rows (only the poked bit changes).
3. Software path: `controller_io` with `board_rev="revD"` (`IN_B_MAP_REVD`) — a rev-C
   `board_rev` never reads port B; that is a config error, not a board fault.

### FA-6 — VCC_5V ADC (item D)
1. GP26/ADC0 reads VCC_5V/2 via R129/R130; the `phase8b-rp2040 v1.2.2` heartbeat carries
   VCC_5V as `v5` (latest) / `v5n` (window min) / `v5x` (window max), all mV
   (R2-5: the old `adc_vcc5` name here matched NOTHING the firmware emits).
2. Compare against the TP1 DMM value: **±3 % gate** (remediation spec R3.4).
3. Energize all 6 coils (FA-3) — the sag must be visible in the heartbeat `v5n` field.

### FA-7 — Rail-tap fault injection (remediation spec **R1.9 governs**; discharges OG-4)

Equipment: bench PSU, scope, heat gun + **thermocouple**, clip leads, Pi-emulator rig,
firmware `phase8b-rp2040 v1.2.2` (release build) + the bench-only **FI-1** build (drives GP16–19
output-high on command; refuses to run without its physical jumper; prints its identity
on the UART banner; NEVER a release artifact).

**Probe rule (R2-5 — governs EVERY tap-node measurement in this procedure):** all
probing and fault insertion on the tap gate/drain nodes goes through the dedicated
probe pads **TP17–TP24** (G column x=128.0, D column x=112.8; silk "TAP PROBES:
D WEST / G EAST") — **never touch a SOT-23 pin of Q17–Q20 with a probe or clip**.
Instrumentation on the GATE pads must present **≥ 100 MΩ input impedance** (high-Z
DMM mode or a ≥ 100 MΩ FET probe): the tap input network is 1 M / 10 M, so a standard
10 MΩ scope/DMM probe loads it and shifts the very levels this procedure verifies.
Drain pads (10 k pull-up) tolerate a 10 MΩ probe, but use the high-Z instrument
throughout if available. Record WHICH instrument was used in the run log.

0. **Boot the FI-1 image (round-3 doc fix — the jumper gate vs the RP2040 bootrom):**
   BOOTSEL held at power-on is intercepted by the ROM — the chip enters the RPI-RP2
   USB bootloader and the image never runs, so a plain power cycle with the jumper
   fitted can NEVER satisfy the gate (bootrom behavior, not a defect). Either:
   **(a) button:** hold BOOTSEL → plug USB (RPI-RP2) → drag
   `wsl_phase8b_rp2040_FI1.uf2` → keep holding through the automatic reboot into the
   image → release after the FI-1 banner (`"fi1":1`) prints; or **(b) jumper +
   picotool:** fit the jumper → plug USB (lands in RPI-RP2 — expected) →
   `picotool reboot`; remove the jumper only after the banner. Booting without the
   jumper is the PERMANENT `fi1_nojumper` refusal — the gate working, never a reason
   to rebuild with the check stubbed.
1. **Level survey (cold):** measure each `TAP_GATE_*` gate node and `TAP_*` drain node
   **at its TP17–TP24 pad** (probe rule above; stage positions in §3.3) through the
   full signal swing. Expect gate-high ≥ 3.0 V
   typical (worst-stack floor per spec R1.5: 2.80–2.82 V). Reads are INVERTED:
   observed HIGH ⇒ GPIO pad LOW.
2. **Unidirectionality proof (cold):** FI-1 drives each GP16–19 output-high in turn
   with J1 UNMATED (ARM_PERMIT / WDOG_KICK high-Z — the Pi-reboot state). Meter each
   observed net (TP11 = NE555_OUT, TP8 = WDOG_KICK, TP13 = ARM_PERMIT,
   TP14 = RP2040_OK): **must not move > 1 mV; the rail (TP16) must not arm.**
3. **Fault insertion (cold):** clip-short each tap stage **drain-gate** (F3) across its
   **TP pad pair** (G pad ↔ D pad — never the SOT-23 pins) — Q17 (555),
   Q18 (KICK), Q19 (ARM), Q20 (RPOK) — and repeat step 2 (the F4 double-fault stack).
   Then with the Pi-emulator arming the rail normally, remove the emulator drive
   (high-Z) with the short still applied — **the rail must drop within the same
   watchdog window as an unfaulted board.**
4. **AT TEMPERATURE — the C1 gate; a cold-only pass does NOT discharge OG-4:** heat
   the Q_AND_ARM (Q15) / Q_AND_RP_OK (Q16) / Q_RAIL (Q14) region AND all four tap FETs
   (Q17–Q20) to **≥ 70 °C case** (thermocouple-verified; hold ≥ 2 min). Repeat steps
   2 and 3 in full at temperature: high-Z + D-G short + stuck-high GPIO — the rail
   must neither arm nor hold, and a deliberate ARM_PERMIT disarm (driven low,
   push-pull — never tristated) must still drop the rail. Photograph thermocouple
   readings for the run log.
5. **Edge-order proof (firmware `phase8b-rp2040 v1.2.2`):** force (a) Pi-death (kill the emulator) and
   (b) kick-starvation (emulator holds ARM high, stops kicking). The 1 ms tap ring
   (`TAPDUMP`) must show the documented edge order and advisory cause for each
   (`arm_drop` / `kick_starvation`), and the record must **survive a Pico reboot**
   (epoch increments, entries retained — spec R3.3). `TAPCLR`, and only `TAPCLR`,
   clears it.
6. Record everything (levels, windows, thermocouple photos) in the run log FA section.

### FA-8 — Cross-mate refusal + sacrificial-pair coding proof (OG-3 / Codex H7)

**Coding install rule (corrected 2026-07-21): the CP-MSTB 1734634 profile fits the
PLUG (or an inverted header) — it is NEVER pressed into a standard MCV G-3.5 header.**
The header side of the code is made by removing the coding rib at the matching pole.

1. **Sacrificial pair FIRST:** on one spare 1840447 plug + one spare/scrap header (or
   the J3 position of a scrap board), install a profile per the Phoenix instruction
   sheet shipped with the parts and make the matching header-side cut. Verify:
   (a) the coded plug seats FULLY in its own coded header;
   (b) the coded plug REFUSES an uncoded header;
   (c) the cut does not damage adjacent poles. Only then code production parts.
2. Code production plugs: J3 @ pole 1 (white band), J15 @ pole 10 (yellow band),
   J13 @ pole 1 (white band), J16 @ pole 6 (blue band); make the matching header-side
   cuts on the board's own headers.
3. **Refusal matrix (all four must physically refuse):** J3-plug vs J15 header ·
   J15-plug vs J3 header · J13-plug vs J16 header · J16-plug vs J13 header.
4. Verify silk legibility at all four: "KEYED: NOT J15" / "NOT J3" / "NOT J16" /
   "NOT J13 LAMP" (1.2 mm silk).

### FA-9 — PC817 input-channel qualification (remediation spec R4 + round-2 R2-7)

1. **V_CE sampling (R4 trigger condition 1):** measure V_CE(on) on **3 sample channels**
   at nominal wetting (~1.7 mA I_F) with the field contact closed. Gate: **V_CE(on) ≤
   0.3 V** on every sampled channel. Any channel above 0.3 V REOPENS the R4 disposition
   (forces Rin 2k2 → 1k ≈ 3.5 mA + mandatory §H.3 wetting and §H.4 D17 budget re-runs).
   Record values per channel.
2. **Per-channel qualification at minimum field voltage (R2-7):** load the wetting rail
   to its fleet worst case (all populated field contacts closed), confirm FIELD_WET_V at
   TP4 sits at its loaded minimum (≈ 4.5 V — FA-1 step 3), then close each populated
   field-input channel in turn and confirm its MCP23017 bit reads ACTIVE-LOW. This is
   the R4 threshold condition made empirical: the phototransistor must sink
   ≈ 0.26 mA (pull the 10 k logic pull-up below V_IL ≈ 0.66 V) at the LOWEST I_F the
   fleet will ever supply. **Every populated channel — not a sample.**
3. **Temperature leg (R2-7):** heat the populated PC817 input optos (§3 refdes map) to
   **≥ 70 °C case** (thermocouple-verified — same rig as FA-7 step 4) and repeat
   step 2 at the loaded minimum field voltage. Hot + low-I_F is the worst-case CTR
   corner the spec R4 arithmetic bounds from typical curves; a clean per-channel pass
   here is the empirical closure of the R2-7 disposition (spec §R4-A). Record
   per-channel PASS + measured TP4 voltage + case temperature. Any failure lands
   under R4 reopen trigger 1.

### FA-10 — MCV header mechanical (FR-9, first connector only)
Before reflowing/soldering the remaining six MCV headers, install and solder ONE
(recommend J14, 4-pos) on the 1.4 mm `_D1.4` drills: verify insertion force is normal
and solder fill is complete. Then proceed with the rest.

### FA-11 — Firmware posture assert (refuses the first-article pass if absent)
1. Boot banner shows `phase8b-rp2040 v1.2.2` (config.h FW_VERSION at pack generation — a
   different banner means the wrong image is flashed) and `tap:{ep,pre,n}` state.
2. `tap_assert_input_only()` is active (heartbeat-tick OE/FUNCSEL readback); simulate
   nothing here — the host suite already proves the trip path; on-silicon just confirm
   no `tap_dir` fault is latched with the release build.
3. Confirm the running build is NOT FI-1 (banner identity), and FI-1 refuses to run
   without its physical jumper.
4. Deliberate disarm drives ARM_PERMIT low (push-pull), never tristates.

### FA-12 — J16 SDA/SCL external-short recovery (round-2 R2-4)

Proves the TCA4307 (U46) actually isolates the controller bus, and that a wedged J16
is an AVAILABILITY event with a fail-safe landing — never an unsafe state. Run with the
board operating normally: release firmware `phase8b-rp2040 v1.2.2`, Pi-emulator arming the rail,
relays exercising the FA-3 pattern.

1. Short **J16 SDA (card side) → GND** at the connector. While the short is held:
   `i2cdetect -y 1` still ACKs **0x20 / 0x21 / 0x22**, the relay pattern keeps
   running, RELAY_ENABLE_RAIL (TP16) and every output are UNCHANGED, and no safety
   fault latches — controller bus + safety response + output state all deterministic.
2. Release the short: U46 must reconnect the card side on its own (~40 ms stuck
   detect, up to 16 SCLOUT recovery pulses per the TI datasheet) — a module on J16
   re-enumerates WITHOUT a board power cycle.
3. Repeat steps 1–2 for **SCL → GND**, then **SDA + SCL → GND together**.
4. Sustained wedge: repeat step 1 holding the short **> 60 s** — bus, outputs, and
   rail state stay deterministic for the full duration (no watchdog trip, no drift).
5. **Severity record (R2-4):** a fault that DID wedge the controller-side bus would
   land as tick-I2C failure → `_on_safety_trip` → ARM drop → rail de-energized — an
   availability incident with a fail-safe landing. U46 exists so a J16 module cannot
   cause even that. Record the observed behavior against this statement.

## 5. Sign-off

| Item | Result | Initials / date |
|---|---|---|
| FA-1 rails (TP4 bleed proof) | | |
| FA-2 I2C 0x20/21/22 | | |
| FA-3 relays K1–K6 | | |
| FA-4 USB seat + UF2 | | |
| FA-5 GPB bank 8/8 no-crosstalk | | |
| FA-6 ADC ±3 % + sag visible | | |
| FA-7 tap fault injection COLD | | |
| FA-7 step 4 **AT ≥ 70 °C** (OG-4) | | |
| FA-7 step 5 edge order + reboot persistence | | |
| FA-8 sacrificial pair + 4-way refusal | | |
| FA-9 V_CE ≤ 0.3 V ×3 channels | | |
| FA-9 per-channel qual @ min FIELD_WET + ≥ 70 °C (R2-7) | | |
| FA-10 MCV insertion/solder fill | | |
| FA-11 firmware `phase8b-rp2040 v1.2.2` posture | | |
| FA-12 J16 SDA/SCL short recovery (U46, R2-4) | | |
