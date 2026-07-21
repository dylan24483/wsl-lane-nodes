"""Pin-map drift regression — controller_io maps vs the PCB netlist generators.

THE GAP THIS CLOSES (review 2026-06-27 finding #53): the drift guard that
re-derives controller_io's OUT_A_MAP / IN_A_MAP from
scripts/generate_kicad_netlist_revB.py lived only in controller_io.py's
__main__ block, so `pytest tests/` stayed green while a rev-C generator edit
could silently drift the maps — exactly the BS/OS + M1/M2 swap class Codex
caught on 2026-06-03, whose downstream consequence is WRONG RELAYS on real
hardware. This file lifts the same assertions into the test suite.

H3 (Codex NO-GO audit 2026-07-21): the guard is PARAMETRIZED over BOTH board
revisions — the rev-B/C generator validates the rev-C IN-B map (8 GPA
channels) and the rev-D generator validates the rev-D map (adds AUX4-11 on
GPB0-7). The old guard pinned the rev-B generator only, so the rev-D GPB
bank had no drift protection at all. Each check is selected EXPLICITLY via
controller_io.IN_B_MAPS; both must pass.

The generator dicts are read via `ast` WITHOUT executing the scripts (they
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

from controller_io import (  # noqa: E402
    OUT_A_MAP, IN_A_MAP, IN_B_MAP, IN_B_MAP_REVD, IN_B_MAPS, in_b_map_for)

# (generator file, board_rev key into IN_B_MAPS) — the explicit selection.
GENERATORS = [
    ("generate_kicad_netlist_revB.py", "revC"),   # rev-B/C boards (pilot, machine 22)
    ("generate_kicad_netlist_revD.py", "revD"),   # rev-D respin (AUX4-11 GPB bank)
]

# Generator lamp names -> controller_io output names (same table as __main__).
OUT_KEY = {"L_FIRST": "first_ball", "L_SECOND": "second_ball",
           "L_STRIKE": "strike", "L_FOUL": "foul"}


def _generator_dicts(gen_name):
    """Parse OUTPUT_PINS + SLOW_INPUT_PINS out of a netlist generator with
    ast.literal_eval — never executes the generator (board generation / SKiDL
    must not run under pytest)."""
    gen_path = REPO / "scripts" / gen_name
    gtree = ast.parse(gen_path.read_text(encoding="utf-8"))
    gdicts = {}
    for node in gtree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("OUTPUT_PINS", "SLOW_INPUT_PINS")):
            gdicts[node.targets[0].id] = ast.literal_eval(node.value)
    assert "OUTPUT_PINS" in gdicts, f"OUTPUT_PINS not found in {gen_path}"
    assert "SLOW_INPUT_PINS" in gdicts, f"SLOW_INPUT_PINS not found in {gen_path}"
    return gdicts


def _pin_to_portbit(pin):
    """MCP23017 package pin -> (port, bit): pin 21-28 = GPA0-7, pin 1-8 = GPB0-7."""
    if 21 <= pin <= 28:
        return (0, pin - 21)
    if 1 <= pin <= 8:
        return (1, pin - 1)
    raise ValueError(f"unexpected MCP pin {pin}")


def test_out_a_map_matches_both_generators():
    for gen_name, _rev in GENERATORS:
        gdicts = _generator_dicts(gen_name)
        exp_out = {OUT_KEY.get(n, n): _pin_to_portbit(p)
                   for n, p in gdicts["OUTPUT_PINS"].items()}
        assert OUT_A_MAP == exp_out, (
            f"[{gen_name}] OUT_A_MAP drift:\n  code={OUT_A_MAP}\n  gen ={exp_out}")


def test_in_a_map_matches_both_generators():
    for gen_name, _rev in GENERATORS:
        gdicts = _generator_dicts(gen_name)
        exp_in = {("Foul" if n == "FOUL" else n): _pin_to_portbit(p)
                  for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items()
                  if chip == "MCP_IN_A"}
        assert IN_A_MAP == exp_in, (
            f"[{gen_name}] IN_A_MAP drift:\n  code={IN_A_MAP}\n  gen ={exp_in}")


def test_in_b_maps_match_their_generators():
    """Per-revision IN-B check: rev-B/C generator <-> IN_B_MAP; rev-D
    generator <-> IN_B_MAP_REVD. Explicit selection through IN_B_MAPS."""
    for gen_name, rev in GENERATORS:
        gdicts = _generator_dicts(gen_name)
        exp_inb = {n: _pin_to_portbit(p)
                   for n, (chip, p) in gdicts["SLOW_INPUT_PINS"].items()
                   if chip == "MCP_IN_B"}
        code_map = in_b_map_for(rev)
        assert code_map == exp_inb, (
            f"[{gen_name} / {rev}] IN-B map drift:\n"
            f"  code={code_map}\n  gen ={exp_inb}")


def test_in_b_revision_structure():
    """Structural invariants: rev-C is GPA-only (single-read path); rev-D is a
    strict superset adding exactly AUX4-11 on GPB0-7; unknown revs are a hard
    error (no silent wrong-bank reads)."""
    assert IN_B_MAPS["revB"] is IN_B_MAP and IN_B_MAPS["revC"] is IN_B_MAP
    assert IN_B_MAPS["revD"] is IN_B_MAP_REVD
    assert all(port == 0 for (port, _bit) in IN_B_MAP.values()), \
        "rev-B/C IN-B channels must all be on GPA"
    assert {n: pb for n, pb in IN_B_MAP_REVD.items() if n in IN_B_MAP} == IN_B_MAP, \
        "rev-D IN-B map must be a strict superset of the rev-C map"
    added = {n: pb for n, pb in IN_B_MAP_REVD.items() if n not in IN_B_MAP}
    assert added == {f"AUX{i}": (1, i - 4) for i in range(4, 12)}, added
    try:
        in_b_map_for("revZ")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown board_rev must raise ValueError")


if __name__ == "__main__":
    test_out_a_map_matches_both_generators()
    test_in_a_map_matches_both_generators()
    test_in_b_maps_match_their_generators()
    test_in_b_revision_structure()
    print(f"pin maps match BOTH PCB generators: OUT_A_MAP({len(OUT_A_MAP)}) "
          f"+ IN_A_MAP({len(IN_A_MAP)}) + IN_B_MAP revC({len(IN_B_MAP)}) / "
          f"revD({len(IN_B_MAP_REVD)}) OK")
