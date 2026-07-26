# Phase 8 — Complete Backplate Parts List (per lane · per pair · 32-lane house)

**Rev 1 · 2026-07-25.** Everything that mounts to, or connects on, the enclosure backplate.
Board revision: **rev-D r6** (`2fd8c5e`, fab pkg `fab_revD_2026-07-26_r8`), 250 × 240 mm.
Layout: `Downloads/pair_enclosure_backplate_complete.html` Rev 2 (items ①–⑬).

**House arithmetic:** 32 lanes = **32 boards** · **16 pairs** = 16 enclosures / 16 Pis.
Spares recommended at ~10% (called out per line where it matters).

> **DECISIONS BAKED IN:** enclosure **upsized** to 36×30×8 (the three breakout modules pushed
> the panel to ~780 mm vs the 30×24's 686 mm subpanel) · **IDC20 breakouts kept** (custom adapter
> PCB declined) · **plywood backplate** replaces the steel subpanel (non-conductive, ~⅛ the cost).

> **⚠ REV-D DELTAS vs the rev-C-era lists:** **+J15** (J_SLOW_IN_C, 10-pos → plug **1840447**,
> same PN as J3) and **+J16** (J_EXT_I2C, 6-pos → plug **1840405**, same PN as J13). That's
> **7 plugs per board, not 5.** A J3/J15 swap is *electrically silent* — order those two in
> **different colours** and rely on the keying. Also: r6 populates series + clamp diodes on all
> 40 input channels, so the **1N4007 harness bodges for PBZ/DIELL are DELETED** from this list.

---

## A · Controller board and its mounting

| # | Item | Part / spec | Per lane | Per pair | ×32 house | Notes |
|---|---|---|---|---|---|---|
| A1 | Controller PCB, assembled | rev-D r6, 250×240 | 1 | 2 | **32** (+2 spare = 34) | Separate fab/PCBA PO — not costed here |
| A2 | Raspberry Pi Pico | SC0915 castellated | 1 | 2 | **34** | Hand-solder. **NOT Pico H/WH.** ⚠ Flash BEFORE soldering |
| A3 | Isolated DC/DC | TRACO **TMA-0505S** | 1 | 2 | **34** | Hand-solder, exact part, no substitution |
| A4 | Board standoffs | M3 F-F, **12 mm**, brass | 4 | 8 | **128** (+16) | MK pattern **242 × 232 mm** (rev-D moved from 242×217) |
| A5 | Standoff screws, rear | M3 × 18 pan head | 4 | 8 | **128** | Through the plywood from behind into the standoff |
| A6 | Board screws, front | M3 × 6 | 4 | 8 | **128** | Board down onto standoff |
| A7 | Washers | M3 flat + split | 8 | 16 | **256** | |
| A8 | Centre support | adhesive PCB standoff / foam pad | 1 | 2 | **32** | Under the relay band — MK pattern leaves the J6–J11 torque zone unsupported |

> **⛔ A4 is the ONLY approved conductive contact with the board.** Nothing else may touch the
> underside (copper isolation gutters), and nothing conductive within **3 mm of the bottom edge**
> (rev-D SLOW_AUX11 copper runs to 1.28 mm from it).

## A′ · Board-side connectors — HAND-SOLDER, NOT SUPPLIED BY JLC ⚠️

> **These are the parts that go ON the board, not the plugs that mate with it (§B).**
> JLC's PCBA excludes every `J*` designator as hand-solder — the upload BOM contains **zero**
> J refdes — so the PCBA PO physically cannot supply them. Until this section existed they were
> on **no** purchase list and 34 boards would have arrived with no connectors.
> Source of truth: `kicad/fab_revD_2026-07-26_r8/assembly/wsl-phase8b-revD-hand-solder-bom.csv`.

| # | Ref | Phoenix / MFR PN | Description | Per board | ×34 boards (+~10%) |
|---|---|---|---|---|---|
| A9 | J2 | **1715734** | MKDS 1,5/3-5,08 · 3-pos fixed screw block, **5.08 mm** | 1 | **38** |
| A10 | J6–J11 | **1715721** | MKDS 1,5/2-5,08 · 2-pos fixed screw block, **5.08 mm** | **6** | **224** |
| A11 | J3, J15 | **1843680** | MCV 1,5/10-G-3,5 · 10-pos vertical header, **3.5 mm** | 2 | **72** |
| A12 | J4 | **1843729** | MCV 1,5/14-G-3,5 · 14-pos vertical header, **3.5 mm** | 1 | **38** |
| A13 | J5 | **1843703** | MCV 1,5/12-G-3,5 · 12-pos vertical header, **3.5 mm** | 1 | **38** |
| A14 | J13, J16 | **1843648** | MCV 1,5/6-G-3,5 · 6-pos vertical header, **3.5 mm** | 2 | **72** |
| A15 | J14 | **1843622** | MCV 1,5/4-G-3,5 · 4-pos vertical header, **3.5 mm** | 1 | **38** |
| A16 | J1 | CNC Tech **3020-20-0100-00** | 2×10 IDC/box header, 2.54 mm | 1 | **38 — ⛔ HOLD** |

**A10 is 6 blocks, not 7 — J12 (M1) is DNP.** Do not install a 7th.

⚠️ **A16 (J1) is ON HOLD.** The hand-solder BOM marks it *"Candidate — verify body/keying."*
Check shroud, key slot and pin-1 orientation against the KiCad footprint before ordering
(this is verify-before-ordering item 4).

⚠️ **PITCH TRAP:** every MKDS here is **5.08 mm**, every MCV is **3.5 mm**. Refuse any
3.81 mm substitution — it will not fit the board.

⏱ **ORDER THESE FIRST.** `docs/cowork_cart_handoff.md` records **1843680** (J3+J15) and
**1843703** (J5) as *backordered at DigiKey at qty 5*; the fleet needs 72 and 38. Buy the whole
Phoenix family — A9–A15 plus §B6/B7 plus the 1840489 lifetime buy — in **one PO, today**.
Phoenix lead times have historically swung 8–20 weeks and this family gates the entire build.

➕ **Spare MCV headers matter more than the usual 10%:** FA-8 requires an *irreversible* coding-rib
cut on 4 headers per board — **136 cuts fleet-wide** — with no sacrificial stock budgeted today.

## B · Board field plugs (mating halves — one set per board)

> ⚠️ **DECISION OPEN — B1–B5 may be a double-buy.** `docs/phase8_harness_RFQ.md` §2/§4 Tier 1
> has the harness vendor supply these five plugs **already fitted** to the assembly (185 plugs
> incl. §12 spares). Ordering B1–B5 here adds **180 more** against a 160-plug installed need.
> Decide free-issue vs vendor-sourced, then annotate; do not order both.
> Also note: **loose, uncoded plugs are a universal key** — an uncoded J13 lamp plug mates J16
> and lands resistorless LEDs across 5 V while wedging I²C. Any spare stock kept must be
> CP-MSTB 1734634 coded and band-marked per `docs/phase8_revD_harness_bom.csv` before use.
> **B6/B7 are unaffected** — the RFQ correctly excludes J15/J16.
> *(Pre-order audit finding H2.)*

| # | Connector | Phoenix PN | Poles | Per lane | Per pair | ×32 house |
|---|---|---|---|---|---|---|
| B1 | J3 J_FAST_IN | **1840447** | 10 | 1 | 2 | **32** (+4) |
| B2 | J4 J_SLOW_IN_A | **1840489** | 14 | 1 | 2 | **32** (+4) |
| B3 | J5 J_SLOW_IN_B | **1840463** | 12 | 1 | 2 | **32** (+4) |
| B4 | J13 J_LAMP_LED | **1840405** | 6 | 1 | 2 | **32** (+4) |
| B5 | J14 J_SAFETY | **1840382** | 4 | 1 | 2 | **32** (+4) |
| B6 | **J15 J_SLOW_IN_C** ⚠ | **1840447** — *different colour to B1* | 10 | 1 | 2 | **32** — *future/AUX; order with the fleet, land when AUX roles go live* |
| B7 | **J16 J_EXT_I2C** ⚠ | **1840405** — *different colour to B4* | 6 | 1 | 2 | **32** — *future/expansion* |

J2 and J6–J11 are **wire-direct MKDS** blocks soldered to the board — **no mating plug**, ferrule only.
J12 (M1) is **DNP** — no plug, no lead, ever.

## C · Compute and the board↔Pi link

| # | Item | Part | Per pair | ×16 pairs | Price ea | Notes |
|---|---|---|---|---|---|---|
| C1 | Raspberry Pi 4 Model B | 4 GB | 1 | **16** (+2) | ~$65 | one Pi serves BOTH lanes |
| C2 | microSD card | 32 GB industrial/endurance | 1 | **16** (+4) | ~$12 | endurance grade — this is a 24/7 write-cycle role |
| C3 | Pi heatsink / thermal | passive kit | 1 | **16** | ~$5 | ⚠ **height-limited — see C5 note.** Sealed box |
| C4 | Pi DIN mount | **DINrPlate DRP2** | 1 | **16** | $12.95 | rail 2 |
| C5 | **Pi GPIO breakout** | **CZH-LABS F-1019** | 1 | **16** (+2) | $35.00 | ✅ **STACKS DIRECTLY ON THE PI** — see note |
| C6 | ~~40-way ribbon, Pi ↔ F-1019~~ | — | — | **DELETED** | — | ✅ **NOT REQUIRED** — C5 has a GPIO receptacle, no cable |

> **✅ C5 FORM FACTOR CONFIRMED IN HAND (2026-07-25, part opened).** The F-1019 is **not** a
> remote DIN/panel module fed by a ribbon — it carries a **40-pin receptacle that seats directly
> on the Pi's GPIO header** and sits above the board, HAT-style. Three consequences:
> ① **C6 is deleted** (−16 ribbons, ~$96). ② **Pi + F-1019 is ONE stacked unit** on the C4 DRP2 —
> it is *not* a third panel-mounted module, so the panel stack loses one item *(this does **not**
> by itself unwind the 36×30 upsize — see the layout note in §E)*. ③ The I²C path loses a cable
> and a connector transition, which **helps** the standing I²C-length concern.
>
> **⚠ Three things to check on the unit you now have, before buying 15 more:**
> **(a) Heatsink clearance** — C5 sits over the SoC. Measure the standoff height against the C3
> heatsink; a tall passive heatsink may not fit, and C5 blocks convection over the SoC in a
> sealed box. A low-profile heatsink or a different thermal approach may be required.
> **(b) DRP2 compatibility** — confirm the Pi still seats in the DINrPlate with C5 fitted.
> **(c) Access with C5 fitted** — microSD slot, USB-C power in (C9), and whether the screw
> terminals are reachable with the assembly on the rail.
| C7 | **Board breakout** | **Winford `BRK2x10-DIN`** ✅ | **2** | **32** (+4) | $22–27 | one per board, panel-mounted beside its own J1. **APPROVED 2026-07-26** |
| C8 | 20-way ribbon, J1 ↔ breakout | 2×10 IDC socket-to-socket, **~150 mm** | **2** | **32** (+6) | ~$5 | ⚠ **SHORT is the requirement** — I²C integrity |
| C9 | Pi power pigtail | USB-C to bare/ferruled, ~300 mm | 1 | **16** | ~$8 | from fuse F4; keeps the Pi's own input protection in circuit |

## D · Power chain

| # | Item | Part | Per pair | ×16 pairs | Price ea | Notes |
|---|---|---|---|---|---|---|
| D1 | PoE splitter | PoE Texas **GBT-12V60W** | 1 | **16** (+2) | $90 | 802.3bt → 12 V 60 W + gigabit passthrough. Panel-mount |
| D2 | DC-DC converter | Mean Well **DDR-60G-5** | 1 | **16** (+2) | $33 | 9–36 V in → 5 V / 10.8 A, DIN |
| D3 | Fuse terminal blocks | Konnect-It **KN-F10** | **4** | **64** | $3.12 | F1 · F2 · F3 · F4 |
| D4 | Fuses 5×20 mm | 3 A · 2 A fast ×2 · 4 A time-delay | 4 | **64** (+32 spare) | ~$0.40 | **F2/F3 (2 A fast) ARE the H-23 fix** |
| D5 | Ground terminal blocks | Konnect-It **KN-G10** | 2 | **32** | ~$3.10 | 5 V return distribution |
| D6 | Terminal block markers | printed strip | 1 set | **16** | ~$3 | label F1–F4 and the ground blocks |

## E · DIN infrastructure and enclosure

| # | Item | Part | Per pair | ×16 pairs | Price ea | Notes |
|---|---|---|---|---|---|---|
| E1 | DIN rail 35 mm slotted | AD **DN-R35S1-2** (2 × 1 m/pack) | ~600 mm (2 rails) | **~10 m → 5 packs** | $9.25/pk | rail 1 power, rail 2 compute |
| E2 | End brackets | Konnect-It **KN-EB3** | 4 | **64** | ~$0.80 | 2 per rail |
| E3 | Wire duct + cover | 1×2 in slotted PVC, 2 m sticks | ~1 m | **~16 m → 8 sticks** | ~$14/stick | harness fan-out |
| E4 | **Enclosure** | Saginaw **SCE-36EL3008LP** (36×30×8, NEMA 12, hinged) | 1 | **16** (+1) | **$492–649** | ⬆ upsized from 30×24 |
| E5 | Backplate | **½″ plywood**, cut ~686 × 838 mm | 1 | **16** → **~6 sheets (4×8)** | ~$50/sheet | **NOT MDF.** Primer + 2 coats both sides & edges |
| E6 | Backplate mounting | nuts/washers for the box's 4 collar studs | 1 set | **16** | ~$2 | |
| E7 | Cable glands | M20 nylon IP68 | **~9** | **144** (+20) | ~$0.60 | bottom face only; Bundle 1 vs 3 ≥50 mm apart |
| E8 | Breather plug | Gore-type M12 | 1 | **16** | ~$8 | condensation, no dust path — optional |

## F · Internal wiring consumables (per pair)

| # | Item | Spec | Per pair | ×16 pairs | Notes |
|---|---|---|---|---|---|
| F1 | Hook-up wire, 22 AWG | UL1007, assorted colours | ~5 m | ~80 m | C2/C4 breakout↔F-1019 jumpers (~16 leads/box) |
| F2 | Hook-up wire, 18 AWG | UL1015 | ~3 m | ~50 m | power distribution inside the box |
| F3 | Ferrules 0.34 mm² | insulated | ~40 | **~700** | buy 1000-pk |
| F4 | Ferrules 0.75 mm² | insulated | ~30 | **~500** | buy 500-pk |
| F5 | Adhesive tie mounts | — | ~12 | **200** | within 50 mm of every MCV plug row (no locking flange) |
| F6 | Cable ties | 4 in | ~30 | **500** | |
| F7 | **Wire-map card** | printed + laminated | 1 | **16** | **MANDATORY, taped inside the door.** Per-lane cavity map, Candidate-C jumper text, breakout terminal→pin map |
| F8 | Label stock | printed heat-shrink / vinyl | — | — | terminal + module identification |

## G · Off-plate — separate POs, listed so nothing is forgotten

| # | Item | Per lane | Per pair | ×32 house | Status |
|---|---|---|---|---|---|
| G1 | **Field harness assembly** | 1 | 2 | **34** | RFQ issued — `phase8_harness_RFQ.md`, $200–400 ea |
| G2 | Machine interposer: C1 (34-pos) — **we supply MALE / PIN contacts** | 1 | 2 | **32** (+4) | Housing class **AMP 1-201357-1** (AMF `000025144`). Gender ✅ confirmed |
| G3 | Machine interposer: C2A (50-pos) — **we supply FEMALE / SOCKET contacts** | 1 | 2 | **32** (+4) | Housing class **AMP 201358-1** (AMF `000028409`) |
| G4a | **Pin** contacts, `.062` dia (size 16) — for C1 | ~24–30 used/lane | — | *see note* | AMF **`760011197`** TERM-PIN .062 DIA LP |
| G4b | **Socket** contacts, `.062` dia (size 16) — for C2A | ~24–30 used/lane | — | *see note* | AMF **`760019201`** TERM SKT .062 DIA LP |
| G5 | Crimp + extraction tooling | — | — | **2 sets** | size-16 crimper w/ positioner + extractor **AMF `030 004 031`** ("Amp Extracting Tool") |
| G5a | Connector hardware | per conn | — | 32 sets | Guide pin `000028442` · guide socket `000028441` · locking spring clip `000029013` · strain-relief clamp `000029093` (C1) / `000029896` (C2A) |

> **✅ INTERPOSER IDENTITIES FOUND 2026-07-26** — from the AMF 82-70 parts catalogue,
> **C-1 Cable Assembly (p. 67)** and **C-2A Harness Assembly (pp. 74–75)**. This retires the
> `67209 / 67211` molded numbers, which were never catalogue part numbers (5-digit `6xxxx` is
> AMP's *contact* scheme; those were almost certainly mold/tool-cavity marks). It also replaces
> the previously-guessed `66101-x` / `66099-x` contacts, which had no source.
>
> **`.062 dia` confirms size-16 contacts**, consistent with the AMP M Series hypothesis, and
> `201357` / `201358` being consecutive confirms one family in two position counts.
>
> **⚠️ Gender (confirmed at the machine 2026-07-26): machine C1 is FEMALE → our half is MALE
> with PIN contacts. Machine C2A is MALE → our half is FEMALE with SOCKET contacts.** Mixed
> genders, almost certainly deliberate anti-mismating. Do not order two of the same.
>
> **⚠️ G4 quantity is NOT `~2,700`.** That figure assumed full population of every cavity and was
> ~2.5× over. Real demand is ~24–30 *used* leads per lane, split between the two connectors —
> derive the exact per-connector split from the harness wire list before ordering, then add ~25 %
> for crimp practice and field spares. **Contacts and tooling are commodity and in production —
> unlike the housings, they carry no obsolescence risk and need not be lifetime-bought.**
>
> **Remaining open on G2/G3: housing availability only.** Confirm the AMP housings are still
> orderable (M Series is winding down — Mouser already flags it obsolete) or harvest from the
> 32 retired OEM control boxes, which is the primary plan and carries zero ID risk.
| G6 | PoE head-end | — | — | **18 injectors** (TL-POE170S ~$50) or 2× 16-port bt switch | |
| G7 | Cat6 runs | — | 1/pair | **16 runs** | one per enclosure; carries power AND data |
| G8 | J14 Stop/CIS interface | 1 | 2 | **32** | ⛔ **DECISION OPEN** — control-power sensing relay ± pit interlock, ~$25/lane |

---

## Cost roll-up (backplate scope, sections A–F only)

| Scope | Estimate |
|---|---|
| **Per pair** (enclosure + power + compute + DIN + consumables) | **~$890–1,050** |
| **×16 pairs** | **~$14.2k–16.8k** |
| Add: boards ×34 | separate PCBA PO |
| Add: harnesses ×34 @ $200–400 | **$6.8k–13.6k** |
| Add: PoE head-end | **~$0.9k** |
| Add: interposer connectors + contacts + tooling | **~$2–3k** (est., pending ID) |

The **enclosure is ~55% of the backplate cost** — the GPT sourcing hunt against the Saginaw
benchmark is still the highest-leverage cost lever in this list, and the hard requirement is now
**≥310 × 780 mm usable panel** (was 670).

## Verify-before-ordering

1. **IDC20 module footprint** — measure in hand; the 780 mm panel figure is provisional and its
   source drawing draws DIN devices at ~28 mm against a real ~90 mm across-rail. *(F-1019 half of
   this item is CLOSED — it stacks on the Pi and is not a panel module.)*
2. ~~Does the F-1019 ship with its 40-way ribbon?~~ ✅ **CLOSED — moot, it plugs straight onto the
   GPIO header.** Replaced by the three C5 checks: heatsink clearance, DRP2 fit, port access.
3. **IDC20 terminal→pin mapping** — beep it once, record on the wire-map card. Do not trust silkscreen.
4. **Ribbon keying / pin-1** on the 20-way (line C8) against the real J1 — the standing unverified item.
5. **Plywood yield** — ~3 panels per 4×8 sheet at 686 × 838; confirm against the box's actual stud pattern.
6. **Colour availability** for the second 1840447 and 1840405 (lines B6/B7) so J3/J15 and J13/J16 can't be swapped.
