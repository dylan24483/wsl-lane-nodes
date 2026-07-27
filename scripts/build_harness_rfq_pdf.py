#!/usr/bin/env python3
"""Render the harness RFQ markdown to a vendor-ready PDF.

Why this exists rather than a one-line pandoc call:

The RFQ carries 11 warning markers written as U+26A0 + U+FE0F. The variation
selector requests *emoji* presentation, which needs a colour emoji font. Chrome
subsets only the text fonts it embeds, so those glyphs do not survive into the
PDF - the PDF ships with zero embedded images and no emoji font, meaning every
one of those warnings silently loses its marker. Several of them carry
safety-relevant content (the isolated/non-isolated domain split, the J14 ferrule
rule), so losing them in the copy that actually goes to an outside shop is not
acceptable.

The fix is to substitute plain text before rendering. Plain text prints on any
reader, any printer, any decade. The source markdown is left untouched - it stays
readable in the repo and on GitHub.

Chain: markdown --(pandoc)--> standalone HTML --(headless Chrome)--> PDF.
No LaTeX/typst/wkhtmltopdf is installed on this machine; Chrome is.

Usage:  py -3 scripts/build_harness_rfq_pdf.py [--out DIR]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "docs" / "phase8_harness_RFQ.md"
CSS = Path(__file__).with_name("harness_rfq_print.css")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Glyphs that do not survive font subsetting, and their print-safe replacements.
SUBSTITUTIONS = [
    ("\u26a0\ufe0f", "**WARNING:**"),   # emoji-presentation warning sign
    ("\u26a0", "**WARNING:**"),         # text-presentation, same meaning
    ("\u26d4", "**DO NOT:**"),
    ("\u2705", "[OK]"),
    ("\u23f1", "[LEAD TIME]"),
    ("\U0001f504", "[UPDATED]"),
    ("\u2b50", "[*]"),
]
# Circled digits are present in Segoe UI but not guaranteed elsewhere.
SUBSTITUTIONS += [(chr(0x2460 + i), f"({i + 1})") for i in range(10)]


def preprocess(md: str) -> tuple[str, int]:
    n = 0
    for bad, good in SUBSTITUTIONS:
        n += md.count(bad)
        md = md.replace(bad, good)
    # "**WARNING:** **bold**" reads badly - collapse doubled emphasis.
    md = re.sub(r"\*\*WARNING:\*\*\s+\*\*", "**WARNING: ", md)
    return md, n


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    sys.exit("No Chrome/Edge found for headless PDF rendering.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "docs"))
    args = ap.parse_args()

    if not shutil.which("pandoc"):
        sys.exit("pandoc not found on PATH.")
    if not SRC.exists():
        sys.exit(f"missing {SRC}")

    md = SRC.read_text(encoding="utf-8")
    # Tolerant of markup and of the header listing more than one assembly:
    # "**WSL-LANE-HARNESS-A** Rev 4  ·  **WSL-PI-LINK-B** Rev 1" must still yield 4.
    rev_m = re.search(r"WSL-LANE-HARNESS-A\**[\s·.]*\**Rev\**\s*(\d+)", md)
    rev = rev_m.group(1) if rev_m else "X"
    md, replaced = preprocess(md)
    print(f"RFQ Rev {rev}: {replaced} unsafe glyph(s) replaced with plain text")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"WSL-LANE-HARNESS-A_RFQ_Rev{rev}.pdf"

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "rfq.md").write_text(md, encoding="utf-8")
        html = tmp / "rfq.html"
        subprocess.run(
            ["pandoc", str(tmp / "rfq.md"), "-s", "--embed-resources",
             f"--css={CSS}", "--metadata",
             f"title=RFQ - WSL-LANE-HARNESS-A Rev {rev}", "-o", str(html)],
            check=True,
        )
        subprocess.run(
            [find_chrome(), "--headless=new", "--disable-gpu",
             "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri()],
            check=True, capture_output=True,
        )

    data = pdf.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    if not data.startswith(b"%PDF") or not data.rstrip().endswith(b"%%EOF"):
        sys.exit("FAIL: output is not a well-formed PDF")
    if pages < 3:
        sys.exit(f"FAIL: only {pages} page(s) - render probably collapsed")
    print(f"OK  {pdf}  ({len(data) / 1024:.0f} KB, {pages} pages)")


if __name__ == "__main__":
    main()
