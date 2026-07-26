#!/usr/bin/env python3
"""Rev-D fab-note/part-lock regression guard for CURRENT packages.

R3-7 finding 7: no CURRENT (non-superseded) rev-D fab
package may carry the false '2x the 100mA module allowance' F1 substitution
note. R3-7 re-derived the J16 module allowance from the Littelfuse 1206L020
temperature-derating table (100 mA used the 23 C hold; ~90 mA hold @85 C -> a
2x-margin allowance of ~45 mA). The corrected note flows from
export_fab_revD.py; this test fails if a frozen package (loose CSV OR inside a
bundled zip) still ships the old figure.

Round-4/5 (2026-07-23): the current package must also carry the fail-closed
J16 substitute rule (minimum Ihold at 85 C >=90mA; trip equivalence rejected)
and the dedicated C17713 / 0805W8F4702T5E 47k line for exactly 40 PC817
collector pull-ups. It must bind that arithmetic to disabled RP2040 fast-input
pulls and zeroed/read-back MCP input GPPU registers, with the 10k diagnostic-tap
drain pull-ups explicitly out of scope.

A package directory carrying a `_SUPERSEDED*` marker file is exempt (it is
explicitly tombstoned DO-NOT-UPLOAD).

Run: py -3 tests/test_fab_package_notes.py
"""
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD = os.path.join(REPO, "kicad")
FIRST_ARTICLE_PACK = os.path.join(
    REPO, "docs", "phase8_revD_first_article_pack.md"
)
FIRST_ARTICLE_MAP = os.path.join(
    REPO, "docs", "phase8_revD_first_article_refdes_map.csv"
)
REVD_GENERATOR = os.path.join(REPO, "scripts", "generate_kicad_netlist_revD.py")
REVD_ERC = os.path.join(REPO, "generate_kicad_netlist_revD.erc")
REVD_NETLIST = os.path.join(REPO, "kicad", "wsl-phase8b-revD.net")
FW_RELEASE_DIR = os.path.join(REPO, "firmware", "rp2040", "release")
FW_RELEASE_MANIFEST = os.path.join(FW_RELEASE_DIR, "firmware_manifest.json")
STALE_SCRIPTS_ERC = os.path.join(
    REPO, "scripts", "generate_kicad_netlist_revD.erc"
)
EXPORT_SCRIPT = os.path.join(REPO, "scripts", "export_fab_revD.py")


def _pinned(name):
    """Read a pinned EXPECTED_* release count out of export_fab_revD.py.

    r6 (2026-07-25) moved the part/DNP counts (271 -> 391, 28 -> 68) and these
    assertions carried their own THIRD hardcoded copy, so they failed on a
    correct board. Scraping the single pinned source keeps the test honest
    without inventing a competing constant: export_fab_revD.py is the release
    gate that fails closed on drift, this test proves the netlist / pack / CSV /
    package all agree with it. `import` is not usable here - the export module
    requires KiCad's bundled `pcbnew`.
    """
    with open(EXPORT_SCRIPT, encoding="utf-8") as stream:
        match = re.search(rf"^{name}\s*=\s*(\d+)", stream.read(), re.M)
    assert match, f"{name} not found in scripts/export_fab_revD.py"
    return int(match.group(1))

BAD = b"2x the 100mA module allowance"
REQUIRED_F1 = (
    b"minimum Ihold at 85C >=90mA",
    b"Trip-current equivalence is not an acceptance criterion",
)
REQUIRED_RPU = (
    b"C17713",
    b"0805W8F4702T5E",
    b"47k 1% 1/8W 0805 resistor",
)
REQUIRED_BIAS_GATE = (
    b"GP6-GP13",
    b"GPPUA/GPPUB",
    b"read back 0x00",
    b"R_TAPPU_* 10k",
    b"rel-0c746b5747143b8011b01d43",
    b"05d808411db4bb0d",
    b"d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae",
    b"supported_board_revisions",
    b"revD",
    b"ea8ea4ceb273df98e888aeb5d1f1327d39577e8492fda455c932fea3768bd7b5",
    b"revD|rel-0c746b5747143b8011b01d43|05d808411db4bb0d",
)


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


def test_current_fab_package_carries_input_and_f1_locks():
    dirs = _current_fab_dirs()
    assert dirs, "no current rev-D fab package found"
    missing = []
    for d in dirs:
        locks = []
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith("-part-lock.csv"):
                    locks.append(open(os.path.join(root, f), "rb").read())
        joined = b"\n".join(locks)
        for marker in REQUIRED_F1 + REQUIRED_RPU:
            if marker not in joined:
                missing.append(f"{os.path.basename(d)} missing {marker!r}")
        if b",40," not in joined:
            missing.append(f"{os.path.basename(d)} missing quantity-40 part-lock row")
        package_evidence_parts = [
            open(os.path.join(d, name), "rb").read()
            for name in ("README-fab-package.txt", "manifest.json")
            if os.path.isfile(os.path.join(d, name))
        ]
        for name in os.listdir(d):
            if not name.endswith("-fab-package.zip"):
                continue
            with zipfile.ZipFile(os.path.join(d, name)) as z:
                for member in ("README-fab-package.txt", "manifest.json"):
                    if member in z.namelist():
                        package_evidence_parts.append(z.read(member))
        package_evidence = b"\n".join(package_evidence_parts)
        for marker in REQUIRED_BIAS_GATE:
            if marker not in package_evidence:
                missing.append(f"{os.path.basename(d)} missing package gate {marker!r}")
    assert not missing, "; ".join(missing)


def test_first_article_dnp_count_matches_csv_and_current_package():
    with open(FIRST_ARTICLE_MAP, newline="", encoding="utf-8") as stream:
        map_dnp = {
            row["Ref"] for row in csv.DictReader(stream)
            if row["DNP"] == "DNP"
        }
    expected_dnp = _pinned("EXPECTED_DNP")
    assert len(map_dnp) == expected_dnp, (
        f"first-article CSV DNP count is {len(map_dnp)}, not the pinned "
        f"{expected_dnp}")
    assert "JP1" in map_dnp, "first-article CSV omits default-open JP1 from DNP"

    with open(FIRST_ARTICLE_PACK, encoding="utf-8") as stream:
        pack = stream.read()
    match = re.search(r"DNP refs \((\d+), listed in the CSV\)", pack)
    assert match, "first-article pack has no machine-checkable DNP count"
    assert int(match.group(1)) == len(map_dnp), (
        f"first-article pack says {match.group(1)} DNP but CSV contains "
        f"{len(map_dnp)}"
    )

    dirs = _current_fab_dirs()
    assert len(dirs) == 1, (
        "exactly one rev-D fab package may be current, got "
        + ", ".join(os.path.basename(path) for path in dirs)
    )
    dnp_csvs = []
    for root, _dirs, files in os.walk(dirs[0]):
        dnp_csvs.extend(
            os.path.join(root, name)
            for name in files
            if name.endswith("-dnp-excluded.csv")
        )
    assert len(dnp_csvs) == 1, "current package must contain one DNP exclusion CSV"
    with open(dnp_csvs[0], newline="", encoding="utf-8") as stream:
        package_dnp = {row["Designator"] for row in csv.DictReader(stream)}
    assert package_dnp == map_dnp, (
        "first-article/current-package DNP mismatch: "
        f"map-only={sorted(map_dnp - package_dnp)} "
        f"package-only={sorted(package_dnp - map_dnp)}"
    )


def test_current_package_source_hashes_match_live_design():
    dirs = _current_fab_dirs()
    assert len(dirs) == 1, "source binding requires exactly one current package"
    with open(os.path.join(dirs[0], "manifest.json"), encoding="utf-8") as stream:
        manifest = json.load(stream)
    for path_key, hash_key in (
        ("source_board", "source_board_sha256"),
        ("source_netlist", "source_netlist_sha256"),
    ):
        source_path = os.path.join(REPO, *manifest[path_key].split("/"))
        with open(source_path, "rb") as stream:
            actual = hashlib.sha256(stream.read()).hexdigest()
        assert actual == manifest[hash_key], (
            f"{path_key} drifted from current package: "
            f"{actual} != {manifest[hash_key]}"
        )


def test_current_package_manifest_hashes_every_member_and_firmware_policy():
    dirs = _current_fab_dirs()
    assert len(dirs) == 1, "package integrity requires exactly one current package"
    with open(os.path.join(dirs[0], "manifest.json"), encoding="utf-8") as stream:
        manifest = json.load(stream)

    mismatches = []
    for record in manifest["files"]:
        path = os.path.join(REPO, *record["path"].split("/"))
        if not os.path.isfile(path):
            mismatches.append(f"missing {record['path']}")
            continue
        with open(path, "rb") as stream:
            actual_hash = hashlib.sha256(stream.read()).hexdigest()
        actual_bytes = os.path.getsize(path)
        if actual_hash != record["sha256"] or actual_bytes != record["bytes"]:
            mismatches.append(
                f"{record['path']} bytes/hash "
                f"{actual_bytes}/{actual_hash} != "
                f"{record['bytes']}/{record['sha256']}"
            )
    assert not mismatches, "; ".join(mismatches)

    with open(FW_RELEASE_MANIFEST, "rb") as stream:
        release_manifest_bytes = stream.read()
    release_manifest = json.loads(release_manifest_bytes)
    production = manifest["production_firmware"]
    assert production["supported_board_revisions"] == ["revD"]
    assert release_manifest["supported_board_revisions"] == ["revD"]
    assert production["qualified_releases"] == release_manifest["qualified_releases"]
    assert production["qualified_releases"] == [
        "revD|rel-0c746b5747143b8011b01d43|05d808411db4bb0d"
    ]
    assert production["manifest_sha256"] == hashlib.sha256(
        release_manifest_bytes
    ).hexdigest()
    release_image = next(
        image for image in release_manifest["images"]
        if image["variant"] == "release" and not image["bench_only"]
    )
    assert production["sha256"] == release_image["image"]["sha256"]


def test_revD_erc_artifact_is_canonical():
    with open(REVD_ERC, "rb") as stream:
        lines = stream.read().splitlines()
    expected = sorted(
        lines,
        key=lambda line: (
            0 if line.startswith(b"ERC ERROR") else
            1 if line.startswith(b"ERC WARNING") else
            2,
            line,
        ),
    )
    assert lines == expected, "Rev-D ERC rows are not in deterministic order"
    assert sum(line.startswith(b"ERC ERROR") for line in lines) == 1
    assert sum(line.startswith(b"ERC WARNING") for line in lines) == 39


def test_revD_generator_has_one_repo_root_erc_custodian():
    assert not os.path.exists(STALE_SCRIPTS_ERC), (
        "stale scripts/generate_kicad_netlist_revD.erc must not exist"
    )
    with open(REVD_GENERATOR, encoding="utf-8") as stream:
        source = stream.read()
    assert 'ERC_ARTIFACT = REPO_ROOT / f"{SCRIPT_PATH.stem}.erc"' in source
    assert "os.chdir(REPO_ROOT)" in source
    assert 'child_env["PYTHONHASHSEED"] = "0"' in source
    assert "erc_candidates" not in source
    assert "pathlib.Path.cwd() /" not in source


def test_revD_netlist_has_no_volatile_skidl_line_numbers():
    with open(REVD_NETLIST, encoding="utf-8") as stream:
        netlist = stream.read()
    assert netlist.count(
        '(source "scripts/generate_kicad_netlist_revD.py")'
    ) == 2
    fields = re.findall(
        r'\(name "SKiDL Line"\) "generate_kicad_netlist_revD\.py:([^"]+)"',
        netlist,
    )
    expected_parts = _pinned("EXPECTED_NETLIST_PARTS")
    assert len(fields) == expected_parts, (
        f"expected {expected_parts} SKiDL Line fields, got {len(fields)}")
    assert set(fields) == {"0"}, f"volatile SKiDL source lines remain: {set(fields)}"


if __name__ == "__main__":
    try:
        test_no_current_fab_package_carries_the_100mA_note()
        test_current_fab_package_carries_input_and_f1_locks()
        test_first_article_dnp_count_matches_csv_and_current_package()
        test_current_package_source_hashes_match_live_design()
        test_current_package_manifest_hashes_every_member_and_firmware_policy()
        test_revD_erc_artifact_is_canonical()
        test_revD_generator_has_one_repo_root_erc_custodian()
        test_revD_netlist_has_no_volatile_skidl_line_numbers()
        print(
            "PASS current fab package notes, input-bias gate, part locks, "
            "DNP set, source binding, and deterministic ERC"
        )
        print("checked dirs:", [os.path.basename(d) for d in _current_fab_dirs()])
        sys.exit(0)
    except AssertionError as e:
        print("FAIL", e)
        sys.exit(1)
