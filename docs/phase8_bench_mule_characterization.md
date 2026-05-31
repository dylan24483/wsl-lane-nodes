# AMF 82-70 Bench-Mule Characterization Protocol

**One pass down the spare cabinet → every measurement for scoring, clone, or full-controller.**

This characterizes the **spare 82-70 control chassis** (Omega-Tek Omniboard + Expander + ZOT foul board + contactors + transformers + connectors) on the bench. It is the single session that gates all three paths:

- **Scoring-first** (keep the board, retire Qubica): need the read-only tap points + their voltages (Part 2).
- **Clone the Omniboard** (continuity): need the connector/power map (Part 1) + a separate board-trace (not in this doc).
- **Full Pi controller** (retire the board): need everything — I/O list + voltages + which stops are hardwired (Parts 3–5).

> **The cabinet is the control chassis only.** The cam switches (SA/SB/SC, TA-1/TA-2), bin switch, start switch, grippers, motors, and mask lamps are **external devices** reached through the chassis connectors (C1, Mask/ELCO, BPP, scoring). Where the bench unit has no mechanism attached, **simulate** an input by jumpering its connector pin and watch the board react; confirm true rest/active levels at a live lane later. Each item below is flagged **[chassis]** (measurable here) or **[ext]** (external device — simulate / confirm live).

---

## ⚠️ SAFETY — read first
- **110 VAC is live in the chassis when powered.** The **only** acceptable disconnect is pulling the **Russell-Stoll plug** (per the Omega-Tek manual).
- **Wait ≥ 1 minute after power-off** before handling boards — ~150 V DC (CP-3 rail) takes time to bleed down.
- **All tracing is done COLD** (unplugged). For powered readings: one hand in your pocket, plug the chassis into a **GFCI** outlet, and once the rails are known, probe **only the low-voltage side**.
- **No mechanism is attached → no pit/pinch hazard.** The only hazard on the bench is the mains. Respect it.

## Setup (once)
- [ ] Meter works (leads together = beep; DC battery reads good).
- [ ] **GND reference** = PC-5 GND lug / chassis frame. Confirm continuity lug→frame. Black probe stays here for all voltage readings. REC: __________
- [ ] Identify + **label + photograph** every connector: **C1** (chassis harness), **Mask** (ELCO), **BPP**, **scoring** (APS/Qubica 3-wire), **Russell-Stoll** (power in).

---

## PART 1 — Power & ground map  *(cold, then powered)* **[chassis]**
- [ ] **Cold:** buzz PC-5 GND lug → chassis frame (continuity). REC ______
- [ ] **Cold:** locate the **12 V lug** adjacent PC-5 (do NOT confuse with the GND lugs at the other end of PC-5).
- [ ] **Powered:** raw rail (expect ~35 V): REC ______  ·  **12 V** (MC7812): REC ______  ·  **5 V** (MC7805): REC ______
- [ ] **Powered:** any higher rail? (CP-3 ~150 V pin-lamp supply per the manual): REC ______ V, where: __________

---

## PART 2 — Scoring tap: the PIN LAMPS connector  *(read-only — now LOCATED + LABELED)*

The Omniboard's labeled **PIN LAMPS** connector carries the entire scoring data set — confirmed off the board:

| Row | Terminals (left → right) |
|---|---|
| **5V** | 7 · 3 · 10 · 6 · 4 · 1B · X · T |
| **12V** | 9 · 5 · 1 · 8 · F · 2 · 2B · S |

- **1–10** = the ten pin-indicator lamps (all present)
- **F** = foul · **1B / 2B** = 1st / 2nd ball · **X, T, S** = status/sync (confirm by cycling)
- **5V / 12V** = supply rails (left column)

Capture (needs a powered, cycling machine — see Next Session): black probe on chassis frame (= ground). Per terminal record **type** (AC/DC), **rest** (pin down), **active** (pin standing), **voltage**.

*(DIELL ball-detect stays the clean "ball thrown" trigger — already known: ~16 V rest / 0.7 V broken, NPN active-low.)*

| Terminal | Type | Rest | Active | Notes |
|---|---|---|---|---|
| pins 1–10 | | | | |
| F (foul) | | | | |
| 1B / 2B | | | | |
| X / T / S | | | | |

---

## ⭐ RECOMMENDED NEXT SESSION — get real PIN LAMPS data safely

The data we still need (each line's real voltage + on/off polarity) **only exists on a powered, cycling machine.** Two ways:

- ✅ **Live lane 21/22 — do this.** The machine is already powered + cycling = real pin data. Wire the opto tap **cold** (machine off at its frame Russell-Stoll), then power on and let the Pi log every line as it cycles. You never probe live mains, you get real data, and it's literally installing the tap.
- ❌ **Bench-powering the spare — skip.** You'd have to wire 110 VAC to the spare yourself (mains shock/fault risk for a beginner), and it still can't produce pin data (no machine = no cycles). It only gives idle rail voltages.

**Use the spare as the zero-voltage build + fit jig**, then capture for real on 21/22:
1. **Reseat** the Omniboard (PC-4) + Expander (PC-1) — gold fingers in, correct orientation.
2. **Close-up photo** of the PIN LAMPS connector itself + how the existing harness plugs into it — so we can spec the tap's mating connector.
3. **Build** the opto tap harness (your AL-ZARD opto chain, already proven) onto those terminals.
4. **Install cold + capture** on lane 21/22 (machine off → wire → power on → Pi logs).

---

## PART 3 — Full-controller I/O  *(only if pursuing board replacement)*

### Inputs the Pi would read
- [ ] **Start switch / cushion [ext]** (cycle trigger) — line + level. REC ______  *(on our machines the DIELL is the trigger)*
- [ ] **Sweep cams SA (270°), SB, SC [ext]** — lines + expected level (logic? pulled to 12 V?). Simulate by jumpering; watch board. REC ______
- [ ] **Table cams TA-1 (185-355°), TA-2 (260°) [ext]** — REC ______
- [ ] **Bin switch (BS) [ext]** — REC ______
- [ ] **Gripper-protect switch [ext]** — REC ______
- [ ] **Off-spot (OS) · Instructomat · 2nd-ball state [ext/chassis]** — REC ______
- [ ] **Grippers ×10 [ext]** (pin sense at U27/U28, 14049 CMOS level) — line map + level. REC ______

### Outputs the Pi would drive  *(measure coil/drive voltage + AC/DC)*
- [ ] **Sweep motor contactor coil [chassis]** — V + AC/DC; read label (Schneider CAD32 / Siemens 3TB4102). REC ______
- [ ] **Table motor contactor coil [chassis]** — V. REC ______
- [ ] **Sweep-reverse relay coil [chassis]** — V. REC ______
- [ ] **Spot relay coil [chassis]** — V. REC ______
- [ ] **Pin lamps ×10 drive [chassis]** — V + AC/DC (SCR/triac-driven; the ~150 V rail?). REC ______
- [ ] **Status lamps (strike/1st/2nd/foul) drive [chassis]** — V. REC ______

---

## PART 4 — WHICH STOPS ARE HARDWIRED  ⭐ *(decides the Pi's real-time burden)*
**The question:** does a cam limit *physically* cut the motor contactor, or does it only tell the board?

- [ ] **SWEEP stop at 270° (SA):** COLD-trace — does SA's contact sit in the **sweep-contactor coil circuit** (hardwired stop), or only land on a **board input**? Hardwired?  **Y / N** ____
- [ ] **TABLE stop (TA cams):** same trace. Hardwired?  **Y / N** ____
- [ ] **If Y (hardwired):** the Pi only *starts* motors; hardware *stops* them → **low real-time burden, much safer.**
- [ ] **If N (board-logic only):** the Pi must *time* the stop → requires the MCU co-processor **and** we ADD hardware end-stops before any live motor. **FLAG.**

---

## PART 5 — SAFETY CHAIN  ⚠️ *(highest priority of all)*
- [ ] Locate the **stop switch** (left of the power plug) and **C.I.S.** (1981 safety switch).
- [ ] **Cold-trace:** are they **in series with the motor contactors**? In series?  **Y / N** ____
- [ ] **If N:** FLAG — any controller (and possibly some tap work) must add a hardware interlock in series before powering motors.

---

## Consolidated table  *(transcribe results)*

| Signal | In/Out | Connector·Pin | AC/DC | Rest | Active | Notes |
|---|---|---|---|---|---|---|
| DIELL ball | in | | DC | ~16 V | ~0.7 V | known/NPN |
| Foul | in | | | | | |
| 2nd-ball lamp | in | | | | | |
| Pin line 1 | in | | | | | |
| … pin lines 2-10 | in | | | | | |
| Start/cushion | in | | | | | |
| SA / SB / SC | in | | | | | |
| TA-1 / TA-2 | in | | | | | |
| Bin switch | in | | | | | |
| Grippers 1-10 | in | | | | | |
| Sweep motor coil | out | | | — | — | |
| Table motor coil | out | | | — | — | |
| Sweep-reverse coil | out | | | — | — | |
| Spot relay coil | out | | | — | — | |
| Pin lamps 1-10 | out | | | — | — | |
| Status lamps ×4 | out | | | — | — | |
| **Sweep stop hardwired?** | — | | | | | **Y / N** |
| **Table stop hardwired?** | — | | | | | **Y / N** |
| **C.I.S./stop in series?** | — | | | | | **Y / N** |

**If short on time:** Part 1 (power), Part 2 (scoring signals), and Parts 4–5 (stops + safety) are essential. Part 3 (controller I/O) only if you're pursuing full replacement.
