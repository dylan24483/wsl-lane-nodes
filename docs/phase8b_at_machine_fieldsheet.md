# Phase 8 Rev-B — AT-MACHINE Measurement Field Sheet (fab-lock session)

**For Dylan, at a REAL 82-70 pinsetter (lane 21 or 22), with the existing controller still installed.** This is the session that turns every `# CONFIRM at-machine` / `TBD` in the rev-B design into a hard number, so the board can go to fab. It is the **last gate** before rev-B PCB release (routing can finish in parallel; these numbers don't change the topology, they set ratings + final clearances).

> ⚠️ **THIS IS NOT THE BENCH.** The earlier field work was the *disconnected spare cabinet* (cold, safe). This session needs the **live machine** to read real voltages/currents and to actuate cams/grippers. **A powered pinsetter moves and bites.** Read §0 before touching anything.

---

## ✅ FIELD SESSION COMPLETE (2026-06-03) — all design-gating data extracted
Everything the rev-B board design needs is in hand. Remaining items are cutover-day work (easier then). Results:
| item | result | feeds |
|---|---|---|
| **A1** working voltage | **24 VAC** (all relays; SP presumed) | creepage can relax 250V→24V → smaller board |
| **A3** lamp supply | **15 VDC** → replaced by board-driven LEDs | lamp output simplified (no PhotoMOS) |
| **A4** cam input form | **dry contact** (normally-closed) | cam front-end = dry-contact wetting |
| **B3** Stop/CIS chain | **parallel, cut master breaker** (OEM svc p11) | preserve upstream safety chain |
| **B1** TB/SC interlock | **parallel into 24V control path** (OEM); exact terminals → cutover | J_SAFETY = NC series loop |
| **B2** cam-stop logic/HW | leans LOGIC; → cutover cam-flip | not a design gate |
| **Grippers** | **chassis-return; gripped = CLOSED to ground** (corrects OEM TAC-common model) | gripper input = chassis-referenced dry contact, FIELD-side |

**DELIBERATELY DEFERRED to cutover (NOT worth bench/field time now — set in software/at-disassembly):** per-gripper GS#→C2A pin labels (drop a pin, watch the live feed), per-cam SA/TA#→cavity labels, exact C1/C2A terminal landings, TB/SC terminal landing. All easier with the machine apart + a live feed; none gate the PCB (function-named + harness-resolved).

---

## §0 — SAFETY (read every time)
- ⛔ **WHEN: lane formally OUT OF SERVICE, OFF-HOURS only.** NOT during active bowling, NOT on any lane customers could be assigned to. "Powered but idle" is NOT safe — a customer/desk action can cycle an in-service machine while your hands are in it. Flag the lane out of service at the desk; do this before open / after close / in a maintenance block; tell whoever runs maintenance you're in the machine.
- **Two modes only:** (A) **LOCKED OUT** — master breaker OFF, machine cannot move → all cold continuity + actuate-by-hand work (this is MOST of the session). (B) **DELIBERATE LIVE READ** — powered, for the few voltage reads that *require* power. The machine cycles **only on a deliberate command you + your helper both expect** — never because of a customer. Your body stays OUT of the sweep/table/pit travel path the whole time; reach in only with the red probe to a coil terminal outside the swing, and skip any terminal you can't reach from outside the danger zone.
- **Default to mode A.** Only go live for the explicitly-marked **[LIVE]** steps, one at a time, then lock out again.
- **[LIVE] reads:** GFCI if possible, one hand in pocket, probe the **low-voltage / control side only**, never the 115 VAC motor leads. Black probe on chassis ground.
- **Never** put any body part in the sweep/table/pit travel path while powered. If a step needs the mechanism rotated, do it **by hand, LOCKED OUT.**
- **Two people** for any live step — one at the meter, one at the stop.
- If anything feels wrong, master breaker OFF first, ask second.

---

## PART A — FAB-LOCK MEASUREMENTS (these release the PCB) ⭐
Each row has a **why** (what design number it locks). Priority order.

> ## STATE LEGEND (which measurements need motion vs just power)
> Every step below is tagged with the state it requires:
> - **🔴 POWER ON + sweep/table CYCLING** — the only "stuff is moving while you read" case. Deliberate commanded cycle, body clear of the swing. Just **A1 for S/T/SP/M/M2** + **A4 Step-2 on cams**.
> - **🟡 POWER ON, static** (no front-end cycle) — powered but sweep/table at rest. Low risk. **A3 lamp**, **A1 for BE** (BE motor runs continuously, no cycle needed), **A4 Step-2 on hand-actuated switches**.
> - **🟢 POWER OFF / locked out** — safe; you hand-actuate, nothing powered. **All of Part B, all of Part C, A4 Step-1.** This is most of the session.
>
> **The takeaway:** the ONLY reads taken while a motor/sweep/table is actively moving are **A1 (S/T/SP/M/M2)** and the **A4 cam voltage-sense check**. Everything in Parts B & C is power-OFF, hand-actuated — nothing powered is moving.

### A1 — Machine-output WORKING VOLTAGE ⭐⭐ (THE creepage gate)
**Why:** the rev-B creepage policy is currently a conservative 250 VAC assumption. This measurement either confirms it or lets the LOGIC↔MACHINE barrier relax from ≥3.2 mm toward ~0.5–1 mm — a big layout relief, but ONLY if measured low. Until measured, fab stays at 250 VAC spacing.
**What:** for each relay we drive, measure the **voltage on the coil circuit** when that function is active. AC range first then DC. **State per relay:** S/T/SP/M/M2 = **🔴 commanded cycle** (coil only energizes during its cycle); **BE = 🟡 powered-static** (back-end motor runs continuously, read it with sweep/table at rest — no cycle).
| relay | what it switches (coil circuit) | V (AC) | V (DC) | notes |
|---|---|---|---|---|
| S (sweep) | Siemens 3TH40 coil ckt | ___ | ___ | coil already known 24 VAC; confirm the *switched* node V |
| T (table) | contactor coil ckt | ___ | ___ | |
| SP (spot) | spot solenoid ckt | ___ | ___ | |
| BE (back-end) | BE relay coil ckt | ___ | ___ | |
| M (master) | master ckt | ___ | ___ | |
| M2 (sweep-rev) | sweep-rev ckt | ___ | ___ | |
→ **Highest reading across all rows = the working voltage the creepage policy uses.** If all ≤30 VAC → relax barrier (big win). If any >50 V → keep conservative for that channel.

### A2 — Coil / control CURRENT per output ⭐ (relay contact rating)
**Why:** sets the G5LE contact rating + whether snubber/MOV get populated. Currently budgeted ~2 A @ 30 VDC / 0.5 A @ 250 VAC (guess).
**What:** measure the **current the board's dry contact will carry** = the holding (and ideally inrush) current of each coil circuit. **[LIVE]**, clamp meter on the coil lead if possible (safer than breaking the circuit), else inline mA.
| relay | holding current | inrush (if seen) | notes |
|---|---|---|---|
| S | ___ | ___ | AC contactor coil — expect higher inrush |
| T | ___ | ___ | |
| SP | ___ | ___ | solenoid — inrush matters |
| BE | ___ | ___ | |
| M | ___ | ___ | |
| M2 | ___ | ___ | |
→ Confirms G5LE 10 A contact is ample (almost certainly yes) + sizes the snubber.

### A3 — Mask status-lamp supply + current (lamp output sizing)
**Why:** picks AQY PhotoMOS vs relay for the 4 status lamps + confirms no on-board 12 V rail needed.
**What:** at the mask, measure the **status-lamp supply** (1st-ball/2nd-ball/strike/foul lamps). **[LIVE].**
- Lamp supply voltage: ___ V (AC/DC?) — *(SYSTEM_REFERENCE says 12 VDC; verify)*
- Per-lamp current: ___ mA
- Is it a shared supply tappable at the mask connector? Y / N ___
→ If 12 VDC ≤ a few hundred mA → AQY282S is fine, machine-sourced, no board rail.

### A4 — Cam input electrical form (per-channel dry-vs-AC population)
**Why:** each opto input front-end is population-selectable dry-contact vs 24 VAC-sense; this sets the default per channel. Cams especially are unconfirmed.
**What:** for each cam (SA/SB/SC/TA1/TA2/TB) + GP/OS/BS, determine at its wire: is it a **dry switch closure** (to ground/common) or a **voltage-sense** (24 VAC present when active)? **[LIVE]** to see voltage; or **LOCKED OUT** continuity to tell dry-contact.
| input | dry-contact? | voltage-sense V (if any) | → population |
|---|---|---|---|
| SA | | | dry / AC |
| SB | | | |
| SC | | | |
| TA1 | | | |
| TA2 | | | |
| TB | | | |
| GP | | | |
| OS | | | |
| BS | | | |

---

## PART B — SAFETY-ARCHITECTURE CONFIRMATIONS (design-critical, not voltage)
> ✅ **STATUS 2026-06-02 — mostly resolved without the hard live trace:**
> - **B3 = DONE from OEM service-manual p11** (Stop + C.I.S. in parallel, both cut the rear-panel master breaker). No probing needed. Skip the steps below.
> - **B1 = design-answered (TB+SC parallel into 24V control path; J_SAFETY accepts an NC series loop). EXACT TERMINALS DEFERRED TO CUTOVER** — easier with the machine apart; do NOT contort behind the live machine for it now.
> - **B2 = deferred to cutover** (cam-flip test; not a design gate).
> The steps below are retained for reference / the cutover session, but Part B needs no further LIVE work now.
### B1 — TB/SC interlock electrical form ⭐ (how it wires into the rail)
**Why:** the relay-enable rail needs the TB/SC interlock as a hardware series condition. We need to know its electrical form on OUR chassis to wire J_SAFETY correctly.
**What:** **LOCKED OUT.** Find the TB + SC cam switches; confirm they're wired in **parallel** in the 24 V control path (per OEM), and determine: is the interlock a **normally-closed loop** that opens on collision? Trace where it lands. Record: contacts found ___ ; NC loop? Y/N ___ ; lands at ___ . Photograph.

### B2 — Cam-stop logic-vs-hardwired (the deferred airtight proof)
**Why:** closes the open question from the bench (S-side was inaccessible). Determines if an existing hardwired cam-stop is preserved as a bonus backstop.
**What:** **LOCKED OUT**, hand-rotate the sweep so the **SA cam** trips; watch whether the **S relay coil drops** purely from the cam (hardwired) or only via the board (logic). Repeat table/TA. Record: SA→S-coil drops by cam alone? Y/N ___ ; TA→T-coil? Y/N ___ . (Expected: logic.)

### B3 — Stop/CIS chain in series with motor power
**Why:** confirms the existing safety chain we must preserve upstream of the board.
**What:** **LOCKED OUT** continuity: stop switch in RUN vs STOP → does the motor-relay coil rail go dead on STOP? Y/N ___ . (Should be Y = hardware-in-series.)

---

## PART C — HARNESS MAP (per-signal C2A binding — was machine-gated on the bench)
**Why:** the board uses function-named connectors + an adapter harness; THIS is where the harness gets its per-pin map. Grippers/cams couldn't be cold-mapped (open switches) — now they can, by actuation.
### C1 — Per-gripper GS-n → C2A plug pin  ⭐ (refined method, 2026-06-02)
**Best method: UNPLUG C2A and probe the MACHINE-SIDE PLUG** (the side whose wires run back to the machine). Why unplug:
- **Isolates the gripper switches** — plugged in, a pin connects through to cabinet wiring/board/other nets, so a continuity hit could be a sneak path, not the gripper. Unplugged, the plug = ONLY the machine harness (gripper switch + its return). Clean.
- Gets you **out from behind the cabinet** — set the plug on your lap/bench and probe in comfort.

**⛔ NOBODY lies under the machine.** Access the grippers safely:
- **LOCK OUT** (breaker off — all of this is cold/no-motion).
- **Position the spotting table to a reachable height** at the deck (hand-crank/jog the mechanism) so you reach the grippers **from the pit/approach end at normal posture** — reaching IN from the front, never under live machinery. If it won't position to a genuinely comfortable reach → **STOP, defer the whole gripper map to cutover** (it's harness/software, not a board gate).

**Scope: spot-confirm 2–3 ACCESSIBLE grippers, not all 10.** The board only needs the gripper BANK location + the polarity; exact GS1-vs-GS7 labels get set in software at cutover (drop a pin, watch the feed). So:
1. C2A unplugged, plug on your lap/bench. The 10 grippers share a **common return** (TAC-GND): black probe = the common pin (the one reading continuity to several gripper pins). Red = a candidate pin.
2. Pick **2–3 easily-reached grippers, spread out** (a corner + a center one shows the pin-ordering pattern). For each: **record RESTING state** (empty/un-pinched): open or closed?
3. **Work that gripper through its FULL open↔pinched travel by hand**; watch the meter flip. **Record BOTH states** → captures the pin + the polarity.
4. ⚠️ **Do NOT assume gripped = closed.** Could be NO-closes-on-pin OR NC-opens-on-pin (the cam was NC; grippers may differ). MEASURE. Polarity is the same for all 10, so 2–3 confirms it.
5. **Stop conditions:** can't position the table comfortably → defer all to cutover. A gripper needs you in the mechanism's travel space → skip it. Got 2–3 + polarity → DONE.

**Record by PLUG PIN POSITION** (you've unplugged, so cabinet cavity labels aren't visible): e.g. "GS I actuated → plug row B, 3rd pin from the notch: empty=open, gripped=closed." **Photograph the plug face with its notch/pin-1 mark** so positions are unambiguous; Claude maps plug-position → C2A cavity from connector geometry afterward.

| gripper actuated | plug pin position (from notch) | empty state | gripped state |
|---|---|---|---|
| (work them one at a time) | | | |
### C2 — Per-cam SA/SB/SC/TA1/TA2/TB → C2A cavity
**LOCKED OUT.** Hand-rotate to trip each cam; note which C2A cavity changes at which angle. Record SA→__@__°, etc.
### C3 — GP/OS/BS/Foul/PBZ/PBC → C2A cavity
Actuate each (some are remote buttons); note cavity. Record each.

---

## PRIORITY / IF SHORT ON TIME
1. **A1 (working voltage)** — the single highest-value read; it's the creepage gate that decides whether the board can shrink. Do this first.
2. **A2 (currents)** + **A3 (lamp)** — fab-lock relay/lamp ratings.
3. **B1 (TB/SC form)** — needed to wire the safety connector.
4. **A4 / C1–C3** — population defaults + harness map (can trickle in; harness is built at cutover).

## WHAT TO SEND BACK
The filled tables (photos of jotted sheets fine) + photos of: the TB/SC switches, the mask lamp supply point, any contactor coil nameplate you can read. I turn A1→final creepage policy + re-DRC; A2/A3→lock relay/lamp parts in the BOM; B1→J_SAFETY wiring; C→the adapter-harness pinout table.

## WHAT THIS UNBLOCKS
- A1 → **24 VAC confirmed; current conservative routed board is fab-exported.** Optional future work is 24 V creepage relaxation for a smaller/spin-2 board; current next step is vendor Gerber/drill upload preview.
- A2/A3 → BOM fab-lock (relay contact rating, lamp switch part, snubber populate y/n).
- A4 → input front-end default population per channel.
- B1/B2/B3 → safety-chain wiring + the bonus-backstop decision.
- C → the per-chassis adapter harness (the thing that maps the function-named board to THIS lane's C1/C2A).

> **Reminder:** this is per-CHASSIS-TYPE. Lanes 21/22 are SS+Omega-Tek; 11/12 are Active-98 MP. The A1/A4/C readings here apply to the 21/22 pair; the MP pair needs its own quick pass before its harness. The BOARD is common; the harness + populations are per-chassis.
