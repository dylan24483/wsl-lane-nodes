# Lane 21 Machine-Interface Harness — CUT-AND-CRIMP BUILD SHEET (Candidate C)

**Status: BUILDABLE — interlock decision FORMAL (Candidate C, Dylan, 2026-07-07 — `phase8_interlock_redesign.md` §7).**
Written 2026-07-07. One lane = one board = one harness. This sheet is for the **pilot lane 21** (SS chassis + Omega-Tek, C1 34-pin + C2A 50-pin AMP edge connectors). Lane 22 is a clone — see the ×2 column in §4 — but **re-verify every machine-side landing on 22's own connectors before crimping** (same chassis type, still per-lane proof).

**Reads-with (do not build without them open):**
- `phase8_machine_harness_spec_sectionF.md` — the governing spec (wire classes, bundles, separation, Path A/B).
- `phase8_interlock_redesign.md` §3-C + §4-RESULTS + §7 — why J_SAFE1-2 is a jumper, and the standing conditions.
- `phase8_trackB_controller_cutover_runbook.md` §3.3/§3.4 + Stage 5/6b + gate G3 — when each machine end lands, and the coil-drop proof.
- `phase8_revB_board1_prepower_test_checklist.md` — pre-power gate before the board ever sees this harness live.

**Mating-strategy decision (per Section F F.3): this sheet builds PATH B** — documented splice / piggyback taps on the **cable-side machine wires** behind C1/C2A. Path A (proper AMP mates) stays blocked on the housing-vs-contact P/N + contact-gender confirm (F.5 step 0 remainder); Section F names Path B the de-risked pilot fallback, and Path B additionally gives the cleanest rollback (pull our leads, re-plug the OEM brain — every tap goes inert). Back-probe pins are a **metering/verification aid only** in this build, never a permanent termination.

**Lead disposition legend:**
- **BUILD** — cut, label, ferrule, terminate board end into the plug NOW; land machine end per this sheet (Stage 5 for taps, per-row otherwise).
- **CUT+LABEL-ONLY** — cut to length, label both ends, ferrule + seat the board end in the plug, **heat-shrink-cap and coil the machine end. DO NOT LAND.** The row names the session that closes it.
- **NO-LEAD** — plug position left empty. Do not stuff a wire "for later."

**Non-negotiables (from Section F + the runbook):**
1. **Never land a sense lead on a common rail** — C2A **J / F / U** (gripper/control common, chassis return) and **N** (motion-cam common) ring to everything.
2. **Never cut or interrupt the safety loop** (Stop/CIS, DIELL interlock, SC/TB ladder) for a tap — bridge/tap in parallel only (Section F F.3 Path-B rule).
3. **The board never sources machine power.** Outputs are dry contacts in series with existing 24 VAC coil circuits. Never feed board 5 V into a C1/C2A cavity.
4. **Bundle separation** (Section F F.2): field-sense (22 AWG) ≥50 mm from safety/output runs (18 AWG); cross at 90°; separate jackets/looms from enclosure to machine.
5. All machine-side work **LOCKED OUT** (runbook §1 mode A) except the explicitly powered mapping/proof steps.

---

## 1. PER-CONNECTOR LEAD TABLES

Label format: print exactly the **Label text** column on heat-shrink at BOTH ends of the lead (board end may add the plug pin, e.g. `J4-8 · GS8 -> C2A-K`). Suggested colors assume discrete UL1007-class hookup wire; if building Bundle 1 as shielded multicore (Belden 1063A / Alpha 5160C — Section F's preferred cable), substitute the cable's core colors and record the actual core color beside each row on the printed sheet.

Lengths: enclosure→C1/C2A run measured ~0.6–1.0 m → **cut sense/output leads at 1.2 m** (service slack + drip loop, per F.2). DIELL leads 1.5 m. Foul 1.0 m. Mask-LED run is **not in Section F — measure on site before cutting** (estimate 2–3 m; treat as an estimate, not a measurement).

### J2 — 5 V logic in (MKDS wire-direct, 3-pos: pin1 = 5 V, pins 2–3 = GND — per the rev netlist `J_PWR`)

| Pin | Signal | AWG | Color | Label text | Termination (far end) | Disposition |
|---|---|---|---|---|---|---|
| J2-1 | +5 V in | 18 | red | `J2-1 +5V <- PSU` | enclosure 5 V PSU + terminal | **BUILD** (0.5 m, enclosure-internal) |
| J2-2 | GND | 18 | black | `J2-2 GND <- PSU` | enclosure PSU − terminal | **BUILD** (0.5 m, enclosure-internal) |
| J2-3 | GND | 18 | black | `J2-3 GND <- PSU` | enclosure PSU − terminal | **BUILD** (0.5 m, enclosure-internal) |

> PSU sized ≥1 A (6 × ~77 mA relay coils + logic — readiness checklist §3). Never also feed 5 V into J1 pin 1.

### J3 — J_FAST_IN (Phoenix MC 1,5/10-ST-3,5 plug, PN **1840447**) — 22 AWG throughout

| Pin | Signal | Color | Label text | Machine-side termination | Disposition |
|---|---|---|---|---|---|
| J3-1 | SA (sweep cam) | orange | `SA -> POWERED MAP ONLY - DO NOT LAND` | none yet — cavity unknown (cold reads invalid: ~21 Ω relay-coil sneak paths, C2A-N is the cam common) | **CUT+LABEL-ONLY** — closes at the **powered cam-cavity mapping at cutover** (runbook §3.2) |
| J3-2 | SB (guard cam) | orange | `SB -> POWERED MAP ONLY - DO NOT LAND` | none yet | **CUT+LABEL-ONLY** — powered cutover mapping |
| J3-3 | SC (interlock cam echo) | orange | `SC -> C2A-U - DO NOT LAND (echo redesign + F.5 step 4)` | **known cavity (C2A-U via the N.O. pink wire) but do NOT land**: U doubles as a live-ladder/common node; front-end class unresolved (Section F F.4 — powered meter, F.5 step 4) and the single-node software-echo redesign (review findings #4/#12) has not consumed the §4.3 window capture | **CUT+LABEL-ONLY** — closes at the powered session (F.5 step 4 + §4.3 capture) + the echo-redesign workstream |
| J3-4 | TA1 (table cam) | orange | `TA1 -> POWERED MAP ONLY - DO NOT LAND` | none yet | **CUT+LABEL-ONLY** — powered cutover mapping |
| J3-5 | TA2 (table cam) | orange | `TA2 -> POWERED MAP ONLY - DO NOT LAND` | none yet | **CUT+LABEL-ONLY** — powered cutover mapping |
| J3-6 | TB | — | — | **nothing to land** — TB has NO standalone cavity on this chassis (both TB wires tie into the SC/U node; measured 2026-06-27) | **NO-LEAD** |
| J3-7 | DIELL-L signal | blue | `DIELL-L SIG (DIELL harness tap)` | IDC tap on the DIELL **L-beam signal wire** on the DIELL harness (NOT C2A). ~16 V rest / 0.7 V beam-broken, NPN active-low. **NEVER tap the sensor's 24 V supply wire.** Twist with J3-9. | **BUILD** (1.5 m) |
| J3-8 | DIELL-R signal | yellow | `DIELL-R SIG (DIELL harness tap)` | IDC tap on the DIELL **R-beam signal wire**; same rules; twist with J3-10 | **BUILD** (1.5 m) |
| J3-9 | FIELD_GND (DIELL-L return) | black | `J3-9 FGND (DIELL GND tap)` | IDC tap on the DIELL harness GND/return wire (signal + GND only per F.2) | **BUILD** (1.5 m, twisted pair w/ J3-7) |
| J3-10 | FIELD_GND (DIELL-R return) | black | `J3-10 FGND (DIELL GND tap)` | IDC tap on the DIELL harness GND/return wire | **BUILD** (1.5 m, twisted pair w/ J3-8) |

> The four motion-cam leads (J3-1/2/4/5) + SC (J3-3) get their board ends seated in the 1840447 plug now so the powered mapping session only has to land machine ends. Cap + coil + tag each machine end.
> **Front-end caveat:** if the powered class check (F.5 step 4) reads sustained 24 VAC at any cam cavity, that channel needs the board's 24 VAC-rectified front-end option populated **before** its lead lands — the lead itself (22 AWG / 300 V insulation) is already rated for it.

### J4 — J_SLOW_IN_A (Phoenix MC 1,5/14-ST-3,5 plug, PN **1840489**) — 22 AWG throughout

All gripper cavities ✓ measured (2026-06-27 + GS8 2026-07-07). Gripper return = **machine chassis** (no TAC strip on this cabinet). Polarity locked: gripped (pin present) = CLOSED to chassis.

| Pin | Signal | Color | Label text | Machine-side termination | Disposition |
|---|---|---|---|---|---|
| J4-1 | GS1 | white | `GS1 -> C2A-C` | IDC tap on the cable-side wire entering C2A cavity **C** (verify: beep tap point → cavity contact face, brain unplugged) | **BUILD** |
| J4-2 | GS2 | white | `GS2 -> C2A-H` | IDC tap, C2A cavity **H** wire | **BUILD** |
| J4-3 | GS3 | white | `GS3 -> C2A-M` | IDC tap, C2A cavity **M** wire | **BUILD** |
| J4-4 | GS4 | white | `GS4 -> C2A-S` | IDC tap, C2A cavity **S** wire | **BUILD** |
| J4-5 | GS5 | white | `GS5 -> C2A-W` | IDC tap, C2A cavity **W** wire | **BUILD** |
| J4-6 | GS6 | white | `GS6 -> C2A-a` | IDC tap, C2A cavity **a** (lower-case) wire | **BUILD** |
| J4-7 | GS7 | white | `GS7 -> C2A-e` | IDC tap, C2A cavity **e** (lower-case) wire | **BUILD** |
| J4-8 | GS8 | white | `GS8 -> C2A-K` | IDC tap, C2A cavity **K** wire (✓ measured 2026-07-07; the old 48H prediction was WRONG — H is GS2) | **BUILD** — then the **G2-GS8 drop-one-pin proof at cutover is mandatory** (unlanded GS8 reads "not standing" → pin-8-only leave = false STRIKE) |
| J4-9 | GS9 | white | `GS9 -> C2A-r` | IDC tap, C2A cavity **r** (lower-case) wire | **BUILD** |
| J4-10 | GS10 | white | `GS10 -> C2A-v` | IDC tap, C2A cavity **v** (lower-case) wire | **BUILD** |
| J4-11 | GP | orange | `GP -> C2A-?? DO NOT LAND (predicted 412DD, unmeasured)` | none yet — prediction only, not resolved by the 2026-06/07 metering | **CUT+LABEL-ONLY** — closes at the next cold probe session / cutover Stage 2 (runbook §3, B.5) |
| J4-12 | OS ⊕ | — | — | cavity UNKNOWN, channel unused by the FSM | **NO-LEAD** (spare) |
| J4-13 | BS | white | `BS -> C2A-CC` | IDC tap, C2A cavity **CC** wire (bin switch) | **BUILD** |
| J4-14 | FIELD_GND | green | `J4-14 FGND -> CHASSIS` | **ring lug on a paint-free chassis stud** + star washer (the gripper return IS the chassis — measured; do NOT go looking for a TAC strip) | **BUILD** |

> **GS-map rule (gate G2-GSMAP):** the GS-label→J4-pin binding is FIXED in `controller_io.py` (`IN_A_MAP`; drift-guard asserted). Lane-specific assignment lives **in this harness crimp order** — J4 lead *N* → measured cavity of gripper *N*, exactly as tabled above. Never "fix" a swap in software; re-crimp the lead. Verify by the per-gripper drop-one-pin test at cutover (runbook §3.1).

### J5 — J_SLOW_IN_B (Phoenix MC 1,5/12-ST-3,5 plug, PN **1840463**) — 22 AWG throughout

| Pin | Signal | Color | Label text | Machine-side termination | Disposition |
|---|---|---|---|---|---|
| J5-1 | PBZ | white | `PBZ -> C2A-EE` | IDC tap, C2A cavity **EE** wire (zero/manual-intervention pushbutton; shorts to common U when pressed — ✓ measured) | **BUILD** |
| J5-2 | PBC ⊕ | orange | `PBC -> C2A-?? DO NOT LAND (unmeasured)` | none yet — "EE area" is approximate only. It's a dry momentary → cold-probeable: press + beep candidate cavity → U | **CUT+LABEL-ONLY** — closes at the next cold probe / cutover Stage 2 (B.5) |
| J5-3 | FOUL | orange | `FOUL -> ?? DO NOT LAND (F.5 step 6 - lamp wire unmetered)` | none yet — Radaray harness tap is marginal (~5 V, 0.3 V swing); preferred lamp-wire tap unmetered, possibly AC (front-end class open) | **CUT+LABEL-ONLY** (1.0 m) — closes at F.5 step 6 (meter the foul lamp wire, powered session) |
| J5-4 | TENTH ⊕ | — | — | cavity UNKNOWN | **NO-LEAD** (spare) |
| J5-5 | MAN_T ⊕ | — | — | descriptive code only ("T-2"), unmeasured | **NO-LEAD** (spare) |
| J5-6 | MAN_S ⊕ | — | — | descriptive only | **NO-LEAD** (spare) |
| J5-7 | MAN_SWS ⊕ | — | — | descriptive only | **NO-LEAD** (spare) |
| J5-8 | MAN_SWSR ⊕ | — | — | UNKNOWN | **NO-LEAD** (spare) |
| J5-9/10/11 | AUX1–3 | — | — | unallocated | **NO-LEAD** (spare) |
| J5-12 | FIELD_GND | green | `J5-12 FGND -> CHASSIS` | ring lug, same chassis stud as J4-14 (second lug or stacked w/ star washers) | **BUILD** |

### J6–J11 — J_MOTION outputs (MKDS 1,5/2-5,08 wire-direct; **pin 1 = NO, pin 2 = COM** on every block) — 18 AWG throughout, Bundle 3

Every output = an isolated dry contact inserted **in series with an existing 24 VAC coil circuit**. Cavities below are bench/at-machine measured continuity groups; the exact pair to bridge inside each group is the **runbook §3.3 land-check** at cutover Stage 2. Build all 12 leads now (Section F: "the output side can be cabled now"); machine ends land at Stage 5. Full insertion method + candidate-C caveat: **§3 of this sheet.**

| Conn | Signal | Pin/lead | Color | Label text | Machine-side termination (at Stage 5, after §3.3 confirm) | Disposition |
|---|---|---|---|---|---|---|
| J6 | S — sweep | 1 (NO) | red | `S NO -> C1{C,D,N,T} feed side` | tap on the feed-side wire of the confirmed pair within C1 {C,D,N,T} | **BUILD** — land per §3, **candidate-C caveat applies** |
| J6 | | 2 (COM) | black | `S COM -> C1{C,D,N,T} coil side` | tap on the coil-side wire (beeps to the S-contactor coil A1/A2, ~5 Ω Siemens) | **BUILD** |
| J7 | T — table | 1 (NO) | red | `T NO -> C1{A,K,H,E,+L} feed side` | tap on the feed-side wire of the confirmed pair within C1 {A,K,H,E,+L through-coil} | **BUILD** — **candidate-C caveat applies** |
| J7 | | 2 (COM) | black | `T COM -> C1{A,K,H,E,+L} coil side` | tap on the coil-side wire (beeps to the T-contactor coil, 24 VAC — measured 2026-07-07) | **BUILD** |
| J8 | SP — spot | 1 (NO) | red | `SP NO -> C2A (spot sol feed)` | tap per §3.3 confirm (C2A direct, 0 Ω group; 100 Ω solenoid coil) | **BUILD** |
| J8 | | 2 (COM) | black | `SP COM -> C2A (spot sol coil)` | tap per §3.3 confirm | **BUILD** |
| J9 | BE ⊕ — back-end | 1 (NO) | red | `BE NO -> C1{KK,C,L} feed side` | tap per §3.3 confirm — circuit straddles C1 (KK, C, L) + coil tap FF@66 Ω + C2A | **BUILD** |
| J9 | | 2 (COM) | black | `BE COM -> BE coil side (FF@66R)` | tap per §3.3 confirm | **BUILD** |
| J10 | M ⊕ — master | 1 (NO) | red | `M NO -> C2A{FF,U,B} feed side` | tap per §3.3 confirm (80 Ω 82-70-5515 relay) | **BUILD** |
| J10 | | 2 (COM) | black | `M COM -> C2A{FF,U,B} coil side` | tap per §3.3 confirm | **BUILD** |
| J11 | M2 ⊕ — sweep-reverse | 1 (NO) | red | `M2 NO -> C2A (swp-rev feed)` | tap per §3.3 confirm — **preserve the Expander interlock / shorting-plug function, not just the cavity** | **BUILD** |
| J11 | | 2 (COM) | black | `M2 COM -> C2A (swp-rev coil)` | tap per §3.3 confirm | **BUILD** |
| J12 | M1 — ball-return | — | — | — | **DNP on the board, never metered** — confirm existence per runbook §3.6 before any future populate | **NO-LEAD** |

### J13 — J_LAMP_LED (Phoenix MC 1,5/6-ST-3,5 plug, PN **1840405**) — 22 AWG; our LEDs in the mask housings (machine 15 VDC mask supply abandoned — leave OEM mask wiring intact, lift don't cut)

Pin order per the rev netlist (`lamp_order`): pin1 = VCC_5V, pin2 = GND, pins 3–6 = L_FIRST / L_SECOND / L_STRIKE / L_FOUL returns (LED anodes → pin1 rail; cathodes → their return pin; drive/limit is on-board).

| Pin | Signal | Color | Label text | Machine-side termination | Disposition |
|---|---|---|---|---|---|
| J13-1 | VCC_5V (LED anode rail) | red | `J13-1 5V -> MASK LED ANODES` | daisy-chain to all 4 LED anodes in the mask housings (Stage 3). **LED-end termination method: solder to the LED pigtail, adhesive heat-shrink over the joint** (no crimps in the mask housing — vibration) | **BUILD** board end now; terminate LED end at cutover Stage 3. **Length: measure the mask run on site (est. 2–3 m — estimate, confirm)** |
| J13-2 | GND | black | `J13-2 GND (reserve)` | none — logic GND; do **NOT** tie to chassis or FIELD_GND at the mask | **CUT+LABEL-ONLY** (length = the on-site mask-run measurement, same as J13-1/3–6; reserve — land only if the LED install needs a logic return) |
| J13-3 | L_FIRST return | white | `L_FIRST <- mask LED cathode` | 1st-ball LED cathode | **BUILD** (board end now, LED end Stage 3) |
| J13-4 | L_SECOND return | white | `L_SECOND <- mask LED cathode` | 2nd-ball LED cathode | **BUILD** |
| J13-5 | L_STRIKE return | white | `L_STRIKE <- mask LED cathode` | strike LED cathode | **BUILD** |
| J13-6 | L_FOUL return | white | `L_FOUL <- mask LED cathode` | foul LED cathode | **BUILD** |

> Before crimping the LED ends, re-check pin→lamp order against the board silk / `generate_kicad_netlist_revB.py` `lamp_order` — a swap is a re-label + re-land, cheap now, confusing at soak.

### J14 — J_SAFETY (Phoenix MC 1,5/4-ST-3,5 plug, PN **1840382**) — 18 AWG (Bundle 2 class)

Loop topology on-board: VCC5 → **pins 1–2 (TBSC loop)** → **pins 3–4 (Stop/CIS loop)** → PMOS → RELAY_ENABLE_RAIL. Both loops must be closed for the rail to arm.

| Pin(s) | Signal | AWG | Color | Label text | Termination | Disposition |
|---|---|---|---|---|---|---|
| J14-1 ↔ J14-2 | TBSC loop | 18 | yellow | see §2 — verbatim label | **the Candidate-C engineered jumper — bridge inside the plug, no machine side.** Full construction in **§2**. | **BUILD (as the §2 jumper)** |
| J14-3 | Stop/CIS loop (out) | 18 | yellow | `J14-3 STOP/CIS - OPEN - DO NOT LAND OR JUMPER` | none — landing **OPEN**, see §2.3 | **CUT+LABEL-ONLY** (1.2 m) |
| J14-4 | Stop/CIS loop (return) | 18 | yellow | `J14-4 STOP/CIS - OPEN - DO NOT LAND OR JUMPER` | none — landing **OPEN**, see §2.3 | **CUT+LABEL-ONLY** (1.2 m) |

---

## 2. THE J_SAFE JUMPER PLUG (Candidate C — engineered part)

### 2.1 Construction

1. Take **one Phoenix MC 1,5/4-ST-3,5 plug (PN 1840382)** — this IS the lane's J14 harness plug (positions 3–4 carry the Stop/CIS cut+label leads from the table above; the jumper lives on positions 1–2 of the same plug).
2. Cut **~120 mm of 18 AWG stranded, yellow** (600 V insulation — Bundle 2 spec). Form a U.
3. Strip both ends 8 mm, fit **0.75/1.0 mm² ferrules**, crimp.
4. Terminate one end in **position 1**, the other in **position 2**. Torque ~0.5 Nm (small flat-blade), tug-test both ends.
5. Slide a printed heat-shrink flag onto the U **before** the second crimp, with this label text, verbatim:

   > **`TBSC JUMPER - ENGINEERED PART (Candidate C, DECIDED 2026-07-07). TB/SC collision protection is DELEGATED to the OEM 24VAC ladder (SC+TB parallel closed-when-SAFE contacts in the S/T coil circuits - proven at machine 2026-07-07). NOT a bypass: the per-lane Stage-6b/G3 coil-drop proof is REQUIRED before live motion, every cutover. See docs/phase8_interlock_redesign.md §7.`**

   If the printer can't fit it, the flag carries the first sentence + `see phase8_interlock_redesign.md §7`, and the full text goes on the wire-map card taped inside the enclosure door (mandatory either way).
6. Label the plug body: **`J14 J_SAFETY · 1-2 = TBSC jumper (engineered) · 3-4 = Stop/CIS (OPEN - never jumper)`**.

### 2.2 What this jumper is — and is not

- It closes the board's TBSC rail condition **permanently**, because as measured (2026-06-27) **no isolatable dry NC pair exists on this chassis** — SC is reachable only on its N.O. wire at a live-ladder/common node, TB never isolates. The rail's TB/SC condition is **formally delegated to the OEM ladder**: SC+TB are a **parallel closed-when-SAFE pair**; danger = **both cam levers BACK (buttons released)** = coil circuit dies even on a manual command — proven for both S and T at the machine 2026-07-07 (`phase8_interlock_redesign.md` §4-RESULTS).
- The delegation is only real **if the board's S/T contacts land in series with those same coil circuits** (§3-C insertion-point caveat). That is why the **Stage-6b/G3 coil-drop proof is a hard gate on every lane, every cutover**: with the board commanding S (then T), body clear, force both levers BACK → **the coil must die even with the board contact closed**. A jumpered J14-1/2 with a failed or skipped coil-drop proof = **G3 automatic FAIL → abort + rollback**.
- **Any other J_SAFE jumper remains FORBIDDEN** (runbook Stage 6b): this documented part on 1-2 is the sole exception. Never bridge 1→4 (skips the Stop/CIS condition); never jumper 3-4 at the machine.

### 2.3 J_SAFE3-4 (Stop/CIS loop) — status per Section F: **OPEN**

Section F carries **no J14/Stop-CIS landing row** — its Bundle-2 rule is only that the Stop/CIS chain "must stay hardware, in-series, untouched by the Pi," and runbook §3.5 says the board's sense *ties into* that chain without naming a tap point. No dry pair for the sense loop has been measured. So the landing is **OPEN**, and this sheet builds only the two cut+label leads.

- **What closes it:** the next at-machine **powered characterization session** (the same visit as the §4.3 window-angle capture / F.5 step 4 front-end classing) or cutover **Stage 2 (§3.5 confirm)** — identify a dry, closed-when-safe tap (e.g., an auxiliary/spare contact in the Stop/CIS→master-breaker path) that can feed J14-3/4 without interrupting the chain. Be alert that it may present the **same no-dry-pair problem as TBSC** — if so, it needs its own mini-decision before cutover; record in `phase8_interlock_redesign.md`-style form.
- **Hard consequence:** the rail **cannot arm** until J14-3/4 closes — that is deliberate. The bench jumper on 3-4 (readiness checklist §3) is a **bench-only tool: remove before cutover.** G3 also requires the Stop/CIS-open → rail-drop test, which needs the real landing.

---

## 3. OUTPUT-SIDE SERIES INSERTION (per motion channel) — cutover Stage 5, per runbook §3.3

### 3.1 The method (all six channels)

With the OEM brain **unplugged (Stage 4), the brain's own switching element IS the series break** in each coil circuit — the circuit dead-ends at two C1/C2A cavities the brain used to bridge. The board contact re-completes that path:

1. **Confirm the group (Stage 2, §3.3, LOCKED OUT):** beep-verify the measured cavity group for the channel (table in §1). Then identify the two sides of the brain's gap: the **coil side** beeps at coil resistance to the load (S: Siemens contactor A1/A2 ~5 Ω · T: heavy-lug contactor, 24 VAC coil · SP: 100 Ω · BE: 66 Ω @ FF · M/M2: 80 Ω). The **feed side** runs toward the 24 VAC transformer/ladder — cold reads on that side can show ohms through relay-coil sneak paths, so if feed-side identity is ambiguous cold, mark it provisional and let the Stage-7 first-motion test (single deliberate command, hand on the breaker) be the arbiter.
2. **Tap, don't cut:** IDC tap (rated for the machine wire gauge and ≥ coil inrush — S is a 5 Ω coil, real inrush; use 18–14 AWG-class taps, not telecom Scotchloks, on S/T) on the **cable-side wire** of each of the two cavities: **NO lead (pin 1) → feed-side wire · COM lead (pin 2) → coil-side wire.** (The contact is non-polar; NO→feed is convention for the wire-map card.) If a tap can't make a sound joint on the machine wire, fall back to cut-and-Wago 221 — and pre-stage the labeled 18 AWG **rollback bridge jumper** for that channel (rollback = pull board leads from the Wagos, insert the bridge, re-plug the brain).
3. **Tug-test + meter each tap** (<0.5 Ω tap-to-wire), photograph, log on the wire-map card.
4. **Rollback property (why taps, not cuts):** with taps, pulling the board leads (or just unscrewing the MKDS plugs... they're wire-direct — pull the leads from the taps) and re-plugging the OEM brain restores the machine **exactly** — the taps go inert. ⚠️ Never re-plug the brain while the board leads are still landed AND the rail can arm — two controllers in parallel is forbidden; rollback order is: rail down/board depowered → lift board leads → re-plug brain.

### 3.2 ⚠️ THE CANDIDATE-C CAVEAT — S (J6) and T (J7) specifically

The whole Candidate-C decision rests on the OEM SC/TB **parallel closed-when-SAFE contacts staying electrically in series with the coil path the board completes.** Therefore, on S and T:

- **Bridge ONLY the brain's gap.** Never tap "conveniently" from the transformer/feed rail upstream of the ladder — if the board's feed-side tap lands upstream of the SC/TB contacts, the board bypasses the machine's own collision protection and Candidate C is void **for that lane**.
- The §4-RESULTS proof (2026-07-07) used the **rear-panel manual switches** — it proves the ladder blocks the *manual* path. Whether it blocks the **board's** path depends entirely on where these two taps land. That is only provable live:
- **Stage-6b/G3 coil-drop gate (hard, per lane, every cutover):** body clear, board commands **S** → hold both SC/TB levers **BACK** (the danger state) → **S-contactor coil must read 0 VAC even with the board contact closed.** Repeat for **T**. Coil energizes in the danger state = the insertion bypassed the interlock → **lift the feed-side tap immediately, re-select the tap point, re-prove. No live motion until both channels pass.** (Runbook Stage 6b / gate G3; `phase8_interlock_redesign.md` §7 standing conditions.)

### 3.3 Channel notes

- **S (J6):** group C1 {C, D, N, T}. Highest inrush (5 Ω coil) — best joints here; snubber/MOV across the board contact stays DNP until coil current is characterized (F.5 step 7 / F.6 #10), so avoid rapid-cycling S during tests.
- **T (J7):** group C1 {A, K, H, E, +L through-coil}. The L cavity reads *through* the coil — don't pick L as the coil-side tap; tap the direct coil-side wire (beep to A1/A2 confirms).
- **SP (J8):** C2A direct (0 Ω group), 100 Ω solenoid — momentary duty only.
- **BE (J9):** straddles C1 (KK, C, L) + coil tap FF@66 Ω + C2A — the §3.3 confirm must sort which side of the straddle is feed vs coil before tapping. Continuous-duty load.
- **M (J10):** C2A {FF, U, B}. **U is a common rail** — expect it to be the common/return side, and never treat a U tap as the switched feed without beeping it out.
- **M2 (J11):** C2A direct — **preserve the Expander-card interlock / shorting-plug function**: confirm the sweep-reverse path still behaves with the Expander removed/bypassed per the §3.3 land-check before trusting M2.
- **M1 (J12):** DNP, no lead, not harnessed — existence check per §3.6 is a future item.

---

## 4. MATERIALS BOM — one lane (+ ×2 column for 21+22)

Plugs per `phase8_revC_readiness_checklist.md` §3 (the BOM-gap list — these ship separately from the boards).

| Item | Spec / PN | Qty ×1 lane | Qty ×2 (21+22) |
|---|---|---|---|
| Plug, J3 J_FAST_IN | Phoenix MC 1,5/10-ST-3,5 · **1840447** | 1 | 2 |
| Plug, J4 J_SLOW_IN_A | Phoenix MC 1,5/14-ST-3,5 · **1840489** | 1 | 2 |
| Plug, J5 J_SLOW_IN_B | Phoenix MC 1,5/12-ST-3,5 · **1840463** | 1 | 2 |
| Plug, J13 J_LAMP_LED | Phoenix MC 1,5/6-ST-3,5 · **1840405** | 1 | 2 |
| Plug, J14 J_SAFETY (+ §2 jumper) | Phoenix MC 1,5/4-ST-3,5 · **1840382** | 1 (+1 spare) | 2 (+2 spare) |
| Wire 22 AWG, white (sense, build-now) | UL1007-class stranded, 300 V | ~25 m | ~50 m |
| Wire 22 AWG, orange (CUT+LABEL-ONLY leads) | same — orange = "do not land" convention | ~12 m | ~24 m |
| Wire 22 AWG, green (FIELD_GND) | same | ~3 m | ~6 m |
| Wire 22 AWG, black (DIELL GND, J13 GND) | same | ~6 m | ~12 m |
| Wire 22 AWG, blue + yellow (DIELL L/R sig) | same, 1.5 m each + spare | ~4 m | ~8 m |
| Wire 22 AWG, red (J13 LED 5 V rail) | same — mask-run length site-measured | ~4 m (est) | ~8 m |
| *(alternative to the six rows above)* Bundle-1 multicore | **Belden 1063A** (12×22 AWG, foil+drain) or Alpha 5160C — Section F preferred; J4's 12 build-now leads (GS1–10 + BS + FGND) fit one run exactly | 1 × ~1.5 m run (+ discrete for J3/J5/J13) | 2 runs |
| Wire 18 AWG, red (output NO leads) | stranded, 600 V | ~8 m | ~16 m |
| Wire 18 AWG, black (output COM leads) | same | ~8 m | ~16 m |
| Wire 18 AWG, yellow (J14 jumper + Stop/CIS + rollback bridges) | same | ~5 m | ~10 m |
| *(alternative)* Bundle-3 multipair | **Belden 1419A** (6-pair 18 AWG) per F.2 | 1 × 1.2 m run | 2 |
| Ferrules 0.34 mm² (22 AWG) | insulated, for MC 1,5 plugs | ~45 (buy 100-pk) | ~90 (1 pk) |
| Ferrules 0.75–1.0 mm² (18 AWG) | insulated, for MKDS + J14 | **~31** (J2 ×3 + J6–J11 board ends ×12 + J14 ×4 + rollback bridges 6×2) — buy 100-pk | ~62 (1 pk) |
| IDC taps, small-gauge (sense) | 3M Scotchlok IDC class, sized to the machine sense-wire gauge (verify on site) | 16 used → buy 30 | 60 |
| IDC taps, 18–14 AWG class (outputs) | T-tap / Scotchlok rated ≥10 A — S/T coil inrush | 12 used → buy 20 | 40 |
| Wago 221-413 (3-port lever nuts) | fallback splice + output cut-fallback | 12 | 24 |
| Rollback bridge jumpers | 18 AWG yellow, 0.2 m, ferruled both ends, labeled `ROLLBACK BRIDGE <chan>` — pre-make one per output channel | 6 | 12 |
| Ring lugs + star washers | sized to the chosen chassis stud (measure on site) | 2 lugs + washers | 4 |
| Heat-shrink label stock | printable 3:1, white — **~100 labels/lane** (≈50 leads × 2 ends + plug bodies) | **2 m** | **4 m** |
| Heat-shrink end caps | for CUT+LABEL-ONLY machine ends (J3-1..5, J4-11, J5-2, J5-3, J13-2, J14-3, J14-4 = 11) | **~12** | ~24 |
| Split loom / jacket | ~10 mm, keep Bundle 1 and Bundle 3 in **separate** looms (≥50 mm apart) | ~4 m | ~8 m |
| Wire-map card | printed §1 tables + §2.1 full label text, taped inside enclosure door | 1 | 2 |
| Back-probe pin set | metering aid ONLY (never permanent termination in this Path-B build) | 1 set | 1 set |
| Tools | ferrule crimper 0.25–2.5 mm², small flat-blade (~0.5 Nm), strippers 22/18 AWG, pliers for IDC taps, DMM, label printer | on hand | — |

**Path-A note:** no AMP mating housings/contacts in this BOM — Path A stays blocked on the housing-vs-contact P/N + gender confirm (Section F F.3 / F.5 step 0). If Path A unblocks before fleet rollout, the machine-side taps get superseded by proper 34/50-pos mates; this pilot ships on taps.

---

## 5. BUILD ORDER + QA

### 5.1 Bench build (at home, before any machine visit)

1. Print the §1 tables + §2.1 label text = the **wire-map card**. Print all heat-shrink labels first — **label before you crimp.**
2. Cut all leads to length per §1 — **EXCEPT the J13 mask leads (J13-1 through J13-6): their run must be MEASURED ON SITE first (§1 note), so defer those cuts to the first machine visit.** Slide labels on. Twist the DIELL pairs (J3-7+9, J3-8+10).
3. Ferrule + terminate every **board end** into its plug (J3/J4/J5/J13/J14) or leave ferruled-loose for the wire-direct blocks (J2, J6–J11 — those screw down at enclosure install). Plug orientation: pin 1 per the Phoenix numbering molded on the plug — double-check against the board silk before seating.
4. Build the **§2 jumper plug** (J14-1↔2) exactly per §2.1.
5. **CUT+LABEL-ONLY leads:** heat-shrink-cap the machine end, coil, tape, tag. Orange insulation = never landed without a named session closing it.
6. **Bench continuity pass (before the machine visit):** for every lead, beep plug-pin ↔ far-end conductor; then check **adjacent-pin isolation** on every populated plug (no strand whiskers): J3 1↔2↔3…, J4 1↔2…, J5, J13, J14 (expect 1↔2 SHORT — that's the jumper — and 3↔4 OPEN).

### 5.2 Machine-side landing (LOCKED OUT — runbook §1 mode A; Stage 2 confirms + Stage 5 landing)

Order: **chassis lugs → J4 sense taps → J5 → DIELL taps → outputs → J14.** Photograph every tap. Log every landing on the wire-map card.

1. Master breaker OFF, tagged, **verify 0 V** on the coil circuits (they hold charge — wait 30 s).
2. Land J4-14 + J5-12 ring lugs on a paint-free chassis stud; star washer; tug-test.
3. Per sense tap: identify the cavity's cable-side wire (count at the wire-entry face, **verify by beep to the cavity contact face** — brain side unplugged/isolated), tap ~50–80 mm behind the connector shell, beep tap↔cavity face, tug-test.
4. DIELL: identify signal vs supply on the DIELL harness **by voltage class from prior measurement (~16 V rest on signal) before tapping — never tap the 24 V supply wire.**
5. Outputs per §3 (Stage 5, after the §3.3 Stage-2 confirm).
6. J14: seat the plug (jumper already in it); Stop/CIS leads stay capped (OPEN — §2.3).

### 5.3 Per-lead continuity checklist (board plug pin → machine point) — run complete after landing

| ☐ | Lead | From | To | Expect |
|---|---|---|---|---|
| ☐ | GS1 | J4-1 | C2A cavity **C** contact face | <1 Ω |
| ☐ | GS2 | J4-2 | C2A **H** | <1 Ω |
| ☐ | GS3 | J4-3 | C2A **M** | <1 Ω |
| ☐ | GS4 | J4-4 | C2A **S** | <1 Ω |
| ☐ | GS5 | J4-5 | C2A **W** | <1 Ω |
| ☐ | GS6 | J4-6 | C2A **a** | <1 Ω |
| ☐ | GS7 | J4-7 | C2A **e** | <1 Ω |
| ☐ | GS8 | J4-8 | C2A **K** | <1 Ω |
| ☐ | GS9 | J4-9 | C2A **r** | <1 Ω |
| ☐ | GS10 | J4-10 | C2A **v** | <1 Ω |
| ☐ | BS | J4-13 | C2A **CC** | <1 Ω |
| ☐ | FGND | J4-14 | chassis stud | <1 Ω |
| ☐ | FGND | J5-12 | chassis stud | <1 Ω |
| ☐ | PBZ | J5-1 | C2A **EE** | <1 Ω; pressed → beeps to U/chassis |
| ☐ | DIELL-L | J3-7 | DIELL L signal tap | <1 Ω |
| ☐ | DIELL-R | J3-8 | DIELL R signal tap | <1 Ω |
| ☐ | DIELL GND | J3-9/10 | DIELL harness GND | <1 Ω |
| ☐ | S NO/COM | J6-1 / J6-2 | confirmed C1 feed/coil wires | <1 Ω each; J6-1↔J6-2 OPEN (relay unpowered) |
| ☐ | T NO/COM | J7-1 / J7-2 | confirmed C1 feed/coil wires | <1 Ω each; OPEN across |
| ☐ | SP NO/COM | J8-1 / J8-2 | confirmed C2A wires | <1 Ω each; OPEN across |
| ☐ | BE NO/COM | J9-1 / J9-2 | confirmed straddle wires | <1 Ω each; OPEN across |
| ☐ | M NO/COM | J10-1 / J10-2 | confirmed C2A wires | <1 Ω each; OPEN across |
| ☐ | M2 NO/COM | J11-1 / J11-2 | confirmed C2A wires | <1 Ω each; OPEN across |
| ☐ | TBSC jumper | J14-1 | J14-2 | <1 Ω (the §2 part, labeled) |
| ☐ | Stop/CIS | J14-3 ↔ J14-4 | — | OPEN (nothing landed, no jumper) |
| ☐ | Mask LED rail + 4 returns | J13-1,3,4,5,6 | mask LED pigtails (Stage 3) | <1 Ω each |
| ☐ | DIELL-L return | J3-9 | DIELL harness GND tap | <1 Ω |
| ☐ | DIELL-R return | J3-10 | DIELL harness GND tap | <1 Ω |
| ☐ | 5 V feed | J2-1 | PSU + terminal | <1 Ω |
| ☐ | PSU returns | J2-2 / J2-3 | PSU − terminal | <1 Ω each |

### 5.4 Isolation checks (Section F domains) — board plugs PULLED from the board, harness landed

| ☐ | Check | Expect |
|---|---|---|
| ☐ | FIELD_GND (J4-14 lead) ↔ chassis | **SHORT** (by design — the gripper return IS the chassis) |
| ☐ | Logic GND (J2-2) ↔ chassis | **OPEN** — logic never touches chassis through the harness |
| ☐ | Logic GND (J2-2) ↔ FIELD_GND (J4-14) | **OPEN** in the harness (isolation lives on-board in the TMA-0505S wetting supply — the harness must not defeat it) |
| ☐ | Bundle-1 shield drain (if multicore used) ↔ chassis | **OPEN** — drain terminates to **logic GND at the ENCLOSURE end only**, never grounded at the machine (F.2) |
| ☐ | Every output lead (J6–J11) ↔ chassis and ↔ FIELD_GND | ↔ FIELD_GND: **OPEN**. ↔ chassis: **OPEN or through-coil ohms** — a coil-side tap legitimately reads **~5–100 Ω to chassis through its 24 VAC coil** if the coil common is chassis-referenced (C2A-U in M's group IS the chassis-referenced control common). **Record the value per channel; only a DEAD SHORT (<1 Ω) to chassis is a FAIL** (that means you tapped a common/feed, not the switched coil wire) |
| ☐ | Every sense lead ↔ every output lead | **OPEN** (no cross-bundle contact) |
| ☐ | With machine LOCKED OUT: 0 VAC/VDC on every landed sense tap ↔ FIELD_GND | 0 V before the board is ever connected |

### 5.5 Pre-power + gates

1. Run **`phase8_revB_board1_prepower_test_checklist.md`** on the board + spec §12.9 bench sequence before the harness ever meets a powered machine.
2. Cutover follows the runbook run-of-show: Stage 6 logic-only (rail disabled) input verification — lift one pin per gripper and watch the GS channel flip (**G2-GS8 / G2-GSMAP**), PBZ press, DIELL beam break.
3. **Stage 6b/G3 including the Candidate-C coil-drop proof (§3.2 of this sheet) — hard gate, both S and T, before any commanded motion.** Every rail condition must independently drop motion permission; Stop/CIS requires the §2.3 landing to have closed.
4. Powered mapping session items that then close the CUT+LABEL-ONLY leads: cam cavities SA/SB/TA1/TA2 + SC front-end class (F.5 step 4) + §4.3 window-angle capture + foul lamp wire (F.5 step 6) + GP/PBC cold confirms.

---

**Change log:** 2026-07-07 — created (Candidate-C decision formal, `phase8_interlock_redesign.md` §7). Measured values only from the 2026-06-01 bench + 2026-06-27 + 2026-07-07 at-machine sessions; everything unmeasured is CUT+LABEL-ONLY / NO-LEAD / OPEN with its closing session named.
