# Phase 8 — Bench Session 2: Exact Probe-Point List (spare cabinet)

**For Dylan (meter-comfortable; cabinet now mapped).** Session 1 identified the hardware; this is the **ordered probe list** — what to touch, what reading to expect, what it tells us. Anchored to the confirmed layout:
- **C1 = LEFT connector (34-pin, 3-col, double-letter rows EE…NN + 2 power pins, "01"+AMP mark).**
- **C2A = RIGHT connector (50-pin, 4-col).**
- **Pin-1 datum = the molded "01" + AMP logo end** on each connector.
- Relays per Fig-1: KX (top-L), S/T (upper-R), M2/M/SP (lower-center), BE (lower-L); Siemens **3TH4022-0A** control relay + a power contactor (upper-R); **P&B JRM-10110 12 VDC** relay.

**All COLD** (cabinet disconnected, mains unplugged). Meter: continuity/beep + resistance (200Ω–20kΩ) + DC volts (for the one cap check). Black probe = chassis frame = ground throughout.

> ## ⚠️ READ FIRST — cabinet vs machine (this fixes the v1 confusion)
> Your **spare cabinet = the control chassis ONLY**: relays, the Omega-Tek board, the C1/C2A connectors, transformers, caps. **That's all that's on your bench.**
> The **stop switch, the cams (SA/SB/SC/TA1/TA2/TB), the motors, grippers, and the Russell-Stoll power inlet are all on the actual pinsetter MACHINE** at the lanes — **NOT on your bench.** They reach the cabinet only through C1/C2A pins.
>
> So this session splits in two:
> - **BENCH-DOABLE NOW (both ends inside the cabinet):** **§D coil voltages**, **§C C1 relay→pin map**, **§B-bench topology trace** (does the cam's C2A pin route toward a relay coil or to the board?). ← do these on the spare.
> - **AT-THE-MACHINE later (needs the real pinsetter), during 21/22 cutover prep:** **§A safety-chain actuation**, **§B-machine actuation** (flip the cam, watch the coil drop). ← these CANNOT be done on the bench; they're moved to the end + clearly tagged. Don't hunt for a stop switch or cam on the cabinet — they aren't there.
>
> **Recommended bench order: §D → §C → §B-bench.** (Start with §D — it's the easiest and you already have the relays in front of you.)

> **Finding a COIL terminal — READ THE ACTUAL OHMS, don't sort by "low/none" (this is the v2 fix).** A relay has TWO kinds of pairs and BOTH can read "low," so the distinction is a *number*:
> - **NC contact at rest = ~0 Ω (dead short, full beep).** ← these are the "multiple low-resistance pairs" you'll see on a contactor; they are CONTACTS, not the coil.
> - **NO contact at rest = open / ∞.**
> - **COIL = a specific MID value, ~50–1000 Ω** — not a dead short, not open.
>
> So **write the real ohms on every pair**, then: ~0 Ω → NC contact · open → NO contact (or coil wired elsewhere) · **~50–1000 Ω → coil.**
> - **Siemens 3TH4022:** 4 contacts (13/14 NO, 21/22 NC, 31/32 NC, 43/44 NO) **+ coil at A1 (top)/A2 (bottom)**. The two ~0 Ω pairs = the NC contacts; **A1–A2 = the coil** (the few-hundred-ohm pair). If you can't find the A1/A2 stamps, the coil is the lone mid-resistance pair.
> - **A relay with NO NC-contacts** (e.g. M2) shows **no ~0 Ω pairs at all** — that's expected; its coil is still the mid-resistance pair (don't discount it for not being a near-short).
> - **3-terminal / unknown parts (e.g. P/N 82-70-5515) & SSRs:** if NO pair is mid-resistance, switch to **DIODE mode** and probe both directions — a ~0.4–0.7 V one-way reading = a **semiconductor (SSR/SCR)**, not a coil relay. Photograph + report all-pair numbers for these.
>
> **Shortcut:** the AMF manual says the native relay coils run on **24 V** (T2/T3/T4 are 24 V) — so for AMF-original relays we're confirming, not discovering. The retrofit **Siemens coil V** is the one that genuinely needs measuring.

> **Recording:** write the reading next to each step (beep/no-beep, Ω, or V); a photo of your jotted sheet is fine. Where the "01" datum makes a C1 pin ambiguous, just say "Nth pin from the 01 end, row R" — I'll map it.

---

# ════════ start here ════════

## §0 — Cap safety pre-check (2 min, once)
The two big cans (CP2/CP3, lower-center) *can* hold charge. It's been unplugged for weeks so this is hygiene:
1. Meter on **DC volts**, 200V range.
2. Red on one CP2 terminal, black on the other. **Expect ~0 V.** Repeat CP3.
3. Both ~0 V → safe to work freely. (If either shows >a few volts, tell me — don't bridge them.)
Record: CP2 ___ V, CP3 ___ V.

---

# ════════ PART 1: BENCH-DOABLE NOW (spare cabinet) ════════
Do these on the bench, in this order. All cold.

## §D — COIL VOLTAGES (do this FIRST — easiest, relays are right in front of you)
For each relay/contactor, find its **coil pair** (the steady-resistance terminals — see the "finding a coil" note up top) and get the voltage two ways:
1. **Label:** photograph any explicit "___V ___Hz" line on the front face / coil body. (For the 3TH40 it's a line *separate* from the contact-rating table you already shot — lower on the front.)
2. **Resistance:** meter the coil pair (3TH40 = **A1–A2**), cold. ⚠️ **The rule below is for DC coils ONLY. AC coils read FAR LOWER** (current is reactance-limited at 60 Hz, not R-limited) → a single-digit-to-low-tens Ω reading on a contactor = **AC coil**, and **resistance CANNOT give its voltage** (get the label). *(Confirmed live: the Siemens A1–A2 = 5 Ω = AC, ~24 VAC.)*
   - **DC coil ~50–200 Ω → 12–24 V**
   - **DC coil ~150–600 Ω → ~110/120 V**
   - **DC coil ~600 Ω–4 kΩ → 230/240 V**
   - **Any coil ≤ ~tens of Ω → it's AC → voltage NOT inferable from R; read the label.**

| coil | unit (Fig-1 pos) | coil pair? | label V | coil Ω | inferred V |
|---|---|---|---|---|---|
| Sweep "S" | upper-R (3TH40 or contactor) | A1–A2 | ___ | ___ | ___ |
| Table "T" | upper-R contactor | A1–A2 | ___ | ___ | ___ |
| M2 sweep-rev | lower-C ice-cube | steady-Ω pair | ___ | ___ | ___ |
| M / master | (contactor) | A1–A2 | ___ | ___ | ___ |
| SP spot | lower-C ice-cube | steady-Ω pair | ___ | ___ | ___ |
| BE back-end | lower-L | steady-Ω pair | ___ | ___ | ___ |
| P&B JRM-10110 | (the 24-pin socket relay) | steady-Ω pair | **12 VDC** (label) | ___ | 12 VDC |

> Note: not every Fig-1 relay may be physically present in the spare — just fill what's there and note any empty socket. The 3TH40 you photographed is one of the upper-R units; identify whether it's the S or T (or M) by which C1 pins it maps to in §C.

**Why it matters:** the coil-voltage SET = what the AEDIKO 5 V dry contacts must SWITCH, and whether the DIN enclosure needs a **12 V and/or 24 V rail** beyond the 5 V (only HDR-15-5 specced now). A mix → add one more DIN PSU.

---

## §C — C1 RELAY→PIN MAP (which C1 pin drives which relay)
C1 = **LEFT 34-pin**. Both ends are inside the cabinet, so this is pure cold continuity. Work from the **"01" datum end**.

For each relay, beep from **one of its coil terminals** (the §D coil pair) to the C1 pins; find which C1 pin(s) the relay's wires reach. The pinout doc predicts these — **verify, and flag mismatches** (mismatches are the real corrections we bake into the board):
| relay | coil drives | predicted C1 pins | your reading |
|---|---|---|---|
| **S** sweep | sweep motor | 21D / 22J / 23N / 24T | ____ |
| **T** table | table motor | 31A / 32E / 33K / 34P / 42H | ____ |
| **M2** sweep-rev | sweep reverse | 17DD / 18JJ / 26BB / 27FF | ____ |
| **SP** spot | spot solenoid | 35U / 36Y | ____ |
| **BE** back-end | back-end motor | 45W / 47EE | ____ |
| power/ground | — | 13L (T2) / 19NN (GND) | ____ |

- **The 2 big power pins on C1** (heavier gauge, bottom): beep them to the transformer primary / power-in terminal block inside the cabinet (NOT the Russell-Stoll — that's on the machine). Just confirm they're the main feed.
- **Tip:** you don't have to test all 34 — for each relay, beep its coil terminal to the *predicted* pins first; if one beeps, log it and move on. Only sweep the rest if none of the predicted pins hit.

---

## §B-bench — CAM-STOP TOPOLOGY (does the cam route to a coil or to the board?) ⭐
This is the **bench half** of THE architecture question. The cams themselves are on the machine, but **the C2A pin each cam lands on is in your cabinet** — so we can see where that pin goes *internally*, cold, without the machine.

C2A = **RIGHT 50-pin**. For each cam pin below, beep from that C2A pin and see where it lands **inside the cabinet**:
| cam | C2A pin (predicted) | beeps to a RELAY COIL circuit? | beeps to the OMEGA-TEK BOARD edge? |
|---|---|---|---|
| **SA** (sweep stop) | C2A-31N | ____ | ____ |
| **TA1** (table stop) | C2A-34N | ____ | ____ |
| **TA2** (run-through) | C2A-21A | ____ | ____ |

- **Method:** from the C2A pin, beep to (a) the S/T relay coil terminals, and (b) the Omega-Tek board's edge-connector fingers. Note which it reaches.
- **Meaning (preliminary):**
  - Reaches a **relay coil circuit** → the stop is likely **hardwired** (the cam breaks the coil directly). Best case — Pi only starts motors, machine stops them.
  - Reaches **only the board edge** → the stop is **logic** (board reads cam, board drops relay) → the Pi/RP2040 must time it + we add a hardware end-stop.
- This is *preliminary* because the final proof is flipping the real cam and watching the coil drop (§B-machine, Part 2). But the bench topology usually tells the story.

---

# ════════ PART 2: AT THE MACHINE — LATER (NOT on the bench) ════════
> ⚠️ **These need the real pinsetter at lane 21/22** (the stop switch, cams, and Russell-Stoll are machine-mounted — none are on your bench). Do these during **cutover prep**, with the machine **locked out** except for the specific deliberate test. **Don't attempt these on the spare cabinet — the parts aren't there.** Listed here so the bench session knows what it's deferring.

## §A — SAFETY CHAIN (at the machine) ⚠️
Answering: is the **Stop switch / C.I.S.** physically in series with motor power, or logic-only?
- At the machine: stop switch in RUN, master breaker ON → confirm the motor-relay coil rail is live; flip stop to STOP → it should go dead. Break on STOP ⇒ hardware-in-series (preserve it). No break ⇒ FLAG: add a hardware interlock before any Pi-driven motor.

## §B-machine — CAM-STOP ACTUATION (at the machine) ⭐
Confirms §B-bench: hand-rotate the sweep/table to trip the **SA / TA cam**, watch whether the corresponding motor-relay coil **drops** purely from the cam (hardwired) or only after the board reacts (logic).

---

## After Part 1 (bench)
Send the §D / §C / §B-bench tables (or photos of your jotted readings). I turn them into:
1. **Corrected C1 pin map** (§C) → locks OUT-A channel assignments in `phase8_channel_allocation.md`.
2. **Coil-voltage table** (§D) → finalizes enclosure PSU rails + AEDIKO contact wiring.
3. **Preliminary cam-stop architecture** (§B-bench) → informs the relay-enable-rail design; confirmed later at the machine (Part 2).

That closes the **bench-gated** unknowns → PCB rev-B can go to layout (the at-machine §A/§B-machine confirm the safety architecture before any live motor, not before layout).

> **If short on bench time:** §D alone (coil voltages) is the single most useful 20 minutes — it unblocks the PSU/enclosure spec. §C next. §B-bench last.
