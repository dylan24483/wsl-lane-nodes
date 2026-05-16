# Phase 8a Cutover Plan — Lanes 21+22

**Status:** draft 2026-05-15 (boards in fab). Will be refined after unit #1 bench validation (~2026-05-25 to 05-26).
**Goal:** replace the QubicaAMF retrofit stack (BCU II + QBK-SIx + T-VISION + VDB-99) at lanes 21+22 with a single Raspberry Pi node running `lane_node.py`. After cutover, scoring + pinsetter control + foul detection at the pair come from the Pi, not from the QubicaAMF chain.
**Window:** off-hours, ~60-90 minutes for the first pair (~30 min for each pair after the procedure is debugged on #1). Plan for a weekday close-night.
**Rollback budget:** ~15 minutes if needed — every move is non-destructive (wires get lifted from one terminal and landed on another; no cuts, no crimps until unit is soaked clean).

This plan is the run-of-show. It assumes the **infrastructure plan** (`docs/phase_8a_infrastructure_plan.md`) is already executed — Cat6 in place, PoE+ switch live, DIN-rail enclosure mounted near the 8270 cabinet, 5V supply wired.

---

## 1. Prerequisites (must be 100% done before scheduling the cutover window)

### Hardware on hand and bench-validated

- [ ] Phase 8a PCB unit #1 (NE555 watchdog + 4-channel AC interposer), bench-validated per `docs/pcb_design_spec.md` Section 10 — all 6 steps passing (power-only, reverse-polarity, watchdog idle, watchdog kick, AC interposer, full integration)
- [ ] Raspberry Pi 4 with `lane_node.py` running clean for ≥24 hours on the bench against the WSL-SRV server
- [ ] AEDIKO 8-channel relay HAT, IN1-IN4 wired to Pi GPIO 23/24/25/27 (cycle+power × 2 lanes)
- [ ] AL-ZARD DST-1R8P-P 8-channel opto-input, O1-O4 wired to Pi GPIO 17/22/5/6 (foul+2nd-ball × 2 lanes)
- [ ] All four K-mitigations confirmed running: SIGTERM handler + try/finally + systemd ExecStopPost + hardware watchdog kick on GPIO 12
- [ ] DIN-rail enclosure assembled with all modules mounted, fused 5V power-in, Phoenix terminals labeled per the channel map below
- [ ] Spare unit #2 (assembled but not yet bench-validated) — for rapid swap if unit #1 fails during cutover
- [ ] 18AWG hookup wire, wire stripper, small flat-blade screwdriver for Phoenix terminals, multimeter, headlamp

### Software / server

- [ ] WSL-SRV running `server/lane_node_server.py` 24/7 (per `docs/deploy_server_to_wsl_srv.md`). Auto-restart via Task Scheduler or NSSM (no longer manual launch).
- [ ] WSL-SRV firewall allows inbound 8765 (WS) + 8766 (HTTP) from the lane subnet
- [ ] `lane_node.py` on the cutover Pi pointed at `ws://192.168.86.36:8765` via `WSL_LANE_SERVER_URL` env var in systemd unit
- [ ] `lane_state.db` on WSL-SRV is clean (no stale state from bench testing — `python server/state_store.py clear` before cutover)
- [ ] Desk staff trained: opening/closing lanes 21+22 will now use whatever desk surface controls Phase 8 (TBD — for cutover #1, the desk simulator at `http://192.168.86.36:8766/` is the operator interface; long-term, integrate into `desk.html`)

### Lane 22 + 21 site state confirmed (from `docs/lane_visit_checklist.md` findings, 2026-05-06)

- [x] QBK-SIx J1 = lane 21 (CYL/PWER outputs + FOL/2ND inputs)
- [x] QBK-SIx J2 = lane 22 (same signal set)
- [x] FOL + 2ND inputs are 24-32V RMS AC at 60Hz → AC interposer required ✓ on Phase 8a PCB
- [x] DIELL LSC/AN-2C6J sensors confirmed NPN open-collector — idle HIGH ~13-17V, active LOW ~0V
- [x] Sweep reverse works without C-1 jumper mod (picker-table operation handles it)
- [x] J3 L-COM bus is irrelevant — Phase 8 retires T-VISION + BCU II entirely

### Decisions locked (2026-05-15)

- **DIELL ball-detect: INCLUDED.** All 4 sensors (2 per lane) wired to DONGKER opto-input channels 5-8, into Pi GPIO 13/16/19/20. DIELL Vcc supplied by a new 12V 1A wall adapter (replacing T-VISION's internal supply, which goes away when T-VISION retires). 10kΩ external pull-up to +12V on each signal line (replacing T-VISION's internal pull-up).
- **Scoring mode: `manual`.** Lane Pi runs with `WSL_LANE_SCORING_MODE=manual` until T-Camera is bench-calibrated. DIELL fires `BALL_EVENT` to the server with `pin_mask=null`; server cycles the pinsetter but does NOT auto-score. Desk operator enters pin count via `POST /api/lane/<N>/score` body `{pin_mask, foul?}` on the new score endpoint (NOT `/trigger-ball`, which is bench-only and would double-pulse the pinsetter). T-Camera follow-up visit moves the mode to `camera` once `PIN_SPOTS` is calibrated against real frames.
- **QBK-SIx fate: full disassembly during cutover.** QBK-SIx + BCU II + T-VISION-98 + VDB-99 all come out during the cutover window. Adds ~30-45 min to the run-of-show but eliminates the cleanup-visit follow-up. Before lifting T-VISION's connections, the new 12V supply must be wired and powered (T-VISION currently supplies DIELL Vcc).
- **Customer display: HDMI from Beelink thin client → existing overhead monitor.** Beelink runs Chromium in kiosk mode pointed at `http://192.168.86.36:8766/display?lane=21&mode=league`. Display is served by `lane_node_server.py` on port 8766 (NOT `wsl_api.py` on port 5000 — port 5000's scoring is for non-Phase-8 lanes and doesn't see Pi events). The display polls `/api/lane/<N>/scoring` on the same origin, which lane_node_server.py answers with the cross-lane scoring response for that lane.

### Still-open question (resolve during site survey visit #1)

- [ ] **Foul-lamp drive verification.** With QBK-SIx fully de-powered, does the lane 21/22 foul lamp still illuminate when the foul beam is broken? Phase 8a expects "yes" — the lamp is wired upstream of QBK-SIx and the 8270's own foul-beam logic lights it. If the answer is "no" (lamp depends on QBK-SIx to drive it), reserve a 5th NOYITO relay channel during cutover to drive the lamp from the Pi side. Multimeter check during the survey resolves this in ~2 minutes.

---

## 2. Channel mapping (the most important table)

**This is the wire-by-wire reference for cutover.** Print it. Tape it inside the enclosure door.

| Source (today) | Goes to (after cutover) | Function | Pi GPIO | Bench-validated |
|---|---|---|---|---|
| **Lane 21 (left of pair)** | | | | |
| QBK-SIx J1.1-J1.2 (CYL) | AEDIKO IN3 — Phoenix `R3` on enclosure | Lane 21 pinsetter cycle command | GPIO 24 | ✓ 05-06 |
| QBK-SIx J1.3-J1.4 (PWER) | AEDIKO IN4 — Phoenix `R4` | Lane 21 pinsetter power on/off | GPIO 25 | ✓ 05-06 |
| QBK-SIx J1.5-J1.6 (+FOL) | Phase 8a PCB J5 (24VAC IN CH2) → J9 (DC OUT CH2) → AL-ZARD input 3+/3- | Lane 21 foul lamp signal (AC) | GPIO 5 | ✓ 05-06 (bench DC + 05-11 with AC) |
| QBK-SIx J1.7-J1.8 (+2ND) | Phase 8a PCB J4 (24VAC IN CH1) → J8 (DC OUT CH1) → AL-ZARD input 4+/4- | Lane 21 2nd-ball lamp signal (AC) | GPIO 6 | ✓ 05-06 |
| DIELL L21 LEFT signal | DONGKER input 5+ (via 10kΩ pull-up to +12V), output O5 | Lane 21 ball-detect left beam | GPIO 13 | bench: button simulator |
| DIELL L21 RIGHT signal | DONGKER input 6+ (via 10kΩ pull-up to +12V), output O6 | Lane 21 ball-detect right beam | GPIO 16 | bench: button simulator |
| DIELL L21 +V supply | New 12V/1A wall adapter (replaces T-VISION supply) | DIELL Vcc | — | bench |
| **Lane 22 (right of pair)** | | | | |
| QBK-SIx J2.1-J2.2 (CYL) | AEDIKO IN1 — Phoenix `R1` | Lane 22 pinsetter cycle command | GPIO 27 | ✓ 05-06 |
| QBK-SIx J2.3-J2.4 (PWER) | AEDIKO IN2 — Phoenix `R2` | Lane 22 pinsetter power on/off | GPIO 23 | ✓ 05-06 |
| QBK-SIx J2.5-J2.6 (+FOL) | Phase 8a PCB J6 (24VAC IN CH3) → J10 (DC OUT CH3) → AL-ZARD input 1+/1- | Lane 22 foul lamp signal (AC) | GPIO 17 | ✓ 05-06 |
| QBK-SIx J2.7-J2.8 (+2ND) | Phase 8a PCB J7 (24VAC IN CH4) → J11 (DC OUT CH4) → AL-ZARD input 2+/2- | Lane 22 2nd-ball lamp signal (AC) | GPIO 22 | ✓ 05-06 |
| DIELL L22 LEFT signal | DONGKER input 7+ (via 10kΩ pull-up to +12V), output O7 | Lane 22 ball-detect left beam | GPIO 19 | bench: button simulator |
| DIELL L22 RIGHT signal | DONGKER input 8+ (via 10kΩ pull-up to +12V), output O8 | Lane 22 ball-detect right beam | GPIO 20 | bench: button simulator |
| DIELL L22 +V supply | Same 12V/1A adapter as L21 | DIELL Vcc | — | bench |

**Reminder:** these match the bench rig per the `project_phase8_bench_rig_validated` memory. Don't improvise channel assignments on-site — if the wire-label colors don't match the table above, re-trace the wires per the `lane_visit_checklist.md` Phase 1 procedure and update the table before proceeding.

---

## 3. Pre-cutover prep (done at home / on the bench, 1-2 days before cutover)

1. **Fully assemble the cutover enclosure.** All modules mounted on DIN rail, all internal wiring done, all Phoenix terminals labeled with the channel map above. Power-up test on the bench: Pi boots, connects to WSL-SRV, watchdog kicks, all 8 relays default OPEN.
2. **Dry-run cutover on the bench.** Use jumper wires to simulate the QBK-SIx outputs and lamp inputs. Run through every step of Section 4 below, including the rollback. Verify everything works in a controlled environment before doing it in production.
3. **Print the kit:**
   - This document (Section 4 onward, the run-of-show)
   - Channel mapping table above, large font
   - `docs/pcb_design_spec.md` Section 10 bench validation steps
   - QBK-SIx terminal photos from the 2026-05-06 visit (so we know what we're looking at)
4. **Pack the on-site kit:**
   - [ ] Cutover enclosure (Pi + PCB + AEDIKO + AL-ZARD + power supply, all assembled)
   - [ ] Spare unit #2 (rapid-swap if unit #1 fails on-site)
   - [ ] Multimeter
   - [ ] Wire strippers + small flat-blade screwdrivers
   - [ ] Sharpie + masking tape + pre-printed terminal labels
   - [ ] Headlamp (the equipment area is dim)
   - [ ] Bowling ball
   - [ ] Phone for on-site photos + AnyDesk-to-WSL-SRV
   - [ ] Laptop with this document, a charged battery, and an offline copy of the bench validation log
5. **WSL-SRV pre-checks** (via AnyDesk, day of):
   - `lane_node_server.py` running and healthy: `curl http://192.168.86.36:8766/api/health` returns OK
   - `lane_state.db` cleared: `python server\state_store.py clear`
   - Firewall confirmed open on 8765/8766
   - WSL-SRV doesn't have any pending Windows updates that might reboot mid-cutover (`Get-WindowsUpdate -IsPending` if PSWindowsUpdate installed)

---

## 4. Cutover window — run-of-show

**Time:** ~60-90 min for the first pair. Off-hours, lanes closed. Notify desk staff that lanes 21+22 are offline for the duration.

### Step 0 — Site arrival + photos (5 min)

1. Walk to the lane 21+22 equipment area. Verify both lanes are powered down and locked out from public use.
2. **Photograph the QubicaAMF stack as-found** — wide and close-up shots of BCU II, QBK-SIx, T-VISION, VDB-99. Capture every visible terminal block. If anything has changed since 2026-05-06, note it.
3. Take note of which Pi mDNS hostname this unit is (e.g., `lane-node-21-22.local`). Verify the laptop can ping it before plugging in any wires.

### Step 1 — Verify Phase 8a chain is live (5 min)

1. Mount the cutover enclosure in its planned spot (near the 8270 cabinet, per the infrastructure plan).
2. Connect Cat6 (PoE+ if applicable) to the enclosure. Pi boots.
3. Connect 5V supply input to enclosure (if not PoE-powered).
4. From the laptop: `ping lane-node-21-22.local` (or whatever hostname). Expect <2ms response.
5. From AnyDesk → WSL-SRV: tail `server/lane_node_server.py` log. Should show `Node 'lane-node-21-22' registered (lanes=[21, 22], protocol_version=2)`.
6. Open `http://192.168.86.36:8766/` in browser. Click **Power On** on lane 22. Watch for the Phoenix terminal labeled `R2` on the enclosure — its indicator LED should light briefly. **At this stage, R2 is NOT wired to the 8270 yet, so nothing physical happens — this just confirms the relay closes on command.**
7. Repeat for Power Off, then for each of R1, R3, R4. Each relay's indicator should light when commanded.
8. Click **Reset Pins** on each lane. The corresponding `R1` (lane 22 cycle) or `R3` (lane 21 cycle) relay should click 3 times in quick succession.
9. If any relay fails to click → **STOP. Do not proceed to wiring. Swap to unit #2 spare, or abort and reschedule.**

### Step 2 — Power down QubicaAMF stack (5 min)

1. Locate the AC plug feeding the QubicaAMF gear. Per the 2026-05-06 walk it's a single power strip behind the equipment area.
2. Unplug the strip. Verify all QubicaAMF gear LEDs go dark.
3. Wait 30 seconds for capacitor discharge.
4. Verify with multimeter (DC volts, 200V scale) that QBK-SIx J1 and J2 terminals show 0V across every pin pair. **Critical safety check** — the 24VAC lamp circuits have capacitive coupling that can hold charge.

### Step 3 — Lift wires from QBK-SIx, re-land on Phase 8a (~25 min, the meat of the cutover)

**Pace:** one channel at a time. Move ONE wire pair, double-check it landed on the right Phase 8a terminal, then move the next.

For each of the **8 wire pairs** on QBK-SIx J1 and J2:

1. **Photograph the terminal block close-up.** Wire color + position visible.
2. **Tag the wire with masking tape** noting the SOURCE (e.g., "L21 CYL +" / "L21 CYL -"). Use the channel-mapping table from Section 2.
3. **Loosen the QBK-SIx terminal screw**, release the wire. Don't cut.
4. **Land the wire on the Phase 8a destination terminal** per the channel map. Tighten the Phoenix screw (these need firm tightening but not gorilla-grip — 0.5 Nm if you have a torque screwdriver).
5. **Tug the wire gently** to verify it's clamped.
6. **Photograph the new termination.** Wire-label-on-tape visible in shot.

Order recommended (least to most risk):
1. L22 CYL (J2.1-J2.2) → AEDIKO R1
2. L22 PWER (J2.3-J2.4) → AEDIKO R2
3. L22 +FOL (J2.5-J2.6) → Phase 8a J6
4. L22 +2ND (J2.7-J2.8) → Phase 8a J7
5. L21 CYL (J1.1-J1.2) → AEDIKO R3
6. L21 PWER (J1.3-J1.4) → AEDIKO R4
7. L21 +FOL (J1.5-J1.6) → Phase 8a J5
8. L21 +2ND (J1.7-J1.8) → Phase 8a J4

Why lane 22 first: it's the one with the most bench validation history (2 of 8 channels of AL-ZARD were directly tested on it). Lane 21 inherits by induction.

After all 8 wire pairs are moved, **do a final visual pass** comparing each Phase 8a Phoenix terminal to the channel map. Catch any swaps now, not after power-up.

### Step 4 — First power-up smoke test (10 min)

1. Verify the Phase 8a enclosure is still powered (Pi green LED + AEDIKO/DONGKER power LEDs). Verify D7 (watchdog-healthy) and D8 (power-good) on the Phase 8a PCB are both lit.
2. **Do NOT plug the QubicaAMF strip back in.** (After the locked decision: the entire QubicaAMF stack is being removed during this cutover — strip should already be unplugged and units physically disconnected per Step 3.)
3. From the laptop browser at `http://192.168.86.36:8766/display?lane=21&mode=league`, the display should show both lanes "Closed" (no scoring state yet).
4. **Bootstrap test scoring state** so the display has bowlers to render. Two options depending on whether you want to simulate open bowling or league night:
   - Open bowling per lane (single-lane scoring):
     ```
     curl -X POST http://192.168.86.36:8766/api/lane/22/open -H "Content-Type: application/json" -d "{\"bowlers\": [\"TEST1\", \"TEST2\"]}"
     curl -X POST http://192.168.86.36:8766/api/lane/21/open -H "Content-Type: application/json" -d "{\"bowlers\": [\"TEST3\", \"TEST4\"]}"
     ```
   - Or league night (cross-lane scoring across both lanes):
     ```
     curl -X POST http://192.168.86.36:8766/api/pair/21-22/open-league -H "Content-Type: application/json" -d "{\"team1_bowlers\": [\"ALICE\", \"ANDREW\"], \"team2_bowlers\": [\"BARB\", \"BRIAN\"], \"team1_name\": \"HOOKS\", \"team2_name\": \"SPLITS\"}"
     ```
   Display should refresh and show the test bowlers within ~2 seconds. The cross-lane variant will mark "ALICE up" on lane 21 and "BARB up" on lane 22.
5. `curl -X POST http://192.168.86.36:8766/api/lane/22/power-on`. The 8270 should power up (audible click from the cabinet, motor energy noise).
6. From the lane 22 approach, **walk over the foul line** to break the foul beam. Lane Pi journal should log `GPIO: foul detected on lane 22` and emit FOUL_EVENT to the server.
7. `curl -X POST http://192.168.86.36:8766/api/lane/22/reset`. The pinsetter should cycle: lift, sweep, re-spot. Audible sweep motor.
8. **Roll a bowling ball down lane 22** (full rack standing). Two things should happen in order:
   - DIELL beams break → Pi journal logs `GPIO: ball detected on lane 22, mode=manual (awaiting desk score)` → server cycles the pinsetter (lift, sweep, re-spot)
   - The display does NOT auto-update (manual mode — awaiting desk score)
9. `curl -X POST http://192.168.86.36:8766/api/lane/22/score -H "Content-Type: application/json" -d "{\"pin_mask\": 0}"` (0 = strike, all pins down). Display should now show frame 1 with X for the bowler. **Foul-latch behavior:** if the foul was triggered in Step 6, the flag persists indefinitely until the next `/score` (no time-based expiration) and this ball will score as a foul. To clear a stale foul without applying it, post `{"pin_mask": 0, "foul": false}` — the explicit `foul: false` clears the pending flag before recording.
10. **Repeat steps 5-9 for lane 21.**
11. **If anything fails to behave correctly:** see Section 6 — Rollback. Don't troubleshoot live during the window; rollback and debug at home.

### Step 5 — Soak handoff (10 min)

1. **Power the 8270 back ON** on both lanes (already on if Step 4 worked, but verify).
2. Brief any night staff: "Lanes 21+22 are on the new Pi system tonight. The overhead monitor at the pair shows live scoring (driven by the Beelink at `http://192.168.86.36:8766/display?lane=21&mode=league`). For each ball customers throw, the pinsetter will cycle automatically — you'll need to **enter the pin count** at the desk via `POST http://192.168.86.36:8766/api/lane/<lane>/score` body `{\"pin_mask\": <int 0-1023>, \"foul\": <bool>}` (T-Camera not yet calibrated, so manual scoring during soak). If anything looks weird, take a photo and don't try to fix it — leave the lane closed and message Dylan."
3. Tape a printed "Phase 8a, contact Dylan" note inside the enclosure door so anyone who opens it sees the context.
4. Pack up. Leave the masking-tape wire labels on the wires for at least the first week of soak — easy reference if rollback is needed.
5. **Drive home.** Don't sit on-site debugging. The watchdog + WSL-SRV setup will tell you if anything goes sideways.

---

## 5. First-week soak monitoring

For the 7-10 days after cutover, check daily:

- **`curl http://192.168.86.36:8766/api/health`** — Pi connected, no recent disconnects, no excessive event counts
- **WSL-SRV journal / log** — any error lines from `lane_node_server.py`? Any `protocol mismatch` warnings? Any unusual disconnects?
- **Walk to lanes 21+22 once per day** during open hours. Watch a frame or two bowled by customers. Spot-check that scoring, foul, and reset all look right.
- **Pin detection state** — if T-Camera was wired during cutover, watch for false-negative strikes or stuck pin states.
- **Watchdog timeouts** in journal — should be zero. Any timeout = investigate (`docs/hardware_watchdog_design.md` calibration section).
- **Heat / vibration** in the enclosure — touch the Pi case and the watchdog PCB once per day for the first three days. Should be warm but not hot (>50°C — uncomfortable to touch sustained).

After 7-10 clean soak days: schedule the **cleanup visit** to physically remove QBK-SIx (it's been dead this whole time) and tidy wire routing. Then plan Phase 8b (next pair, e.g., lanes 19+20).

If the soak surfaces any issue that wasn't caught on the bench, **document it in `project_phase8a_first_cutover_lessons.md` memory** before starting Phase 8b. The whole point of Phase 8a being a single pair is that we learn from it.

---

## 6. Rollback

If Step 4 smoke test fails and the failure isn't immediately obvious + fixable (e.g., a single wire on the wrong terminal — that's fixable in <2 min, just move it and retry):

1. **Power down the Phase 8a enclosure** (unplug 5V or PoE).
2. **Reverse each wire move** from Step 3, taking advantage of the masking-tape labels:
   - For each wire pair: loosen the Phase 8a Phoenix terminal, lift the wire, land it back on its original QBK-SIx terminal per the photo + label.
   - Re-tighten QBK-SIx screws.
3. **Plug the QubicaAMF strip back in.** BCU II + T-VISION + VDB-99 + QBK-SIx all power up.
4. **Bowl a frame on each lane.** Confirm Conqueror-side scoring works. If yes: rollback complete, lanes are back to normal operation.
5. **Leave the Phase 8a enclosure powered down and in place** (it's now harmless — no wires going to/from it). Take it home for debugging.
6. **Document the failure mode:** what step failed, what was the observed behavior, what was the suspected cause. Add to a new memory `project_phase8a_cutover_attempt_1_failed.md` if more than a trivial wire-swap was needed.

**Time budget for rollback:** ~15 min. Faster than the cutover because there's no second-guessing the wire mapping — just reverse what was done.

---

## 7. Post-cutover follow-ups (separate visits, lower priority)

- **T-Camera + `pin_detect.py` calibration.** Wire the USB capture dongle into the lane Pi, tap the existing T-Camera composite signal, run a calibration session (bowl known pin states, measure pixel coordinates, set `PIN_SPOTS` and `STANDING_THRESHOLD`). Once auto-pin-detect works clean against real frames, flip `WSL_LANE_SCORING_MODE` from `manual` to `camera` and retire manual pin entry at the desk.
- **Update operator documentation.** Once Phase 8a is soaked clean, write the staff-facing "operating lanes 21+22 on Phase 8" guide. Likely lives in the wsl-systems repo as user-facing doc.
- **Phase 8b kickoff.** Replicate to the next pair (lanes 19+20). The infrastructure already exists (Cat6 + PoE+ switch); per-pair install is roughly enclosure mount + wire moves + ~1h.

(QBK-SIx/BCU II/T-VISION/VDB-99 removal is no longer a follow-up — full disassembly happens during the cutover window itself per the locked decision in Section 1.)

---

## 8. Schedule

Earliest possible cutover, gated by:

1. Boards arrive from JLCPCB: ~2026-05-22 to 05-24
2. Hand-solder unit #1 + bench validate: ~2026-05-25 to 05-26
3. Hand-solder unit #2 (spare) + dry-run rehearsal: ~2026-05-26 to 05-27
4. Resolve open questions (Section 1 list): ~2026-05-26 to 05-28
5. **Cutover window: target 2026-05-28 to 05-29 evening** (Thursday/Friday close, gives a weekend of soak before busy weekday traffic)
6. First-week soak: 2026-05-29 to 2026-06-05
7. If clean: Phase 8b begin (next pair) ~2026-06-13+

Slippage tolerance: if any prerequisite isn't met, push the cutover by a week. There's no external deadline forcing this — the Phase 8a thesis is "do it once, do it right." A bad first cutover ruins the soak and delays Phase 8b by months.

---

## Appendix A — On-call posture during the window

Phone notifications on. Laptop with AnyDesk + this doc + the bench validation log open. Spare laptop battery charged. If solo on-site, brief one trusted staff member that lanes 21+22 are in maintenance and to call only if there's a safety issue (sparks, smoke, smell). Avoid posting on chat channels during the cutover — focus on the work; debrief after.

## Appendix B — Symbols Dylan uses in the field

To match the bench logbook style if recording readings:

- `^` = ascending (relay closed, lamp lit, voltage rising)
- `v` = descending (relay open, lamp dark)
- `~` = transient / oscillating (probably AC if seen on a DC multimeter)
- `=` = stable reading
- `?` = unsure / need to recheck

E.g., bench log entry: `L22.FOL idle =0V, asserted ^28VAC, latency ~20ms.`
