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
- **Grippers (drop-a-pin) — COMPLETE 10/10:** GS1=**C** · GS2=**H** · GS3=**M** · GS4=**S** · GS5=**W** · GS6=**a** · GS7=**e** · GS8=**K** *(✓ 2026-07-07)* · GS9=**r** · GS10=**v**. (GS1–5 match the schematic; GS6–10 resolve/correct it — the old GS8=48H collided with GS2=H, and GS10=U is a common, both wrong. GS8=K breaks the loose alphabetic run — measurement over pattern; the cutover drop-one-pin gate re-verifies each anyway.)
- **PBZ** (zero button) **→ EE** (shorts to common U when pressed).
- **BS** (#9 bin) **→ CC.**
- **SC** cold trace **→ U.** · **TB → no standalone cavity** (neither TB lead isolates from the shared U live-ladder region; this is a harness fact, not a topology result).
- **Common/ground rails — ignore these, they ring to everything:** **J, F, U** (gripper/control common, chassis return) + **N** (the 5-cam motion common).
- **Deferred to powered cutover:** motion cams **SA / SB / TA1 / TA2** (buried in the relay ladder — a clean one-read each once powered).
- **Still open:** GP (gripper-protect — **DEFERRED 2026-07-07 to a later session or the powered cutover**; predicted ~412DD, no manual photo exists, method = watch DD/sweep while working one gripper's fingers fully open) · OS / PBC / 10th / MAN_* (spare/future) · Foul · DIELL re-check.

### ★ 1. C2A INPUT cavity digits — largely CLOSED 2026-06-27 (see ✅ block above)
**Remaining cold work = GP + the ⊕ stragglers.** The four motion cams (SA/SB/TA1/TA2) map at **POWERED cutover only** (§3) — do **not** re-attempt them cold. The reach-lead procedure below is kept for the remaining stragglers. The cams/grippers/switches live on the **machine**; their wires reach the cabinet through C2A.

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
| **SC** | sweep-under-table interlock cam (pink lead) | **→ C2A-U cold trace** ✓ 2026-06-27; live-ladder node, not a dry landing | ★ HIGH | **U (location only)** |
| **TB** | table-sweep interlock — neither lead isolates from the SC/U live-ladder region | **no standalone cavity** ✓ 2026-06-27 (no independent observation) | ★ HIGH | — shared region |
| **TA2** | table run-through cam switch | ~~confirm 21A, else 30N~~ cold read INVALID (30N impossible — N = cam common; coil sneak paths) | **DEFERRED → powered cutover (§3)** | — |
| SA | sweep cam (270/360) switch | ~~confirm 31N~~ cold read INVALID (N = cam common) | **DEFERRED → powered cutover (§3)** | — |
| SB | sweep guard cam switch | ~~confirm 31H~~ cold read INVALID | **DEFERRED → powered cutover (§3)** | — |
| TA1 | table cam (355/185) switch | ~~confirm 34N~~ cold read INVALID (N = cam common) | **DEFERRED → powered cutover (§3)** | — |
| GS1–GS10 | drop-a-pin (chassis return) | **✓ 10/10:** 1=C 2=H 3=M 4=S 5=W 6=a 7=e **8=K** 9=r 10=v | done | see ✅ block |
| GP / BS | gripper-protect / bin (#9) switch | **BS → CC ✓**; GP still open | confirm | BS=CC |
| PBZ | zero pushbutton terminal | **→ EE ✓** (shorts to common U pressed) | confirm | EE |
| OS / TENTH / MAN_SWSR (⊕) | off-spot / 10th / man-reverse switch | **SWEEP — unknown** | LOW | ____ |
| MAN_T / MAN_S / MAN_SWS (⊕) | manual table / sweep / sweep-switch | sweep T/S/SWS region | LOW | ____ |

> **Status (post-2026-07-07): the cold campaign is CLOSED.** SC/TB, all 10 grippers, PBZ, BS done; **GP deferred by decision** (catch it at the powered session — it gates nothing in the harness build; J4-11 lead gets cut/labeled but not landed). TA2 and the other motion cams map at the powered session (§3).

**Grippers — map by dropping a pin (cold; no reach lead needed).** Because every gripper returns to the machine frame, you don't trace each one — you *actuate* it. Machine cold: clip your meter's **black lead to bare chassis/frame**, then **set a single pin into one spotting cup** (or hand-close that one gripper). With the red lead, **back-probe the C2A cavities** — the cavity that now reads **closed to chassis** is that gripper. The pin you dropped tells you the **gripper number** (its pin position, 1–10), so this step *names* GS1…GS10 at the same time. Work one cup at a time across the triangle. (This is the cutover "drop a pin, watch which input asserts" step from §4.3 — doing it with a meter at the bench gets you the cavity map early.)

**Cam switches — probe the WIRE by color, not the switch terminal** *(now relevant to the POWERED session only — cold per-cam mapping is invalid, see below)*. The cam microswitches are subminiature (tiny plunger + lever) and their terminals are at the back, nearly unreachable. You don't need them — tap the cam's signal **wire** instead: an **insulation-piercing probe**, or a **sewing pin pushed through the insulation** with the long lead clipped to the pin. The board reads the **motion cams (SA/SB/TA1/TA2) normally-closed** → clip their **N.C.** wire; **SC and TB are the interlock cams**, read on their **N.O.** (window) contact → clip the **N.O.** wire. Colors are **per-harness** — the sweep-switch and table-switch harnesses reuse colors (SB's brown ≠ TB's brown), so use the right table for the switch you're on. From the p257 wire legend:

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

**SC/TB reconciliation:** the cold 2026-06-27 trace located SC at TSG-1/C2A-**U** and proved **TB has no independent cavity or dry pair**; neither TB lead isolated from that live-ladder region. Because the same cold measurements include ~21 Ω relay-coil sneak paths, they did **not** establish contact topology or danger polarity. The powered 2026-07-07 test is authoritative: the OEM contacts behave **parallel closed-when-safe**; either pressed lever permits a coil and **both levers BACK/open kill both S and T coils**. Candidate C therefore uses the controlled J_SAFE1-2 jumper and keeps the OEM ladder primary, subject to a per-lane G3 S/T coil-drop proof. Do not treat U as a dry J_SAFE or firmware-input landing; the SC∧TB firmware echo remains default-off, secondary, and unvalidated because no independent TB observation exists.

**Motion cams share a COMMON → C2A-N.** The cam COM wires bus together to one cavity, **N** (confirmed 2026-06-27 — both SA and TA2 ring to N regardless of lever). Because they share this common, **cold per-cam cavity reads are ambiguous** (every cam shows N + maybe its own cavity). **Finish the per-cam SA/SB/TA1/TA2 → cavity mapping at powered cutover** — rotate the mechanism, watch which cavity goes live as each cam trips (§4.2 PART C2); it does **not** gate the board. Cold sweeps also pick up **sneak paths through relay coils** — SA's lower wire reads ~21 Ω to CC (a coil path, ≈BE's 22 Ω coil) plus ~0 Ω to N/FF/F (commons). Those paths prove the region is not an isolated dry harness and make cold topology inference invalid; they do not prove whether the safety contacts themselves are series or parallel. **Do the mapping powered** (rotate, watch the cavity go live).

> **⛔ COLD CAM MAPPING IS A CLOSED METHOD — DO NOT ATTEMPT A THIRD TIME (2026-07-24).**
> Attempted twice at the machine (2026-06-27, and again 2026-07-24 via the "lever differential"
> trick with C2A unmated). Both failed the same way: no clean per-cam closure to N appears at
> rest, the only low-ohm hits are the documented commons (**F** rang <3 Ω to N — it is a common,
> not a cam) plus unstable higher-resistance sneak paths (lowercase **t**), and readings are not
> reproducible enough to identify anything. Meter/leads verified good during the 2026-07-24
> attempt, so this is the method failing, not the instrument.
>
> **The only approved path is POWERED, AT THE CAM SWITCH TERMINALS** (not at the connector):
> machine running under OEM control, clip onto a cam switch's own terminal, watch it through a
> cycle. That yields identification **and** the mandatory voltage class in one operation — and
> the class is the answer that actually matters before any cam lead touches a PC817 (this
> machine has produced 33 VDC on PBZ and 42 VAC on the DIELL board's middle block).
> **Fallback if connector-side identification stays impractical: tap the cams AT THE SWITCHES**
> and skip C2A for those four channels entirely — four extra wires to route, zero identification
> problem.
>
> **Not on the critical path.** Stage 6b (first commanded motion / coil-drop proof) needs the
> output taps and the rail, not cam inputs. Cam signals are required only for full FSM cycle
> timing, which is after first motion. Priority order stands: **Stop/CIS landing → output taps →
> Stage 6b → cams.**

**Isolate it (for one clean beep):** actuate the switch to the state that **opens the contact you're reading**, so that wire disconnects from the bused common — then only its own cavity beeps. **N.C. (motion cams): press** the lever to open it. **N.O. (SC/TB interlock): release / pull the lever off** the button to open it. (Or skip isolating and just take the single *unique* cavity, ignoring the common-bus beeps.)
**Even easier if it survived the retrofit:** every wire lands on a numbered terminal strip (the "TS-nn" above). If that strip is still in the machine, clip there instead of piercing.

### 2. Short stragglers (knock out alongside)
- **M1 (ball-return) output** — never measured. Only needed if you ever populate J12 (DNP). Low priority — beep its coil → connector when convenient.
- ~~**Heavy-lug S/T contactor coil V**~~ **✓ CLOSED 2026-07-07: both S and T motor-contactor coils = 24 VAC** (measured live across A1–A2 during the interlock test-2A session). The suspect T<1Ω cold read is moot for the harness (it was a contact, not the coil — the live coil reads confirm).

### 3. At-machine, POWERED (during cutover prep — one deliberate test at a time, locked out otherwise)
- **Front-end class (dry vs 24 VAC):** **no reach problem here** — meter each actually observable cam cavity at the cabinet with a loaded/LoZ probe. **< 2 V or open = dry** (keep the opto front-end); **12–24 VAC = live** (that channel needs the 24 VAC-rectified sense). SA/SB/SC/TA1/TA2 are the observable candidates; **TB has no independent cavity on lanes 21/22 and must not be invented as a sixth input.** C2A-U remains unlanded unless a separately reviewed observe-only input design is released.
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

> **Bottom line (reconciled 2026-07-24):** the cold tracing is **done** — it located the shared SC/U region, proved no standalone TB/dry pair, and measured all 10 grippers, PBZ, and BS. It did **not** prove SC/TB topology; the powered result controls and is parallel closed-when-safe. Remaining cold = **GP + ⊕ stragglers**; the four motion cams map at **POWERED cutover** (§3). The bench output side was already done.
