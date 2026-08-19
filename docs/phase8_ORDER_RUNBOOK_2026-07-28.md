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
cd "C:/Users/Dylan DeYoung/wsl-lane-nodes" && py -3 scripts/verify_fab_package.py kicad/fab_revD_2026-07-27_r10
```

*(Script written 2026-07-28 — verifies all 46 manifest hashes, the live board/netlist
hashes, the 391/68/323/323/37/0 counts, BOM↔CPL refdes equality, and the 0/0/0 DRC
report. Always `py -3`, never `python` — the bare `python` is the broken MS-Store stub.)*

Also re-verify the rev-C sacred snapshot (checklist G6's standing pre-order requirement):

```bash
cd "C:/Users/Dylan DeYoung/wsl-lane-nodes" && py -3 scripts/verify_revC_snapshot.py --compare-checkout
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
> 4. **Through-hole capacity:** this order carries **≈9,900 through-hole joints across the
>    34 boards** — 1,360 × PC817B DIP-4, 204 × G5LE-14 relays, 476 × Phoenix terminal
>    blocks (14 bodies / 77 pins per board), 34 × 2×10 IDC, 34 × SIP DC/DC. Can you confirm
>    in writing that wave/THT capacity is available for this quantity, and what it adds to
>    the build time? *(figures corrected 2026-07-28 to the 34-board placement counts — the
>    old text mixed in 38-set purchase quantities)*
> 5. For a **consigned** part, how many days between receiving our parcel and starting the
>    build (receiving, counting, incoming inspection)?
> 6. What is the earliest **ship date** you can commit to if we order this week, and what
>    expedited shipping options exist?

⚠️ **Question 4 is the important one.** Going zero-hand-solder moved every one of those joints
onto JLC. THT runs a separate, surcharged, capacity-limited path — it is a bigger schedule
threat than any stock line in this document.

## STEP 3 — Read the TRUE stock (⭐ the highest-value 60 seconds in this runbook)

Roughly **half of the ~24 lines JLC would supply** (37 upload lines − 13 consigned) have
unreadable stock — `jlcpcb.com/partdetail/<C#>` injects the number via JavaScript, so it can't
be read externally. LCSC's retail pool is a **different pool** and disagreed by ~2× on three lines.

1. Log in to JLC → **SMT Assembly quote → BOM upload / parts-matching**
2. Upload `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv`, keyed on **C-number,
   never MPN**
3. That screen prints live assembly stock + an insufficient-stock flag for every line at once
4. **Screenshot it.** Pay closest attention to:
   `C17513` (1k) · `C116963` (relay) · `C5692981` (PC817B) · `C5443576` (Phoenix 6-pos) ·
   `C47023` (MCP23017) · `C17520` (2.2k) · `C89827` (10 µF) · `C17702767` (10 nF) ·
   `C2933281` (10M) · `C17713` (47k — 40/bd, one of only three 1,500-piece-scale lines) ·
   `C118873` (1N4148WS — 88/bd, the largest line in the build)

⚠️ **"My Part Lib" is a bookmark, not an allocation. Nothing is reserved until the order is
placed AND paid.**

## STEP 4 — Finalise the consignment list, then buy

Part 3, Group 1 is the list as it stands from external data. **Step 3's screen is authoritative** —
add or remove lines from it. Buy everything with **+25 % overage**.

> ✅ **STEP 3 EXECUTED 2026-07-29** — matching export archived at
> `docs/phase8_jlc_bom_matching_2026-07-29.xlsx` (JLC download 10:34, qty-50 basis).
> **37/37 lines matched by C-number, zero warnings, part-lock held.** Result:
> - **CONSIGN (6 lines, stock 0/short):** 1843680 (0) · 1843729 (0) · 1843703 (3) ·
>   3020-20-0100-00 (0) · **TMA 0505S (16 — consign ALL, no-mixing rule)** · 10 µF C89827 (1).
>   Buy at the Group 1 quantities: 95 / 48 / 48 / 48 / 48 / 200.
> - **DROP from consign (JLC covered the full need):** C5443576 **100 ✓ → stays a JLC line,
>   Group 1 row 13 is DEAD** (keep it in the no-sub remark) · C116963 relay 300 ✓ ·
>   C47023 150 ✓ · C17513 610 ✓ · C2933281 160 ✓ · C880333 50 ✓ · C17702767 56 ✓ ·
>   Pico 50 ✓ · C118873 4,406 ✓ · C17713 2,010 ✓.
> - **PC817B C5692981: 2,003 ✓ — DECISION (Dylan):** JLC can supply the whole build.
>   Consigning never resolved the B-bin question (no distributor states it either).
>   Recommended: JLC-supply, drop the 1,900-pc consign buy, enforce B-rank via the remark +
>   reel-label check at incoming + FA-9. Consign only for chain-of-custody.
> - ⚠️ Covered = allocated-at-match, not pool depth. **Re-match if >24 h pass before payment.**
> - ⚠️ The 2026-07-29 session ran at qty 50 — re-quote at **34** before paying.

> ✅ **2026-07-29 FINAL ORDER DECISIONS (supersede the two lines above where they conflict):**
> - **QTY = 50 assembled boards** (Dylan — JLC custom-qty constraint; 16 assembled spares
>   beyond the G15 fleet 34. Note next to the OG-1 signature in the run log).
> - **PC817B = JLC-SUPPLIED.** The 1,900-pc consign buy is DEAD. Enforcement = B-rank/CoC
>   demand in the PCBA remark + reel-label check at incoming (Step 8) + FA-9 per channel.
> - **Consignment = exactly 6 lines**, scaled to 50 boards +25 %:
>   **1843680 ×125 (Mouser)** · **1843729 ×65 (DK)** · **1843703 ×65** ·
>   **3020-20-0100-00 ×65** · **TMA 0505S ×65** (consign ALL — no-mixing rule; JLC's 16
>   are unusable alongside ours) · **10 µF C89827 ×200**. Confirm JLC's attrition
>   requirement per line BEFORE the parcel ships (consignment runbook §3.3).
> - **J14 plug 1840382 = 72** (the harness BOM's +1-spare-per-lane rule stands; Group 2 note closed).
> - **G10 camera entry = TWO M20 glands per pair, one per coax** (passes a moulded RCA,
>   seals on the cable, zero field termination). **E7 becomes 96 (+12) M20 + 80 (+10) M16.**
> - **Lead-time strategy — ANSWERED by JLC chat 2026-07-29 (Mitchell Chen):** ⛔ **NO
>   pay-now.** *"We do not support such process to produce the PCB firstly … wait until the
>   part in stock then to place the PCBA order later."* The consignment parcel IS the
>   critical path; fab starts only after receiving. Consequences: buy + ship the 6 lines
>   IMMEDIATELY; **re-match the BOM at payment** — the tight covered lines (C880333 = 50
>   exact · C47023 = 150 · C2933281 = 160) are unprotected during the ~2-wk wait; if one
>   drains, buy it at a distributor same-day and send a small second consignment parcel.
>   Consignment declarations submitted 2026-07-29 (6 lines; TRACO matched C5454708 — no
>   email-approval gate; attrition shown in-UI: 0 on all THT lines, min-20+6 on C89827).
> - Production-file approval rule: accept 250×240 (no rails) or **260×240** (left/right
>   rails); **REJECT 250×250** (top/bottom rails — component damage at U45/U43/row-39).

## STEP 5 — Open the consignment flow

Follow `phase8_jlc_consignment_runbook.md` — **§3–§5 flow mechanics ONLY.** Its §1 decision
gates (GS-first) and §2 quantity table (5 lines at 72/38/38/38/38) are SUPERSEDED by Part 1
decisions 2–3 and the Group 1 table above. A literal follower of that doc buys 5 lines at the
old quantities and under-declares 8 lines — JLC then can't kit the build.
⭐ Also: its "TRACO has no JLC library entry" premise is stale — **C5454708 exists.** Try
matching it in Parts Manager first; only fall back to the direct-consign/email-approval path
if it doesn't match. That skips the review round-trip the doc plans its schedule around.

Get from JLC: the consignment order number, the receiving address, the parcel labeling
requirement, and the fee schedule (visible in-flow).

⚠️ `phase8_jlc_consignment_runbook.md:117` — *"Confirm they appear before releasing the board
order."* **Ask whether that blocks *placing* the order or only *releasing* it to the line.**
It is worth 1.5–2.5 weeks either way.

⚠️ **JLC disclaims quality liability on consigned stock.** That is what the overage is for.

> 🔄 **2026-07-30 SHIPMENT STATE:** declaration WBG2026073100878 submitted, 6/6 lines
> "Reviewing". **SHIP-TO CHANGED — Hong Kong, NOT Zhuhai:** Rebecca (12616613A),
> +852 5421 0550, Block 1 Room 3B, 3 Hung Cheung Road, Tuen Mun, New Territories, Hong Kong
> (banner: "shipping address and customs prepayment rules have changed"). Photograph EVERY
> bag label (PN + COO) before sealing — stated requirement. Combined invoice PDF =
> `Downloads/JLC_consignment_invoices_DK129986470_Mouser91667952.pdf`.
> ✅ **CLAUSE 1 RESOLVED — governed by Dorae's LOGGED 2026-07-27 written reply** (not a fresh
> chat answer; a re-confirmation sat unanswered in chat 2026-07-30 and is NOT a ship blocker):
> the rule is SAME-part source mixing only — "for different parts, you can use JLC parts for
> part A and consigned parts for part B." Our 24-JLC + 6-consigned structure is VALID.
> Residual worst case surfaces at the order screen BEFORE payment (flip the 24 JLC lines to
> Global Sourcing); the 6 consigned lines are needed under any structure → parcel risk zero. ✅ TMA date code verified
> on the cans: **1023 (Oct 2023)** — the packlist's "Jun-2010" was a data artifact; clause-5
> concern closed. **PARCEL CLEARED TO SHIP** (photos of all 6 bag labels kept in a folder
> named WBG2026073100878 — produced only if JLC/customs asks).
> ⚠️ Still open, unrelated to the box: DigiKey code-89 decline ($6,394.99) — deadline
> ~Jul 31 10 PM.
> ✅ **2026-08-01:** PUSHED to origin (994ce79..1452985). **OG-1/G8 + G7 SIGNED** — all fab
> gates closed. DigiKey code-89 RESOLVED. ORDERED: DK add-on (M3DDA-2006J ×50 secured + fans
> + vents + patches + loom + mounts/ties + ribbon 25 ft + grey/violet/brown stranded) ·
> **Calrad 55-877-20 ×36** · **Siemon Z-PLUG + Z-TOOL**. Amazon remainder still open, NOW
> +**1,000 ft Cat6 (attic runs to the overhead displays — forgotten scope**; CMR/riser
> jacket for attic; check Z-plug count + PoE/switch PORT count cover the display drops too).
> Still homeless: VC500 ×1 · uxcell pigtails ×20 · Aim Dynamics glands (status unconfirmed) ·
> Zoro brass · pink spool · 1 MΩ 1 W ×25.
> ⚠️ **2026-08-07 — PACKING ERROR, contained:** JLC HK found TWO undeclared bags in the
> parcel: **1840463 ×40** (Mouser, J5 field plug, $561) and **1840405 ×76** (DK, J13/J16
> plug, $434) — the keep-at-home free-issue stock, boxed by mistake. Caught in HK BEFORE
> mainland customs → no declaration issue (the 6 declared lines match the invoice exactly).
> Asked Lyvia: process the 6 lines without delay; hold the 2 stray bags as customer property
> and return them WITH the PCBA order shipment (fallback: SF return at our cost). Impact
> ~zero: MiniProto self-sources J5/J13 (our stock was fallback only; both PNs re-buyable),
> J16 plugs not needed until commissioning ≈ board-arrival time. Home stock ledger until
> return: 1840447 ×76 · 1840489 ×50 (inbound) · 1840382 ×72 · coding stars ×30 — **J5/J13/J16
> plug stock is ZERO at home.**
> 🔄 **2026-08-19 — stray-bag return in motion:** JLC cannot ride-along loose parts with the
> PCBA shipment (Jax). Return via SF Express, receiver pays; details + HS codes + invoices
> sent to Lyvia (1840463→8536.69.4040, 1840405→8536.90.4000, re-import as HTS 9801.00.10
> returned goods, ~$995 value vs ~$50-100 freight). ⚠️ Six declared lines STILL not
> confirmed received as of Aug 19 (delivered Aug 5!) — confirmation requested in the same
> email; **escalate to Lorraine (lorraine@jlcpcb.com) with the FedEx POD if not resolved
> within ~2 business days — the PCBA order is blocked on this.**
> 📦 **2026-07-31:** parcel SHIPPED — FedEx **875182889683** to the Tuen Mun address; JLC
> declaration still "Reviewing" so tracking not yet attachable (ping if not cleared by
> ~Aug 3). AD + DK main + Mouser orders ARRIVED. Amazon/GPT basket + DK add-on
> (⚠️ M3DDA-2006J is vanishing EOL stock) + VC500 sample + Siemon Z-PLUG+Z-TOOL (verify
> solid-23AWG variant) NOT yet ordered. Plywood: cut+prime today, DRILLING gated on the
> F-1019 caliper (CZH inbound). Harness shop quiet on Rev 2 (nudge Mon; quote to Aug 26).

## STEP 6 — Place the PCB + PCBA order

**Files:**
- PCB → `wsl-phase8b-revD-gerber-drill.zip`
- PCBA BOM → `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv`
- PCBA CPL → `assembly/wsl-phase8b-revD-jlc-standard-pcba-cpl.csv`

⚠️ **CPL filename corrected 2026-07-28** — there is NO `…-upload-cpl.csv` in the package.
⛔ **Do NOT grab `wsl-phase8b-revD-cpl.csv`** (the similarly-named file next to it) — that is
the raw KiCad export in a different column format. The JLC one is the
`…-jlc-standard-pcba-cpl.csv` with `Designator / Mid X / Mid Y / Layer / Rotation` headers.

**Service tier:** ⚠️ **Standard PCBA, not Economic.** `C7203002` (Pico) is the only line flagged
*"Standard Only"* — **that single part forces the whole order onto Standard.** Confirm it's priced
that way.

**Paste into the PCBA remark, verbatim:**

> Board is 250 × 240 mm. No process rails should be required. If any process rail IS added, it
> must be on the LEFT or RIGHT edge ONLY — never the top or bottom edge. Components sit within
> 5 mm of the top and bottom edges (nearest 0.52 mm at U45, 0.63 mm at U43) and depanelisation
> there would damage them. A left/right rail changes the outline; this is pre-approved.
>
> NO SUBSTITUTIONS on: C8678, C16338, C5692981, C47023, C880333, C13612, C207035,
> C116963 (Omron G5LE-14 5VDC — exact coil voltage, no -CF/-ASI suffix), and every Phoenix
> line on this order whether JLC-supplied or consigned (C480520, C480516, C5443576, C480549,
> C3585531, C3582595, C3019636). C19184134 must ship as the RS-branded part, NOT
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
  reversed `Dser`), then FA-15, then FA-1…FA-14 per the pack (FA-13 Stop-interlock P0 and
  FA-14 mains/PE are at-machine gates — later in sequence, not absent).

---

# PART 3 — EVERYTHING BOUGHT OUTSIDE JLC

## GROUP 1 — Consignment ⭐ blocks the board order

*Bought by us, shipped to JLC, soldered by JLC. Quantities include ~25 % overage.*

> ⚠️ **Quantities recomputed 2026-07-28.** The original table was silently computed on a
> 34-board ×1.25 basis; decision #4 is **38 sets, then +25 %** on consigned lines. Every line
> below is now `ceil(per-board × 38 × 1.25)` (rounded up to sane pack sizes). The worst
> offender was PC817B: 1,600 was only +5.3 % over the 1,520-piece 38-set need — on the one
> line whose CTR-bin rejection risk is the program's #2 accepted risk.

| # | Part | LCSC ref | /bd | Order | Source | Why |
|---|---|---|---:|---:|---|---|
| 1 | Phoenix **1843680** MCV 1,5/10-G-3,5 | C3585531 | 2 | **95** | Mouser (722) | J3 + J15 |
| 2 | Phoenix **1843729** MCV 1,5/14-G-3,5 | C3582595 | 1 | **48** | DigiKey (117) | J4 — GS quoted 75 bd |
| 3 | Phoenix **1843703** MCV 1,5/12-G-3,5 | C3019636 | 1 | **48** | DigiKey (2,139) | J5 |
| 4 | CNC Tech **3020-20-0100-00** 2×10 IDC | C17373551 | 1 | **48** | DigiKey (2,958) | J1 |
| 5 | TRACO **TMA 0505S** | C5454708 | 1 | **48** | DigiKey (5,964) | U45 — sole source of `FIELD_WET_V` |
| 6 | **PC817B — B RANK, bin on CoC** | C5692981 | 40 | **1,900** | — | ⚠️ rank unverifiable at distributor |
| 7 | 10 µF 16 V X5R 0805 | C89827 | 1 | **200** | DigiKey/Mouser | ⛔ JLC pool = **1** |
| 8 | 1 kΩ 1 % 0805 | C17513 | 12 | **5,000** (reel) | any | ⛔ LCSC 0 |
| 9 | 10 nF 50 V X7R 0805 | C17702767 | 1 | **100** | any | 90 in pool + MOQ-100 trap; also the Cflt-fast field-stuff part (DNP, ours) |
| 10 | Omron **G5LE-14 5VDC** — exact, no -CF/-ASI | C116963 | 6 | **300** | — | JLC pool unreadable (need+25 % = 285) |
| 11 | **MCP23017-E/SO** (I²C, not MCP23S17) | C47023 | 3 | **145** | — | <1,000 in pool, single-source |
| 12 | **TCA4307DGKR** (recovery variant) | C880333 | 1 | **50** | — | lowest absolute stock in group |
| 13 | Phoenix **1843648** MCV 1,5/6-G-3,5 | C5443576 | 2 | **100** | LCSC/Newark | J13 + J16 — ⚠️ see the dual-status note below |
| *opt* | 1N4148WS | C118873 | 88 | 4,200 | — | largest line in the build |
| *opt* | Raspberry Pi Pico (SC0915) | — | 1 | 48 | DigiKey/PiShop | zero LCSC backfill exists |

> ⚠️ **C5443576 dual status — resolve at Step 3, do not do both.** It is simultaneously a
> Group 1 consign line here AND in the Step 6 no-substitution remark as a JLC-supplied line.
> JLC **cannot mix their stock and consigned stock for the same part** (confirmed 2026-07-27).
> At the parts-matching screen: if JLC assembly stock covers 76 + attrition → leave it a JLC
> line and DROP this row; if not → consign it and strike it from the JLC no-sub remark.

⚠️ **Substitution PROHIBITED** on 1, 2, 3, 5, 6, 10, 11, 12, 13 — and on `C8678` (SS34) and
`C16338` (2N7002LT1G) which stay with JLC. Phoenix 3,5 vs 3,81 mm pitch is the invisible trap.

## GROUP 2 — Board field plugs ⛔ #1 LONG POLE

⭐ **DECISION: FREE-ISSUE these to the harness shop.** The RFQ Tier 1 currently has the vendor
source **148** fitted plugs (4 PNs × 37 — 1840489 is already customer free-issue in the RFQ);
Phoenix lead times swing **8–20 weeks**. Buying them ourselves removes the vendor's purchasing
department from the critical path and closes the §B double-buy question.

> ⚠️ **Quantities raised 2026-07-28.** The old 36-per-type figure couldn't even cover the
> RFQ's own commitment of 34 assemblies + 3 spare plug sets = **37 per type**, before the
> vendor's scrap buffer. J15/J16 at 32 gave the two spare boards zero plugs. New basis:
> harness-carried types 40 (37 + buffer), board-spare types 36 (34 + 2).

| # | Connector | Phoenix PN | Poles | Buy |
|---|---|---|---:|---:|
| B1 | J3 J_FAST_IN | **1840447** | 10 | 40 |
| **B2** | **J4 J_SLOW_IN_A** | **1840489** | 14 | **40** ⛔ (50 if the lifetime buy lands) |
| B3 | J5 J_SLOW_IN_B | **1840463** | 12 | 40 |
| B4 | J13 J_LAMP_LED | **1840405** | 6 | 40 |
| B5 | J14 J_SAFETY | **1840382** | 4 | 40 ⚠️ see J14 note |
| B6 | J15 J_SLOW_IN_C | **1840447** *(different colour to B1)* | 10 | 36 |
| B7 | J16 J_EXT_I2C | **1840405** *(different colour to B4)* | 6 | 36 |

Totals: **1840447 × 76 · 1840489 × 40 (or 50) · 1840463 × 40 · 1840405 × 76 · 1840382 × 40**

> ⚠️ **J14 open question (decide before the parcel ships):** the fleet harness BOM carries a
> **+1 spare J14 plug per lane** rule (2/lane → ~64+ fleet-wide). Either that rule stands —
> then buy ~72 of 1840382 — or it was a lane-21 pilot artifact — then strike it from the
> harness BOM note. The two documents must not disagree on the safety-loop plug.

> ✅ **2026-07-29 SOURCING HUNT (4-agent, verified-on-page unless noted):**
> - **1840489 path found:** part is **ACTIVE** (the "discontinued" note traces to a UK
>   retailer's own end-of-line, not Phoenix). Authorized shelf stock today = 1 pc (RS
>   Americas $16.42) + 4 (Quest). **BEST: Master Electronics / OnlineComponents.com —
>   100 pcs ON ORDER, "can ship 8/12/26" (~2 wk), $16.26 @ 50 — place a 50-pc order
>   against that inflow NOW**, plus a cancellable Newark backorder as hedge (deliveries
>   from 9/3/26, $14.46 @ 50). Mouser/TTI/Sager/TME/Farnell all 0. Brokers if desperate:
>   Vyrian claims 8,862 (RFQ, unverified); ⛔ avoid Unikey's 24 @ $4.32 (far under market
>   — re-mark risk). eBay: zero.
> - **C8 IDC ribbon:** buy **3M M3DDA-2006J** (2×10, 152.4 mm, keyed, socket–socket) —
>   DigiKey 1,706 in stock @ $5.01/50 — ⚠️ *Discontinued-at-DigiKey shelf stock, no
>   restock: buy 50 NOW (~$250).* Renewable repair path: CNC Tech 3030-20-0103-00
>   sockets ×100 ($44) + 3M 3365/20 ribbon 17 ft ($20). Wurth 6876xx is 0.5 mm FFC —
>   wrong class; Samtec HCSD is build-to-order; every other pre-made 150 mm jumper is EOL.
> - **G9 sensor spares:** **AutomationDirect ProSense F18RP-0N-0E** — $41, 35 in stock,
>   M18 **polarized** retro (polarized matters on a glossy ball), NPN, light/dark-on
>   selectable (set DARK-ON to mimic DIELL), M12 QD (buy cables) + **RL110-1 reflector
>   $2.25 (547 stock — Micro Detectors, same family as the existing heads)**. Skip the
>   $11 Baomain tier (non-polarized, IP unstated).
> - **KN pricing mystery SOLVED — those were PACK prices on automationdirect.com, no
>   scalping:** KN-F10 = $156/**pack of 50** ($3.12 ea, 43 packs avail) → buy 2 packs;
>   KN-EB3 = $57/**pack of 100** ($0.57 ea) → 1 pack + 1× KN-EB3-10 ($7.50). ~$376 total.
>
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
| Coding profiles | Phoenix **CP-MSTB 1734634** | **28–30 stars** (6/star) | Code J3@pole 1 · J15@pole 10 · J13@pole 1 · J16@pole 6 — 136+ profiles needed; the old ~25-star figure left ~10 % margin on an irreversible press, and FA-8 practice consumes profiles |
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
| C7 | Board breakout | **Electronics-Salon MD-D220T-1** ⛔ exact variant — the T carrier is removable; bare "D-220"/-1/S variants lose the mount flexibility PANEL-W2 depends on | **36** ⚠️ check one seller holds 36 |
| C8 | 20-way IDC ribbon, socket–socket **~150 mm** | — | 38 · ⚠️ SHORT is the requirement (I²C) · also satisfies the checklist G13 "J1 mate" line — no separate 3030-20-0102-00 socket buy |
| C9 | Pi power pigtail, USB-C to ferruled **~600 mm** *(was 300 — F4 sits at x 256, the Pi USB-C face at x ~560; 300 mm cannot reach on PANEL-W2)* | — | 16 |
| C10 | USB composite capture dongle (UVC) | — | 18 |
| C11 | 75 Ω composite video coax ~4.7 m | — | 36 |

## GROUP 5 — Power (§D)

| # | Item | Part | Qty |
|---|---|---|---:|
| D1 | PoE splitter | PoE Texas **GBT-12V60W — INDOOR** (6 × 2.6 × 1.4 in) | 18 |
| D2 | DC-DC converter | Mean Well **DDR-60G-5** | 18 |
| D3 | Fuse terminal blocks | Konnect-It **KN-F10** | 96 (6/pair) |
| D4 | Fuses 5×20 mm | 3 A · 2 A fast ×2 · 4 A time-delay | 96 — ⚠️ F5/F6 ratings are sized at commissioning; buy an assortment so 2 of 6 positions aren't left empty |
| D5 | **5 V return bus** | ⛔ **NOT KN-G10** — **4 × insulated feed-through (KN-T/KN-S class) + jumper comb per pair** | **64 blocks (+8) + 16 combs** |
| D6 | Terminal markers | printed strip | 16 sets |
| D7 | **Isolated 12 V DC-DC** | **Mean Well DDR-15G-12** ⛔ exact — 4 kVdc I/O, 0–1.25 A load range (no dummy load), same 90 × 54.5 envelope as the DDR-60G-5. A generic "≥5 W isolated" buy risks envelope, isolation, or a minimum-load requirement | 18 |

> ⛔ **TWO GROUND DOMAINS — DO NOT MERGE.** F6 → sensors runs off the **isolated** D7 because the
> sensors sink to `FIELD_GND`. Powering them from the ordinary 12 V rail bonds `FIELD_GND` to
> logic ground and **defeats the TMA-0505S isolation the entire input design rests on.**
> The D5 change above is the same rule in copper: green/yellow PE-class KN-G10 blocks on the
> logic 0 V bus invite an earth bond (PANEL-W2 M-04). There is no earth job left in this box.
> F5 → camera runs off ordinary 12 V (its return reaches logic ground through the dongle anyway).
> Harness colours: **Violet/Grey = isolated sensor pair · Brown/Pink = camera pair** (W50–W53).

## GROUP 6 — Enclosure and DIN (§E)

⚠️ **§E in `phase8_backplate_BOM.md` is STALE.** It still lists the Saginaw SCE-36EL3008LP and
½″ plywood at 686 × 838 mm. The current design is a **custom plastic box + ¾″ plywood panel
`PANEL-W2`, 1100 × 570 × 19.05 mm** — see `phase8_custom_panel_layout_2026-07-26.md`.

| # | Item | Spec | Qty |
|---|---|---|---:|
| E1 | DIN rail 35 mm slotted | AD DN-R35S1-2 | 4 packs (~450 mm/pair, 3 segments) |
| E2 | End brackets | Konnect-It KN-EB3 | **96 (+8)** — PANEL-W2 has THREE rail segments/pair (R1a, R1b, vertical R2) = 6/pair, not 4 |
| E3 | Wire duct + cover | 1×2 in slotted PVC, 2 m — **cover PN is a separate line item, order it** | 9 sticks |
| E4 | **Enclosure** | custom plastic box | 16 (+1) |
| E5 | **Backplate** | **¾″ plywood, 1100 × 570 mm** | 16 → **~5 sheets (4×8)** · primer + 2 coats both sides & edges |
| E6 | Backplate mounting | per box — ⚠️ the old "4 collar studs" note is DEAD (PANEL-W2 6.1: no collar studs exist) | 16 sets |
| E7 | Cable glands | ⚠️ **SIZE MIX, not all-M20:** **64 (+8) × M20 + 96 (+12) × M16** nylon IP68 · zero M25 *(G9 Cat6 = M16, terminate RJ45 inside; G10 camera = M16 spec but probably too small for two moulded RCA plugs — decide upsize vs field-terminate BEFORE drilling)* | 160 (+20) |
| E8 | Breather plug | Gore-type M12 — **REQUIRED** for the sealed plastic box, not optional | 16 |
| E12 | **Internal circulation fan** | 40 × 40 × 10 mm, **5 V, ball bearing**, ~0.7 W, continuous low RPM — nothing may depend on it | 16 (+2) |
| E13 | **Lacing-channel duct** | 1×1 in slotted PVC + cover, ~990 mm/pair | ~16 m → 8 sticks |
| — | **In-box Cat6 patch** (closes L-05) | ~500 mm, splitter LAN → Pi Ethernet | 16 (+2) |

**Board mounting hardware (family restored 2026-07-28 — the old single "A5 standoffs M3×30"
line mislabeled the rear screw as the standoff and dropped the rest):**

| # | Item | Spec | Qty |
|---|---|---|---:|
| A4 | Board standoffs | **M3 F-F 12 mm brass** | 128 (+16) — 4/board × 32, 8 holes per pair box |
| A5 | Rear screws | **M3 × 30** (through ¾″ ply into the standoff) | 144 |
| A6 | Front screws | **M3 × 6** (board side) | 144 |
| A7 | Washers | M3 flat + split, **plus M3 fender washers ≥16 mm OD on the rear face** (L-09 — bearing face on painted ply) | 256 + 144 fender |
| A8 | Board centre supports | **12 mm SCREWED NYLON standoffs, 3/board** — ⛔ NOT adhesive pads (PANEL-W2: adhesive fails) | 96 (+10) |

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
| F5 | Adhesive tie mounts | **400** · within 50 mm of every MCV plug row *(old 200 missed the 9 gland-wall mounts/pair, the J14 anchors and the riser lane — PANEL-W2 counts ~24/pair)* |
| F6 | Cable ties 4 in | 500 |
| F7 | **Wire-map cards**, printed + laminated | 16 · **MANDATORY, taped inside every door** |
| F8 | Label stock, heat-shrink / vinyl | — |
| F9 | **Split loom 10 mm** (L-04) | ~136 m · ~4 m/lane, B1 and B3 in separate looms — **without it the IP68 gland seal never forms** |
| F10 | **ESD bleed stud** | 16 · M4 brass stud + 1 MΩ 1 W resistor to logic 0 V (plastic box, dry dusty room) |

## GROUP 8 — Off-plate (§G)

| # | Item | Qty | Status |
|---|---|---:|---|
| G1 | **Field harness assembly** | **40 quoted** | ✅ **QUOTED 2026-07-30 — MiniProto Q26208-17-001** (expires Aug 26): HARNESS-A ×40 @ $334 + PI-LINK-B ×20 @ $82; **Rush 10–20 bd = $19,500** / Std $15,000. Vendor answers audited — all conformant; accept UL1007 + 1.0 mm² ferrules + stripped machine ends. ⛔ **Before approving: quote line says PI-LINK-B Rev 1 — must be Rev 2 (strip length)**; reconcile qty 40 vs 34+3 on the review page; get the per-PN plug-sourcing matrix + on-hand stock + all-five no-sub lock in writing (email covers J3/J13 vendor-sourced + 1840489 hands-off only). Free-issue 1840489 ×42 ships ~Aug 12–15. **Take Rush — harness stops being the long pole; boards become critical path.**
✅ **2026-08-01 — ALL conditions SETTLED IN WRITING (Alex Malcoci):** Rev 2 re-issued at no
cost (their AI 0,34-6 TQ ferrule already has the 6.0 mm barrel); plug matrix per PN — MiniProto
sources J3/J5/J13/J14 at PO (not on hand; **falls back to our free-issue per line rather than
slip, with notice**), J4 free-issue; no-sub rule on all five PNs incl. FMC; labels + L1 locked;
Aug 12–15 1840489 hand-off meshes with the rush slot; FA→approval→pilot+balance confirmed.
**Unanswered: the 40-vs-37 qty question + review-page spares/NRE + >$10K payment path** —
recommendation ACCEPT 40 (6 spare harnesses = sane insurance) and approve at the review link
with Rush selected. |
| G2 | Interposer C1 housing (34-pos) — **we supply MALE/pins** | 36 | AMP **1-201357-1** (AMF `000025144`) |
| G3 | Interposer C2A housing (50-pos) — **we supply FEMALE/sockets** | 36 | AMP **201358-1** (AMF `000028409`) |
| G4a | **Pin** contacts `.062` (size 16) | ~30/lane +25 % | AMF `760011197` |
| G4b | **Socket** contacts `.062` (size 16) | ~30/lane +25 % | AMF `760019201` |
| G5 | Crimp + extraction tooling | 2 sets | size-16 crimper w/ positioner + AMF `030 004 031` |
| G5a | Guide pins/sockets, spring clips, strain clamps | 32 sets | `000028442` · `000028441` · `000029013` · `000029093` (C1) / `000029896` (C2A) |
| G6 | PoE head-end | 18 injectors **or** 2 × 16-port bt switch | TL-POE170S ~$50 |
| G7 | **Cat6 solid-core, 1000 ft box** | 1 box | ✅ **ON HAND 2026-07-29** — cut list below |
| G8 | J14 Stop/CIS interface | 32 | ⛔ **DECISION OPEN** ~$25/lane |
| G9 | **Ball-detect sensors** | ~~72~~ **8–12 spares** | ⭐ **RESPEC'd 2026-07-29: KEEP the existing 64 DIELL LSC/AN-2C6J heads, replace as they fail.** They are NPN active-low (proven: ~16 V clear / ~0.7 V blocked) and the new architecture feeds them from the isolated 12 V (D7→F6) — **GATE: bench one head at 12 VDC and prove clear/blocked switching before this decision is final.** Buy only a spare-attrition batch of spec-compliant M18 retroreflective NPN-NO 10–30 VDC units (SSC/AN-0C or any brand meeting the deprecation-doc spec table — never diffuse). Full 72-unit fleet buy CANCELLED (~$4.6k saved). |

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

# APPENDIX 0 — PROCUREMENT STATUS 2026-07-29 (end of ordering session 1)

**ORDERED:** DigiKey main (13 lines ≈ $5,041 — consignment 5 + plugs 1840447×76/1840405×76/1840382×72
+ stars ×30 + DDR-15G-12 ×18 + DDR-60G-5 ×18 + Pi 4B ×18 @$100 + heatsinks ×16) ·
Mouser ($1,104 — 1843680 ×125 consign · 1840463 ×40 · 1831293 ×10 practice, BACKORDERED) ·
CZH-Labs ($1,296 — F-1019 ×18 · MD-D220T-1 ×36) · B&H (SanDisk High Endurance 32 GB ×20, $460) ·
**OnlineComponents.com (ORDERED 2026-07-29): 1840489 ×50 @ $16.26 = $813 against the inbound
100 due 8/12** — the #1 long pole now has a PO; Newark hedge still optional ·
**AutomationDirect (ORDERED 2026-07-29, ≈$1,650 after final audit corrections):** KN-F10 ×2pk ·
KN-EB3 100+10 · DN-R35S1-2 ×4 · WDN-1022G-1 ×9 · **WDN-1015W-1 ×8** (white subs for the
backordered gray lacing duct) · **KN-T12SP4 ×1** (100/pk) + **KN-2JM12 ×1** + KN-ECT12SP4 ·
fuses GMA-2 ×8 / GMA-3 ×4 / S506-4-R ×4 / GMA-1 / S506-2-R / **GMC-1** · F18RP-0N-0E **×4**
(Dylan cut from 12) · RL110-1 ×15 · Murr cordsets **×6** · MTW18 BK/RD/WH(1000ft)/OR.
Capture dongle + USB-C pigtail + remaining Amazon-class lines handed to GPT — brief at
`phase8_gpt_sourcing_brief_2026-07-29.md`.

**CARTS BUILT / PENDING:** OnlineComponents 1840489 ×50 @$16.26 = $813 against the 100 due
8/12 (⭐ submit; ground shipping — the harness-PO clock is the constraint, not transit) +
cancellable Newark hedge · AutomationDirect (KN-F10 ×2pk + KN-EB3 100+10 = $376.50 confirmed;
add — FINAL PNs 2026-07-29: WDN-1022G-1 duct ×9 (cover incl.) · lacing duct =
**WDN-1015G-1 ×8** (1.00×1.57 in / 25×40 mm — no true 1×1 exists in the WDN line; width is the
binding constraint) · feed-throughs = **KN-T12SP4 ×1 pack** (100/pk — spec-verified: single-level,
common-point, 4 landings/block; 2 blocks/pair = 8 landings) + **KN-2JM12 ×1 pack** (25/pk —
⛔ NOT KN-4J12: the SP4's For-Use-With list is the JM12 family only) + **KN-ECT12SP4** covers
×1 pack · lacing duct: WDN-1015G-1 BACKORDERED → substitute +8 more WDN-1022G-1 (width is
the binding constraint) · F18RP cut to ×4 (Dylan, cost), cordsets to ×6, RL110-1 ×15 ·
wire = MTW18BK/RD/WH + the OR spool, deliberately NO green/yellow (M-04) · fuses (ALL 5/pack)
**GMA-2 ×8pk / GMA-3 ×4pk / S506-4-R ×4pk** + GMA-1 + S506-2-R + **GMC-1 (sub for backordered
S506-1-R)** (⚠️ suffix trap: S506-**25**-R = 0.25 A) · F18RP-0N-0E ×12 · RL110-1 ×20 ·
M12 cordsets = **Murr 7024-12341-3210300** right-angle 3 m ×12 (⛔ not the $80 D-coded Ethernet
patch) · D6 marker cards DROPPED — P-touch + F7 wire-map cards cover it · MTW 18 AWG spools)
· capture dongle: the $11 VIXLW 4-head clone is chipset roulette — **buy ONE, Pi-test
(/dev/video0 + one ffmpeg frame), then 17× the passing listing**
· DigiKey add-on (M3DDA-2006J ×50 ⚠️ EOL shelf stock · CNC 3030-20-0103-00 ×100 · 3M 3365/20
×17 ft · practice headers **1779420 ×10**).

**AMAZON CART CORRECTIONS:** keep XHF ferrule kits; **REMOVE StarTech SVID2USB232 ×18 —
Windows-only, NOT UVC, will never work on the Pis.** The bench-proven dongle is the **VIXLW**
— but it was proven on the *Windows laptop* only: **bench-test it on a Pi first**
(`/dev/video0` + a v4l2 grab), then buy 18 of whatever passes. REMOVE micro-USB pigtails
(Pi 4 = USB-C, need ~600 mm ×16) · REMOVE 8" T&G rail (AD 2 m sticks cover it) · REMOVE bulk
RG59 (route = pre-made moulded RCA-RCA 75 Ω ~15 ft ×36). Still to add: glands 108×M20/90×M16 ·
fans ×18 · breathers ×16 · Cat6 patch ×18 · split loom ~136 m · tie mounts ×400 · ESD studs ×16
· Remington UL1007 22 AWG color set (violet/grey/brown/pink + std).

---

# APPENDIX — ORDER OF OPERATIONS THIS WEEK

| # | Action | Blocking? |
|---|---|---|
| 0 | **`git push origin fable-audit-fixes`** — this runbook's commit is the ONLY artifact that exists solely on this laptop; the off-disk mirror is r7-era and on the same volume | ⭐ 2 seconds; do it first |
| 1 | **Hunt Phoenix 1840489** — TTI, Powell, Mouser, Newark, RS, Arrow, Phoenix direct | ⛔ #1 long pole; blocks harness FA |
| 2 | **Place the harness PO** (Group 8 G1) — and get competing quotes | ⛔ ~12 wk clock hasn't started |
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
