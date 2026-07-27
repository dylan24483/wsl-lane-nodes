# Phase 8 — Pair Enclosure, CUSTOM PANEL + CUSTOM PLASTIC BOX

**Written 2026-07-26. Supersedes `phase8_pair_enclosure_spec.md` §1/§1.1/§2 (Layout D, 310 × 670,
Saginaw SCE-36EL3008LP) for the FLEET article.** The Saginaw is dropped; the owner builds a
custom rigid-PVC shroud around a plywood backing panel of our choosing. Panel size and aspect
ratio were free variables and have been spent deliberately.

**Layout name: `PANEL-W2` — landscape, both boards unrotated side-by-side, one service band
across the top, Pi between the two breakouts, four vertical duct lanes to a bottom gland wall.**

Board revision: rev-D r6, 250.0 × 240.0 mm. One enclosure per lane PAIR.

**What survives from Layout D:** the ribbon rule (C8 ≤ 150 mm), the invariant that *every board's
y=0 edge faces the Pi/power band*, the per-edge wire clearances, the row-39 keep-clear, the
two-ground-domain rule, standoffs-only board contact, USB keep-out, gland separation.
**What is deleted:** the vertical stack, the 180° Board-A rotation, the 310 mm width, the 150 mm
middle band, the portrait hang, and everything in old §2 that reasons about a steel NEMA-12 box.

---

## 1. THE LAYOUT

### 1.1 Panel

| | |
|---|---|
| **Plywood panel** | **1100 mm (W) × 570 mm (H) × 12.7 mm (½″)** |
| Orientation | **Landscape**, hung with the 1100 mm dimension horizontal |
| Origin for every coordinate below | **panel top-left corner**, +x right, +y down |
| Perimeter land (box wall footprint) | **25 mm all round** → interior usable **x 25–1075, y 25–545** |
| Panel area | 0.627 m² · **4 panels per 4×8 sheet** · **4 sheets** for 16 pairs |

### 1.2 Vertical band structure (full width)

| Band | y range | Height | Contents |
|---|---|---|---|
| Perimeter land (top) | 0–25 | 25 | box wall sits here; no hardware |
| **Lacing channel** | 25–50 | 25 | 1×1 in slotted duct, x 60–1050. Carries: 12 V feeds, Cat6 patch, 2× camera video coax. **No I²C, no 5 V.** |
| **DIN / module band** | 50–175 | 125 | R1a · R1b · Pi · PoE splitter. Modules bottom-justified to y = 175. |
| **Wire band** | 175–220 | 45 | **HARDWARE-FREE BY RULE.** J1 ribbons, J2 power, J14 pairs, both USB keep-outs. |
| **Board zone** | 220–460 | 240 | Board A and Board B, both rotation 0° |
| J13 clearance | 460–480 | 20 | J13/J16 fan-out |
| **Gland / drip band** | 480–545 | 65 | drip loops, gland-wall tie mounts, lane-22 isolated-sensor lateral |
| Perimeter land (bottom) | 545–570 | 25 | box wall sits here |

`25 + 25 + 125 + 45 + 240 + 20 + 65 + 25 = 570` ✔

### 1.3 Horizontal structure (symmetric about x = 550)

| Feature | x range | Width |
|---|---|---|
| Perimeter land (left) | 0–25 | 25 |
| Left margin — **FIELD_GND island (R2)** + Bundle-1A drip | 25–148 | 123 |
| **Duct-L1** — lane 21 FIELD | 148–180 | 32 |
| MCV clearance A | 180–210 | 30 |
| **BOARD A (lane 21)** | 210–460 | 250 |
| MKDS clearance A | 460–490 | 30 |
| **Duct-L2** — lane 21 MACHINE | 490–522 | 32 |
| **SEPARATION CORRIDOR** (keep-clear) | 522–578 | **56** |
| **Duct-L3** — lane 22 FIELD | 578–610 | 32 |
| MCV clearance B | 610–640 | 30 |
| **BOARD B (lane 22)** | 640–890 | 250 |
| MKDS clearance B | 890–920 | 30 |
| **Duct-L4** — lane 22 MACHINE | 920–952 | 32 |
| Right margin — Cat6/video riser | 952–1075 | 123 |
| Perimeter land (right) | 1075–1100 | 25 |

### 1.4 ASCII plan view (not to scale; x → right, y ↓)

```
 x=0   25        148 180  210                  460 490 522 578 610  640                  890 920 952       1075 1100
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ y=0
  │  ░░░░░░░░░░░░░░░░░░░░░░░░░  P E R I M E T E R   L A N D  (25 mm — box wall lands here)  ░░░░░░░░░░░░░░░░░░░  │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 25
  │   ╔══════════════ LACING CHANNEL  1×1 duct  x 60–1050 ═══ 12 V feeds · Cat6 patch · 2× video coax ═══════╗   │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 50
  │        ┌─── RAIL R1a  x150–394 ───────────────┐        ┌ Pi 4B ┐       ┌ R1b x728–836 ┐   ┌──────────────┐   │
  │        │[DDR-60G-5][0V bus][F5F4F3F2]  [C7-A] │        │+F-1019│       │ [C7-B]  [F1] │   │ PoE GBT-12V60│   │
  │        │  158-210   215-239  244-276  305-385 │        │502-618│       │ 736-815  820 │   │  x 860–1010  │   │
  │        └───────────────────────────────────────┘        └───────┘       └──────────────┘   │ RJ45 → x1010 │   │
  │                                                                                            └──────────────┘   │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 175
  │   W I R E   B A N D  —  H A R D W A R E   F R E E    [USB-A 302-318]              [USB-B 732-748]            │
  ├───────────┬────┬────────────────────────────────┬───┬────┬──┬────┬───────────────────────────┬────┬─────────┤ 220
  │           │ D  │ J2·J1·J14 ▲                    │   │ D  │  │ D  │ J2·J1·J14 ▲               │    │  Cat6   │
  │ ┌───────┐ │ U  │  ┌──────────────────────────┐  │   │ U  │KP│ U  │  ┌──────────────────────┐ │ D  │  +video │
  │ │  R2   │ │ C  │ M│                          │M │   │ C  │E │ C  │ M│                      │M│ U  │  riser  │
  │ │ D7+F6 │ │ T  │ C│   BOARD A  (lane 21)     │K │   │ T  │E │ T  │ C│  BOARD B  (lane 22)  │K│ C  │ x1035-  │
  │ │FIELD_ │ │ L  │ V│   x 210–460 · y 220–460  │D │   │ L  │P │ L  │ V│  x 640–890           │D│ T  │  1070   │
  │ │ GND   │ │ 1  │ │   rotation 0°            │S │   │ 2  │C │ 3  │ │  rotation 0°         │S│ L  │         │
  │ │ ISLAND│ │    │ │                          │  │   │    │L │    │ │                      │ │ 4  │         │
  │ └───────┘ │    │  └──────────────────────────┘  │   │    │R │    │  └──────────────────────┘ │    │         │
  │           │    │        J13 ▼   J16 ▼           │   │    │  │    │      J13 ▼  J16 ▼        │    │         │
  ├───────────┴────┴────────────────────────────────┴───┴────┴──┴────┴───────────────────────────┴────┴─────────┤ 480
  │  G2   G1        G3                     G4      │   │  G5      G6            G7            G8    G10   G9    │
  │ ▼120 ▼164      ▼314                   ▼506     │   │ ▼594    ▼650          ▼744          ▼936  ▼1010 ▼1050 │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 545
  │  ░░░░░░░░░░░░░░░░░░░░░░░░░  P E R I M E T E R   L A N D  (25 mm)  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
  └─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ 570
        LANE 21  ◄── Bundle-1 gland G1 = x164 ····· 342 mm ····· Bundle-3 gland G4 = x506 ──►
        LANE 22  ◄── Bundle-1 gland G5 = x594 ····· 342 mm ····· Bundle-3 gland G8 = x936 ──►
```

### 1.5 Placement table — every item, mm from panel top-left

`x, y` = top-left corner of the item's footprint. `w × h` = footprint in the panel plane.
`Z` = height off the plywood face.

#### Boards and board mounting

| # | Item | x | y | w | h | Z | Notes |
|---|---|---|---|---|---|---|---|
| P01 | **BOARD A (lane 21)**, rev-D r6, **rotation 0°** | 210 | 220 | 250 | 240 | 12 + 1.6 | KiCad (0,0) at panel (210,220). True keep-in, zero rigid overhang. |
| P02 | **BOARD B (lane 22)**, rev-D r6, **rotation 0°** | 640 | 220 | 250 | 240 | 12 + 1.6 | Identical orientation to A. **No 180° flip anywhere on this panel.** |
| P03 | MK standoffs, Board A | — | — | M3 | — | 12 | (214,224) (456,224) (214,456) (456,456) — 242 × 232 |
| P04 | MK standoffs, Board B | — | — | M3 | — | 12 | (644,224) (886,224) (644,456) (886,456) — 242 × 232 |
| P05 | Centre supports, Board A — **3 × screwed nylon standoff, 12 mm** | 436 | 314 | 12 | 82 | 12 | Centres (442,320) (442,355) (442,390) = board-local x=232, y=100/135/170. Window board-x 198–240 verified clear of THT pads. **Screwed, not adhesive** — adhesive fails on painted ply at 40 °C in oil mist. |
| P06 | Centre supports, Board B | 866 | 314 | 12 | 82 | 12 | Centres (872,320) (872,355) (872,390) |

**Board-A connector coordinates on the panel** (add 430 to x for Board B, y identical):

| Connector | Panel x | Panel y | Board-local |
|---|---|---|---|
| J2 `J_PWR` (5 V in, MKDS) | 326 | 230 | (116, 10) |
| J1 `J_PI` (IDC20, rot 90) | **345.5** | **230** | (135.5, 10) |
| J14 `J_SAFE` | 377 | 230 | (167, 10) |
| Pico USB face (keep-out) | 302–318 | 220 | x 92–108, y 0–7.5 |
| J3 `J_FAST` (MCV) | 219 | 262 | (9, 42) |
| J4 `J_SLOW_A` | 219 | 323 | (9, 103) |
| J5 `J_SLOW_B` | 219 | 388 | (9, 168) |
| J15 `J_SLOW_C` | 219 | 442 | (9, 222) |
| J6…J11 (MKDS outputs) | 452 | 288 / 310 / 332 / 354 / 376 / 398 | (242, 68…178) |
| J13 `J_LAMP` | 314 | 426 | (104, 206) |
| J16 `J_EXT_I2C` (unpopulated) | 338 | 426 | (128, 206) |

Board B: J2 = 756 · **J1 = 775.5** · J14 = 807 · USB 732–748 · MCV column x = 649 ·
MKDS column x = 882 · J13 = 744 · J16 = 768.

#### Service band — rails and modules (all bottom-justified to y = 175)

| # | Item | x | y | w | h | Z | Notes |
|---|---|---|---|---|---|---|---|
| P10 | **DIN rail R1a** (DN-R35S1-2, 35 mm slotted) | 150 | 130.5 | 244 | 35 | 7.5 | Rail centreline **y = 148**. Carries the 5 V group + C7-A. |
| P11 | KN-EB3 end bracket | 150 | — | 8 | — | — | left end of R1a |
| P12 | **Mean Well DDR-60G-5** (main 5 V) | 158 | 85 | 52.5 | 90 | 54.5 | **TRIM TO 5.20–5.25 V AT ITS OWN TERMINALS BEFORE LANDING ANY LOAD** (audit M-03). Trim pot faces the lid and stays reachable. |
| P13 | **5 V RETURN BUS — 4 × INSULATED feed-through** (KN-T/KN-S class) + jumper comb | 215 | 133 | 24 | 42 | 41 | ⛔ **NOT KN-G10.** Green/yellow PE-class blocks on the logic 0 V bus invite an earth bond and defeat the TMA-0505S isolation (M-04). 4 blocks = 8 landings vs 6 needed. |
| P14 | **F5** KN-F10 — CAMERA 12 V (logic-referenced) | 244 | 111 | 8 | 64.2 | 43.2 | 240 mm from F6, different rail, DDR physically between them. |
| P15 | **F4** KN-F10 — Pi, **4 A time-delay** | 252 | 111 | 8 | 64.2 | 43.2 | Feeds the USB-C pigtail. **Never feed raw GPIO or J1 pins 1/11.** |
| P16 | **F3** KN-F10 — Board B J2, **2 A fast** | 260 | 111 | 8 | 64.2 | 43.2 | |
| P17 | **F2** KN-F10 — Board A J2, **2 A fast** | 268 | 111 | 8 | 64.2 | 43.2 | F2/F3 **ARE** the H-23 fix — the board has no input protection. |
| P18 | **C7-A** Electronics-Salon **D-220** IDC20 breakout | 305.8 | 88 | 79.4 | 87 | 54 | Centred x = **345.5 = J1-A exactly**. **IDC header edge must face the boards (high-y).** One-time continuity beep before power: J1 term 1 = `VCC_5V` is adjacent to term 3 = `I2C_SDA`. |
| P19 | KN-EB3 end bracket | 385.2 | — | 8 | — | — | right end of R1a |
| P20 | **Raspberry Pi 4B in the CZH-LABS F-1019 metal carrier, F-1019 HAT on top** | 502 | 100 | ⚠ **MEASURE** | ⚠ | ⚠ | ✅ **RESOLVED 2026-07-27 by trial fit.** The F-1019 ships as TWO parts: a green breakout **HAT** and a two-piece **black metal carrier** (`CZH-LABS / For RPi 4 Model B / Model F-1019`). Intended assembly: Pi onto the carrier's four standoff posts → HAT onto the Pi's GPIO header → lid on. **Owner confirmed the HAT fits with the lid on and the screw terminals stay accessible.** The carrier base has **outward mounting flanges with holes**, so it screws to the plywood directly. ⛔ **C4 (DINrPlate DRP2) DELETED — the carrier is the mount.** Bonus: the metal shell restores EMI shielding the plastic box gives up, which matters most for board B's **bit-banged** I²C bus, and gives the Pi a conducted thermal path to the panel. |
| P21 | **DIN rail R1b** | 728 | 130.5 | 108 | 35 | 7.5 | Rail centreline y = 148. Separate segment so the panel-mounted Pi is not crossed by a rail. |
| P22 | KN-EB3 end bracket | 728 | — | 8 | — | — | |
| P23 | **C7-B** D-220 IDC20 breakout | 735.8 | 88 | 79.4 | 87 | 54 | Centred x = **775.5 = J1-B exactly.** Same orientation, same continuity check. |
| P24 | **F1** KN-F10 — splitter 12 V → DDR + D7, **3 A** | 820 | 111 | 8 | 64.2 | 43.2 | **Deliberately at the splitter end** — the unfused run is 36 mm; everything downstream is fused. D7's input taps F1's load side. |
| P25 | KN-EB3 end bracket | 828 | — | 8 | — | — | |
| P26 | **PoE Texas GBT-12V60W** splitter, panel-mount U-bracket | 860 | 60 | **152.4** | **66.0** | **35.6** | ✅ **RESOLVED 2026-07-27 from the manufacturer's published dimensions — INDOOR MODEL assumed, see §8.1 item 1.** *(The 6KV variant, 193.0 × 83.8 × 40.6, would leave only 22.0 mm to the wall land and is REJECTED — the RJ45 could not seat.)* **RJ45 end (PoE-in + LAN) faces +x at x = 1010**, giving **65 mm** to the wall face for the Cat6 plug (needs 45–55 with boot and latch). DC-out terminal + PWR LED face −x at x = 860, 36 mm from F1. Hottest single module (3.2 W) — 35 mm to the top wall, 65 mm to the right wall. |

#### FIELD_GND island — the second ground domain

| # | Item | x | y | w | h | Z | Notes |
|---|---|---|---|---|---|---|---|
| P30 | **DIN rail R2 — VERTICAL**, 35 mm slotted | 68 | 250 | 35 | 52 | 7.5 | Rail runs **vertically**, centreline x = 85. Deliberately in the left margin, in the FIELD domain, **240 mm from F5 and 480 mm from the DDR**, with the whole board zone between it and the logic power group. |
| P31 | KN-EB3 end bracket | — | 250 | — | 8 | — | |
| P32 | **D7 — Mean Well DDR-15G-12**, ISOLATED 12 V DC-DC | 40 | 258 | 90 | 17.5 | 54.5 | 9–36 Vdc in / 12 V 1.25 A out / **4 kVdc I-O** / load range **0–1.25 A** so the ~0.6 W sensor draw needs no dummy load. Same 90 × 54.5 envelope as the DDR-60G-5 → zero new depth. **ITS 0 V IS `FIELD_GND`.** |
| P33 | **F6** KN-F10 — ISOLATED SENSOR 12 V | 53 | 280 | 64.2 | 8 | 43.2 | Label strip: **`FIELD_GND — NOT EARTH, NOT LOGIC 0V`** |
| P34 | KN-EB3 end bracket | — | 292 | — | 8 | — | |

> ⚠️ **R2 IS NOT AN ALL-ISOLATED RAIL.** D7's *input* is logic-referenced 12 V arriving fused from
> F1. The barrier is inside D7. The F7 card must say so, or a technician will read the label and
> assume the whole rail is field-side.

#### Ducts, lanes and keep-clears

| # | Item | x | y | w | h | Z | Notes |
|---|---|---|---|---|---|---|---|
| P40 | **Lacing channel** — 1×1 in slotted PVC duct + cover | 60 | 27 | 990 | 25 | ~28 | Carries **only**: F1→DDR 12 V, F1→D7 12 V, F5→camera-B 12 V, Cat6 patch, 2 × camera video coax. **No I²C, no 5 V branch.** |
| P41 | **Duct-L1** — LANE 21 FIELD, Panduit Type G 1×2 + cover | 148 | 225 | 32 | 255 | 53.8 | Actual outside **31.75 × 53.8 mm** (nominal 1×2 in is not the real width — order cover PN separately, C1LG6/C1WH6 class). Bundle-1A (36 × 22 AWG → J3/J4/J5/J15) **+ Violet/Grey isolated sensor pair** — both FIELD domain, correctly co-routed. |
| P42 | **Duct-L2** — LANE 21 MACHINE | 490 | 225 | 32 | 255 | 53.8 | Bundle-3A (12 × 18 AWG from J6–J11) + J14-A safety pair + Brown/Pink camera pair A. |
| P43 | **SEPARATION CORRIDOR — DRAWN KEEP-CLEAR** | 522 | 175 | 56 | 305 | — | **56 mm wall-to-wall**, the one tight number on the panel: 12 % over the ≥50 mm rule across ~255 mm of parallel run between Bundle-3A (relay-switched 24 VAC, RC snubbers DNP) and Bundle-1B (opto sense, 1.1–1.34 mA). **Both duct covers MUST be fitted — that is what earns the number.** Nothing may be placed here: no tie base, no spare block, no coax. |
| P44 | **Duct-L3** — LANE 22 FIELD | 578 | 225 | 32 | 255 | 53.8 | Bundle-1B + Violet/Grey sensor pair B. |
| P45 | **Duct-L4** — LANE 22 MACHINE | 920 | 225 | 32 | 255 | 53.8 | Bundle-3B + J14-B pair + Brown/Pink camera pair B. Total duct 4 × 255 = **1020 mm/pair**. |
| P46 | **Cat6 + video riser lane** (tie-mounted, no duct) | 1035 | 175 | 35 | 370 | — | Cat6 from G9 and 2 × camera video coax from G10, up the right margin to the lacing channel. **83 mm from Duct-L4** — the free version of judge-3's 26 mm improvement. Coax and Cat6 are both shielded and both logic-referenced: co-routing them is correct. ⛔ **Video coax NEVER enters Duct-L2 or Duct-L4.** |
| P47 | **USB keep-out, Board A Pico** | 302 | 187.5 | 16 | 32.5 | 12 (Z band 13.6–25.6 off panel) | **HARD.** 16 × 12 × 40 mm envelope; 7.5 mm on-board, 32.5 mm of cable body + strain relief off the top edge. No duct, rail, tie mount, fuse block or bracket may enter it. |
| P48 | **USB keep-out, Board B Pico** | 732 | 187.5 | 16 | 32.5 | " | Same. J2-B must be approached from the right or stay above y = 200 until x > 748. |
| P49 | J13-A / J16-A fan-out (tie-mounted) | 300 | 460 | 60 | 20 | — | Wires fan over the y = 460 edge and drop to gland G3. |
| P50 | J13-B / J16-B fan-out | 730 | 460 | 60 | 20 | — | Drops to gland G7. |
| P51 | Tie-mount anchoring bands, MCV plug rows | 180–210 · 610–640 | 225–480 | 30 | 255 | — | MC 1,5 ST plugs have no locking flange and every plug axis is horizontal on a wall panel. Anchor each bundle **within 50 mm** of J3/J4/J5/J15 on both boards. Nylon only. |
| P52 | Tie mount, J14 pair (both lanes) | 470 / 900 | 200 | 15 | 15 | — | Added: without it the nearest anchor is 55 mm from J14, over the ~50 mm rule. |
| P53 | Gland-wall tie mounts | — | 500 | — | — | — | ~9 per pair along y = 500, so no gland carries cantilever harness load (L-04). |

#### Gland wall — box BOTTOM face, panel-x aligned

| Gland | Size | Panel x | Carries |
|---|---|---|---|
| G1 | **M20** | 164 | **Bundle-1A** — lane 21 field sense |
| G2 | M16 | 120 | Sensor pair A — **Violet/Grey, FIELD_GND** |
| G3 | M16 | 314 | J13-A mask/lamp run |
| G4 | **M20** | 506 | **Bundle-3A** + J14-A + camera pair A (Brown/Pink, logic) |
| G5 | **M20** | 594 | **Bundle-1B** — lane 22 field sense |
| G6 | M16 | 650 | Sensor pair B — **Violet/Grey, FIELD_GND** |
| G7 | M16 | 744 | J13-B mask/lamp run |
| G8 | **M20** | 936 | **Bundle-3B** + J14-B + camera pair B |
| G9 | **M25** ⚠ | 1050 | **Cat6.** M20 passes 6–12 mm; an RJ45 is ~13.4 mm over the latch (L-05). |
| G10 | M16 | 1010 | **2 × camera video coax** (new — see §7) |

**Separations:** lane 21 B1↔B3 = **342 mm** · lane 22 B1↔B3 = **342 mm** (rule ≥50) ·
worst cross-lane B1/B3 = G4↔G5 = **88 mm** · nearest FIELD gland to a camera gland =
G6↔G4 = **144 mm**. Every bundle gets **10 mm split loom** through its gland, Bundle 1 and
Bundle 3 in **separate looms** — without it the IP68 seal never forms (L-04), ~4 m/lane.

---

## 2. WHY THIS ONE

### 2.1 The organizing principle

> **Every board's y=0 edge faces the service band; the Pi sits BETWEEN the two breakouts; and
> nothing that switches sits between a breakout and the Pi.**

That is one sentence longer than the Layout-D invariant, and the extra clause is the whole
change. Layout D protected the *ribbon* (J1 → C7) and let the *jumper* (C7 → Pi) fall where it
may. The audit then found the jumper is the longer, noisier, un-budgeted segment (M-23: ~750 mm
through four screw-terminal transitions on untwisted UL1007). `PANEL-W2` protects both:

| Segment | Layout D | Layout W (first draft) | **PANEL-W2** |
|---|---|---|---|
| J1 → C7 ribbon, board A | ~100 mm | 113 mm | **~125 mm** |
| J1 → C7 ribbon, board B | ~150 mm | 113 mm | **~125 mm** |
| C7 → Pi jumper, board A | not budgeted | ~285 mm, past the DDR | **~135 mm, clear band** |
| C7 → Pi jumper, board B | not budgeted | ~60 mm | **~135 mm, clear band** |
| Screw-terminal transitions | 4 | 2 | **2** |
| **Total I²C path, each board** | ~750 mm | ~170 / ~395 mm | **~260 mm, symmetric** |

Both C7 modules are centred on their own J1's x to the millimetre (345.5 and 775.5), so the
ribbon is a pure vertical rise with **zero lateral**. The Pi is centred between the two C7 inner
edges, so both jumper runs are equal and neither crosses the DDR-60G-5's case. Because the two
paths are identical, **C-16 (the bit-banged bus-3 board gets the shorter run) is satisfied
trivially rather than by assignment** — the lane↔bus mapping becomes a free choice again.

### 2.2 What changed now that the panel is free-size

Four of Layout D's six stated reasons were artefacts of squeezing into a 686 × 533 mm catalogue
subpanel, and three of those four are now known to be arithmetically wrong:

| Layout-D feature | Verdict | Replacement |
|---|---|---|
| **Vertical stack** | Artefact. Side-by-side was not rejected on merit — 2 × 250 mm of board will not fit a 533 mm subpanel. | Side-by-side, both boards at 0°. |
| **Board A rotated 180°** | Consequence of the stack (a PCB can be rotated, not mirrored). | **Deleted.** One build page, used twice; one drill jig, indexed once. |
| **310 mm width = 30 + 250 + 30** | Bare minimum; the MKDS side got *no duct lane at all*. | 1100 mm. Every edge gets its full clearance **and** a duct. |
| **150 mm middle band** | Self-contradictory: net of two 25 mm J-edge wire bands it leaves 100 mm against 87–90 mm of real across-rail gear, while BOM E1 buys **two** rails. | 125 mm band, **one rail row**, real envelopes, 35 mm of vertical adjustment left over. |
| **J13 edges outboard, 20 mm margins** | A ~10–20 mm height trick that only mattered against 686 mm. | Kept anyway — it is free and it is still the cheapest edge. |
| **J1 ribbon short** | **Physics. Kept, and improved.** | ≤150 mm, symmetric, zero lateral. |
| **Opposite output sides** | Real but only half-delivered in D (board A's Bundle-3 ran 410–650 mm shoulder-to-shoulder with board B's field drops). | **342 mm of separation per lane, symmetric, no shared duct anywhere.** |

Three further things the free panel bought that a catalogue box could not:

1. **60 mm → 45 mm of top-edge clearance where the spec's own D10 says 25 and D12's USB envelope
   needs 32.5.** That contradiction is what produced the hand-shaved right-angle USB cable on
   rev-B *and* rev-C. Here the wire band is 45 mm and hardware-free, so an off-the-shelf micro-B
   seats with the ribbon mated.
2. **A dedicated FIELD_GND island.** The isolated DC-DC and F6 sit on their own vertical rail in
   the left margin, 240 mm from F5 and 480 mm from the DDR, physically inside the field-domain
   half of the panel. Layout D had one band with one rail and no separation concept at all — the
   two-domain rule post-dates it by two weeks and had no home in it.
3. **No far board.** The two lanes are mirror-symmetric about x = 550, so both in-box harness
   routes are identical. That is the finding that touches the RFQ (§7).

### 2.3 Where the three judges disagreed, and how it is resolved

| Disagreement | Resolution |
|---|---|
| **Judge 1**: rail R1 overlaps the panel-mounted Pi (116.5 × 25 mm interference) — unbuildable as drawn. **Judge 3**: same, and it kills the claimed spare rail. | **Accepted.** R1 is split into **R1a (x 150–394)** and **R1b (x 728–836)** with the Pi panel-mounted in the clear gap between them. Spare-rail claims are withdrawn: R1a has 29.8 mm free, R1b has 0. The R-12 second-Pi contingency has **no free slot** — see §8. |
| **Judge 3**: swap the Pi and the power group so no switcher sits between a C7 and the Pi. **Judge 1**: the ~285 mm Board-A jumper is the layout's soft spot. | **Accepted, and taken further.** The Pi goes to panel centre; the 5 V group goes *left of C7-A*; F1 goes *right of C7-B* next to the splitter. Nothing sits between either C7 and the Pi. |
| **Judge 3**: the J2 drop is 2.0 mV, not 15 mV — 5 V run length is free, so nothing should be positioned to shorten it. | **Accepted and corrected on the drawing.** 18 AWG UL1015 at 6.385 mΩ/m, ~0.5 m round trip, 0.65 A peak = **2.0 mV** against a 5.20–5.25 V trimmed rail and a 4500 mV daemon floor. J2-A run is ~200 mm, J2-B ~560 mm; both are electrically irrelevant. The ≤100 mm target in the old spec was a Layout-D artefact, not a derived limit. |
| **Judge 2**: grow the plywood to add a 25 mm perimeter land — "plastic lands on the plywood perimeter" and "internal footprint = panel + 25 mm" are two different builds. | **Accepted.** 25 mm land all round is now explicit and it is the box-wall screw line and gasket seat. |
| **Judge 2**: splitter RJ45 face has ~35 mm to the wall; a Cat6 plug needs 45–55. | **Accepted.** Splitter moved to x 860–1010 with **65 mm** to the wall face. |
| **Judge 2**: DIN keep-in band 95 mm is a needless squeeze on a free-size panel. | **Accepted and exceeded** — 125 mm, which is also the ribbon-length contingency (§3, C-14). |
| **Judge 3**: the camera video coaxes exist in no gland, no duct and no wire-list row. | **Accepted.** G10 + the right-margin riser + W54/W55 added to the wire list. This is the single biggest *omission* any judge found. |
| **Judge 1** scored the 56 mm corridor as "legal but no room to absorb a build error"; **Judge 2** wanted it drawn, not prosed. | **Drawn as P43, a keep-clear rectangle.** Retained at 56 mm — widening it would push the panel past 1100 mm for a 12 % → 20 % margin change. The real mitigation is the RC snubbers (§8). |
| **Judge 2**: adhesive centre standoffs are wrong for painted ply in a 40 °C oil-mist room. | **Accepted.** P05/P06 are **screwed** nylon standoffs; 6 more pilot holes. |
| **Judge 1** flagged the D-220 IDC-orientation contingency as "+40 mm and still fits" = 153 mm = a C-14 **fail**. | **Accepted as a gate.** The 125 mm band gives 35 mm of across-rail adjustment, which absorbs it. See §3 C-14 and §8 item 2. |
| **Judge 2**: plywood cost goes DOWN, not up; the write-up mis-stated it. | **Corrected in §6.** |

---

## 3. CONSTRAINT COMPLIANCE

Every HARD constraint, with the margin. Coordinates are from §1.5.

| ID | Constraint | Required | **Delivered** | Margin | ✔ |
|---|---|---|---|---|---|
| C-01 | Board outline true keep-in, zero rigid overhang | 250.0 × 240.0 ea | 250 × 240 at (210,220) and (640,220); nothing rigid within 30 mm of any board edge | ≥30 mm all sides | **PASS** |
| C-02 | MK pattern | 242 × 232, M3 | (214,224)(456,224)(214,456)(456,456); (644,224)(886,224)(644,456)(886,456) | exact | **PASS** |
| C-03 | Standoffs the only conductive board contact | — | 4 × 12 mm brass at MK only; centre supports are **nylon** | — | **PASS** |
| C-04 | Bottom-edge (y=240) copper keep-clear, **full 250 mm span** (L-13, not the spec's x 52–92) | ≥3 mm | 20 mm to the J13 fan-out band; nearest tie base at y = 480 | **20 mm** | **PASS** |
| C-05 | **Top-edge (y=0) keep-clear** — carries the board's closest copper of all (VCC_5V via at 1.150 mm), uncovered by the written rule | ≥3 mm | 45 mm hardware-free wire band above both boards | **45 mm** | **PASS** |
| C-06 | Centre support under the relay band | ≥1/board (L-08 says 3) | **3 per board**, screwed nylon, board-x 232, y 100/135/170 | L-08 fully adopted | **PASS** |
| C-08 | MKDS output edge clearance | 30 mm | Board A 460→490 (Duct-L2); Board B 890→920 (Duct-L4) | **30.0 mm, exact** | **PASS** |
| C-09 | MCV field edge clearance | 20 min / **30 with a vertical duct** | Board A 180→210; Board B 610→640 | **30.0 mm, exact** | **PASS** |
| C-10 | J1/J2/J14 edge clearance | 25 mm | 45 mm hardware-free | **+20 mm** | **PASS** |
| C-11 | J13 edge clearance | 15–20 mm | 20 mm (y 460–480) | top of range | **PASS** |
| C-12 | Two facing MKDS wire edges must not share | — | No two output edges face each other anywhere. A's output edge faces B's *field* edge across 180 mm | structural | **PASS** |
| C-13 | USB keep-out 16 × 12 × 40 mm, both Picos | 32.5 mm off the top edge | 45 mm hardware-free band; corridors x 302–318 and 732–748 empty from y 175 to the board | **+12.5 mm** | **PASS** |
| **C-14** | **C8 ribbon ≤ 150 mm, both boards** | ≤150 | **~125 mm**: 15 (exit) + 30 (Z rise, 24→54 mm) + 65 (in-plane, y 230→165) + 15 (entry). **Zero lateral.** 15 mm min bend radius assumed. | **25 mm** | **PASS** |
| C-15 | Two C7 breakouts, each beside its OWN J1 | 2 | C7-A centred x 345.5 = J1-A; C7-B centred x 775.5 = J1-B | exact | **PASS** |
| C-16 | Shorter ribbon to the bit-banged bus | asymmetry must favour bus 3 | **Both ribbons and both jumpers identical** — constraint is moot, lane↔bus mapping is free | n/a | **PASS** |
| C-17 | Total I²C path (unbudgeted; >500 mm = red flag) | — | **~260 mm** per board through **2** screw-terminal transitions (vs M-23's ~750 mm / 4) | 48 % of the red-flag line | **PASS** |
| C-18 | J2 power run | ≤100 mm target; 800 mm L0 wall | 200 mm (A) / 560 mm (B). **Drop = 2.0 mV** (18 AWG, 6.385 mΩ/m, 0.65 A). Fused at source by F2/F3 → whole conductor protected. | target is an artefact; see §2.3 | **PASS (target bent, deliberately)** |
| C-19 | Six fuse branches, correct roles | F1 3A · F2/F3 2A fast · F4 4A T · F5 camera · F6 sensor | All present: F1 P24, F2 P17, F3 P16, F4 P15, F5 P14, F6 P33 | — | **PASS** |
| C-20 | 5 V return bus must NOT be PE-class hardware | insulated, ≥6 landings | 4 × insulated feed-through + jumper comb = 8 landings (P13) | +2 landings | **PASS** |
| C-21 | DDR trim pot reachable after build | — | P12 at x 158–210.5, front face open to the lid, nothing above it | — | **PASS** |
| C-22 | F6 → sensors on the ISOLATED DC-DC, 0 V = FIELD_GND | separate supply | D7 (4 kVdc) on rail R2, its own island | — | **PASS** |
| C-23 | F5 → camera on the ORDINARY 12 V | non-isolated | F5 on R1a, fed from F1's 12 V | — | **PASS** |
| C-24 | Physical separation of the two 12 V domains | "separate bundles, never laced" | **F5↔F6 = 240 mm on separate rails with the DDR between.** Violet/Grey ride the FIELD ducts (L1/L3); Brown/Pink ride the MACHINE ducts (L2/L4). Lane-22 Violet/Grey routes **down L1 → along the gland band (y 500) → G6**, never entering the logic zone or the wire band. | 240 mm | **PASS** |
| C-25 | Single-point shield drain to LOGIC GND, enclosure end only | one designated landing | **Landing #4 of the 5 V return bus (P13) is reserved and labelled `SHIELD DRAIN — LOGIC GND, THIS END ONLY`.** Named here because Layout W named it nowhere and the steel box is gone. | — | **PASS** |
| C-26 | All glands on ONE face, drip loops | one face | All 10 on the box **bottom** face; 65 mm drip band on the panel | — | **PASS** |
| C-27 | Per lane, Bundle-1 vs Bundle-3 glands | ≥50 mm | **342 mm** both lanes; worst cross-lane 88 mm | **6.8×** | **PASS** |
| C-28 | Gland count | 10 | 10 (G1–G10) | — | **PASS** |
| C-29 | Cat6 gland > M20 | RJ45 ~13.4 mm | **G9 = M25**; G2/G3/G6/G7/G10 down to M16 so the seal actually forms | — | **PASS** |
| C-30 | Split loom, B1 and B3 separate, ≥50 mm | ~4 m/lane | Specified; loom is a panel-build item, not a harness item | — | **PASS** |
| C-31 | Tie anchors within ~50 mm of every MCV plug row | ≤50 mm | P51 bands 0–39 mm from J3/J4/J5/J15 both boards; **P52 added for J14** (was 55 mm) | ≤39 mm | **PASS** |
| C-32 | Interior depth | ≥80 mm clear | **115 mm** clear panel-to-lid | +35 mm | **PASS** |
| C-33 | Real across-rail DIN envelopes (not the dead 28 mm placeholder) | 87–90 mm | 125 mm band; DDR 90 → y 85–175; D-220 87 → y 88–175 | **35 mm** | **PASS** |
| C-34 | Along-rail arithmetic must close on real widths | sum, don't count modules | R1a: 8+52.5+24+32+79.4+8 = 203.9 in 244 → 40.1 free. R1b: 8+79.4+8+8 = 103.4 in 108 → 4.6 free. R2: 8+17.5+8+8 = 41.5 in 52 → 10.5 free. | closes | **PASS** |
| C-35 | Pi + F-1019 as ONE unit | — | P20, panel-mount Mode 1; **C4/DRP2 deleted** (mechanically mutually exclusive) | — | **PASS** |
| C-36 | In-box routing budget behind the 3200 mm L1 cut | 750–950 mm | **~630 mm worst case.** **MISS — in the safe direction. See §7.** | −120 to −320 mm | ⚠ **DISCLOSED** |
| C-38 | Wire-map card, flat interior surface | — | Lid interior, 200 × 300 mm clear area at x 400–700 | — | **PASS** |
| C-39 | Pico UF2 reflash with the J1 ribbon mated | off-the-shelf micro-B | 45 mm clear corridor, no hardware; BOOTSEL reachable | — | **PASS** |
| C-40 | MCV plugs unplug perpendicular — Z pull path clear to the lid | ~25 mm | 115 mm clear depth; plug body ~15 mm + 12 board stack = 29 mm, so **86 mm of pull path** | +61 mm | **PASS** |
| C-42 | Duct fill ratio — **undefined anywhere in the repo** | — | **SET: 40 % maximum fill, covers fitted.** Worst lane (Bundle-1, 36 × 22 AWG + 2 × 18 AWG) ≈ 9 % of a 1×2 duct. | — | **SET** |
| C-43 | Cable bend radius — **undefined anywhere in the repo** | — | **SET: 20-way IDC ribbon ≥15 mm; 18 AWG UL1015 ≥12 mm; Cat6 ≥25 mm; camera coax ≥8× OD.** | — | **SET** |
| C-45 | Steel-box rules that lapse | — | Enclosure earthing, subpanel studs, portrait-only, 686/838 arithmetic — **all void.** C-20, C-22/23, C-25, C-04/05 **do not lapse.** | — | **NOTED** |
| C-46 | Wall-mount hardware (L-16, in no BOM section) | — | **Added** — French cleat pair, §6 | — | **CLOSED** |

**The three numbers with the least margin, in order:** C-34 rail R1b (4.6 mm free along rail) ·
C-08 / C-09 (30.0 mm exact, four times) · the 56 mm separation corridor (12 % over the rule).
None of them move without moving the panel size, and all three are dimensioned so a build error
is visible rather than silent.

---

## 4. THE BOX

### 4.1 Internal envelope

| | |
|---|---|
| **Internal clear W × H × D** | **1100 × 570 × 115 mm** |
| Back | **is the plywood panel** — the shell lands on the panel's 25 mm perimeter land |
| Outside, in 6 mm PVC | ~1112 × 582 × 121 mm |
| Depth driver | DIN row: 7.5 rail + 54.5 (DDR-60G-5 / DDR-15G-12) = **62.0 mm** static |
| Second-deepest | Duct 53.8 · D-220 breakout 61.5 · splitter 37 · F-1019 36.7 · board stack 13.6 + connectors |
| Why 115 and not 80 | MCV plugs pull **perpendicular** to the panel (29 mm occupied, 86 mm of pull path) and the KN-F10 fuse carriers are **hinged lids that swing ~60 mm off-panel** |

> ⚠️ **FUSE-CARRIER SWING KEEP-OUT.** The KN-F10 carrier is a hinged lid, not a pull-out. Its
> highest swept point is **~110 mm off the panel**. Nothing may be mounted on the **inside of the
> lid** above **x 240–290 and x 810–840, y 100–180** (the F2–F5 and F1 rows). At 115 mm clear the
> carriers swing into the lid volume with the lid open — which is the only time they are opened.

**Module-to-wall standoff: ≥25 mm for every dissipating module.** PVC's HDT is 65–70 °C and the
splitter case runs ~72 °C at 40 °C air; plastic's thermal spreading length is ~13 mm against
steel's ~110 mm, so a plastic wall cannot smear a hot spot. Delivered: DDR 60 mm to the top wall
· splitter 35 mm top / 65 mm right · Pi 75 mm top. D7 (0.45 W) is 15 mm from the left wall and
is exempt on dissipation.

### 4.2 Gland wall

**Bottom face only, 10 glands, per §1.5.** Drill **20.5 mm** for M20, **16.5 mm** for M16,
**25.5 mm** for M25 — **step-drill or hole-saw with a backing block; do not use a hole saw
alone, PVC cracks from the pilot notch.** Glands are **NYLON, not nickel-plated brass** — this is
now a requirement, not a preference (§4.5). Land the P53 tie mounts **inside, within 50 mm of
every gland**, so the gland carries no cantilever load from 3.2–4.7 m of harness per lane.

**The gland wall is the one wall that gets extra material: 10 mm, or 6 mm with a solvent-welded
6 mm doubler strip.** Nine compression nuts bearing on a thin face with that much harness hanging
off them will craze and pull through.

### 4.3 Material and thickness — decided

| Part | Spec |
|---|---|
| **Shell (3 walls + top)** | **Rigid PVC Type 1 sheet, 6 mm**, solvent-welded corners |
| **Gland wall (bottom)** | **Rigid PVC Type 1, 10 mm** |
| **Lid** | **Rigid PVC Type 1, 6 mm**, with **2 × 25 × 25 mm PVC stiffening ribs solvent-welded vertically at x = 400 and x = 750** |
| Lid seal | 10 × 5 mm closed-cell EPDM/neoprene adhesive gasket, 3.4 m, on the shell's front face |
| Lid retention | **2 × 300 mm stainless piano hinge on the LEFT edge** + **8 over-centre draw latches** (2 top, 2 bottom, 4 right) at ≤180 mm spacing |
| Panel attachment | Shell wall carries a solvent-welded 6 mm flange lying on the 25 mm land, screwed to the plywood **#8 × ¾″ every 150 mm** |

**Why PVC Type 1:** inherently **UL 94 V-0** (LOI ~45 — no FR package to specify or get wrong),
excellent resistance to mineral oil, acids and alkalis (which is the actual environment), cheap
in sheet, saws and routs cleanly, solvent-welds. k ≈ 0.17 W/m·K.

- **Acceptable alternate:** FR-ABS (V-0 in **FR grades only** — plain ABS is HB; HDT 90–100 °C).
- ⛔ **Avoid polycarbonate** — environmental stress cracking with alkaline degreasers is a real
  machine-room failure mode.
- ⛔ **Refuse PP, HDPE and acrylic outright** — all UL 94 **HB**, all burn, in a box with a 60 W
  supply. The steel was the only non-combustible boundary in the assembly and it is going; the
  panel is already combustible plywood. **V-0 minimum is not negotiable.**
- Optional, ~$10: a **1 mm aluminium or 0.8 mm steel sheet BEHIND the plywood** under the J6–J11
  output band (panel x 440–470, y 270–410). Behind the panel, so it cannot violate the
  standoffs-only rule or the 3 mm edge keep-clear.

**A 1100 mm lid span will bow and the gasket will leak in the middle.** The two ribs plus 8
latches at ≤180 mm are what stop that, and a bowed lid is exactly how oil mist gets in.

### 4.4 Venting — **NO VENTS. DECIDED.**

Two generous louvres (100 × 60 mm at 65 % free area, 450 mm apart, ΔT 5 K) would move 0.91 L/s
and carry **5.14 W of the 13 W** — turning a 3.5 K rise into ~2.2 K. **That is 1.3 K.**

In exchange, lane-oil mist and pin dust get a direct path onto the isolation gutters the entire
safety case rests on: **LOGIC↔FIELD 2.6505 mm** and **LOGIC↔MACHINE 3.3505 mm**, with only
0.15 mm of etch allowance in the budget. Oil plus dust is a tracking film and it lands exactly
where the creepage was spent. **1.3 K is not a trade.** This upholds sourcing-brief hard
requirement #4 rather than reopening it.

**Thermal envelope, for the record.** In-box dissipation is **~13 W play-average / ~21 W
instantaneous peak / ~8 W idle** (the repo's standing "~20 W" is the *peak*; the 4-second
all-coils peak is thermally invisible against a ~35–40 min box time constant). A
1112 × 582 × 121 mm box has A_ext ≈ 1.70 m², A_eff ≈ **1.06 m²** after discounting the
wall-mounted back face; at U = 4.5 W/m²·K the rise is **2.7 K at 13 W and 4.4 K at 21 W** →
internal air **38–40 °C at 35 °C ambient**. Every part is rated ≥70 °C.
**Going steel → plastic costs 0.5 K, not "a few degrees"** — the sealed-box resistance is two
surface films in series with the wall, and a 1.5 mm steel wall is ~7,400× smaller than the films
it sits in series with. Emissivity does not degrade (PVC 0.90–0.95 vs powder-coated steel
0.85–0.92). **Thermal imposes no floor on panel size that this layout does not clear 3× over,
and thermal must not be cited to grow or shrink it.**

**FIT THE GORE BREATHER (E8) — promote from "optional" to REQUIRED.** M12, on the bottom wall at
panel x ≈ 860. The *lower* the self-heating, the *higher* the condensation risk: this box barely
self-heats and will sit at or below dew point on humid mornings in an unheated area.

**The real thermal item is the Pi, and it binds identically in a steel box.** BCM2711 at 4.5 W
(daemon + camera scoring) with a heatsink lidded by the F-1019 lands ~94 °C against an 80–85 °C
throttle point. ⚠️ **The previously-proposed fix — "raise the F-1019 on 20–25 mm stacking
headers" — is INVALID**: the F-1019 is a complete aluminium carrier (Pi into the bottom cover,
brass standoffs, terminal board onto the GPIO header, top cover over), so raising it means it no
longer closes, and the datasheet caps the heatsink at **< 8.5 mm** with **no CPU fan possible**.
**Do this instead:**
1. Run the F-1019 with its **top cover omitted** — the sealed box already provides the mechanical
   and ingress protection that cover was for.
2. Fit the tallest heatsink the 8.5 mm budget allows.
3. Fit **one 40 mm 5 V ball-bearing fan inside the box**, blowing across the Pi, at panel
   (470, 131) — zero wall penetration, zero ingress cost, ~0.7 W. **Run it continuously at low
   RPM** (an intermittent fan is a fan that seizes) and **make nothing depend on it**.
   It also collapses stratification, which is worth more than its ~1 K box-level effect.

**Pilot-soak acceptance (closes enclosure-spec open item #1 as written):** log
`vcgencmd measure_temp` **plus the throttled flag** continuously; IR the splitter case, DDR case,
hottest relay and Pi heatsink at the end of a busy league night. **Internal air ≤ ambient + 10 K ·
Pi SoC ≤ 70 °C sustained with zero throttle events · splitter case ≤ 65 °C.**

### 4.5 Earth and bond — **there is no protective earth in this box, and that is correct**

Nothing inside exceeds SELV: **57 V DC PoE** and **24 VAC on the dry relay contacts**. No mains,
no 115 VAC (that never enters the enclosure), and the 42 VAC DIELL supply was deleted 2026-07-26.
**No protective earth is required.**

The old spec spends a paragraph on a hazard — *"the enclosure body is earthed; the boards' logic
GND must NOT bond to it"* — that a plastic box makes **structurally impossible to violate**. That
is a net win for the isolation contract the whole 40-channel input design rests on. Consequences:

1. ⛔ **E7's NYLON glands are now a REQUIREMENT.** Refuse any nickel-plated-brass substitution
   "for better strain relief" — it would reintroduce a metallic path through the wall.
2. ⛔ **The 0 V bus is NOT earth. Never bond it.** On the F7 card, in those words (M-04).
3. **FIELD_GND bonds to machine chassis via the harness ring lugs, NEVER inside the box.**
4. **Bundle-1 shield drains terminate to LOGIC GND at the enclosure end ONLY** — one landing,
   reserved as bus position 4 (P13).
5. ➕ **NEW: add one M4 brass ESD stud tied to logic GND through 1 MΩ** at panel (490, 500), and
   put a wrist strap in the service procedure. A plastic box in a dry, dusty room gives static
   nowhere to go. This is a *bleed* path, not a bond.
6. The F-1019's bare aluminium shell floats. **Do not opportunistically bond it to anything**, and
   keep the F6 / Violet-Grey runs clear of it (they are 400+ mm away by construction).

**EMI, honestly:** a gasketed bonded steel box was worth 40–60 dB and we are giving that up for
0 dB. The remaining aggressors are the two switchers and the G5LE contacts breaking a 24 VAC
inductive contactor coil **with the RC snubbers still DNP**; the victims are the 47 kΩ logic-side
opto pull-ups and the NE555 timing node (~15.5 µA at threshold). Mitigations, all of which the
repo already wants for other reasons: **(a) plan to populate Rsnub 100 Ω + Csnub 10 nF X2 on all
six motion-relay contacts at commissioning** (~$0.50/board, footprinted and DNP today — the
plastic box moves this from optional to expected); **(b)** twist each I²C signal with its own
dedicated GND return over the C7→Pi jumper; **(c)** C8 ≤ 150 mm stays hard.
**Retrofit path only if a pilot soak shows a problem:** adhesive Al/Cu tape or Ni-acrylic paint on
the **inside** of the shell (~$30–50/box), bonded at **exactly one point** to logic ground —
never two, or you recreate the ground loop the plastic box just eliminated. Do not do it
pre-emptively, and do not expect carbon-filled plastics to give more than a few dB.

---

## 5. PLYWOOD PANEL

| | |
|---|---|
| Size | **1100 × 570 mm** |
| Material | **½″ (12.7 mm) BC or better exterior plywood. NOT MDF.** Confirm actual thickness — 15/32″ = 11.9 mm vs ½″ = 12.7 mm changes the standoff-screw engagement. |
| Yield | **4 per 4×8 sheet** (2 × 1100 = 2200 ≤ 2438; 2 × 570 = 1140 ≤ 1219) → **4 sheets for 16 pairs** |
| Finish | Sand 120 grit → **oil-based primer, then 2 coats enamel, BOTH faces and ALL FOUR EDGES.** Edges are where a plywood panel takes on moisture in an oil-mist room. |
| Cut tolerance | ±1 mm on both dimensions; corners square within 1 mm across the diagonals |

### 5.1 Drilling schedule — every hole, x/y from panel top-left

**Precision holes (one jig, used twice).** All eight are **Ø3.4 mm** clearance for M3, drilled
square, from the FRONT, and **countersunk on the REAR** for the M3 × 20 pan head.

| Hole | x | y | Ø | For |
|---|---|---|---|---|
| MK-A1 | 214 | 224 | 3.4 | Board A standoff |
| MK-A2 | 456 | 224 | 3.4 | Board A standoff |
| MK-A3 | 214 | 456 | 3.4 | Board A standoff |
| MK-A4 | 456 | 456 | 3.4 | Board A standoff |
| MK-B1 | 644 | 224 | 3.4 | Board B standoff |
| MK-B2 | 886 | 224 | 3.4 | Board B standoff |
| MK-B3 | 644 | 456 | 3.4 | Board B standoff |
| MK-B4 | 886 | 456 | 3.4 | Board B standoff |

> **Make ONE 242 × 232 four-hole template with a 430 mm indexing stop.** Board A is the first
> impression, board B the second. This is the only precision drilling on the whole panel;
> everything else is wood screws.
>
> **Fastener correction (L-09): use M3 × 20, not M3 × 18.** M3 × 18 into a 12 mm standoff leaves
> only ~4.0 mm of brass engagement (~1.3 × d against the 1.5 × d rule) once the flat + split
> washers are counted. **Add M3 fender washers ≥16 mm OD** on the rear face — the 7 mm OD washer
> is an undersized bearing face on painted plywood.

**Centre supports — Ø3.0 mm pilot, screwed nylon standoff, 12 mm:**

| Hole | x | y | Ø |
|---|---|---|---|
| CS-A1…A3 | 442 | 320 / 355 / 390 | 3.0 |
| CS-B1…B3 | 872 | 320 / 355 / 390 | 3.0 |

**DIN rail mounting — Ø3.0 mm pilot, #8 × ¾″ pan head through the rail slots:**

| Rail | x | y | Ø |
|---|---|---|---|
| R1a | 165 · 270 · 380 | 148 | 3.0 |
| R1b | 740 · 825 | 148 | 3.0 |
| R2 (vertical) | 85 | 258 · 295 | 3.0 |

**Panel-mounted modules — Ø3.0 mm pilot (⚠ both patterns VERIFY on the real part, §8):**

| Module | x | y | Ø |
|---|---|---|---|
| Pi + F-1019 ear slots | 507.8 · 613.3 | 118.8 · 143.8 | 3.0 |
| PoE splitter bracket keyholes | 885 · 985 | 72 · 163 | 3.0 |

**Duct and lacing-channel mounting — Ø3.0 mm pilot:**

| Item | x | y | Count |
|---|---|---|---|
| Lacing channel (1×1) | 100 · 300 · 500 · 700 · 900 · 1040 | 37 | 6 |
| Duct-L1 | 164 | 240 · 350 · 460 | 3 |
| Duct-L2 | 506 | 240 · 350 · 460 | 3 |
| Duct-L3 | 594 | 240 · 350 · 460 | 3 |
| Duct-L4 | 936 | 240 · 350 · 460 | 3 |

**ESD stud — Ø4.5 mm through, M4 brass stud + 1 MΩ to logic GND:** (490, 500).

**Internal fan — Ø3.0 mm × 4, 40 mm fan pattern (32 × 32 mm):** (454, 115) (486, 115)
(454, 147) (486, 147).

**Shell attachment — Ø4.5 mm clearance, countersunk FRONT, #8 × ¾″ into the shell flange,
every 150 mm, 12.5 mm in from the panel edge:**

- Top edge, y = 12.5: x = 62, 212, 362, 512, 662, 812, 962, 1038 (8)
- Bottom edge, y = 557.5: same x values (8)
- Left edge, x = 12.5: y = 62, 212, 362, 512 (4)
- Right edge, x = 1087.5: y = 62, 212, 362, 512 (4)
- **24 holes.** They sit under the shell flange and the gasket line — countersink flush.

**Wall mount — Ø4.5 mm countersunk FRONT, into a French-cleat half on the panel REAR:**
(150, 12.5) (450, 12.5) (750, 12.5) (1050, 12.5) and (150, 557.5) (450, 557.5) (750, 557.5)
(1050, 557.5) — **8 holes, shared with the shell-attachment line where they coincide.**

**Total: 8 × Ø3.4 · ~34 × Ø3.0 · ~25 × Ø4.5.**

### 5.2 How the panel mounts in the box

**Make the plywood the STRUCTURE and the plastic a SHROUD.**

1. Two **900 mm French-cleat halves** (¾″ ply, 45° bevel) glued and screwed to the **rear** of the
   panel at y = 60 and y = 500. The mating halves go on the wall, levelled.
2. The panel hangs on the cleats. **Equipment mass is only ~2.5–3 kg** — 2 boards ~0.4 kg each,
   Pi + F-1019 ~0.18, DDR 0.25, splitter 0.2, rail + blocks 0.4, duct + wire 0.6. ½″ ply spans
   1100 mm under 3 kg with negligible deflection. (The sourcing brief's "8–10 kg mounted weight"
   included the steel box and its subpanel; the audit's "45–50 kg loaded enclosure" is now
   ~12–15 kg all-in.)
3. The PVC shell lands **on the panel's 25 mm perimeter land**, gasket between shell flange and
   painted ply, 24 screws at 150 mm.
4. **Build order matters — boards go on LAST.** Paint both faces and all edges → drill → rails,
   duct bases and lacing channel → DIN modules → F-1019 and splitter → standoffs → land power and
   **trim the DDR to 5.20–5.25 V open-circuit** → duct covers off → **boards last.** You cannot
   reach a standoff screw from behind once its board is on it.

---

## 6. BOM DELTAS

### 6.1 Deleted

| Line | Item | Why | Fleet saving |
|---|---|---|---|
| **E4** | Saginaw SCE-36EL3008LP, $492–649 ea | Custom PVC shroud | **−$7.9k to −$10.4k** |
| **E6** | Backplate mounting nuts/washers for the box's 4 collar studs | No collar studs exist. Also permanently kills the R-11/M-17 unknown of whether Saginaw studs can nut a 12.7 mm panel. | −$32 |
| **C4** | DINrPlate DRP2, 16 × $12.95 | **Mechanically incompatible with C5.** The F-1019 is a complete aluminium Pi carrier with its own DIN brackets; its four brass standoffs consume the same M2.5 Pi holes the DRP2 needs. Buy one or the other. Mode-1 panel mount is 17.5 mm lower and needs no rail. **This also makes BOM check C5(b) moot.** | −$207 |

### 6.2 Changed

| Line | Was | **Now** | Note |
|---|---|---|---|
| **E5** Backplate | ½″ ply **686 × 838**, 3/sheet, **6 sheets** | ½″ ply **1100 × 570**, **4/sheet**, **4 sheets** | Panel area drops 0.575 → 0.627 m² each but yield improves. **Plywood goes DOWN ~$100 fleet, not up** — the earlier write-up had this backwards. |
| **E1** DIN rail | ~600 mm/pair, 5 packs | **~450 mm/pair** (R1a 244 + R1b 108 + R2 52 + offcut), **4 packs** | One rail *row*, three short segments. −$9 |
| **E2** End brackets | 4/pair, 64 | **6/pair, 96** | Three rail segments |
| **E3** Wire duct 1×2 | ~1 m/pair, 8 sticks | **1020 mm/pair, 9 sticks** | ⚠ **Cover is sold separately on most SKUs** — put the cover PN (C1LG6/C1WH6 class) on the PO. Actual outside is **31.75 × 53.8 mm**, not the 25 × 50 nominal. |
| **E7** Glands | ~9 × M20, 144 | **10/pair: 4 × M20 · 5 × M16 · 1 × M25** = 64 M20, 80 M16, 16 M25 (+spares) | **Nylon only, no brass** (§4.5). G9 M25 for the RJ45 (L-05); M16 on the small bundles so the seal forms (L-04). |
| **E8** Breather | optional | **REQUIRED, fitted** | Low self-heating ⇒ higher condensation risk |
| **D5** 5 V return bus | 2 × KN-G10 (PE class) | **4 × insulated feed-through, KN-T/KN-S class + jumper comb** | M-04. Keep one real KN-G10 per box for its actual job (none here — there is no earth). |
| **D7** Isolated 12 V | "≥5 W isolated, ~$15" | **Mean Well DDR-15G-12** — 17.5 × 90 × 54.5, 9–36 Vdc in, 12 V/1.25 A, **4 kVdc**, load range **0–1.25 A** (zero minimum load explicitly allowed) | ~$30–35. Same 90 × 54.5 envelope as the DDR-60G-5 ⇒ **zero new depth**, 17.5 mm of rail. Stop looking. |
| **A5** Standoff screws | M3 × 18 | **M3 × 20** | L-09 — only ~4.0 mm brass engagement at ×18 |
| **A7** Washers | M3 flat + split | **+ M3 fender washers ≥16 mm OD** | L-09 — bearing face on painted ply |
| **A8** Centre support | 1 adhesive/board | **3 SCREWED NYLON standoffs/board** (96 + spares) | L-08 quantity, judge-2 attachment. Adhesive fails on painted ply at 40 °C in oil mist. |
| **C9** Pi power pigtail | USB-C, ~300 mm | **USB-C, ~600 mm** | F4 is at x 256, the Pi's USB-C face at x ~560 |
| **F5** Adhesive tie mounts | ~12/pair, 200 | **~24/pair, 400** | +9 on the gland wall (L-04), +J14 anchors, +riser lane |

### 6.3 New

| # | Item | Spec | Per pair | ×16 | ~$ ea | Note |
|---|---|---|---|---|---|---|
| **E9** | **PVC shell material** | Rigid PVC Type 1: **~1.0 m² @ 6 mm** + **~0.13 m² @ 10 mm** (gland wall) | 1 set | 16 | **$60–90** | Includes lid, 4 walls, flanges, 2 ribs |
| **E10** | **Shell hardware** | 2 × 300 mm SS piano hinge · 8 over-centre draw latches · 3.4 m × 10 × 5 mm EPDM gasket · #8 × ¾″ screws · PVC solvent cement | 1 set | 16 | **$75–90** | |
| **E11** | **Wall mount** (closes L-16) | 2 × 900 mm ¾″ ply French-cleat halves + 4 × ⅜″ lag/anchor per pair | 1 set | 16 | **$12–25** | Mounting surface at each pair **still unsurveyed** |
| **E12** | **Internal circulation fan** | 40 × 40 × 10 mm, **5 V, BALL BEARING**, ~0.7 W | 1 | 16 (+2) | **$5** | Continuous low RPM. **Nothing may depend on it.** |
| **E13** | **Lacing channel duct** | 1×1 in slotted PVC + cover, ~990 mm/pair | 1 | ~16 m → 8 sticks | $12/stick | New band, §1.5 P40 |
| **C10** | **In-box Cat6 patch** (closes L-05) | ~500 mm, splitter LAN → Pi Ethernet | 1 | 16 (+2) | $5 | Was on no BOM line at all |
| **C11** | **Camera video coax** ⚠ **NEW** | 2 × ~1.5 m, terminated to match the USB capture dongle | 2 | 32 (+4) | $6 | **Was in no gland, no duct and no wire-list row.** See §7. |
| **F9** | **Split loom** (L-04) | 10 mm, ~4 m/lane, B1 and B3 in separate looms | ~8 m | ~136 m | ~$1.1/m | Without it the IP68 seal never forms |
| **F10** | **ESD bleed stud** | M4 brass stud + 1 MΩ 1 W resistor to logic 0 V | 1 | 16 | $3 | Plastic box, dry dusty room |
| **F11** | **Rsnub/Csnub** (plan, not order-now) | 100 Ω + 10 nF X2 × 6 per board | 12 | 384 | $0.04 | Footprinted, DNP today. **Populate at commissioning** — the plastic box moves this from optional to expected. |

### 6.4 Cost, per pair, against the Saginaw it replaces

| | Old (Saginaw path) | **New (custom box)** |
|---|---|---|
| Enclosure | **$492–649** (E4) | — |
| Backplate mounting | $2 (E6) | — |
| Plywood panel | $18.75 (0.33 sheet) | **$12.50** (0.25 sheet) |
| PVC shell material | — | **$60–90** (E9) |
| Shell hardware | — | **$75–90** (E10) |
| Wall mount | not in BOM (L-16) | **$12–25** (E11) |
| Fan + ESD stud | — | **$8** (E12/F10) |
| DIN rail + brackets (delta) | — | **−$5** |
| DRP2 | $12.95 (C4) | **−$12.95** |
| **TOTAL** | **$525.70 – 682.70** | **$150 – 217.55** |

> **Saving ≈ $310–465 per pair · ≈ $5.0k–7.4k across 16 pairs**, before counting the deleted
> DRP2s. Against a backplate-scope roll-up of ~$890–1,050/pair, the enclosure drops from **~55 %
> of the backplate cost to ~18 %.** The trade is the owner's own fabrication labour — call it
> 4–6 h per box for cutting, welding, drilling and gasketing, front-loaded on the first one.
>
> Not counted: two 4×8 sheets of plywood saved fleet-wide (−~$100) and the fact that a
> 1112 × 582 × 121 mm box is **56 L against the Saginaw 36×30×8's 141 L** — less than half the
> volume to hang on a wall.

---

## 7. HARNESS IMPACT — ⚠️ READ BEFORE THE RFQ GOES OUT

### 7.1 The in-enclosure routing number moves. It moves in the SAFE direction.

Wire list **Rev 4** cut class **L1 at 3200 mm** from: **1829 mm** measured enclosure-to-machine
run **+ ~750–950 mm of in-enclosure route on the FAR board + ~300 mm** service slack and drip
loop. **`PANEL-W2` has no far board** — the two lanes are mirror-symmetric about x = 550, so both
routes are identical.

Worst-case gland→plug routed paths (120 mm drip loop + 65 mm gland-to-duct + duct rise + lateral
+ 80 mm plug service loop):

| Path | Lane 21 | Lane 22 | Class |
|---|---|---|---|
| Bundle-1 → **J3** (highest field plug) | **522 mm** | 522 mm | L1 |
| Bundle-1 → J15 (lowest) | 342 mm | 342 mm | L1 |
| Bundle-3 → **J6** | **495 mm** | 495 mm | L1 |
| Bundle-3 → J11 | 385 mm | 385 mm | L1 |
| **J14 safety pair** (up the duct into the wire band) — **longest L1-class lead** | **628 mm** | 628 mm | L1 |
| J13 mask/lamp drop | 265 mm | 265 mm | site-measured |
| Sensor pair, Violet/Grey (F6 → down L1 → gland band → gland) | 320 mm | **880 mm** | L2 (3700) |
| Camera pair, Brown/Pink (F5 → lacing channel → duct) | 640 mm | **760 mm** | L3 (4700) |

### 7.2 🔴 VERDICT — **DO NOT RE-CUT REV 4 FOR THE PILOT. DO RE-CUT FOR THE FLEET.**

**Worst-case in-box route is ~630 mm against an assumed 750–950 mm — every L1 lead is
120–320 mm LONGER than it needs to be. No lead comes up short.** That is the safe direction to be
wrong and it is exactly what RFQ §9's own policy ("build long, we trim on site") is for.

But **~300–450 mm of coiled excess on each of 30 L1 leads** is not free: coiled excess inside a
sealed box adds bulk and coupled length in precisely the duct lanes where 342 mm of bundle
separation was just bought.

**ACTION — no re-quote required, the mechanism already exists:**

1. **Issue the RFQ AS WRITTEN at Rev 4 / L1 = 3200 mm.** The pilot must be built long; the site
   survey is still incomplete at most lane pairs and 1829 mm is only measured at one.
2. RFQ §9(b) already asks the vendor to quote **the per-assembly cost delta per ±0.5 m on class
   L1 (30 leads)**. **Use it.** Once the pilot confirms the routed path on a real `PANEL-W2`
   panel, take **fleet L1 to 2700–2800 mm**.
3. **L0 (in-box, 800 mm), L2 (3700) and L3 (4700) are UNAFFECTED.** Do not touch them. In
   particular do not let anyone "optimise" the 800 mm L0 J2 power leads down to match the ~200 mm
   run — build to the wire list.

### 7.3 🔴 ADD TWO LEADS TO THE WIRE LIST BEFORE IT ISSUES

**The camera video path does not exist anywhere in Rev 4.** The wire list carries only W52/W53
(camera 12 V, Brown/Pink, L3). The DIELL deprecation doc states plainly that *"the video path
runs to the capture dongle → Pi USB → logic ground"* — so there are **two composite-video coaxes
per pair** that must enter the box and reach the Pi. Today they are in **no gland, no duct lane
and no wire-list row**, and their natural default (following their own power pair) would land
them in Duct-L2/L4 alongside the relay-switched 24 VAC bundle for ~255 mm. **1 Vpp analogue video
beside inductive contact breaks with the snubbers DNP is the textbook victim/aggressor pairing —
and that shield is also the conductor that defines the camera's ground domain.**

| Lead | Colour | Class | Length | Label | Route |
|---|---|---|---|---|---|
| **W54** | coax, black | L3 | 4700 | `CAMERA A VIDEO` | G10 → right-margin riser → lacing channel → Pi USB dongle |
| **W55** | coax, black | L3 | 4700 | `CAMERA B VIDEO` | same |

⛔ **Standing rule for the drawing and the F7 card: video coax NEVER enters Duct-L2 or Duct-L4.**

### 7.4 Everything else the harness cares about is unchanged

Bundle-1 vs Bundle-3 separation is **342 mm per lane** (rule ≥50), better than Rev 4 assumes.
Gland face is unchanged (bottom, one face). Plug counts, colours, coding and the J14 1–2 jumper
are untouched. The Violet/Grey vs Brown/Pink domain rule is honoured by construction — they ride
different ducts and exit different glands 144 mm apart.

---

## 8. OPEN / VERIFY

### 8.1 🔴 GATES ON CUTTING PLYWOOD — measure these first, they are hours of work

| # | Item | Why it gates | What to do |
|---|---|---|---|
| **1** | ✅ **RESOLVED 2026-07-27 — PoE splitter dimensions, from the manufacturer's own site** | **PoE Texas publishes TWO variants and neither is 244 × 155.** Their site gives **6KV Model 7.6 × 3.3 × 1.6 in (193.0 × 83.8 × 40.6 mm)** and **Indoor Model 6 × 2.6 × 1.4 in (152.4 × 66.0 × 35.6 mm)**. The old 9.6 × 6.1 × 2.25 in figure this document contradicted is neither — almost certainly a **packaged/shipping** dimension, so the ~1200 mm panic panel width is retired. **Both variants are SHORTER than the 115 mm assumed**, so the module band gains slack either way (Indoor frees 59 mm, 6KV frees 41 mm). | ⛔ **THE VARIANT CHOICE IS NOW THE GATE, not the measurement.** **Indoor (152.4 wide):** ends x = 1012.4, leaving **62.6 mm** to the wall land — clears the 45–55 mm a Cat6 plug needs. **FITS AS DRAWN.** **6KV (193.0 wide):** ends x = 1053.0, leaving only **22.0 mm** — **FAILS**, the RJ45 will not seat. If the 6KV is wanted for surge protection, move the splitter ~45 mm inboard (x ≈ 815) and re-check the F1 clearance on its −x face. |
| **2** | ✅ **ORIENTATION HALF RESOLVED 2026-07-27 — the mount is a CHOICE, not a constraint.** The CZH-LABS datasheet lists **three variants of the D-220**: `MD-D220-1` **panel mount** (no carrier), `MD-D220S-1` DIN + simple carrier, `MD-D220T-1` DIN + high-quality carrier — **and the T carrier is removable for PCB screw-mount use.** So the header can be pointed at the boards whichever way we like. **Buy `MD-D220T-1`** — it is a strict superset: rail-mount as drawn, or strip the carrier and screw it to plywood if the header lands the wrong way. | **Still open:** the header's offset within the 87 mm across-rail span. The drawing dimensions the outline only. | **Does NOT gate the plywood outline.** Gates the **R1a rail y-position** (35 mm of adjustment available in the 125 mm band) and the **C8 ribbon length**. ⚠ Do not estimate it from the product photo — that method produced the 150 × 115 splitter figure against a real 152.4 × 66.0. |
| **3** | **F-1019 carrier: outline, flange hole pattern, and heatsink clearance** | Mount method is now settled (carrier flanges, C4 deleted) but the **dimensions are still unmeasured**. Any figure previously in P20 came from a false premise and is void. | **(a) No Pi needed — caliper now:** carrier outline W × H × D, flange hole spacing, hole diameter. **This is what gates the plywood drilling schedule.** **(b) Needs a Pi:** the C3 passive heatsink sits on the SoC in the gap between the Pi's top face and the HAT's underside — roughly a GPIO header's height. **A tall heatsink will foul the HAT.** Confirm it closes; if not, switch to a low-profile heatsink — that is a C3 change, NOT a reason to abandon the carrier. |
| **4** | **Actual plywood thickness** — 15/32″ (11.9) vs ½″ (12.7) | Sets M3 × 20 engagement into the 12 mm standoff and the countersink depth. | Caliper the sheet before drilling. |
| **5** | **KN-F10 fuse-carrier swing radius** | The ~60 mm arc is inferred from the 2D drawing (a separate ~60 mm hinged lid with a pivot pin one end, latch the other). AutomationDirect publishes no service clearance. It sets the lid keep-out in §4.1. | Swing the carrier on the Wave-1 unit and measure the highest swept point off the rail. |

### 8.2 🟠 DECISIONS STILL OPEN THAT WOULD MOVE THIS PANEL

| # | Item | Impact |
|---|---|---|
| **6** | **R-12 — does the unified scoring + control daemon ship before cutover?** | If not, each pair needs a **SECOND Pi + SD + USB-C pigtail + fuse branch**. ⚠️ **There is no free slot for it.** R1a has 29.8 mm free, R1b has 4.6 mm, and the splitter bay is full. A second Pi would need the panel to grow ~130 mm in width or the F1/splitter group to be re-planned. **Resolve before the plywood is drilled.** |
| **7** | **OG-1** — Dylan's formal 250 × 225 → 250 × 240 sign-off | Still recorded **OPEN** and still blocks enclosure fab. The re-check half was resolved 2026-07-20 with evidence; the signature half rides gate G14 and the run-log line is still blank. This drawing inherits that gate. |
| **8** | **G8 / J14 Stop-CIS interface** (~$25/lane) | Its physical form is undecided. If it becomes a DIN module it needs band space that does not exist. Currently assumed to live at the machine, not on this panel. |
| **9** | **F5 / F6 fuse sizing** | Deferred to commissioning until real camera and sensor draw are measured. Does not move the layout. |
| **10** | **R-4 — resize the 1.1 kΩ FIELD_WET_V bleed?** | Thermally irrelevant either way (45 mW → 200 mW per pair, 0.35 % → 1.5 % of box heat). Does not move the layout. |

### 8.3 🟡 BUILD-TIME CHECKS AND STANDING RULES

1. **Beep the C7 continuity map ONCE at first article, per module, before power.** J1 terminal 1 =
   `VCC_5V` and terminal 3 = `I2C_SDA` are **adjacent on the same row** — a single-position slip
   puts 5 V onto the Pi's SDA. Two minutes, once, against a Pi-killer. **Record on the F7 card.**
   ⛔ Standing rule: **never land terminal 1 (`VCC_5V`) or terminal 11 (`VCC_3V3`) on the Pi.**
2. **Trim the DDR-60G-5 to 5.20–5.25 V at its own terminals BEFORE landing any load** (M-03). At
   factory 5.00 V the rail lands 4.39–4.61 V under relay load — below the NE555 4.5 V min, the
   TMA-0505S 4.5 V min, and the daemon's `DEFAULT_V5_MIN_MV = 4500.0`. FA-6 step 3 floor: all six
   coils energised → TP1 ≥ 4.75 V, heartbeat v5n ≥ 4700 mV.
3. **First-article criterion for the USB corridor:** an off-the-shelf micro-B seats with the J1
   ribbon mated, BOOTSEL is reachable, and UF2 flash succeeds **without the hand-shaved
   right-angle cable that rev-B and rev-C both needed.**
4. **Twist each I²C signal with its own dedicated GND return** over the C7→Pi jumper (the D-220
   breaks out enough grounds). This is the real EMI fix for the un-budgeted M-23 segment, and it
   costs nothing.
5. **Inspect both 240-length board edges** at first article for depanel nicks — the y=240 edge
   carries live SLOW_AUX11 copper to 1.28 mm and the y=0 edge carries a VCC_5V via at 1.150 mm.
   G12's visual pass covers **both** edges (L-13), across the full 250 mm span.
6. **Any spare J13/J16 plug kept in the box must be CP-MSTB 1734634 coded and band-marked first.**
   A loose uncoded J13 lamp plug mates J16, lands resistorless LEDs across 5 V and wedges I²C.

### 8.4 The F7 wire-map card — mandatory contents, taped inside the lid

Beyond the per-lane cavity map, the Candidate-C jumper text and the breakout terminal→pin map:

1. **`THE 0 V BUS IS NOT EARTH — NEVER BOND IT.`**
2. **`RAIL R2 / D7 / F6 / VIOLET+GREY = FIELD_GND. Never join to logic 0 V, the camera pair, or
   any chassis. D7's INPUT is logic-referenced — the barrier is inside the module.`**
3. **`VIDEO COAX NEVER ENTERS DUCT-L2 OR DUCT-L4.`**
4. The C7 continuity-check result, **dated and initialled**, for each of the two modules.
5. The DDR-60G-5 trim voltage **as actually set**.
6. The three centre-support positions per board (board-x 232, y 100/135/170).
7. Gland map G1–G10 with panel-x and what each carries.
8. `THIS BOX HAS NO PROTECTIVE EARTH. Max internal: 57 V DC SELV, 24 VAC dry contacts.
   Wear the wrist strap on the ESD stud at (490, 500).`

---

## Appendix — quick numbers for the shop wall

```
PANEL          1100 × 570 × 12.7 mm ½" ply, 4/sheet, 4 sheets fleet
BOX INTERNAL   1100 × 570 × 115 mm clear · 6 mm PVC Type 1 (10 mm gland wall) · UL 94 V-0 · NO VENTS
BOARDS         A: x 210–460  B: x 640–890   both y 220–460   both rotation 0°
MK JIG         242 × 232, index +430 mm     8 × Ø3.4, M3 × 20 + ≥16 mm OD fender washers
RIBBONS        C8 ~125 mm routed, both boards, zero lateral   (cap 150)
I²C PATH       ~260 mm per board, 2 screw-terminal transitions (was ~750 / 4)
J2 DROP        2.0 mV — 5 V run length is FREE, never optimise for it
SEPARATION     Bundle-1 ↔ Bundle-3 = 342 mm per lane (rule 50)
CORRIDOR       56 mm, covers MUST be fitted — the one tight number
DOMAINS        F5 ↔ F6 = 240 mm, separate rails, DDR between them
GLANDS         10, bottom face: 4×M20 · 5×M16 · 1×M25(Cat6) · nylon only
DEPTH          62 mm static, 110 mm fuse-carrier swing, 115 mm clear
THERMAL        13 W avg / 21 W peak → +2.7 K / +4.4 K → 38–40 °C internal at 35 °C ambient
PI             top cover OFF + <8.5 mm heatsink + 40 mm ball-bearing fan · ≤70 °C sustained
HARNESS        in-box worst case 630 mm vs 750–950 assumed → leads are LONG, not short
```

**Written 2026-07-26. Supersedes Layout D for the fleet article. Inherits gate OG-1.**





