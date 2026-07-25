"""Expose the legacy script-style checks as normal pytest cases.

WHY THIS EXISTS
---------------
Nine files in ``tests/`` are self-running verification SCRIPTS: they do their
work at import time and end with ``sys.exit(...)``. Pytest executes module
bodies during collection, so collecting one of them aborted the whole run:

    $ py -3 -m pytest tests/
    INTERNALERROR> SystemExit: 0
    no tests ran in 0.09s

Anyone cloning this repository — which is the PUBLIC one — and running the
obvious command got a crash and zero coverage, while the 36 pytest-native
files (717 checks) were never reached. The WSL repo already solved this with
``tests/test_pytest_legacy_scripts.py``; this is the lane-repo equivalent.

``conftest.LEGACY_SCRIPT_TESTS`` lists the scripts and ``collect_ignore``
keeps pytest from importing them. Each one is run here in an isolated child
process so its exit status becomes a normal pass/fail with full output on
failure.

The guards below are the important part: they fail CLOSED so this cannot
silently rot the way a glob-driven list can.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import LEGACY_SCRIPT_TESTS

TEST_DIR = Path(__file__).resolve().parent
WORKSPACE = TEST_DIR.parent
LANE_NODE = WORKSPACE / "lane_node"
SERVER = WORKSPACE / "server"


def _child_env():
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    # Script-mode children get only the script's own dir on sys.path; the
    # legacy scripts import lane_node/server modules directly.
    parts = [str(WORKSPACE), str(LANE_NODE), str(SERVER)]
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


@pytest.mark.parametrize(
    "script_name", LEGACY_SCRIPT_TESTS, ids=lambda n: Path(n).stem)
def test_legacy_script(script_name):
    script = TEST_DIR / script_name
    assert script.is_file(), f"{script_name} is listed but does not exist"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=WORKSPACE,
        env=_child_env(),
        text=True,
        capture_output=True,
        timeout=300,
    )
    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output[-12000:]


def _module_level_exits(path: Path) -> bool:
    """True if the module body can call sys.exit / raise SystemExit directly.

    Parsed statically — importing to find out is precisely the thing that
    breaks collection.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    # Only statements pytest actually EXECUTES at import matter. Prune the
    # bodies of functions/classes (never called during collection) and a
    # guarded `if __name__ == "__main__":` block (module __name__ is the test
    # module, so the branch is not taken). ast.walk() cannot express this —
    # it yields every descendant — so traverse explicitly.
    pruned = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def _exits(node) -> bool:
        if isinstance(node, pruned):
            return False
        if isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                return False
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "exit"
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "sys"):
                return True
            if isinstance(fn, ast.Name) and fn.id == "exit":
                return True
        if isinstance(node, ast.Raise):
            exc = node.exc
            name = None
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                name = exc.func.id
            elif isinstance(exc, ast.Name):
                name = exc.id
            if name == "SystemExit":
                return True
        return any(_exits(child) for child in ast.iter_child_nodes(node))

    return any(_exits(stmt) for stmt in tree.body)


def test_no_unregistered_script_style_tests():
    """Fail closed: a NEW script-style test must not break `pytest tests/`.

    Without this, adding another ``sys.exit``-at-import file silently returns
    the whole repo to INTERNALERROR / zero coverage.
    """
    offenders = []
    for path in sorted(TEST_DIR.glob("test_*.py")):
        if path.name in LEGACY_SCRIPT_TESTS:
            continue
        if _module_level_exits(path):
            offenders.append(path.name)
    assert not offenders, (
        "these test files exit at import time and will abort collection for "
        f"the ENTIRE suite: {offenders}. Write them pytest-native (def "
        "test_*), or guard the exit behind `if __name__ == \"__main__\":`. "
        "Do not just append them to conftest.LEGACY_SCRIPT_TESTS."
    )


def test_registered_legacy_scripts_still_exist_and_are_script_style():
    """The ignore list must not outlive the files or their script-ness.

    A stale entry silently removes a file from collection even after it has
    been converted to pytest-native tests — i.e. it would stop running.
    """
    missing = [n for n in LEGACY_SCRIPT_TESTS if not (TEST_DIR / n).is_file()]
    assert not missing, (
        f"conftest.LEGACY_SCRIPT_TESTS names files that do not exist: "
        f"{missing} — remove them from the list.")
    converted = [
        n for n in LEGACY_SCRIPT_TESTS
        if not _module_level_exits(TEST_DIR / n)
    ]
    assert not converted, (
        f"these are no longer script-style: {converted}. Remove them from "
        "conftest.LEGACY_SCRIPT_TESTS so pytest collects them directly, "
        "otherwise they are silently excluded from `pytest tests/`.")


def test_all_test_files_are_tracked_in_git():
    """A working-tree-only test silently shrinks the suite in a clean clone."""
    result = subprocess.run(
        ["git", "ls-files", "--", "tests"],
        cwd=WORKSPACE, text=True, capture_output=True)
    if result.returncode != 0:
        pytest.skip("not a git checkout (git ls-files failed)")
    tracked = {Path(line).name for line in result.stdout.splitlines()}
    untracked = [
        p.name for p in sorted(TEST_DIR.glob("test_*.py"))
        if p.name not in tracked
    ]
    assert not untracked, (
        "test files exist ONLY in the working tree (a clean clone would "
        f"silently collect fewer tests): {untracked} — git add them.")


def test_tests_do_not_escape_to_a_developer_checkout():
    forbidden = (
        "C:\\Users\\" + "Dylan DeYoung\\WSL Systems",
        "C:\\Users\\" + "Dylan DeYoung\\wsl-lane-nodes",
    )
    offenders = []
    for path in sorted(TEST_DIR.glob("test_*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        if any(p in source for p in forbidden):
            offenders.append(path.name)
    assert not offenders, (
        "tests contain developer-specific checkout paths and can execute "
        f"another tree instead of this clone: {offenders}")
