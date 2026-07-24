WSL Phase 8b rev-D as-ordered fab package
Generated: 2026-07-23T14:05:53
Board: kicad/revD/wsl-phase8b-revD.kicad_pcb
Netlist: kicad/wsl-phase8b-revD.net

Release gates re-proven by this export run:
- kicad-cli DRC: 0 violations / 0 unconnected / 0 footprint errors
  (live remediation .kicad_dru: 2.65 / 3.35 / 1.6 mm - spec R2.3).
- audit_revD_board.py routed mode: ALL PASS (Safety_Rail == 13).
- BOM<->CPL<->netlist equality asserted: 271 parts / 28 DNP / 243 placed /
  226 JLC-placed / 17 hand-solder; every placed refdes present in all three.
- D_PROT hard lock: D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3); no SS14
  anywhere.
- Round-2 locks (2026-07-21): Q17-Q20 = onsemi 2N7002LT1G C16338 (R2-3);
  R135/R138/R141 = UNI-ROYAL 10M C26108 (R2-15, identity pinned - verify
  stock at order, OOS at LCSC retail 2026-07-21); U46 = TCA4307DGKR C880333;
  U47 = Semtech SRV05-4.TCT C13612; F1 = Littelfuse 1206L020YR C207035.
  JP1 (J16 3.3V solder link) is DNP: default-OPEN, no part fitted.
- Rev-D input-margin hardening (2026-07-23): exactly R4,R6,...,R82 = 47k,
  UNI-ROYAL 0805W8F4702T5E / LCSC C17713; unrelated 10k networks unchanged.
  Every populated PC817 channel still requires FA-9 at loaded-min FIELD_WET
  and temperature: C5692981 lacks a guaranteed CTR minimum at ~1.7mA IF.
  BINDING CONFIGURATION GATE: production RP2040 GP6-GP13 internal pulls must
  be disabled (PUE=0, PDE=0), and U1/U2 MCP23017 GPPUA/GPPUB must command
  and read back 0x00. An enabled internal pull invalidates the 47k-only
  sink/leakage/RC arithmetic and is STOP-SHIP. R_TAPPU_* 10k diagnostic-tap
  drain pull-ups are separate networks and remain intentionally unchanged.
  Production firmware identity: phase8b-rp2040 v1.2.3;
  build=rel-0c746b5747143b8011b01d43; cfg=05d808411db4bb0d;
  release UF2 SHA-256=d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae. Verify the release manifest
  SHA-256=5bcbd2df1980acdd365865fc6527c96a3d0c1f51210a9d4a5fdd1f6cfcc279fd before flash; filename/version alone
  is not proof. FA-9/FA-11 require live pull-register confirmation.

Uploads:
- wsl-phase8b-revD-gerber-drill.zip  -> JLC PCB order (4-layer FR-4 1.6mm, 1oz/0.5oz,
  ENIG, confirm preview reads 250 x 240 mm - REV-D IS 240 mm TALL).
- assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv + -cpl.csv -> Standard PCBA.

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
- 'KEYED: NOT ...' silk legible at J3/J15/J13/J16 (1.2 mm / 0.20 mm stroke;
  'KEYED: NOT J13 LAMP' moved below the R2-4 cluster at (136, 226.5)).
- Round-2 additions: J16 protection cluster (F1/U46/U47/JP1/C16/R142/R143)
  south of J16; REV_ID straps R144/R145 east of the Pico; TP17-24 tap
  probe pads + TP silk legend + TP2/TP5 DO-NOT-BRIDGE marks.
- USB keep-out clear; row-39 bottom-edge copper acknowledged (1.28 mm to edge).

This package is fab-geometry evidence only. Fab ORDER remains gated on G7/G8/
G13/G14 + first article per docs/phase8_revD_readiness_checklist.md.
