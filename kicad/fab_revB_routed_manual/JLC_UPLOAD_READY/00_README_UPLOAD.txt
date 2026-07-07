WSL Phase 8b Rev-B JLCPCB upload packet
Generated: 2026-06-26T17:31:57

Upload order:
1. Upload 01_wsl-phase8b-revB_gerbers.zip as the PCB Gerber/drill file.
2. In the JLCPCB assembly step, choose Standard PCBA.
3. Upload 02_wsl-phase8b-revB_BOM_JLC.csv as the BOM.
4. Upload 03_wsl-phase8b-revB_CPL_JLC.csv as the position/CPL file.
5. Use 04_wsl-phase8b-revB_part-lock-audit.csv during part-match review.

Do not upload these as JLC order files:
- 05_wsl-phase8b-revB_excluded-hand-solder.csv is an exclusion audit.
- 06_wsl-phase8b-revB_hand-solder-bom.csv is the post-JLC board install list.
- 07_wsl-phase8b-revB_harness-mating-parts.csv is the harness/mating plug list.

PCB order settings:
- 4 layers, FR-4, 1.6 mm thickness.
- 1 oz outer copper, 0.5 oz inner copper.
- Green solder mask, white silkscreen.
- ENIG surface finish.
- Confirm JLC preview dimensions are 250 mm x 225 mm.

JLC placement contract:
- JLC BOM unique lines: 20.
- JLC CPL placed designators: 174.
- JLC places SMT plus PC817 optos and six G5LE relays.
- Hand solder after JLC: A1, J1-J11, J13, J14, U37.
- Existing DNP/excluded refs remain unplaced.

Critical part-match checks:
- K1-K6: C116963, Omron G5LE-14 5VDC. The relay coil must be 5 VDC.
- U1-U3: C47023, MCP23017-E/SO. This must be I2C MCP23017, not SPI MCP23S17.
- U4-U35: C5692981, PC817B DIP-4.
- U36: C7593, NE555DR SOIC-8.

Mandatory preview checks before ordering:
- Pin 1/orientation markers for U1-U3 and U36 match the KiCad board.
- Diode cathode stripes for D1-D7/D9-D15/D17-D30 and polarity for C5/C6 are correct.
- Relay bodies sit in the machine-contact band and do not rotate.
- PC817 optos stay vertical in the field/logic barrier row.
- A1, J1-J11, J13, J14, U37 are not placed by JLC.
- If JLC rejects PC817 or G5LE through-hole assembly, move those refs to
  hand-solder/DNP in the order UI. No PCB redesign is required.

Verification gates from this export:
- KiCad DRC: 0 violations, 0 unconnected pads, 0 footprint errors.
- Rev-B topology audit: ALL PASS.
