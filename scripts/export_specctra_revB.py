#!/usr/bin/env python3
"""
Export the Rev-B KiCad board to Specctra DSN for autorouter handoff.

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\export_specctra_revB.py

This only exports a routing artifact. It does not run or import an autorouter
session, because the Rev-B custom isolation rules must be clean before routed
copper is trusted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "kicad" / "wsl-phase8b.kicad_pcb"
DEFAULT_DSN = ROOT / "kicad" / "wsl-phase8b.revB-reband.dsn"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--output", type=Path, default=DEFAULT_DSN)
    args = parser.parse_args()

    board_path = args.board.resolve()
    output_path = args.output.resolve()
    if not board_path.exists():
        raise SystemExit(f"ERROR: board not found: {board_path}")

    board = pcbnew.LoadBoard(str(board_path))
    if not pcbnew.ExportSpecctraDSN(board, str(output_path)):
        raise SystemExit(f"ERROR: failed to export DSN: {output_path}")

    print(f"Exported DSN: {output_path}")
    print(f"Bytes: {output_path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
