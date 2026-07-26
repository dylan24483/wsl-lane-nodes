# Phase 8 — Production Lane-Pair Enclosure Spec (**250×240 rev-D**)

**Written 2026-07-14 for the 250×225 rev-C board; REVISED 2026-07-21 for the rev-D board
(Codex NO-GO audit finding H8).** The controlling board envelope is now **250.0 × 240.0 mm
(rev-D)** — every 225-mm-derived number in the original text has been updated in place and
the rev-D panel drawing added as §1.1. Closes PCB-spec open question #7 (board envelope /
DIN enclosure / service clearances, `phase8b_pcb_revB_spec.md:368`) and re-specs task #12.
Supersedes the Phase-8a enclosure specs (`phase_8a_infrastructure_plan.md` §4 Hammond
1597BSGY and the two purchased Ogrmar 8×6×4 boxes — **neither fits even the 225 mm rev-C
board; do not reuse for controllers**).

**Scope:** ONE enclosure per lane PAIR housing 1× Pi 4 + 2× **rev-D** controller boards
(**250.0 × 240.0 mm** each) + PoE-fed 5 V power + fused distribution.
The lane-21 **pilot** box is a separate, already-specced single-board article (Saginaw
SCE-24EL2008LP + HDR-60-5 on the lane-21 wall outlet — its ~578×428 mm panel class takes a
single 250×240 board trivially, OG-1 re-check 2026-07-20); this doc is the **fleet** article.

> **✅ r6 (2026-07-25) MOVED NO DIMENSION — verified, not assumed.** The r6 input-protection
> spin added **120 parts** (40 `Dser` + 40 `Dclamp` + 40 DNP `Cflt`) inside the existing
> outline, in a free corridor at x ≈ 59.7–72.9 mm. Re-measured on the routed board after the
> change: **`BOARD_W` = 250.0 mm, `BOARD_H` = 240.0 mm** (`place_components_revD.py:104,113`;
> exported board stats read `Width 250.0000 mm / Height 240.0000 mm`), `INPUT_PITCH` still
> exactly **5.700 mm** across all 40 opto rows, and the 0.0200 mm inter-courtyard slack in the
> opto column — the dimension that forced 225 → 240 in the first place — was never touched.
> **Every number in this document therefore stands unchanged.** The MK pattern, the panel
> stack, the row-39 bottom-edge keep-clear and the ≥ 310 × 670 mm panel requirement are all
> unaffected.
>
> **Rev-D deltas at a glance (2026-07-21):** board zone 225 → **240 mm** (×2); panel stack
> 640 → **670 mm**; MK mounting pattern 242×217 → **242×232 mm** (bottom holes moved to
> y=236); **row-39 bottom-edge copper constraint** (§1.2) is BINDING on the backplate/lip
> design; sourcing-brief hard requirement #1 reissued at **≥ 310 × 670 mm** panel.

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
  glands│ │   outputs → LEFT outer     │ │ plugs    240 mm (rev-D)
        │ └────────────────────────────┘ │
        │  ~150 mm MIDDLE DIN BAND       │  J1+J2 edges both face here:
        │  [fuses][DDR-60G-5][Pi DRP2]   │  ribbons ≤150 mm, power ≤ 100 mm
        │  [PoE splitter shelf beside]   │
        │ ┌────────────────────────────┐ │
   B1-B │ │   BOARD B (as designed)    │ │ B3-B
   plugs│ │   outputs → RIGHT outer    │ │ glands   240 mm (rev-D)
        │ └────────────────────────────┘ │
        │  20  · J13 edge (board B)      │
        └────────── panel 310 × 670 ─────┘
```

Stack arithmetic (rev-D): 20 + 240 + 150 + 240 + 20 = **670 mm** panel height × 310 mm
width (was 20+225+150+225+20 = 640 at rev-C).

### 1.1 Dimensioned rev-D panel layout (controlling dimensions)

All coordinates in mm from the panel's TOP-LEFT corner, panel hung portrait, 310 wide ×
670 tall. Board origin = board's own (0,0) corner as drawn in KiCad (BOARD A is rotated
180°, so its KiCad (0,0) lands at the panel-zone's bottom-right).

| # | Feature | Dimension / position | Source |
|---|---|---|---|
| D1 | Panel usable area (min) | **310 × 670** | stack arithmetic above |
| D2 | Board A zone (rotated 180°) | x 30–280, **y 20–260** | 250×240 rev-D outline + §1 clearances |
| D3 | Middle DIN band | **y 260–410** (150 tall) | DDR-60G-5 + fuse blocks + Pi DRP2 |
| D4 | Board B zone (as designed) | x 30–280, **y 410–650** | 250×240 rev-D outline |
| D5 | Board outline (each) | **250.0 × 240.0** true keep-in, zero overhang | rev-D `BOARD_W/H` |
| D6 | MK hole pattern (each board) | **242 × 232**, M3, holes at board (4,4) (246,4) (4,236) (246,236) | `place_components_revD.py` (was 242×217; bottom holes moved to y=236) |
| D7 | MK pattern on panel, board B | panel (34, 414) (276, 414) (34, 646) (276, 646) | D4 + D6 |
| D8 | MK pattern on panel, board A (180°) | panel (34, 24) (276, 24) (34, 256) (276, 256) | D2 + D6 |
| D9 | Standoffs | 12 mm metal at MK holes ONLY + 1 adhesive center support under the relay band | §1 mounting rule |
| D10 | Board-edge clearances | MKDS output edges 30 · MCV field edges 20 (30 w/ duct) · J1/J2/J14 edge 25 · J13 edge 15–20 | §1 clearance table |
| D11 | **Row-39/40 bottom-edge copper keep-clear** | see §1.2 — no lip/clamp/conductive contact within **≥ 3 mm** of each board's y=240 edge over the opto-column span (board x ≈ 52–92) | routed board (SLOW_AUX11 copper 1.28 mm from edge) |
| D12 | USB keep-out (each board) | 16 × 12 × 40 mm envelope off the Pico USB face (board top edge) — no duct/cable-tie hardware inside it | spec §B |
| D13 | Gland wall (bottom face of BOX) | ~9 × M20, Bundle-1/Bundle-3 ≥ 50 mm apart per lane | §4 |

SVG/CAD drawing: optional follow-up; the table above carries every controlling dimension
and is the buildable artifact (generated numbers cross-checked against
`place_components_revD.py` BOARD_W=250 / BOARD_H=240 / MK at (4,4)…(246,236)).

### 1.2 Row-39 bottom-edge copper — BINDING constraint on the lip/clamp/backplate (H8)

The rev-D routed board carries live **SLOW_AUX11** copper to **y = 238.72 mm — 1.28 mm
from the y=240 routed edge** (row 39/40 of the re-pitched opto column). Legal vs the
0.5 mm copper-to-edge rule and typical ±0.3 mm routed-edge tolerance, but:

- **Any enclosure lip, panel clamp, edge guide, or backplate flange along a board's
  bottom edge contacts row-39 copper FIRST.** The mounting design must keep every
  conductive or clamping feature ≥ 3 mm clear of the board's y=240 edge across the opto
  column span (board x ≈ 52–92 mm) — standoffs at the MK holes are the ONLY approved
  contact (D9).
- Handling/depanel nicks on that edge land on live AUX11 copper — inspect the bottom
  edge at first article (G12 includes it).
- The 36-row alternative (declining OG-1) removes row 39 entirely; if that respin ever
  happens, this constraint dissolves.

**Clearances (derived from real connector geometry, not blanket 60 mm):** rigid parts have ZERO
edge overhang — the 250×240 outline is a true keep-in. Wire-only crossings: MKDS output edges
30 mm (12× 18 AWG lateral entry + bend + duct wall), MCV field-plug edges 20 mm min / 30 mm with
a vertical duct (plugs pull out of the panel plane; clearance is finger room), J2/J1/J14 edge
25 mm (wire band into the middle rail), J13 edge 15–20 mm. Facing MCV/vertical-exit edges may
share ~40 mm; facing MKDS wire edges must not share.

**Board mounting:** 4× M3 at **242 × 232 mm** (MK1–MK4; rev-D bottom holes moved to board
y=236 — the rev-C 242 × 217 pattern does NOT fit a rev-D board; drill new panels to §1.1
D6–D8), 12 mm metal standoffs at the holes only — **nothing else conductive may touch the
board underside** (isolation gutters are copper-only; and the §1.2 row-39 edge constraint
binds every clamping feature). Add one center support pad (adhesive standoff) under the
relay band — the M3 pattern leaves the J6–J11 screw-torque zone 8 mm from an unsupported
edge mid-span.

**Tie-downs:** MC 1,5 ST plugs have no locking flange and every plug axis is horizontal on a wall
panel — anchor each harness bundle within ~50 mm of J3/J4/J5/J13/J14 on both boards.

**Depth:** DIN row governs — ~62 mm off-panel (DDR + rail); board stack ~50 mm. Any standard
≥8 in (203 mm) deep box is comfortable.

## 2. Enclosure

| Role | Part | Notes |
|---|---|---|
| **Primary** | **Saginaw SCE-30EL2408LP** (30×24×8 in, NEMA 12, hinged) + subpanel **SCE-30P24** (686×533 mm usable) | Hung portrait: the rev-D **670-tall** layout fits the 686 mm panel with **16 mm to spare** (was 46 mm at rev-C's 640) plus 220 mm of spare width for ducting — margin is now thin in HEIGHT; verify subpanel mounting-stud intrusions against §1.1 before drilling. $467 AutomationDirect (15 stock 2026-07-14) / $397 Solutions Direct; subpanel ~$75. |
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
   (Note the standing direction went the OTHER way: rev-D GREW to 240 mm — a shrink respin
   would first have to claw back the 40-row opto column.)
5. Head-end pick (injectors vs switch) at fleet purchase time.
6. **(H8, 2026-07-21) Backplate / lip / clamp detail design must satisfy §1.2** (row-39
   bottom-edge copper keep-clear) and use the §1.1 D6–D8 mounting pattern — the sourcing
   brief's hard requirement #1 is reissued at **≥ 310 × 670 mm** usable panel
   (`phase8_enclosure_sourcing_brief_GPT.md`); nominal 700-mm-class panels are now
   MARGINAL (≤ 30 mm headroom) — verify true usable height per candidate.
