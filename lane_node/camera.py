#!/usr/bin/env python3
"""
camera.py — T-Camera capture + dual-deck pin detection for the lane node.

ONE QubicaAMF T-Camera per lane-pair sees BOTH decks in one 720x576 PAL frame.
This module owns the capture handle + the calibrated DualDeckDetector and turns
"a ball was thrown on lane N" into "the 10-bit standing-pin mask for lane N".

WHY A SEPARATE MODULE (not in lane_node.py):
  lane_node.py imports gpiozero at module load → it can only be imported on the
  Pi. This module is pure cv2/numpy, so it imports + UNIT-TESTS on any machine
  (inject frames; fake the grabber). The detection math (pin_detect) is numpy-
  only; only frame capture touches cv2/PyAV, and that's lazy + optional.

RESPONSIBILITIES:
  * own the cv2.VideoCapture handle (lazy-open, thread-safe, auto-reopen on fail)
  * own the DualDeckdetector + the EMPTY REFERENCE frame (per-install, real
    cleared-deck capture — NOT the synthetic calibration empty)
  * grab_frame() -> gray ndarray | None
  * detect_lane(lane_id) -> 10-bit mask | None   (None = not ready / capture fail)
  * capture an empty reference at install time (CLI: --capture-empty; refuses a
    non-empty deck unless --force) + explicit reload_empty_reference() — the
    reference is never refreshed silently during scoring

TIMING is owned by the caller (the asyncio daemon): it waits the settle window
after DIELL, then calls detect_lane() (via asyncio.to_thread, since cv2 blocks).
SETTLE_S lives here as the single source of truth; the daemon reads it.

SAFE DEGRADATION: if the empty reference is missing, capture fails, the frame is
unusable (pin_detect FrameError/StaleFrameError), or the detection pass is
LOW CONFIDENCE (pin_detect.last_detail — margins too close to DET_THR or drift
out of bounds), detect_lane returns None. The daemon treats None as "no pin
data" → falls back to the manual desk-score path (the safe Phase-8a default),
never a bogus auto-score.
"""
from __future__ import annotations
import os
import time
import threading
import logging

import numpy as np

import pin_detect  # same dir; DualDeckDetector + _to_gray + DECK_TO_LANE + DET_THR

log = logging.getLogger("camera")

# --- settle window (single source of truth; the daemon reads SETTLE_S) ---------
# Seconds to wait AFTER the DIELL ball-detect before grabbing the frame: the ball
# has reached the deck and the pins have stopped rocking, but the (existing)
# pinsetter hasn't swept them yet. Manual hint: pin data settles ~2.5 s after the
# sweep reaches 66°. FIELD: measure the real window on 21/22 and tune.  # CONFIRM
SETTLE_S = float(os.environ.get("WSL_LANE_CAMERA_SETTLE_S", "2.5"))

# --- capture freshness (env-overridable; 0 restores the pre-2026-06-10 path) ----
# cv2 keeps a persistent handle and V4L2/DSHOW drivers buffer a few frames, so a
# bare read() can return a frame from BEFORE the settle window. Flush this many
# frames with cap.grab() right before the scored read so the frame is current.
# (The byte-identical worst case is already refused by pin_detect's
# StaleFrameError; the flush fixes the near-stale case.) Cost ~40 ms/frame at
# PAL 25 fps — negligible inside the SETTLE_S window.
CV2_FLUSH_FRAMES = int(os.environ.get("WSL_LANE_CAMERA_CV2_FLUSH", "2"))
# PyAV opens the device cold on every grab; the first decoded frame(s) after an
# open can be stale/black before the capture pipeline fills. Decode-and-discard
# this many frames inside the SAME open before trusting the output.
AV_WARMUP_FRAMES = int(os.environ.get("WSL_LANE_CAMERA_AV_WARMUP", "3"))

# --- two-frame deck-stability check (DEFAULT OFF = current blind-sleep timing) --
# When WSL_LANE_CAMERA_STABILITY=1, detect_lane()'s live grab takes consecutive
# frames STABILITY_GAP_S apart and scores only once the deck band's mean abs
# difference is <= STABILITY_DIFF_THR (a moving sweep / rocking pins cannot
# produce two matching frames). Extra wait is capped at STABILITY_MAX_EXTRA_S —
# the daemon already slept SETTLE_S before calling, so the default cap keeps the
# total <= SETTLE_S*3 — then we proceed with a WARNING (never drop the ball).
# OFF by default until STABILITY_DIFF_THR is field-tuned against the real analog
# noise floor on 21/22: a threshold below the noise floor would delay EVERY ball
# by the cap (and the server's CYCLE reply with it).  # CONFIRM field-tune
STABILITY_CHECK = os.environ.get("WSL_LANE_CAMERA_STABILITY", "0") == "1"
STABILITY_GAP_S = float(os.environ.get("WSL_LANE_CAMERA_STABILITY_GAP_S", "0.2"))
STABILITY_DIFF_THR = float(os.environ.get("WSL_LANE_CAMERA_STABILITY_DIFF", "6.0"))
STABILITY_MAX_EXTRA_S = float(os.environ.get(
    "WSL_LANE_CAMERA_STABILITY_MAX_S", str(SETTLE_S * 2.0)))
STABILITY_BAND = (180, 280)  # calib-space rows spanning both pin decks (720x576)

# Capture device (cv2 index or a path/URL PyAV can open).
CAMERA_DEVICE = os.environ.get("WSL_LANE_CAMERA_DEVICE", "0")

# Per-install empty-reference frame (real cleared deck, both lanes empty, same
# camera/mount/framing as calibration: 720x576). Defaults next to this module.
EMPTY_REF_PATH = os.environ.get(
    "WSL_LANE_EMPTY_REF",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "empty_ref.png"),
)


def _load_gray_png(path):
    """Load a PNG as a float32 grayscale ndarray (no cv2 dependency)."""
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        return np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    except Exception as e:  # PIL missing or file unreadable
        log.warning(f"camera: could not load empty ref {path!r}: {e}")
        return None


class PairCamera:
    """Capture + detect for one lane-pair (one camera, both decks).

    Thread-safe: grab_frame() serializes on a lock so concurrent detect_lane()
    calls (both lanes throwing within the settle window) don't race the single
    VideoCapture handle.
    """

    def __init__(self, deck_to_lane=None, empty_ref_path=EMPTY_REF_PATH,
                 device=CAMERA_DEVICE, det_thr=None, _grabber=None):
        self.deck_to_lane = dict(deck_to_lane) if deck_to_lane else dict(pin_detect.DECK_TO_LANE)
        self.empty_ref_path = empty_ref_path
        self.device = device
        self.det_thr = pin_detect.DET_THR if det_thr is None else det_thr
        self._lock = threading.Lock()
        self._cap = None          # lazy cv2.VideoCapture
        self._grabber = _grabber  # test seam: callable() -> gray ndarray | None
        self._detector = None

        empty = _load_gray_png(empty_ref_path) if empty_ref_path else None
        if empty is not None:
            self._detector = pin_detect.DualDeckDetector(
                empty, thr=self.det_thr, deck_to_lane=self.deck_to_lane)
            log.info(f"camera: detector ready (empty ref {empty_ref_path}, "
                     f"{empty.shape[1]}x{empty.shape[0]}, thr={self.det_thr})")
        else:
            log.warning(f"camera: NO empty reference at {empty_ref_path!r} → "
                        f"detect_lane() returns None → daemon uses manual scoring. "
                        f"Capture one at install: python camera.py --capture-empty")

    # -- readiness ----------------------------------------------------------
    @property
    def ready(self) -> bool:
        """True once a detector (with empty ref) exists. False → manual fallback."""
        return self._detector is not None

    def lanes(self):
        return sorted(self.deck_to_lane.values())

    def reload_empty_reference(self, path=None):
        """EXPLICITLY (re)load the empty reference and rebuild the detector.

        Operator/installer action only (e.g. right after
        `python camera.py --capture-empty`) — the reference is NEVER refreshed
        silently during scoring. On any failure the previous detector (if any)
        is kept, so a bad reload can't take a working lane down. Returns
        self.ready (True once a detector exists).
        """
        p = path if path is not None else self.empty_ref_path
        empty = _load_gray_png(p) if p else None
        if empty is None:
            log.warning(f"camera: reload_empty_reference: no usable image at "
                        f"{p!r}; keeping the previous detector")
            return self.ready
        try:
            det = pin_detect.DualDeckDetector(
                empty, thr=self.det_thr, deck_to_lane=self.deck_to_lane)
        except Exception as e:
            log.warning(f"camera: reload_empty_reference: detector rebuild "
                        f"failed ({e}); keeping the previous detector")
            return self.ready
        with self._lock:
            self._detector = det
            self.empty_ref_path = p
        log.info(f"camera: empty reference reloaded from {p} "
                 f"({empty.shape[1]}x{empty.shape[0]}, thr={self.det_thr})")
        return True

    # -- capture ------------------------------------------------------------
    # Backend: cv2 if installed, else PyAV (the Pi has `av`, not cv2 — see the
    # repo requirements). Both reduce to "give me one frame as a gray ndarray."
    # The cv2 path keeps a persistent VideoCapture handle (fast re-reads); the
    # PyAV path opens/grabs-one/closes per capture (captures are seconds apart,
    # so per-grab open cost is fine and avoids stale-handle bugs).
    def _ensure_cap(self):
        """Lazy-open the cv2 capture. Returns the handle or None (no cv2)."""
        if self._cap is not None:
            return self._cap
        try:
            import cv2
        except ImportError:
            return None
        dev = int(self.device) if str(self.device).isdigit() else self.device
        cap = cv2.VideoCapture(dev)
        if not cap.isOpened():
            log.warning(f"camera: cv2.VideoCapture({dev!r}) failed to open")
            try:
                cap.release()
            except Exception:
                pass
            return None
        try:
            # shrink the driver's frame queue; not all backends honor it (the
            # CV2_FLUSH_FRAMES grab-and-discard below is the portable fix)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self._cap = cap
        return cap

    def _grab_cv2(self):
        cap = self._ensure_cap()
        if cap is None:
            return None
        try:
            for _ in range(max(0, CV2_FLUSH_FRAMES)):
                cap.grab()   # discard buffered frames so the scored read is current
            ok, frame = cap.read()
        except Exception as e:
            log.warning(f"camera: cv2 read error: {e}")
            ok, frame = False, None
        if not ok or frame is None:
            log.warning("camera: cv2 read returned no frame; closing handle for reopen")
            self._close_cap_locked()
            return None
        return frame

    def _av_device(self):
        """Map CAMERA_DEVICE to a (file, format) PyAV can open. A bare index N
        becomes /dev/videoN with the v4l2 demuxer (Linux/Pi); a path is used
        as-is (format autodetected)."""
        d = str(self.device)
        if d.isdigit():
            return f"/dev/video{d}", "v4l2"
        return d, None

    def _grab_av(self):
        """Open the capture device with PyAV, decode-and-discard AV_WARMUP_FRAMES
        (the first frames after a cold open can be stale/black), return the next
        frame as an RGB ndarray. Open/close per call (robust; captures are
        seconds apart)."""
        try:
            import av
        except ImportError:
            return None
        file, fmt = self._av_device()
        try:
            container = av.open(file, format=fmt) if fmt else av.open(file)
        except Exception as e:
            log.warning(f"camera: PyAV open({file!r}, format={fmt!r}) failed: {e}")
            return None
        try:
            discard = max(0, AV_WARMUP_FRAMES)
            for i, frame in enumerate(container.decode(video=0)):
                if i < discard:
                    continue   # warm-up discard within this open
                return frame.to_ndarray(format="rgb24")
            log.warning(f"camera: PyAV decoded no frame "
                        f"(after {discard} warm-up discards)")
            return None
        except Exception as e:
            log.warning(f"camera: PyAV decode error: {e}")
            return None
        finally:
            try:
                container.close()
            except Exception:
                pass

    def grab_frame(self):
        """Grab ONE frame as float32 grayscale, or None on failure.

        Thread-safe. Order: injected grabber (tests) → cv2 → PyAV. Returns None
        if no backend can produce a frame → daemon falls back to manual scoring.
        """
        with self._lock:
            if self._grabber is not None:
                frame = self._grabber()
                return pin_detect._to_gray(frame) if frame is not None else None
            frame = self._grab_cv2()
            if frame is None:
                frame = self._grab_av()
            if frame is None:
                return None
            return pin_detect._to_gray(frame)

    def _deck_band(self, gray):
        """Rows of `gray` spanning both pin decks (STABILITY_BAND, calib-space)."""
        sy = gray.shape[0] / pin_detect.CALIB_FRAME_SIZE[1]
        y0 = max(0, int(round(STABILITY_BAND[0] * sy)))
        y1 = min(gray.shape[0], max(y0 + 1, int(round(STABILITY_BAND[1] * sy))))
        return gray[y0:y1, :]

    def _grab_stable_frame(self):
        """Two-frame deck-stability grab (used when STABILITY_CHECK is on).

        Re-grabs every STABILITY_GAP_S until two consecutive frames' deck band
        differs by <= STABILITY_DIFF_THR (mean abs gray — a moving sweep or
        still-rocking pins can't produce two matching frames), then returns the
        newer frame. After STABILITY_MAX_EXTRA_S it WARNs and returns the latest
        frame anyway (the daemon already waited SETTLE_S before calling; the cap
        bounds total delay). Returns None only on capture failure.
        """
        prev = self.grab_frame()
        if prev is None:
            return None
        deadline = time.monotonic() + max(STABILITY_GAP_S, STABILITY_MAX_EXTRA_S)
        while True:
            time.sleep(STABILITY_GAP_S)
            cur = self.grab_frame()
            if cur is None:
                return None
            if cur.shape == prev.shape:
                diff = float(np.abs(self._deck_band(cur) - self._deck_band(prev)).mean())
                if diff <= STABILITY_DIFF_THR:
                    return cur
            else:
                diff = float("inf")   # resolution flapped mid-grab; keep trying
            if time.monotonic() >= deadline:
                log.warning(f"camera: deck never settled (last diff {diff:.1f} > "
                            f"{STABILITY_DIFF_THR:g}) after +{STABILITY_MAX_EXTRA_S:g}s; "
                            f"scoring the latest frame anyway")
                return cur
            prev = cur

    def _close_cap_locked(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def close(self):
        with self._lock:
            self._close_cap_locked()

    # -- detect -------------------------------------------------------------
    def detect_lane(self, lane_id, frame=None):
        """Return the 10-bit standing-pin mask for `lane_id`, or None.

        None means "no usable pin data" (detector not ready, capture failed,
        lane not on this camera, frame rejected by pin_detect, or the detection
        pass was LOW CONFIDENCE) → the daemon falls back to manual scoring.
        Pass `frame` to detect from an already-captured frame (tests / reuse).
        """
        if not self.ready:
            return None
        if lane_id not in self.deck_to_lane.values():
            log.warning(f"camera: lane {lane_id} not on this pair {self.lanes()}")
            return None
        if frame is None:
            frame = self._grab_stable_frame() if STABILITY_CHECK else self.grab_frame()
            if frame is None:
                return None
        try:
            mask = self._detector.detect_lane(frame, lane_id)
        except Exception as e:
            log.warning(f"camera: detect_lane({lane_id}) error: {e}")
            return None
        # low-confidence gate: margins too close to DET_THR or drift out of
        # bounds → don't trust a best-guess mask; None → awaiting_manual.
        detail = getattr(self._detector, "last_detail", None)
        if detail and detail.get('low_confidence'):
            log.warning(f"camera: lane {lane_id} detection LOW CONFIDENCE -> "
                        f"None (awaiting_manual): "
                        + "; ".join(detail.get('reasons', [])))
            return None
        return mask

    def detect_both(self, frame=None):
        """Return {lane_id: mask} for both decks from one frame, or None.

        None = no usable pin data (not ready, capture failed, or the frame was
        rejected by pin_detect) — same sentinel as detect_lane, so a future
        daily canary can treat None as "detector not ready".
        """
        if not self.ready:
            return None
        if frame is None:
            frame = self.grab_frame()
            if frame is None:
                return None
        try:
            masks = self._detector.detect(frame)  # {'L':.., 'R':..}
        except Exception as e:
            log.warning(f"camera: detect_both error: {e} -> None")
            return None
        out = {}
        for dk, ln in self.deck_to_lane.items():
            if ln is not None:
                out[ln] = masks[dk]
        return out


# ---------------------------------------------------------------------------
# install-time helper: capture an empty-reference frame
# ---------------------------------------------------------------------------
def _candidate_reads_empty(gray, old_ref_path):
    """Non-empty-deck guard: score the candidate empty-ref frame against the
    PREVIOUS reference. Returns False (refuse to save) if any pins read
    STANDING — i.e. someone ran --capture-empty with pins on a deck, which
    would poison every future detection. Validation problems (no/unreadable
    old ref, resolution change, detector error) WARN and return True: the old
    reference may itself be the thing being replaced."""
    old = _load_gray_png(old_ref_path)
    if old is None:
        return True
    try:
        det = pin_detect.DualDeckDetector(old, stale_check=False)
        detail = det.detect_detail(gray)
    except Exception as e:
        log.warning(f"capture_empty_reference: could not validate candidate "
                    f"against the previous reference ({e}); saving anyway")
        return True
    standing = {dk: [p for p in range(1, 11) if m & (1 << (p - 1))]
                for dk, m in detail['masks'].items() if m}
    if standing:
        log.error(f"capture_empty_reference: REFUSING to save — pins read "
                  f"STANDING vs the previous reference: {standing}. Clear BOTH "
                  f"decks and retry (or --force if the old reference is bad).")
        return False
    lc = {dk: p for dk, p in detail['low_conf_pins'].items() if p}
    if lc:
        log.warning(f"capture_empty_reference: candidate reads empty but pins "
                    f"{lc} are within the confidence band of DET_THR — verify "
                    f"the decks really are clear before trusting this reference")
    return True


def capture_empty_reference(out_path=EMPTY_REF_PATH, device=CAMERA_DEVICE, warmup=5,
                            force=False):
    """Grab a frame from the camera and save it as the empty reference PNG.

    Run with BOTH decks CLEARED (no pins). Reuses PairCamera's capture stack
    (cv2 if present, else PyAV — the Pi has PyAV), so it works wherever live
    capture works. Discards `warmup` frames first so auto-exposure settles.

    Guards (install-time only — scoring NEVER refreshes the reference):
      * if a previous reference exists, the candidate is scored against it and
        REFUSED if any pins read standing (force=True / --force overrides);
      * the previous reference is backed up to <out_path>.bak before overwrite.
    Returns the saved path or None.
    """
    cam = PairCamera(empty_ref_path=None, device=device)  # no detector needed
    try:
        gray = None
        for _ in range(max(1, warmup)):
            gray = cam.grab_frame()      # float32 gray ndarray | None
        if gray is None:
            log.error("capture_empty_reference: no frame captured (no cv2/PyAV "
                      "backend or device unavailable)")
            return None
        if os.path.exists(out_path):
            if not force and not _candidate_reads_empty(gray, out_path):
                return None
            try:
                import shutil
                shutil.copy2(out_path, out_path + ".bak")
                log.info(f"capture_empty_reference: previous reference backed "
                         f"up to {out_path}.bak")
            except Exception as e:
                log.warning(f"capture_empty_reference: backup of previous "
                            f"reference failed ({e}); overwriting anyway")
        from PIL import Image
        Image.fromarray(gray.astype(np.uint8)).save(out_path)
        log.info(f"capture_empty_reference: saved {out_path} "
                 f"({gray.shape[1]}x{gray.shape[0]})")
        return out_path
    finally:
        cam.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser(description="T-Camera capture/detect helper")
    ap.add_argument("--capture-empty", action="store_true",
                    help="capture + save the empty reference (clear BOTH decks first)")
    ap.add_argument("--force", action="store_true",
                    help="with --capture-empty: skip the standing-pins-vs-previous-"
                         "reference guard (use when the old reference is bad)")
    ap.add_argument("--out", default=EMPTY_REF_PATH, help="empty-ref output path")
    ap.add_argument("--device", default=CAMERA_DEVICE, help="cv2 device index or path")
    ap.add_argument("--test", action="store_true", help="detect once and print masks")
    args = ap.parse_args()

    if args.capture_empty:
        p = capture_empty_reference(args.out, args.device, force=args.force)
        raise SystemExit(0 if p else 1)
    if args.test:
        cam = PairCamera(device=args.device)
        if not cam.ready:
            print("camera not ready (no empty ref)"); raise SystemExit(1)
        print("masks:", cam.detect_both())
        raise SystemExit(0)
    ap.print_help()
