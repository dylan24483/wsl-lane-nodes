# 8270 Controller Interface Map — the Pi-controller I/O contract

**Source:** QubicaAMF *8270 MP Pinspotter Operation Training Manual* (PN 610000009), mined in full 2026-05-31 (text + all controller-relevant diagrams). This synthesizes the controller↔machine interface so the field sheet (`phase8_controller_interface_fieldsheet.md`) becomes **"verify a few specifics on our spare,"** not "trace 40 pins blind."

> **Not in this manual:** the big foldout schematics — *9807 MP Chassis & Machine*, *6730 5-Board Chassis & Machine*, *5500 82-70 Machine Wiring*. They're in the **161 MB Service & Parts manual (#2)**. Get that for the exact node-by-node schematic if/when needed.
>
> **Chassis caveat:** the manual's wire tables are the **9800 MP** and **6700 ELCO** chassis. Our **spare is an SS chassis + Omega-Tek Omniboard** (21/22); lanes 11/12 are the **MP** (Ultra 98). The **machine side is common** (same 82-70 cams/motors/grippers via C1/C2A) — only the chassis-internal wiring differs. Verify machine-side pins on our spare; use the Omega-Tek manuals (already have) for that board's internals.

---

## Architecture (confirmed)
The controller **reads machine switches/cams** (via the **C2A** plug + the **TAC** gripper terminal strip) and **drives relay coils** (M/M2/S/T/BE/SP/M1) that switch **115 VAC** to motors/solenoids, plus **lamps** to the mask. On an MP chassis the switches sit at **5 VDC / 24 VAC**. The Pi-controller must present this same I/O.

## INPUTS — Pi must READ (machine → controller, via C2A + TAC)
| Signal | Function | Cam° |
|---|---|---|
| **SS** start switch | cycle trigger (ball hits cushion) — *DIELL on our lanes* | — |
| **SA** sweep cam | stops sweep @2nd guard, runs up, stops @zero | 360° |
| **SB** sweep cam | stops sweep @1st guard (66°), starts table spotting (186°) | 66/186° |
| **SC** sweep cam | table-sweep interlock | — |
| **TA1** table cam | runs table up, stops table @zero | 355° |
| **TA2** table cam | starts sweep run-through; starts sweep up @cycle end | 260° |
| **TB** table cam | table-sweep interlock | — |
| **GS1–GS10** grippers | pin sense (respot cells) → **TAC strip → C2A** | — |
| **GP** gripper-protect | blocks table feeling for pins when off | — |
| **OS** off-spot | table contacts off-spot pin | — |
| **BS** bin switch | #9 pin present in bin | — |
| **PBZ** zero switch | 1st/2nd-ball status; MP restart ("manual intervention") | — |
| **PBC** / 10th-frame / manual T,S,SWS | cycle-from-rear / approach / manual run | — |

**Levels:** 5 VDC / 24 VAC at the switches (MP). Switches are NO/NC closures. ~23 read channels (13 control/cam + 10 grippers) → opto-isolate.

## OUTPUTS — Pi must DRIVE (controller → machine)
**Relay coils** (Pi energizes coil; relay switches 115 V to the load):
| Relay | Drives |
|---|---|
| **M** master | power to T1 / halo / pit light |
| **S** sweep | sweep motor |
| **T** table | table motor |
| **BE** back end | back-end motor (pin/ball elevator, pitveyor, distributor) |
| **M2** sweep reverse | sweep reverse (auto-scoring gutter / 7-10) |
| **SP** spot | spot solenoid |
| **M1** | ball return |

- **Motor circuits** (p17/p18): T/S relays switch 115 V to main (≈1.5 Ω) + start (≈4.2 Ω) windings via caps + centrifugal switch; **braking** on the N.C. contacts (regenerative). BE: single start cap, **no brake**.
- **Status lamps** (mask, **12 VDC**, p36): 1st ball **PM-E24**, 2nd ball **PM-E25**, foul **PM-E27**, strike **PM-E26**.
- **Pin lamps** (mask): **D1–D10** in series with pin lamps 1–10. *(May be driven from our camera data instead — convergence with Track A.)*
- **Neon / mask hi-V lamp**: ~125 VAC / ~-160 VDC supply (p37).
- **Spot solenoid** via SP relay.

~22 output channels (7 relay coils + 4 status lamps + 10 pin lamps + spot) → relay/SSR bank.

## SAFETY — preserve in hardware
- **Stop switch** (post-1979, left of power plug) + **C.I.S.** (1981, under plug-duct cover): both **cut the rear-panel MASTER circuit breaker** → kills control power. Hardware.
- **Table-sweep INTERLOCK** (p15): **TB + SC contacts in PARALLEL** in the 24 V relay-control path. On a collision course both open → both motor relays drop. **Hardware collision-prevention — PRESERVE.**
- **Motor braking**: regenerative, in the relay N.C. contacts + caps. Hardware.
- **⭐ Field-sheet Part 4 ANSWERED:** the cam-position stops (SA/TA1 @zero) are **controller LOGIC** (read cam → drop relay), **not** a hardwired motor latch. So the **Pi times the stops** (real-time → MCU co-processor) with **TB/SC as the hardware backstop** and braking in hardware. Verify on our spare, but expect the same.

## POWER
- 115 VAC in via Russell-Stoll (hot + neutral + ground); 25 A breaker/machine.
- **Transformers:** T1 (chassis voltages), T2 (24 VAC managers control), T3 (24 V board), T4 (24 V BE/M1 relays).
- Rails (MP): 5 VDC + 24 VAC (switches), 12 VDC (status lamps), ~125 VAC/-160 VDC (neon mask).

## Connector pinouts (from the wire tables — chassis side)
- **C1 = motor/relay + power side** (p46, 9800 MP): C1-21D→S-31, 22J→S-14, 23N→S-21, 24T→S-32 (sweep); 31A→T-44, 32E→T-32, 33K→T-21, 34P→T-31, 42H→T-43 (table); 17DD→M2-8, 18J→M2-9, 26BB→M2-11, 27FF→M2-1 (sweep-rev); 35U→SP-5, 36Y→SP-7 (spot); 45W→BE-7, 47EE→BE-3 (back end); 13L→T2, 19NN→GND.
- **C2A = switch/manual-control side** (p42, 47 wires + p34): carries S/T/SWBE/PBC/CB/A&MC/TS/**TAC (grippers)**/PZ. (Full per-pin table on manual p42 — high-DPI crop if a specific pin is unclear.)
- **Mask plug (PM):** pin lamps (D1-10) + status lamps (E24-27) + neon.
- **Table plug / A&MC** (curtain wall): gripper/respot + misc.

## Pi I/O budget (confirmed) → drives the board design
- **~23 inputs** (opto-in, 5 VDC/24 VAC) + **~22 outputs** (7 relay coils @24 V + ~14 lamps + spot) ≈ **~45 channels** → MCP23017 expanders + opto-in banks + relay/SSR-out banks (watchdog + AEDIKO relays slot in here). Pin lamps likely fed from camera data (Track A convergence) — trims the output count.

## Still to do
1. **Verify machine-side C1/C2A pins on OUR spare** (SS/Omega-Tek). Machine harness should match the tables above; the Omniboard's internal mapping comes from the Omega-Tek manuals.
2. **Get the Service & Parts manual (#2)** for the foldout schematics (9807/5500) — the exact node graph.
3. High-DPI crop of p42 (C2A table) / p58-59 (C2A harness) for any specific pin label as needed.
