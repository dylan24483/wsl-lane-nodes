# Phase 8 rev-B — Pre-Arrival Parts Order

**What this is:** everything to BUY now so you can build + bench-bring-up the rev-B lane-controller boards the moment the JLCPCB Standard-PCBA boxes land. Scope = **1 lane pair (2 boards on one Pi) + 1 hot spare = 3 boards**, with sensible spares.

**Status / accuracy:** compiled 2026-06-06 from the fab package's hand-solder / mating-plug / off-board CSVs, web-verified by a 7-agent pass + a completeness critic. **DigiKey/Mouser block automated price scraping, so unit prices are 2026 estimates — confirm exact $ and live stock in the cart.** Part *identities* (MFR PNs) are high-confidence.

> ⚠️ **Order by the manufacturer part number.** The verification agents disagreed on several DigiKey `-ND` numbers, so only the hard-verified ones are listed; for the rest, paste the **MFR PN** into DigiKey/Mouser and let it resolve. The MFR PNs are repo-confirmed and consistent.

---

## 0. Order these FIRST (long-lead / volatile)
1. **All Phoenix Contact connectors in one order** — they show "ships today" but Phoenix historically swings 8–20 weeks. This family gates the whole build.
2. **J4 mating plug `MC 1,5/14-ST-3,5` (1840489)** — flagged **last-time-buy / "will not be replenished."** Buy all 5 now; verify stock first. No same-pitch drop-in substitute.
3. **TRACO `TMA 0505S` (U37)** — only ~10 in DigiKey ship-ready stock at last check. Exact part, no substitute.
4. **Host Raspberry Pi** — RAM-driven pricing is volatile (the 8 GB Pi 5 spiked $80→$175 in the Apr-2026 DRAM crunch). **First check the Phase-8a bench Pi inventory — you may already own these.**

## 1. ⛔ DO NOT ORDER (already in the JLC box, or DNP)
**Already placed by JLC Standard-PCBA — re-ordering is wasted money. If any appear in a cart, delete them:**
32× PC817B (C5692981) · 6× G5LE-14 **5VDC** (C116963) · 3× MCP23017-E/SO (C47023) · 1× NE555DR (C7593) · 8× MMBT3904 · 4× 2N7002 · 2× AO3400A · 1× AO3401A · 8× 1N4148WS · 1× SS14 · **all** 0805 passives.
**DNP (deliberately unpopulated — don't buy):** the M1 channel (K7, Q7, J12, R85–R87, D13) and all motion-output snubbers/MOVs (C4–C10, D2/D4/D6/D8/D10/D12/D14, R69–R84).

## 2. 🚧 Build-blocker to resolve BEFORE you wire it: the J1 ↔ Pi cable
J1 on the board is a **2×10 (20-pin)** header; the Raspberry Pi GPIO is **2×40 (40-pin)**, and the J1 signals land on **scattered** Pi pins (e.g. I²C on Pi pins 3/5, UART on 8/10, but **GPIO12 = Pi pin 32, GPIO26 = Pi pin 37**). **A straight 2×10 ribbon will NOT work** — this is a **custom point-to-point harness** built from the J1 pinout (manual §11) ↔ the Pi-GPIO map (`phase8_pi_provisioning.md` §3). Easiest bench approach: a **40-pin Pi GPIO breakout** (ribbon → screw/header breakout) + jumpers, so each J1 signal lands on the right Pi pin. Parts for it are in §4 (DigiKey J1 set + Amazon breakout). **Confirm the J1↔Pi map before crimping anything.**

---

## 3. Confirm ON-HAND before ordering (don't double-buy)
| Item | Why | If missing |
|---|---|---|
| Multimeter (continuity + DC V) | every §12.9 pass criterion is a meter reading | buy any DMM |
| Solder + flux pen + desolder braid + tip cleaner | ~42 THT connector joints + 2 modules per board, ×3 | add a solder kit (~$25) |
| Bench DC supply (0–30 V / adjustable) | sources the 12 V dummy load + can wet inputs | add ~$55 unit (BENCH-3) or use the 12 V supply you have |
| USB microSD reader + an imaging host | the host-Pi SD cards ship blank | add a $8 USB reader |
| **Phase-8a bench Raspberry Pi(s)** | one Pi drives the whole pair | **likely already owned — check before buying §5 host** |
| VIXLW capture dongle / T-Camera | scoring path (Track A) | noted as already owned |
| ESD wrist strap / mat | A1 + U37 are ESD-sensitive | add a $8 strap |

---

## 4. DigiKey order — board build (modules, connectors, plugs, J1, power)
Qty = **for 3 boards + spares**. Prices = 2026 est, confirm at cart. `crit` = on the bench bring-up critical path / exact-part.

### 4a. Modules (hand-soldered, exact-part-no-sub)
| Ref | Part | MFR PN | DigiKey PN | Qty | ~Unit | ~Ext | crit |
|---|---|---|---|---:|---:|---:|:--:|
| A1 | Raspberry Pi **Pico** (castellated, **NO** headers; **not** H/W/WH) | SC0915 | 2648-SC0915CT-ND | 5 | $4.00 | $20 | ✅ |
| U37 | TRACO **TMA 0505S** iso 5→5 V 1 W SIP-7 (exact, no sub) | TMA 0505S | 1951-1003-ND | 5 | $4.62 | $23 | ✅ |

### 4b. Board-side Phoenix connectors (hand-soldered) — **order by MFR PN**
| Ref | Part (pitch) | MFR PN | DigiKey PN | Qty | ~Unit | ~Ext | crit |
|---|---|---|---|---:|---:|---:|:--:|
| J2 | MKDS 1,5/3-5,08 screw term, 3-pos (**5.08 mm**) | 1715734 | 277-1264-ND ✓ | 5 | $2.25 | $11 | ✅ |
| J6–J11 | MKDS 1,5/2-5,08 screw term, 2-pos (**5.08 mm**) ×6/bd | 1715721 | 277-1263-ND ✓ (LCSC C5183929) | 24 | $1.34 | $32 | ✅ |
| J3 | MCV 1,5/10-G-3,5 header, 10-pos (**3.5 mm**) | 1843680 | 277-5774-ND ✓ | 5 | $2.00 | $10 | ✅ |
| J4 | MCV 1,5/14-G-3,5 header, 14-pos (3.5 mm) | 1843729 | *by MFR PN* | 5 | $2.60 | $13 | ✅ |
| J5 | MCV 1,5/12-G-3,5 header, 12-pos (3.5 mm) | 1843703 | *by MFR PN* | 5 | $2.35 | $12 | ✅ |
| J13 | MCV 1,5/6-G-3,5 header, 6-pos (3.5 mm) | 1843648 | *by MFR PN* | 5 | $1.50 | $8 | ✅ |
| J14 | MCV 1,5/4-G-3,5 header, 4-pos (3.5 mm) — **safety loop** | 1843622 | *by MFR PN* (LCSC C480549) | 5 | $1.25 | $6 | ✅ |

> **Pitch trap:** every MKDS is **5.08 mm**, every MCV is **3.5 mm**. Phoenix sells identical-looking **3.81 mm** variants — order the exact MFR PN and refuse any "similar item" pitch substitution.

### 4c. Off-board mating plugs (field harness; bench can use clip leads) — **order by MFR PN**
| For | Part | MFR PN | Qty | ~Unit (est, varies by source) | ~Ext | crit |
|---|---|---|---:|---:|---:|:--:|
| J3 | MC 1,5/10-ST-3,5 screw plug | 1840447 | 4 | ~$11 | ~$44 | |
| J4 | MC 1,5/14-ST-3,5 screw plug **(last-time-buy!)** | 1840489 | 5 | ~$13 | ~$65 | ✅ |
| J5 | MC 1,5/12-ST-3,5 screw plug | 1840463 | 4 | ~$12 | ~$48 | |
| J13 | MC 1,5/6-ST-3,5 screw plug | 1840405 | 4 | ~$8 | ~$32 | |
| J14 | MC 1,5/4-ST-3,5 screw plug — **safety** | 1840382 | 4 | ~$6 | ~$24 | ✅ |

> Plug prices vary a lot by source/qty (~$3–14). These are upper-ish web estimates — **confirm at cart.** J2 + J6–J11 are screw terminals with **no** plug (wire lands directly).

### 4d. J1 Pi-link set (see the §2 build-blocker)
| Item | MFR PN | DigiKey PN | Qty | ~Unit | ~Ext |
|---|---|---|---:|---:|---:|
| J1 board-side 2×10 2.54 mm box header (**candidate — fit-check 1st**) | CNC Tech 3020-20-0100-00 | 1175-1612-ND | 5 | $0.93 | $5 |
| 2×10 2.54 mm IDC ribbon socket (board end) | CNC Tech 3030-20-0102-00 | (verify at cart) | 10 | $0.61 | $6 |
| 20-cond 1.27 mm ribbon cable, ~1 m roll | (generic) | — | 1 | ~$10 | $10 |

### 4e. Power (board 5 V rail — **separate** from the Pi's own supply)
| Item | MFR PN | DigiKey PN | Qty | ~Unit | ~Ext | crit |
|---|---|---|---:|---:|---:|:--:|
| DIN 5 V/3 A PSU — **pair** supply (feeds both boards' J2) | Mean Well HDR-30-5 | 1866-3554-ND | 2 | $18.69 | $37 | ✅ |
| DIN 5 V/2.4 A PSU — single-board / bench | Mean Well HDR-15-5 | 1866-3548-ND | 1 | $15.40 | $15 | ✅ |

> Board 5 V load (one board, worst case) ≈ **0.7–0.9 A** (6× G5LE coils @ ~79 mA = 0.47 A + TMA-0505S + logic). HDR-30-5 (3 A) covers a pair with margin. **Trim the PSU up ~0.2–0.3 V** so VCC_5V lands 4.7–4.8 V after the SS14 (D17) drop under full relay load.

### 5. DigiKey — host (PER PAIR; **verify you don't already have 8a Pis first**)
| Item | MFR PN | DigiKey PN | Qty | ~Unit | ~Ext |
|---|---|---|---:|---:|---:|
| Raspberry Pi **5 / 4 GB** (≥2 UARTs + 2 I²C for the pair + camera) | SC1111 | 2648-SC1111CT-ND | 2 | $60 | $120 |
| Pi 5 27 W USB-C PD supply (the Pi's **own** power) | SC1153 | 2648-SC1153-ND | 2 | $12 | $24 |
| microSD A2/V30 32 GB (1 live + 1 cloned spare + 1 blank) | SC1628 | 2648-SC1628-ND | 3 | $15 | $46 |
| Pi 5 Active Cooler | SC1148 | 2648-SC1148-ND | 2 | $5 | $10 |

> **Avoid the 8 GB Pi 5 (SC1112, ~$175 right now).** 4 GB is ample for control + scoring. Budget fallback: Pi 4B/4 GB (SC0194) + its 15.3 W USB-C supply.

---

## 6. Amazon / consumables + bench support
| Item | Example PN / ASIN | Qty | ~Unit |
|---|---|---:|---:|
| 20 AWG silicone stranded hookup wire, 6-color kit | TUOFENG B07G2GLKMP | 1 | $17 |
| **Ferrule crimper + 1200-pc ferrule kit (0.5–1.5 mm² covered)** | IWISS HSC8 6-4 B0DDT8GHVY | 1 | $29 |
| M3 brass standoff + screw + nut kit (~180 pc) | Sutemribor B075K3QBMX | 1 | $16 |
| USB-A → **Micro-USB** data cable, 3-pack (Pico flash) | Amazon Basics B072J1BSV6 | 1 | $9 |
| 12 V incandescent test light (relay dry-contact dummy load) | B003UHNMMS | 1 | $9 |
| Alligator-clip test leads + dupont jumpers (TP probing, J14 jumper) | generic | 1 | $10 |
| **40-pin Pi GPIO breakout + ribbon** (for the J1↔Pi custom harness, §2) | generic "GPIO screw-terminal breakout" | 2 | $10 |
| **Solder + flux pen + desolder braid + tip cleaner** *(if not on hand)* | generic kit | 1 | $25 |
| **ESD wrist strap + mat** | generic | 1 | $8 |
| USB microSD card reader *(if not on hand)* | generic | 1 | $8 |
| Label/marker tape (harness tagging for cutover) | generic | 1 | $8 |
| *(optional)* 0–30 V / 5 A adjustable bench DC supply *(if not on hand)* | Korad/Wanptek KA3005D-class | 1 | $55 |

---

## 7. Cost roll-up (estimates — confirm at cart)
| Group | ~Subtotal |
|---|---:|
| DigiKey 4a–4d — modules + connectors + plugs + J1 (the board build) | **~$340** |
| DigiKey 4e — board power (PSUs) | ~$52 |
| DigiKey §5 — host Pi + accessories *(skip if 8a Pis on hand)* | ~$200 |
| Amazon §6 — consumables + bench tools (incl. critic adds) | ~$130 |
| **GRAND TOTAL (everything new)** | **~$720** |
| **If host Pi + bench tools already owned** | **~$420** |

The **mating plugs (~$210) and the host Pi (~$200)** dominate and carry the most price/availability uncertainty — verify both at order time. The plugs are field-harness parts (bench bring-up can use clip leads), so they're the one group you *could* defer a few days if a Phoenix lead-time forces a split order — **except J4's 1840489, which must be bought now (last-time-buy).**

---
*A flat, cart-importable version of this list is in `phase8_revB_preorder_parts.csv` (Supplier · MFR PN · DigiKey PN · Qty · est price). Source of truth for quantities: the fab package `hand-solder-bom.csv` / `harness-mating-parts.csv` / `offboard-hardware.csv`.*
