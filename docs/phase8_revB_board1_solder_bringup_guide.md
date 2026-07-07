# WSL Phase 8 rev-B — Board #1 Hand-Solder & First-Power Guide

**Scope:** the hand-solder pass on a JLC-assembled rev-B lane-controller board, then the **logic-only bench bring-up** (spec §12.9). The board is **not on a machine** — the only hazards here are ESD and solder shorts to the board, not machine motion. This is the gate that proves one assembled board before any machine work.

**How this was built:** six sections, each grounded agent-by-agent in the live design files — pinouts from `scripts/generate_kicad_netlist_revB.py`, test points + thermal-mass from `13_layout-mfg.md`, the rail-fit order from `06_board-power.md`, the bring-up sequence from `21_bringup-cutover.md`, and the flash steps from `firmware/rp2040/README.md`. Where a fact isn't fixed in the sources it's flagged `(VERIFY: …)`.

---

## What's on the board vs. what you solder
**JLC already placed (confirmed from the received-board photo):** 32× PC817B optos (U4–U35), 6× G5LE-14 **5 VDC** relays (K1–K6), 3× MCP23017 (U1–U3), NE555 (U36), the 100 µF electrolytic (C11), and all SOT-23/0805 parts.

**Your hand-solder set (all currently empty):** A1 (Pico), U37 (TMA-0505S), and connectors J1–J11, J13, J14. **J12 / M1 stays DNP — leave the 7th relay spot empty.**

## TL;DR — the safe path (full detail in the sections below)
**Solder power-critical-first and verify each rail as you create it — don't stuff the whole board then power once.**

1. **J2** (Phoenix 1715734) → 5 V in → **TP1 `VCC_5V` ≈ 4.6–4.8 V**
2. **A1** (Pico SC0915) → **TP3 `VCC_3V3` ≈ 3.3 V**
3. **U37** (TMA 0505S) → **TP4 `FIELD_WET_V` ≈ 5 V** AND **TP5 `FIELD_GND` OPEN to TP2 `GND`** (isolation proof)
4. **J1** (CNC Tech 3020-20-0100-00) → Pi link
5. **J14** (1843622) → safety loop, then **J6–J11**, **J3/J4/J5**, **J13**

**Four board-killers:**
- **U37 polarity** — match pin 1 to silk, **never flip** (it's the isolation barrier).
- **A1 Pico** — Micro-USB end overhangs the board edge per silk.
- **Before power** — check for fine-pitch bridges (3× SOIC-28 MCP, SOIC-8 NE555) and **no short** `VCC_5V`→`GND` / `VCC_3V3`→`GND`. Bench supply current-limited to ~500 mA so a bridge trips the limit, not a trace.
- **ESD** — wrist strap on for A1 + U37.

**Firmware:** the flashable `.uf2` is already built at `firmware/rp2040/build/wsl_phase8b_rp2040.uf2` (BOOTSEL drag-drop).

## Contents
1. Safety, ESD & Go/No-Go
2. Solder Order & Technique
3. Part-to-Silkscreen Map & Orientation
4. Connector Pinouts (J1–J14)
5. First Power & Test-Point Verification (the §12.9 sequence)
6. Troubleshooting

---

## Safety, ESD & Go/No-Go

> **Read this whole section before you apply power.** It is short on purpose, and every rule here is enforced by the board's hardware — not by your discipline alone. The one thing it asks of you is to bring the board up in *order* and to *stop* the moment a stage doesn't pass.

### S.0 What this bench session actually is — and the one risk you DON'T have

This board is on your bench. **No pinsetter is connected.** J6–J11 (the relay motion outputs) land in empty Phoenix screw terminals; J14's interlock loops are jumpered with wire, not wired into a machine; the camera/cams/grippers are not present. There is therefore **no machine-motion hazard in this session at all** — nothing can sweep, no table can drop, nothing can crush a hand. The cutover sections of the manual (§19, §21.3) are written around lockout/tagout and a machine that "moves and bites"; **none of that applies here.** This is **pure logic-only bench bring-up** (`21_bringup-cutover.md` §21.2: *"on a workbench, nowhere near a machine … with zero risk"*).

The only two hazards in this session are **to the board, not to you**:

1. **ESD** — A1 (the Pico) and U37 (the TRACO DC/DC) are the static-sensitive hand-solder parts. The MCP23017s, optos, NE555, and FETs are already placed and survived JLC's line, but you'll be handling the whole board.
2. **Solder shorts** — a bridge on a fine-pitch IC or a backwards electrolytic/diode can short a rail the instant you power up. The pre-power inspection (S.2) is what catches these *before* they let smoke out.

### S.1 Understand WHY the relays stay silent — the relay-enable rail (so you don't chase a "dead" board)

The single most important thing to internalize before you power up: **on a correctly-built board, the motion relays K1–K6 will NOT click when you first apply 5 V, and that is correct, not a fault.** If you don't understand this you will waste an hour "debugging" a board that is working perfectly.

Every motion relay coil hangs off a gated supply called `RELAY_ENABLE_RAIL` (test point **TP16**), *not* directly off 5 V (`06_board-power.md` §6.5; `12_channel-maps.md` §12.11). That rail is the drain of a P-channel pass-FET (**Q14**, AO3401A) and it is live **only when a hardware AND of six independent conditions is ALL true at once** (`19_safety-architecture.md` §19.2.5; `21_bringup-cutover.md` §21.1). Software cannot bypass any of them. Every condition's default state is **false/open** — the board is **fail-open by construction** (`22_troubleshooting.md` §22.0 item 6: *"a dead rail during diagnosis is the safe state, not necessarily a fault."*).

The six conditions, and why each is dead on a freshly-powered bare board:

| # | Condition | Source | Default state on a cold board | Why it's false at first power-up |
|---|---|---|---|---|
| 1 | **Watchdog OK** | NE555 (U36) kicked by the Pi on `WDOG_KICK` (J1 pin 7) → Q13 | false | No Pi kicking yet → NE555 times out → Q13 off |
| 2 | **Arm OK** | Pi `ARM_PERMIT` (J1 pin 8) → Q15 | false (R108 100k base pulldown) | Pi hasn't asserted ARM |
| 3 | **RP2040 OK** | Pico `GP2` (`RP2040_OK`, J1 pin 13) → Q16 | false (R110 100k pulldown; GP2 Hi-Z on reset) | Pico not booted / GP2 Hi-Z |
| 4 | **Cam-stop OK** | folds into #3 (firmware drives GP2 LOW on a cam-stop fault) | false | same path as #3 — *not a separate transistor* |
| 5 | **TB/SC interlock** | external NC loop on J14 pins **1↔2** | open | nothing wired across J14 |
| 6 | **Stop/CIS/master chain** | external NC loop on J14 pins **3↔4** | open | nothing wired across J14 |

Two structural facts (verified against `block_rail()`, per `19_safety-architecture.md` §19.2.5 and `22_troubleshooting.md` §22.4.2):

- **Conditions 5 & 6 are NC loops in series with the FET *source*.** +5 V enters J14 pin 1 → must traverse the closed TB/SC loop (1→2) → cross the on-board jumper (`SAFE_TBSC_RETURN`, J14 pin 2 = pin 3) → traverse the closed Stop/CIS loop (3→4, `SAFE_STOP_RETURN`) → only then reach Q14's source. **Break either loop and no gate state on earth can turn the rail on.**
- **Conditions 1, 2, 3(=4) are a series transistor stack on the FET *gate*.** The gate (`RAIL_GATE`) is held up to the source by R106 (100k) — off by default. Q15 (ARM) · Q16 (RP2040_OK) · Q13 (watchdog) must **all three conduct** to pull the gate low and turn the P-FET on. Any one open → rail dead.

> **Bench consequence:** to make the rail come up on the bench you must *deliberately* satisfy all six — including jumpering J14 1–2 and 3–4 closed (S.3 stage E). **Do NOT jumper J14 pin 1→4** to "make it work" — that bypasses both interlocks and is the one bench shortcut that defeats the whole safety model (`11_connector-pinouts.md` §11.9). On a machine this rail is what guarantees the board can only ever *fail to permit* motion, never *cause* it; on the bench it's just the thing you prove drops cleanly six different ways.

### S.2 ESD handling for the hand-solder parts (A1, U37)

A1 (Raspberry Pi Pico SC0915) and U37 (TRACO TMA-0505S) are the parts you'll be soldering. The CLAUDE.md project rule and the Pi-GPIO memory both stress static discipline; for the DC/DC and the Pico:

1. **Wrist strap + grounded mat.** Wear an ESD wrist strap clipped to a grounded mat (or to the bench's ground point). The Pico's castellated module and the DC/DC's exposed SIP pins are both handled directly.
2. **Keep parts in their ESD bags / trays until the moment you place them.** Don't fan them out on a cloth bench surface.
3. **Iron must be ESD-safe / grounded-tip.** A floating-tip iron can dump static into the part you're soldering.
4. **Touch the board's GND (TP2) before handling.** Equalize potential with the board before each handling session.
5. **No carpet, no synthetic clothing static.** Standard bench hygiene; the WSL Pi-voltage memory already flags 3.3V-only sensitivity — treat the whole logic side as static-sensitive.
6. **Use the castellated SC0915, NOT a Pico H/WH with header pins** (`hand-solder-bom.csv` A1 note; `22_troubleshooting.md` §22.9.1). A headered Pico will not fit the A1 footprint.

### S.3 Pre-power inspection checklist (do this BEFORE applying 5 V at J2)

Bridges and reversed polarized parts are the failure mode that kills a board on first power. Inspect under magnification, both sides, before the supply touches J2. The recommended solder order is **J2 → A1 → U37 → J1 → J14 → J6-J11 → J3/J4/J5 → J13**; run this inspection on whatever you've placed so far, and re-run the relevant rows after each new part.

**(a) Fine-pitch IC bridges — the 3× MCP23017 (SOIC-28W) + the NE555 (SOIC-8):**

- [ ] **U1, U2, U3 (MCP23017, SOIC-28W, P1.27mm):** sight down each side of all three for solder bridges between adjacent legs. These are 1.27 mm pitch — the most likely place for a JLC reflow whisker. A bridge on the I²C or address-strap pins will NAK the bus.
- [ ] **U36 (NE555DR, SOIC-8):** same — check all 8 legs. A short here corrupts the watchdog timing or VCC.
- [ ] Confirm **pin-1 orientation** on all four: the dot/notch on each IC matches the silk pin-1 datum. (JLC placed them, but verify — a reflowed-rotated part is rare but board-killing.)
- [ ] Glance the SOT-23 FET/BJT cluster around the rail (Q12/Q13 AO3400A, Q14 AO3401A, Q15/Q16 MMBT3904): **do not assume N-ch and P-ch are interchangeable** — Q14 is the *P-channel* AO3401A rail pass-FET; Q12/Q13 are *N-channel* AO3400A; they look identical in SOT-23 (`22_troubleshooting.md` §22.9.2 critical note). You can't fix a swap (JLC placed them) but flag it if you find one — it would explain a rail that never comes up.

**(b) C11 electrolytic polarity (the 100 µF / 16 V watchdog timing cap):**

- [ ] **C11** is the only polarized electrolytic and it sets the NE555 monostable timeout (`C_WDOG_TIMING`, 100 µF/16 V, per `21_bringup-cutover.md` §21.2.1 step 4 and `12_channel-maps.md` §12.10). Confirm the **minus stripe / short leg faces the silk's negative mark.** Backwards = it bulges/vents on power and the watchdog timing is wrong. JLC placed it, but it's the highest-consequence polarized part on the board — eyeball it.
- [ ] **D17 (SS14 Schottky, SMA):** confirm the cathode band matches the silk. Anode → `VCC_5V_RAW`, cathode → `VCC_5V` (`06_board-power.md` §6.2.2). Backwards = no 5 V reaches the board at all (and is also your reverse-polarity guard, so a backwards D17 defeats that protection).
- [ ] **D2-class flyback/steering diodes** (1N4148WS, SOD-323) — cathode bands per silk if you're spot-checking; JLC-placed.

**(c) Opto / relay / IC pin-1 orientation:**

- [ ] **U4–U35 (32× PC817B, DIP-4):** scan that pin-1 (the LED-anode corner, marked by the chamfer/dot) faces the silk pin-1 on all 32. A reversed opto won't conduct the right way. (JLC-placed, but 32 parts is 32 chances.)
- [ ] **K1–K6 (G5LE-14 relays):** seated flat, correct orientation per silk outline. **Confirm these are the 5 VDC coil variant** — the BOM is explicit: *do not substitute 9V/12V/24V coil* (`06_board-power.md` §6.5; `22_troubleshooting.md` §22.9.2). **K7/J12 (M1) is DNP — confirm it is empty.**
- [ ] **A1 (Pico)** when fitted: castellations fully wetted, module flat, pin-1 / USB-end matches the silk "J1 PI / LOGIC / SAFETY" datum.
- [ ] **U37 (TMA-0505S)** when fitted: pin-1 to silk. This part is *isolated* — getting it backwards or bridging primary↔secondary defeats the FIELD_GND isolation barrier (see (d)).

**(d) Bottom side clean + isolation intact:**

- [ ] Flux residue cleaned, **no stray solder balls** on either side (a loose ball bridging LOGIC↔FIELD across the keepout gutter is the worst case).
- [ ] **`FIELD_GND` must share ZERO nodes with `GND`.** With the board unpowered, meter continuity between **TP5 (`FIELD_GND`)** and **TP2 (`GND`)** → must read **OPEN / no continuity** (`06_board-power.md` §6.9; `22_troubleshooting.md` §22.0 item 4). If they beep continuous, you have a solder bridge across the isolation barrier or U37 fitted wrong — **STOP and fix before powering**. Do this check *after* fitting U37, and never bond the two grounds with a probe clip or scope ground during testing.
- [ ] Quick rail-short check, board unpowered: meter resistance **TP1 (`VCC_5V`) → TP2 (`GND`)** and **TP3 (`VCC_3V3`) → TP2**. A dead-short (near 0 Ω) on either means a bridge — find it before applying power. (Expect tens of kΩ to a few hundred Ω, not 0 Ω.)

### S.4 The per-stage GO / NO-GO gates

Bring the board up in the documented order: **power rails → I²C enumerate → RP2040 boot → watchdog drop → arm drop → interlock drop → relays → inputs** (`06_board-power.md` §6.8; `22_troubleshooting.md` §22.0 item 5; firmware README §"Bench bring-up"). **The governing rule: each stage gates the next. If a rail check fails, STOP and fix it before adding the next part — do not stack a second fault on top of an unverified rail** (`21_bringup-cutover.md` §21.2.1: *"each step gates the next"*).

Use the test pads as your meter taps — **probe TPx, not IC legs**. Net-per-TP map (`21_bringup-cutover.md` §21.2.2 / `11_connector-pinouts.md` §11.10):

| TP | Net | TP | Net |
|---|---|---|---|
| TP1 | `VCC_5V` | TP9 | `WDOG_TIMING_NODE` |
| TP2 | `GND` | TP10 | `NE555_TRIG` |
| TP3 | `VCC_3V3` | TP11 | `NE555_OUT` |
| TP4 | `FIELD_WET_V` | TP12 | `WDOG_OK_PULLDOWN` |
| TP5 | `FIELD_GND` | TP13 | `ARM_PERMIT` |
| TP6 | `I2C_SDA` | TP14 | `RP2040_OK` |
| TP7 | `I2C_SCL` | TP15 | `SAFE_STOP_RETURN` |
| TP8 | `WDOG_KICK` | **TP16** | **`RELAY_ENABLE_RAIL`** ← the single most useful tap |

**Gate-by-gate "what pass looks like" (probe values from `06_board-power.md` §6.9 and `21_bringup-cutover.md` §21.2.1):**

| Stage | What you do | GO (pass) | NO-GO → STOP and… |
|---|---|---|---|
| **A. Rails** | 5 V into **J2** pin 1 (`VCC_5V_RAW`), GND on pins 2/3. (J2 soldered first.) | **TP1 ≈ 4.6–4.8 V** (5 V minus SS14 Vf). **TP3 ≈ 3.3 V** *only after A1 fitted* (Pico sources 3V3). **TP4 ≈ 5 V isolated** *only after U37 fitted*. **TP5↔TP2 = OPEN** (isolation). No part hot to the touch. | Rail wrong/short → check D17 orientation, U37 fit, the S.3(d) short check, A1 fit. **Do not fit the next part on a bad rail.** Note: TP3 dead before A1 is fitted is *expected* — there is no 3.3 V until the Pico is on (`06_board-power.md` §6.3). |
| **B. I²C enumerate** | Pi connected via **J1**; scan the board's I²C bus. | All **3× MCP23017** answer: **0x20 (U1, IN-A), 0x21 (U2, IN-B), 0x22 (U3, OUT-A)** (`12_channel-maps.md` §12.3). | A chip NAKs → re-check that chip's solder/bridges (S.3a), the 4.7k pull-ups (R1/R2), and the A0/A1/A2 address straps. |
| **C. RP2040 boot** | Flash `firmware/rp2040/build/wsl_phase8b_rp2040.uf2` (BOOTSEL drag-drop), power up; watch UART (J1 pins 5/6, 115200-8N1). | A `boot` line, then `hb` heartbeats at ~4 Hz with `ok:1`. After ~200 ms (`BOOT_SETTLE_MS`) **TP14 (`RP2040_OK`/GP2) goes HIGH** (`rp_ok:1`). | No boot/hb → check Pico solder, UART crossover (Pi TX→Pico GP1, Pico GP0→Pi RX — *crossover is done on the PCB, wire the ribbon straight*, `11_connector-pinouts.md` §11.2). GP2 stuck LOW → firmware not healthy / a latched fault. |
| **D. Watchdog drop** | With the rail armed on the bench-safe path (all six conditions satisfied — see E), **stop kicking `WDOG_KICK`**. | After the NE555 timeout, **TP16 drops to ~0 V.** Watch the transition at TP11 (`NE555_OUT`) / TP12 (`WDOG_OK_PULLDOWN`). | Rail won't drop → the watchdog AND-rung isn't gating. Check the NE555 RC (R100 100k, C11 100µF), the trigger pull-up (10k), Q13. **(VERIFY: NE555 timeout is bench-measured, NOT assumed — design RC ≈ 11 s but it's a retrigger topology; measure it, don't trust ~10 s** — `19_safety-architecture.md` §19.2.4 / `22_troubleshooting.md` §22.7.) |
| **E. Arm + interlock drops** | First satisfy all six conditions so the rail is live (kick the watchdog, assert ARM, GP2 high, and **jumper J14 1–2 and 3–4 closed**) → confirm **TP16 ≈ VCC_5V**. Then knock out one condition at a time: de-assert `ARM_PERMIT` (TP13 low); then open the **TB/SC** loop (J14 1–2); then open the **Stop/CIS** loop (J14 3–4). | **TP16 drops to ~0 V on EACH** independent knock-out. TP15 (`SAFE_STOP_RETURN`) goes open/low when a J14 loop opens. | Any one fails to drop the rail → that safety condition is not gating. **This is the heart of the safety proof — do not move on until all of them drop the rail independently.** Confirm the J14 jumpers were actually closed for the "live" baseline; check Q14 (rail pass-FET), Q15 (ARM AND). |
| **F. Each relay (dummy load)** | Re-establish all rail conditions. Command each motion relay (**S, T, SP, BE, M, M2** = K1–K6) in turn via MCP OUT-A (0x22). Put a dummy load (lamp/resistor) across that relay's J6–J11 contact pair. | Relay clicks; its COM-NO contact closes the dummy load; **the load drops the instant you drop the rail** (proving the rail gates the coil, not just the command). **M1 (K7/J12) is DNP — not tested.** | Relay won't fire with rail up → check the per-relay NPN (Q1–Q6), the OUT-A bit↔relay map (S=(0,0) … M2=(0,5); M2 is bit 5 *before* M1 — `12_channel-maps.md` §12.7), the flyback. |
| **G. Inputs** | Exercise each opto: wet a fast input pin (J3) to `FIELD_GND`; wet each slow input (J4/J5). | The matching RP2040 fast-input edge (`cam`/`ball` over UART) or MCP bit flips. **Optos are active-LOW** — a closed field contact pulls the logic pin LOW (`12_channel-maps.md` §12.2.2). | No flip → check the PC817 (U4–U35), `Rin` 2.2k, the 10k logic pull-up to 3V3, and that `FIELD_WET_V` (TP4) is present (needs U37). |

**Pass = stages A–G all green and logged.** Only then is the board a candidate for the cutover work in §21.3 (gate **G1**) — which is a *separate, future, at-a-machine* operation, not part of this bench session.

> **Note on the cam-stop sub-test (firmware caveat).** The shipped firmware provides RP2040 *health* + the *motion max-run* backstop (`MAX_MOTION_MS` = 8000 ms). You can prove the GP2→rail drop path directly (reset/halt the Pico → TP16 drops) and the max-run sense (mark a motor RUN, let it exceed 8 s → fault → TP16 drops). True **per-cam-edge cam-stop overrun** enforcement ships **default OFF** (v1.1 flags gated until per-cam edge→angle polarity is field-captured at cutover — firmware README ⛔ banner; `19_safety-architecture.md` §19.3.4). That is a cutover-day item; it does **not** block your logic-only bench bring-up.

### S.5 The one rule to carry through the whole session

**If a rail check fails, STOP and fix it before adding the next part.** Don't fit U37 onto an unverified 5 V rail; don't flash the Pico onto a board whose I²C won't enumerate; don't command a relay before TP16 has been proven to come up *and* drop six different ways. The board is designed to fail open — a dead rail mid-bring-up is the safe, expected state, not necessarily a defect (`22_troubleshooting.md` §22.0 item 6). Your job at the bench is to prove, stage by stage, that it comes *up* when all conditions are met and goes *dead* the instant any one is removed.

---

**Source files grounding this section** (all absolute):
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\19_safety-architecture.md` (§19.2.5 six-condition rail, §19.2.6 welded-contact, §19.3.4 v1.1 cam-stop deferral)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\21_bringup-cutover.md` (§21.1 rail summary, §21.2.1 bring-up steps, §21.2.2 TP map)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\06_board-power.md` (§6.5 rail topology, §6.8 fit order, §6.9 power TP expected values)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\11_connector-pinouts.md` (§11.2 J1, §11.9 J14, §11.10 TP cross-ref)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\12_channel-maps.md` (§12.3 MCP addrs, §12.7 OUT-A map, §12.10 watchdog timing)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\22_troubleshooting.md` (§22.0 safe handling, §22.4.2 six conditions, §22.9.2 critical-substitution notes)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\firmware\rp2040\README.md` (safety model, bench bring-up, v1.1 flags-OFF banner; `.uf2` at `firmware\rp2040\build\wsl_phase8b_rp2040.uf2`)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\fab_revB_routed_manual\assembly\wsl-phase8b-revB-hand-solder-bom.csv` (A1/U37/J-connector parts + critical notes)

**Flagged for verification at the bench (carried from the source docs):**
- **NE555 watchdog timeout is bench-MEASURED, not assumed** — design RC ≈ 11 s but it's a retrigger topology; do not assume ~10 s (§19.2.4 / §22.7).
- **C11 is 100 µF / 16 V electrolytic, polarized** — verify the minus stripe against silk before power (highest-consequence polarized part).
- **Q14 = P-channel AO3401A vs Q12/Q13 = N-channel AO3400A** — visually identical SOT-23; a swap (JLC-placed) would explain a rail that never comes up.
- **Pin-1 datum for A1 (Pico) and U37 (TMA-0505S)** — confirm against the silk before/after soldering; U37 backwards also defeats FIELD_GND isolation.

---

## Solder Order & Technique

This is the hand-solder pass on a JLC-assembled Rev-B board (`A1`, `U37`, and the Phoenix/IDC connectors `J1–J11`, `J13`, `J14` are the empty parts; `J12`/`M1` stay DNP — leave it empty). Work the order **power-critical-first and verify each rail as you create it.** Do **not** stuff the whole board and then power it once — the whole point of the staging is that if a rail comes up wrong you know exactly which part you just fitted caused it, on an otherwise-bare board, instead of hunting across 14 connectors and two actives at the end.

### 0. Bench setup, ESD, and the one safety note

- **This is logic-only bench bring-up.** The board is not on a machine; the only hazards are to the board — ESD and solder bridges — not machine motion. (`21_bringup-cutover.md` §21.2: "prove one assembled board… with **zero risk** — the board is on a bench, not on a machine.")
- **ESD matters for A1 and U37.** The Pico (RP2040) and the TMA-0505S DC/DC are the two static-sensitive hand-solder parts. Wear a grounded wrist strap, work on an ESD mat, and keep both parts in their bags until you fit them. The JLC-placed actives (3× MCP23017, 32× PC817B, NE555, the FETs) are already on and survived reflow, but ground yourself anyway before touching the board.
- **Iron + consumables.** Temperature-controlled iron; a chisel tip (2–3 mm) for the Phoenix THT joints and a fine conical for the Pico castellations. **Use flux** — a flux pen or a dab of no-clean paste on every THT pad and along the Pico edge. Have solder wick and a meter on hand. Eutectic 63/37 or SAC305 both fine; set the iron accordingly (see per-part temps below).
- **Thermal-mass warning (read before the first Phoenix joint).** This is a **250 × 225 mm, 4-copper-layer, 1.6 mm board** (`13_layout-mfg.md` §13.0). The `In1.Cu` GND plane and `In2.Cu` power pour are heavy internal copper, and `GND` / `VCC_5V` are poured at **0.50 mm** trace with `RELAY_ENABLE_RAIL` at **0.60 mm** (`13_layout-mfg.md` §13.2). Any pin tied to one of those planes — every GND landing on J2, J1, J13, J14; the 5 V pins — is a **massive heatsink.** A 25–30 W iron at a normal tip temp will make a cold ring around a plane pin while the solder looks shiny on the pad side. Plan for higher wattage / higher tip temp / longer dwell on plane-connected pins (details per part below).

### 1. Solder order (and why it interleaves with rail checks)

Follow this order. The rail checks in **bold** are the gates — do them on the bench meter at the test pads (TP map in `21_bringup-cutover.md` §21.2.2) before moving on.

| # | Part(s) | Why here / what it creates | Verify before next step |
|---|---|---|---|
| 1 | **J2** (5 V screw terminal) | The board's power entry. Nothing can be checked until 5 V can land. | Visual + continuity only (no power yet). |
| 2 | **A1** (Pico) | Sources `VCC_3V3` from its own regulator (pin 36). **No A1 → no 3.3 V → MCPs and opto pull-ups stay dark** (`06_board-power.md` §6.3). | After power-on: **TP1 `VCC_5V` ≈ 4.6–4.8 V**, **TP3 `VCC_3V3` ≈ 3.3 V**. (`06_board-power.md` §6.9) |
| 3 | **U37** (TMA-0505S) | Creates the isolated field-wetting rail `FIELD_WET_V`. **No U37 → dry-contact inputs cannot be sensed** (`06_board-power.md` §6.4.). | **TP4 `FIELD_WET_V` ≈ 5 V isolated**, and **TP5 `FIELD_GND` shows OPEN to TP2 `GND`** (isolation intact — `06_board-power.md` §6.9 / `13_layout-mfg.md` audit: GND and FIELD_GND share **0** nodes). |
| 4 | **J1** (2×10 IDC, Pi) | The only logic link to the Pi — I²C, UART, watchdog kick, arm, RP2040_OK, and both rails. Needed for the I²C-enumerate and heartbeat steps. | Continuity check J1 pin 1→TP1, pin 11→TP3, pins 2/12→TP2 before plugging the Pi. |
| 5 | **J14** (4-pin safety loop) | The two NC interlock loops that gate `RELAY_ENABLE_RAIL`. Fit before any relay test so you can prove the rail drops on an opened loop (`21_bringup-cutover.md` §21.2.1 step 6). | — |
| 6 | **J6–J11** (6× 2-pin motion screw blocks) | The relay dry-contact outputs (S, T, SP, BE, M, M2). **J12/M1 stays DNP — leave empty.** | — |
| 7 | **J3 / J4 / J5** (FAST / SLOW-A / SLOW-B field headers) | The opto input front-ends. Need `FIELD_WET_V` (step 3) live to wet a contact and see the input flip. | — |
| 8 | **J13** (6-pin LED-lamp header) | Status-LED drive off `VCC_5V`; lowest priority, nothing downstream depends on it. | — |

**Why interleave rather than batch:** the board deliberately has no on-board 3.3 V regulator and no isolated supply until *you* fit them — `VCC_3V3` comes from the Pico (step 2) and `FIELD_WET_V` from U37 (step 3). `06_board-power.md` §6.8 spells out the exact gate: "Fit and verify rails in the order: 5 V in → confirm `VCC_5V` after D17 → fit A1, confirm 3.3 V at Pico pin 36 → fit U37, confirm isolated `FIELD_WET_V`/`FIELD_GND` and confirm `FIELD_GND` is *not* continuous with `GND`." If you fit U37 before confirming `VCC_5V`, you can't tell a dead 5 V rail from a bad U37. If you fit all connectors first and `FIELD_GND` turns out shorted to `GND`, you've buried the fault under 12 connectors. One part, one rail check.

> Power for steps 2–3 comes from your bench supply landed in J2: regulated **5 V** on pin 1 (`VCC_5V_RAW`), GND on pins 2–3. The on-board SS14 (D17) drops ~0.3–0.5 V, so expect ~4.6–4.8 V at TP1, not a clean 5.00 (`06_board-power.md` §6.2.2). Size the supply ≥1.5 A (3 A comfortable) per §6.5.2 — at bench bring-up you're nowhere near that, but use a current-limited supply set to ~500 mA so a solder bridge trips the limit instead of cooking a trace.

### 2. Phoenix THT screw blocks — J2, J6–J11 (MKDS, 5.08 mm)

These are the **fixed screw terminals**: `J2` (3-pos, 5.08 mm, Phoenix 1715734) and `J6–J11` (2-pos, 5.08 mm, Phoenix 1715721). Wires land directly under the screws — there is **no mating plug** for these (`11_connector-pinouts.md` §11.0). They are also the most plane-heavy joints on the board: J2 has two `GND` landings (pins 2 and 3) straight into the ground plane, and every J6–J11 pin is a `Machine_Output` net at 0.50 mm.

1. **Iron temp: 370–400 °C** on a chisel tip. This is hotter than you'd use for signal joints — it's deliberate, to overcome the plane thermal mass without dwelling so long you lift a pad.
2. Flux each pad. Seat the block flush and square to the silk (wire-entry mouths facing the board edge — **VERIFY** wire-entry direction against the footprint render; the BOM flags "Verify wire-entry direction" for both MKDS parts).
3. Tack one corner pin, recheck the block is flush and not tilted, then solder the rest.
4. **Dwell longer on plane pins.** For the GND pins on J2 and any Machine_Output pin, hold the iron on the pin+pad for ~3–4 s to bring the joint up to temp, feed solder *into the joint* (not onto the tip), and watch for a full fillet that wets the pad ring all the way around. A dull, balled, or ring-cracked joint = the plane sucked the heat; reflow with more dwell or a hotter tip. If a pin just won't take, preheat the area (hot-air at low flow, or a preheater plate) for 20–30 s and try again.
5. Confirm no bridge between adjacent pins (5.08 mm pitch is forgiving, but flux residue can look like a bridge — clean and re-inspect).

### 3. Phoenix MCV shrouded pin headers — J3, J4, J5, J13, J14 (3.5 mm)

These are the **pluggable** 3.5 mm vertical PCB headers; their mating `MC …-ST-3,5` plugs are off-board field wiring you do **not** solder (`21_bringup-cutover.md` §21.2.0). Refs and sizes: `J3` 10-pos (1843680), `J4` 14-pos (1843729), `J5` 12-pos (1843703), `J13` 6-pos (1843648), `J14` 4-pos (1843622). J3/J4/J5 carry `Field_Sense` nets (mostly low-mass) plus the `FIELD_GND` return pins (J3 pins 9/10, J4 pin 14, J5 pin 12) which tie to the isolated field-ground pour; J13 pin 1 is `VCC_5V` and pin 2 is `GND` (plane pins); J14 pin 1 is `VCC_5V`.

1. **Iron temp: 350–370 °C**, chisel or large conical. A touch cooler than the MKDS blocks because most of these pins are signal nets — but bump dwell/temp on the plane pins called out above (J13 pin 1/2, J14 pin 1, the FIELD_GND returns).
2. Flux the pad row. The MCV headers have many closely-spaced pins (J4 is 14 across a 3.5 mm pitch) — **seat dead-flush and square** before tacking, because a tilted header throws every pin's plug alignment.
3. Tack the two end pins first, verify flush + square against the silk outline, then solder down the row.
4. **Watch for bridges** — 3.5 mm pitch is tighter than the MKDS, and the higher pin count means more chances. Drag-solder is fine if you're comfortable; otherwise pin-by-pin with the iron on the lead and pad together. Inspect each gap; wick any bridge.
5. **Orientation matters for the plug later** — get the shroud key / pin-1 facing per the footprint so the field harness plugs in the intended way. (The board silk labels each: `J3 FAST`, `J13 LED LAMPS`, `J14 SAFETY LOOP`, etc. — `13_layout-mfg.md` §13.7.)

### 4. Raspberry Pi Pico A1 (SC0915, castellated module)

A1 is the **castellated SC0915** — no headers (do **not** use a Pico H/WH; `hand-solder-bom.csv` Notes). The board footprint is `Module:RaspberryPi_Pico_SMD` (`13_layout-mfg.md` §13.10), so it is laid out as an **SMD/castellated** footprint with both the castellated edge half-holes **and** the bottom SMD pads under each castellation. You have two valid techniques; either gives the same connection.

**Common setup:** ESD-grounded. Flux the whole pad ring. **Iron 340–360 °C**, fine conical tip. Orient the Pico per the silk by `J1 PI / LOGIC / SAFETY` so the USB end and pin 1 land correctly — get this right *before* you tack, because the Pico straddles signal nets you don't want crossed (UART is already crossed on the board; wire the ribbon straight — `11_connector-pinouts.md` §11.2 UART gotcha).

**Edge A — castellation flooding (recommended, easiest to inspect):**
1. Tin **one corner pad** on the board lightly. Set the Pico flush and aligned to the silk, reflow that one corner pad to tack it. Recheck alignment — every castellation should sit centered on its pad.
2. Tack the diagonally opposite corner. Now it's locked; re-verify flush (no rocking) and aligned.
3. Work around the perimeter: touch the iron to the **castellation half-hole and the board pad together**, feed a little solder so it **flows down into the half-hole and fillets onto the pad.** A good joint is a concave fillet filling the castellation, wetted to both the module and the board pad.
4. Don't bridge adjacent castellations (0.1" pitch — forgiving, but watch the corners). Wick any bridge.

**Edge B — bottom SMD pads (use if you prefer, or if a castellation won't wet):** because the footprint carries the SMD pads under the module, you *can* reflow the bottom pads (hot-air or a careful iron-and-drag on the exposed pad toes), but the castellation method is far easier to inspect by eye and is the recommended path for a one-off. If you go SMD-only, verify continuity on a few pins afterward since you can't see the joints.

**Critical pins to confirm after fitting A1** (then power up): the 3V3 rail and GP2 health line.
- **TP3 `VCC_3V3` ≈ 3.3 V** — proves the Pico's regulator and its 3V3-out pad are connected (`06_board-power.md` §6.9).
- The eight Pico GND pins (3, 8, 13, 18, 23, 28, 33, 38) must all be down to `GND` — a missing GND castellation gives flaky boot.
- Don't flash/boot-test yet beyond the rail check; full I²C-enumerate + heartbeat is the §21.2 step-2/3 sequence after J1 is on.

### 5. TRACO TMA-0505S U37 (4-pin part in a SIP-7 land)

U37 is the **isolated 5→5 V 1 W SIP-7** (Locked exact part; **do not substitute without a pinout + isolation review** — `hand-solder-bom.csv`, `11_connector-pinouts.md` §11.11). Footprint `Converter_DCDC:..._TRACO_TMA-05xxS_..._THT`. ESD-grounded.

1. **Orientation** — this part bridges the logic/field isolation barrier. Confirmed against the TRACO TMA datasheet (Rev. 2026-04-15, p.4 "Pinout") and matched to the board: **pin 1 = +Vin (Vcc) → `VCC_5V`, pin 2 = −Vin → `GND`** (logic side), **pin 4 = −Vout → `FIELD_GND`, pin 6 = +Vout → `FIELD_WET_V`** (isolated field side); position 5 has no pin on the single-output S part. The single-output TMA-0505S has **4 pins** populating a SIP-7 land — the spacing is asymmetric (2.54 mm input pair, then 5.08 mm gaps), so it **physically seats only one way**: pin 1 (+Vin) into the square pad. You cannot fit it backwards. If it won't drop in, you're trying the wrong holes (e.g. the bare-copper pour blob beside the connector), not the 4 plated holes.
2. **Iron 350–370 °C**, chisel tip. The +Vin/−Vin pins are logic-side plane pins (`VCC_5V`, `GND`) → use the longer dwell. The +Vout/−Vout pins sit in the isolated FIELD pour — also plane-connected on `FIELD_GND`.
3. Insert flush, tack one pin, verify the body is seated flat and not tilted (a SIP standing proud is fine electrically but check it clears nearby parts), then solder all **four pins (1, 2, 4, 6)** with full fillets. The single-output part has only 4 pins; the SIP-7 land leaves positions 3/5/7 with no hole, so there are exactly 4 holes to fill — don't go hunting for a 5th/6th/7th.
4. **After fitting, with 5 V applied:** **TP4 `FIELD_WET_V` ≈ 5 V**, and the isolation proof — **TP5 `FIELD_GND` reads OPEN / no continuity to TP2 `GND`** on the meter (`06_board-power.md` §6.9; `13_layout-mfg.md` §13.9 audit invariant #5: GND and FIELD_GND share zero nodes). If `FIELD_GND` beeps continuous to `GND`, **stop** — you have a solder bridge across the barrier or U37 is mis-oriented; do not proceed to the input tests.

### 6. Clean + inspect each joint before moving on (do not skip)

After **every** part in the order above — not just at the end:

1. **Visual:** full concave fillet on each pin, no balls, no dull/cracked rings (the plane-pin failure mode), no bridges. Use magnification on the Pico castellations and the tight MCV pin rows.
2. **Clean flux** so residue doesn't masquerade as a bridge or hide a cold joint — IPA + brush, then re-inspect.
3. **Meter the rail that part creates or carries**, per the order table above, before fitting the next part:
   - After **J2**: continuity only.
   - After **A1**: power up → **TP1 ≈ 4.6–4.8 V**, **TP3 ≈ 3.3 V**.
   - After **U37**: **TP4 ≈ 5 V**, **TP5↔TP2 OPEN**.
   - After **J1**: continuity J1.1→TP1, J1.11→TP3, J1.2/12→TP2 (this is also where the §21.2 I²C-enumerate at 0x20/0x21/0x22 and RP2040 boot/heartbeat happen once the Pi is plugged).
   - **J14 / J6–J11 / J3–J5 / J13**: continuity + no-bridge; the functional relay-drop, interlock-drop, and opto-input tests are the §21.2.1 steps 4–8 sequence that follows this solder pass.
4. **No part hot.** During each powered check, touch each active — nothing should be warm beyond mild. A hot U37 or hot Pico = a short or reversed pin; kill power (`21_bringup-cutover.md` §21.2.1 step 1: "No part hot").

> **Leave J12/M1 empty.** It is DNP by design — the M1 ball-return channel (K7/Q7/J12) is unconfirmed on this chassis (`11_connector-pinouts.md` §11.7, `13_layout-mfg.md` §13.6.1). Do not populate the J12 terminal block.

---

**Reference files** (all absolute):
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\fab_revB_routed_manual\assembly\wsl-phase8b-revB-hand-solder-bom.csv` — the part list and the A1 "no headers" / U37 "no substitute" locks
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\06_board-power.md` §6.7/§6.8/§6.9 — rail-fit order and expected rail values
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\21_bringup-cutover.md` §21.2 — the bench bring-up sequence, TP map, "no part hot"
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\11_connector-pinouts.md` §11 — connector pinouts, U37 orientation, J12 DNP
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\13_layout-mfg.md` §13.0/§13.2/§13.7/§13.10 — board size/layers, plane net widths (thermal mass), Pico footprint, TP map

**Flags:**
- **(VERIFY: J2 / J6–J11 wire-entry direction)** — the hand-solder BOM explicitly says "Verify wire-entry direction" for both MKDS parts; confirm against the footprint render before tacking so the screw mouths face the intended edge.
- **(VERIFY: J1 ribbon pin-1 / keying)** — `11_connector-pinouts.md` §11.2 flags the J1 mating socket as a "candidate" and the ribbon pin-1/keying as "confirm before crimping." The header solders fine either way, but get pin-1 orientation right relative to the Pi.
- **(VERIFY: exact iron temperatures)** — the temps above (370–400 °C MKDS, 350–370 °C MCV/U37, 340–360 °C Pico) are standard hand-solder values scaled for this board's heavy 4-layer plane copper; they are not specified in the source docs. Adjust to your iron/solder alloy; the load-bearing instruction from the docs is "this is a large 4-layer board with heavy GND/power copper — plan for extra dwell/heat on plane pins."

---

## Part-to-Silkscreen Map & Orientation

This section is the single bench reference for *which part goes where and which way round* on the rev-B board. Use it before you pick up the iron. Everything here is grounded in `wsl-phase8b-revB-hand-solder-bom.csv`, `06_board-power.md`, `11_connector-pinouts.md`, and `05_board-overview.md` §5.8; the footprint identifiers come straight from `scripts/generate_kicad_netlist_revB.py`.

> **The one rule that overrides everything:** the silkscreen *function label* is authoritative, not the `Jn` number and never a machine-cavity number (`05_board-overview.md` §5.8). For the motion outputs in particular, the `Jn` numbers were assigned by the tool's annotation order and do **not** run S-T-SP-BE-M-M2 in `Jn` sequence (see the J6-J11 note below). When in doubt, read the function name screened next to the part.

---

### 1. Master hand-solder part → silk → footprint → orientation table

These 14 reference designators are the entire hand-solder job. Recommended order (power-critical first, per `06_board-power.md` §6.8 / `21_bringup-cutover.md` §21.2.0): **J2 → A1 → U37 → J1 → J14 → J6-J11 → J3/J4/J5 → J13.**

| Ref | MFR P/N | What it is | Exact silk label | Footprint (KiCad) | Orientation / keying / polarity rule |
|---|---|---|---|---|---|
| **A1** | Raspberry Pi **SC0915** | RP2040 Pico module, castellated (no headers) | screened **J1 PI / LOGIC / SAFETY** zone (ref **A1**, no function-label of its own) | `Module:RaspberryPi_Pico_SMD` | **Polarized by pinout.** Pin-1 (GP0) corner must match the silk pad-1 marker; the **USB / Micro-USB connector end overhangs the board edge** — see §3. Castellated land-grid: solder flat to the pads, USB end off the edge. Do **not** use a Pico H/WH with pre-soldered headers (`hand-solder-bom.csv`, §5.8). |
| **U37** | TRACO **TMA-0505S** | Isolated 5→5 V 1 W SIP-7 DC/DC (the isolation barrier) | screened **J2 5V IN** zone (ref **U37**, "ISO supply") | `Converter_DCDC:Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT` | **POLARIZED — NEVER FLIP.** SIP-7, pin-1 = +Vin. Pin-1 dot/notch on the package must match the pin-1 silk. +Vin/−Vin on the logic side, +Vout/−Vout on the field side — see §2. Flipping it bridges logic GND to FIELD_GND through the wrong pins and defeats the only galvanic isolation barrier on the input side (`06_board-power.md` §6.4.2). |
| **J1** | CNC Tech **3020-20-0100-00** | 2×10 (20-pin) 2.54 mm box/IDC header | **J1 PI** | `Connector_IDC:IDC-Header_2x10_P2.54mm_Vertical` | **Keyed shroud.** The shroud's polarizing **notch/slot faces the silk pin-1 end**; pin 1 (square pad, `VCC_5V`) sits at the same end. Vertical box header — body sits flat, shroud opening faces up. See §4. Confirm pin-1/keying against the Pi ribbon before crimping (this is a flagged VERIFY — see below). |
| **J2** | Phoenix **1715734** | MKDS 1,5/3-5,08 screw terminal, 3-pos, 5.08 mm | **J2 5V IN** | `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal` | **Wire-entry faces the board edge** (horizontal entry). Fixed block, no plug. Pin 1 = `VCC_5V_RAW`, pins 2-3 = `GND`. See §5. |
| **J3** | Phoenix **1843680** | MCV 1,5/10-G-3,5 pin header, 10-pos, 3.5 mm | **J3 FAST** | `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical` | Vertical pin header; **shroud opening (plug-entry) faces outward toward the board edge.** Pin 1 at the silk-marked end. See §5. |
| **J4** | Phoenix **1843729** | MCV 1,5/14-G-3,5 pin header, 14-pos, 3.5 mm | **J4 SLOW A** | `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_14-G-3.5_1x14_P3.50mm_Vertical` | Same rule as J3: vertical, shroud opening faces the board edge, pin 1 at silk-marked end. |
| **J5** | Phoenix **1843703** | MCV 1,5/12-G-3,5 pin header, 12-pos, 3.5 mm | **J5 SLOW B** | `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_12-G-3.5_1x12_P3.50mm_Vertical` | Same rule as J3. |
| **J6** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos, 5.08 mm | **J6 S** (`J_MOTION_S`) | `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal` | Wire-entry faces board edge. Pin 1 = NO, pin 2 = COM (`11_connector-pinouts.md` §11.7). |
| **J7** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos | **J7 T** (`J_MOTION_T`) | (same as J6) | Same wire-entry/pin rule as J6. |
| **J8** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos | **J8 SP** (`J_MOTION_SP`) | (same as J6) | Same as J6. |
| **J9** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos | **J9 BE** (`J_MOTION_BE`) | (same as J6) | Same as J6. |
| **J10** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos | **J10 M** (`J_MOTION_M`) | (same as J6) | Same as J6. |
| **J11** | Phoenix **1715721** | MKDS 1,5/2-5,08 screw terminal, 2-pos | **J11 M2** (`J_MOTION_M2`) | (same as J6) | Same as J6. |
| **J13** | Phoenix **1843648** | MCV 1,5/6-G-3,5 pin header, 6-pos, 3.5 mm | **J13 LED LAMPS** | `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical` | Vertical; shroud opening faces board edge; pin 1 (`VCC_5V`) at silk-marked end. |
| **J14** | Phoenix **1843622** | MCV 1,5/4-G-3,5 pin header, 4-pos, 3.5 mm | **J14 SAFETY LOOP** | `Connector_Phoenix_MC:PhoenixContact_MCV_1,5_4-G-3.5_1x04_P3.50mm_Vertical` | Vertical; shroud opening faces board edge; pin 1 (`VCC_5V` loop source) at silk-marked end. |

> **DNP — leave empty:** **J12 / M1** (the 7th motion channel, `J_MOTION_M1`, relay K7) is **Do Not Populate** (`11_connector-pinouts.md` §11.0/§11.7, `05_board-overview.md` §5.8). The footprint is on the board screened **J12 M1**; leave it bare. Do not stuff a 7th MKDS block into it. Its whole channel (K7/Q7/R85-87/D13-14/snubber) is DNP copper only.

> **NOT soldered (off-board parts):** the Phoenix **MC …-ST-3,5 mating plugs** for J3/J4/J5/J13/J14 (PNs 1840447 / 1840489 / 1840463 / 1840405 / 1840382) and the **J1 ribbon socket** (CNC Tech 3030-20-0102-00 candidate) are the *cable-side* halves — they crimp onto the harness, **not** onto the board (`11_connector-pinouts.md` §11.0 footprint-vs-mating-plug note, §11.11). J2 and J6-J11 are *fixed* screw blocks: bare wire lands directly under the screw, there is no plug for them.

---

### 2. U37 TMA-0505S — the isolation barrier, do not flip (detail)

This is the most consequential orientation on the board. The TMA-0505S is a SIP-7 brick whose internal transformer is the **only** galvanic separation between the logic ground (`GND`) and the isolated field ground (`FIELD_GND`). Reverse it and you tie the wrong pins across that barrier.

Pin assignment from `generate_kicad_netlist_revB.py` `block_supplies()` and `06_board-power.md` §6.4.2:

| TMA-0505S pin | Net | Side |
|---|---|---|
| **pin 1 — +Vin (Vcc)** | `VCC_5V` | Logic (primary) |
| **pin 2 — −Vin (GND)** | `GND` | Logic (primary) |
| **pin 4 — −Vout** | `FIELD_GND` | Field (secondary, isolated) |
| **pin 6 — +Vout** | `FIELD_WET_V` | Field (secondary, isolated) |

(Pin numbers per the TRACO datasheet, Rev. 2026-04-15, p.4. Position 5 = *No pin* on the single-output S model; 3/7 unused — **4 pins total** in the SIP-7 land. Pads 1,2,4,6 on the board match exactly.)

Rules at the bench:
1. Find the **pin-1 marker** on the TMA package (printed dot / chamfered corner / the "1" on the case) and align it to the **pin-1 pad** on the silk (square pad, by the **J2 5V IN** zone).
2. The +Vin/−Vin pair sit on the **logic side** of the keepout gutter; +Vout/−Vout reach into the **FIELD room** (`05_board-overview.md` §5.5). If the part orients so the output pins point toward the logic cluster, it is in **backwards** — stop.
3. After fitting (and only after A1 is in and 5 V is applied), verify at TP4↔TP5: **+5 V isolated**, and TP5 (`FIELD_GND`) to TP2 (`GND`) reads **open / no continuity** (`21_bringup-cutover.md` §21.2.2, `06_board-power.md` §6.9). Continuity there means the barrier is broken — most likely U37 is reversed.

> **CONFIRMED against the TRACO TMA datasheet (Rev. 2026-04-15, p.4 "Pinout"):** single-output pinout is **pin 1 = +Vin (Vcc), pin 2 = −Vin (GND), pin 4 = −Vout, pin 6 = +Vout** (position 5 = No pin). This matches the board (`block_supplies()` → pads 1/2/4/6) exactly, so there is **no reverse-feed risk**. The SIP pin spacing is asymmetric, so the part can only seat one way (pin 1 → square pad); flipping it is physically impossible. Still eyeball the part's pin-1 mark to the square silk pad as a final visual check.

---

### 3. A1 Pico — USB end overhangs the board edge

A1 is the SC0915 castellated module (no headers — solder the castellated/SMD lands flat to the board). Orientation facts:

1. **Pin-1 corner (GP0) matches the silk pad-1 marker** in the **J1 PI / LOGIC / SAFETY** zone. The Pico land pattern is `Module:RaspberryPi_Pico_SMD`; its electrical pins are confirmed by `block_rp2040()` — pin 1 = GP0/`PI_UART_RX`, pin 39 = VSYS/`VCC_5V`, pin 36 = 3V3 OUT/`VCC_3V3`, GNDs on 3/8/13/18/23/28/33/38.
2. **The USB / Micro-USB connector end overhangs the board edge.** The footprint places the module so the USB jack hangs past the PCB outline, leaving the BOOTSEL button and USB port physically accessible for flashing after the module is soldered down. Orient the module so the USB jack points **off the nearest board edge in the J1-PI zone**, not inward over the MCP/logic cluster.
   - This matters for bring-up: flashing is done by **holding BOOTSEL while plugging USB** to mount `RPI-RP2` and drag-dropping the pre-built `firmware/rp2040/build/wsl_phase8b_rp2040.uf2` (`firmware/rp2040/README.md`, Flash section). If the USB end is buried over the board you lose that access and must fall back to the SWD test pads.
3. **No 3.3 V exists on the board until A1 is fitted and powered** — A1's onboard regulator is the source of `VCC_3V3` (`06_board-power.md` §6.3). That is why A1 comes right after J2/5V-in and before the inputs in the solder order.

> **(VERIFY: confirm the USB-end-vs-which-edge from the fab silk/render before soldering.** The footprint is `Module:RaspberryPi_Pico_SMD` (USB-overhang style is standard for that footprint), but the manuals don't name the specific board edge the USB faces — read it off the assembly drawing / pin-1 silk on the actual board.)

---

### 4. J1 box header — keyway / shroud notch / pin-1

J1 is the only shrouded/keyed connector on the board. Footprint `Connector_IDC:IDC-Header_2x10_P2.54mm_Vertical`; the schematic uses `Conn_02x10_Odd_Even`, so **odd pins (1,3,…,19) run down one row, even pins (2,4,…,20) down the other**, with pins 1 and 2 side-by-side at the pin-1 end (`11_connector-pinouts.md` §11.2).

1. The **shroud's polarizing notch/slot** must align so it faces the **silk pin-1 datum** (the silk marks pin 1 with a square pad / "1" / triangle at the **J1 PI** label end).
2. Solder it so the **shroud opening faces up** (vertical box header) for the ribbon socket to drop on.
3. Pin 1 = `VCC_5V`, pin 2 = `GND`, pin 13 = `RP2040_OK`; pins 14-20 are no-connect/reserved. The UART crossover is already done in copper — wire the ribbon **straight through**, do not cross TX/RX (`11_connector-pinouts.md` §11.2 UART gotcha).

> **(VERIFY: ribbon pin-1 / shroud keying convention.** `11_connector-pinouts.md` §11.2 flags the physical ribbon orientation as "confirm cable keying/orientation"; the J1 part is a CNC Tech *candidate* in the BOM. Confirm board-vs-Pi pin-1 alignment and that the chosen box header's key matches the ribbon socket before crimping.)

---

### 5. MKDS / MCV wire-entry & pin-shroud direction (the rule that prevents a reversed connector)

All the Phoenix parts share one orientation rule, stated two ways depending on type:

- **MKDS screw terminals (J2, J6-J11) — horizontal wire entry:** the **wire-entry mouth (where the bare conductor goes in under the screw) faces outward toward the board edge.** These are fixed blocks; there is no key, but a block soldered 180° backwards points its wire mouths inward over the board and is unusable. Footprints are the `…_Horizontal` MKDS variants.
- **MCV pin headers (J3, J4, J5, J13, J14) — vertical:** the **shroud / plug-entry opening faces outward toward the board edge** so the mating `…-ST-3,5` plug seats from outside the board. Pin 1 sits at the silk-marked end of each.

Pin-1 anchors to check after fitting (from `11_connector-pinouts.md`):

| Connector | Pin 1 net | Quick check |
|---|---|---|
| **J2 5V IN** | `VCC_5V_RAW` (pins 2-3 = GND) | continuity pin 1 → D17 anode / TP1 path |
| **J3 FAST** | `FIELD_FAST_SA` (pins 9-10 = `FIELD_GND`) | pin 9/10 → TP5 |
| **J4 SLOW A** | `FIELD_SLOW_GS1` (pin 14 = `FIELD_GND`) | pin 14 → TP5 |
| **J5 SLOW B** | `FIELD_SLOW_PBZ` (pin 12 = `FIELD_GND`) | pin 12 → TP5 |
| **J13 LED LAMPS** | `VCC_5V` (pin 2 = GND; pins 3-6 = LED returns) | pin 1 → TP1 |
| **J14 SAFETY LOOP** | `VCC_5V` loop source (pin 4 = `SAFE_STOP_RETURN`) | pin 4 → TP15 |

J6-J11 motion blocks — **pin 1 = NO, pin 2 = COM** on every one (`11_connector-pinouts.md` §11.7) — and the silk **function** label is what tells them apart, because the `Jn` numbers are *not* in S-T-SP-BE-M-M2 order:

> **J6-J11 silk-vs-Jn trap (read this before wiring outputs).** The board screens each motion block with both its `Jn` number and its function name. The *function* assignment that matters is **J6=S, J7=T, J8=SP, J9=BE, J10=M, J11=M2, J12=M1(DNP)** — that is the as-fabricated/silk function map used by the cutover harness (`21_bringup-cutover.md` §21.3.3 output table, `11_connector-pinouts.md` §11.7). Note `05_board-overview.md` §5.8 lists the *annotation* order (BE/M/M2/S/SP/T) and explicitly warns: **follow the silkscreen function label, not the `Jn` number,** to avoid swapping sweep (S) and table (T). At the bench, trust the screened `J_MOTION_*` name.

---

### 6. C11 — the one polarized SMT part: confirm + polarity before power

C11 is **already placed by JLC**, but it is the single polarized SMT part on the board, so it gets a pre-power eyeball. It is `C_WDOG_TIMING`, the **100 µF / 16 V** electrolytic in the NE555 watchdog RC timing network (`generate_kicad_netlist_revB.py` `block_watchdog()`; called out as C11 in `21_bringup-cutover.md` §21.2.1 step 4).

- Footprint: `Capacitor_SMD:CP_Elec_6.3x5.4` — an **SMD aluminum electrolytic** (a small can, not a leaded radial). Symbol `C_Polarized`.
- **Before applying any power, confirm the + (positive) terminal matches the silk + mark** (the marked/banded end of the can = the polarity stripe convention for SMD electrolytics; the silk shows the + pad). Net side: C11 pin 1 = `WDOG_TIMING_NODE`, pin 2 = `GND` (`block_watchdog()`: `GND += … ctim[2] …`), so the **positive end is the timing-node side and the negative/banded end goes to GND**.
- If the can is reversed relative to the silk +, do not power up — a reversed electrolytic on a continuous DC rail can vent/fail. Because it sets the ~10 s watchdog timeout, a wrong/dead C11 also shows up later as a failed step-4 watchdog-drop test, but **catch it visually first** (`21_bringup-cutover.md` §21.2.1 step 4 / §21.2.2 TP9 `WDOG_TIMING_NODE`).

---

### 7. Quick "did I orient it right?" pre-power checklist

Run these *before* the §21.2 power-on sequence:

1. **U37** pin-1 dot aligned to silk pin-1; +Vout/−Vout point into the FIELD room (not the logic cluster). (No power yet.)
2. **A1** pin-1 corner on silk pad-1; **USB jack overhanging the board edge** and reachable for BOOTSEL.
3. **J1** shroud notch toward the silk pin-1 (J1 PI) end.
4. **C11** + terminal matches silk + (the one placed-by-JLC polarity check).
5. **J2 / J6-J11** screw mouths face the board edge; **J3/J4/J5/J13/J14** shroud openings face the board edge; every pin 1 at its silk-marked end.
6. **J12 / M1** left **empty** (DNP).
7. Mating plugs (MC-ST) and the J1 ribbon socket are **on the harness, not on the board.**

Then proceed to `21_bringup-cutover.md` §21.2.1 step 1 (apply 5 V at J2, read TP1≈5 V → TP3≈3.3 V → TP4≈5 V isolated, TP5↔TP2 open).

---

**Files referenced (all absolute):**
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\fab_revB_routed_manual\assembly\wsl-phase8b-revB-hand-solder-bom.csv`
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\05_board-overview.md` (§5.5 banding, §5.8 ref→function map + motion-terminal-ordering warning)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\06_board-power.md` (§6.3 A1=3V3 source, §6.4 U37 pinout/isolation, §6.8 solder order, §6.9 rail TPs)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\11_connector-pinouts.md` (§11.0 footprint table + DNP J12 + mating-plug note, §11.2 J1, §11.7 J6-J12 pin1=NO/pin2=COM, §11.11 parts summary)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\21_bringup-cutover.md` (§21.2.0 assembly state, §21.2.1 step 4 = C11, §21.2.2 TP map, §21.3.3 J6-J11 output function map)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\firmware\rp2040\README.md` (Pico BOOTSEL/USB flash; `.uf2` path)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\scripts\generate_kicad_netlist_revB.py` (authoritative footprints: `FP_PICO`, `FP_TMA`, `FP_IDC_2X10`, `FP_CP`; `block_supplies()` U37 pins; `block_watchdog()` C11=`C_WDOG_TIMING` 100µF/16V polarized)

**Flagged for confirmation:** (a) TMA-0505S exact pin-1 datum (TRACO datasheet, not in fab CSVs); (b) which board edge A1's USB faces (read from assembly drawing/silk); (c) J1 ribbon pin-1 / shroud keying ("candidate" part, flagged in §11.2). All three are pin-1/orientation confirmations against the physical part and silk — none change the wiring described above.

---

## Connector Pinouts (J1-J14)

This is the pin-by-pin reference for every **hand-soldered** connector on the Rev-B board. Use it as you orient each part before soldering, and again when you wire the harness. Every pin/net below is cross-checked against the authoritative generator `scripts/generate_kicad_netlist_revB.py` (`block_connectors()`, `block_rail()`, `block_rp2040()`) and the manual's `11_connector-pinouts.md`. Where the two agree, no flag; where a source leaves something open, it is marked **(VERIFY: …)**.

> **One rule to internalize before you wire anything:** the board has **two galvanically isolated grounds**. `GND` (logic) and `FIELD_GND` (machine-side) share **zero** nodes — that isolation runs through U37 (TMA-0505S) and the 32 optos. J1/J2/J13 are logic-domain. J3/J4/J5 are field-domain. J14 is the safety rail. Do not bridge `GND` to `FIELD_GND` on the bench.

---

### Quick orientation map (silk ↔ ref ↔ what it is)

| Silk | Ref (net) | Pos | Domain | Solder it as |
|---|---|---|---|---|
| **J1 PI** | J1 (`J_PI`) | 2x10 IDC | LOGIC | The Pi ribbon link |
| **J2 5V IN** | J2 (`J_PWR 5V`) | 3 screw | LOGIC power-in | Bench 5 V lands here first |
| **J3 FAST** | J3 (`J_FAST_IN`) | 10 (3.5 mm) | FIELD sense | Cams + DIELL → RP2040 |
| **J4 SLOW A** | J4 (`J_SLOW_IN_A`) | 14 (3.5 mm) | FIELD sense | Grippers → MCP IN-A |
| **J5 SLOW B** | J5 (`J_SLOW_IN_B`) | 12 (3.5 mm) | FIELD sense | Manual/foul/aux → MCP IN-B |
| **J6 S / J7 T / J8 SP / J9 BE / J10 M / J11 M2** | J6–J11 | 2 screw each | MACHINE OUT (dry contact) | Relay COM/NO pairs |
| *(J12 M1)* | J12 | 2 screw | — | **DNP — leave empty** |
| **J13 LED LAMPS** | J13 (`J_LAMP_LED`) | 6 (3.5 mm) | LOGIC (LED drive) | 4 mask LEDs |
| **J14 SAFETY LOOP** | J14 (`J_SAFETY`) | 4 (3.5 mm) | SAFETY | Two NC interlock loops |

**Pin-1 convention for the 3.5 mm Phoenix MCV headers (J3/J4/J5/J13/J14):** pin 1 is the end **marked "1" on the silk**; positions count up sequentially from there toward the body. Confirm the silk "1" before crimping the mating plug — these are keyed but reversible if you ignore the marker.

---

### J1 — `J_PI` (Pi logic interface, 2x10 IDC, 2.54 mm)

The only link to the Raspberry Pi. **KiCad odd/even numbering** (footprint `Conn_02x10_Odd_Even`): odd pins 1,3,…,19 run down one row; even pins 2,4,…,20 down the other; **pins 1 and 2 are side-by-side at the keyed pin-1 end**. The generator wires **pins 1–13**; **pins 14–20 are no-connect (reserved)**.

| Pin | Signal | Net | Dir | Notes |
|---|---|---|---|---|
| 1 | +5 V logic | `VCC_5V` | PWR | Same net as J2's post-diode 5 V. |
| 2 | Logic GND | `GND` | — | |
| 3 | I2C SDA | `I2C_SDA` | BIDIR | 4.7 kΩ pull-up to 3V3 on board. |
| 4 | I2C SCL | `I2C_SCL` | BIDIR | 4.7 kΩ pull-up to 3V3 on board. |
| 5 | Pi UART TX → Pico RX | `PI_UART_TX` | IN | Pi transmit → RP2040 GP1 (Pico pin 2). 115200 8N1. |
| 6 | Pi UART RX ← Pico TX | `PI_UART_RX` | OUT | RP2040 GP0 (Pico pin 1) → Pi receive. |
| 7 | Watchdog kick | `WDOG_KICK` | IN | Pi pulse re-triggers NE555 (U36). Missing kick → rail drops. |
| 8 | Arm permit | `ARM_PERMIT` | IN | One series condition of the relay-enable rail. HIGH = permit. |
| 9 | MCP INT-A | `MCP_INT_A` | OUT | From MCP IN-A (U1) INTA pin 20. Optional. |
| 10 | MCP INT-B | `MCP_INT_B` | OUT | From MCP IN-B (U2) INTA pin 20. Optional. |
| 11 | +3.3 V logic | `VCC_3V3` | PWR | Sourced by the Pico's onboard regulator (Pico pin 36). Powers MCPs + opto logic side. |
| 12 | Logic GND | `GND` | — | Second GND for ribbon return integrity. |
| 13 | RP2040 OK | `RP2040_OK` | OUT | RP2040 GP2. HIGH = permit motion; LOW = drop rail. Hard safety condition. |
| 14–20 | *(no connect)* | — | — | Reserved. |

> **UART crossover is already on the PCB — wire the ribbon straight-through.** Net names are from the **Pi's** perspective: `PI_UART_TX` (pin 5) lands on the Pico's **RX (GP1)**; `PI_UART_RX` (pin 6) lands on the Pico's **TX (GP0)**. Do not re-cross in the cable.

> **(VERIFY: ribbon pin-1 / shroud keying.)** The pad numbers above are fixed by the placed footprint, but the physical ribbon orientation (which conductor is pin 1, shroud key) is flagged "confirm cable keying/orientation" and the J1 ribbon socket is a *candidate* part. Confirm pin-1 alignment board↔Pi before crimping.

> **Pi-side note:** the J1→Pi mapping is a **custom harness** (the Pi GPIOs are scattered, not a clean 1:1 to the ribbon order). See `docs/phase8_pi_provisioning.md` before building the Pi end — do not assume the ribbon pinout matches a Pi 40-pin header order.

---

### J2 — `J_PWR 5V` (regulated 5 V input, 3-pos screw, 5.08 mm)

Bench 5 V lands here. Powers everything: Pico, MCPs, NE555, opto logic sides, U37, relay coils, LEDs.

| Pin | Signal | Net | Dir | Notes |
|---|---|---|---|---|
| 1 | +5 V raw in | `VCC_5V_RAW` | PWR | Feeds the board through reverse-polarity Schottky **D17 (SS14)**. |
| 2 | Ground | `GND` | — | |
| 3 | Ground | `GND` | — | Second return for coil/LED current. |

> `VCC_5V_RAW` (pin 1) → D17 (anode=RAW, cathode=`VCC_5V`) → the protected `VCC_5V` rail. Expect ~**0.3–0.4 V drop** across D17, so on-board 5 V reads slightly low (e.g. feed 5.0 V, measure ≈4.6–4.7 V at TP1). `VCC_5V` here is the **same net** as J1 pin 1 — never feed 5 V into both J1 and J2 from two supplies.

> **(VERIFY: 5 V supply current budget.)** Worst-case = 6 G5LE coils (≈6 × ~40 mA) + logic + LEDs + margin; exact sizing is an open assembly item in the spec. For logic-only bench bring-up (no relays commanded) a ~1 A bench supply is ample.

---

### J3 — `J_FAST_IN` (RP2040 fast inputs, 10-pos, 3.5 mm)

Eight fast machine signals the **RP2040** services directly (cams + both DIELL ball-detect beams), then **2 field-ground pins**. Pin order = `FAST_INPUTS` in the generator. Pico GPIO column = `block_rp2040()`/`config.h` (GP6–GP13).

| Pin | Signal | Field net | Logic net | Pico GPIO (Pico pin) | Function |
|---|---|---|---|---|---|
| 1 | SA | `FIELD_FAST_SA` | `FAST_SA` | GP6 (Pico 9) | Sweep cam. |
| 2 | SB | `FIELD_FAST_SB` | `FAST_SB` | GP7 (Pico 10) | Sweep guard cam. |
| 3 | SC | `FIELD_FAST_SC` | `FAST_SC` | GP8 (Pico 11) | Sweep-under-table interlock window (also SC interlock echo). |
| 4 | TA1 | `FIELD_FAST_TA1` | `FAST_TA1` | GP9 (Pico 12) | Table cam (zero stop / delay reset). |
| 5 | TA2 | `FIELD_FAST_TA2` | `FAST_TA2` | GP10 (Pico 14) | Table cam (run-through / pin-latch / decision). |
| 6 | TB | `FIELD_FAST_TB` | `FAST_TB` | GP11 (Pico 15) | Table-sweep interference interlock cam. |
| 7 | DIELL-L | `FIELD_FAST_DIELL_L` | `FAST_DIELL_L` | GP12 (Pico 16) | Ball detect, left beam (cushion SS cycle trigger). |
| 8 | DIELL-R | `FIELD_FAST_DIELL_R` | `FAST_DIELL_R` | GP13 (Pico 17) | Ball detect, right beam. |
| 9 | Field ground | `FIELD_GND` | — | — | Isolated wetting return (shared with pin 10). |
| 10 | Field ground | `FIELD_GND` | — | — | Isolated wetting return. |

> **Active-low front end:** each pin = `FIELD_WET_V` → 2.2 kΩ → opto LED → this pin; the machine cam contact closes this pin to `FIELD_GND` (pins 9/10), lighting the opto and pulling the Pico GPIO LOW. Idle = HIGH via 10 kΩ to 3V3. **Closed contact = opto ON = logic 0 on the pin**, which firmware inverts to "asserted = 1."

> **GPIO source-of-truth:** the GP6–GP13 column is from `config.h`. The older `docs/phase8_channel_allocation.md` GP0–GP7 column is **STALE — ignore it.**

> **(VERIFY: per-channel dry-contact vs 24 VAC sense population.)** Tables show the default dry-contact wetting front-end; the per-channel dry-vs-24VAC choice is locked at-machine, not yet pinned. Same open item on J4/J5.

---

### J4 — `J_SLOW_IN_A` (MCP IN-A slow inputs, 14-pos, 3.5 mm)

Ten gripper switches + gripper-protect/off-spot/bin, read by **MCP23017 IN-A (U1, I2C 0x20)**, then **1 field-ground pin**. Pin order = `slowa_order`. MCP pin→port/bit: pins 21–28 = GPA0–7; pins 1–8 = GPB0–7.

| Pin | Signal | Field net | Logic net | MCP IN-A pin (port,bit) | Function |
|---|---|---|---|---|---|
| 1 | GS1 | `FIELD_SLOW_GS1` | `SLOW_GS1` | 21 (GPA0 / 0,0) | Gripper switch 1 (standing-pin sense, bit 0). |
| 2 | GS2 | `FIELD_SLOW_GS2` | `SLOW_GS2` | 22 (GPA1 / 0,1) | Gripper switch 2. |
| 3 | GS3 | `FIELD_SLOW_GS3` | `SLOW_GS3` | 23 (GPA2 / 0,2) | Gripper switch 3. |
| 4 | GS4 | `FIELD_SLOW_GS4` | `SLOW_GS4` | 24 (GPA3 / 0,3) | Gripper switch 4. |
| 5 | GS5 | `FIELD_SLOW_GS5` | `SLOW_GS5` | 25 (GPA4 / 0,4) | Gripper switch 5. |
| 6 | GS6 | `FIELD_SLOW_GS6` | `SLOW_GS6` | 26 (GPA5 / 0,5) | Gripper switch 6. |
| 7 | GS7 | `FIELD_SLOW_GS7` | `SLOW_GS7` | 27 (GPA6 / 0,6) | Gripper switch 7. |
| 8 | GS8 | `FIELD_SLOW_GS8` | `SLOW_GS8` | 28 (GPA7 / 0,7) | Gripper switch 8. |
| 9 | GS9 | `FIELD_SLOW_GS9` | `SLOW_GS9` | 1 (GPB0 / 1,0) | Gripper switch 9. |
| 10 | GS10 | `FIELD_SLOW_GS10` | `SLOW_GS10` | 2 (GPB1 / 1,1) | Gripper switch 10. |
| 11 | GP | `FIELD_SLOW_GP` | `SLOW_GP` | 3 (GPB2 / 1,2) | Gripper protect. |
| 12 | OS | `FIELD_SLOW_OS` | `SLOW_OS` | 4 (GPB3 / 1,3) | Off-spot. |
| 13 | BS | `FIELD_SLOW_BS` | `SLOW_BS` | 5 (GPB4 / 1,4) | Bin / #9 (back-stop / bin-full). |
| 14 | Field ground | `FIELD_GND` | — | — | Isolated wetting return for J4. |

> Same opto front-end as J3 (PC817 U12…U24), but logic side lands on **MCP IN-A**. The ten GS bits form the **standing-pin mask** (`controller_io.py read_grippers()`: `GS1=bit0 … GS10=bit9`; a *closed* opto / pin-reads-0 = a *standing* pin). None of J4 is on the safety rail — sense-only.

---

### J5 — `J_SLOW_IN_B` (MCP IN-B slow inputs, 12-pos, 3.5 mm)

Manual-op / 10th-frame / foul / pushbutton / 3 spare inputs, read by **MCP23017 IN-B (U2, I2C 0x21)**, then **1 field-ground pin**. Pin order = `slowb_order`. (IN-B is wired on the board but not yet read by the current FSM.)

| Pin | Signal | Field net | Logic net | MCP IN-B pin (port,bit) | Function |
|---|---|---|---|---|---|
| 1 | PBZ | `FIELD_SLOW_PBZ` | `SLOW_PBZ` | 21 (GPA0 / 0,0) | First-ball / zero / manual-intervention pushbutton. |
| 2 | PBC | `FIELD_SLOW_PBC` | `SLOW_PBC` | 22 (GPA1 / 0,1) | Cycle pushbutton. |
| 3 | FOUL | `FIELD_SLOW_FOUL` | `SLOW_FOUL` | 23 (GPA2 / 0,2) | Foul-line detector. |
| 4 | TENTH | `FIELD_SLOW_TENTH` | `SLOW_TENTH` | 24 (GPA3 / 0,3) | 10th-frame signal. |
| 5 | MAN_T | `FIELD_SLOW_MAN_T` | `SLOW_MAN_T` | 25 (GPA4 / 0,4) | Manual table. |
| 6 | MAN_S | `FIELD_SLOW_MAN_S` | `SLOW_MAN_S` | 26 (GPA5 / 0,5) | Manual sweep. |
| 7 | MAN_SWS | `FIELD_SLOW_MAN_SWS` | `SLOW_MAN_SWS` | 27 (GPA6 / 0,6) | Manual sweep-switch. |
| 8 | MAN_SWSR | `FIELD_SLOW_MAN_SWSR` | `SLOW_MAN_SWSR` | 28 (GPA7 / 0,7) | Manual sweep-reverse. |
| 9 | AUX1 | `FIELD_SLOW_AUX1` | `SLOW_AUX1` | 1 (GPB0 / 1,0) | Spare input. |
| 10 | AUX2 | `FIELD_SLOW_AUX2` | `SLOW_AUX2` | 2 (GPB1 / 1,1) | Spare input. |
| 11 | AUX3 | `FIELD_SLOW_AUX3` | `SLOW_AUX3` | 3 (GPB2 / 1,2) | Spare input. |
| 12 | Field ground | `FIELD_GND` | — | — | Isolated wetting return for J5. |

> Same opto front-end (PC817 U25…U35) → **MCP IN-B**. AUX1–3 are deliberately spare so a switch discovered at cutover doesn't force a respin.

---

### J6–J11 — `J_MOTION_*` (isolated relay dry contacts, 2-pos screw each, 5.08 mm)

Each motion output is its own 2-pin screw block carrying **one G5LE-14 relay's COM + NO** dry contact. **The board never sources voltage across these** — it just opens/closes a contact in the machine's existing control circuit, and only while the safety rail is up.

**Pin convention — identical on every J_MOTION_* (this is the one that bites people):**

| Pin | Signal | Relay pad | Notes |
|---|---|---|---|
| **1** | Relay **NO** (normally-open) | K-pad 3 (NO) | `OUT_x_B`. Open when de-energized; closes to COM when commanded + rail up. |
| **2** | Relay **COM** (common) | K-pad 1 (COM) | `OUT_x_A`. The contact common. |

> **Pin 1 = NO, Pin 2 = COM on all of J6–J11.** Straight from the generator: `b += j_motion[name][1]` (pin 1 = `OUT_x_B`/NO) and `a += j_motion[name][2]` (pin 2 = `OUT_x_A`/COM); `relay_output()` puts `relay[1]=COM`, `relay[3]=NO`. Metered G5LE-14 map: coil pads 2/5, COM pad 1, NO pad 3, NC pad 4 unused.

**Per-connector map (the only thing that differs):**

| Silk / Ref | Function | NO net (pin 1) | COM net (pin 2) | Relay | Driver | MCP OUT-A pin (port,bit) |
|---|---|---|---|---|---|---|
| **J6 S** | Sweep motor contactor command | `OUT_S_B` | `OUT_S_A` | K1 | Q1 | 21 (GPA0 / 0,0) |
| **J7 T** | Table motor contactor command | `OUT_T_B` | `OUT_T_A` | K2 | Q2 | 22 (GPA1 / 0,1) |
| **J8 SP** | Spot solenoid command | `OUT_SP_B` | `OUT_SP_A` | K3 | Q3 | 23 (GPA2 / 0,2) |
| **J9 BE** | Back-end command | `OUT_BE_B` | `OUT_BE_A` | K4 | Q4 | 24 (GPA3 / 0,3) |
| **J10 M** | Master / control command | `OUT_M_B` | `OUT_M_A` | K5 | Q5 | 25 (GPA4 / 0,4) |
| **J11 M2** | Sweep-reverse command | `OUT_M2_B` | `OUT_M2_A` | K6 | Q6 | 26 (GPA5 / 0,5) |
| *J12 M1 (DNP)* | Ball-return command | `OUT_M1_B` | `OUT_M1_A` | K7 *(DNP)* | Q7 *(DNP)* | 27 (GPA6 / 0,6) |

> **Watch the M2/M1 ordering:** M2 = bit 5 / MCP pin 26 (J11, populated); M1 = bit 6 / MCP pin 27 (J12, **DNP — do not solder**). This ordering was a real bug-class Codex caught; the maps were corrected to agree with the netlist. **J12/K7 stays empty.**

> How a relay fires: MCP OUT-A bit → `DRV_x` → 1 kΩ → MMBT3904 base (100 kΩ pull-down so it's OFF on float/reset) → NPN sinks the coil low side; **coil high side is `RELAY_ENABLE_RAIL`, not raw 5 V**. So a contact closes only when the FSM sets the bit AND the safety rail holds the rail up. Snubber/MOV across each contact are **DNP** until the inductive AC load is characterized.

> **(VERIFY: G5LE-14 contact rating vs measured S/T/SP/BE/M/M2 control loads)** and **(VERIFY: M2 sweep-reverse interlock/shorting-plug preservation in the harness)** — both open assembly/cutover items in the spec. Neither affects logic-only bench bring-up.

---

### J13 — `J_LAMP_LED` (status-LED drive, 6-pos, 3.5 mm)

Drives the four mask LEDs. **Not machine-isolated** — board-supplied LEDs off `VCC_5V` through low-side FET sinks. Not on the safety rail.

| Pin | Signal | Net | Driver FET | MCP OUT-A pin (port,bit) | Notes |
|---|---|---|---|---|---|
| 1 | +5 V LED supply | `VCC_5V` | — | — | **Common anode** feed for all four LEDs. |
| 2 | Logic GND | `GND` | — | — | |
| 3 | L_FIRST return | `LED_L_FIRST_RETURN` | Q8 (2N7002) | 28 (GPA7 / 0,7) | 1st-ball lamp. 330 R limit (R90). |
| 4 | L_SECOND return | `LED_L_SECOND_RETURN` | Q9 | 1 (GPB0 / 1,0) | 2nd-ball lamp. 330 R (R93). |
| 5 | L_STRIKE return | `LED_L_STRIKE_RETURN` | Q10 | 2 (GPB1 / 1,1) | Strike lamp. 330 R (R96). |
| 6 | L_FOUL return | `LED_L_FOUL_RETURN` | Q11 | 3 (GPB2 / 1,2) | Foul lamp. 330 R (R99). |

> Wire each external LED **anode → pin 1 (`VCC_5V`)**, **cathode → its return pin (3/4/5/6)**. Setting the OUT-A bit turns on the 2N7002, sinks the return to GND, lights the lamp. Bit map (`L_FIRST`=GPA7 … `L_FOUL`=GPB2) matches `OUT_A_MAP` (first_ball/second_ball/strike/foul).

> **(VERIFY: mask LED type + current-limit value.)** The 330 Ω is a scaffold placeholder; the actual LED + per-channel resistor for bowling-center brightness are an open assembly item. Confirm before populating R90/R93/R96/R99.

---

### J14 — `J_SAFETY` (hardware interlock loops, 4-pos, 3.5 mm)

Two external **normally-closed (NC)** interlock loops, wired **in series** between `VCC_5V` and the relay-enable pass-FET gate. **No software can bypass this** — if either loop opens, the rail collapses and every motion relay coil de-energizes.

| Pin | Signal | Net | Notes |
|---|---|---|---|
| 1 | +5 V loop source | `VCC_5V` | Start of the series interlock string. |
| 2 | TB/SC loop return → next loop | `SAFE_TBSC_RETURN` | Far end of the **TB/SC** NC loop; **internally the same net as pin 3.** |
| 3 | Stop/CIS loop source | `SAFE_TBSC_RETURN` | Same net as pin 2 — start of the **Stop/CIS/master** NC loop. |
| 4 | Stop/CIS loop return → pass-FET source | `SAFE_STOP_RETURN` | Far end; lands on AO3401A (Q14) source + 100 kΩ gate pull-up. |

> Wiring: `VCC_5V` (pin 1) → external **TB/SC** contacts → pin 2; pins 2 & 3 are the same board net, so the string continues out pin 3 → external **Stop/CIS/master** contacts → pin 4 → Q14 source. The rail comes up only when **both loops are closed** AND the downstream AND-chain (`ARM_PERMIT` + `RP2040_OK` + NE555 watchdog-OK) pulls Q14's gate low. Any one false condition leaves the rail dead.

> **Bench bring-up (logic-only, no machine):** to bring `RELAY_ENABLE_RAIL` up on the bench you must satisfy both loops — **jumper pin 1↔2 and pin 3↔4**. Do **not** jumper pin 1→4 (that defeats both interlocks). Because this board is not connected to any machine, these jumpers are safe here; **remove them before cutover.**

> **(VERIFY: TB/SC + Stop/CIS electrical form and polarity.)** The exact loop derivation (cam contacts vs 24 V control path vs isolated low-voltage loop) and final connector polarity are an open assembly/cutover item. The board makes the interlock a first-class rail condition; the loop *source* is harness-resolved at the machine.

---

### Test points that prove a connector is live (for use during bring-up)

| TP | Net | Confirms |
|---|---|---|
| TP1 | `VCC_5V` | J1 pin 1, J2 (post-D17), J13 pin 1 |
| TP2 | `GND` | logic ground |
| TP3 | `VCC_3V3` | J1 pin 11 (I2C / opto logic rail) — only present once A1 is powered |
| TP4 | `FIELD_WET_V` | isolated wetting source for J3/J4/J5 (only present once U37 is in) |
| TP5 | `FIELD_GND` | J3 pins 9/10, J4 pin 14, J5 pin 12 |
| TP6 / TP7 | `I2C_SDA` / `I2C_SCL` | J1 pins 3 / 4 |
| TP8 | `WDOG_KICK` | J1 pin 7 |
| TP13 | `ARM_PERMIT` | J1 pin 8 |
| TP14 | `RP2040_OK` | J1 pin 13 |
| TP15 | `SAFE_STOP_RETURN` | J14 pin 4 |
| TP16 | `RELAY_ENABLE_RAIL` | the rail that energizes every J6–J11 relay coil |

Expected isolation check before powering relays: with the board powered and both safety jumpers OUT, **TP16 ≈ 0 V** (rail dead). DMM between TP2 (`GND`) and TP5 (`FIELD_GND`) should read **open / no continuity** — that confirms the isolation barrier is intact before you wire any field harness.

---

Source files cited: `scripts/generate_kicad_netlist_revB.py` (authoritative — `block_connectors`, `block_rail`, `block_rp2040`, `opto_input`, `relay_output`, `lamp_led_output`, the `FAST_INPUTS` / `SLOW_INPUT_PINS` / `OUTPUT_PINS` maps); `docs/manual_src/11_connector-pinouts.md` §11.0–§11.11; cross-checks in `12_channel-maps.md` (GPIO/MCP bit maps) and `firmware/rp2040/config.h` (UART crossover, GP6–GP13). Pi-side harness caveat from `docs/phase8_pi_provisioning.md`. All **(VERIFY: …)** flags trace to `phase8b_pcb_revB_spec.md` open assembly/cutover items as noted inline.

---

## First Power & Test-Point Verification (the spec §12.9 sequence)

This is the **power-on, logic-only bench bring-up** of an as-received rev-B board that you have just hand-soldered (J2 → A1 → U37 → J1 → J14 → J6–J11 → J3/J4/J5 → J13). The board is **not connected to any machine** — the only hazards are to the board (ESD, solder shorts). Work the steps **in order**; each gates the next. Keep a written bench log with the actual meter reading for every step, because these readings are your G1 evidence for the cutover gate (`21_bringup-cutover.md` §21.2, gate G1).

> **Two ground references, never bonded.** This board has `GND` (logic) and `FIELD_GND` (isolated), and the audit proved they share **zero nodes** (`13_layout-mfg.md` §13.2: GND = 93 pads, FIELD_GND = 6 pads, 0 shared). Do **not** clip your scope/meter ground to both at once and do **not** jumper them — U37's whole job is to keep them apart (`22_troubleshooting.md` §22.0 item 4). For all LOGIC-domain readings (TP1, TP3, TP6–TP16) reference **TP2 (GND)**. For the one FIELD reading (TP4) reference **TP5 (FIELD_GND)**.

> **TP pads are not silk-labeled.** Per `13_layout-mfg.md` §13.7, the 16 test pads (1.5 × 1.5 mm) carry no individual silk labels on this board. Map TP1–TP16 by position from the reference table at the end of this section or from `review/wsl-phase8b-revB-review-layers.pdf`. The connectors **are** silk-labeled (`J1 PI`, `J2 5V IN`, `J14 SAFETY LOOP`, `J6 S` … `J11 M2`, etc.).

### TP1–TP16 reference table (your bench meter taps)

Source: `13_layout-mfg.md` §13.7 + `11_connector-pinouts.md` §11.10 (the authoritative net→TP map from `dnp-excluded.csv`).

| TP | Net | Domain | Reference to | What it tells you |
|---|---|---|---|---|
| **TP1** | `VCC_5V` | LOGIC pwr | TP2 | Protected 5 V rail (after SS14 D17) |
| **TP2** | `GND` | LOGIC ret | — | Logic ground (your meter common for all LOGIC TPs) |
| **TP3** | `VCC_3V3` | LOGIC pwr | TP2 | Pico-sourced 3.3 V (MCP + opto-logic rail) |
| **TP4** | `FIELD_WET_V` | FIELD | **TP5** | Isolated wetting supply (U37 output) |
| **TP5** | `FIELD_GND` | FIELD | — | Isolated field ground — **must read distinct from TP2** |
| **TP6** | `I2C_SDA` | LOGIC sig | TP2 | I²C data to the 3 MCP23017s |
| **TP7** | `I2C_SCL` | LOGIC sig | TP2 | I²C clock |
| **TP8** | `WDOG_KICK` | LOGIC sig | TP2 | Pi kick pulse into the NE555 (before the kick FET) |
| **TP9** | `WDOG_TIMING_NODE` | LOGIC sig | TP2 | NE555 timing-cap (C11) node — watch it ramp |
| **TP10** | `NE555_TRIG` | LOGIC sig | TP2 | NE555 trigger (Rev-A trigger pull-up fix) |
| **TP11** | `NE555_OUT` | LOGIC sig | TP2 | NE555 monostable output (watchdog-OK before the gate) |
| **TP12** | `WDOG_OK_PULLDOWN` | LOGIC sig | TP2 | Watchdog-OK contribution into the rail AND chain (Q13 drain) |
| **TP13** | `ARM_PERMIT` | LOGIC sig | TP2 | Pi arm permission (rail condition 2) |
| **TP14** | `RP2040_OK` | LOGIC sig | TP2 | RP2040 health / cam-stop permit = Pico GP2 (rail condition 3/4) |
| **TP15** | `SAFE_STOP_RETURN` | Safety_Rail | TP2 | Bottom of the J14 NC interlock series loop, into the pass-FET source |
| **TP16** | `RELAY_ENABLE_RAIL` | Safety_Rail | TP2 | **The rail itself** — must be live for any motion relay coil to energize |

---

### Step 0 — Pre-power continuity check (board OFF, no supply attached)

Before any voltage touches the board, ohm-out the rails with the supply **disconnected**. A short here means a solder bridge from your hand-soldering (most likely under A1, U37, or a Phoenix pad) — find it now, not by watching a part smoke.

Meter on **continuity/diode or low-ohms**. Probe between each rail and GND:

| # | Probe A | Probe B | Expected | Go / No-Go |
|---|---|---|---|---|
| 0a | TP1 (`VCC_5V`) | TP2 (`GND`) | **Not a dead short.** A few hundred Ω rising as caps charge through the meter is normal; a hard 0 Ω is a fault. | **0 Ω → STOP**, find the bridge before powering. |
| 0b | TP3 (`VCC_3V3`) | TP2 (`GND`) | Not a dead short (A1 not yet powered, so 3V3 is open/high-Z — expect high resistance). | 0 Ω → STOP. |
| 0c | TP16 (`RELAY_ENABLE_RAIL`) | TP2 (`GND`) | Not a dead short. The rail sits behind the Q14 pass-FET and 6 relay coils; expect high resistance, **not** 0 Ω. | 0 Ω → STOP (suspect a coil-rail bridge or a relay pad short). |
| 0d | TP5 (`FIELD_GND`) | TP2 (`GND`) | **OPEN / no continuity** — this is the isolation barrier (`06_board-power.md` §6.9; audit: 0 shared nodes). | **Any continuity → STOP.** GND↔FIELD_GND bonded = U37 mis-fitted or a field/logic gutter bridge. |

> Optional but recommended: also confirm TP1↔TP3 are **not** shorted to each other (5 V into the 3.3 V rail would kill the MCPs and back-feed the Pi). Expect high resistance.

**Pass 0 = no hard short on any rail, and TP5 isolated from TP2.** Only then attach power.

---

### Step 1 — Apply regulated 5 V to J2, confirm VCC_5V (TP1)

Per `06_board-power.md` §6.2 / `11_connector-pinouts.md` §11.3, J2 (`J2 5V IN`, the 3-pos MKDS screw block) lands **bare wire**:

- **J2 pin 1 = `VCC_5V_RAW` (+5 V)**
- **J2 pins 2 & 3 = `GND`**

Use a current-limited regulated bench supply set to **≥ 1.5 A** capability (3 A comfortable, per §6.5.2). Start with the limit set low (~250 mA) for the first power-on so a missed short trips the limit instead of cooking copper.

1. Wire +5 V → J2.1, supply ground → J2.2 (and J2.3). Double-check polarity — D17 (SS14) protects against reversal, but verify anyway.
2. **Important — trim the supply UP.** The on-board reverse-polarity Schottky **D17 (SS14)** drops ~0.3–0.5 V (§6.2.2), so a supply set to exactly 5.00 V lands `VCC_5V` at ~4.6–4.7 V. To land `VCC_5V` near **~4.8 V**, set the supply to roughly **5.2–5.3 V**.
3. Power on. Watch the current draw: logic-only (no relays energized, A1 not yet fitted) should be **tens of mA**, not hundreds.

| Probe | Expected | Go / No-Go |
|---|---|---|
| **TP1 (`VCC_5V`) → TP2 (`GND`)** | **≈ 4.8 V** (4.6–4.8 V acceptable; = supply minus the SS14 Vf, §6.9) | **< 4.5 V** → either supply too low, or D17 backward / a partial short. **No part hot to the touch.** Any hot part → power off, STOP. |

> Note: at this point **TP3 (`VCC_3V3`) reads ~0 V / open** — that is expected. 3.3 V comes from the Pico (A1), which isn't powered into VSYS until the rail is up *and* A1 is fitted. Likewise TP16 (the rail) is **0 V** — correct, the safety chain is not satisfied (J14 open, A1 absent, no watchdog). A dead rail is the safe default (`22_troubleshooting.md` §22.0 item 6).

**Pass 1 = TP1 ≈ 4.8 V, nothing hot.** Raise the supply current limit to ~1.5 A for the rest of the bring-up.

---

### Step 2 — Fit + power A1 (Pico), confirm VCC_3V3 (TP3)

The 3.3 V rail is **sourced by the Pico's own regulator** — there is no on-board 3V3 regulator (`06_board-power.md` §6.3). With A1 fitted, `VCC_5V` feeds Pico VSYS (pin 39) and the Pico's pin 36 (3V3 OUT) becomes `VCC_3V3`, which powers all 3× MCP23017 and every opto logic-side pull-up.

A1 should already be soldered (it's earlier in your solder order), so this step is a **verification with power applied**:

| Probe | Expected | Go / No-Go |
|---|---|---|
| **TP3 (`VCC_3V3`) → TP2 (`GND`)** | **≈ 3.3 V** (Pico's regulated 3V3 OUT) | If **0 V**: A1 not seated / VSYS (pin 39) not getting `VCC_5V` / a 3V3-rail short. Check A1's GND pins (3, 8, 13, 18, 23, 28, 33, 38) and pin 39 = VSYS, pin 36 = 3V3 OUT (§12.2.1). **No MCP work until this is 3.3 V** — the MCPs and opto pull-ups are dark without it (§6.3, "Consequence for bench bring-up"). |

**Pass 2 = TP3 ≈ 3.3 V.**

---

### Step 3 — Fit + power U37, confirm FIELD_WET_V (TP4) AND isolation (TP5↔TP2)

U37 (`J2 5V IN` area, the TMA-0505S SIP-7) is the isolated field-wetting supply (`06_board-power.md` §6.4). Its primary sits in the logic domain (`+Vin=VCC_5V`, `-Vin=GND`); its secondary is the **isolated** field domain (`+Vout=FIELD_WET_V`, `-Vout=FIELD_GND`) — confirmed in `generate_kicad_netlist_revB.py` `block_supplies()`. Without U37 there is no wetting supply and dry-contact inputs cannot be sensed.

Two readings — the **voltage** and the **isolation proof**:

| # | Probe | Expected | Go / No-Go |
|---|---|---|---|
| 3a | **TP4 (`FIELD_WET_V`) → TP5 (`FIELD_GND`)** | **≈ +5 V isolated** (U37 output, §6.9) | If **0 V**: U37 not fitted / wrong orientation / a field-side short. The TMA-0505S is a "locked exact part" — confirm it is the TMA-0505S and that the SIP pinout matches (hand-solder BOM, `U37`). |
| 3b | **TP5 (`FIELD_GND`) → TP2 (`GND`)** | **OPEN — no continuity** (isolation intact; §6.9, §13.2) | **Any continuity → STOP.** The isolation barrier is bridged (U37 mis-fitted, or a field/logic copper bridge). This is a safety-defeating fault — do not proceed. |

> Probe 3a with your meter floating between the two **field** test pads only; do not common it to logic GND for this reading.

**Pass 3 = TP4 ≈ 5 V (referenced to TP5) AND TP5 fully isolated from TP2.**

---

### Step 4 — I²C scan from the Pi over J1 → the 3× MCP23017 answer at 0x20 / 0x21 / 0x22

Now bring the Pi up against J1 (`J1 PI`, the 2×10 IDC). The board exposes the I²C bus on **J1 pin 3 (`I2C_SDA`)** and **pin 4 (`I2C_SCL`)**, with on-board 4.7 kΩ pull-ups to `VCC_3V3` (`11_connector-pinouts.md` §11.2). The board also feeds the Pi its rails on J1 (pin 1 = `VCC_5V`, pin 11 = `VCC_3V3`, pins 2/12 = `GND`).

> **Wire the J1 ribbon straight-through.** The UART crossover (Pi TX → Pico RX, Pico TX → Pi RX) is already done **on the PCB** (§11.2 "UART naming gotcha"). Do not cross it again in the ribbon. **(VERIFY: J1 ribbon pin-1 / shroud keying** — the J1 mating socket is a *candidate* (CNC Tech 3030-20-0102-00) and §11.2 flags "confirm cable keying/orientation"; confirm pin-1 alignment between board and Pi before crimping.)

1. Connect the Pi to J1 via the 2×10 ribbon. Confirm at the Pi end that the board's rails are present on the ribbon (J1 pin 1 ≈ 4.8 V, pin 11 ≈ 3.3 V) before trusting the bus.
2. On the Pi, scan the board's I²C bus (`i2cdetect` on the bus this board lands on — `i2c-1` for board 1, the `dtoverlay=i2c-gpio` bus for board 2 per `12_channel-maps.md` §12.1).

| Probe / check | Expected | Go / No-Go |
|---|---|---|
| `i2cdetect` on the board's bus | **Three devices answer: `0x20` (U1, IN-A), `0x21` (U2, IN-B), `0x22` (U3, OUT-A)** (§12.3; addresses set by A2/A1/A0 straps) | Missing a device → re-check that MCP's SOIC-28 solder, its address straps, and the two I²C pull-ups (R1/R2, 4.7 kΩ to 3V3). |
| **TP6 (`I2C_SDA`) / TP7 (`I2C_SCL`) → TP2** | Both idle **HIGH ≈ 3.3 V** between transactions (pulled up); you'll see them toggle during the scan on a scope | Stuck LOW on either = bus contention / pull-up missing / a shorted MCP. |

> If `i2cdetect` finds nothing at all: confirm TP3 = 3.3 V (step 2) and that the bus pull-ups are present — without the 3V3 rail the MCPs can't answer (§22.4.3, "I²C bus not enumerating").

**Pass 4 = all three MCP23017 enumerate at 0x20 / 0x21 / 0x22.**

---

### Step 5 — Flash the Pico, confirm boot + ~4 Hz heartbeat + RP2040_OK (TP14) HIGH

Flash the **already-built** firmware image at `firmware/rp2040/build/wsl_phase8b_rp2040.uf2` (the v1.1.0 build; all v1.1 enforcement flags ship **OFF**, so on-the-wire behavior is exactly v0.2.0 health + 8 s max-run backstop — `firmware/rp2040/README.md` "Status / next").

1. **BOOTSEL drag-drop (preferred):** hold BOOTSEL on the Pico while connecting its USB → it mounts as **`RPI-RP2`** → drag-drop `wsl_phase8b_rp2040.uf2` onto it. It reboots automatically. (SWD via `picotool load -x` is the fallback once soldered — README "Flash".)
2. Open the Pi↔Pico UART on J1 pins 5/6 at **115200 8N1** (or USB-CDC if you built `-DDEBUG_USB`).

Expected on the wire (README "Bench bring-up" step 1, UART protocol):

```
{"ev":"boot","fw":"phase8b-rp2040 v1.1.0","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000,"dbg":0}
{"ev":"hb","ok":1,"flt":"","up":...,"drp":0,"in":0,"run":0}      <- ~every 250 ms (~4 Hz)
```

| Probe / check | Expected | Go / No-Go |
|---|---|---|
| UART log | a single **`boot`** line, then **`hb`** lines at **~4 Hz** (`HB_INTERVAL_MS` = 250 ms) with **`ok:1`** | No boot line → check A1 solder, UART crossover (Pi TX → GP1, Pico GP0 → Pi RX), and that the `.uf2` actually copied. README "bench-only gates". |
| **TP14 (`RP2040_OK`) → TP2** | **LOW at boot**, then goes **HIGH ≈ 3.3 V about 200 ms after boot** (`BOOT_SETTLE_MS` = 200 ms) once healthy with no latched fault | TP14 stuck LOW with `ok:1` on the wire → suspect the GP2 trace or the AND-chain pulldown (R110). TP14 HIGH but no `hb` → UART path, not the rail line. |

> The boot field **`maxrun_ms`:8000** is the firmware's compile-time max-run backstop. The Pi must refuse to arm if its `MAX_MOTION_S` exceeds it; at the bench just confirm it reads 8000 (matches `cycle_control_8270.MAX_MOTION_S = 8.0 s`, §12.10).

**Pass 5 = boot line + steady ~4 Hz `hb ok:1`, and TP14 goes HIGH ~200 ms after boot.**

---

### Step 6 — Watchdog drop test (stop kicking WDOG_KICK → TP14 LOW → TP16 drops)

This proves the firmware health line (rail condition 3) and the on-chip watchdog are fail-safe. The Pi kicks `WDOG_KICK` (J1 pin 7 → TP8) to keep the **NE555** (U36) happy; that's a *separate* watchdog (the NE555 watches the Pi). This step exercises the **RP2040** side — stop the firmware loop and confirm GP2 drops the rail.

Per README "Bench bring-up" step 3 / `21_bringup-cutover.md` §21.2 step 4:

1. With the board healthy (TP14 HIGH), **stop the firmware loop** — pull power to just the Pico (or force a hang). 
2. Watch TP14 and TP16.

| Probe | Expected | Go / No-Go |
|---|---|---|
| **TP14 (`RP2040_OK`)** | goes **LOW** (GP2 → Hi-Z on power loss; the on-board 100 kΩ pulldown R110 holds it down) | Stays HIGH with the Pico dead → GP2 not actually pulled down; the rail is **not** fail-safe — STOP and fix before any further step. |
| **TP16 (`RELAY_ENABLE_RAIL`)** | **drops toward 0 V** (rail condition 3 false → Q16 off → gate held up → Q14 off) | Rail stays up with TP14 LOW → the AND chain isn't gating on RP2040_OK; STOP. |

For the **NE555 / Pi-kick** half (rail condition 1): with the loop running and the rail armed (step 8 jumpers in place), **stop the Pi's kick** on `WDOG_KICK`. Watch **TP8** (kick pulses stop), **TP9** (`WDOG_TIMING_NODE`, the C11 timing cap, ramps), **TP11** (`NE555_OUT`) flips, **TP12** (`WDOG_OK_PULLDOWN`) releases → **TP16 drops**. **(VERIFY: the NE555 drop time** — R100 100 kΩ × C11 100 µF computes ~11 s textbook, but the design states it qualitatively as "~10 s"; treat the precise number as **bench-measured**, do not assume 11 s — §22.7 / §12.10.)

**Pass 6 = stopping the kick (either watchdog) drops TP16.**

---

### Step 7 — ARM test (TP13 ARM_PERMIT, rail condition 2)

`ARM_PERMIT` (J1 pin 8 → TP13) is rail condition 2 — driven HIGH by the Pi only after an operator-safe state. De-assert it and confirm the rail drops (README/`21_bringup-cutover.md` §21.2 step 5).

| Probe | Action | Expected | Go / No-Go |
|---|---|---|---|
| **TP13 (`ARM_PERMIT`)** | De-assert the Pi's ARM GPIO | TP13 reads **LOW** | — |
| **TP16 (`RELAY_ENABLE_RAIL`)** | (after de-assert) | **drops** (Q15 off → gate held up by R106 → Q14 off) | Rail stays up with TP13 LOW → check Q15 (AND ARM) and its base network (Rb 10 kΩ / Rpd 100 kΩ). Default-off pulldown is R108 100 kΩ. |

> Conversely, with TP13 HIGH, TP14 HIGH, and **both J14 loops closed** (step 8) and the watchdog kicked, **TP16 should come UP ≈ VCC_5V** — that is the only condition under which the rail arms. This is your positive proof the AND chain works.

**Pass 7 = de-asserting ARM drops TP16; asserting all conditions raises it.**

---

### Step 8 — J14 interlock loops (jumper 1-2 and 3-4 closed — NEVER 1-4)

J14 (`J14 SAFETY LOOP`, the 4-pos MCV) carries the **two external NC interlock loops in series** with the pass-FET source (`11_connector-pinouts.md` §11.9; `generate_kicad_netlist_revB.py` `block_rail()`):

- **Pins 1↔2 = TB/SC collision interlock loop** (`VCC_5V` → `SAFE_TBSC_RETURN`)
- **Pins 3↔4 = Stop/CIS/master chain loop** (`SAFE_TBSC_RETURN` → `SAFE_STOP_RETURN` → Q14 source)

On the bench there are no machine loops, so close them with jumpers — **jumper pins 1-2 and jumper pins 3-4**. Both loops are then "satisfied" (NC = closed when safe) and the FET source can reach +5 V.

> ⛔ **NEVER jumper pin 1 → pin 4.** That bypasses both interlocks and defeats the entire hardware safety loop (§11.9 explicit warning). Use **two separate** jumpers (1-2 and 3-4) only, only on this off-machine bench board, and remove them before cutover.

| # | Action | Probe | Expected | Go / No-Go |
|---|---|---|---|---|
| 8a | Jumper 1-2 **and** 3-4; ARM asserted (TP13 HIGH), RP2040 healthy (TP14 HIGH), watchdog kicked | **TP15 (`SAFE_STOP_RETURN`) → TP2** | **≈ +5 V** (both loops closed → source fed) | TP15 ≈ 0 V with both jumpers in → a loop isn't actually closed / Q14 source open. |
| 8b | same | **TP16 (`RELAY_ENABLE_RAIL`) → TP2** | **≈ VCC_5V** — the rail is finally **armed** (all 6 conditions true) | TP16 low with TP13/TP14 high and TP15 ≈ 5 V → work back through the watchdog (TP9/TP10/TP11/TP12) and the AND chain (§13.7). |
| 8c | Remove the **1-2** jumper (open TB/SC loop) | TP15, TP16 | **both drop** (FET source dead) | Rail stays up → interlock not in series; STOP. |
| 8d | Re-jumper 1-2, remove the **3-4** jumper (open Stop/CIS loop) | TP15, TP16 | **both drop** | Rail stays up → STOP. |

**Pass 8 = rail arms (TP16 ≈ 5 V) with both loops closed, and opening *either* loop drops TP15 and TP16.** This plus steps 6–7 is five of the six G3 rail-drop conditions proven (watchdog, ARM, RP2040 health, TB/SC, Stop/CIS). **The sixth — per-cam-edge cam-stop overrun — is BLOCKED at the bench** until cam polarity is field-captured (§3.2) and firmware v1.1 flags are armed cam-by-cam; v1.1.0 ships those flags OFF (`19_safety-architecture.md` §19.5, firmware README). At the bench you can prove the GP2→rail path directly (step 6) and the 8 s max-run backstop (drive `RUN S`, wait > 8 s without `STOP S` → `flt:motion_timeout` → TP14 LOW → TP16 drops; `CLEAR` from safe → TP14 back HIGH), which is the max-run sense of step 9 in the spec list.

---

### Step 9 — Each relay K1–K6, COM/NO with a 12 V test-light dummy load

With the rail armed (step 8), command each motion relay through OUT-A (`0x22`) and watch a dummy load on its J_MOTION contact. **The board never sources the contact voltage** — you supply it through the test light. Use a **12 V test lamp** (or a resistor sized to the expected ~24 VAC coil-circuit current) as a stand-in for the machine coil circuit. (`21_bringup-cutover.md` §21.2 step 7.)

Contact pinout is identical on every J_MOTION block (`11_connector-pinouts.md` §11.7): **pin 1 = NO (`OUT_x_B`)**, **pin 2 = COM (`OUT_x_A`)**. Wire your 12 V source: +12 V → lamp → **J_MOTION pin 1 (NO)**; lamp/source return ↔ **J_MOTION pin 2 (COM)**. The lamp lights only when the relay closes COM↔NO.

Relay / connector / OUT-A bit map (§11.7, §12.7):

| Relay | Connector (silk) | Function | OUT-A bit (port,bit) |
|---|---|---|---|
| K1 | J6 (`J6 S`) | Sweep | (0,0) GPA0 |
| K2 | J7 (`J7 T`) | Table | (0,1) GPA1 |
| K3 | J8 (`J8 SP`) | Spot | (0,2) GPA2 |
| K4 | J9 (`J9 BE`) | Back-end | (0,3) GPA3 |
| K5 | J10 (`J10 M`) | Master | (0,4) GPA4 |
| K6 | J11 (`J11 M2`) | Sweep-reverse | (0,5) GPA5 |
| ~~K7~~ | ~~J12 (M1)~~ | Ball-return | **DNP — not present, do not test** |

For each of K1–K6:

| Action | Expected | Go / No-Go |
|---|---|---|
| Set that relay's OUT-A bit (e.g. via `controller_io.py` or a raw I²C write to `0x22`) | relay **clicks**, COM↔NO closes, **the dummy load lights** | No click / no light → confirm the rail is up (TP16 ≈ 5 V) *first* (a dropped rail kills *all* coils, not one — §22.4.3); then trace the bit → MMBT3904 driver (Q1–Q6) → coil → flyback (D1/D3/D5/D7/D9/D11). |
| **Drop the rail** (de-assert ARM, or open a J14 jumper) while the bit is still set | the load **dies the instant the rail drops** | Load stays lit with the rail down → a **welded/stuck contact** or the coil isn't on the rail — STOP (the rail can't open a welded contact; §22.4.4). |

> **M1 / K7 / J12 is DNP** — its relay, driver, and connector are unpopulated by design (§13.6.1). It will not actuate; that is correct, not a fault.

**Pass 9 = each of K1–K6 lights its dummy load on command and extinguishes the instant the rail drops.**

---

### Step 10 — Input front-ends (wet a channel, watch it assert)

Exercise the opto inputs. All inputs are **dry-contact, active-LOW at the logic side**: closing a field contact from the channel pin to `FIELD_GND` lights the PC817 LED (fed from `FIELD_WET_V` through a 2.2 kΩ resistor) and pulls the logic pin LOW = **asserted** (`06_board-power.md` §6.4.3; `12_channel-maps.md` §12.2.2). So to "wet" a channel at the bench, **short its field pin to the connector's FIELD_GND pin**.

Two classes (`11_connector-pinouts.md` §11.4–§11.6):

| Class | Connector (silk) | FIELD_GND return pin | Asserts via | How to verify |
|---|---|---|---|---|
| **Fast** (SA, SB, SC, TA1, TA2, TB, DIELL-L, DIELL-R) | J3 (`J3 FAST`), pins 1–8 | J3 pins 9 & 10 | **RP2040 → UART event** | short the channel pin to J3 pin 9/10 → expect `{"ev":"cam","id":"SA",...}` or `{"ev":"ball","src":"L",...}` with the correct `id` (README step 2) |
| **Slow A** (GS1–10, GP, OS, BS) | J4 (`J4 SLOW A`), pins 1–13 | J4 pin 14 | **MCP IN-A bit (0x20)** | short channel pin to J4 pin 14 → the matching IN-A bit flips (read `0x20` over I²C) |
| **Slow B** (PBZ, PBC, FOUL, TENTH, MAN_*, AUX1–3) | J5 (`J5 SLOW B`), pins 1–11 | J5 pin 12 | **MCP IN-B bit (0x21)** | short channel pin to J5 pin 12 → IN-B bit flips (note: IN-B is configured but not yet read by the FSM — read `0x21` directly; §12.4) |

| Check | Expected | Go / No-Go |
|---|---|---|
| Wet a fast channel (e.g. SA at J3 pin 1 → J3 pin 9) | matching `cam`/`ball` UART event with the correct `id`; on a scope the Pico GPIO goes **LOW** while wetted | No event → check that PC817 (U4–U11 fast), the 2.2 kΩ `Rin`, the 10 kΩ pull-up to 3V3 (`Rpu`), and that **TP4 (`FIELD_WET_V`) ≈ 5 V** (no wetting supply → no opto current). |
| Wet a slow-A channel (e.g. GS1 at J4 pin 1 → J4 pin 14) | IN-A `0x20` bit 0 reads **asserted** (active-low: pin reads 0 = standing, software inverts to 1) | Bit doesn't flip → check that opto (U12–U24), `FIELD_WET_V`, and the MCP IN-A solder. |

> This step also **captures each cam's edge polarity** for the deferred v1.1 cam-stop hook + the cutover field sheet (README step 2 / §3.2) — log which physical edge (`f`/`r`) corresponds to each cam as you wet it. Do **not** enable any v1.1 `CAM_*_STOP_ENABLED` flag here; polarity capture is a record-only step at the bench.

**Pass 10 = every fast input produces the correct UART event and every slow input flips the correct MCP bit.**

---

### Bring-up complete — what "pass" means

**All of steps 0–10 green and logged = the board passes the spec §12.9 / §21.2 bench bring-up** (minus the v1.1-blocked per-cam-edge cam-stop sub-test, which is captured-and-deferred, not failed). Per `21_bringup-cutover.md` §21.2 / gate **G1**, only a board that has passed this whole sequence becomes a candidate for the Track-B controller cutover — and it is **never** wired to a pinsetter until it has. Build the spare unit #2 the same way. Step 10 of the spec list ("machine-harness test") is the cutover itself (§21.3) and is **not** part of this bench bring-up.

---

**Files referenced (all absolute):**
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\21_bringup-cutover.md` (§21.2 step list + TP map; gate G1)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\06_board-power.md` (§6.2 D17/SS14 drop; §6.3 Pico-sourced 3V3; §6.4 U37; §6.9 expected rail values)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\13_layout-mfg.md` (§13.7 TP1–TP16; §13.2 GND/FIELD_GND 0 shared nodes)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\11_connector-pinouts.md` (§11.2 J1, §11.3 J2, §11.4–§11.7 J3/J4/J5/J6–J12 pinouts, §11.9 J14 loops, §11.10 TP map)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\12_channel-maps.md` (§12.2.2 active-low opto, §12.3 MCP addresses, §12.7 OUT-A relay bit map, §12.10 watchdog timing)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\19_safety-architecture.md` (§19.5 G3 cam-stop blocked-until-v1.1, six rail conditions)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\manual_src\22_troubleshooting.md` (§22.0 safe handling, §22.4 rail-down diagnosis, §22.7 watchdog drop-time VERIFY)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\firmware\rp2040\README.md` (flash via BOOTSEL; boot line + ~4 Hz heartbeat; bench bring-up steps; v1.1 flags ship OFF)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\scripts\generate_kicad_netlist_revB.py` (`block_rail()` rail topology; `block_supplies()` U37 isolated nets — authoritative)
- `C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\fab_revB_routed_manual\assembly\wsl-phase8b-revB-hand-solder-bom.csv` (A1, U37, J1–J14 hand-solder set)

**Flagged uncertainties:** (1) NE555 watchdog drop time is **bench-measured, not source-declared** — ~10 s qualitative, ~11 s computed; do not assume. (2) J1 ribbon pin-1/keying is a "confirm" item (mating socket is a candidate). (3) Per-cam-edge cam-stop overrun (rail condition 4 sub-test) is **blocked at the bench** pending §3.2 cam-polarity capture + v1.1 flag arming; only the max-run-backstop sense is bench-provable today.

---

## Troubleshooting (Bench Bring-Up)

This section is the symptom → likely cause → fix table for the **logic-only bench bring-up** of a hand-soldered rev-B board — no machine attached, the only hazards are to the board (ESD, solder shorts). It assumes you are working the rail-fit order from §06.8 / §21.2.1 (`J2 → A1 → U37 → J1 → J14 → J6-J11 → J3/J4/J5 → J13`) and probing the test pads in §11.10 / §21.2.2. Every fix points back to a hand-soldered joint, an orientation, or a rail dependency, because on a JLC-PCBA board the SMT/wave parts are already placed — **a first-power fault is almost always in your hand-solder work or the supply, not the placed silicon.**

> **Probe discipline (carry this through every table).** Logic ground is **TP2 (`GND`)**; isolated field ground is **TP5 (`FIELD_GND`)**. They share **zero nodes** by design (§06.1, isolation audit). Reference logic-domain measurements (TP1/TP3/TP6-TP16) to **TP2**, and field-domain measurements (TP4) to **TP5**. **Never clip your meter/scope ground across the two** — bonding GND to FIELD_GND defeats the U37 barrier and invalidates the isolation check in §6.2 below.

> **A "dead" rail is the safe state, not always a fault (§22.0 item 6).** `RELAY_ENABLE_RAIL` (TP16) is *designed* to read 0 V until all six AND conditions are satisfied — and at the bench, with no J14 jumpers and an un-armed Pi, it **should** be 0 V. Confirm a rail is *supposed* to be up before you treat 0 V at TP16 as a defect.

---

### TS.1 No / low `VCC_3V3` (TP3) — the 3.3 V rail is dead

3.3 V on this board comes **only from the Pico's on-board regulator (A1, pin 36)** — there is no dedicated 3V3 LDO (§06.3). So `VCC_3V3` is a direct proxy for "is A1 fitted, oriented, soldered, and powered." A JLC bare board with A1 not yet hand-soldered will show 5 V at TP1 but a dead TP3 — that is expected, not a fault, until you fit A1 (§06.8).

**Expected when healthy:** TP1 (`VCC_5V`) ≈ 4.6–4.8 V (5 V in minus the SS14 Vf, §06.2.2); TP3 (`VCC_3V3`) ≈ 3.3 V; measured to TP2.

| Symptom | Likely cause | Fix |
|---|---|---|
| TP3 = 0 V, TP1 ≈ 4.7 V, board not hot | **A1 (Pico) not yet fitted** — the most common "fault" (it's the first hand-solder part with a rail dependency) | Fit A1 per the rail-fit order. There is no 3V3 (and the MCPs/opto pull-ups stay dark) until A1 is on and powered (§06.3 note, §06.8). |
| TP3 = 0 V even with A1 fitted; TP1 ≈ 4.7 V | **A1 VSYS not getting 5 V** — cold/open joint on Pico **pin 39 (VSYS)**, which is fed from `VCC_5V` (§12.2.1) | Reflow Pico pin 39. Confirm continuity from TP1 to A1 pin 39. |
| TP3 = 0 V; A1 fitted; pin 39 has 5 V | **Cold/open castellation on the 3V3 OUT pin** (A1 **pin 36** → `VCC_3V3`) | Reflow A1 pin 36. The castellated SC0915 needs each pad heated through the half-via — drag-solder and inspect every joint under magnification. |
| TP3 low / sagging (e.g. ~2 V), A1 warm or hot | **A1 backwards, or a short on the 3V3 rail** (solder bridge at A1, an MCP, or the `C_3V3_BULK` 10 µF cap) — the Pico regulator is current-limiting or back-powered | Power off immediately. Verify A1 pin-1 orientation against the silk "J1 PI / LOGIC / SAFETY" datum. Inspect A1 castellations + the three MCP SOIC-28 banks for bridges; ohm TP3→TP2 (should be high-kΩ, not near 0). |
| TP3 = 0 V and TP1 also = 0 V | Not a 3V3 problem — **no 5 V at all** (see TS.5: D17/J2/source) | Fix the 5 V rail first; 3V3 can't exist without it. |
| **A1 won't power at all** (no `RPI-RP2`, no UART, TP3 dead) | A1 is not getting VSYS, **or A1 is not actually flashed/booting** | See TS.3 (BOOTSEL/flash) and TS.4 (RP2040_OK). A1 that enumerates over USB but shows no TP3 = a pin-36 joint; A1 with TP3 good but no boot = firmware. |

> **Do not** chase TP3 with a bench supply forced onto the 3V3 rail — you'd back-drive the Pico's regulator. Fix the joint/orientation and let A1 source it.

---

### TS.2 MCP23017s not enumerating on I²C

All three expanders must answer on the board's own bus: **IN-A `0x20` (U1), IN-B `0x21` (U2), OUT-A `0x22` (U3)** (§11.11, §12.3). If `i2cdetect` (run from the Pi over J1) shows none/some missing, no slow inputs or relay/lamp outputs work. The MCPs and the bus pull-ups all hang off `VCC_3V3`, so **fix TS.1 first** — a dead 3V3 rail looks like "no MCPs."

| Symptom | Likely cause | Fix |
|---|---|---|
| **No** address answers (`0x20/0x21/0x22` all absent) | **`VCC_3V3` dead** (TS.1) — VDD of all three MCPs is 3V3 (pin 9), so they're unpowered | Confirm TP3 ≈ 3.3 V first (TS.1). |
| No address answers, TP3 good | **I²C bus not reaching the chips** — missing/weak pull-ups, or SDA/SCL not landing | Confirm the **4.7 kΩ pull-ups to 3V3**: R1 on SDA, R2 on SCL (§11.2). With the bus idle, TP6 (`I2C_SDA`) and TP7 (`I2C_SCL`) should each sit at ≈ 3.3 V (idle-high). If a line sits at 0 V → that line is shorted/stuck. |
| No answers; TP6/TP7 both idle-high | **SDA/SCL swapped at the J1 ribbon** to the Pi (board has SDA on J1 pin 3, SCL on pin 4 — §11.2) | Confirm the ribbon maps Pi SDA→J1 pin 3, Pi SCL→J1 pin 4. TP6=J1 pin 3, TP7=J1 pin 4 (§11.10). |
| **One or two** chips answer, another is missing | **Address-strap (A2/A1/A0) error or a SOIC-28 solder issue** on the missing chip. Straps (A2,A1,A0): U1 IN-A = `000`→0x20, U2 IN-B = `100`→0x21, U3 OUT-A = `010`→0x22 (§12.3). A bridged/open strap moves or kills an address. | Inspect the strap pins (MCP pins 15/16/17 = A0/A1/A2) on the missing chip for a bridge to VCC/GND that flips its address; inspect the SOIC-28 leg field for a bridge/cold leg on SDA(13)/SCL(12)/VDD(9)/VSS(10)/~RESET(18). ~RESET (pin 18) must be tied to `VCC_3V3` (held de-asserted) — a floating/low ~RESET holds that chip off the bus. |
| A chip answers at the **wrong** address (e.g. a phantom `0x24`) | **One strap pin bridged high** | Find the bridged A0/A1/A2 leg and clear it. (These are JLC-placed parts — a bridge here is rare but is the classic "wrong address" signature.) |
| Bus answers but reads/writes are garbage | **SDA/SCL bridged to each other** or to an adjacent net | Reflow/clean U1-U3 SDA/SCL legs; re-scope TP6/TP7 for clean idle-high. |

> Note these are **JLC-placed SOIC-28 parts**, not your hand-solder work — so on a freshly-received board the strap and SOIC bridges are unlikely. Suspect the **hand-soldered J1 ribbon path and the 3V3 rail (A1)** before you suspect the placed MCPs.

---

### TS.3 No `FIELD_WET_V` (TP4) / FIELD_GND isolation breach

The isolated field-wetting 5 V comes **only from U37 (TRACO TMA-0505S)**, a hand-soldered SIP-7 by the silk "J2 5V IN" / ISO supply (§06.4, hand-solder BOM). No U37 → no `FIELD_WET_V` → no dry-contact input can be sensed. U37 is the part that keeps a machine-side fault off the Pi, so its isolation is a hard check, not a nicety.

**Expected when healthy:** TP4 (`FIELD_WET_V`) ≈ +5 V referenced **to TP5 (`FIELD_GND`)**; and **TP5↔TP2 reads open / no continuity** (the isolation proof, §6.9).

| Symptom | Likely cause | Fix |
|---|---|---|
| TP4 = 0 V (to TP5) | **U37 not yet fitted** — expected on a fresh board until you hand-solder it (§06.8) | Fit U37. Until it's on, dry-contact inputs (J3/J4/J5) cannot be wet/sensed — that's expected, not a fault. |
| TP4 = 0 V, U37 fitted | **U37 backwards / wrong pin orientation, or a cold SIP joint on +Vin/−Vin** — primary is `+Vin=VCC_5V`, `−Vin=GND` (§06.4.2) | Verify U37 pin-1/orientation against the footprint render (the TMA-0505S is a SIP-7; pinout is *not* symmetric — confirm against the TRACO datasheet before reflow). Confirm ≈5 V across its **input** pins (+Vin to −Vin, i.e. TP1-ref). If input has 5 V and output is dead → cold output joint or a dead brick. |
| TP4 low / unstable, U37 warm | **Short on the field rail** (`FIELD_WET_V`/`FIELD_GND`) — a bridge on a J3/J4/J5 opto field-side, or U37 output bridged | Power off; ohm TP4→TP5 (should be high, not ~0). Inspect the field-side legs of the input optos and U37's +Vout/−Vout. |
| **TP5 (`FIELD_GND`) is continuous with TP2 (`GND`)** — isolation breach | **Solder bridge across the U37 isolation barrier**, or a field-gnd-to-logic-gnd short anywhere (a J3/J4/J5 field-ground pin bridged to a logic net, a probe clip left bonding them) | **Stop — this defeats the whole isolation design.** Ohm TP5→TP2: it must be **open**. If shorted: first remove any test jumper/scope-ground bonding the two; then inspect under U37 for a bridge spanning primary↔secondary; then inspect J3 pins 9/10, J4 pin 14, J5 pin 12 (all `FIELD_GND`) for a bridge to an adjacent logic pad. Do not proceed to input testing until TP5↔TP2 reads open. |
| TP4 ≈ 5 V but inputs never assert | Field rail is fine — this is an **input front-end** issue, not a U37 issue (Rin 2.2 kΩ, the opto, the 10 kΩ Rpu to 3V3, or `FIELD_GND` return). See §22 input-stage guidance / §21.2.1 step 8. | — |

---

### TS.4 Pico won't enter BOOTSEL / won't flash

The firmware UF2 is pre-built at `firmware/rp2040/build/wsl_phase8b_rp2040.uf2`. Flashing is **USB BOOTSEL drag-drop** to the `RPI-RP2` mass-storage volume (firmware README §Flash; §22.6). This is independent of the board's J2 power — BOOTSEL flashing runs off the Pico's USB.

| Symptom | Likely cause | Fix |
|---|---|---|
| Plugging in USB does nothing — no `RPI-RP2` drive, no device | **Charge-only USB cable** (very common) | Swap to a known **data** Micro-USB cable. The SC0915 is **Micro-USB**, not USB-C — confirm the connector. Try a different USB port. |
| Pico powers (LED) but no `RPI-RP2` mount | **BOOTSEL not held during connect** | Hold the **BOOTSEL** button down *while* plugging USB in (or while tapping reset/power), then release. The volume mounts as `RPI-RP2`; drag-drop the `.uf2`, which auto-reboots into firmware. |
| `RPI-RP2` mounts, copy fails or "already running fw" | You're plugging in a Pico that **already booted firmware** | Re-do the BOOTSEL-held connect; a firmware-running Pico won't expose mass storage unless you force BOOTSEL. |
| USB inaccessible because A1 is soldered tight to the board | **Once soldered, the USB jack may be awkward to reach** | Fall back to **SWD**: `picotool load -x build/wsl_phase8b_rp2040.uf2`, or OpenOCD via the board's SWD test points (§22.6). |
| Drag-drop "succeeds" but no `boot` line over UART | Wrong file, or A1 not actually getting board power for the UART path | Confirm you flashed `wsl_phase8b_rp2040.uf2` (~40 KB). For UART you need A1 powered from the board (TS.1) and the J1 UART wired (see TS.5). |

> **Flash A1 before relying on TS.5.** Until the UF2 is on, A1 emits no `boot`/`hb` and `RP2040_OK` (GP2) stays low — which looks identical to a watchdog/rail fault. Flash first, then chase TP14.

---

### TS.5 `RP2040_OK` (TP14) never goes HIGH

`RP2040_OK` = Pico **GP2**, on **J1 pin 13**, **TP14** (§11.2, §12.2.1). It is **fail-safe-low by construction**: Hi-Z/LOW on boot, in reset, in BOOTSEL, or on any latched fault; it goes HIGH only after `BOOT_SETTLE_MS` (200 ms) **and** only while no fault is latched (firmware README §Safety model; §19.3.1). It is condition 3 of the rail, so a low TP14 holds the whole rail dead.

**Expected when healthy:** over the J1 UART (115200 8N1) a `boot` line, then `{"ev":"hb","ok":1,...}` at ~4 Hz after ~200 ms; **TP14 then reads HIGH** (≈ 3.3 V) (§21.2.1 step 3, firmware README §Bench bring-up step 1).

| Symptom | Likely cause | Fix |
|---|---|---|
| TP14 stuck low, no `boot`/`hb` on UART | **Firmware not flashed / A1 not booting** | Flash the UF2 (TS.4). Confirm A1 powered (TS.1, pin 39). |
| TP14 stuck low, `boot` seen but UART otherwise silent or one-way | **J1 UART mis-wired.** Net names are from the *Pi's* view and the crossover is already on the PCB — wire the ribbon **straight-through** (§11.2 UART gotcha). J1 pin 5 = `PI_UART_TX` → Pico GP1/RX; J1 pin 6 = `PI_UART_RX` ← Pico GP0/TX. | Confirm Pi TX→J1 pin 5, Pi RX→J1 pin 6, GND common. 115200 8N1. Do **not** re-cross TX/RX — the board already crossed them. |
| `boot`/`hb` arrive with `ok:1` but **TP14 still reads low** | **Cold/open joint on A1 GP2 (Pico pin 4)** or the GP2→J1 pin 13 trace | Reflow A1 pin 4. Confirm continuity A1 pin 4 → TP14 / J1 pin 13. |
| `hb` shows `ok:0`, or a `flt` line, and TP14 low | **A latched fault** — firmware is healthy but withholding permit. On a logic-only bench board the usual cause is the **motion max-run** fault if you sent `RUN <m>` without `STOP`, or a `chatter` fault from a noisy input | Read the `flt` `code`/`m` (e.g. `motion_timeout`, `chatter`). Issue **`CLEAR`** from the Pi (only from a safe/ready state) → expect `ack` + GP2 back HIGH (§22.5, firmware README step 4). |
| TP14 toggles low ~periodically, `boot` shows `wdt_reset:1` | **Firmware loop hanging** → RP2040 internal WDT (250 ms) resetting the chip (§19.3.2) | A `wdt_reset:1` boot after a forced hang is *expected* in the watchdog-drop test (§21.2.1 step? / firmware step 3). If it's unprompted, suspect a flaky A1 joint causing brownout/reset — reflow VSYS/GND pins. |
| TP14 low only because **you reset/halted A1 on purpose** | This is the **G3 RP2040-health drop test** working (§19.7) — reset/halt A1 → GP2 Hi-Z → rail drops | Not a fault. Release reset; GP2 returns HIGH after boot-settle. |

---

### TS.6 Rail (TP16) won't drop on watchdog/stop, or won't arm

`RELAY_ENABLE_RAIL` = **TP16**, the single most useful tap (§11.10, §21.2.2). On the bench, the rail is a hardware AND of six conditions — three on-board gate-stack transistors (ARM·RP2040_OK·watchdog) and two external J14 NC loops in series with the pass-FET source, with cam-stop folding into RP2040_OK (§19.2.5, §22.4.2). **There is no sixth transistor — don't look for one.** Probe order: is the rail supposed to be up? Then which condition is false?

**Bench setup reality:** with no J14 jumpers and an un-armed Pi, **TP16 = 0 V is correct.** To arm the rail for drop-testing you must (a) close both J14 loops with known jumpers (1–2 and 3–4) **on this logic-only board**, (b) flash + boot A1 so GP2 is HIGH, (c) kick the watchdog from the Pi, and (d) assert ARM. Then prove each condition independently drops it.

| Symptom | Likely cause | Fix |
|---|---|---|
| **Rail won't come up** (TP16 = 0 V) when you expect it armed | **J14 loops open** — #1 bench reason (§22.4.2 note). +5 V must traverse J14 1→2 (TB/SC) then 3→4 (Stop/CIS) to reach Q14 source | Jumper J14 1–2 and 3–4 (bench only). Probe **TP15 (`SAFE_STOP_RETURN`)** — it should read ≈ +5 V only when **both** loops are closed. If TP15 is dead, a loop is open. **Do not jumper J14 pin 1→4** to "make it work" — that bypasses both interlocks (§11.9). |
| Rail won't come up; TP15 ≈ 5 V (loops good) | One of the **gate-stack** conditions is false: **ARM** (Q15), **RP2040_OK** (Q16), or **watchdog** (Q13) — all default off via 100 kΩ pulldowns | Probe each: **TP13 (`ARM_PERMIT`)** HIGH? **TP14 (`RP2040_OK`)** HIGH (TS.5)? Watchdog OK — see below. All three transistors must conduct to pull `RAIL_GATE` low and turn the P-FET on. Any one low → rail dead. |
| Rail won't come up; ARM + RP2040_OK both HIGH, loops closed | **Watchdog not OK** — Pi isn't kicking, or the kick path is broken | Confirm the Pi is pulsing **`WDOG_KICK`** (J1 pin 7, **TP8**). Watch **TP11 (`NE555_OUT`)** toggling and **TP12 (`WDOG_OK_PULLDOWN`)** pulled to GND while kicks arrive. No kicks → NE555 times out → Q13 off → rail dead. Check the kick GPIO is wired/asserted on the Pi. |
| **Rail won't DROP when you stop kicking** (watchdog-drop test fails) | Watchdog timeout not expiring, or the NE555 stage stuck "OK" | Stop kicks; after the NE555 monostable timeout (a **bench-measured** number — do **not** assume ~11 s, §22.7 VERIFY) TP16 must fall. Watch TP11 (`NE555_OUT`) and TP12. If it won't drop: verify the timing network — `R_WDOG_TIMING` 100 kΩ + `C_WDOG_TIMING` 100 µF (= C11) at **TP9 (`WDOG_TIMING_NODE`)**, the `R_WDOG_TRIG_PULLUP` 10 kΩ holding **TP10 (`NE555_TRIG`)** high between kicks, and Q13. C11 is JLC-placed; the trig pull-up is the "Rev-A trigger pull-up fix." |
| **Rail won't drop on ARM de-assert** | Q15 (AND ARM) or its base network | De-assert ARM (J1 pin 8); TP13 → low and TP16 must drop. If not, check Q15 (MMBT3904) + its 10 kΩ base / 100 kΩ pulldown. |
| **Rail won't drop on RP2040 reset/halt** | Q16 (AND RP_OK) path | Reset/halt A1 → TP14 (GP2) → Hi-Z/LOW → TP16 must drop. If not, check Q16. This shares the path with cam-stop (condition 4). |
| **Rail won't drop when you open a J14 loop** | The opened loop isn't actually in series with the FET source, or a jumper is bridging it | Open J14 1–2 (TB/SC), confirm TP16 drops; restore; open J14 3–4 (Stop/CIS), confirm TP16 drops. TP15 should go open/low when either loop opens. If a loop opens and the rail stays up → you have an unintended bridge (e.g. an accidental 1→4 jumper) — find and remove it. |
| Cam-stop sub-test won't drop the rail | **Expected on the shipped firmware** — per-cam-edge cam-stop overrun is the v1.1 feature, ships **OFF** behind config flags; a stock build only provides RP2040 health + the 8 s motion max-run backstop (§19.3.4, §22.5, firmware README) | At the bench you can prove the GP2→rail path directly (reset/halt A1 → rail drops) and the **max-run** backstop (send `RUN S`, wait >8 s without `STOP S` → `flt:motion_timeout` → GP2 low → rail drops). True per-cam-edge drop is bench-provable only after cam-polarity capture + flashing v1.1 — not part of logic-only bench bring-up. |

> Every one of the five testable conditions (watchdog, ARM, RP2040, and the two J14 loops) **must** independently drop TP16. This is the heart of the bench gate; the cam-stop sub-test is deferred to v1.1 (§19.7).

---

### TS.7 A relay never clicks on its contact test

Each motion relay (S/T/SP/BE/M/M2 → K1-K6, drivers Q1-Q6; **M1/K7/J12 is DNP — leave empty**) energizes only when **both** (a) the Pi sets that relay's bit on MCP23017 **OUT-A `0x22`** (turning the per-relay MMBT3904 on to ground the coil low side) **AND** (b) the rail is live feeding the coil high side (§22.4, §19.2.5). Software alone can never fire a coil. So always answer "is the rail up?" before chasing a single channel.

**Expected:** with the rail armed (TS.6) and the Pi setting the OUT-A bit, the relay clicks; dropping the rail (TP16 → 0) drops the contact instantly.

| Symptom | Likely cause | Fix |
|---|---|---|
| **No** relay clicks on any channel | **Rail not armed** (TP16 = 0 V) — kills *all* coils at once, not one | Bring the rail up first (TS.6); confirm TP16 ≈ 5 V. A dead rail is the #1 reason "no relay does anything." |
| No clicks; rail up (TP16 ≈ 5 V) | **OUT-A `0x22` not enumerating** — no MCP, no command path | Confirm `0x22` answers on I²C (TS.2). If the OUT-A chip is missing, no relay (and no lamp) works. |
| One specific relay won't click; others do; rail up | **Wrong bit↔relay mapping in your test command**, or that channel's driver/coil | OUT-A bits: **S=(0,0), T=(0,1), SP=(0,2), BE=(0,3), M=(0,4), M2=(0,5)** (M2 is bit 5, **before** M1 bit 6 — §12.7, §11.7). Set the right bit. If the bit is right, probe the per-relay **MMBT3904 (Q1-Q6)**: base driven from OUT-A through 1 kΩ (`Rb`) with a 100 kΩ pulldown; collector sinks the K-coil low side. Reflow the driver; check the G5LE coil and the flyback (`Dfly`, 1N4148WS). |
| The **M1** channel won't fire | **By design — K7/Q7/J12 are DNP** and the FSM never drives M1 (§06.5.2, §11.7) | Expected. Leave J12/K7 empty. Don't populate without an explicit release decision. |
| Relay clicks but contact never closes the dummy load | Wrong pin pair on J6-J11, or a cold contact | Pin convention on every J_MOTION_*: **pin 1 = NO (`OUT_*_B`), pin 2 = COM (`OUT_*_A`)** (§11.7). Land the dummy load across COM↔NO. |
| Relay clicks but **won't drop** when you drop the rail | Possible **welded contact** (rare on a bench dry-contact test) | The rail removes coil drive; it cannot open a welded contact (§22.4.4) — but at logic-only bench with a small dummy load this is unlikely. Re-seat the dummy load; if a contact truly won't release, replace the relay (G5LE-14 **5 VDC** coil, LCSC C116963 — never a 9/12/24 V coil). |
| Coil buzzes / chatters instead of a clean click | **Sagging 5 V under coil load** — supply too small, or excessive SS14 drop | Confirm TP1 stays ≈ 4.6-4.8 V with the coil energized. Size the bench 5 V supply ≥ 1.5 A (3 A comfortable) per §06.5.2. |

---

### TS.8 Quick test-point reference (your meter taps)

All logic-domain values referenced to **TP2 (GND)**; field-domain to **TP5 (FIELD_GND)**.

| TP | Net | Healthy reading (logic-only bench) |
|---|---|---|
| TP1 | `VCC_5V` | ≈ 4.6-4.8 V (5 V in − SS14 Vf) |
| TP2 | `GND` | 0 V (logic reference) |
| TP3 | `VCC_3V3` | ≈ 3.3 V (**only with A1 fitted + powered**) |
| TP4 | `FIELD_WET_V` | ≈ +5 V to TP5 (**only with U37 fitted**) |
| TP5 | `FIELD_GND` | **open to TP2** (isolation proof) |
| TP6 / TP7 | `I2C_SDA` / `I2C_SCL` | ≈ 3.3 V idle-high each |
| TP8 | `WDOG_KICK` | kick pulses present while the Pi kicks |
| TP9 | `WDOG_TIMING_NODE` | NE555 RC ramp |
| TP10 | `NE555_TRIG` | high between kicks (10 kΩ pull-up) |
| TP11 | `NE555_OUT` | toggles with kicks |
| TP12 | `WDOG_OK_PULLDOWN` | pulled to GND while watchdog OK |
| TP13 | `ARM_PERMIT` | HIGH when armed, low otherwise |
| TP14 | `RP2040_OK` | HIGH (~3.3 V) once A1 booted + healthy; low on boot/reset/fault |
| TP15 | `SAFE_STOP_RETURN` | ≈ +5 V only when **both** J14 loops closed |
| TP16 | `RELAY_ENABLE_RAIL` | ≈ +5 V only when all six conditions true; **0 V otherwise (the safe default)** |

---

### Notes / things I could not fully confirm from the live files

- **(VERIFY: NE555 watchdog timeout in seconds.)** The RC is `R_WDOG_TIMING` 100 kΩ × `C_WDOG_TIMING` 100 µF (= C11), but the kick is wired into both the timing and trigger nodes (retrigger topology) and the spec states the drop behavior **qualitatively** without a number. The effective drop time is a **bench measurement** — **do not assume ~11 s** (§22.7, §19.2.4).
- **U37 TMA-0505S pinout — CONFIRMED** against the TRACO datasheet (Rev. 2026-04-15, p.4): **pin 1 +Vin / pin 2 −Vin / pin 4 −Vout / pin 6 +Vout**, matching board pads 1/2/4/6. The asymmetric SIP spacing means it can only seat one way (pin 1 → square pad), so a *flipped* U37 isn't physically possible. A dead TP4 with U37 fitted therefore points to a **cold joint on +Vin/−Vin or a field-side short**, not reversal.
- **(VERIFY: J1 ribbon pin-1 / keying.)** The J1 mating socket and shroud keying are flagged "candidate / confirm cable keying-orientation" in the working BOM. Confirm pin-1 alignment between board and Pi before crimping, or the entire J1 logic interface (power/I²C/UART/kick/ARM/RP2040_OK) lands shifted (§11.2 VERIFY).
- The per-channel **dry-contact vs 24 VAC-sense** input population (J3/J4/J5) is a cutover decision, not a bench-bring-up item; logic-only bench testing uses the default dry-contact wetting from U37 (§11.4-§11.6 VERIFY).

**Source files cited:** `docs/manual_src/22_troubleshooting.md` (§22.0/22.4-22.7), `21_bringup-cutover.md` (§21.2.1-21.2.2 sequence + TP map), `06_board-power.md` (§6.3 A1→3V3, §6.4 U37, §6.5 coil rail, §6.8-6.9 assembly/test-point values), `11_connector-pinouts.md` (§11.2 J1, §11.7 J_MOTION, §11.9 J14, §11.10 TP map), `12_channel-maps.md` (§12.2 GPIO, §12.3 I²C addresses, §12.7 OUT-A bit map, §12.10 watchdog timing), `19_safety-architecture.md` (§19.2.5 six-condition rail, §19.3 firmware layer, §19.7 G3 gate), `firmware/rp2040/README.md` (flash/BOOTSEL, bench bring-up, fail-safe-low RP_OK), `scripts/generate_kicad_netlist_revB.py` (net names), `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-hand-solder-bom.csv` (A1/U37/J-connector parts).

---
