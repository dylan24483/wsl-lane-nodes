# Field-Test Concepts Primer — the "why" behind the measurements

**Purpose:** build the mental model under the field sheet, so each step makes sense instead of being a ritual. Grounded in YOUR machine's real numbers. Read once before the session; it'll make everything click. ~15 min.

---

## 1. The three quantities: Voltage, Current, Resistance
The water-in-a-pipe analogy is corny but genuinely correct:
- **Voltage (V, volts)** = water **pressure**. The "push." A 24 V coil circuit has 24 volts of push behind it.
- **Current (I, amps)** = the **flow rate** — how much water actually moves per second. This is what does work + generates heat.
- **Resistance (R, ohms, Ω)** = how **narrow the pipe** is. More resistance = harder to push flow through.

They're locked together by **Ohm's Law: V = I × R** (pressure = flow × narrowness). Rearranged: **I = V / R**. So if you know two, you get the third.

**Why this matters for you:** on the bench you measured **resistance** (R) because the machine was off — you can measure R only on a dead circuit. At the machine you measure **voltage** (V) because it's live. Same circuit, different quantity, because of whether power is flowing.

**Worked example from your own data:** the SP relay coil = 100 Ω, fed by 24 V. So the current through it = I = V/R = 24/100 = **0.24 A**. That's why I said "coil circuits draw under 1 A" — you can *calculate* it from what you already measured, no clamp meter needed.

---

## 2. AC vs DC (and why it matters here)
- **DC (direct current)** = steady push in one direction. A battery. Symbol: ⎓ (straight line).
- **AC (alternating current)** = the push reverses back-and-forth 60 times a second (60 Hz, US wall power). Symbol: ~ (wavy line).

Your machine's control voltage is **24 VAC** — alternating. That's why your meter needs the **V~** setting, not **V⎓**, for the coil reads. (If you're on the wrong setting, AC on a DC range reads near-zero or garbage — a common "huh, nothing's there" mistake. If a read looks dead, try the other setting before concluding the wire is dead.)

---

## 3. The thing that confused you on the bench: why a 24 V coil reads only 5 Ω
This is worth really understanding because it bit you once. The Siemens S coil reads **5 Ω**, yet runs on **24 VAC**. By DC Ohm's law that would mean 24/5 = ~5 amps — absurd for a little control coil. So what gives?

**A coil is not just a resistor — it's an electromagnet (an inductor).** When you push **AC** through a coil, the changing magnetic field *pushes back* against the current. That pushback is called **inductive reactance** — it acts like extra resistance, but **only for AC**, and it doesn't show up on an ohmmeter (which uses DC).

So the coil has:
- **5 Ω of real wire resistance** (what your DC ohmmeter sees), plus
- **a much larger AC reactance** (invisible to the ohmmeter) that actually limits the running current.

That's why **resistance alone can't tell you an AC coil's voltage** — you measured 5 Ω but the voltage was hidden until you read the part number / will read it live. **DC coils** (no reactance trick) *do* follow the resistance→voltage rule, which is why the rule-of-thumb table worked for guessing DC coils but failed on the AC Siemens. One sentence: **on AC, the ohmmeter only sees the wire, not the magnetism.**

---

## 4. What a relay actually is (the heart of this whole project)
A **relay** is an electrically-operated switch. Two completely separate parts inside one package:
- **The coil** — a small electromagnet. Put voltage on it (your 24 V) and it makes a magnetic field.
- **The contacts** — metal switch points. The coil's magnetism physically *pulls* them open or closed.

The magic: **the coil and the contacts are not electrically connected to each other.** Low-voltage coil controls a totally separate (possibly high-power) contact circuit. That's the basis of everything.

**Terminology you hit:**
- **Relay** = the general term (e.g. your little ice-cube SP/M/M2).
- **Contactor** = just a big, beefy relay built for switching motors (your Siemens, your T). Same idea, heavier contacts.
- **NO / NC** = Normally-Open / Normally-Closed — the contact's resting state when the coil is OFF. NO = open until energized; NC = closed until energized. (You saw 21NC/13NO etc. on the Siemens.)

**Why your bench "coil = the steady-mid-resistance pair" trick worked:** the coil is wire (reads a steady ~tens-of-ohms); the contacts are either touching (0 Ω) or apart (open). That's literally how you tell coil terminals from contact terminals with an ohmmeter.

---

## 5. The single most important design idea: "we switch the coil, not the motor"
This is the principle the whole rev-B board rests on, so internalize it.

The pinsetter's motors run on **115 VAC at high current** — dangerous, heavy. We do **not** want our little board carrying that. We don't have to. Here's the chain that already exists in the machine:

> tiny control signal → energizes a **coil** (24 V, <1 A) → the coil's magnetism closes a **contactor** → the contactor's heavy contacts switch the **115 V motor**.

Our board just needs to **close the coil circuit** (the 24 V, <1 A part). The machine's existing contactor still does the dangerous motor-switching. So our relay (the G5LE) only ever sees the gentle coil circuit — which is why a 10 A signal relay is wildly overkill-safe for it.

**This is why your field test measures coil circuits, not motor circuits.** You're characterizing the gentle thing we touch, never the dangerous thing we leave alone. It's also why the design is fundamentally safe: we're one step removed from the motor, always.

---

## 6. Dry contact vs voltage-sense (the A4 concept)
Both are ways a switch "tells" something it's active — the difference is *who provides the voltage*:
- **Dry contact** = the switch is just bare metal touching. It has **no voltage of its own**; it just connects two wires. Like a wall light switch. To detect it, *we* send a small voltage down the wire and watch for it to come back when the switch closes ("wetting" it — that's what the isolated wetting supply on the board is for).
- **Voltage-sense** = the switch, when active, **delivers a voltage** to the wire (e.g. 24 VAC appears). We just watch for the voltage to show up.

**Why you test continuity-first:** a dry contact shows a **continuity change** (open→closed) even with the machine off. If you see that, you're done — it's dry. Only if there's *no* continuity change do you go live to check if a voltage appears (sense). Dry is the common case.

This matters for the board because each input front-end is built to handle *either* — you're just recording which default to set per channel.

---

## 7. Why measuring current is different (and awkward) — series vs parallel
This answers your "I've never measured current" directly, at the concept level:
- To measure **voltage**, you touch two points **without disturbing anything** — like checking the pressure difference across a pipe section by tapping it at two spots. Two probes, in **parallel** with the circuit. Easy, safe.
- To measure **current** the traditional way, you must **break the pipe and insert the meter so all the flow goes through it** — **in series**. That means cutting into a live circuit. Awkward and easy to botch.

A **clamp meter** cheats this: it senses the magnetic field *around* a wire (remember, current makes magnetism — §4), so it reads flow **without breaking the pipe** — you just clip it around one wire. That's why I said use a clamp or skip it. And §1 showed you can often just *calculate* current (I = V/R) from your resistance data instead of measuring it at all.

---

## 8. Ground / common — why the black probe stays on the chassis
Voltage is always a **difference between two points** — "24 volts" is meaningless without "relative to what." We pick one reference point and call it **ground** (or common): the metal chassis, which everything's voltage is measured against.

By clipping your **black probe to the chassis and leaving it**, every red-probe reading is automatically "volts relative to ground" — consistent, comparable, and it frees a hand. It's the electrical equivalent of measuring every height from the same floor instead of from wherever you happen to stand.

---

## 9. Isolation — why the board is split into "domains"
Some parts of the system must be **electrically separated** so a fault on one side can't push dangerous voltage to the other. Specifically: the **machine side** (24 V+, near motors, dirty) must not be able to backfeed the **logic side** (the 3.3 V Pi brain).

The bridge between them is an **optocoupler** (the PC817s): inside, an LED shines on a light-sensor across a tiny gap. The signal crosses as **light, not wire** — so the two sides share *no metal connection*. That gap is the "isolation barrier."

**Creepage/clearance** (the whole policy that's been gating the PCB) is just: *keep enough physical distance across that barrier that voltage can't jump it* — through the air (clearance) or crawling across the surface (creepage). That's why the board has FIELD / LOGIC / MACHINE "rooms" with gaps between them. Your **A1 measurement sets how big those gaps must be** — if the machine side is only 24 V, the gaps can be small; if it were 250 V, they'd need to be large. That's the direct line from "you with a meter" to "how the board is laid out."

---

## 10. Cams & timing — what those switches are doing
The pinsetter is a **rotating-machine ballet**: the sweep and table move through a precise sequence every cycle. The machine knows "where it is" in that sequence using **cam switches** — a lobe (bump) on a rotating shaft pushes a microswitch at a specific angle of rotation.

So "SA trips at 270°" means: when the sweep shaft has rotated to 270°, its cam lobe hits the SA microswitch, which tells the controller "sweep has reached the stop position." The controller reacts (stops the motor). The cams are the machine's **position sensors** — its sense of timing. Our Pi controller will read these same cams to know when to do what. That's why mapping them (Part C) matters: the board needs to hear the same timing signals the old controller did.

---

## Putting it together: what your field test actually IS
In one paragraph: *You're characterizing the gentle 24 V control layer of the machine — the coil circuits, the cam/switch signals — so our board can plug into that layer and command the machine the same way the old controller does, without ever touching the dangerous 115 V motor side. The voltage reads (A1) tell us how much isolation the board needs. The dry-vs-sense test (A4) tells us how to listen to each input. The harness map (Part C) tells us which wire is which. The safety traces (Part B) confirm the machine's own protections stay intact. Every measurement feeds one decision in the board design — none of it is busywork.*

You already did the hard conceptual leap on the bench (telling coils from contacts by resistance). This is the same kind of thinking, now with the power on for a few specific reads. The concepts above are the entire toolkit — there's nothing deeper hiding.
