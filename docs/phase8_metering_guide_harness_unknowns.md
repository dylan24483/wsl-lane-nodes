# Metering Guide — Closing the Section F Harness Unknowns (REVISED)

**Most of the bench work is already done** (2026-06-01 spare-cabinet session). This revision marks what's confirmed and foregrounds the short list that actually remains — which is essentially **"trace the C2A input cavities at the machine."**

---

## ✅ Already CONFIRMED (2026-06-01 bench) — do NOT re-measure

- **Connectors ID'd, P/N read:** AMP **67209 / 67211** ("1-0 series", molded). **C1 = LEFT 34-pin** (3-col, rows A…NN + 2 large power pins), **C2A = RIGHT 50-pin** (4-col). Pin-1 datum = the **"01" + AMP** end on each. *(Open only: confirm housing-vs-contact P/N + contact gender when ordering the mates — or skip it and go Path B taps.)*
- **Output relay → connector map:** S→C1 **(C,D,N,T)** · T→C1 **(A,K,H,E,+L)** · M2→C2A · SP→C2A · M→C2A **(FF,U,B)** · BE→C1 (KK,C,L + coil FF@66Ω) + C2A. (S = C not J; T = L not P — both corrected.)
- **Coil voltages:** Siemens 3TH4022 = 5Ω = **24 VAC** · M/M2 (82-70-5515) = 80Ω · SP = 100Ω · BE = 22Ω (all ~24 V native) · P&B JRM-10110 = **12 VDC**.
- **Cam-stop topology:** the Omega-Tek board is a triac + CMOS driver bank → **LOGIC stops** (cams route *through the board*, not hardwired in series with the coils). This **confirms the plan** — the Pi/RP2040 times the stops and we add hardware end-stops. (A final at-machine cam-flip proof is a nice-to-have, not a build gate.)

---

## 🔵 What's REMAINING (the real list)

### ✅ Confirmed at the machine (2026-06-27)
- **Grippers (drop-a-pin):** GS1=**C** · GS2=**H** · GS3=**M** · GS4=**S** · GS5=**W** · GS6=**a** · GS7=**e** · GS8=**TBD (recheck)** · GS9=**r** · GS10=**v**. (GS1–5 match the schematic; GS6–10 resolve/correct it — the old GS8=48H collided with GS2=H, and GS10=U is a common, both wrong.)
- **PBZ** (zero button) **→ EE** (shorts to common U when pressed).
- **BS** (#9 bin) **→ CC.**
- **SC** (interlock) **→ U.** · **TB → none** (interlock-only, shares the U node).
- **Common/ground rails — ignore these, they ring to everything:** **J, F, U** (gripper/control common, chassis return) + **N** (the 5-cam motion common).
- **Deferred to powered cutover:** motion cams **SA / SB / TA1 / TA2** (buried in the relay ladder — a clean one-read each once powered).
- **Still open:** GS8 (recheck) · GP (gripper-protect) · OS / PBC / 10th / MAN_* (spare/future) · Foul · DIELL re-check.

### ★ 1. C2A INPUT cavity digits — the one true blocker (AT THE MACHINE, cold)
This is the only substantial job left. The cams/grippers/switches live on the **machine**; their wires reach the cabinet through C2A.

**The reach problem + the fix.** C2A is in the cabinet, the cams are out on the mechanism — too far for two meter probes. **Don't buy long probes — use a long extension lead.** Grab **~25 ft of stranded hookup wire with an alligator clip on each end** (or chain 2–3 alligator test-lead sets — about $10). Clip one end to the device's signal terminal at the machine, run the wire back to the cabinet — you've now "brought" that terminal to you, and **both meter probes work at the cabinet**: one on the long lead (= the device), the other sweeping C2A.

**Procedure (per device, cold, continuity/beep):**
1. **Anchor** the long lead's clip on the device's **signal terminal** (per-type guide below). One device at a time — label the clip so you don't lose track.
2. **Sweep at the cabinet:** one meter probe on the long lead; with the other, **back-probe** the C2A cavities (a back-probe pin slides in beside the wire from the rear — no need to un-mate). The cavity that **beeps** is the pin. *(Or un-mate C2A and probe the cabinet-side cavities directly — same cavity number either way.)*
3. **Confirm (cams):** rotate the mechanism to trip that cam — the beep should appear/drop. That's the lock.
4. **Record** the cavity as column letter + count from the **"01" + AMP** datum end.

**Where the "signal terminal" is, by device:**
- **Cams (SA/SB/SC/TA1/TA2/TB):** each is a lever microswitch (COM/NO/NC). Clip to the terminal whose **wire heads into the C2A harness bundle**, not the one to the shared common/return. Unsure → try NO; if nothing beeps, try COM.
- **Grippers (GS1–10):** the spotting-table pin-presence switches. ⚠️ **Correction from the at-machine trace (2026-06-03):** there is **no physical TAC terminal strip** — each gripper switch closes to the **machine chassis/frame** (the chassis *is* the common return), and its signal wire runs in the table harness straight to a C2A cavity. So **don't clip-and-sweep the grippers — map them by dropping a pin** (see the gripper note under the table).
- **Pushbuttons (PBZ/PBC):** the button terminal that isn't the common.

| Device | Clip the long lead to… | Beep / sweep at C2A | Priority | Reading |
|---|---|---|---|---|
| **SC** | sweep-under-table interlock cam (read N.O. = pink) | **→ C2A-U** ✓ 2026-06-27 | ★ HIGH | **U** |
| **TB** | table-sweep interlock — both wires tie to the SC/pin-U node, no switched signal of its own | **no standalone cavity** ✓ 2026-06-27 (interlock-only) | ★ HIGH | — shares U |
| **TA2** | table run-through cam switch | confirm **21A**, else **30N** | HIGH | ____ |
| SA | sweep cam (270/360) switch | confirm **31N** | confirm | ____ |
| SB | sweep guard cam switch | confirm **31H** | confirm | ____ |
| TA1 | table cam (355/185) switch | confirm **34N** | confirm | ____ |
| GS1–GS10 | drop-a-pin (chassis return) | **✓** 1=C 2=H 3=M 4=S 5=W 6=a 7=e 8=**TBD** 9=r 10=v | per-pin | see ✅ block |
| GP / BS | gripper-protect / bin (#9) switch | **BS → CC ✓**; GP still open | confirm | BS=CC |
| PBZ | zero pushbutton terminal | **→ EE ✓** (shorts to common U pressed) | confirm | EE |
| OS / TENTH / MAN_SWSR (⊕) | off-spot / 10th / man-reverse switch | **SWEEP — unknown** | LOW | ____ |
| MAN_T / MAN_S / MAN_SWS (⊕) | manual table / sweep / sweep-switch | sweep T/S/SWS region | LOW | ____ |

> **Do SC, TB, TA2 first** — they unblock the harness, and for SC/TB the actuation-confirm (step 3) matters: they're the interlock cams.

**Grippers — map by dropping a pin (cold; no reach lead needed).** Because every gripper returns to the machine frame, you don't trace each one — you *actuate* it. Machine cold: clip your meter's **black lead to bare chassis/frame**, then **set a single pin into one spotting cup** (or hand-close that one gripper). With the red lead, **back-probe the C2A cavities** — the cavity that now reads **closed to chassis** is that gripper. The pin you dropped tells you the **gripper number** (its pin position, 1–10), so this step *names* GS1…GS10 at the same time. Work one cup at a time across the triangle. (This is the cutover "drop a pin, watch which input asserts" step from §4.3 — doing it with a meter at the bench gets you the cavity map early.)

**Cam switches — probe the WIRE by color, not the switch terminal.** The cam microswitches are subminiature (tiny plunger + lever) and their terminals are at the back, nearly unreachable. You don't need them — tap the cam's signal **wire** instead: an **insulation-piercing probe**, or a **sewing pin pushed through the insulation** with the long lead clipped to the pin. The board reads the **motion cams (SA/SB/TA1/TA2) normally-closed** → clip their **N.C.** wire; **SC and TB are the interlock cams**, read on their **N.O.** (window) contact → clip the **N.O.** wire. Colors are **per-harness** — the sweep-switch and table-switch harnesses reuse colors (SB's brown ≠ TB's brown), so use the right table for the switch you're on. From the p257 wire legend:

*Sweep switches (SA / SB / SC):*
| Cam | Clip the N.C. wire | (N.O.) | (COM — avoid) | lands on |
|---|---|---|---|---|
| SA | **WHITE** | blue | black | TS-31 |
| SB | **BROWN** | red | bused → SA | TS-16 |
| SC | **PINK** (N.O.) | yellow = N.C. | green = COM | **→ C2A-U** ✓ 2026-06-27 |

*Table switches (TA1 / TA2 / TB):*
| Cam | Clip the N.C. wire | (N.O.) | (COM — avoid) | lands on |
|---|---|---|---|---|
| TA1 | **PINK** | purple | black | TS-30 |
| TA2 | **BLUE** | gray | bused → TA1 | TS-33 |
| TB | *(N.O. only)* **GREEN** | — | brown | TSA-5 |

**SC & TB are a series hardware interlock** sharing node TSG-1 (= C2A-**U**): SC reads at U; **TB has no independent cavity** — both its wires tie to that node (confirmed at machine 2026-06-27, neither isolates). Read the interlock at U; infer TB from the table-cam angle.

**Motion cams share a COMMON → C2A-N.** The cam COM wires bus together to one cavity, **N** (confirmed 2026-06-27 — both SA and TA2 ring to N regardless of lever). Because they share this common, **cold per-cam cavity reads are ambiguous** (every cam shows N + maybe its own cavity). **Finish the per-cam SA/SB/TA1/TA2 → cavity mapping at powered cutover** — rotate the mechanism, watch which cavity goes live as each cam trips (§4.2 PART C2); it does **not** gate the board. Cold sweeps also pick up **sneak paths through relay coils** — SA's lower wire reads ~21Ω to CC (a coil path, ≈BE's 22Ω coil) plus ~0Ω to N/FF/F (commons) — because the cam contacts sit **in series in the machine's relay ladder**, not as isolated dry contacts. That's the real reason no cam isolates cold. **Do them powered** (rotate, watch the cavity go live); doesn't gate the board.

**Isolate it (for one clean beep):** actuate the switch to the state that **opens the contact you're reading**, so that wire disconnects from the bused common — then only its own cavity beeps. **N.C. (motion cams): press** the lever to open it. **N.O. (SC/TB interlock): release / pull the lever off** the button to open it. (Or skip isolating and just take the single *unique* cavity, ignoring the common-bus beeps.)
**Even easier if it survived the retrofit:** every wire lands on a numbered terminal strip (the "TS-nn" above). If that strip is still in the machine, clip there instead of piercing.

### 2. Short stragglers (knock out alongside)
- **M1 (ball-return) output** — never measured. Only needed if you ever populate J12 (DNP). Low priority — beep its coil → connector when convenient.
- **Heavy-lug S/T contactor coil V** + **verify the suspect T <1Ω read** (armature-press: steady = coil, jumps = contact). Minor — affects contact-rating/snubber sizing, not the harness map. The S/T contactors are almost certainly 24 VAC like everything else; just confirm.

### 3. At-machine, POWERED (during cutover prep — one deliberate test at a time, locked out otherwise)
- **Front-end class (dry vs 24 VAC):** **no reach problem here** — you meter right at the cabinet: the cam's signal is present at its C2A cavity once the machine is powered, so meter **cavity → FIELD_GND** (both in the cabinet) with the probe **loaded (LoZ)**. **< 2 V or open = dry** (keep the opto front-end); **12–24 VAC = live** (that channel needs the 24 VAC-rectified sense). The **six cam channels** (SA/SB/SC/TA1/TA2/TB) are the ones in question.
- **Foul tap:** meter the foul **lamp wire** voltage → decide dry vs 24 VAC front-end for J5-3.
- **DIELL re-check:** signal line ~16 V beam-clear / ~0.7 V blocked (already proven). Tap **signal + GND only** into J3-7/8.
- **Safety chain (§A):** stop switch RUN → coil rail live; STOP → dead. **Break-on-STOP = hardware-in-series (preserve).** No break = **FLAG: add hardware interlock before any Pi-driven motor.**
- **Cam-stop actuation (§B):** flip the cam — does the motor-relay coil drop **from the cam alone** (hardwired) or **only after the board reacts** (logic)? Confirms the topology read. *(This one needs eyes on the coil while flipping the cam — easiest with a helper, or clip a 12/24 V test lamp across the coil so you can watch it from the mechanism.)*

---

## Safety (the bits still live)
- The cold C2A tracing (#1) is **continuity only — safe.**
- For the powered steps (#3): **lock out**, power only for the one deliberate test, **load the probe (LoZ)** to kill ghost voltage, **never cut the safety loop to measure** (bridge across it), and confirm the caps read ~0 V before handling.

## Tools
DMM (continuity/beep, AC + DC volts, **LoZ/low-Z** mode if it has one), **back-probe pin kit** (touch a C2A cavity without un-mating), **a ~25 ft extension lead** (stranded wire + 2 alligator clips, or 2–3 chained test-lead sets — bridges the cabinet↔machine reach for B1), clip leads, the Section F spec printout, phone camera, this sheet.

## What to send back
Photos or typed copy of the **B1 table** (+ any straggler readings). I turn them straight into the corrected Section F input map — and the harness goes from spec to cut-and-crimp.

> **Bottom line:** it's essentially **one task — trace the C2A input cavities at the machine, SC/TB/TA2 first.** The bench output side is already done.
