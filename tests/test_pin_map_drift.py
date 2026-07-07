"""Pin-map drift regression — OUT_A_MAP / IN_A_MAP vs the PCB netlist generator.

THE GAP THIS CLOSES (review 2026-06-27 finding #53): the drift guard that
re-derives controller_io's OUT_A_MAP / IN_A_MAP from
scripts/generate_kicad_netlist_revB.py lived only in controller_io.py's
__main__ block, so `pytest tests/` stayed green while a rev-C generator edit
could silently drift the maps — exactly the BS/OS + M1/M2 swap class Codex
caught on 2026-06-03, whose downstream consequence is WRONG RELAYS on real
hardware. This file lifts the same assertions into the test suite.

The generator's dicts are read via `ast` WITHOUT executing the script (it
would try to generate a board / import SKiDL), mirroring how the __main__
guard does it. No hardware deps: controller_io imports smbus lazily.

Run with:
    py -3 tests/test_pin_map_drift.py     (or via pytest)
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lane_node"))

from controller_io import OUT_A_MAP, IN_A_MAP  # noqa: E402

GEN_PATH = REPO / "scripts" / "generate_kicad_netlist_revB.py"

# Generator lamp names -> controller_io output names (same table as __main__).
OUT_KEY = {"L_FIRST": "first_ball", "L_SECOND": "second_ball",
           "L_STRIKE": "strike", "L_FOUL": "foul"}


def _generator_dicts():
    """Parse OUTPUT_PINS + SLOW_INPUT_PINS out of the netlist generator with
    ast.literal_eval — never executes the generator (board generation / SKiDL
    must not run under pytest)."""
    gtree = ast.parse(GEN_PATH.read_text(encoding="utf-8"))
    gdicts = {}
    for node in gtree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("OUTPUT_PINS", "SLOW_INPUT_PINS")):
            gdicts[node.targets[0].id] = ast.literal_eval(node.value)
    assert "OUTPUT_PINS" in gdicts, f"OUTPUT_PINS not found in {GEN_PATH}"
    assert "SLOW_INPUT_PINS" in gdicts, f"SLOW_INPUT_PINS not found in {GEN_PATH}"
    return gdicts


def _pin_to_portbit(pin):
    """MCP23017 package pin -> (port, bit): pin 21-28 = GPA0-7, pin 1-8 = GPB0-7."""
    if 21 <= pin <= 28:
        return (0, pin - 21)
    if 1 <= pin <= 8:
        return (1, pin - 1)
    raise ValueError(f"unexpected MCP pin {pin}")


def test_out_a_map_matches_generator():
    gdicts = _generator_dicts()
    exp_out = {OUT_KEY.get(n, n): _pin_to_portbit(p)
               for n, p in gdicts["OUTPUT_PINS"].items()}
    assert OUT_A_MAP == exp_out, (
        f"OUT_A_MAP drift vs generator:\n  code={OUT_A_MAP}\n  gen ={exp_out}")


def test_in_a_map_matches_generator():
    gdicts = _generator_dicts()
    exp_in = {("Foul" if n == "FOUL" else n): _pin_to_portbit(p)
              for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items()
              if chip == "MCP_IN_A"}
    assert IN_A_MAP == exp_in, (
        f"IN_A_MAP drift vs generator:\n  code={IN_A_MAP}\n  gen ={exp_in}")


if __name__ == "__main__":
    test_out_a_map_matches_generator()
    test_in_a_map_matches_generator()
    print(f"pin maps match the PCB generator: OUT_A_MAP({len(OUT_A_MAP)}) "
          f"+ IN_A_MAP({len(IN_A_MAP)}) OK")
