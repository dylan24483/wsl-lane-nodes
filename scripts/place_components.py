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

    # ---- D_PROT: reverse-polarity Schottky (between J1 raw input and VCC_5V).
    # SKiDL assigns refdes D9 since it's defined last among diode-prefix parts.
    # Placed in the x-gap between J1 (x=8) and channel 1 column (x=20), at
    # y=33 (between J1 at y=22 and J2 at y=45 to clear both terminals).
    'D9':  (16, 33, 0),    # SS14 Schottky, SMA package

    # ---- AC interposer channels: 4 vertical columns aligned with terminals
    # Each column has D (top, near DC_OUT) -> C (middle) -> R (bottom)
    # The 50mm vertical run from R to AC_IN is clear of watchdog parts.
    # Channel 1 (x=20, below J8)
    'D3':  (20, 18, 0),    # M7 rectifier
    'C4':  (20, 30, 0),    # 10uF smoothing
    'R9':  (20, 42, 0),    # 100k bleeder
    # Channel 2 (x=40, below J9)
    'D4':  (40, 18, 0),
    'C5':  (40, 30, 0),
    'R10': (40, 42, 0),
    # Channel 3 (x=60, below J10)
    'D5':  (60, 18, 0),
    'C6':  (60, 30, 0),
    'R11': (60, 42, 0),
    # Channel 4 (x=80, below J11)
    'D6':  (80, 18, 0),
    'C7':  (80, 30, 0),
    'R12': (80, 42, 0),

    # ---- Watchdog cluster (y=55-80, fills the gaps between channel columns)
    # Critical clearance check: channel return traces run vertically at
    # x=20, 40, 60, 80 from y=42 down to y=92. Watchdog parts MUST sit
    # in the x-gaps (x≈10, 28, 48, 70) to avoid blocking these traces.

    'U1':  (32, 65, 0),    # NE555 (between channel 1 and 2 columns)

    'D1':  (45, 62, 0),    # 1N4148WS D1 (between U1 and Q1, diode-OR to TIMING_NODE)
    'D2':  (45, 68, 0),    # 1N4148WS D2 (between U1 and Q2, diode-OR to TRIG)

    'Q1':  (52, 60, 0),    # AO3400 Q1 discharge (between ch2 and ch3 cols)
    'Q2':  (52, 70, 0),    # AO3400 Q2 output

    'C1':  (12, 65, 0),    # 100uF timing cap (far left, clears ch1 trace)
    'C2':  (28, 55, 0),    # 0.1uF NE555 VCC bypass (above U1, x-gap)
    'C3':  (28, 75, 0),    # 10nF NE555 CTRL filter (below U1, x-gap)

    'R1':  (12, 55, 0),    # 100k NE555 timing pullup (far left, x-gap)
    'R2':  (24, 55, 0),    # 10k TRIG pullup

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
    if missing:
        print(f"WARNING: No placement defined for: {missing}")

    removed_cuts = draw_board_outline(board, BOARD_WIDTH_MM, BOARD_HEIGHT_MM)
    print(f"Replaced board outline (removed {removed_cuts} prior shapes, added 4 segments forming {BOARD_WIDTH_MM}x{BOARD_HEIGHT_MM}mm rectangle).")

    mounts_added = add_mounting_holes(board, MOUNTING_HOLE_POSITIONS)
    print(f"Added {mounts_added} M3 mounting holes at corners.")

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
