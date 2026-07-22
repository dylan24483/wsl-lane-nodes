#!/usr/bin/env python3
"""
Machine-readable netlist diff: rev-C (kicad/wsl-phase8b.net — read-only) vs
rev-D (kicad/wsl-phase8b-revD.net). Writes kicad/revD/netlist_diff_revC_to_revD.txt.

Identity model: SKiDL tags (the 'SKiDL Tag' netlist field) are the stable part
identity across revisions; numeric refdes shift when parts are inserted
mid-sequence and are reported separately as REFDES_SHIFT lines. Net node
membership is therefore compared as (tag, pin) sets, not (ref, pin).

Fails (exit 1) if anything OUTSIDE the documented rev-D contract changed:
  - any rev-C part removed, or its value/footprint changed (except the
    ALLOWED_CHANGED_PARTS whitelist: D_PROT SS14->SS34 per spec §H.4)
  - any rev-C net removed
  - any rev-C net changed other than the 11 documented touch-point nets
  - any touch-point net LOSING a rev-C node (additions only)
  - any added part/net not in the spec's expected-additions list

M1 DEEP CHECK (Codex NO-GO audit 2026-07-21): name/count validation alone
let a wrong value, footprint or pad hookup ride under a correct tag. The
expected-DELTA tables below now pin, for EVERY addition:
  - each added part's exact value + footprint (EXPECTED_ADDED_PART_SPECS)
  - each added net's exact (tag, pin) membership (EXPECTED_ADDED_NET_NODES)
  - each touched rev-C net's exact ADDED nodes (EXPECTED_TOUCHED_NET_ADDITIONS)
Codex's manual deep pass proved these values correct; encoding them keeps
the proof executable — any future rev-D netlist change must update the
tables in the SAME commit or this script exits 1.

Run:  py -3 scripts\\diff_netlist_revC_to_revD.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REVC = os.path.join(ROOT, "kicad", "wsl-phase8b.net")
REVD = os.path.join(ROOT, "kicad", "wsl-phase8b-revD.net")
OUT_DIR = os.path.join(ROOT, "kicad", "revD")
OUT = os.path.join(OUT_DIR, "netlist_diff_revC_to_revD.txt")

# The only rev-C nets rev-D is allowed to touch (all additions-only), per
# docs/phase8_revD_change_spec.md items A/C/D/E/F:
ALLOWED_TOUCHED_NETS = {
    "FIELD_WET_V",    # A: bleed pair; C: 8 x Rin_AUXn
    "FIELD_GND",      # A: bleed pair; C: J15 pins 9-10
    "VCC_5V",         # D: divider top; F: J16 pin 1
    "GND",            # C: 8 x opto emitter; D: divider bottom + cap;
                      # E(R1): 4 x Q_TAP source + 3 x R_TAPG; F: J16 pins 2,6
    "VCC_3V3",        # C: 8 x Rpu_AUXn; E(R1): 4 x R_TAPPU; F: J16 pin 5
    "I2C_SDA",        # F: J16 pin 3
    "I2C_SCL",        # F: J16 pin 4
    "NE555_OUT",      # E(R1): R_TAPIN_555 series input
    "WDOG_KICK",      # E(R1): R_TAPIN_KICK series input
    "ARM_PERMIT",     # E(R1): R_TAPIN_ARM series input
    "RP2040_OK",      # E(R1): R_TAPIN_RPOK series input
}

# Item E per remediation spec R1.7 (2026-07-21): the five resistive tap parts
# (R_TAP_555/R_TAP_555_DIV/R_TAP_KICK/R_TAP_ARM/R_TAP_RPOK) were rev-D-INTERNAL
# (never existed in rev-C) and are replaced wholesale by the unidirectional
# stages below — so they simply vanish from the expected-additions list; there
# is still ZERO rev-C removal.
_TAP_SUFFIXES = ["555", "KICK", "ARM", "RPOK"]
EXPECTED_ADDED_TAGS = (
    ["R_WET_BLEED1", "R_WET_BLEED2"]                                   # A
    + [f"{p}_AUX{i}" for i in range(4, 12) for p in ("OPTO", "Rin", "Rpu")]  # C
    + ["J_SLOWC"]                                                      # C
    + ["R_ADC5_TOP", "R_ADC5_BOT", "C_ADC5"]                           # D
    + [f"R_TAPIN_{s}" for s in _TAP_SUFFIXES]                          # E (R1)
    + [f"R_TAPPU_{s}" for s in _TAP_SUFFIXES]                          # E (R1)
    + [f"Q_TAP_{s}" for s in _TAP_SUFFIXES]                            # E (R1)
    + [f"R_TAPG_{s}" for s in ("KICK", "ARM", "RPOK")]                 # E (R1; 555 has none by design)
    + ["J_EXTI2C"]                                                     # F
)

EXPECTED_ADDED_NETS = (
    [f"{p}AUX{i}" for i in range(4, 12) for p in ("SLOW_", "FIELD_SLOW_", "FIELD_LED_")]  # C
    + ["ADC_VCC5_SENSE"]                                               # D
    + ["TAP_NE555_OUT", "TAP_WDOG_KICK", "TAP_ARM_PERMIT", "TAP_RP2040_OK"]  # E
    + [f"TAP_GATE_{s}" for s in _TAP_SUFFIXES]                         # E (R1)
)

# ---------------------------------------------------------------------------
# M1 expected-DELTA deep tables (Codex audit 2026-07-21) — see module docstring.
# ---------------------------------------------------------------------------
_FP_R = "Resistor_SMD:R_0805_2012Metric"
_FP_C = "Capacitor_SMD:C_0805_2012Metric"
_FP_DIP4 = "Package_DIP:DIP-4_W7.62mm"
_FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"   # existing on-board class (AO3401A)

# tag -> (value, footprint) for EVERY expected added part.
EXPECTED_ADDED_PART_SPECS = {
    "R_WET_BLEED1": ("2k2", _FP_R),                                    # A
    "R_WET_BLEED2": ("2k2", _FP_R),                                    # A
    "J_SLOWC": ("J_SLOW_IN_C",                                         # C (J15)
                "wsl_footprints:PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical_D1.4"),
    "R_ADC5_TOP": ("10k", _FP_R),                                      # D
    "R_ADC5_BOT": ("10k", _FP_R),                                      # D
    "C_ADC5": ("100nF", _FP_C),                                        # D
    "J_EXTI2C": ("J_EXT_I2C",                                          # F (J16)
                 "wsl_footprints:PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical_D1.4"),
}
for _i in range(4, 12):                                                # C: AUX bank
    EXPECTED_ADDED_PART_SPECS[f"OPTO_AUX{_i}"] = (f"PC817 AUX{_i}", _FP_DIP4)
    EXPECTED_ADDED_PART_SPECS[f"Rin_AUX{_i}"] = ("2k2", _FP_R)
    EXPECTED_ADDED_PART_SPECS[f"Rpu_AUX{_i}"] = ("10k", _FP_R)
for _s in _TAP_SUFFIXES:                                               # E (R1)
    EXPECTED_ADDED_PART_SPECS[f"R_TAPIN_{_s}"] = ("1M", _FP_R)
    EXPECTED_ADDED_PART_SPECS[f"R_TAPPU_{_s}"] = ("10k", _FP_R)
    EXPECTED_ADDED_PART_SPECS[f"Q_TAP_{_s}"] = (f"2N7002 TAP {_s}", _FP_SOT23)
for _s in ("KICK", "ARM", "RPOK"):                                     # E (R1; 555 none by design)
    EXPECTED_ADDED_PART_SPECS[f"R_TAPG_{_s}"] = ("10M", _FP_R)
assert sorted(EXPECTED_ADDED_PART_SPECS) == sorted(EXPECTED_ADDED_TAGS), \
    "EXPECTED_ADDED_PART_SPECS and EXPECTED_ADDED_TAGS moved out of lockstep"

# added net -> exact (tag, pin) membership. RP_PICO pin numbers are the
# remediation-spec R1 GP16-19/GP26 package pins (21/22/24/25/31).
_TAP_RAIL = {"555": ("TAP_NE555_OUT", "21"), "KICK": ("TAP_WDOG_KICK", "22"),
             "ARM": ("TAP_ARM_PERMIT", "24"), "RPOK": ("TAP_RP2040_OK", "25")}
EXPECTED_ADDED_NET_NODES = {
    "ADC_VCC5_SENSE": {("C_ADC5", "1"), ("RP_PICO", "31"),
                       ("R_ADC5_BOT", "1"), ("R_ADC5_TOP", "2")},      # D
}
for _i in range(4, 12):                                                # C: AUX bank
    EXPECTED_ADDED_NET_NODES[f"FIELD_LED_AUX{_i}"] = {
        (f"OPTO_AUX{_i}", "1"), (f"Rin_AUX{_i}", "2")}
    EXPECTED_ADDED_NET_NODES[f"FIELD_SLOW_AUX{_i}"] = {
        ("J_SLOWC", str(_i - 3)), (f"OPTO_AUX{_i}", "2")}
    EXPECTED_ADDED_NET_NODES[f"SLOW_AUX{_i}"] = {
        ("MCP_IN_B", str(_i - 3)), (f"OPTO_AUX{_i}", "4"), (f"Rpu_AUX{_i}", "2")}
for _s, (_tapnet, _pico_pin) in _TAP_RAIL.items():                     # E (R1)
    # open-drain output node: Q drain (SOT-23 pin 3) + 10k pull-up + Pico GPIO
    EXPECTED_ADDED_NET_NODES[_tapnet] = {
        (f"Q_TAP_{_s}", "3"), ("RP_PICO", _pico_pin), (f"R_TAPPU_{_s}", "2")}
    _gate = {(f"Q_TAP_{_s}", "1"), (f"R_TAPIN_{_s}", "2")}
    if _s != "555":
        _gate.add((f"R_TAPG_{_s}", "1"))     # 10M gate bleed (555 has none)
    EXPECTED_ADDED_NET_NODES[f"TAP_GATE_{_s}"] = _gate
assert sorted(EXPECTED_ADDED_NET_NODES) == sorted(EXPECTED_ADDED_NETS), \
    "EXPECTED_ADDED_NET_NODES and EXPECTED_ADDED_NETS moved out of lockstep"

# touched rev-C net -> the exact set of nodes rev-D ADDS to it (losses are
# forbidden outright by the base check).
EXPECTED_TOUCHED_NET_ADDITIONS = {
    "FIELD_GND": {("J_SLOWC", "9"), ("J_SLOWC", "10"),
                  ("R_WET_BLEED1", "2"), ("R_WET_BLEED2", "2")},
    "FIELD_WET_V": ({("R_WET_BLEED1", "1"), ("R_WET_BLEED2", "1")}
                    | {(f"Rin_AUX{i}", "1") for i in range(4, 12)}),
    "VCC_5V": {("J_EXTI2C", "1"), ("R_ADC5_TOP", "1")},
    "GND": ({("C_ADC5", "2"), ("J_EXTI2C", "2"), ("J_EXTI2C", "6"),
             ("R_ADC5_BOT", "2")}
            | {(f"OPTO_AUX{i}", "3") for i in range(4, 12)}
            | {(f"Q_TAP_{s}", "2") for s in _TAP_SUFFIXES}
            | {(f"R_TAPG_{s}", "2") for s in ("KICK", "ARM", "RPOK")}),
    "VCC_3V3": ({("J_EXTI2C", "5")}
                | {(f"R_TAPPU_{s}", "1") for s in _TAP_SUFFIXES}
                | {(f"Rpu_AUX{i}", "1") for i in range(4, 12)}),
    "I2C_SDA": {("J_EXTI2C", "3")},
    "I2C_SCL": {("J_EXTI2C", "4")},
    "NE555_OUT": {("R_TAPIN_555", "1")},
    "WDOG_KICK": {("R_TAPIN_KICK", "1")},
    "ARM_PERMIT": {("R_TAPIN_ARM", "1")},
    "RP2040_OK": {("R_TAPIN_RPOK", "1")},
}
assert set(EXPECTED_TOUCHED_NET_ADDITIONS) == ALLOWED_TOUCHED_NETS, \
    "EXPECTED_TOUCHED_NET_ADDITIONS and ALLOWED_TOUCHED_NETS moved out of lockstep"

# Documented rev-C part value/footprint changes (still reported as
# CHANGED_PART lines, but not PROBLEMs).
#  - D_PROT: spec §H.4 / run-log FR-3: SS14 (1 A) -> SS34 (3 A, MDD C8678,
#    same D_SMA footprint) — rev-D worst case 0.73-0.93 A + J16's 100 mA
#    module allowance exceeds SS14's rating.
#  - MCV connectors (remediation spec R2.5, Codex M4, run-log FR-9): all
#    MCV 1,5 G-3.5 instances repoint to the project-local _D1.4 footprints
#    (drill 1.4 mm per the Phoenix drilling plan, pad 2.0x3.6). Value
#    unchanged; footprint string only.
def _mcv(n: int) -> tuple[str, str]:
    base = f"PhoenixContact_MCV_1,5_{n}-G-3.5_1x{n:02d}_P3.50mm_Vertical"
    return (f"Connector_Phoenix_MC:{base}", f"wsl_footprints:{base}_D1.4")


ALLOWED_CHANGED_PARTS = {
    "D_PROT": {("SS14", "Diode_SMD:D_SMA"): ("SS34", "Diode_SMD:D_SMA")},
}
for _tag, _val, _n in (("J_FAST", "J_FAST_IN", 10), ("J_SLOWA", "J_SLOW_IN_A", 14),
                       ("J_SLOWB", "J_SLOW_IN_B", 12), ("J_LAMP", "J_LAMP_LED", 6),
                       ("J_SAFE", "J_SAFETY", 4)):
    _old, _new = _mcv(_n)
    ALLOWED_CHANGED_PARTS[_tag] = {(_val, _old): (_val, _new)}


def parse(path):
    text = open(path, encoding="utf-8").read()
    comps = {}   # tag -> (ref, value, footprint)
    ref2tag = {}
    for m in re.finditer(
            r'\(comp\s+\(ref "(?P<ref>[^"]+)"\)\s+\(value "(?P<val>[^"]*)"\).*?'
            r'\(footprint "(?P<fp>[^"]*)"\)(?P<rest>.*?)\(tstamps',
            text, re.S):
        tag_m = re.search(r'\(name "SKiDL Tag"\) "([^"]*)"', m.group("rest"))
        tag = tag_m.group(1) if tag_m else m.group("ref")
        comps[tag] = (m.group("ref"), m.group("val"), m.group("fp"))
        ref2tag[m.group("ref")] = tag

    nets = {}    # name -> set of (tag, pin)
    nets_text = text[text.index("(nets"):]
    for block in re.split(r'\(net\s+\(code\s', nets_text)[1:]:
        name = re.search(r'\(name "([^"]*)"\)', block).group(1)
        nodes = set()
        for nm in re.finditer(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', block):
            nodes.add((ref2tag.get(nm.group(1), nm.group(1)), nm.group(2)))
        nets[name] = nodes
    return comps, nets


def main():
    c_comps, c_nets = parse(REVC)
    d_comps, d_nets = parse(REVD)

    lines = []
    problems = []

    lines.append("# Netlist diff: rev-C (kicad/wsl-phase8b.net) -> rev-D (kicad/wsl-phase8b-revD.net)")
    lines.append("# Generated by scripts/diff_netlist_revC_to_revD.py. Identity = SKiDL tag.")
    lines.append("# Format: TAB-separated records; first field is the record type.")
    lines.append(f"SUMMARY\tparts_revC={len(c_comps)}\tparts_revD={len(d_comps)}\tnets_revC={len(c_nets)}\tnets_revD={len(d_nets)}")

    # ---- parts ----
    added_tags = sorted(set(d_comps) - set(c_comps))
    removed_tags = sorted(set(c_comps) - set(d_comps))
    for t in added_tags:
        ref, val, fp = d_comps[t]
        lines.append(f"ADDED_PART\t{t}\t{ref}\t{val}\t{fp}")
    for t in removed_tags:
        ref, val, fp = c_comps[t]
        lines.append(f"REMOVED_PART\t{t}\t{ref}\t{val}\t{fp}")
        problems.append(f"rev-C part removed: {t}")

    changed_parts = []
    shifts = []
    for t in sorted(set(c_comps) & set(d_comps)):
        cref, cval, cfp = c_comps[t]
        dref, dval, dfp = d_comps[t]
        if (cval, cfp) != (dval, dfp):
            changed_parts.append(t)
            lines.append(f"CHANGED_PART\t{t}\t{cval}|{cfp}\t->\t{dval}|{dfp}")
            if ALLOWED_CHANGED_PARTS.get(t, {}).get((cval, cfp)) == (dval, dfp):
                lines.append(f"NOTE\tdocumented change (D_PROT: spec H.4/FR-3; MCV _D1.4: remediation R2.5/FR-9): {t}")
            else:
                problems.append(f"rev-C part value/footprint changed: {t}")
        if cref != dref:
            shifts.append(f"REFDES_SHIFT\t{t}\t{cref}\t{dref}")
    lines.extend(shifts)

    if sorted(added_tags) != sorted(EXPECTED_ADDED_TAGS):
        problems.append(f"added-part set != spec expectation: extra={sorted(set(added_tags)-set(EXPECTED_ADDED_TAGS))} missing={sorted(set(EXPECTED_ADDED_TAGS)-set(added_tags))}")

    # ---- M1 deep check 1: every added part's exact value + footprint ----
    deep_part_ok = 0
    for t in added_tags:
        exp = EXPECTED_ADDED_PART_SPECS.get(t)
        if exp is None:
            continue    # already a PROBLEM via the set comparison above
        _ref, val, fp = d_comps[t]
        if (val, fp) != exp:
            lines.append(f"DEEP_PART_MISMATCH\t{t}\tgot {val}|{fp}\texpected {exp[0]}|{exp[1]}")
            problems.append(f"added part {t} value/footprint != expected-delta table: "
                            f"got ({val!r}, {fp!r}) expected {exp}")
        else:
            deep_part_ok += 1
    lines.append(f"DEEP_PART_CHECK\t{deep_part_ok}/{len(EXPECTED_ADDED_PART_SPECS)} added parts match value+footprint")

    # ---- nets ----
    added_nets = sorted(set(d_nets) - set(c_nets))
    removed_nets = sorted(set(c_nets) - set(d_nets))
    for n in added_nets:
        nodes = " ".join(f"{t}.{p}" for t, p in sorted(d_nets[n]))
        lines.append(f"ADDED_NET\t{n}\t{nodes}")
    for n in removed_nets:
        lines.append(f"REMOVED_NET\t{n}")
        problems.append(f"rev-C net removed: {n}")
    if sorted(added_nets) != sorted(EXPECTED_ADDED_NETS):
        problems.append(f"added-net set != spec expectation: extra={sorted(set(added_nets)-set(EXPECTED_ADDED_NETS))} missing={sorted(set(EXPECTED_ADDED_NETS)-set(added_nets))}")

    # ---- M1 deep check 2: every added net's exact (tag, pin) membership ----
    deep_net_ok = 0
    for n in added_nets:
        exp_nodes = EXPECTED_ADDED_NET_NODES.get(n)
        if exp_nodes is None:
            continue    # already a PROBLEM via the set comparison above
        if d_nets[n] != exp_nodes:
            extra = sorted(d_nets[n] - exp_nodes)
            missing = sorted(exp_nodes - d_nets[n])
            lines.append(f"DEEP_NET_MISMATCH\t{n}\textra={extra}\tmissing={missing}")
            problems.append(f"added net {n} pad membership != expected-delta table: "
                            f"extra={extra} missing={missing}")
        else:
            deep_net_ok += 1
    lines.append(f"DEEP_NET_CHECK\t{deep_net_ok}/{len(EXPECTED_ADDED_NET_NODES)} added nets match pad membership")

    unchanged = 0
    deep_touch_ok = 0
    for n in sorted(set(c_nets) & set(d_nets)):
        plus = sorted(d_nets[n] - c_nets[n])
        minus = sorted(c_nets[n] - d_nets[n])
        if not plus and not minus:
            unchanged += 1
            continue
        plus_s = " ".join(f"+{t}.{p}" for t, p in plus)
        minus_s = " ".join(f"-{t}.{p}" for t, p in minus)
        lines.append(f"CHANGED_NET\t{n}\t{(plus_s + ' ' + minus_s).strip()}")
        if n not in ALLOWED_TOUCHED_NETS:
            problems.append(f"undocumented rev-C net touched: {n} (+{plus} -{minus})")
        if minus:
            problems.append(f"touch-point net LOST rev-C nodes: {n} -{minus}")
        # ---- M1 deep check 3: exact ADDED nodes on each touched net ----
        exp_plus = EXPECTED_TOUCHED_NET_ADDITIONS.get(n)
        if exp_plus is not None:
            if set(plus) != exp_plus:
                extra = sorted(set(plus) - exp_plus)
                missing = sorted(exp_plus - set(plus))
                lines.append(f"DEEP_TOUCH_MISMATCH\t{n}\textra={extra}\tmissing={missing}")
                problems.append(f"touched net {n} additions != expected-delta table: "
                                f"extra={extra} missing={missing}")
            else:
                deep_touch_ok += 1
    # a touch-point net whose documented additions never arrived at all
    for n, exp_plus in sorted(EXPECTED_TOUCHED_NET_ADDITIONS.items()):
        if exp_plus and n in c_nets and n in d_nets and d_nets[n] == c_nets[n]:
            problems.append(f"touch-point net {n} expected additions "
                            f"{sorted(exp_plus)} but was untouched")
    lines.append(f"DEEP_TOUCH_CHECK\t{deep_touch_ok}/{len(EXPECTED_TOUCHED_NET_ADDITIONS)} touched nets match exact additions")

    touched = [l.split("\t")[1] for l in lines if l.startswith("CHANGED_NET")]
    untouched_allowed = sorted(ALLOWED_TOUCHED_NETS - set(touched))
    lines.append(f"UNCHANGED_NETS\t{unchanged}")
    lines.append(f"TOUCHED_NETS\t{len(touched)}\t{' '.join(sorted(touched))}")
    if untouched_allowed:
        lines.append(f"NOTE\tallowed-touch nets not actually touched: {' '.join(untouched_allowed)}")

    for p in problems:
        lines.append(f"PROBLEM\t{p}")
    lines.append("RESULT\t" + ("CLEAN - all deltas match docs/phase8_revD_change_spec.md" if not problems
                               else f"{len(problems)} PROBLEM(S)"))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWROTE {OUT}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
