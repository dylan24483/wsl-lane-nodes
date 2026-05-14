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

# Layout: refdes -> (x_mm, y_mm, rotation_degrees)
# Zones:
#   Top edge (y~8):       J8-J11 (DC OUT to AL-ZARD, channels 1-4)
#   Bottom edge (y~92):   J4-J7  (24VAC IN from foul/2nd-ball lamps, ch 1-4)
#   Left edge (x~8):      J1, J2, J3 (TB_PWR_IN, TB_AEDIKO_PWR, TB_KICK)
#   Interior left:        watchdog cluster (U1, Q1, Q2, D1, D2, C1-C3, R1-R8, LEDs)
#   Interior right:       4 AC channels stacked vertically (D + C + R per channel)
PLACEMENT = {
    # ---- Top edge: DC OUT terminals, screws facing up (rotation 0)
    'J8':  (20, 8, 0),     # Channel 1 DC OUT
    'J9':  (40, 8, 0),     # Channel 2 DC OUT
    'J10': (60, 8, 0),     # Channel 3 DC OUT
    'J11': (80, 8, 0),     # Channel 4 DC OUT

    # ---- Bottom edge: 24VAC IN terminals, screws facing down (180)
    'J4':  (20, 92, 180),  # Channel 1 AC IN
    'J5':  (40, 92, 180),  # Channel 2 AC IN
    'J6':  (60, 92, 180),  # Channel 3 AC IN
    'J7':  (80, 92, 180),  # Channel 4 AC IN

    # ---- Left edge: Power terminals, screws facing left (90 CCW)
    'J1':  (8, 28, 90),    # TB_PWR_IN
    'J2':  (8, 50, 90),    # TB_AEDIKO_PWR
    'J3':  (8, 72, 90),    # TB_KICK

    # ---- Watchdog block (left-center interior)
    'U1':  (32, 50, 0),    # NE555D

    'Q1':  (44, 45, 0),    # AO3400 Q1 (discharge MOSFET)
    'Q2':  (44, 55, 0),    # AO3400 Q2 (output MOSFET, low-side coil switch)

    'D1':  (25, 55, 180),  # 1N4148W D1 (TIMING_NODE side, anode toward TIMING_NODE)
    'D2':  (25, 45, 180),  # 1N4148W D2 (NE555_TRIG side, anode toward TRIG)

    'C1':  (22, 35, 0),    # 100uF/16V timing cap
    'C2':  (35, 38, 0),    # 0.1uF NE555 VCC bypass
    'C3':  (42, 40, 0),    # 10nF NE555 CTRL filter

    'R1':  (28, 28, 0),    # 100k timing pullup
    'R2':  (35, 28, 0),    # 10k TRIG pullup

    'R3':  (50, 42, 90),   # 1k Q1 gate series (rotated for vertical orientation near Q1)
    'R4':  (50, 48, 90),   # 10k Q1 gate pulldown
    'R5':  (50, 53, 90),   # 1k Q2 gate series (Python R6)
    'R6':  (50, 59, 90),   # 10k Q2 gate pulldown (Python R7)

    'R7':  (35, 66, 0),    # 470 LED1 current limit (Python R8)
    'R8':  (45, 66, 0),    # 470 LED2 current limit (Python R9)

    'D7':  (40, 70, 0),    # LED1 (watchdog-healthy)
    'D8':  (50, 70, 0),    # LED2 (power-good)

    # ---- AC interposer: 4 channels stacked vertically on right interior
    # Each row: D (rectifier) | C (smoothing cap) | R (bleeder)
    # Spacing: ~17mm between channels vertically
    # Channel 1 (top)
    'D3':  (62, 22, 0),
    'C4':  (75, 22, 0),
    'R9':  (87, 22, 90),
    # Channel 2
    'D4':  (62, 40, 0),
    'C5':  (75, 40, 0),
    'R10': (87, 40, 90),
    # Channel 3
    'D5':  (62, 58, 0),
    'C6':  (75, 58, 0),
    'R11': (87, 58, 90),
    # Channel 4 (bottom)
    'D6':  (62, 76, 0),
    'C7':  (75, 76, 0),
    'R12': (87, 76, 90),
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
