# Phase 8 Track A — Pin-Spot Calibration + Dual-Deck Detector ✅ DONE (2026-05-31 session 3)

> **STATUS: calibration complete, detector written + validated 0-error on all labeled frames.**
> Remaining before live = (a) Dylan confirms 3 bindings (below), (b) capture-timing hook + wire to scoring engine → 8b proxy → display, (c) bench soak. The hard CV problem is solved.

## What shipped this session
- **`lane_node/pin_detect.py` REWRITTEN** → dual-deck, drift-corrected ("M4") detector. One camera → TWO 10-bit masks (L + R). Legacy single-deck API kept for back-compat. Self-tests in `__main__`.
- **20 PIN_SPOTS calibrated** (10/deck, 720×576), baked into the module as `PIN_SPOTS_PX`.
- **Validated:** `_verify_module.py` ran the real module against all 6 labeled frames → **12/12 deck-checks OK, ALL_OK=True** (`_verify_module_verdict.txt`).

## Inputs used (`C:\Users\Dylan DeYoung\Downloads\`, all 720×576 RGB, aligned)
- Leave-frames: `corners.png`=1,7,10 · `123.png`=1,2,3 · `456.png`=4,5,6 · `78910.png`=7,8,9,10
- `Screenshot 2026-05-31 15-19-36.png` = EMPTY (detector reference) · `...14-35-27.png` = FULL rack.

## How calibration was done (reproducible — scripts in Downloads)
1. `_calib.py` / `_calib2.py`: synthetic empty = per-pixel MIN across the 4 leaves; diff each leaf; brightened, **grid-annotated** diff PNGs (`_calib2_anno_*.png`) read visually → 8 solid pin-cap positions per deck (pins 2,3 are squeezed/dim).
2. `_calib3.py`: fit a **rack→image homography** per deck from the 8 measured pins (**sub-3px residual**: L max 2.7, R max 1.9), **predict pins 2,3**, emit `PIN_SPOTS`, write `pin_spots_calibrated.py` + the numbered overlay `_calib3_fullrack_numbered.png` (every ROI box lands on its pin).

## The detection method — "M4" (why naive failed)
- **Naive `frame−empty`** (old single-deck method) FAILED: analog capture **exposure drifts** frame-to-frame (lane-band median varied 87→91 vs 51 empty), lifting every ROI ~35 → absent pins read as standing. Measured: **15/120 spot errors, separation gap −27** (no working threshold).
- **8-method bake-off** (`_exp.py`): additive **drift correction** + **tight cap-ROI** wins. **M4 = drift-corrected cap brightness vs empty cap → gap +35.0, 0/120 errors.** (Tight ROI also kills the 2nd failure mode: brightness bleed from an adjacent standing pin — the worst case was R2 catching pin-4 spill.)
- M4 baked into `pin_detect.py`: `DRIFT_BAND=(440,560)` rows (pin-free lane), `CAP_HALF=(5,12)`, `CAP_DY=-4`, `DET_THR=38` (validated safe band [19,53]).

## Dylan confirmations (status 2026-05-31)
1. ✅ **Deck → lane: left = 21, right = 22.** `DECK_TO_LANE = {'L':21,'R':22}` SET in `pin_detect.py`.
2. ✅ **Mirror / 7↔10 CONFIRMED 2026-05-31 (session 5).** Dylan set a real **pin 7 on both decks** (`Downloads/two 7 pins.png`). Detector reads it as **7 under MIRROR=True, 10 under MIRROR=False** → **MIRROR=True is CORRECT** (already the default in `pin_detect.py` — no code change). Why this frame was needed: all 4 calibration leaves are mirror-symmetric *as sets* ({7,8,9,10}↔{10,9,8,7}), so they validated either way; a single corner pin is the first asymmetric test that fixes the L-R convention. Test: `Downloads/_mirror_check.py` (blob at L cx≈45 / R cx≈454 = the back-left-corner position = pin 7). **All 3 Dylan confirmations now resolved.**
3. ✅ **Prod capture = 720×576 PAL full-frame** (keep — native res; higher = upscale w/ no real detail given composite bandwidth + soft focus; same camera/mount/framing required; calibration locked to it).

## ✅ CAMERA→SCORING WIRING DONE (session 4, 2026-05-31)
The detect→score chain is coded end-to-end + tested. **Discovery:** the scoring path already existed (DIELL → `BALL_EVENT{pin_mask}` → server `_process_ball_event` → `record_ball` → state → Phase 8b proxy → `wsl_scoring_display.html`). Only the stub at `lane_node.detect_current_pins()` was missing. **Server unchanged** — its BALL_EVENT handler already does real-mask→auto-score / None→await-manual.

Built/changed:
- **`lane_node/camera.py` (NEW):** `PairCamera` owns the capture handle + calibrated `DualDeckDetector` + per-install empty reference; `detect_lane(lane)→mask|None`, `detect_both()`, thread-safe grab with **cv2 OR PyAV** backend (Pi has PyAV, not cv2), `--capture-empty` CLI. Pure numpy detection; lazy capture import → unit-tests off-Pi.
- **`lane_node.py` rewired:** `detect_current_pins()` uses `PairCamera` (old synthetic stub survives behind `WSL_LANE_CAMERA_STUB=1`). New `_settle_capture_emit()` coroutine: DIELL→sleep `camera.SETTLE_S`→capture **off-loop via `asyncio.to_thread`**→`BALL_EVENT`. `_init_camera()` in `main()`; camera closed in cleanup.
- **Safe degradation:** detector-not-ready / capture-fail / unknown-lane → None → `awaiting_manual=True` → desk scores. A real ball NEVER auto-scores bogus pins.
- **Deps:** Pi already has numpy 2.2 / pillow 11.1 / av 14.2 (verified in `requirements.txt`); cv2 absent → PyAV path used. No requirements change needed.

**Tested:** `camera.py` end-to-end through the production path (injected grabber=real frames, empty screenshot=empty ref): all 6 frames → correct masks both decks (L21/R22) + None-fallback + unknown-lane (`Downloads/_test_camera.py`, exit 0). All 4 lane_node modules `py_compile` clean.

⚠️ **Timing coupling (fine for pilot; revisit at Track B cutover):** the server's CYCLE reply rides on BALL_EVENT, so the 2.5s settle delays CYCLE by 2.5s too. Harmless now — the EXISTING controller cycles the machine on its own ball-detect; our CYCLE relay isn't the live driver. At Track B, decouple "cycle now" from "here's the score." (Noted in `_settle_capture_emit` docstring.)

## REMAINING before live on 21/22
1. ⏳ **Mirror frame** (Dylan) → confirm/flip `MIRROR`.
2. **Capture a real per-lane empty** on the Pi: `python lane_node/camera.py --capture-empty` with BOTH decks cleared (same camera/mount/framing, 720×576) → writes `lane_node/empty_ref.png` (gitignored — each Pi captures its own).
3. **Measure the real settle window** on 21/22 (DIELL→pins-stopped→before-sweep); set `WSL_LANE_CAMERA_SETTLE_S`.  # CONFIRM (default 2.5s)
4. **Run camera mode:** `WSL_LANE_SCORING_MODE=camera`. Soak; log detected-vs-actual; tune `DET_THR` if lighting shifts. IR illuminator only if ambient drift causes misses (not expected — drift correction handles exposure).

## Robustness notes for soak
- `cv2` still NOT in requirements; detection math is **pure numpy**. Capture via PyAV (installed) or `pip install opencv-python` on the Pi — `capture_frame()` tries cv2 then PyAV.
- Pins 2,3 are homography-**predicted** (never directly measured); they validated 0-error but are the spots to watch first in soak.
- Right deck is more oblique (pins closer together) → tighter margins there; the cap-ROI handles it but it's the deck to watch.

## Scratch (Downloads): `_calib.py` `_calib2.py` `_calib3.py` `_exp.py` `_verify.py` `_verify_module.py` · `pin_spots_calibrated.py` (generated) · annotated/diff PNGs. ⚠️ ignore `_calib_out.txt` (polluted); verdicts in `_verify_module_verdict.txt`, `_exp_out.txt`.
