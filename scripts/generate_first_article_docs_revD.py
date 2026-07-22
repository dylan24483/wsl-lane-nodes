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
import re
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


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def main() -> int:
    parts = parse_netlist()
    board = parse_board()
    shifts = parse_shifts()

    missing = [r for r in parts if r not in board]
    if missing:
        raise SystemExit(f"Netlist refs missing from board: {missing}")
    if len(shifts) != 46:
        raise SystemExit(f"Expected 46 REFDES_SHIFT rows, got {len(shifts)}")

    # ---- CSV: full refdes map -------------------------------------------------------
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
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

    today = date.today().isoformat()
    net_hash = sha256(NETLIST)
    brd_hash = sha256(BOARD)
    fw_ver = firmware_version()   # R2-5: pack must agree with config.h

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
>
> Companion: `docs/phase8_revD_first_article_refdes_map.csv` — the complete
> 262-row refdes → function → value → location map (same generation run).
> Procedure authority: `phase8_revD_remediation_spec_2026-07-21.md` §R1.9/§R3/§R4 and
> `phase8_revD_readiness_checklist.md` §2 — this pack is their per-board execution form.

## 0. Hard rules before power

1. **⛔ Use ONLY this pack + its CSV for probing.** A technician probing "U37" from the
   rev-C TP map lands on the **AUX5 optocoupler** (U37 rev-D), not the isolated wetting
   supply (now **U45**), during a procedure that includes powered safety-rail fault
   injection.
2. Bench PSU ≥ 1 A on J2 (6 × ~77 mA coils + logic). Never feed 5 V into J1 pin 1
   at the same time as J2.
3. J14 bench jumper on 3-4 (Stop/CIS) is a **bench-only tool — remove before cutover.**
4. DNP refs (27, listed in the CSV) must be EMPTY: 7 × Rsnub (100R), 7 × Csnub
   (10nF X2), 7 × MOV, and the 6-part M1 channel (K7, J12, D13, Q7, R101, R102).
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

## 4. First-article procedures (FA-1 … FA-12)

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

### FA-9 — PC817 input-channel qualification (remediation spec R4 + round-2 R2-7)

1. **V_CE sampling (R4 trigger condition 1):** measure V_CE(on) on **3 sample channels**
   at nominal wetting (~1.7 mA I_F) with the field contact closed. Gate: **V_CE(on) ≤
   0.3 V** on every sampled channel. Any channel above 0.3 V REOPENS the R4 disposition
   (forces Rin 2k2 → 1k ≈ 3.5 mA + mandatory §H.3 wetting and §H.4 D17 budget re-runs).
   Record values per channel.
2. **Per-channel qualification at minimum field voltage (R2-7):** load the wetting rail
   to its fleet worst case (all populated field contacts closed), confirm FIELD_WET_V at
   TP4 sits at its loaded minimum (≈ 4.5 V — FA-1 step 3), then close each populated
   field-input channel in turn and confirm its MCP23017 bit reads ACTIVE-LOW. This is
   the R4 threshold condition made empirical: the phototransistor must sink
   ≈ 0.26 mA (pull the 10 k logic pull-up below V_IL ≈ 0.66 V) at the LOWEST I_F the
   fleet will ever supply. **Every populated channel — not a sample.**
3. **Temperature leg (R2-7):** heat the populated PC817 input optos (§3 refdes map) to
   **≥ 70 °C case** (thermocouple-verified — same rig as FA-7 step 4) and repeat
   step 2 at the loaded minimum field voltage. Hot + low-I_F is the worst-case CTR
   corner the spec R4 arithmetic bounds from typical curves; a clean per-channel pass
   here is the empirical closure of the R2-7 disposition (spec §R4-A). Record
   per-channel PASS + measured TP4 voltage + case temperature. Any failure lands
   under R4 reopen trigger 1.

### FA-10 — MCV header mechanical (FR-9, first connector only)
Before reflowing/soldering the remaining six MCV headers, install and solder ONE
(recommend J14, 4-pos) on the 1.4 mm `_D1.4` drills: verify insertion force is normal
and solder fill is complete. Then proceed with the rest.

### FA-11 — Firmware posture assert (refuses the first-article pass if absent)
1. Boot banner shows `{fw_ver}` (config.h FW_VERSION at pack generation — a
   different banner means the wrong image is flashed) and `tap:{{ep,pre,n}}` state.
2. `tap_assert_input_only()` is active (heartbeat-tick OE/FUNCSEL readback); simulate
   nothing here — the host suite already proves the trip path; on-silicon just confirm
   no `tap_dir` fault is latched with the release build.
3. Confirm the running build is NOT FI-1 (banner identity), and FI-1 refuses to run
   without its physical jumper.
4. Deliberate disarm drives ARM_PERMIT low (push-pull), never tristates.

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
| FA-9 V_CE ≤ 0.3 V ×3 channels | | |
| FA-9 per-channel qual @ min FIELD_WET + ≥ 70 °C (R2-7) | | |
| FA-10 MCV insertion/solder fill | | |
| FA-11 firmware `{fw_ver}` posture | | |
| FA-12 J16 SDA/SCL short recovery (U46, R2-4) | | |
"""

    OUT_MD.write_text(doc, encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_CSV} ({len(parts)} rows)")
    print(f"Shifts: {len(shifts)}; TPs: {len(tp_rows)}; GPB rows: {len(gpb_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
