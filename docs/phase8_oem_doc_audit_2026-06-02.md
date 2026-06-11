# Phase 8 - OEM Documentation Audit

**Date:** 2026-06-02
**Purpose:** capture the OEM/OmegaTek read-through before Rev-B schematic/netlist work.

This note is an evidence sheet for `phase8b_pcb_revB_spec.md`. It is not a replacement for at-machine verification; it records what the manuals say and how that should constrain the PCB contract.

## Documents Read

Located in `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs`:

- `8270-pinspotter-operation-training-manual.pdf`
- `8270-service-parts-manual.pdf`
- `610-007-030, 8270 PC Board Components Manual.PDF`
- `OmegaTek_Omniboard.pdf`
- `OmegaTek_Expander_Card.pdf`

Scratch extraction/render artifacts are under:

- `C:\Users\Dylan DeYoung\WSL Systems\.tmp_oem_review\extracted_text`
- `C:\Users\Dylan DeYoung\WSL Systems\.tmp_oem_review\omegatek_omniboard`
- `C:\Users\Dylan DeYoung\WSL Systems\.tmp_oem_review\omegatek_expander_card`
- `C:\Users\Dylan DeYoung\WSL Systems\.tmp_oem_review\8270_pc_board_components`
- `C:\Users\Dylan DeYoung\WSL Systems\.tmp_oem_review\service_selected_pages`

The OmegaTek and PC-board documents are scanned/image-heavy, so they were rendered page-by-page and OCRed. High-risk schematic and connector pages were also checked visually.

## Confirmed OEM Constraints

### 1. S/T Contactors Must Stay Mechanically Authoritative

The training manual describes S and T relays as having both NO and NC contacts. Energized NO contacts feed the motor main/start circuits; de-energized NC contacts connect capacitors across the main winding for regenerative braking.

PCB implication:

- Rev-B must command the existing S/T control circuits only.
- Rev-B must not replace the S/T relay/contactors' multi-contact motor/braking function.
- A relay-output PCB is still valid, but it must not route motor current or bypass the original braking contact set.

### 2. TB/SC Is A Real Hardware Interlock, Not A Software Hint

The training and service manuals define:

- `SC` sweep interlock cam: sweep under table, approximately 86 to 243 degrees.
- `TB` table interlock cam: table/sweep interference zone, approximately 105 to 255 degrees.
- The table/sweep interlock removes controlling voltage when table and sweep are both in an unsafe interference relationship.

PCB implication:

- TB/SC must remain a hardware rail condition in Rev-B.
- It is acceptable for firmware to observe TB/SC, but firmware observation is not enough.
- The schematic must provide a non-software path that drops output-relay permission on interlock fault.

### 3. Cam Timing Is Tight Enough To Budget Input Latency

The service manual identifies SA/SB/SC and TA1/TA2/TB as the cam timing surfaces. The OmegaTek manual describes timing transitions around sweep 66, sweep 270, table 260, and table 355/360, including SA/TA-2 overlap behavior.

PCB implication:

- Fast cam channels need bounded, documented debounce/filter latency.
- Avoid slow RC filters on SA/SB/SC/TA1/TA2/TB that could hide edge timing or overlap.
- RP2040 fast-input paths should be edge-capable and have a firmware-configurable debounce window.

### 4. C1/C2A Are Mixed Machine Interfaces

OEM connector tables and schematics do not support a simplistic "C1 = power, C2A = logic" split. Broadly:

- C1 carries S/T/BE/SP and sweep reverse related machine/control wiring.
- C2A carries many control/cam/gripper/scoring/lamp paths and machine references.
- C2A-12F is identified as chassis ground in the training manual and OmegaTek installation checks.

PCB implication:

- The Rev-B board should continue to expose function-named connectors.
- The adapter harness, not PCB copper, maps functions to C1/C2A cavities.
- Treat both C1 and C2A as field/machine domains unless a specific net is verified.
- Do not tie machine ground/reference to logic ground by assumption.

### 5. OEM Sweep Reverse / M2 Path Is Not A Universal Cavity Map

The training manual and OmegaTek Expander manual repeatedly identify C1 pins in the sweep reverse path:

- C1-17DD
- C1-18JJ / 18J depending on drawing/OCR
- C1-26BB
- C1-27FF

The Expander installation uses those C1 pins plus TSA-2/TSA-3 and sweep motor plug wiring. The shorting-plug warning also says the expander cable must be terminated or sweep will not run.

PCB implication:

- The Rev-B `M2`/sweep-reverse output must be function-named and harness-resolved, not assigned to a universal C1 or C2A cavity in copper.
- OEM docs identify a C1/TSA/Expander path; our SS + Omega-Tek bench measured M2 at C2A. Treat both as chassis-specific evidence.
- Harness design must preserve whatever motor-start/reverse interlock function currently lives in the machine wiring.

### 6. OmegaTek Uses Optos, SCRs/Triacs, MOVs, Debounce ICs

The OmegaTek and AMF PC-board manuals show:

- Opto-isolators/photo couplers on machine inputs and outputs.
- SCRs/triacs for lamps/relay-style power switching.
- MOV/transient suppression components.
- Digital debouncing around machine switch inputs.

PCB implication:

- Rev-B's isolated dry-contact relay output topology remains conservative and appropriate.
- Snubber/MOV footprints on motion outputs are not optional decoration; they are part of surviving inductive machine control wiring.
- Input isolation and transient protection should be treated as source-compatible behavior, not overengineering.

### 7. TAC / Gripper Mapping Needs Field Verification

The training/service manuals refer to TAC terminal contacts/wiring for gripper switches GS1-GS10. Bench notes suggest the physical terminal-strip presentation may differ on the actual OmegaTek-retrofitted chassis.

PCB implication:

- Allocate GS1-GS10 channels, but do not lock final C2A/TAC cavity mapping into copper.
- Keep gripper channels function-named and software/harness mapped after at-machine actuation tests.

## Corrections To Carry Into Rev-B

1. Mark M2/sweep-reverse cavity routing as chassis-specific and harness-resolved. OEM docs show C1/TSA/Expander; our SS + Omega-Tek bench measured C2A.
2. Add an explicit S/T braking-contact warning: command existing contactor coils/control circuits only.
3. Add a fast-input debounce/latency budget as a netlist blocker.
4. Keep TB/SC as a first-class hardware rail condition, now OEM-confirmed rather than merely bench-suspected.
5. Preserve the function-named connector strategy because OEM C1/C2A are mixed and machine-specific.

## ⚠️ OEM-vs-BENCH RECONCILIATION (Claude, 2026-06-02) — read before trusting §4/§5 cavities
The OEM wire tables document the **9800-MP / 6700-ELCO factory chassis.** Our spare is an **SS chassis + Omega-Tek retrofit** (lanes 21/22). They **disagree on cavity routing**, and that's expected — the retrofit moved harness landings. Two concrete conflicts with yesterday's bench (`phase8_bench_session1_FINDINGS.md`):

| signal | OEM audit says | OUR bench measured | resolution |
|---|---|---|---|
| **M2 sweep-rev** (§5) | C1-17DD/18JJ/26BB/27FF | **C2A, direct 0 Ω** | chassis-specific; harness resolves |
| **C1/C2A split** (§4) | "not a simple power/logic split" | largely WAS a split (S/T motors→C1; SP/M/M2 low-power→C2A) | both true for their chassis |

**Neither is wrong** — they describe different chassis. **Takeaways that ARE chassis-independent (keep):** isolated inputs, dry-contact outputs, MOV/snubber, TB/SC as hardware interlock, S/T braking-contact preservation, the M2/Expander start-reverse-interlock + shorting-plug function. **Takeaways that are chassis-SPECIFIC (do NOT bake into copper, harness-resolve):** every actual C1/C2A cavity number, OEM or bench. This *strengthens* the function-named-harness decision: cavities vary by chassis type (OEM vs Omega-Tek vs Active-98), so a per-chassis adapter harness is the only correct path. The audit's cavity citations are valid as "what to look for," not "what our chassis has."

## Open Items After OEM Read

- At-machine confirmation of actual coil/control voltage and current for S/T/SP/BE/M/M2.
- At-machine confirmation of TB/SC electrical form and best safe method to include it in the rail.
- At-machine confirmation of C1-17DD/18JJ/26BB/27FF presence and current path on Dylan's chassis.
- At-machine gripper/TAC/C2A cavity mapping.
- Lamp supply/current and whether Rev-B should populate lamp outputs at all.
