# FA-9 bench pre-check — proving the opto front end on hardware you already own

**Written 2026-07-27.** A ~1-hour bench test on an **existing rev-B or rev-C board** that
de-risks the single largest technical unknown in the rev-D design, using **no new parts**.

> **What this is.** FA-9 asks whether the PC817B optocouplers can still pull a logic input LOW at
> rev-D's reduced LED current, hot. That question cannot be formally closed until rev-D boards
> exist — but it can be **answered early, and conservatively, on the boards already on the bench.**
>
> **What it is not.** This does **not** discharge gate FA-9. FA-9 is still executed per channel on
> the first articles. This is a pre-check that tells you now whether to expect a problem then.

---

## 1. Why an old board is a *harder* test than the real one

| | rev-B / rev-C (bench) | rev-D (real) |
|---|---|---|
| Collector pull-up `Rpu` | **10 kΩ** | 47 kΩ |
| Current the opto must sink to reach V_OL 0.66 V | **(3.3 − 0.66)/10 k = 264 µA** | (3.3 − 0.66)/47 k = **56.2 µA** |

**The bench board demands 4.7× more current from the same optocoupler.** So if a channel passes
at 1.12 mA on a 10 kΩ pull-up, the rev-D channel passes with 4.7× margin in hand. A pass here is
strong evidence; a fail here is not yet fatal, but it is the warning you want before 1,360 optos
are wave-soldered.

**Target LED current** (rev-D r6, after the series blocking diode):

| Condition | I_F |
|---|---|
| Nominal, Vw = 5.0 V | **1.34 mA** |
| FA-9 loaded minimum, TP4 ≈ 4.5 V | **1.12 mA** ← test at this |

Test at **1.12 mA**. It is the worst case that matters.

---

## 2. Equipment

- **DMM ×2** — or one meter and two passes. ⚠️ See the isolation warning in §3.
- **Bench supply** or a 9 V battery + resistor. A constant-current supply is nicer but not required.
- **Resistor assortment** around 1–5 kΩ, or a 10 kΩ trimmer, to set the current.
- **Hot-air gun or heat gun** and a way to read temperature — thermocouple, IR thermometer, or a
  cheap probe taped to the opto body.
- The **rev-B/rev-C** test-point map.

> ⛔ **Use the rev-B/rev-C TP map, never the rev-D one.** 46 refdes shifted between rev-C and
> rev-D (`ISO_WET` U37→U45, `U_WDOG` U36→U44, the R100-series watchdog family → R116–128). A
> rev-D map on a rev-B board points you at the wrong parts.

---

## 3. ⛔ The one way to damage something: bridging the isolation

The board has **two separate ground domains**, and the whole opto design exists to keep them apart:

- **`FIELD_GND`** — TP5. The field/machine side.
- **Logic `GND`** — TP2. The Pi/MCU side.

The silkscreen says **DO NOT BRIDGE TP2 TO TP5**, and it means it.

**The trap:** you are measuring `I_F` on the *field* side and `V_CE` on the *logic* side. If you
use two mains-powered instruments whose grounds are commoned through the earth pin, **you bridge
the isolation through the test gear** — and the measurement you are trying to make becomes
meaningless at the same moment you defeat the thing under test.

**Do one of these:**
- Use a **battery-powered DMM** for the field-side current, or
- Measure the two sides **sequentially**, never simultaneously with commoned grounds, or
- Use a floating/isolated bench supply for the field injection.

Confirm before you start: **TP5 to TP2 must read OPEN.** If it reads short, stop and find out why.

---

## 4. Setup

One opto channel, as built on rev-B/C:

```
  FIELD_WET_V ──► Rin (2k2) ──► PC817 LED anode
                                PC817 LED cathode ──► field pin  (J3/J4/J5 terminal)
                                                          │
                                                    [ your Rext ]   ← you insert this
                                                          │
                                                     FIELD_GND

  VCC_3V3 ──► Rpu (10k) ──► COLLECTOR NODE  ← measure V_CE here
                    ▲
   PC817 collector ─┘
   PC817 emitter ──► logic GND
```

1. Power the board normally. Let `FIELD_WET_V` settle and **record TP4**.
   *(Expect a high reading unloaded — the TMA-0505S is unregulated and rises with no load. It
   falls once the channel draws current. That is normal, not a fault.)*
2. Pick **one** channel on a landed field connector. Note which refdes opto it is.
3. Wire your DMM **in series** between that field pin and `FIELD_GND`, through `Rext`.
4. Put the second meter (or your second pass) on the **collector node** referenced to **logic GND**.

---

## 5. Procedure

### Step 1 — set the current
Adjust `Rext` until the series DMM reads **1.12 mA ±0.02**. Record the value of `Rext` you needed.

### Step 2 — cold reading
Record `V_CE` at the collector node.

### Step 3 — heat
Warm the opto body to **≥ 70 °C** and hold it there. Let the reading settle — 30 s or so.
Re-record `V_CE` **and** re-check `I_F` (it drifts as the LED warms; re-trim `Rext` back to
1.12 mA if it has moved).

### Step 4 — repeat on 3–4 channels
Optos vary part to part. One channel proves nothing about spread. Do at least three, and include
one from each opto bank if the board has more than one.

### Step 5 — optional, worth doing
Repeat at **1.34 mA** (the nominal case) to see how much the margin improves off the worst case.

### Data table

| Channel / refdes | Rext (Ω) | I_F (mA) | V_CE cold (V) | Temp (°C) | V_CE hot (V) | Pass? |
|---|---|---|---|---|---|---|
| | | 1.12 | | | | |
| | | 1.12 | | | | |
| | | 1.12 | | | | |

---

## 6. Pass criteria

| Result | Meaning |
|---|---|
| **V_CE < 0.66 V hot, on every channel** | **PASS.** The rev-D channel has ~4.7× more margin than this proved. Expect FA-9 to pass. |
| V_CE 0.66–1.0 V hot | **MARGINAL on the bench board.** rev-D would still likely pass on the 47 kΩ, but stop and re-derive before ordering optos in fleet quantity. |
| V_CE > 1.0 V hot, or it will not pull down at all | **INVESTIGATE.** Do not assume the design is wrong — first confirm `I_F` really is 1.12 mA, that you are on the right collector node, and that the isolation is intact. |

**0.66 V is the design's V_OL assumption** — the number behind the 56.2 µA sink requirement in
the 47 kΩ arithmetic.

---

## 7. If it fails

Do not jump to replacing optos. The cheap fixes come first and they are all **0805 SMD**:

1. **Lower `Rin`** (2k2 → smaller) to raise LED current. 40 per board, SMD, cheap rework.
2. **Raise `Rpu`** beyond 47 kΩ to reduce the required sink — but this eats noise margin and the
   RC edge budget, so re-derive both before touching it.
3. **Replace the optos** — 40 through-hole parts per board. This is the expensive one and the
   reason the pre-check exists at all.

---

## 8. What this proves, and what it does not

**Proves:** that a PC817B of this type, at rev-D's operating current and hot, can sink enough to
make a valid logic LOW — with a 4.7× conservatism built into the test.

**Does not prove:**
- **Lot variance.** JLC pulls its own reel. This tests the *part type and rank*, which is the
  actual open question — the UMW part lacks a guaranteed minimum CTR at this current — but not
  the specific reel JLC will use.
- **Per-channel behaviour on rev-D.** Only FA-9 on real boards does that.
- **Edge speed.** The ≤ 100 µs transition criterion needs a scope and is a separate FA-9 step.
- **End-of-life drift.** Aging reserve is in the FA-9 numbers, not in a bench snapshot.

Record the numbers in the run log either way. A clean pass is evidence worth keeping; a marginal
result is a finding that changes the fleet decision.
