# WSL Phase 8 rev-B — Harness & Connector Parts (Bench + Production)

**Why this exists:** the board-side connectors are on the assembly BOM, but the **mating
side was never captured** — the J1↔Pi harness and the field-connector plugs. This bit us at
bench bring-up (no J1 socket). This doc is the missing connector/harness BOM, split into what
you need **now (bench)** vs **per-lane (production)**.

Board-side reference (already installed): J1 = 2×10 IDC box header (Pi interface); J2 + J6–J11
= Phoenix MKDS fixed screw blocks (wire-direct, no plug); J3/J4/J5/J13/J14 = Phoenix MCV
vertical headers (need MC-ST plugs). Source-of-truth: `docs/manual_src/11_connector-pinouts.md` §11.

---

## A. Bench bring-up — to finish board #1 (qty = 1 board)

The only hard purchase is the J1 harness. Everything else can be jumper wire you already have.

| # | Item | Purpose | Part / source | Qty | Notes |
|---|------|---------|---------------|-----|-------|
| A1 | **F/F 20-pos 2.54 mm IDC ribbon (socket-to-socket)** | Mate J1 + break out to Pi | DigiKey [Socket-to-Socket IDC Cable Assemblies](https://www.digikey.com/catalog/en/partgroup/socket-to-socket-idc-cable-assemblies/48643) → Positions = 20 (Assmann WSW / 3M / CNC Tech); **overnight** | 1 | **The one thing you must buy.** Cut in half, strip conductors 2/3/4 (GND/SDA/SCL). |
| A1-alt | 20-pin IDC socket "FC-20" + your ribbon | same | CNC Tech `3030-20-0103-00` (socket) + 1.27 mm 20-way ribbon | 1 | Only if you'd rather crimp than buy pre-made. |
| A2 | F-F Dupont jumper wires | Land ribbon conductors on Pi GPIO | generic | ~10 | **Likely on hand.** |
| A3 | Hookup wire / 2 jumpers | **Close J14 safety loop** so the relay rail can enable (Step 3) | generic | — | Bench: jumper **J14 pin1↔pin2** and **pin3↔pin4**. No plug needed for bench. |
| A4 | Hookup wire | Simulate field inputs (Step 4): tap an input pin to FIELD_GND | generic | — | Bench-only; real wiring is production. |

**On hand already (no purchase):** bench PSU, DMM, Raspberry Pi 4, the (improvised) Pico flash
cable, ferrule kit, solder.

---

## B. Production — per-lane harness & field plugs

Each **Pi drives 2 boards** (a lane pair: lane-21 + lane-22). 16 Pis → **32 boards**.

### B-1. J1 ↔ Pi interface (panel-grade) — per board (×32), Pi side per Pi (×16)
| # | Item | Part / source | Qty | Notes |
|---|------|---------------|-----|-------|
| B1 | **DIN-rail 2×10 IDC → screw-terminal breakout** | [Winford BRK2x10-DIN](https://www.winford.com/products/brk2x10.php) (ships direct/fast) — or Sysly/Molence IDC20 (Amazon, long lead) | ×32 | Board side; labeled screw terminals. |
| B2 | F/F 20-pos 2.54 mm IDC ribbon | same as A1 | ×32 | J1 → breakout. |
| B3 | Pi GPIO screw-terminal breakout (optional) | "Raspberry Pi GPIO terminal block HAT/board" | ×16 | Pi side, for all-screw-terminal panels. Otherwise wire to GPIO directly. |
| B1-alt | J1 mating IDC ribbon socket (no DIN board) | CNC Tech `3030-20-0102-00` *(candidate — verify keying)* | ×32 | If you skip the DIN breakout. |

### B-2. Field-connector mating plugs (Phoenix MC 1,5/N-ST-3,5) — per board (×32 each)
These land the machine/field wiring, then plug onto the board headers. **These were the other BOM gap.**
| Board header | Pins | Mating plug | Phoenix PN | Qty |
|---|---|---|---|---|
| **J3** FAST A | 10 | MC 1,5/10-ST-3,5 | **1840447** | ×32 |
| **J4** SLOW A | 14 | MC 1,5/14-ST-3,5 | **1840489** | ×32 |
| **J5** SLOW B | 12 | MC 1,5/12-ST-3,5 | **1840463** | ×32 |
| **J13** LED LAMPS | 6 | MC 1,5/6-ST-3,5 | **1840405** | ×32 |
| **J14** SAFETY | 4 | MC 1,5/4-ST-3,5 | **1840382** | ×32 |

> Phoenix MC plugs are stock at **DigiKey / Mouser** (overnight). Order 1 of each now as bench
> samples if you want to test inputs/lamps/safety with real plugs instead of jumpers.

### B-3. Wire-direct connectors (no plug — wires land in the fixed screw block)
| Board header | Pins | Need |
|---|---|---|
| **J2** 5 V IN | 3 | Field 5 V supply wiring + ferrules (have ferrule kit) |
| **J6–J11** MOTION OUT | 2 ea | Machine relay-output wiring + ferrules |

### B-4. Mounting / panel (note, not specced here)
DIN rail, board standoffs/enclosure, per-board 5 V supply — part of the panel BOM, out of scope of this connector list.

---

## Order-now vs order-later
- **Now (bench, board #1):** **A1** (the F/F ribbon) — overnight from DigiKey/Mouser. That's it to reach `i2cdetect`.
- **Soon (bench convenience):** 1× each MC-ST plug (B-2) if you'd rather use plugs than jumpers for the input/safety tests.
- **Production (no rush — panel build):** B-1 ×32, B-2 ×32 each, B-3 wiring. DIN breakouts via Winford-direct (fast) or Amazon (2–3 wk, fine for panel timeline).

## Related (design, not parts) — rev-C fixes surfaced this session
Break SWD out to a 3-pin header · give the Pico USB end clearance from J1 · add the J1 mating socket to the assembly BOM · consider a min-load/bleed resistor on `FIELD_WET_V`. *(Tracked here so they aren't lost; not a parts purchase.)*
