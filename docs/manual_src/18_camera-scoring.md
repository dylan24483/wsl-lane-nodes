## 18. Camera Pin Scoring (Track A)

This section documents the **optical pin-scoring** half of the Phase 8 system — "Track A." It is independent of the lane-controller board (Track B). Track A is **read-only with respect to the machine**: it watches the existing QubicaAMF pinsetter camera and computes the score; it never drives the pinsetter. A scoring failure can produce a wrong score, never an unsafe machine action. On any failure the system **falls back to manual desk scoring** automatically.

Read this section to install, operate, calibrate, or extend camera scoring. It is self-contained: an engineer with no prior context can stand the pilot up on lanes 21/22 from here.

> **Scope note.** Track A runs today on the **scoring node software** (`lane_node/`) talking to a small **scoring server** (`server/lane_node_server.py`). It uses the *existing* pinsetter controller to cycle the machine — our cycle relay is wired but is **not** the live machine driver during the scoring pilot. The Track-B controller board (Sections 5–14) is a separate, parallel effort. Where the two interact (the settle-delay vs. the cycle command), it is flagged explicitly below.

---

### 18.1 What Track A does, end to end

```
  QubicaAMF T-Camera (1 per pair, sees BOTH decks)
        │  composite video (PAL, 720×576), Brown=video / Blue=gnd
        ▼
  VIXLW USB capture dongle  →  /dev/video0 on the Pi
        │  one analog frame on demand
        ▼
  lane_node/camera.py  (PairCamera: owns capture handle + empty reference)
        │  float32 grayscale frame
        ▼
  lane_node/pin_detect.py  (DualDeckDetector, "M4" method)
        │  TWO 10-bit standing-pin masks  {'L': maskL, 'R': maskR}
        ▼
  lane_node/lane_node.py  (DIELL ball-detect → settle → capture → BALL_EVENT)
        │  WebSocket ws://<server>:8765   BALL_EVENT{lane, pin_mask}
        ▼
  server/lane_node_server.py  (wsl_scoring_engine.record_ball → running score)
        │  HTTP :8766
        ▼
  scoring display  (wsl_scoring_display.html, polls /api/lane/<N>/scoring)
```

One **T-Camera per lane pair** sits at the pinsetter behind the pins, looking back toward the bowler, and frames **both decks of the pair in a single 720×576 PAL field**. The left half of the image is one deck, the right half the other. The capture dongle hands the Pi one frame per ball; the detector turns each half-image into a 10-bit "which pins are still standing" mask; the daemon ships that mask to the server, which feeds the existing Python bowling scorer and serves the result to the overhead display.

Physical lane mapping is fixed by calibration (Section 18.3): **left image deck = lane 21, right image deck = lane 22**.

---

### 18.2 Hardware: T-Camera, the composite tap, and the VIXLW dongle

| Item | Value / part | Notes |
|---|---|---|
| Camera | QubicaAMF **T-Camera**, one per **lane pair** | Existing house equipment, reused. Mounted at the pinsetter, behind the pins, looking toward the bowler. Sees **both decks** of the pair in one frame. |
| Video format | Composite **PAL**, **720×576** | This is the native capture resolution and the resolution everything is calibrated to (`CALIB_FRAME_SIZE = (720, 576)`). Do not upscale — composite bandwidth + soft focus mean higher resolution adds no real detail. |
| Capture device | **VIXLW** USB composite-capture dongle | Enumerates as a UVC device → `/dev/video0` (the default). Owned and proven. |
| Video tap | **Brown = video, Blue = ground** | The proven composite tap off the T-Camera feed. RCA shell → Blue (the cable's pin-8 ground). |
| Pi capture index | `WSL_LANE_CAMERA_DEVICE`, default `0` (`/dev/video0`) | If the dongle enumerates as `/dev/video1`, set this to `1`. |

> ⚠️ **The #1 field failure is a missing video ground, not a software bug.** A black frame / "mask always 0 or always 1023" almost always means the RCA shell → Blue (cable pin-8) ground is not seated. Reseat the tap ground before touching any code. (Same trap as the original camera tap.)

The camera being **behind** the pins means the image is **mirrored** relative to the bowler's view — see `MIRROR` in Section 18.3.

---

### 18.3 The detection method ("M4") and why naive subtraction failed

The detector lives in `lane_node/pin_detect.py`. Understanding *why* it works the way it does is essential before changing any constant.

#### 18.3.1 Why the obvious method fails

The obvious approach — capture a frame, subtract a stored "empty deck" frame, and call any bright spot a standing pin — **does not work on this analog feed.** The VIXLW/composite path has **exposure drift**: the auto-exposure shifts frame to frame, so the whole image gets brighter or darker between captures. Measured on the real deck (2026-05-31), the pin-free lane area read median 87→91 on live frames vs. 51 on the stored empty — a uniform ~35-count lift. With naive `frame − empty`, that lift makes **every** region of interest (ROI) look bright, so **absent pins read as standing**. Benchmark of the naive single-deck method: **15/120 spot errors, separation gap −27** (i.e., no threshold can separate standing from down). The legacy naive method is retained in `pin_detect.py` as `detect_pins()` / `PinDetector` **for the synthetic unit tests only** — it must not be used on real analog frames.

#### 18.3.2 What "M4" does

"M4" was the winner of an 8-method bake-off (**0/120 errors, separation gap +35**). Three ideas:

1. **Drift correction.** Estimate the global exposure drift from a band of lane that pins never occupy (`DRIFT_BAND` rows), then subtract that drift from every measurement. `drift = median(frame[band]) − median(empty[band])`.
2. **Tight cap-ROI.** Sample a *small* ROI on the pin **cap** (not the whole pin body). A tight cap window avoids the second failure mode: brightness bleed from an adjacent *standing* pin spilling into a neighbor's ROI (worst observed case was the right-deck pin-2 spot catching pin-4 spill).
3. **Fixed spots.** The rack lands in the same image positions every time, so the 20 pin-spot pixel centers are **calibrated once** and then sampled forever. Calibration does not run live.

The per-spot score (`spot_value`) is:

```
value = mean(frame_cap − drift) − mean(empty_cap)
standing if value > DET_THR
```

`detect_deck()` runs this for all 10 spots of one deck and builds a 10-bit mask. `DualDeckDetector.detect()` does it for both decks from one frame and returns `{'L': maskL, 'R': maskR}`.

#### 18.3.3 The calibrated constants (do not edit without re-calibrating)

All constants below are baked into `lane_node/pin_detect.py` at the top of the file. They were fit on 2026-05-31 and validated **0 detection errors** across all 6 labeled frames (4 leaves + full rack + empty) for any `DET_THR` in the band **[19, 53]**.

| Constant | Value | Meaning |
|---|---|---|
| `CALIB_FRAME_SIZE` | `(720, 576)` (W, H) | The frame size the spots were measured in. Other sizes are auto-scaled by `_scale_for()`, but production must stay 720×576. |
| `DET_THR` | `38.0` | Standing threshold on the M4 score. Validated-safe band **[19, 53]**. This is the primary soak-tuning knob for lighting. |
| `DRIFT_BAND` | `(440, 560)` | Row range (at calib resolution) of the **pin-free** lane area used as the exposure-drift probe. |
| `CAP_DY` | `−4` | The cap sits a few pixels **above** the measured spot center; the ROI is offset up by this. |
| `CAP_HALF` | `(5, 12)` | (half-width, half-height) in px of the tight cap ROI. |
| `MIRROR` | `True` | See 18.3.4. |
| `DECK_TO_LANE` | `{'L': 21, 'R': 22}` | Which physical lane each image deck is. **Confirmed** 2026-05-31. |

**`PIN_SPOTS_PX`** — the 20 calibrated pixel centers (10 per deck), at 720×576. These were fit by a rack→image homography from 4 labeled leave-frames (sub-3px residual: L max 2.7px, R max 1.9px). Pins **2 and 3** were not directly measured — they are squeezed/dim in the image and were **homography-predicted**; they validated 0-error but are the spots to watch first in soak (Section 18.8). The right deck is more oblique (pins closer together) → tighter margins there.

| Pin | Left deck (`'L'`) px (x, y) | Right deck (`'R'`) px (x, y) |
|---|---|---|
| 1 | (94.3, 230.8) | (615.0, 200.4) |
| 2 | (154.9, 233.0) *(predicted)* | (631.6, 202.4) *(predicted)* |
| 3 | (74.5, 239.6) *(predicted)* | (554.1, 207.6) *(predicted)* |
| 4 | (205.0, 234.8) | (645.7, 204.0) |
| 5 | (131.0, 240.8) | (574.4, 208.9) |
| 6 | (58.4, 246.7) | (500.5, 214.0) |
| 7 | (247.3, 236.3) | (657.8, 205.4) |
| 8 | (178.7, 241.8) | (591.8, 210.0) |
| 9 | (111.3, 247.3) | (523.6, 214.7) |
| 10 | (45.1, 252.6) | (453.2, 219.6) |

*(Pins 2 & 3 are homography-predicted, not directly measured — watch them first if a single spot misreads.)*

#### 18.3.4 The mirror (`MIRROR = True`) — why, and how to confirm

Because the camera is **behind** the pins looking toward the bowler, the image is left-right flipped vs. the bowler's view: the back-row pin on the *left of the image* is **pin 10** (bowler's right), not pin 7. `MIRROR = True` corrects the **reported pin numbers** by swapping the mirrored pairs after detection:

| Image position reads as | Reported as (under `MIRROR=True`) |
|---|---|
| 7 | 10 |
| 4 | 6 |
| 2 | 3 |
| 8 | 9 |

(and vice-versa; pins 1 and 5 are mirror-invariant). `MIRROR` **only** affects pin *numbers* on asymmetric leaves — it never changes detection accuracy, pins-down counts, strikes, or spares.

**Confirmed correct 2026-05-31.** A deliberate single pin 7 set on both decks read as **7 under `MIRROR=True`** (and as 10 under `MIRROR=False`), proving `True` is right. This frame was required because all four calibration leaves are mirror-symmetric *as sets* (e.g. {7,8,9,10} ↔ {10,9,8,7}), so a single corner pin is the first test that fixes the L↔R convention. If you ever re-mount the camera and a known **7-pin or 10-pin** reports as the opposite corner, flip `MIRROR` — no other change needed.

---

### 18.4 The bit mapping (shared contract)

Both `pin_detect.py` and `wsl_scoring_engine.py` use the **same** 10-bit encoding. This is the QubicaAMF-standard "pins **remaining**" convention.

- **Bit `n−1` set = pin `n` is STANDING.** Pin 1 = LSB (`0x001`), pin 10 = bit 9 (`0x200`).
- **`0x000` (0)** = all down = **strike** (on ball 1).
- **`0x3FF` (1023)** = full rack standing = **gutter** (nothing knocked down).
- After ball 2, only pins that survived ball 1 can still be standing.

| Bit | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Pin (standing if bit=1)** | 10 | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
| **Hex weight** | 0x200 | 0x100 | 0x080 | 0x040 | 0x020 | 0x010 | 0x008 | 0x004 | 0x002 | 0x001 |

Standard 10-pin layout with bit positions:

```
   7  8  9 10        bits  6 7 8 9
    4  5  6                3 4 5
     2  3                   1 2
      1                      0
```

Worked examples:

| On the deck | Mask (bin) | Mask (hex / dec) |
|---|---|---|
| Strike (all down) | `0000000000` | 0x000 / 0 |
| Gutter (full rack) | `1111111111` | 0x3FF / 1023 |
| 7-pin leave (only pin 7 standing) | `0001000000` | 0x040 / 64 |
| 10-pin leave (only pin 10 standing) | `1000000000` | 0x200 / 512 |
| 7-10 split | `1001000000` | 0x240 / 576 |

> The scoring engine derives splits, displays (`X`, `/`, `-`, `F`), bonuses, and totals from this mask — see the scoring engine (`wsl_scoring_engine.py`, in the main app — outside this manual's scope) for the scoring logic itself. Track A's only job is to produce the correct mask.

---

### 18.5 The scoring node: modes, settle window, and safe fallback

The Pi daemon is `lane_node/lane_node.py`. It controls one **pair** (lanes 21 + 22). *(This same `lane_node.py` daemon also carries the Phase-8a pilot's cycle/power relay outputs — see the file table at the end of this section — so the "read-only" framing above describes the **scoring path**, not the whole process. A scoring-only Pi never wires those outputs.)* Ball detection comes from the **DIELL** photoelectric beams at the pin deck (read-only inputs); see Section 4 (Machine I/O Inventory) and Section 8 (PC817 Opto-isolators) for the DIELL electrical interface and Section 12 (Channel Maps) for the GPIO assignment that feeds it.

#### 18.5.1 Scoring modes (`WSL_LANE_SCORING_MODE`)

Set on the `lane-node` systemd service. Default is the **safe** `manual`.

| Mode | What DIELL does | When to use |
|---|---|---|
| `camera` | Waits the settle window, captures a frame, runs detection, emits `BALL_EVENT` with a **real** `pin_mask` → **auto-scoring**. | Only once the empty reference is captured and detection is dry-run-validated on the live feed. |
| `manual` *(default)* | Emits `BALL_EVENT` with `pin_mask=None, awaiting_manual=True`. The server records that a ball happened and cycles the lane, **but applies no pin count** — the desk enters pins via `POST /api/lane/<N>/score`. | The safe Phase-8a default; any time camera scoring is not yet trusted. Abort target (Section 18.7). |
| `disabled` | DIELL events are logged on the Pi but **no** message is sent to the server. | Bench testing without scoring side effects. |

An unknown value falls back to `manual` with a warning.

#### 18.5.2 The settle window (`WSL_LANE_CAMERA_SETTLE_S`)

When DIELL fires, the ball has just *reached* the deck and the pins are **still rocking** — capturing now would misread. So in `camera` mode the daemon schedules `_settle_capture_emit()`: it `sleep`s `camera.SETTLE_S` seconds, **then** captures and detects, at the moment the pins have stopped but the (existing) pinsetter has **not yet swept**. The blocking capture runs off the event loop via `asyncio.to_thread`, so the watchdog kick stays responsive.

| Knob | Default | Source of truth | Tune by |
|---|---|---|---|
| `SETTLE_S` (`WSL_LANE_CAMERA_SETTLE_S`) | `2.5` s | `camera.SETTLE_S` in `lane_node/camera.py` (the daemon reads it) | Watching real balls: time from "ball hits pins" to "pins stopped, sweep not yet down." |

> **(VERIFY: the 2.5 s settle window is a manual-derived default, not yet field-measured on 21/22.)** The code comment notes the manual hint "pin data settles ~2.5 s after the sweep reaches 66°" and explicitly flags this to be measured on the real machine. Start at 2.5 s and adjust during soak (Step 4/Step 8 of the runbook).

> ⚠️ **Timing coupling (Track-B caveat).** The server sends the pinsetter `CYCLE` *in reply to* `BALL_EVENT`, so delaying `BALL_EVENT` by `SETTLE_S` also delays that `CYCLE` reply by `SETTLE_S`. **Harmless in the scoring pilot** — the existing controller cycles the machine on its own ball-detect; our cycle relay is not the live driver. **When the Track-B controller drives the machine, this must be decoupled** ("cycle now" must not wait on "here's the score"). Flagged in the `_settle_capture_emit` docstring; see Section 3 (Machine Sequence) and Section 14 (Machine Interface).

#### 18.5.3 Safe fallback — a real ball NEVER auto-scores bogus pins

This is the central safety property of Track A. The capture/detect chain returns `None` whenever it cannot produce trustworthy pins, and `None` is treated as "no data → desk scores it":

| Failure | Where it returns `None` | Result |
|---|---|---|
| No empty reference loaded | `PairCamera.ready == False` (`camera.py`) | `detect_lane()` → `None` |
| Capture fails (no frame / dongle gone) | `grab_frame()` → `None` (`camera.py`) | `detect_lane()` → `None` |
| Detector raises / lane not on this camera | caught in `PairCamera.detect_lane()` | `None` |
| Camera init failed at startup | `_PAIR_CAMERA` stays `None` (`lane_node._init_camera`) | `detect_current_pins()` → `None` |

When `detect_current_pins()` returns `None`, `_settle_capture_emit()` emits `BALL_EVENT` with `pin_mask=None, awaiting_manual=True`. The server then **cycles the lane but does not record a score**, and logs "awaiting `/score` POST from desk." The lane keeps running; only the auto-score is skipped. There is **no** code path where a real ball records a synthetic/bogus mask in production.

> **Bench-only exception:** `WSL_LANE_CAMERA_STUB=1` makes `camera` mode rotate synthetic masks (`_STUB_PIN_MASKS`) when no real camera is present, to reproduce old bench behavior. It is **off by default** and must **never** be set on a live lane — it would record fake pins on real balls.

---

### 18.6 The empty reference — the one must-do install step

The detector compares every ball's frame to a **real cleared-deck reference frame from this specific camera and mount.** The calibration "empty" was a *different* capture (a downloaded screenshot used to fit the spots); **production needs its own.** This is the single mandatory per-install step.

- Stored at `lane_node/empty_ref.png` (720×576), overridable via `WSL_LANE_EMPTY_REF`.
- It is **gitignored** — *each Pi captures its own*. It does not ship in the repo.
- Captured by `capture_empty_reference()` (CLI `--capture-empty`), which discards 5 warm-up frames so auto-exposure settles, then saves one frame.

**Procedure** (both decks must be **cleared** — cycle 21 and 22 so all pins are swept, deck empty):

```bash
cd /home/pi/wsl-lane-nodes
.venv/bin/python3 lane_node/camera.py --capture-empty
#   add  --device 1   if your dongle is /dev/video1
```

Verify it is a genuine empty deck: `ls -l lane_node/empty_ref.png` (non-zero), and ideally `scp` it to a laptop and eyeball it — both decks visible, no pins, normal house lighting. If it errors "no frame captured," the problem is upstream (device index or, most likely, the **video ground**) — see 18.2.

At daemon startup you want the log line `Camera ready for lanes [21, 22] (settle=2.5s).` If you instead see `Camera mode but detector NOT ready`, the empty ref did not load — **the lane still runs and falls back to manual scoring** (not dangerous; just not auto-scoring yet). Re-capture the empty reference.

---

### 18.7 Go-live procedure and instant abort (lanes 21/22)

Full runbook: `docs/phase8_trackA_golive_runbook.md`. Condensed:

| Step | Action |
|---|---|
| Pre-flight | On the Pi: `git pull`; confirm `lane_node/camera.py` + `pin_detect.py` exist; `.venv/bin/python3 -c "import numpy, PIL, av"`. On the server: confirm `lane_node_server.py` is up (8765/8766) via `curl http://<server>:8766/api/health`. |
| 1 — capture feed | `ls -l /dev/video*` (expect `/dev/video0`); `v4l2-ctl --list-devices`. Black frame later ⇒ video ground (18.2), not code. |
| 2 — **empty reference** | Clear both decks → `camera.py --capture-empty` (Section 18.6). The one must-do step. |
| 3 — **dry-run detector** | Set a known rack, then `camera.py --test` → prints `masks: {21: …, 22: …}`. Full rack → both `1023`; empty → `0`; 7-pin leave → `64`. **This is the real go/no-go.** Everything downstream is plumbing that already passed its tests. |
| 4 — settle window | Watch a few balls; if clearly ≠ 2.5 s, note it for Step 5. |
| 5 — start camera mode | `sudo systemctl edit lane-node` → add `Environment=WSL_LANE_SCORING_MODE=camera` (+ `WSL_LANE_CAMERA_SETTLE_S`, `WSL_LANE_CAMERA_DEVICE`, `WSL_LANE_SERVER_URL` as needed) → `sudo systemctl restart lane-node` → `journalctl -u lane-node -f`. Want: `Camera ready for lanes [21, 22]`. |
| 6 — watch a real ball | Open `http://<server>:8766/display?lane=21`. Throw; log shows `ball detected … mode=camera; settling …` → `camera pin_mask=0x…` → display updates. Compare detected vs. actual for ~10 balls + a few leave types. |
| 7 — **abort to manual** | `sudo systemctl edit lane-node` → `WSL_LANE_SCORING_MODE=camera` → `manual` → restart. (Or Ctrl-C the foreground daemon and relaunch without the env var.) **No machine impact** — manual mode just emits the ball without a mask and the desk scores via the existing flow. |
| 8 — soak + tune | Section 18.8. |

> **Service-enable reminder:** the `lane-node` service must be `systemctl enable`d, or the lane goes dark after a reboot. See the provisioning runbook / Section 2 (Architecture).

---

### 18.8 Calibration & soak-tuning knobs

The hard CV problem is solved (calibration done, 0-error on labeled frames). Soak is about confirming it on the live feed across lighting and play, and nudging three knobs.

| Symptom in soak | Likely cause | Knob / fix |
|---|---|---|
| **Consistent miss on one pin/spot** | That spot's `PIN_SPOTS_PX` coordinate (watch pins **2 & 3** first — homography-predicted; and the **right deck** — more oblique) | Adjust the spot's `(x, y)` in `pin_detect.py`. Send the tallies + a couple of misread frames for the fix. |
| **Whole-frame flakiness that tracks lighting** (house lights on/off, sun) | The per-frame threshold | Bump or re-measure `DET_THR` (safe band [19, 53]). Drift correction already handles exposure, so this should be rare. Last resort: IR illuminator + IR-pass filter. |
| **Catching the sweep, or catching pins still rocking** | Capture timing | Adjust `WSL_LANE_CAMERA_SETTLE_S`. |

Keep a **detected-vs-actual** tally per ball across both lanes and several leave types (strike, spare, split, single pin). **Target: a clean week of agreement** before declaring Track A "soaked."

**How calibration was originally done** (reproducible; scratch scripts in `~/Downloads`, see `docs/phase8_trackA_calibration_progress.md`): a synthetic empty was built as the per-pixel **min** across 4 labeled leave-frames; each leave was diffed, brightened, and grid-annotated to read off 8 solid cap positions per deck visually (pins 2,3 too dim/squeezed to measure); a rack→image **homography** per deck was fit from those 8 points (sub-3px residual) and used to **predict** pins 2,3 and emit `PIN_SPOTS_PX`. The detector was then validated against all 6 labeled frames at **12/12 deck-checks OK**.

---

### 18.9 Server, endpoints, and the display

The scoring server is `server/lane_node_server.py`. It runs on WSL-SRV and listens on **two ports**:

| Port | Protocol | Purpose |
|---|---|---|
| **8765** | WebSocket | Pi node ⇄ server. Carries `HELLO`, `BALL_EVENT`, `FOUL_EVENT`, `HEARTBEAT` (node→server) and `CYCLE`/`OPEN_LANE`/`CLOSE_LANE`/`RESET`/`POWER_ON`/`POWER_OFF` (server→node). |
| **8766** | HTTP | Scoring display, scoring JSON, health, and the manual `/score` + `/correct` endpoints. |

`PROTOCOL_VERSION = 2` (multi-lane). A node/server version mismatch logs a warning but does **not** reject the connection (degrade rather than refuse — a refused connection would mean a dead pinsetter).

**HTTP endpoints (port 8766):**

| Method + path | Use |
|---|---|
| `GET /?lane=N` *(and `/` root)* | Scoring display for lane N (the overhead/desk screen). |
| `GET /display` | Customer-facing display; serves `wsl_scoring_display.html` from the repo root; the page polls `/api/lane/<N>/scoring`. |
| `GET /api/lane/N/scoring` | Scoring JSON for lane N (what the display polls). Returns a `{open:false, players:[]}` stub if the lane has no state, so the display can render "Lane Closed." |
| `GET /api/state` | All active lanes' scoring snapshots. |
| `GET /api/health` | Server uptime, connected nodes, per-lane bowlers/scores/frame, pending fouls, state-DB path. **Use this to confirm the node is connected.** |
| `POST /api/lane/N/score` `{pin_mask:int 0-1023, foul?:bool}` | **Manual desk score / correction.** Records a ball; does **not** send `CYCLE` (the Pi already cycled). Strict range check — out-of-range `pin_mask` is rejected (not silently masked). `foul` is tri-state: `true` flags, `false` clears a stale foul, omitted leaves it. Always available, even in `camera` mode. |
| `POST /api/lane/N/correct` `{bowler_idx, frame_idx (0-9), bowls:[{pins_down 0-10, foul?}]}` | Rewrite a frame's bowls (desk correction). No hardware command. Returns the result plus a fresh `scoring` payload. |
| `POST /api/lane/N/trigger-ball` | **Bench helper only** — synthesizes a `BALL_EVENT` *and* sends `CYCLE`. Do **not** use on a live lane (it would pulse the pinsetter again and sweep the just-set rack). For live soak use `/score`. |
| `POST /api/lane/N/{open\|close\|reset\|power-on\|power-off}` | Lane/scoring lifecycle + machine commands relayed to the node. |
| `POST /api/pair/<L>-<R>/open-league` | Open a cross-lane league match across the pair (see Section 19). |

**How a `BALL_EVENT` is handled** (server `_process_ball_event` + the WS handler):

- `pin_mask` present (camera mode) → `record_ball()` immediately (**auto-score**), then send `CYCLE` to the node.
- `pin_mask=None` **or** `awaiting_manual=True` (manual mode) → send `CYCLE` so the lane resets, but **do not** record — wait for the desk's `POST /api/lane/<N>/score`. (This is what prevents bogus auto-scores; the server's internal `PIN_MASK_CYCLE` fallback is for the synthetic bench `trigger-ball` path only, never for a real `awaiting_manual` ball.)
- A pending `FOUL_EVENT` flag set since the previous ball is consumed by the next ball (scored `F`, 0 pins) — fouls are a **separate** signal (foul lamp circuit) from ball-detect (DIELL); see Section 4.

The scoring engine (`wsl_scoring_engine.LaneScoring` / `CrossLaneScoring`) consumes the masks and produces the running game. State persists to disk (`state_store`) so a server restart doesn't wipe in-progress games. The scoring logic, the desk-correction reconstruction, and cross-lane (league) play live in the scoring engine code (`wsl_scoring_engine.py`, in the main app — outside this manual's scope).

---

### 18.10 Service environment variables (the `lane-node` service)

| Variable | Default | Meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only. |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | Seconds after DIELL before grabbing the frame. *(VERIFY on 21/22 — see 18.5.2.)* |
| `WSL_LANE_CAMERA_DEVICE` | `0` | Capture device index (`/dev/videoN`). |
| `WSL_LANE_EMPTY_REF` | `lane_node/empty_ref.png` | Path to the per-install empty-reference PNG. |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks — **bench only, never on a live lane.** |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | The scoring server. Production: `ws://<WSL-SRV-IP>:8765`. |
| `WSL_LANE_NODE_ID` | `lane-node-dev-pair-21-22` | Node identifier sent in `HELLO`. |

> **(VERIFY: current WSL-SRV IP.)** The go-live runbook uses `192.168.4.103:8765/:8766` (post-2026-06-03 eero router swap; the old `192.168.86.36` is dead and a DHCP reservation was still TODO). **Confirm the live WSL-SRV IP and reserve it before go-live**, and set `WSL_LANE_SERVER_URL` to match. Do not treat any hardcoded IP in older docs as current.

---

### 18.11 Failure-mode cheat-sheet

| Symptom | Cause | Fix |
|---|---|---|
| Log: "detector NOT ready" | `empty_ref.png` missing / unreadable | Re-capture the empty reference (Section 18.6) |
| `--test` all-black / mask always 0 or 1023 | Video ground (RCA shell → Blue / cable pin-8) | Reseat the tap ground (18.2) |
| No `/dev/video0` | Dongle not enumerated | Reseat USB; check `dmesg` |
| Scores wrong but consistent | Spot / threshold calibration | Tally + misread frames → fix `PIN_SPOTS_PX` or `DET_THR` (18.8) |
| Nothing happens on a ball | DIELL not firing / wrong mode | Check log for "ball detected"; confirm `=camera` |
| Lane went dark after reboot | Service not `enable`d | `sudo systemctl enable lane-node` |
| Pins read standing right after a real ball, then a wrong score | Settle window too short (caught pins rocking) | Increase `WSL_LANE_CAMERA_SETTLE_S` (18.5.2) |

---

### 18.12 File reference

| File | Role |
|---|---|
| `lane_node/pin_detect.py` | M4 detection core; `DualDeckDetector`; calibrated `PIN_SPOTS_PX`, `DET_THR`, `MIRROR`, `DECK_TO_LANE`. Pure numpy. Legacy single-deck API kept for unit tests only. |
| `lane_node/camera.py` | `PairCamera`: capture handle (cv2 **or** PyAV), empty reference, `detect_lane()`, `--capture-empty`. Lazy capture import → unit-tests off-Pi. `SETTLE_S` lives here. |
| `lane_node/lane_node.py` | Pi daemon. DIELL → `_settle_capture_emit` → `BALL_EVENT`; scoring-mode logic; safe fallback. (Also drives the cycle/power relays + watchdog — Sections 9, 10.) |
| `server/lane_node_server.py` | Scoring server: WS 8765 + HTTP 8766; `_process_ball_event`; `/score`, `/correct`, `/scoring`, `/health`, display. |
| `wsl_scoring_engine.py` | The bowling scorer (mask → score). Section 19. |
| `wsl_scoring_display.html` | Customer/overhead scoring display (polls `/api/lane/<N>/scoring`). |
| `docs/phase8_trackA_golive_runbook.md` | Step-by-step go-live (18.7). |
| `docs/phase8_trackA_calibration_progress.md` | How calibration was done + status. |
