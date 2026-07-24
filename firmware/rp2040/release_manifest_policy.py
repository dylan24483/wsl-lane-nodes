#!/usr/bin/env python3
"""Stamp and verify deployment policy outside the identity-bearing firmware inputs.

The runtime build ID intentionally covers only inputs that can change the UF2.
Board compatibility is release-bundle metadata, so this helper can tighten that
policy without falsely changing the identity embedded in an already-built image.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_BOARD_REVISIONS = ["revD"]


class BoardPolicyError(RuntimeError):
    """The release manifest is missing or violates the board policy."""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoardPolicyError(f"cannot read release manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BoardPolicyError(f"release manifest {path} is not a JSON object")
    return data


def verify_manifest_policy(path: Path) -> None:
    data = load_manifest(path)
    actual = data.get("supported_board_revisions")
    if actual != SUPPORTED_BOARD_REVISIONS:
        raise BoardPolicyError(
            "supported_board_revisions must be exactly "
            f"{SUPPORTED_BOARD_REVISIONS!r}, got {actual!r}"
        )
    release_images = [
        image for image in data.get("images", [])
        if isinstance(image, dict)
        and image.get("variant") == "release"
        and image.get("bench_only") is False
    ]
    if len(release_images) != 1:
        raise BoardPolicyError(
            "manifest must contain exactly one non-bench release image"
        )
    identity = release_images[0].get("identity", {})
    build = identity.get("id.build")
    config = identity.get("id.cfg")
    if not isinstance(build, str) or not build:
        raise BoardPolicyError("release image has no id.build")
    if not isinstance(config, str) or not config:
        raise BoardPolicyError("release image has no id.cfg")
    expected_qualified = [f"revD|{build}|{config}"]
    actual_qualified = data.get("qualified_releases")
    if actual_qualified != expected_qualified:
        raise BoardPolicyError(
            "qualified_releases must bind the exact "
            f"board/build/config tuple {expected_qualified!r}, got "
            f"{actual_qualified!r}"
        )


def stamp_manifest_policy(path: Path) -> None:
    data = load_manifest(path)
    data["supported_board_revisions"] = SUPPORTED_BOARD_REVISIONS
    release_images = [
        image for image in data.get("images", [])
        if isinstance(image, dict)
        and image.get("variant") == "release"
        and image.get("bench_only") is False
    ]
    if len(release_images) != 1:
        raise BoardPolicyError(
            "manifest must contain exactly one non-bench release image"
        )
    identity = release_images[0].get("identity", {})
    build = identity.get("id.build")
    config = identity.get("id.cfg")
    if not isinstance(build, str) or not build:
        raise BoardPolicyError("release image has no id.build")
    if not isinstance(config, str) or not config:
        raise BoardPolicyError("release image has no id.cfg")
    data["qualified_releases"] = [f"revD|{build}|{config}"]
    encoded = json.dumps(
        data, indent=2, sort_keys=True, ensure_ascii=True
    ) + "\n"
    path.write_bytes(encoded.encode("ascii"))
    verify_manifest_policy(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stamp", "verify"))
    parser.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "stamp":
            stamp_manifest_policy(args.manifest)
        else:
            verify_manifest_policy(args.manifest)
    except BoardPolicyError as exc:
        print(f"BOARD POLICY ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
