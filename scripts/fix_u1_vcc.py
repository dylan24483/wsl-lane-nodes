#!/usr/bin/env python3
"""
Fix the U1.pin8 (VCC_5V) unconnected pad that FreeRouting left.

FreeRouting routed VCC_5V near U1 but left a 0.2mm stub at (29.38, 68.05)
and never reached U1.pin8 at (34.475, 64.095). This script adds a 3-segment
L-shaped track on F.Cu that routes from U1.pin8 around the top of U1's
body to C2.pin1 (also on VCC_5V), bridging the gap.

Routing path (all on F.Cu, 0.5mm Power-class width):
  1. U1.pin8 (34.475, 64.095) UP to (34.475, 62.0)  - 2.1mm vertical
  2. (34.475, 62.0) LEFT to (23.05, 62.0)            - 11.4mm horizontal
                                                       above U1 body (top at y=63.55)
  3. (23.05, 62.0) DOWN to C2.pin1 (23.05, 65.0)     - 3.0mm vertical

Operates on the CURRENT .kicad_pcb (with FreeRouting traces already imported).
Does NOT regenerate from netlist — preserves all existing routing.

Run with KiCad's bundled Python (has pcbnew):
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" fix_u1_vcc.py

Close KiCad before running.
"""

import os
import sys
import pcbnew

KICAD_PCB = r"C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\wsl-phase8a.kicad_pcb"


def find_pad(footprint, pin_number):
    """Return the pad with the given pin number from a footprint."""
    for pad in footprint.Pads():
        if pad.GetNumber() == str(pin_number):
            return pad
    return None


def add_track(board, start_xy, end_xy, net, layer=None, width_mm=0.5):
    """Add a single track segment to the board."""
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(start_xy if isinstance(start_xy, pcbnew.VECTOR2I)
                   else pcbnew.VECTOR2I_MM(start_xy[0], start_xy[1]))
    track.SetEnd(end_xy if isinstance(end_xy, pcbnew.VECTOR2I)
                 else pcbnew.VECTOR2I_MM(end_xy[0], end_xy[1]))
    track.SetLayer(layer if layer is not None else pcbnew.F_Cu)
    track.SetWidth(pcbnew.FromMM(width_mm))
    track.SetNet(net)
    board.Add(track)


def main():
    if not os.path.exists(KICAD_PCB):
        print(f"ERROR: {KICAD_PCB} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {KICAD_PCB}...")
    board = pcbnew.LoadBoard(KICAD_PCB)

    # Find U1.pin8 and C2.pin1
    u1 = board.FindFootprintByReference("U1")
    c2 = board.FindFootprintByReference("C2")

    if u1 is None:
        print("ERROR: U1 not found", file=sys.stderr)
        sys.exit(1)
    if c2 is None:
        print("ERROR: C2 not found", file=sys.stderr)
        sys.exit(1)

    u1_pin8 = find_pad(u1, 8)
    c2_pin1 = find_pad(c2, 1)

    if u1_pin8 is None:
        print("ERROR: U1.pin8 not found", file=sys.stderr)
        sys.exit(1)
    if c2_pin1 is None:
        print("ERROR: C2.pin1 not found", file=sys.stderr)
        sys.exit(1)

    vcc_net = board.FindNet("VCC_5V")
    if vcc_net is None:
        print("ERROR: VCC_5V net not found", file=sys.stderr)
        sys.exit(1)

    u1_pos = u1_pin8.GetPosition()
    c2_pos = c2_pin1.GetPosition()
    print(f"U1.pin8 (VCC): ({pcbnew.ToMM(u1_pos.x):.3f}, {pcbnew.ToMM(u1_pos.y):.3f})")
    print(f"C2.pin1 (VCC): ({pcbnew.ToMM(c2_pos.x):.3f}, {pcbnew.ToMM(c2_pos.y):.3f})")

    # 3-segment L-shape routing around top of U1 (y < 63.55 stays above body)
    corner1 = pcbnew.VECTOR2I_MM(34.475, 62.0)
    corner2 = pcbnew.VECTOR2I_MM(23.05, 62.0)

    print("Adding 3 track segments:")
    add_track(board, u1_pos, corner1, vcc_net, width_mm=0.5)
    print(f"  Seg 1: U1.pin8 -> ({pcbnew.ToMM(corner1.x):.3f}, {pcbnew.ToMM(corner1.y):.3f})  [F.Cu, 0.5mm]")
    add_track(board, corner1, corner2, vcc_net, width_mm=0.5)
    print(f"  Seg 2: -> ({pcbnew.ToMM(corner2.x):.3f}, {pcbnew.ToMM(corner2.y):.3f})  [F.Cu, 0.5mm]")
    add_track(board, corner2, c2_pos, vcc_net, width_mm=0.5)
    print(f"  Seg 3: -> C2.pin1  [F.Cu, 0.5mm]")

    print(f"Saving {KICAD_PCB}...")
    pcbnew.SaveBoard(KICAD_PCB, board)
    print("Done.")
    print()
    print("Next: reopen KiCad, run DRC (F8). Should now show 0 errors.")


if __name__ == "__main__":
    main()
