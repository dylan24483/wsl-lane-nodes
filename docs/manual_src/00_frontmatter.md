# Westside Lanes — Phase 8 Lane Controller & Scoring System
## Technical Reference & Service Manual

**Baseline manual hardware:** rev-B · **Current controlled firmware bundle:**
RP2040 v1.2.3 (Rev-D-only, not flashed; measured-cam flags OFF) · **Source set
reconciled:** 2026-07-24

> **SC/TB OPERATIONAL CORRECTION (2026-07-24 — supersedes every older SC/TB/J14 statement in this manual):** powered testing on 2026-07-07 proved the OEM ladder uses **parallel closed-when-safe contacts**; either pressed lever permits a coil and **both levers BACK/open kill both S and T coils**. The 2026-06-27 cold trace proved only that C2A-U is a non-isolatable live-ladder region, TB has no standalone/dry J_SAFE landing, and ~21 Ω coil sneak paths prevent topology inference. **Candidate C is decided:** J_SAFE1-2 receives the controlled, labeled jumper; the OEM ladder is the primary guard; every lane must pass the G3 board-commanded S-and-T coil-drop insertion proof. The firmware SC∧TB echo is default-off, secondary, and unvalidated because there is no independent TB observation.
>
> **REV-D/R5 INPUT-BIAS CORRECTION (2026-07-24 — supersedes generic 10 kΩ/GPPU statements in the Rev-B chapters):** the current Rev-D/R5 board has exactly forty PC817 collector pull-ups `Rpu_*` (`R4,R6,…,R82`) at **47 kΩ** (UNI-ROYAL `0805W8F4702T5E`, LCSC C17713). Production firmware disables RP2040 GP6–GP13 PUE/PDE, and the Pi driver commands and reads back U1/U2 MCP23017 `GPPUA=GPPUB=0x00`; any internal pull enabled is **STOP-SHIP** because it invalidates the qualified 47 kΩ-only margin and can mask an open external pull-up. Rev-B's 10 kΩ `Rpu_*` value remains historical; unrelated 10 kΩ networks, including `R_TAPPU_*`, are unchanged. This margin change does not waive per-channel first-article FA-9 at loaded-minimum `FIELD_WET_V` and ≥70 °C.
>
> **RETIRED / FROZEN BINARY EXPORTS:** `WSL_PHASE8_SYSTEM_MANUAL.docx` and `WSL_PHASE8_SYSTEM_MANUAL.corrected.docx` have a retirement cover, but their bodies were compiled on 2026-06-04 and do **not** contain this reconciliation. Do not use either DOCX body for Rev-D assembly, SC/TB/J_SAFE wiring, diagnostics, or cutover work; use the current Markdown sources, Rev-D R5 fab manifest/README, `phase8_interlock_redesign.md`, the lane harness build sheet, and the Track-B cutover runbook.

**Status:** The Rev-D design and immutable R5 fab package have been generated, but the board is **not fab-ordered and is not authorized for JLCPCB ordering or controller cutover**. Physical release remains **NO-GO** pending the recorded sign-offs, vendor-upload inspection, first-article/FA-9 qualification, powered proof, and bench gates. This manual documents the system *as designed*; values still to be confirmed against real hardware are marked `(VERIFY: …)` inline and summarized in the **Open-Items Register** below.

---

### Purpose & audience
This is the complete, top-to-bottom reference for the system that replaces **Conqueror Pro** (bowling ops), the **QubicaAMF VDB scoring** stack, and the **OEM AMF 82-70 controller brain** at Westside Lanes (32 lanes / 16 pinsetter pairs). It assumes a competent engineer or electrician with **zero prior context on this project**, and is written so that person can operate, repair, calibrate, or extend the system without the original author present. Read §1–§2 for the whole picture; use the rest as a lookup reference.

### How to use this manual
| You want… | Read |
|---|---|
| The big picture + what it replaces | §1 System Overview, §2 Architecture |
| How the bowling machine itself works | §3 Sequence of Operation, §4 Machine I/O |
| The controller board (theory of every block) | §5–§10 |
| **A specific connector pinout / channel map** | **§11 Connector Pinouts, §12 Channel Maps** |
| How it manufactures (net classes, DNP, fab) | §13, §20 |
| How the board wires to the machine | §14 Machine Interface (C1/C2A + harness) |
| The software/firmware | §15 Firmware, §16–§17 Pi software, §18 Camera scoring |
| **Safety — read before any powered work** | **§19 Safety Architecture** |
| Deploy, bring-up, cutover, troubleshoot | §20–§22 |
| Full BOM, cam timing, glossary, doc index | §23 Appendices |

> ⚠️ **SAFETY.** This system controls an AMF 82-70 pinsetter that **moves and bites**, and it switches mains-powered motor contactors. Read **§19 (Safety Architecture)** and the **lockout/tagout procedure in §21** before any powered work on a machine. The board is never the only safety device — the machine's Stop/C.I.S./master-breaker chain and TB/SC interlock stay in hardware.

### Source & maintenance
This manual was assembled from per-section source files in `docs/manual_src/`
(`00`–`23`). For current Rev-D work, source-of-truth order is the Rev-D netlist
generator, manifest-controlled firmware, lane harness build sheet, interlock
redesign, and current cutover runbook; frozen Rev-B fabrication prose remains
historical. If prose disagrees with those sources, the prose has a bug.

---

### Open-Items Register (reconciled 2026-07-24)
Every item below is *intentionally* unresolved at design/fab time and resolves at the noted stage. The inline `(VERIFY: …)` flags throughout the manual point back to these.

| # | Open item | Resolves at | See |
|---|---|---|---|
| 1 | Independently landed motion-cam **SA/SB/TA1/TA2** cavity/class + trip-edge polarity. SC/U stays unlanded; TB has no lane-21/22 lead. | Powered capture before new enforcement release | §14; cutover runbook §3.2 |
| 2 | Per-gripper **GS# → C2A cavity** (1:1 order) | Cutover (drop one pin, watch which input asserts) | §14; runbook §3.1 |
| 3 | **Stop/CIS J_SAFE3-4** + exact C1/C2A output insertion. TB/SC is Candidate C (controlled 1-2 jumper + per-lane S/T G3 proof), not a terminal search. | Cutover | §14; runbook §3.3–3.5 |
| 4 | **M1** (ball-return) existence on this chassis — stays **DNP** until proven | Cutover | §9, §14 |
| 5 | `controller_daemon.DEFAULT_BOARDS`: real I²C bus ids, UART ports, ARM + watchdog GPIOs, MCP INT lines (currently `# CONFIRM` placeholders) — boot overlays, pin table + the Track-A coexistence constraint in **`docs/phase8_pi_provisioning.md`** | Bench bring-up | §12, §17 |
| 6 | Capture each independently landed motion-cam polarity; enable only confirmed cam-stop paths in a **new controlled release**; pass first-article/bench G3 sub-tests. Stock v1.2.3 flags are OFF. | Before controller cutover | §15, §19, §21 |
| 7 | **Relay contact current rating** + snubber/MOV population (field-sheet A2) | At-machine coil-current measurement | §9, §13 |
| 8 | **Status-LED current-limit resistor** (`Rled_*` = 330R placeholder) | Final LED brightness selection | §9, §12 |
| 9 | **SP spot-solenoid working voltage** (presumed ~24 VAC; coil was inaccessible at the field session) | Cutover glance | §3, §5 |
| 10 | **24 VAC creepage relax** (board is routed to conservative 250 VAC spacing; optional shrink before the 16-lane fleet run) | Pre-fleet, optional | §5, §13 |
| 11 | Hand-solder part sourcing: **TRACO TMA-0505S**, the **Phoenix mating plugs**, the **Pico module** (none are JLC-placed) | Procurement | §20, §23 |
| 12 | Track-A scoring soak tuning: `WSL_LANE_CAMERA_SETTLE_S`, pins 2 & 3 (homography-predicted), `MIRROR` confirm with a deliberate 7- or 10-pin | Scoring go-live soak | §18 |

> A historical doc lists the machine **mask-lamp supply as 12 VDC**; the field measurement is **15 VDC**. This is **moot** — the board drives its own status LEDs and the machine lamp supply is abandoned (§9).

---

### Table of Contents
1. System Overview & Purpose
2. System Architecture & Signal Chain
3. The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing
4. Machine I/O Inventory (Cams, Grippers, DIELL, Foul, Mask, Buttons)
5. Rev-B Controller Board: Overview, Domains & Isolation
6. Rev-B Power Architecture
7. Rev-B Logic: RP2040 Co-processor + MCP23017 Expanders + I²C
8. Rev-B Field Inputs: PC817 Opto-isolators
9. Rev-B Machine Outputs: G5LE Relays
10. Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail
11. Rev-B Connector Pinouts (J1–J14)
12. Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps
13. Rev-B Layout & Manufacturing Contract (Net Classes, Creepage, DNP, Test Points)
14. Machine Interface: C1/C2A Connectors & the Adapter Harness
15. RP2040 Firmware (Safety Co-processor)
16. Pi Software: The Cycle-Control FSM
17. Pi Software: IO Layer, RP2040 Link & Controller Daemon
18. Camera Pin Scoring (Track A)
19. Safety Architecture (Consolidated)
20. Operations: Network, Deployment, Build & Fab
21. Bring-up, Bench Validation & Cutover
22. Troubleshooting, Maintenance & Spares
23. Appendices: Full BOM, Cam Timing, Glossary & Document Index
