# Phase 8 — T-Camera Auto Pin-Detection Plan (Path B)

**Decision (2026-05-30):** after the live-lane test showed the Omniboard PIN LAMPS tap is a dead end (weak ~0.5 VAC / ~20 kΩ chopped-AC floating signal, too weak to drive an opto), we go straight to optical pin detection.

## The key realization: the camera already exists

"T-Camera" here is **not a new camera we mount** — it's the **QubicaAMF T-VISION camera that's already mounted and aimed at the pin deck.** Path B *replaces T-VISION's brain*, not the camera:

```
existing T-Camera (composite NTSC analog video)
   → USB composite-video capture dongle (~$15)
   → Raspberry Pi (lane node)
   → our OpenCV/numpy pin-detect pipeline  (lane_node/pin_detect.py)
   → 10-bit standing-pin mask
   → wsl_scoring_engine.record_ball()
   → Phase 8b proxy  → desk + new scoring display
```

**Independence note:** reusing the QubicaAMF camera retires T-VISION + VDB + ETHost (the expensive EOL brains) immediately, but the *camera* (QubicaAMF) stays for now. That's a deliberate near-term trade — the camera is already aimed and working, so reusing it is the fast path. The camera is also the **easiest piece to swap later** (a Pi Camera or any analog/USB cam in the same mount): `pin_detect.py` only needs *frames*, so a future camera swap is drop-in with zero change to the detection/scoring code.

## What's ALREADY built (in the repo)

- **`lane_node/pin_detect.py`** — full pipeline designed; `detect_pins()` implemented and **passing its synthetic test suite** (strike, gutter, 7-10 split, single pin, etc.). Pin layout + 10-bit mask mapping (bit n-1 = pin n) already matches the scoring engine.
- **`wsl_scoring_engine.py`** — `record_ball()` consumes exactly that mask.
- **Phase 8b proxy** (in `wsl_api.py`) + **`wsl_scoring_display.html`** — already serve scoring to the desk + display.

So the detection math, the data format, the scoring, and the display all exist. The gaps are: real video in, calibration, capture timing, and integration.

## What's LEFT — the actual work

### Phase B-1 — Get the video in *(the gating step)*
- Buy a **USB composite/RCA NTSC video capture dongle** (~$10–15).
- At lane 21/22, find the **T-Camera's composite video feed** (the cable into the T-VISION box). Route or **split** it into the dongle → Pi. (Split = keep T-VISION running in parallel during the pilot; or just take the feed over.)
- **Capture ONE real frame of a full rack.** This single image unblocks all calibration below — and you can grab it on a laptop at the lane; the Pi isn't required yet.
- Implement `capture_frame()` for the real dongle.
  - **Lib note:** `pin_detect.py` imports `cv2` (OpenCV), which is **NOT in `requirements.txt`** yet. Either `pip install opencv-python` (headless) on the Pi, **or** implement capture with the already-installed **`av` (PyAV)** + numpy. The detection math is pure numpy — only capture/deinterlace needs the lib.

### Phase B-2 — Calibrate *(on that real frame)*
- Set the 10 **`PIN_SPOTS`** coordinates (where each pin lands in the deinterlaced frame) — currently placeholders. Method: full-rack frame, mark each pin's top-center.
- Set **`STANDING_THRESHOLD`** (lit pin-top brightness vs dark lane wood) from real pixel values.
- Tune **deinterlace** (field-drop vs better) against real frame quality.
- Validate against known racks: full (10), strike (0), 7-10 split, single pins, etc.

### Phase B-3 — Capture timing
- Grab the frame at the right instant: after the **DIELL ball-detect** fires + a short **settle delay** (pins done rocking), before the sweep clears them. Measure the real settle window (manual hint: pin data settles ~2.5 s after sweep reaches 66°). Hooks into the ball event already in `lane_node.py`.

### Phase B-4 — Integrate
- `detect_pins()` mask → `wsl_scoring_engine.record_ball()` → Phase 8b proxy → desk + display. Wire + end-to-end test on one lane.

### Phase B-5 — Robustness + soak
- Lighting variation is the #1 reliability driver. Start with the brightness threshold; if it's flaky, swap `classify_spot()` for a template-match / blob / small classifier (the pipeline is built to swap this one function). Add a constant **IR illuminator + IR-pass** if ambient light shifts cause misses.
- Soak on 21/22; log detections vs what actually stood; tune threshold/spots.

## Honest risks (none fatal)
- **Analog NTSC quality + interlacing** — real frames tell us how good the deinterlace must be.
- **Lighting consistency** — drives detector reliability; mitigations above.
- **Video split vs takeover** — decide whether T-VISION stays alive in parallel during the pilot.
- **cv2 not installed** — small fix (install, or use PyAV).

## Immediate next action
1. Order a **USB composite-video capture dongle**.
2. Grab **one full-rack frame** from the T-Camera at lane 21/22 (laptop is fine).
3. Send Claude that frame → calibrate `PIN_SPOTS` + threshold → real detection begins.

Everything downstream (timing, scoring, display) is assembling pieces that already exist.
