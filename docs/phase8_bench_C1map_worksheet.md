# Phase 8 — C1 Cavity Map + §B-bench Cam-Stop Trace (fill-in worksheet)

**For Dylan, at the spare cabinet. All COLD (unplugged), continuity/beep mode.** Two jobs:
- **JOB 1 — C1 map:** confirm which relay each C1 cavity reaches (verifies the machine-side pinout + tells us which physical relay is S vs T).
- **JOB 2 — §B-bench:** trace the S & T relay *coils* to learn whether the motor-stops are hardwired or board-logic.

---

## How C1 cavities are addressed (the key that unlocks this)
The schematic pin labels like **`21D`, `17DD`, `19NN`** = **[wire number][CAVITY LETTER]**. The **letter is the physical cavity molded on your connector** (the A, B, D, … EE, FF, … NN you photographed). The number is just the schematic's wire ID. **So you locate cavities by their molded letters** — ignore the numbers, they're only for cross-referencing.

- **Datum:** the **"01" + AMP** mark = the pin-1 corner. Hold the connector with "01" oriented the same as in photo `20260601_091852` so letters read consistently.
- AMP skips I, O, Q (look-alikes for 1/0). Sequence: A B C D E F G H J K L M N P R S T U V W X Y Z, then AA BB CC DD EE FF GG HH JJ KK LL MM NN.
- If a molded letter is unreadable, tell me "Nth cavity from 01 in column X" and I'll map it.

---

# JOB 1 — C1 CAVITY → RELAY MAP

## ❓ "How are terminals numbered?" — they're NOT, and for JOB 1 it doesn't matter
The "terminal 1/2/3" rows below are just **blank lines to record hits + a count** — NOT a required numbering scheme. JOB 1 asks **"does this relay reach the expected SET of cavities?"** (e.g. is S wired to {D,J,N,T}?). It's irrelevant whether a given terminal hits D vs N — only the *set* matters. So **just record the cavity letters you find, in any order.**

When you DO want to name a specific terminal:
- **Labeled relays → use the printed labels.** Siemens 3TH4022: contacts **13/14, 21/22, 31/32, 43/44**, coil **A1/A2**. Report those as-is; don't invent numbers.
- **Unlabeled relays (M2, M, SP, BE, the 4-terminal partner) → any consistent physical convention + a photo.** Suggested: orient the relay a repeatable way (label/coil facing you, mounting tab down), number **left→right, top row first**. Note it / mark with tape so "T1,T2…" matches your photo. (Only needed if a reading is surprising and we have to correlate.)

**Method (relay-by-relay — fewest probe moves):** anchor one probe on a **relay terminal**, sweep the other across the C1 cavities until it beeps, record the **cavity letter**. Do all terminals of one relay, then move on. Compare the set of letters to the "Expected cavities" column.

> **⚠️ S and T = the HEAVY-LUG COPPER CONTACTORS** (the big saddle-terminal units with thick motor leads, center/right of the upper-R cluster — photos 150135/150146/150247). **NOT the Siemens 3TH4022** — that's a thin-wire control relay (probing it to C1 reads open; that's correct, it's not a motor relay). **C1 = the 3-column connector** (round pins, 2 power cavities, "C1" stencil beside it; LEFT in photo 150321). This job tells you **which contactor is S vs T** — whichever hits {D,J,N,T} is **S (sweep)**; {A,E,K,P,H} is **T (table)**.

### Sweep relay "S" — expected cavities: **D, J, N, T**
| relay terminal (any order) | cavity letter it beeps to | matches D/J/N/T? |
|---|---|---|
| terminal 1 | ____ | |
| terminal 2 | ____ | |
| terminal 3 | ____ | |
| terminal 4 | ____ | |
→ Is THIS relay the Siemens or the 4-terminal partner? ____  → so **S = ______**

### Table relay "T" — expected cavities: **A, E, K, P, H**
| relay terminal | cavity letter | matches A/E/K/P/H? |
|---|---|---|
| terminal 1 | ____ | |
| terminal 2 | ____ | |
| terminal 3 | ____ | |
| terminal 4 | ____ | |
| terminal 5 | ____ | |
→ **T = ______** (the other upper-right relay)

### M2 sweep-reverse — expected cavities: **DD, JJ, BB, FF**
| terminal | cavity | match? |
|---|---|---|
| 1 | ____ | |
| 2 | ____ | |
| 3 | ____ | |
| 4 | ____ | |
(M2 = one of the 82-70-5515 family, 80 Ω coil)

### SP spot solenoid relay — expected cavities: **U, Y**
| terminal | cavity | match? |
|---|---|---|
| 1 | ____ | |
| 2 | ____ | |
(SP = the 100 Ω-coil relay)

### BE back-end — expected cavities: **W, EE**
| terminal | cavity | match? |
|---|---|---|
| 1 | ____ | |
| 2 | ____ | |
(BE = the 22 Ω-coil, 6-terminal relay)

### M master — expected cavities: (not in the C1 wire table — M switches T1/power, may land on the transformer/power block, not C1)
- Beep M's contact terminals to C1 anyway; record any cavity hits: ____
- (M = the other 80 Ω 82-70-5515, identical to M2)

### Power / reference cavities (confirm)
| cavity | expected | beep test | reading |
|---|---|---|---|
| **L** | → T2 transformer | beep cavity L to the transformer terminals | ____ |
| **NN** | → GND / chassis | beep cavity NN to bare chassis frame | ____ (should beep) |
| **2 big power pins** (bottom, heavy gauge) | main power feed | beep to the power-in terminal block / transformer primary | ____ |

> **What to send me:** the cavity letter recorded for each relay terminal. Anything that does NOT land in the expected set is a real correction (we bake it into the board). Mismatches are useful, not failures — write them down.

---

# JOB 2 — §B-bench: ARE THE MOTOR-STOPS HARDWIRED OR LOGIC? ⭐

**Why we trace the COIL, not the cam:** the cams are on the machine (not your bench), and the exact C2A cam-pin codes are uncertain. But the **relay coil is in your cabinet and you've already found it.** What *drives* that coil tells us the answer:
- If the coil is energized/de-energized **by the Omega-Tek board** (coil terminal → a board output driver) → **LOGIC stop** (the board reads the cam and decides). Expected on this SS/Omega-Tek chassis.
- If the coil circuit **passes through a C2A pin** (i.e., a machine cam switch is physically in series with the coil) → **HARDWIRED stop.**

### Trace each coil terminal of S and T
Here "coil terminal #1 / #2" = simply **the two ends of the coil pair you already found** (the mid-resistance pair). On the Siemens those are the stamped **A1 and A2**; on the partner relay they're the two ends of its coil pair. **Order doesn't matter** — you trace both ends either way. For **each** coil terminal, beep it to each of these and mark what it reaches:

**Sweep "S" — coil terminal #1 (A1):**
- reaches the **Omega-Tek board edge** (any finger)? ____ (Y/N)
- reaches a **24 V transformer** terminal (T2/T3/T4)? ____
- reaches a **C2A connector pin**? ____ (Y/N — if Y, note which cavity if readable)

**Sweep "S" — coil terminal #2 (A2):**
- board edge? ____ · transformer? ____ · C2A pin? ____

**Table "T" — coil terminal #1:**
- board edge? ____ · transformer? ____ · C2A pin? ____

**Table "T" — coil terminal #2:**
- board edge? ____ · transformer? ____ · C2A pin? ____

### How to read your own results (quick):
- **Both coil terminals reach only the BOARD + transformer, NO C2A pin** → **LOGIC stops.** (The board switches the coil; cams are board inputs.) → our design's RP2040 cam-stop + hardware end-stop plan is correct as-is.
- **A coil terminal goes through a C2A pin** → **HARDWIRED path exists** → even better (machine cam can drop the relay directly); we preserve it.
- **Unsure / weird** → just send the raw "reaches X" answers + a photo of the board edge connector; I'll interpret.

> This is *preliminary* (the definitive proof is flipping the real cam at the machine — Part 2/§B-machine). But the bench trace usually answers it, and it's enough to lock the relay-enable-rail design.

---

## When done, send me:
1. **Job 1:** the cavity letter for each relay terminal (+ which relay = S vs T).
2. **Job 2:** the "reaches board / transformer / C2A" answers for the 4 coil terminals.
3. Any mismatches or oddities + a photo if something doesn't fit.

→ I lock the **corrected C1 map** into `phase8_channel_allocation.md` (OUT-A channel assignments) and set the **cam-stop architecture** → that's the last bench-gated input before PCB rev-B layout.

## If short on time
**Job 1 for just S, T, SP** (the three the FSM drives first) + **Job 2** = the high-value 30 minutes. M2/M/BE/power can follow.
