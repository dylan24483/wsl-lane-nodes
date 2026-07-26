#!/usr/bin/env python3
"""Generate the rev-D first-article / bench document pack FROM the design artifacts (Codex M6).

  py -3 scripts/generate_first_article_docs_revD.py

Why this exists: the AUX4-11 opto-bank insertion shifted 46 refdes rev-C -> rev-D
(ISO_WET U37->U45, U_WDOG U36->U44, the watchdog/rail/lamp/snubber R families). Every
rev-C bench artifact (TP map, board-1 bench packet, solder/bring-up guides) therefore
names WRONG parts on a rev-D board - a technician probing "U37" from the rev-C TP map
lands on the AUX5 optocoupler, not the isolated wetting supply, during a procedure that
includes powered safety-rail fault injection. Codex M6 requires the rev-D docs to be
REGENERATED from the netlist + board, never hand-translated from rev-C notes.

Inputs (read-only):
  kicad/wsl-phase8b-revD.net                 (refdes/value/footprint/tag)
  kicad/revD/wsl-phase8b-revD.kicad_pcb      (positions, sides, TP pads)
  kicad/revD/netlist_diff_revC_to_revD.txt   (REFDES_SHIFT authoritative cross-reference)

Outputs (regenerated in place - these are DERIVED docs, re-run after any netlist or
placement change):
  docs/phase8_revD_first_article_pack.md
  docs/phase8_revD_first_article_refdes_map.csv
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NETLIST = ROOT / "kicad" / "wsl-phase8b-revD.net"
BOARD = ROOT / "kicad" / "revD" / "wsl-phase8b-revD.kicad_pcb"
DIFF = ROOT / "kicad" / "revD" / "netlist_diff_revC_to_revD.txt"
OUT_MD = ROOT / "docs" / "phase8_revD_first_article_pack.md"
OUT_CSV = ROOT / "docs" / "phase8_revD_first_article_refdes_map.csv"

M1_OPTIONAL_TAGS = {"K_M1", "MOV_M1", "Csnub_M1", "Dfly_M1", "Rb_M1", "Rpd_M1", "Rsnub_M1"}
# r6 (2026-07-25): 28 + 40 Cflt_* logic-side filter caps (C17-C56). Dser_*/
# Dclamp_* are POPULATED, so they do not enter this count. Keep in LOCKSTEP
# with export_fab_revD.EXPECTED_DNP.
EXPECTED_DNP = 68


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def natural_ref_key(ref: str):
    prefix = "".join(ch for ch in ref if not ch.isdigit())
    digits = "".join(ch for ch in ref if ch.isdigit())
    return prefix, int(digits or 0), ref


def parse_netlist() -> dict[str, dict[str, str]]:
    text = NETLIST.read_text(encoding="utf-8")
    parts = {}
    for block in re.split(r"\(comp\s*\n", text)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', block).group(1)
        value = re.search(r'\(value "([^"]+)"\)', block).group(1)
        fp = re.search(r'\(footprint "([^"]+)"\)', block)
        tag = re.search(r'\(name "SKiDL Tag"\) "([^"]+)"', block)
        parts[ref] = {
            "value": value,
            "footprint": (fp.group(1) if fp else "").split(":", 1)[-1],
            "tag": tag.group(1) if tag else ref,
        }
    return parts


def parse_board() -> dict[str, dict[str, object]]:
    """ref -> {x, y, rot, side, net_of_pad1(for TPs)} from the routed board text.

    Net format note (Codex round-2 R2-5, 2026-07-21): KiCad 10 writes pad nets
    as `(net "NAME")` — the old `(net <int> "NAME")` regex matched NOTHING in
    this board file, so every TP row in the pack rendered with a BLANK net and
    a technician had no way to know what a pad probes. Both spellings are
    accepted now, and main() FAILS generation outright if any TP still
    resolves to a blank net (silent blanks are exactly the M6 hazard class).
    """
    text = BOARD.read_text(encoding="utf-8")
    out = {}
    for block in text.split("\n\t(footprint ")[1:]:
        mref = re.search(r'\(property "Reference"\s+"([^"]+)"', block)
        if not mref:
            continue
        ref = mref.group(1)
        mat = re.search(r"\(at (-?[\d.]+) (-?[\d.]+)(?: (-?[\d.]+))?\)", block)
        x, y = float(mat.group(1)), float(mat.group(2))
        rot = float(mat.group(3) or 0)
        mlayer = re.search(r'\(layer "([^"]+)"\)', block)
        side = "top" if (mlayer and mlayer.group(1) == "F.Cu") else "bottom"
        mnet = re.search(r'\(net (?:\d+\s+)?"([^"]+)"\)', block)
        out[ref] = {"x": x, "y": y, "rot": rot, "side": side,
                    "pad_net": mnet.group(1) if mnet else ""}
    return out


def firmware_version() -> str:
    """FW_VERSION from firmware/rp2040/config.h — the pack's firmware
    references must agree with the shippable image (R2-5 version-output
    agreement; the pack said 'v1.2.0' while config.h was already v1.2.1)."""
    cfg = ROOT / "firmware" / "rp2040" / "config.h"
    m = re.search(r'#define\s+FW_VERSION\s+"([^"]+)"',
                  cfg.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"FW_VERSION not found in {cfg}")
    return m.group(1)


def firmware_release_manifest() -> dict[str, str]:
    """Verify and extract the exact release/FI-1 identities used by FA-11."""
    fw_dir = ROOT / "firmware" / "rp2040"
    verifier = fw_dir / "release_provenance.py"
    manifest_path = fw_dir / "release" / "firmware_manifest.json"
    checked = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "verify-manifest",
            "--source-dir",
            str(fw_dir),
            "--manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
    )
    if checked.returncode:
        detail = (checked.stderr or checked.stdout).strip()
        raise SystemExit(f"firmware release manifest failed verification: {detail}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = {item["variant"]: item for item in manifest["images"]}
    release = images["release"]
    fi1 = images["fi1"]
    return {
        "manifest_sha256": sha256(manifest_path),
        "release_build": release["identity"]["id.build"],
        "release_cfg": release["identity"]["id.cfg"],
        "release_sha256": release["image"]["sha256"],
        "fi1_build": fi1["identity"]["id.build"],
        "fi1_sha256": fi1["image"]["sha256"],
    }


def band_of(x: float) -> str:
    if x < 76.8:
        return "FIELD"
    if x <= 80.0:
        return "GUTTER-F/L"
    if x < 181.0:
        return "LOGIC"
    if x <= 184.2:
        return "GUTTER-L/M"
    return "MACHINE"


def parse_shifts() -> list[tuple[str, str, str]]:
    shifts = []
    for line in DIFF.read_text(encoding="utf-8").splitlines():
        if line.startswith("REFDES_SHIFT\t"):
            _, tag, old, new = line.split("\t")
            shifts.append((tag, old, new))
    return shifts


def is_dnp(tag: str, value: str) -> bool:
    return tag.endswith("_M1") or tag in M1_OPTIONAL_TAGS or "DNP" in value.upper()


def parse_nets() -> dict[str, list[tuple[str, str]]]:
    """net name -> [(refdes, pin), ...] from the netlist (r6 census source)."""
    text = NETLIST.read_text(encoding="utf-8")
    nets: dict[str, list[tuple[str, str]]] = {}
    for block in re.split(r"\(net\s*\n", text)[1:]:
        name = re.search(r'\(name "([^"]+)"\)', block)
        if not name:
            continue
        nets[name.group(1)] = re.findall(
            r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', block)
    return nets


# r6 fast channels (RP2040 GP6-GP13) - mirror of generate_kicad_netlist_revD.FAST_INPUTS.
R6_FAST_CHANNELS = ("SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R")


def r6_census(parts, nets) -> list[list[str]]:
    """Per-channel FA-16 census: connector pin + the three r6 refdes per channel.

    FAIL-ON-BLANK (same hazard class as the R2-5 blank-net TP table): a census row
    with a missing refdes or a blank connector pin sends a technician probing the
    wrong pad on a 120-placement change. Refuse to generate the pack instead.
    """
    by_tag = {p["tag"]: ref for ref, p in parts.items()}
    channels = sorted(t[len("Dser_"):] for t in by_tag if t.startswith("Dser_"))
    if len(channels) != 40:
        raise SystemExit(f"r6 census: expected 40 Dser_* channels, got {len(channels)}")
    rows = []
    for ch in channels:
        fast = ch in R6_FAST_CHANNELS
        field_net = f"FIELD_{'FAST' if fast else 'SLOW'}_{ch}"
        cells = {
            "opto": by_tag.get(f"OPTO_{ch}", ""),
            "rin": by_tag.get(f"Rin_{ch}", ""),
            "dser": by_tag.get(f"Dser_{ch}", ""),
            "dclamp": by_tag.get(f"Dclamp_{ch}", ""),
            "cflt": by_tag.get(f"Cflt_{ch}", ""),
        }
        pins = sorted(f"{r}-{pin}" for r, pin in nets.get(field_net, [])
                      if r.startswith("J"))
        blanks = [k for k, v in cells.items() if not v]
        if blanks or len(pins) != 1:
            raise SystemExit(
                f"r6 census FAILED for channel {ch}: missing {blanks}, "
                f"connector pins {pins} (expected exactly one). A blank census row "
                f"must never ship - fix the netlist/tag lookup.")
        cval = parts[cells["cflt"]]["value"].replace(" DNP", "")
        rows.append([ch, "FAST" if fast else "SLOW", pins[0], cells["opto"],
                     cells["rin"], cells["dser"], cells["dclamp"],
                     f"{cells['cflt']} ({cval}, DNP)"])
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def main() -> int:
    parts = parse_netlist()
    nets = parse_nets()
    board = parse_board()
    shifts = parse_shifts()
    dnp_refs = {
        ref for ref, part in parts.items()
        if is_dnp(part["tag"], part["value"])
    }

    missing = [r for r in parts if r not in board]
    if missing:
        raise SystemExit(f"Netlist refs missing from board: {missing}")
    if len(shifts) != 46:
        raise SystemExit(f"Expected 46 REFDES_SHIFT rows, got {len(shifts)}")
    if len(dnp_refs) != EXPECTED_DNP:
        raise SystemExit(
            f"Expected exactly {EXPECTED_DNP} DNP refs, got {len(dnp_refs)}: "
            f"{sorted(dnp_refs, key=natural_ref_key)}"
        )
    if "JP1" not in dnp_refs:
        raise SystemExit("JP1 must be DNP: the J16 3.3 V solder link ships open")

    # ---- CSV: full refdes map -------------------------------------------------------
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Ref", "Function (SKiDL tag)", "Value", "Footprint",
                    "X mm", "Y mm", "Rot", "Side", "Band", "DNP"])
        for ref in sorted(parts, key=natural_ref_key):
            p, b = parts[ref], board[ref]
            w.writerow([ref, p["tag"], p["value"], p["footprint"],
                        f"{b['x']:.2f}", f"{b['y']:.2f}", f"{b['rot']:.0f}",
                        b["side"], band_of(b["x"]),
                        "DNP" if is_dnp(p["tag"], p["value"]) else ""])

    # ---- helper for grouped tables --------------------------------------------------
    def rows_for(pred) -> list[list[str]]:
        rows = []
        for ref in sorted(parts, key=natural_ref_key):
            p, b = parts[ref], board[ref]
            if pred(ref, p):
                rows.append([ref, p["tag"], p["value"],
                             f"({b['x']:.1f}, {b['y']:.1f})", band_of(b["x"]),
                             "DNP" if is_dnp(p["tag"], p["value"]) else ""])
        return rows

    hdr = ["Ref", "Function (tag)", "Value", "Location (x, y) mm", "Band", "DNP"]

    tp_rows = []
    blank_tps = []
    for ref in sorted((r for r in board if r.startswith("TP")), key=natural_ref_key):
        b = board[ref]
        if not str(b["pad_net"]).strip():
            blank_tps.append(ref)
        tp_rows.append([ref, b["pad_net"], f"({b['x']:.0f}, {b['y']:.0f})", band_of(b["x"])])
    if blank_tps:
        # R2-5: a TP row without a net name is a probing hazard, not a
        # cosmetic gap — refuse to generate the pack.
        raise SystemExit(f"TP net resolution FAILED for {blank_tps} — the "
                         f"board pad-net parser found no net (format drift?). "
                         f"Fix parse_board(); a blank-net TP table must never "
                         f"ship.")

    shift_rows = [[tag, old, new,
                   parts.get(new, {}).get("value", "?"),
                   f"({board[new]['x']:.1f}, {board[new]['y']:.1f})" if new in board else "?"]
                  for tag, old, new in sorted(shifts)]

    gpb_rows = []
    for i in range(4, 12):
        oref = next(r for r, p in parts.items() if p["tag"] == f"OPTO_AUX{i}")
        b = board[oref]
        gpb_rows.append([f"J15-{i - 3}", f"AUX{i}", f"GPB{i - 4}", oref,
                         f"({b['x']:.1f}, {b['y']:.1f})"])

    r6_rows = r6_census(parts, nets)

    today = date.today().isoformat()
    net_hash = sha256(NETLIST)
    brd_hash = sha256(BOARD)
    fw_ver = firmware_version()   # R2-5: pack must agree with config.h
    fw_release = firmware_release_manifest()

    doc = f"""# Phase 8 Rev-D — First-Article / Bench Pack (GENERATED — do not hand-edit)

> **GENERATED {today} by `scripts/generate_first_article_docs_revD.py` from the rev-D
> netlist + routed board. Re-run the script after ANY netlist or placement change —
> hand edits will be overwritten.** This pack is the Codex-M6 remediation artifact:
> the rev-C bench documents (TP map, board-1 bench packet, solder/bring-up guides)
> name WRONG parts on a rev-D board (46 refdes shifted) and MUST NOT be used here.
>
> Sources (sha256 at generation):
> - `kicad/wsl-phase8b-revD.net` — `{net_hash[:16]}…`
> - `kicad/revD/wsl-phase8b-revD.kicad_pcb` — `{brd_hash[:16]}…`
> - `kicad/revD/netlist_diff_revC_to_revD.txt` (REFDES_SHIFT cross-reference)
> - `firmware/rp2040/config.h` FW_VERSION — `{fw_ver}` (every firmware reference below)
> - `firmware/rp2040/release/firmware_manifest.json` — `{fw_release["manifest_sha256"][:16]}…`
>   (FA-11 release `id.build={fw_release["release_build"]}`, `id.cfg={fw_release["release_cfg"]}`)
>
> Companion: `docs/phase8_revD_first_article_refdes_map.csv` — the complete
> {len(parts)}-row refdes → function → value → location map (same generation run).
> Procedure authority: `phase8_revD_remediation_spec_2026-07-21.md` §R1.9/§R3/§R4 and
> `phase8_revD_readiness_checklist.md` §2 — this pack is their per-board execution form.

> **⚗️ EXPERIMENTAL FIRST-ARTICLE (R3-8).** These boards are a prototype validation run,
> not a fleet release. The input front-end uses the Rev-D 47 kΩ hardening, but
> the selected PC817 lot is not guaranteed at this board's I_F/hot corner (spec §R4)
> — **r6 moved that operating point to 1.34 mA (`Vw` = 5 V) / ≈1.12 mA (TP4 loaded min);
> the retired pre-r6 figure was ~1.7 mA**. Fleet-release status is contingent on the
> upgraded **FA-9 numeric V_CE / I_C-capability aging-reserve qualification** and the
> at-temperature **FA-7 step 4 (OG-4)** passing on every populated channel of the real
> boards. Do not scale to fleet quantity or field-deploy a lane on these boards until
> FA-9 + OG-4 pass and the readiness-checklist G15 EXPERIMENTAL-ORDER acceptance line is
> signed.

> **✅ INPUT FRONT-END IS PROTECTED IN COPPER (r6, 2026-07-25) — the "BARE, do not land
> PBZ/DIELL" warning that stood here is RETRACTED.** All 40 channels now carry
> `FIELD_WET_V → Rin (2k2) → **Dser** (1N4148WS, series block) → PC817 LED → field pin`,
> with an **anti-parallel `Dclamp`** (1N4148WS) across the LED and a **DNP** logic-side
> `Cflt`. Verified against the emitted netlist: every `FIELD_LED_<n>` now has **three**
> nodes (`Dser.1` + `Dclamp.1` + `PC817.1`). `Dser` and `Dclamp` are **POPULATED on all 40
> channels by default** — there is no per-channel stuffing decision.
> Consequences for this pack:
> - **PBZ (33 VDC) and DIELL_L / DIELL_R (15.4–16 V) MAY now be landed directly on board
>   inputs.** The clamp pins LED reverse voltage at **≈ 0.35 V** against the PC817 6 V
>   absolute maximum (17× inside spec), by a specified V-I curve rather than a leakage
>   ratio. **Prove it per board with FA-15 before relying on it.**
> - **The harness 1N4007 interposer for PBZ/DIELL_L/DIELL_R is SUPERSEDED** and must not
>   be built. Keep it only as a per-lane *verification* note, never as a build step.
> - The cam channels (SA · SB · TA1 · TA2) are still **UNMEASURED** and sit in the
>   machine's 24 VAC relay ladder. r6 makes them **electrically survivable, NOT
>   functionally usable**: a 60 Hz pulse train produces 12 debounced edges per 100 ms
>   against `CHATTER_MAX_CAM` = 8, so a cam channel on sustained 24 VAC **faults
>   continuously**. That needs a **firmware** change, not a cap — do not read the copper
>   fix as closing it. Meter DC-or-AC / RMS / frequency on SA, SB, SC, TA1, TA2, TB at the
>   powered characterization session.
> - **`FIELD_WET_V` has no bulk capacitance** and a driven 24 VAC channel draws 16.8 mA
>   peak from it (vs 1.34 mA dry). The board is budgeted for **zero** driven AC channels;
>   record the count if any are landed.
> Authority: `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md`;
> change-list item 6 is **CLOSED IN COPPER (r6)**.

## 0. Hard rules before power

1. **⛔ Use ONLY this pack + its CSV for probing.** A technician probing "U37" from the
   rev-C TP map lands on the **AUX5 optocoupler** (U37 rev-D), not the isolated wetting
   supply (now **U45**), during a procedure that includes powered safety-rail fault
   injection.
2. Bench PSU ≥ 1 A on J2 (6 × ~77 mA coils + logic). Never feed 5 V into J1 pin 1
   at the same time as J2.
3. J14 bench jumper on 3-4 (legacy Stop/CIS source position) is a
   **bench-only tool — remove before cutover.**
4. DNP refs ({len(dnp_refs)}, listed in the CSV) must be EMPTY: 7 × Rsnub (100R), 7 × Csnub
   (10nF X2), 7 × MOV, the 6-part M1 channel (K7, J12, D13, Q7, R101, R102),
   and **JP1 (default-open ARM bypass)**.
   A populated snubber/MOV at first article means the board was built off-spec
   (sizing awaits the powered characterization session — readiness G7 item 7).

## 1. Refdes shifts rev-C → rev-D (46 — the M6 hazard table)

Never translate from rev-C notes; this table is generated from the authoritative diff.

{md_table(["Function (tag)", "rev-C ref", "rev-D ref", "Value", "rev-D location (x, y)"], shift_rows)}

**Headline traps:** ISO_WET is **U45** (was U37; U37 is now PC817 AUX5). U_WDOG NE555 is
**U44** (was U36; U36 is now PC817 AUX4). The rail-gate pull-up is **R124** (was R106;
R106 is now a lamp resistor).

## 2. Test-pad map (rev-D strip locations — relocated vs rev-C)

{md_table(["TP", "Net", "Location (x, y) mm", "Band"], tp_rows)}

## 3. Key functional groups (positions from the routed board)

### 3.1 Modules / ICs / relays

{md_table(hdr, rows_for(lambda r, p: p["tag"] in ("RP_PICO", "MCP_IN_A", "MCP_IN_B", "MCP_OUT_A", "U_WDOG", "ISO_WET") or r.startswith("K")))}

### 3.2 Safety chain (watchdog → AND → rail gate) — the fault-injection targets

{md_table(hdr, rows_for(lambda r, p: p["tag"] in (
    "Q_WDOG_KICK", "Q_WDOG_OK", "Q_RAIL", "Q_AND_ARM", "Q_AND_RP_OK",
    "R_WDOG_TIMING", "R_WDOG_TRIG_PULLUP", "R_WDOG_KICK_GATE", "R_WDOG_KICK_PD",
    "R_WDOG_OUT_GATE", "R_WDOG_OUT_PD", "R_RAIL_GATE_PULLUP",
    "C_WDOG_TIMING", "C_WDOG_VCC", "C_WDOG_CTRL", "D_WDOG_TIMING", "D_WDOG_TRIG")))}

### 3.3 Rail-tap stages (remediation R1 — 2N7002 unidirectional, reads INVERTED)

{md_table(hdr, rows_for(lambda r, p: p["tag"].startswith(("Q_TAP_", "R_TAPIN_", "R_TAPPU_", "R_TAPG_"))))}

Netting per stage: observed net → R_TAPIN (1M) → `TAP_GATE_*` → FET gate; VCC_3V3 →
R_TAPPU (10k) → `TAP_*` drain → GPIO (GP16=555, GP17=KICK, GP18=ARM, GP19=RPOK, Pico
pins 21/22/24/25). R_TAPG 10M gate pulldowns exist on KICK/ARM/RPOK only — **the 555
stage deliberately has none** (push-pull source, never high-Z); do not report it missing.

### 3.4 Diagnostics adds (ADC divider, wetting bleed, protection diode)

{md_table(hdr, rows_for(lambda r, p: p["tag"] in ("R_ADC5_TOP", "R_ADC5_BOT", "C_ADC5", "R_WET_BLEED1", "R_WET_BLEED2", "D_PROT")))}

### 3.5 Connectors

{md_table(hdr, rows_for(lambda r, p: r.startswith("J") or r == "A1"))}

## 4. First-article procedures (FA-1 … FA-16)

Run in order. Record every measurement in `phase8_revD_run_log.md` (new FA section,
per board serial). One channel of each NEW I/O type must pass before trusting the board.

### FA-1 — Rails
1. Power J2 from the bench PSU (5.0 V, current-limit 1.5 A). Idle draw noted.
2. TP1 (VCC_5V) ≈ 4.6–4.8 V (behind D17 SS34). TP3 (VCC_3V3) 3.3 V ±3 %.
3. **TP4 (FIELD_WET_V) unloaded ≤ ~6 V** — the item-A bleed proof (11–14 V float gone;
   if TP4 still floats high, R122/R123 are missing/open). Under opto load ≥ ~4.5 V.
4. Regression: TP5 ↔ TP2 OPEN (field/logic ground isolation).

### FA-2 — I2C presence
`i2cdetect -y 1` → 0x20 / 0x21 / 0x22 ACK. (Any module later added on J16 must avoid
0x20–0x23.)

### FA-3 — Relay make/break
`lane_node/bench_first_article.py` pattern: each of K1–K6 makes and breaks (K7 DNP).
Watch the ADC trend during the 6-coil energize (feeds FA-6 step 3).

### FA-4 — USB / flash (item B)
Ordinary unmodified micro-B cable fully seats with the J1 ribbon MATED; BOOTSEL
reachable; UF2 drag-drop flash of firmware `{fw_ver}` succeeds WITHOUT a shaved cable.

### FA-5 — GPB bank poke (item C — AUX4-11 on MCP_IN_B 0x21 port B)

{md_table(["J15 pin", "Channel", "GPB bit", "Opto ref", "Opto location"], gpb_rows)}

1. Poke each J15 pin 1–8 to FIELD_GND (J15 pins 9/10) in turn.
2. The matching GPB bit reads ACTIVE-LOW on 0x21; all 8 channels, and confirm NO
   crosstalk between adjacent rows (only the poked bit changes).
3. Software path: `controller_io` with `board_rev="revD"` (`IN_B_MAP_REVD`) — a rev-C
   `board_rev` never reads port B; that is a config error, not a board fault.

**Canonical field allocation after FA-5 and FA-9 both PASS:**

- Reserve **AUX4** for provisional `stop_request`, **AUX5** for provisional
  `pit_interlock_request` if an installed/new pit-entry interlock is approved,
  and **AUX6** for provisional downstream `control_power_ok` /
  breaker-aux proof. These are distinct observations so a bounded demand→power-drop
  test can expose a bypass; a static healthy contact is insufficient. Pilot
  lanes 21/22 have no C.I.S. device or wiring, so never configure a fictitious
  `cis_request` there.
- Reserve **AUX7/AUX8** for S/T digital current switches if threshold sensing is
  selected. Command-off current is `uncommanded_motor_current`; its cause remains
  `external-feed-or-welded` unless independent evidence separates it.
- Reserve **AUX9** for one measured optional dry contact (manual S/T, a verified
  Klixon auxiliary, or a door/service contact). Leave it spare if none is qualified.
- Reserve **J15-7 / AUX10 / GPB6** for `sensor_24v_ok`, supervising the separate
  isolated 24 VDC supply that powers the exit photoeye and distributor prox.
- Reserve **AUX11** for `field_wet_ok`.
- AUX4–AUX9 role names above are design reservations, not released mappings. Leave
  them unmapped until electrical form, landing, isolation, event semantics,
  open-wire behavior, and FA proof are approved.
- Land only a galvanically isolated voltage-monitor relay's
  **energize-to-prove, healthy-when-closed dry contact** between J15-7 and one
  J15-9/10 FIELD_GND terminal. **Never apply 24 V to J15.**
- Sense the monitored voltage downstream of the sensor branch fuse/common so
  loss of branch power opens the contact. Record whether the device is
  undervoltage-only or an under/over-voltage window relay: an undervoltage-only
  contact cannot detect overvoltage, and no single contact can continuously
  distinguish healthy voltage from a welded/shorted-healthy contact.
- Map the role on every board carrying an `exit_beam` or `dist_index` sensor
  powered by that supply. If one supply spans a lane pair, use one independently
  isolated contact pole per board; never join or parallel the boards' field
  domains.
- Provision complete per-board maps (for example,
  `WSL_DIAG_AUX_ROLES_L21=aux2=exit_beam,aux3=dist_index,aux10=sensor_24v_ok`
  and `WSL_DIAG_AUX_ROLES_L22=aux3=dist_index,aux10=sensor_24v_ok`). The
  unscoped map is one-board-bench-only; prove startup refuses two pair
  `exit_beam` sources.
- Before enabling `aux10=sensor_24v_ok`, prove and record: healthy supply =
  stable asserted input; removing sensor power/fuse or either contact lead =
  exactly one `sensor_supply_lost` and no `ball_return_missing`,
  `dist_index_stall`, or `stale_channel` cascade; restoration = exactly one
  `sensor_supply_restored`, no revived pre-outage absence claim, no immediate
  dependent fault, and one configured return-timeout drain interval before new
  pair-return claims. Exercise the relay's test/proof control (or physically
  open the healthy contact) to expose a welded/shorted bypass; if a window relay
  is selected, prove both under- and over-voltage dropouts. Repeat pickup and
  dropout at the FA-9 hot condition. Leave AUX10 unmapped until this passes.
- Only volt-free contacts from listed galvanically isolated monitors may enter
  J15. Never land mains, unclassified live ladder voltage, protective earth, or
  a SAFE_* conductor on an AUX input.

### FA-6 — VCC_5V ADC (item D)
1. GP26/ADC0 reads VCC_5V/2 via R129/R130; the `{fw_ver}` heartbeat carries
   VCC_5V as `v5` (latest) / `v5n` (window min) / `v5x` (window max), all mV
   (R2-5: the old `adc_vcc5` name here matched NOTHING the firmware emits).
2. Compare against the TP1 DMM value: **±3 % gate** (remediation spec R3.4).
3. Energize all 6 coils (FA-3) — the sag must be visible in the heartbeat `v5n` field.

### FA-7 — Rail-tap fault injection (remediation spec **R1.9 governs**; discharges OG-4)

Equipment: bench PSU, scope, heat gun + **thermocouple**, clip leads, Pi-emulator rig,
firmware `{fw_ver}` (release build) + the bench-only **FI-1** build (drives GP16–19
output-high on command; refuses to run without its physical jumper; prints its identity
on the UART banner; NEVER a release artifact).

**Probe rule (R2-5 — governs EVERY tap-node measurement in this procedure):** all
probing and fault insertion on the tap gate/drain nodes goes through the dedicated
probe pads **TP17–TP24** (G column x=128.0, D column x=112.8; silk "TAP PROBES:
D WEST / G EAST") — **never touch a SOT-23 pin of Q17–Q20 with a probe or clip**.
Instrumentation on the GATE pads must present **≥ 100 MΩ input impedance** (high-Z
DMM mode or a ≥ 100 MΩ FET probe): the tap input network is 1 M / 10 M, so a standard
10 MΩ scope/DMM probe loads it and shifts the very levels this procedure verifies.
Drain pads (10 k pull-up) tolerate a 10 MΩ probe, but use the high-Z instrument
throughout if available. Record WHICH instrument was used in the run log.

0. **Boot the FI-1 image (round-3 doc fix — the jumper gate vs the RP2040 bootrom):**
   BOOTSEL held at power-on is intercepted by the ROM — the chip enters the RPI-RP2
   USB bootloader and the image never runs, so a plain power cycle with the jumper
   fitted can NEVER satisfy the gate (bootrom behavior, not a defect). Either:
   **(a) button:** hold BOOTSEL → plug USB (RPI-RP2) → drag
   `wsl_phase8b_rp2040_FI1.uf2` → keep holding through the automatic reboot into the
   image → release after the FI-1 banner (`"fi1":1`) prints; or **(b) jumper +
   picotool:** fit the jumper → plug USB (lands in RPI-RP2 — expected) →
   `picotool reboot`; remove the jumper only after the banner. Booting without the
   jumper is the PERMANENT `fi1_nojumper` refusal — the gate working, never a reason
   to rebuild with the check stubbed.
1. **Level survey (cold):** measure each `TAP_GATE_*` gate node and `TAP_*` drain node
   **at its TP17–TP24 pad** (probe rule above; stage positions in §3.3) through the
   full signal swing. Expect gate-high ≥ 3.0 V
   typical (worst-stack floor per spec R1.5: 2.80–2.82 V). Reads are INVERTED:
   observed HIGH ⇒ GPIO pad LOW.
2. **Unidirectionality proof (cold):** FI-1 drives each GP16–19 output-high in turn
   with J1 UNMATED (ARM_PERMIT / WDOG_KICK high-Z — the Pi-reboot state). Meter each
   observed net (TP11 = NE555_OUT, TP8 = WDOG_KICK, TP13 = ARM_PERMIT,
   TP14 = RP2040_OK): **must not move > 1 mV; the rail (TP16) must not arm.**
3. **Fault insertion (cold):** clip-short each tap stage **drain-gate** (F3) across its
   **TP pad pair** (G pad ↔ D pad — never the SOT-23 pins) — Q17 (555),
   Q18 (KICK), Q19 (ARM), Q20 (RPOK) — and repeat step 2 (the F4 double-fault stack).
   Then with the Pi-emulator arming the rail normally, remove the emulator drive
   (high-Z) with the short still applied — **the rail must drop within the same
   watchdog window as an unfaulted board.**
4. **AT TEMPERATURE — the C1 gate; a cold-only pass does NOT discharge OG-4:** heat
   the Q_AND_ARM (Q15) / Q_AND_RP_OK (Q16) / Q_RAIL (Q14) region AND all four tap FETs
   (Q17–Q20) to **≥ 70 °C case** (thermocouple-verified; hold ≥ 2 min). Repeat steps
   2 and 3 in full at temperature: high-Z + D-G short + stuck-high GPIO — the rail
   must neither arm nor hold, and a deliberate ARM_PERMIT disarm (driven low,
   push-pull — never tristated) must still drop the rail. Photograph thermocouple
   readings for the run log.
5. **Edge-order proof (firmware `{fw_ver}`):** force (a) Pi-death (kill the emulator) and
   (b) kick-starvation (emulator holds ARM high, stops kicking). The 1 ms tap ring
   (`TAPDUMP`) must show the documented edge order and advisory cause for each
   (`arm_drop` / `kick_starvation`), and the record must **survive a Pico reboot**
   (epoch increments, entries retained — spec R3.3). `TAPCLR`, and only `TAPCLR`,
   clears it.
6. Record everything (levels, windows, thermocouple photos) in the run log FA section.

### FA-8 — Cross-mate refusal + sacrificial-pair coding proof (OG-3 / Codex H7)

**Coding install rule (corrected 2026-07-21): the CP-MSTB 1734634 profile fits the
PLUG (or an inverted header) — it is NEVER pressed into a standard MCV G-3.5 header.**
The header side of the code is made by removing the coding rib at the matching pole.

1. **Sacrificial pair FIRST:** on one spare 1840447 plug + one spare/scrap header (or
   the J3 position of a scrap board), install a profile per the Phoenix instruction
   sheet shipped with the parts and make the matching header-side cut. Verify:
   (a) the coded plug seats FULLY in its own coded header;
   (b) the coded plug REFUSES an uncoded header;
   (c) the cut does not damage adjacent poles. Only then code production parts.
2. Code production plugs: J3 @ pole 1 (white band), J15 @ pole 10 (yellow band),
   J13 @ pole 1 (white band), J16 @ pole 6 (blue band); make the matching header-side
   cuts on the board's own headers.
3. **Refusal matrix (all four must physically refuse):** J3-plug vs J15 header ·
   J15-plug vs J3 header · J13-plug vs J16 header · J16-plug vs J13 header.
4. Verify silk legibility at all four: "KEYED: NOT J15" / "NOT J3" / "NOT J16" /
   "NOT J13 LAMP" (1.2 mm silk).

### FA-9 — PC817 input-channel NUMERIC qualification (Rev-D 47 kΩ hardening) — **EXPERIMENTAL FIRST-ARTICLE**

> **Rev-D pull-up change (2026-07-23):** all 40 `Rpu_*` collector pull-ups are now
> **47 kΩ**. The UMW PC817B selected as C5692981 guarantees its CTR rank only at the
> manufacturer's stated test current/temperature; it does **not** guarantee minimum CTR
> at this board's operating I_F and hot corner. The resistor change materially lowers the
> required sink current, but it does not erase that lot uncertainty. Every populated
> channel therefore remains subject to loaded-minimum-voltage and hot numeric
> qualification. Record every number; a bare "PASS" is not acceptable closure.
>
> ### ⚠️ r6 (2026-07-25) MOVED THIS GATE'S OPERATING POINT — do not use the old 1.7 mA
>
> r6 inserts a **series blocking diode (`Dser_*`, 1N4148WS) in every one of the 40
> channels**. The pre-r6 figure of "~1.7 mA I_F" **no longer exists on this board**:
>
> | Condition | I_F | Note |
> |---|---|---|
> | pre-r6 (no series diode), `Vw` = 5 V | 1.750 mA | **HISTORICAL — do not test to this** |
> | r6, `Vw` = 5.0 V nominal | **1.340 mA** | step 2 census condition |
> | r6, TP4 at the step-3 loaded minimum ≈ 4.5 V | **≈ 1.12 mA** | steps 3–5 condition |
>
> That is **21 %–34 % below** the retired figure. The `PART_LOCK` note tying the PC817B
> 130 % CTR floor to the "R4 disposition" also referred to the pre-r6 point; the CTR
> derate applies at the r6 currents above. Derivation:
> `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md` §C.
>
> ### ⚠️ THE ≤ 100 µs EDGE CRITERION ASSUMES EVERY `Cflt_*` IS UNFITTED
>
> r6 also lands 40 **DNP** logic-side filter caps (`Cflt_*`, C17–C56). **They ship
> unfitted and the first article has none — FA-9 step 5 is measured in exactly that
> state.** The fab package's own DNP instruction
> (`assembly/…-dnp-excluded.csv`) authorises fitting 10 nF on the RP2040 fast channels
> (47 k × 10 nF × ln(3.3/1.155) = **493 µs**) and up to 2.2 µF on the MCP slow channels
> (**≈ 180 ms**) on a channel *measured* to carry a 60 Hz pulse train. Those values are
> deliberately far beyond 100 µs.
>
> **Ordering rule (binding):** a channel that later takes a `Cflt` is **re-qualified
> against the debounce budget** — `DEBOUNCE_CAM_US` 2000 µs / `DEBOUNCE_DIELL_US` 500 µs
> on fast channels, and the 200 ms slow-channel release budget — **NOT against ≤ 100 µs**.
> Fitting a `Cflt` and then re-running FA-9 step 5 unchanged produces a channel that can
> never pass, on the cam and DIELL channels that gate the FSM. Record which channels (if
> any) carry a `Cflt` alongside the FA-9 numbers.
>
> **Binding pull-configuration dependency:** the arithmetic below assumes each external
> 47 kΩ `Rpu_*` is the channel's only pull-up. The production RP2040 build must leave
> internal pulls disabled on all eight fast-input pads (GP6–GP13), and the deployed
> MCP23017 setup must program and read back `GPPUA=0x00` and `GPPUB=0x00` on both
> input expanders U1/U2. Any enabled internal pull changes the effective resistance
> and invalidates this disposition. The four 10 kΩ diagnostic-tap drain pull-ups
> `R_TAPPU_*` are separate MOSFET-drain networks; they are intentionally unchanged
> and are not part of the PC817 `Rpu_*` calculation.

**Threshold, idle-high, and timing arithmetic:**
- For the 32 MCP23017-received slow channels, GPIO V_IL(max) is 0.2 × VDD =
  **0.66 V** at 3.3 V. With 47 kΩ as the sole pull-up, the
  phototransistor need only sink `(3.3 − 0.66)/47 kΩ` = **56.2 µA** to cross the
  guaranteed LOW threshold. The pull-up can supply at most `3.3/47 kΩ` =
  **70.2 µA** at a zero-volt collector. Healthy hard saturation remains
  **V_CE(on) ≤ 0.30 V**.
- MCP23017 GPIO V_IH(min) is 0.8 × VDD = **2.64 V**. Its ±1 µA input-leakage
  limit can pull a 47 kΩ idle node down by at most 47 mV, leaving
  **3.253 V**, 0.613 V above V_IH. That calculation covers receiver leakage
  only; FA-9 measures the assembled channel so optocoupler dark leakage,
  contamination, and board leakage are included.
- Using the MCP23017's 50 pF GPIO capacitance figure as a first-order node load,
  `47 kΩ × 50 pF` = **2.35 µs**. Actual optocoupler, trace, and probe
  capacitance add to it. The measured worst transition must remain **≤ 100 µs**,
  at least 5× faster than the 500 µs fastest-input debounce. **This limit is valid
  only with `Cflt_*` UNFITTED — see the r6 ordering rule above.**
- **Why V_CE(on) alone is not the reserve:** once capability exceeds the
  70.2 µA rail limit, V_CE pins low regardless of extra capability. Measure
  non-rail-limited collector capability **I_C(cap)** with an adjustable
  diagnostic load/current meter at the hot/min-I_F corner.
- **Aging-reserve criterion:** after the existing 30% lifetime-loss planning
  factor, capability must still exceed the 70.2 µA pull-up maximum:
  **PASS ⟺ I_C(cap, hot, min-I_F) × 0.70 ≥ 70.2 µA ⟺ I_C(cap) ≥ 100.3 µA.**

**Procedure — record numerics per channel, both temperature legs:**
1. **Fail-closed pull-configuration proof (before voltage arithmetic):** boot the exact
   production release from FA-11. Record a runtime pad-register/self-check readback for
   RP2040 **GP6–GP13** and require both PUE and PDE clear on every pad. Read the
   MCP23017 `GPPUA` (`0x0C`) and `GPPUB` (`0x0D`) registers from input expanders
   **U1/0x20 and U2/0x21** and require all four bytes = **`0x00`**. Any nonzero
   value is a STOP-SHIP: do not apply the 47 kΩ sink/leakage/RC limits until fixed.
2. **V_CE(sat) census at nominal wetting (R4 trigger condition 1):** with the field
   contact closed at the **r6 nominal 1.34 mA I_F** (`Vw` = 5.0 V; NOT the retired
   pre-r6 ~1.7 mA), measure and RECORD **in-circuit V_CE(on) on every
   populated channel** (not a 3-channel sample any more). Flag any channel with
   **V_CE(on) > 0.30 V** — it blocks release and reopens the input-front-end disposition.
3. **Loaded-minimum FIELD_WET leg (R2-7, cold):** load the wetting rail to fleet worst case
   (all populated contacts closed), confirm FIELD_WET_V at TP4 at its loaded minimum
   (≈ 4.5 V — FA-1 step 3). Per populated channel record **in-circuit V_CE(sat)** AND the
   **diagnostic-load capability I_C(cap)** (bench pull-up / µA meter as above); confirm the
   actual receiver bit reads ACTIVE-LOW. **Every populated channel.**
4. **Temperature leg (R2-7 + R3-8 — the worst-case CTR corner):** heat the populated PC817
   input optos (§3 refdes map) to **≥ 70 °C case** (thermocouple-verified — same rig as
   FA-7 step 4) and repeat step 3 at the loaded minimum field voltage, spanning the declared
   range (25 °C ambient → ≥ 70 °C case). **Record per channel: V_CE(on) cold,
   V_CE(on) hot, I_C(cap) hot, I_C(cap)/100.3 µA, aging-reserve PASS/FAIL,
   measured TP4 voltage, and case temperature.**
5. **Idle-high/leakage and edge-time leg:** at ≥70 °C and with each contact open,
   record its collector-node HIGH voltage and receiver state. Require
   **V_node ≥ 2.84 V** (V_IH + 0.20 V service guard) and INACTIVE. At the
   loaded-minimum field voltage, capture both assertion and release at the
   collector; require the slower transition **≤100 µs**. Any channel failure
   blocks G15 fleet release and requires component/contamination/root-cause
   disposition before a resistor or optocoupler substitution.

### FA-10 — MCV header mechanical (FR-9, first connector only)
Before reflowing/soldering the remaining six MCV headers, install and solder ONE
(recommend J14, 4-pos) on the 1.4 mm `_D1.4` drills: verify insertion force is normal
and solder fill is complete. Then proceed with the rest.

### FA-11 — Firmware posture assert (refuses the first-article pass if absent)
1. Run `powershell -ExecutionPolicy Bypass -File firmware/rp2040/release.ps1
   -VerifyOnly`; record manifest SHA-256
   **`{fw_release["manifest_sha256"]}`**. Any verifier failure blocks flashing.
2. Hash the exact release UF2 before flash and require
   **`{fw_release["release_sha256"]}`**. After boot, request `ID` and require all four
   values exactly: `fw="{fw_ver}"`, `build="{fw_release["release_build"]}"`,
   `cfg="{fw_release["release_cfg"]}"`, `fi1=0`. A matching filename or version
   banner alone is not image proof. Also confirm `tap:{{ep,pre,n}}` state.
3. The lane deployment identity allowlists must contain those exact `build` and `cfg`
   values from the manifest; no wildcard, prefix, Git hash, or manually typed substitute.
4. Confirm the production build's fast-input pull invariant at runtime: RP2040
   **GP6–GP13** must report PUE=0 and PDE=0. This is the firmware half of FA-9 step 1;
   any enabled pull invalidates the 47 kΩ input-margin arithmetic.
5. `tap_assert_input_only()` is active (heartbeat-tick OE/FUNCSEL readback); simulate
   nothing here — the host suite already proves the trip path; on-silicon just confirm
   no `tap_dir` fault is latched with the release build.
6. The bench-only FI-1 UF2 must hash
   **`{fw_release["fi1_sha256"]}`** and emit
   `build="{fw_release["fi1_build"]}", fi1=1`; confirm it refuses to run without its
   physical jumper. Never enter the FI-1 build in the deployment allowlist.
7. Deliberate disarm drives ARM_PERMIT low (push-pull), never tristates.

### FA-12 — J16 SDA/SCL external-short recovery (round-2 R2-4)

Proves the TCA4307 (U46) actually isolates the controller bus, and that a wedged J16
is an AVAILABILITY event with a fail-safe landing — never an unsafe state. Run with the
board operating normally: release firmware `{fw_ver}`, Pi-emulator arming the rail,
relays exercising the FA-3 pattern.

1. Short **J16 SDA (card side) → GND** at the connector. While the short is held:
   `i2cdetect -y 1` still ACKs **0x20 / 0x21 / 0x22**, the relay pattern keeps
   running, RELAY_ENABLE_RAIL (TP16) and every output are UNCHANGED, and no safety
   fault latches — controller bus + safety response + output state all deterministic.
2. Release the short: U46 must reconnect the card side on its own (~40 ms stuck
   detect, up to 16 SCLOUT recovery pulses per the TI datasheet) — a module on J16
   re-enumerates WITHOUT a board power cycle.
3. Repeat steps 1–2 for **SCL → GND**, then **SDA + SCL → GND together**.
4. Sustained wedge: repeat step 1 holding the short **> 60 s** — bus, outputs, and
   rail state stay deterministic for the full duration (no watchdog trip, no drift).
5. **Severity record (R2-4):** a fault that DID wedge the controller-side bus would
   land as tick-I2C failure → `_on_safety_trip` → ARM drop → rail de-energized — an
   availability incident with a fail-safe landing. U46 exists so a J16 module cannot
   cause even that. Record the observed behavior against this statement.
6. **Polyfuse contract (F1 = 1206L020YR; R2-4 fitted, allowance re-derived R3-7):** the
   sanctioned STEADY module draw on J16 pin 1 (VCC_5V) is **≤ 45 mA** — re-derived from the
   1206L020 temperature-derating table at the 85 °C worst-case enclosure body temperature
   with a ≥ 2× hold margin (90 mA hold @ 85 °C ÷ 2); the earlier 100 mA figure used the
   23 °C hold and had no hot margin. F1 still trips a *shorted* module (~420 mA @23 °C) well
   inside the SS34 3 A rail budget. If a module is fitted, record its measured steady draw
   and confirm ≤ 45 mA. (rev-D.1 upgrade path — eFuse with an open-drain FAULT flag to a
   spare RP2040 GPIO — is recorded in run-log FR-15; needs copper, not this spin.)

### FA-13 — Stop / pit-interlock demand-to-power-drop proof (**system-level P0 gate**)

This is an at-machine commissioning test, not a bare-board substitute. J14.3–4
is physically OPEN in the released lane-21/22 harness and the field rail cannot
arm. Keep it open—and never jumper it at the machine—until an approved drawing,
measured electrical form, and fail-safe isolated interface are recorded.

1. With the machine locked out, identify and meter the proposed Stop/master
   control-power landing. The leading candidate is a correctly rated,
   galvanically isolated, energize-to-prove control-power sensing relay: its
   coil bridges the selected downstream control rail and its N.O. volt-free
   contact closes J14.3–4 only while that rail is energized. Require an approved
   drawing, coil/overcurrent protection, enclosure, conductor routing, voltage
   class, and acceptance limits. Power/coil/open-wire failures de-energize the
   contact, but a welded sensing contact remains a credible fault and must be
   exposed by the proof test below. No mains, unclassified live ladder, or
   protective-earth conductor may enter J14 or J15.
2. Record the installed chassis devices. On pilot lanes 21/22, physical
   inspection found **no C.I.S. device or wiring**; a C.I.S. test is N/A, not a
   pass. Determine whether another pit-entry interlock exists. If none exists,
   the owner and a qualified machine-safety reviewer must decide whether to
   install one or accept a Stop-plus-lockout-only operating design before
   controller cutover.
3. If a new/other pit interlock is used as a final disconnect, it must act in
   the approved upstream master/control-power safety chain (or an equivalently
   qualified safety-disconnect architecture). A contact placed only in J14 can
   drop board permission but cannot stop a welded downstream contact and is not
   a replacement for an upstream C.I.S.
4. If continuous diagnostics are fitted, land separate isolated
   `stop_request`, optional `pit_interlock_request`, and downstream
   energize-to-prove `control_power_ok`/breaker-aux contacts. Pass FA-5 and FA-9
   on those exact populated channels before enabling their still-provisional
   role mappings.
5. Before the powered test, record the maximum permitted demand→master/control
   power drop time and demand→TP16 drop time. The limits come from the approved
   safety design and measured machine behavior; this pack does not invent them.
6. In the guarded powered session, demand **Stop**. Require the Stop request to
   be observed, the master/control power and TP16 to drop within the recorded
   bounds, every commanded output to be de-energized, and no automatic motion on
   restoration. Reset only through the deliberate operator recovery sequence.
7. On a chassis that actually has a C.I.S. or another approved pit-entry
   interlock, repeat step 6 independently for that device. On lanes 21/22,
   record C.I.S. absent and execute the approved disposition from step 2; do
   not invent or silently waive a C.I.S. result.
8. Open each monitor lead in turn. Every open wire must fail visible. Exercise
   the control-power relay's proof path by de-energizing its coil and requiring
   J14.3–4 and TP16 to open/drop. Exercise every monitor's proof/test control so
   a welded/shorted-healthy or bypassed observation cannot pass merely because
   it remains asserted.
9. Execute the Candidate-C **TB/SC G3 insertion proof** per lane. With both
   levers BACK/open, command S and then T independently from the board and prove
   each respective machine coil dead. Record both results and verify the OEM
   closed-when-safe ladder remains in the series coil path and has not been
   bypassed. Incorporate this exact evidence into the signed commissioning
   latch; neither a generic ladder observation nor a one-coil sample passes.
10. Record this proof per lane at cutover and in the periodic safety-proof
   schedule. The manifest-controlled retest interval is **365 days maximum**,
   and repeat testing is required sooner after relevant safety/control
   electrical service. Expired evidence blocks healthy monitor status. A
   healthy static sample never replaces the demand test.
11. Complete the signed commissioning record. Bind it to fleet policy, lane,
    Pico UID, board revision/serial, and harness revision/serial. The verifier
    must obtain a matching controller-originated live identity through its
    hard-deadline path no more than **90 seconds** before acceptance; record the
    observation timestamp and age. A stale, absent, mismatched, or manually
    substituted identity fails closed. Signing authenticates the evidence; it
    does not create or replace any physical test above.

### FA-14 — Protective-earth and supply-polarity proof (**external mains gate**)

1. A qualified electrician uses an appropriately listed, in-calibration tester
   and the machine manufacturer's procedure to verify protective-earth
   continuity/bonding and hot/neutral polarity at commissioning.
2. Record instrument ID/calibration status, measured results, acceptance limits,
   lane/machine identity, initials, and date. Repeat at the manifest-controlled
   interval of **365 days maximum**, and sooner after relevant electrical
   service. Expired evidence blocks healthy monitor status.
3. Board 5 V, 24 VAC, and `control_power_ok` do not prove either condition.
   Mains and PE test current stay completely outside Rev-D and every Pi/RP2040/
   MCP/J14/J15 circuit.

### FA-15 — r6 LED reverse-voltage proof (anti-parallel clamp populated + correct)

> **ID NOTE:** the r6 spec §F.4 originally allocated this gate "FA-10". **FA-10 is already
> the MCV header mechanical gate.** This gate is **FA-15** — the next free ID. Do not
> renumber it back.

**Why this gate exists and no other gate replaces it.** The two clamp failure modes are
**not symmetric**. A **reversed or shorted** `Dclamp` shunts the PC817 LED (`Vf` 0.7 V <
LED 1.15 V) and the channel reads **dead** — commissioning catches that 100 %. An
**OPEN or unplaced** clamp (tombstoned 0.60 × 0.45 mm SOD-323, wrong reel, AOI miss on 80
new placements) leaves the channel **fully functional in every commissioning test** while
the PC817 LED sits at up to **27.7 V reverse** against its **6 V** absolute-max `V_R` on
PBZ, and 10–15 V on DIELL_L/R. Protection silently degrades to the leakage-ratio case the
design explicitly rejects, and the LED dies weeks later in service with no diagnostic
trail. **FA-15 is the only measurement that distinguishes those two states.**

**Procedure (per board; every populated channel that can go reverse-biased):**
1. With the machine energised and the channel landed, drive the field pin **positive**
   relative to `FIELD_GND` (PBZ at its measured 33 VDC is the canonical case; DIELL_L/R at
   15.4–16 V; for a bench proof inject ≥ 15 VDC through the harness lead).
2. Measure across the PC817 LED — `FIELD_LED_<n>` (clamp/`Dser` cathode node) to the
   field-pin net — with a high-impedance DMM.
3. **PASS ⟺ 0.35 V ± 0.1 V reverse** (i.e. **0.25 V … 0.45 V**). This is the clamp's
   forward drop at ~15 µA of `Dser` + LED reverse leakage, and it is set by a **specified
   V-I curve**, not by a leakage ratio.
4. **Interpretation of a failure — record which, do not just fail:**
   - **> 1 V** → clamp **missing, open, or reversed**. STOP: the LED is unprotected.
   - **≈ 0 V with the channel dead in the forward direction** → clamp **shorted or fitted
     reversed-and-conducting**.
   - **At the 150 °C leakage extreme** the predicted value rises to ≈ 0.42 V; a hot-leg
     reading inside 0.25–0.50 V is acceptable if the cold leg passed.
5. Record the measured millivolts per channel, the field voltage used, and the board
   serial. A bare "PASS" is not acceptable closure.

### FA-16 — r6 per-channel orientation + continuity census (**UNPOWERED, before FA-1**)

> **Run this FIRST, on the bare assembled board, before any power is applied.** FA-15
> proves the clamp on the handful of channels that can be driven reverse-biased by a
> live machine. FA-16 proves **all 120 r6 parts on all 40 channels** with no machine, no
> harness and no risk — and it is the only gate that catches a **reversed `Dser`** before
> that channel is quietly dead in commissioning.

**Why a census and not a sample.** r6 added **80 diodes in two different orientations**
(`Dser` anode-west toward `Rin`, `Dclamp` cathode-north on the LED node) on 0.60 × 0.45 mm
SOD-323 lands. A reel loaded backwards, a rotated placement, or one tombstone produces
**four distinguishable faults**, and only a two-direction probe separates them:

| Probe (DMM diode test, board unpowered, no harness) | Good board | Fault it exposes |
|---|---|---|
| **(A)** red on the channel's `Rin` **board-side** pad (`FIELD_RIN_<n>`), black on the field pin at the connector | **≈ 1.75–1.95 V** (`Dser` Vf ≈ 0.7 V **+** PC817 LED Vf ≈ 1.15 V in series) | **OL** → `Dser` REVERSED, open, or tombstoned; or the LED is open. **≈ 0.7 V** → the LED is shorted or `Dser` is missing and `Dclamp` is conducting. |
| **(B)** reverse the leads (red on the field pin, black on `FIELD_RIN_<n>`) | **≈ 0.60–0.75 V** — this is `Dclamp` conducting forward, and it is the ONLY thing that should conduct this way | **OL** → `Dclamp` MISSING, open, or REVERSED (the silent failure FA-15 exists for — catch it here instead). **≈ 0 V** → `Dclamp` shorted. |
| **(C)** visual/AOI: the 40 `Cflt_*` lands | **EMPTY** (all 40 ship DNP) | A fitted `Cflt` on a fast channel silently breaks FA-9's ≤ 100 µs edge criterion. |

**Meter requirement:** the (A) reading needs a diode-test source compliance **above ~2.0 V**
(two junctions in series). Many pocket DMMs stop at 1.5–2.0 V and will read **OL on a
perfect board**. Verify your meter first on a known-good channel, or substitute a bench
supply: 5 V through a 2.2 kΩ series resistor into `FIELD_RIN_<n>`, field pin to
`FIELD_GND`, and confirm ≈ 1.5–2.0 mA flows and the opto's collector goes LOW.

**Acceptance: 40/40 channels pass BOTH (A) and (B).** Record the two readings per channel
in the census below — a bare "PASS" is not acceptable closure, for the same reason as
FA-15: the failure mode this gate exists to catch reads as a working board everywhere else.

{md_table(["Ch", "Speed", "Field pin", "Opto", "Rin", "Dser", "Dclamp", "Cflt (DNP)"],
          r6_rows)}

## 5. Sign-off

| Item | Result | Initials / date |
|---|---|---|
| FA-1 rails (TP4 bleed proof) | | |
| FA-2 I2C 0x20/21/22 | | |
| FA-3 relays K1–K6 | | |
| FA-4 USB seat + UF2 | | |
| FA-5 GPB bank 8/8 no-crosstalk | | |
| FA-6 ADC ±3 % + sag visible | | |
| FA-7 tap fault injection COLD | | |
| FA-7 step 4 **AT ≥ 70 °C** (OG-4) | | |
| FA-7 step 5 edge order + reboot persistence | | |
| FA-8 sacrificial pair + 4-way refusal | | |
| FA-9 V_CE(sat) numeric census — every populated channel (R4) | | |
| FA-9 per-channel I_C(cap) + aging-reserve PASS @ min FIELD_WET + ≥ 70 °C (R2-7 / R3-8) | | |
| FA-9 per-channel hot idle-HIGH/leakage + ≤100 µs edge-time PASS (**with every `Cflt_*` UNFITTED**) | | |
| FA-10 MCV insertion/solder fill | | |
| FA-11 verified manifest + UF2 SHA + exact `id.build`/`id.cfg`/`fi1=0` posture | | |
| FA-12 J16 SDA/SCL short recovery (U46, R2-4) | | |
| FA-13 installed safety devices recorded; lane-21/22 C.I.S.-absent disposition approved | | |
| FA-13 Stop demand → master/control power + TP16 drop, per lane | | |
| FA-13 installed/new pit interlock demand → upstream power + TP16 drop, if applicable | | |
| FA-13 Candidate-C TB/SC G3 — board-command **S**, both levers BACK/open, S coil dead, OEM ladder not bypassed (`tb_sc_insertion_proof`, S result/evidence) | | |
| FA-13 Candidate-C TB/SC G3 — board-command **T**, both levers BACK/open, T coil dead, OEM ladder not bypassed (`tb_sc_insertion_proof`, T result/evidence) | | |
| FA-13 monitor open-wire/proof-control tests + periodic-test owner | | |
| FA-14 protective-earth continuity/bonding — tester ID, calibration due, result, limit (`protective_earth_continuity`) | | |
| FA-14 hot/neutral polarity — tester ID, calibration due, result (`hot_neutral_polarity`) | | |
| **FA-15 (r6) LED reverse = 0.35 V ± 0.1 V per over-voltage channel — mV recorded, not "PASS"** | | |
| **FA-15 (r6) cam-channel AC/DC + RMS + frequency metered on SA/SB/SC/TA1/TA2/TB** | | |
| **FA-15 (r6) driven-24 VAC channel count N recorded (board budgeted for N = 0; N ≥ 1 reopens the `FIELD_WET_V` budget)** | | |
| **FA-16 (r6) probe (A) forward 1.75–1.95 V — 40/40 channels, volts recorded per channel** | | |
| **FA-16 (r6) probe (B) reverse 0.60–0.75 V — 40/40 channels, volts recorded (this is the `Dclamp`-present proof)** | | |
| **FA-16 (r6) all 40 `Cflt_*` lands EMPTY; meter diode-test compliance verified > 2.0 V** | | |
| Signed commissioning binding — lane, Pico UID, board/harness rev+serial, record ID, signer, tested/due UTC (≤365 d), exact controller-originated live identity observed UTC/age (≤90 s) | | |
"""

    OUT_MD.write_text(doc, encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_CSV} ({len(parts)} rows)")
    print(f"Shifts: {len(shifts)}; TPs: {len(tp_rows)}; GPB rows: {len(gpb_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
