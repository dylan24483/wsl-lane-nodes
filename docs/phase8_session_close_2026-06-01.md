# Phase 8 — Session Close / Walk-In Doc (2026-06-01)

> **READ THIS FIRST tomorrow.** One-page state of both tracks + the single next action for each. Detail lives in the linked docs; this is the map. (Supersedes the day-to-day notes in `HANDOFF.md` §2–§3 for current state.)

## 30-second orientation
Two parallel tracks. **Track A = camera scoring** (near-live, low-risk). **Track B = controller replacement** (months, safety-critical, bench-developed). Today was almost entirely **Track B bench work on the spare cabinet** — and it went well: the connector identities and output map are now bench-confirmed.

---

## TRACK A — camera scoring — CODE COMPLETE, awaiting on-Pi install
**State:** detection calibrated + validated 0-error; `MIRROR` confirmed (pin-7 frame); `DECK_TO_LANE={L:21,R:22}`; `camera.py` + rewired `lane_node.py` built & tested; server needs no changes; safe-fallback to manual on any failure. **Nothing left to code.**

**SINGLE NEXT ACTION (Dylan, at lanes 21/22, any slow hour):** run the go-live runbook → `phase8_trackA_golive_runbook.md`. The gating step is `python lane_node/camera.py --capture-empty` (both decks cleared) → then `--test` against a known rack (the real go/no-go) → then `WSL_LANE_SCORING_MODE=camera` + soak. Read-only to the machine; instant abort to manual.

---

## TRACK B — controller replacement — design locked, bench in progress
**Design (all done, test-passing):** FSM `cycle_control_8270.py` (SPOTTING/SP path, assert-sim green) · `controller_io.py` (MachineIO + RecordingIO, smoke test green) · `phase8_channel_allocation.md` (per-pin map) · board arch = **self-contained identical single-lane boards** (3× MCP23017 + 1 RP2040 + AEDIKO + NE555 watchdog, per board; per-board I²C bus; **UART** Pi↔RP2040). AEDIKO specs in-repo (5 V, onboard opto+flyback, switches coils not motors).

### ✅ TODAY'S BENCH WINS (spare cabinet — all bench-confirmed)
| item | result |
|---|---|
| **Connector roles** | **C1 = motor/CONTACT side** (heavy 115 V to motors, 3-col conn, 2 power cavities, "C1" stencil). **C2A = COIL/control side + cams** (4-col, many thin wires). |
| **S relay** | = the **Siemens 3TH4022-0AC2**, coil **24 VAC** (5 Ω, datasheet-confirmed). Contacts → C1: C,D,N,T. |
| **T relay** | open-frame contactor. Contacts → C1: A,K,H,E. Coil switched-side → board (0 Ω). |
| **Coil family** | ALL **24 V**: S=24VAC(5Ω), M/M2=80Ω, SP=100Ω, BE=22Ω. One coil-voltage family → simple enclosure rails. |
| **Output→connector** | S,T (main motors) → **C1**; M2,SP,M (low-power) → **C2A**; BE straddles. Channel-alloc §3 updated. |
| **KX relay** | **SKIP** — it fed the old scorer; camera replaces it. |
| **Cam-stops (JOB 2)** | **Leans LOGIC** (board = triac+CMOS driver bank; T switched-side runs to board). NOT airtight — see open item. |

Detail + raw readings: `phase8_bench_session1_FINDINGS.md`. Probe procedures: `phase8_bench_C1map_worksheet.md`, `phase8_bench_JOB2_camstop.md`.

### ⚠️ ONE OPEN BENCH QUESTION (does NOT block design)
**Is the motor cam-stop hardwired or logic?** Today's elimination test was defeated by the shared 24 V supply rail (a flaw in my test, not a probing error) — a coil reading 0 Ω to C2A is the *supply bus*, not a cam-in-series. Evidence **leans LOGIC** but isn't conclusive.
- **Why it doesn't block:** we add hardware end-stops + TB/SC interlock + RP2040 cam-stop timing **regardless** (never trust software near motors). This only decides whether an *existing* cam-stop is preserved as a bonus backstop — a cutover wiring detail.
- **To close it (pick one, low priority):** (a) **5-min bench probe** — separate S's switched-vs-supply side (supply beeps to M2/SP coils; switched does not), then check S-switched → board like T; OR (b) **defer to the at-machine cam-flip test** at cutover (airtight anyway).

### TRACK B — what's left (UPDATED 2026-06-02)
1. ✅ **C1 pinout corrections applied** (S-T1=C, T=L) → `phase8_controller_interface_MAP.md`.
2. ⏸️ **C2A INPUT side — bench-EXHAUSTED, rest is machine-gated.** No physical "TAC strip" exists (grippers land directly on C2A cavities; "TAC"=net name). Grippers + cams are OPEN switches → can't cold-map per-pin; PBZ/PBC buttons are REMOTE (not on this cabinet). Per-signal C2A binding waits for the **at-machine cutover session** (actuate each + watch C2A). **Does NOT gate PCB** — board needs channel COUNT (locked), not per-pin binding. (`phase8_bench_JOB3_C2A_inputs.md` documents what's bench-able vs machine-gated.)
3. ⏳ **cam-stop S-side airtight proof** — deferred to at-machine (S board-pin inaccessible on bench). Leans LOGIC; not a design gate.
4. 🔨 **PCB rev-B — IN PROGRESS.** Decision: **fully-integrated single board** (opto-in + relay drivers designed in; no COTS AEDIKO/AL-ZARD). Spec-first: `phase8b_pcb_revB_spec.md` (DRAFT v0) → **next = Codex-review the spec on paper** (focus relay-enable rail + safety + power), then extend the SKiDL generator. Toolchain proven (rev-A scripts present in `scripts/`).
5. **Off-live validation plan** (locked-out machine) before any live motor — part of the rev-B build sequence.

### AT-MACHINE SESSION (cutover prep) — deferred bench items collected here
- Per-gripper GS-n ↔ C2A cavity (lift each pin, watch which closes).
- Per-cam SA/SB/SC/TA1/TA2/TB ↔ A&MC/C2A (rotate mechanism, watch which closes at which angle).
- GP/OS/BS/Foul/PBZ/PBC actuation → C2A cavity.
- Cam-stop logic-vs-hardwired airtight (flip cam, watch coil).
- TB/SC interlock electrical form on our chassis.

---

## DECISIONS LOCKED (don't relitigate)
- Track A resolution **720×576 PAL**, `MIRROR=True`, deck L=21/R=22.
- Board = **self-contained identical single-lane boards**; **UART** RP2040↔Pi; per-board I²C bus; one RP2040/board.
- All relay coils are **24 V**; AEDIKO switches **coil circuits** (machine contactors keep handling motor inrush).
- C1 = motor/contact connector, C2A = coil/control+cam connector. Siemens = S. KX skipped.

## NEW DOCS THIS SESSION
- `phase8_session_close_2026-06-01.md` (this) · `phase8_channel_allocation.md` · `phase8_trackA_golive_runbook.md` · `phase8_bench_session1_FINDINGS.md` · `phase8_bench_C1map_worksheet.md` · `phase8_bench_JOB2_camstop.md` · `lane_node/controller_io.py` · `lane_node/camera.py`.

## START HERE TOMORROW
- **If at the lanes:** run the Track A go-live runbook → scoring live on 21/22.
- **If at the bench:** Track B item #2 (C2A input/gripper map) — ask Claude for the worksheet; or close the cam-stop question first (#1, 5 min).
- **If at the desk:** Track B #3 (pinout corrections) + start the rev-B schematic on the confirmed output side.
- **Scratch:** crop/resize temp images live in `Downloads/Cabinet images/_small/` (regenerable, ignorable).
