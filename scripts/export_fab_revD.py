#!/usr/bin/env python3
"""Export the Phase 8 rev-D routed board into an as-ordered fab package (gate G11, Codex H6).

Run from KiCad's bundled Python (pcbnew is required for the BOM/attribute pass):

  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\export_fab_revD.py

Contract (spec step I.7 / change-list P3 / remediation task H6):
- REV and the output directory are PARAMETERS (`--rev`, `--out`); the default output is
  kicad/fab_revD_<YYYY-MM-DD>/.
- The script REFUSES TO RUN if the output directory already exists. It never deletes or
  overwrites anything (the rev-B/rev-C rmtree incident must be structurally impossible).
- Exports from the ROUTED board kicad/revD/wsl-phase8b-revD.kicad_pcb after re-proving the
  release gates in-process (kicad-cli DRC 0/0/0 with the live remediation .kicad_dru;
  audit_revD_board.py routed mode ALL PASS).
- BOM <-> CPL <-> netlist equality is ASSERTED, not assumed: every non-testpoint/mounting
  footprint on the board must exist in kicad/wsl-phase8b-revD.net with the same value and
  footprint, the DNP set must match the generator's DNP rule exactly, and the CPL refs must
  equal the placed (non-DNP) set exactly. Pinned counts: 271 parts / 28 DNP / 243 placed /
  226 JLC-placed / 17 hand-solder.
  (History: 252 pre-remediation -> 262 after R1.7 -> 271 after the 2026-07-21 round-2
  batch: +9 parts for the R2-4 J16 protection stack and R2-6 REV_ID straps; the JP1
  default-OPEN solder link is the 28th DNP.)
- Round-2 hard locks (Codex 2026-07-21): Q17-Q20 -> onsemi 2N7002LT1G C16338 (R2-3);
  R135/R138/R141 -> UNI-ROYAL 10M C26108 with MATCH-AT-UPLOAD rows forbidden (R2-15);
  U46 -> TCA4307DGKR C880333, U47 -> Semtech SRV05-4.TCT C13612, F1 -> Littelfuse
  1206L020YR C207035 (R2-4). Source paths DERIVE from --rev so a rev-D board can never
  be exported under another revision's label (R2-15).
- D_PROT is HARD-LOCKED to MDD SS34, LCSC C8678, SMA/DO-214AC (run-log FR-3). The script
  fails if D17 is not SS34/D_SMA, if any SS14 survives anywhere, or if the JLC BOM line for
  SS34 carries anything but C8678/MDD/SMA.
- Every file in the package lands in a sha256 manifest (manifest.json) so the as-ordered
  package is hashable and reproducible.
- Also emits the hand-solder BOM and the HARNESS BOM (Codex H7): the harness CSV carries
  the Phoenix MC 1,5 termination data verbatim (7 mm strip, 0.22-0.25 N*m, max 0.5 mm^2
  with insulated ferrule) and the corrected coding-profile install rule (CP-MSTB 1734634
  fits the PLUG - it is never pressed into a standard G-3.5 header). A tracked copy of the
  harness BOM is written to docs/phase8_revD_harness_bom.csv.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
KICAD_CLI = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
# R2-15 (Codex round-2, 2026-07-21): the source board/netlist paths are
# DERIVED from --rev inside main() — a rev-D source can no longer be exported
# under another revision's label (the old code hard-coded revD sources while
# `--rev` freely renamed every emitted file). Any other --rev now fails on
# "missing routed board" unless that revision's sources actually exist.
DOCS_HARNESS_BOM = ROOT / "docs" / "phase8_revD_harness_bom.csv"

# ---- pinned release counts (fail closed on ANY drift) -------------------------------
EXPECTED_NETLIST_PARTS = 271     # R1.7 (262) + round-2 R2-4/R2-6 (+9)
EXPECTED_DNP = 28                # 22 value-DNP + 5 M1-optional + JP1 (default-OPEN link)
EXPECTED_PLACED = 243            # 271 - 28
EXPECTED_HAND_SOLDER = 17        # A1, J1-J11 (J12 is DNP), J13-J16, U45
EXPECTED_JLC_PLACED = 226        # 243 - 17
EXPECTED_JLC_LINES = 26          # 22 + 2N7002LT1G + TCA4307 + SRV05-4 + 1206L020YR

GERBER_LAYERS = ",".join(
    [
        "F.Cu", "In1.Cu", "In2.Cu", "B.Cu",
        "F.Paste", "B.Paste",
        "F.Silkscreen", "B.Silkscreen",
        "F.Mask", "B.Mask",
        "Edge.Cuts",
    ]
)

PDF_LAYERS = ",".join(
    [
        "F.Cu", "In1.Cu", "In2.Cu", "B.Cu",
        "F.Silkscreen", "B.Silkscreen",
        "F.Mask", "B.Mask",
        "Edge.Cuts", "F.Fab", "B.Fab",
    ]
)

# Board refs installed AFTER JLC assembly (hand solder). J12 is DNP (M1 channel) and is
# NOT in this set - it lives in the DNP list.
HAND_SOLDER_REFS = {
    "A1",                                    # Raspberry Pi Pico module
    "J1", "J2", "J3", "J4", "J5",
    "J6", "J7", "J8", "J9", "J10", "J11",
    "J13", "J14", "J15", "J16",
    "U45",                                   # TRACO TMA-0505S (rev-C U37 - refdes shifted)
}

# M1-optional tags (mirror of place_components_revD.is_m1_optional_tag - the DNP rule).
M1_OPTIONAL_TAGS = {"K_M1", "MOV_M1", "Csnub_M1", "Dfly_M1", "Rb_M1", "Rpd_M1", "Rsnub_M1"}


def is_dnp(tag: str, value: str) -> bool:
    return tag.endswith("_M1") or tag in M1_OPTIONAL_TAGS or "DNP" in value.upper()


# ---- JLC part locks (rev-B locks carried + rev-D additions) -------------------------
PART_LOCK: dict[tuple[str, str], dict[str, str]] = {
    ("0.1uF", "C_0805_2012Metric"): {
        "lcsc": "C49678", "mpn": "CC0805KRX7R9BB104", "manufacturer": "YAGEO",
        "class": "Basic", "locked_spec": "100nF 50V X7R +/-10% 0805 MLCC", "note": "",
    },
    # Rev-D: C_ADC5 emits value "100nF" (same physical part as the 0.1uF decouplers).
    ("100nF", "C_0805_2012Metric"): {"alias": ("0.1uF", "C_0805_2012Metric")},
    ("100uF/16V", "CP_Elec_6.3x5.4"): {
        "lcsc": "C19184134", "mpn": "CK1C101M-CRE54", "manufacturer": "RS",
        "class": "Extended",
        "locked_spec": "100uF 16V +/-20% SMD aluminum electrolytic, D6.3xL5.4mm",
        "note": "Polarized; verify positive mark and package preview before order.",
    },
    ("10nF", "C_0805_2012Metric"): {
        "lcsc": "C17702767", "mpn": "C0805B103K500NT", "manufacturer": "TORCH",
        "class": "Extended", "locked_spec": "10nF 50V X7R +/-10% 0805 MLCC", "note": "",
    },
    ("10uF", "C_0805_2012Metric"): {
        "lcsc": "C89827", "mpn": "CC0805KKX5R7BB106", "manufacturer": "YAGEO",
        "class": "Extended", "locked_spec": "10uF 16V X5R +/-10% 0805 MLCC",
        "note": "Verify DC-bias derating remains acceptable on the 5V rail.",
    },
    ("1N4148", "D_SOD-323"): {
        "lcsc": "C118873", "mpn": "1N4148WS", "manufacturer": "onsemi",
        "class": "Extended", "locked_spec": "1N4148WS switching diode, SOD-323", "note": "",
    },
    # Rev-D D_PROT: SS14 -> SS34 (spec H.4 / run-log FR-3). HARD LOCK - the G5LE-1/-14
    # package-trap class: SS34 from other vendors ships in SMB/SMC; only MDD C8678 is SMA.
    ("SS34", "D_SMA"): {
        "lcsc": "C8678", "mpn": "SS34", "manufacturer": "MDD",
        "class": "Basic",
        "locked_spec": "SS34 Schottky diode 40V 3A, SMA/DO-214AC",
        "note": "HARD LOCK (FR-3): must be MDD C8678 in SMA. Any MPN substitution re-runs the footprint review.",
    },
    ("G5LE S", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE T", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE SP", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE BE", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE M", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE M2", "Relay_SPDT_Omron-G5LE-1"): {"alias": ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1")},
    ("G5LE 5V", "Relay_SPDT_Omron-G5LE-1"): {
        "lcsc": "C116963", "mpn": "G5LE-14 5VDC", "manufacturer": "Omron Electronics",
        "class": "Extended", "locked_spec": "G5LE-14 5VDC SPDT relay, wave solder",
        "note": "Critical: 5VDC coil. Do not substitute 9V/12V/24V coil.",
    },
    ("MMBT3904", "SOT-23"): {
        "lcsc": "C909754", "mpn": "MMBT3904", "manufacturer": "GOODWORK",
        "class": "Extended", "locked_spec": "MMBT3904 NPN BJT, SOT-23", "note": "",
    },
    ("2N7002", "SOT-23"): {
        "lcsc": "C916396", "mpn": "2N7002", "manufacturer": "JSMSEMI",
        "class": "Extended", "locked_spec": "2N7002 N-channel MOSFET, SOT-23",
        "note": "Qled_* lamp drivers ONLY. The Q_TAP_* rail-tap stages are MPN-locked "
                "to onsemi 2N7002LT1G (R2-3/FR-10) - do NOT merge the lines.",
    },
    # R2-3 (Codex round-2, 2026-07-21): tap-stage FETs Q17-Q20 HARD-LOCKED to
    # onsemi 2N7002LT1G - the R1.5 cold-corner gate-drive margin (+0.12-0.14V
    # worst-stack) is derived from onsemi's published V_GS(th) 1.0-2.5V @
    # 250uA / tc ~-5mV/C and V_GS abs-max +/-20V; the JSMSEMI datasheet
    # documents none of these. LCSC C16338 verified in stock 2026-07-21.
    ("2N7002LT1G", "SOT-23"): {
        "lcsc": "C16338", "mpn": "2N7002LT1G", "manufacturer": "onsemi",
        "class": "Extended",
        "locked_spec": "2N7002LT1G N-channel MOSFET 60V 115mA, SOT-23",
        "note": "HARD LOCK (R2-3/FR-10): tap stages Q17-Q20 only. Substitution "
                "requires a documented V_GS(th)/tempco datasheet review "
                "(Nexperia 2N7002-QR is the approved alternate).",
    },
    # R2-4 (Codex round-2): J16 protection stack parts.
    ("1206L020YR 200mA", "Fuse_1206_3216Metric"): {
        "lcsc": "C207035", "mpn": "1206L020YR", "manufacturer": "Littelfuse",
        "class": "Extended",
        "locked_spec": "PTC resettable fuse 200mA hold / 420mA trip / 24V, 1206",
        "note": "F_J16_5V current limit for the J16 module supply (R2-4). "
                "Any substitute must be 1206, hold >= 2x the 100mA module "
                "allowance and trip << the SS34 3A budget.",
    },
    ("TCA4307DGKR", "VSSOP-8_3x3mm_P0.65mm"): {
        "lcsc": "C880333", "mpn": "TCA4307DGKR", "manufacturer": "Texas Instruments",
        "class": "Extended",
        "locked_spec": "TCA4307 hot-swap I2C buffer w/ stuck-bus recovery, VSSOP-8 (DGK)",
        "note": "Critical: stuck-bus RECOVERY variant (TCA4307, 40ms + SCL pulses); "
                "do not substitute plain buffers (TCA9517 etc). Pinout verified vs "
                "TI SCPS270B (FR-13).",
    },
    ("SRV05-4", "SOT-23-6"): {
        "lcsc": "C13612", "mpn": "SRV05-4.TCT", "manufacturer": "SEMTECH",
        "class": "Extended",
        "locked_spec": "SRV05-4 4-channel ESD/TVS array 5V, SOT-23-6",
        "note": "Connector-side ESD for J16 (R2-4). Semtech original locked; "
                "clone SRV05-4s exist under the same marking - keep the Semtech line.",
    },
    ("AO3400A kick", "SOT-23"): {"alias": ("AO3400A", "SOT-23")},
    ("AO3400A wdog", "SOT-23"): {"alias": ("AO3400A", "SOT-23")},
    ("AO3400A", "SOT-23"): {
        "lcsc": "C20917", "mpn": "AO3400A", "manufacturer": "Alpha & Omega Semicon",
        "class": "Basic", "locked_spec": "AO3400A N-channel logic MOSFET, SOT-23", "note": "",
    },
    ("AO3401A rail pass", "SOT-23"): {"alias": ("AO3401A", "SOT-23")},
    ("AO3401A", "SOT-23"): {
        "lcsc": "C347476", "mpn": "AO3401A", "manufacturer": "UMW",
        "class": "Extended", "locked_spec": "AO3401A P-channel MOSFET, SOT-23", "note": "",
    },
    ("4.7k", "R_0805_2012Metric"): {
        "lcsc": "C17673", "mpn": "0805W8F4701T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "4.7k 1% 1/8W 0805 resistor", "note": "",
    },
    ("2k2", "R_0805_2012Metric"): {
        "lcsc": "C17520", "mpn": "0805W8F2201T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "2.2k 1% 1/8W 0805 resistor", "note": "",
    },
    ("10k", "R_0805_2012Metric"): {
        "lcsc": "C17414", "mpn": "0805W8F1002T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "10k 1% 1/8W 0805 resistor", "note": "",
    },
    ("1k", "R_0805_2012Metric"): {
        "lcsc": "C17513", "mpn": "0805W8F1001T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "1k 1% 1/8W 0805 resistor", "note": "",
    },
    ("330R", "R_0805_2012Metric"): {
        "lcsc": "C17630", "mpn": "0805W8F3300T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "330R 1% 1/8W 0805 resistor", "note": "",
    },
    ("100k", "R_0805_2012Metric"): {
        "lcsc": "C149504", "mpn": "0805W8F1003T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "100k 1% 1/8W 0805 resistor", "note": "",
    },
    # Rev-D remediation R1 tap-stage values (FR-6 update: 680k is GONE; 1M + 10M are the
    # new jumbo values, same 0805 footprint class).
    ("1M", "R_0805_2012Metric"): {
        "lcsc": "C17514", "mpn": "0805W8F1004T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "1M 1% 1/8W 0805 resistor",
        # R2-2 (2026-07-21): the "~825k" floor here was the RETRACTED 25C-only
        # derivation (run-log RV-5); the binding floor is 1M (>=917k vs the
        # derated 85C 3.6uA partial-hold onset, remediation spec R1.4).
        "note": "R_TAPIN_* injection limiters (remediation R1.4 corrected: never "
                "reduce below 1M - the >=917k derated-onset floor; the old ~825k "
                "figure was retracted, Codex R2-2).",
    },
    ("10M", "R_0805_2012Metric"): {
        # R2-15 (2026-07-21): identity PINNED - C26108 verified on LCSC as
        # UNI-ROYAL 0805W8F1005T5E 10M 1% 0805 (the MATCH-AT-UPLOAD row is
        # dead). Listed out-of-stock at LCSC retail 2026-07-21: confirm JLC
        # assembly stock at order time; any substitute must be >=10M 0805 1%
        # with its C-number fetch-verified (C325772 was a hallucinated match,
        # rejected - see run log H6).
        "lcsc": "C26108", "mpn": "0805W8F1005T5E", "manufacturer": "UNI-ROYAL",
        "class": "Extended", "locked_spec": "10M 1% 1/8W 0805 resistor",
        "note": "R_TAPG_* gate pulldowns (R135/R138/R141). Identity pinned "
                "C26108 (R2-15); verify stock at order time (OOS at LCSC "
                "retail 2026-07-21).",
    },
    ("MCP23017 MCP_IN_A", "SOIC-28W_7.5x17.9mm_P1.27mm"): {"alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm")},
    ("MCP23017 MCP_IN_B", "SOIC-28W_7.5x17.9mm_P1.27mm"): {"alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm")},
    ("MCP23017 MCP_OUT_A", "SOIC-28W_7.5x17.9mm_P1.27mm"): {"alias": ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm")},
    ("MCP23017", "SOIC-28W_7.5x17.9mm_P1.27mm"): {
        "lcsc": "C47023", "mpn": "MCP23017-E/SO", "manufacturer": "Microchip Tech",
        "class": "Extended", "locked_spec": "MCP23017 I2C I/O expander, SOIC-28-300mil",
        "note": "Critical: I2C MCP23017, not SPI MCP23S17.",
    },
    ("NE555", "SOIC-8_3.9x4.9mm_P1.27mm"): {
        "lcsc": "C7593", "mpn": "NE555DR", "manufacturer": "Texas Instruments",
        "class": "Extended", "locked_spec": "NE555 bipolar timer, SOIC-8",
        "note": "Bipolar 555 selected; avoid CMOS/TLC555 timing change unless revalidated.",
    },
    ("PC817", "DIP-4_W7.62mm"): {
        "lcsc": "C5692981", "mpn": "PC817B", "manufacturer": "UMW",
        "class": "Extended", "locked_spec": "PC817B optocoupler, DIP-4, wave solder",
        "note": "B rank (CTR 130-260%) REQUIRED - remediation spec R4 disposition assumes "
                "the 130% class floor. Confirm DIP-4 preview/orientation.",
    },
}

# alias fan-outs: MMBT3904 <relay/AND> tags, 2N7002 LED/TAP tags, PC817 channel labels
for _lbl in ["S", "T", "SP", "BE", "M", "M2", "AND ARM", "AND RP_OK"]:
    PART_LOCK[(f"MMBT3904 {_lbl}", "SOT-23")] = {"alias": ("MMBT3904", "SOT-23")}
for _lbl in ["LED L_FIRST", "LED L_SECOND", "LED L_STRIKE", "LED L_FOUL"]:
    PART_LOCK[(f"2N7002 {_lbl}", "SOT-23")] = {"alias": ("2N7002", "SOT-23")}
# R2-3: the tap stages alias to the onsemi hard-lock line, never the generic.
for _lbl in ["TAP 555", "TAP KICK", "TAP ARM", "TAP RPOK"]:
    PART_LOCK[(f"2N7002LT1G {_lbl}", "SOT-23")] = {"alias": ("2N7002LT1G", "SOT-23")}
for _lbl in [
    "SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R",
    "GS1", "GS2", "GS3", "GS4", "GS5", "GS6", "GS7", "GS8", "GS9", "GS10",
    "GP", "OS", "BS", "PBZ", "PBC", "FOUL", "TENTH",
    "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR",
    "AUX1", "AUX2", "AUX3", "AUX4", "AUX5", "AUX6", "AUX7", "AUX8", "AUX9",
    "AUX10", "AUX11",
]:
    PART_LOCK[(f"PC817 {_lbl}", "DIP-4_W7.62mm")] = {"alias": ("PC817", "DIP-4_W7.62mm")}


# ---- hand-solder BOM (rev-C pattern, rev-D refs incl. J15/J16 + the U37->U45 shift) --
HAND_SOLDER_ROWS = [
    {"Ref": "A1", "Qty": 1, "Role": "RP2040 module", "Manufacturer": "Raspberry Pi",
     "MFR Part #": "SC0915",
     "Description": "Raspberry Pi Pico, castellated module, no pre-soldered headers",
     "Source": "DigiKey 2648-SC0915CT-ND or official Raspberry Pi reseller",
     "Status": "Locked",
     "Notes": "Program with firmware v1.2 (remediation R3) after assembly; do not use Pico H/WH."},
    {"Ref": "J1", "Qty": 1, "Role": "Pi IDC/header", "Manufacturer": "CNC Tech candidate",
     "MFR Part #": "3020-20-0100-00",
     "Description": "20-position 2x10 2.54mm vertical through-hole box/IDC header candidate",
     "Source": "DigiKey 1175-1612-ND candidate", "Status": "Candidate - verify body/keying",
     "Notes": "Verify shroud, key slot, pin-1 orientation vs KiCad footprint before ordering."},
    {"Ref": "J2", "Qty": 1, "Role": "5V power terminal", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1715734",
     "Description": "MKDS 1,5/ 3-5,08, 3-position fixed screw terminal block, 5.08mm pitch",
     "Source": "Phoenix / DigiKey / Mouser equivalent", "Status": "Locked - footprint verify at order",
     "Notes": "Fixed screw terminal; no off-board plug."},
    {"Ref": "J3", "Qty": 1, "Role": "FAST field input header", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1843680",
     "Description": "MCV 1,5/10-G-3,5, 10-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "Board drills 1.4mm per the Phoenix drilling plan (FR-9 _D1.4 footprints). "
              "Mating plug 1840447 on the harness BOM. CODED: keep-out profile pairing vs J15."},
    {"Ref": "J4", "Qty": 1, "Role": "SLOW A field input header", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1843729",
     "Description": "MCV 1,5/14-G-3,5, 14-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "Mating plug 1840489 on the harness BOM."},
    {"Ref": "J5", "Qty": 1, "Role": "SLOW B field input header", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1843703",
     "Description": "MCV 1,5/12-G-3,5, 12-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "Mating plug 1840463 on the harness BOM."},
    {"Ref": "J6,J7,J8,J9,J10,J11", "Qty": 6, "Role": "Machine output terminals",
     "Manufacturer": "Phoenix Contact", "MFR Part #": "1715721",
     "Description": "MKDS 1,5/ 2-5,08, 2-position fixed screw terminal block, 5.08mm pitch",
     "Source": "Phoenix / LCSC C5183929 / DigiKey / Mouser equivalent",
     "Status": "Locked - footprint verify at order",
     "Notes": "J12 (M1) is DNP - do not install a 7th block."},
    {"Ref": "J13", "Qty": 1, "Role": "LED lamp header", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1843648",
     "Description": "MCV 1,5/ 6-G-3,5, 6-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "Mating plug 1840405 on the harness BOM. CODED: keep-out profile pairing vs J16."},
    {"Ref": "J14", "Qty": 1, "Role": "Safety loop header", "Manufacturer": "Phoenix Contact",
     "MFR Part #": "1843622",
     "Description": "MCV 1,5/ 4-G-3,5, 4-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "Mating plug 1840382 on the harness BOM (carries the Candidate-C TBSC jumper)."},
    {"Ref": "J15", "Qty": 1, "Role": "SLOW C field input header (AUX4-11, NEW in rev-D)",
     "Manufacturer": "Phoenix Contact", "MFR Part #": "1843680",
     "Description": "MCV 1,5/10-G-3,5, 10-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "SAME header PN as J3 - the CP-MSTB coding (harness BOM) is what tells the "
              "plugs apart. Silk: KEYED: NOT J3."},
    {"Ref": "J16", "Qty": 1, "Role": "External I2C expansion header (NEW in rev-D)",
     "Manufacturer": "Phoenix Contact", "MFR Part #": "1843648",
     "Description": "MCV 1,5/ 6-G-3,5, 6-position vertical PCB header, 3.5mm pitch",
     "Source": "Phoenix Contact", "Status": "Locked",
     "Notes": "SAME header PN as J13 - CP-MSTB coding required. Silk: KEYED: NOT J13 LAMP. "
              "DNP-tolerant: may be left unpopulated on early articles."},
    {"Ref": "U45", "Qty": 1, "Role": "Isolated field supply (rev-C refdes U37 - SHIFTED)",
     "Manufacturer": "TRACO Power", "MFR Part #": "TMA 0505S",
     "Description": "Isolated 5V-to-5V 1W SIP DC/DC converter, 5V 200mA output",
     "Source": "DigiKey 1951-1003-ND / TME / Mouser equivalent", "Status": "Locked exact part",
     "Notes": "Do not substitute without pinout and isolation review. Rev-D refdes is U45; "
              "U37 on a rev-D board is the AUX5 optocoupler (first-article doc pack)."},
]

# ---- HARNESS BOM (Codex H7 deliverable) ---------------------------------------------
# Termination data verbatim from the Phoenix MC 1,5/..-ST-3,5 plug data (1840447 family):
#   stripping length 7 mm; screw M2, tightening torque 0.22-0.25 N*m;
#   conductor 0.14-1.5 mm^2 rigid/flexible; flexible with UNinsulated ferrule up to
#   1.5 mm^2; flexible with INSULATED ferrule max 0.5 mm^2.
# The old build-sheet figures (8 mm strip / ~0.5 N*m / 0.75-1.0 mm^2 insulated ferrules)
# were WRONG for MC 1,5 plugs and are corrected in phase8_lane21_harness_build_sheet.md
# (dated correction note, 2026-07-21).
MC15_TERMINATION = ("strip 7mm; torque 0.22-0.25 Nm (M2 screw); max 0.5mm2 with insulated "
                    "ferrule / 1.5mm2 bare or uninsulated ferrule")
CODING_INSTALL = ("CP-MSTB profile fits the PLUG (or an inverted header) - NEVER pressed "
                  "into a standard MCV G-3.5 header; header side of the code = remove the "
                  "coding rib at the matching pole. Sacrificial-pair proof REQUIRED before "
                  "coding production parts (first-article pack step FA-8).")

HARNESS_ROWS = [
    {"Mate For": "J3", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840447",
     "Description": "MC 1,5/10-ST-3,5, 10-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION,
     "Coding / marking": "CP-MSTB profile in PLUG at pole 1; remove J3 header rib at pole 1; "
                         "WHITE band. " + CODING_INSTALL,
     "Status": "Locked",
     "Notes": "SAME PN as J15's plug - coding + band color are the only discriminators."},
    {"Mate For": "J15", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840447",
     "Description": "MC 1,5/10-ST-3,5, 10-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION,
     "Coding / marking": "CP-MSTB profile in PLUG at pole 10; remove J15 header rib at pole 10; "
                         "YELLOW band. " + CODING_INSTALL,
     "Status": "Locked",
     "Notes": "NEW in rev-D (AUX4-11). A J3<->J15 swap is electrically silent but crosses "
              "cycle sensors with AUX contacts - the coding is mandatory (OG-3/FR-4)."},
    {"Mate For": "J4", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840489",
     "Description": "MC 1,5/14-ST-3,5, 14-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION, "Coding / marking": "none (unique pole count)",
     "Status": "Locked", "Notes": ""},
    {"Mate For": "J5", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840463",
     "Description": "MC 1,5/12-ST-3,5, 12-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION, "Coding / marking": "none (unique pole count)",
     "Status": "Locked", "Notes": ""},
    {"Mate For": "J13", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840405",
     "Description": "MC 1,5/ 6-ST-3,5, 6-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION,
     "Coding / marking": "CP-MSTB profile in PLUG at pole 1; remove J13 header rib at pole 1; "
                         "WHITE band. " + CODING_INSTALL,
     "Status": "Locked",
     "Notes": "SAME PN as J16's plug. A lamp plug in J16 lands resistorless LEDs across "
              "5V->GND and wedges I2C (FR-5) - coding is mandatory."},
    {"Mate For": "J16", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840405",
     "Description": "MC 1,5/ 6-ST-3,5, 6-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION,
     "Coding / marking": "CP-MSTB profile in PLUG at pole 6; remove J16 header rib at pole 6; "
                         "BLUE band. " + CODING_INSTALL,
     "Status": "Locked", "Notes": "NEW in rev-D (external I2C module)."},
    {"Mate For": "J14", "Qty per board": 1, "Manufacturer": "Phoenix Contact", "MFR Part #": "1840382",
     "Description": "MC 1,5/ 4-ST-3,5, 4-position 3.5mm screw plug",
     "Termination": MC15_TERMINATION + "; 18 AWG (0.82mm2) exceeds the 0.5mm2 insulated-"
                    "ferrule limit - use UNinsulated ferrules or bare stranded (corrected "
                    "2026-07-21, was wrongly specced 0.75-1.0mm2 insulated)",
     "Coding / marking": "none (unique pole count); carries the Candidate-C TBSC jumper on 1-2",
     "Status": "Locked", "Notes": "+1 spare per lane (build-sheet section 4)."},
    {"Mate For": "J3/J15/J13/J16 coding",
     # R2-15 (2026-07-21): quantity CORRECTED. Only the PLUG side takes a
     # profile (COR-5: the header side is a rib REMOVAL, no part) and each
     # coded plug takes exactly ONE profile at its coded pole -> 4 profiles
     # per board, so one 6-profile star covers a board with 2 spares. The
     # old "2 positions x 4 connectors" line double-counted (8/board).
     "Qty per board": "4 profiles (1 per coded plug: J3@1, J15@10, J13@1, J16@6) = 1 star of 6; "
                      "buy 2 stars min for the pilot (FA-8 sacrificial-pair proof + spares)",
     "Manufacturer": "Phoenix Contact", "MFR Part #": "1734634",
     "Description": "CP-MSTB coding profile star (6 profiles per star)",
     "Termination": "n/a",
     "Coding / marking": CODING_INSTALL,
     "Status": "Locked",
     "Notes": "MUST be fitted before first article; first-article gate includes the physical "
              "cross-mate refusal test AND the sacrificial-pair proof (FA-8)."},
    {"Mate For": "J1", "Qty per board": 1, "Manufacturer": "CNC Tech candidate",
     "MFR Part #": "3030-20-0102-00",
     "Description": "20-position IDC socket candidate for 2x10 2.54mm ribbon harness",
     "Termination": "IDC - ribbon per J1 header orientation",
     "Coding / marking": "verify pin-1 convention",
     "Status": "Candidate - verify with J1", "Notes": ""},
    {"Mate For": "harness marking stock", "Qty per board": "as needed",
     "Manufacturer": "-", "MFR Part #": "-",
     "Description": "Band-color stock: WHITE (J3+J13), YELLOW (J15), BLUE (J16) heat-shrink "
                    "or wire-marker bands",
     "Termination": "n/a",
     "Coding / marking": "apply at plug end of every harness bundle per the rows above",
     "Status": "Locked convention (FR-4/FR-5)", "Notes": ""},
]


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], report_dir: Path, log_name: str) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    (report_dir / log_name).write_text(text, encoding="utf-8")
    if proc.returncode:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{text}")
    return text


def natural_ref_key(ref: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in ref if not ch.isdigit())
    digits = "".join(ch for ch in ref if ch.isdigit())
    return prefix, int(digits or 0), ref


def parse_netlist(path: Path) -> dict[str, dict[str, str]]:
    """ref -> {value, footprint, tag} from the SKiDL-emitted KiCad netlist."""
    text = path.read_text(encoding="utf-8")
    parts: dict[str, dict[str, str]] = {}
    for block in re.split(r"\(comp\s*\n", text)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', block).group(1)
        value = re.search(r'\(value "([^"]+)"\)', block).group(1)
        fp = re.search(r'\(footprint "([^"]+)"\)', block)
        tag = re.search(r'\(name "SKiDL Tag"\) "([^"]+)"', block)
        parts[ref] = {
            "value": value,
            "footprint": fp.group(1) if fp else "",
            "tag": tag.group(1) if tag else ref,
        }
    return parts


def locked_part(value: str, footprint: str):
    key = (value, footprint)
    seen = set()
    while True:
        if key in seen:
            raise SystemExit(f"Alias loop in part lock: {value} / {footprint}")
        seen.add(key)
        meta = PART_LOCK.get(key)
        if meta is None:
            raise SystemExit(f"No JLC part lock for {value!r} / {footprint!r}")
        alias = meta.get("alias")
        if not alias:
            return key, meta
        key = alias


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def zip_paths(zip_path: Path, files: list[Path], base: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            z.write(path, path.relative_to(base).as_posix())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rev", default="D", help="board revision letter (default D)")
    ap.add_argument("--out", default=None,
                    help="output directory (default kicad/fab_rev<REV>_<date>); "
                         "REFUSED if it already exists")
    args = ap.parse_args()

    rev = args.rev.upper()
    stem = f"wsl-phase8b-rev{rev}"
    # R2-15: sources DERIVE from the requested revision — the package label
    # and the design files can never disagree. (--rev C would look for
    # kicad/revC/wsl-phase8b-revC.* and fail, not silently relabel rev-D.)
    board_path = ROOT / "kicad" / f"rev{rev}" / f"{stem}.kicad_pcb"
    netlist_path = ROOT / "kicad" / f"{stem}.net"
    global BOARD_PATH, NETLIST_PATH
    BOARD_PATH, NETLIST_PATH = board_path, netlist_path
    out = Path(args.out) if args.out else ROOT / "kicad" / f"fab_rev{rev}_{date.today().isoformat()}"
    if not out.is_absolute():
        out = ROOT / out

    if not BOARD_PATH.exists():
        raise SystemExit(f"Missing routed board for rev-{rev}: {BOARD_PATH}\n"
                         "(R2-15: the export sources derive from --rev; a package "
                         "can only ever be labeled with its own revision.)")
    if not NETLIST_PATH.exists():
        raise SystemExit(f"Missing netlist for rev-{rev}: {NETLIST_PATH}")
    if not KICAD_CLI.exists():
        raise SystemExit(f"Missing KiCad CLI: {KICAD_CLI}")

    # P3 / change-list item 12: NEVER overwrite an as-ordered package. No rmtree, ever.
    if out.exists():
        raise SystemExit(
            f"REFUSING TO RUN: output directory already exists: {out}\n"
            "Pick a new dated directory (--out). Existing as-ordered packages are immutable."
        )
    gerber_dir = out / "gerber_drill"
    assembly_dir = out / "assembly"
    report_dir = out / "reports"
    review_dir = out / "review"
    for d in (out, gerber_dir, assembly_dir, report_dir, review_dir):
        d.mkdir(parents=True, exist_ok=False)

    # ---- gate 1: DRC 0/0/0 with the live remediation rules --------------------------
    drc_report = report_dir / f"DRC-rev{rev}-fab-export.rpt"
    run([str(KICAD_CLI), "pcb", "drc", "--severity-all", "--units", "mm",
         "--output", str(drc_report), str(BOARD_PATH)], report_dir, "kicad-drc.log")
    drc_text = drc_report.read_text(encoding="utf-8")
    required = ["Found 0 DRC violations", "Found 0 unconnected pads", "Found 0 Footprint errors"]
    missing = [line for line in required if line not in drc_text]
    if missing:
        raise SystemExit(f"DRC gate failed; missing expected lines: {missing}")

    # ---- gate 2: routed-mode topology audit ALL PASS --------------------------------
    audit_text = run([sys.executable, str(ROOT / "scripts" / "audit_revD_board.py"),
                      str(BOARD_PATH)], report_dir, "audit-revD-board.log")
    if "AUDIT RESULT: ALL PASS" not in audit_text:
        raise SystemExit("Topology audit failed; see reports/audit-revD-board.log")

    # ---- exports --------------------------------------------------------------------
    run([str(KICAD_CLI), "pcb", "export", "gerbers", "--output", str(gerber_dir),
         "--layers", GERBER_LAYERS, "--precision", "6", "--subtract-soldermask",
         "--check-zones", str(BOARD_PATH)], report_dir, "export-gerbers.log")
    run([str(KICAD_CLI), "pcb", "export", "drill", "--output", str(gerber_dir),
         "--excellon-separate-th", "--generate-map", "--generate-report",
         "--report-path", str(report_dir / "drill-report.txt"), str(BOARD_PATH)],
        report_dir, "export-drill.log")
    cpl_path = assembly_dir / f"{stem}-cpl.csv"
    run([str(KICAD_CLI), "pcb", "export", "pos", "--output", str(cpl_path),
         "--side", "both", "--format", "csv", "--units", "mm", "--exclude-dnp",
         str(BOARD_PATH)], report_dir, "export-pos.log")
    run([str(KICAD_CLI), "pcb", "export", "stats", "--output", str(report_dir / "board-stats.json"),
         "--format", "json", "--units", "mm", str(BOARD_PATH)], report_dir, "export-stats-json.log")
    run([str(KICAD_CLI), "pcb", "export", "stats", "--output", str(report_dir / "board-stats.txt"),
         "--format", "report", "--units", "mm", str(BOARD_PATH)], report_dir, "export-stats-report.log")
    run([str(KICAD_CLI), "pcb", "export", "ipcd356", "--output", str(report_dir / f"{stem}.ipc"),
         str(BOARD_PATH)], report_dir, "export-ipcd356.log")
    run([str(KICAD_CLI), "pcb", "export", "pdf", "--output", str(review_dir / f"{stem}-review-layers.pdf"),
         "--layers", PDF_LAYERS, "--mode-multipage", "--check-zones", str(BOARD_PATH)],
        report_dir, "export-review-pdf.log")

    # ---- BOM <-> CPL <-> netlist equality (the H6 gate) -----------------------------
    net_parts = parse_netlist(NETLIST_PATH)
    if len(net_parts) != EXPECTED_NETLIST_PARTS:
        raise SystemExit(f"Netlist part count {len(net_parts)} != pinned {EXPECTED_NETLIST_PARTS}")

    board = pcbnew.LoadBoard(str(BOARD_PATH))

    # ---- Round-3 (Codex 2026-07-21 PM, finding 8): the revision label EMBEDDED
    #      in the artifacts (title block -> gerber .gbrjob "Revision") must match
    #      --rev. Empty title block used to export as "rev?" — the board-house
    #      record could not identify the revision from the gerbers themselves. ----
    tb_rev = board.GetTitleBlock().GetRevision()
    if tb_rev != rev:
        raise SystemExit(
            f"Board title-block revision {tb_rev!r} != --rev {rev!r} — the gerber "
            f"job file would embed the wrong (or 'rev?') revision. Fix the board title "
            f"block (place_components_revD.py stamps it) before exporting.")

    board_parts: dict[str, dict[str, object]] = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref.startswith("TP") or ref.startswith("MK"):
            continue  # board-only test pads / mounting holes - never in the netlist/BOM
        board_parts[ref] = {
            "value": fp.GetValue(),
            "footprint": str(fp.GetFPID().GetLibItemName()),
            "lib": str(fp.GetFPID().GetLibNickname()),
            "dnp": bool(fp.IsDNP()) or bool(fp.IsExcludedFromBOM()),
        }

    net_refs = set(net_parts)
    brd_refs = set(board_parts)
    if net_refs != brd_refs:
        raise SystemExit(
            "netlist<->board refdes mismatch: "
            f"netlist-only={sorted(net_refs - brd_refs)} board-only={sorted(brd_refs - net_refs)}"
        )
    for ref in sorted(net_refs):
        nv, bv = net_parts[ref]["value"], board_parts[ref]["value"]
        nfull = net_parts[ref]["footprint"]
        nfp = nfull.split(":", 1)[-1]
        bfp = board_parts[ref]["footprint"]
        if nv != bv:
            raise SystemExit(f"value mismatch {ref}: netlist {nv!r} vs board {bv!r}")
        if nfp != bfp:
            raise SystemExit(f"footprint mismatch {ref}: netlist {nfp!r} vs board {bfp!r}")

    dnp_net = {r for r, p in net_parts.items() if is_dnp(p["tag"], p["value"])}
    dnp_brd = {r for r, p in board_parts.items() if p["dnp"]}
    if dnp_net != dnp_brd:
        raise SystemExit(
            f"DNP set mismatch: netlist-rule-only={sorted(dnp_net - dnp_brd)} "
            f"board-attr-only={sorted(dnp_brd - dnp_net)}"
        )
    if len(dnp_net) != EXPECTED_DNP:
        raise SystemExit(f"DNP count {len(dnp_net)} != pinned {EXPECTED_DNP}")

    placed = net_refs - dnp_net
    if len(placed) != EXPECTED_PLACED:
        raise SystemExit(f"Placed count {len(placed)} != pinned {EXPECTED_PLACED}")

    with cpl_path.open(newline="", encoding="utf-8-sig") as f:
        cpl_rows = list(csv.DictReader(f))
    cpl_refs = {row["Ref"].strip() for row in cpl_rows}
    if cpl_refs != placed:
        raise SystemExit(
            f"CPL<->placed mismatch: CPL-only={sorted(cpl_refs - placed)} "
            f"placed-only={sorted(placed - cpl_refs)}"
        )

    # ---- D_PROT hard lock (FR-3) ----------------------------------------------------
    dprot_refs = {r for r, p in net_parts.items() if p["tag"] == "D_PROT"}
    if dprot_refs != {"D17"}:
        raise SystemExit(f"D_PROT tag must be exactly D17, got {sorted(dprot_refs)}")
    if net_parts["D17"]["value"] != "SS34" or not net_parts["D17"]["footprint"].endswith("D_SMA"):
        raise SystemExit(f"D_PROT lock violated: D17 = {net_parts['D17']}")
    ss14 = [r for r, p in net_parts.items() if "SS14" in p["value"].upper()]
    if ss14:
        raise SystemExit(f"SS14 must not appear anywhere in rev-{rev}: {ss14}")

    # ---- grouped BOM (non-DNP) + DNP audit list -------------------------------------
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ref in placed:
        p = net_parts[ref]
        groups[(p["value"], p["footprint"].split(":", 1)[-1])].append(ref)
    bom_path = assembly_dir / f"{stem}-bom-non-dnp.csv"
    with bom_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "Quantity", "LCSC Part #"])
        for (value, fpname), refs in sorted(groups.items(), key=lambda kv: natural_ref_key(sorted(kv[1], key=natural_ref_key)[0])):
            refs = sorted(refs, key=natural_ref_key)
            w.writerow([value, ",".join(refs), fpname, len(refs), ""])
    dnp_path = assembly_dir / f"{stem}-dnp-excluded.csv"
    with dnp_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Value", "Footprint", "Reason"])
        for ref in sorted(dnp_net, key=natural_ref_key):
            p = net_parts[ref]
            if p["tag"] == "JP_J16_3V3":
                reason = ("Default-OPEN solder link (R2-4): J16 pin 5 ships NC; bridge "
                          "only for a verified 3.3V module - no part is ever fitted")
            elif p["tag"].endswith("_M1") or p["tag"] in M1_OPTIONAL_TAGS:
                reason = "M1 optional channel (never metered; populate only after runbook 3.6)"
            else:
                reason = "DNP (snubber/MOV sizing awaits the powered characterization session - G7 item 7)"
            w.writerow([ref, p["value"], p["footprint"].split(":", 1)[-1], reason])

    # ---- JLC Standard-PCBA split ----------------------------------------------------
    hand_refs = {r for r in placed if r in HAND_SOLDER_REFS}
    if hand_refs != HAND_SOLDER_REFS:
        raise SystemExit(f"Hand-solder refs not all placed: missing {sorted(HAND_SOLDER_REFS - hand_refs)}")
    if len(hand_refs) != EXPECTED_HAND_SOLDER:
        raise SystemExit(f"Hand-solder count {len(hand_refs)} != pinned {EXPECTED_HAND_SOLDER}")
    jlc_refs = placed - hand_refs
    if len(jlc_refs) != EXPECTED_JLC_PLACED:
        raise SystemExit(f"JLC placed count {len(jlc_refs)} != pinned {EXPECTED_JLC_PLACED}")

    jlc_groups: dict[tuple[str, str], dict[str, object]] = {}
    for ref in jlc_refs:
        p = net_parts[ref]
        fpname = p["footprint"].split(":", 1)[-1]
        # strip the _D1.4 suffix marker only for lock lookup keys that never carry it
        key, meta = locked_part(p["value"], fpname)
        g = jlc_groups.setdefault(key, {
            "Comment": meta["locked_spec"], "Designators": [], "Footprint": fpname,
            "Quantity": 0, "LCSC Part #": meta["lcsc"], "MFR Part #": meta["mpn"],
            "Manufacturer": meta["manufacturer"], "JLC Class": meta["class"],
            "Notes": meta["note"],
        })
        g["Designators"].append(ref)
        g["Quantity"] = int(g["Quantity"]) + 1
    jlc_bom = []
    for g in jlc_groups.values():
        g["Designator"] = ",".join(sorted(g["Designators"], key=natural_ref_key))
        jlc_bom.append(g)
    jlc_bom.sort(key=lambda r: natural_ref_key(str(r["Designator"]).split(",")[0]))
    if sum(int(r["Quantity"]) for r in jlc_bom) != EXPECTED_JLC_PLACED:
        raise SystemExit("JLC BOM quantity sum drifted from the placed set")
    if len(jlc_bom) != EXPECTED_JLC_LINES:
        raise SystemExit(f"Expected {EXPECTED_JLC_LINES} unique JLC part lines, got {len(jlc_bom)}")

    # relay/MCP/D_PROT lock re-checks on the emitted lines
    by_lcsc = {str(r["LCSC Part #"]): r for r in jlc_bom}
    relay = by_lcsc.get("C116963")
    if not relay or "5VDC" not in str(relay["MFR Part #"]):
        raise SystemExit("Relay lock failed: C116963 / G5LE-14 5VDC required")
    mcp = by_lcsc.get("C47023")
    if not mcp or "MCP23017" not in str(mcp["MFR Part #"]) or "MCP23S17" in str(mcp["MFR Part #"]):
        raise SystemExit("MCP lock failed: MCP23017 I2C part required")
    dprot_line = by_lcsc.get("C8678")
    if (not dprot_line or str(dprot_line["MFR Part #"]) != "SS34"
            or str(dprot_line["Manufacturer"]) != "MDD"
            or str(dprot_line["Designator"]) != "D17"
            or "SMA" not in str(dprot_line["Comment"])):
        raise SystemExit("D_PROT JLC lock failed: D17 must map to MDD SS34 LCSC C8678 in SMA")
    # R2-3 hard lock: the tap FETs Q17-Q20 must ride the onsemi 2N7002LT1G
    # line (C16338) and nothing else may join it.
    tap_line = by_lcsc.get("C16338")
    if (not tap_line or str(tap_line["MFR Part #"]) != "2N7002LT1G"
            or str(tap_line["Manufacturer"]) != "onsemi"
            or str(tap_line["Designator"]) != "Q17,Q18,Q19,Q20"):
        raise SystemExit("R2-3 lock failed: Q17-Q20 must map exactly to onsemi 2N7002LT1G LCSC C16338 "
                         f"(got {tap_line})")
    # R2-15 hard lock: the 10M gate pulldowns are R135/R138/R141 on the
    # pinned C26108 identity (MATCH-AT-UPLOAD is dead).
    r10m_line = by_lcsc.get("C26108")
    if (not r10m_line or str(r10m_line["MFR Part #"]) != "0805W8F1005T5E"
            or str(r10m_line["Designator"]) != "R135,R138,R141"):
        raise SystemExit("R2-15 lock failed: R135/R138/R141 must map exactly to UNI-ROYAL "
                         f"0805W8F1005T5E LCSC C26108 (got {r10m_line})")
    if any(str(r["LCSC Part #"]) == "MATCH-AT-UPLOAD" for r in jlc_bom):
        raise SystemExit("R2-15: MATCH-AT-UPLOAD rows are forbidden - every JLC line needs a pinned C-number")
    # R2-4 hard locks: buffer + ESD + polyfuse identity.
    for lcsc, mpn, refs, what in (("C880333", "TCA4307DGKR", "U46", "TCA4307 stuck-bus-recovery buffer"),
                                  ("C13612", "SRV05-4.TCT", "U47", "Semtech SRV05-4 ESD array"),
                                  ("C207035", "1206L020YR", "F1", "Littelfuse 200mA polyfuse")):
        line = by_lcsc.get(lcsc)
        if (not line or str(line["MFR Part #"]) != mpn or str(line["Designator"]) != refs):
            raise SystemExit(f"R2-4 lock failed: {refs} must map to {what} ({mpn}, LCSC {lcsc}); got {line}")

    jlc_cpl = []
    for row in cpl_rows:
        if row["Ref"].strip() not in jlc_refs:
            continue
        side = row["Side"].strip().lower()
        if side not in ("top", "bottom"):
            raise SystemExit(f"Unexpected CPL side value: {row['Side']!r}")
        jlc_cpl.append({
            "Designator": row["Ref"].strip(),
            "Mid X": f"{float(row['PosX']):.6f}",
            "Mid Y": f"{float(row['PosY']):.6f}",
            "Layer": side.capitalize(),
            "Rotation": f"{float(row['Rot']):.6f}",
        })
    jlc_cpl.sort(key=lambda r: natural_ref_key(r["Designator"]))
    if {r["Designator"] for r in jlc_cpl} != jlc_refs:
        raise SystemExit("JLC CPL refs != JLC BOM refs")

    excluded_rows = [
        {"Designator": ref, "Comment": net_parts[ref]["value"],
         "Footprint": net_parts[ref]["footprint"].split(":", 1)[-1],
         "Reason": ("Hand solder: Raspberry Pi Pico module" if ref == "A1" else
                    "Hand solder: TRACO TMA-0505S isolated DC/DC" if ref == "U45" else
                    "Hand solder: connector/header")}
        for ref in sorted(hand_refs, key=natural_ref_key)
    ]

    write_csv(assembly_dir / f"{stem}-jlc-standard-pcba-bom.csv",
              ["Comment", "Designator", "Footprint", "Quantity", "LCSC Part #",
               "MFR Part #", "Manufacturer", "JLC Class", "Notes"], jlc_bom)
    write_csv(assembly_dir / f"{stem}-jlc-standard-pcba-upload-bom.csv",
              ["Comment", "Designator", "Footprint", "Quantity", "LCSC Part #"], jlc_bom)
    write_csv(assembly_dir / f"{stem}-jlc-standard-pcba-cpl.csv",
              ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"], jlc_cpl)
    write_csv(assembly_dir / f"{stem}-jlc-standard-pcba-excluded.csv",
              ["Designator", "Comment", "Footprint", "Reason"], excluded_rows)
    write_csv(assembly_dir / f"{stem}-jlc-standard-pcba-part-lock.csv",
              ["LCSC Part #", "MFR Part #", "Manufacturer", "JLC Class", "Locked Spec",
               "Quantity", "Designators", "Notes"],
              [{"LCSC Part #": r["LCSC Part #"], "MFR Part #": r["MFR Part #"],
                "Manufacturer": r["Manufacturer"], "JLC Class": r["JLC Class"],
                "Locked Spec": r["Comment"], "Quantity": r["Quantity"],
                "Designators": r["Designator"], "Notes": r["Notes"]} for r in jlc_bom])

    # ---- hand-solder + harness BOMs -------------------------------------------------
    hand_bom_path = assembly_dir / f"{stem}-hand-solder-bom.csv"
    write_csv(hand_bom_path,
              ["Ref", "Qty", "Role", "Manufacturer", "MFR Part #", "Description",
               "Source", "Status", "Notes"], HAND_SOLDER_ROWS)
    hand_bom_refs = set()
    for row in HAND_SOLDER_ROWS:
        hand_bom_refs.update(r.strip() for r in str(row["Ref"]).split(","))
    if hand_bom_refs != HAND_SOLDER_REFS:
        raise SystemExit(f"Hand-solder BOM refs != exclusion set: {sorted(hand_bom_refs ^ HAND_SOLDER_REFS)}")

    harness_fields = ["Mate For", "Qty per board", "Manufacturer", "MFR Part #",
                      "Description", "Termination", "Coding / marking", "Status", "Notes"]
    harness_pkg_path = assembly_dir / f"{stem}-harness-bom.csv"
    write_csv(harness_pkg_path, harness_fields, HARNESS_ROWS)
    write_csv(DOCS_HARNESS_BOM, harness_fields, HARNESS_ROWS)  # tracked doc copy
    harness_pns = {str(r["MFR Part #"]) for r in HARNESS_ROWS}
    for pn in ("1840447", "1840405", "1734634", "1840489", "1840463", "1840382"):
        if pn not in harness_pns:
            raise SystemExit(f"Harness BOM missing mandatory PN {pn}")

    # ---- README + zips + manifest ---------------------------------------------------
    generated_at = datetime.now().isoformat(timespec="seconds")
    readme = out / "README-fab-package.txt"
    readme.write_text("\n".join([
        f"WSL Phase 8b rev-{rev} as-ordered fab package",
        f"Generated: {generated_at}",
        f"Board: {rel(BOARD_PATH)}",
        f"Netlist: {rel(NETLIST_PATH)}",
        "",
        "Release gates re-proven by this export run:",
        "- kicad-cli DRC: 0 violations / 0 unconnected / 0 footprint errors",
        "  (live remediation .kicad_dru: 2.65 / 3.35 / 1.6 mm - spec R2.3).",
        "- audit_revD_board.py routed mode: ALL PASS (Safety_Rail == 13).",
        "- BOM<->CPL<->netlist equality asserted: 271 parts / 28 DNP / 243 placed /",
        "  226 JLC-placed / 17 hand-solder; every placed refdes present in all three.",
        "- D_PROT hard lock: D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3); no SS14",
        "  anywhere.",
        "- Round-2 locks (2026-07-21): Q17-Q20 = onsemi 2N7002LT1G C16338 (R2-3);",
        "  R135/R138/R141 = UNI-ROYAL 10M C26108 (R2-15, identity pinned - verify",
        "  stock at order, OOS at LCSC retail 2026-07-21); U46 = TCA4307DGKR C880333;",
        "  U47 = Semtech SRV05-4.TCT C13612; F1 = Littelfuse 1206L020YR C207035.",
        "  JP1 (J16 3.3V solder link) is DNP: default-OPEN, no part fitted.",
        "",
        "Uploads:",
        f"- {stem}-gerber-drill.zip  -> JLC PCB order (4-layer FR-4 1.6mm, 1oz/0.5oz,",
        "  ENIG, confirm preview reads 250 x 240 mm - REV-D IS 240 mm TALL).",
        f"- assembly/{stem}-jlc-standard-pcba-upload-bom.csv + -cpl.csv -> Standard PCBA.",
        "",
        "Hand-solder after JLC: A1, J1-J11, J13, J14, J15, J16, U45.",
        "  U45 is the TMA-0505S (rev-C called it U37 - 46 refdes shifted; use",
        "  docs/phase8_revD_first_article_pack.md, never rev-C bench notes).",
        "",
        "Harness order (ship WITH the boards - gate G13/OG-3):",
        f"- assembly/{stem}-harness-bom.csv (tracked copy: docs/phase8_revD_harness_bom.csv).",
        "- Termination per Phoenix MC 1,5 data: 7 mm strip, 0.22-0.25 Nm, max 0.5 mm2",
        "  with insulated ferrule (the old 8 mm / 0.5 Nm / 0.75-1.0 mm2 figures were",
        "  wrong - corrected 2026-07-21).",
        "- CP-MSTB 1734634 coding profiles fit the PLUG, never a standard header;",
        "  sacrificial-pair proof before coding production parts (first-article FA-8).",
        "",
        "Manual inspection gate G12 before paying:",
        "- K1-K7 pad-net map (coil 2/5, COM 1, NO 3, NC 4 unused).",
        "- The 8 new AUX4-11 opto channels + J15/J16 pads (1.4 mm drills - FR-9).",
        "- Five doubled power vias (RD-VIA-1 twins) visible in the drill map.",
        "- 'KEYED: NOT ...' silk legible at J3/J15/J13/J16 (1.2 mm / 0.20 mm stroke;",
        "  'KEYED: NOT J13 LAMP' moved below the R2-4 cluster at (136, 226.5)).",
        "- Round-2 additions: J16 protection cluster (F1/U46/U47/JP1/C16/R142/R143)",
        "  south of J16; REV_ID straps R144/R145 east of the Pico; TP17-24 tap",
        "  probe pads + TP silk legend + TP2/TP5 DO-NOT-BRIDGE marks.",
        "- USB keep-out clear; row-39 bottom-edge copper acknowledged (1.28 mm to edge).",
        "",
        "This package is fab-geometry evidence only. Fab ORDER remains gated on G7/G8/",
        "G13/G14 + first article per docs/phase8_revD_readiness_checklist.md.",
        "",
    ]), encoding="utf-8")

    gerber_suffixes = {".gtl", ".gbl", ".g1", ".g2", ".g3", ".gts", ".gbs", ".gtp", ".gbp",
                       ".gto", ".gbo", ".gm1", ".gbr", ".gbrjob", ".drl", ".pdf", ".rpt"}
    gerber_files = [p for p in gerber_dir.rglob("*") if p.is_file() and p.suffix.lower() in gerber_suffixes]
    if not any(p.suffix.lower() == ".drl" for p in gerber_files):
        raise SystemExit("No Excellon drill files found in fab output")
    if len([p for p in gerber_files if p.suffix.lower() not in {".gbrjob", ".drl", ".pdf", ".rpt"}]) < 11:
        raise SystemExit("Expected at least 11 Gerber layer files")

    gerber_zip = out / f"{stem}-gerber-drill.zip"
    zip_paths(gerber_zip, gerber_files, gerber_dir)

    upload_zip = out / f"{stem}-jlc-standard-pcba-upload.zip"
    upload_files = [
        gerber_zip,
        assembly_dir / f"{stem}-jlc-standard-pcba-upload-bom.csv",
        assembly_dir / f"{stem}-jlc-standard-pcba-cpl.csv",
        assembly_dir / f"{stem}-jlc-standard-pcba-part-lock.csv",
        assembly_dir / f"{stem}-jlc-standard-pcba-excluded.csv",
        readme,
    ]
    for p in upload_files:
        if not p.exists():
            raise SystemExit(f"Missing JLC upload file: {p}")
    zip_paths(upload_zip, upload_files, out)

    package_zip = out / f"{stem}-fab-package.zip"
    package_files = [p for p in out.rglob("*")
                     if p.is_file() and p.name not in {"manifest.json", package_zip.name}]
    zip_paths(package_zip, package_files, out)

    all_files = [p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"]
    manifest = {
        "package": f"phase8b rev-{rev} as-ordered fab package",
        "generated_at": generated_at,
        "source_board": rel(BOARD_PATH),
        "source_board_sha256": sha256(BOARD_PATH),
        "source_netlist": rel(NETLIST_PATH),
        "source_netlist_sha256": sha256(NETLIST_PATH),
        "counts": {
            "netlist_parts": len(net_parts),
            "dnp": len(dnp_net),
            "placed": len(placed),
            "jlc_placed": len(jlc_refs),
            "jlc_lines": len(jlc_bom),
            "hand_solder": len(hand_refs),
        },
        "d_prot_lock": "D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3)",
        "files": [{"path": rel(p) if str(p).startswith(str(ROOT)) else str(p),
                   "bytes": p.stat().st_size, "sha256": sha256(p)}
                  for p in sorted(all_files)],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Fab output: {out}")
    print(f"Counts: parts={len(net_parts)} dnp={len(dnp_net)} placed={len(placed)} "
          f"jlc={len(jlc_refs)} lines={len(jlc_bom)} hand={len(hand_refs)}")
    print(f"Gerber/drill zip: {gerber_zip}")
    print(f"JLC upload zip: {upload_zip}")
    print(f"Package zip: {package_zip}")
    print(f"Harness BOM (tracked): {DOCS_HARNESS_BOM}")
    print("ALL EXPORT GATES PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
