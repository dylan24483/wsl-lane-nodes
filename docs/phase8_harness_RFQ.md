# RFQ — Custom Wire Harness Assembly (Lane Controller Field Harness)

**Westside Lanes · Olympia, WA** · Issued 2026-07-25 · Contact: Dylan DeYoung
**Assembly:** WSL-LANE-HARNESS-A · **Rev 3**
**Quantity:** 1 first article → 2 pilot → balance to **34 total** (32 lanes + 2 spares).
Option pricing requested at 48 and 64.

> **Rev 3 supersedes Rev 2 — quote against Rev 3 only.** Rev 2 was never issued.
> **Rev 3 change:** the enclosure-to-machine run was measured at **6 ft (1829 mm)**;
> Rev 2 lead lengths were sized before that and were too short once the in-enclosure
> route is added. L1 2500→**3200**, L2 3000→**3700**, L3 4000→**4700**, L1-200 2300→**3000**.
> L0 (800) and the J14 jumper (120) are unchanged.
>
> **Rev 2 changes vs Rev 1** (all carried forward into Rev 3):
> ① **All lead lengths increased** — Rev 1 budgeted the machine run but not the
> in-enclosure route (§3, §9). ② **J14 ferrules corrected to bare/uninsulated** — an
> insulated 0.75 mm² collar fouls the adjacent pole at 3.5 mm pitch (§5).
> ③ **Terminal torque now specified** (§5). ④ **Strip length corrected 8 mm → 7 mm** (§5).
> ⑤ **Coding profiles added** to Tier 1 (§4). ⑥ **1840489 is customer-free-issued** (§4).
> ⑦ Two questions we previously asked you are now answered by us (§Questions).

---

## 0. Read this first — what kind of customer we are

We are a **small business (a bowling center), not an OEM.** We do not require PPAP, a formal
FAI package, ISO quality-system flow-down, a supplier audit, or source inspection. **Your
standard Certificate of Conformance is acceptable.** Please do not price a documentation
program into this quote — if you see a line item that exists only to satisfy an aerospace or
automotive customer, leave it out and tell us you did.

What we *do* care about, in priority order: **correct and unambiguous labeling**, 100%
electrical test, consistency unit-to-unit, and on-time delivery.

## 1. What this assembly is

A field wiring harness for a replacement control board on bowling pinsetter machines. One
harness per lane. It connects a controller PCB (mounted in a wall enclosure) to sensors,
switches, and relay-coil circuits on the machine. The enclosure-to-machine run is **measured at 6 ft (1.83 m)**; leads are built longer than that to cover the in-enclosure route plus service slack.

**Electrically trivial** — nothing above 33 V, nothing above ~1 A. This is a **labeling- and
termination-intensive** assembly, not a high-voltage or high-current one. Cost lives in the
~49 leads × 2 ends of printed markers, not in the wire.

**Environment:** indoor, unconditioned equipment area behind bowling pinsetters. Ambient to
~35 °C. Fine wood/pin dust and light lane-oil mist. Vibration from adjacent machinery. No
flexing in service once installed — this is a static installation.

## 2. Scope boundary (important)

Quote the **controller-side harness only**, as specified here:

- **Controller end (one end of every lead): FULLY TERMINATED** — insulated ferrule, landed and
  torqued into its Phoenix plug, per §4/§5.
- **Machine end (the other end): PREPARED BUT UNTERMINATED** — cut to length, labeled, and
  left with **10 mm of insulation stripped, no ferrule** unless noted otherwise in the wire
  list. We terminate the machine end ourselves on site (the machine-side interface is a legacy
  1982 connector still being characterized).

Do **not** quote any machine-side connector. If you have an opinion on whether the stripped
ends should instead ship un-stripped, say so.

## 3. Wire list

**Attached as a separate CSV** (`WSL-LANE-HARNESS-A_wirelist_rev3.csv`), one row per lead, with
columns: `Wire ID · AWG · UL style · Color · End-A connector ref + position · End-A termination ·
End-B termination · **Length Class** · Finished length · Label text (identical both ends) ·
Twisted-pair partner · Notes`.

> **Rev 2 added a `Length Class` column; Rev 3 revises the class values.** Every lead belongs to one of four classes
> (**L0 / L1 / L2 / L3**). If we revise lengths again, only the class values change — the
> per-lead assignments stay put. Please structure your quote so a class-length change is a
> price delta, not a re-quote.

Summary for scoping:

| Group | Connector (controller end) | Leads | AWG | Length class | Length |
|---|---|---|---|---|---|
| Fast field inputs — cams | J3 — Phoenix MC 1,5/10-ST-3,5 | 5 (positions 1–5; all capped) | 22 | **L3** | 4.7 m |
| Fast field inputs — DIELL | J3 (positions 7–10; **6 empty**) | 4 | 22 | **L2** | 3.7 m |
| Slow inputs A | J4 — MC 1,5/14-ST-3,5 | 13 (positions 1–11, 13, 14; **12 empty**) | 22 | **L1** | 3.2 m |
| Slow inputs B | J5 — MC 1,5/12-ST-3,5 | 4 (positions 1, 2, 3, 12; **4–11 empty**) | 22 | **L1** | 3.2 m (FOUL lead 3.0 m) |
| Lamp outputs | J13 — MC 1,5/ 6-ST-3,5 | 6 | 22 | **L3** | 4.7 m (see §9) |
| Safety loop | J14 — MC 1,5/ 4-ST-3,5 | 2 + 1 internal jumper | 18 | **L1** | 3.2 m (jumper 120 mm) |
| Power in | none — ferruled loose leads | 3 | 18 | **L0** | 0.8 m |
| Machine outputs | none — ferruled loose leads | 12 | 18 | **L1** | 3.2 m |
| **Total** | | **~49 leads** | | | |

**Length class definitions:** **L0** = stays inside the enclosure · **L1** = enclosure to the
machine connector · **L2** = enclosure to the photoelectric sensors · **L3** = enclosure to the
overhead lamp unit / far mechanism.

## 4. BOM

### Tier 1 — NO SUBSTITUTIONS (form/fit/function critical)

| Item | Manufacturer | Part number | Qty/assy | Source |
|---|---|---|---|---|
| Plug, 10-pos, 3.5 mm | Phoenix Contact | **1840447** (MC 1,5/10-ST-3,5) | 1 | you |
| Plug, 14-pos, 3.5 mm | Phoenix Contact | **1840489** (MC 1,5/14-ST-3,5) | 1 | ⚠️ **CUSTOMER FREE-ISSUE** |
| Plug, 12-pos, 3.5 mm | Phoenix Contact | **1840463** (MC 1,5/12-ST-3,5) | 1 | you |
| Plug, 6-pos, 3.5 mm | Phoenix Contact | **1840405** (MC 1,5/ 6-ST-3,5) | 1 | you |
| Plug, 4-pos, 3.5 mm | Phoenix Contact | **1840382** (MC 1,5/ 4-ST-3,5) | 1 | you |
| **Coding profile** | Phoenix Contact | **1734634** (CP-MSTB) | **2** | you |

> **⚠️ 1840489 is FREE-ISSUED — do not source it.** It is discontinued and the authorized
> distribution channel is dry. We are making a lifetime buy and will ship it to you with the PO.
> Tell us your required buffer quantity. **Pre-approved fallback** if our stock runs short:
> **Phoenix FMC 1,5/14-ST-3,5** (push-in rather than screw; mates the identical MCV 1,5-G header,
> no other change). Use it only if we authorize in writing.

> **Coding profiles (new in Rev 2) — install 2 per assembly:** **J3 at pole 1** and **J13 at
> pole 1**. Profiles fit the **PLUG**, never a header. This is not cosmetic: the board has two
> pairs of *identical* connectors (J3/J15 both 10-pos, J13/J16 both 6-pos). An uncoded plug
> mates either one. A J13 lamp plug pushed into J16 lands LEDs across 5 V and wedges the I²C bus.
> Also apply the **WHITE identification band** per the marking scheme in the attached harness BOM.
> **Prove the coding operation on a sacrificial plug before coding production parts** — profile
> installation is not reversible.

### Tier 2 — functional equivalents acceptable (tell us what you'd use)

Hook-up wire (UL1007 or UL1015 class, 300 V min for 22 AWG, 600 V for 18 AWG), insulated
ferrules, printed heat-shrink marker stock, adhesive-lined heat-shrink end caps, lacing/ties,
bags.

**Wire colors are functionally meaningful — do not substitute colors.** See §6.

## 5. Ferrule, strip, and torque specification

**Strip length is 7 mm on every landed end.** *(Rev 1 said an 8 mm ferrule barrel — that was
wrong; 7 mm is the Phoenix MC 1,5 figure.)*

| Leads | Lands in | Pitch | Ferrule |
|---|---|---|---|
| 22 AWG → J3, J4, J5, J13 | MC 1,5-ST-3,5 plugs | 3.5 mm | **0.34 mm² INSULATED**, 7 mm |
| 18 AWG → **J14 only** (JMP1, W33, W34) | MC 1,5/4-ST-3,5 | **3.5 mm** | ⚠️ **BARE STRANDED, or 0.75–1.0 mm² UNINSULATED**, 7 mm |
| 18 AWG → loose leads for J2 / J6–J11 | MKDS 1,5 blocks | 5.08 mm | **0.75 mm² INSULATED**, 7 mm |

> **⚠️ Why J14 is different — this is the one place Rev 1 was wrong.** The Phoenix MC 1,5 series
> is rated 0.14–1.5 mm² **bare or with an uninsulated ferrule, but only 0.5 mm² maximum with an
> insulated ferrule.** A 0.75 mm² insulated collar is roughly 4.0 mm across, against a 3.5 mm
> pole pitch — and all four J14 poles are populated, so adjacent collars physically interfere.
> **Do not fit insulated ferrules on any J14 lead.** The 0.75 mm² insulated ferrules on the
> loose J2/J6–J11 leads are correct and must stay: those blocks are 5.08 mm pitch, rated to
> 1.5 mm². Please do not "standardize" the three J14 leads to match them.

**Terminal screw torque: 0.22–0.25 N·m** (M2 screw). This is roughly **36 landed screws per
assembly**. Do not use ~0.5 N·m — it is more than 2× the rating and will strip the screw or
crack the plug body. Use a calibrated driver.

- Phoenix AI-series or Weidmüller H-series preferred; equivalents acceptable.
- Crimp to the ferrule manufacturer's die spec; **every ferruled joint must pass a pull test.**

## 6. Wire colors (functional, not cosmetic)

| Color | Meaning |
|---|---|
| **White** | landed sense signal |
| **Orange** | **DO-NOT-LAND lead** — capped at the machine end, deliberately unconnected until a future commissioning step. Orange must not appear on any other lead. |
| **Green** | field ground / chassis bond |
| **Black** | ground / return |
| **Blue, Yellow (22 AWG)** | photoelectric sensor signals L and R |
| **Red (18 AWG)** | relay normally-open output, and +5 V power |
| **Black (18 AWG)** | relay common, and power return |
| **Yellow (18 AWG)** | safety-loop circuit |

## 7. Labeling — the cost driver, specified precisely

- **Printed heat-shrink sleeve markers** (Brady PermaSleeve, Phoenix THERMOMARK, or equivalent),
  white sleeve, black print, permanent. Not wrap-around adhesive labels; not hand-marked.
- **BOTH ends of every lead**, ~49 leads = **~98 markers per assembly.**
- Exact text is in the wire-list CSV, column `Label text`. Text is identical at both ends of a
  given lead. **Labels are deliberately short — longest string is 22 characters** (`STOP/CIS - DO NOT LAND`).
  Signal names only; no machine-specific wiring references appear on the wire, because those
  vary per lane and live on a per-lane card instead. If any string is still too long for your
  marker stock, tell us your maximum — do not truncate on your own initiative.
- Position: within 40 mm of each termination, oriented so text reads with the lead running
  left-to-right.
- Additionally: each of the five Phoenix plug bodies carries its own printed label (text in the
  CSV, `Plug body label` sheet).

## 8. Special construction features

1. **Twisted pairs (2 per assembly).** Blue+Black and Yellow+Black on J3, ~1 twist per 30–40 mm,
   starting 50 mm from the plug and stopping **100 mm short of the machine ends** so those ends
   remain independently routable. Pair partners are named in the wire list.
2. **Capped leads (11 per assembly).** All orange leads plus the two 18 AWG yellow safety leads
   get their **machine end sealed with adhesive-lined heat shrink** — no ferrule, no exposed
   conductor. They still carry their printed label. These are deliberately dead-ended.
3. **Empty connector positions.** J3-6, J4-12, and J5 positions 4–11 are **intentionally empty.**
   Do not populate them. The wire list is authoritative; if a position isn't listed, it stays
   empty.
4. **J14 internal jumper.** A ~120 mm 18 AWG yellow U-jumper is fitted **inside the J14 plug
   between positions 1 and 2**, ferruled both ends, with a printed flag label on the loop
   (text in the CSV). This is a deliberate engineered link, not an error. Positions 3 and 4
   carry the two capped leads. **A finished J14 must read SHORT across 1–2 and OPEN across 3–4.**
5. **Loose ferruled leads.** The 3 power leads and 12 machine-output leads have **no connector at
   the controller end** — they ship ferruled and labeled, loose, to be landed in screw terminals
   at install. Bundle and tie them per group.

## 9. Lengths — build long, we trim on site

**Rev 3 lengths are measured-plus-margin.** The enclosure-to-machine run is **6 ft (1829 mm)**, measured. Each L1 lead must also cross the in-enclosure route (~750–950 mm on the far board) plus ~300 mm service slack and drip loop, which is how 3200 mm is derived. Per-lane siting is not yet
surveyed at every lane pair, so all four classes are sized so that **no lead can come up short**.
We will trim on site. Build to the wire list; do not optimize lengths down.

> **⚠️ Marker placement requirement (new in Rev 2, and it affects your process).** Because we
> trim the machine end in the field, a marker printed at the very end of the lead gets cut off.
> On every **L1 / L2 / L3** lead, either:
> **(a)** position the machine-end marker **150 mm back from the cut end**, or
> **(b)** ship the machine-end markers loose, un-shrunk, in a labeled bag per assembly.
> **State which you will do.** The controller-end marker is unaffected.
> (Correct labeling is priority #1 in §0 — a trimmed-off marker defeats the whole spec.)

Please quote: **(a)** at the Rev 3 lengths as written, and **(b)** the per-assembly cost delta
per **±0.5 m on class L1** (30 leads), so we can price the classes down once the site survey is
complete without re-quoting.

## 10. Test and workmanship

- **Workmanship: IPC/WHMA-A-620, Rev E, Class 2.** Class 2 is correct for this application —
  please do not build or price to Class 3.
- **100% electrical test on every assembly:** point-to-point continuity on all nets, **plus
  isolation/shorts testing between all nets.** Isolation matters more than usual here — an
  adjacent-position short inside a Phoenix plug is our most likely failure mode.
- **Explicit exception:** the J14 1–2 jumper is an intentional short and must not be flagged.
- **No hipot required** (max circuit voltage 33 V).
- Ship a test record or pass/fail log per serialized assembly.

## 11. Identification and traceability

- Each assembly carries a printed label with **assembly PN + revision + serial number** on the
  main bundle near the J4 plug.
- Serial-level traceability requested (simple sequential numbering is fine — we need to tie a
  harness to a lane, not to a wire lot).

## 12. Quantity, ramp, and spares

| Stage | Qty | Note |
|---|---|---|
| First article | **1** | Ship for our approval before proceeding. We will respond within 5 business days. |
| Pilot | **2** | After FA approval |
| Balance | **31** | 32 lanes + 2 spares total |
| **Total program** | **34** | Please also quote **48** and **64** so we can see the price break |

Additionally quote as separate line items: **10% spare loose leads** (assorted, pre-labeled) and
**3 spare sets of the five Phoenix plugs**, unpopulated.

## 13. Packaging and kitting

**Individually bagged and labeled per assembly**, with the serial number visible on the outside
of the bag. This is worth paying for on a 32-lane install — it is what prevents a
wrong-harness-on-wrong-lane afternoon. Coil to ~250 mm diameter, tie in at least 3 places, one
carton per 6–8 assemblies with a packing list.

## 14. Commercial

- **Target:** first article within 3 weeks of PO; balance within 8 weeks of FA approval.
- Ship to Olympia, WA 98502. Freight prepaid and added is fine.
- Quote NRE separately from unit price, and tell us what the NRE buys (fixture, program, setup)
  and whether it recurs on a reorder.
- State your acceptable over/under shipment tolerance.
- **Drawing revision control stays with us.** We will issue revised wire lists as
  `Rev 2`, `Rev 3`, etc.; please quote against the revision stated on the PO.

## 15. Attachments provided with this RFQ

1. `WSL-LANE-HARNESS-A_wirelist_rev3.csv` — the 49-row from-to wire list with label text and
   length classes. **This is the controlling document. Where it and this RFQ disagree, the CSV wins.**
2. `phase8_revD_harness_bom.csv` — plug + coding-profile part identities and the band-marking scheme
3. Phoenix Contact datasheets for the five Tier-1 plugs and the CP-MSTB coding profile

> **Not attached, and deliberately so:** Rev 1 referenced a dimensioned 2D layout PDF and a
> golden-sample photo set. **Neither exists** — the prototype unit has not been built. Both
> references are withdrawn rather than left dangling. If a flat layout drawing would materially
> reduce your quote, say so and we will produce one.

> **Plug-body labels:** the J14 plug body carries `J14 SAFE LOOP - SHORT 1-2` (text is in the
> wire list). The other four plug bodies need identification text we have **not** yet specified —
> quote plug-body labeling as a **separate line item** and we will supply the text on PO.

---

## Questions we specifically want answered in your quote

1. Your maximum legible characters per heat-shrink marker (§7).
2. The §9 length delta (per ±0.5 m on class L1), and **which marker-placement option you will
   use** — set back 150 mm, or shipped loose and un-shrunk.
3. Your required **buffer quantity** for the free-issued 1840489 (§4).
4. Confirmation that you can install **CP-MSTB coding profiles** (§4), and whether you would
   rather we ship the plugs pre-coded.
5. Anything in this package that is over-specified and costing us money for no benefit. We would
   rather hear that than pay for it.

> **Two Rev-1 questions are now answered by us — no response needed:**
> **Ferrules (old Q1):** resolved in §5. J14 takes bare or uninsulated; everything else is as
> tabulated. Do not substitute.
> **Machine-end preparation (old Q4):** build them **stripped 10 mm as specified.** The machine
> end is crimped into a contact on our side, so stripped is correct.
