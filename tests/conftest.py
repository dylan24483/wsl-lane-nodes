"""Pytest-wide isolation for the lane server's persistent stores.

Several test modules import ``lane_node_server`` during collection.  Setting
database paths inside an individual test module is therefore order-dependent:
an earlier import can bind the server to the repository's default databases.
Establish disposable paths before test-module collection so a combined test
run can never read or mutate operator/runtime state.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# `lane_node` package vs `lane_node/lane_node.py` module — resolve it ONCE
# ---------------------------------------------------------------------------
# The repo contains BOTH a `lane_node/` package directory (no __init__.py, so a
# namespace package) and a `lane_node/lane_node.py` module inside it. Most test
# modules do `sys.path.insert(0, <repo>/lane_node)` so they can `import
# controller_daemon` directly. Once any of them has done that, a later
# `import lane_node.strict_json` resolves `lane_node` to the SHADOWING MODULE
# `lane_node/lane_node.py` and fails with:
#
#     ModuleNotFoundError: No module named 'lane_node.strict_json';
#     'lane_node' is not a package
#
# ...and, because that shadow module does an unguarded `from gpiozero import
# Button, LED`, other modules fail with a misleading `No module named
# 'gpiozero'` on a machine that has no Pi libraries.
#
# Each file passes in isolation, so this only ever appeared in a whole-suite
# run — which was impossible before 2026-07-25 because collection aborted with
# INTERNALERROR first (see test_pytest_legacy_scripts.py). Fixing the abort
# exposed this.
#
# Bind the real namespace package into sys.modules HERE, before any test module
# is imported. A later sys.path insert then cannot rebind the name.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if "lane_node" not in sys.modules:
    _pkg = importlib.import_module("lane_node")
    if not hasattr(_pkg, "__path__"):  # pragma: no cover - defensive
        raise RuntimeError(
            "'lane_node' resolved to a module rather than the package "
            f"directory ({getattr(_pkg, '__file__', '?')}). The repo-root "
            "path entry must precede lane_node/ on sys.path.")


# ---------------------------------------------------------------------------
# Legacy script-style checks (see tests/test_pytest_legacy_scripts.py)
# ---------------------------------------------------------------------------
# These files are self-running verification SCRIPTS: they do their work at
# import time and finish with ``sys.exit(...)``. Pytest executes module bodies
# during collection, so collecting even one of them aborts the ENTIRE run with
# ``INTERNALERROR> SystemExit`` and reports "no tests ran" — which is what
# ``pytest tests/`` did in this (public) repo before 2026-07-25.
#
# They are ignored for direct collection here and re-exposed as real pytest
# cases by running each in an isolated child process, exactly as the WSL repo
# does. Do NOT add to this list to silence a collection error in a NEW file:
# write new tests pytest-native. ``test_no_unregistered_script_style_tests``
# fails closed if a script-style file appears that is not listed here.
LEGACY_SCRIPT_TESTS = (
    "test_cursor_resync.py",
    "test_flight_recorder.py",
    "test_foul_scoring.py",
    "test_fsm_legality_matrix.py",
    "test_max_possible.py",
    "test_premature_10th.py",
    "test_rp2040_link.py",
    "test_safety_rail_rig.py",
    "test_tenth_ball3_display.py",
)

collect_ignore = list(LEGACY_SCRIPT_TESTS)


_STORE_ROOT = tempfile.TemporaryDirectory(prefix="wsl-lane-tests-")
_STORE_PATH = Path(_STORE_ROOT.name)

os.environ["STATE_DB_PATH"] = str(_STORE_PATH / "lane_state.db")
os.environ["MACHINE_DB_PATH"] = str(_STORE_PATH / "machine_diag.db")
os.environ.setdefault("WSL_MACHINE_LANES", "21,22")
os.environ.setdefault("WSL_LANES", "21,22")
os.environ.setdefault("WSL_LANE_NODE_ID", "test-pair-21-22")
os.environ.setdefault("WSL_DIAG_SOURCE_ID", "test-pair-21-22")
os.environ.setdefault(
    "WSL_SCORING_NODE_TOPOLOGY", "test-pair-21-22=21,22")
os.environ.setdefault("WSL_ALLOW_UNAUTHENTICATED_BENCH", "1")
