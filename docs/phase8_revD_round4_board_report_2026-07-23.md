# Phase 8 Rev-D — Round-4 Board / Round-5 Bias-Package Report (2026-07-23)

## Outcome

The Rev-D input-front-end gain is worth the board change. Exactly the 40
PC817 collector pull-ups `Rpu_*` (`R4,R6,…,R82`) changed from 10 kΩ to
47 kΩ. No field resistor, unrelated 10 kΩ network, component placement,
copper, net, netclass, safety-rail member, or board outline changed.

This materially reduces required optocoupler sink current while preserving
the 200 mA isolated wetting-rail budget:

- For the 32 slow channels, MCP23017 V_IL(max) at 3.3 V = 0.66 V.
- Required collector sink = `(3.3 - 0.66) / 47 kΩ` = **56.2 µA**.
- Maximum pull-up current = `3.3 / 47 kΩ` = **70.2 µA**.
- MCP23017 V_IH(min) = 2.64 V.
- Worst HIGH from ±1 µA MCP input leakage alone =
  `3.3 - (1 µA × 47 kΩ)` = **3.253 V**, a 0.613 V margin.
- First-order node RC using the MCP23017 50 pF GPIO figure =
  `47 kΩ × 50 pF` = **2.35 µs**.

These bounds require the external 47 kΩ to be the channel's sole pull. The
production RP2040 image disables PUE/PDE on all eight fast-input pads GP6–GP13.
`MachineIO` commands U1/U2 MCP23017 `GPPUA=GPPUB=0x00`, reads back every
IODIR/GPPU write, and fails startup on mismatch. An enabled internal pull
changes the effective resistance and invalidates the 47 kΩ arithmetic. The
four `R_TAPPU_*` 10 kΩ diagnostic-tap drain pull-ups are separate MOSFET-drain
networks and are intentionally unchanged.

Sources: [Microchip MCP23017/MCP23S17 DS20001952C](https://ww1.microchip.com/downloads/en/DeviceDoc/20001952C.pdf),
[UMW PC817 datasheet](https://www.umw-ic.com/static/pdf/56c3a4f58af79c3608299bd9810e59e0.pdf),
and [LCSC C17713 / UNI-ROYAL 0805W8F4702T5E](https://www.lcsc.com/product-detail/C17713.html).

## Honest proof boundary

The resistor change improves receiver-side margin; it does not turn a
typical-curve inference into a lot guarantee. UMW C5692981 guarantees its
CTR rank at the manufacturer's stated test condition, not at this board's
~1.7 mA I_F and hot corner. Fleet release therefore remains blocked until
every populated input passes revised FA-9:

1. loaded-minimum FIELD_WET, cold and ≥70 °C `V_CE(on) ≤ 0.30 V`;
2. hot/min-I_F non-rail-limited `I_C(cap) ≥ 100.3 µA` (30% aging reserve);
3. hot contact-open node ≥2.84 V and receiver INACTIVE; and
4. assertion and release each ≤100 µs.

## Board and BOM implementation

- Generator: `opto_input()` emits 47 kΩ only for `Rpu_*`.
- Netlist: all 40 `Rpu_*` values are 47 kΩ.
- Routed PCB: exactly 40 value-field changes, 10 kΩ → 47 kΩ; no geometry diff.
- Netlist/board audit: fails unless `R4,R6,…,R82` are the complete 47 kΩ set
  and no unrelated part is 47 kΩ.
- Production firmware: RP2040 GP6–GP13 internal pulls disabled. Release identity
  = build `rel-0c746b5747143b8011b01d43`, cfg `05d808411db4bb0d`, UF2 SHA-256
  `d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae`.
- Deployed `MachineIO`: input MCP GPPUA/GPPUB are zero with fail-closed
  write/readback verification. FA-9 repeats both RP2040 and MCP checks live.
- Export lock: dedicated BOM line =
  UNI-ROYAL `0805W8F4702T5E`, LCSC C17713, quantity 40, exact designator set.
- Unrelated 10 kΩ BOM line remains C17414, quantity 13.
- First-article pack and 271-row refdes map were regenerated from the current
  board/netlist; the map contains exactly 40 47 kΩ rows and exactly **28 DNP
  refs**, including the default-open `JP1`.

## J16 substitution correction

F1 remains Littelfuse 1206L020YR / C207035. A substitute is accepted only
when its **minimum Ihold at 85 °C is at least 90 mA**. Nominal trip-current
equivalence is not an acceptance criterion because PPTC trip behavior is
time- and temperature-dependent, not a hard current clamp. The sanctioned
steady J16 module draw remains ≤45 mA.

## Immutable fabrication artifact

Current and only orderable package:

`kicad/fab_revD_2026-07-23_r5/`

The exporter was run once into a new path and a second run against that path
was refused as designed. Every predecessor (`2026-07-21`, `_r2`, `_r3`, and
`2026-07-23_r4`) carries an explicit `_SUPERSEDED_DO_NOT_UPLOAD.txt` marker
that points directly to R5. R4 is tombstoned because it predates the binding
RP2040/MCP internal-pull-zero package gate.

| Artifact | SHA-256 |
|---|---|
| source board | `93972c28d07c8d37193ffecea4bfc3e012b934415fec1f85597d6e87edf7ea7b` |
| source netlist | `1d5d36f26f24c91bcf30ae5c895ac053128f1608054e19410a1506b4741f291f` |
| `manifest.json` | `99f1819ee63cec1578f57331c8b3d7b0eec3db7d228c4f8810c0424ff8f31e93` |
| full fab-package zip | `b3ae254e54ec3efef5ea78daff4e70f73d068a8d2cef3b2d823c218312b71a87` |
| JLC upload zip | `789bec819c017bd841d0e853dc0038d03af040090e59761a6d104b7d2ce13fdc` |
| Gerber/drill zip | `efe841d387e11886f1b7870a1d1f6802f04296d14fb404b5d88b27604e295f68` |

Manifest verification: **45/45 file hashes match**.

Package counts: **271 parts / 28 DNP / 243 placed / 226 JLC placed /
27 JLC lines / 17 hand-solder**.

Proof boundary: the R5 manifest freezes and verifies the exact as-ordered
bytes. KiCad embeds generation timestamps, and may vary serialization order,
in Gerber/drill/report/PDF output; therefore a later clean export is expected
to re-pass topology, DRC, BOM/CPL, part-lock, and count gates, but is not
claimed to reproduce every R5 output byte. In the isolated re-export below,
all ten assembly/order CSVs were byte-identical; time-bearing KiCad outputs
were validated by their gates and the original R5 bytes by the 45-entry
manifest.

## Verification record

| Gate | Result |
|---|---|
| Rev-D SKiDL generator / ERC waiver | PASS — 271 parts; 1 waived error + 39 warnings |
| Rev-D netlist audit | **ALL PASS**, including exact 40-channel 47 kΩ scope |
| Rev-C → Rev-D deep diff | **CLEAN** — 55/55 parts, 39/39 nets, 11/11 touched nets |
| Netclass dry run | PASS — 103/4/13/82/21; Safety_Rail exactly 13 |
| Router check-only regeneration | **0 problems**, 2167 actions (2026-07-24 audit: figure not independently re-run — hours-scale; superseded by the independent DRC 0/0/0 + routed-board audit on the same board bytes) |
| KiCad routed-board audit | **ALL PASS** |
| KiCad DRC in R5 export | **0 violations / 0 unconnected / 0 footprint errors** |
| Export equality/part locks | PASS — BOM↔CPL↔netlist exact; C17713 line exact |
| Immutable-path refusal | PASS — second export refused |
| First-article doc generation | PASS — 271 rows / 24 TPs / 46 shifts / 8 GPB rows / 28 DNP including JP1 |
| DNP cross-artifact equality | **PASS** — first-article prose count = refdes CSV set = R5 exclusion CSV set |
| SKiDL deterministic regeneration | **PASS for the netlist** — two full runs retained netlist `1d5d36f…f291f`. The ERC hash was environment-dependent (pin ordering inside the waived conflict line); fixed 2026-07-24 in the canonicalizer, which now converges every environment to the checked-in `c5dfdf52…1caa3` bytes |
| Python syntax compile | PASS |
| RP2040 fast-input pull regression | PASS — 140/140 v1.2 host checks; GP6–GP13 pulls off |
| RP2040 clean release reproduction | **PASS** — 64/64 + 32/32 + 140/140 + 44/44; manifest, release UF2, and FI-1 UF2 byte-identical |
| MCP input-bias regression | PASS — 2/2; GPPUA/GPPUB zero + mismatch fails closed |
| Fab-package note/DNP regression | PASS — only R5 is current; exact 28-ref set |
| R5 frozen manifest verification | **PASS — 45/45 file hashes match** |
| Isolated exporter reproduction | PASS — all gates; 271/28/243/226/27/17; all 10 assembly/order CSVs byte-identical |
| Rev-C sacred snapshot | **189/189 OK, 0 failures** |

Source Git state when the package was generated:
`fable-audit-fixes` at
`3024346d9f437099acde8a8d4a12d1a0793fee4c`, with the round-4 remediation
present as uncommitted working-tree changes. The manifest's source-file hashes,
not the pre-change Git commit, are the authoritative package provenance.

## Remaining external gates

The source/fab remediation is complete and R5 is the sole orderable package.
This is still **NO-GO for fleet fabrication, installation, or field
deployment**. Deterministic CAD/firmware evidence does not discharge physical or
owner gates: G8/OG-1 enclosure/240 mm sign-off, G12 JLC upload/preview
inspection, G13 harness/coding order, G14 document review, G15 experimental
order acceptance, and FA-1…FA-12/OG-4 on assembled hardware. In particular,
FA-9 is mandatory before fleet quantity or field deployment.
