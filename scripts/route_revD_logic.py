#!/usr/bin/env python3
"""Logic-room routing passes for rev-D (imported by route_revD.py).

Layer discipline (logic room): IN1 = horizontals, IN2 = verticals,
B.Cu = power trunks/backbones + the GPA 'staircase' elbows, F.Cu = stubs.
Coordinates derive from the rev-D placement (place_components_revD.py) and
the board geometry dump; verified by the Router self-check + KiCad DRC.
"""
from __future__ import annotations

from route_revD_lib import (
    F_CU, B_CU, IN1_CU, IN2_CU, FAST_INPUTS, SLOW_A, SLOW_B, SLOW_C,
    item_pos, row_y, INPUT_ORDER,
)

# Rpu pad2 x (signal side) and the shared source-escape via column.
RPU2_X = 86.912
SRC_VIA_X = 87.7


def src_y(name: str) -> float:
    return row_y(INPUT_ORDER.index(name)) + 1.8


def route_fast_inputs(r) -> int:
    """FAST_* : Rpu.2 -> via -> IN1 -> IN2 lane under the Pico -> Pico pad."""
    added = 0
    lanes = {"SA": 99.75, "SB": 99.05, "SC": 96.1, "TA1": 95.4,
             "TA2": 94.7, "TB": 94.0, "DIELL_L": 93.3, "DIELL_R": 92.6}
    tgt_via_x = 93.5
    for name in FAST_INPUTS:
        net = f"FAST_{name}"
        sy = src_y(name)
        tx, ty = item_pos(r.net_pad(net, ref="A1"))
        lx = lanes[name]
        added += r.poly(net, [(RPU2_X, sy), (SRC_VIA_X, sy)], F_CU)
        r.via(net, (SRC_VIA_X, sy)); added += 1
        # IN1 source horizontal to the lane (with per-net jogs where the
        # straight entry would collide with a neighbour's corner via).
        if name == "TA1":
            added += r.poly(net, [(SRC_VIA_X, sy), (91.8, sy), (91.8, 33.0), (lx, 33.0)], IN1_CU)
            lane_top = 33.0
        elif name == "DIELL_L":
            added += r.poly(net, [(SRC_VIA_X, sy), (91.5, sy), (91.5, 47.8), (lx, 47.8)], IN1_CU)
            lane_top = 47.8
        else:
            added += r.poly(net, [(SRC_VIA_X, sy), (lx, sy)], IN1_CU)
            lane_top = sy
        r.via(net, (lx, lane_top)); added += 1
        added += r.poly(net, [(lx, lane_top), (lx, ty)], IN2_CU)
        r.via(net, (lx, ty)); added += 1
        if lx >= tgt_via_x + 1.2:
            added += r.poly(net, [(lx, ty), (tgt_via_x, ty)], IN1_CU)
            r.via(net, (tgt_via_x, ty)); added += 1
            added += r.poly(net, [(tgt_via_x, ty), (tx, ty)], F_CU)
        else:
            added += r.poly(net, [(lx, ty), (tx, ty)], F_CU)
    return added


def _slow_group(r, names, lanes, tgt_side, tgt_via_x, special=None) -> int:
    """Parallel (order-preserving) SLOW group to an MCP left column.
    src IN1 at sy -> IN2 lane -> IN1 at ty' -> via col -> F.Cu stub east.
    special[name] = (lane_end_y, col_via, fcu_points) overrides the row entry."""
    added = 0
    special = special or {}
    for name in names:
        net = f"SLOW_{name}"
        sy = src_y(name)
        # the MCP pad on this net (U1/U2); Rpu + opto pads share the net.
        tx, ty = None, None
        for p in r.pads_by_net()[net]:
            ref = p.GetParentFootprint().GetReference()
            if ref in ("U1", "U2"):
                tx, ty = item_pos(p)
        lx = lanes[name]
        added += r.poly(net, [(RPU2_X, sy), (SRC_VIA_X, sy)], F_CU)
        r.via(net, (SRC_VIA_X, sy)); added += 1
        added += r.poly(net, [(SRC_VIA_X, sy), (lx, sy)], IN1_CU)
        r.via(net, (lx, sy)); added += 1
        if name in special:
            ley, cvia, fpts = special[name]
            added += r.poly(net, [(lx, sy), (lx, ley)], IN2_CU)
            r.via(net, (lx, ley)); added += 1
            added += r.poly(net, [(lx, ley), (cvia[0], ley)] if ley != cvia[1] else [(lx, ley), cvia], IN1_CU)
            if ley != cvia[1]:
                added += r.poly(net, [(cvia[0], ley), cvia], IN1_CU)
            r.via(net, cvia); added += 1
            added += r.poly(net, fpts + [(tx, ty)], F_CU)
            continue
        added += r.poly(net, [(lx, sy), (lx, ty)], IN2_CU)
        r.via(net, (lx, ty)); added += 1
        added += r.poly(net, [(lx, ty), (tgt_via_x, ty)], IN1_CU)
        r.via(net, (tgt_via_x, ty)); added += 1
        added += r.poly(net, [(tgt_via_x, ty), (tx, ty)], F_CU)
    return added


def _gpa_staircase(r, names, lanes, hys, vxs, tgt_via_x=None, special=None) -> int:
    """Reversed GPA group: src IN1 -> IN2 lane -> B.Cu elbow (horizontal at hy,
    vertical at vx) -> via at (vx, ty) -> F.Cu stub west into the right column."""
    added = 0
    for name in names:
        net = f"SLOW_{name}"
        sy = src_y(name)
        tx, ty = None, None
        for p in r.pads_by_net()[net]:
            ref = p.GetParentFootprint().GetReference()
            if ref in ("U1", "U2"):
                tx, ty = item_pos(p)
        lx, hy, vx = lanes[name], hys[name], vxs[name]
        added += r.poly(net, [(RPU2_X, sy), (SRC_VIA_X, sy)], F_CU)
        r.via(net, (SRC_VIA_X, sy)); added += 1
        entry = (special or {}).get(name)
        if entry:
            added += r.poly(net, [(SRC_VIA_X, sy)] + entry, IN1_CU)
            lane_top = entry[-1]
        else:
            added += r.poly(net, [(SRC_VIA_X, sy), (lx, sy)], IN1_CU)
            lane_top = (lx, sy)
        r.via(net, lane_top); added += 1
        added += r.poly(net, [lane_top, (lx, hy)], IN2_CU)
        r.via(net, (lx, hy)); added += 1
        added += r.poly(net, [(lx, hy), (vx, hy), (vx, ty)], B_CU)
        r.via(net, (vx, ty)); added += 1
        added += r.poly(net, [(vx, ty), (tx, ty)], F_CU)
    return added


def route_slow_inputs(r) -> int:
    added = 0
    # U1 GPB (order-preserving, sources below targets)
    gpb1 = ["GS9", "GS10", "GP", "OS", "BS", "PBZ", "PBC", "FOUL"]
    lanes = {n: 96.0 + i * 0.7 for i, n in enumerate(gpb1)}
    lanes["PBZ"] = 99.45
    lanes["PBC"] = 100.25
    lanes["FOUL"] = 100.95
    special = {"BS": (101.46, (114.2, 101.46),
                      [(114.2, 101.46), (116.1, 101.46)])}
    added += _slow_group(r, gpb1, lanes, "L", 115.0, special)

    # U2 GPB = AUX4..11 (order-preserving; AUX6+ lanes east of J13).
    # AUX4 swings east of the lamp-gate row; AUX10/11 duck below the U2
    # rows (their lanes sit within pad clearance of the right column).
    gpb2 = ["AUX5", "AUX6", "AUX7", "AUX8", "AUX9"]
    lanes2 = {"AUX5": 106.1, "AUX6": 122.9, "AUX7": 123.6,
              "AUX8": 124.3, "AUX9": 125.0}
    added += _slow_group(r, gpb2, lanes2, "L", 115.0)
    for name, lx, top_y, wvia_x, ty in (
            ("AUX10", 125.7, 158.2, 113.9, 145.365),
            ("AUX11", 126.4, 158.9, 114.7, 146.635)):
        net = f"SLOW_{name}"
        sy = src_y(name)
        added += r.poly(net, [(RPU2_X, sy), (SRC_VIA_X, sy)], F_CU)
        r.via(net, (SRC_VIA_X, sy)); added += 1
        added += r.poly(net, [(SRC_VIA_X, sy), (lx, sy)], IN1_CU)
        r.via(net, (lx, sy)); added += 1
        added += r.poly(net, [(lx, sy), (lx, top_y)], IN2_CU)
        r.via(net, (lx, top_y)); added += 1
        added += r.poly(net, [(lx, top_y), (wvia_x, top_y)], IN1_CU)
        r.via(net, (wvia_x, top_y)); added += 1
        added += r.poly(net, [(wvia_x, top_y), (wvia_x, ty)], IN2_CU)
        r.via(net, (wvia_x, ty)); added += 1
        added += r.poly(net, [(wvia_x, ty), (117.35, ty)], F_CU)
    # AUX4: lane east of the lamp gates at x=146.9, row entry from the west
    net = "SLOW_AUX4"
    sy = src_y("AUX4")
    added += r.poly(net, [(RPU2_X, sy), (SRC_VIA_X, sy)], F_CU)
    r.via(net, (SRC_VIA_X, sy)); added += 1
    added += r.poly(net, [(SRC_VIA_X, sy), (97.9, sy), (97.9, 194.6), (146.9, 194.6)], IN1_CU)
    r.via(net, (146.9, 194.6)); added += 1
    added += r.poly(net, [(146.9, 194.6), (146.9, 134.9)], IN2_CU)
    r.via(net, (146.9, 134.9)); added += 1
    added += r.poly(net, [(146.9, 134.9), (115.7, 134.9)], IN1_CU)
    r.via(net, (115.7, 134.9)); added += 1
    added += r.poly(net, [(115.7, 134.9), (116.4, 136.5), (117.35, 137.745)], F_CU)

    # U1 GPA staircase (GS1..GS8, reversed)
    gpa1 = [f"GS{i}" for i in range(1, 9)]
    lanes3 = {"GS1": 106.55, "GS2": 105.85, "GS3": 105.15, "GS4": 104.45,
              "GS5": 103.75, "GS6": 103.05, "GS7": 102.35, "GS8": 101.65}
    # hy monotone with vx; GS5-8 vx west of R125/R126 (x=133), GS1-4 east-low
    vxs3 = {"GS5": 129.4, "GS6": 130.1, "GS7": 130.8, "GS8": 131.5,
            "GS1": 132.3, "GS2": 133.0, "GS3": 133.7, "GS4": 134.4}
    hys3 = {"GS5": 113.5, "GS6": 114.4, "GS7": 115.3, "GS8": 116.2,
            "GS1": 117.1, "GS2": 118.0, "GS3": 118.9, "GS4": 119.8}
    added += _gpa_staircase(r, gpa1, lanes3, hys3, vxs3)

    # U2 GPA staircase (TENTH..AUX3, reversed)
    gpa2 = ["TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "AUX1", "AUX2", "AUX3"]
    lanes4 = {n: 112.1 - i * 0.7 for i, n in enumerate(gpa2)}
    hys4 = {"TENTH": 148.7, "MAN_T": 149.6, "MAN_S": 153.05, "MAN_SWS": 153.95,
            "MAN_SWSR": 154.85, "AUX1": 155.75, "AUX2": 136.9, "AUX3": 136.0}
    vxs4 = {n: 129.4 + i * 0.7 for i, n in enumerate(gpa2)}
    special4 = {"AUX3": [(105.0, 191.5), (105.0, 193.2), (107.2, 193.2)]}
    added += _gpa_staircase(r, gpa2, lanes4, hys4, vxs4, special=special4)
    return added


def route_i2c(r) -> int:
    """SDA trunk IN2 x=121.0, SCL trunk IN2 x=119.8 (top joins via IN1/IN2)."""
    added = 0
    SDA_X, SCL_X = 121.0, 119.8
    # J1 drops
    added += r.poly("I2C_SDA", [(138.04, 10.0), (138.04, 13.5)], F_CU)
    r.via("I2C_SDA", (138.04, 13.5)); added += 1
    added += r.poly("I2C_SDA", [(138.04, 13.5), (SDA_X, 13.5)], IN1_CU)
    r.via("I2C_SDA", (SDA_X, 13.5)); added += 1
    # (west leg on IN1; the ARM_PERMIT IN2 vertical crosses at x=134.8)
    added += r.poly("I2C_SDA", [(SDA_X, 13.5), (SDA_X, 197.3)], IN2_CU)

    added += r.poly("I2C_SCL", [(138.04, 7.46), (138.04, 1.55)], F_CU)
    r.via("I2C_SCL", (138.04, 1.55)); added += 1
    added += r.poly("I2C_SCL", [(138.04, 1.55), (118.54, 1.55), (118.54, 13.2),
                                (SCL_X, 14.4), (SCL_X, 218.2)], IN2_CU)

    # R1 (SDA pullup, pad2 north) / R2 (SCL pullup)
    added += r.poly("I2C_SDA", [(103.0, 85.088), (102.5, 84.3), (102.5, 81.9)], F_CU)
    r.via("I2C_SDA", (102.5, 81.9)); added += 1
    added += r.poly("I2C_SDA", [(102.5, 81.9), (SDA_X, 81.9)], IN1_CU)
    r.via("I2C_SDA", (SDA_X, 81.9)); added += 1
    added += r.poly("I2C_SCL", [(110.0, 85.088), (110.0, 83.5)], F_CU)
    r.via("I2C_SCL", (110.0, 83.5)); added += 1
    added += r.poly("I2C_SCL", [(110.0, 83.5), (SCL_X, 83.5)], IN1_CU)
    r.via("I2C_SCL", (SCL_X, 83.5)); added += 1

    # U1 drops (straight tees); U2 drops jog off the GPA hy corridors
    sx, sy = r.ppos("U1", "13")
    added += r.poly("I2C_SDA", [(sx, sy), (SDA_X, sy)], F_CU)
    r.via("I2C_SDA", (SDA_X, sy)); added += 1
    cx, cy = r.ppos("U1", "12")
    added += r.poly("I2C_SCL", [(cx, cy), (SCL_X, cy)], F_CU)
    r.via("I2C_SCL", (SCL_X, cy)); added += 1
    added += r.poly("I2C_SDA", [(117.35, 152.985), (118.75, 152.985), (118.75, 152.3), (SDA_X, 152.3)], F_CU)
    r.via("I2C_SDA", (SDA_X, 152.3)); added += 1
    added += r.poly("I2C_SCL", [(135.35, 117.715), (132.45, 117.715), (132.45, 121.5), (SCL_X, 121.5)], F_CU)
    r.via("I2C_SCL", (SCL_X, 121.5)); added += 1
    added += r.poly("I2C_SDA", [(135.35, 118.985), (133.1, 118.985), (133.1, 122.3), (SDA_X, 122.3)], F_CU)
    r.via("I2C_SDA", (SDA_X, 122.3)); added += 1
    added += r.poly("I2C_SCL", [(117.35, 151.715), (118.75, 151.715), (118.75, 150.85), (SCL_X, 150.85)], F_CU)
    r.via("I2C_SCL", (SCL_X, 150.85)); added += 1

    # J16 drops (THT pads start on inner layers directly)
    added += r.poly("I2C_SDA", [(135.0, 206.0), (135.0, 201.6)], IN2_CU)
    r.via("I2C_SDA", (135.0, 201.6)); added += 1
    added += r.poly("I2C_SDA", [(135.0, 201.6), (125.3, 201.6)], IN1_CU)
    added += r.poly("I2C_SDA", [(125.3, 201.6), (121.0, 197.3)], IN1_CU)
    r.via("I2C_SDA", (121.0, 197.3)); added += 1
    added += r.poly("I2C_SCL", [(138.5, 206.0), (138.5, 202.6)], IN2_CU)
    r.via("I2C_SCL", (138.5, 202.6)); added += 1
    added += r.poly("I2C_SCL", [(138.5, 202.6), (SCL_X, 202.6)], IN1_CU)
    r.via("I2C_SCL", (SCL_X, 202.6)); added += 1

    # test pads: SDA drops to TP6 through the J13/J16 gap at x=129.9
    r.via("I2C_SDA", (129.9, 201.6)); added += 1
    added += r.poly("I2C_SDA", [(129.9, 201.6), (129.9, 226.0)], IN2_CU)
    r.via("I2C_SDA", (129.9, 226.0)); added += 1
    added += r.poly("I2C_SDA", [(129.9, 226.0), (130.0, 229.0)], F_CU)
    r.via("I2C_SCL", (SCL_X, 218.2)); added += 1
    added += r.poly("I2C_SCL", [(SCL_X, 218.2), (138.6, 218.2), (138.6, 226.0)], B_CU)
    r.via("I2C_SCL", (138.6, 226.0)); added += 1
    added += r.poly("I2C_SCL", [(138.6, 226.0), (140.0, 226.0), (140.0, 229.0)], F_CU)
    return added


def route_uart(r) -> int:
    added = 0
    # RX: J1.6 (140.58,7.46) -> IN1 y=3.9 -> Pico pad1 (90.31,8.87)
    added += r.poly("PI_UART_RX", [(140.58, 7.46), (140.58, 3.9)], F_CU)
    r.via("PI_UART_RX", (140.58, 3.9)); added += 1
    added += r.poly("PI_UART_RX", [(140.58, 3.9), (87.9, 3.9)], IN1_CU)
    r.via("PI_UART_RX", (87.9, 3.9)); added += 1
    added += r.poly("PI_UART_RX", [(87.9, 3.9), (87.9, 8.87), (90.31, 8.87)], F_CU)
    # TX: J1.5 (140.58,10) -> gap jog -> IN1 y=2.6 -> Pico pad2 (90.31,11.41)
    added += r.poly("PI_UART_TX", [(140.58, 10.0), (139.3, 10.0), (139.3, 2.6)], F_CU)
    r.via("PI_UART_TX", (139.3, 2.6)); added += 1
    added += r.poly("PI_UART_TX", [(139.3, 2.6), (86.9, 2.6), (86.9, 11.41)], IN1_CU)
    r.via("PI_UART_TX", (86.9, 11.41)); added += 1
    added += r.poly("PI_UART_TX", [(86.9, 11.41), (90.31, 11.41)], F_CU)
    return added


def route_mcp_int(r) -> int:
    added = 0
    # INT_A: J1.9 (145.66,10) -> IN1 y=14.6 -> IN2 x=128.5 -> U1.20
    added += r.poly("MCP_INT_A", [(145.66, 10.0), (145.66, 14.6)], F_CU)
    r.via("MCP_INT_A", (145.66, 14.6)); added += 1
    added += r.poly("MCP_INT_A", [(145.66, 14.6), (128.5, 14.6)], IN1_CU)
    r.via("MCP_INT_A", (128.5, 14.6)); added += 1
    tx, ty = r.ppos("U1", "20")
    added += r.poly("MCP_INT_A", [(128.5, 14.6), (128.5, ty)], IN2_CU)
    r.via("MCP_INT_A", (128.5, ty)); added += 1
    added += r.poly("MCP_INT_A", [(128.5, ty), (tx, ty)], F_CU)
    # INT_B: J1.10 (145.66,7.46) -> IN1 y=4.9 -> IN2 x=127.3 -> U2.20
    added += r.poly("MCP_INT_B", [(145.66, 7.46), (145.66, 3.0)], F_CU)
    r.via("MCP_INT_B", (145.66, 3.0)); added += 1
    added += r.poly("MCP_INT_B", [(145.66, 3.0), (145.66, 5.6), (127.3, 5.6)], IN1_CU)
    r.via("MCP_INT_B", (127.3, 5.6)); added += 1
    tx, ty = r.ppos("U2", "20")
    added += r.poly("MCP_INT_B", [(127.3, 5.6), (127.3, 7.2), (128.05, 8.0),
                                  (128.05, 12.0), (127.3, 12.8), (127.3, ty)], IN2_CU)
    r.via("MCP_INT_B", (127.3, ty)); added += 1
    added += r.poly("MCP_INT_B", [(127.3, ty), (tx, ty)], F_CU)
    return added


def route_taps_and_adc(r) -> int:
    """Item E tap nets to Pico GP pins + item D ADC divider."""
    added = 0
    # TAP_NE555_OUT: R131.2 (146.912,33) -> B.Cu y=31 -> x=110.5 -> pin21 (109.69,57.13)
    added += r.poly("TAP_NE555_OUT", [(146.912, 33.0), (148.5, 33.0), (148.5, 31.0)], F_CU)
    r.via("TAP_NE555_OUT", (148.5, 31.0)); added += 1
    added += r.poly("TAP_NE555_OUT", [(132.0, 44.9125), (132.0, 48.6), (130.4, 48.6)], F_CU)
    r.via("TAP_NE555_OUT", (130.4, 48.6)); added += 1
    added += r.poly("TAP_NE555_OUT", [(130.4, 48.6), (111.05, 48.6), (111.05, 31.0)], B_CU)
    added += r.poly("TAP_NE555_OUT", [(148.5, 31.0), (110.5, 31.0), (110.5, 57.13)], B_CU)
    r.via("TAP_NE555_OUT", (110.5, 57.13)); added += 1
    added += r.poly("TAP_NE555_OUT", [(110.5, 57.13), (109.69, 57.13)], F_CU)
    # TAP_WDOG_KICK: R133.2 (136,46.088) -> B.Cu y=51.5 -> x=111.3 -> pin22 (109.69,54.59)
    added += r.poly("TAP_WDOG_KICK", [(136.0, 46.088), (132.95, 46.088), (132.95, 51.5)], F_CU)
    r.via("TAP_WDOG_KICK", (132.95, 51.5)); added += 1
    added += r.poly("TAP_WDOG_KICK", [(132.95, 51.5), (111.3, 51.5), (111.3, 54.59)], B_CU)
    r.via("TAP_WDOG_KICK", (111.3, 54.59)); added += 1
    added += r.poly("TAP_WDOG_KICK", [(111.3, 54.59), (109.69, 54.59)], F_CU)
    # TAP_ARM_PERMIT: R134.2 (130,69.088) -> B.Cu y=72.5 -> x=106.5 (under Pico) -> pin24 (109.69,49.51)
    added += r.poly("TAP_ARM_PERMIT", [(130.0, 69.088), (131.15, 69.088), (131.15, 72.5)], F_CU)
    r.via("TAP_ARM_PERMIT", (131.15, 72.5)); added += 1
    added += r.poly("TAP_ARM_PERMIT", [(131.15, 72.5), (107.25, 72.5), (107.25, 49.51)], B_CU)
    r.via("TAP_ARM_PERMIT", (107.25, 49.51)); added += 1
    added += r.poly("TAP_ARM_PERMIT", [(107.25, 49.51), (109.69, 49.51)], F_CU)
    # TAP_RP2040_OK: east stub, IN2 north at x=158.3, B.Cu west at y=45.6
    added += r.poly("TAP_RP2040_OK", [(156.912, 64.0), (158.3, 64.0)], F_CU)
    r.via("TAP_RP2040_OK", (158.3, 64.0)); added += 1
    added += r.poly("TAP_RP2040_OK", [(158.3, 64.0), (158.3, 44.2), (147.9, 44.2), (147.9, 45.6)], IN2_CU)
    r.via("TAP_RP2040_OK", (147.9, 45.6)); added += 1
    added += r.poly("TAP_RP2040_OK", [(147.9, 45.6), (112.4, 45.6), (111.75, 47.2)], B_CU)
    r.via("TAP_RP2040_OK", (111.75, 47.2)); added += 1
    added += r.poly("TAP_RP2040_OK", [(111.75, 47.2), (110.9, 46.97), (109.69, 46.97)], F_CU)
    # ADC divider: local F.Cu tree at x=112.4 joining R129.2/R130.1/C15.1 -> A1.31
    added += r.poly("ADC_VCC5_SENSE", [(114.0, 40.087), (112.65, 40.087)], F_CU)
    added += r.poly("ADC_VCC5_SENSE", [(114.0, 47.913), (112.65, 47.913), (112.65, 40.087)], F_CU)
    added += r.poly("ADC_VCC5_SENSE", [(117.0, 44.95), (115.2, 44.95), (115.2, 43.6), (112.65, 43.6)], F_CU)
    added += r.poly("ADC_VCC5_SENSE", [(112.65, 40.087), (112.65, 31.73), (109.69, 31.73)], F_CU)
    return added
