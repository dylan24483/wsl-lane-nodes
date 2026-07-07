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
import hashlib
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

# --- empty-reference auto-recalibration (idea #14, DEFAULT OFF) ----------------
# The slowest-failing mode of camera scoring is the stored empty reference
# DRIFTING (lighting change, camera shift) so every read degrades. self_check_empty()
# detects this on a KNOWN-EMPTY-DECK moment and always FLAGS it (observe-only).
# If WSL_CAM_AUTO_RECAL=1 it ALSO refreshes the reference from that confirmed-empty
# frame — OFF by default because a bad auto-update corrupts ALL future scoring, so
# it must be a deliberate operator opt-in. Even when on, it only ever fires on a
# deck that read fully empty with high confidence AND whose drift exceeds the
# pin_detect threshold but stays under AUTO_RECAL_MAX (a divergence past that is
# too large to be benign drift — it WARNs and refuses, leaving the ref for a human).
AUTO_RECAL = os.environ.get("WSL_CAM_AUTO_RECAL", "0") == "1"
AUTO_RECAL_MAX = float(os.environ.get("WSL_CAM_AUTO_RECAL_MAX",
                                      str(pin_detect.CONF_BAND)))


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
        # Frozen-pipeline tracker for the OBSERVE-ONLY health/self-check grabs
        # (SEPARATE from the scoring path's pin_detect stale gate, which the
        # self-check deliberately bypasses): a hung camera / stale driver buffer
        # re-serves one old frame forever, and analog capture noise makes a true
        # byte-identical repeat impossible — so a repeat = frozen capture chain.
        self._health_sig = None
        self._health_repeats = 0

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
            # Serialize the whole detect pass under the capture lock:
            # detect_detail mutates shared detector state (_last_sig stale
            # tracking, last_detail), so two concurrent detect_lane() calls
            # (both lanes throwing within the settle window) must not
            # interleave. The gate below reads THIS pass's returned detail —
            # never detector.last_detail, which the other lane's pass could
            # overwrite between our detect and the read (a low-confidence mask
            # would then be trusted and auto-scored).
            with self._lock:
                detail = self._detector.detect_detail(frame)
        except Exception as e:
            log.warning(f"camera: detect_lane({lane_id}) error: {e}")
            return None
        # low-confidence gate: margins too close to DET_THR or drift out of
        # bounds → don't trust a best-guess mask; None → awaiting_manual.
        if detail.get('low_confidence'):
            log.warning(f"camera: lane {lane_id} detection LOW CONFIDENCE -> "
                        f"None (awaiting_manual): "
                        + "; ".join(detail.get('reasons', [])))
            return None
        for dk, ln in self.deck_to_lane.items():
            if ln == lane_id:
                return detail['masks'][dk]
        return None   # unreachable: lane membership checked above

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
            # serialized like detect_lane: the detect pass mutates shared state
            with self._lock:
                masks = self._detector.detect(frame)  # {'L':.., 'R':..}
        except Exception as e:
            log.warning(f"camera: detect_both error: {e} -> None")
            return None
        out = {}
        for dk, ln in self.deck_to_lane.items():
            if ln is not None:
                out[ln] = masks[dk]
        return out

    # -- health + empty-reference self-check (idea #14) — OBSERVE-ONLY -------
    # Neither method touches a relay or the scored detect path. frame_health is
    # pure observation. self_check_empty FLAGS a drifted reference by default and
    # only refreshes it when WSL_CAM_AUTO_RECAL is explicitly set (a bad refresh
    # would corrupt all scoring). The daemon may call frame_health on its existing
    # heartbeat and self_check_empty after a clean cycle / full respot.
    def _grab_health_frame(self):
        """grab_frame() + frozen-pipeline tracking for the health/self-check paths.

        Returns (frame, repeats): repeats > 0 means this grab is byte-identical
        to the previous health/self-check grab — a frozen capture pipeline
        (camera hang / stale driver buffer re-serving one old frame), the exact
        failure StaleFrameError catches on the scoring path. Analog capture
        noise makes a true repeat impossible, so even one repeat is decisive.
        Tracked separately from the scoring _last_sig so health checks never
        perturb scoring state."""
        frame = self.grab_frame()
        if frame is None:
            return None, 0
        sig = hashlib.sha1(frame.tobytes()).digest()
        with self._lock:
            if sig == self._health_sig:
                self._health_repeats += 1
            else:
                self._health_sig = sig
                self._health_repeats = 0
            reps = self._health_repeats
        return frame, reps

    def frame_health(self, frame=None):
        """Exposure/focus health of one frame, for daemon/telemetry. OBSERVE-ONLY.

        Returns pin_detect.frame_health(...)'s dict (mean/variance/focus/ok/reasons)
        plus 'grabbed' (False if capture failed) and 'stale' (True if the grabbed
        frame is byte-identical to the previous health/self-check grab — a FROZEN
        capture pipeline re-serving one old healthy scene must not read as a
        healthy camera, so stale also forces ok=False). Never raises: a capture
        failure yields ok=False with a reason, so the caller can surface a dead
        camera the same way it surfaces a bad exposure.

        MONITORING NOTE: alert on grabbed=False and stale=True, not just the
        content metrics — a dead/frozen camera shows up in those two fields.
        Staleness is only tracked for frames grabbed HERE (frame=None); an
        explicitly passed frame is not a capture. Does NOT need a loaded empty
        reference (health is about the live frame, not the calibration)."""
        stale_reps = 0
        if frame is None:
            frame, stale_reps = self._grab_health_frame()
            if frame is None:
                return {'mean': 0.0, 'variance': 0.0, 'focus': 0.0, 'ok': False,
                        'grabbed': False, 'stale': False,
                        'reasons': ['capture failed (no cv2/PyAV frame)']}
        h = pin_detect.frame_health(frame)
        h['grabbed'] = True
        h['stale'] = stale_reps > 0
        if stale_reps > 0:
            h['ok'] = False
            h['reasons'] = list(h['reasons']) + [
                f"frame byte-identical to the previous health/self-check grab "
                f"(repeat #{stale_reps}) -- frozen capture pipeline?"]
        return h

    def self_check_empty(self, frame=None, auto_recal=None):
        """Self-check the stored empty reference at a KNOWN-EMPTY-DECK moment.

        The CALLER asserts the deck is empty right now (the pinsetter just did a
        full respot, or pin_detect read all-pins-down with high confidence after a
        cycle). This compares the live empty frame's cap ROIs to the stored
        reference (drift-corrected) and FLAGS divergence beyond the pin_detect
        threshold. OBSERVE-ONLY unless auto-recal is enabled.

        Returns the pin_detect verdict dict (empty_confirmed / divergence /
        max_divergence / max_spot_divergence / flagged / reason) plus:
          grabbed        bool — a frame was available
          stale          bool — grabbed frame was byte-identical to the previous
                                health/self-check grab (frozen capture pipeline;
                                the check is SKIPPED — a frozen old empty frame
                                must not confirm a dead camera as healthy)
          recalibrated   bool — the reference was refreshed (auto-recal only)
        On 'detector not ready' or capture failure returns a dict with
        empty_confirmed=False, flagged=False, grabbed=<bool>. Never raises.
        MONITORING NOTE: alert on grabbed=False and stale=True, not just
        flagged=True — a dead/frozen camera reports flagged=False here.

        AUTO-RECAL (WSL_CAM_AUTO_RECAL, default OFF): when on AND the deck is
        confirmed empty AND the drift is flagged but still under AUTO_RECAL_MAX
        — BOTH the per-deck mean AND every single spot's |divergence| (a single
        corrupted cap ROI dilutes 10x into the mean but would poison the
        reference with a permanent phantom pin) — AND a SECOND independent grab
        re-confirms all of the above, the confirmed frame is persisted as the
        new empty reference (backups rotated) and the detector is rebuilt.
        A divergence past AUTO_RECAL_MAX is too large to be benign drift — it is
        logged and REFUSED, leaving the reference for a human to re-capture.
        Default OFF means the production behavior is flag-only; nothing
        auto-updates without the operator opting in.

        KNOWN LIMIT (documented, not fully fixable here): emptiness is judged
        through the SAME stored reference being checked, so a misaligned/bumped
        camera whose standing pins sample off-cap can still read 'empty'. When
        the daemon wiring lands, callers must add a non-self-referential
        machine-state gate (only call this in the FSM's post-sweep/full-respot
        known-empty window).  # CONFIRM daemon wiring"""
        recal = AUTO_RECAL if auto_recal is None else bool(auto_recal)
        if not self.ready:
            return {'empty_confirmed': False, 'divergence': {}, 'max_divergence': 0.0,
                    'flagged': False, 'grabbed': False, 'stale': False,
                    'recalibrated': False,
                    'reason': 'detector not ready (no empty reference) -- self-check skipped'}
        if frame is None:
            frame, stale_reps = self._grab_health_frame()
            if frame is None:
                return {'empty_confirmed': False, 'divergence': {},
                        'max_divergence': 0.0, 'flagged': False, 'grabbed': False,
                        'stale': False, 'recalibrated': False,
                        'reason': 'capture failed -- self-check skipped'}
            if stale_reps > 0:
                # Frozen capture pipeline: an old empty frame re-served forever
                # would read 'empty reference healthy' — the exact slow failure
                # this check exists to catch. Skip; never confirm or recal.
                log.warning("camera: self_check_empty frame byte-identical to the "
                            "previous health/self-check grab (repeat #%d) -- "
                            "frozen capture pipeline? Self-check skipped.", stale_reps)
                return {'empty_confirmed': False, 'divergence': {},
                        'max_divergence': 0.0, 'flagged': False, 'grabbed': True,
                        'stale': True, 'recalibrated': False,
                        'reason': 'frame byte-identical to the previous grab '
                                  '(frozen capture pipeline?) -- self-check skipped'}
        try:
            # Serialize the detection pass: check_empty_reference mutates shared
            # detector state (last_detail save/restore), and a concurrent scored
            # detect_lane() pass must not interleave with it (see detect_lane).
            with self._lock:
                verdict = self._detector.check_empty_reference(frame)
        except pin_detect.FrameError as e:
            return {'empty_confirmed': False, 'divergence': {}, 'max_divergence': 0.0,
                    'flagged': False, 'grabbed': True, 'stale': False,
                    'recalibrated': False,
                    'reason': f'frame unusable for self-check ({e})'}
        except Exception as e:
            log.warning(f"camera: self_check_empty error: {e}")
            return {'empty_confirmed': False, 'divergence': {}, 'max_divergence': 0.0,
                    'flagged': False, 'grabbed': True, 'stale': False,
                    'recalibrated': False,
                    'reason': f'self-check error ({e})'}
        verdict = dict(verdict)
        verdict.pop('detail', None)   # drop the heavy nested dict for telemetry
        verdict['grabbed'] = True
        verdict['stale'] = False
        verdict['recalibrated'] = False
        if verdict['flagged']:
            spot_max = verdict.get('max_spot_divergence')
            if not recal:
                log.warning("camera: empty-reference drift FLAGGED (auto-recal OFF): %s",
                            verdict['reason'])
            elif verdict['max_divergence'] > AUTO_RECAL_MAX:
                log.error("camera: empty-reference drift %.2f exceeds AUTO_RECAL_MAX "
                          "%.2f -- REFUSING auto-recal, re-capture manually: %s",
                          verdict['max_divergence'], AUTO_RECAL_MAX, verdict['reason'])
            elif spot_max is None or spot_max > AUTO_RECAL_MAX:
                # PER-SPOT cap: max_divergence is a per-deck MEAN over 10 pins,
                # so a single corrupted cap ROI (~65-99 gray: shadow, grease,
                # sweep-board edge) dilutes to a mean under the cap yet would
                # bake a permanent phantom pin into the reference. EVERY spot
                # must be under the cap; an unknown per-spot value refuses
                # (fail toward safe: reference kept for a human).
                log.error("camera: empty-reference drift has a single-spot "
                          "divergence %s exceeding AUTO_RECAL_MAX %.2f -- REFUSING "
                          "auto-recal (localized corruption, not benign drift); "
                          "re-capture manually: %s",
                          "?" if spot_max is None else f"{spot_max:.2f}",
                          AUTO_RECAL_MAX, verdict['reason'])
            else:
                confirm, why = self._confirm_empty_for_recal(frame)
                if confirm is None:
                    log.error("camera: auto-recal REFUSED (confirmation grab): %s "
                              "-- keeping the current reference", why)
                else:
                    verdict['recalibrated'] = self._auto_recalibrate(confirm, verdict)
        return verdict

    def _confirm_empty_for_recal(self, first_frame):
        """Second, independent confirmation grab before an auto-recal persists.

        The empty gate in check_empty_reference is SELF-REFERENTIAL (it re-reads
        the same possibly-drifted reference) and no machine-state signal is wired
        yet, so before rewriting the reference we require a SECOND live grab that
        (a) is not byte-identical to the first (frozen-pipeline guard), (b)
        independently re-confirms empty + the drift flag, and (c) stays under
        both the per-deck and per-spot AUTO_RECAL_MAX caps. Returns (frame2, '')
        on success or (None, reason) — any doubt refuses the recal, keeping the
        current reference (the safe direction). Note: a caller that passed an
        explicit frame with no live capture backend will always refuse here —
        auto-recal requires a live camera by design.

        WHAT THIS STILL CANNOT GUARANTEE: both grabs judge emptiness through the
        SAME stored reference, so a misaligned/bumped camera whose standing pins
        sample off-cap can still read 'empty'. A non-self-referential gate (FSM
        post-sweep known-empty window / operator attestation) must come from the
        daemon wiring when it lands.  # CONFIRM daemon wiring
        """
        frame2 = self.grab_frame()
        if frame2 is None:
            return None, "no confirmation frame (capture failed)"
        first_gray = pin_detect._to_gray(first_frame)
        if first_gray.shape == frame2.shape and np.array_equal(first_gray, frame2):
            return None, ("confirmation frame byte-identical to the first "
                          "(frozen capture pipeline?)")
        try:
            with self._lock:
                v2 = self._detector.check_empty_reference(frame2)
        except Exception as e:
            return None, f"confirmation self-check failed ({e})"
        if not v2.get('empty_confirmed'):
            return None, "confirmation grab did not re-confirm an empty deck"
        if not v2.get('flagged'):
            return None, "confirmation grab did not reproduce the drift flag"
        spot_max2 = v2.get('max_spot_divergence')
        if (v2.get('max_divergence', float('inf')) > AUTO_RECAL_MAX
                or spot_max2 is None or spot_max2 > AUTO_RECAL_MAX):
            return None, "confirmation grab exceeded an AUTO_RECAL_MAX cap"
        return frame2, ""

    def _auto_recalibrate(self, frame, verdict):
        """Persist `frame` as the new empty reference + rebuild the detector.
        Called ONLY from self_check_empty after every empty/confidence/bounds
        guard has passed and auto-recal is enabled. Failure is non-fatal: the old
        reference stays in place (reload_empty_reference keeps the prior detector
        on error). Returns True iff the reference was refreshed."""
        gray = pin_detect._to_gray(frame)
        path = self.empty_ref_path
        if not path:
            log.warning("camera: auto-recal requested but no empty_ref_path; skipped")
            return False
        try:
            from PIL import Image
            if os.path.exists(path):
                try:
                    import shutil
                    if os.path.exists(path + ".bak"):
                        # rotate one extra generation: a repeated auto-recal must
                        # not destroy the last-known-good backup by overwriting
                        # .bak with a newer (possibly already-poisoned) reference.
                        shutil.copy2(path + ".bak", path + ".bak2")
                    shutil.copy2(path, path + ".bak")
                except Exception as e:
                    log.warning(f"camera: auto-recal backup failed ({e}); overwriting")
            tmp = path + ".tmp"
            # explicit PNG format: the .tmp extension can't be auto-detected.
            Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8)).save(tmp, format="PNG")
            os.replace(tmp, path)            # atomic swap into place
        except Exception as e:
            log.warning(f"camera: auto-recal could not save reference ({e}); "
                        f"keeping the previous reference")
            return False
        ok = self.reload_empty_reference(path)
        if ok:
            log.warning("camera: AUTO-RECALIBRATED empty reference from a "
                        "confirmed-empty deck (divergence %.2f). %s",
                        verdict['max_divergence'], verdict['reason'])
        return bool(ok)


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


def _selftest():
    """Synthetic, device-free self-test of the health + empty-ref self-check
    paths (idea #14). Uses the _grabber injection seam, so it runs on any machine
    (no cv2/PyAV/device). Returns 0 on success; raises AssertionError on failure."""
    import tempfile
    from PIL import Image

    rng = np.random.default_rng(14)
    # textured empty deck (clears the focus floor); save as a real PNG so the
    # PairCamera loads a detector exactly like production.
    empty = rng.integers(60, 110, size=(576, 720)).astype(np.uint8)
    tmpdir = tempfile.mkdtemp(prefix="wsl_cam_selftest_")
    ref_path = os.path.join(tmpdir, "empty_ref.png")
    Image.fromarray(empty).save(ref_path)

    # injected grabber returns whatever frame we stage next, plus fresh per-grab
    # noise: real analog capture never repeats byte-identically, and the noise
    # keeps the frozen-pipeline guard quiet on this production-faithful path
    # (the guard itself is tested with a constant grabber further down).
    staged = {'frame': empty.astype(np.float32)}

    def _noisy_grab():
        f = staged['frame']
        return f + rng.normal(0.0, 0.3, f.shape).astype(np.float32)

    cam = PairCamera(empty_ref_path=ref_path, deck_to_lane={'L': 21, 'R': 22},
                     _grabber=_noisy_grab)
    assert cam.ready, "detector should be ready from the saved empty ref"

    # frame_health: textured empty frame is healthy; a black frame is not.
    h = cam.frame_health()
    assert h['ok'] and h['grabbed'], h
    staged['frame'] = np.zeros((576, 720), dtype=np.float32)
    hb = cam.frame_health()
    assert (not hb['ok']) and hb['grabbed'], hb
    # capture-failure health verdict (grabber returns None)
    cam_none = PairCamera(empty_ref_path=ref_path, _grabber=lambda: None)
    hn = cam_none.frame_health()
    assert (not hn['ok']) and (hn['grabbed'] is False), hn

    # self_check_empty on a true empty frame: confirmed, not flagged.
    staged['frame'] = empty.astype(np.float32)
    v_ok = cam.self_check_empty()
    assert v_ok['empty_confirmed'] and not v_ok['flagged'], v_ok
    assert 'detail' not in v_ok, "telemetry verdict should drop the heavy detail dict"
    assert v_ok.get('max_spot_divergence') is not None, v_ok
    assert v_ok['stale'] is False, v_ok

    # drifted empty (cap ROIs locally brighter, drift band untouched): flagged,
    # but with auto-recal OFF the reference is NOT rewritten.
    drift = empty.astype(np.float32).copy()
    for dk in ('L', 'R'):
        for p, (x, y) in pin_detect.PIN_SPOTS_PX[dk].items():
            cx = int(round(x)); cy = int(round(y + pin_detect.CAP_DY))
            hx, hy = pin_detect.CAP_HALF
            drift[cy-hy:cy+hy, cx-hx:cx+hx] = np.clip(
                drift[cy-hy:cy+hy, cx-hx:cx+hx] + 9.0, 0, 255)
    staged['frame'] = drift
    v_flag = cam.self_check_empty(auto_recal=False)
    assert v_flag['empty_confirmed'] and v_flag['flagged'], v_flag
    assert not v_flag['recalibrated'], v_flag
    before = _load_gray_png(ref_path)

    # auto-recal ON, divergence OVER AUTO_RECAL_MAX → REFUSE (reference kept).
    global AUTO_RECAL_MAX
    saved_max = AUTO_RECAL_MAX
    AUTO_RECAL_MAX = 1.0          # force the divergence (~9) above the cap
    try:
        v_refuse = cam.self_check_empty(auto_recal=True)
    finally:
        AUTO_RECAL_MAX = saved_max
    assert v_refuse['flagged'] and not v_refuse['recalibrated'], v_refuse
    assert np.array_equal(before, _load_gray_png(ref_path)), \
        "refused auto-recal must NOT rewrite the reference"
    assert not os.path.exists(ref_path + ".bak"), "refused auto-recal must not back up"

    # PER-SPOT cap: ONE cap darkened ~-80 dilutes the per-deck MEAN to ~8 (under
    # AUTO_RECAL_MAX=10) while that spot still reads confidently 'down' — the old
    # mean-only cap would recalibrate and bake a permanent phantom pin into the
    # reference. The per-spot cap must REFUSE.
    corrupt = empty.astype(np.float32).copy()
    xs, ys = pin_detect.PIN_SPOTS_PX['L'][5]
    ccx = int(round(xs)); ccy = int(round(ys + pin_detect.CAP_DY))
    chx, chy = pin_detect.CAP_HALF
    corrupt[ccy-chy:ccy+chy, ccx-chx:ccx+chx] = np.clip(
        corrupt[ccy-chy:ccy+chy, ccx-chx:ccx+chx] - 80.0, 0, 255)
    staged['frame'] = corrupt
    v_spot = cam.self_check_empty(auto_recal=True)
    assert v_spot['empty_confirmed'] and v_spot['flagged'], v_spot
    assert v_spot['max_divergence'] <= AUTO_RECAL_MAX, v_spot      # the mean dilutes...
    assert v_spot['max_spot_divergence'] > AUTO_RECAL_MAX, v_spot  # ...the spot does not
    assert not v_spot['recalibrated'], v_spot
    assert np.array_equal(before, _load_gray_png(ref_path)), \
        "per-spot-capped auto-recal must NOT rewrite the reference"
    assert not os.path.exists(ref_path + ".bak"), "refused auto-recal must not back up"

    # auto-recal ON, divergence UNDER AUTO_RECAL_MAX → recalibrate (ref rewritten
    # only after a second, non-identical confirmation grab re-confirms it).
    staged['frame'] = drift
    v_recal = cam.self_check_empty(auto_recal=True)   # same drift, default cap
    assert v_recal['recalibrated'], v_recal
    after = _load_gray_png(ref_path)
    assert after is not None and not np.array_equal(before, after), \
        "auto-recal should have rewritten the reference file"
    assert os.path.exists(ref_path + ".bak"), "auto-recal should back up the old ref"
    # after recal, the same drift frame should no longer diverge (ref == frame).
    staged['frame'] = drift
    v_post = cam.self_check_empty(auto_recal=False)
    assert v_post['empty_confirmed'] and not v_post['flagged'], v_post

    # a non-empty deck (a real standing pin) is NEVER flagged or recalibrated.
    pinf = empty.astype(np.float32).copy()
    xp, yp = pin_detect.PIN_SPOTS_PX['L'][1]
    pinf[int(yp)-12:int(yp)+2, int(xp)-5:int(xp)+5] = 240
    staged['frame'] = pinf
    v_pin = cam.self_check_empty(auto_recal=True)
    assert (not v_pin['empty_confirmed']) and (not v_pin['flagged']), v_pin
    assert not v_pin['recalibrated'], v_pin

    # not-ready detector: self_check_empty returns a safe skipped verdict.
    cam_nr = PairCamera(empty_ref_path=None, _grabber=lambda: empty.astype(np.float32))
    assert not cam_nr.ready
    v_nr = cam_nr.self_check_empty()
    assert (not v_nr['empty_confirmed']) and (not v_nr['flagged']), v_nr

    # FROZEN-PIPELINE detection: a constant grabber re-serves byte-identical
    # frames (impossible on real analog capture ⇒ frozen capture chain). The
    # health check must go ok=False/stale, the self-check must SKIP (never
    # 'empty reference healthy'), and a frozen CONFIRMATION grab must refuse
    # an otherwise-valid auto-recal.
    ref2 = os.path.join(tmpdir, "empty_ref_frozen.png")
    Image.fromarray(empty).save(ref2)
    frozen = {'frame': empty.astype(np.float32)}
    camf = PairCamera(empty_ref_path=ref2, deck_to_lane={'L': 21, 'R': 22},
                      _grabber=lambda: frozen['frame'].copy())
    h1 = camf.frame_health()
    assert h1['ok'] and not h1['stale'], h1
    h2 = camf.frame_health()                    # identical bytes -> stale, not ok
    assert (not h2['ok']) and h2['stale'] and h2['grabbed'], h2
    assert any('frozen' in r for r in h2['reasons']), h2
    v_frozen = camf.self_check_empty(auto_recal=True)   # still identical -> skip
    assert v_frozen['stale'] and v_frozen['grabbed'], v_frozen
    assert (not v_frozen['empty_confirmed']) and (not v_frozen['flagged']) \
        and (not v_frozen['recalibrated']), v_frozen
    frozen['frame'] = empty.astype(np.float32) + 0.5    # fresh bytes clear the tracker
    h3 = camf.frame_health()
    assert h3['ok'] and not h3['stale'], h3
    # frozen CONFIRMATION grab: first self-check grab of the drift frame passes
    # every gate, but the confirmation grab re-serves the same bytes -> REFUSE.
    frozen['frame'] = drift.astype(np.float32)
    v_conf = camf.self_check_empty(auto_recal=True)
    assert v_conf['flagged'] and not v_conf['stale'], v_conf
    assert not v_conf['recalibrated'], v_conf
    assert np.array_equal(empty.astype(np.float32), _load_gray_png(ref2)), \
        "frozen confirmation grab must NOT rewrite the reference"

    import shutil as _sh
    _sh.rmtree(tmpdir, ignore_errors=True)
    print("camera self-check + health + auto-recal self-test OK")
    return 0


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
    ap.add_argument("--health", action="store_true",
                    help="grab one frame and print the exposure/focus health verdict")
    ap.add_argument("--check-empty", action="store_true",
                    help="run the empty-reference self-check on the current (assert-empty) "
                         "deck; honors WSL_CAM_AUTO_RECAL")
    ap.add_argument("--selftest", action="store_true",
                    help="device-free synthetic self-test of the health + self-check paths")
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(_selftest())
    if args.capture_empty:
        p = capture_empty_reference(args.out, args.device, force=args.force)
        raise SystemExit(0 if p else 1)
    if args.health:
        cam = PairCamera(empty_ref_path=None, device=args.device)
        print("health:", cam.frame_health()); cam.close()
        raise SystemExit(0)
    if args.check_empty:
        cam = PairCamera(device=args.device)
        if not cam.ready:
            print("camera not ready (no empty ref)"); raise SystemExit(1)
        print("self-check:", cam.self_check_empty()); cam.close()
        raise SystemExit(0)
    if args.test:
        cam = PairCamera(device=args.device)
        if not cam.ready:
            print("camera not ready (no empty ref)"); raise SystemExit(1)
        print("masks:", cam.detect_both())
        raise SystemExit(0)
    ap.print_help()
