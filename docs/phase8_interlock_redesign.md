# Phase 8 — TB/SC interlock redesign (the J_SAFETY landing)

**Status: ✅ DECIDED 2026-07-07 — Candidate C.** J_SAFE1-2 receives the documented, labeled engineered jumper and the OEM SC/TB relay ladder remains the primary collision interlock. The powered test in §4 proved that the ladder alone blocks both S and T coils when both cam levers are BACK. This decision remains conditional on the **per-lane Stage-6b/G3 insertion-point proof** at every cutover; a failure is an abort/rollback, not a waiver. The firmware echo is only an unvalidated, default-off secondary diagnostic and is not the primary guard.

**Reads-with:** `phase8_metering_guide_harness_unknowns.md` (the measured record) · `phase8_trackB_controller_cutover_runbook.md` §3.4 + G3 · `phase8_lane21_harness_build_sheet.md` §2 · `scripts/generate_kicad_netlist_revD.py` `block_rail()` (the current board-side contract).

---

## 1. Cold-trace record (2026-06-27) and its powered correction

- Cold tracing located SC at C2A cavity U through the pink lead and found no independently landable TB cavity or isolated dry contact pair.
- **Cold continuity did not establish contact topology or danger polarity.** The apparent “series / closes-on-danger” interpretation was contaminated by relay-coil sneak paths and is superseded by the powered result in §4.
- **Powered ground truth controls:** SC and TB behave as **parallel closed-when-SAFE contacts** in the OEM ladder; either pressed lever permits the coil, and the danger/blocking state is **both levers BACK / both contacts open**.
- **U is also a common rail** (gripper/control common — it “rings to everything” cold, and PBZ shorts to U when pressed). It is not a dry interlock landing and must never be connected to the board’s VCC5 J_SAFE sense loop.
- **Cold continuity tracing remains invalid in this region:** locked-out beeps can travel through approximately 21 Ω relay-coil paths. Per-cam SA/SB/TA1/TA2 edge-to-angle capture remains a powered-session task.

## 2. What the Rev-D board expects, and the Candidate-C resolution

`block_rail()` (`generate_kicad_netlist_revD.py`) builds the relay-enable rail as:

```
VCC5 → J_SAFE1/2  ("TBSC loop"  — EXTERNAL dry NC series contact pair)
     → J_SAFE3/4  (Stop/CIS loop)
     → PMOS source → RAIL_EN
```

The J_SAFE1/2 leg requires an **external, electrically isolated (dry), normally-closed contact pair that opens on a table/sweep interference** — closed-when-safe, open-on-danger, floating with respect to machine power.

**As measured, no such pair exists anywhere on this machine:**

1. **No isolatable contacts.** TB never isolates; SC is reachable only on its N.O. wire at a node that doubles as a common rail. There is no dry NC pair to lift and land.
2. **No equivalent two-wire loop.** The powered result shows two parallel closed-when-safe contacts embedded in the OEM ladder, not an external floating pair that can be lifted onto J_SAFE1/2.
3. **Not dry.** The only observable is a node inside the **live 24 VAC ladder**. Landing the board's VCC5 sense loop there ties the 5 V logic domain into a live 24 VAC node — a board-killer and an isolation violation, independent of polarity.
4. **Unverifiable by the planned method.** Runbook 3.4's original "LOCKED OUT, confirm the NC loop by continuity" procedure cannot work: cold reads are poisoned by the ~21 Ω coil sneak paths.

An **unrecorded or improvised** J_SAFE1/2 jumper removes the board-side rail condition with no independent jumper detection and is forbidden. Candidate C is the sole exception: its keyed/labeled jumper is a controlled harness part, protection is deliberately delegated to the unchanged OEM ladder, and every lane must pass the live G3 S-and-T coil-drop proof. No other J_SAFE bridge is permitted.

## 3. Candidate designs (historical decision analysis)

The alternatives below are retained as the decision record. Candidate C was selected after the powered characterization in §4. Cold-trace topology/polarity assumptions in the rejected A/B analysis are historical and must not override the powered result.

### Candidate A — auxiliary contacts added at the SC/TB switches, feeding J_SAFE1/2

Add one auxiliary switch at each of the SC and TB cam followers — a second subminiature snap-action lever switch mounted to track the same lobe as the OEM switch — wired as a **dry series pair using the closed-when-outside-the-window throw**, landed on J_SAFE1/2. Fully isolated from the ladder; gives the board exactly the loop it was designed for.

- **Parts (per lane):** 2× subminiature SPDT lever microswitch (same form factor as the existing cam switches — Omron SS-5GL / D2F class, ~$3–8 ea), 2× mounting brackets (fab or bent sheet), hookup wire to J_SAFE1/2, hardware. **~$15–30/lane.**
- **Effort:** mechanical — bracket fab + mounting + lobe alignment at the machine, per lane. Est. **3–5 h for the first lane** (alignment iteration), ~2 h/lane after. Alignment verified against the powered window capture (§4).
- **Failure modes:**
  - *Alignment drift / window skew* — aux switch window offset from the OEM window → protection window narrowed or shifted. Mitigate: align against the powered capture; re-check at soak.
  - *Mechanical interference* — a badly mounted aux switch could foul the cam follower, i.e. **introduces a new failure mode into an OEM safety mechanism.** Mitigate: mount on independent bracket, never load the OEM lever.
  - *Contact/wire failure* → loop opens → **rail drops = fail-safe.** ✅
  - *Wrong throw wired* (closed-in-window) → loop open at rest, rail never arms → **loud, not silent.** ✅
- **Pros:** true independent hardware interlock; matches `block_rail()` unchanged; fail-safe in both dominant failure directions; testable locked-out (it's our own dry switch).
- **Cons:** the only candidate that touches the machine mechanically; per-lane fab labor across the fleet; alignment is a craft step.

### Candidate B — interposing relay sensing the interlock node

Sense the ladder's own interlock electrically and translate it to a dry contact: a small relay (or rectified-opto + relay) whose input is bridged across the interlock signal, with its output contact feeding J_SAFE1/2.

- **Parts (per lane):** 24 VAC-coil ice-cube relay (IDEC RH2B-UAC24 / Omron MY2 24 VAC, ~$10–15) + DIN socket (~$5), or a rectifier+opto front-end + small SSR; bridge-tap leads (bridge across, **never interrupt**, the ladder). **~$15–25/lane.**
- **Effort:** electrical only, ~**1–2 h/lane** — after powered characterization identifies a safe ladder observation point and polarity (U is a common rail and is not a valid dry landing).
- **Failure modes — the big one:**
  - Any design that energizes only on danger and uses an NC contact to open J_SAFE is not fail-safe: a **broken sensing coil, blown tap wire, or lost sensing supply reads as “safe,” leaving the loop closed.** Only the G3 machine-side test would catch it, and only at test time.
  - *B′ variant (partial rescue):* sense the **coil-side effect** instead — the motor-relay coil rail the interlock *removes* power from. That signal is present-when-safe → relay energized-when-safe → contact opens on either danger **or** sensor failure = fail-safe. But it senses "the ladder already dropped the coils," which overlaps candidate C's premise and is only meaningful if the sensed rail is upstream of the board's own contact.
  - *Wrong polarity chosen at install* → loop closed always → silent no-protection (same detection gap).
  - AC sensing needs filtering (half-cycle dropout chatter on the rail).
- **Pros:** no mechanical modification; single-point landing matches the measured single-node reality; cheap.
- **Cons:** simple form is **inherently not fail-safe** (danger-asserted signal); an active component in the safety path; entirely dependent on powered characterization; polarity mistakes are silent.

### Candidate C — documented + powered-verified reliance on the OEM ladder inside the coil circuits the board switches

The board never sources machine power — its motion relays close dry contacts in the existing 24 VAC coil circuits. The powered result proves the OEM ladder’s parallel safe contacts block both S and T coils when both contacts open. If the board contact is inserted without bypassing that ladder, OEM protection survives controller replacement: even a board command cannot energize a blocked coil. J_SAFE1/2 therefore gets a **documented, labeled jumper plug on the harness** (an engineered decision, not a field improvisation), and the rail's TB/SC condition is formally delegated to the OEM ladder.

- **Parts:** none (one labeled 2-pin jumper plug per lane).
- **Effort:** zero install; all the cost is **verification** — the §4 powered characterization must prove the premise *before cutover is scheduled*, and Stage 6b/7 must re-prove it live per lane (force the interlock into the danger state while the board commands S/T, body clear → **coil must drop even with the board contact closed**, both S and T).
- **Failure modes:**
  - **The premise was initially open and is now proven for lanes 21/22.** The §4 manual-command test showed the OEM ladder kills both coils independently of the brain. This does not waive the per-lane insertion-point proof.
  - **Depends on insertion point.** Whether the interlock is in series with the *specific* coil path the board switches depends on where the board contact lands relative to those contacts (C1 cavities per runbook §3.3) — again only determinable powered.
  - **Weakens the board's rail** from 6 AND-conditions to 5, and **normalizes the jumpered-J_SAFE pattern** the review flagged as the predictable escape. Mitigation: the jumper is a labeled harness part + the runbook G3 sub-test makes the machine-side interlock drop a hard gate every cutover.
  - Protection depends on OEM switches/wiring whose condition we don't control; no board-side observability of interlock health.
- **Pros:** zero new hardware, zero OEM modification, keeps the machine's own certified-by-decades protection primary; honest about where protection actually lives.
- **Cons:** unverifiable until powered; if it fails verification late, you're re-planning at the machine; permanent rail-condition delegation must be loudly documented (board silk says TBSC loop; harness says jumper).

## 4. Powered characterization session (OEM brain installed)

This prerequisite was run on 2026-07-07 under the staged, two-person live-work rules. Item 2 is complete and drove the Candidate-C decision; items 1 and 3 remain inputs to any future software echo and the final cam-window record:

1. **Node/tap behavior:** with the mechanism hand-rotated (powered, motors not commanded) into and out of the interference window, meter (LoZ) the relevant OEM ladder points and polarity. Feeds any future B′ or software-echo redesign; U remains an invalid dry landing.
2. **C's premise:** with the OEM brain still in place, establish whether forcing SC+TB into the danger state kills the S/T motor-relay coil rail via the **ladder alone** (upstream of / independent of the brain's outputs). This can and should be answered **before** cutover day.
3. **Window angles:** capture the actual SC/TB closure angles vs cam rotation. Feeds A's alignment target and the (separate-workstream) single-node software echo.

## 4-RESULTS — §4.2 MEASURED 2026-07-07 (Dylan, at the machine): **PREMISE TRUE — the ladder alone kills both motor coils**

Method: motors unplugged; meter (VAC, LoZ) clipped **across A1–A2** of each motor contactor coil; interlock forced by holding the SC + TB cam-switch levers; motion commanded from the **rear-panel manual S / T switches** (brain-independent path).

| Levers (SC+TB) | Manual S → S-contactor coil | Manual T → T-contactor coil |
|---|---|---|
| **both held BACK (off buttons)** | **0 VAC (0.07 VDC noise) — DEAD** | **0 VAC — DEAD** |
| both pressing buttons | 24 VAC — energized | 24 VAC — energized |
| one back, one pressed | 24 VAC — energized | 24 VAC — energized |
| switch off (control) | 0 V | — |

Findings locked by this session:
1. **Candidate C's premise is TRUE**: a manual (brain-bypassing) motion command is blocked by the ladder when both cams are in the blocking state — for **both S and T**. The OEM collision protection lives in the relay ladder and survives brain removal, **provided the board's contact lands in series with these same coil circuits** (§3-C insertion-point caveat → re-prove per lane at Stage 6b/G3 as already gated).
2. **Contact logic = parallel closed-when-SAFE:** coil dies only when **both** switches release; either one pressed keeps it alive. This is the OEM "TB + SC in PARALLEL" reconciled with the single measured node: two parallel safe-contacts, danger = both open.
3. **Actuation direction INVERTED vs the pre-session assumption:** the blocking/danger state = **levers held BACK (buttons released)**, i.e. on the cams the interference window presents as the follower dropping back, not being pressed. Any software echo / aux-switch design must use this polarity — and the powered cam-window capture (§4.3) should still confirm the lever-back↔in-window mapping on the rotating machine.
4. Bonus: **S and T motor-contactor coils = 24 VAC** (closes the 2026-06-01 "heavy-lug contactor coil V" straggler).

## 5. Final decision — Candidate C

**Candidate C is adopted.** The controlled jumper and OEM ladder are the released interlock architecture. Candidate A is the fallback only if a lane fails the Candidate-C insertion-point proof; Candidate B is rejected except as a newly reviewed fail-safe B′ design.

Rationale:

- **C first** because it's the only candidate where the protection is the OEM ladder itself — the mechanism that has guarded this machine for decades — with zero new parts and zero new failure modes *if* the premise holds. The premise is a single measurable fact (§4.2) answerable in one pre-cutover powered session; it is not a cutover-day gamble if the verification is done up front. The cost (rail drops from 6 to 5 conditions, documented jumper) is real but bounded, and the rewritten G3 gate forces the machine-side drop to be re-proven at every cutover regardless.
- **A second** because it's the only candidate that gives the board the loop it was actually designed for, and it fails safe in both dominant failure directions. It costs mechanical craft work per lane and adds a (mitigable) interference risk to an OEM safety mechanism — acceptable if C's premise fails, since at that point the machine has *no* surviving hardware interlock post-brain-removal and building one becomes mandatory, not optional.
- **B last** because its simple form is silently-not-fail-safe (a dead sensor reads "safe"), which is a worse property than either alternative for a collision interlock. B′ fixes the fail-safe direction but converges on C's premise anyway — at which point C is simpler.

The decision does not make cutover automatic. Every lane still must prove, with the board commanding S and then T, that forcing both cam levers BACK makes the corresponding contactor coil dead. Any energized coil is G3 FAIL → abort and rollback.

## 6. What changed alongside this doc (already done)

- **Runbook §3.4 rewritten** — powered truth is parallel closed-when-safe; no isolatable dry pair; cold trace invalidated by coil sneak paths; Candidate C is the decided landing.
- **Runbook Stage 6b + G3** — J_SAFE1/2 jumper forbidden as a way to pass G3 (except as the *documented outcome of candidate C*, in which case the machine-side coil-drop proof replaces the rail-drop proof); new sub-test: physically force the SC/TB interlock at the machine → motion permission must drop.
- **Primary guard:** the OEM ladder is the decided hardware interlock. Firmware/software echo logic remains default-off, unvalidated, and secondary; it must never be described as the only guard.
- **Separate workstream:** any software echo redesign must consume the powered topology/polarity and window-angle captures, and must not delay or weaken the per-lane G3 hardware proof.

## 7. Decision record

| date | decision | by | notes |
|---|---|---|---|
| 2026-07-06 | **OPEN** | — | doc created; §4 powered session not yet run |
| 2026-07-07 | **OPEN — premise PROVEN, C is now the live recommendation** | measurements: Dylan | §4.2 answered TRUE at the machine (see §4-RESULTS): ladder alone kills S+T coils on manual command, both-levers-back = danger. Remaining before formal C adoption: §4.3 window-angle capture + per-lane Stage-6b insertion-point proof. Dylan to record the formal pick here. |
| 2026-07-07 | **✅ DECIDED: CANDIDATE C** | **Dylan** | J_SAFE1-2 gets the **documented, labeled jumper plug** as an engineered harness part; TB/SC rail condition formally delegated to the OEM ladder (proven §4-RESULTS). Standing conditions of the decision: **per-lane Stage-6b/G3 machine-side coil-drop proof stays a hard gate** (force levers BACK while the board commands S/T → coil must die) · §4.3 window-angle capture at the powered session · harness build sheet implements the jumper (`phase8_lane21_harness_build_sheet.md`). |
