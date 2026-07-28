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
  equal the placed (non-DNP) set exactly. Pinned counts (see the EXPECTED_* constants -
  never re-type them here): 391 parts / 68 DNP / 323 placed / 306 JLC-placed /
  27 JLC lines / 17 hand-solder, after the r6 spin.
  (History: 252 pre-remediation -> 262 after R1.7 -> 271 after the 2026-07-21 round-2
  batch: +9 parts for the R2-4 J16 protection stack and R2-6 REV_ID straps; the JP1
  default-OPEN solder link is the 28th DNP.)
- Round-2 hard locks (Codex 2026-07-21): Q17-Q20 -> onsemi 2N7002LT1G C16338 (R2-3);
  R135/R138/R141 -> FOJAN 10M C2933281 (r8 re-pin; C26108 retired OOS) with
  MATCH-AT-UPLOAD rows forbidden (R2-15);
  U46 -> TCA4307DGKR C880333, U47 -> Semtech SRV05-4.TCT C13612, F1 -> Littelfuse
  1206L020YR C207035 (R2-4). Source paths DERIVE from --rev so a rev-D board can never
  be exported under another revision's label (R2-15).
- Rev-D input-margin lock (2026-07-23): exactly R4,R6,...,R82 are 47k,
  UNI-ROYAL 0805W8F4702T5E / LCSC C17713; no unrelated part may join that
  line and the remaining 10k networks stay on C17414. The production
  configuration must leave RP2040 GP6-GP13 internal pulls disabled and read
  back MCP input GPPUA/GPPUB=0x00 so the external 47k is the sole bias.
- r6 input-protection equality gate (2026-07-25): the totals above cannot distinguish
  "40 series diodes + 40 clamps" from "80 clamps and no series diode", so
  assert_r6_input_protection() checks every one of the 40 channels individually - part
  identity, DNP state, membership in placed/CPL/JLC, and the three-node FIELD_LED_<n>
  topology. It also emits the per-channel STUFFING BOM (all 40 channels populated
  uniformly; the DNP Cflt is the only decision and each row carries the measurement that
  decides it) and locks the FIELD-STUFFED (non-JLC) MPNs: Cflt 2.2uF = Samsung
  CL21B225KAFNNNE / C19110 (FR-17), Cflt 10nF = TORCH C0805B103K500NT / C17702767 (FR-18).
- D_PROT is HARD-LOCKED to MDD SS34, LCSC C8678, SMA/DO-214AC (run-log FR-3). The script
  fails if D17 is not SS34/D_SMA, if any SS14 survives anywhere, or if the JLC BOM line for
  SS34 carries anything but C8678/MDD/SMA.
- Every file in the package lands in a sha256 manifest (manifest.json) so the exact
  as-ordered package is immutable and independently verifiable. KiCad embeds generation
  timestamps (and may vary serialization order) in several Gerber/drill/report/PDF
  outputs, so a later clean export is expected to satisfy the same topology/BOM/count
  gates but is not claimed to be byte-identical to the frozen package.
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
DOCS_R6_STUFFING = ROOT / "docs" / "phase8_revD_r6_channel_stuffing.csv"
FW_RELEASE_MANIFEST = ROOT / "firmware" / "rp2040" / "release" / "firmware_manifest.json"

# ---- pinned release counts (fail closed on ANY drift) -------------------------------
# r6 input protection (2026-07-25, docs/phase8_revD_r6_input_protection_
# spec_2026-07-25.md SS A.4/E.2): +120 parts = 40 Dser + 40 Dclamp (BOTH
# POPULATED, joining the EXISTING 1N4148/SOD-323 line, qty 8 -> 88) + 40 Cflt
# (ALL DNP by design). Hence +120 parts, +40 DNP, +80 placed, +80 JLC-placed,
# and EXPECTED_JLC_LINES stays 27 - r6 adds ZERO new assembled part classes.
EXPECTED_NETLIST_PARTS = 391     # 271 + 120 r6
EXPECTED_DNP = 68                # 28 + 40 Cflt (Dser/Dclamp are POPULATED)
EXPECTED_PLACED = 323            # 391 - 68
EXPECTED_HAND_SOLDER = 0         # r10 wave 2: ZERO hand-solder. Every placement is JLC-placed.
EXPECTED_JLC_PLACED = 323        # r10: ALL placed parts (323 - 0 hand-solder)
EXPECTED_JLC_LINES = 37          # 30 + 7 (r10 wave 2: Pico, IDC header, MCV-10, MCV-14,
                                 # MCV-12, MCV-6, TRACO). J15->J3 and J16->J13 collapse via
                                 # aliases, as J6-J11 already do; without them it would be 39.

# ---- r6 per-channel input-protection equality gate (2026-07-25) ---------------------
# The pre-r6 gate asserted TOTALS only (parts/DNP/placed/CPL). Totals cannot tell
# "40 series diodes + 40 clamps + 40 DNP caps" from "80 clamps and no series diode",
# and the r6 safety argument is entirely about WHICH part is where:
#   - a DNP/absent Dser leaves the channel OPEN-CIRCUIT (spec SS A.3.4), and
#   - a missing Dclamp is invisible in commissioning (first-article FA-15).
# So the equality asserts below are extended per PART CLASS, and every one of the 120
# new parts must appear in the netlist, the board, the CPL and the JLC BOM (or, for the
# 40 Cflt, in NONE of the assembled outputs and in the DNP exclusion CSV).
EXPECTED_R6_DSER = 40            # Dser_* series blocking diodes - POPULATED, never DNP
EXPECTED_R6_DCLAMP = 40          # Dclamp_* anti-parallel clamps - POPULATED
EXPECTED_R6_CFLT = 40            # Cflt_* logic-side filter caps - ALL DNP by design
EXPECTED_R6_CFLT_FAST = 8        # 10nF on the RP2040 fast channels (1 ms edge budget)
EXPECTED_R6_CFLT_SLOW = 32       # 2.2uF on the MCP23017 slow channels
EXPECTED_1N4148_QTY = 88         # 8 pre-r6 (relay flyback / steering) + 80 r6
# RP2040 fast channels - mirror of generate_kicad_netlist_revD.FAST_INPUTS. A Cflt
# large enough to integrate 60 Hz (>=951 nF) on any of these blows the 1 ms edge
# budget by 183x, so the fast set is called out explicitly in the stuffing table.
R6_FAST_CHANNELS = ("SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R")

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
HAND_SOLDER_REFS: set[str] = set()   # r10: EMPTY. Nothing is hand-soldered any more.
# History: 17 at r8 -> 9 at r9 (wave 1: J2, J6-J11, J14) -> 0 at r10 (wave 2: A1, J1, J3,
# J4, J5, J13, J15, J16, U45). The sourcing route per part - JLC stock, Global Sourcing or
# consigned - is chosen at ORDER time and does not affect this split.

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
        "locked_spec": "PTC resettable fuse 200mA hold @23C / 24V, 1206",
        "note": "F_J16_5V current limit for the J16 module supply (R2-4; "
                "allowance re-derived to 45mA @85C worst case per R3-7). Any "
                "substitute must be 1206 and have minimum Ihold at 85C >=90mA. "
                "Trip-current equivalence is not an acceptance criterion: a PPTC "
                "trip point is time/temperature dependent, not a hard clamp.",
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
    ("47k", "R_0805_2012Metric"): {
        "lcsc": "C17713", "mpn": "0805W8F4702T5E", "manufacturer": "UNI-ROYAL",
        "class": "Basic", "locked_spec": "47k 1% 1/8W 0805 resistor",
        "note": "Rev-D PC817 collector pull-ups only (Rpu_*, 40 channels). "
                "Do not merge with or substitute for unrelated 10k networks.",
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
        # R8 (2026-07-26): identity RE-PINNED to FOJAN FRC0805F1005TS / C2933281.
        # The R2-15 pin (UNI-ROYAL 0805W8F1005T5E / C26108) went permanently
        # out of stock; a 26-part LCSC sweep of 10M 0805 1% found only THREE
        # lines with any stock - C2933281 (FOJAN, 11,300), C46635375
        # (CHANGLONG, 300) and C3037549 (LIZ, 100). Against a 102-piece fleet
        # need (3/board x 34) only C2933281 has real headroom; the other two
        # are 3x and 1x. No UNI-ROYAL 10M 0805 line has stock (C2780392 = 0),
        # so there is no same-manufacturer rescue.
        # Spec parity with the retired pin: 10M +/-1% 0805 150V 125mW
        # +/-100ppm/C thick film - identical on every locked attribute.
        # Any future substitute must still be >=10M 0805 1% with its C-number
        # FETCH-VERIFIED on the LCSC product page (C325772 was a hallucinated
        # match, rejected - see run log H6). Never take a C-number from a
        # search result alone.
        "lcsc": "C2933281", "mpn": "FRC0805F1005TS", "manufacturer": "FOJAN",
        "class": "Extended", "locked_spec": "10M 1% 1/8W 0805 resistor",
        "note": "R_TAPG_* gate pulldowns (R135/R138/R141). Identity re-pinned "
                "C2933281 FOJAN at r8 (2026-07-26) after C26108 went OOS; "
                "JLC assembly stock confirmed at order time.",
    },
    # ---- WAVE 2 (r10, 2026-07-27): the last NINE placements move to JLC ----------------
    # Hand-solder goes to ZERO. Every C-number below was verified against its own JLC
    # part-detail page (searching JLC by bare numeric Phoenix MPN returns FALSE NEGATIVES).
    # Sourcing route is chosen per-part AT ORDER TIME - JLC stock, Global Sourcing, or
    # consigned - and does not change this BOM. JLC 2026-07-27: "indicate your components
    # in the BOM and CPL files ... select the corresponding components when placing the order."
    # NOTE: several of these show 0 stock in JLC's library today; that is a PROCUREMENT
    # question, not an identity one. All resolve to the EXACT required MPNs, so no
    # substitution is in play and FR-2/FR-9 stay closed.
    ("RP2040 Pico", "RaspberryPi_Pico_SMD"): {
        "lcsc": "C7203002", "mpn": "SC0915", "manufacturer": "Raspberry Pi",
        "class": "Extended", "locked_spec": "Raspberry Pi Pico, RP2040, bare castellated module",
        "note": "A1. JLC confirmed IN WRITING 2026-07-27: 'the Raspberry Pi Pico model "
                "provided by JLCPCB is SC0915' = BARE module, RP2040, NO pre-soldered headers. "
                "MUST NOT be SC0917 (Pico H, headers fitted - cannot be reflow-mounted) and MUST "
                "NOT be an RP2350 Pico 2 - the firmware is RP2040-only. Require a silkscreen "
                "photo at G12 before payment.",
    },
    ("J_PI", "IDC-Header_2x10_P2.54mm_Vertical"): {
        "lcsc": "C17373551", "mpn": "3020-20-0100-00", "manufacturer": "CNC Tech",
        "class": "Extended", "locked_spec": "2x10 shrouded IDC box header, 2.54mm, vertical THT",
        "note": "J1. Keying verified 2026-07-27: pin-1 row faces the board interior, matching "
                "rev-B/C. This is the ONE connector where a conforming DIN 41651 / IEC 60603-13 "
                "equivalent is acceptable; every Phoenix part is exact-only.",
    },
    ("J_SLOW_IN_C", "PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical_D1.4"): {"alias": ("J_FAST_IN", "PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical_D1.4")},
    ("J_FAST_IN", "PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical_D1.4"): {
        "lcsc": "C3585531", "mpn": "1843680", "manufacturer": "Phoenix Contact",
        "class": "Extended", "locked_spec": "Phoenix MCV 1,5/10-G-3,5 10-pos vertical header, 3.5mm",
        "note": "J3 + J15, 2/board. JLC price is $11.31 and they confirmed 2026-07-27 they CANNOT "
                "adjust it (supplier-set) against Mouser ~$5.02 with 722 in stock - so this line "
                "is a DECIDED buy-ourselves/consign, ~$453 saved. J3/J15 are an electrically "
                "SILENT cross-mate: CP-MSTB coding is what prevents it.",
    },
    ("J_SLOW_IN_A", "PhoenixContact_MCV_1,5_14-G-3.5_1x14_P3.50mm_Vertical_D1.4"): {
        "lcsc": "C3582595", "mpn": "1843729", "manufacturer": "Phoenix Contact",
        "class": "Extended", "locked_spec": "Phoenix MCV 1,5/14-G-3,5 14-pos vertical header, 3.5mm",
        "note": "J4. JLC's listing shows 'Assembly Type: SMT Assembly' on a through-hole part; "
                "they confirmed 2026-07-27 the default is WAVE SOLDERING and the attribute is a "
                "data error. Its mating plug 1840489 is the discontinued lifetime-buy line.",
    },
    ("J_SLOW_IN_B", "PhoenixContact_MCV_1,5_12-G-3.5_1x12_P3.50mm_Vertical_D1.4"): {
        "lcsc": "C3019636", "mpn": "1843703", "manufacturer": "Phoenix Contact",
        "class": "Extended", "locked_spec": "Phoenix MCV 1,5/12-G-3,5 12-pos vertical header, 3.5mm",
        "note": "J5. DigiKey holds 2,139 against a need of 38 if JLC cannot supply.",
    },
    ("J_EXT_I2C", "PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical_D1.4"): {"alias": ("J_LAMP_LED", "PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical_D1.4")},
    ("J_LAMP_LED", "PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical_D1.4"): {
        "lcsc": "C5443576", "mpn": "1843648", "manufacturer": "Phoenix Contact",
        "class": "Extended", "locked_spec": "Phoenix MCV 1,5/6-G-3,5 6-pos vertical header, 3.5mm",
        "note": "J13 + J16, 2/board. The ONLY A'.2 line JLC can fill from stock today (503 vs 72 "
                "needed). J13/J16 cross-mate is a DAMAGE path - a J13 lamp plug in J16 lands "
                "resistorless LEDs across 5V and wedges I2C. CP-MSTB coding prevents it.",
    },
    ("TMA-0505S", "Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT"): {
        "lcsc": "C5454708", "mpn": "TMA 0505S", "manufacturer": "TRACO Power",
        "class": "Extended", "locked_spec": "TRACO TMA 0505S 1W isolated DC/DC, 5V/5V 200mA, 1kV, 6-SIP THT",
        "note": "U45. Sole source of FIELD_WET_V - the ENTIRE opto front end depends on its 1kV "
                "isolation. NO SUBSTITUTION without pinout and isolation review. Found only via a "
                "no-space MPN search ('TMA0505S'); JLC support had said it was not in the library. "
                "JLC package reads SIP 19.5x6.1mm against TRACO's 0.77x0.24in = 19.56x6.10mm - "
                "exact match. Stock 16 vs 38 needed, so expect to consign.",
    },
    # ---- WAVE 1 (r9, 2026-07-26): three connector types moved from hand-solder to JLC ----
    # Library-native, in stock, unique PN, uncoded and unkeyed. JLC marks all three
    # "Wave Soldering / Economic and Standard" - the same THT path this board already
    # uses for its 40 PC817 optos and 6 G5LE relays, so no service-tier change.
    # NOT moved in wave 1: J3/J4/J5/J13/J15/J16 (unresolved in the JLC library - needs a
    # Global Sourcing quote), A1 (Pico C-number pending), U45 (TRACO, ~30 pcs vs 34 need),
    # J1 (identity is CANDIDATE, keying never verified - stays hand until it is).
    ("J_PWR 5V", "TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal"): {
        "lcsc": "C480520", "mpn": "1715734", "manufacturer": "Phoenix Contact",
        "class": "Extended",
        "locked_spec": "Phoenix MKDS 1,5/3-5,08 3-pos screw terminal, 5.08mm, THT",
        "note": "J2 board 5V power terminal. Verified 2026-07-26: JLC partdetail C480520 "
                "= Phoenix 1715734, 1x3P 5.08mm 250V 17.5A, Wave Soldering, Economic+"
                "Standard; LCSC 1,173 in stock @ $0.4365/100+. Fleet need 34 (+spares).",
    },
    # J6-J11 are six DIFFERENT netlist values on ONE identical footprint and part. Alias
    # them to a single canonical entry or the BOM emits six lines for one component -
    # six feeder loads and six feeder fees for the same reel.
    ("J_MOTION_T 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"):
        {"alias": ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal")},
    ("J_MOTION_SP 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"):
        {"alias": ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal")},
    ("J_MOTION_BE 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"):
        {"alias": ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal")},
    ("J_MOTION_M 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"):
        {"alias": ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal")},
    ("J_MOTION_M2 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"):
        {"alias": ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal")},
    ("J_MOTION_S 5.08mm", "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"): {
        "lcsc": "C480516", "mpn": "1715721", "manufacturer": "Phoenix Contact",
        "class": "Extended",
        "locked_spec": "Phoenix MKDS 1,5/2-5,08 2-pos screw terminal, 5.08mm, THT",
        "note": "J6-J11 machine relay-output terminals, 6/board. Verified 2026-07-26: JLC "
                "partdetail C480516 = Phoenix 1715721, 1x2P 5.08mm 250V 17.5A, Wave "
                "Soldering, Economic+Standard; LCSC 1,591 in stock @ $0.3437/100+. Fleet "
                "need 204 (+spares). NOTE C5183929 is the SAME Phoenix MPN but held only "
                "~239 pcs - too thin for 204; C480516 is the line to use.",
    },
    ("J_SAFETY", "PhoenixContact_MCV_1,5_4-G-3.5_1x04_P3.50mm_Vertical_D1.4"): {
        "lcsc": "C480549", "mpn": "1843622", "manufacturer": "Phoenix Contact",
        "class": "Extended",
        "locked_spec": "Phoenix MCV 1,5/4-G-3,5 4-pos vertical header, 3.5mm, THT",
        "note": "J14 safety-loop header. Verified 2026-07-26: JLC partdetail C480549 = "
                "Phoenix 1843622, 1x4P 3.5mm 160V 8A, Wave Soldering, Economic+Standard; "
                "LCSC 2,481 in stock @ $1.11/1+. Fleet need 34 (+spares). NOT one of the "
                "FA-8 coded pairs - no coding rib is cut on J14, so JLC placing it does "
                "not touch the keying scheme. Board drill is the project-local _D1.4 "
                "footprint (1.4mm, 0.30mm annular vs JLC's 0.15mm floor = 2x margin).",
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


# ---- FIELD-STUFFED part locks (DNP on the board, bought and fitted by US) -----------
# PART_LOCK covers only what JLC assembles. The 40 r6 Cflt_* lands ship EMPTY, so their
# MPN never reached a lock table - and a part nobody locked is a part the crew guesses
# at with a meter in one hand. These locks are emitted into the DNP-exclusion CSV so the
# stuffing decision and the buy identity travel in the SAME row.
# Identities: run-log FR-17 (2.2uF) and FR-18 (10nF) - footprint-vs-datasheet reviews
# done at r6, same 0805 land as the existing C13 10nF and the Csnub_* family.
FIELD_STUFF_LOCK: dict[tuple[str, str], dict[str, str]] = {
    ("2.2uF X7R DNP", "C_0805_2012Metric"): {
        "lcsc": "C19110", "mpn": "CL21B225KAFNNNE",
        "manufacturer": "Samsung Electro-Mechanics",
        "locked_spec": "2.2uF 25V X7R +/-10% 0805 MLCC",
        "note": "FR-17. 25 V minimum (the logic side is 3.3 V, but X7R DC-bias "
                "derating at 0805/2.2uF is severe: worst-effective ~1.65uF is what "
                "the 951 nF 60 Hz floor is computed against). A 1uF part (C28323) "
                "was REJECTED: 749 nF effective < 951 nF.",
    },
    ("10nF X7R DNP", "C_0805_2012Metric"): {
        "lcsc": "C17702767", "mpn": "C0805B103K500NT", "manufacturer": "TORCH",
        "locked_spec": "10nF 50V X7R +/-10% 0805 MLCC",
        "note": "FR-18. Same MPN as the assembled C13 line - zero new part class. "
                "10 nF -> 0.493 ms edge; 22 nF is the HARD ceiling on a fast channel.",
    },
}

# ---- r6 per-channel stuffing evidence (the ONLY per-channel decision left) -----------
# Dser_* and Dclamp_* are POPULATED on all 40 channels - uniform, no decision, no
# per-channel table needed for them (r6 spec SS A.4; the "0 ohm link now, diode later"
# plan in the recommendation doc SS3 was REJECTED - an R-prefix part would have shifted
# every resistor refdes above R3, and 0805 and SOD-323 cannot share a land anyway).
# Cflt_* is the decision, and it is a MEASURE-THEN-STUFF decision on every channel whose
# signal class is not yet metered. Class strings below are evidence, not guesses:
#   MEASURED  - a real meter reading exists (recommendation doc SS2, lane 22, 2026-07-18/21)
#   UNMEASURED- no reading exists; the machine-side prior is recorded
#   SPARE     - no signal assigned yet
R6_MEASURED = "MEASURED (lane 22, 2026-07-18/21)"
R6_UNMEASURED = "UNMEASURED"
R6_SPARE = "SPARE - unallocated"
# The measurement that decides Cflt, written once and referenced per row.
R6_MEASURE_PROC = (
    "At the machine end, OEM brain powered, THIS BOARD DISCONNECTED: meter the channel "
    "wire to machine common on DC volts AND AC volts through a full machine cycle, then "
    "confirm with a scope (a DMM cannot tell 60 Hz AC from a chopped DC train). "
    "DECIDE: (a) V_AC < 1 Vrms -> DC class, LEAVE Cflt UNFITTED whatever V_DC is - Dser "
    "+ Dclamp already cover DC up to 75 V V_RRM; (b) V_AC >= 5 Vrms (24 VAC ladder) AND "
    "this is a SLOW channel AND its release budget is >= 200 ms -> FIT Cflt 2.2uF and "
    "re-run FA-9 edge timing; (c) V_AC >= 5 Vrms on a FAST channel (SA/SB/SC/TA1/TA2/TB/"
    "DIELL_L/DIELL_R) -> DO NOT FIT. 60 Hz integration needs >=951 nF = 183 ms de-assert "
    "against a 1 ms edge budget, 92x DEBOUNCE_CAM_US and 122% of CAM_*_GRACE_MS; that "
    "channel is SURVIVABLE but NOT USABLE on AC and must be tapped at the switch or "
    "handled in firmware (r6 spec SS B.4). RECORD the reading either way - FA-15 requires "
    "the driven-24 VAC channel count N, and the board is budgeted for N = 0."
)
R6_CHANNEL_EVIDENCE: dict[str, tuple[str, str, str]] = {}
for _ch in [f"GS{i}" for i in range(1, 11)]:
    R6_CHANNEL_EVIDENCE[_ch] = (
        R6_MEASURED, "11 VDC dry",
        "DC dry contact, safe bare even pre-r6. Cflt UNFITTED. No measurement pending.")
R6_CHANNEL_EVIDENCE["BS"] = (
    R6_MEASURED, "11 VDC dry",
    "DC dry contact (bin/#9 switch). Cflt UNFITTED. No measurement pending.")
R6_CHANNEL_EVIDENCE["PBZ"] = (
    R6_MEASURED, "33 VDC (rectified-24 VAC class)",
    "THE canonical over-voltage channel: 27-28 V reverse at the rev-D Vw = 5-6 V rail "
    "vs a PC817 V_R max of 6 V (4.5-4.7x). Dser + Dclamp are what make it landable at "
    "all. Cflt UNFITTED (DC, not AC). FA-15 reverse proof is MANDATORY on this channel.")
for _ch in ("DIELL_L", "DIELL_R"):
    R6_CHANNEL_EVIDENCE[_ch] = (
        R6_MEASURED, "15.4-16 VDC at rest (DIELL board self-powers)",
        "Absolute-maximum VIOLATION pre-r6: 9.4-11 V reverse at the rev-D Vw = 5-6 V "
        "rail (1.6-1.8x the 6 V V_R). Permanent, survives brain removal. Cflt UNFITTED "
        "(DC). FA-15 reverse proof MANDATORY. NOTE: FAST channel - never fit >22 nF.")
for _ch in ("SA", "SB", "TA1", "TA2"):
    R6_CHANNEL_EVIDENCE[_ch] = (
        R6_UNMEASURED, "cam contact in the machine's 24 VAC relay ladder (prior, not "
        "reading) - proven by the ~21 ohm coil sneak paths that invalidated cold "
        "mapping twice",
        "MEASURE-THEN-STUFF. FAST channel: if it is driven 24 VAC the answer is still "
        "DO NOT FIT Cflt - r6 makes it electrically SURVIVABLE (28.9 Vpk vs 75 V V_RRM) "
        "but NOT functionally usable (120 debounced edges/s = 12 per CHATTER_WINDOW_MS "
        "vs CHATTER_MAX_CAM = 8 -> sustained chatter fault). Fallback per the metering "
        "guide: tap the cam AT THE SWITCH and skip C2A for that channel.")
for _ch in ("SC", "TB"):
    R6_CHANNEL_EVIDENCE[_ch] = (
        R6_UNMEASURED, "cam class, same 24 VAC ladder prior as SA/SB/TA1/TA2",
        "MEASURE-THEN-STUFF. FAST channel - see SA/SB/TA1/TA2: AC-driven means tap at "
        "the switch or change firmware, never a cap.")
R6_CHANNEL_EVIDENCE["FOUL"] = (
    R6_UNMEASURED, "Radaray foul-lamp wire - lamp circuits are a rectified/AC prior",
    "MEASURE-THEN-STUFF. SLOW channel, so 2.2uF IS available if it meters as 24 VAC - "
    "but foul is an EDGE input (on_foul); a 183 ms de-assert must be checked against the "
    "foul-detect timing before fitting. Default UNFITTED.")
R6_CHANNEL_EVIDENCE["GP"] = (
    R6_UNMEASURED, "gripper-protect, C2A-412DD - class open",
    "MEASURE-THEN-STUFF. SLOW channel. Default UNFITTED; fit 2.2uF only on a metered "
    "24 VAC reading with a >=200 ms release budget.")
R6_CHANNEL_EVIDENCE["PBC"] = (
    R6_UNMEASURED, "cycle pushbutton, C2A-21EE area (adjacent to the 33 VDC PBZ tap)",
    "MEASURE-THEN-STUFF. SLOW channel. Physically next to PBZ, so treat a 33 VDC-class "
    "reading as likely; that is a DC reading and still means Cflt UNFITTED.")
R6_CHANNEL_EVIDENCE["OS"] = (
    R6_UNMEASURED, "off-spot, C2A source not yet identified - future FSM use",
    "MEASURE-THEN-STUFF before landing. SLOW channel. Default UNFITTED.")
for _ch in ("TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR"):
    R6_CHANNEL_EVIDENCE[_ch] = (
        R6_UNMEASURED, "machine console / manual switch - dry-contact prior, unmetered",
        "MEASURE-THEN-STUFF before landing (these are future-FSM channels and unlanded "
        "on the first article). SLOW channel. Default UNFITTED.")
for _i in range(1, 12):
    R6_CHANNEL_EVIDENCE[f"AUX{_i}"] = (
        R6_SPARE, "no signal assigned",
        "Default UNFITTED. The reason Dclamp is POPULATED rather than DNP: nobody has "
        "chosen these channels' signal class yet, and a spare landed on an unknown wire "
        "is exactly the case a stuffing table loses across 32 lanes.")


# ---- hand-solder BOM (rev-C pattern, rev-D refs incl. J15/J16 + the U37->U45 shift) --
HAND_SOLDER_ROWS: list[dict[str, object]] = []   # r10: empty, see HAND_SOLDER_REFS

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


def parse_nets(path: Path) -> dict[str, list[tuple[str, str]]]:
    """net name -> [(refdes, pin), ...] from the SKiDL-emitted KiCad netlist.

    Added at r6: the connector/pin and the exact per-channel part identities in the
    stuffing table are DERIVED from the netlist, never hand-typed. A hand-typed
    stuffing table is a table that goes stale the next time a refdes moves.
    """
    text = path.read_text(encoding="utf-8")
    nets: dict[str, list[tuple[str, str]]] = {}
    for block in re.split(r"\(net\s*\n", text)[1:]:
        name = re.search(r'\(name "([^"]+)"\)', block)
        if not name:
            continue
        nodes = re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', block)
        nets[name.group(1)] = nodes
    return nets


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


def assert_r6_input_protection(net_parts, nets, placed, dnp_net, cpl_refs, jlc_refs):
    """Extend the BOM<->CPL<->netlist equality gate to the 120 r6 parts.

    Returns the per-channel stuffing rows (also written to CSV). Every check below
    fails CLOSED - this runs inside the export, so a violation means no package.
    """
    chans = sorted(p["tag"][len("Dser_"):] for p in net_parts.values()
                   if p["tag"].startswith("Dser_"))
    if len(chans) != EXPECTED_R6_DSER:
        raise SystemExit(f"r6: expected {EXPECTED_R6_DSER} Dser_* channels, got {len(chans)}")
    by_tag = {p["tag"]: ref for ref, p in net_parts.items()}
    for family, count in (("Dclamp_", EXPECTED_R6_DCLAMP), ("Cflt_", EXPECTED_R6_CFLT)):
        got = sum(1 for p in net_parts.values() if p["tag"].startswith(family))
        if got != count:
            raise SystemExit(f"r6: expected {count} {family}* parts, got {got}")

    rows, dser_refs, dclamp_refs, cflt_refs = [], [], [], []
    fast_caps = slow_caps = 0
    for ch in chans:
        try:
            dser = by_tag[f"Dser_{ch}"]
            dclamp = by_tag[f"Dclamp_{ch}"]
            cflt = by_tag[f"Cflt_{ch}"]
            opto = by_tag[f"OPTO_{ch}"]
            rin = by_tag[f"Rin_{ch}"]
            rpu = by_tag[f"Rpu_{ch}"]
        except KeyError as exc:
            raise SystemExit(f"r6: channel {ch} is missing part {exc}") from None
        is_fast = ch in R6_FAST_CHANNELS
        field_net = f"FIELD_{'FAST' if is_fast else 'SLOW'}_{ch}"
        logic_net = f"{'FAST' if is_fast else 'SLOW'}_{ch}"

        # --- topology: the three provisions are where the safety case says they are ---
        rin_nodes = set(nets.get(f"FIELD_RIN_{ch}", []))
        if rin_nodes != {(rin, "2"), (dser, "2")}:
            raise SystemExit(f"r6: FIELD_RIN_{ch} must be Rin.2 + Dser ANODE(2), got {sorted(rin_nodes)}")
        led_nodes = set(nets.get(f"FIELD_LED_{ch}", []))
        if led_nodes != {(dser, "1"), (dclamp, "1"), (opto, "1")}:
            raise SystemExit(f"r6: FIELD_LED_{ch} must be Dser.K + Dclamp.K + PC817 anode, "
                             f"got {sorted(led_nodes)}")
        field_nodes = set(nets.get(field_net, []))
        if (dclamp, "2") not in field_nodes or (opto, "2") not in field_nodes:
            raise SystemExit(f"r6: {field_net} must carry the Dclamp ANODE(2) + PC817 cathode, "
                             f"got {sorted(field_nodes)}")
        conn = sorted(f"{r}-{pin}" for r, pin in field_nodes if r.startswith("J"))
        if len(conn) != 1:
            raise SystemExit(f"r6: {field_net} must land on exactly one connector pin, got {conn}")
        logic_nodes = set(nets.get(logic_net, []))
        if (cflt, "1") not in logic_nodes or (rpu, "2") not in logic_nodes:
            raise SystemExit(f"r6: {logic_net} must carry Cflt.1 + Rpu.2, got {sorted(logic_nodes)}")
        if (cflt, "2") not in set(nets.get("GND", [])):
            raise SystemExit(f"r6: Cflt_{ch} pin 2 must return to GND (logic side)")

        # --- population: series NEVER DNP, clamp populated, cap always DNP -----------
        for ref, who in ((dser, "Dser"), (dclamp, "Dclamp")):
            p = net_parts[ref]
            if p["value"] != "1N4148" or not p["footprint"].endswith("D_SOD-323"):
                raise SystemExit(f"r6: {who}_{ch} ({ref}) must be 1N4148 / D_SOD-323, got {p}")
            if ref in dnp_net:
                raise SystemExit(
                    f"r6 STOP-SHIP: {who}_{ch} ({ref}) is DNP. A DNP series position leaves "
                    f"the channel OPEN-CIRCUIT; a DNP clamp reverts the LED reverse voltage "
                    f"to a leakage divider that FA-15 cannot distinguish from a good board.")
            for member, label in ((placed, "placed"), (cpl_refs, "CPL"), (jlc_refs, "JLC")):
                if ref not in member:
                    raise SystemExit(f"r6: {who}_{ch} ({ref}) missing from the {label} set")
        cap = net_parts[cflt]
        want = "10nF X7R DNP" if is_fast else "2.2uF X7R DNP"
        if cap["value"] != want:
            raise SystemExit(f"r6: Cflt_{ch} ({cflt}) must be {want!r}, got {cap['value']!r}")
        if cflt not in dnp_net or cflt in placed or cflt in cpl_refs or cflt in jlc_refs:
            raise SystemExit(f"r6: Cflt_{ch} ({cflt}) must be DNP and absent from CPL/JLC")
        key = (cap["value"], cap["footprint"].split(":", 1)[-1])
        if key not in FIELD_STUFF_LOCK:
            raise SystemExit(f"r6: no FIELD_STUFF_LOCK identity for {key} - a field-stuffed "
                             f"part with no locked MPN is a part the crew guesses at")
        fast_caps += is_fast
        slow_caps += not is_fast
        dser_refs.append(dser)
        dclamp_refs.append(dclamp)
        cflt_refs.append(cflt)

        klass, measured, decision = R6_CHANNEL_EVIDENCE[ch]
        lock = FIELD_STUFF_LOCK[key]
        rows.append({
            "Channel": ch,
            "Speed class": "FAST (RP2040)" if is_fast else "SLOW (MCP23017)",
            "Field connector pin": conn[0],
            "Opto": opto, "Rin (2k2)": rin, "Rpu (47k)": rpu,
            "Dser ref": dser, "Dser part": "1N4148WS SOD-323 (LCSC C118873)",
            "Dser stuffing": "POPULATE - ALWAYS (never DNP: DNP = open channel)",
            "Dclamp ref": dclamp, "Dclamp part": "1N4148WS SOD-323 (LCSC C118873)",
            "Dclamp stuffing": "POPULATE - ALWAYS (uniform; no per-channel decision)",
            "Cflt ref": cflt, "Cflt value": cap["value"].replace(" DNP", ""),
            "Cflt MFR Part #": lock["mpn"], "Cflt LCSC Part #": lock["lcsc"],
            "Cflt stuffing": "DNP - DO NOT FIT unless the measurement below says so",
            "Signal-class evidence": klass,
            "Measured / prior": measured,
            "Decision + measurement that decides Cflt": decision,
            "Measurement procedure": (R6_MEASURE_PROC if klass != R6_MEASURED
                                      else "Already metered - no measurement pending."),
        })

    if len(set(dser_refs)) != EXPECTED_R6_DSER or len(set(dclamp_refs)) != EXPECTED_R6_DCLAMP:
        raise SystemExit("r6: Dser/Dclamp refdes are not unique per channel")
    if set(dser_refs) & set(dclamp_refs):
        raise SystemExit("r6: a single diode is serving as BOTH series block and clamp")
    if len(set(cflt_refs)) != EXPECTED_R6_CFLT:
        raise SystemExit("r6: Cflt refdes are not unique per channel")
    if (fast_caps, slow_caps) != (EXPECTED_R6_CFLT_FAST, EXPECTED_R6_CFLT_SLOW):
        raise SystemExit(f"r6: Cflt fast/slow split {fast_caps}/{slow_caps} != pinned "
                         f"{EXPECTED_R6_CFLT_FAST}/{EXPECTED_R6_CFLT_SLOW}")
    # No r6 part may touch the safety rail or the wetting rail (standing prohibition X3
    # / spec SS A.5). The audit proves this on the BOARD; assert it on the shipped netlist.
    r6_refs = set(dser_refs) | set(dclamp_refs) | set(cflt_refs)
    for netname in ("FIELD_WET_V", "RELAY_ENABLE_RAIL", "RAIL_GATE",
                    "SAFE_STOP_RETURN", "SAFE_TBSC_RETURN"):
        if netname not in nets:
            # A renamed net would silently DISARM this guard - fail instead.
            raise SystemExit(f"r6 guard cannot run: net {netname} is absent from the netlist")
        touching = sorted({r for r, _ in nets[netname]} & r6_refs)
        if touching:
            raise SystemExit(f"r6 STOP-SHIP: {touching} land on {netname}")
    rows.sort(key=lambda r: (r["Speed class"], r["Channel"]))
    return rows


def zip_paths(zip_path: Path, files: list[Path], base: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            z.write(path, path.relative_to(base).as_posix())


def load_firmware_release_identity(expected_board_revision: str) -> dict[str, object]:
    """Load and hash-check the one production image named by the release manifest."""
    if not FW_RELEASE_MANIFEST.exists():
        raise SystemExit(f"Missing firmware release manifest: {FW_RELEASE_MANIFEST}")
    data = json.loads(FW_RELEASE_MANIFEST.read_text(encoding="utf-8"))
    release_images = [
        image for image in data.get("images", [])
        if image.get("variant") == "release" and not image.get("bench_only", False)
    ]
    if len(release_images) != 1:
        raise SystemExit(
            "Firmware release identity gate failed: expected exactly one non-bench "
            f"release image, got {len(release_images)}")
    release = release_images[0]
    identity = release.get("identity", {})
    image = release.get("image", {})
    build = str(identity.get("id.build", ""))
    cfg = str(identity.get("id.cfg", ""))
    sha = str(image.get("sha256", "")).lower()
    image_path = FW_RELEASE_MANIFEST.parent / str(image.get("file", ""))
    if not build or not cfg or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit("Firmware release manifest has incomplete build/cfg/image identity")
    if not image_path.is_file() or sha256(image_path) != sha:
        raise SystemExit(
            f"Firmware release image missing or hash mismatch: {image_path}")
    policy = data.get("deployment_identity", {})
    if policy.get("build_allowlist") != [build] or policy.get("config_allowlist") != [cfg]:
        raise SystemExit(
            "Firmware release manifest allowlists do not exactly match the production image")
    supported_boards = data.get("supported_board_revisions")
    if supported_boards != [expected_board_revision]:
        raise SystemExit(
            "Firmware release board policy must contain exactly the exported revision: "
            f"expected {[expected_board_revision]!r}, got {supported_boards!r}")
    expected_qualified = [f"{expected_board_revision}|{build}|{cfg}"]
    qualified_releases = data.get("qualified_releases")
    if qualified_releases != expected_qualified:
        raise SystemExit(
            "Firmware release policy must bind the exact board/build/config tuple: "
            f"expected {expected_qualified!r}, got {qualified_releases!r}")
    return {
        "version": str(data.get("firmware_version", "")),
        "build": build,
        "cfg": cfg,
        "sha256": sha,
        "manifest_sha256": sha256(FW_RELEASE_MANIFEST),
        "supported_board_revisions": supported_boards,
        "qualified_releases": qualified_releases,
    }


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
    fw_release = load_firmware_release_identity(f"rev{rev}")

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
    nets = parse_nets(NETLIST_PATH)
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

    # ---- r6 per-channel input-protection equality (extends the H6 gate) -------------
    # NOTE the ordering: jlc_refs is not built yet, so pass the set this gate needs -
    # every Dser/Dclamp is placed and NOT hand-solder, so placed - HAND_SOLDER_REFS is
    # exactly the JLC set and is computed identically below.
    r6_rows = assert_r6_input_protection(
        net_parts, nets, placed, dnp_net, cpl_refs, placed - HAND_SOLDER_REFS)

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
        # r6: the identity columns are NEW. A DNP row used to say "do not fit" and
        # nothing else; for the 40 field-stuffable Cflt lands that left the buy
        # decision undocumented. Rows whose part is not yet chosen carry an explicit
        # "(identity awaits ...)" marker rather than an empty cell.
        w.writerow(["Designator", "Value", "Footprint", "Manufacturer", "MFR Part #",
                    "LCSC Part #", "Reason"])
        for ref in sorted(dnp_net, key=natural_ref_key):
            p = net_parts[ref]
            lock = FIELD_STUFF_LOCK.get((p["value"], p["footprint"].split(":", 1)[-1]))
            if p["tag"] == "JP_J16_3V3":
                reason = ("Default-OPEN solder link (R2-4): J16 pin 5 ships NC; bridge "
                          "only for a verified 3.3V module - no part is ever fitted")
            elif p["tag"].startswith("Cflt_"):
                reason = ("DNP by design (r6): logic-side AC-integration / de-glitch cap. "
                          "Fit ONLY on a channel MEASURED to carry a 60 Hz pulse train. "
                          "2.2uF max on the MCP23017 slow channels (183 ms de-assert, and "
                          "no slow channel may have a release budget tighter than 200 ms); "
                          "NEVER exceed 22 nF on the RP2040 fast channels GP6-GP13 (1 ms "
                          "edge budget). NOTE: 60 Hz integration is NOT available on the "
                          "fast cam channels SA/SB/TA1/TA2 - see r6 spec SS B.4, that case "
                          "needs a firmware change, not a cap.")
            elif p["tag"].endswith("_M1") or p["tag"] in M1_OPTIONAL_TAGS:
                reason = "M1 optional channel (never metered; populate only after runbook 3.6)"
            else:
                reason = "DNP (snubber/MOV sizing awaits the powered characterization session - G7 item 7)"
            if lock:
                mfr, mpn, lcsc = lock["manufacturer"], lock["mpn"], lock["lcsc"]
                reason = f"{reason} FIELD-STUFF LOCK: {lock['locked_spec']}. {lock['note']}"
            elif p["tag"] == "JP_J16_3V3":
                mfr = mpn = lcsc = "(no part - solder bridge)"
            else:
                mfr = mpn = lcsc = "(identity awaits G7 item 7 characterization)"
            w.writerow([ref, p["value"], p["footprint"].split(":", 1)[-1],
                        mfr, mpn, lcsc, reason])

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
    # R2-15 hard lock, r8 re-pin: the 10M gate pulldowns are R135/R138/R141 on
    # the pinned C2933281 identity (MATCH-AT-UPLOAD is dead; C26108 retired OOS).
    r10m_line = by_lcsc.get("C2933281")
    if (not r10m_line or str(r10m_line["MFR Part #"]) != "FRC0805F1005TS"
            or str(r10m_line["Designator"]) != "R135,R138,R141"):
        raise SystemExit("R2-15/r8 lock failed: R135/R138/R141 must map exactly to FOJAN "
                         f"FRC0805F1005TS LCSC C2933281 (got {r10m_line})")
    # Rev-D input-margin hardening: exactly the 40 optocoupler collector
    # pull-ups, and no unrelated resistor, must ride the dedicated 47k line.
    r47k_line = by_lcsc.get("C17713")
    expected_rpu_refs = ",".join(f"R{n}" for n in range(4, 83, 2))
    if (not r47k_line or str(r47k_line["MFR Part #"]) != "0805W8F4702T5E"
            or str(r47k_line["Manufacturer"]) != "UNI-ROYAL"
            or str(r47k_line["Designator"]) != expected_rpu_refs):
        raise SystemExit(
            "Rev-D input pull-up lock failed: R4,R6,...,R82 must map exactly "
            f"to UNI-ROYAL 47k 0805W8F4702T5E LCSC C17713 (got {r47k_line})")
    # r6 hard lock: the 80 new input-protection diodes must ride the EXISTING onsemi
    # 1N4148WS line and nothing else. If a second diode line ever appears for them, the
    # "zero new assembled part classes" claim (and EXPECTED_JLC_LINES == 27) is false.
    d4148_line = by_lcsc.get("C118873")
    # D13 (Dfly_M1) is a 1N4148 too but ships DNP with the M1 channel, so it is NOT on
    # the assembled line - compare against the PLACED 1N4148 set, not every 1N4148.
    d4148_refs = sorted((r for r, p in net_parts.items()
                         if p["value"] == "1N4148" and r in placed),
                        key=natural_ref_key)
    if (not d4148_line or str(d4148_line["MFR Part #"]) != "1N4148WS"
            or str(d4148_line["Manufacturer"]) != "onsemi"
            or "SOD-323" not in str(d4148_line["Comment"])
            or int(d4148_line["Quantity"]) != EXPECTED_1N4148_QTY
            or str(d4148_line["Designator"]) != ",".join(d4148_refs)):
        raise SystemExit(
            f"r6 lock failed: all {EXPECTED_1N4148_QTY} 1N4148 parts (8 pre-r6 + 80 r6 "
            f"Dser/Dclamp) must map to ONE onsemi 1N4148WS SOD-323 line, LCSC C118873 "
            f"(got {d4148_line})")
    r6_diode_refs = {row["Dser ref"] for row in r6_rows} | {row["Dclamp ref"] for row in r6_rows}
    missing_r6 = sorted(r6_diode_refs - set(d4148_refs), key=natural_ref_key)
    if missing_r6 or len(r6_diode_refs) != EXPECTED_R6_DSER + EXPECTED_R6_DCLAMP:
        raise SystemExit(f"r6 lock failed: {len(r6_diode_refs)} r6 diodes, missing from the "
                         f"C118873 line: {missing_r6}")
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

    # ---- r6 per-channel stuffing BOM (new at r6) ------------------------------------
    # This is the crew-facing answer to "what goes on channel <n>": all 40 get
    # Dser + Dclamp POPULATED (no decision), and the only decision left is the DNP
    # Cflt, which is a MEASURE-THEN-STUFF call with the deciding measurement in the row.
    stuff_fields = ["Channel", "Speed class", "Field connector pin", "Opto",
                    "Rin (2k2)", "Rpu (47k)",
                    "Dser ref", "Dser part", "Dser stuffing",
                    "Dclamp ref", "Dclamp part", "Dclamp stuffing",
                    "Cflt ref", "Cflt value", "Cflt MFR Part #", "Cflt LCSC Part #",
                    "Cflt stuffing", "Signal-class evidence", "Measured / prior",
                    "Decision + measurement that decides Cflt", "Measurement procedure"]
    write_csv(assembly_dir / f"{stem}-r6-channel-stuffing.csv", stuff_fields, r6_rows)
    write_csv(DOCS_R6_STUFFING, stuff_fields, r6_rows)   # tracked doc copy
    if len(r6_rows) != EXPECTED_R6_DSER:
        raise SystemExit(f"r6 stuffing table has {len(r6_rows)} rows, expected {EXPECTED_R6_DSER}")

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
        # DERIVED from the pinned constants, never a hardcoded literal: the r6
        # spin moved all five and a fixed string silently shipped the pre-r6
        # counts inside a 391-part package, contradicting manifest.json in the
        # same directory.
        f"- BOM<->CPL<->netlist equality asserted: {EXPECTED_NETLIST_PARTS} parts / "
        f"{EXPECTED_DNP} DNP / {EXPECTED_PLACED} placed /",
        f"  {EXPECTED_JLC_PLACED} JLC-placed / {EXPECTED_HAND_SOLDER} hand-solder; "
        "every placed refdes present in all three.",
        "- D_PROT hard lock: D17 = MDD SS34, LCSC C8678, SMA/DO-214AC (FR-3); no SS14",
        "  anywhere.",
        f"- r6 input protection asserted PER CHANNEL, not by totals: {EXPECTED_R6_DSER} x Dser_*",
        f"  + {EXPECTED_R6_DCLAMP} x Dclamp_* (1N4148WS SOD-323, LCSC C118873, onsemi -",
        f"  ALL {EXPECTED_1N4148_QTY} 1N4148 on ONE line, zero new assembled part classes)",
        f"  and {EXPECTED_R6_CFLT} x Cflt_* (ALL DNP: {EXPECTED_R6_CFLT_FAST} x 10nF fast /",
        f"  {EXPECTED_R6_CFLT_SLOW} x 2.2uF slow). Each channel's FIELD_RIN_<n> = Rin.2 +",
        "  Dser ANODE, FIELD_LED_<n> = Dser.K + Dclamp.K + PC817 anode, field pin = Dclamp",
        "  ANODE + PC817 cathode. A DNP Dser is STOP-SHIP (open channel); a DNP/absent",
        "  Dclamp is invisible until FA-15. No r6 part touches FIELD_WET_V, RELAY_ENABLE_",
        "  RAIL, RAIL_GATE, SAFE_STOP_RETURN or SAFE_TBSC_RETURN.",
        "- FIELD-STUFF locks (parts WE buy and fit, never JLC): Cflt 2.2uF = Samsung",
        "  CL21B225KAFNNNE / LCSC C19110 (FR-17; 1uF C28323 REJECTED - 749 nF effective",
        "  < the 951 nF 60 Hz floor); Cflt 10nF = TORCH C0805B103K500NT / LCSC C17702767",
        "  (FR-18). Identities travel in assembly/*-dnp-excluded.csv next to the reason.",
        f"- Per-channel stuffing table: assembly/{stem}-r6-channel-stuffing.csv (tracked",
        "  copy docs/phase8_revD_r6_channel_stuffing.csv). ALL 40 channels get Dser +",
        "  Dclamp POPULATED - uniform, no per-channel decision. The ONLY decision is the",
        "  DNP Cflt, and it is MEASURE-THEN-STUFF: PBZ (33 VDC), DIELL_L/R (15.4-16 V)",
        "  are metered DC and stay UNFITTED; SA/SB/SC/TA1/TA2/TB (cams), FOUL, GP, PBC,",
        "  OS and the manual/AUX channels are UNMEASURED and carry the deciding",
        "  measurement in their row. A 24 VAC FAST channel is never a cap fix.",
        "- Round-2 locks (2026-07-21): Q17-Q20 = onsemi 2N7002LT1G C16338 (R2-3);",
        "  R135/R138/R141 = FOJAN 10M FRC0805F1005TS C2933281 (R2-15 identity lock,",
        "  RE-PINNED at r8 2026-07-26: the former UNI-ROYAL 0805W8F1005T5E / C26108",
        "  went permanently OOS); U46 = TCA4307DGKR C880333;",
        "  U47 = Semtech SRV05-4.TCT C13612; F1 = Littelfuse 1206L020YR C207035.",
        "  JP1 (J16 3.3V solder link) is DNP: default-OPEN, no part fitted.",
        "- Rev-D input-margin hardening (2026-07-23): exactly R4,R6,...,R82 = 47k,",
        "  UNI-ROYAL 0805W8F4702T5E / LCSC C17713; unrelated 10k networks unchanged.",
        "  Every populated PC817 channel still requires FA-9 at loaded-min FIELD_WET",
        "  and temperature: C5692981 lacks a guaranteed CTR minimum at this board's",
        "  operating IF. r6 (2026-07-25) INSERTED A SERIES BLOCKING DIODE in every",
        "  channel, so the FA-9 operating point is NO LONGER ~1.7mA: it is 1.34mA at",
        "  Vw=5.0V and ~1.12mA at the FA-9 step-3 loaded minimum (TP4 ~4.5V). Use",
        "  those numbers, not the pre-r6 1.7mA. FA-9's <=100us edge criterion applies",
        "  only with every Cflt_* UNFITTED (they ship DNP); a channel that later takes",
        "  a Cflt is re-qualified against the debounce budget instead - see FA-9 and",
        "  the DNP CSV reason text.",
        "  BINDING CONFIGURATION GATE: production RP2040 GP6-GP13 internal pulls must",
        "  be disabled (PUE=0, PDE=0), and U1/U2 MCP23017 GPPUA/GPPUB must command",
        "  and read back 0x00. An enabled internal pull invalidates the 47k-only",
        "  sink/leakage/RC arithmetic and is STOP-SHIP. R_TAPPU_* 10k diagnostic-tap",
        "  drain pull-ups are separate networks and remain intentionally unchanged.",
        f"  Production firmware identity: {fw_release['version']};",
        f"  build={fw_release['build']}; cfg={fw_release['cfg']};",
        f"  release UF2 SHA-256={fw_release['sha256']}. Verify the release manifest",
        f"  SHA-256={fw_release['manifest_sha256']} before flash; filename/version alone",
        "  is not proof. The manifest must contain supported_board_revisions="
        f"{json.dumps(fw_release['supported_board_revisions'])}.",
        "  Provision only qualified_releases="
        f"{json.dumps(fw_release['qualified_releases'])};",
        "  independent build/config allowlists must not authorize a cross-product.",
        "  This exact bundle is Rev-D only: never flash Rev-B/Rev-C, and never deploy",
        "  wsl_phase8b_rp2040_FI1.uf2. FA-9/FA-11 require live pull-register confirmation.",
        "",
        "Uploads:",
        f"- {stem}-gerber-drill.zip  -> JLC PCB order (4-layer FR-4 1.6mm, 1oz/0.5oz,",
        "  ENIG, confirm preview reads 250 x 240 mm - REV-D IS 240 mm TALL).",
        f"- assembly/{stem}-jlc-standard-pcba-upload-bom.csv + -cpl.csv -> Standard PCBA.",
        "",
        "Hand-solder after JLC: NONE. r10 WAVE 2 took it to ZERO.",
        "  Every one of the 323 placed parts is JLC-placed. The nine that were",
        "  hand-solder at r9 - A1, J1, J3, J4, J5, J13, J15, J16, U45 - now carry",
        "  pinned C-numbers, each verified against its own JLC part-detail page.",
        "  A1 = C7203002, confirmed IN WRITING by JLC 2026-07-27 as order code",
        "  SC0915: the BARE RP2040 module. NOT SC0917 (Pico H, headers fitted) and",
        "  NOT an RP2350 Pico 2 - the firmware is RP2040-only. Require a silkscreen",
        "  photo before payment.",
        "",
        "  PROCUREMENT IS SEPARATE FROM THIS BOM. Several lines show 0 stock in",
        "  JLC's library today. The route per part - JLC stock / Global Sourcing /",
        "  consigned - is selected at ORDER time and does not change these files.",
        "  Per JLC 2026-07-27, consigned and JLC parts may coexist on one order for",
        "  DIFFERENT parts, but never for the SAME part - so each line is all-one-way.",
        "",
        "r9 WAVE 1: J2, J6-J11 and J14 are now JLC-PLACED (8 placements/board, 19 THT",
        "  joints/board, 646 fleet-wide). All three are library-native Phoenix Contact,",
        "  marked Wave Soldering / Economic and Standard - the SAME through-hole path",
        "  this board already uses for its 40 PC817 optos and 6 G5LE relays. No service",
        "  tier changes: JLC offers only Economic and Standard, and this order is already",
        "  Standard. Verified 2026-07-26 by JLC part-detail page, not by MPN search",
        "  (searching JLC by bare numeric Phoenix MPN returns FALSE NEGATIVES - e.g.",
        "  searchTxt=1843622 gives '0 Found' while partdetail/C480549 shows it in stock):",
        "    J2      = C480520  Phoenix 1715734  MKDS 1,5/3-5,08   1,173 stock",
        "    J6-J11  = C480516  Phoenix 1715721  MKDS 1,5/2-5,08   1,591 stock",
        "              (NOT C5183929 - same MPN, only ~239 pcs vs a 204 fleet need)",
        "    J14     = C480549  Phoenix 1843622  MCV 1,5/4-G-3,5   2,481 stock",
        "  J14 is NOT one of the FA-8 coded pairs, so no coding rib is cut on it and",
        "  JLC placing it cannot disturb the J3/J15 + J13/J16 keying scheme.",
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
        "input_pullup_lock": (
            "R4,R6,...,R82 = 40 x UNI-ROYAL 47k 0805W8F4702T5E, LCSC C17713; "
            "all unrelated 10k networks unchanged"
        ),
        "r6_input_protection_lock": (
            f"{EXPECTED_R6_DSER} Dser_* + {EXPECTED_R6_DCLAMP} Dclamp_* = 1N4148WS "
            f"SOD-323, onsemi, LCSC C118873, ALL POPULATED (a DNP series position opens "
            f"the channel); {EXPECTED_1N4148_QTY} 1N4148 total on one JLC line. "
            f"{EXPECTED_R6_CFLT} Cflt_* ALL DNP "
            f"({EXPECTED_R6_CFLT_FAST} x 10nF fast / {EXPECTED_R6_CFLT_SLOW} x 2.2uF slow)"
        ),
        "r6_field_stuff_lock": (
            "Cflt 2.2uF = Samsung CL21B225KAFNNNE / LCSC C19110 (FR-17); "
            "Cflt 10nF = TORCH C0805B103K500NT / LCSC C17702767 (FR-18); "
            "fitted by us, never by JLC - see assembly/*-r6-channel-stuffing.csv"
        ),
        "input_bias_runtime_gate": (
            "production RP2040 GP6-GP13 PUE=0/PDE=0; U1/U2 MCP23017 "
            "GPPUA=0x00/GPPUB=0x00 with readback; R_TAPPU_* 10k is separate"
        ),
        "production_firmware": fw_release,
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
