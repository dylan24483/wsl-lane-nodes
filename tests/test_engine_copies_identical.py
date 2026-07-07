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
import os, sys

THIS_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANE_NODES_COPY = os.path.join(THIS_REPO, 'wsl_scoring_engine.py')
SYSTEMS_COPY = os.path.join(os.path.dirname(THIS_REPO),
                            'WSL Systems', 'wsl_scoring_engine.py')

fails = []
def chk(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'   [{extra}]' if (extra and not cond) else ''))
    if not cond: fails.append(name)


def normalized_bytes(path):
    """File bytes with line endings normalized to LF."""
    with open(path, 'rb') as f:
        data = f.read()
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


if (not os.path.exists(SYSTEMS_COPY)
        and os.environ.get('WSL_ENGINE_MIRROR_OPTIONAL') == '1'):
    print('SKIPPED: WSL Systems sibling checkout not present and '
          'WSL_ENGINE_MIRROR_OPTIONAL=1 (lane-Pi checkout). The engine-copy '
          'drift guard DID NOT RUN — it must pass on a machine with both repos.')
    sys.exit(0)

a = b = None
try:
    a = normalized_bytes(LANE_NODES_COPY)
    chk('wsl-lane-nodes copy readable', True)
except OSError as e:
    chk('wsl-lane-nodes copy readable', False, str(e))
try:
    b = normalized_bytes(SYSTEMS_COPY)
    chk('WSL Systems copy readable (sibling repo checked out)', True)
except OSError as e:
    # Missing sibling is a hard FAIL, not a skip — a silent skip would let
    # single-sided edits through, which is exactly what this test prevents.
    chk('WSL Systems copy readable (sibling repo checked out)', False, str(e))

if a is not None and b is not None:
    if a == b:
        chk('engine copies byte-identical (line-ending-normalized)', True)
    else:
        # Point at the first divergence so the drift is easy to find.
        la, lb = a.split(b'\n'), b.split(b'\n')
        first = next((i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y),
                     min(len(la), len(lb)) + 1)
        chk('engine copies byte-identical (line-ending-normalized)', False,
            f'first divergence at line {first} '
            f'({len(la)} vs {len(lb)} lines) — edit landed in only one repo?')

print()
print('ALL ENGINE-COPY CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
