# Phase 8 — Complete Backplate Parts List (per lane · per pair · 32-lane house)

**Rev 1 · 2026-07-25.** Everything that mounts to, or connects on, the enclosure backplate.
Board revision: **rev-D r6** (`2fd8c5e`, fab pkg `fab_revD_2026-07-27_r10`), 250 × 240 mm.
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
| A5 | Standoff screws, rear | **M3 × 30** pan head ⚠️ | 4 | 8 | **128** | Through the plywood from behind into the standoff. ⚠️ **CORRECTED 2026-07-27 for ¾″ ply** — see below |
| A6 | Board screws, front | M3 × 6 | 4 | 8 | **128** | Board down onto standoff |
| A7 | Washers | M3 flat + split | 8 | 16 | **256** | |
| A8 | Centre support | adhesive PCB standoff / foam pad | 1 | 2 | **32** | Under the relay band — MK pattern leaves the J6–J11 torque zone unsupported |


> **⚠️ ¾″ PLYWOOD (19.05 mm) BREAKS THE A5 SCREW — corrected 2026-07-27.** The panel is now ¾″,
> not the ½″ (12.7 mm) originally assumed. A5's **M3 × 18 no longer reaches the standoff at all**,
> and neither does the M3 × 20 that audit finding L-09 proposed as its fix at ½″:
>
> | Screw | Engagement into the 12 mm F-F standoff | |
> |---|---|---|
> | M3 × 18 *(old spec)* | **−2.05 mm** | ❌ does not reach |
> | M3 × 20 *(L-09's ½″ fix)* | **−0.05 mm** | ❌ does not reach |
> | **M3 × 30** | **9.95 mm** | ✅ **use this** |
> | M3 × 35 | 14.95 mm | ❌ bottoms out in a 12 mm standoff |
>
> *(Allowing ~1 mm for the washer stack and head seat.)* Also revisit **E5 plywood cost and
> weight** — ¾″ is ~50 % heavier at ~7.2 kg per 1100 × 570 panel, and the sheet is dearer. Sheet
> yield is unchanged at 4 panels per 4 × 8.

> **⛔ A4 is the ONLY approved conductive contact with the board.** Nothing else may touch the
> underside (copper isolation gutters), and nothing conductive within **3 mm of the bottom edge**
> (rev-D SLOW_AUX11 copper runs to 1.28 mm from it).

## A′ · Board-side connectors — ALL JLC-PLACED as of r10 ✅

> **These are the parts that go ON the board, not the plugs that mate with it (§B).**
>
> ✅ **r10 (2026-07-27) TOOK HAND-SOLDER TO ZERO.** JLC now places all 323 parts. The
> hand-solder count went **17 → 9 → 0** across r9 and r10, eliminating ~4,150 through-hole joints
> including A1's 40 castellated Pico pads — the hardest operation on the board.
>
> ⚠️ **"JLC PLACES IT" IS NOT THE SAME AS "JLC BUYS IT."** Placement is settled; **sourcing is
> not**. For several lines we still buy the part ourselves and consign it — JLC just solders it.
> The split below is now about **who buys**, not who solders.
>
> Per JLC 2026-07-27, consigned and JLC-library parts may coexist on one order for **different**
> parts, but never for the **same** part — so each line is all-one-way. Partial stock does not help.
>
> Source of truth: `kicad/fab_revD_2026-07-27_r10/assembly/wsl-phase8b-revD-jlc-standard-pcba-part-lock.csv`.
> The hand-solder BOM in that package is now **header-only, by design**.

> **🔄 WAVE 1 (r9, 2026-07-26):** J2, J6–J11 and J14 moved to JLC, sourced from their own
> library. **DO NOT BUY THEM — that would be a double-buy**, the same trap §B carries.
> **WAVE 2 (r10, 2026-07-27):** the remaining nine — A1, J1, J3, J4, J5, J13, J15, J16, U45 —
> moved to JLC placement. Their **sourcing** is resolved per line in A′.2 below.

### A′.1 — ⛔ DO NOT BUY · JLC sources AND places these

| # | Ref | Phoenix PN | JLC part | Per board | Stock at LCSC |
|---|---|---|---|---|---|
| ~~A9~~ | J2 | 1715734 | **C480520** | 1 | 1,173 |
| ~~A10~~ | J6–J11 | 1715721 | **C480516** | 6 | 1,591 |
| ~~A15~~ | J14 | 1843622 | **C480549** | 1 | 2,481 |

⚠️ **On C480516 vs C5183929:** both are Phoenix 1715721, but `C5183929` (the number this repo
cited before) held only ~239 pcs against a **204-piece** fleet need. `C480516` is the line to
use. If JLC ever proposes swapping back, refuse.

### A′.2 — JLC PLACES THEM · but we may still have to BUY them

> **All nine are in the r10 assembly BOM with pinned C-numbers — JLC solders every one.** What is
> unresolved is *where the part comes from*. Lines JLC cannot fill from stock go to Global
> Sourcing or, more likely, we buy and consign. **Buying these is still on us; soldering them
> is not.**

| Ref | JLC part | Source decision |
|---|---|---|
| **A1** Pico | `C7203002` | ✅ **JLC** — confirmed SC0915, in library |
| **J13, J16** | `C5443576` | ✅ **JLC** — 503 in stock vs 72 needed |
| **J3, J15** | `C3585531` | ⛔ **BUY OURSELVES** — JLC $11.31 is supplier-set and unmovable vs Mouser ~$5.02 (722 stock). ~$453 saved |
| **J4** | `C3582595` | ⏳ 0 stock — Global Sourcing quote pending, else consign |
| **J5** | `C3019636` | ⏳ 3 stock vs 38 — same |
| **J1** | `C17373551` | ⏳ 0 stock — same. DigiKey holds 2,958 |
| **U45** | `C5454708` | ⏳ 16 stock vs 38 — expect to consign. DigiKey holds 5,964 |


| # | Ref | Phoenix / MFR PN | Description | Per board | ×34 boards (+~10%) |
|---|---|---|---|---|---|
| A11 | J3, J15 | **1843680** | MCV 1,5/10-G-3,5 · 10-pos vertical header, **3.5 mm** | 2 | **72** |
| A12 | J4 | **1843729** | MCV 1,5/14-G-3,5 · 14-pos vertical header, **3.5 mm** | 1 | **38** |
| A13 | J5 | **1843703** | MCV 1,5/12-G-3,5 · 12-pos vertical header, **3.5 mm** | 1 | **38** |
| A14 | J13, J16 | **1843648** | MCV 1,5/6-G-3,5 · 6-pos vertical header, **3.5 mm** | 2 | **72** |
| A16 | J1 | CNC Tech **3020-20-0100-00** | 2×10 IDC/box header, 2.54 mm | 1 | **38** ✅ |
| A17 | — | **sacrificial MCV headers** | 2 × 1843680 + 2 × 1843648 + spares | — | **~10** |

> **🔎 JLC PART-IDENTITY VERIFICATION — 2026-07-27. All five resolve to the EXACT required MPNs;
> the problem is stock, not identity.** JLC proposed C-numbers for every A′.2 line and each was
> checked against its own part-detail page (not a search result — searching JLC by bare numeric
> Phoenix MPN returns false negatives).
>
> | Ref | JLC C-number | Resolves to | Stock | Need | Verdict |
> |---|---|---|---|---|---|
> | J13, J16 | **C5443576** | Phoenix **1843648** ✅ | 503 | 72 | **ACCEPT — proceed** |
> | J3, J15 | C3585531 | Phoenix **1843680** ✅ | **0** | 72 | stock-blocked |
> | J4 | C3582595 | Phoenix **1843729** ✅ | **0** | 38 | stock-blocked |
> | J5 | C3019636 | Phoenix **1843703** ✅ | **3** | 38 | stock-blocked |
> | J1 | C17373551 | CNC Tech **3020-20-0100-00** ✅ | **0** | 38 | stock-blocked |
> | U45 | — | *no match in JLC's library* | — | 38 | not sourceable via JLC |
>
> **✅ Mechanically this is the best possible answer: no substitution is on the table**, so FR-2/FR-9
> stay closed, no re-route is triggered, and the five mating plugs + CP-MSTB coding scheme + the 185
> vendor-fitted harness plugs all remain valid. The exposure is **purely procurement**.
>
> ⚠️ **Two anomalies to resolve before paying:**
> **(a) C3585531 is priced $11.31 ea** — against $2.48 for the 12-pole sibling and $1.10 for the
> 4-pole. A 10-pole costing more than a 12-pole is spot pricing, not a catalogue progression.
> 72 × $11.31 = **$814**. Requote it.
> **(b) C3582595 is listed "Assembly Type: SMT Assembly"** on a through-hole part, while its 12-pole
> sibling is correctly listed Wave Soldering. Probably bad JLC data — but it can mis-route the process.
>
> ⛔ **Zero stock on a 2-per-board connector is exactly where a contract manufacturer proposes a
> "dimensionally similar" swap at build time. Restate NO SUBSTITUTIONS per line on the order.**
>
> **All four short lines are stocked at franchised distributors** (Digi-Key alone lists 2,958 of the
> J1 header), so buying them ourselves — which §A′.2 already plans, and which the "order these first"
> block already calls the gating family — preserves the exact MPNs either way.

> **✅ DISTRIBUTOR SOURCING VERIFIED 2026-07-27 — the stock block is JLC's, not the market's.**
> Every short line is available in quantity at a franchised distributor, so **consignment (or
> buying + hand-soldering) preserves the exact MPNs and hand-soldering is NOT forced.**
>
> | Part | Ref | Need | Distributor stock | |
> |---|---|---|---|---|
> | Phoenix **1843680** | J3, J15 | 72 | **Mouser 722** · DigiKey 52 | ✅ |
> | Phoenix **1843729** | J4 | 38 | DigiKey lists it @ $5.72, count not readable | ⚠️ confirm |
> | Phoenix **1843703** | J5 | 38 | **DigiKey 2,139** @ $4.04/10+ | ✅ |
> | Phoenix **1843648** | J13, J16 | 72 | **JLC 503** — use JLC, no consignment | ✅ |
> | CNC Tech **3020-20-0100-00** | J1 | 38 | **DigiKey 2,958** | ✅ |
> | TRACO **TMA 0505S** | U45 | 38 | **DigiKey 5,964** @ $4.16/50+ | ✅ |
>
> **Parts total ≈ $925**; consignment overhead ≈ $125–195 → **~$1,050–1,120 all in**.
>
> 💡 **The overpricing on ONE line exceeds the entire consignment overhead.** JLC quoted
> C3585531 (1843680) at **$11.31 × 72 = $814**; Mouser stock is ~$5.02 → **~$361**. Buying it
> ourselves saves **~$450 on that line alone** — more than consignment costs in total.
>
> ⚠️ **Buy from shelf stock, never backorder.** Both 1843680 and the TMA 0505S show a **12-week
> manufacturer lead time** beyond stock. Taking Mouser's 722 and DigiKey's 5,964 avoids that
> entirely; a backorder would put the whole build behind the harness.
>
> ⚠️ **Do not construct distributor URLs to check a part.** During this verification a guessed
> DigiKey product-detail link returned **1830680** — an 11-position 3.81 mm part, 0 stock —
> instead of the intended 1843703. Different pole count, different pitch, and it would have been
> fatal. Same failure class as the `C325772` hallucination in the run log. Search by MPN; never
> assume a product ID.

**A′.2 is a WAVE-2 CANDIDATE.** These four MCV part numbers are unresolved in JLC's library —
not absent, *unresolved*: searching JLC by bare numeric Phoenix MPN returns **false negatives**
(`searchTxt=1843622` → "0 Found" while `partdetail/C480549` shows it in stock). A free Global
Sourcing quote resolves them. If JLC can source the **exact** PN, they move to JLC too. ⛔ **A
substitution is never acceptable** — it re-opens FR-2/FR-9, forces a re-route, and invalidates
all five mating plugs plus the CP-MSTB coding scheme and the harness RFQ's 185 fitted plugs.

**A17 is new and required either way:** FA-8 step 1 demands the coding-rib cut be proven on a
sacrificial part first, and with JLC (or a vendor) holding production headers there are no loose
ones. The rib is cut **post-solder on the board's own header** — Phoenix designs MCV with the
coding features facing away from the PCB — so JLC placing headers does not break FA-8.

**J6–J11 is 6 blocks, not 7 — J12 (M1) is DNP.** Do not install a 7th.

✅ **A16 (J1) HOLD RELEASED 2026-07-26 — verify-before-ordering item 4 is CLOSED.** Shroud and
polarising notch confirmed present on rev-B/C, and rev-D's J1 is **geometrically identical to
rev-B** (same footprint, same 90° rotation, same pad-1 Y of 10.0 mm; only X moved 126 → 135.5).
Measured on rev-D: pin-1 row at y = 10.000 mm vs the even row at 7.460 mm, board edge at y = 0 —
so the **pin-1 row faces the board interior**, matching the rev-B/C notch orientation. A 2×10 box
header inserts only two ways and pin 1 and the notch move together, so correct pin-1 placement
forces correct keying. 5 pcs of this PN were bought for rev-B and one is soldered to board #1,
which brought up I²C successfully. Full record: readiness checklist DECISION RECORD item 9.

⚠️ **PITCH TRAP:** every MKDS here is **5.08 mm**, every MCV is **3.5 mm**. Refuse any
3.81 mm substitution — it will not fit the board.

⏱ **ORDER THESE FIRST.** `docs/cowork_cart_handoff.md` records **1843680** (J3+J15) and
**1843703** (J5) as *backordered at DigiKey at qty 5*; the fleet needs 72 and 38. Buy the whole
Phoenix family — **A11–A14, A16, A17** plus §B6/B7 plus the 1840489 lifetime buy — in
**one PO, today**. *(A9/A10/A15 are no longer on this list — JLC supplies them, see A′.1.)*
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
| B2 | J4 J_SLOW_IN_A ⚠️ | **1840489** — *see lifecycle note* | 14 | 1 | 2 | **32** (+4) |
| B3 | J5 J_SLOW_IN_B | **1840463** | 12 | 1 | 2 | **32** (+4) |
| B4 | J13 J_LAMP_LED | **1840405** | 6 | 1 | 2 | **32** (+4) |
| B5 | J14 J_SAFETY | **1840382** | 4 | 1 | 2 | **32** (+4) |
| B6 | **J15 J_SLOW_IN_C** ⚠ | **1840447** — *different colour to B1* | 10 | 1 | 2 | **32** — *future/AUX; order with the fleet, land when AUX roles go live* |
| B7 | **J16 J_EXT_I2C** ⚠ | **1840405** — *different colour to B4* | 6 | 1 | 2 | **32** — *future/expansion* |


> **⚠️ 1840489 LIFECYCLE — the repo and DigiKey DISAGREE, resolve before treating this as a
> lifetime buy (checked 2026-07-27).** Three rev-B-era files call it discontinued / last-time-buy
> / "will not be replenished" (`phase8_revB_preorder_parts_list.md:13`,
> `phase8_revB_preorder_parts.csv:12`, `cowork_cart_handoff.md:27`). **DigiKey currently lists it
> as lifecycle ACTIVE with a 6-week manufacturer lead time** — out of stock, backorder available,
> $16.42/1 and $13.34/10.
>
> Those are different situations. *Discontinued* means buy 50 now or never. *Active with a 6-week
> lead* means order early but reorder is possible. **Confirm with a distributor before committing
> to the lifetime quantity** — ordering early is right either way, but 50 pcs at $13.34 is ~$670
> and the justification changes.
>
> ⛔ DigiKey offers **Amphenol ELXP14100** as a substitute. **Refuse it** — a substituted plug
> breaks the CP-MSTB coding scheme and the mating contract with the board headers.

J2 and J6–J11 are **wire-direct MKDS** blocks soldered to the board — **no mating plug**, ferrule only.
J12 (M1) is **DNP** — no plug, no lead, ever.

## C · Compute and the board↔Pi link

| # | Item | Part | Per pair | ×16 pairs | Price ea | Notes |
|---|---|---|---|---|---|---|
| C1 | Raspberry Pi 4 Model B | 4 GB | 1 | **16** (+2) | ~$65 | one Pi serves BOTH lanes |
| C2 | microSD card | 32 GB industrial/endurance | 1 | **16** (+4) | ~$12 | endurance grade — this is a 24/7 write-cycle role |
| C3 | Pi heatsink / thermal | passive kit | 1 | **16** | ~$5 | ⚠ **height-limited — see C5 note.** Sealed box |
| ~~C4~~ | ~~Pi DIN mount~~ | ~~DINrPlate DRP2~~ | — | **DELETED** | ~~$12.95~~ | ⛔ **DELETED 2026-07-27 — the F-1019's own metal carrier is the mount.** Saves ~$207 fleet. See the C5 note |
| C5 | **Pi GPIO breakout** | **CZH-LABS F-1019** | 1 | **16** (+2) | $35.00 | ✅ **STACKS DIRECTLY ON THE PI** — see note |
| C6 | ~~40-way ribbon, Pi ↔ F-1019~~ | — | — | **DELETED** | — | ✅ **NOT REQUIRED** — C5 has a GPIO receptacle, no cable |

> **✅ C7 DIMENSIONED + PINOUT DOCUMENTED (2026-07-26) — reverted to the Electronics-Salon
> `D-220`.** Manufacturer drawing and board photo obtained, so the Winford substitute is no
> longer needed (it existed only because C7 had no manufacturer PN and no published dimensions).
>
> | | |
> |---|---|
> | **Along rail (L)** | **79.352 mm** |
> | **Across rail (H)** | **87 mm** |
> | **Depth (D)** | **54 mm** |
> | Module code | `D-220` (the IDC-20 variant of the D-217…D-227 family) |
> | Mapping | **1:1 straight-through** — IDC header pin *n* → terminal *n*, per the manufacturer's own wiring diagram |
> | Silk | Standard IDC convention: odd `1…19` on one row, even `2…20` on the other |
>
> ⭐ **This is the number that was blocking the panel layout.** With C5 now stacking on the Pi
> (not a panel module) and C7 measured at 79.352 × 87 mm, the panel stack can finally be re-run
> against real envelopes instead of the drawing's ~28 mm placeholders — which is what gates the
> E4 enclosure PO (~$8–10k). See M-06/M-07 in the pre-order audit.
>
> ⚠️ **Keep ONE continuity check at first article — and this is not generic distrust of the silk.**
> The manufacturer documents 1:1 and the numbering follows standard IDC convention, so the map is
> almost certainly right. The reason to beep it once, for the whole fleet, is the *specific*
> consequence here: **J1 terminal 1 = `VCC_5V` and terminal 3 = `I2C_SDA`, and they are adjacent
> on the same row.** A single-position slip puts 5 V onto the Pi's SDA line. Two minutes, once,
> against a Pi-killer. Record the result on the F7 wire-map card.
> *(Standing rule unchanged: never land terminal 1 `VCC_5V` or terminal 11 `VCC_3V3` on the Pi.)*

> **✅ C5 CONFIRMED FROM PHOTOS OF THE PART, 2026-07-27 — it is a PCB HAT.** 40-pin FEMALE socket
> underneath (seats on the Pi's GPIO header), four rows of 10 screw terminals plus a 40-pin MALE
> pass-through IDC box header on top, four corner mounting holes, one LED. Silkscreen reads
> "Raspberry Pi B+ Breakout / HCDC". **Terminals are labelled by BCM GPIO name** — `SDA`, `SCL`,
> `TXD`, `RXD`, `IO4`…`IO27`, `MOSI`, `MISO`, `SCLK`, `CE0`, `CE1`, plus 3V3/5V/GND — which will make
> the WSL-PI-LINK-B End-B assignment nameable once the Pi GPIO map is frozen.
>
> ✅ **CARRIER CONFIRMED 2026-07-27 — the F-1019 ships as TWO parts, and C4 IS deleted after all.**
> Besides the green HAT there is a two-piece **black metal carrier** (`CZH-LABS / For RPi 4 Model B /
> Model F-1019`) with four Pi standoff posts and **outward mounting flanges**. Trial fit by the owner:
> **Pi onto the standoffs → HAT onto the GPIO header → lid on, terminals still accessible.**
>
> *History, so the flip-flop stays legible: a 2026-07-26 layout agent called the F-1019 "a complete
> aluminium Pi carrier with its own ears" and deleted C4. Photos of the green PCB appeared to disprove
> that, so C4 was reinstated on 2026-07-27. Photos of the carrier then showed the agent was
> substantially right. **C4 is deleted.** The only genuinely wrong part of the original claim was that
> the breakout PCB itself was the carrier — it is a separate metal part in the same box.*
>
> **Two benefits beyond the $207:** the metal shell restores EMI shielding the plastic enclosure gives
> up — most valuable for board B's **bit-banged** I²C bus — and gives the Pi a conducted thermal path.
>
> ⚠️ **Still to measure:** carrier outline and flange hole pattern (caliper, no Pi needed — **this
> gates the plywood drilling**), and whether the **C3 heatsink** clears the HAT. The heatsink sits on the
> SoC in the gap between the Pi's top face and the HAT's underside; a tall one will foul it. If so, fit a
> low-profile heatsink — that is a C3 change, not a reason to drop the carrier.
>
> **Original 2026-07-25 note, still accurate:** The F-1019 is **not** a
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
| C7 | **Board breakout** | **Electronics-Salon `D-220`** (IDC20 2×10) ✅ | **2** | **32** (+4) | $22–27 | one per board, DIN-mounted beside its own J1. **DIMENSIONED 2026-07-26** — see below |
| C8 | 20-way ribbon, J1 ↔ breakout | 2×10 IDC socket-to-socket, **~150 mm** | **2** | **32** (+6) | ~$5 | ⚠ **SHORT is the requirement** — I²C integrity |
| C9 | Pi power pigtail | USB-C to bare/ferruled, ~300 mm | 1 | **16** | ~$8 | from fuse F4; keeps the Pi's own input protection in circuit |
| C10 | **USB composite capture dongle** ⚠️ | UVC composite-to-USB | 1 | **16** (+2) | ~$20 | **NEW 2026-07-26.** The camera's video path to the Pi. Was audit finding L-06, on no BOM line until now |
| C11 | **Camera video coax** ⚠️ | 75 Ω composite video, ~4.7 m | **2** | **32** (+4) | ~$8 | **NEW 2026-07-26.** Machine camera → C10 dongle. See the gland warning below |


> **⚠️ CAMERA VIDEO PATH — added 2026-07-26 after a coverage check, and it carries a gland trap.**
> The panel layout routes two camera video coax per pair (`PANEL-W2` P46, gland **G10**) and the
> DIELL-board deprecation gave the camera its own 12 V feed (F5, harness leads W52/W53) — but the
> **coax itself and the capture dongle were on no BOM line at all**, and are in neither custom
> harness. They are now C10/C11.
>
> ⛔ **G10 is specified M16 and that is probably too small.** The same problem was already caught
> and fixed for Cat6 — G9 was upsized to **M25** because an RJ45 is ~13.4 mm over the latch and an
> M20 only passes 6–12 mm (audit L-05). **A moulded RCA plug is ~9–10 mm, and G10 must pass TWO of
> them.** Either upsize G10, or buy bulk coax and field-terminate at the box. Decide before
> drilling the gland wall.
>
> **These are bought cables, not a third custom harness.** Composite coax with standard connectors
> is a commodity; a harness shop would add cost without adding value.

## D · Power chain

| # | Item | Part | Per pair | ×16 pairs | Price ea | Notes |
|---|---|---|---|---|---|---|
| D1 | PoE splitter | PoE Texas **GBT-12V60W** | 1 | **16** (+2) | $90 | 802.3bt → 12 V 60 W + gigabit passthrough. Panel-mount |
| D2 | DC-DC converter | Mean Well **DDR-60G-5** | 1 | **16** (+2) | $33 | 9–36 V in → 5 V / 10.8 A, DIN |
| D3 | Fuse terminal blocks | Konnect-It **KN-F10** | **6** | **96** | $3.12 | F1 · F2 · F3 · F4 · **F5 camera** · **F6 sensors** |
| D7 | **Isolated 12 V DC-DC** ⚠️ | ≥5 W isolated, 12 V in / 12 V out | 1 | **16** (+2) | ~$15 | **NEW 2026-07-26.** Feeds F6 only. Its 0 V is `FIELD_GND` — see the warning below |
| D4 | Fuses 5×20 mm | 3 A · 2 A fast ×2 · 4 A time-delay | 4 | **64** (+32 spare) | ~$0.40 | **F2/F3 (2 A fast) ARE the H-23 fix** |
| D5 | Ground terminal blocks | Konnect-It **KN-G10** | 2 | **32** | ~$3.10 | 5 V return distribution |
| D6 | Terminal block markers | printed strip | 1 set | **16** | ~$3 | label F1–F4 and the ground blocks |


> **⚠️ TWO GROUND DOMAINS — do not merge them.** The 2026-07-26 decision to deprecate the OEM
> DIELL interface board means we now power the ball sensors and the camera ourselves, and they
> are **not** on the same supply:
> - **F6 → sensors** runs off the **isolated** DC-DC (D7). The sensors sink their output to
>   `FIELD_GND`, so their 0 V *is* `FIELD_GND`. Powering them from the ordinary 12 V rail would
>   bond `FIELD_GND` to logic ground and **defeat the TMA-0505S field isolation the whole input
>   design rests on.**
> - **F5 → camera** runs off the ordinary (non-isolated) 12 V. The camera's video return reaches
>   logic ground through the capture dongle anyway, so an isolated supply would only re-bond it
>   by a longer path.
>
> Harness leads are colour-coded so the two cannot be confused: **Violet/Grey = isolated sensor
> pair**, **Brown/Pink = camera pair**, used on no other lead (wire list Rev 4, W50–W53).
> Full rationale: `docs/phase8_diell_board_deprecation_2026-07-26.md`.

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
| G7 | **Cat6 runs, switch → enclosure** | solid-core Cat6, **1000 ft box** | 1/pair | **16 runs · ~752 ft** | one per enclosure; carries **power AND data** (802.3bt). Cut list below |
| G8 | J14 Stop/CIS interface | 1 | 2 | **32** | ⛔ **DECISION OPEN** — control-power sensing relay ± pit interlock, ~$25/lane |
| G9 | **Ball-detect sensors** (replaces OEM DIELL) | 2 | 4 | **64** (+8) | ~$40–65 ea. M18 retroreflective NPN-NO, 10–30 VDC, IP67. **NEW 2026-07-26** — see below |


> **🔄 OEM DIELL INTERFACE BOARD DEPRECATED (2026-07-26).** Confirmed at the machine that the
> board feeds and outputs **only** the DIELL sensors and the camera — nothing else — so it can be
> deleted outright rather than replaced. That retires **32 boards** with no sourcing story (and
> 42 VAC out of the ball-detect path) plus **64 sensors** with no North American distribution.
> A commodity NPN-NO sensor sinks the J3 field pin to `FIELD_GND` directly, which is
> electrically the same event the channel was designed for — no interface board needed.
> ⛔ **Retroreflective or through-beam only — never diffuse.** A bowling ball is dark and glossy.
> First article: Datasensing/Micro Detectors **`SSC/AN-0C`**, the documented successor, ~$64 at
> Rankin USA. Full spec, the two-ground-domain rule, and the BOM deltas:
> **`docs/phase8_diell_board_deprecation_2026-07-26.md`**.
> *(This also CLOSES audit finding M-21 — the camera's 12 V died with T-VISION.)*


> **📏 CAT6 CUT LIST — measured on site 2026-07-27.** Switch sits between lanes 21 and 22.
> **Measured path to the first Pi in each direction = 12 ft** (this figure already includes the drop
> to the Pi **and** its slack). **Each subsequent Pi is +10 ft.**
>
> **Cut = 12 + 10(N−1) ft. Nothing is added** — the slack is already inside the 12.
>
> | Pi from switch | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
> |---|---|---|---|---|---|---|---|---|
> | **Cut (ft)** | **12** | **22** | **32** | **42** | **52** | **62** | **72** | **82** |
>
> ×2 directions = **752 ft**. A 1000 ft box leaves ~250 ft spare for re-pulls.
>
> ⚠️ **Confirm the split before cutting the two longest.** 8 Pis each direction gives the table
> above. If lanes number 1–32 sequentially, pair 11 (lanes 21+22) straddles the switch and the
> split is **10 low / 5 high / 1 at the switch** — which adds **92 ft** and **102 ft** on the low
> side and stops the high side at 52 ft (~742 ft total). Same box either way.
>
> ⭐ **Cut, terminate and TEST the first cable before cutting the other fifteen.** That validates the
> path measurement, the slack and the crimp technique on one cable instead of discovering a
> systematic error sixteen times.
>
> **Build notes:**
> - ⚠️ **SOLID core, not stranded.** Stranded is for patch cords and attenuates more over these runs.
> - Plugs must be **rated for solid core** (or pass-through). Crimper + tester required.
> - PoE is not a constraint: 802.3bt reaches 100 m (328 ft); the longest run here is ~82 ft.
> - ⭐ **Terminate INSIDE the enclosure.** Only bare cable then passes the gland, so **G9 drops from
>   M25 back to M16** — and the seal actually works. An M25 gland gapes around a 5.5–6.5 mm Cat6
>   jacket even with the correct insert; that was a latent IP-rating problem in the M25 fix, which
>   had been sized to pass a moulded RJ45 (~13.4 mm over the latch, audit L-05).
> - **Label both ends as you pull.** Sixteen identical grey cables in a machine room is where an
>   afternoon disappears.


> **📨 JLC ANSWERS — 2026-07-27 (Dorae). Four things resolved, one decided against us.**
>
> | # | Question | Answer | Consequence |
> |---|---|---|---|
> | 6 | Pico **C7203002** order code | ✅ **"the Raspberry Pi Pico model provided by JLCPCB is SC0915"** | **Bare RP2040 module, no headers.** A1 is unblocked — the FA-4 acceptance is no longer conditional |
> | 4 | **C3582595** listed "SMT Assembly" on a THT part | ✅ **"the default assembly method for this component is Wave Soldering"** | Data-error theory confirmed. Anomaly closed |
> | 3 | **C3585531** at $11.31 | ⛔ **"we are currently unable to determine or adjust the component price … pricing is provided by the supplier"** | **The $11.31 stands.** See below |
> | 7 | Process rails at 250 × 240 | ⚠️ They will follow instructions **only if put in the PCBA remark** — they did NOT confirm rails are unnecessary | Must be written into the order remark |
> | 5 | Consignment fees | Visible on the platform once the flow is started | The previously-unverified ~$45 figure will be confirmed in-flow |
>
> ⛔ **1843680 (J3/J15) IS NOW A DECIDED BUY-OURSELVES.** JLC cannot move the price and it is
> supplier-set, so the choice is $11.31 × 72 = **$814** through JLC against Mouser's ~$5.02 × 72 =
> **~$361** from 722 in stock. **~$453 saved on one line** — more than the entire consignment
> overhead. There is nothing further to negotiate here.
>
> ⭐ **TWO PARTS CAN MOVE TO JLC RIGHT NOW WITH NO SOURCING FRICTION AT ALL:**
> - **A1** → `C7203002`, now confirmed SC0915, in their library, Standard PCBA, reflow-capable.
> - **J13 / J16** → `C5443576` = Phoenix 1843648, **503 in stock** against a need of 72.
>
> Neither needs Global Sourcing or consignment. Moving them alone drops hand-solder **9 → 6** and
> removes the hardest hand-solder operation on the board (A1's 40 castellated pads).

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

1. ✅ **CLOSED 2026-07-26 — both halves.** C7 is the Electronics-Salon **D-220**, measured
   **79.352 mm along rail × 87 mm across rail × 54 mm deep**; C5 (F-1019) stacks on the Pi and is
   not a panel module at all. **The panel stack must now be RE-RUN** against these real envelopes —
   the source drawing used ~28 mm placeholders against a real ~87–90 mm, which is what produced the
   provisional 780 mm figure. Re-running it is what releases the E4 enclosure PO.
2. ~~Does the F-1019 ship with its 40-way ribbon?~~ ✅ **CLOSED — moot, it plugs straight onto the
   GPIO header.** Replaced by the three C5 checks: heatsink clearance, DRP2 fit, port access.
3. **IDC20 terminal→pin mapping** — manufacturer documents **1:1 straight-through** (IDC pin *n*
   → terminal *n*). Still beep it **once** at first article and record on the wire-map card:
   terminal 1 = `VCC_5V` sits adjacent to terminal 3 = `I2C_SDA` on the same row, so a
   one-position slip puts 5 V on the Pi's SDA. Two minutes for the whole fleet.
4. **Ribbon keying / pin-1** on the 20-way (line C8) against the real J1 — the standing unverified item.
5. **Plywood yield** — ~3 panels per 4×8 sheet at 686 × 838; confirm against the box's actual stud pattern.
6. **Colour availability** for the second 1840447 and 1840405 (lines B6/B7) so J3/J15 and J13/J16 can't be swapped.
