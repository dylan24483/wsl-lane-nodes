#!/usr/bin/env python3
"""Pin recognition pipeline.

Replaces QubicaAMF T-VISION with an OpenCV pipeline running on the Pi
node. Reads frames from a USB video capture dongle that's fed by the
existing T-Camera (composite NTSC analog video), identifies which of
the 10 pins are standing, and returns a 10-bit mask matching what
wsl_scoring_engine.LaneScoring.record_ball() consumes.

PIPELINE
========

  USB capture dongle (cv2.VideoCapture)
    → frame (NTSC 480i, ~30 fps interlaced)
    → deinterlace (yadif or simple field-drop)
    → ROI crop (the pin deck triangle, ~1/3 of frame)
    → per-pin-spot classification (10 fixed positions)
    → 10-bit pin_mask (bit 0 = pin 1, bit 1 = pin 2, ..., bit 9 = pin 10)

The 10-pin layout in standard 10-pin bowling, viewed from a camera
mounted above-and-behind the pin deck pointing toward the bowler:

         Pin 7   Pin 8   Pin 9   Pin 10        (back row)
              Pin 4   Pin 5   Pin 6            (third row)
                  Pin 2   Pin 3                (second row)
                      Pin 1                    (head pin, closest)

ALGORITHM (baseline — color-threshold per-spot)
==============================================

For each pin spot:
  - Crop the small ROI around the known spot center (~30x30 px in a
    640x480 deinterlaced frame)
  - Compute the mean brightness of the ROI in grayscale
  - If above STANDING_THRESHOLD → pin is standing (bit set in mask)
  - Else → pin is knocked down (bit clear)

Pins standing show as bright spots (top of the pin reflects overhead
lighting). Knocked-down pins lying on the deck show as the lane wood
color, which is darker. This is the simplest viable detector. More
robust algorithms (template match, blob detection, neural classifier)
can swap in by replacing classify_spot() without changing the rest
of the pipeline.

CALIBRATION NOTES
=================

PIN_SPOTS coordinates and the threshold are CALIBRATION PARAMETERS
that must be tuned per-camera-installation. Different camera
mounting heights, angles, and focal lengths shift where pins land
in the frame. Calibration is a separate task — for now PIN_SPOTS
is a placeholder that needs to be measured from a real frame.

The deinterlace step is also TBD — yadif (in OpenCV) is good but
slow; bob/weave or just dropping one field is faster but loses
vertical resolution. Pick after measuring real-frame quality.

STATUS
======

- detect_pins(): implemented, runs against synthetic test images
- capture_frame(): stubbed — real impl needs the USB capture device
- deinterlace(): stubbed — real impl waits on real frame samples
- ROI crop: hardcoded to a placeholder rectangle, must calibrate
- PIN_SPOTS: placeholder positions, must calibrate from real frames
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import cv2
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False

log = logging.getLogger('pin_detect')

# ---------------------------------------------------------------------------
# Calibration parameters — TBD against real frames
# ---------------------------------------------------------------------------

# After deinterlace + ROI crop, working frame size in pixels.
# Placeholder: assumes a 640x240 strip after vertical halving from 480.
WORKING_WIDTH = 640
WORKING_HEIGHT = 240

# Per-pin-spot center coordinates (x, y) in the working frame.
# Layout: 10 pins in 4 rows, triangle pointing toward bowler (down in image).
# These values are placeholders. Real calibration: capture a frame with all
# 10 pins standing, click on each pin's top center, save those coordinates.
PIN_SPOTS = {
    1:  (320, 200),  # head pin (closest to bowler)
    2:  (290, 160),  # second row left
    3:  (350, 160),  # second row right
    4:  (260, 120),  # third row left
    5:  (320, 120),  # third row middle
    6:  (380, 120),  # third row right
    7:  (230,  80),  # back row leftmost
    8:  (290,  80),  # back row left-middle
    9:  (350,  80),  # back row right-middle
    10: (410,  80),  # back row rightmost
}

# Per-spot classification ROI radius (pixels).
SPOT_RADIUS = 15

# Minimum mean brightness (0-255 grayscale) for a spot to count as a
# standing pin. Placeholder. Real calibration: average brightness of
# pin tops vs lane wood across several test frames.
STANDING_THRESHOLD = 140


@dataclass
class DetectionResult:
    """One detection's full output — the mask plus per-spot diagnostics.

    The mask is what the scoring engine cares about. Diagnostics are
    for tuning and debugging — they let us see WHY a pin was classified
    standing or knocked down.
    """
    pin_mask: int  # 10-bit, bit (n-1) = pin n standing
    per_spot_brightness: dict[int, float]  # pin_id → mean ROI brightness
    frame_shape: tuple[int, int] | None  # (h, w) of input frame, for sanity

    @property
    def standing_pins(self) -> list[int]:
        """List of pin numbers (1-10) currently standing."""
        return [n for n in range(1, 11) if self.pin_mask & (1 << (n - 1))]

    @property
    def pins_down(self) -> int:
        """Count of pins knocked down (0-10)."""
        return 10 - bin(self.pin_mask).count("1")


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def capture_frame(capture_device) -> Optional[np.ndarray]:
    """Read one frame from the USB video capture dongle.

    capture_device is a cv2.VideoCapture instance, set up with the
    correct device index (typically /dev/video0 if it's the only USB
    capture). Returns None if read fails.

    Stubbed for now — needs real hardware to validate.
    """
    if not HAVE_CV2:
        raise RuntimeError("cv2 not available; install opencv-python")
    ok, frame = capture_device.read()
    if not ok:
        log.warning("capture_frame: VideoCapture.read() returned False")
        return None
    return frame


def deinterlace(frame: np.ndarray) -> np.ndarray:
    """Deinterlace a 480i frame to a progressive frame.

    Cheapest correct option: drop one of the two fields, halving
    vertical resolution. Output is 640x240 from a 640x480 input.

    Better option (TBD): yadif via cv2.cuda.createCUDAFilterYadif (GPU)
    or libyadif binding (CPU). Decide after measuring real-frame quality.
    """
    if frame.ndim == 3:
        return frame[::2, :, :]  # take every other row
    return frame[::2, :]


def crop_pin_deck_roi(frame: np.ndarray) -> np.ndarray:
    """Crop the pin deck region from a deinterlaced frame.

    Currently a no-op — PIN_SPOTS coordinates are specified in
    deinterlaced-frame space (240 rows × 640 cols) directly, so per-spot
    classification clamps to frame bounds and we don't need to crop
    here. Kept as an explicit pipeline stage in case future calibration
    benefits from cropping (e.g., to suppress lighting artifacts in
    the upper region of the frame).
    """
    return frame


def to_grayscale(frame: np.ndarray) -> np.ndarray:
    """Convert BGR/RGB to grayscale. Falls through if already grayscale.

    Uses simple luminance approximation; doesn't depend on cv2.
    """
    if frame.ndim == 2:
        return frame
    # BGR (cv2's default) or RGB — both have weights ~0.299/0.587/0.114
    # for grayscale. Using matrix multiplication via numpy.
    weights = np.array([0.114, 0.587, 0.299])  # B, G, R for BGR
    return (frame @ weights).astype(np.uint8)


def classify_spot(gray_frame: np.ndarray, spot_center: tuple[int, int],
                  radius: int = SPOT_RADIUS,
                  threshold: float = STANDING_THRESHOLD) -> tuple[bool, float]:
    """Classify a single pin spot as standing (True) or down (False).

    Returns (is_standing, mean_brightness) so the caller can log
    diagnostics for calibration.

    Algorithm: mean grayscale brightness in a square ROI of side
    2*radius centered on spot_center. Compare against threshold.
    """
    x, y = spot_center
    h, w = gray_frame.shape
    # Clamp ROI to frame bounds (handles spot near edge)
    x0 = max(0, x - radius)
    x1 = min(w, x + radius)
    y0 = max(0, y - radius)
    y1 = min(h, y + radius)
    if x1 <= x0 or y1 <= y0:
        return False, 0.0
    roi = gray_frame[y0:y1, x0:x1]
    mean_brightness = float(roi.mean())
    return mean_brightness >= threshold, mean_brightness


def detect_pins(frame: np.ndarray) -> DetectionResult:
    """Run the full pipeline against one captured frame.

    Caller is responsible for capturing the frame at the right moment
    (e.g., a fixed delay after the ball-event signal — the pinsetter
    has finished settling but hasn't started cycling yet).

    Returns a DetectionResult with the 10-bit mask + diagnostics.
    """
    deinterlaced = deinterlace(frame)
    cropped = crop_pin_deck_roi(deinterlaced)
    gray = to_grayscale(cropped)

    pin_mask = 0
    per_spot = {}
    for pin_id, spot in PIN_SPOTS.items():
        is_standing, brightness = classify_spot(gray, spot)
        per_spot[pin_id] = brightness
        if is_standing:
            pin_mask |= (1 << (pin_id - 1))

    return DetectionResult(
        pin_mask=pin_mask,
        per_spot_brightness=per_spot,
        frame_shape=frame.shape[:2],
    )


# ---------------------------------------------------------------------------
# Synthetic-image helpers (for tests + calibration UI someday)
# ---------------------------------------------------------------------------

def synthesize_frame(standing_pins: list[int],
                     interlaced: bool = True) -> np.ndarray:
    """Generate a synthetic frame with the given pins shown as bright spots.

    Used for testing the pipeline without a real camera. Returns a
    BGR uint8 array sized to mimic NTSC 480i (640x480) when interlaced=True,
    or 640x240 progressive when interlaced=False.

    Each pin spot in PIN_SPOTS becomes a bright square if its pin_id
    is in standing_pins, dark otherwise. The rest of the frame is mid-gray
    (lane wood color).
    """
    working = _synthesize_working(standing_pins)
    if interlaced:
        # Each working row becomes 2 frame rows. After deinterlace
        # (frame[::2]) we get back the working frame intact.
        return np.repeat(working, 2, axis=0)
    return working


def _synthesize_working(standing_pins: list[int]) -> np.ndarray:
    """Build a synthetic working-coordinate frame (240x640 BGR).

    Pins listed in standing_pins get bright squares centered at their
    PIN_SPOTS coordinates. The rest is uniform lane-wood gray.
    """
    h, w = WORKING_HEIGHT, WORKING_WIDTH
    # Lane wood color baseline well below STANDING_THRESHOLD
    LANE_WOOD = 80
    PIN_WHITE = 220  # well above STANDING_THRESHOLD

    frame = np.full((h, w, 3), LANE_WOOD, dtype=np.uint8)
    for pin_id, (x, y) in PIN_SPOTS.items():
        if pin_id in standing_pins:
            x0 = max(0, x - SPOT_RADIUS)
            x1 = min(w, x + SPOT_RADIUS)
            y0 = max(0, y - SPOT_RADIUS)
            y1 = min(h, y + SPOT_RADIUS)
            frame[y0:y1, x0:x1] = (PIN_WHITE, PIN_WHITE, PIN_WHITE)
    return frame


# ---------------------------------------------------------------------------
# Self-test (run as `python3 -m lane_node.pin_detect`)
# ---------------------------------------------------------------------------

def _self_test():
    """Smoke test the pipeline against synthetic frames.

    Run: python3 lane_node/pin_detect.py
    """
    print("pin_detect self-test")
    print("=" * 60)

    test_cases = [
        ("strike — all 10 pins standing", list(range(1, 11)), 10),
        ("gutter ball — same as before, 10 standing", list(range(1, 11)), 10),
        ("head pin only down (split potential)", [2, 3, 4, 5, 6, 7, 8, 9, 10], 9),
        ("pins 1+2+3 down (3 pin count)", [4, 5, 6, 7, 8, 9, 10], 7),
        ("7-10 split (only 7 and 10)", [7, 10], 2),
        ("all pins down (spare/strike second ball)", [], 0),
        ("just pin 1 standing", [1], 1),
    ]

    failures = 0
    for desc, standing, expected_count in test_cases:
        # Use interlaced=True to exercise the deinterlace step in the pipeline
        frame = synthesize_frame(standing, interlaced=True)
        result = detect_pins(frame)
        actual_count = len(result.standing_pins)
        actual_pins = sorted(result.standing_pins)
        expected_pins = sorted(standing)
        ok = actual_pins == expected_pins
        marker = "✓" if ok else "✗"
        print(f"  {marker} {desc}")
        print(f"      expected: {expected_pins} ({expected_count} standing, "
              f"{10 - expected_count} down)")
        print(f"      actual:   {actual_pins} ({actual_count} standing, "
              f"{result.pins_down} down)")
        if not ok:
            failures += 1
            print(f"      brightnesses: {result.per_spot_brightness}")

    print("=" * 60)
    if failures:
        print(f"FAIL: {failures} of {len(test_cases)} cases mismatched")
        return False
    else:
        print(f"PASS: all {len(test_cases)} cases match expected pin masks")
        return True


if __name__ == '__main__':
    import sys
    sys.exit(0 if _self_test() else 1)
