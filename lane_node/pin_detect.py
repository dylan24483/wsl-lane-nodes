#!/usr/bin/env python3
"""
pin_detect.py — T-Camera standing-pin detection for the WSL lane node.

ONE QubicaAMF T-Camera views BOTH lanes of a pair (left deck + right deck in a
single 720x576 PAL frame). This module turns that frame into TWO 10-bit
standing-pin masks (one per deck), which feed wsl_scoring_engine.record_ball().

Bit mapping (matches wsl_scoring_engine): bit (n-1) set = pin n STANDING.
  pin 1 = LSB (0x001) ... pin 10 = bit 9 (0x200).  full rack = 0x3FF.

------------------------------------------------------------------------------
DETECTION METHOD — "M4": drift-corrected cap-ROI difference-from-empty.
------------------------------------------------------------------------------
The naive `frame - empty` (the old single-deck method, kept below as
`detect_pins`) FAILS in practice: analog capture exposure drifts frame-to-frame,
so every ROI lifts ~35 brightness on a brighter capture and absent pins read as
standing. Measured on the real deck (2026-05-31), naive method = 15/120 spot
errors, separation gap -27 (no working threshold).

M4 fixes it and was the winner of an 8-method bake-off (0/120 errors, gap +35):
  1. Estimate global exposure drift from a PIN-FREE band of the lane (rows the
     pins never occupy): drift = median(frame[band]) - median(empty[band]).
  2. For each fixed pin spot, sample a TIGHT ROI on the pin CAP (not the whole
     pin — tight ROI avoids brightness bleed from adjacent standing pins, the
     other failure mode), subtract the drift, compare to the empty cap ROI.
  3. value = mean(frame_cap - drift) - mean(empty_cap);  standing if > DET_THR.

Spots are FIXED (the rack lands in the same positions every time) so we
calibrate once from labeled leave-frames, then check those fixed spots forever.

CALIBRATION (2026-05-31): PIN_SPOTS_PX below were fit by homography from 4
labeled leave-frames (corners=1/7/10, 123, 456, 78910) — 8 measured pins/deck,
sub-3px residual, pins 2&3 homography-predicted. Validated against all 6 frames
(4 leaves + full rack + empty): 0 detection errors at DET_THR in [19,53].
See docs/phase8_trackA_calibration_progress.md + Downloads/_calib3.py, _exp.py.

SAFETY LAYER (2026-06-10 audit): DualDeckDetector validates calibration data on
load (CalibrationError), refuses frames whose shape mismatches the empty ref or
that are byte-identical repeats of the previous frame (FrameError /
StaleFrameError — camera.py converts both to None → awaiting_manual), and every
detect pass leaves per-pin margins + a low_confidence flag on .last_detail
(flag-only; masks are never altered).

PURE NUMPY for the math (no scipy, no OpenCV). Capture (capture_frame) is a
thin wrapper over camera.PairCamera, so the module imports + tests anywhere.
"""
from __future__ import annotations
import hashlib
import logging
import os

import numpy as np

log = logging.getLogger("pin_detect")

# =============================================================================
# CALIBRATED CONSTANTS  (720x576 PAL; one camera, both decks)
# =============================================================================
CALIB_FRAME_SIZE = (720, 576)            # (W, H) the spots were measured in

# Pixel spot centers per image deck. 'L' = left half of the image, 'R' = right.
# NOTE: image-deck-side != lane number yet — see DECK_TO_LANE (await Dylan).
PIN_SPOTS_PX = {
    'L': {
        1: (94.3, 230.8),  2: (154.9, 233.0),  3: (74.5, 239.6),  4: (205.0, 234.8),
        5: (131.0, 240.8), 6: (58.4, 246.7),   7: (247.3, 236.3), 8: (178.7, 241.8),
        9: (111.3, 247.3), 10: (45.1, 252.6),
    },
    'R': {
        1: (615.0, 200.4), 2: (631.6, 202.4),  3: (554.1, 207.6), 4: (645.7, 204.0),
        5: (574.4, 208.9), 6: (500.5, 214.0),  7: (657.8, 205.4), 8: (591.8, 210.0),
        9: (523.6, 214.7), 10: (453.2, 219.6),
    },
}

# Camera is BEHIND the pins (at the pinsetter) looking toward the bowler, so the
# image is MIRRORED vs the bowler's view: leftmost-back-row pin in the image is
# pin 10 (bowler's right), not pin 7. If a KNOWN single-corner leave proves this
# backwards, flip with mirror_numbering() — it swaps 7<->10, 4<->6, 2<->3, 8<->9.
# This ONLY affects reported pin numbers on asymmetric leaves; detection is
# unaffected. CONFIRM on the real machine with a deliberate 7-pin (or 10-pin).
MIRROR = True

# Which physical lane each image deck is. CONFIRMED 2026-05-31 (Dylan): left=21, right=22.
DECK_TO_LANE = {'L': 21, 'R': 22}

# M4 sampling geometry (at calibration resolution; auto-scaled for other sizes).
CAP_DY    = -4        # cap sits a few px above the measured spot center
CAP_HALF  = (5, 12)   # (half-width, half-height) of the tight cap ROI, px
DRIFT_BAND = (440, 560)  # row range of the pin-free lane area (global-drift probe)
DET_THR   = 38.0      # M4 standing threshold (validated safe band [19,53])

# Confidence gates (flag-only — they never change a mask, they mark it suspect):
# CONF_BAND: a spot whose M4 value lands within ±CONF_BAND of DET_THR is too
#   close to the threshold to trust (validated frames kept margins outside ±10).
# DRIFT_MAX: |global drift| beyond this means the capture chain has shifted far
#   outside anything the calibration ever saw (measured real drift was ~35 at
#   worst on the naive method; M4's residual drift should be near 0).
CONF_BAND = 10.0
DRIFT_MAX = 60.0

# --- camera health + empty-reference self-check (idea #14, OBSERVE-ONLY) -------
# These never touch a mask and never drive a relay. They turn a frame into a
# health verdict (exposure/focus in band?) and, on a KNOWN-EMPTY deck moment,
# measure how far the live empty frame has drifted from the stored empty
# reference. A FLAG is surfaced for the daemon/telemetry; auto-recalibration is
# a separate, opt-in step in camera.py (a bad auto-update corrupts ALL scoring).
#
# HEALTH bands describe a frame the analog T-Camera produces when it is exposing
# and focusing correctly. The defaults are deliberately WIDE — they catch a dead
# / blacked-out / washed-out / wildly-defocused camera, NOT marginal lighting
# (which the per-pin confidence gate already handles for actual scoring). A frame
# whose mean or focus leaves these bands does not block scoring; it only sets
# health['ok'] = False for telemetry. Field-tune against the real 21/22 camera.
HEALTH_MEAN_MIN = float(os.environ.get("WSL_CAM_HEALTH_MEAN_MIN", "12.0"))
HEALTH_MEAN_MAX = float(os.environ.get("WSL_CAM_HEALTH_MEAN_MAX", "245.0"))
# Focus = mean(|2nd spatial difference|) over the deck band — a crude sharpness
# proxy (no scipy/cv2). A blurred or frozen-gray frame collapses toward 0; a
# correctly-focused analog frame on these decks measured well above this floor.
HEALTH_FOCUS_MIN = float(os.environ.get("WSL_CAM_HEALTH_FOCUS_MIN", "0.6"))
# Rows (calibration-space) spanning both pin decks — where focus/exposure matter.
HEALTH_BAND = (180, 280)

# EMPTY-REFERENCE DRIFT: on a confirmed-empty deck, the mean absolute per-spot
# brightness difference between the live empty frame and the stored empty ref
# (after global-drift correction, so a uniform exposure shift does NOT count —
# M4 already corrects that at scoring time). Beyond this the reference itself is
# stale relative to what the camera now sees → FLAG (and, only if WSL_CAM_AUTO_RECAL
# is set, camera.py may refresh the ref). Default chosen well inside CONF_BAND so
# a flagged-but-not-yet-failing reference is caught before it starts mis-scoring.
EMPTY_DIVERGENCE_MAX = float(
    os.environ.get("WSL_CAM_EMPTY_DIVERGENCE_MAX", "6.0"))


# =============================================================================
# error types — camera.py's detect_lane() try/except converts these to None
# → the daemon emits awaiting_manual (the safe default) instead of a bad score.
# =============================================================================
class CalibrationError(ValueError):
    """Calibration data (pin spots / empty reference) is unusable."""


class FrameError(ValueError):
    """A frame is unusable for detection (e.g. shape != empty reference)."""


class StaleFrameError(FrameError):
    """Frame is byte-identical to the previous one (camera hang / stale buffer)."""


def validate_spots(spots, frame_size=CALIB_FRAME_SIZE, decks=('L', 'R')):
    """Validate a {deck: {pin: (x, y)}} calibration dict; raise CalibrationError.

    Checks: both decks present, exactly pins 1..10 per deck, every coordinate a
    finite number inside the calibration frame. Extra top-level keys are allowed
    (extend-don't-break for future calibration files); only `decks` are checked.
    Returns `spots` unchanged on success.
    """
    if not isinstance(spots, dict):
        raise CalibrationError(
            f"pin spots must be a dict of decks, got {type(spots).__name__}")
    w, h = frame_size
    for dk in decks:
        if dk not in spots:
            raise CalibrationError(
                f"pin spots missing deck {dk!r} (decks present: {sorted(map(str, spots))})")
        deck = spots[dk]
        if not isinstance(deck, dict):
            raise CalibrationError(
                f"pin spots[{dk!r}] must be a dict of pins, got {type(deck).__name__}")
        if set(deck) != set(range(1, 11)):
            raise CalibrationError(
                f"pin spots[{dk!r}] must have exactly pins 1..10, got {sorted(map(str, deck))}")
        for pin, xy in deck.items():
            try:
                x, y = float(xy[0]), float(xy[1])
            except (TypeError, ValueError, IndexError):
                raise CalibrationError(
                    f"pin spots[{dk!r}][{pin}] must be an (x, y) pair, got {xy!r}")
            if not (np.isfinite(x) and np.isfinite(y)):
                raise CalibrationError(
                    f"pin spots[{dk!r}][{pin}] has non-finite coords {xy!r}")
            if not (0 <= x < w and 0 <= y < h):
                raise CalibrationError(
                    f"pin spots[{dk!r}][{pin}] = ({x}, {y}) is outside the "
                    f"calibration frame {w}x{h}")
    return spots


# =============================================================================
# M4 detection core
# =============================================================================
def _to_gray(frame):
    """Accept HxW gray or HxWx3 color; return float32 HxW."""
    a = np.asarray(frame)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    return a.astype(np.float32)


def _scale_for(frame_shape):
    """Return (sx, sy) to map calibration-space coords onto this frame."""
    h, w = frame_shape[:2]
    cw, ch = CALIB_FRAME_SIZE
    return w / cw, h / ch


def _roi(gray, cx, cy, hx, hy):
    h, w = gray.shape
    x0 = max(0, int(round(cx - hx))); x1 = min(w, int(round(cx + hx)))
    y0 = max(0, int(round(cy - hy))); y1 = min(h, int(round(cy + hy)))
    if x1 <= x0 or y1 <= y0:
        return None
    return gray[y0:y1, x0:x1]


def estimate_drift(gray, empty, sy=1.0):
    """Global exposure drift between `gray` and `empty`, from the pin-free band."""
    y0 = int(round(DRIFT_BAND[0] * sy)); y1 = int(round(DRIFT_BAND[1] * sy))
    y1 = min(y1, gray.shape[0])
    if y1 <= y0:
        return 0.0
    return float(np.median(gray[y0:y1, :])) - float(np.median(empty[y0:y1, :]))


def spot_value(gray, empty, x, y, drift, sx=1.0, sy=1.0):
    """M4 score for one spot: drift-corrected cap brightness over empty cap."""
    cx = x * sx
    cy = (y + CAP_DY) * sy
    hx = max(1.0, CAP_HALF[0] * sx); hy = max(1.0, CAP_HALF[1] * sy)
    fcap = _roi(gray, cx, cy, hx, hy)
    ecap = _roi(empty, cx, cy, hx, hy)
    if fcap is None or ecap is None:
        return 0.0
    return float((fcap - drift).mean() - ecap.mean())


def detect_deck_values(gray, empty, spots, sx=1.0, sy=1.0, drift=None):
    """Per-pin M4 scores for one deck: {pin: value}. value > thr ⇒ standing."""
    if drift is None:
        drift = estimate_drift(gray, empty, sy)
    return {pin: spot_value(gray, empty, x, y, drift, sx, sy)
            for pin, (x, y) in spots.items()}


def detect_deck(gray, empty, spots, thr=DET_THR, sx=1.0, sy=1.0, drift=None):
    """Return a 10-bit standing-pin mask for one deck's spots."""
    mask = 0
    for pin, v in detect_deck_values(gray, empty, spots, sx, sy, drift).items():
        if v > thr:
            mask |= (1 << (pin - 1))
    return mask


# =============================================================================
# camera health + empty-reference self-check (idea #14) — PURE, OBSERVE-ONLY.
# Nothing here mutates a mask, the empty reference, or any control output; the
# functions return verdict dicts the daemon/telemetry (and camera.py's opt-in
# auto-recal) read. Auto-recalibration itself lives in camera.py behind a flag.
# =============================================================================
def _band_rows(gray, band=HEALTH_BAND):
    """Slice `gray` to the calibration-space row `band`, scaled to this frame."""
    sy = gray.shape[0] / CALIB_FRAME_SIZE[1]
    y0 = max(0, int(round(band[0] * sy)))
    y1 = min(gray.shape[0], max(y0 + 1, int(round(band[1] * sy))))
    return gray[y0:y1, :]


def _focus_metric(region):
    """Crude sharpness proxy: mean magnitude of the 2nd spatial difference.

    A sharp frame has strong edges (large 2nd differences); a black/frozen/blurred
    frame collapses toward 0. Pure numpy — no scipy/cv2. Returns a non-negative
    float (0.0 for a degenerate region)."""
    r = np.asarray(region, dtype=np.float32)
    if r.ndim != 2 or r.shape[0] < 3 or r.shape[1] < 3:
        return 0.0
    # |d2/dx2| + |d2/dy2| averaged over the interior (a discrete Laplacian).
    dxx = np.abs(r[1:-1, 2:] - 2.0 * r[1:-1, 1:-1] + r[1:-1, :-2])
    dyy = np.abs(r[2:, 1:-1] - 2.0 * r[1:-1, 1:-1] + r[:-2, 1:-1])
    return float((dxx + dyy).mean())


def frame_health(frame, mean_min=HEALTH_MEAN_MIN, mean_max=HEALTH_MEAN_MAX,
                 focus_min=HEALTH_FOCUS_MIN, band=HEALTH_BAND):
    """Exposure/focus sanity of one frame — OBSERVE-ONLY telemetry.

    Returns a dict:
      mean       float  — mean brightness over the deck band
      variance   float  — brightness variance over the deck band
      focus      float  — sharpness proxy (mean |2nd difference|)
      ok         bool   — all metrics inside their bands
      reasons    [str]  — why ok is False (empty when ok)

    A False verdict means the camera looks dead / washed-out / blacked-out /
    badly defocused; it never blocks scoring (the per-pin confidence gate does
    that), it only feeds the daemon's health signal. Robust to a None/garbage
    frame: returns ok=False with a reason rather than raising."""
    reasons = []
    try:
        gray = _to_gray(frame)
    except Exception as e:
        return {'mean': 0.0, 'variance': 0.0, 'focus': 0.0,
                'ok': False, 'reasons': [f"frame unreadable: {e}"]}
    if gray.ndim != 2 or gray.size == 0:
        return {'mean': 0.0, 'variance': 0.0, 'focus': 0.0,
                'ok': False, 'reasons': ['frame is not a usable 2-D image']}
    region = _band_rows(gray, band)
    mean = float(region.mean())
    variance = float(region.var())
    focus = _focus_metric(region)
    if mean < mean_min:
        reasons.append(f"frame mean {mean:.1f} < {mean_min:g} (camera dark / no signal?)")
    if mean > mean_max:
        reasons.append(f"frame mean {mean:.1f} > {mean_max:g} (over-exposed / washed out?)")
    if focus < focus_min:
        reasons.append(f"focus {focus:.2f} < {focus_min:g} (defocused / frozen-gray frame?)")
    return {'mean': mean, 'variance': variance, 'focus': focus,
            'ok': not reasons, 'reasons': reasons}


def spot_divergence(gray, empty, spots, sx=1.0, sy=1.0, drift=None):
    """Mean absolute per-spot brightness difference between a (supposedly empty)
    live frame and the stored empty reference, AFTER global-drift correction.

    This is the empty-reference drift metric for the self-check: M4 already
    cancels a uniform exposure shift via `drift`, so this measures the part the
    reference can't correct — localized lighting/camera-shift changes at the very
    cap ROIs scoring depends on. Returns (mean_abs, {pin: signed_diff}); 0.0 on a
    degenerate ROI set."""
    if drift is None:
        drift = estimate_drift(gray, empty, sy)
    diffs = {}
    for pin, (x, y) in spots.items():
        cx = x * sx
        cy = (y + CAP_DY) * sy
        hx = max(1.0, CAP_HALF[0] * sx); hy = max(1.0, CAP_HALF[1] * sy)
        fcap = _roi(gray, cx, cy, hx, hy)
        ecap = _roi(empty, cx, cy, hx, hy)
        if fcap is None or ecap is None:
            continue
        diffs[pin] = float((fcap - drift).mean() - ecap.mean())
    if not diffs:
        return 0.0, {}
    return float(np.mean([abs(v) for v in diffs.values()])), diffs


# mirror pin renumbering (camera-behind-pins view → bowler numbering)
_MIRROR_PIN = {2: 3, 3: 2, 4: 6, 6: 4, 7: 10, 10: 7, 8: 9, 9: 8}


def _mirror_pins(d):
    """Remap a {pin: value} dict through the mirror pairs (7<->10, 4<->6, ...)."""
    return {_MIRROR_PIN.get(p, p): v for p, v in d.items()}


def _mirror_mask(mask):
    """Swap mirrored pin pairs in a 10-bit mask: 7<->10, 4<->6, 2<->3, 8<->9."""
    pairs = [(7, 10), (4, 6), (2, 3), (8, 9)]
    out = mask
    for a, b in pairs:
        ba, bb = 1 << (a - 1), 1 << (b - 1)
        hi_a, hi_b = bool(mask & ba), bool(mask & bb)
        out = (out & ~ba & ~bb)
        if hi_a:
            out |= bb
        if hi_b:
            out |= ba
    return out


class DualDeckDetector:
    """Stateful detector for ONE camera covering BOTH decks of a pair.

    Usage:
        det = DualDeckDetector(empty_frame, deck_to_lane={'L': 21, 'R': 22})
        masks = det.detect(frame)          # {'L': maskL, 'R': maskR}
        m21   = det.detect_lane(frame, 21) # 10-bit mask for lane 21
    `empty_frame` is a full frame (both decks visible) of the CLEARED deck.
    """

    def __init__(self, empty_frame, spots=PIN_SPOTS_PX, thr=DET_THR,
                 mirror=MIRROR, deck_to_lane=None,
                 conf_band=CONF_BAND, drift_max=DRIFT_MAX, stale_check=True):
        validate_spots(spots)   # wrong pin count / out-of-bounds → CalibrationError
        self.empty = _to_gray(empty_frame)
        if self.empty.ndim != 2 or self.empty.size == 0:
            raise CalibrationError(
                f"empty reference is not a usable 2-D image "
                f"(ndim={self.empty.ndim}, size={self.empty.size})")
        self.spots = spots
        self.thr = thr
        self.mirror = mirror
        self.deck_to_lane = dict(deck_to_lane) if deck_to_lane else dict(DECK_TO_LANE)
        self.conf_band = float(conf_band)
        self.drift_max = float(drift_max)
        self.stale_check = bool(stale_check)  # set False to re-detect a saved frame
        self._last_sig = None
        self._stale_count = 0
        self.last_detail = None   # detail dict from the most recent detect pass

    def detect_detail(self, frame, stale_check=None):
        """One full detection pass: masks + per-pin confidence + frame sanity.

        `stale_check` overrides self.stale_check for THIS call only (None = use
        the instance default). The self-check passes False so re-reading a steady
        empty deck does not raise StaleFrameError AND does not perturb the
        scoring path's stale-frame tracking (self._last_sig is left untouched).

        Returns (and stores on self.last_detail) a dict:
          masks          {'L': int, 'R': int} — what detect() returns
          values         {'L': {pin: float}, 'R': ...} — per-pin M4 scores, in
                         the SAME pin numbering as the masks (mirrored if set)
          margins        same shape — value - thr (>0 standing, <0 down)
          drift          global exposure drift used for this frame
          low_conf_pins  {'L': [pins], 'R': [pins]} — |margin| < conf_band
          low_confidence bool — any low-conf pin, or |drift| > drift_max
          reasons        human-readable strings explaining low_confidence

        low_confidence NEVER changes the masks — callers decide whether to
        trust the result or fall back to manual scoring.

        Raises FrameError if the frame shape doesn't match the empty reference
        (the spot geometry would index garbage), StaleFrameError if the frame
        is byte-identical to the previous one (camera hang / driver re-serving
        a buffered frame — analog capture noise makes a true repeat
        impossible). camera.py's detect_lane() catches these → None → the
        daemon emits awaiting_manual instead of scoring a bad frame.
        """
        gray = _to_gray(frame)
        if gray.shape != self.empty.shape:
            raise FrameError(
                f"frame shape {gray.shape} != empty reference {self.empty.shape}; "
                f"spot geometry would be wrong — recapture the empty ref at the "
                f"live resolution (python camera.py --capture-empty)")
        do_stale = self.stale_check if stale_check is None else bool(stale_check)
        if do_stale:
            sig = hashlib.sha1(gray.tobytes()).digest()
            if sig == self._last_sig:
                self._stale_count += 1
                raise StaleFrameError(
                    f"frame is byte-identical to the previous frame (repeat "
                    f"#{self._stale_count}; camera hang or stale driver buffer?) "
                    f"— refusing to score it")
            self._last_sig = sig
            self._stale_count = 0
        sx, sy = _scale_for(gray.shape)
        drift = estimate_drift(gray, self.empty, sy)
        masks, values, margins, low_conf_pins, reasons = {}, {}, {}, {}, []
        for dk in ('L', 'R'):
            vals = detect_deck_values(gray, self.empty, self.spots[dk], sx, sy, drift)
            mask = 0
            for pin, v in vals.items():
                if v > self.thr:
                    mask |= (1 << (pin - 1))
            if self.mirror:
                mask = _mirror_mask(mask)
                vals = _mirror_pins(vals)
            masks[dk] = mask
            values[dk] = vals
            margins[dk] = {p: v - self.thr for p, v in vals.items()}
            lp = sorted(p for p, m in margins[dk].items() if abs(m) < self.conf_band)
            low_conf_pins[dk] = lp
            if lp:
                reasons.append(
                    f"deck {dk}: pins {lp} within +/-{self.conf_band:g} of thr "
                    f"{self.thr:g} (" +
                    ", ".join(f"{p}:{vals[p]:.1f}" for p in lp) + ")")
        if abs(drift) > self.drift_max:
            reasons.append(
                f"exposure drift {drift:+.1f} exceeds sanity bound +/-{self.drift_max:g}")
        low_confidence = bool(reasons)
        if low_confidence:
            log.warning("pin_detect LOW CONFIDENCE: %s", "; ".join(reasons))
        detail = {
            'masks': masks, 'values': values, 'margins': margins,
            'drift': drift, 'low_conf_pins': low_conf_pins,
            'low_confidence': low_confidence, 'reasons': reasons,
        }
        self.last_detail = detail
        return detail

    def detect(self, frame):
        """Return {'L': mask, 'R': mask} of pins STANDING after the ball.

        Raises FrameError/StaleFrameError on an unusable frame (see
        detect_detail) — camera.py converts that to None → awaiting_manual.
        Per-pin confidence for this pass is left on self.last_detail.
        """
        return dict(self.detect_detail(frame)['masks'])

    def detect_lane(self, frame, lane_id):
        """Return the 10-bit mask for a physical lane (needs deck_to_lane set)."""
        masks = self.detect(frame)
        for dk, ln in self.deck_to_lane.items():
            if ln == lane_id:
                return masks[dk]
        raise KeyError(f"lane {lane_id} not in deck_to_lane={self.deck_to_lane}; "
                       f"set it (e.g. {{'L':21,'R':22}}) after confirming the binding")

    # -- empty-reference self-check (idea #14) — OBSERVE-ONLY ---------------
    # These never alter a mask or the stored empty reference. is_empty_deck()
    # turns an already-computed detail dict into a high-confidence "both decks
    # are CLEAR" signal; check_empty_reference() runs a fresh pass on a frame the
    # CALLER asserts was captured at a known-empty moment (full respot / clean
    # cycle) and measures how far that empty frame has drifted from the stored
    # empty reference. The verdict's `flagged` is the slow-failure alarm; whether
    # to act on it (re-capture the reference) is camera.py's opt-in decision.
    @staticmethod
    def is_empty_deck(detail):
        """True iff a detect_detail() result shows BOTH decks fully clear with
        high confidence (no pins standing, no low-confidence pins, drift in band).

        This is the "known-empty-deck moment" gate: only when this is True does an
        empty-reference comparison mean anything (otherwise pins or noise would
        masquerade as reference drift). Defensive against a malformed dict."""
        if not isinstance(detail, dict):
            return False
        masks = detail.get('masks')
        if not isinstance(masks, dict) or any(dk not in masks for dk in ('L', 'R')):
            return False                     # malformed / incomplete pass
        if any(masks.get(dk) for dk in ('L', 'R')):
            return False                     # a pin reads standing → not empty
        if detail.get('low_confidence'):
            return False                     # margins/drift already suspect
        lcp = detail.get('low_conf_pins') or {}
        if any(lcp.get(dk) for dk in ('L', 'R')):
            return False
        return True

    def reference_divergence(self, frame):
        """Per-deck (mean_abs, {pin: signed_diff}) of a live frame's cap ROIs
        vs the stored empty reference, drift-corrected. OBSERVE-ONLY.

        Returns {'L': (mean_abs, diffs), 'R': (...)}. Raises the same
        FrameError on a shape mismatch as detect_detail (geometry would be
        wrong) but does NOT run the stale-frame gate — a self-check re-reading a
        saved empty frame is legitimate."""
        gray = _to_gray(frame)
        if gray.shape != self.empty.shape:
            raise FrameError(
                f"frame shape {gray.shape} != empty reference {self.empty.shape}; "
                f"cannot compare to the reference")
        sx, sy = _scale_for(gray.shape)
        drift = estimate_drift(gray, self.empty, sy)
        return {dk: spot_divergence(gray, self.empty, self.spots[dk], sx, sy, drift)
                for dk in ('L', 'R')}

    def check_empty_reference(self, frame, divergence_max=EMPTY_DIVERGENCE_MAX):
        """Self-check the stored empty reference against a known-empty live frame.

        The CALLER asserts `frame` was captured at a known-empty-deck moment
        (full respot / clean cycle). This:
          1. runs a detection pass (without the stale gate — re-reading is ok),
          2. confirms the deck really does read empty (is_empty_deck),
          3. measures per-deck drift of the cap ROIs vs the stored reference,
          4. FLAGS if confirmed-empty AND any deck's drift exceeds divergence_max.

        Returns a verdict dict (also useful as telemetry):
          empty_confirmed bool   — both decks read clear with high confidence
          divergence      {'L': mean_abs, 'R': mean_abs}
          max_divergence  float  — worst per-deck MEAN
          max_spot_divergence float — worst SINGLE spot |diff| across both decks
                                 (the means dilute a single corrupted cap 10x;
                                 camera.py's auto-recal cap must see the raw spot)
          flagged         bool   — empty_confirmed and max_divergence > threshold
          reason          str    — human-readable summary
          detail          the underlying detect_detail() dict

        NEVER mutates the reference or a mask. If the deck is NOT confirmed empty,
        flagged is False (we can't attribute the difference to reference drift)
        and the caller should simply skip this opportunity. Raises FrameError on
        a shape mismatch (caller converts to a skipped check)."""
        # stale gate off for THIS call only (a self-check legitimately re-reads a
        # steady empty deck); the scoring path's stale tracking is left intact.
        # last_detail is also scoring-path state (camera.detect_lane reads it for
        # the low-confidence gate right after a scored pass), so restore it: a
        # self-check must not perturb ANY state the scoring path depends on.
        prev_detail = self.last_detail
        detail = self.detect_detail(frame, stale_check=False)
        self.last_detail = prev_detail
        empty_confirmed = self.is_empty_deck(detail)
        div = self.reference_divergence(frame)
        per_deck = {dk: round(div[dk][0], 2) for dk in ('L', 'R')}
        max_div = max(per_deck.values()) if per_deck else 0.0
        # worst SINGLE-spot |diff|: the per-deck numbers are MEANS over 10 pins,
        # so one corrupted cap ROI (shadow/grease/sweep edge) dilutes 10x — keep
        # the raw per-spot worst so the auto-recal cap can refuse what the mean hides.
        spot_max = 0.0
        for dk in ('L', 'R'):
            diffs = div[dk][1]
            if diffs:
                spot_max = max(spot_max, max(abs(v) for v in diffs.values()))
        flagged = bool(empty_confirmed and max_div > divergence_max)
        if not empty_confirmed:
            reason = ("deck not confirmed empty (pins standing / low confidence) "
                      "-- self-check skipped, reference unchanged")
        elif flagged:
            reason = (f"empty reference DRIFTED: per-deck cap divergence {per_deck} "
                      f"exceeds {divergence_max:g} -- lighting/camera shift suspected; "
                      f"re-capture the empty reference (or enable WSL_CAM_AUTO_RECAL)")
            log.warning("pin_detect EMPTY-REF DRIFT: %s", reason)
        else:
            reason = f"empty reference healthy (per-deck cap divergence {per_deck})"
        return {
            'empty_confirmed': empty_confirmed,
            'divergence': per_deck,
            'max_divergence': max_div,
            'max_spot_divergence': round(spot_max, 2),
            'flagged': flagged,
            'reason': reason,
            'detail': detail,
        }


# =============================================================================
# LEGACY single-deck API (normalized coords, plain difference) — kept for the
# existing synthetic tests + any caller still using it. SUPERSEDED by M4 above
# for real analog frames (it has no drift correction).
# =============================================================================
PIN_SPOTS_NORM = {
    1:  (0.50, 0.86), 2:  (0.44, 0.70), 3:  (0.56, 0.70), 4:  (0.38, 0.54),
    5:  (0.50, 0.54), 6:  (0.62, 0.54), 7:  (0.32, 0.38), 8:  (0.44, 0.38),
    9:  (0.56, 0.38), 10: (0.68, 0.38),
}
ROI_HALF = 0.025
STANDING_DELTA = 18.0


def _roi_mean_norm(gray, cx, cy, half):
    h, w = gray.shape
    x0 = max(0, int((cx - half) * w)); x1 = min(w, int((cx + half) * w))
    y0 = max(0, int((cy - half) * h)); y1 = min(h, int((cy + half) * h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(gray[y0:y1, x0:x1].mean())


def detect_pins(gray, empty, spots=PIN_SPOTS_NORM, half=ROI_HALF, delta=STANDING_DELTA):
    """LEGACY: 10-bit mask via plain normalized-ROI difference (no drift corr.)."""
    gray = _to_gray(gray); empty = _to_gray(empty)
    mask = 0
    for pin, (cx, cy) in spots.items():
        if _roi_mean_norm(gray, cx, cy, half) - _roi_mean_norm(empty, cx, cy, half) >= delta:
            mask |= (1 << (pin - 1))
    return mask


class PinDetector:
    """LEGACY stateful single-deck detector (normalized spots, plain diff)."""
    def __init__(self, empty_gray, spots=PIN_SPOTS_NORM, half=ROI_HALF, delta=STANDING_DELTA):
        self.empty = _to_gray(empty_gray)
        self.spots = spots; self.half = half; self.delta = delta

    def detect(self, gray):
        return detect_pins(gray, self.empty, self.spots, self.half, self.delta)


# =============================================================================
# capture — DELEGATED to camera.PairCamera (same dir), which owns the real
# backend stack (cv2 if present, else PyAV with the /dev/videoN + v4l2 mapping
# the Pi needs). The detection math above needs neither. This wrapper exists
# only for REPL/calibration convenience; production capture is camera.py's.
# =============================================================================
def capture_frame(device=None):
    """Grab one grayscale frame via camera.PairCamera. Returns 2-D float32.

    `device` defaults to camera.CAMERA_DEVICE (env WSL_LANE_CAMERA_DEVICE).
    Raises RuntimeError if no backend/device can produce a frame.
    """
    try:
        import camera  # lazy: camera.py imports this module at load time
    except ImportError as e:
        raise RuntimeError(
            "capture_frame needs lane_node/camera.py importable (same dir); "
            "production capture lives in camera.PairCamera") from e
    cam = camera.PairCamera(
        empty_ref_path=None,
        device=camera.CAMERA_DEVICE if device is None else device)
    try:
        gray = cam.grab_frame()
    finally:
        cam.close()
    if gray is None:
        raise RuntimeError(
            "capture_frame: no frame (no cv2/PyAV backend or device unavailable)")
    return gray


# =============================================================================
# self-test (synthetic; portable — real-frame validation lives in
# Downloads/_calib3.py + _exp.py, which scored 0/120 on the labeled frames)
# =============================================================================
if __name__ == "__main__":
    # 1) legacy synthetic single-deck
    H = W = 100
    empty = np.full((H, W), 30, dtype=np.uint8)
    frame = empty.copy()
    for p in (1, 5, 9):
        cx, cy = PIN_SPOTS_NORM[p]
        frame[int(cy*H)-4:int(cy*H)+4, int(cx*W)-4:int(cx*W)+4] = 200
    standing = [p for p in range(1, 11) if detect_pins(frame, empty) & (1 << (p-1))]
    assert standing == [1, 5, 9], standing
    print(f"legacy synthetic OK: standing={standing}")

    # 2) dual-deck synthetic on a 720x576 field using the real spots
    empty2 = np.full((576, 720), 40, dtype=np.uint8)
    f2 = empty2.copy()
    want = {'L': {1, 7, 10}, 'R': {2, 5}}
    for dk, pins in want.items():
        for p in pins:
            x, y = PIN_SPOTS_PX[dk][p]
            f2[int(y)-12:int(y)+2, int(x)-5:int(x)+5] = 220   # bright cap
    det = DualDeckDetector(empty2, mirror=False)              # mirror off for raw-number test
    got = det.detect(f2)
    gotL = {p for p in range(1, 11) if got['L'] & (1 << (p-1))}
    gotR = {p for p in range(1, 11) if got['R'] & (1 << (p-1))}
    assert gotL == want['L'], (gotL, want['L'])
    assert gotR == want['R'], (gotR, want['R'])
    print(f"dual-deck synthetic OK: L={sorted(gotL)} R={sorted(gotR)}")

    # 3) mirror swap sanity
    assert _mirror_mask(1 << (7-1)) == (1 << (10-1)), "7->10 mirror failed"
    assert _mirror_mask(1 << (1-1)) == (1 << (1-1)), "pin1 should be mirror-invariant"
    assert _mirror_pins({7: 1.0, 1: 2.0}) == {10: 1.0, 1: 2.0}, "value remap failed"
    print("mirror swap OK")

    # 4) detail pass: confidence plumbing + stale-frame + shape gates
    det2 = DualDeckDetector(empty2, mirror=False)
    d = det2.detect_detail(f2)
    assert d['masks'] == got, (d['masks'], got)
    assert not d['low_confidence'], d['reasons']   # synthetic caps are far from thr
    try:
        det2.detect(f2)                            # same frame again → stale
        raise AssertionError("stale frame not flagged")
    except StaleFrameError:
        pass
    try:
        det2.detect(np.full((100, 100), 40, dtype=np.uint8))
        raise AssertionError("shape mismatch not flagged")
    except StaleFrameError:
        raise
    except FrameError:
        pass
    f3 = empty2.copy()
    x, y = PIN_SPOTS_PX['L'][1]
    f3[int(y)-20:int(y)+16, int(x)-8:int(x)+8] = 82  # +42 over empty → margin +4
    d3 = det2.detect_detail(f3)
    assert d3['masks']['L'] & 1, "pin 1 should still read standing (42 > thr)"
    assert d3['low_confidence'] and 1 in d3['low_conf_pins']['L'], d3
    print("detail/confidence/stale/shape gates OK")

    # 5) calibration validation
    badA = {'L': dict(PIN_SPOTS_PX['L']), 'R': dict(PIN_SPOTS_PX['R'])}
    del badA['L'][7]
    try:
        DualDeckDetector(empty2, spots=badA)
        raise AssertionError("missing pin 7 not rejected")
    except CalibrationError:
        pass
    badB = {'L': dict(PIN_SPOTS_PX['L']), 'R': dict(PIN_SPOTS_PX['R'])}
    badB['R'][3] = (9999.0, 207.6)
    try:
        DualDeckDetector(empty2, spots=badB)
        raise AssertionError("out-of-bounds spot not rejected")
    except CalibrationError:
        pass
    validate_spots(PIN_SPOTS_PX)   # the shipped calibration must pass
    print("calibration validation OK")

    # 6) camera health + empty-reference self-check (idea #14, OBSERVE-ONLY)
    rng = np.random.default_rng(14)
    # textured empty deck (so the focus metric clears its floor): mid-gray base
    # + per-pixel noise across the whole field.
    base = rng.integers(60, 110, size=(576, 720)).astype(np.float32)
    empty6 = base.copy()
    det6 = DualDeckDetector(empty6, mirror=False)

    # frame_health: a textured empty frame is healthy; a black frame is not.
    h_ok = frame_health(empty6)
    assert h_ok['ok'], h_ok
    assert HEALTH_MEAN_MIN <= h_ok['mean'] <= HEALTH_MEAN_MAX, h_ok
    assert h_ok['focus'] >= HEALTH_FOCUS_MIN, h_ok
    h_dark = frame_health(np.zeros((576, 720), dtype=np.uint8))
    assert not h_dark['ok'] and any('dark' in r for r in h_dark['reasons']), h_dark
    h_flat = frame_health(np.full((576, 720), 128, dtype=np.uint8))
    assert not h_flat['ok'] and any('focus' in r for r in h_flat['reasons']), h_flat
    h_none = frame_health(None)
    assert not h_none['ok'], h_none

    # is_empty_deck: a clean empty frame is confirmed; a frame with a standing
    # pin (and one with a low-confidence pin) is not.
    clean = det6.check_empty_reference(empty6)
    assert clean['empty_confirmed'], clean
    assert not clean['flagged'], clean              # ref == live → no divergence
    assert clean['max_divergence'] < EMPTY_DIVERGENCE_MAX, clean

    f_pin = empty6.copy()
    xp, yp = PIN_SPOTS_PX['L'][1]
    f_pin[int(yp)-12:int(yp)+2, int(xp)-5:int(xp)+5] = 240   # a real standing pin
    pin_chk = det6.check_empty_reference(f_pin)
    assert not pin_chk['empty_confirmed'], pin_chk          # pin standing → not empty
    assert not pin_chk['flagged'], pin_chk                  # so never a drift flag

    # drifted empty: every cap ROI brightened locally (lighting/camera shift),
    # but the global DRIFT_BAND left alone so M4's drift correction can't hide it
    # → divergence exceeds threshold on a confirmed-empty deck → flagged.
    f_drift = empty6.copy()
    for dk in ('L', 'R'):
        for p, (x, y) in PIN_SPOTS_PX[dk].items():
            cx = int(round(x)); cy = int(round(y + CAP_DY))
            hx, hy = CAP_HALF
            f_drift[cy-hy:cy+hy, cx-hx:cx+hx] = np.clip(
                f_drift[cy-hy:cy+hy, cx-hx:cx+hx] + 9.0, 0, 255)
    drift_chk = det6.check_empty_reference(f_drift)
    assert drift_chk['empty_confirmed'], drift_chk          # still no pins standing
    assert drift_chk['flagged'], drift_chk                  # but the ref has drifted
    assert drift_chk['max_divergence'] > EMPTY_DIVERGENCE_MAX, drift_chk
    assert drift_chk['max_spot_divergence'] >= drift_chk['max_divergence'], drift_chk

    # single-spot dilution: ONE cap darkened -40 -> per-deck MEAN 4 (under the
    # flag threshold, so flag semantics are unchanged) but max_spot_divergence
    # reports the raw ~40 so camera.py's per-spot auto-recal cap can refuse
    # what the mean hides.
    f_spot = empty6.copy()
    xs, ys = PIN_SPOTS_PX['L'][5]
    scx = int(round(xs)); scy = int(round(ys + CAP_DY))
    shx, shy = CAP_HALF
    f_spot[scy-shy:scy+shy, scx-shx:scx+shx] -= 40.0
    spot_chk = det6.check_empty_reference(f_spot)
    assert spot_chk['empty_confirmed'], spot_chk            # -40 is confidently 'down'
    assert spot_chk['max_divergence'] < EMPTY_DIVERGENCE_MAX, spot_chk
    assert not spot_chk['flagged'], spot_chk
    assert spot_chk['max_spot_divergence'] > 30.0, spot_chk

    # reference_divergence shape-mismatch guard
    try:
        det6.reference_divergence(np.zeros((100, 100), dtype=np.uint8))
        raise AssertionError("reference_divergence shape mismatch not flagged")
    except FrameError:
        pass
    # is_empty_deck is defensive against a malformed detail dict
    assert det6.is_empty_deck({}) is False
    assert det6.is_empty_deck(None) is False

    # a self-check must NOT poison the scoring path's stale tracking: score a
    # frame (sets _last_sig), run a self-check on the SAME bytes, then re-score
    # the same frame — it must still raise StaleFrameError (sig preserved).
    det7 = DualDeckDetector(empty6, mirror=False)
    det7.detect(empty6)                       # primes _last_sig with empty6's hash
    scored_detail = det7.last_detail          # the scoring pass's detail dict
    chk7 = det7.check_empty_reference(empty6) # stale gate off → no raise, no clobber
    # ...nor the scoring path's last_detail (camera.detect_lane's low-confidence
    # gate reads it right after a scored pass): the self-check's own detail is
    # returned in the verdict, but last_detail must still be the SCORED pass's.
    assert det7.last_detail is scored_detail, \
        "self-check clobbered last_detail (scoring low-confidence gate state)"
    assert chk7['detail'] is not scored_detail and chk7['empty_confirmed'], chk7
    try:
        det7.detect(empty6)                   # same bytes again → must still be stale
        raise AssertionError("self-check clobbered the scoring stale-frame guard")
    except StaleFrameError:
        pass
    print("camera-health + empty-ref self-check OK")

    print("pin_detect self-tests PASSED")
