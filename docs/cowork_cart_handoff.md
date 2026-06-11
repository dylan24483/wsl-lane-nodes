# Cart-building handoff — Phase 8 rev-B parts (for Claude Cowork)

You previously built a **DigiKey** cart for this BOM. Three things remain: **(1)** prune 5 lines from that DigiKey cart, **(2)** build a small **Mouser** cart (3 parts), **(3)** build an **Amazon** cart (Pi hosts + consumables). 

## GLOBAL RULES (read first)
- **Do NOT check out / place any order.** Leave all three as saved or guest carts for the human to review.
- **Order connectors + PSUs by MANUFACTURER part number**, not DigiKey/Mouser internal numbers — the distributor `-ND`/internal numbers proved unreliable on this BOM. Verify each line resolves to the exact MFR PN, pole count, and pitch before adding.
- **Never substitute.** If a part is out of stock, discontinued, or unavailable, **flag it for the human — do not swap in a different part, SKU, or pitch.**
- **Phoenix pitch trap:** every Phoenix header/plug here is **3.5 mm**. Phoenix sells visually-identical **3.81 mm** parts — reject any "similar item" that is 3.81 mm.
- At the end, report each cart: line items, quantities, running total, and anything that wouldn't add.

---

## CART 1 — DigiKey (EDIT the existing cart): remove these 5 lines, keep the rest
Delete exactly these (find by DigiKey PN):

| Delete | DigiKey PN | MFR PN | Qty | Why |
|---|---|---|---|---|
| 27 W USB-C PSU | 2648-SC1153-ND | SC1153 | 2 | wrong PSU — host is a Pi **4**, not Pi 5 |
| Active Cooler | 2648-SC1148-ND | SC1148 | 2 | Pi-5-only accessory |
| Mean Well PSU | 1866-2246-ND | HDR-30-5 | 2 | **backordered** — re-ordering at Mouser (Cart 2) |
| 10-pos header (J3) | 277-5774-ND | 1843680 | 5 | **backordered** — re-ordering at Mouser (Cart 2) |
| 12-pos header (J5) | 277-5812-ND | 1843703 | 5 | **backordered** — re-ordering at Mouser (Cart 2) |

- **Do NOT add** the Raspberry Pi 5 (SC1111 / SC1431) — it's ~$110, 0 stock, 34-week lead. The host is a Pi 4 from Amazon (Cart 3).
- The **Raspberry Pi Pico (2648-SC0915CT-ND, SC0915) already in the cart at qty 5 is correct — leave it.**
- After deleting the 5 lines above, the DigiKey cart should have **15 line items remaining.** Sanity-check that the discontinued **14-pos plug `1840489` (277-5958-ND, qty 5)** is still present and in stock — that one is last-time-buy and must not be dropped.
- Do not check out.

---

## CART 2 — Mouser (NEW cart): add these 3, BY MFR PN
| MFR PN | Description | Qty | Notes |
|---|---|---|---|
| **1843680** | Phoenix Contact MCV 1,5/10-G-3,5 — 10-pos PCB header, **3.5 mm** | 5 | NOT the 3.81 mm version |
| **1843703** | Phoenix Contact MCV 1,5/12-G-3,5 — 12-pos PCB header, **3.5 mm** | 5 | NOT the 3.81 mm version |
| **HDR-30-5** | Mean Well DIN-rail PSU, 5 V / 3 A / 15 W | 2 | if Mouser shows backordered, use **TRC Electronics** (trcelectronics.com — confirmed in stock, same-day) |

Confirm each resolves to the exact MFR PN + correct pole count + 3.5 mm pitch before adding. Do not check out.

---

## CART 3 — Amazon (NEW cart): add these
**Raspberry Pi 4 hosts (the host SBCs — kit bundles PSU + fan + microSD):**
| Item | ASIN | Qty |
|---|---|---|
| CanaKit Raspberry Pi 4 **4 GB** Starter PRO kit | B07V5JTMV9 | 2 |

**Consumables + bench tools:**
| Item | ASIN (or search) | Qty |
|---|---|---|
| TUOFENG 20 AWG silicone hookup wire, 6-color | B07G2GLKMP | 1 |
| IWISS HSC8 6-4 ferrule crimper + 1200-pc ferrule kit | B0DDT8GHVY | 1 |
| M3 brass standoff/screw/nut kit (~180 pc) | B075K3QBMX | 1 |
| USB-A → Micro-USB **data** cable, 3-pack | B072J1BSV6 | 1 |
| 12 V incandescent test light (relay dummy load) | B003UHNMMS | 1 |
| Alligator-clip test leads + dupont jumper wires | *search* | 1 |
| 40-pin Raspberry Pi GPIO breakout board + ribbon | *search* | 2 |
| Solder + flux pen + desolder braid + tip cleaner kit | *search* | 1 |
| ESD wrist strap + mat | *search* | 1 |
| Label / marker tape | *search* | 1 |
| *(optional)* 0–30 V / 5 A adjustable bench DC power supply | *search* | 1 |

For the *search* rows, pick a reasonable in-stock listing and report the ASIN + price you chose. Do not check out.

---

## ⛔ Never add (already on the assembled JLC PCBA boards — re-ordering is wasted)
If any of these appear in a cart auto-fill, delete them: 32× PC817 optocouplers, 6× G5LE-14 5VDC relays, 3× MCP23017, 1× NE555, all MMBT3904 / 2N7002 / AO3400A / AO3401A transistors, all 1N4148WS / SS14 diodes, and all 0805 passives. Also never buy the DNP parts: the M1 channel (K7, Q7, J12, R85–R87, D13) or any snubber/MOV (C4–C10, D2/D4/D6/D8/D10/D12/D14, R69–R84).
