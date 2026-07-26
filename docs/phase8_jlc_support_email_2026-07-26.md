# JLCPCB support enquiry — draft, 2026-07-26

**Send to:** JLCPCB support (support@jlcpcb.com) or the in-account ticket form.
**Why these four together:** Q1 gates the whole assembly plan, Q2 is a fleet-wide wrong-part
risk, Q3 is a physical-damage risk, Q4 unlocks the rest. One ticket, four numbered questions —
support answers numbered questions far more reliably than prose.

> **⚠️ Before sending, fill in the two placeholders:** `[ORDER/QUOTE REF]` and, if you have one,
> your account/company name. Everything else is ready to paste.

---

## Subject

`PCBA enquiry — consigned/global-sourcing mixing rule, Pico variant, depanel order, Phoenix sourcing (4 questions)`

---

## Body

Hello,

We are preparing a 34-board Standard PCBA order (4-layer, 250 × 240 mm, ENIG, ~314 placed
components including through-hole). Before we upload, we need four things confirmed. Numbered
answers would be very helpful.

---

**1. Consigned parts + JLCPCB parts on the same order — can they be mixed?**

Your Consigned Parts *Terms & Conditions* state that consigned parts "can only be used together
with global sourcing parts, instead of JLCPCB parts."

Your Consigned Parts *how-to* page appears to describe the rule **per component** — that for the
same part A you cannot mix JLC and consigned stock, but you may use a JLCPCB part for part A and
a consigned part for part B on the same order.

These read differently to us and the difference is decisive:

- If the rule is **per component**, we would consign roughly 6 component types and continue to
  use your library for the remaining ~27 lines.
- If the rule is **per order**, consigning any part would force all ~27 of our existing JLCPCB
  library lines onto Global Sourcing as well.

**Which is correct?** If mixing is allowed, please confirm explicitly that JLCPCB-library parts
and consigned parts may appear on the same BOM for different components.

---

**2. Which JLCPCB part number is the bare Raspberry Pi Pico (RP2040, SC0915)?**

We need the **original Raspberry Pi Pico — RP2040 silicon, castellated module, NO pre-soldered
headers**. Our firmware is RP2040-only. A Pico 2 / RP2350, or a Pico H/WH with headers fitted,
would be unusable for us.

Two candidates in your library, both ambiguous from the public page:

- **C9900019762** — MPN shows as `SC0915` (correct for the bare Pico) and package `LCC-43`, but
  the manufacturer field reads "JLCPCB Assembly" rather than Raspberry Pi.
- **C7203002** — manufacturer Raspberry Pi, but the MPN string is just "Pico", which does not
  distinguish Pico / Pico H / Pico 2.

Please confirm:
  a) Which C-number is the **bare RP2040 Pico with no headers**?
  b) Is that part **RP2040**, not RP2350?
  c) Is it available on **Standard** PCBA, and what is current stock and unit price?
  d) It mounts as a surface-mount module on our board (footprint `RaspberryPi_Pico_SMD`, 40-pad
     castellated edge, 28 pads electrically connected in our design). Can your Standard service
     place it reflow, and are there any special requirements?

---

**3. Through-hole insertion vs depanelization order**

Our board carries through-hole connectors close to the board edge — the nearest component body
sits about **0.6 mm** from one edge and about **2.3 mm** from another, on 1.4 mm plated barrels.

If an edge rail is added for the SMT pass, **is the rail removed before or after the
through-hole components are inserted and soldered?**

Our concern is depanelization stress running within a few millimetres of a connector body on
1.4 mm barrels. If the rail is snapped off after THT insertion, we would like to discuss rail
placement — specifically, **we need any rail on the LEFT or RIGHT edge, never the top or
bottom.**

---

**4. Sourcing four Phoenix Contact connectors we could not resolve in your library**

We already use these three from your library and they are working well for us:

| Our ref | Phoenix MPN | JLCPCB part |
|---|---|---|
| J2 | 1715734 | C480520 |
| J6–J11 | 1715721 | C480516 |
| J14 | 1843622 | C480549 |

We would like the following four in the **same exact Phoenix Contact part numbers**. Searching
your site by the bare numeric MPN returns no results, but we know that is unreliable — searching
`1843622` also returns "0 Found" even though C480549 exists and is in stock — so we suspect
these may exist under C-numbers we have not found:

| Our ref | Phoenix MPN | Description |
|---|---|---|
| J3, J15 | **1843680** | MCV 1,5/10-G-3,5 — 10-position vertical header, 3.5 mm |
| J4 | **1843729** | MCV 1,5/14-G-3,5 — 14-position vertical header, 3.5 mm |
| J5 | **1843703** | MCV 1,5/12-G-3,5 — 12-position vertical header, 3.5 mm |
| J13, J16 | **1843648** | MCV 1,5/6-G-3,5 — 6-position vertical header, 3.5 mm |

Plus two more, same request:

| Our ref | MPN | Description |
|---|---|---|
| U45 | **TMA 0505S** (TRACO Power) | Isolated 1 W 5 V→5 V SIP DC/DC converter, through-hole |
| J1 | **3020-20-0100-00** (CNC Tech) | 2×10 shrouded IDC box header, 2.54 mm, vertical THT |

For **J1 only**, a functionally equivalent part **is acceptable** provided it is a standard
**DIN 41651 / IEC 60603-13 2×10 shrouded box header, 2.54 mm pitch, vertical through-hole, with a
polarising notch**. If you have a library part meeting that description, please quote it — this
is the one component on our board where we are flexible on manufacturer.

Please tell us either (a) the C-numbers if they exist in your library, or (b) a Global Sourcing
quote for the exact manufacturer part numbers above.

> **⛔ IMPORTANT — no substitutions.** If you cannot supply an exact part number listed above,
> please tell us and we will fit that component ourselves. **Please do not substitute an
> equivalent connector.** These parts mate with pre-committed cable assemblies and use a
> mechanical coding scheme, so a dimensionally similar alternative would not work for us, even
> if it is electrically identical.

---

Thank you — we are ready to upload as soon as questions 1 and 2 are answered.

Best regards,
Dylan DeYoung
Westside Lanes · Olympia, WA
`[ORDER/QUOTE REF]`

---

## What each answer unblocks

| Q | If the answer is… | Then |
|---|---|---|
| 1 | per-component mixing allowed | Wave 2 proceeds at the ~$125–340 channel cost |
| 1 | per-order | **Wave 2 is dead at any sane price.** Ship wave 1 only; hand-solder the remaining 9 |
| 2 | a confirmed bare RP2040 C-number | A1 joins wave 2; still require a silkscreen photo before payment |
| 2 | ambiguous or Pico 2 | **A1 stays hand-soldered.** Never risk RP2350 on 34 boards |
| 3 | rail removed *before* THT insertion | Edge-proximity concern dissolves |
| 3 | rail removed *after* | Insist on left/right placement in writing |
| 4 | C-numbers exist | Wave 2 is nearly free — no consignment, Q1 becomes moot |
| 4 | Global Sourcing only | Weigh $162–333 against hand-soldering 62 pins/board |
