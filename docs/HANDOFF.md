# WSL Phase 8 — Session Handoff (2026-05-31)

> **NEXT SESSION: READ THIS FIRST.** This captures the live, in-flight state of the Phase 8 work as of end-of-session 2026-05-31. The exhaustive technical detail lives in the referenced docs; this ties it together + records the state that only existed in the conversation. **Phase 8 (pinsetter controller replacement + camera scoring) is the CURRENT active work** — *not* the April unified-checkout (that's prior/paused).

---

## 0. Cold-start orientation
- **Project:** Westside Lanes (Olympia WA), 32 lanes / 16 pairs of **AMF 82-70** pinsetters. Phase 8 = replace the aging QubicaAMF scoring (VDB/ETHost/T-VISION) and eventually the pinsetter controllers with **one Raspberry Pi per lane-pair**.
- **Deployment model:** Claude Code runs on Dylan's **laptop** (Windows). Production = **WSL-SRV** (192.168.86.36). Dylan deploys via AnyDesk; Claude has no remote access. The Phase 8 code lives in a **separate repo: `C:\Users\Dylan DeYoung\wsl-lane-nodes\`** (GitHub: dylan24483/wsl-lane-nodes). The main WSL app is in `C:\Users\Dylan DeYoung\WSL Systems\`.
- **Two ACTIVE PARALLEL tracks** (decided 2026-05-31): **Track A = camera scoring** (near-term, low-risk), **Track B = controller replacement** (months, safety-critical, bench-developed). They converge later into one Pi node per pair doing both.
- **Collaboration:** Dylan is the hands (fieldwork, soldering, captures); Claude does research/docs/code. Dylan is **new to electronics** — give beginner-level, concrete, photo-driven guidance. He's direct/technical, catches scope creep, prefers copy-paste-ready steps.

---

## 1. THE HARDWARE REALITY (critical context)

### Mixed controller fleet
The 82-70 *machine* (mechanism, motors, cams, grippers, mask lamps) is **identical on every lane**; only the bolted-on retrofit **controller** differs:
- **Lanes 21/22 (the pilot pair):** Omega-Tek **Omniboard** (1984/1990 CMOS logic) + **Expander** card (©1982, five MCT6 dual-optos, in socket PC-1) + **ZOT** board (foul lights only) on the original **SS (solid-state) chassis**.
- **Lanes 11/12:** Active Technology **"Ultra 98 Plus" 82-70 MP chassis** (microprocessor, ~1997; PARALINE transformer dated 09-97).
- Likely other controller types across the 32 lanes.
- **Omega-Tek (Shelby OH) appears DEFUNCT** → controller continuity risk (lifetime warranty worthless).
- **Implication:** a Pi-controller targets the **common 82-70 machine** (via the C1/C2A harness), NOT the varied controller brands → **develop once, works on any 82-70 lane.** This is also the continuity answer (own the brain).
- **Spare 82-70 cabinet** on Dylan's bench = an Omega-Tek unit → the Track-B bench specimen.

### The camera (Track A)
- **QubicaAMF "T-Camera"** (Qubica S.p.a. Italia, Mod. T-Camera, S/N 20021313). **Composite video, PAL (720×576), MONOCHROME.**
- **Camera wire pinout (from its label):** Red=Pin5=**+12VDC power**, Black=Pin6=**power gnd**, **Brown=Pin7=Video out**, **Blue=Pin8=Gnd video**. (Red LED on the camera = powered indicator.)
- Camera wires run to the **T-VISION board** terminal strip. Two blue **serial** wires run from that board toward the pinsetters (T-VISION data out — NOT video, ignore).
- **ONE T-Camera views BOTH lanes of the pair** (left deck + right deck + central kickback divider in one frame). → perfect for one-Pi-per-pair; pin detection must handle **two racks per frame**.
- **Camera focus is SOFT** (blurry). Leave it alone — Conqueror is tuned to it, and our detection method tolerates blur.

---

## 2. TRACK A — CAMERA SCORING (state + next action)

### What's proven
- **The tap works.** Composite video tapped at the T-VISION board: **dongle RCA center → Brown (video, terminal 7); RCA shell/ground → Blue (gnd-video, terminal 8).** Only the **yellow** RCA is video (red/white = audio, unused). **Do NOT touch the camera's red power wire.** Tap in **parallel** (leave camera + T-VISION connected & powered).
- **Capture device: VIXLW USB capture dongle** (RCA→USB). It's **UVC** — enumerates as **"USB Video"** (video) + "USB Digital Audio" (audio), no manual driver. **A black screen = the video GROUND (RCA shell) wasn't connected**, not a driver problem. **VLC's dshow is finicky → use OBS Studio.** Set standard to **PAL**.
- **Detection METHOD validated: difference-from-empty.** Full-rack frame **minus** empty-deck frame cleanly isolates the pins despite the soft focus (this is how Conqueror does it too). Raw brightness-threshold is too fragile here.
- **Dual-lane confirmed** (one camera, both decks).

### Captured frames (in `C:\Users\Dylan DeYoung\Downloads\`)
- `Screenshot 2026-05-31 14-35-27.png` — **FULL RACK** (both decks), 720×576.
- `Screenshot 2026-05-31 15-19-36.png` — **EMPTY DECK** (both lanes cleared), 720×576. **Aligned with the full frame** (same camera, framing identical).
- `pins.bmp` — Conqueror export, **LEFT-deck detection markers**, 512×285 grayscale.
- `pins even.bmp` — Conqueror export, **RIGHT-deck detection markers**, 512×285.
- ⚠️ Conqueror's 512×285 is a different crop/aspect than our 720×576 capture → **cannot pixel-copy** its markers; use them only to confirm pin layout/count.

### CALIBRATION STATE (the live blocker)
- The detection method works, but we **don't yet have the 20 pin-spot positions** (10 per deck) with correct pin-number labels in our 720×576 coordinates.
- **Auto-locate via brightness peaks FAILED** (clustered on the few brightest pins — too much pin-to-pin brightness variance + blur). See `_autocal.py` / `autocal.png`.
- **THE RELIABLE PATH (awaiting from Dylan):** capture **3–4 KNOWN leave-states** on our dongle feed and report what's standing in each (e.g., "7-10 split", "left 2-4-5", "full left / 3-6-9-10 right"). Each leave's difference-vs-empty lights up exactly those pins → triangulate + label **all 20 spots unambiguously** in our coords.

### Code state
- `lane_node/pin_detect.py` — EXISTING skeleton: single-deck, brightness-threshold, `detect_pins()` passes synthetic tests. **Needs rework → dual-deck difference engine** (subtract empty reference; per-spot compare on BOTH decks; return TWO 10-bit masks). Straightforward once spots are calibrated.
- `wsl_scoring_engine.py`, the **Phase 8b proxy** (in `wsl_api.py`), and `wsl_scoring_display.html` already exist (downstream of detection).
- ⚠️ **`cv2` (OpenCV) is NOT in `requirements.txt`.** Either `pip install opencv-python` on the Pi OR use the already-installed **`av` (PyAV)** for capture. The detection math is pure **numpy**.

### TRACK A — IMMEDIATE NEXT ACTION
1. **Dylan:** capture 3–4 labeled leave-state frames (whatever's standing + what it is) → save to Downloads → send.
2. **Claude:** from full + empty + labeled leaves → compute diffs → place + label all 20 `PIN_SPOTS` (both decks) in 720×576 → write the **dual-deck difference `pin_detect.py`** → validate against the known states → wire to `wsl_scoring_engine` → Phase 8b proxy → display. Scoring live on 21/22 (manual-entry fallback exists if needed).

---

## 3. TRACK B — CONTROLLER REPLACEMENT (state + next action)

### THE BREAKTHROUGH (2026-05-31)
Both AMF manuals were **mined in full** → the entire controller is now a **documented spec**, not a mystery. AMF's own **MP chassis** already did our exact project (a microprocessor dropped into the same machine I/O, replacing the relay/discrete chassis). **Our Pi = a modern MP chassis.** The 9807 MP schematic *omits the microprocessor logic and shows only the machine↔chassis interconnections* — i.e., **the schematic is our interface spec, and the omitted logic is the part we write.**

### Authoritative spec
- **`docs/phase8_8270_SYSTEM_REFERENCE.md`** — THE master controller reference (FSM, cam timing, I/O, safety, schematic inventory). Read it for full detail.
- Manuals (in `Downloads/`): `8270-pinspotter-operation-training-manual.pdf` (PN 610000009, 67pp), `8270-service-parts-manual.pdf` (PN 610007028, 290pp). Text extracts: `svc_text.txt`, `svc_toc.txt`, `svc_charcounts.txt`, `8270_text.txt`. Omega-Tek board manuals: `OmegaTek_Omniboard.pdf`, `OmegaTek_Expander_Card.pdf`.
- **Schematics = Service & Parts manual pp 287–290** (foldouts): p287 chassis (MP/9807-class), **p288 machine+chassis "three-board projection" — has C1 + C2A connectors (BEST page for exact C1/C2A machine-side pins)**, p289 mask/pindicator wiring, p290 full 6730 5-board schematic. Readable at topology level; need **high-DPI crops** for exact wire/terminal labels.

### FSM (written this session)
- **`lane_node/cycle_control_8270.py`** — DRAFT R1, **supersedes the void `cycle_control.py` (SS-pulse model)**. Event-driven FSM derived from the documented Sequence of Operation. States: POWER_OFF / MANUAL_INTERVENTION / READY / SWEEP_TO_GUARD / GUARD_DELAY / TABLE_DETECT / RUNTHROUGH / TABLE_FINISH / FAULT. Handles 1st/2nd/strike/foul cycles + safety hooks. **Bench sim runs clean.** Refine points marked `# CONFIRM` (run-through/respot timing, BS gating, exact cam windows — verify vs p288 schematic + bench).

### TRACK B — IMMEDIATE NEXT ACTIONS (Claude, parallel to Dylan's camera work)
1. **High-DPI crop Service manual p288** (and p287) for the **exact C1/C2A machine-side pinout**.
2. **Spec the ~45-channel I/O board** (see §4 I/O budget) — MCP23017 expanders + opto-in banks + relay/SSR-out banks; the existing **NE555 watchdog + AEDIKO relay boards slot in here**.
3. Refine the FSM against the schematic; then: build reads+lamps (no motors) on the spare → FSM-in-sim → motor control in isolation **+ the full hardware safety chain** → off-live validation on a locked-out machine → cutover. (Plan: `docs/phase8_PLAN_A_full_replacement.md`.)
- **Honest scope:** Track B is months + safety-critical (drives AC motors near people). Understanding is now solved; the BUILD + VALIDATION are the remaining mountain. Track A (scoring) will go live long before Track B.

---

## 4. CRITICAL REFERENCE DATA (do not lose)

### Cam timing (the FSM triggers — authoritative, from Service manual)
| Cam | Trips at | Role |
|---|---|---|
| **SA** (sweep) | 270° + 360°/zero | stop run-through @270°; stop @zero |
| **SB** (sweep) | 66° + 186° | guard stop @66°; initiate table spotting @186° |
| **SC** (sweep) | 86–243° | sweep-under-table → **interlock** |
| **TA1** (table) | 355° (+185°) | table zero stop; @185° reset time delay |
| **TA2** (table) | 260° | initiate sweep run-through; pin-lamp latch; ball/strike decision |
| **TB** (table) | 105–255° | table-sweep interference zone → **interlock** |
+ **3-second time delay** (pin settle), gated by **GP** (gripper-protect) closed.

### Controller I/O (the Pi must reproduce this)
- **INPUTS (read; via C2A 50-pin + TAC gripper strip; 5 VDC / 24 VAC on MP):** SS (cushion start — **DIELL on our lanes**), cams SA/SB/SC/TA1/TA2/TB, grippers **GS1–GS10** (pin sense), GP, OS (off-spot), BS (bin/#9), PBZ (zero / 1st-2nd ball / manual-intervention), PBC (cycle), 10th-frame, manual T/S/SWS/SWSR, **Foul** (Radaray detector).
- **OUTPUTS (drive; relay coils ~24 V switch 115 V):** relays **M** (master), **BE** (back-end, continuous), **S** (sweep), **T** (table), **SP** (spot solenoid), **M1** (ball return), **M2** (sweep reverse). Motors: T/S main≈1.5 Ω + start≈4.2 Ω windings, caps + centrifugal switch, **regenerative braking on relay N.C. contacts**; BE single start cap, no brake.
- **Mask lamps:** pin lamps 1–10 via diodes D1–D10; status lamps **12 VDC** → 1st-ball **PM-E24**, 2nd-ball **E25**, foul **E27**, strike **E26**; neon ~125 VAC / -160 VDC.
- **Connectors:** **C1 = 34-pin** (motor/relay + power), **C2A = 50-pin** (switches/control). AMP "M" type.
- **Transformers:** T1 (chassis V), T2 (24 VAC mgr control), T3 (24 V board), T4 (24 V BE/M1).
- **I/O budget ≈ 45 channels** (~23 in + ~22 out) → MCP23017 + opto-in + relay/SSR-out.

### Safety model (PRESERVE in hardware — the Pi is never the sole guard)
- **Stop switch + C.I.S.** (parallel) → cut the **rear-panel master circuit breaker** → all control dead.
- **Table-sweep INTERLOCK: TB + SC in PARALLEL** in the 24 V relay-control path → both motor relays drop on a collision course. The MP's manual Sweep/Table override buttons bypass *everything except BE + this interlock* → it's the irreducible hardware safety.
- **MP "Power-Down" rule:** after any 115 VAC loss in "Bowl", **NO machine motion on power restore** until a deliberate **"First Ball Zero"** (Manual Intervention). **The Pi MUST replicate this** (fail-safe-off + require operator zero). This is the controller-level sibling of the NE555 watchdog.
- Cam-position stops are **controller LOGIC** (read cam → drop relay), not a hardwired motor latch → the Pi times them; TB/SC + braking are the hardware backstops.

### The difference-detection method (Track A core)
`diff = full_rack_frame − empty_deck_frame` → pins are the bright residual. Per spot: compare current-frame-vs-empty at the spot ROI; significantly brighter ⇒ pin standing. Robust to the soft focus + lighting drift. Spots are FIXED (the rack is always the same positions) → calibrate once from labeled frames, then check those fixed spots forever.

---

## 5. ARTIFACTS INDEX

### Docs (`C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\`)
- **`phase8_8270_SYSTEM_REFERENCE.md`** — master controller spec (FSM, cams, I/O, safety, schematics). ⭐
- `phase8_status_2026-05-30.md` — overall status + to-do (two tracks).
- `phase8_controller_interface_MAP.md` — Pi-controller I/O contract.
- `phase8_controller_interface_fieldsheet.md` — bench field sheet (C1/C2A mapping).
- `phase8_tcamera_pin_detect_plan.md` — Track A plan.
- `phase8_camera_frame_capture_guide.md` — how to capture frames.
- `phase8_bench_mule_characterization.md` — spare-chassis characterization protocol.
- `phase8_PLAN_A_full_replacement.md`, `phase8_PLAN_B_scoring_first.md` — the two strategy docs.
- `phase8_r1_field_checklist.md` — early field checklist.

### Code (`...\wsl-lane-nodes\lane_node\` + repo root)
- `cycle_control_8270.py` — FSM DRAFT R1 (Track B). Supersedes `cycle_control.py` (void).
- `pin_detect.py` — detection skeleton (Track A; needs dual-deck difference rework).
- `lane_node.py` — the Pi daemon (GPIO reads, WS, scoring, watchdog kick).
- `relay_cleanup.py`, `wsl_scoring_engine.py`, `wsl_scoring_display.html`.
- Phase 8b proxy lives in the main app `wsl_api.py` (`C:\Users\Dylan DeYoung\WSL Systems\`).

### Memory (`C:\Users\Dylan DeYoung\.claude\projects\C--Users-Dylan-DeYoung-WSL-Systems\memory\`)
- `MEMORY.md` (index — has a pointer to this handoff at the top), `project_phase8_scoring_decision.md`, `project_amf_8270_interface_research.md`, and the other `project_phase8*` files.

### Manuals + frames + extracts (`C:\Users\Dylan DeYoung\Downloads\`)
- PDFs: `8270-service-parts-manual.pdf`, `8270-pinspotter-operation-training-manual.pdf`, `OmegaTek_Omniboard.pdf`, `OmegaTek_Expander_Card.pdf`.
- Text extracts: `svc_text.txt`, `svc_toc.txt`, `svc_charcounts.txt`, `8270_text.txt`.
- Frames: `Screenshot 2026-05-31 14-35-27.png` (full), `...15-19-36.png` (empty), `pins.bmp`, `pins even.bmp`.

### Scratch scripts (worktree `...\.claude\worktrees\kind-hugle-bcf2f1\`)
`_pdfx.py` (PDF text/img/crop via PyMuPDF), `_mine_svc.py`, `_mine8270.py`, `_diff_pins.py`, `_autocal.py`, `_crop_pins.py`, `_markers.py`, `_conv.py`, `_resize.py`, `_annotate.py`, `_mkpdf*.py`. ⚠️ The worktree is temporary — these may not persist; they're regenerable from the PDFs/frames.

---

## 6. TOOLING NOTES / GOTCHAS (learned this session)
- **PDF rendering:** the Read tool's PDF path needs `pdftoppm` (poppler) which is **absent**. Use **PyMuPDF (`fitz`) via Windows `py`** (`_pdfx.py`). WSL python lacks fitz; **use Windows `py`**, not `python3` in WSL.
- **PIL on huge phone photos:** set `Image.MAX_IMAGE_PIXELS = None` (200 MP photos trip the decompression-bomb guard).
- **`SendUserFile` became unavailable** mid-session — files were just saved to `Downloads` and Dylan opened them locally. Expect to do the same.
- **Capture black-screen = missing video ground** (RCA shell to Blue/pin-8), not a driver issue.
- **Camera is PAL** (720×576), not NTSC.
- **The scoring lamp-tap was a DEAD END:** tapping the Omniboard "PIN LAMPS" connector gave a weak ~0.5 VAC, floating, chopped-AC signal with ghost-voltage traps → abandoned in favor of the optical camera path. (Don't revisit it.)
- **High-Z multimeter ghost voltage:** floating SCR-off pins read phantom AC; load the probe (~1 kΩ / LoZ) to get true readings.
- **Conqueror images ≠ our capture resolution** (512×285 vs 720×576) — layout reference only, no pixel copy.

---

## 7. TASK LIST (active items)
- **#22** (in_progress) — Build T-Camera auto pin-detection (Track A). Live blocker = labeled leave-frames for spot calibration.
- **#16** (in_progress) — 8270 cycle-control FSM (Track B). Draft R1 written; refine vs schematic + validate.
- **#19** (in_progress) — Controller reverse-engineering / SYSTEM_REFERENCE (Track B). Manuals mined; next = I/O-board spec + p288 crops.
- **#20** — bench-mule characterization of the spare chassis. **#21** — integrated lane-node PCB rev B (fold opto-in + relay-out onto the watchdog/interposer board) — gated on the I/O spec.
- Pre-existing/independent: **#7** (board #1 timing-node leak), **#8** (pre-screen bare boards TP4→TP2), **#11** (relay clicking), **#12** (production DIN enclosure), **#14** (Cat6 + switch for 21/22), **#15** (cutover/rollback run-of-show), **#17** (off-live controller validation).

---

## 8. RESUME-HERE CHECKLIST (next session)
1. Read this doc + `phase8_8270_SYSTEM_REFERENCE.md`.
2. **Track A:** did Dylan send labeled leave-frames? If yes → calibrate the 20 `PIN_SPOTS` + write the dual-deck difference `pin_detect.py`. If no → that's the ask.
3. **Track B:** high-DPI crop Service p288 for C1/C2A pins; spec the ~45-ch I/O board; refine `cycle_control_8270.py`.
4. Both tracks are parallel; Track A is closer to a live win. Keep the safety model (§4) front-and-center for Track B.
