"""Standing gate: hash-verify the SACRED rev-C design snapshot (189 files).

Run after EVERY batch of board/doc work (campaign standing rule 1):
  py -3 scripts/verify_revC_snapshot.py
Exit 0 only on 189/189 OK. Any MISSING/MISMATCH is a stop-ship event.

Tracked version of the ad-hoc tmp/verify_revC.py (tmp/ is gitignored; the
gate tool itself must survive a clean clone — same M7 rationale as
scripts/repro_m2_getisrulearea.py). Paths are repo-relative.
"""
import hashlib
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = REPO / "backups" / "revC_design_snapshot_2026-07-19" / "MANIFEST.json"


def main():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    entries = man["files"] if "files" in man else man["entries"]
    ok = 0
    fails = []
    os.chdir(REPO)  # original_path entries are repo-relative
    for e in entries:
        p = pathlib.Path(e["original_path"])
        if not p.is_file():
            fails.append("MISSING  " + str(p))
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() == e["sha256"]:
            ok += 1
        else:
            fails.append("MISMATCH " + str(p))
    print(f"total {len(entries)}; verified OK {ok}; failures {len(fails)}")
    for f in fails:
        print("  ", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
