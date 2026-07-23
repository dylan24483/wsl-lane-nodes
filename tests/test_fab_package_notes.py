#!/usr/bin/env python3
"""R3-7 finding 7 regression guard: no CURRENT (non-superseded) rev-D fab
package may carry the false '2x the 100mA module allowance' F1 substitution
note. R3-7 re-derived the J16 module allowance from the Littelfuse 1206L020
temperature-derating table (100 mA used the 23 C hold; ~90 mA hold @85 C -> a
2x-margin allowance of ~45 mA). The corrected note flows from
export_fab_revD.py; this test fails if a frozen package (loose CSV OR inside a
bundled zip) still ships the old figure.

A package directory carrying a `_SUPERSEDED*` marker file is exempt (it is
explicitly tombstoned DO-NOT-UPLOAD).

Run: py -3 tests/test_fab_package_notes.py
"""
import io
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD = os.path.join(REPO, "kicad")

BAD = b"2x the 100mA module allowance"


def _current_fab_dirs():
    if not os.path.isdir(KICAD):
        return []
    dirs = []
    for n in sorted(os.listdir(KICAD)):
        p = os.path.join(KICAD, n)
        if not (os.path.isdir(p) and n.startswith("fab_revD_")):
            continue
        if any(f.startswith("_SUPERSEDED") for f in os.listdir(p)):
            continue    # tombstoned package — exempt
        dirs.append(p)
    return dirs


def _offenders_in_zip(path):
    hits = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            data = z.read(name)
            if BAD in data:
                hits.append(f"{os.path.basename(path)}:{name}")
            elif name.endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as nz:
                        for nn in nz.namelist():
                            if BAD in nz.read(nn):
                                hits.append(f"{os.path.basename(path)}:{name}:{nn}")
                except zipfile.BadZipFile:
                    pass
    return hits


def test_no_current_fab_package_carries_the_100mA_note():
    offenders = []
    for d in _current_fab_dirs():
        for root, _dirs, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, KICAD)
                if f.endswith(".zip"):
                    offenders += [f"{rel} -> {h}" for h in _offenders_in_zip(p)]
                else:
                    try:
                        if BAD in open(p, "rb").read():
                            offenders.append(rel)
                    except OSError:
                        pass
    assert not offenders, (
        "current rev-D fab package(s) still carry the false '2x the 100mA "
        "module allowance' F1 note (R3-7 re-derived it to 45mA): "
        + "; ".join(offenders))


if __name__ == "__main__":
    try:
        test_no_current_fab_package_carries_the_100mA_note()
        print("PASS no current fab package carries the 100mA note")
        print("checked dirs:", [os.path.basename(d) for d in _current_fab_dirs()])
        sys.exit(0)
    except AssertionError as e:
        print("FAIL", e)
        sys.exit(1)
