# P9 guard (lane-nodes side): wsl_scoring_engine.py is deliberately duplicated
# across the two repos (WSL Systems serves the desk/API on WSL-SRV;
# wsl-lane-nodes runs on the lane Pis). Every engine edit MUST land in both
# copies. This is the mirror of WSL Systems/tests/test_engine_copies_identical.py
# pointing the other direction, so an engine edit committed from THIS repo
# fails THIS suite too — not just the Systems suite. It compares raw bytes
# after normalizing line endings (CRLF/CR -> LF); as of 2026-07 both working
# copies are byte-identical CRLF, but the normalized compare keeps the guard
# meaningful even if a checkout normalizes.
#
# On a machine that legitimately has no WSL Systems checkout (a lane Pi),
# set WSL_ENGINE_MIRROR_OPTIONAL=1 to skip LOUDLY instead of failing.
# Default is a hard FAIL — a silent skip would let single-sided edits
# through, which is exactly what this test prevents.
#
# Runs BOTH ways: `py tests/test_engine_copies_identical.py` (script, repo
# convention) and under pytest (`test_engine_copies_identical` collects; the
# script path is guarded under __main__ so it can't kill pytest collection).
import os
import sys

THIS_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANE_NODES_COPY = os.path.join(THIS_REPO, 'wsl_scoring_engine.py')
SYSTEMS_COPY = os.path.join(os.path.dirname(THIS_REPO),
                            'WSL Systems', 'wsl_scoring_engine.py')


def normalized_bytes(path):
    """File bytes with line endings normalized to LF."""
    with open(path, 'rb') as f:
        data = f.read()
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def _mirror_optional_and_absent():
    return (not os.path.exists(SYSTEMS_COPY)
            and os.environ.get('WSL_ENGINE_MIRROR_OPTIONAL') == '1')


def _first_divergence(a, b):
    la, lb = a.split(b'\n'), b.split(b'\n')
    return next((i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y),
                min(len(la), len(lb)) + 1), len(la), len(lb)


def run_checks():
    """Returns a list of failure strings (empty = pass). Raises nothing."""
    fails = []
    if _mirror_optional_and_absent():
        print('SKIPPED: WSL Systems sibling checkout not present and '
              'WSL_ENGINE_MIRROR_OPTIONAL=1 (lane-Pi checkout). The engine-copy '
              'drift guard DID NOT RUN — it must pass on a machine with both repos.')
        return fails

    a = b = None
    try:
        a = normalized_bytes(LANE_NODES_COPY)
        print('ok   wsl-lane-nodes copy readable')
    except OSError as e:
        print(f'FAIL wsl-lane-nodes copy readable   [{e}]')
        fails.append('lane-nodes copy readable')
    try:
        b = normalized_bytes(SYSTEMS_COPY)
        print('ok   WSL Systems copy readable (sibling repo checked out)')
    except OSError as e:
        # Missing sibling is a hard FAIL, not a skip — a silent skip would let
        # single-sided edits through, which is exactly what this test prevents.
        print(f'FAIL WSL Systems copy readable   [{e}]')
        fails.append('WSL Systems copy readable')

    if a is not None and b is not None:
        if a == b:
            print('ok   engine copies byte-identical (line-ending-normalized)')
        else:
            first, na, nb = _first_divergence(a, b)
            print(f'FAIL engine copies byte-identical — first divergence at line '
                  f'{first} ({na} vs {nb} lines) — edit landed in only one repo?')
            fails.append('engine copies identical')
    return fails


def test_engine_copies_identical():
    """Pytest entry point."""
    fails = run_checks()
    assert not fails, f'{len(fails)} FAILURES: {fails}'


if __name__ == '__main__':
    _fails = run_checks()
    print()
    print('ALL ENGINE-COPY CHECKS PASSED' if not _fails
          else f'{len(_fails)} FAILURES: {_fails}')
    sys.exit(1 if _fails else 0)
