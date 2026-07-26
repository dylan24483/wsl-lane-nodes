# Phase 8 Track-B — Controller-Replacement Cutover Runbook — Lanes 21+22

**Status: DRAFT / PHYSICAL RELEASE NO-GO (updated 2026-07-24).** The Rev-D R5 fabrication package exists as geometry evidence, but the board has not been ordered, assembled, first-article qualified, or bench-proven. The committed v1.2.3 production UF2 is Rev-D-only and still has every cam-stop enforcement flag OFF with trip polarities unconfirmed; it is **not a cutover image**. This runbook remains the run-of-show and field-capture procedure and must be refined after unit #1 passes the Rev-D first-article and bench gates.

> **2026-07-24 field safety correction:** physical inspection found no C.I.S.
> device or wiring on lanes 21/22; their cushion is mechanical and DIELL is the
> ball/cycle trigger. Whether another pit-entry interlock exists is unresolved.
> J_SAFE3–4 remains OPEN and the field rail cannot arm. Any new final pit-entry
> interlock must act in an approved upstream master/control-power
> safety-disconnect architecture; a J14-only contact is permission gating and
> cannot stop a welded downstream contact.

**What this does:** replaces the **OEM 82-70 controller brain** at lanes 21+22 — the Omega-Tek Omniboard + its S2003LS2 triac driver bank + the Siemens/ice-cube control relays — with the **Rev-D integrated Pi controller** (one board per lane, two boards on one Pi). After cutover, **cam timing, cam-stops, the cycle, masking, ball-state, and status indication come from the Pi/RP2040**, not the OEM controller. Scoring already comes from the camera (Track A) — *but note (2026-06-10): with current code the Track-A scoring node and this controller **cannot share a Pi**, so camera scoring goes dark at controller cutover until the unified scoring+control daemon exists — see the §2 prerequisite.*

**Who runs it:** Dylan, at the lane + on the Pi node, with **one helper for every live step**. Claude can't reach the hardware.

**Chassis scope:** lanes **21/22 = SS chassis + Omega-Tek retrofit**. The **Rev-D board is the fleet-common production revision; the harness + input populations are per-chassis.** Lanes 11/12 (Active-98 MP) need their own short field pass before their harness — see §10. Rev-B and Rev-C boards are not valid targets for the Rev-D firmware bundle.

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

## 0. Cold-start — what the Rev-D board is, and the non-negotiable safety model

- **One board per lane**, two identical boards on one Pi (independent I²C bus + RP2040 each). Develop/validate one, clone.
- **The board never sources machine power.** It only **opens/closes isolated dry contacts** in the existing machine control circuits. The S/T heavy-lug **contactors stay** and keep switching the 115 V motors and their OEM braking behavior; we only switch their **coil circuits** (all measured ~24 VAC).
- **The board is never the only safety device.** OEM service literature shows
  Stop + C.I.S. in parallel, but installed lanes 21/22 have no C.I.S. Their
  existing Stop/master-control-power path stays live and upstream. Before
  cutover, identify any other pit-entry interlock and obtain the qualified
  install-versus-Stop+LOTO-only disposition. The upstream disconnect—not the
  board rail—must remain capable of stopping a welded downstream contact.
- **The safety system** gates motion through five on-board rail conditions plus the OEM TB/SC coil-ladder condition. Any false → motion permission drops; none is bypassable by normal Pi software:

  | condition | source | fail-safe default |
  |---|---|---|
  | Watchdog OK | NE555 monostable, Pi kicks GPIO 12 (<~10 s) | false |
  | Arm OK | Pi arm GPIO (asserts only after operator-safe state / First-Ball-Zero) | false |
  | RP2040 OK | RP2040 heartbeat/permission | false |
  | Cam-stop OK | RP2040 immediate cam-edge drop path | false on fault |
  | TB/SC interlock OK | **DELEGATED to the OEM ladder (Candidate C, decided 2026-07-07)** — J_SAFE1-2 carries the engineered jumper plug; protection = the SC/TB parallel-safe contacts in the S/T coil circuits, re-proven per lane at Stage-6b/G3. See §3.4 + `phase8_interlock_redesign.md` §7 + `phase8_lane21_harness_build_sheet.md` §2 | enforced in the machine's coil circuit, not on the rail |
  | Stop/control-power OK | approved external energize-to-prove interface on J_SAFE3–4; actual Stop remains upstream | open/false |

- **Cam-stops are now SOLELY the RP2040's job.** Bench work (JOB-2) found the OEM machine uses **logic stops** (triac board), not hardwired cam-in-series — so removing the Omega-Tek board removes the existing cam-stop. The RP2040 hardware cam-stop **replaces** it. This is why the RP2040 cam-stop must be bench-proven (spec §12.9) *before* this cutover, and why the §6 Stage-6b cam-stop drop test is a hard gate.

**Reads-with:** `phase8b_pcb_revB_spec.md` (base electrical contract + §12.9 bench sequence), `phase8_revD_remediation_spec_2026-07-21.md`, `phase8_revD_readiness_checklist.md`, `phase8_revD_first_article_pack.md`, `phase8_interlock_redesign.md`, `phase8_channel_allocation.md` (channel→pin map), `phase8_C1_C2A_pinout_p288.md` + `phase8_bench_session1_FINDINGS.md` (machine-side cavities), `phase8b_at_machine_fieldsheet.md`, `phase8_trackA_golive_runbook.md`, and `phase_8a_infrastructure_plan.md`.

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

### Hardware / firmware (all are hard NO-GO gates)
- [ ] **Rev-D board ordered only from the current r7 package** (`kicad/fab_revD_2026-07-26_r8/`) after G7/G8/G13/G14, vendor-preview, BOM/substitution, and first-article prerequisites pass; then assembled with all DNP parts held out unless explicitly released. ⚠️ r7 is the **r6 input-protection** build (391 parts / 68 DNP / 323 placed / 306 JLC / 17 hand-solder, 250 × 240 mm). Every earlier rev-D package — including `_r5/` — has **bare opto inputs** with no `Dser`/`Dclamp` and must never be uploaded.
- [ ] **Release artifact custody passes before any flash:** run `firmware/rp2040/release.ps1 -VerifyOnly`; require `supported_board_revisions` to equal exactly `["revD"]` and `qualified_releases` to equal exactly `["revD|rel-0c746b5747143b8011b01d43|05d808411db4bb0d"]`; provision those as `WSL_RP2040_SUPPORTED_BOARD_REVISIONS=revD` and the exact `WSL_RP2040_QUALIFIED_RELEASES` tuple (independent build/config lists must not authorize a cross-product); verify production UF2 SHA-256 `d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae`; verify the physical board is marked/read as Rev-D. Never flash this bundle on Rev-B/Rev-C. Never deploy the `_FI1.uf2` bench image.
- [ ] **Cam polarity captured and a new controlled Rev-D-only production bundle generated.** The committed v1.2.3 image has `CAM_*_STOP_ENABLED=0` and unconfirmed `CAM_*_TRIP='?'`; do not treat its valid signature as cutover readiness. Capture §3.2, enable only proven cams, rebuild through `release.ps1`, record the new manifest/UF2 hashes, and bench-prove cam edge → rail drop independently of the Pi.
- [ ] **Unit #1 fully first-article + bench validated off-machine** per `phase8_revD_first_article_pack.md`, `phase8_revD_readiness_checklist.md`, and the base `phase8b_pcb_revB_spec.md` §12.9 sequence: power rails → I²C enumerate (3× MCP23017) → pull-register readback → Rev-ID → RP2040 boot/identity/heartbeat → watchdog drop → arm drop → each relay contact with dummy load → input front-ends/margins → **enabled cam-stop rail drop** → only then machine-harness test.
- [ ] **Spare unit #2** assembled (rapid swap if #1 fails on-site).
- [ ] **Gripper front-end confirmed for chassis-referenced returns** (queued board item): JOB-3 found grippers are **chassis-return, gripped = CLOSED to ground** (not the TAC-GND bus the OEM 9800-MP schematic assumed). Confirm the opto-input front-end handles a chassis-referenced return before cutover. Likely fine (still contact-to-a-reference); does not change isolation domains.

### Software / server (mostly already live from Track-A)
- [ ] WSL-SRV `lane_node_server.py` running 24/7 (ports 8765 WS + 8766 HTTP), auto-restart configured.
- [ ] Pi node `lane-node.service` pointed at `ws://192.168.4.103:8765`, **`systemctl enable`d** (the "lane goes dark after a power event" trap — provisioning runbook). *(IP per the 2026-06-03 eero re-IP; old `192.168.86.36` is dead.)*
- [ ] `lane_node/controller_io.py` `MachineIO` map matches the Rev-D contract (3× MCP23017 @ 0x20/0x21/0x22 + RP2040 UART link).
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

### 3.4 TB/SC hardware interlock → J_SAFETY landing — ✅ RESOLVED 2026-07-07 = CANDIDATE C (jumper + gates)
- **DECISION FORMAL (Dylan, 2026-07-07 — `phase8_interlock_redesign.md` §7):** J_SAFE1-2 (TBSC loop) gets a **documented, labeled JUMPER PLUG as an engineered harness part**; the rail's TB/SC condition is **formally delegated to the OEM ladder**. Premise **proven at the machine 2026-07-07** (§4-RESULTS): with both SC/TB cam levers held **BACK** (the danger state), the ladder alone kills **both** S and T motor-contactor coils even on a brain-independent manual command — SC+TB act as a **parallel closed-when-SAFE pair**. Build + verbatim label text: **`phase8_lane21_harness_build_sheet.md` §2**; insertion-point rules for the S/T taps (do NOT bypass the ladder): build sheet §3.2.
- **Measured 2026-06-27 (this machine), unchanged:** no isolatable dry NC pair exists — SC reads only on its **N.O. (pink)** wire at the shared node (**TSG-1 = C2A-U**, also a common rail); **TB has no standalone cavity**. ⛔ Never land J_SAFE1/2 into the ladder — that ties the board's VCC5 dry-sense loop into a live 24 VAC node. Cold continuity in this region stays invalid (~21 Ω coil sneak paths).
- **Standing conditions of the decision (hard):** ① the **per-lane Stage-6b/G3 machine-side coil-drop proof every cutover** — board commands S (then T), body clear, force both levers BACK → **coil must die even with the board contact closed**; a failure = the insertion bypassed the interlock = G3 FAIL → abort/rollback. ② **§4.3 window-angle capture** at the powered session. ③ The firmware SC∧TB echo is **default-off, secondary, and unvalidated** because this harness has no independent TB observation; the SC (J3-3) sense lead stays CUT+LABEL-ONLY unless a separately reviewed observe-only design is released after F.5 step 4 classes the node.
- Still true: this is a **first-class rail condition** — under Candidate C it is enforced **in machine hardware (the OEM ladder)**, verified per lane at G3, not by firmware.

### 3.5 Stop/control-power and pit-entry protection — OPEN/P0
- Record the installed devices. Lanes 21/22 have **no C.I.S.**; C.I.S. is N/A,
  not passed. Determine whether another pit-entry interlock exists. If none
  exists, the owner and a qualified machine-safety reviewer must approve either
  an upstream pit-entry safety disconnect or the existing Stop-plus-lockout-only
  operating design before this cutover can be scheduled.
- Confirm Stop in RUN versus STOP: STOP must remove master/control power within
  the approved bound. Preserve that upstream path.
- J_SAFE3–4 remains OPEN until an approved, measured, galvanically isolated
  energize-to-prove interface is installed. The leading candidate is a
  correctly rated control-power sensing relay with a N.O. volt-free contact on
  J_SAFE3–4. Its drawing and proof must include de-energize/open-wire behavior
  and a deliberate coil-off test that detects a welded/stuck sensing contact.
- A new pit switch placed only at J14 is not a final safety disconnect. If an
  installed/new pit interlock is credited for personnel protection, it acts
  upstream and receives its own demand→power-drop proof.

### 3.6 M1 ball-return existence check
- Confirm whether ball-return is a **separate command** on this chassis. If yes → it requires a future reviewed population change; **for this cutover M1 stays DNP and unharnessed** (FSM doesn't drive it).

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
| | SC, TB | SC/U = CUT+LABEL-ONLY pending reviewed observe-only input; TB = NO-LEAD (no independent cavity) | **do not feed J_SAFETY**; Candidate C uses only the controlled J_SAFE1-2 jumper and the OEM ladder |
| | DIELL-L, DIELL-R | DIELL sensor leads | NPN open-collector, **idle HIGH ~13–17 V, broken LOW ~0 V**; 10 kΩ pull-up to +12 V |
| **J_SLOW_IN_A** | GS1–GS10 | C2A 4-bank ≈41C…410U — **per-GS# CAPTURE §3.1** | dry contact, **gripped = CLOSED to chassis** (chassis return) |
| | GP, OS, BS | C2A (GP≈412DD, BS≈112cc) — confirm §3 | dry contact |
| **J_SLOW_IN_B** | PBZ, PBC | C2A ≈21EE area — confirm §3 | momentary dry |
| | Foul (Radaray) | foul detector lead | edge; confirm form |
| | 10th / manual T/S/SWS/SWSR | spare (future) | — |
| **J_LAMP_LED** | L_FIRST/SECOND/STRIKE/FOUL | **our LEDs in the mask housings** | 5 V logic via low-side FET; **machine 15 VDC mask supply abandoned** |
| **J_SAFETY** | TB/SC loop (J_SAFE1-2) | **RESOLVED = Candidate C (2026-07-07): engineered labeled jumper plug — no machine landing; protection delegated to the OEM ladder, proven per lane at Stage-6b/G3 — see §3.4 + `phase8_lane21_harness_build_sheet.md` §2** | jumper closed; rail condition delegated to the machine's coil circuit |
| | Stop/control-power source (J_SAFE3–4) | **OPEN/P0** pending approved interface and §3.5/FA-13 proof | never jumper at machine |
| **J_PI** | I²C bus, UART(↔RP2040), WDOG-kick GPIO12, ARM, INT | Pi 40-pin | per-board bus (board-22 on i2c-gpio) |
| **J_PWR** | 5 V logic, isolated field-wetting, 12 V DIELL | enclosure supplies | RPP + transient protection on input |

---

## 5. Pre-cutover prep (bench, 1–2 days before)

1. **Dry-run the whole §6 run-of-show on the bench** with the spare/off machine or a jumpered fixture — including every safety-drop test (Stage 6b) and the rollback. Don't first-run any step in production.
2. **Print the kit:** this doc §3 onward, the harness map §4, the Appendix-B worksheets (blank), spec §12.9 bench steps, and the OEM-brain in-place photos.
3. **Pack:** cutover enclosure (Pi + both Rev-D boards + supplies, assembled), **spare unit #2**, multimeter, wire strippers + small flat-blade + torque driver set for the applicable Phoenix terminal (**0.22–0.25 Nm for the MC 1,5 harness plugs; never the retired ~0.5 Nm figure**), Sharpie + tape + pre-printed terminal labels, headlamp, bowling ball, phone (photos + AnyDesk), laptop (this doc + bench log + verified release manifest, charged).
4. **WSL-SRV pre-checks (AnyDesk):** `curl http://192.168.4.103:8766/api/health` OK; `lane_state.db` clean of bench state; firewall 8765/8766 open; no pending Windows updates that could reboot mid-window.

---

## 6. Cutover window — run-of-show (staged, rail-disabled first)

**Time:** budget ~2–3 h for the first pair (capture + landing + staged bring-up). Off-hours, lanes closed, desk notified. Subsequent pairs are faster once the procedure is debugged on #1.

### Stage 0 — Arrival + photos (10 min)
Verify 21+22 out of service. **Photograph the OEM brain as-found** (Omega-Tek board, triac driver bank, every connector + terminal block, the C1/C2A faces with the "01"/AMP pin-1 datum). Ping the Pi node; confirm it registers at the server.

### Stage 1 — LOCKOUT (5 min)
Master breaker **OFF**, **tag it**, wait 30 s for discharge, **verify 0 V** across the coil circuits on C1/C2A (the 24 VAC coil rail can hold charge). You are now in mode A for everything through Stage 6.

### Stage 2 — Field capture §3 (45–60 min)
Work §3.1–§3.7. Fill Appendix-B worksheets. Record the lane-21/22 no-C.I.S.
finding, identify any other pit-entry interlock, and close the qualified
disposition in §3.5; this is not a deferrable observation. This is most of the
window and it is cold/hand-actuated except for the separately guarded demand
proofs.

### Stage 3 — Install our mask LEDs (10 min)
Fit the L_FIRST/SECOND/STRIKE/FOUL LEDs into the mask housings, run J_LAMP_LED (5 V, GND, 4 returns). **Leave the OEM 15 VDC mask-lamp wiring physically intact** (lift, don't cut) so rollback is clean.

### Stage 4 — Disconnect the OEM brain (15 min)
**Unplug** the Omega-Tek board + triac driver bank + their connectors. **Do not cut anything.** Bag/label each OEM connector. Keep the OEM brain on a shelf at the cabinet — it is your rollback.

### Stage 5 — Land the adapter harness (30 min)
One connector group at a time, **double-checking each against the §4 map**,
lift-and-land, torque, tug-test, photograph: J_MOTION_OUT → C1/C2A coil
circuits · J_FAST_IN → cams + DIELL · J_SLOW_IN_A/B → grippers/switches ·
J_SAFE1-2 → the exact Candidate-C keyed/labeled jumper only · J_SAFE3-4 → the
already approved and bench-proved Stop/control-power interface from §3.5 ·
J_LAMP_LED → mask LEDs · J_PI → Pi · J_PWR → supplies. If the §3.5 interface
or pit-interlock disposition is still open, **do not start Stage 5**. Final
visual pass: every board terminal vs the map. Catch swaps **now**.

### Stage 6 — Logic-only bring-up (rail DISABLED, no motion possible) (20 min)
**Master breaker still OFF; power LOGIC only (5 V).**
1. Pi boots, connects to server. **I²C enumerates all 3 MCP23017** per board and input pull registers command/read back `0x00`. **RP2040 boots + emits identity + heartbeats** — require `pcb:"revD"`, a release-allowlisted `build`/`cfg`, `fi1:0`, then `hb … ok:1` at ~4 Hz. The board has **no on-board status LEDs** — D-refdes parts are flyback/snubber/protection devices, not indicators. Verify **GP2/`RP2040_OK` HIGH**, measurable **NE555 watchdog output**, and **5 V at J_PWR** per the bench contract. **All relays default OPEN; rail DISABLED** (arm de-asserted).
2. **Read inputs (still no motion):** lift a pin → a GS channel flips; hand-rotate a cam → fast input + (when armed) cam-stop path; break a DIELL beam → ball input; trip foul. Confirm the live feed reads each — this also verifies §3 captures.
3. **⭐ SAFETY-DROP TESTS (the heart of the cutover):** with the rail's enable simulated/armed on the bench-safe path, prove **each** condition independently drops the rail:
   - stop the watchdog kick → rail drops
   - de-assert arm → rail drops
   - reset/halt the RP2040 → rail drops
   - trigger each enabled cam-stop edge → rail drops. **The committed v1.2.3 release does not satisfy this gate:** its enforcement flags are OFF and polarities are unconfirmed. Capture §3.2 first, generate and verify a new Rev-D-only controlled release with only measured cams enabled, then prove each cam on the bench and again here. A valid hash/manifest without enabled, measured cam enforcement is still G3 FAIL.
   - TB/SC interlock → **coil-drop proof (Candidate C form — the landed design as of 2026-07-07, `phase8_interlock_redesign.md` §7).** J_SAFE1-2 carries the *documented, labeled* engineered jumper (build sheet §2), so a rail-drop test is meaningless for this condition — the proof moves to the MACHINE side: **force SC/TB into the danger state (both cam levers held BACK) while the board commands S → the S-contactor COIL must read dead even with the board contact closed; repeat for T.** A coil that energizes = the §3.3 insertion bypassed the ladder → G3 FAIL, lift the feed-side tap, re-select, re-prove (build sheet §3.2). ⛔ Any OTHER J_SAFE jumper remains FORBIDDEN — the §2 engineered part on 1-2 is the sole exception; never jumper 3-4, never bridge 1→4.
   - demand Stop → master/control power and TP16 both drop within the approved
     bounds; deliberately de-energize the sensing-relay coil/open its proof path
     and require J_SAFE3–4/TP16 to open. On lanes 21/22 record C.I.S. absent/N/A.
     Demand-test every actually installed/new upstream pit interlock separately.
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
| **G1** | before scheduling | Rev-D first article + spec §12.9 bench sequence + FA-13/FA-14 passed · physical Rev-ID and exact release manifest/UF2 verified · measured cam enforcement enabled/proven · signed per-lane Stop/pit-interlock/PE commissioning evidence accepted by the operations latch, bound to exact lane/Pico/board/harness identity, with a matching controller-originated live observation **≤90 s old** and proof age **≤365 days** · Track-A scoring soaked clean · spare on hand · OEM brain photographed | don't schedule |
| **G2** | after Stage 2 | all §3 field items captured; harness map §4 complete; lane-21/22 no-C.I.S. and pit-entry disposition recorded; approved J_SAFE3–4 interface complete; no surprises vs measured cavities | resolve or defer only non-safety items; any safety/interface ambiguity aborts |
| **G3** | Stage 6b | watchdog, arm, RP2040, every enabled cam-stop, and the approved Stop/control-power interface each independently drop the rail · Stop drops upstream master/control power and TP16 · every installed/new upstream pit interlock passes separately · TB/SC is proven at the MACHINE side by forcing both levers BACK while the board commands S and then T; both coils must be dead · J_SAFE1-2 contains only the controlled Candidate-C keyed/labeled jumper; any other bridge or an energized coil is FAIL | **ABORT → rollback** |
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
2. **Lift the adapter harness** from C1/C2A/TB/SC and the J_SAFE3–4
   Stop/control-power interface (use the tape labels; lift, don't cut). Leave
   every upstream Stop/pit safety device intact.
3. **Re-plug the OEM Omega-Tek board + triac driver bank + connectors** (preserved from Stage 4).
4. Mask LEDs (J_LAMP_LED) can stay unpowered (harmless); the OEM 15 VDC mask wiring was left intact, so OEM lamps work on re-plug.
5. **Master breaker ON.** OEM controller runs the machine. **Bowl a frame on each lane** to confirm normal operation.
6. Leave the Rev-D enclosure powered down + in place (harmless); take the unit home to debug.
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

The **board is fleet-common; the harness + input populations are per-chassis-type.**
Before cutting over **11/12 (Active-98 MP)**, run a short field pass for A1 working
voltage, A4 input forms, the C-series harness map, and the TB/SC observable +
S/T-insertion facts. Do not assume an independently landable TB/SC pair exists or
copy lane 21/22's Candidate-C evidence without that lane's powered proof. Clone the
*board*; re-capture and G3-prove the *harness*.

---

## 11. Where this sits in the sequence

Upstream of this runbook (must finish first): Rev-D R5 **package/hash verification → G7/G8/G13/G14 + vendor upload preview → fab order → assemble with DNP parts held out → first-article qualification → measured cam-polarity capture → new controlled Rev-D-only firmware bundle → daemon/firmware bench bring-up → full board validation.** The cutover is scheduled only after all of those are green. There is no external deadline — the Phase-8 thesis is "do it once, do it right." A bad first controller cutover poisons the soak and the per-chassis rollout.

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
**B.4 Safety + signed commissioning evidence (§3.4/§3.5, FA-13/FA-14)** —
one complete block per lane; attach procedure sheets, meter/tester output, and
photos rather than reducing a failed or ambiguous result to a checked box:
```
Lane __  Pico UID __  board rev/serial __  harness rev/serial __
Candidate-C J_SAFE1-2 keyed/labeled jumper verified __
OEM S/T ladder still in series / not bypassed __
G3 S: board commands S + both levers BACK/open -> S coil dead: result __ evidence __
G3 T: board commands T + both levers BACK/open -> T coil dead: result __ evidence __
C.I.S. installed? NO/N/A on lanes 21/22 __  other pit interlock found __
Pit-interlock install-vs-Stop+LOTO disposition / approver __
J14.3-4 isolated control-power interface drawing + relay ID __
Stop request observed __  master/control-power drop __ ms (limit __ ms; PASS/FAIL __)
Stop -> TP16 drop __ ms (limit __ ms; PASS/FAIL __)
Monitor open-wire tests __  control-power proof-path coil-off test __
Installed/new upstream pit-interlock demand result, if applicable __
PE continuity/bonding: tester ID __ calibration due __ result __ limit __
Hot/neutral polarity: tester ID __ calibration due __ result __
FA-13/FA-14 tested UTC __  retest due UTC __ (must be <=365 days)
Controller-originated live identity __  observed UTC __  age __ s (must be <=90)
Exact live lane/Pico/board/harness match PASS/FAIL __
Signed commissioning record ID __  signer/date __
```
**B.5 Switches** — PBZ __ · PBC __ · GP __ · OS __ · BS __ · Foul form __
