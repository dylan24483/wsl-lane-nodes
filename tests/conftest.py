"""Pytest-wide isolation for the lane server's persistent stores.

Several test modules import ``lane_node_server`` during collection.  Setting
database paths inside an individual test module is therefore order-dependent:
an earlier import can bind the server to the repository's default databases.
Establish disposable paths before test-module collection so a combined test
run can never read or mutate operator/runtime state.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


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
