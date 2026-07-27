# JLCPCB consigned-parts runbook — rev-D board order

**Written 2026-07-27.** First time using consignment, so this is written to be followed
literally. Sources: JLCPCB's own help article *How to consign parts to JLCPCB*, plus Dorae's
email reply of 2026-07-27 confirming the mixing rule.

> **⚠️ CONSIGNMENT MAY NOT BE NEEDED.** It is the fallback, not the plan. Work §1 first — if the
> Global Sourcing quote comes back near catalogue price with an acceptable lead time, **let JLC
> buy** and stop reading. Consignment costs freight, customs paperwork, and JLC's quality-liability
> disclaimer. Only take it if Global Sourcing is slow or overpriced.

---

## 0. Why this exists

Five parts are needed that JLC's library cannot currently fill:

| Ref | Manufacturer PN | JLC # | Need | JLC stock | Distributor stock |
|---|---|---|---|---|---|
| J3, J15 | Phoenix **1843680** | C3585531 | 72 | 0 | **Mouser 722** · DK 52 |
| J4 | Phoenix **1843729** | C3582595 | 38 | 0 | DK listed, count unconfirmed |
| J5 | Phoenix **1843703** | C3019636 | 38 | 3 | **DK 2,139** |
| J1 | CNC Tech **3020-20-0100-00** | C17373551 | 38 | 0 | **DK 2,958** |
| U45 | TRACO **TMA 0505S** | *(none)* | 38 | — | **DK 5,964** |

**All five are the exact required MPNs** — JLC proposed no substitutes and none are acceptable.
J13/J16 (Phoenix 1843648, C5443576, 503 in stock) is **not** on this list — JLC supplies it.

---

## 1. DECIDE FIRST — do not skip

| # | Gate | Action |
|---|---|---|
| 1.1 | **Send the reply to JLC** requesting the Global Sourcing quote, firm lead times, the C3585531 price re-check and the C3582595 wave-solder confirmation. | This starts the clock. Do it first. |
| 1.2 | **Start the TMA 0505S consignment declaration the same day** (§3.2). It is the only part with no JLC library entry, so it needs review + email approval — the long pole. Declaring is free and commits you to nothing. | Parallel, not sequential. |
| 1.3 | **Do NOT buy parts yet.** Wait for the quote. | Mouser holds 722 of the tightest line against a need of 72 — 10× headroom, safe for a few days. |
| 1.4 | When the quote lands, choose: **Global Sourcing** (JLC buys, no freight, no customs, no liability gap) or **consignment** (you control the parts, you eat the logistics). | If GS lead time > ~3 weeks or the $11.31 on C3585531 stands, consign. |

**Reference economics:** parts ≈ **$925**. JLC quoted C3585531 at **$11.31 × 72 = $814** against
Mouser's ~$5.02 → **~$361**. The saving on that one line (~$450) exceeds the entire consignment
overhead, so a bad GS quote makes consignment obviously correct.

---

## 2. Buy (only after §1.4 says consign)

- **Buy from shelf stock. Never backorder.** Both 1843680 and the TMA 0505S carry a **12-week
  manufacturer lead time** beyond stock. A backorder puts the boards behind the harness and
  destroys the ~9 weeks of slack you currently have.
- ⛔ **Do not construct distributor URLs to check a part.** During verification a guessed DigiKey
  detail link returned **1830680** — an 11-position **3.81 mm** part, 0 stock — instead of the
  intended 1843703. Wrong pole count, wrong pitch, and fatal if trusted. **Search by MPN.**
- Keep every packing slip and invoice. You need declared values for customs (§4).

### Quantities to buy

| Part | Installed | Buy | Margin |
|---|---|---|---|
| 1843680 | 68 (2 × 34) | **72** | 4 |
| 1843729 | 34 | **38** | 4 |
| 1843703 | 34 | **38** | 4 |
| 3020-20-0100-00 | 34 | **38** | 4 |
| TMA 0505S | 34 | **38** | 4 |

⚠️ **Those margins may not be enough — see §3.3 attrition.** Confirm JLC's requirement before
buying, or you will be short after the parts are already in China.

---

## 3. Declare in Parts Manager

### 3.1 The four parts already in JLC's library

`Parts Manager → Consign Parts → search by Manufacturer Part Number + Package`

They will match on C3585531 / C3582595 / C3019636 / C17373551. Declare the quantity you are
sending. No approval step needed for these.

### 3.2 ⛔ The TRACO TMA 0505S — the one that gates the schedule

Not in JLC's library, so it takes the **"Or Consign the part directly"** path.

> **JLC's review and email approval is required BEFORE you are authorised to ship.**

This is the step people trip over. Submit it **first**, before the connectors and before you buy
anything. Have the datasheet ready: TRACO **TMA 0505S**, 1 W isolated DC/DC, 5 V in / 5 V out
200 mA, **1 kV isolation**, 6-SIP through-hole module, 0.77 × 0.24 × 0.40 in.

⛔ **Substitution is forbidden on this part** — the part lock reads *"no substitution without
pinout and isolation review."* It is the sole source of `FIELD_WET_V` and the whole opto front
end depends on its isolation. If JLC proposes an alternative, refuse.

### 3.3 Attrition — ask, do not assume

JLC's guide says to *"consider the minimum required quantity and attrition quantity during
assembly process"* but publishes **no number**.

**Ask them to state the attrition requirement per line before you buy.** Your current ~10 %
margin (4 spare per line) is probably fine for hand-placed through-hole parts, but if they want
more you will be short — and being short after the parcel has cleared Chinese customs is the
worst place to discover it.

---

## 4. Ship

- Only after §3.2 approval is in hand for the TRACO.
- International shipment needs a **commercial invoice** and marked package information.
- Supply JLC the **tracking number** and contact details.
- Declare honestly. Under-declaring risks the parcel; over-declaring costs duty.
- ⚠️ **Fees are unconfirmed.** ~$45 for a customs service has been quoted secondhand but is **not**
  in JLC's own documentation. Get the fee schedule in writing before shipping — it is one of the
  questions in the reply email.

On arrival JLC audits, tags and stores the parts; they then appear under **Consigned Parts** in
My Parts Lib. **Confirm they appear before releasing the board order.**

---

## 5. Rules that stay in force

| Rule | Why |
|---|---|
| ⛔ **NO SUBSTITUTIONS, restated per line on the order** | Zero stock on a 2-per-board connector is exactly where a CM proposes a "dimensionally similar" swap at build time. A substituted MCV re-opens FR-2/FR-9, forces a board re-route, and invalidates the five mating plugs, the CP-MSTB coding scheme and 185 vendor-fitted harness plugs. |
| **Cannot mix JLC and consigned stock for the SAME part** | Confirmed by JLC 2026-07-27. Different parts on one order is fine — which is exactly what we need, since J13/J16 comes from their library while these five are consigned. |
| **JLC disclaims quality liability on consigned parts** | Acceptable for passive connectors and a sealed DC/DC module. Note it; do not consign anything where incoming inspection matters. |

---

## 6. Abort points

Stop and re-think if any of these happen:

1. **JLC asks to substitute any of the five.** Refuse — see §5.
2. **TRACO approval is refused or slow.** Fall back to hand-soldering U45 only (34 joints — it is
   a 4-lead SIP, trivial) and consign the four connectors. Do not let one part hold the parcel.
3. **Attrition demand exceeds what you bought.** Buy the difference before shipping, not after.
4. **Global Sourcing comes back good while consignment is mid-flight.** Take it. Unshipped parts
   are returnable to DigiKey/Mouser; unopened stock is a routine return.
5. **The harness quote lands and the boards are no longer the long pole.** Re-check whether the
   consignment round trip is still worth ~40 hours of hand-soldering avoided.

---

## 7. What this does NOT cover

The **Raspberry Pi Pico (A1)** is not consigned — it is in JLC's library as **C7203002**, pending
their confirmation that it is order code **SC0915/SC0916 (bare module)** and **not SC0917
(Pico H)**, which has pre-soldered headers and cannot be reflow-mounted. That question is in the
reply email. **Do not release the order until it is answered in writing.**
