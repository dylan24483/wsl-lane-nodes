# WSL Phase 8 — Status Summary & To-Do (2026-05-30)

## TL;DR
The Phase 8 pilot (lanes 21/22) is on the **scoring-first** track, and the scoring approach is now locked: **optical pin detection via the existing T-Camera**, after a live field test proved the electrical pin-lamp tap is a dead end. The detection code is already built and the capture hardware is owned. The only thing between us and real pin detection is **one calibration frame** — to be captured tomorrow.

## Direction (NOT a course change — corrected framing)

**Camera-based pin detection is required for automated scoring EITHER WAY** — it was always the Phase 8a plan ("T-Camera/PIN_SPOTS calibration" has been on the remaining-work list since bench validation; the `pin_detect.py` skeleton dates from then). The architecture has always been: **ball-detect = electrical (DIELL → opto → Pi), pin-detect = the camera.** This is not a pivot.

What changed *this session* was narrow: we noticed the labeled "PIN LAMPS" connector, tried to grab pins *electrically* off it (a shortcut), field-tested it, found the signal too weak → returned to the camera baseline.

1. **Two ACTIVE tracks in parallel (decided 2026-05-31).** (A) Scoring via camera — live on the pilot's *existing* controllers, low-risk, fast. (B) **Controller replacement — developed in parallel on the bench** (spare cabinet), high-risk (AC motors), slow, never touches a live lane until exhaustively validated. Independent now; converge later into one Pi node per pair doing both. Keep the existing controllers running until (B) is bench-proven. 21/22 = Omega-Tek Omniboard (+Expander, +ZOT); 11/12 = Active Technology Ultra 98 Plus — mixed fleet (but the Pi-controller targets the common AMF 82-70 *machine* via C1, so it's developed once for all lanes).
2. **Scoring (now): reuse the QubicaAMF camera + `pin_detect.py`** → retire T-VISION + VDB + ETHost. Controller-agnostic (works on any lane regardless of controller — the win for the mixed fleet).
3. **Electrical pin-lamp tap = dead end** (~0.5 VAC under 10 kΩ / ~20 kΩ source, chopped AC, floating, ghost-prone). Abandoned in favor of the camera.

## What the past month's bench/PCB work buys (it's NOT wasted)
- **Used now (camera scoring):** per-pair Pi node + networking + DIELL ball-detect read chain + scoring engine + display + Phase 8b proxy. The camera just feeds the pin input into this proven node.
- **Staged for the deferred controller track:** NE555 watchdog + AEDIKO relays (built for the "Pi drives the pinsetter" thesis). Read-only scoring drives nothing, so these sit idle near-term — **reserved, not scrapped.**
- The custom PCB serves as the node's read-carrier (DIELL / foul); its watchdog section is dormant until the controller track activates.

## Assets in place
- **`lane_node/pin_detect.py`** — detection pipeline built; `detect_pins()` passes its synthetic tests; 10-bit mask matches `wsl_scoring_engine`.
- **`wsl_scoring_engine.py`**, **Phase 8b proxy** (in `wsl_api.py`), **`wsl_scoring_display.html`** — already exist.
- **USB composite capture dongle (VIXLW RCA→USB)** — owned.
- **Spare 82-70 cabinet** — fully ID'd; bench asset (parts / sandbox).
- **Docs:** `phase8_tcamera_pin_detect_plan.md` (active plan), `phase8_bench_mule_characterization.md`, `phase8_PLAN_A/B_*.md`.

## TO-DO — prioritized

### Active track — T-Camera scoring (task #22)
1. **[TOMORROW] Capture one full-rack frame** from a pilot-lane (21/22) T-Camera using the VIXLW on a Windows laptop → send to Claude. *Unblocks everything below.*
2. Calibrate `PIN_SPOTS` (10 coords) + `STANDING_THRESHOLD` on that frame; tune deinterlace; validate vs known racks (full / strike / 7-10 split…).
3. Implement `capture_frame()` on the Pi; resolve OpenCV-vs-PyAV + the dongle's Linux driver.
4. Capture timing: DIELL ball-detect + settle delay → grab frame before the sweep clears.
5. Integrate: detection mask → scoring engine → Phase 8b proxy → desk + display; end-to-end on one lane.
6. Robustness (lighting; better per-spot classifier if needed; IR illuminator if needed) + soak on 21/22.

### Pilot infrastructure (still needed)
- Pull Cat6 + mount switch for 21/22 (task #14).
- Write 21/22 cutover + rollback run-of-show (task #15).
- Integrated lane-node PCB — **scope now shrinks**: camera-scoring needs only DIELL ball-detect (+ maybe foul) opto-in, not the 10 pin taps. Revisit rev B spec (task #21).

### Active (parallel) — controller-replacement track [Track B — bench, high-risk, slow]
1. **Bench-mule characterization Parts 3-5** on the spare cabinet — map the AMF 82-70 machine interface (C1: cam inputs, motor/lamp outputs) + the pivotal **"which stops are hardwired"** question (decides the Pi's real-time burden). *Gating step.* (#19/#20)
2. Design the Pi I/O layer: MCP23017 expanders + opto-in + SSR/relay-out (~30-40 ch). Watchdog + AEDIKO relays (already built) slot in here.
3. Build **reads + lamps first, NO motors**, on the spare → FSM in sim (#16) → motor control in isolation + full hardware safety (hardwired stops preserved, interlocks in series, watchdog, E-stop, MCU co-processor for timing).
4. Off-live validation on a real machine, locked out (#17) → cutover → soak.
- Plan: `phase8_PLAN_A_full_replacement.md`. The Pi-controller IS the long-term continuity answer (own the whole brain → defunct-vendor problem disappears).

### Open hardware tasks (pre-existing Phase 8a)
- Board #1 timing-node leak (#7), pre-screen bare boards (#8), relay-clicking characterization (#11), production DIN enclosure (#12).

## Tomorrow's single action
Capture one clear full-rack frame from a 21/22 T-Camera (VIXLW → Windows laptop) and send it. Calibration begins immediately.
