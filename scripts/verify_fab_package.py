#!/usr/bin/env python3
"""Verify a rev-D fab package against its own manifest.json before upload.

Usage:  py -3 scripts/verify_fab_package.py kicad/fab_revD_2026-07-27_r10

Checks, fail-closed (any failure => exit 1):
  1. Every manifest 'files' entry exists with the recorded byte size and SHA-256.
  2. No stray files on disk inside the package that the manifest does not list
     (manifest.json itself excepted).
  3. source_board / source_netlist SHA-256 match the LIVE repo files — this is
     the check that catches a KiCad save made after export (the stale-.lck trap).
  4. Manifest counts vs the actual CSVs: jlc_lines == upload-BOM rows,
     placed == jlc_placed == JLC-CPL rows, dnp == dnp-excluded rows,
     netlist_parts == placed + dnp, hand_solder == hand-solder-BOM rows.
  5. Upload-BOM refdes union == JLC-CPL refdes set (exact set equality).
  6. The packaged DRC report reads 0 violations / 0 unconnected / 0 footprint
     errors.
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    pkg = (REPO / sys.argv[1]).resolve() if not Path(sys.argv[1]).is_absolute() else Path(sys.argv[1])
    if not pkg.is_dir():
        fail(f"package dir not found: {pkg}")
    manifest_path = pkg / "manifest.json"
    if not manifest_path.exists():
        fail(f"no manifest.json in {pkg}")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. every manifest file exists, size + hash match
    listed = set()
    for entry in m["files"]:
        p = REPO / entry["path"]
        listed.add(p.resolve())
        if not p.exists():
            fail(f"missing file: {entry['path']}")
        if p.stat().st_size != entry["bytes"]:
            fail(f"size mismatch: {entry['path']} ({p.stat().st_size} vs {entry['bytes']})")
        if sha256_of(p) != entry["sha256"]:
            fail(f"sha256 mismatch: {entry['path']}")
    print(f"PASS: {len(m['files'])}/{len(m['files'])} manifest files verified (size + sha256)")

    # 2. no strays inside the package
    strays = [p for p in pkg.rglob("*") if p.is_file()
              and p.resolve() not in listed and p.resolve() != manifest_path.resolve()]
    if strays:
        fail("stray files not in manifest: " + ", ".join(str(s.relative_to(pkg)) for s in strays))
    print("PASS: no stray files in the package")

    # 3. live source files still hash to the manifest values (KiCad-save trap)
    for key, path_key in (("source_board_sha256", "source_board"),
                          ("source_netlist_sha256", "source_netlist")):
        src = REPO / m[path_key]
        if not src.exists():
            fail(f"source file missing: {m[path_key]}")
        if sha256_of(src) != m[key]:
            fail(f"{path_key} CHANGED since export — {m[path_key]} no longer hashes to "
                 f"{key}. DO NOT UPLOAD; re-export or restore the file.")
    print("PASS: live source board + netlist match the manifest hashes")

    # 4. counts vs the actual CSVs
    def rows(name):
        with open(pkg / "assembly" / name, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    bom = rows("wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv")
    cpl = rows("wsl-phase8b-revD-jlc-standard-pcba-cpl.csv")
    dnp = rows("wsl-phase8b-revD-dnp-excluded.csv")
    hand = rows("wsl-phase8b-revD-hand-solder-bom.csv")
    c = m["counts"]
    checks = [
        ("jlc_lines", len(bom), c["jlc_lines"]),
        ("placed (CPL rows)", len(cpl), c["placed"]),
        ("jlc_placed", len(cpl), c["jlc_placed"]),
        ("dnp", len(dnp), c["dnp"]),
        ("netlist_parts", len(cpl) + len(dnp), c["netlist_parts"]),
        ("hand_solder", len(hand), c["hand_solder"]),
    ]
    for name, got, want in checks:
        if got != want:
            fail(f"count mismatch {name}: files say {got}, manifest says {want}")
    print(f"PASS: counts {c['netlist_parts']} parts / {c['dnp']} DNP / {c['placed']} placed / "
          f"{c['jlc_placed']} JLC / {c['jlc_lines']} lines / {c['hand_solder']} hand-solder")

    # 5. BOM refdes union == CPL refdes set
    bom_refs = set()
    for r in bom:
        for ref in re.split(r"[,\s]+", r["Designator"].strip()):
            if ref:
                if ref in bom_refs:
                    fail(f"duplicate refdes in upload BOM: {ref}")
                bom_refs.add(ref)
    cpl_refs = {r["Designator"].strip() for r in cpl}
    if bom_refs != cpl_refs:
        only_bom = sorted(bom_refs - cpl_refs)[:10]
        only_cpl = sorted(cpl_refs - bom_refs)[:10]
        fail(f"BOM/CPL refdes mismatch — only in BOM: {only_bom}; only in CPL: {only_cpl}")
    print(f"PASS: BOM refdes union == CPL refdes set ({len(cpl_refs)} refs)")

    # 6. DRC report is 0/0/0
    drc_files = list((pkg / "reports").glob("DRC*")) if (pkg / "reports").is_dir() else []
    if not drc_files:
        fail("no DRC report found in reports/")
    text = drc_files[0].read_text(encoding="utf-8", errors="replace")
    nums = re.findall(r"Found (\d+) DRC violations|Found (\d+) unconnected pads|Found (\d+) Footprint errors", text)
    flat = [int(x) for tup in nums for x in tup if x != ""]
    if not nums:
        fail(f"could not parse DRC summary in {drc_files[0].name}")
    if any(flat):
        fail(f"DRC report {drc_files[0].name} is not clean: {nums}")
    print(f"PASS: DRC report {drc_files[0].name} reads 0 violations / 0 unconnected / 0 footprint errors")

    print("\nALL CHECKS PASS — package is intact and matches the live sources.")


if __name__ == "__main__":
    main()
