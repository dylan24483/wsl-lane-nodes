#!/usr/bin/env python3
"""
Apply the Rev-D KiCad net-class contract to kicad/revD/wsl-phase8b-revD.kicad_pcb.

COPY of scripts/apply_netclasses_revB.py (the rev-C script is SACRED and
untouched) with the two rev-D classifier edits from
docs/phase8_revD_change_spec.md §H.1 — kept in LOCKSTEP with
scripts/audit_revD_board.py:
  * exact-name 'ADC_VCC5_SENSE' -> Logic_Signal   (item D)
  * prefix 'TAP_'               -> Logic_Signal   (item E)
plus a fail-closed EXACT per-class count assertion (remediation spec R1.7):
  Logic_Signal 97 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 82 /
  Machine_Output 21  = 217 nets.
A Safety_Rail count != 13 is an automatic stop-ship (spec §E).

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\apply_netclasses_revD.py --write

The class map is intentionally strict: every current board net must match
exactly one class, and anonymous / unknown nets fail the run.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "kicad" / "revD" / "wsl-phase8b-revD.kicad_pcb"

# Spec §H.1 delta table + remediation spec R1.7 (2026-07-21: +4 TAP_GATE_*
# nets -> Logic_Signal 93->97) — keep in LOCKSTEP with audit_revD_board.py
# EXPECTED.
EXPECTED_COUNTS = {
    # 2026-07-21 round-2 remediation (Codex R2-4/R2-6): +6 Logic_Signal
    # (J16_5V/J16_3V3/J16_SDA/J16_SCL/REV_ID0/REV_ID1) -> 97 -> 103.
    "Logic_Signal": 103,
    "Logic_Power": 4,
    "Safety_Rail": 13,
    "Field_Sense": 82,
    "Machine_Output": 21,
}

NETCLASS_RULES = {
    "Logic_Signal": {
        "width_mm": 0.25,
        "clearance_mm": 0.20,
        "via_dia_mm": 0.60,
        "via_drill_mm": 0.30,
    },
    "Logic_Power": {
        "width_mm": 0.50,
        "clearance_mm": 0.20,
        "via_dia_mm": 0.80,
        "via_drill_mm": 0.40,
    },
    "Safety_Rail": {
        "width_mm": 0.60,
        "clearance_mm": 0.30,
        "via_dia_mm": 0.80,
        "via_drill_mm": 0.40,
    },
    "Field_Sense": {
        "width_mm": 0.30,
        "clearance_mm": 0.40,
        "via_dia_mm": 0.70,
        "via_drill_mm": 0.35,
    },
    "Machine_Output": {
        "width_mm": 0.50,
        "clearance_mm": 0.35,
        "via_dia_mm": 1.00,
        "via_drill_mm": 0.50,
    },
}

LOGIC_POWER = {"VCC_5V", "VCC_5V_RAW", "VCC_3V3", "GND"}
LOGIC_EXACT = {
    "RP2040_OK",
    "ARM_PERMIT",
    "WDOG_TIMING_NODE",
    "BASE_S",
    "BASE_T",
    "BASE_SP",
    "BASE_BE",
    "BASE_M",
    "BASE_M2",
    "BASE_M1",
    "ADC_VCC5_SENSE",  # rev-D item D
}
SAFETY_EXACT = {"RELAY_ENABLE_RAIL", "RAIL_GATE"}


def mm(value: float) -> int:
    return pcbnew.FromMM(float(value))


def make_netclass(name: str, rule: dict[str, float]) -> pcbnew.NETCLASS:
    netclass = pcbnew.NETCLASS(name)
    netclass.SetTrackWidth(mm(rule["width_mm"]))
    netclass.SetClearance(mm(rule["clearance_mm"]))
    netclass.SetViaDiameter(mm(rule["via_dia_mm"]))
    netclass.SetViaDrill(mm(rule["via_drill_mm"]))
    return netclass


def classify_net(net_name: str) -> list[str]:
    hits: list[str] = []

    if net_name in LOGIC_POWER:
        hits.append("Logic_Power")

    if (
        net_name in SAFETY_EXACT
        or net_name.startswith("COIL_LO_")
        or net_name.startswith("BASE_AND_")
        or net_name.startswith("SAFE_")
    ):
        hits.append("Safety_Rail")

    if net_name.startswith("FIELD_"):
        hits.append("Field_Sense")

    if (
        net_name.startswith("OUT_")
        or net_name.startswith("SNUB_")
    ):
        hits.append("Machine_Output")

    if (
        net_name in LOGIC_EXACT
        or net_name.startswith("FAST_")
        or net_name.startswith("SLOW_")
        or net_name.startswith("DRV_")
        or net_name.startswith("I2C_")
        or net_name.startswith("PI_UART_")
        or net_name.startswith("MCP_INT_")
        or net_name.startswith("LED_")
        or net_name.startswith("NE555_")
        or net_name.startswith("WDOG_KICK")
        or net_name.startswith("WDOG_OK")
        or net_name.startswith("AND_")
        or net_name.startswith("TAP_")     # rev-D item E
        or net_name.startswith("J16_")     # round-2 R2-4 protected J16 nets
        or net_name.startswith("REV_ID")   # round-2 R2-6 revision straps
    ):
        hits.append("Logic_Signal")

    return hits


def board_nets(board: pcbnew.BOARD) -> list[str]:
    return sorted(str(net) for net in board.GetNetsByName().keys() if str(net))


def classify_all(nets: list[str]) -> tuple[dict[str, str], list[str], list[tuple[str, list[str]]]]:
    assignments: dict[str, str] = {}
    unknown: list[str] = []
    overlap: list[tuple[str, list[str]]] = []

    for net_name in nets:
        hits = classify_net(net_name)
        if len(hits) == 1:
            assignments[net_name] = hits[0]
        elif not hits:
            unknown.append(net_name)
        else:
            overlap.append((net_name, hits))

    return assignments, unknown, overlap


def apply_netclasses(board: pcbnew.BOARD, assignments: dict[str, str]) -> None:
    settings = board.GetDesignSettings().m_NetSettings
    settings.ClearNetclasses()
    settings.ClearNetclassPatternAssignments()
    settings.ClearNetclassLabelAssignments()

    for name, rule in NETCLASS_RULES.items():
        settings.SetNetclass(name, make_netclass(name, rule))

    # Use exact-name patterns so KiCad persists the assignments cleanly and a
    # future unexpected net still fails this script instead of inheriting a class.
    for net_name, class_name in sorted(assignments.items()):
        settings.SetNetclassPatternAssignment(net_name, class_name)

    settings.RecomputeEffectiveNetclasses()


def verify_effective(board: pcbnew.BOARD, assignments: dict[str, str]) -> list[tuple[str, str, str]]:
    settings = board.GetDesignSettings().m_NetSettings
    settings.RecomputeEffectiveNetclasses()
    mismatches: list[tuple[str, str, str]] = []

    for net_name, expected in sorted(assignments.items()):
        actual = settings.GetEffectiveNetClass(net_name).GetName()
        if actual != expected:
            mismatches.append((net_name, expected, actual))

    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--write", action="store_true", help="modify the PCB file")
    args = parser.parse_args()

    board_path = args.board.resolve()
    if not board_path.exists():
        raise SystemExit(f"ERROR: board not found: {board_path}")
    # Sacred-file guard: this script only ever writes revD-named boards.
    if "revD" not in board_path.name:
        raise SystemExit(f"REFUSING: {board_path} is not revD-named (sacred-file guard).")

    board = pcbnew.LoadBoard(str(board_path))
    nets = board_nets(board)
    assignments, unknown, overlap = classify_all(nets)

    print(f"Board: {board_path}")
    print(f"Nets: {len(nets)}")

    if unknown:
        print("ERROR: unknown nets:")
        for net_name in unknown:
            print(f"  {net_name}")

    if overlap:
        print("ERROR: overlapping net-class rules:")
        for net_name, hits in overlap:
            print(f"  {net_name}: {', '.join(hits)}")

    if unknown or overlap:
        return 2

    counts = Counter(assignments.values())
    for class_name in NETCLASS_RULES:
        print(f"{class_name}: {counts[class_name]}")

    # Fail-closed exact-count gate (spec §H.1, lockstep with audit_revD_board.py).
    count_errors = []
    for class_name, expected in EXPECTED_COUNTS.items():
        if counts.get(class_name, 0) != expected:
            count_errors.append(f"{class_name}: expected {expected}, got {counts.get(class_name, 0)}")
    if counts.get("Safety_Rail", 0) != 13:
        count_errors.append("STOP-SHIP: Safety_Rail count is not EXACTLY 13")
    if len(nets) != sum(EXPECTED_COUNTS.values()):
        count_errors.append(f"total nets: expected {sum(EXPECTED_COUNTS.values())}, got {len(nets)}")
    if count_errors:
        print("ERROR: class-count contract violated:")
        for err in count_errors:
            print(f"  {err}")
        return 5

    apply_netclasses(board, assignments)
    mismatches = verify_effective(board, assignments)
    if mismatches:
        print("ERROR: effective net-class mismatch before save:")
        for net_name, expected, actual in mismatches:
            print(f"  {net_name}: expected {expected}, got {actual}")
        return 3

    if not args.write:
        print("Dry run only; pass --write to modify the board.")
        return 0

    pcbnew.SaveBoard(str(board_path), board)

    reloaded = pcbnew.LoadBoard(str(board_path))
    mismatches = verify_effective(reloaded, assignments)
    if mismatches:
        print("ERROR: effective net-class mismatch after reload:")
        for net_name, expected, actual in mismatches:
            print(f"  {net_name}: expected {expected}, got {actual}")
        return 4

    print("Saved board with Rev-D net classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
