# Phase 8 rev-D — ORDER RUNBOOK

**Written 2026-07-28. Supersedes the scattered decisions in `phase8_backplate_BOM.md`,
the pre-order audit, and the JLC correspondence notes.**
This is the single document to work from when placing orders.

---

# PART 1 — WHAT WAS DECIDED

## The five standing decisions

| # | Decision | Consequence |
|---|---|---|
| 1 | **ZERO HAND-SOLDER.** JLC places all 323 parts. | `kicad/fab_revD_2026-07-27_r10/` ships **as-is**. No r11, no re-cut, no re-verification. |
| 2 | **COST IS NOT A FACTOR.** Schedule and certainty win. | Global Sourcing is rejected on lead time despite being ~$380 cheaper. Consignment overage is bought freely. |
| 3 | **CONSIGN, DON'T GLOBAL-SOURCE.** | 13 lines bought at distributors and shipped to JLC. JLC still solders every one. |
| 4 | **FLEET = 34 BOARDS** (32 lanes + 2 spares). | Parts ordered at 38 sets (34 + 4 spare sets), then +25 % overage on consigned lines. |
| 5 | **Harness is the owner's to chase.** League delay accepted. | Board schedule is optimised independently. |

## Why Global Sourcing was rejected

JLC quoted (ref `XOB2026072800482-12616613A`, expires **Aug 13–24 GMT+8**):

| MPN | GS lead |
|---|---:|
| TMA 0505S | 7 bd · 1.4 wk |
| 1843680 | 8 bd · 1.6 wk |
| 1843703 | 21 bd · 4.2 wk |
| 3020-20-0100-00 | 21 bd · 4.2 wk |
| **1843729 (J4)** | **75 bd · 15 wk** |

⚠️ **The "4.2 wk" figure in older notes is the PARTS PROCUREMENT lead, not board-in-hand.**
It was mislabeled "Board lead" in `phase8_backplate_BOM.md:557`. There is no build term and no
freight term in it. Real board-in-hand on that route is **~6.4–8.8 weeks**.

Once *any* line is consigned, the consignment leg (~2–2.5 wk) is the critical path and JLC does
not start the build until every part is on hand. Splitting the two fast lines off to Global
Sourcing therefore buys **zero days** while adding a second process. Hence: consign everything
that isn't solidly in JLC's own stock.

**Estimated board-in-hand: ~4–6.5 weeks from upload.** Every step after "buy" is an estimate,
not a JLC commitment — see the questions in Part 2, Step 2.

## The three risks being accepted

1. **⚠️ N = 0 driven-24 VAC channels.** `readiness_checklist:124-134` — cams read as dry
   contacts is *"what lets 34 boards ship against the current revision"* and *"is reversible only
   by a board revision."* That decision was **delegated, not owner-measured**, and SA/SB/SC/TA1/
   TA2/TB are still recorded UNMEASURED. **One powered scope session at a cam microswitch settles
   it. A DMM cannot** — it can't separate 60 Hz AC from a chopped DC train.
2. **⚠️ PC817B CTR bin.** Design assumes **B rank, CTR 130–260 %**. No distributor page states
   the bin; LCSC prints `"600%;50%"` (the ungraded family span). The whole 22.3× → 16.4× margin
   stack rests on that floor, across 1,520 parts. **Mitigation: demand the bin on the CoC.**
3. **⚠️ r6 has never existed in copper.** Series `Dser` + anti-parallel `Dclamp` on all 40
   channels are paper-validated only. FA-16/FA-15/FA-9 are the proof and they run *after*
   delivery. **Mitigation: run the existing bench pre-check now** (`phase8_FA9_bench_precheck_guide.md`
   — ~1 h, zero new parts, and it is 4.7× harder than the real board).

## What is NOT a risk — checked and dismissed

- **2N7002 lamp drivers (Q8–Q11).** A stock-audit flagged the 115 mA rating as marginal.
  It isn't: `lamp_led_output()` fits a **330R limiter in every LED return**
  (`generate_kicad_netlist_revB.py:305,312` → R106/R109/R112/R115). Worst case 5 V/330R =
  **15 mA against 115 mA — 7.7× margin.** No respin question.

---

# PART 2 — THE JLC ORDER, STEP BY STEP

## STEP 0 — Close the pre-order gates ⛔ BLOCKING

`readiness_checklist:4` — *"Do not place a fab order until every PRE-ORDER GATE is `[x]`."*

| Gate | State | What closes it | Time |
|---|---|---|---|
| **G8** — 250×240 board growth sign-off | `[~]` | Dylan appends the sign-off line in `phase8_revD_run_log.md` gate **OG-1**. The evidence record is already there waiting. | **2 min** |
| **G7** — rev-C verify items 6–7 | `[~]` | **Either** the powered at-machine metering session, **or** Dylan records an explicit waiver in `phase8_revD_run_log.md` accepting rev-C-validated defaults for this spin. | 2 min (waiver) |
| **G13** — mating + coding parts ordered | `[ ]` | Place the §B plug + coding-profile order (Part 3, Group 2 & 3). Ships **with** the boards. | same day |
| **G12 Part A** | `[x]` | closed 2026-07-26 | — |
| **G12 Part B** | `[ ]` | **Cannot close before upload.** It is the checklist you run *at* the JLC preview screen — Step 6 below. | — |
| G16 | `[ ]` | ✅ **Not a fab blocker** — explicitly *"blocks LIVE, not fab."* | — |
| G17 open items | `[ ]` | ✅ **Not a fab blocker** — FA-16 / FA-15 / Record-N are first-article gates that need physical boards. | — |

> ⚠️ **If you waive G7 you are accepting one specific thing:** a 24 VAC cam channel is
> *survivable but not usable* under r6 — 60 Hz gives 12 debounced edges per 100 ms against
> `CHATTER_MAX_CAM = 8`, so it faults continuously. **Closing that needs a firmware change or
> tapping the cams at the switches — not a board change.** The boards are still correct.
> What a waiver does *not* cover is the `FIELD_WET_V` rail budget: **N ≥ 1 reopens it**
> (16.8 mA peak/channel, zero bulk capacitance). That one is board-level. Scope TP4.

## STEP 1 — Verify package integrity

```bash
cd "C:/Users/Dylan DeYoung/wsl-lane-nodes" && python scripts/verify_fab_package.py kicad/fab_revD_2026-07-27_r10
```

⚠️ **Re-verify `source_board_sha256` against `manifest.json` immediately before upload.**
`kicad/revD/~wsl-phase8b-revD.kicad_pro.lck` is stale and **any KiCad save silently breaks it.**

Expected: 391 parts · 68 DNP · 323 placed · 323 JLC · 37 lines · **0 hand-solder** · DRC 0/0/0.

## STEP 2 — Ask JLC the open questions (send today, free)

Three quote lines lapse **Aug 13 GMT+8**, so there is time for one round trip.

> On quote `XOB2026072800482-12616613A`:
>
> 1. Is the quoted per-line lead time the date the **parts arrive at your factory**, or the
>    date the **finished assembled boards ship** to us?
> 2. If it is the parts date — what is the additional PCB fabrication + PCBA build time after
>    the last line lands, for **34 pcs of a 250 × 240 mm board with 323 placements** including
>    wave-soldered through-hole?
> 3. Do you begin the SMT pass on library-stock parts while a consigned or Global Sourcing line
>    is still inbound, or is the whole job held for a complete kit?
> 4. **Through-hole capacity:** this order carries **≈8,400 through-hole joints** — 1,520 ×
>    PC817B DIP-4, 228 × G5LE-14 relays, 380 × Phoenix terminal blocks. Can you confirm in
>    writing that wave/THT capacity is available for this quantity, and what it adds to the
>    build time?
> 5. For a **consigned** part, how many days between receiving our parcel and starting the
>    build (receiving, counting, incoming inspection)?
> 6. What is the earliest **ship date** you can commit to if we order this week, and what
>    expedited shipping options exist?

⚠️ **Question 4 is the important one.** Going zero-hand-solder moved every one of those joints
onto JLC. THT runs a separate, surcharged, capacity-limited path — it is a bigger schedule
threat than any stock line in this document.

## STEP 3 — Read the TRUE stock (⭐ the highest-value 60 seconds in this runbook)

**16 of 32 JLC-supplied lines have unreadable stock** — `jlcpcb.com/partdetail/<C#>` injects the
number via JavaScript, so it can't be read externally. LCSC's retail pool is a **different pool**
and disagreed by ~2× on three lines.

1. Log in to JLC → **SMT Assembly quote → BOM upload / parts-matching**
2. Upload `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv`, keyed on **C-number,
   never MPN**
3. That screen prints live assembly stock + an insufficient-stock flag for every line at once
4. **Screenshot it.** Pay closest attention to:
   `C17513` (1k) · `C116963` (relay) · `C5692981` (PC817B) · `C5443576` (Phoenix 6-pos) ·
   `C47023` (MCP23017) · `C17520` (2.2k) · `C89827` (10 µF) · `C17702767` (10 nF) · `C2933281` (10M)

⚠️ **"My Part Lib" is a bookmark, not an allocation. Nothing is reserved until the order is
placed AND paid.**

## STEP 4 — Finalise the consignment list, then buy

Part 3, Group 1 is the list as it stands from external data. **Step 3's screen is authoritative** —
add or remove lines from it. Buy everything with **+25 % overage**.

## STEP 5 — Open the consignment flow

Follow `phase8_jlc_consignment_runbook.md`. Get from JLC: the consignment order number, the
receiving address, the parcel labeling requirement, and the fee schedule (visible in-flow).

⚠️ `phase8_jlc_consignment_runbook.md:117` — *"Confirm they appear before releasing the board
order."* **Ask whether that blocks *placing* the order or only *releasing* it to the line.**
It is worth 1.5–2.5 weeks either way.

⚠️ **JLC disclaims quality liability on consigned stock.** That is what the overage is for.

## STEP 6 — Place the PCB + PCBA order

**Files:**
- PCB → `wsl-phase8b-revD-gerber-drill.zip`
- PCBA → `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv`
- PCBA → `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-cpl.csv`

**Service tier:** ⚠️ **Standard PCBA, not Economic.** `C7203002` (Pico) is the only line flagged
*"Standard Only"* — **that single part forces the whole order onto Standard.** Confirm it's priced
that way.

**Paste into the PCBA remark, verbatim:**

> Board is 250 × 240 mm. No process rails should be required. If any process rail IS added, it
> must be on the LEFT or RIGHT edge ONLY — never the top or bottom edge. Components sit within
> 5 mm of the top and bottom edges (nearest 0.52 mm at U45, 0.63 mm at U43) and depanelisation
> there would damage them. A left/right rail changes the outline; this is pre-approved.
>
> NO SUBSTITUTIONS on: C8678, C16338, C5692981, C47023, C880333, C13612, and all Phoenix parts
> (C480520, C480516, C5443576, C480549). C19184134 must ship as the RS-branded part, NOT
> Fujicon C18214278. C5692981 PC817B must be **B rank (CTR 130–260 %)** with the bin stated on
> the CoC / reel label.

⚠️ JLC confirmed 2026-07-27 they follow rail instructions **only if written in the PCBA remark.**
They did *not* confirm rails are unnecessary.

**G12 Part B — run this at the preview screen, before paying:**

- `[ ]` Preview reads **250 × 240 mm** (rev-D is 240 tall, not rev-C's 225)
- `[ ]` **Part rotation** on the four classes new in rev-D — `F1` (1206L020YR), `U46` (TCA4307
  VSSOP-8), `U47` (SRV05-4 SOT-23-6), `Q17–Q20` (2N7002LT1G). The CPL ships raw KiCad rotations
  and the exporter has **no rotation-correction table**.
- `[ ]` **A1 silkscreen photo** — confirm the Pico is the bare RP2040 module. ⚠️ **Do not quote
  "SC0915" to JLC** — their page lists the MFR part as "Raspberry Pi Pico" and nothing links that
  string to `C7203002`. *(JLC did confirm SC0915 in writing on 2026-07-27; pin the order to the
  C-number regardless.)*
- `[ ]` USB keep-out clear; row-39 bottom-edge copper (1.28 mm) acknowledged on **both** edges
- `[ ]` `C2933281` (10M) matched and in stock at the moment of upload
- `[ ]` `source_board_sha256` re-verified (Step 1)

## STEP 7 — Pay in the same session

Stock is only yours once payment clears. Re-read `C17520` (2.2k) and `C118873` (1N4148WS) in the
cart immediately before paying.

## STEP 8 — Incoming inspection when the boards land

- **PC817B CTR bin** on the reel label / CoC
- **Semtech marking** on SRV05-4 (clones share the marking)
- **Phoenix pitch — 3.5 mm, not 3.81 mm.** Wrong pitch is invisible until it won't seat.
- Then: **FA-16 before FA-1** (unpowered, 40/40, volts recorded — the only gate that catches a
  reversed `Dser`), then FA-15, then FA-1…FA-12.

---

# PART 3 — EVERYTHING BOUGHT OUTSIDE JLC

## GROUP 1 — Consignment ⭐ blocks the board order

*Bought by us, shipped to JLC, soldered by JLC. Quantities include ~25 % overage.*

| # | Part | LCSC ref | Order | Source | Why |
|---|---|---|---:|---|---|
| 1 | Phoenix **1843680** MCV 1,5/10-G-3,5 | C3585531 | **85** | Mouser (722) | J3 + J15 |
| 2 | Phoenix **1843729** MCV 1,5/14-G-3,5 | C3582595 | **43** | DigiKey (117) | J4 — GS quoted 75 bd |
| 3 | Phoenix **1843703** MCV 1,5/12-G-3,5 | C3019636 | **43** | DigiKey (2,139) | J5 |
| 4 | CNC Tech **3020-20-0100-00** 2×10 IDC | C17373551 | **43** | DigiKey (2,958) | J1 |
| 5 | TRACO **TMA 0505S** | C5454708 | **43** | DigiKey (5,964) | U45 — sole source of `FIELD_WET_V` |
| 6 | **PC817B — B RANK, bin on CoC** | C5692981 | **1,600** | — | ⚠️ rank unverifiable at distributor |
| 7 | 10 µF 16 V X5R 0805 | C89827 | **200** | DigiKey/Mouser | ⛔ JLC pool = **1** |
| 8 | 1 kΩ 1 % 0805 | C17513 | **5,000** (reel) | any | ⛔ LCSC 0 |
| 9 | 10 nF 50 V X7R 0805 | C17702767 | **100** | any | 90 in pool + MOQ-100 checkout trap |
| 10 | Omron **G5LE-14 5VDC** — exact, no -CF/-ASI | C116963 | **300** | — | JLC pool unreadable |
| 11 | **MCP23017-E/SO** (I²C, not MCP23S17) | C47023 | **130** | — | <1,000 in pool, single-source |
| 12 | **TCA4307DGKR** (recovery variant) | C880333 | **50** | — | lowest absolute stock in group |
| 13 | Phoenix **1843648** MCV 1,5/6-G-3,5 | C5443576 | **100** | LCSC/Newark | J13 + J16, thinnest Phoenix line |
| *opt* | 1N4148WS | C118873 | 4,000 | — | largest line in the build (88/bd) |
| *opt* | Raspberry Pi Pico (SC0915) | — | 40 | DigiKey/PiShop | zero LCSC backfill exists |

⚠️ **Substitution PROHIBITED** on 1, 2, 3, 5, 6, 10, 11, 12, 13 — and on `C8678` (SS34) and
`C16338` (2N7002LT1G) which stay with JLC. Phoenix 3,5 vs 3,81 mm pitch is the invisible trap.

## GROUP 2 — Board field plugs ⛔ #1 LONG POLE

⭐ **DECISION: FREE-ISSUE these to the harness shop.** The RFQ Tier 1 currently has the vendor
source 185 fitted plugs; Phoenix lead times swing **8–20 weeks**. Buying them ourselves removes
the vendor's purchasing department from the critical path and closes the §B double-buy question.

| # | Connector | Phoenix PN | Poles | ×32 lanes |
|---|---|---|---:|---:|
| B1 | J3 J_FAST_IN | **1840447** | 10 | 36 |
| **B2** | **J4 J_SLOW_IN_A** | **1840489** | 14 | **36** ⛔ |
| B3 | J5 J_SLOW_IN_B | **1840463** | 12 | 36 |
| B4 | J13 J_LAMP_LED | **1840405** | 6 | 36 |
| B5 | J14 J_SAFETY | **1840382** | 4 | 36 |
| B6 | J15 J_SLOW_IN_C | **1840447** *(different colour to B1)* | 10 | 32 |
| B7 | J16 J_EXT_I2C | **1840405** *(different colour to B4)* | 6 | 32 |

Totals: **1840447 × 68 · 1840489 × 36 · 1840463 × 36 · 1840405 × 68 · 1840382 × 36**

> ⛔ **1840489 IS THE #1 LONG POLE IN THE ENTIRE PROGRAMME.**
> DigiKey: lifecycle **ACTIVE**, **zero stock, 6-week manufacturer lead**, $16.42/1 · $13.34/10.
> Authorized distribution reads 0/on-order. RFQ `:114, :120-124` makes it **customer free-issue** —
> **the harness shop cannot build even the first article without it.**
> **Call TTI, Powell, Mouser, Newark, RS, Arrow, Phoenix direct — not just DigiKey.**
> Consider a 50 pc lifetime buy (~$670).
> ⛔ **Refuse the Amphenol ELXP14100 substitute** DigiKey offers — it breaks the CP-MSTB coding
> scheme and the mating contract with the board headers.
> *(Three rev-B-era files call this part discontinued; DigiKey says active with a lead. Confirm
> with a distributor before committing to a lifetime quantity — the justification changes.)*

## GROUP 3 — Coding + FA-8 (gate G13, ships WITH the boards)

| Item | PN | Qty | Notes |
|---|---|---:|---|
| Coding profiles | Phoenix **CP-MSTB 1734634** | ~25 stars (6/star) | Code J3@pole 1 · J15@pole 10 · J13@pole 1 · J16@pole 6 |
| Sacrificial MCV headers | mixed MCV 1,5-G-3,5 | ~10 | FA-8 step 1 proves the rib cut on a scrap part first |
| Harness band colours | — | — | J3 white · J15 yellow · J13 white · J16 blue |

> ⚠️ **The profile fits the PLUG** (or an inverted header) — **never** pressed into a standard
> G-3.5 header. On the header side you **remove the coding rib** at the matching pole.
> **136 irreversible cuts fleet-wide.** Prove on a sacrificial pair first.
> ⛔ **Loose uncoded plugs are a universal key** — an uncoded J13 lamp plug mates J16 and lands
> resistorless LEDs across 5 V while wedging I²C. Code and band-mark any spare stock before use.

## GROUP 4 — Compute (§C)

| # | Item | Part | Qty |
|---|---|---|---:|
| C1 | Raspberry Pi 4 Model B 4 GB | — | **18** ⚠️ re-price; last buy in this role hit 0 stock / 34-wk lead |
| C2 | microSD, industrial/endurance 32 GB | — | 20 |
| C3 | Pi heatsink | **low-profile** | 16 ⚠️ must clear the F-1019 HAT |
| C5 | Pi GPIO breakout | **CZH-LABS F-1019** | 18 · ships with its own metal carrier = the mount |
| C7 | Board breakout | **Electronics-Salon D-220** | **36** ⚠️ check one seller holds 36 |
| C8 | 20-way IDC ribbon, socket–socket **~150 mm** | — | 38 · ⚠️ SHORT is the requirement (I²C) |
| C9 | Pi power pigtail, USB-C to ferruled ~300 mm | — | 16 |
| C10 | USB composite capture dongle (UVC) | — | 18 |
| C11 | 75 Ω composite video coax ~4.7 m | — | 36 |

## GROUP 5 — Power (§D)

| # | Item | Part | Qty |
|---|---|---|---:|
| D1 | PoE splitter | PoE Texas **GBT-12V60W — INDOOR** (6 × 2.6 × 1.4 in) | 18 |
| D2 | DC-DC converter | Mean Well **DDR-60G-5** | 18 |
| D3 | Fuse terminal blocks | Konnect-It **KN-F10** | 96 (6/pair) |
| D4 | Fuses 5×20 mm | 3 A · 2 A fast ×2 · 4 A time-delay | 96 |
| D5 | Ground terminal blocks | Konnect-It **KN-G10** | 32 |
| D6 | Terminal markers | printed strip | 16 sets |
| D7 | **Isolated 12 V DC-DC**, ≥5 W, 12 V→12 V | — | 18 |

> ⛔ **TWO GROUND DOMAINS — DO NOT MERGE.** F6 → sensors runs off the **isolated** D7 because the
> sensors sink to `FIELD_GND`. Powering them from the ordinary 12 V rail bonds `FIELD_GND` to
> logic ground and **defeats the TMA-0505S isolation the entire input design rests on.**
> F5 → camera runs off ordinary 12 V (its return reaches logic ground through the dongle anyway).
> Harness colours: **Violet/Grey = isolated sensor pair · Brown/Pink = camera pair** (W50–W53).

## GROUP 6 — Enclosure and DIN (§E)

⚠️ **§E in `phase8_backplate_BOM.md` is STALE.** It still lists the Saginaw SCE-36EL3008LP and
½″ plywood at 686 × 838 mm. The current design is a **custom plastic box + ¾″ plywood panel
`PANEL-W2`, 1100 × 570 × 19.05 mm** — see `phase8_custom_panel_layout_2026-07-26.md`.

| # | Item | Spec | Qty |
|---|---|---|---:|
| E1 | DIN rail 35 mm slotted | AD DN-R35S1-2 | 5 packs (~10 m) |
| E2 | End brackets | Konnect-It KN-EB3 | 64 |
| E3 | Wire duct + cover | 1×2 in slotted PVC, 2 m | 8 sticks |
| E4 | **Enclosure** | custom plastic box | 16 (+1) |
| E5 | **Backplate** | **¾″ plywood, 1100 × 570 mm** | 16 → **~5 sheets (4×8)** · primer + 2 coats both sides & edges |
| E6 | Backplate mounting | per box | 16 sets |
| E7 | Cable glands | M20 nylon IP68 | 144 (+20) |
| E8 | Breather plug | Gore-type M12 | 16 (optional) |
| A5 | Board standoffs | **M3 × 30** | 8/board → ~280 |

> ⚠️ **Gland sizing, twice corrected:**
> **G9 (Cat6) = M16** — terminate the RJ45 *inside* the enclosure so only bare cable passes.
> An M25 gapes around a 5.5–6.5 mm jacket and the IP rating is fiction.
> **G10 (camera coax) is specified M16 and is probably too small** — it must pass **two** moulded
> RCA plugs at ~9–10 mm each. Either upsize it or field-terminate at the box. **Decide before
> drilling the gland wall.**

## GROUP 7 — Consumables (§F)

| # | Item | Qty |
|---|---|---|
| F1 | Hook-up wire 22 AWG UL1007, assorted | ~80 m |
| F2 | Hook-up wire 18 AWG UL1015 | ~50 m |
| F3 | Ferrules 0.34 mm² insulated | 1000-pk |
| F4 | Ferrules 0.75 mm² insulated | 500-pk |
| F5 | Adhesive tie mounts | 200 · within 50 mm of every MCV plug row |
| F6 | Cable ties 4 in | 500 |
| F7 | **Wire-map cards**, printed + laminated | 16 · **MANDATORY, taped inside every door** |
| F8 | Label stock, heat-shrink / vinyl | — |

## GROUP 8 — Off-plate (§G)

| # | Item | Qty | Status |
|---|---|---:|---|
| G1 | **Field harness assembly** | **34** | ⛔ RFQ issued to MiniProto only. **~12 wk from PO. PO not placed.** Call Prairie Electric, Falconer, and every shop you can. |
| G2 | Interposer C1 housing (34-pos) — **we supply MALE/pins** | 36 | AMP **1-201357-1** (AMF `000025144`) |
| G3 | Interposer C2A housing (50-pos) — **we supply FEMALE/sockets** | 36 | AMP **201358-1** (AMF `000028409`) |
| G4a | **Pin** contacts `.062` (size 16) | ~30/lane +25 % | AMF `760011197` |
| G4b | **Socket** contacts `.062` (size 16) | ~30/lane +25 % | AMF `760019201` |
| G5 | Crimp + extraction tooling | 2 sets | size-16 crimper w/ positioner + AMF `030 004 031` |
| G5a | Guide pins/sockets, spring clips, strain clamps | 32 sets | `000028442` · `000028441` · `000029013` · `000029093` (C1) / `000029896` (C2A) |
| G6 | PoE head-end | 18 injectors **or** 2 × 16-port bt switch | TL-POE170S ~$50 |
| G7 | **Cat6 solid-core, 1000 ft box** | 1 box | cut list below |
| G8 | J14 Stop/CIS interface | 32 | ⛔ **DECISION OPEN** ~$25/lane |
| G9 | **Ball-detect sensors** | **72** | Datasensing **SSC/AN-0C** ~$64 · Rankin USA · ⚠️ **fleet lead time UNKNOWN, not ordered** |

> ⛔ **Retroreflective or through-beam ONLY — never diffuse.** A bowling ball is dark and glossy.
> ⚠️ **G2/G3 housings: AMP M Series is winding down** (Mouser already flags it obsolete). The
> **primary plan is to harvest from the 32 retired OEM control boxes** — zero lead time, zero ID
> risk. Contacts and tooling are commodity and in production; they need no lifetime buy.
> ⚠️ **G2–G5 are BLOCKED on ~20 minutes of measuring at the machine.**

### Cat6 cut list — measured on site 2026-07-27

Switch sits between lanes 21 and 22. Path to the first Pi in each direction = **12 ft**
(already includes the drop and its slack). Each subsequent Pi **+10 ft**.

**Cut = 12 + 10(N−1) ft. Nothing is added.**

| Pi from switch | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| **Cut (ft)** | **12** | **22** | **32** | **42** | **52** | **62** | **72** | **82** |

×2 directions = **752 ft**. A 1000 ft box leaves ~250 ft spare.

- ⚠️ **SOLID core, not stranded.** Plugs must be rated for solid core. Crimper + tester required.
- PoE is not a constraint: 802.3bt reaches 328 ft; longest run here is 82 ft.
- ⭐ **Cut, terminate and TEST the first cable before cutting the other fifteen.**
- **Label both ends as you pull.** Sixteen identical grey cables is where an afternoon disappears.
- ⚠️ **Confirm the split before cutting the two longest.** 8-per-direction gives the table above.
  If lanes number 1–32 sequentially, pair 11 straddles the switch and the split is 10/5/1 —
  which adds 92 ft and 102 ft runs. Same box either way.

---

# APPENDIX — ORDER OF OPERATIONS THIS WEEK

| # | Action | Blocking? |
|---|---|---|
| 1 | **Hunt Phoenix 1840489** — TTI, Powell, Mouser, Newark, RS, Arrow, Phoenix direct | ⛔ #1 long pole; blocks harness FA |
| 2 | **Place the harness PO** (G13) — and get competing quotes | ⛔ ~12 wk clock hasn't started |
| 3 | **Email JLC the six questions** (Step 2) | free; 3 quote lines lapse Aug 13 |
| 4 | **Sign G8 + G7** in `phase8_revD_run_log.md` | ⛔ blocks the fab order · ~5 min |
| 5 | **Upload BOM to parts-matching**, screenshot the true stock (Step 3) | ⛔ sets the final consign list |
| 6 | **Buy Group 1** (consignment) and **Group 2** (plugs) | ⛔ |
| 7 | **Powered session: scope one cam microswitch** — AC or DC | ⚠️ only thing that can invalidate 34 boards |
| 8 | **Run the FA-9 bench pre-check** — ~1 h, zero parts, board already on the bench | ⭐ highest value per minute |
| 9 | **Order G9 sensors (72)** — lead time unknown | ⚠️ potential hidden long pole |
| 10 | **Caliper the F-1019 carrier** — outline + flange holes | gates the plywood drilling schedule |
| 11 | **20 min measuring the C1/C2A interposer** | unblocks G2–G5 |
| 12 | Re-price and order **18 × Pi 4B** | ⚠️ 34-wk lead last time |
