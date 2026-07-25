#!/usr/bin/env python3
"""Regenerate the Phase 8 compiled Markdown and legacy DOCX export names.

The ordered files under docs/manual_src are authoritative.  The two DOCX names
are intentionally synchronized so old field links cannot select a stale body.
Pandoc performs the Markdown-to-OOXML conversion; an existing DOCX is used only
as a style reference, never as a content source.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from docx import Document
from docx.shared import Inches


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCE_DIR = DOCS / "manual_src"
COMPILED_MD = DOCS / "WSL_PHASE8_SYSTEM_MANUAL.md"
DOCX_OUTPUTS = (
    DOCS / "WSL_PHASE8_SYSTEM_MANUAL.docx",
    DOCS / "WSL_PHASE8_SYSTEM_MANUAL.corrected.docx",
)

REQUIRED_TEXT = (
    "J_SAFE3-4 is currently open/unlanded",
    "Never jumper J_SAFE3-4 at the machine",
    "protective-earth continuity/bonding",
    "uncommanded_motor_current",
    "external-feed-or-welded",
)
FORBIDDEN_TEXT = (
    "RETIRED / FROZEN BINARY EXPORTS",
    "J_SAFE3-4 Stop/CIS loop is implemented",
)


def ordered_sources() -> list[Path]:
    sources = sorted(SOURCE_DIR.glob("[0-2][0-9]_*.md"))
    expected = [f"{number:02d}" for number in range(24)]
    actual = [path.name[:2] for path in sources]
    if actual != expected:
        raise RuntimeError(
            f"manual source set must contain exactly 00..23; got {actual!r}"
        )
    return sources


def assemble_markdown(sources: list[Path]) -> str:
    sections = [path.read_text(encoding="utf-8").rstrip() for path in sources]
    return "\n\n".join(sections) + "\n"


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    return "".join(root.itertext())


def validate_export(path: Path, expected_text: str) -> None:
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"{path} is not a valid OOXML ZIP")
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"{path} has a corrupt ZIP member: {bad_member}")
        required_members = {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
        }
        missing = required_members.difference(archive.namelist())
        if missing:
            raise RuntimeError(f"{path} is missing OOXML members: {sorted(missing)}")

    rendered_text = docx_text(path)
    for token in REQUIRED_TEXT:
        if token not in expected_text:
            raise RuntimeError(f"source assembly is missing required token: {token!r}")
        if token not in rendered_text:
            raise RuntimeError(f"{path} is missing required token: {token!r}")
    for token in FORBIDDEN_TEXT:
        if token in expected_text or token in rendered_text:
            raise RuntimeError(f"{path} contains forbidden stale token: {token!r}")


def normalize_page_geometry(path: Path) -> None:
    """Give every section explicit US-Letter geometry for portable rendering."""

    document = Document(path)
    for section in document.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.header_distance = Inches(0.3)
        section.footer_distance = Inches(0.3)
    document.save(path)


def build(*, verify_only: bool = False) -> None:
    sources = ordered_sources()
    expected_markdown = assemble_markdown(sources)

    if verify_only:
        if COMPILED_MD.read_text(encoding="utf-8") != expected_markdown:
            raise RuntimeError(f"{COMPILED_MD} is not the exact source assembly")
        for output in DOCX_OUTPUTS:
            validate_export(output, expected_markdown)
        if DOCX_OUTPUTS[0].read_bytes() != DOCX_OUTPUTS[1].read_bytes():
            raise RuntimeError("legacy DOCX export names are not synchronized")
        return

    COMPILED_MD.write_text(expected_markdown, encoding="utf-8", newline="\n")

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("pandoc is required to regenerate the DOCX exports")

    reference = next((path for path in reversed(DOCX_OUTPUTS) if path.exists()), None)
    with tempfile.TemporaryDirectory(prefix="phase8-manual-") as tmp:
        candidate = Path(tmp) / "WSL_PHASE8_SYSTEM_MANUAL.docx"
        command = [
            pandoc,
            str(COMPILED_MD),
            "--from=gfm+smart",
            "--to=docx",
            "--toc",
            "--toc-depth=3",
            f"--resource-path={DOCS};{SOURCE_DIR};{ROOT}",
            "--output",
            str(candidate),
        ]
        if reference is not None:
            command.extend(["--reference-doc", str(reference)])
        subprocess.run(command, cwd=ROOT, check=True)
        normalize_page_geometry(candidate)
        validate_export(candidate, expected_markdown)
        for output in DOCX_OUTPUTS:
            shutil.copyfile(candidate, output)

    build(verify_only=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify compiled Markdown/DOCX files without writing them",
    )
    args = parser.parse_args()
    build(verify_only=args.verify_only)
    print("Phase 8 manual exports verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
