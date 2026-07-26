# rev-D full-assembly assessment — "let JLC solder everything"

Date: 2026-07-26 · Board: rev-D r8, 250 × 240 mm, 4-layer · Order: 34 boards (fleet)
Question: can JLCPCB solder all 17 hand-solder placements, at what cost, and what breaks?

---

## 1. ANSWER

**YES-EXCEPT-1 — and not as a service-tier upgrade.** JLC can place 16 of the 17; the only
exception is **J1**, and it is excluded because its part identity has never been verified
(BOM status: "Candidate — verify body/keying"), not because JLC lacks the capability. The
premise behind the ask is wrong in a way that saves money: **there is no upgraded PCBA tier to
buy.** JLC offers exactly two assembly services, Economic and Standard; this order is already
on Standard (mandatory anyway above Economic's board-count cap), and Standard already
through-hole-assembles 190 joints per board today — the 40 PC817 DIP-4 optos and 6 G5LE
relays. JLC's own FAQ states that parts flagged "wave soldering" in its library "will be
assembled manually," so the new connector joints use the identical process the board already
relies on. The measured labour delta for moving all 17 is **$71–79 across the entire fleet**
($2.09–2.32/board). The real constraint is not process and not price — it is **sourcing**: 6
of the 10 distinct part types have no confirmed JLCPCB library entry and must route through
Global Sourcing or consignment, which adds $125–340 in channel fees, a mandatory JLC
engineering-approval step, and 1–3 weeks of serialized logistics. Spend the money on the
sourcing problem, not on a tier that does not exist.

---

## 2. THE SPLIT I RECOMMEND

Three waves, ordered by risk and lead time. **Wave 1 is free and should be done regardless of
what the owner decides about the rest.**

| Ref | Qty | MPN | Verdict | Wave | Why |
|---|---|---|---|---|---|
| J2 | 1 | Phoenix 1715734 (MKDS 1,5/3-5,08) | **JLC** | 1 | In JLC library as **C480520**, Wave Soldering, Economic+Standard. Unique PN, uncoded, unkeyed. LCSC price ~$0.51 @30+ vs $2.25 DigiKey estimate in `phase8_revB_preorder_parts.csv` — cheaper than buying it ourselves. |
| J6–J11 | 6 | Phoenix 1715721 (MKDS 1,5/2-5,08) | **JLC** | 1 | In library as **C5183929** (239 pcs — thin) and, better, **C480516**, same Phoenix MPN, 3,214 pcs. Uncoded, unkeyed, no flash gate. See §3 note: the repo's BOM cites the thin line. |
| J14 | 1 | Phoenix 1843622 (MCV 1,5/4-G-3,5) | **JLC** | 1 | In library as **C480549**, Wave Soldering, Economic+Standard, 451 pcs. It is *not* one of the FA-8 coded pairs — safety-loop header, no rib cut. LCSC ~$0.84 @30+ vs $1.25 DigiKey. |
| J3 | 1 | Phoenix 1843680 (MCV 1,5/10-G-3,5) | **JLC — conditional** | 2 | Not resolved in the library by MPN search (search-by-numeric-MPN gives false negatives — see §3). Needs a Global Sourcing quote or consignment. Coding rib is cut **post-solder on the board's own header** per FA-8 step 2, so JLC ships one uncoded PN. |
| J4 | 1 | Phoenix 1843729 (MCV 1,5/14-G-3,5) | **JLC — conditional** | 2 | Same route as J3. Uncoded, unique pole count. |
| J5 | 1 | Phoenix 1843703 (MCV 1,5/12-G-3,5) | **JLC — conditional** | 2 | Library entry **C3019636** exists but shows only ~7 pcs — cannot cover 34. Global Sourcing or consignment. |
| J13 | 1 | Phoenix 1843648 (MCV 1,5/6-G-3,5) | **JLC — conditional** | 2 | Same route as J3. Coded vs J16 post-solder. |
| J15 | 1 | Phoenix 1843680 | **JLC — conditional** | 2 | Same PN as J3. One bin, one BOM line, qty 2/board. Coding is a post-solder cut, so there is no two-bin problem. |
| J16 | 1 | Phoenix 1843648 | **JLC — conditional** | 2 | Same PN as J13. Same reasoning. |
| U45 | 1 | TRACO TMA 0505S | **JLC — conditional** | 2 | Library entry **C5454708** exists at ~30 pcs against a need of 34 (38 with spares) and is OOS at LCSC retail. **Do not let JLC substitute** — the lock says "no substitution without pinout and isolation review." Consign from DigiKey 1951-1003-ND (5,964 in stock, $4.32/10+) or Global Source the exact PN. Rides along with the Wave-2 parcel at ~zero marginal logistics. |
| A1 | 1 | Raspberry Pi SC0915 (Pico) | **JLC** | 3 | Not a THT part — `Module:RaspberryPi_Pico_SMD`, 96 SMD pads, 0 drills. Raspberry Pi designs it for module reflow. Requires a **pinned C-number** and a silkscreen photo gate (§5). See §3 for why "flash before soldering" is a dead argument. |
| **J1** | 1 | CNC Tech 3020-20-0100-00 | **HAND — for now** | — | The only genuine exclusion. Status is "Candidate — verify body/keying"; it has never been checked against the KiCad `IDC-Header_2x10_P2.54mm_Vertical` footprint, the mating ribbon socket is unbought, and the crimp orientation is flagged "confirm before crimping." **Escalation path:** J1 is *not* Locked, so re-specifying it to a library-native DIN 41651 box header (e.g. BH254V-20P / C492444, 10,481 pcs, $0.12) is legitimate and would move 20 joints/board — 680 fleet-wide — into Wave 1. That is an owner call, not mine (see §6 Q4). |

**Totals:** Wave 1 = 8 placements, 19 THT joints/board. Wave 2 = 7 placements, 61 THT joints/board.
Wave 3 = A1, 96 SMD pads. J1 stays hand = 20 joints/board, 680 fleet-wide.

### The case for keeping J1 hand-soldered
It is the one part on the list whose *identity* is unproven. The board-side footprint is
generic (stock KiCad, DIN 41651 / IEC 60603-13, 1.0 mm drill on 1.7 mm pads at 2.54 mm pitch),
so any conforming 20-way box header drops in — but that also means locking the wrong shroud or
key orientation is invisible until a ribbon is presented. The rev-B bring-up guide is explicit:
"the header solders fine either way, but get pin-1 orientation right relative to the Pi." That
verification is 15 minutes of work against the existing rev-B board #1, and until it happens
J1 should not be committed to 34 boards by anyone — JLC or owner.

### The case for sending A1 (the Pico) — this is the finding that changes the plan
1. **The "flash before soldering" note is stale rev-C geometry.** In rev-D, A1 sits at
   (100, 33) rot 0 with the micro-USB facing the board's own y=0 edge and 5.70 mm of empty
   board in front of it. J1 was moved from (126, 10) to (135.5, 10) — 25.4 mm of lateral
   separation, with J2 physically interposed. Nothing occupies x 88–114 below y 5.7. The
   16 × 12 × 40 mm USB keep-out (D12) is drawn on Dwgs.User and is on the G12 inspection list.
   The rev-C jam condition no longer exists.
2. **Pre-flashing buys exactly one flash cycle, then expires.** The arming flags
   (`CAM_SA_STOP_ENABLED`, `CAM_SA_TRIP`, `CAM_TA1_TRIP`, `INTERLOCK_ECHO_ENABLED`,
   `MOTION_NO_RUN_ENABLED`) are compile-time; the cutover image does not exist yet and will be
   a different hash-locked UF2. The repo states it plainly: the compiled-OFF detectors and "?"
   polarity sentinels "guarantee at least one reflash per board after Phase 0, possibly
   in-enclosure." **Post-assembly USB flashing is already mandatory fleet-wide.** Hand-soldering
   A1 postpones the problem by one flash and leaves you in the identical position.
3. **Two independent recovery paths survive reflow.** The shaved right-angle micro-B cable is
   proven — it flashed a soldered rev-B board whose geometry was strictly worse. And the Pico's
   own SWCLK/GND/SWDIO castellated holes are on the module's top face at the end opposite the
   USB, in a courtyard whose nearest neighbour is 14 mm away; audit L-03 already relies on that
   path to close a different gate.
4. **Cost of insisting otherwise:** 34 hand-soldered 40-pad castellated LGA modules — the
   hardest single operation on the board, with pads partly under the module body — to protect a
   mitigation that has already expired. That is roughly 6–9 hours of the highest-risk soldering
   in the build, bought for nothing.

**Caveat, accepted knowingly:** FA-4 (unmodified micro-B seats with the J1 ribbon mated) has
never been run and cannot be run before a fleet PO commits all 34 A1 placements. Under the
recorded G15 fleet-quantity decision there is no first article to gate on. Record this as an
explicit pre-order risk acceptance with the shaved cable + module-SWD rig as the named
contingency. Do not pretend it was tested.

---

## 3. BLOCKERS

Ranked by whether they stop the order.

### B1 — The fleet order is already blocked, independent of this decision (**HARD**)
`docs/phase8_revD_PREORDER_FINAL_AUDIT_2026-07-25.md` records that the G15
EXPERIMENTAL-ORDER acceptance line at `docs/phase8_revD_readiness_checklist.md:350` is blank,
and that **both** the 0.4807 mm field-pin clearance (vs IPC-2221B's 0.6 mm) and the PC817B CTR
item are dispositioned to the *fleet revision* — i.e. 34 boards would be built to a revision
the project has already committed to changing. Nothing in this assessment moves that. If G15
is not signed, the assembly question is moot.

### B2 — 6 of 10 part types have no confirmed library entry (**HARD until quoted, then routine**)
Confirmed present in JLC's assembly library via part-detail pages (the authoritative source):
1715721 (C5183929 / C480516), 1715734 (C480520), 1843622 (C480549), 1843703 (C3019636, stock ~7),
SC0915 (C9900019762) and Pico (C7203002), TMA0505S (C5454708, stock ~30).
Unresolved in either direction: **1843680, 1843729, 1843648, CNC Tech 3020-20-0100-00.**

> **Method warning — do not repeat this mistake.** Searching JLC/LCSC by bare numeric Phoenix
> MPN produces guaranteed false negatives. `jlcpcb.com/parts/componentSearch?searchTxt=1843622`
> returns "0 Found" while `jlcpcb.com/partdetail/C480549` returns the part, in stock, marked
> Wave Soldering / Economic and Standard. **Absence of a search hit is not evidence of absence.**
> Resolve by C-number or by a free Global Sourcing quote.

Route options, both with a mandatory JLC engineering-approval step *before* parts move:
- **Global Sourcing** (self-serve, JLC buys the exact MPN from Western distributors, 9–20
  business days + 1–3 day review): $20 commodity inspection per part type, 3–30 % customs duty,
  $0.017/pin loose handling (max $0.078/component). **Non-cancellable once paid.**
- **Consignment** (owner buys, ships to Zhuhai): $45 customs service (<5000 CNY parcel), owner
  pays DDP freight, JLC explicitly disclaims quality liability for consigned parts, and
  "only parts with JLC number can be consigned" — everything else needs written approval first.

Quote Global Sourcing **first** — it is free, non-binding, and it also reveals whether JLC
beats DigiKey's historically 8–20 week Phoenix lead time on 1843680/1843703.

### B3 — JLC's own consignment T&C contradicts itself on mixing (**HARD — settle by support ticket**)
The consignment Terms & Conditions state consigned parts "can only be used together with global
sourcing parts, instead of JLCPCB parts." The how-to page reads it per-part ("for the same part
A, JLC parts cannot be mixed with consigned parts… you can use JLC parts for part A and
consigned parts for part B"). **If the order-level reading governs, consigning 6 part types
forces all 27 existing JLC-library lines onto Global Sourcing** — a far larger cost and
schedule hit than anything else in this document, and the plan fails at any price. Get this in
writing from JLC support before spending a dollar.

### B4 — Substitution is forbidden; say so in writing before requesting a quote (**PROCESS**)
If JLC cannot source an exact Phoenix PN, the answer is "that refdes stays hand-solder," **not**
"substitute an equivalent." Substituting an MCV header cascades: FR-2 and FR-9 (footprint-vs-
datasheet, the `_D1.4` locals) invalidate → netlist regen → placement + DRC → **full re-route**
(the run log records that the wider J13.4 `_D1.4` pad already pinched the VCC_3V3 IN2 trunk to a
0.4 mm gap once) → and it invalidates the mating plugs 1840447/1840489/1840463/1840405/1840382,
the CP-MSTB coding scheme, FA-8's entire refusal matrix, and the harness RFQ's 185 vendor-fitted
plugs. That is a board re-spin plus a harness re-spec, not a sourcing choice.

### B5 — FA-10 cannot be executed as written (**MEDIUM — rewrite required**)
FA-10 is an *ordering* gate, not a test: solder one MCV header, verify insertion force and
solder fill, **then** do the remaining six. It is the only physical proof of the project-local
`_D1.4` footprint, which has never been built. If JLC solders all seven, that gate disappears
and 2,108 joints land on unproven geometry at once. Replace it with an **incoming-inspection**
step on board #1 (bottom-side fillet + barrel fill on all 62 T8 barrels, before boards 2–34 are
unpacked). Note the drill is defensible: 1.4 mm is exactly the IPC-2222 Level A number for a
0.8 × 0.8 mm pin (1.131 mm diagonal + 0.25 mm), and JLC's annular-ring floor is 0.15 mm against
this footprint's 0.30 mm — 2× margin. Separately, **the FR-9 justification text is wrong**:
Phoenix's own sheet for 1843680 specifies a **1.2 mm** hole, not 1.4 mm. Fix the prose, keep
the drill.

### B6 — G12 Part B: 10 new part classes with zero CPL rotation precedent (**MEDIUM**)
The exporter has no rotation-correction table — `"Rotation": f"{float(row['Rot']):.6f}"` is a raw
KiCad pass-through — and R-7 is retired "by prior-build inference for the optos/diodes/relays
only." A1 and the connectors are in neither class. A systematic 180° error on the six single-row
MCV headers is batch-wide and puts wire entry facing inboard on 34 boards. **Mitigation:**
require JLC's rendered placement preview / 3D check before payment, and annotate expected
orientation per refdes in the r9 README.

### B7 — Sacrificial header stock for FA-8 (**LOW — buy it either way**)
FA-8 makes the header side of the code by cutting a rib at J3 pole 1, J15 pole 10, J13 pole 1,
J16 pole 6 — 4 cuts/board, 136 fleet-wide — and step 1 requires proving it on a sacrificial
part first. This is **unchanged** by the decision: Phoenix designs MCV as a vertical shrouded
header whose coding features face away from the PCB, and FA-8 step 2 already says to cut "on the
board's own headers," i.e. post-solder. But with JLC holding the production headers there are
zero loose ones. **Buy ~10 loose sacrificial MCV headers (2 × 1843680, 2 × 1843648, spares) in
the same PO.** Explicitly reject pre-cutting ribs before consignment: it would split 1843680
into two coded SKUs (J3 @ pole 1, J15 @ pole 10) and 1843648 into two more, and a feeder swap
would then produce a silently mis-keyed board.
Add one line to FA-8: **shear with flush cutters, board supported, never pry** (0.30 mm annular
rings on unproven barrels), and clear swarf before running the refusal matrix.

### B8 — Edge rails and depanelization order (**LOW — one question to JLC**)
Standard PCBA lists edge rails as "Necessary." Today the rail has somewhere safe to go
(minimum courtyard-to-edge over JLC-placed parts: top 10.25 mm, left 20.75 mm, right 53.80 mm,
bottom 0.63 mm). Fully populated, every edge falls under 5 mm (top 0.52 mm at U45, bottom
0.63 mm at U43, left 4.25 mm at J15, right 2.29 mm at J6). The rail *requirement* does not
change — it serves the SMT pass — but if the rail is snapped off **after** connector insertion,
break stress runs within 0.5–4.3 mm of a connector body on 1.4 mm barrels. Ask JLC in writing
whether depanelization precedes or follows THT insertion.

### Non-blockers (raised and dismissed, evidence in §7)
Wave-solder thermal risk (JLC hand-assembles THT), FA-8 destruction (post-solder cut is the
Phoenix-sanctioned order), the two-bin coding dilemma (headers ship uncoded), Phoenix backorder
(1843703 shows 2,139 at DigiKey, 1843680 shows 774 across DigiKey+Mouser — the backorder note
is 6.5 weeks stale and its own mitigation is printed two lines below it), board size
(250 × 240 mm is inside Standard's 70 × 70 – 460 × 500 mm single-board range; the 250 × 250 mm
figure is the *panel* limit — so do **not** let JLC panelize).

---

## 4. COST — delta vs status quo at 34 boards

### Assembly fees (VERIFIED against JLC's published price page)
Status-quo Standard PCBA assembly stack: **$213.36** fleet.

| Item | Basis | Fleet cost |
|---|---|---|
| New manual (THT) joints | 101 joints/bd × 34 = 3,434 × $0.0157 | **$53.91** |
| A1 SMD joints | 96 pads × 34 = 3,264 × $0.0016 | **$5.22** |
| Feeder loading, 10 new part types | 10 × $1.50 | **$15.00** |
| **Full-move delta** | | **$74.13** ($2.18/board) |
| Same, at the $0.0173/joint rate JLC quotes in its FAQ | | **$79.63** |
| *Wave 1 only* (J2 + J6–J11 + J14) | 19 joints/bd = 646 × $0.0157 + 3 feeders | ***$14.64*** |

Fleet totals stay at ~34,578 placed joints — well under JLC's 50,000-joint tier-1 breakpoint,
so **no price-tier change occurs.** Wave/THT adds "+1 more day" to build time. **Any quote
materially above ~$80 of incremental labour is priced on parts sourcing or NRE, not process.**

### Parts-channel fees (the real money) — ESTIMATED, ranges are honest
| Route | Composition | Fleet cost |
|---|---|---|
| Global Sourcing, 6 unlisted types | $20/type inspection ($120) + 3–30 % duty on ~$632 of parts ($19–190) + loose handling (~$23) | **$162–333** |
| Consignment, 6 unlisted types | $45 customs service + DDP express freight US→Zhuhai (**estimated $80–150, not quoted**) | **$125–195** |
| Contingency: PCBA "Large Size" fee | $59.23/order — trigger dimension **not published** by JLC; board is 600 cm², under the 650 cm² *fab* threshold | **$0–59** |

**Parts cost itself is not a delta** — the owner buys these connectors either way. Only channel
fees move. Wave 1 has **zero** parts-channel cost: JLC buys those three PNs the same way it
already buys the PC817s.

### What the money buys
141 hand joints/board × 34 = **4,794 hand joints eliminated** (or 4,114 if J1 stays hand).
At 60–90 min/board including insertion, squaring, and the post-solder visual/continuity checks
this board's safety story requires, that is **34–51 hours of owner bench time**, midpoint ~42 h.

**Bottom line:** ~$250–475 of cash for ~42 hours — roughly $6–11/hour. The decision should be
made on schedule and batch-risk grounds, not on this number. Secondary benefit: it fixes the
solder half of audit finding M-14 (a spare PCBA is currently not a swappable spare — 17 hand
placements plus a Pico flash, unbudgeted), turning a 4–7 h outage-pressure build into a ~1 h
swap.

---

## 5. WHAT HAS TO CHANGE

The split is a **hardcoded refdes set** with seven fail-closed `SystemExit` guards. Nothing
fails silently — the export simply refuses to run until every constant is updated coherently.

### `scripts/export_fab_revD.py` (~80 edited lines)
| Line | Constant / block | Full move | Wave 1 only |
|---|---|---|---|
| :97 | `EXPECTED_HAND_SOLDER = 17` | → `1` (J1 stays) | → `9` |
| :98 | `EXPECTED_JLC_PLACED = 306` | → `322` | → `314` |
| :99 | `EXPECTED_JLC_LINES = 27` | → `43` natural, **37 with 7 aliases** (recommended) | → `35` natural, **30 with aliases** |
| :142–148 | `HAND_SOLDER_REFS` | → `{"J1"}` | remove J2, J6–J11, J14 |
| :484 ff. | `HAND_SOLDER_ROWS` | trim to the J1 row | remove 3 rows |
| :~200–700 | `PART_LOCK` | **+9 primaries + 7 aliases**, each needing a real pinned C-number | +3 primaries + 5 aliases |
| :201, :342 | `locked_spec` strings reading "wave solder" | correct — JLC assembles THT **manually**; this is the project's own hardcoded text, not JLC's | same |
| :1364–65 | README literal naming retired UNI-ROYAL 10M **C26108** while the part-lock CSV in the same package says FOJAN **C2933281** | **fix — independent defect (F8)**, exactly the class the exporter's own comment says it fixed for counts | same |
| :1401 | README literal `"Hand-solder after JLC: A1, J1-J11, …"` | rewrite | rewrite |
| :20–21 | module docstring counts | update | update |

Guards that trip until all of the above is coherent: `:715` (×N, `No JLC part lock for …`),
`:1137` (hand count), `:1140` (JLC placed count), `:1162` (BOM quantity sum), `:1164` (line
count), `:1291` (hand BOM refs vs exclusion set), `:1394` (MATCH-AT-UPLOAD / empty C-number ban).

**Sequencing constraint:** `:1394` bans a JLC line without a pinned C-number, so **the code
change cannot be written until procurement returns real part numbers.** Do B2 first.

**A1 specifically** needs: a pinned C-number, an identity assert alongside the existing
relay/MCP/D_PROT/2N7002/47k/1N4148 hard locks, and a **G12 photo gate** — a photograph
confirming the silkscreen reads "Raspberry Pi Pico" (RP2040), not "Pico 2". JLC's library
carries six SMT-assemblable Pico entries including **C41407547 (Pico 2 / RP2350)**, and the
firmware is RP2040-only (`build_options.pico_board = "pico"`, UF2 `d5570efd…`). See §6 Q3 for
the C-number choice.

### Unchanged — this is why the job is small
`EXPECTED_NETLIST_PARTS = 391`, `EXPECTED_DNP = 68`, `EXPECTED_PLACED = 323`. **The board does
not change.** No re-route, no re-place, no netlist regen, no ERC re-run. CPL rotations for all
17 already exist in the master CPL (`…-cpl.csv`, 324 lines) — the exporter merely filters them
at `:1241`. **Zero new CPL code.** No test file needs editing:
`tests/test_fab_package_notes.py` scrapes only `EXPECTED_DNP` and `EXPECTED_NETLIST_PARTS`.

### Package: an r9 is MANDATORY
`:945` — `REFUSING TO RUN: output directory already exists`. So the change ships as
`kicad/fab_revD_2026-07-27_r9/`. Three tests then assert `len(dirs) == 1` ("exactly one rev-D
fab package may be current"), and `_current_fab_dirs()` exempts only directories carrying a
`_SUPERSEDED*` marker. **r1–r7 each carry one; r8 does not.** Create
`kicad/fab_revD_2026-07-26_r8/_SUPERSEDED_DO_NOT_UPLOAD.txt` or three tests fail. r8 is already
git-tracked (47 files).

### Docs
- `scripts/generate_first_article_docs_revD.py:720` — **FA-10 rewrite** (ordering gate →
  incoming inspection on board #1). FA-10 is *generated*; edit the generator, not the .md.
- `docs/phase8_revD_first_article_pack.md` — regenerate; add the FA-8 cutting technique line.
- `docs/phase8_backplate_BOM.md` — move the transferred refs out of §A′ owner-buy into a
  consignment/Global-Sourcing section; **add ~10 sacrificial MCV headers**; leave the A2
  "Flash BEFORE soldering" note in place until FA-4 passes (per L-10's standing disposition),
  but stop using it as an argument.
- `docs/phase8_revD_readiness_checklist.md` — reopen G11, G12 Part A, G14; add the B3
  consignment/mixing gate and the B8 depanelization question; record the FA-4 risk acceptance.
- `docs/phase8_revD_run_log.md` — correct the FR-9 justification prose (Phoenix specifies
  1.2 mm; 1.4 mm is the IPC-2222 Level A figure and is correct — the *reason* given is wrong).

### Gates
**Re-open:** G11 (export), G12 Part A (package inspection — drill report T8, silk, K1–K7 pad-net
map, review plots), **G12 Part B (CPL rotations — the real risk, see B6)**, G14 (checklist
sign-off). Both G12A and G14 were closed on 2026-07-26 against package r8 and are package-scoped.
**Do NOT re-open** (no board change): G2, G3, G4, G5, G9, G10.

### Effort
~2 h code + ~1 h docs + ~1 h re-export and gate re-verification = **half a day of engineering**,
gated behind the procurement answer, which is the long pole (Global Sourcing review 1–3 business
days, sourcing 9–20 business days; or consignment freight + customs ~1–1.5 weeks).

---

## 6. DECISION FOR THE OWNER

**Do this today, unconditionally:** move **J2, J6–J11, J14** into the JLC BOM. $14.64 fleet,
zero logistics, zero new risk, no consignment, no customs, 646 joints gone. They are library-
native, in-stock, unique-PN, uncoded and unkeyed. This is free money and it is the same code
change as the full move, just smaller.

Then I need answers to five things:

1. **Is G15 signed?** The fleet order is blocked on the blank EXPERIMENTAL-ORDER acceptance line
   at `readiness_checklist.md:350`, with the 0.4807 mm clearance and PC817B CTR both
   dispositioned to the fleet revision. Everything below is moot until that is resolved. Yes/no.

2. **Do I open a JLC support ticket on the consignment/mixing contradiction (B3) before anything
   else?** If the order-level reading governs, this whole plan costs 10× what §4 says. It is one
   email and it gates the decision. Yes/no.

3. **Which Pico C-number do I pin for A1?** Options: **C9900019762** (explicitly SC0915,
   Extended, Economic+Standard — but its manufacturer field reads "JLCPCB Assembly," an internal
   SKU class with no published stock or price) or **C7203002** (RP2040 Pico, ~834–1,647 in
   stock, ~$5.87–6.16, **Standard only** — tier-compatible) whose library MPN string is just
   "PICO" and does not distinguish the bare module from a Pico H with pre-soldered headers,
   which the lock forbids. My recommendation: **ask JLC to confirm the exact variant on
   C7203002, pin whichever they confirm as the bare castellated module, and require the
   silkscreen photo gate regardless.** Your call, or delegate it to me to resolve with JLC.

4. **J1 — re-spec to a library part, or keep hand-soldering it?** It is *Candidate*, not Locked,
   so re-specifying is legitimate. A library DIN 41651 box header (C492444 class, 10,481 pcs,
   $0.12) moves 680 joints into Wave 1. Cost of saying yes: you must also pick and buy the
   matching 2×10 ribbon socket and verify pin-1/keying against the existing rev-B board #1
   (~15 min). Cost of saying no: 680 hand joints and J1 stays the last hand-solder operation
   on every board. **My default is no — keep it hand — until the keying is verified either way.**

5. **Do you accept the FA-4 risk acceptance in writing?** Under G15 fleet quantity there is no
   first article, so JLC placing A1 commits 34 Picos before anyone confirms an unmodified
   micro-B cable seats with the J1 ribbon mated. The geometry is measured clear (25.4 mm from
   J1, 5.70 mm of empty board in front of the USB, D12 envelope drawn) and there are two proven
   fallbacks (shaved right-angle micro-B, module SWD pads). **I recommend accepting it** — the
   alternative is 34 hand-soldered castellated modules to protect a mitigation that expires at
   the Phase-0 reflash anyway. But it must be a recorded acceptance, not silence.

**Two things I will do regardless of your answers**, because they are defects found in passing:
fix the r8 README's retired 10M part-number literal (`export_fab_revD.py:1364–65` — README says
UNI-ROYAL C26108, the part-lock CSV in the same package says FOJAN C2933281), and add the
missing `_SUPERSEDED` marker to r8 the moment an r9 exists.

---

## 7. REFUTED / CARRIED-UNVERIFIED — brief

### Refuted (do not re-raise)
- **"Buy an upgraded PCBA tier."** No such tier. Economic and Standard only; already on Standard,
  which is mandatory at 34 boards. JLC assembles THT **manually**, not by wave — its own FAQ
  says parts flagged "wave soldering" in the library "will be assembled manually." The entire
  wave/pallet/thermal risk class is out of scope. (The "wave solder" strings in our own BOM are
  hardcoded in `export_fab_revD.py:201,342` — our text, not JLC's.)
- **"6 of 10 part types are absent from the JLC library."** The search method producing that
  result gives guaranteed false negatives — JLC's own search box returns "0 Found" for parts JLC
  sells (`1843622` → 0 found; `partdetail/C480549` → in stock). Verified-absent count is **zero**;
  4 types are confirmed present, 6 are unresolved in either direction.
- **"FA-8 is destroyed / the coding rib must be cut before soldering."** No repo document
  specifies cut-before-solder. FA-8 step 2 says the cut is made "on the board's own headers,"
  and step 3's refusal matrix and step 4's per-position silk check are inherently post-assembly.
  Zero process steps change.
- **"J3/J15 and J13/J16 need two consigned bins."** Headers ship uncoded; the pair is
  distinguished only by a post-solder cut. One PN, one bin, one BOM line at qty 2/board. The
  KiCad values are already distinct (`J_FAST_IN` vs `J_SLOW_IN_C`), so they default to separate
  BOM lines anyway — aliasing is opt-in.
- **"Phoenix headers are backordered; consignment serializes an 8–20 week lead time."**
  `cowork_cart_handoff.md` is 6.5 weeks stale, is a rev-B document, records the backorder at
  qty 5, and prints the mitigation ("re-ordering at Mouser") two lines below. Live: 1843703 shows
  2,139 at DigiKey; 1843680 shows 52 at DigiKey + 722 at Mouser. The real serialization leg
  against in-stock drop-shipped parts is ~1–1.5 weeks.
- **"FA-10's 1.4 mm drill is unproven, non-standard geometry."** 1.4 mm is exactly IPC-2222
  Level A for a 0.8 × 0.8 mm pin (1.131 + 0.25 = 1.381). Annular ring is 0.30 mm against JLC's
  0.15 mm floor. rev-C assembled at 1.2 mm and pins fit; 1.2 → 1.4 mm strictly relaxes insertion.
  What survives is only that FA-10's *sequence* can no longer run (B5) and that the FR-9
  justification prose is factually wrong.
- **"There is no second flash path / rev-D has no SWD."** What was dropped in rev-C is a
  *carrier-side* SWD breakout header. The Pico's own castellated SWCLK/GND/SWDIO holes survive
  reflow and audit L-03 already relies on them. `picotool` also reaches any assembled board via
  BOOTSEL/PICOBOOT — only the `-f` force-reboot path needs USB-CDC, which is compiled out.
- **"Staged 2-board pilot then 32."** Re-litigates an owner decision recorded 2026-07-26 at
  `readiness_checklist.md:448-453`: proceed at fleet quantity, reaffirmed after exposure was laid
  out in full. Also costs a second setup, a second consignment shipment and 3–5 weeks.
- **"A1 is a through-hole part."** It is `Module:RaspberryPi_Pico_SMD`, `(attr smd)`, 96 SMD pads,
  0 drills. 16 of the 17 are the THT question; A1 is not.
- **"JLC places 7 G5LE relays."** Six. K7 (M1 channel) and J12 (7th MKDS block) are both DNP.
  Current JLC manual-joint count is **190/board**, not 195 — this is the basis for the §4 costs.

### Carried unverified (labelled as such — do not treat as fact)
- **JLC's overseas consignment terms** are read from published help pages, not confirmed with
  support for this order. The mixing clause (B3) is the load-bearing unknown.
- **The BOM cites a thin LCSC line for J6–J11.** C5183929 carries ~239 pcs against a need of
  204–224; **C480516** is the same Phoenix MPN with ~3,214. Worth fixing regardless of this
  decision. Not independently re-verified today.
- **PS-4/PF-6: A1's footprint puts solder paste on the D1/D2/D3 lands**, so reflow may wick
  solder into the Pico's own DEBUG through-holes, degrading the SWD fallback to a wick-and-header
  operation. Pad census (43 paste-only / 43 Cu+Mask / 10 Cu+Mask+Paste) is from the board file;
  the wicking behaviour is inferred, not observed.
- **Do not buy JLC's programming service.** It requires "the programming interface definition
  reserved on the board" (there is none — the interface is the module's USB plus a button) and a
  HEX/BIN file, while `firmware/rp2040/release/` contains only signed `.uf2`. It would also break
  the hash-locked chain of custody and the image is not cutover-ready anyway. $7.86 + $7.86/h,
  and it solves nothing.
- **Freight, duty and bare-PCB prices in §4** are estimates from published rate cards, not live
  quotes. DDP means the sender pays Chinese import duty and VAT, which the $80–150 estimate
  excludes.
- **Attrition percentage** JLC requires on consigned/global-sourced parts is referenced in their
  docs but never stated numerically. Under-shipping stalls the whole order. Ask before sizing a
  parcel — it matters for the thin C3019636 (~7) and C5454708 (~30) lines.
- **Whether JLC hand-solders *consigned* THT parts at the same $0.0157/joint manual rate** is not
  documented. The §4 assembly delta assumes it does.
- **Whether JLC's DFM will demand an edge rail** given the 0.63 mm bottom-edge part (U43) — audit
  open question R-9, answerable only by the real upload preview and quote.
