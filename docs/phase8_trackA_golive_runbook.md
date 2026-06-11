# Phase 8 Track A — Camera-Scoring Go-Live Runbook (lanes 21/22)

> ⚠️ **SERVER IP (updated 2026-06-03 — eero router swap):** WSL-SRV moved to **192.168.4.103**; the old **192.168.86.36 is DEAD**. All URLs below now use `.4.103`. **Before this go-live, confirm the current WSL-SRV IP and reserve it on the eero** — the DHCP reservation is still TODO, so the address could move again. Set `WSL_LANE_SERVER_URL=ws://<current-IP>:8765` to match.

**What this does:** turns the finished, tested camera-scoring code into a LIVE auto-scoring pilot on lanes 21 & 22. Every design unknown is resolved (calibration done, MIRROR confirmed, deck→lane set, wiring + safe-fallback built and tested). This is the **install + verify** procedure — no more coding.

**Who runs it:** Dylan, at the lanes + on the Pi node. Claude can't reach the hardware.

**Time:** ~30–45 min during a slow period on 21/22.

**Safety/blast-radius:** scoring is **read-only** w.r.t. the machine — the existing controller still runs the pinsetter. If anything's off, **the worst case is a wrong score, never a machine action**, and the code auto-falls-back to manual desk scoring on any failure. You can abort to manual instantly (Step 7).

---

## Pre-flight: confirm the pieces are in place
On the **Pi node** (the one wired to 21/22; `ssh pi@<pi-ip>` or直接):
```bash
cd /home/pi/wsl-lane-nodes
git pull                              # get session-3/4/5 code (pin_detect, camera.py, lane_node.py)
ls lane_node/camera.py lane_node/pin_detect.py   # both must exist
.venv/bin/python3 -c "import numpy, PIL, av; print('deps ok')"   # numpy + Pillow + PyAV present
```
- `git pull` must include `camera.py` (new) + the rewired `lane_node.py` + calibrated `pin_detect.py`.
- If `import av` fails: `.venv/bin/pip install av` (or `pip install opencv-python` — either backend works).

On **WSL-SRV** (the server, 192.168.4.103): confirm `lane_node_server.py` is running (ports 8765 WS + 8766 HTTP). Health check from any LAN machine:
```
curl http://192.168.4.103:8766/api/health
```
Should return JSON with the connected node. (If the server isn't up, that's a separate deploy — see `deploy_server_to_wsl_srv.md`.)

---

## Step 1 — Verify the capture feed (the dongle sees the camera)
At lane 21/22, the **VIXLW dongle** must be on the Pi's USB and fed by the **T-Camera composite tap** (Brown=video / Blue=gnd, the proven tap). Confirm the Pi enumerates it:
```bash
ls -l /dev/video*                     # expect at least /dev/video0
v4l2-ctl --list-devices 2>/dev/null   # should show a USB Video / UVC capture device
```
- The device index here is your `WSL_LANE_CAMERA_DEVICE` (default `0` → `/dev/video0`). If it's `/dev/video1`, note that for later steps.

> **Black/no frame later = missing video ground** (RCA shell→Blue/pin-8), not a code bug — same trap as the original tap.

---

## Step 2 — Capture the per-lane EMPTY reference  ⭐ (the one must-do)
The detector compares each ball's frame to a **real cleared-deck reference** from THIS camera. The calibration empty was a different capture; production needs its own.

**Clear BOTH decks** (cycle 21 and 22 so all pins are swept, deck empty), then on the Pi:
```bash
cd /home/pi/wsl-lane-nodes
.venv/bin/python3 lane_node/camera.py --capture-empty
# (add  --device 1  if your dongle is /dev/video1)
```
- Saves `lane_node/empty_ref.png` (720×576). It's gitignored — each Pi captures its own.
- **Verify it's a real empty deck:** `ls -l lane_node/empty_ref.png` (non-zero), and ideally scp it to your laptop and eyeball it — both lanes' decks, no pins, normal lighting.
- If it errors "no frame captured": re-check Step 1 (device index / video ground).

---

## Step 3 — Dry-run the detector against the live feed (no scoring yet)
Prove detection works on the real camera before involving the scorer. Set a **known rack** (e.g. full rack on both lanes, or a deliberate 7-pin), then:
```bash
.venv/bin/python3 lane_node/camera.py --test
# prints: masks: {21: <mask>, 22: <mask>}
```
- Full rack → both masks `0b1111111111` (1023). Empty → `0`. A 7-pin leave → bit 6 set (mask 64) on that lane.
- Try 2–3 known states. If they read correctly, **detection is live-validated.** If a state is wrong, STOP and send me the frame (`camera.py` can be extended to save it) + what was actually standing — likely a `DET_THR` or framing tweak, not a redesign.

> This step is the real go/no-go. Everything downstream is plumbing that already passed its tests.

---

## Step 4 — Measure the settle window (when to grab the frame)
After a ball, pins rock then settle before the sweep clears them. We grab the frame `WSL_LANE_CAMERA_SETTLE_S` seconds after DIELL fires. Default **2.5 s** (manual hint). To tune: watch a few real balls and note roughly how long from "ball hits pins" to "pins stopped moving, sweep not yet down." If it's clearly more/less than 2.5 s, set it in Step 5. (Fine to start at 2.5 and adjust during soak.)

---

## Step 5 — Start the node in CAMERA mode
The daemon runs under systemd as the `lane-node` service. Set the env for camera mode. Edit the service drop-in (preferred — survives reboot):
```bash
sudo systemctl edit lane-node
```
Add:
```ini
[Service]
Environment=WSL_LANE_SCORING_MODE=camera
Environment=WSL_LANE_CAMERA_SETTLE_S=2.5
# Environment=WSL_LANE_CAMERA_DEVICE=0        # uncomment+set if dongle isn't /dev/video0
# Environment=WSL_LANE_SERVER_URL=ws://192.168.4.103:8765   # if not already set
```
Then:
```bash
sudo systemctl restart lane-node
journalctl -u lane-node -f             # watch the log live
```
**In the log, on startup you want to see:**
- `Camera ready for lanes [21, 22] (settle=2.5s).`  ← detector loaded the empty ref.
- If instead `Camera mode but detector NOT ready` → the empty ref didn't load (redo Step 2) — **the lane still runs, just falls back to manual scoring.** Not dangerous, just not auto-scoring yet.

> Quick test without systemd (foreground, Ctrl-C to stop):
> `WSL_LANE_SCORING_MODE=camera .venv/bin/python3 lane_node/lane_node.py`

---

## Step 6 — Watch it score a real ball
Open the scoring display on a screen at the lanes (or your laptop):
```
http://192.168.4.103:8766/display?lane=21          (and ?lane=22 for the other)
```
Throw a ball (or roll one by hand) on 21. In the `journalctl` log you should see, in order:
```
GPIO: ball detected on lane 21, mode=camera; settling 2.5s before capture
lane 21: camera pin_mask=0x... (standing=[...])
→ {"type":"ball_event","lane":21,"pin_mask":...}
```
And the display updates with the score. **Compare the detected standing-pins to what's actually on the deck.** Do this for ~10 balls across both lanes + a few leave types (strike, spare, a split, a single pin).

---

## Step 7 — Abort to manual (instant, if needed)
If detection is flaky and you want to stop auto-scoring **right now**, flip back to manual — the lane keeps running, desk enters scores:
```bash
sudo systemctl edit lane-node      # change WSL_LANE_SCORING_MODE=camera → manual
sudo systemctl restart lane-node
```
Or for a fast foreground stop: Ctrl-C the daemon and relaunch without the env var (defaults to `manual`). **No machine impact either way** — manual mode just emits the ball event without a pin_mask, and the desk scores via the existing flow.

---

## Step 8 — Soak + tune
Run camera mode through real play on 21/22. Keep a tally: **detected vs actual** standing pins per ball. Things to watch + their knobs:
- **Consistent miss on one pin/spot** → that spot's `PIN_SPOTS_PX` coord or the per-frame threshold. Pins **2 & 3** are the homography-predicted ones (watch first); the **right deck** is more oblique (tighter margins). Send me the tallies + a couple of misread frames and I'll adjust.
- **Whole-frame flakiness that tracks lighting changes** (house lights on/off, sun) → bump or re-measure `DET_THR`; the drift-correction already handles exposure, so this should be rare. Last resort = an IR illuminator + IR-pass (mitigation in the plan).
- **Timing: catching the sweep or catching pins still rocking** → adjust `WSL_LANE_CAMERA_SETTLE_S`.

Target: a clean week of camera-vs-actual agreement before calling Track A "soaked."

---

## What "done" looks like
Lanes 21 & 22 auto-score from the T-Camera, scores show on the display, and the desk only touches scoring for the occasional correction (the manual `/api/lane/<N>/score` path still works for fixes). That's the Phase-8 scoring win live on the pilot pair — months ahead of the Track-B controller work.

---

## Quick reference — env vars (all on the `lane-node` service)
| var | default | meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | seconds after DIELL before grabbing the frame |
| `WSL_LANE_CAMERA_DEVICE` | `0` | capture device index (`/dev/videoN`) |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks (bench only; never on a live lane) |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | the WSL-SRV server (`ws://192.168.4.103:8765`) |

## Endpoints
| url | use |
|---|---|
| `http://192.168.4.103:8766/display?lane=N` | scoring display for lane N (bare `/?lane=N` 404s; `/` without a query = desk simulator) |
| `http://192.168.4.103:8766/api/lane/N/scoring` | scoring JSON (display polls this) |
| `http://192.168.4.103:8766/api/health` | server + connected-node health |
| `POST /api/lane/N/score` `{pin_mask, foul?}` | manual desk score / correction (always available) |

## Failure-mode cheat-sheet
| symptom | cause | fix |
|---|---|---|
| log: "detector NOT ready" | empty_ref.png missing/unreadable | redo Step 2 |
| `--test` all-black / mask always 0 or 1023 | video ground (RCA shell→Blue) | reseat the tap ground |
| no `/dev/video0` | dongle not enumerated | reseat USB; check `dmesg` |
| scores wrong but consistent | spot/threshold calibration | tally + frames → Claude |
| nothing happens on a ball | DIELL not firing / wrong mode | check log for "ball detected"; confirm `=camera` |
| lane "went dark" after reboot | service not enabled | `sudo systemctl enable lane-node` (provisioning runbook) |
