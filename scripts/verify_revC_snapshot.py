"""Standing gate: verify the self-contained SACRED rev-C archive (189 files).

Run after EVERY batch of board/doc work (campaign standing rule 1):
  py -3 scripts/verify_revC_snapshot.py --compare-checkout
Exit 0 only on 189/189 OK. Any MISSING/MISMATCH is a stop-ship event.

The tracked ZIP contains the original manifest plus the exact 189 baseline
files, so archive integrity is clean-clone reproducible and independent of
checkout line-ending conversion. ``--compare-checkout`` separately checks the
173 release-tracked Rev-C paths semantically (byte-exact for binary files,
line-ending-insensitive for UTF-8 text, with one exact safety-notice exception).
``--expanded-root`` verifies an explicitly supplied expanded recovery copy
byte-for-byte; there is no silent fallback to workstation-only paths.
"""
import argparse
import hashlib
import json
import pathlib
import re
import stat
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE = REPO / "release_evidence" / "revC_design_snapshot_2026-07-19.zip"
ARCHIVE_SIDECAR = ARCHIVE.with_suffix(ARCHIVE.suffix + ".sha256")
EXPECTED_ARCHIVE_SHA256 = (
    "d785b267f7b43fa580e933d22e5afa87c79a0f2a036ff35c9e9159ff2153c638"
)
EXPECTED_FILE_COUNT = 189
EXPECTED_TOTAL_BYTES = 29_868_830
EXPECTED_ARCHIVE_MEMBER_COUNT = EXPECTED_FILE_COUNT + 1
MANIFEST_MEMBER = "MANIFEST.json"
REV_B_SPEC_PATH = "docs/phase8b_pcb_revB_spec.md"
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
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ARCHIVE_ONLY_PATHS = frozenset(
    {
        "generate_kicad_netlist_revB.log",
        "kicad/fab_revB_routed_manual/reports/audit-revB-board.log",
        "kicad/fab_revB_routed_manual/reports/export-drill.log",
        "kicad/fab_revB_routed_manual/reports/export-gerbers.log",
        "kicad/fab_revB_routed_manual/reports/export-ipcd356.log",
        "kicad/fab_revB_routed_manual/reports/export-pos.log",
        "kicad/fab_revB_routed_manual/reports/export-review-pdf.log",
        "kicad/fab_revB_routed_manual/reports/export-stats-json.log",
        "kicad/fab_revB_routed_manual/reports/export-stats-report.log",
        "kicad/fab_revB_routed_manual/reports/kicad-drc.log",
        "kicad/fab_revB_routed_manual/reports/prepare-hand-solder-procurement.log",
        "kicad/fab_revB_routed_manual/reports/prepare-jlc-standard-pcba.log",
        "kicad/fab_revB_routed_manual/reports/prepare-pcba-parts.log",
        "kicad/freerouting-revB-pass1.log",
        "kicad/freerouting-revB-pass2-2layer.log",
        "skidl_REPL.log",
    }
)


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_path(raw_path, *, label):
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\\" in raw_path
        or ":" in raw_path
    ):
        raise ValueError(f"{label} has an invalid POSIX path")
    rel = pathlib.PurePosixPath(raw_path)
    if (
        rel.is_absolute()
        or "." in rel.parts
        or ".." in rel.parts
        or str(rel) != raw_path
    ):
        raise ValueError(f"{label} escapes or is not canonical")
    return rel


def _load_manifest(raw):
    try:
        man = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"embedded manifest is invalid UTF-8 JSON: {exc}") from exc

    entries = man.get("files")
    if not isinstance(entries, list):
        raise ValueError("embedded manifest files must be a list")
    if man.get("file_count") != EXPECTED_FILE_COUNT or len(entries) != EXPECTED_FILE_COUNT:
        raise ValueError(
            f"embedded manifest must contain exactly {EXPECTED_FILE_COUNT} files"
        )
    if man.get("total_bytes") != EXPECTED_TOTAL_BYTES:
        raise ValueError(
            f"embedded manifest total_bytes must be exactly {EXPECTED_TOTAL_BYTES}"
        )

    seen = set()
    parsed = []
    byte_total = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"embedded manifest entry {index} must be an object")
        raw_path = entry.get("relative_path")
        rel = _safe_member_path(raw_path, label=f"manifest entry {index}")
        expected_bytes = entry.get("bytes")
        expected_sha = entry.get("sha256")
        if raw_path in seen:
            raise ValueError(f"embedded manifest has duplicate path {raw_path}")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ValueError(f"manifest entry {raw_path} has invalid byte count")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            raise ValueError(f"manifest entry {raw_path} has invalid sha256")
        seen.add(raw_path)
        byte_total += expected_bytes
        parsed.append((rel, expected_bytes, expected_sha))

    if byte_total != EXPECTED_TOTAL_BYTES:
        raise ValueError(
            f"manifest entry bytes total {byte_total}, expected {EXPECTED_TOTAL_BYTES}"
        )
    if [str(item[0]) for item in parsed] != sorted(seen):
        raise ValueError("embedded manifest paths must be unique and sorted")
    if not ARCHIVE_ONLY_PATHS.issubset(seen):
        raise ValueError("embedded manifest is missing an archive-only evidence path")
    return parsed


def _verify_archive():
    if not ARCHIVE.is_file():
        raise ValueError(f"tracked archive is missing: {ARCHIVE}")
    try:
        sidecar = ARCHIVE_SIDECAR.read_text(encoding="utf-8").split()
    except OSError as exc:
        raise ValueError(f"cannot read archive sidecar: {exc}") from exc
    if sidecar != [EXPECTED_ARCHIVE_SHA256, ARCHIVE.name]:
        raise ValueError("archive sidecar is not the pinned hash and filename")
    actual_archive_sha = _sha256_file(ARCHIVE)
    if actual_archive_sha != EXPECTED_ARCHIVE_SHA256:
        raise ValueError(
            f"archive sha256 mismatch: {actual_archive_sha} "
            f"!= {EXPECTED_ARCHIVE_SHA256}"
        )

    try:
        with zipfile.ZipFile(ARCHIVE, "r") as zf:
            infos = zf.infolist()
            if len(infos) != EXPECTED_ARCHIVE_MEMBER_COUNT:
                raise ValueError(
                    "archive must contain exactly the manifest plus "
                    f"{EXPECTED_FILE_COUNT} files"
                )
            names = []
            info_by_name = {}
            for index, info in enumerate(infos):
                rel = _safe_member_path(info.filename, label=f"ZIP member {index}")
                name = str(rel)
                if info.is_dir():
                    raise ValueError(f"ZIP member {name} must be a regular file")
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and stat.S_ISLNK(mode):
                    raise ValueError(f"ZIP member {name} must not be a symlink")
                if info.flag_bits & 0x1:
                    raise ValueError(f"ZIP member {name} must not be encrypted")
                if name in info_by_name:
                    raise ValueError(f"ZIP has duplicate member {name}")
                names.append(name)
                info_by_name[name] = info
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError("ZIP has a case-insensitive member collision")
            if MANIFEST_MEMBER not in info_by_name:
                raise ValueError("ZIP is missing MANIFEST.json")

            entries = _load_manifest(zf.read(info_by_name[MANIFEST_MEMBER]))
            expected_names = {MANIFEST_MEMBER}
            expected_names.update(str(item[0]) for item in entries)
            if set(names) != expected_names:
                extras = sorted(set(names) - expected_names)
                missing = sorted(expected_names - set(names))
                raise ValueError(
                    f"ZIP member set mismatch; extras={extras}, missing={missing}"
                )

            failures = []
            archive_data = {}
            for rel, expected_bytes, expected_sha in entries:
                name = str(rel)
                info = info_by_name[name]
                if info.file_size != expected_bytes:
                    failures.append(
                        f"SIZE     {name}: {info.file_size} != {expected_bytes}"
                    )
                    continue
                digest = hashlib.sha256()
                chunks = []
                byte_count = 0
                with zf.open(info, "r") as member:
                    while True:
                        chunk = member.read(1024 * 1024)
                        if not chunk:
                            break
                        byte_count += len(chunk)
                        digest.update(chunk)
                        chunks.append(chunk)
                if byte_count != expected_bytes or digest.hexdigest() != expected_sha:
                    failures.append(f"MISMATCH {name}")
                    continue
                archive_data[name] = b"".join(chunks)
            if failures:
                raise ValueError("; ".join(failures))
            if zf.testzip() is not None:
                raise ValueError("ZIP CRC verification failed")
            return entries, archive_data
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError(f"cannot verify tracked archive: {exc}") from exc


def _is_link_like(path):
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _contained_file(root, rel):
    root = root.absolute()
    if _is_link_like(root):
        raise ValueError(f"supplied root must not be a symlink or junction: {root}")
    root_resolved = root.resolve()
    lexical_target = root
    for part in rel.parts:
        lexical_target /= part
        if _is_link_like(lexical_target):
            raise ValueError(f"path contains a symlink or junction: {rel}")
    target = lexical_target.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"path escapes supplied root: {rel}")
    return target


def _verify_expanded(root, entries):
    failures = []
    ok = 0
    for rel, expected_bytes, expected_sha in entries:
        target = _contained_file(root, rel)
        if not target.is_file():
            failures.append(f"MISSING  {rel}")
            continue
        if target.stat().st_size != expected_bytes:
            failures.append(f"SIZE     {rel}")
            continue
        if _sha256_file(target) != expected_sha:
            failures.append(f"MISMATCH {rel}")
            continue
        ok += 1
    return ok, failures


def _normalize_utf8_eol(data):
    if b"\0" in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _matches_safety_notice(current, frozen):
    normalized_current = _normalize_utf8_eol(current)
    normalized_frozen = _normalize_utf8_eol(frozen)
    if normalized_current is None or normalized_frozen is None:
        return False
    expected = normalized_frozen.replace(
        REV_B_SPEC_TITLE,
        REV_B_SPEC_TITLE + REV_B_SPEC_SAFETY_NOTICE,
        1,
    )
    return normalized_frozen.startswith(REV_B_SPEC_TITLE) and normalized_current == expected


def _verify_checkout(root, entries, archive_data):
    failures = []
    ok = 0
    matches = {
        "byte_exact": 0,
        "eol_equivalent": 0,
        "safety_notice": 0,
    }
    for rel, _, _ in entries:
        name = str(rel)
        if name in ARCHIVE_ONLY_PATHS:
            continue
        target = _contained_file(root, rel)
        if not target.is_file():
            failures.append(f"MISSING  {rel}")
            continue
        current = target.read_bytes()
        frozen = archive_data[name]
        if current == frozen:
            ok += 1
            matches["byte_exact"] += 1
            continue
        current_text = _normalize_utf8_eol(current)
        frozen_text = _normalize_utf8_eol(frozen)
        if current_text is not None and current_text == frozen_text:
            ok += 1
            matches["eol_equivalent"] += 1
            continue
        if name == REV_B_SPEC_PATH and _matches_safety_notice(current, frozen):
            ok += 1
            matches["safety_notice"] += 1
            continue
        failures.append(f"MISMATCH {rel}")
    expected = EXPECTED_FILE_COUNT - len(ARCHIVE_ONLY_PATHS)
    if ok + len(failures) != expected:
        failures.append(
            f"INTERNAL expected {expected} checkout paths, saw {ok + len(failures)}"
        )
    return ok, failures, matches


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compare-checkout",
        action="store_true",
        help="also compare the 173 release-tracked Rev-C paths in this checkout",
    )
    parser.add_argument(
        "--expanded-root",
        type=pathlib.Path,
        help="also verify an explicitly supplied expanded 189-file recovery copy",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        entries, archive_data = _verify_archive()
    except ValueError as exc:
        print(f"ARCHIVE INVALID: {exc}")
        return 1
    print(
        f"archive total {len(entries)}; verified OK {len(entries)}; "
        "failures 0"
    )

    failed = False
    if args.compare_checkout:
        ok, failures, matches = _verify_checkout(REPO, entries, archive_data)
        print(
            f"checkout total {EXPECTED_FILE_COUNT - len(ARCHIVE_ONLY_PATHS)}; "
            f"verified OK {ok}; archive-only {len(ARCHIVE_ONLY_PATHS)}; "
            f"failures {len(failures)}; byte-exact {matches['byte_exact']}; "
            f"EOL-equivalent {matches['eol_equivalent']}; "
            f"safety-notice {matches['safety_notice']}"
        )
        for failure in failures:
            print("  ", failure)
        failed = failed or bool(failures)

    if args.expanded_root is not None:
        root = args.expanded_root
        if not root.is_dir():
            print(f"EXPANDED ROOT INVALID: not a directory: {root}")
            return 1
        ok, failures = _verify_expanded(root, entries)
        print(
            f"expanded total {len(entries)}; verified OK {ok}; "
            f"failures {len(failures)}"
        )
        for failure in failures:
            print("  ", failure)
        failed = failed or bool(failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
