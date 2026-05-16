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

### Open questions to resolve before scheduling (DO NOT skip this list)

- [ ] **DIELL sensor wiring in Phase 8a.** Bench rig has not yet wired DIELL sensors to AL-ZARD inputs 5-8. Two options:
  - **Option A (recommended for cutover #1):** ship Phase 8a WITHOUT DIELL ball detection. Use T-Camera + `pin_detect.py` as the sole ball-detect source (frame-to-frame pin-mask delta = ball event). Defers DIELL wiring to a follow-up visit. **Caveat:** T-Camera not yet on bench, `PIN_SPOTS` not calibrated. Cutover #1 may have to ship without any ball detection and use foul + 2nd-ball lamp signals only as scoring triggers. Need to decide: is that good enough for a one-week soak? Probably yes — the lamp signals already drive scoring on most legacy 8270 setups.
  - **Option B:** wire DIELL sensors as part of the cutover. Adds ~20 min on-site. Requires DIELL +V supply tap (12-24V) — where does that come from? T-VISION today supplies the DIELL Vcc (~17V). If we retire T-VISION, we need an alternate Vcc. Bench supply or a tap off the AEDIKO 24V coil supply? Resolve before site visit.
- [ ] **QBK-SIx fate during cutover.** Two paths:
  - **Path 1 (recommended):** leave QBK-SIx physically installed but disconnected from its outputs. Lift the wires from QBK-SIx J1.CYL/J1.PWER + J2.CYL/J2.PWER and re-land them on AEDIKO relay terminals. QBK-SIx is now dead but still in place — can be removed in a future visit. Risk: BCU II/T-VISION may scream about missing QBK-SIx; cut power to BCU II + T-VISION to silence.
  - **Path 2:** physically remove QBK-SIx during cutover. Cleaner end state but adds disassembly time and risk of mis-wiring elsewhere. Defer to a follow-up "cleanup visit" 1-2 weeks post-soak.
  - Decision: Path 1 for cutover. QBK-SIx stays in place, powered off (BCU II + T-VISION power cut).
- [ ] **What drives the scoring display?** Today VDB-99 drives the overhead score monitor. After cutover, the monitor must show scores from `lane_node.py` → WSL-SRV → … → display. Phase 8a includes a browser display at `http://192.168.86.36:8766/` that can be opened on a tablet or the existing overhead monitor's HDMI input. **Verify:** does the lane 21+22 overhead monitor have HDMI input (not just VGA from VDB-99)? If HDMI: route a long HDMI cable from a Pi (could be a second Pi — "display Pi" — in the network closet, OR a Chromecast / Fire TV stick into the HDMI port, OR the lane Pi itself driving HDMI out). For cutover #1, simplest is: small tablet/laptop on the desk showing the browser display.
- [ ] **Foul-lamp side-effect.** Today, when foul is detected, QBK-SIx illuminates the foul lamp. After cutover, who illuminates the foul lamp? If the foul lamp wiring is upstream of QBK-SIx (i.e., the 8270's foul beam triggers the lamp directly), then Phase 8 sees the lamp via AC interposer and the lamp continues to light itself. If QBK-SIx is what lights the lamp (less likely but possible), we need to handle that. **Verify on-site:** with QBK-SIx fully de-powered, does the foul lamp still light when the beam is broken? If yes → Phase 8 just observes; if no → Phase 8 needs to drive a fifth AEDIKO relay channel to light the lamp.

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
| DIELL sensor pair (lane 21) | (deferred per "open question" above) | Ball-detect / pin-clearing | TBD | not yet wired on bench |
| **Lane 22 (right of pair)** | | | | |
| QBK-SIx J2.1-J2.2 (CYL) | AEDIKO IN1 — Phoenix `R1` | Lane 22 pinsetter cycle command | GPIO 27 | ✓ 05-06 |
| QBK-SIx J2.3-J2.4 (PWER) | AEDIKO IN2 — Phoenix `R2` | Lane 22 pinsetter power on/off | GPIO 23 | ✓ 05-06 |
| QBK-SIx J2.5-J2.6 (+FOL) | Phase 8a PCB J6 (24VAC IN CH3) → J10 (DC OUT CH3) → AL-ZARD input 1+/1- | Lane 22 foul lamp signal (AC) | GPIO 17 | ✓ 05-06 |
| QBK-SIx J2.7-J2.8 (+2ND) | Phase 8a PCB J7 (24VAC IN CH4) → J11 (DC OUT CH4) → AL-ZARD input 2+/2- | Lane 22 2nd-ball lamp signal (AC) | GPIO 22 | ✓ 05-06 |
| DIELL sensor pair (lane 22) | (deferred per "open question" above) | Ball-detect / pin-clearing | TBD | not yet wired on bench |

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

1. Verify the Phase 8a enclosure is still powered (Pi green LED + AEDIKO/AL-ZARD power LEDs). Verify D7 (watchdog-healthy) and D8 (power-good) on the Phase 8a PCB are both lit.
2. **Do NOT plug the QubicaAMF strip back in.** It stays off for the duration of the soak.
3. From the laptop browser, click **Power On** on lane 22. The 8270 should power up (audible click from the cabinet, motor energy noise).
4. From the lane 22 approach, **walk over the foul line** to break the foul beam. Watch the browser display — should show "foul" event for lane 22.
5. Click **Reset Pins** on lane 22. The pinsetter should cycle: lift, sweep, re-spot. Audible sweep motor.
6. **Roll a bowling ball down lane 22** (full rack standing). Pins fall, lamp lights for 2nd ball, pinsetter waits.
7. Click **Reset Pins** again. Pinsetter sweeps + re-spots. Score increments. Foul + 2nd-ball events appear in the browser display.
8. **Repeat all of step 3-7 for lane 21.**
9. **If anything fails to behave correctly:** see Section 6 — Rollback. Don't troubleshoot live during the window; rollback and debug at home.

### Step 5 — Soak handoff (10 min)

1. **Power the 8270 back ON** on both lanes (already on if Step 4 worked, but verify).
2. Brief any night staff: "Lanes 21+22 are on the new Pi system tonight. Use the browser display URL `http://192.168.86.36:8766/` as the desk for these two lanes. If anything looks weird, take a photo and don't try to fix it — leave the lane closed and message Dylan."
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

- **Remove QBK-SIx physically.** After 1-2 weeks soak, schedule a daytime visit to disassemble QBK-SIx, BCU II, T-VISION-98, VDB-99 from the lane 21+22 stack. Strip the L-COM bus daisy-chain wires that fed downstream pairs. Reclaim cabinet space.
- **Wire DIELL sensors.** Once T-Camera + `pin_detect.py` are bench-validated against real frames, decide whether DIELL is still needed for ball detection. If yes, schedule a wiring visit (Vcc tap, AL-ZARD channels 5-8, GPIO mapping).
- **Foul lamp drive.** If the on-site observation in Section 1 shows the foul lamp depends on QBK-SIx, wire a 5th AEDIKO channel to drive the lamp directly.
- **Display integration.** Move from the `http://192.168.86.36:8766/` browser display to either the existing overhead monitor (via HDMI) or a dedicated desk-side surface integrated into `desk.html`.
- **Update operator documentation.** Once Phase 8a is soaked clean, write the staff-facing "operating lanes 21+22 on Phase 8" guide. Likely lives in the wsl-systems repo as user-facing doc.

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
