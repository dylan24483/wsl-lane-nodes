# Rev-C Readiness & Reorder-Gate Checklist — Phase 8 Lane Controller Board

Status legend: `[ ]` open · `[~]` blocked on physical verify · `[x]` done.
**Do not reorder until every PRE-ORDER GATE is `[x]`.**

---

## 1. PRE-ORDER GATES (green before reorder)

### G1 — Relay footprint/pin remap fixed in the generator  `[x]`
- The rev-B defect: `scripts/generate_kicad_netlist_revB.py` `relay_output()` (lines ~276-283)
  put `RELAY_ENABLE_RAIL` on pad 1 and the MMBT3904 collector on pad 2, leaving the real
  second coil terminal floating. KEEP `FP_RELAY = "Relay_THT:Relay_SPDT_Omron-G5LE-1"`
  (line 55) — the footprint is mechanically correct. Fix is a **pin-number remap only**.
- Meter/continuity-confirmed map for the placed Omron **G5LE-14 5VDC / LCSC C116963**:
  - coil = pads **2 & 5** (~65 Ω)
  - COM = pad **1** (square pad)
  - NO = pad **3**
  - NC = pad **4**, deliberately unused
- Generator remap: `RELAY_ENABLE_RAIL` → pad 2; MMBT3904 collector + flyback anode → pad 5;
  flyback cathode → pad 2; `out_a`/J_MOTION pin 2 COM → pad 1; `out_b`/J_MOTION pin 1 NO
  → pad 3.

### G2 — Relay pinout independently verified against the EXACT placed part  `[x]`
- Board #1 measurement: pads 2↔5 read ~65 Ω.
- Dylan's J11 continuity check locked the contact side to the board copper: J11 pin 1
  to COM is **closed at rest**, so the J11 pin-1 net / relay pad 4 is NC. Therefore
  pad 3 is the NO contact, pad 1 remains COM, and pad 4 is NC/unused.
- Remaining obligation moves to G5: after regeneration, visually inspect the fab output so
  the copper actually follows this metered map.

### G3 — Rev-C netlist regenerated + ERC clean  `[x]`
- Re-ran `generate_kicad_netlist_revB.py` after the G2-confirmed remap. Result: netlist written,
  216 parts, **0 errors**. The same SKiDL environment warnings remain (`fp-lib-table`/missing tag);
  no new relay-map conflict appeared.
- Re-ran `controller_io.py __main__` self-test (asserts OUT_A_MAP/IN_A_MAP vs
  OUTPUT_PINS/SLOW_INPUT_PINS): PASS.

### G4 — DRC clean on the re-laid board  `[x]`
- Re-routed from the corrected pad-3 netlist and regenerated the fab package.
- KiCad DRC report: **0 DRC violations, 0 unconnected pads, 0 footprint errors**.
- Topology audit: **AUDIT RESULT: ALL PASS**.

### G5 — Manual Gerber relay-pad inspection  `[x]`
- Post-export routed-board pad audit for K1-K7: pad 2 carries
  `RELAY_ENABLE_RAIL`, pad 5 carries `COIL_LO_*` / transistor collector / flyback anode,
  pad 1 carries COM / `OUT_*_A` / J_MOTION pin 2, pad 3 carries NO / `OUT_*_B` /
  J_MOTION pin 1, and pad 4 is the unused NC contact. Confirms the remap actually moved
  copper, not just the symbol.
- Final paid-order habit still applies: compare JLC's Gerber preview against this map before paying.

---

## 2. INTERIM SOFTWARE / DOC FIXES (do before next bring-up; NOT PCB blockers)

### D1 — Fix `docs/manual_src/11_connector-pinouts.md` §11.6 J5 table  `[ ]`
The whole J5 MCP map is wrong vs `SLOW_INPUT_PINS` / `controller_io.py`. Per-row corrections (regenerate from the corrected script rather than hand-edit if possible):
- **PBZ** → IN-A (U1, 0x20), pin 6 / GPB5 / (port,bit)=(1,5).
- **PBC** → IN-A (0x20), pin 7 / GPB6 / (1,6).
- **FOUL** → IN-A (0x20), pin 8 / GPB7 / (1,7).
- **TENTH** → IN-B (0x21), pin 21 / GPA0 / (0,0).
- **MAN_T** → IN-B pin 22 / GPA1 / (0,1).
- **MAN_S** → IN-B pin 23 / GPA2 / (0,2).
- **MAN_SWS** → IN-B pin 24 / GPA3 / (0,3).
- **MAN_SWSR** → IN-B pin 25 / GPA4 / (0,4).
- **AUX1** → IN-B pin 26 / GPA5 / (0,5).
- **AUX2** → IN-B pin 27 / GPA6 / (0,6).
- **AUX3** → IN-B pin 28 / GPA7 / (0,7).
- **Intro/theory (lines 281-282):** drop the "all J5 on IN-B / not yet read" claim. Correct: PBZ/PBC/FOUL route to IN-A (0x20) GPB5-7 and **are read by the FSM today**; pins 4-11 route to IN-B (0x21) GPA0-7 (configured, not yet read). J5 spans both expanders.

### D2 — Fix relay part name in the manual  `[x]`
- §11.7 line 312 and the line-365 contact-rating note, and §11.11 summary line 484: state the
  **footprint symbol = G5LE-1**, **as-ordered part = G5LE-14 (C116963)**, and the
  meter-confirmed pad map: coil pads 2/5, COM pad 1, NO pad 3, NC pad 4 unused.

### D3 — Daemon one-board bench mode  `[ ]`
- File: `lane_node/controller_daemon.py`. Three localized edits (no touch to BoardController/run()/FSM):
  1. Add `WSL_LANES` env + `_parse_lanes()` / `_select_boards()` after `_shadow_enabled()` (line ~66). Lane filter applied to configs **before** construction so a single-board Pi never opens lane-22's `/dev/ttyAMA1`/bus-3.
  2. Add `_build_boards()` above `main()` — wrap each `BoardController(cfg)` in try/except; an open failure is logged loudly and **skipped** (never ticked → no NE555 kick → rail stays down = fail-safe). Returns the boards that came up clean.
  3. Rewrite `main()` to add `--lanes` (CLI beats `WSL_LANES`), select+build via the helpers, and `return 1` if zero boards come up.
- Usage on this bench: `python controller_daemon.py --lanes 21` (or `WSL_LANES=21 …`). No more sed-ing lane 22 out of `DEFAULT_BOARDS`.
- Confirm with Dylan: (a) zero-board exit-1 (systemd restart) vs stay-idle; (b) `--lanes` precedence over env. No new imports needed.

---

## 3. ON-HAND FOR BOARD ARRIVAL

**Pi is staged — no reprovisioning.** `lane-node-dev` (Pi 4): UART/ttyAMA0 on, I2C on, venv+deps, controller modules, RP2040 UF2 on box, `controller --selftest` 28/28. Just land the J1↔Pi ribbon → `i2cdetect -y 1` shows `0x20/0x21/0x22` → power rails → first-article test (§4).

### Mating connectors — ⚠️ ALL SIX ARE BOM-GAPS (missing from rev-B assy BOM; fold onto rev-C harness/assy BOM so they SHIP WITH THE BOARDS)
| Ref | Part | PN |
|---|---|---|
| J1 (J_PI) | 2×10 2.54mm F/F IDC ribbon socket | CNC Tech **3030-20-0102-00** — *CANDIDATE: verify pin-1/keying/strain-relief/gauge before committing qty* |
| J3 (J_FAST_IN) | Phoenix MC 1,5/10-ST-3,5 plug | Phoenix **1840447** |
| J4 (J_SLOW_IN_A) | Phoenix MC 1,5/14-ST-3,5 plug | Phoenix **1840489** |
| J5 (J_SLOW_IN_B) | Phoenix MC 1,5/12-ST-3,5 plug | Phoenix **1840463** |
| J13 (J_LAMP_LED) | Phoenix MC 1,5/6-ST-3,5 plug | Phoenix **1840405** |
| J14 (J_SAFETY) | Phoenix MC 1,5/4-ST-3,5 plug | Phoenix **1840382** |

J2 (5V in) and J6-J12 (motion out) are wire-direct Phoenix MKDS fixed blocks = **no plug**, ferrule only. **J12 (M1 ball-return) is DNP.** Phoenix PN is the authoritative key (CSV has comma-in-value `MC 1,5/…`). Sources: `docs/phase8_revB_harness_parts.md`, `docs/phase8_revB_bench_harness_parts.csv`, `docs/phase8_revB_production_harness_parts.csv`.

### Order priority
- **Bench-now (the one required buy):** F/F 20-pos 2.54mm socket-to-socket IDC ribbon (Assmann/3M/CNC Tech) to reach `i2cdetect`. Cut in half, strip conductors 2/3/4 (GND/SDA/SCL). Alt: CNC Tech 3030-20-0103-00 FC-20 socket + 1.27mm ribbon.
- Optional bench samples: 1 each of the 5 Phoenix MC-ST plugs for real-plug input/lamp/safety tests instead of jumpers.
- Production (×32): DIN 2×10 breakout + ribbon + the 5 plugs; Pi GPIO terminal HAT ×16 optional.

### Consumables / tools (mostly on hand)
- Micro-USB cable for RP2040 BOOTSEL/UF2 flashing — **keep the hand-shaved right-angle micro-B** (rev-B USB jams against J1; rev-C clears it).
- F-F Dupont jumpers (~10): land ribbon GND/SDA/SCL onto **Pi pins 6/3/5**. **NEVER J1 pin1/11.**
- Hookup wire to bench-close the J14 safety loop: jumper **pin1↔pin2** (TB/SC) and **pin3↔pin4** (Stop/CIS) so RELAY_ENABLE_RAIL can come up. **Do NOT jumper pin1→pin4.** Remove before cutover.
- Hookup wire to tap an input pin (J3/J4/J5) to FIELD_GND to fire its opto.
- Iron/solder/flux + ferrule kit (Phoenix plugs hand-terminated; J2/J6-J11 wire-direct).
- DMM — TP1 VCC_5V, TP3 VCC_3V3, TP4 FIELD_WET_V, TP5 FIELD_GND, TP14 RP2040_OK, TP15 SAFE_STOP_RETURN, TP16 RELAY_ENABLE_RAIL + relay coil/contact continuity.
- Bench PSU: regulated 5V into J2 (sized for 6 coils ~6×40mA + logic + LEDs + margin). **Do NOT also feed 5V into J1 pin1.**
- LEDs + limit resistors for the first-article click-test.

---

## 4. FIRST-ARTICLE QUALITY GATE (per assembled board, before trusting it)

> ⚠️ **On a rev-B board this gate WILL FAIL — the relay footprint mismatch means no relay energizes. That failure is EXPECTED and is the headline rev-C fix.** Everything upstream (MCP → driver transistor → RELAY_ENABLE_RAIL) is already validated. Only expect working relays on the G2-corrected rev-C spin.

- `[ ]` Rails good at TPs (VCC_5V, VCC_3V3, FIELD_WET_V, RP2040_OK=3.3V, RELAY_ENABLE_RAIL up with J14 loop closed).
- `[ ]` `i2cdetect -y 1` → 0x20 / 0x21 / 0x22.
- `[ ]` **Energize ONE J_MOTION relay (J6-J11)** via its driver → meter/listen for COM↔NO **make**, then de-energize → confirm **break**.
- `[ ]` One J13 status LED lights (anode→J13 pin1 VCC_5V, cathode→return pin 3/4/5/6).
- `[ ]` **Only after one relay proves make/break, repeat across all six.** Do not trust any assembled board until all 6 relays click make AND break.
