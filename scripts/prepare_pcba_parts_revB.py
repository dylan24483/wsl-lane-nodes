#!/usr/bin/env python3
"""Prepare Phase 8b Rev-B assembly sourcing worklists from the KiCad BOM.

The KiCad/JLC export BOM is intentionally conservative: it preserves the
schematic comment text, so channel-specific parts such as PC817 SA/PC817 SB
appear as separate BOM rows. This script folds those rows into purchasable part
families and adds sourcing buckets for PCBA quoting.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / "kicad" / "fab_revB_routed_manual" / "assembly"
IN_BOM = ASM / "wsl-phase8b-revB-bom-non-dnp.csv"
IN_DNP = ASM / "wsl-phase8b-revB-dnp-excluded.csv"
OUT_WORKING = ASM / "wsl-phase8b-revB-pcba-working-bom.csv"
OUT_BUCKETS = ASM / "wsl-phase8b-revB-pcba-placement-buckets.csv"
OUT_OFFBOARD = ASM / "wsl-phase8b-revB-offboard-hardware.csv"


def split_designators(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def prefix_number(ref: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in ref if not ch.isdigit())
    number = "".join(ch for ch in ref if ch.isdigit())
    return prefix, int(number or 0)


def sort_refs(refs: list[str]) -> list[str]:
    return sorted(refs, key=prefix_number)


def classify(comment: str, footprint: str) -> dict[str, str]:
    c = comment.upper()
    f = footprint.upper()

    def row(
        key: str,
        bucket: str,
        source: str,
        purchase_spec: str,
        candidate: str = "",
        notes: str = "",
        candidate_jlcpcb_part: str = "",
    ) -> dict[str, str]:
        return {
            "purchase_key": key,
            "bucket": bucket,
            "source_strategy": source,
            "purchase_spec": purchase_spec,
            "candidate_mpn": candidate,
            "candidate_jlcpcb_part": candidate_jlcpcb_part,
            "notes": notes,
        }

    if "RP2040 PICO" in c:
        return row(
            "RP2040 Pico module",
            "Consign / assembly-house verify",
            "Consign or separately source",
            "Raspberry Pi Pico module, SMD castellated footprint",
            "Raspberry Pi Pico",
            notes="Verify assembly house will place module; otherwise hand-solder after SMT/THT assembly.",
            candidate_jlcpcb_part="JLC candidate C7203002",
        )

    if "C_0805" in f:
        if "0.1UF" in c:
            return row("0.1uF 0805 MLCC", "SMT candidate", "JLC/LCSC stock", "0.1uF 0805 MLCC, X7R/X5R, 16V minimum")
        if "10NF" in c:
            return row("10nF 0805 MLCC", "SMT candidate", "JLC/LCSC stock", "10nF 0805 MLCC, X7R/C0G, 50V preferred")
        if "10UF" in c:
            return row("10uF 0805 MLCC", "SMT candidate", "JLC/LCSC stock", "10uF 0805 MLCC, X5R/X7R, 16V preferred", notes="Verify DC-bias derating is acceptable on 5V rail.")

    if "CP_ELEC" in f and "100UF" in c:
        return row(
            "100uF 16V SMD electrolytic",
            "SMT candidate - verify footprint",
            "JLC/LCSC stock or exact substitute",
            "100uF 16V SMD electrolytic, 6.3x5.4mm footprint",
            notes="Polarized part; verify can diameter and pad geometry against selected part.",
        )

    if "R_0805" in f:
        value = comment.strip()
        return row(
            f"{value} 0805 resistor",
            "SMT candidate",
            "JLC/LCSC stock",
            f"{value} 0805 resistor, 1%, 1/8W minimum",
        )

    if "1N4148" in c and "SOD-323" in f:
        return row("1N4148WS SOD-323", "SMT candidate", "JLC/LCSC stock", "1N4148WS or equivalent small-signal diode, SOD-323", candidate_jlcpcb_part="JLC candidate C118873")

    if "SS14" in c and "SMA" in f:
        return row("SS14 SMA", "SMT candidate", "JLC/LCSC stock", "SS14 Schottky diode, SMA", candidate_jlcpcb_part="JLC candidate C2480")

    if "MMBT3904" in c and "SOT-23" in f:
        return row("MMBT3904 SOT-23", "SMT candidate", "JLC/LCSC stock", "MMBT3904 NPN transistor, SOT-23", candidate_jlcpcb_part="JLC candidate C909754")

    if "2N7002" in c and "SOT-23" in f:
        return row("2N7002 SOT-23", "SMT candidate", "JLC/LCSC stock", "2N7002 N-channel MOSFET, SOT-23", candidate_jlcpcb_part="JLC candidate C916396")

    if "AO3400A" in c and "SOT-23" in f:
        return row("AO3400A SOT-23", "SMT candidate", "JLC/LCSC stock", "AO3400A or equivalent logic-level N-channel MOSFET, SOT-23", candidate_jlcpcb_part="JLC candidate C20917")

    if "AO3401A" in c and "SOT-23" in f:
        return row("AO3401A SOT-23", "SMT candidate", "JLC/LCSC stock", "AO3401A or equivalent P-channel MOSFET, SOT-23", candidate_jlcpcb_part="JLC candidate C347476")

    if "MCP23017" in c:
        return row(
            "MCP23017 SOIC-28W",
            "SMT candidate - stock verify",
            "JLC/LCSC stock or pre-order",
            "MCP23017 I/O expander, SOIC-28W 7.5mm body, 1.27mm pitch",
            "MCP23017-E/SO or MCP23017T-E/SO",
            notes="Confirm package width and I2C address variant; do not substitute SPI MCP23S17.",
            candidate_jlcpcb_part="JLC candidate C47023",
        )

    if c == "NE555" or c.startswith("NE555"):
        return row("NE555 SOIC-8", "SMT candidate", "JLC/LCSC stock", "NE555 timer, SOIC-8", "NE555D / TLC555-compatible only if timing verified", notes="No locked JLC part yet; select an in-stock bipolar 555 compatible with the watchdog timing circuit.")

    if "PC817" in c:
        return row(
            "PC817 DIP-4 wide",
            "THT assembly / verify",
            "JLC THT, consign, or hand-solder",
            "PC817/LTV-817 optocoupler, DIP-4, 7.62mm row spacing",
            "PC817C/LTV-817C family",
            notes="Keep the wide isolation footprint; verify CTR bin is acceptable with Rev-B resistor values.",
            candidate_jlcpcb_part="JLC candidates C5692981 or C50176486",
        )

    if "G5LE" in c:
        return row(
            "G5LE 5V SPDT relay",
            "THT assembly / verify",
            "JLC THT, consign, or hand-solder",
            "5V coil SPDT relay matching Omron G5LE-1 footprint",
            "Omron G5LE-14 DC5 or footprint-compatible",
            notes="Verify coil voltage, contact rating, pinout, height, and wash/flux rules.",
            candidate_jlcpcb_part="JLC candidate C116963",
        )

    if "TMA-0505S" in c:
        return row(
            "TMA-0505S isolated DC/DC",
            "THT assembly / consign likely",
            "Consign exact part unless stock match is proven",
            "TMA-0505S isolated 5V-to-5V 1W SIP DC/DC converter",
            "TRACO Power TMA 0505S",
            "Do not substitute until pinout, isolation rating, output current, and footprint are checked.",
        )

    if c == "J_PI":
        return row(
            "2x10 IDC header",
            "THT assembly / verify",
            "JLC THT or consign",
            "2x10 vertical IDC/shrouded header, 2.54mm pitch",
            notes="Confirm cable keying/orientation against Pi interface harness.",
        )

    if c.startswith("J_PWR") or c.startswith("J_MOTION"):
        positions = "3-position" if "1X03" in f else "2-position"
        candidate_jlcpcb_part = "JLC candidate C5183929" if positions == "2-position" else "No locked JLC candidate yet"
        return row(
            f"{positions} 5.08mm fixed terminal block",
            "THT assembly / verify",
            "JLC THT, consign, or hand-solder",
            f"{positions} fixed screw terminal block, 5.08mm pitch, horizontal wire entry",
            "Phoenix MKDS 1,5 series or footprint-compatible",
            notes="Verify pin pitch, drill size, body keepout, and wire-entry direction.",
            candidate_jlcpcb_part=candidate_jlcpcb_part,
        )

    if c.startswith("J_FAST") or c.startswith("J_SLOW") or c.startswith("J_LAMP") or c.startswith("J_SAFETY"):
        positions = {
            "J_FAST": "10-position",
            "J_SLOW_IN_A": "14-position",
            "J_SLOW_IN_B": "12-position",
            "J_LAMP_LED": "6-position",
            "J_SAFETY": "4-position",
        }
        label = next((v for k, v in positions.items() if c.startswith(k)), "multi-position")
        return row(
            f"{label} 3.5mm pluggable header",
            "THT assembly / verify",
            "JLC THT, consign, or hand-solder",
            f"{label} vertical pluggable terminal header, 3.5mm pitch",
            "Phoenix MCV 1,5/x-G-3,5 family or footprint-compatible",
            "Order matching off-board plugs separately; verify latching/keying and orientation.",
        )

    return row(
        f"{comment} / {footprint}",
        "Needs classification",
        "Manual review",
        f"{comment}, footprint {footprint}",
        notes="No rule matched; classify before PCBA quote.",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    bom_rows = read_csv(IN_BOM)
    dnp_rows = read_csv(IN_DNP)

    grouped: dict[str, dict[str, object]] = {}
    bucket_rows: list[dict[str, object]] = []

    for raw in bom_rows:
        comment = raw["Comment"].strip()
        footprint = raw["Footprint"].strip()
        refs = split_designators(raw["Designator"])
        qty = int(raw["Quantity"])
        meta = classify(comment, footprint)
        key = meta["purchase_key"]

        bucket_rows.append(
            {
                "Comment": comment,
                "Designator": raw["Designator"],
                "Footprint": footprint,
                "Quantity": qty,
                "Assembly Bucket": meta["bucket"],
                "Source Strategy": meta["source_strategy"],
                "Purchase Spec": meta["purchase_spec"],
                "Candidate MPN": meta["candidate_mpn"],
                "Candidate JLCPCB Part #": meta["candidate_jlcpcb_part"],
                "LCSC Part #": raw.get("LCSC Part #", ""),
                "Notes": meta["notes"],
            }
        )

        if key not in grouped:
            grouped[key] = {
                "Assembly Bucket": meta["bucket"],
                "Source Strategy": meta["source_strategy"],
                "Purchase Spec": meta["purchase_spec"],
                "Candidate MPN": meta["candidate_mpn"],
                "Candidate JLCPCB Part #": meta["candidate_jlcpcb_part"],
                "LCSC Part #": raw.get("LCSC Part #", ""),
                "Quantity": 0,
                "Designators": [],
                "Raw BOM Comments": set(),
                "Footprints": set(),
                "Notes": meta["notes"],
            }
        group = grouped[key]
        group["Quantity"] = int(group["Quantity"]) + qty
        group["Designators"].extend(refs)
        group["Raw BOM Comments"].add(comment)
        group["Footprints"].add(footprint)

    working_rows: list[dict[str, object]] = []
    for group in grouped.values():
        working_rows.append(
            {
                "Assembly Bucket": group["Assembly Bucket"],
                "Source Strategy": group["Source Strategy"],
                "Purchase Spec": group["Purchase Spec"],
                "Candidate MPN": group["Candidate MPN"],
                "Candidate JLCPCB Part #": group["Candidate JLCPCB Part #"],
                "LCSC Part #": group["LCSC Part #"],
                "Quantity": group["Quantity"],
                "Designators": ",".join(sort_refs(group["Designators"])),
                "Raw BOM Comments": " | ".join(sorted(group["Raw BOM Comments"])),
                "Footprints": " | ".join(sorted(group["Footprints"])),
                "Notes": group["Notes"],
            }
        )

    bucket_order = {
        "SMT candidate": 0,
        "SMT candidate - verify footprint": 1,
        "SMT candidate - stock verify": 2,
        "THT assembly / verify": 3,
        "THT assembly / consign likely": 4,
        "Consign / assembly-house verify": 5,
        "Needs classification": 6,
    }
    working_rows.sort(key=lambda r: (bucket_order.get(str(r["Assembly Bucket"]), 99), str(r["Purchase Spec"])))
    bucket_rows.sort(key=lambda r: (bucket_order.get(str(r["Assembly Bucket"]), 99), str(r["Comment"])))

    offboard_rows = [
        {
            "Use": "J3 FAST field inputs",
            "Board-side Header": "J3",
            "Required Off-board Part": "10-position 3.5mm pluggable mating plug",
            "Suggested Family": "Phoenix MC 1,5/10-ST-3,5 or compatible mate for MCV 1,5/10-G-3,5",
            "Quantity per Board": 1,
            "Notes": "Order with harness parts; not placed on PCB.",
        },
        {
            "Use": "J4 SLOW A field inputs",
            "Board-side Header": "J4",
            "Required Off-board Part": "14-position 3.5mm pluggable mating plug",
            "Suggested Family": "Phoenix MC 1,5/14-ST-3,5 or compatible mate for MCV 1,5/14-G-3,5",
            "Quantity per Board": 1,
            "Notes": "Order with harness parts; not placed on PCB.",
        },
        {
            "Use": "J5 SLOW B field inputs",
            "Board-side Header": "J5",
            "Required Off-board Part": "12-position 3.5mm pluggable mating plug",
            "Suggested Family": "Phoenix MC 1,5/12-ST-3,5 or compatible mate for MCV 1,5/12-G-3,5",
            "Quantity per Board": 1,
            "Notes": "Order with harness parts; not placed on PCB.",
        },
        {
            "Use": "J13 LED lamps",
            "Board-side Header": "J13",
            "Required Off-board Part": "6-position 3.5mm pluggable mating plug",
            "Suggested Family": "Phoenix MC 1,5/6-ST-3,5 or compatible mate for MCV 1,5/6-G-3,5",
            "Quantity per Board": 1,
            "Notes": "Order with harness parts; not placed on PCB.",
        },
        {
            "Use": "J14 safety loop",
            "Board-side Header": "J14",
            "Required Off-board Part": "4-position 3.5mm pluggable mating plug",
            "Suggested Family": "Phoenix MC 1,5/4-ST-3,5 or compatible mate for MCV 1,5/4-G-3,5",
            "Quantity per Board": 1,
            "Notes": "Order with harness parts; not placed on PCB.",
        },
        {
            "Use": "Mounting hardware",
            "Board-side Header": "MK1-MK4",
            "Required Off-board Part": "M3 mounting hardware and standoffs",
            "Suggested Family": "M3 screws/standoffs sized for enclosure",
            "Quantity per Board": 4,
            "Notes": "Board holes are excluded from BOM/POS.",
        },
        {
            "Use": "Pi ribbon cable",
            "Board-side Header": "J1",
            "Required Off-board Part": "2x10 2.54mm IDC ribbon cable/mate",
            "Suggested Family": "Match J1 shrouded/header choice and Pi-side connector",
            "Quantity per Board": 1,
            "Notes": "Confirm keying/orientation before harness build.",
        },
    ]

    write_csv(
        OUT_WORKING,
        [
            "Assembly Bucket",
            "Source Strategy",
            "Purchase Spec",
            "Candidate MPN",
            "Candidate JLCPCB Part #",
            "LCSC Part #",
            "Quantity",
            "Designators",
            "Raw BOM Comments",
            "Footprints",
            "Notes",
        ],
        working_rows,
    )
    write_csv(
        OUT_BUCKETS,
        [
            "Comment",
            "Designator",
            "Footprint",
            "Quantity",
            "Assembly Bucket",
            "Source Strategy",
            "Purchase Spec",
            "Candidate MPN",
            "Candidate JLCPCB Part #",
            "LCSC Part #",
            "Notes",
        ],
        bucket_rows,
    )
    write_csv(
        OUT_OFFBOARD,
        [
            "Use",
            "Board-side Header",
            "Required Off-board Part",
            "Suggested Family",
            "Quantity per Board",
            "Notes",
        ],
        offboard_rows,
    )

    bucket_counts = defaultdict(int)
    for row in working_rows:
        bucket_counts[str(row["Assembly Bucket"])] += int(row["Quantity"])

    print(f"Input BOM rows: {len(bom_rows)}")
    print(f"Input non-DNP refs: {sum(int(row['Quantity']) for row in bom_rows)}")
    print(f"Grouped purchase lines: {len(working_rows)}")
    print(f"DNP/excluded rows: {len(dnp_rows)}")
    for bucket, count in sorted(bucket_counts.items()):
        print(f"{bucket}: {count}")
    print(f"Wrote {OUT_WORKING}")
    print(f"Wrote {OUT_BUCKETS}")
    print(f"Wrote {OUT_OFFBOARD}")


if __name__ == "__main__":
    main()
