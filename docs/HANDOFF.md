# WSL Phase 8 — Session Handoff (2026-05-31)

> **[SUPERSEDED by the ⚡ 2026-06-27 addendum below — Steps 2→3→4 are DONE; do NOT redo them.]** ~~**⚡ NEXT SESSION: READ `phase8_session_close_2026-06-25.md` FIRST**~~ — rev-B **board #1 bench bring-up**, ribbon now in hand; the task is to **wire J1↔Pi and finish Steps 2→3→4** (I²C enumerate → relay-enable rail → relay click test). That doc is the live state + the full step-by-step. Older close docs (`phase8_session_close_2026-06-03.md`, `…06-01.md`) are prior background (rev-B routing/DRC era). THIS handoff is the deeper background; the close docs supersede §2–§3 for live state.
>
> This captures the live, in-flight state of the Phase 8 work. The exhaustive technical detail lives in the referenced docs; this ties it together + records the state that only existed in the conversation. **Phase 8 (pinsetter controller replacement + camera scoring) is the CURRENT active work** — *not* the April unified-checkout (that's prior/paused).

> **⚠️ ADDENDUM 2026-06-10 — read before acting on anything below (history left intact):**
> - **Network:** WSL-SRV was re-IP'd in the **2026-06-03 eero router swap** — the old static **`192.168.86.36` is DEAD; the live server is `192.168.4.103`** (eero subnet `192.168.4.0/22`, gw `.4.1`; the DHCP reservation is still TODO, so re-confirm before relying on it). Any `.86.x` address below is historical.
> - **Current work state:** the **2026-06-09 Fable-5 audit-fix campaign** post-dates this handoff's "next actions". For what's actually current, read **`C:\Users\Dylan DeYoung\WSL Systems\IMPLEMENTATION_PLAN.md`** (the audit-fix tracker) **+ the `fable-audit-fixes` branch** — alongside the session-close docs above.
> - **Scoring display URL:** the display is served at **`http://<srv>:8766/display?lane=N`** — the bare `/?lane=N` form used in older sections returns 404 (`/` with no query serves the desk simulator).
>
> **⚡ ADDENDUM 2026-06-24 — rev-B controller board #1 bench bring-up (Track B):**
> - **Board #1 is assembled, fully bench-tested, and its Pico is flashed + running.** Pre-power ohm-out PASS; powered with all rails correct (TP1≈4.6V after the SS14 D17 drop, TP3=3.3V, isolation **TP5↔TP2 OPEN held live**, no part hot). **`FIELD_WET_V`=14V is EXPECTED** — the unloaded no-load rise of the unregulated **TMA-0505S** (U37 confirmed genuine; drops under field load). **Pico (A1) flashed** with `firmware/rp2040/build/wsl_phase8b_rp2040.uf2` → **RP2040_OK = TP14 = 3.3V** (firmware live; 1 of the rail's AND-conditions met).
> - **PAUSED at Step 2 (Pi↔board I²C), blocked on the J1↔Pi ribbon (on order).** Resume: wire **J1 pin 2/3/4 → Pi physical pin 6/3/5 (GND/SDA/SCL)**; **NEVER connect J1 pin1 (`VCC_5V`) or pin11 (`VCC_3V3`) to the Pi** — board is powered via J2, the rails would fight. Verify ribbon orientation by metering the pin-1 conductor = ~4.6V before the Pi connects. Then `i2cdetect -y 1` → expect **0x20/0x21/0x22**. Step 3 = jumper **J14 pin1↔2 & pin3↔4** (close the safety loop) + Pi drives ARM_PERMIT/WDOG_KICK → **`RELAY_ENABLE_RAIL` (TP16)** comes up. Step 4 = relay click test on J6–J11.
> - **Pi pin map** (source: `lane_node/controller_daemon.py` DEFAULT_BOARDS, board-21): i2c_bus=1 (hw I²C GPIO2/3), uart `ttyAMA0`, arm=GPIO26, wdog=GPIO12. Full J1↔Pi map + power rules: `docs/phase8_revB_harness_parts.md` + manual §11.2.
> - **BOM gap closed:** the J1 mating IDC socket + field Phoenix MC-ST plugs (J3/J4/J5/J13/J14 = 1840447/1840489/1840463/1840405/1840382) were never on the BOM → captured in `docs/phase8_revB_harness_parts.md` + `phase8_revB_bench_harness_parts.csv` / `phase8_revB_production_harness_parts.csv`.
> - **Flash gotcha / rev-C:** the Pico micro-USB is jammed against J1 and is the **ONLY flash path (SWD is NOT broken out)** → flashed via a hand-shaved right-angle micro-B cable. **rev-C must:** break SWD to a 3-pin header, clear the USB end, add the J1 mate to the assembly BOM, consider a `FIELD_WET_V` bleed/min-load resistor. *(Superseded — see the 2026-06-27 addendum: SWD header **DROPPED**; USB clearance did **NOT** make the rev-C layout.)*
>
> **⚡ ADDENDUM 2026-06-27 (recorded 2026-07-06) — bring-up FINISHED · relay footprint bug · rev-C ordered · at-machine metering · Fable review. THIS supersedes the "NEXT SESSION" pointer above (Steps 2→3→4 are DONE — do not redo):**
> - **Board #1 bring-up COMPLETE (2026-06-25):** J1↔Pi ribbon wired; `i2cdetect -y 1` → **0x20/0x21/0x22** (Step 2 PASS); `RELAY_ENABLE_RAIL` (TP16) up with J14 loop closed + ARM + WDOG kick, **fail-safe drop verified** (Step 3 PASS). **Step 4 relay click test FAILED: ALL SIX relays DEAD.**
> - **Root cause = rev-B relay footprint bug (NOT a fresh fault — do not chase it):** the netlist drove G5LE-**1** pad functions but the placed part is a G5LE-**14** (coil = pads **2/5**, ~65 Ω; COM=1, NO=3, NC=4) → the coil never sees voltage; **no rev-B relay can ever energize.** Generator remapped, netlist/DRC/Gerber re-verified → **rev-C ordered** with pre-order gates **G1–G5 all passed**. Source of truth: `phase8_revC_change_list.md` + `phase8_revC_readiness_checklist.md`. ⚠️ Caveats that did NOT make the rev-C spin: change-list **#3 USB clearance — layout unchanged** (A1/J1 never moved; **flash the Pico BEFORE soldering**, or use the shaved right-angle cable), **#5 FIELD_WET_V bleed — not implemented** (external bleed-R at a field connector is the interim option); **#2 SWD header — DROPPED** (Dylan 2026-06-25).
> - **2026-06-27 at-machine metering (lanes 21/22 Omega-Tek) — MEASURED ground truth:** **SC** reads at **C2A cavity U** via its N.O. (pink) wire; **TB has NO standalone cavity** — both TB wires tie into the SC/U node → **SC+TB is a SERIES interlock in the live 24 VAC relay ladder** (§4's "TB + SC in PARALLEL" is superseded; the J_SAFETY dry-loop plan has no landing point as designed). **C2A-N = motion-cam common bus** (all N-cavity cam predictions void). Cold cam probing hits ~21 Ω coil sneak paths → **per-cam SA/SB/TA1/TA2 cavities DEFERRED to POWERED mapping at cutover**; cam edge polarity unmeasured. Grippers **COMPLETE 10/10**: **GS1=C GS2=H GS3=M GS4=S GS5=W GS6=a GS7=e GS8=K (✓ 2026-07-07) GS9=r GS10=v**, with **J/F/U as common rails** (old GS8=48H / GS10=410U predictions PROVEN WRONG). **PBZ=EE** (shorts to common U pressed); **BS=CC**. **No physical TAC strip** — gripper return = machine chassis. Measured record: `phase8_metering_guide_harness_unknowns.md`.
> - **Fable review 2026-06-27:** adversarial review of all post-06-10 work → **62 confirmed findings** (1 critical: the J_SAFETY TBSC loop is unbuildable as measured) → **`docs/phase8_fable_review_2026-06-27.md`**. **Interlock redesign is OPEN** — decide the hardware path (aux contacts / interposing relay / verified OEM series reliance) before any cutover.
> - **NEXT ACTIONS:** ① first-article relay click test when the rev-C boards arrive (readiness checklist §4); ② powered cam-cavity mapping at cutover (cold trace invalid); ③ ~~re-read GS8~~ **✓ DONE 2026-07-07: GS8 = C2A-K (gripper map complete)**; ④ interlock: **§4.2 premise PROVEN TRUE at the machine 2026-07-07** (ladder alone kills S+T coils; danger = both cam levers BACK; coils 24 VAC) → **✅ CANDIDATE C FORMALLY DECIDED 2026-07-07** (`phase8_interlock_redesign.md` §7); §4.3 window capture + per-lane Stage-6b proof remain standing gates; ⑤ **build the lane-21 machine harness per `docs/phase8_lane21_harness_build_sheet.md`** (cut-and-crimp build sheet: Path-B taps, J_SAFE1-2 engineered jumper, Stop/CIS landing OPEN).

> **⚡ ADDENDUM 2026-07-20 — REV-D BOARD CAMPAIGN: designed, ROUTED (DRC 0/0/0), NOT fab-ordered — read the rev-D docs before touching any board file:**
> - **Rev-D exists and is fully routed.** `kicad/revD/wsl-phase8b-revD.kicad_pcb` — 252 parts / 213 nets / 250×240 mm, netclasses 93/4/13/82/21, post-route DRC **0 violations / 0 unconnected / 0 footprint errors** (`kicad/revD/DRC-revD-routed-r3.rpt`), routed-mode audit ALL PASS, five single-point power vias doubled (RD-VIA-1). Adds the AUX4–11 opto bank (40 rows), USB clearance fix, VCC_5V ADC divider, safety-rail observe-only taps, J15/J16, SS34 D_PROT.
> - **Authoritative docs (read in this order):** `phase8_revD_readiness_checklist.md` (gates G1–G14 — G1–G6, G9, G10 done; **G8/OG-1 = Dylan's 240 mm sign-off is OPEN and BLOCKING fab**, and routing ran out of order past it — see run-log **PV-1**), `phase8_revD_run_log.md` (FR/COR/PV/RD records), `phase8_revD_change_spec.md` + `phase8_revD_change_list.md`, `kicad/revD/netlist_diff_revC_to_revD.txt`.
> - **⚠️ REFDES_SHIFT trap:** 46 refdes moved rev-C→rev-D (ISO_WET U37→U45, U_WDOG U36→U44, R100-series watchdog family →R116–128…). **NEVER probe or bring up a rev-D board from rev-C TP maps / bench packets / photos** — regenerate per-board docs from the rev-D netlist first (readiness checklist §2, first line).
> - **Rev-C design files are SACRED** (validated hardware): snapshot + SHA256 manifest at `backups/revC_design_snapshot_2026-07-19/MANIFEST.json` (189 files) — hash-verify after any board work; never edit rev-B/rev-C files. External mirrors: `C:\Users\Dylan DeYoung\WSL_Backups\2026-07-20_phase8_revC_revD\` (rev-C + PRE-route rev-D only) and `...\2026-07-20_phase8_revD_routed\` (the routed board). Branch `fable-audit-fixes` still has NO remote (160 MB PDF push blocker).
> - **Open before fab:** G7 (powered-session items 6–7 or waiver) · **G8/OG-1 (Dylan)** · G11–G12 (`export_fab_revD.py` not yet written; Gerber/JLC inspection) · G13/OG-3 (harness + coding parts) · G14 (Dylan doc review).

---

## 0. Cold-start orientation
- **Project:** Westside Lanes (Olympia WA), 32 lanes / 16 pairs of **AMF 82-70** pinsetters. Phase 8 = replace the aging QubicaAMF scoring (VDB/ETHost/T-VISION) and eventually the pinsetter controllers with **one Raspberry Pi per lane-pair**.
- **Deployment model:** Claude Code runs on Dylan's **laptop** (Windows). Production = **WSL-SRV** (now **192.168.4.103** — the `192.168.86.36` this doc originally cited died in the 2026-06-03 eero swap; see the addendum above). Dylan deploys via AnyDesk; Claude has no remote access. The Phase 8 code lives in a **separate repo: `C:\Users\Dylan DeYoung\wsl-lane-nodes\`** (GitHub: dylan24483/wsl-lane-nodes). The main WSL app is in `C:\Users\Dylan DeYoung\WSL Systems\`.
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

### TRACK A — ✅ CALIBRATION + DETECTOR DONE (2026-05-31 session 3)
- Dylan sent 4 labeled leave-frames (`corners`=1,7,10 · `123` · `456` · `78910`, all 720×576, both decks). **All 20 `PIN_SPOTS` calibrated** (homography fit, sub-3px residual, pins 2/3 predicted) and **`lane_node/pin_detect.py` REWRITTEN** as a dual-deck **drift-corrected ("M4")** detector → ONE camera → TWO 10-bit masks. **Validated 0-error: 12/12 deck-checks across all 6 frames** (`_verify_module_verdict.txt`, ALL_OK=True).
- **Key finding:** naive `frame−empty` FAILS (analog exposure drift → 15/120 errors, gap −27). Fix = subtract global drift (pin-free lane band) + tight cap-ROI. 8-method bake-off → M4 wins (gap +35, 0 errors). Full detail: **`phase8_trackA_calibration_progress.md`** + Downloads scripts `_calib3.py` / `_exp.py` / `_verify_module.py`.

### TRACK A — NEXT ACTIONS
1. ✅ **All 3 Dylan confirmations RESOLVED (2026-05-31):** (a) deck→lane **left=21, right=22** → `DECK_TO_LANE` set. (b) **mirror CONFIRMED** — real pin-7-both-decks (`two 7 pins.png`) reads 7 under `MIRROR=True` (10 under False) → MIRROR=True correct, already the default, no code change (`_mirror_check.py`). (c) prod capture **720×576 PAL full-frame** (keep). **Track A has no remaining design unknowns.**
2. ✅ **GO-LIVE RUNBOOK written (session 5)** → `docs/phase8_trackA_golive_runbook.md`. Numbered on-Pi steps to take camera scoring LIVE on 21/22: pre-flight (git pull, deps) → verify dongle (`/dev/video0`) → **capture per-lane empty (`camera.py --capture-empty`)** → dry-run detector (`camera.py --test`, the real go/no-go) → measure settle → start `lane-node` service with `WSL_LANE_SCORING_MODE=camera` → watch it score on `http://192.168.4.103:8766/display?lane=21` (live IP + URL per the 2026-06-10 addendum) → soak/tune. Read-only w.r.t. machine (existing controller still cycles); auto-falls-back to manual on any failure; instant abort to manual. Env-var + endpoint + failure-mode tables included. **This is the path to Track A live — Dylan runs it at the lanes.**
3. ✅ **DONE — capture-timing hook + scoring wiring shipped:** `lane_node.py` rewired (session 4) with the camera path (DIELL → settle → capture → BALL_EVENT, manual fallback) and verified in the 2026-06-03 pre-check (`phase8_session_close_2026-06-03.md`). Remaining from this item = the install-day steps in the go-live runbook (per-lane empty capture + soak on 21/22).

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

### TRACK B — PROGRESS 2026-05-31 (session 2)
- ✅ **p288 crop DONE** → `phase8_C1_C2A_pinout_p288.md`. p288 = **PDF page 287** (offset: printed − 1); foldout native **4944×3947 px ≈ 225 DPI** (legibility ceiling — pin codes are at-scan-resolution, best-effort, bench-verify). Crops saved: `Downloads\p288_C1C2A_band.png`, `p288_C1.png`, `p288_C2A_top.png`, `p288_C2A_bot.png`. **Structural win (high-conf):** C2A = input connector — **TAC-1…10 strip = grippers GS1–GS10**, **A&MC plug = cams SA/SB/SC/TA1/TA2/TB + GP/OS/BS**, + PBC/PBZ/SWS/SWBE/CB/T-S. C1 = motor/relay/power (all `T.S-xx` terminal-strip wiring). Tooling: `Downloads\_pdfx.py` (clip/render via fitz), `_pdftext.py` (text-layer — foldouts have NO text layer, raster only).
- ✅ **~45-ch I/O board spec DONE** → `phase8_io_board_spec.md` (rev B integrated). Key decisions: **two-tier inputs** (FAST cams+SS on direct GPIO+RP2040 cam-stop co-proc; SLOW switches on 4× MCP23017 @0x20–0x23 w/ INT); isolated outputs (opto→ULN→AEDIKO relays, opto→MOSFET/SSR lamps); **relay-enable rail gated by NE555 watchdog AND arm-GPIO AND hardware TB/SC interlock AND master breaker**; recommend **two single-lane boards per Pi** (Option B); camera pin-data can omit the 10 pin-lamp outputs.

### TRACK B — NEXT ACTIONS
1. ✅ **p289 functional map DONE 2026-05-31** → `phase8_C1_C2A_pinout_p288.md` §4. Cam→C2A pairings read (SA→C2A-31N, SB→31H, TA1→34N, TA2→21A/30N, B'S→112cc, GP-SW→412DD/TAC-SW, PBC/PBZ→21EE); gripper DETAIL K confirms **GS-n → TAP tap → TAC strip → C2A** (10-gripper bank lands on TAC, as the I/O spec assumed). Pin codes 225-DPI best-effort → bench-verify; functional clusters now pinned. Crops in Downloads `_svc_p289_crop_*.png`.
2. ✅ **FSM refined (session 4)** — added SPOTTING state + `_needs_fresh_rack()` (2nd-ball/strike wait for BS→SP spotting rev; 1st-ball respots held pins). Sim is now assert-based, exit-0. `# CONFIRM`s remaining: foul respot semantics, exact SP pulse-vs-continuous + de-energize timing (bench).
3. ✅ **Channel allocation map DONE (session 5)** → `phase8_channel_allocation.md`. Per-lane per-pin map (FSM io surface → MCP23017/RP2040 ports → C1/C2A → device), grounded in the FSM's actual `io.*` usage. **Gates rev-B PCB (#21).** **3 architecture refinements (doc §6) ADOPTED (Dylan 2026-05-31):** (#1) RP2040 owns fast inputs + forwards events; (#2) per-board I²C bus (each board repeats 0x20–0x23); (#3) one RP2040 per board → **self-contained identical single-lane boards** (develop one, clone). Locked into `phase8_io_board_spec.md` too.
4. ✅ **io-wrapper firmware DONE (session 5)** → `lane_node/controller_io.py`. `MachineIO` (3× MCP23017 via per-board I²C, OUT_A_MAP/IN_A_MAP bit assignments, GS1–10 mask read, watchdog kick + arm-relay injection) + `RecordingIO` (no-hw fake). Smoke test drives the **real FSM through a full strike cycle off-Pi** (exit 0). Hardware path needs `smbus2` on the Pi; RP2040 link (fast cam/ball + cam-stop) injected, `# CONFIRM`. **The FSM is now runnable on hardware once the board exists.**
4. ✅ **RP2040↔Pi link DECIDED = UART** (session 5; RP2040 pushes events, no bus contention, cam-STOP stays hardware-local → dead link = fail-safe FAULT, not unsafe motion). ✅ **AEDIKO specs FOUND in `pcb_design_spec.md`** (5V module ~70mA/coil, onboard optos+flyback → NO external ULN needed; switches contactor COILS not motors → existing contactors handle inrush; watchdog gating bench-proven). Both recorded in `phase8_channel_allocation.md` §6–7.
5. **Bench (Dylan + Claude, photo-first):** ✅ **Session-1 photos IN + analyzed** → `docs/phase8_bench_session1_FINDINGS.md` (6 photos `Downloads/Cabinet images/20260601_09*.jpg`, crops in `_small/`). Confirmed vs Fig-1: chassis rail stamps **T1·OLL·T2·S·T**; relays (Siemens control relay w/ 22E/21NC/31NC/32NC/44NO/43NO aux block + a **P&B JRM-10110 12 VDC** relay = first hard coil-V); **C1/C2A FOUND** = the two AMP **67209/67211** edge-card connectors right of the Omega-Tek board; board edge legend reads T,S,X,2B,1B + PIN LAMPS 2,F,4,6,8,10,1. ✅ **Follow-up photos IN (091852/04/07) → C1/C2A ASSIGNED:** connectors shot OUT on the bench, both AMP M-series. **LEFT = C1 (34-pin)** — 3 cols, double-letter rows EE/FF/GG/HH/JJ/KK/LL/MM/NN + 2 power pins + "01" pin-1 mark (matches pinout-doc C1 pins like 17-DD/19-NN). **RIGHT = C2A (50-pin)** — 4 cols ×~13. "01"+AMP logo = pin-1 datum. **Siemens contactor = 3TH40, 22E** (2NO+2NC). ⚠️ STILL OPEN (small, non-blocking): coil voltages (3TH40 + power contactor + confirm P&B=12VDC — read side stickers / meter A1-A2). 3TH40 side label (092859) = contact-load table NOT coil-V (`-0A`≠voltage code; coil V via A1-A2 Ω or front "___V" line). (`20260506_181247.jpg` = QubicaAMF SCORING board, NOT this chassis.)
6. ✅ **SESSION-2 PROBE LIST WRITTEN** → `docs/phase8_bench_session2_probe_list.md` — ordered, safety-first, anchored to C1=left(34)/C2A=right(50)+"01" datum. §A safety chain (Stop/CIS in series w/ motor coils?) → §B **cam-stops hardwired vs logic** ⭐ (THE architecture Q) → §C C1 motor/relay pin map (vs predicted 21D/31A/17DD/35U/45W) → §D coil voltages (label or A1-A2 Ω; folds in the open 3TH40/contactor/P&B reads). §A+§B are the design-changing parts; §C/§D are mapping. **Dylan runs it → readings close the last bench-gated unknowns → PCB rev-B to layout.**
7. Then: fieldsheet complete → build reads+lamps (no motors) on the spare → FSM-in-sim → motor control in isolation **+ the full hardware safety chain** → off-live validation on a locked-out machine → cutover. (Plan: `docs/phase8_PLAN_A_full_replacement.md`.)
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
- **Table-sweep INTERLOCK: ~~TB + SC in PARALLEL~~ MEASURED 2026-06-27: SC + TB in SERIES** at one node (C2A-U/TSG-1) in the live 24 V relay-control path → both motor relays drop on a collision course. The MP's manual Sweep/Table override buttons bypass *everything except BE + this interlock* → it's the irreducible hardware safety. The planned J_SAFETY dry-loop landing has no landing point as designed — `phase8_interlock_redesign.md`, decision OPEN.
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
- `phase8_io_board_spec.md` — **NEW 2026-05-31** ⭐ ~45-ch I/O board spec (rev B integrated; two-tier inputs + isolated outputs + watchdog/interlock gating). Gates PCB rev B (#21).
- `phase8_C1_C2A_pinout_p288.md` — **NEW 2026-05-31** C1/C2A connector extraction from p288 (structure high-conf; pin codes best-effort; p289 = functional next).
- `phase8_tcamera_pin_detect_plan.md` — Track A plan.
- `phase8_trackA_calibration_progress.md` — **NEW 2026-05-31** ✅ Track A calibration DONE: 20 PIN_SPOTS + M4 drift-corrected dual-deck detector, 0-error validated. Has the 3 Dylan-confirmations + wire-up next steps.
- `phase8_camera_frame_capture_guide.md` — how to capture frames.
- `phase8_bench_mule_characterization.md` — spare-chassis characterization protocol.
- `phase8_PLAN_A_full_replacement.md`, `phase8_PLAN_B_scoring_first.md` — the two strategy docs.
- `phase8_r1_field_checklist.md` — early field checklist.

### Code (`...\wsl-lane-nodes\lane_node\` + repo root)
- `cycle_control_8270.py` — FSM (Track B). Refined session 4 (SPOTTING/SP, assert sim). Supersedes `cycle_control.py` (void).
- `controller_io.py` — **NEW session 5** — concrete FSM `io` object: `MachineIO` (MCP23017 hw) + `RecordingIO` (fake). Smoke test = FSM strike cycle off-Pi.
- `camera.py` — **NEW session 4** — `PairCamera`: T-Camera capture (cv2/PyAV) + dual-deck detect for Track A scoring.
- `pin_detect.py` — **REWRITTEN session 3** — dual-deck drift-corrected ("M4") detector; 20 PIN_SPOTS calibrated; 0-error validated.
- `lane_node.py` — the Pi daemon. Rewired session 4: camera-backed scoring (DIELL→settle→capture→BALL_EVENT) w/ manual fallback.
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
2. **Track A — DONE 2026-05-31** (calibrated + dual-deck `pin_detect.py` written + 0-error validated → `phase8_trackA_calibration_progress.md`). The 3 confirmations, bindings, capture-timing hook, and scoring-engine wiring are all ✅ resolved (see §2) — next = **run `docs/phase8_trackA_golive_runbook.md`** (install-day: empty-ref capture → detector dry-run → camera mode → soak).
3. **Track B (p288 crop + I/O-board spec DONE 2026-05-31 → `phase8_io_board_spec.md`, `phase8_C1_C2A_pinout_p288.md`):** next = crop **p289 (PDF 288)** for the functional pin map (TAC-n→GS-n, A&MC→cam), refine `cycle_control_8270.py` `# CONFIRM`s vs schematic, then bench fieldsheet.
4. Both tracks are parallel; Track A is closer to a live win. Keep the safety model (§4) front-and-center for Track B.
