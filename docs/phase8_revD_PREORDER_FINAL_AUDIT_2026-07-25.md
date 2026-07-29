# Phase 8 rev-D r6 — FINAL PRE-ORDER VERDICT

> ⛔ **SUPERSEDED 2026-07-28 — DO NOT UPLOAD r7.** The current package is
> **`kicad/fab_revD_2026-07-27_r10/`** (zero hand-solder, 323 JLC-placed / 37 lines) and the
> current ordering document is **`phase8_ORDER_RUNBOOK_2026-07-28.md`**. This file's upload
> instructions and its 34-board quantity basis are historical; its findings record remains valid.

**Date:** 2026-07-25 · **Repo HEAD:** `85dfce7` · **Package under audit:** `kicad/fab_revD_2026-07-25_r7/`
**Scope:** 34 assembled controller PCBs · 16 pair backplate sets · 34 field harnesses · machine interposer connectors
**Basis:** 10-dimension adversarial audit, findings survived independent refutation. Refuted claims are listed in §9 so they are not re-raised.

---

## 1. VERDICT

| Purchase order | Verdict | One-line reason |
|---|---|---|
| **PCB + JLC PCBA** (rev-D r6, 250 × 240 mm, 4-layer) | **GO-WITH-CHANGES** | The r7 package is technically clean and reproducible — but three documents still point a buyer at the wrong package, and the quantity must drop from 34 to a first article (§4). Fix the pointers, sign G15, upload. |
| **Backplate BOM** (`docs/phase8_backplate_BOM.md` §A–F, ×16 pairs) | **NO-GO at 16 pairs · GO for 1 pair** | Enclosure size rests on an un-measured 780 mm panel figure with DIN devices drawn at ~28 mm against a real 90 mm; 15 board-side connectors are on no purchase list; B1–B5 double-buys ~180 plugs the harness vendor already fits. Buy one pair's worth. |
| **Field harness** (`docs/phase8_harness_RFQ.md` ×34) | **NO-GO until wire list Rev 2 issues** | Every 1.2 m lead budgets zero for the in-enclosure run and the fleet box is per-PAIR; the RFQ also regresses the 2026-07-21 J14 ferrule/torque/strip correction. Both are free document fixes; both are unrecoverable after 34 assemblies are built. |
| **Machine interposer** (C1/C2A housings, contacts, tooling) | **NO-GO — correctly blocked** | G2/G3 already BLOCKED on 20 minutes of measuring. Do not release G4 contacts or G5 tooling either; they are family-specific and currently mis-scoped. |

**Net: do not place a $25–35k order this week. Place roughly $3–5k this week** (§5), fix five documents, run the first article, then release the balance.

---

## 2. STOP-SHIP

Nothing in this section is a design defect. All five are text edits. All five fire silently if skipped.

### S1 — The order is scoped at fleet quantity; every gate in the repo forbids it *(blocks: all POs)*

`docs/phase8_revD_readiness_checklist.md:31` and `docs/phase8_revD_first_article_pack.md:29`, verbatim: *"Do not scale to fleet quantity or field-deploy a lane on these boards until FA-9 + OG-4 pass and the … G15 EXPERIMENTAL-ORDER acceptance line is signed."* The G15 line at `docs/phase8_revD_readiness_checklist.md:350` is blank underscores. `docs/phase8_revD_r6_release_report_2026-07-25.md:267` blocks *"fleet quantity, lane deployment"* on FA-1…FA-16 being unexecuted; `:280` dispositions the **0.4807 mm** field-pin clearance (r6 spec §D.5.1, `FIELD_SLOW_MAN_T ↔ FIELD_SLOW_TENTH`, ~68 Vpk, IPC-2221B B1 wants 0.6 mm) as OPEN and assigns the fix to the **fleet revision** — i.e. 34 boards would be built to a revision the project has already committed to changing.

**Edit:** resolve §4 of this report and write the answer on the G15 acceptance line at `docs/phase8_revD_readiness_checklist.md:350` before opening a JLC upload dialog. Also close `[ ]` G12 (Gerber/JLC preview) and `[ ]` G14 (doc review) — the checklist's own header rule forbids ordering with any PRE-ORDER GATE unchecked, and both are one-sitting items.

### S2 — Three live documents name the superseded **r5** package as the one to order from *(blocks: PCB+PCBA)*

r5 has **bare opto inputs** — no `Dser`/`Dclamp`, no 47 k pull-ups, 250 × 225 mm, 271 parts vs r7's 391. Landing PBZ (measured 33 VDC) or DIELL_L/R (15.4–16 V) on it puts those rails across a 6 V-rated PC817 LED. r5's own gerber+BOM+CPL set is internally consistent and would pass JLC without an error. Nothing in `scripts/` asserts the current package.

**Edits (exact):**
- `docs/phase8_revD_readiness_checklist.md:17` and `:56-57` — replace `kicad/fab_revD_2026-07-23_r5/` with `kicad/fab_revD_2026-07-25_r7/`; add `_r5` and `_r6` to the superseded list at `:61`.
- `docs/phase8_trackB_controller_cutover_runbook.md:80` — *"Rev-D board ordered only from the current R5 package (kicad/fab_revD_2026-07-23_r5/)"* → `kicad/fab_revD_2026-07-25_r7/`.
- `docs/WSL_PHASE8_SYSTEM_MANUAL.md:8091-8092` (plus the three other r5 pointers at `:2396`, `:7869`, `:9141`) — same substitution. The manual contains **zero** references to `_r6` or `_r7` across ~9,100 lines.
- `docs/phase8_revD_change_list.md:38` — *"Current immutable package: kicad/fab_revD_2026-07-23_r5/"* → `_r7` (it is already corrected at `:450`; the header is not).

The only artifacts to upload are `kicad/fab_revD_2026-07-25_r7/wsl-phase8b-revD-gerber-drill.zip` and `assembly/wsl-phase8b-revD-jlc-standard-pcba-upload-bom.csv` + `-cpl.csv`.

### S3 — The rev-C as-ordered tree still holds a complete, numbered JLC upload packet with no tombstone *(blocks: PCB+PCBA)*

`kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/00_README_UPLOAD.txt` is a step-by-step upload procedure through PCB order settings, plus `wsl-phase8b-revB-JLC_UPLOAD_READY.zip` at the tree root. `_r1`…`_r6` all carry `_SUPERSEDED_DO_NOT_UPLOAD.txt`; this tree does not. Worse, `docs/phase8b_revB_fab_order_checklist.md` (106 lines, zero occurrences of *superseded / historical / rev-D*) is **the only file in the repo whose name asserts it is the fab order checklist**, is indexed as such at `docs/manual_src/23_appendices.md:320` and `docs/WSL_PHASE8_SYSTEM_MANUAL.md:9445`, and points at that packet. A repo-wide search for `JLC_UPLOAD_READY` returns hits only in the rev-C tree — r7 has no such directory. Building it yields 34 rev-C boards: wrong size, no AUX bank, no J15/J16, no 47 k, **no r6 input protection**.

**Edits (exact):**
- New file `kicad/fab_revB_routed_manual/_SUPERSEDED_DO_NOT_UPLOAD.txt` → *"Rev-C as-ordered record. DO NOT UPLOAD. Current package: kicad/fab_revD_2026-07-25_r7/"*
- New file `kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/_SUPERSEDED_DO_NOT_UPLOAD.txt` → same text.
- Banner at the top of `docs/phase8b_revB_fab_order_checklist.md` → *"HISTORICAL — REV-B/C ONLY. DO NOT ORDER FROM THIS DOCUMENT. Current: kicad/fab_revD_2026-07-25_r7/ + docs/phase8_revD_readiness_checklist.md."*
- Add the same qualifier to the two index entries (`docs/manual_src/23_appendices.md:320`, `docs/WSL_PHASE8_SYSTEM_MANUAL.md:9445`).

*(No automated gate enforces the tombstone convention — grep of `tests/` and `scripts/` for `_SUPERSEDED_DO_NOT_UPLOAD` returns nothing. This is hand-applied and will not be caught by the release gate.)*

### S4 — Every field lead is cut at 1.2 m and budgets **zero** for the in-enclosure run *(blocks: harness PO)*

`docs/phase8_machine_harness_spec_sectionF.md:136-138` derives 1.2 m as *"enclosure → C1/C2A run measured ~0.6–1.0 m → build at 1.2 m for service slack + drip loop"*. The 0.2–0.6 m of headroom is slack, not routing. But End-A in `docs/WSL-LANE-HARNESS-A_wirelist_rev1.csv` is the **landed Phoenix plug**, so 1200 mm must also contain the in-box run — and the fleet layout puts Board A at panel y 20–260 on a 780 mm panel with all bundles routed to the **bottom-face** gland wall. Board A therefore burns ~0.75–0.95 m in-box, leaving ~0.25–0.45 m to cross a measured 0.6–1.0 m gap. Additionally the fleet box is one per **PAIR**, and per-pair siting has never been surveyed. `docs/phase8_backplate_BOM.md` (commit 85dfce7, *after* the RFQ at `0537e26`) then upsized the panel stack 670 → ~780 mm, lengthening the in-box run another ~110 mm, with no revisit of any wire length. Affected: 40 leads × 34 assemblies. Re-buy = $6.8k–13.6k plus a repeat of the 3-week FA + 8-week balance lead time. The staged 1+2+31 ramp does **not** catch it — the 2 pilot units go on lanes 21/22, which use the single-lane pilot box.

**Edit:** tape-measure one representative pair location (Board-A J3 plug → duct → bottom gland → C1/C2A on **both** machines), then issue `docs/WSL-LANE-HARNESS-A_wirelist_rev1.csv` as **Rev 2** with a near-lane / far-lane length class. If measurement is not possible now, set every 1200 mm lead to **2500 mm** and every 1500 mm lead to **3000 mm** and trim on site — but note that trimming removes the machine-end printed heat-shrink marker, so machine-end labels must be set back or shipped un-shrunk. RFQ §9 already asks the shop to price a length delta; use it.

### S5 — The RFQ regresses the 2026-07-21 (H7) MC 1,5 termination correction *(blocks: harness PO)*

`docs/phase8_harness_RFQ.md:92` specifies *"18 AWG leads → **0.75 mm² insulated** ferrule, 8 mm barrel"*, and `docs/WSL-LANE-HARNESS-A_wirelist_rev1.csv` rows 37–39 (JMP1 pos 1+2, W33 pos 3, W34 pos 4) hard-specify *"0.75 mm² insulated ferrule; landed"* into **J14**, a 3.5 mm-pitch `MCV_1,5_4-G-3.5` carrying `SAFE_TBSC_RETURN` / `SAFE_STOP_RETURN`. The corrected limit is **0.5 mm² max with an insulated ferrule**; a 0.75 mm² insulated collar is ~4.0 mm OD against a 3.5 mm pole pitch, so **adjacent poles interfere** — all four J14 poles are populated. Both files are commit `0537e26`, four days after the correction landed in six places including `kicad/fab_revD_2026-07-25_r7/README-fab-package.txt:76-78`.

Understated in the original finding, and worse: the RFQ carries **no torque and no controller-end strip length at all**. §2 says leads are *"landed and torqued into its Phoenix plug, per §4/§5"* and §5 contains ferrule sizes only. The corrected **0.22–0.25 N·m** (H7 found the old ~0.5 N·m figure was over 2× rated — enough to strip the M2 screw or crack the plug body) and the corrected **7 mm strip** never reach the vendor, who performs ~36 landed screws per assembly × 34 = **~1,224 M2 screws**. RFQ §5 also asserts the opposite of the correction as field-proven: *"We have hand-built one unit successfully using insulated ferrules at both sizes above."*

**Edits (exact):**
- `docs/WSL-LANE-HARNESS-A_wirelist_rev1.csv` rows JMP1 / W33 / W34 → *"bare stranded or 0.75–1.0 mm² **UNinsulated** ferrule; strip 7 mm; landed"*. Leave 0.34 mm² insulated on J3/J4/J5/J13 (collar ~3.0 mm, fine) and 0.75 mm² insulated on the MKDS loose leads W35–W49 (5.08 mm pitch, rated to 1.5 mm²).
- `docs/phase8_harness_RFQ.md:92-97` → state the real rating: *"0.14–1.5 mm² bare or with an UNinsulated ferrule; **0.5 mm² MAX with an insulated/plastic-sleeve ferrule**"*; change the 8 mm ferrule barrel to match a 7 mm strip; **add** *"Terminal screw torque 0.22–0.25 N·m (M2). Do not use ~0.5 N·m — it is over 2× rated."*
- Delete the §5 *"hand-built one unit successfully using insulated ferrules"* sentence and the §15 attachment-3 prototype-photo line unless that unit exists (lane-21 harness build is still open NEXT-ACTION 5 in `docs/HANDOFF.md`).
- Add `docs/phase8_revD_harness_bom.csv` to the §15 attachment list — it is the only machine-readable artifact carrying all three corrected figures, and it is currently not attached.

---

## 3. FIX-BEFORE-ORDER (HIGH)

### H1 — All 15 board-side connectors are on **no** purchase list. 510 pieces. ~$900.

`kicad/fab_revD_2026-07-25_r7/assembly/wsl-phase8b-revD-jlc-standard-pcba-excluded.csv` lists `A1, J1–J11, J13–J16, U45` as *"Hand solder"* — the JLC upload BOM contains **zero** `J*` designators, so the PCBA PO physically cannot supply them. `docs/phase8_backplate_BOM.md` (HEAD, the only doc with fleet quantities) pulls exactly **2 of 17** into §A — A2 Pico ×34 and A3 TMA-0505S ×34 — and stops. §B is mating halves only; §G has no connector line; G13's scope is *"every **mating** + coding part"*. Grep of `1843680|1843729|1843703|1843648|1843622|1715734|1715721|3020-20-0100` over `phase8_backplate_BOM.md` returns **zero hits**. The parts are fully identified and `Status=Locked` — this is a purchasing-list omission, not a design defect, and it does **not** invalidate the PCB/PCBA PO. But it must go out on the **same day**, because `docs/cowork_cart_handoff.md:22-23` records **1843680** (J3+J15) and **1843703** (J5) as *backordered at DigiKey at qty 5*, and the fleet needs 68 and 34.

**Edit — add to `docs/phase8_backplate_BOM.md` §A, sourced from `kicad/fab_revD_2026-07-25_r7/assembly/wsl-phase8b-revD-hand-solder-bom.csv`, at 34 boards + ~10 % spares:**

| Ref | PN | Per board | Order qty |
|---|---|---|---|
| J2 | Phoenix 1715734 (MKDS 1,5/3-5,08) | 1 | 38 |
| J6–J11 | Phoenix 1715721 (MKDS 1,5/2-5,08) | 6 *(not 7 — J12 is DNP)* | 224 |
| J3, J15 | Phoenix 1843680 (MCV 1,5/10-G-3,5) | 2 | 72 |
| J4 | Phoenix 1843729 (MCV 1,5/14-G-3,5) | 1 | 38 |
| J5 | Phoenix 1843703 (MCV 1,5/12-G-3,5) | 1 | 38 |
| J13, J16 | Phoenix 1843648 (MCV 1,5/6-G-3,5) | 2 | 72 |
| J14 | Phoenix 1843622 (MCV 1,5/4-G-3,5) | 1 | 38 |
| J1 | CNC Tech 3020-20-0100-00 (2×10 IDC) | 1 | 38 — **HOLD** |

**J1 stays gated** — it is `Status: Candidate – verify body/keying` in the hand-solder BOM and is verify-item 4 in the backplate BOM. Close the pin-1/keying fit-check against the KiCad footprint first. **Pitch trap:** every MKDS is 5.08 mm, every MCV is 3.5 mm — refuse any 3.81 mm substitution. Source 1843680 and 1843703 with a Mouser second-source fallback. Also re-word G13 at `docs/phase8_revD_readiness_checklist.md:317` so *"assembly BOM"* explicitly includes board-side headers.

Add **~10 % spare MCV headers specifically**: FA-8 requires an irreversible coding-rib cut on 4 headers per board (136 cuts fleet-wide) with no spare stock today.

### H2 — B1–B5 re-orders 180 plugs the harness vendor already buys and fits. $730–1,800, plus a safety hazard.

`docs/phase8_harness_RFQ.md` §2 puts the controller end *"FULLY TERMINATED — insulated ferrule, landed and torqued into its Phoenix plug"*; §4 Tier 1 lists all five PNs at Qty/assy 1 **NO SUBSTITUTIONS**; §12 adds 3 unpopulated spare sets = **185 plugs**. `docs/phase8_backplate_BOM.md:43-47` independently orders 32 (+4) = **180 more** against a 160-plug installed need. There is no free-issue/consignment clause anywhere in the RFQ (grep of `docs/` finds "consign" only against U37/TMA-0505S). `kicad/fab_revD_2026-07-25_r7/README-fab-package.txt:74` and readiness-checklist G13 create a **third** overlapping instruction, and both are *newer* than the RFQ — so the supersession defence fails.

Two things make this worse than waste:
1. **1840489 (J4) is in the constrained pool** (see H3). A parallel 36-unit house buy can exhaust the same stock the harness vendor needs, stalling the harness PO.
2. **Uncoded spares are a universal key.** Per `docs/phase8_revD_harness_bom.csv` the OG-3 key is *"CP-MSTB profile in the PLUG at pole N; remove the J-header rib at pole N"* — a plug with **no** profile mates any header. 36 loose 10-pos plugs are indistinguishable J3-or-J15 (an electrically **silent** swap: cycle sensors crossed with AUX contacts) and 36 loose 6-pos plugs are indistinguishable J13-or-J16 (a J13 lamp plug into J16 lands resistorless LEDs across 5 V→GND and **wedges I²C** — FR-5, a damage path on a live board).

**Edit — `docs/phase8_backplate_BOM.md:43-47`:** annotate B1–B5 *"SUPPLIED FITTED BY THE HARNESS VENDOR per RFQ §4 Tier 1 — do NOT procure. Spares come from RFQ §12's three spare sets."* If any loose stock is kept, gate it *"SPARES ONLY — must be CP-MSTB 1734634 coded and band-marked per docs/phase8_revD_harness_bom.csv before use."* Keep **B6/B7** (J15/J16) — the RFQ correctly excludes them — but resolve their self-contradiction: B6 specifies PN **1840447, byte-identical to B1**, while instructing *"different colour to B1"*; 1840447 is one colour and no alternate PN is given. Delete the colour scheme and rely on the CP-MSTB + WHITE/YELLOW/BLUE band scheme the harness CSV already locks. Write the de-conflict into **all three** places (backplate BOM §B, fab-package README "Harness order" block, gate G13) or the next reader re-creates it.

### H3 — 1840489 (J4 plug): authorized channel is dry, and every current doc dropped the last-time-buy flag.

`docs/phase8_revB_preorder_parts_list.md:13` flagged it *"will not be replenished"*; `docs/phase8_revB_preorder_parts.csv:12` reads *"LAST-TIME-BUY/discontinued — buy now; no sub"*; `docs/cowork_cart_handoff.md:27` calls it discontinued. Both live rev-D artifacts lost the flag: `docs/phase8_backplate_BOM.md:44` lists it at 32 (+4) with no note, and the 1840489 row in `docs/phase8_revD_harness_bom.csv:4` has an **empty Notes column**. Aggregators show every authorized distributor at 0/on-order with brokers holding stock — an obsolescence signature. Meanwhile the RFQ lists it **Tier 1 NO SUBSTITUTIONS**, forbidding the vendor the obvious workaround. Real combined need after the H2 de-duplication is ~37–40 for a 32-lane installation with a 20-year service life and **zero** replacement channel.

**Edits:**
- Restore the flag at `docs/phase8_backplate_BOM.md:44`, `docs/phase8_revD_harness_bom.csv:4`, and the fab-package copy.
- Buy the **lifetime quantity in one line — 50 pieces** (34 in service + 4 board spares + ~12 service spares) from the house today, and **free-issue** to the harness vendor rather than letting the vendor source it. Add that instruction to RFQ §4 Tier 1.
- Add a pre-approved fallback to RFQ §4 so "NO SUBSTITUTIONS" cannot stall the build: **Phoenix FMC 1,5/14-ST-3,5** push-in mates the same MCV 1,5-G header. Termination changes screw→push-in; **zero PCB impact, no channel re-split.** (The "must re-split SLOW-A across two plugs" fear is wrong.)

### H4 — The fleet order has no lead-time / order-first tier at all, and the schedule-critical items are the cheap ones.

`docs/phase8_backplate_BOM.md` is the newest doc in the repo and contains **no** lead-time, stock, or sequencing content; its "Verify-before-ordering" block is six mechanical items. No rev-D successor exists to `docs/phase8_revB_preorder_parts_list.md:11-15` ("**Order these FIRST (long-lead / volatile)**" — *"All Phoenix Contact connectors in one order … Phoenix historically swings 8–20 weeks. This family gates the whole build."*). Meanwhile the single highest-cost line (E4 Saginaw, ~55 % of backplate cost) is verified **widely stocked at ~$492, same-day ship**. The supply picture is inverted from the cost picture: if the POs go out in cost order, $10k of steel boxes sit on the floor while the cutover stalls on a $2 header.

**Edit — add a `## §0 Order these FIRST` block to `docs/phase8_backplate_BOM.md` before line 24:**
- **Tier 1, today:** the entire Phoenix family in ONE PO — the 14 locked board-side header lines from H1, B6/B7, the 1840489 lifetime buy, CP-MSTB 1734634.
- **Tier 2, today:** TMA-0505S ×38 (sole source of FIELD_WET_V, exact-part-no-substitution) and Pico SC0915 ×38.
- **Tier 3, today:** resolve `C26108` (10 M, R135/R138/R141) — see M-01.
- **Tier 4, any time:** E4 enclosures, E5 plywood, DIN gear, glands, fuses, wire, Pi, PoE. All verified commodity.
- Record the actual quoted lead time per line as each quote returns.

---

## 4. THE FLEET-QUANTITY QUESTION

**Recommendation: split into two POs. Wave 1 is a first article. Do not release 34 boards.**

The project's own documents are unambiguous and I found nothing that reclassifies them. `docs/phase8_revD_r6_release_report_2026-07-25.md:290` states the PC817B CTR issue *"is what makes this an experimental first-article build rather than a fleet release."* `:280` leaves the 0.4807 mm clearance OPEN and assigns the fix to the **fleet revision** — so a 34-board build is 34 copies of a revision already committed to change. G8/OG-1 separately blocks *"enclosure/backplate purchase"* and records that *"no fleet enclosure, subpanel, or backplate has been purchased — purchases were explicitly frozen pending this gate."*

**The blast radius is specific.** Each board carries **40 wave-soldered THT PC817B optos** (LCSC C5692981, UMW, "B rank CTR 130-260% REQUIRED") — 1,360 across the fleet. FA-9 exists to condemn exactly that lot at the r6 operating point (1.34 mA nominal / 1.12 mA loaded). The 40 × 47 k and the 2k2 Rin are 0805 SMD and are cheap rework; the **optos are not** — an FA-9 failure means 40 THT desolders per board. The harness spend is largely *not* stranded by an FA-9 failure (the wire list maps to connector positions, not to opto topology). The enclosure/power/compute spend is not stranded by FA-9 either — it is stranded by an enclosure-dimension error, which is a separate live risk (M-06/M-07).

### Wave 1 — release after S1–S3 are done and G12 + G14 + G15 + OG-1 are signed

| Item | Qty | Note |
|---|---|---|
| Assembled rev-D r6 boards | **5** | JLC PCBA practical minimum. 2 for the lane-21/22 pilot pair, 3 for FA + spares. |
| Board-side hand-solder connector kits | **fleet qty (H1)** | Lead-time driven — buy 34-boards-worth NOW even though only 5 boards ship. Connector count is stable across the expected copper re-spin. |
| Pico SC0915 · TMA-0505S | **38 each** | Sole-source, no-sub, cheap. Buy fleet. |
| 1840489 (J4 plug) | **50** | Lifetime buy. Discontinued. Free-issue to the harness vendor. |
| CP-MSTB 1734634 coding profiles | **~40 stars (240 profiles)** | 4/board × 34 = 136 + FA-8 sacrificial + spares. ~$150–350. |
| Harnesses | **3** | RFQ's own ramp: 1 FA + 2 pilot. **Only after wire list Rev 2.** Do NOT release the 31-unit balance. |
| Enclosure + backplate + power + compute set | **1 pair** | One SCE-36EL3008LP, one plywood panel, one DDR-60G-5, one Pi, **one PoE injector + one GBT splitter** (the PoE chain has never been exercised end-to-end anywhere). |
| Breakout modules | **1 × F-1019, 1 × IDC20** | These are the measurement that gates the whole enclosure decision (M-06). |

**Wave 1 spend: roughly $3–5k.**

### Wave 2 trigger — all of these green and recorded

1. **FA-16** — 40/40 unpowered orientation + per-direction continuity census.
2. **FA-15** — reverse-bias 0.35 V ±0.1 V on every reverse-capable channel.
3. **FA-9** — numeric per channel at loaded-minimum FIELD_WET and ≥70 °C, including `I_C(cap) ≥ 100.3 µA` aging reserve.
4. **OG-4** — at-temperature (≥70 °C) rail-tap fault injection.
5. **Powered characterization session** — cam AC/DC class + RMS + frequency, record N, snubber sizing, **and** the wetting-current floor measurement (M-02).
6. **F-1019 + IDC20 measured**, panel stack re-run with real 90 mm across-rail DIN envelopes, enclosure size re-decided (M-06/M-07).
7. **G15 acceptance line signed.**

### Re-order penalty for staging

**Boards:** one extra JLC PCBA setup + shipping, plus ~3–4 weeks of re-order lead time. That runs **in parallel** with the harness balance, which the RFQ already schedules at *"within 8 weeks of FA approval"* — so the calendar cost of staging the boards is **approximately zero**. **Harnesses:** the 1+2+31 ramp is already the RFQ's own structure; do not disturb it. **Enclosures:** the Saginaw is verified same-day stock at multiple distributors, so staging costs nothing but a second freight charge on 16 boxes. **Phoenix:** do *not* stage — that is the one family where staging costs weeks, which is why it is Tier 1 above.

---

## 5. ORDER-NOW vs HOLD

### ORDER TODAY (~$3–5k) — lead-time or single-source driven

| BOM line / source | Item | Qty | Why today |
|---|---|---|---|
| **NEW §A sub-table** (H1) | Phoenix board-side headers 1843680 / 1843729 / 1843703 / 1843648 / 1843622 / 1715734 / 1715721 | 72/38/38/72/38/38/224 | Two of these were backordered at qty 5. Fleet needs 34–224. One PO, whole family. |
| B2 + RFQ Tier 1 | **1840489** MC 1,5/14-ST-3,5 | **50** | Discontinued, authorized channel dry, no same-pitch screw drop-in. Lifetime buy. Free-issue to harness vendor. |
| B6 / B7 | 1840447 (J15) · 1840405 (J16) | 38 each | Not in RFQ scope. Raise from 32 to 38 to match the 34-board count + spares. |
| `phase8_revD_harness_bom.csv` row 9 | CP-MSTB **1734634** coding profiles | ~40 stars | $0.10 ea, MOQ 1 at DigiKey. FA-8 cannot run without them. |
| A2 | Raspberry Pi Pico SC0915 (castellated, **not** H/WH) | 38 | Sole spec, no spares currently budgeted. |
| A3 | TRACO **TMA-0505S** | 38 | Sole source of FIELD_WET_V. No U45 = no input channels. |
| — | **C26108** 10 M 0805 1 % (R135/R138/R141, 102 pcs) | resolve | OOS at LCSC **and** its obvious alternate C228256 is OOS. See M-01 — this is design-coupled, not a swap. |
| §G (new) | 1 × F-1019 + 1 × **Winford BRK2x10-DIN** | 1 each | The measurement that unblocks the entire enclosure decision. |
| §G (new) | 1 × TL-POE170S + 1 × GBT-12V60W | 1 each | Prove the 802.3bt → 12 V → DDR chain before committing 18+18. |
| A1 | rev-D r6 assembled PCB | **5** | First article. After S1–S3 + G12/G14/G15. |
| G1 | Field harness | **3** | After wire list Rev 2 (S4 + S5). |

### HOLD

| BOM line | Item | Qty held | Release condition |
|---|---|---|---|
| A1 | rev-D boards | 29 | Wave 2 trigger (§4) |
| G1 | Harnesses | 31 | FA approval of harness unit 000 |
| E4 | Saginaw SCE-36EL3008LP | 16 | F-1019/IDC20 measured + panel stack re-run with 90 mm DIN envelopes + OG-1 signed. **Verified same-day stock — nothing is lost by waiting.** |
| E5 / E6 / E1 / E2 / E3 / E7 | Plywood, stud hardware, DIN rail, brackets, duct, glands | 15 pairs | Follows E4 |
| C1 | Raspberry Pi 4B 4 GB | 16 | Price risk noted (M-13) — but 16 Pis assumes the unified scoring+control daemon ships; buy 2 now |
| D1 / G6 | GBT-12V60W splitters · TL-POE170S injectors | 17 / 17 | PoE chain proven end-to-end on the pilot |
| **B1–B5** | The five harness-side Phoenix plugs | **ALL 180 — delete the line** | Vendor supplies fitted (H2) |
| G2 / G3 / G4 / G5 | Interposer housings, contacts, tooling | all | 20 minutes of measuring at the machine. Mark G4/G5 BLOCKED too — they are not. |
| — | 3020-20-0100-00 (J1 header) | 38 | Body/keying verification against the KiCad footprint |

---

## 6. MEDIUM / LOW FINDINGS

| # | Sev | Finding | File · fix |
|---|---|---|---|
| M-01 | MED | `C26108` (10 M, R135/R138/R141) OOS **and** its alternate C228256 OOS. Not a swap: it is the `R_TAPG` divider with **+0.14 V worst-stack margin** — 4.7 M fails outright (~2.56 V vs 2.68 V V_GS(th)); only 22 M works and needs the leakage term re-derived. The LCSC code is hard-coded in `scripts/export_fab_revD.py` PART_LOCK (line 312) and a miss is fatal (line 706), so a change forces an **r8 package** + re-run of G10/G11/G12. | Resolve stock **before** upload. All other JLC lines verified amply stocked (PC817B 4,920 vs ~1,400 need; 1N4148WS 37,160 vs ~3,100). |
| M-02 | MED | **No minimum wetting-current requirement exists anywhere.** r6 puts 1.12–1.34 mA at ~4.5–5.0 V through dry machine contacts the repo itself describes as *"finicky due to dirt/oxide"*; the only live-proven point (machine-22 GS map 10/10) was ~3–5 mA at 11–14 V. Dominated by the already-committed item-A bleed, not by r6 (r6's own contribution is −23 %). | Add the floor to the spec so the next revision cannot spend it silently. Measure per dry-wetted class at the powered session. **Gate R122/R123 (2 pcs, same BOM line) — NOT Rin (40 pcs, splits the line, moves EXPECTED_JLC_LINES 27→28).** |
| M-03 | MED | Nothing trims the **DDR-60G-5** up. At factory 5.00 V the rail lands **4.39–4.61 V** under relay load — below the NE555 4.5 V min, the TMA-0505S 4.5 V min, and the daemon's own `DEFAULT_V5_MIN_MV = 4500.0`. The design's own requirement (`docs/manual_src/06_board-power.md:110-111`) is 4.6–4.8 V under full relay load; it survives only in rev-B bench docs. **Not an order change** — the DDR is trim-adjustable ±10 %. | Add to `docs/phase8_backplate_BOM.md` §D / box build sheet: *"Set DDR-60G-5 output to 5.20–5.25 V at its terminals before landing any load."* Give FA-6 step 3 a numeric floor: all 6 coils energised → TP1 ≥ 4.75 V, heartbeat v5n ≥ 4700 mV. Mark FA-1's 4.6–4.8 V band **idle-only**. |
| M-04 | MED | **D5** specifies Konnect-It **KN-G10 ground blocks** (green/yellow, earth-symbol, rail-bonding PE class) as the **5 V return bus**, and D6 orders printed markers for them — a standing invitation for an electrician to bond logic 0V to earth and defeat the TMA-0505S isolation the whole board rests on. Also under-counted: 2 blocks = 4 landings against 6 needed. Separately §A–F contain **no earth bond** for the steel box (plywood replaced the steel subpanel; the enclosure ships with a door ground stud). | Change D5 → insulated feed-through (KN-T/KN-S class) + jumper comb, **qty 4/pair**; keep one real KN-G10 per box for its actual job. Add ring lug + ~1 m green 12 AWG to the box's factory stud. Add to the F7 wire-map card: *"The 0V bus is NOT earth. Never bond it."* ~$180 fleet. |
| M-05 | MED | RFQ + wire list carry **no CP-MSTB coding and no band-marking instruction**, and 1734634 has no fleet quantity anywhere (only *"buy 2 stars min for the pilot"*). 34 harnesses would ship as universal keys. | Add 1734634 as a Tier-1 RFQ line (2 profiles/assy, J3 @ pole 1 + J13 @ pole 1) with the WHITE band marking, **or** accept doing it in-house and buy ~40 stars. Add the header-side rib cuts (136 fleet-wide) to a fleet build sheet, not just FA-8. |
| M-06 | MED | **E4 bakes in the ~$1.6–3.1k enclosure upsize before the measurement the source drawing says must gate it.** The 780 mm figure is labelled *"provisional"* by its own drawing; C7 has no manufacturer PN; three live docs now disagree on the box (BOM ≥310×780 · sourcing brief ≥310×670 · enclosure spec still lists SCE-30EL2408LP as **Primary**). | Buy ONE F-1019 + ONE **Winford BRK2x10-DIN**, measure, re-run the stack, then release E4 and reconcile `docs/phase8_enclosure_sourcing_brief_GPT.md` + `docs/phase8_pair_enclosure_spec.md`. |
| M-07 | MED | The Rev-2 drawing draws DIN devices at **~28 mm** across-rail against a real **90 mm** (Mean Well DDR = 52.5 × 90 × 54.5). Real stacked panel is ~975–990 mm, not 780 — the SCE-36P30's 838 mm panel does **not** hold the drawn topology either. **The 36×30 upsize is still NECESSARY** (one horizontal rail needs ~315–325 mm against 290 mm available; 2 × 250 mm boards won't fit the 30×24's 533 mm width) — so there is no saving to recover, but the **internal layout must move to side-by-side (spec layout B2)** before the plywood is drilled. | Re-dimension with real 90 mm envelopes. **Order consequence:** C8's "~150 mm" J1 ribbons (×38) are likely the wrong length — layout B2 needs <200 mm. E1 DIN rail packs grow ~+5 (~$50) if rails run the 686 mm width. |
| M-08 | MED | **No overhead-display driver in the order.** VDB-99 drives each pair's overhead monitor today over VGA and is pulled at every cutover; the pilot's replacement is **one** owned Beelink thin client. A cut-over pair with no display cannot show a score to the bowler. Zero-lead-time commodities, phased cutover ⇒ can go on a later PO. | Add §G9: 15 (+1) mini-PC thin clients (~$150), HDMI cable + mount each; survey per-pair monitor input (HDMI vs VGA-only) and add active converters; each needs a network path — G7 buys only 16 Cat6 runs, not 32. |
| M-09 | MED | The **~$890–1,050/pair roll-up is provably C+D+E only** (I reproduced it to the dollar). Sections A (~$23–26/pair), B ($58–138) and F (~$30–45, no prices at all) contribute $0. The board PO has **no dollar figure anywhere current** — the only board-cost number in the repo (`docs/pcb_design_spec.md:6`, *"20 boards … ~$160-190"*) is the rev-A 100×100 mm 2-layer board at 31 placements, and that doc carries **no supersede banner**. | Re-scope the roll-up heading, and get a real JLC quote before budgeting. rev-D r6 is 250×240 mm, 4-layer, 306 placements, ~192 THT joints/board. |
| M-10 | MED | **G4 orders "~2,700" undifferentiated interposer contacts** — no pin/socket split, quantity computed on 32 lanes while G2/G3 buy 36 housings, and G4/G5 are **not marked BLOCKED** although they depend on the same unconfirmed family. 66101/66099/305183 appear in exactly one line in the whole repo with no source. Real crimp count is ~24–30 leads/lane, so 2,688 is ~2.5× over. | Split G4 by gender with explicit quantities, cite the source, mark G4 **and** G5 BLOCKED alongside G2/G3. Contacts and tooling are commodity/in-production — only the **housing** carries obsolescence risk. |
| M-11 | MED | **Network plant is two placeholder lines.** G6/G7 have empty Part columns and no cost; no aggregation switch, bulk Cat6, patch panel, keystones, crimper, tester, raceway, rack shelf, or PDU. The closet survey (`phase_8a_infrastructure_plan.md` §8) was never done. Note the plan's TL-SG2428P baseline (250 W PoE+) is now **under** the 16 × ~20 W = ~320 W load model. | ~$1.2–2.5k of materials + 2–4 days of cable pull. Decide injectors-vs-bt-switch (different downstream needs) and write G7 out as a real BOM before the enclosure PO. |
| M-12 | MED | **Install/commissioning tooling has no owner.** No LOTO device, danger tag, padlock or voltage tester for 32 cutovers; no ferrule crimper for the ~1,200 ferrules F3/F4 buy (G5's size-16 crimper is a different tool); F7 is marked **MANDATORY** and F8 has quantity "—" with no printer or label stock; FA-7/FA-9 bench gear (heat gun + thermocouple, ≥100 MΩ probe, µA-capable adjustable load, scope) is on no list. | Add a §H tooling section. None of it is long-lead; all of it stops work if absent. |
| M-13 | MED | **C1 prices 18 Pi 4B 4 GB at ~$65** in a market where Raspberry Pi itself raised the 4 GB SKU **+$25** (April 2026, LPDDR4 up 7× YoY). List is now ~$80 before margin. The repo's own last buy for this role hit *"0 stock, 34-week lead"* on a Pi 5 and resolved via **Amazon consumer kits at qty 2** — a channel never tested at 18 units. | Re-price and re-source before committing 16–18. |
| M-14 | MED | **Spares and field repair are unsupported.** A spare PCBA is not a swappable spare (17 hand-solder refdes + a Pico flash, unbudgeted); the manual's spares chapter is entirely rev-B (250×225, U4–U35, SS14, no 47 k, no r6 diodes) and points a 2028 technician at the **rev-B** BOM; `empty_ref.png` is gitignored and per-Pi, with no golden-image or SD-clone step and one `.bak` generation. | Update the spares chapter to rev-D. Add an SD imaging step to provisioning. Budget building the 2 spare boards, not just fabbing them. |
| M-15 | MED | **Two RFQ attachments do not exist.** `WSL-LANE-HARNESS-A_layout_rev1.pdf` is nowhere in the repo or Downloads; the *"Plug Body Labels sheet"* that both §7 and the CSV point to is not in the CSV, so 5 plug-body labels/assembly (204 fleet) have **no specified text** in a package whose §0 names labelling as priority #1. | Produce both before issuing, or delete the references. |
| M-16 | MED | **D4 lumps three fuse types into one 64-pc quantity** (3 A · 2 A fast ×2 · 4 A time-delay) — not orderable as written; real demand is 16/32/16 + spares, and 5×20 cartridges sell in 5s/10s. **D3's fuse blocks have no end plates** (KN-EP class) anywhere in §D/§E. Related: no **+5 V distribution point** and no jumper/comb bar — the DDR's +Vo must feed three fused branches from one terminal. | Split D4 into three lines; add end plates and a comb bar. |
| M-17 | MED | **Backplate mounting hardware missing.** No screws for the two DIN rails, the wire duct, the panel-mounted splitter or the three breakout modules (the layout says *"screwed to plate"*). E6 provides nuts/washers for 4 collar studs sized for a ~2 mm steel subpanel against a **12.7 mm plywood** panel. No hole-cutting tool for ~150 M20 gland holes in enclosure-gauge steel. | ~$30 of parts + a Forstner bit + a step drill/knockout punch. Measure the stud thread projection on the already-owned pilot box. |
| M-18 | MED | **Machine ends stripped 10 mm is the wrong prep for IDC taps.** RFQ ships every landed field lead stripped, and asks the shop about it as open question 4 — but the pilot landing method is 3M Scotchlok-class IDC piercing taps, which need insulation **intact**. | Answer the RFQ's own question before issuing: un-stripped for IDC-tap leads. |
| M-19 | MED | **Cam leads cut at 1.2 m commit to a C2A landing** the project may not use — SA/SB/TA1/TA2 have no identified C2A cavity, cold mapping is a CLOSED method, and the approved fallback (tap the cams **at the switches**, out on the mechanism) is also the r6 spec's answer to the AC-chatter problem. | Either build W01–W05 long, or hold those 5 leads out of the assembly and field-build after the powered session. |
| M-20 | MED | **J14 label regressed to "STOP/CIS"** on permanent printed heat-shrink, naming a device physically proven absent on lanes 21/22 (2026-07-24), and **drops the "OR JUMPER" prohibition** — the one instruction the whole Candidate-C safety posture depends on, in a package that elsewhere teaches installers that a J14 jumper is a normal feature. | `docs/WSL-LANE-HARNESS-A_wirelist_rev1.csv` W33/W34 → *"J14-3/4 STOP/CTRL-PWR — OPEN — DO NOT LAND **OR JUMPER**"*. |
| M-21 | MED | **T-Camera 12 V dies with T-VISION.** The camera runs on +12 VDC from the T-VISION board Phase 8 retires. §D's power chain is exactly four fused branches with D3 buying exactly 4 blocks/pair — no fifth branch, no spare position, no camera lead, no camera entry in the wire list. The pilot sidesteps it by leaving T-VISION powered. | Add a 5th fused 12 V branch off the splitter + a 2-conductor field lead + gland, or accept a separate 12 V supply. |
| M-22 | MED | **No PO sequencing / schedule anywhere** (see H4). The only schedule statement in the program is the harness RFQ's 3+8 weeks — making the harness the long pole, and it is simultaneously the PO that cannot issue until wire list Rev 2. Rollout cadence (7–10 clean soak days/pair) puts the last pair ~5–6 months after delivery regardless. | Fold into the §0 block from H4. |
| M-23 | MED | **I²C path is ~750 mm through four screw-terminal transitions on untwisted UL1007.** C8 caps the ribbon at 150 mm *"SHORT is the requirement — I²C integrity"*, but the chain the BOM buys is J1 → 150 mm ribbon → IDC20 screw terminals → ~8 discrete 22 AWG jumpers → F-1019 screw terminals → 200 mm ribbon → Pi. No I²C length/capacitance budget exists in the repo. One of the two buses is bit-banged. | Needs an electrical opinion before the 16-pair quantity — not before the pilot. |
| L-01 | LOW | **Three JLC-placed parts inside JLC's 5 mm edge clearance** on the bottom edge (U43 pad copper 1.360 mm, D97 1.860, R82 2.200); rev-C had 13.2 mm. Left/right edges are >56 mm clear so a rail is unlikely — but a silently added, V-scored bottom rail depanelized 1.36 mm from a DIP-4 body risks cracked joints fleet-wide. | Add to the G12 list: *"If JLC proposes an edge rail it goes on the LEFT or RIGHT edge, never the bottom; pre-approve the resulting outline change so the '250 × 240 preview' gate does not read as a mismatch."* |
| L-02 | LOW | **DIELL_L/R run at 0.76–1.03 mA, not the 1.12–1.34 mA FA-9 and the fab README tell the technician to qualify at** — the source saturates at ~0.7 V, not 0 V. These are the two thinnest-margin channels and they drive ball detection for both scoring and ball-accept. Still passes (2.7× after aging). | Add a DIELL row to FA-9's condition table: qualify at 1.03 mA / 0.82 mA via a 0.7 V source emulation, not a dead short. Re-measure the 0.7 V level **under ~1 mA of load** at the powered session (the existing figure is open-circuit DMM). |
| L-03 | LOW | **The STOP-SHIP pull-configuration gate is not executable on the shipping firmware.** `README-fab-package.txt:50-63` declares PUE/PDE readback STOP-SHIP; the pinned v1.2.3 image has **zero** reads of PADS_BANK0 and no pad field in `id`/`hb`. Scope is 8 of 40 channels (the MCP half **is** genuinely enforced with write+readback+raise). Closable at the bench via SWD on the Pico's own SWCLK/GND/SWDIO, or inferable from FA-9 steps 3/5. | Restate FA-9 step 1 / FA-11 step 4 / the fab README as *"pull configuration is established by the hash-locked image identity (FA-11 steps 1–3) + source review + the test_v12 host assertion; on-target readback is by SWD pad-register read, not a firmware field."* **Do not reopen the frozen firmware for this.** |
| L-04 | LOW | **No strain relief for 144 M20 compression glands** — the harness as quoted has no jacket, sleeve or shield. The pilot build sheet has the line (*"split loom ~10 mm, Bundle 1 and Bundle 3 in separate looms ≥50 mm apart, ~4 m/lane"*); the fleet BOM and RFQ Tier 2 lost it. Without it the IP68 seal never forms and NEMA 12 is void in a dust/oil-mist room; the layout's shield-drain rule is unexecutable. **Fully retrofittable after delivery.** | Add ~136 m of 10 mm split loom (~$150) to §F; swap the two small-bundle gland positions (J13 lamp run, J14) from M20 to M16/M12; add ~9 tie mounts/pair to F5 for the gland wall. |
| L-05 | LOW | **No in-box Cat6 patch cable line** (splitter RJ45 → Pi), and E7's M20 glands (6–12 mm) will not pass an RJ45 plug (~13.4 mm over the latch). | Add 16 (+2) × ~300 mm Cat6 to §C; decide field-crimp-inside-the-box (needs plugs + crimper + tester) vs M25/RJ45-rated entry. |
| L-06 | LOW | **USB composite capture dongle has no fleet line** (16 needed, ~$20 ea, ~$320). Gland count is already covered (144+20 = 164 vs 160 needed) and the enclosure ships blank so all holes are field-drilled — the "cut a 10th hole in a sealed box" scenario is not real. Camera scoring at controller cutover is separately blocked in software anyway. | Add a §C line: 16 (+2) VIXLW-class UVC dongles. Drill 10 glands/box. |
| L-07 | LOW | **NE555 timing cap C11** is an unspecified aluminium electrolytic (C19184134) with no temperature class, endurance or leakage limit, on a node where only ~15.5 µA is available at threshold. Failure direction is a **stretched** timeout (11 s → 14–19 s), not a disabled watchdog — and the RP2040's `MAX_MOTION_MS = 8000` latch drops RP_OK **ahead of** the NE555 regardless of C11. | Pin C11 to a 105 °C / ≥2000 h part with a specified leakage limit, preferably 6.3–10 V rather than 16 V (~$0.05/board, no copper). Add a numeric drop-time band to FA-7 and record it per serial. |
| L-08 | LOW | **A8 centre support is 66 mm from the load it carries.** Real concern is not the MKDS or relays but the seven 0805 ceramics C4–C10 at x=230: ~550 µε with the single pad against a 500–750 µε 0805 flex limit. Window at x=198–240 is verified clear of THT pads. | A8: 1 → **3** adhesive standoffs/board (32 → 96 + spares, ~$40). Record placement at ~(232,100) and ~(232,170) on the F7 wire-map card. |
| L-09 | LOW | **M3 × 18 into a 12 mm standoff leaves only ~4.0 mm of brass engagement** (~1.3×d, under the 1.5×d rule) once the A7 flat + split washers are counted, and A7's 7 mm OD washer is an undersized bearing face on painted plywood. *(The "bottoming out" and "intermittent grounding" mechanisms are refuted — MK1–MK4 are NPTH with no annular, no net.)* | A5 → **M3 × 20**; add M3 fender washers ≥16 mm OD to A7. Confirm actual plywood thickness (15/32″ vs ½″). ~$40 fleet. |
| L-10 | LOW | **Backplate BOM says "Flash BEFORE soldering" (A2); the r7 hand-solder BOM says "program after assembly."** A rev-C workaround vs rev-D design intent (J1 moved to (135.5, 10), USB keep-out D12), unresolved because **FA-4 has never been executed** — no rev-D board exists. | Leave A2's conservative note **as-is** until FA-4 passes on board #1, then relax it. Do not relax ahead of the gate. |
| L-11 | LOW | **Field-stuffed Cflt caps and spare-board mounting hardware are in no PO.** Locked identities exist (2.2 µF C19110, 10 nF C17702767) but appear in no purchasing section; A4 standoffs are 128 (+16) while A5/A6/A7 are flat 128 — the two spare boards get standoffs and no screws. | One reel of each cap; raise A5/A6/A7 to 144/144/288. |
| L-12 | LOW | **F2/F3 selectivity is unproven** — depends on whether the DDR-60G-5 uses constant-current or **hiccup** limiting. In hiccup mode (~2 ms pulses, ~1 % duty) the 2 A fast element may never reach its ~4.5 A²s melting I²t, so the "H-23 fix" would not isolate a faulted board and the whole box cycles instead. | One datasheet line. Ask Mean Well or scope it on the pilot. |
| L-13 | LOW | **Row-39 keep-clear is scoped x 52–92 mm; measured it runs to x 180**, and the **top** edge (which faces down on Board A, rotated 180°) holds the board's closest-to-edge copper (VCC_5V via at 1.150 mm) and is not covered. *(No conductive part is being ordered that goes near either edge — the plywood is the answer. Safety framing refuted: the un-scoped span is GND-only.)* | Extend the G12 visual edge pass to **both** edges. |
| L-14 | LOW | **Breakout modules bought through a consumer channel:** C5 = CZH-LABS F-1019 (Amazon house brand, no authorized distributor, no second source) at 18 units; C7 has **no manufacturer PN at all** at 36 units. The project already solved both — `docs/phase8_revB_production_harness_parts.csv:2` carries **Winford BRK2x10-DIN** ×32, ships direct. | Put Winford on C7. Find a second source or accept the risk on C5. |
| L-15 | LOW | **The 36×30 box only works hung portrait** (780 mm stack fits only the 838 mm direction), but the sourcing brief explicitly allows *"either orientation"*. Hung landscape the panel is 686 mm and the layout fails immediately. | State portrait as a requirement on the enclosure PO and the sourcing brief. |
| L-16 | LOW | **No wall-mount hardware** for sixteen ~45–50 kg loaded enclosures — no anchors, lag bolts, unistrut or brackets in §A–F. | Add a §E line once the mounting surface at each pair is surveyed. |
| L-17 | LOW | **The camera/monitor census was never taken.** "T-Camera, 1 per pair" and "monitor accepts HDMI" are asserted fleet-wide from one visit to lanes 21/22. Cameras are EOL from QubicaAMF. A missing/dead/misaimed camera on any of the other 15 pairs means no scoring path at all — and the fix is a camera, a mount, a 12 V feed and a fresh calibration, not a $20 dongle. | Fold a camera + monitor-input census into the site survey before wave 2. |
| L-18 | LOW | **Zero spares on A2/A3** (34 for 34 boards) while every other line carries ~10 %; both are hand-soldered and both are flagged no-substitution. | Already corrected to 38 in §5. |

---

## 7. WHAT WAS VERIFIED CLEAN — do not re-check

**The r7 fab package is sound. This is the strongest part of the whole submission.**

- **Manifest integrity:** all 46 SHA-256 entries verify byte-for-byte on disk; all byte counts match; zero mismatches, zero missing, no untracked strays. `source_board_sha256` and `source_netlist_sha256` match the live `.kicad_pcb` and `.net` — **no drift between as-exported and live design**.
- **Determinism:** re-ran `scripts/generate_kicad_netlist_revD.py` under KiCad 10.0.2 — regenerated netlist is **byte-identical**. Re-ran `scripts/export_fab_revD.py` into a clean scratch dir — all 11 assembly CSVs byte-identical, all 11 gerbers geometrically identical (diff clean after stripping only timestamps).
- **DRC:** re-ran `kicad-cli pcb drc --severity-all` independently — **0 violations / 0 unconnected / 0 footprint errors**, matching the shipped report. Proved the custom `.kicad_dru` is **not vacuous** with a positive control.
- **Audit:** re-ran `scripts/audit_revD_board.py` in both routed-board and netlist modes — **ALL PASS**, exit 0. `Safety_Rail == 13` STOP-SHIP guard holds.
- **BOM ↔ CPL ↔ netlist:** 391 parts − 68 DNP = 323 placed = 306 JLC + 17 hand-solder. Upload-BOM refdes set == CPL set == part-lock set (306 each, zero symmetric difference). Every BOM Quantity equals its own designator count. **Zero DNP leaks** into any JLC file. Zero blank/placeholder LCSC fields; no "MATCH AT UPLOAD" rows.
- **r6 topology, per channel, 40/40, zero exceptions:** Rin(2k2) → Dser(anode) / Dser(cathode) = FIELD_LED → PC817 LED anode; Dclamp genuinely **anti-parallel across the LED only**; all 40 Cflt DNP (8 × 10 nF fast / 32 × 2.2 µF slow). **Diode polarity independently verified from the placed board** via footprint F.Fab geometry, silkscreen, symbol and netlist — four independent artifacts agree. No r6 part touches FIELD_WET_V, RELAY_ENABLE_RAIL, RAIL_GATE, or either SAFE_* net.
- **The rev-B relay-footprint killer cannot recur.** K1–K7 pad→net map is **byte-identical** to the rev-C netlist that was fabricated and bench-validated 6/6 relays. Zero pad-net changes on any K refdes.
- **rev-C → rev-D regression diff (by SKiDL tag, so the 46-refdes shift cannot hide anything):** the **only** pad-net change on any common part is the 32 Rin.2 nodes moving to FIELD_RIN_n — precisely the r6 diode insertion. Zero tags removed. No previously bench-validated wiring silently changed.
- **Isolation re-derived independently** by bracketing KiCad's own DRC engine: LOGIC↔FIELD 2.6505 mm, LOGIC↔MACHINE 3.3505 mm, MACHINE ch-to-ch ≥2.10 mm, r6 FIELD_LED 0.910 mm. The "half-micron margin" reading is wrong — 2.65 mm is already 2.5 mm requirement + 0.15 mm etch allowance, i.e. **as-fabbed worst case 2.54 mm against a 2.5 mm requirement**.
- **Software/firmware contracts match the board exactly.** MCP23017 bit maps == `IN_A_MAP` / `IN_B_MAP_REVD` / `OUT_A_MAP` in `lane_node/controller_io.py`. RP2040 GP6–GP13 == `config.h` pin map == netlist A1 pads. REV_ID straps are populated 10 k and decode to 0b01 == `REV_ID_REVD`. Host-side revision gating is **fail-closed** (9 distinct rejection reasons). Firmware identity chain (UF2 `d5570efd…`, manifest `ea8ea4ce…`, cfg `05d808411db4bb0d`) verifies exactly, all 6 source inputs hash-match, and `release.ps1 -VerifyOnly` returns **VERIFIED** with no toolchain.
- **Connector pole counts match the ordered Phoenix PNs, all 16 J-refdes.** Pin-to-signal map cross-checked position-by-position against the harness wire list — **every landed lead maps to the right board pin**. No 3.5 vs 3.81 mm pitch mismatch anywhere. The 1.4 mm MCV drill (vs KiCad stock 1.2 mm) is a correct and necessary fix.
- **Relay output polarity correct on all six pairs** (pad 1 = COM, pad 3 = NO; wire list agrees). **J14 safety topology correct** (`SAFE_TBSC_RETURN` connects only J14-2/J14-3 — a board-internal link; JMP1 on 1-2 bypasses TBSC, W33/W34 leave Stop open).
- **J16 protection stack verified on the board:** polyfuse in series, SRV05-4 VP **upstream** of F1 (the round-3 sneak-path fix is really there), JP1 DNP so J16_3V3 is default-open, TCA4307 in/out not swapped.
- **Tap stages Q17–Q20 cannot back-drive anything.** The Pico appears only on drain nets; no `TAP_GATE_*` reaches A1; none touches the safety rail. Every driver gate/base has a pull-down — the rail is fail-safe-dead on a floating driver.
- **Power/thermal budget re-derived from the netlist, not the doc:** per-board 0.69–0.9 A confirmed; pair vs DDR-60G-5 = 28–44 % of 10.8 A; PoE 34–62 % of a Class-6 PD; sealed-box ΔT computes to **1.6–4.0 °C** (the BOM's "+8 °C" is 2–3× conservative). Brownout behaviour is fail-safe by construction — nothing can re-arm on a bare power cycle. r6 genuinely **reduces** 5 V load (74.5 → 58.1 mA on FIELD_WET_V).
- **All r6 electrical arithmetic reproduces**: 1.340 mA @ 5.0 V, 1.121 mA @ 4.5 V, 16.43× CTR margin, 56.17 µA / 45.64 µA sink requirements, 100.3 µA aging bar, the 24 VAC conduction window (8.80 ms on / 7.87 ms off, 12 edges per chatter window), the 951 nF filter minimum, the 2.35 µs edge RC. Reverse-bias topology works in **both** polarities. FA-9's ≥70 °C + aging-reserve gate is adequate.
- **Fab capability:** every via 0.6/0.3 … 1.0/0.5 mm (min annular 0.150 mm = exactly JLC standard), min track 0.25 mm, min PTH 0.3 mm, 250 × 240 × 1.6 mm, 4 layers — **no advanced-process surcharge or DFM query triggered** by geometry.
- **Silk warnings physically present:** all four `KEYED: NOT J3 / J15 / J13 LAMP / J16` legends, `REV ID D=01`, MK pattern 242 × 232 mm matching BOM A4, and **zero copper within 5 mm of any mounting hole**.
- **Backplate BOM house arithmetic** verified row-by-row A1–G8, including the rows that mix per-lane and per-pair scaling. Plywood yield (3 panels/sheet, 6 sheets) correct. E4's part number decodes correctly and its SCE-36P30 panel really is 838 × 686 mm.
- **Harness wire list is internally correct:** 49 leads, arithmetic matches the RFQ summary exactly, the 11 capped DO-NOT-LAND leads correspond exactly to the deliberately deferred channels, and the machine-end-unterminated design correctly supports per-lane cavity variation. The RFQ's **1 + 2 + 31 staged ramp is the one correctly-structured part of the whole order** — mirror it, don't disturb it.

---

## 8. RESIDUAL RISK — what this audit could not determine

| # | Unknown | What closes it |
|---|---|---|
| R-1 | **Distance from a fleet pair enclosure to each machine's C1/C2A, and the in-box run.** No document records either. This is the S4 stop-ship. | **One tape measure, one pair location, ~10 minutes.** Highest value-per-minute item in this list. |
| R-2 | **C1/C2A connector family, housing-vs-contact P/N, contact gender.** The 66101/66099/305183 numbers appear in exactly one BOM line with no source. Wire-range compatibility for 22 AWG cannot be checked without the confirmed dash number. | **20 minutes of measuring at the machine.** Gates G2/G3/G4/G5 — ~$2–3k plus tooling. |
| R-3 | **F-1019 and IDC20 real footprints, and DIN across-rail envelopes.** Drives the 780 mm panel figure, E4's $1.6–3.1k upsize, E1 rail quantity, and C8 ribbon length. | Buy **one** of each and measure. |
| R-4 | **Loaded FIELD_WET_V and contact conduction current.** rev-D has never been fabricated; the only real readings (11 V, 14 V) are open-circuit on an unbled rail. The design's "5 V nominal" is itself an assumption — 4.55 mA of bleed is 2.3 % of the TMA's 200 mA, below the ~10 % minimum load an unregulated brick wants. And nobody has measured gripper contact resistance at 1 mA. | Powered characterization session: TP4 under load + minimum reliable contact current per dry-wetted class. Gates M-02. |
| R-5 | **Cam AC/DC class, RMS, frequency (SA/SB/SC/TA1/TA2/TB).** Two cold-mapping attempts failed; the method is closed. Determines whether cams land at C2A or at the switches (M-19), and which firmware remedy applies. A DMM cannot separate 60 Hz AC from a chopped DC train. | Powered at-machine session **with a scope**. |
| R-6 | **PC817B CTR at the r6 operating point, for the actual UMW lot.** The whole 16.4× disposition rests on the part-lock's B-rank (130–260 %). An un-ranked shipment drops the floor 2.6× to ~6.3×. Also: PC817 turn-off time at RL = 47 kΩ cannot be derived from the datasheet's 100 Ω condition. | **FA-9**, per channel, at loaded minimum and ≥70 °C. This is the gate that makes wave 1 a first article. |
| R-7 | **JLC part-rotation convention** for the parts that are NEW in rev-D (F1 1206L020YR, U46 TCA4307 VSSOP-8, U47 SRV05-4 SOT-23-6, Q17–Q20 2N7002LT1G). No rotation-correction table exists in the exporter; the CPL ships raw KiCad rotations. Retired by prior-build inference for the optos/diodes/relays only. | **FA-16** unpowered orientation census. Also give it a specific look during G12. |
| R-8 | **Live LCSC/DigiKey/Mouser stock** — specifically C26108 (M-01) and Phoenix 1843680/1843703/1840489 at fleet quantity. | Distributor quote at the moment of ordering. |
| R-9 | **How JLC's DFM will treat the 1.36 mm bottom-edge component clearance** (L-01), and whether they will add and charge for a break-away rail. | The real upload preview + quote. Decide the answer **before** uploading so the "250 × 240" acceptance gate does not read as a mismatch. |
| R-10 | **DDR-60G-5 protection mode** (constant-current vs hiccup) — decides whether F2/F3 achieve selectivity (L-12) — and its exact trim range and OVP trip. | One datasheet, or scope the pilot. |
| R-11 | **Saginaw collar-stud thread projection and count** on an SCE-36EL3008LP. Not published in any reachable datasheet. Decides whether a 12.7 mm plywood panel can be nutted at all (M-17). | Tape measure on the already-owned pilot SCE-24EL2008LP, or a call to Saginaw. |
| R-12 | **Whether the unified scoring + control daemon ships before cutover.** `docs/phase8_trackB_controller_cutover_runbook.md` §2 states camera scoring **goes dark at controller cutover** with current code. If it does not ship, each pair needs a **second** Pi, SD card, DRP2, USB-C pigtail and fuse branch — and the DIN band was not sized for it. | Software decision. Affects C1's Pi count, D3's fuse-block count, and the panel layout. Resolve before the panel freezes. |
| R-13 | **JLC quote for the rev-D board.** None exists in the repo, and the only board-cost figure anywhere is for the superseded rev-A 100 × 100 mm 2-layer board. Nobody knows the PCBA turn for 34 boards at ~192 THT joints each. | Get the quote as part of wave 1. |
| R-14 | **G12 visual pass.** I verified the layer set, DRC, drill table, BOM/CPL equality and 250.0 × 240.0 mm outline **numerically** — I did not render the plots. The K1–K7 pad-net map, KEYED silk legibility, silk-over-pad clipping, the USB keep-out and the row-39 bottom edge still need a human eye. | One sitting with `review/wsl-phase8b-revD-review-layers.pdf` and the JLC preview. |

**One housekeeping trap:** `kicad/revD/~wsl-phase8b-revD.kicad_pro.lck` exists but is stale. No drift resulted, but a future KiCad save would silently break `source_board_sha256`. **Re-verify that hash immediately before uploading.**

---

## 9. REFUTED — do not re-raise

These were investigated and dismissed with cause. Full refutation records are in the audit dataset; one-line reasons here so they do not resurface.

| Claim | Why dismissed |
|---|---|
| AC cam chatter drops RP_OK and disables the lane | Accurate but a verbatim restatement of the project's own gate-7/gate-15/§3.2 scope. Fail-safe by design and documented as such. Changes nothing ordered. |
| "Protected by construction" has no upper voltage bound | The bound **is** declared (`.kicad_dru` header ≤34 Vpk; 75 V V_RRM at 2.6–2.7×), and the AUX prohibition already exists verbatim in FA-5 and the diagnostics scope. FOUL is measured at ~5 VDC, not 120 VAC. |
| CP-MSTB profiles unbuyable — Phoenix MOQ 100 | False. DigiKey PN 348744 sells at **MOQ 1, $0.10 ea, 53,135 in stock**. |
| B6/B7 same PN "different colour" is unorderable | Misreads the design — the discriminator is a **heat-shrink band**, not a plug housing colour, and the proposed substitute PNs would collide with the CP-MSTB pole scheme. *(A residual wording nit is folded into H2.)* |
| F1 = 3 A undersized / F4 = 4 A oversized | Both refuted on the repo's own board power budget. Real F1 current ~1.44–1.6 A = ~50 % of rating; the claimed inrush hazard has ~30× I²t headroom. The 2 A F4 proposal is a nuisance-trip **regression**. |
| No OVP between DDR and loads | The DDR is an **isolated** flyback — a shorted primary cannot put 12 V on the secondary. A rail TVS **is** populated (U47 SRV05-4, VP on VCC_5V, deliberate round-3 change). DDR has OVP at 5.75–7 V. The proposed SMBJ5.0A is un-landable in a screw terminal and clamps too high anyway. |
| E6 buys no usable stud hardware | Premise wrong — the flanged-nut note is a disclaimer in a **grounding-kit** BOM; the enclosure ships bolt pack SCE-122191. *(The thread-projection question survives as M-17.)* |
| Row-39 keep-clear span understated → isolation risk | Measurements right, consequence wrong. Nothing conductive is being ordered near either edge (plywood), and the un-scoped span is GND-only. *(Survives as L-13, checklist scope.)* |
| RFQ never states torque/strip → HIGH | The data **is** in the RFQ package (§15 attachment 4, Phoenix datasheets) and IPC/WHMA-A-620 Class 2 is imposed. Arithmetic also off. *(A belt-and-braces restatement is folded into S5.)* |
| 22 AWG vs size-16 contacts incompatible | TE Type III+ size-16 **is** catalogued 24–20 AWG. Our 22 AWG never enters a size-16 barrel under the approved interposer-pigtail architecture. The claim's own proposed 20 AWG fix would also be out of range. |
| Firmware Phase-0 detectors compiled OFF | Explicitly documented in the cutover runbook (`:82`, `:237`, `:328`) as a **G3 ABORT gate**. The posture is intentional and gated. |
| A2 "flash before soldering" is stale | Rests on a firmware claim I disproved (`DEBUG_USB=0` in the release, so `stdio_init_all()` is compiled out and picotool cannot see a running board). Keep the conservative note until FA-4 passes. *(Documented as L-10.)* |
| OG-1 forbids this purchase / enclosure layout unversioned | OG-1 is a correctly-tracked open gate re-affirmed in the newest release report; the plywood backplate makes it financially decoupled. The Downloads HTML is a dimensioned Rev-2 drawing with its own supersede banner and its own space-finding gate. *(The real enclosure issues are M-06/M-07.)* |
| Various duplicate reports of the board-connector gap and the B1–B5 double-buy | Real — **merged** into H1 and H2 rather than counted four and three times. |

---

**Bottom line:** the engineering is in good shape — the r7 package is one of the cleanest artifacts in this repo and it survived every independent re-derivation I threw at it. What is not in good shape is the **paperwork around the purchase**: three documents point at the wrong package, a live upload packet for the wrong board has no tombstone, 510 connectors are on no list, 180 plugs are double-bought, the harness leads are cut to the wrong length, and the order is scoped at fleet quantity against gates that say first article. Every one of those is a text edit or a purchase-order line. Fix them this week, spend $3–5k, run the first article, then spend the other $25k.
