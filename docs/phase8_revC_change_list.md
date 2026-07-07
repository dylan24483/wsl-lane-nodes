# Phase 8 Rev-B Lane-Controller — Rev-C Change List

> Consolidated 2026-06-25 during rev-B board #1 bench bring-up. Items 1–5 are layout
> changes; 6–9 are verify-before-commit; 10–11 are process. Source of truth for the
> next PCB spin.

## CRITICAL (assembly/function-blocking)

### 1. Relay footprint — coil/contact pad-number mismatch ⛔ (found 2026-06-25, all 6 relays)
- **Symptom:** none of the 6 relays energize. Bench-confirmed: rev-B drives pad 1
  (`RELAY_ENABLE_RAIL`) and pad 2 (MMBT3904 collector), but the placed **Omron G5LE-14
  5 V coil measures ~65 Ω across pads 2 and 5**. Pad 1 is COM, pad 3 is NO, and pad 4 is
  NC/unused. The J11 pin-1-to-COM check was closed at rest, proving the J11 pin-1 net /
  relay pad 4 is NC rather than NO. Because rev-B leaves pad 5 unconnected and puts the
  rail on COM, the coil never sees voltage.
- **Root cause:** `scripts/generate_kicad_netlist_revB.py` `relay_output()` used the G5LE
  symbol as if pins 1/2 were the coil and pins 3/4 were COM/NO. The footprint is mechanically
  right for the placed **Omron G5LE-14** (photo + BOM LCSC C116963), but the net assignment
  was wrong for the exact pad functions on this part.
- **Fix:** keep footprint **`Relay_THT:Relay_SPDT_Omron-G5LE-1`** and remap the netlist:
  `RELAY_ENABLE_RAIL` → pad 2, transistor collector/flyback anode → pad 5, COM/J_MOTION pin 2
  → pad 1, NO/J_MOTION pin 1 → pad 3, pad 4 NC unused. Re-verify K1-K7 in the fab netlist
  (K7 remains DNP for M1);
  first-article click-test before trusting.
- **Impact:** blocks all motion output. Everything upstream (MCP → driver transistor → rail)
  is validated; only the relay land pattern is wrong.

## ERGONOMICS / BRING-UP (carried from prior rev-C notes)

### 2. ~~Break SWD out to a 3-pin header~~ — DROPPED (Dylan, 2026-06-25)
Superseded by #3. Giving the Pico's micro-USB physical clearance makes normal USB (UF2 /
BOOTSEL) flashing trivial, so a dedicated SWD header isn't needed. SWD would only add on-chip
debugging / USB-enumeration-failure recovery — not required for this firmware. Revisit only if
hardware debugging is later wanted.

### 3. USB connector clearance — ❌ NOT DONE in the rev-C layout (status corrected 2026-07-06)
Give the Pico micro-USB physical clearance from J1 so a normal cable seats. This rev had the USB
jammed against J1 and was flashed via a hand-shaved right-angle micro-B cable; clearing it
restores ordinary USB flashing and makes #2 unnecessary.
- **⚠️ The layout was never changed:** `scripts/place_components_revB.py` still hardcodes
  `J_PI=(126,10,90)` / `RP_PICO=(124,55,0)`, and A1/J1 placements are byte-identical between the
  pre-bug and corrected (Jun-26) boards — the Jun-26 fab package **re-ships the jam**. Since #2
  (SWD header) was dropped on the strength of this item, a board from that package has **neither
  SWD nor USB clearance**.
- **Workarounds until a spin fixes it:** **flash the Pico BEFORE soldering it down** (BOOTSEL
  drag-drop with the module loose), or use the hand-shaved right-angle micro-B cable.
- Carry as an open layout item for the next spin (move A1/J1 → re-route → re-export).

### 4. J1 mating socket + field plugs onto the assembly BOM
The 2×10 IDC ribbon socket for J1 (CNC Tech 3030-20-0102-00 *candidate*) was never on the BOM,
and the field Phoenix plugs (J3/J4/J5/J13/J14 = 1840447 / 1840489 / 1840463 / 1840405 / 1840382)
were a BOM gap. Fold all mating parts into the harness/assembly BOM. (Captured in
`phase8_revB_harness_parts.md` + the harness CSVs.)

### 5. FIELD_WET_V bleed / min-load resistor — ❌ NOT IMPLEMENTED (status corrected 2026-07-06)
The unregulated **TMA-0505S (U37)** rises to ~14 V no-load (expected, but undesirable). Add a
bleed / minimum-load resistor so `FIELD_WET_V` sits near its 5 V nominal unloaded.
- **⚠️ Not in the generator, netlist, or Jun-26 fab package:** `block_supplies()` in
  `generate_kicad_netlist_revB.py` has no bleed — `FIELD_WET_V` carries only the 32 opto Rin
  resistors + U37. Boards from the current package still show ~14 V no-load at TP4 (expected —
  don't chase it at bring-up).
- **Interim option (no spin needed):** an **external bleed / min-load resistor** — 1 k–2.2 kΩ,
  ≥¼ W, across `FIELD_WET_V`→`FIELD_GND` (TP4→TP5, or soldered at any WET access point, returned
  to a J3/J4/J5 field-ground pin) so the rail sits near 5 V unloaded.
- Carry as an open item for the next spin (add to `block_supplies()` + regenerate).

## VERIFY BEFORE COMMITTING THE SPIN (may or may not change layout)

### 6. Per-channel input front-end: dry-contact vs 24 VAC-rectified sense
Choose per channel after at-machine measurement on J3/J4/J5 (Rev-B contract open item). May
change population/BOM per channel.

### 7. Relay contact rating + arc suppression
Confirm G5LE-14 contact rating vs the measured S/T/SP/BE/M/M2 control-coil loads; size the
currently-DNP arc suppression (Rsnub 100 R / Csnub 10 nF X2 / MOV) from the measured inductive
load before populating.

### 8. 5 V supply current budget
Pin the supply sizing for worst-case (6 relay coils + logic + LEDs + margin).

### 9. M2 sweep-reverse interlock preservation
Harness-resolved (not PCB), but note for cutover: preserve the OEM Expander motor-start/reverse
interlock + shorting-plug termination on the M2 path.

## PROCESS (so the footprint class of bug can't recur)

### 10. Footprint-pads-vs-datasheet review gate
Add a distinct review step that cross-checks every footprint's pad numbering against the
**exact ordered part's** datasheet — separate from netlist/ERC review. Trigger especially when
the ordered part number differs from the footprint name (G5LE-1 vs G5LE-14 is exactly this).

### 11. First-article bench test of one of each output type
Before trusting a populated board, energize one channel of each output type (one relay, one
status lamp) and confirm make/break. A netlist/ERC review cannot catch a footprint mismatch;
only a datasheet cross-check or a physical test does.

### 12. Export every spin to a NEW dated directory — never overwrite the as-ordered package
The Jun-26 re-export rmtree'd `kicad/fab_revB_routed_manual/` in place, destroying the rev-B-as-ordered gerbers (that tree is now the rev-C-as-ordered package under revB filenames — see `kicad/fab_revB_routed_manual/PROVENANCE.md`); parameterize the REV/output-dir in `export_fab_revB.py` before the next spin.
