#!/usr/bin/env python3
"""Generate JLCPCB Standard-PCBA BOM/CPL for Phase 8b Rev-B.

This is the order split selected for Rev-B:
- JLC places SMT parts, 32 PC817 optos, and 6 G5LE relays.
- Hand solder A1, all board connectors, and U37.
- Existing DNP/excluded refs remain excluded.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / "kicad" / "fab_revB_routed_manual" / "assembly"
IN_BOM = ASM / "wsl-phase8b-revB-bom-non-dnp.csv"
IN_CPL = ASM / "wsl-phase8b-revB-cpl.csv"
IN_DNP = ASM / "wsl-phase8b-revB-dnp-excluded.csv"

OUT_BOM = ASM / "wsl-phase8b-revB-jlc-standard-pcba-bom.csv"
OUT_UPLOAD_BOM = ASM / "wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv"
OUT_CPL = ASM / "wsl-phase8b-revB-jlc-standard-pcba-cpl.csv"
OUT_EXCLUDED = ASM / "wsl-phase8b-revB-jlc-standard-pcba-excluded.csv"
OUT_LOCK = ASM / "wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv"


# Board refs intentionally omitted from the JLC placement list. These are still
# on the PCB and are installed after JLC assembly.
HAND_SOLDER_REFS = {
    "A1",  # Raspberry Pi Pico module
    "J1",  # Pi IDC/header
    "J2",
    "J3",
    "J4",
    "J5",
    "J6",
    "J7",
    "J8",
    "J9",
    "J10",
    "J11",
    "J13",
    "J14",
    "U37",  # TRACO TMA-0505S
}


PART_LOCK: dict[tuple[str, str], dict[str, str]] = {
    ("0.1uF", "C_0805_2012Metric"): {
        "lcsc": "C49678",
        "mpn": "CC0805KRX7R9BB104",
        "manufacturer": "YAGEO",
        "class": "Basic",
        "locked_spec": "100nF 50V X7R +/-10% 0805 MLCC",
        "note": "Basic, high-stock 0805 decoupler.",
    },
    ("100uF/16V", "CP_Elec_6.3x5.4"): {
        "lcsc": "C19184134",
        "mpn": "CK1C101M-CRE54",
        "manufacturer": "RS",
        "class": "Extended",
        "locked_spec": "100uF 16V +/-20% SMD aluminum electrolytic, D6.3xL5.4mm",
        "note": "Polarized; verify positive mark and package preview before order.",
    },
    ("10nF", "C_0805_2012Metric"): {
        "lcsc": "C17702767",
        "mpn": "C0805B103K500NT",
        "manufacturer": "TORCH",
        "class": "Extended",
        "locked_spec": "10nF 50V X7R +/-10% 0805 MLCC",
        "note": "",
    },
    ("10uF", "C_0805_2012Metric"): {
        "lcsc": "C89827",
        "mpn": "CC0805KKX5R7BB106",
        "manufacturer": "YAGEO",
        "class": "Extended",
        "locked_spec": "10uF 16V X5R +/-10% 0805 MLCC",
        "note": "Verify DC-bias derating remains acceptable on the 5V rail.",
    },
    ("1N4148", "D_SOD-323"): {
        "lcsc": "C118873",
        "mpn": "1N4148WS",
        "manufacturer": "onsemi",
        "class": "Extended",
        "locked_spec": "1N4148WS switching diode, SOD-323",
        "note": "",
    },
    ("SS14", "D_SMA"): {
        "lcsc": "C2480",
        "mpn": "SS14",
        "manufacturer": "MDD",
        "class": "Basic",
        "locked_spec": "SS14 Schottky diode, SMA/DO-214AC",
        "note": "",
    },
    ("G5LE S", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE T", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE SP", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE BE", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE M", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE M2", "Relay_SPDT_Omron-G5LE-1"): {
        "alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"),
    },
    ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"): {
        "lcsc": "C116963",
        "mpn": "G5LE-14 5VDC",
        "manufacturer": "Omron Electronics",
        "class": "Extended",
        "locked_spec": "G5LE-14 5VDC SPDT relay, wave solder",
        "note": "Critical: 5VDC coil. Do not substitute 9V/12V/24V coil.",
    },
    ("MMBT3904 S", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 T", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 SP", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 BE", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 M", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 M2", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 AND ARM", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904 AND RP_OK", "SOT-23"): {
        "alias": ("MMBT3904", "SOT-23"),
    },
    ("MMBT3904", "SOT-23"): {
        "lcsc": "C909754",
        "mpn": "MMBT3904",
        "manufacturer": "GOODWORK",
        "class": "Extended",
        "locked_spec": "MMBT3904 NPN BJT, SOT-23",
        "note": "",
    },
    ("2N7002 LED L_FIRST", "SOT-23"): {
        "alias": ("2N7002", "SOT-23"),
    },
    ("2N7002 LED L_SECOND", "SOT-23"): {
        "alias": ("2N7002", "SOT-23"),
    },
    ("2N7002 LED L_STRIKE", "SOT-23"): {
        "alias": ("2N7002", "SOT-23"),
    },
    ("2N7002 LED L_FOUL", "SOT-23"): {
        "alias": ("2N7002", "SOT-23"),
    },
    ("2N7002", "SOT-23"): {
        "lcsc": "C916396",
        "mpn": "2N7002",
        "manufacturer": "JSMSEMI",
        "class": "Extended",
        "locked_spec": "2N7002 N-channel MOSFET, SOT-23",
        "note": "",
    },
    ("AO3400A kick", "SOT-23"): {
        "alias": ("AO3400A", "SOT-23"),
    },
    ("AO3400A wdog", "SOT-23"): {
        "alias": ("AO3400A", "SOT-23"),
    },
    ("AO3400A", "SOT-23"): {
        "lcsc": "C20917",
        "mpn": "AO3400A",
        "manufacturer": "Alpha & Omega Semicon",
        "class": "Basic",
        "locked_spec": "AO3400A N-channel logic MOSFET, SOT-23",
        "note": "",
    },
    ("AO3401A rail pass", "SOT-23"): {
        "alias": ("AO3401A", "SOT-23"),
    },
    ("AO3401A", "SOT-23"): {
        "lcsc": "C347476",
        "mpn": "AO3401A",
        "manufacturer": "UMW",
        "class": "Extended",
        "locked_spec": "AO3401A P-channel MOSFET, SOT-23",
        "note": "",
    },
    ("4.7k", "R_0805_2012Metric"): {
        "lcsc": "C17673",
        "mpn": "0805W8F4701T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "4.7k 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("2k2", "R_0805_2012Metric"): {
        "lcsc": "C17520",
        "mpn": "0805W8F2201T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "2.2k 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("10k", "R_0805_2012Metric"): {
        "lcsc": "C17414",
        "mpn": "0805W8F1002T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "10k 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("1k", "R_0805_2012Metric"): {
        "lcsc": "C17513",
        "mpn": "0805W8F1001T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "1k 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("330R", "R_0805_2012Metric"): {
        "lcsc": "C17630",
        "mpn": "0805W8F3300T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "330R 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("100k", "R_0805_2012Metric"): {
        "lcsc": "C149504",
        "mpn": "0805W8F1003T5E",
        "manufacturer": "UNI-ROYAL",
        "class": "Basic",
        "locked_spec": "100k 1% 1/8W 0805 resistor",
        "note": "",
    },
    ("MCP23017 MCP_IN_A", "SOIC-28W_7.5x17.9mm_P1.27mm"): {
        "alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm"),
    },
    ("MCP23017 MCP_IN_B", "SOIC-28W_7.5x17.9mm_P1.27mm"): {
        "alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm"),
    },
    ("MCP23017 MCP_OUT_A", "SOIC-28W_7.5x17.9mm_P1.27mm"): {
        "alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm"),
    },
    ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm"): {
        "lcsc": "C47023",
        "mpn": "MCP23017-E/SO",
        "manufacturer": "Microchip Tech",
        "class": "Extended",
        "locked_spec": "MCP23017 I2C I/O expander, SOIC-28-300mil",
        "note": "Critical: I2C MCP23017, not SPI MCP23S17.",
    },
    ("PC817 SA", "DIP-4_W7.62mm"): {
        "alias": ("PC817", "DIP-4_W7.62mm"),
    },
    ("PC817 SB", "DIP-4_W7.62mm"): {
        "alias": ("PC817", "DIP-4_W7.62mm"),
    },
    ("PC817 SC", "DIP-4_W7.62mm"): {
        "alias": ("PC817", "DIP-4_W7.62mm"),
    },
    ("NE555", "SOIC-8_3.9x4.9mm_P1.27mm"): {
        "lcsc": "C7593",
        "mpn": "NE555DR",
        "manufacturer": "Texas Instruments",
        "class": "Extended",
        "locked_spec": "NE555 bipolar timer, SOIC-8",
        "note": "Bipolar 555 selected; avoid CMOS/TLC555 timing change unless revalidated.",
    },
}

for label in [
    "TA1",
    "TA2",
    "TB",
    "DIELL_L",
    "DIELL_R",
    "GS1",
    "GS2",
    "GS3",
    "GS4",
    "GS5",
    "GS6",
    "GS7",
    "GS8",
    "GS9",
    "GS10",
    "GP",
    "OS",
    "BS",
    "PBZ",
    "PBC",
    "FOUL",
    "TENTH",
    "MAN_T",
    "MAN_S",
    "MAN_SWS",
    "MAN_SWSR",
    "AUX1",
    "AUX2",
    "AUX3",
]:
    PART_LOCK[(f"PC817 {label}", "DIP-4_W7.62mm")] = {"alias": ("PC817", "DIP-4_W7.62mm")}

PART_LOCK[("PC817", "DIP-4_W7.62mm")] = {
    "lcsc": "C5692981",
    "mpn": "PC817B",
    "manufacturer": "UMW",
    "class": "Extended",
    "locked_spec": "PC817B optocoupler, DIP-4, wave solder",
    "note": "Confirm DIP-4 preview/orientation; CTR bin must be accepted with Rev-B field resistors.",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_refs(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def ref_key(ref: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in ref if not ch.isdigit())
    number = "".join(ch for ch in ref if ch.isdigit())
    return prefix, int(number or 0)


def refs_join(refs: list[str]) -> str:
    return ",".join(sorted(refs, key=ref_key))


def jlc_layer(side: str) -> str:
    normalized = side.strip().lower()
    if normalized == "top":
        return "Top"
    if normalized == "bottom":
        return "Bottom"
    raise SystemExit(f"Unexpected CPL side value: {side!r}")


def jlc_cpl_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "Designator": row["Ref"].strip(),
        "Mid X": f"{float(row['PosX']):.6f}",
        "Mid Y": f"{float(row['PosY']):.6f}",
        "Layer": jlc_layer(row["Side"]),
        "Rotation": f"{float(row['Rot']):.6f}",
    }


def locked_part(comment: str, footprint: str) -> tuple[tuple[str, str], dict[str, str]]:
    key = (comment, footprint)
    seen = set()
    while True:
        if key in seen:
            raise SystemExit(f"Alias loop in part lock: {comment} / {footprint}")
        seen.add(key)
        meta = PART_LOCK.get(key)
        if meta is None:
            raise SystemExit(f"No JLC part lock for {comment!r} / {footprint!r}")
        alias = meta.get("alias")
        if not alias:
            return key, meta
        key = alias


def excluded_reason(ref: str) -> str:
    if ref == "A1":
        return "Hand solder: Raspberry Pi Pico module"
    if ref == "U37":
        return "Hand solder: TRACO TMA-0505S isolated DC/DC"
    if ref.startswith("J"):
        return "Hand solder: connector/header"
    return "Excluded from JLC placement"


def main() -> int:
    bom_rows = read_csv(IN_BOM)
    cpl_rows = read_csv(IN_CPL)
    dnp_rows = read_csv(IN_DNP)

    groups: dict[tuple[str, str], dict[str, object]] = {}
    excluded_rows: list[dict[str, object]] = []

    for row in bom_rows:
        comment = row["Comment"].strip()
        footprint = row["Footprint"].strip()
        refs = split_refs(row["Designator"])

        place_refs = [ref for ref in refs if ref not in HAND_SOLDER_REFS]
        hand_refs = [ref for ref in refs if ref in HAND_SOLDER_REFS]

        for ref in hand_refs:
            excluded_rows.append(
                {
                    "Designator": ref,
                    "Comment": comment,
                    "Footprint": footprint,
                    "Reason": excluded_reason(ref),
                }
            )

        if not place_refs:
            continue

        lock_key, meta = locked_part(comment, footprint)
        if lock_key not in groups:
            groups[lock_key] = {
                "Comment": meta["locked_spec"],
                "Designators": [],
                "Footprint": footprint,
                "Quantity": 0,
                "LCSC Part #": meta["lcsc"],
                "MFR Part #": meta["mpn"],
                "Manufacturer": meta["manufacturer"],
                "JLC Class": meta["class"],
                "Notes": meta["note"],
            }

        group = groups[lock_key]
        group["Designators"].extend(place_refs)
        group["Quantity"] = int(group["Quantity"]) + len(place_refs)

    bom_out = []
    for group in groups.values():
        bom_out.append(
            {
                "Comment": group["Comment"],
                "Designator": refs_join(group["Designators"]),
                "Footprint": group["Footprint"],
                "Quantity": group["Quantity"],
                "LCSC Part #": group["LCSC Part #"],
                "MFR Part #": group["MFR Part #"],
                "Manufacturer": group["Manufacturer"],
                "JLC Class": group["JLC Class"],
                "Notes": group["Notes"],
            }
        )
    bom_out.sort(key=lambda row: ref_key(str(row["Designator"]).split(",")[0]))

    place_refs = {ref for row in bom_out for ref in split_refs(str(row["Designator"]))}
    cpl_out = [row for row in cpl_rows if row["Ref"] in place_refs]
    cpl_out.sort(key=lambda row: ref_key(row["Ref"]))
    jlc_cpl_out = [jlc_cpl_row(row) for row in cpl_out]

    cpl_refs = {row["Ref"] for row in cpl_out}
    if cpl_refs != place_refs:
        raise SystemExit(f"BOM/CPL ref mismatch: BOM-only={sorted(place_refs-cpl_refs)} CPL-only={sorted(cpl_refs-place_refs)}")

    expected_hand = set(HAND_SOLDER_REFS)
    excluded_hand = {str(row["Designator"]) for row in excluded_rows}
    if excluded_hand != expected_hand:
        raise SystemExit(f"Hand-solder exclusion mismatch: {sorted(expected_hand ^ excluded_hand)}")

    jlc_ref_count = sum(int(row["Quantity"]) for row in bom_out)
    if jlc_ref_count != 174:
        raise SystemExit(f"Expected 174 JLC-placed refs, got {jlc_ref_count}")
    if len(bom_out) != 20:
        raise SystemExit(f"Expected 20 unique JLC part lines, got {len(bom_out)}")

    # Hard correctness checks for the two high-risk substitutions.
    by_lcsc = {str(row["LCSC Part #"]): row for row in bom_out}
    relay = by_lcsc.get("C116963")
    if not relay or "5VDC" not in str(relay["MFR Part #"]):
        raise SystemExit("Relay lock failed: C116963 / G5LE-14 5VDC is required")
    mcp = by_lcsc.get("C47023")
    if not mcp or "MCP23017" not in str(mcp["MFR Part #"]) or "MCP23S17" in str(mcp["MFR Part #"]):
        raise SystemExit("MCP lock failed: MCP23017 I2C part is required")

    write_csv(
        OUT_BOM,
        [
            "Comment",
            "Designator",
            "Footprint",
            "Quantity",
            "LCSC Part #",
            "MFR Part #",
            "Manufacturer",
            "JLC Class",
            "Notes",
        ],
        bom_out,
    )
    write_csv(
        OUT_UPLOAD_BOM,
        [
            "Comment",
            "Designator",
            "Footprint",
            "Quantity",
            "LCSC Part #",
        ],
        bom_out,
    )
    write_csv(OUT_CPL, ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"], jlc_cpl_out)
    write_csv(
        OUT_EXCLUDED,
        ["Designator", "Comment", "Footprint", "Reason"],
        sorted(excluded_rows, key=lambda row: ref_key(str(row["Designator"]))),
    )
    write_csv(
        OUT_LOCK,
        [
            "LCSC Part #",
            "MFR Part #",
            "Manufacturer",
            "JLC Class",
            "Locked Spec",
            "Quantity",
            "Designators",
            "Notes",
        ],
        [
            {
                "LCSC Part #": row["LCSC Part #"],
                "MFR Part #": row["MFR Part #"],
                "Manufacturer": row["Manufacturer"],
                "JLC Class": row["JLC Class"],
                "Locked Spec": row["Comment"],
                "Quantity": row["Quantity"],
                "Designators": row["Designator"],
                "Notes": row["Notes"],
            }
            for row in bom_out
        ],
    )

    class_counts = defaultdict(int)
    for row in bom_out:
        class_counts[str(row["JLC Class"])] += int(row["Quantity"])

    print(f"Input BOM refs: {sum(int(row['Quantity']) for row in bom_rows)}")
    print(f"JLC placed refs: {jlc_ref_count}")
    print(f"JLC unique part lines: {len(bom_out)}")
    print(f"Filtered CPL rows: {len(cpl_out)}")
    print(f"Hand-solder excluded refs: {len(excluded_rows)}")
    print(f"DNP/excluded reference rows remain separate: {len(dnp_rows)}")
    for klass, count in sorted(class_counts.items()):
        print(f"{klass}: {count}")
    print(f"Wrote {OUT_BOM}")
    print(f"Wrote {OUT_UPLOAD_BOM}")
    print(f"Wrote {OUT_CPL}")
    print(f"Wrote {OUT_EXCLUDED}")
    print(f"Wrote {OUT_LOCK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
