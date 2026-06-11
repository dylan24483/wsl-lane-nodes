# Phase 8 — Bench Session 1: Orient + Photograph the Spare Cabinet

**For Dylan (comfortable with a meter; new to THIS cabinet).** Goal of session 1 is NOT to fill the whole fieldsheet — it's to **map the schematic to your physical hardware** so that every later "probe here" instruction is exact, not a guess. You'll identify ~8 landmarks, photograph them, and do **two** safe cold-continuity checks. ~30–45 min.

**Output:** a set of labeled photos + 2 readings → I turn those into the precise probe-point list for session 2.

---

## 0. Safety (read once)
- The spare cabinet is **disconnected from the machine and from mains** → all work here is **cold** (continuity / resistance / reading labels). 100% safe to probe.
- **ONE exception:** if it was powered in the last ~5 min, the big filter caps **CP2/CP3** (bottom-center, the two large cylinders) can hold ~150 V. It's been on the bench unplugged for weeks, so this is just hygiene: **don't bridge the CP2/CP3 terminals**, and if you want certainty, meter across each cap on DC volts first and confirm ~0 V.
- Black probe = **chassis frame = ground** throughout (there's no dedicated ground lug).
- Meter: continuity/beep mode + a 200Ω/2kΩ resistance range. That's all session 1 needs.

---

## 1. What the cabinet looks like (from the Omega-Tek Fig-1 map)
Your reference is `Downloads/OmegaTek_Fig1_chassis_map.png` (the drawing of this exact chassis). Landmarks, roughly by position:

| Location in cabinet | What it is |
|---|---|
| **Bottom-right edge** | **C2A** — a **14-pin** connector (2 rows of 7). ⭐ the input connector we care about most |
| Right edge, top→bottom | **T1, T2** (transformers), then relays **S** and **T** (sweep / table) |
| Bottom-center | relays **M2, M, SP** + caps **CP2, CP3** |
| Left edge | relay **BE** (back-end) |
| Top-left | relay **KX** |
| Center | the **Omega-Tek PC-4 board** with two pin-strips labeled **"PIN 1 … 31"** |
| Left of center | **PC-5 cable** + a **+12V** label + a **"CONNECT TO GND"** point |

> **Note:** the Fig-1 map shows **C2A** but does **not** clearly show **C1** (the 34-pin motor/relay connector). Finding C1 physically is one of session 1's jobs — it'll be a larger connector (34-pin) near the relays/transformers or where the thick motor harness enters.

---

## 2. The photo pass (the important part)
Take these shots. For each: get it **square-on, in focus, well-lit**, and include enough surrounding area that I can see how it sits relative to neighbors. Name them as listed (or just tell me which is which when you send).

**A. `cab_overview` — the whole open cabinet, straight on.** One wide shot so I can map everything to the Fig-1 drawing. If the cabinet is deeper than one shot, take 2–3 overlapping.

**B. `cab_C2A` — the C2A connector, close.** Bottom-right edge, the 14-pin (2×7) connector. **Critical detail:** get close enough to see any **numbers, letters, or a triangle/notch molded into the connector body** at one end — that tells us which physical pin is pin 1. If wires are attached, shoot the **wire colors entering each position**.

**C. `cab_C1` — the suspected 34-pin connector.** Look for the **largest multi-pin connector** (bigger than C2A), likely where the **thick motor/power harness** enters, near the S/T/M relays. Same close-up of its numbering/notch + wire colors. *(If you can't find one obvious 34-pin connector, photograph the 2–3 biggest connectors you DO see and say "not sure which is C1.")*

**D. `cab_relays` — the relay bank, close.** The row/cluster of relays (KX, M2, M, SP, BE, S, T). I want to read the **part numbers + coil-voltage markings** stamped on each relay/contactor body. If they're small, one shot per relay is fine — label which is which using the Fig-1 positions.

**E. `cab_cams` — wherever the cam switches land.** The cams (SA/SB/SC/TA1/TA2/TB) are microswitches **on the machine**, but their wires terminate in the cabinet (via C2A / the A&MC plug). Photograph any **terminal strip or labeled switch wiring** you can find — look for stamped labels like `SA`, `TA2`, `GS`, `TAC`, `A&MC`. *(May not be obvious yet — shoot anything labeled; we'll sort it out.)*

**F. `cab_labels` — any printed wire-table, sticker, or legend** inside the cabinet door or on the chassis. Old AMF/Omega-Tek cabinets often have a paper wire chart — that's gold if it exists.

---

## 3. Two safe cold reads (while you're in there)
These don't need pin-1 orientation — they answer the single biggest architecture question (**are the motor stops hardwired or logic?**) and confirm ground.

**Read 1 — confirm chassis ground.**
- Meter on continuity/beep.
- Black probe on bare chassis metal (a screw head / frame edge).
- Red probe on the **"CONNECT TO GND"** point shown on the Fig-1 map (left-of-center, near the PC-5 cable).
- **Expect: beep / ~0 Ω.** Report: ____ (beep? resistance?). *(This confirms my ground assumption for every later read.)*

**Read 2 — is C2A pin-numbering ascending which way?**
- Don't trace signals yet — just establish geometry. With the meter on continuity, pick the connector-body end that has a **molded "1" or notch** (from photo B).
- Touch red to that end-pin, black to chassis. Note beep or not. Then the pin at the **other** end. We're not interpreting — just logging so I can correlate with your photos.
- Report which physical end has the marking, and roughly the pin spacing (2 rows of 7? single row?).

---

## 4. Send + next
Send the photos + the 2 readings. From those I'll produce **Session 2: the exact probe-point list** — "black on chassis, red on C2A pin N, expect X" — for the high-value targets in this order (per the fieldsheet priorities):
1. **Safety chain** — is the stop-switch / C.I.S. in series with the motor relay coils? (decides whether we ADD a hardware interlock)
2. **Motor-stop wiring** — does a cam contact physically break a relay coil (hardwired stop) or only feed a board input (logic stop)? ⭐ decides the Pi's real-time burden
3. **C1 pin map** — each motor/relay coil terminal
4. **Coil voltages** — what each relay coil runs on (sets the AEDIKO contact wiring)

> Why photos before probes: the schematic gives me the *electrical* pinout, but only your photos tell me the *physical* orientation (where pin 1 is, which connector is C1, what the relays are stamped). With both, "probe here" is exact — and since this board gets cloned to all 16 pairs, exact matters.

**Honesty:** session 1 produces no fieldsheet numbers yet — it's the map that makes session 2's numbers trustworthy. If you'd rather skip straight to probing, we can, but I'll be saying "the pin the schematic *calls* 31, wherever that physically is on your connector," which is exactly the ambiguity this session removes.
