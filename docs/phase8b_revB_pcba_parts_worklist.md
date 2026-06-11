# Phase 8b Rev-B PCBA Parts Worklist

This is the sourcing/assembly handoff for the routed Rev-B board. The selected
primary path is JLCPCB Standard PCBA:

- JLC places all SMD, 32 PC817 optos, and 6 G5LE relays.
- Hand solder A1, all board connectors, and U37.
- Existing DNP/excluded refs remain out of the placement list.

## Current Outputs

Fab package:

- `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip`
- `kicad/fab_revB_routed_manual/wsl-phase8b-revB-fab-package.zip`

Assembly upload files:

- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-bom-non-dnp.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-cpl.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-cpl.csv`

Assembly worklists:

- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-pcba-working-bom.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-pcba-placement-buckets.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-offboard-hardware.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-excluded.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-hand-solder-bom.csv`
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-harness-mating-parts.csv`

Order checklist:

- `docs/phase8b_revB_fab_order_checklist.md`

Regenerate with:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\export_fab_revB.py
```

The export script regenerates the general PCBA worklists, the filtered JLC
Standard-PCBA upload files, and includes all of them in the full fab package
zip.

## Counts

- Raw non-DNP KiCad BOM: 84 rows, 189 placed references.
- Grouped purchase list: 30 sourcing lines.
- JLC Standard-PCBA upload: 20 part lines, 174 placed references.
- Clean JLC upload BOM: 20 part lines, only `Comment`, `Designator`,
  `Footprint`, `Quantity`, and `LCSC Part #`.
- JLC Standard-PCBA CPL: 174 rows.
- Hand-solder refs excluded from JLC BOM/CPL: 15.
- Hand-solder procurement BOM: 15 board refs.
- Harness/mating procurement list: 6 mating/accessory refs.
- JLC placement class split: 108 Basic placements, 66 Extended placements.
- DNP references: 27.
- Excluded non-DNP references: 20 test pads / mounting holes.
- Assembly buckets:
  - SMT candidate: 132 placements.
  - SMT stock/footprint verify: 4 placements.
  - THT assembly / verify: 51 placements.
  - THT consign likely: 1 placement.
  - Consign / assembly-house verify: 1 placement.

## JLC Standard-PCBA Upload Pair

Use these two files for the JLC assembly upload:

- `assembly/wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv`
- `assembly/wsl-phase8b-revB-jlc-standard-pcba-cpl.csv`

Do not use the raw `bom-non-dnp.csv` as the final JLC upload without filtering;
it includes hand-soldered refs A1, J1-J11, J13, J14, and U37.

The richer `assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv` and
`assembly/wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv` are for audit,
not the clean upload.

The generator is `scripts/prepare_jlc_standard_pcba_revB.py`. It aborts unless
the JLC ref count is 174, the unique part count is 20, the filtered CPL count is
174, the relay is locked to `C116963 / G5LE-14 5VDC`, and the I/O expander is
locked to `C47023 / MCP23017-E/SO`.

## Hand-Soldered Parts

These refs stay on the board but are omitted from the JLC placement BOM/CPL:

- A1: Raspberry Pi Pico module.
- J1: Pi IDC/header.
- J2-J11, J13, J14: Phoenix/terminal connectors.
- U37: TRACO TMA-0505S isolated DC/DC.

J12 is already DNP and is not part of this hand-solder set.

Use these procurement files:

- `assembly/wsl-phase8b-revB-hand-solder-bom.csv`
- `assembly/wsl-phase8b-revB-harness-mating-parts.csv`

Most board-side Phoenix parts are locked. J1 and its IDC socket are candidates
pending final body/keying/pin-1 verification against the board and cable plan.

## Locked JLC Part Map

| Board part | Qty | LCSC/JLCPCB # | MFR part | Class | Notes |
| --- | ---: | --- | --- | --- | --- |
| 100nF 50V X7R 0805 | 4 | C49678 | CC0805KRX7R9BB104 | Basic | Decoupling |
| 100uF 16V SMD electrolytic | 1 | C19184134 | CK1C101M-CRE54 | Extended | Verify polarity preview |
| 10nF 50V X7R 0805 | 1 | C17702767 | C0805B103K500NT | Extended | Watchdog timing |
| 10uF 16V X5R 0805 | 1 | C89827 | CC0805KKX5R7BB106 | Extended | Verify DC-bias margin |
| 1N4148WS SOD-323 | 8 | C118873 | 1N4148WS | Extended | Coil/timing diodes |
| SS14 SMA | 1 | C2480 | SS14 | Basic | Input protection |
| G5LE 5V SPDT relay | 6 | C116963 | G5LE-14 5VDC | Extended | Critical: 5VDC coil |
| MMBT3904 SOT-23 | 8 | C909754 | MMBT3904 | Extended | NPN drivers/logic |
| 2N7002 SOT-23 | 4 | C916396 | 2N7002 | Extended | LED FETs |
| AO3400A SOT-23 | 2 | C20917 | AO3400A | Basic | N-channel watchdog/kick FETs |
| AO3401A SOT-23 | 1 | C347476 | AO3401A | Extended | P-channel rail pass FET |
| 4.7k 0805 resistor | 2 | C17673 | 0805W8F4701T5E | Basic | 1%, 1/8W |
| 2.2k 0805 resistor | 32 | C17520 | 0805W8F2201T5E | Basic | 1%, 1/8W |
| 10k 0805 resistor | 37 | C17414 | 0805W8F1002T5E | Basic | 1%, 1/8W |
| 1k 0805 resistor | 12 | C17513 | 0805W8F1001T5E | Basic | 1%, 1/8W |
| 100k 0805 resistor | 14 | C149504 | 0805W8F1003T5E | Basic | 1%, 1/8W |
| 330R 0805 resistor | 4 | C17630 | 0805W8F3300T5E | Basic | 1%, 1/8W |
| MCP23017 SOIC-28W | 3 | C47023 | MCP23017-E/SO | Extended | Critical: I2C, not MCP23S17 |
| PC817 DIP-4 | 32 | C5692981 | PC817B | Extended | Wave solder; verify orientation/CTR |
| NE555 SOIC-8 | 1 | C7593 | NE555DR | Extended | Bipolar 555 selected |

## Quote Path

Upload the Gerbers plus the filtered JLC BOM/CPL pair. In the JLC placement
preview, explicitly verify:

- PC817 orientation on U4-U35.
- Relay orientation and that the part is `G5LE-14 5VDC`.
- C11 electrolytic polarity.
- MCP23017 package/identity: `MCP23017-E/SO`, not MCP23S17.
- No A1/J*/U37 refs are present in the JLC placement list.

If JLC rejects PC817 or G5LE wave soldering during the order flow, fall back to
SMT-only JLC assembly and move those rejected THT lines to hand solder. The PCB
does not need a redesign for that fallback.

JLC's current PCBA pages list SMT and wave-solder assembly support on relevant
part pages; the C116963 relay page identifies `G5LE-14 5VDC`, wave soldering,
and Economic/Standard PCBA support, and the C5692981 PC817B page shows stock
and through-hole placement support.

References:

- https://jlcpcb.com/pcb-assembly
- https://jlcpcb.com/help/article/how-to-consign-parts-to-jlcpcb
- https://jlcpcb.com/help/catalog/191-PCBA-Parts-Sourcing

## Critical Selection Notes

PC817 optos:

- Keep the DIP-4 wide / 7.62mm isolation footprint.
- Verify CTR bin against the Rev-B field input resistor values before locking a
  supplier part. Do not silently replace with a narrow SOIC opto.

TMA-0505S isolated converter:

- Treat as exact or pinout-audited substitute only.
- Verify isolation rating, output current, SIP pinout, and body clearance before
  approving a global-sourced alternative.

G5LE relays:

- Use 5V coil SPDT matching the Omron G5LE-1 footprint.
- Verify coil voltage, contact rating, pinout, height, and wash/flux rules.

Raspberry Pi Pico:

- JLC has candidate Pico entries, but the assembler must confirm they can place
  the castellated module on this footprint.
- Assume the Pico arrives unprogrammed unless programming is explicitly quoted.

NE555:

- Prefer a bipolar 555/LM555/KA555-compatible SOIC-8 unless the watchdog timing
  is recalculated for CMOS/TLC555 behavior.

Connectors:

- Verify wire-entry direction against the board render before ordering.
- The 3.5mm MCV headers need matching off-board plugs; those plugs are not PCB
  placements and are listed separately in `offboard-hardware.csv`.

DNP:

- Keep the M1 channel and suppression-option parts unpopulated unless Rev-B is
  explicitly revised to release them.

## Next Sourcing Steps

1. Upload `wsl-phase8b-revB-jlc-standard-pcba-upload.zip` to JLC or upload the
   Gerber zip, clean JLC BOM, and JLC CPL manually.
2. Run BOM matching and placement preview.
3. Re-audit every substituted or rejected part before ordering.
4. Save the matched BOM export / screenshots from JLC back into the fab folder.
5. Order hand-solder and harness/mating parts in parallel.
