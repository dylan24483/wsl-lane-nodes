"""M2 evidence — minimal repro for the KiCad 10.0.2 route_revD.py --check-only crash
(Codex NO-GO audit finding M2, remediated 2026-07-21).

Tracked copy of the repro cited by docs/phase8_revD_run_log.md ("BOARD CHAIN
REMEDIATION" / M2 entry). Originally written as tmp/m2_repro.py — but tmp/ is
gitignored, so the audit-trail citation pointed at an artifact that existed only on
one laptop (post-remediation review finding). Moved here verbatim except: paths made
repo-relative and output goes to stdout, so it runs from a clean clone.

WHAT IT DEMONSTRATES (against the PRE-fix route_revD_lib, i.e. any checkout before
commit 496d8c2): after `Router.clear_tracks()` used `BOARD.Remove()` (detach without
destroy), the subsequent `board.Zones()` iteration either segfaults or yields raw
`SwigPyObject` entries with no `GetIsRuleArea` attribute — the exact AttributeError
the audit hit. Against the FIXED lib (`BOARD.Delete()`), it prints the copper-zone
count and exits 0.

RUN WITH KiCad's bundled python (pcbnew is not importable from a stock CPython):
  "C:/Program Files/KiCad/10.0/bin/python.exe" scripts/repro_m2_getisrulearea.py
"""
import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import pcbnew  # noqa: E402  (needs KiCad bundled python)


def main():
    from route_revD_lib import Router, assert_netclasses_active
    board = pcbnew.LoadBoard(
        os.path.join(REPO, "kicad", "revD", "wsl-phase8b-revD.kicad_pcb"))
    assert_netclasses_active(board)
    r = Router(board)
    removed = r.clear_tracks()
    print("removed", removed)
    print("Zones type:", type(board.Zones()))
    try:
        keep = [z for z in board.Zones() if not z.GetIsRuleArea()]
        print("ok, copper zones:", len(keep))
        print("RESULT: PASS (fixed lib — Delete() keeps the zone container sane)")
        return 0
    except Exception:
        traceback.print_exc()
        try:
            zs = board.Zones()
            print("elem types:", set(type(z).__name__ for z in zs))
        except Exception:
            traceback.print_exc()
        print("RESULT: REPRODUCED the M2 failure (pre-fix lib)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
