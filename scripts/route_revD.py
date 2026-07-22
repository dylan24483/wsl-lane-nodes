#!/usr/bin/env python3
"""Manual, deterministic routing for WSL Phase 8 Rev-D.

NEW script — adapted from scripts/manual_route_revB.py (rev-C router is
SACRED and untouched). The rev-C geometry assumptions do not transfer
(Pico moved to the top edge, 40-row 5.7 mm input column, Rpu column at 86,
new AUX/tap/divider/J15/J16 parts), so every pass is re-derived for the
rev-D placement; machine-side passes carry the rev-C pattern.

Run from KiCad's bundled Python:
  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\route_revD.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_revD_lib import (
    Router, assert_netclasses_active, F_CU, B_CU, IN1_CU, IN2_CU,
    FAST_INPUTS, SLOW_A, SLOW_B, SLOW_C, MOTION, LAMPS, INPUT_ORDER,
    item_pos, row_y, mm, v,
)
import route_revD_logic as logic

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "kicad" / "revD" / "wsl-phase8b-revD.kicad_pcb"

WET_X = 55.3       # FIELD_WET_V backbone (B.Cu)
FGND_X = 5.5       # FIELD_GND backbone (B.Cu)
GNDRAIL_X = 83.3   # opto emitter GND rail (B.Cu)
V33_X = 84.3       # VCC_3V3 pullup backbone (B.Cu)
V33_TRUNK_X = 113.1  # VCC_3V3 logic trunk (IN2)
V5_TRUNK_X = 151.5   # VCC_5V trunk (B.Cu)
RAIL_X = 160.0       # RELAY_ENABLE_RAIL spine (B.Cu)


# --------------------------------------------------------------- field side
def route_field_led_series(r) -> int:
    added = 0
    for i, name in enumerate(INPUT_ORDER):
        net = f"FIELD_LED_{name}"
        y = row_y(i)
        if name == "SB":
            # Row 1 passes the wet-bleed pair (R122/R123): duck under on B.Cu.
            added += r.poly(net, [(58.913, 16.9), (60.3, 16.9)], F_CU)
            r.via(net, (60.3, 16.9)); added += 1
            added += r.poly(net, [(60.3, 16.9), (70.8, 16.9)], B_CU)
            r.via(net, (70.8, 16.9)); added += 1
            added += r.poly(net, [(70.8, 16.9), (72.0, 16.9), (72.0, 18.7), (74.0, 18.7)], F_CU)
            continue
        added += r.poly(net, [(58.913, y - 1.8), (72.0, y - 1.8), (72.0, y), (74.0, y)], F_CU)
    return added


def route_field_input_returns(r) -> int:
    """Connector pin -> opto pad 2 doglegs through B.Cu channel columns.

    Opto-side via ys are solved per net so no via or run lands within
    clearance of another net's connector-row run (the conn ys are on 3.5 mm
    grids that nearly coincide with some opto-row ys)."""
    added = 0
    geo = []
    for i, name in enumerate(INPUT_ORDER):
        prefix = "FIELD_FAST_" if name in FAST_INPUTS else "FIELD_SLOW_"
        net = prefix + name
        pads = r.pads_by_net().get(net, [])
        if len(pads) != 2:
            continue
        conn = min(pads, key=lambda p: item_pos(p)[0])
        opto = max(pads, key=lambda p: item_pos(p)[0])
        chx = 20.4 if name == "SB" else 12.0 + i * 1.05
        geo.append((name, net, item_pos(conn), item_pos(opto), chx))

    rin_rows = [row_y(k) - 1.8 for k in range(40)]
    placed = []
    vy_map = {}
    for name, net, (cx, cy), (ox, oy), chx in geo:
        if name == "SA":
            continue
        pick = None
        for vy in (oy, oy - 0.95, oy - 1.45, oy - 1.95, oy - 2.45, oy - 2.95, oy + 0.95):
            if any(abs(vy - c2) < 0.95 for n2, _, (c1, c2), _, x2 in
                   ((g[0], g[1], g[2], g[3], g[4]) for g in geo) if x2 > chx + 1e-9):
                continue
            if any(abs(vy - v) < 0.95 for v in placed):
                continue
            if any(abs(vy - ry) < 1.3 for ry in rin_rows):
                continue
            if 16.2 < vy < 20.6:
                continue
            bad = False
            for n2, _, (c1, c2), _, x2 in geo:
                if n2 != name and abs(x2 - chx) < 1.2:
                    if ((x2 - chx) ** 2 + (vy - c2) ** 2) ** 0.5 < 1.15:
                        bad = True
            if bad:
                continue
            pick = vy
            break
        if pick is None:
            raise SystemExit(f"no channel via_y for {net}")
        placed.append(pick)
        vy_map[name] = pick

    for name, net, (cx, cy), (ox, oy), chx in geo:
        if name == "SA":
            # Row 0: cross the bleed band at y=13 and dodge the wet backbone.
            added += r.poly(net, [(cx, cy), (chx, cy)], F_CU)
            r.via(net, (chx, cy)); added += 1
            added += r.poly(net, [(chx, cy), (chx, 13.0), (53.9, 13.0)], B_CU)
            r.via(net, (53.9, 13.0)); added += 1
            added += r.poly(net, [(53.9, 13.0), (71.2, 13.0), (71.2, oy), (ox, oy)], F_CU)
            continue
        vy = vy_map[name]
        added += r.poly(net, [(cx, cy), (chx, cy)], F_CU)
        r.via(net, (chx, cy)); added += 1
        added += r.poly(net, [(chx, cy), (chx, vy)], B_CU)
        r.via(net, (chx, vy)); added += 1
        if abs(vy - oy) < 1e-6:
            added += r.poly(net, [(chx, vy), (ox, oy)], F_CU)
        else:
            added += r.poly(net, [(chx, vy), (71.2, vy), (71.2, oy), (ox, oy)], F_CU)
    return added


def route_opto_pullups(r) -> int:
    """Opto pad4 -> Rpu pad2: south detour clears Rpu pad1 and the 3V3 via."""
    added = 0
    for i, name in enumerate(INPUT_ORDER):
        net = ("FAST_" if name in FAST_INPUTS else "SLOW_") + name
        y = row_y(i)
        added += r.poly(net, [(81.62, y), (83.5, y), (83.5, y + 3.3),
                              (86.912, y + 3.3), (86.912, y + 1.8)], F_CU)
    return added


def route_field_power(r) -> int:
    added = 0
    # ---- FIELD_WET_V ----
    wet_ys = [row_y(i) - 1.8 for i in range(40)]
    added += r.poly("FIELD_WET_V", [(72.3, 5.7), (WET_X, 5.7)], F_CU)
    r.via("FIELD_WET_V", (WET_X, 5.7)); added += 1
    added += r.poly("FIELD_WET_V", [(WET_X, 5.7), (WET_X, wet_ys[-1])], B_CU)
    for y in wet_ys:
        added += r.poly("FIELD_WET_V", [(57.087, y), (WET_X, y)], F_CU)
        r.via("FIELD_WET_V", (WET_X, y)); added += 1
    # bleed pair WET pads (south) join on a shared F.Cu tee at y=19.9
    added += r.poly("FIELD_WET_V", [(63.0, 16.913), (63.0, 19.9), (WET_X, 19.9)], F_CU)
    added += r.poly("FIELD_WET_V", [(67.0, 16.913), (67.0, 19.9), (63.0, 19.9)], F_CU)
    r.via("FIELD_WET_V", (WET_X, 19.9)); added += 1
    # TP4
    added += r.poly("FIELD_WET_V", [(22.0, 229.0), (22.0, 234.5), (WET_X, 234.5)], F_CU)
    r.via("FIELD_WET_V", (WET_X, 234.5)); added += 1
    added += r.poly("FIELD_WET_V", [(WET_X, wet_ys[-1]), (WET_X, 234.5)], B_CU)

    # ---- FIELD_GND ----
    conn_fgnd = [("J3", "9"), ("J3", "10"), ("J4", "14"), ("J5", "12"), ("J15", "9"), ("J15", "10")]
    ys = []
    for ref, pin in conn_fgnd:
        x, y = r.ppos(ref, pin)
        added += r.poly("FIELD_GND", [(x, y), (FGND_X, y)], B_CU)
        ys.append(y)
    added += r.poly("FIELD_GND", [(FGND_X, min(ys)), (FGND_X, max(ys))], B_CU)
    # U45 field return crosses the gutter above the keepout strip (y<8)
    added += r.poly("FIELD_GND", [(77.38, 5.7), (77.38, 7.55), (8.5, 7.55)], F_CU)
    r.via("FIELD_GND", (8.5, 7.55)); added += 1
    added += r.poly("FIELD_GND", [(8.5, 7.55), (FGND_X, min(ys))], B_CU)
    # bleed GND pads (north) tee together on F.Cu, duck under the SA return on
    # B.Cu, and land on the U45 crossing run at y=7.55.
    added += r.poly("FIELD_GND", [(63.0, 15.088), (67.0, 15.088)], F_CU)
    added += r.poly("FIELD_GND", [(65.0, 15.088), (65.0, 14.1)], F_CU)
    r.via("FIELD_GND", (65.0, 14.1)); added += 1
    added += r.poly("FIELD_GND", [(65.0, 14.1), (65.0, 7.55)], B_CU)
    r.via("FIELD_GND", (65.0, 7.55)); added += 1
    # TP5
    added += r.poly("FIELD_GND", [(34.0, 229.0), (34.0, 225.1), (FGND_X, 225.1)], F_CU)
    r.via("FIELD_GND", (FGND_X, 225.1)); added += 1
    added += r.poly("FIELD_GND", [(FGND_X, max(ys)), (FGND_X, 225.1)], B_CU)
    return added


# --------------------------------------------------------------- logic power
def route_gnd_rail(r) -> int:
    """Opto emitter (pad3) GND rail on B.Cu + zone stitch vias."""
    added = 0
    ys = [row_y(i) + 2.54 for i in range(40)]
    added += r.poly("GND", [(GNDRAIL_X, ys[0]), (GNDRAIL_X, ys[-1])], B_CU)
    for y in ys:
        added += r.poly("GND", [(81.62, y), (GNDRAIL_X, y)], B_CU)
    # U45 logic-side ground into the rail region
    added += r.poly("GND", [(82.46, 5.7), (GNDRAIL_X, 10.0), (GNDRAIL_X, ys[0])], B_CU)
    for y in (23.2, 131.5, 234.1):
        r.via("GND", (GNDRAIL_X, y)); added += 1
    return added


def route_3v3(r) -> int:
    added = 0
    ys = [row_y(i) + 1.8 for i in range(40)]
    # pullup backbone + stubs
    added += r.poly("VCC_3V3", [(V33_X, 12.3), (V33_X, ys[-1])], B_CU)
    for y in ys:
        added += r.poly("VCC_3V3", [(85.088, y), (V33_X, y)], F_CU)
        r.via("VCC_3V3", (V33_X, y)); added += 1
    # logic trunk (IN2) fed from the Pico 3V3_OUT (A1.36).
    # M4 ripple (remediation spec R2.5): J13's MCV pads grew 1.8 -> 2.0 mm,
    # so the straight trunk at x=113.1 would run 0.4 mm from J13.4's pad
    # edge — jog to x=112.75 (centered in the J13.3/J13.4 gap) past y=206.
    added += r.poly("VCC_3V3", [(109.69, 19.03), (V33_TRUNK_X, 19.03)], F_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 19.03)); added += 1
    added += r.poly("VCC_3V3", [(V33_TRUNK_X, 12.3), (V33_TRUNK_X, 201.2),
                                (112.75, 201.9), (112.75, 210.3),
                                (V33_TRUNK_X, 211.0), (V33_TRUNK_X, 224.1)], IN2_CU)
    # bridge trunk -> pullup backbone
    r.via("VCC_3V3", (V33_TRUNK_X, 12.3)); added += 1
    added += r.poly("VCC_3V3", [(V33_TRUNK_X, 12.3), (V33_X, 12.3)], B_CU)
    # J1.11 (148.2,10)
    added += r.poly("VCC_3V3", [(148.2, 10.0), (148.2, 16.3)], F_CU)
    r.via("VCC_3V3", (148.2, 16.3)); added += 1
    added += r.poly("VCC_3V3", [(148.2, 16.3), (V33_TRUNK_X, 16.3)], IN1_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 16.3)); added += 1
    # U1.9 / U2.9 (left col) via short IN2 tees
    x, y = r.ppos("U1", "9")
    added += r.poly("VCC_3V3", [(x, y), (115.9, y)], F_CU)
    r.via("VCC_3V3", (115.9, y)); added += 1
    added += r.poly("VCC_3V3", [(115.9, y), (V33_TRUNK_X, y)], IN2_CU)
    x, y = r.ppos("U2", "9")
    added += r.poly("VCC_3V3", [(x, y), (115.0, y), (115.0, 155.5),
                                (116.4, 156.4), (116.4, 157.0)], F_CU)
    r.via("VCC_3V3", (116.4, 157.0)); added += 1
    # U3 3V3 island: C3 -> (IN1 hop over the DRV_L stubs) -> pin 9 ->
    # pins 18/16 through the SOIC interior
    added += r.poly("VCC_3V3", [(139.05, 96.0), (138.6, 96.6), (138.6, 99.3)], F_CU)
    r.via("VCC_3V3", (138.6, 99.3)); added += 1
    added += r.poly("VCC_3V3", [(138.6, 99.3), (138.6, 112.3)], IN1_CU)
    r.via("VCC_3V3", (138.6, 112.3)); added += 1
    added += r.poly("VCC_3V3", [(138.6, 112.3), (138.2, 114.7),
                                (138.2, 118.985), (144.65, 118.985)], F_CU)
    added += r.poly("VCC_3V3", [(135.35, 113.905), (136.4, 114.35), (138.2, 114.7)], F_CU)
    added += r.poly("VCC_3V3", [(138.2, 116.445), (144.65, 116.445)], F_CU)
    # U1.18 (RESET) east stub -> B.Cu -> trunk
    x, y = r.ppos("U1", "18")
    added += r.poly("VCC_3V3", [(x, y), (128.6, y)], F_CU)
    r.via("VCC_3V3", (128.6, y)); added += 1
    added += r.poly("VCC_3V3", [(128.6, y), (V33_TRUNK_X, y)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, y)); added += 1
    # U2.15 / U2.18 (right col)
    x, y = r.ppos("U2", "15")
    added += r.poly("VCC_3V3", [(x, y), (128.7, y), (128.7, 157.0)], F_CU)
    r.via("VCC_3V3", (128.7, 157.0)); added += 1
    added += r.poly("VCC_3V3", [(128.7, 157.0), (V33_TRUNK_X, 157.0)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 157.0)); added += 1
    x, y = r.ppos("U2", "18")
    added += r.poly("VCC_3V3", [(x, y), (128.7, y), (128.7, 157.0)], F_CU)
    # R1.1 / R2.1 pullup tops (south pads) via a shared B.Cu run at y=90.1
    added += r.poly("VCC_3V3", [(103.0, 86.912), (103.9, 87.8), (103.9, 90.1), (100.2, 90.1)], F_CU)
    r.via("VCC_3V3", (100.2, 90.1)); added += 1
    added += r.poly("VCC_3V3", [(100.2, 90.1), (V33_TRUNK_X, 90.1)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 90.1)); added += 1
    added += r.poly("VCC_3V3", [(110.0, 86.912), (110.0, 90.1)], F_CU)
    r.via("VCC_3V3", (110.0, 90.1)); added += 1
    # C1 / C2 / C3 / C14 3V3 pads
    added += r.poly("VCC_3V3", [(115.05, 92.0), (V33_TRUNK_X, 92.0)], F_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 92.0)); added += 1
    added += r.poly("VCC_3V3", [(112.05, 130.0), (111.0, 130.0)], F_CU)
    r.via("VCC_3V3", (111.0, 130.0)); added += 1
    added += r.poly("VCC_3V3", [(111.0, 130.0), (V33_TRUNK_X, 130.0)], IN2_CU)
    # C3 (139.05,96) + C14 (139.05,78): B.Cu feeders from the trunk
    added += r.poly("VCC_3V3", [(139.05, 96.0), (137.9, 96.0)], F_CU)
    r.via("VCC_3V3", (137.9, 96.0)); added += 1
    added += r.poly("VCC_3V3", [(137.9, 96.0), (137.9, 94.4), (V33_TRUNK_X, 94.4)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 94.4)); added += 1
    added += r.poly("VCC_3V3", [(139.05, 78.0), (137.9, 78.0)], F_CU)
    r.via("VCC_3V3", (137.9, 78.0)); added += 1
    added += r.poly("VCC_3V3", [(137.9, 78.0), (V33_TRUNK_X, 78.0)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 78.0)); added += 1
    # J16.5 (142,206)
    added += r.poly("VCC_3V3", [(142.0, 206.0), (142.0, 211.4), (142.15, 212.4)], F_CU)
    r.via("VCC_3V3", (142.15, 212.4)); added += 1
    added += r.poly("VCC_3V3", [(142.15, 212.4), (V33_TRUNK_X, 212.4)], B_CU)
    r.via("VCC_3V3", (V33_TRUNK_X, 212.4)); added += 1
    # TP3 (120,229)
    r.via("VCC_3V3", (V33_TRUNK_X, 224.1)); added += 1
    added += r.poly("VCC_3V3", [(V33_TRUNK_X, 224.1), (120.0, 224.1), (120.0, 229.0)], F_CU)
    return added


def route_5v(r) -> int:
    added = 0
    # RAW: J2.1 -> D17.2
    added += r.poly("VCC_5V_RAW", [(116.0, 10.0), (116.0, 14.9), (124.0, 14.9), (124.0, 20.0)], F_CU)
    # hub at D17.1 -> B.Cu y=23 -> trunk
    added += r.poly("VCC_5V", [(120.0, 20.0), (118.4, 20.0)], F_CU)
    r.via("VCC_5V", (118.4, 20.0)); added += 1
    added += r.poly("VCC_5V", [(118.4, 20.0), (118.4, 23.0)], B_CU)
    added += r.poly("VCC_5V", [(114.2, 23.0), (V5_TRUNK_X, 23.0)], B_CU)
    added += r.poly("VCC_5V", [(V5_TRUNK_X, 11.4), (V5_TRUNK_X, 217.0)], B_CU)
    # U45.1 (85,5.7) across the top on F.Cu, dropping at x=114.2
    added += r.poly("VCC_5V", [(85.0, 5.7), (85.0, 1.55), (114.2, 1.55)], F_CU)
    r.via("VCC_5V", (114.2, 1.55)); added += 1
    added += r.poly("VCC_5V", [(114.2, 1.55), (114.2, 23.0)], B_CU)
    # J1.1 (135.5,10): dogleg east clear of the ARM_PERMIT vertical
    added += r.poly("VCC_5V", [(135.5, 10.0), (135.5, 11.4), (136.6, 11.4)], F_CU)
    r.via("VCC_5V", (136.6, 11.4)); added += 1
    added += r.poly("VCC_5V", [(136.6, 11.4), (V5_TRUNK_X, 11.4)], B_CU)
    # J14.1 (167,10)
    added += r.poly("VCC_5V", [(167.0, 10.0), (167.0, 14.0)], F_CU)
    r.via("VCC_5V", (167.0, 14.0)); added += 1
    added += r.poly("VCC_5V", [(167.0, 14.0), (V5_TRUNK_X, 14.0)], B_CU)
    # U44.4 (148.525,51.905): drop south, clear of the TRIG vertical
    added += r.poly("VCC_5V", [(148.525, 51.905), (148.525, 54.9), (149.9, 54.9)], F_CU)
    r.via("VCC_5V", (149.9, 54.9)); added += 1
    added += r.poly("VCC_5V", [(149.9, 54.9), (V5_TRUNK_X, 54.9)], B_CU)
    # U44.8 (153.475,48.095)
    added += r.poly("VCC_5V", [(153.475, 48.095), (153.475, 45.6)], F_CU)
    r.via("VCC_5V", (153.475, 45.6)); added += 1
    added += r.poly("VCC_5V", [(153.475, 45.6), (V5_TRUNK_X, 45.6)], B_CU)
    # R116.1 (146,40.913)
    added += r.poly("VCC_5V", [(146.0, 40.913), (145.55, 41.5), (145.55, 43.4)], F_CU)
    r.via("VCC_5V", (145.55, 43.4)); added += 1
    added += r.poly("VCC_5V", [(145.55, 43.4), (V5_TRUNK_X, 43.4)], B_CU)
    # C12.1 (156,67.95): east stub, IN1 hop over the B.Cu verticals
    added += r.poly("VCC_5V", [(156.0, 67.95), (157.2, 67.95)], F_CU)
    r.via("VCC_5V", (157.2, 67.95)); added += 1
    added += r.poly("VCC_5V", [(157.2, 67.95), (151.9, 67.95)], IN1_CU)
    r.via("VCC_5V", (151.9, 67.95)); added += 1
    added += r.poly("VCC_5V", [(151.9, 67.95), (V5_TRUNK_X, 67.95)], B_CU)
    # R117.1 (145,78.912)
    added += r.poly("VCC_5V", [(145.0, 78.912), (146.3, 78.4), (146.9, 78.4)], F_CU)
    r.via("VCC_5V", (146.9, 78.4)); added += 1
    added += r.poly("VCC_5V", [(146.9, 78.4), (V5_TRUNK_X, 78.4)], B_CU)
    # R129.1 (114,41.913) ADC divider top
    added += r.poly("VCC_5V", [(114.0, 41.913), (115.4, 41.913), (115.4, 40.0)], F_CU)
    r.via("VCC_5V", (115.4, 40.0)); added += 1
    added += r.poly("VCC_5V", [(115.4, 40.0), (V5_TRUNK_X, 40.0)], B_CU)
    # J16.1 (128,206) on IN1 (clears the WDOG_KICK tail)
    added += r.poly("VCC_5V", [(128.0, 206.0), (128.0, 210.8), (V5_TRUNK_X, 210.8)], IN1_CU)
    r.via("VCC_5V", (V5_TRUNK_X, 210.8)); added += 1
    # J13.1 (104,206) on IN1 (dodges the TRIG/KICK verticals)
    added += r.poly("VCC_5V", [(104.0, 206.0), (104.0, 203.7), (V5_TRUNK_X, 203.7)], IN1_CU)
    r.via("VCC_5V", (V5_TRUNK_X, 203.7)); added += 1
    # A1.39 VUSB?  (109.69,11.41) — feed from the trunk region on IN1
    added += r.poly("VCC_5V", [(109.69, 11.41), (111.9, 11.41)], F_CU)
    r.via("VCC_5V", (111.9, 11.41)); added += 1
    added += r.poly("VCC_5V", [(111.9, 11.41), (114.2, 11.41)], B_CU)
    # TP1 (100,229) on IN1 y=217
    r.via("VCC_5V", (V5_TRUNK_X, 217.0)); added += 1
    added += r.poly("VCC_5V", [(V5_TRUNK_X, 217.0), (100.0, 217.0)], IN1_CU)
    r.via("VCC_5V", (100.0, 217.0)); added += 1
    added += r.poly("VCC_5V", [(100.0, 217.0), (100.0, 229.0)], F_CU)
    return added


# --------------------------------------------------------- watchdog / safety
def route_watchdog(r) -> int:
    added = 0

    def local_trunk(net, refs_pins, trunk_x):
        pads = [r.ppos(ref, pin) for ref, pin in refs_pins]
        ys = [p[1] for p in pads]
        n = r.poly(net, [(trunk_x, min(ys)), (trunk_x, max(ys))], F_CU)
        for x, y in pads:
            n += r.poly(net, [(x, y), (trunk_x, y)], F_CU)
        return n

    added += local_trunk("WDOG_KICK_GATE", [("R118", "2"), ("Q12", "1"), ("R119", "1")], 139.5)
    added += local_trunk("RAIL_GATE", [("Q14", "1"), ("R124", "2"), ("Q15", "3")], 146.2)
    added += local_trunk("BASE_AND_ARM", [("R125", "2"), ("Q15", "1"), ("R126", "1")], 136.0)

    added += r.poly("NE555_CTRL", [r.ppos("C13", "1"), (166.0, 51.905), r.ppos("U44", "5")], F_CU)

    added += r.poly("AND_MID_ARM_RP", [r.ppos("Q15", "2"), (144.8, 92.95), (144.8, 97.8),
                                       (163.2, 97.8), (163.2, 96.0), r.ppos("Q16", "3")], F_CU)

    trunk_x = 168.0
    added += r.poly("BASE_AND_RP_OK", [(trunk_x, 89.088), (trunk_x, 98.912)], F_CU)
    for ref, pin in (("R127", "2"), ("R128", "1")):
        p = r.ppos(ref, pin)
        added += r.poly("BASE_AND_RP_OK", [p, (trunk_x, p[1])], F_CU)
    q16 = r.ppos("Q16", "1")
    added += r.poly("BASE_AND_RP_OK", [q16, (156.8, q16[1]), (trunk_x, q16[1])], F_CU)

    for ref, pin in (("R120", "2"), ("Q13", "1"), ("R121", "1")):
        p = r.ppos(ref, pin)
        added += r.poly("WDOG_OK_GATE", [p, (164.8, p[1])], F_CU)
        r.via("WDOG_OK_GATE", (164.8, p[1])); added += 1
    added += r.poly("WDOG_OK_GATE", [(164.8, r.ppos("R120", "2")[1]), (164.8, r.ppos("R121", "1")[1])], IN1_CU)

    # NE555_OUT: U44.3 + R120.1 + R131.1 + TP11
    u44_out = r.ppos("U44", "3")
    r120 = r.ppos("R120", "1")
    added += r.poly("NE555_OUT", [u44_out, (146.3, u44_out[1])], F_CU)
    r.via("NE555_OUT", (146.3, u44_out[1])); added += 1
    added += r.poly("NE555_OUT", [r120, (163.0, r120[1])], F_CU)
    r.via("NE555_OUT", (163.0, r120[1])); added += 1
    added += r.poly("NE555_OUT", [(146.3, 34.3), (146.3, u44_out[1])], IN1_CU)
    added += r.poly("NE555_OUT", [(146.3, u44_out[1]), (146.3, 53.0), (163.0, 53.0), (163.0, r120[1])], IN1_CU)
    added += r.poly("NE555_OUT", [(145.088, 33.0), (144.5, 33.0)], F_CU)
    r.via("NE555_OUT", (144.5, 33.0)); added += 1
    added += r.poly("NE555_OUT", [(144.5, 33.0), (144.5, 34.3), (146.3, 34.3)], IN1_CU)
    r.via("NE555_OUT", (156.0, 53.0)); added += 1
    added += r.poly("NE555_OUT", [(156.0, 53.0), (156.0, 232.85)], B_CU)
    r.via("NE555_OUT", (156.0, 232.85)); added += 1
    added += r.poly("NE555_OUT", [(156.0, 232.85), (120.0, 232.85), (120.0, 236.0)], F_CU)

    # timing / trigger / drain locals (rev-C pattern, same coordinates)
    added += r.poly("WDOG_TIMING_NODE", [r.ppos("D15", "2"), (153.05, 37.2), (146.0, 37.2), r.ppos("R116", "2")], F_CU)
    added += r.poly("WDOG_TIMING_NODE", [r.ppos("D15", "2"), (153.05, 44.8), r.ppos("C11", "1")], F_CU)
    added += r.poly("WDOG_TIMING_NODE", [r.ppos("C11", "1"), (158.0, 44.8), (158.0, 49.365), r.ppos("U44", "7")], F_CU)
    added += r.poly("WDOG_TIMING_NODE", [r.ppos("U44", "7"), r.ppos("U44", "6")], F_CU)

    added += r.poly("WDOG_KICK_DRAIN", [r.ppos("D15", "1"), (150.95, 32.8), (157.95, 32.8), r.ppos("D16", "1")], F_CU)
    added += r.poly("WDOG_KICK_DRAIN", [r.ppos("D15", "1"), (149.0, 35.0)], F_CU)
    r.via("WDOG_KICK_DRAIN", (149.0, 35.0)); added += 1
    added += r.poly("WDOG_KICK_DRAIN", [r.ppos("Q12", "3"), (144.8, 58.0)], F_CU)
    r.via("WDOG_KICK_DRAIN", (144.8, 58.0)); added += 1
    added += r.poly("WDOG_KICK_DRAIN", [(149.0, 35.0), (144.8, 35.0), (144.8, 58.0)], IN2_CU)

    for ref, pin, via_xy in (("U44", "2", (147.0, 49.365)),
                             ("D16", "2", (162.2, 35.0))):
        added += r.poly("NE555_TRIG", [r.ppos(ref, pin), via_xy], F_CU)
        r.via("NE555_TRIG", via_xy); added += 1
    added += r.poly("NE555_TRIG", [(162.2, 35.0), (162.2, 29.8), (147.0, 29.8), (147.0, 49.365)], IN1_CU)
    added += r.poly("NE555_TRIG", [(147.0, 49.365), (147.0, 75.4), (144.65, 76.6)], IN2_CU)
    r.via("NE555_TRIG", (144.65, 76.6)); added += 1
    added += r.poly("NE555_TRIG", [(144.65, 76.6), (145.0, 77.088)], F_CU)

    # WDOG_OK_PULLDOWN: Q13.3 + Q16.2 + TP12
    added += r.poly("WDOG_OK_PULLDOWN", [r.ppos("Q13", "3"), (163.6, 58.0)], F_CU)
    r.via("WDOG_OK_PULLDOWN", (163.6, 58.0)); added += 1
    added += r.poly("WDOG_OK_PULLDOWN", [r.ppos("Q16", "2"), (162.0, 96.95)], F_CU)
    r.via("WDOG_OK_PULLDOWN", (162.0, 96.95)); added += 1
    added += r.poly("WDOG_OK_PULLDOWN", [(163.6, 58.0), (163.6, 96.95), (162.0, 96.95)], IN2_CU)
    added += r.poly("WDOG_OK_PULLDOWN", [(163.6, 96.95), (163.6, 233.75)], IN2_CU)
    r.via("WDOG_OK_PULLDOWN", (163.6, 233.75)); added += 1
    added += r.poly("WDOG_OK_PULLDOWN", [(163.6, 233.75), (128.0, 233.75), (128.0, 236.0)], F_CU)

    added += r.poly("SAFE_STOP_RETURN", [r.ppos("R124", "1"), (157.062, 82.95), r.ppos("Q14", "2")], F_CU)
    return added


def route_header_safety(r) -> int:
    """J1/J14 watchdog + safety header nets and their test-pad tails."""
    added = 0
    # WDOG_KICK: J1.7 -> IN2 x=143.12 -> R118.1/R133.1; tail B.Cu x=143.75 -> TP8
    added += r.poly("WDOG_KICK", [(143.12, 10.0), (143.12, 13.2)], F_CU)
    r.via("WDOG_KICK", (143.12, 13.2)); added += 1
    added += r.poly("WDOG_KICK", [(143.12, 13.2), (143.12, 49.3)], IN2_CU)
    r.via("WDOG_KICK", (143.12, 49.3)); added += 1
    added += r.poly("WDOG_KICK", [(143.12, 49.3), (142.9, 47.913), (142.0, 47.913)], F_CU)
    added += r.poly("WDOG_KICK", [(136.0, 47.912), (136.6, 48.8), (136.6, 52.4)], F_CU)
    r.via("WDOG_KICK", (136.6, 52.4)); added += 1
    added += r.poly("WDOG_KICK", [(136.6, 52.4), (143.3, 52.4)], B_CU)
    added += r.poly("WDOG_KICK", [(143.12, 49.3), (143.3, 49.9), (143.3, 202.5), (143.75, 203.5),
                                  (143.75, 209.0), (143.3, 210.0), (143.3, 226.9)], B_CU)
    r.via("WDOG_KICK", (143.3, 226.9)); added += 1
    added += r.poly("WDOG_KICK", [(143.3, 226.9), (150.0, 226.9), (150.0, 229.0)], F_CU)

    # ARM_PERMIT: J1.8 -> IN2 x=139.5 -> R125.1 -> (J16 jog at 140.25) -> TP13
    added += r.poly("ARM_PERMIT", [(143.12, 7.46), (143.12, 4.6)], F_CU)
    r.via("ARM_PERMIT", (143.12, 4.6)); added += 1
    added += r.poly("ARM_PERMIT", [(143.12, 4.6), (133.9, 4.6), (133.9, 90.912), (132.9, 90.912)], IN2_CU)
    r.via("ARM_PERMIT", (132.9, 90.912)); added += 1
    added += r.poly("ARM_PERMIT", [(133.0, 90.912), (132.9, 90.912)], F_CU)
    added += r.poly("ARM_PERMIT", [(130.0, 70.912), (130.0, 74.0), (132.5, 74.0)], F_CU)
    r.via("ARM_PERMIT", (132.5, 74.0)); added += 1
    added += r.poly("ARM_PERMIT", [(132.5, 74.0), (133.9, 74.0)], IN2_CU)
    added += r.poly("ARM_PERMIT", [(133.9, 90.912), (133.9, 96.5), (139.5, 101.5),
                                   (139.5, 201.0), (140.25, 201.9),
                                   (140.25, 209.5), (139.5, 210.4), (139.5, 234.6)], IN2_CU)
    r.via("ARM_PERMIT", (139.5, 234.6)); added += 1
    added += r.poly("ARM_PERMIT", [(139.5, 234.6), (136.0, 234.6), (136.0, 236.0)], F_CU)

    # RP2040_OK: A1.4 + J1.13 + R135.1 + R127.1 + TP14 on IN2 trunk x=168.4
    added += r.poly("RP2040_OK", [(90.31, 16.49), (88.9, 16.49), (88.9, 17.8), (86.4, 17.8)], F_CU)
    r.via("RP2040_OK", (86.4, 17.8)); added += 1
    added += r.poly("RP2040_OK", [(86.4, 17.8), (86.4, 80.0)], IN2_CU)
    r.via("RP2040_OK", (86.4, 80.0)); added += 1
    added += r.poly("RP2040_OK", [(86.4, 80.0), (162.2, 80.0)], IN1_CU)
    r.via("RP2040_OK", (162.2, 80.0)); added += 1
    added += r.poly("RP2040_OK", [(162.2, 80.0), (168.4, 80.0)], B_CU)
    r.via("RP2040_OK", (168.4, 80.0)); added += 1
    added += r.poly("RP2040_OK", [(150.74, 10.0), (150.74, 15.0)], F_CU)
    r.via("RP2040_OK", (150.74, 15.0)); added += 1
    added += r.poly("RP2040_OK", [(150.74, 15.0), (163.3, 15.0)], IN1_CU)
    r.via("RP2040_OK", (163.3, 15.0)); added += 1
    added += r.poly("RP2040_OK", [(163.3, 15.0), (168.4, 15.0)], B_CU)
    r.via("RP2040_OK", (168.4, 15.0)); added += 1
    added += r.poly("RP2040_OK", [(168.4, 15.0), (168.4, 234.6)], IN2_CU)
    # R135.1 branch: around the west/south of C12, B.Cu y=70.3 to the trunk
    added += r.poly("RP2040_OK", [(155.088, 64.0), (154.7, 64.4), (154.7, 69.9), (158.6, 69.9)], F_CU)
    r.via("RP2040_OK", (158.6, 69.9)); added += 1
    added += r.poly("RP2040_OK", [(158.6, 69.9), (168.4, 69.9)], B_CU)
    r.via("RP2040_OK", (168.4, 69.9)); added += 1
    # R127.1 branch (rev-C jog)
    added += r.poly("RP2040_OK", [(168.4, 90.912), (170.0, 90.912)], IN2_CU)
    r.via("RP2040_OK", (170.0, 90.912)); added += 1
    added += r.poly("RP2040_OK", [(170.0, 90.912), (170.0, 90.912)], F_CU)
    added += r.poly("RP2040_OK", [r.ppos("R127", "1"), (170.0, 90.912)], F_CU)
    # TP14 tail
    r.via("RP2040_OK", (168.4, 234.6)); added += 1
    added += r.poly("RP2040_OK", [(168.4, 234.6), (144.0, 234.6), (144.0, 236.0)], F_CU)

    # SAFE_STOP_RETURN: J14.4 -> IN1 -> (153.4,83.1) -> TP15
    added += r.poly("SAFE_STOP_RETURN", [(177.5, 10.0), (177.5, 13.0)], F_CU)
    r.via("SAFE_STOP_RETURN", (177.5, 13.0)); added += 1
    added += r.poly("SAFE_STOP_RETURN", [(177.5, 13.0), (165.75, 13.0), (165.75, 83.1), (153.4, 83.1)], IN1_CU)
    r.via("SAFE_STOP_RETURN", (153.4, 83.1)); added += 1
    added += r.poly("SAFE_STOP_RETURN", [(153.4, 83.1), (155.4, 83.1), (157.062, 82.95)], F_CU)
    added += r.poly("SAFE_STOP_RETURN", [(153.4, 83.1), (153.4, 235.75)], IN1_CU)
    r.via("SAFE_STOP_RETURN", (153.4, 235.75)); added += 1
    added += r.poly("SAFE_STOP_RETURN", [(153.4, 235.75), (152.75, 235.75), (152.0, 236.0)], F_CU)

    # SAFE_TBSC_RETURN: adjacent J14 pins
    added += r.poly("SAFE_TBSC_RETURN", [(170.5, 10.0), (174.0, 10.0)], F_CU)

    # WDOG_TIMING_NODE tail -> TP9
    wt = (154.8, 50.0)
    added += r.poly("WDOG_TIMING_NODE", [r.ppos("U44", "6"), (154.8, 50.635), wt], F_CU)
    r.via("WDOG_TIMING_NODE", wt); added += 1
    added += r.poly("WDOG_TIMING_NODE", [wt, (154.8, 230.4)], IN2_CU)
    r.via("WDOG_TIMING_NODE", (154.8, 230.4)); added += 1
    added += r.poly("WDOG_TIMING_NODE", [(154.8, 230.4), (100.0, 230.4), (100.0, 236.0)], F_CU)

    # NE555_TRIG tail -> TP10 (IN2 x=144.65 with J16 gap jog)
    added += r.poly("NE555_TRIG", [(144.65, 76.6), (144.65, 199.5), (143.75, 200.5),
                                   (143.75, 209.5), (144.65, 210.5), (144.65, 232.05)], IN2_CU)
    r.via("NE555_TRIG", (144.65, 232.05)); added += 1
    added += r.poly("NE555_TRIG", [(144.65, 232.05), (110.0, 232.05), (110.0, 236.0)], F_CU)
    return added


# ------------------------------------------------------- drivers and lamps
def route_relay_drivers(r) -> int:
    added = 0
    for name in MOTION:
        base = f"BASE_{name}"
        pads = r.pads_by_net().get(base, [])
        if len(pads) == 2:
            rp = min(pads, key=lambda p: item_pos(p)[0])
            qp = max(pads, key=lambda p: item_pos(p)[0])
            (rx, ry), (qx, qy) = item_pos(rp), item_pos(qp)
            jog = min(ry, qy) - 1.35
            added += r.poly(base, [(rx, ry), (rx, jog), (qx, jog), (qx, qy)], F_CU)
        coil = f"COIL_LO_{name}"
        pads = r.pads_by_net().get(coil, [])
        if pads:
            xs = [item_pos(p)[0] for p in pads]
            ys = [item_pos(p)[1] for p in pads]
            trunk_x = 166.8
            added += r.poly(coil, [(trunk_x, min(ys)), (trunk_x, max(ys))], IN1_CU)
            for p in pads:
                x, y = item_pos(p)
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    r.via(coil, (trunk_x, y)); added += 1
                    added += r.poly(coil, [(x, y), (trunk_x, y)], F_CU)
                else:
                    added += r.poly(coil, [(x, y), (trunk_x, y)], IN1_CU)
    return added


def route_safety_rail(r) -> int:
    added = 0
    rail = "RELAY_ENABLE_RAIL"
    pads = r.pads_by_net().get(rail, [])
    krefs = [p for p in pads if p.GetParentFootprint().GetReference().startswith("K")]
    others = [p for p in pads if not p.GetParentFootprint().GetReference().startswith("K")]
    ys = [item_pos(p)[1] for p in pads if not p.GetParentFootprint().GetReference().startswith("TP")]
    y1 = min(ys)
    added += r.poly(rail, [(RAIL_X, y1), (RAIL_X, 213.0)], B_CU)
    for p in krefs:
        x, y = item_pos(p)
        dog = y + 3.0
        added += r.poly(rail, [(RAIL_X, dog), (x, dog), (x, y)], B_CU)
    for p in others:
        ref = p.GetParentFootprint().GetReference()
        x, y = item_pos(p)
        if ref == "TP16":
            continue
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            r.via(rail, (RAIL_X, y)); added += 1
            added += r.poly(rail, [(x, y), (RAIL_X, y)], F_CU)
        else:
            added += r.poly(rail, [(x, y), (RAIL_X, y)], B_CU)
    # D1..D7 rail-side pads are SMD at x=162.95 -> stubs+vias handled above.
    # TP16 approach from the east (keeps the bottom slot band clear)
    added += r.poly(rail, [(RAIL_X, 213.0), (161.6, 214.4), (161.6, 236.0)], B_CU)
    r.via(rail, (161.6, 236.0)); added += 1
    added += r.poly(rail, [(161.6, 236.0), (160.0, 236.0)], F_CU)
    return added


def route_status_leds(r) -> int:
    added = 0
    sink_vx = {"L_FIRST": 105.0, "L_SECOND": 118.912, "L_STRIKE": 130.912, "L_FOUL": 142.0}
    # return bus: F.Cu escape to a via, then a B.Cu dogleg down to the J13 pin
    ret_path = {
        "L_FIRST": ([(103.088, 182.0), (100.7, 182.0)], (100.7, 182.0),
                    [(100.7, 182.0), (100.7, 199.5), (111.0, 199.5), (111.0, 206.0)]),
        "L_SECOND": ([(115.088, 182.0), (112.2, 182.0)], (112.2, 182.0),
                     [(112.2, 182.0), (112.2, 201.6), (114.5, 201.6), (114.5, 206.0)]),
        "L_STRIKE": ([(127.088, 182.0), (126.2, 182.0), (126.2, 180.2), (129.6, 180.2)], (129.6, 180.2),
                     [(129.6, 180.2), (129.6, 199.15), (118.0, 199.15), (118.0, 206.0)]),
        "L_FOUL": ([(139.088, 182.0), (138.2, 182.0), (138.2, 180.0), (140.6, 180.0)], (140.6, 180.0),
                   [(140.6, 180.0), (140.6, 200.6), (120.9, 200.6), (120.9, 206.0)]),
    }
    for name in LAMPS:
        sink = f"LED_SINK_{name}"
        pads = r.pads_by_net().get(sink, [])
        if len(pads) == 2:
            a, b = sorted(pads, key=lambda p: item_pos(p)[1])
            (ax, ay), (bx, by) = item_pos(a), item_pos(b)
            vx = sink_vx[name]
            added += r.poly(sink, [(ax, ay), (vx, ay)], F_CU)
            r.via(sink, (vx, ay)); added += 1
            added += r.poly(sink, [(vx, ay), (vx, by)], B_CU)
            r.via(sink, (vx, by)); added += 1
            added += r.poly(sink, [(vx, by), (bx, by)], F_CU)
        ret = f"LED_{name}_RETURN"
        pads = r.pads_by_net().get(ret, [])
        if len(pads) == 2:
            fpts, via_xy, path = ret_path[name]
            added += r.poly(ret, fpts, F_CU)
            r.via(ret, via_xy); added += 1
            added += r.poly(ret, path, B_CU)
        gate = f"LED_GATE_{name}"
        gpads = sorted(r.pads_by_net().get(gate, []), key=lambda p: item_pos(p)[0])
        if len(gpads) == 3:
            rg, qg, rpd = (item_pos(p) for p in gpads)
            left_x = rg[0] - 2.0
            right_x = 120.2 if name == "L_SECOND" else rpd[0] + 2.0
            join_y = qg[1]
            added += r.poly(gate, [rg, (left_x, rg[1]), (left_x, join_y), qg], F_CU)
            added += r.poly(gate, [rpd, (right_x, rpd[1]), (right_x, join_y), qg], F_CU)
    return added


def route_drv(r) -> int:
    """U3 -> relay driver / lamp gate DRV_* fanout (rev-C pattern, U3 unmoved)."""
    added = 0
    for name in MOTION:
        net = f"DRV_{name}"
        rpads = [p for p in r.pads_by_net().get(net, [])
                 if p.GetParentFootprint().GetReference().startswith("R") and p.GetNumber() == "1"]
        if len(rpads) == 2:
            a, b = sorted(rpads, key=lambda p: item_pos(p)[1])
            (ax, ay), (bx, by) = item_pos(a), item_pos(b)
            added += r.poly(net, [(ax, ay), (147.8, ay), (147.8, by), (bx, by)], F_CU)
    routes = [
        ("DRV_SP", "23", None),
        ("DRV_T", "22", (147.0, (93.912,))),
        ("DRV_S", "21", (144.0, (71.912,))),
        ("DRV_BE", "24", (148.2, (131.912,))),
        ("DRV_M", "25", (145.5, (153.912,))),
        ("DRV_M2", "26", (149.2, (175.912,))),
        ("DRV_M1", "27", (150.2, (197.912,))),
    ]
    added += r.poly("DRV_SP", [r.ppos("U3", "23"), (147.8, 110.095), (147.8, 109.912)], F_CU)
    for net, pin, drop in routes[1:]:
        sx, sy = r.ppos("U3", pin)
        dx, (dy,) = drop
        added += r.poly(net, [(sx, sy), (dx, sy)], F_CU)
        r.via(net, (dx, sy)); added += 1
        added += r.poly(net, [(dx, sy), (dx, dy)], IN2_CU)
        r.via(net, (dx, dy)); added += 1
        added += r.poly(net, [(dx, dy), (147.8, dy)], F_CU)
    # lamp DRV_L_* : U3 pins 1-3,28 -> Rgled pad1 (tgt_x, 190.912).
    # IN2 lanes 135.6-137.7 run inside/beside U3 (SMD - inner layers free).
    added += r.poly("DRV_L_FIRST", [(144.65, 103.745), (144.65, 101.6), (135.6, 101.6)], F_CU)
    r.via("DRV_L_FIRST", (135.6, 101.6)); added += 1
    added += r.poly("DRV_L_FIRST", [(135.6, 101.6), (135.6, 184.55)], IN2_CU)
    r.via("DRV_L_FIRST", (135.6, 184.55)); added += 1
    added += r.poly("DRV_L_FIRST", [(135.6, 184.55), (102.6, 184.55), (102.6, 190.912), (101.0, 190.912)], F_CU)

    added += r.poly("DRV_L_SECOND", [(135.35, 103.745), (135.35, 102.9), (136.3, 102.9)], F_CU)
    r.via("DRV_L_SECOND", (136.3, 102.9)); added += 1
    added += r.poly("DRV_L_SECOND", [(136.3, 102.9), (136.3, 185.25)], IN2_CU)
    r.via("DRV_L_SECOND", (136.3, 185.25)); added += 1
    added += r.poly("DRV_L_SECOND", [(136.3, 185.25), (114.6, 185.25), (114.6, 190.912), (113.0, 190.912)], F_CU)

    added += r.poly("DRV_L_STRIKE", [(135.35, 105.015), (136.2, 105.65), (137.0, 105.65)], F_CU)
    r.via("DRV_L_STRIKE", (137.0, 105.65)); added += 1
    added += r.poly("DRV_L_STRIKE", [(137.0, 105.65), (137.0, 185.95)], IN2_CU)
    r.via("DRV_L_STRIKE", (137.0, 185.95)); added += 1
    added += r.poly("DRV_L_STRIKE", [(137.0, 185.95), (126.6, 185.95), (126.6, 190.912), (125.0, 190.912)], F_CU)

    added += r.poly("DRV_L_FOUL", [(135.35, 106.285), (136.4, 106.92), (137.7, 106.92)], F_CU)
    r.via("DRV_L_FOUL", (137.7, 106.92)); added += 1
    added += r.poly("DRV_L_FOUL", [(137.7, 106.92), (137.7, 186.65)], IN2_CU)
    r.via("DRV_L_FOUL", (137.7, 186.65)); added += 1
    added += r.poly("DRV_L_FOUL", [(137.7, 186.65), (138.6, 186.65), (138.6, 190.912), (137.0, 190.912)], F_CU)
    return added


# ------------------------------------------------------------- machine side
def route_machine(r) -> int:
    added = 0

    def projection(start, end, x):
        sx, sy = start
        ex, ey = end
        if abs(ex - sx) < 1e-3:
            return (x, sy)
        t = max(0.0, min(1.0, (x - sx) / (ex - sx)))
        return (x, sy + (ey - sy) * t)

    for name in MOTION:
        for suffix in ("B", "A"):
            net = f"OUT_{name}_{suffix}"
            pads = r.pads_by_net().get(net, [])
            relay = [p for p in pads if p.GetParentFootprint().GetReference().startswith("K")]
            conn = [p for p in pads if p.GetParentFootprint().GetReference().startswith("J")]
            if not relay or not conn:
                continue
            start = item_pos(relay[0])
            end = item_pos(conn[0])
            is_a = suffix == "A"
            core_layer = B_CU if is_a else IN2_CU
            core_points = [start, end]
            escapes = []
            for p in pads:
                ref = p.GetParentFootprint().GetReference()
                if not ref.startswith(("R", "C", "D")):
                    continue
                px, py = item_pos(p)
                if ref.startswith("R"):
                    ey = py + 2.2
                elif ref.startswith("C"):
                    ey = py - 2.2
                else:
                    ey = py - 2.4
                side_x = 216.0 if is_a else 228.0
                side = (side_x, ey)
                proj_x = max(min(side_x, max(start[0], end[0]) - 0.5), min(start[0], end[0]) + 0.5)
                proj = projection(start, end, proj_x)
                added += r.poly(net, [(px, py), (side_x, py), side], F_CU)
                r.via(net, side); added += 1
                escapes.append((side, proj))
                core_points.append(proj)
            core_points = sorted(core_points, key=lambda xy: (xy[0] - start[0]) ** 2 + (xy[1] - start[1]) ** 2)
            added += r.poly(net, core_points, core_layer)
            for side, proj in escapes:
                added += r.poly(net, [side, proj], core_layer)

    for name in MOTION:
        snub = f"SNUB_{name}"
        pads = r.pads_by_net().get(snub, [])
        if len(pads) == 2:
            a, b = sorted(pads, key=lambda p: item_pos(p)[0])
            (ax, ay), (bx, by) = item_pos(a), item_pos(b)
            mid = (ax + bx) / 2.0
            added += r.poly(snub, [(ax, ay), (mid, ay), (mid, by), (bx, by)], F_CU)
    return added


# ---------------------------------------------------- power-via redundancy
def route_power_via_redundancy(r) -> int:
    """RD-VIA-1 (run log, 2026-07-20): double the five single-point power
    vias with a twin barrel ON an existing same-net track plus a short
    same-net stub on the complementary layer — two truly parallel barrels
    per junction. Originally applied as a manual post-route board edit;
    emitted by the router since 2026-07-21 (remediation M2 batch) so the
    routed artifact is fully reproducible from this script. Copper-only:
    no netlist / pad-membership / netclass change. Twin coordinates are the
    run-log-recorded finals (incl. the (160, 81.0) north re-placement that
    keeps the F.Cu GND zone neck at ~(160, 83-84) intact)."""
    added = 0
    twins = [
        # (net, original via, twin via, stub layer)
        ("VCC_5V", (118.4, 20.0), (118.4, 21.0), F_CU),
        ("VCC_5V", (167.0, 14.0), (164.7, 14.0), F_CU),
        ("SAFE_STOP_RETURN", (177.5, 13.0), (176.5, 13.0), F_CU),
        ("SAFE_STOP_RETURN", (153.4, 83.1), (150.5, 82.923), IN1_CU),
        ("RELAY_ENABLE_RAIL", (160.0, 82.0), (160.0, 81.0), F_CU),
    ]
    for net, orig, twin, stub_layer in twins:
        r.via(net, twin); added += 1
        added += r.poly(net, [orig, twin], stub_layer)
    return added


# ------------------------------------------------------------------- zones
def add_gnd_zone(r) -> int:
    zone = pcbnew.ZONE(r.board)
    zone.SetNet(r.board.FindNet("GND"))
    zone.SetLayer(F_CU)
    zone.SetIsRuleArea(False)
    zone.SetAssignedPriority(0)
    zone.SetLocalClearance(mm(0.25))
    poly = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in [(80.4, 4.5), (180.5, 4.5), (180.5, 238.5), (80.4, 238.5)]:
        poly.Append(v(x, y))
    poly.SetClosed(True)
    zone.AddPolygon(poly)
    r.board.Add(zone)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--check-only", action="store_true", help="run self-check, do not save")
    args = parser.parse_args()

    board_path = args.board.resolve()
    if "revD" not in board_path.name or "revD" not in str(board_path.parent):
        raise SystemExit("REFUSING: not a revD board path (sacred-file guard).")

    board = pcbnew.LoadBoard(str(board_path))
    assert_netclasses_active(board)
    r = Router(board)
    removed = r.clear_tracks()
    # remove any previously added copper zones (keep rule areas).
    # KiCad 10.0.2 (M2 fix): snapshot the container first, then Delete()
    # (not Remove()) — Remove() leaks the native object and corrupts later
    # container iteration (see route_revD_lib.clear_tracks note).
    for z in [z for z in tuple(board.Zones()) if not z.GetIsRuleArea()]:
        board.Delete(z)

    totals = {
        "field_led_series": route_field_led_series(r),
        "field_input_returns": route_field_input_returns(r),
        "opto_pullups": route_opto_pullups(r),
        "field_power": route_field_power(r),
        "gnd_rail": route_gnd_rail(r),
        "v3v3": route_3v3(r),
        "v5": route_5v(r),
        "fast_inputs": logic.route_fast_inputs(r),
        "slow_inputs": logic.route_slow_inputs(r),
        "i2c": logic.route_i2c(r),
        "uart": logic.route_uart(r),
        "mcp_int": logic.route_mcp_int(r),
        "taps_adc": logic.route_taps_and_adc(r),
        "watchdog": route_watchdog(r),
        "header_safety": route_header_safety(r),
        "relay_drivers": route_relay_drivers(r),
        "safety_rail": route_safety_rail(r),
        "status_leds": route_status_leds(r),
        "drv": route_drv(r),
        "machine": route_machine(r),
        "power_via_redundancy": route_power_via_redundancy(r),
        "gnd_zone": add_gnd_zone(r),
    }

    print(f"Removed existing tracks/vias: {removed}")
    for k, n in totals.items():
        print(f"{k}: {n}")
    print(f"Total actions: {sum(totals.values())}")

    problems = r.check()
    print(f"\nSELF-CHECK: {len(problems)} problems")
    for p in problems[:200]:
        print("  " + p)

    if args.check_only:
        return 1 if problems else 0

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(board_path), board)
    print(f"Saved {board_path}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
