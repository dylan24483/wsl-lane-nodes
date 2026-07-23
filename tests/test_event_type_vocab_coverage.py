#!/usr/bin/env python3
"""test_event_type_vocab_coverage.py — R3-1a never-again gate (Codex round-3).

THE THREE-ROUND FAILURE CLASS this closes: an event_type STRING is emitted
somewhere in the Pi daemon (lane_node/*.py) but is absent from the machine
diagnostics contract vocabulary. That is exactly the fw_identity poison pill
(R3-1 / reopened R2-6/R2-12): controller_daemon emitted 'fw_identity', the
server's validator did not know it, and the WHOLE batch 400'd so the outbox
cursor stalled and every later event was blocked.

This test statically walks the AST of every lane_node/*.py module, finds
every event_type string argument to an emit call, and fails if ANY of them
is not in server/machine_contract.json's vocab.event_types. It cannot be
satisfied by adding a type to only one side, because the contract is the one
source both the server (machine_store) and the client (diag_events) load.

Emit sites recognised (the event_type argument position per callee):
  * emit_event(severity, event_type, ...)        -> arg index 1 / kw event_type
  * _emit(severity, event_type, ...)             -> arg index 1
  * _diag_emit(severity, event_type, ...)        -> arg index 1
  * diag_emit(severity, event_type, ...)         -> arg index 1  (lambda forwards)
  * make_event(lane_id, severity, event_type,..) -> arg index 2 / kw event_type

`if __name__ == "__main__":` blocks are skipped — those are per-module smoke
harnesses ('smoke', 'catastrophic') that deliberately exercise the
error/degenerate paths, not production emissions.

Runs under pytest or standalone (exit 0/1).
"""
import ast
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANE_NODE_DIR = os.path.join(REPO_ROOT, "lane_node")
CONTRACT_PATH = os.path.join(REPO_ROOT, "server", "machine_contract.json")

# callee name -> zero-based positional index of the event_type argument
_EMIT_CALLEES = {
    "emit_event": 1,
    "_emit": 1,
    "_diag_emit": 1,
    "diag_emit": 1,
    "make_event": 2,
}


def _contract_event_types():
    with open(CONTRACT_PATH, encoding="utf-8") as f:
        return set(json.load(f)["vocab"]["event_types"])


class _EmitVisitor(ast.NodeVisitor):
    """Collect (lineno, literal_event_type) for every recognised emit call,
    and a list of (lineno) dynamic sites (non-literal event_type) for report.
    Skips `if __name__ == '__main__':` bodies (module smoke harnesses)."""

    def __init__(self):
        self.literals = []     # (lineno, str)
        self.dynamic = []      # (lineno, callee)

    def visit_If(self, node):
        if _is_main_guard(node.test):
            return   # do not descend into the smoke harness
        self.generic_visit(node)

    def visit_Call(self, node):
        callee = _callee_name(node.func)
        idx = _EMIT_CALLEES.get(callee)
        if idx is not None:
            arg = _event_type_arg(node, idx)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self.literals.append((node.lineno, arg.value))
            elif arg is not None:
                self.dynamic.append((node.lineno, callee))
        self.generic_visit(node)


def _callee_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _event_type_arg(node, idx):
    for kw in node.keywords:
        if kw.arg == "event_type":
            return kw.value
    if len(node.args) > idx:
        return node.args[idx]
    return None


def _is_main_guard(test):
    # matches `__name__ == "__main__"`
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def _scan_all():
    emitted = {}    # event_type -> [(module, lineno), ...]
    for name in sorted(os.listdir(LANE_NODE_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(LANE_NODE_DIR, name)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        v = _EmitVisitor()
        v.visit(tree)
        for lineno, et in v.literals:
            emitted.setdefault(et, []).append((name, lineno))
    return emitted


def test_every_emitted_event_type_is_in_the_contract():
    contract = _contract_event_types()
    emitted = _scan_all()
    missing = {et: sites for et, sites in emitted.items()
               if et not in contract}
    assert not missing, (
        "event_type(s) emitted in lane_node/*.py but ABSENT from "
        "server/machine_contract.json vocab.event_types (the R3-1 drift "
        "class — server would 400 the whole batch): "
        + "; ".join(f"{et!r} at {sites}" for et, sites in sorted(missing.items()))
    )


def test_scan_found_the_known_emit_sites():
    # Guard against the scanner silently matching nothing (a refactor that
    # renamed the emit helpers would make the coverage test vacuously pass).
    emitted = _scan_all()
    assert "fw_identity" in emitted, (
        "scanner did not find the fw_identity emit site — the AST walk is "
        "broken; the coverage gate would pass vacuously")
    assert "fsm_fault" in emitted and "camera_health" in emitted, \
        "scanner missed known emit sites across multiple modules"
    assert len(emitted) >= 20, \
        f"scanner found only {len(emitted)} emitted types — suspiciously few"


if __name__ == "__main__":
    fails = 0
    for fn in (test_scan_found_the_known_emit_sites,
               test_every_emitted_event_type_is_in_the_contract):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    if not fails:
        em = _scan_all()
        print(f"\n{len(em)} distinct event_type literals emitted across "
              f"lane_node/*.py, all present in the contract.")
    sys.exit(1 if fails else 0)
