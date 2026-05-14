#!/usr/bin/env python3
"""
Remove the bad U1.pin8 -> C2.pin1 VCC track I added in fix_u1_vcc.py.

The track I added crossed multiple existing F.Cu traces (KICK, GND,
NE555_CTRL all run through the y=62 area I routed through), producing
7 new DRC errors. Better to delete those tracks and route the
connection interactively in KiCad with push-and-shove.

Identifies the 3 bad tracks by their VCC_5V net + position (y=62 area
or specific endpoints from fix_u1_vcc.py) and removes them. Leaves all
FreeRouting-generated tracks intact.

Run with KiCad's bundled Python (has pcbnew):
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" undo_u1_vcc_fix.py

Close KiCad before running.
"""

import os
import sys
import pcbnew

KICAD_PCB = r"C:\Users\Dylan DeYoung\wsl-lane-nodes\kicad\wsl-phase8a.kicad_pcb"

# Endpoint coordinates of the 3 tracks added by fix_u1_vcc.py (in mm)
# Track 1: U1.pin8 (34.475, 64.095) -> (34.475, 62.0)
# Track 2: (34.475, 62.0) -> (23.05, 62.0)
# Track 3: (23.05, 62.0) -> C2.pin1 (23.05, 65.0)
BAD_TRACK_ENDPOINTS = [
    ((34.475, 64.095), (34.475, 62.0)),
    ((34.475, 62.0),   (23.05,  62.0)),
    ((23.05,  62.0),   (23.05,  65.0)),
]

TOLERANCE_NM = 1000  # 0.001mm tolerance for matching endpoints


def approx_equal(p1_nm, p2_xy_mm):
    """Check if two points match within tolerance (one in nm, one in mm)."""
    p2_nm = (pcbnew.FromMM(p2_xy_mm[0]), pcbnew.FromMM(p2_xy_mm[1]))
    return (abs(p1_nm.x - p2_nm[0]) < TOLERANCE_NM
            and abs(p1_nm.y - p2_nm[1]) < TOLERANCE_NM)


def track_matches(track, endpoint_pair):
    """Check if a track matches one of our bad endpoint pairs (either direction)."""
    s = track.GetStart()
    e = track.GetEnd()
    a, b = endpoint_pair
    return ((approx_equal(s, a) and approx_equal(e, b))
            or (approx_equal(s, b) and approx_equal(e, a)))


def main():
    if not os.path.exists(KICAD_PCB):
        print(f"ERROR: {KICAD_PCB} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {KICAD_PCB}...")
    board = pcbnew.LoadBoard(KICAD_PCB)

    # Collect tracks to remove
    to_remove = []
    for track in board.GetTracks():
        # Skip vias
        try:
            if track.GetClass() == "PCB_VIA":
                continue
        except AttributeError:
            pass
        for endpoint_pair in BAD_TRACK_ENDPOINTS:
            if track_matches(track, endpoint_pair):
                to_remove.append(track)
                break

    print(f"Found {len(to_remove)} bad tracks to remove (expected 3).")
    for track in to_remove:
        s = track.GetStart()
        e = track.GetEnd()
        print(f"  Removing: ({pcbnew.ToMM(s.x):.3f}, {pcbnew.ToMM(s.y):.3f}) "
              f"-> ({pcbnew.ToMM(e.x):.3f}, {pcbnew.ToMM(e.y):.3f})")
        board.Remove(track)

    print(f"Saving {KICAD_PCB}...")
    pcbnew.SaveBoard(KICAD_PCB, board)
    print("Done. Reopen KiCad and route U1.pin8 -> VCC manually.")


if __name__ == "__main__":
    main()
