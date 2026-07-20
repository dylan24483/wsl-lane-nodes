# Phase 8 — Diagnostics Sensor Order List (2026-07-19)

Pilot scope: pair 21/22 (one Pi, machine 22 = active pilot). Quantities below cover the pair + spares.
Companion docs: `phase8_diagnostics_target_conditions_2026-07-19.md` §3 (what each sensor detects), `phase8_diagnostics_scope_2026-07-19.md` §4.

## Path 1 — dry-contact sensors → AUX inputs (J5 pins 9-11)

| # | Item | Example parts (either works) | Qty | Est. |
|---|---|---|---|---|
| 1 | **BE-motor current switch** — split-core, self-powered (induction), **adjustable** setpoint, N.O. solid-state dry contact | Veris Hawkeye **H908** (adjustable, split-core) or NK Technologies **AS1-NOAC-FT**. Avoid fixed-trip models (H300 class) — trip must be set from a live clamp-meter reading | 2 (one per machine; install 22 first) | ~$90-150 ea |
| 2 | **Ball-return exit photoeye** — retroreflective, **NPN** N.O., 10-30 VDC, M18 barrel + reflector | Omron **E3F2-R2C4** class, or generic **E3F-R2NK** + 84 mm reflector. ONE per pair (shared lift) — order 2 for a spare | 2 + 2 reflectors | ~$15-40 ea |
| 3 | **Distributor index sensor** — the cam gear is NYLON, so either (a) diffuse photoeye M18 NPN (**E3F-DS30C4** class) reading a bolted bright/reflective flag, or (b) inductive **LJ18A3-8-Z/BX** + a bolted steel flag | Pick (a) if unsure — no flag-material constraint | 2 + spare | ~$10-25 ea |
| 4 | **Isolated 24 VDC sensor supply** — DIN rail, powers photoeye + prox (current switch is self-powered) | Mean Well **HDR-15-24** (0.63 A — plenty) | 1 (+1 spare optional) | ~$15 |

Wiring rule (from the catalog): sensor outputs are dry/NPN into the AUX optos (board's FIELD_WET_V wets the loop at ~1-2 mA). The 24 VDC brick's 0 V ties to the field-side common. **Never** power sensors from FIELD_WET_V or the Pi.

## Path 2 — analog → isolated USB ADC on the Pi

| # | Item | Example parts | Qty | Est. |
|---|---|---|---|---|
| 5 | **USB DAQ** | LabJack **U3-LV** (~$115, 12-bit, 16 flexible I/O — enough for 4 CTs + 2 voltage + digital) or **T4** (~$265) if you want the newer line | 1 per pair | ~$115 |
| 6 | **Split-core CTs, voltage-output** — 20 A range is a safe default for fractional-HP 115 V motors (verify FLA with clamp meter at the powered session) | YHDC **SCT-013-020** (20 A / 1 V out — plugs straight into a DAQ analog input, no burden resistor) | 4 (BE, S, T + spare) | ~$12 ea |
| 7 | **24 VAC control-rail sense** — isolated voltage-transformer module, analog out | **ZMPT101B** module | 2 | ~$5-8 ea |
| 8 | **Temperature probes** — waterproof DS18B20 + USB 1-wire master | 5× DS18B20 probe (3 m leads) + **DS9490R** USB adapter (or a generic USB 1-wire master) | 5 + 1 | ~$25 total |

## Sundries

- 1 kΩ and 2.2 kΩ ½ W resistors (FIELD_WET_V bleed — interim external fit at a field connector)
- ~50-100 ft shielded twisted pair 22 AWG (CT secondaries + sensor runs), ferrules, DIN rail + terminal blocks, M18 mounting brackets, inline 1 A fuse for the 24 VDC brick

**Pilot-pair total: roughly $450-650.**

## Do-not-order-yet / notes

- **Do not set the current-switch trip point until the powered session** — BE nameplate FLA is not in the manuals; size it from a live clamp-meter reading.
- S/T current rides the DAQ CTs (item 6) — no extra dry-contact switches needed until rev-D GPB channels exist.
- Deferred (per catalog §3): vibration accelerometer, carpet-shaft pickup, USB mic. Skip list: shaft encoders, per-bin switches, Klixon direct taps.
