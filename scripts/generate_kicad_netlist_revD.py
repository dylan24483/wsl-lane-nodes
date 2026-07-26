#!/usr/bin/env python3
"""
WSL Phase 8 Rev-D - fully integrated lane controller PCB.

COPY of the rev-C generator (scripts/generate_kicad_netlist_revB.py — every
rev-C artifact carries a revB filename; see kicad/fab_revB_routed_manual/
PROVENANCE.md). The rev-C source file is SACRED and untouched; all rev-D work
lives here. Implementation contract: docs/phase8_revD_change_spec.md.

Rev-D deltas over rev-C (spec items A-G):
  A - FIELD_WET_V minimum-load bleed: 2 x 2k2 0805 in parallel (1.1k, 4.5 mA)
      across FIELD_WET_V -> FIELD_GND in block_supplies(). 0 new nets.
  B - Pico USB clearance: placement-only (no netlist delta; owned by
      place_components_revD.py).
  C - IN-B GPB opto bank: 8 exact opto_input() clones AUX4-AUX11 appended at
      the END of SLOW_INPUT_PINS -> MCP_IN_B (0x21) pins 1-8 (GPB0-7), plus
      new field connector J15 = J_SLOW_IN_C (Conn_01x10 on FP_MCV_1X10,
      pinout mirrors J3 keying: signals 1-8, FIELD_GND 9-10). Mating plug
      Phoenix MC 1,5/10-ST-3,5 = 1840447 (harness BOM) — SAME plug PN as J3
      on the same field edge: cross-mate hazard; CP-MSTB 1734634 coding keys
      at different positions are MANDATORY (spec §C.3, gate OG-3).
      25 parts, 24 new nets.
  D - VCC_5V board-self-health ADC divider: 10k/10k + 100nF -> new net
      ADC_VCC5_SENSE -> Pico pin 31 (GP26/ADC0). ADC_VREF (pin 35) stays NC
      (module-internal reference, spec drift DR-3). 3 parts, 1 new net.
  E - Rail-drop edge-ordering taps on EXISTING observable points only.
      2026-07-21 REDESIGN (remediation spec R1, closes Codex C1 + H1 —
      SUPERSEDES the §E.2/§E.3 resistive taps): per tap, a 2N7002
      common-source inverter (SOT-23, the existing Qled_* class):
        observed_net -> R_TAPIN 1M -> gate; gate -> R_TAPG 10M -> GND
        (3.3 V taps only; the NE555 push-pull output is never high-Z and
        deliberately omits it); VCC_3V3 -> R_TAPPU 10k -> drain -> GPIO.
      GENUINELY UNIDIRECTIONAL: the GPIO touches only the drain; a MOS gate
      sources nothing into the observed net (I_GSS <= 100 nA); any GPIO
      state injects ZERO DC. Worst DOUBLE fault (FET D-G short + stuck-high
      GPIO + legitimate driver high-Z + 85 C) injects <= 0.56 uA -> 0.056 V
      on RAIL_GATE, >= 8x below the 5 uA partial-hold onset, with a
      transistor-free absolute ceiling of 3.3 V/1.01 M = 3.3 uA (why R_TAPIN
      must never drop below 1M: the derated 85 C partial-hold onset is
      ~3.6 uA, so 3.3 V/R <= 3.6 uA requires R >= 917 k; 1M is the smallest
      standard value. The earlier "~825k" floor cleared only the 25 C onset
      and was RETRACTED - remediation spec R1.4 / run-log RV-5, Codex R2-2).
      H1 dies by construction: the 2N7002 gate
      is +/-20 V rated, the GPIO only ever sees the 3V3-referenced drain.
      LOGIC INVERSION is binding on firmware v1.2 (spec R3): observed HIGH
      => GPIO reads LOW. Firmware input-only remains ENFORCED (R3.2), now as
      defense-in-depth rather than the primary barrier.
      NE555_OUT -> GP16, WDOG_KICK -> GP17, ARM_PERMIT -> GP18,
      RP2040_OK -> GP19. 15 parts, 8 new nets (4 TAP_GATE_* + the 4 TAP_*
      drain nets). 680k and the 100k/680k divider leave the BOM (taps were
      the only 680k use).
      SAFE_* loop taps are explicitly OUT OF SCOPE — no new copper on any
      SAFE_ net; Safety_Rail class count stays EXACTLY 13.
  F - External-analog expansion header J16 = J_EXT_I2C (Conn_01x06 on
      FP_MCV_1X06): VCC_5V / GND / SDA / SCL / VCC_3V3 / GND. Mating plug
      Phoenix MC 1,5/6-ST-3,5 = 1840405 (harness BOM) — SAME plug PN as J13
      (lamps) 24 mm away on the same edge, and pins 1/2 are VCC_5V/GND on
      BOTH: a swapped lamp harness dumps unlimited-current LED strings onto
      GND/SDA/SCL (the 330R limiters live on-board behind J13). CP-MSTB
      1734634 coding keys at different positions are MANDATORY (spec §F,
      gate OG-3). 1 part, 0 new nets.
      Modules must avoid I2C addresses 0x20-0x23.
      2026-07-21 round-2 remediation (Codex R2-4): J16 now sits behind a
      protection stack — 200 mA polyfuse on pin 1, default-OPEN solder
      link on pin 5, TCA4307 stuck-bus-recovery buffer + 4.7k card-side
      pull-ups + SRV05-4 connector-side ESD array on pins 3/4. Plus R2-6:
      2-bit REV_ID strap (GP20/GP21, rev-D = 0b01). +9 parts, +6 nets —
      see block_j16_protection_and_revid().
  G - OUT-B MCP23017 @0x23: DEFERRED (spec decision — not placed; a breakout
      on J16 at 0x23 provides the same capacity off-board).

  r6 - PER-CHANNEL INPUT PROTECTION on all 40 opto channels (2026-07-25,
      docs/phase8_revD_r6_input_protection_spec_2026-07-25.md). opto_input()
      now emits a NEW node FIELD_RIN_<n> between Rin and the LED; a later
      block_input_protection() inserts, per channel, a POPULATED 1N4148WS
      SOD-323 series block (FIELD_RIN_<n> -> FIELD_LED_<n>), a POPULATED
      1N4148WS SOD-323 anti-parallel clamp across the PC817 LED, and a DNP
      0805 logic-side filter cap (10nF fast / 2.2uF slow). Closes the
      measured reverse-stress case (PBZ 33 VDC = 4.5-4.7x the PC817 LED's
      6 V V_R max; DIELL_L/R 15.4-16 V = 1.6-1.8x OVER once rev-D's own
      1.1k bleed pulls Vw to 5-6 V; cams in the 24 VAC ladder = 4.8x peak).
      120 parts, 40 new nets. ZERO safety copper, ZERO new part class
      (1N4148WS/SOD-323 was already on the BOM), ZERO refdes churn.
      Board revision stays D (never fabricated); fab package iteration r6.

Expected emitted totals: 391 parts (271 + 120 r6), 263 nets (223 + 40
FIELD_RIN_*), 0 netlist-generation errors
(remediation spec R1.7: 252-5+15 parts, 213+4 TAP_GATE_* nets; round-2
remediation 2026-07-21 (Codex R2-4/R2-6): +9 parts (J16 protection stack +
REV_ID straps) and +6 nets (J16_5V/J16_3V3/J16_SDA/J16_SCL/REV_ID0/REV_ID1)
-> 262+9 / 217+6).
ERC baseline (waiver WVR-ERC-1, recorded in docs/phase8_revD_run_log.md):
EXACTLY 1 ERC error — the Pico module's AGND (pin 33) vs GND (pin 3)
POWER-OUT/POWER-OUT pin-type conflict, a SKiDL symbol artifact (both pins are
grounds of the same module and MUST be tied; electrically benign) — plus 39
baseline warnings. main() enforces this fail-closed: any second error, a
different single error, or warning-count drift aborts the run, so a REAL
future ERC error can never hide behind the known baseline.
Output: kicad/wsl-phase8b-revD.net (NEW file — never the rev-C wsl-phase8b.net).

Refdes note: tags are the stable identity (all downstream scripts key on the
SKiDL Tag field). Appending parts mid-sequence shifts the numeric refdes of
later same-prefix parts vs rev-C (e.g. the 8 AUX optos shift U_WDOG's U-number;
the two bleed resistors shift the block_rail R-numbers). This is expected and
recorded in kicad/revD/netlist_diff_revC_to_revD.txt.

--- original rev-B/rev-C docstring follows ---

This generator is intentionally separate from the Rev-A generator. It emits a
Rev-B connectivity scaffold with function-named machine connectors. Ratings,
per-channel dry/AC population, and final connector/pin choices still need the
at-machine checks listed in docs/phase8b_pcb_revB_spec.md.

The corrective pass wires the previously orphaned blocks:
  - fast optos -> Pico GPIOs and field connector
  - slow optos -> MCP23017 GPIOs and field connectors
  - MCP outputs -> relay/logic-LED drivers
  - relay contacts/snubber/MOV footprints -> motion connector
  - logic LED outputs -> lamp connector
  - J_SAFETY loops -> relay-enable rail source
  - Rev-A-style NE555 watchdog timing network -> rail AND chain
"""

import os
import pathlib
import subprocess
import sys

SCRIPT_PATH = pathlib.Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
ERC_ARTIFACT = REPO_ROOT / f"{SCRIPT_PATH.stem}.erc"

# SKiDL traverses sets/dicts while emitting the legacy netlist. Re-exec before
# importing it with a fixed hash seed so separate clean processes serialize the
# same electrical graph in the same order.
if os.environ.get("PYTHONHASHSEED") != "0":
    child_env = os.environ.copy()
    child_env["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *sys.argv[1:]],
        cwd=pathlib.Path.cwd(),
        env=child_env,
        check=False,
    )
    raise SystemExit(completed.returncode)

KICAD_CANDIDATE_ROOTS = [
    r"C:\Program Files\KiCad\10.0\share\kicad",
    r"C:\Program Files\KiCad\9.0\share\kicad",
    r"C:\Program Files (x86)\KiCad\10.0\share\kicad",
]

kicad_root = next((p for p in KICAD_CANDIDATE_ROOTS if os.path.isdir(p)), None)
if kicad_root is None:
    sys.exit("ERROR: KiCad install not found; edit KICAD_CANDIDATE_ROOTS.")

symbol_dir = os.path.join(kicad_root, "symbols")
footprint_dir = os.path.join(kicad_root, "footprints")
for var in ["KICAD_SYMBOL_DIR"] + [f"KICAD{v}_SYMBOL_DIR" for v in (6, 7, 8, 9, 10)]:
    os.environ[var] = symbol_dir
for var in ["KICAD_FOOTPRINT_DIR"] + [f"KICAD{v}_FOOTPRINT_DIR" for v in (6, 7, 8, 9, 10)]:
    os.environ[var] = footprint_dir
print(f"Using KiCad libraries at {kicad_root}")

# SKiDL selects its .erc log location when its logger is imported. Anchor that
# import at the repository root so invoking this script from root, scripts/, an
# IDE, or a clean-clone verifier can only ever write ERC_ARTIFACT.
_caller_cwd = pathlib.Path.cwd()
try:
    os.chdir(REPO_ROOT)
    from skidl import ERC, KICAD, SKIDL, Part, Pin, Net, generate_netlist, lib_search_paths, set_default_tool
finally:
    os.chdir(_caller_cwd)

set_default_tool(KICAD)
lib_search_paths[KICAD].append(symbol_dir)


# Footprints verified present in the local KiCad 10 footprint tree.
FP_R = "Resistor_SMD:R_0805_2012Metric"
FP_C = "Capacitor_SMD:C_0805_2012Metric"
FP_CP = "Capacitor_SMD:CP_Elec_6.3x5.4"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FP_SOIC28 = "Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
FP_PC817 = "Package_DIP:DIP-4_W7.62mm"
FP_RELAY = "Relay_THT:Relay_SPDT_Omron-G5LE-1"
FP_TMA = "Converter_DCDC:Converter_DCDC_TRACO_TMA-05xxS_12xxS_Single_THT"
FP_PICO = "Module:RaspberryPi_Pico_SMD"
FP_D_SOD323 = "Diode_SMD:D_SOD-323"
FP_D_SMA = "Diode_SMD:D_SMA"
FP_TB3 = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal"
FP_IDC_2X10 = "Connector_IDC:IDC-Header_2x10_P2.54mm_Vertical"
# Rev-D remediation R2.5 (Codex M4): ALL MCV 1,5 G-3.5 instances repoint to
# PROJECT-LOCAL copies (kicad/wsl_footprints.pretty, suffix _D1.4) with drill
# 1.2 -> 1.4 mm per the Phoenix MC 1,5 / MCV 1,5 G-3.5 drilling plan (1843680
# header system) and pad narrow axis 1.8 -> 2.0 mm (annular ring 0.30 mm >=
# JLC's 0.20 mm multilayer floor + 50%). The system KiCad library is NEVER
# edited — it also serves the sacred rev-C generator. Run-log entry FR-9.
FP_MCV_1X04 = "wsl_footprints:PhoenixContact_MCV_1,5_4-G-3.5_1x04_P3.50mm_Vertical_D1.4"
FP_MCV_1X06 = "wsl_footprints:PhoenixContact_MCV_1,5_6-G-3.5_1x06_P3.50mm_Vertical_D1.4"
FP_MCV_1X10 = "wsl_footprints:PhoenixContact_MCV_1,5_10-G-3.5_1x10_P3.50mm_Vertical_D1.4"
FP_MCV_1X12 = "wsl_footprints:PhoenixContact_MCV_1,5_12-G-3.5_1x12_P3.50mm_Vertical_D1.4"
FP_MCV_1X14 = "wsl_footprints:PhoenixContact_MCV_1,5_14-G-3.5_1x14_P3.50mm_Vertical_D1.4"
FP_TB_1X02_508 = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"
# Rev-D round-2 (Codex R2-4/R2-6, 2026-07-21): J16 protection stack + REV_ID
# straps. All system-library footprints, verified present in KiCad 10.0.2
# (run-log FR-11..FR-14).
FP_FUSE_1206 = "Fuse:Fuse_1206_3216Metric"
FP_SJ2_OPEN = "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm"
FP_SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
FP_VSSOP8 = "Package_SO:VSSOP-8_3x3mm_P0.65mm"


# Global rails and control nets.
VRAW = Net("VCC_5V_RAW")
VCC5 = Net("VCC_5V")
VCC3V3 = Net("VCC_3V3")
GND = Net("GND")
FGND = Net("FIELD_GND")
WET = Net("FIELD_WET_V")
SDA = Net("I2C_SDA")
SCL = Net("I2C_SCL")
UART_TX = Net("PI_UART_TX")
UART_RX = Net("PI_UART_RX")
KICK = Net("WDOG_KICK")
ARM = Net("ARM_PERMIT")
RP_OK = Net("RP2040_OK")
INT_A = Net("MCP_INT_A")
INT_B = Net("MCP_INT_B")
RAIL_EN = Net("RELAY_ENABLE_RAIL")
# Rev-D round-2 (Codex R2-4): J16 no longer touches the raw rails/bus.
# Pin 1 sits behind a 200 mA polyfuse (J16_5V), pin 5 behind a default-OPEN
# solder link (J16_3V3), pins 3/4 behind a TCA4307 stuck-bus-recovery I2C
# buffer (J16_SDA/J16_SCL). All four are LOGIC-domain nets.
J16_5V = Net("J16_5V")
J16_3V3 = Net("J16_3V3")
J16_SDA = Net("J16_SDA")
J16_SCL = Net("J16_SCL")

parts = {}
# r6 (2026-07-25): channel -> (FIELD_RIN_<n>, FIELD_LED_<n>, FIELD_<n>,
# FAST_/SLOW_<n>) handles, filled by opto_input() and consumed by
# block_input_protection(). Keyed by channel name; insertion order is the
# opto instantiation order (8 fast, then the 32 slow channels).
input_protection_nodes = {}


FAST_INPUTS = [
    ("SA", 9),
    ("SB", 10),
    ("SC", 11),
    ("TA1", 12),
    ("TA2", 14),
    ("TB", 15),
    ("DIELL_L", 16),
    ("DIELL_R", 17),
]

# MCP23017 pin numbers: GPA0-7 are 21-28, GPB0-7 are 1-8.
# Rev-D item C: AUX4-AUX11 appended at the END of the dict (preserves
# instantiation order for all pre-existing channels) on MCP_IN_B GPB0-7.
SLOW_INPUT_PINS = {
    "GS1": ("MCP_IN_A", 21),
    "GS2": ("MCP_IN_A", 22),
    "GS3": ("MCP_IN_A", 23),
    "GS4": ("MCP_IN_A", 24),
    "GS5": ("MCP_IN_A", 25),
    "GS6": ("MCP_IN_A", 26),
    "GS7": ("MCP_IN_A", 27),
    "GS8": ("MCP_IN_A", 28),
    "GS9": ("MCP_IN_A", 1),
    "GS10": ("MCP_IN_A", 2),
    "GP": ("MCP_IN_A", 3),
    "OS": ("MCP_IN_A", 4),
    "BS": ("MCP_IN_A", 5),
    "PBZ": ("MCP_IN_A", 6),
    "PBC": ("MCP_IN_A", 7),
    "FOUL": ("MCP_IN_A", 8),
    "TENTH": ("MCP_IN_B", 21),
    "MAN_T": ("MCP_IN_B", 22),
    "MAN_S": ("MCP_IN_B", 23),
    "MAN_SWS": ("MCP_IN_B", 24),
    "MAN_SWSR": ("MCP_IN_B", 25),
    "AUX1": ("MCP_IN_B", 26),
    "AUX2": ("MCP_IN_B", 27),
    "AUX3": ("MCP_IN_B", 28),
    "AUX4": ("MCP_IN_B", 1),
    "AUX5": ("MCP_IN_B", 2),
    "AUX6": ("MCP_IN_B", 3),
    "AUX7": ("MCP_IN_B", 4),
    "AUX8": ("MCP_IN_B", 5),
    "AUX9": ("MCP_IN_B", 6),
    "AUX10": ("MCP_IN_B", 7),
    "AUX11": ("MCP_IN_B", 8),
}

OUTPUT_PINS = {
    "S": 21,
    "T": 22,
    "SP": 23,
    "BE": 24,
    "M": 25,
    "M2": 26,
    "M1": 27,
    "L_FIRST": 28,
    "L_SECOND": 1,
    "L_STRIKE": 2,
    "L_FOUL": 3,
}


def add_res(name, value, footprint=FP_R):
    r = Part("Device", "R", value=value, footprint=footprint, tag=name)
    parts[name] = r
    return r


def add_cap(name, value, footprint=FP_C, polarized=False):
    sym = "C_Polarized" if polarized else "C"
    c = Part("Device", sym, value=value, footprint=footprint, tag=name)
    parts[name] = c
    return c


def add_drive_pulldown(name, net):
    global GND

    rpd = add_res(f"Rpd_{name}", "100k")
    net += rpd[1]
    GND += rpd[2]
    return rpd


def block_rp2040(fast_logic):
    global VCC5, VCC3V3, GND, UART_TX, UART_RX, RP_OK

    pico = Part("MCU_Module", "RaspberryPi_Pico", value="RP2040 Pico", footprint=FP_PICO, tag="RP_PICO")
    parts["RP_PICO"] = pico

    VCC5 += pico[39]       # VSYS.
    VCC3V3 += pico[36]     # Pico 3V3 output.
    GND += pico[3], pico[8], pico[13], pico[18], pico[23], pico[28], pico[33], pico[38]

    UART_TX += pico[2]     # Pi TX -> Pico GP1/RX.
    UART_RX += pico[1]     # Pico GP0/TX -> Pi RX.
    RP_OK += pico[4]       # GP2: firmware health/cam-stop permission.

    for name, pico_pin in FAST_INPUTS:
        fast_logic[name] += pico[pico_pin]

    return pico


def block_mcp(refval, a0a1a2, int_net=None):
    # a0a1a2 = MCP23017 address straps in (A0, A1, A2) order — tuple[0] lands on
    # pin 15 (A0), tuple[1] on pin 16 (A1), tuple[2] on pin 17 (A2), matching the
    # zip((15, 16, 17), ...) below. I2C address = 0x20 | (A2<<2 | A1<<1 | A0).
    # (Was misleadingly named a2a1a0 — the consumption order was always A0-first.)
    global VCC3V3, GND, SDA, SCL

    mcp = Part(
        "Interface_Expansion",
        "MCP23017x-x-SO",
        value=f"MCP23017 {refval}",
        footprint=FP_SOIC28,
        tag=refval,
    )
    parts[refval] = mcp

    # Verified KiCad symbol pin numbers:
    # 9=VDD, 10=VSS, 12=SCK, 13=SDA, 15=A0, 16=A1, 17=A2,
    # 18=~RESET, 19=INTB, 20=INTA, 21-28=GPA0-7, 1-8=GPB0-7.
    VCC3V3 += mcp[9], mcp[18]
    GND += mcp[10]
    SCL += mcp[12]
    SDA += mcp[13]
    for pin, high in zip((15, 16, 17), a0a1a2):   # (A0, A1, A2) order
        if high:
            VCC3V3 += mcp[pin]
        else:
            GND += mcp[pin]
    if int_net is not None:
        int_net += mcp[20]

    c = add_cap(f"C_{refval}", "0.1uF")
    VCC3V3 += c[1]
    GND += c[2]
    return mcp


def block_i2c_pullups():
    global VCC3V3, SDA, SCL
    rsda = add_res("R_I2C_SDA", "4.7k")
    rscl = add_res("R_I2C_SCL", "4.7k")
    VCC3V3 += rsda[1], rscl[1]
    SDA += rsda[2]
    SCL += rscl[2]


def opto_input(name, logic_net, field_net):
    global VCC3V3, GND, WET

    opto = Part("Isolator", "PC817", value=f"PC817 {name}", footprint=FP_PC817, tag=f"OPTO_{name}")
    parts[f"OPTO_{name}"] = opto
    rin = add_res(f"Rin_{name}", "2k2")
    # Rev-D diagnostic hardening (2026-07-23): the selected UMW PC817B lot has
    # no guaranteed CTR minimum at this design's ~1.7 mA LED current. A 47k
    # collector pull-up lowers the MCP23017 VIL-threshold sink requirement to
    # (3.3 V - 0.66 V) / 47k = 56 uA while keeping wetting current unchanged.
    # This value is scoped only to the 40 Rpu_* parts.
    rpu = add_res(f"Rpu_{name}", "47k")
    # r6 input protection (2026-07-25, docs/phase8_revD_r6_input_protection_
    # spec_2026-07-25.md §A.1): Rin's output is no longer the LED-anode node.
    # A NEW named node FIELD_RIN_<n> sits between Rin and the series blocking
    # diode; FIELD_LED_<n> is now the LED-anode node only (Dser cathode +
    # Dclamp cathode + PC817 pin 1). Both parts are instantiated LATER, in
    # block_input_protection(), so no existing refdes moves (§E.3).
    rin_series = Net(f"FIELD_RIN_{name}")
    led_series = Net(f"FIELD_LED_{name}")

    # Dry-contact default: WET -> Rin -> Dser -> opto LED -> field pin. The
    # field contact closes that pin to FIELD_GND at the connector/harness.
    WET += rin[1]
    rin_series += rin[2]
    led_series += opto[1]
    opto[2] += field_net

    # Logic side is 3.3 V so Pico and MCP inputs are Pi-safe.
    opto[4] += logic_net
    opto[3] += GND
    VCC3V3 += rpu[1]
    logic_net += rpu[2]
    input_protection_nodes[name] = (rin_series, led_series, field_net, logic_net)
    return opto


def block_input_protection():
    """r6 per-channel input protection on all 40 optocoupler channels.

    Spec: docs/phase8_revD_r6_input_protection_spec_2026-07-25.md §A.
    Evidence: docs/phase8_revD_input_frontend_recommendation.md (measured
    lane-22 field voltages) + docs/phase8_revD_round5_claude_audit_2026-07-25.md
    §5 (the electrical case, and the four corrections the spec carries forward).

    Per channel, three provisions:

      Dser_<n>   1N4148WS SOD-323, SERIES BLOCK, ALWAYS POPULATED.
                 Anode (pin 2) on FIELD_RIN_<n>, cathode (pin 1) on
                 FIELD_LED_<n>. Blocks the reverse half-cycle / reverse DC so
                 an over-voltage channel cannot backfeed Rin into the SHARED
                 FIELD_WET_V rail (the unregulated TMA-0505S cannot sink it:
                 the clamp-alone solve pulls Vw to 10.77 V at 9.79 mA on a
                 33 VDC PBZ channel — spec §F.3). NEVER DNP: a DNP-empty
                 series position leaves the channel OPEN-CIRCUIT (§A.3.4).
                 CTR cost 22x -> 17.1x; the rev-D 47k collector pull-up
                 already paid for it, so Rin STAYS 2k2 (§C).

      Dclamp_<n> 1N4148WS SOD-323, ANTI-PARALLEL CLAMP across the PC817 LED.
                 Cathode (pin 1) on FIELD_LED_<n>, anode (pin 2) on the field
                 pin. With Dser fitted it is never a current path (leakage
                 only, <= 15 uA), so it is a VOLTAGE-DEFINING element: it pins
                 the LED reverse voltage at ~0.35 V against the PC817's 6 V
                 absolute maximum (17x inside), BY CONSTRUCTION rather than by
                 the diode/LED leakage ratio a series diode alone would rely
                 on (§A.3.2, §F.3). Populated by default (spec §A.4 NORMATIVE);
                 variant B = value "1N4148 DNP", copper identical (§A.6).

      Cflt_<n>   0805 X7R, DNP BY DESIGN, logic side (opto collector -> GND).
                 2.2uF on the 32 MCP23017 slow channels (60 Hz AC integration,
                 951 nF minimum effective, 183 ms de-assert), 10nF on the 8
                 RP2040 fast channels (de-glitch; NEVER exceed 22 nF on
                 GP6-GP13 — the 1 ms edge budget, spec §B.3/§B.4). Fit ONLY on
                 a channel MEASURED to carry a 60 Hz pulse train.

    Instantiated AFTER every existing block so the new parts take D18-D97 and
    C17-C56 and ZERO existing refdes moves (spec §E.3) — in particular
    EXPECTED_OPTO_PULLUPS = {R4, R6, ... R82} in audit_revD_board.py and the
    manual's designator tables stay correct. This is also why the series
    element is a diode on a SOD-323 land and NOT a 0R 0805 link: 40 R-prefix
    parts would shift every resistor above R3 by 40, and an 0805 land
    (pads +/-0.913) and a SOD-323 land (pads +/-1.05) cannot be shared, so the
    "0R now, diode later" swap plan does not survive a real footprint (§A.4).
    """
    global GND

    fast_names = {n for n, _ in FAST_INPUTS}
    for name, (rin_series, led_series, field_net, logic_net) in input_protection_nodes.items():
        dser = Part("Device", "D", value="1N4148", footprint=FP_D_SOD323,
                    tag=f"Dser_{name}")
        parts[f"Dser_{name}"] = dser
        rin_series += dser[2]   # anode  (Device:D pin 2 = A) faces Rin / the board
        led_series += dser[1]   # cathode (pin 1 = K) faces the PC817 LED anode

        dclamp = Part("Device", "D", value="1N4148", footprint=FP_D_SOD323,
                      tag=f"Dclamp_{name}")
        parts[f"Dclamp_{name}"] = dclamp
        led_series += dclamp[1]  # cathode on the LED-anode node ...
        field_net += dclamp[2]   # ... anode on the field pin => ANTI-PARALLEL

        cval = "10nF X7R DNP" if name in fast_names else "2.2uF X7R DNP"
        cflt = add_cap(f"Cflt_{name}", cval)
        logic_net += cflt[1]
        GND += cflt[2]


def relay_output(name, drive_net, out_a, out_b, dnp=False):
    global GND, RAIL_EN

    value = f"G5LE {name}" + (" DNP" if dnp else "")
    relay = Part("Relay", "G5LE-1", value=value, footprint=FP_RELAY, tag=f"K_{name}")
    parts[f"K_{name}"] = relay
    q = Part("Transistor_BJT", "MMBT3904", value=f"MMBT3904 {name}", footprint=FP_SOT23, tag=f"Qk_{name}")
    parts[f"Qk_{name}"] = q
    rb = add_res(f"Rb_{name}", "1k")
    add_drive_pulldown(name, drive_net)
    fly = Part("Device", "D", value="1N4148", footprint=FP_D_SOD323, tag=f"Dfly_{name}")
    parts[f"Dfly_{name}"] = fly
    base = Net(f"BASE_{name}")
    coil_lo = Net(f"COIL_LO_{name}")

    drive_net += rb[1]
    base += rb[2], q[1] # B
    GND += q[2]         # E
    # G5LE-14 as placed on rev-B uses the G5LE footprint mechanically, but the
    # actual 5 V coil is on pads 2/5. Pad 1 is COM, pad 3 is NO, pad 4 is NC (unused).
    # NO=pad3 corrected after board-#1 meter: J11 pin1->COM CLOSED at rest => pad4 is NC.
    RAIL_EN += relay[2]
    coil_lo += relay[5], q[3]    # C
    fly[1] += relay[2]  # diode cathode to rail
    fly[2] += coil_lo   # diode anode to switched coil side

    # Dry contact and depopulatable arc suppression across the contact.
    relay[1] += out_a   # COM (pad 1)
    relay[3] += out_b   # NO  (pad 3; pad 4 = NC, unused)
    snub_r = add_res(f"Rsnub_{name}", "100R DNP")
    snub_c = add_cap(f"Csnub_{name}", "10nF X2 DNP")
    mov = Part("Device", "D", value="MOV DNP", footprint=FP_D_SMA, tag=f"MOV_{name}")
    parts[f"MOV_{name}"] = mov
    snub_mid = Net(f"SNUB_{name}")
    out_a += snub_r[1], mov[1]
    snub_mid += snub_r[2], snub_c[1]
    out_b += snub_c[2], mov[2]
    return relay


def lamp_led_output(name, drive_net, led_return):
    global GND

    q = Part("Transistor_FET", "Q_NMOS_GSD", value=f"2N7002 LED {name}", footprint=FP_SOT23, tag=f"Qled_{name}")
    parts[f"Qled_{name}"] = q
    rg = add_res(f"Rgled_{name}", "1k")
    rpd = add_res(f"Rpdled_{name}", "100k")
    rlim = add_res(f"Rled_{name}", "330R")
    gate = Net(f"LED_GATE_{name}")
    sink = Net(f"LED_SINK_{name}")

    drive_net += rg[1]
    gate += rg[2], rpd[1], q[1]  # G
    GND += rpd[2], q[2]          # S
    led_return += rlim[1]
    sink += rlim[2], q[3]        # D
    return q


def block_watchdog():
    global VCC5, GND, KICK

    u = Part("Timer", "NE555D", value="NE555", footprint=FP_SOIC8, tag="U_WDOG")
    parts["U_WDOG"] = u
    qkick = Part("Transistor_FET", "Q_NMOS_GSD", value="AO3400A kick", footprint=FP_SOT23, tag="Q_WDOG_KICK")
    parts["Q_WDOG_KICK"] = qkick
    qwd = Part("Transistor_FET", "Q_NMOS_GSD", value="AO3400A wdog", footprint=FP_SOT23, tag="Q_WDOG_OK")
    parts["Q_WDOG_OK"] = qwd

    rtim = add_res("R_WDOG_TIMING", "100k")
    rtrig = add_res("R_WDOG_TRIG_PULLUP", "10k")
    rkick = add_res("R_WDOG_KICK_GATE", "1k")
    rkick_pd = add_res("R_WDOG_KICK_PD", "10k")
    rqwd = add_res("R_WDOG_OUT_GATE", "1k")
    rqwd_pd = add_res("R_WDOG_OUT_PD", "10k")
    ctim = add_cap("C_WDOG_TIMING", "100uF/16V", FP_CP, polarized=True)
    cvcc = add_cap("C_WDOG_VCC", "0.1uF")
    cctrl = add_cap("C_WDOG_CTRL", "10nF")
    d_timing = Part("Device", "D", value="1N4148", footprint=FP_D_SOD323, tag="D_WDOG_TIMING")
    d_trig = Part("Device", "D", value="1N4148", footprint=FP_D_SOD323, tag="D_WDOG_TRIG")
    parts["D_WDOG_TIMING"] = d_timing
    parts["D_WDOG_TRIG"] = d_trig

    q1_gate = Net("WDOG_KICK_GATE")
    q1_drain = Net("WDOG_KICK_DRAIN")
    timing = Net("WDOG_TIMING_NODE")
    trig = Net("NE555_TRIG")
    out = Net("NE555_OUT")
    q2_gate = Net("WDOG_OK_GATE")
    wdog_pull = Net("WDOG_OK_PULLDOWN")
    ctrl = Net("NE555_CTRL")

    VCC5 += u[4], u[8], rtim[1], rtrig[1], cvcc[1]
    GND += u[1], ctim[2], cvcc[2], cctrl[2], rkick_pd[2], rqwd_pd[2], qkick[2], qwd[2]

    KICK += rkick[1]
    q1_gate += rkick[2], rkick_pd[1], qkick[1]
    q1_drain += qkick[3], d_timing[1], d_trig[1]

    timing += u[6], u[7], rtim[2], ctim[1], d_timing[2]
    trig += u[2], rtrig[2], d_trig[2]
    out += u[3], rqwd[1]
    q2_gate += rqwd[2], rqwd_pd[1], qwd[1]
    wdog_pull += qwd[3]
    ctrl += u[5], cctrl[1]

    # Rev-D: also return the NE555 output net so block_diag() can tap it
    # (item E). Electrically identical to rev-C; only the return arity changed.
    return wdog_pull, out


def block_connectors(fast_field, slow_field, motion_pairs, lamp_returns):
    global VRAW, VCC5, VCC3V3, GND, FGND, SDA, SCL, UART_TX, UART_RX, KICK, ARM, RP_OK, INT_A, INT_B
    global J16_5V, J16_3V3, J16_SDA, J16_SCL

    j_pi = Part("Connector_Generic", "Conn_02x10_Odd_Even", value="J_PI", footprint=FP_IDC_2X10, tag="J_PI")
    j_pwr = Part("Connector_Generic", "Conn_01x03", value="J_PWR 5V", footprint=FP_TB3, tag="J_PWR")
    j_fast = Part("Connector_Generic", "Conn_01x10", value="J_FAST_IN", footprint=FP_MCV_1X10, tag="J_FAST")
    j_slowa = Part("Connector_Generic", "Conn_01x14", value="J_SLOW_IN_A", footprint=FP_MCV_1X14, tag="J_SLOWA")
    j_slowb = Part("Connector_Generic", "Conn_01x12", value="J_SLOW_IN_B", footprint=FP_MCV_1X12, tag="J_SLOWB")
    j_motion = {
        name: Part(
            "Connector_Generic",
            "Conn_01x02",
            value=f"J_MOTION_{name} 5.08mm",
            footprint=FP_TB_1X02_508,
            tag=f"J_MOTION_{name}",
        )
        for name in ["S", "T", "SP", "BE", "M", "M2", "M1"]
    }
    j_lamp = Part("Connector_Generic", "Conn_01x06", value="J_LAMP_LED", footprint=FP_MCV_1X06, tag="J_LAMP")
    j_safe = Part("Connector_Generic", "Conn_01x04", value="J_SAFETY", footprint=FP_MCV_1X04, tag="J_SAFE")
    # Rev-D item C: J15 field connector for the AUX4-AUX11 GPB bank.
    # Instantiated AFTER the rev-C connectors (J1-J14) so the emitted refdes
    # lands at J15; mating plug Phoenix MC 1,5/10-ST-3,5 = 1840447.
    # CROSS-MATE GUARD (gate OG-3): same plug PN as J3 on the same field
    # edge — a J3/J15 swap is same-domain and electrically silent but crosses
    # the cycle sensors with AUX contacts. Harness BOM carries CP-MSTB
    # 1734634 coding profiles at DIFFERENT pole positions (J3: pole 1;
    # J15: pole 10) + distinct plug colors; silk warns at both connectors.
    j_slowc = Part("Connector_Generic", "Conn_01x10", value="J_SLOW_IN_C", footprint=FP_MCV_1X10, tag="J_SLOWC")
    # Rev-D item F: J16 external-analog / I2C expansion header (LOGIC domain
    # only; any module carries its own isolation and must avoid addresses
    # 0x20-0x23). Mating plug Phoenix MC 1,5/6-ST-3,5 = 1840405.
    # CROSS-MATE GUARD (gate OG-3): same plug PN as J13 (lamps) on the same
    # edge, identical VCC_5V/GND on pins 1/2 — a lamp harness in J16 puts
    # resistorless LED strings on 5 V/SDA/SCL. CP-MSTB 1734634 coding at
    # DIFFERENT pole positions (J13: pole 1; J16: pole 6) + distinct plug
    # colors; silk warns at both connectors.
    j_exti2c = Part("Connector_Generic", "Conn_01x06", value="J_EXT_I2C", footprint=FP_MCV_1X06, tag="J_EXTI2C")

    for key, conn in (
        ("J_PI", j_pi),
        ("J_PWR", j_pwr),
        ("J_FAST", j_fast),
        ("J_SLOWA", j_slowa),
        ("J_SLOWB", j_slowb),
        ("J_LAMP", j_lamp),
        ("J_SAFE", j_safe),
        ("J_SLOWC", j_slowc),
        ("J_EXTI2C", j_exti2c),
    ):
        parts[key] = conn
    for name, conn in j_motion.items():
        parts[f"J_MOTION_{name}"] = conn

    VCC5 += j_pi[1]
    GND += j_pi[2], j_pi[12]
    SDA += j_pi[3]
    SCL += j_pi[4]
    UART_TX += j_pi[5]
    UART_RX += j_pi[6]
    KICK += j_pi[7]
    ARM += j_pi[8]
    INT_A += j_pi[9]
    INT_B += j_pi[10]
    VCC3V3 += j_pi[11]
    RP_OK += j_pi[13]

    VRAW += j_pwr[1]
    GND += j_pwr[2], j_pwr[3]
    # Rev-D (spec §H.4, review finding 2026-07-20): SS14 (1 A) -> SS34 (3 A).
    # The rev-D worst case is 0.73-0.93 A on a rail whose SS14 margin was ALREADY
    # thin; SS34 buys headroom with zero copper change (value swap only). The
    # generator is the BOM source of truth so the substitution lands HERE.
    # (R3-7, 2026-07-21: the J16 sanctioned module allowance was RE-DERIVED from
    # the Littelfuse 1206L020 temperature-derating table to 45 mA @ 85 C worst
    # case, down from the false 100 mA; the corrected 45 mA takes the worst case
    # to ~0.775-0.975 A, so the reduced allowance only WIDENS the SS34 margin --
    # it does not un-justify the swap, and SS14 stays retired.) Gate-10 check
    # done: MPN MDD SS34, LCSC C8678,
    # package SMA/DO-214AC verified (SS34 also ships in SMB/SMC from other
    # vendors — do NOT swap MPNs without re-running gate 10). Same D_SMA
    # footprint, zero copper change. Run-log entry FR-3.
    dprot = Part("Device", "D_Schottky", value="SS34", footprint=FP_D_SMA, tag="D_PROT")
    parts["D_PROT"] = dprot
    VRAW += dprot[2]   # anode
    VCC5 += dprot[1]   # cathode

    for pin, (name, _) in enumerate(FAST_INPUTS, start=1):
        fast_field[name] += j_fast[pin]
    FGND += j_fast[9], j_fast[10]

    slowa_order = [f"GS{i}" for i in range(1, 11)] + ["GP", "OS", "BS"]
    for pin, name in enumerate(slowa_order, start=1):
        slow_field[name] += j_slowa[pin]
    FGND += j_slowa[14]

    slowb_order = ["PBZ", "PBC", "FOUL", "TENTH", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "AUX1", "AUX2", "AUX3"]
    for pin, name in enumerate(slowb_order, start=1):
        slow_field[name] += j_slowb[pin]
    FGND += j_slowb[12]

    # Rev-D item C: J15 pinout mirrors J3's keying pattern (signals 1-8,
    # doubled FIELD_GND on the last two pins).
    slowc_order = [f"AUX{i}" for i in range(4, 12)]
    for pin, name in enumerate(slowc_order, start=1):
        slow_field[name] += j_slowc[pin]
    FGND += j_slowc[9], j_slowc[10]

    # Rev-D item F, REVISED by round-2 remediation R2-4 (2026-07-21): the
    # J16 pin functions are unchanged (5V / GND / SDA / SCL / 3V3 / GND) but
    # every non-GND pin now lands on a PROTECTED net:
    #   pin 1 -> J16_5V   (behind the F_J16_5V 200 mA polyfuse)
    #   pin 3 -> J16_SDA  (behind the TCA4307 buffer + local pull-up + ESD)
    #   pin 4 -> J16_SCL  (ditto)
    #   pin 5 -> J16_3V3  (behind the JP_J16_3V3 default-OPEN solder link —
    #                      the pin ships NC; bridge only for a verified
    #                      3.3 V module)
    # A wedged/shorted external module can no longer wedge the main I2C bus
    # (MCP_OUT_A holding last relay state was the FR-5 hazard) nor drag the
    # main 5 V rail. Parts live in block_j16_protection_and_revid().
    J16_5V += j_exti2c[1]
    GND += j_exti2c[2], j_exti2c[6]
    J16_SDA += j_exti2c[3]
    J16_SCL += j_exti2c[4]
    J16_3V3 += j_exti2c[5]

    motion_order = ["S", "T", "SP", "BE", "M", "M2", "M1"]
    for name in motion_order:
        a, b = motion_pairs[name]
        # Put each relay pair on its own 2-pin terminal in the same vertical
        # order as the G5LE contact pads (B above A). Splitting the compressed
        # 14-pin block into per-function blocks keeps the harness
        # function-named while preserving channel-to-channel creepage.
        b += j_motion[name][1]
        a += j_motion[name][2]

    lamp_order = ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]
    VCC5 += j_lamp[1]
    GND += j_lamp[2]
    for pin, name in enumerate(lamp_order, start=3):
        lamp_returns[name] += j_lamp[pin]

    return {"J_SAFE": j_safe}


def block_supplies():
    global VCC5, VCC3V3, GND, FGND, WET

    iso = Part("Converter_DCDC", "TMA-0505S", value="TMA-0505S", footprint=FP_TMA, tag="ISO_WET")
    parts["ISO_WET"] = iso
    iso["+Vin"] += VCC5
    iso["-Vin"] += GND
    iso["+Vout"] += WET
    iso["-Vout"] += FGND

    # The Pico module supplies VCC_3V3. This capacitor makes the rail visible
    # and gives KiCad something local to place near the MCP/Pico cluster.
    c = add_cap("C_3V3_BULK", "10uF")
    VCC3V3 += c[1]
    GND += c[2]

    # Rev-D item A: FIELD_WET_V minimum-load bleed. 2 x 2k2 0805 in PARALLEL
    # (1.1k effective): 4.5 mA at 5 V nominal, 11.4 mW/part; 89 mW/part even at
    # the 14 V unloaded-float bound < 125 mW 0805 rating. Kills the 11-14 V
    # unloaded float on the unregulated TMA-0505S (TP4 gate: <= ~6 V unloaded).
    # Entirely FIELD-domain; both ends land on existing nets (0 new nets).
    rb1 = add_res("R_WET_BLEED1", "2k2")
    rb2 = add_res("R_WET_BLEED2", "2k2")
    WET += rb1[1], rb2[1]
    FGND += rb1[2], rb2[2]
    return iso


def block_rail(wdog_pull, j_safe):
    global VCC5, GND, ARM, RP_OK, RAIL_EN

    qpass = Part("Transistor_FET", "Q_PMOS_GSD", value="AO3401A rail pass", footprint=FP_SOT23, tag="Q_RAIL")
    parts["Q_RAIL"] = qpass
    safe_mid = Net("SAFE_TBSC_RETURN")
    safe_src = Net("SAFE_STOP_RETURN")

    # Two external NC loops in series:
    # VCC5 -> J_SAFE1/2 TBSC loop -> J_SAFE3/4 Stop/CIS loop -> PMOS source.
    VCC5 += j_safe[1]
    safe_mid += j_safe[2], j_safe[3]
    safe_src += j_safe[4], qpass["S"]
    qpass["D"] += RAIL_EN

    gate = Net("RAIL_GATE")
    rgate = add_res("R_RAIL_GATE_PULLUP", "100k")
    safe_src += rgate[1]
    gate += rgate[2], qpass["G"]

    q_arm = Part("Transistor_BJT", "MMBT3904", value="MMBT3904 AND ARM", footprint=FP_SOT23, tag="Q_AND_ARM")
    q_rpok = Part("Transistor_BJT", "MMBT3904", value="MMBT3904 AND RP_OK", footprint=FP_SOT23, tag="Q_AND_RP_OK")
    parts["Q_AND_ARM"] = q_arm
    parts["Q_AND_RP_OK"] = q_rpok

    n_mid = Net("AND_MID_ARM_RP")
    q_arm[3] += gate
    q_arm[2] += n_mid
    q_rpok[3] += n_mid
    q_rpok[2] += wdog_pull

    for tag, sig, q in (("ARM", ARM, q_arm), ("RP_OK", RP_OK, q_rpok)):
        rb = add_res(f"Rb_AND_{tag}", "10k")
        rpd = add_res(f"Rpd_AND_{tag}", "100k")
        base = Net(f"BASE_AND_{tag}")
        sig += rb[1]
        base += rb[2], q[1], rpd[1]
        GND += rpd[2]

    return qpass


def block_diag(pico, ne555_out):
    """Rev-D items D + E: board-self-health ADC divider + rail-drop edge taps.

    Everything here is LOGIC-domain copper on EXISTING observable points.
    Explicitly out of scope (spec §E): SAFE_* loops, RELAY_ENABLE_RAIL,
    RAIL_GATE — no connection of any kind to safety-rail nets, and there is
    NO RELAY_ENABLE_RAIL divider (a prior critic deleted it; VCC_5V sensing
    only).
    """
    global VCC5, VCC3V3, GND, KICK, ARM, RP_OK

    # Item D: VCC_5V ADC divider 10k/10k + 100nF -> Pico pin 31 (GP26/ADC0).
    # 5k Thevenin (< 10k RP2040 ADC guidance), 318 Hz RC (ADC channel, not an
    # edge channel), 0.25 mA permanent load, 5.25 V worst -> 2.63 V < 3.3 V.
    # ADC_VREF (Pico pin 35) stays NC — referenced on the module (DR-3).
    rtop = add_res("R_ADC5_TOP", "10k")
    rbot = add_res("R_ADC5_BOT", "10k")
    cadc = add_cap("C_ADC5", "100nF")
    sense = Net("ADC_VCC5_SENSE")
    VCC5 += rtop[1]
    sense += rtop[2], rbot[1], cadc[1], pico[31]   # GP26/ADC0
    GND += rbot[2], cadc[2]

    # Item E, REDESIGNED per remediation spec R1 (2026-07-21, closes Codex
    # C1 + H1; supersedes the resistive 680k/100k-680k taps and their
    # temperature-qualified proof): per tap, a 2N7002 common-source inverter
    # (SOT-23 = the existing Qled_* footprint/BOM class):
    #
    #   observed_net -- R_TAPIN 1M --+-- gate(2N7002)     source -- GND
    #                                |
    #                          [R_TAPG 10M -> GND, 3.3 V taps only]
    #   VCC_3V3 -- R_TAPPU 10k --+-- drain -- Pico GPIO (input, Schmitt)
    #
    # Unidirectional BY CONSTRUCTION: the GPIO lands on the drain only;
    # drain->gate is open at DC and a MOS gate injects nothing into the
    # observed net (I_GSS <= 100 nA) — a stuck-high GPIO (C1's headline
    # scenario) does NOTHING to the observed net in unfaulted hardware.
    # Worst DOUBLE fault (D-G short + stuck-high GPIO + ARM driver high-Z +
    # 85 C junction): V_base = 3.3*100k/(1M+10k+100k) = 0.297 V ->
    # I_C <= 0.56 uA (COR-1 hot calibration, 71 mV/decade) -> 0.056 V across
    # R_RAIL_GATE_PULLUP 100k, >= 8x below the ~5 uA/0.5 V partial-hold
    # onset; absolute transistor-free ceiling 3.3 V/1.01 M = 3.3 uA < 5 uA.
    # DO NOT reduce R_TAPIN below 1M: the DERATED 85 C partial-hold onset is
    # ~3.6 uA (|V_GS(th)|min ~0.36 V / 100k), so 3.3 V/R <= 3.6 uA needs
    # R >= 917 k and 1M is the smallest standard value. (The earlier "~825k"
    # floor cleared only the 25 C onset and was RETRACTED - remediation spec
    # R1.4 corrected derivation / run-log RV-5 / Codex R2-2.) Do not
    # "tidy" the missing R_TAPG on the 555 tap (its push-pull output is
    # never high-Z; omitting the pulldown preserves 0.3 V of gate margin
    # against the 555's worst-case VOH). H1 closed: the 2N7002 gate is
    # +/-20 V abs-max — the NE555's unguaranteed light-load VOH (<= 5.25 V)
    # is tolerated by construction and the GPIO only sees the 3V3 drain.
    # READS ARE INVERTED (observed HIGH => pad LOW) — firmware v1.2 contract
    # (remediation spec R3.1); input-only is ENFORCED there (R3.2), now as
    # defense-in-depth. FMEA + at-temperature fault injection: spec R1.6/R1.9.
    # Full math + worst-corner read margins: remediation spec R1.4/R1.5.
    tap_specs = [
        # (suffix, observed_net, pico_pin/GP, has_gate_pulldown)
        ("555", ne555_out, 21, False),   # GP16; push-pull source, no R_TAPG
        ("KICK", KICK, 22, True),        # GP17
        ("ARM", ARM, 24, True),          # GP18
        ("RPOK", RP_OK, 25, True),       # GP19
    ]
    tap_net_names = {"555": "TAP_NE555_OUT", "KICK": "TAP_WDOG_KICK",
                     "ARM": "TAP_ARM_PERMIT", "RPOK": "TAP_RP2040_OK"}
    # R2-3 (Codex round-2, 2026-07-21): Q17-Q20 tap FETs are MPN-LOCKED to
    # onsemi 2N7002LT1G (LCSC C16338, verified in stock 2026-07-21) — the
    # 0.12-0.14 V cold-corner gate-drive margin in spec R1.5 depends on the
    # documented V_GS(th) 1.0-2.5 V @ 250 uA / tc ~-5 mV/C and V_GS abs-max
    # +/-20 V figures, which the previously-locked JSMSEMI C916396 datasheet
    # does not publish. The MPN rides the VALUE field so the netlist, board,
    # and fab BOM stay equality-asserted (export_fab_revD.py hard-locks the
    # JLC line). The Qled_* lamp drivers keep the generic 2N7002 value (no
    # margin-critical corner there). Run-log FR-10.
    for suffix, observed, pin, has_gpd in tap_specs:
        rin = add_res(f"R_TAPIN_{suffix}", "1M")
        rpu = add_res(f"R_TAPPU_{suffix}", "10k")
        q = Part("Transistor_FET", "Q_NMOS_GSD", value=f"2N7002LT1G TAP {suffix}",
                 footprint=FP_SOT23, tag=f"Q_TAP_{suffix}")
        parts[f"Q_TAP_{suffix}"] = q
        gate = Net(f"TAP_GATE_{suffix}")
        drain = Net(tap_net_names[suffix])

        observed += rin[1]
        gate += rin[2], q[1]          # G
        GND += q[2]                   # S
        drain += q[3], rpu[2], pico[pin]
        VCC3V3 += rpu[1]
        if has_gpd:
            rgpd = add_res(f"R_TAPG_{suffix}", "10M")
            gate += rgpd[1]
            GND += rgpd[2]


def block_j16_protection_and_revid(pico):
    """Rev-D round-2 remediation (Codex R2-4 board side + R2-6), 2026-07-21.

    APPENDED after block_diag() so every pre-existing refdes is unchanged
    (the R135/R138/R141 = 10M gate-pulldown pinning in export_fab_revD.py
    depends on this — appending mid-sequence would shift them).

    J16 protection stack (all LOGIC-domain; the TCA4307 buffer and the
    polyfuse are NOT isolation-barrier parts — every pin lands on LOGIC
    nets; the PC817/G5LE barrier inventory is untouched):
      * F_J16_5V  — Littelfuse 1206L020YR polyfuse (200 mA hold / 420 mA
        trip / 24 V @ 23 C), VCC_5V -> J16_5V -> J16 pin 1. Protects the
        module branch; PPTC trip current is time/temperature dependent, not
        a hard current clamp. The
        sanctioned steady module allowance is 45 mA (R3-7, re-derived from
        the 1206L020 temperature-derating table: I_hold falls to 90 mA @
        85 C worst-case enclosure temperature, and >=2x hold margin -> 45 mA;
        the old "100 mA << 200 mA hold" claim silently used the 23 C hold and
        evaporated hot). F1 part choice is UNCHANGED -- only the allowance
        number is corrected. This is the FR-3 "open option" now TAKEN
        (Codex R2-4). rev-D.1 upgrade path: swap the PPTC+ESD for a
        current-limiting eFuse with an open-drain FAULT flag to a spare
        RP2040 GPIO (TI TPS2660 / TPS25200 class) so a wedged module is a
        diagnosable event, not a silent trip -- needs copper, so NOT this spin.
      * JP_J16_3V3 — default-OPEN solder link, VCC_3V3 -> J16_3V3 ->
        J16 pin 5. The 3.3 V pin ships NOT CONNECTED; bridging is a
        deliberate, documented act for a verified 3.3 V module. Value
        carries DNP so the exporters exclude it from assembly.
      * U_I2C_BUF — TI TCA4307 (DGK/VSSOP-8, LCSC C880333) hot-swap I2C
        buffer with 40 ms stuck-bus detection + automatic SCL-pulse
        recovery between the MAIN bus (SDAIN/SCLIN, pins 6/3) and J16
        (SDAOUT/SCLOUT, pins 7/2). A wedged module is disconnected and
        recovery-pulsed; the Pi/MCP bus never sees it. EN (pin 1) tied to
        VCC_3V3 (datasheet: tie to VCC when unused); READY (pin 5) NC
        (open-drain status, unused — WVR-ERC-2). VCC (pin 8) = VCC_3V3
        (2.3-5.5 V range; bus levels are 3.3 V on both sides). Pinout
        verified against TI SCPS270B (2026-07-21). ICC <= 4.5 mA.
      * R_J16_SDA_PU / R_J16_SCL_PU — 4.7k card-side pull-ups to VCC_3V3
        (TCA4307 datasheet requires pull-ups on BOTH sides; main-bus side
        already has R_I2C_SDA/SCL 4.7k).
      * C_I2C_BUF — 100 nF bypass at U_I2C_BUF pin 8 (datasheet).
      * D_ESD_J16 — Semtech SRV05-4 (SOT-23-6, LCSC C13612) connector-side
        ESD/TVS array: VN (pin 2) = GND, VP (pin 5) = VCC_5V UPSTREAM of
        the polyfuse (round-3 fix — VP on the fused J16_5V node let a
        bridged-JP1 board defeat the fuse through IO1's upper steering
        diode on a J16 5V-to-GND short), steering IOs on J16_SDA (3),
        J16_SCL (6), J16_3V3 (1), and J16_5V (4) so the fused 5 V pin
        keeps its ESD clamp.

    REV_ID straps (Codex R2-6): 2-bit board-revision code on spare Pico
    GPIOs, read by firmware (v1.2.2 task) and reported in the identity
    line so the daemon can reject roles unsupported by the physical board.
      * GP20 (pin 26) = REV_ID0 — 10k strap to VCC_3V3 (reads 1)
      * GP21 (pin 27) = REV_ID1 — 10k strap to GND     (reads 0)
    ENCODING (REV_ID[1:0] = GP21<<1 | GP20):
      0b00 = reserved/legacy (no straps — a rev-C-class board would float;
             firmware must treat unreadable/floating as UNKNOWN, not rev-D)
      0b01 = rev-D  (THIS board)
      0b10 / 0b11 = future revisions
    Straps are 10k to rails with the GPIO input-only: zero static current.
    Pins 26/27 verified free in the pre-change netlist (2026-07-21).

    VCC_3V3 budget delta: buffer <= 4.5 mA + 2 x 4.7k pull-ups (~1.4 mA
    worst, only while a card-side line is held low) ~ +6 mA worst-case on
    the Pico 3V3 regulator; VCC_5V ripple-through is noise vs the spec
    (S)H.4 0.73-0.93 A worst case. Wetting rail untouched; D17 unchanged.
    """
    global VCC5, VCC3V3, GND, SDA, SCL, J16_5V, J16_3V3, J16_SDA, J16_SCL

    # --- current-limited 5 V (R2-4a) ---
    fuse = Part("Device", "Polyfuse", value="1206L020YR 200mA",
                footprint=FP_FUSE_1206, tag="F_J16_5V")
    parts["F_J16_5V"] = fuse
    VCC5 += fuse[1]
    J16_5V += fuse[2]

    # --- default-open 3.3 V solder link (R2-4b) ---
    jp = Part("Jumper", "SolderJumper_2_Open", value="3V3 LINK OPEN DNP",
              footprint=FP_SJ2_OPEN, tag="JP_J16_3V3")
    parts["JP_J16_3V3"] = jp
    VCC3V3 += jp[1]
    J16_3V3 += jp[2]

    # --- TCA4307 stuck-bus-recovery I2C buffer (R2-4c). No KiCad symbol
    #     exists for the TCA4307, so the part is constructed pin-by-pin from
    #     the TI SCPS270B pin table (DGK package, verified 2026-07-21):
    #     1 EN / 2 SCLOUT / 3 SCLIN / 4 GND / 5 READY / 6 SDAIN /
    #     7 SDAOUT / 8 VCC. ---
    buf = Part(tool=SKIDL, name="TCA4307", ref_prefix="U", value="TCA4307DGKR",
               footprint=FP_VSSOP8, tag="U_I2C_BUF")
    for num, pname, ptype in ((1, "EN", "INPUT"), (2, "SCLOUT", "BIDIR"),
                              (3, "SCLIN", "BIDIR"), (4, "GND", "PWRIN"),
                              (5, "READY", "OPENCOLL"), (6, "SDAIN", "BIDIR"),
                              (7, "SDAOUT", "BIDIR"), (8, "VCC", "PWRIN")):
        buf += Pin(num=str(num), name=pname, func=getattr(Pin.types, ptype))
    parts["U_I2C_BUF"] = buf
    VCC3V3 += buf[8], buf[1]     # VCC + EN tied high (datasheet)
    GND += buf[4]
    SCL += buf[3]                # SCLIN  <- main bus
    SDA += buf[6]                # SDAIN  <- main bus
    J16_SCL += buf[2]            # SCLOUT -> card side
    J16_SDA += buf[7]            # SDAOUT -> card side
    # READY (pin 5) deliberately NC — WVR-ERC-2 covers the ERC warning.

    r_sda_pu = add_res("R_J16_SDA_PU", "4.7k")
    r_scl_pu = add_res("R_J16_SCL_PU", "4.7k")
    VCC3V3 += r_sda_pu[1], r_scl_pu[1]
    J16_SDA += r_sda_pu[2]
    J16_SCL += r_scl_pu[2]

    cbuf = add_cap("C_I2C_BUF", "0.1uF")
    VCC3V3 += cbuf[1]
    GND += cbuf[2]

    # --- connector-side ESD array (R2-4d). KiCad Power_Protection:SRV05-4
    #     symbol pin map verified against the Semtech datasheet: IO1=1,
    #     VN=2, IO2=3, IO3=4, VP=5, IO4=6. IO channels are interchangeable.
    #
    #     ROUND-3 REWIRE (Codex 2026-07-21 PM, finding 2 — unfused rail sneak
    #     path): the round-2 wiring tied VP to the FUSED J16_5V node and IO1
    #     to J16_3V3. With the sanctioned JP1 3V3 link bridged, a J16 5V-to-
    #     GND short defeated the polyfuse: VCC_3V3 -> IO1 upper steering
    #     diode -> VP/J16_5V -> short, continuous current through a pulse-
    #     rated ESD diode (3V3 sag / Pico brownout; likely SRV05-4
    #     destruction; a fail-short part then ties VCC_3V3 to the dead
    #     J16_5V node permanently). Now: VP rides VCC_5V UPSTREAM of the
    #     polyfuse (a solid rail — steering diodes from any shorted IO pin
    #     are reverse-biased, clamp energy still lands on a decoupled rail)
    #     and the fused J16_5V pin gets the previously-spare IO3 channel so
    #     the connector's 5 V pin keeps ESD protection. Under the same
    #     fault: IO3 lower diode to VN reverse-biased, IO3 upper diode
    #     (0 V -> 5 V VP) reverse-biased — NO sneak path, fuse does its job. ---
    esd = Part("Power_Protection", "SRV05-4", value="SRV05-4",
               footprint=FP_SOT23_6, tag="D_ESD_J16")
    parts["D_ESD_J16"] = esd
    J16_3V3 += esd[1]            # IO1
    GND += esd[2]                # VN
    J16_SDA += esd[3]            # IO2
    J16_5V += esd[4]             # IO3 — fused 5V pin as an IO channel (round-3)
    VCC5 += esd[5]               # VP — UPSTREAM of the polyfuse (round-3)
    J16_SCL += esd[6]            # IO4

    # --- REV_ID straps (R2-6) ---
    r_id0 = add_res("R_REVID0", "10k")
    r_id1 = add_res("R_REVID1", "10k")
    rev0 = Net("REV_ID0")
    rev1 = Net("REV_ID1")
    VCC3V3 += r_id0[1]           # rev-D: REV_ID0 = 1
    rev0 += r_id0[2], pico[26]   # GP20
    GND += r_id1[1]              # rev-D: REV_ID1 = 0
    rev1 += r_id1[2], pico[27]   # GP21


# ---- ERC waiver gate (fail-closed; see docstring + docs/phase8_revD_run_log.md
#      WVR-ERC-1). Update these constants ONLY together with a new run-log
#      waiver entry — that is the point of the gate.
ERC_EXPECTED_ERRORS = 1
# WVR-ERC-1 (round-3 update, 2026-07-21): the waiver now matches the pin PAIR
# order-insensitively — the round-3 SRV05-4 rewire (U47.4 GND -> J16_5V)
# changed the GND net's pin ordering and SKiDL flipped which side of the
# A1 GND/AGND conflict prints first. Same single waived error, all three
# substrings must appear in the one ERC ERROR line.
ERC_WAIVED_ERROR_SUBSTRS = ("Pin conflict on net GND",
                            "pin 33/AGND of RaspberryPi_Pico/A1",
                            "pin 3/GND of RaspberryPi_Pico/A1")
# WVR-ERC-2 (2026-07-21, round-2 remediation): baseline 40 -> 39.
# Delta fully accounted: -2 (Pico pins 26/27 = GP20/GP21 were
# unconnected-spare warnings, now the REV_ID straps) and +1 (TCA4307
# READY pin 5 deliberately NC). The waived ERROR is unchanged.
ERC_EXPECTED_WARNINGS = 39


def check_erc_waiver():
    """Assert the ERC result matches the waived baseline EXACTLY.

    The rev-C generator never ran ERC (its .erc is 0 bytes), so rev-D defines
    the baseline: 1 error (Pico AGND/GND POWER-OUT pin-type artifact —
    module-internal grounds that MUST be tied; benign) + 40 warnings. A
    silently tolerated mismatch would let the NEXT spin's real single ERC
    error hide behind "the known AGND thing" — so this fails closed instead.
    """
    from skidl.logger import erc_logger

    n_err = erc_logger.error.count
    n_warn = erc_logger.warning.count
    problems = []
    if n_err != ERC_EXPECTED_ERRORS:
        problems.append(f"ERC error count {n_err} != waived baseline {ERC_EXPECTED_ERRORS}")
    if n_warn != ERC_EXPECTED_WARNINGS:
        problems.append(f"ERC warning count {n_warn} != waived baseline {ERC_EXPECTED_WARNINGS}")

    # Confirm the single error is EXACTLY the waived one via the one canonical
    # repository-root artifact. The SKiDL import above owns this exact path.
    if not ERC_ARTIFACT.is_file():
        problems.append(f"cannot locate the emitted .erc file at {ERC_ARTIFACT}")
    else:
        err_lines = [ln for ln in ERC_ARTIFACT.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
                     if ln.startswith("ERC ERROR")]
        if (len(err_lines) != ERC_EXPECTED_ERRORS
                or not all(all(s in ln for s in ERC_WAIVED_ERROR_SUBSTRS) for ln in err_lines)):
            problems.append(f"ERC error line(s) do not match waiver WVR-ERC-1: {err_lines}")

    if problems:
        print("\nERC WAIVER GATE FAILED (WVR-ERC-1 baseline drift — investigate before proceeding):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(2)
    print(f"ERC waiver gate PASS: {n_err} error (waived WVR-ERC-1) + {n_warn} baseline warnings, nothing else.")


def main():
    fast_logic = {name: Net(f"FAST_{name}") for name, _ in FAST_INPUTS}
    fast_field = {name: Net(f"FIELD_FAST_{name}") for name, _ in FAST_INPUTS}
    slow_logic = {name: Net(f"SLOW_{name}") for name in SLOW_INPUT_PINS}
    slow_field = {name: Net(f"FIELD_SLOW_{name}") for name in SLOW_INPUT_PINS}
    drive = {name: Net(f"DRV_{name}") for name in OUTPUT_PINS}
    motion_pairs = {name: (Net(f"OUT_{name}_A"), Net(f"OUT_{name}_B")) for name in ["S", "T", "SP", "BE", "M", "M2", "M1"]}
    lamp_returns = {name: Net(f"LED_{name}_RETURN") for name in ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]}

    pico = block_rp2040(fast_logic)
    mcps = {
        # Address straps in (A0, A1, A2) order -> I2C addr 0x20 | (A2<<2|A1<<1|A0):
        "MCP_IN_A": block_mcp("MCP_IN_A", (0, 0, 0), INT_A),    # A0=0 A1=0 A2=0 -> 0x20
        "MCP_IN_B": block_mcp("MCP_IN_B", (1, 0, 0), INT_B),    # A0=1 A1=0 A2=0 -> 0x21
        "MCP_OUT_A": block_mcp("MCP_OUT_A", (0, 1, 0), None),   # A0=0 A1=1 A2=0 -> 0x22
        # (A next OUT_B spin would be (1, 1, 0) -> 0x23 — A0 and A1 high, NOT A2.)
        # Rev-D item G decision: OUT_B stays DEFERRED — zero diagnostics yield,
        # and an MCP23017 breakout on J16 at 0x23 delivers the same capacity
        # off-board (spec §G). Do not place without a documented override.
    }
    block_i2c_pullups()

    for name, _ in FAST_INPUTS:
        opto_input(name, fast_logic[name], fast_field[name])

    for name, (mcp_name, pin) in SLOW_INPUT_PINS.items():
        opto_input(name, slow_logic[name], slow_field[name])
        slow_logic[name] += mcps[mcp_name][pin]

    for name, pin in OUTPUT_PINS.items():
        drive[name] += mcps["MCP_OUT_A"][pin]

    for name in ["S", "T", "SP", "BE", "M", "M2"]:
        relay_output(name, drive[name], *motion_pairs[name])
    relay_output("M1", drive["M1"], *motion_pairs["M1"], dnp=True)

    for name in ["L_FIRST", "L_SECOND", "L_STRIKE", "L_FOUL"]:
        lamp_led_output(name, drive[name], lamp_returns[name])

    wdog_pull, ne555_out = block_watchdog()
    connectors = block_connectors(fast_field, slow_field, motion_pairs, lamp_returns)
    block_supplies()
    block_rail(wdog_pull, connectors["J_SAFE"])
    block_diag(pico, ne555_out)
    block_j16_protection_and_revid(pico)
    # r6 (2026-07-25) MUST be last: refdes stability depends on it (spec §E.3).
    block_input_protection()

    # Rev-D output is a NEW file — never the rev-C kicad/wsl-phase8b.net.
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kicad", "wsl-phase8b-revD.net"))
    ERC()
    check_erc_waiver()
    generate_netlist(file_=out)
    canonicalize_generated_artifacts(out)
    print(f"\nWROTE {out}")
    print(f"part registry count: {len(parts)}")


def canonicalize_generated_artifacts(netlist_path):
    """Remove SKiDL runtime volatility from the checked-in Rev-D artifacts.

    SKiDL emits the wall-clock generation time and source line numbers in the
    legacy KiCad netlist, and iterates ERC diagnostics in hash-dependent order.
    None changes the electrical design, but all previously changed
    source/package hashes on a no-op regeneration. Keep the established R5
    design timestamp, normalize diagnostic-only source-line fields, and sort
    ERC rows so two clean generator runs are byte-identical.
    """
    import re

    netlist = pathlib.Path(netlist_path)
    netlist_bytes = netlist.read_bytes()
    netlist_bytes, replacements = re.subn(
        rb'\(date "[^"]+"\)',
        b'(date "07/23/2026 01:36 PM")',
        netlist_bytes,
        count=1,
    )
    if replacements != 1:
        raise RuntimeError("generated Rev-D netlist has no unique design date")

    netlist_bytes, source_replacements = re.subn(
        rb'\(source "[^"]*generate_kicad_netlist_revD\.py"\)',
        b'(source "scripts/generate_kicad_netlist_revD.py")',
        netlist_bytes,
    )
    if source_replacements != 2:
        raise RuntimeError(
            "generated Rev-D netlist source field count drifted: "
            f"{source_replacements} != 2"
        )

    netlist_bytes, line_replacements = re.subn(
        rb'(\(name "SKiDL Line"\) "generate_kicad_netlist_revD\.py:)\d+(")',
        rb"\g<1>0\g<2>",
        netlist_bytes,
    )
    if line_replacements != len(parts):
        raise RuntimeError(
            "generated Rev-D netlist source-line field count drifted: "
            f"{line_replacements} != {len(parts)}"
        )
    netlist.write_bytes(netlist_bytes)

    if not ERC_ARTIFACT.is_file():
        raise RuntimeError(
            f"cannot canonicalize canonical ERC artifact {ERC_ARTIFACT}"
        )

    def _canonical_erc_line(line):
        # SKiDL also orders the two operands INSIDE a pin-conflict
        # diagnostic hash-dependently ("pin 3 <==> pin 33" vs
        # "pin 33 <==> pin 3"); sorting whole lines cannot see that, so
        # across environments the ERC artifact hash drifted while the
        # netlist stayed byte-identical (round-4 audit). Order the two
        # operands lexically — same waived electrical fact, one spelling.
        match = re.fullmatch(
            rb"(?P<head>ERC (?:ERROR|WARNING): .*?[,:] )"
            rb"(?P<a>\S.*?) <==> (?P<b>\S.*?)"
            rb"(?P<tail> \([^()]*\))?",
            line,
        )
        if not match:
            return line
        first, second = sorted([match.group("a"), match.group("b")])
        return (match.group("head") + first + b" <==> " + second
                + (match.group("tail") or b""))

    erc_lines = [
        _canonical_erc_line(line)
        for line in ERC_ARTIFACT.read_bytes().splitlines()
    ]
    erc_lines.sort(
        key=lambda line: (
            0 if line.startswith(b"ERC ERROR") else
            1 if line.startswith(b"ERC WARNING") else
            2,
            line,
        )
    )
    ERC_ARTIFACT.write_bytes(b"\r\n".join(erc_lines) + b"\r\n")


if __name__ == "__main__":
    main()
