#!/usr/bin/env python3
"""
Programmatic first placement for WSL Phase 8 Rev-D.

COPY of scripts/place_components_revB.py (the rev-C placement script is SACRED
and untouched) with the rev-D deltas from docs/phase8_revD_change_spec.md:

  BOARD    - GROWN 250x225 -> 250x240 (spec C.4 fallback 3, +15 mm, the
            sanctioned last resort - PENDING DYLAN SIGN-OFF + enclosure
            re-check). The spec's 5.25 mm pitch came from a 5.2 mm courtyard
            measurement; the true KiCad 10 DIP-4_W7.62mm courtyard is 5.68 mm
            (measured via pcbnew 2026-07-19), so 40 rows need ~227 mm of
            column and CANNOT fit 225 mm at any legal pitch (fallbacks 1-2
            are arithmetically dead). See BOARD_H note for the math.
  Item B  - Pico USB clearance (Dylan's explicitly-requested fix). The Pico's
            micro-USB faces the TOP board edge and a documented keep-out
            envelope (16 mm W x 12 mm H x 40 mm from the receptacle face) is
            drawn on Dwgs_User; the cable overmold hangs off-board. DEVIATION
            FROM THE SPEC'S RECOMMENDED COORDS (spec marks them
            RECOMMENDED-VERIFY; envelope/banding/gutters are binding):
              * spec RP_PICO (92, 33, 0) puts the module courtyard
                (x 80.4-103.6) on top of the Rpu pull-up column -> REAL
                collision. Rev-D: RP_PICO (100, 33, 0), Rpu column moved
                92 -> 86, envelope x 92-108 / y 0-7.5 on-board.
              * spec J_PWR (113, 10) sits INSIDE that envelope; there is no
                16.3 mm slot left of the Pico clear of the opto column ->
                J_PWR moves RIGHT to (116, 10); D_PROT follows to (122, 20).
              * J_PI moves 126 -> 135.5 (top edge, rot 90): J2's courtyard
                (16.33 mm) does not fit between the Pico and J1's 34 mm IDC
                courtyard at the old spot. J14 follows to 167. Spec said J_PI
                unchanged - flagged as a deviation; ribbon path unaffected.
            SWD stays DROPPED (Dylan 2026-06-25) - no debug header re-added.
  Item C  - straddle column re-pitched 6.0 -> 5.7 mm (not the spec's 5.25 -
            see BOARD note), 40 rows, y 13.0-235.3; AUX4-AUX11 appended at
            the END of the input order; J15 (J_SLOWC) at (9, 222, 90) (the
            MCV pin column runs -y; the spec's (9,200) collides with J5).
            ISO_WET vacates the column head to (85, 5.7, 270): body runs -x,
            clearing the Pico courtyard, with logic pins now properly in the
            LOGIC band (better than rev-C's inverted rot-90 arrangement);
            traces cross the gutter above the keepout's top end (strip starts
            y=8). TP strip relocated to the new bottom band (y 229/236).
  Item A  - R_WET_BLEED1/2 in the FIELD band near ISO_WET / TP4 area.
  Item D  - ADC divider (R_ADC5_TOP/BOT + C_ADC5) in LOGIC, right of the Pico.
  Item E  - REDESIGNED 2026-07-21 (remediation spec R1, closes Codex C1+H1):
            four unidirectional 2N7002 tap stages. Each R_TAPIN (1M) stays at
            the OLD tap-resistor spot (within ~10 mm of its source node, so
            the long run is the high-impedance gate side and the pre-existing
            observed-net feeds in route_revD.py stay valid); the Q_TAP /
            R_TAPPU / R_TAPG cluster sits in the LOGIC band just east of the
            Pico (x 114-127, y 52-64), rows aligned to the GP16-19 drain
            corridors. No barrier crossing, no gutter incursion.
  M3      - silkscreen fab floor (remediation spec R2.4): every F.SilkS label
            >= 1.0 mm height / 0.15 mm stroke (JLC minimum); the four KEYED
            cross-mate warnings 1.2 mm / 0.20 mm stroke. Dwgs_User text is
            not fabricated and is unchanged.
  M4      - all MCV 1,5 G-3.5 connectors load from the PROJECT-LOCAL library
            kicad/wsl_footprints.pretty (suffix _D1.4: drill 1.4 mm, pad
            2.0x3.6 mm; remediation spec R2.5). System library untouched.
  Item F  - J16 (J_EXTI2C) at (128, 206, 0), LOGIC band bottom edge (spec's
            (155,206) violates 3.2 mm creepage to relay K7 - measured).
  Item G  - deferred; no MCP_OUT_B exists in the netlist.

Reads  kicad/wsl-phase8b-revD.net   (NEW rev-D netlist; never wsl-phase8b.net)
Writes kicad/revD/wsl-phase8b-revD.kicad_pcb   (NEW directory; the script
REFUSES any output path without 'revD' in it - sacred-file guard).

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\place_components_revD.py --force

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
REVD_DIR = KICAD_DIR / "revD"
DEFAULT_NETLIST = KICAD_DIR / "wsl-phase8b-revD.net"
DEFAULT_BOARD = REVD_DIR / "wsl-phase8b-revD.kicad_pcb"
FP_ROOT = Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints")
# Remediation spec R2.5 (M4): project-local footprint libraries (the system
# KiCad tree is never edited — it also serves the sacred rev-C generator).
LOCAL_FP_LIBS = {"wsl_footprints": KICAD_DIR / "wsl_footprints.pretty"}
TESTPOINT_LIB = FP_ROOT / "TestPoint.pretty"
TESTPOINT_FP = "TestPoint_Pad_1.5x1.5mm"
MOUNTING_HOLE_LIB = FP_ROOT / "MountingHole.pretty"
MOUNTING_HOLE_FP = "MountingHole_3.2mm_M3"

BOARD_W = 250.0
# Rev-D: BOARD GROWN 225 -> 240 (spec C.4 fallback 3, +15 mm, the sanctioned
# LAST resort - PENDING DYLAN SIGN-OFF + enclosure re-check per spec).
# Why: the spec's 5.25 mm pitch was computed from a 5.2 mm courtyard
# measurement, but KiCad 10's DIP-4_W7.62mm courtyard is actually 5.68 mm
# tall (-1.565..+4.115) - measured 2026-07-19 via pcbnew. 40 rows therefore
# need >= 40 x 5.68 = 227.2 mm of column: fallback 1 (5.3-5.4 pitch) cannot
# fit on 225 mm, and fallback 2 (move lamp drivers) cannot shorten the single
# mandatory straddle column. 250x240 at 5.7 mm pitch is the minimal clean fit.
BOARD_H = 240.0
FIELD_LOGIC_GUTTER = (76.8, 80.0)
LOGIC_MACHINE_GUTTER = (181.0, 184.2)

# Rev-D straddle column: 40 rows. Spec C.4 said 5.25 mm pitch / y0=14.0, but
# the true DIP-4 courtyard is 5.68 mm (see BOARD_H note) -> pitch 5.7 mm,
# y0=13.0, rows y 13.0..235.3 (last courtyard bottom 239.4 < 240).
INPUT_COL_Y0 = 13.0
INPUT_PITCH = 5.7
OPTO_X = 74.0   # unchanged - field pads left of the gutter, logic pads right
RIN_X = 58.0    # unchanged
# Rpu column moved 92 -> 86: at x=92 it ran the full column height directly
# under any Pico position wide enough to clear J2/J1 on the top edge (Pico
# courtyard is 23.16 mm wide). 86 keeps it clear of the gutter (80) and of
# the opto courtyard (right edge 82.72).
RPU_X = 86.0

# Item B keep-out envelope (spec B): 16 W x 12 H x 40 mm from the receptacle
# face. With the Pico at (100, 33, 0) the receptacle face is at the module's
# top edge y=7.5, plug axis toward -y, so only y 0..7.5 of the envelope is
# on-board; the remaining ~32.5 mm (cable body + strain relief) hangs off the
# top board edge. Envelope x-span: 100 +/- 8.
USB_ENVELOPE = (92.0, 0.0, 108.0, 7.5)

FAST_INPUTS = ["SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R"]
SLOW_A = [f"GS{i}" for i in range(1, 11)] + ["GP", "OS", "BS"]
SLOW_B = ["PBZ", "PBC", "FOUL", "TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "AUX1", "AUX2", "AUX3"]
SLOW_C = [f"AUX{i}" for i in range(4, 12)]  # rev-D item C: IN-B GPB bank
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
    lib_dir = LOCAL_FP_LIBS.get(lib, FP_ROOT / f"{lib}.pretty")
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
        # Edge connectors. Top-edge packing is courtyard-exact (measured via
        # pcbnew 2026-07-19): opto column crtyd right 82.72 | Rpu col 84.5-87.5
        # | Pico crtyd 88.4-111.6 (envelope x 92-108 fully inside) | J2 crtyd
        # 112.9-129.25 | J1 crtyd 129.9-164.0 | J14 crtyd 164.0-180.5.
        # Item B: J_PWR moved RIGHT of the Pico (spec's (113,10) sits inside
        # the shifted USB envelope; left of the Pico there is no 16.3 mm slot
        # clear of the opto column). J_PI moved +9.5 mm right (spec said
        # unchanged, but J2's displacement forces it; still top edge, ribbon
        # path unaffected, USB envelope untouched). J14 follows to 167.
        "J_PWR": (116, 10, 0),
        "J_SAFE": (167, 10, 0),
        "J_PI": (135.5, 10, 90),
        "J_FAST": (9, 42, 90),
        "J_SLOWA": (9, 103, 90),
        "J_SLOWB": (9, 168, 90),
        "J_LAMP": (104, 206, 0),
        # Item C: new field connector for AUX4-11. Spec sketched (9,200,90)
        # but the MCV pin column runs -y from the origin (measured: J15 at
        # origin y=200 spans y 165.5-203 and collides with J5 at 126.5-171);
        # origin y=222 spans y 187.5-225, adjacent to the AUX rows (195.4+).
        "J_SLOWC": (9, 222, 90),
        # Item F: expansion header, LOGIC bottom edge. Spec sketched (155,206)
        # but that puts pad 6 1.35 mm from relay K7's pads (3.2 mm
        # LOGIC-MACHINE creepage violation). 128 slots the 23.5 mm courtyard
        # (origin-3..+20.5) exactly between J13 (crtyd to 124.5) and the M1
        # driver ladder Rpd_M1 at (150,203) (crtyd from 149.2), 28 mm to K7.
        "J_EXTI2C": (128, 206, 0),

        # Logic/control spine.
        # Item B: USB faces the TOP edge; see module docstring for the
        # deviation from the spec's recommended (92,33) (Rpu-column collision).
        "RP_PICO": (100, 33, 0),
        "MCP_IN_A": (122, 104, 0),
        "MCP_IN_B": (122, 146, 0),
        "MCP_OUT_A": (140, 112, 0),
        # Item C consequence: ISO_WET vacates the column head (rev-C spot
        # (73.9,13,90) collides with row 0). Rot 270 with origin x=85: body
        # runs -x (courtyard x 67.3-87.4, y 2.9-9.6), clearing the Pico
        # courtyard (from 88.42) and Rin/opto row 0 (crtyd from ~10.5) - and
        # unlike the rev-C rot-90 arrangement the LOGIC pins (pads 1/2 =
        # VCC_5V/GND at x 85/82.5) now sit in the LOGIC band with the FIELD
        # pins (pads 3/4) toward the gutter. Gutter crossings happen inside
        # the package / above the keepout strip's top end (strip starts y=8).
        "ISO_WET": (85, 5.7, 270),
        "D_PROT": (122, 20, 0),
        "C_3V3_BULK": (140, 78, 0),
        "R_I2C_SDA": (103, 86, 90),
        "R_I2C_SCL": (110, 86, 90),

        # Item A: FIELD_WET_V bleed pair (FIELD band, near ISO_WET secondary /
        # the TP4 net, clear of the re-pitched Rin column at x=58).
        "R_WET_BLEED1": (63, 16, 90),
        "R_WET_BLEED2": (67, 16, 90),

        # Item D: VCC_5V ADC divider - LOGIC band, right of the moved Pico
        # (Pico crtyd right edge 111.6), short run to GP26 (pin 31).
        "R_ADC5_TOP": (114, 41, 90),
        "R_ADC5_BOT": (114, 47, 90),
        "C_ADC5": (117, 44, 90),

        # Item E (remediation spec R1, 2026-07-21): unidirectional tap
        # stages. R_TAPIN (1M) keeps the OLD tap-resistor position — pad 1
        # sits on the identical observed-net feed point already routed in
        # route_revD.py (route_watchdog / route_header_safety), pad 2 now
        # feeds the TAP_GATE_* run instead of the GPIO directly. The gate
        # side is the long, high-impedance run by design (spec R1.7).
        "R_TAPIN_555": (146, 33, 0),    # NE555_OUT source at U_WDOG (151,50)
        "R_TAPIN_KICK": (136, 47, 90),  # WDOG_KICK source at kick gate (142,47)
        "R_TAPIN_ARM": (130, 70, 90),   # ARM_PERMIT run J1 -> Rb_AND_ARM (133,90)
        "R_TAPIN_RPOK": (156, 64, 0),   # RP2040_OK near Q_WDOG_OK (162,58)
        # Q/R_TAPPU/R_TAPG cluster east of the Pico, one row per tap, rows
        # matched to the GP16-19 drain corridors (all LOGIC band; Pico
        # courtyard right edge is 111.6, MCP_IN_A courtyard starts ~113 at
        # y >= 96 — this block sits y 52-64). Q rot 180 puts the drain
        # (pad 3) toward the Pico and gate (pad 1) toward the sources.
        "Q_TAP_555": (116, 52, 180),
        "R_TAPPU_555": (120.5, 52, 180),   # pad2 (west) = drain net
        "Q_TAP_KICK": (116, 56, 180),
        "R_TAPPU_KICK": (120.5, 56, 180),
        "R_TAPG_KICK": (125, 56, 0),       # rot 0: pad1 (gate) west, pad2 (GND zone) east
        "Q_TAP_ARM": (116, 60, 180),
        "R_TAPPU_ARM": (120.5, 60, 180),
        "R_TAPG_ARM": (125, 60, 0),
        "Q_TAP_RPOK": (116, 64, 180),
        "R_TAPPU_RPOK": (120.5, 64, 180),
        "R_TAPG_RPOK": (125, 64, 0),

        # Watchdog and safety rail (unchanged from rev-C).
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
    # Rev-D: 40 rows at 5.7 mm pitch starting y=13.0 (rows y 13.0 .. 235.3);
    # see the BOARD_H/INPUT_PITCH notes for why not the spec's 5.25/225.
    input_order = FAST_INPUTS + SLOW_A + SLOW_B + SLOW_C
    assert len(input_order) == 40, f"expected 40 input channels, got {len(input_order)}"
    for i, name in enumerate(input_order):
        y = INPUT_COL_Y0 + i * INPUT_PITCH
        p[f"OPTO_{name}"] = (OPTO_X, y, 0)
        p[f"Rin_{name}"] = (RIN_X, y - 1.8, 0)
        p[f"Rpu_{name}"] = (RPU_X, y + 1.8, 0)

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
    # Rev-D: SAME 16 test pads / nets as rev-C (identical membership - the
    # audit freezes SAFE_/rail pad counts at the rev-C pattern), but the strip
    # is RELOCATED (spec C.4): the re-pitched input column now reaches
    # y=235.3 at x 56-88, so the strip moves to the grown board's bottom band
    # (y 229/236) at x >= 100. TP4/TP5 keep FIELD-band x (22/34).
    pads = [
        ("TP4", "FIELD_WET_V", 22, 229),
        ("TP5", "FIELD_GND", 34, 229),
        ("TP1", "VCC_5V", 100, 229),
        ("TP2", "GND", 110, 229),
        ("TP3", "VCC_3V3", 120, 229),
        ("TP6", "I2C_SDA", 130, 229),
        ("TP7", "I2C_SCL", 140, 229),
        ("TP8", "WDOG_KICK", 150, 229),
        ("TP9", "WDOG_TIMING_NODE", 100, 236),
        ("TP10", "NE555_TRIG", 110, 236),
        ("TP11", "NE555_OUT", 120, 236),
        ("TP12", "WDOG_OK_PULLDOWN", 128, 236),
        ("TP13", "ARM_PERMIT", 136, 236),
        ("TP14", "RP2040_OK", 144, 236),
        ("TP15", "SAFE_STOP_RETURN", 152, 236),
        ("TP16", "RELAY_ENABLE_RAIL", 160, 236),
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


def add_text(board: pcbnew.BOARD, text: str, x: float, y: float, size=1.0, rot=0, layer=None, thickness=0.15) -> None:
    # Remediation spec R2.4 (M3): fabricated silk must meet JLC's published
    # floor of 1.0 mm height / 0.15 mm stroke — enforce it here so no call
    # site can regress a F.SilkS label below the fab minimum.
    if (layer is None or layer == pcbnew.F_SilkS or layer == pcbnew.B_SilkS):
        size = max(size, 1.0)
        thickness = max(thickness, 0.15)
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetLayer(layer if layer is not None else pcbnew.F_SilkS)
    item.SetPosition(mm(x, y))
    item.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    item.SetTextThickness(pcbnew.FromMM(thickness))
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
    # Rev-D: strip starts at y=8 (ISO_WET now sits at y=4.4; its logic-side
    # routing passes over the strip's top end, as in rev-C) and extends to
    # y=239 to cover the re-pitched 40-row column (last courtyard ~239.4).
    add_keepout(board, "NO COPPER FIELD/LOGIC", FIELD_LOGIC_GUTTER[0], 8, FIELD_LOGIC_GUTTER[1], 239)

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
    if y < 231.0:
        # Rev-D: tail extended 216 -> 231 for the grown board (no machine
        # parts below the M1 row, but the strip should span the band).
        add_keepout(board, "NO COPPER LOGIC/MACHINE", LOGIC_MACHINE_GUTTER[0], y, LOGIC_MACHINE_GUTTER[1], 231)


def add_usb_keepout_drawing(board: pcbnew.BOARD) -> None:
    # Item B (spec): document the USB cable envelope on Dwgs_User.
    # Full envelope: 16 mm W x 12 mm H x 40 mm from the receptacle face along
    # the plug axis (-y). On-board portion only (y 0..7.5); the rest hangs off
    # the top board edge, which is the point of the top-edge orientation.
    x1, y1, x2, y2 = USB_ENVELOPE
    add_rect(board, x1, y1, x2, y2, pcbnew.Dwgs_User, 0.15)
    add_text(board, "USB CABLE KEEP-OUT 16Wx12H", (x1 + x2) / 2, 2.2, 0.7, 0, pcbnew.Dwgs_User)
    add_text(board, "ENVELOPE EXTENDS 40mm OFF-BOARD", (x1 + x2) / 2, 4.4, 0.7, 0, pcbnew.Dwgs_User)
    add_text(board, "NO PART / RIBBON / WALL IN PATH", (x1 + x2) / 2, 6.4, 0.7, 0, pcbnew.Dwgs_User)


def add_domain_guides(board: pcbnew.BOARD) -> None:
    # Rev-D: FIELD guide extended for the longer input column on the grown
    # board; labels moved to the very bottom edge.
    add_rect(board, 6, 8, FIELD_LOGIC_GUTTER[0], 239, pcbnew.Dwgs_User)
    add_rect(board, FIELD_LOGIC_GUTTER[1], 8, LOGIC_MACHINE_GUTTER[0], 232, pcbnew.Dwgs_User)
    add_rect(board, LOGIC_MACHINE_GUTTER[1], 20, 246, 232, pcbnew.Dwgs_User)
    add_text(board, "FIELD INPUT / ISOLATED WETTING", 12, 238.6, 0.8, 0, pcbnew.Dwgs_User)
    add_text(board, "LOGIC / SAFETY / WATCHDOG", 82, 238.6, 0.8, 0, pcbnew.Dwgs_User)
    add_text(board, "MACHINE OUTPUTS", 187, 233.5, 0.8, 0, pcbnew.Dwgs_User)


def add_connector_labels(board: pcbnew.BOARD) -> None:
    labels = [
        ("5V IN", 116, 20, 0.8, 0),
        ("SAFETY", 167, 20, 0.8, 0),
        ("PI LINK", 140, 20, 0.8, 0),
        ("FAST", 22, 42, 0.8, 90),
        ("SLOW A", 22, 103, 0.8, 90),
        ("SLOW B", 22, 168, 0.8, 90),
        ("SLOW C", 22, 212, 0.8, 90),
        ("MOTION", 232, 110, 0.8, 90),
        ("LAMPS", 232, 180, 0.8, 90),
        ("EXT I2C", 134, 216.5, 0.8, 0),
        ("M1 DNP", 191, 220, 0.8, 0),
    ]
    for args in labels:
        add_text(board, *args, layer=pcbnew.Dwgs_User)


def add_silkscreen_labels(board: pcbnew.BOARD) -> None:
    # Remediation spec R2.4 (M3): every fabricated F.SilkS label >= 1.0 mm
    # height / 0.15 mm stroke (JLC published minimum; below it JLC auto-widens
    # strokes and the text smears). The four KEYED cross-mate warnings are the
    # safety-relevant ones: 1.2 mm / 0.20 mm stroke for extra margin.
    labels = [
        # Board identity / order sanity.
        ("WSL LANE NODE PHASE 8B REV-D", 210.0, 42.0, 1.0, 0),
        ("4L 250x240  INPUTS LEFT  OUTPUTS RIGHT", 210.0, 45.4, 1.0, 0),

        # Domain labels.
        ("FIELD INPUTS", 28.0, 28.0, 1.0, 0),
        ("LOGIC / SAFETY", 124.0, 26.0, 1.0, 0),
        ("MACHINE CONTACTS", 188.0, 28.0, 1.0, 0),

        # Top connectors.
        ("J2 5V IN", 116.0, 17.5, 1.0, 0),
        ("J1 PI", 135.5, 16.5, 1.0, 0),
        ("J14 SAFETY LOOP", 167.0, 16.5, 1.0, 0),

        # Field connectors.
        ("J3 FAST", 21.0, 33.0, 1.0, 90),
        ("J4 SLOW A", 21.0, 92.0, 1.0, 90),
        ("J5 SLOW B", 21.0, 157.0, 1.0, 90),
        ("J15 SLOW C", 21.0, 204.0, 1.0, 90),

        # Output connectors.
        ("J6 S", 230.0, 67.0, 1.0, 0),
        ("J7 T", 230.0, 89.0, 1.0, 0),
        ("J8 SP", 229.0, 111.0, 1.0, 0),
        ("J9 BE", 229.0, 133.0, 1.0, 0),
        ("J10 M", 228.0, 155.0, 1.0, 0),
        ("J11 M2", 227.0, 177.0, 1.0, 0),
        # (moved off Rsnub_M1's pad after the 0.8 -> 1.0 mm M3 growth)
        ("J12 M1 DNP", 227.5, 200.5, 1.0, 0),
        ("J13 LED LAMPS", 112.0, 213.0, 1.0, 0),
        ("J16 EXT I2C", 136.0, 213.0, 1.0, 0),
    ]
    for args in labels:
        add_text(board, *args, layer=pcbnew.F_SilkS)

    # Cross-mate guards (review finding 2026-07-20, gate OG-3): J15 shares
    # its mating plug PN (1840447) with J3, and J16 shares its plug PN
    # (1840405) with J13 on the same edge — CP-MSTB 1734634 coding keys at
    # different pole positions are the real fix (harness BOM); the silk
    # names the hazard at both ends of each pair. 1.2 mm / 0.20 mm stroke
    # (remediation spec R2.4), positions nudged for the taller text.
    keyed = [
        ("KEYED: NOT J15", 25.0, 48.0, 90),   # below 'FIELD INPUTS' silk
        ("KEYED: NOT J3", 25.0, 204.0, 90),
        ("KEYED: NOT J16", 112.0, 218.0, 0),
        ("KEYED: NOT J13 LAMP", 138.0, 218.0, 0),
    ]
    for text, x, y, rot in keyed:
        add_text(board, text, x, y, 1.2, rot, layer=pcbnew.F_SilkS, thickness=0.20)


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
    add_usb_keepout_drawing(board)
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
        lib_dir = LOCAL_FP_LIBS.get(lib, FP_ROOT / f"{lib}.pretty")
        if not (lib_dir / f"{name}.kicad_mod").exists():
            missing_fp.append(comp.footprint)

    print(f"Wrote {args.board}")
    print(f"  components from netlist: {len(components)}")
    print(f"  nets from netlist: {len(nets)}")
    print(f"  placed footprints: {placed}")
    print(f"  mounting holes: 4")
    print(f"  test pads: 16")
    print(f"  missing footprints: {len(set(missing_fp))}")
    print(f"  board: {BOARD_W:.0f}mm x {BOARD_H:.0f}mm, 4 copper layers")
    print()
    print("  *** OPEN GATE OG-1 (spec C.4 fallback 3): board GROWN 250x225 -> "
          f"250x{BOARD_H:.0f} — PENDING DYLAN SIGN-OFF + enclosure re-check. ***")
    print("  *** phase8_pair_enclosure_spec.md panel math assumes 225 mm and the "
          "bottom mounting holes moved to y=236: do NOT treat routing (step I.5) "
          "as fab-gating, and do NOT order enclosures/backplates, until the "
          "sign-off is recorded in docs/phase8_revD_run_log.md. ***")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create and place WSL Phase 8 Rev-D KiCad PCB from the rev-D SKiDL netlist.")
    parser.add_argument("--netlist", type=Path, default=DEFAULT_NETLIST)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--force", action="store_true", help="Replace existing board, saving a .bak copy first.")
    args = parser.parse_args(argv)

    # Sacred-file guard: this script must never be able to touch a rev-B/rev-C
    # artifact. Both the netlist it reads and the board it writes must be
    # revD-named, and the board must live inside kicad/revD/.
    if "revD" not in args.netlist.name:
        raise SystemExit(f"REFUSING: netlist {args.netlist} is not a revD netlist (sacred-file guard).")
    if "revD" not in args.board.name:
        raise SystemExit(f"REFUSING: board {args.board} is not revD-named (sacred-file guard).")
    if "revD" not in str(args.board.resolve().parent):
        raise SystemExit(f"REFUSING: board output dir {args.board.resolve().parent} is not a revD directory (sacred-file guard).")
    args.board.resolve().parent.mkdir(parents=True, exist_ok=True)

    if not args.netlist.exists():
        raise SystemExit(f"Netlist not found: {args.netlist}")
    if not FP_ROOT.exists():
        raise SystemExit(f"KiCad footprint root not found: {FP_ROOT}")

    create_board(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
