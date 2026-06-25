---
title: "WSL Phase 8 — rev-B Controller Board — Pre-Power Test Checklist"
---

# WSL Phase 8 — rev-B Controller Board
## Pre-Power Bench Test Checklist (shorts · continuity · first power)

| Field | Value |
|---|---|
| Board ID / serial | ____________________ |
| Date | ____________________ |
| Tester | ____________________ |
| DMM model | ____________________ |
| Bench supply | ________ V set, ________ mA current limit |

**Derived from the live board netlist** (`wsl-phase8b.routed-manual.kicad_pcb`). Every probe point below is a real net/pad on this board. Do the phases **in order**. Do **not** apply power until Phase 0–2 pass.

### How to use the meter
- **Short checks (Phase 1):** continuity/beep + low-Ω range. "NOT shorted" = no steady beep, reads high. Caps charge through the meter, so rail-to-rail readings *climb* as C11/decoupling fill — that's normal; a real short sits steady near 0 Ω.
- **Continuity (Phase 2):** continuity/beep. "Beep" = ~0 Ω = good joint / same net. Probe the **pin metal** (top contact or back-side tail), not the plastic.
- **Diode mode** where noted (D17).
- **Reference grounds:** logic measurements → **TP2 (`GND`)**. Field-domain measurements → **TP5 (`FIELD_GND`)**. **Never bridge a meter lead across TP2 and TP5** — that defeats the U37 isolation barrier.

### Test-point locations (silk labels TP1–TP16)
| TP | Net | TP | Net |
|---|---|---|---|
| TP1 | `VCC_5V` (logic +5 V, post-D17) | TP9 | `WDOG_TIMING_NODE` |
| TP2 | `GND` (logic ground) | TP10 | `NE555_TRIG` |
| TP3 | `VCC_3V3` (Pico regulator) | TP11 | `NE555_OUT` |
| TP4 | `FIELD_WET_V` (isolated +5 V) | TP12 | `WDOG_OK_PULLDOWN` |
| TP5 | `FIELD_GND` (isolated ground) | TP13 | `ARM_PERMIT` |
| TP6 | `I2C_SDA` | TP14 | `RP2040_OK` |
| TP7 | `I2C_SCL` | TP15 | `SAFE_STOP_RETURN` |
| TP8 | `WDOG_KICK` | TP16 | `RELAY_ENABLE_RAIL` |

> **STOP CONDITIONS (any phase):** rail-to-ground short · ANY `FIELD_GND`↔`GND` continuity · current pegging the limit at power-up · any part heating. Power off and find the cause before continuing.

---

## PHASE 0 — Visual inspection (no meter, both sides, magnification)

**Bridges / defects**
- ☐ No solder balls, whiskers, or flux bridges anywhere — **top side**
- ☐ No solder balls, whiskers, or flux bridges anywhere — **bottom side**
- ☐ **A1 Pico** castellations — no bridges between adjacent castellations
- ☐ **3× MCP23017** SOIC leads (U1/U2/U3) — no lead-to-lead bridges
- ☐ **32-opto bank** (PC817 U4–U35) — no pin bridges
- ☐ **Relay pins** K1–K6 — no bridges
- ☐ **U37 (TMA-0505S)** 4 pins — no bridges

**Cold / insufficient joints** (dull, balled, not wicked through)
- ☐ All connector joints inspected — full, shiny fillets
- ☐ **J13 reseated pins** specifically — confirmed full fillets both sides

**Polarized / orientation — HAND-SOLDERED (where errors happen)**
- ☐ **A1 Pico** — pin-1 / USB edge matches silk
- ☐ **U37 (TMA-0505S)** — square pad = pin 1 = +Vin (verified pinout); body flush

**Polarized / orientation — JLC-PLACED (glance for tombstone/rotation/wrong part)**
- ☐ **D17 (SS14)** reverse-protection Schottky — cathode band toward the rail (silk)
- ☐ **D15, D16 (1N4148)** watchdog diodes — cathode bands match silk
- ☐ **D1, D3, D5, D7, D9, D11, D13 (1N4148)** relay flyback diodes — cathode bands match silk
- ☐ **C11 electrolytic** ("100 16V") — minus stripe matches silk polarity
- ☐ **K1–K6** relays all seated flat; **K7 (M1) is EMPTY** (DNP — correct)
- ☐ **D2/D4/D6/D8/D10/D12/D14 (MOV)** footprints are **EMPTY** (DNP — correct)

**Mechanical**
- ☐ Every connector body flush and square — no lifted/tilted headers

---

## PHASE 1 — Unpowered short check  ·  SUPPLY DISCONNECTED

Meter on continuity/low-Ω. These are the checks that prevent a power-on disaster.

- ☐ **TP1 (`VCC_5V`)** ↔ **TP2 (`GND`)** — **NOT shorted** (high Ω). Steady ~0 Ω → **STOP** (5 V↔gnd bridge)
- ☐ **TP3 (`VCC_3V3`)** ↔ **TP2 (`GND`)** — **NOT shorted**. Steady ~0 Ω → STOP
- ☐ **TP1 (`VCC_5V`)** ↔ **TP3 (`VCC_3V3`)** — **NOT shorted** (3V3 is regulated from 5 V, not tied)
- ☐ **J2 pin 1 (`VCC_5V_RAW`)** ↔ **TP2 (`GND`)** — **NOT shorted** (input side, before D17)
- ☐ **TP4 (`FIELD_WET_V`)** ↔ **TP5 (`FIELD_GND`)** — **NOT shorted** (U37 isolated output)
- ☐ **TP5 (`FIELD_GND`)** ↔ **TP2 (`GND`)** — **OPEN / no continuity** ← **isolation barrier**. ANY beep → **STOP**
- ☐ **TP4 (`FIELD_WET_V`)** ↔ **TP2 (`GND`)** — **OPEN** (field/logic isolation). ANY beep → STOP
- ☐ **TP4 (`FIELD_WET_V`)** ↔ **TP1 (`VCC_5V`)** — **OPEN** (field/logic isolation). ANY beep → STOP

---

## PHASE 2 — Continuity / joint integrity  ·  still unpowered

### 2A — Logic ground common (probe **TP2 `GND`** ↔ each; all should beep)
- ☐ TP2 ↔ **J2 pin 2** (`GND`)
- ☐ TP2 ↔ **J2 pin 3** (`GND`)
- ☐ TP2 ↔ **J1 pin 2** (`GND`)
- ☐ TP2 ↔ **J1 pin 12** (`GND`)
- ☐ TP2 ↔ **J13 pin 2** (`GND`)
- ☐ TP2 ↔ **C11 minus (−) terminal**

### 2B — Logic +5 V (probe **TP1 `VCC_5V`** ↔ each; all should beep)
- ☐ TP1 ↔ **J1 pin 1** (`VCC_5V`)
- ☐ TP1 ↔ **J13 pin 1** (`VCC_5V`)
- ☐ TP1 ↔ **J14 pin 1** (`VCC_5V`)

### 2C — Input rail + reverse-protection diode D17
- ☐ **J2 pin 1 (`VCC_5V_RAW`)** ↔ **D17 anode pad** — beep (same raw-input net)
- ☐ **D17 in diode mode:** J2 pin 1 (anode) → TP1 (cathode) reads **~0.3 V forward, OPEN reversed** — confirms D17 present and **correctly oriented**
- ☐ Note: J2 pin 1 ↔ TP1 is **not** a plain beep — it passes through D17 (expected)

### 2D — Logic 3.3 V and named control signals (probe TP ↔ J1 pin; should beep)
- ☐ **TP3 (`VCC_3V3`)** ↔ **J1 pin 11**
- ☐ **TP6 (`I2C_SDA`)** ↔ **J1 pin 3**
- ☐ **TP7 (`I2C_SCL`)** ↔ **J1 pin 4**
- ☐ **TP8 (`WDOG_KICK`)** ↔ **J1 pin 7**
- ☐ **TP13 (`ARM_PERMIT`)** ↔ **J1 pin 8**
- ☐ **TP14 (`RP2040_OK`)** ↔ **J1 pin 13**
- ☐ **J1 pin 5** (`PI_UART_TX`) — joint solid (no dedicated TP; ring to Pico TX pad or verify visually + wiggle)
- ☐ **J1 pin 6** (`PI_UART_RX`) — joint solid (ring to Pico RX pad or verify visually + wiggle)
- ☐ **J1 pin 9** (`MCP_INT_A`) — joint solid (ring to MCP INTA pad or verify visually + wiggle)
- ☐ **J1 pin 10** (`MCP_INT_B`) — joint solid (ring to MCP INTB pad or verify visually + wiggle)

### 2E — Field ground common (probe **TP5 `FIELD_GND`** ↔ each; FIELD domain — all beep)
- ☐ TP5 ↔ **J3 pin 9** (`FIELD_GND`)
- ☐ TP5 ↔ **J3 pin 10** (`FIELD_GND`)
- ☐ TP5 ↔ **J4 pin 14** (`FIELD_GND`)
- ☐ TP5 ↔ **J5 pin 12** (`FIELD_GND`)
- ☐ Confirm all four also read **OPEN to TP2** (already covered in Phase 1 — re-verify any that didn't)

### 2F — J13 lamp-return pins → their 330 Ω resistors (the row of "331" 0805s by J13)
- ☐ **J13 pin 3** (`LED_L_FIRST_RETURN`) ↔ **R90** — beep one pad / ~330 Ω other pad
- ☐ **J13 pin 4** (`LED_L_SECOND_RETURN`) ↔ **R93** — beep / ~330 Ω
- ☐ **J13 pin 5** (`LED_L_STRIKE_RETURN`) ↔ **R96** — beep / ~330 Ω
- ☐ **J13 pin 6** (`LED_L_FOUL_RETURN`) ↔ **R99** — beep / ~330 Ω
- ☐ **Wiggle test** on the two reseated J13 pins while probing — reading must stay solid

### 2G — J14 safety loop
- ☐ **J14 pin 1** (`VCC_5V`) ↔ **TP1** — beep
- ☐ **J14 pin 2** ↔ **J14 pin 3** — **beep** (bridged on-board, `SAFE_TBSC_RETURN`)
- ☐ **J14 pin 4** (`SAFE_STOP_RETURN`) ↔ **TP15** — beep
- ☐ **J14 pin 1 ↔ pin 2** — **OPEN** (loop open until an external NC contact closes it)
- ☐ **J14 pin 3 ↔ pin 4** — **OPEN** (second external loop)

### 2H — Motion-output terminals (relay dry contacts; J12/M1 is DNP — skip)
- ☐ **J6** (K1, S): both terminals solid joint to relay K1; no bridge to J7
- ☐ **J7** (K2, T): both terminals solid joint to K2; no bridge to neighbors
- ☐ **J8** (K3, SP): both terminals solid joint to K3; no bridge to neighbors
- ☐ **J9** (K4, BE): both terminals solid joint to K4; no bridge to neighbors
- ☐ **J10** (K5, M): both terminals solid joint to K5; no bridge to neighbors
- ☐ **J11** (K6, M2): both terminals solid joint to K6; no bridge to J10
- ☐ Note: pin 1↔pin 2 of each = relay contact (open or closed depending on G5LE NO/NC at rest) — **not** a fault by itself

### 2I — Adjacent-pin short scan (drag probes across neighbors; OPEN except noted ties)
- ☐ **J1** (20-pin) — all adjacent pairs OPEN (no two used pins share a net)
- ☐ **J2** — pin 2↔pin 3 **beep** (both GND, OK); pin 1↔pin 2 OPEN
- ☐ **J3** (10-pin) — all adjacent OPEN **except** pin 9↔pin 10 beep (both FIELD_GND, OK)
- ☐ **J4** (14-pin) — all adjacent pairs OPEN
- ☐ **J5** (12-pin) — all adjacent pairs OPEN
- ☐ **J13** (6-pin) — all adjacent pairs OPEN
- ☐ **J14** (4-pin) — pin 2↔pin 3 beep (OK); all other adjacent pairs OPEN

---

## PHASE 3 — First power-up (current-limited)

- ☐ Bench supply set: **5.0 V** (or ~5.3 V for full rail margin), **current limit ~200 mA**
- ☐ Connect supply to **J2** — **pin 1 = +5 V, pins 2/3 = GND**. Double-check polarity before switching on
- ☐ Switch on. **Steady current < ~100 mA** (Pico + 3× MCP + NE555 + pull-ups). Pegging the limit → **STOP**. → Record actual: __________ mA
- ☐ **TP1 (`VCC_5V`)** ≈ **4.6 V** (= 5 V − SS14 drop; expected). → Record: __________ V
- ☐ **TP3 (`VCC_3V3`)** ≈ **3.3 V** (confirms Pico is alive and regulating). → Record: __________ V
- ☐ **TP4 → TP5** (`FIELD_WET_V`) ≈ **+5 V isolated** (measure to TP5, not TP2). → Record: __________ V
- ☐ **TP5 ↔ TP2 still OPEN under power** (isolation holds live)
- ☐ **No part hot** — finger-touch A1, U37, U1/U2/U3 (MCP), the NE555, the FETs, K1–K6. Anything more than mildly warm → **STOP, power off**
- ☐ **TP16 (`RELAY_ENABLE_RAIL`)** — record state (likely held LOW until firmware drives the watchdog kick + ARM): __________ V

---

## RESULT

- ☐ **PASS** — all phases clean; board cleared for functional bring-up (I²C enumerate MCPs @ 0x20/0x21/0x22, relay-click, watchdog rail-drop)
- ☐ **HOLD** — issue(s) found (note below)

**Notes / anomalies:**

________________________________________________________________

________________________________________________________________

________________________________________________________________

| | |
|---|---|
| Tester signature | ____________________ |
| Date / time | ____________________ |
