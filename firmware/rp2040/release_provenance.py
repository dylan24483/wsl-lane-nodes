#!/usr/bin/env python3
"""Deterministic RP2040 build identity and release-bundle verification.

The on-wire ``id.build`` value is a digest of an explicit, variant-specific
set of firmware source/recipe inputs, image-affecting options, the clean Pico
SDK commit, and the C compiler ID/version. It deliberately does not inspect
the application repository's Git state, timestamps, or unrelated files.

The release manifest additionally binds the two UF2 images to their emitted
identity, the complete source/config digests, CMake caches, and full tool
version records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "wsl-rp2040-release-manifest-v1"
IDENTITY_ALGORITHM = "wsl-rp2040-controlled-inputs-v2"
COMMON_INPUTS = (
    "CMakeLists.txt",
    "config.h",
    "gen_build_id.cmake",
    "main.c",
    "pico_sdk_import.cmake",
    "release_provenance.py",
)
VARIANT_INPUTS = {
    "release": (),
    "fi1": ("fi1_bootsel.c",),
}
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30


class ProvenanceError(RuntimeError):
    """A release identity or artifact failed closed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_input_records(source_dir: Path, variant: str) -> list[dict[str, Any]]:
    if variant not in VARIANT_INPUTS:
        raise ProvenanceError(f"unsupported variant: {variant!r}")
    records: list[dict[str, Any]] = []
    for relative in sorted((*COMMON_INPUTS, *VARIANT_INPUTS[variant])):
        path = source_dir / relative
        if not path.is_file():
            raise ProvenanceError(f"controlled source input is missing: {path}")
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return records


def compute_identity(
    source_dir: Path,
    variant: str,
    *,
    debug_usb: bool = False,
    pico_board: str = "pico",
    build_type: str = "Release",
    sdk_commit: str,
    compiler_id: str,
) -> dict[str, Any]:
    """Return the exact identity compiled into one image."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", pico_board):
        raise ProvenanceError(f"invalid PICO_BOARD value: {pico_board!r}")
    if not build_type or not re.fullmatch(r"[A-Za-z0-9_.-]+", build_type):
        raise ProvenanceError(f"invalid build type: {build_type!r}")
    if not re.fullmatch(r"(?:[0-9a-f]{40}(?:-dirty)?|unversioned)", sdk_commit):
        raise ProvenanceError(f"invalid Pico SDK identity: {sdk_commit!r}")
    if not compiler_id or not re.fullmatch(r"[A-Za-z0-9_.+-]+", compiler_id):
        raise ProvenanceError(f"invalid C compiler identity: {compiler_id!r}")

    source_dir = source_dir.resolve()
    inputs = _required_input_records(source_dir, variant)
    identity_input = {
        "algorithm": IDENTITY_ALGORITHM,
        "build_options": {
            "build_type": build_type,
            "debug_usb": bool(debug_usb),
            "fi1": variant == "fi1",
            "pico_board": pico_board,
            "variant": variant,
        },
        "toolchain_inputs": {
            "c_compiler": compiler_id,
            "pico_sdk_commit": sdk_commit,
        },
        "inputs": inputs,
    }
    canonical = json.dumps(
        identity_input, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    source_sha256 = _sha256_bytes(canonical)
    config_sha256 = next(
        item["sha256"] for item in inputs if item["path"] == "config.h"
    )
    prefix = "rel" if variant == "release" else "fi1"
    return {
        **identity_input,
        "source_sha256": source_sha256,
        # 28 characters, safely below the firmware's %.32s wire cap.
        "emitted_build": f"{prefix}-{source_sha256[:24]}",
        # Exactly 16 characters, matching the firmware's %.16s wire cap.
        "config_sha256": config_sha256,
        "emitted_cfg": config_sha256[:16],
    }


def _write_if_different(path: Path, data: str) -> None:
    encoded = data.encode("utf-8")
    if path.is_file() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def write_header(args: argparse.Namespace) -> None:
    identity = compute_identity(
        args.source_dir,
        args.variant,
        debug_usb=args.debug_usb,
        pico_board=args.pico_board,
        build_type=args.build_type,
        sdk_commit=args.sdk_commit,
        compiler_id=args.compiler_id,
    )
    content = (
        "/* generated by release_provenance.py; DO NOT EDIT OR COMMIT */\n"
        f'#define WSL_BUILD_ID         "{identity["emitted_build"]}"\n'
        f'#define WSL_CFG_SHA          "{identity["emitted_cfg"]}"\n'
        f'#define WSL_SOURCE_SHA256    "{identity["source_sha256"]}"\n'
        f'#define WSL_BUILD_VARIANT    "{args.variant}"\n'
        f'#define WSL_PICO_SDK_COMMIT  "{args.sdk_commit}"\n'
        f'#define WSL_C_COMPILER_ID    "{args.compiler_id}"\n'
    )
    _write_if_different(args.output, content)


def _read_header(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProvenanceError(f"generated identity header is missing: {path}")
    values = dict(
        re.findall(
            r'^\s*#define\s+(WSL_[A-Z0-9_]+)\s+"([^"]*)"\s*$',
            path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )
    required = {
        "WSL_BUILD_ID",
        "WSL_CFG_SHA",
        "WSL_SOURCE_SHA256",
        "WSL_BUILD_VARIANT",
        "WSL_PICO_SDK_COMMIT",
        "WSL_C_COMPILER_ID",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise ProvenanceError(f"{path}: missing macros: {', '.join(missing)}")
    return values


def _run_version(executable: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProvenanceError(f"cannot query {executable}: {exc}") from exc
    lines = (completed.stdout or completed.stderr).strip().splitlines()
    if not lines:
        raise ProvenanceError(f"{executable}: empty version output")
    return lines[0].strip()


def _git_output(repo: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProvenanceError(f"cannot inspect Pico SDK Git provenance: {exc}") from exc
    return completed.stdout.strip()


def _pico_sdk_record(sdk_dir: Path) -> dict[str, Any]:
    sdk_dir = sdk_dir.resolve()
    if not (sdk_dir / "pico_sdk_init.cmake").is_file():
        raise ProvenanceError(f"not a Pico SDK checkout: {sdk_dir}")
    commit = _git_output(sdk_dir, "rev-parse", "HEAD")
    dirty = bool(_git_output(sdk_dir, "status", "--porcelain", "--untracked-files=all"))
    if dirty:
        raise ProvenanceError(
            "Pico SDK checkout is dirty; a commit hash cannot identify modified SDK inputs"
        )
    version_file = sdk_dir / "pico_sdk_version.cmake"
    version_sha256 = _sha256_file(version_file) if version_file.is_file() else None
    return {
        "git_commit": commit,
        "git_dirty": False,
        "pico_sdk_version_file_sha256": version_sha256,
    }


def _uf2_payload(path: Path) -> bytes:
    data = path.read_bytes()
    if not data or len(data) % 512:
        raise ProvenanceError(f"{path}: invalid UF2 length {len(data)}")
    segments: list[tuple[int, bytes]] = []
    for offset in range(0, len(data), 512):
        block = data[offset : offset + 512]
        magic0, magic1 = struct.unpack_from("<II", block, 0)
        target_address, payload_size = struct.unpack_from("<II", block, 12)
        magic_end = struct.unpack_from("<I", block, 508)[0]
        if (
            magic0 != UF2_MAGIC_START0
            or magic1 != UF2_MAGIC_START1
            or magic_end != UF2_MAGIC_END
            or payload_size > 476
        ):
            raise ProvenanceError(f"{path}: malformed UF2 block at byte {offset}")
        segments.append((target_address, block[32 : 32 + payload_size]))
    low = min(address for address, _ in segments)
    high = max(address + len(payload) for address, payload in segments)
    if high - low > 16 * 1024 * 1024:
        raise ProvenanceError(f"{path}: implausibly sparse UF2 address span")
    payload = bytearray(b"\xff" * (high - low))
    for address, chunk in segments:
        start = address - low
        payload[start : start + len(chunk)] = chunk
    return bytes(payload)


def _assert_identity_embedded(path: Path, build_id: str, cfg: str) -> None:
    payload = _uf2_payload(path)
    for label, value in (("id.build", build_id), ("id.cfg", cfg)):
        if value.encode("ascii") not in payload:
            raise ProvenanceError(f"{path}: emitted {label} value {value!r} not in UF2")


def _parse_cache(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProvenanceError(f"CMake cache is missing: {path}")
    wanted = {"CMAKE_BUILD_TYPE", "DEBUG_USB", "FI1_BUILD", "PICO_BOARD"}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([^/#][^:=]*):[^=]*=(.*)$", line)
        if match and match.group(1) in wanted:
            result[match.group(1)] = match.group(2)
    return result


def _cmake_compiler_identity(build_dir: Path) -> str:
    candidates = sorted((build_dir / "CMakeFiles").glob("*/CMakeCCompiler.cmake"))
    if len(candidates) != 1:
        raise ProvenanceError(
            f"{build_dir}: expected one CMakeCCompiler.cmake, found {len(candidates)}"
        )
    text = candidates[0].read_text(encoding="utf-8", errors="replace")
    compiler_id = re.search(
        r'^set\(CMAKE_C_COMPILER_ID "([^"]+)"\)', text, re.MULTILINE
    )
    compiler_version = re.search(
        r'^set\(CMAKE_C_COMPILER_VERSION "([^"]+)"\)', text, re.MULTILINE
    )
    if not compiler_id or not compiler_version:
        raise ProvenanceError(f"{candidates[0]}: missing compiler ID/version")
    return f"{compiler_id.group(1)}-{compiler_version.group(1)}"


def _firmware_version(source_dir: Path) -> str:
    text = (source_dir / "config.h").read_text(encoding="utf-8")
    match = re.search(r'^\s*#define\s+FW_VERSION\s+"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ProvenanceError("FW_VERSION is missing from config.h")
    return match.group(1)


def _image_record(
    *,
    source_dir: Path,
    variant: str,
    uf2: Path,
    header: Path,
    build_dir: Path,
    sdk_commit: str,
    compiler_id: str,
) -> dict[str, Any]:
    expected = compute_identity(
        source_dir,
        variant,
        debug_usb=False,
        pico_board="pico",
        build_type="Release",
        sdk_commit=sdk_commit,
        compiler_id=compiler_id,
    )
    actual = _read_header(header)
    exact = {
        "WSL_BUILD_ID": expected["emitted_build"],
        "WSL_CFG_SHA": expected["emitted_cfg"],
        "WSL_SOURCE_SHA256": expected["source_sha256"],
        "WSL_BUILD_VARIANT": variant,
        "WSL_PICO_SDK_COMMIT": sdk_commit,
        "WSL_C_COMPILER_ID": compiler_id,
    }
    if actual != exact:
        raise ProvenanceError(
            f"{header}: generated identity does not match controlled inputs: "
            f"expected {exact}, got {actual}"
        )
    if not uf2.is_file():
        raise ProvenanceError(f"UF2 image is missing: {uf2}")
    _assert_identity_embedded(uf2, expected["emitted_build"], expected["emitted_cfg"])
    cache = build_dir / "CMakeCache.txt"
    cache_values = _parse_cache(cache)
    expected_cache = {
        "CMAKE_BUILD_TYPE": "Release",
        "DEBUG_USB": "OFF",
        "FI1_BUILD": "ON" if variant == "fi1" else "OFF",
        "PICO_BOARD": "pico",
    }
    if cache_values != expected_cache:
        raise ProvenanceError(
            f"{cache}: release options differ: expected {expected_cache}, got {cache_values}"
        )
    return {
        "variant": variant,
        "bench_only": variant == "fi1",
        "build_options": expected["build_options"],
        "identity": {
            "id.build": expected["emitted_build"],
            "id.cfg": expected["emitted_cfg"],
            "id.fi1": 1 if variant == "fi1" else 0,
        },
        "source": {
            "algorithm": expected["algorithm"],
            "sha256": expected["source_sha256"],
            "config_sha256": expected["config_sha256"],
            "inputs": expected["inputs"],
        },
        "runtime_identity_inputs": expected["toolchain_inputs"],
        "cmake": {
            "cache_sha256": _sha256_file(cache),
            "release_values": cache_values,
        },
        "image": {
            "file": uf2.name,
            "bytes": uf2.stat().st_size,
            "sha256": _sha256_file(uf2),
        },
    }


def create_manifest(args: argparse.Namespace) -> None:
    source_dir = args.source_dir.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sdk_record = _pico_sdk_record(args.sdk_dir)
    release_compiler_id = _cmake_compiler_identity(args.release_build_dir.resolve())
    fi1_compiler_id = _cmake_compiler_identity(args.fi1_build_dir.resolve())
    if release_compiler_id != fi1_compiler_id:
        raise ProvenanceError(
            "release and FI-1 builds used different C compiler identities"
        )

    release_record = _image_record(
        source_dir=source_dir,
        variant="release",
        uf2=args.release_uf2.resolve(),
        header=args.release_header.resolve(),
        build_dir=args.release_build_dir.resolve(),
        sdk_commit=sdk_record["git_commit"],
        compiler_id=release_compiler_id,
    )
    fi1_record = _image_record(
        source_dir=source_dir,
        variant="fi1",
        uf2=args.fi1_uf2.resolve(),
        header=args.fi1_header.resolve(),
        build_dir=args.fi1_build_dir.resolve(),
        sdk_commit=sdk_record["git_commit"],
        compiler_id=fi1_compiler_id,
    )
    if release_record["image"]["sha256"] == fi1_record["image"]["sha256"]:
        raise ProvenanceError("release and FI-1 images unexpectedly have the same SHA-256")

    manifest = {
        "schema": SCHEMA,
        "firmware_version": _firmware_version(source_dir),
        "release_policy": {
            "debug_usb": False,
            "fi1_is_bench_only": True,
            "pico_board": "pico",
            "requires_clean_pico_sdk": True,
        },
        "deployment_identity": {
            "build_allowlist": [release_record["identity"]["id.build"]],
            "config_allowlist": [release_record["identity"]["id.cfg"]],
        },
        "toolchain": {
            "arm_none_eabi_gcc": _run_version(args.compiler, "--version"),
            "runtime_c_compiler_identity": release_compiler_id,
            "cmake": _run_version(args.cmake, "--version"),
            "ninja": _run_version(args.ninja, "--version"),
            "pico_sdk": sdk_record,
        },
        "images": [release_record, fi1_record],
    }
    _write_if_different(
        output,
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    )


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ProvenanceError(message)


def verify_manifest(args: argparse.Namespace) -> None:
    manifest_path = args.manifest.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read manifest {manifest_path}: {exc}") from exc
    _expect(manifest.get("schema") == SCHEMA, "wrong release-manifest schema")
    _expect(
        manifest.get("firmware_version") == _firmware_version(args.source_dir),
        "manifest FW_VERSION does not match config.h",
    )
    images = manifest.get("images")
    _expect(isinstance(images, list) and len(images) == 2, "manifest must bind two images")
    by_variant = {
        item.get("variant"): item for item in images if isinstance(item, dict)
    }
    _expect(set(by_variant) == {"release", "fi1"}, "missing release or FI-1 image")
    toolchain = manifest.get("toolchain", {})
    sdk_record = toolchain.get("pico_sdk", {})
    sdk_commit = sdk_record.get("git_commit")
    compiler_id = toolchain.get("runtime_c_compiler_identity")
    _expect(
        isinstance(sdk_commit, str)
        and bool(re.fullmatch(r"[0-9a-f]{40}", sdk_commit)),
        "manifest has no clean Pico SDK commit for runtime identity",
    )
    _expect(
        isinstance(compiler_id, str)
        and bool(re.fullmatch(r"[A-Za-z0-9_.+-]+", compiler_id)),
        "manifest has no C compiler ID/version for runtime identity",
    )

    for variant in ("release", "fi1"):
        record = by_variant[variant]
        expected = compute_identity(
            args.source_dir,
            variant,
            debug_usb=False,
            pico_board="pico",
            build_type="Release",
            sdk_commit=sdk_commit,
            compiler_id=compiler_id,
        )
        identity = record.get("identity", {})
        _expect(identity.get("id.build") == expected["emitted_build"], f"{variant}: build ID mismatch")
        _expect(identity.get("id.cfg") == expected["emitted_cfg"], f"{variant}: config ID mismatch")
        _expect(identity.get("id.fi1") == (1 if variant == "fi1" else 0), f"{variant}: FI-1 identity mismatch")
        source = record.get("source", {})
        _expect(source.get("sha256") == expected["source_sha256"], f"{variant}: source digest mismatch")
        _expect(source.get("config_sha256") == expected["config_sha256"], f"{variant}: full config digest mismatch")
        _expect(source.get("inputs") == expected["inputs"], f"{variant}: source-input list mismatch")
        _expect(
            record.get("runtime_identity_inputs") == expected["toolchain_inputs"],
            f"{variant}: runtime toolchain identity inputs mismatch",
        )
        image = record.get("image", {})
        image_path = manifest_path.parent / str(image.get("file", ""))
        _expect(image_path.is_file(), f"{variant}: image is missing from release bundle")
        _expect(image_path.stat().st_size == image.get("bytes"), f"{variant}: image size mismatch")
        _expect(_sha256_file(image_path) == image.get("sha256"), f"{variant}: image SHA-256 mismatch")
        _assert_identity_embedded(
            image_path, expected["emitted_build"], expected["emitted_cfg"]
        )

    release_identity = by_variant["release"]["identity"]
    _expect(
        manifest.get("deployment_identity")
        == {
            "build_allowlist": [release_identity["id.build"]],
            "config_allowlist": [release_identity["id.cfg"]],
        },
        "deployment allowlist must contain exactly the emitted release identity",
    )
    _expect(
        by_variant["release"]["image"]["sha256"]
        != by_variant["fi1"]["image"]["sha256"],
        "release and FI-1 hashes must differ",
    )
    for key in (
        "arm_none_eabi_gcc",
        "runtime_c_compiler_identity",
        "cmake",
        "ninja",
        "pico_sdk",
    ):
        _expect(bool(toolchain.get(key)), f"toolchain provenance is missing {key}")


def _add_identity_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--variant", choices=("release", "fi1"), required=True)
    parser.add_argument("--debug-usb", action="store_true")
    parser.add_argument("--pico-board", default="pico")
    parser.add_argument("--build-type", default="Release")
    parser.add_argument("--sdk-commit", required=True)
    parser.add_argument("--compiler-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    identity_parser = commands.add_parser("identity", help="print controlled identity JSON")
    _add_identity_options(identity_parser)

    header_parser = commands.add_parser("write-header", help="write generated build_id.h")
    _add_identity_options(header_parser)
    header_parser.add_argument("--output", type=Path, required=True)

    create_parser = commands.add_parser("create-manifest", help="create dual-image manifest")
    create_parser.add_argument("--source-dir", type=Path, required=True)
    create_parser.add_argument("--release-uf2", type=Path, required=True)
    create_parser.add_argument("--release-header", type=Path, required=True)
    create_parser.add_argument("--release-build-dir", type=Path, required=True)
    create_parser.add_argument("--fi1-uf2", type=Path, required=True)
    create_parser.add_argument("--fi1-header", type=Path, required=True)
    create_parser.add_argument("--fi1-build-dir", type=Path, required=True)
    create_parser.add_argument("--sdk-dir", type=Path, required=True)
    create_parser.add_argument("--compiler", type=Path, required=True)
    create_parser.add_argument("--cmake", type=Path, required=True)
    create_parser.add_argument("--ninja", type=Path, required=True)
    create_parser.add_argument("--output", type=Path, required=True)

    verify_parser = commands.add_parser("verify-manifest", help="verify source + images")
    verify_parser.add_argument("--source-dir", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "identity":
            print(
                json.dumps(
                    compute_identity(
                        args.source_dir,
                        args.variant,
                        debug_usb=args.debug_usb,
                        pico_board=args.pico_board,
                        build_type=args.build_type,
                        sdk_commit=args.sdk_commit,
                        compiler_id=args.compiler_id,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "write-header":
            write_header(args)
        elif args.command == "create-manifest":
            create_manifest(args)
        elif args.command == "verify-manifest":
            verify_manifest(args)
        else:  # pragma: no cover - argparse makes this unreachable
            parser.error(f"unknown command: {args.command}")
    except ProvenanceError as exc:
        print(f"PROVENANCE ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
