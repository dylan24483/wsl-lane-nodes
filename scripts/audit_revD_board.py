#!/usr/bin/env python3
"""
Rev-D topological audit (COPY of scripts/audit_revB_board.py — the rev-C
auditor is SACRED and untouched). Contract: docs/phase8_revD_change_spec.md
§H.1/§I.6. Fails closed, same as rev-C.

Expected rev-D class counts (spec delta table + remediation spec R1.7 +
round-2 remediation R2-4/R2-6 — extend apply_netclasses_revD.py in
LOCKSTEP with these):
    Logic_Signal 103 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 82 /
    Machine_Output 21  = 223 nets total, 271 parts.
    (2026-07-21 R1: -5 resistive tap parts, +15 unidirectional tap-stage
    parts, +4 TAP_GATE_* nets -> Logic_Signal 93->97.
    2026-07-21 round 2 (Codex R2-4/R2-6): +9 parts (J16 protection stack +
    REV_ID straps), +6 Logic_Signal nets (J16_5V/J16_3V3/J16_SDA/J16_SCL/
    REV_ID0/REV_ID1) -> Logic_Signal 97->103.)
A Safety_Rail count != 13 is an automatic stop-ship (spec §E — the rev-D spin
adds ZERO safety-rail copper; SAFE_* taps are FMEA-gated out of scope).

Two modes, selected by the input file extension:

  BOARD mode (.kicad_pcb) — the original pcbnew audit, updated counts, plus
  the SAFE_-membership guard. Runs under KiCad 10's bundled python:
    & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\audit_revD_board.py kicad\\wsl-phase8b-revD.routed-manual.kicad_pcb

  NETLIST mode (.net) — the subset of checks provable from the SKiDL netlist
  alone (class classification counts, anonymous nets, rail topology, Pico
  isolation, GND/FIELD_GND separation, SAFE_ membership, DNP survey, the new
  rev-D channels). Pure python, no pcbnew:
    py -3 scripts\\audit_revD_board.py kicad\\wsl-phase8b-revD.net

Checks carried from rev-C: the 5 net classes actually assigned/assignable
(else the .dru hasNetclass() isolation rules are vacuous), safety rail reaches
all 7 relay coils + pass-FET, no machine OUT_* net touches the Pico, GND /
FIELD_GND distinct with zero shared nodes (only the TMA-0505S straddles them),
SAFE_* + RAIL_GATE present, M1 channel still DNP.
New rev-D checks: EXACT SAFE_-net pad membership (no new pads beyond rev-C —
guards spec §E scope), ADC_VCC5_SENSE on Pico GP26 (pin 31), TAP_ nets on
Pico pins 21/22/24/25, J15/J16 identity, 271-part / 223-net totals, the
round-2 J16 protection-stack membership (J16 never directly on a rail/bus)
and the REV_ID strap encoding (rev-D = 0b01).
"""
import sys
import collections
import re

EXPECTED = {"Logic_Signal": 103, "Logic_Power": 4, "Safety_Rail": 13,
            "Field_Sense": 82, "Machine_Output": 21}
EXPECTED_NETS = 223
EXPECTED_PARTS = 271
# Board-level extras added by place_components_revD.py, NOT in the netlist
# (same pattern as rev-C: the routed-manual board has 236 = 216 + 16 TP + 4 MK).
# Round-2 remediation R2-5: +8 tap probe/fault-injection pads (TP17-TP24,
# one gate + one drain pad per tap stage) -> 24 test pads.
EXPECTED_TESTPADS = 24
EXPECTED_MOUNTING = 4
EXPECTED_OPTO_PULLUPS = {f"R{n}" for n in range(4, 83, 2)}

# --pre-route: placement-stage board (no routing yet). Route-stage checks
# (copper zone fills) are reported as WARN-expected instead of FAIL; every
# topological/netclass/membership check still fails closed.
PRE_ROUTE = False

fails = []
def need(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond: fails.append(msg)


# ---- rev-D net classifier (rev-C rules + the two spec §H.1 edits:
#      exact 'ADC_VCC5_SENSE' -> Logic_Signal, prefix 'TAP_' -> Logic_Signal).
#      Keep apply_netclasses_revD.py's classify_net() in LOCKSTEP with this.
LOGIC_POWER = {"VCC_5V", "VCC_5V_RAW", "VCC_3V3", "GND"}
LOGIC_EXACT = {
    "RP2040_OK",
    "ARM_PERMIT",
    "WDOG_TIMING_NODE",
    "BASE_S",
    "BASE_T",
    "BASE_SP",
    "BASE_BE",
    "BASE_M",
    "BASE_M2",
    "BASE_M1",
    "ADC_VCC5_SENSE",   # rev-D item D
}
SAFETY_EXACT = {"RELAY_ENABLE_RAIL", "RAIL_GATE"}

def classify_net(net_name):
    hits = []
    if net_name in LOGIC_POWER:
        hits.append("Logic_Power")
    if (net_name in SAFETY_EXACT
            or net_name.startswith("COIL_LO_")
            or net_name.startswith("BASE_AND_")
            or net_name.startswith("SAFE_")):
        hits.append("Safety_Rail")
    if net_name.startswith("FIELD_"):
        hits.append("Field_Sense")
    if (net_name.startswith("OUT_")
            or net_name.startswith("SNUB_")):
        hits.append("Machine_Output")
    if (net_name in LOGIC_EXACT
            or net_name.startswith("FAST_")
            or net_name.startswith("SLOW_")
            or net_name.startswith("DRV_")
            or net_name.startswith("I2C_")
            or net_name.startswith("PI_UART_")
            or net_name.startswith("MCP_INT_")
            or net_name.startswith("LED_")
            or net_name.startswith("NE555_")
            or net_name.startswith("WDOG_KICK")
            or net_name.startswith("WDOG_OK")
            or net_name.startswith("AND_")
            or net_name.startswith("TAP_")     # rev-D item E
            or net_name.startswith("J16_")     # round-2 R2-4 protected J16 nets
            or net_name.startswith("REV_ID")): # round-2 R2-6 revision straps
        hits.append("Logic_Signal")
    return hits


def audit_common(net_pads, pico_ref, comp_info=None, board_mode=False):
    """Checks shared by both modes. net_pads: net -> [(ref, pad)].
    comp_info (netlist mode only): ref -> (value, footprint, tag).
    board_mode: the physical board additionally carries the rev-C test-pad
    set; SAFE_STOP_RETURN legitimately gains TP15 there (verified against
    kicad/wsl-phase8b.routed-manual.kicad_pcb ground truth 2026-07-19:
    SAFE_STOP_RETURN = J14.4 + Q14.2 + R106.1 + TP15.1)."""

    names = sorted(n for n in net_pads if n)
    anon = [n for n in names if n.startswith("N$")]
    need(len(anon) == 0, f"no anonymous N$ nets (found {len(anon)})")

    # ---- classifier-based class counts (netlist truth; the board carries the
    #      persisted assignments which board mode re-checks via pcbnew) ----
    cls = collections.Counter()
    unknown, overlap = [], []
    for n in names:
        hits = classify_net(n)
        if len(hits) == 1:
            cls[hits[0]] += 1
        elif not hits:
            unknown.append(n)
        else:
            overlap.append((n, hits))
    print(f"[netclass] {dict(cls)}")
    print(f"[netclass] expected {EXPECTED}")
    need(not unknown, f"no unclassifiable nets (found {unknown})")
    need(not overlap, f"no overlapping-class nets (found {overlap})")
    for k, v in EXPECTED.items():
        need(cls.get(k, 0) == v, f"  class {k} = {v} (got {cls.get(k, 0)})")
    need(cls.get("Safety_Rail", 0) == 13,
         "STOP-SHIP GUARD: Safety_Rail count is EXACTLY 13 (rev-D adds zero safety copper)")
    need(len(names) == EXPECTED_NETS, f"total named nets = {EXPECTED_NETS} (got {len(names)})")

    # ---- safety rail reaches all 7 relay coils + pass-FET ----
    rail = net_pads.get("RELAY_ENABLE_RAIL", [])
    rail_refs = sorted(set(r for r, _ in rail))
    krelays = sorted(r for r in rail_refs if r.startswith("K"))
    print(f"[rail] RELAY_ENABLE_RAIL pads={len(rail)} relays={krelays}")
    print(f"[rail] all refs on rail: {rail_refs}")
    need(len(krelays) == 7, f"safety rail reaches 7 relay coils (got {len(krelays)}: {krelays})")
    need(any(r.startswith("Q") for r in rail_refs), "safety rail reaches a pass-FET (Q*)")

    # ---- no machine output on the Pico ----
    out_on_pico = [(n, r, p) for n, pads in net_pads.items() if n.startswith("OUT_")
                   for r, p in pads if r == pico_ref]
    need(not out_on_pico, f"no OUT_* net touches the Pico (violations: {out_on_pico})")

    # ---- isolation: GND vs FIELD_GND distinct, zero shared nodes ----
    need("GND" in net_pads and "FIELD_GND" in net_pads, "GND and FIELD_GND both present + distinct")
    print(f"[iso] GND pads={len(net_pads.get('GND', []))} FIELD_GND pads={len(net_pads.get('FIELD_GND', []))}")
    gnd_refs = set(r for r, _ in net_pads.get("GND", []))
    fgnd_refs = set(r for r, _ in net_pads.get("FIELD_GND", []))
    straddle = sorted(gnd_refs & fgnd_refs)
    print(f"[iso] refs on BOTH GND and FIELD_GND: {straddle}")
    if comp_info is not None:
        ok = all("TMA" in (comp_info.get(r, ("", "", ""))[1] or "") for r in straddle)
    else:
        ok = len(straddle) <= 1
    need(ok and len(straddle) == 1,
         f"only the TMA-0505S isolation converter straddles GND/FIELD_GND (got {straddle})")

    # ---- SAFE_ nets: present AND membership frozen at rev-C (guards spec §E scope) ----
    for n in ("SAFE_STOP_RETURN", "SAFE_TBSC_RETURN", "RAIL_GATE", "ARM_PERMIT", "RP2040_OK"):
        print(f"[safety] {n}: {net_pads.get(n, [])}")
    need(all(n in net_pads for n in ("SAFE_STOP_RETURN", "SAFE_TBSC_RETURN", "RAIL_GATE")),
         "SAFE_STOP_RETURN + SAFE_TBSC_RETURN + RAIL_GATE present")
    tbsc = net_pads.get("SAFE_TBSC_RETURN", [])
    need(len(tbsc) == 2 and all(r.startswith("J") for r, _ in tbsc),
         f"SAFE_TBSC_RETURN pad membership frozen at rev-C: exactly 2 pads, both on J_SAFETY (got {tbsc})")
    stop = net_pads.get("SAFE_STOP_RETURN", [])
    if board_mode:
        # rev-C BOARD ground truth includes the TP15 test pad (see docstring).
        stop_refs = sorted(r for r, _ in stop)
        ok_stop = (len(stop) == 4 and "TP15" in stop_refs
                   and sorted(r[0] for r, _ in stop if r != "TP15") == ["J", "Q", "R"])
        need(ok_stop,
             f"SAFE_STOP_RETURN pad membership frozen at rev-C board: exactly 4 pads (J_SAFETY, pass-FET, gate pullup, TP15) (got {stop})")
    else:
        stop_prefixes = sorted(r[0] for r, _ in stop)
        need(len(stop) == 3 and stop_prefixes == ["J", "Q", "R"],
             f"SAFE_STOP_RETURN pad membership frozen at rev-C: exactly 3 pads (J_SAFETY, pass-FET, gate pullup) (got {stop})")
    gate = net_pads.get("RAIL_GATE", [])
    gate_prefixes = sorted(r[0] for r, _ in gate)
    need(len(gate) == 3 and gate_prefixes == ["Q", "Q", "R"],
         "RAIL_GATE pad membership frozen at rev-C: exactly 3 pads "
         f"(pass-FET gate, AND-chain collector, gate pullup) (got {gate})")

    # ---- rev-D item D/E channels land on the right Pico pins ----
    adc = net_pads.get("ADC_VCC5_SENSE", [])
    need((pico_ref, "31") in [(r, str(p)) for r, p in adc],
         f"ADC_VCC5_SENSE reaches Pico pin 31 (GP26/ADC0) (got {adc})")
    for tap, pin in (("TAP_NE555_OUT", "21"), ("TAP_WDOG_KICK", "22"),
                     ("TAP_ARM_PERMIT", "24"), ("TAP_RP2040_OK", "25")):
        pads = [(r, str(p)) for r, p in net_pads.get(tap, [])]
        need((pico_ref, pin) in pads, f"{tap} reaches Pico pin {pin} (got {pads})")
    # Remediation spec R1 (2026-07-21): each TAP_* drain net carries EXACTLY
    # (2N7002 drain Q, pull-up R, Pico pad) — the GPIO must connect to the
    # FET drain only (the unidirectionality contract, Codex C1). The
    # TAP_GATE_* nets are the ONLY copper touching the observed side and
    # must NEVER reach the Pico.
    # Round-2 remediation R2-5: the physical board adds ONE TestPoint probe
    # pad per tap drain net (TP18/20/22/24) and per tap gate net
    # (TP17/19/21/23) — board mode tolerates exactly one TP ref extra.
    for tap in ("TAP_NE555_OUT", "TAP_WDOG_KICK", "TAP_ARM_PERMIT", "TAP_RP2040_OK"):
        pads = net_pads.get(tap, [])
        core = [(r, p) for r, p in pads if not r.startswith("TP")]
        tp_n = len(pads) - len(core)
        prefixes = sorted(r[0] for r, _ in core)
        ok = len(core) == 3 and prefixes == sorted(["Q", "R", pico_ref[0]])
        if board_mode:
            ok = ok and tp_n == 1
            need(ok, f"{tap} carries exactly (FET drain, pull-up R, Pico) + 1 probe TP (got {pads})")
        else:
            ok = ok and tp_n == 0
            need(ok, f"{tap} carries exactly (FET drain, pull-up R, Pico) pads (got {pads})")
    for gate in ("TAP_GATE_555", "TAP_GATE_KICK", "TAP_GATE_ARM", "TAP_GATE_RPOK"):
        pads = net_pads.get(gate, [])
        core = [(r, p) for r, p in pads if not r.startswith("TP")]
        tp_n = len(pads) - len(core)
        refs = sorted(set(r for r, _ in core))
        expected_n = 2 if gate == "TAP_GATE_555" else 3  # 555 tap has no R_TAPG by design
        ok = (gate in net_pads and len(core) == expected_n
              and all(r.startswith(("R", "Q")) for r in refs)
              and pico_ref not in refs
              and tp_n == (1 if board_mode else 0))
        need(ok, f"{gate} carries only R_TAPIN(/R_TAPG) + FET gate"
                 + (" + 1 probe TP" if board_mode else "")
                 + f", never the Pico (got {pads})")

    # ---- round-2 remediation (Codex R2-4): J16 protection-stack topology.
    #      Fail-closed exact membership — the connector must NEVER regain a
    #      direct rail/bus connection. Refs are stable generation order
    #      (F1 polyfuse, JP1 solder link, U46 TCA4307, U47 SRV05-4,
    #      R142/R143 card-side pull-ups). ----
    def members(net):
        return sorted((r, str(p)) for r, p in net_pads.get(net, []))
    # Round-3 (Codex 2026-07-21 PM, finding 2): ESD VP moved UPSTREAM of the
    # polyfuse (VCC_5V) — VP on the fused node was an unfused sneak path from
    # VCC_3V3 through IO1's steering diode when JP1 is bridged. The fused pin
    # keeps ESD protection via the previously-spare IO3 channel (U47.4).
    need(members("J16_5V") == sorted([("F1", "2"), ("J16", "1"), ("U47", "4")]),
         f"J16_5V is exactly polyfuse-out + J16.1 + ESD IO3 (got {members('J16_5V')})")
    need([(r, str(p)) for r, p in net_pads.get("VCC_5V", []) if r == "U47"] == [("U47", "5")],
         "ESD VP (U47.5) rides VCC_5V UPSTREAM of the polyfuse — round-3 sneak-path fix")
    need(members("J16_3V3") == sorted([("JP1", "2"), ("J16", "5"), ("U47", "1")]),
         f"J16_3V3 is exactly solder-link-out + J16.5 + ESD IO (default-OPEN pin) (got {members('J16_3V3')})")
    need(members("J16_SDA") == sorted([("U46", "7"), ("R142", "2"), ("J16", "3"), ("U47", "3")]),
         f"J16_SDA is exactly TCA4307 SDAOUT + pull-up + J16.3 + ESD IO (got {members('J16_SDA')})")
    need(members("J16_SCL") == sorted([("U46", "2"), ("R143", "2"), ("J16", "4"), ("U47", "6")]),
         f"J16_SCL is exactly TCA4307 SCLOUT + pull-up + J16.4 + ESD IO (got {members('J16_SCL')})")
    for raw_net in ("VCC_5V", "VCC_3V3", "I2C_SDA", "I2C_SCL"):
        on_j16 = [(r, p) for r, p in net_pads.get(raw_net, []) if r == "J16"]
        need(not on_j16,
             f"{raw_net} never touches J16 directly (protection stack bypass!) (got {on_j16})")
    need([(r, str(p)) for r, p in net_pads.get("I2C_SDA", []) if r == "U46"] == [("U46", "6")]
         and [(r, str(p)) for r, p in net_pads.get("I2C_SCL", []) if r == "U46"] == [("U46", "3")],
         "TCA4307 main-bus side is exactly SDAIN(6)/SCLIN(3) — in/out not swapped")

    # ---- round-2 remediation (Codex R2-6): REV_ID straps. rev-D = 0b01:
    #      REV_ID0 (GP20, pin 26) strapped HIGH, REV_ID1 (GP21, pin 27) LOW. ----
    need(members("REV_ID0") == sorted([("R144", "2"), (pico_ref, "26")]),
         f"REV_ID0 is exactly strap R144 + Pico pin 26/GP20 (got {members('REV_ID0')})")
    need(members("REV_ID1") == sorted([("R145", "2"), (pico_ref, "27")]),
         f"REV_ID1 is exactly strap R145 + Pico pin 27/GP21 (got {members('REV_ID1')})")
    r144_rail = [(r, str(p)) for r, p in net_pads.get("VCC_3V3", []) if r == "R144"]
    r145_rail = [(r, str(p)) for r, p in net_pads.get("GND", []) if r == "R145"]
    need(r144_rail == [("R144", "1")] and r145_rail == [("R145", "1")],
         "REV_ID encoding is rev-D = 0b01 (R144 pulls HIGH, R145 pulls LOW)")


def audit_netlist(path):
    text = open(path, encoding="utf-8").read()

    # components: ref/value/footprint/tag
    comp_info = {}
    for m in re.finditer(
            r'\(comp\s+\(ref "(?P<ref>[^"]+)"\)\s+\(value "(?P<val>[^"]*)"\).*?'
            r'\(footprint "(?P<fp>[^"]*)"\)(?P<rest>.*?)\(tstamps',
            text, re.S):
        tag_m = re.search(r'\(name "SKiDL Tag"\) "([^"]*)"', m.group("rest"))
        comp_info[m.group("ref")] = (m.group("val"), m.group("fp"),
                                     tag_m.group(1) if tag_m else "")
    print(f"[netlist] components={len(comp_info)}")
    need(len(comp_info) == EXPECTED_PARTS,
         f"part count = {EXPECTED_PARTS} (got {len(comp_info)})")

    pico_ref = next((r for r, (v, fp, t) in comp_info.items() if "Pico" in fp or "Pico" in v), None)
    print(f"[netlist] Pico ref = {pico_ref}")
    need(pico_ref is not None, "Pico module present")

    # nets -> nodes (SKiDL 2.2.3 emits (code N) unquoted, one attr per line)
    net_pads = collections.defaultdict(list)
    nets_text = text[text.index("(nets"):]
    for block in re.split(r'\(net\s+\(code\s', nets_text)[1:]:
        name = re.search(r'\(name "([^"]*)"\)', block).group(1)
        for nm in re.finditer(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', block):
            net_pads[name].append((nm.group(1), nm.group(2)))
    print(f"[netlist] nets={len(net_pads)}")

    # ---- J15/J16 identity (SKiDL assigns refdes by instantiation order) ----
    j15 = comp_info.get("J15", ("", "", ""))
    j16 = comp_info.get("J16", ("", "", ""))
    need(j15[0] == "J_SLOW_IN_C" and j15[2] == "J_SLOWC",
         f"J15 is J_SLOW_IN_C (tag J_SLOWC) (got value={j15[0]!r} tag={j15[2]!r})")
    need(j16[0] == "J_EXT_I2C" and j16[2] == "J_EXTI2C",
         f"J16 is J_EXT_I2C (tag J_EXTI2C) (got value={j16[0]!r} tag={j16[2]!r})")

    # Rev-D input-margin hardening: tags prove the value change is limited
    # to the 40 optocoupler collector pull-ups.
    rpu = {r for r, (v, fp, t) in comp_info.items() if t.startswith("Rpu_")}
    wrong_rpu = sorted((r, comp_info[r][0]) for r in rpu if comp_info[r][0] != "47k")
    other_47k = sorted(r for r, (v, fp, t) in comp_info.items()
                       if v == "47k" and not t.startswith("Rpu_"))
    need(rpu == EXPECTED_OPTO_PULLUPS,
         f"exactly 40 Rpu_* refs are R4,R6,...,R82 (got {sorted(rpu)})")
    need(not wrong_rpu, f"every Rpu_* value is 47k (wrong: {wrong_rpu})")
    need(not other_47k, f"no unrelated component was changed to 47k (got {other_47k})")

    # ---- M1 channel + arc suppression still DNP (by value marker) ----
    dnp = sorted(r for r, (v, fp, t) in comp_info.items() if "DNP" in v)
    print(f"[dnp] count={len(dnp)} {dnp}")
    need(len(dnp) >= 8, f"M1 channel still DNP (>=8 DNP-marked parts, found {len(dnp)})")
    k_m1 = next((r for r, (v, fp, t) in comp_info.items() if t == "K_M1"), None)
    need(k_m1 in dnp, f"K_M1 relay itself is DNP (ref {k_m1})")

    audit_common(net_pads, pico_ref, comp_info)


def audit_board(path):
    import pcbnew
    board = pcbnew.LoadBoard(path)

    def MM(iu):
        try: return round(pcbnew.ToMM(iu), 2)
        except Exception: return iu

    bb = board.GetBoardEdgesBoundingBox()
    print(f"[board] {MM(bb.GetWidth())} x {MM(bb.GetHeight())} mm, "
          f"{board.GetCopperLayerCount()} cu layers, nets={board.GetNetCount()}")
    fps = list(board.GetFootprints())
    print(f"[board] footprints={len(fps)}")

    net_pads = collections.defaultdict(list)
    pico = None
    for fp in fps:
        ref = fp.GetReference()
        try: fpid = fp.GetFPID().GetLibItemName().wx_str()
        except Exception: fpid = ""
        if "Pico" in fpid or "Pico" in fp.GetValue():
            pico = ref
        for pad in fp.Pads():
            net_pads[pad.GetNetname()].append((ref, pad.GetPadName()))
    print(f"[board] Pico ref = {pico}")
    # The board carries the 252 netlist parts PLUS board-level test pads and
    # mounting holes (rev-C pattern: 236 = 216 + 16 TP + 4 MK).
    tp_refs = [fp.GetReference() for fp in fps if fp.GetReference().startswith("TP")]
    mk_refs = [fp.GetReference() for fp in fps if fp.GetReference().startswith("MK")]
    netlist_fps = len(fps) - len(tp_refs) - len(mk_refs)
    need(netlist_fps == EXPECTED_PARTS,
         f"netlist-part footprint count = {EXPECTED_PARTS} (got {netlist_fps})")
    need(len(tp_refs) == EXPECTED_TESTPADS and len(mk_refs) == EXPECTED_MOUNTING,
         f"board extras: {EXPECTED_TESTPADS} test pads + {EXPECTED_MOUNTING} mounting holes "
         f"(got {len(tp_refs)} TP, {len(mk_refs)} MK)")
    board_rpu = {fp.GetReference() for fp in fps
                 if fp.GetReference() in EXPECTED_OPTO_PULLUPS and fp.GetValue() == "47k"}
    board_other_47k = sorted(fp.GetReference() for fp in fps
                             if fp.GetValue() == "47k"
                             and fp.GetReference() not in EXPECTED_OPTO_PULLUPS)
    need(board_rpu == EXPECTED_OPTO_PULLUPS,
         f"board has exactly R4,R6,...,R82 as 47k PC817 pull-ups "
         f"(got {sorted(board_rpu)})")
    need(not board_other_47k,
         f"board has no unrelated 47k footprints (got {board_other_47k})")

    # ---- netclass assignments on THIS board (the critical check: without
    #      them the .dru hasNetclass() isolation rules are vacuous) ----
    settings = board.GetDesignSettings().m_NetSettings
    try: settings.RecomputeEffectiveNetclasses()
    except Exception: pass
    names = [str(n) for n in board.GetNetsByName().keys() if str(n)]
    cls = collections.Counter()
    for n in names:
        try: c = settings.GetEffectiveNetClass(n).GetName()
        except Exception: c = "?"
        cls[c] += 1
    print(f"[netclass-board] {dict(cls)}")
    need(cls.get("Default", 0) == 0, f"no named net fell to Default class (found {cls.get('Default', 0)})")
    custom_total = sum(cls.get(k, 0) for k in EXPECTED)
    need(custom_total == len(names),
         f"every named net ({len(names)}) is in a custom class (got {custom_total})")
    for k, v in EXPECTED.items():
        need(cls.get(k, 0) == v, f"  board-assigned class {k} = {v} (got {cls.get(k, 0)})")

    # ---- zones (power planes) ----
    zones = list(board.Zones())
    print(f"[zones] count={len(zones)}")
    filled_ok = True
    filled_copper_zones = 0
    keepout_rule_areas = 0
    for z in zones:
        try: filled = z.IsFilled()
        except Exception: filled = "?"
        try: layer = board.GetLayerName(z.GetLayer())
        except Exception: layer = z.GetLayer()
        try: area = MM(z.GetFilledArea())
        except Exception: area = "?"
        net = z.GetNetname()
        is_rule_area = not net
        print(f"  net={net!r} layer={layer} filled={filled} area_mm2={area} rule_area={is_rule_area}")
        if is_rule_area:
            keepout_rule_areas += 1
            continue
        filled_copper_zones += 1
        if filled is False:
            filled_ok = False
    if PRE_ROUTE:
        print(f"WARN  netted copper zones not yet present/filled ({filled_copper_zones}) - "
              "EXPECTED pre-route; the final routed-board audit (no --pre-route) fails closed on this")
    else:
        need(filled_copper_zones >= 1 and filled_ok, f"netted copper zones are filled ({filled_copper_zones})")
    need(keepout_rule_areas >= 2, f"isolation keepout rule areas present ({keepout_rule_areas})")

    # ---- M1 channel DNP intact ----
    dnp = sorted(fp.GetReference() for fp in fps if (fp.IsDNP() if hasattr(fp, "IsDNP") else False))
    print(f"[dnp] count={len(dnp)} {dnp}")
    need(len(dnp) >= 8, f"M1 channel still DNP (>=8 DNP footprints, found {len(dnp)})")

    # ---- connectivity (independent of the DRC report) ----
    try:
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        try:
            print(f"[conn] GetUnconnectedCount={conn.GetUnconnectedCount(True)}")
        except TypeError:
            print(f"[conn] GetUnconnectedCount={conn.GetUnconnectedCount()}")
    except Exception as e:
        print(f"[conn] {e}")

    audit_common(net_pads, pico, board_mode=True)


def main():
    global PRE_ROUTE
    args = [a for a in sys.argv[1:] if a != "--pre-route"]
    PRE_ROUTE = "--pre-route" in sys.argv[1:]
    path = args[0] if args else "kicad/wsl-phase8b-revD.net"
    print(f"AUDIT INPUT: {path}" + ("  [--pre-route: zone-fill check advisory]" if PRE_ROUTE else ""))
    if path.lower().endswith(".net"):
        audit_netlist(path)
    else:
        audit_board(path)

    print("\nAUDIT RESULT: " + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S)"))
    for f in fails:
        print("  - " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
