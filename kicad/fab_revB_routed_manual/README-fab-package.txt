WSL Phase 8b Rev-B routed-manual fab package
Generated: 2026-06-26T17:31:57
Board: kicad/wsl-phase8b.routed-manual.kicad_pcb

Bare PCB gate:
- KiCad DRC: 0 DRC violations, 0 unconnected pads, 0 footprint errors.
- Rev-B topology audit: ALL PASS.
- Custom .kicad_dru rules are active via the routed .kicad_pro netclass map.

Use for bare PCB fabrication:
- kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip

Assembly support:
- assembly/wsl-phase8b-revB-bom-non-dnp.csv is grouped by value/footprint.
- assembly/wsl-phase8b-revB-cpl.csv is KiCad position output, DNP excluded.
- assembly/wsl-phase8b-revB-pcba-working-bom.csv groups rows into
  purchasable sourcing lines with assembly/source buckets.
- assembly/wsl-phase8b-revB-pcba-placement-buckets.csv preserves each
  KiCad BOM row with the same source-bucket classification.
- assembly/wsl-phase8b-revB-offboard-hardware.csv lists mating plugs and
  hardware that are not placed on the PCB.
- assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv and
  assembly/wsl-phase8b-revB-jlc-standard-pcba-cpl.csv are the
  filtered JLCPCB Standard-PCBA upload pair: JLC places SMT, PC817,
  and G5LE; A1/connectors/U37 are hand-soldered.
- assembly/wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv is
  the clean upload BOM with only JLC order-driving columns.
- assembly/wsl-phase8b-revB-hand-solder-bom.csv and
  assembly/wsl-phase8b-revB-harness-mating-parts.csv list the
  post-JLC board install and harness/mating connector purchases.
- kicad/fab_revB_routed_manual/wsl-phase8b-revB-jlc-standard-pcba-upload.zip contains the Gerber zip plus the clean
  JLC Standard-PCBA upload BOM/CPL.
- The raw grouped BOM intentionally keeps LCSC/manufacturer fields blank.
- The JLC Standard-PCBA upload BOM has locked LCSC numbers, but still
  requires final JLC part-match, polarity, and orientation approval.
- kicad/fab_revB_routed_manual/JLC_UPLOAD_READY contains short, upload-order filenames
  for the Gerber zip, clean JLC BOM, clean JLC CPL, and audit files.
- kicad/fab_revB_routed_manual/wsl-phase8b-revB-JLC_UPLOAD_READY.zip is a transport zip of that upload-ready
  folder. Use the files inside it in the JLC flow; do not upload the
  transport zip itself as the PCB Gerber file.

Safety caveat:
- This package is PCB-fab-ready under the current conservative DRC contract.
- It is not controller cutover-ready; RP2040 v1.1 cam-stop overrun and
  on-hardware bench bring-up remain required before live machine use.
