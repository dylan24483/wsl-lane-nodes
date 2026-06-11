# WSL Phase 8 System Manual Audit

Date: 2026-06-04

Manual audited:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.docx`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md` used for precise line references. The same candidate issue text was confirmed present in the DOCX.

## Verdict

The manual is broadly consistent with the project artifacts and captures the major hardware, firmware, Pi-side, routing, fab, and bring-up state. I would not treat it as ready-for-final without the corrections below, because two items could directly mislead safety/bring-up or assembly expectations.

Severity key:

- P1: safety, bring-up, or assembly expectation issue.
- P2: factual mismatch or wording that can cause confusion, but not likely to invalidate the board/order.

## Findings

### P1 - RP2040 cam-stop enforcement is overstated in several sections

The manual repeatedly says the current RP2040 firmware enforces cam-stops in hardware. That is not true for firmware v0.1.0 as currently checked in. The firmware implements health/status, UART event reporting, ARM control, and the 8 s motion max-run backstop. Per-cam-edge cam-stop overrun enforcement is explicitly deferred to v1.1 after live cam polarity/timing capture.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:405`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:1223`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:1228`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:3565-3566`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:3871`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:4782`

Source-of-truth evidence:

- `firmware/rp2040/main.c:34-39` says cam-stop overrun enforcement is deferred to v1.1 and is not implemented in this firmware.
- `firmware/rp2040/README.md:18-19` and `firmware/rp2040/README.md:135-136` say v1 provides health plus max-run backstop, not per-cam-edge enforcement.
- The manual itself says the correct deferred status later, including around `docs/WSL_PHASE8_SYSTEM_MANUAL.md:5271`, `docs/WSL_PHASE8_SYSTEM_MANUAL.md:6824`, `docs/WSL_PHASE8_SYSTEM_MANUAL.md:7780`, and `docs/WSL_PHASE8_SYSTEM_MANUAL.md:8843-8844`.

Recommended correction:

Replace unqualified "cam-stop enforcement" language with:

> RP2040 fast cam/ball event capture, RP2040_OK health gating, ARM relay control, and an 8 s motion max-run backstop. Per-cam-edge cam-stop overrun enforcement is deferred to firmware v1.1 pending live cam polarity/timing capture.

### P1 - U37 assembly-house population is contradicted

One bring-up/cutover section says the assembly house populates U37. That conflicts with the actual JLC order split and with other manual sections.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:7755` says the assembly house populates the TMA-0505S isolated field supply U37.

Source-of-truth evidence:

- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-hand-solder-bom.csv` lists U37 as hand-soldered: TRACO Power `TMA 0505S`.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:1802` correctly says U37 is hand-soldered/consigned and not in the JLC standard PCBA upload.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:1806` correctly says the JLC-assembled board arrives without A1 and without U37.

Recommended correction:

Remove U37 from the assembly-house populated list. State that JLC board arrival excludes A1, U37, and hand-solder connectors; U37 must be installed before isolated field-wetting/input tests.

### P2 - JLC placed BOM count is wrong in one late section

The manual has one late summary saying the JLC-placed line count is 21. The actual JLC BOM has 20 rows, and the manual correctly says 20 elsewhere.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:8693` says "JLC-placed line count: 21 sourcing lines."

Source-of-truth evidence:

- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv` contains 20 component rows.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:7517` correctly says "JLC BOM unique lines: 20."

Recommended correction:

Change 21 to 20.

### P2 - Hand-solder connector wording incorrectly says all Phoenix connectors J1-J14

The manual says all Phoenix connectors J1-J14 are hand-soldered. That is imprecise:

- J1 is an IDC/header candidate, not Phoenix.
- J12 is DNP and should not be installed.
- The actual hand-solder connector set is J1-J11, J13, and J14.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:8664`

Source-of-truth evidence:

- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-hand-solder-bom.csv` lists A1, J1-J11, J13, J14, and U37.
- `kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-dnp-excluded.csv` lists J12 as DNP.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:8714` correctly notes J12 is absent and only J6-J11 are populated machine-output terminals.

Recommended correction:

Use:

> Hand-solder A1, J1, J2-J11, J13, J14, and U37. J12/M1 remains DNP. J1 is the IDC/header candidate; the Phoenix terminal blocks are J2-J11, J13, and J14.

### P2 - 5 V logic wording can confuse the 3.3 V I2C design rule

One high-level architecture line says external regulated 5 V powers "all logic, MCP23017s..." This is electrically misleading. The board receives 5 V, but the MCP23017s and I2C rail are on Pico-derived 3.3 V.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:391`

Source-of-truth evidence:

- `scripts/generate_kicad_netlist_revB.py:176` has Pico pin 36 feeding `VCC_3V3`.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:1275-1277` correctly says the Pico supplies 3.3 V and the MCP23017s run at 3.3 V.

Recommended correction:

Use:

> External regulated 5 V feeds board input power, Pico VSYS, relay coils, and the NE555/watchdog rail. Pico-derived 3.3 V powers the MCP23017s, I2C pull-ups, and opto logic-side pull-ups.

### P2 - MCP23017 address range wording implies four populated expanders

Several summary passages describe "three MCP23017s at 0x20-0x23" or say each board repeats 0x20-0x23. The populated Rev-B board has three MCP23017s at 0x20, 0x21, and 0x22. Address 0x23 is reserved for optional OUT-B/pin lamps and is not populated.

Manual text to correct:

- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:431`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:436`
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:3863`

Source-of-truth evidence:

- `lane_node/controller_io.py:44-47` defines 0x20, 0x21, 0x22, and optional 0x23.
- `scripts/generate_kicad_netlist_revB.py:518-520` instantiates only `MCP_IN_A`, `MCP_IN_B`, and `MCP_OUT_A`.

Recommended correction:

Use:

> Three populated MCP23017s at 0x20, 0x21, and 0x22; 0x23 is reserved for optional OUT-B/pin-lamp expansion and is not populated on Rev-B.

## Verified Good

The following high-risk claims were checked against source artifacts and passed:

- Board audit passes on the routed board: `AUDIT RESULT: ALL PASS`.
- Latest fab reports show 0 DRC violations, 0 unconnected pads, and 0 footprint errors.
- Netclass counts match the manual's routing/audit state: Logic_Signal 80, Safety_Rail 13, Field_Sense 66, Logic_Power 4, Machine_Output 21.
- `GND` and `FIELD_GND` remain distinct.
- No `OUT_*` net touches the Pico.
- DNP count is 27 and includes the M1/J12/K7 channel exclusions.
- JLC critical parts match the locked PCBA split:
  - K1-K6: C116963 / Omron G5LE-14 5VDC.
  - U1-U3: C47023 / MCP23017-E/SO.
  - U4-U35: C5692981 / PC817B.
  - U36: C7593 / NE555DR.
- Hand-solder split matches the board/order artifacts: A1, J1-J11, J13, J14, and U37.

## Commands Run

From `C:\Users\Dylan DeYoung\wsl-lane-nodes`:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb
python lane_node\cycle_control_8270.py
python lane_node\controller_io.py
python lane_node\rp2040_link.py
python lane_node\controller_daemon.py --selftest
```

Results:

- Board audit: ALL PASS.
- FSM selftest: ALL ASSERTS PASSED.
- `controller_io.py`: RecordingIO strike-cycle and PCB pin-map checks OK.
- `rp2040_link.py`: 29/29 checks passed.
- `controller_daemon.py --selftest`: 22/22 checks passed.

