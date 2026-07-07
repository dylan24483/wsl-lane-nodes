# Section F — Machine Interface Harness Build Spec

WSL Phase 8 Lane Controller (rev-B/C) ↔ AMF 82-70 (C1 / C2A)
Scope = ONE LANE = ONE BOARD. Spare cabinet = lanes 21/22, SS chassis + Omega-Tek Omniboard.
Synthesized 2026-06-27 from the reverse-engineering docs (provenance at bottom).

---

## F.0 — How to read this spec

- **Confidence legend:** `confirmed` = bench-measured on the spare cabinet 2026-06-01, or read from a legible schematic detail. `best-effort` = signal→device pairing is solid but the exact C1/C2A pin *digit* is 225-DPI OCR-ceiling guesswork — **must be metered before you crimp.** `TBD` = not yet measured at all.
- **⊕** = channel is wired/footprinted on the board but the current FSM (`cycle_control_8270.py`) does not use it. Build the lead anyway (no respin at cutover), but it's not on the cutover critical path.
- **Board-side connectors are already fixed** (Phoenix MC/MKDS plugs on the rev-B BOM). Nothing here changes the board — everything below is the *cable + machine-side mate*.
- **The single hard blocker is the C2A input-pin digit map** (best-effort throughout) + **two TBD output connectors (M, M1)**. F.5 is the meter list that closes them.

---

## F.1 — SIGNAL MAP TABLE (one row per wire)

### INPUTS — machine → board

#### J3 `J_FAST_IN` → RP2040 (10-pin MCV-1,5/10; field-sense, opto front-end)

| Board pin | Signal | Dir | C1/C2A cavity | Machine device | Voltage class | Confidence |
|---|---|---|---|---|---|---|
| J3-1 | SA (GP6) | IN | C2A-31N | Sweep cam (270 run-thru / 360 zero) | dry contact, wet @ FIELD_WET_V 5V | best-effort (cavity) |
| J3-2 | SB (GP7) | IN | C2A-31H | Sweep guard cam (66/186) | dry contact | best-effort |
| J3-3 | SC (GP8) | IN | **C2A-? UNKNOWN** | Sweep-under-table interlock cam (86–243); HW interlock echo | dry contact | **TBD (cavity)** |
| J3-4 | TA1 (GP9) | IN | C2A-34N | Table cam (355 zero / 185 reset) | dry contact | best-effort |
| J3-5 | TA2 (GP10) | IN | **C2A-21A or 30N** | Table cam (260 run-thru / decision) | dry contact | **best-effort, 2 candidates** |
| J3-6 | TB (GP11) | IN | **C2A-? UNKNOWN** | Table-sweep interlock cam (105–255); HW interlock echo | dry contact | **TBD (cavity)** |
| J3-7 | DIELL-L (GP12) | IN | DIELL harness (not C2A) | Ball detect L beam — cycle trigger | ~16 V rest / 0.7 V broken, NPN active-low | **confirmed** |
| J3-8 | DIELL-R (GP13) | IN | DIELL harness (not C2A) | Ball detect R beam | ~16 V / 0.7 V, NPN active-low | **confirmed** |
| J3-9/10 | FIELD_GND | — | C2A isolated return | wetting return | — | — |

#### J4 `J_SLOW_IN_A` → MCP IN-A 0x20 (14-pin MCV-1,5/14)

| Board pin | Signal | Dir | C1/C2A cavity | Machine device | Voltage class | Confidence |
|---|---|---|---|---|---|---|
| J4-1 | GS1 | IN | C2A-41C (TAC-1) | Gripper 1 pin-sense | dry contact | best-effort |
| J4-2 | GS2 | IN | C2A-42H (TAC-2) | Gripper 2 | dry contact | best-effort |
| J4-3 | GS3 | IN | C2A-43M (TAC-3) | Gripper 3 | dry contact | best-effort |
| J4-4 | GS4 | IN | C2A-44S (TAC-4) | Gripper 4 | dry contact | best-effort |
| J4-5 | GS5 | IN | C2A-45W (TAC-5) | Gripper 5 | dry contact | best-effort |
| J4-6 | GS6 | IN | C2A-46Z (TAC-6) | Gripper 6 | dry contact | best-effort |
| J4-7 | GS7 | IN | **C2A-47? (TAC-7)** | Gripper 7 | dry contact | **best-effort, digit unread** |
| J4-8 | GS8 | IN | C2A-48H (TAC-8) | Gripper 8 | dry contact | best-effort |
| J4-9 | GS9 | IN | **C2A-49? (TAC-9)** | Gripper 9 | dry contact | **best-effort, digit unread** |
| J4-10 | GS10 | IN | C2A-410U (TAC-10) | Gripper 10 | dry contact | best-effort |
| J4-11 | GP | IN | C2A-412DD | Gripper-protect switch | dry contact | best-effort |
| J4-12 | OS ⊕ | IN | **C2A-? UNKNOWN** | Off-spot switch | dry contact | **TBD** |
| J4-13 | BS | IN | C2A-112cc | Bin switch (#9 in bin) | dry contact | best-effort |
| J4-14 | FIELD_GND | — | C2A TAC-GND (C2A-310E) | gripper-strip common / return | — | confirmed (chain) |

#### J5 `J_SLOW_IN_B` → MCP IN-B 0x21 (12-pin MCV-1,5/12) — all ⊕ future / spare

| Board pin | Signal | Dir | C1/C2A cavity | Machine device | Voltage class | Confidence |
|---|---|---|---|---|---|---|
| J5-1 | PBZ | IN | C2A-21EE | Zero / 1st-ball / manual-intervention pushbutton | dry contact, momentary | best-effort |
| J5-2 | PBC ⊕ | IN | C2A-21EE area | Cycle pushbutton | dry contact, momentary | best-effort (approx) |
| J5-3 | FOUL | IN | Radaray foul harness (not C2A) | Foul-line detector | ~5 V DC logic (4.6→4.9 swing); LAMP wire unmetered | **best-effort (marginal tap)** |
| J5-4 | TENTH ⊕ | IN | **C2A-? UNKNOWN** | 10th-frame switch | dry contact | **TBD** |
| J5-5 | MAN_T ⊕ | IN | C2A T-2 (approx) | Manual table | dry contact | best-effort (descriptive) |
| J5-6 | MAN_S ⊕ | IN | C2A S-1 / S-4 (approx) | Manual sweep | dry contact | best-effort (descriptive) |
| J5-7 | MAN_SWS ⊕ | IN | C2A SWS-4 (approx) | Manual sweep-switch | dry contact | best-effort (descriptive) |
| J5-8 | MAN_SWSR ⊕ | IN | **C2A-? UNKNOWN** | Manual sweep-reverse | dry contact | **TBD** |
| J5-9/10/11 | AUX1–3 | IN | — (spare) | unallocated | — | spare |
| J5-12 | FIELD_GND | — | C2A isolated return | wetting return | — | — |

### OUTPUTS — board → machine (J6–J11, 2-pin MKDS-1,5/2; **pin1 = NO, pin2 = COM** on every block; relay dry contact, board never sources voltage)

| Board conn | Signal | Dir | C1/C2A cavity (bench) | Machine load | Voltage class (coil switched) | Confidence |
|---|---|---|---|---|---|---|
| **J6** | S — sweep | OUT | **C1: C, D, N, T** | Sweep contactor coil → sweep motor | **24 VAC** (Siemens 3TH4022-0AC2, 5 Ω) | **confirmed** (corrects predicted J→C) |
| **J7** | T — table | OUT | **C1: A, K, H, E (+L through-coil)** | Table contactor coil → table motor | 24 VAC class (heavy-lug contactor) | **confirmed** (corrects predicted P→L) |
| **J8** | SP — spot | OUT | **C2A (direct 0 Ω)** | Spot solenoid | ~24 V native AMF (100 Ω coil) | **confirmed** |
| **J9** | BE ⊕ — back-end | OUT | **C1: KK, C, L + coil FF@66 Ω; straddles C2A** | Back-end motor (continuous) | ~24 V native AMF (22 Ω) | **confirmed (straddle)** |
| **J10** | M ⊕ — master | OUT | **C2A: FF, U, B** | Master relay → power/halo/pit light | ~24 V native AMF (82-70-5515, 80 Ω) | **confirmed** (was TBD; session-2 found C2A FF/U/B) |
| **J11** | M2 ⊕ — sweep-reverse | OUT | **C2A (direct 0 Ω)** | Sweep-reverse relay (gutter / 7-10) | ~24 V native AMF (82-70-5515, 80 Ω) | **confirmed** |
| *(J12 DNP)* | M1 ⊕ — ball-return | OUT | **TBD — not measured** | Ball-return motor relay | ~24 V class (assumed) | **TBD** (footprint only, off-BOM) |

Status lamps L-1st/L-2nd/L-foul/L-strike (OUT-A.A7–B2) and the optional OUT-B pindicator land on the **mask (PM) plug** — a separate ELCO-class connector, **out of scope for Section F**. (And per the leave-on-monitor decision, the OUT-B 10-pin pindicator is deprecated.)

> **Net design rule (load this before wiring outputs):** the machine's own T2/T3/T4 transformers power every coil. Each J6–J11 dry contact goes **in series with an existing coil circuit** — you are *switching* the coil, not *supplying* it. The board's RELAY_ENABLE_RAIL + Omron G5LE contact is the only thing you insert. **Never feed board 5 V/24 V into these cavities.**

---

## F.2 — WIRE SPEC

Three physically separated cable bundles. **Do not co-bundle them** — field-sense and machine-output may share a connector shell at the machine but must run as separate jacketed cables from the enclosure to reduce 24 VAC/115 V coupling into the opto sense lines.

### Bundle 1 — FIELD-SENSE (J3 / J4 / J5 inputs)
- **Conductors:** J3 = 8 sig + 2 GND (10); J4 = 13 sig + 1 GND (14); J5 = 11 sig + 1 GND (12). ~36 cores total.
- **Gauge:** **22 AWG** stranded (7/30). Opto-LED loops at ~2 mA (5 V / 2.2 kΩ); gauge chosen for crimp reliability, not ampacity.
- **Insulation:** 300 V PVC, 80 °C min (rate for 300 V so a mis-probe onto a 24 VAC cam rail can't melt it).
- **Recommended cable:** shielded multicore — **Belden 1063A (12×22 AWG, foil+drain)** or Alpha 5160C. **Terminate shield drain to logic GND at the ENCLOSURE end only** (single-point; never ground shield at the machine — isolated domain).
- **DIELL (J3-7/8) exception:** 3-wire active sensor on its own factory harness. Tap **signal + GND only** into J3; do not pull supply through the board cable. Twisted pair, 22 AWG.

### Bundle 2 — SAFETY-LOOP (interlock + E-stop continuity)
- **NOT a board cable.** It's the machine's existing 24 V control safety chain (Stop/CIS, DIELL interlock, TB/SC parallel interlock). Must stay **hardware, in-series, untouched by the Pi.**
- Where the harness passes *through* the coil circuits the relays switch, use **18 AWG** stranded, **600 V** (24 VAC coil current ~0.3–1 A, safety-critical loop — over-spec deliberately).
- **Physically separate raceway** from Bundle 1.

### Bundle 3 — MACHINE-OUTPUT (J6–J11 relay dry contacts)
- **Conductors:** 2 per connector × 6 = 12 cores (NO/COM pairs).
- **Gauge:** **18 AWG** stranded, 600 V. S/T contactor coils pull the most (Siemens 5 Ω → real inrush).
- **Recommended cable:** 18 AWG 2-cond per output, or **Belden 1419A (6-pair, 18 AWG)** for the whole output bundle. No shield (dry contacts).
- **Keep the C1 motor-side 115 V cavities OUT of this bundle** — those are switched by the contactors, never tapped by the board.

### Rough lengths (enclosure at the pinsetter base)
- Enclosure → C1/C2A block: **~0.6–1.0 m** → build at **1.2 m** for service slack + drip loop.
- DIELL tap: **~1.5 m**. Foul tap (at the cabinet, not the foul line): **~1.0 m**.

### Separation summary
| Run | Domain | Min separation |
|---|---|---|
| Bundle 1 field-sense | isolated 5 V / opto | ≥50 mm from Bundles 2 & 3; cross at 90° |
| Bundle 2 safety/coil loop | 24 VAC, safety-critical | own raceway; never bundled with sense |
| Bundle 3 machine-output | 24 VAC switched coils | may parallel Bundle 2; ≥50 mm from Bundle 1 |

---

## F.3 — MACHINE-SIDE CONNECTOR PARTS

**Status (corrected 2026-06-27): the connector P/N WAS read at the session-1 bench (2026-06-01)** — molded **AMP "1-0 series" 67209 / 67211** on the C1 (34-pin) + C2A (50-pin) edge-card connectors, with "01"+AMP as the pin-1 datum. So the family is known. **Still to confirm before ordering mates:** whether 67209/67211 is the *housing* or the *crimp-contact* P/N, and the **contact gender** (cabinet header vs cable plug). Pin those two and Path A is straightforward; Path B (splice) stays the fast fallback for the pilot.

### Path A (preferred) — proper mating connectors
1. **Confirm the housing series at the cabinet** (F.5 step 0): read molded P/N, count rows/cols (C1 = 34-pin 3-col double-letter rows + 2 power; C2A = 50-pin 4-col), measure pitch.
2. If Mate-N-Lok class: 34-pos plug (gender opposite the header) + crimp contacts (candidate **AMP 770988-1 / 60619-x** sockets or **67209/67211** strip — verify 18 AWG range + pin/socket gender first); 50-pos plug + 50 contacts same family; correct keying plug + pin-1 datum each.
3. Crimp tool: family-specific AMP hand crimper, confirmed once contact P/N is fixed.

### Path B (fallback, fine for a 2-lane pilot) — documented splice / piggyback
- **In-line tap each cavity** at the existing machine wire with **3M Scotchlok IDC taps** or (cleaner) **cut-and-Wago 221** with the original wire restored on the far side — preserves the machine's own circuit (critical for coil/safety loops) while bringing a parallel lead to the enclosure.
- **Document every tap** on a wire-map card taped inside the enclosure door.
- **NEVER cut into the safety loop** (Stop/CIS, DIELL interlock, TB/SC) for a tap — bridge across an existing contact, never interrupt the loop.

### Board side — already specified, no action
Phoenix MC 1,5/x-ST-3,5 (J3/J4/J5) + MKDS 1,5/2-5,08 (J6–J11) plugs are on the rev-B parts list. **22 AWG ferrules** on the sense plugs, **18 AWG ferrules** on the output plugs.

---

## F.4 — PER-CHANNEL FRONT-END DECISIONS (dry-contact wetting vs 24 VAC-rectified sense)

Board ships every input as the **default dry-contact wetting front-end** (FIELD_WET_V 5 V → 2.2 kΩ → opto → field pin → FIELD_GND on close; active-low). Per-channel choice to swap to 24 VAC-rectified sense for any input that's a live AC node:

| Channel(s) | Decision | Rationale | Lock state |
|---|---|---|---|
| **GS1–GS10, GP, BS, OS** (J4) | **DRY-CONTACT** (default) | Mechanical switches to TAC common — clean dry contacts. | **LOCKED** (pending cavity digits) |
| **SA, SB, SC, TA1, TA2, TB** (J3 cams) | **DRY default — VERIFY each isn't a live 24 V cam node** | Omega-Tek cams *may* present switched 24 V. **If metered AC > a few V at the cam C2A pin → switch that channel to 24 VAC-rectified sense.** | **CONDITIONAL — meter first (F.5 step 4)** |
| **PBZ, PBC, TENTH, MAN_*** (J5) | **DRY-CONTACT** (default) | Pushbuttons + manual toggles = dry. | LOCKED (⊕ future) |
| **DIELL-L / DIELL-R** | **dedicated active-sensor opto** (~16 V NPN active-low) | Powered 3-wire NPN, not dry. Bench-proven. | **LOCKED (confirmed)** |
| **FOUL** (J5-3) | **~5 V logic sense — RE-TAP recommended** | Marginal ~5 V node; prefer the foul LAMP wire (unmetered — may be AC → needs 24 VAC front-end). | **OPEN — meter lamp wire (F.5 step 6)** |

**Meter rule:** at each input cavity, machine powered + idle, meter pin → FIELD_GND. **< ~2 V or open = dry → keep default wetting. Sustained 12–24 VAC = live → populate that channel's 24 VAC-rectified sense option.** Mark per channel on the wire-map card.

---

## F.5 — BENCH-VERIFY-BEFORE-BUILD CHECKLIST

Do these at the spare cabinet, in order. Steps 0–8 bench/idle; 10–12 at-machine during cutover prep. (session-2 probe-list refs in brackets.)

- **Step 0 — Connector identity (BLOCKS F.3).** Photograph + read molded P/N on C1/C2A. Count rows/cols, pitch, **pin-1 datum** + keying. Decide Path A vs B. *(fieldsheet PART 0 — never done)*
- **Step 1 — C2A INPUT pin digits (BLOCKS most of F.1).** Continuity-trace each cam+gripper+pushbutton to its C2A cavity:
  - **SC (J3-3) + TB (J3-6)** — resolve `C2A-?` (interlock cams — highest priority/safety). *(§5)*
  - **TA2 (J3-5)** — resolve **21A vs 30N**. *(§5)*
  - GS7 (`47?`), GS9 (`49?`) — read the unread digit. *(DETAIL-K)*
  - OS, TENTH, MAN_SWSR — resolve the three `C2A-?` (⊕, lower). MAN_T/S/SWS — upgrade descriptive → real cavity codes.
- **Step 2 — C1 OUTPUT re-confirm (S/T).** Beep-verify **S = C,D,N,T (C not J); T = A,K,H,E,L (L not P)**. *(§4)*
- **Step 3 — Output close-out (M1 TBD).** Re-confirm M (C2A FF/U/B) + BE straddle. **M1 never metered → meter coil + connector** before populating J12. *(§ M/M1)*
- **Step 4 — Per-input front-end class (drives F.4).** Meter each input cavity → FIELD_GND: dry (<2 V) vs live 24 VAC. Flips cam channels if any read AC. *(§5)*
- **Step 5 — Cam-stop topology.** From each cam C2A pin, beep to (a) S/T relay coil vs (b) Omega-Tek edge — coil = hardwired stop (preserve), board-only = logic stop (RP2040 must time). *(§11)*
- **Step 6 — Foul tap.** Meter the foul **lamp wire** voltage; decide dry vs 24 VAC front-end for J5-3. *(§6)*
- **Step 7 — Coil voltage labels.** Photograph Siemens 3TH4022 "__V __Hz" face to confirm 24 VAC; read heavy-lug table-contactor coil Ω + V. *(§1–2)*
- **Step 8 — T-coil <1 Ω suspect + cap safety.** Armature-press the suspect <1 Ω table-coil read (steady=coil, jumps=contact). Confirm CP2/CP3 ≈ 0 V before handling. *(§3, §8)*
- **Step 10 (at-machine) — Safety chain actuation.** Stop RUN → coil rail live; STOP → dead. Break-on-STOP = hardware-in-series (preserve). No break = **FLAG, add hardware interlock before any Pi-driven motor.** *(§A)*
- **Step 11 (at-machine) — Cam-stop actuation proof.** Hand-rotate sweep/table to trip SA/TA; coil drops from cam alone (hardwired) or only after the board reacts (logic)? *(§B)*
- **Step 12 (at-machine) — Preserve DIELL interlock + E-stop + confirm chassis variant** at the tap before energizing. *(§12)*

---

## F.6 — OPEN RISKS / HONEST GAPS

1. **Connector P/N known** (AMP 67209/67211, read at the bench) **but housing-vs-contact + gender not yet pinned.** Confirm both before ordering Path-A mates; Path B (splice) stays the de-risked fallback. *(Downgraded from "#1 gap" — the real #1 is the C2A **input** cavity digits, item 2.)*
2. **Every C2A input pin digit is best-effort (OCR ceiling).** SC + TB are literally unknown *interlock* cams (safety dimension). Don't crimp any J3/J4 sense lead before F.5 step 1.
3. **TA2 = two candidate cavities (21A vs 30N)** — coin-flip until metered.
4. **M1 connector never measured; M re-confirm.** Both ⊕ future (not cutover-blocking); don't populate J12 on assumption.
5. **Cam front-end (dry vs 24 VAC) conditional.** If cams present a live AC node, six J3 channels need the rectified front-end — only F.5 step 4 resolves it.
6. **Foul tap marginal** (~5 V, 0.3 V swing); cleaner lamp-wire tap unmetered/possibly AC. J5-3 genuinely open.
7. **Safety-chain series-vs-logic unproven.** Design already mandates hardware end-stops + TB/SC interlock + RP2040 timing regardless — so not build-blocking — but steps 10/11 must precede first motor energize; "no-break-on-STOP" is a hard FLAG.
8. **Chassis generalization:** all landings are from the **SS + Omega-Tek spare (21/22)**. Lanes 11/12 = **MP/Ultra-98** — machine side common, but re-verify cavity codes before reusing on MP.
9. **RP2040 cam-stop is firmware v1.1 (deferred), not shipped.** Shipped = RP2040_OK + 8 s max-run backstop only. Harness carries the fast-input wires today, but per-cam-edge relay-drop is not live — don't spec as if hardware cam-stop enforcement exists yet.
10. **Snubber/MOV on outputs DNP** until inductive coil current is characterized (F.5 step 7). The 5 Ω Siemens S contactor has real inrush — populate arc-suppression before sustained switching or the G5LE contacts pit.

---

**Build-order bottom line:** Do F.5 **step 0** (connector ID) + **step 1** (C2A digits, esp. SC/TB/TA2) **first** — they unblock F.1 and F.3 together. The output side (J6–J11) except M1 is bench-confirmed and **can be cabled now** (18 AWG, Bundle 3). DIELL + grippers are the most build-ready inputs; cams + foul are gated on metering.

**Provenance:** `phase8_channel_allocation.md`, `phase8_controller_interface_MAP.md`, `11_connector-pinouts.md` §11.1/§11.4–11.7, `phase8_C1_C2A_pinout_p288.md`, `phase8_controller_interface_fieldsheet.md`, `phase8_bench_session1_FINDINGS.md`, `phase8_bench_session2_probe_list.md`, memory `project_amf_8270_interface_research.md`. Every `confirmed` row traces to the 2026-06-01 bench session; every `best-effort`/`TBD` is flagged in F.5.
