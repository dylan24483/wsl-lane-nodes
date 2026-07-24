# At-Machine Field Sheet — Beginner's Companion (how to actually do each measurement)

> ⛔ **RETIRED 2026-06 FIELD-SESSION COMPANION — DO NOT EXECUTE ITS B1 TB/SC
> PROCEDURE OR USE IT TO WIRE J_SAFETY.** Cold continuity cannot establish topology
> in the ~21 Ω coil-ladder sneak paths, and lane 21/22 has no dry/independent TB
> pair. Powered 2026-07-07 evidence proved the OEM contacts are parallel
> closed-when-safe and both levers BACK/open kill S/T. Candidate C uses only the
> controlled J_SAFE1-2 jumper, preserves the OEM ladder, and requires per-lane G3
> coil proof. Use the current interlock redesign, lane harness build sheet, and
> Track-B runbook for any new work. The body below is historical procedure context.

**Read this alongside `phase8b_at_machine_fieldsheet.md`.** It answers: exact probe points, how to measure current, how to tell dry-contact vs voltage-sense, where each cam physically is, and step-by-step Parts B & C. Written assuming you've used a multimeter for continuity/resistance (you have) but not much else. No prior current-measurement or live-mains experience assumed.

---

## ⭐ FIRST — good news that shrinks this whole session
Your **bench data already answered most of Part A.** You measured every coil and proved they're all **24 V**: S = 24 VAC (confirmed from the Siemens part number), M/M2 = 80 Ω, SP = 100 Ω, BE = 22 Ω — all fed by the machine's 24 V transformers (T2/T3/T4).

So the live session is mostly **confirming 24 V**, not discovering unknown voltages. That means:
- **A1 becomes a quick confirm**, not a hunt. You're checking "yep, ~24 V" on each, not finding surprise 120 V.
- Less time with hands near a powered machine = safer.
- If every A1 read is ~24 VAC (very likely), the board's isolation spacing can relax — that's the payoff.

**If you do only one thing live: confirm S and one other relay read ~24 VAC. That alone is most of the value.**

---

## METER SETUP (one-time, before you start)
Your multimeter has a rotary dial. You'll use four settings:
- **Ω (ohms / continuity)** — the one you already know. Beeps or shows low number = connected.
- **V~ (AC volts)** — wavy line. For 24 VAC coil circuits. Set range to 200 V (or autorange).
- **V⎓ (DC volts)** — straight line + dashes. In case something's DC.
- **A (amps)** — covered in the current section below. You likely WON'T need this (see A2).

**Probe rule for everything live:** **black probe clipped to bare chassis metal** (a frame screw) and **leave it there**. You move only the **red probe**. This keeps one hand free and gives every reading a common reference. Use an alligator-clip lead on black if you have one — then you're truly one-handed.

---

## A1 — RELAY WORKING VOLTAGE: exact probe points

**The concept in one sentence:** the existing controller energizes each relay's **coil** to make the machine do a thing; we measure the voltage on that coil so we know what our board's contact will be switching.

**Black probe:** chassis ground (clip it, leave it).
**Red probe:** touch the relay's **coil terminal** — the same terminals you already found on the bench. From your bench notes:

| relay | where it is in the cabinet | coil terminals = red-probe point |
|---|---|---|
| **S** (sweep) | upper-right, the **Siemens 3TH40** | **A1** (top) and **A2** (bottom) — the screw terminals your white wires landed on |
| **T** (table) | upper-right, the contactor next to the Siemens | its two coil terminals (the mid-resistance pair you found) |
| **SP** (spot) | lower-center ice-cube relay (100 Ω coil) | its two coil terminals |
| **BE** (back-end) | lower-left (22 Ω coil) | its two coil terminals |
| **M** (master) | lower-center (80 Ω coil) | its two coil terminals |
| **M2** (sweep-rev) | lower-center (80 Ω, identical to M) | its two coil terminals |

**Procedure per relay (this is the [LIVE] part):**
1. Machine powered, **but make the relay actually energize for its function** — e.g. for S, the sweep has to be called. Easiest: have your helper run a normal machine cycle (throw/trigger a ball or use the manual cycle button) while you watch the meter. The coil is only "live" when that function is active, so you're catching it during the cycle.
2. Red probe on **one coil terminal**, black on chassis → read **V~ (AC)**. Note it.
3. If AC reads ~0, switch to **V⎓ (DC)** and read again (some could be DC).
4. **Expected: ~24 V (AC for S, likely AC for the rest).** Write it in the A1 table.
5. **Simpler alternative if catching it live mid-cycle is hard:** measure across the coil terminals (red on A1, black moved to A2 instead of chassis) — same reading, and you can do it the instant the relay clicks.

> **Safety:** you're touching **low-voltage coil terminals (~24 V)** — uncomfortable but not dangerous. **Do NOT** probe the fat motor wires or the 115 VAC input. If you're not sure which terminals are the coil vs the motor contacts, the coil terminals are the **thin wires**; the motor contacts are the **thick/heavy wires**. Stay on thin.

---

## A2 — HOW TO MEASURE CURRENT (you probably don't need to — read this first)

**You likely can skip A2.** Here's why: the board's relay (G5LE) has a **10 A contact**, and these coil circuits draw well under 1 A (a 24 V coil at 22–100 Ω pulls ~0.25–1 A; the Siemens AC coil a bit more on inrush). 10 A >> 1 A by a huge margin, so the contact is fine **without** an exact number. **Recommended: skip the live current measurement; note "coil circuits, <1 A, G5LE 10 A contact = ample" and move on.** Less risk, and the rating decision doesn't actually need the precise number.

**If you want the number anyway, here's how — and the safe way vs the risky way:**

Current is different from voltage: to measure voltage you *touch two points* (parallel). To measure current the old way you must **break the circuit and insert the meter in line (series)** — that means disconnecting a wire, which on a live machine is fiddly and easy to get wrong. **Don't do that.**

**Use a clamp meter instead (the safe, no-contact way):**
- A **clamp meter** has a hinged jaw. You open the jaw, put it **around a single wire** (just one — the coil's hot lead), close it, and it reads the current flowing through that wire **without touching anything**. No breaking the circuit, no disconnecting.
- Set it to **A~ (AC amps)**, clamp around **one** coil wire (not both — both cancels out), run the cycle, read the number during the moment the relay is energized.
- ~$30 clamp meter is the right tool; if you don't have one, **skip A2** (the G5LE 10 A margin makes it non-critical).

**Bottom line for A2:** skip it unless you happen to own a clamp meter. The relay rating is safe either way.

---

## A3 — MASK LAMP SUPPLY (same method as A1)
The status lamps (1st-ball, 2nd-ball, strike, foul) are on the **mask** (the lit panel above the pins). Their supply is brought to the mask connector.
- **[LIVE]:** black on chassis, red on a **lamp terminal at the mask connector** while that lamp is lit (run a cycle that lights it, or it may be on at rest).
- Read V~ then V⎓. **Expected ~12 VDC** (per the manual). Note voltage + which (AC/DC).
- That's it — current here you can eyeball: small indicator lamps, well under the PhotoMOS rating. Don't bother clamping.

---

## A4 — DRY-CONTACT vs VOLTAGE-SENSE: the simplest test

**What this question means in plain terms:** every input (a cam, a gripper, a switch) tells the controller "I'm active" in one of two ways:
- **Dry contact** = it's just a **switch**. When active, it connects two wires together (continuity). No voltage of its own. Like a light switch.
- **Voltage-sense** = when active, a **voltage appears** on the wire (e.g. 24 VAC shows up).

**The test — do it in this order:**

**Step 1 (LOCKED OUT, safe): is it a dry contact?**
- Meter on **Ω / continuity**.
- Put one probe on the input's wire/terminal, the other on chassis ground (or the input's common).
- **Actuate the input** (trip the cam by hand, lift the gripper, press the button).
- **If the meter goes from open (OL) to ~0 Ω (beep) when you actuate → it's a DRY CONTACT.** Done. Mark "dry."

**Step 2 (LIVE, only if Step 1 showed no continuity change): is it voltage-sense?**
- Meter on **V~ (AC)**, black on chassis, red on the input wire.
- Actuate / run the machine so the input goes active.
- **If a voltage appears (e.g. ~24 V) when active → it's VOLTAGE-SENSE.** Mark "AC, ___V."

**That's the whole test.** Most machine switches are dry contacts (Step 1 catches them). You only go live (Step 2) for the ones that *don't* show a continuity change.

---

## WHERE EACH CAM PHYSICALLY IS

**What a cam switch looks like:** a small **microswitch** (lever or roller arm, ~1 inch, 2–3 wires) mounted so a rotating **cam lobe** (a bump on a disc/shaft) pushes the lever once per revolution. You're looking for little switches with a roller riding on a shaft-mounted disc.

**The 6 cams live on two shafts:**

**SWEEP cams (SA, SB, SC)** — on the **sweep drive**, which is the mechanism that swings the sweep bar (the rake that clears dead wood). Find the **sweep motor** (front-end, drives the sweep), follow its shaft — the cams ride on that shaft / its gearbox output. There are 3 microswitches clustered there:
- **SA** = stops sweep (the 270°/zero one)
- **SB** = the guard-stop (66°)
- **SC** = the interlock cam (sweep-under-table)

**TABLE cams (TA1, TA2, TB)** — on the **table drive**, the mechanism that lowers/raises the spotting table (the part that sets pins). Find the **table motor**, follow its shaft — 3 microswitches there:
- **TA1** = table zero/355°
- **TA2** = run-through/260° (the pin-read trigger)
- **TB** = the interlock cam (table-sweep interference)

**How to confirm which is which (you don't have to ID them perfectly at the machine):** for the harness map (Part C) you'll trip each one and watch which C2A cavity reacts — that *tells* you which is which, so you don't need to read tiny labels in the machine. Just find "the cluster of ~3 microswitches near the sweep motor" and "the cluster of ~3 near the table motor."

> **Reference:** the AMF "Front End" parts manual (`Downloads/Pinspotters 82-70_Front End.pdf`) has the sweep + table drive exploded views (pages 2, 8) if you want to see the assemblies. But honestly, finding "3 microswitches on the sweep shaft / 3 on the table shaft" by eye is faster than the diagram.

---

## PART B — SAFETY-ARCHITECTURE CHECKS (step by step)

These confirm the machine's existing safety wiring so our board plugs in without defeating it. **All can be done LOCKED OUT (safe).**

### B1 — TB/SC interlock: how it's wired
**Plain meaning:** TB and SC are the two "collision" cams. If the table and sweep are ever about to hit each other, this interlock cuts power to both motors. We need to see how it's wired so our board's safety connector matches it.
**Steps (LOCKED OUT):**
1. You already located TB (table shaft) and SC (sweep shaft) above.
2. Meter on **continuity**. Probe across the TB switch terminals; hand-rotate so TB trips. Confirm it **opens** (goes from beep to open) when tripped — that's a "normally-closed, opens-on-danger" switch. Note: TB opens when tripped? Y/N.
3. Same for SC. Note: SC opens when tripped? Y/N.
4. Trace where their wires go: do TB and SC connect **together** (in parallel) and then into the 24 V control line? Follow the two wires; if they join, that's the parallel interlock. Photograph the junction.
5. **What to send me:** "TB opens Y/N, SC opens Y/N, they join at ___ , photo attached." That's enough for me to wire our J_SAFETY connector correctly.

### B2 — Are the motor stops hardwired or done by the board?
**Plain meaning:** when a cam says "stop," does it cut the motor *directly* (hardwired), or does it just tell the controller, which then stops the motor (logic)? Affects whether we keep a bonus hardware backstop.
**Steps (LOCKED OUT):**
1. Meter on continuity across the **S relay coil terminals** (from A1).
2. Hand-rotate the sweep so the **SA cam** trips.
3. Watch the meter: does the **coil circuit open the instant SA trips** (→ hardwired), or does nothing change at the coil (→ the board does it = logic)?
4. Note: "SA trip opens S-coil directly? Y/N." Repeat with a table cam + T-coil if easy.
5. (Expected: logic — nothing changes at the coil. Either answer is fine; it's informational.)

### B3 — Stop button / safety chain
**Plain meaning:** confirm the big Stop switch actually kills motor power in series (it should).
**Steps (LOCKED OUT):**
1. Find the machine's **Stop switch** (and the C.I.S. safety switch if present).
2. Meter continuity from the **motor-relay coil supply** to the **power-in**, through the stop switch.
3. Flip Stop to STOP → continuity should **break**. Flip to RUN → continuity returns.
4. Note: "Stop breaks the coil supply? Y/N." (Should be Y.)

---

## PART C — HARNESS MAP (which machine wire = which board signal)

**Plain meaning:** our board has function-named inputs (GS1, SA, etc.) but the actual machine wires land on the C2A connector in some order we haven't mapped. This is where we map "machine signal → C2A cavity." Now that the machine's here, we can **actuate each input and watch which cavity reacts** — impossible on the dead bench, easy now.

**The universal method for all of Part C (LOCKED OUT):**
1. Meter on **continuity**, black on the input's **common/return** (or chassis).
2. Red probe on a **C2A cavity**.
3. **Actuate the one input you're testing** (lift a gripper / trip a cam by hand / press a button).
4. Sweep the red probe across C2A cavities until you find the one that **changes** (open↔closed) exactly when you actuate. **That cavity = that signal.** Record it.

### C1 — the 10 grippers (GS1–GS10)
The grippers are the little fingers on the spotting table that grab pins. Lift/squeeze **one** by hand → find the C2A cavity that closes → that's that GS number. Repeat for all 10. (Tedious but mechanical. Record GS1→cavity, … GS10→cavity.)

### C2 — the 6 cams
Hand-rotate the sweep/table so **one** cam trips → find the C2A cavity that changes → that's that cam. You'll also learn which cam is which this way (the one that trips at the sweep-stop position is SA, etc.). Record each.

### C3 — GP / OS / BS / Foul / PBZ / PBC
Actuate each (GP/OS/BS are machine switches you trip by hand; PBZ/PBC are operator buttons you press; Foul you can simulate at the foul unit) → find its C2A cavity. Record each.

> **Part C is the most time-consuming and the LEAST safety-sensitive** (all locked-out continuity). If you run low on time/energy, do the grippers (C1) first — they're the scoring-critical 10 — and let cams/switches trickle.

---

## YOUR REALISTIC PLAN (priority + safety)
1. **A1 confirm (LIVE, ~15 min):** S + one or two others read ~24 VAC. ← the payoff measurement. Helper runs cycles; you watch the meter; black clipped to chassis.
2. **A3 (LIVE, 5 min):** mask lamp voltage.
3. **A4 (mostly LOCKED OUT):** dry-vs-AC on the cams/switches — Step 1 continuity catches most.
4. **B1/B2/B3 (LOCKED OUT):** the three safety traces.
5. **C1 grippers (LOCKED OUT):** the 10-gripper map. C2/C3 if time.
6. **Skip A2** unless you own a clamp meter.

**Send me:** filled tables (photos of your jottings are fine) + photos of the TB/SC junction, the mask lamp point, and any contactor nameplate. I'll turn A1 into the final board spacing, A3 into the lamp part, B into the safety wiring, C into the harness pinout.

**You've got this.** It's a lot of small, individually-simple steps — none of it is harder than the bench resistance work you already did well. The only genuinely "live" parts are A1 and A3, and those are low-voltage coil/lamp terminals with one hand in your pocket.
