# Phase 8b Rev-B Fab Order Checklist

> ⛔ **HISTORICAL — REV-B/C ONLY. DO NOT ORDER FROM THIS DOCUMENT.**
> Despite its name, this is **not** the current fab order checklist. It points at
> `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/`, which builds a **rev-C** board:
> 250 × 225 mm, no AUX4–11 bank, no J15/J16, 10 kΩ pull-ups, and **no r6 per-channel
> input protection** — landing PBZ (33 VDC) or DIELL_L/R (15.4–16 V) on it puts those
> rails across a 6 V-rated PC817 LED.
>
> **Current package:** `kicad/fab_revD_2026-07-25_r7/`
> **Current gate checklist:** `docs/phase8_revD_readiness_checklist.md`
>
> *Banner added 2026-07-25 per pre-order audit finding S3
> (`docs/phase8_revD_PREORDER_FINAL_AUDIT_2026-07-25.md`).*

Use this with the generated Rev-B package. This checklist is intentionally
order-facing: it maps the board artifacts to the JLCPCB order flow and flags
the preview checks that must happen before payment.

## Files To Use

Primary JLC upload folder:

- `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/`

Use these files from that folder in order:

- Gerbers/drill: `01_wsl-phase8b-revB_gerbers.zip`
- Clean JLC BOM: `02_wsl-phase8b-revB_BOM_JLC.csv`
- JLC CPL: `03_wsl-phase8b-revB_CPL_JLC.csv`

Transport zip for moving the upload folder as one file:

- `kicad/fab_revB_routed_manual/wsl-phase8b-revB-JLC_UPLOAD_READY.zip`

Do not upload the transport zip itself as the PCB Gerber file; unzip it and use
the three order files above.

Audit/support files:

- Full package: `kicad/fab_revB_routed_manual/wsl-phase8b-revB-fab-package.zip`
- Legacy combined upload bundle: `kicad/fab_revB_routed_manual/wsl-phase8b-revB-jlc-standard-pcba-upload.zip`
- Part lock: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv`
- JLC excluded refs: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-excluded.csv`
- Hand-solder BOM: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-hand-solder-bom.csv`
- Harness/mating parts: `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-harness-mating-parts.csv`

## PCB Settings

Set or confirm these in the JLC order form:

- Layers: 4.
- Dimensions: 250 mm x 225 mm.
- Thickness: 1.6 mm.
- Material: FR-4.
- Solder mask: green.
- Silkscreen: white.
- Surface finish: ENIG.
- Outer copper: 1 oz.
- Inner copper: 0.5 oz.
- Via process: standard through vias only.
- Castellated holes: no.
- Impedance control: no.
- Edge plating: no.
- Panelization: no unless JLC requires it for assembly handling.

## PCBA Settings

- Assembly side: top side only.
- Assembly service: Standard PCBA.
- Assembly contents: SMT + wave-solder THT for PC817 and G5LE.
- JLC-placed refs: 174.
- JLC BOM lines: 20.
- Filtered CPL rows: 174.
- Hand-solder refs excluded from JLC placement: A1, J1-J11, J13, J14, U37.
- Existing DNP refs remain excluded, including J12/K7/M1-channel population.

## Mandatory Preview Checks

Do not pay until these are checked in the JLC preview:

- Relay row is `C116963 / G5LE-14 5VDC`; reject any 9V, 12V, or 24V relay coil substitution.
- I/O expander row is `C47023 / MCP23017-E/SO`; reject MCP23S17.
- PC817 row is `C5692981 / PC817B`, DIP-4 / through-hole / wave solder.
- NE555 row is `C7593 / NE555DR`.
- C11 electrolytic polarity matches the board.
- All PC817 orientations match the board preview.
- All G5LE relay orientations match the board preview.
- No A1, J1-J11, J13, J14, or U37 refs appear in the JLC placement list.
- J12, K7, Q7, and the M1 support passives remain unpopulated.
- Board outline remains 250 mm x 225 mm with four mounting holes visible.

## If JLC Rejects A Part

No board redesign is needed for these fallbacks:

- If PC817 is rejected for wave solder, remove U4-U35 from JLC placement and add 32x PC817 to the hand-solder BOM.
- If G5LE is rejected for wave solder, remove K1-K6 from JLC placement and add 6x G5LE-14 5VDC to the hand-solder BOM.
- If C11 part fit/polarity is questionable, pick another 100uF/16V SMD electrolytic that matches the 6.3x5.4 footprint and re-run the BOM generator after updating the lock.

## Post-JLC Bench Install

Install these after the assembled boards arrive:

- A1 Raspberry Pi Pico, SC0915.
- J1 IDC/header candidate after keying/body check.
- J2-J11, J13, J14 Phoenix connectors.
- U37 TRACO TMA 0505S.
- Mating plugs for J3, J4, J5, J13, J14.

Then run continuity/visual inspection before applying power.

## Last Gate Before Order

The current generated package has passed:

- KiCad DRC: 0 DRC violations, 0 unconnected pads, 0 footprint errors.
- Rev-B topology audit: ALL PASS.
- JLC Standard-PCBA generator guardrails: 174 placed refs, 20 unique part lines, 15 hand-solder exclusions.
