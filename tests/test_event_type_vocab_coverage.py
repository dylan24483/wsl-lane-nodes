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

# callee name -> (severity-arg index, event_type-arg index). Both positions are
# checked: an emit call is only counted when its SEVERITY position holds a
# plausible severity (a string literal, a forwarded Name, or a ternary) — this
# is how the gate tells a real diagnostics emitter apart from an unrelated
# method that happens to share the name `_emit` (e.g. CamTelemetry._emit(
# cycle_index, durations), whose arg-0 is `self.cycle_index`, not a severity).
_EMIT_CALLEES = {
    "emit_event": (0, 1),
    "_emit": (0, 1),
    "_diag_emit": (0, 1),
    "diag_emit": (0, 1),
    "make_event": (1, 2),
}
# SEVERITIES is loaded lazily by the visitor (contract-driven) but a severity is
# ALSO accepted structurally (Name / IfExp) so a forwarded or computed severity
# never causes a real emit site to be skipped.


def _contract_event_types():
    with open(CONTRACT_PATH, encoding="utf-8") as f:
        return set(json.load(f)["vocab"]["event_types"])


def _param_names(args):
    names = []
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.append(a.arg)
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


class _Scope:
    __slots__ = ("params", "bindings")

    def __init__(self, params=()):
        self.params = set(params)
        # name -> (values:set[str], resolved:bool) for simple string/ternary
        # assignments seen so far in this scope.
        self.bindings = {}


class _EmitVisitor(ast.NodeVisitor):
    """Enumerate every event_type STRING that can be emitted in a module, and
    every emit site whose event_type CANNOT be pinned to string literals.

    Handles the three-round drift class structurally:
      * literal args and ternaries of literals (inline OR assigned to a local
        variable first — the `et = ('rp2040_wdt_reset' if ... else 'fw_reboot')`
        case the original gate silently dropped);
      * forwarding helpers/lambdas whose event_type is a PARAMETER (the real
        literals live at the call sites, which the module-wide scan covers) —
        these are resolved-with-no-literals, not flagged;
      * name collisions on `_emit` are rejected by the severity-position gate.
    Anything left genuinely unresolvable (a bare variable of unknown origin, an
    f-string) is reported so the test FAILS on it.

    `if __name__ == '__main__':` bodies (module smoke harnesses) are skipped."""

    def __init__(self, severities):
        self.literals = []     # (lineno, str)
        self.dynamic = []      # (lineno, callee) — UNRESOLVABLE event_type
        self._severities = set(severities)
        self._scopes = [_Scope()]     # module scope

    # -- scopes ---------------------------------------------------------------
    def visit_FunctionDef(self, node):
        self._scopes.append(_Scope(_param_names(node.args)))
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self._scopes.append(_Scope(_param_names(node.args)))
        self.visit(node.body)
        self._scopes.pop()

    def visit_If(self, node):
        if _is_main_guard(node.test):
            return   # do not descend into the smoke harness
        self.generic_visit(node)

    def visit_Assign(self, node):
        # Record simple string/ternary bindings so a later emit(et) resolves.
        if isinstance(node.value, (ast.Constant, ast.IfExp)):
            vals, res = self._resolve(node.value)
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    self._scopes[-1].bindings[tgt.id] = (vals, res)
        self.generic_visit(node)

    # -- resolution -----------------------------------------------------------
    def _resolve(self, expr):
        """(values, resolved) for an event_type/severity expression, scope-aware.
        A Name resolves via the nearest scope binding, else (as a forwarded
        parameter) to resolved-with-no-literals, else unresolved."""
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}, True
        if isinstance(expr, ast.IfExp):
            a, ra = self._resolve(expr.body)
            b, rb = self._resolve(expr.orelse)
            return (a | b), (ra and rb)
        if isinstance(expr, ast.Name):
            for sc in reversed(self._scopes):
                if expr.id in sc.bindings:
                    return sc.bindings[expr.id]
                if expr.id in sc.params:
                    return set(), True     # forwarded param — literals at callers
            return set(), False
        return set(), False

    def _looks_like_severity(self, arg):
        if arg is None:
            return False
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value in self._severities
        # a forwarded/computed severity (Name / ternary) is plausible; a
        # self.cycle_index (Attribute), Subscript, Call, etc. is NOT.
        return isinstance(arg, (ast.Name, ast.IfExp))

    def visit_Call(self, node):
        spec = _EMIT_CALLEES.get(_callee_name(node.func))
        if spec is not None:
            sev_idx, et_idx = spec
            sev = _arg_at(node, sev_idx, "severity")
            if self._looks_like_severity(sev):
                arg = _arg_at(node, et_idx, "event_type")
                if arg is not None:
                    values, resolved = self._resolve(arg)
                    for v in values:
                        self.literals.append((node.lineno, v))
                    if not resolved:
                        self.dynamic.append((node.lineno,
                                             _callee_name(node.func)))
        self.generic_visit(node)


def _callee_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _arg_at(node, idx, kw):
    for k in node.keywords:
        if k.arg == kw:
            return k.value
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


def _contract_severities():
    with open(CONTRACT_PATH, encoding="utf-8") as f:
        return set(json.load(f)["vocab"]["severities"])


def _scan_all():
    emitted = {}    # event_type -> [(module, lineno), ...]
    dynamic = []    # (module, lineno, callee) — unresolvable event_type args
    severities = _contract_severities()
    for name in sorted(os.listdir(LANE_NODE_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(LANE_NODE_DIR, name)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        v = _EmitVisitor(severities)
        v.visit(tree)
        for lineno, et in v.literals:
            emitted.setdefault(et, []).append((name, lineno))
        for lineno, callee in v.dynamic:
            dynamic.append((name, lineno, callee))
    return emitted, dynamic


def test_every_emitted_event_type_is_in_the_contract():
    contract = _contract_event_types()
    emitted, _dynamic = _scan_all()
    missing = {et: sites for et, sites in emitted.items()
               if et not in contract}
    assert not missing, (
        "event_type(s) emitted in lane_node/*.py but ABSENT from "
        "server/machine_contract.json vocab.event_types (the R3-1 drift "
        "class — the server would per-record-reject them and the client "
        "raise at the emitter): "
        + "; ".join(f"{et!r} at {sites}" for et, sites in sorted(missing.items()))
    )


def test_no_unresolvable_dynamic_emit_sites():
    # R3-1/R3-6: the ORIGINAL gate collected non-literal event_type args into a
    # 'dynamic' list it never asserted on, so `et = ('rp2040_wdt_reset' if ...
    # else 'fw_reboot')` shipped both types UNGUARDED. The scanner now resolves
    # ternary branches to literals (checked by the test above); anything it
    # STILL cannot pin to a string literal (a bare variable from elsewhere, an
    # f-string) is a hole in the never-again gate and must fail here — either
    # rewrite the site into a resolvable form or the contract check is blind to
    # it.
    _emitted, dynamic = _scan_all()
    assert not dynamic, (
        "emit site(s) with an event_type the static gate cannot resolve to a "
        "string literal (so it is NOT bound to the contract vocab): "
        + "; ".join(f"{callee}() at {mod}:{ln}" for mod, ln, callee in dynamic)
        + " — make the event_type a literal or a ternary of literals.")


def test_scan_found_the_known_emit_sites():
    # Guard against the scanner silently matching nothing (a refactor that
    # renamed the emit helpers would make the coverage test vacuously pass).
    emitted, _dynamic = _scan_all()
    assert "fw_identity" in emitted, (
        "scanner did not find the fw_identity emit site — the AST walk is "
        "broken; the coverage gate would pass vacuously")
    assert "fsm_fault" in emitted and "camera_health" in emitted, \
        "scanner missed known emit sites across multiple modules"
    # The ternary-carried firmware-reboot types are the exact R3-1/R3-6 blind
    # spot — prove the ternary resolver now brings BOTH under the gate.
    assert "rp2040_wdt_reset" in emitted and "fw_reboot" in emitted, (
        "scanner did not resolve the `('rp2040_wdt_reset' if ... else "
        "'fw_reboot')` ternary — the dynamic-site fix regressed")
    assert len(emitted) >= 20, \
        f"scanner found only {len(emitted)} emitted types — suspiciously few"


if __name__ == "__main__":
    fails = 0
    for fn in (test_scan_found_the_known_emit_sites,
               test_no_unresolvable_dynamic_emit_sites,
               test_every_emitted_event_type_is_in_the_contract):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    if not fails:
        em, _dyn = _scan_all()
        print(f"\n{len(em)} distinct event_type literals emitted across "
              f"lane_node/*.py, all present in the contract.")
    sys.exit(1 if fails else 0)
