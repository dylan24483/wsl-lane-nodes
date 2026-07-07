# Phase 8 Track-B — Controller-Replacement Cutover Runbook — Lanes 21+22

**Status:** DRAFT 2026-06-03 (rev-B bare-PCB fab package generated; board not yet fabricated/assembled/bench-proven). This is the run-of-show + the cutover-day field-capture procedure. It will be **refined after bench bring-up of unit #1** (spec §12.9), exactly like the Track-A / 8a plans were refined after their first validations. Written now so the **deliberately-deferred field items** are captured in a structured way before the controller swap.

**What this does:** replaces the **OEM 82-70 controller brain** at lanes 21+22 — the Omega-Tek Omniboard + its S2003LS2 triac driver bank + the Siemens/ice-cube control relays — with the **rev-B integrated Pi controller** (one board per lane, two boards on one Pi). After cutover, **cam timing, cam-stops, the cycle, masking, ball-state, and status indication come from the Pi/RP2040**, not the OEM controller. Scoring already comes from the camera (Track A) — *but note (2026-06-10): with current code the Track-A scoring node and this controller **cannot share a Pi**, so camera scoring goes dark at controller cutover until the unified scoring+control daemon exists — see the §2 prerequisite.*

**Who runs it:** Dylan, at the lane + on the Pi node, with **one helper for every live step**. Claude can't reach the hardware.

**Chassis scope:** lanes **21/22 = SS chassis + Omega-Tek retrofit**. The **board is common to the whole fleet; the harness + input populations are per-chassis.** Lanes 11/12 (Active-98 MP) need their own short field pass before their harness — see §10.

---

## ⚠️ READ BEFORE ANYTHING — how this differs from the 8a/Track-A cutovers

| | Track-A scoring (8a) | **Track-B controller (this doc)** |
|---|---|---|
| What it replaces | QubicaAMF scoring overlay (BCU/QBK/T-VISION/VDB) | **the 82-70 control brain (Omega-Tek + driver bank)** |
| Machine motion | OEM controller still runs the pinsetter | **the Pi/RP2040 now runs the pinsetter** |
| Worst-case failure | a wrong score (read-only) | **uncommanded or unstopped machine motion** |
| Blast radius | low — auto-falls-back to manual | **HIGH — this is a controls swap on a machine that moves and bites** |
| Reversibility | lift wires, ~15 min | re-plug the OEM brain, ~20–40 min |

**Because the blast radius is motion, this cutover is gated on a fully bench-validated unit (spec §12.9) and uses a STAGED, rail-disabled bring-up. Never go straight from "harness landed" to "auto motion." The safety-rail drop tests (§6 Stage 6b / Go-gate G3) are the heart of this procedure — if any rail condition fails to drop motion, you ABORT, you do not "fix it live."**

---

## 0. Cold-start — what the rev-B board is, and the non-negotiable safety model

- **One board per lane**, two identical boards on one Pi (independent I²C bus + RP2040 each). Develop/validate one, clone.
- **The board never sources machine power.** It only **opens/closes isolated dry contacts** in the existing machine control circuits. The S/T heavy-lug **contactors stay** and keep switching the 115 V motors and their OEM braking behavior; we only switch their **coil circuits** (all measured ~24 VAC).
- **The board is never the only safety device.** The upstream **Stop / C.I.S. / master-breaker chain stays live and upstream** (OEM service manual p11: Stop + C.I.S. are in parallel and both cut the rear-panel master breaker). The master breaker remains the final physical stop, including for a welded contact (the rail can drop a coil; it cannot open a welded contact).
- **The safety rail** (relay-enable rail) gates the board's output-relay coil supply. It is the **AND** of six conditions, any false → all motion relays drop, **not bypassable by the Pi in software**:

  | condition | source | fail-safe default |
  |---|---|---|
  | Watchdog OK | NE555 monostable, Pi kicks GPIO 12 (<~10 s) | false |
  | Arm OK | Pi arm GPIO (asserts only after operator-safe state / First-Ball-Zero) | false |
  | RP2040 OK | RP2040 heartbeat/permission | false |
  | Cam-stop OK | RP2040 immediate cam-edge drop path | false on fault |
  | TB/SC interlock OK | external hardware interlock loop (NC) — **landing design OPEN, see §3.4 + `phase8_interlock_redesign.md`** | open/false |
  | Stop/CIS/master OK | external machine safety chain | open/false |

- **Cam-stops are now SOLELY the RP2040's job.** Bench work (JOB-2) found the OEM machine uses **logic stops** (triac board), not hardwired cam-in-series — so removing the Omega-Tek board removes the existing cam-stop. The RP2040 hardware cam-stop **replaces** it. This is why the RP2040 cam-stop must be bench-proven (spec §12.9) *before* this cutover, and why the §6 Stage-6b cam-stop drop test is a hard gate.

**Reads-with:** `phase8b_pcb_revB_spec.md` (the electrical contract + §12.9 bench bring-up), `phase8_channel_allocation.md` (channel→pin map), `phase8_C1_C2A_pinout_p288.md` + `phase8_bench_session1_FINDINGS.md` (machine-side cavities), `phase8b_at_machine_fieldsheet.md` (the field results this consolidates), `phase8_trackA_golive_runbook.md` (scoring, brought up separately), `phase_8a_infrastructure_plan.md` (Cat6/PoE/enclosure/5 V — assumed already done).

---

## 1. SAFETY — lockout/tagout (read every time)

> ⛔ **A powered pinsetter moves and bites.** "Powered but idle" is NOT safe — a desk/customer action or a stray cam edge can cycle it. Treat motion as the default hazard.

- **WHEN:** lane formally **OUT OF SERVICE, OFF-HOURS only.** Flag 21+22 out of service at the desk. Tell whoever runs maintenance you are in the machine.
- **Two modes only:**
  - **(A) LOCKED OUT** — master breaker **OFF**, breaker tagged, **verified 0 V** on the coil circuits before hands go in. All capture work, all harness landing, all hand-actuation happens here. This is **most of the cutover.**
  - **(B) DELIBERATE LIVE** — powered, only for the explicitly-marked staged-motion steps in §6 Stage 7+. The machine moves **only on a command you and your helper both expect** — never because of a customer.
- **Body stays OUT of the sweep / table / pit travel path whenever powered.** If a step needs the mechanism rotated, rotate it **by hand, LOCKED OUT.**
- **Two people** for every live step — one at the controls/meter, one at the master breaker / e-stop.
- **Lift, don't cut.** Every machine wire is moved by lifting it from a terminal and landing it elsewhere. No cuts/crimps until the unit is soaked clean. This is what makes rollback possible.
- If anything feels wrong: **master breaker OFF first, ask second.**

---

## 2. Prerequisites — ALL must be green before scheduling the window

### Hardware / firmware (the gate that doesn't exist yet)
- [ ] **rev-B board fabbed + assembled** (bare-PCB fab package generated in `kicad/fab_revB_routed_manual/` → vendor upload preview → fab order → hand-solder Phoenix/through-hole parts; DNP suppression/M1 parts stay unpopulated unless explicitly released).
- [ ] **RP2040 firmware** flashed and bench-proven: cam-stop enforcement (cam edge → rail drop, independent of Pi) + UART event protocol to the Pi + heartbeat/permission.
- [ ] **Unit #1 fully bench-validated on a LOCKED-OUT / off machine per `phase8b_pcb_revB_spec.md` §12.9**, every step passing: power rails → I²C enumerate (3× MCP23017) → RP2040 boot+heartbeat → watchdog drop → arm drop → interlock drop → each relay contact with dummy load → input front-ends → **cam-stop rail drop** → only then machine-harness test.
- [ ] **Spare unit #2** assembled (rapid swap if #1 fails on-site).
- [ ] **Gripper front-end confirmed for chassis-referenced returns** (queued board item): JOB-3 found grippers are **chassis-return, gripped = CLOSED to ground** (not the TAC-GND bus the OEM 9800-MP schematic assumed). Confirm the opto-input front-end handles a chassis-referenced return before cutover. Likely fine (still contact-to-a-reference); does not change isolation domains.

### Software / server (mostly already live from Track-A)
- [ ] WSL-SRV `lane_node_server.py` running 24/7 (ports 8765 WS + 8766 HTTP), auto-restart configured.
- [ ] Pi node `lane-node.service` pointed at `ws://192.168.4.103:8765`, **`systemctl enable`d** (the "lane goes dark after a power event" trap — provisioning runbook). *(IP per the 2026-06-03 eero re-IP; old `192.168.86.36` is dead.)*
- [ ] `lane_node/controller_io.py` `MachineIO` map matches the rev-B contract (3× MCP23017 @ 0x20/0x21/0x22 + RP2040 UART link).
- [ ] **Track-A camera scoring already live + soaked** on 21/22 (`phase8_trackA_golive_runbook.md`). Bring scoring up *first, on a separate visit* so the cutover only changes the controller, not scoring too.
- [ ] **Unified scoring+control daemon exists** — **gates Stage 8's scoring half, gate G5, and the §9 scoring-agreement soak check.** With current code the controller and Track-A scoring **cannot run on the same Pi**: `lane-node-controller.service` carries `Conflicts=lane-node.service` and their GPIO maps overlap (`phase8_pi_provisioning.md` §7; the `TODO(server)` unification in `controller_daemon.py`). Until that unified daemon ships, **camera scoring goes DARK at controller cutover** — the desk's manual `POST /api/lane/<N>/score` path and the display keep working, but nothing auto-scores. Either ship the unification first, or run this cutover with Stage 8/G5/§9 scoring checks explicitly marked BLOCKED and replaced by the manual deck check (see Stage 8).

### Site / infra
- [ ] Infrastructure plan executed (Cat6, PoE+/5 V, DIN enclosure mounted near the cabinet) — `phase_8a_infrastructure_plan.md`.
- [ ] 12 V supply for DIELL on hand (replaces the retiring T-VISION supply, if not already done at Track-A).
- [ ] OEM brain **photographed in place** before any disconnection (so rollback re-plug is unambiguous).

---

## 3. THE DEFERRED FIELD-CAPTURE WORK ⭐ (the reason this runbook exists)

These were **deliberately deferred** to cutover because they're easier with the machine apart + a live input feed, and **none gate the board** (function-named connectors + adapter harness resolve them). Do all of §3 **LOCKED OUT**, hand-actuating, watching the daemon's live input feed (`journalctl -u lane-node-controller -f` shows input-bank reads — that's the **controller** unit; the Track-A `lane-node` service is stopped while the controller runs, enforced by its `Conflicts=lane-node.service`). Fill the worksheets in Appendix B as you go.

> **Live feed = your meter.** With the harness landed on the inputs (J_FAST_IN / J_SLOW_IN) but the **rail still disabled** (no motion possible), the Pi reads every input. So most capture is "actuate the thing by hand, watch which channel flips in the log." Cleaner than probing cavities cold.

### 3.1 Per-gripper GS# → C2A cavity (scoring/pin-sense map)
- Polarity is **locked: gripped (pin present) = CLOSED to ground**, return = **machine chassis** (not a C2A common pin). Block confirmed at C2A **4-bank (≈41C…410U)**; the per-GS# 1:1 is what we capture.
- **Method:** harness's gripper bank landed → inputs read in the live feed. **Lift ONE pin off the deck at a time** (or hand-actuate one gripper) and watch which `GS` channel deasserts. Record GS# → channel. Walk all 10 (corner + center first to catch ordering); flag any that don't follow the block order.
- Realize the result in the **HARNESS crimp order** (J4 lead *N* → measured cavity of gripper *N*) — do **NOT** edit the `controller_io.py` GS map; the netlist drift guard forbids it (see §7 gripper-mask gates, review finding #23).

### 3.2 Per-cam SA/SB/SC/TA1/TA2/TB → C2A cavity + trip angle
- **Method:** LOCKED OUT, **hand-rotate** the sweep/table mechanism; watch which **fast input** fires at which cam angle. Expected roles to confirm: SA (sweep run-through/zero ~270/360°), SB (guard ~66/186°), TA1 (table zero ~355/185°), TA2 (run-through ~260°), SC + TB (interlock cams). Record cam → C2A cavity → RP2040 GP#.
- **While here, prove the cam-stop:** with the rail armed for a single deliberate test only (§6 Stage 7), confirm each stop cam edge drops the rail. (Capture the *mapping* locked-out; prove the *drop* in the staged live step.)

### 3.3 C1/C2A output cavity confirm (land-check, mostly known)
Confirm the **measured** output cavities against THIS in-place machine before landing J_MOTION_OUT (they were probed on the spare cabinet):

| output | function | machine connector + cavities (measured on spare) | confirm here |
|---|---|---|---|
| S | sweep contactor coil ckt | **C1: C, D, N, T** | ☐ |
| T | table contactor coil ckt | **C1: A, K, H, E (+L @55Ω through-coil)** | ☐ |
| SP | spot solenoid ckt | **C2A** (0 Ω direct) | ☐ |
| BE | back-end | **straddles C1 (KK,C,L) + coil FF@66Ω; also C2A** | ☐ |
| M | master/control | **C2A** (FF/U/B) | ☐ |
| M2 | sweep-reverse | **C2A** (0 Ω) — **preserve the Expander interlock / shorting-plug function**, not just the cavity | ☐ |
| M1 | ball-return | **DNP — NOT harnessed** (see §3.6) | n/a |

> **Harness note:** outputs span **both** C1 (S, T) and C2A (M2, SP, M, BE) → J_MOTION_OUT needs leads to **both** machine connectors. The board switches the coil circuit only; it does not supply the ~24 VAC coil power.

### 3.4 TB/SC hardware interlock → J_SAFETY landing — ⚠️ REDESIGN OPEN, do NOT land as originally written
- **Measured 2026-06-27 (this machine):** SC + TB are a **SERIES interlock** embedded in the **live 24 VAC relay ladder** at a single node (**TSG-1 = C2A-U**) — NOT "parallel into the 24 V control path" as this step previously claimed. SC is accessible only via its **N.O. (pink)** wire (closed *in* the danger window — the inverse of a closed-when-safe loop); **TB has no standalone cavity** — both its wires tie into the same U node and neither isolates. **There is no isolatable dry NC pair to land J_SAFE1/2 on.**
- **The original method (LOCKED OUT continuity trace) is INVALID here:** the interlock contacts sit in series inside the relay ladder, so cold beeps travel **sneak paths through ~21 Ω relay coils** — a cold trace can neither find nor verify the landing. Interlock characterization is a **POWERED** capture (one deliberate test at a time, §1 mode B).
- ⛔ **Never land J_SAFE1/2 into the ladder as drawn** — that ties the board's VCC5 dry-sense loop into a live 24 VAC node.
- **The hardware landing is an OPEN DESIGN DECISION** — `phase8_interlock_redesign.md` (3 candidates: aux contacts added at the SC/TB switches · interposing relay sensing the interlock node · documented + powered-verified reliance on the OEM series contacts inside the coil circuits the board switches). **This step cannot be executed — and the cutover cannot be scheduled — until that decision lands** (feeds G2 + G3).
- Still true: this is a **first-class rail condition** — whatever design is chosen must remove motion permission **in hardware, not via firmware**. Until it lands, the software echo is the ONLY TB/SC guard (and it is itself pending the single-node redesign — review findings #4/#12).

### 3.5 Stop/CIS/master chain — confirm, preserve, do not replace
- OEM service p11: Stop + C.I.S. parallel, both cut the master breaker. **Confirm continuity** (Stop in RUN vs STOP drops the motor-relay coil rail) and **leave the chain intact upstream.** J_SAFETY's Stop/CIS sense ties into this chain so the board's rail also requires it OK.

### 3.6 M1 ball-return existence check
- Confirm whether ball-return is a **separate command** on this chassis. If yes → it's a future rev-C populate; **for this cutover M1 stays DNP and unharnessed** (FSM doesn't drive it).

### 3.7 (bonus, not a gate) cam-stop logic-vs-hardwired
- Hand-rotate so the SA cam trips; watch whether the S coil drops **by cam alone** (hardwired bonus backstop) or **only via the board** (logic). Expected: logic → no bonus backstop → the RP2040 cam-stop is the sole stop (already accounted for). Record for completeness.

---

## 4. Adapter-harness map (function-named board → C1/C2A)

The board exposes function-named connectors; this per-chassis harness lands them on C1/C2A. Cells marked **CAPTURE** are filled by §3 on the day.

| board connector | signal(s) | machine landing | front-end / polarity |
|---|---|---|---|
| **J_MOTION_OUT** | S, T | C1 cavities per §3.3 | isolated NO dry contact in series w/ existing 24 VAC coil ckt |
| | SP, M, M2, BE | C2A (+C1 for BE) per §3.3 | same; **M2: preserve Expander interlock** |
| | M1 | — | **DNP, not landed** |
| **J_FAST_IN** | SA/SB/TA1/TA2 | C2A cam cavities — **CAPTURE §3.2** | dry contact, **normally-closed** (A4) → dry-wetting population |
| | SC, TB | C2A interlock cams — **CAPTURE §3.2** | dry-wetting + also feed J_SAFETY HW path |
| | DIELL-L, DIELL-R | DIELL sensor leads | NPN open-collector, **idle HIGH ~13–17 V, broken LOW ~0 V**; 10 kΩ pull-up to +12 V |
| **J_SLOW_IN_A** | GS1–GS10 | C2A 4-bank ≈41C…410U — **per-GS# CAPTURE §3.1** | dry contact, **gripped = CLOSED to chassis** (chassis return) |
| | GP, OS, BS | C2A (GP≈412DD, BS≈112cc) — confirm §3 | dry contact |
| **J_SLOW_IN_B** | PBZ, PBC | C2A ≈21EE area — confirm §3 | momentary dry |
| | Foul (Radaray) | foul detector lead | edge; confirm form |
| | 10th / manual T/S/SWS/SWSR | spare (future) | — |
| **J_LAMP_LED** | L_FIRST/SECOND/STRIKE/FOUL | **our LEDs in the mask housings** | 5 V logic via low-side FET; **machine 15 VDC mask supply abandoned** |
| **J_SAFETY** | TB/SC NC loop | **BLOCKED — no isolatable dry pair exists (measured 2026-06-27); design open per `phase8_interlock_redesign.md`, see §3.4** | hardware NC series; rail condition |
| | Stop/CIS/master sense | upstream chain — confirm §3.5 | preserve; rail condition |
| **J_PI** | I²C bus, UART(↔RP2040), WDOG-kick GPIO12, ARM, INT | Pi 40-pin | per-board bus (board-22 on i2c-gpio) |
| **J_PWR** | 5 V logic, isolated field-wetting, 12 V DIELL | enclosure supplies | RPP + transient protection on input |

---

## 5. Pre-cutover prep (bench, 1–2 days before)

1. **Dry-run the whole §6 run-of-show on the bench** with the spare/off machine or a jumpered fixture — including every safety-drop test (Stage 6b) and the rollback. Don't first-run any step in production.
2. **Print the kit:** this doc §3 onward, the harness map §4, the Appendix-B worksheets (blank), spec §12.9 bench steps, and the OEM-brain in-place photos.
3. **Pack:** cutover enclosure (Pi + both rev-B boards + supplies, assembled), **spare unit #2**, multimeter, wire strippers + small flat-blade + torque driver (~0.5 Nm Phoenix), Sharpie + tape + pre-printed terminal labels, headlamp, bowling ball, phone (photos + AnyDesk), laptop (this doc + bench log, charged).
4. **WSL-SRV pre-checks (AnyDesk):** `curl http://192.168.4.103:8766/api/health` OK; `lane_state.db` clean of bench state; firewall 8765/8766 open; no pending Windows updates that could reboot mid-window.

---

## 6. Cutover window — run-of-show (staged, rail-disabled first)

**Time:** budget ~2–3 h for the first pair (capture + landing + staged bring-up). Off-hours, lanes closed, desk notified. Subsequent pairs are faster once the procedure is debugged on #1.

### Stage 0 — Arrival + photos (10 min)
Verify 21+22 out of service. **Photograph the OEM brain as-found** (Omega-Tek board, triac driver bank, every connector + terminal block, the C1/C2A faces with the "01"/AMP pin-1 datum). Ping the Pi node; confirm it registers at the server.

### Stage 1 — LOCKOUT (5 min)
Master breaker **OFF**, **tag it**, wait 30 s for discharge, **verify 0 V** across the coil circuits on C1/C2A (the 24 VAC coil rail can hold charge). You are now in mode A for everything through Stage 6.

### Stage 2 — Field capture §3 (45–60 min)
Work §3.1–§3.7. Fill Appendix-B worksheets. This is most of the window and it's all cold/hand-actuated.

### Stage 3 — Install our mask LEDs (10 min)
Fit the L_FIRST/SECOND/STRIKE/FOUL LEDs into the mask housings, run J_LAMP_LED (5 V, GND, 4 returns). **Leave the OEM 15 VDC mask-lamp wiring physically intact** (lift, don't cut) so rollback is clean.

### Stage 4 — Disconnect the OEM brain (15 min)
**Unplug** the Omega-Tek board + triac driver bank + their connectors. **Do not cut anything.** Bag/label each OEM connector. Keep the OEM brain on a shelf at the cabinet — it is your rollback.

### Stage 5 — Land the adapter harness (30 min)
One connector group at a time, **double-checking each against the §4 map**, lift-and-land, torque, tug-test, photograph: J_MOTION_OUT → C1/C2A coil circuits · J_FAST_IN → cams + DIELL · J_SLOW_IN_A/B → grippers/switches · J_SAFETY → TB/SC + Stop/CIS · J_LAMP_LED → mask LEDs · J_PI → Pi · J_PWR → supplies. Final visual pass: every board terminal vs the map. Catch swaps **now**.

### Stage 6 — Logic-only bring-up (rail DISABLED, no motion possible) (20 min)
**Master breaker still OFF; power LOGIC only (5 V).**
1. Pi boots, connects to server. **I²C enumerates all 3 MCP23017** per board. **RP2040 boots + heartbeats** — a `boot` line then `hb … ok:1` at ~4 Hz over UART. Health checks that actually exist on rev-B (the board has **no on-board status LEDs** — the D-refdes parts are flyback/snubber diodes and a DNP MOV footprint, NOT indicators): **GP2/`RP2040_OK` reads HIGH** on a meter or its test pad once healthy, **NE555 watchdog output** measurable at its test point while the Pi kicks GPIO 12, and **5 V present at J_PWR** — per spec §12.9. **All relays default OPEN; rail DISABLED** (arm de-asserted).
2. **Read inputs (still no motion):** lift a pin → a GS channel flips; hand-rotate a cam → fast input + (when armed) cam-stop path; break a DIELL beam → ball input; trip foul. Confirm the live feed reads each — this also verifies §3 captures.
3. **⭐ SAFETY-DROP TESTS (the heart of the cutover):** with the rail's enable simulated/armed on the bench-safe path, prove **each** condition independently drops the rail:
   - stop the watchdog kick → rail drops
   - de-assert arm → rail drops
   - reset/halt the RP2040 → rail drops
   - trigger a cam-stop edge → rail drops  **⚠️ requires RP2040 firmware v1.1 (cam-stop overrun). v1 firmware provides only the motion max-run backstop, NOT per-cam-edge enforcement — it depends on the §3.2 per-cam edge→angle polarity. So capture cam polarity FIRST (§3.2), flash v1.1, THEN run this sub-test. This sub-test is BLOCKED until then; the other five rail-drop conditions are testable with v1.**
   - open the TB/SC loop → rail drops  **⚠️ BLOCKED until the interlock design lands (`phase8_interlock_redesign.md` — decision OPEN). When run: prove it at the MACHINE side — physically force the SC/TB interlock (hold/rotate the followers into the interference state, or open the aux/interposed path at its machine-side origin) → motion permission must drop. Lifting a wire at the J_SAFE terminal is NOT sufficient. ⛔ Jumpering J_SAFE1-2 to bring the rail up is FORBIDDEN — a jumpered loop passes a terminal-lift test while silently removing collision protection, and nothing in software can detect it. (Sole exception: candidate C of the redesign doc, where a *documented, labeled* harness jumper is the design — then this sub-test becomes: force SC/TB into the danger state while the board commands S/T → the COIL circuit must drop even with the board contact closed.)**
   - open the Stop/CIS chain → rail drops
   **Every one must drop motion permission. Any failure → ABORT + rollback (G3).** Do not proceed to live motion with a safety condition that doesn't drop the rail.

### Stage 7 — First commanded motion (mode B — DELIBERATE LIVE) (20 min)
**Two people. Body CLEAR of the sweep/table/pit travel path. Hand on the master breaker.** Each command is one you both expect.
1. Master breaker **ON**. Arm.
2. Command **SP** (spot) alone → spot solenoid fires. No sweep/table motion yet.
3. Command **one sweep (S)** → watch it move and **stop on the SA cam** (RP2040 cam-stop). Body clear.
4. Command **one table (T)** → watch the cam-stop on TA.
5. Command **one full reset cycle** (lift/sweep/respot) → completes and stops cleanly on cams, no overrun.
   **Any runaway / missed stop → master breaker OFF, ABORT, rollback (G4).**

### Stage 8 — Ball cycle + scoring (15 min) — ⚠️ scoring half BLOCKED until the unified daemon (§2 prerequisite)
Roll a ball down each lane: DIELL fires → FSM cycles the pinsetter (cam-timed). **Verify the ball cycle with a manual deck check** — the cycle ran correctly for the leave (respot vs fresh rack), no overrun, stops crisp.

**The camera-scoring half of this stage is BLOCKED with current code:** Track-A scoring (`lane-node`) cannot run on the same Pi as the controller (`Conflicts=` + GPIO overlap — §2 prerequisite), so until the unified scoring+control daemon exists, **camera scoring is dark at this point**. Score the test balls manually (`POST /api/lane/<N>/score`) and watch the display at `http://192.168.4.103:8766/display?lane=21` update from manual entry. Once the unified daemon ships, restore the original check here: camera scores → display updates → detected standing pins match the deck across a few leave types. Repeat for both lanes.

### Stage 9 — Soak handoff (10 min)
Brief night staff: "21+22 are on the new Pi controller. The machine cycles automatically per ball; scoring is on the overhead display. If anything looks wrong — **leave the lane closed, photograph it, message Dylan. Do not try to fix it.**" Tape a "Phase 8 Track-B, contact Dylan" note inside the cabinet. Leave the OEM brain shelved + all wire labels on for the first soak week. **Drive home** — the watchdog + server tell you if anything goes sideways.

---

## 7. Go / No-Go gates

| gate | when | pass condition | fail action |
|---|---|---|---|
| **G1** | before scheduling | unit bench-validated (spec §12.9 all steps) · firmware proven · Track-A scoring soaked clean · spare on hand · OEM brain photographed | don't schedule |
| **G2** | after Stage 2 | all §3 field items captured; harness map §4 complete; no surprises vs measured cavities | resolve or defer non-blocking; abort if a safety landing (TB/SC) is unclear |
| **G3** | Stage 6b | **EVERY** rail condition (watchdog, arm, RP2040, cam-stop, TB/SC, Stop/CIS) independently drops motion permission · **TB/SC proven by physically forcing the interlock at the MACHINE side** (not a J_SAFE terminal lift) · **a J_SAFE1-2 jumper = automatic FAIL** (unless it IS the landed candidate-C design, in which case the live coil-drop proof replaces the rail-drop proof — `phase8_interlock_redesign.md`) | **ABORT → rollback** |
| **G4** | Stage 7 | commanded S/T/SP each stop on cams; full reset completes + stops; no runaway | **breaker OFF → rollback** |
| **G5** | Stage 8 | ball cycle correct + manual deck check across a few balls/leaves both lanes *(the auto-score half is **BLOCKED** until the unified scoring+control daemon — §2 prerequisite; until then G5 gates on cycle correctness only)* | flip scoring to manual (Track-A Step 7); controller stays if G3/G4 passed |

**Rule:** any failure at or before **G4 = rollback to the OEM brain.** Do not debug machine motion live.

**Gripper-mask gates** (crosscut deferrals from the 2026-06-27 review, findings #23/#24 — enforce at **G2**, captured via §3.1):

- **G2-GS8:** the **GS8 C2A cavity MUST be read before any gripper-mask-based decision is trusted.** ✓ **READ 2026-07-07: GS8 = C2A-K** (drop-a-pin; the old 48H prediction was wrong — H is GS2's cavity). Gate's residual obligation: **land the K lead and prove it** — an unwired/unlanded GS8 input reads idle-high = "not standing" (`INPUT_ACTIVE_LOW`), so a **pin-8-only leave reads `mask==0` → false STRIKE** → the fresh-rack cycle sweeps the standing pin. The per-gripper drop-one-pin assert check at cutover remains mandatory.
- **G2-GSMAP:** the **GS-label→J4-lead binding is fixed in software** (`controller_io.py` `IN_A_MAP` order; the netlist drift guard asserts it — do NOT edit the map at cutover). **Cutover assignment happens in the HARNESS:** crimp J4 lead *N* to the **measured** C2A cavity of gripper *N* per the Section F J4 table (`phase8_machine_harness_spec_sectionF.md` §F.1, J4 `J_SLOW_IN_A`). **Verify by the drop-one-pin test per gripper** (lift one pin at a time, confirm the asserted GS label matches — §3.1) **before trusting the mask.**

---

## 8. Rollback (reconnect the OEM brain)

Trigger: any G3/G4 failure, or a Stage-7/8 fault that isn't a trivial single-wire fix.

1. **Master breaker OFF, lockout, verify 0 V.**
2. **Lift the adapter harness** from C1/C2A/TB/SC/Stop-CIS (use the tape labels; lift, don't cut).
3. **Re-plug the OEM Omega-Tek board + triac driver bank + connectors** (preserved from Stage 4).
4. Mask LEDs (J_LAMP_LED) can stay unpowered (harmless); the OEM 15 VDC mask wiring was left intact, so OEM lamps work on re-plug.
5. **Master breaker ON.** OEM controller runs the machine. **Bowl a frame on each lane** to confirm normal operation.
6. Leave the rev-B enclosure powered down + in place (harmless); take the unit home to debug.
7. **Document the failure:** which gate/stage, observed behavior, suspected cause → `project_phase8b_cutover_attempt_N.md` memory.

**Budget:** ~20–40 min (longer than the 8a wire-lift because you re-plug the brain). Practice it in the Stage-5 dry run.

---

## 9. First-week soak

Daily for 7–10 days:
- `curl http://192.168.4.103:8766/api/health` — node connected, no excessive disconnects.
- WSL-SRV log — no `lane_node_server.py` errors, no protocol-mismatch, no unexpected disconnects.
- **Walk 21+22 during open hours** — watch a few real cycles: cam-stops crisp, no overrun, reset completes, scoring agrees.
- **Cam-stop / watchdog timeouts in the journal must be ZERO.** Any timeout → investigate before it recurs.
- **Heat/vibration** — touch the Pi case + boards days 1–3; warm-not-hot.
- **Track-A scoring** agreement (detected vs actual) — *BLOCKED until the unified scoring+control daemon exists (§2 prerequisite): while the controller owns the Pi, camera scoring is dark and scores are manual desk entries; skip this check until unification ships.*

After 7–10 clean days → **cleanup visit** (tidy wire routing; decide whether the OEM brain is permanently retired or stays shelved as a spare). Then the next chassis (§10). Capture any surprise in `project_phase8b_first_cutover_lessons.md` before replicating.

---

## 10. Per-chassis — this is the 21/22 (SS + Omega-Tek) harness only

The **board is fleet-common; the harness + input populations are per-chassis-type.** Before cutting over **11/12 (Active-98 MP)**, run a short field pass on that pair for the chassis-specific items: A1 working voltage, A4 input forms, and the C-series harness map (output cavities, cam→cavity, gripper return reference, TB/SC terminals). Don't assume 21/22's cavities carry over — the Omega-Tek retrofit already diverged from OEM on M2/S cavities and on the gripper return (chassis vs TAC-GND). Clone the *board*, re-capture the *harness*.

---

## 11. Where this sits in the sequence

Upstream of this runbook (must finish first): rev-B **bare-PCB fab package generated → vendor upload preview → fab order → assemble with DNP parts held out → RP2040 firmware/daemon bench bring-up → full board validation (spec §12.9).** The cutover is scheduled only after all of those are green. There is no external deadline — the Phase-8 thesis is "do it once, do it right." A bad first controller cutover poisons the soak and the per-chassis rollout.

---

## Appendix A — On-call posture
Phone on. Laptop with AnyDesk + this doc + the bench log. Helper briefed that 21+22 are in maintenance; call only for a safety issue (sparks/smoke/smell/unexpected motion). No chat during the window — debrief after.

## Appendix B — Field-capture worksheets (fill on the day)

**Field symbols:** `^` asserted/closed/rising · `v` deasserted/open · `~` transient/AC · `=` stable · `?` recheck.

**B.1 Grippers (§3.1)** — polarity locked gripped=CLOSED-to-chassis; capture GS#→channel:
```
GS1 __  GS2 __  GS3 __  GS4 __  GS5 __  GS6 __  GS7 __  GS8 __  GS9 __  GS10 __
order matches 4-bank block? Y/N ___   anomalies: ___________
```
**B.2 Cams (§3.2)** — cam → C2A cavity → RP2040 GP# → trip angle:
```
SA __/__/__°  SB __/__/__°  SC __/__/__°  TA1 __/__/__°  TA2 __/__/__°  TB __/__/__°
cam-stop drop confirmed (Stage 7)?  S:__  T:__
```
**B.3 Outputs (§3.3 confirm)** — S(C1 C,D,N,T)__ · T(C1 A,K,H,E,L)__ · SP(C2A)__ · BE(straddle)__ · M(C2A)__ · M2(C2A)__ · M1 exists? Y/N __
**B.4 Safety (§3.4/§3.5)** — interlock design landed (`phase8_interlock_redesign.md` candidate A/B/C): __ · machine-side SC/TB force drops motion permission Y/N __ · Stop drops coil rail Y/N __
**B.5 Switches** — PBZ __ · PBC __ · GP __ · OS __ · BS __ · Foul form __
