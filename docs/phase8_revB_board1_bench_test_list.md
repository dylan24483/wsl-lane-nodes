---
title: "WSL Phase 8 rev-B Board #1 — Bench Test List"
---

# WSL Phase 8 rev-B — Board #1 Bench Test List

| Field | Value |  | Field | Value |
|---|---|---|---|---|
| Board ID | __________ | | Date | __________ |
| Tester | __________ | | DMM | __________ |
| Bench supply | ______ V / ______ mA limit | | | |

**Grounded from the live netlist.** Pair this with the **probe-locations map (page 1)** and the connector pin-number map. Do Phases 0–2 fully **before any power**. Meter notes: shorts on continuity/low-Ω ("NOT shorted" = reads high, not a steady beep — caps make rail readings *climb*, that's normal). Continuity = beep ≈ 0 Ω; probe **pin metal**, not flux/plastic. **Logic → reference TP2 (GND); field → reference TP5 (FIELD_GND); never bridge a lead across TP2↔TP5.**

> **STOP if:** any rail↔ground short · ANY `FIELD_GND`↔`GND` continuity · current pegs the limit · any part heats. Power off and find it.

---

## PHASE 0 — Visual (no meter, both sides, magnification)
- ☐ **Flux cleaned** (90 %+ IPA + brush) around the Pico, test points, and joints — needed so probing isn't fooled by insulating residue and so you can actually see the joints. Dry fully before power; keep solvent out of the USB jack and relays.
- ☐ No bridges/balls/whiskers — **top side** · ☐ **bottom side**
- ☐ Dense areas clean: **A1 Pico castellations**, **U1/U2/U3 MCP** leads, **PC817 opto bank**, **K1–K6** relay pins, **U37** pins
- ☐ **A1 Pico** — every castellation has a concave fillet (notch→pad), shiny, **no bridges**, module flat; **USB + pin-1 (GP0) oriented per silk**
- ☐ **U37** square pad = pin 1 = +Vin; body flush. ☐ **D17 (SS14)**, **D15/D16, D1/D3/D5/D7/D9/D11/D13 (1N4148)** cathode bands match silk. ☐ **C11** (–) stripe matches silk. ☐ **K1–K6** seated, **K7 + the MOVs empty (DNP, correct)**
- ☐ Every connector body flush/square; J13 reseated pins OK

## PHASE 1 — Short check (SUPPLY DISCONNECTED)
- ☐ **TP1 VCC_5V ↔ TP2 GND** — NOT shorted *(STOP if 0 Ω)*
- ☐ **TP3 VCC_3V3 ↔ TP2 GND** — NOT shorted
- ☐ **TP1 VCC_5V ↔ TP3 VCC_3V3** — NOT shorted
- ☐ **J2 pin 1 VCC_5V_RAW ↔ TP2 GND** — NOT shorted (input side)
- ☐ **TP4 FIELD_WET_V ↔ TP5 FIELD_GND** — NOT shorted
- ☐ **TP5 FIELD_GND ↔ TP2 GND** — **OPEN** *(isolation barrier — STOP on any beep)*
- ☐ **TP4 FIELD_WET_V ↔ TP2 GND** — OPEN · ☐ **TP4 ↔ TP1 VCC_5V** — OPEN

## PHASE 2 — Continuity / joints (unpowered)

**2A · Logic ground (probe TP2 ↔ each, all beep):**
- ☐ J2 pin 2 · ☐ J2 pin 3 · ☐ J1 pin 2 · ☐ J1 pin 12 · ☐ J13 pin 2 · ☐ C11 (–) leg

**2B · Logic +5 V (probe TP1 ↔ each, all beep):**
- ☐ J1 pin 1 · ☐ J13 pin 1 · ☐ J14 pin 1

**2C · D17 reverse-protection diode (DIODE-TEST mode):**
- ☐ **D17 anode (J2-side pad, 103,24) → cathode (banded, 99,24):** ~**0.3 V forward**, **OPEN reversed** → D17 present + correctly oriented
- ☐ J2 pin 1 (VCC_5V_RAW) ↔ D17 anode = beep (same net). *(J2 pin 1 ↔ TP1 is NOT a plain beep — it goes through D17.)*

**2D · Pico power joints (use the Pico's printed labels):**
- ☐ **Pico GND pad → TP2** (beep) · ☐ **Pico 3V3(OUT) pin 36 → TP3** (beep) · ☐ **Pico VSYS pin 39 → TP1** (beep)

**2E · 3V3 + named signals (probe TP ↔ J1 pin, beep):**
- ☐ TP3 ↔ J1 pin 11 · ☐ TP6 SDA ↔ J1 pin 3 · ☐ TP7 SCL ↔ J1 pin 4 · ☐ TP8 WDOG_KICK ↔ J1 pin 7 · ☐ TP13 ARM_PERMIT ↔ J1 pin 8 · ☐ TP14 RP2040_OK ↔ J1 pin 13
- ☐ **J1 pins 5/6/9/10** (UART_TX/RX, INT_A/B): **visual + wiggle** is enough. ⚠️ Only if a joint looks suspect, ring to the IC pad with a **fine tip** — Pico TX = A1 pin 2/GP1 (114,33), RX = A1 pin 1/GP0 (114,31); INTA = U1 pin 19 (127,107); INTB = U2 pin 19 (127,149). **Don't risk bridging fine-pitch pins.**

**2F · Field ground (probe TP5 ↔ each, beep; field domain):**
- ☐ J3 pin 9 · ☐ J3 pin 10 · ☐ J4 pin 14 · ☐ J5 pin 12  *(all also OPEN to TP2 — see Phase 1)*

**2G · J13 lamp returns → 330 Ω resistors (row of "331" 0805s by J13):**
- ☐ J13 pin 3 ↔ **R90** · ☐ pin 4 ↔ **R93** · ☐ pin 5 ↔ **R96** · ☐ pin 6 ↔ **R99** (beep one pad / ~330 Ω other) · ☐ wiggle the two reseated pins

**2H · J14 safety loop:**
- ☐ pin 1 ↔ TP1 (beep) · ☐ pin 2 ↔ pin 3 (beep, bridged) · ☐ pin 4 ↔ TP15 (beep) · ☐ pin 1↔2 OPEN · ☐ pin 3↔4 OPEN

**2I · Adjacent-pin short scan (OPEN except noted ties):**
- ☐ **J1** all adjacent OPEN · ☐ **J2** pin2–3 beep (GND, OK), pin1–2 OPEN · ☐ **J3** all OPEN except pin9–10 beep · ☐ **J4** all OPEN · ☐ **J5** all OPEN · ☐ **J13** all OPEN · ☐ **J14** pin2–3 beep, rest OPEN

**2J · Motion-output terminals J6–J11 (pin 2 = COM, pin 1 = NO):**
- ☐ Each terminal pin → its relay Kn contact = beep (joint), or visual + wiggle
- ☐ **Pin 1 ↔ pin 2 = OPEN** on every J6–J11 (NO contact open at rest). *(Closed at rest = bridge or welded contact → investigate.)*
- ☐ No bridge to neighbor connector. *(J6=S/K1, J7=T/K2, J8=SP/K3, J9=BE/K4, J10=M/K5, J11=M2/K6; J12=DNP.)*

## PHASE 3 — First power-up (current-limited)
- ☐ Supply **5.0 V** (or ~5.3 V for full rail margin), **limit ~200 mA**; feed **J2** (pin 1 +5 V, pin 2/3 GND) — recheck polarity
- ☐ **Steady current < ~100 mA** → record ______ mA *(pegs limit → STOP)*
- ☐ **TP1 ≈ 4.6 V** (5 V − SS14 drop, expected) → ______ V · ☐ **TP3 ≈ 3.3 V** (Pico alive) → ______ V
- ☐ **TP4→TP5 ≈ +5 V isolated** (to TP5, not TP2) → ______ V · ☐ **TP5↔TP2 still OPEN** under power
- ☐ **No part hot** — touch A1, U37, U1/U2/U3, NE555, FETs, K1–K6

## PHASE 4 — Functional (powered, Pi/firmware in the loop)
- ☐ **Pico boots** — TP3 holds 3.3 V (confirms Pico power/GND/3V3 joints)
- ☐ **I²C enumerate** — all three MCP23017 answer at **0x20 / 0x21 / 0x22** (confirms SDA/SCL joints + Pico running)
- ☐ **Watchdog** — stop kicking GPIO12 → RELAY_ENABLE_RAIL (TP16) drops within ~10–11 s
- ☐ **Relay / motion outputs** — with the rail enabled (watchdog kicked + ARM_PERMIT high + J14 loop closed), assert each channel via its MCP output:
  - ☐ J6 (S/K1) · ☐ J7 (T/K2) · ☐ J8 (SP/K3) · ☐ J9 (BE/K4) · ☐ J10 (M/K5) · ☐ J11 (M2/K6)
  - For each: relay **audibly clicks**, and **meter across the terminal pins goes OPEN → ~0 Ω when energized**, back to OPEN when released (COM↔NO makes/breaks)

---

## Probe-point quick reference (the 10 extra pads)
| Item | Where | Coord |
|---|---|---|
| D17 anode | SMA diode by J2; pad on the **J2 side / un-banded** end | (103, 24) |
| D17 cathode | same diode, **banded** end (VCC_5V/TP1 side) | (99, 24) |
| Pico TX | A1 **pin 2 (GP1)**, Pico pin-1 corner (away from USB) | (114, 33) |
| Pico RX | A1 **pin 1 (GP0)**, next to TX | (114, 31) |
| MCP INTA | **U1 pin 19** (upper MCP) | (127, 107) |
| MCP INTB | **U2 pin 19** (lower MCP) | (127, 149) |
| R90 / R93 / R96 / R99 | row of four "331" 330 Ω by J13 (= J13 pins 3/4/5/6) | (104/116/128/140, 182) |

---

## RESULT
- ☐ **PASS** — cleared for full functional bring-up / lane install
- ☐ **HOLD** — issue(s) noted below

Notes: ______________________________________________________________

______________________________________________________________

Tester ____________________  Date/time ____________________
