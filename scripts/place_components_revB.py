#!/usr/bin/env python3
"""
Programmatic first placement for WSL Phase 8 Rev-B.

This script intentionally starts from the corrected SKiDL netlist
(`kicad/wsl-phase8b.net`) and creates `kicad/wsl-phase8b.kicad_pcb`.
It places by the SKiDL functional tag field, not by assumed refdes, so
small ref-number shifts do not scramble the layout.

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\place_components_revB.py --force

The placement is a connectivity/room scaffold for review and routing, not a
fab release. Board ratings, connector pinout, dry-vs-AC input population,
clearance/creepage, and final enclosure constraints still need review.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
KICAD_DIR = ROOT / "kicad"
DEFAULT_NETLIST = KICAD_DIR / "wsl-phase8b.net"
DEFAULT_BOARD = KICAD_DIR / "wsl-phase8b.kicad_pcb"
FP_ROOT = Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints")
TESTPOINT_LIB = FP_ROOT / "TestPoint.pretty"
TESTPOINT_FP = "TestPoint_Pad_1.5x1.5mm"
MOUNTING_HOLE_LIB = FP_ROOT / "MountingHole.pretty"
MOUNTING_HOLE_FP = "MountingHole_3.2mm_M3"

BOARD_W = 250.0
BOARD_H = 225.0
FIELD_LOGIC_GUTTER = (76.8, 80.0)
LOGIC_MACHINE_GUTTER = (181.0, 184.2)

FAST_INPUTS = ["SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R"]
SLOW_A = [f"GS{i}" for i in range(1, 11)] + ["GP", "OS", "BS"]
SLOW_B = ["PBZ", "PBC", "FOUL", "TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "AUX1", "AUX2", "AUX3"]
MOTION = ["S", "T", "SP", "BE", "M", "M2", "M1"]
LAMPS = ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]


@dataclass
class Component:
    ref: str
    value: str
    footprint: str
    tag: str


def mm(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def set_angle(item, degrees: float) -> None:
    try:
        item.SetTextAngle(pcbnew.EDA_ANGLE(degrees, pcbnew.DEGREES_T))
    except Exception:
        item.SetTextAngle(int(degrees * 10))


def section(text: str, start_pat: str, end_pat: str) -> str:
    start = re.search(start_pat, text, re.M)
    if not start:
        raise ValueError(f"Missing section marker: {start_pat}")
    end = re.search(end_pat, text[start.end():], re.M)
    if not end:
        raise ValueError(f"Missing section end marker after: {start_pat}")
    return text[start.end(): start.end() + end.start()]


def parse_netlist(path: Path) -> tuple[list[Component], dict[str, list[tuple[str, str]]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    comp_text = section(text, r"^\s*\(components\s*$", r"^\s*\(nets\s*$")
    net_text = text[re.search(r"^\s*\(nets\s*$", text, re.M).end():]

    components: list[Component] = []
    blocks = re.split(r"\n\s*\(comp\s*\n", comp_text)
    for block in blocks[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', block)
        value = re.search(r'\(value "([^"]*)"\)', block)
        footprint = re.search(r'\(footprint "([^"]+)"\)', block)
        tag = re.search(r'\(name "SKiDL Tag"\) "([^"]+)"\)', block)
        if not (ref and value and footprint):
            continue
        components.append(
            Component(
                ref=ref.group(1),
                value=value.group(1),
                footprint=footprint.group(1),
                tag=tag.group(1) if tag else ref.group(1),
            )
        )

    nets: dict[str, list[tuple[str, str]]] = {}
    current_name: str | None = None
    pending_ref: str | None = None
    for line in net_text.splitlines():
        if line.strip().startswith("(net"):
            current_name = None
            pending_ref = None
            continue
        name = re.search(r'\(name "([^"]+)"\)', line)
        if name and current_name is None:
            current_name = name.group(1)
            nets[current_name] = []
            continue
        if current_name:
            ref = re.search(r'\(ref "([^"]+)"\)', line)
            if ref:
                pending_ref = ref.group(1)
            pin = re.search(r'\(pin "([^"]+)"\)', line)
            if pin and pending_ref:
                nets[current_name].append((pending_ref, pin.group(1)))
                pending_ref = None

    if not components:
        raise ValueError(f"No components parsed from {path}")
    if not nets:
        raise ValueError(f"No nets parsed from {path}")
    return components, nets


def load_footprint(fp_name: str):
    if ":" not in fp_name:
        raise ValueError(f"Malformed footprint name: {fp_name}")
    lib, name = fp_name.split(":", 1)
    lib_dir = FP_ROOT / f"{lib}.pretty"
    if not lib_dir.exists():
        raise FileNotFoundError(f"Footprint library not found: {lib_dir}")
    fp = pcbnew.FootprintLoad(str(lib_dir), name)
    if fp is None:
        raise FileNotFoundError(f"Could not load footprint {fp_name}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def build_board_from_netlist(components: list[Component], nets: dict[str, list[tuple[str, str]]]) -> pcbnew.BOARD:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)

    net_items = {}
    for name in sorted(nets):
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        net_items[name] = item

    pin_to_net = {}
    for net_name, nodes in nets.items():
        for ref, pin in nodes:
            pin_to_net[(ref, pin)] = net_items[net_name]

    for comp in components:
        fp = load_footprint(comp.footprint)
        fp.SetReference(comp.ref)
        fp.SetValue(comp.value)
        fp.Reference().SetLayer(pcbnew.F_Fab)
        fp.Value().SetVisible(False)
        fp.SetPosition(mm(BOARD_W / 2, BOARD_H / 2))
        dnp = is_dnp_component(comp)
        if hasattr(fp, "SetDNP") and dnp:
            fp.SetDNP(True)
        if hasattr(fp, "SetExcludedFromBOM") and dnp:
            fp.SetExcludedFromBOM(True)
        if hasattr(fp, "SetExcludedFromPosFiles") and dnp:
            fp.SetExcludedFromPosFiles(True)
        for pad in fp.Pads():
            net = pin_to_net.get((comp.ref, pad.GetNumber()))
            if net is not None:
                pad.SetNet(net)
        board.Add(fp)

    return board


def is_m1_optional_tag(tag: str) -> bool:
    return tag.endswith("_M1") or tag in {"K_M1", "MOV_M1", "Csnub_M1", "Dfly_M1", "Rb_M1", "Rpd_M1", "Rsnub_M1"}


def is_dnp_component(comp: Component) -> bool:
    return is_m1_optional_tag(comp.tag) or "DNP" in comp.value.upper()


def base_placement() -> dict[str, tuple[float, float, float]]:
    p: dict[str, tuple[float, float, float]] = {
        # Edge connectors.
        "J_PWR": (104, 10, 0),
        "J_SAFE": (160, 10, 0),
        "J_PI": (126, 10, 90),
        "J_FAST": (9, 42, 90),
        "J_SLOWA": (9, 103, 90),
        "J_SLOWB": (9, 168, 90),
        "J_LAMP": (104, 206, 0),

        # Logic/control spine.
        "RP_PICO": (124, 55, 0),
        "MCP_IN_A": (122, 104, 0),
        "MCP_IN_B": (122, 146, 0),
        "MCP_OUT_A": (140, 112, 0),
        "ISO_WET": (73.9, 13, 90),
        "D_PROT": (101, 24, 0),
        "C_3V3_BULK": (140, 78, 0),
        "R_I2C_SDA": (103, 86, 90),
        "R_I2C_SCL": (110, 86, 90),

        # Watchdog and safety rail.
        "U_WDOG": (151, 50, 0),
        "Q_WDOG_KICK": (142, 58, 0),
        "Q_WDOG_OK": (162, 58, 0),
        "R_WDOG_TIMING": (146, 40, 90),
        "C_WDOG_TIMING": (156, 42, 90),
        "R_WDOG_TRIG_PULLUP": (145, 78, 90),
        "R_WDOG_KICK_GATE": (142, 47, 90),
        "R_WDOG_KICK_PD": (142, 70, 90),
        "R_WDOG_OUT_GATE": (162, 47, 90),
        "R_WDOG_OUT_PD": (162, 70, 90),
        "C_WDOG_VCC": (156, 67, 90),
        "C_WDOG_CTRL": (166, 42, 90),
        "D_WDOG_TIMING": (152, 35, 0),
        "D_WDOG_TRIG": (159, 35, 0),
        "Q_RAIL": (158, 82, 0),
        "R_RAIL_GATE_PULLUP": (148, 82, 90),
        "Q_AND_ARM": (143, 92, 0),
        "Q_AND_RP_OK": (160, 96, 0),
        "Rb_AND_ARM": (133, 90, 90),
        "Rpd_AND_ARM": (133, 98, 90),
        "Rb_AND_RP_OK": (170, 90, 90),
        "Rpd_AND_RP_OK": (170, 98, 90),

        # MCP decoupling.
        "C_MCP_IN_A": (116, 92, 0),
        "C_MCP_IN_B": (113, 130, 0),
        "C_MCP_OUT_A": (140, 96, 0),
    }

    # Input front ends. All optos straddle the FIELD/LOGIC gutter: field-side
    # LED pins on the left, logic transistor pins on the right.
    input_order = FAST_INPUTS + SLOW_A + SLOW_B
    for i, name in enumerate(input_order):
        y = 24 + i * 6.0
        p[f"OPTO_{name}"] = (74, y, 0)
        p[f"Rin_{name}"] = (58, y - 1.8, 0)
        p[f"Rpu_{name}"] = (92, y + 1.8, 0)

    # Motion outputs. Coils/drivers are logic-side of each relay; contacts
    # and suppression are machine-output side near J_MOTION.
    for i, name in enumerate(MOTION):
        y = 72 + i * 22
        p[f"J_MOTION_{name}"] = (242, y - 4, 270)
        p[f"K_{name}"] = (176, y, 90)
        p[f"Qk_{name}"] = (160, y - 5, 0)
        p[f"Rb_{name}"] = (150, y - 7, 90)
        p[f"Rpd_{name}"] = (150, y - 1, 90)
        p[f"Dfly_{name}"] = (164, y + 6, 0)
        p[f"Rsnub_{name}"] = (222, y - 7, 90)
        p[f"Csnub_{name}"] = (230, y, 90)
        p[f"MOV_{name}"] = (222, y + 8, 90)

    # Mask status LEDs are user-supplied LEDs in the mask housings, driven from
    # logic-side 5V through local low-side FET drivers.
    lamp_x = {
        "L_FIRST": 104,
        "L_SECOND": 116,
        "L_STRIKE": 128,
        "L_FOUL": 140,
    }
    for name in LAMPS:
        x = lamp_x[name]
        p[f"Qled_{name}"] = (x, 198, 0)
        p[f"Rgled_{name}"] = (x - 3, 190, 90)
        p[f"Rpdled_{name}"] = (x + 3, 190, 90)
        p[f"Rled_{name}"] = (x, 182, 0)

    return p


def place_components(board: pcbnew.BOARD, tag_by_ref: dict[str, str]) -> tuple[int, list[str]]:
    placement = base_placement()
    placed = 0
    missing: list[str] = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        tag = tag_by_ref.get(ref, ref)
        pos = placement.get(tag)
        if pos is None:
            missing.append(f"{ref}:{tag}")
            continue
        x, y, rot = pos
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        placed += 1
    return placed, missing


def add_mounting_holes(board: pcbnew.BOARD) -> int:
    positions = [(4, 4), (BOARD_W - 4, 4), (4, BOARD_H - 4), (BOARD_W - 4, BOARD_H - 4)]
    for i, (x, y) in enumerate(positions, 1):
        fp = pcbnew.FootprintLoad(str(MOUNTING_HOLE_LIB), MOUNTING_HOLE_FP)
        if fp is None:
            raise RuntimeError(f"Could not load {MOUNTING_HOLE_FP}")
        fp.SetFPID(pcbnew.LIB_ID("MountingHole", MOUNTING_HOLE_FP))
        fp.SetReference(f"MK{i}")
        fp.SetValue("M3")
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetPosition(mm(x, y))
        board.Add(fp)
    return len(positions)


def add_test_pad(board: pcbnew.BOARD, ref: str, net_name: str, x: float, y: float) -> None:
    fp = pcbnew.FootprintLoad(str(TESTPOINT_LIB), TESTPOINT_FP)
    if fp is None:
        raise RuntimeError(f"Could not load {TESTPOINT_FP}")
    fp.SetFPID(pcbnew.LIB_ID("TestPoint", TESTPOINT_FP))
    fp.SetReference(ref)
    fp.SetValue(net_name)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetPosition(mm(x, y))
    net = board.FindNet(net_name)
    if net is None:
        print(f"  WARN: test pad {ref} net not found: {net_name}")
    else:
        for pad in fp.Pads():
            pad.SetNet(net)
    board.Add(fp)


def add_test_pads(board: pcbnew.BOARD) -> int:
    pads = [
        ("TP4", "FIELD_WET_V", 22, 214),
        ("TP5", "FIELD_GND", 34, 214),
        ("TP1", "VCC_5V", 92, 214),
        ("TP2", "GND", 104, 214),
        ("TP3", "VCC_3V3", 116, 214),
        ("TP6", "I2C_SDA", 128, 214),
        ("TP7", "I2C_SCL", 140, 214),
        ("TP8", "WDOG_KICK", 150, 214),
        ("TP9", "WDOG_TIMING_NODE", 92, 221),
        ("TP10", "NE555_TRIG", 104, 221),
        ("TP11", "NE555_OUT", 116, 221),
        ("TP12", "WDOG_OK_PULLDOWN", 128, 221),
        ("TP13", "ARM_PERMIT", 136, 221),
        ("TP14", "RP2040_OK", 148, 221),
        ("TP15", "SAFE_STOP_RETURN", 156, 221),
        ("TP16", "RELAY_ENABLE_RAIL", 164, 221),
    ]
    for ref, net, x, y in pads:
        add_test_pad(board, ref, net, x, y)
    return len(pads)


def add_rect(board: pcbnew.BOARD, x1: float, y1: float, x2: float, y2: float, layer, width=0.12) -> None:
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    for a, b in zip(pts, pts[1:]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(mm(*a))
        seg.SetEnd(mm(*b))
        seg.SetLayer(layer)
        seg.SetWidth(pcbnew.FromMM(width))
        board.Add(seg)


def add_text(board: pcbnew.BOARD, text: str, x: float, y: float, size=1.0, rot=0, layer=None) -> None:
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetLayer(layer if layer is not None else pcbnew.F_SilkS)
    item.SetPosition(mm(x, y))
    item.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    item.SetTextThickness(pcbnew.FromMM(0.15))
    set_angle(item, rot)
    board.Add(item)


def draw_board_outline(board: pcbnew.BOARD) -> None:
    add_rect(board, 0, 0, BOARD_W, BOARD_H, pcbnew.Edge_Cuts, 0.15)


def add_keepout(board: pcbnew.BOARD, name: str, x1: float, y1: float, x2: float, y2: float) -> None:
    zone = pcbnew.ZONE(board)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowTracks(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowZoneFills(True)
    zone.SetDoNotAllowPads(False)
    zone.SetDoNotAllowFootprints(False)
    zone.SetLayerSet(pcbnew.LSET.AllCuMask())

    poly = pcbnew.VECTOR_VECTOR2I()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        poly.append(mm(x, y))
    zone.AddPolygon(poly)
    board.Add(zone)

    add_rect(board, x1, y1, x2, y2, pcbnew.Dwgs_User, 0.08)
    add_text(board, name, x1 + 0.3, y1 + 2.0, 0.55, 90, pcbnew.Dwgs_User)


def add_isolation_keepouts(board: pcbnew.BOARD) -> None:
    # Narrow hard no-route strips between the legitimate package-side pads.
    add_keepout(board, "NO COPPER FIELD/LOGIC", FIELD_LOGIC_GUTTER[0], 14, FIELD_LOGIC_GUTTER[1], 207)

    # The G5LE-14 contact set straddles the old logic/machine no-route strip:
    # COM is pad 1 on the relay's coil-side half, while NO/NC are pads 3/4 on
    # the contact-side half. Leave narrow, explicit openings for those
    # relay contact cores and let the 3.2 mm clearance/creepage rules enforce
    # the real isolation contract around them.
    relay_rows = [72 + i * 22 for i in range(len(MOTION))]
    y = 20.0
    for row_y in relay_rows:
        gap_lo = row_y - 2.0
        gap_hi = row_y + 2.0
        if gap_lo > y:
            add_keepout(board, "NO COPPER LOGIC/MACHINE", LOGIC_MACHINE_GUTTER[0], y, LOGIC_MACHINE_GUTTER[1], gap_lo)
        y = gap_hi
    if y < 216.0:
        add_keepout(board, "NO COPPER LOGIC/MACHINE", LOGIC_MACHINE_GUTTER[0], y, LOGIC_MACHINE_GUTTER[1], 216)


def add_domain_guides(board: pcbnew.BOARD) -> None:
    add_rect(board, 6, 14, FIELD_LOGIC_GUTTER[0], 207, pcbnew.Dwgs_User)
    add_rect(board, FIELD_LOGIC_GUTTER[1], 14, LOGIC_MACHINE_GUTTER[0], 216, pcbnew.Dwgs_User)
    add_rect(board, LOGIC_MACHINE_GUTTER[1], 20, 246, 216, pcbnew.Dwgs_User)
    add_text(board, "FIELD INPUT / ISOLATED WETTING", 12, 210, 0.8, 0, pcbnew.Dwgs_User)
    add_text(board, "LOGIC / SAFETY / WATCHDOG", 82, 210, 0.8, 0, pcbnew.Dwgs_User)
    add_text(board, "MACHINE OUTPUTS", 187, 210, 0.8, 0, pcbnew.Dwgs_User)


def add_connector_labels(board: pcbnew.BOARD) -> None:
    labels = [
        ("5V IN", 18, 20, 0.8, 0),
        ("SAFETY", 49, 20, 0.8, 0),
        ("PI LINK", 115, 20, 0.8, 0),
        ("FAST", 22, 42, 0.8, 90),
        ("SLOW A", 22, 103, 0.8, 90),
        ("SLOW B", 22, 168, 0.8, 90),
        ("MOTION", 232, 110, 0.8, 90),
        ("LAMPS", 232, 180, 0.8, 90),
        ("M1 DNP", 191, 209, 0.8, 0),
    ]
    for args in labels:
        add_text(board, *args, layer=pcbnew.Dwgs_User)


def add_silkscreen_labels(board: pcbnew.BOARD) -> None:
    labels = [
        # Board identity / order sanity.
        ("WSL LANE NODE PHASE 8B REV-C", 210.0, 42.0, 1.0, 0),
        ("4L 250x225  INPUTS LEFT  OUTPUTS RIGHT", 210.0, 45.4, 0.8, 0),

        # Domain labels.
        ("FIELD INPUTS", 28.0, 28.0, 0.8, 0),
        ("LOGIC / SAFETY", 124.0, 24.0, 0.8, 0),
        ("MACHINE CONTACTS", 188.0, 28.0, 0.8, 0),

        # Top connectors.
        ("J2 5V IN", 88.0, 19.0, 0.8, 0),
        ("J1 PI", 120.0, 19.0, 0.8, 0),
        ("J14 SAFETY LOOP", 148.5, 19.0, 0.8, 0),

        # Field connectors.
        ("J3 FAST", 21.0, 33.0, 0.8, 90),
        ("J4 SLOW A", 21.0, 92.0, 0.8, 90),
        ("J5 SLOW B", 21.0, 157.0, 0.8, 90),

        # Output connectors.
        ("J6 S", 230.0, 67.0, 0.8, 0),
        ("J7 T", 230.0, 89.0, 0.8, 0),
        ("J8 SP", 229.0, 111.0, 0.8, 0),
        ("J9 BE", 229.0, 133.0, 0.8, 0),
        ("J10 M", 228.0, 155.0, 0.8, 0),
        ("J11 M2", 227.0, 177.0, 0.8, 0),
        ("J12 M1 DNP", 224.0, 199.0, 0.8, 0),
        ("J13 LED LAMPS", 124.0, 193.0, 0.8, 0),
    ]
    for args in labels:
        add_text(board, *args, layer=pcbnew.F_SilkS)


def create_board(args) -> None:
    components, nets = parse_netlist(args.netlist)
    tag_by_ref = {c.ref: c.tag for c in components}

    board = build_board_from_netlist(components, nets)
    placed, missing = place_components(board, tag_by_ref)
    if missing:
        print("WARNING: placement missing for:")
        for item in missing:
            print(f"  {item}")

    draw_board_outline(board)
    add_mounting_holes(board)
    add_test_pads(board)
    add_isolation_keepouts(board)
    add_domain_guides(board)
    add_connector_labels(board)
    add_silkscreen_labels(board)
    board.SanitizeNetcodes()

    if args.board.exists():
        if not args.force:
            raise SystemExit(f"{args.board} exists; rerun with --force to replace it.")
        backup = args.board.with_suffix(args.board.suffix + ".bak")
        shutil.copy2(args.board, backup)
        print(f"Backed up existing board to {backup}")

    pcbnew.SaveBoard(str(args.board), board)

    missing_fp = []
    for comp in components:
        lib, name = comp.footprint.split(":", 1)
        if not (FP_ROOT / f"{lib}.pretty" / f"{name}.kicad_mod").exists():
            missing_fp.append(comp.footprint)

    print(f"Wrote {args.board}")
    print(f"  components from netlist: {len(components)}")
    print(f"  nets from netlist: {len(nets)}")
    print(f"  placed footprints: {placed}")
    print(f"  mounting holes: 4")
    print(f"  test pads: 16")
    print(f"  missing footprints: {len(set(missing_fp))}")
    print(f"  board: {BOARD_W:.0f}mm x {BOARD_H:.0f}mm, 4 copper layers")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create and place WSL Phase 8 Rev-B KiCad PCB from SKiDL netlist.")
    parser.add_argument("--netlist", type=Path, default=DEFAULT_NETLIST)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--force", action="store_true", help="Replace existing board, saving a .bak copy first.")
    args = parser.parse_args(argv)

    if not args.netlist.exists():
        raise SystemExit(f"Netlist not found: {args.netlist}")
    if not FP_ROOT.exists():
        raise SystemExit(f"KiCad footprint root not found: {FP_ROOT}")

    create_board(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
