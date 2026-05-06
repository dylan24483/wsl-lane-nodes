# Lane 22 Characterization Visit Checklist

**Purpose:** capture every signal characteristic the bench rig couldn't tell us, so the Pi adapter cable + cutover procedure can be finalized with zero unknowns.

**This visit does NOT cut over to the Pi.** Nothing is disconnected from the SIX BOX. Pure measurement + documentation. Cutover happens in a separate visit after these findings are reviewed.

**Estimated time on-site:** 60-90 minutes.

---

## Before leaving home

**Kit to bring:**
- [ ] Multimeter (the bench one is fine — we just need go/no-go for AC vs DC and rough voltage)
- [ ] Insulated test leads with alligator clips (hands-free probing)
- [ ] Sharpie + masking tape OR pre-printed labels
- [ ] Phone with camera (every photo geo-tagged + timestamped helps later)
- [ ] Flashlight or headlamp (cabinet interior is dim)
- [ ] Small notebook (write readings as you take them, don't trust memory)
- [ ] A few short jumper wires with alligator-clip ends
- [ ] Laptop with this checklist open OR phone set to dark mode for reading at the lane
- [ ] AnyDesk to WSL-SRV ready (for live cross-checking against any Conqueror / Qubica state)
- [ ] Bowling ball (for triggering foul + cycle empirically)

**Pre-visit reads (5 min refresher):**
- [ ] `project_phase8_full_hardware_replacement.md` — DEFINITIVE PHASE 8 TAP POINT section (SIX BOX terminal layout)
- [ ] `project_phase8_bench_rig_validated.md` — what we already know works on the bench
- [ ] T-VISION install manual — pages on SIX BOX terminals + sweep reverse mod (pp. 20-22)

---

## Order of operations on-site

### Phase 1: Static documentation (~10 min) — gear OFF or normal idle

Goal: capture the as-installed state before any probe touches anything. If something gets miswired during the visit, we have the original to revert to.

1. **Photograph the entire equipment area** — wide shots from each side. Pinsetter cabinet, SIX BOX, BCU II, T-VISION, VDB-99, junction boxes. ~6-8 photos.
2. **Photograph each Qubica module's labels close-up** — model number, serial, voltage selector. We may already have these from the May 1 walk, but confirm nothing's been swapped.
3. **Photograph the SIX BOX terminal block straight-on, close enough to read every silkscreen label.** This is the single most important photo of the visit. If the camera can't capture every wire color clearly in one shot, take 3-4 overlapping shots.
4. **Label every wire entering the SIX BOX** with masking tape + Sharpie BEFORE any disconnect or probing. Use the convention: `J1-A` through `J1-D` for J1 terminals, `J2-A` through `J2-D` for J2, plus `J3-1` through `J3-4` for the L-COM. (Labels go on the wire just outside the terminal, where they won't fall off if the wire is wiggled.)
5. **Trace each labeled wire back to where it goes** (8270 cabinet, foul lamp circuit, A&MC junction, T-VISION, BCU II). Note which wire goes where in the notebook. A simple table is fine:

| Label | Wire color | Goes to | Function (best guess) |
|---|---|---|---|
| J1-A | red | 8270 cabinet | Cycle output |
| J1-B | blk | 8270 cabinet | Cycle return |
| ... | ... | ... | ... |

### Phase 2: Voltage characterization with system idle (~15 min) — gear powered on, NOT bowling

Goal: measure the resting-state voltage on each SIX BOX input terminal. This tells us the voltage class and AC vs DC type.

**Safety:** Pinsetter cabinet has 110V AC inside. Stay on the SIX BOX terminals — those are the low-voltage logic signals (10-40V per T-VISION specs). Do NOT probe inside the 8270 chassis.

For each of the **4 inputs** (Lane 1 Foul, Lane 1 2nd-Ball, Lane 2 Foul, Lane 2 2nd-Ball):

6. **Set multimeter to DC volts**, autoranging or 200V scale. Probe across the terminal pair (e.g., Foul Lane 1 `+` to Foul Lane 1 `-`, or terminal-to-ground if it's single-ended).
7. **Record the reading.** If it's stable at some DC value (e.g., +24V or 0V), it's DC. If it bounces between positive and negative numbers, it's AC.
8. **Switch to AC volts.** If the AC reading is significant (e.g., 24V AC) AND the DC reading was bouncing, confirms AC.
9. **Note in the table:**

| Terminal | Idle DC | Idle AC | Verdict |
|---|---|---|---|
| L1 Foul | 0.0V | 24.1V | **AC** |
| L1 2nd-Ball | 0.0V | 24.0V | **AC** |
| L2 Foul | ... | ... | ... |
| L2 2nd-Ball | ... | ... | ... |

**This is the gate-keeping measurement of the entire visit.** If any input is AC, the AL-ZARD board needs rectifier interposers (4× 1N4007 + bridge per channel, ~$5 of parts) OR replacement with an AC-tolerant input module before any cutover.

### Phase 3: Active-state characterization (~15 min) — bowl a frame

Goal: confirm the same terminals show a different voltage when the actual signal is asserted (foul lamp lit, ball-2 indicator on, etc.).

10. **Set up:** clip multimeter probes on Lane 1 Foul terminals, leave hands-free.
11. **Trigger a foul** by manually breaking the foul beam (wave a hand across it OR roll a ball through and step over the line). Watch the multimeter reading change.
12. **Record the asserted reading** (e.g., 0V → 24V AC, or 0V → +24V DC).
13. **Repeat for L1 2nd-Ball:** bowl a first ball (any pin count). When the second-ball lamp lights, the input asserts. Read it.
14. **Repeat for L2** (foul + 2nd-ball) on the other lane.

Update the table:

| Terminal | Idle | Asserted | Class |
|---|---|---|---|
| L1 Foul | 0V AC | 24V AC | AC |
| L1 2nd-Ball | 0V AC | 24V AC | AC |
| L2 Foul | ... | ... | ... |
| L2 2nd-Ball | ... | ... | ... |

### Phase 4: DIELL sensor characterization (~10 min)

Goal: confirm whether the DIELL LSC/AN-2C6J photoelectric sensors are NPN or PNP output, and what voltage their output line carries when triggered.

15. **Trace the DIELL sensor cables** from each sensor (mounted on the kickback) back to where they terminate. Per the May 1 walk, they likely land on QBK-SIx J1 or J3.
16. **Photograph the termination points** and label each conductor.
17. **DIELL part number on the sensor:** confirm it reads `LSC/AN-2C6J` (`AN` = NPN per DIELL convention; `AP` = PNP). If the suffix is different, look up the datasheet.
18. **Empirical test:**
    - Disconnect the sensor's output wire from QBK-SIx (one wire only — leave power + ground intact).
    - Probe between the loose output wire and ground, multimeter on DC volts.
    - **Untriggered (beam unbroken):** read voltage. NPN sensor reads ~0V (open-collector pulled to GND when active). PNP sensor reads supply voltage (sourcing).
    - **Triggered (break the beam with your hand):** voltage should flip (NPN → supply voltage, PNP → 0V).
    - Reconnect immediately after.

| Sensor | Suffix | Untriggered voltage | Triggered voltage | Verdict |
|---|---|---|---|---|
| LEFT | AN | 24V | 0V | NPN open-collector |
| RIGHT | AN | ... | ... | ... |

If they're NPN: Pi side needs a pull-up to +V on the input line. If PNP: connects directly to opto-input board's `+/-` pair (or to Pi GPIO via voltage divider).

### Phase 5: Sweep reverse test (~10 min)

Goal: confirm whether the 8270 currently does sweep-reverse on incomplete first-ball clears (gutter ball, 7-pin only, 10-pin only). Per T-VISION pp. 20-22, older 8270s without original AMF scoring may need a C-1 jumper mod to enable sweep reverse.

19. **Set up the lane for fresh first-ball** (ensure full rack, no existing ball-2 state).
20. **Roll a gutter ball** (down the channel, no pins hit). Watch the sweep:
    - If it sweeps **forward only** (toward the pit) → no sweep reverse. C-1 jumper mod needed.
    - If it sweeps **forward then reverses** (back through the pit area) → sweep reverse working.
21. **Roll a 7-pin only** (left side, knocking down only the 7-pin). Same observation.
22. **Roll a 10-pin only** (right side). Same observation.
23. **Note in the notebook:** which scenarios trigger sweep reverse, which don't. Photograph the sweep mechanism mid-cycle if possible.

If the C-1 jumper mod is needed, that's **not a Phase 8a cutover task** — it's a separate mechanical/electrical job to do at any time. Don't attempt it during this visit; just note it.

### Phase 6: Infrastructure check (~5 min)

24. **Network drop at the lane:** Is there a Cat6 jack within reach of the equipment area? Is the upstream switch a PoE+ model? Note the make/model.
25. **Power infrastructure:** Is there a 12V or 24V DC rail accessible (T-Camera supply, BCU II 18V output, etc.)? Or do we need to add a Pi-dedicated PSU?
26. **Physical mounting:** Is there room for an industrial enclosure (DIN-rail, 6-8" wide × 4-6" tall) near the 8270 cabinet for the Pi node? Photograph candidate locations.
27. **Cable routing:** Is the existing Qubica wire harness in conduit, or run loose? Determines whether we need to fish new cable or reuse paths.

### Phase 7: Reset + leave (~5 min)

28. **Confirm everything is back to as-found state.** All wires connected the way they were. All Qubica gear powered up. Pinsetter operating normally.
29. **Roll a test frame** on each lane in the pair to confirm normal operation. Foul detection, ball count, pin count, scoring all working.
30. **Photograph the equipment area one final time** for "as-left" documentation.
31. **Pack up. Don't leave alligator clips or test leads on any terminal.**

---

## Decisions gated by visit findings

After the visit, we'll have answers to:

1. **AC or DC on the foul / 2nd-ball inputs?**
   - DC → AL-ZARD board works as-is, no hardware changes.
   - AC → add rectifier interposers (4× 1N4007 + bridge per channel) OR replace with AC-tolerant module before cutover. Order parts before the cutover visit.

2. **DIELL sensors NPN or PNP?**
   - NPN → Pi GPIO needs an external pull-up to 3.3V (10kΩ from input pin to 3.3V). One resistor per sensor.
   - PNP → connect directly to AL-ZARD opto-input via voltage divider (24V → 3.3V), or to Pi GPIO via direct voltage divider.

3. **Sweep reverse working?**
   - Yes → no action.
   - No → C-1 jumper mod scheduled as separate mechanical task. NOT a cutover blocker — Phase 8a can ship without sweep reverse, fix it in a follow-up visit.

4. **Network + power available at the lane?**
   - PoE+ → use PoE HAT, single-cable install.
   - Cat6 only → Pi PSU + Cat6, two-cable install.
   - No network → upstream switch upgrade needed before Phase 8a.

5. **Mounting space available?**
   - Yes → spec the enclosure size for ordering.
   - No → mount Pi inside the existing 8270 cabinet (verify thermal + EMI tolerable).

---

## Post-visit deliverables

Within 24 hours of the visit, update memory:

- [ ] Add findings to `project_phase8_full_hardware_replacement.md` under a new "## Lane 22 characterization (2026-XX-XX)" section
- [ ] If AC on inputs: add `project_phase8_input_frontend_redesign.md` memory + parts order
- [ ] If sweep reverse missing: add to followup queue in CLAUDE.md
- [ ] Photo dump → `~/wsl-lane-nodes/docs/lane22_photos/` (gitignore the directory if photos are private)

---

## Red flags during the visit (stop and reassess)

- **Voltage on a logic input >40V**: outside SIX BOX spec, something is wrong. Don't probe further.
- **Sparking / heat / burning smell**: power down everything immediately.
- **Wires you can't trace** (mystery cables): photograph and note, don't disconnect.
- **Anything that looks like Qubica's documentation contradicts what's installed**: photograph before assuming the docs are wrong. Both are possible — Qubica retrofits over decades introduce field variations.

If something feels off, take more photos and leave it for analysis. Cutover is a separate visit; we're not under time pressure to fix things on the spot.
