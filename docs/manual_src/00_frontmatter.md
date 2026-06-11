# Westside Lanes — Phase 8 Lane Controller & Scoring System
## Technical Reference & Service Manual

**Hardware revision:** rev-B controller board · **Firmware:** RP2040 v0.1.0 · **Compiled:** 2026-06-04
**Status:** Design + fabrication complete (bare PCB + Standard-PCBA package released to JLCPCB). On-hardware **bench bring-up and the Track-B cutover are still pending.** This manual documents the system *as designed*; values still to be confirmed against real hardware are marked `(VERIFY: …)` inline and summarized in the **Open-Items Register** below.

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
This manual was assembled from per-section source files in `docs/manual_src/` (`00`–`23`), each grounded in the live design files (the KiCad netlist generator, the firmware, the Pi code, and the fab BOM/CPL). To update: edit the relevant `docs/manual_src/NN_*.md` and re-assemble. **Sources of truth for pins/parts/maps** are the code + netlist, not prose — if this manual ever disagrees with `scripts/generate_kicad_netlist_revB.py`, `firmware/rp2040/`, `lane_node/controller_io.py`, or the fab BOM, the code wins (and this manual has a bug to fix).

---

### Open-Items Register (as of 2026-06-04)
Every item below is *intentionally* unresolved at design/fab time and resolves at the noted stage. The inline `(VERIFY: …)` flags throughout the manual point back to these.

| # | Open item | Resolves at | See |
|---|---|---|---|
| 1 | Per-cam → C2A cavity **and trip-edge polarity** (SA/SB/SC/TA1/TA2/TB) | Cutover (hand-rotate mechanism, watch the live input feed) | §14; cutover runbook §3.2 |
| 2 | Per-gripper **GS# → C2A cavity** (1:1 order) | Cutover (drop one pin, watch which input asserts) | §14; runbook §3.1 |
| 3 | **TB/SC interlock** + **Stop/CIS** + exact **C1/C2A relay landings** | Cutover | §14; runbook §3.3–3.5 |
| 4 | **M1** (ball-return) existence on this chassis — stays **DNP** until proven | Cutover | §9, §14 |
| 5 | `controller_daemon.DEFAULT_BOARDS`: real I²C bus ids, UART ports, ARM + watchdog GPIOs, MCP INT lines (currently `# CONFIRM` placeholders) — boot overlays, pin table + the Track-A coexistence constraint in **`docs/phase8_pi_provisioning.md`** | Bench bring-up | §12, §17 |
| 6 | RP2040 **firmware v1.1 cam-stop overrun** (needs cam polarity from item 1) — until then the cutover G3 cam-stop sub-test is blocked | Post-cutover capture | §15, §19, §21 |
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
