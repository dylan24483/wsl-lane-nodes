# Phase 8 — Production Lane-Pair Enclosure Spec (rev-C board, no-shrink assumption)

**Written 2026-07-14.** Closes PCB-spec open question #7 (board envelope / DIN enclosure / service
clearances, `phase8b_pcb_revB_spec.md:368`) and re-specs task #12 for the rev-C board size.
Supersedes the Phase-8a enclosure specs (`phase_8a_infrastructure_plan.md` §4 Hammond 1597BSGY and
the two purchased Ogrmar 8×6×4 boxes — **neither fits the 250×225 mm rev-C board; do not reuse
for controllers**).

**Scope:** ONE enclosure per lane PAIR housing 1× Pi 4 + 2× rev-C controller boards
(250.0 × 225.0 mm each, assumed NOT to shrink) + PoE-fed 5 V power + fused distribution.
The lane-21 **pilot** box is a separate, already-specced single-board article (Saginaw
SCE-24EL2008LP + HDR-60-5 on the lane-21 wall outlet); this doc is the **fleet** article.

---

## 1. Panel layout — LAYOUT D: stacked, mirrored, shared middle DIN band

Both boards mount portrait, one above the other, the **upper board rotated 180°** so that BOTH
boards' top edges (J1 ribbon / J2 power / J14 safety) face a shared **150 mm middle band**
carrying the DIN rail. Chosen over side-by-side/rotated alternatives because:

- **Both J1 ribbons land ~80–150 mm from the Pi** — board 2's bit-banged bus-3 I²C gets the
  shortest run of any evaluated layout (~100 mm). (Bench lesson 2026-07-13: marginal I²C from a
  disturbed 300 mm harness cost an hour — the ribbon is the one cable that must stay short.)
- Both J2 power runs land directly on the middle fuse blocks (no cross-panel 5 V routing).
- The machine-output (MKDS) edges end up on **opposite outer sides** — each lane's Bundle-3
  harness exits its own side, cleanly separated from Bundle-1 field-sense drops.
- The outer top/bottom edges are the low-clearance J13 edges (15–20 mm).

```
        ┌──────────── 310 mm ────────────┐
        │  20  · J13 edge (board A)      │
        │ ┌────────────────────────────┐ │
   B3-A │ │   BOARD A (rotated 180°)   │ │ B1-A     board zone
  glands│ │   outputs → LEFT outer     │ │ plugs    225 mm
        │ └────────────────────────────┘ │
        │  ~150 mm MIDDLE DIN BAND       │  J1+J2 edges both face here:
        │  [fuses][DDR-60G-5][Pi DRP2]   │  ribbons ≤150 mm, power ≤ 100 mm
        │  [PoE splitter shelf beside]   │
        │ ┌────────────────────────────┐ │
   B1-B │ │   BOARD B (as designed)    │ │ B3-B
   plugs│ │   outputs → RIGHT outer    │ │ glands   225 mm
        │ └────────────────────────────┘ │
        │  20  · J13 edge (board B)      │
        └────────── panel 310 × 640 ─────┘
```

**Clearances (derived from real connector geometry, not blanket 60 mm):** rigid parts have ZERO
edge overhang — the 250×225 outline is a true keep-in. Wire-only crossings: MKDS output edges
30 mm (12× 18 AWG lateral entry + bend + duct wall), MCV field-plug edges 20 mm min / 30 mm with
a vertical duct (plugs pull out of the panel plane; clearance is finger room), J2/J1/J14 edge
25 mm (wire band into the middle rail), J13 edge 15–20 mm. Facing MCV/vertical-exit edges may
share ~40 mm; facing MKDS wire edges must not share.

**Board mounting:** 4× M3 at 242 × 217 mm (MK1–MK4), 12 mm metal standoffs at the holes only —
**nothing else conductive may touch the board underside** (isolation gutters are copper-only).
Add one center support pad (adhesive standoff) under the relay band — the M3 pattern leaves the
J6–J11 screw-torque zone 8 mm from an unsupported edge mid-span.

**Tie-downs:** MC 1,5 ST plugs have no locking flange and every plug axis is horizontal on a wall
panel — anchor each harness bundle within ~50 mm of J3/J4/J5/J13/J14 on both boards.

**Depth:** DIN row governs — ~62 mm off-panel (DDR + rail); board stack ~50 mm. Any standard
≥8 in (203 mm) deep box is comfortable.

## 2. Enclosure

| Role | Part | Notes |
|---|---|---|
| **Primary** | **Saginaw SCE-30EL2408LP** (30×24×8 in, NEMA 12, hinged) + subpanel **SCE-30P24** (686×533 mm usable) | Hung portrait: 640-tall layout fits the 686 mm panel with 220 mm of spare width for ducting. $467 AutomationDirect (15 stock 2026-07-14) / $397 Solutions Direct; subpanel ~$75. |
| Upsize alt | SCE-36EL3008LP (36×30×8) + SCE-36P30 | Fits side-by-side layouts; +$180–260/box. Only if a wall demands wide-not-tall (then use layout B2, counter-rotated, ribbons <200 mm). |
| Alternates | nVent Hoffman A302408LP · Wiegmann N412302408C | Spec-equivalent; verify pricing (Hoffman usually costs more; Wiegmann quote before assuming savings). |

Steel + NEMA 12 gasketed door; **sealed, no vents** (pair worst-case ~20 W → ΔT ≈ 8 °C in this
volume; at 35 °C summer ambient, internal ≤ ~48 °C — every part is in rating; heatsink the Pi).
Optional Gore-type M12 breather plug against condensation. **Wire-map card taped inside the
door** (mandatory, per harness build sheet / Section F).

**Grounding rule (steel box):** the enclosure body is earthed; the boards' logic GND must NOT
bond to it — metal standoffs at MK holes are fine, nothing else. Bundle-1 shield drains (if
multicore) terminate to LOGIC GND at the enclosure end only. FIELD_GND bonds to *machine
chassis* via the harness ring lugs, never inside the box.

## 3. Power — PoE in, one fused 5 V rail

Every enclosure needs a Cat6 run for the Pi regardless → the same cable powers the box.
**No AC, no conduit run down the house.** (The lane-21 pilot box keeps its HDR-60-5 on the
existing outlet; downstream distribution is identical, so the pilot validates this section.)

Chain: **802.3bt drop → PoE Texas GBT-12V60W splitter** (12 V/4.5 A out, gigabit passthrough,
$90 — panel-mounted beside the rail) **→ Mean Well DDR-60G-5** (9–36 V in, 5 V/10.8 A, DIN,
$33 — the $6.50 upgrade over DDR-30G-5 buys 2.7× headroom) **→ four fused branches:**

| Fuse block (5×20 mm) | Feeds | Fuse |
|---|---|---|
| F1 | 12 V splitter → DDR input | 3 A |
| F2 | Board A J2 | **2 A fast** (H-23: the board has no input protection; D17 is a 1 A part — this fuse IS the audit fix) |
| F3 | Board B J2 | **2 A fast** |
| F4 | Pi 4 via USB-C pigtail | **4 A time-delay** (rides out boot inrush; keeps the Pi's own input protection in-circuit — never feed raw GPIO or J1 pins 1/11) |

Load math: two boards worst-case ~2 A + Pi ≤3 A ≈ 5 A of 10.8 A. Splitter draw ~23 W of 60 W.

**Head-end (16 drops), decide at fleet buy:**
- **Recommended:** per-drop TP-Link TL-POE170S 802.3bt injectors, ~$50/port — no shared budget,
  no single point of failure, spare-friendly (buy 18).
- Value: 2× Netgear GS516UP (~$740 for 16 ports, only 8/unit are Ultra60 — use only those).
- Single-box: IPCamPower 16-port full-bt (~$950).

DIN bits per box: Konnect-It KN-F10 fuse blocks ($3.12 ea in 50-pk), KN-G10 ground blocks ×2,
DN-R35S1-2 rail, end brackets, 1×2 in slotted duct, DINrPlate DRP2 for the Pi.

## 4. Glands (~9, all on the BOTTOM face, drip loops per Section F)

Per lane: Bundle 1 (field-sense) and Bundle 3 (outputs) in **separate glands ≥50 mm apart**
(×2 lanes = 4), DIELL taps (B1 domain, ×2), J13 mask runs (×2), Cat6 (×1). M20 IP68 nylon
(uxcell 20-pk ~$0.60 ea or Bimed BMSPX). Bundle-1 vs Bundle-3 separation carries from the
gland plate to the wall penetrations.

## 5. Cost

- **Per pair, box side:** $633–703 (enclosure $397–467 · subpanel $75 · splitter $90 · DDR $33 ·
  fuses/blocks/rail/duct/glands ~$40) **+ head-end share $23–50/port ⇒ ~$680–760.**
- **Fleet ×16:** **~$10.9k–12.1k** (excl. boards/Pis/harnesses). Add ~5% consumables + 1–2 spare
  splitters/converters.

## 6. Open items

1. PoE final commit after lane-21 pilot soak publishes real watts (expected ~16–20 W/pair —
   802.3bt has 2.6× margin; even PoE+ would carry it, but bt is the spec).
2. J13 mask-run lengths: site-measure per lane (est. 2–3 m) before cutting those leads.
3. Wiegmann current pricing if the fleet budget wants the ~$50/box savings.
4. If the fleet respin shrinks the board (24 VAC creepage relax, layout-mfg §13.3), re-run
   layout D math — a smaller board may allow the 24×20 box (−$80/pair) or side-by-side.
5. Head-end pick (injectors vs switch) at fleet purchase time.
