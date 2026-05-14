#!/usr/bin/env python3
"""
Programmatic component placement for WSL Phase 8a PCB.

Reads wsl-phase8a.kicad_pcb, positions all 41 components on a 100x100mm
board per the layout dict below, draws the Edge.Cuts board outline, and
saves. Replaces manual placement entirely.

MUST be run from KiCad's bundled Python (has pcbnew module):
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" place_components.py

Coords are in mm. Board origin (0,0) = top-left corner, X right, Y down.

Rotation convention (verified empirically; adjust if Phoenix terminals
end up flipped relative to board edge in KiCad):
  0    = default orientation
  90   = rotate counter-clockwise 90 degrees
  180  = upside-down relative to default
  270  = rotate clockwise 90 degrees (or 270 CCW)

CLOSE KiCad before running this script — the .kicad_pcb file is locked
while KiCad has it open.
"""

import os
import sys
import pcbnew

KICAD_PCB = r"C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\wsl-phase8a.kicad_pcb"

BOARD_WIDTH_MM = 100
BOARD_HEIGHT_MM = 100

# Layout v2: refdes -> (x_mm, y_mm, rotation_degrees)
#
# Key insight: align each AC channel's components vertically with its
# top (DC OUT) and bottom (AC IN) terminals. Channel N components live
# in the x=20/40/60/80 column above the watchdog, so each channel's
# DC_POS and CH_RETURN traces run as clean vertical strokes from
# J(7+N) at the top down through D, C, R to J(3+N) at the bottom.
# Watchdog cluster occupies the lower half (y=55-80) in the gaps
# BETWEEN channel columns, so channel return traces (vertical at x=20,
# 40, 60, 80) pass through the watchdog zone without hitting parts.
#
# Zones:
#   Top edge (y~8):       J8-J11 (DC OUT, channels 1-4 left to right)
#   Bottom edge (y~92):   J4-J7  (24VAC IN, channels 1-4 left to right)
#   Left edge (x~8):      J1, J2, J3 (TB_PWR_IN, TB_AEDIKO_PWR, TB_KICK)
#   Upper interior:       4 AC channel columns at x=20, 40, 60, 80
#   Lower interior:       Watchdog (U1, Q1/Q2, D1/D2, C1-C3, R1-R8, LEDs)
PLACEMENT = {
    # ---- Top edge: DC OUT terminals
    'J8':  (20, 8, 0),     # Channel 1
    'J9':  (40, 8, 0),     # Channel 2
    'J10': (60, 8, 0),     # Channel 3
    'J11': (80, 8, 0),     # Channel 4

    # ---- Bottom edge: 24VAC IN terminals (180° rotation: screws face down)
    'J4':  (20, 92, 180),  # Channel 1
    'J5':  (40, 92, 180),  # Channel 2
    'J6':  (60, 92, 180),  # Channel 3
    'J7':  (80, 92, 180),  # Channel 4

    # ---- Left edge: Power terminals (90° rotation: screws face left)
    'J1':  (8, 22, 90),    # TB_PWR_IN  (top)
    'J2':  (8, 45, 90),    # TB_AEDIKO_PWR (middle)
    'J3':  (8, 78, 90),    # TB_KICK  (bottom)

    # ---- D_PROT: reverse-polarity Schottky.
    # SKiDL assigns refdes D9 (defined last among diode-prefix parts).
    # Originally placed at (15, 22) immediately right of J1, but that
    # caused courtyard overlaps with both J1 (body extends to x=12) AND
    # channel 1 D3 at x=20. Moved DOWN to (10, 35) — in the gap between
    # J1 (y=22) and J2 (y=45), at x=10 which is OUTSIDE the B.Cu keepout
    # zone (gap_J1_to_ch1 starts at x=14). VCC_5V_RAW trace is ~13mm
    # diagonal from J1.1 — still short and clean.
    # Rotation 180: A on LEFT toward J1 side, K on RIGHT toward VCC_5V loads.
    'D9':  (10, 35, 180),  # SS14 Schottky

    # ---- AC interposer channels: 4 vertical columns aligned with terminals
    # All rotated 90° so pads run TOP/BOTTOM (in line with the vertical
    # column traces) instead of LEFT/RIGHT. K (cathode, pin 1) ends up at
    # top toward DC_OUT, A (anode) at bottom toward AC_IN. + side of cap
    # at top toward DC_POS, - at bottom toward CH_RETURN.
    # Channel 1 (x=20, below J8)
    'D3':  (20, 18, 90),   # M7 rectifier, vertical, K up toward J8
    'C4':  (20, 30, 90),   # 10uF smoothing, + up toward DC_POS
    'R9':  (20, 42, 90),   # 100k bleeder, pads aligned to column trace
    # Channel 2 (x=40, below J9)
    'D4':  (40, 18, 90),
    'C5':  (40, 30, 90),
    'R10': (40, 42, 90),
    # Channel 3 (x=60, below J10)
    'D5':  (60, 18, 90),
    'C6':  (60, 30, 90),
    'R11': (60, 42, 90),
    # Channel 4 (x=80, below J11)
    'D6':  (80, 18, 90),
    'C7':  (80, 30, 90),
    'R12': (80, 42, 90),

    # ---- Watchdog cluster (y=55-80, fills the gaps between channel columns)
    # Critical clearance check: channel return traces run vertically at
    # x=20, 40, 60, 80 from y=42 down to y=92. Watchdog parts MUST sit
    # in the x-gaps (x≈10, 28, 48, 70) to avoid blocking these traces.

    'U1':  (32, 66, 0),    # NE555 (moved down 1mm for C1 courtyard clearance)

    # D1/D2 rotated 180 so anode (pin 2) faces U1 left side (TIMING_NODE/TRIG),
    # cathode (pin 1) faces Q1 right side (Q1_DRAIN). Shortens the critical
    # noise-sensitive TIMING_NODE and NE555_TRIG traces.
    'D1':  (45, 62, 180),  # 1N4148WS D1 (A toward U1 TIMING_NODE, K toward Q1_DRAIN)
    'D2':  (45, 68, 180),  # 1N4148WS D2 (A toward U1 TRIG, K toward Q1_DRAIN)

    'Q1':  (52, 60, 0),    # AO3400 Q1 discharge (between ch2 and ch3 cols)
    'Q2':  (52, 70, 0),    # AO3400 Q2 output

    # Per Codex rev A audit: tighten timing network around U1 pins 6/7/5/8.
    # Pin layout (rotation 0): VCC=pin8 top-left, CTRL=pin5 top-right, THRES=pin6
    # top-mid-right, DISCH=pin7 top-mid-left, TRIG=pin2 bottom-mid-left.
    'C1':  (30, 58, 0),    # 100uF timing — directly above U1.7/U1.6 (THRES/DISCH)
    # C2 was at (28, 65) but pad 2 (GND, at x=28.95) was 0.7mm from U1 pin 2
    # (TRIG, at x=29.525) — DRC short violation. Pushed left 4mm to clear.
    'C2':  (24, 65, 0),    # 0.1uF VCC bypass — left of U1.8 (VCC) and U1.1 (GND)
    'C3':  (37, 60, 0),    # 10nF CTRL filter — right of U1.5 (CTRL)

    'R1':  (32, 52, 0),    # 100k timing pullup — directly above C1, short TIMING_NODE
    'R2':  (25, 67, 0),    # 10k TRIG pullup — left of U1.2 (TRIG, bottom-mid-left)

    'R3':  (48, 55, 0),    # 1k Q1 gate series
    'R4':  (48, 60, 0),    # 10k Q1 gate pulldown
    'R5':  (48, 70, 0),    # 1k Q2 gate series (Python R6 in script)
    'R6':  (48, 75, 0),    # 10k Q2 gate pulldown (Python R7)

    'R7':  (72, 60, 0),    # 470 LED1 current limit (right-side gap, ch3-ch4)
    'R8':  (72, 70, 0),    # 470 LED2 current limit
    'D7':  (76, 60, 0),    # LED1 (watchdog-healthy indicator)
    'D8':  (76, 70, 0),    # LED2 (power-good indicator)
}


def place_components(board):
    """Walk all footprints in the board, position those in PLACEMENT."""
    placed = 0
    missing = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in PLACEMENT:
            x, y, rot = PLACEMENT[ref]
            fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
            fp.SetOrientationDegrees(rot)
            placed += 1
        else:
            missing.append(ref)
    return placed, missing


MOUNTING_HOLE_POSITIONS = [
    (3.5, 3.5),    # top-left
    (96.5, 3.5),   # top-right
    (3.5, 96.5),   # bottom-left
    (96.5, 96.5),  # bottom-right
]

MOUNTING_HOLE_LIB = r"C:\Program Files\KiCad\10.0\share\kicad\footprints\MountingHole.pretty"
MOUNTING_HOLE_NAME = "MountingHole_3.2mm_M3"


def add_mounting_holes(board, positions):
    """Add M3 mounting holes (3.2mm NPTH) at the given (x,y) positions.

    Removes any existing MountingHole-prefixed footprints first so the
    script is idempotent.
    """
    # Remove existing mounting holes (idempotency)
    existing = [fp for fp in board.GetFootprints()
                if fp.GetReference().startswith('MK')]
    for fp in existing:
        board.Remove(fp)

    added = 0
    for i, (x, y) in enumerate(positions, start=1):
        try:
            fp = pcbnew.FootprintLoad(MOUNTING_HOLE_LIB, MOUNTING_HOLE_NAME)
        except Exception as e:
            print(f"  Could not load mounting hole footprint: {e}")
            return added
        if fp is None:
            print(f"  FootprintLoad returned None for mounting hole {i}")
            continue
        fp.SetReference(f"MK{i}")
        fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        board.Add(fp)
        added += 1
    return added


# ----------------------------------------------------------------------
# B.Cu keepout zones in gap areas between AC channel columns (per Codex
# rev A pass-4 audit). AC channels are at x=20, 40, 60, 80. Adding
# bottom-layer keepouts in the gaps forces FreeRouting to keep AC return
# nets within their channel columns rather than running them across the
# board on B.Cu. F.Cu unaffected, so watchdog routes are not blocked.
# ----------------------------------------------------------------------

BCU_KEEPOUT_GAPS = [
    # (x_min, x_max, name)
    (14, 18, 'gap_J1_to_ch1'),    # left edge: between J1-J3 column and ch1
    (23, 37, 'gap_ch1_to_ch2'),
    (43, 57, 'gap_ch2_to_ch3'),
    (63, 77, 'gap_ch3_to_ch4'),
    (83, 92, 'gap_ch4_to_right'), # right edge
]
KEEPOUT_Y_MIN = 5
KEEPOUT_Y_MAX = 95


def add_bcu_keepouts(board, gaps):
    """Add B.Cu Rule Areas in the named gap zones. Idempotent."""
    # Remove any existing rule areas from previous runs
    to_remove = []
    for zone in board.Zones():
        try:
            if zone.GetIsRuleArea():
                to_remove.append(zone)
        except AttributeError:
            continue
    for zone in to_remove:
        board.Remove(zone)

    added = 0
    for x_min, x_max, _name in gaps:
        zone = pcbnew.ZONE(board)
        zone.SetLayer(pcbnew.B_Cu)
        zone.SetIsRuleArea(True)
        zone.SetDoNotAllowTracks(True)
        zone.SetDoNotAllowVias(True)
        # KiCad 10 renamed CopperPour -> ZoneFills
        if hasattr(zone, 'SetDoNotAllowZoneFills'):
            zone.SetDoNotAllowZoneFills(True)
        # Pads/footprints aren't expected in these zones anyway
        zone.SetDoNotAllowPads(False)
        zone.SetDoNotAllowFootprints(False)

        # 4-corner rectangle outline
        zone.AppendCorner(pcbnew.VECTOR2I_MM(x_min, KEEPOUT_Y_MIN), 0)
        zone.AppendCorner(pcbnew.VECTOR2I_MM(x_max, KEEPOUT_Y_MIN), 0)
        zone.AppendCorner(pcbnew.VECTOR2I_MM(x_max, KEEPOUT_Y_MAX), 0)
        zone.AppendCorner(pcbnew.VECTOR2I_MM(x_min, KEEPOUT_Y_MAX), 0)
        # Polygon auto-closes; no explicit Fix() needed in KiCad 10 API

        board.Add(zone)
        added += 1
    return added


# ----------------------------------------------------------------------
# Test pads (per Codex rev A audit) — single SMD pad per net, exposed copper
# for probing. 14 pads total: 6 critical watchdog nets + 8 per-channel
# (DC_POS + RETURN per AC channel).
# ----------------------------------------------------------------------

TEST_PADS = [
    # (ref, net_name, x_mm, y_mm)
    ('TP1',  'VCC_5V',          25, 22),   # near J1 +5V (post-D_PROT)
    ('TP2',  'GND',             25, 28),   # near J1 GND
    ('TP3',  'KICK',            18, 80),   # near J3
    ('TP4',  'TIMING_NODE',      6, 60),   # near C1
    ('TP5',  'NE555_OUT',       40, 65),   # right of U1
    ('TP6',  'COIL_GND_RETURN', 58, 70),   # near Q2.D
    # Per-channel: DC_POS and RETURN test points.
    # Moved to y=48 (was y=36) — y=36 put them too close to D9/J2 in the
    # upper-left area. y=48 is the clean gap between AC bleeders (y=42)
    # and watchdog components (y=55+). x-positions split between channel
    # columns and gap centers for clean trace stubs.
    ('TP7',  'DC_CH1_POS',      15, 48),   ('TP8',  'CH1_RETURN', 25, 48),
    ('TP9',  'DC_CH2_POS',      35, 48),   ('TP10', 'CH2_RETURN', 45, 48),
    ('TP11', 'DC_CH3_POS',      55, 48),   ('TP12', 'CH3_RETURN', 65, 48),
    ('TP13', 'DC_CH4_POS',      75, 48),   ('TP14', 'CH4_RETURN', 85, 48),
]


TESTPOINT_LIB = r"C:\Program Files\KiCad\10.0\share\kicad\footprints\TestPoint.pretty"
TESTPOINT_FP = "TestPoint_Pad_1.5x1.5mm"


def create_test_pad(board, ref, net_name, x, y):
    """Load the standard KiCad TestPoint footprint, place at (x,y), tie to net.

    Earlier attempts built the footprint by hand with SetFPID('custom:...').
    KiCad's DSN export drops FPIDs that don't resolve to a real library,
    leaving '(image "")' which crashes the .ses re-import. Loading a real
    library footprint avoids this entirely.
    """
    fp = pcbnew.FootprintLoad(TESTPOINT_LIB, TESTPOINT_FP)
    if fp is None:
        raise RuntimeError(f"Could not load TestPoint footprint from {TESTPOINT_LIB}")
    fp.SetReference(ref)
    fp.SetValue(net_name)
    fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
    # FootprintLoad sets the FPID without the library prefix. Restore the
    # full "TestPoint:..." form so DSN export gets a valid image_id.
    fp.SetFPID(pcbnew.LIB_ID("TestPoint", TESTPOINT_FP))

    # The loaded TestPoint footprint already has its pad. Just wire it up.
    net = board.FindNet(net_name)
    if net is None:
        print(f"  WARN: net '{net_name}' not found for {ref}")
    else:
        for pad in fp.Pads():
            pad.SetNet(net)

    board.Add(fp)


def add_test_pads(board, test_pads):
    """Add test pads to the board. Removes existing TP* footprints first.

    KiCad's SWIG bindings can return SwigPyObjects without proper FOOTPRINT
    methods after manipulations earlier in the same session. Use try/except
    to skip those gracefully.
    """
    to_remove = []
    for fp in board.GetFootprints():
        try:
            if fp.GetReference().startswith('TP'):
                to_remove.append(fp)
        except AttributeError:
            continue  # SwigPyObject without GetReference — skip
    for fp in to_remove:
        board.Remove(fp)

    for ref, net_name, x, y in test_pads:
        create_test_pad(board, ref, net_name, x, y)
    return len(test_pads)


# ----------------------------------------------------------------------
# Silkscreen field labels (per Codex rev A audit) — readable text on
# F.Silkscreen so a field installer can wire the board without the spec
# doc in hand.
# ----------------------------------------------------------------------

SILKSCREEN_LABELS = [
    # (text, x_mm, y_mm, size_mm, rotation_deg)
    # Polish pass: consolidate per-pin labels into single per-channel
    # labels to clear 22 silkscreen DRC warnings. Pad numbers (1/2) on
    # the terminal footprint outlines already identify polarity.

    # Power terminals (left edge) — single label per terminal, placed
    # just to the RIGHT of each so they don't overlap J1-J3 bodies.
    ('+5V/GND',     17, 22, 0.9, 0),   # next to J1
    ('AEDIKO',      17, 45, 0.9, 0),   # next to J2
    ('KICK/GND',    17, 78, 0.9, 0),   # next to J3

    # DC OUT terminals (top edge) — one label per channel, centered above
    ('CH1 DC',  20, 15, 1.0, 0),
    ('CH2 DC',  40, 15, 1.0, 0),
    ('CH3 DC',  60, 15, 1.0, 0),
    ('CH4 DC',  80, 15, 1.0, 0),

    # AC IN terminals (bottom edge) — one label per channel
    ('CH1 24VAC', 20, 85, 0.9, 0),
    ('CH2 24VAC', 40, 85, 0.9, 0),
    ('CH3 24VAC', 60, 85, 0.9, 0),
    ('CH4 24VAC', 80, 85, 0.9, 0),

    # Indicator LEDs (right side of watchdog)
    ('WD',  82, 60, 1.0, 0),   # watchdog-healthy
    ('PWR', 82, 70, 1.0, 0),   # power-good
]


def add_silkscreen_labels(board, labels):
    """Add silkscreen text items to F.Silkscreen layer."""
    for text, x, y, size, rot in labels:
        item = pcbnew.PCB_TEXT(board)
        item.SetText(text)
        item.SetLayer(pcbnew.F_SilkS)
        item.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        item.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size),
                                          pcbnew.FromMM(size)))
        item.SetTextThickness(pcbnew.FromMM(0.15))
        try:
            item.SetTextAngle(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
        except Exception:
            item.SetTextAngle(rot * 10)
        board.Add(item)
    return len(labels)


def draw_board_outline(board, width_mm, height_mm):
    """Add a rectangular outline on Edge.Cuts (replace any existing)."""
    # Remove any existing Edge.Cuts drawings
    existing = [d for d in board.GetDrawings()
                if d.GetLayerName() == 'Edge.Cuts']
    for d in existing:
        board.Remove(d)

    # Draw 4 line segments forming a rectangle (0,0) -> (w,0) -> (w,h) -> (0,h) -> (0,0)
    corners = [(0, 0), (width_mm, 0), (width_mm, height_mm), (0, height_mm), (0, 0)]
    for i in range(len(corners) - 1):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I_MM(corners[i][0], corners[i][1]))
        seg.SetEnd(pcbnew.VECTOR2I_MM(corners[i + 1][0], corners[i + 1][1]))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.15))
        board.Add(seg)
    return len(existing)


def main():
    if not os.path.exists(KICAD_PCB):
        print(f"ERROR: {KICAD_PCB} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {KICAD_PCB}...")
    board = pcbnew.LoadBoard(KICAD_PCB)

    placed, missing = place_components(board)
    print(f"Placed {placed} footprints.")
    # Filter out test pad (TP*) and mounting hole (MK*) refdes — those are
    # added programmatically by add_test_pads / add_mounting_holes, not
    # listed in PLACEMENT.
    truly_missing = [r for r in missing
                     if not r.startswith('TP') and not r.startswith('MK')]
    if truly_missing:
        print(f"WARNING: No placement defined for: {truly_missing}")

    removed_cuts = draw_board_outline(board, BOARD_WIDTH_MM, BOARD_HEIGHT_MM)
    print(f"Replaced board outline (removed {removed_cuts} prior shapes, added 4 segments forming {BOARD_WIDTH_MM}x{BOARD_HEIGHT_MM}mm rectangle).")

    mounts_added = add_mounting_holes(board, MOUNTING_HOLE_POSITIONS)
    print(f"Added {mounts_added} M3 mounting holes at corners.")

    keepouts_added = add_bcu_keepouts(board, BCU_KEEPOUT_GAPS)
    print(f"Added {keepouts_added} B.Cu keepout zones in AC channel gaps.")

    tps_added = add_test_pads(board, TEST_PADS)
    print(f"Added {tps_added} test pads.")

    labels_added = add_silkscreen_labels(board, SILKSCREEN_LABELS)
    print(f"Added {labels_added} silkscreen labels.")

    print(f"Saving {KICAD_PCB}...")
    pcbnew.SaveBoard(KICAD_PCB, board)
    print("Done.")
    print()
    print("Next steps:")
    print("  1. Open KiCad, open the project, verify placement looks right")
    print("  2. File > Export > Specctra DSN")
    print("  3. Run FreeRouting on the .dsn file")
    print("  4. File > Import > Specctra Session (.ses)")
    print("  5. DRC and Gerber export")


if __name__ == '__main__':
    main()
