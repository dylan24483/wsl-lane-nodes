WSL Phase 8b rev-D as-ordered fab package
Generated: 2026-07-26T13:40:32
Board: kicad/revD/wsl-phase8b-revD.kicad_pcb
Netlist: kicad/wsl-phase8b-revD.net

Release gates re-proven by this export run:
- kicad-cli DRC: 0 violations / 0 unconnected / 0 footprint errors
  (live remediation .kicad_dru: 2.65 / 3.35 / 1.6 mm - spec R2.3).
- audit_revD_board.py routed mode: ALL PASS (Safety_Rail == 13).
- BOM<->CPL<->netlist equality asserted: 391 parts / 68 DNP / 323 placed /
  314 JLC-placed / 9 hand-solder; every placed refdes present in all three.
- D_PROT hard lock: D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3); no SS14
  anywhere.
- r6 input protection asserted PER CHANNEL, not by totals: 40 x Dser_*
  + 40 x Dclamp_* (1N4148WS SOD-323, LCSC C118873, onsemi -
  ALL 88 1N4148 on ONE line, zero new assembled part classes)
  and 40 x Cflt_* (ALL DNP: 8 x 10nF fast /
  32 x 2.2uF slow). Each channel's FIELD_RIN_<n> = Rin.2 +
  Dser ANODE, FIELD_LED_<n> = Dser.K + Dclamp.K + PC817 anode, field pin = Dclamp
  ANODE + PC817 cathode. A DNP Dser is STOP-SHIP (open channel); a DNP/absent
  Dclamp is invisible until FA-15. No r6 part touches FIELD_WET_V, RELAY_ENABLE_
  RAIL, RAIL_GATE, SAFE_STOP_RETURN or SAFE_TBSC_RETURN.
- FIELD-STUFF locks (parts WE buy and fit, never JLC): Cflt 2.2uF = Samsung
  CL21B225KAFNNNE / LCSC C19110 (FR-17; 1uF C28323 REJECTED - 749 nF effective
  < the 951 nF 60 Hz floor); Cflt 10nF = TORCH C0805B103K500NT / LCSC C17702767
  (FR-18). Identities travel in assembly/*-dnp-excluded.csv next to the reason.
- Per-channel stuffing table: assembly/wsl-phase8b-revD-r6-channel-stuffing.csv (tracked
  copy docs/phase8_revD_r6_channel_stuffing.csv). ALL 40 channels get Dser +
  Dclamp POPULATED - uniform, no per-channel decision. The ONLY decision is the
  DNP Cflt, and it is MEASURE-THEN-STUFF: PBZ (33 VDC), DIELL_L/R (15.4-16 V)
  are metered DC and stay UNFITTED; SA/SB/SC/TA1/TA2/TB (cams), FOUL, GP, PBC,
  OS and the manual/AUX channels are UNMEASURED and carry the deciding
  measurement in their row. A 24 VAC FAST channel is never a cap fix.
- Round-2 locks (2026-07-21): Q17-Q20 = onsemi 2N7002LT1G C16338 (R2-3);
  R135/R138/R141 = FOJAN 10M FRC0805F1005TS C2933281 (R2-15 identity lock,
  RE-PINNED at r8 2026-07-26: the former UNI-ROYAL 0805W8F1005T5E / C26108
  went permanently OOS); U46 = TCA4307DGKR C880333;
  U47 = Semtech SRV05-4.TCT C13612; F1 = Littelfuse 1206L020YR C207035.
  JP1 (J16 3.3V solder link) is DNP: default-OPEN, no part fitted.
- Rev-D input-margin hardening (2026-07-23): exactly R4,R6,...,R82 = 47k,
  UNI-ROYAL 0805W8F4702T5E / LCSC C17713; unrelated 10k networks unchanged.
  Every populated PC817 channel still requires FA-9 at loaded-min FIELD_WET
  and temperature: C5692981 lacks a guaranteed CTR minimum at this board's
  operating IF. r6 (2026-07-25) INSERTED A SERIES BLOCKING DIODE in every
  channel, so the FA-9 operating point is NO LONGER ~1.7mA: it is 1.34mA at
  Vw=5.0V and ~1.12mA at the FA-9 step-3 loaded minimum (TP4 ~4.5V). Use
  those numbers, not the pre-r6 1.7mA. FA-9's <=100us edge criterion applies
  only with every Cflt_* UNFITTED (they ship DNP); a channel that later takes
  a Cflt is re-qualified against the debounce budget instead - see FA-9 and
  the DNP CSV reason text.
  BINDING CONFIGURATION GATE: production RP2040 GP6-GP13 internal pulls must
  be disabled (PUE=0, PDE=0), and U1/U2 MCP23017 GPPUA/GPPUB must command
  and read back 0x00. An enabled internal pull invalidates the 47k-only
  sink/leakage/RC arithmetic and is STOP-SHIP. R_TAPPU_* 10k diagnostic-tap
  drain pull-ups are separate networks and remain intentionally unchanged.
  Production firmware identity: phase8b-rp2040 v1.2.3;
  build=rel-0c746b5747143b8011b01d43; cfg=05d808411db4bb0d;
  release UF2 SHA-256=d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae. Verify the release manifest
  SHA-256=ea8ea4ceb273df98e888aeb5d1f1327d39577e8492fda455c932fea3768bd7b5 before flash; filename/version alone
  is not proof. The manifest must contain supported_board_revisions=["revD"].
  Provision only qualified_releases=["revD|rel-0c746b5747143b8011b01d43|05d808411db4bb0d"];
  independent build/config allowlists must not authorize a cross-product.
  This exact bundle is Rev-D only: never flash Rev-B/Rev-C, and never deploy
  wsl_phase8b_rp2040_FI1.uf2. FA-9/FA-11 require live pull-register confirmation.

Uploads:
- wsl-phase8b-revD-gerber-drill.zip  -> JLC PCB order (4-layer FR-4 1.6mm, 1oz/0.5oz,
  ENIG, confirm preview reads 250 x 240 mm - REV-D IS 240 mm TALL).
- assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv + -cpl.csv -> Standard PCBA.

Hand-solder after JLC (9 refdes - r9 WAVE 1 reduced this from 17):
  A1, J1, J3, J4, J5, J13, J15, J16, U45.
  U45 is the TMA-0505S (rev-C called it U37 - 46 refdes shifted; use
  docs/phase8_revD_first_article_pack.md, never rev-C bench notes).
  J1 stays hand because its identity is CANDIDATE (CNC Tech 3020-20-0100-00,
  body/keying never verified against the KiCad footprint) - not for any
  process reason. A1/U45 and the six MCV headers await part sourcing.

r9 WAVE 1: J2, J6-J11 and J14 are now JLC-PLACED (8 placements/board, 19 THT
  joints/board, 646 fleet-wide). All three are library-native Phoenix Contact,
  marked Wave Soldering / Economic and Standard - the SAME through-hole path
  this board already uses for its 40 PC817 optos and 6 G5LE relays. No service
  tier changes: JLC offers only Economic and Standard, and this order is already
  Standard. Verified 2026-07-26 by JLC part-detail page, not by MPN search
  (searching JLC by bare numeric Phoenix MPN returns FALSE NEGATIVES - e.g.
  searchTxt=1843622 gives '0 Found' while partdetail/C480549 shows it in stock):
    J2      = C480520  Phoenix 1715734  MKDS 1,5/3-5,08   1,173 stock
    J6-J11  = C480516  Phoenix 1715721  MKDS 1,5/2-5,08   1,591 stock
              (NOT C5183929 - same MPN, only ~239 pcs vs a 204 fleet need)
    J14     = C480549  Phoenix 1843622  MCV 1,5/4-G-3,5   2,481 stock
  J14 is NOT one of the FA-8 coded pairs, so no coding rib is cut on it and
  JLC placing it cannot disturb the J3/J15 + J13/J16 keying scheme.

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
