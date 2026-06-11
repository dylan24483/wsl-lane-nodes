# JOB 3 — C2A Input-Side Map (cams + GP/OS/BS + 10 grippers)

**For Dylan, spare cabinet, all COLD.** This maps the **input** signals the Pi must READ — the cams (SA/SB/SC/TA1/TA2/TB), the gate/bin switches (GP/OS/BS), and the **10 grippers** (GS1–10 via the TAC strip). All arrive on **C2A** (the RIGHT 4-column connector). This is the last bench-gated input before PCB rev-B layout.

> **Heads-up — C2A carries TWO things:** yesterday we found the S/T **coils** also land on C2A (it's the coil/control + cam connector). So some C2A cavities are coil wires, others are cam/switch inputs. **Don't confuse them.** The grippers (TAC strip) are physically separate from the relay coils, so they're unambiguous; the cams come in on the **A&MC** plug wires. We anchor on those, not on raw cavity guesses.

> **Method = same as JOB 1 (it worked):** anchor on a *device* you can identify (a gripper switch, a cam microswitch lead, the A&MC plug), probe to C2A, record the cavity. We do NOT trust the 225-DPI predicted cavity codes — we measure.

---

## ⭐ GRIPPER ARCHITECTURE — CORRECTED AT MACHINE (2026-06-03, Dylan)
Field tracing on the real machine **overturns the "TAC strip with a shared common-return wire" model** (that was from the OEM 9800-MP DETAIL-K; our SS+Omega-Tek chassis differs, same as M2/S-cavities did):
- **Each gripper switch closes its signal wire to a CONTACT POINT that is the machine CHASSIS/FRAME** (gripped = wire touches grounded point). Confirmed: that contact point is **not insulated from the frame** (continuity finicky only due to dirt/oxide).
- **So the COMMON RETURN = the machine chassis itself**, NOT a TAC-GND bus wire on C2A. There is no single "common pin" to hunt for. Each gripper = one **signal wire** (via a wire-nut splice → back to the plug → C2A) + **chassis return**.
- **POLARITY CONFIRMED: gripped (pin present) = CLOSED to ground.** (Opposite of the cam, which was normally-closed.) Locked for all 10 → firmware: gripper input asserts (pulls to common) when a pin is standing.
- **Test method (revised):** **black probe clipped to clean bare chassis metal** (anywhere, incl. at the cabinet — scrub a spot for a solid bite), meter on beep, **red probe on C2A signal pins** (start the predicted 4-bank 41C/42H/43M…), helper grips one gripper → the pin that beeps = that gripper. Distance is irrelevant; chassis ground bridges it.
- **⚠️ BOARD IMPACT (flag for Codex):** the gripper input front-ends must use **CHASSIS as the return reference**, not the isolated FIELD_GND/wetting scheme assumed for "dry contact to TAC-GND." This is still a dry-contact-to-ground input (the opto field side wets through the gripper to chassis), but the *return* is machine frame, not a dedicated wire. **Confirm the field-wetting/opto-input topology handles chassis-referenced grippers** — likely fine (it's still contact-to-a-reference) but the reference node identity changed. Does NOT change the board's isolation domains (grippers are still FIELD-side), but the harness ties gripper returns to chassis, not to a C2A common pin.

## PART 1 — THE 10 GRIPPERS
The grippers (GS1–GS10) are the pin-sense switches; they read which pins are standing. **10 of the Pi's ~23 inputs, scoring-critical.**

### ⚠️ 1a — there is NO separate "TAC strip" in this cabinet (photo review, 2026-06-02)
Reviewed all 19 cabinet photos. **No discrete 10–12-lug "TAC" terminal block exists.** What's actually in there:
- The "black screw-terminal block" near the Omega board = the **S2003LS2 TRIAC output bank** (board OUTPUTS), not gripper inputs.
- DETAIL K listed TAC-1…TAC-10 with **C2A pin codes** (41C, 42H, 43M, 44S, 45W, 46Z, 47?, 48H, 49?, 410U). → **Conclusion: on this Omega-Tek retrofit the grippers land DIRECTLY on C2A cavities; "TAC" is the schematic net/harness name, not a physical strip.**
- The grippers arrive via the **machine/table harness bundle** (the cloth-wire bundle, zip-tied, entering near the C2A connector — visible in `150331` back-panel + `090437` overview) and terminate **on C2A pins.**

**So Part 1 = identify which C2A cavities are the grippers, by working from the harness bundle, NOT a strip.**

### 1a-revised — how to find the gripper wires without a strip
The gripper net is 10 switches sharing a common return (TAC-GND). Strategy:
1. **Find the table/machine harness bundle** where it enters the cabinet (the fat cloth-wire bundle near C2A's back, photo `150331`). The grippers are 10 wires in here.
2. **Use the common return as the anchor:** the 10 grippers share **TAC-GND** (predicted C2A-310E). At rest (no pins/contacts made on the bench), the grippers are open switches — so resistance alone may not light them up cold. **Better: identify them by the C2A cavity block.** DETAIL K says they occupy a contiguous block **41C…410U** — i.e. the C2A "4-bank" (cavities starting with 4). On the connector, find the **4-column/4-bank group of ~10 adjacent cavities** and confirm wires land there.
3. **Photograph** the C2A back where that bundle lands + note which cavity-bank the gripper bundle occupies.
- Honestly: cold-mapping individual grippers is hard without actuating them (they're open switches on the bench). The high-confidence bench result is **"the gripper bundle lands on C2A cavities 41C–410U (the 4-bank)"** — confirm that block exists and is wired. Per-gripper 1:1 (GS-n = which exact cavity) is best nailed at the machine by lifting one pin at a time and watching which cavity closes.

### 1b — confirm TAC-n → C2A cavity (the map)
For each TAC lug, beep to C2A, record the cavity. Predicted (from p290 DETAIL K — VERIFY, don't trust):
| gripper | TAC lug | predicted C2A | measured cavity | Ω |
|---|---|---|---|---|
| GS1 | TAC-1 | C2A-41C | ____ | ____ |
| GS2 | TAC-2 | C2A-42H | ____ | ____ |
| GS3 | TAC-3 | C2A-43M | ____ | ____ |
| GS4 | TAC-4 | C2A-44S | ____ | ____ |
| GS5 | TAC-5 | C2A-45W | ____ | ____ |
| GS6 | TAC-6 | C2A-46Z | ____ | ____ |
| GS7 | TAC-7 | C2A-47? | ____ | ____ |
| GS8 | TAC-8 | C2A-48H | ____ | ____ |
| GS9 | TAC-9 | C2A-49? | ____ | ____ |
| GS10 | TAC-10 | C2A-410U | ____ | ____ |
| common | TAC-GND | C2A-310E | ____ | ____ |

- **Shortcut:** if the TAC strip is clearly numbered and lands on C2A in a tidy block, just confirm the FIRST, MIDDLE, LAST (TAC-1, TAC-5, TAC-10) map sanely and note the block — don't grind all 10 unless the order looks scrambled.
- **What we need:** confirmation that TAC-n = GS-n (1:1, no scramble) and the C2A cavity block they occupy. Flag any gripper that doesn't follow the pattern.

---

## PART 1.5 — ACTUATE-AND-WATCH: the switches you CAN close by hand ⭐ (high-value, cold)
The reason grippers/cams resist cold-probing is they're open until something actuates them. But **any switch you can press/move by hand IS cold-mappable**: put the meter across "candidate C2A cavity ↔ common", press the switch, watch it go 0 Ω. Best targets:

### PBZ + PBC (control-panel pushbuttons — you can press these!)
1. On the C2A connector, you're hunting the cavity that **changes state when you press the button.** Easiest method: meter from a **known common/ground** (e.g. TAC-GND/chassis) to a candidate C2A cavity while a helper (or your free hand) presses PBZ.
   - **Faster:** press-and-hold PBZ, sweep the C2A cavities with the red probe (black on chassis/common) — the one that reads **closed only while pressed** = PBZ. Record cavity: ____
   - Repeat for PBC: ____
2. These are real, lockable bench data — PBZ (zero/manual-intervention) + PBC (cycle) are both Pi inputs.

### Any GP/OS/BS switch you can physically reach + toggle
If the gripper-protect / off-spot / bin switches are accessible enough to flip by hand on the spare, same method: toggle + find the C2A cavity that follows. If they're buried machine-side, skip → at-machine. Record any you get: GP ____ · OS ____ · BS ____.

## PART 2 — THE CAMS (SA, SB, SC, TA1, TA2, TB) via the A&MC plug
The cams are microswitches **on the machine** (not on your bench) — but their wires enter via the **A&MC plug** and land on C2A. So on the bench you map **A&MC-plug wire → C2A cavity**; the cam-to-A&MC association comes from the schematic.

### 2a — find the A&MC plug
The A&MC ("Approach & Machine Control"?) plug is the **curtain-wall / machine harness connector** that brings the cam + gate-switch wires in. Per schematic the cams associate to A&MC pins: **A&MC-11A, 12D, 13H, 14L, 21B, 22E, 31C.**
- Locate + photograph the A&MC plug. How many pins? ____
- Is it a separate plug from C2A, or do the A&MC wires feed straight into C2A cavities? ____

### 2b — A&MC → C2A cavity (so we know where each cam lands)
For each A&MC pin, beep to C2A, record the cavity:
| A&MC pin | schematic cam assoc. (tentative) | C2A cavity | Ω |
|---|---|---|---|
| A&MC-11A | (cam — TBD) | ____ | ____ |
| A&MC-12D | (cam — TBD) | ____ | ____ |
| A&MC-13H | (cam — TBD) | ____ | ____ |
| A&MC-14L | (cam — TBD) | ____ | ____ |
| A&MC-21B | (cam — TBD) | ____ | ____ |
| A&MC-22E | (cam — TBD) | ____ | ____ |
| A&MC-31C | (cam — TBD) | ____ | ____ |

> ⚠️ **We can't fully ID which A&MC pin = which specific cam (SA vs TA1 …) from the bench** — that needs the at-machine test (rotate the mechanism, watch which switch closes at which angle). For now we just map **A&MC pin → C2A cavity**; the cam↔A&MC binding is a cutover-prep at-machine task. Note that as the gap.

---

## PART 3 — GATE / BIN SWITCHES (GP, OS, BS) + pushbuttons (PBZ, PBC)
These are individual switches; some are machine-side (GP/OS/BS), some are panel (PBZ/PBC). From the C2A signal list we already have tentative cavities. Confirm what you can reach:
| signal | role | tentative C2A (schematic) | measured | Ω |
|---|---|---|---|---|
| PBZ | zero / 1st-2nd-ball / manual-intervention | C2A-21EE area | ____ | ____ |
| PBC | cycle pushbutton | C2A-21EE area | ____ | ____ |
| GP | gripper-protect | (TBD) | ____ | ____ |
| OS | off-spot | (TBD) | ____ | ____ |
| BS | bin/#9 | C2A-112cc | ____ | ____ |
| Foul | Radaray foul | (TBD) | ____ | ____ |

- **PBZ/PBC** are on the control panel — find them at the panel buttons, beep to C2A.
- **GP/OS/BS** are machine-side switches (like the cams) — may only be mappable as "A&MC/table-plug wire → C2A cavity," with the switch itself confirmed at the machine. Map what lands on C2A; flag the rest for at-machine.

---

## HOW FAR TO GO (priority — revised for "what's cold-probeable")
The bench can only nail down what you can **actuate by hand** or **trace as a wire**. Open switches (grippers, cams) can't be cold-mapped per-pin → those defer to the machine. So today, in order:
1. **PART 1.5 (actuate-and-watch): PBZ + PBC** — you can press these → fully mappable now. **Highest-yield cold data left.** Plus any hand-reachable GP/OS/BS.
2. **PART 1 (gripper BANK location)** — confirm the table harness lands on the C2A 4-bank (41C–410U) + photograph. (Per-gripper GS-n binding = at-machine.)
3. **PART 2 (A&MC → C2A cavity)** — map cavities for the cam bundle; cam↔A&MC binding = at-machine.
4. Anything else you can physically toggle → map it.

**Everything else (per-gripper, per-cam, machine-side GP/OS/BS) is machine-gated — not a bench failure, just physics. None of it blocks PCB layout** (the board needs bank/cavity locations, not the GS-n/cam-n software binding).

## WHAT TO SEND ME
- Part 1: the TAC→C2A block (or the 1/5/10 spot-check + "tidy block" confirmation) + lug count + whether labeled.
- Part 2: A&MC pin → C2A cavity table + A&MC plug photo + pin count.
- Part 3: whatever PBZ/PBC/BS you could reach.
- Photos of the TAC strip + A&MC plug.

→ I lock the **C2A input map** into `phase8_channel_allocation.md` §2 (the MCP23017 IN-A/IN-B assignments) → that's the last bench-gated input → **PCB rev-B can go to layout.**

## PART 0 — cam-stop close-out: ⛔ S→board pin is INACCESSIBLE (board plugged in blocks it) → DEFER
The direct "S-switched → board pin" probe is **not bench-doable** — the S 3-pin block sits too close to the original board, blocked when the Omega is plugged in (same access wall as the bottom rail). So:
- **Bench can't make this airtight.** Physical limit, not a work gap.
- **Optional elimination half (only if quick):** (1) ID S's SWITCHED tag = the S-coil tag that does NOT beep to M2/SP coils (the other is the shared-24V SUPPLY side). (2) Probe ONLY that switched tag → C2A. **No 0 Ω C2A hit → board-driven by elimination** (nothing else for it to connect to). Record: switched tag = ____, switched→C2A hit? ____.
- **Otherwise PUNT to the at-machine cam-flip** (rotate mechanism, watch S coil drop) at cutover — airtight + free then.
- **Why it's fine to leave open:** T is already confirmed board-driven; S is symmetric (board has matching S+T output fingers); and we add HW end-stops + TB/SC interlock + RP2040 timing REGARDLESS. This only decides whether a *bonus* hardwired backstop exists. **Not a design gate. Go to Part 1.**

## REMINDER — what stays for the at-machine session (not bench)
- Which A&MC pin = which specific cam (SA/SB/SC/TA1/TA2/TB) — needs rotating the mechanism.
- The GP/OS/BS switch bodies (machine-side) — confirm actuation at the machine.
- The cam-stop logic-vs-hardwired airtight proof (yesterday's open item).
These are cutover-prep tasks; they don't block the board layout (the board just needs "this signal lands on this C2A cavity → this MCP pin").
