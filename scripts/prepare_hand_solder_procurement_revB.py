#!/usr/bin/env python3
"""Generate hand-solder procurement lists for Phase 8b Rev-B."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / "kicad" / "fab_revB_routed_manual" / "assembly"
OUT_HAND = ASM / "wsl-phase8b-revB-hand-solder-bom.csv"
OUT_HARNESS = ASM / "wsl-phase8b-revB-harness-mating-parts.csv"


HAND_SOLDER_ROWS = [
    {
        "Ref": "A1",
        "Qty": 1,
        "Role": "RP2040 module",
        "Manufacturer": "Raspberry Pi",
        "MFR Part #": "SC0915",
        "Description": "Raspberry Pi Pico, castellated module, no pre-soldered headers",
        "Source": "DigiKey 2648-SC0915CT-ND or official Raspberry Pi reseller",
        "Status": "Locked",
        "Notes": "Program after assembly; do not use Pico H/WH with header pins.",
        "URL": "https://www.digikey.com/en/products/detail/raspberry-pi/SC0915/13684020",
    },
    {
        "Ref": "J1",
        "Qty": 1,
        "Role": "Pi IDC/header",
        "Manufacturer": "CNC Tech candidate",
        "MFR Part #": "3020-20-0100-00",
        "Description": "20-position 2x10 2.54mm vertical through-hole box/IDC header candidate",
        "Source": "DigiKey 1175-1612-ND candidate",
        "Status": "Candidate - verify body/keying",
        "Notes": "Verify shroud, key slot, pin-1 orientation, and body keepout against KiCad footprint/render before ordering.",
        "URL": "https://www.digikey.com/en/products/detail/cnc-tech/3020-20-0100-00/3441738",
    },
    {
        "Ref": "J2",
        "Qty": 1,
        "Role": "5V power terminal",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1715734",
        "Description": "MKDS 1,5/ 3-5,08, 3-position fixed screw terminal block, 5.08mm pitch",
        "Source": "Phoenix / Newark / DigiKey / Mouser equivalent",
        "Status": "Locked - footprint verify at order",
        "Notes": "Fixed screw terminal; no off-board plug. Verify wire-entry direction.",
        "URL": "https://www.phoenixcontact.com/us/products/1715734/pdf",
    },
    {
        "Ref": "J3",
        "Qty": 1,
        "Role": "FAST field input header",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1843680",
        "Description": "MCV 1,5/10-G-3,5, 10-position vertical PCB header, 3.5mm pitch",
        "Source": "Phoenix Contact",
        "Status": "Locked",
        "Notes": "Order matching MC 1,5/10-ST-3,5 plug separately.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-header-mcv-1510-g-35-1843680",
    },
    {
        "Ref": "J4",
        "Qty": 1,
        "Role": "SLOW A field input header",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1843729",
        "Description": "MCV 1,5/14-G-3,5, 14-position vertical PCB header, 3.5mm pitch",
        "Source": "Phoenix Contact",
        "Status": "Locked",
        "Notes": "Order matching MC 1,5/14-ST-3,5 plug separately.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-header-mcv-1514-g-35-1843729",
    },
    {
        "Ref": "J5",
        "Qty": 1,
        "Role": "SLOW B field input header",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1843703",
        "Description": "MCV 1,5/12-G-3,5, 12-position vertical PCB header, 3.5mm pitch",
        "Source": "Phoenix Contact",
        "Status": "Locked",
        "Notes": "Order matching MC 1,5/12-ST-3,5 plug separately.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-header-mcv-1512-g-35-1843703",
    },
    {
        "Ref": "J6,J7,J8,J9,J10,J11",
        "Qty": 6,
        "Role": "Machine output terminals",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1715721",
        "Description": "MKDS 1,5/ 2-5,08, 2-position fixed screw terminal block, 5.08mm pitch",
        "Source": "Phoenix / LCSC C5183929 / DigiKey / Mouser equivalent",
        "Status": "Locked - footprint verify at order",
        "Notes": "Fixed screw terminal; no off-board plug. Verify wire-entry direction.",
        "URL": "https://www.phoenixcontact.com/en-us/products/printed-circuit-board-terminal-mkds-15-2-508-1715721?type=pdf",
    },
    {
        "Ref": "J13",
        "Qty": 1,
        "Role": "LED lamp header",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1843648",
        "Description": "MCV 1,5/ 6-G-3,5, 6-position vertical PCB header, 3.5mm pitch",
        "Source": "Phoenix Contact",
        "Status": "Locked",
        "Notes": "Order matching MC 1,5/ 6-ST-3,5 plug separately.",
        "URL": "https://www.phoenixcontact.com/en-pc/products/printed-circuit-board-connector-mcv-15-6-g-35-1843648",
    },
    {
        "Ref": "J14",
        "Qty": 1,
        "Role": "Safety loop header",
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1843622",
        "Description": "MCV 1,5/ 4-G-3,5, 4-position vertical PCB header, 3.5mm pitch",
        "Source": "Phoenix Contact",
        "Status": "Locked",
        "Notes": "Order matching MC 1,5/ 4-ST-3,5 plug separately.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-header-mcv-15-4-g-35-1843622",
    },
    {
        "Ref": "U37",
        "Qty": 1,
        "Role": "Isolated field supply",
        "Manufacturer": "TRACO Power",
        "MFR Part #": "TMA 0505S",
        "Description": "Isolated 5V-to-5V 1W SIP DC/DC converter, 5V 200mA output",
        "Source": "DigiKey 1951-1003-ND / TME / Mouser equivalent",
        "Status": "Locked exact part",
        "Notes": "Do not substitute without pinout and isolation review.",
        "URL": "https://www.digikey.com/en/products/detail/traco-power/TMA-0505S/9324924",
    },
]


HARNESS_ROWS = [
    {
        "Mate For": "J3",
        "Qty": 1,
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1840447",
        "Description": "MC 1,5/10-ST-3,5, 10-position 3.5mm screw plug",
        "Status": "Locked",
        "Notes": "Mates J3 MCV 1,5/10-G-3,5.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-plug-mc-1510-st-35-1840447?type=pdf",
    },
    {
        "Mate For": "J4",
        "Qty": 1,
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1840489",
        "Description": "MC 1,5/14-ST-3,5, 14-position 3.5mm screw plug",
        "Status": "Locked",
        "Notes": "Mates J4 MCV 1,5/14-G-3,5.",
        "URL": "https://www.phoenixcontact.com/en-pc/products/printed-circuit-board-connector-mc-15-14-st-35-1840489",
    },
    {
        "Mate For": "J5",
        "Qty": 1,
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1840463",
        "Description": "MC 1,5/12-ST-3,5, 12-position 3.5mm screw plug",
        "Status": "Locked",
        "Notes": "Mates J5 MCV 1,5/12-G-3,5.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-plug-mc-1512-st-35-1840463",
    },
    {
        "Mate For": "J13",
        "Qty": 1,
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1840405",
        "Description": "MC 1,5/ 6-ST-3,5, 6-position 3.5mm screw plug",
        "Status": "Locked",
        "Notes": "Mates J13 MCV 1,5/ 6-G-3,5.",
        "URL": "https://www.phoenixcontact.com/en-pc/products/printed-circuit-board-connector-mc-15-6-st-35-1840405",
    },
    {
        "Mate For": "J14",
        "Qty": 1,
        "Manufacturer": "Phoenix Contact",
        "MFR Part #": "1840382",
        "Description": "MC 1,5/ 4-ST-3,5, 4-position 3.5mm screw plug",
        "Status": "Locked",
        "Notes": "Mates J14 MCV 1,5/ 4-G-3,5.",
        "URL": "https://www.phoenixcontact.com/en-us/products/pcb-plug-mc-15-4-st-35-1840382",
    },
    {
        "Mate For": "J1",
        "Qty": 1,
        "Manufacturer": "CNC Tech candidate",
        "MFR Part #": "3030-20-0102-00",
        "Description": "20-position IDC socket candidate for 2x10 2.54mm ribbon harness",
        "Status": "Candidate - verify with J1",
        "Notes": "Verify keying, strain relief, cable gauge, and pin-1 convention.",
        "URL": "https://www.digikey.com/en/products/detail/cnc-tech/3030-20-0102-00/3821471",
    },
]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    write_csv(OUT_HAND, HAND_SOLDER_ROWS)
    write_csv(OUT_HARNESS, HARNESS_ROWS)
    print(f"Hand-solder board refs: {sum(int(row['Qty']) for row in HAND_SOLDER_ROWS)}")
    print(f"Harness/mating parts: {sum(int(row['Qty']) for row in HARNESS_ROWS)}")
    print(f"Wrote {OUT_HAND}")
    print(f"Wrote {OUT_HARNESS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
