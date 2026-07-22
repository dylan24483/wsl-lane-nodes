WSL Phase 8b rev-D as-ordered fab package
Generated: 2026-07-21T17:15:36
Board: kicad/revD/wsl-phase8b-revD.kicad_pcb
Netlist: kicad/wsl-phase8b-revD.net

Release gates re-proven by this export run:
- kicad-cli DRC: 0 violations / 0 unconnected / 0 footprint errors
  (live remediation .kicad_dru: 2.65 / 3.35 / 1.6 mm - spec R2.3).
- audit_revD_board.py routed mode: ALL PASS (Safety_Rail == 13).
- BOM<->CPL<->netlist equality asserted: 262 parts / 27 DNP / 235 placed /
  218 JLC-placed / 17 hand-solder; every placed refdes present in all three.
- D_PROT hard lock: D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3); no SS14
  anywhere.

Uploads:
- wsl-phase8b-revD-gerber-drill.zip  -> JLC PCB order (4-layer FR-4 1.6mm, 1oz/0.5oz,
  ENIG, confirm preview reads 250 x 240 mm - REV-D IS 240 mm TALL).
- assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv + -cpl.csv -> Standard PCBA.
- 10M 0805 line: LCSC number is MATCH-AT-UPLOAD by MPN 0805W8F1005T5E - record
  the matched C-number in the order notes (see part-lock CSV).

Hand-solder after JLC: A1, J1-J11, J13, J14, J15, J16, U45.
  U45 is the TMA-0505S (rev-C called it U37 - 46 refdes shifted; use
  docs/phase8_revD_first_article_pack.md, never rev-C bench notes).

Harness order (ship WITH the boards - gate G13/OG-3):
- assembly/wsl-phase8b-revD-harness-bom.csv (tracked copy: docs/phase8_revD_harness_bom.csv).
- Termination per Phoenix MC 1,5 data: 7 mm strip, 0.22-0.25 Nm, max 0.5 mm2
  with insulated ferrule (the old 8 mm / 0.5 Nm / 0.75-1.0 mm2 figures were
  wrong - corrected 2026-07-21).
- CP-MSTB 1734634 coding profiles fit the PLUG, never a standard header;
  sacrificial-pair proof before coding production parts (first-article FA-8).

Manual inspection gate G12 before paying:
- K1-K7 pad-net map (coil 2/5, COM 1, NO 3, NC 4 unused).
- The 8 new AUX4-11 opto channels + J15/J16 pads (1.4 mm drills - FR-9).
- Five doubled power vias (RD-VIA-1 twins) visible in the drill map.
- 'KEYED: NOT ...' silk legible at J3/J15/J13/J16 (1.2 mm / 0.20 mm stroke).
- USB keep-out clear; row-39 bottom-edge copper acknowledged (1.28 mm to edge).

This package is fab-geometry evidence only. Fab ORDER remains gated on G7/G8/
G13/G14 + first article per docs/phase8_revD_readiness_checklist.md.
