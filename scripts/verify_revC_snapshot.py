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
REV_B_SPEC = REPO / "docs" / "phase8b_pcb_revB_spec.md"
REV_B_SPEC_SNAPSHOT = (
    REPO
    / "backups"
    / "revC_design_snapshot_2026-07-19"
    / "docs"
    / "phase8b_pcb_revB_spec.md"
)
REV_B_SPEC_TITLE = b"# Phase 8 - PCB Rev-B Schematic Contract\n\n"
REV_B_SPEC_SAFETY_NOTICE = (
    b"> \xe2\x9b\x94 **FROZEN REV-B ELECTRICAL RECORD \xe2\x80\x94 NOT CURRENT FIELD-WIRING, SAFETY,\n"
    b"> OR CUTOVER AUTHORITY.** The PCB topology and fabrication record below remain\n"
    b"> historical evidence only. Its external TB/SC J_SAFE1-2 loop, assumed Stop/C.I.S.\n"
    b"> chain, and v1.1-era operational conclusions are superseded. Lane 21/22 uses\n"
    b"> Candidate C: a controlled J_SAFE1-2 jumper, the powered-proven OEM parallel\n"
    b"> closed-when-safe S/T coil ladder, and a mandatory per-lane G3 S-and-T coil-drop\n"
    b"> insertion proof. A 2026-07-24 inspection found no C.I.S. device or wiring on\n"
    b"> those lanes; the other pit-interlock disposition and approved Stop/control-power\n"
    b"> interface remain open, so J14.3\xe2\x80\x934 stays OPEN and the field rail must not arm.\n"
    b"> Use `phase8_interlock_redesign.md`, the lane harness build sheet, current\n"
    b"> `manual_src/`, and the Track-B cutover runbook for Rev-D work.\n\n"
)


def _matches_rev_b_snapshot_with_safety_notice(data, expected_sha):
    """Allow one exact additive notice while keeping the frozen body byte-exact."""
    frozen = REV_B_SPEC_SNAPSHOT.read_bytes()
    if hashlib.sha256(frozen).hexdigest() != expected_sha:
        return False
    if not frozen.startswith(REV_B_SPEC_TITLE):
        return False
    expected = frozen.replace(
        REV_B_SPEC_TITLE,
        REV_B_SPEC_TITLE + REV_B_SPEC_SAFETY_NOTICE,
        1,
    )
    return data == expected


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
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() == e["sha256"]:
            ok += 1
        elif (
            p.resolve() == REV_B_SPEC.resolve()
            and _matches_rev_b_snapshot_with_safety_notice(data, e["sha256"])
        ):
            ok += 1
        else:
            fails.append("MISMATCH " + str(p))
    print(f"total {len(entries)}; verified OK {ok}; failures {len(fails)}")
    for f in fails:
        print("  ", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
