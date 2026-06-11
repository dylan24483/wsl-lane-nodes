# JOB 2 — Are the Motor-Stops HARDWIRED or LOGIC? (full field list)

> ## ✅ STRONG ANSWER BY INSPECTION (2026-06-01): LOGIC stops (board photo)
> The Omega-Tek board's top-rail screw strip photo shows the **driver stage**: a vertical bank of **`S2003LS2` TO-220 TRIACs** (Teccor/Littelfuse sensitive-gate ~4 A triacs), one per output terminal, **gated by CMOS logic (`MM74C…` DIPs) via 4-pin SIP resistor networks**, with an **`LM340T5`/7805** 5 V reg for the logic. → Each coil output (S, T, SP, lamps) is switched by an **on-board triac the logic gates** — i.e. **cams → logic ICs → triac → coil = LOGIC control.** A hardwired cam-in-series-with-coil design wouldn't need a logic-gated triac bank. **This matches the manual's MP-chassis model.** The probe test below now just CONFIRMS (and checks for any exception).
>
> **⚠️ THIS CHANGES THE RESISTANCE RULE for the board side:** an output triac reads **OPEN (high) in both directions when off** (it's a semiconductor, not a wire). So probing a coil tag toward the board will NOT read 0 Ω even though it's connected through the triac. "No 0 Ω to the board" is EXPECTED and CONSISTENT with logic control — not a failed probe. The elimination test (coil tag → C2A, looking for a 0 Ω wire to a cam) is unaffected and still the clean check.

**For Dylan, spare cabinet, all COLD (unplugged), continuity + 200 Ω resistance.** This is THE architecture question: when a cam reaches its stop angle, does it **physically break the motor-relay coil** (hardwired), or does it just **tell the Omega-Tek board**, which then drops the relay (logic)? The answer sets the Pi's real-time burden and the safety-rail design.

> **Why this trace avoids C2A pin numbers:** we don't have verified C2A cam-pin IDs (the 225-DPI codes are guesses). So instead of chasing "cam pins," we trace **outward from the relay coils** (which you've already found) to see WHAT DRIVES them. That answers the question directly and uses only anchors you can see.

> **Expected answer (so you know if a reading is sane):** SS/Omega-Tek chassis almost certainly = **LOGIC** (cams → board inputs → board's amplifier drives the coil). The manual says the MP chassis works that way; we're verifying the Omega-Tek does too. So I *expect* each motor coil to be driven by the board, not broken by a cam in series. If you find a cam directly in a coil circuit, that's a surprise worth a double-check.

---

## THE ANCHORS — where each probe point physically is

### Anchor 1 — the Omega-Tek board's S/T connections ⭐ (access note added)
The `T S X 2B 1B` labels are on the **black legend plate at the board's edge**; **S and T are rows on the board's EDGE CONNECTORS** (the black multi-pin connector bodies). Dylan found: these connectors have **two rows (rails); the S row is on the BOTTOM rail, squeezed against the board → hard to probe directly.**
- **⭐ You usually do NOT need to touch the board S/T pin at all** — use the **ELIMINATION test (Test A, revised below):** prove the S coil does NOT go out to a C2A cam, which means it MUST be board-driven (logic). That sidesteps the access problem entirely.
- If you DO want the board connection directly, two easier routes than the squeezed front pin: (a) **the wire on that pin is the SAME wire that lands on the S-coil switched tag** — so probe continuity along the board's wire BUNDLE where it's accessible, not the pin; (b) **the solder side of the board** (back), if the board can be safely tilted/unscrewed.

### Anchor 2 — the S relay coil (you've found this)
**Siemens 3TH4022, terminals A1 (top) / A2 (bottom)** — the 5 Ω pair. This is S (sweep).

### Anchor 3 — the T relay coil (unlabeled contactor — ID by resistance)
T is an **open-frame "tombstone" power contactor** (AMF/Arrow-Hart style), NOT a Siemens — so **no A1/A2 stamps.** Find its coil:
- The **4 big copper crosshatched saddle terminals** at the corners = **POWER POLES** (switch 115 V motor current; thick leads bolt here). **NOT the coil.** A pole pair reads 0 Ω (closed) or open — never mid-value.
- The **coil = the one pair of SMALLER terminals** (thinner wires, off to the side/base, away from the 4 copper pads) that reads a **steady mid-value (~tens–hundreds Ω;** the T-family coils measured 80–100 Ω earlier). **The resistance IS the label** — the only pair reading mid-Ω is the coil = "T's A1/A2."
- **100%-sure confirm (optional):** meter the candidate pair, gently press the armature (black crossbar) by hand — coil reading stays steady; a CONTACT pair would switch. Steady mid-Ω = coil.
- Then trace those two coil leads to wherever they land (likely strip tags, like the Siemens) and probe THOSE → C2A.

### Anchor 4 — the L-plate = a multi-lug TERMINAL/TAG STRIP  ⭐ (confirmed by Dylan's plate photos)
Confirmed: the "L-shaped plate" is a **row of ~8 solder/spade tags** on a bracket — the **control-wiring distribution strip** (cloth-covered orange/yellow/brown/grey/red/green wires land on individual tags). Below it is a **small 2-winding transformer/choke** (red+green leads) = likely **T2/T3, the 24 V control supply** (separate from the big enclosed T1). Both Siemens **A1 and A2 land on SEPARATE tags** of this strip.
- **Probe the TAGS**, not the transformer. Each tag = one node.
- ⚠️ **FRAGILE:** old cloth-insulated wire on aged solder tags — **rest the probe, don't tug/pry.** 
- **First, visually trace A1's wire and A2's wire down to WHICH specific tag each lands on** — then meter those two tags. (Photos: the 3 plate close-ups 2026-06-01.)

### Anchor 5 — C2A connector (the RIGHT 4-column one)
The cams enter here. We treat it as "the place cam wires land" — we'll note IF a coil terminal reaches any C2A cavity, but we don't need to pre-identify which cavity is which cam.

---

## TEST A — How is the S (sweep) coil driven?  ⭐ core test
Goal: find whether the S coil's controlled side goes to the **board** (logic) or out through a **C2A cam** (hardwired). Probe **from the two plate terminals** where A1's and A2's wires land (Anchor 4).

**A1 — confirm the two plate landings are the coil's two ends.**
- Probe **A1's plate-landing → A2's plate-landing.**
- **Expect ~5 Ω** (= across the coil → they're two separate terminals, one supply, one switched). If **0 Ω**, they're the same node (unusual — tell me).
- Record: A1-landing↔A2-landing = ____ Ω.

**A2 — ELIMINATION test: does either S-coil tag go OUT to a C2A cam?**  ⭐ THE tell (no board pin needed)
Since the board S-pin is hard to reach, prove logic-vs-hardwired by ruling out the cam path. Probe **both S-coil tags → the C2A connector** (sweep ALL its cavities — C2A is reachable):
- **NEITHER S tag connects to any C2A cavity** → the S coil is NOT broken/switched by a machine cam → it MUST be **board/logic-driven → LOGIC stop.** ✅ (this is the expected result, and it's a complete answer — board never touched)
- **One S tag hits a C2A cavity at ~0 Ω** → a cam may be in series with the coil → possible **HARDWIRED.** Record which cavity + Ω: ____ . (Flag it — we dig in.)
- Record: A1-tag→C2A any hit? ____ · A2-tag→C2A any hit? ____

**A3 — (optional, only if you want board confirmation) reach the board connection the easy way.**
- The wire on the board's S-pin is the SAME wire on the S-coil switched tag. So probe the **switched tag → the accessible wires in the board's ribbon/connector BUNDLE** (where they leave the board), NOT the squeezed pin. A hit confirms board-driven.
- Or probe the **solder side** of the board if you can tilt it safely.
- Skip this if A2 already gave a clean "no C2A connection" — that's sufficient.

---

## TEST B — How is the T (table) coil driven?  ⭐ core test
Repeat Test A exactly, for the **T contactor coil** (Anchor 3) and the board finger labeled **`T`**.
- **B1** — T supply side = ____, switched side = ____ (probe each T coil terminal → 24 V transformer).
- **B2** — T switched-side → board `T` finger = ____ Ω (beep? Y/N). *(beep = LOGIC ✅)*
- **B3** — T switched-side → C2A cavities = ____ (any hit? which, Ω).

---

## TEST C — supply-rail sanity (quick, confirms the model)
Confirms the coils share a common 24 V supply (so only the *switched* side is interesting).
- Probe **S supply-side → T supply-side.** Beep? ____ (expect Y — common 24 V rail).
- Probe **S supply-side → M2/SP coil supply sides** (the ones you found earlier). Beep? ____ (expect Y).
- Record anything that does NOT share the rail.

---

## TEST D — (STRETCH, only if you have appetite) the interlock cams SC + TB
SC and TB form the **collision interlock** (TB+SC in parallel) — the one piece of cam logic we specifically want to confirm is **hardware** (we preserve it). This is harder because we can't ID SC/TB pins for sure, so treat as optional:
- The interlock should drop **both** S and T coils on a collision course. So look for a switch/contact path that, if opened, kills BOTH coil circuits at once.
- Practically: is there a single point (a relay contact, a terminal) that is **in series with BOTH the S and T supply rails**? Probe the S supply rail and T supply rail back toward the transformer — do they pass through a **common contact** before the transformer? ____
- If yes, that common contact is likely the interlock/safety drop point (hardware). Photograph it. If you can't find it, **stop — that's a great at-the-machine item later**, not a bench dead-end.

---

## HOW TO READ YOUR RESULTS (you can self-interpret)
- **S & T switched sides both reach the board (`S`/`T` fingers), NOT a C2A cam → LOGIC stops.** ✅ The board reads the cams and drives the coils. → Our design's RP2040-times-the-cam-stop + hardware end-stop plan is correct; the cams are board inputs.
- **A switched side goes through a C2A cam in series with the coil → HARDWIRED stop** for that motor. → Even better (machine cam can drop the relay directly); we preserve that path. Flag which.
- **Mixed / weird / can't tell → just send the raw "reaches X at Y Ω" for each coil terminal + a photo of the board edge.** I'll interpret — don't force a conclusion.

## WHAT TO SEND ME
1. **Test A:** S supply vs switched side; switched-side → board finger (Ω); switched-side → C2A (any cavity/Ω).
2. **Test B:** same three for T.
3. **Test C:** do the coil supply sides share a rail? (Y/N each)
4. **Test D (if attempted):** any common contact in series with both S & T supplies.
5. Anything surprising + a photo of the board's labeled edge so I can confirm the finger labels.

## IF YOU HIT A WALL
Stop and send whatever you got. The **single most valuable result is Test A2 + B2** (do the coils reach the board's S/T fingers?) — that one pair of readings answers logic-vs-hardwired for the main motors. Everything else is confirmation. Even just A2+B2 is a complete, useful session.
