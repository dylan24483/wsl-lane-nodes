# AMF 82-70 — Machine Device Location Guide

Where every cam, switch, gripper, the start-switch/DIELL, and the foul unit **physically sits on the machine** — so you can find each one to clip a meter lead. Companion to **§1 of the metering guide** (`phase8_metering_guide_harness_unknowns.md`) and **§4 Machine I/O Inventory** (`manual_src/04_machine-io.md`).

**Sources** (in `WSL Systems/`): service-parts manual `UPDATED8270-service-parts-manual.pdf` (physical labeled photos/drawings) · operation/training manual `UPDATED 8270-pinspotter-operation-training-manual.pdf` (switch legend + cam timing). **Rendered diagrams:** `Downloads/machine_diagrams/`.

---

## ★ The one master diagram — service-parts p29
`svc_p29_machine_overview_HI.png` — a labeled back-end photo of the whole machine. In **one image** it calls out: **SA / SB / SC** ("Sweep Cam & Switch"), **TA1 / TA2 / TB** ("Table Cam & Switch"), **Off Spot Switch Lever**, **Sweep Motor**, **Table Motor**, **Spot Solenoid**, **A & MC Plug**, Russell-Stoll Plug, and the Shuttle/Respot/Spot levers. **Start here** — everything else below is a close-up of one device on this photo.

---

## Device-location table

| Device | Where it physically sits | Manual fig. | Diagram file |
|---|---|---|---|
| **Sweep cams SA / SB / SC** | Stacked on the **sweep-shaft**, back end, next to the Sweep Motor and the **A&MC plug** (right side of the p29 photo) | svc p29 | `svc_p29_sweepcam_crop.png`, `svc_p29_machine_overview_HI.png` |
| **Table cams TA1 / TA2 / TB** | Stacked on the **table shaft** (left-center of the p29 photo), with the Off-Spot lever | svc p29; exploded svc p257 | `parts_p257.png`, `svc_p29_machine_overview_HI.png` |
| **Cam-switch assembly (exploded)** | Bracket + microswitch + cam weldment on each shaft — how the cam/switch/bracket stack assembles | svc p256–258 | `parts_p257.png` |
| **OS — Off-Spot switch** | On the **table torque tube**; lever closed by the **Clevis** when the table hits an off-spot pin → forces 2nd-ball logic | svc p82 | `svc_p82_offspot_switch.png` |
| **BS — #9 Bin switch** | In the **bin framework between the #8 and #9 bins**; Switch Actuator Lever trips when pin #9 lands ("10 pins ready") | svc p81 | `svc_p81_bin_switch.png` |
| **SS — Start switch** (the cycle trigger; **= DIELL** on our lanes) | OEM lever on the **kickback/cushion**, tripped by cushion movement on ball impact. On 21/22 the SS *function* is the DIELL photoeye, but this shows where the cushion switch sits | svc p112 | `svc_p112_start_switch_cushion.png` |
| **Grippers GS1–GS10** | Ten respot-cell pockets on the **triangular spotting table**, in the pin triangle (see numbering below) | svc p186; cell detail p188 | `svc_p186_hi.png` |
| **GP — Gripper-protect switch** | On the **table/gripper mechanism**; closes when grippers fully open (protects table fingers). *No standalone photo in either manual* — logic input only | legend op p11; circuit Fig.18 (tm p38) | `op_p11_switch_legend.png`, `tm_p38.png` |
| **PBZ (Zero/1st-ball) & PBC (Cycle) buttons** | Pushbuttons on the **rear / back-end control panel**. *Manuals give legend + wiring only — no clean panel-face photo* | legend op p11; wiring op p34/p40 | `op_p11_switch_legend.png`, `op_p40_rear_panel.png` |
| **FOUL (Radaray)** | **Not on the pinsetter** — a foul-line accessory. *No mechanical drawing in either manual*; needs the separate AMF Radaray doc | op p11 (foul light only) | — |

---

## Gripper numbering GS1 → GS10

Standard USBC pin triangle — **gripper switch GS-N = respot cell N = pin N**:

```
        (back of deck / pit side — wide edge of the table)
     7     8     9     10      <-  GS7  GS8  GS9  GS10   (back row)
        4     5     6          <-  GS4  GS5  GS6
           2     3             <-  GS2  GS3
              1                <-  GS1  (head pin)
        (front / approach side — apex of the table)
```

- **GS1** = head pin (front apex). **GS7–GS10** = back row, along the table's widest edge.
- Each gripper switch **closes (signals) to the machine chassis** when a standing pin is lifted by that cell — confirmed even in the OEM legend ("GS gripper switch — signals chassis when pins present").
- **Cell #7 is the one mechanically-distinct unit** (its own part numbers / yoke assembly); cells 1–6 and 8–10 are the common type. Only asymmetry in the set — note it for the pin-detect harness.

> **Software label is set at cutover, not assumed.** Don't trust a physical GS# wire number to match the software channel. Map each by **dropping one pin in one cell and watching which input asserts** (metering-guide §1 gripper note). The triangle tells you where to look; the live drop locks the binding.

---

## TAC strip — OEM vs. your 21/22 machine (reconciliation)

The OEM manuals route the 10 gripper wires to a **"TAC" terminal strip, terminals 1–10** (training-manual **Fig.18** / `tm_p38.png`). Important detail: Fig.18 labels that strip **"WIREWAY ASSY — LEFT FRONT OF MACHINE"** — i.e. out at the machine's left-front, **not** in the control cabinet.

Your project's **§4.3 at-machine trace (2026-06-03)** found **no physical TAC strip in the Omega-Tek cabinet** — the gripper wires run in the table harness **direct to C2A**, with the **machine chassis as the common return**.

These reconcile cleanly: **both agree the grippers signal to chassis.** The only open question is whether the physical left-front TAC terminal block still exists on your machine or was bypassed in the Omega-Tek retrofit.

**Practical takeaway:**
- **Look** for a 10-terminal strip in the wireway at the **left front of the machine**. If it's there, it's a tidy 1–10 clip point for all ten grippers.
- If it's absent (likely on the retrofit), the grippers land direct on C2A — use the **drop-a-pin** method, which works either way and also numbers them.

---

## Quick reference legends (rendered)
- **Switch master key** — `op_p11_switch_legend.png` (defines SS/OS/GP/GS/BS/PBZ/PBC/SWS/SWSR/T/S + motors + solenoids).
- **Cam timing** — `ops_p9.png` (SA 360°/2nd-guard · SB 66° first-guard / 186° spot · SC interlock · TA1 355° · TA2 260° · TB interlock). Matches §4.2.

## Not available in these manuals
- **Rear control-panel face photo** (PBZ/PBC buttons) — legend + wiring maps only.
- **Radaray / foul mechanical drawing** — a separate AMF Radaray/Magic-Score document.
- **Full-machine wiring schematics** (svc p287/p290) exist but are too dense at page scale — net references only; crop per-region at high DPI if you must trace one net.
