import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "release_evidence" / "revC_design_snapshot_2026-07-19.zip"
SIDECAR = ARCHIVE.with_suffix(ARCHIVE.suffix + ".sha256")
VERIFY = ROOT / "scripts" / "verify_revC_snapshot.py"
EXPECTED_SHA256 = "d785b267f7b43fa580e933d22e5afa87c79a0f2a036ff35c9e9159ff2153c638"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_revC_snapshot", VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revC_archive_is_pinned_clone_portable_and_complete():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == EXPECTED_SHA256
    assert SIDECAR.read_text(encoding="utf-8").split() == [
        EXPECTED_SHA256,
        ARCHIVE.name,
    ]

    with zipfile.ZipFile(ARCHIVE, "r") as archive:
        infos = archive.infolist()
        assert len(infos) == 190
        assert len({info.filename for info in infos}) == 190
        manifest = json.loads(archive.read("MANIFEST.json").decode("utf-8"))

    entries = manifest["files"]
    assert manifest["file_count"] == 189 == len(entries)
    assert manifest["total_bytes"] == 29_868_830
    assert manifest["total_bytes"] == sum(entry["bytes"] for entry in entries)
    paths = [entry["relative_path"] for entry in entries]
    assert len(paths) == len(set(paths)) == 189
    assert all(not pathlib.PurePosixPath(path).is_absolute() for path in paths)
    assert all(".." not in pathlib.PurePosixPath(path).parts for path in paths)


@pytest.mark.parametrize(
    "member",
    [
        "../escape",
        "/absolute",
        "C:/drive",
        "folder\\windows",
        "folder//noncanonical",
        "folder/./noncanonical",
    ],
)
def test_revC_gate_rejects_unsafe_or_noncanonical_member_names(member):
    verifier = _load_verifier()
    with pytest.raises(ValueError):
        verifier._safe_member_path(member, label="test member")


def test_revC_gate_rejects_archive_byte_mutation(tmp_path):
    verifier = _load_verifier()
    mutated = tmp_path / ARCHIVE.name
    mutated_sidecar = mutated.with_suffix(mutated.suffix + ".sha256")
    shutil.copyfile(ARCHIVE, mutated)
    shutil.copyfile(SIDECAR, mutated_sidecar)
    with mutated.open("r+b") as stream:
        stream.seek(-1, 2)
        original = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([original[0] ^ 0x01]))

    verifier.ARCHIVE = mutated
    verifier.ARCHIVE_SIDECAR = mutated_sidecar
    with pytest.raises(ValueError, match="archive sha256 mismatch"):
        verifier._verify_archive()


def test_revC_gate_rejects_link_like_expanded_members(tmp_path, monkeypatch):
    verifier = _load_verifier()
    root = tmp_path / "expanded"
    root.mkdir()
    alias = root / "alias"
    alias.write_bytes(b"not a real expanded member")

    monkeypatch.setattr(
        verifier,
        "_is_link_like",
        lambda path: path == alias,
    )
    with pytest.raises(ValueError, match="symlink or junction"):
        verifier._contained_file(root, pathlib.PurePosixPath("alias"))


def test_revC_gate_verifies_archive_and_invoking_checkout_from_external_cwd(tmp_path):
    result = subprocess.run(
        [sys.executable, str(VERIFY), "--compare-checkout"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "archive total 189; verified OK 189; failures 0" in result.stdout
    assert (
        "checkout total 173; verified OK 173; archive-only 16; failures 0"
        in result.stdout
    )


def test_revC_gate_verifies_an_explicit_expanded_copy(tmp_path):
    # Keep the 189-file fixture near the Windows temp root. Nesting it under
    # pytest's already-long clean-clone basetemp can exceed legacy MAX_PATH.
    with tempfile.TemporaryDirectory(prefix="revc-expanded-") as temp_dir:
        verifier = _load_verifier()
        entries, archive_data = verifier._verify_archive()
        expanded = pathlib.Path(temp_dir)
        for rel, _, _ in entries:
            target = verifier._contained_file(expanded, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive_data[str(rel)])

        result = subprocess.run(
            [
                sys.executable,
                str(VERIFY),
                "--expanded-root",
                str(expanded),
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "expanded total 189; verified OK 189; failures 0" in result.stdout
