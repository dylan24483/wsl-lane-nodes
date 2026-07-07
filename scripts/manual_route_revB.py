#!/usr/bin/env python3
"""
Manual, deterministic routing passes for WSL Phase 8 Rev-B.

This is not a full autorouter. It routes only nets whose geometry is
well-understood from the Rev-B placement bands, then relies on KiCad DRC after
each pass. The intent is to make the "manual route" repeatable and auditable.

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\manual_route_revB.py
"""

from __future__ import annotations

import argparse
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "kicad" / "wsl-phase8b.kicad_pcb"
DEFAULT_OUTPUT = ROOT / "kicad" / "wsl-phase8b.routed-manual.kicad_pcb"

F_CU = pcbnew.F_Cu
B_CU = pcbnew.B_Cu
IN1_CU = pcbnew.In1_Cu
IN2_CU = pcbnew.In2_Cu

NET_RULES = {
    "Logic_Signal": {"width": 0.25, "via": 0.60, "drill": 0.30},
    "Logic_Power": {"width": 0.50, "via": 0.80, "drill": 0.40},
    "Safety_Rail": {"width": 0.60, "via": 0.80, "drill": 0.40},
    "Field_Sense": {"width": 0.30, "via": 0.70, "drill": 0.35},
    "Machine_Output": {"width": 0.50, "via": 1.00, "drill": 0.50},
}
NETCLASS_COUNTS = {
    "Logic_Signal": 80,
    "Logic_Power": 4,
    "Safety_Rail": 13,
    "Field_Sense": 66,
    "Machine_Output": 21,
}

FAST_INPUTS = ["SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R"]
SLOW_A = [f"GS{i}" for i in range(1, 11)] + ["GP", "OS", "BS"]
SLOW_B = [
    "PBZ",
    "PBC",
    "FOUL",
    "TENTH",
    "MAN_T",
    "MAN_S",
    "MAN_SWS",
    "MAN_SWSR",
    "AUX1",
    "AUX2",
    "AUX3",
]
MOTION = ["S", "T", "SP", "BE", "M", "M2", "M1"]
LAMPS = ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]


def mm(value: float) -> int:
    return pcbnew.FromMM(float(value))


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def pt_mm(point: pcbnew.VECTOR2I) -> tuple[float, float]:
    return point.x / 1_000_000.0, point.y / 1_000_000.0


def item_pos(item) -> tuple[float, float]:
    return pt_mm(item.GetPosition())


def net_rule(board: pcbnew.BOARD, net_name: str) -> dict[str, float]:
    settings = board.GetDesignSettings().m_NetSettings
    try:
        settings.RecomputeEffectiveNetclasses()
        cls = settings.GetEffectiveNetClass(net_name).GetName()
    except Exception:
        net = board.FindNet(net_name)
        cls = net.GetNetClassName() if net else "Logic_Signal"
    return NET_RULES.get(cls, NET_RULES["Logic_Signal"])


def copy_project_sidecars(source: Path, output: Path) -> None:
    """Keep the routed board in a KiCad project with the same rules/classes."""
    for suffix in (".kicad_pro", ".kicad_prl", ".kicad_dru"):
        src = source.with_suffix(suffix)
        if src.exists():
            shutil.copy2(src, output.with_suffix(suffix))


def assert_netclasses_active(board: pcbnew.BOARD) -> None:
    """Fail closed if KiCad did not load the Rev-B project netclass map."""
    settings = board.GetDesignSettings().m_NetSettings
    settings.RecomputeEffectiveNetclasses()
    names = [str(n) for n in board.GetNetsByName().keys() if str(n)]
    counts = Counter(settings.GetEffectiveNetClass(n).GetName() for n in names)
    if counts.get("Default", 0):
        raise SystemExit(
            "ERROR: routed project has nets in Default class; "
            f"netclass DRC would be vacuous: {dict(counts)}"
        )
    for class_name, expected in NETCLASS_COUNTS.items():
        actual = counts.get(class_name, 0)
        if actual != expected:
            raise SystemExit(
                f"ERROR: netclass {class_name} expected {expected}, got {actual}; "
                f"all counts={dict(counts)}"
            )


def pads_by_net(board: pcbnew.BOARD) -> dict[str, list[pcbnew.PAD]]:
    nets: dict[str, list[pcbnew.PAD]] = defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                nets[pad.GetNetname()].append(pad)
    return nets


def pad(board: pcbnew.BOARD, ref: str, pin: str) -> pcbnew.PAD:
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        raise KeyError(f"Missing footprint {ref}")
    for candidate in fp.Pads():
        if candidate.GetNumber() == str(pin):
            return candidate
    raise KeyError(f"Missing pad {ref}.{pin}")


def ref_by_value(board: pcbnew.BOARD, value: str) -> str:
    for fp in board.GetFootprints():
        if fp.GetValue() == value:
            return fp.GetReference()
    raise KeyError(f"Missing footprint value {value}")


def by_net_ref_pin(board: pcbnew.BOARD, net_name: str, ref_prefix: str | None = None, pin: str | None = None) -> pcbnew.PAD:
    matches = []
    for candidate in pads_by_net(board)[net_name]:
        ref = candidate.GetParentFootprint().GetReference()
        if ref_prefix and not ref.startswith(ref_prefix):
            continue
        if pin and candidate.GetNumber() != str(pin):
            continue
        matches.append(candidate)
    if len(matches) != 1:
        refs = ", ".join(f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}" for p in matches)
        raise KeyError(f"Expected 1 match for {net_name} {ref_prefix=} {pin=}, got {len(matches)}: {refs}")
    return matches[0]


def clear_tracks(board: pcbnew.BOARD) -> int:
    tracks = list(board.GetTracks())
    for track in tracks:
        board.Remove(track)
    return len(tracks)


def add_track(board: pcbnew.BOARD, net_name: str, start: tuple[float, float], end: tuple[float, float], layer: int, width_mm: float | None = None) -> None:
    if abs(start[0] - end[0]) < 0.001 and abs(start[1] - end[1]) < 0.001:
        return
    rule = net_rule(board, net_name)
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(v(*start))
    track.SetEnd(v(*end))
    track.SetLayer(layer)
    track.SetWidth(mm(width_mm if width_mm is not None else rule["width"]))
    track.SetNet(board.FindNet(net_name))
    board.Add(track)


def add_via(board: pcbnew.BOARD, net_name: str, xy: tuple[float, float]) -> None:
    rule = net_rule(board, net_name)
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(v(*xy))
    via.SetWidth(mm(rule["via"]))
    via.SetDrill(mm(rule["drill"]))
    via.SetLayerPair(F_CU, B_CU)
    via.SetNet(board.FindNet(net_name))
    board.Add(via)


def route_poly(board: pcbnew.BOARD, net_name: str, points: list[tuple[float, float]], layer: int) -> int:
    added = 0
    for a, b in zip(points, points[1:]):
        add_track(board, net_name, a, b, layer)
        added += 1
    return added


def route_pad_to_backbone(
    board: pcbnew.BOARD,
    net_name: str,
    target: pcbnew.PAD,
    backbone_x: float,
    layer: int = B_CU,
) -> int:
    """Join a pad to a vertical backbone.

    PTH pads can be reached directly on the backbone layer. SMD pads need a
    short F.Cu stub to a via placed on the backbone.
    """
    x, y = item_pos(target)
    if target.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
        add_track(board, net_name, (x, y), (backbone_x, y), F_CU)
        add_via(board, net_name, (backbone_x, y))
        return 2
    add_track(board, net_name, (x, y), (backbone_x, y), layer)
    return 1


def add_zone_rect(
    board: pcbnew.BOARD,
    net_name: str,
    layer: int,
    corners: list[tuple[float, float]],
    clearance_mm: float = 0.25,
) -> None:
    zone = pcbnew.ZONE(board)
    zone.SetNet(board.FindNet(net_name))
    zone.SetLayer(layer)
    zone.SetIsRuleArea(False)
    zone.SetAssignedPriority(0)
    zone.SetLocalClearance(mm(clearance_mm))
    poly = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in corners:
        poly.Append(v(x, y))
    poly.SetClosed(True)
    zone.AddPolygon(poly)
    board.Add(zone)


def route_two_layer_dogleg(
    board: pcbnew.BOARD,
    net_name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    channel_x: float,
) -> int:
    """F.Cu horizontal fanout, B.Cu vertical channel, F.Cu horizontal fanin."""
    added = 0
    if abs(start[1] - end[1]) < 0.8:
        add_track(board, net_name, start, end, F_CU)
        return 1
    p1 = (channel_x, start[1])
    p2 = (channel_x, end[1])
    add_track(board, net_name, start, p1, F_CU)
    add_via(board, net_name, p1)
    add_track(board, net_name, p1, p2, B_CU)
    add_via(board, net_name, p2)
    add_track(board, net_name, p2, end, F_CU)
    added += 5
    return added


def route_field_led_series(board: pcbnew.BOARD) -> int:
    added = 0
    nets = [n for n in pads_by_net(board) if n.startswith("FIELD_LED_")]
    for net_name in sorted(nets):
        r = by_net_ref_pin(board, net_name, "R", "2")
        u = by_net_ref_pin(board, net_name, "U", "1")
        start = item_pos(r)
        end = item_pos(u)
        mid = (end[0] - 2.0, start[1])
        added += route_poly(board, net_name, [start, mid, (mid[0], end[1]), end], F_CU)
    return added


def route_field_input_returns(board: pcbnew.BOARD) -> int:
    added = 0
    ordered = [f"FIELD_FAST_{name}" for name in FAST_INPUTS]
    ordered += [f"FIELD_SLOW_{name}" for name in SLOW_A + SLOW_B]
    channel_x = 12.5
    step = 1.25
    channel_override = {
        "FIELD_FAST_DIELL_R": 42.0,
        "FIELD_SLOW_GP": 18.0,
        "FIELD_SLOW_GS1": 42.0,
        "FIELD_SLOW_GS9": 20.0,
        "FIELD_SLOW_OS": 36.25,
        "FIELD_SLOW_AUX1": 30.0,
        "FIELD_SLOW_BS": 53.5,
        "FIELD_SLOW_MAN_SWS": 20.0,
    }
    for i, net_name in enumerate(ordered):
        pads = pads_by_net(board).get(net_name, [])
        if len(pads) != 2:
            continue
        connector = min(pads, key=lambda p: item_pos(p)[0])
        opto = max(pads, key=lambda p: item_pos(p)[0])
        added += route_two_layer_dogleg(board, net_name, item_pos(connector), item_pos(opto), channel_override.get(net_name, channel_x + i * step))
    return added


def route_opto_to_pullups(board: pcbnew.BOARD) -> int:
    added = 0
    for prefix in ("FAST_", "SLOW_"):
        for net_name in sorted(n for n in pads_by_net(board) if n.startswith(prefix)):
            try:
                opto = next(
                    p
                    for p in pads_by_net(board).get(net_name, [])
                    if p.GetNumber() == "4"
                    and p.GetParentFootprint().GetReference().startswith("U")
                    and int(p.GetParentFootprint().GetReference()[1:]) >= 4
                )
                pullup = by_net_ref_pin(board, net_name, "R", "2")
            except (KeyError, StopIteration, ValueError):
                continue
            start = item_pos(opto)
            end = item_pos(pullup)
            # The pullup resistors are horizontal with VCC on pad 1 to the left
            # and the signal on pad 2 to the right. Approach pad 2 from the
            # right side; approaching from the opto side crosses the VCC pad.
            right_x = end[0] + 2.0
            jog_y = end[1] - 1.25 if end[1] > 200 else end[1] + 1.25
            added += route_poly(
                board,
                net_name,
                [start, (start[0] + 2.0, start[1]), (start[0] + 2.0, jog_y), (right_x, jog_y), (right_x, end[1]), end],
                F_CU,
            )
    return added


def route_status_led_cluster(board: pcbnew.BOARD) -> int:
    added = 0
    for name in LAMPS:
        sink = f"LED_SINK_{name}"
        pads = pads_by_net(board).get(sink, [])
        if len(pads) == 2:
            a, b = sorted(pads, key=lambda p: item_pos(p)[1])
            ax, ay = item_pos(a)
            bx, by = item_pos(b)
            via_x = ax + 2.0
            add_track(board, sink, (ax, ay), (via_x, ay), F_CU)
            add_via(board, sink, (via_x, ay))
            add_track(board, sink, (via_x, ay), (via_x, by), B_CU)
            add_via(board, sink, (via_x, by))
            add_track(board, sink, (via_x, by), (bx, by), F_CU)
            added += 5

        ret = f"LED_L_{name[2:]}_RETURN"
        pads = pads_by_net(board).get(ret, [])
        if len(pads) == 2:
            rpad = min(pads, key=lambda p: item_pos(p)[1])
            jpad = max(pads, key=lambda p: item_pos(p)[1])
            rx, ry = item_pos(rpad)
            jx, jy = item_pos(jpad)
            idx = LAMPS.index(name)
            via = (rx - 2.0, ry)
            bus_y = 201.5 + idx * 0.75
            add_track(board, ret, (rx, ry), via, F_CU)
            add_via(board, ret, via)
            add_track(board, ret, via, (via[0], bus_y), B_CU)
            add_track(board, ret, (via[0], bus_y), (jx, bus_y), B_CU)
            add_track(board, ret, (jx, bus_y), (jx, jy), B_CU)
            added += 5

        gate = f"LED_GATE_{name}"
        gpads = sorted(pads_by_net(board).get(gate, []), key=lambda p: item_pos(p)[0])
        if len(gpads) == 3:
            rg, qgate, rpd = gpads
            rgx, rgy = item_pos(rg)
            qx, qy = item_pos(qgate)
            rpdx, rpdy = item_pos(rpd)
            left_x = rgx - 2.0
            right_x = rpdx + 2.0
            join_y = qy
            added += route_poly(board, gate, [(rgx, rgy), (left_x, rgy), (left_x, join_y), (qx, join_y)], F_CU)
            added += route_poly(board, gate, [(rpdx, rpdy), (right_x, rpdy), (right_x, join_y), (qx, join_y)], F_CU)
    return added


def route_relay_driver_locals(board: pcbnew.BOARD) -> int:
    added = 0
    for name in MOTION:
        for net_name in [f"BASE_{name}", f"COIL_LO_{name}"]:
            pads = pads_by_net(board).get(net_name, [])
            if not pads:
                continue
            if net_name.startswith("BASE_") and len(pads) == 2:
                rpad = min(pads, key=lambda p: item_pos(p)[0])
                qpad = max(pads, key=lambda p: item_pos(p)[0])
                rx, ry = item_pos(rpad)
                qx, qy = item_pos(qpad)
                jog_y = min(ry, qy) - 1.35
                added += route_poly(board, net_name, [(rx, ry), (rx, jog_y), (qx, jog_y), (qx, qy)], F_CU)
                continue
            xs = [item_pos(p)[0] for p in pads]
            ys = [item_pos(p)[1] for p in pads]
            trunk_x = 166.8 if net_name.startswith("COIL_LO_") else min(xs) + 2.5
            trunk_y1, trunk_y2 = min(ys), max(ys)
            trunk_layer = IN1_CU if net_name.startswith("COIL_LO_") else F_CU
            added += route_poly(board, net_name, [(trunk_x, trunk_y1), (trunk_x, trunk_y2)], trunk_layer)
            for p in pads:
                x, y = item_pos(p)
                if net_name.startswith("COIL_LO_") and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    add_via(board, net_name, (trunk_x, y))
                    added += 1
                    added += route_poly(board, net_name, [(x, y), (trunk_x, y)], F_CU)
                else:
                    added += route_poly(board, net_name, [(x, y), (trunk_x, y)], trunk_layer)
    return added


def route_safety_rail_spine(board: pcbnew.BOARD) -> int:
    added = 0
    rail = "RELAY_ENABLE_RAIL"
    pads = pads_by_net(board).get(rail, [])
    if not pads:
        return 0
    trunk_x = 160.0
    ys = [item_pos(p)[1] for p in pads]
    y1, y2 = min(ys), max(ys)
    added += route_poly(board, rail, [(trunk_x, y1), (trunk_x, y2)], B_CU)
    for p in pads:
        x, y = item_pos(p)
        jog = (trunk_x, y)
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            add_via(board, rail, jog)
            added += 1
            added += route_poly(board, rail, [item_pos(p), jog], F_CU)
        else:
            ref = p.GetParentFootprint().GetReference()
            if ref.startswith("K"):
                # The corrected G5LE-14 coil-high pad is K*.2 at the same Y as
                # the coil-low driver via row. Dogleg the rail branch around
                # those through-vias so the two coil nets never share copper.
                x, y = item_pos(p)
                dogleg_y = y + 3.0
                added += route_poly(board, rail, [jog, (trunk_x, dogleg_y), (x, dogleg_y), (x, y)], B_CU)
            else:
                added += route_poly(board, rail, [item_pos(p), jog], B_CU)

    # The two-node TB/SC safety loop is intentionally just adjacent J8 pins.
    pads = pads_by_net(board).get("SAFE_TBSC_RETURN", [])
    if len(pads) == 2:
        a, b = pads
        added += route_poly(board, "SAFE_TBSC_RETURN", [item_pos(a), item_pos(b)], F_CU)
    return added


def route_power_backbones(board: pcbnew.BOARD) -> int:
    """Route constrained power backbones that are clearer as copper rails.

    This intentionally stops short of broad plane/zones. The rails stay inside
    their domains and use B.Cu backbones where F.Cu signal stubs already occupy
    the obvious pad columns.
    """
    added = 0
    j_safe = ref_by_value(board, "J_SAFETY")
    j_lamp = ref_by_value(board, "J_LAMP_LED")

    # Isolated wetting rail: output side of U37 feeds the 33 input LED series
    # resistors plus TP4. Route above the FIELD/LOGIC keepout at y=13, then use
    # a left-of-pad B.Cu rail with short component-side stubs.
    wet_x = 55.3
    wet_pads = [p for p in pads_by_net(board).get("FIELD_WET_V", []) if p.GetParentFootprint().GetReference().startswith("R")]
    wet_ys = [item_pos(p)[1] for p in wet_pads]
    if wet_ys:
        u37_wet = pad(board, "U37", "6")
        tp4 = pad(board, "TP4", "1")
        added += route_poly(board, "FIELD_WET_V", [item_pos(u37_wet), (item_pos(u37_wet)[0], 9.0), (wet_x, 9.0), (wet_x, 217.0)], B_CU)
        for p in wet_pads:
            added += route_pad_to_backbone(board, "FIELD_WET_V", p, wet_x)
        tx, ty = item_pos(tp4)
        added += route_poly(board, "FIELD_WET_V", [(tx, ty), (tx, 217.0), (wet_x, 217.0)], F_CU)
        add_via(board, "FIELD_WET_V", (wet_x, 217.0))
        added += 1

    # Isolated field ground: keep the common return on the far-left field edge,
    # then return to U37 above the keepout. This avoids the field signal fanout.
    fgnd_x = 5.5
    fgnd_pads = pads_by_net(board).get("FIELD_GND", [])
    if fgnd_pads:
        u37_fgnd = pad(board, "U37", "4")
        tp5 = pad(board, "TP5", "1")
        skip = {(u37_fgnd.GetParentFootprint().GetReference(), u37_fgnd.GetNumber()), (tp5.GetParentFootprint().GetReference(), tp5.GetNumber())}
        connector_pads = [p for p in fgnd_pads if (p.GetParentFootprint().GetReference(), p.GetNumber()) not in skip]
        ys = [item_pos(p)[1] for p in connector_pads] + [211.5]
        added += route_poly(board, "FIELD_GND", [(fgnd_x, min(ys)), (fgnd_x, max(ys))], B_CU)
        ux, uy = item_pos(u37_fgnd)
        added += route_poly(board, "FIELD_GND", [(ux, uy), (ux, 8.0), (fgnd_x, 8.0)], F_CU)
        add_via(board, "FIELD_GND", (fgnd_x, 8.0))
        added += 1
        added += route_poly(board, "FIELD_GND", [(fgnd_x, 8.0), (fgnd_x, min(ys))], B_CU)
        for p in connector_pads:
            added += route_pad_to_backbone(board, "FIELD_GND", p, fgnd_x)
        tx, ty = item_pos(tp5)
        added += route_poly(board, "FIELD_GND", [(tx, ty), (tx, 211.5), (fgnd_x, 211.5)], F_CU)
        add_via(board, "FIELD_GND", (fgnd_x, 211.5))
        added += 1

    # 3V3 pullup rail for the opto outputs. The opto signal fanout crosses the
    # pullup column on F.Cu, so the rail lives on B.Cu with one via per pad.
    vcc3_x = 88.6
    pullups = [
        p
        for p in pads_by_net(board).get("VCC_3V3", [])
        if p.GetParentFootprint().GetReference().startswith("R") and item_pos(p)[0] < 100.0
    ]
    if pullups:
        ys = [item_pos(p)[1] for p in pullups]
        y1, y2 = min(ys), max(ys)
        added += route_poly(board, "VCC_3V3", [(vcc3_x, y1), (vcc3_x, y2)], B_CU)
        for p in pullups:
            added += route_pad_to_backbone(board, "VCC_3V3", p, vcc3_x)

        # Bring the rail to the Pi/Pico logic connector without crossing the
        # J2 ground pins at y=10 or crowding U37's isolated output pads.
        j1_3v3 = pad(board, "J1", "11")
        added += route_poly(board, "VCC_3V3", [item_pos(j1_3v3), (item_pos(j1_3v3)[0], 18.0), (vcc3_x, 18.0), (vcc3_x, 22.0)], F_CU)
        add_via(board, "VCC_3V3", (vcc3_x, 22.0))
        added += 1
        added += route_poly(board, "VCC_3V3", [(vcc3_x, 22.0), (vcc3_x, y1)], B_CU)

        for p in pads_by_net(board).get("VCC_3V3", []):
            ref = p.GetParentFootprint().GetReference()
            px, py = item_pos(p)
            if ref.startswith("R") and px < 100.0:
                continue
            if ref.startswith("J") or ref.startswith("TP"):
                continue
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            via_x = px - 2.0 if px > vcc3_x else px + 2.0
            added += route_poly(board, "VCC_3V3", [(px, py), (via_x, py)], F_CU)
            add_via(board, "VCC_3V3", (via_x, py))
            added += 1
            if ref == "C3":
                added += route_poly(board, "VCC_3V3", [(via_x, py), (via_x, 93.5), (vcc3_x, 93.5)], B_CU)
            else:
                added += route_poly(board, "VCC_3V3", [(via_x, py), (vcc3_x, py)], B_CU)

    # Opto transistor ground rail. PC817 pad 3 is PTH; use a B.Cu rail offset
    # from the pad column so it does not pass through interleaved pad 4 signals.
    opto_gnd_x = 84.6
    opto_gnds = [
        p
        for p in pads_by_net(board).get("GND", [])
        if p.GetParentFootprint().GetReference().startswith("U") and item_pos(p)[0] < 90.0 and item_pos(p)[1] > 20.0
    ]
    if opto_gnds:
        ys = [item_pos(p)[1] for p in opto_gnds]
        y1, y2 = min(ys), max(ys)
        added += route_poly(board, "GND", [(opto_gnd_x, y1), (opto_gnd_x, y2)], B_CU)
        for p in opto_gnds:
            added += route_pad_to_backbone(board, "GND", p, opto_gnd_x)

        # Feed the opto-ground rail from the logic ground connector at J2.
        # U37 input ground is left for a later local power pass so this rail
        # does not cross the isolated wetting-voltage escape.
        j2_gnd = pad(board, "J2", "2")
        jx, jy = item_pos(j2_gnd)
        added += route_poly(board, "GND", [(jx, jy), (jx, 20.0), (opto_gnd_x, 20.0), (opto_gnd_x, y1)], B_CU)

    # Protected 5V rail. Keep the dense J1/J8 row escaped above the header
    # pins, then use a B.Cu trunk through the logic/safety side. VCC_5V_RAW is
    # only the short J2 -> D17 anode hop.
    raw_j2 = pad(board, "J2", "1")
    raw_d17 = pad(board, "D17", "2")
    rvx = item_pos(raw_d17)[0] + 2.2
    added += route_poly(board, "VCC_5V_RAW", [item_pos(raw_d17), (rvx, item_pos(raw_d17)[1])], F_CU)
    add_via(board, "VCC_5V_RAW", (rvx, item_pos(raw_d17)[1]))
    added += 1
    added += route_poly(board, "VCC_5V_RAW", [item_pos(raw_j2), (rvx, item_pos(raw_j2)[1]), (rvx, item_pos(raw_d17)[1])], IN1_CU)

    vcc5_x = 151.5
    added += route_poly(board, "VCC_5V", [(vcc5_x, 2.5), (vcc5_x, 214.0)], B_CU)
    added += route_poly(board, "VCC_5V", [item_pos(pad(board, "U37", "1")), (73.9, 2.5), (vcc5_x, 2.5)], IN1_CU)
    add_via(board, "VCC_5V", (vcc5_x, 2.5))
    added += 1
    for ref, pin, escape_y in [("J1", "1", 15.0), (j_safe, "1", 15.0)]:
        p = pad(board, ref, pin)
        px, py = item_pos(p)
        added += route_poly(board, "VCC_5V", [(px, py), (px, escape_y), (vcc5_x, escape_y)], B_CU)

    for p in pads_by_net(board).get("VCC_5V", []):
        ref = p.GetParentFootprint().GetReference()
        if ref in {"J1", j_safe, "U37"}:
            continue
        px, py = item_pos(p)
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            if ref == "D17":
                via_x = px - 2.2
            elif ref == "TP1":
                via_x = px - 2.0
            else:
                via_x = px + 2.2 if px < vcc5_x else px - 2.2
            added += route_poly(board, "VCC_5V", [(px, py), (via_x, py)], F_CU)
            add_via(board, "VCC_5V", (via_x, py))
            added += 1
            if ref == "D17":
                added += route_poly(board, "VCC_5V", [(via_x, py), (via_x, 27.4), (vcc5_x, 27.4)], B_CU)
            else:
                added += route_poly(board, "VCC_5V", [(via_x, py), (vcc5_x, py)], B_CU)
        else:
            if ref == j_lamp:
                added += route_poly(board, "VCC_5V", [item_pos(p), (px, 209.0), (vcc5_x, 209.0)], B_CU)
            else:
                added += route_poly(board, "VCC_5V", [item_pos(p), (vcc5_x, py)], B_CU)

    return added


def route_machine_outputs(board: pcbnew.BOARD) -> int:
    added = 0

    def projection_on_core(start: tuple[float, float], end: tuple[float, float], x: float) -> tuple[float, float]:
        sx, sy = start
        ex, ey = end
        if abs(ex - sx) < 0.001:
            return (x, sy)
        t = max(0.0, min(1.0, (x - sx) / (ex - sx)))
        return (x, sy + (ey - sy) * t)

    def escape_y_for_pad(ref: str, is_a: bool, py: float) -> float:
        if ref.startswith("R"):
            return py + 2.2
        if ref.startswith("C"):
            return py - 2.2
        if ref.startswith("D"):
            return py - 2.4
        return py

    for name in MOTION:
        for suffix in ("B", "A"):
            net_name = f"OUT_{name}_{suffix}"
            pads = pads_by_net(board).get(net_name, [])
            relay_pads = [p for p in pads if p.GetParentFootprint().GetReference().startswith("K")]
            conn_pads = [p for p in pads if p.GetParentFootprint().GetReference().startswith("J")]
            if not relay_pads or not conn_pads:
                continue
            start = item_pos(relay_pads[0])
            end = item_pos(conn_pads[0])
            is_a = suffix == "A"
            core_layer = B_CU if is_a else IN2_CU

            core_points = [start, end]
            escapes: list[tuple[tuple[float, float], tuple[float, float]]] = []
            for p in pads:
                ref = p.GetParentFootprint().GetReference()
                if not ref.startswith(("R", "C", "D")):
                    continue
                px, py = item_pos(p)
                escape_y = escape_y_for_pad(ref, is_a, py)
                side_x = 216.0 if is_a else 228.0
                side = (side_x, escape_y)
                proj_x = max(min(side_x, max(start[0], end[0]) - 0.5), min(start[0], end[0]) + 0.5)
                projection = projection_on_core(start, end, proj_x)

                added += route_poly(board, net_name, [(px, py), (side_x, py), side], F_CU)
                add_via(board, net_name, side)
                added += 1
                escapes.append((side, projection))
                core_points.append(projection)

            core_points = sorted(core_points, key=lambda xy: (xy[0] - start[0]) ** 2 + (xy[1] - start[1]) ** 2)
            added += route_poly(board, net_name, core_points, core_layer)
            for side, projection in escapes:
                added += route_poly(board, net_name, [side, projection], core_layer)
            continue

    # The DNP snubber/MOV pads remain for a later pass. This pass routes the
    # safety-relevant relay-contact core (relay contact <-> J_MOTION) cleanly
    # without letting optional suppression pads contaminate adjacent channels.
    return added


def route_machine_suppression(board: pcbnew.BOARD) -> int:
    """Route optional MOV/RC suppression pads within each machine channel."""
    added = 0

    for name in MOTION:
        snub = f"SNUB_{name}"
        snub_pads = pads_by_net(board).get(snub, [])
        if len(snub_pads) == 2:
            a, b = sorted(snub_pads, key=lambda p: item_pos(p)[0])
            ax, ay = item_pos(a)
            bx, by = item_pos(b)
            dogleg_x = (ax + bx) / 2.0
            added += route_poly(board, snub, [(ax, ay), (dogleg_x, ay), (dogleg_x, by), (bx, by)], F_CU)

    return added


def route_logic_input_fanout(board: pcbnew.BOARD) -> int:
    """Route pullup-to-controller legs for FAST_* and SLOW_* input nets.

    The opto-to-pullup stubs are already on F.Cu. This pass takes the other
    side of those same nets from pullup pad 2 into the Pico/MCP input pins.
    Long runs stay on In2.Cu inside the logic room to avoid both the F.Cu opto
    stubs and the B.Cu power backbones.
    """
    def route_group(nets: list[str], start_x: float, step: float) -> int:
        group_added = 0
        for i, net_name in enumerate(nets):
            pads = pads_by_net(board).get(net_name, [])
            try:
                rpad = next(p for p in pads if p.GetParentFootprint().GetReference().startswith("R") and p.GetNumber() == "2")
                target = next(
                    p
                    for p in pads
                    if p.GetParentFootprint().GetReference() == "A1"
                    or p.GetParentFootprint().GetReference() in {"U1", "U2", "U3"}
                )
            except StopIteration:
                continue

            rx, ry = item_pos(rpad)
            tx, ty = item_pos(target)
            entry_x = start_x + i * step
            exit_x = tx - 2.2 if tx < 125.0 else tx + 2.2

            group_added += route_poly(board, net_name, [(rx, ry), (entry_x, ry)], F_CU)
            add_via(board, net_name, (entry_x, ry))
            group_added += 1
            group_added += route_poly(board, net_name, [(entry_x, ry), (entry_x, ty), (exit_x, ty)], IN2_CU)
            add_via(board, net_name, (exit_x, ty))
            group_added += 1
            group_added += route_poly(board, net_name, [(exit_x, ty), (tx, ty)], F_CU)
        return group_added

    added = 0
    # Source and target Y both rise in this group, while the route climbs from
    # source to target. Use right-to-left entry channels to avoid crossings.
    added += route_group(
        ["FAST_SA", "FAST_SB", "FAST_SC", "FAST_TA1", "FAST_TA2", "FAST_TB", "FAST_DIELL_L", "FAST_DIELL_R"],
        112.0,
        -1.2,
    )

    # Source and target Y both rise here, while the route descends from source
    # to target. Use left-to-right entry channels to avoid crossings.
    added += route_group(
        ["SLOW_GS9", "SLOW_GS10", "SLOW_GP", "SLOW_OS", "SLOW_BS", "SLOW_PBZ", "SLOW_PBC", "SLOW_FOUL"],
        97.0,
        1.2,
    )
    return added


def route_reversed_slow_input_fanout(board: pcbnew.BOARD) -> int:
    """Route slow-input groups whose pullup order reverses at the MCP pins."""
    added = 0

    def route_group(
        nets: list[str],
        source_lanes: list[float],
        target_lanes: list[float],
        corridor_ys: list[float],
        source_y_offsets: dict[str, float] | None = None,
        vertical_layer: int = IN1_CU,
        corridor_layer: int = IN2_CU,
    ) -> int:
        group_added = 0
        source_y_offsets = source_y_offsets or {}
        for net_name, source_x, target_x, corridor_y in zip(nets, source_lanes, target_lanes, corridor_ys):
            pads = pads_by_net(board).get(net_name, [])
            try:
                rpad = next(p for p in pads if p.GetParentFootprint().GetReference().startswith("R") and p.GetNumber() == "2")
                target = next(p for p in pads if p.GetParentFootprint().GetReference() in {"U1", "U2"})
            except StopIteration:
                continue

            rx, ry = item_pos(rpad)
            tx, ty = item_pos(target)
            source_via = (source_x, ry + source_y_offsets.get(net_name, 0.0))
            source_corner = (source_x, ry)
            source_corridor = (source_x, corridor_y)
            target_corridor = (target_x, corridor_y)
            target_via = (target_x, ty)

            group_added += route_poly(board, net_name, [(rx, ry), source_corner, source_via], F_CU)
            add_via(board, net_name, source_via)
            group_added += 1
            group_added += route_poly(board, net_name, [source_via, source_corridor], vertical_layer)
            add_via(board, net_name, source_corridor)
            group_added += 1
            group_added += route_poly(board, net_name, [source_corridor, target_corridor], corridor_layer)
            add_via(board, net_name, target_corridor)
            group_added += 1
            group_added += route_poly(board, net_name, [target_corridor, target_via], vertical_layer)
            add_via(board, net_name, target_via)
            group_added += 1
            group_added += route_poly(board, net_name, [target_via, (tx, ty)], F_CU)
        return group_added

    added += route_group(
        ["SLOW_GS1", "SLOW_GS2", "SLOW_GS3", "SLOW_GS4", "SLOW_GS5", "SLOW_GS6", "SLOW_GS7", "SLOW_GS8"],
        [106.0, 107.0, 101.0, 109.0, 110.0, 111.0, 112.0, 118.0],
        [119.0, 120.0, 124.0, 128.0, 121.0, 125.0, 126.0, 127.0],
        [75.0, 77.0, 82.0, 80.0, 84.0, 86.0, 88.0, 90.0],
        {"SLOW_GS1": -1.5, "SLOW_GS4": -1.3, "SLOW_GS5": -3.3, "SLOW_GS6": 3.0, "SLOW_GS8": -1.0},
    )
    added += route_group(
        ["SLOW_TENTH", "SLOW_MAN_T", "SLOW_MAN_S", "SLOW_MAN_SWS", "SLOW_MAN_SWSR"],
        [94.8, 95.8, 96.8, 97.8, 95.0],
        [119.0, 120.0, 121.0, 122.0, 126.0],
        [166.8, 168.8, 170.8, 172.8, 174.8],
    )
    for net_name, source_x, lane_x, target_x, source_jog_y in [
        ("SLOW_AUX1", 99.0, 126.8, 126.0, None),
        ("SLOW_AUX2", 100.0, 127.8, 127.0, 209.5),
        ("SLOW_AUX3", 101.0, 128.8, 127.5, None),
    ]:
        pads = pads_by_net(board).get(net_name, [])
        try:
            rpad = next(p for p in pads if p.GetParentFootprint().GetReference().startswith("R") and p.GetNumber() == "2")
            target = next(p for p in pads if p.GetParentFootprint().GetReference() == "U2")
        except StopIteration:
            continue
        rx, ry = item_pos(rpad)
        tx, ty = item_pos(target)
        source_via = (source_x, ry)
        target_via = (target_x, ty)
        added += route_poly(board, net_name, [(rx, ry), source_via], F_CU)
        add_via(board, net_name, source_via)
        added += 1
        if source_jog_y is None:
            added += route_poly(board, net_name, [source_via, (lane_x, ry), (lane_x, ty), target_via], IN2_CU)
        else:
            added += route_poly(board, net_name, [source_via, (source_x, source_jog_y), (lane_x, source_jog_y), (lane_x, ty), target_via], IN2_CU)
        add_via(board, net_name, target_via)
        added += 1
        added += route_poly(board, net_name, [target_via, (tx, ty)], F_CU)
    return added


def route_i2c_bus(board: pcbnew.BOARD) -> int:
    """Route SDA/SCL as two simple inner-layer logic-room trunks."""
    added = 0
    trunks = {"I2C_SDA": (123.0, IN1_CU), "I2C_SCL": (129.5, IN2_CU)}
    for net_name, (trunk_x, layer) in trunks.items():
        pads = pads_by_net(board).get(net_name, [])
        trunk_ys: list[float] = []
        drops: list[tuple[float, float, str]] = []

        for p in pads:
            ref = p.GetParentFootprint().GetReference()
            px, py = item_pos(p)
            if ref.startswith("TP"):
                continue
            if ref == "J1":
                if net_name == "I2C_SCL":
                    added += route_poly(board, net_name, [(px, py), (px, 4.0), (124.0, 4.0), (124.0, 20.0), (trunk_x, 20.0)], layer)
                    trunk_ys.append(20.0)
                else:
                    escape_y = 15.0
                    added += route_poly(board, net_name, [(px, py), (px, escape_y), (trunk_x, escape_y)], layer)
                    trunk_ys.append(escape_y)
                continue

            via_x = px + 2.2 if px < trunk_x else px - 2.2
            via_y = py
            if ref == "U2":
                via_x = 113.0 if net_name == "I2C_SDA" else 110.8
            if net_name == "I2C_SDA" and ref == "R1":
                via_x = 99.5
            if net_name == "I2C_SDA" and ref == "U3":
                via_x = px + 2.2
                via_y = py + 1.5
                added += route_poly(board, net_name, [(px, py), (via_x, py), (via_x, via_y)], F_CU)
            else:
                added += route_poly(board, net_name, [(px, py), (via_x, py)], F_CU)
            add_via(board, net_name, (via_x, via_y))
            added += 1
            drops.append((via_x, via_y, ref))
            if net_name == "I2C_SDA" and ref == "R1":
                trunk_ys.append(57.0)
            elif ref == "U2":
                trunk_ys.append(134.0)
            else:
                trunk_ys.append(via_y)

        if trunk_ys:
            added += route_poly(board, net_name, [(trunk_x, min(trunk_ys)), (trunk_x, max(trunk_ys))], layer)
            for via_x, py, ref in drops:
                if net_name == "I2C_SDA" and ref == "R1":
                    added += route_poly(board, net_name, [(via_x, py), (via_x, 57.0), (trunk_x, 57.0)], layer)
                elif ref == "U2":
                    added += route_poly(board, net_name, [(via_x, py), (via_x, 134.0), (trunk_x, 134.0)], layer)
                else:
                    added += route_poly(board, net_name, [(via_x, py), (trunk_x, py)], layer)
    return added


def route_watchdog_control_locals(board: pcbnew.BOARD) -> int:
    """Route local watchdog and safety-control nets inside the logic room."""
    added = 0

    def local_trunk(net_name: str, refs_pins: list[tuple[str, str]], trunk_x: float) -> int:
        pads = [pad(board, ref, pin) for ref, pin in refs_pins]
        ys = [item_pos(p)[1] for p in pads]
        count = route_poly(board, net_name, [(trunk_x, min(ys)), (trunk_x, max(ys))], F_CU)
        for p in pads:
            x, y = item_pos(p)
            count += route_poly(board, net_name, [(x, y), (trunk_x, y)], F_CU)
        return count

    added += local_trunk("WDOG_KICK_GATE", [("R102", "2"), ("Q12", "1"), ("R103", "1")], 139.5)
    added += local_trunk("RAIL_GATE", [("Q14", "1"), ("R106", "2"), ("Q15", "3")], 145.5)
    added += local_trunk("BASE_AND_ARM", [("R107", "2"), ("Q15", "1"), ("R108", "1")], 136.0)

    added += route_poly(board, "NE555_CTRL", [item_pos(pad(board, "C13", "1")), (166.0, 51.905), item_pos(pad(board, "U36", "5"))], F_CU)

    added += route_poly(
        board,
        "AND_MID_ARM_RP",
        [
            item_pos(pad(board, "Q15", "2")),
            (144.8, 92.95),
            (144.8, 97.8),
            (163.2, 97.8),
            (163.2, 96.0),
            item_pos(pad(board, "Q16", "3")),
        ],
        F_CU,
    )

    base_rp_trunk_x = 168.0
    added += route_poly(board, "BASE_AND_RP_OK", [(base_rp_trunk_x, 89.0875), (base_rp_trunk_x, 98.9125)], F_CU)
    for ref, pin in [("R109", "2"), ("R110", "1")]:
        p = pad(board, ref, pin)
        added += route_poly(board, "BASE_AND_RP_OK", [item_pos(p), (base_rp_trunk_x, item_pos(p)[1])], F_CU)
    q16_base = pad(board, "Q16", "1")
    added += route_poly(board, "BASE_AND_RP_OK", [item_pos(q16_base), (156.8, item_pos(q16_base)[1])], F_CU)
    added += route_poly(board, "BASE_AND_RP_OK", [(156.8, item_pos(q16_base)[1]), (base_rp_trunk_x, item_pos(q16_base)[1])], F_CU)
    added += route_poly(board, "BASE_AND_RP_OK", [(base_rp_trunk_x, item_pos(q16_base)[1]), (base_rp_trunk_x, 95.05)], F_CU)

    for ref, pin in [("R104", "2"), ("Q13", "1"), ("R105", "1")]:
        p = pad(board, ref, pin)
        px, py = item_pos(p)
        added += route_poly(board, "WDOG_OK_GATE", [(px, py), (164.8, py)], F_CU)
        add_via(board, "WDOG_OK_GATE", (164.8, py))
        added += 1
    added += route_poly(board, "WDOG_OK_GATE", [(164.8, item_pos(pad(board, "R104", "2"))[1]), (164.8, item_pos(pad(board, "R105", "1"))[1])], IN1_CU)

    u36_out = pad(board, "U36", "3")
    r104_out = pad(board, "R104", "1")
    added += route_poly(board, "NE555_OUT", [item_pos(u36_out), (146.3, item_pos(u36_out)[1])], F_CU)
    add_via(board, "NE555_OUT", (146.3, item_pos(u36_out)[1]))
    added += 1
    added += route_poly(board, "NE555_OUT", [item_pos(r104_out), (163.0, item_pos(r104_out)[1])], F_CU)
    add_via(board, "NE555_OUT", (163.0, item_pos(r104_out)[1]))
    added += 1
    added += route_poly(
        board,
        "NE555_OUT",
        [(146.3, item_pos(u36_out)[1]), (146.3, 53.0), (163.0, 53.0), (163.0, item_pos(r104_out)[1])],
        IN1_CU,
    )

    return added


def route_watchdog_timing_locals(board: pcbnew.BOARD) -> int:
    """Route local 555 timing/discharge and safety-return nodes."""
    added = 0

    # Escape the 555 timing node from the outside of the timing pins so it
    # does not cross the adjacent 5V/control pads on U36.
    added += route_poly(
        board,
        "WDOG_TIMING_NODE",
        [
            item_pos(pad(board, "D15", "2")),
            (153.05, 37.2),
            (146.0, 37.2),
            item_pos(pad(board, "R100", "2")),
        ],
        F_CU,
    )
    added += route_poly(board, "WDOG_TIMING_NODE", [item_pos(pad(board, "D15", "2")), (153.05, 44.8), item_pos(pad(board, "C11", "1"))], F_CU)
    added += route_poly(board, "WDOG_TIMING_NODE", [item_pos(pad(board, "C11", "1")), (158.0, 44.8), (158.0, 49.365), item_pos(pad(board, "U36", "7"))], F_CU)
    added += route_poly(board, "WDOG_TIMING_NODE", [item_pos(pad(board, "U36", "7")), item_pos(pad(board, "U36", "6"))], F_CU)

    added += route_poly(board, "WDOG_KICK_DRAIN", [item_pos(pad(board, "D15", "1")), (150.95, 32.8), (157.95, 32.8), item_pos(pad(board, "D16", "1"))], F_CU)
    added += route_poly(board, "WDOG_KICK_DRAIN", [item_pos(pad(board, "D15", "1")), (149.0, 35.0)], F_CU)
    add_via(board, "WDOG_KICK_DRAIN", (149.0, 35.0))
    added += 1
    added += route_poly(board, "WDOG_KICK_DRAIN", [item_pos(pad(board, "Q12", "3")), (144.8, 58.0)], F_CU)
    add_via(board, "WDOG_KICK_DRAIN", (144.8, 58.0))
    added += 1
    added += route_poly(board, "WDOG_KICK_DRAIN", [(149.0, 35.0), (144.8, 35.0), (144.8, 58.0)], IN2_CU)

    for ref, pin, via_xy in [
        ("U36", "2", (147.0, 49.365)),
        ("D16", "2", (162.2, 35.0)),
        ("R101", "2", (142.8, 77.0875)),
    ]:
        added += route_poly(board, "NE555_TRIG", [item_pos(pad(board, ref, pin)), via_xy], F_CU)
        add_via(board, "NE555_TRIG", via_xy)
        added += 1
    added += route_poly(board, "NE555_TRIG", [(162.2, 35.0), (162.2, 33.0), (147.0, 33.0), (147.0, 49.365), (142.8, 49.365), (142.8, 77.0875)], IN1_CU)

    added += route_poly(board, "WDOG_OK_PULLDOWN", [item_pos(pad(board, "Q13", "3")), (163.6, 58.0)], F_CU)
    add_via(board, "WDOG_OK_PULLDOWN", (163.6, 58.0))
    added += 1
    added += route_poly(board, "WDOG_OK_PULLDOWN", [item_pos(pad(board, "Q16", "2")), (162.0, 96.95)], F_CU)
    add_via(board, "WDOG_OK_PULLDOWN", (162.0, 96.95))
    added += 1
    added += route_poly(board, "WDOG_OK_PULLDOWN", [(163.6, 58.0), (163.6, 96.95), (162.0, 96.95)], IN2_CU)

    added += route_poly(board, "SAFE_STOP_RETURN", [item_pos(pad(board, "R106", "1")), (157.0625, 82.9125), item_pos(pad(board, "Q14", "2"))], F_CU)

    return added


def route_driver_input_pairs(board: pcbnew.BOARD) -> int:
    """Join local resistor-pair pads for the relay DRV_* command nets."""
    added = 0
    for name in MOTION:
        net_name = f"DRV_{name}"
        rpads = [
            p
            for p in pads_by_net(board).get(net_name, [])
            if p.GetParentFootprint().GetReference().startswith("R") and p.GetNumber() == "1"
        ]
        if len(rpads) != 2:
            continue
        a, b = sorted(rpads, key=lambda p: item_pos(p)[1])
        ax, ay = item_pos(a)
        bx, by = item_pos(b)
        dogleg_x = 147.8
        added += route_poly(board, net_name, [(ax, ay), (dogleg_x, ay), (dogleg_x, by), (bx, by)], F_CU)
    return added


def route_driver_u3_fanout(board: pcbnew.BOARD) -> int:
    """Route U3 driver fanouts that have clean local access to existing stubs."""
    added = 0
    added += route_poly(board, "DRV_SP", [item_pos(pad(board, "U3", "23")), (147.8, 110.095), (147.8, 109.9125)], F_CU)
    added += route_poly(board, "DRV_T", [item_pos(pad(board, "U3", "22")), (147.0, 111.365)], F_CU)
    add_via(board, "DRV_T", (147.0, 111.365))
    added += 1
    added += route_poly(board, "DRV_T", [(147.0, 111.365), (147.0, 93.9125)], IN2_CU)
    add_via(board, "DRV_T", (147.0, 93.9125))
    added += 1
    added += route_poly(board, "DRV_T", [(147.0, 93.9125), (147.8, 93.9125)], F_CU)
    added += route_poly(board, "DRV_S", [item_pos(pad(board, "U3", "21")), (144.0, 112.635)], F_CU)
    add_via(board, "DRV_S", (144.0, 112.635))
    added += 1
    added += route_poly(board, "DRV_S", [(144.0, 112.635), (144.0, 71.9125)], IN2_CU)
    add_via(board, "DRV_S", (144.0, 71.9125))
    added += 1
    added += route_poly(board, "DRV_S", [(144.0, 71.9125), (147.8, 71.9125)], F_CU)
    added += route_poly(board, "DRV_BE", [item_pos(pad(board, "U3", "24")), (148.2, 108.825)], F_CU)
    add_via(board, "DRV_BE", (148.2, 108.825))
    added += 1
    added += route_poly(board, "DRV_BE", [(148.2, 108.825), (148.2, 131.9125)], IN2_CU)
    add_via(board, "DRV_BE", (148.2, 131.9125))
    added += 1
    added += route_poly(board, "DRV_BE", [(148.2, 131.9125), (147.8, 131.9125)], F_CU)
    added += route_poly(board, "DRV_M", [item_pos(pad(board, "U3", "25")), (145.5, 107.555)], F_CU)
    add_via(board, "DRV_M", (145.5, 107.555))
    added += 1
    added += route_poly(board, "DRV_M", [(145.5, 107.555), (145.5, 153.9125)], IN2_CU)
    add_via(board, "DRV_M", (145.5, 153.9125))
    added += 1
    added += route_poly(board, "DRV_M", [(145.5, 153.9125), (147.8, 153.9125)], F_CU)
    added += route_poly(board, "DRV_M2", [item_pos(pad(board, "U3", "26")), (149.2, 106.285)], F_CU)
    add_via(board, "DRV_M2", (149.2, 106.285))
    added += 1
    added += route_poly(board, "DRV_M2", [(149.2, 106.285), (149.2, 175.9125)], IN2_CU)
    add_via(board, "DRV_M2", (149.2, 175.9125))
    added += 1
    added += route_poly(board, "DRV_M2", [(149.2, 175.9125), (147.8, 175.9125)], F_CU)
    added += route_poly(board, "DRV_M1", [item_pos(pad(board, "U3", "27")), (150.2, 105.015)], F_CU)
    add_via(board, "DRV_M1", (150.2, 105.015))
    added += 1
    added += route_poly(board, "DRV_M1", [(150.2, 105.015), (150.2, 197.9125)], IN2_CU)
    add_via(board, "DRV_M1", (150.2, 197.9125))
    added += 1
    added += route_poly(board, "DRV_M1", [(150.2, 197.9125), (150.0, 197.9125)], F_CU)
    added += route_poly(board, "DRV_L_FOUL", [item_pos(pad(board, "U3", "3")), (136.5, 106.285)], F_CU)
    add_via(board, "DRV_L_FOUL", (136.5, 106.285))
    added += 1
    added += route_poly(board, "DRV_L_FOUL", [(136.5, 106.285), (136.5, 121.5)], IN2_CU)
    add_via(board, "DRV_L_FOUL", (136.5, 121.5))
    added += 1
    added += route_poly(
        board,
        "DRV_L_FOUL",
        [(136.5, 121.5), (136.5, 180.6), (138.0, 180.6), (138.0, 190.9125)],
        B_CU,
    )
    add_via(board, "DRV_L_FOUL", (138.0, 190.9125))
    added += 1
    added += route_poly(board, "DRV_L_FOUL", [(138.0, 190.9125), (137.0, 190.9125)], F_CU)
    added += route_poly(board, "DRV_L_STRIKE", [item_pos(pad(board, "U3", "2")), (134.2, 105.015)], F_CU)
    add_via(board, "DRV_L_STRIKE", (134.2, 105.015))
    added += 1
    added += route_poly(board, "DRV_L_STRIKE", [(134.2, 105.015), (134.2, 121.4)], IN2_CU)
    add_via(board, "DRV_L_STRIKE", (134.2, 121.4))
    added += 1
    added += route_poly(
        board,
        "DRV_L_STRIKE",
        [(134.2, 121.4), (134.2, 179.5), (126.0, 179.5), (126.0, 190.9125)],
        B_CU,
    )
    add_via(board, "DRV_L_STRIKE", (126.0, 190.9125))
    added += 1
    added += route_poly(board, "DRV_L_STRIKE", [(126.0, 190.9125), (125.0, 190.9125)], F_CU)
    added += route_poly(board, "DRV_L_SECOND", [item_pos(pad(board, "U3", "1")), (130.2, 103.745)], F_CU)
    add_via(board, "DRV_L_SECOND", (130.2, 103.745))
    added += 1
    added += route_poly(board, "DRV_L_SECOND", [(130.2, 103.745), (130.2, 115.5)], IN2_CU)
    add_via(board, "DRV_L_SECOND", (130.2, 115.5))
    added += 1
    added += route_poly(board, "DRV_L_SECOND", [(130.2, 115.5), (128.6, 115.5)], IN1_CU)
    add_via(board, "DRV_L_SECOND", (128.6, 115.5))
    added += 1
    added += route_poly(board, "DRV_L_SECOND", [(128.6, 115.5), (128.6, 122.4)], IN2_CU)
    add_via(board, "DRV_L_SECOND", (128.6, 122.4))
    added += 1
    added += route_poly(
        board,
        "DRV_L_SECOND",
        [(128.6, 122.4), (128.6, 178.4), (114.0, 178.4), (114.0, 190.9125)],
        B_CU,
    )
    add_via(board, "DRV_L_SECOND", (114.0, 190.9125))
    added += 1
    added += route_poly(board, "DRV_L_SECOND", [(114.0, 190.9125), (113.0, 190.9125)], F_CU)
    added += route_poly(board, "DRV_L_FIRST", [item_pos(pad(board, "U3", "28")), (142.7, 103.745)], F_CU)
    add_via(board, "DRV_L_FIRST", (142.7, 103.745))
    added += 1
    added += route_poly(board, "DRV_L_FIRST", [(142.7, 103.745), (142.7, 112.0)], IN2_CU)
    add_via(board, "DRV_L_FIRST", (142.7, 112.0))
    added += 1
    added += route_poly(board, "DRV_L_FIRST", [(142.7, 112.0), (106.2, 112.0)], B_CU)
    add_via(board, "DRV_L_FIRST", (106.2, 112.0))
    added += 1
    added += route_poly(board, "DRV_L_FIRST", [(106.2, 112.0), (106.2, 190.9125), (105.5, 190.9125)], IN1_CU)
    add_via(board, "DRV_L_FIRST", (105.5, 190.9125))
    added += 1
    added += route_poly(board, "DRV_L_FIRST", [(105.5, 190.9125), (101.0, 190.9125)], F_CU)
    return added


def route_logic_gnd_zone(board: pcbnew.BOARD) -> int:
    """Add a filled F.Cu GND zone inside the logic room only."""
    add_zone_rect(
        board,
        "GND",
        F_CU,
        [(80.4, 4.5), (180.5, 4.5), (180.5, 219.0), (80.4, 219.0)],
    )
    return 1


def route_power_signal_tails(board: pcbnew.BOARD) -> int:
    """Route small tails left open by backbone/trunk passes."""
    added = 0

    # U37 input ground sits just left of the FIELD/LOGIC keepout. Bring it to
    # the opto-side logic ground rail above/beside the keepout without crossing
    # the isolated wetting-voltage escape.
    added += route_poly(board, "GND", [item_pos(pad(board, "U37", "2")), (76.44, 3.5), (91.0, 3.5), (91.0, 20.0)], IN2_CU)
    add_via(board, "GND", (91.0, 20.0))
    added += 1

    # Bottom test pads for already-routed rails/buses.
    added += route_poly(board, "VCC_3V3", [(88.6, 211.8), (88.6, 217.5)], B_CU)
    added += route_poly(board, "VCC_3V3", [item_pos(pad(board, "TP3", "1")), (116.0, 217.5), (88.6, 217.5)], F_CU)
    add_via(board, "VCC_3V3", (88.6, 217.5))
    added += 1

    added += route_poly(board, "I2C_SDA", [(123.0, 134.0), (123.0, 216.2), (126.0, 216.2)], IN1_CU)
    added += route_poly(board, "I2C_SDA", [item_pos(pad(board, "TP6", "1")), (128.0, 216.2), (126.0, 216.2)], F_CU)
    add_via(board, "I2C_SDA", (126.0, 216.2))
    added += 1

    added += route_poly(board, "I2C_SCL", [(129.5, 134.0), (129.5, 216.5), (138.0, 216.5)], IN2_CU)
    added += route_poly(board, "I2C_SCL", [item_pos(pad(board, "TP7", "1")), (138.0, 216.5)], F_CU)
    add_via(board, "I2C_SCL", (138.0, 216.5))
    added += 1

    return added


def route_header_logic_signals(board: pcbnew.BOARD) -> int:
    """Route small J1-to-logic point-to-point signals."""
    added = 0

    routes = [
        ("PI_UART_RX", ("J1", "6"), ("A1", "1"), 116.5, IN2_CU, 2.5),
        ("PI_UART_TX", ("J1", "5"), ("A1", "2"), 118.8, IN1_CU, 16.0),
    ]
    for net_name, start_refpin, end_refpin, channel_x, layer, escape_y in routes:
        start = pad(board, *start_refpin)
        end = pad(board, *end_refpin)
        sx, sy = item_pos(start)
        ex, ey = item_pos(end)
        via_x = ex + 2.2 if ex < channel_x else ex - 2.2
        if net_name == "PI_UART_TX":
            switch = (125.0, 21.0)
            added += route_poly(board, net_name, [(sx, sy), (sx, 16.0), (125.0, 16.0), switch], IN1_CU)
            add_via(board, net_name, switch)
            added += 1
            added += route_poly(board, net_name, [switch, (channel_x, 21.0), (channel_x, ey), (via_x, ey)], IN2_CU)
            added += route_poly(board, net_name, [(ex, ey), (via_x, ey)], F_CU)
            add_via(board, net_name, (via_x, ey))
            added += 1
            continue
        added += route_poly(board, net_name, [(sx, sy), (sx, escape_y), (channel_x, escape_y), (channel_x, ey), (via_x, ey)], layer)
        added += route_poly(board, net_name, [(ex, ey), (via_x, ey)], F_CU)
        add_via(board, net_name, (via_x, ey))
        added += 1

    added += route_poly(board, "MCP_INT_A", [item_pos(pad(board, "J1", "9")), (136.16, 17.0), (130.9, 17.0)], F_CU)
    add_via(board, "MCP_INT_A", (130.9, 17.0))
    added += 1
    added += route_poly(board, "MCP_INT_A", [(130.9, 17.0), (130.9, 105.905)], IN2_CU)
    add_via(board, "MCP_INT_A", (130.9, 105.905))
    added += 1
    added += route_poly(board, "MCP_INT_A", [(130.9, 105.905), item_pos(pad(board, "U1", "20"))], F_CU)

    added += route_poly(board, "MCP_INT_B", [item_pos(pad(board, "J1", "10")), (136.16, 4.0), (140.0, 4.0)], F_CU)
    add_via(board, "MCP_INT_B", (140.0, 4.0))
    added += 1
    added += route_poly(board, "MCP_INT_B", [(140.0, 4.0), (140.0, 147.905), (140.3, 147.905)], IN2_CU)
    add_via(board, "MCP_INT_B", (140.3, 147.905))
    added += 1
    added += route_poly(board, "MCP_INT_B", [(140.3, 147.905), item_pos(pad(board, "U2", "20"))], F_CU)

    return added


def route_watchdog_header_signals(board: pcbnew.BOARD) -> int:
    """Route header/controller watchdog signals into their local logic nodes."""
    added = 0
    j_safe = ref_by_value(board, "J_SAFETY")

    added += route_poly(board, "WDOG_KICK", [item_pos(pad(board, "R102", "1")), (141.0, 47.9125)], F_CU)
    add_via(board, "WDOG_KICK", (141.0, 47.9125))
    added += 1
    added += route_poly(board, "WDOG_KICK", [item_pos(pad(board, "J1", "7")), (133.62, 12.5), (141.0, 12.5), (141.0, 47.9125)], IN1_CU)

    arm_via = (132.9, 90.9125)
    added += route_poly(board, "ARM_PERMIT", [item_pos(pad(board, "R107", "1")), arm_via], F_CU)
    add_via(board, "ARM_PERMIT", arm_via)
    added += 1
    added += route_poly(board, "ARM_PERMIT", [item_pos(pad(board, "J1", "8")), (134.8, 4.0), (134.8, 90.9125), arm_via], IN2_CU)

    safe_stop_header_via = (153.4, 83.1)
    added += route_poly(board, "SAFE_STOP_RETURN", [item_pos(pad(board, "R106", "1")), safe_stop_header_via], F_CU)
    add_via(board, "SAFE_STOP_RETURN", safe_stop_header_via)
    added += 1
    added += route_poly(board, "SAFE_STOP_RETURN", [item_pos(pad(board, j_safe, "4")), (170.5, 83.1), safe_stop_header_via], F_CU)

    return added


def route_watchdog_testpad_tails(board: pcbnew.BOARD) -> int:
    """Connect bottom monitor test pads for already-routed watchdog nets."""
    added = 0

    def tail(
        net_name: str,
        source: tuple[float, float],
        tp_ref: str,
        channel: tuple[float, float],
        layer: int,
        horizontal_first: bool = True,
    ) -> int:
        bend = (channel[0], source[1]) if horizontal_first else (source[0], channel[1])
        count = route_poly(board, net_name, [source, bend, channel], layer)
        add_via(board, net_name, channel)
        count += 1
        tx, ty = item_pos(pad(board, tp_ref, "1"))
        count += route_poly(board, net_name, [channel, (tx, channel[1]), (tx, ty)], F_CU)
        return count

    added += tail("WDOG_KICK", (141.0, 47.9125), "TP8", (149.0, 211.5), IN2_CU, horizontal_first=False)
    added += tail("ARM_PERMIT", (132.9, 90.9125), "TP13", (139.5, 218.0), IN1_CU)
    added += tail("SAFE_STOP_RETURN", (153.4, 83.1), "TP15", (152.5, 218.3), IN1_CU)
    added += tail("WDOG_OK_PULLDOWN", (162.0, 96.95), "TP12", (128.0, 219.5), IN2_CU, horizontal_first=False)
    add_via(board, "NE555_OUT", (156.0, 53.0))
    added += 1
    added += route_poly(board, "NE555_OUT", [(156.0, 53.0), (156.0, 220.5), (116.0, 220.5)], B_CU)
    add_via(board, "NE555_OUT", (116.0, 220.5))
    added += 1
    added += route_poly(board, "NE555_OUT", [(116.0, 220.5), item_pos(pad(board, "TP11", "1"))], F_CU)

    added += route_poly(board, "NE555_TRIG", [(142.8, 77.0875), (141.0, 77.0875), (141.0, 218.8), (104.0, 218.8)], IN1_CU)
    add_via(board, "NE555_TRIG", (104.0, 218.8))
    added += 1
    added += route_poly(board, "NE555_TRIG", [(104.0, 218.8), item_pos(pad(board, "TP10", "1"))], F_CU)

    wdog_timing_via = (154.8, 50.0)
    added += route_poly(board, "WDOG_TIMING_NODE", [item_pos(pad(board, "U36", "6")), (154.8, 50.635), wdog_timing_via], F_CU)
    add_via(board, "WDOG_TIMING_NODE", wdog_timing_via)
    added += 1
    added += route_poly(board, "WDOG_TIMING_NODE", [wdog_timing_via, (154.8, 217.2), (90.0, 217.2), (90.0, 219.5)], IN2_CU)
    add_via(board, "WDOG_TIMING_NODE", (90.0, 219.5))
    added += 1
    added += route_poly(board, "WDOG_TIMING_NODE", [(90.0, 219.5), (92.0, 219.5), item_pos(pad(board, "TP9", "1"))], F_CU)
    return added


def route_rp2040_ok(board: pcbnew.BOARD) -> int:
    """Route the RP2040_OK monitor/permit status net."""
    added = 0
    a1_via = (116.8, 38.49)
    layer_switch = (149.0, 38.49)
    rp_trunk_x = 168.0
    r109_via = (170.0, 90.9125)
    tp_via = (148.0, 223.0)

    added += route_poly(board, "RP2040_OK", [item_pos(pad(board, "A1", "4")), a1_via], F_CU)
    add_via(board, "RP2040_OK", a1_via)
    added += 1
    added += route_poly(board, "RP2040_OK", [a1_via, layer_switch], B_CU)
    add_via(board, "RP2040_OK", layer_switch)
    added += 1
    added += route_poly(
        board,
        "RP2040_OK",
        [item_pos(pad(board, "J1", "13")), (141.24, 12.2), (152.0, 12.2), (152.0, 38.49), layer_switch, (rp_trunk_x, 38.49), (rp_trunk_x, 223.0), tp_via],
        IN2_CU,
    )
    added += route_poly(board, "RP2040_OK", [(rp_trunk_x, r109_via[1]), r109_via], IN2_CU)
    added += route_poly(board, "RP2040_OK", [item_pos(pad(board, "R109", "1")), r109_via], F_CU)
    add_via(board, "RP2040_OK", r109_via)
    added += 1
    add_via(board, "RP2040_OK", tp_via)
    added += 1
    added += route_poly(board, "RP2040_OK", [tp_via, item_pos(pad(board, "TP14", "1"))], F_CU)
    return added


def route_small_local_logic(board: pcbnew.BOARD) -> int:
    """Route short non-power, non-domain-crossing two-node logic nets."""
    added = 0
    skip_prefixes = ("FIELD_", "OUT_", "SNUB_", "LED_", "COIL_LO_", "BASE_")
    for net_name, pads in sorted(pads_by_net(board).items()):
        if net_name in {"GND", "VCC_3V3", "VCC_5V", "VCC_5V_RAW", "FIELD_WET_V", "FIELD_GND", "RELAY_ENABLE_RAIL"}:
            continue
        if net_name.startswith(skip_prefixes):
            continue
        if len(pads) != 2:
            continue
        pts = [item_pos(p) for p in pads]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) - min(xs) > 35 or max(ys) - min(ys) > 35:
            continue
        mid = (pts[0][0], pts[1][1])
        added += route_poly(board, net_name, [pts[0], mid, pts[1]], F_CU)
    return added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--in-place", action="store_true", help="write back to --source instead of --output")
    parser.add_argument("--skip-machine-outputs", action="store_true", help="leave J_MOTION relay-contact cores unrouted")
    args = parser.parse_args()

    source = args.source.resolve()
    output = source if args.in_place else args.output.resolve()
    if not source.exists():
        raise SystemExit(f"ERROR: missing board: {source}")
    if output != source:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        copy_project_sidecars(source, output)

    board = pcbnew.LoadBoard(str(output))
    assert_netclasses_active(board)
    removed = clear_tracks(board)

    totals = {
        "field_led_series": route_field_led_series(board),
        "field_input_returns": route_field_input_returns(board),
        "opto_to_pullups": route_opto_to_pullups(board),
        "status_led_cluster": route_status_led_cluster(board),
        "relay_driver_locals": route_relay_driver_locals(board),
        "safety_rail_spine": route_safety_rail_spine(board),
        "power_backbones": route_power_backbones(board),
        "logic_input_fanout": route_logic_input_fanout(board),
        "reversed_slow_input_fanout": route_reversed_slow_input_fanout(board),
        "i2c_bus": route_i2c_bus(board),
        "watchdog_control_locals": route_watchdog_control_locals(board),
        "watchdog_timing_locals": route_watchdog_timing_locals(board),
        "driver_input_pairs": route_driver_input_pairs(board),
        "driver_u3_fanout": route_driver_u3_fanout(board),
        "logic_gnd_zone": route_logic_gnd_zone(board),
        "power_signal_tails": route_power_signal_tails(board),
        "header_logic_signals": route_header_logic_signals(board),
        "watchdog_header_signals": route_watchdog_header_signals(board),
        "watchdog_testpad_tails": route_watchdog_testpad_tails(board),
        "rp2040_ok": route_rp2040_ok(board),
        # Dense machine-output routing and remaining bulk logic are separate
        # passes; keep this first pass clean and auditable.
        "machine_outputs": 0 if args.skip_machine_outputs else route_machine_outputs(board),
        "machine_suppression": 0 if args.skip_machine_outputs else route_machine_suppression(board),
        "small_local_logic": 0,
    }

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(output), board)
    print(f"Board: {output}")
    print(f"Removed existing tracks/vias: {removed}")
    for name, count in totals.items():
        print(f"{name}: {count}")
    print(f"Total route actions added: {sum(totals.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
