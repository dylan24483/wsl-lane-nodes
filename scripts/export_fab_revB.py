#!/usr/bin/env python3
"""
Export the Phase 8b Rev-B routed-manual board into a fab-review package.

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\export_fab_revB.py

The script intentionally exports from kicad/wsl-phase8b.routed-manual.kicad_pcb,
not the clean unrouted source board.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
KICAD = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
PY_KICAD = Path(r"C:\Program Files\KiCad\10.0\bin\python.exe")
BOARD = ROOT / "kicad" / "wsl-phase8b.routed-manual.kicad_pcb"
OUT = ROOT / "kicad" / "fab_revB_routed_manual"
GERBER_DIR = OUT / "gerber_drill"
ASSEMBLY_DIR = OUT / "assembly"
REPORT_DIR = OUT / "reports"
REVIEW_DIR = OUT / "review"
JLC_READY_DIR = OUT / "JLC_UPLOAD_READY"

GERBER_LAYERS = ",".join(
    [
        "F.Cu",
        "In1.Cu",
        "In2.Cu",
        "B.Cu",
        "F.Paste",
        "B.Paste",
        "F.Silkscreen",
        "B.Silkscreen",
        "F.Mask",
        "B.Mask",
        "Edge.Cuts",
    ]
)

PDF_LAYERS = ",".join(
    [
        "F.Cu",
        "In1.Cu",
        "In2.Cu",
        "B.Cu",
        "F.Silkscreen",
        "B.Silkscreen",
        "F.Mask",
        "B.Mask",
        "Edge.Cuts",
        "F.Fab",
        "B.Fab",
    ]
)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_safe_output_dir(path: Path) -> None:
    resolved = path.resolve()
    allowed = (ROOT / "kicad").resolve()
    if allowed not in (resolved, *resolved.parents):
        raise SystemExit(f"Refusing to clean output outside kicad/: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    GERBER_DIR.mkdir()
    ASSEMBLY_DIR.mkdir()
    REPORT_DIR.mkdir()
    REVIEW_DIR.mkdir()
    JLC_READY_DIR.mkdir()


def run(cmd: list[str], log_name: str) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    text = ""
    if proc.stdout:
        text += proc.stdout
    if proc.stderr:
        text += proc.stderr
    (REPORT_DIR / log_name).write_text(text, encoding="utf-8")
    if proc.returncode:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{text}")
    return text


def natural_ref_key(ref: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in ref if not ch.isdigit())
    digits = "".join(ch for ch in ref if ch.isdigit())
    return prefix, int(digits or 0), ref


def board_bom() -> dict[str, object]:
    board = pcbnew.LoadBoard(str(BOARD))
    rows: dict[tuple[str, str], list[str]] = defaultdict(list)
    dnp = []
    excluded = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        value = fp.GetValue()
        footprint = str(fp.GetFPID().GetLibItemName())
        is_dnp = bool(fp.IsDNP())
        is_bom_excluded = bool(fp.IsExcludedFromBOM())
        is_pos_excluded = bool(fp.IsExcludedFromPosFiles())

        if is_dnp:
            dnp.append([ref, value, footprint])
        if is_bom_excluded and not is_dnp:
            excluded.append([ref, value, footprint])
        if is_dnp or is_bom_excluded:
            continue
        rows[(value, footprint)].append(ref)

    bom_path = ASSEMBLY_DIR / "wsl-phase8b-revB-bom-non-dnp.csv"
    with bom_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "Quantity", "LCSC Part #"])
        for (value, footprint), refs in sorted(rows.items(), key=lambda item: natural_ref_key(item[1][0])):
            refs = sorted(refs, key=natural_ref_key)
            w.writerow([value, ",".join(refs), footprint, len(refs), ""])

    dnp_path = ASSEMBLY_DIR / "wsl-phase8b-revB-dnp-excluded.csv"
    with dnp_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Value", "Footprint", "Reason"])
        for ref, value, footprint in sorted(dnp, key=lambda row: natural_ref_key(row[0])):
            w.writerow([ref, value, footprint, "DNP / excluded from BOM and POS"])
        for ref, value, footprint in sorted(excluded, key=lambda row: natural_ref_key(row[0])):
            w.writerow([ref, value, footprint, "Excluded from BOM/POS"])

    return {
        "bom_rows": len(rows),
        "bom_refs": sum(len(v) for v in rows.values()),
        "dnp_refs": len(dnp),
        "excluded_non_dnp_refs": len(excluded),
    }


def zip_paths(zip_path: Path, files: list[Path], base: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            z.write(path, path.relative_to(base).as_posix())


def write_upload_ready_readme(summary: dict[str, object]) -> Path:
    readme = JLC_READY_DIR / "00_README_UPLOAD.txt"
    readme.write_text(
        "\n".join(
            [
                "WSL Phase 8b Rev-B JLCPCB upload packet",
                f"Generated: {summary['generated_at']}",
                "",
                "Upload order:",
                "1. Upload 01_wsl-phase8b-revB_gerbers.zip as the PCB Gerber/drill file.",
                "2. In the JLCPCB assembly step, choose Standard PCBA.",
                "3. Upload 02_wsl-phase8b-revB_BOM_JLC.csv as the BOM.",
                "4. Upload 03_wsl-phase8b-revB_CPL_JLC.csv as the position/CPL file.",
                "5. Use 04_wsl-phase8b-revB_part-lock-audit.csv during part-match review.",
                "",
                "Do not upload these as JLC order files:",
                "- 05_wsl-phase8b-revB_excluded-hand-solder.csv is an exclusion audit.",
                "- 06_wsl-phase8b-revB_hand-solder-bom.csv is the post-JLC board install list.",
                "- 07_wsl-phase8b-revB_harness-mating-parts.csv is the harness/mating plug list.",
                "",
                "PCB order settings:",
                "- 4 layers, FR-4, 1.6 mm thickness.",
                "- 1 oz outer copper, 0.5 oz inner copper.",
                "- Green solder mask, white silkscreen.",
                "- ENIG surface finish.",
                "- Confirm JLC preview dimensions are 250 mm x 225 mm.",
                "",
                "JLC placement contract:",
                "- JLC BOM unique lines: 20.",
                "- JLC CPL placed designators: 174.",
                "- JLC places SMT plus PC817 optos and six G5LE relays.",
                "- Hand solder after JLC: A1, J1-J11, J13, J14, U37.",
                "- Existing DNP/excluded refs remain unplaced.",
                "",
                "Critical part-match checks:",
                "- K1-K6: C116963, Omron G5LE-14 5VDC. The relay coil must be 5 VDC.",
                "- U1-U3: C47023, MCP23017-E/SO. This must be I2C MCP23017, not SPI MCP23S17.",
                "- U4-U35: C5692981, PC817B DIP-4.",
                "- U36: C7593, NE555DR SOIC-8.",
                "",
                "Mandatory preview checks before ordering:",
                "- Pin 1/orientation markers for U1-U3 and U36 match the KiCad board.",
                "- Cathode stripes for D1/D3/D5/D7/D9/D11/D15/D16 (1N4148), D17 (SS14) orientation,",
                "  and C11 (100uF electrolytic) polarity are correct. (C5/C6 are DNP; D18+ do not exist.)",
                "- Relay bodies sit in the machine-contact band and do not rotate.",
                "- PC817 optos stay vertical in the field/logic barrier row.",
                "- A1, J1-J11, J13, J14, U37 are not placed by JLC.",
                "- If JLC rejects PC817 or G5LE through-hole assembly, move those refs to",
                "  hand-solder/DNP in the order UI. No PCB redesign is required.",
                "",
                "Verification gates from this export:",
                "- KiCad DRC: 0 violations, 0 unconnected pads, 0 footprint errors.",
                "- Rev-B topology audit: ALL PASS.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return readme


def make_jlc_upload_ready_packet(summary: dict[str, object]) -> list[Path]:
    readme = write_upload_ready_readme(summary)
    copies = [
        (OUT / "wsl-phase8b-revB-gerber-drill.zip", "01_wsl-phase8b-revB_gerbers.zip"),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv",
            "02_wsl-phase8b-revB_BOM_JLC.csv",
        ),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-cpl.csv",
            "03_wsl-phase8b-revB_CPL_JLC.csv",
        ),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv",
            "04_wsl-phase8b-revB_part-lock-audit.csv",
        ),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-excluded.csv",
            "05_wsl-phase8b-revB_excluded-hand-solder.csv",
        ),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-hand-solder-bom.csv",
            "06_wsl-phase8b-revB_hand-solder-bom.csv",
        ),
        (
            ASSEMBLY_DIR / "wsl-phase8b-revB-harness-mating-parts.csv",
            "07_wsl-phase8b-revB_harness-mating-parts.csv",
        ),
    ]
    ready_files = [readme]
    for src, name in copies:
        if not src.exists():
            raise SystemExit(f"Missing file for upload-ready packet: {src}")
        dst = JLC_READY_DIR / name
        shutil.copy2(src, dst)
        ready_files.append(dst)
    return ready_files


def write_readme(summary: dict[str, object]) -> Path:
    readme = OUT / "README-fab-package.txt"
    readme.write_text(
        "\n".join(
            [
                "WSL Phase 8b Rev-B routed-manual fab package",
                f"Generated: {summary['generated_at']}",
                f"Board: {rel(BOARD)}",
                "",
                "Bare PCB gate:",
                "- KiCad DRC: 0 DRC violations, 0 unconnected pads, 0 footprint errors.",
                "- Rev-B topology audit: ALL PASS.",
                "- Custom .kicad_dru rules are active via the routed .kicad_pro netclass map.",
                "",
                "Use for bare PCB fabrication:",
                f"- {summary['gerber_zip']}",
                "",
                "Assembly support:",
                "- assembly/wsl-phase8b-revB-bom-non-dnp.csv is grouped by value/footprint.",
                "- assembly/wsl-phase8b-revB-cpl.csv is KiCad position output, DNP excluded.",
                "- assembly/wsl-phase8b-revB-pcba-working-bom.csv groups rows into",
                "  purchasable sourcing lines with assembly/source buckets.",
                "- assembly/wsl-phase8b-revB-pcba-placement-buckets.csv preserves each",
                "  KiCad BOM row with the same source-bucket classification.",
                "- assembly/wsl-phase8b-revB-offboard-hardware.csv lists mating plugs and",
                "  hardware that are not placed on the PCB.",
                "- assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv and",
                "  assembly/wsl-phase8b-revB-jlc-standard-pcba-cpl.csv are the",
                "  filtered JLCPCB Standard-PCBA upload pair: JLC places SMT, PC817,",
                "  and G5LE; A1/connectors/U37 are hand-soldered.",
                "- assembly/wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv is",
                "  the clean upload BOM with only JLC order-driving columns.",
                "- assembly/wsl-phase8b-revB-hand-solder-bom.csv and",
                "  assembly/wsl-phase8b-revB-harness-mating-parts.csv list the",
                "  post-JLC board install and harness/mating connector purchases.",
                f"- {summary['jlc_upload_zip']} contains the Gerber zip plus the clean",
                "  JLC Standard-PCBA upload BOM/CPL.",
                "- The raw grouped BOM intentionally keeps LCSC/manufacturer fields blank.",
                "- The JLC Standard-PCBA upload BOM has locked LCSC numbers, but still",
                "  requires final JLC part-match, polarity, and orientation approval.",
                f"- {summary['jlc_upload_ready_dir']} contains short, upload-order filenames",
                "  for the Gerber zip, clean JLC BOM, clean JLC CPL, and audit files.",
                f"- {summary['jlc_upload_ready_zip']} is a transport zip of that upload-ready",
                "  folder. Use the files inside it in the JLC flow; do not upload the",
                "  transport zip itself as the PCB Gerber file.",
                "",
                "Safety caveat:",
                "- This package is PCB-fab-ready under the current conservative DRC contract.",
                "- It is not controller cutover-ready; RP2040 v1.1 cam-stop overrun and",
                "  on-hardware bench bring-up remain required before live machine use.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return readme


def main() -> int:
    if not BOARD.exists():
        raise SystemExit(f"Missing routed board: {BOARD}")
    if not KICAD.exists():
        raise SystemExit(f"Missing KiCad CLI: {KICAD}")
    if not PY_KICAD.exists():
        raise SystemExit(f"Missing KiCad Python: {PY_KICAD}")

    ensure_safe_output_dir(OUT)

    drc_report = REPORT_DIR / "DRC-revB-routed-manual-fab.rpt"
    run(
        [
            str(KICAD),
            "pcb",
            "drc",
            "--severity-all",
            "--units",
            "mm",
            "--output",
            str(drc_report),
            str(BOARD),
        ],
        "kicad-drc.log",
    )
    drc_text = drc_report.read_text(encoding="utf-8")
    required = [
        "Found 0 DRC violations",
        "Found 0 unconnected pads",
        "Found 0 Footprint errors",
    ]
    missing = [line for line in required if line not in drc_text]
    if missing:
        raise SystemExit(f"DRC gate failed; missing expected lines: {missing}")

    audit_text = run(
        [
            str(PY_KICAD),
            str(ROOT / "scripts" / "audit_revB_board.py"),
            str(BOARD),
        ],
        "audit-revB-board.log",
    )
    if "AUDIT RESULT: ALL PASS" not in audit_text:
        raise SystemExit("Topology audit failed; see reports/audit-revB-board.log")

    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "gerbers",
            "--output",
            str(GERBER_DIR),
            "--layers",
            GERBER_LAYERS,
            "--precision",
            "6",
            "--subtract-soldermask",
            "--check-zones",
            str(BOARD),
        ],
        "export-gerbers.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "drill",
            "--output",
            str(GERBER_DIR),
            "--excellon-separate-th",
            "--generate-map",
            "--generate-report",
            "--report-path",
            str(REPORT_DIR / "drill-report.txt"),
            str(BOARD),
        ],
        "export-drill.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "pos",
            "--output",
            str(ASSEMBLY_DIR / "wsl-phase8b-revB-cpl.csv"),
            "--side",
            "both",
            "--format",
            "csv",
            "--units",
            "mm",
            "--exclude-dnp",
            str(BOARD),
        ],
        "export-pos.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "stats",
            "--output",
            str(REPORT_DIR / "board-stats.json"),
            "--format",
            "json",
            "--units",
            "mm",
            str(BOARD),
        ],
        "export-stats-json.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "stats",
            "--output",
            str(REPORT_DIR / "board-stats.txt"),
            "--format",
            "report",
            "--units",
            "mm",
            str(BOARD),
        ],
        "export-stats-report.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "ipcd356",
            "--output",
            str(REPORT_DIR / "wsl-phase8b-revB.ipc"),
            str(BOARD),
        ],
        "export-ipcd356.log",
    )
    run(
        [
            str(KICAD),
            "pcb",
            "export",
            "pdf",
            "--output",
            str(REVIEW_DIR / "wsl-phase8b-revB-review-layers.pdf"),
            "--layers",
            PDF_LAYERS,
            "--mode-multipage",
            "--check-zones",
            str(BOARD),
        ],
        "export-review-pdf.log",
    )

    bom_summary = board_bom()
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_pcba_parts_revB.py"),
        ],
        "prepare-pcba-parts.log",
    )
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_jlc_standard_pcba_revB.py"),
        ],
        "prepare-jlc-standard-pcba.log",
    )
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_hand_solder_procurement_revB.py"),
        ],
        "prepare-hand-solder-procurement.log",
    )

    gerber_suffixes = {
        ".gtl",
        ".gbl",
        ".g1",
        ".g2",
        ".gts",
        ".gbs",
        ".gtp",
        ".gbp",
        ".gto",
        ".gbo",
        ".gm1",
        ".gbr",
        ".gbrjob",
    }
    gerber_files = [
        p
        for p in GERBER_DIR.rglob("*")
        if p.is_file()
        and p.suffix.lower() in gerber_suffixes | {".drl", ".pdf", ".rpt"}
    ]
    if not any(p.suffix.lower() == ".drl" for p in gerber_files):
        raise SystemExit("No Excellon drill files found in fab output")
    if len([p for p in gerber_files if p.suffix.lower() in gerber_suffixes - {".gbrjob"}]) < 11:
        raise SystemExit("Expected at least 11 Gerber layer files")

    summary: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "board": rel(BOARD),
        "output_dir": rel(OUT),
        "gerber_zip": rel(OUT / "wsl-phase8b-revB-gerber-drill.zip"),
        "jlc_upload_zip": rel(OUT / "wsl-phase8b-revB-jlc-standard-pcba-upload.zip"),
        "jlc_upload_ready_dir": rel(JLC_READY_DIR),
        "jlc_upload_ready_zip": rel(OUT / "wsl-phase8b-revB-JLC_UPLOAD_READY.zip"),
        **bom_summary,
    }
    readme = write_readme(summary)

    package_zip = OUT / "wsl-phase8b-revB-fab-package.zip"
    gerber_zip = OUT / "wsl-phase8b-revB-gerber-drill.zip"
    jlc_upload_zip = OUT / "wsl-phase8b-revB-jlc-standard-pcba-upload.zip"
    jlc_upload_ready_zip = OUT / "wsl-phase8b-revB-JLC_UPLOAD_READY.zip"
    zip_paths(gerber_zip, gerber_files, GERBER_DIR)

    jlc_upload_files = [
        gerber_zip,
        ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-upload-bom.csv",
        ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-cpl.csv",
        ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-part-lock.csv",
        ASSEMBLY_DIR / "wsl-phase8b-revB-jlc-standard-pcba-excluded.csv",
        OUT / "README-fab-package.txt",
    ]
    missing_upload = [p for p in jlc_upload_files if not p.exists()]
    if missing_upload:
        raise SystemExit(f"Missing JLC upload package files: {missing_upload}")
    zip_paths(jlc_upload_zip, jlc_upload_files, OUT)

    ready_files = make_jlc_upload_ready_packet(summary)
    zip_paths(jlc_upload_ready_zip, ready_files, JLC_READY_DIR)

    package_files = [
        p
        for p in OUT.rglob("*")
        if p.is_file() and p.name not in {"manifest.json", package_zip.name}
    ]
    zip_paths(package_zip, package_files, OUT)

    all_files = [p for p in OUT.rglob("*") if p.is_file()]
    manifest = {
        **summary,
        "package_zip": rel(package_zip),
        "files": [
            {
                "path": rel(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(all_files)
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Fab output: {OUT}")
    print(f"Gerber/drill zip: {gerber_zip}")
    print(f"JLC upload zip: {jlc_upload_zip}")
    print(f"JLC upload-ready folder: {JLC_READY_DIR}")
    print(f"JLC upload-ready zip: {jlc_upload_ready_zip}")
    print(f"Full package zip: {package_zip}")
    print(f"BOM refs: {summary['bom_refs']} non-DNP, DNP refs: {summary['dnp_refs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
