#!/usr/bin/env python3
"""Shared helpers + self-check registry for the rev-D manual router.

ADAPTED from scripts/manual_route_revB.py (the rev-C router is SACRED and
untouched). Adds a geometric self-check registry: every track/via the router
adds is recorded and checked for same-layer clearance against (a) every other
added item on a different net and (b) every board pad on a different net,
plus rule-area (keepout) incursions. This catches routing errors at
generation time, before KiCad DRC.

Run from KiCad's bundled Python (imported by route_revD.py).
"""
from __future__ import annotations

import math
from collections import defaultdict

import pcbnew

F_CU = pcbnew.F_Cu
B_CU = pcbnew.B_Cu
IN1_CU = pcbnew.In1_Cu
IN2_CU = pcbnew.In2_Cu

NET_RULES = {
    "Logic_Signal": {"width": 0.25, "via": 0.60, "drill": 0.30, "clr": 0.20},
    "Logic_Power": {"width": 0.50, "via": 0.80, "drill": 0.40, "clr": 0.20},
    "Safety_Rail": {"width": 0.60, "via": 0.80, "drill": 0.40, "clr": 0.30},
    "Field_Sense": {"width": 0.30, "via": 0.70, "drill": 0.35, "clr": 0.40},
    "Machine_Output": {"width": 0.50, "via": 1.00, "drill": 0.50, "clr": 0.35},
}
# Remediation spec R1.7 (2026-07-21): +4 TAP_GATE_* nets -> Logic_Signal 97.
# Round-2 remediation R2-4/R2-6 (2026-07-21): +6 (J16_*/REV_ID*) -> 103.
NETCLASS_COUNTS = {
    "Logic_Signal": 103,
    "Logic_Power": 4,
    "Safety_Rail": 13,
    "Field_Sense": 122,   # r6 (2026-07-25): 82 + 40 x FIELD_RIN_<n>
    "Machine_Output": 21,
}

FAST_INPUTS = ["SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R"]
SLOW_A = [f"GS{i}" for i in range(1, 11)] + ["GP", "OS", "BS"]
SLOW_B = ["PBZ", "PBC", "FOUL", "TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "AUX1", "AUX2", "AUX3"]
SLOW_C = [f"AUX{i}" for i in range(4, 12)]
MOTION = ["S", "T", "SP", "BE", "M", "M2", "M1"]
LAMPS = ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]

INPUT_ORDER = FAST_INPUTS + SLOW_A + SLOW_B + SLOW_C
ROW_Y0 = 13.0
ROW_PITCH = 5.7


def row_y(i: int) -> float:
    return ROW_Y0 + i * ROW_PITCH


def mm(value: float) -> int:
    return pcbnew.FromMM(float(value))


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def pt_mm(point) -> tuple[float, float]:
    return point.x / 1e6, point.y / 1e6


def item_pos(item) -> tuple[float, float]:
    return pt_mm(item.GetPosition())


class Router:
    """Board wrapper with a self-check registry of everything we add."""

    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self.segs: list[tuple[str, int, tuple, tuple, float]] = []   # net, layer, p1, p2, width
        self.vias: list[tuple[str, tuple, float]] = []               # net, pos, dia
        self.net_class: dict[str, str] = {}
        settings = board.GetDesignSettings().m_NetSettings
        settings.RecomputeEffectiveNetclasses()
        for n in board.GetNetsByName().keys():
            name = str(n)
            if name:
                self.net_class[name] = settings.GetEffectiveNetClass(name).GetName()
        self._pads = None
        self._pad_geo = None

    # ---- lookups ----
    def rule(self, net: str) -> dict:
        return NET_RULES.get(self.net_class.get(net, "Logic_Signal"), NET_RULES["Logic_Signal"])

    def pads_by_net(self) -> dict[str, list]:
        if self._pads is None:
            nets = defaultdict(list)
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetNetname():
                        nets[pad.GetNetname()].append(pad)
            self._pads = nets
        return self._pads

    def pad(self, ref: str, pin) -> pcbnew.PAD:
        fp = self.board.FindFootprintByReference(ref)
        if fp is None:
            raise KeyError(f"Missing footprint {ref}")
        for cand in fp.Pads():
            if cand.GetNumber() == str(pin):
                return cand
        raise KeyError(f"Missing pad {ref}.{pin}")

    def ppos(self, ref: str, pin) -> tuple[float, float]:
        return item_pos(self.pad(ref, pin))

    def net_pad(self, net: str, ref_prefix=None, pin=None, ref=None):
        matches = []
        for cand in self.pads_by_net().get(net, []):
            r = cand.GetParentFootprint().GetReference()
            if ref and r != ref:
                continue
            if ref_prefix and not r.startswith(ref_prefix):
                continue
            if pin and cand.GetNumber() != str(pin):
                continue
            matches.append(cand)
        if len(matches) != 1:
            got = ", ".join(f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}" for p in matches)
            raise KeyError(f"net_pad {net} {ref_prefix=} {ref=} {pin=}: {len(matches)} matches ({got})")
        return matches[0]

    # ---- copper add ----
    def track(self, net: str, p1, p2, layer, width=None):
        if abs(p1[0] - p2[0]) < 1e-4 and abs(p1[1] - p2[1]) < 1e-4:
            return
        w = width if width is not None else self.rule(net)["width"]
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(v(*p1))
        t.SetEnd(v(*p2))
        t.SetLayer(layer)
        t.SetWidth(mm(w))
        t.SetNet(self.board.FindNet(net))
        self.board.Add(t)
        self.segs.append((net, int(layer), tuple(p1), tuple(p2), w))

    def poly(self, net: str, points, layer, width=None) -> int:
        n = 0
        for a, b in zip(points, points[1:]):
            self.track(net, a, b, layer, width)
            n += 1
        return n

    def via(self, net: str, xy, dia=None, drill=None):
        r = self.rule(net)
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(v(*xy))
        via.SetWidth(mm(dia if dia else r["via"]))
        via.SetDrill(mm(drill if drill else r["drill"]))
        via.SetLayerPair(F_CU, B_CU)
        via.SetNet(self.board.FindNet(net))
        self.board.Add(via)
        self.vias.append((net, tuple(xy), dia if dia else r["via"]))

    def clear_tracks(self) -> int:
        # KiCad 10.0.2 (M2 fix): BOARD.Remove() detaches without freeing —
        # SWIG reports "memory leak of type 'PCB_TRACK *'" and the board's
        # item containers are left in a state where a later Zones() iteration
        # segfaults or yields raw SwigPyObject (the audit's GetIsRuleArea
        # crash). BOARD.Delete() removes AND destroys natively; verified
        # stable on 10.0.2 (tmp/m2_fix_test.py, 2026-07-21).
        tracks = list(self.board.GetTracks())
        for t in tracks:
            self.board.Delete(t)
        return len(tracks)

    # ---- self-check ----
    def clr(self, net_a: str, net_b: str) -> float:
        return max(self.rule(net_a)["clr"], self.rule(net_b)["clr"])

    def _pad_geometry(self):
        if self._pad_geo is None:
            geo = []
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if not str(pad.GetNumber()):
                        continue
                    x, y = item_pos(pad)
                    sx = pad.GetSizeX() / 1e6
                    sy = pad.GetSizeY() / 1e6
                    ang = abs(pad.GetOrientationDegrees()) % 180.0
                    if 45 < ang < 135:
                        sx, sy = sy, sx
                    smd = pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                    ref = pad.GetParentFootprint().GetReference()
                    geo.append((pad.GetNetname(), ref + "." + str(pad.GetNumber()),
                                x - sx / 2, y - sy / 2, x + sx / 2, y + sy / 2, smd))
            self._pad_geo = geo
        return self._pad_geo

    def check(self) -> list[str]:
        probs = []
        segs = self.segs
        vias = self.vias

        def seg_seg(a1, a2, b1, b2) -> float:
            def d_ps(p, s1, s2):
                sx, sy = s2[0] - s1[0], s2[1] - s1[1]
                ln = sx * sx + sy * sy
                if ln < 1e-12:
                    return math.hypot(p[0] - s1[0], p[1] - s1[1])
                t = max(0.0, min(1.0, ((p[0] - s1[0]) * sx + (p[1] - s1[1]) * sy) / ln))
                return math.hypot(p[0] - s1[0] - t * sx, p[1] - s1[1] - t * sy)

            def ccw(a, b, c):
                return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

            if (ccw(a1, a2, b1) * ccw(a1, a2, b2) < 0) and (ccw(b1, b2, a1) * ccw(b1, b2, a2) < 0):
                return 0.0
            return min(d_ps(b1, a1, a2), d_ps(b2, a1, a2), d_ps(a1, b1, b2), d_ps(a2, b1, b2))

        def d_seg_rect(s1, s2, x1, y1, x2, y2) -> float:
            if x1 <= s1[0] <= x2 and y1 <= s1[1] <= y2:
                return 0.0
            if x1 <= s2[0] <= x2 and y1 <= s2[1] <= y2:
                return 0.0
            edges = [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]
            return min(seg_seg(s1, s2, e1, e2) for e1, e2 in edges)

        # bucket segs by layer for pair checks
        by_layer = defaultdict(list)
        for i, s in enumerate(segs):
            by_layer[s[1]].append(i)
        for layer, idxs in by_layer.items():
            for ii in range(len(idxs)):
                for jj in range(ii + 1, len(idxs)):
                    a = segs[idxs[ii]]
                    b = segs[idxs[jj]]
                    if a[0] == b[0]:
                        continue
                    # cheap bbox reject
                    if (max(a[2][0], a[3][0]) + 2 < min(b[2][0], b[3][0])
                            or max(b[2][0], b[3][0]) + 2 < min(a[2][0], a[3][0])
                            or max(a[2][1], a[3][1]) + 2 < min(b[2][1], b[3][1])
                            or max(b[2][1], b[3][1]) + 2 < min(a[2][1], a[3][1])):
                        continue
                    need = a[4] / 2 + b[4] / 2 + self.clr(a[0], b[0])
                    d = seg_seg(a[2], a[3], b[2], b[3])
                    if d < need - 1e-4:
                        probs.append(f"seg-seg L{layer} {a[0]} {a[2]}-{a[3]} vs {b[0]} {b[2]}-{b[3]}: {d:.3f} < {need:.3f}")
        # via vs seg (vias block all layers)
        for net_v, pos, dia in vias:
            for net_s, layer, p1, p2, w in segs:
                if net_v == net_s:
                    continue
                if abs(pos[0] - (p1[0] + p2[0]) / 2) > abs(p1[0] - p2[0]) / 2 + 3 and \
                   abs(pos[1] - (p1[1] + p2[1]) / 2) > abs(p1[1] - p2[1]) / 2 + 3:
                    continue
                need = dia / 2 + w / 2 + self.clr(net_v, net_s)
                sx, sy = p2[0] - p1[0], p2[1] - p1[1]
                ln = sx * sx + sy * sy
                t = 0.0 if ln < 1e-12 else max(0.0, min(1.0, ((pos[0] - p1[0]) * sx + (pos[1] - p1[1]) * sy) / ln))
                d = math.hypot(pos[0] - p1[0] - t * sx, pos[1] - p1[1] - t * sy)
                if d < need - 1e-4:
                    probs.append(f"via-seg {net_v}@{pos} vs {net_s} L{layer} {p1}-{p2}: {d:.3f} < {need:.3f}")
        # via-via
        for i in range(len(vias)):
            for j in range(i + 1, len(vias)):
                a, b = vias[i], vias[j]
                if a[0] == b[0]:
                    continue
                need = a[2] / 2 + b[2] / 2 + self.clr(a[0], b[0])
                d = math.hypot(a[1][0] - b[1][0], a[1][1] - b[1][1])
                if d < need - 1e-4:
                    probs.append(f"via-via {a[0]}@{a[1]} vs {b[0]}@{b[1]}: {d:.3f} < {need:.3f}")
        # copper vs pads
        pads = self._pad_geometry()
        for net_s, layer, p1, p2, w in segs:
            for pnet, pname, x1, y1, x2, y2, smd in pads:
                if pnet == net_s:
                    continue
                if smd and layer != int(F_CU):
                    continue
                if min(p1[0], p2[0]) - 3 > x2 or max(p1[0], p2[0]) + 3 < x1:
                    continue
                if min(p1[1], p2[1]) - 3 > y2 or max(p1[1], p2[1]) + 3 < y1:
                    continue
                need = w / 2 + (self.clr(net_s, pnet) if pnet else self.rule(net_s)["clr"])
                d = d_seg_rect(p1, p2, x1, y1, x2, y2)
                if d < need - 1e-4:
                    probs.append(f"seg-pad {net_s} L{layer} {p1}-{p2} vs {pname}({pnet}): {d:.3f} < {need:.3f}")
        for net_v, pos, dia in vias:
            for pnet, pname, x1, y1, x2, y2, smd in pads:
                if pnet == net_v:
                    continue
                if pos[0] - 3 > x2 or pos[0] + 3 < x1 or pos[1] - 3 > y2 or pos[1] + 3 < y1:
                    continue
                need = dia / 2 + (self.clr(net_v, pnet) if pnet else self.rule(net_v)["clr"])
                dx = max(x1 - pos[0], 0, pos[0] - x2)
                dy = max(y1 - pos[1], 0, pos[1] - y2)
                d = math.hypot(dx, dy)
                if not smd and d < need - 1e-4:
                    probs.append(f"via-pad {net_v}@{pos} vs {pname}({pnet}): {d:.3f} < {need:.3f}")
                elif smd and d < need - 1e-4:
                    probs.append(f"via-padF {net_v}@{pos} vs {pname}({pnet}): {d:.3f} < {need:.3f}")
        # keepout rule areas (no tracks/vias inside)
        areas = []
        for z in self.board.Zones():
            if not z.GetIsRuleArea():
                continue
            bb = z.GetBoundingBox()
            areas.append((bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6))
        for net_s, layer, p1, p2, w in segs:
            for x1, y1, x2, y2 in areas:
                if d_seg_rect(p1, p2, x1, y1, x2, y2) < w / 2 - 1e-4:
                    probs.append(f"seg-keepout {net_s} L{layer} {p1}-{p2} in ({x1},{y1})-({x2},{y2})")
        for net_v, pos, dia in vias:
            for x1, y1, x2, y2 in areas:
                if x1 - dia / 2 < pos[0] < x2 + dia / 2 and y1 - dia / 2 < pos[1] < y2 + dia / 2:
                    probs.append(f"via-keepout {net_v}@{pos}")
        return probs


def assert_netclasses_active(board: pcbnew.BOARD) -> None:
    from collections import Counter
    settings = board.GetDesignSettings().m_NetSettings
    settings.RecomputeEffectiveNetclasses()
    names = [str(n) for n in board.GetNetsByName().keys() if str(n)]
    counts = Counter(settings.GetEffectiveNetClass(n).GetName() for n in names)
    if counts.get("Default", 0):
        raise SystemExit(f"ERROR: nets in Default class: {dict(counts)}")
    for cls, expected in NETCLASS_COUNTS.items():
        if counts.get(cls, 0) != expected:
            raise SystemExit(f"ERROR: netclass {cls} expected {expected}, got {counts.get(cls, 0)}: {dict(counts)}")
