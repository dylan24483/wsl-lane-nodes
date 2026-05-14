#!/usr/bin/env python3
"""
WSL Phase 8a — Unified Watchdog + AC Interposer PCB
SKiDL script that generates a KiCad netlist for the board.

Source of truth: ../docs/pcb_design_spec.md (Section 4 netlist table)

This script mirrors every component and net from the spec doc explicitly.
Cross-check by reading this code side-by-side with Section 4 of the spec.

REFDES MAPPING (KiCad uses standard prefixes — slightly different from spec):
  Spec doc       Code refdes   Function
  --------       -----------   --------
  IC1            U1            NE555 timer
  Q1, Q2         Q1, Q2        AO3400 N-MOSFETs (Q1=discharge, Q2=output)
  D1, D2         D1, D2        1N4148WS switching diodes (diode-OR isolation)
  DA1..DA4       D3..D6        M7 (1N4007 SMA) AC interposer rectifiers
  C1             C1            100uF/16V NE555 timing cap
  C2             C2            0.1uF NE555 VCC bypass MLCC
  CFILT          C3            10nF NE555 CTRL filter MLCC
  CA1..CA4       C4..C7        10uF/50V AC interposer smoothing caps
  R1             R1            100k NE555 timing pullup
  R2             R2            10k TRIG pullup (CRITICAL — without R2 the
                               NE555 free-runs as astable)
  R3, R4         R3, R4        1k Q1 gate series + 10k Q1 gate pulldown
  R6, R7         R6, R7        1k Q2 gate series + 10k Q2 gate pulldown
  R8, R9         R8, R9        470 LED current-limit resistors
  Rb1..Rb4       R10..R13      100k AC interposer bleeders (per Codex review)
  LED1, LED2     LED1, LED2    Watchdog-healthy + power-good indicators
  TB_PWR_IN      J1            +5V power input
  TB_AEDIKO_PWR  J2            5V out to AEDIKO PWR (V+ direct, V- gated by Q2)
  TB_KICK        J3            Pi GPIO 12 watchdog kick input
  TB_AC_IN_CH*   J4..J7        24VAC channel inputs (foul/2nd-ball lamps)
  TB_DC_OUT_CH*  J8..J11       DC channel outputs to AL-ZARD selector inputs

PIN CONVENTION ASSUMPTIONS (KiCad standard library):
  Diode (Device:D and Diode:*):  pin 1 = K (cathode), pin 2 = A (anode)
  LED (Device:LED):              pin 1 = K, pin 2 = A
  Polarized cap (Device:CP):     pin 1 = +, pin 2 = -
  N-MOSFET (Q_NMOS_GSD):         pin 1 = G, pin 2 = S, pin 3 = D
  NE555 (Timer:NE555):           pin 1=GND, 2=TRIG, 3=OUT, 4=RESET,
                                 5=CTRL, 6=THRES, 7=DISCH, 8=VCC

If a pin name lookup fails when running this script, the part's symbol in
your KiCad library uses different pin names — fix the offending line by
swapping name for pin number (e.g., D1['K'] -> D1[1]) and re-run.

USAGE:
  python generate_kicad_netlist.py
  -> writes ../kicad/wsl-phase8a.net

NEXT STEP:
  Open KiCad, new project, open pcbnew, File > Import > Netlist...
  Select wsl-phase8a.net. Components appear ready for placement.
"""

import os
import re
import sys

# ----------------------------------------------------------------------
# KiCad library path setup (MUST happen before skidl import)
# ----------------------------------------------------------------------

KICAD_CANDIDATE_ROOTS = [
    r"C:\Program Files\KiCad\10.0\share\kicad",
    r"C:\Program Files\KiCad\9.0\share\kicad",
    r"C:\Program Files\KiCad\8.0\share\kicad",
    r"C:\Program Files\KiCad\7.0\share\kicad",
    r"C:\Program Files (x86)\KiCad\10.0\share\kicad",
    r"C:\Program Files (x86)\KiCad\9.0\share\kicad",
]

kicad_root = next((p for p in KICAD_CANDIDATE_ROOTS if os.path.isdir(p)), None)
if kicad_root is None:
    print("ERROR: Couldn't find KiCad install. Tried:", file=sys.stderr)
    for p in KICAD_CANDIDATE_ROOTS:
        print(f"  {p}", file=sys.stderr)
    print("Edit KICAD_CANDIDATE_ROOTS in this script to add your install path.",
          file=sys.stderr)
    sys.exit(1)

m = re.search(r"KiCad\\(\d+)\.\d+", kicad_root)
major = m.group(1) if m else "10"

symbol_dir = os.path.join(kicad_root, "symbols")
footprint_dir = os.path.join(kicad_root, "footprints")

# Set every env var SKiDL might check (it looks at generic + per-version)
for var in ["KICAD_SYMBOL_DIR"] + [f"KICAD{v}_SYMBOL_DIR" for v in (6, 7, 8, 9, 10)]:
    os.environ[var] = symbol_dir
for var in ["KICAD_FOOTPRINT_DIR"] + [f"KICAD{v}_FOOTPRINT_DIR" for v in (6, 7, 8, 9, 10)]:
    os.environ[var] = footprint_dir

print(f"Using KiCad {major}.x libraries at {kicad_root}")

# ----------------------------------------------------------------------
# Now import SKiDL
# ----------------------------------------------------------------------

from skidl import (
    Part, Net, generate_netlist, set_default_tool, KICAD, ERC, lib_search_paths
)

set_default_tool(KICAD)

# Belt-and-suspenders: also push the symbol path into SKiDL's search list
lib_search_paths[KICAD].append(symbol_dir)

# ----------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------

# Watchdog block
U1 = Part('Timer', 'NE555D',
          value='NE555',
          footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')

Q1 = Part('Transistor_FET', 'Q_NMOS_GSD',
          value='AO3400A',
          footprint='Package_TO_SOT_SMD:SOT-23')
Q2 = Part('Transistor_FET', 'Q_NMOS_GSD',
          value='AO3400A',
          footprint='Package_TO_SOT_SMD:SOT-23')

# Switching diodes (diode-OR isolation in watchdog)
D1 = Part('Device', 'D',
          value='1N4148WS',
          footprint='Diode_SMD:D_SOD-323')
D2 = Part('Device', 'D',
          value='1N4148WS',
          footprint='Diode_SMD:D_SOD-323')

# AC interposer rectifiers — M7 / 1N4007 in SMA package
D3 = Part('Device', 'D', value='M7 (1N4007)', footprint='Diode_SMD:D_SMA')
D4 = Part('Device', 'D', value='M7 (1N4007)', footprint='Diode_SMD:D_SMA')
D5 = Part('Device', 'D', value='M7 (1N4007)', footprint='Diode_SMD:D_SMA')
D6 = Part('Device', 'D', value='M7 (1N4007)', footprint='Diode_SMD:D_SMA')

# Caps
C1 = Part('Device', 'C_Polarized', value='100uF/16V',
          footprint='Capacitor_SMD:CP_Elec_6.3x5.4')
C2 = Part('Device', 'C', value='0.1uF/50V',
          footprint='Capacitor_SMD:C_0805_2012Metric')
C3 = Part('Device', 'C', value='10nF/50V',
          footprint='Capacitor_SMD:C_0805_2012Metric')
C4 = Part('Device', 'C_Polarized', value='10uF/50V',
          footprint='Capacitor_SMD:CP_Elec_6.3x5.4')
C5 = Part('Device', 'C_Polarized', value='10uF/50V',
          footprint='Capacitor_SMD:CP_Elec_6.3x5.4')
C6 = Part('Device', 'C_Polarized', value='10uF/50V',
          footprint='Capacitor_SMD:CP_Elec_6.3x5.4')
C7 = Part('Device', 'C_Polarized', value='10uF/50V',
          footprint='Capacitor_SMD:CP_Elec_6.3x5.4')

# Resistors
R1 = Part('Device', 'R', value='100k', footprint='Resistor_SMD:R_0805_2012Metric')
R2 = Part('Device', 'R', value='10k',  footprint='Resistor_SMD:R_0805_2012Metric')
R3 = Part('Device', 'R', value='1k',   footprint='Resistor_SMD:R_0805_2012Metric')
R4 = Part('Device', 'R', value='10k',  footprint='Resistor_SMD:R_0805_2012Metric')
# R5 intentionally skipped to match spec doc numbering
R6 = Part('Device', 'R', value='1k',   footprint='Resistor_SMD:R_0805_2012Metric')
R7 = Part('Device', 'R', value='10k',  footprint='Resistor_SMD:R_0805_2012Metric')
R8 = Part('Device', 'R', value='470',  footprint='Resistor_SMD:R_0805_2012Metric')
R9 = Part('Device', 'R', value='470',  footprint='Resistor_SMD:R_0805_2012Metric')

# Bleeders Rb1..Rb4 (numbered R10..R13 in KiCad)
R10 = Part('Device', 'R', value='100k', footprint='Resistor_SMD:R_0805_2012Metric')
R11 = Part('Device', 'R', value='100k', footprint='Resistor_SMD:R_0805_2012Metric')
R12 = Part('Device', 'R', value='100k', footprint='Resistor_SMD:R_0805_2012Metric')
R13 = Part('Device', 'R', value='100k', footprint='Resistor_SMD:R_0805_2012Metric')

# LEDs
LED1 = Part('Device', 'LED', value='Green',
            footprint='LED_SMD:LED_0805_2012Metric')
LED2 = Part('Device', 'LED', value='Green',
            footprint='LED_SMD:LED_0805_2012Metric')

# Terminal blocks (5.08mm pitch 2-pos screw terminal — pluggable in production
# per Dylan's LCSC pick DLL 2EDG-5.08-2ALS; KiCad footprint is generic 5.08mm 2P)
TB_FP = 'TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal'
J1  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J2  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J3  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J4  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J5  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J6  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J7  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J8  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J9  = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J10 = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)
J11 = Part('Connector_Generic', 'Conn_01x02', value='5.08mm 2P TB', footprint=TB_FP)

# ----------------------------------------------------------------------
# Nets (mirrors spec Section 4 net list table exactly)
# ----------------------------------------------------------------------

VCC         = Net('VCC_5V')
GND         = Net('GND')
KICK        = Net('KICK')
Q1_GATE     = Net('Q1_GATE')
Q1_DRAIN    = Net('Q1_DRAIN')
TIMING_NODE = Net('TIMING_NODE')
TRIG        = Net('NE555_TRIG')
OUT_555     = Net('NE555_OUT')
Q2_GATE     = Net('Q2_GATE')
COIL_RET    = Net('COIL_GND_RETURN')
LED1_DRIVE  = Net('LED1_ANODE_DRIVE')
LED2_DRIVE  = Net('LED2_ANODE_DRIVE')
CTRL        = Net('NE555_CTRL')

AC1_L1  = Net('AC_CH1_L1');  AC2_L1  = Net('AC_CH2_L1')
AC3_L1  = Net('AC_CH3_L1');  AC4_L1  = Net('AC_CH4_L1')

DC1_POS = Net('DC_CH1_POS'); DC2_POS = Net('DC_CH2_POS')
DC3_POS = Net('DC_CH3_POS'); DC4_POS = Net('DC_CH4_POS')

CH1_RET = Net('CH1_RETURN'); CH2_RET = Net('CH2_RETURN')
CH3_RET = Net('CH3_RETURN'); CH4_RET = Net('CH4_RETURN')

# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------

# --- VCC_5V net ---
VCC += J1[1]      # TB_PWR_IN.1 (V+ in)
VCC += U1[4]      # NE555 RESET (held HIGH = enabled)
VCC += U1[8]      # NE555 VCC
VCC += R1[1]      # 100k timing pullup, top
VCC += R2[1]      # 10k TRIG pullup, top
VCC += C2[1]      # NE555 VCC bypass cap, one side (non-polar MLCC)
VCC += R8[1]      # LED1 current-limit R, top
VCC += R9[1]      # LED2 current-limit R, top
VCC += J2[1]      # TB_AEDIKO_PWR.1 (V+ direct to AEDIKO)

# --- GND net ---
GND += J1[2]      # TB_PWR_IN.2 (V- in)
GND += U1[1]      # NE555 GND
GND += C1[2]    # Timing cap negative
GND += C2[2]      # NE555 bypass cap, other side
GND += C3[2]      # CFILT, other side (CTRL filter to GND)
GND += R4[2]      # Q1 gate pulldown, bottom
GND += R7[2]      # Q2 gate pulldown, bottom
GND += Q1[2]      # Q1 source (SOT-23 pin 2 = S)
GND += Q2[2]      # Q2 source
GND += LED2['K']  # LED2 cathode (power-good LED, cathode to GND)
GND += J3[2]      # TB_KICK.2 (kick GND reference, back to Pi)

# --- KICK (Pi GPIO 12 input to watchdog) ---
KICK += J3[1]     # TB_KICK.1
KICK += R3[1]     # Q1 gate series, top

# --- Q1_GATE (gate-drive network) ---
Q1_GATE += R3[2]  # Q1 gate series, bottom
Q1_GATE += R4[1]  # Q1 gate pulldown, top
Q1_GATE += Q1[1]  # Q1 gate (SOT-23 pin 1 = G)

# --- Q1_DRAIN (diode-OR isolation node) ---
Q1_DRAIN += Q1[3]    # Q1 drain (SOT-23 pin 3 = D)
Q1_DRAIN += D1['K']  # D1 cathode (Q1 pulls this LOW when ON)
Q1_DRAIN += D2['K']  # D2 cathode

# --- TIMING_NODE (NE555 RC + diode-OR anode for TIMING) ---
TIMING_NODE += U1[6]    # THRES (NE555 pin 6)
TIMING_NODE += U1[7]    # DISCH (NE555 pin 7)
TIMING_NODE += R1[2]    # Timing pullup, bottom
TIMING_NODE += C1[1]  # Timing cap +
TIMING_NODE += D1['A']  # D1 anode — when Q1 ON, D1 pulls TIMING_NODE down

# --- NE555_TRIG ---
TRIG += U1[2]    # NE555 TRIG (pin 2)
TRIG += R2[2]    # TRIG pullup (10k), bottom
TRIG += D2['A']  # D2 anode — when Q1 ON, D2 pulls TRIG down (re-fires monostable)

# --- NE555_OUT (drives Q2 gate via R6) ---
OUT_555 += U1[3]  # NE555 OUT (pin 3)
OUT_555 += R6[1]  # Q2 gate series, top

# --- Q2_GATE ---
Q2_GATE += R6[2]  # Q2 gate series, bottom
Q2_GATE += R7[1]  # Q2 gate pulldown, top
Q2_GATE += Q2[1]  # Q2 gate

# --- COIL_GND_RETURN (Q2 drain output = gated AEDIKO V- return) ---
COIL_RET += Q2[3]      # Q2 drain
COIL_RET += J2[2]      # TB_AEDIKO_PWR.2 (V- return to AEDIKO)
COIL_RET += LED1['K']  # LED1 cathode (lights when Q2 ON = watchdog healthy)

# --- LED anode drive nets ---
LED1_DRIVE += R8[2]      # LED1 current-limit R, bottom
LED1_DRIVE += LED1['A']  # LED1 anode

LED2_DRIVE += R9[2]      # LED2 current-limit R, bottom
LED2_DRIVE += LED2['A']  # LED2 anode

# --- NE555 CTRL pin with CFILT to GND (noise immunity) ---
CTRL += U1[5]    # NE555 CTRL pin (pin 5)
CTRL += C3[1]    # CFILT, hot side

# ----------------------------------------------------------------------
# AC interposer channels (4 identical, each isolated from the others)
# ----------------------------------------------------------------------

# Channel 1
AC1_L1  += J4[1];  AC1_L1  += D3['A']
DC1_POS += D3['K']; DC1_POS += C4[1]; DC1_POS += R10[1]; DC1_POS += J8[1]
CH1_RET += J4[2];   CH1_RET += C4[2]; CH1_RET += R10[2]; CH1_RET += J8[2]

# Channel 2
AC2_L1  += J5[1];  AC2_L1  += D4['A']
DC2_POS += D4['K']; DC2_POS += C5[1]; DC2_POS += R11[1]; DC2_POS += J9[1]
CH2_RET += J5[2];   CH2_RET += C5[2]; CH2_RET += R11[2]; CH2_RET += J9[2]

# Channel 3
AC3_L1  += J6[1];  AC3_L1  += D5['A']
DC3_POS += D5['K']; DC3_POS += C6[1]; DC3_POS += R12[1]; DC3_POS += J10[1]
CH3_RET += J6[2];   CH3_RET += C6[2]; CH3_RET += R12[2]; CH3_RET += J10[2]

# Channel 4
AC4_L1  += J7[1];  AC4_L1  += D6['A']
DC4_POS += D6['K']; DC4_POS += C7[1]; DC4_POS += R13[1]; DC4_POS += J11[1]
CH4_RET += J7[2];   CH4_RET += C7[2]; CH4_RET += R13[2]; CH4_RET += J11[2]

# ----------------------------------------------------------------------
# ERC + netlist generation
# ----------------------------------------------------------------------

# Run ERC — flags unconnected pins, conflicts, etc.
print("\nRunning ERC...")
ERC()

# Write netlist to ../kicad/wsl-phase8a.net
script_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(os.path.dirname(script_dir), 'kicad')
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, 'wsl-phase8a.net')

generate_netlist(file_=output_file)
print(f"\nNetlist written to: {output_file}")
print("\nNext: open KiCad, create a new project in the kicad/ dir,")
print("      then in pcbnew: File > Import > Netlist... and select this file.")
