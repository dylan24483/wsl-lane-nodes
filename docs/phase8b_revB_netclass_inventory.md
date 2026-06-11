# Phase 8 Rev-B Net-Class Inventory

**Status:** Policy-neutral prep audit after the SKiDL net-rename pass. Based on `kicad/wsl-phase8b.kicad_pcb` regenerated from `kicad/wsl-phase8b.net`: 206 netlist components, 16 test pads, 4 mounting holes, 184 named nets, **0 anonymous `N$` nets**, 0 KiCad DRC violations before routing.

This document does **not** assign final trace widths, clearances, creepage distances, copper pours, or routing rules. It groups the current nets into electrical domains so KiCad net classes can be applied without guessing.

## Summary

| Domain candidate | Net count | Notes |
|---|---:|---|
| `LOGIC_3V3_CONTROL` | 52 | Pico/MCP GPIO, I2C, UART, interrupts, logic-side opto outputs, MCP driver commands. |
| `LOGIC_GND` | 1 | Logic ground only. Must remain distinct from `FIELD_GND`. |
| `LOGIC_5V_WATCHDOG_RELAY_COIL` | 14 | 5V rail, NE555/watchdog, rail enable, relay coil supply/control nodes. |
| `RELAY_COIL_LOW_INTERNAL` | 7 | `COIL_LO_*`: low-side transistor/flyback/relay-coil internal nodes. |
| `LOGIC_RELAY_BASE_INTERNAL` | 7 | `BASE_S/T/SP/BE/M/M2/M1`: MCP output after base resistor into relay-driver transistor base. |
| `LOGIC_LAMP_INPUT_INTERNAL` | 4 | `PHOTOMOS_LED_*`: PhotoMOS input LED/resistor internal nodes. |
| `SAFETY_AND_CHAIN_INTERNAL` | 2 | `BASE_AND_*`: internal pass-FET/AND-chain base nodes for safety rail gating. |
| `FIELD_WETTING_EXTERNAL` | 34 | Isolated wetting supply and all field input connector returns. |
| `FIELD_INPUT_LED_SERIES` | 32 | `FIELD_LED_*`: opto LED series nets; field side, not logic. |
| `SAFETY_LOOP_EXTERNAL` | 2 | External safety/interlock loop nets on J_SAFE. Treat separately from generic logic. |
| `MACHINE_RELAY_CONTACT_EXTERNAL` | 14 | Relay dry-contact output nets to J_MOTION. Includes optional M1 pair. |
| `MACHINE_OUTPUT_SNUBBER_MIDPOINT` | 7 | `SNUB_*`: RC snubber midpoint nets across relay contacts; machine-output side. |
| `LAMP_PHOTOMOS_OUTPUT_EXTERNAL` | 8 | PhotoMOS isolated output nets to J_LAMP. |

Unknown/unclassified nets: **0**.

## Policy Slots Claude Should Fill

| Policy class | Nets/domains to include | Open decision |
|---|---|---|
| Logic low-voltage | `LOGIC_3V3_CONTROL`, `LOGIC_GND`, `LOGIC_RELAY_BASE_INTERNAL`, `LOGIC_LAMP_INPUT_INTERNAL` | Width/clearance for 3.3V signals, I2C, UART, MCP GPIO, PhotoMOS input LEDs, and relay-driver bases. |
| 5V power/watchdog | `LOGIC_5V_WATCHDOG_RELAY_COIL` | Width for 5V rail/watchdog; whether relay enable rail gets larger width. |
| Safety/relay coil integrity | `RELAY_COIL_LOW_INTERNAL`, `SAFETY_AND_CHAIN_INTERNAL`, `RELAY_ENABLE_RAIL` | Whether flyback/coil low-side and safety-chain base nodes use Safety_Rail or Logic_Power. |
| Isolated field wetting | `FIELD_WETTING_EXTERNAL`, `FIELD_INPUT_LED_SERIES` | Clearance to logic ground/3.3V/5V across the optocoupler and U41 isolation boundary. |
| Safety loop external | `SAFETY_LOOP_EXTERNAL`, especially `SAFE_STOP_RETURN` | Whether safety-loop nets use field-domain clearance or their own stricter class. |
| Machine relay contacts | `MACHINE_RELAY_CONTACT_EXTERNAL`, `MACHINE_OUTPUT_SNUBBER_MIDPOINT` | Contact-to-logic and contact-to-contact creepage/clearance for measured machine voltage/current. |
| Lamp isolated outputs | `LAMP_PHOTOMOS_OUTPUT_EXTERNAL` | Same as machine output class or a separate lamp-output class after voltage/current confirmation. |

## Full Domain Inventory

### `LOGIC_3V3_CONTROL`

`ARM_PERMIT`, `DRV_BE`, `DRV_L_FIRST`, `DRV_L_FOUL`, `DRV_L_SECOND`, `DRV_L_STRIKE`, `DRV_M`, `DRV_M1`, `DRV_M2`, `DRV_S`, `DRV_SP`, `DRV_T`, `FAST_DIELL_L`, `FAST_DIELL_R`, `FAST_SA`, `FAST_SB`, `FAST_SC`, `FAST_TA1`, `FAST_TA2`, `FAST_TB`, `I2C_SCL`, `I2C_SDA`, `MCP_INT_A`, `MCP_INT_B`, `PI_UART_RX`, `PI_UART_TX`, `RP2040_OK`, `SLOW_AUX1`, `SLOW_AUX2`, `SLOW_AUX3`, `SLOW_BS`, `SLOW_FOUL`, `SLOW_GP`, `SLOW_GS1`, `SLOW_GS10`, `SLOW_GS2`, `SLOW_GS3`, `SLOW_GS4`, `SLOW_GS5`, `SLOW_GS6`, `SLOW_GS7`, `SLOW_GS8`, `SLOW_GS9`, `SLOW_MAN_S`, `SLOW_MAN_SWS`, `SLOW_MAN_SWSR`, `SLOW_MAN_T`, `SLOW_OS`, `SLOW_PBC`, `SLOW_PBZ`, `SLOW_TENTH`, `VCC_3V3`.

### `LOGIC_5V_WATCHDOG_RELAY_COIL`

`AND_MID_ARM_RP`, `NE555_CTRL`, `NE555_OUT`, `NE555_TRIG`, `RAIL_GATE`, `RELAY_ENABLE_RAIL`, `VCC_5V`, `VCC_5V_RAW`, `WDOG_KICK`, `WDOG_KICK_DRAIN`, `WDOG_KICK_GATE`, `WDOG_OK_GATE`, `WDOG_OK_PULLDOWN`, `WDOG_TIMING_NODE`.

### `FIELD_WETTING_EXTERNAL`

`FIELD_FAST_DIELL_L`, `FIELD_FAST_DIELL_R`, `FIELD_FAST_SA`, `FIELD_FAST_SB`, `FIELD_FAST_SC`, `FIELD_FAST_TA1`, `FIELD_FAST_TA2`, `FIELD_FAST_TB`, `FIELD_GND`, `FIELD_SLOW_AUX1`, `FIELD_SLOW_AUX2`, `FIELD_SLOW_AUX3`, `FIELD_SLOW_BS`, `FIELD_SLOW_FOUL`, `FIELD_SLOW_GP`, `FIELD_SLOW_GS1`, `FIELD_SLOW_GS10`, `FIELD_SLOW_GS2`, `FIELD_SLOW_GS3`, `FIELD_SLOW_GS4`, `FIELD_SLOW_GS5`, `FIELD_SLOW_GS6`, `FIELD_SLOW_GS7`, `FIELD_SLOW_GS8`, `FIELD_SLOW_GS9`, `FIELD_SLOW_MAN_S`, `FIELD_SLOW_MAN_SWS`, `FIELD_SLOW_MAN_SWSR`, `FIELD_SLOW_MAN_T`, `FIELD_SLOW_OS`, `FIELD_SLOW_PBC`, `FIELD_SLOW_PBZ`, `FIELD_SLOW_TENTH`, `FIELD_WET_V`.

### `FIELD_INPUT_LED_SERIES`

`FIELD_LED_AUX1`, `FIELD_LED_AUX2`, `FIELD_LED_AUX3`, `FIELD_LED_BS`, `FIELD_LED_DIELL_L`, `FIELD_LED_DIELL_R`, `FIELD_LED_FOUL`, `FIELD_LED_GP`, `FIELD_LED_GS1`, `FIELD_LED_GS10`, `FIELD_LED_GS2`, `FIELD_LED_GS3`, `FIELD_LED_GS4`, `FIELD_LED_GS5`, `FIELD_LED_GS6`, `FIELD_LED_GS7`, `FIELD_LED_GS8`, `FIELD_LED_GS9`, `FIELD_LED_MAN_S`, `FIELD_LED_MAN_SWS`, `FIELD_LED_MAN_SWSR`, `FIELD_LED_MAN_T`, `FIELD_LED_OS`, `FIELD_LED_PBC`, `FIELD_LED_PBZ`, `FIELD_LED_SA`, `FIELD_LED_SB`, `FIELD_LED_SC`, `FIELD_LED_TA1`, `FIELD_LED_TA2`, `FIELD_LED_TB`, `FIELD_LED_TENTH`.

These are field-side nets between field input resistors and PC817 LED anodes. They replaced historical anonymous nets `N$1`-`N$32`.

### `MACHINE_RELAY_CONTACT_EXTERNAL`

`OUT_S_A`, `OUT_S_B`, `OUT_T_A`, `OUT_T_B`, `OUT_SP_A`, `OUT_SP_B`, `OUT_BE_A`, `OUT_BE_B`, `OUT_M_A`, `OUT_M_B`, `OUT_M2_A`, `OUT_M2_B`, `OUT_M1_A`, `OUT_M1_B`.

### `MACHINE_OUTPUT_SNUBBER_MIDPOINT`

`SNUB_S`, `SNUB_T`, `SNUB_SP`, `SNUB_BE`, `SNUB_M`, `SNUB_M2`, `SNUB_M1`.

These are RC snubber midpoint nets for S/T/SP/BE/M/M2/M1 relay contacts. M1 remains DNP optional. They replaced historical anonymous nets `N$35`, `N$38`, `N$41`, `N$44`, `N$47`, `N$50`, `N$53`.

### `LAMP_PHOTOMOS_OUTPUT_EXTERNAL`

`OUT_L_FIRST_A`, `OUT_L_FIRST_B`, `OUT_L_SECOND_A`, `OUT_L_SECOND_B`, `OUT_L_STRIKE_A`, `OUT_L_STRIKE_B`, `OUT_L_FOUL_A`, `OUT_L_FOUL_B`.

### Internal Low-Voltage Named Nets

- `LOGIC_RELAY_BASE_INTERNAL`: `BASE_S`, `BASE_T`, `BASE_SP`, `BASE_BE`, `BASE_M`, `BASE_M2`, `BASE_M1`.
- `RELAY_COIL_LOW_INTERNAL`: `COIL_LO_S`, `COIL_LO_T`, `COIL_LO_SP`, `COIL_LO_BE`, `COIL_LO_M`, `COIL_LO_M2`, `COIL_LO_M1`.
- `LOGIC_LAMP_INPUT_INTERNAL`: `PHOTOMOS_LED_L_FIRST`, `PHOTOMOS_LED_L_SECOND`, `PHOTOMOS_LED_L_STRIKE`, `PHOTOMOS_LED_L_FOUL`.
- `SAFETY_AND_CHAIN_INTERNAL`: `BASE_AND_ARM`, `BASE_AND_RP_OK`.

### Safety Loop Nets

`SAFE_STOP_RETURN`, `SAFE_TBSC_RETURN`.

`SAFE_STOP_RETURN` touches the J_SAFE connector, TP15, R102, and Q10 safety-rail gating. Do not collapse it into generic logic without an explicit policy decision.

## Boundary Checklist

- Optocoupler boundary: `FIELD_*` and `FIELD_LED_*` must stay on the field/wetting side of PC817 devices; `FAST_*`/`SLOW_*` nets are logic-side.
- Isolated converter boundary: `FIELD_WET_V`/`FIELD_GND` are isolated output-side nets of U41; `VCC_5V`/`GND` are logic-side.
- Relay boundary: `RELAY_ENABLE_RAIL`, `COIL_LO_*`, and `BASE_*` relay-driver nets are logic/5V side; `OUT_*` contact nets and `SNUB_*` midpoints are machine-output side.
- PhotoMOS boundary: `DRV_L_*` and `PHOTOMOS_LED_*` are logic input side; `OUT_L_*` nets are isolated lamp-output side.
- Safety boundary: J_SAFE nets are external safety-loop nets even though `SAFE_STOP_RETURN` participates in the internal relay-enable gating.
