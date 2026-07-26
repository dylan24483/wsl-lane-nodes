# Harness Wire List Rev 2 — change notes, length classes, and the RFQ amendments

**File:** `docs/WSL-LANE-HARNESS-A_wirelist_rev3.csv` · supersedes `..._rev2.csv` (never issued) and `..._rev1.csv` (commit `0537e26`)

> **REV 3 (2026-07-26) — LENGTHS NOW MEASURED.** The enclosure-to-machine run is
> **6 ft (1829 mm)**. Rev 2 sized L1 at 2500 mm before that was known, which is short
> once the ~750–950 mm in-enclosure route is added. Rev 3: **L1 3200 · L2 3700 · L3 4700 ·
> L1-200 3000**; L0 (800) and the J14 jumper (120) unchanged. **§2 below is CLOSED** —
> the measurement it asked for has been taken. ~168 m of wire per assembly.
**Reason:** pre-order audit 2026-07-25 findings **S4** (lead lengths), **S5** (J14 ferrule/torque/strip),
**M-19** (cam lead destination), **M-20** (J14 label), **M-15** (missing attachments).
**Status:** ready to issue **once the length classes below are confirmed** (§2).

---

## 1. What changed vs Rev 1

| # | Change | Rows | Why |
|---|---|---|---|
| 1 | **New `Length Class` column** (L0/L1/L2/L3) | all | Rev 1 hard-coded 49 lengths. Rev 2 puts them in 4 classes so a measurement changes **4 numbers, not 49**. |
| 2 | **L1 1200 → 2500 mm** (provisional) | 30 leads | Rev 1's 1200 mm was derived from the *machine-to-enclosure* run only and budgets **zero** for the in-enclosure route. On the 780 mm fleet panel, Board A alone burns ~0.75–0.95 m getting to the bottom-face gland. |
| 3 | **L2 1500 → 3000 mm** (DIELL pair) | W06–W09 | Same, plus the photoelectrics sit further out than C2A. |
| 4 | **L3 2500 → 4000 mm** (lamp + cams) | W01–W05, W27–W32 | Same, plus overhead lamp run. |
| 5 | **L0 500 → 800 mm** (J2 power) | W35–W37 | In-box only, but the panel grew 670 → ~780 mm. 500 mm no longer crosses it. |
| 6 | **Cam leads W01–W05 promoted to L3** | 5 | **M-19.** SA/SB/SC/TA1/TA2 have no confirmed C2A cavity; the approved fallback is to tap them **at the switches out on the mechanism**, much further than C2A. They are capped leads — trimming and re-capping on site is free, running short is not. |
| 7 | **J14 ferrules: insulated → BARE or UNINSULATED** | JMP1, W33, W34 | **S5.** J14 is `MCV 1,5/4-G-3,5` — **3.5 mm pitch, all 4 poles populated.** A 0.75 mm² *insulated* collar is ~4.0 mm OD and fouls the adjacent pole. Corrected Phoenix limit is **0.5 mm² max with an insulated ferrule**. |
| 8 | **Strip length stated as 7 mm on every landed end** | all landed | **S5.** Rev 1 gave an 8 mm ferrule barrel and no strip length. The corrected MC 1,5 figure (2026-07-21, H7) is **7 mm**. |
| 9 | **J14 label rewritten** | W33, W34 | **M-20.** Was `STOP/CIS - DO NOT LAND` — names a device physically proven **absent** on lanes 21/22, and drops the prohibition the whole Candidate-C safety posture rests on. Now `STOP/CTRL-PWR - OPEN - DO NOT LAND OR JUMPER`. This is permanent printed heat-shrink; it is the only instruction that reaches a 2030 technician. |
| 10 | **JMP1 label text supplied inline** | JMP1 | **M-15.** Rev 1 said *"see Plug Body Labels sheet"* — that sheet does not exist. Text is now `J14 SAFE LOOP - SHORT 1-2`. |
| 11 | **Explicit "insulated ferrule is CORRECT here" notes** | W35–W49 | J2 and J6–J11 are MKDS at **5.08 mm** pitch, rated to 1.5 mm². Rev 2 must not cause a vendor to "helpfully" strip insulation off leads that are fine. |

**Unchanged and deliberately so:** 49 leads, all colours, all connector/position assignments,
0.34 mm² insulated ferrules on J3/J4/J5/J13 (~3.0 mm collar on 3.5 mm pitch — fine), the 11
capped DO-NOT-LAND leads, the machine-end-unterminated scope boundary, and the 1 + 2 + 31
staged ramp. **The audit verified the pin-to-signal map position-by-position against the rev-D
netlist — every landed lead maps to the right board pin. Do not touch it.**

---

## 2. THE ONE THING STILL OPEN — confirm the length classes

The 2500 / 3000 / 4000 / 800 numbers above are **provisional trim-on-site values**, sized so
that no lead can be short. They are safe but wasteful: ~30 % more wire, and every field lead
needs trimming at install × 34 assemblies.

**Ten minutes at one representative pair replaces them with real numbers.**

### Measurement card — take to one fleet pair location (NOT lanes 21/22)

Lanes 21/22 use the single-lane pilot box and will give the wrong answer.

| # | Measure | Record |
|---|---|---|
| 1 | Planned enclosure position → mark it on the wall | ______ |
| 2 | **In-box run:** from where Board A's J3 plug will sit, through the duct, to the bottom-face gland wall. Follow the route, don't measure straight-line. | ______ mm |
| 3 | Same for Board **B** (the far board — it is the longer one) | ______ mm |
| 4 | Gland wall → machine **A** C1/C2A | ______ mm |
| 5 | Gland wall → machine **B** C1/C2A | ______ mm |
| 6 | Gland wall → the **DIELL photoelectrics** on the far machine | ______ mm |
| 7 | Gland wall → the **overhead lamp/masking unit** feed point | ______ mm |
| 8 | Gland wall → the furthest **cam switch** on the mechanism (for M-19) | ______ mm |

Then: **L1 = (3) + (5) + 300 mm service slack + drip loop.** Same construction for L2 (item 6),
L3 (max of 7 and 8), L0 = (3) + 150 mm. Always size on the **far** board and the **far** machine —
one part number serves both lanes.

### If you cannot measure before issuing

Issue Rev 2 as written and add this to RFQ §9: *"Machine-end printed markers on all L1/L2/L3
leads to be positioned **150 mm back from the machine end**, or shipped un-shrunk in a labelled
bag, so that field trimming does not destroy the marker."* Without that clause, trimming a lead
removes its identification — which defeats the whole labelling spec that §0 calls priority #1.

---

## 3. RFQ amendments that must ship with Rev 2

`docs/phase8_harness_RFQ.md` is **not** yet amended. These four edits are required — the wire
list alone does not carry them.

### §5 — replace the ferrule section

> - 22 AWG leads → **0.34 mm²** insulated ferrule, **7 mm strip**.
> - 18 AWG leads into **J2 / J6–J11** (MKDS, 5.08 mm pitch) → **0.75 mm²** insulated ferrule, 7 mm strip.
> - 18 AWG leads into **J14** (MCV 1,5/4-G-3,5, **3.5 mm pitch**) → **bare stranded, or a 0.75–1.0 mm²
>   UNINSULATED ferrule.** An insulated collar at this pitch fouls the adjacent pole.
> - Phoenix MC 1,5 rating: 0.14–1.5 mm² bare or uninsulated; **0.5 mm² MAX with an insulated ferrule.**
> - **Terminal screw torque: 0.22–0.25 N·m (M2). Do NOT use ~0.5 N·m — it is over 2× rated and
>   will strip the screw or crack the plug body.**
> - Crimp to the ferrule manufacturer's die spec; every ferruled joint must pass a pull test.

**Delete the §5 DFM question entirely** — it asks the vendor to rule on exactly the thing that
is now specified, and its premise sentence (*"we have hand-built one unit successfully using
insulated ferrules at both sizes"*) asserts the opposite of the correction as field-proven.
The lane-21 harness build is still open (`docs/HANDOFF.md` next-action 5), so that unit does
not exist.

### §4 Tier 1 — 1840489 (J4 plug)

Add: *"**FREE-ISSUED BY CUSTOMER — do not source.** Phoenix 1840489 is discontinued with the
authorized channel dry; we are making a lifetime buy and will ship it to you. Pre-approved
fallback if our stock is short: **Phoenix FMC 1,5/14-ST-3,5** (push-in, mates the same
MCV 1,5-G header, zero PCB impact)."*

### §4 Tier 1 — coding profiles (M-05)

Add **CP-MSTB 1734634**, 2 profiles/assembly: J3 @ pole 1, J13 @ pole 1, with the WHITE band
marking per `docs/phase8_revD_harness_bom.csv`. Without this, 34 harnesses ship as **universal
keys** — an uncoded J13 lamp plug will mate J16 and land resistorless LEDs across 5 V while
wedging I²C. *(Alternative: do the coding in-house and buy ~40 stars — DigiKey PN 348744, MOQ 1,
$0.10 ea.)*

### §15 attachments (M-15)

- `WSL-LANE-HARNESS-A_layout_rev1.pdf` — **does not exist.** Produce or delete the reference.
- *"Plug Body Labels sheet"* — **does not exist.** JMP1's text is now inline; the other 4 plug-body
  labels (204 fleet-wide) still have **no specified text**. Specify them or delete §7's reference.
- **Add `docs/phase8_revD_harness_bom.csv`** — it is the only machine-readable artifact carrying
  the corrected ferrule/torque/strip figures and the coding scheme, and it is currently not attached.

### §Open questions — answer #4 yourself before issuing (M-18)

Rev 1 asks the shop whether machine ends should be stripped. Under the approved **interposer-pigtail**
fleet architecture the machine end is **crimped into a contact**, so stripped 10 mm is correct —
say so rather than asking. *(It would be wrong only for Scotchlok-class IDC piercing taps, which
the fleet does not use; taps were a pilot-only parallel-listening method.)*

---

## 4. Do not disturb

The RFQ's **1 + 2 + 31 staged ramp** (§12) is the correctly-structured part of this order and it
matches the board wave plan. Release **3 harnesses** with wave 1. Hold the 31-unit balance until
the first article is accepted.
